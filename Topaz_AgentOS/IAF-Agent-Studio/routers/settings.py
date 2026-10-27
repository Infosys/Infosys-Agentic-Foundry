"""
IAF Agent Studio — Settings API Router

Two tiers of configuration:

1. **User Settings** (per-user preferences)
   - Storage: enterprise_root/tenants/{tenant}/users/{user}/settings.json
   - Purely additive UI defaults on page load.
   - The per-message WebSocket payload remains authoritative during a session.

2. **Admin Config** (platform-wide infrastructure & safety knobs)
   - Storage: enterprise_root/tenants/{tenant}/config/admin_config.json
   - Phase 1: Read live values + save overrides to JSON. ✅
   - Phase 2: Hot-reload — POST also patches in-memory Python attrs. ✅
   - Phase 3: Auto-load admin_config.json on server startup. ✅
"""

import json
import logging
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlsplit, urlunsplit

from fastapi import APIRouter, Depends, HTTPException, Request

from auth.middleware import require_admin
from security.dependencies import bind_request_identity, require_scoped_identity
from shared.config import SERVER_DIR, DATA_ROOT, TENANT_ID, OBSERVERS_ENABLED
from shared.file_utils import atomic_write_json, atomic_write_yaml, locked_rmw_json, locked_rmw_yaml

logger = logging.getLogger(__name__)

router = APIRouter()


_DEFAULTS: dict = {
    "dark_mode": True,
    "human_approval": True,
    "light_mode": False,
    "knowledge_mode": "hybrid",
    "skill_mode": "auto",
    "show_conversations": True,
    "panel_files": True,
    "panel_reasoning": True,
    "progress_expanded": True,
    "preferred_agent_id": "enterprise_agent",
    "critique_mode": "off",
    "consistency_check": False,
    "plan_mode": False,
    "profile": "",
}

# Keys we accept — anything else is silently dropped on save
_ALLOWED_KEYS = set(_DEFAULTS.keys())


def _settings_path(tenant_id: str, user_id: str) -> Path:
    """Return the path to the user's settings JSON file."""
    root = Path(str(SERVER_DIR / DATA_ROOT)).resolve()
    return root / "tenants" / tenant_id / "users" / user_id / "settings.json"


def _read_settings(tenant_id: str, user_id: str) -> dict:
    """Read settings from disk, returning defaults if file is missing/corrupt."""
    p = _settings_path(tenant_id, user_id)
    if not p.exists():
        return dict(_DEFAULTS)
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        # Merge with defaults so new keys added in future are always present
        merged = dict(_DEFAULTS)
        merged.update({k: v for k, v in data.items() if k in _ALLOWED_KEYS or k == "updated_at"})
        return merged
    except Exception as exc:
        logger.warning("Corrupt settings.json for %s/%s: %s", tenant_id, user_id, exc)
        return dict(_DEFAULTS)


def _write_settings(tenant_id: str, user_id: str, settings: dict) -> None:
    """Persist settings dict to disk."""
    p = _settings_path(tenant_id, user_id)
    settings["updated_at"] = datetime.now(timezone.utc).isoformat()
    atomic_write_json(p, settings)


@router.get("/api/settings")
async def get_settings(
    request: Request,
    tenant_id: str = "company",
    user_id: str = "demo",
):
    """Return the full settings dict for this user (merged with defaults)."""
    # Bind to the caller: with auth on, the query-string user/tenant cannot select someone else's file.
    _principal, tenant_id, _agent, user_id = bind_request_identity(
        request, requested_tenant=tenant_id, requested_user=user_id)
    return _read_settings(tenant_id, user_id)


@router.post("/api/settings")
async def update_settings(
    request: Request,
    tenant_id: str = "company",
    user_id: str = "demo",
):
    """
    Partial-update user settings.

    Accepts a JSON body with any subset of allowed keys.
    Unknown keys are silently dropped. Existing keys not in the
    request body are preserved (merge, not replace).
    """
    _principal, tenant_id, _agent, user_id = bind_request_identity(
        request, requested_tenant=tenant_id, requested_user=user_id)
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON body")

    if not isinstance(body, dict):
        raise HTTPException(status_code=400, detail="Body must be a JSON object")

    # Read current, merge incoming (only allowed keys), write back
    current = _read_settings(tenant_id, user_id)
    changed = 0
    for key, value in body.items():
        if key in _ALLOWED_KEYS:
            current[key] = value
            changed += 1

    if changed > 0:
        _write_settings(tenant_id, user_id, current)

    return current


def _safe_read(fn: Callable, fallback: Any = "unavailable") -> Any:
    """Call a read function; return *fallback* if the module isn't loaded."""
    try:
        return fn()
    except Exception:
        return fallback


def _read_kernel_attr(attr: str) -> Any:
    from agent_os.kernel import SafeKernel
    return getattr(SafeKernel, attr)


def _read_agent_cls_attr(attr: str) -> Any:
    from iaf_agent_skills.agent import SkillAgent
    return getattr(SkillAgent, attr)


def _read_agent_behavior_attr(attr: str) -> Any:
    """Read an Agent Behavior class default, distinguishing *why* a read can fail.

    `SkillAgent` declares each of these as a class attribute (its normal,
    expected state) — a freshly constructed agent reads the same attribute in
    `__init__`, so this always reports the value new sessions will actually
    use. The two string fallbacks only appear if that invariant regresses —
    never the bare, ambiguous "unavailable" the class/instance mismatch used
    to produce for every read.
    """
    try:
        from iaf_agent_skills.agent import SkillAgent
    except Exception:
        return "could not be read — agent module unavailable"
    if not hasattr(SkillAgent, attr):
        return "not configured — no class default set"
    return getattr(SkillAgent, attr)


def _read_state_session_attr(attr: str) -> Any:
    from shared.state import session_state
    return getattr(session_state, attr)


def _read_approval_const(name: str) -> Any:
    import iaf_agent_skills.approval_store as _as
    return getattr(_as, name)


def _read_approval_sla() -> dict:
    from iaf_agent_skills.approval_store import DEFAULT_SLA
    return dict(DEFAULT_SLA)


# agent_id/tenant_id become a path component: reject traversal (`../`, absolute paths).
_SAFE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")


