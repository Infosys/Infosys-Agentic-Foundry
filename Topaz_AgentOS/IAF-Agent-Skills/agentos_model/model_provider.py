"""Adapter boundary for model provider and catalog capabilities."""

from __future__ import annotations

import os
import json
from typing import Any

from .model_registry import AZURE_ROLE_ENV_MAP, ROLE_ALIAS, ModelRegistry
from agentos_contracts import resolve_react_runtime


class ModelProviderAdapter:
    """Thin adapter over ModelRegistry for swappable model provider wiring."""

    DEFAULT_ROLES = ("primary", "light", "router", "queue_router", "fallback")

    def __init__(self, registry: type[ModelRegistry] = ModelRegistry, roles: tuple[str, ...] | None = None) -> None:
        self.registry = registry
        self.roles = tuple(roles or self.DEFAULT_ROLES)

    def get(self, role: str = "primary") -> Any:
        """Return the model for a role using the existing registry semantics."""
        return self.registry.get(self._routed_role(role))

    def reset(self) -> None:
        """Clear cached model instances when supported by the backing registry."""
        reset = getattr(self.registry, "reset", None)
        if callable(reset):
            reset()

    def snapshot(self) -> dict[str, Any]:
        """Return log-safe model catalog metadata without creating models."""
        cached = getattr(self.registry, "_instances", {})
        runtime_selection = resolve_react_runtime(config={}, env=os.environ)
        return {
            "provider": getattr(self.registry, "__name__", type(self.registry).__name__),
            "roles": list(self.roles),
            "cached_roles": sorted(str(role) for role in cached.keys()),
            "role_aliases": dict(sorted(ROLE_ALIAS.items())),
            "azure_role_env_map": dict(sorted(AZURE_ROLE_ENV_MAP.items())),
            "react_runtime_default": runtime_selection.runtime,
            "react_runtime_source": runtime_selection.source,
            "react_runtime_fallback_reason": runtime_selection.fallback_reason[:200],
            "eval_router_enabled": _truthy(os.getenv("EVAL_ROUTER_ENABLED", "")),
            "eval_router_roles": sorted(_role_map().keys()),
        }

    def _routed_role(self, role: str) -> str:
        if not _truthy(os.getenv("EVAL_ROUTER_ENABLED", "")):
            return role
        clean_role = str(role or "primary")
        direct = os.getenv(f"EVAL_ROUTER_ROLE_{clean_role.upper()}", "").strip()
        if direct:
            return direct
        mapped = _role_map().get(clean_role)
        if isinstance(mapped, str) and mapped.strip():
            return mapped.strip()
        if isinstance(mapped, dict):
            candidate = str(mapped.get("role") or "").strip()
            if candidate:
                return candidate
        return role


def _truthy(value: str) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def _role_map() -> dict[str, Any]:
    raw = os.getenv("EVAL_ROUTER_ROLE_MAP", "").strip()
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


default_model_provider = ModelProviderAdapter()