"""Provider-neutral entitlement data models."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class Principal:
    user_id: str
    email: str = ""
    tenant_id: str = "company"
    roles: tuple[str, ...] = ("user",)
    groups: tuple[str, ...] = ()
    allowed_tenants: tuple[str, ...] = ("company",)
    attributes: dict[str, Any] = field(default_factory=dict)

    def has_role(self, role: str) -> bool:
        return role in self.roles


@dataclass(frozen=True)
class Resource:
    type: str
    id: str
    tenant_id: str = "company"
    attributes: dict[str, Any] = field(default_factory=dict)

    @property
    def key(self) -> str:
        return f"{self.type}:{self.id}"


@dataclass(frozen=True)
class Decision:
    allowed: bool
    reason: str = ""
    matched_policy: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class PolicyDecisionInput:
    principal: Principal
    tenant_id: str
    action: str
    resource: Resource
    tool_name: str = ""
    skill_name: str = ""
    risk_level: str = ""
    request_context: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_parts(
        cls,
        principal: Principal,
        action: str,
        resource: Resource,
        context: dict[str, Any] | None = None,
    ) -> "PolicyDecisionInput":
        request_context = dict(context or {})
        tenant_id = resource.tenant_id or principal.tenant_id
        tool_name = str(
            request_context.get("tool_name")
            or request_context.get("tool")
            or (resource.id if resource.type == "tool" else "")
            or ""
        )
        skill_name = str(request_context.get("skill_name") or request_context.get("skill") or "")
        risk_level = str(
            request_context.get("risk_level")
            or request_context.get("risk")
            or resource.attributes.get("risk", "")
            or ""
        )
        return cls(
            principal=principal,
            tenant_id=tenant_id,
            action=action,
            resource=resource,
            tool_name=tool_name,
            skill_name=skill_name,
            risk_level=risk_level,
            request_context=request_context,
        )

    def metadata(self, request_context: dict[str, Any] | None = None) -> dict[str, Any]:
        return {
            "tenant_id": self.tenant_id,
            "principal_user_id": self.principal.user_id,
            "principal_roles": list(self.principal.roles),
            "principal_groups": list(self.principal.groups),
            "action": self.action,
            "resource_type": self.resource.type,
            "resource_id": self.resource.id,
            "tool_name": self.tool_name,
            "skill_name": self.skill_name,
            "risk_level": self.risk_level,
            "request_context": request_context if request_context is not None else dict(self.request_context),
        }
