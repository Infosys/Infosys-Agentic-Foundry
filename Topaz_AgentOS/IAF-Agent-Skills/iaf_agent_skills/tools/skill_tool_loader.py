"""
skill_tool_loader — Discover and load bundled Python tools from skill folders.

Each skill can contain a ``tools/`` subfolder with Python scripts.  Each script
that exposes a ``TOOL_SPEC`` dict at module level is wrapped as a LangChain
tool and injected into the agent's ReAct loop at runtime.

Script contract
---------------
* ``TOOL_SPEC`` — a module-level dict parsed via ``ast.literal_eval`` (never
  executed at discovery time).  Required keys: ``name``, ``description``,
  ``parameters``.  Optional: ``timeout`` (seconds, default 30).
* The script reads a JSON object from **stdin** and writes a JSON result to
  **stdout**.  Stderr is captured for diagnostics.

Folder layout::

    skills/
      invoice_processing_ap/
        SKILL.md
        tools/
          calculate_late_fee.py   ← has TOOL_SPEC + stdin/stdout contract
          __init__.py             ← ignored
"""

from __future__ import annotations

import ast
import json
import os
import subprocess
import sys
import textwrap
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Union

# Prevent child processes from popping a console window on Windows, where the
# server runs under console-less pythonw.exe. Evaluates to 0 (no-op) elsewhere.
_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)

from langchain_core.tools import StructuredTool
from pydantic import BaseModel, create_model

import logging
logger = logging.getLogger(__name__)



@dataclass
class SkillToolSpec:
    """Parsed TOOL_SPEC from a bundled Python script."""
    name: str
    description: str
    parameters: Dict[str, Dict[str, str]]  # {param_name: {type, description}}
    timeout: int = 30
    script_path: Optional[Path] = None
    required: Optional[List[str]] = None  # None => every declared param is required



STDOUT_CAP = 10 * 1024  # 10 KB max output returned to agent
DEFAULT_TIMEOUT = 30



def _normalize_parameters(raw: Any) -> "tuple[Dict[str, Dict[str, str]], Optional[List[str]]]":
    """
    Normalise a TOOL_SPEC parameters block into a ``(params, required)`` pair.

    Tolerates the three shapes custom tools are authored in:
      1. Flat mapping ``{param: {"type": ..., "description": ...}}``.
      2. The same value reached under the ``params`` / ``args`` aliases
         (the alias key is resolved by :func:`_parse_tool_spec`).
      3. JSON-Schema ``{"type": "object", "properties": {...}, "required": [...]}``.

    ``params`` always maps each name to a ``{"type", "description"}`` dict.
    ``required`` is the explicit required list (JSON-Schema shape) or ``None``
    (treat every declared parameter as required). Garbage shapes normalise to an
    empty params dict instead of raising — the old code crashed on these.
    """
    if not isinstance(raw, dict):
        return {}, None

    # JSON-Schema object shape: {"type": "object", "properties": {...}, "required": [...]}
    if raw.get("type") == "object" and isinstance(raw.get("properties"), dict):
        # In JSON-Schema an omitted `required` means NO property is required, so default
        # to [] here (not None — None means "all required", the legacy flat-mapping rule).
        required = raw.get("required", [])
        required = required if isinstance(required, list) else []
        params: Dict[str, Dict[str, str]] = {}
        for pname, pdef in raw["properties"].items():
            if isinstance(pdef, dict):
                params[str(pname)] = {
                    "type": pdef.get("type", "str"),
                    "description": pdef.get("description", ""),
                }
            else:
                params[str(pname)] = {"type": "str", "description": ""}
        return params, required

    # Flat mapping shape: {param: {type, description}} or {param: "description"}
    params = {}
    for pname, pdef in raw.items():
        if isinstance(pdef, dict):
            params[str(pname)] = {
                "type": pdef.get("type", "str"),
                "description": pdef.get("description", ""),
            }
        elif isinstance(pdef, str):
            params[str(pname)] = {"type": "str", "description": pdef}
        else:
            params[str(pname)] = {"type": "str", "description": ""}
    return params, None


