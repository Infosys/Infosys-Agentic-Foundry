"""Deterministic, read-only verification of isolated enterprise restore roots."""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from time import monotonic
from typing import Any
from urllib.parse import urlsplit, urlunsplit

import yaml

from shared.file_utils import atomic_write_json, atomic_write_text


MANIFEST_FILENAME = ".agentpro-recovery-manifest.json"
REPORT_SCHEMA = "agentpro.recovery_report.v1"
MANIFEST_SCHEMA = "agentpro.recovery_manifest.v1"
DRILL_EVIDENCE_SCHEMA = "agentpro.recovery_drill_evidence.v1"
_SECRET_KEY_RE = re.compile(
    r"(token|secret|password|credential|authorization|api[_-]?key|signature|redis[_-]?url|database[_-]?url)",
    re.IGNORECASE,
)
_SAFE_ID_RE = re.compile(r"^[A-Za-z0-9_.:-]{1,128}$")


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat()


def _parse_time(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return None


def _safe_float(value: Any) -> float | None:
    try:
        if value is None or value == "":
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        if value is None or value == "":
            return default
        return int(value)
    except (TypeError, ValueError):
        return default


def _redact_url(value: str) -> str:
    try:
        parsed = urlsplit(value)
    except ValueError:
        return value
    if parsed.scheme not in {"http", "https", "redis", "rediss", "postgres", "postgresql"}:
        return value
    host = parsed.hostname or ""
    if not host:
        return value
    netloc = host
    if parsed.port:
        netloc = f"{netloc}:{parsed.port}"
    return urlunsplit((parsed.scheme, netloc, "", "", ""))


def _sanitize_value(key: str, value: Any) -> Any:
    if _SECRET_KEY_RE.search(key):
        return "[redacted]"
    if isinstance(value, dict):
        return {
            str(child_key)[:80]: _sanitize_value(str(child_key), child_value)
            for child_key, child_value in value.items()
        }
    if isinstance(value, list):
        return [_sanitize_value(key, item) for item in value[:100]]
    if isinstance(value, tuple):
        return [_sanitize_value(key, item) for item in value[:100]]
    if isinstance(value, str):
        text = value.strip()
        if "://" in text:
            text = _redact_url(text)
        return text[:1000]
    if isinstance(value, (int, float, bool)) or value is None:
        return value
    return str(value)[:1000]


def sanitize_drill_evidence(raw: dict[str, Any]) -> dict[str, Any]:
    """Return a bounded, secret-free drill evidence bundle."""
    if not isinstance(raw, dict):
        raise ValueError("Drill evidence must be a JSON object")
    sanitized = _sanitize_value("", raw)
    if not isinstance(sanitized, dict):
        raise ValueError("Drill evidence must sanitize to a JSON object")
    evidence_id = str(sanitized.get("evidence_id") or sanitized.get("drill_id") or "").strip()
    if not evidence_id or not _SAFE_ID_RE.match(evidence_id):
        evidence_id = f"drill_{_utc_now().strftime('%Y%m%dT%H%M%SZ')}_{uuid.uuid4().hex[:8]}"
    sanitized["schema_version"] = DRILL_EVIDENCE_SCHEMA
    sanitized["evidence_id"] = evidence_id
    sanitized.setdefault("collected_at", _iso(_utc_now()))
    return sanitized


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _overlaps(first: Path, second: Path) -> bool:
    return first == second or first in second.parents or second in first.parents


def _safe_restore_root(root: Path, active_data_root: Path) -> Path:
    resolved = root.expanduser().resolve()
    active = active_data_root.expanduser().resolve()
    if _overlaps(resolved, active):
        raise ValueError("Recovery verification root must not overlap the active DATA_ROOT")
    if not resolved.is_dir():
        raise ValueError("Recovery verification root does not exist or is not a directory")
    return resolved


def _category(relative_path: Path) -> str:
    parts = relative_path.parts
    lowered = relative_path.as_posix().lower()
    if "command_center" in lowered or "queue" in parts:
        return "queue"
    if "workstreams" in parts or "workstream_runtime" in lowered:
        return "workstreams"
    if "approval" in lowered:
        return "approvals"
    if ".audit" in parts or "audit" in lowered:
        return "audit"
    if any(part.startswith("history") for part in parts) or "conversation" in lowered:
        return "conversations"
    if "security" in parts or "config" in parts:
        return "configuration"
    if "automations" in parts or "scheduler" in parts:
        return "operations"
    if "memory" in parts or "knowledge" in parts:
        return "knowledge_memory"
    if "evals" in parts or "golden_sets" in parts or "eval_evaluators" in parts:
        return "learning"
    if relative_path.suffix == ".db" or "databases" in parts:
        return "runtime_state"
    return "other"


def _recovery_class(relative_path: Path) -> str:
    if relative_path.name == "knowledge_index.db":
        return "rebuildable"
    if any(part in {"tmp", "temp", "cache", "__pycache__", "demo"} for part in relative_path.parts):
        return "optional"
    return "authoritative"


def build_manifest(
    root: Path,
    tenant_id: str,
    redis_snapshot: Path | None = None,
) -> dict[str, Any]:
    """Build a deterministic checksum inventory for a static recovery root."""
    tenant_root = root / "tenants" / tenant_id
    if not tenant_root.is_dir():
        raise ValueError(f"Restored tenant '{tenant_id}' was not found")

    files: list[dict[str, Any]] = []
    latest_mtime = 0.0
    latest_by_category: dict[str, float] = {}
    total_bytes = 0
    for path in sorted(tenant_root.rglob("*")):
        if path.name == MANIFEST_FILENAME or not path.is_file():
            continue
        resolved = path.resolve()
        try:
            resolved.relative_to(root)
        except ValueError as exc:
            raise ValueError(f"Restored path escapes recovery root: {path}") from exc
        stat = path.stat()
        relative = path.relative_to(root)
        category = _category(relative)
        latest_mtime = max(latest_mtime, stat.st_mtime)
        latest_by_category[category] = max(
            latest_by_category.get(category, 0.0),
            stat.st_mtime,
        )
        total_bytes += stat.st_size
        files.append(
            {
                "path": relative.as_posix(),
                "size": stat.st_size,
                "sha256": _sha256(path),
                "category": category,
                "recovery_class": _recovery_class(relative),
                "modified_at": _iso(datetime.fromtimestamp(stat.st_mtime, timezone.utc)),
            }
        )

    databases: list[dict[str, Any]] = []
    for row in files:
        if not row["path"].endswith(".db"):
            continue
        path = root / row["path"]
        tables: list[str] = []
        status = "error"
        try:
            with sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=2) as connection:
                integrity = connection.execute("PRAGMA quick_check").fetchone()
                status = str(integrity[0] if integrity else "missing").lower()
                tables = [
                    table[0]
                    for table in connection.execute(
                        "SELECT name FROM sqlite_master "
                        "WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
                    )
                ]
        except Exception:
            pass
        databases.append({
            "path": row["path"],
            "recovery_class": row["recovery_class"],
            "quick_check": status,
            "expected_tables": tables,
        })

    redis_metadata: dict[str, Any] | None = None
    if redis_snapshot is not None:
        snapshot = redis_snapshot.expanduser().resolve()
        try:
            snapshot_relative = snapshot.relative_to(root)
        except ValueError as exc:
            raise ValueError("Redis snapshot must be inside the backup root") from exc
        if not snapshot.is_file():
            raise ValueError("Redis snapshot does not exist or is not a file")
        snapshot_stat = snapshot.stat()
        redis_metadata = {
            "path": snapshot_relative.as_posix(),
            "size": snapshot_stat.st_size,
            "sha256": _sha256(snapshot),
            "modified_at": _iso(
                datetime.fromtimestamp(snapshot_stat.st_mtime, timezone.utc)
            ),
        }

    manifest = {
        "schema_version": MANIFEST_SCHEMA,
        "tenant_id": tenant_id,
        "captured_at": _iso(_utc_now()),
        "latest_data_timestamp": (
            _iso(datetime.fromtimestamp(latest_mtime, timezone.utc))
            if latest_mtime
            else None
        ),
        "latest_timestamps": {
            category: _iso(datetime.fromtimestamp(timestamp, timezone.utc))
            for category, timestamp in sorted(latest_by_category.items())
        },
        "file_count": len(files),
        "total_bytes": total_bytes,
        "required_paths": [
            f"tenants/{tenant_id}/security/policies.yaml",
            f"tenants/{tenant_id}/shared/Enterprise_Context.md",
            f"tenants/{tenant_id}/agents",
            f"tenants/{tenant_id}/shared/databases",
        ],
        "databases": databases,
        "redis_snapshot": redis_metadata,
        "files": files,
    }
    canonical = json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode()
    manifest["manifest_hash"] = hashlib.sha256(canonical).hexdigest()
    return manifest


