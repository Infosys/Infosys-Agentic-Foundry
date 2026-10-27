"""Dependency-free React runtime selection helpers."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Mapping


VALID_REACT_RUNTIMES = {"langgraph", "native"}
DEFAULT_REACT_RUNTIME = "langgraph"


@dataclass(frozen=True)
class ReactRuntimeSelection:
    """Resolved React runtime and the source that selected it."""

    runtime: str
    source: str
    fallback_reason: str = ""


def _as_mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _read_config_runtime(config: Mapping[str, Any]) -> str:
    if "react_runtime" in config:
        return str(config.get("react_runtime") or "")
    react_cfg = _as_mapping(config.get("react"))
    if "runtime" in react_cfg:
        return str(react_cfg.get("runtime") or "")
    runtime_cfg = _as_mapping(config.get("runtime"))
    if "react_runtime" in runtime_cfg:
        return str(runtime_cfg.get("react_runtime") or "")
    return ""


def _normalize_runtime(value: str, *, source: str) -> ReactRuntimeSelection | None:
    runtime = (value or "").strip().lower()
    if not runtime:
        return None
    if runtime in VALID_REACT_RUNTIMES:
        return ReactRuntimeSelection(runtime=runtime, source=source)
    return ReactRuntimeSelection(
        runtime=DEFAULT_REACT_RUNTIME,
        source=source,
        fallback_reason=f"Unknown react runtime '{value}', falling back to {DEFAULT_REACT_RUNTIME}",
    )


def resolve_react_runtime(
    *,
    skill: Any = None,
    config: Mapping[str, Any] | None = None,
    env: Mapping[str, str] | None = None,
    routing_info: Mapping[str, Any] | None = None,
) -> ReactRuntimeSelection:
    """Resolve the React runtime without changing the skill execution mode."""

    config_map = _as_mapping(config or {})
    env_map: Mapping[str, str] = env if env is not None else os.environ
    routing_map = _as_mapping(routing_info or {})

    candidates = (
        (routing_map.get("react_runtime"), "request"),
        (getattr(skill, "react_runtime", "") if skill is not None else "", "skill"),
        (_read_config_runtime(config_map), "config"),
        (env_map.get("IAF_REACT_RUNTIME", ""), "env"),
    )
    for value, source in candidates:
        selection = _normalize_runtime(str(value or ""), source=source)
        if selection is not None:
            return selection
    return ReactRuntimeSelection(runtime=DEFAULT_REACT_RUNTIME, source="default")
