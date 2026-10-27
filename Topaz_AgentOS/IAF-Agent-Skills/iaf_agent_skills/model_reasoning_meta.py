"""Compatibility shim for provider-neutral reasoning metadata."""

from agentos_model.model_reasoning_meta import (
    ReasoningCapability,
    ReasoningDial,
    ReasoningWireFormat,
    TRUTHY_ENV_VALUES,
    get_reasoning_capability,
    is_truthy_env,
    provider_env_prefix,
    reasoning_expose_enabled,
    reasoning_replay_enabled,
)

__all__ = [
    "ReasoningCapability",
    "ReasoningDial",
    "ReasoningWireFormat",
    "TRUTHY_ENV_VALUES",
    "get_reasoning_capability",
    "is_truthy_env",
    "provider_env_prefix",
    "reasoning_expose_enabled",
    "reasoning_replay_enabled",
]