def _require_safe_id(value: str, label: str) -> str:
    """Reject anything that is not a single, traversal-free path component."""
    text = str(value or "")
    if text in ("", ".", "..") or not _SAFE_ID_RE.match(text) or text.startswith("."):
        raise HTTPException(status_code=400, detail=f"Invalid {label}")
    return text


def _require_safe_optional_id(value: str | None, label: str) -> None:
    """Validate an id only when the caller supplied one.

    `tenant_id` is now omitted by the UI so the server resolves it from the
    authenticated principal; an absent value is correct, an unsafe one is not.
    """
    if value is not None:
        _require_safe_id(value, label)


def _agent_config_path(agent_id: str = "enterprise_agent", tenant_id: str = "company") -> Path:
    """Return the path to an agent's config.yaml, confined to the tenant's agents dir."""
    agent_id = _require_safe_id(agent_id, "agent_id")
    tenant_id = _require_safe_id(tenant_id, "tenant_id")
    root = Path(DATA_ROOT)
    if not root.is_absolute():
        root = (SERVER_DIR / root).resolve()
    agents_dir = (root / "tenants" / tenant_id / "agents").resolve()
    resolved = (agents_dir / agent_id / "config.yaml").resolve()
    # Defence in depth: a symlinked agent directory must not point outside either.
    if agents_dir not in resolved.parents:
        raise HTTPException(status_code=400, detail="Invalid agent_id")
    return resolved


def _cached_agents_for(tenant_id: str, agent_id: str) -> list:
    """Live agent instances a per-agent config change must be pushed onto.

    Returns the empty list rather than raising when the state service has no
    cache for this pair — a save must still succeed on a server where nobody
    has opened the agent yet; those sessions read the persisted config.yaml.

    Deliberately does *not* swallow AttributeError: a missing
    ``iter_cached_agents`` is a programming error, and catching it here once
    silently reduced this whole function to a no-op in the default in-memory
    mode while every test kept passing against a monkeypatched stand-in.
    """
    from shared.state import state

    if not hasattr(state, "iter_cached_agents"):
        raise AttributeError(
            "state service %r has no iter_cached_agents; per-agent hot reload "
            "would silently do nothing" % type(state).__name__
        )
    try:
        return state.iter_cached_agents(tenant_id, agent_id)
    except AttributeError:
        raise
    except Exception as exc:  # pragma: no cover - defensive at the service boundary
        logger.warning("Hot-reload skipped for %s/%s: %s", tenant_id, agent_id, exc)
        return []


def _read_agent_context_key(
    key: str, default: str = "", *, tenant_id: str = "company", agent_id: str = "enterprise_agent"
) -> str:
    """Read a key from the agent config.yaml context section."""
    try:
        import yaml
        p = _agent_config_path(agent_id=agent_id, tenant_id=tenant_id)
        if not p.exists():
            return default
        cfg = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
        return cfg.get("context", {}).get(key, default)
    except Exception as exc:
        logger.warning("Failed to read agent config context.%s: %s", key, exc)
        return default


def _write_agent_context_key(
    key: str, value: str, *, tenant_id: str = "company", agent_id: str = "enterprise_agent"
) -> None:
    """Write a key to the agent config.yaml context section and hot-reload the live agent."""
    try:
        import yaml
        p = _agent_config_path(agent_id=agent_id, tenant_id=tenant_id)
        if not p.exists():
            logger.warning("Agent config.yaml not found at %s", p)
            return

        from shared.file_utils import atomic_write_yaml
        from iaf_agent_skills.file_lock import portable_lock
        with portable_lock(p):
            cfg = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
            cfg.setdefault("context", {})[key] = value
            atomic_write_yaml(p, cfg)
        logger.info("Agent config.yaml updated: context.%s = %r", key, value)

        # Patch every cached agent for this tenant/agent: templates are keyed by user and role.
        for agent in _cached_agents_for(tenant_id, agent_id):
            if key == "context_loading_mode":
                agent.context_loading_mode = value
            elif key == "context_file_path":
                agent._context_file_path = value
        logger.info("Hot-reload: agent.%s = %r", key, value)

    except Exception as exc:
        logger.warning("Failed to write agent config context.%s: %s", key, exc)
        raise


def _read_agent_profile_default(
    default: str = "standard", *, tenant_id: str = "company", agent_id: str = "enterprise_agent"
) -> str:
    """Read the agent's default harness profile from config.yaml (top-level default_profile)."""
    try:
        import yaml
        p = _agent_config_path(agent_id=agent_id, tenant_id=tenant_id)
        if not p.exists():
            return default
        cfg = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
        return str(cfg.get("default_profile", default))
    except Exception:
        return default


def _write_agent_profile_default(
    value: str, *, tenant_id: str = "company", agent_id: str = "enterprise_agent"
) -> None:
    """Write config.yaml default_profile and hot-reload the live agent (no restart)."""
    try:
        import yaml
        from shared.file_utils import atomic_write_yaml
        from iaf_agent_skills.file_lock import portable_lock
        p = _agent_config_path(agent_id=agent_id, tenant_id=tenant_id)
        if not p.exists():
            logger.warning("Agent config.yaml not found at %s", p)
            return
        with portable_lock(p):
            cfg = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
            cfg["default_profile"] = str(value)
            atomic_write_yaml(p, cfg)
        for agent in _cached_agents_for(tenant_id, agent_id):
            if isinstance(getattr(agent, "config", None), dict):
                agent.config["default_profile"] = str(value)
        logger.info("Hot-reload: agent default_profile = %r", value)
    except Exception as exc:
        logger.warning("Failed to write default_profile: %s", exc)
        raise


_FILE_MODE_NEEDS_PATH = (
    "Context loading mode 'file' requires a CONTEXT_FILE_PATH pointing at an "
    "existing '/shared/*.md' file."
)


def _context_pair_is_usable(mode: Any, path: Any, *, tenant_id: str, agent_id: str) -> tuple[bool, str]:
    """The mode/path cross-field rule, in one place.

    `file` mode is only coherent with a path that exists; `table` mode has no
    path to check. Extracted because three separate paths must enforce it —
    the save route, the reset route, and the startup re-apply — and it was
    previously implemented inline in the save route only, so reset and startup
    could each recreate the exact broken state the save route rejects.
    """
    if str(mode) != "file":
        return True, ""
    if not path:
        return False, _FILE_MODE_NEEDS_PATH
    return _validate_context_file_path(path, tenant_id=tenant_id, agent_id=agent_id)


