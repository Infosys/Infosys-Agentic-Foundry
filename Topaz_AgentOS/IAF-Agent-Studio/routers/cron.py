"""
IAF Agent Studio — Cron Jobs API Router

Scheduled agent task management: CRUD, start/stop scheduler,
manual triggers, run history.

Authorization model (owner-scoped, mirrors how skills are creator-owned):
  * Ownership is server-truth: `created_by` is stamped from the authenticated
    identity on create — the client CANNOT set/spoof the owner or tenant.
  * Visibility/management: a normal user sees & manages ONLY the jobs they
    created (`created_by == user_id`); a tenant admin sees & manages ALL jobs in
    their tenant. Everything is tenant-isolated (tenant derived from identity).
  * Legacy/system jobs (`created_by` empty or a service principal — workstream
    reconcilers, platform `ccd-*`, the scheduler itself) have no real user owner,
    so they are visible to admins only.
  * Jobs a caller may not access return 404 (not 403) so job existence isn't
    leaked across users/tenants.
  * Scheduler start/stop is an operational control → admin only.
When AUTH_ENABLED=false (dev), require_auth/require_admin resolve to a dev admin,
so every route is fully visible locally.
"""

import asyncio
import logging
import time
from typing import Optional

from fastapi import APIRouter, HTTPException, Depends, Request

from shared.models import CronJobCreate, CronJobUpdate
from shared.state import cron_scheduler
from shared import cron_read_cache
from iaf_agent_skills.scheduler import Job, RunStatus
from auth.middleware import require_auth, require_admin

logger = logging.getLogger(__name__)

router = APIRouter()


def _invalidate_cron_cache() -> None:
    """Drop cached cron reads so the next list/status reflects a mutation at once."""
    cron_read_cache.invalidate()


async def _get_jobs_cached(tenant: str, enabled_only: bool) -> list:
    """Tenant's jobs, offloaded to a thread and served from the shared TTL cache."""
    return await cron_read_cache.get_jobs(cron_scheduler.list_jobs, tenant, enabled_only)


async def _get_status_cached() -> dict:
    """Scheduler status, offloaded to a thread and served from the shared TTL cache."""
    return await cron_read_cache.get_status(cron_scheduler.get_status)


def _is_admin(user: dict) -> bool:
    """True if the identity carries the admin role."""
    return user.get("role") == "admin" or "admin" in (user.get("roles") or [])


def _caller_tenant(user: dict) -> str:
    """Tenant to scope every query by — always derived from the identity, never
    from client input (prevents cross-tenant enumeration)."""
    return user.get("tenant_id") or "company"


def _owns(user: dict, job: Job) -> bool:
    """True if this identity is the job's creator. Legacy/system jobs
    (`created_by` empty) have no real owner and never match a user."""
    created_by = (getattr(job, "created_by", "") or "").strip()
    return bool(created_by) and created_by == user.get("user_id")


def _can_access(user: dict, job: Job) -> bool:
    """A job is accessible iff it's in the caller's tenant AND (caller is admin
    OR caller owns it). Same rule for view and manage."""
    if getattr(job, "tenant_id", None) != _caller_tenant(user):
        return False
    return _is_admin(user) or _owns(user, job)


def _get_accessible_job_or_404(job_id: str, user: dict) -> Job:
    """Fetch a job the caller is allowed to see; otherwise 404 (never leak
    existence of another user's / system / cross-tenant job)."""
    job = cron_scheduler.get_job(job_id)
    if not job or not _can_access(user, job):
        raise HTTPException(404, f"Job '{job_id}' not found")
    return job


@router.get("/api/cron")
async def list_cron_jobs(
    enabled_only: bool = False,
    user: dict = Depends(require_auth),
):
    """List scheduled cron jobs the caller may see: own jobs for a normal user,
    all of the tenant's jobs for an admin. Tenant is derived from the identity."""
    tenant = _caller_tenant(user)
    jobs = await _get_jobs_cached(tenant, enabled_only)
    is_admin = _is_admin(user)
    if not is_admin:
        jobs = [j for j in jobs if _owns(user, j)]
    status = await _get_status_cached()
    return {
        "jobs": [j.to_dict() for j in jobs],
        "total": len(jobs),
        "scope": "all" if is_admin else "owned",
        "scheduler_status": status,
    }


