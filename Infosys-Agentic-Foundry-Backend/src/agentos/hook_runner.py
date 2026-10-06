# © 2024-25 Infosys Limited, Bangalore, India. All Rights Reserved.
"""
Hook Runner — Multi-layer lifecycle hooks for IAF Skill Agents.

Eight hook layers, all optional:
  1. **Agent lifecycle** — on_agent_start / on_agent_end / on_agent_error
  2. **Node hooks**      — before_node / after_node  (LangGraph node boundaries)
  3. **Routing hooks**   — before_route / after_route (skill routing decisions)
  4. **LLM hooks**       — before_llm / after_llm    (each LLM invocation)
  5. **Tool hooks**      — pre_hook / post_hook       (individual tool calls)
  6. **PreResponse**     — pre_response  (sync response gate: validate/modify/block)
  7. **PostSampling**    — post_sampling  (async fire-and-forget after response)
  8. **External hooks**  — shell commands configured via YAML (Agent OS compat)

Tool hooks use fnmatch wildcards (e.g. ``"execute_*"``).
All hooks support optional skill-level filtering via ``skills`` parameter.

Config-driven registration (config.yaml / dict):

    hooks:
      pre_hook:
        - pattern: "execute_python_code"
          module: "my_hooks.code_scanner"
          function: "scan_code"
          priority: 10
      pre_response:
        - module: "my_hooks.compliance"
          function: "check_pii"
          priority: 20
      external:
        - event: "PreResponse"
          command: "python3 /hooks/response_compliance.py"
          block_on_nonzero: true

Usage:
    runner = HookRunner()

    @runner.pre_hook("execute_python_code")
    def before_code(tool_name, args):
        if "rm -rf" in args.get("code", ""):
            raise ToolBlockedError("Destructive code blocked")
        return args

    @runner.on_agent_start()
    def start(agent_id, session_id, query, **kw):
        log.info(f"Agent {agent_id} started with: {query[:60]}")

    @runner.pre_response(priority=10)
    def check_pii(response, session_ctx):
        if "SSN" in response:
            return HookResult(blocked=True, reason="PII detected in response")
        return HookResult(blocked=False)
"""

import asyncio
import fnmatch
import importlib
import inspect
import json
import os
import re
import subprocess
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple

try:
    from telemetry_wrapper import logger as log
except ImportError:
    import logging
    log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# HookResult — unified return type for all hook layers
# ---------------------------------------------------------------------------

@dataclass
class HookResult:
    """Unified result protocol for all hook layers.

    Attributes:
        blocked:        If True, the operation is blocked (PreToolUse, PreResponse).
        reason:         Human-readable explanation when blocked or needs_approval.
        response:       PreResponse only — replacement response text.
        feedback:       PostStep only — feedback for manager LLM.
        modified_args:  PreToolUse only — replacement tool args dict.
        needs_approval: If True, the tool call requires human approval (exit code 2).
    """
    blocked: bool = False
    reason: str = ""
    response: Optional[str] = None
    feedback: Optional[str] = None
    modified_args: Optional[Dict[str, Any]] = None
    needs_approval: bool = False


# ---------------------------------------------------------------------------
# ExternalHook — shell command hooks (Agent OS compatible)
# ---------------------------------------------------------------------------

@dataclass
class ExternalHook:
    """A shell command hook loaded from config.

    Scripts receive context via IAF_* environment variables and communicate
    back via exit codes + JSON stdout.
    """
    event: str              # "PreToolUse"|"PostToolUse"|"PreResponse"|"PostSampling"|"OnAgentStart"|"OnAgentEnd"|"OnAgentError"
    command: str            # Shell command executed via subprocess
    matcher: str = ".*"     # Regex matched against tool_name
    skills: List[str] = field(default_factory=list)
    block_on_nonzero: bool = False
    timeout_seconds: int = 10
    hook_id: Optional[str] = None   # If loaded from Hook Repository
    _matcher_re: object = field(default=None, repr=False, compare=False)

    def __post_init__(self):
        # Normalize common UI-friendly values to valid regex
        _raw = self.matcher.strip() if self.matcher else ""
        if _raw in ("", "*", "all", "All", "ALL"):
            self.matcher = ".*"
        try:
            self._matcher_re = re.compile(self.matcher, re.IGNORECASE)
        except re.error:
            log.warning(f"[HookRunner] Invalid matcher regex {self.matcher!r} — using '.*'")
            self._matcher_re = re.compile(".*")


class ToolBlockedError(Exception):
    """Raised by pre-hooks to prevent tool execution."""
    pass


