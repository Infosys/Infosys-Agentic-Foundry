"""Process-wide runtime bridge.

Lets an embedding host application (e.g. ``IAF-Agent-Studio``) inject services
into the engine at startup WITHOUT the engine importing the host. The host calls
the ``register_*`` functions once during boot; engine modules read services via
the ``get_*`` accessors. When nothing is registered — standalone scripts, unit
tests, or a partner embedding the engine — the accessors return ``None`` (or the
built-in default) and callers degrade gracefully.

This module deliberately has no dependencies on ``shared`` / ``routers`` /
``trace_emitter`` or any other host package.
"""

from __future__ import annotations

import logging
from typing import Any, Callable, Optional

logger = logging.getLogger(__name__)


_MODEL_PRICING: dict[str, dict[str, float]] = {
    "gpt-4o-mini":       {"input": 0.000150, "output": 0.000600},
    "gpt-4o":            {"input": 0.002500, "output": 0.010000},
    "gpt-4-turbo":       {"input": 0.010000, "output": 0.030000},
    "gpt-4":             {"input": 0.030000, "output": 0.060000},
    "gpt-3.5":           {"input": 0.000500, "output": 0.001500},
    "claude-3-5-sonnet": {"input": 0.003000, "output": 0.015000},
    "claude-3-opus":     {"input": 0.015000, "output": 0.075000},
    "claude-3-haiku":    {"input": 0.000250, "output": 0.001250},
}

_cost_fn: Optional[Callable[[str, int, int], float]] = None


def register_cost_function(fn: Optional[Callable[[str, int, int], float]]) -> None:
    """Register an authoritative cost function (host override)."""
    global _cost_fn
    _cost_fn = fn


def calculate_cost(model: str, prompt_tokens: int, completion_tokens: int) -> float:
    """Return estimated cost in USD for a single LLM call."""
    if _cost_fn is not None:
        try:
            return _cost_fn(model, prompt_tokens, completion_tokens)
        except Exception as exc:  # pragma: no cover - defensive
            logger.debug("registered cost function failed, using built-in: %s", exc)
    model_lower = (model or "").lower()
    pricing = None
    for key, value in _MODEL_PRICING.items():
        if key in model_lower:
            pricing = value
            break
    if not pricing:
        pricing = _MODEL_PRICING["gpt-4o"]
    return round(
        (prompt_tokens / 1000) * pricing["input"]
        + (completion_tokens / 1000) * pricing["output"],
        8,
    )



_trace_emitter_factory: Optional[Callable[[], Any]] = None


def register_trace_emitter_factory(factory: Optional[Callable[[], Any]]) -> None:
    """Register a zero-arg factory returning the host trace emitter."""
    global _trace_emitter_factory
    _trace_emitter_factory = factory


def get_trace_emitter() -> Any:
    """Return the host trace emitter, or None when unavailable."""
    if _trace_emitter_factory is None:
        return None
    try:
        return _trace_emitter_factory()
    except Exception as exc:  # pragma: no cover - defensive
        logger.debug("trace emitter factory failed (non-fatal): %s", exc)
        return None



_provider_config: dict[str, str] = {}


def register_provider_config(mapping: dict[str, Any]) -> None:
    """Register host provider settings (e.g. TRACE_PROVIDER=...)."""
    global _provider_config
    _provider_config = {str(k): str(v) for k, v in (mapping or {}).items() if v is not None}


def get_provider_setting(name: str) -> Optional[str]:
    """Return a registered provider setting value, or None."""
    return _provider_config.get(name)



_evidence_sink: Optional[Any] = None


def register_evidence_sink(sink: Optional[Any]) -> None:
    """Register the host evidence sink (see ``agentos_contracts.EvidenceSink``)."""
    global _evidence_sink
    _evidence_sink = sink


def get_evidence_sink() -> Optional[Any]:
    """Return the registered evidence sink, or None."""
    return _evidence_sink



_mission_bridge: Optional[Any] = None


def register_mission_bridge(bridge: Optional[Any]) -> None:
    """Register the host Mission runtime bridge.

    See ``agentos_contracts.MissionRuntimeBridge``.
    """
    global _mission_bridge
    _mission_bridge = bridge


def get_mission_bridge() -> Optional[Any]:
    """Return the registered Mission runtime bridge, or None."""
    return _mission_bridge



import os as _os

_default_tenant_id: str = _os.getenv("AGENTOS_DEFAULT_TENANT") or "company"
_default_agent_id: str = _os.getenv("AGENTOS_DEFAULT_AGENT") or "enterprise_agent"
_identity_registered: bool = False
_identity_warned: bool = False


def register_default_identity(
    tenant_id: Optional[str] = None,
    agent_id: Optional[str] = None,
) -> None:
    """Register fallback tenant/agent ids for the current deployment."""
    global _default_tenant_id, _default_agent_id, _identity_registered
    if tenant_id:
        _default_tenant_id = tenant_id
    if agent_id:
        _default_agent_id = agent_id
    _identity_registered = True


def _warn_unregistered_identity_once() -> None:
    global _identity_warned
    if not _identity_registered and not _identity_warned:
        _identity_warned = True
        logger.warning(
            "Runtime identity not registered; falling back to tenant=%r agent=%r. "
            "Call register_default_identity() or set AGENTOS_DEFAULT_TENANT/"
            "AGENTOS_DEFAULT_AGENT to avoid routing data to the wrong tenant.",
            _default_tenant_id, _default_agent_id,
        )


def default_tenant_id() -> str:
    """Return the deployment's fallback tenant id."""
    _warn_unregistered_identity_once()
    return _default_tenant_id


def default_agent_id() -> str:
    """Return the deployment's fallback agent id."""
    _warn_unregistered_identity_once()
    return _default_agent_id
