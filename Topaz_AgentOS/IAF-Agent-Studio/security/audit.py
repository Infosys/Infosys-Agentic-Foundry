"""Lightweight entitlement decision audit sink."""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from typing import Any

from shared.config import DATA_ROOT, ENTITLEMENTS_AUDIT_ENABLED, SERVER_DIR
from shared import audit_evidence_sinks as _sink_mod

from .models import Decision, Principal, Resource


_MAX_CONTEXT_DEPTH = 4
_MAX_CONTEXT_ITEMS = 50
_MAX_CONTEXT_TEXT = 300
_SENSITIVE_KEY_PARTS = (
    "authorization",
    "bearer",
    "token",
    "password",
    "passwd",
    "passphrase",
    "secret",
    "api_key",
    "apikey",
    "access_key",
    "client_secret",
    "credential",
    # short / domain-specific variants found in pentest (e.g. imap_pass, db_pw)
    "_pass",
    "_pw",
    "_pin",
    "_auth",
    "auth_key",
    "private_key",
    "signing_key",
    "encryption_key",
)


def _is_sensitive_key(key: str) -> bool:
    normalized = key.lower().replace("-", "_").replace(" ", "_")
    return any(part in normalized for part in _SENSITIVE_KEY_PARTS)


def _bound_text(value: str) -> str:
    redacted = re.sub(r"Bearer\s+[A-Za-z0-9._\-]+", "Bearer [REDACTED]", value, flags=re.IGNORECASE)
    redacted = re.sub(r"Basic\s+[A-Za-z0-9+/=]+", "Basic [REDACTED]", redacted, flags=re.IGNORECASE)
    if len(redacted) > _MAX_CONTEXT_TEXT:
        return redacted[:_MAX_CONTEXT_TEXT]
    return redacted


def sanitize_policy_context(value: Any, *, key: str = "", depth: int = 0) -> Any:
    if key and _is_sensitive_key(key):
        return "[REDACTED]"
    if depth >= _MAX_CONTEXT_DEPTH:
        return "[TRUNCATED]"
    if isinstance(value, dict):
        sanitized: dict[str, Any] = {}
        for idx, (item_key, item_value) in enumerate(value.items()):
            if idx >= _MAX_CONTEXT_ITEMS:
                sanitized["_truncated"] = True
                break
            key_text = str(item_key)
            sanitized[key_text] = sanitize_policy_context(item_value, key=key_text, depth=depth + 1)
        return sanitized
    if isinstance(value, (list, tuple)):
        items = [sanitize_policy_context(item, depth=depth + 1) for item in list(value)[:_MAX_CONTEXT_ITEMS]]
        if len(value) > _MAX_CONTEXT_ITEMS:
            items.append("[TRUNCATED]")
        return items
    if isinstance(value, str):
        return _bound_text(value)
    if value is None or isinstance(value, (bool, int, float)):
        return value
    return _bound_text(str(value))


def audit_decision(
    principal: Principal,
    action: str,
    resource: Resource,
    decision: Decision,
    context: dict[str, Any] | None = None,
) -> None:
    if not ENTITLEMENTS_AUDIT_ENABLED:
        return
    try:
        row = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "tenant_id": principal.tenant_id,
            "user_id": principal.user_id,
            "email": principal.email,
            "roles": list(principal.roles),
            "groups": list(principal.groups),
            "action": action,
            "resource": resource.key,
            "allowed": decision.allowed,
            "reason": decision.reason,
            "matched_policy": decision.matched_policy,
            "context": sanitize_policy_context(context or {}),
        }
        if _sink_mod.SERVER_DIR != SERVER_DIR or _sink_mod.DATA_ROOT != DATA_ROOT:
            _sink_mod.SERVER_DIR = SERVER_DIR
            _sink_mod.DATA_ROOT = DATA_ROOT
            _sink_mod.reset_sink_fanouts_for_testing()
        _sink_mod.get_audit_sink_fanout().write(row, tenant_id=principal.tenant_id, category="entitlement_decision")
    except Exception:
        # Audit must never break user-facing execution.
        return
