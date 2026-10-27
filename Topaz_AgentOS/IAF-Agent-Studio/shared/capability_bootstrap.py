"""Studio bootstrap for the passive capability registry.

This module registers existing Studio singletons as capability providers. It is
diagnostic infrastructure only; runtime code continues to call the existing
objects directly until each adapter is migrated behind tests and flags.
"""

from __future__ import annotations

import logging
from typing import Any

from iaf_agent_skills.capability_registry import CapabilityRegistry
from iaf_agent_skills.model_provider import default_model_provider
from iaf_agent_skills.tool_execution_capability import ToolExecutionCapability
from iaf_agent_skills.credential_resolver_adapter import CredentialResolverAdapter
from iaf_agent_skills.evidence_collector_adapter import EvidenceCollectorAdapter
from iaf_agent_skills.memory_capability import MEMORY_CAPABILITY_FLAG
from iaf_agent_skills.providers.factory import (
    build_hook_provider,
    build_router_provider,
    build_skill_provider,
    build_tool_provider,
    build_trace_provider,
)
from iaf_agent_skills.taxonomy_routing_capability import (
    TAXONOMY_ROUTING_MODE_ENV,
    TAXONOMY_SHADOW_SAMPLE_RATE_ENV,
)


logger = logging.getLogger("iaf_server")

_METADATA_BLOCKED_KEYS = {
    "authorization",
    "headers",
    "endpoint",
    "url",
    "password",
    "secret",
    "token",
    "api_key",
    "apikey",
    "client_secret",
    "access_token",
    "refresh_token",
}


class _PassivePlaceholder:
    """Named placeholder for contracts whose existing provider is not wired yet."""

    def __init__(self, name: str, reason: str) -> None:
        self.name = name
        self.reason = reason


def _safe_metadata(value: Any, *, limit: int = 512) -> Any:
    """Return bounded metadata safe for startup logs and snapshot APIs."""
    if isinstance(value, dict):
        cleaned = {}
        for key, item in value.items():
            key_text = str(key)
            if key_text.lower() in _METADATA_BLOCKED_KEYS:
                continue
            cleaned[key_text] = _safe_metadata(item, limit=limit)
        return cleaned
    if isinstance(value, list):
        return [_safe_metadata(item, limit=limit) for item in value[:50]]
    if isinstance(value, str):
        return value if len(value) <= limit else value[: limit - 14] + "...[TRUNCATED]"
    return value


def _emitter_metadata(emitter: Any, *, local_db: str) -> dict:
    metadata = {"local_store": "sqlite", "local_db": local_db}
    if emitter is None:
        metadata["telemetry_provider"] = {"mode": "disabled", "provider_count": 0, "providers": []}
        return metadata
    diagnostics = {"mode": "local_sqlite_only", "provider_count": 0, "providers": []}
    if hasattr(emitter, "telemetry_diagnostics"):
        try:
            diagnostics = emitter.telemetry_diagnostics()
        except Exception:
            diagnostics = {"mode": "unknown", "provider_count": 0, "providers": []}
    metadata["telemetry_provider"] = _safe_metadata(diagnostics)
    return metadata


def _provider_health(provider: Any) -> dict:
    if hasattr(provider, "health"):
        try:
            return _safe_metadata(provider.health())
        except Exception as exc:
            logger.warning("Provider health check failed: %s", exc, exc_info=True)
            return {"status": "unhealthy", "error": "health check failed"}
    return {}


