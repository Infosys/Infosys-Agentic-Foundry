"""
IAF Hook System — HookRunner

Provides four lifecycle hooks for external integration and future internal migration:

  PreToolUse   — Synchronous, can block, fires for ALL tool calls before execution
  PostToolUse  — Async fire-and-forget, fires from trace_callback after tool completes
  PostTurn     — Synchronous, can block/modify response, fires before HTTP response
  PostSampling — Async fire-and-forget, fires at end of bg thread after response sent

Phase 1: External commands configured via config.yaml hooks: section, run as
argv without a shell (allowlisted interpreter + confined script).
Phase 2: Internal Python callables registered via register_internal() replace
         inline side-effect code in agent.py (episodic log, implicit feedback,
         plan cache write, tool learning, HITL gate).

Config format (config.yaml per agent — all sections optional):

    hooks:
      PreToolUse:
        - matcher: "run_sql_query"
          command: "python3 /hooks/audit_sql.py"
          block_on_nonzero: true
          timeout_seconds: 10

      PostToolUse:
        - matcher: ".*"
          command: "python3 /hooks/splunk_log.py"

      PostTurn:
        - command: "python3 /hooks/response_compliance.py"
          block_on_nonzero: true

      PostSampling:
        - command: "python3 /hooks/notify_slack.py"

Hook scripts receive IAF_* environment variables (see _build_env).
Structured JSON stdout is supported — scripts can return:
    {"blocked": true, "reason": "Violates SOX §302"}
    {"blocked": false, "message": "Audit logged: ref=AUD-2026-001"}

Design decisions captured in: docs/HOOK_SYSTEM_DESIGN.md
"""

from __future__ import annotations

import ast
import json
import logging
import os
import re
import shlex
import shutil
import subprocess
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, List, Optional

# Prevent child processes from popping a console window on Windows, where the
# server runs under console-less pythonw.exe. Evaluates to 0 (no-op) elsewhere.
_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)

from agent_os.safe_path import (
    SecurityError as _PathSecurityError,
    confine_to_root,
    reconstruct_path,
    validated_path,
)

try:
    from ._pyexec import get_python_executable as _get_python_executable
except Exception:  # pragma: no cover - direct test loading fallback
    import sys as _pyexec_sys

    def _get_python_executable() -> str:  # type: ignore[misc]
        return _pyexec_sys.executable

try:
    from .hook_context import build_hook_context, redact_hook_value
except Exception:  # pragma: no cover - direct test loading fallback
    import importlib.util as _importlib_util
    import sys as _sys

    _hook_context_path = Path(__file__).with_name("hook_context.py")
    _hook_context_spec = _importlib_util.spec_from_file_location(
        "iaf_agent_skills.hook_context", _hook_context_path
    )
    _hook_context_module = _importlib_util.module_from_spec(_hook_context_spec)
    _sys.modules["iaf_agent_skills.hook_context"] = _hook_context_module
    _hook_context_spec.loader.exec_module(_hook_context_module)
    build_hook_context = _hook_context_module.build_hook_context
    redact_hook_value = _hook_context_module.redact_hook_value

logger = logging.getLogger(__name__)


HOOK_PRE_TOOL_USE        = "PreToolUse"
HOOK_POST_TOOL_USE       = "PostToolUse"
HOOK_POST_TURN           = "PostTurn"
HOOK_POST_SAMPLING       = "PostSampling"
# Orchestrator / workflow / parallel step-level events (new)
HOOK_PRE_STEP            = "PreStep"            # blocking — can abort a step
HOOK_POST_STEP           = "PostStep"           # synchronous — can return feedback
HOOK_ON_EXEC_FAILURE     = "OnExecutionFailure" # fire-and-forget on step exception
HOOK_ON_APPROVAL_RESOLVED = "OnApprovalResolved"  # observe-only after approval decision is recorded
HOOK_BEFORE_APPROVAL_RESUME = "BeforeApprovalResume"  # blocking gate before checkpoint resume
HOOK_AFTER_APPROVAL_RESUME = "AfterApprovalResume"  # observe-only after resume attempt
HOOK_ON_BLOCKED          = "OnBlocked"          # fire-and-forget after a blocking hook denies

HOOK_BEFORE_TURN          = "BeforeTurn"
HOOK_ON_TURN_END          = "OnTurnEnd"
HOOK_ON_ERROR             = "OnError"
HOOK_BEFORE_MODEL_CALL    = "BeforeModelCall"
HOOK_AFTER_MODEL_CALL     = "AfterModelCall"
HOOK_AROUND_MODEL_CALL    = "AroundModelCall"
HOOK_BEFORE_SCHEDULE_FIRE = "BeforeScheduleFire"
HOOK_AFTER_SCHEDULE_FIRE  = "AfterScheduleFire"
HOOK_ON_SCHEDULE_ERROR    = "OnScheduleError"

HOOK_BEFORE_QUEUE_ITEM_START = "BeforeQueueItemStart"
HOOK_AFTER_QUEUE_ITEM_COMPLETE = "AfterQueueItemComplete"
HOOK_ON_QUEUE_ITEM_ERROR = "OnQueueItemError"
HOOK_BEFORE_QUEUE_RETRY = "BeforeQueueRetry"
HOOK_ON_QUEUE_DLQ = "OnQueueDLQ"
HOOK_ON_QUEUE_HITL_PENDING = "OnQueueHITLPending"

HOOK_ON_KNOWLEDGE_ENTRY_PENDING = "OnKnowledgeEntryPending"
HOOK_ON_MEMORY_WRITE            = "OnMemoryWrite"
HOOK_ON_SKILL_GAP_DETECTED      = "OnSkillGapDetected"
HOOK_ON_SELF_EVOLUTION_PASS     = "OnSelfEvolutionPass"
HOOK_ON_BACKGROUND_TASK_ERROR   = "OnBackgroundTaskError"

# Mission Mode lifecycle (workstream grinder — fires across many cron iterations)
HOOK_BEFORE_MISSION_START   = "BeforeMissionStart"      # gateable — block first activation
HOOK_ON_MISSION_ITEM_FAILED = "OnMissionItemFailed"     # observe — item exhausted retries
HOOK_ON_MISSION_COMPLETE    = "OnMissionComplete"       # observe — workstream terminal

HOOK_ON_DECOMPOSITION_COMPLETE      = "OnDecompositionComplete"      # gateable — block low-conf decomps
HOOK_ON_RESEARCH_WORKSTREAM_CREATED = "OnResearchWorkstreamCreated"  # gateable — block expensive launches

ALLOWED_HOOK_EVENTS = {
    HOOK_PRE_TOOL_USE,
    HOOK_POST_TOOL_USE,
    HOOK_POST_TURN,
    HOOK_POST_SAMPLING,
    HOOK_PRE_STEP,
    HOOK_POST_STEP,
    HOOK_ON_EXEC_FAILURE,
    HOOK_ON_APPROVAL_RESOLVED,
    HOOK_BEFORE_APPROVAL_RESUME,
    HOOK_AFTER_APPROVAL_RESUME,
    HOOK_ON_BLOCKED,
    HOOK_BEFORE_TURN,
    HOOK_ON_TURN_END,
    HOOK_ON_ERROR,
    HOOK_BEFORE_MODEL_CALL,
    HOOK_AFTER_MODEL_CALL,
    HOOK_AROUND_MODEL_CALL,
    HOOK_BEFORE_SCHEDULE_FIRE,
    HOOK_AFTER_SCHEDULE_FIRE,
    HOOK_ON_SCHEDULE_ERROR,
    HOOK_BEFORE_QUEUE_ITEM_START,
    HOOK_AFTER_QUEUE_ITEM_COMPLETE,
    HOOK_ON_QUEUE_ITEM_ERROR,
    HOOK_BEFORE_QUEUE_RETRY,
    HOOK_ON_QUEUE_DLQ,
    HOOK_ON_QUEUE_HITL_PENDING,
    HOOK_ON_KNOWLEDGE_ENTRY_PENDING,
    HOOK_ON_MEMORY_WRITE,
    HOOK_ON_SKILL_GAP_DETECTED,
    HOOK_ON_SELF_EVOLUTION_PASS,
    HOOK_ON_BACKGROUND_TASK_ERROR,
    HOOK_BEFORE_MISSION_START,
    HOOK_ON_MISSION_ITEM_FAILED,
    HOOK_ON_MISSION_COMPLETE,
    HOOK_ON_DECOMPOSITION_COMPLETE,
    HOOK_ON_RESEARCH_WORKSTREAM_CREATED,
}


HOOK_EVENT_CATALOGUE: dict[str, dict[str, Any]] = {
    HOOK_PRE_TOOL_USE: {"category": "tool", "gateable": True,
        "summary": "Runs before a tool call; a blocking hook can deny it — the deterministic HITL gate."},
    HOOK_POST_TOOL_USE: {"category": "tool", "gateable": False,
        "summary": "Runs after a tool call completes; observe-only."},

    HOOK_PRE_STEP: {"category": "step", "gateable": True,
        "summary": "Runs before an orchestrator/workflow step; a blocking hook can abort the step."},
    HOOK_POST_STEP: {"category": "step", "gateable": False,
        "summary": "Runs after a step; synchronous and can return feedback, but not a hard block."},
    HOOK_ON_EXEC_FAILURE: {"category": "step", "gateable": False,
        "summary": "Fires on a step exception; fire-and-forget."},

    HOOK_ON_APPROVAL_RESOLVED: {"category": "approval", "gateable": False,
        "summary": "Fires after an approval decision is recorded; observe-only."},
    HOOK_BEFORE_APPROVAL_RESUME: {"category": "approval", "gateable": True,
        "summary": "Runs before a checkpoint resume; a blocking hook can gate the resume."},
    HOOK_AFTER_APPROVAL_RESUME: {"category": "approval", "gateable": False,
        "summary": "Fires after a resume attempt; observe-only."},
    HOOK_ON_BLOCKED: {"category": "approval", "gateable": False,
        "summary": "Fires after a blocking hook denies a call, so observers don't need to wrap every PreToolUse themselves."},

    HOOK_POST_TURN: {"category": "turn", "gateable": False,
        "summary": "Fires after a conversational turn completes; observe-only."},
    HOOK_BEFORE_TURN: {"category": "turn", "gateable": True,
        "summary": "Runs before a turn starts; a hook can return deny to skip the turn."},
    HOOK_ON_TURN_END: {"category": "turn", "gateable": False,
        "summary": "Fires when a turn ends; observe-only."},
    HOOK_ON_ERROR: {"category": "turn", "gateable": False,
        "summary": "Fires on an unhandled error; observe-only."},

    HOOK_POST_SAMPLING: {"category": "model", "gateable": False,
        "summary": "Fires after the model produces a sample; observe-only."},
    HOOK_BEFORE_MODEL_CALL: {"category": "model", "gateable": True,
        "summary": "Runs before a model call; a hook can return deny to skip the call."},
    HOOK_AFTER_MODEL_CALL: {"category": "model", "gateable": False,
        "summary": "Fires after a model call returns; observe-only."},
    HOOK_AROUND_MODEL_CALL: {"category": "model", "gateable": True,
        "summary": "Wraps a model call end-to-end and can intercept it."},

    HOOK_BEFORE_SCHEDULE_FIRE: {"category": "schedule", "gateable": True,
        "summary": "Runs before a cron schedule fires; a blocking hook can skip this firing."},
    HOOK_AFTER_SCHEDULE_FIRE: {"category": "schedule", "gateable": False,
        "summary": "Fires after a cron schedule runs; observe-only audit fan-out."},
    HOOK_ON_SCHEDULE_ERROR: {"category": "schedule", "gateable": False,
        "summary": "Fires when a cron schedule errors; observe-only audit fan-out."},

    HOOK_BEFORE_QUEUE_ITEM_START: {"category": "queue", "gateable": False,
        "summary": "Runs before a queue item starts executing; observe-only/fail-open today."},
    HOOK_AFTER_QUEUE_ITEM_COMPLETE: {"category": "queue", "gateable": False,
        "summary": "Fires after a queue item completes; observe-only."},
    HOOK_ON_QUEUE_ITEM_ERROR: {"category": "queue", "gateable": False,
        "summary": "Fires when a queue item errors; observe-only."},
    HOOK_BEFORE_QUEUE_RETRY: {"category": "queue", "gateable": False,
        "summary": "Runs before a queue item is retried; observe-only, fire-and-forget."},
    HOOK_ON_QUEUE_DLQ: {"category": "queue", "gateable": False,
        "summary": "Fires when a queue item moves to the dead-letter queue; observe-only."},
    HOOK_ON_QUEUE_HITL_PENDING: {"category": "queue", "gateable": False,
        "summary": "Fires when a queue item is waiting on a human approval; observe-only."},

    HOOK_ON_KNOWLEDGE_ENTRY_PENDING: {"category": "background", "gateable": False,
        "summary": "Fires when a knowledge entry is queued for review; observe-only background instrumentation."},
    HOOK_ON_MEMORY_WRITE: {"category": "background", "gateable": False,
        "summary": "Fires on a memory write from a non-tool path; observe-only background instrumentation."},
    HOOK_ON_SKILL_GAP_DETECTED: {"category": "background", "gateable": False,
        "summary": "Fires when a skill gap is detected; observe-only background instrumentation."},
    HOOK_ON_SELF_EVOLUTION_PASS: {"category": "background", "gateable": False,
        "summary": "Fires after a self-evolution pass; observe-only background instrumentation."},
    HOOK_ON_BACKGROUND_TASK_ERROR: {"category": "background", "gateable": False,
        "summary": "Fires when a background task errors; observe-only background instrumentation."},

    HOOK_BEFORE_MISSION_START: {"category": "mission", "gateable": True,
        "summary": "Runs before a mission's first activation; a blocking hook can block it."},
    HOOK_ON_MISSION_ITEM_FAILED: {"category": "mission", "gateable": False,
        "summary": "Fires when a mission item exhausts its retries; observe-only."},
    HOOK_ON_MISSION_COMPLETE: {"category": "mission", "gateable": False,
        "summary": "Fires when a mission reaches a terminal state; observe-only."},

    HOOK_ON_DECOMPOSITION_COMPLETE: {"category": "research", "gateable": True,
        "summary": "Fires after research decomposition; a blocking hook can block a low-confidence decomposition."},
    HOOK_ON_RESEARCH_WORKSTREAM_CREATED: {"category": "research", "gateable": True,
        "summary": "Fires when a research workstream is created; a blocking hook can block an expensive launch."},
}

