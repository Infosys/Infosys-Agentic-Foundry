#!/usr/bin/env python3
"""
Skill Agent - Same pattern as dilo_agent.py but loads prompts from SKILL.md files.

Usage:
    from iaf_agent_skills import SkillAgent
    from agent_os import SafeKernel
    
    kernel = SafeKernel(data_root="./data", tenant_id="company", agent_id="assistant")
    agent = SkillAgent(kernel=kernel, skills_path="./skills")
    
    response = agent.run("log my day")  # Routes to dilo skill
"""

import os
import re
import json
import logging
import yaml
import uuid
import time
import threading

from datetime import datetime
from pathlib import Path
from typing import Any

from langchain_core.tools import tool
from langgraph.prebuilt import create_react_agent

from agent_os import SafeKernel
from agent_os.safe_path import (
    SecurityError as PathSecurityError,
    confine_to_root,
    safe_join_under_root,
    validated_path,
)

from .memory import AgentMemory
from .memory_capability import MemoryCapability, memory_capability_enabled
from .taxonomy_routing_capability import TaxonomyRoutingCapability
from .approval_rules import evaluate_rules, compile_rules_to_prompt, escalate_urgency, get_sla_minutes
from .execution import WorkflowEngine, ParallelEngine, SupervisorEngine, OrchestratorEngine, Step, StepResult, ExecutionMode, get_execution_mode
from .planner import PlannerEngine
from .trace_callback import TraceToolCallback
from .tool_governance import govern_tool_batch, govern_tool_call, MCP_FP_UNAVAILABLE
from .tool_gating import tool_allowed_for_skill
from . import cancellation as _run_cancel
from .hook_approval import set_hook_approval, wants_hitl, wants_retry, build_hook_approval
from .react_runtime.factory import resolve_react_runtime
from .react_runtime.native import NativeReactRuntime, ReactRuntimeUnavailable
from .model_reasoning_meta import reasoning_expose_enabled, reasoning_replay_enabled
from . import llm_tracker
from .llm_tracker import LLMTokenTracker
from .runtime_bridge import calculate_cost, default_agent_id, default_tenant_id
from .progress_phases import ProgressPhase, ProgressTracker
from .tool_factory import (
    MAX_INVOKE_DEPTH,
)
from .providers.factory import (
    build_hook_provider,
    build_router_provider,
    build_skill_provider,
    build_tool_provider,
    build_trace_provider,
)
from .prompt_assembler import (
    load_user_profile,
    build_messages_with_history,
    build_local_tree_section,
)
from .implicit_learning import (
    append_learning as _append_learning_impl,
    analyze_implicit_feedback as _analyze_implicit_feedback_impl,
    triage_implicit_signal as _triage_implicit_signal_impl,
    IMPLICIT_CONFIDENCE_THRESHOLDS,
    IMPLICIT_TYPE_MAP,
)
from .memory_md import load_memory_md as _load_memory_md
from .model_call_pipeline import (
    ModelCallBlocked,
    ModelCallPipeline,
    PolicyChatModel,
    model_call_context,
    model_call_pipeline_enabled,
)
from .tool_execution_capability import ToolExecutionCapability

logger = logging.getLogger(__name__)

# Token thresholds for context size warnings (heuristic: 1 token ≈ 4 chars)
_CTX_WARN_TOKENS  = 60_000   # start warning here
_CTX_ERROR_TOKENS = 100_000  # danger zone — 413 risk on most Azure deployments


def dynamic_orchestrator_enabled() -> bool:
    """Return whether router-selected dynamic orchestration is enabled."""
    raw = os.getenv("DYNAMIC_ORCHESTRATOR_ENABLED", "true").strip().lower()
    return raw not in {"0", "false", "no", "off"}


def should_use_dynamic_orchestrator(
    *,
    mode_hint: str,
    skill_execution_mode: ExecutionMode,
    router_execution_mode: str,
) -> bool:
    """Centralize the safe fallback decision for router-selected orchestration."""
    return (
        dynamic_orchestrator_enabled()
        and mode_hint == "orchestrator"
        and skill_execution_mode == ExecutionMode.REACT
        and router_execution_mode != "planned"
    )


def _estimate_context_tokens(messages: list) -> int:
    """Estimate LLM context size using 1 token ≈ 4 chars heuristic (no API call)."""
    total_chars = 0
    for m in messages:
        if hasattr(m, "content"):           # LangChain message object
            content = m.content
        elif isinstance(m, (tuple, list)):  # (role, content) tuples from build_messages_with_history
            content = m[1] if len(m) >= 2 else ""
        elif isinstance(m, dict):           # {"role": ..., "content": ...} dicts
            content = m.get("content", "")
        else:
            content = str(m)
        total_chars += len(str(content))
    return total_chars // 4


def _log_context_size(messages: list, skill: str = "") -> None:
    """Log context token estimate; warn/error when approaching model limits."""
    tokens = _estimate_context_tokens(messages)
    label = f"[{skill}] " if skill else ""
    if tokens > _CTX_ERROR_TOKENS:
        logger.error(
            "%sContext critical: ~%dK tokens (%d messages) — 413 prompt-too-long risk",
            label, tokens // 1000, len(messages),
        )
    elif tokens > _CTX_WARN_TOKENS:
        logger.warning(
            "%sContext growing: ~%dK tokens (%d messages) — approaching limit",
            label, tokens // 1000, len(messages),
        )
    else:
        logger.info(
            "%sContext: ~%dK tokens (%d messages)",
            label, tokens // 1000, len(messages),
        )


def _bounded_text(value: Any, limit: int = 1000) -> str:
    text = "" if value is None else str(value)
    if len(text) <= limit:
        return text
    return text[: max(limit - 3, 0)] + "..."


def _build_observable_reasoning_summary(
    *,
    runtime: str,
    skill_name: str,
    tool_results_detail: list[dict[str, Any]],
    native_turn: dict[str, Any] | None = None,
    limit: int = 1000,
) -> str:
    """Build a UI-safe summary from observable execution metadata."""
    runtime_label = "provider-native React" if runtime == "native" else "LangGraph React"
    tools = tool_results_detail or []
    tool_names: list[str] = []
    for item in tools[:6]:
        name = str(item.get("tool") or "unknown")
        if name not in tool_names:
            tool_names.append(name)
    error_count = sum(1 for item in tools if item.get("has_error"))

    clauses = [f"Used {runtime_label} for skill '{skill_name}'."]
    if tools:
        tool_phrase = ", ".join(tool_names) if tool_names else "tools"
        clauses.append(f"Gathered evidence with {len(tools)} tool call(s): {tool_phrase}.")
        first_input = next((str(item.get("input") or "").strip() for item in tools if item.get("input")), "")
        if first_input:
            clauses.append(f"First evidence lookup: {_bounded_text(first_input, 180)}.")
    else:
        clauses.append("No external tools were needed for this turn.")

    if error_count:
        clauses.append(f"{error_count} tool result(s) reported errors, so the outcome was marked partial.")
    else:
        clauses.append("Tool governance allowed the executed calls and no tool errors were reported.")

    provider_meta = (native_turn or {}).get("provider_metadata") if isinstance(native_turn, dict) else None
    if isinstance(provider_meta, dict):
        model = str(provider_meta.get("model") or "").strip()
        finish_reason = str(provider_meta.get("finish_reason") or "").strip()
        if model or finish_reason:
            parts = []
            if model:
                parts.append(f"model={model}")
            if finish_reason:
                parts.append(f"finish={finish_reason}")
            clauses.append("Native provider metadata: " + ", ".join(parts) + ".")
        provider = str(provider_meta.get("provider") or "").strip()
        if provider and reasoning_expose_enabled(provider):
            preview = _native_reasoning_preview(native_turn, limit=limit)
            if preview:
                clauses.append(f"Native reasoning preview: {preview}")

    clauses.append("Final answer was synthesized from the gathered tool outputs, routing context, and skill instructions.")
    return _bounded_text(" ".join(clauses), limit)


def _native_reasoning_preview(native_turn: dict[str, Any] | None, limit: int = 1000) -> str:
    """Return a bounded native reasoning preview when a provider exposes one."""
    if not isinstance(native_turn, dict):
        return ""
    reasoning = str(native_turn.get("reasoning") or "").strip()
    if reasoning:
        return _bounded_text(reasoning, limit)
    items = native_turn.get("reasoning_items")
    if isinstance(items, list):
        parts: list[str] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            for key in ("summary", "text", "content", "thinking"):
                value = str(item.get(key) or "").strip()
                if value:
                    parts.append(value)
                    break
        return _bounded_text("\n".join(parts), limit)
    return ""


def _resolve_native_max_iterations(config: dict | None, env: dict | None = None, default: int = 8) -> int:
    env = os.environ if env is None else env
    raw = None
    if isinstance(config, dict):
        react_cfg = config.get("react", {})
        if isinstance(react_cfg, dict):
            raw = react_cfg.get("native_max_iterations")
        if raw in (None, ""):
            runtime_cfg = config.get("runtime", {})
            if isinstance(runtime_cfg, dict):
                raw = runtime_cfg.get("react_native_max_iterations")
    if raw in (None, ""):
        raw = env.get("IAF_REACT_NATIVE_MAX_ITERATIONS", default)
    try:
        return max(1, int(raw or default))
    except Exception:
        return max(1, int(default or 8))


def _skill_path_is_personal(skill_path, agent_root) -> bool:
    """True if a skill lives under a per-user (tenant-authored) directory
    ``{agent_root}/users/...`` rather than the trusted global/promoted skills path.
    Used by the untrusted-execution guard to block bundled tool-script execution for
    tenant-authored personal skills while leaving admin-reviewed global skills working."""
    if not skill_path:
        return False
    try:
        # Validate + rebuild both config-derived paths before comparing (CWE-22/73).
        users_root = validated_path(os.path.join(str(agent_root), "users"), label="agent root")
        sp = validated_path(skill_path, label="skill path")
        return sp.is_relative_to(users_root)
    except Exception:
        norm = str(skill_path).replace("\\", "/")
        return "/users/" in norm


def _tenant_root_from_agent_root(agent_root):
    """Tenant root (``agent_root/../..``) from the validated kernel agent root.
    Raises ``PathSecurityError`` when the configured agent root is not a valid path."""
    return validated_path(agent_root, label="agent root").parent.parent


def _tenant_config_dir(tenant_root):
    """``{tenant_root}/shared/config`` confined under the validated kernel tenant root.
    Returns None when no tenant root is set or it fails path validation, so callers
    take the same path they already take without a tenant root."""
    if not tenant_root:
        return None
    try:
        return safe_join_under_root(
            validated_path(tenant_root, label="tenant root"), "shared/config", label="tenant config dir",
        )
    except PathSecurityError as exc:
        logger.warning("Tenant config dir unavailable: %s", exc)
        return None


def _resolve_graph_ref(skill_dir, graph_ref):
    """Resolve a skill's ``graph_ref`` and require it to stay inside the skill folder.
    Raises ``PathSecurityError`` for traversal, invalid segments or an absolute ref
    outside the folder (the graph dispatch caller then falls back to ReAct)."""
    root = validated_path(skill_dir, label="skill path")
    if Path(graph_ref).is_absolute():
        return confine_to_root(validated_path(graph_ref, label="graph_ref"), root, label="graph_ref")
    return safe_join_under_root(root, graph_ref, label="graph_ref")


def _personal_skills_path(enterprise_root, tenant_id, agent_id, user_id):
    """Build ``{enterprise_root}/tenants/{tenant}/agents/{agent}/users/{user}/skills``
    confined under the validated enterprise root. Returns None (no personal skills
    workspace) when the root or any id segment fails path validation."""
    try:
        root = validated_path(enterprise_root, label="enterprise root")
        return safe_join_under_root(
            root,
            f"tenants/{tenant_id}/agents/{agent_id}/users/{user_id}/skills",
            label="personal skills path",
        )
    except PathSecurityError as exc:
        logger.warning("Personal skills path disabled: %s", exc)
        return None


def _is_local_stdio_mcp(conn: dict) -> bool:
    """True if an MCP connection spawns a LOCAL process (direct + stdio transport).
    Brokered `registry` and remote HTTP (`streamable_http`/`sse`) connections return False.
    Used by the untrusted-execution guard to strip local-process MCP from personal skills."""
    try:
        return (
            str(conn.get("type", "")).lower() == "direct"
            and str(conn.get("transport", "")).lower() == "stdio"
        )
    except Exception:
        return False


class SkillAgent:
    """
    Generic ReAct agent - same pattern as dilo_agent.py.

    Differences from dilo_agent.py:
    - Prompt loaded from skills/{skill_name}/SKILL.md (not hardcoded)
    - Routes query to correct skill via _index.yaml
    """

    RECURSION_LIMIT = 200
    SESSION_COMPACT_THRESHOLD = 30   # compact once history exceeds this many turns
    SESSION_KEEP_RECENT = 8          # turns kept verbatim after a compaction
    PENDING_ACTION_TIMEOUT_MINUTES = 10
    # Compact on SIZE too, not just turn count — two 200KB turns blow the context long
    # before turn 30, and the existing size check only *logs* the 413 risk.
    SESSION_COMPACT_CHARS = 120_000
    # How many compacted turns keep a provenance entry (skill / trace id / tools).
    SESSION_SUMMARY_MAX_REFS = 40

    def __init__(
        self,
        kernel: SafeKernel,
        skills_path: str = "./skills",
        user_id: str = None,
        trace_emitter=None,
        enterprise_root: str = None,   # Path to enterprise_root — enables personal skill workspaces
        *,
        skill_provider=None,
        router_provider=None,
        tool_provider=None,
        hook_provider=None,
        trace_provider=None,
    ):
        self.kernel = kernel
        self.skills_path = skills_path
        self.enterprise_root = enterprise_root
        self.user_id = user_id
        self._trace_provider = trace_provider or build_trace_provider(emitter=trace_emitter)
        self.trace_emitter = trace_emitter if trace_emitter is not None else self._trace_provider.get_emitter()
        self._skill_provider = skill_provider
        self._router_provider = router_provider
        self.tool_provider = tool_provider or build_tool_provider()
        self.hook_provider = hook_provider or build_hook_provider()
        self.entitlement_checker = None
        self.entitlement_principal = None
        
        # Note: user_id should be passed to SafeKernel constructor for /me/ to work
        # If kernel.user_id is not set but agent has user_id, warn
        if user_id and not kernel.user_id:
            logger.warning("kernel.user_id not set. Pass user_id to SafeKernel() for /me/ to work.")
        
        # Router and loader. Defaults wrap the existing SkillRouter and
        # SkillLoader so external code can keep using agent.router/agent.loader.
        self.router = router_provider or build_router_provider(skills_path)
        self.loader = skill_provider or build_skill_provider(skills_path)

        if user_id and enterprise_root and ":" not in user_id:
            personal_tenant = str(getattr(kernel, "tenant_id", "") or default_tenant_id())
            personal_agent = default_agent_id()
            personal_path = _personal_skills_path(enterprise_root, personal_tenant, personal_agent, user_id)
            if personal_path is not None:
                self.router.set_personal_path(personal_path)
                self.loader.set_personal_path(personal_path)
        
        # LLM from environment
        self.llm = self._create_llm()
        self.light_llm = self._create_light_llm()  # For cheap classification tasks
        
        # Load agent-specific configuration (skill/tool restrictions)
        self.config = self._load_agent_config()
        
        # Apply skill filtering to router based on config
        self._apply_skill_filter()

        # Optional per-agent Jev (TypeSafe) router — wraps the filtered LLM router.
        self._maybe_wrap_router_with_jev()

        # Current state
        self.current_skill = None
        self.agent = None
        self.agent_config = {"recursion_limit": type(self).RECURSION_LIMIT}  # High limit for complex multi-step workflows
        self.auto_run = False  # If True, skip asking for confirmation before writes
        
        # Conversation history storage - unique per user + timestamp + random uuid
        user_prefix = (user_id or "anon")[:20]  # Limit length
        uuid_suffix = uuid.uuid4().hex[:6]  # 6 random chars
        self.session_id = f"{user_prefix}_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid_suffix}"
        self.parent_session_id = None  # Set when loading a past conversation (fork semantics)
        self.conversation_history = []
        self.reasoning_ref = None  # Provider-tagged replay handle; never raw CoT.
        self._inflight_query = None  # Set at run() start, cleared after _log_conversation()
        self._active_trace_id = ""  # Current run trace id for hook audit correlation
        
        self.session_summary = None  # Stores LLM-generated summary of compacted turns
        self.compaction_count = 0  # Track how many times we've compacted
        self.session_summary_refs = []      # provenance digest of compacted turns
        self.session_summary_pointer = ""   # history file the compacted turns live in
        
        self.knowledge_retrieval_mode = self.config.get("memory", {}).get(
            "knowledge_retrieval", "hybrid"
        )
        logger.info("Knowledge retrieval mode: %s", self.knowledge_retrieval_mode)
        
        # Pending action state for confirmation flow (kernel-level enforcement)
        # Structure: {operation, target, command, skill, timestamp}
        self.pending_action = None
        self.pending_tool_call = None   # Set by stream intercept; cleared after approve/reject
        self.PENDING_ACTION_TIMEOUT_MINUTES = type(self).PENDING_ACTION_TIMEOUT_MINUTES
        self.tool_execution_capability = ToolExecutionCapability()
        
        self.approval_pending = None
        self._hitl_decision_injected = False  # True during resume, suppresses re-trigger
        
        # Entity ontology cache — set per-query in run(), consumed in _load_prompt/query_memory
        self._cached_query_embedding = None  # Embedding computed once per query, reused everywhere
        self._entity_context = None  # Dict from entity_registry.collect_context()

        self.context_loading_mode: str = self.config.get("context", {}).get(
            "context_loading_mode", "table"
        )
        # Path to the Enterprise Context .md file used when mode == "file".
        # Read from config["context"]["context_file_path"]; default None.
        self._context_file_path = self.config.get("context", {}).get(
            "context_file_path", None
        )
        # Per-query instruction block injected into the prompt in file mode.
        # Tells the ReAct agent where to read context. Reset each run().
        self._file_context_block = None
        logger.info("Context loading mode: %s", self.context_loading_mode)
        # RLM (Recursive Language Model) context mode — opt-in tunables, used only when
        # context_loading_mode == "rlm". Read from config["context"]["rlm"].
        self._rlm_cfg = self.config.get("context", {}).get("rlm", {}) or {}
        
        # Cross-skill delegation depth (0 = top-level agent; incremented for children)
        self._invoke_depth = 0

        # Sufficiency checker config — drives iterative reasoning loop in run()
        _suf_cfg = self.config.get("sufficiency", {})
        self.sufficiency_enabled: bool = _suf_cfg.get("enabled", False)
        self.sufficiency_auto_complexity: bool = _suf_cfg.get("auto_complexity", False)
        self.sufficiency_max_iterations: int = int(_suf_cfg.get("max_iterations", 3))
        self.sufficiency_threshold: float = float(_suf_cfg.get("threshold", 0.85))
        self.sufficiency_skip_skills: list = _suf_cfg.get("skip_for_skills", [])
        logger.info("Sufficiency checker: enabled=%s auto_complexity=%s max_iter=%d threshold=%.2f",
                    self.sufficiency_enabled, self.sufficiency_auto_complexity,
                    self.sufficiency_max_iterations, self.sufficiency_threshold)
        
        self.memory = AgentMemory(
            kernel=kernel,
            user_id=user_id,
            session_id=self.session_id,
            llm=self.llm,  # For fact extraction
            light_llm=self.light_llm,  # For lightweight classification tasks
            tenant_id=getattr(kernel, 'tenant_id', ''),
            agent_id=getattr(kernel, 'agent_id', ''),
        )
        self.memory_capability = MemoryCapability(
            self.memory,
            append_learning_fn=_append_learning_impl,
            agent_root=self.kernel.agent_root,
            session_id=self.session_id,
            user_id=self.user_id,
        )

        try:
            from .taxonomy_signal_index import TaxonomySignalIndex as _TSI
            _cfg_ec   = self.config.get("context", {}).get("context_file_path", "")
            _ec_path  = str(self._resolve_context_file(_cfg_ec or "/shared/Enterprise_Context.md"))
            _indexer  = getattr(self.memory, 'knowledge_indexer', None)
            _db_path  = str(getattr(_indexer, 'db_path', None) or "")
            _emb_fn   = getattr(_indexer, '_safe_get_embedding', None)
            _sk_path  = str(getattr(self.router, 'skills_path', ''))
            if _db_path and _sk_path and Path(_ec_path).exists():
                _taxonomy_signal_index = _TSI(
                    ec_path      = _ec_path,
                    db_path      = _db_path,
                    llm          = self.llm,
                    skills_path  = _sk_path,
                    embedding_fn = _emb_fn,
                )
                self._taxonomy_index = TaxonomyRoutingCapability(_taxonomy_signal_index)
                self._taxonomy_index.load()
                logger.info("TaxonomyRoutingCapability: init OK — ec=%s db=%s", _ec_path, _db_path)
            else:
                self._taxonomy_index = None
                logger.debug(
                    "TaxonomySignalIndex: skipped — ec_exists=%s db=%s skills=%s",
                    Path(_ec_path).exists(), bool(_db_path), bool(_sk_path)
                )
        except Exception as _tsi_err:
            self._taxonomy_index = None
            logger.warning("TaxonomySignalIndex init failed (non-fatal): %s", _tsi_err)

        try:
            from .entity_guide_seeder import EntityGuideSeeder as _EGS
            _tn_root_ege   = _tenant_root_from_agent_root(getattr(kernel, 'agent_root', '..'))
            _guide_path    = str(safe_join_under_root(
                _tn_root_ege, "shared/contexts/entity_guide.md", label="entity guide path",
            ))
            _indexer_ege   = getattr(self.memory, 'knowledge_indexer', None)
            _ereg_ege      = getattr(_indexer_ege, 'entity_registry', None) if _indexer_ege else None
            _db_path_ege   = str(getattr(_indexer_ege, 'db_path', None) or "")
            if _ereg_ege and _db_path_ege and Path(_guide_path).exists():
                _eguide_seeder = _EGS(
                    guide_path      = _guide_path,
                    entity_registry = _ereg_ege,
                    db_path         = _db_path_ege,
                )
                _eguide_seeder.load()
                logger.info("EntityGuideSeeder: init OK — guide=%s", Path(_guide_path).name)
            else:
                logger.debug(
                    "EntityGuideSeeder: skipped — guide_exists=%s ereg=%s db=%s",
                    Path(_guide_path).exists(), bool(_ereg_ege), bool(_db_path_ege),
                )
        except Exception as _ege_err:
            logger.warning("EntityGuideSeeder init failed (non-fatal): %s", _ege_err)

        self.hook_runner = self.hook_provider.build_runner(
            agent=self,
            hooks_config=self.config.get("hooks", {}) or {},
            agent_root=str(self.kernel.agent_root),
            trace_emitter=self.trace_emitter,
            tenant_id=str(getattr(self.kernel, "tenant_id", "") or ""),
            agent_id=str(getattr(self.kernel, "agent_id", "") or ""),
        )
        if not hasattr(self, "_model_call_pipeline"):
            self._model_call_pipeline = ModelCallPipeline(self.hook_runner)
        self.llm = self._policy_wrap_llm(self.llm, role="primary")

    def _policy_wrap_llm(self, llm, *, role: str = "primary"):
        """Return a policy-wrapped LLM when the model-call pipeline is enabled."""
        if llm is None or isinstance(llm, PolicyChatModel):
            return llm
        if not model_call_pipeline_enabled():
            return llm
        return PolicyChatModel(
            inner=llm,
            pipeline=getattr(self, "_model_call_pipeline", None),
            model_role=role,
        )

    def _ensure_runtime_providers(self) -> None:
        """Backfill provider attributes on cloned/restored pre-provider agents."""
        if not hasattr(self, "_trace_provider"):
            self._trace_provider = build_trace_provider(emitter=getattr(self, "trace_emitter", None))
        if not hasattr(self, "trace_emitter"):
            self.trace_emitter = self._trace_provider.get_emitter()
        if not hasattr(self, "_skill_provider"):
            self._skill_provider = getattr(self, "loader", None)
        if not hasattr(self, "_router_provider"):
            self._router_provider = getattr(self, "router", None)
        if not hasattr(self, "tool_provider"):
            self.tool_provider = build_tool_provider()
        if not hasattr(self, "hook_provider"):
            self.hook_provider = build_hook_provider()

    def _clear_pending_state(self, *, clear_approval: bool = False) -> None:
        """Atomically clear ALL interactive-HITL pending fields.

        The three pending fields (pending_action, pending_tool_call, approval_pending)
        must move together; clearing only one leaves stale state that wedges later turns
        (e.g. govern's `already_pending` check). Call this everywhere a pending is
        consumed, rejected, expired, or reset. `approval_pending` is owned by the durable
        ApprovalStore TTL, so only clear it when explicitly asked (resolve/reject/clone).
        """
        self.pending_action = None
        self.pending_tool_call = None
        # Drop any warm native runtime holding a paused turn — once the pending is
        # consumed/rejected/expired, resuming a dead turn would be incoherent.
        self._native_runtime = None
        if clear_approval:
            self.approval_pending = None

    def _restore_kernel_skill(self) -> None:
        """Re-bind the kernel's current-skill ContextVar for an approval resume.

        kernel.current_skill is a ContextVar. A resume runs on a fresh
        event-loop/async context (the original run's context copy is gone), so
        the ContextVar would read its default ``None`` and the kernel would fall
        back to ``agent_id`` — denying scope-restricted credentials or resolving
        them under the wrong consumer. Restore it from the resumed agent state
        (``import_state`` repopulates ``self.current_skill``) or the recorded
        skill on the pending action / tool call.
        """
        skill = (
            getattr(self, "current_skill", None)
            or (getattr(self, "pending_action", None) or {}).get("skill")
            or (getattr(self, "pending_tool_call", None) or {}).get("skill")
        )
        if not skill:
            return
        try:
            self.current_skill = skill
            if getattr(self, "kernel", None) is not None:
                self.kernel.current_skill = skill
        except Exception:
            logger.debug("Could not restore kernel current_skill on resume", exc_info=True)

    def execute_approved_action(self, edited_content: str = "") -> str:
        """
        Execute the pending action after user approval.

        Routes to resume_approved_tool_call() for stream-intercepted tool calls,
        or falls back to run_shell_command() for legacy kernel-level blocks.

        Returns:
            Result message from executing the command
        """
        if not self.pending_action:
            return "❌ No pending action to execute"

        # Approval resume runs on a fresh context — rebind the skill consumer so
        # scope-restricted credentials resolve correctly during the resumed action.
        self._restore_kernel_skill()

        command = self.pending_action.get("command")
        if not command:
            self._clear_pending_state()
            return "❌ Invalid pending action (no command)"

        # Stream-intercepted tool call — delegate to resume method
        if command == "__STREAM_INTERCEPT__":
            return self.resume_approved_tool_call(edited_content=edited_content)

        # Legacy kernel-level shell block (echo >, rm, mkdir)
        result = self.kernel.run_shell_command(command, confirmed=True)
        operation = self.pending_action.get("operation", "action")
        target = self.pending_action.get("target", "unknown")
        self._clear_pending_state()
        logger.info("Approved %s on %s: %s", operation, target, result[:100])
        return f"✅ **Approved and executed**\n\n{result}"

    def reject_pending_action(self) -> str:
        """
        Reject the pending action.

        Returns:
            Rejection message
        """
        if not self.pending_action:
            return "No pending action to reject"

        operation = self.pending_action.get("operation", "action")
        target = self.pending_action.get("target", "unknown")
        self._clear_pending_state()

        logger.info("Rejected %s on %s", operation, target)
        
        return f"❌ **Action rejected**\n\nThe {operation} on `{target}` was cancelled."


    def _build_session_ctx(self) -> dict:
        """
        Build a lightweight context dict for hook fire points.
        Called at run() time so skill_name and user_id are always current.
        """
        return {
            "session_id":     self.session_id,
            "agent_id":       getattr(self.kernel, "agent_id", ""),
            "tenant_id":      getattr(self.kernel, "tenant_id", ""),
            "skill_name":     getattr(self, "current_skill", "") or "",
            "user_id":        self.user_id or "",
            "agent_root":     str(self.kernel.agent_root),
            "execution_mode": getattr(self, '_execution_mode', 'react'),
            "run_id":         self.session_id or "",
            "trace_id":       getattr(self, '_active_trace_id', '') or "",
            "entrypoint":     getattr(self, "_entrypoint", "chat") or "chat",
            "queue_item_id":  getattr(self, "_queue_item_id", "") or "",
            "exec_id":        getattr(self, "_queue_exec_id", "") or "",
            "workstream_name": getattr(self, "_mission_workstream", "") or "",
            "mission_item_id": getattr(self, "_mission_item_id", "") or "",
        }

    def _inherit_workflow_child_context(self, worker):
        """Copy parent execution attribution onto a workflow child agent."""
        for attr in (
            "_entrypoint",
            "_queue_item_id",
            "_queue_exec_id",
            "_mission_workstream",
            "_mission_item_id",
        ):
            value = getattr(self, attr, None)
            if value:
                setattr(worker, attr, value)
        return worker

    def get_tool_execution_snapshot(self, limit: int = 50) -> dict:
        """Return a bounded read-only snapshot of passive tool observations."""
        observer = getattr(self, "tool_execution_capability", None)
        if observer is None:
            return {"events": [], "count": 0, "dropped_count": 0}
        events = observer.snapshot(limit=max(0, int(limit or 0)))
        return {
            "events": events,
            "count": len(events),
            "dropped_count": getattr(observer, "dropped_count", 0),
        }

    def _memory_capability_enabled(self) -> bool:
        return memory_capability_enabled()

    def _memory_write_provider(self):
        if self._memory_capability_enabled():
            capability = getattr(self, "memory_capability", None)
            if capability is not None:
                return capability
        return self.memory

    def _log_episode_via_memory_boundary(self, **kwargs):
        return self._memory_write_provider().log_episode(**kwargs)

    def _write_knowledge_via_memory_boundary(self, **kwargs):
        return self._memory_write_provider().write_knowledge(**kwargs)

    def _find_taxonomy_hits_via_boundary(self, query_embedding: list, query_text: str) -> list:
        taxonomy_index = getattr(self, '_taxonomy_index', None)
        if not taxonomy_index or not query_embedding:
            return []
        return taxonomy_index.find_skills(
            query_embedding=query_embedding,
            query_text=query_text,
        )


    # Built-in dangerous shell patterns — active when config.yaml has no hitl.shell_patterns.
    # Covers Cases 3 & 4: destructive kubectl, forced rm, service lifecycle, SQL DDL, curl mutations.
    _DEFAULT_HITL_SHELL_PATTERNS = [
        r"kubectl\s+(delete|drain|cordon|uncordon|taint|scale|patch)\b",
        r"\brm\s+(-[a-zA-Z]*f[a-zA-Z]*\s+|-[a-zA-Z]*r[a-zA-Z]*\s+|--force\s+|--recursive\s+)\S",
        r"\bsystemctl\s+(stop|disable|mask|kill)\b",
        r"\b(pkill|killall)\b",
        r"\b(DROP\s+TABLE|TRUNCATE\s+TABLE|DROP\s+DATABASE|DROP\s+SCHEMA)\b",
        r"\bcurl\b.*(-X\s*(DELETE|PATCH|PUT)|--request\s+(DELETE|PATCH|PUT))\b",
    ]

    # Default SQL mutation patterns — empty so existing deployments see no behavior change.
    # Operators opt in by adding hitl.sql_patterns to config.yaml.
    _DEFAULT_HITL_SQL_PATTERNS: list = []

    def _load_hitl_patterns(self) -> dict:
        """
        Load HITL intercept patterns from config.yaml hitl: section.
        Falls back to built-in defaults when section is absent.
        Cached per agent instance — config is immutable after __init__.
        """
        if hasattr(self, "_hitl_patterns_cache"):
            return self._hitl_patterns_cache
        cfg = getattr(self, "config", {})
        hitl_cfg = cfg.get("hitl", {}) if isinstance(cfg, dict) else {}
        patterns = {
            "dangerous_tools":  hitl_cfg.get("dangerous_tools", []),
            "hitl_skills":      hitl_cfg.get("hitl_skills", []),
            "shell_patterns":   hitl_cfg.get("shell_patterns") or self._DEFAULT_HITL_SHELL_PATTERNS,
            "keyword_patterns": hitl_cfg.get("keyword_patterns", []),
            "sql_patterns":     hitl_cfg.get("sql_patterns", self._DEFAULT_HITL_SQL_PATTERNS),
        }
        self._hitl_patterns_cache = patterns
        return patterns

    def _is_write_call(self, tool_name: str, args: dict) -> bool:
        """Return True if this tool call is a write/delete operation that needs
        confirmation in ask-first (non-auto_run) chat mode."""
        if tool_name == "write_file":
            return True
        if tool_name == "shell":
            cmd = args.get("command", "")
            if re.search(r'(?<![=!<>\-\d])(>>?)\s*\S', cmd):
                return True
            # Basic delete
            if cmd.strip().startswith("rm "):
                return True
            # python3 heredoc/inline script writing to user paths
            _py_write = (".save(", ".to_csv(", ".to_excel(", ".to_parquet(", ".to_json(", ".to_html(")
            _user_paths = ("/local/", "/me/", "/workspace/")
            if "python3" in cmd and any(p in cmd for p in _py_write) and any(u in cmd for u in _user_paths):
                return True
        return False

    def _is_dangerous_call(self, tool_name: str, args: dict) -> tuple:
        """
        Deterministic HITL gate — checks 6 policy cases regardless of auto_run mode.

        Returns:
            (True, reason_str)  — HITL required
            (False, "")         — safe to proceed

        Cases:
            1. Tool name in config hitl.dangerous_tools list
            2. Current skill in config hitl.hitl_skills list
            3. Shell command matches hitl.shell_patterns (kubectl delete, rm -rf, systemctl stop…)
            4. curl with mutating HTTP method — covered by shell_patterns
            5. Any string arg contains a keyword from hitl.keyword_patterns
            6. SQL tool (run_sql / run_sql_query) query matches hitl.sql_patterns
        """
        patterns = self._load_hitl_patterns()

        # Case 1: explicitly blocked tool name
        if tool_name in patterns["dangerous_tools"]:
            return True, f"Tool '{tool_name}' requires human approval (dangerous_tools policy)"

        # Case 2: skill-level HITL — every tool call in this skill needs approval
        current_skill = getattr(self, "current_skill", None) or ""
        if current_skill and current_skill in patterns["hitl_skills"]:
            return True, f"Skill '{current_skill}' requires human approval before tool execution"

        # Cases 3 & 4: shell command / curl pattern matching
        if tool_name == "shell":
            cmd = args.get("command", "")
            for pat in patterns["shell_patterns"]:
                if re.search(pat, cmd, re.IGNORECASE):
                    preview = cmd[:120].replace("\n", " ")
                    return True, f"Dangerous shell operation detected: `{preview}`"

        # Case 5: keyword scan across all string-valued args
        if patterns["keyword_patterns"]:
            all_text = " ".join(str(v) for v in args.values() if isinstance(v, str))
            for kw in patterns["keyword_patterns"]:
                if re.search(kw, all_text, re.IGNORECASE):
                    return True, f"Keyword policy triggered: '{kw}' found in tool arguments"

        # Case 6: SQL mutation gate — only active when hitl.sql_patterns is set in config.yaml
        if patterns["sql_patterns"] and tool_name in ("run_sql", "run_sql_query", "execute_sql", "sql"):
            query = args.get("query", args.get("sql", args.get("statement", "")))
            if isinstance(query, str):
                for pat in patterns["sql_patterns"]:
                    if re.search(pat, query, re.IGNORECASE):
                        preview = query[:100].replace("\n", " ")
                        return True, f"SQL mutation requires human approval: `{preview}`"

        return False, ""

    def _run_with_stream_intercept(self, messages: list, config: dict):
        """
        Replace self.agent.invoke() with a streaming equivalent that intercepts
        tool calls before they execute.

        Two interception layers:
          - is_write:     write/redirect/rm in ask-first chat mode (auto_run=False)
          - is_dangerous: policy-matched dangerous ops in ALL modes (including auto_run=True)

        In auto_run mode an intercepted dangerous call also sets self.approval_pending
        so the queue processor picks it up via the same HITL path as request_human_approval.

        Returns:
            dict {"messages": [...]}  — identical shape to invoke() on normal completion
            "__PENDING__"             — when a call is intercepted (pending_tool_call set)
        """
        collected = list(messages)

        try:
            for chunk in self.agent.stream({"messages": messages}, config, stream_mode="updates"):
                _run_cancel.check_cancelled()  # cooperative stop between stream chunks
                # chunk is {"agent": {...}} or {"tools": {...}}

                if "agent" in chunk:
                    agent_update = chunk["agent"]
                    agent_msgs = agent_update.get("messages", []) if isinstance(agent_update, dict) else []
                    if not isinstance(agent_msgs, list):
                        agent_msgs = [agent_msgs]

                    for msg in agent_msgs:
                        if hasattr(msg, "tool_calls") and msg.tool_calls:
                            for tc in msg.tool_calls:
                                decision = govern_tool_call(self, tc, source="stream_intercept")
                                if not decision.allowed:
                                    if decision.status == "already_pending":
                                        logger.warning(
                                            "Stream intercept: skipping — approval already pending for %s",
                                            self.pending_tool_call.get("name", "?")
                                            if isinstance(self.pending_tool_call, dict) else "?"
                                        )
                                        return "__PENDING__"
                                    if decision.status == "blocked":
                                        collected.extend(agent_msgs)
                                        logger.info("Stream intercept: denied %s — %s", decision.tool_name, decision.reason)
                                        return f"__BLOCKED__|{decision.reason or 'Tool call blocked by policy hook.'}"
                                    collected.extend(agent_msgs)
                                    logger.info("Stream intercept: blocked %s — %s", decision.tool_name, decision.reason)
                                    return "__PENDING__"

                    collected.extend(agent_msgs)

                elif "tools" in chunk:
                    tools_update = chunk["tools"]
                    tool_msgs = tools_update.get("messages", []) if isinstance(tools_update, dict) else []
                    if not isinstance(tool_msgs, list):
                        tool_msgs = [tool_msgs]

                    # Evidence: capture full tool output BEFORE downstream truncation
                    _ec = getattr(self, '_evidence_collector', None)
                    if _ec is not None:
                        for _tm in tool_msgs:
                            _ec.record_tool_result(
                                tool_call_id=getattr(_tm, 'tool_call_id', '') or '',
                                tool_name=getattr(_tm, 'name', '') or '',
                                content=_tm.content if isinstance(
                                    getattr(_tm, 'content', None), str)
                                    else str(getattr(_tm, 'content', '')),
                            )

                    collected.extend(tool_msgs)

        except _run_cancel.RunCancelled:
            raise
        except Exception:
            _run_cancel.check_cancelled()
            logger.warning("Stream intercept failed, falling back to invoke()")
            return self.agent.invoke({"messages": messages}, config)

        return {"messages": collected}


    def _is_complex_query(self, query: str) -> bool:
        """
        Heuristic complexity classifier — no LLM call, works for any domain.

        A query is complex if it is long (many requirements) or
        has multiple sub-tasks joined by connectors (commas, 'and', '—', ';').
        """
        if len(query) > 150:
            return True
        if len(query) < 60:
            return False
        q = query.lower()
        signals = (
            query.count(",")       # listing: "check X, Y, Z"
            + q.count(" and ")     # joining tasks: "check X and do Y"
            + query.count("—")     # clause separation: "do X — then Y"
            + query.count(";")     # explicit multi-part
        )
        return signals >= 3

    def _check_sufficiency(
        self,
        query: str,
        answer: str,
        tool_calls_made: list,
        skill_name: str,
        criteria: list = None,
    ) -> dict:
        """
        Call light_llm to evaluate whether the agent's answer sufficiently
        addresses the original query.

        Returns dict: {sufficient, confidence, missing, continue_prompt}
        Never raises — on any failure returns sufficient=True so the loop exits.
        """
        criteria_block = ""
        if criteria:
            criteria_block = "\n\nSufficiency criteria for this skill:\n" + "\n".join(
                f"- {c}" for c in criteria
            )

        tool_summary = ", ".join(t.get("name", "?") for t in tool_calls_made) if tool_calls_made else "none"

        prompt = f"""You are a pragmatic QA evaluator for an IT operations AI agent.

Original query: {query}
Skill: {skill_name or "general"}
Tool calls made: {tool_summary}
Agent answer (last 3000 chars):
{answer[-3000:]}
{criteria_block}

STRICT SCOPE RULE: Only evaluate against what the user EXPLICITLY asked in the original query.
Do NOT add requirements that are not in the query. Do NOT invent sub-tasks beyond what was requested.

A SUFFICIENT answer:
- Made at least one actual tool/API call (not just said "I would check")
- Addressed the specific things the user asked for — nothing more, nothing less
- Cited real observed data from the tool calls

IMPORTANT BIAS: If the agent made real tool/API calls and produced an answer that addresses
the query — lean towards sufficient=True. An imperfect answer with real data beats no answer.
Only mark sufficient=False if the agent made zero tool calls or completely missed what was asked.

Return valid JSON only — no markdown fences:
{{"sufficient": true/false, "confidence": 0.0-1.0, "missing": ["item1", "item2"], "continue_prompt": "one sentence telling the agent exactly what to check next"}}"""

        try:
            from langchain_core.messages import HumanMessage
            # Verifier model is profile-selectable: high-assurance grades on the primary model,
            # everything else on the cheap light model (default).
            _verifier_llm = self.llm if getattr(self, "_verifier_model", "light") == "primary" else self.light_llm
            _suf_model = getattr(_verifier_llm, 'azure_deployment', None) or getattr(_verifier_llm, 'model_name', None) or getattr(_verifier_llm, 'model', '') or ''
            logger.info("🔍 SUFFICIENCY CHECK  ▸ model=%s (verifier=%s)", _suf_model, getattr(self, "_verifier_model", "light"))
            resp = _verifier_llm.invoke([HumanMessage(content=prompt)])
            raw = resp.content.strip()
            # Strip markdown fences if model wraps in ```json
            if raw.startswith("```"):
                raw = raw.split("```")[1]
                if raw.startswith("json"):
                    raw = raw[4:]
                raw = raw.strip()
            result = json.loads(raw)
            # Ensure all expected keys present
            result.setdefault("sufficient", True)
            result.setdefault("confidence", 1.0)
            result.setdefault("missing", [])
            result.setdefault("continue_prompt", "")
            try:
                from .capture_events import emit_evaluator_result

                data_root = validated_path(str(getattr(getattr(self, "kernel", None), "agent_root", "") or "."), label="agent root")
                for parent in [data_root, *data_root.parents]:
                    candidate = parent / "enterprise_root"
                    if candidate.exists():
                        data_root = candidate
                        break
                trace_id = str(getattr(self, "_active_trace_id", "") or self.session_id or "")
                if trace_id:
                    emit_evaluator_result(
                        data_root=data_root,
                        tenant_id=str(getattr(getattr(self, "kernel", None), "tenant_id", "") or default_tenant_id()),
                        agent_id=str(getattr(getattr(self, "kernel", None), "agent_id", "") or ""),
                        trace_id=trace_id,
                        target_id=trace_id,
                        rubric="sufficiency",
                        evaluator="sufficiency_checker",
                        verdict="sufficient" if bool(result.get("sufficient")) else "insufficient",
                        score=float(result.get("confidence") or 0.0),
                        details={
                            "skill": skill_name,
                            "missing": result.get("missing", []),
                            "continue_prompt": result.get("continue_prompt", ""),
                            "tool_count": len(tool_calls_made or []),
                        },
                    )
            except Exception as emit_exc:
                logger.debug("Sufficiency evaluator capture skipped: %s", emit_exc)
            return result
        except Exception as exc:
            logger.warning("Sufficiency check failed (%s) — treating as sufficient", exc)
            return {"sufficient": True, "confidence": 1.0, "missing": [], "continue_prompt": ""}

    def _run_with_sufficiency(
        self,
        messages: list,
        config: dict,
        query: str,
        skill_name: str,
    ):
        """
        Iterative reasoning loop wrapping _run_with_stream_intercept.

        After each iteration, calls _check_sufficiency() via light_llm.
        If the answer is insufficient and max iterations not reached,
        injects a continue_prompt and reruns.

        Rules:
        - __PENDING__ is always bubbled up immediately (no sufficiency check)
        - Rate limit exceptions propagate unchanged to run()'s except block
        - Returns same dict shape as _run_with_stream_intercept: {"messages": [...]}
        """
        _run_loop = self.sufficiency_enabled or (
            getattr(self, 'sufficiency_auto_complexity', False)
            and self._is_complex_query(query)
        )
        if not _run_loop or (skill_name and skill_name in self.sufficiency_skip_skills):
            logger.info("Sufficiency loop: skipped (complex=%s enabled=%s skill=%s)",
                        self._is_complex_query(query), self.sufficiency_enabled, skill_name)
            return self._run_with_stream_intercept(messages, config)

        # Load skill-level sufficiency_criteria if declared in SKILL.md
        skill_criteria = []
        try:
            skill_data = self.loader.load(skill_name) if skill_name else None
            if skill_data:
                skill_criteria = skill_data.get("sufficiency_criteria", []) or []
        except Exception:
            pass

        from langchain_core.messages import HumanMessage as _HM

        current_messages = list(messages)
        last_result = None

        for iteration in range(1, self.sufficiency_max_iterations + 1):
            _run_cancel.check_cancelled()  # cooperative stop between ReAct rounds
            logger.info("Sufficiency loop: iteration %d/%d", iteration, self.sufficiency_max_iterations)

            result = self._run_with_stream_intercept(current_messages, config)

            # __PENDING__/__BLOCKED__ means governance interrupted the loop — bubble up immediately
            if result == "__PENDING__" or (isinstance(result, str) and result.startswith("__BLOCKED__|")):
                return result

            last_result = result

            # Don't evaluate on final iteration — just return what we have
            if iteration == self.sufficiency_max_iterations:
                logger.info("Sufficiency loop: max iterations reached, returning")
                break

            # Extract answer and tool calls from this iteration's messages
            new_messages = result.get("messages", [])
            answer = ""
            tool_calls_made = []
            for msg in new_messages:
                if hasattr(msg, "tool_calls") and msg.tool_calls:
                    tool_calls_made.extend(msg.tool_calls)
                # Last AIMessage with no tool_calls is the final answer
                if hasattr(msg, "content") and msg.content and not getattr(msg, "tool_calls", None):
                    answer = str(msg.content)

            verdict = self._check_sufficiency(
                query=query,
                answer=answer,
                tool_calls_made=tool_calls_made,
                skill_name=skill_name,
                criteria=skill_criteria,
            )

            logger.info(
                "Sufficiency verdict: sufficient=%s confidence=%.2f missing=%s",
                verdict["sufficient"], verdict["confidence"], verdict.get("missing", [])
            )

            _missing = verdict.get("missing") or []
            _no_gaps = not _missing
            if _no_gaps and (verdict["sufficient"] or verdict["confidence"] >= self.sufficiency_threshold):
                logger.info("Sufficiency loop: answer accepted at iteration %d", iteration)
                break
            if not _no_gaps and (verdict["sufficient"] or verdict["confidence"] >= self.sufficiency_threshold):
                logger.info(
                    "Sufficiency loop: verifier flagged sufficient/confident but listed %d missing item(s); forcing continue",
                    len(_missing),
                )

            # Answer is insufficient — inject continue_prompt and loop
            missing_list = verdict.get("missing", [])
            continue_prompt = verdict.get("continue_prompt", "") or (
                "Please continue investigating. Still missing: " + ", ".join(missing_list)
            )
            logger.info("Sufficiency loop: continuing — %s", continue_prompt)

            # Extend messages with all output from this iteration + the continue signal
            current_messages = new_messages + [_HM(content=continue_prompt)]

        return last_result

    def _native_react_fallback_enabled(self) -> bool:
        """Return whether native React runtime may fall back to LangGraph."""
        react_cfg = self.config.get("react", {}) if isinstance(self.config, dict) else {}
        runtime_cfg = self.config.get("runtime", {}) if isinstance(self.config, dict) else {}
        raw = (
            react_cfg.get("native_fallback_on_error")
            if isinstance(react_cfg, dict) and "native_fallback_on_error" in react_cfg
            else runtime_cfg.get("react_native_fallback_on_error")
            if isinstance(runtime_cfg, dict)
            else None
        )
        if raw is None:
            raw = os.getenv("IAF_REACT_NATIVE_FALLBACK_ON_ERROR", "true")
        return str(raw).strip().lower() not in ("0", "false", "no", "off")

    def _run_with_native_react_runtime(
        self,
        messages: list,
        config: dict,
        query: str,
        skill_name: str,
        emit=None,
    ):
        """Run the provider-native React loop while preserving governance."""
        tools = list(getattr(self, "_react_tools", None) or [])
        system_prompt = str(getattr(self, "_react_system_prompt", "") or "")
        if not tools or not system_prompt:
            self.agent = self._create_agent(skill_name, query=query)
            tools = list(getattr(self, "_react_tools", None) or [])
            system_prompt = str(getattr(self, "_react_system_prompt", "") or "")
        if not tools:
            raise ReactRuntimeUnavailable("Native React runtime has no tools to bind")

        max_iterations = _resolve_native_max_iterations(self.config)
        logger.info("Native React runtime max_iterations=%d", max_iterations)

        runtime = NativeReactRuntime(
            llm=self.llm,
            tools=tools,
            system_prompt=system_prompt,
            max_iterations=max_iterations,
            model_kwargs=self._native_reasoning_model_kwargs(),
            emit=emit,
        )

        def _govern(tool_calls: list[dict]) -> list:
            return govern_tool_batch(self, tool_calls, source="native_react")

        def _record_tool_result(tool_call: dict, content: str) -> None:
            evidence_collector = getattr(self, "_evidence_collector", None)
            if evidence_collector is not None:
                tool_name = str(tool_call.get("name") or "")
                tool_args = tool_call.get("args") if isinstance(tool_call.get("args"), dict) else {}
                if tool_name == "run_sql_query":
                    evidence_collector.record_sql_result(
                        query=str(tool_args.get("query") or ""),
                        result_text=content,
                        database=str(tool_args.get("database") or ""),
                    )
                evidence_collector.record_tool_result(
                    tool_call_id=str(tool_call.get("id") or ""),
                    tool_name=tool_name,
                    content=content,
                )

        result = runtime.run(
            messages=messages,
            config=config,
            govern_batch=_govern,
            record_tool_result=_record_tool_result,
        )
        self._last_native_react_turn = runtime.last_turn.to_safe_dict() if runtime.last_turn else {}
        if result == "__PENDING__" and getattr(runtime, "pending_resume", None):
            self._native_runtime = runtime
        else:
            self._native_runtime = None
        return result

    def resume_approved_tool_call(self, edited_content: str = "") -> str:
        """
        Execute the intercepted tool call after user approval.
        Optionally accepts edited content from the UI textarea.

        Returns:
            Result string shown to the user.
        """
        tc = getattr(self, "pending_tool_call", None)
        if not tc:
            return "❌ No pending tool call to execute"

        # Approval resume runs on a fresh context — rebind the skill consumer so
        # scope-restricted credentials resolve correctly during the resumed call.
        self._restore_kernel_skill()

        _rt = getattr(self, "_native_runtime", None)
        if _rt is not None and getattr(_rt, "pending_resume", None):
            return self._resume_native_turn(_rt, edited_content)

        result = self._execute_held_tool_call(tc, edited_content)
        self._clear_pending_state()
        return f"✅ **Approved and executed**\n\n{result}"

    def _execute_held_tool_call(self, tc: dict, edited_content: str = "") -> str:
        """Execute ONE approved held tool call with the correct kernel-confirmed
        semantics and return the raw result string.

        shell/write_file MUST run via the kernel with confirmed=True — executing them
        through the bound react tool would re-apply the auto_run gate (confirmed=False
        when Human Approval is on), so the kernel would just return the pending sentinel
        again. Other tools (run_sql_query, …) run via the bound tool / tools_map.

        Does NOT clear pending state or format the response — callers do that. Shared by
        resume_approved_tool_call (single-tool) and _resume_native_turn (continue-turn).
        """
        tool_name = tc.get("name", "")
        args = tc.get("args", {}) or {}
        _cmd = args.get("command", "") if isinstance(args, dict) else ""
        try:
            if tool_name == "write_file":
                path = args.get("path", "")
                content = edited_content if edited_content else args.get("content", "")
                append = args.get("append", False)
                result = self.kernel.write_file(path, content, append=append)
                logger.info("Approved write_file: %s (%d chars)", path, len(content))

            elif tool_name == "shell":
                command = edited_content if edited_content else args.get("command", "")
                _cmd = command
                # Heredoc Python (python3 - << 'EOF') can't run via kernel's Python3 sandbox
                # in stdin mode. Extract the script, write to a temp file, run that instead.
                import re as _re, os as _os
                _heredoc = _re.search(r"python3\s+-\s+<<\s*['\"]?EOF['\"]?\s*\n(.*?)\nEOF", command, _re.DOTALL | _re.IGNORECASE)
                if _heredoc:
                    _script = _heredoc.group(1)
                    import uuid as _uuid
                    _vpath = f"/workspace/.agentpro_{_uuid.uuid4().hex[:8]}.py"
                    self.kernel.write_file(_vpath, _script)
                    try:
                        result = self.kernel.run_shell_command(f"python3 {_vpath}", confirmed=True)
                        logger.info("Approved shell (heredoc→vpath): %s", _vpath)
                    finally:
                        try:
                            _real = self.kernel._resolve_path(_vpath)
                            _os.unlink(str(_real))
                        except Exception:
                            pass
                else:
                    result = self.kernel.run_shell_command(command, confirmed=True)
                    logger.info("Approved shell: %s", command[:80])

            else:
                _scope_skill = tc.get("skill") or getattr(self, "current_skill", None)
                # Stale-approval guard — run BEFORE using any tool (already-bound OR
                # rebuilt), so changing/removing the skill's MCP connection after the
                # approval was queued can never be bypassed. If this call recorded an
                # MCP-config fingerprint when it was approved and the skill's config no
                # longer matches (including the connection now being GONE → current
                # None), refuse: the tool would target a different server than reviewed.
                _orig_fp = tc.get("_mcp_config_fp") if isinstance(tc, dict) else None
                if _orig_fp is not None:
                    _now_fp = self._skill_mcp_fingerprint(_scope_skill)
                    # Fail closed when the attestation is unavailable on EITHER side
                    # (couldn't be computed), or when the config changed (incl. the
                    # connection now being GONE → current None).
                    _unattestable = (_orig_fp == MCP_FP_UNAVAILABLE) or (_now_fp == MCP_FP_UNAVAILABLE)
                    if _unattestable or _orig_fp != _now_fp:
                        logger.warning(
                            "Refusing held call '%s' on skill '%s': %s (approved=%s current=%s).",
                            tool_name, _scope_skill,
                            "MCP config attestation unavailable" if _unattestable else "MCP config changed",
                            _orig_fp, _now_fp,
                        )
                        return (
                            f"❌ Approval not executed: the MCP server configuration for skill "
                            f"'{_scope_skill}' could not be verified unchanged since approval "
                            f"(it changed, or the attestation was unavailable). Please re-run the "
                            f"action and approve it again."
                        )
                tool = self._tool_by_name_map().get(tool_name)
                if tool is None and _scope_skill:
                    # Cold resume: this SkillAgent instance never ran _create_agent()
                    # (e.g. rebuilt by state.get_or_create() after the original one
                    # expired while this call sat in the approval queue), so
                    # self._react_tools — including MCP-discovered tools — is empty.
                    # Rebuild it for the held call's skill via _create_agent(), which
                    # threads the credential scope EXPLICITLY to the MCP bridge (no
                    # reliance on process-global env — isolated across concurrent
                    # resumes), instead of failing the call as unknown.
                    try:
                        self._create_agent(_scope_skill)
                        tool = self._tool_by_name_map().get(tool_name)
                        if tool is not None:
                            logger.info(
                                "Rebuilt tools for skill '%s' to resume held call '%s' (cold resume)",
                                _scope_skill, tool_name,
                            )
                    except Exception:
                        logger.warning(
                            "Could not rebuild tools for skill '%s' while resuming '%s'",
                            _scope_skill, tool_name, exc_info=True,
                        )
                if tool is not None:
                    _res = tool.invoke(args)
                    result = _res if isinstance(_res, str) else str(_res)
                    logger.info("Approved tool '%s' resumed via bound tool", tool_name)
                else:
                    _fn = self._get_tools_map().get(tool_name) if hasattr(self, "_get_tools_map") else None
                    if _fn is not None:
                        _res = _fn(**args) if isinstance(args, dict) else _fn(args)
                        result = _res if isinstance(_res, str) else str(_res)
                        logger.info("Approved tool '%s' resumed via tools_map", tool_name)
                    else:
                        result = f"❌ Unknown tool: {tool_name}"

        except Exception as e:
            result = f"❌ Execution error: {e}"

        # If shell/script produced no output, try to surface the saved file path.
        if not result or not result.strip() or result.strip() == "(no output)":
            import re as _re2
            _path_match = _re2.search(r"['\"](/(?:me|workspace|local)/[^'\"]+\.\w+)['\"]", _cmd or "")
            if _path_match:
                result = f"File saved to `{_path_match.group(1)}`"
            else:
                result = "Command completed successfully"
        return result

    def _tool_by_name_map(self) -> dict:
        """Map of tool_name -> bound LangChain tool, from the agent's react tools.
        Used by resume_approved_tool_call to execute ANY approved held tool."""
        tools = getattr(self, "_react_tools", None) or []
        return {getattr(t, "name", ""): t for t in tools if getattr(t, "name", "")}

    def _skill_mcp_fingerprint(self, skill_name: str | None) -> str | None:
        """Stable hash of the *effective* MCP connection targets (non-secret routing
        fields only) for a skill. Tri-state return:

          * ``None``                 — the skill genuinely has NO MCP connections, so
                                       there is nothing to attest (no guard needed).
          * ``"<hash>"``             — the attested fingerprint.
          * ``MCP_FP_UNAVAILABLE``   — the attestation could NOT be computed (a
                                       transient skill-load/config error). This is
                                       distinct from None so callers FAIL CLOSED
                                       (refuse the approval) instead of silently
                                       skipping the stale-config guard.

        Covers the SAME merged set ``_create_agent`` builds the bridge from — both
        agent-level ``config["mcp"]["connections"]`` and skill-level
        ``skill.mcp_connections`` (skill overrides agent by name, mirroring
        ``MCPToolBridge.from_merged_config``). A held call served by an agent-level /
        shared connection is therefore covered too.

        Used to detect a stale approval: a held MCP tool call is durably queued, but
        if a connection's endpoint/command/filters change before the human approves,
        a cold resume would rebuild the tool against the NEW config and send the
        approved call to a different server than was reviewed. Comparing this
        fingerprint lets the resume reject such a stale approval.
        """
        try:
            agent_conns = []
            _cfg = getattr(self, "config", None)
            if isinstance(_cfg, dict):
                agent_conns = ((_cfg.get("mcp") or {}).get("connections")) or []
            skill = self.loader.load(skill_name) if skill_name else None
            skill_conns = getattr(skill, "mcp_connections", None) or []
            # Merge by name, skill overriding agent — same precedence as from_merged_config.
            merged: dict[str, dict] = {}
            for c in list(agent_conns) + list(skill_conns):
                if isinstance(c, dict) and c.get("name"):
                    merged[str(c.get("name"))] = c
            conns = list(merged.values())
            if not conns:
                return None  # genuinely no MCP connections — nothing to attest
            import hashlib as _hashlib
            _fields = ("name", "type", "transport", "url", "command", "args",
                       "server_filter", "tool_filter")
            _norm = sorted(
                ({k: c.get(k) for k in _fields if k in c} for c in conns),
                key=lambda d: str(d.get("name", "")),
            )
            _blob = json.dumps(_norm, sort_keys=True, default=str)
            return _hashlib.sha256(_blob.encode("utf-8")).hexdigest()[:16]
        except Exception:
            # Could NOT produce the attestation — fail closed (NOT None), so the guard
            # is enforced rather than skipped after a transient load/config error.
            logger.warning(
                "MCP fingerprint computation failed for skill '%s'; failing closed",
                skill_name, exc_info=True,
            )
            return MCP_FP_UNAVAILABLE

    def _resume_native_turn(self, runtime, edited_content: str = "") -> str:
        """Resume a paused native-React turn after approval: run the held call(s), then
        continue the governed loop so the model finishes the task. If a NEW call is
        blocked during the continuation, re-arm the pending and return a fresh
        confirmation prompt (multi-step HITL). Otherwise return the final answer."""
        rs = getattr(runtime, "pending_resume", None) or {}
        held_ids = {str((tc or {}).get("id") or "") for tc in (rs.get("tool_calls") or [])}

        self._clear_pending_state()

        def _govern(tool_calls: list[dict]) -> list:
            return govern_tool_batch(self, tool_calls, source="native_react")

        def _record(tool_call: dict, content: str) -> None:
            ec = getattr(self, "_evidence_collector", None)
            if ec is not None:
                ec.record_tool_result(
                    tool_call_id=str(tool_call.get("id") or ""),
                    tool_name=str(tool_call.get("name") or ""),
                    content=content,
                )

        def _execute_held(tool_call: dict) -> str:
            _edit = edited_content if str((tool_call or {}).get("id") or "") in held_ids else ""
            return self._execute_held_tool_call(tool_call, _edit)

        try:
            result = runtime.resume_and_continue(
                config=None, govern_batch=_govern, record_tool_result=_record,
                execute_held=_execute_held,
            )
        except Exception as e:
            self._clear_pending_state()
            self._native_runtime = None
            return f"❌ Execution error: {e}"

        self._last_native_react_turn = runtime.last_turn.to_safe_dict() if runtime.last_turn else {}

        if result == "__PENDING__":
            # A new tool call was blocked while finishing the task. govern_tool_batch
            # already armed pending_tool_call; keep the runtime for the next approval.
            self._native_runtime = runtime
            return self._build_stream_intercept_pending(getattr(self, "current_skill", "") or "")
        if isinstance(result, str) and result.startswith("__BLOCKED__|"):
            self._clear_pending_state()
            self._native_runtime = None
            return f"⚠️ Tool call blocked by policy hook: {result.split('|', 1)[1]}"

        # Completed — clear the held state and surface the model's final answer.
        self._clear_pending_state()
        self._native_runtime = None
        return self._extract_final_text(result)

    def _extract_final_text(self, result) -> str:
        """Pull the final assistant text out of a native-runtime result dict."""
        try:
            msgs = result.get("messages") if isinstance(result, dict) else None
            if msgs:
                content = getattr(msgs[-1], "content", msgs[-1])
                return content if isinstance(content, str) else str(content)
        except Exception:
            pass
        return "Command completed successfully"

    def _build_stream_intercept_pending(self, skill_name: str = "") -> str:
        """Build the legacy pending_action + confirmation text for a stream-intercept
        block. Shared by agent.run() and the re-pause case in _resume_native_turn.

        Describes ANY tool — not just shell/write_file — so the confirmation prompt
        shows the real target (e.g. the SQL for run_sql_query) and a correct operation
        label (the tool name) instead of a blank target labelled "shell"."""
        tc = getattr(self, "pending_tool_call", {}) or {}
        tool_name = tc.get("name", "tool")
        args = tc.get("args", {}) if isinstance(tc.get("args"), dict) else {}
        operation, target = self._describe_pending_call(tool_name, args)
        _ap = getattr(self, "approval_pending", None)
        _approval_id = _ap.get("approval_id") if isinstance(_ap, dict) else None
        self.pending_action = {
            "operation": operation,
            "target": target,
            "command": "__STREAM_INTERCEPT__",
            "tool_name": tool_name,
            "skill": skill_name or getattr(self, "current_skill", "") or "",
            "approval_id": _approval_id,
            "timestamp": datetime.now(),
        }
        logger.info("Stream intercept pending: %s on %s", operation, target[:80])
        return (
            f"⚠️ **Confirmation Required**\n\n**Operation:** {operation}\n"
            f"**Target:** `{target}`\n\nPlease approve or reject this action."
        )

    @staticmethod
    def _describe_pending_call(tool_name: str, args: dict) -> tuple[str, str]:
        """Return (operation_label, target_text) for a held tool call, for display in
        the approval prompt. write_file/shell keep their familiar labels; every other
        tool is labelled by its own name with the most meaningful argument as target."""
        if tool_name == "write_file":
            operation = "append" if args.get("append") else "write"
        elif tool_name == "shell":
            operation = "shell"
        else:
            operation = tool_name or "tool"
        # Pick the most human-meaningful arg as the target, across tool types.
        target = ""
        for key in ("path", "command", "query", "sql", "code", "url", "name", "reason"):
            val = args.get(key)
            if val:
                target = str(val)
                break
        if not target and args:
            for val in args.values():
                if val:
                    target = str(val)
                    break
            if not target:
                target = str(args)
        return operation, target[:200]

    def reject_pending_tool_call(self) -> str:
        """Reject the intercepted tool call."""
        tc = getattr(self, "pending_tool_call", None)
        if not tc:
            return "No pending tool call to reject"
        tool_name = tc.get("name", "")
        target = tc.get("args", {}).get("path") or tc.get("args", {}).get("command", "")[:60]
        self._clear_pending_state()
        logger.info("Rejected %s on %s", tool_name, target)
        return f"❌ **Action rejected**\n\nThe {tool_name} on `{target}` was cancelled."

    def _get_history_path(self) -> Path:
        """Get path to session log file (unified with episodic memory)."""
        # Store in memory/history/{date}/{session_id}.jsonl — single source of truth
        session_dir = self.kernel.agent_root / "memory" / "history" / datetime.now().strftime("%Y-%m-%d")
        session_dir.mkdir(parents=True, exist_ok=True)
        return session_dir / f"{self.session_id}.jsonl"
    
    def _load_agent_config(self) -> dict:
        """
        Load agent-specific configuration from config.yaml.
        
        If no config exists, returns empty dict (all skills/tools allowed).
        This ensures backward compatibility - existing agents work without config.
        
        Returns:
            Agent configuration dict, or {} if no config file
        """
        config_path = self.kernel.agent_root / "config.yaml"
        
        if not config_path.exists():
            logger.info("No config.yaml found, using defaults (all skills/tools allowed)")
            return {}
        
        try:
            config = yaml.safe_load(config_path.read_text(encoding='utf-8'))
            agent_name = config.get("agent", {}).get("name", "unnamed")
            skills_mode = config.get("skills", {}).get("mode", "all")
            logger.info("Loaded agent config: '%s', skills.mode=%s", agent_name, skills_mode)
            return config or {}
        except Exception as e:
            logger.warning("Error loading config.yaml: %s, using defaults", e)
            return {}
    
    def _apply_skill_filter(self):
        """Apply skill filtering based on agent config."""
        skills_config = self.config.get("skills", {})
        mode = skills_config.get("mode", "all")
        
        if mode == "all":
            return  # No filtering needed
        
        allowed = None
        denied = None
        
        if mode == "allowlist":
            allowed = skills_config.get("allowed", [])
            logger.info("Skill allowlist active: %s", allowed)
        elif mode == "denylist":
            denied = skills_config.get("denied", [])
            logger.info("Skill denylist active: %s", denied)
        
        self.router.set_skill_filter(allowed=allowed, denied=denied)
    
    def _maybe_wrap_router_with_jev(self):
        """Opt-in per agent via config.yaml `router: {provider: jev, ...}`. Default: unchanged.

        Wraps the (already skill-filtered) router in a JevRouterProvider so the Jev
        Choice call sees exactly this agent's candidate skills, with automatic
        confidence-gated fallback to the LLM router.
        """
        router_cfg = self.config.get("router", {}) if isinstance(self.config, dict) else {}
        if str(router_cfg.get("provider", "")).lower() != "jev":
            return
        try:
            from iaf_agent_skills.providers_default.jev_router_provider import JevRouterProvider
            self.router = JevRouterProvider(self.router, config=router_cfg)
            logger.info("Router: Jev enabled for this agent (config=%s)", router_cfg)
        except Exception as e:
            logger.warning("Router: Jev wrap failed, staying on LLM router: %s", e)
    
    def _get_allowed_tools(self) -> list:
        """Get list of tools this agent is allowed to use."""
        tools_config = self.config.get("tools", {})
        allowed = tools_config.get("allowed", None)
        
        # Default: all tools allowed if no config
        if allowed is None:
            allowed = ["shell", "write_file", "run_sql_query", "query_memory",
                       "invoke_skill", "invoke_plan", "create_plan", "context_query",
                       "fetch_canonical"]

        return [
            tool_name for tool_name in allowed
            if self._entitlement_allowed("use", "tool", tool_name, {"user_id": self.user_id})
        ]

    def set_entitlement_context(self, principal=None, checker=None):
        """Attach request-scoped entitlement context supplied by Studio."""
        self.entitlement_principal = principal
        self.entitlement_checker = checker
        if hasattr(self.kernel, "set_entitlement_context"):
            self.kernel.set_entitlement_context(principal, checker)

    def _entitlement_allowed(self, action: str, resource_type: str, resource_id: str, context: dict = None) -> bool:
        if not self.entitlement_checker:
            return True
        try:
            return bool(self.entitlement_checker(action, resource_type, resource_id, context or {}))
        except Exception as exc:
            logger.warning("Entitlement check failed for %s:%s action=%s: %s", resource_type, resource_id, action, exc)
            return False

    def _assert_skill_entitled(self, skill_name: str, action: str = "use"):
        if not self._entitlement_allowed(action, "skill", skill_name, {"user_id": self.user_id}):
            raise PermissionError(f"Access denied: skill '{skill_name}' is not permitted for this user")

    def _mcp_connection_allowed(self, conn: dict, skill_name: str) -> bool:
        """Check entitlement for an MCP connection before tool discovery."""
        if os.getenv("EXTERNAL_ACCESS_ENFORCE_MCP", os.getenv("EXTERNAL_ACCESS_ENABLED", "false")).lower() != "true":
            return True
        if not self.entitlement_checker:
            # Fail closed, matching the kernel: governance is on but nobody bound a principal.
            logger.warning(
                "MCP governance: no principal bound for agent user=%s — denying connection %s. "
                "The code path that built this agent must call set_entitlement_context().",
                self.user_id, conn.get("name") or conn.get("url") or "unknown",
            )
            return False
        conn_name = str(conn.get("name") or conn.get("url") or "unknown")
        context = {"skill": skill_name, "connection": conn_name}
        if self._entitlement_allowed("call", "mcp", conn_name, context):
            return True
        try:
            from agent_os.external_access import resources_for_mcp
            linked = resources_for_mcp(self.kernel.tenant_root, conn_name)
            if any(self._entitlement_allowed("access", resource.resource_type, resource.resource_id, context) for resource in linked):
                return True
            if not linked and os.getenv("EXTERNAL_ACCESS_UNKNOWN_MODE", "audit").lower() != "deny":
                logger.info("MCP connection '%s' allowed in audit mode (no registry mapping)", conn_name)
                return True
        except Exception as exc:
            logger.warning("MCP entitlement lookup failed for %s: %s", conn_name, exc)
        logger.warning("MCP connection '%s' denied by entitlement policy", conn_name)
        return False

    @staticmethod
    def _summarize_ui_blocks(response: str) -> str:
        """Replace ```ui:type {...}``` blocks with short human-readable summaries.
        
        Uses generic JSON introspection — works for any ui: component type
        without per-type code. New UI types get useful summaries automatically.
        """
        def _summarize_block(match):
            ui_type = match.group(1)
            json_str = match.group(2).strip()
            try:
                props = json.loads(json_str)
            except (json.JSONDecodeError, TypeError):
                return f"[Displayed {ui_type} component]"
            
            hints = []
            # 1. Extract title/label/message (nearly every component has one)
            for key in ("title", "label", "message"):
                if key in props and isinstance(props[key], str):
                    hints.append(props[key][:80])
            # 2. Count arrays (rows, cards, buttons, fields, datasets)
            for key, val in props.items():
                if isinstance(val, list):
                    hints.append(f"{len(val)} {key}")
            # 3. Fallback: grab first short string value for minimal context
            if not hints:
                for key, val in props.items():
                    if isinstance(val, str) and len(val) < 100:
                        hints.append(val)
                        break
            
            detail = ": " + ", ".join(hints) if hints else ""
            return f"[Displayed {ui_type}{detail}]"
        
        return re.sub(r'```ui:(\w+)\s*([\s\S]*?)```', _summarize_block, response)

    def _build_reasoning_ref_from_last_turn(self) -> dict | None:
        """Build a small replay reference from the last native turn, if enabled.

        This intentionally stores only handles/metadata (for example Azure
        ``response_id``), never raw reasoning items or encrypted provider blobs.
        """
        native_turn = getattr(self, "_last_native_react_turn", None) or {}
        if not isinstance(native_turn, dict):
            return None
        provider_meta = native_turn.get("provider_metadata") or {}
        provider = str(provider_meta.get("provider") or "").strip()
        response_id = str(native_turn.get("response_id") or provider_meta.get("response_id") or "").strip()
        if not provider or not response_id:
            return None
        if not reasoning_replay_enabled(provider):
            return None
        return {
            "provider": provider,
            "response_id": response_id,
            "model": str(provider_meta.get("model") or ""),
        }

    def _native_reasoning_model_kwargs(self) -> dict:
        """Return request-scoped model kwargs for reasoning replay.

        ModelRegistry caches LLM instances by role, so never mutate ``self.llm``
        with a session-specific response id. Passing kwargs through the runtime
        keeps replay scoped to this single request.
        """
        ref = self.reasoning_ref if isinstance(self.reasoning_ref, dict) else None
        if not ref:
            return {}
        provider = str(ref.get("provider") or "").strip()
        response_id = str(ref.get("response_id") or "").strip()
        if not provider or not response_id or not reasoning_replay_enabled(provider):
            return {}
        llm_type = str(getattr(self.llm, "_llm_type", "") or "")
        if provider in {"azure", "azure_openai"} and llm_type == "azure-responses-raw":
            if response_id.startswith("resp"):
                return {"previous_response_id": response_id}
        return {}

    def _log_conversation(self, user_input: str, skill: str, tool_calls: list, response: str,
                          llm_visible_limit: int = 0):
        """Update in-memory conversation context (file write handled by async log_episode).

        The in-memory conversation_history gets a summarized version where
        ui: blocks are replaced with short descriptions, so the LLM can
        understand what was shown without being confused by raw JSON markup.

        File-level audit logging is handled exclusively by log_episode() in the
        async background thread — single writer to memory/history/.

        ``llm_visible_limit`` (0 = unlimited, the ReAct default) caps only the
        ``response`` field — what future turns re-read via _build_messages_with_history.
        ``response_raw`` always keeps the full text for replay/resume. Used by the
        early-return execution modes, whose outputs (a workflow execution summary, an
        RLM proposal list) run to several KB and would otherwise be re-injected into
        every subsequent prompt.
        """
        evidence_bundle = getattr(self, "_evidence_bundle", None) or {}
        try:
            from .vertex_chat import _strip_image_data_urls
            response_for_history = _strip_image_data_urls(response) if isinstance(response, str) else response
            response_raw_for_history = _strip_image_data_urls(response) if isinstance(response, str) else response
        except Exception:
            response_for_history = response
            response_raw_for_history = response
        _llm_visible = self._summarize_ui_blocks(response_for_history)
        if llm_visible_limit and isinstance(_llm_visible, str) and len(_llm_visible) > llm_visible_limit:
            _llm_visible = (_llm_visible[:llm_visible_limit].rstrip()
                            + "\n…[truncated for context — full output kept in response_raw]")
        summarized_entry = {
            "timestamp": datetime.now().isoformat(),
            "user_id": self.user_id,
            "skill": skill,
            "user_input": user_input,
            "tool_calls": tool_calls,
            "response": _llm_visible,
            "response_raw": response_raw_for_history,
        }
        reasoning_ref = self._build_reasoning_ref_from_last_turn()
        if reasoning_ref:
            summarized_entry["reasoning_ref"] = reasoning_ref
            self.reasoning_ref = reasoning_ref
        if evidence_bundle and (evidence_bundle.get("documents") or evidence_bundle.get("evidence_items")):
            summarized_entry["evidence_trace_id"] = evidence_bundle.get("trace_id", "")
            # Kept in memory only so hot conversation switches can restore the
            # Evidence panel even before the persisted bundle is reloaded.
            summarized_entry["source_documents"] = evidence_bundle
        self.conversation_history.append(summarized_entry)

        # Trigger compaction on turn COUNT or total SIZE, whichever trips first. Count
        # alone lets two oversized turns 413 the model long before turn 30.
        if len(self.conversation_history) > self.SESSION_COMPACT_THRESHOLD:
            self._compact_session()
        elif self._history_chars() > self.SESSION_COMPACT_CHARS:
            logger.info("Compacting on size: history ~%d chars > %d",
                        self._history_chars(), self.SESSION_COMPACT_CHARS)
            self._compact_session()

    def _history_chars(self) -> int:
        """Rough size of what conversation_history contributes to a prompt."""
        total = 0
        for t in self.conversation_history or []:
            if not isinstance(t, dict):
                continue
            total += len(str(t.get("user_input") or "")) + len(str(t.get("response") or ""))
        return total

    # Chars of an early-return mode's output that future turns re-read. Full text is
    # always preserved in response_raw; this only bounds what goes back into prompts.
    EARLY_RETURN_HISTORY_LIMIT = 1200

    def _log_early_return_turn(self, query: str, skill_name: str, mode_response,
                               skip_memory: bool = False) -> None:
        """Record a turn for an execution mode that returns before run()'s memory tail.

        workflow / parallel / supervisor / orchestrator / rlm / graph all return early
        from _run_impl, so they never reached _log_conversation or the episodic log at the
        bottom of run(). Their turns were therefore invisible to conversation memory,
        session resume, the router's continuation check (chat.py reads
        conversation_history[-1] as `last_response`), and the on-disk episode log.

        Those same early returns already call _finalize_evidence_bundle() and
        _close_trace_for_early_return() — evidence and trace parity were handled; this is
        the memory equivalent that was missed.

        Deliberately NOT done here: implicit-feedback learning and knowledge extraction.
        Those live in run()'s async tail and spend light-LLM calls per turn; firing them
        for every workstream item would be a real cost change, so they stay ReAct-only.
        Honours ``skip_memory`` exactly as the main path does, and never raises — a
        bookkeeping failure must not fail a turn that already produced its answer.
        """
        if skip_memory:
            return
        try:
            if isinstance(mode_response, tuple):
                text = mode_response[0] if mode_response else ""
                tool_calls = (mode_response[1] if len(mode_response) > 1 else []) or []
            else:
                text, tool_calls = mode_response, []
            text = str(text or "")
            if not text.strip():
                return  # nothing worth remembering

            self._log_conversation(query, skill_name, tool_calls, text,
                                   llm_visible_limit=self.EARLY_RETURN_HISTORY_LIMIT)
            try:
                self.memory.add_to_short_term(role="assistant", content=text,
                                              skill=skill_name, tool_calls=tool_calls)
            except Exception as mem_err:
                logger.debug("early-return short-term memory skipped: %s", mem_err)
            # Episodic/JSONL audit record. summary_mode="truncate" + no brain index =
            # a cheap file write, no LLM call.
            try:
                self._log_episode_via_memory_boundary(
                    user_input=query, response=text, skill=skill_name,
                    tool_calls=tool_calls, decision_context=None,
                    summary_mode="truncate", update_brain_index=False,
                )
            except Exception as ep_err:
                logger.debug("early-return episode log skipped: %s", ep_err)
            logger.info("Recorded %s turn in conversation history (early-return mode)", skill_name)
        except Exception as exc:
            logger.warning("early-return turn not recorded for %s: %s", skill_name, exc)
    
    def _compact_session(self):
        """
        Compact conversation history using LLM summarization (OpenClaw-style).
        
        When conversation exceeds SESSION_COMPACT_THRESHOLD:
        1. Summarize older turns via light_llm
        2. Store summary in session_summary
        3. Keep only last SESSION_KEEP_RECENT turns in memory
        4. Full history remains in JSONL file for drill-down
        
        This prevents context window bloat while preserving continuity.
        """
        # Guard SESSION_KEEP_RECENT=0: `[:-0]` is `[]` and `[-0:]` is the whole list, which
        # silently disables compaction AND fires a light-LLM call every turn on empty text.
        keep_count = max(1, int(self.SESSION_KEEP_RECENT or 1))
        if len(self.conversation_history) <= keep_count:
            return  # nothing old enough to compact

        old_turns = self.conversation_history[:-keep_count]
        recent_turns = self.conversation_history[-keep_count:]
        if not old_turns:
            return

        logger.info("Compacting session: %d old turns -> summary, keeping %d recent", len(old_turns), len(recent_turns))

        new_refs = []
        for turn in old_turns:
            ref = {"skill": turn.get("skill") or "general"}
            if turn.get("evidence_trace_id"):
                ref["trace_id"] = turn["evidence_trace_id"]
            names = []
            for tc in (turn.get("tool_calls") or [])[:6]:
                if isinstance(tc, dict):
                    n = tc.get("tool_name") or tc.get("name") or tc.get("action")
                elif isinstance(tc, str):
                    n = tc.split()[0] if tc.strip() else ""
                else:
                    n = ""
                if n and n not in names:
                    names.append(str(n)[:40])
            if names:
                ref["tools"] = names
            new_refs.append(ref)

        # Build text to summarize. Prefer response_raw: `response` is already ui-stripped
        # and may be length-capped, so summarizing it was lossy on top of lossy.
        turns_text = []
        for turn in old_turns:
            skill_tag = f"[{turn.get('skill', 'general')}]" if turn.get('skill') else ""
            user_msg = str(turn.get('user_input', '') or '')[:400]
            resp_msg = str(turn.get('response_raw') or turn.get('response', '') or '')[:800]
            turns_text.append(f"User{skill_tag}: {user_msg}")
            turns_text.append(f"Assistant: {resp_msg}")

        conversation_text = "\n".join(turns_text)

        # Re-condense rather than append. The previous summary goes IN to the prompt and
        # comes back folded into a single summary, so it can't grow without bound.
        if self.session_summary:
            summary_prompt = f"""You are maintaining a running summary of a long conversation.

Rewrite the PREVIOUS SUMMARY and the NEW TURNS into ONE consolidated summary that covers
both. Do not simply append — merge, deduplicate, and drop anything now superseded.

Focus on: key topics; decisions and actions taken; user preferences; unresolved items.
Keep it under 500 words. Use bullet points.

PREVIOUS SUMMARY:
{self.session_summary}

NEW TURNS:
{conversation_text}

CONSOLIDATED SUMMARY:"""
        else:
            summary_prompt = f"""Summarize this conversation history concisely. Focus on:
1. Key topics discussed
2. Important decisions or actions taken
3. Any user preferences or context revealed
4. Unresolved items or pending tasks

Keep the summary under 500 words. Use bullet points.

CONVERSATION:
{conversation_text}

SUMMARY:"""

        try:
            # Use light_llm for cheaper summarization
            from langchain_core.messages import HumanMessage
            _compact_model = getattr(self.light_llm, 'azure_deployment', None) or getattr(self.light_llm, 'model_name', None) or getattr(self.light_llm, 'model', '') or ''
            logger.info("📝 MEMORY COMPACTION  ▸ model=%s", _compact_model)
            result = self.light_llm.invoke([HumanMessage(content=summary_prompt)])
            new_summary = result.content.strip()
            if not new_summary:
                raise ValueError("summarizer returned empty text")

            self.session_summary = new_summary        # REPLACES, never appends
            self.session_summary_refs = (list(self.session_summary_refs or []) + new_refs)[-self.SESSION_SUMMARY_MAX_REFS:]
            try:
                self.session_summary_pointer = str(self._get_history_path())
            except Exception:
                pass

            self.conversation_history = recent_turns
            self.compaction_count += 1
            logger.info("Session compacted (#%d): %d turns -> %d char summary (%d refs kept)",
                        self.compaction_count, len(old_turns), len(new_summary),
                        len(self.session_summary_refs))

        except Exception as e:
            logger.warning("Session compaction failed — history preserved, will retry: %s", e)
            hard_cap = max(keep_count + 1, self.SESSION_COMPACT_THRESHOLD * 2)
            if len(self.conversation_history) > hard_cap:
                # Backstop for a persistently unavailable summarizer: trim, but leave a
                # VISIBLE marker so the loss is in the transcript rather than silent.
                gap = {
                    "timestamp": datetime.now().isoformat(),
                    "user_id": self.user_id,
                    "skill": "system",
                    "user_input": "",
                    "tool_calls": [],
                    "response": (f"[GAP: {len(old_turns)} earlier turns were dropped — the "
                                 f"summarizer was unavailable. Full history remains on disk.]"),
                    "response_raw": "",
                }
                self.conversation_history = [gap] + recent_turns
                logger.error("Compaction backstop: dropped %d turns past hard cap %d (gap marker inserted)",
                             len(old_turns), hard_cap)
    
    def append_learning(self, learning_type: str, content: dict, skill_name: str = None) -> Path:
        """
        Safely append a learning entry to memory files.

        DELEGATED to implicit_learning.append_learning().
        See that module for implementation details.

        Batch 5 / Phase 3b: fires ``OnMemoryWrite`` with the learning type +
        key so audit observers can track background memory mutations. Errors
        in the write itself become ``OnBackgroundTaskError``.
        """
        try:
            if self._memory_capability_enabled() and getattr(self, "memory_capability", None) is not None:
                path = self.memory_capability.append_learning(
                    learning_type=learning_type,
                    content=content,
                    skill_name=skill_name,
                )
            else:
                path = _append_learning_impl(
                    learning_type=learning_type,
                    content=content,
                    skill_name=skill_name,
                    session_id=self.session_id,
                    user_id=self.user_id,
                    agent_root=self.kernel.agent_root,
                )
        except Exception as exc:
            try:
                self.hook_runner.run_on_background_task_error(
                    task_name="append_learning",
                    error_msg=f"{type(exc).__name__}: {exc}",
                    session_ctx={**self._build_session_ctx(), "skill_name": skill_name or ""},
                )
            except Exception:  # pragma: no cover - observe-only
                pass
            raise

        # Fire OnMemoryWrite with a bounded preview of the content dict.
        try:
            import json as _json
            _value_preview = _json.dumps(content, default=str)[:500] if content else ""
        except Exception:
            _value_preview = str(content)[:500]
        try:
            self.hook_runner.run_on_memory_write(
                store=str(learning_type or ""),
                key=str(path) if path else "",
                value_preview=_value_preview,
                session_ctx={**self._build_session_ctx(), "skill_name": skill_name or ""},
            )
        except Exception as _hexc:  # pragma: no cover - observe-only
            logger.debug("OnMemoryWrite hook error (non-fatal): %s", _hexc)
        return path


    # Class-level aliases to module constants (for backward compatibility)
    _IMPLICIT_CONFIDENCE_THRESHOLDS = IMPLICIT_CONFIDENCE_THRESHOLDS
    _IMPLICIT_TYPE_MAP = IMPLICIT_TYPE_MAP

    def _analyze_implicit_feedback(
        self,
        query: str,
        response: str,
        prev_user_msg: str,
        skill_name: str,
        tool_calls_log: list,
    ) -> list:
        """
        Analyze a conversation exchange for implicit learning signals.

        DELEGATED to implicit_learning.analyze_implicit_feedback().
        See that module for implementation details.

        Batch 5 / Phase 3b: every returned signal that would land as a
        pending-review entry triggers ``OnKnowledgeEntryPending`` so audit
        observers can track what the implicit learner is queuing without
        having to poll the knowledge index.
        """
        try:
            signals = _analyze_implicit_feedback_impl(
                query=query,
                response=response,
                prev_user_msg=prev_user_msg,
                skill_name=skill_name,
                tool_calls_log=tool_calls_log,
                light_llm=getattr(self, 'light_llm', None),
                confidence_thresholds=self._IMPLICIT_CONFIDENCE_THRESHOLDS,
            )
        except Exception as exc:
            try:
                self.hook_runner.run_on_background_task_error(
                    task_name="analyze_implicit_feedback",
                    error_msg=f"{type(exc).__name__}: {exc}",
                    session_ctx={**self._build_session_ctx(), "skill_name": skill_name},
                )
            except Exception:  # pragma: no cover - observe-only
                pass
            raise

        # Fire OnKnowledgeEntryPending per returned signal (observe-only).
        for sig in signals or []:
            try:
                self.hook_runner.run_on_knowledge_entry_pending(
                    skill_name=skill_name,
                    entry_kind=str((sig or {}).get("type") or ""),
                    entry_preview=str(sig)[:500],
                    session_ctx=self._build_session_ctx(),
                )
            except Exception as _hexc:  # pragma: no cover - observe-only
                logger.debug("OnKnowledgeEntryPending hook error (non-fatal): %s", _hexc)
        return signals

    def _triage_implicit_signal(self, signal: dict) -> str:
        """
        Determine knowledge status based on signal type and confidence.
        
        DELEGATED to implicit_learning.triage_implicit_signal().
        See that module for implementation details.
        """
        return _triage_implicit_signal_impl(
            signal=signal,
            confidence_thresholds=self._IMPLICIT_CONFIDENCE_THRESHOLDS,
        )

    def _create_llm(self):
        """Create primary LLM via the model provider adapter."""
        from .model_provider import default_model_provider
        return default_model_provider.get("primary")
    
    def _create_light_llm(self):
        """Create lightweight LLM for cheap classification tasks via ModelRegistry.
        Falls back to main deployment if AZURE_OPENAI_DEPLOYMENT_LIGHT is not set.
        """
        from .model_provider import default_model_provider
        return default_model_provider.get("light")
    
    def _create_tool(self):
        """Create the shell tool through the active ToolProvider."""
        self._ensure_runtime_providers()
        return self.tool_provider.create_shell_tool(self.kernel, auto_run=self.auto_run)
    
    def _create_sql_tool(self, connections=None):
        """Create the SQL query tool through the active ToolProvider.

        `connections` are the skill's data connections (SQLite / SQL Server /
        PostgreSQL) — the tool routes by each connection's engine."""
        self._ensure_runtime_providers()
        try:
            return self.tool_provider.create_sql_tool(
                self.kernel,
                sql_write_allowed=getattr(self, '_sql_write_allowed', False),
                indexer=getattr(self.memory, 'knowledge_indexer', None),
                connections=connections,
            )
        except TypeError:
            # Back-compat: a custom ToolProvider that predates the `connections`
            # kwarg. Retry without it (indexer stays) so older providers still work.
            return self.tool_provider.create_sql_tool(
                self.kernel,
                sql_write_allowed=getattr(self, '_sql_write_allowed', False),
                indexer=getattr(self.memory, 'knowledge_indexer', None),
            )

    def _create_fetch_canonical_tool(self):
        """Create the fetch_canonical tool (binding-resolver backed) via the ToolProvider."""
        self._ensure_runtime_providers()
        return self.tool_provider.create_fetch_canonical_tool(self.kernel)


    def _create_write_file_tool(self):
        """Create the write_file tool through the active ToolProvider."""
        self._ensure_runtime_providers()
        return self.tool_provider.create_write_file_tool(self.kernel)
    
    def _create_memory_tool(self):
        """Create the query_memory tool through the active ToolProvider."""
        self._ensure_runtime_providers()
        return self.tool_provider.create_memory_tool(
            memory=self.memory,
            get_retrieval_mode=lambda: getattr(self, 'knowledge_retrieval_mode', 'hybrid'),
            get_cached_embedding=lambda: getattr(self, '_cached_query_embedding', None),
            get_entity_hint=lambda: getattr(self, '_last_entity_hint', None),
        )

    def _rlm_mode_active(self) -> bool:
        """True when RLM context mode is on for this agent and not globally disabled.
        Global kill switch: env RLM_ENABLED=false."""
        if getattr(self, 'context_loading_mode', 'table') != 'rlm':
            return False
        return os.getenv('RLM_ENABLED', 'true').strip().lower() not in ('0', 'false', 'no', 'off')

    @staticmethod
    def _rlm_execution_enabled() -> bool:
        """Global kill switch for RLM CODE EXECUTION (`execution_mode: rlm`).

        Deliberately independent of `_rlm_mode_active()`, which additionally requires
        RLM *context* loading and therefore cannot gate the execution dispatch.

        Scope note: this honours RLM_ENABLED only. It is intentionally NOT tied to
        AGENTOS_UNTRUSTED_EXECUTION_GUARD, because that flag is on by default here and
        coupling them would disable the three shipped `execution_mode: rlm` skills. If
        you want the guard to also kill in-process exec(), add the guard check here —
        that is a deliberate posture decision, not a default.
        """
        return os.getenv('RLM_ENABLED', 'true').strip().lower() not in ('0', 'false', 'no', 'off')

    def _rlm_wrapped_light(self):
        """Policy-wrap the light LLM once so RLM leaf calls also flow through the model-call pipeline
        (audit/RL/hooks). light_llm is otherwise raw — only primary/fallback are wrapped."""
        if getattr(self, "_rlm_light_wrapped", None) is None:
            base = getattr(self, "light_llm", None) or self.llm
            try:
                self._rlm_light_wrapped = self._policy_wrap_llm(base, role="light")
            except Exception:
                self._rlm_light_wrapped = base
        return self._rlm_light_wrapped

    def _rlm_invoke(self, llm, role: str, prompt: str) -> str:
        """Invoke an LLM for the RLM engine inside model_call_context (audit/RL/hooks apply)."""
        from langchain_core.messages import HumanMessage
        _ctx = {**self._build_session_ctx(), "model_role": role, "purpose": "rlm"}
        try:
            with model_call_context(_ctx):
                resp = llm.invoke([HumanMessage(content=str(prompt))])
        except Exception:
            resp = llm.invoke([HumanMessage(content=str(prompt))])
        return (getattr(resp, "content", "") or "").strip()

    def _rlm_root_call(self, prompt: str) -> str:
        """RLM ROOT reasoning turn → capable model (primary, already policy-wrapped)."""
        return self._rlm_invoke(self.llm, "primary", prompt)

    def _rlm_leaf_call(self, prompt: str) -> str:
        """RLM LEAF sub-call (llm_query) → light model (policy-wrapped for audit)."""
        return self._rlm_invoke(self._rlm_wrapped_light(), "light", prompt)

    def _rlm_model_call(self, prompt: str, max_tokens: int = 1500) -> str:
        """Back-compat alias — the RLM leaf/light call."""
        return self._rlm_leaf_call(prompt)

    def _rlm_child_agent_factory(self, child_skill_name: str):
        """Create a child SkillAgent for RLM-initiated skill delegation. Mirrors the closure in
        _create_agent: same kernel/tenant/user + inherited entitlements (NO privilege escalation),
        depth+1 so MAX_INVOKE_DEPTH still bounds recursion."""
        child = SkillAgent(kernel=self.kernel, skills_path=self.skills_path, user_id=self.user_id)
        child.set_entitlement_context(self.entitlement_principal, self.entitlement_checker)
        child._invoke_depth = getattr(self, "_invoke_depth", 0) + 1
        child.current_skill = child_skill_name
        child.auto_run = self.auto_run
        return child

    def _rlm_log_emit(self, ev: dict) -> None:
        """Log one RLM engine event so the inner programs/sub-calls are visible (playground-style)."""
        try:
            t = ev.get("type")
            d = int(ev.get("depth", 0))
            pad = "  " * d
            if t == "code":
                logger.info("RLM%s [d%d] code iter%s (%d chars):\n%s",
                            pad, d, ev.get("iter", "?"), len(ev.get("code", "")), (ev.get("code", "") or "")[:1200])
            elif t == "stdout":
                logger.info("RLM%s [d%d] stdout (%d chars): %s",
                            pad, d, ev.get("chars", 0), (ev.get("preview", "") or "")[:400])
            elif t == "llm_query":
                logger.info("RLM%s [d%d] ↳ llm_query #%s (in=%d chars)",
                            pad, d, ev.get("n", "?"), ev.get("in_chars", 0))
            elif t == "rlm_start":
                logger.info("RLM%s [d%d] ⇘ rlm_query → sub-RLM (%d chars): %s",
                            pad, d, ev.get("sub_chars", 0), (ev.get("query", "") or "")[:120])
            elif t == "rlm_end":
                logger.info("RLM%s [d%d] rlm_query done → %s",
                            pad, d, (ev.get("answer", "") or "")[:200])
            elif t == "tool_call":
                logger.info("RLM%s [d%d] ⚙ tool_call %s #%s args=%s",
                            pad, d, ev.get("name", "?"), ev.get("n", "?"), (ev.get("args", "") or "")[:200])
            elif t == "tool_result":
                logger.info("RLM%s [d%d] ⚙ %s → %s",
                            pad, d, ev.get("name", "?"), (ev.get("result", "") or "")[:200])
        except Exception:
            pass

    def _create_context_query_tool(self):
        """RLM mode: a read-only tool that answers questions over the offloaded context via a
        recursive RLM (llm_query/rlm_query), keeping the full context out of the ReAct window."""
        from langchain_core.tools import tool
        from .rlm.context_store import get_context_store
        from .rlm.engine import run_rlm
        agent_ref = self
        _cfg = getattr(self, '_rlm_cfg', {}) or {}
        _max_iters = int(_cfg.get('max_iters', 6))
        _max_depth = int(_cfg.get('max_depth', 2))
        _max_leaf = int(_cfg.get('max_leaf_calls', 30))
        _max_concurrent = int(_cfg.get('max_concurrent', 4))

        @tool
        def context_query(question: str) -> str:
            """Answer a question using the full offloaded context for this session.

            The context is too large to inline; this tool reads and aggregates only the parts
            relevant to your question. Ask ONE well-scoped question (call it again for follow-ups).

            Args:
                question: A natural-language question to answer from the context.
            Returns:
                The answer synthesised from the relevant parts of the context.
            """
            _k = getattr(agent_ref, "kernel", None)
            _scope = f"{getattr(_k, 'tenant_id', '') or ''}:{getattr(_k, 'agent_id', '') or ''}:{agent_ref.user_id or ''}"
            text = get_context_store().get(agent_ref.session_id, scope=_scope)
            if not text:
                return "No offloaded context is available for this session."
            try:
                answer, _ = run_rlm(
                    agent_ref._rlm_root_call, text, question,
                    leaf_model_call=agent_ref._rlm_leaf_call,
                    max_iters=_max_iters, max_depth=_max_depth, max_leaf_calls=_max_leaf,
                    max_concurrent=_max_concurrent,
                    run_id=getattr(agent_ref, "_active_trace_id", "") or "",
                    emit=agent_ref._rlm_log_emit,
                )
                return answer or "(no answer produced)"
            except Exception as _cq_e:
                logger.error("context_query failed: %s", _cq_e)
                return f"context_query error: {_cq_e}"
        return context_query

    def _run_rlm(self, skill, query: str, return_tool_calls: bool, emit_status):
        """RLM execution_mode: the whole turn is a code-action RLM loop over GOVERNED tools +
        sub-LLMs. Read/analysis tools execute inline (each via govern_tool_call); side-effecting
        actions are RECORDED via propose_action and surfaced for approval — NOT executed in v1.
        Any exception here is caught by the dispatch caller, which falls back to ReAct."""
        from .rlm.engine import run_rlm
        from .rlm.context_store import get_context_store
        from .rlm.tools import build_rlm_tools
        _cfg = getattr(self, "_rlm_cfg", {}) or {}
        if callable(emit_status):
            try:
                emit_status("Running RLM execution mode…")
            except Exception:
                pass

        tools, tools_prompt, proposed = build_rlm_tools(self)
        logger.info("RLM execution: tools available = %s", sorted(tools.keys()))

        def _rlm_emit(ev: dict) -> None:
            self._rlm_log_emit(ev)
            if not callable(emit_status):
                return
            try:
                t = ev.get("type")
                d = int(ev.get("depth", 0))
                pad = "› " * d
                if t == "tool_call":
                    name = ev.get("name", "?")
                    args = (ev.get("args", "") or "")
                    _m = re.search(r"[\w./-]+\.(?:md|txt)", args)
                    _doc = _m.group(0).split("/")[-1] if _m else "a document"
                    _inv = re.search(r"INV-\d+", args)
                    friendly = {
                        "run_sql_query": "🗄 Querying the AP ledger…",
                        "read_document": f"📄 Reading {_doc}…",
                        "invoke_skill": "🔗 Delegating to a governed sub-skill…",
                        "http_get": f"🌐 Checking live status{(' ' + _inv.group(0)) if _inv else ''}…",
                        "propose_action": "📝 Proposing a payment hold…",
                    }.get(name, f"⚙ {name}…")
                    emit_status(f"{pad}{friendly}")
                    emit_status({"__rlm_event__": True, "card_type": "tool_call",
                                 "label": name, "text": friendly, "detail": args[:400], "depth": d})
                elif t == "tool_result":
                    emit_status({"__rlm_event__": True, "card_type": "tool_result",
                                 "label": ev.get("name", "?"),
                                 "text": (ev.get("result", "") or "")[:300], "depth": d})
                elif t == "code":
                    emit_status({"__rlm_event__": True, "card_type": "rlm_code",
                                 "label": f"code · step {ev.get('iter', '?')}",
                                 "text": (ev.get("code", "") or ""), "depth": d})
                elif t == "llm_query":
                    emit_status(f"{pad}💭 Sub-analysis…")
                elif t == "rlm_start":
                    emit_status(f"{pad}⇘ Recursive sub-RLM…")
            except Exception:
                pass
        ctx_text = ("(No document is preloaded. You MUST call the available tools to obtain real data — "
                    + ", ".join(sorted(tools.keys())) + " — and must NOT rely on prior/general knowledge "
                    "or any other system's context.)")

        # The SKILL.md body carries the task instructions; combine with the user's request.
        _skill_body = (getattr(skill, "body", "") or "").strip()
        effective_query = f"{_skill_body}\n\n## User request\n{query}" if _skill_body else str(query)

        answer, _metrics = run_rlm(
            self._rlm_root_call, ctx_text, effective_query,
            leaf_model_call=self._rlm_leaf_call,
            tools=tools, tools_prompt=tools_prompt,
            max_iters=int(_cfg.get("max_iters", 6)),
            max_depth=int(_cfg.get("max_depth", 2)),
            max_leaf_calls=int(_cfg.get("max_leaf_calls", 30)),
            max_tool_calls=int(_cfg.get("max_tool_calls", 20)),
            max_concurrent=int(_cfg.get("max_concurrent", 4)),
            deadline_s=float(_cfg.get("max_wall_s", 300)),
            run_id=getattr(self, "_active_trace_id", "") or "",
            emit=_rlm_emit,
        )

        response = str(answer or "")
        # Propose-then-apply (v1): surface side-effecting proposals for human review — do NOT execute.
        if proposed:
            lines = [f"\n\n---\n**Proposed actions requiring approval ({len(proposed)}) — not executed:**"]
            for i, pa in enumerate(proposed, 1):
                lines.append(f"{i}. {pa.get('kind', '?')} — {pa.get('rationale', '')}".rstrip())
            response += "\n".join(lines)
            logger.info("RLM: %d proposed side-effecting action(s) surfaced for approval (not executed)",
                        len(proposed))

            _apply_on = bool(_cfg.get("apply_phase", False)) or \
                os.getenv("RLM_APPLY_PHASE", "").strip().lower() in ("1", "true", "yes", "on")
            if _apply_on:
                staged = []
                for pa in proposed:
                    try:
                        _args = str(pa.get("args", "") or "")
                        _dec = govern_tool_call(
                            self,
                            {"id": f"rlm-apply-{uuid.uuid4().hex[:8]}",
                             "name": str(pa.get("kind", "hold_payment")), "args": {"detail": _args}},
                            source="rlm_apply",
                        )
                        if not getattr(_dec, "allowed", True) and \
                                getattr(_dec, "status", "") not in ("pending", "already_pending"):
                            logger.info("RLM apply-phase: proposal blocked by governance — %s",
                                        getattr(_dec, "reason", ""))
                            continue
                        _inv = re.search(r"INV-\d+", _args)
                        _amt = re.search(r"\$([\d.]+)", _args)
                        _ven = re.search(r"vendor=(.+?)\s*$", _args)
                        staged.append({
                            "kind": str(pa.get("kind", "hold_payment")),
                            "args": _args,
                            "rationale": str(pa.get("rationale", "") or ""),
                            "invoice_id": _inv.group(0) if _inv else "",
                            "amount": float(_amt.group(1)) if _amt else 0.0,
                            "vendor": _ven.group(1).strip() if _ven else "",
                        })
                    except Exception as _ap_e:
                        logger.warning("RLM apply-phase staging failed for a proposal: %s", _ap_e)
                # Studio-layer seam consumes this after the turn to create approval cards.
                self._rlm_proposed = staged
                if staged:
                    response += (f"\n\n_{len(staged)} hold(s) sent to the approvals queue "
                                 f"for human decision._")

        return (response, []) if return_tool_calls else response

    def _rlm_shadow_maybe(self, query, result) -> None:
        """Phase-0 shadow: if env RLM_SHADOW is on and a context file is configured, run the
        RLM analytical path over the same context+query and log a comparison vs the served
        answer. Best-effort — any failure is swallowed and never affects the served result."""
        try:
            if os.getenv("RLM_SHADOW", "").strip().lower() not in ("1", "true", "yes", "on"):
                return
            _ctx_file = getattr(self, "_context_file_path", None)
            if not _ctx_file:
                return
            normal_answer = str((result[0] if isinstance(result, tuple) else result) or "")
            try:
                context_text = self._resolve_context_file(_ctx_file).read_text(encoding="utf-8", errors="ignore")
            except Exception:
                return
            import time as _t
            from .rlm.engine import run_rlm
            from .rlm.shadow import append_jsonl, build_record
            _cfg = getattr(self, "_rlm_cfg", {}) or {}
            _t0 = _t.time()
            rlm_answer, rlm_metrics = run_rlm(
                self._rlm_root_call, context_text, str(query),
                leaf_model_call=self._rlm_leaf_call,
                max_iters=int(_cfg.get("max_iters", 6)),
                max_depth=int(_cfg.get("max_depth", 2)),
                max_leaf_calls=int(_cfg.get("max_leaf_calls", 30)),
                max_concurrent=int(_cfg.get("max_concurrent", 4)),
                emit=self._rlm_log_emit,
            )
            rec = build_record(
                query=str(query), normal_answer=normal_answer, rlm_answer=rlm_answer or "",
                rlm_metrics=rlm_metrics or {}, context_chars=len(context_text),
                ts=_t.time(), session_id=getattr(self, "session_id", ""),
                rlm_elapsed_ms=int((_t.time() - _t0) * 1000),
            )
            log_path = os.getenv("RLM_SHADOW_LOG") or os.path.join(
                str(getattr(self.kernel, "agent_root", ".")), "rlm_shadow.jsonl")
            append_jsonl(log_path, rec)
            logger.info("RLM shadow: logged comparison (overlap=%.2f) -> %s",
                        rec.get("overlap", 0.0), log_path)
        except Exception as _e:
            logger.debug("RLM shadow (non-fatal): %s", _e)

    # Agentic behavior prompt block - encourages retry and verification
    AGENTIC_PROMPT = """
## Execution Guidelines
- After any write operation, VERIFY it worked by reading back (e.g., `cat` the file)
- If a command fails, analyze the error and try a different approach
- If file not found, check the parent directory with `ls` first
- Don't give up on first error - retry with corrected syntax or alternative method
- Confirm the goal is achieved before responding to the user
- Maximum 3 retry attempts before asking user for clarification

## File Discovery Protocol — How to Find the Right File

**NEVER assume a filename. Always search by content when the exact file is not known.**

### ⚠️ CRITICAL: Always quote paths that contain spaces
The shell parser splits on spaces. A path like `/local/Invoice To Pay_md/` MUST be quoted:
```
CORRECT:   grep -r -i -l 'keyword' '/local/Invoice To Pay_md/'
WRONG:     grep -r -i -l 'keyword' /local/Invoice To Pay_md/   ← breaks at the space
CORRECT:   find '/local/Invoice To Pay_md' -name '*.mmd'
WRONG:     find /local/Invoice To Pay_md -name '*.mmd'          ← "To" becomes a separate arg
```
**Rule: if a path has a space in it, wrap the entire path in single quotes.**

### PDF / Office document text extraction
Do not `cat` binary documents such as `.pdf`, `.docx`, `.pptx`, or `.xlsx`.
Do not use OS-specific extractors (Quartz/PDFKit, win32com, PyPDF2, pdftotext).
Always use the shared extractor script (markitdown + PDF fallbacks inside):
```
shell(command="python3 /shared/scripts/extract_document.py '/me/uploads/FILENAME'")
```
Quote paths that contain spaces. For longer documents, write extracted text to
`/workspace/<name>.txt` and read/search that text file.

Follow this escalation sequence:

### Step 1 — Context file first
If a skill context file is loaded (e.g., `/shared/contexts/p2p_package_context.md`), read it first.
It tells you which folders are relevant — but it does NOT give you exact filenames.
**Always grep within those folders to find the right file.** Do not assume a filename from context.

### Step 2 — Expand query, then grep ALL folders in ONE response turn

**MANDATORY — always do this for every file search, no exceptions:**
1. Generate 3–5 search variants for your keyword — synonyms, abbreviations, alternate phrasings
   a domain expert would use. Single-keyword search is not allowed.
2. Run ALL variants across ALL relevant folders using the parallel script below — fire it in
   a single shell call. Do NOT run one grep, get a result, and stop.
3. Pool all returned filenames. Files appearing in 2+ variant results = read those first.

The skill context file (if loaded) tells you which folders to use — fill them into the script.

Always run this pattern — replace variants and folders before executing:

shell(command="python3 -c \"
import subprocess
from concurrent.futures import ThreadPoolExecutor
from collections import Counter

variants = ['<term1>', '<term2>', '<term3>']  # expand from query — 3-5 variants minimum
folders  = ['<folder1>', '<folder2>']          # from skill context file

def run(args):
    v, f = args
    r = subprocess.run(['grep','-r','-i','-l', v, f], capture_output=True, text=True)
    return r.stdout.strip().split('\n') if r.stdout.strip() else []

with ThreadPoolExecutor(max_workers=12) as pool:
    results = list(pool.map(run, [(v,f) for v in variants for f in folders]))

hits = Counter()
for files in results:
    for file in files:
        if file: hits[file] += 1

for file, count in hits.most_common(10):
    print(f'{count} hits: {file}')
\"")

Read the top-ranked files (highest hit count first). Do not skip this script.

### Step 3 — RRF confidence scoring
Files returned by 2+ search variants carry higher confidence than files from a single variant.
Read highest-hit-count files first. A file found by both your primary keyword and a synonym
is more likely the right file than one found by only one variant.

### Step 4 — Search inside a file if it is large
When a file is too large to read fully, search inside it:
```
shell(command="grep -n -i 'keyword' '/local/Domain_md/subfolder/file.md'")
```
`-n` = show line numbers so you know where to focus

### Step 5 — Semgrep for conceptual search
If exact keyword grep fails across all folders, use `semgrep` for conceptual/semantic search across all of `/local/`:
```
shell(command="semgrep 'how invoices are approved in Oracle AP' '/local/'")
```
Always use `/local/` root — not a subfolder — so client files and KB files are both ranked.

### Step 6 — Broaden to parent folder
If subfolder search fails, move up one level:
```
shell(command="grep -r -i -l 'keyword' '/local/Invoice To Pay_md/'")
```

### Decision table — which command for which situation

| Situation | Command |
|---|---|
| Know exact file path | `cat '/local/path/to file.md'` (quote if spaces) |
| Know folder, not filename — search by content | `grep -r -i -l 'keyword' '/local/folder/'` |
| Know part of the filename — search by name pattern | `find '/local/folder' -name '*pattern*'` |
| Know the file number prefix (e.g. 7.1.2) | `find '/local/folder' -name '7.1.2*'` |
| Know the file type / extension | `find /local -name '*.mmd' -type f` |
| File found but it's large — search inside it | `grep -n -i 'keyword' '/local/folder/file.md'` |
| Content grep returns nothing | Try 2–3 alternative keywords with grep |
| Filename grep returns nothing | Broaden: `find /local -name '*pattern*'` |
| Both grep and find fail | `semgrep 'concept description' '/local/folder/'` |
| Genuinely unknown folder structure | Check injected `/local/` tree above first — then grep |

**NEVER do: `ls` → read every file one by one → hope the right one appears.**
**ALWAYS do: check the local tree map above → grep by content OR find by name → cat only the matched file.**

## HTTP/API Calls
> If a "Data Connections" section appears later in this prompt, it lists the
> declared APIs (base URL + how to authenticate) and databases for this skill —
> use those details (run_sql_query for DBs; shell+curl for APIs) to answer
> natural-language requests about them.

**You CAN make outbound HTTP requests** using the shell tool with curl:

```
shell(command="curl -s http://localhost:8080/api/endpoint")
shell(command="curl -s -H 'Authorization: Bearer $CRED_API_TOKEN' 'http://api.example.com/data'")
```

**IMPORTANT:**
- DO NOT say "I can't make outbound HTTP calls" — this is FALSE
- Use `-s` flag for silent mode (no progress bars)
- DO NOT use `-o` to save to files — just print to stdout
- When context sources show a `credential_ref`, load it with `get_credential <name> <field>`
- Use the returned `$CRED_*` variable in curl; the kernel substitutes the real secret at execution time

**Pattern for API calls:**
1. Find the endpoint in context sources metadata
2. Load the credential with `get_credential` and keep the returned `$CRED_*` variable
3. Run: `shell(command="curl -s -H 'Authorization: Bearer $CRED_NAME_FIELD' 'http://endpoint/path'")`

## File Writing: Choosing the Right Tool
- **write_file()**: Use for multi-line content, markdown with tables, code with special chars (|, $, *, backticks)
- **shell("echo ... > file")**: Use for simple one-line writes without special characters
- **Rule of thumb**: If content has tables, code blocks, or is >3 lines, use write_file()

## Using Past Context
- Past conversations and learnings are GUIDANCE, not golden rules
- If past context conflicts with current tool documentation, trust the TOOL DOCS
- Prior refusals may have been errors - re-evaluate based on current capabilities
- Learn from past successes, but don't blindly repeat past failures

## Self-Correction Patterns
- Error "No such file": Check if directory exists, create with `mkdir -p` if needed
- Error "Permission denied": Check if path is within allowed scope (/me/, /workspace/, /shared/, /memory/, /local/)
- SQL error: Verify table/column names with schema query first
- Empty result: Broaden search criteria or check different paths

## Cross-Skill Delegation (invoke_skill / invoke_plan)
You have access to delegation tools for tasks that span MULTIPLE domains:

### invoke_skill(skill_name, task)
- Delegates a single sub-task to another skill and returns its answer.
- Use when part of the user's request needs data from a DIFFERENT domain.
- Example: You are ar_ops but the user asks about vendor balances → `invoke_skill("ap_ops", "list vendor debit balances")`

### invoke_plan(plan_json)
- Executes a multi-step plan across skills (parallel or sequential).
- Use when the user wants a combined report spanning 3+ domains.
- Plan format: `{"mode": "parallel", "steps": [{"name": "step1", "skill": "ar_ops", "task": "..."}, ...]}`

### When to delegate
- **ALWAYS delegate** when a [ROUTING CONTEXT] hint names other skills — those skills own data you cannot access.
- **ALWAYS delegate** when the user asks about entities/processes outside your skill's domain.
- **NEVER guess** data from another domain — delegate instead.
- **Combine results** from delegated calls with your own data into a unified answer.

## Understanding User Intent

### Implicit Confirmations
When user says "yes", "ok", "do it", "go ahead", "proceed", "sure", "yep" after you've proposed an action:
- This means EXECUTE the proposed action immediately
- Don't re-explain or ask for more confirmation
- Don't confuse with business approvals (like "approve invoice") - those are domain actions

### Referring to Previous Response
When the user says "this", "it", "that data", "the above", "in readable format", or similar in a follow-up:
- They are referring to the content of your most recent response
- Reformat, re-explain, or act on it accordingly — do NOT ask what they're referring to
- Your conversation history shows summaries like [Displayed data_table: ...] — use those to recall what you showed
- If they ask to reformat, re-query the data and present it differently

### Partial/Vague Requests  
When user gives incomplete instructions like "save this", "do that", "run it":
- Infer from recent conversation what "this/that/it" refers to
- Make reasonable assumptions based on context
- State your assumption briefly and proceed
- Example: "save this" → save to /me/notes/ with meaningful name

### Follow-Up Patterns
Recognize these continuity patterns:
- "now the other one" → apply same action to next logical item
- "same for X" → replicate the last operation on X
- "again" / "one more" → repeat the last action
- "undo that" / "revert" → reverse the last action if possible
- "what about Y?" → apply same analysis/query to Y

### Context Switching
When user abruptly changes topic:
- Don't force continuation of previous task
- Acknowledge the switch and address new request
- Previous pending actions expire after topic change

### Tone Cues
- "quickly" / "just" / "real quick" → give concise response, skip elaboration
- "explain" / "why" / "how" → give detailed explanation
- "??" / multiple questions → user is confused, be extra clear

## Multi-Step Task Execution

For complex tasks requiring multiple operations:
1. **Plan**: What steps are needed? What data do I need?
2. **Execute**: Run each step, verify success before continuing
3. **Summarize**: Brief confirmation of what was accomplished

If a step fails: diagnose error → try alternative → report progress if stuck

## Cross-Skill Delegation

You have two tools for delegating work to other skills:

**invoke_skill(task, context)** — Sequential, one skill at a time.
- Use when you need a single capability outside your current skill.
- The framework routes your task to the best-matching skill automatically.
- After each result, you can re-plan and call again if needed.
- Example: invoke_skill(task="Get AR aging summary for Q4", context="For executive report")

**invoke_plan(plan_json)** — Parallel or sequential DAG of multiple skills.
- Use when you need results from multiple skills and some can run in parallel.
- Build a JSON plan: {"mode": "parallel", "steps": [{"name": "...", "skill": "...", "task": "...", "depends_on": [...]}]}
- Steps without depends_on run concurrently. Use {{step_name.output}} to reference prior results.

**To discover available skills:** Read the skills index file using the shell tool:
  shell(command="cat /workspace/skills/_index.yaml")

**When NOT to delegate:** If your current skill can handle the full request, do not delegate.
"""

    # Fresh mode instruction (injected when light_mode=True)
    # Prevents LLM from answering from conversation history without making live calls.
    FRESH_MODE_INSTRUCTION = """
## ⚡ FRESH MODE — LIVE DATA REQUIRED
You are in Fresh Mode. This means:
- **NEVER answer from the conversation history above** — the prior Q&A is provided for follow-up context only, NOT as a source of current facts
- **ALWAYS make a live tool call first** — call the API, shell, or database NOW before composing any answer
- If you already ran this query in a prior turn, run it AGAIN — data changes minute to minute
- You may use prior tool *outputs* to guide what to query next, but you MUST re-fetch any data you plan to present
- One exception: if the user's question is purely conversational (e.g. "what did you just say?", "summarize the above"), answer from context — for everything else, call the tool
"""

    # Auto-run mode instruction (appended when auto_run=True)
    AUTO_RUN_INSTRUCTION = """
## 🚀 AUTO-RUN MODE ACTIVE
The user has enabled auto-run mode. You have FULL PERMISSION to:
- Write files to /me/ or /local/ without asking
- Execute the complete workflow immediately
- DO NOT ask "shall I proceed?" or "do you want me to..." - just DO IT
- Only ask for clarification if you genuinely need more information to complete the task

⚠️ EXCEPTION — request_human_approval tool: If the task or skill instructions explicitly require calling the `request_human_approval` tool, you MUST call it using the tool (not just mention it in text). That tool is a mandatory workflow gate, not a user confirmation prompt. Auto-run mode does NOT bypass it.
"""

    CONFIRMATION_PROTOCOL = ""  # Disabled - kernel handles confirmation

    # UI Generation prompt (appended when render_ui=True, i.e., browser requests)
    UI_GENERATION_PROMPT = """
## Interactive Response Formatting (UI Mode)

When presenting structured data, enhance responses with these interactive components:

### Data Tables (for lists, records, invoices, orders, etc.)
```ui:data_table
{
  "title": "Optional title",
  "columns": ["Col1", "Col2", "Col3"],
  "rows": [["val1", "val2", "val3"]],
  "actions": ["View", "Approve", "Reject"]
}
```

### Stat Cards (for KPIs, summaries, metrics - max 4)
```ui:stat_cards
{
  "cards": [
    {"icon": "📊", "label": "Total Revenue", "value": "$50K", "trend": "+12%"},
    {"icon": "⚠️", "label": "Pending", "value": "23", "action": "View All"}
  ]
}
```

### Charts (for trends, comparisons, analytics)
```ui:chart
{
  "type": "bar",
  "title": "Monthly Sales",
  "labels": ["Jan", "Feb", "Mar"],
  "datasets": [{"label": "Revenue", "data": [100, 150, 200], "backgroundColor": "#3fb950"}]
}
```

### Action Buttons (for follow-up actions)
```ui:action_buttons
{
  "buttons": [
    {"label": "Export CSV", "icon": "📥", "style": "primary", "action": "export_csv"},
    {"label": "Send Reminder", "icon": "📧", "style": "secondary", "action": "send_reminder"}
  ]
}
```

### Progress Bars (for status, completion)
```ui:progress
{"label": "Processing", "value": 75, "max": 100, "showPercent": true}
```

### Alerts (for warnings, success, info)
```ui:alert
{"type": "warning", "title": "Attention", "message": "3 invoices are overdue"}
```

### Forms (for collecting user input)
```ui:form
{
  "title": "Quick Approval",
  "fields": [
    {"name": "reason", "label": "Reason", "type": "text", "required": true},
    {"name": "priority", "label": "Priority", "type": "select", "options": ["Low", "Medium", "High"]}
  ],
  "submitLabel": "Submit",
  "submitAction": "approve_with_reason"
}
```

### Mermaid Diagrams (for flows, sequences, timelines, ER diagrams)
```mermaid
graph TD
  A[Start] --> B{Decision}
  B -->|Yes| C[Action A]
  B -->|No| D[Action B]
```
Supported diagram types:
- `graph TD` / `graph LR` — flowcharts (process flows, decision trees)
- `sequenceDiagram` — system/API interaction sequences
- `gantt` — project timelines, period close schedules
- `erDiagram` — database / entity relationships
- `pie` — simple proportional breakdowns
- `journey` — user/process journey maps

**CRITICAL mermaid rules (violations break rendering):**
- Node labels must be on a SINGLE LINE — never put a literal newline inside `[]`, `()`, `{}`, or `(( ))`
- Keep labels short; if multi-word use a space, e.g. `A[Invoice Received]` not `A[Invoice\nReceived]`
- Arrow labels use `-->|text|` syntax with text on one line
- Do not use HTML tags inside node labels unless wrapped in `"quotes"`

### Email Compose (when user asks to send / email / notify someone)
```ui:email_compose
{
  "to": ["recipient@example.com"],
  "cc": [],
  "from": "sender@company.com",
  "subject": "Subject line here",
  "body": "Email body text here.\n\nRegards,\nAP Team"
}
```
- Pre-fill all fields from context (recipient from user request, subject/body from the data being shared)
- `to` must be a JSON array of strings, even for one recipient
- `body` is plain text; keep it professional and concise
- Use this whenever the user says: send, email, notify, share via email, forward, mail to

### Images (for charts saved as files, screenshots, generated visuals)
```ui:image
{
  "src": "/path/to/image.png",
  "alt": "Description of image",
  "title": "Optional caption",
  "width": "100%"
}
```

### HTML Preview (for rich reports, formatted output, custom layouts)
IMPORTANT: Output HTML reports using a standard fenced code block with the `html` language tag.
DO NOT output {"type":"html_preview","props":{...}} JSON — just use the code block directly:
```html
<!DOCTYPE html>
<html>
<head><style>/* your styles */</style></head>
<body>
  <!-- your full HTML report here -->
</body>
</html>
```
The UI will automatically render it as a live sandboxed preview. Use this for KPI dashboards with colour-coded status, multi-section reports, and custom styled tables.

**Guidelines:**
- Use tables for structured record lists (invoices, orders, users)
- Use stat cards for dashboard-style summaries (3-4 max)
- Use charts when showing trends over time or comparisons
- Use mermaid for process flows, approval sequences, ER diagrams, timelines
- Use action buttons when user might want follow-up actions
- Use forms when you need user input before proceeding
- Use html_preview for rich formatted reports that need custom styling
- Use image when referencing a saved chart, screenshot, or generated visual
- Use email_compose when user asks to send, email, notify, or share results via email — pre-fill all fields from context
- Combine components as needed (e.g., stat cards + table + action buttons)
- Always include relevant action buttons for actionable items
"""

    def _load_user_profile(self) -> str:
        """
        Load user profile from both global and agent-specific sources.
        
        DELEGATED to prompt_assembler.load_user_profile().
        See that module for implementation details.
        """
        return load_user_profile(self.kernel)

    def _resolve_context_file(self, ctx_file) -> Path:
        """Resolve the configured ``context_file_path`` under the tenant root.

        Accepts the documented tenant-relative form (``/shared/Enterprise_Context.md``) or a
        real path that already sits under the tenant root. Raises ``PathSecurityError`` for
        anything that would resolve outside the tenant root.
        """
        tenant_root = _tenant_root_from_agent_root(
            getattr(getattr(self, "kernel", None), "agent_root", None)
        )
        raw = str(ctx_file or "")
        try:
            return confine_to_root(validated_path(raw, label="context file"), tenant_root, label="context file")
        except PathSecurityError:
            return safe_join_under_root(tenant_root, raw, label="context file")

    def _read_skill_context_file(self, rel_path: str, max_chars: int = 20000) -> str:
        """Read a per-skill ``context_file`` (virtual path, e.g. ``shared/contexts/x.md``).

        Separate from the tenant-wide Enterprise_Context.md — this loads a doc attached to ONE
        skill, only when that skill is active. Returns '' on any failure; content is capped;
        a containment guard keeps reads under the tenant ``shared/`` root, and
        ``shared/config/`` (credential and connection config) is always refused.
        """
        try:
            raw = (rel_path or "").strip().lstrip("/")
            if not raw:
                return ""
            agent_root = getattr(getattr(self, "kernel", None), "agent_root", None)
            if not agent_root:
                return ""
            if raw.startswith("shared/"):
                remainder = raw[len("shared/"):]
            elif raw.startswith("contexts/"):
                remainder = raw
            else:
                remainder = "contexts/" + raw
            try:
                shared_root = _tenant_root_from_agent_root(agent_root) / "shared"
                candidate = safe_join_under_root(shared_root, remainder, label="skill context_file")
            except PathSecurityError:
                logger.warning("Skill context_file outside shared root, ignored: %s", rel_path)
                return ""
            # shared/config holds tenant credential/connection config — never prompt context.
            if candidate.is_relative_to(shared_root.resolve() / "config"):
                logger.warning("Skill context_file under shared/config is not allowed, ignored: %s", rel_path)
                return ""
            if not candidate.exists():
                logger.info("Skill context_file not found: %s", candidate)
                return ""
            return candidate.read_text(encoding="utf-8", errors="replace")[:max_chars]
        except Exception as exc:
            logger.debug("read_skill_context_file failed for %r: %s", rel_path, exc)
            return ""

    def _load_prompt(self, skill_name: str, query: str = None) -> str:
        """Load system prompt with IDENTITY context only.
        
        World knowledge (context graph, episodic memory) is now accessed
        via the query_memory tool INSIDE the ReAct loop, giving the agent
        autonomy to pull context on-demand based on the reasoning path.
        
        What stays here (identity - always relevant):
        - Skill prompt (SKILL.md)
        - Agentic guidelines
        - User profile & preferences
        - Short-term conversation history
        - Corrections/learnings (lightweight, no LLM)
        - Quick entity hints (regex-based, no LLM)
        - Auto-run/Ask-first mode
        - UI generation instructions
        
        What moved to query_memory tool (world knowledge - situational):
        - Context graph entities/decisions/knowledge
        - Episodic memory (past sessions)
        - Alias expansion
        """
        try:
            skill = self.loader.load(skill_name)
            base_prompt = self.loader.get_prompt(skill, include_files=True)

            # Per-skill context_file: inject this skill's own context doc (separate from the
            # tenant-wide Enterprise_Context.md), only while this skill is active. Default-off.
            _skill_ctx = getattr(skill, "context_file", "") or ""
            if _skill_ctx.strip():
                _ctx_text = self._read_skill_context_file(_skill_ctx)
                if _ctx_text:
                    base_prompt = f"{base_prompt}\n\n## Skill Context — {_skill_ctx}\n{_ctx_text}"
                    logger.info("Injected per-skill context_file (%d chars): %s", len(_ctx_text), _skill_ctx)

            # Knowledge bundles: make the skill's `knowledge:` paths reachable — tell the agent
            # they exist and can be read with the shell (cat/grep). Default-off when empty.
            _kn = [str(k).strip() for k in (getattr(skill, "knowledge", []) or []) if str(k).strip()]
            if _kn:
                base_prompt = (f"{base_prompt}\n\n## Knowledge bundles available to this skill\n"
                               f"Read these with the shell tool (cat/grep/ls) when relevant:\n"
                               + "\n".join(f"- {p}" for p in _kn))

            _is_plan_mode = getattr(self, '_execution_mode', 'react') == 'planned'
            _compact_lines = []
            for _domain in getattr(self, '_other_domains', []):
                try:
                    _domain_skill = self.loader.load(_domain)
                    if _is_plan_mode:
                        _desc = _domain_skill.description or f"Handles {_domain} domain queries."
                        _compact_lines.append(f"  - **{_domain}**: {_desc}")
                        logger.info("Multi-domain (plan): compact ref for '%s'", _domain)
                    else:
                        _domain_prompt = self.loader.get_prompt(_domain_skill, include_files=True)
                        base_prompt += (
                            f"\n\n---\n## ADDITIONAL DOMAIN CONTEXT: {_domain}\n"
                            f"The following is the expertise and data access for the '{_domain}' skill. "
                            f"Use this knowledge when the query requires data from this domain.\n\n"
                            f"{_domain_prompt}"
                        )
                        logger.info("Multi-domain: appended SKILL.md for '%s'", _domain)
                except Exception:
                    logger.error("Multi-domain: could not load SKILL.md for '%s'", _domain)

            if _compact_lines:
                base_prompt += (
                    "\n\n---\n## AVAILABLE SKILLS FOR PLANNING\n"
                    "The following skills are available when building a multi-step plan. "
                    "Use create_plan to assign steps to the correct skill.\n\n"
                    + "\n".join(_compact_lines)
                )

            # Build mode-specific instructions
            logger.debug("auto_run=%s", self.auto_run)
            if self.auto_run:
                mode_instruction = self.AUTO_RUN_INSTRUCTION
                logger.info("AUTO-RUN MODE: Adding auto-run instruction to prompt")
            else:
                mode_instruction = ""
                logger.info("ASK-FIRST MODE: Kernel will enforce confirmation for writes")

            # Fresh mode: tell LLM not to answer from conversation history
            fresh_mode_instruction = ""
            if getattr(self, 'light_mode', False):
                fresh_mode_instruction = self.FRESH_MODE_INSTRUCTION
                logger.info("FRESH MODE: Injecting live-data-required instruction")
            
            # Add UI generation instructions if render_ui is enabled (browser requests)
            ui_instruction = ""
            if getattr(self, 'render_ui', False):
                ui_instruction = self.UI_GENERATION_PROMPT
                logger.info("UI MODE: Adding UI generation instructions to prompt")
            
            
            # 1. User profile (file read)
            user_profile = self._load_user_profile()
            
            profile_section = ""
            if user_profile:
                profile_section = f"""# USER PREFERENCES
The following profile describes this user's preferences and context. Adapt your responses accordingly:

{user_profile}

---
"""
                logger.info("USER PROFILE: Loaded (%d chars)", len(user_profile))

            # Local folder tree — injected once at session start so agent knows
            # what documents exist under /local/ without needing to ls.
            local_tree_section = build_local_tree_section(self.kernel)
            if local_tree_section:
                logger.info("LOCAL TREE: Injected /local/ structure (%d chars)", len(local_tree_section))
            
            short_term_context = ""
            
            # 3. Confirmed knowledge (from knowledge store)
            # Mode: scan (full JSONL) | semantic (embedding search) | hybrid (semantic + scan backfill)
            knowledge_section = ""
            if not getattr(self, 'light_mode', False):
                kr_mode = getattr(self, 'knowledge_retrieval_mode', 'hybrid')
                if kr_mode not in ("scan", "semantic", "hybrid"):
                    kr_mode = "hybrid"
                try:
                    confirmed = []

                    # Entity-first: pull facts about the specific entity (newest first)
                    # before query-similarity search fills remaining slots.
                    _entity_hint = getattr(self, '_last_entity_hint', None)
                    if _entity_hint and hasattr(self.memory, 'knowledge_indexer'):
                        try:
                            ent_results = self.memory.knowledge_indexer.search_by_entity(
                                entity_name=_entity_hint,
                                top_k=5,
                            )
                            for r in ent_results:
                                confirmed.append({
                                    "type": r.get("knowledge_type", "knowledge"),
                                    "summary": r.get("summary", ""),
                                    "scope": {"applies_when": "", "recommended_tools": [], "skill": r.get("skill", "")},
                                    "entity_keys": r.get("entities", []),
                                    "id": r.get("id", ""),
                                    "_score": 1.0,
                                    "_match": r.get("match_method", "entity_xref"),
                                })
                            if ent_results:
                                logger.debug("ENTITY-FIRST: %d records for entity=%s", len(ent_results), _entity_hint)
                        except Exception as ent_err:
                            logger.warning("Entity-first knowledge fetch failed (non-fatal): %s", ent_err)

                    if kr_mode in ("semantic", "hybrid"):
                        # Semantic: query-aware retrieval via embeddings + FTS5
                        # Exclude IDs already fetched by entity-first to avoid duplicates
                        _entity_ids = {c["id"] for c in confirmed}
                        try:
                            sem_results = self.memory.knowledge_indexer.search_similar(
                                query=query or "",
                                top_k=10,
                                status="confirmed",
                                skill=skill_name,
                                min_score=0.3,
                                _precomputed_embedding=getattr(self, '_cached_query_embedding', None),
                            )
                            # Normalize keys — skip IDs already fetched by entity-first
                            for r in sem_results:
                                if r.get("id") in _entity_ids:
                                    continue
                                confirmed.append({
                                    "type": r.get("knowledge_type", "knowledge"),
                                    "summary": r.get("summary", ""),
                                    "scope": {"applies_when": "", "recommended_tools": [], "skill": r.get("skill", "")},
                                    "entity_keys": r.get("entities", []),
                                    "id": r.get("id", ""),
                                    "_score": r.get("score", 0),
                                    "_match": r.get("match_method", "semantic"),
                                })
                            logger.debug("SEMANTIC: %d results (mode=%s)", len(confirmed), kr_mode)
                        except Exception as sem_err:
                            logger.warning("Semantic search failed, falling back to scan: %s", sem_err)
                            kr_mode = "scan"  # Degrade gracefully
                        
                        # Hybrid backfill: if semantic returned too few, supplement from scan
                        if kr_mode == "hybrid" and len(confirmed) < 3:
                            scan_result = self.memory.query_knowledge(
                                status="confirmed", skill=skill_name, limit=10
                            )
                            scan_items = scan_result.get("items", []) if isinstance(scan_result, dict) else scan_result
                            seen_ids = {c.get("id") for c in confirmed}
                            for item in scan_items:
                                if item.get("id") not in seen_ids:
                                    confirmed.append(item)
                                if len(confirmed) >= 10:
                                    break
                            if len(scan_items) > 0:
                                logger.debug("HYBRID backfill: +%d from scan", len(confirmed) - len(seen_ids))
                    
                    if kr_mode == "scan" and not confirmed:
                        # Scan: original full-JSONL behavior (backward-compatible)
                        result = self.memory.query_knowledge(
                            status="confirmed", skill=skill_name, limit=10
                        )
                        confirmed = result.get("items", []) if isinstance(result, dict) else result
                        logger.debug("SCAN: %d confirmed records", len(confirmed))
                    
                    if confirmed:
                        knowledge_lines = []
                        for k in confirmed:
                            ktype = k.get("type", k.get("knowledge_type", "knowledge"))
                            summary = k.get("summary", "")[:120]
                            applies = k.get("scope", {}).get("applies_when", "")
                            entities = k.get("entity_keys", k.get("entities", []))
                            tools = k.get("scope", {}).get("recommended_tools", [])
                            score_tag = ""
                            if k.get("_score"):
                                score_tag = f" [relevance: {k['_score']:.2f}]"
                            line = f"- [{ktype}] {summary}{score_tag}"
                            if applies:
                                line += f" (when: {applies[:60]})"
                            if entities:
                                line += f" | entities: {', '.join(str(e) for e in entities[:5])}"
                            if tools:
                                line += f" | tools: {', '.join(str(t) for t in tools[:3])}"
                            knowledge_lines.append(line)
                        knowledge_section = f"""## 📚 Confirmed Knowledge
{chr(10).join(knowledge_lines)}
"""
                        logger.debug("KNOWLEDGE: %d records loaded (mode=%s)", len(knowledge_lines), kr_mode)
                except Exception as e:
                    logger.error("Knowledge load skipped: %s", e)

            memory_md_section = ""
            if not getattr(self, 'light_mode', False):
                try:
                    _mem_root = getattr(self.memory, 'memory_root', None)
                    if _mem_root:
                        _mem_content = _load_memory_md(
                            _mem_root,
                            user_id=getattr(self.memory, 'user_id', None),
                        )
                        if _mem_content:
                            memory_md_section = (
                                f"## What I Know\n{_mem_content}\n"
                                f"> These are summaries. Full detail for each topic is stored in subfolders "
                                f"under `/memory/` (e.g. `/memory/org/p2p_context.md`, `/memory/skills/...`). "
                                f"Use `shell` to read those files when you need complete context for a topic.\n\n---\n"
                            )
                            logger.info(
                                "MEMORY.MD: injected (%d chars)",
                                len(_mem_content),
                            )
                except Exception as _mme:
                    logger.warning("MEMORY.MD load skipped (non-fatal): %s", _mme)

            entity_context_section = ""
            _file_block = getattr(self, '_file_context_block', None)
            if _file_block:
                # File mode — simple string block, no xref SQL needed
                entity_context_section = _file_block
            else:
                # Table mode — existing resolution path below (unchanged)
                pass
            try:
                ectx = getattr(self, '_entity_context', None)
                if ectx and ectx.get("tree_context") and not _file_block:
                    lines = []
                    
                    for ent in ectx.get("resolved_entities", []):
                        lines.append(f"- **{ent['display_name']}** (score: {ent['score']:.2f}, via {ent.get('match_method', '?')})")

                    lines.append("")
                    lines.append("### Context Sources (use tools to fetch as needed)")
                    
                    for tc in ectx.get("tree_context", []):
                        meta = tc.get("metadata", {})
                        level = tc.get("level", "")
                        name = tc.get("name", tc.get("display_name", ""))
                        node_id = tc.get("node_id", "")
                        
                        if meta:
                            lines.append(f"**{name}** ({level}):")
                            lines.append(f"```json")
                            lines.append(json.dumps(meta, indent=2, default=str))
                            lines.append(f"```")
                            
                            context_sources = meta.get("context_sources", [])
                            for cs in context_sources:
                                if cs.get("type") == "api" and cs.get("credential_ref"):
                                    cred_ref = cs["credential_ref"]
                                    endpoint = cs.get("endpoint", "the external endpoint")
                                    lines.append(
                                        "  **→ Credential required:** "
                                        f"`get_credential {cred_ref} <field>` before calling {endpoint}; "
                                        "use the returned `$CRED_*` variable in curl. The real secret is substituted by the kernel."
                                    )

                    tree_path = " → ".join(n["name"] for n in ectx["tree_context"])
                    if tree_path:
                        lines.append(f"- Ontology path: {tree_path}")
                    if ectx.get("skill_hint"):
                        lines.append(f"- Entity signal: **{ectx['skill_hint']}**")
                    if ectx.get("process_hint"):
                        lines.append(f"- Process signal: **{ectx['process_hint']}**")
                        if ectx.get("process_matches"):
                            pm_desc = ", ".join(
                                f'{m.get("matched_alias", "")} ({m.get("display_name", "")})'
                                for m in ectx["process_matches"][:3]
                            )
                            lines.append(f"  Matched keywords: {pm_desc}")
                    if ectx.get("signals_agree") is False:
                        lines.append("- **Note**: Entity and process signals disagree — check user intent carefully")

                    xref_keys = ectx.get("entity_keys_for_xref", set())
                    if xref_keys and not getattr(self, 'light_mode', False):
                        try:
                            indexer = getattr(self.memory, 'knowledge_indexer', None)
                            if indexer:
                                ep_rows = indexer.expand_by_entities(
                                    set(xref_keys), record_type="episode", top_k=5)
                                if ep_rows:
                                    lines.append("")
                                    lines.append("### Recent Interactions")
                                    for row in ep_rows:
                                        ts_short = (row.get("ts") or "")[:10]
                                        summary = (row.get("summary") or row.get("user_input") or "")[:120]
                                        lines.append(f"- [{ts_short}] {summary}")

                                # Related knowledge
                                kv_rows = indexer.expand_by_entities(
                                    set(xref_keys), record_type="knowledge", top_k=3)
                                if kv_rows:
                                    lines.append("")
                                    lines.append("### Related Knowledge")
                                    for row in kv_rows:
                                        summary = (row.get("summary") or "")[:150]
                                        lines.append(f"- ({row.get('knowledge_type') or 'note'}) {summary}")
                                logger.info("ENTITY_XREF: Found %d episodes, %d knowledge for keys=%s",
                                           len(ep_rows), len(kv_rows), list(xref_keys)[:3])
                        except Exception as xref_err:
                            logger.error("Entity xref history lookup failed: %s", xref_err)

                    if lines:
                        entity_context_section = "## Entity Context (Ontology)\n" + "\n".join(lines) + "\n"
            except Exception:
                pass
            
            procedural_hints_section = ""
            _similar_patterns = getattr(self, '_similar_patterns_cache', [])
            
            if _similar_patterns:
                tool_hints = []
                for p in _similar_patterns[:3]:  # Top 3 most similar
                    user_input_short = (p.get("user_input") or "")[:60]
                    tools = p.get("tools", "")
                    if tools and user_input_short:
                        # Format: "shell,curl" → "shell → curl"
                        tool_chain = " → ".join(tools.split(",")[:4])
                        tool_hints.append(f'- "{user_input_short}" → {tool_chain}')
                
                if tool_hints:
                    procedural_hints_section = f"""## Past Successful Approaches
Similar queries succeeded with these tools:
{chr(10).join(tool_hints)}

Use this as guidance, but adapt to the current query's specific needs.
"""
                    logger.debug("PROCEDURAL HINTS: %d patterns injected", len(tool_hints))
            
            # 4. Skill grounding truth (static file read, if exists)
            grounding_section = ""
            grounding_file = self.memory.context_graph_path / "grounding" / f"{skill_name}.md"
            if grounding_file.exists():
                try:
                    grounding_content = grounding_file.read_text(encoding='utf-8')
                    grounding_section = f"""## Skill Grounding ({skill_name})
{grounding_content[:1000]}
"""
                except Exception:
                    pass
            
            # 5. Memory tool guidance (tell agent about both options)
            memory_tool_guidance = ""
            if not getattr(self, 'light_mode', False):
                memory_tool_guidance = """
## Your Memory System

You have persistent memory across conversations. USE IT PROACTIVELY.

### WHEN TO CHECK MEMORY (Before Acting)

**1. Entity mentioned** → Check status first
   - User mentions "ACME Corp" → What's their current status? Any flags?
   - Invoice/PO number appears → Do I know this entity? Any history?

**2. About to make a decision** → Check for precedent
   - Before recommending action → Have I handled similar cases?
   - Before processing exception → Any rules I've learned about this?

**3. User asks about history/context** → Search episodes
   - "What did we discuss about X?" → Check past conversations
   - "Why did we do Y?" → Check decisions for rationale

**4. Uncertain about facts** → Verify before assuming
   - Don't guess entity relationships → Check memory
   - Don't assume status → Look it up

### HOW TO ACCESS MEMORY

**Step 1 — Always call `query_memory` first**
```
query_memory("FastShip payment terms")           # entity-specific facts + recent episodes
query_memory("duplicate PO", scope="knowledge")  # rules, corrections, patterns
query_memory("BOFA dispute", scope="episodes")   # past conversations only
```
Scopes: "knowledge" | "episodes" | "all" (default)

`query_memory` returns:
- Structured records (entity facts newest first, then query-similarity matches)
- File paths for knowledge.jsonl and recent episode files
- A grep tip with the relevant keyword

**Step 2 — Grep the files if structured results are thin**

When `query_memory` returns fewer than 3 records, or you need more precision,
use the file paths it returned:
```bash
grep -i "fastship" /path/to/knowledge.jsonl
grep -i "INV-050" /path/to/history/2026-03-21/session.jsonl
```
Try 2-3 keyword variations before concluding nothing exists:
```bash
grep -i "fastship" /path/to/knowledge.jsonl  # try aliases too: vnd-777, berlin
```
Parse matching JSONL lines: each line is a JSON record — look at the "summary" field.

### Decision Guide:
| Situation | Action |
|---|---|
| Need facts about a specific entity | `query_memory("entity name")` |
| query_memory returned 3+ results | Use them directly |
| query_memory returned < 3 results | Grep the file paths it gave you |
| Need exact value (amount, date, ID) | Grep episode files |
| Aggregation / counting across records | Shell grep + count |
| Exploring what's in memory | `query_memory` first, then cat/head the files |
"""
            
            approval_prompt = ""
            try:
                skill_obj = self.loader.load(skill_name)
                if skill_obj.approval_rules:
                    approval_prompt = compile_rules_to_prompt(skill_obj.approval_rules)
                    logger.info("Approval rules injected: %d rule sections", len(skill_obj.approval_rules))
            except Exception:
                pass
            
            learn_marker_instruction = ""
            if not getattr(self, 'light_mode', False):
                learn_marker_instruction = """
## Self-Learning Protocol

When ANYTHING worth remembering emerges from this conversation — whether the USER stated it or YOU discovered it during execution — append an invisible HTML comment marker at the VERY END of your response:

<!-- LEARN: {"type": "<type>", "summary": "<what to remember>", "applies_when": "<context>", "entity_keys": ["<entity_id_or_name>"]} -->

- `entity_keys`: list any specific entities the knowledge is about (vendor IDs, invoice numbers, customer names etc). Leave as `[]` for general/process-level knowledge. Examples: `["VND-777", "FastShip Express"]`, `["INV-AP-1001"]`, `["CUST-001", "Acme Corp"]`.

Types: rule | preference | correction | exception | workaround | fact | pattern

### A. User-side (the user tells you something reusable)
- "auto approve anything below $5" → rule
- "I prefer tables over bullets" → preference
- "ACME Corp uses net-60" → fact
- "No, always use pytest not unittest" → correction
- "Skip step 3 for internal invoices" → exception
- "Use API v2 because v1 is deprecated" → workaround

### B. Response-side (YOU discover something during execution)
- You flagged an invoice because it exceeded a threshold → rule
- You applied a policy (e.g., manager approval above $X) → rule
- You used a workaround because a path was read-only or a system was unavailable → workaround
- You found a vendor uses specific payment terms → fact
- You noticed a recurring pattern across data → pattern
- You couldn't find a required document or PO → exception
- You created or applied a new rule/policy for the user → fact

### When to emit
- ALWAYS emit when the user expresses a rule, preference, correction, or override
- ALWAYS emit when your response applies a business rule, threshold, or policy
- ALWAYS emit when you use a workaround or encounter a system limitation
- ALWAYS emit when you discover a factual detail about an entity (vendor, customer, invoice)
- ALWAYS emit when you notice a data pattern worth tracking
- SKIP only for purely informational Q&A with zero actionable knowledge

### Rules
- Capture intent immediately — do NOT wait for user to confirm
- Keep summary concise (<100 chars) and actionable
- The marker is invisible to the user (HTML comment) — do NOT mention it
- Maximum 1 marker per response (pick the most important if multiple)
- applies_when should describe the context (e.g., "invoice processing", "vendor onboarding")
"""

            prompt = f"""{profile_section}{local_tree_section}{grounding_section}
# SKILL INSTRUCTIONS
{base_prompt}

{self.AGENTIC_PROMPT}
{mode_instruction}
{fresh_mode_instruction}
{ui_instruction}
{approval_prompt}
{memory_tool_guidance}
{learn_marker_instruction}
{memory_md_section}{short_term_context}
{knowledge_section}
{entity_context_section}
{procedural_hints_section}"""
            
            logger.info("Prompt assembled: %d chars (identity only, no pre-loaded world knowledge)", len(prompt))
            return prompt
            
        except FileNotFoundError:
            auto_run_block = self.AUTO_RUN_INSTRUCTION if self.auto_run else ""
            return f"You are a helpful assistant with access to a secure filesystem.\n\n{self.AGENTIC_PROMPT}\n{auto_run_block}"
    
    @staticmethod
    def _build_connection_guidance(connections: list, tool_names: set) -> str:
        """Build a system-prompt section that makes the skill's declared connections
        usable in natural language:

          - **Database** connections → the `run_sql_query` tool (routes by engine).
          - **REST API** connections → the `shell` tool with `curl`. There is no
            dedicated API tool; the kernel resolves secrets (get_credential /
            $CRED_<NAME>_<FIELD>) and applies the corporate CA bundle to curl, so a
            plain shell curl against a declared API works and stays secure.

        Listing each connection by name/URL is what lets the agent act on a
        natural-language request without the user spelling out the endpoint.
        Returns '' when there is nothing useful to say.
        """
        db_conns, api_conns = [], []
        for c in (connections or []):
            if not isinstance(c, dict):
                continue
            name = c.get("name")
            if not name:
                continue
            ctype = str(c.get("type") or "").lower()
            cfg = c.get("config", {}) or {}
            if ctype == "database":
                engine = str(cfg.get("engine") or "sqlite").lower()
                db_conns.append(f"{name} ({engine})")
            elif ctype == "api":
                api_conns.append({
                    "name": str(name),
                    "base_url": str(cfg.get("base_url") or "").rstrip("/"),
                    "auth_type": str(cfg.get("auth_type") or "").lower(),
                    "credential": str(cfg.get("credential") or cfg.get("credential_ref") or ""),
                    "verify_ssl": cfg.get("verify_ssl", None),
                })

        show_sql = "run_sql_query" in tool_names and db_conns
        show_api = "shell" in tool_names and api_conns
        if not (show_sql or show_api):
            return ""

        lines = ["\n## Data Connections\n",
                 "This skill declares the connections below. When the user asks about "
                 "one in natural language, act on it directly using the matching method — "
                 "you already have the endpoint here, so don't ask for the URL.\n"]

        if show_sql:
            lines.append(
                "### Databases — use `run_sql_query`\n"
                "Call `run_sql_query(database=\"<name>\", query=\"SELECT ...\")` "
                "(read-only: SELECT/WITH only). Do NOT shell out to a DB client. "
                "Available: " + ", ".join(db_conns) + ".\n"
            )

        if show_api:
            lines.append("### REST APIs — use `shell` + `curl`")
            lines.append(
                "There is no separate API tool — call these with the `shell` tool. The "
                "kernel applies the corporate CA bundle to curl automatically. For "
                "authenticated APIs, first run `get_credential <name> <field>` and then "
                "use the returned `$CRED_<NAME>_<FIELD>` placeholder in the curl header "
                "(the kernel substitutes the real secret at run time — never print it)."
            )
            for a in api_conns:
                base = a["base_url"] or "(no base_url set)"
                bits = [f"- **{a['name']}** — base URL `{base}`"]
                if a["auth_type"] and a["auth_type"] not in ("", "none"):
                    cred = a["credential"] or "<credential-name>"
                    if a["auth_type"] == "bearer":
                        bits.append(
                            f"; auth: Bearer. Run `get_credential {cred} token`, then "
                            f"`shell(command=\"curl -s -H 'Authorization: Bearer $CRED_{cred.upper()}_TOKEN' '{base}/<path>'\")`"
                        )
                    elif a["auth_type"] == "api_key":
                        bits.append(
                            f"; auth: API key. Run `get_credential {cred} key`, then send it in the "
                            f"`X-API-Key: $CRED_{cred.upper()}_KEY` header via curl."
                        )
                    elif a["auth_type"] == "basic":
                        bits.append(
                            f"; auth: Basic. Run `get_credential {cred} username` and "
                            f"`get_credential {cred} password`, then curl with "
                            f"`-u \"$CRED_{cred.upper()}_USERNAME:$CRED_{cred.upper()}_PASSWORD\"`."
                        )
                    else:
                        bits.append(f"; auth: {a['auth_type']} (credential `{cred}`).")
                else:
                    bits.append(
                        f"; no auth — e.g. `shell(command=\"curl -s '{base}/<path>'\")`"
                    )
                if str(a["verify_ssl"]).lower() in ("false", "0", "no", "off"):
                    bits.append(" This connection skips TLS verification — add `-k` to curl.")
                lines.append("".join(bits))
            lines.append("")

        return "\n".join(lines)

    def _create_agent(self, skill_name: str, query: str = None):
        """Create LangGraph agent with memory context and appropriate tools."""
        self._ensure_runtime_providers()
        system_prompt = self._load_prompt(skill_name, query=query)
        
        allowed_tools = self._get_allowed_tools()
        logger.debug("Allowed tools from config: %s", allowed_tools)
        tools = []

        skill_load_failed = False
        try:
            skill = self.loader.load(skill_name)
            skill_tools = list(getattr(skill, 'tools', []) or [])  # Dataclass attribute
        except Exception as _skill_load_exc:  # noqa: BLE001 - fail closed below
            skill = None
            skill_tools = []
            skill_load_failed = True
            logger.error(
                "Could not load skill '%s' for tool gating — withholding powerful "
                "tools (fail-closed): %s", skill_name, _skill_load_exc)
        logger.debug("Skill '%s' tools config: %s", skill_name, skill_tools)

        # Add shell tool if permitted for this skill (shell provides FS access)
        if tool_allowed_for_skill("shell", allowed_tools, skill_tools, skill_load_failed):
            tools.append(self._create_tool())
        elif "shell" in allowed_tools:
            logger.info(
                "shell tool withheld: agent allows it but skill '%s' does not declare it", skill_name)

        # Add write_file tool if permitted (multi-line content without escaping)
        if tool_allowed_for_skill("write_file", allowed_tools, skill_tools, skill_load_failed):
            tools.append(self._create_write_file_tool())
            logger.info("Added write_file tool")
        elif "write_file" in allowed_tools:
            logger.info(
                "write_file tool withheld: agent allows it but skill '%s' does not declare it", skill_name)
        else:
            logger.warning("write_file NOT in allowed_tools: %s", allowed_tools)
        
        if tool_allowed_for_skill("query_memory", allowed_tools, skill_tools, skill_load_failed) and not getattr(self, 'light_mode', False):
            tools.append(self._create_memory_tool())
            logger.info("Added query_memory tool (agent-driven context retrieval)")
        elif getattr(self, 'light_mode', False):
            logger.info("LIGHT MODE: query_memory tool skipped for fast response")
        elif "query_memory" in allowed_tools:
            logger.info(
                "query_memory tool withheld: agent allows it but skill '%s' does not declare it", skill_name)

        # Add fetch_canonical tool if allowed — grounds client-agnostic skills against
        # the active tenant binding (canonical intent -> resolved rows).
        if "fetch_canonical" in allowed_tools:
            tools.append(self._create_fetch_canonical_tool())
            logger.info("Added fetch_canonical tool (binding-grounded canonical data)")

        # Add context_query tool when in RLM context mode (reads the offloaded context handle)
        if self._rlm_mode_active() and "context_query" in allowed_tools:
            tools.append(self._create_context_query_tool())
            logger.info("Added context_query tool (RLM context handle)")
        
        # Check if skill needs SQL tool AND agent allows it
        try:
            if skill is None:
                skill = self.loader.load(skill_name)
                skill_tools = list(getattr(skill, 'tools', []) or [])
            logger.debug("Skill '%s' tools config: %s", skill_name, skill_tools)
            
            if 'run_sql_query' in skill_tools:
                if 'run_sql_query' in allowed_tools:
                    sql_mode = getattr(skill, 'sql_mode', 'read_only')
                    self._sql_write_allowed = (sql_mode == 'read_write')
                    tools.append(self._create_sql_tool(connections=getattr(skill, 'connections', [])))
                    mode_label = "read_write" if self._sql_write_allowed else "read_only"
                    logger.info("Added run_sql_query (%s) for skill '%s'", mode_label, skill_name)
                else:
                    logger.info("run_sql_query denied by agent config")

            if 'jev_decide' in skill_tools:
                _jev_gate = float(self.config.get("jev", {}).get("confidence_threshold", 0.90))
                tools.append(self.tool_provider.create_jev_tool(confidence_threshold=_jev_gate))
                logger.info("Added jev_decide tool (gate=%.2f) for skill '%s'", _jev_gate, skill_name)

            if 'jev_verify' in skill_tools:
                _jv_gate = float(self.config.get("jev", {}).get("verify_threshold", 0.65))
                tools.append(self.tool_provider.create_jev_verify_tool(self.kernel, confidence_threshold=_jv_gate))
                logger.info("Added jev_verify tool (gate=%.2f) for skill '%s'", _jv_gate, skill_name)

            if 'jev_see' in skill_tools:
                _vs_gate = float(self.config.get("vision", {}).get("confidence_threshold", 0.80))
                tools.append(self.tool_provider.create_jev_vision_tool(confidence_threshold=_vs_gate))
                logger.info("Added jev_see tool (gate=%.2f) for skill '%s'", _vs_gate, skill_name)
            if 'jev_vision_verify' in skill_tools:
                _vv_gate = float(self.config.get("vision", {}).get("verify_threshold", 0.65))
                tools.append(self.tool_provider.create_jev_vision_verify_tool(self.kernel, confidence_threshold=_vv_gate))
                logger.info("Added jev_vision_verify tool (gate=%.2f) for skill '%s'", _vv_gate, skill_name)

            # Add request_human_approval tool if skill has approval_rules
            # OR if 'request_human_approval' is explicitly in skill tools list
            if skill.approval_rules or 'request_human_approval' in skill_tools:
                approval_tool = self._create_approval_tool(skill)
                tools.append(approval_tool)
                logger.info("Added request_human_approval tool for skill '%s'", skill_name)

            if 'pause_in_chat' in skill_tools:
                tools.append(self._create_pause_in_chat_tool(skill))
                logger.info("Added pause_in_chat tool for skill '%s'", skill_name)

            if skill.path:
                _guard = getattr(self.kernel, "untrusted_execution_guard", False)
                if _guard and _skill_path_is_personal(skill.path, getattr(self.kernel, "agent_root", "")):
                    logger.warning(
                        "Untrusted-execution guard: skipping bundled tool scripts for personal "
                        "skill '%s' (%s)", skill_name, skill.path,
                    )
                else:
                    _agent_root = str(getattr(self.kernel, "agent_root", "") or "")
                    try:
                        bundled = self.tool_provider.load_skill_tools(
                            skill.path,
                            agent_root=_agent_root,
                        )
                    except TypeError as exc:
                        # Back-compat: some ToolProviders don't accept the agent_root kwarg.
                        msg = str(exc)
                        if "agent_root" in msg and "unexpected keyword argument" in msg:
                            bundled = self.tool_provider.load_skill_tools(skill.path)
                        else:
                            raise
                    if bundled:
                        bundled = [
                            t for t in bundled
                            if self._entitlement_allowed("use", "tool", getattr(t, "name", ""), {"skill": skill_name})
                        ]
                        tools.extend(bundled)
                        logger.info("Loaded %d bundled tool(s) for skill '%s': %s", len(bundled), skill_name, [t.name for t in bundled])
            
            try:
                agent_mcp_conns = self.config.get("mcp", {}).get("connections", [])
                skill_mcp_conns = getattr(skill, "mcp_connections", [])
                agent_mcp_conns = [
                    conn for conn in agent_mcp_conns
                    if self._mcp_connection_allowed(conn, skill_name)
                ]
                skill_mcp_conns = [
                    conn for conn in skill_mcp_conns
                    if self._mcp_connection_allowed(conn, skill_name)
                ]

                _mcp_guard = getattr(self.kernel, "untrusted_execution_guard", False)
                if _mcp_guard and _skill_path_is_personal(
                    getattr(skill, "path", ""), getattr(self.kernel, "agent_root", "")
                ):
                    _before = len(skill_mcp_conns)
                    skill_mcp_conns = [c for c in skill_mcp_conns if not _is_local_stdio_mcp(c)]
                    if len(skill_mcp_conns) != _before:
                        logger.warning(
                            "Untrusted-execution guard: dropped %d local stdio MCP connection(s) "
                            "from personal skill '%s'", _before - len(skill_mcp_conns), skill_name,
                        )

                # Resolve credential_ref in MCP connections from the credential store
                # so skills can reference stored credentials instead of env vars.
                _tenant_cfg_dir = _tenant_config_dir(getattr(self.kernel, "tenant_root", None))
                if _tenant_cfg_dir is not None:
                    def _resolve_mcp_cred(conn: dict):
                        """Resolve a connection's credential_ref via the SCOPED store.

                        Returns the connection with bearer auth injected, the connection
                        unchanged when it declares no credential_ref, or None to DROP it
                        (fail closed) when a declared credential is missing, scope-denied,
                        or has no usable secret — so discovery never reaches the server
                        without the required credential.
                        """
                        cred_ref = conn.get("credential_ref")
                        if not cred_ref:
                            return conn
                        try:
                            # Resolve through the SCOPED credential store so credential_ref
                            # honours the credential's consumer scope (SCOPE_DENIED when this
                            # skill isn't allowed) — the same access control as ${CRED:...}.
                            from .tools.mcp_bridge import _get_cred_store as _mcp_cred_store
                            _store = _mcp_cred_store(str(_tenant_cfg_dir))
                            _raw = _store.get(
                                cred_ref, consumer=(skill_name or None), purpose="mcp_connection"
                            ) if _store is not None else None
                        except Exception as _e:
                            logger.warning("MCP credential_ref '%s' resolution error: %s", cred_ref, _e)
                            _raw = None
                        # CredentialStore.get() returns a Credential dataclass (.value is the
                        # secret dict); tolerate a plain dict too for alternate backends.
                        _val = {}
                        if _raw is not None:
                            _v = getattr(_raw, "value", None)
                            if _v is None and isinstance(_raw, dict):
                                _v = _raw.get("value")
                            if isinstance(_v, dict):
                                _val = _v
                        _tok = _val.get("token") or _val.get("key") or _val.get("password", "")
                        if _tok:
                            conn = dict(conn)
                            conn["auth"] = {"type": "bearer", "token": _tok}
                            conn.pop("credential_ref", None)  # consumed
                            return conn
                        # Fail closed: a credential_ref was declared but could not be
                        # resolved under this skill's scope. Drop the connection.
                        logger.warning(
                            "MCP connection '%s': credential_ref '%s' unresolved or scope-denied "
                            "for skill '%s'; dropping connection (fail closed).",
                            conn.get("name"), cred_ref, skill_name,
                        )
                        return None
                    agent_mcp_conns = [c for c in (_resolve_mcp_cred(x) for x in agent_mcp_conns) if c is not None]
                    skill_mcp_conns = [c for c in (_resolve_mcp_cred(x) for x in skill_mcp_conns) if c is not None]

                if agent_mcp_conns or skill_mcp_conns:
                    # Thread the credential scope EXPLICITLY to the bridge so ${CRED:...}
                    # resolves per-call, isolated from the process-global env (which is
                    # shared across concurrent resumes — see mcp_bridge._resolve_env_vars).
                    # The env vars are still set as a back-compat fallback for any resolver
                    # that doesn't receive the explicit scope.
                    _cred_consumer = skill_name or ""
                    _cred_cfg_dir = str(_tenant_cfg_dir) if _tenant_cfg_dir is not None else None
                    _prev_cred_consumer = os.environ.get("AGENTOS_CRED_CONSUMER")
                    _prev_cred_cfg_dir = os.environ.get("AGENTOS_CREDENTIAL_CONFIG_DIR")
                    os.environ["AGENTOS_CRED_CONSUMER"] = _cred_consumer
                    if _tenant_cfg_dir is not None:
                        os.environ["AGENTOS_CREDENTIAL_CONFIG_DIR"] = str(_tenant_cfg_dir)
                    try:
                        from .tools.mcp_bridge import MCPToolBridge
                        bridge = MCPToolBridge.from_merged_config(
                            agent_mcp_conns, skill_mcp_conns,
                            consumer=_cred_consumer or None, config_dir=_cred_cfg_dir,
                        )
                        errors = bridge.validate()
                        if errors:
                            for err in errors:
                                logger.error("MCP config error: %s", err)

                        # Async tool discovery — run in event loop
                        import asyncio
                        try:
                            loop = asyncio.get_running_loop()
                        except RuntimeError:
                            loop = None

                        if loop and loop.is_running():
                            import concurrent.futures
                            from .tools.mcp_bridge import _discovery_timeout as _mcp_disc_timeout
                            _outer_timeout = _mcp_disc_timeout() + 10
                            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                                mcp_tools = pool.submit(asyncio.run, bridge.get_tools()).result(timeout=_outer_timeout)
                        else:
                            mcp_tools = asyncio.run(bridge.get_tools())
                    finally:
                        # Restore prior credential-resolution env so one skill's discovery
                        # never leaks its consumer/config-dir into another's.
                        if _prev_cred_consumer is None:
                            os.environ.pop("AGENTOS_CRED_CONSUMER", None)
                        else:
                            os.environ["AGENTOS_CRED_CONSUMER"] = _prev_cred_consumer
                        if _prev_cred_cfg_dir is None:
                            os.environ.pop("AGENTOS_CREDENTIAL_CONFIG_DIR", None)
                        else:
                            os.environ["AGENTOS_CREDENTIAL_CONFIG_DIR"] = _prev_cred_cfg_dir
                    
                    if mcp_tools:
                        mcp_tools = [
                            t for t in mcp_tools
                            if self._entitlement_allowed("use", "tool", getattr(t, "name", ""), {"skill": skill_name})
                        ]
                        _mcp_allow: list[str] = []
                        for _entry in (getattr(skill, "mcp_tools", []) or []):
                            if isinstance(_entry, str):
                                _n = _entry.strip().lower()
                                if _n:
                                    _mcp_allow.append(_n)
                            elif isinstance(_entry, dict):
                                # Legacy per-server dict: read the "tools" list.
                                _server_tools = _entry.get("tools") or []
                                if isinstance(_server_tools, (list, tuple)):
                                    for _tn in _server_tools:
                                        _s = str(_tn).strip().lower()
                                        if _s:
                                            _mcp_allow.append(_s)
                                # Some authors write ``{name: tool_name}`` — accept it.
                                elif _entry.get("name"):
                                    _s = str(_entry["name"]).strip().lower()
                                    if _s:
                                        _mcp_allow.append(_s)
                        if _mcp_allow:
                            _allow_set = set(_mcp_allow)
                            _before = len(mcp_tools)
                            mcp_tools = [t for t in mcp_tools if getattr(t, "name", "").lower() in _allow_set]
                            logger.info("MCP tool allowlist for skill '%s': kept %d of %d tool(s)", skill_name, len(mcp_tools), _before)
                        tools.extend(mcp_tools)
                        logger.info("Loaded %d MCP tool(s) for skill '%s': %s", len(mcp_tools), skill_name, [t.name for t in mcp_tools])
                        summary = bridge.get_connection_summary()
                        logger.debug("MCP sources: %s connection(s) -- direct=%d, registry=%d", summary.get('total'), len(summary.get('direct') or []), len(summary.get('registry') or []))
                    else:
                        logger.info("MCP connections configured but yielded 0 tools")
            except Exception as mcp_err:
                logger.error("MCP tool loading failed (non-fatal): %s", mcp_err)
                
        except Exception as e:
            logger.error("Error loading skill tools: %s", e)
        
        _depth = getattr(self, '_invoke_depth', 0)
        if _depth < MAX_INVOKE_DEPTH:
            # Factory creates child SkillAgent with depth+1 (reuses _run_supervisor pattern)
            _parent_depth = _depth

            def _child_agent_factory(child_skill_name: str):
                """Create a child SkillAgent for cross-skill delegation."""
                child = SkillAgent(
                    kernel=self.kernel,
                    skills_path=self.skills_path,
                    user_id=self.user_id,
                )
                child.set_entitlement_context(self.entitlement_principal, self.entitlement_checker)
                child._invoke_depth = _parent_depth + 1
                child.current_skill = child_skill_name
                child.auto_run = self.auto_run  # Propagate auto_run so child doesn't gate on confirmation
                return child

            if "invoke_skill" in allowed_tools:
                tools.append(self.tool_provider.create_invoke_skill_tool(
                    router=self.router,
                    agent_factory_fn=_child_agent_factory,
                    current_depth=_depth,
                ))
                logger.info("Added invoke_skill tool (depth=%d)", _depth)

            if "invoke_plan" in allowed_tools:
                tools.append(self.tool_provider.create_invoke_plan_tool(
                    agent_factory_fn=_child_agent_factory,
                    tools_map_fn=self._get_tools_map,
                    current_depth=_depth,
                    router=self.router,
                ))
                logger.info("Added invoke_plan tool (depth=%d)", _depth)

            if "create_plan" in allowed_tools:
                tools.append(self.tool_provider.create_create_plan_tool(
                    agent=self,
                    llm=getattr(self, 'light_llm', self.llm),
                    router=self.router,
                ))
                logger.info("Added create_plan tool (depth=%d)", _depth)

        else:
            logger.info("Delegation tools skipped (depth=%d >= max=%d)", _depth, MAX_INVOKE_DEPTH)

        if not tools:
            if tool_allowed_for_skill("shell", allowed_tools, skill_tools, skill_load_failed):
                logger.warning("No tools available! Adding shell as fallback.")
                tools = [self._create_tool()]
            else:
                logger.warning(
                    "No tools available for skill '%s' and shell is withheld by its "
                    "declared tool list; proceeding with no runtime tools.", skill_name)

        _conns = []
        try:
            _conns = getattr(skill, "connections", []) or []
        except NameError:
            _conns = []
        if _conns:
            _tool_names = {getattr(t, "name", "") for t in tools}
            system_prompt += self._build_connection_guidance(_conns, _tool_names)

        self._react_system_prompt = system_prompt
        self._react_tools = list(tools)
        logger.info("Agent created with %d tools: %s", len(tools), [t.name for t in tools])
        return create_react_agent(self.llm, tools, prompt=system_prompt)
    
    def _create_approval_tool(self, skill):
        """
        Create the request_human_approval tool with an embedded rule guard.

        The tool guard enforces approval_rules at the framework level:
        - never_require → rejects the tool call ('no approval needed')
        - urgency escalation from threshold/condition matches
        - Returns __APPROVAL_CHECKPOINT__|{approval_id} sentinel to pause agent
        """
        rules = getattr(skill, 'approval_rules', {}) or {}
        agent_ref = self  # Capture for closure

        @tool
        def request_human_approval(
            reason: str,
            context: str,
            options: str = '["Approve", "Reject"]',
            urgency: str = "medium",
        ) -> str:
            """Request human approval before proceeding with an action.
            
            Use this tool when you need human authorization for a business decision,
            high-value transaction, policy-sensitive action, or when you're uncertain
            how to proceed.
            
            Args:
                reason: Why human approval is needed (reference the policy rule)
                context: JSON string with relevant data (amounts, entities, identifiers)
                options: JSON string list of choices, e.g. '["Approve", "Reject"]'
                urgency: low | medium | high | critical
            
            Returns:
                Confirmation that approval has been queued. Agent should STOP after this.
            """
            import uuid as _uuid

            if getattr(agent_ref, '_hitl_decision_injected', False):
                return (
                    f"This action has already been approved by a human approver. "
                    f"Proceed with the task — no additional approval needed."
                )

            try:
                ctx = json.loads(context) if isinstance(context, str) else context
            except (json.JSONDecodeError, TypeError):
                ctx = {"raw": str(context)}

            # Inject Mission Mode attribution (set by mission_engine.run_iteration())
            # so the workstream detail page filter can reliably attribute the approval.
            _ws = getattr(agent_ref, "_mission_workstream", None)
            _item_id = getattr(agent_ref, "_mission_item_id", None)
            if _ws and isinstance(ctx, dict):
                ctx.setdefault("workstream_name", _ws)
                if _item_id:
                    ctx.setdefault("mission_item_id", _item_id)

            try:
                opts = json.loads(options) if isinstance(options, str) else options
            except (json.JSONDecodeError, TypeError):
                opts = ["Approve", "Reject"]

            action = ctx.get("action", "")
            never = [s.lower() for s in rules.get("never_require", [])]
            if action and action.lower() in never:
                return f"No approval needed for '{action}'. Proceed with the action."

            if rules:
                urgency_final = escalate_urgency(ctx, rules, urgency)
            else:
                urgency_final = urgency

            rule_matched = None
            rule_type = "agent_initiated"
            if rules:
                result = evaluate_rules(ctx, rules)
                if result:
                    rule_matched = result[0]  # reason from rule
                    rule_type = result[2]      # threshold/condition/always_require

            approval_id = str(_uuid.uuid4())
            sla = get_sla_minutes(urgency_final, rules)

            # Store approval metadata on agent for run() to pick up
            agent_ref.approval_pending = {
                "approval_id": approval_id,
                "reason": reason,
                "context": ctx,
                "options": opts,
                "urgency": urgency_final,
                "sla_minutes": sla,
                "skill": getattr(skill, 'name', 'unknown'),
                "rule_matched": rule_matched,
                "rule_type": rule_type,
                "timestamp": datetime.now().isoformat(),
            }

            logger.info("HITL Approval requested: %s (urgency=%s, sla=%sm)", reason, urgency_final, sla)

            # Return sentinel — agent.run() will detect this and checkpoint
            return f"__APPROVAL_CHECKPOINT__|{approval_id}|{reason}"

        return request_human_approval

    def _create_pause_in_chat_tool(self, skill):
        """Create the pause_in_chat tool — the in-chat twin of request_human_approval.

        Unlike request_human_approval (which agent.run() rewrites into a Command
        Center approval card), pause_in_chat renders the EXACT markdown the skill
        passes (tables/prose) as the paused turn's message, and marks the pause
        `resume_kind: "inline_chat"` so state.py skips the dashboard broadcast.
        The pause itself is resolved from chat (type "approve"/"reject") via the
        existing WS keyword-resume path.

        NOTE (see docs/F5_USECASE/INLINE_CHAT_HITL_DESIGN.md, Review #1): this is a
        presentation + in-chat upgrade, NOT a new determinism guarantee. The "stop"
        is prompt-coaxed, exactly like request_human_approval. Do NOT gate a real
        write behind this tool — writes stay on the deterministic ccd_caller_gate.
        """
        agent_ref = self

        @tool
        def pause_in_chat(
            render: str,
            reason: str,
            options: str = '["Approve", "Reject"]',
            payload: str = "{}",
            urgency: str = "medium",
        ) -> str:
            """Pause the turn IN CHAT and show the skill's own content for approval.

            Render your tables/prose, then call this to pause. The framework shows
            `render` verbatim as this turn's message (no approval card) and holds the
            task until the user replies in chat. Agent should STOP after this — do NOT
            call any other tool in the same turn.

            Args:
                render: The exact markdown to display (e.g. your summary tables + a line
                        telling the user to reply "approve" or "reject").
                reason: Short label for this pause (used for audit + the resume message).
                options: JSON list of choices, e.g. '["Approve", "Reject"]'.
                payload: JSON string carried through resume (e.g. a staged-findings path).
                         The resumed skill should re-read its own staged file to act.
                urgency: low | medium | high | critical

            Returns:
                A pause sentinel. Agent should STOP after this.
            """
            import uuid as _uuid

            # Guard: on decision-injected resume, don't re-pause — proceed.
            if getattr(agent_ref, '_hitl_decision_injected', False):
                return (
                    "This step has already been resolved by a human in chat. "
                    "Proceed with the task — do NOT call pause_in_chat again."
                )

            try:
                pl = json.loads(payload) if isinstance(payload, str) else (payload or {})
            except (json.JSONDecodeError, TypeError):
                pl = {"raw": str(payload)}
            if not isinstance(pl, dict):
                pl = {"value": pl}

            try:
                opts = json.loads(options) if isinstance(options, str) else options
            except (json.JSONDecodeError, TypeError):
                opts = ["Approve", "Reject"]

            ctx = dict(pl)
            ctx["resume_kind"] = "inline_chat"
            _ws = getattr(agent_ref, "_mission_workstream", None)
            _item_id = getattr(agent_ref, "_mission_item_id", None)
            if _ws:
                ctx.setdefault("workstream_name", _ws)
                if _item_id:
                    ctx.setdefault("mission_item_id", _item_id)

            approval_id = str(_uuid.uuid4())
            agent_ref.approval_pending = {
                "approval_id": approval_id,
                "reason": reason,
                "context": ctx,
                "options": opts,
                "urgency": urgency,
                "sla_minutes": 120,
                "skill": getattr(skill, 'name', 'unknown'),
                "rule_type": "agent_initiated",
                "render": render,   # in-memory: what run() echoes as the paused message
                "timestamp": datetime.now().isoformat(),
            }

            logger.info("Inline-chat pause requested: %s (skill=%s)", reason, getattr(skill, 'name', '?'))
            return f"__CHAT_PAUSE__|{approval_id}"

        return pause_in_chat

    def _get_tools_map(self) -> dict:
        """
        Get a dictionary mapping action names to tool functions.
        Used by workflow/parallel engines.
        """
        self._ensure_runtime_providers()
        tools_map = {}

        def _govern_workflow_step(tool_name: str, tool_args: dict) -> "str | None":
            """Apply tool governance to a step the engine invokes directly.

            Workflow/parallel steps written as `action: shell` (rather than
            `action: skill`) call the tool straight out of this map, so they never pass
            through the react path's govern_tool_call. That meant PreToolUse hooks and
            the tenant's `hitl.*` rules did not apply to them — a policy configured to
            require sign-off would be live in chat and silently inert on the automated
            path, with nothing to warn the workflow author.

            `source="workflow_step"` keeps the pre-authorisation that makes workflows
            usable: the write heuristic is skipped (a human wrote the step), while hooks
            and the hitl policy run exactly as they do everywhere else.

            Returns an error string when the call must not proceed, else None.
            """
            try:
                decision = govern_tool_call(
                    self,
                    {"name": tool_name, "args": tool_args},
                    source="workflow_step",
                )
            except Exception as exc:  # noqa: BLE001 — never fail a step on governance plumbing
                logger.warning("Workflow step governance failed for %s (allowing): %s",
                               tool_name, exc)
                return None
            if decision.allowed:
                return None
            logger.info("Workflow step denied by governance: %s — %s",
                        tool_name, decision.reason)
            return f"Error [TOOL_BLOCKED]: {decision.reason}"

        if "shell" in self._get_allowed_tools():
            def shell_func(command: str) -> str:
                """Execute shell command via kernel, under the same governance as react."""
                denial = _govern_workflow_step("shell", {"command": command})
                if denial:
                    return denial
                call_id = f"workflow-shell-{uuid.uuid4()}"
                _ec = getattr(self, "_evidence_collector", None)
                if _ec is not None:
                    _ec.record_tool_call(call_id, "shell", {"command": command})
                result = self.kernel.run_shell_command(command, confirmed=True)
                if _ec is not None:
                    _ec.record_tool_result(call_id, "shell", result)
                return result
            tools_map['shell'] = shell_func


        # SQL tool (if available)
        try:
            sql_tool = self._create_sql_tool()
            if sql_tool:
                def sql_func(query: str, database: str = None) -> str:
                    """Execute SQL query under the same governance as react."""
                    denial = _govern_workflow_step(
                        "run_sql_query", {"query": query, "database": database}
                    )
                    if denial:
                        return denial
                    result = sql_tool.func(query=query, database=database)
                    _ec = getattr(self, "_evidence_collector", None)
                    if _ec is not None:
                        _ec.record_sql_result(query=query, result_text=result, database=database or "")
                    return result
                tools_map['run_sql_query'] = sql_func
        except Exception:
            pass  # SQL tool not available

        # context_query tool (RLM mode) — lets plan/workflow steps query the offloaded context
        try:
            if self._rlm_mode_active():
                _cq_tool = self._create_context_query_tool()

                def context_query_func(question: str) -> str:
                    """Query the offloaded RLM context."""
                    return _cq_tool.func(question=question)
                tools_map['context_query'] = context_query_func
        except Exception:
            pass

        return tools_map

    def _finalize_evidence_bundle(self, response_text: str = "", trace_id: str = "", query_text: str = ""):
        """Build the per-run evidence bundle from captured tool observations."""
        try:
            _ec = getattr(self, '_evidence_collector', None)
            if _ec is not None:
                _mem = getattr(self, 'memory', None)
                _highlight_config = {}
                try:
                    _skill_name = getattr(self, "current_skill", None)
                    if _skill_name:
                        _skill = self.loader.load(_skill_name)
                        _highlight_config = getattr(_skill, "evidence_highlights", {}) or {}
                except Exception as _cfg_err:
                    logger.debug("Evidence highlight config load failed (non-fatal): %s", _cfg_err)
                self._evidence_bundle = _ec.get_bundle(
                    response_text=response_text or '',
                    query_text=query_text or '',
                    trace_id=str(trace_id or ''),
                    tenant_id=getattr(_mem, 'tenant_id', '') or '',
                    agent_id=getattr(_mem, 'agent_id', '') or '',
                    user_id=self.user_id or '',
                    execution_source=getattr(self, '_evidence_execution_source', 'chat'),
                    highlight_config=_highlight_config,
                )
        except Exception as _ev_err:
            logger.debug("Evidence bundle build failed (non-fatal): %s", _ev_err)
    
    def _run_workflow(self, skill, query: str, return_tool_calls: bool, emit_status):
        """
        Execute skill using deterministic workflow engine.
        
        Supports:
        - shell: Execute shell commands
        - skill: Invoke another skill with a specific task
        - condition: Branch based on output content
        
        No LLM calls between steps - pure rule-based execution
        (except when invoking 'skill' action which uses LLM).
        """
        import time
        start_time = time.time()
        
        if not skill.steps:
            # No steps defined - fall back to single-command execution
            logger.warning("Workflow mode but no steps defined for skill: %s", skill.name)
            return (f"Error: Skill '{skill.name}' has execution_mode=workflow but no steps defined.", []) if return_tool_calls else f"Error: Skill '{skill.name}' has execution_mode=workflow but no steps defined."
        
        # Create workflow engine with available tools and agent factory for skill steps
        tools_map = self._get_tools_map()
        
        # Factory to create agents for skill steps
        def create_workflow_agent(skill_name: str):
            """Create a child SkillAgent for skill steps in workflow."""
            worker = SkillAgent(
                kernel=self.kernel,
                skills_path=self.skills_path,
                user_id=self.user_id
            )
            worker.current_skill = skill_name
            return self._inherit_workflow_child_context(worker)
        
        engine = WorkflowEngine(tools_map, agent_factory=create_workflow_agent, parent_agent=self)

        steps = [Step.from_dict(s) for s in skill.steps]

        emit_status(f"Executing {len(steps)} workflow steps...")
        logger.info("Starting workflow with %d steps", len(steps))

        # Execute workflow — pass query as initial_context so {{_input.output}} works in condition steps
        results = engine.run(steps, status_callback=emit_status, initial_context=query)
        
        # HITL: propagate child approval to parent agent
        if getattr(engine, 'approval_pending', None):
            self.approval_pending = engine.approval_pending
        
        # HITL: If workflow paused for approval, save checkpoint for resume
        if getattr(engine, 'paused_for_approval', False):
            # Save child agent state so we can resume the paused step on approval
            paused_step_state = None
            if engine.paused_child_agent:
                paused_step_state = engine.paused_child_agent.export_state()
            
            self._workflow_checkpoint = {
                "skill_name": skill.name,
                "remaining_steps": [self._step_to_dict(s) for s in engine.remaining_steps],
                "completed_results": {name: {"output": r.output, "success": r.success, "error": r.error}
                                      for name, r in engine.results.items()},
                "paused_step": self._step_to_dict(engine.paused_step) if engine.paused_step else None,
                "paused_child_state": paused_step_state,
            }
            logger.info("Workflow checkpoint saved: step '%s' paused, %d steps remaining", engine.paused_step.name if engine.paused_step else '?', len(engine.remaining_steps))
        
        # Format response — prefer last skill/LLM step output over raw workflow log
        duration_ms = int((time.time() - start_time) * 1000)
        if getattr(engine, 'paused_for_approval', False):
            response = engine.format_summary()
            response += f"\n\n*Workflow paused after {duration_ms}ms — awaiting human approval to continue*"
        else:
            # Find the last successful skill-action step output (contains LLM-generated content)
            last_skill_output = None
            for name, result in engine.results.items():
                step_obj = next((s for s in steps if s.name == name), None)
                # Skip injected context and any condition/branch steps — they never produce user-visible content
                if not step_obj or step_obj.action in ("condition",) or name == "_input":
                    continue
                if step_obj.action == "skill" and result.success and result.output:
                    last_skill_output = result.output
            if last_skill_output:
                response = last_skill_output
                response += f"\n\n*Workflow completed in {duration_ms}ms*"
            else:
                response = engine.format_summary()
                response += f"\n\n*Workflow completed in {duration_ms}ms*"
        
        # Collect structured workflow steps for Workstream Detail / audit views.
        tool_calls_log = []
        for step in steps:
            result = results.get(step.name)
            if not result:
                continue
            tool_calls_log.append({
                "tool_name": step.name,
                "name": step.name,
                "action": step.action,
                "skill": step.skill or "",
                "status": "completed" if result.success else "failed",
                "duration_ms": result.duration_ms,
                # Show what the step ACTUALLY received (post-{{step.output}} interpolation),
                # falling back to the declared template only if no resolved value was captured.
                "input": getattr(result, "resolved_input", "") or step.task or step.params or "",
                "output": result.output or "",
                "error": result.error or "",
            })
        
        self.memory.add_to_short_term(role="user", content=query, skill=skill.name)
        self.memory.add_to_short_term(role="assistant", content=response, skill=skill.name)
        
        if return_tool_calls:
            return response, tool_calls_log
        return response
    
    def _resume_workflow(self, skill, query: str, return_tool_calls: bool, emit_status):
        """
        Resume a workflow that was paused for HITL approval.
        
        Picks up from the checkpoint: restores completed results,
        then executes remaining steps.
        """
        import time
        start_time = time.time()
        
        checkpoint = self._workflow_checkpoint
        remaining_step_dicts = checkpoint["remaining_steps"]
        completed_results = checkpoint["completed_results"]
        paused_step_dict = checkpoint.get("paused_step")
        paused_child_state = checkpoint.get("paused_child_state")
        
        logger.info("Resuming workflow: paused_step=%s, %d steps remaining", paused_step_dict.get('name') if paused_step_dict else 'none', len(remaining_step_dicts))

        if not paused_step_dict and not remaining_step_dicts:
            logger.error(
                "Workflow resume checkpoint is incomplete: no paused step and no remaining steps "
                "(skill=%s). Refusing to report success.", getattr(skill, "name", "?")
            )
            raise RuntimeError(
                "Cannot resume workflow: the checkpoint records no paused step and no remaining "
                "steps, so the approval has nothing to execute. Refusing to mark this complete."
            )

        tools_map = self._get_tools_map()
        
        def create_workflow_agent(skill_name: str):
            worker = SkillAgent(
                kernel=self.kernel,
                skills_path=self.skills_path,
                user_id=self.user_id
            )
            worker.current_skill = skill_name
            return self._inherit_workflow_child_context(worker)
        
        engine = WorkflowEngine(tools_map, agent_factory=create_workflow_agent, parent_agent=self)
        
        # Restore completed results so {{step.output}} references work
        for name, res_data in completed_results.items():
            engine.results[name] = StepResult(
                name=name,
                success=res_data["success"],
                output=res_data["output"],
                error=res_data.get("error"),
            )
        
        if paused_step_dict and paused_child_state:
            step_name = paused_step_dict["name"]
            skill_name = paused_step_dict.get("skill", "unknown")
            emit_status(f"Resuming paused step '{step_name}'...")
            logger.debug("Restoring child agent for step '%s' (skill: %s)", step_name, skill_name)
            
            # Recreate child agent and restore its conversation history
            child = SkillAgent(
                kernel=self.kernel,
                skills_path=self.skills_path,
                user_id=self.user_id
            )
            child.import_state(paused_child_state)
            self._inherit_workflow_child_context(child)
            child._hitl_decision_injected = True  # Suppress re-trigger
            
            # Inject the human decision and let the child complete
            decision_msg = query  # e.g., "[HUMAN DECISION] approved"
            logger.debug("Injecting decision into child: %s", decision_msg[:80])
            child_result = child.run(decision_msg, skill_name=skill_name)
            
            engine.results[step_name] = StepResult(
                name=step_name,
                success=True,
                output=str(child_result) if child_result else "",
            )
            logger.info("Paused step '%s' completed after approval", step_name)

        elif paused_step_dict:
            _fresh = dict(paused_step_dict)
            _fresh["task"] = (
                str(_fresh.get("task") or "")
                + f"\n\n{query}\n"
                + "A human reviewed the previous failed attempt(s) and released this step. "
                  "Perform it now and persist its result."
            )
            remaining_step_dicts = [_fresh] + list(remaining_step_dicts)
            logger.info("Resume: no saved child state for paused step '%s' — re-running it fresh",
                        paused_step_dict.get("name"))
            emit_status(f"Re-running '{paused_step_dict.get('name')}' after approval...")

        remaining_steps = [Step.from_dict(s) for s in remaining_step_dicts]
        if remaining_steps:
            emit_status(f"Continuing: {len(remaining_steps)} steps remaining...")
            results = engine.run(
                remaining_steps,
                status_callback=emit_status,
                preserve_existing_results=True,
            )
        else:
            results = engine.results
        
        # HITL: check if paused again (nested approval)
        if getattr(engine, 'approval_pending', None):
            self.approval_pending = engine.approval_pending
        
        if getattr(engine, 'paused_for_approval', False):
            paused_step_state = None
            if engine.paused_child_agent:
                paused_step_state = engine.paused_child_agent.export_state()
            self._workflow_checkpoint = {
                "skill_name": skill.name,
                "remaining_steps": [self._step_to_dict(s) for s in engine.remaining_steps],
                "completed_results": {name: {"output": r.output, "success": r.success, "error": r.error}
                                      for name, r in engine.results.items()},
                "paused_step": self._step_to_dict(engine.paused_step) if engine.paused_step else None,
                "paused_child_state": paused_step_state,
            }
            logger.info("Workflow re-paused: %d steps still remaining", len(engine.remaining_steps))
        else:
            # Workflow fully complete — clear checkpoint
            self._workflow_checkpoint = None
            logger.info("Workflow fully resumed and completed")
        
        duration_ms = int((time.time() - start_time) * 1000)
        response = engine.format_summary()
        if getattr(engine, 'paused_for_approval', False):
            response += f"\n\n*Workflow re-paused after {duration_ms}ms — awaiting another approval*"
        else:
            response += f"\n\n*Workflow resumed and completed in {duration_ms}ms*"
        
        tool_calls_log = []
        _logged_steps = ([paused_step_dict] if paused_step_dict else []) + remaining_step_dicts
        _seen_logged = set()
        for _s in _logged_steps:
            _name = _s.get("name") if isinstance(_s, dict) else None
            if not _name or _name in _seen_logged:
                continue  # the re-run branch puts the paused step in BOTH lists — log it once
            _res = engine.results.get(_name)
            if not _res:
                continue
            _seen_logged.add(_name)
            tool_calls_log.append({
                "tool_name": _name,
                "name": _name,
                "action": _s.get("action") or "skill",
                "skill": _s.get("skill") or "",
                "status": "completed" if _res.success else "failed",
                "duration_ms": getattr(_res, "duration_ms", 0) or 0,
                "input": getattr(_res, "resolved_input", "") or _s.get("task") or _s.get("params") or "",
                "output": _res.output or "",
                "error": _res.error or "",
            })

        self.memory.add_to_short_term(role="user", content=query, skill=skill.name)
        self.memory.add_to_short_term(role="assistant", content=response, skill=skill.name)
        
        if return_tool_calls:
            return response, tool_calls_log
        return response
    
    @staticmethod
    def _step_to_dict(step) -> dict:
        """Convert a Step object back to a serializable dict."""
        d = {"name": step.name, "action": step.action}
        if step.params:
            d["params"] = step.params
        if step.depends_on:
            d["depends_on"] = step.depends_on
        if step.skill:
            d["skill"] = step.skill
        if step.task:
            d["task"] = step.task
        if step.condition_if:
            d["if"] = step.condition_if
        if step.contains:
            d["contains"] = step.contains
        if step.equals:
            d["equals"] = step.equals
        if step.then_step:
            d["then"] = step.then_step
        if step.else_step:
            d["else"] = step.else_step
        return d
    
    def _run_parallel(self, skill, query: str, return_tool_calls: bool, emit_status):
        """
        Execute skill using parallel DAG engine.
        
        Independent steps run concurrently.
        Supports skill invocation for concurrent LLM calls.
        """
        import asyncio
        import time
        start_time = time.time()
        
        if not skill.steps:
            logger.warning("Parallel mode but no steps defined for skill: %s", skill.name)
            return (f"Error: Skill '{skill.name}' has execution_mode=parallel but no steps defined.", []) if return_tool_calls else f"Error: Skill '{skill.name}' has execution_mode=parallel but no steps defined."
        
        # Create parallel engine with available tools and agent factory for skill invocation
        tools_map = self._get_tools_map()
        
        # Factory function to create agents for skill steps
        def create_parallel_agent(skill_name: str):
            """Create a new SkillAgent instance for a skill step in parallel execution."""
            worker = SkillAgent(
                kernel=self.kernel,
                skills_path=self.skills_path,
                user_id=self.user_id
            )
            worker.current_skill = skill_name
            return worker
        
        engine = ParallelEngine(tools_map, agent_factory=create_parallel_agent, parent_agent=self)
        
        steps = [Step.from_dict(s) for s in skill.steps]
        
        emit_status(f"Executing {len(steps)} steps in parallel...")
        logger.info("Starting parallel execution with %d steps", len(steps))
        
        # Execute parallel workflow (handle asyncio nesting when inside uvicorn loop)
        try:
            try:
                loop = asyncio.get_running_loop()
            except RuntimeError:
                loop = None

            if loop and loop.is_running():
                import concurrent.futures
                with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                    results = pool.submit(
                        asyncio.run, engine.run(steps, status_callback=emit_status)
                    ).result(timeout=300)
            else:
                results = asyncio.run(engine.run(steps, status_callback=emit_status))
        except ValueError as e:
            return (f"Error: {str(e)}", []) if return_tool_calls else f"Error: {str(e)}"
        
        # HITL: propagate child approval to parent agent
        if getattr(engine, 'approval_pending', None):
            self.approval_pending = engine.approval_pending

        if getattr(engine, 'paused_for_approval', False):
            paused_step_state = None
            if engine.paused_child_agent:
                paused_step_state = engine.paused_child_agent.export_state()

            self._workflow_checkpoint = {
                "engine_mode": "parallel",
                "skill_name": skill.name,
                "remaining_steps": [self._step_to_dict(s) for s in engine.remaining_steps],
                "completed_results": {name: {"output": r.output, "success": r.success, "error": r.error}
                                      for name, r in engine.results.items()},
                "paused_step": self._step_to_dict(engine.paused_step) if engine.paused_step else None,
                "paused_child_state": paused_step_state,
            }
            logger.info("Parallel checkpoint saved: step '%s' paused, %d steps remaining",
                        engine.paused_step.name if engine.paused_step else '?', len(engine.remaining_steps))

        # Format response (reuse WorkflowEngine's format since structure is same)
        duration_ms = int((time.time() - start_time) * 1000)

        if getattr(engine, 'paused_for_approval', False):
            lines = ["## Parallel Execution Summary\n"]
            lines.append(f"**Total Steps:** {len(steps)}")
            lines.append(f"**Completed:** {len(results)}")
            lines.append(f"**Remaining:** {len(engine.remaining_steps)}\n")
            for name, result in results.items():
                status = "✅" if result.success else "❌"
                lines.append(f"{status} **{name}** ({result.duration_ms}ms)")
                if result.error:
                    lines.append(f"   Error: {result.error}")
            lines.append(
                f"\n*Parallel execution paused after {duration_ms}ms — awaiting human approval "
                f"({engine.paused_step.name if engine.paused_step else '?'}) to continue*"
            )
            response = "\n".join(lines)

            tool_calls_log = [f"{s.action}: {s.params}" for s in steps]
            self.memory.add_to_short_term(role="user", content=query, skill=skill.name)
            self.memory.add_to_short_term(role="assistant", content=response, skill=skill.name)
            if return_tool_calls:
                return response, tool_calls_log
            return response

        lines = ["## Parallel Execution Summary\n"]
        successful = sum(1 for r in results.values() if r.success)
        lines.append(f"**Total Steps:** {len(results)}")
        lines.append(f"**Successful:** {successful}")
        lines.append(f"**Failed:** {len(results) - successful}\n")
        
        for name, result in results.items():
            status = "✅" if result.success else "❌"
            lines.append(f"{status} **{name}** ({result.duration_ms}ms)")
            if result.error:
                lines.append(f"   Error: {result.error}")
        
        lines.append(f"\n*Parallel execution completed in {duration_ms}ms*")
        
        lines.append("\n---\n## Step Outputs\n")
        for name, result in results.items():
            if result.success and result.output:
                lines.append(f"### {name}\n")
                # Truncate long outputs but show key content
                output = result.output
                if len(output) > 2000:
                    output = output[:2000] + "\n... (truncated)"
                lines.append(output)
                lines.append("")
        
        response = "\n".join(lines)
        
        tool_calls_log = [f"{s.action}: {s.params}" for s in steps]
        
        self.memory.add_to_short_term(role="user", content=query, skill=skill.name)
        self.memory.add_to_short_term(role="assistant", content=response, skill=skill.name)
        
        if return_tool_calls:
            return response, tool_calls_log
        return response

    def _resume_parallel(self, skill, query: str, return_tool_calls: bool, emit_status):
        """
        Resume a parallel-DAG execution that paused for HITL approval.

        Mirrors _resume_workflow's checkpoint contract (same "remaining_steps" /
        "paused_step" / "paused_child_state" / "completed_results" shape), but drives
        ParallelEngine instead: completes the paused step's child conversation, then runs
        whatever steps hadn't been dispatched yet — respecting depends_on against the
        results restored from the completed waves before the pause.
        """
        import asyncio
        import time
        start_time = time.time()

        checkpoint = self._workflow_checkpoint
        remaining_step_dicts = checkpoint["remaining_steps"]
        completed_results = checkpoint["completed_results"]
        paused_step_dict = checkpoint.get("paused_step")
        paused_child_state = checkpoint.get("paused_child_state")

        logger.info("Resuming parallel execution: paused_step=%s, %d steps remaining",
                    paused_step_dict.get('name') if paused_step_dict else 'none', len(remaining_step_dicts))

        # Same fail-loud contract as _resume_workflow: an empty checkpoint must not silently
        # report success for work that never ran.
        if not paused_step_dict and not remaining_step_dicts:
            logger.error(
                "Parallel resume checkpoint is incomplete: no paused step and no remaining "
                "steps (skill=%s). Refusing to report success.", getattr(skill, "name", "?")
            )
            raise RuntimeError(
                "Cannot resume parallel execution: the checkpoint records no paused step and "
                "no remaining steps, so the approval has nothing to execute. Refusing to mark "
                "this complete."
            )

        tools_map = self._get_tools_map()

        def create_parallel_agent(skill_name: str):
            worker = SkillAgent(
                kernel=self.kernel,
                skills_path=self.skills_path,
                user_id=self.user_id
            )
            worker.current_skill = skill_name
            return worker

        engine = ParallelEngine(tools_map, agent_factory=create_parallel_agent, parent_agent=self)

        # Restore completed results so {{step.output}}/auto-context and depends_on all see them.
        for name, res_data in completed_results.items():
            engine.results[name] = StepResult(
                name=name,
                success=res_data["success"],
                output=res_data["output"],
                error=res_data.get("error"),
            )

        if paused_step_dict and paused_child_state:
            step_name = paused_step_dict["name"]
            skill_name = paused_step_dict.get("skill", "unknown")
            emit_status(f"Resuming paused step '{step_name}'...")
            logger.debug("Restoring child agent for parallel step '%s' (skill: %s)", step_name, skill_name)

            child = SkillAgent(
                kernel=self.kernel,
                skills_path=self.skills_path,
                user_id=self.user_id
            )
            child.import_state(paused_child_state)
            self._inherit_workflow_child_context(child)
            child._hitl_decision_injected = True  # Suppress re-trigger

            decision_msg = query  # e.g., "[HUMAN DECISION] approved"
            logger.debug("Injecting decision into child: %s", decision_msg[:80])
            child_result = child.run(decision_msg, skill_name=skill_name)

            engine.results[step_name] = StepResult(
                name=step_name,
                success=True,
                output=str(child_result) if child_result else "",
            )
            logger.info("Paused parallel step '%s' completed after approval", step_name)
        elif paused_step_dict:
            _fresh = dict(paused_step_dict)
            _fresh["task"] = (
                str(_fresh.get("task") or "")
                + f"\n\n{query}\n"
                + "A human reviewed the previous failed attempt(s) and released this step. "
                  "Perform it now and persist its result."
            )
            remaining_step_dicts = [_fresh] + list(remaining_step_dicts)
            logger.info("Resume: no saved child state for paused parallel step '%s' — re-running it fresh",
                        paused_step_dict.get("name"))
            emit_status(f"Re-running '{paused_step_dict.get('name')}' after approval...")

        remaining_steps = [Step.from_dict(s) for s in remaining_step_dicts]
        if remaining_steps:
            emit_status(f"Continuing: {len(remaining_steps)} steps remaining...")
            try:
                try:
                    loop = asyncio.get_running_loop()
                except RuntimeError:
                    loop = None

                if loop and loop.is_running():
                    import concurrent.futures
                    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                        results = pool.submit(
                            asyncio.run,
                            engine.run(remaining_steps, status_callback=emit_status,
                                       preserve_existing_results=True),
                        ).result(timeout=300)
                else:
                    results = asyncio.run(engine.run(remaining_steps, status_callback=emit_status,
                                                      preserve_existing_results=True))
            except ValueError as e:
                return (f"Error: {str(e)}", []) if return_tool_calls else f"Error: {str(e)}"
        else:
            results = engine.results

        # HITL: check if paused again (nested approval)
        if getattr(engine, 'approval_pending', None):
            self.approval_pending = engine.approval_pending

        if getattr(engine, 'paused_for_approval', False):
            paused_step_state = None
            if engine.paused_child_agent:
                paused_step_state = engine.paused_child_agent.export_state()
            self._workflow_checkpoint = {
                "engine_mode": "parallel",
                "skill_name": skill.name,
                "remaining_steps": [self._step_to_dict(s) for s in engine.remaining_steps],
                "completed_results": {name: {"output": r.output, "success": r.success, "error": r.error}
                                      for name, r in engine.results.items()},
                "paused_step": self._step_to_dict(engine.paused_step) if engine.paused_step else None,
                "paused_child_state": paused_step_state,
            }
            logger.info("Parallel execution re-paused: %d steps still remaining", len(engine.remaining_steps))
        else:
            self._workflow_checkpoint = None
            logger.info("Parallel execution fully resumed and completed")

        duration_ms = int((time.time() - start_time) * 1000)
        successful = sum(1 for r in engine.results.values() if r.success)
        lines = ["## Parallel Execution Summary\n"]
        lines.append(f"**Total Steps:** {len(engine.results)}")
        lines.append(f"**Successful:** {successful}")
        lines.append(f"**Failed:** {len(engine.results) - successful}\n")
        for name, result in engine.results.items():
            status = "✅" if result.success else "❌"
            lines.append(f"{status} **{name}** ({result.duration_ms}ms)")
            if result.error:
                lines.append(f"   Error: {result.error}")
        if getattr(engine, 'paused_for_approval', False):
            lines.append(f"\n*Parallel execution re-paused after {duration_ms}ms — awaiting another approval*")
        else:
            lines.append(f"\n*Parallel execution resumed and completed in {duration_ms}ms*")
            lines.append("\n---\n## Step Outputs\n")
            for name, result in engine.results.items():
                if result.success and result.output:
                    lines.append(f"### {name}\n")
                    output = result.output
                    if len(output) > 2000:
                        output = output[:2000] + "\n... (truncated)"
                    lines.append(output)
                    lines.append("")
        response = "\n".join(lines)

        tool_calls_log = []
        _logged_steps = ([paused_step_dict] if paused_step_dict else []) + remaining_step_dicts
        _seen_logged = set()
        for _s in _logged_steps:
            _name = _s.get("name") if isinstance(_s, dict) else None
            if not _name or _name in _seen_logged:
                continue
            _res = engine.results.get(_name)
            if not _res:
                continue
            _seen_logged.add(_name)
            tool_calls_log.append({
                "tool_name": _name,
                "name": _name,
                "action": _s.get("action") or "skill",
                "skill": _s.get("skill") or "",
                "status": "completed" if _res.success else "failed",
                "duration_ms": getattr(_res, "duration_ms", 0) or 0,
                "input": _s.get("task") or _s.get("params") or "",
                "output": _res.output or "",
                "error": _res.error or "",
            })

        self.memory.add_to_short_term(role="user", content=query, skill=skill.name)
        self.memory.add_to_short_term(role="assistant", content=response, skill=skill.name)

        if return_tool_calls:
            return response, tool_calls_log
        return response

    def _run_supervisor(self, skill, query: str, return_tool_calls: bool, emit_status):
        """
        Execute skill using supervisor-worker pattern.
        
        Delegates to child agents for each worker skill.
        """
        import time
        start_time = time.time()
        
        if not skill.worker_skills:
            logger.warning("Supervisor mode but no worker_skills defined for skill: %s", skill.name)
            return (f"Error: Skill '{skill.name}' has execution_mode=supervisor but no worker_skills defined.", []) if return_tool_calls else f"Error: Skill '{skill.name}' has execution_mode=supervisor but no worker_skills defined."
        
        # Factory to create worker agents
        def create_worker(skill_name: str):
            """Create a child SkillAgent for a specific skill."""
            # Workers share the same kernel and memory
            worker = SkillAgent(
                kernel=self.kernel,
                skills_path=self.skills_path,
                user_id=self.user_id
            )
            worker.current_skill = skill_name
            return worker
        
        engine = SupervisorEngine(create_worker)
        
        worker_names = [w.get('name', w) if isinstance(w, dict) else w for w in skill.worker_skills]
        emit_status(f"Delegating to {len(skill.worker_skills)} workers...")
        logger.info("Supervisor delegating to workers: %s", worker_names)
        
        response = engine.run(query, skill.worker_skills, status_callback=emit_status)
        
        # HITL: propagate child worker approval to parent agent
        if getattr(engine, 'approval_pending', None):
            self.approval_pending = engine.approval_pending
        
        duration_ms = int((time.time() - start_time) * 1000)
        response += f"\n\n*Supervisor completed in {duration_ms}ms*"
        
        tool_calls_log = [f"delegate: {name}" for name in worker_names]
        
        self.memory.add_to_short_term(role="user", content=query, skill=skill.name)
        self.memory.add_to_short_term(role="assistant", content=response, skill=skill.name)
        
        if return_tool_calls:
            return response, tool_calls_log
        return response


    def _run_orchestrator(self, skill, query: str, return_tool_calls: bool, emit_status, worker_skills_override=None):
        """
        Execute skill using orchestrator pattern.

        A manager LLM runs a loop: it reads the step log built so far and decides
        which skill to call next, adapting to results, until it has enough to synthesise
        a final answer.

        Subagents are fully isolated:
          - skip_memory=True  — no read/write to shared session memory
          - light_mode=True   — skip heavy context loading
          - _invoke_depth=MAX — invoke_skill tool disabled (no recursion)
        """
        import time as _time
        _start = _time.time()

        # worker_skills_override is passed by auto-mode (dynamic orchestration);
        # skill.worker_skills is used when explicitly configured in SKILL.md.
        _worker_source = worker_skills_override if worker_skills_override is not None else skill.worker_skills

        if not _worker_source:
            msg = (
                f"Error: Skill '{skill.name}' has execution_mode=orchestrator "
                f"but no worker_skills defined."
            )
            logger.warning(msg)
            return (msg, []) if return_tool_calls else msg

        # Build available_skills list for the engine.
        # worker_skills entries may be dicts (with description) or plain strings.
        available_skills = []
        for w in _worker_source:
            if isinstance(w, dict):
                available_skills.append({
                    "name":        w.get("name", ""),
                    "description": w.get("description", ""),
                })
            else:
                available_skills.append({"name": str(w), "description": ""})

        available_skills = [s for s in available_skills if s["name"]]

        if not available_skills:
            msg = f"Error: Skill '{skill.name}' orchestrator has no valid worker skill names."
            return (msg, []) if return_tool_calls else msg

        # Factory: create an isolated child agent for a given skill name
        def create_child(skill_name: str):
            child = SkillAgent(
                kernel=self.kernel,
                skills_path=self.skills_path,
                user_id=self.user_id,
            )
            # Disable invoke_skill in child to prevent recursion
            child._invoke_depth = MAX_INVOKE_DEPTH
            return child

        max_steps = int(getattr(skill, "max_steps", None) or 10)

        engine = OrchestratorEngine(
            manager_llm=self.llm,
            agent_factory=create_child,
            available_skills=available_skills,
            max_steps=max_steps,
            hook_runner=getattr(self, "hook_runner", None),
            status_callback=emit_status,
            session_ctx={
                "user_id":   self.user_id or "",
                "tenant_id": getattr(self.kernel, "tenant_id", ""),
                "agent_id":  getattr(self.kernel, "agent_id", ""),
                "session_id": self.session_id or "",
            },
        )

        worker_names = [s["name"] for s in available_skills]
        emit_status(f"Orchestrating across: {', '.join(worker_names)}")
        logger.info("Orchestrator goal=%s | workers=%s", query[:80], worker_names)

        response = engine.run(query)

        duration_ms = int((_time.time() - _start) * 1000)
        response += f"\n\n*Orchestrator completed in {duration_ms}ms ({len(engine.step_log)} steps)*"

        self.memory.add_to_short_term(role="user",      content=query,    skill=skill.name)
        self.memory.add_to_short_term(role="assistant", content=response, skill=skill.name)

        tool_calls_log = [
            f"orchestrator_step_{s.step_num}: {s.skill_name}"
            for s in engine.step_log
        ]

        if return_tool_calls:
            return response, tool_calls_log
        return response


    def _run_planned(self, query: str, routing_info: dict,
                     return_tool_calls: bool, emit_status):
        """
        Generate and return a DAG execution plan for multi-domain queries.

        Does NOT execute the plan — returns it for user confirmation first.
        Execution happens when the user approves via execute_confirmed_plan().

        Args:
            query: Original user query.
            routing_info: Router result dict (contains detected_domains, skill descriptions).
            return_tool_calls: Whether to return tool call log.
            emit_status: Callback for progress updates.

        Returns:
            Plan display string (or tuple with tool_calls if return_tool_calls=True).
        """
        import time
        start_time = time.time()

        emit_status("Generating execution plan...")
        logger.info("PLANNED: Generating plan for query: %s", query[:100])

        detected_domains = routing_info.get("detected_domains", [])
        available_skills = [s["name"] for s in self.router.list_skills()]

        # Build skill descriptions for better LLM plan quality
        skill_descriptions = {}
        for s in self.router.list_skills():
            skill_descriptions[s["name"]] = s.get("description", "")

        # Use light_llm for fast plan generation (cheaper + faster)
        llm = getattr(self, "light_llm", self.llm)
        engine = PlannerEngine(llm=llm)

        plan = engine.generate_plan(
            query=query,
            detected_domains=detected_domains,
            available_skills=available_skills,
            skill_descriptions=skill_descriptions,
        )

        if "error" in plan:
            err_msg = f"Could not generate a plan: {plan['error']}\n\nFalling back to standard mode."
            logger.error("PLANNED: Plan generation failed: %s", plan["error"])
            if return_tool_calls:
                return err_msg, []
            return err_msg

        # Store plan on agent for later execution upon user confirmation
        self._pending_plan = plan
        display = engine.format_plan_for_display(plan)

        duration_ms = int((time.time() - start_time) * 1000)
        display += f"\n\n*Plan generated in {duration_ms}ms*"

        logger.info("PLANNED: Plan generated with %d steps in %dms",
                     len(plan["steps"]), duration_ms)

        if return_tool_calls:
            return display, [f"plan: {len(plan['steps'])} steps"]
        return display

    def _make_child_agent(self, skill_name: str = None) -> "SkillAgent":
        """Create a fresh isolated child agent for a single planner step.

        Each child gets its own AgentMemory instance (new SQLite connections),
        so it cannot race with this agent's background logging thread.
        The kernel, skills_path, and LLM config are reused — only stateful
        memory objects are fresh.
        """
        child = SkillAgent(
            kernel=self.kernel,
            skills_path=self.skills_path,
            user_id=self.user_id,
            trace_emitter=self.trace_emitter,
        )
        child.auto_run = self.auto_run
        child.session_id = self.session_id       # same session for conversation continuity
        child._invoke_depth = getattr(self, '_invoke_depth', 0) + 1  # treat as child invocation
        return child

    def execute_confirmed_plan(self, status_callback=None):
        """
        Execute a previously generated plan that the user has confirmed.

        Call this after the user approves the plan returned by _run_planned().

        Returns:
            Combined results string.
        """
        plan = getattr(self, '_pending_plan', None)
        if not plan:
            return "No pending plan to execute."

        plan["confirmed"] = True
        llm = getattr(self, "light_llm", self.llm)
        engine = PlannerEngine(llm=llm)

        result = engine.execute_plan(
            plan, self,
            agent_factory=self._make_child_agent,
            status_callback=status_callback,
        )
        self._pending_plan = None

        if "error" in result:
            return f"Plan execution failed: {result['error']}"

        return result.get("combined_result", "Plan completed with no output.")

    def _run_graph(self, skill, query: str, return_tool_calls: bool, emit_status):
        """execution_mode 'graph' — run a STORED, authored process-graph.

        Loads the graph referenced by `skill.graph_ref` (resolved relative to the skill folder),
        validates it, compiles it, and executes it via the existing PlannerEngine (nodes = child
        skills, each in its own execution mode). If the graph declares a `converge` block the compiler
        attaches `plan["graph_meta"]` and we use the convergence executor (`execute_graph`: iterate the
        scope until the verifier passes, carry feedback, bound, then downstream or on_exhausted). No
        `converge` → the one-shot `execute_plan` (P1). Any exception here is caught by the dispatch
        caller, which falls back to ReAct.
        """
        from pathlib import Path
        from .process_graph import load_graph, compile_to_plan
        gref = (getattr(skill, "graph_ref", "") or "").strip()
        if not gref:
            raise ValueError("execution_mode 'graph' requires 'graph_ref' in the skill front-matter")
        gpath = _resolve_graph_ref(getattr(skill, "path", ".") or ".", gref)
        if callable(emit_status):
            try:
                emit_status(f"Loading process graph: {gpath.name}…")
            except Exception:
                pass

        g = load_graph(str(gpath))
        _overrides = {}
        _item = str(getattr(self, "_mission_item_id", "") or "").strip()
        if not _item and query:
            import re as _re
            _m = _re.search(r"[A-Z]{2,4}-\d{4}-\d+|INV-\d+|CL-\d+", query)
            if _m:
                _item = _m.group(0)
        if _item:
            _overrides["case_id"] = _item   # back-compat for finance graphs
            # Generic: also bind the item id to the graph's FIRST declared input, so
            # non-finance graphs (e.g. event_id for physical-AI) get it without hardcoding.
            try:
                _decl = [i.get("name") for i in (g.get("inputs") or []) if i.get("name")]
                if _decl:
                    _overrides.setdefault(_decl[0], _item)
            except Exception:
                pass
        plan = compile_to_plan(g, input_overrides=_overrides or None)
        if _overrides:
            logger.info("GRAPH: bound item id=%s to inputs %s", _item, list(_overrides))
        plan["confirmed"] = True   # authored graph = pre-approved structure; nodes still HITL-gated per skill
        plan["query"] = query
        graph_meta = plan.get("graph_meta")
        logger.info("GRAPH: '%s' compiled to %d node(s)%s: %s",
                    g.get("name"), len(plan["steps"]),
                    " [converge]" if graph_meta else "",
                    [f"{s['id']}[{s['skill']}]" for s in plan["steps"]])

        llm = getattr(self, "light_llm", self.llm)
        engine = PlannerEngine(llm=llm)
        if graph_meta:
            result = engine.execute_graph(
                plan, graph_meta, self,
                agent_factory=self._make_child_agent,
                status_callback=emit_status,
            )
        else:
            result = engine.execute_plan(
                plan, self,
                agent_factory=self._make_child_agent,
                status_callback=emit_status,
            )

        if "error" in result:
            response = f"Process graph '{g.get('name')}' failed: {result['error']}"
            return (response, []) if return_tool_calls else response

        # on_exhausted=escalate_to_human → raise a real HITL card on THIS (top-level) agent, so
        # checkpoint_hitl_if_needed persists it after the turn (same seam as request_human_approval).
        if result.get("escalate"):
            self._raise_graph_escalation(skill, g, result)

        response = result.get("combined_result", "Process graph completed with no output.")
        if result.get("escalate"):
            response = (f"⚠️ **Human review required** — {result.get('reason', 'verifier did not pass')}.\n\n"
                        f"Latest verifier feedback:\n> {(result.get('feedback') or '')[:600]}\n\n"
                        f"An approval has been raised for a reviewer to decide.\n\n---\n{response}")
        return (response, []) if return_tool_calls else response

    def _raise_graph_escalation(self, skill, g, result) -> None:
        """Set approval_pending on this top-level agent so the post-turn checkpoint creates a
        Command Center card (the on_exhausted=escalate_to_human path). Best-effort; never raises."""
        try:
            import uuid as _uuid
            skill_name = getattr(skill, "name", "") or getattr(self, "current_skill", "") or "process_graph"
            ctx = {
                "resume_kind": "process_graph_escalation",
                "graph": g.get("name", skill_name),
                "iterations": result.get("iterations"),
                "verifier_feedback": (result.get("feedback") or "")[:1200],
                "goal": (g.get("goal") or "")[:600],
            }
            # Carry mission attribution if this graph is running inside a workstream item.
            for _a in ("_mission_workstream", "_mission_item_id"):
                _v = getattr(self, _a, None)
                if _v:
                    ctx["workstream_name" if _a == "_mission_workstream" else "mission_item_id"] = _v
            self.approval_pending = {
                "approval_id": f"graph-{_uuid.uuid4().hex[:12]}",
                "reason": result.get("reason", "Process-graph verifier did not pass; human review required."),
                "context": ctx,
                "options": ["Approve", "Reject"],
                "urgency": "high",
                "sla_minutes": 120,
                "skill": skill_name,
                "rule_matched": "process_graph.converge.on_exhausted",
                "rule_type": "agent_initiated",
                "timestamp": datetime.now().isoformat(),
            }
            logger.info("GRAPH: escalation approval raised (%s) after %s iteration(s)",
                        self.approval_pending["approval_id"], result.get("iterations"))
        except Exception as _esc_err:
            logger.warning("GRAPH: failed to raise escalation approval (non-fatal): %s", _esc_err)

    def _apply_profile(self, skill, routing_info, request_profile: str = None):
        """Resolve the harness profile for this run and apply its dimensions to the agent.

        Config-baseline knobs (``sufficiency.*``) are reset to their __init__ values then re-applied,
        so a profile never leaks between runs. Request-scoped knobs (auto_run, critique, light_mode,
        knowledge mode, recursion budget) are captured into ``self._profile_restore`` and reverted at
        the end of ``_run_impl``. The default profile ``standard`` applies nothing (parity anchor).
        """
        try:
            from agentos_contracts.profile import resolve_profile
            from .harness_profiles import load_profile_registry
        except Exception:
            self._profile_selection = None
            return

        # Snapshot the config-baseline sufficiency knobs once (undo point for those dims).
        if not hasattr(self, "_suf_baseline"):
            self._suf_baseline = {
                "sufficiency_enabled": self.sufficiency_enabled,
                "sufficiency_auto_complexity": self.sufficiency_auto_complexity,
                "sufficiency_max_iterations": self.sufficiency_max_iterations,
                "sufficiency_threshold": self.sufficiency_threshold,
            }
        # Reset config-baseline dims so the previous run's profile never lingers.
        for attr, val in self._suf_baseline.items():
            setattr(self, attr, val)

        agent_root = getattr(getattr(self, "kernel", None), "agent_root", None)
        registry = load_profile_registry(agent_root)
        routing = dict(routing_info or {})
        if request_profile:
            routing["profile"] = request_profile
        sel = resolve_profile(
            skill=skill,
            config=self.config if isinstance(self.config, dict) else {},
            env=os.environ,
            routing_info=routing,
            registry=registry,
        )
        self._profile_selection = sel
        if sel.fallback_reason:
            logger.warning("Profile selection: %s", sel.fallback_reason)

        # Fresh restore map for request-scoped knobs.
        self._profile_restore = {}

        def _cap(attr, default=None):
            if attr not in self._profile_restore:
                self._profile_restore[attr] = getattr(self, attr, default)

        dims = sel.dimensions or {}
        if not dims:
            logger.info("Harness profile: %s (source=%s) — no overrides", sel.name, sel.source)
            return

        # verification → sufficiency loop + critique (baseline already reset above)
        ver = dims.get("verification") or {}
        if "enabled" in ver:
            self.sufficiency_enabled = bool(ver["enabled"])
        if "auto_complexity" in ver:
            self.sufficiency_auto_complexity = bool(ver["auto_complexity"])
        if "max_iter" in ver:
            self.sufficiency_max_iterations = int(ver["max_iter"])
        if "threshold" in ver:
            self.sufficiency_threshold = float(ver["threshold"])
        if "critique_mode" in ver:
            _cap("enable_critique", False)
            _cap("critique_mode", "off")
            self.critique_mode = ver["critique_mode"]
            self.enable_critique = ver["critique_mode"] != "off"
        if "consistency" in ver:
            _cap("consistency_check", False)
            self.consistency_check = bool(ver["consistency"])
        if ver.get("verifier_model"):
            _cap("_verifier_model", "light")
            self._verifier_model = ver["verifier_model"]  # "light" | "primary"

        # autonomy → auto_run (ratchet already clamped a locked floor to False in resolve_profile)
        autonomy = dims.get("autonomy") or {}
        if "auto_run" in autonomy:
            _cap("auto_run", False)
            self.auto_run = bool(autonomy["auto_run"])
            if self.auto_run:
                logger.info("Harness profile '%s' enables auto_run (dangerous-op HITL gate still applies)", sel.name)

        # memory → light_mode (OR-in; re-set from the param each run so no leak)
        mem = dims.get("memory") or {}
        if mem.get("light_mode"):
            self.light_mode = True

        # knowledge retrieval (only if no explicit per-request knowledge_mode override was set)
        kr = dims.get("knowledge_retrieval")
        if kr and getattr(self, "_prev_kr_mode", None) is None and kr in ("scan", "semantic", "hybrid"):
            _cap("knowledge_retrieval_mode", self.knowledge_retrieval_mode)
            self.knowledge_retrieval_mode = kr

        # budget.max_tool_calls → LangGraph recursion budget (each tool call ≈ 2-3 graph steps)
        budget = dims.get("budget") or {}
        if budget.get("max_tool_calls"):
            _cap("agent_config", dict(self.agent_config))
            self.agent_config = {**self.agent_config,
                                 "recursion_limit": max(int(self.agent_config.get("recursion_limit", 200)),
                                                        int(budget["max_tool_calls"]) * 3)}

        logger.info("Harness profile applied: %s (source=%s) dims=%s",
                    sel.name, sel.source, sorted(dims.keys()))

    def _restore_profile_overrides(self):
        """Revert request-scoped knobs captured by _apply_profile (end of _run_impl)."""
        restore = getattr(self, "_profile_restore", None)
        if not restore:
            return
        for attr, val in restore.items():
            try:
                setattr(self, attr, val)
            except Exception:
                pass
        self._profile_restore = {}

    def run(self, query: str, skill_name: str = None, routing_info: dict = None, return_tool_calls: bool = False, status_callback=None, skip_memory: bool = False, render_ui: bool = False, light_mode: bool = False, knowledge_mode: str = None, token_callback=None, profile: str = None, cancel_check=None):
        """Public entry — wraps _run_impl in a self-auth context so the
        agent can authenticate its own HTTP calls (e.g. curl from the
        shell tool to /api/workstreams) using a short-lived JWT minted
        from the agent's entitlement principal.

        The self-auth token lives in the IAF_AGENT_SELF_AUTH_TOKEN env
        var for the duration of this run; cleared automatically on exit.

        cancel_check: optional zero-arg predicate polled at loop/tool
        boundaries so a UI "Stop" cooperatively halts this run (the run
        executes on a worker thread that cannot be force-killed). When it
        returns True the run aborts with a RunCancelled that is turned into
        a clean "stopped" response here.
        """
        try:
            from agent_os.self_auth import with_self_auth
        except Exception:  # agent_os.self_auth optional — keep run() working
            with_self_auth = None

        principal = getattr(self, "entitlement_principal", None)

        from iaf_agent_skills import cancellation as _cancel
        _cancel_prev = _cancel.get_current()
        _cancel.bind_current(cancel_check)
        logger.debug("agent.run: cancel_check bound=%s (inherited=%s)",
                     cancel_check is not None, cancel_check is None and _cancel_prev is not None)
        try:
            if with_self_auth is None or principal is None:
                _result = self._run_impl(
                    query, skill_name=skill_name, routing_info=routing_info,
                    return_tool_calls=return_tool_calls, status_callback=status_callback,
                    skip_memory=skip_memory, render_ui=render_ui, light_mode=light_mode,
                    knowledge_mode=knowledge_mode, token_callback=token_callback, profile=profile,
                )
            else:
                with with_self_auth(principal):
                    _result = self._run_impl(
                        query, skill_name=skill_name, routing_info=routing_info,
                        return_tool_calls=return_tool_calls, status_callback=status_callback,
                        skip_memory=skip_memory, render_ui=render_ui, light_mode=light_mode,
                        knowledge_mode=knowledge_mode, token_callback=token_callback, profile=profile,
                    )
            self._rlm_shadow_maybe(query, _result)
            return _result
        except _cancel.RunCancelled:
            logger.info("Agent run cancelled by user (cooperative stop)")
            self._finalize_cancelled_trace()
            _stopped = "⛔ Execution stopped by user."
            return (_stopped, []) if return_tool_calls else _stopped
        finally:
            _cancel.restore_current(_cancel_prev)

    def _finalize_cancelled_trace(self) -> None:
        """Close the in-flight trace with a terminal ``cancelled`` status when a
        run is cooperatively stopped by the user.

        The trace is begun in :meth:`_run_impl` (status ``running``, skill not yet
        known). A cooperative Stop raises :class:`RunCancelled` — a BaseException
        that propagates straight to :meth:`run` without hitting any of the normal
        ``end_trace`` paths, so the row would otherwise stay ``running`` with a
        blank skill. This records the routed skill and the token/cost totals
        accumulated before the stop. Best-effort: never let telemetry mask the
        stop itself.
        """
        _te = getattr(self, "trace_emitter", None)
        _tid = getattr(self, "_active_trace_id", "") or ""
        if not (_te and _tid):
            return
        try:
            _budget = llm_tracker.end_budget()
            _summary = (_budget or {}).get("summary", {}) if isinstance(_budget, dict) else {}
            _start = getattr(self, "_active_trace_start_ms", 0) or 0
            _routed_skill = getattr(getattr(self, "kernel", None), "current_skill", None) \
                or self.current_skill or ""
            _te.end_trace(
                trace_id=_tid,
                status="cancelled",
                skill=_routed_skill,
                total_ms=(time.time() * 1000 - _start) if _start else 0,
                prompt_tokens=int(_summary.get("total_prompt_tokens", 0) or 0),
                completion_tokens=int(_summary.get("total_completion_tokens", 0) or 0),
                cost_usd=float(_summary.get("total_cost_usd", 0.0) or 0.0),
                metadata={"cancelled_by": "user"},
            )
        except Exception:  # pragma: no cover - finalization must not mask the stop
            logger.debug("cancelled-trace finalize skipped (non-fatal)", exc_info=True)
        finally:
            # Prevent a later stray finalize from re-closing the same trace.
            self._active_trace_id = ""

    def _run_impl(self, query: str, skill_name: str = None, routing_info: dict = None, return_tool_calls: bool = False, status_callback=None, skip_memory: bool = False, render_ui: bool = False, light_mode: bool = False, knowledge_mode: str = None, token_callback=None, profile: str = None):
        """
        Run agent with a query.

        Args:
            query: User's input
            skill_name: Force a specific skill (optional, auto-routes if None)
            return_tool_calls: If True, returns (response, tool_calls_list) tuple
            status_callback: Optional callable(str) for progress updates
            skip_memory: If True, skip all memory operations (faster for batch)
            render_ui: If True, include UI generation instructions (for browser requests)
            light_mode: If True, skip memory context + async learning (faster responses)
            knowledge_mode: Override knowledge retrieval mode for this request.
                           "scan" | "semantic" | "hybrid" | None (use instance default)

        Returns:
            Agent's response string, or (response, tool_calls) if return_tool_calls=True
        """
        # Store flags for _load_prompt to access
        self.render_ui = render_ui
        self.light_mode = light_mode
        
        # Track in-flight query so loadConversation can show it
        # while we're still processing (cleared after _log_conversation)
        self._inflight_query = query
        
        try:
            if not skip_memory and hasattr(self, 'memory') and self.memory:
                self.memory.conversation_manager.upsert_session(
                    session_id=self.session_id,
                    tenant_id=getattr(self.memory, 'tenant_id', ''),
                    agent_id=getattr(self.memory, 'agent_id', ''),
                    user_id=self.user_id or '',
                    title=query[:80] if query else '',
                    first_message=query or '',
                    skill=self.current_skill or '',
                    parent_session_id=getattr(self, 'parent_session_id', None),
                )
        except Exception:
            pass  # Non-fatal — log_episode() will index later anyway
        
        # Per-request knowledge mode override (restores after run)
        if knowledge_mode and knowledge_mode in ("scan", "semantic", "hybrid"):
            self._prev_kr_mode = self.knowledge_retrieval_mode
            self.knowledge_retrieval_mode = knowledge_mode
        else:
            self._prev_kr_mode = None
        
        if light_mode:
            logger.info("FRESH MODE: Skipping plan_cache, episode log, memory context + async learning")
        tracker = ProgressTracker(callback=status_callback, phase_total=len(ProgressPhase))
        # Store on instance so tools (create_plan, invoke_plan) can emit sub-steps
        # into the reasoning stepper without needing a separate callback arg.
        self._progress_tracker = tracker

        # Fresh evidence collector for this request — captures file reads at
        # the tool boundary before any truncation happens downstream.
        from .evidence_collector_adapter import EvidenceCollectorAdapter
        self._evidence_collector = EvidenceCollectorAdapter().new_collector()
        self._evidence_bundle = {}
        # Backward-compat alias: workflow/parallel/supervisor still call emit_status(str)
        def emit_status(msg: str):
            tracker.emit_status(msg)

        _te = self.trace_emitter  # Local ref for speed
        _trace_id = None
        self._active_trace_id = ""
        _span_count = 0
        _prompt_tokens = 0      # accumulated across all LLM calls in this trace
        _completion_tokens = 0  # accumulated across all LLM calls in this trace
        _trace_start_ms = time.time() * 1000 if _te else 0
        _telemetry_entrypoint = (
            self.__dict__.pop("_telemetry_entrypoint", None)
            or ("subagent" if getattr(self, "_invoke_depth", 0) > 0 else None)
            or getattr(self, "_evidence_execution_source", None)
            or getattr(self, "_entrypoint", None)
            or "chat"
        )
        if _te:
            try:
                _trace_id = _te.begin_trace(
                    session_id=self.session_id,
                    tenant=getattr(self.kernel, 'tenant_id', 'default'),
                    agent=getattr(self.kernel, 'agent_id', 'default'),
                    user_id=self.user_id or '',
                    query=query,
                    metadata={"entrypoint": _telemetry_entrypoint},
                )
                self._active_trace_id = _trace_id or ""
                # Remember the start so a cooperative cancel can finalize the trace
                # with a real duration (RunCancelled skips the normal end_trace path).
                self._active_trace_start_ms = _trace_start_ms
                # Start per-request LLM budget after begin_trace so budget metadata
                # carries the same trace_id shown in Dashboard V2.
                llm_tracker.start_budget(_trace_id or "")
            except Exception:
                _te = None  # Disable tracing for this request if begin fails

        def _trace_response_text(result_payload) -> str:
            if isinstance(result_payload, tuple):
                return str(result_payload[0] or "")
            return str(result_payload or "")

        def _trace_status_for(result_payload) -> str:
            if getattr(self, "approval_pending", None):
                return "awaiting_human"
            text = _trace_response_text(result_payload).strip().lower()
            if text.startswith("error:") or text.startswith("❌"):
                return "error"
            return "success"

        def _replay_preroute_budget() -> None:
            router_llm = (routing_info or {}).get("_router_llm") if isinstance(routing_info, dict) else None
            if not router_llm or router_llm.get("recorded_in_budget"):
                return
            try:
                llm_tracker.record_usage(
                    "router",
                    model=str(router_llm.get("model") or ""),
                    prompt_tokens=int(router_llm.get("prompt_tokens") or 0),
                    completion_tokens=int(router_llm.get("completion_tokens") or 0),
                    duration_ms=float(router_llm.get("duration_ms") or 0.0),
                )
                router_llm["recorded_in_budget"] = True
            except Exception:  # pragma: no cover - telemetry must not break routing
                pass

        def _close_trace_for_early_return(
            mode_name: str,
            result_payload,
            mode_start_ms: float,
            *,
            final_skill: str | None = None,
            metadata: dict | None = None,
        ) -> None:
            nonlocal _span_count
            if not (_te and _trace_id):
                return
            try:
                response_text = _trace_response_text(result_payload)
                status = _trace_status_for(result_payload)
                span_status = "error" if status == "error" else status if status == "awaiting_human" else "ok"
                _te.add_span(
                    trace_id=_trace_id,
                    span_type=mode_name,
                    name=f"{mode_name}_execution",
                    start_ms=mode_start_ms or _trace_start_ms,
                    duration_ms=(time.time() * 1000 - (mode_start_ms or _trace_start_ms)),
                    status=span_status,
                    input_preview=query[:500],
                    output_preview=response_text[:4096],
                    metadata={
                        "skill": final_skill or skill_name,
                        "execution_mode": mode_name,
                        **(metadata or {}),
                    },
                )
                _span_count += 1
                _te.add_span(
                    trace_id=_trace_id,
                    span_type="response",
                    name="full_request",
                    start_ms=_trace_start_ms,
                    duration_ms=(time.time() * 1000 - _trace_start_ms),
                    status=span_status,
                    input_preview=query[:500],
                    output_preview=response_text[:4096],
                    metadata={"skill": final_skill or skill_name, "execution_mode": mode_name},
                )
                _span_count += 1
                _model_name = getattr(self.llm, 'azure_deployment', getattr(self.llm, 'model_name', ''))
                _llm_budget = llm_tracker.end_budget()
                _summary = (_llm_budget or {}).get("summary", {}) if isinstance(_llm_budget, dict) else {}
                _te.end_trace(
                    trace_id=_trace_id,
                    status=status,
                    skill=final_skill or skill_name,
                    span_count=_span_count,
                    total_ms=(time.time() * 1000 - _trace_start_ms),
                    prompt_tokens=int(_summary.get("total_prompt_tokens", 0) or _prompt_tokens),
                    completion_tokens=int(_summary.get("total_completion_tokens", 0) or _completion_tokens),
                    cost_usd=float(_summary.get("total_cost_usd", 0.0) or calculate_cost(_model_name, _prompt_tokens, _completion_tokens)),
                    metadata={"llm_budget": _llm_budget, **(metadata or {})} if _llm_budget else metadata,
                )
            except Exception:  # pragma: no cover - tracing must not break agent responses
                pass

        _replay_preroute_budget()

        try:
            _bt_ctx = {
                **self._build_session_ctx(),
                "query": query,
                "execution_mode": "react",
                "entrypoint": getattr(self, "_entrypoint", "chat"),
                "queue_item_id": getattr(self, "_queue_item_id", "") or "",
                "exec_id": getattr(self, "_queue_exec_id", "") or "",
                "workstream_name": getattr(self, "_mission_workstream", "") or "",
                "mission_item_id": getattr(self, "_mission_item_id", "") or "",
            }
            _bt_gate = self.hook_runner.run_before_turn(_bt_ctx)
            if _bt_gate is not None and _bt_gate.blocked:
                logger.info("HookRunner [BeforeTurn]: turn skipped — %s", _bt_gate.reason[:120])
                # Clear in-flight marker so the UI does not hang on a phantom turn
                self._inflight_query = None
                if wants_hitl(_bt_gate) and not self.approval_pending:
                    _bt_approval = set_hook_approval(
                        self,
                        _bt_gate,
                        session_ctx=_bt_ctx,
                        skill_name=skill_name,
                        query=query,
                    )
                    blocked_response = f"Human approval required: {_bt_approval.get('reason')}"
                else:
                    blocked_response = f"⚠️ Turn blocked by policy hook: {_bt_gate.reason}"
                # Emit OnTurnEnd so observers see a consistent lifecycle
                try:
                    self.hook_runner.run_on_turn_end(
                        {**self._build_session_ctx(), "query": query, "execution_mode": "react"},
                        response=blocked_response,
                        error_msg="blocked_by_hook",
                    )
                except Exception:  # pragma: no cover - observe-only
                    pass
                # Close the trace cleanly so audit isn't left dangling
                if _te and _trace_id:
                    try:
                        _te.end_trace(
                            trace_id=_trace_id, status="blocked", skill=skill_name,
                            span_count=_span_count, total_ms=(time.time()*1000 - _trace_start_ms),
                            metadata={"blocked_by": "BeforeTurn", "reason": _bt_gate.reason[:200]},
                        )
                    except Exception:  # pragma: no cover - defensive
                        pass
                if return_tool_calls:
                    return blocked_response, []
                return blocked_response
        except Exception as _bt_err:  # pragma: no cover - hooks must never break run()
            logger.debug("HookRunner [BeforeTurn] error (non-fatal): %s", _bt_err)
        
        if self.pending_action:
            pending_time = self.pending_action.get("timestamp")
            if pending_time:
                elapsed_minutes = (datetime.now() - pending_time).total_seconds() / 60
                if elapsed_minutes > self.PENDING_ACTION_TIMEOUT_MINUTES:
                    logger.warning("Pending action expired (%.1f min > %d min), clearing", elapsed_minutes, self.PENDING_ACTION_TIMEOUT_MINUTES)
                    self._clear_pending_state()
        
        if getattr(self, '_hitl_decision_injected', False) and getattr(self, '_workflow_checkpoint', None):
            checkpoint = self._workflow_checkpoint
            wf_skill_name = checkpoint["skill_name"]
            skill = self.loader.load(wf_skill_name)
            self.current_skill = wf_skill_name
            engine_mode = checkpoint.get("engine_mode", "workflow")
            logger.info("HITL Resume: Continuing %s '%s' from checkpoint", engine_mode, wf_skill_name)
            _resume_start = time.time() * 1000 if _te else 0
            if engine_mode == "parallel":
                _resume_response = self._resume_parallel(skill, query, return_tool_calls, emit_status)
            else:
                _resume_response = self._resume_workflow(skill, query, return_tool_calls, emit_status)
            _close_trace_for_early_return(
                f"{engine_mode}_resume",
                _resume_response,
                _resume_start,
                final_skill=wf_skill_name,
                metadata={"execution_mode": engine_mode, "resume": True},
            )
            return _resume_response
        
        # Route to skill (with context for smart continuation detection)
        _route_start = time.time() * 1000 if _te else 0
        # Preserve caller-supplied routing_info (contains execution_mode, detected_domains).
        # Only initialise to empty dict if caller didn't pass one.
        if routing_info is None:
            routing_info = {}
        
        entity_hint = None
        entity_confidence = 0.0
        process_hint = None
        process_matches = None
        signals_agree = None
        self._cached_query_embedding = None
        self._entity_context = None
        self._file_context_block = None

        try:
            indexer = getattr(self.memory, 'knowledge_indexer', None)
            if indexer and query:
                q_emb = indexer._safe_get_embedding(query)
                if q_emb:
                    self._cached_query_embedding = q_emb
        except Exception as emb_err:
            logger.warning("Embedding compute failed (non-fatal): %s", emb_err)

        _taxonomy_hit = None
        _taxonomy_hits = []   # multi-hit list for multi-domain detection
        try:
            _tax_idx = getattr(self, '_taxonomy_index', None)
            if _tax_idx and self._cached_query_embedding:
                _taxonomy_hits = self._find_taxonomy_hits_via_boundary(self._cached_query_embedding, query)
                if _taxonomy_hits:
                    _taxonomy_hit = _taxonomy_hits[0]  # best hit for backward-compat
        except Exception as _te:
            logger.debug("TaxonomySignalIndex lookup failed (non-fatal): %s", _te)

        _ctx_mode = getattr(self, 'context_loading_mode', 'table')
        try:
            if _ctx_mode == 'file':
                from .md_entity_resolver import MdEntityResolver
                _ctx_file = getattr(self, '_context_file_path', None)
                if _ctx_file:
                    if not self._entitlement_allowed("read", "context", str(_ctx_file), {"skill": skill_name}):
                        raise PermissionError(f"Access denied: context '{_ctx_file}' is not permitted for this user")
                    _exec_hints = None
                    if getattr(self, '_plan_cache_hit', None):
                        import json as _hints_json
                        _raw_hints = self._plan_cache_hit.get("context_hints") or "[]"
                        try:
                            _exec_hints = _hints_json.loads(_raw_hints) or None
                        except Exception:
                            _exec_hints = None
                    # Derive entities dir from config (zero hardcoding — reads entity_validation.yaml)
                    _entities_dir = MdEntityResolver.get_entities_dir(_ctx_file)
                    _entity_name_hint = (routing_info or {}).get("entity_name")
                    self._file_context_block = MdEntityResolver.make_file_context_block(
                        _ctx_file,
                        execution_hints=_exec_hints,
                        entity_name=_entity_name_hint,
                        entities_dir=_entities_dir,
                    )
                    if _taxonomy_hit and _taxonomy_hit.get("context_files"):
                        _tax_ref_files = [
                            _trf for _trf in _taxonomy_hit["context_files"]
                            if self._entitlement_allowed("read", "context", str(_trf), {"skill": skill_name})
                        ]
                        if _tax_ref_files:
                            _tax_block = "\n\n## Taxonomy Reference Files\n"
                            _tax_block += "The taxonomy index identified these files as directly relevant to this query:\n"
                            for _trf in _tax_ref_files:
                                _tax_block += f"- `{_trf}`\n"
                            _tax_block += "Read these files (using shell) after the master context file.\n"
                            self._file_context_block += _tax_block
                            logger.info("FileMode: injected %d taxonomy ref files into context block", len(_tax_ref_files))
                        else:
                            logger.info("FileMode: taxonomy reference files were denied by entitlements")
                # Pull entity_name / entity_type the router LLM already extracted
                entity_hint = (routing_info or {}).get("entity_name")
                entity_confidence = 1.0 if entity_hint else 0.0
                _entity_type = (routing_info or {}).get("entity_type")
                logger.info(
                    "FileMode: entity=%s (%s) context_file=%s",
                    entity_hint, _entity_type, _ctx_file)
            elif _ctx_mode == 'rlm':
                from .rlm.context_store import get_context_store
                _ctx_file = getattr(self, '_context_file_path', None)
                _rlm_text = ""
                if _ctx_file:
                    if not self._entitlement_allowed("read", "context", str(_ctx_file), {"skill": skill_name}):
                        raise PermissionError(f"Access denied: context '{_ctx_file}' is not permitted for this user")
                    try:
                        _rlm_text = self._resolve_context_file(_ctx_file).read_text(encoding="utf-8", errors="ignore")
                    except Exception as _rlm_e:
                        logger.warning("RLM mode: could not read context file %s: %s", _ctx_file, _rlm_e)
                _ctx_scope = f"{getattr(self.kernel, 'tenant_id', '') or ''}:{getattr(self.kernel, 'agent_id', '') or ''}:{self.user_id or ''}"
                get_context_store().offload(self.session_id, _rlm_text, scope=_ctx_scope)
                self._file_context_block = (
                    "## Context (RLM handle — not inlined)\n"
                    f"The full context ({len(_rlm_text)} chars) is held outside this window. "
                    "To consult it, call the `context_query` tool with ONE well-scoped natural-language "
                    "question; it reads and aggregates only the relevant parts and returns the answer. "
                    "Call it again for follow-up questions rather than requesting the whole document.\n"
                )
                entity_hint = (routing_info or {}).get("entity_name")
                entity_confidence = 1.0 if entity_hint else 0.0
                _entity_type = (routing_info or {}).get("entity_type")
                logger.info("RLM mode: offloaded %d chars (session=%s) context_file=%s",
                            len(_rlm_text), self.session_id, _ctx_file)
            else:
                # TABLE MODE (default): SQLite entity_registry via FTS5 + cosine
                _indexer = getattr(self.memory, 'knowledge_indexer', None)
                entity_store = getattr(_indexer, 'entity_registry', None) if _indexer else None
                if entity_store and query:
                    # Always call collect_context — FTS5 works even without embedding.
                    # Pass cached embedding if available for cosine fallback.
                    ctx = entity_store.collect_context(
                        query_embedding=self._cached_query_embedding,
                        query_text=query
                    )
                    if ctx:
                        self._entity_context = ctx
                        entity_hint = ctx.get("skill_hint")
                        entity_confidence = ctx.get("skill_confidence", 0.0)
                        process_hint = ctx.get("process_hint")
                        process_matches = ctx.get("process_matches")
                        signals_agree = ctx.get("signals_agree")
                        logger.info(
                            "Ontology: entity_hint=%s (%.2f) process_hint=%s agree=%s entities=%s",
                            entity_hint, entity_confidence, process_hint, signals_agree,
                            [e.get("display_name") for e in ctx.get("resolved_entities", [])])
        except Exception as ent_err:
            logger.warning("Entity resolution failed (non-fatal): %s", ent_err)

        if _taxonomy_hit and not process_hint:
            process_hint = _taxonomy_hit["skill"]
            # Build process_matches from ALL taxonomy hits (deduped by skill).
            # Each entry becomes a detected domain in router._detected set.
            process_matches = []
            for _th in (_taxonomy_hits or [_taxonomy_hit]):
                process_matches.append({
                    "matched_alias": _th["embed_text"][:80],
                    "display_name":  (
                        _th["embed_text"].split(" > ")[2]
                        if _th["embed_text"].count(" > ") >= 2
                        else _th["embed_text"][:40]
                    ),
                    "node_type":  "activity",
                    "skill_name": _th["skill"],
                    "score":      _th["score"],
                    "context_files": _th.get("context_files", []),
                })
            _skill_list = [m["skill_name"] for m in process_matches]
            logger.info(
                "TaxonomySignalIndex: injected %d process_matches — skills=%s (best=%.3f via %s)",
                len(process_matches), _skill_list,
                _taxonomy_hit["score"], _taxonomy_hit["method"]
            )

        logger.info(
            "TaxonomySignal: execution_mode=%s from router (skill=%s detected_domains=%s)",
            (routing_info or {}).get("execution_mode", "react"),
            (routing_info or {}).get("skill", "?"),
            (routing_info or {}).get("detected_domains", []),
        )

        if self.context_loading_mode == "file":
            try:
                _fm_indexer = getattr(self.memory, 'knowledge_indexer', None)
                _fm_ereg = getattr(_fm_indexer, 'entity_registry', None) if _fm_indexer else None
                if _fm_ereg:
                    _search_text = entity_hint or query
                    _fm_matches = _fm_ereg.resolve_entities(
                        query_text=_search_text,
                        query_embedding=self._cached_query_embedding,
                        top_k=1,
                    )
                    if _fm_matches:
                        _resolved_nid = _fm_matches[0]["node_id"]
                        _fm_method = _fm_matches[0].get("match_method", "?")
                        _fm_score = _fm_matches[0].get("score", 1.0)
                        _accept = True
                        if _fm_method != "alias":
                            _q_toks = {t.lower() for t in re.findall(r'\w+', _search_text or '') if len(t) >= 3}
                            _n_toks = {t.lower() for t in re.findall(r'\w+', _resolved_nid or '') if len(t) >= 3}
                            _n_toks -= {"entity", "customer", "node", "id"}
                            if _q_toks and _n_toks and not (_q_toks & _n_toks):
                                _accept = False
                                logger.info(
                                    "FileMode entity REJECTED: %r ↛ %r (no token overlap; method=%s score=%.2f)",
                                    _search_text[:60], _resolved_nid, _fm_method, _fm_score,
                                )
                        if _accept:
                            logger.info(
                                "FileMode entity resolved: %r → %r (method=%s score=%.2f)",
                                _search_text[:60], _resolved_nid, _fm_method, _fm_score,
                            )
                            entity_hint = _resolved_nid
                            entity_confidence = _fm_score
            except Exception as _fe:
                logger.debug("FileMode entity registry resolve failed (non-fatal): %s", _fe)

        # Store per-query entity hint so query_memory tool can access it
        self._last_entity_hint = entity_hint or None

        _similar_patterns = []  # Cache for Stage 2 (context assembly)
        _routing_hint = None
        
        if not light_mode and hasattr(self.memory, 'knowledge_indexer'):
            try:
                _similar_patterns = self.memory.knowledge_indexer.search_similar_episodes(
                    query=query,
                    top_k=5,
                    min_score=0.6,
                    success_only=True,
                )
                
                if _similar_patterns:
                    # Count skill votes from similar successful queries
                    from collections import Counter
                    skill_votes = Counter([p["skill"] for p in _similar_patterns if p.get("skill")])
                    if skill_votes:
                        top_skill, count = skill_votes.most_common(1)[0]
                        
                        if count >= 2:  # At least 2/5 similar queries used this skill
                            _routing_hint = {
                                "suggested_skill": top_skill,
                                "confidence": count / len(_similar_patterns),
                                "evidence": f"{count}/{len(_similar_patterns)} similar queries succeeded with '{top_skill}'"
                            }
                            logger.info("PROCEDURAL HINT: skill=%s confidence=%.2f from %d patterns", 
                                       top_skill, _routing_hint["confidence"], len(_similar_patterns))
                    
                    # Cache for Stage 2 (prompt assembly)
                    self._similar_patterns_cache = _similar_patterns
            except Exception as e:
                logger.warning("Procedural memory search failed (non-fatal): %s", e)

        self._plan_cache_hit = None
        if not getattr(self, 'light_mode', False):
            try:
                _pc_results = self.memory.knowledge_indexer.search_plan_cache(
                    embedding=getattr(self, '_cached_query_embedding', None),
                    top_k=1,
                    min_score=0.90,
                )
                if _pc_results:
                    self._plan_cache_hit = _pc_results[0]
                    logger.info("PLAN CACHE HIT: plan_id=%s score=%.2f mode=%s",
                                self._plan_cache_hit["plan_id"],
                                self._plan_cache_hit["score"],
                                self._plan_cache_hit["execution_mode"])
                    _pc_domains = self._plan_cache_hit.get("detected_domains") or []
                    if not _pc_domains:
                        logger.warning("PLAN CACHE: hit plan_id=%s but detected_domains is empty — ignoring, falling back to router",
                                       self._plan_cache_hit["plan_id"])
                        self._plan_cache_hit = None
                    else:
                        _cached_skill = _pc_domains[0]
                        if _cached_skill != skill_name:
                            logger.info("PLAN CACHE: overriding skill '%s' → '%s'",
                                        skill_name, _cached_skill)
                        skill_name = _cached_skill
                        _caller_exec_mode = (routing_info or {}).get("execution_mode", "react")
                        _cached_exec_mode = self._plan_cache_hit.get("execution_mode", "react")
                        _effective_exec_mode = "planned" if _caller_exec_mode == "planned" else _cached_exec_mode
                        if _caller_exec_mode == "planned" and _cached_exec_mode != "planned":
                            logger.info("PLAN CACHE: caller forced execution_mode=planned — overrides cached mode='%s'", _cached_exec_mode)
                        # When forced to planned, keep caller's detected_domains (all skills)
                        # so [ROUTING CONTEXT] is injected and LLM calls create_plan.
                        _effective_domains = (routing_info or {}).get("detected_domains", _pc_domains) \
                            if _caller_exec_mode == "planned" else _pc_domains
                        _effective_mode_hint = (
                            "planned"
                            if _caller_exec_mode == "planned"
                            else (routing_info or {}).get("mode_hint", "react")
                        )
                        routing_info = {
                            "skill":            _cached_skill,
                            "method":           "plan_cache",
                            "confidence":       self._plan_cache_hit["score"],
                            "is_continuation":  False,
                            "is_confirmation":  False,
                            "alternatives":     [],
                            "detected_domains": _effective_domains,
                            "execution_mode":   _effective_exec_mode,
                            "mode_hint":        _effective_mode_hint,
                            "routing_source":   "plan_cache",
                        }
            except Exception as _pce:
                logger.warning("Plan cache search failed (non-fatal): %s", _pce)

        if skill_name is None:
            # Check if procedural memory strongly suggests a skill (>= 80% confidence)
            if _routing_hint and _routing_hint.get("confidence", 0) >= 0.8:
                skill_name = _routing_hint["suggested_skill"]
                routing_info = {
                    "skill": skill_name,
                    "method": "procedural_memory",
                    "confidence": _routing_hint["confidence"],
                    "is_continuation": False,
                    "alternatives": [],
                    "evidence": _routing_hint.get("evidence", "")
                }
                logger.info("ROUTING: Forced to '%s' by procedural memory (conf=%.2f)", 
                           skill_name, _routing_hint["confidence"])
            else:
                last_response = None
                if self.conversation_history:
                    last_response = self.conversation_history[-1].get("response", "")
                routing_info = self.router.match(
                    query, 
                    current_skill=self.current_skill,
                    last_response=last_response,
                    return_details=True,
                    pending_action=self.pending_action,
                    entity_hint=entity_hint,
                    entity_confidence=entity_confidence,
                    process_hint=process_hint,
                    process_matches=process_matches or [],
                    signals_agree=signals_agree,
                )
                skill_name = routing_info["skill"]
        else:
            # Do NOT overwrite routing_info when plan cache already set it above.
            if not routing_info:
                routing_info = {
                    "skill": skill_name,
                    "method": "forced",
                    "confidence": 1.0,
                    "is_continuation": False,
                    "alternatives": []
                }
            elif routing_info.get("method") != "plan_cache":
                routing_info["skill"] = skill_name  # caller's skill is authoritative
        # TRACE: Route span
        if _te and _trace_id:
            try:
                _route_meta = {
                    "method": routing_info.get("method", "") if routing_info else "forced",
                    "confidence": routing_info.get("confidence", 0) if routing_info else 1.0,
                    "is_continuation": routing_info.get("is_continuation", False) if routing_info else False,
                    "alternatives": routing_info.get("alternatives", [])[:5] if routing_info else [],
                }
                _router_llm_meta = (routing_info or {}).get("_router_llm") if isinstance(routing_info, dict) else None
                if isinstance(_router_llm_meta, dict):
                    _route_meta["router_llm"] = _router_llm_meta
                    _route_meta["model"] = _router_llm_meta.get("model", "")
                    _route_meta["prompt_tokens"] = int(_router_llm_meta.get("prompt_tokens") or 0)
                    _route_meta["completion_tokens"] = int(_router_llm_meta.get("completion_tokens") or 0)
                    _route_meta["cost_usd"] = float(_router_llm_meta.get("cost_usd") or 0.0)
                _te.add_span(trace_id=_trace_id, span_type="route", name="skill_router",
                    start_ms=_route_start, duration_ms=(time.time()*1000 - _route_start),
                    status="ok", input_preview=query[:500],
                    output_preview=skill_name,
                    metadata=_route_meta)
                _span_count += 1
            except Exception:
                pass
        
        # Recreate agent if skill changed OR always include fresh memory context
        # We recreate to inject updated memory context into the prompt
        _ctx_start = time.time() * 1000 if _te else 0
        tracker.start_phase(ProgressPhase.LOADING_CONTEXT)
        logger.info("Loading context for skill: %s", skill_name)
        
        self._assert_skill_entitled(skill_name, action="use")
        try:
            self.kernel.current_skill = skill_name
        except Exception:
            pass
        skill = self.loader.load(skill_name)
        self._apply_profile(skill, routing_info, request_profile=profile)
        exec_mode = get_execution_mode(skill.execution_mode)
        _run_cancel.check_cancelled()  # early-out if user stopped before execution began

        if exec_mode == ExecutionMode.WORKFLOW:
            if skill.steps:
                logger.info("Using WORKFLOW execution mode for skill: %s", skill_name)
                _workflow_start = time.time() * 1000 if _te else 0
                _workflow_response = self._run_workflow(skill, query, return_tool_calls, emit_status)
                _workflow_text = _workflow_response[0] if isinstance(_workflow_response, tuple) else _workflow_response
                self._finalize_evidence_bundle(str(_workflow_text or ''), str(_trace_id or ''), query)
                self._log_early_return_turn(query, skill_name, _workflow_response, skip_memory=skip_memory)
                _close_trace_for_early_return(
                    "workflow",
                    _workflow_response,
                    _workflow_start,
                    metadata={"execution_mode": "workflow"},
                )
                return _workflow_response
            logger.info("WORKFLOW skill %s has no steps — falling back to ReAct", skill_name)

        elif exec_mode == ExecutionMode.PARALLEL:
            if skill.steps:
                logger.info("Using PARALLEL execution mode for skill: %s", skill_name)
                _parallel_start = time.time() * 1000 if _te else 0
                _parallel_response = self._run_parallel(skill, query, return_tool_calls, emit_status)
                _parallel_text = _parallel_response[0] if isinstance(_parallel_response, tuple) else _parallel_response
                self._finalize_evidence_bundle(str(_parallel_text or ''), str(_trace_id or ''), query)
                self._log_early_return_turn(query, skill_name, _parallel_response, skip_memory=skip_memory)
                _close_trace_for_early_return(
                    "parallel",
                    _parallel_response,
                    _parallel_start,
                    metadata={"execution_mode": "parallel"},
                )
                return _parallel_response
            logger.info("PARALLEL skill %s has no steps — falling back to ReAct", skill_name)
        
        elif exec_mode == ExecutionMode.SUPERVISOR:
            logger.info("Using SUPERVISOR execution mode for skill: %s", skill_name)
            _supervisor_start = time.time() * 1000 if _te else 0
            _supervisor_response = self._run_supervisor(skill, query, return_tool_calls, emit_status)
            _supervisor_text = _supervisor_response[0] if isinstance(_supervisor_response, tuple) else _supervisor_response
            self._finalize_evidence_bundle(str(_supervisor_text or ''), str(_trace_id or ''), query)
            self._log_early_return_turn(query, skill_name, _supervisor_response, skip_memory=skip_memory)
            _close_trace_for_early_return(
                "supervisor",
                _supervisor_response,
                _supervisor_start,
                metadata={"execution_mode": "supervisor"},
            )
            return _supervisor_response

        elif exec_mode == ExecutionMode.ORCHESTRATOR:
            logger.info("Using ORCHESTRATOR execution mode for skill: %s", skill_name)
            _orchestrator_start = time.time() * 1000 if _te else 0
            _orchestrator_response = self._run_orchestrator(skill, query, return_tool_calls, emit_status)
            _orchestrator_text = _orchestrator_response[0] if isinstance(_orchestrator_response, tuple) else _orchestrator_response
            self._finalize_evidence_bundle(str(_orchestrator_text or ''), str(_trace_id or ''), query)
            self._log_early_return_turn(query, skill_name, _orchestrator_response, skip_memory=skip_memory)
            _close_trace_for_early_return(
                "orchestrator",
                _orchestrator_response,
                _orchestrator_start,
                metadata={"execution_mode": "orchestrator"},
            )
            return _orchestrator_response

        elif exec_mode == ExecutionMode.RLM:
            if not self._rlm_execution_enabled():
                logger.warning(
                    "RLM execution requested for skill '%s' but RLM_ENABLED is false — refusing.",
                    skill_name,
                )
                _msg = (
                    "RLM code execution is disabled on this deployment (RLM_ENABLED=false). "
                    "Enable it, or run this task with a react/graph skill."
                )
                return (_msg, []) if return_tool_calls else _msg
            logger.info("Using RLM execution mode for skill: %s", skill_name)
            self.current_skill = skill_name
            try:
                _rlm_start = time.time() * 1000 if _te else 0
                _rlm_response = self._run_rlm(skill, query, return_tool_calls, emit_status)
                _rlm_text = _rlm_response[0] if isinstance(_rlm_response, tuple) else _rlm_response
                self._finalize_evidence_bundle(str(_rlm_text or ''), str(_trace_id or ''), query)
                self._log_early_return_turn(query, skill_name, _rlm_response, skip_memory=skip_memory)
                _close_trace_for_early_return(
                    "rlm",
                    _rlm_response,
                    _rlm_start,
                    metadata={"execution_mode": "rlm"},
                )
                return _rlm_response
            except Exception as _rlm_err:
                logger.error("RLM execution_mode failed — falling back to ReAct: %s", _rlm_err, exc_info=True)
                # fall through to the ReAct path below

        elif exec_mode == ExecutionMode.GRAPH:
            logger.info("Using GRAPH execution mode for skill: %s", skill_name)
            self.current_skill = skill_name
            try:
                _graph_start = time.time() * 1000 if _te else 0
                _graph_response = self._run_graph(skill, query, return_tool_calls, emit_status)
                _graph_text = _graph_response[0] if isinstance(_graph_response, tuple) else _graph_response
                self._finalize_evidence_bundle(str(_graph_text or ''), str(_trace_id or ''), query)
                self._log_early_return_turn(query, skill_name, _graph_response, skip_memory=skip_memory)
                _close_trace_for_early_return(
                    "graph",
                    _graph_response,
                    _graph_start,
                    metadata={"execution_mode": "graph"},
                )
                return _graph_response
            except Exception as _graph_err:
                logger.error("GRAPH execution_mode failed — falling back to ReAct: %s", _graph_err, exc_info=True)
                # fall through to the ReAct path below

        _router_exec_mode = (routing_info or {}).get("execution_mode", "react") or "react"
        _auto_mode_hint = (routing_info or {}).get("mode_hint", "react")
        if should_use_dynamic_orchestrator(
            mode_hint=_auto_mode_hint,
            skill_execution_mode=exec_mode,
            router_execution_mode=_router_exec_mode,
        ):
            try:
                _all_skills = self.router._get_filtered_skills()
                dynamic_workers = [
                    {"name": sn, "description": smeta.get("description", "")}
                    for sn, smeta in _all_skills.items()
                    if sn != skill_name
                ]
                if dynamic_workers:
                    logger.info(
                        "AUTO-MODE: upgrading '%s' to dynamic orchestrator "
                        "(%d workers, complexity=%s)",
                        skill_name, len(dynamic_workers),
                        (routing_info or {}).get("complexity_class", "multi_step"),
                    )
                    emit_status("Orchestrating across skills…")
                    _dynamic_start = time.time() * 1000 if _te else 0
                    _dynamic_response = self._run_orchestrator(
                        skill, query, return_tool_calls, emit_status,
                        worker_skills_override=dynamic_workers,
                    )
                    _close_trace_for_early_return(
                        "orchestrator",
                        _dynamic_response,
                        _dynamic_start,
                        metadata={"execution_mode": "dynamic_orchestrator"},
                    )
                    return _dynamic_response
                else:
                    logger.info("AUTO-MODE: no other skills available, falling back to ReAct")
            except Exception as _ae:
                logger.warning("AUTO-MODE orchestrator failed to build worker list: %s — falling back to ReAct", _ae)
        elif _auto_mode_hint == "orchestrator" and not dynamic_orchestrator_enabled():
            logger.info(
                "AUTO-MODE: dynamic orchestrator disabled by "
                "DYNAMIC_ORCHESTRATOR_ENABLED=false — using ReAct"
            )


        detected_domains = routing_info.get("detected_domains", []) if routing_info else []
        _exec_mode = (routing_info or {}).get("execution_mode", "react") or "react"
        # Store on self so _load_prompt() can choose compact vs full SKILL.md loading
        self._execution_mode = _exec_mode
        if _exec_mode == "planned":
            self._other_domains = [d for d in detected_domains if d != skill_name]
        else:
            self._other_domains = []

        if skill_name != self.current_skill or self.agent is None:
            self.current_skill = skill_name
            self.agent = self._create_agent(skill_name, query=query)

        from .model_registry import llm_model_name as _llm_model_name, llm_base_url as _llm_base_url
        _primary_model = _llm_model_name(self.llm)
        _primary_base = _llm_base_url(self.llm)
        _light_model = _llm_model_name(self.light_llm) if self.light_llm else 'N/A'
        _light_base = _llm_base_url(self.light_llm) if self.light_llm else ''
        logger.info("🤖 SKILL EXEC  ▸ skill=%s  primary_model=%s  primary_base=%s", skill_name, _primary_model, _primary_base)
        logger.info("🤖 SKILL EXEC  ▸ light_model=%s  light_base=%s", _light_model, _light_base)

        # Per-request streaming LLM: swap only when token_callback provided.
        # Uses model_copy so the ModelRegistry singleton stays non-streaming.
        _orig_llm_streaming = None
        if token_callback is not None:
            try:
                _streaming_llm = self.llm.model_copy(update={"streaming": True})
                _orig_llm_streaming = self.llm
                self.llm = _streaming_llm
                self.agent = self._create_agent(skill_name, query=query)
            except Exception as _stream_setup_err:
                logger.warning("Streaming LLM setup failed, using buffered mode: %s", _stream_setup_err)
                token_callback = None
                _orig_llm_streaming = None

        self.memory.add_to_short_term(role="user", content=query, skill=skill_name)
        tracker.start_phase(ProgressPhase.BUILDING_PROMPT,
                            detail=f"{len(self.memory.short_term)} turns")
        logger.info("Building conversation context...")
        
        # Check if this is a confirmation of pending action
        is_confirmation = routing_info.get("is_confirmation", False) if routing_info else False

        # other_domains already computed above before _create_agent
        other_domains = self._other_domains

        # Search variants pre-expanded by router — inject into prompt so agent
        # uses them directly in file search instead of generating its own
        search_variants = routing_info.get("search_variants", []) if routing_info else []

        # Build messages with conversation history (inject confirmation + domain hints)
        messages = self._build_messages_with_history(
            query, is_confirmation=is_confirmation, other_domains=other_domains,
            search_variants=search_variants,
        )
        _log_context_size(messages, skill=skill_name or "")

        # If confirming, log it
        if is_confirmation and self.pending_action:
            logger.info("Processing confirmation for: %s", self.pending_action.get('action_summary', 'pending action'))
        
        # TRACE: Knowledge/context span
        if _te and _trace_id:
            try:
                _ctx_meta = {
                    "message_count": len(messages),
                    "is_continuation": routing_info.get("is_continuation", False) if routing_info else False,
                    "short_term_turns": len(self.memory.short_term),
                    "has_session_summary": self.session_summary is not None,
                }
                # Capture system prompt snippet (first message is always system)
                _sys_prompt_preview = ""
                if messages and hasattr(messages[0], 'content'):
                    _sys_prompt_preview = str(messages[0].content)[:500]
                elif messages and isinstance(messages[0], tuple):
                    _sys_prompt_preview = str(messages[0][1])[:500] if len(messages[0]) > 1 else ""
                _te.add_span(trace_id=_trace_id, span_type="knowledge", name="context_loading",
                    start_ms=_ctx_start, duration_ms=(time.time()*1000 - _ctx_start),
                    status="ok", input_preview=f"skill={skill_name}",
                    output_preview=f"{len(messages)} messages built\n\nSystem prompt preview:\n{_sys_prompt_preview}",
                    metadata=_ctx_meta)
                _span_count += 1
            except Exception:
                pass
        
        _prev_user_msg = None
        if self.conversation_history:
            _prev_user_msg = self.conversation_history[-1].get("user_input", "")

        logger.info("Calling LLM with %d messages...", len(messages))
        tracker.start_phase(ProgressPhase.GENERATING,
                            detail=f"{len(messages)} messages")
        
        # Track processing time for outcome metrics
        start_time = time.time()
        
        # Run agent with exception capture for learning
        _llm_start = time.time() * 1000 if _te else 0
        _llm_error = None
        # LangChain callback: always created for live tool status via Option D,
        # trace spans only emitted when _te is available.
        _tool_cb = TraceToolCallback(
            trace_id=_trace_id if _te else None,
            trace_emitter=_te,
            progress_tracker=tracker,
            hook_runner=self.hook_runner,
            session_ctx=self._build_session_ctx(),
            tool_execution_observer=self.tool_execution_capability,
        )
        _token_cb = LLMTokenTracker("agent")
        _callbacks = [_tool_cb, _token_cb]
        if token_callback is not None:
            _callbacks.append(token_callback)
        _invoke_config = {**self.agent_config, "callbacks": _callbacks}

        _react_runtime_selection = resolve_react_runtime(
            skill=skill,
            config=self.config if isinstance(self.config, dict) else {},
            env=os.environ,
            routing_info=routing_info,
        )
        self._react_runtime_selection = _react_runtime_selection
        if _react_runtime_selection.fallback_reason:
            logger.warning("React runtime selection: %s", _react_runtime_selection.fallback_reason[:200])

        def _is_rate_limit(exc: Exception) -> bool:
            s = str(exc).lower()
            return "429" in s or "ratelimitreached" in s or "rate_limit" in s or "rate limit" in s

        try:
            self.hook_runner.run_before_model_call(
                {**self._build_session_ctx(), "query": query, "execution_mode": "react"},
                model_role="primary",
                model_name=getattr(self.llm, "azure_deployment", "") or getattr(self.llm, "model_name", "") or "",
            )
        except Exception as _bmc_err:  # pragma: no cover
            logger.debug("HookRunner [BeforeModelCall] error (non-fatal): %s", _bmc_err)

        _mc_start_ms = time.time() * 1000
        try:
            with model_call_context({
                **self._build_session_ctx(),
                "query": query,
                "execution_mode": "react",
                "model_role": "primary",
                "model_name": getattr(self.llm, "azure_deployment", "") or getattr(self.llm, "model_name", "") or "",
            }):
                # Sufficiency loop: may run up to sufficiency_max_iterations internally.
                # Falls back to single-shot if sufficiency_enabled=False or skill is skipped.
                if _react_runtime_selection.runtime == "native":
                    try:
                        logger.info("Using native React runtime for skill: %s", skill_name)
                        # Live-activity emitter for the thinking box (Tier 2/3): narrates each
                        # model call, tool call, and surfaces per-turn reasoning. Guarded end-to-end.
                        def _native_activity_emit(kind, value):
                            if status_callback is None:
                                return
                            try:
                                if kind == "reason":
                                    status_callback(f"💭 Reasoning… (step {int(value) + 1})")
                                elif kind == "tool":
                                    status_callback(f"🔧 {value}…")
                                elif kind == "reasoning_text" and value:
                                    status_callback({"__rlm_event__": True, "card_type": "native_reasoning",
                                                     "label": "Model reasoning", "text": str(value)[:1400]})
                            except Exception:
                                pass
                        result = self._run_with_native_react_runtime(
                            messages, _invoke_config, query, skill_name, emit=_native_activity_emit)
                    except ReactRuntimeUnavailable as native_err:
                        if not self._native_react_fallback_enabled():
                            raise
                        logger.warning(
                            "Native React runtime unavailable for skill '%s' — falling back to LangGraph: %s",
                            skill_name,
                            str(native_err)[:300],
                        )
                        _collected = getattr(native_err, "collected_messages", None)
                        if getattr(native_err, "exhausted_max_iterations", False) and _collected:
                            logger.info(
                                "Resuming LangGraph from %d executed native messages (no re-run)",
                                len(_collected),
                            )
                            result = self._run_with_sufficiency(_collected, _invoke_config, query, skill_name)
                        else:
                            result = self._run_with_sufficiency(messages, _invoke_config, query, skill_name)
                else:
                    result = self._run_with_sufficiency(messages, _invoke_config, query, skill_name)
        except ModelCallBlocked as blocked:
            _llm_error = blocked
            _blocked_hook_result = getattr(blocked, "hook_result", None)
            if wants_hitl(_blocked_hook_result) and not getattr(self, "approval_pending", None):
                try:
                    set_hook_approval(
                        self,
                        _blocked_hook_result,
                        session_ctx={**self._build_session_ctx(), "hook_event": getattr(_blocked_hook_result, "hook_event", "BeforeModelCall")},
                        skill_name=skill_name,
                        query=query,
                        extra_context={
                            "model_role": "primary",
                            "model_name": getattr(self.llm, "azure_deployment", "") or getattr(self.llm, "model_name", "") or "",
                        },
                    )
                    result = "__PENDING__"
                except Exception as _mcp_hitl_err:  # pragma: no cover - defensive
                    logger.debug("Model-call HITL approval conversion failed: %s", _mcp_hitl_err)
                    result = f"__BLOCKED__|{blocked.reason}"
            else:
                result = f"__BLOCKED__|{blocked.reason}"
        except Exception as e:
            try:
                self.hook_runner.run_on_error(
                    {**self._build_session_ctx(), "query": query, "execution_mode": "react"},
                    error_msg=str(e)[:500],
                )
            except Exception:  # pragma: no cover - observe-only
                pass
            if _is_rate_limit(e):
                from .model_provider import default_model_provider
                _fallback_llm = default_model_provider.get("fallback")
                _primary_deployment = getattr(self.llm, 'azure_deployment', 'primary')
                _fallback_deployment = getattr(_fallback_llm, 'azure_deployment', 'fallback') if _fallback_llm else None
                if _fallback_llm and _fallback_deployment != _primary_deployment:
                    logger.warning(
                        "Rate limit on '%s' — retrying with fallback '%s'",
                        _primary_deployment, _fallback_deployment
                    )
                    _orig_llm = self.llm
                    try:
                        self.llm = self._policy_wrap_llm(_fallback_llm, role="fallback")
                        self.agent = self._create_agent(skill_name, query=query)
                        # Rate limit fallback: single shot only, no sufficiency loop
                        result = self._run_with_stream_intercept(messages, _invoke_config)
                    except Exception as fallback_exc:
                        _llm_error = fallback_exc
                        raise
                    finally:
                        # Always restore primary for next request
                        self.llm = _orig_llm
                        self.agent = None  # force rebuild with primary on next turn
                else:
                    _llm_error = e
                    raise
            else:
                _llm_error = e
                # TRACE: LLM error span
                if _te and _trace_id:
                    try:
                        _te.add_span(trace_id=_trace_id, span_type="llm", name="agent_invoke",
                            start_ms=_llm_start, duration_ms=(time.time()*1000 - _llm_start),
                            status="error", input_preview=query[:500],
                            output_preview=f"{type(e).__name__}: {str(e)[:500]}",
                            metadata={"model": getattr(self.llm, 'azure_deployment', 'unknown'),
                                      "error_type": type(e).__name__})
                        _span_count += 1
                        _model_name = getattr(self.llm, 'azure_deployment', getattr(self.llm, 'model_name', ''))
                        _llm_budget = llm_tracker.end_budget()
                        _te.end_trace(trace_id=_trace_id, status="error", skill=skill_name,
                            span_count=_span_count, total_ms=(time.time()*1000 - _trace_start_ms),
                            prompt_tokens=_llm_budget["summary"]["total_prompt_tokens"] if _llm_budget else _prompt_tokens,
                            completion_tokens=_llm_budget["summary"]["total_completion_tokens"] if _llm_budget else _completion_tokens,
                            cost_usd=_llm_budget["summary"]["total_cost_usd"] if _llm_budget else calculate_cost(_model_name, _prompt_tokens, _completion_tokens),
                            metadata={"llm_budget": _llm_budget} if _llm_budget else None)
                    except Exception:
                        pass
                # Log agent execution failure (skill-scoped)
                self.append_learning("agent_error", {
                    "query_preview": query[:100],
                    "error_type": type(e).__name__,
                    "error_message": str(e)[:500]
                }, skill_name=skill_name)
                raise  # Re-raise to let caller handle
        finally:
            # Restore non-streaming LLM singleton if we swapped it for this request
            if _orig_llm_streaming is not None:
                self.llm = _orig_llm_streaming
                self.agent = None  # Force rebuild on next request

        # ── Stream intercept: write tool was blocked, waiting for user approval ──
        if result == "__PENDING__":
            # Builds the legacy pending_action (so chat.py WS broadcast still works) and
            # the confirmation text; shared with the re-pause case in _resume_native_turn.
            response = self._build_stream_intercept_pending(skill_name)
            if _te and _trace_id:
                try:
                    _te.add_span(
                        trace_id=_trace_id,
                        span_type="hitl",
                        name="approval_pending",
                        start_ms=_mc_start_ms,
                        duration_ms=(time.time() * 1000 - _mc_start_ms),
                        status="awaiting_human",
                        input_preview=query[:500],
                        output_preview=response[:1000],
                        metadata={
                            "skill": skill_name,
                            "approval_id": (getattr(self, "approval_pending", None) or {}).get("approval_id", ""),
                            "pending_tool": (getattr(self, "pending_tool_call", None) or {}).get("name", ""),
                        },
                    )
                    _span_count += 1
                    _model_name = getattr(self.llm, 'azure_deployment', getattr(self.llm, 'model_name', ''))
                    _llm_budget = llm_tracker.end_budget()
                    _te.end_trace(
                        trace_id=_trace_id,
                        status="awaiting_human",
                        skill=skill_name,
                        span_count=_span_count,
                        total_ms=(time.time() * 1000 - _trace_start_ms),
                        prompt_tokens=_llm_budget["summary"]["total_prompt_tokens"] if _llm_budget else _prompt_tokens,
                        completion_tokens=_llm_budget["summary"]["total_completion_tokens"] if _llm_budget else _completion_tokens,
                        cost_usd=_llm_budget["summary"]["total_cost_usd"] if _llm_budget else calculate_cost(_model_name, _prompt_tokens, _completion_tokens),
                        metadata={"llm_budget": _llm_budget, "paused_for": "hitl"} if _llm_budget else {"paused_for": "hitl"},
                    )
                except Exception:  # pragma: no cover - tracing must not block HITL
                    pass
            if return_tool_calls:
                return response, []
            return response

        if isinstance(result, str) and result.startswith("__BLOCKED__|"):
            reason = result.split("|", 1)[1] or "Tool call blocked by policy hook."
            response = f"⚠️ Tool call blocked by policy hook: {reason}"
            if _te and _trace_id:
                try:
                    _te.add_span(
                        trace_id=_trace_id,
                        span_type="hook",
                        name="tool_call_blocked",
                        start_ms=time.time() * 1000,
                        duration_ms=0,
                        status="blocked",
                        input_preview=query[:500],
                        output_preview=response[:1000],
                        metadata={"skill": skill_name, "reason": reason[:500]},
                    )
                    _span_count += 1
                    _finalize_trace_now(response, metadata={"blocked_by": "PreToolUse", "reason": reason[:200]})
                except Exception:
                    pass
            if return_tool_calls:
                return response, []
            return response

        _llm_duration = time.time() * 1000 - _llm_start if _te else 0
        logger.info("Agent invoke completed, got %d result messages", len(result.get('messages', [])))
        tracker.start_phase(ProgressPhase.PROCESSING)

        try:
            _mc_dur = int(time.time() * 1000 - _mc_start_ms)
            _budget_snap = llm_tracker.get_budget() or {}
            _summary = (_budget_snap.get("summary") or {}) if isinstance(_budget_snap, dict) else {}
            self.hook_runner.run_after_model_call(
                {**self._build_session_ctx(), "query": query, "execution_mode": "react"},
                model_role="primary",
                model_name=getattr(self.llm, "azure_deployment", "") or getattr(self.llm, "model_name", "") or "",
                prompt_tokens=int(_summary.get("total_prompt_tokens", 0) or 0),
                completion_tokens=int(_summary.get("total_completion_tokens", 0) or 0),
                duration_ms=_mc_dur,
            )
        except Exception as _amc_err:  # pragma: no cover - observe-only
            logger.debug("HookRunner [AfterModelCall] error (non-fatal): %s", _amc_err)

        response = result["messages"][-1].content

        try:
            _ec = getattr(self, '_evidence_collector', None)
            if _ec is not None:
                _mem = getattr(self, 'memory', None)
                _highlight_config = {}
                try:
                    _skill_name = getattr(self, "current_skill", None)
                    if _skill_name:
                        _skill = self.loader.load(_skill_name)
                        _highlight_config = getattr(_skill, "evidence_highlights", {}) or {}
                except Exception as _cfg_err:
                    logger.debug("Evidence highlight config load failed (non-fatal): %s", _cfg_err)
                self._evidence_bundle = _ec.get_bundle(
                    response_text=response or '',
                    query_text=query or '',
                    trace_id=str(_trace_id or ''),
                    tenant_id=getattr(_mem, 'tenant_id', '') or '',
                    agent_id=getattr(_mem, 'agent_id', '') or '',
                    user_id=self.user_id or '',
                    execution_source=getattr(self, '_evidence_execution_source', 'chat'),
                    highlight_config=_highlight_config,
                )
        except Exception as _ev_err:
            logger.debug("Evidence bundle build failed (non-fatal): %s", _ev_err)

        # TRACE: LLM success span
        if _te and _trace_id:
            try:
                _llm_meta = {
                    "result_messages": len(result.get('messages', [])),
                    "model": getattr(self.llm, 'azure_deployment', getattr(self.llm, 'model_name', 'unknown')),
                }
                # Extract token usage from LangChain response if available
                _last_msg = result["messages"][-1]
                _usage = getattr(_last_msg, 'usage_metadata', None) or getattr(_last_msg, 'response_metadata', {}).get('token_usage')
                if _usage and isinstance(_usage, dict):
                    _llm_meta["prompt_tokens"] = _usage.get("input_tokens") or _usage.get("prompt_tokens", 0)
                    _llm_meta["completion_tokens"] = _usage.get("output_tokens") or _usage.get("completion_tokens", 0)
                    _llm_meta["total_tokens"] = _usage.get("total_tokens", 0)
                    # Accumulate into trace-level totals
                    _prompt_tokens += int(_llm_meta["prompt_tokens"])
                    _completion_tokens += int(_llm_meta["completion_tokens"])
                _provider_meta = (getattr(self, "_last_native_react_turn", None) or {}).get("provider_metadata") or {}
                _provider = str(_provider_meta.get("provider") or "")
                if _provider and reasoning_expose_enabled(_provider):
                    _preview = _native_reasoning_preview(getattr(self, "_last_native_react_turn", None))
                    if _preview:
                        _llm_meta["reasoning_preview"] = _preview
                _te.add_span(trace_id=_trace_id, span_type="llm", name="agent_invoke",
                    start_ms=_llm_start, duration_ms=_llm_duration,
                    status="ok", input_preview=query[:500],
                    output_preview=response[:4096],
                    metadata=_llm_meta)
                _span_count += 1
            except Exception:
                pass
        
        pending_approval = None
        for msg in result["messages"]:
            if msg.__class__.__name__ == "ToolMessage":
                content = getattr(msg, 'content', '')
                if "__PENDING_APPROVAL__" in content:
                    # Parse: __PENDING_APPROVAL__|operation|target|command
                    parts = content.split("|")
                    if len(parts) >= 4:
                        pending_approval = {
                            "operation": parts[1],
                            "target": parts[2],
                            "command": parts[3],
                            "skill": skill_name,
                            "timestamp": datetime.now()
                        }
                        self.pending_action = pending_approval
                        logger.info("Pending approval: %s on %s", parts[1], parts[2])
                        response = f"⚠️ **Confirmation Required**\n\n**Operation:** {parts[1]}\n**Target:** {parts[2]}\n\n```\n{parts[3]}\n```\n\nPlease approve or reject this action."
                        if return_tool_calls:
                            return response, []  # Return tuple for consistency
                        return response
        
        approval_checkpoint = None
        for msg in result["messages"]:
            if msg.__class__.__name__ == "ToolMessage":
                content = getattr(msg, 'content', '')
                if "__APPROVAL_CHECKPOINT__" in content:
                    # Parse: __APPROVAL_CHECKPOINT__|{approval_id}|{reason}
                    parts = content.split("|", 2)
                    approval_id = parts[1] if len(parts) > 1 else "unknown"
                    reason = parts[2] if len(parts) > 2 else "Approval requested"
                    
                    # self.approval_pending was set by the tool closure
                    if self.approval_pending:
                        approval_checkpoint = self.approval_pending.copy()
                    else:
                        approval_checkpoint = {
                            "approval_id": approval_id,
                            "reason": reason,
                            "skill": skill_name,
                            "timestamp": datetime.now().isoformat(),
                        }
                    
                    logger.info("HITL Checkpoint: %s -- %s", approval_id, reason)
                    
                    # Build rich response for UI
                    ctx = approval_checkpoint.get("context", {})
                    ctx_display = ""
                    if ctx:
                        ctx_lines = [f"  - **{k}**: {v}" for k, v in ctx.items()]
                        ctx_display = "\n".join(ctx_lines)
                    
                    urgency = approval_checkpoint.get("urgency", "medium")
                    urgency_emoji = {"low": "🟢", "medium": "🟡", "high": "🟠", "critical": "🔴"}.get(urgency, "🟡")
                    
                    response = (
                        f"🔔 **Human Approval Required** {urgency_emoji} {urgency.upper()}\n\n"
                        f"**Reason:** {reason}\n\n"
                    )
                    if ctx_display:
                        response += f"**Context:**\n{ctx_display}\n\n"
                    
                    rule_info = approval_checkpoint.get("rule_matched")
                    if rule_info:
                        response += f"**Policy Rule:** {rule_info}\n\n"
                    
                    response += (
                        f"**Approval ID:** `{approval_id}`\n\n"
                        f"⏳ This task is paused. Resolve via the Command Center dashboard or API.\n"
                        f"SLA: {approval_checkpoint.get('sla_minutes', 120)} minutes"
                    )
                    
                    if return_tool_calls:
                        return response, []
                    return response

        for msg in result["messages"]:
            if msg.__class__.__name__ == "ToolMessage":
                content = getattr(msg, 'content', '')
                if "__CHAT_PAUSE__" in content:
                    ap = self.approval_pending or {}
                    logger.info("Inline-chat pause checkpoint: %s", ap.get("approval_id"))
                    # Echo exactly what the skill asked to render (its tables/prose).
                    response = ap.get("render") or ap.get("reason") or "⏳ Paused — reply to continue."
                    if return_tool_calls:
                        return response, []
                    return response

        # Clear pending action if this was a confirmed execution
        if self.pending_action and not pending_approval:
            logger.info("Action completed, clearing pending state")
            self.pending_action = None
        
        # Collect tool calls and their results for logging
        tool_calls_log = []
        tool_results = {}  # Map tool_call_id -> result content
        
        # First pass: collect tool results (ToolMessage)
        for msg in result["messages"]:
            if msg.__class__.__name__ == "ToolMessage":
                tool_results[getattr(msg, 'tool_call_id', None)] = {
                    "content": getattr(msg, 'content', ''),
                    "name": getattr(msg, 'name', 'unknown')
                }
        
        # Second pass: collect tool calls and save learnings
        for msg in result["messages"]:
            if hasattr(msg, 'tool_calls') and msg.tool_calls:
                for tc in msg.tool_calls:
                    tool_name = tc.get('name', 'unknown')
                    cmd = tc.get('args', {}).get('command', '')
                    tool_call_id = tc.get('id')
                    
                    tool_calls_log.append(cmd if cmd else tool_name)
                    
                    # Get result for this tool call
                    tool_result = tool_results.get(tool_call_id, {})
                    result_content = tool_result.get("content", "")
                    
                    # Determine success: real errors start with "Error" (kernel format)
                    has_error = result_content.strip().startswith("Error") if result_content else False
                    
                    # Save tool execution learning (skill-scoped)
                    self.append_learning("tool_execution", {
                        "tool": tool_name,
                        "command": cmd[:200] if cmd else None,
                        "executed": True,
                        "has_error": has_error,
                        "result_preview": result_content[:500] if result_content else None
                    }, skill_name=skill_name)
        
        import re as _ctx_re
        _ctx_file_names = []
        for _tc_cmd in tool_calls_log:
            for _m in _ctx_re.findall(r'contexts/([^/\s\'"]+\.md)', str(_tc_cmd)):
                if _m not in _ctx_file_names:
                    _ctx_file_names.append(_m)
        self._session_context_files = _ctx_file_names  # list of basenames e.g. ["p2p_context.md"]

        # Build tool_results for decision_context (enhanced detail)
        # Captures full tool input args + output preview for reasoning extraction
        tool_results_detail = []
        for msg in result["messages"]:
            if hasattr(msg, 'tool_calls') and msg.tool_calls:
                for tc in msg.tool_calls:
                    tool_name = tc.get('name', 'unknown')
                    tool_args = tc.get('args', {})
                    cmd = tool_args.get('command', '')
                    tool_call_id = tc.get('id')
                    tool_result = tool_results.get(tool_call_id, {})
                    result_content = tool_result.get("content", "")
                    # Real errors start with "Error" (kernel format)
                    has_error = result_content.strip().startswith("Error") if result_content else False
                    
                    # Build a readable input string from all args (not just 'command')
                    if cmd:
                        tool_input = cmd[:500]
                    else:
                        # For non-shell tools (run_sql_query, query_memory, etc.)
                        # Capture the full args as a readable string
                        input_parts = []
                        for k, v in tool_args.items():
                            v_str = str(v)[:300]
                            input_parts.append(f"{k}: {v_str}")
                        tool_input = "; ".join(input_parts)[:500] if input_parts else None
                    
                    tool_results_detail.append({
                        "tool": tool_name,
                        "input": tool_input,
                        "output_preview": result_content[:800] if result_content else None,
                        "executed": True,
                        "has_error": has_error,
                    })
                    try:
                        from .capture_events import emit_tool_call

                        data_root = validated_path(str(getattr(getattr(self, "kernel", None), "agent_root", "") or "."), label="agent root")
                        for parent in [data_root, *data_root.parents]:
                            candidate = parent / "enterprise_root"
                            if candidate.exists():
                                data_root = candidate
                                break
                        emit_tool_call(
                            data_root=data_root,
                            tenant_id=str(getattr(getattr(self, "kernel", None), "tenant_id", "") or default_tenant_id()),
                            trajectory_id=str(_trace_id or getattr(self, "_active_trace_id", "") or self.session_id or ""),
                            tool_call_id=str(tool_call_id or f"{_trace_id}:tool:{len(tool_results_detail)}"),
                            name=str(tool_name),
                            arguments=tool_args,
                            output=result_content,
                            status="error" if has_error else "ok",
                            error=result_content[:1000] if has_error else None,
                            metadata={"skill": skill_name, "source": "agent_tool_message"},
                        )
                    except Exception as emit_exc:
                        logger.debug("Tool call capture skipped: %s", emit_exc)
        
        _critique_result = None  # placeholder — filled by chat.py

        # Build decision_context for episodic logging
        # Note: facts_used deprecated - user facts now tracked via Context Graph entities
        facts_used = []
        prior_skill = None
        if len(self.memory.short_term) > 1:
            # Get skill from 2nd-to-last entry (before current)
            prior_skill = self.memory.short_term[-2].get("skill") if len(self.memory.short_term) >= 2 else None
        
        # Get business context from skill metadata (if available)
        skill_business_context = {}
        try:
            skill_obj = self.loader.load(skill_name)
            skill_business_context = skill_obj.business_context or {}
        except Exception:
            pass  # Skill may not have business_context defined
        
        processing_time_ms = int((time.time() - start_time) * 1000)
        
        # Skip all memory operations if requested (for batch processing)
        if skip_memory:
            # TRACE: End trace (batch mode)
            if _te and _trace_id:
                try:
                    _model_name = getattr(self.llm, 'azure_deployment', getattr(self.llm, 'model_name', ''))
                    _llm_budget = llm_tracker.end_budget()
                    _te.end_trace(trace_id=_trace_id, status="success", skill=skill_name,
                        span_count=_span_count, total_ms=(time.time()*1000 - _trace_start_ms),
                        prompt_tokens=_llm_budget["summary"]["total_prompt_tokens"] if _llm_budget else _prompt_tokens,
                        completion_tokens=_llm_budget["summary"]["total_completion_tokens"] if _llm_budget else _completion_tokens,
                        cost_usd=_llm_budget["summary"]["total_cost_usd"] if _llm_budget else calculate_cost(_model_name, _prompt_tokens, _completion_tokens),
                        metadata={"llm_budget": _llm_budget} if _llm_budget else None)
                except Exception:
                    pass
            logger.info("Response ready in %dms (memory skipped for batch)", processing_time_ms)
            self._last_trace_id = _trace_id or ""   # expose for orchestrator child linking
            if return_tool_calls:
                return response, tool_calls_log
            return response
        
        # Add response to short-term memory IMMEDIATELY (fast, sync)
        tracker.start_phase(ProgressPhase.SAVING)
        logger.info("Saving to short-term memory...")
        self.memory.add_to_short_term(
            role="assistant", content=response, 
            skill=skill_name, tool_calls=tool_calls_log
        )
        
        # Log conversation turn (JSONL audit + in-memory conversation_history)
        # conversation_history feeds _build_messages_with_history for follow-up context.
        self._log_conversation(query, skill_name, tool_calls_log, response)
        self._inflight_query = None  # Turn is now in conversation_history
        
        # Count tool errors for basic logging
        tool_error_count = sum(1 for t in tool_results_detail if t.get("has_error"))
        react_runtime = getattr(getattr(self, "_react_runtime_selection", None), "runtime", "langgraph")
        observable_reasoning_summary = _build_observable_reasoning_summary(
            runtime=react_runtime,
            skill_name=skill_name,
            tool_results_detail=tool_results_detail,
            native_turn=getattr(self, "_last_native_react_turn", None),
        )
        
        # Build decision context BEFORE async thread so UI can read it immediately
        _ri = routing_info or {}
        _pending_plan = getattr(self, '_pending_plan', None)
        decision_context = {
            "routing": {
                "method":          _ri.get("method", "unknown"),
                "confidence":      _ri.get("confidence", 0.0),
                "is_continuation": _ri.get("is_continuation", False),
                "alternatives":    _ri.get("alternatives", []),
                # Entity & process signals that drove routing (already computed, now persisted)
                "entity_hint":      _ri.get("entity_hint") or entity_hint,
                "entity_confidence": _ri.get("entity_confidence", entity_confidence),
                "process_hint":     _ri.get("process_hint") or process_hint,
                "signals_agree":    _ri.get("signals_agree", signals_agree),
                "detected_domains": _ri.get("detected_domains", []),
                "execution_mode":   _ri.get("execution_mode", "react"),
                "react_runtime":     react_runtime,
                "routing_source":   _ri.get("method", "llm"),
            },
            # Ontology nodes resolved at query time — gives LLM full context for
            # lifecycle questions without needing tool-level instrumentation
            "entity_context": {
                "entity_hint":     entity_hint,
                "process_hint":    process_hint,
                "process_matches": process_matches or [],
            } if (entity_hint or process_hint or process_matches) else None,
            # Plan details — only present when create_plan tool ran this turn
            "plan": {
                "plan_id":         _pending_plan.get("plan_id"),
                "plan_steps":      _pending_plan.get("steps", []),
                "critique_result": _pending_plan.get("critique"),
                "plan_outcome":    "pending_approval",
            } if _pending_plan else None,
            "context_used": {
                "facts_referenced": facts_used[:10],
                "data_sources": [
                    # `input` may be None or non-string for non-shell tools (e.g. MCP
                    # tool calls) — coerce so .split()/.startswith() never hit None.
                    _inp.split()[1] if _tool == "shell" and len(_inp.split()) > 1
                    else _inp.split(";")[0].replace("database:", "").strip() if _inp.startswith("database:")
                    else _tool
                    for t in tool_results_detail[:5]
                    for _inp in [t.get("input") if isinstance(t.get("input"), str) else ""]
                    for _tool in [t.get("tool") or "unknown"]
                ],
                "short_term_turns": len(self.memory.short_term),
                "prior_skill": prior_skill,
            },
            "outcome": {
                "status": "success" if tool_error_count == 0 else "partial",
                "processing_time_ms": processing_time_ms,
                "tools_executed": len(tool_results_detail),
                "tool_errors": tool_error_count,
                "human_intervention": False,
                "feedback": None
            },
            "tool_calls": tool_results_detail,
            "reasoning_summary": observable_reasoning_summary,
            "critique": _critique_result,   # None when critique disabled / no tools ran
        }
        if _trace_id:
            decision_context["trace_id"] = _trace_id
        _provider_meta = (getattr(self, "_last_native_react_turn", None) or {}).get("provider_metadata") or {}
        _provider = str(_provider_meta.get("provider") or "")
        if _provider and reasoning_expose_enabled(_provider):
            _preview = _native_reasoning_preview(getattr(self, "_last_native_react_turn", None))
            if _preview:
                decision_context["native_reasoning"] = {
                    "provider": _provider,
                    "preview": _preview,
                }
        
        # Stash for server to read after run() returns (UI reasoning panel)
        self._last_decision_context = decision_context

        if (_exec_mode == "react" and
                decision_context["outcome"]["status"] in ("success", "partial") and
                not getattr(self, '_plan_cache_hit', None) and
                not getattr(self, 'light_mode', False)):  # don't cache in fresh mode
            try:
                import uuid as _uuid
                _indexer = getattr(self.memory, 'knowledge_indexer', None)
                if _indexer and hasattr(_indexer, 'upsert_plan_cache'):
                    _ri_domains = (_ri.get("detected_domains") or [skill_name]) if _ri else [skill_name]
                    _pc_steps = [{"step": 1, "skill": skill_name, "action": query[:120]}]
                    _pc_nodes = []
                    if process_matches:
                        _pc_nodes = [m.get("node_id", "") for m in process_matches if m.get("node_id")]
                    _pc_entity_types = []
                    if entity_hint:
                        _pc_entity_types = [entity_hint]
                    _pc_hints = [
                        {"tool": t.get("tool"), "input": t.get("input")}
                        for t in tool_results_detail
                        if not t.get("has_error") and t.get("input")
                    ]
                    _indexer.upsert_plan_cache(
                        plan_id=f"single_{_uuid.uuid4().hex[:12]}",
                        goal=query,
                        plan_steps=_pc_steps,
                        execution_mode="react",
                        detected_domains=_ri_domains,
                        entity_types=_pc_entity_types,
                        process_nodes=_pc_nodes,
                        critique_json=None,
                        session_id=self.session_id,
                        tenant_id=getattr(self.kernel, 'tenant_id', None),
                        agent_id=getattr(self.kernel, 'agent_id', None),
                        executed_at=datetime.now().isoformat(),
                        embedding=getattr(self, '_cached_query_embedding', None),
                        context_hints=__import__('json').dumps(_pc_hints),
                    )
            except Exception as _pce:
                logger.warning("plan_cache single-skill write failed (non-fatal): %s", _pce)

        def _async_extract_and_log():
            """Background thread: Log episode + analyze implicit feedback."""
            try:
                import time as _t
                _start = _t.time()
                logger.debug("[ASYNC] Logging episode for: %s...", query[:50])
                
                # Step 1: Log to episodic memory (with trace_id for cross-linking)
                self._log_episode_via_memory_boundary(
                    user_input=query,
                    response=response,
                    skill=skill_name,
                    tool_calls=tool_calls_log,
                    decision_context=decision_context,
                    summary_mode="truncate",  # Simpler - no LLM summary needed
                    update_brain_index=False  # Disabled - grep search works without it
                )
                logger.debug("[ASYNC] Episodic logging completed in %.0fms", (_t.time()-_start)*1000)

                if "<!-- LEARN:" in (response or ""):
                    logger.debug("[ASYNC] Skipping implicit feedback — LEARN marker present in response")
                else:
                    try:
                        _fb_start = _t.time()
                        signals = self._analyze_implicit_feedback(
                            query=query,
                            response=response,
                            prev_user_msg=_prev_user_msg,
                            skill_name=skill_name,
                            tool_calls_log=tool_calls_log,
                        )
                        for sig in signals:
                            knowledge_type = self._IMPLICIT_TYPE_MAP.get(sig["type"], "pattern")
                            status = self._triage_implicit_signal(sig)
                            # Preferences are personal — tag with user_id so dashboard
                            # can filter per-user. All other types are shared team knowledge.
                            extra_tags = ["implicit_feedback", sig["type"]]
                            _current_user = getattr(self.memory, 'user_id', None)
                            if knowledge_type == "preference" and _current_user:
                                extra_tags.append(f"user:{_current_user}")
                            self._write_knowledge_via_memory_boundary(
                                knowledge_type=knowledge_type,
                                summary=sig["summary"][:150],
                                applies_when=sig.get("applies_when", "")[:100],
                                source="inferred",
                                status=status,
                                skill=skill_name,
                                tags=extra_tags,
                                user_query=query[:200],
                                source_context_file=(getattr(self, '_session_context_files', None) or [None])[0],
                            )
                            status_emoji = "confirmed" if status == "confirmed" else "pending"
                            logger.debug("[IMPLICIT] %s (%s, %s): %s", sig['type'], sig.get('confidence', '?'), status_emoji, sig['summary'][:60])
                        if signals:
                            logger.debug("[ASYNC] Implicit feedback: %d signal(s) in %.0fms", len(signals), (_t.time()-_fb_start)*1000)
                    except Exception as fb_err:
                        logger.warning("[ASYNC] Implicit feedback failed (non-fatal): %s", fb_err)

            except Exception as e:
                logger.warning("[ASYNC] Episodic logging failed (non-fatal): %s", e)

            # HOOKS: PostSampling — external hooks only in Phase 1 (internal stubs not yet active).
            # Switch external_only=False in Phase 2 after inline code above is deleted.
            try:
                self.hook_runner.run_post_sampling(
                    session_ctx={
                        **self._build_session_ctx(),
                        "query":            query,
                        "response":         response,
                        "tool_calls_log":   tool_calls_log,
                        "tool_error_count": tool_error_count,
                    },
                    external_only=True,
                )
            except Exception as _hpe:
                logger.warning("[ASYNC] PostSampling hook fire failed (non-fatal): %s", _hpe)

        # TRACE: Emit tool spans from callback (real per-tool timing)
        if _tool_cb:
            _span_count += _tool_cb.emit_spans()
        
        # TRACE: Memory span
        _mem_start = time.time() * 1000 if _te else 0
        
        def _async_log_episode_only():
            """Light-mode background thread: persist JSONL history, skip learning."""
            try:
                self._log_episode_via_memory_boundary(
                    user_input=query,
                    response=response,
                    skill=skill_name,
                    tool_calls=tool_calls_log,
                    decision_context=decision_context,
                    summary_mode="truncate",
                    update_brain_index=False,
                )
            except Exception as e:
                logger.warning("[ASYNC light] Episode log failed: %s", e)

        if not getattr(self, 'light_mode', False):
            bg_thread = threading.Thread(target=_async_extract_and_log, daemon=False)
            bg_thread.start()
            logger.info("Response ready in %dms (memory extraction running async)", processing_time_ms)
        else:
            # Light mode: still persist conversation history, skip learning extraction
            bg_thread = threading.Thread(target=_async_log_episode_only, daemon=False)
            bg_thread.start()
            logger.info("Response ready in %dms (light mode — episode logged, no learning extraction)", processing_time_ms)
        
        # TRACE: Memory span + end trace
        if _te and _trace_id:
            try:
                _te.add_span(trace_id=_trace_id, span_type="memory", name="episodic_log",
                    start_ms=_mem_start, duration_ms=(time.time()*1000 - _mem_start),
                    status="ok", input_preview=f"skill={skill_name}, session={self.session_id[:20]}",
                    output_preview=f"tools={len(tool_calls_log)}, errors={tool_error_count}, trace_id={_trace_id[:12]}",
                    metadata={"tools_executed": len(tool_calls_log), "tool_errors": tool_error_count,
                              "trace_id_ref": _trace_id, "processing_time_ms": processing_time_ms})
                _span_count += 1
                # TRACE: Response span (full request)
                _te.add_span(trace_id=_trace_id, span_type="response", name="full_request",
                    start_ms=_trace_start_ms, duration_ms=(time.time()*1000 - _trace_start_ms),
                    status="success" if tool_error_count == 0 else "partial",
                    input_preview=query[:500], output_preview=response[:4096],
                    metadata={"processing_time_ms": processing_time_ms, "tool_count": len(tool_calls_log),
                              "skill": skill_name, "model": getattr(self.llm, 'azure_deployment', 'unknown')})
                _span_count += 1
                _model_name = getattr(self.llm, 'azure_deployment', getattr(self.llm, 'model_name', ''))
                _llm_budget = llm_tracker.end_budget()
                _te.end_trace(trace_id=_trace_id, status="success" if tool_error_count == 0 else "partial",
                    skill=skill_name, span_count=_span_count,
                    total_ms=(time.time()*1000 - _trace_start_ms),
                    prompt_tokens=_llm_budget["summary"]["total_prompt_tokens"] if _llm_budget else _prompt_tokens,
                    completion_tokens=_llm_budget["summary"]["total_completion_tokens"] if _llm_budget else _completion_tokens,
                    cost_usd=_llm_budget["summary"]["total_cost_usd"] if _llm_budget else calculate_cost(_model_name, _prompt_tokens, _completion_tokens),
                    metadata={"llm_budget": _llm_budget} if _llm_budget else None)
            except Exception:
                pass
        
        # Restore knowledge retrieval mode if overridden per-request
        if getattr(self, '_prev_kr_mode', None) is not None:
            self.knowledge_retrieval_mode = self._prev_kr_mode
            self._prev_kr_mode = None

        # Restore request-scoped knobs overridden by the harness profile this run
        self._restore_profile_overrides()

        # Clear procedural patterns cache (set in Stage 1, used in Stage 2)
        self._similar_patterns_cache = []

        post_turn_ctx = {
            **self._build_session_ctx(),
            "query": query,
            "input_preview": str(query or "")[:4096],
            "execution_mode": "react",
            "entrypoint": getattr(self, "_entrypoint", "chat"),
            "queue_item_id": getattr(self, "_queue_item_id", "") or "",
            "exec_id": getattr(self, "_queue_exec_id", "") or "",
            "workstream_name": getattr(self, "_mission_workstream", "") or "",
            "mission_item_id": getattr(self, "_mission_item_id", "") or "",
        }
        post_turn_result = self.hook_runner.run_post_turn_result(
            response=response,
            session_ctx=post_turn_ctx,
        )
        if post_turn_result.blocked:
            reason = post_turn_result.reason or "PostTurn policy requires human approval."
            if wants_hitl(post_turn_result) and not self.approval_pending:
                approval = set_hook_approval(
                    self,
                    post_turn_result,
                    session_ctx=post_turn_ctx,
                    skill_name=skill_name,
                    query=query,
                    response=response,
                )
                logger.info(
                    "PostTurn HITL approval requested: %s [context=%s]",
                    reason[:160],
                    approval.get("context") or {},
                )
                response = f"Human approval required: {reason}"
            elif wants_retry(post_turn_result) and not self.approval_pending:
                _appr = post_turn_result.approval if isinstance(post_turn_result.approval, dict) else {}
                self._retry_requested = {
                    "reason": reason,
                    "feedback": post_turn_result.feedback or reason,
                    "max_step_retries": _appr.get("max_step_retries", 1),
                    "on_exhausted": str(_appr.get("on_exhausted", "escalate_to_human")),
                    "approval_payload": build_hook_approval(
                        self, post_turn_result, session_ctx=post_turn_ctx,
                        skill_name=skill_name, query=query, response=response,
                    ),
                }
                logger.info("PostTurn verify-retry requested: %s", reason[:160])
                response = f"Verification failed (will retry): {reason}"
            else:
                response = f"⚠️ Response blocked by compliance policy: {reason}"
        elif post_turn_result.response is not None:
            response = post_turn_result.response

        try:
            self.hook_runner.run_on_turn_end(
                {**self._build_session_ctx(), "query": query, "execution_mode": "react"},
                response=response or "",
            )
        except Exception as _ote_err:  # pragma: no cover - observe-only
            logger.debug("HookRunner [OnTurnEnd] error (non-fatal): %s", _ote_err)

        if return_tool_calls:
            return response, tool_calls_log
        return response
    
    def _build_messages_with_history(self, query: str, max_history: int = 10,
                                       is_confirmation: bool = False,
                                       other_domains: list = None,
                                       search_variants: list = None) -> list:
        """
        Build messages list including recent conversation history.

        DELEGATED to prompt_assembler.build_messages_with_history().
        See that module for implementation details.
        """
        return build_messages_with_history(
            query=query,
            conversation_history=self.conversation_history,
            current_skill=self.current_skill,
            session_summary=self.session_summary,
            pending_action=self.pending_action,
            get_history_path_fn=self._get_history_path,
            max_history=max_history,
            is_confirmation=is_confirmation,
            other_domains=other_domains,
            search_variants=search_variants,
            summary_refs=getattr(self, "session_summary_refs", None),
            summary_pointer=getattr(self, "session_summary_pointer", ""),
        )
    
    
    def export_state(self) -> dict:
        """
        Export serializable state for Redis persistence.
        
        This enables session state to be stored in Redis and restored
        on any server instance, supporting horizontal scaling.
        
        Returns:
            Dictionary containing all serializable state
        """
        pending = None
        if self.pending_action:
            pending = self.pending_action.copy()
            if "timestamp" in pending and hasattr(pending["timestamp"], "isoformat"):
                pending["timestamp"] = pending["timestamp"].isoformat()
        
        return {
            # Identity
            "session_id": self.session_id,
            "user_id": self.user_id,
            
            # Conversation state
            "current_skill": self.current_skill,
            "conversation_history": self.conversation_history.copy(),
            "reasoning_ref": self.reasoning_ref,
            "session_summary": self.session_summary,
            "compaction_count": self.compaction_count,
            "session_summary_refs": list(self.session_summary_refs or []),
            "session_summary_pointer": self.session_summary_pointer,
            "parent_session_id": self.parent_session_id,
            
            # Pending action
            "pending_action": pending,
            "pending_tool_call": self.pending_tool_call,

            # HITL approval checkpoint
            "approval_pending": self.approval_pending,
            
            # Workflow checkpoint (for HITL resume mid-workflow)
            "workflow_checkpoint": getattr(self, '_workflow_checkpoint', None),
            
            # Memory state (short-term only - long-term is file-based)
            "short_term_memory": self.memory.export_short_term() if self.memory else [],
            
            # Settings
            "auto_run": self.auto_run,
        }
    
    def import_state(self, state: dict, preserve_history: bool = False) -> None:
        """
        Import state from Redis snapshot.

        Restores conversation history, pending actions, and memory
        after agent is recreated on a different server.

        Args:
            state: Dictionary from export_state() or AgentStateSnapshot
            preserve_history: Keep the agent's CURRENT conversation_history instead of
                replacing it with the snapshot's. Set this when importing into a LIVE agent —
                e.g. a HITL approval resolved long after the snapshot was taken, where the
                snapshot is stale and replacing would erase every turn since. Leave False
                (the default) when importing into a freshly created agent.
        """
        # Restore conversation state
        self.current_skill = state.get("current_skill")
        _live_history = list(self.conversation_history or [])
        self.conversation_history = state.get("conversation_history", [])
        if preserve_history and _live_history:
            # The live agent has turns the snapshot never saw — they win.
            logger.info("import_state: preserving %d live turn(s) over the snapshot's %d",
                        len(_live_history), len(self.conversation_history or []))
            self.conversation_history = _live_history
        self.reasoning_ref = state.get("reasoning_ref")
        self.session_summary = state.get("session_summary")
        self.compaction_count = state.get("compaction_count", 0)
        self.session_summary_refs = state.get("session_summary_refs") or []
        self.session_summary_pointer = state.get("session_summary_pointer") or ""
        
        # Restore pending action (convert ISO timestamp back to datetime if needed)
        pending = state.get("pending_action")
        if pending:
            pending = pending.copy()
            if "timestamp" in pending and isinstance(pending["timestamp"], str):
                try:
                    pending["timestamp"] = datetime.fromisoformat(pending["timestamp"])
                except (ValueError, TypeError):
                    pending["timestamp"] = datetime.now()
            self.pending_action = pending
        else:
            self.pending_action = None

        # Restore the held tool call (interactive stream-intercept HITL)
        self.pending_tool_call = state.get("pending_tool_call")

        # Restore settings
        self.auto_run = state.get("auto_run", False)
        
        # Restore HITL approval checkpoint
        self.approval_pending = state.get("approval_pending")
        
        # Restore workflow checkpoint (for resuming paused workflows)
        self._workflow_checkpoint = state.get("workflow_checkpoint")
        
        # Restore memory short-term
        short_term = state.get("short_term_memory", [])
        if short_term and self.memory:
            self.memory.import_short_term(short_term)
        
        # Update session_id if different (cross-server restore)
        if state.get("session_id") and state["session_id"] != self.session_id:
            logger.info("Restored session from %s...", state['session_id'][:20])
            # Keep our new session_id - it's tied to our log file
            # Track the loaded conversation as parent (fork semantics)
            self.parent_session_id = state["session_id"]
            # Propagate parent_session_id to memory so log_episode() can record it
            if self.memory:
                self.memory._parent_session_id = self.parent_session_id
        
        turns = len(self.conversation_history)
        logger.info("State imported: %d history turns, skill=%s, pending=%s", turns, self.current_skill, self.pending_action is not None)
    
    def reset_session(self) -> str:
        """
        Start a fresh conversation session.

        Generates a new session_id, clears conversation history and summary,
        but preserves the agent's configuration and skill setup.

        Returns the new session_id for the caller to track.
        """
        old_session_id = self.session_id
        user_prefix = (self.user_id or "anon")[:20]
        uuid_suffix = uuid.uuid4().hex[:6]
        self.session_id = f"{user_prefix}_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid_suffix}"
        self.parent_session_id = None
        self.conversation_history = []
        self.reasoning_ref = None
        self.session_summary = None
        self.compaction_count = 0
        self.pending_action = None
        self.approval_pending = None
        if self.memory:
            self.memory.session_id = self.session_id
            self.memory._parent_session_id = None
        logger.info("Session reset: %s -> %s", old_session_id[:20], self.session_id[:20])
        return self.session_id
    
    def clone_for_session(self, new_session_id: str = None) -> "SkillAgent":
        """
        Create a lightweight clone sharing kernel/router/llm but with fresh session state.

        Used by the per-session agent pool so multiple conversations can
        run in parallel without mutating each other's state.

        Shared (references — zero memory cost):
            kernel, router, loader, llm, light_llm, config, trace_emitter

        Fresh per-session:
            session_id, conversation_history, memory, pending_action, etc.
        """
        clone = object.__new__(SkillAgent)  # Skip __init__ — avoids LLM/router re-creation
        self._ensure_runtime_providers()

        # ── SHARED across all sessions (immutable / stateless) ──
        clone.kernel = self.kernel
        clone.skills_path = self.skills_path
        clone.enterprise_root = getattr(self, "enterprise_root", None)
        clone.user_id = self.user_id
        clone._trace_provider = self._trace_provider
        clone.trace_emitter = self.trace_emitter
        clone._skill_provider = self._skill_provider
        clone._router_provider = self._router_provider
        clone.tool_provider = self.tool_provider
        clone.hook_provider = self.hook_provider
        clone.entitlement_checker = self.entitlement_checker
        clone.entitlement_principal = self.entitlement_principal
        clone.router = self.router
        clone.loader = self.loader
        clone.llm = self.llm
        clone.light_llm = self.light_llm
        clone.config = self.config
        clone.hook_runner = self.hook_runner  # shared — config is per-agent not per-session
        clone.tool_execution_capability = ToolExecutionCapability()
        clone._active_trace_id = ""

        # ── FRESH per-session state ──
        user_prefix = (self.user_id or "anon")[:20]
        uuid_suffix = uuid.uuid4().hex[:6]
        clone.session_id = new_session_id or f"{user_prefix}_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid_suffix}"
        clone.parent_session_id = None
        clone.conversation_history = []
        clone.reasoning_ref = None
        clone._inflight_query = None
        clone.current_skill = None
        clone.agent = None
        clone.agent_config = {"recursion_limit": type(self).RECURSION_LIMIT}
        clone.auto_run = False
        clone.session_summary = None
        clone.compaction_count = 0
        clone.session_summary_refs = []      # provenance belongs to the session, not the template
        clone.session_summary_pointer = ""
        clone._clear_pending_state(clear_approval=True)
        clone._hitl_decision_injected = False
        clone._workflow_checkpoint = None
        clone._last_native_react_turn = {}
        clone._last_decision_context = None
        clone._prev_kr_mode = None
        clone._implicit_fb_warned = False
        clone._sql_write_allowed = False
        clone.render_ui = False
        clone.light_mode = False
        clone.knowledge_retrieval_mode = self.knowledge_retrieval_mode
        # Context loading mode — propagated from template so per-agent config applies
        clone.context_loading_mode = getattr(self, 'context_loading_mode', 'table')
        clone._context_file_path = getattr(self, '_context_file_path', None)
        # RLM tunables (docs_dir/creds_file/budgets) — clone skips __init__, so propagate
        # explicitly or the RLM execution mode loses read_document/http_get (they gate on this).
        clone._rlm_cfg = getattr(self, '_rlm_cfg', {}) or {}
        clone._file_context_block = None  # always start fresh per-session
        # Share the taxonomy index — same object, same background thread, same _nodes list
        clone._taxonomy_index = getattr(self, '_taxonomy_index', None)
        # Sufficiency checker config — propagated from template (config-driven, not session-specific)
        clone.sufficiency_enabled = getattr(self, 'sufficiency_enabled', False)
        clone.sufficiency_auto_complexity = getattr(self, 'sufficiency_auto_complexity', False)
        clone.sufficiency_max_iterations = getattr(self, 'sufficiency_max_iterations', 3)
        clone.sufficiency_threshold = getattr(self, 'sufficiency_threshold', 0.85)
        clone.sufficiency_skip_skills = getattr(self, 'sufficiency_skip_skills', [])
        clone.PENDING_ACTION_TIMEOUT_MINUTES = type(self).PENDING_ACTION_TIMEOUT_MINUTES

        # Fresh memory (unique session_id → unique JSONL file)
        clone.memory = AgentMemory(
            kernel=self.kernel,
            user_id=self.user_id,
            session_id=clone.session_id,
            llm=self.llm,
            light_llm=self.light_llm,
            tenant_id=getattr(self.kernel, 'tenant_id', ''),
            agent_id=getattr(self.kernel, 'agent_id', ''),
        )

        logger.info("Cloned agent for session: %s (from template %s)",
                     clone.session_id[:30], self.session_id[:20])
        return clone
    
    def run_interactive(self):
        """Interactive loop - same as dilo_agent.py main loop."""
        logger.info("=" * 60)
        logger.info("  Skill Agent")
        logger.info("=" * 60)
        logger.info("User: %s", self.user_id or 'anonymous')
        logger.info("Today: %s", datetime.now().strftime('%Y-%m-%d'))
        logger.info("Session: %s", self.session_id)
        logger.info("Skills: %s", [s['name'] for s in self.router.list_skills()])
        logger.info("=" * 60)
        
        logger.info("Ready! Type your messages below.")
        logger.info("Commands: 'quit' to exit, 'history' to show session history")
        logger.info("-" * 60)
        
        while True:
            try:
                user_input = input("\nYou: ").strip()
                
                if not user_input:
                    continue
                
                if user_input.lower() == 'quit':
                    logger.info("Session saved to: %s", self._get_history_path())
                    logger.info("Bye!")
                    break
                
                if user_input.lower() == 'history':
                    logger.info("Session history (%d turns):", len(self.conversation_history))
                    for i, turn in enumerate(self.conversation_history, 1):
                        logger.info("  %d. [%s] %s...", i, turn['skill'], turn['user_input'][:50])
                    continue
                
                # Route with context for smart continuation detection
                last_response = None
                if self.conversation_history:
                    last_response = self.conversation_history[-1].get("response", "")
                
                if self.pending_action:
                    elapsed = (datetime.now() - self.pending_action.get("timestamp", datetime.now())).total_seconds() / 60
                    if elapsed > self.PENDING_ACTION_TIMEOUT_MINUTES:
                        self._clear_pending_state()
                
                routing_info = self.router.match(
                    user_input,
                    current_skill=self.current_skill,
                    last_response=last_response,
                    return_details=True,
                    pending_action=self.pending_action
                )
                skill_name = routing_info["skill"]
                is_confirmation = routing_info.get("is_confirmation", False)
                
                if skill_name != self.current_skill:
                    logger.info("Routing to: %s", skill_name)
                    self.current_skill = skill_name
                    self.agent = self._create_agent(skill_name)
                
                # Build messages with history (inject confirmation context if needed)
                messages = self._build_messages_with_history(user_input, is_confirmation=is_confirmation)
                _log_context_size(messages, skill=skill_name or "")

                result = self._run_with_stream_intercept(messages, self.agent_config)
                if result == "__PENDING__":
                    # Use the shared builder so pending_action is armed identically to the
                    # server path (and a complete pending — never a dangling tool_call).
                    response = self._build_stream_intercept_pending(skill_name)
                    self._log_conversation(user_input, skill_name, [], response)
                    logger.info("Agent: %s", response)
                    continue
                
                # Collect tool calls for logging
                tool_calls_log = []
                for msg in result["messages"]:
                    if hasattr(msg, 'tool_calls') and msg.tool_calls:
                        for tc in msg.tool_calls:
                            cmd = tc.get('args', {}).get('command', '')
                            tool_calls_log.append(cmd)
                            logger.debug("Tool call: %s", cmd[:70])
                
                response = result['messages'][-1].content
                
                # Check for pending approval in tool results (kernel-level confirmation)
                pending_approval = None
                for msg in result["messages"]:
                    if msg.__class__.__name__ == "ToolMessage":
                        content = getattr(msg, 'content', '')
                        if "__PENDING_APPROVAL__" in content:
                            parts = content.split("|")
                            if len(parts) >= 4:
                                pending_approval = {
                                    "operation": parts[1],
                                    "target": parts[2],
                                    "command": parts[3],
                                    "skill": skill_name,
                                    "timestamp": datetime.now()
                                }
                                self.pending_action = pending_approval
                                response = f"⚠️ Confirmation Required: {parts[1]} on {parts[2]}"
                                logger.info("Pending approval: %s on %s", parts[1], parts[2])
                
                if self.pending_action and not pending_approval:
                    logger.info("Pending action executed, clearing")
                    self._clear_pending_state()  # clear BOTH fields — no dangling tool_call
                
                self._log_conversation(user_input, skill_name, tool_calls_log, response)
                
                logger.info("Agent: %s", response)
                
            except KeyboardInterrupt:
                logger.info("Session saved to: %s", self._get_history_path())
                logger.info("Bye!")
                break
    
    def list_skills(self):
        """List available skills."""
        return self.router.list_skills()