def _parse_tool_spec(script_path: Path) -> Optional[SkillToolSpec]:
    """
    Parse ``TOOL_SPEC`` from *script_path* using the AST.

    Returns ``None`` if the file has no valid ``TOOL_SPEC`` dict or is missing
    the required ``name`` key.  Skips are logged at WARNING with the file path
    (they used to be silent / DEBUG, which hid real authoring mistakes).
    """
    try:
        source = Path(script_path).read_text(encoding='utf-8')
        tree = ast.parse(source)
    except (SyntaxError, OSError) as exc:
        logger.warning("skill_tool_loader: cannot parse %s: %s", script_path, exc)
        return None

    for node in ast.iter_child_nodes(tree):
        if not isinstance(node, ast.Assign):
            continue
        for target in node.targets:
            if isinstance(target, ast.Name) and target.id == "TOOL_SPEC":
                try:
                    value = ast.literal_eval(node.value)
                except (ValueError, TypeError):
                    logger.warning("skill_tool_loader: TOOL_SPEC in %s is not a literal — skipped", script_path)
                    return None

                if not isinstance(value, dict):
                    logger.warning("skill_tool_loader: TOOL_SPEC in %s is not a dict — skipped", script_path)
                    return None
                if "name" not in value:
                    logger.warning("skill_tool_loader: TOOL_SPEC in %s has no 'name' — skipped", script_path)
                    return None

                # Accept `parameters`, `params` or `args` as aliases for the
                # parameter block, then normalise whatever shape it is.
                raw_params = value.get("parameters")
                if raw_params is None:
                    raw_params = value.get("params")
                if raw_params is None:
                    raw_params = value.get("args", {})
                params, required = _normalize_parameters(raw_params)

                return SkillToolSpec(
                    name=value["name"],
                    description=value.get("description", ""),
                    parameters=params,
                    timeout=value.get("timeout", DEFAULT_TIMEOUT),
                    script_path=Path(script_path),
                    required=required,
                )
    return None



_TYPE_MAP = {
    "str": str,
    "string": str,
    "int": int,
    "integer": int,
    "float": float,
    "number": float,
    "bool": bool,
    "boolean": bool,
}


def _build_pydantic_model(spec: SkillToolSpec) -> type:
    """
    Build a dynamic Pydantic model from ``spec.parameters``.

    Every parameter becomes a ``str`` keyword argument (the subprocess receives
    JSON so types are preserved), but we annotate with the declared type so the
    LLM sees the correct schema.
    """
    fields: Dict[str, Any] = {}
    params = spec.parameters if isinstance(spec.parameters, dict) else {}
    required = spec.required
    for pname, pdef in params.items():
        # Tolerate a non-dict param definition (JSON-Schema leftovers, a bare
        # string, etc.) instead of crashing on ``pdef.get``.
        if isinstance(pdef, dict):
            type_name = pdef.get("type", "str")
        elif isinstance(pdef, str):
            type_name = pdef
        else:
            type_name = "str"
        py_type = _TYPE_MAP.get(type_name, str)
        # Honour an explicit `required` list when the spec carried one; without
        # it, every declared parameter stays required (legacy behaviour).
        if required is None or pname in required:
            fields[pname] = (py_type, ...)          # required field
        else:
            fields[pname] = (Optional[py_type], None)  # optional field

    if not fields:
        # Tool with no parameters — accept an empty object
        fields["_no_params"] = (str, "")  # optional dummy

    model = create_model(f"{spec.name}_Input", **fields)
    return model



# Allowlist only: server secrets (JWT, DB, API keys) must not reach tool scripts.
_TOOL_ENV_KEYS = (
    "PATH", "PATHEXT", "SYSTEMROOT", "SystemRoot", "COMSPEC", "WINDIR",
    "HOME", "USERPROFILE", "TEMP", "TMP", "TMPDIR", "LANG", "LC_ALL", "LC_CTYPE",
    "PYTHONPATH", "PYTHONHOME", "VIRTUAL_ENV", "CONDA_PREFIX", "PYTHONIOENCODING",
    "HTTP_PROXY", "HTTPS_PROXY", "NO_PROXY", "http_proxy", "https_proxy", "no_proxy",
    "REQUESTS_CA_BUNDLE", "SSL_CERT_FILE",
)


EnvExtra = Union[Dict[str, str], Callable[[], Dict[str, str]], None]


def _tool_env(agent_root: str | None, extra: Dict[str, str] | None = None) -> Dict[str, str]:
    env = {k: os.environ[k] for k in _TOOL_ENV_KEYS if k in os.environ}
    if agent_root:
        env["IAF_AGENT_ROOT"] = agent_root
    # Per-call context the agent computes for THIS caller (e.g. which graphs they may not
    # read). Only IAF_-prefixed keys are accepted so this can never inject PATH/PYTHONPATH.
    for k, v in (extra or {}).items():
        if isinstance(k, str) and k.startswith("IAF_") and k != "IAF_AGENT_ROOT" and isinstance(v, str):
            env[k] = v
    return env