@router.post("/api/cron")
async def create_cron_job(job_data: CronJobCreate, user: dict = Depends(require_auth)):
    """Create a scheduled cron job. The owner (`created_by`/`user_id`) and tenant
    are stamped from the authenticated identity — the request body cannot set them
    (prevents impersonating another user or targeting another tenant)."""
    from iaf_agent_skills.scheduler.models import RetryPolicy

    tenant = _caller_tenant(user)
    owner = user.get("user_id") or "unknown"

    # Check if job with this name already exists within the caller's tenant
    existing = await asyncio.to_thread(cron_scheduler.get_job_by_name, job_data.name, tenant)
    if existing:
        raise HTTPException(400, f"Job '{job_data.name}' already exists")

    retry_policy = None
    if job_data.retry_max_retries > 0:
        retry_policy = RetryPolicy(
            max_retries=job_data.retry_max_retries,
            initial_delay_seconds=job_data.retry_initial_delay,
            backoff_multiplier=job_data.retry_backoff_multiplier,
        )

    # Create job — owner/tenant come from identity, NOT the client body.
    job = Job(
        name=job_data.name,
        skill_name=job_data.skill_name,
        task=job_data.task,
        cron=job_data.cron,
        description=job_data.description,
        tenant_id=tenant,
        agent_id=job_data.agent_id,
        user_id=owner,
        created_by=owner,
        max_runtime_seconds=job_data.max_runtime_seconds,
        enabled=job_data.enabled,
        tags=job_data.tags,
        retry_policy=retry_policy,
    )

    saved = await asyncio.to_thread(cron_scheduler.add_job, job)
    _invalidate_cron_cache()
    logger.info("Cron job created: name=%s id=%s created_by=%s tenant=%s",
                saved.name, saved.id, owner, tenant)

    return {
        "message": f"Created cron job '{saved.name}'",
        "job": saved.to_dict(),
    }


# NOTE: These routes MUST come BEFORE /api/cron/{job_id} to avoid being matched as job_id
@router.get("/api/cron/status")
async def get_scheduler_status(user: dict = Depends(require_auth)):
    """Get overall scheduler status and metrics (any authenticated user)."""
    return await _get_status_cached()


@router.post("/api/cron/start")
async def start_scheduler(user: dict = Depends(require_admin)):
    """Start the cron scheduler (if not already running). Admin only — this is a
    fleet-wide operational control, not a per-user action."""
    if cron_scheduler.is_running:
        return {"message": "Scheduler already running", "status": await _get_status_cached()}

    # Offloaded: start/stop touch the scheduler's threads and must not block the loop.
    await asyncio.to_thread(cron_scheduler.start, blocking=False)
    _invalidate_cron_cache()
    return {"message": "Scheduler started", "status": await _get_status_cached()}


@router.post("/api/cron/stop")
async def stop_scheduler(user: dict = Depends(require_admin)):
    """Stop the cron scheduler gracefully. Admin only (fleet-wide control)."""
    if not cron_scheduler.is_running:
        return {"message": "Scheduler not running"}

    # Offloaded: stop(wait=True, timeout=10s) would otherwise block EVERY request on
    # the single API worker for up to 10 seconds.
    await asyncio.to_thread(cron_scheduler.stop, wait=True, timeout=10.0)
    _invalidate_cron_cache()
    return {"message": "Scheduler stopped", "status": await _get_status_cached()}


@router.get("/api/cron/{job_id}")
async def get_cron_job(
    job_id: str,
    include_runs: bool = True,
    runs_limit: int = 10,
    user: dict = Depends(require_auth),
):
    """Get cron job details with recent run history (owner or admin only)."""
    job = _get_accessible_job_or_404(job_id, user)

    result = {"job": job.to_dict()}

    if include_runs:
        runs = cron_scheduler.get_runs(job_id=job_id, limit=runs_limit)
        logger.debug("get_cron_job: Found %d runs for job %s", len(runs), job_id)
        for i, r in enumerate(runs[:3]):
            logger.debug("Run %d: id=%s, status=%s, output=%s...", i, r.id, r.status, r.output_response[:30] if r.output_response else 'None')
        result["runs"] = [r.to_dict() for r in runs]
        result["stats"] = cron_scheduler.get_job_stats(job_id)

    return result


