"""Security audit events as structured log records, for export to a SIEM.

Audit decisions are still written to their local JSONL files as before. When
TELEMETRY_EXPORT_AUDIT is `denials` or `all`, each decision is ALSO emitted on the
`agentos.audit` logger, to which telemetry/otel_setup.py attaches an OpenTelemetry log
handler — so Splunk, Sentinel, Datadog etc. receive them as standard OTel log records.

The logger never propagates, so these records do not reach the console or app log, and
with export off nothing is attached and the call is a cheap no-op.
"""

from __future__ import annotations

import logging
import os
from typing import Any, Mapping

AUDIT_LOGGER = logging.getLogger("agentos.audit")
AUDIT_LOGGER.propagate = False
AUDIT_LOGGER.setLevel(logging.INFO)

_FIELDS = ("tenant_id", "user_id", "email", "agent_id", "skill", "action", "resource",
           "allowed", "reason", "matched_policy")


def export_mode() -> str:
    return os.getenv("TELEMETRY_EXPORT_AUDIT", "off").strip().lower()


def emit_audit(category: str, row: Mapping[str, Any]) -> None:
    """Emit one audit decision as a log record (no-op unless export is enabled)."""
    mode = export_mode()
    if mode not in ("denials", "all"):
        return
    allowed = row.get("allowed")
    if mode == "denials" and allowed is not False:
        return
    attrs: dict[str, Any] = {"agentos.audit.category": category}
    for key in _FIELDS:
        value = row.get(key)
        if isinstance(value, (str, bool, int, float)) and value != "":
            attrs[f"agentos.audit.{key}"] = value
    outcome = "denied" if allowed is False else "allowed"
    try:
        AUDIT_LOGGER.log(
            logging.WARNING if allowed is False else logging.INFO,
            "audit %s: %s %s %s", category, row.get("action", ""), row.get("resource", ""), outcome,
            extra=attrs,
        )
    except Exception:
        pass  # auditing to telemetry must never affect the decision path
