"""Entitlement provider contract and provider factory."""

from __future__ import annotations

from abc import ABC, abstractmethod
from functools import lru_cache
from typing import Any

from shared.config import ENTITLEMENTS_ENABLED, ENTITLEMENTS_ENFORCEMENT_MODE, ENTITLEMENTS_PROVIDER

from .audit import audit_decision, sanitize_policy_context
from .models import Decision, PolicyDecisionInput, Principal, Resource


def _enforcement_mode() -> str:
    mode = str(ENTITLEMENTS_ENFORCEMENT_MODE or "enforce").lower()
    return "observe" if mode == "observe" else "enforce"


def _with_metadata(decision: Decision, metadata: dict[str, Any]) -> Decision:
    merged = dict(decision.metadata or {})
    merged.update(metadata)
    return Decision(decision.allowed, decision.reason, decision.matched_policy, merged)


class EntitlementProvider(ABC):
    @abstractmethod
    def can(
        self,
        principal: Principal,
        action: str,
        resource: Resource,
        context: dict[str, Any] | None = None,
    ) -> Decision:
        ...

    def check(
        self,
        principal: Principal,
        action: str,
        resource: Resource,
        context: dict[str, Any] | None = None,
    ) -> Decision:
        policy_input = PolicyDecisionInput.from_parts(principal, action, resource, context)
        error_type = ""
        try:
            evaluate = getattr(self, "evaluate", None)
            if evaluate is None:
                decision = EntitlementProvider.evaluate(self, policy_input)
            else:
                decision = evaluate(policy_input)
        except Exception as exc:
            error_type = type(exc).__name__
            decision = Decision(
                False,
                reason="entitlement provider unavailable",
                matched_policy="provider_unavailable",
                metadata={"error_type": error_type},
            )
        decision = EntitlementProvider._apply_enforcement_mode(self, decision)
        EntitlementProvider._record_decision(self, decision, error_type=error_type)
        audit_decision(principal, action, resource, decision, EntitlementProvider._provider_context(self, policy_input))
        return decision

    def evaluate(self, policy_input: PolicyDecisionInput) -> Decision:
        principal = policy_input.principal
        resource = policy_input.resource
        if not (principal.user_id or principal.email):
            return Decision(
                False,
                reason="missing identity",
                matched_policy="missing_identity",
                metadata={"effect": "deny"},
            )
        if resource.tenant_id and principal.tenant_id and resource.tenant_id != principal.tenant_id:
            return Decision(
                False,
                reason="tenant mismatch",
                matched_policy="tenant_mismatch",
                metadata={"effect": "deny"},
            )
        if principal.allowed_tenants and policy_input.tenant_id not in principal.allowed_tenants:
            return Decision(
                False,
                reason="tenant access denied",
                matched_policy="tenant_mismatch",
                metadata={"effect": "deny"},
            )
        return self.can(
            principal,
            policy_input.action,
            resource,
            EntitlementProvider._provider_context(self, policy_input),
        )

    def health(self) -> dict[str, Any]:
        stats = EntitlementProvider._stats(self)
        return {
            "provider": type(self).__name__,
            "available": stats.get("last_error_type", "") == "",
            "enforcement_mode": _enforcement_mode(),
            "check_count": stats["check_count"],
            "allow_count": stats["allow_count"],
            "deny_count": stats["deny_count"],
            "error_count": stats["error_count"],
            "observe_allow_count": stats["observe_allow_count"],
            "last_error_type": stats.get("last_error_type", ""),
            "redaction": "policy context values are bounded and sensitive keys are redacted",
        }

    def _provider_context(self, policy_input: PolicyDecisionInput) -> dict[str, Any]:
        sanitized_request_context = sanitize_policy_context(policy_input.request_context)
        provider_context = dict(sanitized_request_context)
        provider_context["policy_input"] = policy_input.metadata(sanitized_request_context)
        return provider_context

    def _apply_enforcement_mode(self, decision: Decision) -> Decision:
        mode = _enforcement_mode()
        if mode == "observe" and not decision.allowed:
            metadata = dict(decision.metadata or {})
            metadata.update(
                {
                    "enforcement_mode": "observe",
                    "observed_allowed": False,
                    "observed_reason": decision.reason,
                    "effective_allowed": True,
                }
            )
            return Decision(
                True,
                reason=f"observe-only: {decision.reason or 'would deny'}",
                matched_policy=decision.matched_policy,
                metadata=metadata,
            )
        return _with_metadata(decision, {"enforcement_mode": mode})

    def _stats(self) -> dict[str, Any]:
        stats = getattr(self, "_policy_provider_stats", None)
        if not isinstance(stats, dict):
            stats = {
                "check_count": 0,
                "allow_count": 0,
                "deny_count": 0,
                "error_count": 0,
                "observe_allow_count": 0,
                "last_error_type": "",
            }
            setattr(self, "_policy_provider_stats", stats)
        return stats

    def _record_decision(self, decision: Decision, *, error_type: str = "") -> None:
        stats = EntitlementProvider._stats(self)
        stats["check_count"] += 1
        if decision.allowed:
            stats["allow_count"] += 1
        else:
            stats["deny_count"] += 1
        if error_type:
            stats["error_count"] += 1
            stats["last_error_type"] = error_type
        if decision.metadata.get("enforcement_mode") == "observe" and decision.metadata.get("observed_allowed") is False:
            stats["observe_allow_count"] += 1


class NoopEntitlementProvider(EntitlementProvider):
    def can(
        self,
        principal: Principal,
        action: str,
        resource: Resource,
        context: dict[str, Any] | None = None,
    ) -> Decision:
        return Decision(True, reason="entitlements disabled", matched_policy="noop")


@lru_cache(maxsize=1)
def get_entitlement_provider() -> EntitlementProvider:
    if not ENTITLEMENTS_ENABLED:
        return NoopEntitlementProvider()
    if ENTITLEMENTS_PROVIDER == "yaml":
        from .yaml_provider import YamlEntitlementProvider

        return YamlEntitlementProvider()
    raise RuntimeError(f"Unknown ENTITLEMENTS_PROVIDER={ENTITLEMENTS_PROVIDER!r}")
