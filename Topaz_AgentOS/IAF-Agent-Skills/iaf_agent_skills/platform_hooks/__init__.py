"""
Platform-owned (built-in) hooks — framework source + load-time merge.

Built-in governance hooks (the orchestrator circuit-breaker / audit / validator set)
live HERE, in the framework package, NOT in tenant-editable config.yaml. They are
merged into every applicable agent's effective hook set at HookRunner construction
(agent.py), so they are structurally non-editable / non-deletable from the tenant UI/API.

Two-band ordering: platform hook priorities are clamped to <=99 and tenant priorities
to >=100, so platform governance always runs before tenant hooks regardless of what
priority a tenant picks (lower priority runs first; see hook_runner._hook_sort_key).

Manifest: this package's ``hooks.yaml`` (override with ``IAF_PLATFORM_HOOKS_MANIFEST``
— a PRIVILEGED governance override; intended for dev/test). Scripts: this package's
``scripts/`` dir, exposed to hooks via ``$IAF_PLATFORM_HOOKS_DIR``.

Fail-loud: a corrupt/unreadable manifest must NOT silently degrade to "no governance".
With ``IAF_PLATFORM_HOOKS_REQUIRED=true`` (default) a load/parse error raises. A
legitimately empty manifest list is fine.
"""

from __future__ import annotations

import logging
import os
import re
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger(__name__)

# hook_id format — mirrors hook_runner._validate_external_manifest.
_HOOK_ID_RE = re.compile(r"^[A-Za-z0-9_.:-]{1,128}$")

# Runtime fields HookRunner understands; everything else (applies_to, source, …) is
# manifest-only metadata and must be stripped before an entry reaches the runner.
_RUNTIME_FIELDS = {
    "hook_id", "command", "matcher", "skills", "mode", "fail_policy",
    "block_on_nonzero", "timeout_seconds", "max_output_chars", "priority",
    "owner", "permissions", "input_schema", "output_schema", "on_block", "approval",
}

_PACKAGE_DIR = Path(__file__).resolve().parent
_DEFAULT_MANIFEST = _PACKAGE_DIR / "hooks.yaml"
_SCRIPTS_DIR = _PACKAGE_DIR / "scripts"

# Module-level cache: the manifest is read once per process (changes need a restart).
_manifest_cache: list[dict] | None = None


class PlatformHookConfigError(RuntimeError):
    """Raised when a required platform-hook manifest is missing or unparseable."""


def _required() -> bool:
    return os.environ.get("IAF_PLATFORM_HOOKS_REQUIRED", "true").strip().lower() != "false"


def _manifest_path() -> Path:
    from iaf_agent_skills.app_config import skills_config
    override = skills_config.platform_hooks_manifest.strip()
    if not override:
        return _DEFAULT_MANIFEST
    # Resolve to an absolute path and require a .yaml extension so an
    # accidentally misconfigured value can't redirect to an arbitrary file.
    p = Path(override).resolve()
    if p.suffix not in (".yaml", ".yml"):
        raise PlatformHookConfigError(
            f"IAF_PLATFORM_HOOKS_MANIFEST must point to a .yaml file, got: {override!r}"
        )
    return p


def platform_hooks_dir() -> str:
    """Filesystem dir of platform hook scripts (value of $IAF_PLATFORM_HOOKS_DIR)."""
    return str(_SCRIPTS_DIR)


def load_platform_manifest(*, force_reload: bool = False) -> list[dict]:
    """Load + cache the platform hook manifest (a flat list of entries).

    Fail-loud: a parse error, or a missing manifest while required, raises
    PlatformHookConfigError so a broken governance deploy cannot run silently.
    An empty/whitelisted-off manifest returns [].
    """
    global _manifest_cache
    if _manifest_cache is not None and not force_reload:
        return _manifest_cache

    path = _manifest_path()
    if not path.exists():
        if _required():
            raise PlatformHookConfigError(
                f"Platform hook manifest not found at {path} and "
                "IAF_PLATFORM_HOOKS_REQUIRED is true. Set it to 'false' to allow none."
            )
        logger.warning("Platform hook manifest missing at %s — proceeding with none.", path)
        _manifest_cache = []
        return _manifest_cache

    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except Exception as exc:  # parse error — never degrade silently
        raise PlatformHookConfigError(f"Failed to parse platform hook manifest {path}: {exc}") from exc

    if data is None:
        _manifest_cache = []
        logger.info("Loaded 0 platform hook(s) from %s", path)
        return _manifest_cache
    if not isinstance(data, list):
        raise PlatformHookConfigError(
            f"Platform hook manifest {path} must be a YAML list of hook entries, got {type(data).__name__}."
        )

    _manifest_cache = _validate_manifest(data, path)
    logger.info("Loaded %d platform hook(s) from %s", len(_manifest_cache), path)
    return _manifest_cache


