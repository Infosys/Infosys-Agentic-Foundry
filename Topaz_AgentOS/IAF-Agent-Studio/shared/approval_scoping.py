"""Role- and tenant-scoped filtering for Command Center approval reads."""

from __future__ import annotations

from typing import Any, Iterable

from security.models import Principal


def is_admin_principal(principal: Principal) -> bool:
    return principal.has_role("admin")


def effective_observability_user_id(
    principal: Principal,
    caller_user: str,
    requested_user: str = "",
) -> str:
    """Non-admins always query their own traces/audit rows."""
    if is_admin_principal(principal):
        return (requested_user or "").strip()
    return caller_user


def approval_owner_id(item: dict[str, Any]) -> str:
    """Resolve the owning user for a kernel or HITL approval record."""
    for key in ("user_id", "requested_by", "email"):
        value = item.get(key)
        if value:
            return str(value)
    return ""


def scope_approval_records(
    items: Iterable[dict[str, Any]],
    *,
    principal: Principal,
    tenant_id: str,
) -> list[dict[str, Any]]:
    """Return only approval rows the caller is entitled to see.

    Admins receive every row for the resolved tenant. Non-admins receive only
    rows they own. Rows from other tenants are always excluded.
    """
    scoped: list[dict[str, Any]] = []
    caller = principal.email or principal.user_id
    admin = is_admin_principal(principal)
    for item in items:
        row_tenant = str(item.get("tenant_id") or tenant_id)
        if row_tenant != tenant_id:
            continue
        if admin:
            scoped.append(item)
            continue
        owner = approval_owner_id(item)
        if owner and owner == caller:
            scoped.append(item)
    return scoped


def _avg_resolution_seconds(history: list[dict[str, Any]]) -> "int | None":
    """Mean seconds between created_at and decided_at across resolved rows."""
    from datetime import datetime

    durations: list[float] = []
    for row in history:
        created = str(row.get("created_at") or "")
        decided = str(row.get("decided_at") or "")
        if not created or not decided:
            continue
        try:
            start = datetime.fromisoformat(created)
            end = datetime.fromisoformat(decided)
        except ValueError:
            continue
        delta = (end - start).total_seconds()
        if delta >= 0:
            durations.append(delta)
    if not durations:
        return None
    return round(sum(durations) / len(durations))


def compute_hitl_stats(
    pending: Iterable[dict[str, Any]],
    history: Iterable[dict[str, Any]],
    *,
    tenant_id: str,
) -> dict[str, Any]:
    """Derive approval statistics from already-scoped pending/history rows."""
    pending_list = list(pending)
    history_list = list(history)
    approved = sum(1 for row in history_list if str(row.get("status", "")).lower() in ("approved", "approve"))
    rejected = sum(1 for row in history_list if str(row.get("status", "")).lower() in ("rejected", "reject"))
    total_resolved = approved + rejected
    approval_rate = round((approved / total_resolved) * 100, 1) if total_resolved else None
    avg_seconds = _avg_resolution_seconds(history_list)
    return {
        "connected": True,
        "tenant_id": tenant_id,
        "pending_count": len(pending_list),
        "history_count": len(history_list),
        "approved_count": approved,
        "rejected_count": rejected,
        "resolved_count": total_resolved,
        "approval_rate_percent": approval_rate,
        "avg_resolution_seconds": avg_seconds,
    }