# Per-agent keys live in config.yaml; every other registry entry patches a process-global attribute.
_PER_AGENT_KEYS = {"CONTEXT_LOADING_MODE", "CONTEXT_FILE_PATH", "DEFAULT_PROFILE"}


def _read_per_agent_param(key: str, *, tenant_id: str, agent_id: str) -> Any:
    """Read one of the three per-agent params, resolved to the given agent/tenant."""
    if key == "CONTEXT_LOADING_MODE":
        return _read_agent_context_key("context_loading_mode", "table", tenant_id=tenant_id, agent_id=agent_id)
    if key == "CONTEXT_FILE_PATH":
        return _read_agent_context_key("context_file_path", "", tenant_id=tenant_id, agent_id=agent_id)
    if key == "DEFAULT_PROFILE":
        return _read_agent_profile_default(tenant_id=tenant_id, agent_id=agent_id)
    raise KeyError(key)


def _apply_per_agent_param(key: str, value: Any, *, tenant_id: str, agent_id: str) -> None:
    """Write one of the three per-agent params, resolved to the given agent/tenant."""
    if key == "CONTEXT_LOADING_MODE":
        _write_agent_context_key("context_loading_mode", str(value), tenant_id=tenant_id, agent_id=agent_id)
    elif key == "CONTEXT_FILE_PATH":
        _write_agent_context_key("context_file_path", str(value), tenant_id=tenant_id, agent_id=agent_id)
    elif key == "DEFAULT_PROFILE":
        _write_agent_profile_default(str(value), tenant_id=tenant_id, agent_id=agent_id)
    else:
        raise KeyError(key)


_BUILTIN_PROFILE_DESCRIPTIONS = {
    "standard": "Default behavior — matches today's harness exactly, no overrides.",
    "fast-lookup": "Lightweight ReAct engine, verification off, cheap model — quick lookups.",
    "high-assurance": "High verification threshold, primary model, autonomy locked off — high-stakes tasks.",
    "autonomous": "Orchestrator engine, auto-run enabled, bounded budget — unattended runs.",
    "deep-research": "Orchestrator engine, verification on, hybrid retrieval, long-running budget.",
}


def resolve_profile_options(*, tenant_id: str, agent_id: str) -> list[dict[str, str]]:
    """Registered profiles (built-ins overlaid with the tenant's harness_profiles.yaml)."""
    from agentos_contracts.profile import available_profiles
    from iaf_agent_skills.harness_profiles import load_profile_registry

    agent_root = _agent_config_path(agent_id=agent_id, tenant_id=tenant_id).parent
    registry = load_profile_registry(agent_root)
    profiles = available_profiles(registry)
    return [
        {"name": name, "description": vec.get("description") or _BUILTIN_PROFILE_DESCRIPTIONS.get(name, "")}
        for name, vec in sorted(profiles.items())
    ]


def _validate_default_profile(value: Any, *, tenant_id: str, agent_id: str) -> tuple[bool, str]:
    name = str(value)
    allowed = [opt["name"] for opt in resolve_profile_options(tenant_id=tenant_id, agent_id=agent_id)]
    if name not in allowed:
        return False, "Unknown harness profile '%s'. Use one of: %s." % (name, ", ".join(allowed))
    return True, ""


_CONTEXT_LOADING_MODES = ("file", "table")


def _validate_context_loading_mode(value: Any, *, tenant_id: str, agent_id: str) -> tuple[bool, str]:
    name = str(value)
    if name not in _CONTEXT_LOADING_MODES:
        return False, "Invalid context loading mode '%s'. Use one of: %s." % (
            name, ", ".join(_CONTEXT_LOADING_MODES),
        )
    return True, ""


_CONTEXT_FILE_PATH_REASON = "Invalid context file path. Use a valid '/shared/*.md' path."


def _tenant_root_for_agent(*, tenant_id: str, agent_id: str) -> Path:
    """.../tenants/<t>/agents/<a>/config.yaml -> .../tenants/<t> — mirrors the
    resolution SkillAgent itself uses for `_context_file_path` at runtime."""
    return _agent_config_path(agent_id=agent_id, tenant_id=tenant_id).parent.parent.parent


def _validate_context_file_path(value: Any, *, tenant_id: str, agent_id: str) -> tuple[bool, str]:
    path = str(value or "")
    if not path:
        # An empty path is fine on its own; the file-mode cross-field check is
        # what catches "file mode with no usable path".
        return True, ""
    if "\x00" in path or not path.startswith("/shared/") or not path.endswith(".md"):
        return False, _CONTEXT_FILE_PATH_REASON
    if any(segment in ("..", ".") for segment in path.split("/")):
        return False, _CONTEXT_FILE_PATH_REASON

    tenant_root = _tenant_root_for_agent(tenant_id=tenant_id, agent_id=agent_id).resolve()
    target = (tenant_root / path.lstrip("/")).resolve()
    try:
        target.relative_to(tenant_root)
    except ValueError:
        return False, _CONTEXT_FILE_PATH_REASON
    if not target.is_file():
        return False, "Context file '%s' does not exist." % path
    return True, ""


# key -> validator(value, *, tenant_id, agent_id) -> (ok, rejection_message)
_ADMIN_VALIDATORS: dict[str, Callable[..., tuple[bool, str]]] = {
    "DEFAULT_PROFILE": _validate_default_profile,
    "CONTEXT_LOADING_MODE": _validate_context_loading_mode,
    "CONTEXT_FILE_PATH": _validate_context_file_path,
}


def _apply_kernel_attr(attr: str, value: Any) -> None:
    """Patch a SafeKernel class attribute. Takes effect instantly for all instances."""
    from agent_os.kernel import SafeKernel
    setattr(SafeKernel, attr, value)
    logger.info("Hot-reload: SafeKernel.%s = %r", attr, value)


def _apply_agent_cls_attr(attr: str, value: Any) -> None:
    """Patch a SkillAgent class attribute. New sessions pick up the change."""
    from iaf_agent_skills.agent import SkillAgent
    setattr(SkillAgent, attr, value)
    logger.info("Hot-reload: SkillAgent.%s = %r", attr, value)


def _apply_state_session_attr(attr: str, value: Any) -> None:
    """Patch the live session_state singleton."""
    from shared.state import session_state
    setattr(session_state, attr, value)
    logger.info("Hot-reload: session_state.%s = %r", attr, value)


