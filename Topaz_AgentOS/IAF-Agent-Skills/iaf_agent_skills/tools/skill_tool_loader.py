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
from typing import Any, Dict, List, Optional

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



STDOUT_CAP = 10 * 1024  # 10 KB max output returned to agent
DEFAULT_TIMEOUT = 30



def _parse_tool_spec(script_path: Path) -> Optional[SkillToolSpec]:
    """
    Parse ``TOOL_SPEC`` from *script_path* using the AST.

    Returns ``None`` if the file has no valid ``TOOL_SPEC`` dict or is missing
    required keys (``name``, ``description``, ``parameters``).
    """
    try:
        source = Path(script_path).read_text(encoding='utf-8')
        tree = ast.parse(source)
    except (SyntaxError, OSError) as exc:
        logger.debug(f"⚠️  skill_tool_loader: cannot parse {script_path}: {exc}")
        return None

    for node in ast.iter_child_nodes(tree):
        if not isinstance(node, ast.Assign):
            continue
        for target in node.targets:
            if isinstance(target, ast.Name) and target.id == "TOOL_SPEC":
                try:
                    value = ast.literal_eval(node.value)
                except (ValueError, TypeError):
                    logger.debug(f"⚠️  TOOL_SPEC in {script_path} is not a literal — skipped")
                    return None

                if not isinstance(value, dict):
                    return None
                if "name" not in value:
                    return None

                return SkillToolSpec(
                    name=value["name"],
                    description=value.get("description", ""),
                    parameters=value.get("parameters", {}),
                    timeout=value.get("timeout", DEFAULT_TIMEOUT),
                    script_path=Path(script_path),
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
    for pname, pdef in spec.parameters.items():
        py_type = _TYPE_MAP.get(pdef.get("type", "str"), str)
        desc = pdef.get("description", "")
        # Pydantic v2 field tuple: (type, FieldInfo)
        fields[pname] = (py_type, ...)  # required field

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


def _tool_env(agent_root: str | None) -> Dict[str, str]:
    env = {k: os.environ[k] for k in _TOOL_ENV_KEYS if k in os.environ}
    if agent_root:
        env["IAF_AGENT_ROOT"] = agent_root
    return env


def create_skill_tool(spec: SkillToolSpec, script_path: Path,
                      agent_root: str | None = None) -> StructuredTool:
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
        run_env = _tool_env(agent_root if run_cwd else None)

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


def load_skill_tools(skill_path: Path, agent_root: str | None = None) -> List[StructuredTool]:
    """
    Discover **and** create LangChain tools for the given skill folder.

    *agent_root* is threaded to each tool so its subprocess runs in the agent
    workspace (see ``create_skill_tool``).

    Returns an empty list if the skill has no ``tools/`` subfolder or no
    valid scripts.
    """
    specs = discover_skill_tools(skill_path)
    tools: List[StructuredTool] = []
    for spec in specs:
        try:
            t = create_skill_tool(spec, spec.script_path, agent_root=agent_root)
            tools.append(t)
            logger.debug(f"  🔧 Loaded skill tool: {spec.name} (timeout={spec.timeout}s)")
        except Exception as exc:
            logger.debug(f"  ⚠️  Failed to load skill tool '{spec.name}': {exc}")
    return tools