@router.put("/api/cron/{job_id}")
async def update_cron_job(job_id: str, update: CronJobUpdate, user: dict = Depends(require_auth)):
    """Update an existing cron job (owner or admin only). Only provided fields are
    updated; owner and tenant are immutable via this endpoint."""
    job = _get_accessible_job_or_404(job_id, user)

    if update.name is not None:
        job.name = update.name
    if update.skill_name is not None:
        job.skill_name = update.skill_name
    if update.task is not None:
        job.task = update.task
    if update.cron is not None:
        job.cron = update.cron
        # Recalculate next run when cron changes
        job.next_run_at = cron_scheduler._calculate_next_run(job)
    if update.description is not None:
        job.description = update.description
    if update.max_runtime_seconds is not None:
        job.max_runtime_seconds = update.max_runtime_seconds
    if update.enabled is not None:
        job.enabled = update.enabled
    if update.tags is not None:
        job.tags = update.tags

    saved = await asyncio.to_thread(cron_scheduler.update_job, job)
    _invalidate_cron_cache()

    return {
        "message": f"Updated job '{saved.name}'",
        "job": saved.to_dict(),
    }


@router.delete("/api/cron/{job_id}")
async def delete_cron_job(job_id: str, user: dict = Depends(require_auth)):
    """Delete a cron job (owner or admin only)."""
    job = _get_accessible_job_or_404(job_id, user)

    await asyncio.to_thread(cron_scheduler.delete_job, job_id)
    _invalidate_cron_cache()

    return {"message": f"Deleted job '{job.name}'"}


@router.post("/api/cron/{job_id}/run")
async def trigger_cron_job(job_id: str, user: dict = Depends(require_auth)):
    """Manually trigger a cron job to run immediately (owner or admin only; fire-and-forget)."""
    import asyncio
    job = _get_accessible_job_or_404(job_id, user)

    # Run in a background thread: trigger_now() takes 15-30s and would hang the HTTP response.
    asyncio.create_task(asyncio.to_thread(cron_scheduler.trigger_now, job_id, "manual"))

    return {
        "message": f"Job '{job.name}' started in background",
        "status": "running",
        "job_id": job_id,
    }


@router.post("/api/cron/{job_id}/enable")
async def enable_cron_job(job_id: str, user: dict = Depends(require_auth)):
    """Enable a disabled cron job (owner or admin only)."""
    _get_accessible_job_or_404(job_id, user)  # authorize before mutating
    job = await asyncio.to_thread(cron_scheduler.enable_job, job_id)
    if not job:
        raise HTTPException(404, f"Job '{job_id}' not found")
    _invalidate_cron_cache()

    return {
        "message": f"Enabled job '{job.name}'",
        "job": job.to_dict(),
    }


@router.post("/api/cron/{job_id}/disable")
async def disable_cron_job(job_id: str, user: dict = Depends(require_auth)):
    """Disable a cron job (owner or admin only; stops scheduling but preserves config)."""
    _get_accessible_job_or_404(job_id, user)  # authorize before mutating
    job = await asyncio.to_thread(cron_scheduler.disable_job, job_id)
    if not job:
        raise HTTPException(404, f"Job '{job_id}' not found")
    _invalidate_cron_cache()

    return {
        "message": f"Disabled job '{job.name}'",
        "job": job.to_dict(),
    }


@router.get("/api/cron/{job_id}/runs")
async def get_cron_job_runs(
    job_id: str,
    status: Optional[str] = None,
    limit: int = 50,
    user: dict = Depends(require_auth),
):
    """Get run history for a specific job (owner or admin only)."""
    job = _get_accessible_job_or_404(job_id, user)

    run_status = RunStatus(status) if status else None
    runs = cron_scheduler.get_runs(job_id=job_id, status=run_status, limit=limit)

    return {
        "job_id": job_id,
        "job_name": job.name,
        "runs": [r.to_dict() for r in runs],
        "total": len(runs),
    }