def _apply_approval_const(name: str, value: Any) -> None:
    """Patch a module-level constant in approval_store."""
    import iaf_agent_skills.approval_store as _as
    setattr(_as, name, value)
    logger.info("Hot-reload: approval_store.%s = %r", name, value)


def _apply_approval_sla(value: dict) -> None:
    """Patch the DEFAULT_SLA dict in approval_store."""
    import iaf_agent_skills.approval_store as _as
    if isinstance(value, dict):
        _as.DEFAULT_SLA.update(value)
        logger.info("Hot-reload: approval_store.DEFAULT_SLA updated: %r", value)


_AdminEntry = tuple

_ADMIN_REGISTRY: dict[str, _AdminEntry] = {
    "MAX_READ_BYTES":           (lambda: _safe_read(lambda: _read_kernel_attr("MAX_READ_BYTES")),           51200,  "kernel.py",  "safety",  True,  "Max bytes per file read operation",              lambda v: _apply_kernel_attr("MAX_READ_BYTES", int(v))),
    "MAX_READ_LINES":           (lambda: _safe_read(lambda: _read_kernel_attr("MAX_READ_LINES")),           100,    "kernel.py",  "safety",  True,  "Max lines per file read operation",              lambda v: _apply_kernel_attr("MAX_READ_LINES", int(v))),
    "MAX_LIST_ITEMS":           (lambda: _safe_read(lambda: _read_kernel_attr("MAX_LIST_ITEMS")),           100,    "kernel.py",  "safety",  True,  "Max items returned by list_directory",           lambda v: _apply_kernel_attr("MAX_LIST_ITEMS", int(v))),
    "MAX_GREP_RESULTS":         (lambda: _safe_read(lambda: _read_kernel_attr("MAX_GREP_RESULTS")),         50,     "kernel.py",  "safety",  True,  "Max results from grep operations",              lambda v: _apply_kernel_attr("MAX_GREP_RESULTS", int(v))),
    "MAX_FIND_RESULTS":         (lambda: _safe_read(lambda: _read_kernel_attr("MAX_FIND_RESULTS")),         100,    "kernel.py",  "safety",  True,  "Max results from find operations",              lambda v: _apply_kernel_attr("MAX_FIND_RESULTS", int(v))),
    "MAX_RECURSIVE_DEPTH":      (lambda: _safe_read(lambda: _read_kernel_attr("MAX_RECURSIVE_DEPTH")),      5,      "kernel.py",  "safety",  True,  "Max recursion depth for file operations",       lambda v: _apply_kernel_attr("MAX_RECURSIVE_DEPTH", int(v))),
    "COMMAND_TIMEOUT":          (lambda: _safe_read(lambda: _read_kernel_attr("COMMAND_TIMEOUT")),          30,     "kernel.py",  "safety",  True,  "Timeout in seconds for shell commands",         lambda v: _apply_kernel_attr("COMMAND_TIMEOUT", int(v))),
    "BLOCKED_COMMANDS":         (lambda: _safe_read(lambda: _read_kernel_attr("BLOCKED_COMMANDS")),         [],     "kernel.py",  "safety",  True,  "List of blocked shell commands",                lambda v: _apply_kernel_attr("BLOCKED_COMMANDS", list(v))),
    "DANGEROUS_OPERATORS":      (lambda: _safe_read(lambda: _read_kernel_attr("DANGEROUS_OPERATORS")),      [],     "kernel.py",  "safety",  False, "Shell operators considered dangerous",          None),
    "AUDIT_LOG_MAX_DAYS":       (lambda: _safe_read(lambda: _read_kernel_attr("AUDIT_LOG_MAX_DAYS")),       30,     "kernel.py",  "safety",  True,  "Days to retain audit logs",                     lambda v: _apply_kernel_attr("AUDIT_LOG_MAX_DAYS", int(v))),
    "AUDIT_LOG_COMPRESS_AFTER": (lambda: _safe_read(lambda: _read_kernel_attr("AUDIT_LOG_COMPRESS_AFTER_DAYS")), 1, "kernel.py",  "safety",  True,  "Days before compressing audit logs",            lambda v: _apply_kernel_attr("AUDIT_LOG_COMPRESS_AFTER_DAYS", int(v))),

    "DEFAULT_RATE_LIMIT":       (lambda: _safe_read(lambda: _read_kernel_attr("DEFAULT_RATE_LIMIT")),       60,     "kernel.py",  "rate_limits", True,  "Max commands per rate window",                lambda v: _apply_kernel_attr("DEFAULT_RATE_LIMIT", int(v))),
    "DEFAULT_RATE_WINDOW":      (lambda: _safe_read(lambda: _read_kernel_attr("DEFAULT_RATE_WINDOW")),      60,     "kernel.py",  "rate_limits", True,  "Rate window duration in seconds",             lambda v: _apply_kernel_attr("DEFAULT_RATE_WINDOW", int(v))),

    "RECURSION_LIMIT":          (lambda: _read_agent_behavior_attr("RECURSION_LIMIT"), 200, "agent.py",  "agent",  True,  "LangGraph recursion limit per invocation",     lambda v: _apply_agent_cls_attr("RECURSION_LIMIT", int(v))),  # Set at SkillAgent.__init__, affects new sessions only
    "SESSION_COMPACT_THRESHOLD":(lambda: _read_agent_behavior_attr("SESSION_COMPACT_THRESHOLD"), 30, "agent.py",   "agent",   True,  "Message count that triggers session compaction", lambda v: _apply_agent_cls_attr("SESSION_COMPACT_THRESHOLD", int(v))),
    "SESSION_KEEP_RECENT":      (lambda: _read_agent_behavior_attr("SESSION_KEEP_RECENT"),   8,      "agent.py",   "agent",   True,  "Number of recent messages kept after compaction", lambda v: _apply_agent_cls_attr("SESSION_KEEP_RECENT", int(v))),
    "PENDING_ACTION_TIMEOUT":   (lambda: _read_agent_behavior_attr("PENDING_ACTION_TIMEOUT_MINUTES"), 10, "agent.py",  "agent", True, "Minutes before a pending HITL action times out", lambda v: _apply_agent_cls_attr("PENDING_ACTION_TIMEOUT_MINUTES", int(v))),
    "MAX_HISTORY":              (lambda: _safe_read(lambda: 10),                                            10,     "agent.py",   "agent",   True,  "Default max conversation history depth",       None),  # Function param default, not patchable

    "MAX_SESSIONS_PER_USER":    (lambda: _safe_read(lambda: _read_state_session_attr("MAX_SESSIONS_PER_USER")), 5,  "state.py",   "session", True,  "Max concurrent sessions per user",             lambda v: _apply_state_session_attr("MAX_SESSIONS_PER_USER", int(v))),
    "CACHE_TTL":                (lambda: _safe_read(lambda: 300),                                           300,    "state.py",   "session", True,  "Redis session cache TTL in seconds",           None),  # Set at construction, needs restart
    "SCHEDULER_CHECK_INTERVAL": (lambda: _safe_read(lambda: 60),                                            60,     "state.py",   "session", True,  "Cron scheduler check interval in seconds",     None),  # Set at construction, needs restart
    "MAX_CONCURRENT_JOBS":      (lambda: _safe_read(lambda: 5),                                             5,      "state.py",   "session", True,  "Maximum concurrent cron job executions",       None),  # Set at construction, needs restart

    "APPROVAL_TTL_SECONDS":     (lambda: _safe_read(lambda: _read_approval_const("APPROVAL_TTL_SECONDS")),  604800, "approval_store.py", "hitl", True, "Approval record TTL (seconds, default 7 days)", lambda v: _apply_approval_const("APPROVAL_TTL_SECONDS", int(v))),
    "HISTORY_MAX_LENGTH":       (lambda: _safe_read(lambda: _read_approval_const("HISTORY_MAX_LENGTH")),    500,    "approval_store.py", "hitl", True, "Max approval history entries",                  lambda v: _apply_approval_const("HISTORY_MAX_LENGTH", int(v))),
    "SLA_DEFAULTS":             (lambda: _safe_read(_read_approval_sla, {}),                                {"low":480,"medium":120,"high":30,"critical":10}, "approval_store.py", "hitl", True, "SLA targets by priority (minutes)", _apply_approval_sla),

    "CONTEXT_LOADING_MODE":     (lambda: _read_agent_context_key("context_loading_mode", "table"),  "table",  "config.yaml", "context", True,  "Context loading mode: 'file' (Enterprise Context .md), 'table' (SQLite entity registry), or 'rlm' (offload context to a queryable handle via the context_query tool; requires context_file_path)", lambda v: _write_agent_context_key("context_loading_mode", str(v))),
    "CONTEXT_FILE_PATH":        (lambda: _read_agent_context_key("context_file_path", ""),          "",       "config.yaml", "context", True,  "Virtual path to the Enterprise Context .md file (used when mode = file), e.g. /shared/Enterprise_Context.md", lambda v: _write_agent_context_key("context_file_path", str(v))),

    "MAX_SHORT_TERM":           (lambda: _safe_read(lambda: 20),                                            20,     "memory.py",  "agent",   True,  "Max short-term memory entries per session",    None),  # Instance attr, new sessions only
    "EMBEDDING_CACHE_MAX_SIZE": (lambda: int(os.getenv("EMBEDDING_CACHE_MAX_SIZE", "4096")),                4096,   "memory.py",  "agent",   True,  "LRU embedding cache max entries",              None),  # Constructed once at import

    "HOST":                     (lambda: os.getenv("HOST", "127.0.0.1"),                                    "127.0.0.1",    "env",     "infra", False, "Server bind host",                            None),
    "PORT":                     (lambda: int(os.getenv("PORT", "8080")),                                    8080,           "env",     "infra", False, "Server bind port",                            None),
    "REDIS_URL":                (lambda: os.getenv("REDIS_URL", "redis://localhost:6379"),                   "redis://localhost:6379", "env", "infra", False, "Redis connection URL",                  None),
    "DATA_ROOT":                (lambda: os.getenv("DATA_ROOT", "../enterprise_root"),                      "../enterprise_root",     "env", "infra", False, "Enterprise data root path",             None),
    "SKILLS_PATH":              (lambda: os.getenv("SKILLS_PATH", "../enterprise_root/tenants/company/skills"), "../enterprise_root/tenants/company/skills", "env", "infra", False, "Skills directory path", None),
    "LOG_LEVEL":                (lambda: os.getenv("LOG_LEVEL", "INFO"),                                    "INFO",         "env",     "infra", False, "Server log level",                            None),
    "QUEUE_BACKEND":             (lambda: _safe_read(lambda: __import__('shared.config', fromlist=['QUEUE_BACKEND']).QUEUE_BACKEND), "memory", "config.py", "infra", True, "Queue backend: 'memory' (single server) or 'redis' (enterprise)", None),  # Restart required — constructed at boot
    "USE_REDIS_SESSIONS":       (lambda: _safe_read(lambda: __import__('shared.config', fromlist=['USE_REDIS_SESSIONS']).USE_REDIS_SESSIONS), False, "config.py", "infra", True, "Use Redis for session storage (requires restart)", None),  # Restart required — constructed at boot

    "AZURE_OPENAI_ENDPOINT":    (lambda: _mask_secret(os.getenv("AZURE_OPENAI_ENDPOINT", "")),              "",     "env",     "llm",   False, "Azure OpenAI endpoint URL",                    None),
    "AZURE_OPENAI_API_VERSION": (lambda: os.getenv("AZURE_OPENAI_API_VERSION", "2024-12-01-preview"),      "2024-12-01-preview", "env", "llm", False, "Azure OpenAI API version",                    None),
    "AZURE_OPENAI_DEPLOYMENT":  (lambda: os.getenv("AZURE_OPENAI_DEPLOYMENT", "gpt-4o"),                   "gpt-4o",  "env",     "llm",   False, "Primary LLM deployment name",                 None),
    "AZURE_OPENAI_DEPLOYMENT_LIGHT": (lambda: os.getenv("AZURE_OPENAI_DEPLOYMENT_LIGHT", os.getenv("AZURE_OPENAI_DEPLOYMENT", "gpt-4o")), "gpt-4o", "env", "llm", False, "Light/cheap LLM deployment name",  None),
    "AZURE_OPENAI_EMBEDDING_MODEL": (lambda: os.getenv("AZURE_OPENAI_EMBEDDING_MODEL", "text-embedding-ada-002"), "text-embedding-ada-002", "env", "llm", False, "Embedding model for knowledge search", None),

    "DEFAULT_PROFILE":          (lambda: _read_agent_profile_default(), "standard", "config.yaml", "profiles", True, "Default harness execution profile (standard | fast-lookup | high-assurance | autonomous | deep-research). Per-skill 'profile:' and per-request override this.", lambda v: _write_agent_profile_default(str(v))),

    "TWIN_TELEMETRY":           (lambda: os.getenv("TWIN_TELEMETRY", "true").lower() == "true",            True,   "env",     "telemetry", False, "Enable twin telemetry emission",              None),
    "TRACE_TELEMETRY":          (lambda: os.getenv("TRACE_TELEMETRY", "true").lower() == "true",           True,   "env",     "telemetry", False, "Enable trace telemetry emission",             None),
    "TWIN_QUEUE_MAXSIZE":       (lambda: _safe_read(lambda: 10_000),                                       10000,  "twin_emitter.py", "telemetry", False, "Twin emitter async queue capacity",   None),
    "TRACE_QUEUE_MAXSIZE":      (lambda: _safe_read(lambda: 100_000),                                      100000, "trace_emitter.py","telemetry", False, "Trace emitter async queue capacity",  None),
}