def create_skill_tool(spec: SkillToolSpec, script_path: Path,
                      agent_root: str | None = None,
                      env_extra: EnvExtra = None) -> StructuredTool:
    """
    Create a LangChain ``StructuredTool`` that executes *script_path* in a
    subprocess, passing parameters as JSON on stdin and capturing JSON from
    stdout.

    When *agent_root* is provided the subprocess runs with that directory as its
    cwd and ``IAF_AGENT_ROOT`` set in its environment — so bundled tools resolve
    ``workspace/tmp/...`` to the agent workspace exactly like shell tools do.
    Without it the tool would inherit the server's cwd and fail to find files
    the agent wrote earlier in the turn.
    """
    input_model = _build_pydantic_model(spec)
    timeout = spec.timeout or DEFAULT_TIMEOUT

    def _run_tool(**kwargs) -> str:
        # Remove dummy param if present
        kwargs.pop("_no_params", None)
        payload = json.dumps(kwargs)

        run_cwd = agent_root if (agent_root and os.path.isdir(agent_root)) else None
        try:
            # A callable is re-evaluated on every run, so per-caller context (e.g. which graphs
            # were denied) reflects the caller's access NOW, not when the tool was loaded.
            extra = env_extra() if callable(env_extra) else env_extra
        except Exception as exc:
            logger.warning("skill tool '%s': per-caller context unavailable (%s); not running", spec.name, exc)
            return json.dumps({"error": f"Tool '{spec.name}' could not be authorised for this call"})
        run_env = _tool_env(agent_root if run_cwd else None, extra)

        try:
            proc = subprocess.run(
                [sys.executable, str(script_path)],
                input=payload,
                capture_output=True,
                text=True,
                timeout=timeout,
                creationflags=_NO_WINDOW,
                cwd=run_cwd,
                env=run_env,
            )
        except subprocess.TimeoutExpired:
            return json.dumps({"error": f"Tool '{spec.name}' timed out after {timeout}s"})
        except Exception as exc:
            return json.dumps({"error": f"Tool '{spec.name}' failed to start: {exc}"})

        if proc.returncode != 0:
            stderr_preview = (proc.stderr or "")[:500]
            return json.dumps({
                "error": f"Tool '{spec.name}' exited with code {proc.returncode}",
                "stderr": stderr_preview,
            })

        stdout = proc.stdout or ""
        if len(stdout) > STDOUT_CAP:
            stdout = stdout[:STDOUT_CAP] + "\n... [output truncated at 10KB]"

        return stdout

    return StructuredTool.from_function(
        func=_run_tool,
        name=spec.name,
        description=spec.description,
        args_schema=input_model,
    )



def discover_skill_tools(skill_path: Path) -> List[SkillToolSpec]:
    """
    Scan ``skill_path/tools/*.py`` and return a list of parsed
    ``SkillToolSpec`` objects (no LangChain tools created yet).

    Ignores ``__init__.py`` and scripts without a valid ``TOOL_SPEC``.
    """
    tools_dir = Path(skill_path) / "tools"
    if not tools_dir.is_dir():
        return []

    specs: List[SkillToolSpec] = []
    for py_file in sorted(tools_dir.glob("*.py")):
        if py_file.name.startswith("__"):
            continue
        spec = _parse_tool_spec(py_file)
        if spec is not None:
            specs.append(spec)
    return specs


def load_skill_tools(skill_path: Path, agent_root: str | None = None,
                     env_extra: EnvExtra = None) -> List[StructuredTool]:
    """
    Discover **and** create LangChain tools for the given skill folder.

    *agent_root* is threaded to each tool so its subprocess runs in the agent
    workspace (see ``create_skill_tool``). *env_extra* (``IAF_*`` keys only, or a callable
    returning them, evaluated per run) adds per-caller context to each tool's environment.

    Returns an empty list if the skill has no ``tools/`` subfolder or no
    valid scripts.
    """
    specs = discover_skill_tools(skill_path)
    tools: List[StructuredTool] = []
    for spec in specs:
        try:
            t = create_skill_tool(spec, spec.script_path, agent_root=agent_root, env_extra=env_extra)
            tools.append(t)
            logger.debug(f"  🔧 Loaded skill tool: {spec.name} (timeout={spec.timeout}s)")
        except Exception as exc:
            logger.warning("skill_tool_loader: failed to load skill tool '%s' from %s: %s",
                           spec.name, getattr(spec, "script_path", "?"), exc)
    return tools