class HookRunner:
    """
    Multi-layer lifecycle hook manager for IAF Skill Agents.

    Eight layers:
      1. Agent lifecycle  — on_agent_start / on_agent_end / on_agent_error
      2. Node hooks       — before_node / after_node
      3. Routing hooks    — before_route / after_route
      4. LLM hooks        — before_llm / after_llm
      5. Tool hooks       — pre_hook / post_hook  (fnmatch pattern matched)
      6. PreResponse      — pre_response  (sync response gate)
      7. PostSampling     — post_sampling  (async fire-and-forget)
      8. External hooks   — shell commands (Agent OS compatible)

    All hooks support:
      - Priority ordering (lower = runs first)
      - Skill-level filtering via ``skills`` parameter
      - Both sync and async variants (``run_*`` and ``arun_*``)

    Config-driven registration:
      Pass a hooks_config dict to load_from_config() to register hooks
      from YAML/dict without touching Python source code.
    """

    _DEFAULT_PRIORITY = 100

    def __init__(self):
        # Layer 5: Tool hooks  — (priority, pattern, fn, skills)
        self._pre_hooks: List[Tuple[int, str, Callable, List[str]]] = []
        self._post_hooks: List[Tuple[int, str, Callable, List[str]]] = []
        # Layer 1: Agent lifecycle — (priority, fn, skills)
        self._on_agent_start: List[Tuple[int, Callable, List[str]]] = []
        self._on_agent_end: List[Tuple[int, Callable, List[str]]] = []
        self._on_agent_error: List[Tuple[int, Callable, List[str]]] = []
        # Layer 2: Node hooks — (priority, fn, skills)
        self._before_node: List[Tuple[int, Callable, List[str]]] = []
        self._after_node: List[Tuple[int, Callable, List[str]]] = []
        # Layer 3: Routing hooks — (priority, fn, skills)
        self._before_route: List[Tuple[int, Callable, List[str]]] = []
        self._after_route: List[Tuple[int, Callable, List[str]]] = []
        # Layer 4: LLM hooks — (priority, fn, skills)
        self._before_llm: List[Tuple[int, Callable, List[str]]] = []
        self._after_llm: List[Tuple[int, Callable, List[str]]] = []
        # Layer 6: PreResponse — (priority, fn, skills)
        self._pre_response: List[Tuple[int, Callable, List[str]]] = []
        # Layer 7: PostSampling — (priority, fn, skills)
        self._post_sampling: List[Tuple[int, Callable, List[str]]] = []
        # Layer 8: External hooks (shell commands)
        self._external_hooks: List[ExternalHook] = []
        # Current skill context (set per-request)
        self._current_skill: str = ""

    # ------------------------------------------------------------------
    # Skill context
    # ------------------------------------------------------------------

    def set_current_skill(self, skill_name: str):
        """Set the current skill context for skill-level filtering."""
        self._current_skill = (skill_name or "").lower()

    def load_skill_hooks(self, skill_hooks_config: dict) -> int:
        """Load skill-level hooks from a skill's frontmatter hooks dict.

        This is called after routing determines the active skill.  The hooks
        are registered with an automatic ``skills`` filter so they only fire
        for the current skill.

        Args:
            skill_hooks_config: The ``hooks`` dict from SKILL.md frontmatter.
                Same format as the agent-level config.yaml ``hooks`` section.

        Returns:
            Number of hooks loaded.
        """
        if not skill_hooks_config:
            return 0
        skill_name = self._current_skill
        log.info(f"[HookRunner] Loading skill-level hooks for '{skill_name}': {list(skill_hooks_config.keys())}")
        loaded = self.load_from_config(skill_hooks_config)
        log.info(f"[HookRunner] Loaded {loaded} skill-level hook(s) for '{skill_name}'")
        return loaded

    def load_global_hooks(self, department: str) -> int:
        """Auto-load global hooks for a department from the Hook Repository.

        Global hooks (scope='global') fire automatically for ALL agents
        in the department without requiring per-agent binding. They support
        lifecycle events: OnAgentStart, OnAgentEnd, OnAgentError, PostSampling.

        This is called once during ``_build_chains`` so the hooks are
        registered before the first inference node runs.

        Args:
            department: The department to load global hooks for.

        Returns:
            Number of global hooks loaded.
        """
        try:
            from src.agentos.hook_repository import get_hook_repository
            repo = get_hook_repository()
            global_hooks = repo.list_global_hooks(department)
        except Exception as e:
            log.debug(f"[HookRunner] Could not load global hooks for '{department}': {e}")
            return 0

        if not global_hooks:
            return 0

        loaded = 0
        for meta in global_hooks:
            hook_id = meta.get("hook_id", "")
            event = meta.get("event", "")
            if not event:
                continue

            try:
                hook_path = repo.get_hook_path(hook_id)
                if not hook_path:
                    log.warning(f"[HookRunner] Global hook {hook_id} script not found — skipping")
                    continue

                import sys
                command = f"{sys.executable} {hook_path}"
                self.add_external_hook(ExternalHook(
                    event=event,
                    command=command,
                    matcher=".*",
                    skills=[],          # Empty = all skills
                    block_on_nonzero=(event in ("OnAgentStart",)),  # Only OnAgentStart can block
                    timeout_seconds=10,
                    hook_id=hook_id,
                ))
                loaded += 1
                log.info(
                    f"[HookRunner] Global hook '{meta.get('name', hook_id)}' "
                    f"({hook_id}) loaded for event={event} dept={department}"
                )
            except Exception as e:
                log.warning(f"[HookRunner] Failed to load global hook {hook_id}: {e}")

        if loaded:
            log.info(f"[HookRunner] Loaded {loaded} global hook(s) for department '{department}'")
        return loaded

    @staticmethod
    def _skill_matches(hook_skills: List[str], current_skill: str) -> bool:
        """Check if current skill is in the hook's skill filter.
        Empty list = all skills (no filter)."""
        if not hook_skills:
            return True
        return current_skill.lower() in [s.lower() for s in hook_skills]

    # ------------------------------------------------------------------
    # Internal: invoke a hook (sync or async)
    # ------------------------------------------------------------------

    @staticmethod
    async def _call_hook(fn: Callable, *args, **kwargs):
        """Call *fn* regardless of whether it is sync or async.

        Fix #15 — also handles callable objects with async __call__.
        """
        if asyncio.iscoroutinefunction(fn):
            return await fn(*args, **kwargs)
        result = fn(*args, **kwargs)
        # Handle callable objects that return a coroutine (async __call__)
        if asyncio.iscoroutine(result):
            result = await result
        return result

    @staticmethod
    def _call_hook_sync(fn: Callable, label: str, *args, **kwargs):
        """Call *fn* from a synchronous context.  Async hooks are skipped
        with a warning (use ``arun_*`` instead)."""
        if asyncio.iscoroutinefunction(fn):
            log.warning(f"[HookRunner] Skipping async hook in sync {label}; use arun_* instead")
            return None
        return fn(*args, **kwargs)

    # ==================================================================
    # Layer 5: Tool Hooks (with skill filtering)
    # ==================================================================

    def pre_hook(self, tool_pattern: str = "*", priority: int = _DEFAULT_PRIORITY, skills: Optional[List[str]] = None):
        """Decorator to register a pre-hook for matching tool names.

        Lower *priority* values execute first (e.g. security=10, logging=50).
        *skills* — optional list of skill names this hook fires for (empty = all).
        """
        def decorator(fn: Callable):
            self._pre_hooks.append((priority, tool_pattern, fn, skills or []))
            self._pre_hooks.sort(key=lambda t: t[0])
            return fn
        return decorator

    def post_hook(self, tool_pattern: str = "*", priority: int = _DEFAULT_PRIORITY, skills: Optional[List[str]] = None):
        """Decorator to register a post-hook for matching tool names."""
        def decorator(fn: Callable):
            self._post_hooks.append((priority, tool_pattern, fn, skills or []))
            self._post_hooks.sort(key=lambda t: t[0])
            return fn
        return decorator

    def add_pre_hook(self, pattern: str, fn: Callable, priority: int = _DEFAULT_PRIORITY, skills: Optional[List[str]] = None):
        """Programmatic pre-hook registration."""
        self._pre_hooks.append((priority, pattern, fn, skills or []))
        self._pre_hooks.sort(key=lambda t: t[0])

    def add_post_hook(self, pattern: str, fn: Callable, priority: int = _DEFAULT_PRIORITY, skills: Optional[List[str]] = None):
        """Programmatic post-hook registration."""
        self._post_hooks.append((priority, pattern, fn, skills or []))
        self._post_hooks.sort(key=lambda t: t[0])

    def run_pre_hooks(self, tool_name: str, args: Dict[str, Any]) -> Dict[str, Any]:
        """Run all matching pre-hooks in priority order. Returns (possibly modified) args."""
        current_args = args
        # Fix #14 — iterate over a snapshot to avoid corruption if hooks mutate the list
        for _pri, pattern, fn, skills in list(self._pre_hooks):
            if not fnmatch.fnmatch(tool_name, pattern):
                continue
            if not self._skill_matches(skills, self._current_skill):
                continue
            try:
                result = fn(tool_name, current_args)
                if isinstance(result, HookResult):
                    if result.blocked:
                        raise ToolBlockedError(result.reason or f"Hook blocked {tool_name}")
                    if result.modified_args:
                        current_args = result.modified_args
                elif isinstance(result, dict):
                    current_args = result
            except ToolBlockedError:
                raise
            except Exception as e:
                log.warning(f"[HookRunner] Pre-hook error for {tool_name}: {e}")
        return current_args

    def run_post_hooks(
        self, tool_name: str, args: Dict[str, Any],
        result: Any, duration_ms: float,
    ) -> Any:
        """Run all matching post-hooks in priority order. Returns (possibly modified) result."""
        current_result = result
        for _pri, pattern, fn, skills in self._post_hooks:
            if not fnmatch.fnmatch(tool_name, pattern):
                continue
            if not self._skill_matches(skills, self._current_skill):
                continue
            try:
                modified = fn(tool_name, args, current_result, duration_ms)
                if modified is not None:
                    current_result = modified
            except Exception as e:
                log.warning(f"[HookRunner] Post-hook error for {tool_name}: {e}")
        return current_result

    # ==================================================================
    # Layer 1: Agent Lifecycle Hooks (with skill filtering)
    # ==================================================================

    def _sorted_insert(self, hook_list, entry):
        """Insert *entry* keeping the list sorted by priority (first element)."""
        hook_list.append(entry)
        hook_list.sort(key=lambda t: t[0])

    def on_agent_start(self, priority: int = _DEFAULT_PRIORITY, skills: Optional[List[str]] = None):
        """Decorator: fn(agent_id, session_id, query, **context)"""
        def decorator(fn: Callable):
            self._sorted_insert(self._on_agent_start, (priority, fn, skills or []))
            return fn
        return decorator

    def on_agent_end(self, priority: int = _DEFAULT_PRIORITY, skills: Optional[List[str]] = None):
        """Decorator: fn(agent_id, session_id, response, duration_ms, **context)"""
        def decorator(fn: Callable):
            self._sorted_insert(self._on_agent_end, (priority, fn, skills or []))
            return fn
        return decorator

    def on_agent_error(self, priority: int = _DEFAULT_PRIORITY, skills: Optional[List[str]] = None):
        """Decorator: fn(agent_id, session_id, error, **context)"""
        def decorator(fn: Callable):
            self._sorted_insert(self._on_agent_error, (priority, fn, skills or []))
            return fn
        return decorator

    def run_on_agent_start(self, agent_id: str, session_id: str, query: str, **ctx) -> HookResult:
        """Run internal + external OnAgentStart hooks.

        Returns HookResult. If blocked=True, the agent should reject the query.
        If needs_approval=True, the agent should request human approval before proceeding.
        """
        for _pri, fn, skills in list(self._on_agent_start):
            if not self._skill_matches(skills, self._current_skill):
                continue
            try:
                fn(agent_id=agent_id, session_id=session_id, query=query, **ctx)
            except Exception as e:
                log.warning(f"[HookRunner] on_agent_start error: {e}")

        # Fire external OnAgentStart hooks
        session_ctx = {
            "session_id": session_id,
            "agentic_application_id": agent_id,
            "query": query,
            **ctx,
        }
        for hook in self._external_hooks:
            if hook.event != "OnAgentStart":
                continue
            if not self._skill_matches(hook.skills, self._current_skill):
                continue
            result = self._run_external_hook(hook, {
                "IAF_HOOK_EVENT": "OnAgentStart",
                "IAF_TOOL_NAME": "",
                "IAF_TOOL_INPUT": "",
                **self._build_session_env(session_ctx),
            })
            if result.blocked or result.needs_approval:
                return result
        return HookResult(blocked=False)

    def run_on_agent_end(self, agent_id: str, session_id: str, response: str, duration_ms: float, **ctx):
        """Run internal + external OnAgentEnd hooks (fire-and-forget for external)."""
        for _pri, fn, skills in list(self._on_agent_end):
            if not self._skill_matches(skills, self._current_skill):
                continue
            try:
                fn(agent_id=agent_id, session_id=session_id, response=response, duration_ms=duration_ms, **ctx)
            except Exception as e:
                log.warning(f"[HookRunner] on_agent_end error: {e}")

        # Fire external OnAgentEnd hooks in background thread
        _has_ext = any(
            h.event == "OnAgentEnd" and self._skill_matches(h.skills, self._current_skill)
            for h in self._external_hooks
        )
        if _has_ext:
            _skill_snapshot = self._current_skill
            session_ctx = {
                "session_id": session_id,
                "agentic_application_id": agent_id,
                "query": ctx.get("query", ""),
            }

            def _fire():
                for hook in self._external_hooks:
                    if hook.event != "OnAgentEnd":
                        continue
                    if not self._skill_matches(hook.skills, _skill_snapshot):
                        continue
                    self._run_external_hook(hook, {
                        "IAF_HOOK_EVENT": "OnAgentEnd",
                        "IAF_TOOL_NAME": "",
                        "IAF_TOOL_INPUT": "",
                        "IAF_RESPONSE": str(response)[:4096],
                        "IAF_DURATION_MS": str(int(duration_ms)),
                        **self._build_session_env(session_ctx),
                    })

            threading.Thread(target=_fire, daemon=True, name="hook-on-agent-end").start()

    def run_on_agent_error(self, agent_id: str, session_id: str, error: Exception, **ctx) -> HookResult:
        """Run internal + external OnAgentError hooks.

        Returns HookResult. If result.response is set, it contains a fallback
        response from the external hook's stdout.
        """
        for _pri, fn, skills in list(self._on_agent_error):
            if not self._skill_matches(skills, self._current_skill):
                continue
            try:
                fn(agent_id=agent_id, session_id=session_id, error=error, **ctx)
            except Exception as e:
                log.warning(f"[HookRunner] on_agent_error error: {e}")

        # Fire external OnAgentError hooks
        session_ctx = {
            "session_id": session_id,
            "agentic_application_id": agent_id,
            "query": ctx.get("query", ""),
        }
        for hook in self._external_hooks:
            if hook.event != "OnAgentError":
                continue
            if not self._skill_matches(hook.skills, self._current_skill):
                continue
            result = self._run_external_hook(hook, {
                "IAF_HOOK_EVENT": "OnAgentError",
                "IAF_TOOL_NAME": "",
                "IAF_TOOL_INPUT": "",
                "IAF_ERROR": str(error)[:4096],
                **self._build_session_env(session_ctx),
            })
            # If the error hook produced a response (exit 0 + stdout), treat as fallback response
            if result.response:
                return result
        return HookResult(blocked=False)

    # ==================================================================
    # Layer 2: Node Hooks (with skill filtering)
    # ==================================================================

    def before_node(self, priority: int = _DEFAULT_PRIORITY, skills: Optional[List[str]] = None):
        """Decorator: fn(node_name, state, **context)"""
        def decorator(fn: Callable):
            self._sorted_insert(self._before_node, (priority, fn, skills or []))
            return fn
        return decorator

    def after_node(self, priority: int = _DEFAULT_PRIORITY, skills: Optional[List[str]] = None):
        """Decorator: fn(node_name, state, result, duration_ms, **context)"""
        def decorator(fn: Callable):
            self._sorted_insert(self._after_node, (priority, fn, skills or []))
            return fn
        return decorator

    def run_before_node(self, node_name: str, state: dict, **ctx):
        for _pri, fn, skills in list(self._before_node):
            if not self._skill_matches(skills, self._current_skill):
                continue
            try:
                fn(node_name=node_name, state=state, **ctx)
            except Exception as e:
                log.warning(f"[HookRunner] before_node({node_name}) error: {e}")

    def run_after_node(self, node_name: str, state: dict, result: Any, duration_ms: float, **ctx):
        for _pri, fn, skills in list(self._after_node):
            if not self._skill_matches(skills, self._current_skill):
                continue
            try:
                fn(node_name=node_name, state=state, result=result, duration_ms=duration_ms, **ctx)
            except Exception as e:
                log.warning(f"[HookRunner] after_node({node_name}) error: {e}")

    # ==================================================================
    # Layer 3: Routing Hooks (with skill filtering)
    # ==================================================================

    def before_route(self, priority: int = _DEFAULT_PRIORITY, skills: Optional[List[str]] = None):
        """Decorator: fn(query, agent_id, **context)"""
        def decorator(fn: Callable):
            self._sorted_insert(self._before_route, (priority, fn, skills or []))
            return fn
        return decorator

    def after_route(self, priority: int = _DEFAULT_PRIORITY, skills: Optional[List[str]] = None):
        """Decorator: fn(query, skill_name, method, confidence, **context)"""
        def decorator(fn: Callable):
            self._sorted_insert(self._after_route, (priority, fn, skills or []))
            return fn
        return decorator

    def run_before_route(self, query: str, agent_id: str, **ctx):
        for _pri, fn, skills in list(self._before_route):
            if not self._skill_matches(skills, self._current_skill):
                continue
            try:
                fn(query=query, agent_id=agent_id, **ctx)
            except Exception as e:
                log.warning(f"[HookRunner] before_route error: {e}")

    def run_after_route(self, query: str, skill_name: str, method: str, confidence: float, **ctx):
        for _pri, fn, skills in list(self._after_route):
            if not self._skill_matches(skills, self._current_skill):
                continue
            try:
                fn(query=query, skill_name=skill_name, method=method, confidence=confidence, **ctx)
            except Exception as e:
                log.warning(f"[HookRunner] after_route error: {e}")

    # ==================================================================
    # Layer 4: LLM Hooks (with skill filtering)
    # ==================================================================

    def before_llm(self, priority: int = _DEFAULT_PRIORITY, skills: Optional[List[str]] = None):
        """Decorator: fn(messages, iteration, **context). Can modify messages in-place."""
        def decorator(fn: Callable):
            self._sorted_insert(self._before_llm, (priority, fn, skills or []))
            return fn
        return decorator

    def after_llm(self, priority: int = _DEFAULT_PRIORITY, skills: Optional[List[str]] = None):
        """Decorator: fn(messages, ai_response, iteration, duration_ms, **context)"""
        def decorator(fn: Callable):
            self._sorted_insert(self._after_llm, (priority, fn, skills or []))
            return fn
        return decorator

    def run_before_llm(self, messages: list, iteration: int, **ctx):
        for _pri, fn, skills in list(self._before_llm):
            if not self._skill_matches(skills, self._current_skill):
                continue
            try:
                fn(messages=messages, iteration=iteration, **ctx)
            except Exception as e:
                log.warning(f"[HookRunner] before_llm error: {e}")

    def run_after_llm(self, messages: list, ai_response: Any, iteration: int, duration_ms: float, **ctx):
        for _pri, fn, skills in list(self._after_llm):
            if not self._skill_matches(skills, self._current_skill):
                continue
            try:
                fn(messages=messages, ai_response=ai_response, iteration=iteration, duration_ms=duration_ms, **ctx)
            except Exception as e:
                log.warning(f"[HookRunner] after_llm error: {e}")

    # ==================================================================
    # Layer 6: PreResponse — Synchronous Response Gate
    # ==================================================================

    def pre_response(self, priority: int = _DEFAULT_PRIORITY, skills: Optional[List[str]] = None):
        """Decorator: fn(response, session_ctx) -> HookResult or str or None.

        PreResponse fires AFTER the LLM produces a final response but BEFORE
        it's sent to the user. It can:
          - Block: return HookResult(blocked=True, reason="...")
          - Modify: return HookResult(response="new response")
          - Pass through: return HookResult(blocked=False) or None
        """
        def decorator(fn: Callable):
            self._sorted_insert(self._pre_response, (priority, fn, skills or []))
            return fn
        return decorator

    def add_pre_response(self, fn: Callable, priority: int = _DEFAULT_PRIORITY, skills: Optional[List[str]] = None):
        """Programmatic PreResponse hook registration."""
        self._sorted_insert(self._pre_response, (priority, fn, skills or []))

    def run_pre_response(self, response: str, session_ctx: Optional[dict] = None) -> str:
        """Fire all PreResponse hooks synchronously.

        Returns the (possibly modified) response string.
        If a hook returns blocked=True, returns a compliance error message.
        """
        current_response = response
        ctx = session_ctx or {}

        # Internal Python hooks
        for _pri, fn, skills in list(self._pre_response):
            if not self._skill_matches(skills, self._current_skill):
                continue
            try:
                result = fn(current_response, ctx)
                if isinstance(result, HookResult):
                    if result.blocked:
                        log.info(f"[HookRunner] PreResponse blocked: {result.reason[:80]}")
                        return f"⚠️ Response blocked by compliance policy: {result.reason}"
                    if result.response is not None:
                        current_response = result.response
                elif isinstance(result, str):
                    current_response = result
            except Exception as e:
                log.warning(f"[HookRunner] pre_response error: {e}")

        # External hooks (PreResponse event)
        for hook in self._external_hooks:
            if hook.event != "PreResponse":
                continue
            if not self._skill_matches(hook.skills, self._current_skill):
                continue
            ext_result = self._run_external_hook(hook, {
                "IAF_HOOK_EVENT": "PreResponse",
                "IAF_RESPONSE": current_response[:4096],
                **self._build_session_env(ctx),
            })
            if ext_result.blocked:
                log.info(f"[HookRunner] External PreResponse blocked: {ext_result.reason[:80]}")
                return f"⚠️ Response blocked by compliance policy: {ext_result.reason}"
            if ext_result.response is not None:
                current_response = ext_result.response

        return current_response

    # ==================================================================
    # Layer 7: PostSampling — Async Fire-and-Forget
    # ==================================================================

    def post_sampling(self, priority: int = _DEFAULT_PRIORITY, skills: Optional[List[str]] = None):
        """Decorator: fn(session_ctx) -> None.

        PostSampling fires in a daemon thread AFTER the response is sent.
        Used for non-blocking side effects: logging, notifications, analytics.
        """
        def decorator(fn: Callable):
            self._sorted_insert(self._post_sampling, (priority, fn, skills or []))
            return fn
        return decorator

    def add_post_sampling(self, fn: Callable, priority: int = _DEFAULT_PRIORITY, skills: Optional[List[str]] = None):
        """Programmatic PostSampling hook registration."""
        self._sorted_insert(self._post_sampling, (priority, fn, skills or []))

    def run_post_sampling(self, session_ctx: dict) -> None:
        """Fire all PostSampling hooks in a daemon thread (fire-and-forget).

        Never blocks. Returns immediately.
        """
        has_internal = any(
            self._skill_matches(skills, self._current_skill)
            for _pri, fn, skills in self._post_sampling
        )
        has_external = any(
            h.event == "PostSampling" and self._skill_matches(h.skills, self._current_skill)
            for h in self._external_hooks
        )
        if not has_internal and not has_external:
            return  # Fast path: no hooks, skip thread creation

        # Snapshot current skill so the daemon thread has correct context
        _skill_snapshot = self._current_skill

        def _fire():
            for _pri, fn, skills in list(self._post_sampling):
                if not self._skill_matches(skills, _skill_snapshot):
                    continue
                try:
                    fn(session_ctx)
                except Exception as e:
                    log.warning(f"[HookRunner] post_sampling error: {e}")

            for hook in self._external_hooks:
                if hook.event != "PostSampling":
                    continue
                if not self._skill_matches(hook.skills, _skill_snapshot):
                    continue
                self._run_external_hook(hook, {
                    "IAF_HOOK_EVENT": "PostSampling",
                    "IAF_RESPONSE": str(session_ctx.get("response", ""))[:4096],
                    **self._build_session_env(session_ctx),
                })

        threading.Thread(target=_fire, daemon=True, name="hook-post-sampling").start()

    # ==================================================================
    # Layer 8: External Shell Hooks (Agent OS compatible)
    # ==================================================================

    def add_external_hook(self, hook: ExternalHook):
        """Register an external shell command hook."""
        self._external_hooks.append(hook)
        log.debug(f"[HookRunner] External hook registered: [{hook.event}] {hook.command[:60]}")

    @staticmethod
    def _build_session_env(session_ctx: dict) -> dict:
        """Build IAF_* env var dict from session context."""
        ctx = session_ctx or {}
        return {
            "IAF_SESSION_ID": str(ctx.get("session_id", "")),
            "IAF_AGENT_ID": str(ctx.get("agent_id", ctx.get("agentic_application_id", ""))),
            "IAF_TENANT_ID": str(ctx.get("tenant_id", "")),
            "IAF_SKILL_NAME": str(ctx.get("skill_name", "")),
            "IAF_USER_ID": str(ctx.get("user_id", "")),
            "IAF_QUERY": str(ctx.get("query", ""))[:4096],
        }

    @staticmethod
    def _run_external_hook(hook: ExternalHook, env_vars: dict) -> HookResult:
        """Execute one external shell command hook and return a HookResult."""
        env = os.environ.copy()
        env.update(env_vars)
        try:
            proc = subprocess.run(
                hook.command,
                shell=True,
                env=env,
                capture_output=True,
                text=True,
                timeout=hook.timeout_seconds,
            )

            # Exit code 2 → approval required (PreToolUse / PostToolUse)
            if proc.returncode == 2:
                reason = _parse_hook_output(proc.stdout, proc.stderr) or "Hook requires human approval"
                log.info(f"[HookRunner] External [{hook.event}]: approval required (exit 2) — {reason[:120]}")
                return HookResult(needs_approval=True, reason=reason)

            if proc.returncode != 0:
                if hook.block_on_nonzero:
                    reason = _parse_hook_output(proc.stdout, proc.stderr)
                    log.info(f"[HookRunner] External [{hook.event}]: blocked (exit {proc.returncode}) — {reason[:120]}")
                    return HookResult(blocked=True, reason=reason)
                log.debug(f"[HookRunner] External [{hook.event}]: exit {proc.returncode} (non-blocking)")
                return HookResult(blocked=False)

            # PreResponse / OnAgentError: non-empty stdout on exit 0 → replacement/fallback response
            if hook.event in ("PreResponse", "OnAgentError") and proc.stdout.strip():
                return HookResult(blocked=False, response=proc.stdout.strip())

            return HookResult(blocked=False)

        except subprocess.TimeoutExpired:
            log.warning(f"[HookRunner] External [{hook.event}]: timed out after {hook.timeout_seconds}s — continuing")
            return HookResult(blocked=False)
        except Exception as exc:
            log.warning(f"[HookRunner] External [{hook.event}]: exec error — {exc}")
            return HookResult(blocked=False)

    def run_external_pre_tool(self, tool_name: str, tool_args: dict, session_ctx: dict) -> HookResult:
        """Fire external PreToolUse hooks for a tool call."""
        for hook in self._external_hooks:
            if hook.event != "PreToolUse":
                continue
            if not self._skill_matches(hook.skills, self._current_skill):
                continue
            if hook._matcher_re and not hook._matcher_re.search(tool_name):
                continue
            result = self._run_external_hook(hook, {
                "IAF_HOOK_EVENT": "PreToolUse",
                "IAF_TOOL_NAME": tool_name,
                "IAF_TOOL_INPUT": json.dumps(tool_args) if isinstance(tool_args, dict) else str(tool_args),
                **self._build_session_env(session_ctx),
            })
            if result.blocked or result.needs_approval:
                return result
        return HookResult(blocked=False)

    def run_external_post_tool(self, tool_name: str, tool_args: dict, tool_output: str, session_ctx: dict) -> HookResult:
        """Fire external PostToolUse hooks synchronously.

        Runs AFTER the tool executes but BEFORE the result reaches the LLM.
        Supports the same exit-code semantics as PreToolUse:
          - 0: ALLOW  — tool output passes to LLM as-is
          - 1: BLOCK  — tool output replaced with blocked message (if block_on_nonzero)
          - 2: APPROVAL_REQUIRED — pause for human review of tool output
        """
        for hook in self._external_hooks:
            if hook.event != "PostToolUse":
                continue
            if not self._skill_matches(hook.skills, self._current_skill):
                continue
            if hook._matcher_re and not hook._matcher_re.search(tool_name):
                continue
            result = self._run_external_hook(hook, {
                "IAF_HOOK_EVENT": "PostToolUse",
                "IAF_TOOL_NAME": tool_name,
                "IAF_TOOL_INPUT": json.dumps(tool_args) if isinstance(tool_args, dict) else str(tool_args),
                "IAF_TOOL_OUTPUT": str(tool_output)[:4096],
                **self._build_session_env(session_ctx),
            })
            if result.blocked or result.needs_approval:
                return result
        return HookResult(blocked=False)

    # ==================================================================
    # Config-driven hook loading
    # ==================================================================

    def load_from_config(self, hooks_config: dict) -> int:
        """Load hooks from a config dict (typically from YAML config file).

        Supports three sections:
          - Event-keyed Python hooks (e.g. ``pre_hook``, ``pre_response``):
            Each entry has ``module``, ``function``, optional ``pattern``,
            ``priority``, ``skills``, ``block``.
          - ``external``: Shell command hooks (Agent OS compatible)

        External hooks can specify either ``command`` (shell command) or
        ``hook_id`` (resolved from Hook Repository).  Events supported:
        ``PreToolUse``, ``PostToolUse``, ``PreResponse``, ``PostSampling``,
        ``OnAgentStart``, ``OnAgentEnd``, ``OnAgentError``.

        Exit code semantics:
          - 0: ALLOW (continue)
          - 1: BLOCK (if block_on_nonzero=True)
          - 2: APPROVAL_REQUIRED (triggers HITL approval)

        Returns the number of hooks loaded.

        Config format::

            hooks:
              pre_hook:
                - pattern: "execute_python_code"
                  module: "my_hooks.code_scanner"
                  function: "scan_code"
                  priority: 10
                  skills: ["data_analysis"]
              pre_response:
                - module: "my_hooks.compliance"
                  function: "check_pii"
                  priority: 20
              external:
                - event: "PreToolUse"
                  command: "python3 /hooks/audit_sql.py"
                  matcher: "run_sql_query"
                  block_on_nonzero: true
                  skills: ["invoice_processing"]
                - event: "PreToolUse"
                  hook_id: "hk_abc123def456"
                  matcher: "run_shell_command"
                  block_on_nonzero: true
                - event: "OnAgentStart"
                  hook_id: "hk_789ghi012jkl"
                  block_on_nonzero: true
        """
        if not hooks_config:
            return 0

        loaded = 0

        # Map config keys to registration methods
        _PYTHON_HOOK_MAP = {
            "pre_hook": self._load_python_tool_hook,
            "post_hook": self._load_python_tool_hook,
            "on_agent_start": self._load_python_lifecycle_hook,
            "on_agent_end": self._load_python_lifecycle_hook,
            "on_agent_error": self._load_python_lifecycle_hook,
            "before_node": self._load_python_lifecycle_hook,
            "after_node": self._load_python_lifecycle_hook,
            "before_route": self._load_python_lifecycle_hook,
            "after_route": self._load_python_lifecycle_hook,
            "before_llm": self._load_python_lifecycle_hook,
            "after_llm": self._load_python_lifecycle_hook,
            "pre_response": self._load_python_lifecycle_hook,
            "post_turn": self._load_python_lifecycle_hook,  # backward compat alias
            "post_sampling": self._load_python_lifecycle_hook,
        }

        for section_key, entries in hooks_config.items():
            if section_key == "external":
                # External shell hooks
                if not isinstance(entries, list):
                    log.warning(f"[HookRunner] Config hooks.external must be a list — skipping")
                    continue
                for entry in entries:
                    if not isinstance(entry, dict):
                        log.warning(f"[HookRunner] Malformed external hook entry — skipping: {entry!r}")
                        continue

                    # Resolve command: either explicit 'command' or via 'hook_id' from Hook Repository
                    resolved_command = entry.get("command")
                    resolved_hook_id = entry.get("hook_id")

                    if not resolved_command and resolved_hook_id:
                        # Resolve hook_id → file path via Hook Repository
                        try:
                            from src.agentos.hook_repository import get_hook_repository
                            repo = get_hook_repository()
                            hook_path = repo.get_hook_path(resolved_hook_id)
                            if hook_path:
                                resolved_command = f"python \"{hook_path}\""
                                log.info(f"[HookRunner] Resolved hook_id={resolved_hook_id} → {hook_path}")
                            else:
                                log.warning(f"[HookRunner] hook_id={resolved_hook_id} not found in repository — skipping")
                                continue
                        except Exception as e:
                            log.warning(f"[HookRunner] Failed to resolve hook_id={resolved_hook_id}: {e}")
                            continue
                    elif not resolved_command:
                        log.warning(f"[HookRunner] External hook entry needs 'command' or 'hook_id' — skipping: {entry!r}")
                        continue

                    _skills = entry.get("skills", [])
                    if isinstance(_skills, str):
                        _skills = [_skills]
                    self.add_external_hook(ExternalHook(
                        event=str(entry.get("event", "PostToolUse")),
                        command=str(resolved_command),
                        matcher=str(entry.get("matcher", ".*")),
                        skills=[str(s) for s in _skills],
                        block_on_nonzero=bool(entry.get("block_on_nonzero", False)),
                        timeout_seconds=int(entry.get("timeout_seconds", 10)),
                        hook_id=resolved_hook_id,
                    ))
                    loaded += 1
            elif section_key in _PYTHON_HOOK_MAP:
                if not isinstance(entries, list):
                    log.warning(f"[HookRunner] Config hooks.{section_key} must be a list — skipping")
                    continue
                for entry in entries:
                    if not isinstance(entry, dict):
                        continue
                    try:
                        _PYTHON_HOOK_MAP[section_key](section_key, entry)
                        loaded += 1
                    except Exception as e:
                        log.warning(f"[HookRunner] Failed to load hook [{section_key}]: {e}")
            else:
                log.debug(f"[HookRunner] Unknown config section 'hooks.{section_key}' — skipping")

        if loaded:
            log.info(f"[HookRunner] Config loaded {loaded} hook(s)")
        return loaded

    def _load_python_module_fn(self, entry: dict) -> Callable:
        """Import a Python callable from module + function config entry."""
        module_path = entry.get("module", "")
        function_name = entry.get("function", "")
        if not module_path or not function_name:
            raise ValueError(f"Hook entry must have 'module' and 'function': {entry!r}")
        mod = importlib.import_module(module_path)
        fn = getattr(mod, function_name)
        if not callable(fn):
            raise ValueError(f"{module_path}.{function_name} is not callable")
        return fn

    def _load_python_tool_hook(self, section_key: str, entry: dict):
        """Load a pre_hook or post_hook from config."""
        fn = self._load_python_module_fn(entry)
        pattern = entry.get("pattern", "*")
        priority = int(entry.get("priority", self._DEFAULT_PRIORITY))
        skills = entry.get("skills", [])
        if isinstance(skills, str):
            skills = [skills]
        if section_key == "pre_hook":
            self.add_pre_hook(pattern, fn, priority, skills)
        else:
            self.add_post_hook(pattern, fn, priority, skills)

    def _load_python_lifecycle_hook(self, section_key: str, entry: dict):
        """Load a lifecycle/layer hook from config."""
        fn = self._load_python_module_fn(entry)
        priority = int(entry.get("priority", self._DEFAULT_PRIORITY))
        skills = entry.get("skills", [])
        if isinstance(skills, str):
            skills = [skills]

        _HOOK_LIST_MAP = {
            "on_agent_start": self._on_agent_start,
            "on_agent_end": self._on_agent_end,
            "on_agent_error": self._on_agent_error,
            "before_node": self._before_node,
            "after_node": self._after_node,
            "before_route": self._before_route,
            "after_route": self._after_route,
            "before_llm": self._before_llm,
            "after_llm": self._after_llm,
            "pre_response": self._pre_response,
            "post_turn": self._pre_response,  # backward compat alias
            "post_sampling": self._post_sampling,
        }
        target_list = _HOOK_LIST_MAP.get(section_key)
        if target_list is None:
            raise ValueError(f"Unknown hook section: {section_key}")
        self._sorted_insert(target_list, (priority, fn, skills))

    # ==================================================================
    # Convenience: wrap a tool call with hooks
    # ==================================================================

    async def execute_with_hooks(
        self, tool_name: str, args: Dict[str, Any], tool_fn: Callable,
    ) -> Any:
        """Execute a tool function wrapped with pre/post hooks."""
        args = self.run_pre_hooks(tool_name, args)
        start = time.time()
        try:
            if asyncio.iscoroutinefunction(tool_fn):
                result = await tool_fn(**args)
            else:
                result = tool_fn(**args)
        except Exception:
            duration_ms = (time.time() - start) * 1000
            self.run_post_hooks(tool_name, args, None, duration_ms)
            raise
        duration_ms = (time.time() - start) * 1000
        return self.run_post_hooks(tool_name, args, result, duration_ms)

    # ==================================================================
    # Info
    # ==================================================================

    @property
    def hook_count(self) -> Dict[str, int]:
        return {
            "tool_pre": len(self._pre_hooks),
            "tool_post": len(self._post_hooks),
            "agent_start": len(self._on_agent_start),
            "agent_end": len(self._on_agent_end),
            "agent_error": len(self._on_agent_error),
            "before_node": len(self._before_node),
            "after_node": len(self._after_node),
            "before_route": len(self._before_route),
            "after_route": len(self._after_route),
            "before_llm": len(self._before_llm),
            "after_llm": len(self._after_llm),
            "pre_response": len(self._pre_response),
            "post_sampling": len(self._post_sampling),
            "external": len(self._external_hooks),
        }

    # ==================================================================
    # Async-aware variants  (Fix #18)
    # ==================================================================

    async def arun_pre_hooks(self, tool_name: str, args: Dict[str, Any]) -> Dict[str, Any]:
        """Async version of run_pre_hooks — awaits async hooks in priority order."""
        current_args = args
        for _pri, pattern, fn, skills in self._pre_hooks:
            if not fnmatch.fnmatch(tool_name, pattern):
                continue
            if not self._skill_matches(skills, self._current_skill):
                continue
            try:
                result = await self._call_hook(fn, tool_name, current_args)
                if isinstance(result, HookResult):
                    if result.blocked:
                        raise ToolBlockedError(result.reason or f"Hook blocked {tool_name}")
                    if result.modified_args:
                        current_args = result.modified_args
                elif isinstance(result, dict):
                    current_args = result
            except ToolBlockedError:
                raise
            except Exception as e:
                log.warning(f"[HookRunner] Pre-hook error for {tool_name}: {e}")
        return current_args

    async def arun_post_hooks(
        self, tool_name: str, args: Dict[str, Any],
        result: Any, duration_ms: float,
    ) -> Any:
        """Async version of run_post_hooks — awaits async hooks in priority order."""
        current_result = result
        for _pri, pattern, fn, skills in self._post_hooks:
            if not fnmatch.fnmatch(tool_name, pattern):
                continue
            if not self._skill_matches(skills, self._current_skill):
                continue
            try:
                modified = await self._call_hook(fn, tool_name, args, current_result, duration_ms)
                if modified is not None:
                    current_result = modified
            except Exception as e:
                log.warning(f"[HookRunner] Post-hook error for {tool_name}: {e}")
        return current_result

    async def arun_on_agent_start(self, agent_id: str, session_id: str, query: str, **ctx):
        for _pri, fn, skills in list(self._on_agent_start):
            if not self._skill_matches(skills, self._current_skill):
                continue
            try:
                await self._call_hook(fn, agent_id=agent_id, session_id=session_id, query=query, **ctx)
            except Exception as e:
                log.warning(f"[HookRunner] on_agent_start error: {e}")

    async def arun_on_agent_end(self, agent_id: str, session_id: str, response: str, duration_ms: float, **ctx):
        for _pri, fn, skills in list(self._on_agent_end):
            if not self._skill_matches(skills, self._current_skill):
                continue
            try:
                await self._call_hook(fn, agent_id=agent_id, session_id=session_id, response=response, duration_ms=duration_ms, **ctx)
            except Exception as e:
                log.warning(f"[HookRunner] on_agent_end error: {e}")

    async def arun_on_agent_error(self, agent_id: str, session_id: str, error: Exception, **ctx):
        for _pri, fn, skills in list(self._on_agent_error):
            if not self._skill_matches(skills, self._current_skill):
                continue
            try:
                await self._call_hook(fn, agent_id=agent_id, session_id=session_id, error=error, **ctx)
            except Exception as e:
                log.warning(f"[HookRunner] on_agent_error error: {e}")

    async def arun_before_node(self, node_name: str, state: dict, **ctx):
        for _pri, fn, skills in list(self._before_node):
            if not self._skill_matches(skills, self._current_skill):
                continue
            try:
                await self._call_hook(fn, node_name=node_name, state=state, **ctx)
            except Exception as e:
                log.warning(f"[HookRunner] before_node({node_name}) error: {e}")

    async def arun_after_node(self, node_name: str, state: dict, result: Any, duration_ms: float, **ctx):
        for _pri, fn, skills in list(self._after_node):
            if not self._skill_matches(skills, self._current_skill):
                continue
            try:
                await self._call_hook(fn, node_name=node_name, state=state, result=result, duration_ms=duration_ms, **ctx)
            except Exception as e:
                log.warning(f"[HookRunner] after_node({node_name}) error: {e}")

    async def arun_before_route(self, query: str, agent_id: str, **ctx):
        for _pri, fn, skills in list(self._before_route):
            if not self._skill_matches(skills, self._current_skill):
                continue
            try:
                await self._call_hook(fn, query=query, agent_id=agent_id, **ctx)
            except Exception as e:
                log.warning(f"[HookRunner] before_route error: {e}")

    async def arun_after_route(self, query: str, skill_name: str, method: str, confidence: float, **ctx):
        for _pri, fn, skills in list(self._after_route):
            if not self._skill_matches(skills, self._current_skill):
                continue
            try:
                await self._call_hook(fn, query=query, skill_name=skill_name, method=method, confidence=confidence, **ctx)
            except Exception as e:
                log.warning(f"[HookRunner] after_route error: {e}")

    async def arun_before_llm(self, messages: list, iteration: int, **ctx):
        for _pri, fn, skills in list(self._before_llm):
            if not self._skill_matches(skills, self._current_skill):
                continue
            try:
                await self._call_hook(fn, messages=messages, iteration=iteration, **ctx)
            except Exception as e:
                log.warning(f"[HookRunner] before_llm error: {e}")

    async def arun_after_llm(self, messages: list, ai_response: Any, iteration: int, duration_ms: float, **ctx):
        for _pri, fn, skills in list(self._after_llm):
            if not self._skill_matches(skills, self._current_skill):
                continue
            try:
                await self._call_hook(fn, messages=messages, ai_response=ai_response, iteration=iteration, duration_ms=duration_ms, **ctx)
            except Exception as e:
                log.warning(f"[HookRunner] after_llm error: {e}")

    async def arun_pre_response(self, response: str, session_ctx: Optional[dict] = None) -> str:
        """Async version of run_pre_response."""
        current_response = response
        ctx = session_ctx or {}
        for _pri, fn, skills in list(self._pre_response):
            if not self._skill_matches(skills, self._current_skill):
                continue
            try:
                result = await self._call_hook(fn, current_response, ctx)
                if isinstance(result, HookResult):
                    if result.blocked:
                        log.info(f"[HookRunner] PreResponse blocked: {result.reason[:80]}")
                        return f"⚠️ Response blocked by compliance policy: {result.reason}"
                    if result.response is not None:
                        current_response = result.response
                elif isinstance(result, str):
                    current_response = result
            except Exception as e:
                log.warning(f"[HookRunner] pre_response error: {e}")

        # External PreResponse hooks (same as sync version)
        for hook in self._external_hooks:
            if hook.event != "PreResponse":
                continue
            if not self._skill_matches(hook.skills, self._current_skill):
                continue
            ext_result = self._run_external_hook(hook, {
                "IAF_HOOK_EVENT": "PreResponse",
                "IAF_RESPONSE": current_response[:4096],
                **self._build_session_env(ctx),
            })
            if ext_result.blocked:
                return f"⚠️ Response blocked by compliance policy: {ext_result.reason}"
            if ext_result.response is not None:
                current_response = ext_result.response

        return current_response


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _parse_hook_output(stdout: str, stderr: str) -> str:
    """Extract a human-readable reason from hook script output."""
    try:
        data = json.loads(stdout)
        reason = data.get("reason") or data.get("message") or ""
        if reason:
            return str(reason)[:500]
    except (json.JSONDecodeError, AttributeError, TypeError):
        pass
    text = (stderr or stdout or "").strip()
    return text[:500]