def write_manifest(root: Path, manifest: dict[str, Any]) -> Path:
    path = root / MANIFEST_FILENAME
    atomic_write_json(path, manifest)
    return path


def _check(
    checks: list[dict[str, Any]],
    check_id: str,
    label: str,
    status: str,
    message: str,
    **evidence: Any,
) -> None:
    checks.append(
        {
            "id": check_id,
            "label": label,
            "status": status,
            "message": message,
            "evidence": evidence,
        }
    )


def _verify_structured_files(
    tenant_root: Path,
    checks: list[dict[str, Any]],
) -> None:
    errors: list[str] = []
    counts = {"yaml": 0, "json": 0, "jsonl": 0}
    for path in sorted(tenant_root.rglob("*")):
        if not path.is_file():
            continue
        try:
            if path.suffix in {".yaml", ".yml"}:
                yaml.safe_load(path.read_text(encoding="utf-8"))
                counts["yaml"] += 1
            elif path.suffix == ".json":
                json.loads(path.read_text(encoding="utf-8"))
                counts["json"] += 1
            elif path.suffix == ".jsonl":
                for line_number, line in enumerate(
                    path.read_text(encoding="utf-8").splitlines(),
                    start=1,
                ):
                    if line.strip():
                        json.loads(line)
                counts["jsonl"] += 1
        except Exception as exc:
            errors.append(f"{path.relative_to(tenant_root)}: {exc}")
    _check(
        checks,
        "structured_files",
        "YAML, JSON and JSONL integrity",
        "fail" if errors else "pass",
        f"{len(errors)} invalid structured file(s)" if errors else "Structured files parse cleanly",
        counts=counts,
        errors=errors[:50],
    )