_ADMIN_CATEGORIES = {
    "profiles":    {"label": "Harness Profiles",     "icon": "🎛️", "order": 0, "editable": True},
    "context":     {"label": "Context Loading",      "icon": "📂", "order": 1, "editable": True},
    "agent":       {"label": "Agent Behavior",       "icon": "🤖", "order": 2, "editable": True},
    "safety":      {"label": "Safety & Sandbox",     "icon": "🛡️", "order": 3, "editable": True},
    "rate_limits": {"label": "Rate Limits",          "icon": "⚡", "order": 4, "editable": True},
    "session":     {"label": "Session & Scheduling", "icon": "📋", "order": 5, "editable": True},
    "hitl":        {"label": "HITL / Approvals",     "icon": "✅", "order": 6, "editable": True},
    "infra":       {"label": "Infrastructure",       "icon": "🏗️", "order": 7, "editable": True},
    "llm":         {"label": "LLM / Model",          "icon": "🧠", "order": 8, "editable": False},
    "telemetry":   {"label": "Telemetry",            "icon": "📡", "order": 9, "editable": False},
}


def _mask_secret(value: str) -> str:
    """Mask sensitive values — show first 8 chars + '***' for long strings."""
    if not value or len(value) < 12:
        return "***" if value else ""
    return value[:8] + "***"


