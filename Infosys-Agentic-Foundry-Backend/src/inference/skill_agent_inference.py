# © 2024-25 Infosys Limited, Bangalore, India. All Rights Reserved.
"""
SkillAgentInference — LangGraph-based inference for skill_agent type.

Plugs into the standard IAF inference pipeline (POST /chat/inference) so
the UI treats a skill-based agent just like any react_agent.

Workflow:
    START → generate_past_conversation_summary → skill_executor → final_response → [formatter] → END

The skill_executor node:
    1. Loads the skill folder from disk (SKILL.md files)
    2. Routes the query (keyword → default) via SkillRouter
    3. Builds a system prompt from skill + enterprise context
    4. Calls the LLM and returns the result as standard executor_messages
"""

import os
import re
import json
import asyncio
import threading
from pathlib import Path
from typing import Dict, List, Optional, Any, TypedDict, Annotated
from copy import deepcopy

from langgraph.graph import StateGraph, START, END
from langgraph.types import StreamWriter, interrupt, Command
from langchain_core.messages import AIMessage, HumanMessage, ChatMessage, AnyMessage, SystemMessage, ToolMessage

from src.inference.inference_utils import InferenceUtils
from src.inference.base_agent_inference import BaseWorkflowState, BaseAgentInference
from src.schemas import AdminConfigLimits
from src.utils.helper_functions import get_timestamp
from src.config.constants import AgentType
from src.agentos.skill_tools import create_skill_tools, get_directory_tree
from src.agentos.llm_tracker import (
    start_budget, end_budget, record as llm_record,
    LLMTokenTracker, format_budget_summary,
)
from src.agentos.hook_runner import create_default_hooks, ToolBlockedError, HookResult
from src.agentos.knowledge_store import KnowledgeStore, EpisodeEntry
from src.agentos.plan_cache import PlanCache, CachedPlan
from src.agentos.session_store import SessionStore, SessionSnapshot
from src.agentos.prompt_budget import PromptBudget
from src.agentos.request_audit import RequestAuditTrail

from telemetry_wrapper import logger as log, update_session_context

# ---------------------------------------------------------------------------
# Module-level singletons for expensive-to-init services.
# These survive across requests (avoid CREATE TABLE IF NOT EXISTS on every call).
# Thread lock prevents race conditions when two requests arrive simultaneously
# on a fresh server and both try to initialize the singletons.
# ---------------------------------------------------------------------------
_singleton_lock = threading.Lock()
_knowledge_store_singleton: KnowledgeStore | None = None
_plan_cache_singleton: PlanCache | None = None
_session_store_singleton: SessionStore | None = None

# ---------------------------------------------------------------------------
# Agent-dir resolution cache (Fix #11).
# Maps agent_id → (resolved_path, timestamp).  Avoids scanning all
# department folders on every request.  Entries expire after
# _AGENT_DIR_CACHE_TTL seconds so new agents / moves are picked up.
# ---------------------------------------------------------------------------
import time as _time
_agent_dir_cache: Dict[str, tuple] = {}            # agent_id → (Path, float)
_agent_dir_cache_lock = threading.Lock()
_AGENT_DIR_CACHE_TTL = float(os.getenv("AGENT_DIR_CACHE_TTL", "300"))  # 5 min


# ---------------------------------------------------------------------------
# Workflow State
# ---------------------------------------------------------------------------

class SkillWorkflowState(BaseWorkflowState):
    """State for the skill-based agent workflow."""
    preference: str = ""
    skill_name: str = ""
    skill_description: str = ""
    routing_method: str = ""
    routing_confidence: float = 0.0
    system_prompt_text: str = ""
    execution_mode: Optional[str] = None  # User-selected execution mode (from API request)
    # Tool interruption fields (mirrors ReactWorkflowState)
    tool_feedback: str = None
    is_tool_interrupted: bool = False
    tool_result: str = None
    # Persisted react-loop context for resuming after tool interrupt
    _pending_tool_call: str = ""       # JSON: {name, args, id} of tool awaiting approval
    _react_invoke_messages: str = ""   # JSON-serialized invoke_messages list
    _react_messages: str = ""          # JSON-serialized react_messages list
    _react_iteration: int = 0           # Current loop iteration
    # Interrupt type metadata (propagated to _enrich_interrupted_response)
    _interrupt_type: str = ""           # "tool_interrupt" | "hook_approval" | "skill_interrupt"
    _interrupt_reason: str = ""         # Human-readable reason for the interrupt
    # Skill verification fields (human-in-the-loop skill routing approval)
    is_skill_interrupted: bool = False
    skill_feedback: str = None          # "approve"/"reject"/<skill_name>
    _skill_verifier_data: str = ""      # JSON: {selected_skill, available_skills, routing_method, routing_confidence}
    # Planned mode fields (plan confirmation / modification via chat)
    _pending_plan: str = ""             # JSON: serialized ExecutionPlan dict awaiting user confirmation
    _pending_plan_skill: str = ""       # Which skill triggered the plan (for re-routing on confirm)


class _ToolInterruptSignal(Exception):
    """Raised inside _run_skill_react_loop when a tool needs HITL approval.

    Carries all the context needed to persist the loop state and resume later.

    interrupt_type:
        "tool_interrupt"      — standard HITL tool verification (user can approve, modify args, or reject)
        "hook_approval"       — hook script requested approval via exit code 2 (approve/reject only)
    """
    def __init__(self, tool_call: dict, invoke_messages: list, react_messages: list, iteration: int,
                 interrupt_type: str = "tool_interrupt", reason: str = ""):
        self.tool_call = tool_call
        self.invoke_messages = invoke_messages
        self.react_messages = react_messages
        self.iteration = iteration
        self.interrupt_type = interrupt_type
        self.reason = reason
        super().__init__(f"Tool interrupt ({interrupt_type}): {tool_call.get('name', '?')}")


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

AGENT_WORKSPACES_BASE = os.getenv("AGENT_WORKSPACES_BASE", "./agent_workspaces")
AGENTOS_FOLDER_NAME = "agentos_agents"


# ---------------------------------------------------------------------------
# Inference Class
# ---------------------------------------------------------------------------

