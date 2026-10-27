"""Standalone cron declarations backed by enterprise_root YAML.

Workstream crons already live inside workstream YAML. This module gives
non-workstream cron jobs the same portability guarantee: the job definition is
business configuration under ``enterprise_root`` and Redis is only the runtime
scheduler cache.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any

import yaml

from shared.config import AGENT_ID, DATA_ROOT_PATH, TENANT_ID

logger = logging.getLogger(__name__)


def standalone_cron_dir(tenant_id: str = TENANT_ID) -> Path:
    """Return the tenant's standalone cron source-of-truth directory."""
    return DATA_ROOT_PATH / "tenants" / tenant_id / "scheduler" / "jobs"


def load_standalone_cron_jobs(tenant_id: str = TENANT_ID) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    """Load standalone cron YAML files for a tenant.

    Required YAML fields: ``skill_name``, ``cron``, ``user_id``.
    ``params`` and ``payload`` are accepted aliases; they map to Job.params.
    """
    root = standalone_cron_dir(tenant_id)
    if not root.exists():
        return [], []

    jobs: list[dict[str, Any]] = []
    skipped: list[dict[str, str]] = []
    for path in sorted(root.glob("*.yaml")):
        if path.name.startswith("_"):
            continue
        try:
            raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
            if not isinstance(raw, dict):
                skipped.append({"file": path.name, "reason": "YAML root must be a mapping"})
                continue
            job = _normalize_job_dict(raw, path, tenant_id)
            jobs.append(job)
        except Exception as exc:
            skipped.append({"file": path.name, "reason": str(exc)})
    return jobs, skipped


def reconcile_standalone_cron_jobs(tenant_id: str = TENANT_ID) -> dict[str, Any]:
    """Ensure enterprise_root standalone cron YAML exists in Redis scheduler.

    This creates or updates Redis scheduler jobs, but intentionally does not
    delete Redis-only jobs. That avoids losing manually-created jobs before an
    explicit export/migration step has captured them as YAML.
    """
    from iaf_agent_skills.scheduler.models import Job
    from shared.state import cron_scheduler

    definitions, skipped = load_standalone_cron_jobs(tenant_id)
    repaired: list[dict[str, Any]] = []

    for definition in definitions:
        existing = cron_scheduler.get_job(str(definition["id"]))
        if existing is None:
            existing = cron_scheduler.get_job_by_name(str(definition["name"]), tenant_id)

        if existing is not None:
            existing.name = str(definition["name"])
            existing.skill_name = str(definition["skill_name"])
            existing.task = str(definition.get("task") or "")
            existing.params = dict(definition.get("params") or {})
            existing.cron = str(definition["cron"])
            existing.timezone = str(definition.get("timezone") or "UTC")
            existing.tenant_id = tenant_id
            existing.agent_id = str(definition.get("agent_id") or AGENT_ID)
            existing.user_id = str(definition["user_id"])
            existing.enabled = bool(definition.get("enabled", True))
            existing.max_runtime_seconds = int(definition.get("max_runtime_seconds") or 300)
            existing.description = str(definition.get("description") or "")
            existing.tags = _tags(definition.get("tags"))
            existing.next_run_at = None
            saved = cron_scheduler.add_job(existing)
            action = "updated"
        else:
            saved = cron_scheduler.add_job(Job(
                id=str(definition["id"]),
                name=str(definition["name"]),
                skill_name=str(definition["skill_name"]),
                task=str(definition.get("task") or ""),
                params=dict(definition.get("params") or {}),
                cron=str(definition["cron"]),
                timezone=str(definition.get("timezone") or "UTC"),
                tenant_id=tenant_id,
                agent_id=str(definition.get("agent_id") or AGENT_ID),
                user_id=str(definition["user_id"]),
                enabled=bool(definition.get("enabled", True)),
                max_runtime_seconds=int(definition.get("max_runtime_seconds") or 300),
                description=str(definition.get("description") or ""),
                tags=_tags(definition.get("tags")),
                created_by=str(definition.get("created_by") or "enterprise_root"),
            ))
            action = "created"

        repaired.append({
            "file": definition["_source_file"],
            "job_id": saved.id,
            "job_name": saved.name,
            "cron": saved.cron,
            "enabled": saved.enabled,
            "action": action,
        })

    logger.info(
        "Standalone cron reconcile: %s repaired, %s skipped",
        len(repaired),
        len(skipped),
    )
    if repaired:
        from shared import cron_read_cache
        cron_read_cache.invalidate()   # reconcile mutated the scheduler → drop stale reads
    return {"repaired": repaired, "skipped": skipped, "total": len(repaired)}