def _mask_url_credentials(value: str) -> str:
    """Strip userinfo from a connection URL, leaving it diagnosable.

    `REDIS_URL` and friends are normally `scheme://<userinfo>@host:port` in
    production. An operator debugging a connection needs the scheme, host, port
    and path; only the credential is sensitive — so collapsing the whole value to
    "***" would hide the credential and the useful half along with it.

    Values that are not URL-shaped, or that carry no userinfo, are returned
    untouched: this runs over every string in the config payload, so it must be
    a no-op for the ~35 entries that are paths, hostnames and log levels.
    """
    text = str(value or "")
    if "://" not in text:
        return text
    try:
        parts = urlsplit(text)
    except ValueError:
        # URL-shaped but unparseable — fail closed rather than echo it.
        return "***"
    if not parts.netloc or "@" not in parts.netloc:
        return text
    # rpartition, not partition: a password may itself contain '@'.
    host = parts.netloc.rpartition("@")[2]
    return urlunsplit((parts.scheme, f"***@{host}", parts.path, parts.query, parts.fragment))


def _admin_config_path(tenant_id: str) -> Path:
    """Return path to the tenant's admin config override file."""
    root = Path(str(SERVER_DIR / DATA_ROOT)).resolve()
    return root / "tenants" / tenant_id / "config" / "admin_config.json"


def _read_admin_overrides(tenant_id: str) -> dict:
    """Read saved admin overrides from disk (empty dict if none exist)."""
    p = _admin_config_path(tenant_id)
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception as exc:
        logger.warning("Corrupt admin_config.json for tenant %s: %s", tenant_id, exc)
        return {}


@router.get("/api/admin/config")
async def get_admin_config(
    request: Request,
    tenant_id: str | None = None,
    agent_id: str = "enterprise_agent",
    admin: dict = Depends(require_admin),
):
    """
    Return the full admin config with live values, defaults, and saved overrides.

    Response shape:
    {
      "categories": { "safety": { "label": ..., "icon": ..., "order": ..., "editable": bool }, ... },
      "params": {
        "MAX_READ_BYTES": {
          "value": 51200,         # live value from Python module
          "default": 51200,       # hardcoded default
          "override": null,       # saved override (if user changed it)
          "source": "kernel.py",  # where it lives
          "category": "safety",
          "editable": true,
          "description": "...",
          "scope": "server",      # "agent" (this agent's config.yaml) or "server" (process-global)
        },
        ...
      }
    }
    """
    _require_safe_optional_id(tenant_id, "tenant_id")
    _require_safe_id(agent_id, "agent_id")
    _principal, tenant_id, agent_id, _user_id = require_scoped_identity(
        request,
        requested_tenant=tenant_id,
        requested_agent=agent_id,
        action="read",
        resource_type="agent",
        resource_id=agent_id,
    )

    overrides = _read_admin_overrides(tenant_id)
    params = {}

    for key, entry in _ADMIN_REGISTRY.items():
        read_fn, default, source, category, editable, description, apply_fn = entry
        is_per_agent = key in _PER_AGENT_KEYS
        live_value = (
            _read_per_agent_param(key, tenant_id=tenant_id, agent_id=agent_id) if is_per_agent else read_fn()
        )
        saved_override = overrides.get(key)
        if is_per_agent:
            # Per-agent keys live in the agent's config.yaml, so do not report a tenant-wide entry as an override.
            saved_override = None

        params[key] = {
            # Mask credentials at the response boundary so a new URL parameter cannot ship unmasked.
            "value": _mask_url_credentials(live_value) if isinstance(live_value, str) else live_value,
            "default": _mask_url_credentials(default) if isinstance(default, str) else default,
            "override": _mask_url_credentials(saved_override) if isinstance(saved_override, str) else saved_override,
            "source": source,
            "category": category,
            "editable": editable,
            "description": description,
            "hot_reload": apply_fn is not None or is_per_agent,  # tells UI whether change is instant
            "scope": "agent" if is_per_agent else "server",
            "agent_id": agent_id if is_per_agent else None,
        }

    return {
        "categories": _ADMIN_CATEGORIES,
        "params": params,
        "tenant_id": tenant_id,
        "agent_id": agent_id,
        "profile_options": resolve_profile_options(tenant_id=tenant_id, agent_id=agent_id),
        "context_loading_modes": list(_CONTEXT_LOADING_MODES),
    }