class SkillAgentInference(BaseAgentInference):
    """
    Implements the LangGraph workflow for 'skill_agent' type.

    Reads skills from disk (SKILL.md etc.), routes the query to the
    best-matching skill, builds a prompt from the .md files plus
    enterprise context, calls the LLM, and returns standard
    executor_messages that the UI can render.
    """

    def __init__(self, inference_utils: InferenceUtils):
        super().__init__(inference_utils)

    # ------------------------------------------------------------------
    # Helpers — resolve skill folder paths
    # ------------------------------------------------------------------

    @staticmethod
    def _resolve_agent_dir(agent_id: str, department: Optional[str] = None) -> Path:
        """Find the agent's folder on disk (cached with TTL).

        First checks a module-level TTL cache to avoid scanning department
        folders on every request.  Cache entries expire after
        ``AGENT_DIR_CACHE_TTL`` seconds (default 300 s / 5 min).
        """
        now = _time.monotonic()

        # --- Fast path: cache hit ---
        with _agent_dir_cache_lock:
            entry = _agent_dir_cache.get(agent_id)
            if entry is not None:
                cached_path, ts = entry
                if now - ts < _AGENT_DIR_CACHE_TTL:
                    return cached_path

        # --- Slow path: scan departments ---
        resolved: Optional[Path] = None

        # Fix #7 — validate department and agent_id to prevent path traversal
        _unsafe = lambda s: s and (".." in s or "/" in s or "\\" in s)
        if _unsafe(department) or _unsafe(agent_id):
            raise ValueError(f"Invalid department or agent_id (path traversal detected)")

        if department:
            candidate = Path(AGENT_WORKSPACES_BASE) / department / AGENTOS_FOLDER_NAME / agent_id
            if candidate.exists():
                resolved = candidate

        if resolved is None:
            base = Path(AGENT_WORKSPACES_BASE)
            if base.exists():
                for dept_dir in base.iterdir():
                    if dept_dir.is_dir() and not dept_dir.name.startswith("_"):
                        candidate = dept_dir / AGENTOS_FOLDER_NAME / agent_id
                        if candidate.exists():
                            resolved = candidate
                            break

        if resolved is None:
            # Fallback
            resolved = Path(AGENT_WORKSPACES_BASE) / "General" / AGENTOS_FOLDER_NAME / agent_id

        # --- Store in cache ---
        with _agent_dir_cache_lock:
            _agent_dir_cache[agent_id] = (resolved, now)

        return resolved

    # ------------------------------------------------------------------
    # Extracted helpers (Issue #14 — break up the god function)
    # ------------------------------------------------------------------

    @staticmethod
    def _build_skill_section(sname: str, label: str, skill_loader) -> str:
        """Build a metadata prompt section for one skill.

        Includes DB connection info (schema/example paths) when the
        skill declares ``databases`` entries in SKILL.md so that the
        agent knows HOW to query — but only after reading the skill.
        Does NOT embed SKILL.md body — the agent must read it via
        ``run_shell_command(command="cat /skills/{sname}/SKILL.md")`` at runtime.
        """
        sk = skill_loader.load(sname)
        if not sk:
            return f"\n## {label}: {sname}\n\n_Skill not found._\n"

        section = f"\n## {label}: {sname}\n"
        section += f"- **Description**: {sk.description or 'N/A'}\n"
        if sk.triggers:
            section += f"- **Keywords**: {', '.join(str(t) for t in sk.triggers)}\n"

        # List ALL files the agent should/can read
        skill_dir = Path(sk.folder_path) if sk.folder_path else None
        if skill_dir and skill_dir.exists():
            all_files = [
                f.name for f in skill_dir.iterdir()
                if f.is_file()
                   and f.suffix.lower() in (".md", ".yaml", ".yml", ".txt", ".json")
            ]
            if all_files:
                section += f"- **Files**: "
                section += ", ".join(f'`/skills/{sname}/{fn}`' for fn in sorted(all_files))
                section += "\n"

        # --- Database connections declared by this skill ---
        if sk.databases:
            section += "\n### Database Connections for this skill\n"
            section += "**You MUST read the SKILL.md above first** — it contains the workflow, business rules, and query patterns for these databases.\n"
            for db_entry in sk.databases:
                conn = db_entry.get("connection_name", "unknown")
                mode = db_entry.get("sql_mode", "read_only")
                section += f"\n**Connection: `{conn}`** (mode: {mode})\n"
                section += f"- Schema: `run_shell_command(command=\"cat /databases/{conn}/schema.md\")`\n"
                section += f"- Examples (fallback): `run_shell_command(command=\"cat /databases/{conn}/samples.md\")`\n"
                section += f"- Execute queries: `database_query_tool(connection_name=\"{conn}\", query=\"SELECT ...\", limit=100)`\n"
            section += "\n⚠️ **Do NOT call these tools until you have read the SKILL.md file.** The skill file tells you WHAT to query and WHEN.\n"

        return section

    @staticmethod
    def _build_skill_system_prompt(
        *,
        skills_section: str,
        read_instructions: str,
        multi_skill_note: str,
        other_skills_text: str,
        low_confidence_fallback: str,
        enterprise_context_text: str,
        preference: str,
        has_shell: bool,
        db_connection_names: List[str],
        additional_mounts_info: str = "",
    ) -> str:
        """Assemble the full system prompt for the skill executor.

        Kept as a static method so it can be unit-tested without I/O.
        """
        system_prompt = f"""You are a skill-based AI assistant. Your knowledge comes from skill files that you MUST read before answering.

## Enterprise Context
{enterprise_context_text if enterprise_context_text else "No enterprise context available."}
{skills_section}
{read_instructions}
{multi_skill_note}
{other_skills_text}
{low_confidence_fallback}
## Execution Rules
1. **ABSOLUTE GATE — Read SKILL.md BEFORE anything else.** You MUST call `run_shell_command(command="cat /skills/<skill_name>/SKILL.md")` as your FIRST action. NEVER call `database_query_tool`, `execute_python_code`, or any other tool until you have read the relevant SKILL.md. The skill file is your single source of truth.
2. **Read INSTRUCTIONS.md next** (only if listed in Files above) using `run_shell_command(command="cat /skills/<skill_name>/INSTRUCTIONS.md")`.
3. **Read EXAMPLES.md only if needed** — when you are unsure how to respond or the query is ambiguous.
4. **Follow the skill file's instructions exactly.** Use the tools it prescribes (database_query_tool, run_shell_command for DB schema, etc.) following the workflow described in the skill.
5. If the skill references companion files (e.g., credentials.md), read them via `run_shell_command(command="cat /skills/<skill_name>/<file>")`.
6. **Do NOT call `ls` or `grep` on /skills/ unless you need to discover unknown files.** The skill names, file paths, and DB connections are already listed above — use them directly with `cat`.
7. When you need to make HTTP API calls, use `execute_python_code` with the `requests` library. **Actually execute the code — do NOT just describe it.**
8. After getting real data from API calls or DB queries, present the actual results to the user.
9. **Reading binary/complex files (PDF, Excel, DOCX, PPTX, images):** Use `run_shell_command(command="readfile /mount_name/file.pdf")`. The `readfile` command extracts readable text from PDF, Excel, DOCX, PPTX, CSV, JSON, YAML, Parquet, images, and all common formats. If you only know the filename, just use `readfile report.pdf` — it auto-discovers the file across all mounts.
   Example: `run_shell_command(command="readfile department_budgets.pdf")`
10. **File paths in `execute_python_code`:** When writing Python code that reads files (pandas, open(), etc.), NEVER use raw virtual paths like `/motiva_demo/file.csv` or `/mnt/...`. Instead, use the built-in `resolve_path()` function to translate virtual mount paths to real filesystem paths:
   ```python
   import pandas as pd
   df = pd.read_csv(resolve_path('/motiva_demo/inventory.csv'))
   ```
   Also available: `read_file_from_mount('/motiva_demo/file.pdf')` for text extraction and `list_files_in_mount('/motiva_demo/')` to list directory contents.
11. Respond in markdown format.
{f'12. Follow these preferences: {preference}' if preference else ""}
"""

        if has_shell:
            # Compute mount count dynamically (6 built-in + additional)
            _additional_mount_lines = ""
            _mount_count = 6
            if additional_mounts_info:
                _additional_mount_lines = "\n" + additional_mounts_info
                # Count additional mounts by counting lines starting with "- `/"
                _mount_count = 6 + sum(
                    1 for line in additional_mounts_info.strip().splitlines()
                    if line.strip().startswith("- `/")
                )

            system_prompt += f"""

## File-Based Memory & Knowledge (run_shell_command)
You have a virtual filesystem via `run_shell_command` with {_mount_count} mount points:
- `/skills/` — Skill knowledge files (READ-ONLY)
- `/enterprise_context/` — Enterprise policies (READ-ONLY)
- `/databases/` — DB schema.md and samples.md (READ-ONLY)
- `/user/facts/` — User-scoped persistent storage
- `/agent/facts/` — Agent-scoped persistent storage
- `/session/workspace/` — Session scratch space
- `/session/conversations/` — Session logs (read-only){_additional_mount_lines}

### Key Commands:
- `cat /path/file` — Read file | `stat /file` — Check size first
- `grep -rC3 "pattern" /` — Search all mounts | `semgrep "concept" /` — Semantic search
- `find / -iname "*.md"` — Find files | `tree --size /path` — Directory overview
- `sed -n '10,20p' /file` — Read line range | `head -n N` / `tail -n N`
- `diff /f1 /f2` — Compare | `wc /path/*.md` — Count lines
- `echo "data" > /agent/facts/key.md` — Store facts
- `readfile report.pdf` — Extract text from binary files (PDF, Excel, DOCX, images)
- Pipes supported: `grep "x" file | head -5`

### Rules:
1. **Read SKILL.md FIRST** via `cat /skills/<name>/SKILL.md` before any other action.
2. Read schema.md before SQL queries.
3. Use `stat` before reading large files; use `sed -n` for chunked reads.
4. For file paths in `execute_python_code`, use `resolve_path('/mount/file')`.
"""

        if db_connection_names:
            connections_list = ", ".join(db_connection_names)
            system_prompt += f"""

## Database Tools Available
You have `database_query_tool` and `run_shell_command` available for database connections: [{connections_list}].
**Use them only when a skill file (SKILL.md) instructs you to query a database.**
The skill file contains the workflow, schema paths, example paths, and query patterns — read it first.
"""
            log.info(f"[SkillAgent] Minimal DB note added to system prompt for connections: {db_connection_names}")

        return system_prompt

    # ------------------------------------------------------------------
    # Extracted helpers (Issue #H6 — break up the god function further)
    # ------------------------------------------------------------------

    @staticmethod
    async def _inject_knowledge_context(
        system_prompt: str,
        knowledge_store,
        agent_id: str,
        query: str,
    ) -> str:
        """Append Knowledge Store context to the system prompt if available."""
        if not knowledge_store:
            return system_prompt
        try:
            knowledge_context = await knowledge_store.build_knowledge_context(
                agent_id=agent_id,
                query=query,
                max_items=5,
            )
            if knowledge_context:
                system_prompt += f"\n{knowledge_context}\n"
                log.debug("[SkillAgent] Knowledge context injected into system prompt")
        except Exception as e:
            log.debug(f"[SkillAgent] Knowledge context injection skipped: {e}")
        return system_prompt

    @staticmethod
    async def _inject_user_info(system_prompt: str) -> str:
        """Append current user information to the system prompt if available."""
        try:
            from src.utils.secrets_handler import current_user_email
            _user_email = current_user_email.get(None)
            if _user_email:
                try:
                    from src.api.dependencies import ServiceProvider
                    _auth_service = ServiceProvider.get_auth_service()
                    _user_data = await _auth_service.user_repo.get_user_by_email(_user_email)
                    if _user_data:
                        system_prompt += (
                            f"\n## Current User Information\n"
                            f"You are currently assisting the following user:\n"
                            f"- **Email:** {_user_data.get('mail_id', _user_email)}\n"
                            f"- **Name:** {_user_data.get('user_name', 'Unknown')}\n"
                            f"- **Role:** {_user_data.get('role', 'User')}\n\n"
                            f"Please personalize your responses appropriately. "
                            f"Always greet the user by their Name.\n"
                        )
                    else:
                        system_prompt += f"\n## Current User Information\nYou are currently assisting: {_user_email}\n"
                except Exception:
                    system_prompt += f"\n## Current User Information\nYou are currently assisting: {_user_email}\n"
                log.debug(f"[SkillAgent] User info injected for: {_user_email}")
        except Exception as e:
            log.debug(f"[SkillAgent] User info injection skipped: {e}")
        return system_prompt

    async def _run_skill_react_loop(
        self,
        *,
        llm,
        tools: list,
        tool_map: dict,
        system_prompt: str,
        user_message: str,
        writer: StreamWriter,
        state: dict,
        hook_runner,
        llm_tracker_callback,
        tool_interrupt_flag: bool,
        max_iterations: int = 15,
        audit: Optional[RequestAuditTrail] = None,
        skill_name: str = "",
        resume_invoke_messages: list = None,
        resume_react_messages: list = None,
        resume_pending_tool: dict = None,
        resume_iteration: int = 0,
        skip_post_tool_hooks_on_resume: bool = False,
    ) -> tuple:
        """Execute the ReAct tool-calling loop.

        Returns ``(response_content, react_messages, errors)``
        where *react_messages* is the list of AI/Tool messages collected.

        Raises ``_ToolInterruptSignal`` when a tool needs HITL approval
        so that the caller (skill_executor node) can persist state and
        let the graph route to the tool_interrupt_node.
        """
        import time as _time

        errors: List[str] = []
        llm_with_tools = llm.bind_tools(tools)

        # --- Resume from saved state (after tool interrupt approval) ---
        if resume_invoke_messages is not None:
            invoke_messages = resume_invoke_messages
            react_messages = resume_react_messages or []
            start_iteration = resume_iteration
            log.info(f"[SkillAgent] Resuming react loop from iteration {start_iteration}, "
                     f"invoke_messages={len(invoke_messages)}, pending_tool={resume_pending_tool}")

            # Execute the previously-interrupted tool call now that it's approved
            if resume_pending_tool:
                _tc = resume_pending_tool
                _tool_name = _tc["name"]
                _tool_args = _tc.get("args", {})
                writer({"Node Name": "Tool Call", "Status": "Started", "Tool Name": _tool_name, "Tool Arguments": _tool_args})
                writer({"raw": {"tool_verifier": "User approved the tool execution"}, "content": "User approved the tool execution."})

                _tool_start = _time.time()
                tool_fn = tool_map.get(_tool_name)
                if tool_fn is None:
                    result = f"Error: Unknown tool '{_tool_name}'"
                else:
                    try:
                        result = tool_fn.invoke(_tool_args)
                    except Exception as e:
                        result = f"Error executing tool: {e}"
                _tool_duration = (_time.time() - _tool_start) * 1000

                if hook_runner:
                    try:
                        result = hook_runner.run_post_hooks(_tool_name, _tool_args, result, _tool_duration)
                    except Exception:
                        pass
                    # Fire external PostToolUse hooks — but skip if we're resuming
                    # from a PostToolUse approval (tool already ran, hooks already fired)
                    if not skip_post_tool_hooks_on_resume:
                        try:
                            _post_tool_ctx = {
                                "session_id": state.get("session_id", ""),
                                "agentic_application_id": state.get("agentic_application_id", ""),
                                "skill_name": skill_name,
                                "query": state.get("query", ""),
                            }
                            _pt_result = hook_runner.run_external_post_tool(_tool_name, _tool_args, str(result), _post_tool_ctx)
                            if _pt_result.blocked:
                                result = f"Blocked by post-tool hook: {_pt_result.reason}"
                            elif _pt_result.needs_approval:
                                log.info(f"[SkillAgent] PostToolUse hook requires approval for tool '{_tool_name}' output: {_pt_result.reason}")
                                writer({"raw": {"tool_verifier": f"Hook requires approval for tool '{_tool_name}' output: {_pt_result.reason}"}, "content": f"Tool '{_tool_name}' output requires hook approval. {_pt_result.reason}"})
                                raise _ToolInterruptSignal(
                                    tool_call=_tc,
                                    invoke_messages=invoke_messages,
                                    react_messages=react_messages,
                                    iteration=start_iteration,
                                    interrupt_type="hook_approval",
                                    reason=_pt_result.reason,
                                )
                        except _ToolInterruptSignal:
                            raise
                        except Exception:
                            pass
                if audit:
                    audit.record_tool_call(
                        tool_name=_tool_name, args_preview=str(_tool_args),
                        result_preview=str(result), duration_ms=_tool_duration, success=True,
                    )

                tool_msg = ToolMessage(content=str(result), tool_call_id=_tc.get("id", ""), name=_tool_name)
                invoke_messages.append(tool_msg)
                react_messages.append(tool_msg)
                writer({"raw": {"Tool Name": _tool_name, "Tool Output": str(result)[:500]}, "content": f"Tool {_tool_name} returned: {str(result)[:100]}"})
                writer({"Node Name": "Tool Call", "Status": "Completed", "Tool Name": _tool_name})
        else:
            invoke_messages = [
                SystemMessage(content=system_prompt),
                HumanMessage(content=user_message),
            ]
            react_messages = []
            start_iteration = 0

        response_content = ""

        budget_trace_id = f"{state['session_id']}_{state['agentic_application_id']}"
        start_budget(budget_trace_id)

        try:
            for iteration in range(start_iteration, max_iterations):
                # Hook Layer 4: before_llm
                if hook_runner:
                    hook_runner.run_before_llm(invoke_messages, iteration)

                _llm_start = _time.time()
                if llm_tracker_callback:
                    # Fix #6 — wrap LLM call with timeout to prevent hangs
                    ai_response = await asyncio.wait_for(
                        llm_with_tools.ainvoke(
                            invoke_messages,
                            config={"callbacks": [llm_tracker_callback]},
                        ),
                        timeout=float(os.getenv("SKILL_LLM_TIMEOUT", "120")),
                    )
                else:
                    ai_response = await asyncio.wait_for(
                        llm_with_tools.ainvoke(invoke_messages),
                        timeout=float(os.getenv("SKILL_LLM_TIMEOUT", "120")),
                    )

                _llm_duration = (_time.time() - _llm_start) * 1000

                # Audit: record LLM call
                if audit:
                    _usage = getattr(ai_response, 'usage_metadata', None) or {}
                    audit.record_llm_call(
                        iteration=iteration,
                        prompt_tokens=_usage.get('input_tokens', 0) if isinstance(_usage, dict) else getattr(_usage, 'input_tokens', 0),
                        completion_tokens=_usage.get('output_tokens', 0) if isinstance(_usage, dict) else getattr(_usage, 'output_tokens', 0),
                        duration_ms=_llm_duration,
                        has_tool_calls=bool(ai_response.tool_calls),
                    )

                # Hook Layer 4: after_llm
                if hook_runner:
                    hook_runner.run_after_llm(invoke_messages, ai_response, iteration, _llm_duration)

                invoke_messages.append(ai_response)
                react_messages.append(ai_response)

                if not ai_response.tool_calls:
                    response_content = ai_response.content or ""
                    break

                writer({"raw": {"executor_agent": ai_response.tool_calls}, "content": "Agent is calling tools"})

                for tc in ai_response.tool_calls:
                    tool_name = tc["name"]
                    tool_args = tc["args"]

                    writer({"Node Name": "Tool Call", "Status": "Started", "Tool Name": tool_name, "Tool Arguments": tool_args})

                    if tool_args:
                        args_str = ", ".join(f"{k}={v}" for k, v in tool_args.items()) if isinstance(tool_args, dict) else str(tool_args)
                        writer({"content": f"Agent called the tool '{tool_name}', passing arguments: {args_str}."})
                    else:
                        writer({"content": f"Agent called the tool '{tool_name}', passing no arguments."})

                    # --- Selective tool interruption (human-in-the-loop) ---
                    # Instead of calling interrupt() here (which would cause
                    # the node to re-run on resume, losing all local state),
                    # we raise _ToolInterruptSignal so the node can persist
                    # state and let the graph route to tool_interrupt_node.
                    #
                    # interrupt_items come from the chat request (user-specified list).
                    if tool_interrupt_flag:
                        interrupt_items = state.get("interrupt_items") or []
                        should_interrupt = not interrupt_items or (tool_name in interrupt_items)
                        if should_interrupt:
                            log.info(f"[SkillAgent] Tool '{tool_name}' needs HITL approval, raising interrupt signal")
                            writer({"raw": {"tool_verifier": f"Awaiting approval to execute tool '{tool_name}'"}, "content": f"Tool '{tool_name}' requires confirmation. Please approve to proceed."})
                            raise _ToolInterruptSignal(
                                tool_call=tc,
                                invoke_messages=invoke_messages,
                                react_messages=react_messages,
                                iteration=iteration,
                                interrupt_type="tool_interrupt",
                            )

                    # Run pre-hooks, execute, run post-hooks
                    _tool_start = _time.time()
                    try:
                        if hook_runner:
                            try:
                                tool_args = hook_runner.run_pre_hooks(tool_name, tool_args)
                            except ToolBlockedError as tbe:
                                result = f"Blocked by policy: {tbe}"
                                tool_msg = ToolMessage(content=str(result), tool_call_id=tc["id"], name=tool_name)
                                invoke_messages.append(tool_msg)
                                react_messages.append(tool_msg)
                                writer({"raw": {"Tool Name": tool_name, "Tool Output": str(result)[:500]}, "content": f"Tool {tool_name} blocked: {str(result)[:100]}"})
                                writer({"Node Name": "Tool Call", "Status": "Completed", "Tool Name": tool_name})
                                continue

                            # Run external pre-tool hooks (shell command hooks)
                            _session_ctx = {
                                "session_id": state.get("session_id", ""),
                                "agentic_application_id": state.get("agentic_application_id", ""),
                                "skill_name": skill_name,
                                "query": state.get("query", ""),
                            }
                            ext_result = hook_runner.run_external_pre_tool(tool_name, tool_args, _session_ctx)
                            if ext_result.blocked:
                                result = f"Blocked by external hook: {ext_result.reason}"
                                tool_msg = ToolMessage(content=str(result), tool_call_id=tc["id"], name=tool_name)
                                invoke_messages.append(tool_msg)
                                react_messages.append(tool_msg)
                                writer({"raw": {"Tool Name": tool_name, "Tool Output": str(result)[:500]}, "content": f"Tool {tool_name} blocked: {str(result)[:100]}"})
                                writer({"Node Name": "Tool Call", "Status": "Completed", "Tool Name": tool_name})
                                continue
                            if ext_result.needs_approval:
                                log.info(f"[SkillAgent] External hook requires approval for tool '{tool_name}': {ext_result.reason}")
                                writer({"raw": {"tool_verifier": f"Hook requires approval to execute tool '{tool_name}': {ext_result.reason}"}, "content": f"Tool '{tool_name}' requires hook approval. {ext_result.reason}"})
                                raise _ToolInterruptSignal(
                                    tool_call=tc,
                                    invoke_messages=invoke_messages,
                                    react_messages=react_messages,
                                    iteration=iteration,
                                    interrupt_type="hook_approval",
                                    reason=ext_result.reason,
                                )

                        tool_fn = tool_map.get(tool_name)
                        if tool_fn is None:
                            result = f"Error: Unknown tool '{tool_name}'"
                        else:
                            result = tool_fn.invoke(tool_args)

                        _tool_duration = (_time.time() - _tool_start) * 1000

                        if hook_runner:
                            result = hook_runner.run_post_hooks(tool_name, tool_args, result, _tool_duration)
                            # Fire external PostToolUse hooks (synchronous — can block/approve output before LLM sees it)
                            try:
                                _pt_result = hook_runner.run_external_post_tool(tool_name, tool_args, str(result), _session_ctx)
                                if _pt_result.blocked:
                                    result = f"Blocked by post-tool hook: {_pt_result.reason}"
                                elif _pt_result.needs_approval:
                                    log.info(f"[SkillAgent] PostToolUse hook requires approval for tool '{tool_name}' output: {_pt_result.reason}")
                                    writer({"raw": {"tool_verifier": f"Hook requires approval for tool '{tool_name}' output: {_pt_result.reason}"}, "content": f"Tool '{tool_name}' output requires hook approval. {_pt_result.reason}"})
                                    raise _ToolInterruptSignal(
                                        tool_call=tc,
                                        invoke_messages=invoke_messages,
                                        react_messages=react_messages,
                                        iteration=iteration,
                                        interrupt_type="hook_approval",
                                        reason=_pt_result.reason,
                                    )
                            except _ToolInterruptSignal:
                                raise
                            except Exception:
                                pass

                        # Audit: record successful tool call
                        if audit:
                            audit.record_tool_call(
                                tool_name=tool_name,
                                args_preview=str(tool_args),
                                result_preview=str(result),
                                duration_ms=_tool_duration,
                                success=True,
                            )

                    except _ToolInterruptSignal:
                        raise  # propagate to outer handler — do NOT swallow as tool error
                    except Exception as e:
                        result = f"Error executing tool: {e}"
                        _tool_duration = (_time.time() - _tool_start) * 1000
                        # Audit: record failed tool call
                        if audit:
                            audit.record_tool_call(
                                tool_name=tool_name,
                                args_preview=str(tool_args),
                                result_preview=str(result),
                                duration_ms=_tool_duration,
                                success=False,
                            )

                    tool_msg = ToolMessage(content=str(result), tool_call_id=tc["id"], name=tool_name)
                    invoke_messages.append(tool_msg)
                    react_messages.append(tool_msg)

                    writer({"raw": {"Tool Name": tool_name, "Tool Output": str(result)[:500]}, "content": f"Tool {tool_name} returned: {str(result)[:100]}"})
                    writer({"Node Name": "Tool Call", "Status": "Completed", "Tool Name": tool_name})
            else:
                # Fix #8 — guard against None content when iterations exhausted
                if react_messages and hasattr(react_messages[-1], "content"):
                    response_content = react_messages[-1].content or ""
                else:
                    response_content = "I reached the maximum number of reasoning steps. Please try a more specific query."

        except asyncio.TimeoutError:
            log.error("[SkillAgent] LLM invocation timed out")
            response_content = "I'm sorry, the request took too long. Please try again with a simpler query."
            errors.append("LLM timeout")
        except _ToolInterruptSignal:
            # Propagate to skill_executor so it can persist loop state
            raise
        except Exception as e:
            log.error(f"[SkillAgent] ReAct loop error: {e}", exc_info=True)
            # Fix #12 — don't leak internal error details to user
            response_content = "I encountered an error while processing your request. Please try again."
            errors.append(str(e))

        llm_budget = end_budget()
        if llm_budget:
            budget_summary = format_budget_summary(llm_budget)
            log.info(f"[SkillAgent] {budget_summary}")

        return response_content, react_messages, errors

    # ------------------------------------------------------------------
    # Abstract method overrides
    # ------------------------------------------------------------------

    async def _build_agent_and_chains(
        self, llm, agent_config, checkpointer=None,
        tool_interrupt_flag: bool = False,
        use_kafka_tool_worker: bool = False,
        session_id: str = None,
        agent_id: str = None,
        context_flag: bool = True,
        file_context_management_flag: bool = False,
    ):
        """
        Prepare the SkillRouter, EnterpriseContext, and LangChain tools
        that the ReAct loop in skill_executor will use.

        When ``file_context_management_flag=True`` **and** ``context_flag=True``,
        the AgentShell ``run_shell_command`` tool is loaded alongside the
        skill-specific tools so the LLM can manage file-based memory
        (facts, session workspace, etc.) exactly like a react_agent.
        """
        from src.agentos.skill_router import SkillRouter
        from src.agentos.enterprise_context import EnterpriseContextManager

        real_agent_id = agent_id or agent_config.get("AGENT_ID", "")
        department = agent_config.get("DEPARTMENT", None)
        agent_dir = self._resolve_agent_dir(real_agent_id, department)

        # ---- Set structured logging context (ContextVar) ----
        # All subsequent log calls (including downstream modules like shell,
        # vector_store, skill_router) will carry these fields via CustomFilter.
        update_session_context(
            agent_id=real_agent_id,
            session_id=session_id or "",
            user_session=session_id or "",
            agent_type="skill_agent",
            agent_name=agent_config.get("AGENT_NAME", ""),
            call_category="agent_inference"
        )

        skills_dir = agent_dir / "skills"
        enterprise_dir = agent_dir / "enterprise_context"

        # ========== PRE-INFERENCE ASSET RESTORATION (parallel) ==========
        # Ensure all required skill agent assets are available locally.
        # Restores from blob: skills folder, database schema/samples, SQLite DBs.
        try:
            from src.inference.pre_inference_restore import ensure_inference_assets_available
            from src.inference.database_tools_integration import get_db_connections_for_agent as _get_db_conns_pre

            _pre_db_conns = await _get_db_conns_pre(real_agent_id)
            await ensure_inference_assets_available(
                department=department or "General",
                agent_id=real_agent_id,
                agent_name=agent_config.get("AGENT_NAME", ""),
                db_connection_names=_pre_db_conns,
                file_context_management_flag=file_context_management_flag,
                uploaded_files=None,
                is_skill_agent=True,
                skills_dir=skills_dir,
            )
        except Exception as e:
            log.warning(f"[SkillAgent][PreInferenceRestore] Non-critical error: {e}")

        # Auto-regenerate enterprise_context if missing (e.g. deleted or never created)
        if not enterprise_dir.exists() or not any(enterprise_dir.iterdir()):
            enterprise_dir.mkdir(parents=True, exist_ok=True)
            ec_file = enterprise_dir / "Enterprise_Context.md"
            if not ec_file.exists():
                agent_name = agent_config.get("AGENT_NAME", real_agent_id)
                ec_file.write_text(
                    f"# Enterprise Context \u2014 {agent_name}\n\n"
                    "_Edit this file to provide company-wide context, policies, "
                    "and guidelines that apply across all skills._\n",
                    encoding="utf-8",
                )
                log.info(f"[SkillAgent] Regenerated missing enterprise_context for {real_agent_id}")

        skill_router = SkillRouter(str(skills_dir), llm=llm)

        enterprise_ctx_mgr = None
        if enterprise_dir.exists():
            enterprise_ctx_mgr = EnterpriseContextManager(str(enterprise_dir))

        # Create LangChain tools scoped to this agent's directory
        tools = create_skill_tools(agent_dir)
        tool_map = {t.name: t for t in tools}

        # ---- AgentShell (ALWAYS loaded for skill agents) ----
        # run_shell_command is the primary tool for reading skill files
        # via virtual paths: /skills/, /enterprise_context/, /databases/
        agent_shell = None
        additional_paths = None
        allowed_absolute_mount_roots = None
        try:
            from src.memory.agent_shell.tools import get_shell_tools_for_session
            from src.utils.secrets_handler import current_user_email, current_user_department
            from src.inference.agent_config_loader import load_agent_mount_config

            user_email = current_user_email.get(None)
            user_department = current_user_department.get(department or "General")

            # Load additional_paths and allowed_absolute_mount_roots from agent_config.json
            additional_paths, allowed_absolute_mount_roots = load_agent_mount_config(
                real_agent_id, agent_dir=agent_dir, department=department,
            )

            agent_shell, shell_tools = get_shell_tools_for_session(
                agent_id=real_agent_id,
                session_id=session_id or "default",
                user_email=user_email,
                workspace_root="./agent_workspaces",
                department=user_department,
                additional_paths=additional_paths,
                allowed_absolute_mount_roots=allowed_absolute_mount_roots,
                agentos_root_override=str(agent_dir),
                databases_root_override=str(agent_dir.parent.parent / "databases"),
            )
            for st in shell_tools:
                tools.append(st)
                tool_map[st.name] = st
            log.info(
                f"[SkillAgent] AgentShell loaded: user={user_email}, "
                f"agent={real_agent_id}, session={session_id or 'default'} "
                f"(+{len(shell_tools)} tool(s): {[t.name for t in shell_tools]})"
            )
        except Exception as e:
            log.warning(f"[SkillAgent] Failed to load AgentShell: {e}")

        # ---- Database tools (Data Connector) ----
        db_connection_names = []
        try:
            from src.inference.database_tools_integration import get_db_connections_for_agent, get_database_tools_for_injection, ensure_database_files_restored
            db_connection_names = await get_db_connections_for_agent(real_agent_id)
            if db_connection_names:
                log.info(f"[SkillAgent] DB connections found for {real_agent_id}: {db_connection_names}")
                
                # Ensure schema/samples files exist locally (restore from blob if missing)
                _dept_for_restore = department or "General"
                await ensure_database_files_restored(db_connection_names, department=_dept_for_restore)
                
                db_tools = get_database_tools_for_injection(db_connection_names)
                for dt in db_tools:
                    tools.append(dt)
                    tool_map[dt.name] = dt
                log.info(f"[SkillAgent] Injected {len(db_tools)} database tools: {[t.name for t in db_tools]}")
            else:
                log.info(f"[SkillAgent] No DB connections for agent {real_agent_id}")
        except Exception as e:
            log.warning(f"[SkillAgent] Error loading DB tools: {e}")

        # Create hook runner with default production hooks
        # Load user-defined hooks from agent config if available
        _hooks_config = None
        try:
            _agent_config_path = agent_dir / "config.yaml"
            if _agent_config_path.exists():
                import yaml
                with open(_agent_config_path) as _f:
                    _agent_cfg = yaml.safe_load(_f) or {}
                _hooks_config = _agent_cfg.get("hooks")
        except Exception as _hcfg_err:
            log.debug(f"[SkillAgent] Config.yaml load skipped: {_hcfg_err}")
        hook_runner = create_default_hooks(hooks_config=_hooks_config)

        # Auto-load global hooks for the department (OnAgentStart, OnAgentEnd,
        # OnAgentError, PostSampling) — these fire for ALL agents automatically.
        _dept = department or "General"
        try:
            hook_runner.load_global_hooks(_dept)
        except Exception as _gh_err:
            log.debug(f"[SkillAgent] Global hooks load skipped: {_gh_err}")

        # Create LLM token tracker callback for LangGraph
        llm_tracker_callback = LLMTokenTracker("agent")

        # ---- Enhancement modules (Knowledge Store, Plan Cache, Session Store) ----
        # Thread-safe lazy initialization of module-level singletons.
        # The lock prevents two concurrent first-requests from double-initializing.
        global _knowledge_store_singleton, _plan_cache_singleton, _session_store_singleton
        knowledge_store = _knowledge_store_singleton
        plan_cache = _plan_cache_singleton
        session_store = _session_store_singleton

        if knowledge_store is None or plan_cache is None or session_store is None:
            with _singleton_lock:
                # Re-read after acquiring lock (double-checked locking)
                knowledge_store = _knowledge_store_singleton
                plan_cache = _plan_cache_singleton
                session_store = _session_store_singleton

                if knowledge_store is None or plan_cache is None:
                    try:
                        from src.api.app_container import app_container
                        from src.config.constants import DatabaseName
                        db_pool = await app_container.db_manager.get_pool(DatabaseName.MAIN.db_name)
                        if db_pool:
                            if knowledge_store is None:
                                knowledge_store = KnowledgeStore(db_pool)
                                await knowledge_store.initialize()
                                _knowledge_store_singleton = knowledge_store
                            if plan_cache is None:
                                plan_cache = PlanCache(db_pool)
                                await plan_cache.initialize()
                                _plan_cache_singleton = plan_cache
                            log.info("[SkillAgent] KnowledgeStore + PlanCache initialized (cached)")
                    except Exception as e:
                        log.warning(f"[SkillAgent] Enhancement modules (KS/PC) init skipped: {e}")

                if session_store is None:
                    try:
                        session_store = SessionStore()
                        _session_store_singleton = session_store
                        # NOTE: Do NOT call session_store.ping() here — it blocks for
                        # socket_connect_timeout (2s) + socket_timeout (2s) when Redis is
                        # unavailable, adding ~24s of pure wait time.  The SessionStore
                        # already handles failures gracefully at point-of-use (restore/save)
                        # so we just create the instance and let it fail lazily.
                        log.info("[SkillAgent] SessionStore created (lazy connect)")
                    except Exception as e:
                        log.warning(f"[SkillAgent] SessionStore init skipped: {e}")
                        session_store = None

        return {
            "llm": llm,
            "skill_router": skill_router,
            "enterprise_context_manager": enterprise_ctx_mgr,
            "agent_dir": agent_dir,
            "tools": tools,
            "tool_map": tool_map,
            "hook_runner": hook_runner,
            "llm_tracker_callback": llm_tracker_callback,
            "agent_shell": agent_shell,
            "file_context_management_flag": file_context_management_flag,
            "context_flag": context_flag,
            "db_connection_names": db_connection_names,
            "knowledge_store": knowledge_store,
            "plan_cache": plan_cache,
            "session_store": session_store,
        }

    async def _build_workflow(self, chains: dict, flags: Dict[str, bool] = {}, get_dummy: bool = False) -> StateGraph:
        """
        Builds the LangGraph workflow:
            generate_past_conversation_summary → skill_executor → final_response → [formatter] → END

        skill_executor uses a manual ReAct tool-calling loop where the LLM
        reads skill files via tools (list, read, search) and composes the
        answer — matching the react_agent's SSE event format exactly.
        """
        llm = chains.get("llm", None)
        skill_router = chains.get("skill_router", None)
        enterprise_ctx_mgr = chains.get("enterprise_context_manager")
        tools = chains.get("tools", [])
        tool_map = chains.get("tool_map", {})
        agent_dir: Path = chains.get("agent_dir", None)
        hook_runner = chains.get("hook_runner")
        llm_tracker_callback = chains.get("llm_tracker_callback")
        agent_shell = chains.get("agent_shell")  # AgentShell instance (or None)
        chain_file_ctx_flag = chains.get("file_context_management_flag", False)
        chain_context_flag = chains.get("context_flag", True)
        chain_db_connection_names = chains.get("db_connection_names", [])
        knowledge_store: Optional[KnowledgeStore] = chains.get("knowledge_store")
        plan_cache: Optional[PlanCache] = chains.get("plan_cache")
        session_store: Optional[SessionStore] = chains.get("session_store")

        response_formatting_flag = flags.get("response_formatting_flag", True)
        tool_interrupt_flag = flags.get("tool_interrupt_flag", get_dummy or False)
        skill_verifier_flag = flags.get("skill_verifier_flag", get_dummy or False)
        inference_config: AdminConfigLimits = flags.get("inference_config", AdminConfigLimits())

        if agent_shell:
            log.info(f"[SkillAgent] AgentShell memory enabled — LLM can use run_shell_command for file-based context")

        # Fix #10 — Configurable iteration limit
        MAX_REACT_ITERATIONS = int(os.getenv("SKILL_MAX_REACT_ITERATIONS", "15"))

        # ---- Node 1: Generate past conversation summary ----
        async def generate_past_conversation_summary(state: SkillWorkflowState, writer: StreamWriter):
            """Fetches past conversation summary from the IAF chat service."""
            import time as _node_time
            _node_start = _node_time.time()
            
            # Set session context for LLM tracking within this workflow node
            # LangGraph spawns new async tasks that don't inherit contextvars automatically
            update_session_context(
                session_id=state['session_id'],
                user_session=state['session_id'],
                agent_id=state['agentic_application_id'],
                call_category="agent_inference"
            )
            
            # Hook Layer 2: before_node
            if hook_runner:
                hook_runner.run_before_node("generate_past_conversation_summary", state)
            # Hook Layer 1: on_agent_start (first node = agent start)
            if hook_runner:
                hook_runner.run_on_agent_start(
                    agent_id=state.get("agentic_application_id", ""),
                    session_id=state.get("session_id", ""),
                    query=state.get("query", ""),
                )

            strt_tmstp = get_timestamp()
            conv_summary = ""
            preference = ""
            errors = []

            try:
                current_state_query = await self.inference_utils.add_prompt_for_feedback(state["query"])

                if state["reset_conversation"]:
                    state["executor_messages"].clear()
                    state["ongoing_conversation"].clear()
                    log.info("[SkillAgent] Conversation reset for session")
                elif not state.get("context_flag", True):
                    # context_flag=False → no external context retrieval at all
                    log.info("[SkillAgent] Context flag is False — no context management.")
                    return {
                        "past_conversation_summary": "",
                        "query": current_state_query.content,
                        "ongoing_conversation": current_state_query,
                        "executor_messages": current_state_query,
                        "preference": "",
                        "response": None,
                        "start_timestamp": strt_tmstp,
                        "errors": errors,
                    }
                elif state.get("file_context_management_flag", False):
                    # file_context_management_flag=True → agent uses run_shell_command
                    # for file-based memory; skip DB conversation summary fetch
                    log.info(
                        "[SkillAgent] File context management enabled — "
                        "using run_shell_command for memory, skipping DB conversation fetch."
                    )
                    return {
                        "past_conversation_summary": "",
                        "query": current_state_query.content,
                        "ongoing_conversation": [],  # Don't pass ongoing conversation
                        "executor_messages": current_state_query,
                        "preference": "",
                        "response": None,
                        "start_timestamp": strt_tmstp,
                        "errors": errors,
                    }
                else:
                    writer({"Node Name": "Generating Context", "Status": "Started"})
                    try:
                        pref_and_summary = await self.chat_service.get_chat_conversation_summary(
                            agentic_application_id=state["agentic_application_id"],
                            session_id=state["session_id"],
                        )
                        pref_and_summary = pref_and_summary or {}
                        preference = pref_and_summary.get("preference", "")
                        conv_summary = pref_and_summary.get("summary", "")
                    except Exception as e:
                        log.warning(f"[SkillAgent] Failed to fetch conversation summary: {e}")
                    writer({"raw": {"past_conversation_summary": conv_summary}, "content": conv_summary[:100] + ("..." if len(conv_summary) > 100 else "")}) if conv_summary else writer({"raw": {"past_conversation_summary": conv_summary}, "content": "No past conversation summary available."})
                    writer({"Node Name": "Generating Context", "Status": "Completed"})
            except Exception as e:
                log.error(f"[SkillAgent] generate_past_conversation_summary failed: {e}")
                errors.append(str(e))
                current_state_query = HumanMessage(content=state["query"], role="user_query")

            # ---- Session Store: Restore snapshot for fast context hydration ----
            if session_store and not conv_summary and not preference:
                try:
                    snapshot = session_store.restore(
                        state["agentic_application_id"], state["session_id"]
                    )
                    if snapshot:
                        conv_summary = conv_summary or snapshot.past_conversation_summary
                        preference = preference or snapshot.preference
                        log.info(
                            f"[SkillAgent] Session snapshot restored "
                            f"(skill={snapshot.current_skill}, turns={snapshot.conversation_turn_count})"
                        )
                except Exception as e:
                    log.debug(f"[SkillAgent] Session restore skipped: {e}")

            _node1_result = {
                "past_conversation_summary": f"past_conversation_summary : {conv_summary}" if conv_summary else "",
                "query": current_state_query.content,
                "ongoing_conversation": current_state_query,
                "executor_messages": current_state_query,
                "preference": preference,
                "response": None,
                "start_timestamp": strt_tmstp,
                "errors": errors,
            }
            # Hook Layer 2: after_node
            if hook_runner:
                _node_duration = (_node_time.time() - _node_start) * 1000
                hook_runner.run_after_node("generate_past_conversation_summary", state, _node1_result, _node_duration)
            return _node1_result

        # ---- Node 2: Skill executor (ReAct tool-calling loop) ----
        async def skill_executor(state: SkillWorkflowState, writer: StreamWriter):
            """
            Routes the query to matching skills, builds a system prompt,
            and runs the ReAct tool-calling loop.

            Heavy lifting is delegated to extracted helpers:
            - ``_build_skill_section`` — per-skill metadata
            - ``_build_skill_system_prompt`` — full prompt assembly
            - ``_run_skill_react_loop`` — ReAct execution

            On resume from a tool interrupt (is_tool_interrupted=True),
            skips routing/prompt-building and resumes the loop directly
            using persisted state.
            """
            nonlocal tool_interrupt_flag
            import time as _node_time

            # === FAST PATH: Resume after tool interrupt approval ===
            if state.get("is_tool_interrupted") and state.get("_pending_tool_call"):
                writer({"Node Name": "Thinking...", "Status": "Started"})
                _node2_start = _node_time.time()
                errors = state.get("errors", [])
                system_prompt = state.get("system_prompt_text", "")
                skill_name = state.get("skill_name", "")
                routing_method = state.get("routing_method", "")
                routing_confidence = state.get("routing_confidence", 0.0)
                query = state["query"]

                # Build user_message same as the initial path
                context_parts = []
                if not chain_file_ctx_flag:
                    if state.get("past_conversation_summary"):
                        context_parts.append(state["past_conversation_summary"])
                    if state.get("context_flag", True) and state.get("ongoing_conversation"):
                        try:
                            formatted_conv = await self.chat_service.get_formatted_messages(state["ongoing_conversation"])
                            if formatted_conv:
                                context_parts.append(formatted_conv)
                        except Exception:
                            pass
                user_message = query
                if context_parts:
                    user_message = "\n\n".join(context_parts) + f"\n\nUser Query:\n{query}"

                log.info(f"[SkillAgent] Resuming skill_executor after tool approval")

                # Check if user rejected the tool
                _feedback = state.get("tool_feedback", "yes")
                _resume_pending_tool = None
                _resume_invoke = None
                _resume_react = None
                _resume_iteration = state.get("_react_iteration", 0)

                try:
                    _resume_pending_tool = json.loads(state["_pending_tool_call"])
                    from langchain_core.messages import messages_from_dict
                    if state.get("_react_invoke_messages"):
                        _resume_invoke = messages_from_dict(json.loads(state["_react_invoke_messages"]))
                    if state.get("_react_messages"):
                        _resume_react = messages_from_dict(json.loads(state["_react_messages"]))
                except Exception as _deser_err:
                    log.warning(f"[SkillAgent] Failed to deserialize resume state: {_deser_err}")

                if _feedback != "yes" and _feedback != "no":
                    # User provided modified args (JSON) or feedback text
                    try:
                        modified_args = json.loads(_feedback)
                        if isinstance(modified_args, dict) and _resume_pending_tool:
                            _resume_pending_tool["args"] = modified_args
                            log.info(f"[SkillAgent] User modified tool args: {modified_args}")
                    except (json.JSONDecodeError, TypeError):
                        # Treat as rejection feedback — inject as tool message
                        if _resume_pending_tool and _resume_invoke is not None:
                            _rej_msg = ToolMessage(
                                content=f"Tool execution rejected by user: {_feedback}",
                                tool_call_id=_resume_pending_tool.get("id", ""),
                                name=_resume_pending_tool.get("name", ""),
                            )
                            _resume_invoke.append(_rej_msg)
                            if _resume_react is not None:
                                _resume_react.append(_rej_msg)
                            _resume_pending_tool = None  # Don't execute the tool
                            log.info(f"[SkillAgent] User rejected tool with feedback: {_feedback}")
                elif _feedback == "no":
                    # User declined
                    if _resume_pending_tool and _resume_invoke is not None:
                        _rej_msg = ToolMessage(
                            content="Tool execution was declined by user.",
                            tool_call_id=_resume_pending_tool.get("id", ""),
                            name=_resume_pending_tool.get("name", ""),
                        )
                        _resume_invoke.append(_rej_msg)
                        if _resume_react is not None:
                            _resume_react.append(_rej_msg)
                        _resume_pending_tool = None
                        log.info("[SkillAgent] User declined tool execution")

                try:
                    # If resuming from a PostToolUse hook_approval, skip PostToolUse hooks
                    # on the resumed tool to avoid infinite re-triggering
                    _skip_ptu = (state.get("_interrupt_type") == "hook_approval" and _feedback == "yes")
                    response_content, react_messages, loop_errors = await self._run_skill_react_loop(
                        llm=llm,
                        tools=tools,
                        tool_map=tool_map,
                        system_prompt=system_prompt,
                        user_message=user_message,
                        writer=writer,
                        state=state,
                        hook_runner=hook_runner,
                        llm_tracker_callback=llm_tracker_callback,
                        tool_interrupt_flag=tool_interrupt_flag,
                        max_iterations=MAX_REACT_ITERATIONS,
                        audit=None,  # skip audit on resume
                        skill_name=skill_name,
                        resume_invoke_messages=_resume_invoke,
                        resume_react_messages=_resume_react,
                        resume_pending_tool=_resume_pending_tool,
                        resume_iteration=_resume_iteration,
                        skip_post_tool_hooks_on_resume=_skip_ptu,
                    )
                except _ToolInterruptSignal as _sig:
                    # Another tool needs approval — persist and route back
                    from langchain_core.messages import messages_to_dict
                    return {
                        "is_tool_interrupted": True,
                        "executor_messages": _sig.react_messages,
                        "errors": errors,
                        "skill_name": skill_name,
                        "routing_method": routing_method,
                        "routing_confidence": routing_confidence,
                        "system_prompt_text": system_prompt,
                        "_pending_tool_call": json.dumps(_sig.tool_call),
                        "_react_invoke_messages": json.dumps(messages_to_dict(_sig.invoke_messages)),
                        "_react_messages": json.dumps(messages_to_dict(_sig.react_messages)),
                        "_react_iteration": _sig.iteration,
                        "_interrupt_type": _sig.interrupt_type,
                        "_interrupt_reason": _sig.reason,
                    }

                errors.extend(loop_errors)
                writer({"Node Name": "Thinking...", "Status": "Completed"})

                # Strip final no-tool-calling AIMessage
                if react_messages and hasattr(react_messages[-1], 'type') and react_messages[-1].type == "ai":
                    _last = react_messages[-1]
                    if not getattr(_last, 'tool_calls', None):
                        react_messages = react_messages[:-1]

                return {
                    "response": response_content,
                    "executor_messages": react_messages,
                    "errors": errors,
                    "skill_name": skill_name,
                    "routing_method": routing_method,
                    "routing_confidence": routing_confidence,
                    "system_prompt_text": system_prompt,
                    # Clear interrupt state
                    "is_tool_interrupted": False,
                    "_pending_tool_call": "",
                    "_react_invoke_messages": "",
                    "_react_messages": "",
                    "_react_iteration": 0,
                }

            # === FAST PATH: Resume after skill verification (approve/modify/reject) ===
            _resuming_skill_verify = False
            if state.get("is_skill_interrupted") and state.get("_skill_verifier_data") and not state.get("_pending_tool_call"):
                _sf = state.get("skill_feedback", "approve")
                _sd = json.loads(state["_skill_verifier_data"])
                errors = state.get("errors", [])
                query = state["query"]

                if _sf in ("reject", "no"):
                    writer({"Node Name": "Thinking...", "Status": "Started"})
                    writer({"Node Name": "Thinking...", "Status": "Completed"})
                    return {
                        "response": "Skill execution was cancelled by user.",
                        "executor_messages": [],
                        "errors": errors,
                        "is_skill_interrupted": False,
                        "_skill_verifier_data": "",
                        "_interrupt_type": "",
                    }
                elif _sf in ("approve", "yes"):
                    skill_name = _sd["selected_skill"]
                    routing_method = _sd["routing_method"]
                    routing_confidence = _sd["routing_confidence"]
                else:
                    # User provided a different skill name
                    skill_name = _sf
                    routing_method = "user_override"
                    routing_confidence = 1.0

                routing_results = []
                _resuming_skill_verify = True
                log.info(f"[SkillAgent] Resuming after skill verification: skill={skill_name}, feedback={_sf}")

            # === NORMAL PATH: First invocation ===
            writer({"Node Name": "Thinking...", "Status": "Started"})
            import time as _node_time
            _node2_start = _node_time.time()
            # Hook Layer 2: before_node
            if hook_runner:
                hook_runner.run_before_node("skill_executor", state)

            errors = state.get("errors", []) if not _resuming_skill_verify else errors
            query = state["query"] if not _resuming_skill_verify else query

            # Enrich structured logging context with per-request fields
            update_session_context(
                session_id=state.get("session_id", ""),
                user_query=query[:200],
            )

            # --- 1. Route query to matching skills (skip if resuming from skill verification) ---
            if not _resuming_skill_verify:
                # Hook Layer 3: before_route
                if hook_runner:
                    hook_runner.run_before_route(query, state["agentic_application_id"])

                # --- 1a. Check Plan Cache first (fast path) ---
                _cached_plan = None
                if plan_cache:
                    try:
                        _cached_plan = await plan_cache.lookup(
                            query, state["agentic_application_id"],
                        )
                    except Exception as e:
                        log.debug(f"[SkillAgent] Plan cache lookup skipped: {e}")

                if _cached_plan:
                    # Plan cache hit — skip routing, use cached skill
                    skill_name = _cached_plan.skill_name
                    routing_method = _cached_plan.routing_method
                    routing_confidence = _cached_plan.routing_confidence
                    routing_results = []
                    log.info(
                        f"[SkillAgent] Plan cache HIT: query='{query[:60]}' → "
                        f"skill={skill_name} (method={routing_method}, hits={_cached_plan.hit_count})"
                    )
                else:
                    # --- 1b. Normal routing (no cache hit) ---
                    try:
                        # Build concise enterprise context for the router LLM
                        _routing_ctx = ""
                        if enterprise_ctx_mgr:
                            try:
                                _routing_ctx = enterprise_ctx_mgr.build_routing_context()
                            except Exception:
                                pass
                        routing_results = await skill_router.route_multi(
                            query=query, enterprise_context=_routing_ctx or None,
                        )
                        primary = routing_results[0]
                        skill_name = primary.skill_name
                        routing_method = primary.method
                        routing_confidence = primary.confidence
                        matched_names = [r.skill_name for r in routing_results]
                        log.info(
                            f"[SkillAgent] Routing: query='{query[:60]}' → "
                            f"matched={matched_names} (method={routing_method}, conf={routing_confidence})"
                        )
                    except Exception as e:
                        log.error(f"[SkillAgent] Skill routing failed: {e}")
                        routing_results = []
                        skill_name = skill_router.get_default_skill()
                        routing_method = "error_fallback"
                        routing_confidence = 0.0

                routing_info = {"skill": skill_name, "method": routing_method, "confidence": routing_confidence}
                if len(routing_results) > 1:
                    routing_info["additional_skills"] = [r.skill_name for r in routing_results[1:]]
                writer({"raw": {"skill_routing": routing_info}, "content": f"Routed to skill(s): {', '.join(r.skill_name for r in routing_results) if routing_results else skill_name} (method={routing_method})"})

                # --- Skill Verifier: Pause for human approval of selected skill ---
                if skill_verifier_flag:
                    all_active_skills = [s for s in skill_router.list_skills() if s["status"] == "active"]
                    # Build matched_skills from routing_results (all LLM-selected skills with confidences)
                    _matched_skills = [
                        {"name": r.skill_name, "confidence": r.confidence, "reasoning": r.reasoning}
                        for r in routing_results
                    ] if routing_results else [{"name": skill_name, "confidence": routing_confidence, "reasoning": ""}]
                    _skill_verifier_payload = {
                        "selected_skill": skill_name,
                        "matched_skills": _matched_skills,
                        "available_skills": all_active_skills,
                        "routing_method": routing_method,
                        "routing_confidence": routing_confidence,
                    }
                    log.info(f"[SkillAgent] Skill verifier active — pausing for approval: skill={skill_name}")
                    return {
                        "is_skill_interrupted": True,
                        "_skill_verifier_data": json.dumps(_skill_verifier_payload),
                        "skill_name": skill_name,
                        "routing_method": routing_method,
                        "routing_confidence": routing_confidence,
                        "_interrupt_type": "skill_interrupt",
                        "errors": errors,
                    }

            # --- Request-scoped audit trail ---
            _user_email_for_audit = ""
            try:
                from src.utils.secrets_handler import current_user_email
                _user_email_for_audit = current_user_email.get("") or ""
            except Exception:
                pass
            _audit = RequestAuditTrail(
                request_id=f"{state['session_id']}_{state.get('start_timestamp', '')}",
                agent_id=state["agentic_application_id"],
                session_id=state["session_id"],
                user_email=_user_email_for_audit,
                model_name=state.get("model_name", ""),
                query=query,
            )
            _audit.record_routing(
                skill_name=skill_name,
                method=routing_method,
                confidence=routing_confidence,
                candidate_skills=[r.skill_name for r in routing_results] if routing_results else [skill_name],
            )

            # Set skill context for skill-level hook filtering
            if hook_runner:
                hook_runner.set_current_skill(skill_name)

            # Hook Layer 3: after_route
            if hook_runner:
                hook_runner.run_after_route(query, skill_name, routing_method, routing_confidence)
            # --- 2. Load skill metadata and build prompt sections ---
            from src.agentos.skill_loader import SkillLoader
            _skill_loader = SkillLoader(str(agent_dir / "skills"))

            loaded_sections = []
            loaded_names = set()
            for idx, rr in enumerate(routing_results):
                label = "Primary Skill" if idx == 0 else f"Matched Skill #{idx + 1}"
                loaded_sections.append(self._build_skill_section(rr.skill_name, label, _skill_loader))
                loaded_names.add(rr.skill_name)
            if not loaded_sections:
                loaded_sections.append(self._build_skill_section(skill_name, "Primary Skill", _skill_loader))
                loaded_names.add(skill_name)
            skills_section = "\n".join(loaded_sections)

            # --- 2b. Load skill-level hooks ---
            _primary_skill = _skill_loader.load(skill_name)

            # Load skill-level hooks (if any)
            if hook_runner and _primary_skill and _primary_skill.hooks:
                hook_runner.load_skill_hooks(_primary_skill.hooks)

            # Build read instructions
            read_instructions = "\n## Files to Read\n"
            read_instructions += "Use `run_shell_command(command=\"cat <path>\")` to read these files:\n"
            for sname in loaded_names:
                read_instructions += f"1. **`/skills/{sname}/SKILL.md`** — **MUST read first** (core knowledge & workflow)\n"
                sk = _skill_loader.load(sname)
                skill_dir_path = Path(sk.folder_path) if sk and sk.folder_path else None
                if skill_dir_path:
                    if (skill_dir_path / "INSTRUCTIONS.md").exists():
                        read_instructions += f"2. `/skills/{sname}/INSTRUCTIONS.md` — read if SKILL.md says to follow detailed steps\n"
                    if (skill_dir_path / "EXAMPLES.md").exists():
                        read_instructions += f"3. `/skills/{sname}/EXAMPLES.md` — read only if unsure how to respond\n"

            # Build awareness list of other skills
            all_skills = skill_router.list_skills()
            other_skills = [s for s in all_skills if s["status"] == "active" and s["name"] not in loaded_names]
            other_skills_text = ""
            if other_skills:
                other_skills_text = "\n## Other Available Skills\n"
                for s in other_skills:
                    other_skills_text += f"- **{s['name']}**: {s['description']}\n"
                other_skills_text += '\n_If the query matches one of these, read its SKILL.md first via `run_shell_command(command="cat /skills/<skill_name>/SKILL.md")`._\n'

            # Enterprise context
            enterprise_context_text = ""
            if enterprise_ctx_mgr:
                try:
                    enterprise_context_text = enterprise_ctx_mgr.build_context_for_skill(skill_name=skill_name)
                except Exception as e:
                    log.warning(f"[SkillAgent] Failed to load enterprise context: {e}")

            # Multi-skill instruction
            multi_skill_note = ""
            if len(loaded_names) > 1:
                skill_bullets = "\n".join(f"- **{n}**" for n in loaded_names)
                multi_skill_note = f"""
## Multi-Skill Query Detected
The user's query touches **{len(loaded_names)} topics**. Read the SKILL.md for ALL of them:
{skill_bullets}
Address ALL relevant parts of the user's query in your response.
"""

            # Low-confidence routing fallback
            low_confidence_fallback = ""
            if routing_confidence < 0.5 and chain_db_connection_names:
                connections_list = ", ".join(chain_db_connection_names)
                low_confidence_fallback = f"""
## Note: Low Routing Confidence ({routing_confidence:.0%})
The matched skill may not be an exact fit. If no skill file covers the user's question and the query seems data-related, you have database connections available: [{connections_list}].
Read the schema first via `run_shell_command(command="cat /databases/<connection>/schema.md")`, then query with `database_query_tool`.
"""

            # --- 3. Assemble system prompt (extracted helper) ---
            # Build additional mounts info for prompt injection
            _additional_mounts_info = ""
            if agent_shell and agent_shell._additional_mounts:
                lines = []
                for vprefix, _, readonly in agent_shell._additional_mounts:
                    mode_label = "READ-ONLY" if readonly else "READ-WRITE"
                    lines.append(f"- `{vprefix}/` — Additional mounted folder ({mode_label})")
                _additional_mounts_info = "\n".join(lines)

            system_prompt = self._build_skill_system_prompt(
                skills_section=skills_section,
                read_instructions=read_instructions,
                multi_skill_note=multi_skill_note,
                other_skills_text=other_skills_text,
                low_confidence_fallback=low_confidence_fallback,
                enterprise_context_text=enterprise_context_text,
                preference=state.get("preference", ""),
                has_shell=agent_shell is not None,
                db_connection_names=chain_db_connection_names,
                additional_mounts_info=_additional_mounts_info,
            )

            # --- 3b. Inject Knowledge Store context into system prompt ---
            system_prompt = await self._inject_knowledge_context(
                system_prompt, knowledge_store,
                state["agentic_application_id"], query,
            )

            # --- 3c. Inject current user info into system prompt ---
            system_prompt = await self._inject_user_info(system_prompt)

            # --- 4. Build user message with conversation context ---
            context_parts = []
            if not chain_file_ctx_flag:
                if state.get("past_conversation_summary"):
                    context_parts.append(state["past_conversation_summary"])
                if state.get("context_flag", True) and state.get("ongoing_conversation"):
                    try:
                        formatted_conv = await self.chat_service.get_formatted_messages(state["ongoing_conversation"])
                        if formatted_conv:
                            context_parts.append(formatted_conv)
                    except Exception:
                        pass

            user_message = query
            if context_parts:
                user_message = "\n\n".join(context_parts) + f"\n\nUser Query:\n{query}"

            # --- 4b. Enforce prompt size budget before LLM call ---
            try:
                from src.agentos.prompt_budget import estimate_tokens as _est_tokens
                _model_name = state.get("model_name", "")
                _budget = PromptBudget(model_name=_model_name)
                _orig_tokens = _est_tokens(system_prompt)
                system_prompt = _budget.enforce(
                    system_prompt=system_prompt,
                    user_message=user_message,
                    reserved_for_response=4096,
                )
                _final_tokens = _est_tokens(system_prompt)
                if _budget.truncation_log:
                    log.info(
                        f"[SkillAgent] Prompt budget truncated: "
                        + "; ".join(_budget.truncation_log)
                    )
                # Audit: record prompt budget
                _audit.record_prompt_budget(
                    original_tokens=_orig_tokens,
                    final_tokens=_final_tokens,
                    truncation_log=_budget.truncation_log,
                )
            except Exception as _budget_err:
                log.warning(f"[SkillAgent] Prompt budget enforcement skipped: {_budget_err}")

            # --- 5. Execution Mode Dispatch ---
            # Check if there's a pending plan from previous turn (planned mode HITL)
            _pending_plan_json = state.get("_pending_plan", "")
            if _pending_plan_json:
                from src.agentos.execution_modes import route_execution
                _plan_dict = json.loads(_pending_plan_json)
                _plan_skill = state.get("_pending_plan_skill", "")
                _user_msg_lower = query.strip().lower()

                # Detect user intent: confirm, reject, or modify
                _is_confirm = _user_msg_lower in (
                    "confirm", "yes", "execute", "go", "run", "proceed",
                    "approve", "ok", "do it", "execute plan", "run plan",
                )
                _is_reject = _user_msg_lower in (
                    "reject", "no", "cancel", "abort", "stop", "nevermind",
                    "never mind", "discard",
                )

                if _is_reject:
                    # Clear pending plan and respond
                    log.info(f"[SkillAgent] Plan rejected by user for skill '{_plan_skill}'")
                    response_content = "Plan cancelled. How else can I help you?"
                    react_messages = [AIMessage(content=response_content)]
                    loop_errors = []
                    # Clear plan state in return
                    _node2_result_override = {
                        "response": response_content,
                        "executor_messages": react_messages,
                        "errors": errors,
                        "skill_name": _plan_skill or skill_name,
                        "skill_description": "",
                        "routing_method": routing_method,
                        "routing_confidence": routing_confidence,
                        "system_prompt_text": "",
                        "_pending_plan": "",
                        "_pending_plan_skill": "",
                    }
                    writer({"Node Name": "Thinking...", "Status": "Completed"})
                    return _node2_result_override

                elif _is_confirm:
                    # Execute the confirmed plan
                    log.info(f"[SkillAgent] Plan confirmed by user — executing")
                    writer({"raw": {"execution_mode": "planned"},
                            "content": "Plan confirmed — executing..."})
                    _plan_dict["confirmed"] = True

                    # Build skill_runner for plan execution
                    async def _plan_skill_runner(sub_skill_name: str, sub_task: str) -> str:
                        _sub_loader = SkillLoader(str(agent_dir / "skills"))
                        _sub_skill = _sub_loader.load(sub_skill_name)
                        if not _sub_skill:
                            return f"Error: Skill '{sub_skill_name}' not found."
                        _sub_section = self._build_skill_section(sub_skill_name, "Skill", _sub_loader)
                        _sub_prompt = self._build_skill_system_prompt(
                            skills_section=_sub_section,
                            read_instructions=f"\nRead `/skills/{sub_skill_name}/SKILL.md` first.\n",
                            multi_skill_note="", other_skills_text="",
                            low_confidence_fallback="",
                            enterprise_context_text=enterprise_context_text,
                            preference=state.get("preference", ""),
                            has_shell=agent_shell is not None,
                            db_connection_names=chain_db_connection_names,
                            additional_mounts_info=_additional_mounts_info,
                        )
                        _sub_result, _, _ = await self._run_skill_react_loop(
                            llm=llm, tools=tools, tool_map=tool_map,
                            system_prompt=_sub_prompt, user_message=sub_task,
                            writer=writer, state=state, hook_runner=hook_runner,
                            llm_tracker_callback=llm_tracker_callback,
                            tool_interrupt_flag=False, max_iterations=MAX_REACT_ITERATIONS,
                            audit=None, skill_name=sub_skill_name,
                        )
                        return _sub_result

                    _primary_skill_for_plan = None
                    if _plan_skill:
                        _plan_loader = SkillLoader(str(agent_dir / "skills"))
                        _primary_skill_for_plan = _plan_loader.load(_plan_skill)

                    _worker_skills_for_plan = getattr(_primary_skill_for_plan, "worker_skills", []) if _primary_skill_for_plan else []
                    _max_steps_for_plan = getattr(_primary_skill_for_plan, "max_steps", 10) or 10

                    _exec_result = await route_execution(
                        "planned",
                        query=_plan_dict.get("goal", query),
                        writer=writer,
                        skill_runner=_plan_skill_runner,
                        llm=llm,
                        worker_skills=_worker_skills_for_plan,
                        max_steps=_max_steps_for_plan,
                        confirmed_plan=_plan_dict,
                    )

                    response_content = _exec_result.response
                    react_messages = [AIMessage(content=response_content)]
                    loop_errors = _exec_result.errors
                    errors.extend(loop_errors)
                    # Clear plan state after execution
                    _node2_result_override = {
                        "response": response_content,
                        "executor_messages": react_messages,
                        "errors": errors,
                        "skill_name": _plan_skill or skill_name,
                        "skill_description": "",
                        "routing_method": "plan_execution",
                        "routing_confidence": 1.0,
                        "system_prompt_text": "",
                        "_pending_plan": "",
                        "_pending_plan_skill": "",
                    }
                    writer({"Node Name": "Thinking...", "Status": "Completed"})
                    return _node2_result_override

                else:
                    # Treat as modification instructions
                    log.info(f"[SkillAgent] Plan modification requested: '{query[:80]}'")
                    writer({"raw": {"execution_mode": "planned"},
                            "content": "Modifying plan based on your feedback..."})

                    _primary_skill_for_plan = None
                    if _plan_skill:
                        _plan_loader = SkillLoader(str(agent_dir / "skills"))
                        _primary_skill_for_plan = _plan_loader.load(_plan_skill)

                    _worker_skills_for_plan = getattr(_primary_skill_for_plan, "worker_skills", []) if _primary_skill_for_plan else []
                    _max_steps_for_plan = getattr(_primary_skill_for_plan, "max_steps", 10) or 10

                    _exec_result = await route_execution(
                        "planned",
                        query=_plan_dict.get("goal", query),
                        writer=writer,
                        skill_runner=None,
                        llm=llm,
                        worker_skills=_worker_skills_for_plan,
                        max_steps=_max_steps_for_plan,
                        confirmed_plan=_plan_dict,
                        plan_modifications=query,
                    )

                    response_content = _exec_result.response
                    react_messages = [AIMessage(content=response_content)]
                    loop_errors = _exec_result.errors

                    # Plan is still pending — update with modified plan
                    _modified_plan = _exec_result.metadata.get("plan", _plan_dict)
                    _node2_result_override = {
                        "response": response_content,
                        "executor_messages": react_messages,
                        "errors": errors,
                        "skill_name": _plan_skill or skill_name,
                        "skill_description": "",
                        "routing_method": "plan_modification",
                        "routing_confidence": 1.0,
                        "system_prompt_text": "",
                        "_pending_plan": json.dumps(_modified_plan),
                        "_pending_plan_skill": _plan_skill,
                    }
                    writer({"Node Name": "Thinking...", "Status": "Completed"})
                    return _node2_result_override

            # ===================================================================
            # EXECUTION MODE SELECTION — Layer 1 (User-selectable)
            # ===================================================================
            # Priority:
            #   1. User explicitly passes execution_mode in the API request
            #      - "auto" → SmartRouter auto-detection
            #      - specific mode (e.g. "planned", "supervisor") → use directly
            #   2. If not provided (None) → use SKILL.md configured default
            #      (backward-compatible, no SmartRouter)
            # ===================================================================
            _user_requested_mode = state.get("execution_mode")  # from API request
            _skill_configured_mode = "react"
            if _primary_skill:
                _skill_configured_mode = getattr(_primary_skill, "execution_mode", "react") or "react"

            _auto_upgraded = False
            _worker_skills_raw = getattr(_primary_skill, "worker_skills", []) if _primary_skill else []
            _skill_steps_raw = _primary_skill.steps if _primary_skill else []

            # Determine effective execution mode
            if _user_requested_mode and _user_requested_mode.lower() == "auto":
                # --- Layer 1: User chose "auto" → SmartRouter kicks in ---
                _execution_mode = _skill_configured_mode  # start with skill default, SmartRouter may upgrade
                if _primary_skill:
                    try:
                        from src.agentos.execution_modes import SmartRouter

                        # Build all-skills list for multi-domain detection
                        _all_skills_loader = SkillLoader(str(agent_dir / "skills"))
                        _all_skill_names = _all_skills_loader.list_skill_names()
                        _all_skills_meta = []
                        for _sn in _all_skill_names:
                            _sk = _all_skills_loader.load(_sn)
                            if _sk:
                                _all_skills_meta.append({
                                    "name": _sk.name,
                                    "description": _sk.description or "",
                                    "triggers": _sk.triggers if hasattr(_sk, "triggers") else [],
                                })

                        # Only attempt auto-routing if there are multiple skills
                        if len(_all_skills_meta) >= 2:
                            _smart_router = SmartRouter(llm=llm, use_llm_routing=True)
                            _routing_decision = await _smart_router.route(
                                query=query,
                                current_skill_name=skill_name,
                                current_execution_mode=_execution_mode,
                                all_skills=_all_skills_meta,
                                worker_skills=_worker_skills_raw or None,
                            )

                            if _routing_decision.auto_upgraded:
                                _execution_mode = _routing_decision.execution_mode
                                _auto_upgraded = True
                                log.info(
                                    f"[SkillAgent] SmartRouter auto-upgraded to '{_execution_mode}' "
                                    f"(complexity={_routing_decision.complexity_class}, "
                                    f"confidence={_routing_decision.confidence:.2f}): "
                                    f"{_routing_decision.reason}"
                                )
                                writer({"raw": {"auto_routing": True, "complexity": _routing_decision.complexity_class},
                                        "content": f"Smart routing: auto-detected **{_routing_decision.complexity_class}** query → using **{_execution_mode}** mode"})

                                # For auto-detected modes, build worker_skills from all available skills
                                if not _worker_skills_raw and _execution_mode in ("orchestrator", "planned"):
                                    _worker_skills_raw = [
                                        {"name": s["name"], "description": s.get("description", "")}
                                        for s in _all_skills_meta
                                    ]
                        else:
                            log.info(f"[SkillAgent] SmartRouter skipped — only {len(_all_skills_meta)} skill(s) available")
                    except Exception as _sr_err:
                        log.warning(f"[SkillAgent] SmartRouter failed: {_sr_err} — continuing with '{_execution_mode}'")

            elif _user_requested_mode:
                # --- Layer 1: User chose a specific mode → use it directly (override SKILL.md) ---
                _execution_mode = _user_requested_mode.lower()
                log.info(f"[SkillAgent] User-selected execution mode: '{_execution_mode}' (overrides SKILL.md default '{_skill_configured_mode}')")

            else:
                # --- No user selection → use SKILL.md configured default (backward compat) ---
                _execution_mode = _skill_configured_mode
                log.info(f"[SkillAgent] Using SKILL.md configured mode: '{_execution_mode}'")

            if _execution_mode != "react":
                # --- Non-React Mode: Use execution_modes router ---
                from src.agentos.execution_modes import route_execution, validate_execution_mode

                # Validate configuration
                _valid, _val_err = validate_execution_mode(_execution_mode, _skill_steps_raw, _worker_skills_raw)
                if not _valid:
                    log.warning(f"[SkillAgent] {_val_err} Falling back to react mode.")
                    _execution_mode = "react"

            if _execution_mode != "react":
                # Build skill_runner: async callable to invoke sub-skills via ReAct loop
                # This references REAL deployed skills in the agent's workspace
                _available_skill_names = set(SkillLoader(str(agent_dir / "skills")).list_skill_names())

                async def _skill_runner_fn(sub_skill_name: str, sub_task: str) -> str:
                    """
                    Invoke a sub-skill via the ReAct loop.
                    References REAL deployed skills in this agent's workspace.
                    """
                    # Validate skill exists (prevents "Skill not found" errors)
                    if sub_skill_name not in _available_skill_names:
                        available = sorted(_available_skill_names)
                        log.warning(
                            f"[ExecutionRouter] Requested skill '{sub_skill_name}' not found. "
                            f"Available: {available}"
                        )
                        return (
                            f"Error: Skill '{sub_skill_name}' does not exist in this agent. "
                            f"Available skills are: {', '.join(available)}"
                        )

                    _sub_loader = SkillLoader(str(agent_dir / "skills"))
                    _sub_skill = _sub_loader.load(sub_skill_name)
                    if not _sub_skill:
                        return f"Error: Skill '{sub_skill_name}' failed to load."

                    _sub_section = self._build_skill_section(sub_skill_name, "Skill", _sub_loader)
                    _sub_prompt = self._build_skill_system_prompt(
                        skills_section=_sub_section,
                        read_instructions=f"\nRead `/skills/{sub_skill_name}/SKILL.md` first.\n",
                        multi_skill_note="",
                        other_skills_text="",
                        low_confidence_fallback="",
                        enterprise_context_text=enterprise_context_text,
                        preference=state.get("preference", ""),
                        has_shell=agent_shell is not None,
                        db_connection_names=chain_db_connection_names,
                        additional_mounts_info=_additional_mounts_info,
                    )
                    _sub_result, _, _sub_errors = await self._run_skill_react_loop(
                        llm=llm, tools=tools, tool_map=tool_map,
                        system_prompt=_sub_prompt, user_message=sub_task,
                        writer=writer, state=state, hook_runner=hook_runner,
                        llm_tracker_callback=llm_tracker_callback,
                        tool_interrupt_flag=False, max_iterations=MAX_REACT_ITERATIONS,
                        audit=None, skill_name=sub_skill_name,
                    )
                    if _sub_errors:
                        log.warning(f"[ExecutionRouter] Sub-skill '{sub_skill_name}' had errors: {_sub_errors}")
                    return _sub_result

                # Gather iterative-specific params
                _max_iterations = getattr(_primary_skill, "max_iterations", 3) or 3
                _quality_threshold = getattr(_primary_skill, "quality_threshold", 7) or 7
                _eval_criteria = getattr(_primary_skill, "evaluation_criteria", "") or "Completeness, accuracy, clarity, and relevance"
                _initial_instruction = ""
                if _skill_steps_raw and isinstance(_skill_steps_raw[0], dict):
                    _initial_instruction = _skill_steps_raw[0].get("instruction", "")

                _max_supervisor_steps = getattr(_primary_skill, "max_steps", 10) or 10

                log.info(
                    f"[SkillAgent] Routing to execution_mode='{_execution_mode}' "
                    f"for skill '{skill_name}'"
                    + (f" (auto-upgraded)" if _auto_upgraded else "")
                )
                if not _auto_upgraded:
                    writer({"raw": {"execution_mode": _execution_mode},
                            "content": f"Executing skill in **{_execution_mode}** mode"})

                # Build session context for audit/rate-limiting/hooks
                _session_ctx = {
                    "session_id": state.get("session_id", ""),
                    "user_id": state.get("user_id", state.get("created_by", "")),
                    "agent_id": state.get("agent_id", state.get("agentic_application_id", "")),
                    "skill_name": skill_name,
                    "auto_upgraded": _auto_upgraded,
                }

                # Route to the appropriate engine
                _exec_result = await route_execution(
                    _execution_mode,
                    query=query,
                    writer=writer,
                    tool_map=tool_map,
                    steps=_skill_steps_raw,
                    skill_runner=_skill_runner_fn,
                    llm=llm,
                    worker_skills=_worker_skills_raw,
                    max_steps=_max_supervisor_steps,
                    max_iterations=_max_iterations,
                    quality_threshold=_quality_threshold,
                    evaluation_criteria=_eval_criteria,
                    initial_instruction=_initial_instruction,
                    session_ctx=_session_ctx,
                )

                response_content = _exec_result.response
                react_messages = [AIMessage(content=response_content)]
                errors.extend(_exec_result.errors)
                loop_errors = _exec_result.errors

                # If planned mode returned a pending plan, persist it for the next turn
                if _exec_result.metadata.get("plan_pending_confirmation"):
                    _plan_to_store = _exec_result.metadata.get("plan", {})
                    log.info(f"[SkillAgent] Planned mode generated plan — storing for confirmation (plan_id={_exec_result.metadata.get('plan_id')})")
                    # Return early with plan state persisted
                    _node2_result_override = {
                        "response": response_content,
                        "executor_messages": react_messages,
                        "errors": errors,
                        "skill_name": skill_name,
                        "skill_description": "",
                        "routing_method": routing_method,
                        "routing_confidence": routing_confidence,
                        "system_prompt_text": system_prompt,
                        "_pending_plan": json.dumps(_plan_to_store),
                        "_pending_plan_skill": skill_name,
                    }
                    writer({"Node Name": "Thinking...", "Status": "Completed"})
                    return _node2_result_override

            else:
                # --- 5b. Default ReAct loop execution ---
                try:
                    response_content, react_messages, loop_errors = await self._run_skill_react_loop(
                        llm=llm,
                        tools=tools,
                        tool_map=tool_map,
                        system_prompt=system_prompt,
                        user_message=user_message,
                        writer=writer,
                        state=state,
                        hook_runner=hook_runner,
                        llm_tracker_callback=llm_tracker_callback,
                        tool_interrupt_flag=tool_interrupt_flag,
                        max_iterations=MAX_REACT_ITERATIONS,
                        audit=_audit,
                        skill_name=skill_name,
                    )
                except _ToolInterruptSignal as _sig:
                    # The react loop needs HITL approval for a tool.
                    # Serialize the loop state so we can resume after approval.
                    from langchain_core.messages import messages_to_dict
                    _serialized_invoke = json.dumps(messages_to_dict(_sig.invoke_messages))
                    _serialized_react = json.dumps(messages_to_dict(_sig.react_messages))
                    _serialized_tc = json.dumps(_sig.tool_call)
                    _tc = _sig.tool_call
                    log.info(f"[SkillAgent] Tool interrupt signal: tool={_tc.get('name')}, iteration={_sig.iteration}, type={_sig.interrupt_type}")
                    return {
                        "is_tool_interrupted": True,
                        "executor_messages": _sig.react_messages,
                        "errors": errors,
                        "skill_name": skill_name,
                        "skill_description": "",
                        "routing_method": routing_method,
                        "routing_confidence": routing_confidence,
                        "system_prompt_text": system_prompt,
                        "_pending_tool_call": _serialized_tc,
                        "_react_invoke_messages": _serialized_invoke,
                        "_react_messages": _serialized_react,
                        "_react_iteration": _sig.iteration,
                        "_interrupt_type": _sig.interrupt_type,
                        "_interrupt_reason": _sig.reason,
                    }
                errors.extend(loop_errors)

            # Audit: record any errors from the loop
            for err in loop_errors:
                _audit.record_error("react_loop", err)

            # Audit: finalize the request audit trail
            _node2_duration_for_audit = (_node_time.time() - _node2_start) * 1000
            _audit.finalize(
                response_preview=response_content,
                total_duration_ms=_node2_duration_for_audit,
                skill_name=skill_name,
                success=len(loop_errors) == 0,
            )

            writer({"Node Name": "Thinking...", "Status": "Completed"})

            skill_desc = next(
                (s["description"] for s in skill_router.list_skills() if s["name"] == skill_name),
                "",
            )

            # Hook Layer 6: PreResponse — response gate (validate/modify/block)
            if hook_runner:
                try:
                    _pre_response_ctx = {
                        "session_id": state.get("session_id", ""),
                        "agentic_application_id": state.get("agentic_application_id", ""),
                        "skill_name": skill_name,
                        "query": query,
                        "routing_method": routing_method,
                    }
                    response_content = hook_runner.run_pre_response(response_content, _pre_response_ctx)
                except Exception as _pr_err:
                    log.warning(f"[SkillAgent] PreResponse hook error: {_pr_err}")

            # Strip the final no-tool-calling AIMessage from react_messages
            # (matches react agent behaviour — final_response node re-adds it)
            if react_messages and hasattr(react_messages[-1], 'type') and react_messages[-1].type == "ai":
                _last = react_messages[-1]
                if not getattr(_last, 'tool_calls', None):
                    react_messages = react_messages[:-1]

            _node2_result = {
                "response": response_content,
                "executor_messages": react_messages,
                "errors": errors,
                "skill_name": skill_name,
                "skill_description": skill_desc,
                "routing_method": routing_method,
                "routing_confidence": routing_confidence,
                "system_prompt_text": system_prompt,
                # Clear skill interrupt state on completion
                "is_skill_interrupted": False,
                "_skill_verifier_data": "",
            }
            # Hook Layer 2: after_node
            if hook_runner:
                _node2_duration = (_node_time.time() - _node2_start) * 1000
                hook_runner.run_after_node("skill_executor", state, _node2_result, _node2_duration)
            return _node2_result

        # ---- Node 3: Final response (save to DB, update memory) ----
        async def final_response(state: SkillWorkflowState, writer: StreamWriter):
            """Stores conversation and updates memory — mirrors ReactAgent's final_response."""
            import time as _node_time
            _node3_start = _node_time.time()
            # Hook Layer 2: before_node
            if hook_runner:
                hook_runner.run_before_node("final_response", state)

            writer({"Node Name": "Memory Update", "Status": "Started"})
            errors = []
            end_timestamp = get_timestamp()

            try:
                # Save chat message to DB
                self._safe_background_task(self.chat_service.save_chat_message(
                    agentic_application_id=state["agentic_application_id"],
                    session_id=state["session_id"],
                    start_timestamp=state["start_timestamp"],
                    end_timestamp=end_timestamp,
                    human_message=state["query"],
                    ai_message=state["response"],
                ), name="save_chat_message")

                # Save chat to file
                await self.chat_service.save_chat_to_file(
                    agentic_application_id=state["agentic_application_id"],
                    session_id=state["session_id"],
                    start_timestamp=state["start_timestamp"],
                    end_timestamp=end_timestamp,
                    human_message=state["query"],
                    ai_message=state["response"],
                    llm=llm,
                )

                # Update preferences
                self._safe_background_task(
                    self.chat_service.update_preferences_and_analyze_conversation(
                        user_input=state["query"],
                        llm=llm,
                        agentic_application_id=state["agentic_application_id"],
                        session_id=state["session_id"],
                    ),
                    name="update_preferences",
                )

                # Periodically summarize
                config_limits = await self.admin_config_service.get_limits()
                if (len(state["ongoing_conversation"]) + 1) % (2 * config_limits.chat_summary_interval) == 0:
                    self._safe_background_task(self.chat_service.get_chat_summary(
                        agentic_application_id=state["agentic_application_id"],
                        session_id=state["session_id"],
                        llm=llm,
                    ), name="get_chat_summary")

                writer({"raw": {"final_response": "Memory Updated"}, "content": "Memory Updated"})
                writer({"Node Name": "Memory Update", "Status": "Completed"})
            except Exception as e:
                writer({"Node Name": "Memory Update", "Status": "Failed"})
                log.error(f"[SkillAgent] Error in final_response: {e}")
                errors.append(str(e))
                # Hook Layer 1: on_agent_error
                if hook_runner:
                    try:
                        hook_runner.run_on_agent_error(
                            agent_id=state.get("agentic_application_id", ""),
                            session_id=state.get("session_id", ""),
                            error=e,
                            node="final_response",
                        )
                    except Exception:
                        pass  # Never let hook errors crash the response pipeline

            # ---- Enhancement modules: background knowledge/plan/session persistence ----
            agent_id = state["agentic_application_id"]
            session_id = state["session_id"]

            # Knowledge Store: log this interaction as an episode
            if knowledge_store:
                async def _log_episode():
                    try:
                        # Fix #1 — use correct EpisodeEntry field names
                        await knowledge_store.log_episode(EpisodeEntry(
                            agent_id=agent_id,
                            session_id=session_id,
                            query=state["query"],
                            response_summary=state["response"][:500],
                            skill_name=state.get("skill_name", ""),
                            outcome="success",
                            department=state.get("department_name", "General") or "General",
                        ))
                    except Exception as e:
                        log.debug(f"[SkillAgent] Episode logging failed: {e}")
                self._safe_background_task(_log_episode(), name="log_episode")

            # Plan Cache: store successful routing plan
            if plan_cache and state.get("skill_name"):
                async def _store_plan():
                    try:
                        # Extract tool names from executor messages
                        tools_used = []
                        for msg in state.get("executor_messages", []):
                            if hasattr(msg, "name") and msg.name:
                                tools_used.append(msg.name)
                        await plan_cache.store(CachedPlan(
                            agent_id=agent_id,
                            department=state.get("department_name", "General") or "General",
                            query_text=state["query"],
                            skill_name=state["skill_name"],
                            routing_method=state.get("routing_method", ""),
                            routing_confidence=state.get("routing_confidence", 0.0),
                            tools_used=list(dict.fromkeys(tools_used)),  # deduplicate, preserve order
                            outcome="success",
                        ))
                    except Exception as e:
                        log.warning(f"[SkillAgent] Plan cache store failed: {e}")
                self._safe_background_task(_store_plan(), name="store_plan")

            # Session Store: save snapshot for horizontal scaling
            # Fix #9 — run synchronous Redis save in executor to avoid blocking event loop
            if session_store:
                try:
                    snapshot = SessionStore.snapshot_from_state(
                        state=state, agent_id=agent_id, session_id=session_id,
                    )
                    loop = asyncio.get_running_loop()
                    await loop.run_in_executor(None, session_store.save, snapshot)
                except Exception as e:
                    log.debug(f"[SkillAgent] Session snapshot save failed: {e}")

            final_ai = AIMessage(content=state["response"])

            # Hook Layer 2: after_node for final_response
            if hook_runner:
                _node3_elapsed = _node_time.time() - _node3_start
                _node3_duration_ms = _node3_elapsed * 1000
                hook_runner.run_after_node("final_response", state, {"elapsed_sec": round(_node3_elapsed, 3)}, _node3_duration_ms)

            # Hook Layer 1: on_agent_end (entire agent workflow finishing)
            # Fix #4 — use correct state key "skill_name" (not "routed_skill_name")
            if hook_runner:
                _total_elapsed = (_node_time.time() - _node3_start) if _node3_start else 0
                hook_runner.run_on_agent_end(
                    agent_id=state.get("agentic_application_id", ""),
                    session_id=state.get("session_id", ""),
                    response=state.get("response", ""),
                    duration_ms=_total_elapsed * 1000,
                    skill_name=state.get("skill_name", "?"),
                    routing_method=state.get("routing_method", "?"),
                )

            # Hook Layer 7: PostSampling — async fire-and-forget after response
            if hook_runner:
                try:
                    _sampling_ctx = {
                        "session_id": session_id,
                        "agent_id": agent_id,
                        "agentic_application_id": agent_id,
                        "skill_name": state.get("skill_name", ""),
                        "query": state.get("query", ""),
                        "response": state.get("response", ""),
                        "routing_method": state.get("routing_method", ""),
                    }
                    hook_runner.run_post_sampling(_sampling_ctx)
                except Exception:
                    pass  # Never let PostSampling crash the response

            return {
                "ongoing_conversation": AIMessage(content=state["response"]),
                "executor_messages": final_ai,
                "end_timestamp": end_timestamp,
                "errors": errors,
            }

        # ---- Tool interrupt node (HITL approval — runs between nodes, not inside) ----
        async def tool_interrupt_node(state: SkillWorkflowState, writer: StreamWriter):
            """Interrupts the graph for HITL tool approval.

            This node mirrors the react agent's ``tool_interrupt_node``:
            it calls ``interrupt()`` which suspends the graph and waits
            for the user to approve/reject/modify the tool call.

            The pending tool info was persisted in state by ``skill_executor``
            via ``_pending_tool_call``.
            """
            writer({"Node Name": "Tool Interrupt", "Status": "Started"})
            _tc = {}
            try:
                _tc = json.loads(state.get("_pending_tool_call", "{}"))
            except Exception:
                pass
            _tool_name = _tc.get("name", "unknown")
            _tool_args = _tc.get("args", {})
            _tool_call_id = _tc.get("id", "")

            writer({
                "raw": {"tool_verifier": f"Please Confirm me for executing the tool"},
                "content": "Tool execution requires confirmation. Please approve to proceed.",
            })

            # Embed tool metadata so _enrich_interrupted_response can build
            # proper executor_messages for the UI.
            _interrupt_payload = json.dumps({
                "prompt": "approved?(yes/feedback)",
                "tool_name": _tool_name,
                "tool_args": _tool_args,
                "tool_call_id": _tool_call_id,
            })
            approval = interrupt(_interrupt_payload)

            log.info(f"[SkillAgent] tool_interrupt_node: approval={approval} for tool={_tool_name}")
            writer({"Node Name": "Tool Interrupt", "Status": "Completed"})
            return {
                "tool_feedback": approval,
                "is_tool_interrupted": True,
            }

        # ---- Routing: skill_executor → tool_interrupt_node or skill_interrupt_node or final_response ----
        async def skill_executor_router(state: SkillWorkflowState):
            """Routes after skill_executor: if a tool is pending approval,
            go to tool_interrupt_node; if skill verification pending, go to
            skill_interrupt_node; otherwise proceed to final_response."""
            if state.get("is_tool_interrupted") and state.get("_pending_tool_call"):
                log.info(f"[SkillAgent] Routing to tool_interrupt_node (pending tool approval)")
                return "tool_interrupt_node"
            if state.get("is_skill_interrupted") and state.get("_skill_verifier_data"):
                log.info(f"[SkillAgent] Routing to skill_interrupt_node (pending skill approval)")
                return "skill_interrupt_node"
            return "final_response"

        # ---- Skill interrupt node (HITL skill routing approval) ----
        async def skill_interrupt_node(state: SkillWorkflowState, writer: StreamWriter):
            """Interrupts the graph for HITL skill routing approval.

            Suspends the graph and presents the user with the selected skill
            and available alternatives. The user can approve, modify (pick
            a different skill), or reject.
            """
            writer({"Node Name": "Skill Verification", "Status": "Started"})
            _sd = {}
            try:
                _sd = json.loads(state.get("_skill_verifier_data", "{}"))
            except Exception:
                pass

            _selected = _sd.get("selected_skill", "unknown")
            _matched = _sd.get("matched_skills", [])
            _available = _sd.get("available_skills", [])
            _method = _sd.get("routing_method", "")
            _confidence = _sd.get("routing_confidence", 0.0)

            writer({
                "raw": {"skill_verifier": {
                    "selected_skill": _selected,
                    "matched_skills": _matched,
                    "available_skills": _available,
                    "routing_method": _method,
                    "routing_confidence": _confidence,
                }},
                "content": (
                    f"Skill **{_selected}** was selected via **{_method}** routing "
                    f"(confidence: {_confidence}). Please approve, modify, or reject."
                ),
            })

            # Embed skill metadata for _enrich_interrupted_response
            _interrupt_payload = json.dumps({
                "prompt": "approve/reject/<skill_name>",
                "selected_skill": _selected,
                "matched_skills": _matched,
                "available_skills": _available,
                "routing_method": _method,
                "routing_confidence": _confidence,
            })
            approval = interrupt(_interrupt_payload)

            log.info(f"[SkillAgent] skill_interrupt_node: approval={approval} for skill={_selected}")
            writer({"Node Name": "Skill Verification", "Status": "Completed"})
            return {
                "skill_feedback": approval,
                "is_skill_interrupted": True,
            }

        # ---- Routing: skill_interrupt_node → back to skill_executor ----
        async def skill_interrupt_decision(state: SkillWorkflowState):
            """After skill verification, route back to skill_executor
            which will process the feedback in the skill resume fast path."""
            feedback = state.get("skill_feedback", "approve")
            log.info(f"[SkillAgent] Skill feedback='{feedback}', routing back to skill_executor")
            return "skill_executor"

        # ---- Routing: tool_interrupt_node → back to skill_executor ----

        # ---- Routing: tool_interrupt_node → back to skill_executor ----
        async def tool_interrupt_decision(state: SkillWorkflowState):
            """After interrupt approval, route back to skill_executor to
            resume the react loop with the approved tool."""
            feedback = state.get("tool_feedback", "yes")
            if feedback == "yes":
                log.info(f"[SkillAgent] Tool approved, routing back to skill_executor to resume")
                return "skill_executor"
            else:
                # User rejected or provided feedback — route to skill_executor
                # which will handle the rejection in the resume logic
                log.info(f"[SkillAgent] Tool feedback='{feedback}', routing back to skill_executor")
                return "skill_executor"

        # ---- Build the graph ----
        workflow = StateGraph(SkillWorkflowState)

        workflow.add_node("generate_past_conversation_summary", generate_past_conversation_summary)
        workflow.add_node("skill_executor", skill_executor)
        workflow.add_node("tool_interrupt_node", tool_interrupt_node)
        workflow.add_node("skill_interrupt_node", skill_interrupt_node)
        workflow.add_node("final_response", final_response)
        if response_formatting_flag:
            workflow.add_node("formatter", lambda state: InferenceUtils.format_for_ui_node(state, llm))

        workflow.add_edge(START, "generate_past_conversation_summary")
        workflow.add_edge("generate_past_conversation_summary", "skill_executor")

        # skill_executor → conditional: tool_interrupt_node, skill_interrupt_node, or final_response
        workflow.add_conditional_edges(
            "skill_executor",
            skill_executor_router,
            {
                "tool_interrupt_node": "tool_interrupt_node",
                "skill_interrupt_node": "skill_interrupt_node",
                "final_response": "final_response",
            },
        )

        # skill_interrupt_node → back to skill_executor (to resume with approved/modified skill)
        workflow.add_conditional_edges(
            "skill_interrupt_node",
            skill_interrupt_decision,
            {"skill_executor": "skill_executor"},
        )

        # tool_interrupt_node → back to skill_executor (to resume loop)
        workflow.add_conditional_edges(
            "tool_interrupt_node",
            tool_interrupt_decision,
            {"skill_executor": "skill_executor"},
        )

        if response_formatting_flag:
            workflow.add_edge("final_response", "formatter")
            workflow.add_edge("formatter", END)
        else:
            workflow.add_edge("final_response", END)

        log.info("[SkillAgent] Workflow built successfully")
        return workflow
