"""Audit and evidence sink fanout boundaries.

Local persistence remains the source of truth. Optional JSONL mirror sinks emit
bounded, redacted records that can be picked up by enterprise log forwarders.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

from shared.config import (
    TELEMETRY_EXPORT_AUDIT,
    AUDIT_EVIDENCE_MIRROR_DIR,
    AUDIT_EVIDENCE_MIRROR_ENABLED,
    AUDIT_EVIDENCE_PREVIEW_LIMIT,
    DATA_ROOT,
    SERVER_DIR,
    TENANT_ID,
)


_MAX_DEPTH = 5
_MAX_ITEMS = 50
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


@runtime_checkable
class AuditSink(Protocol):
    name: str

    def write(self, row: dict[str, Any], *, tenant_id: str, category: str) -> None:
        ...

    def health(self) -> dict[str, Any]:
        ...


@runtime_checkable
class EvidenceSink(Protocol):
    name: str

    def store_bundle(self, bundle: dict[str, Any], *, tenant_id: str) -> dict[str, Any]:
        ...

    def health(self) -> dict[str, Any]:
        ...


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _preview_limit() -> int:
    try:
        return max(64, min(int(AUDIT_EVIDENCE_PREVIEW_LIMIT), 8192))
    except Exception:
        return 1024


def _is_sensitive_key(key: str) -> bool:
    normalized = key.lower().replace("-", "_").replace(" ", "_")
    return any(part in normalized for part in _SENSITIVE_KEY_PARTS)


def _bound_text(value: str) -> str:
    text = str(value)
    text = re.sub(r"Bearer\s+[A-Za-z0-9._\-]+", "Bearer [REDACTED]", text, flags=re.IGNORECASE)
    text = re.sub(r"Basic\s+[A-Za-z0-9+/=]+", "Basic [REDACTED]", text, flags=re.IGNORECASE)
    text = re.sub(
        r"\b((?:client_secret|password|secret|token|api_key|apikey)\s*[:=]\s*)[^\s,;]+",
        r"\1[REDACTED]",
        text,
        flags=re.IGNORECASE,
    )
    text = re.sub(
        r"\b[A-Za-z0-9._\-]*(?:secret|token|password)[A-Za-z0-9._\-]*\b(?!\s*[:=])",
        "[REDACTED]",
        text,
        flags=re.IGNORECASE,
    )
    limit = _preview_limit()
    if len(text) > limit:
        return text[:limit]
    return text


def sanitize_for_sink(value: Any, *, key: str = "", depth: int = 0) -> Any:
    if key and _is_sensitive_key(key):
        return "[REDACTED]"
    if depth >= _MAX_DEPTH:
        return "[TRUNCATED]"
    if isinstance(value, dict):
        result: dict[str, Any] = {}
        for idx, (item_key, item_value) in enumerate(value.items()):
            if idx >= _MAX_ITEMS:
                result["_truncated"] = True
                break
            key_text = str(item_key)
            result[key_text] = sanitize_for_sink(item_value, key=key_text, depth=depth + 1)
        return result
    if isinstance(value, (list, tuple)):
        result = [sanitize_for_sink(item, depth=depth + 1) for item in list(value)[:_MAX_ITEMS]]
        if len(value) > _MAX_ITEMS:
            result.append("[TRUNCATED]")
        return result
    if isinstance(value, str):
        return _bound_text(value)
    if value is None or isinstance(value, (bool, int, float)):
        return value
    return _bound_text(str(value))


def _tenant_database_dir(tenant_id: str) -> Path:
    root = Path(DATA_ROOT)
    data_root = root if root.is_absolute() else (Path(SERVER_DIR) / root).resolve()
    path = data_root / "tenants" / (tenant_id or TENANT_ID) / "shared" / "databases"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _category_filename(category: str) -> str:
    if category == "entitlement_decision":
        return "entitlements_audit.jsonl"
    clean = re.sub(r"[^A-Za-z0-9_.-]+", "_", category or "audit")
    return f"{clean}.jsonl"


class LocalAuditJsonlSink:
    name = "local_jsonl_audit"

    def __init__(self) -> None:
        self.write_count = 0

    def write(self, row: dict[str, Any], *, tenant_id: str, category: str) -> None:
        audit_file = _tenant_database_dir(tenant_id) / _category_filename(category)
        with audit_file.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(sanitize_for_sink(row), ensure_ascii=True) + "\n")
        self.write_count += 1

    def health(self) -> dict[str, Any]:
        return {"name": self.name, "available": True, "write_count": self.write_count, "store": "jsonl"}


class JsonlMirrorAuditSink:
    name = "jsonl_mirror_audit"

    def __init__(self, mirror_dir: str | Path) -> None:
        self.mirror_dir = Path(mirror_dir)
        self.write_count = 0

    def write(self, row: dict[str, Any], *, tenant_id: str, category: str) -> None:
        tenant_dir = self.mirror_dir / (tenant_id or TENANT_ID)
        tenant_dir.mkdir(parents=True, exist_ok=True)
        event = {
            "timestamp": _now(),
            "category": category,
            "tenant_id": tenant_id or TENANT_ID,
            "row": sanitize_for_sink(row),
        }
        with (tenant_dir / "audit_events.jsonl").open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(event, ensure_ascii=True) + "\n")
        self.write_count += 1

    def health(self) -> dict[str, Any]:
        return {"name": self.name, "available": True, "write_count": self.write_count, "store": "jsonl_mirror"}


class OtelLogAuditSink:
    """Mirror audit decisions to OpenTelemetry log records (TELEMETRY_EXPORT_AUDIT)."""

    name = "otel_log_audit"

    def __init__(self) -> None:
        self.write_count = 0

    def write(self, row: dict[str, Any], *, tenant_id: str, category: str) -> None:
        from agent_os.audit_log import emit_audit

        emit_audit(category, {"tenant_id": tenant_id, **sanitize_for_sink(row)})
        self.write_count += 1

    def health(self) -> dict[str, Any]:
        from agent_os.audit_log import export_mode

        return {"name": self.name, "available": True, "write_count": self.write_count,
                "store": "otel_logs", "mode": export_mode()}


class AuditSinkFanout:
    def __init__(self, sinks: list[AuditSink]) -> None:
        self.sinks = sinks
        self.write_count = 0
        self.error_count = 0
        self.last_error_type = ""

    def write(self, row: dict[str, Any], *, tenant_id: str, category: str) -> None:
        self.write_count += 1
        for sink in self.sinks:
            try:
                sink.write(row, tenant_id=tenant_id, category=category)
            except Exception as exc:
                self.error_count += 1
                self.last_error_type = type(exc).__name__

    def health(self) -> dict[str, Any]:
        return {
            "mode": "fanout",
            "sink_count": len(self.sinks),
            "sinks": [sink.health() if hasattr(sink, "health") else {"name": type(sink).__name__} for sink in self.sinks],
            "write_count": self.write_count,
            "error_count": self.error_count,
            "degraded": self.error_count > 0,
            "last_error_type": self.last_error_type,
            "redaction": "bounded previews and sensitive keys are redacted",
        }


class LocalEvidenceSqliteSink:
    name = "local_sqlite_evidence"

    def __init__(self) -> None:
        self.store_count = 0

    def _with_store_config(self, func):
        from shared import evidence_store as store_mod

        old_values = (store_mod.SERVER_DIR, store_mod.DATA_ROOT, store_mod.TENANT_ID)
        try:
            store_mod.SERVER_DIR = Path(SERVER_DIR)
            store_mod.DATA_ROOT = DATA_ROOT
            store_mod.TENANT_ID = TENANT_ID
            return func(store_mod)
        finally:
            store_mod.SERVER_DIR, store_mod.DATA_ROOT, store_mod.TENANT_ID = old_values

    def store_bundle(self, bundle: dict[str, Any], *, tenant_id: str) -> dict[str, Any]:
        def _store(store_mod):
            return store_mod.EvidenceStore(tenant_id or str(bundle.get("tenant_id") or TENANT_ID)).store_bundle(bundle)

        result = self._with_store_config(_store)
        self.store_count += 1
        return result

    def fetch_bundle(self, trace_id: str, *, tenant_id: str = "") -> dict[str, Any] | None:
        return self._with_store_config(lambda store_mod: store_mod.EvidenceStore(tenant_id or TENANT_ID).get_bundle(trace_id))

    def fetch_item(self, trace_id: str, evidence_id: str, *, tenant_id: str = "") -> dict[str, Any] | None:
        return self._with_store_config(lambda store_mod: store_mod.EvidenceStore(tenant_id or TENANT_ID).get_item(trace_id, evidence_id))

    def fetch_blob(self, trace_id: str, evidence_id: str, *, tenant_id: str = "") -> tuple[bytes, str] | None:
        return self._with_store_config(lambda store_mod: store_mod.EvidenceStore(tenant_id or TENANT_ID).get_blob(trace_id, evidence_id))

    def health(self) -> dict[str, Any]:
        try:
            from shared.evidence_store import _resolve_evidence_backend
            store = _resolve_evidence_backend()
        except Exception:
            store = "sqlite"
        return {"name": self.name, "available": True, "store_count": self.store_count, "store": store}


def _evidence_item_count(bundle: dict[str, Any]) -> int:
    items = bundle.get("evidence_items") or []
    if items:
        return len(items)
    return len(bundle.get("documents") or [])


def _evidence_preview(bundle: dict[str, Any]) -> list[dict[str, Any]]:
    raw_items = bundle.get("evidence_items") or bundle.get("documents") or []
    previews = []
    for item in list(raw_items)[:10]:
        previews.append(
            sanitize_for_sink(
                {
                    "evidence_id": item.get("evidence_id") or item.get("doc_id"),
                    "source_uri": item.get("source_uri", ""),
                    "display_name": item.get("display_name", ""),
                    "mime_type": item.get("mime_type", ""),
                    "excerpt_preview": item.get("excerpt") or (item.get("extracted_text") or {}).get("excerpt", ""),
                    "metadata": item.get("metadata") or {},
                    "provenance": item.get("provenance") or {"reads": item.get("reads") or []},
                }
            )
        )
    return previews


class JsonlMirrorEvidenceSink:
    name = "jsonl_mirror_evidence"

    def __init__(self, mirror_dir: str | Path) -> None:
        self.mirror_dir = Path(mirror_dir)
        self.store_count = 0

    def store_bundle(self, bundle: dict[str, Any], *, tenant_id: str) -> dict[str, Any]:
        trace_id = str(bundle.get("trace_id") or "")
        item_count = _evidence_item_count(bundle)
        tenant = tenant_id or str(bundle.get("tenant_id") or TENANT_ID)
        tenant_dir = self.mirror_dir / tenant
        tenant_dir.mkdir(parents=True, exist_ok=True)
        event = sanitize_for_sink(
            {
                "timestamp": _now(),
                "category": "evidence_bundle",
                "trace_id": trace_id,
                "tenant_id": tenant,
                "agent_id": bundle.get("agent_id", ""),
                "user_id": bundle.get("user_id", ""),
                "execution_source": bundle.get("execution_source", ""),
                "schema_version": bundle.get("schema_version", ""),
                "source_documents_count": int(bundle.get("source_documents_count") or len(bundle.get("documents") or [])),
                "evidence_items_count": item_count,
                "evidence_items": _evidence_preview(bundle),
                "metadata": bundle.get("metadata") or {},
            }
        )
        with (tenant_dir / "evidence_events.jsonl").open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(event, ensure_ascii=True) + "\n")
        self.store_count += 1
        return {"trace_id": trace_id, "evidence_items_count": item_count}

    def health(self) -> dict[str, Any]:
        return {"name": self.name, "available": True, "store_count": self.store_count, "store": "jsonl_mirror"}


class EvidenceSinkFanout:
    def __init__(self, local_sink: LocalEvidenceSqliteSink, mirrors: list[EvidenceSink] | None = None) -> None:
        self.local_sink = local_sink
        self.mirrors = mirrors or []
        self.store_count = 0
        self.local_error_count = 0
        self.mirror_error_count = 0
        self.last_error_type = ""

    def store_bundle(self, bundle: dict[str, Any], *, tenant_id: str) -> dict[str, Any]:
        self.store_count += 1
        try:
            result = self.local_sink.store_bundle(bundle, tenant_id=tenant_id)
        except Exception as exc:
            self.local_error_count += 1
            self.last_error_type = type(exc).__name__
            raise
        for sink in self.mirrors:
            try:
                sink.store_bundle(bundle, tenant_id=tenant_id)
            except Exception as exc:
                self.mirror_error_count += 1
                self.last_error_type = type(exc).__name__
        return result

    def fetch_bundle(self, trace_id: str, *, tenant_id: str = "") -> dict[str, Any] | None:
        return self.local_sink.fetch_bundle(trace_id, tenant_id=tenant_id)

    def fetch_item(self, trace_id: str, evidence_id: str, *, tenant_id: str = "") -> dict[str, Any] | None:
        return self.local_sink.fetch_item(trace_id, evidence_id, tenant_id=tenant_id)

    def fetch_blob(self, trace_id: str, evidence_id: str, *, tenant_id: str = "") -> tuple[bytes, str] | None:
        return self.local_sink.fetch_blob(trace_id, evidence_id, tenant_id=tenant_id)

    def health(self) -> dict[str, Any]:
        return {
            "mode": "local_required_mirror_optional",
            "store_count": self.store_count,
            "local_error_count": self.local_error_count,
            "mirror_error_count": self.mirror_error_count,
            "degraded": self.local_error_count > 0 or self.mirror_error_count > 0,
            "last_error_type": self.last_error_type,
            "local": self.local_sink.health(),
            "mirrors": [sink.health() if hasattr(sink, "health") else {"name": type(sink).__name__} for sink in self.mirrors],
            "redaction": "mirrored evidence emits bounded summaries only; stored payloads stay local",
        }


_AUDIT_FANOUT: AuditSinkFanout | None = None
_EVIDENCE_FANOUT: EvidenceSinkFanout | None = None


def _mirror_sinks_enabled() -> bool:
    return bool(AUDIT_EVIDENCE_MIRROR_ENABLED and str(AUDIT_EVIDENCE_MIRROR_DIR or "").strip())


def get_audit_sink_fanout() -> AuditSinkFanout:
    global _AUDIT_FANOUT
    if _AUDIT_FANOUT is None:
        sinks: list[AuditSink] = [LocalAuditJsonlSink()]
        if _mirror_sinks_enabled():
            sinks.append(JsonlMirrorAuditSink(AUDIT_EVIDENCE_MIRROR_DIR))
        if TELEMETRY_EXPORT_AUDIT in ("denials", "all"):
            sinks.append(OtelLogAuditSink())
        _AUDIT_FANOUT = AuditSinkFanout(sinks)
    return _AUDIT_FANOUT


def get_evidence_sink_fanout() -> EvidenceSinkFanout:
    global _EVIDENCE_FANOUT
    if _EVIDENCE_FANOUT is None:
        mirrors: list[EvidenceSink] = []
        if _mirror_sinks_enabled():
            mirrors.append(JsonlMirrorEvidenceSink(AUDIT_EVIDENCE_MIRROR_DIR))
        _EVIDENCE_FANOUT = EvidenceSinkFanout(LocalEvidenceSqliteSink(), mirrors=mirrors)
    return _EVIDENCE_FANOUT


def reset_sink_fanouts_for_testing() -> None:
    global _AUDIT_FANOUT, _EVIDENCE_FANOUT
    _AUDIT_FANOUT = None
    _EVIDENCE_FANOUT = None


def set_audit_sink_fanout_for_testing(fanout: AuditSinkFanout) -> None:
    global _AUDIT_FANOUT
    _AUDIT_FANOUT = fanout


def set_evidence_sink_fanout_for_testing(fanout: EvidenceSinkFanout) -> None:
    global _EVIDENCE_FANOUT
    _EVIDENCE_FANOUT = fanout