def _validate_manifest(data: list, path) -> list[dict]:
    """Schema-validate platform manifest entries. Governance must not silently lose a
    hook to a schema typo: when required (default), any violation raises; in the dev
    escape (IAF_PLATFORM_HOOKS_REQUIRED=false) bad entries are warned + dropped.
    """
    from ..hook_runner import ALLOWED_HOOK_EVENTS as allowed_events  # lazy: avoids import cycle
    required = _required()
    valid: list[dict] = []
    seen_ids: set[str] = set()

    def _bad(msg: str):
        if required:
            raise PlatformHookConfigError(f"Platform hook manifest {path}: {msg}")
        logger.warning("Platform hook manifest %s: %s — dropping entry", path, msg)

    for idx, entry in enumerate(data):
        loc = f"entry[{idx}]"
        if not isinstance(entry, dict):
            _bad(f"{loc} is not a mapping"); continue
        hook_id = entry.get("hook_id")
        if not isinstance(hook_id, str) or not _HOOK_ID_RE.match(hook_id):
            _bad(f"{loc} missing/invalid 'hook_id'"); continue
        if hook_id in seen_ids:
            _bad(f"duplicate hook_id {hook_id!r}"); continue
        event = entry.get("event")
        if event not in allowed_events:
            _bad(f"{hook_id}: unknown event {event!r}"); continue
        if not isinstance(entry.get("command"), str) or not entry["command"].strip():
            _bad(f"{hook_id}: missing/empty 'command'"); continue
        if "priority" in entry:
            try:
                int(entry["priority"])
            except (TypeError, ValueError):
                _bad(f"{hook_id}: non-numeric 'priority' {entry['priority']!r}"); continue
        applies = entry.get("applies_to", {"scope": "all"})
        if not isinstance(applies, dict) or str(applies.get("scope", "all")).lower() not in ("all", "tenants", "agents"):
            _bad(f"{hook_id}: invalid 'applies_to'"); continue
        seen_ids.add(hook_id)
        valid.append(entry)
    return valid


def _entry_applies(entry: dict, agent_id: str, tenant_id: str) -> bool:
    """Evaluate applies_to (coarse, construction-time: agents / tenants / all)."""
    applies = entry.get("applies_to") or {"scope": "all"}
    scope = str(applies.get("scope", "all")).lower()
    if scope == "all":
        return True
    if scope == "tenants":
        return tenant_id in (applies.get("tenants") or [])
    if scope == "agents":
        agents = applies.get("agents") or []
        # support optional tenant-qualified form "tenant/agent"
        return agent_id in agents or f"{tenant_id}/{agent_id}" in agents
    logger.warning("Platform hook %s: unknown applies_to.scope=%r — treating as not-applicable",
                   entry.get("hook_id"), scope)
    return False


def to_runtime_hook(entry: dict, *, owner: str) -> dict:
    """Strip manifest-only metadata; keep only fields HookRunner understands; stamp owner."""
    runtime = {k: v for k, v in entry.items() if k in _RUNTIME_FIELDS}
    runtime["owner"] = owner
    return runtime


def platform_hook_ids() -> set[str]:
    """All hook_ids declared in the manifest (used to reject tenant collisions)."""
    return {str(e.get("hook_id")) for e in load_platform_manifest() if e.get("hook_id")}


def applicable_platform_hooks(agent_id: str, tenant_id: str) -> list[dict]:
    """Raw manifest entries that apply to this agent (for read-only API/UI display)."""
    return [e for e in load_platform_manifest() if _entry_applies(e, agent_id, tenant_id)]


def _coerce_priority(value, default: int, *, owner: str, hook_id: str) -> int:
    """Coerce a hook priority to int, safely.

    A malformed priority must NOT crash agent construction. For a platform hook it's
    a manifest bug → raise (fail loud). For a tenant hook → warn + use the default so a
    bad config.yaml entry can't take the agent down.
    """
    if value is None or value == "":
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        if owner == "platform":
            raise PlatformHookConfigError(
                f"Platform hook {hook_id!r} has non-numeric priority {value!r}."
            )
        logger.warning("Tenant hook %s has non-numeric priority %r — using default %d",
                       hook_id or "?", value, default)
        return default


def resolve_effective_hooks(tenant_hooks: dict | None, agent_id: str, tenant_id: str) -> dict:
    """Merge platform (framework) hooks with tenant (config.yaml) hooks for HookRunner.

    Returns ``{event: [platform..., tenant...]}``. Platform-first is guaranteed two ways:
    platform entries are appended first per event AND clamped to priority <=99 while
    tenant entries are clamped to >=100.
    """
    effective: dict[str, list] = {}

    # 1) Platform hooks first, in band 0..99.
    for entry in applicable_platform_hooks(agent_id, tenant_id):
        event = entry.get("event")
        if not event:
            logger.warning("Platform hook %s has no event — skipping", entry.get("hook_id"))
            continue
        runtime = to_runtime_hook(entry, owner="platform")
        prio = _coerce_priority(runtime.get("priority"), 50, owner="platform",
                                hook_id=str(runtime.get("hook_id", "")))
        runtime["priority"] = min(prio, 99)
        effective.setdefault(event, []).append(runtime)

    reserved = platform_hook_ids()

    # 2) Tenant hooks after, in band 100+, sanitized (owner forced, metadata stripped).
    for event, entries in (tenant_hooks or {}).items():
        if not isinstance(entries, list):
            continue
        for raw in entries:
            if not isinstance(raw, dict):
                continue
            if raw.get("hook_id") in reserved:
                logger.warning("Dropping tenant hook reusing reserved platform hook_id: %s",
                               raw.get("hook_id"))
                continue
            runtime = to_runtime_hook(raw, owner="tenant")
            prio = _coerce_priority(runtime.get("priority"), 100, owner="tenant",
                                    hook_id=str(runtime.get("hook_id", "")))
            runtime["priority"] = max(prio, 100)
            effective.setdefault(event, []).append(runtime)

    return effective