def _verify_sqlite(
    tenant_root: Path,
    checks: list[dict[str, Any]],
    expected_manifest: dict[str, Any] | None,
) -> None:
    results: list[dict[str, Any]] = []
    failures: list[str] = []
    rebuildable_warnings: list[str] = []
    expected_databases = {
        row.get("path"): row
        for row in (expected_manifest or {}).get("databases", [])
        if row.get("path")
    }
    for path in sorted(tenant_root.rglob("*.db")):
        relative = path.relative_to(tenant_root).as_posix()
        rebuildable = path.name == "knowledge_index.db"
        try:
            with sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=2) as connection:
                integrity = connection.execute("PRAGMA quick_check").fetchone()
                tables = [
                    row[0]
                    for row in connection.execute(
                        "SELECT name FROM sqlite_master "
                        "WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
                    )
                ]
            status = str(integrity[0] if integrity else "missing").lower()
            manifest_path = (
                Path("tenants") / tenant_root.name / Path(relative)
            ).as_posix()
            expected_tables = set(
                expected_databases.get(manifest_path, {}).get("expected_tables", [])
            )
            missing_tables = sorted(expected_tables - set(tables))
            results.append({
                "path": relative,
                "quick_check": status,
                "tables": tables,
                "rebuildable": rebuildable,
                "missing_expected_tables": missing_tables,
            })
            if status != "ok" or missing_tables:
                target = rebuildable_warnings if rebuildable else failures
                detail = status
                if missing_tables:
                    detail += f"; missing tables {', '.join(missing_tables)}"
                target.append(f"{relative}: {detail}")
        except Exception as exc:
            target = rebuildable_warnings if rebuildable else failures
            target.append(f"{relative}: {exc}")
            results.append({
                "path": relative,
                "quick_check": "error",
                "tables": [],
                "rebuildable": rebuildable,
            })
    _check(
        checks,
        "sqlite_integrity",
        "SQLite database integrity",
        "fail" if failures else ("warning" if rebuildable_warnings or not results else "pass"),
        (
            f"{len(failures)} database(s) failed integrity checks"
            if failures
            else f"{len(rebuildable_warnings)} rebuildable index database(s) need reindexing"
            if rebuildable_warnings
            else f"{len(results)} database(s) passed"
            if results
            else "No SQLite databases were found"
        ),
        databases=results,
        errors=failures[:50],
        rebuildable_warnings=rebuildable_warnings[:50],
    )


def _verify_queue_duplicates(tenant_root: Path, checks: list[dict[str, Any]]) -> None:
    database = tenant_root / "shared" / "databases" / "command_center.db"
    if not database.exists():
        _check(
            checks,
            "queue_duplicate_history",
            "Queue duplicate execution history",
            "warning",
            "command_center.db was not found",
        )
        return
    try:
        with sqlite3.connect(f"file:{database}?mode=ro", uri=True, timeout=2) as connection:
            table = connection.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='job_executions'"
            ).fetchone()
            if table is None:
                _check(
                    checks,
                    "queue_duplicate_history",
                    "Queue duplicate execution history",
                    "warning",
                    "job_executions table was not found",
                )
                return
            duplicates = [
                {"queue_item_id": row[0], "completed_executions": row[1]}
                for row in connection.execute(
                    "SELECT queue_item_id, COUNT(*) FROM job_executions "
                    "WHERE status='completed' GROUP BY queue_item_id HAVING COUNT(*) > 1 "
                    "ORDER BY COUNT(*) DESC, queue_item_id"
                )
            ]
        _check(
            checks,
            "queue_duplicate_history",
            "Queue duplicate execution history",
            "fail" if duplicates else "pass",
            (
                f"{len(duplicates)} queue item(s) have multiple completed executions"
                if duplicates
                else "No duplicate completed queue executions were found"
            ),
            duplicates=duplicates[:100],
        )
    except Exception as exc:
        _check(
            checks,
            "queue_duplicate_history",
            "Queue duplicate execution history",
            "fail",
            f"Queue history could not be inspected: {exc}",
        )


