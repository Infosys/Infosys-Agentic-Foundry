"""Compatibility shim for the AgentOS model registry."""

from agentos_model.model_registry import (
    AZURE_ROLE_ENV_MAP,
    ROLE_ALIAS,
    ModelRegistry,
    _api_version_supports_reasoning,
    _reasoning_kwargs_for,
    _role_key,
    llm_base_url,
    llm_model_name,
)

__all__ = [
    "AZURE_ROLE_ENV_MAP",
    "ROLE_ALIAS",
    "ModelRegistry",
    "_api_version_supports_reasoning",
    "_reasoning_kwargs_for",
    "_role_key",
    "llm_base_url",
    "llm_model_name",
]