ALLOWED_HOOK_MODES = {"observe", "blocking", "async"}
ALLOWED_FAIL_POLICIES = {"open", "closed"}
ALLOWED_ON_BLOCK_ACTIONS = {"deny", "hitl", "retry"}
MAX_HOOK_OUTPUT_CHARS = 65536
MAX_HOOK_AUDIT_PREVIEW_CHARS = 4096

CREDENTIAL_BEARING_TOOLS = frozenset({
    "get_credential",
    "query_credentials",
    "credential_store",
    "credential_resolver",
    "resolve_credential",
})


def _is_credential_bearing(tool_name: str) -> bool:
    """Return True if a tool name should trigger credential fail-closed semantics."""
    if not tool_name:
        return False
    return tool_name.strip().lower() in CREDENTIAL_BEARING_TOOLS


_ENV_VAR_PATTERN = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}|\$([A-Za-z_][A-Za-z0-9_]*)")


def _expand_env_token(token: str, env: dict) -> str:
    """Expand ``$VAR`` and ``${VAR}`` references inside ONE argv token.

    Hook commands are split into argv tokens BEFORE expansion, so a
    value is substituted literally into the token it appears in and can never
    add tokens or shell syntax, whatever characters it contains. The same
    ``$VAR`` YAML therefore works on Linux and Windows without a shell.

    Unknown variables are left as-is so the failure surfaces with a
    recognisable token instead of collapsing to a malformed path.
    """
    if not token or "$" not in token:
        return token

    def _replace(match: "re.Match[str]") -> str:
        name = match.group(1) or match.group(2)
        if name in env:
            return str(env[name])
        return match.group(0)

    return _ENV_VAR_PATTERN.sub(_replace, token)



class HookCommandError(ValueError):
    """A hook ``command:`` failed argv validation, so the hook was not run."""


_HOOK_INTERPRETERS = ("python3", "python", "bash", "sh", "node")
_PYTHON_INTERPRETERS = frozenset({"python3", "python"})
# Interpreter options allowed before the script. Anything else (``-c``, ``-m``,
# ``-e``, ...) would run code that is not a confined script file.
_PYTHON_FLAGS = frozenset({"-u", "-B", "-E", "-I", "-s", "-O"})
_SHELL_FLAGS = frozenset({"-e", "-u", "-x"})
_INTERPRETER_FLAGS = {
    "python3": _PYTHON_FLAGS,
    "python": _PYTHON_FLAGS,
    "bash": _SHELL_FLAGS,
    "sh": _SHELL_FLAGS,
    "node": frozenset(),
}
# Interpreter executable path: portable path characters only (as safe_path).
_INTERPRETER_PATH_RE = re.compile(r"^[\w .@+()~:/\\\-]{1,4096}$")
_HOOK_ARG_RE = re.compile(r"^[\x20-\x7E\w]{0,4096}$")


def _reconstruct_str(value: str) -> str:
    """Return a fresh copy of an already-validated string (breaks taint chains)."""
    return value.encode("utf-8").decode("utf-8")


def _split_hook_template(command: str) -> List[str]:
    """Split the UN-expanded hook command template into argv tokens.

    POSIX rules are used unless the template contains a backslash (a literal
    Windows path), which POSIX rules would treat as an escape; such templates
    are split with ``posix=False`` and outer quotes stripped per token.
    """
    posix = "\\" not in command
    try:
        tokens = shlex.split(command, posix=posix)
    except ValueError as exc:
        raise HookCommandError(f"hook command cannot be parsed: {exc}") from None
    if not posix:
        tokens = [
            tok[1:-1] if len(tok) >= 2 and tok[0] == tok[-1] and tok[0] in "\"'" else tok
            for tok in tokens
        ]
    return tokens


def _interpreter_name(token: str) -> str:
    """Basename of an interpreter token, lower-cased, without ``.exe``."""
    name = token.replace("\\", "/").rsplit("/", 1)[-1].lower()
    return name[:-4] if name.endswith(".exe") else name


def _resolve_hook_interpreter(token: str) -> tuple[str, str]:
    """Return ``(name, absolute_executable)`` for an allowlisted interpreter.

    Bare ``python3``/``python`` resolve exactly as before (``_pyexec``:
    ``IAF_PYTHON_EXECUTABLE`` override, PATH, then the running interpreter);
    ``bash``/``sh``/``node`` resolve through PATH. An explicit path is kept
    when its basename is allowlisted and it exists. Symlinks are NOT resolved
    so a venv interpreter keeps its venv.
    """
    name = _interpreter_name(token)
    if name not in _HOOK_INTERPRETERS:
        raise HookCommandError(
            f"program {name!r} is not an allowed hook interpreter "
            f"(allowed: {', '.join(_HOOK_INTERPRETERS)})"
        )
    if "/" in token or "\\" in token:
        candidate = token
    elif name in _PYTHON_INTERPRETERS:
        candidate = _get_python_executable()
    else:
        candidate = shutil.which(name) or ""
    if not candidate or not _INTERPRETER_PATH_RE.fullmatch(candidate):
        raise HookCommandError(f"hook interpreter {name!r} was not found")
    resolved = os.path.abspath(candidate)
    if not os.path.isfile(resolved):
        raise HookCommandError(f"hook interpreter {name!r} was not found")
    if os.name == "nt" and not resolved.lower().endswith(".exe"):
        # A .cmd/.bat shim would be run through cmd.exe, re-parsing argv.
        raise HookCommandError(f"hook interpreter {name!r} must resolve to an .exe")
    return name, str(reconstruct_path(resolved))


def _confine_hook_script(token: str, roots: List[Path]) -> str:
    """Resolve the hook script path and require it under one of ``roots``."""
    try:
        candidate = validated_path(token, label="hook script")
    except _PathSecurityError:
        raise HookCommandError("hook script path is invalid") from None
    for root in roots:
        try:
            return str(confine_to_root(candidate, root, label="hook script"))
        except _PathSecurityError:
            continue
    raise HookCommandError(
        "hook script resolves outside the agent's tenant tree and the platform hooks dir"
    )


_ENV_PATH_CHAR_RE = re.compile(r'^[A-Za-z0-9 _/\\:.\-;]+$')
_ENV_LANG_CHAR_RE = re.compile(r'^[A-Za-z0-9._\-]+$')
_ENV_DIR_CHAR_RE = re.compile(r'^[A-Za-z0-9 _/\\:.\-]+$')
_ENV_URL_CHAR_RE = re.compile(r'^[A-Za-z0-9._\-:/@?=&%+~!*(),\[\]]+$')


def _sanitize_env_path_value(value: str) -> str:
    """Validate a PATH-style env var and return a sanitized copy.

    Raises ValueError on invalid input to act as a Fortify-recognised
    sanitiser gate (CWE-78 / CWE-73).
    """
    if not _ENV_PATH_CHAR_RE.fullmatch(value):
        raise ValueError("PATH value contains disallowed characters")
    return value.encode("utf-8").decode("utf-8")


def _sanitize_env_lang_value(value: str) -> str:
    """Validate a LANG-style env var and return a sanitized copy."""
    if not _ENV_LANG_CHAR_RE.fullmatch(value):
        raise ValueError("LANG value contains disallowed characters")
    return value.encode("utf-8").decode("utf-8")


def _sanitize_env_url_value(value: str) -> str:
    r"""Validate a URL/DSN env var (REDIS_URL and similar) and return a sanitized copy.

    Same Fortify-sanitiser role as the other _sanitize_env_* helpers: fullmatch
    against an allowlist regex, then re-encode to sever taint propagation from
    os.environ into subprocess (CWE-78). Shell metacharacters ($ ` \ | ; < > and
    whitespace) are excluded so a tainted value can never be re-parsed as shell.
    """
    if not _ENV_URL_CHAR_RE.fullmatch(value):
        raise ValueError("URL value contains disallowed characters")
    return value.encode("utf-8").decode("utf-8")


def _sanitize_env_dir_path(value: str) -> str:
    """Validate a directory-path env var (TEMP, HOME, etc.).

    Ensures the value contains only safe characters, resolves to an actual
    directory, and returns a reconstructed string to break Fortify taint.
    """
    if not _ENV_DIR_CHAR_RE.fullmatch(value):
        raise ValueError("Directory path contains disallowed characters")
    clean = value.encode("utf-8").decode("utf-8")
    resolved = Path(clean).resolve()
    if not resolved.is_dir():
        raise ValueError(f"Not an existing directory: {clean}")
    return str(resolved).encode("utf-8").decode("utf-8")


def _sanitize_env_shell_path(value: str) -> str:
    """Validate a COMSPEC-style env var pointing to a known shell executable.

    Only cmd.exe and powershell.exe are accepted.
    """
    if not _ENV_DIR_CHAR_RE.fullmatch(value):
        raise ValueError("Shell path contains disallowed characters")
    clean = value.encode("utf-8").decode("utf-8")
    resolved = Path(clean).resolve()
    if not resolved.is_file():
        raise ValueError(f"Shell path is not a file: {clean}")
    if resolved.name.lower() not in ("cmd.exe", "powershell.exe"):
        raise ValueError(f"Unknown shell binary: {resolved.name}")
    return str(resolved).encode("utf-8").decode("utf-8")



@dataclass
class HookResult:
    """
    Result returned by synchronous hooks (PreToolUse, PostTurn, PreStep, PostStep).
    PostToolUse, PostSampling, OnExecutionFailure results are discarded (fire-and-forget).
    """
    blocked: bool
    reason: str = ""
    # PostTurn only: if non-None, replaces the agent response sent to the user
    response: Optional[str] = None
    # PostStep only: if non-None, appended to the OrchestratorStep and surfaced
    # to the manager LLM on its next decision so it can adapt to result quality
    feedback: Optional[str] = None
    hook_event: str = ""
    hook_id: str = ""
    # "deny" keeps the historical block-only behavior; "hitl" asks callers to
    # convert the block into agent.approval_pending when the call site can pause.
    on_block: str = "deny"
    approval: dict[str, Any] = field(default_factory=dict)


@dataclass
class ExternalHook:
    """
    An external command hook loaded from config.yaml (run as argv, no shell).
    Compiled matcher regex is stored in _matcher_re after __post_init__.
    """
    event: str              # "PreToolUse" | "PostToolUse" | "PostTurn" | "PostSampling"
    command: str            # "<interpreter> <script> [args]" — split to argv, no shell
    hook_id: str = ""       # Stable manifest id used for audit/debug output
    matcher: str = ".*"     # Regex matched against tool_name (re.IGNORECASE, re.search)
    skills: List[str] = field(default_factory=list)  # Skill name filter — empty = ALL skills
    priority: int = 100      # Lower values run first; ties use registration order
    mode: str = "observe"   # observe | blocking | async (declarative manifest metadata)
    fail_policy: str = "open"  # open | closed (declarative manifest metadata)
    owner: str = ""
    permissions: List[str] = field(default_factory=list)
    input_schema: dict = field(default_factory=dict)
    output_schema: dict = field(default_factory=dict)
    on_block: str = "deny"  # deny | hitl
    approval: dict = field(default_factory=dict)
    max_output_chars: int = 4096
    block_on_nonzero: bool = False   # PreToolUse/PostTurn: non-zero exit blocks operation
    timeout_seconds: int = 10        # Timeout — on expiry: log warning and CONTINUE
    mutates: List[str] = field(default_factory=list)
    can_short_circuit: bool = False
    lock_fields: List[str] = field(default_factory=list)
    hot_path: bool = False
    external_mutation_allowed: bool = False
    _registration_order: int = field(default=0, repr=False, compare=False)
    _matcher_re: object = field(default=None, repr=False, compare=False)

    def __post_init__(self):
        try:
            self._matcher_re = re.compile(self.matcher, re.IGNORECASE)
        except re.error:
            logger.warning("HookRunner: invalid matcher regex %r for [%s] — using '.*'",
                           self.matcher, self.event)
            self._matcher_re = re.compile(".*")