def export_redis_standalone_cron_jobs(
    tenant_id: str = TENANT_ID,
    *,
    overwrite: bool = False,
) -> dict[str, Any]:
    """Export existing Redis-only standalone cron jobs to enterprise_root YAML.

    Workstream cron jobs (`ws_*` / `workstream` tag) are intentionally skipped
    because their source of truth is already the workstream YAML.
    """
    from shared.state import cron_scheduler

    root = standalone_cron_dir(tenant_id)
    root.mkdir(parents=True, exist_ok=True)
    exported: list[dict[str, str]] = []
    skipped: list[dict[str, str]] = []

    for job in cron_scheduler.list_jobs(tenant_id=tenant_id):
        if _is_workstream_job(job):
            skipped.append({"job": job.name, "reason": "workstream cron"})
            continue
        filename = f"{_safe_filename(job.name or job.id)}.yaml"
        path = root / filename
        if path.exists() and not overwrite:
            skipped.append({"job": job.name, "reason": f"{filename} already exists"})
            continue
        payload = _job_to_yaml_dict(job)
        path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")
        exported.append({"job": job.name, "file": filename})

    return {"exported": exported, "skipped": skipped, "total": len(exported)}


def _normalize_job_dict(raw: dict[str, Any], path: Path, tenant_id: str) -> dict[str, Any]:
    job_id = str(raw.get("id") or path.stem).strip()
    name = str(raw.get("name") or job_id).strip()
    skill_name = str(raw.get("skill_name") or "").strip()
    cron = str(raw.get("cron") or raw.get("cron_schedule") or "").strip()
    user_id = str(raw.get("user_id") or raw.get("cron_user_id") or "").strip()

    missing = [
        field
        for field, value in [
            ("id/name", job_id or name),
            ("skill_name", skill_name),
            ("cron", cron),
            ("user_id", user_id),
        ]
        if not value
    ]
    if missing:
        raise ValueError(f"missing required field(s): {', '.join(missing)}")

    params = raw.get("params")
    if params is None:
        params = raw.get("payload") or {}
    if not isinstance(params, dict):
        raise ValueError("params/payload must be a mapping")

    job = dict(raw)
    job.update({
        "id": job_id,
        "name": name,
        "skill_name": skill_name,
        "cron": cron,
        "user_id": user_id,
        "tenant_id": str(raw.get("tenant_id") or tenant_id),
        "agent_id": str(raw.get("agent_id") or AGENT_ID),
        "params": params,
        "_source_file": path.name,
    })
    return job


def _tags(raw_tags: Any) -> list[str]:
    if isinstance(raw_tags, list):
        tags = [str(t).strip() for t in raw_tags if str(t).strip()]
    elif isinstance(raw_tags, str) and raw_tags.strip():
        tags = [raw_tags.strip()]
    else:
        tags = []
    return sorted(set([*tags, "standalone_cron", "reconciled"]))


def _is_workstream_job(job: Any) -> bool:
    tags = {str(t).strip().lower() for t in (getattr(job, "tags", None) or [])}
    name = str(getattr(job, "name", "") or "")
    return name.startswith("ws_") or "workstream" in tags or "mission_mode" in tags


def _safe_filename(value: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9_.-]+", "_", value.strip()).strip("._")
    return slug or "cron_job"


def _job_to_yaml_dict(job: Any) -> dict[str, Any]:
    tags = [
        str(t)
        for t in (getattr(job, "tags", None) or [])
        if str(t) not in {"reconciled"}
    ]
    return {
        "id": str(getattr(job, "id", "")),
        "name": str(getattr(job, "name", "")),
        "skill_name": str(getattr(job, "skill_name", "")),
        "task": str(getattr(job, "task", "")),
        "cron": str(getattr(job, "cron", "")),
        "timezone": str(getattr(job, "timezone", "UTC") or "UTC"),
        "tenant_id": str(getattr(job, "tenant_id", TENANT_ID) or TENANT_ID),
        "agent_id": str(getattr(job, "agent_id", AGENT_ID) or AGENT_ID),
        "user_id": str(getattr(job, "user_id", "scheduler") or "scheduler"),
        "enabled": bool(getattr(job, "enabled", True)),
        "max_runtime_seconds": int(getattr(job, "max_runtime_seconds", 300) or 300),
        "description": str(getattr(job, "description", "") or ""),
        "params": dict(getattr(job, "params", None) or {}),
        "tags": sorted(set(tags + ["standalone_cron"])),
    }