@router.post("/api/admin/config")
async def update_admin_config(
    request: Request,
    tenant_id: str | None = None,
    agent_id: str = "enterprise_agent",
    admin: dict = Depends(require_admin),
):
    """
    Save admin config overrides and hot-reload where possible.

    Accepts a JSON body like:
      { "MAX_READ_BYTES": 102400, "COMMAND_TIMEOUT": 60, ... }

    Only editable params are accepted. Unknown or read-only keys are rejected.

    Phase 2: Saves to admin_config.json AND applies to live Python objects
    for params that support hot-reload. Params without apply_fn are saved
    but require a server restart to take effect.
    """
    _require_safe_optional_id(tenant_id, "tenant_id")
    _require_safe_id(agent_id, "agent_id")
    _principal, tenant_id, agent_id, _user_id = require_scoped_identity(
        request,
        requested_tenant=tenant_id,
        requested_agent=agent_id,
        action="write",
        resource_type="agent",
        resource_id=agent_id,
    )
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON body")

    if not isinstance(body, dict):
        raise HTTPException(status_code=400, detail="Body must be a JSON object")

    # Validate — only editable keys allowed, and only values their validator accepts
    rejected = []
    accepted = {}
    for key, value in body.items():
        if key.startswith("_"):
            continue  # skip metadata keys
        if key not in _ADMIN_REGISTRY:
            rejected.append({"key": key, "reason": "unknown parameter"})
            continue
        entry = _ADMIN_REGISTRY[key]
        if not entry[4]:  # editable flag
            rejected.append({"key": key, "reason": "read-only parameter"})
            continue
        validator = _ADMIN_VALIDATORS.get(key)
        if validator is not None:
            ok, message = validator(value, tenant_id=tenant_id, agent_id=agent_id)
            if not ok:
                rejected.append({"key": key, "reason": message})
                continue
        accepted[key] = value

    # Cross-field rule: 'file' mode needs a usable CONTEXT_FILE_PATH; check effective values whenever either key changes.
    if "CONTEXT_LOADING_MODE" in body or "CONTEXT_FILE_PATH" in body:
        def _effective(key: str) -> Any:
            if key in accepted:
                return accepted[key]
            return _read_per_agent_param(key, tenant_id=tenant_id, agent_id=agent_id)

        ok, reason = _context_pair_is_usable(
            _effective("CONTEXT_LOADING_MODE"),
            _effective("CONTEXT_FILE_PATH"),
            tenant_id=tenant_id,
            agent_id=agent_id,
        )
        if not ok:
            offending_key = "CONTEXT_LOADING_MODE" if "CONTEXT_LOADING_MODE" in accepted else "CONTEXT_FILE_PATH"
            accepted.pop(offending_key, None)
            rejected.append({"key": offending_key, "reason": "Cannot use file mode: %s" % reason})

    # Per-agent keys are not stored in the tenant-wide admin_config.json (they would overwrite each other); they live in config.yaml.
    _accepted = {k: v for k, v in accepted.items() if k not in _PER_AGENT_KEYS}

    # Capture the merged result for the response builder.
    _merged: dict = {}

    def _merge(overrides: dict) -> dict:
        overrides.update(_accepted)
        for stale in _PER_AGENT_KEYS:
            overrides.pop(stale, None)
        overrides["_updated_at"] = datetime.now(timezone.utc).isoformat()
        _merged.clear()
        _merged.update(overrides)
        return overrides
    overrides = await locked_rmw_json(_admin_config_path(tenant_id), _merge)

    applied = []
    needs_restart = []
    apply_errors = []
    for key, value in accepted.items():
        try:
            if key in _PER_AGENT_KEYS:
                _apply_per_agent_param(key, value, tenant_id=tenant_id, agent_id=agent_id)
                applied.append(key)
                continue
            apply_fn = _ADMIN_REGISTRY[key][6]  # 7th element = apply_fn
            if apply_fn is not None:
                apply_fn(value)
                applied.append(key)
            else:
                needs_restart.append(key)
        except Exception as exc:
            apply_errors.append({"key": key, "error": "An internal error occurred"})
            logger.error("Hot-reload failed for %s: %s", key, exc)

    return {
        "saved": len(accepted),
        "applied": applied,           # hot-reloaded instantly
        "needs_restart": needs_restart, # saved but requires restart
        "apply_errors": apply_errors,  # hot-reload attempted but failed
        "rejected": rejected,
        "overrides": {k: v for k, v in overrides.items() if not k.startswith("_")},
        "tenant_id": tenant_id,
        "agent_id": agent_id,
    }


