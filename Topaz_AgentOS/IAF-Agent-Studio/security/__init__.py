"""Framework-level entitlement helpers for AgentPro Studio."""

from .models import Decision, Principal, Resource
from .provider import EntitlementProvider, get_entitlement_provider

__all__ = [
    "Decision",
    "EntitlementProvider",
    "Principal",
    "Resource",
    "get_entitlement_provider",
]
