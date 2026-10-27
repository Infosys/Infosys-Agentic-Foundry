"""Tenant harness-profile registry loader.

Reads ``enterprise_root/tenants/<tenant>/config/harness_profiles.yaml`` (the tenant maintenance
surface for adding/overriding profiles) and returns a plain dict registry to pass to
``agentos_contracts.profile.resolve_profile(registry=...)``. Absent file → ``{}`` (built-in presets
are the fallback). Cached by (path, mtime) so edits hot-reload without a restart.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, Optional

from agent_os.safe_path import confine_to_root, validated_path

logger = logging.getLogger(__name__)

_CACHE: dict[str, tuple[float, Dict[str, Any]]] = {}


def _registry_path(agent_root: Path) -> Path:
    """`.../tenants/<t>/agents/<a>`  →  `.../tenants/<t>/config/harness_profiles.yaml`."""
    return agent_root.parent.parent / "config" / "harness_profiles.yaml"


def load_profile_registry(agent_root: Optional[Path]) -> Dict[str, Any]:
    """Return the tenant profile registry dict (``{default_profile, profiles}``) or ``{}``.

    Never raises — a malformed/missing file yields ``{}`` so resolution falls back to built-ins.
    """
    if not agent_root:
        return {}
    try:
        safe_root = validated_path(agent_root, label="agent_root")
        path = confine_to_root(
            _registry_path(safe_root), safe_root.parent.parent, label="harness profile registry"
        )
    except Exception as exc:
        logger.warning("Rejected harness profile registry path (%s); using built-in presets", exc)
        return {}
    if not path.exists():
        return {}
    try:
        mtime = path.stat().st_mtime
        cached = _CACHE.get(str(path))
        if cached and cached[0] == mtime:
            return cached[1]
        import yaml
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        if not isinstance(data, dict):
            logger.warning("harness_profiles.yaml at %s is not a mapping; ignoring", path)
            data = {}
        _CACHE[str(path)] = (mtime, data)
        return data
    except Exception as exc:  # never let a bad file break a run
        logger.warning("Failed to load harness_profiles.yaml (%s); using built-in presets", exc)
        return {}