@router.post("/api/admin/config/reset")
async def reset_admin_config(
    request: Request,
    tenant_id: str | None = None,
    agent_id: str = "enterprise_agent",
    admin: dict = Depends(require_admin),
):
    """
    Reset specific admin config overrides back to defaults.

    Accepts: { "keys": ["MAX_READ_BYTES", "COMMAND_TIMEOUT"] }
    Or: { "keys": "__all__" } to reset everything.
    """
    _require_safe_optional_id(tenant_id, "tenant_id")
    _require_safe_id(agent_id, "agent_id")
    _principal, tenant_id, agent_id, _user_id = require_scoped_identity(
        request,
        requested_tenant=tenant_id,
        requested_agent=agent_id,
        action="write",
        resource_type="agent",
        resource_id=agent_id,
    )
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON body")

    keys = body.get("keys", [])

    _keys = keys
    def _reset(overrides: dict) -> dict:
        if _keys == "__all__":
            return {"_updated_at": datetime.now(timezone.utc).isoformat()}
        if isinstance(_keys, list):
            for k in _keys:
                overrides.pop(k, None)
        overrides["_updated_at"] = datetime.now(timezone.utc).isoformat()
        return overrides
    overrides = await locked_rmw_json(_admin_config_path(tenant_id), _reset)

    # Hot-reload defaults for reset params
    reset_keys = list(keys) if isinstance(keys, list) else list(_ADMIN_REGISTRY.keys())

    # Cross-field rule: resetting CONTEXT_FILE_PATH must also reset the mode if it was 'file'.
    if "CONTEXT_FILE_PATH" in reset_keys and "CONTEXT_LOADING_MODE" not in reset_keys:
        try:
            eff_mode = _read_per_agent_param("CONTEXT_LOADING_MODE", tenant_id=tenant_id, agent_id=agent_id)
            ok, _reason = _context_pair_is_usable(
                eff_mode, _ADMIN_REGISTRY["CONTEXT_FILE_PATH"][1],
                tenant_id=tenant_id, agent_id=agent_id,
            )
            if not ok:
                reset_keys.append("CONTEXT_LOADING_MODE")
                logger.info(
                    "Reset: also restoring CONTEXT_LOADING_MODE — clearing the path "
                    "would otherwise leave '%s' in file mode with nothing to load", agent_id,
                )
        except Exception as exc:
            logger.warning("Reset cross-field check skipped: %s", exc)

    restored = []
    for k in reset_keys:
        entry = _ADMIN_REGISTRY.get(k)
        if not entry:
            continue
        try:
            if k in _PER_AGENT_KEYS:
                _apply_per_agent_param(k, entry[1], tenant_id=tenant_id, agent_id=agent_id)
                restored.append(k)
            elif entry[6] is not None:  # has apply_fn
                entry[6](entry[1])  # apply default value
                restored.append(k)
        except Exception as exc:
            logger.error("Hot-reload reset failed for %s: %s", k, exc)

    return {
        "status": "ok",
        "remaining_overrides": len([k for k in overrides if not k.startswith("_")]),
        "restored": restored,  # params hot-reloaded back to defaults
    }


def apply_saved_overrides_on_startup(tenant_id: str = "company") -> dict:
    """
    Read admin_config.json and apply all saved overrides to live Python objects.

    Called once during server startup (in server.py lifespan).
    Returns a summary of what was applied.
    """
    overrides = _read_admin_overrides(tenant_id)
    if not overrides:
        logger.info("Admin config: no saved overrides for tenant '%s'", tenant_id)
        return {"applied": 0, "skipped": 0, "errors": 0}

    applied = 0
    skipped = 0
    errors = 0

    # Startup has no per-request agent: apply to the default agent.
    startup_agent = "enterprise_agent"

    # Cross-field rule as in save/reset: skip both keys unless 'file' mode has a usable path.
    context_pair_ok = True
    if "CONTEXT_LOADING_MODE" in overrides or "CONTEXT_FILE_PATH" in overrides:
        def _startup_effective(key: str) -> Any:
            if key in overrides:
                return overrides[key]
            try:
                return _read_per_agent_param(key, tenant_id=tenant_id, agent_id=startup_agent)
            except Exception:
                return None

        context_pair_ok, pair_reason = _context_pair_is_usable(
            _startup_effective("CONTEXT_LOADING_MODE"),
            _startup_effective("CONTEXT_FILE_PATH"),
            tenant_id=tenant_id,
            agent_id=startup_agent,
        )
        if not context_pair_ok:
            logger.error(
                "Startup apply skipped for CONTEXT_LOADING_MODE/CONTEXT_FILE_PATH: "
                "the saved pair is not usable — %s", pair_reason,
            )

    for key, value in overrides.items():
        if key.startswith("_"):
            continue  # skip metadata
        entry = _ADMIN_REGISTRY.get(key)
        if not entry:
            skipped += 1
            continue
        if key in _PER_AGENT_KEYS:
            # Per-agent params live in config.yaml; a value here is a stale tenant-wide leftover. Log it, do not replay it.
            skipped += 1
            logger.info(
                "Admin config startup: ignoring legacy tenant-wide entry for per-agent "
                "key %s; each agent's config.yaml is authoritative", key,
            )
            continue
        apply_fn = entry[6]
        if apply_fn is None:
            skipped += 1
            continue
        if not context_pair_ok and key in ("CONTEXT_LOADING_MODE", "CONTEXT_FILE_PATH"):
            errors += 1
            continue
        validator = _ADMIN_VALIDATORS.get(key)
        if validator is not None:
            ok, message = validator(value, tenant_id=tenant_id, agent_id=startup_agent)
            if not ok:
                errors += 1
                logger.error(
                    "Startup apply skipped for %s: a previously saved value is no longer valid — %s",
                    key, message,
                )
                continue
        try:
            apply_fn(value)
            applied += 1
        except Exception as exc:
            errors += 1
            logger.error("Startup apply failed for %s: %s", key, exc)

    logger.info(
        "Admin config startup: %d applied, %d skipped (need restart), %d errors",
        applied, skipped, errors,
    )
    return {"applied": applied, "skipped": skipped, "errors": errors}


@router.get("/api/config/entity-types")
async def get_entity_types(tenant_id: str = TENANT_ID):
    """
    Return the list of entity types configured for this tenant.
    Reads from entity_validation.yaml — no hardcoding in frontend or backend code.
    Frontend dropdowns (entity type selectors, knowledge card filters) call this
    endpoint so any domain can define its own entity types without code changes.
    """
    try:
        import yaml as _yaml
        cfg_path = (
            SERVER_DIR / DATA_ROOT / "tenants" / tenant_id / "shared" / "entity_validation.yaml"
        )
        if not cfg_path.exists():
            return {"entity_types": ["vendor", "customer"]}  # safe fallback
        with open(cfg_path, encoding="utf-8") as fh:
            data = _yaml.safe_load(fh) or {}
        types = data.get("entity_types") or ["vendor", "customer"]
        return {"entity_types": types, "tenant_id": tenant_id}
    except Exception as exc:
        logger.warning("get_entity_types failed: %s", exc)
        return {"entity_types": ["vendor", "customer"]}


@router.get("/api/config/features")
async def get_feature_flags():
    """Feature flags the frontend reads to show/hide optional subsystems.

    Observers ship feature-flagged off (OBSERVERS_ENABLED). The UI hides the
    Observers nav entry and view entirely when it is off, rather than rendering a
    404 'unavailable' card for a subsystem that is intentionally dark.
    """
    return {"observers_enabled": OBSERVERS_ENABLED}