def _compare_expected_manifest(
    root: Path,
    current: dict[str, Any],
    checks: list[dict[str, Any]],
) -> dict[str, Any] | None:
    path = root / MANIFEST_FILENAME
    if not path.exists():
        _check(
            checks,
            "backup_manifest",
            "Backup manifest comparison",
            "warning",
            f"{MANIFEST_FILENAME} is absent; checksums cannot be compared to capture time",
        )
        return None
    try:
        expected = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        _check(
            checks,
            "backup_manifest",
            "Backup manifest comparison",
            "fail",
            f"Backup manifest is invalid: {exc}",
        )
        return None

    expected_files = {row["path"]: row for row in expected.get("files", [])}
    current_files = {row["path"]: row for row in current.get("files", [])}
    missing = sorted(set(expected_files) - set(current_files))
    changed = sorted(
        path
        for path in set(expected_files).intersection(current_files)
        if expected_files[path].get("sha256") != current_files[path].get("sha256")
    )
    unexpected = sorted(set(current_files) - set(expected_files))
    status = "fail" if missing or changed else ("warning" if unexpected else "pass")
    _check(
        checks,
        "backup_manifest",
        "Backup manifest comparison",
        status,
        (
            f"{len(missing)} missing, {len(changed)} changed, "
            f"{len(unexpected)} unexpected file(s)"
        ),
        missing=missing[:100],
        changed=changed[:100],
        unexpected=unexpected[:100],
    )
    return expected


def _verify_redis_snapshot(
    root: Path,
    expected_manifest: dict[str, Any] | None,
    checks: list[dict[str, Any]],
    runtime_rpo_target_minutes: int,
    verification_started: datetime,
) -> float | None:
    metadata = (expected_manifest or {}).get("redis_snapshot")
    if not metadata:
        _check(
            checks,
            "redis_snapshot",
            "Redis recovery snapshot",
            "warning",
            "No Redis snapshot metadata was captured in the backup manifest",
        )
        return None
    relative = Path(str(metadata.get("path", "")))
    snapshot = (root / relative).resolve()
    try:
        snapshot.relative_to(root)
    except ValueError:
        _check(
            checks,
            "redis_snapshot",
            "Redis recovery snapshot",
            "fail",
            "Redis snapshot path escapes the recovery root",
        )
        return None
    if not snapshot.is_file():
        _check(
            checks,
            "redis_snapshot",
            "Redis recovery snapshot",
            "fail",
            "Captured Redis snapshot is missing from the restored root",
        )
        return None
    checksum_matches = _sha256(snapshot) == metadata.get("sha256")
    modified_at = _parse_time(metadata.get("modified_at"))
    runtime_rpo = (
        max(0.0, (verification_started - modified_at).total_seconds() / 60)
        if modified_at
        else None
    )
    status = (
        "fail"
        if not checksum_matches
        else "pass"
        if runtime_rpo is not None and runtime_rpo <= runtime_rpo_target_minutes
        else "fail"
        if runtime_rpo is not None
        else "warning"
    )
    _check(
        checks,
        "redis_snapshot",
        "Redis recovery snapshot",
        status,
        (
            f"Snapshot checksum matches; age is {runtime_rpo:.1f} minutes"
            if checksum_matches and runtime_rpo is not None
            else "Redis snapshot checksum does not match the backup manifest"
            if not checksum_matches
            else "Redis snapshot timestamp is unavailable"
        ),
        checksum_matches=checksum_matches,
        measured_minutes=runtime_rpo,
        target_minutes=runtime_rpo_target_minutes,
    )
    return runtime_rpo