@dataclass
class InternalHook:
    """
    A Python callable registered for Phase 2 migration.
    handler(ctx: dict) — ctx contains tool/session fields.
    can_block=True allows handler to return HookResult(blocked=True).

    fail_policy ("open"|"closed") controls what happens when the handler raises:
      * "open"   — log + treat as non-blocking (legacy behaviour)
      * "closed" — log + treat as a HookResult(blocked=True, reason="hook error")
                   so callers protected by a security hook fail safe.
    """
    event: str
    handler: Callable
    hook_id: str = ""
    matcher: str = ".*"
    skills: List[str] = field(default_factory=list)  # Skill name filter — empty = ALL skills
    priority: int = 100
    can_block: bool = False
    fail_policy: str = "open"
    mutates: List[str] = field(default_factory=list)
    can_short_circuit: bool = False
    lock_fields: List[str] = field(default_factory=list)
    hot_path: bool = False
    external_mutation_allowed: bool = False
    _registration_order: int = field(default=0, repr=False, compare=False)
    _matcher_re: object = field(default=None, repr=False, compare=False)

    def __post_init__(self):
        try:
            self._matcher_re = re.compile(self.matcher, re.IGNORECASE)
        except re.error:
            self._matcher_re = re.compile(".*")
        if self.fail_policy not in ALLOWED_FAIL_POLICIES:
            logger.warning(
                "HookRunner: invalid fail_policy %r for internal hook %s — defaulting to 'open'",
                self.fail_policy, self.hook_id or self.event,
            )
            self.fail_policy = "open"