def build_capability_registry(
    *,
    trace_emitter: Any,
    twin_emitter: Any,
    queue_manager: Any,
    cron_scheduler: Any,
    approval_store: Any,
) -> CapabilityRegistry:
    """Build a passive registry over already-created Studio implementations."""
    registry = CapabilityRegistry()

    registry.register(
        "model_provider",
        default_model_provider,
        implementation="ModelProviderAdapter",
        owner="iaf_agent_skills",
        metadata={
            "mode": "adapter_boundary",
            "backing_provider": "ModelRegistry",
            "provider_status": "incremental_hardening",
            "runtime_resolution": "default_model_provider.get(role)",
            "react_runtime_selector": "execution_mode=react uses react_runtime=langgraph|native; default=langgraph",
        },
    )
    registry.register(
        "model_catalog",
        default_model_provider,
        implementation="ModelProviderAdapter",
        owner="iaf_agent_skills",
        dependencies=("model_provider",),
        metadata={
            "mode": "adapter_boundary",
            "backing_provider": "ModelRegistry",
            "provider_status": "incremental_hardening",
            "runtime_resolution": "default_model_provider.get(role)",
            "react_runtime_selector": "execution_mode=react uses react_runtime=langgraph|native; default=langgraph",
        },
    )

    try:
        from pathlib import Path as _Path
        from shared.config import SERVER_DIR, SKILLS_PATH  # type: ignore

        _skills_path = str(_Path(SERVER_DIR) / str(SKILLS_PATH))
    except Exception:
        _skills_path = "../IAF-Agent-Skills/skills"

    for _name, _builder, _implementation, _deps in (
        ("skill_provider", lambda: build_skill_provider(_skills_path), "SkillProvider", ()),
        ("router_provider", lambda: build_router_provider(_skills_path), "RouterProvider", ("skill_provider", "model_provider")),
        ("tool_provider", build_tool_provider, "ToolProvider", ("policy_engine",)),
        ("hook_provider", build_hook_provider, "HookProvider", ("trace_provider",)),
        ("trace_provider", lambda: build_trace_provider(emitter=trace_emitter), "TraceProvider", ("trace_emitter",)),
    ):
        try:
            _provider = _builder()
        except Exception as exc:  # pragma: no cover - diagnostic fallback
            _provider = _PassivePlaceholder(_name, f"provider unavailable: {exc}")
        registry.register(
            _name,
            _provider,
            implementation=type(_provider).__name__ if not isinstance(_provider, _PassivePlaceholder) else _implementation,
            owner="iaf_agent_skills",
            dependencies=_deps,
            enabled=not isinstance(_provider, _PassivePlaceholder),
            metadata={
                "mode": "adapter_boundary",
                "runtime_resolution": "iaf_agent_skills.providers.factory",
                "provider_health": _provider_health(_provider),
            },
        )
    # Constructed lazily so registry creation in unit tests needs no filesystem layout.
    try:
        from shared.config import SERVER_DIR, DATA_ROOT, TENANT_ID  # type: ignore
        from pathlib import Path as _Path
        _cred_config_dir = _Path(SERVER_DIR) / DATA_ROOT / "tenants" / TENANT_ID / "shared" / "config"
        _credential_resolver = CredentialResolverAdapter(config_dir=_cred_config_dir)
    except Exception:  # pragma: no cover - test-mode fallback
        _credential_resolver = CredentialResolverAdapter()
    registry.register(
        "credential_resolver",
        _credential_resolver,
        implementation="CredentialResolverAdapter",
        owner="iaf_agent_skills",
        metadata={
            "mode": "adapter_boundary",
            "backing_store": "agent_os.credential_store",
            "secret_provider": _safe_metadata(_credential_resolver.health()),
        },
    )
    # NoopEntitlementProvider is an alternate so dev/test can disable enforcement.
    try:
        from security.provider import get_entitlement_provider as _get_ent_provider  # type: ignore
        _default_policy = _get_ent_provider()
    except Exception:  # pragma: no cover - test-mode fallback
        _default_policy = _PassivePlaceholder("policy_engine", "security provider unavailable")
    registry.register(
        "policy_engine",
        _default_policy,
        implementation=type(_default_policy).__name__,
        owner="IAF-Agent-Studio/security",
        dependencies=("credential_resolver",),
        metadata={
            "mode": "adapter_boundary",
            "policy_provider": _safe_metadata(_default_policy.health()) if hasattr(_default_policy, "health") else {},
        },
    )
    registry.register(
        "trace_emitter",
        trace_emitter,
        implementation="TraceEmitter" if trace_emitter is not None else "TraceEmitterDisabled",
        owner="IAF-Agent-Studio",
        enabled=trace_emitter is not None,
        metadata=_emitter_metadata(trace_emitter, local_db="traces.db"),
    )
    registry.register(
        "twin_emitter",
        twin_emitter,
        implementation="TwinEmitter" if twin_emitter is not None else "TwinEmitterDisabled",
        owner="IAF-Agent-Studio",
        enabled=twin_emitter is not None,
        metadata=_emitter_metadata(twin_emitter, local_db="twin_telemetry.db"),
    )
    # Swap surface for external evidence sinks; existing direct callers are unchanged.
    _evidence_collector = EvidenceCollectorAdapter()
    registry.register(
        "evidence_collector",
        _evidence_collector,
        implementation="EvidenceCollectorAdapter",
        owner="iaf_agent_skills",
        dependencies=("trace_emitter",),
        metadata={
            "mode": "adapter_boundary",
            "backing": "document_evidence + audit_evidence_sinks",
            "evidence_sinks": _safe_metadata(_evidence_collector.health()),
        },
    )
    registry.register(
        "memory_capability",
        _PassivePlaceholder(
            "memory_capability",
            "MemoryCapability is created per SkillAgent because AgentMemory is session-scoped",
        ),
        implementation="MemoryCapability",
        owner="iaf_agent_skills",
        metadata={
            "agent_scope": "per_agent_instance",
            "backing_store": "filesystem+sqlite",
            "enable_flag": MEMORY_CAPABILITY_FLAG,
            "mode": "pass_through",
            "provider_status": "deferred_parity_required",
            "runtime_resolution": "direct_memory_until_flag_enabled",
            "defer_reason": "memory/vector providers require behavior and corpus parity before swapping",
            "writes_default": "direct_memory",
        },
    )
    registry.register(
        "tool_execution",
        ToolExecutionCapability,
        implementation="ToolExecutionCapability",
        owner="iaf_agent_skills",
        dependencies=("trace_emitter", "policy_engine", "evidence_collector"),
        metadata={"mode": "per_agent_passive_observer"},
    )
    registry.register(
        "execution_router",
        {"queue_manager": queue_manager, "cron_scheduler": cron_scheduler},
        implementation="CronSchedulerAndQueueManager",
        owner="IAF-Agent-Studio/shared.state",
        dependencies=("policy_engine", "tool_execution"),
        metadata={
            "mode": "direct_and_queue_runtime_preserved",
            "provider_status": "deferred_customer_demand",
            "runtime_resolution": "direct_local_singletons",
            "defer_reason": "queue and workflow providers are deferred until Azure Service Bus, Kafka, SQS, ServiceNow, Jira, or Teams workflow is required",
        },
    )
    registry.register(
        "approval_store",
        approval_store,
        implementation="ApprovalStore",
        owner="iaf_agent_skills",
        dependencies=("policy_engine",),
        metadata={
            "mode": "direct_runtime_preserved",
            "provider_status": "deferred_customer_demand",
            "runtime_resolution": "direct_approval_store_singleton",
            "defer_reason": "approval workflow adapters are deferred until a target system of record is selected",
        },
    )
    # No formal adapter contract yet; PassivePlaceholder marks it known-but-unwrapped.
    registry.register(
        "taxonomy_signal_index",
        _PassivePlaceholder(
            "taxonomy_signal_index",
            "indexing runs within SkillAgent and is wrapped by taxonomy_routing",
        ),
        implementation="TaxonomySignalIndex",
        owner="iaf_agent_skills",
        metadata={"mode": "wrapped_provider", "swap_target": False, "wrapped_by": "taxonomy_routing"},
    )
    registry.register(
        "taxonomy_routing",
        _PassivePlaceholder(
            "taxonomy_routing",
            "TaxonomyRoutingCapability is created per SkillAgent around TaxonomySignalIndex",
        ),
        implementation="TaxonomyRoutingCapability",
        owner="iaf_agent_skills",
        dependencies=("taxonomy_signal_index",),
        metadata={
            "backing_provider": "TaxonomySignalIndex",
            "diagnostics": "bounded_in_memory_drift_log",
            "current_result_authoritative": True,
            "mode_env": TAXONOMY_ROUTING_MODE_ENV,
            "provider_status": "deferred_quality_parity_required",
            "shadow_sample_rate_env": TAXONOMY_SHADOW_SAMPLE_RATE_ENV,
            "swap_target": False,
            "defer_reason": "taxonomy/routing providers must prove routing-quality parity in shadow mode before becoming authoritative",
            "valid_modes": "current|shadow",
        },
    )

    registry.validate_dependencies()
    return registry


def log_capability_registry(registry: CapabilityRegistry) -> None:
    """Emit redacted startup metadata for diagnostics."""
    for item in registry.snapshot():
        logger.info(
            "Capability: %s -> %s enabled=%s deps=%s owner=%s",
            item["name"],
            item["implementation"],
            item["enabled"],
            item["dependencies"],
            item["owner"],
        )