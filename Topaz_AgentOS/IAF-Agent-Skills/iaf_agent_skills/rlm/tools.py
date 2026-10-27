"""Governed tool wrappers for the RLM execution_mode (Phase 3 v1).

Every wrapper routes a call through the host's `govern_tool_call` firewall (PreToolUse hooks,
policy, write/dangerous gate, HITL) BEFORE executing the underlying tool. Only these governed
wrappers are injected into the RLM's restricted namespace — never a raw tool — so a side effect
cannot bypass governance. Read tools execute inline; side-effecting *intent* is recorded via
`propose_action` and applied at a governed boundary by the caller (propose-then-apply).
"""
from __future__ import annotations

import json
import logging
import os
import urllib.request
import uuid
from typing import Any, Callable

from ..tool_governance import govern_tool_call

logger = logging.getLogger(__name__)


def govern_and_run(agent: Any, name: str, args: dict, exec_fn: Callable[[], Any]) -> str:
    """Route one tool call through governance; execute `exec_fn` only if allowed.
    Returns a string result (blocked/pending are surfaced, never executed)."""
    tool_call = {"id": f"rlm-{uuid.uuid4().hex[:8]}", "name": name, "args": args}
    decision = govern_tool_call(agent, tool_call, source="rlm_repl")
    if getattr(decision, "allowed", False):
        try:
            return str(exec_fn())
        except Exception as e:  # tool failures are returned, not raised, so the RLM can adapt
            logger.error("RLM tool %s failed: %s", name, e)
            return f"[{name} error: {e}]"
    status = getattr(decision, "status", "blocked")
    reason = getattr(decision, "reason", "") or ""
    if status in ("pending", "already_pending"):
        return (f"[{name} requires human approval — NOT executed in this RLM turn. "
                f"Use propose_action(...) for side-effecting steps. reason: {reason}]")
    return f"[{name} blocked by governance: {reason}]"


def build_rlm_tools(agent: Any) -> tuple[dict, str, list]:
    """Build governed tools for the RLM namespace.

    Returns (tools, tools_prompt, proposed_actions):
      - tools: {name: callable} governed wrappers to inject into the engine.
      - tools_prompt: ROOT_SYSTEM lines describing them.
      - proposed_actions: list the model appends to via propose_action(); the caller applies them.
    """
    tools: dict[str, Callable] = {}
    lines: list[str] = []
    proposed: list[dict] = []
    # YAML list here would let a skill expose a tool the caller's policy denies. Fail closed.
    allowed = set(agent._get_allowed_tools())

    if "run_sql_query" in allowed:
        try:
            _prev = getattr(agent, "_sql_write_allowed", False)
            agent._sql_write_allowed = False          # force read-only for the RLM
            sql_tool = agent._create_sql_tool()
            agent._sql_write_allowed = _prev           # restore (tool already captured read-only)
        except Exception as e:
            logger.warning("RLM run_sql_query wrapper unavailable: %s", e)
            sql_tool = None
        if sql_tool is not None:
            def run_sql_query(query: str, database: str = "") -> str:
                return govern_and_run(
                    agent, "run_sql_query", {"query": query, "database": database or None},
                    lambda: sql_tool.func(query=query, database=(database or None)))
            tools["run_sql_query"] = run_sql_query
            lines.append("- run_sql_query(query: str, database: str='') -> str : run a READ-ONLY SQL "
                         "query (governed).")

    if "invoke_skill" in allowed:
        try:
            from ..tool_factory import MAX_INVOKE_DEPTH
            if getattr(agent, "_invoke_depth", 0) < MAX_INVOKE_DEPTH:
                skill_tool = agent.tool_provider.create_invoke_skill_tool(
                    router=agent.router,
                    agent_factory_fn=agent._rlm_child_agent_factory,
                    current_depth=getattr(agent, "_invoke_depth", 0),
                )
            else:
                skill_tool = None
        except Exception as e:
            logger.warning("RLM invoke_skill wrapper unavailable: %s", e)
            skill_tool = None
        if skill_tool is not None:
            def invoke_skill(task: str, context: str = "", target_skill: str = "") -> str:
                return govern_and_run(
                    agent, "invoke_skill",
                    {"task": task, "context": context, "target_skill": target_skill},
                    lambda: skill_tool.func(task=task, context=context, target_skill=target_skill))
            tools["invoke_skill"] = invoke_skill
            lines.append("- invoke_skill(task: str, context: str='', target_skill: str='') -> str : "
                         "delegate a sub-task to another governed skill (read/analysis).")

    _cfg = getattr(agent, "_rlm_cfg", {}) or {}

    docs_dir = _cfg.get("docs_dir")
    if "read_document" in allowed and docs_dir:
        # realpath the root so containment is enforced against resolved symlinks.
        docs_root = os.path.realpath(os.path.expanduser(str(docs_dir)))

        def read_document(name: str) -> str:
            # Resolve symlinks on the target too: an abspath-only check lets a symlink
            # inside docs_root point outside it and still pass the prefix test.
            target = os.path.realpath(os.path.join(docs_root, str(name)))
            if target != docs_root and not target.startswith(docs_root + os.sep):
                return "[read_document blocked: path escapes the docs directory]"

            def _do():
                if not os.path.isfile(target):
                    return f"[document not found: {name}]"
                with open(target, encoding="utf-8", errors="ignore") as fh:
                    return fh.read()[:8000]
            return govern_and_run(agent, "read_document", {"name": name, "path": target}, _do)

        tools["read_document"] = read_document
        _desc = "- read_document(name: str) -> str : read a document by filename from the docs library (governed)."
        try:
            _avail = [f for f in sorted(os.listdir(docs_root)) if f.endswith((".md", ".txt"))]
            if _avail:
                _desc += "\n    available documents: " + ", ".join(_avail)
        except Exception:
            pass
        lines.append(_desc)

    creds_file = _cfg.get("creds_file")
    if "http_get" in allowed and creds_file:
        creds_path = os.path.abspath(os.path.expanduser(str(creds_file)))

        def http_get(path: str) -> str:
            def _do():
                with open(creds_path, encoding="utf-8") as fh:
                    creds = json.load(fh)
                api = creds.get("invoice_api", creds) if isinstance(creds, dict) else {}
                base = str(api.get("base_url", "")).rstrip("/")
                key = str(api.get("api_key", ""))
                if not base:
                    return "[http_get error: no base_url in credentials]"
                url = base + "/" + str(path).lstrip("/")
                req = urllib.request.Request(url, headers={"X-API-Key": key})
                with urllib.request.urlopen(req, timeout=15) as resp:
                    return resp.read().decode("utf-8", "ignore")[:8000]
            return govern_and_run(agent, "http_get", {"path": path}, _do)

        tools["http_get"] = http_get
        lines.append("- http_get(path: str) -> str : GET the demo API at <base>/<path> using the API key "
                     "from the credentials file (read server-side; governed). e.g. http_get('/invoices/INV-9001').")

    def propose_action(kind: str, args: str = "", rationale: str = "") -> str:
        proposed.append({"kind": str(kind), "args": str(args), "rationale": str(rationale)})
        return f"[proposed action #{len(proposed)} recorded: {kind} — will be governed + applied after FINAL]"
    tools["propose_action"] = propose_action
    lines.append("- propose_action(kind: str, args: str='', rationale: str='') -> str : for any "
                 "SIDE-EFFECTING action, RECORD it (do NOT try to execute side effects directly); "
                 "recorded actions are governed and applied after you FINAL.")

    tools_prompt = "".join(line + "\n" for line in lines)
    return tools, tools_prompt, proposed