def report_markdown(report: dict[str, Any]) -> str:
    """Render the compact human-readable companion to a JSON recovery report."""
    summary = report["summary"]
    measurements = report["measurements"]
    targets = report["targets"]
    lines = [
        f"# Recovery Report {report['report_id']}",
        "",
        f"- Status: **{report['status']}**",
        f"- Tenant: `{report['tenant_id']}`",
        f"- Recovery root: {report['root_label']} (`{report['root_id']}`)",
        f"- Triggered by: `{report['triggered_by']}`",
        f"- Started: {report['started_at']}",
        f"- Completed: {report['completed_at']}",
        f"- Duration: {report['duration_ms']} ms",
        (
            f"- Checks: {summary['passed']} passed, {summary['failed']} failed, "
            f"{summary['warnings']} warning/not-run"
        ),
        (
            f"- Runtime RPO: {measurements.get('runtime_rpo_minutes')} min "
            f"(target ≤ {targets.get('runtime_rpo_minutes')} min)"
        ),
        (
            f"- Tenant RPO: {measurements['tenant_rpo_minutes']} min "
            f"(target ≤ {targets['tenant_rpo_minutes']} min)"
        ),
        (
            f"- Service RTO: {measurements['service_rto_minutes']} min "
            f"(target ≤ {targets['service_rto_minutes']} min)"
        ),
        "",
        "## Checks",
        "",
    ]
    for check in report["checks"]:
        lines.extend(
            [
                f"### {check['label']}",
                f"- Status: **{check['status']}**",
                f"- {check['message']}",
                "",
            ]
        )
    if report.get("recommended_remediation"):
        lines.extend(["## Recommended remediation", ""])
        lines.extend(
            f"- `{item['check_id']}`: {item['recommendation']}"
            for item in report["recommended_remediation"]
        )
        lines.append("")
    return "\n".join(lines)


def _refresh_report_summary(report: dict[str, Any]) -> dict[str, Any]:
    checks = report.get("checks", [])
    failed = sum(row.get("status") == "fail" for row in checks)
    warnings = sum(row.get("status") in {"warning", "not_run"} for row in checks)
    passed = sum(row.get("status") == "pass" for row in checks)
    report["summary"] = {
        "passed": passed,
        "failed": failed,
        "warnings": warnings,
        "total": len(checks),
    }
    report["status"] = "fail" if failed else ("warning" if warnings else "pass")
    recommendations = {
        "required_assets": "Restore the missing authoritative tenant paths and rerun verification.",
        "backup_manifest": "Recreate the backup artifact or manifest; do not certify checksum drift.",
        "redis_snapshot": "Capture and restore a fresh isolated Redis snapshot, then rerun verification.",
        "structured_files": "Repair or restore each invalid YAML, JSON, or JSONL file.",
        "sqlite_integrity": "Restore authoritative databases; rebuild only entries marked rebuildable.",
        "queue_duplicate_history": "Investigate repeated completed executions before resuming the queue.",
        "tenant_rpo": "Increase backup frequency or reduce backup-to-restore delay.",
        "runtime_api": "Restore recovery-cell API dependencies and readiness before continuing.",
        "runtime_auth": "Validate the recovery token, identity provider, tenant binding, and policies.",
        "runtime_data_read": "Restore unreadable tenant datasets and re-run the live probes.",
        "signed_files": "Validate signing secrets, file entitlements, and restored shared files.",
        "scheduler_leader": "Archive both scheduler candidate logs proving exactly one active leader.",
        "queue_resume": "Run a drill-prefixed queue canary and archive exactly-once execution evidence.",
        "service_rto": "Automate or parallelize restore steps until the RTO target is met.",
        "load_failover_slo": "Reduce latency/error rate or improve failover recovery before certifying the SLO.",
    }
    report["recommended_remediation"] = [
        {
            "check_id": row.get("id"),
            "recommendation": recommendations.get(
                row.get("id"),
                "Review this check and attach recovery evidence before certification.",
            ),
        }
        for row in checks
        if row.get("status") in {"fail", "warning", "not_run"}
    ]
    return report