class HookRunner:
    """
    Runs lifecycle hooks for a single SkillAgent instance.

    If hooks_config is empty (no hooks: section in config.yaml),
    all run_* methods iterate over empty lists — effectively a no-op.

    Batch 4 kill switch: set the env var ``CAPABILITY_HOOKS_ENABLED=false``
    (read once at module import) to disable ALL hook fan-outs platform-wide.
    Kernel hard-gates (credential / external-access deny) remain in effect —
    only the hook layer is bypassed. This is intended for production rollback
    or A/B baseline comparison without a code revert.
    """

    _capability_hooks_enabled = os.environ.get("CAPABILITY_HOOKS_ENABLED", "true").lower() == "true"

    @classmethod
    def set_capability_hooks_enabled(cls, enabled: bool) -> None:
        """Flip the platform-wide kill switch at runtime."""
        cls._capability_hooks_enabled = bool(enabled)
        logger.info("HookRunner: capability hooks %s", "ENABLED" if cls._capability_hooks_enabled else "DISABLED")

    @classmethod
    def capability_hooks_enabled(cls) -> bool:
        return bool(cls._capability_hooks_enabled)

    def __init__(self, hooks_config: dict, agent_root: str = "", hook_audit_sink=None,
                 platform_hooks_dir: str = ""):
        """
        Args:
            hooks_config: Effective hooks (platform + tenant, merged by
                          platform_hooks.resolve_effective_hooks) — may be empty dict/None.
            agent_root:   Absolute path to agent directory — set as IAF_AGENT_ROOT env var
                          (scripts use it for per-tenant output, e.g. the audit DB).
            platform_hooks_dir: Dir of framework-owned platform hook scripts — exposed as
                          IAF_PLATFORM_HOOKS_DIR. Defaults to the platform_hooks package's
                          scripts/ dir so platform hook commands resolve across tenants.
        """
        self._agent_root = str(agent_root)
        if not platform_hooks_dir:
            try:
                from .platform_hooks import platform_hooks_dir as _default_dir
                platform_hooks_dir = _default_dir()
            except Exception:  # pragma: no cover - defensive; platform hooks optional
                platform_hooks_dir = ""
        self._platform_hooks_dir = str(platform_hooks_dir)
        self._external: List[ExternalHook] = []
        self._internal: List[InternalHook] = []
        self._registration_counter = 0
        self._hook_audit_sink = hook_audit_sink

        for event, entries in (hooks_config or {}).items():
            if not isinstance(entries, list):
                logger.warning("HookRunner: hooks.%s must be a list — skipping", event)
                continue
            if event not in ALLOWED_HOOK_EVENTS:
                logger.warning("HookRunner: unknown hook event [%s] — skipping", event)
                continue
            for entry in entries:
                order = self._next_registration_order()
                manifest = self._validate_external_manifest(event, entry, order)
                if manifest is None:
                    logger.warning(
                        "HookRunner: malformed hook entry under [%s] — skipping: %r",
                        event, entry,
                    )
                    continue
                self._external.append(ExternalHook(
                    event=event,
                    command=manifest["command"],
                    hook_id=manifest["hook_id"],
                    matcher=manifest["matcher"],
                    skills=manifest["skills"],
                    priority=manifest["priority"],
                    mode=manifest["mode"],
                    fail_policy=manifest["fail_policy"],
                    owner=manifest["owner"],
                    permissions=manifest["permissions"],
                    input_schema=manifest["input_schema"],
                    output_schema=manifest["output_schema"],
                    on_block=manifest["on_block"],
                    approval=manifest["approval"],
                    max_output_chars=manifest["max_output_chars"],
                    block_on_nonzero=manifest["block_on_nonzero"],
                    timeout_seconds=manifest["timeout_seconds"],
                    mutates=manifest["mutates"],
                    can_short_circuit=manifest["can_short_circuit"],
                    lock_fields=manifest["lock_fields"],
                    hot_path=manifest["hot_path"],
                    external_mutation_allowed=manifest["external_mutation_allowed"],
                    _registration_order=order,
                ))

        self._external.sort(key=self._hook_sort_key)

        if self._external:
            events = {}
            for h in self._external:
                events[h.event] = events.get(h.event, 0) + 1
            logger.info("HookRunner: loaded %d external hook(s): %s",
                        len(self._external),
                        ", ".join(f"{k}×{v}" for k, v in events.items()))


    def register_internal(
        self,
        event: str,
        handler: Callable,
        matcher: str = ".*",
        can_block: bool = False,
        priority: int = 100,
        hook_id: str = "",
        fail_policy: str = "open",
        mutates: List[str] | None = None,
        can_short_circuit: bool = False,
        lock_fields: List[str] | None = None,
        hot_path: bool = False,
        external_mutation_allowed: bool = False,
    ) -> None:
        """
        Register an internal Python callable as a hook.
        Called from agent.py __init__ as inline code is migrated in Phase 2.
        """
        order = self._next_registration_order()
        self._internal.append(InternalHook(
            event=event,
            handler=handler,
            hook_id=hook_id or f"internal:{event}:{order}",
            matcher=matcher,
            can_block=can_block,
            priority=self._coerce_priority(priority, default=100),
            fail_policy=fail_policy,
            mutates=[str(item) for item in (mutates or [])],
            can_short_circuit=bool(can_short_circuit),
            lock_fields=[str(item) for item in (lock_fields or [])],
            hot_path=bool(hot_path),
            external_mutation_allowed=bool(external_mutation_allowed),
            _registration_order=order,
        ))
        self._internal.sort(key=self._hook_sort_key)
        logger.debug("HookRunner: registered internal hook [%s] %s",
                     event, getattr(handler, "__name__", repr(handler)))

    def set_audit_sink(self, hook_audit_sink) -> None:
        """Attach or replace the optional hook audit sink after construction."""
        self._hook_audit_sink = hook_audit_sink


    def _matches(self, matcher_re, tool_name: str) -> bool:
        """Match compiled regex against tool_name (empty string always matches '.*')."""
        return bool(matcher_re.search(tool_name or ""))

    def _next_registration_order(self) -> int:
        order = self._registration_counter
        self._registration_counter += 1
        return order

    @staticmethod
    def _hook_sort_key(hook) -> tuple:
        return (getattr(hook, "priority", 100), getattr(hook, "_registration_order", 0))

    @staticmethod
    def _coerce_priority(value, default: int = 100) -> int:
        try:
            priority = int(value)
        except (TypeError, ValueError):
            return default
        if priority < 0:
            return default
        return priority

    def _validate_external_manifest(self, event: str, entry, order: int) -> Optional[dict]:
        if not isinstance(entry, dict) or "command" not in entry:
            return None

        hook_id = str(entry.get("id") or entry.get("hook_id") or f"{event}:{order}")
        if not re.fullmatch(r"[A-Za-z0-9_.:-]{1,128}", hook_id):
            logger.warning("HookRunner: invalid hook id %r under [%s]", hook_id, event)
            return None

        try:
            priority = int(entry.get("priority", 100))
        except (TypeError, ValueError):
            logger.warning("HookRunner: invalid priority for hook %s", hook_id)
            return None
        if priority < 0:
            logger.warning("HookRunner: negative priority for hook %s", hook_id)
            return None

        mode = str(entry.get("mode", "observe")).lower()
        if mode not in ALLOWED_HOOK_MODES:
            logger.warning("HookRunner: invalid mode %r for hook %s", mode, hook_id)
            return None

        fail_policy = str(entry.get("fail_policy", "open")).lower()
        if fail_policy not in ALLOWED_FAIL_POLICIES:
            logger.warning("HookRunner: invalid fail_policy %r for hook %s", fail_policy, hook_id)
            return None

        _skills = entry.get("skills", [])
        if isinstance(_skills, str):
            _skills = [_skills]
        if not isinstance(_skills, list):
            logger.warning("HookRunner: skills must be a list or string for hook %s", hook_id)
            return None

        permissions = entry.get("permissions", [])
        if isinstance(permissions, str):
            permissions = [permissions]
        if not isinstance(permissions, list):
            logger.warning("HookRunner: permissions must be a list or string for hook %s", hook_id)
            return None

        input_schema = entry.get("input_schema", {})
        output_schema = entry.get("output_schema", {})
        if not isinstance(input_schema, dict) or not isinstance(output_schema, dict):
            logger.warning("HookRunner: schemas must be objects for hook %s", hook_id)
            return None

        default_on_block = "hitl" if event == HOOK_PRE_TOOL_USE else "deny"
        on_block = str(entry.get("on_block", default_on_block)).lower()
        if on_block not in ALLOWED_ON_BLOCK_ACTIONS:
            logger.warning("HookRunner: invalid on_block %r for hook %s", on_block, hook_id)
            return None

        approval = entry.get("approval", {})
        if approval is None:
            approval = {}
        if not isinstance(approval, dict):
            logger.warning("HookRunner: approval must be an object for hook %s", hook_id)
            return None

        try:
            timeout_seconds = int(entry.get("timeout_seconds", 10))
        except (TypeError, ValueError):
            logger.warning("HookRunner: invalid timeout_seconds for hook %s", hook_id)
            return None
        if timeout_seconds <= 0:
            logger.warning("HookRunner: timeout_seconds must be positive for hook %s", hook_id)
            return None

        try:
            max_output_chars = int(entry.get("max_output_chars", 4096))
        except (TypeError, ValueError):
            logger.warning("HookRunner: invalid max_output_chars for hook %s", hook_id)
            return None
        if max_output_chars <= 0 or max_output_chars > MAX_HOOK_OUTPUT_CHARS:
            logger.warning("HookRunner: max_output_chars out of range for hook %s", hook_id)
            return None

        def _string_list(name: str) -> list[str]:
            value = entry.get(name, [])
            if isinstance(value, str):
                return [value]
            if isinstance(value, list):
                return [str(item) for item in value]
            logger.warning("HookRunner: %s must be a list or string for hook %s", name, hook_id)
            return []

        return {
            "hook_id": hook_id,
            "command": str(entry["command"]),
            "matcher": str(entry.get("matcher", ".*")),
            "skills": [str(s) for s in _skills],
            "priority": priority,
            "mode": mode,
            "fail_policy": fail_policy,
            "owner": str(entry.get("owner", "")),
            "permissions": [str(permission) for permission in permissions],
            "input_schema": input_schema,
            "output_schema": output_schema,
            "on_block": on_block,
            "approval": approval,
            "max_output_chars": max_output_chars,
            "block_on_nonzero": bool(entry.get("block_on_nonzero", False)),
            "timeout_seconds": timeout_seconds,
            "mutates": _string_list("mutates"),
            "can_short_circuit": bool(entry.get("can_short_circuit", False)),
            "lock_fields": _string_list("lock_fields"),
            "hot_path": bool(entry.get("hot_path", False)),
            "external_mutation_allowed": bool(entry.get("external_mutation_allowed", False)),
        }

    @staticmethod
    def _skill_matches(hook_skills: List[str], skill_name: str) -> bool:
        """
        Check if the current skill is in the hook's skills filter.
        Empty list = all skills (no filter). Case-insensitive exact match.
        """
        if not hook_skills:
            return True   # no filter = fires for all skills
        return (skill_name or "").lower() in [s.lower() for s in hook_skills]

    def _build_env(
        self,
        event: str,
        tool_name: str = "",
        tool_input=None,
        tool_output: str = "",
        response: str = "",
        session_ctx: Optional[dict] = None,
        # Step-level kwargs (orchestrator / workflow / parallel)
        step_result: str = "",
        step_success: Optional[bool] = None,
        step_duration_ms: int = 0,
        step_trace_id: str = "",
        error_msg: str = "",
    ) -> dict:
        """
        Build subprocess env dict with IAF_* variables for hook scripts.

        Tier 1 — always present:
          IAF_HOOK_EVENT, IAF_SESSION_ID, IAF_AGENT_ID, IAF_TENANT_ID,
          IAF_SKILL_NAME, IAF_USER_ID, IAF_AGENT_ROOT,
          IAF_PLATFORM_HOOKS_DIR  (framework dir of platform hook scripts; platform
            hook commands reference it as $IAF_PLATFORM_HOOKS_DIR. Distinct from
            IAF_AGENT_ROOT, which is the per-agent root scripts use for per-tenant output.)

        Tier 2 — tool-call hooks (PreToolUse / PostToolUse):
          IAF_TOOL_NAME, IAF_TOOL_INPUT, IAF_TOOL_OUTPUT, IAF_RESPONSE

        Tier 3 — step-level hooks (PreStep / PostStep / OnExecutionFailure):
          IAF_EXECUTION_MODE, IAF_RUN_ID,
          IAF_STEP_NUM, IAF_STEP_NAME, IAF_STEP_ACTION,
          IAF_TARGET_SKILL, IAF_AVAILABLE_SKILLS,
          IAF_STEP_RESULT, IAF_STEP_SUCCESS, IAF_STEP_DURATION_MS,
          IAF_STEP_TRACE_ID, IAF_ERROR_MSG
        """
        ctx = session_ctx or {}
        hook_ctx = build_hook_context(
            event=event,
            session_ctx=ctx,
            tool_name=tool_name,
            tool_input=tool_input,
            tool_output=tool_output,
            response=response,
            step_result=step_result,
            step_success=step_success,
            step_duration_ms=step_duration_ms,
            step_trace_id=step_trace_id,
            error_msg=error_msg,
        )
        _SAFE_SYSTEM_KEYS = (
            "PATH", "SYSTEMROOT", "SystemRoot", "PATHEXT",
            "TEMP", "TMP", "USERPROFILE", "HOME", "LANG",
            "COMSPEC", "PYTHONPATH", "PYTHONHOME",
            "VIRTUAL_ENV", "CONDA_PREFIX",
            "REDIS_URL",
        )
        _validated_pairs: list[tuple[str, str]] = []
        for _k in _SAFE_SYSTEM_KEYS:
            _v = os.environ.get(_k)
            if _v is None:
                continue
            try:
                if _k in ("PATH", "PYTHONPATH", "PYTHONHOME", "VIRTUAL_ENV",
                           "CONDA_PREFIX", "PATHEXT"):
                    _validated_pairs.append((_k, _sanitize_env_path_value(_v)))
                elif _k in ("TEMP", "TMP", "USERPROFILE", "HOME",
                             "SYSTEMROOT", "SystemRoot"):
                    _validated_pairs.append((_k, _sanitize_env_dir_path(_v)))
                elif _k in ("LANG",):
                    _validated_pairs.append((_k, _sanitize_env_lang_value(_v)))
                elif _k == "COMSPEC":
                    _validated_pairs.append((_k, _sanitize_env_shell_path(_v)))
                elif _k in ("REDIS_URL",):
                    _validated_pairs.append((_k, _sanitize_env_url_value(_v)))
            except ValueError:
                continue
        env = dict(_validated_pairs)

        env["IAF_HOOK_EVENT"]  = event
        env["IAF_SESSION_ID"]  = hook_ctx.get("session_id", "")
        env["IAF_AGENT_ID"]    = hook_ctx.get("agent_id", "")
        env["IAF_TENANT_ID"]   = hook_ctx.get("tenant_id", "")
        env["IAF_SKILL_NAME"]  = hook_ctx.get("skill_name", "")
        env["IAF_CURRENT_SKILL"] = hook_ctx.get("current_skill", "")
        env["IAF_USER_ID"]     = hook_ctx.get("user_id", "")
        env["IAF_AGENT_ROOT"]  = self._agent_root
        env["IAF_PLATFORM_HOOKS_DIR"] = self._platform_hooks_dir
        env["IAF_TRACE_ID"]    = hook_ctx.get("trace_id", "")
        env["IAF_PARENT_TRACE_ID"] = hook_ctx.get("parent_trace_id", "")
        env["IAF_ENTRYPOINT"]  = hook_ctx.get("entrypoint", "")
        env["IAF_QUEUE_ITEM_ID"] = hook_ctx.get("queue_item_id", "")
        env["IAF_QUEUE_EXEC_ID"] = str(hook_ctx.get("exec_id", ""))
        env["IAF_QUEUE_STATUS"] = str(hook_ctx.get("queue_status", ""))
        env["IAF_QUEUE_RETRY_COUNT"] = str(hook_ctx.get("retry_count", ""))
        env["IAF_QUEUE_WILL_DLQ"] = str(bool(hook_ctx.get("will_dlq", False))).lower()
        env["IAF_QUEUE_PRIORITY"] = str(hook_ctx.get("priority", ""))
        env["IAF_QUEUE_EVIDENCE_COUNT"] = str(hook_ctx.get("evidence_count", ""))
        env["IAF_ERROR_TYPE"] = str(hook_ctx.get("error_type", ""))
        env["IAF_CRON_JOB_ID"] = hook_ctx.get("cron_job_id", "")
        env["IAF_EVIDENCE_TRACE_ID"] = hook_ctx.get("evidence_trace_id", "")
        env["IAF_APPROVAL_ID"] = hook_ctx.get("approval_id", "")
        env["IAF_APPROVAL_DECISION"] = hook_ctx.get("decision", "")
        env["IAF_APPROVAL_DECIDED_BY"] = hook_ctx.get("decided_by", "")
        env["IAF_APPROVAL_DECISION_NOTE"] = hook_ctx.get("decision_note", "")[:500]
        env["IAF_APPROVAL_REASON"] = hook_ctx.get("approval_reason", "")[:500]
        env["IAF_RESUME_STATUS"] = hook_ctx.get("resume_status", "")
        env["IAF_INPUT_PREVIEW"] = hook_ctx.get("input_preview", "")
        env["IAF_OUTPUT_PREVIEW"] = hook_ctx.get("output_preview", "")
        env["IAF_RESPONSE_PREVIEW"] = hook_ctx.get("response_preview", "")
        env["IAF_QUERY"] = str(hook_ctx.get("query") or "")[:MAX_HOOK_AUDIT_PREVIEW_CHARS]
        env["IAF_TASK"] = str(hook_ctx.get("query") or hook_ctx.get("task") or "")[:MAX_HOOK_AUDIT_PREVIEW_CHARS]
        env["IAF_WORKSTREAM_NAME"] = str(hook_ctx.get("workstream_name") or hook_ctx.get("workstream") or "")
        env["IAF_MISSION_ITEM_ID"] = str(
            hook_ctx.get("mission_item_id") or hook_ctx.get("item_id") or hook_ctx.get("workstream_item") or ""
        )
        env["IAF_VIRTUAL_PATHS"] = json.dumps(hook_ctx.get("virtual_paths", []))

        env["IAF_TOOL_NAME"]   = tool_name
        redacted_tool_input = redact_hook_value(tool_input)
        if redacted_tool_input is None:
            env["IAF_TOOL_INPUT"] = ""
        elif isinstance(redacted_tool_input, dict):
            env["IAF_TOOL_INPUT"] = json.dumps(redacted_tool_input)
        elif isinstance(redacted_tool_input, str):
            try:
                parsed = ast.literal_eval(redacted_tool_input)
                env["IAF_TOOL_INPUT"] = json.dumps(redact_hook_value(parsed)) if isinstance(parsed, dict) else json.dumps(redacted_tool_input)
            except Exception:
                env["IAF_TOOL_INPUT"] = json.dumps(redacted_tool_input)
        else:
            env["IAF_TOOL_INPUT"] = json.dumps(redacted_tool_input)
        env["IAF_TOOL_OUTPUT"] = str(redact_hook_value(tool_output))[:4096]
        env["IAF_RESPONSE"]    = str(redact_hook_value(response))[:4096]

        env["IAF_EXECUTION_MODE"]    = hook_ctx.get("execution_mode", "")
        env["IAF_RUN_ID"]            = hook_ctx.get("run_id", "")
        env["IAF_STEP_NUM"]          = str(ctx.get("step_num", ""))
        env["IAF_STEP_NAME"]         = ctx.get("step_name", "")
        env["IAF_STEP_ACTION"]       = "call_skill"
        env["IAF_TARGET_SKILL"]      = ctx.get("step_name", "")
        env["IAF_AVAILABLE_SKILLS"]  = ctx.get("available_skills", "")
        env["IAF_STEP_RESULT"]       = step_result[:500]
        env["IAF_STEP_SUCCESS"]      = "true" if step_success else "false"
        env["IAF_STEP_DURATION_MS"]  = str(step_duration_ms)
        env["IAF_STEP_TRACE_ID"]     = step_trace_id
        env["IAF_ERROR_MSG"]         = error_msg[:500]

        return env

    def _emit_hook_audit(
        self,
        *,
        hook,
        ctx: dict,
        outcome: str,
        duration_ms: float,
        reason: str = "",
    ) -> None:
        """Emit a bounded hook audit span through a duck-typed trace emitter."""
        sink = self._hook_audit_sink
        trace_id = str(ctx.get("trace_id") or "")
        if not trace_id:
            return

        metadata = {
            "hook_event": str(ctx.get("hook_event") or getattr(hook, "event", "")),
            "hook_id": str(getattr(hook, "hook_id", "") or getattr(hook, "event", "")),
            "hook_kind": "external" if isinstance(hook, ExternalHook) else "internal",
            "priority": getattr(hook, "priority", 100),
            "mode": getattr(hook, "mode", "internal"),
            "fail_policy": getattr(hook, "fail_policy", ""),
            "entrypoint": str(ctx.get("entrypoint") or ""),
            "current_skill": str(ctx.get("current_skill") or ""),
            "tenant_id": str(ctx.get("tenant_id") or ""),
            "user_id": str(ctx.get("user_id") or ""),
            "agent_id": str(ctx.get("agent_id") or ""),
            "queue_item_id": str(ctx.get("queue_item_id") or ""),
            "queue_status": str(ctx.get("queue_status") or ""),
            "exec_id": str(ctx.get("exec_id") or ""),
            "outcome": outcome,
            "reason": (reason or "")[:500],
        }
        try:
            from agent_os.safe_path import reconstruct_path, validated_path

            from .capture_events import emit_hook_outcome

            data_root = validated_path(self._agent_root or ".", label="hook agent_root")
            for parent in [data_root, *data_root.parents]:
                candidate = parent / "enterprise_root"
                if candidate.exists():
                    data_root = reconstruct_path(candidate)
                    break
            from .runtime_bridge import default_tenant_id

            emit_hook_outcome(
                data_root=data_root,
                tenant_id=metadata["tenant_id"] or default_tenant_id(),
                agent_id=metadata["agent_id"],
                trace_id=trace_id,
                hook_id=metadata["hook_id"],
                hook_event=metadata["hook_event"],
                outcome=outcome,
                target_id=metadata["hook_id"],
                notes=reason,
                metadata=metadata,
            )
        except Exception as exc:
            logger.debug("HookRunner: capture hook outcome failed (non-fatal): %s", exc)
        if not sink or not hasattr(sink, "add_span"):
            return
        try:
            sink.add_span(
                trace_id=trace_id,
                span_type="hook",
                name=metadata["hook_id"],
                start_ms=time.time() * 1000 - duration_ms,
                duration_ms=duration_ms,
                status=outcome,
                input_preview=str(ctx.get("input_preview") or "")[:MAX_HOOK_AUDIT_PREVIEW_CHARS],
                output_preview=str(ctx.get("output_preview") or ctx.get("response_preview") or "")[:MAX_HOOK_AUDIT_PREVIEW_CHARS],
                metadata=metadata,
            )
        except Exception as exc:
            logger.debug("HookRunner: hook audit sink failed (non-fatal): %s", exc)

    @staticmethod
    def _context_from_env(env: dict) -> dict:
        return {
            "hook_event": env.get("IAF_HOOK_EVENT", ""),
            "trace_id": env.get("IAF_TRACE_ID", ""),
            "entrypoint": env.get("IAF_ENTRYPOINT", ""),
            "current_skill": env.get("IAF_CURRENT_SKILL", ""),
            "tenant_id": env.get("IAF_TENANT_ID", ""),
            "user_id": env.get("IAF_USER_ID", ""),
            "agent_id": env.get("IAF_AGENT_ID", ""),
            "input_preview": env.get("IAF_INPUT_PREVIEW", ""),
            "output_preview": env.get("IAF_OUTPUT_PREVIEW", ""),
            "response_preview": env.get("IAF_RESPONSE_PREVIEW", ""),
        }

    def _fail_policy_result(self, hook, reason: str) -> HookResult:
        """Translate a hook execution failure into a HookResult based on fail_policy.

        ``fail_policy='closed'`` is the security-safe behaviour: when the hook
        couldn't render an opinion (timeout, exec error, callable raised) treat
        it as a deny so the protected operation does not silently proceed past
        an unavailable guard. ``'open'`` keeps the legacy non-blocking behaviour.
        """
        hook_event = str(getattr(hook, "event", "") or "")
        hook_id = str(getattr(hook, "hook_id", "") or hook_event)
        on_block = str(getattr(hook, "on_block", "deny") or "deny")
        approval = getattr(hook, "approval", {}) or {}
        if getattr(hook, "fail_policy", "open") == "closed":
            return HookResult(
                blocked=True,
                reason=f"hook unavailable (fail_policy=closed): {reason}"[:500],
                hook_event=hook_event,
                hook_id=hook_id,
                on_block=on_block,
                approval=approval if isinstance(approval, dict) else {},
            )
        return HookResult(
            blocked=False,
            hook_event=hook_event,
            hook_id=hook_id,
            on_block=on_block,
            approval=approval if isinstance(approval, dict) else {},
        )

    def _hook_script_roots(self) -> List[Path]:
        """Trusted roots a hook script may live under.

        The platform hooks dir, plus the tenant tree that owns this agent
        (``<data_root>/tenants/<tenant>`` for an agent root of
        ``<data_root>/tenants/<tenant>/agents/<agent>``). Never the whole data
        root: that would let one tenant's hook config run another tenant's
        scripts. An agent root that does not follow that layout only trusts
        itself.
        """
        roots: List[Path] = []
        for raw, label in ((self._platform_hooks_dir, "platform hooks dir"),
                           (self._agent_root, "agent root")):
            if not raw:
                continue
            try:
                root = validated_path(raw, label=label)
            except _PathSecurityError:
                logger.warning("HookRunner: ignoring invalid %s for hook confinement", label)
                continue
            if label == "agent root":
                parents = root.parents
                if (len(parents) >= 4 and parents[0].name == "agents"
                        and parents[2].name == "tenants"):
                    root = parents[1]
            roots.append(root)
        return roots

    def _build_hook_argv(self, command: str, env: dict) -> List[str]:
        """Turn a hook ``command:`` template into a validated argv (no shell).

        Split the template first, then expand ``$VAR`` per token, so an env
        value can never add arguments or shell syntax. argv[0] must be an
        allowlisted interpreter, the script must resolve under a trusted root,
        and every remaining argument must match ``_HOOK_ARG_RE``.
        Raises HookCommandError when the command is not acceptable.
        """
        tokens = _split_hook_template(command or "")
        if not tokens:
            raise HookCommandError("hook command is empty")
        name, interpreter = _resolve_hook_interpreter(_expand_env_token(tokens[0], env))
        argv = [interpreter]
        rest = [_expand_env_token(tok, env) for tok in tokens[1:]]
        idx = 0
        allowed_flags = _INTERPRETER_FLAGS[name]
        while idx < len(rest) and rest[idx].startswith("-"):
            if rest[idx] not in allowed_flags:
                raise HookCommandError(
                    f"interpreter option {rest[idx][:16]!r} is not allowed; "
                    "a hook must run a script file"
                )
            argv.append(_reconstruct_str(rest[idx]))
            idx += 1
        if idx >= len(rest):
            raise HookCommandError("hook command does not name a script")
        argv.append(_confine_hook_script(rest[idx], self._hook_script_roots()))
        for arg in rest[idx + 1:]:
            if not _HOOK_ARG_RE.fullmatch(arg):
                raise HookCommandError("hook argument contains disallowed characters")
            argv.append(_reconstruct_str(arg))
        return argv

    def _run_external(self, hook: ExternalHook, env: dict) -> HookResult:
        """Execute one external command hook (argv, no shell) and return a HookResult."""
        start = time.time() * 1000
        audit_ctx = self._context_from_env(env)
        try:
            argv = self._build_hook_argv(hook.command, env)
        except HookCommandError as exc:
            logger.warning("HookRunner [%s]: hook %s rejected — %s",
                           hook.event, hook.hook_id, exc)
            self._emit_hook_audit(
                hook=hook,
                ctx=audit_ctx,
                outcome="error",
                duration_ms=time.time() * 1000 - start,
                reason=f"rejected hook command: {exc}",
            )
            return self._fail_policy_result(hook, f"rejected hook command: {exc}")
        try:
            logger.debug(
                "hook subprocess: hook_id=%s event=%s template=%r timeout=%s "
                "env_subset=%s",
                getattr(hook, "hook_id", ""),
                getattr(hook, "event", ""),
                hook.command,
                hook.timeout_seconds,
                {k: env.get(k) for k in (
                    "IAF_TOOL_NAME", "IAF_AGENT_ID", "IAF_TENANT_ID",
                    "IAF_SESSION_ID",
                )},
            )
            proc = subprocess.run(
                argv,
                shell=False,
                env=env,
                capture_output=True,
                text=True,
                timeout=hook.timeout_seconds,
                creationflags=_NO_WINDOW,
            )
            logger.debug(
                "hook subprocess result: hook_id=%s rc=%s stdout_len=%s "
                "stderr_len=%s elapsed_ms=%.1f",
                getattr(hook, "hook_id", ""),
                proc.returncode,
                len(proc.stdout or ""),
                len(proc.stderr or ""),
                time.time() * 1000 - start,
            )
            if proc.returncode != 0:
                if hook.block_on_nonzero:
                    reason = self._parse_hook_output(proc.stdout, proc.stderr, hook.max_output_chars)
                    logger.info("HookRunner [%s]: blocked (exit %d) — %s",
                                hook.event, proc.returncode, reason[:120])
                    self._emit_hook_audit(
                        hook=hook,
                        ctx=audit_ctx,
                        outcome="blocked",
                        duration_ms=time.time() * 1000 - start,
                        reason=reason,
                    )
                    return HookResult(
                        blocked=True,
                        reason=reason,
                        hook_event=hook.event,
                        hook_id=hook.hook_id,
                        on_block=hook.on_block,
                        approval=hook.approval,
                    )
                logger.debug("HookRunner [%s]: exit %d (non-blocking) stderr=%s",
                             hook.event, proc.returncode, proc.stderr[:200])
                reason = self._parse_hook_output(proc.stdout, proc.stderr, hook.max_output_chars)
                self._emit_hook_audit(
                    hook=hook,
                    ctx=audit_ctx,
                    outcome="error",
                    duration_ms=time.time() * 1000 - start,
                    reason=reason,
                )
                return self._fail_policy_result(hook, f"non-zero exit ({proc.returncode}): {reason}")

            # PostTurn: non-empty stdout on exit 0 → replacement response
            if hook.event == "PostTurn" and proc.stdout.strip():
                response = proc.stdout.strip()[:hook.max_output_chars]
                self._emit_hook_audit(
                    hook=hook,
                    ctx=audit_ctx,
                    outcome="ok",
                    duration_ms=time.time() * 1000 - start,
                )
                return HookResult(
                    blocked=False,
                    response=response,
                    hook_event=hook.event,
                    hook_id=hook.hook_id,
                    on_block=hook.on_block,
                    approval=hook.approval,
                )

            self._emit_hook_audit(
                hook=hook,
                ctx=audit_ctx,
                outcome="ok",
                duration_ms=time.time() * 1000 - start,
            )
            return HookResult(
                blocked=False,
                hook_event=hook.event,
                hook_id=hook.hook_id,
                on_block=hook.on_block,
                approval=hook.approval,
            )

        except subprocess.TimeoutExpired:
            logger.warning("HookRunner [%s]: timed out after %ds — fail_policy=%s",
                           hook.event, hook.timeout_seconds, hook.fail_policy)
            self._emit_hook_audit(
                hook=hook,
                ctx=audit_ctx,
                outcome="timeout",
                duration_ms=time.time() * 1000 - start,
                reason="timeout",
            )
            return self._fail_policy_result(hook, f"timeout after {hook.timeout_seconds}s")
        except Exception as exc:
            logger.warning("HookRunner [%s]: exec error — %s", hook.event, exc)
            self._emit_hook_audit(
                hook=hook,
                ctx=audit_ctx,
                outcome="error",
                duration_ms=time.time() * 1000 - start,
                reason=str(exc),
            )
            return self._fail_policy_result(hook, f"exec error: {exc}")

    def _run_internal(self, hook: InternalHook, ctx: dict) -> HookResult:
        """Call one internal Python hook and return a HookResult."""
        start = time.time() * 1000
        try:
            result = hook.handler(ctx)
            if hook.can_block and isinstance(result, HookResult):
                result.hook_event = result.hook_event or hook.event
                result.hook_id = result.hook_id or hook.hook_id or hook.event
                self._emit_hook_audit(
                    hook=hook,
                    ctx=ctx,
                    outcome="blocked" if result.blocked else "ok",
                    duration_ms=time.time() * 1000 - start,
                    reason=result.reason,
                )
                return result
        except Exception as exc:
            logger.warning("HookRunner [%s]: internal hook %r error — %s",
                           hook.event, getattr(hook.handler, "__name__", "?"), exc)
            self._emit_hook_audit(
                hook=hook,
                ctx=ctx,
                outcome="error",
                duration_ms=time.time() * 1000 - start,
                reason=str(exc),
            )
            return self._fail_policy_result(hook, f"internal error: {exc}")
        self._emit_hook_audit(
            hook=hook,
            ctx=ctx,
            outcome="ok",
            duration_ms=time.time() * 1000 - start,
        )
        return HookResult(
            blocked=False,
            hook_event=hook.event,
            hook_id=hook.hook_id,
        )

    def iter_model_call_hooks(self, event: str, *, skill_name: str = "") -> list[InternalHook]:
        """Return ordered in-process hooks for the model-call pipeline.

        The hot model boundary intentionally starts with in-process hooks only.
        External shell hooks remain available through the existing coarse
        lifecycle fan-out, but mutation/around behavior is kept off the
        subprocess path until payload limits and latency budgets are proven.
        """
        if event not in {HOOK_BEFORE_MODEL_CALL, HOOK_AROUND_MODEL_CALL, HOOK_AFTER_MODEL_CALL}:
            return []
        if not HookRunner._capability_hooks_enabled:
            return []
        return [
            hook
            for hook in self._internal
            if hook.event == event and self._skill_matches(hook.skills, skill_name)
        ]

    def run_model_call_hook(self, hook: InternalHook, ctx: dict):
        """Run an in-process model-call hook and return its raw value.

        Unlike the legacy lifecycle helpers, the model-call pipeline needs
        typed mutations, cached responses, and around-call wrappers. Returning
        the raw handler value keeps those contracts out of HookResult while
        still preserving audit and fail_policy behavior.
        """
        start = time.time() * 1000
        try:
            result = hook.handler(ctx)
            outcome = "blocked" if bool(getattr(result, "blocked", False)) else "ok"
            self._emit_hook_audit(
                hook=hook,
                ctx=ctx,
                outcome=outcome,
                duration_ms=time.time() * 1000 - start,
                reason=str(getattr(result, "reason", "") or "")[:500],
            )
            return result
        except Exception as exc:
            logger.warning("HookRunner [%s]: model-call hook %r error — %s",
                           hook.event, getattr(hook.handler, "__name__", "?"), exc)
            self._emit_hook_audit(
                hook=hook,
                ctx=ctx,
                outcome="error",
                duration_ms=time.time() * 1000 - start,
                reason=str(exc),
            )
            return self._fail_policy_result(hook, f"internal error: {exc}")

    def _fan_out_on_blocked(
        self,
        *,
        blocked_event: str,
        blocked_hook_id: str,
        reason: str,
        session_ctx: dict,
        tool_name: str = "",
        tool_input=None,
    ) -> None:
        """Notify OnBlocked observer hooks after a blocking deny.

        Fire-and-forget across both internal callables and external shell hooks.
        Never blocks the caller — even if every observer fails, the original
        deny still propagates. This gives audit/notification hooks a single
        seam to react to any block decision without wrapping every PreToolUse
        manually.
        """
        if not HookRunner._capability_hooks_enabled:
            return
        skill_name = session_ctx.get("skill_name", "")
        enriched_ctx = {
            **session_ctx,
            "blocked_event": blocked_event,
            "blocked_hook_id": blocked_hook_id,
            "blocked_reason": (reason or "")[:500],
            "decision": "blocked",
        }

        # Internal observers
        for hook in self._internal:
            if hook.event != HOOK_ON_BLOCKED:
                continue
            if not self._matches(hook._matcher_re, tool_name):
                continue
            if not self._skill_matches(hook.skills, skill_name):
                continue
            try:
                self._run_internal(hook, {
                    **build_hook_context(
                        event=HOOK_ON_BLOCKED,
                        session_ctx=enriched_ctx,
                        tool_name=tool_name,
                        tool_input=tool_input,
                    ),
                })
            except Exception as exc:  # pragma: no cover - defensive
                logger.debug("HookRunner [OnBlocked]: internal observer error — %s", exc)

        # External observers
        env = None
        for hook in self._external:
            if hook.event != HOOK_ON_BLOCKED:
                continue
            if not self._matches(hook._matcher_re, tool_name):
                continue
            if not self._skill_matches(hook.skills, skill_name):
                continue
            if env is None:
                env = self._build_env(
                    event=HOOK_ON_BLOCKED,
                    tool_name=tool_name,
                    tool_input=tool_input,
                    session_ctx=enriched_ctx,
                )
                env["IAF_BLOCKED_EVENT"] = blocked_event
                env["IAF_BLOCKED_HOOK_ID"] = blocked_hook_id
                env["IAF_BLOCKED_REASON"] = (reason or "")[:500]
            try:
                self._run_external(hook, env)
            except Exception as exc:  # pragma: no cover - defensive
                logger.debug("HookRunner [OnBlocked]: external observer error — %s", exc)

    @staticmethod
    def _parse_hook_output(stdout: str, stderr: str, max_chars: int = 500) -> str:
        """
        Extract a human-readable reason from hook script output.
        Tries JSON parsing first (looks for 'reason' or 'message' key),
        falls back to stderr then stdout as plain text. Max 500 chars.
        """
        try:
            data = json.loads(stdout)
            reason = data.get("reason") or data.get("message") or ""
            if reason:
                return str(reason)[:max_chars]
        except (json.JSONDecodeError, AttributeError, TypeError):
            pass
        text = (stderr or stdout or "").strip()
        return text[:max_chars]


    def run_pre_tool(
        self,
        tool_name: str,
        tool_input,
        session_ctx: dict,
    ) -> HookResult:
        """
        Fire all PreToolUse hooks synchronously.
        Fires for EVERY tool call (not just write/dangerous ones).
        Short-circuits on the first hook that returns blocked=True.
        Internal hooks fire before external (config.yaml) hooks.

        Batch 1: when ``tool_name`` is credential-bearing (see CREDENTIAL_BEARING_TOOLS)
        and the propagated context has no ``current_skill``, deny BEFORE any
        hook runs. The kernel still has its own hard deny — this hook-layer
        check provides defense-in-depth observability so the denial surfaces
        in the hook audit trail with a single ``hook_id`` instead of as a
        silent kernel rejection.

        Batch 4: when the platform kill switch is OFF, all hook checks are
        bypassed and the operation is allowed through. The kernel's own
        credential / external-access gates still apply.
        """
        if not HookRunner._capability_hooks_enabled:
            return HookResult(blocked=False)
        skill_name = session_ctx.get("skill_name", "")
        credential_bearing = _is_credential_bearing(tool_name)

        if credential_bearing:
            preflight = build_hook_context(
                event="PreToolUse",
                session_ctx=session_ctx,
                tool_name=tool_name,
                tool_input=tool_input,
                credential_bearing=True,
            )
            if preflight.get("enforce_fail_closed"):
                reason = (
                    "credential-bearing tool call denied: current_skill missing from hook context "
                    "(propagation contract violated; see hook_context.build_hook_context)"
                )
                logger.warning(
                    "HookRunner [PreToolUse]: fail-closed deny for credential-bearing tool %r — %s",
                    tool_name, reason,
                )
                self._fan_out_on_blocked(
                    blocked_event="PreToolUse",
                    blocked_hook_id="hook_runner:credential_fail_closed",
                    reason=reason,
                    session_ctx=session_ctx,
                    tool_name=tool_name,
                    tool_input=tool_input,
                )
                return HookResult(blocked=True, reason=reason)

        # Internal hooks first
        for hook in self._internal:
            if hook.event != "PreToolUse":
                continue
            if not self._matches(hook._matcher_re, tool_name):
                continue
            if not self._skill_matches(hook.skills, skill_name):
                continue
            result = self._run_internal(hook, {
                **build_hook_context(
                    event="PreToolUse",
                    session_ctx=session_ctx,
                    tool_name=tool_name,
                    tool_input=tool_input,
                    credential_bearing=credential_bearing,
                ),
            })
            if result.blocked:
                self._fan_out_on_blocked(
                    blocked_event="PreToolUse",
                    blocked_hook_id=hook.hook_id,
                    reason=result.reason,
                    session_ctx=session_ctx,
                    tool_name=tool_name,
                    tool_input=tool_input,
                )
                return result

        # External hooks (lazy-build env only if there are matching hooks)
        env = None
        for hook in self._external:
            if hook.event != "PreToolUse":
                continue
            if not self._matches(hook._matcher_re, tool_name):
                continue
            if not self._skill_matches(hook.skills, skill_name):
                continue
            if env is None:
                env = self._build_env(
                    event="PreToolUse",
                    tool_name=tool_name,
                    tool_input=tool_input,
                    session_ctx=session_ctx,
                )
            result = self._run_external(hook, env)
            if result.blocked:
                self._fan_out_on_blocked(
                    blocked_event="PreToolUse",
                    blocked_hook_id=hook.hook_id,
                    reason=result.reason,
                    session_ctx=session_ctx,
                    tool_name=tool_name,
                    tool_input=tool_input,
                )
                return result

        return HookResult(blocked=False)

    def run_post_tool(
        self,
        tool_name: str,
        tool_input,
        tool_output: str,
        session_ctx: dict,
    ) -> None:
        """
        Fire all PostToolUse hooks in a daemon thread (fire-and-forget).
        Called from trace_callback.on_tool_end() and on_tool_error().
        Never blocks. Returns immediately.
        """
        if not HookRunner._capability_hooks_enabled:
            return
        skill_name = session_ctx.get("skill_name", "")

        # Check if any hooks exist for this tool before spawning a thread
        has_internal = any(
            h.event == "PostToolUse"
            and self._matches(h._matcher_re, tool_name)
            and self._skill_matches(h.skills, skill_name)
            for h in self._internal
        )
        has_external = any(
            h.event == "PostToolUse"
            and self._matches(h._matcher_re, tool_name)
            and self._skill_matches(h.skills, skill_name)
            for h in self._external
        )
        if not has_internal and not has_external:
            return  # Fast path: no hooks configured, skip thread creation

        ctx = build_hook_context(
            event="PostToolUse",
            session_ctx=session_ctx,
            tool_name=tool_name,
            tool_input=tool_input,
            tool_output=tool_output,
        )

        def _fire():
            for hook in self._internal:
                if hook.event != "PostToolUse":
                    continue
                if not self._matches(hook._matcher_re, tool_name):
                    continue
                if not self._skill_matches(hook.skills, skill_name):
                    continue
                self._run_internal(hook, ctx)

            env = None
            for hook in self._external:
                if hook.event != "PostToolUse":
                    continue
                if not self._matches(hook._matcher_re, tool_name):
                    continue
                if not self._skill_matches(hook.skills, skill_name):
                    continue
                if env is None:
                    env = self._build_env(
                        event="PostToolUse",
                        tool_name=tool_name,
                        tool_input=tool_input,
                        tool_output=tool_output,
                        session_ctx=session_ctx,
                    )
                self._run_external(hook, env)

        threading.Thread(target=_fire, daemon=True).start()


    def _approval_context(
        self,
        *,
        event: str,
        approval_id: str,
        decision: str,
        decided_by: str,
        decision_note: str,
        reason: str,
        session_ctx: dict,
        resume_status: str = "",
        error_msg: str = "",
    ) -> dict:
        return build_hook_context(
            event=event,
            session_ctx={
                **session_ctx,
                "approval_id": approval_id,
                "decision": decision,
                "decided_by": decided_by,
                "decision_note": decision_note,
                "approval_reason": reason,
                "resume_status": resume_status,
            },
            decision=decision,
            error_msg=error_msg,
        )

    def run_on_approval_resolved(
        self,
        *,
        approval_id: str,
        decision: str,
        decided_by: str,
        decision_note: str,
        reason: str,
        session_ctx: dict,
    ) -> None:
        """Fire observe-only hooks after an HITL approval is resolved."""
        if not HookRunner._capability_hooks_enabled:
            return
        ctx = self._approval_context(
            event=HOOK_ON_APPROVAL_RESOLVED,
            approval_id=approval_id,
            decision=decision,
            decided_by=decided_by,
            decision_note=decision_note,
            reason=reason,
            session_ctx=session_ctx,
        )
        skill_name = ctx.get("skill_name", "")
        for hook in self._internal:
            if hook.event == HOOK_ON_APPROVAL_RESOLVED and self._skill_matches(hook.skills, skill_name):
                self._run_internal(hook, ctx)

        env = None
        for hook in self._external:
            if hook.event != HOOK_ON_APPROVAL_RESOLVED:
                continue
            if not self._skill_matches(hook.skills, skill_name):
                continue
            if env is None:
                env = self._build_env(event=HOOK_ON_APPROVAL_RESOLVED, session_ctx=ctx)
            self._run_external(hook, env)

    def run_before_approval_resume(
        self,
        *,
        approval_id: str,
        decision: str,
        decided_by: str,
        decision_note: str,
        reason: str,
        session_ctx: dict,
    ) -> HookResult:
        """Fire gateable hooks before restoring and resuming an HITL checkpoint."""
        if not HookRunner._capability_hooks_enabled:
            return HookResult(blocked=False)
        ctx = self._approval_context(
            event=HOOK_BEFORE_APPROVAL_RESUME,
            approval_id=approval_id,
            decision=decision,
            decided_by=decided_by,
            decision_note=decision_note,
            reason=reason,
            session_ctx=session_ctx,
        )
        skill_name = ctx.get("skill_name", "")

        for hook in self._internal:
            if hook.event != HOOK_BEFORE_APPROVAL_RESUME:
                continue
            if not self._skill_matches(hook.skills, skill_name):
                continue
            result = self._run_internal(hook, ctx)
            if result.blocked:
                self._fan_out_on_blocked(
                    blocked_event=HOOK_BEFORE_APPROVAL_RESUME,
                    blocked_hook_id=hook.hook_id,
                    reason=result.reason,
                    session_ctx=ctx,
                )
                return result

        env = None
        for hook in self._external:
            if hook.event != HOOK_BEFORE_APPROVAL_RESUME:
                continue
            if not self._skill_matches(hook.skills, skill_name):
                continue
            if env is None:
                env = self._build_env(event=HOOK_BEFORE_APPROVAL_RESUME, session_ctx=ctx)
            result = self._run_external(hook, env)
            if result.blocked:
                self._fan_out_on_blocked(
                    blocked_event=HOOK_BEFORE_APPROVAL_RESUME,
                    blocked_hook_id=hook.hook_id,
                    reason=result.reason,
                    session_ctx=ctx,
                )
                return result

        return HookResult(blocked=False)

    def run_after_approval_resume(
        self,
        *,
        approval_id: str,
        decision: str,
        decided_by: str,
        decision_note: str,
        reason: str,
        resume_status: str,
        session_ctx: dict,
        error_msg: str = "",
    ) -> None:
        """Fire observe-only hooks after an HITL resume attempt finishes."""
        if not HookRunner._capability_hooks_enabled:
            return
        ctx = self._approval_context(
            event=HOOK_AFTER_APPROVAL_RESUME,
            approval_id=approval_id,
            decision=decision,
            decided_by=decided_by,
            decision_note=decision_note,
            reason=reason,
            session_ctx=session_ctx,
            resume_status=resume_status,
            error_msg=error_msg,
        )
        skill_name = ctx.get("skill_name", "")
        for hook in self._internal:
            if hook.event == HOOK_AFTER_APPROVAL_RESUME and self._skill_matches(hook.skills, skill_name):
                self._run_internal(hook, ctx)

        env = None
        for hook in self._external:
            if hook.event != HOOK_AFTER_APPROVAL_RESUME:
                continue
            if not self._skill_matches(hook.skills, skill_name):
                continue
            if env is None:
                env = self._build_env(event=HOOK_AFTER_APPROVAL_RESUME, session_ctx=ctx)
            self._run_external(hook, env)

    def run_post_turn_result(self, response: str, session_ctx: dict) -> HookResult:
        """
        Fire all PostTurn hooks synchronously.
        Returns a HookResult with the possibly modified response.
        If a hook returns blocked=True, callers decide how to handle the gate.
        """
        if not HookRunner._capability_hooks_enabled:
            return HookResult(blocked=False, response=response)
        env = None
        skill_name = session_ctx.get("skill_name", "")

        # Internal hooks first
        for hook in self._internal:
            if hook.event != "PostTurn":
                continue
            if not self._skill_matches(hook.skills, skill_name):
                continue
            result = self._run_internal(
                hook,
                build_hook_context(event="PostTurn", session_ctx=session_ctx, response=response),
            )
            if result.blocked:
                logger.info("HookRunner [PostTurn]: internal hook blocked response — %s",
                            result.reason[:80])
                self._fan_out_on_blocked(
                    blocked_event="PostTurn",
                    blocked_hook_id=hook.hook_id,
                    reason=result.reason,
                    session_ctx=session_ctx,
                )
                return result
            if result.response is not None:
                response = result.response

        # External hooks
        for hook in self._external:
            if hook.event != "PostTurn":
                continue
            if not self._skill_matches(hook.skills, skill_name):
                continue
            if env is None:
                env = self._build_env(
                    event="PostTurn",
                    response=response,
                    session_ctx=session_ctx,
                )
            result = self._run_external(hook, env)
            if result.blocked:
                logger.info("HookRunner [PostTurn]: hook blocked response — %s",
                            result.reason[:80])
                self._fan_out_on_blocked(
                    blocked_event="PostTurn",
                    blocked_hook_id=hook.hook_id,
                    reason=result.reason,
                    session_ctx=session_ctx,
                )
                return result
            if result.response is not None:
                response = result.response

        return HookResult(blocked=False, response=response)

    def run_post_turn(self, response: str, session_ctx: dict) -> str:
        """
        Fire all PostTurn hooks synchronously.
        Returns the (possibly modified) response string.
        If a hook returns blocked=True, returns a compliance error message instead.
        If a hook returns a non-None response, it replaces the agent response.
        """
        result = self.run_post_turn_result(response=response, session_ctx=session_ctx)
        if result.blocked:
            return f"⚠️ Response blocked by compliance policy: {result.reason}"
        return result.response if result.response is not None else response

    def run_post_sampling(
        self,
        session_ctx: dict,
        external_only: bool = False,
    ) -> None:
        """
        Fire all PostSampling hooks in a daemon thread (fire-and-forget).
        external_only=True (Phase 1): skips internal hooks to avoid double-firing
        while the inline code in _async_extract_and_log() still runs.
        Switch to external_only=False in Phase 2 after inline code is deleted.
        """
        if not HookRunner._capability_hooks_enabled:
            return
        skill_name = session_ctx.get("skill_name", "")
        has_internal = (not external_only and
                        any(h.event == "PostSampling" and self._skill_matches(h.skills, skill_name)
                            for h in self._internal))
        has_external = any(h.event == "PostSampling" and self._skill_matches(h.skills, skill_name)
                           for h in self._external)
        if not has_internal and not has_external:
            return  # Fast path: no hooks configured, skip thread creation

        def _fire():
            if not external_only:
                for hook in self._internal:
                    if hook.event != "PostSampling":
                        continue
                    if not self._skill_matches(hook.skills, skill_name):
                        continue
                    self._run_internal(
                        hook,
                        build_hook_context(
                            event="PostSampling",
                            session_ctx=session_ctx,
                            response=session_ctx.get("response", ""),
                        ),
                    )

            env = None
            for hook in self._external:
                if hook.event != "PostSampling":
                    continue
                if not self._skill_matches(hook.skills, skill_name):
                    continue
                if env is None:
                    env = self._build_env(
                        event="PostSampling",
                        response=session_ctx.get("response", ""),
                        session_ctx=session_ctx,
                    )
                self._run_external(hook, env)

        threading.Thread(target=_fire, daemon=True).start()


    def run_pre_step(
        self,
        step_num: int,
        skill_name: str,
        session_ctx: dict,
    ) -> HookResult:
        """
        Fire all PreStep hooks synchronously.
        Short-circuits on the first blocked=True result.
        A blocked PreStep prevents the subagent from running; the reason is
        recorded in the step_log so the manager LLM can adapt.
        """
        if not HookRunner._capability_hooks_enabled:
            return HookResult(blocked=False)
        env = None
        for hook in self._external:
            if hook.event != HOOK_PRE_STEP:
                continue
            if not self._skill_matches(hook.skills, skill_name):
                continue
            if env is None:
                env = self._build_env(event=HOOK_PRE_STEP, session_ctx=session_ctx)
            result = self._run_external(hook, env)
            if result.blocked:
                self._fan_out_on_blocked(
                    blocked_event=HOOK_PRE_STEP,
                    blocked_hook_id=hook.hook_id,
                    reason=result.reason,
                    session_ctx=session_ctx,
                )
                return result

        for hook in self._internal:
            if hook.event != HOOK_PRE_STEP:
                continue
            if not self._skill_matches(hook.skills, skill_name):
                continue
            result = self._run_internal(
                hook,
                build_hook_context(
                    event=HOOK_PRE_STEP,
                    session_ctx={"step_num": step_num, "skill_name": skill_name, **session_ctx},
                ),
            )
            if result.blocked:
                self._fan_out_on_blocked(
                    blocked_event=HOOK_PRE_STEP,
                    blocked_hook_id=hook.hook_id,
                    reason=result.reason,
                    session_ctx=session_ctx,
                )
                return result

        return HookResult(blocked=False)

    def run_post_step(
        self,
        step_num: int,
        skill_name: str,
        step_result: str,
        success: bool,
        duration_ms: int,
        trace_id: str,
        session_ctx: dict,
    ) -> HookResult:
        """
        Fire all PostStep hooks synchronously and collect feedback.
        Returns a HookResult whose .feedback field (if set) is appended to the
        OrchestratorStep and surfaced to the manager LLM on its next decision
        — enabling hook-guided recovery without restarting steps.
        """
        if not HookRunner._capability_hooks_enabled:
            return HookResult(blocked=False)
        combined_feedback: list = []
        env = None

        for hook in self._external:
            if hook.event != HOOK_POST_STEP:
                continue
            if not self._skill_matches(hook.skills, skill_name):
                continue
            if env is None:
                env = self._build_env(
                    event=HOOK_POST_STEP,
                    session_ctx=session_ctx,
                    step_result=step_result,
                    step_success=success,
                    step_duration_ms=duration_ms,
                    step_trace_id=trace_id,
                )
            result = self._run_external(hook, env)
            if result.feedback:
                combined_feedback.append(result.feedback)

        for hook in self._internal:
            if hook.event != HOOK_POST_STEP:
                continue
            if not self._skill_matches(hook.skills, skill_name):
                continue
            result = self._run_internal(
                hook,
                build_hook_context(
                    event=HOOK_POST_STEP,
                    session_ctx={"step_num": step_num, "skill_name": skill_name, **session_ctx},
                    step_result=step_result,
                    step_success=success,
                    step_duration_ms=duration_ms,
                    step_trace_id=trace_id,
                    duration_ms=duration_ms,
                ),
            )
            if result.feedback:
                combined_feedback.append(result.feedback)

        return HookResult(
            blocked=False,
            feedback=" | ".join(combined_feedback) if combined_feedback else None,
        )

    def run_on_exec_failure(
        self,
        step_num: int,
        skill_name: str,
        error_msg: str,
        session_ctx: dict,
    ) -> None:
        """
        Fire all OnExecutionFailure hooks in a daemon thread (fire-and-forget).
        Use for compensation / saga rollback, alerting, or audit on step exceptions.
        Never blocks the orchestrator loop.
        """
        if not HookRunner._capability_hooks_enabled:
            return
        has_hooks = any(
            h.event == HOOK_ON_EXEC_FAILURE and self._skill_matches(h.skills, skill_name)
            for h in (self._external + self._internal)
        )
        if not has_hooks:
            return

        def _fire():
            env = None
            for hook in self._external:
                if hook.event != HOOK_ON_EXEC_FAILURE:
                    continue
                if not self._skill_matches(hook.skills, skill_name):
                    continue
                if env is None:
                    env = self._build_env(
                        event=HOOK_ON_EXEC_FAILURE,
                        session_ctx=session_ctx,
                        error_msg=error_msg,
                    )
                self._run_external(hook, env)

            for hook in self._internal:
                if hook.event != HOOK_ON_EXEC_FAILURE:
                    continue
                if not self._skill_matches(hook.skills, skill_name):
                    continue
                self._run_internal(
                    hook,
                    build_hook_context(
                        event=HOOK_ON_EXEC_FAILURE,
                        session_ctx={"step_num": step_num, "skill_name": skill_name, **session_ctx},
                        error_msg=error_msg,
                    ),
                )

        threading.Thread(target=_fire, daemon=True).start()


    def _fire_lifecycle(
        self,
        *,
        event: str,
        session_ctx: dict,
        gateable: bool = False,
        extra_ctx: Optional[dict] = None,
    ) -> HookResult:
        """Common fan-out used by Batch 2 lifecycle events.

        Returns the first blocking HookResult (or non-blocked HookResult if
        nothing blocks). Caller decides whether to act on `.blocked` — for
        observe-only sites, ignore the result; for gateable sites, honour it.
        """
        if not HookRunner._capability_hooks_enabled:
            return HookResult(blocked=False)
        if event not in ALLOWED_HOOK_EVENTS:
            return HookResult(blocked=False)

        skill_name = session_ctx.get("skill_name", "")
        merged_ctx = {**session_ctx, **(extra_ctx or {})}

        for hook in self._internal:
            if hook.event != event:
                continue
            if not self._skill_matches(hook.skills, skill_name):
                continue
            result = self._run_internal(
                hook,
                build_hook_context(event=event, session_ctx=merged_ctx),
            )
            if gateable and result.blocked:
                self._fan_out_on_blocked(
                    blocked_event=event,
                    blocked_hook_id=hook.hook_id,
                    reason=result.reason,
                    session_ctx=merged_ctx,
                )
                return result

        env = None
        for hook in self._external:
            if hook.event != event:
                continue
            if not self._skill_matches(hook.skills, skill_name):
                continue
            if env is None:
                env = self._build_env(event=event, session_ctx=merged_ctx)
            result = self._run_external(hook, env)
            if gateable and result.blocked:
                self._fan_out_on_blocked(
                    blocked_event=event,
                    blocked_hook_id=hook.hook_id,
                    reason=result.reason,
                    session_ctx=merged_ctx,
                )
                return result

        return HookResult(blocked=False)

    def run_before_turn(self, session_ctx: dict) -> HookResult:
        """Fire BeforeTurn hooks. Gateable — caller may honour deny to skip the turn."""
        return self._fire_lifecycle(
            event=HOOK_BEFORE_TURN,
            session_ctx=session_ctx,
            gateable=True,
        )

    def run_on_turn_end(self, session_ctx: dict, *, response: str = "", error_msg: str = "") -> None:
        """Fire OnTurnEnd hooks (observe-only)."""
        self._fire_lifecycle(
            event=HOOK_ON_TURN_END,
            session_ctx={**session_ctx, "response": response, "error_msg": error_msg},
            gateable=False,
        )

    def run_on_error(self, session_ctx: dict, *, error_msg: str) -> None:
        """Fire OnError hooks (observe-only, fire-and-forget for caught exceptions)."""
        self._fire_lifecycle(
            event=HOOK_ON_ERROR,
            session_ctx={**session_ctx, "error_msg": error_msg, "error": error_msg},
            gateable=False,
        )

    def run_before_model_call(self, session_ctx: dict, *, model_role: str = "", model_name: str = "") -> HookResult:
        """Fire BeforeModelCall hooks. Gateable but callers default to observe-only."""
        return self._fire_lifecycle(
            event=HOOK_BEFORE_MODEL_CALL,
            session_ctx={**session_ctx, "model_role": model_role, "model_name": model_name},
            gateable=True,
        )

    def run_after_model_call(
        self,
        session_ctx: dict,
        *,
        model_role: str = "",
        model_name: str = "",
        prompt_tokens: int = 0,
        completion_tokens: int = 0,
        duration_ms: int = 0,
    ) -> None:
        """Fire AfterModelCall hooks (observe-only). Carries token + latency telemetry."""
        self._fire_lifecycle(
            event=HOOK_AFTER_MODEL_CALL,
            session_ctx={
                **session_ctx,
                "model_role": model_role,
                "model_name": model_name,
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "duration_ms": duration_ms,
            },
            gateable=False,
        )

    def run_before_schedule_fire(self, session_ctx: dict, *, job_name: str = "", cron_expr: str = "") -> HookResult:
        """Fire BeforeScheduleFire hooks. Gateable — caller may honour deny to skip the firing."""
        return self._fire_lifecycle(
            event=HOOK_BEFORE_SCHEDULE_FIRE,
            session_ctx={**session_ctx, "job_name": job_name, "cron_expr": cron_expr},
            gateable=True,
        )

    def run_after_schedule_fire(
        self,
        session_ctx: dict,
        *,
        job_name: str = "",
        duration_ms: int = 0,
        response: str = "",
    ) -> None:
        """Fire AfterScheduleFire hooks (observe-only) after a successful cron run."""
        self._fire_lifecycle(
            event=HOOK_AFTER_SCHEDULE_FIRE,
            session_ctx={
                **session_ctx,
                "job_name": job_name,
                "duration_ms": duration_ms,
                "response": response,
            },
            gateable=False,
        )

    def run_on_schedule_error(
        self,
        session_ctx: dict,
        *,
        job_name: str = "",
        error_msg: str = "",
        duration_ms: int = 0,
    ) -> None:
        """Fire OnScheduleError hooks (observe-only) when a cron run raised."""
        self._fire_lifecycle(
            event=HOOK_ON_SCHEDULE_ERROR,
            session_ctx={
                **session_ctx,
                "job_name": job_name,
                "error_msg": error_msg,
                "error": error_msg,
                "duration_ms": duration_ms,
            },
            gateable=False,
        )


    def run_before_queue_item_start(
        self,
        session_ctx: dict,
        *,
        item_id: str = "",
        exec_id: str = "",
        skill_name: str = "",
        queue_status: str = "running",
        priority: str = "",
        retry_count: int = 0,
        payload_preview: str = "",
        **extra,
    ) -> HookResult:
        return self._fire_queue_lifecycle(
            event=HOOK_BEFORE_QUEUE_ITEM_START,
            session_ctx=session_ctx,
            item_id=item_id,
            exec_id=exec_id,
            skill_name=skill_name,
            queue_status=queue_status,
            priority=priority,
            retry_count=retry_count,
            payload_preview=payload_preview,
            **extra,
        )

    def run_after_queue_item_complete(
        self,
        session_ctx: dict,
        *,
        item_id: str = "",
        exec_id: str = "",
        skill_name: str = "",
        queue_status: str = "done",
        duration_ms: int = 0,
        result_summary: str = "",
        payload_preview: str = "",
        evidence_trace_id: str = "",
        evidence_count: int = 0,
        **extra,
    ) -> None:
        self._fire_queue_lifecycle(
            event=HOOK_AFTER_QUEUE_ITEM_COMPLETE,
            session_ctx=session_ctx,
            item_id=item_id,
            exec_id=exec_id,
            skill_name=skill_name,
            queue_status=queue_status,
            duration_ms=duration_ms,
            result_summary=result_summary,
            payload_preview=payload_preview,
            evidence_trace_id=evidence_trace_id,
            evidence_count=evidence_count,
            **extra,
        )

    def run_on_queue_item_error(
        self,
        session_ctx: dict,
        *,
        item_id: str = "",
        exec_id: str = "",
        skill_name: str = "",
        queue_status: str = "failed",
        error_msg: str = "",
        error_type: str = "",
        retry_count: int = 0,
        will_dlq: bool = False,
        duration_ms: int = 0,
        payload_preview: str = "",
        **extra,
    ) -> None:
        self._fire_queue_lifecycle(
            event=HOOK_ON_QUEUE_ITEM_ERROR,
            session_ctx=session_ctx,
            item_id=item_id,
            exec_id=exec_id,
            skill_name=skill_name,
            queue_status=queue_status,
            error_msg=error_msg,
            error_type=error_type,
            retry_count=retry_count,
            will_dlq=will_dlq,
            duration_ms=duration_ms,
            payload_preview=payload_preview,
            **extra,
        )

    def run_before_queue_retry(
        self,
        session_ctx: dict,
        *,
        item_id: str = "",
        exec_id: str = "",
        skill_name: str = "",
        retry_count: int = 0,
        error_msg: str = "",
        error_type: str = "",
        payload_preview: str = "",
        **extra,
    ) -> None:
        self._fire_queue_lifecycle(
            event=HOOK_BEFORE_QUEUE_RETRY,
            session_ctx=session_ctx,
            item_id=item_id,
            exec_id=exec_id,
            skill_name=skill_name,
            queue_status="queued",
            retry_count=retry_count,
            error_msg=error_msg,
            error_type=error_type,
            payload_preview=payload_preview,
            **extra,
        )

    def run_on_queue_dlq(
        self,
        session_ctx: dict,
        *,
        item_id: str = "",
        exec_id: str = "",
        skill_name: str = "",
        failure_reason: str = "",
        error_msg: str = "",
        error_type: str = "",
        retry_count: int = 0,
        payload_preview: str = "",
        **extra,
    ) -> None:
        self._fire_queue_lifecycle(
            event=HOOK_ON_QUEUE_DLQ,
            session_ctx=session_ctx,
            item_id=item_id,
            exec_id=exec_id,
            skill_name=skill_name,
            queue_status="dlq",
            failure_reason=failure_reason,
            error_msg=error_msg,
            error_type=error_type,
            retry_count=retry_count,
            will_dlq=True,
            payload_preview=payload_preview,
            **extra,
        )

    def run_on_queue_hitl_pending(
        self,
        session_ctx: dict,
        *,
        item_id: str = "",
        exec_id: str = "",
        skill_name: str = "",
        approval_id: str = "",
        prompt: str = "",
        payload_preview: str = "",
        **extra,
    ) -> None:
        self._fire_queue_lifecycle(
            event=HOOK_ON_QUEUE_HITL_PENDING,
            session_ctx=session_ctx,
            item_id=item_id,
            exec_id=exec_id,
            skill_name=skill_name,
            queue_status="awaiting_human",
            approval_id=approval_id,
            approval_reason=prompt,
            payload_preview=payload_preview,
            **extra,
        )

    def _fire_queue_lifecycle(
        self,
        *,
        event: str,
        session_ctx: dict,
        item_id: str = "",
        exec_id: str = "",
        skill_name: str = "",
        queue_status: str = "",
        result_summary: str = "",
        payload_preview: str = "",
        error_msg: str = "",
        evidence_trace_id: str = "",
        **extra,
    ) -> HookResult:
        ctx = {
            **session_ctx,
            **extra,
            "entrypoint": session_ctx.get("entrypoint") or "queue",
            "queue_item_id": item_id or session_ctx.get("queue_item_id", ""),
            "item_id": item_id or session_ctx.get("item_id", ""),
            "exec_id": exec_id or session_ctx.get("exec_id", ""),
            "skill_name": skill_name or session_ctx.get("skill_name", ""),
            "current_skill": skill_name or session_ctx.get("current_skill") or session_ctx.get("skill_name", ""),
            "queue_status": queue_status,
            "input_preview": str(redact_hook_value(payload_preview or session_ctx.get("input_preview", "")))[:MAX_HOOK_AUDIT_PREVIEW_CHARS],
            "output_preview": str(redact_hook_value(result_summary or error_msg or session_ctx.get("output_preview", "")))[:MAX_HOOK_AUDIT_PREVIEW_CHARS],
            "response_preview": str(redact_hook_value(result_summary or session_ctx.get("response_preview", "")))[:MAX_HOOK_AUDIT_PREVIEW_CHARS],
            "response": result_summary,
            "error_msg": error_msg,
            "error": error_msg,
            "evidence_trace_id": evidence_trace_id or session_ctx.get("evidence_trace_id", ""),
        }
        self._fire_lifecycle(event=event, session_ctx=ctx, gateable=False)
        return HookResult(blocked=False)


    def run_before_mission_start(
        self,
        session_ctx: dict,
        *,
        workstream_name: str = "",
        owner: str = "",
        total_items: int = 0,
        skill: str = "",
    ) -> HookResult:
        """Fire BeforeMissionStart. Gateable — caller may halt first activation."""
        return self._fire_lifecycle(
            event=HOOK_BEFORE_MISSION_START,
            session_ctx={
                **session_ctx,
                "workstream_name": workstream_name,
                "owner": owner,
                "total_items": total_items,
                "skill": skill,
            },
            gateable=True,
        )

    def run_on_mission_item_failed(
        self,
        session_ctx: dict,
        *,
        workstream_name: str = "",
        item_id: str = "",
        attempts: int = 0,
        error_msg: str = "",
    ) -> None:
        """Fire OnMissionItemFailed (observe-only) when an item exhausts retries."""
        self._fire_lifecycle(
            event=HOOK_ON_MISSION_ITEM_FAILED,
            session_ctx={
                **session_ctx,
                "workstream_name": workstream_name,
                "item_id": item_id,
                "attempts": attempts,
                "error_msg": error_msg,
                "error": error_msg,
            },
            gateable=False,
        )

    def run_on_mission_complete(
        self,
        session_ctx: dict,
        *,
        workstream_name: str = "",
        duration_total_sec: int = 0,
        items_done: int = 0,
        items_failed: int = 0,
        items_escalated: int = 0,
    ) -> None:
        """Fire OnMissionComplete (observe-only) when a workstream reaches terminal state."""
        self._fire_lifecycle(
            event=HOOK_ON_MISSION_COMPLETE,
            session_ctx={
                **session_ctx,
                "workstream_name": workstream_name,
                "duration_total_sec": duration_total_sec,
                "items_done": items_done,
                "items_failed": items_failed,
                "items_escalated": items_escalated,
            },
            gateable=False,
        )


    def run_on_decomposition_complete(
        self,
        session_ctx: dict,
        *,
        question: str = "",
        angles: Optional[list] = None,
        target_skills: Optional[list] = None,
        confidence: str = "",
        confidence_reason: str = "",
        decomposer_model: str = "",
        tokens_used: int = 0,
    ) -> dict:
        """Fire OnDecompositionComplete (gateable).

        Tenants can register a blocking handler with fail_policy=closed that
        denies decompositions below a confidence threshold or above a cost
        estimate. By default observe-only — emits to audit log and any
        learning handlers, no behavioural change.

        Returns the lifecycle envelope ({allow: bool, reason: str}); callers
        SHOULD check ``allow`` before proceeding to workstream creation.
        """
        return self._fire_lifecycle(
            event=HOOK_ON_DECOMPOSITION_COMPLETE,
            session_ctx={
                **session_ctx,
                "question": (question or "")[:500],
                "angles": angles or [],
                "target_skills": target_skills or [],
                "confidence": confidence,
                "confidence_reason": (confidence_reason or "")[:500],
                "decomposer_model": decomposer_model,
                "tokens_used": int(tokens_used or 0),
            },
            gateable=True,
        )

    def run_on_research_workstream_created(
        self,
        session_ctx: dict,
        *,
        workstream_name: str = "",
        source_question: str = "",
        parent_session_id: str = "",
        parent_trace_id: str = "",
        item_count: int = 0,
        estimated_cost_usd: float = 0.0,
        target_skills: Optional[list] = None,
        decomposer_confidence: str = "",
    ) -> dict:
        """Fire OnResearchWorkstreamCreated (gateable).

        Fires from the /api/workstreams POST handler when meta.source ==
        "research_orchestrator". Tenants can register a blocking handler
        that denies the launch (e.g. user has spent >$N this month, or
        item_count exceeds a per-tenant cap). By default observe-only —
        emits for lineage tracking + cost telemetry, no behavioural change.

        Returns the lifecycle envelope; callers SHOULD check ``allow``
        before committing the workstream YAML to disk.
        """
        return self._fire_lifecycle(
            event=HOOK_ON_RESEARCH_WORKSTREAM_CREATED,
            session_ctx={
                **session_ctx,
                "workstream_name": workstream_name,
                "source_question": (source_question or "")[:500],
                "parent_session_id": parent_session_id,
                "parent_trace_id": parent_trace_id,
                "item_count": int(item_count or 0),
                "estimated_cost_usd": float(estimated_cost_usd or 0.0),
                "target_skills": target_skills or [],
                "decomposer_confidence": decomposer_confidence,
            },
            gateable=True,
        )


    @staticmethod
    def _background_ctx(session_ctx: Optional[dict]) -> dict:
        """Best-effort context for background-task events.

        Marks ``background_context_missing=True`` when no session/tenant/user
        was propagated, so observers can distinguish ambient writes (audit
        sweeps, demo seeds) from in-flight request writes.
        """
        ctx = dict(session_ctx or {})
        has_identity = any(
            ctx.get(k) for k in ("session_id", "trace_id", "tenant_id", "user_id")
        )
        if not has_identity:
            ctx["background_context_missing"] = True
        return ctx

    def run_on_knowledge_entry_pending(
        self,
        *,
        skill_name: str = "",
        entry_kind: str = "",
        entry_preview: str = "",
        session_ctx: Optional[dict] = None,
    ) -> None:
        """Fire OnKnowledgeEntryPending when implicit learning queues a pending_review entry."""
        ctx = self._background_ctx(session_ctx)
        ctx.update({
            "skill_name": skill_name or ctx.get("skill_name") or "",
            "entry_kind": entry_kind,
            "entry_preview": str(entry_preview or "")[:500],
        })
        self._fire_lifecycle(
            event=HOOK_ON_KNOWLEDGE_ENTRY_PENDING,
            session_ctx=ctx,
            gateable=False,
        )

    def run_on_memory_write(
        self,
        *,
        store: str = "",
        key: str = "",
        value_preview: str = "",
        session_ctx: Optional[dict] = None,
    ) -> None:
        """Fire OnMemoryWrite for any non-tool memory mutation (implicit learning, plan cache, …)."""
        ctx = self._background_ctx(session_ctx)
        ctx.update({
            "memory_store": store,
            "memory_key": key,
            "value_preview": str(value_preview or "")[:500],
        })
        self._fire_lifecycle(
            event=HOOK_ON_MEMORY_WRITE,
            session_ctx=ctx,
            gateable=False,
        )

    def run_on_skill_gap_detected(
        self,
        *,
        skill_name: str = "",
        gap_summary: str = "",
        severity: str = "",
        session_ctx: Optional[dict] = None,
    ) -> None:
        """Fire OnSkillGapDetected when offline self-evolution analysis finds a missing capability."""
        ctx = self._background_ctx(session_ctx)
        ctx.update({
            "skill_name": skill_name or ctx.get("skill_name") or "",
            "gap_summary": str(gap_summary or "")[:500],
            "severity": severity,
        })
        self._fire_lifecycle(
            event=HOOK_ON_SKILL_GAP_DETECTED,
            session_ctx=ctx,
            gateable=False,
        )

    def run_on_self_evolution_pass(
        self,
        *,
        pass_id: str = "",
        skills_analyzed: int = 0,
        gaps_found: int = 0,
        duration_ms: int = 0,
        session_ctx: Optional[dict] = None,
    ) -> None:
        """Fire OnSelfEvolutionPass once per offline self-evolution sweep."""
        ctx = self._background_ctx(session_ctx)
        ctx.update({
            "pass_id": pass_id,
            "skills_analyzed": int(skills_analyzed or 0),
            "gaps_found": int(gaps_found or 0),
            "duration_ms": int(duration_ms or 0),
        })
        self._fire_lifecycle(
            event=HOOK_ON_SELF_EVOLUTION_PASS,
            session_ctx=ctx,
            gateable=False,
        )

    def run_on_background_task_error(
        self,
        *,
        task_name: str = "",
        error_msg: str = "",
        session_ctx: Optional[dict] = None,
    ) -> None:
        """Fire OnBackgroundTaskError when any background sweep / writer raises."""
        ctx = self._background_ctx(session_ctx)
        ctx.update({
            "task_name": task_name,
            "error_msg": str(error_msg or "")[:500],
            "error": str(error_msg or "")[:500],
        })
        self._fire_lifecycle(
            event=HOOK_ON_BACKGROUND_TASK_ERROR,
            session_ctx=ctx,
            gateable=False,
        )
