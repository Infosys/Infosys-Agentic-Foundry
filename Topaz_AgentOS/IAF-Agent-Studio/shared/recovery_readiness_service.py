"""Configured recovery verification orchestration outside FastAPI routers."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from shared.config import (
    DATA_ROOT_PATH,
    RECOVERY_LIVE_BASE_URL,
    RECOVERY_LIVE_CONFIRMATION,
    RECOVERY_LIVE_TIMEOUT_SECONDS,
    RECOVERY_LIVE_TOKEN,
    RECOVERY_REDIS_URL,
    RECOVERY_RUNTIME_RPO_TARGET_MINUTES,
    RECOVERY_RPO_TARGET_MINUTES,
    RECOVERY_RTO_TARGET_MINUTES,
    RECOVERY_VERIFICATION_ROOT_PATH,
    REDIS_URL,
)
from shared.recovery_live_probe import ISOLATION_CONFIRMATION, run_live_probes
from shared.recovery_verifier import (
    list_reports,
    load_report,
    merge_drill_evidence,
    merge_live_probe_results,
    persist_report,
    sanitize_drill_evidence,
    verify_restore,
)
from shared.file_utils import atomic_write_json


CONFIGURED_ROOT_ID = "configured_restore"
CONFIGURED_ROOT_LABEL = "Configured recovery cell"


def reports_dir(tenant_id: str) -> Path:
    return (
        DATA_ROOT_PATH
        / "tenants"
        / tenant_id
        / "shared"
        / "databases"
        / "recovery_reports"
    )


def evidence_dir(tenant_id: str) -> Path:
    return reports_dir(tenant_id) / "drill_evidence"


def roots() -> list[dict[str, Any]]:
    configured = RECOVERY_VERIFICATION_ROOT_PATH
    if configured is None:
        return []
    resolved = configured.expanduser().resolve()
    active = DATA_ROOT_PATH.expanduser().resolve()
    overlaps = resolved == active or resolved in active.parents or active in resolved.parents
    return [
        {
            "id": CONFIGURED_ROOT_ID,
            "label": CONFIGURED_ROOT_LABEL,
            "description": "Server-configured isolated restore root",
            "available": resolved.is_dir() and not overlaps,
            "safety": "overlaps_active_data_root" if overlaps else "isolated",
        }
    ]


def summary(tenant_id: str) -> dict[str, Any]:
    recent = list_reports(reports_dir(tenant_id), limit=1)
    recent_evidence = list_drill_evidence(tenant_id, limit=1)
    return {
        "tenant_id": tenant_id,
        "configured": bool(RECOVERY_VERIFICATION_ROOT_PATH),
        "live_probe_configured": bool(
            RECOVERY_LIVE_BASE_URL
            and RECOVERY_REDIS_URL
            and REDIS_URL
            and RECOVERY_LIVE_CONFIRMATION == ISOLATION_CONFIRMATION
        ),
        "roots": roots(),
        "latest_report": recent[0] if recent else None,
        "latest_drill_evidence": recent_evidence[0] if recent_evidence else None,
        "targets": {
            "runtime_rpo_minutes": RECOVERY_RUNTIME_RPO_TARGET_MINUTES,
            "tenant_rpo_minutes": RECOVERY_RPO_TARGET_MINUTES,
            "service_rto_minutes": RECOVERY_RTO_TARGET_MINUTES,
        },
    }


def reports(tenant_id: str, limit: int = 50) -> list[dict[str, Any]]:
    return list_reports(reports_dir(tenant_id), limit=limit)


def report(tenant_id: str, report_id: str) -> dict[str, Any] | None:
    return load_report(reports_dir(tenant_id), report_id)


def _load_evidence_path(path: Path) -> dict[str, Any] | None:
    try:
        payload = sanitize_drill_evidence(json.loads(path.read_text(encoding="utf-8")))
    except Exception:
        return None
    return payload


def list_drill_evidence(tenant_id: str, limit: int = 50) -> list[dict[str, Any]]:
    directory = evidence_dir(tenant_id)
    if not directory.exists():
        return []
    rows: list[dict[str, Any]] = []
    for path in sorted(directory.glob("*.json"), reverse=True):
        payload = _load_evidence_path(path)
        if not payload:
            continue
        rows.append({
            "evidence_id": payload.get("evidence_id"),
            "schema_version": payload.get("schema_version"),
            "tenant_id": payload.get("tenant_id", tenant_id),
            "root_id": payload.get("root_id"),
            "collected_at": payload.get("collected_at"),
            "submitted_at": payload.get("submitted_at"),
            "summary": {
                "has_scheduler": isinstance(payload.get("scheduler_leader"), dict),
                "has_queue": isinstance(payload.get("queue_resume"), dict),
                "has_signed_files": isinstance(payload.get("signed_files"), dict),
                "has_slo": isinstance(payload.get("slo") or payload.get("slo_measurements"), dict),
            },
        })
        if len(rows) >= max(1, min(limit, 200)):
            break
    return rows


def get_drill_evidence(tenant_id: str, evidence_id: str) -> dict[str, Any] | None:
    if any(character not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_.:-" for character in evidence_id):
        return None
    path = evidence_dir(tenant_id) / f"{evidence_id}.json"
    if not path.exists():
        return None
    return _load_evidence_path(path)


def persist_drill_evidence(
    *,
    tenant_id: str,
    root_id: str,
    evidence: dict[str, Any],
    submitted_by: str,
) -> dict[str, Any]:
    payload = sanitize_drill_evidence({
        **evidence,
        "tenant_id": tenant_id,
        "root_id": root_id,
        "submitted_by": submitted_by,
    })
    from datetime import datetime, timezone

    payload["submitted_at"] = datetime.now(timezone.utc).isoformat()
    directory = evidence_dir(tenant_id)
    directory.mkdir(parents=True, exist_ok=True)
    atomic_write_json(directory / f"{payload['evidence_id']}.json", payload)
    return payload


def run_verification(
    *,
    tenant_id: str,
    root_id: str,
    triggered_by: str,
    evidence_id: str | None = None,
) -> dict[str, Any]:
    if root_id != CONFIGURED_ROOT_ID or RECOVERY_VERIFICATION_ROOT_PATH is None:
        raise ValueError("Unknown or unconfigured recovery root")
    report_result = verify_restore(
        restore_root=RECOVERY_VERIFICATION_ROOT_PATH,
        active_data_root=DATA_ROOT_PATH,
        tenant_id=tenant_id,
        root_id=root_id,
        root_label=CONFIGURED_ROOT_LABEL,
        triggered_by=triggered_by,
        reports_dir=None,
        runtime_rpo_target_minutes=RECOVERY_RUNTIME_RPO_TARGET_MINUTES,
        rpo_target_minutes=RECOVERY_RPO_TARGET_MINUTES,
        rto_target_minutes=RECOVERY_RTO_TARGET_MINUTES,
    )
    drill_evidence = get_drill_evidence(tenant_id, evidence_id) if evidence_id else None
    if evidence_id and drill_evidence is None:
        raise ValueError("Unknown recovery drill evidence id")
    if RECOVERY_LIVE_BASE_URL:
        live_checks = run_live_probes(
            base_url=RECOVERY_LIVE_BASE_URL,
            recovery_redis_url=RECOVERY_REDIS_URL,
            production_redis_url=REDIS_URL,
            confirmation=RECOVERY_LIVE_CONFIRMATION,
            tenant_id=tenant_id,
            token=RECOVERY_LIVE_TOKEN,
            timeout_seconds=RECOVERY_LIVE_TIMEOUT_SECONDS,
            drill_evidence=drill_evidence,
        )
        merge_live_probe_results(report_result, live_checks)
    if drill_evidence:
        merge_drill_evidence(report_result, drill_evidence)
    persist_report(reports_dir(tenant_id), report_result)
    return report_result