# ---------------------------------------------------------------------------
# Default hooks factory
# ---------------------------------------------------------------------------

def create_default_hooks(hooks_config: Optional[dict] = None) -> HookRunner:
    """Create a HookRunner with standard production hooks pre-registered.

    Args:
        hooks_config: Optional config dict (from YAML) for user-defined hooks.
                      Merged on top of the built-in defaults.

    Priority convention:
      10  — Security (prompt guard, code blockers)
      50  — Logging
      100 — Default / user hooks
    """
    runner = HookRunner()

    # --- Layer 0: Prompt injection guard (priority 10 — runs first) ---
    try:
        from src.agentos.prompt_guard import create_prompt_guard_hook
        create_prompt_guard_hook(runner)
    except Exception as e:
        log.debug(f"[HookRunner] Prompt guard not registered: {e}")

    # --- Layer 0b: OpenTelemetry span hooks (priority 20 — after security) ---
    try:
        from telemetry_wrapper import create_otel_hooks
        create_otel_hooks(runner)
    except Exception as e:
        log.debug(f"[HookRunner] OTel span hooks not registered: {e}")

    # --- Layer 1: Agent lifecycle (priority 50 — logging) ---
    @runner.on_agent_start(priority=50)
    def _log_agent_start(agent_id, session_id, query, **kw):
        log.info(
            f"[Hook:lifecycle] Agent START agent={agent_id[:12]}... "
            f"session={session_id[:8]}... query='{query[:80]}'"
        )

    @runner.on_agent_end(priority=50)
    def _log_agent_end(agent_id, session_id, response, duration_ms, **kw):
        skill = kw.get("skill_name", "?")
        method = kw.get("routing_method", "?")
        log.info(
            f"[Hook:lifecycle] Agent END agent={agent_id[:12]}... "
            f"skill={skill} method={method} "
            f"duration={duration_ms:.0f}ms response_len={len(response or '')}"
        )

    @runner.on_agent_error(priority=50)
    def _log_agent_error(agent_id, session_id, error, **kw):
        log.error(
            f"[Hook:lifecycle] Agent ERROR agent={agent_id[:12]}... "
            f"session={session_id[:8]}... error={error}"
        )

    # --- Layer 2: Node hooks (priority 50 — logging) ---
    @runner.before_node(priority=50)
    def _log_before_node(node_name, state, **kw):
        log.debug(f"[Hook:node] → {node_name}")

    @runner.after_node(priority=50)
    def _log_after_node(node_name, state, result, duration_ms, **kw):
        log.info(f"[Hook:node] ← {node_name} ({duration_ms:.0f}ms)")

    # --- Layer 3: Routing hooks (priority 50 — logging) ---
    @runner.after_route(priority=50)
    def _log_route_result(query, skill_name, method, confidence, **kw):
        log.info(
            f"[Hook:route] '{query[:50]}' → skill={skill_name} "
            f"method={method} conf={confidence:.2f}"
        )

    # --- Layer 4: LLM hooks (priority 50 — logging) ---
    @runner.after_llm(priority=50)
    def _log_llm_call(messages, ai_response, iteration, duration_ms, **kw):
        has_tools = bool(getattr(ai_response, "tool_calls", None))
        content_len = len(getattr(ai_response, "content", "") or "")
        log.info(
            f"[Hook:llm] iteration={iteration} duration={duration_ms:.0f}ms "
            f"has_tool_calls={has_tools} content_len={content_len}"
        )

    # --- Layer 5: Tool hooks (logging=50, security=10) ---
    @runner.post_hook("*", priority=50)
    def _log_all_tool_calls(tool_name, args, result, duration_ms):
        result_preview = str(result)[:100] if result else ""
        log.info(
            f"[Hook:tool] tool={tool_name} "
            f"duration={duration_ms:.0f}ms "
            f"result_preview={result_preview}"
        )
        return result

    # Fix #13 — use AST-based analysis instead of trivially-bypassable substring matching
    @runner.pre_hook("execute_python_code", priority=10)
    def _block_dangerous_patterns(tool_name, args):
        import ast as _ast
        code = args.get("code", "")
        # Stage 1: quick substring pre-filter (cheap)
        _QUICK_BLOCKLIST = [
            "os.system", "os.popen", "subprocess", "__import__",
            "shutil.rmtree", "exec(", "eval(", "compile(",
            "importlib", "ctypes", "pickle.loads",
        ]
        has_suspect = any(p in code for p in _QUICK_BLOCKLIST)
        if not has_suspect:
            return args
        # Stage 2: AST-based structural check (thorough)
        _BLOCKED_CALLS = {
            "os.system", "os.popen", "os.exec", "os.execvp", "os.execve",
            "os.spawn", "os.spawnl", "os.spawnle",
            "subprocess.run", "subprocess.call", "subprocess.Popen",
            "subprocess.check_output", "subprocess.check_call",
            "shutil.rmtree", "shutil.move",
            "eval", "exec", "compile", "__import__",
            "importlib.import_module",
            "ctypes.cdll", "pickle.loads",
        }
        try:
            tree = _ast.parse(code)
            for node in _ast.walk(tree):
                if isinstance(node, _ast.Call):
                    func = node.func
                    # Match: module.func()
                    if isinstance(func, _ast.Attribute) and isinstance(func.value, _ast.Name):
                        full = f"{func.value.id}.{func.attr}"
                        if full in _BLOCKED_CALLS:
                            raise ToolBlockedError(
                                f"Hook blocked: '{full}()' is not allowed for security reasons."
                            )
                    # Match: bare func()
                    elif isinstance(func, _ast.Name):
                        if func.id in _BLOCKED_CALLS:
                            raise ToolBlockedError(
                                f"Hook blocked: '{func.id}()' is not allowed for security reasons."
                            )
                    # Match: getattr() used for evasion
                    if isinstance(func, _ast.Name) and func.id == "getattr":
                        raise ToolBlockedError(
                            "Hook blocked: 'getattr()' is not allowed in code execution."
                        )
        except ToolBlockedError:
            raise
        except SyntaxError:
            pass  # Let the code executor handle syntax errors
        except Exception:
            pass  # Don't block on AST parse edge cases
        return args

    log.debug(f"[HookRunner] Default hooks registered: {runner.hook_count}")

    # --- Load user-defined hooks from config (if provided) ---
    if hooks_config:
        try:
            runner.load_from_config(hooks_config)
        except Exception as e:
            log.warning(f"[HookRunner] Config hook loading failed: {e}")

    return runner