def _drill_evidence_checks(
    evidence: dict[str, Any],
    *,
    targets: dict[str, Any] | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    targets = targets or {}
    checks: list[dict[str, Any]] = []
    measurements: dict[str, Any] = {}

    scheduler = evidence.get("scheduler_leader")
    if isinstance(scheduler, dict):
        active_leaders = _safe_int(scheduler.get("active_leaders"), -1)
        candidates = _safe_int(scheduler.get("candidates_observed"), 0)
        if active_leaders == 1:
            status = "pass"
            message = "Drill evidence shows exactly one active scheduler leader"
        elif active_leaders >= 0:
            status = "fail"
            message = f"Drill evidence shows {active_leaders} active scheduler leaders"
        else:
            status = "warning"
            message = "Scheduler drill evidence did not include active_leaders"
        _check(
            checks,
            "scheduler_leader",
            "Single scheduler leader after restore",
            status,
            message,
            active_leaders=active_leaders if active_leaders >= 0 else None,
            candidates_observed=candidates,
            leader_ids=scheduler.get("leader_ids", []),
            evidence_id=evidence["evidence_id"],
        )

    queue = evidence.get("queue_resume")
    if isinstance(queue, dict):
        expected = _safe_int(queue.get("expected_items") or queue.get("count"), 0)
        terminal = _safe_int(queue.get("terminal_items"), 0)
        observed = _safe_int(queue.get("observed_items"), 0)
        duplicates = _safe_int(queue.get("duplicate_completed_items"), 0)
        duplicate_ids = queue.get("duplicate_item_ids") if isinstance(queue.get("duplicate_item_ids"), list) else []
        stale_claims = _safe_int(queue.get("stale_claims"), 0)
        processor_online = bool(queue.get("processor_online", True))
        workers_online = _safe_int(queue.get("workers_online"), 0)
        if duplicates > 0 or stale_claims > 0:
            status = "fail"
            message = (
                f"Queue drill found {duplicates} duplicate completed item(s) "
                f"and {stale_claims} stale claim(s)"
            )
        elif expected > 0 and terminal >= expected:
            status = "pass"
            message = f"Queue drill completed {terminal}/{expected} canary item(s) without duplicates"
        elif expected > 0:
            status = "fail"
            message = f"Queue drill only reached {terminal}/{expected} terminal canary item(s)"
        else:
            status = "warning"
            message = "Queue drill evidence did not include expected canary counts"
        _check(
            checks,
            "queue_resume",
            "Queue resumes without duplicate processing",
            status,
            message,
            run_id=queue.get("run_id"),
            expected_items=expected,
            observed_items=observed,
            terminal_items=terminal,
            duplicate_completed_items=duplicates,
            duplicate_item_ids=duplicate_ids[:100],
            stale_claims=stale_claims,
            processor_online=processor_online,
            workers_online=workers_online,
            evidence_id=evidence["evidence_id"],
        )

    signed_files = evidence.get("signed_files")
    if isinstance(signed_files, dict):
        serve_status = _safe_int(
            signed_files.get("serve_status")
            or signed_files.get("signed_file_status")
            or signed_files.get("http_status"),
            0,
        )
        list_status = _safe_int(signed_files.get("list_status"), 0)
        status = "pass" if serve_status == 200 else ("fail" if serve_status else "warning")
        _check(
            checks,
            "signed_files",
            "Signed file and evidence rendering",
            status,
            (
                f"Drill signed-file probe returned HTTP {serve_status}"
                if serve_status
                else "Signed-file drill evidence did not include a file fetch status"
            ),
            list_status=list_status or None,
            serve_status=serve_status or None,
            evidence_id=evidence["evidence_id"],
        )

    slo = evidence.get("slo") or evidence.get("slo_measurements")
    if isinstance(slo, dict):
        service_rto = _safe_float(slo.get("service_rto_minutes"))
        if service_rto is not None:
            target = float(targets.get("service_rto_minutes") or slo.get("service_rto_target_minutes") or 240)
            measurements["service_rto_minutes"] = service_rto
            _check(
                checks,
                "service_rto",
                "Service recovery RTO",
                "pass" if service_rto <= target else "fail",
                f"Drill measured service RTO at {service_rto:.1f} minutes",
                measured_minutes=service_rto,
                target_minutes=target,
                evidence_id=evidence["evidence_id"],
            )
        load_p95 = _safe_float(slo.get("load_p95_ms"))
        failover_seconds = _safe_float(slo.get("failover_recovery_seconds"))
        error_rate = _safe_float(slo.get("error_rate"))
        if load_p95 is not None:
            measurements["load_p95_ms"] = load_p95
        if failover_seconds is not None:
            measurements["failover_recovery_seconds"] = failover_seconds
        if error_rate is not None:
            measurements["load_error_rate"] = error_rate
        if load_p95 is not None or failover_seconds is not None or error_rate is not None:
            p95_target = float(slo.get("load_p95_target_ms") or 15000)
            failover_target = float(slo.get("failover_recovery_target_seconds") or 120)
            error_target = float(slo.get("error_rate_target") or 0.01)
            failures = []
            if load_p95 is not None and load_p95 > p95_target:
                failures.append("load p95")
            if failover_seconds is not None and failover_seconds > failover_target:
                failures.append("failover recovery")
            if error_rate is not None and error_rate > error_target:
                failures.append("error rate")
            _check(
                checks,
                "load_failover_slo",
                "Load and failover SLO evidence",
                "fail" if failures else "pass",
                (
                    f"Drill exceeded target(s): {', '.join(failures)}"
                    if failures
                    else "Drill load/failover measurements are within targets"
                ),
                load_p95_ms=load_p95,
                load_p95_target_ms=p95_target,
                failover_recovery_seconds=failover_seconds,
                failover_recovery_target_seconds=failover_target,
                error_rate=error_rate,
                error_rate_target=error_target,
                evidence_id=evidence["evidence_id"],
            )
    return checks, measurements


def merge_drill_evidence(report: dict[str, Any], drill_evidence: dict[str, Any]) -> dict[str, Any]:
    """Attach sanitized drill evidence and promote matching checks to pass/fail."""
    evidence = sanitize_drill_evidence(drill_evidence)
    checks, measurements = _drill_evidence_checks(evidence, targets=report.get("targets", {}))
    replacements = {row["id"]: row for row in checks}
    merged = [replacements.pop(row["id"], row) for row in report.get("checks", [])]
    merged.extend(replacements.values())
    report["checks"] = merged
    report.setdefault("measurements", {}).update(measurements)
    report["drill_evidence"] = {
        "evidence_id": evidence["evidence_id"],
        "schema_version": evidence["schema_version"],
        "collected_at": evidence.get("collected_at"),
        "submitted_at": evidence.get("submitted_at"),
        "check_count": len(checks),
        "evidence": evidence,
    }
    return _refresh_report_summary(report)


def merge_live_probe_results(
    report: dict[str, Any],
    live_checks: list[dict[str, Any]],
) -> dict[str, Any]:
    """Replace offline not-run checks with redacted live-cell probe evidence."""
    replacements = {row["id"]: row for row in live_checks}
    merged = [
        replacements.pop(row["id"], row)
        for row in report.get("checks", [])
    ]
    merged.extend(replacements.values())
    report["checks"] = merged
    report["live_probe"] = {
        "performed": True,
        "check_count": len(live_checks),
    }
    completed = _utc_now()
    started = _parse_time(report.get("started_at"))
    previous_completed = _parse_time(report.get("completed_at"))
    report["completed_at"] = _iso(completed)
    if started:
        report["duration_ms"] = int((completed - started).total_seconds() * 1000)
    measured_rto = report.get("measurements", {}).get("service_rto_minutes")
    if measured_rto is not None and previous_completed is not None:
        measured_rto = float(measured_rto) + max(
            0.0,
            (completed - previous_completed).total_seconds() / 60,
        )
        report["measurements"]["service_rto_minutes"] = measured_rto
        target = float(report.get("targets", {}).get("service_rto_minutes", 0))
        for check in report["checks"]:
            if check.get("id") == "service_rto":
                check["status"] = "pass" if measured_rto <= target else "fail"
                check["message"] = f"Recovery elapsed time is {measured_rto:.1f} minutes"
                check["evidence"] = {
                    "measured_minutes": measured_rto,
                    "target_minutes": target,
                }
                break
    return _refresh_report_summary(report)


def persist_report(reports_dir: Path, report: dict[str, Any]) -> None:
    reports_dir.mkdir(parents=True, exist_ok=True)
    report_id = report["report_id"]
    atomic_write_json(reports_dir / f"{report_id}.json", report)
    atomic_write_text(
        reports_dir / f"{report_id}.md",
        report_markdown(report),
    )


def verify_restore(
    *,
    restore_root: Path,
    active_data_root: Path,
    tenant_id: str,
    root_id: str = "cli",
    root_label: str = "CLI restore root",
    triggered_by: str = "operator",
    reports_dir: Path | None = None,
    runtime_rpo_target_minutes: int = 15,
    rpo_target_minutes: int = 60,
    rto_target_minutes: int = 240,
) -> dict[str, Any]:
    """Verify a restored tenant tree and optionally persist the resulting report."""
    started = _utc_now()
    timer = monotonic()
    root = _safe_restore_root(restore_root, active_data_root)
    tenant_root = root / "tenants" / tenant_id
    checks: list[dict[str, Any]] = []

    required = {
        "tenant_root": tenant_root,
        "security_policies": tenant_root / "security" / "policies.yaml",
        "shared_context": tenant_root / "shared" / "Enterprise_Context.md",
        "agents": tenant_root / "agents",
        "runtime_databases": tenant_root / "shared" / "databases",
    }
    missing_required = [
        key for key, path in required.items() if not path.exists()
    ]
    _check(
        checks,
        "required_assets",
        "Required tenant assets",
        "fail" if missing_required else "pass",
        (
            f"Missing required assets: {', '.join(missing_required)}"
            if missing_required
            else "Required tenant assets are present"
        ),
        missing=missing_required,
    )

    current_manifest = build_manifest(root, tenant_id)
    expected_manifest = _compare_expected_manifest(root, current_manifest, checks)
    runtime_rpo_minutes = _verify_redis_snapshot(
        root,
        expected_manifest,
        checks,
        runtime_rpo_target_minutes,
        started,
    )
    _verify_structured_files(tenant_root, checks)
    _verify_sqlite(tenant_root, checks, expected_manifest)
    _verify_queue_duplicates(tenant_root, checks)

    operational_counts = {
        name: len(list((tenant_root / name).glob("*.yaml")))
        if (tenant_root / name).exists()
        else 0
        for name in ("workstreams", "automations")
    }
    operational_counts["scheduler_jobs"] = (
        len(list((tenant_root / "scheduler" / "jobs").glob("*.yaml")))
        if (tenant_root / "scheduler" / "jobs").exists()
        else 0
    )
    _check(
        checks,
        "operational_definitions",
        "Workstream, automation and scheduler definitions",
        "pass" if any(operational_counts.values()) else "warning",
        "Operational definitions inventoried",
        counts=operational_counts,
    )

    captured_at = _parse_time(
        (expected_manifest or {}).get("captured_at")
        or current_manifest.get("latest_data_timestamp")
    )
    rpo_minutes = (
        max(0.0, (started - captured_at).total_seconds() / 60)
        if captured_at
        else None
    )
    _check(
        checks,
        "tenant_rpo",
        "Tenant data RPO",
        (
            "pass"
            if rpo_minutes is not None and rpo_minutes <= rpo_target_minutes
            else "fail"
            if rpo_minutes is not None
            else "warning"
        ),
        (
            f"Recovered data age is {rpo_minutes:.1f} minutes"
            if rpo_minutes is not None
            else "No capture timestamp is available"
        ),
        measured_minutes=rpo_minutes,
        target_minutes=rpo_target_minutes,
    )

    for check_id, label in (
        ("runtime_auth", "Login and tenant authorization"),
        ("scheduler_leader", "Single scheduler leader after restore"),
        ("queue_resume", "Queue resumes without duplicate processing"),
        ("signed_files", "Signed file and evidence rendering"),
    ):
        _check(
            checks,
            check_id,
            label,
            "not_run",
            "Requires the optional isolated live recovery-cell drill",
        )

    completed = _utc_now()
    duration_ms = int((monotonic() - timer) * 1000)
    restore_started = _parse_time((expected_manifest or {}).get("restore_started_at"))
    rto_minutes = (
        max(0.0, (completed - restore_started).total_seconds() / 60)
        if restore_started
        else None
    )
    _check(
        checks,
        "service_rto",
        "Service recovery RTO",
        (
            "pass"
            if rto_minutes is not None and rto_minutes <= rto_target_minutes
            else "fail"
            if rto_minutes is not None
            else "not_run"
        ),
        (
            f"Recovery elapsed time is {rto_minutes:.1f} minutes"
            if rto_minutes is not None
            else "Add restore_started_at to the backup manifest for RTO measurement"
        ),
        measured_minutes=rto_minutes,
        target_minutes=rto_target_minutes,
    )

    failed = sum(row["status"] == "fail" for row in checks)
    warnings = sum(row["status"] in {"warning", "not_run"} for row in checks)
    passed = sum(row["status"] == "pass" for row in checks)
    status = "fail" if failed else ("warning" if warnings else "pass")
    report_id = f"recovery_{started.strftime('%Y%m%dT%H%M%SZ')}_{uuid.uuid4().hex[:8]}"
    report = {
        "schema_version": REPORT_SCHEMA,
        "report_id": report_id,
        "tenant_id": tenant_id,
        "root_id": root_id,
        "root_label": root_label,
        "triggered_by": triggered_by,
        "started_at": _iso(started),
        "completed_at": _iso(completed),
        "duration_ms": duration_ms,
        "status": status,
        "summary": {
            "passed": passed,
            "failed": failed,
            "warnings": warnings,
            "total": len(checks),
        },
        "targets": {
            "runtime_rpo_minutes": runtime_rpo_target_minutes,
            "tenant_rpo_minutes": rpo_target_minutes,
            "service_rto_minutes": rto_target_minutes,
        },
        "measurements": {
            "runtime_rpo_minutes": runtime_rpo_minutes,
            "tenant_rpo_minutes": rpo_minutes,
            "service_rto_minutes": rto_minutes,
        },
        "inventory": {
            "file_count": current_manifest["file_count"],
            "total_bytes": current_manifest["total_bytes"],
            "latest_data_timestamp": current_manifest["latest_data_timestamp"],
            "manifest_hash": current_manifest["manifest_hash"],
        },
        "checks": checks,
    }
    _refresh_report_summary(report)
    if reports_dir is not None:
        persist_report(reports_dir, report)
    return report


def list_reports(reports_dir: Path, limit: int = 50) -> list[dict[str, Any]]:
    if not reports_dir.exists():
        return []
    reports: list[dict[str, Any]] = []
    for path in sorted(reports_dir.glob("recovery_*.json"), reverse=True):
        try:
            report = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        reports.append({key: report.get(key) for key in (
            "report_id",
            "tenant_id",
            "root_id",
            "root_label",
            "triggered_by",
            "started_at",
            "completed_at",
            "duration_ms",
            "status",
            "summary",
            "targets",
            "measurements",
            "inventory",
            "drill_evidence",
        )})
        if len(reports) >= max(1, min(limit, 200)):
            break
    return reports


def load_report(reports_dir: Path, report_id: str) -> dict[str, Any] | None:
    if not report_id.startswith("recovery_") or any(
        character not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-"
        for character in report_id
    ):
        return None
    path = reports_dir / f"{report_id}.json"
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
