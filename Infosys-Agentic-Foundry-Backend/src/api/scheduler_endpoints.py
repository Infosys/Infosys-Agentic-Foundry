# © 2024-25 Infosys Limited, Bangalore, India. All Rights Reserved.
"""REST endpoints for the cron scheduler subsystem.

All routes are mounted under `/chat/schedules`. Authorization rules:

| Action          | Admin / SuperAdmin     | Developer (owner)   | User |
|-----------------|------------------------|---------------------|------|
| Create          | yes                    | yes                 | no   |
| List own        | yes                    | yes                 | no   |
| List all        | yes                    | no                  | no   |
| Read / update / delete / pause / resume / history | yes (any) | yes (own only) | no |
| Validate / enums / upcoming                       | yes      | yes            | no |

Soft-delete is the default; pass `?hard_delete=true` for irreversible removal.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from src.api.dependencies import ServiceProvider
from src.auth.authorization_service import AuthorizationService
from src.auth.dependencies import get_current_user
from src.auth.models import User, UserRole
from src.config.constants import CronSchedulerConfig, FrameworkType
from src.database.services.scheduler_service import SchedulerService
from src.database.services import ChatService
from src.schemas.scheduler_schemas import (
    CommonTimezone,
    DayOfWeek,
    Month,
    RunNowResponse,
    ScheduleExecutionStatus,
    ScheduleFrequency,
    ScheduledJobCreateRequest,
    ScheduledJobListResponse,
    ScheduledJobResponse,
    ScheduledJobUpdateRequest,
    ScheduleExecutionDetailResponse,
    ScheduleHistoryListResponse,
    SchedulerEnumsResponse,
    UpcomingRunEntry,
    UpcomingRunsResponse,
    ValidateCronRequest,
    ValidateCronResponse,
)
from src.utils.cron_expression_helper import (
    describe_cron_expression,
    parse_cron_to_structured,
)
from src.utils.message_queue_factory.message_queue_manager import MessageQueueManager
from telemetry_wrapper import logger as log


router = APIRouter(prefix="/chat/schedules", tags=["Scheduler"])


# ---------------------------------------------------------------------------
# RBAC helpers
# ---------------------------------------------------------------------------


_ADMIN_ROLES = {UserRole.ADMIN.value, UserRole.SUPER_ADMIN.value}
_OWNER_ROLES = {UserRole.ADMIN.value, UserRole.SUPER_ADMIN.value, UserRole.DEVELOPER.value}


def _is_admin(user: User) -> bool:
    return user.role in _ADMIN_ROLES


def _ensure_can_manage(user: User) -> None:
    """Reject regular `User` accounts from any scheduler operation."""
    if user.role not in _OWNER_ROLES:
        raise HTTPException(
            status_code=403,
            detail="You do not have permission to use the scheduler.",
        )


def _ensure_can_create(user: User) -> None:
    if user.role == UserRole.SUPER_ADMIN.value:
        raise HTTPException(
            status_code=403, detail="SuperAdmin is not allowed to create schedules."
        )
    if user.role not in _OWNER_ROLES:
        raise HTTPException(
            status_code=403, detail="You do not have permission to create schedules."
        )


def _ensure_can_access(user: User, schedule: Dict[str, Any]) -> None:
    """Ensure the caller can read/modify the given schedule."""
    if _is_admin(user):
        return
    if schedule.get("created_by") == user.email:
        return
    raise HTTPException(
        status_code=403, detail="You do not have access to this schedule."
    )


async def _check_authz(
    authorization_service: AuthorizationService,
    user: User,
    operation: str,
) -> None:
    """Optional cross-check against the central authz matrix.

    Resource type is `agents` because schedules invoke agents — the
    central permission model already gates that resource.
    """
    try:
        ok = await authorization_service.check_operation_permission(
            user.email, user.role, operation, "agents", user.department_name
        )
    except Exception as exc:
        log.warning(f"Authz check failed (operation={operation}): {exc}")
        ok = True  # do not lock users out if the central service errors
    if not ok:
        raise HTTPException(
            status_code=403,
            detail=f"You do not have permission to {operation} schedules.",
        )


def _to_response(row: Dict[str, Any]) -> ScheduledJobResponse:
    return ScheduledJobResponse(**row)


# ---------------------------------------------------------------------------
# Bootstrap / helper endpoints
# ---------------------------------------------------------------------------


@router.get("/status")
async def get_scheduler_status(request: Request):
    """Return whether the scheduler subsystem is available.

    This endpoint does NOT require authentication so the UI can check
    availability before showing scheduler features.
    """
    from src.api.app_container import app_container

    mq_configured = app_container.mq_manager is not None
    scheduler_enabled = CronSchedulerConfig.ENABLED

    available = mq_configured and scheduler_enabled

    reasons = []
    if not mq_configured:
        reasons.append("Message queue is not configured (MESSAGE_QUEUE_PROVIDER is empty or 'none').")
    if not scheduler_enabled:
        reasons.append("Cron scheduler is disabled (CRON_SCHEDULER_ENABLED=false).")

    return {
        "available": available,
        "mq_configured": mq_configured,
        "scheduler_enabled": scheduler_enabled,
        "reason": " ".join(reasons) if reasons else None,
    }


@router.get("/enums", response_model=SchedulerEnumsResponse)
async def get_scheduler_enums(
    user_data: User = Depends(get_current_user),
):
    """Return the dropdown values the UI needs to build the schedule form."""
    _ensure_can_manage(user_data)
    return SchedulerEnumsResponse(
        frequencies=[f.value for f in ScheduleFrequency],
        days_of_week=[d.value for d in DayOfWeek],
        months=[m.value for m in Month],
        timezones=[tz.value for tz in CommonTimezone],
        framework_types=[ft.value for ft in FrameworkType],
        execution_statuses=[s.value for s in ScheduleExecutionStatus],
    )


@router.post("/validate-cron", response_model=ValidateCronResponse)
async def validate_cron_expression_endpoint(
    payload: ValidateCronRequest,
    user_data: User = Depends(get_current_user),
    scheduler_service: SchedulerService = Depends(ServiceProvider.get_scheduler_service),
):
    """Validate a raw or structured cron expression and preview next runs."""
    _ensure_can_manage(user_data)
    from src.utils.cron_expression_helper import resolve_cron_expression

    cron_expression, error = resolve_cron_expression(
        payload.cron_expression, payload.schedule
    )
    if error:
        return ValidateCronResponse(
            valid=False,
            cron_expression=payload.cron_expression or "",
            timezone=payload.timezone,
            error=error,
        )

    next_runs, preview_error = scheduler_service.preview_runs(
        cron_expression, payload.timezone
    )
    if preview_error:
        return ValidateCronResponse(
            valid=False,
            cron_expression=cron_expression,
            timezone=payload.timezone,
            error=preview_error,
        )

    return ValidateCronResponse(
        valid=True,
        cron_expression=cron_expression,
        timezone=payload.timezone,
        human_readable=describe_cron_expression(cron_expression),
        schedule=parse_cron_to_structured(cron_expression),
        next_runs=next_runs,
    )


@router.get("/upcoming", response_model=UpcomingRunsResponse)
async def get_upcoming_runs_endpoint(
    only_mine: bool = Query(default=False, description="Restrict to the caller's own jobs."),
    limit: int = Query(default=20, ge=1, le=200),
    user_data: User = Depends(get_current_user),
    scheduler_service: SchedulerService = Depends(ServiceProvider.get_scheduler_service),
):
    """Dashboard helper: next-fire times across active schedules."""
    _ensure_can_manage(user_data)
    rows = await scheduler_service.list_upcoming(
        viewer_email=user_data.email,
        viewer_is_admin=_is_admin(user_data),
        only_mine=only_mine,
        limit=limit,
    )
    upcoming = [
        UpcomingRunEntry(
            job_id=r["job_id"],
            schedule_name=r["schedule_name"],
            cron_expression=r["cron_expression"],
            timezone=r["timezone"],
            next_run_at=r["next_run_at"],
        )
        for r in rows
        if r.get("next_run_at") is not None
    ]
    return UpcomingRunsResponse(total=len(upcoming), upcoming=upcoming)


# ---------------------------------------------------------------------------
# CRUD
# ---------------------------------------------------------------------------


@router.post("", response_model=ScheduledJobResponse, status_code=201)
async def create_schedule_endpoint(
    payload: ScheduledJobCreateRequest,
    user_data: User = Depends(get_current_user),
    authorization_service: AuthorizationService = Depends(
        ServiceProvider.get_authorization_service
    ),
    scheduler_service: SchedulerService = Depends(ServiceProvider.get_scheduler_service),
):
    """Create a new scheduled job."""
    _ensure_can_create(user_data)
    await _check_authz(authorization_service, user_data, "create")

    record, error = await scheduler_service.create_schedule(payload, user_data.email)
    if error or record is None:
        # Conflicts use 409, anything else is 400.
        status = 409 if error and "already exists" in error.lower() else 400
        raise HTTPException(status_code=status, detail=error or "Could not create schedule.")
    return _to_response(record)


@router.get("", response_model=ScheduledJobListResponse)
async def list_schedules_endpoint(
    only_mine: bool = Query(default=False, description="Admins: restrict to own jobs."),
    only_active: bool = Query(default=False, description="Filter to active jobs."),
    search_value: Optional[str] = Query(default=None, description="Filter by schedule name (substring match, case-insensitive)."),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    user_data: User = Depends(get_current_user),
    scheduler_service: SchedulerService = Depends(ServiceProvider.get_scheduler_service),
):
    """List schedules visible to the caller."""
    _ensure_can_manage(user_data)
    rows, total = await scheduler_service.list_schedules(
        viewer_email=user_data.email,
        viewer_is_admin=_is_admin(user_data),
        only_mine=only_mine,
        only_active=only_active,
        search_value=search_value.strip() if search_value else None,
        limit=limit,
        offset=offset,
    )
    return ScheduledJobListResponse(
        total=total, schedules=[_to_response(r) for r in rows]
    )


@router.get("/{job_id}", response_model=ScheduledJobResponse)
async def get_schedule_endpoint(
    job_id: str,
    user_data: User = Depends(get_current_user),
    scheduler_service: SchedulerService = Depends(ServiceProvider.get_scheduler_service),
):
    """Fetch a single schedule by id."""
    _ensure_can_manage(user_data)
    record = await scheduler_service.get_schedule(job_id)
    if not record:
        raise HTTPException(status_code=404, detail="Schedule not found.")
    _ensure_can_access(user_data, record)
    return _to_response(record)


@router.patch("/{job_id}", response_model=ScheduledJobResponse)
@router.post("/update/{job_id}", response_model=ScheduledJobResponse)
async def update_schedule_endpoint(
    job_id: str,
    payload: ScheduledJobUpdateRequest,
    user_data: User = Depends(get_current_user),
    authorization_service: AuthorizationService = Depends(
        ServiceProvider.get_authorization_service
    ),
    scheduler_service: SchedulerService = Depends(ServiceProvider.get_scheduler_service),
):
    """Update a schedule (partial)."""
    _ensure_can_manage(user_data)
    existing = await scheduler_service.get_schedule(job_id)
    if not existing:
        raise HTTPException(status_code=404, detail="Schedule not found.")
    _ensure_can_access(user_data, existing)
    await _check_authz(authorization_service, user_data, "update")

    record, error = await scheduler_service.update_schedule(job_id, payload)
    if error or record is None:
        status = 409 if error and "conflict" in error.lower() else 400
        raise HTTPException(status_code=status, detail=error or "Update failed.")
    return _to_response(record)


@router.delete("/{job_id}", status_code=204)
@router.post("/delete/{job_id}", status_code=204)
async def delete_schedule_endpoint(
    job_id: str,
    hard_delete: bool = Query(default=False, description="If true, irreversibly delete."),
    user_data: User = Depends(get_current_user),
    authorization_service: AuthorizationService = Depends(
        ServiceProvider.get_authorization_service
    ),
    scheduler_service: SchedulerService = Depends(ServiceProvider.get_scheduler_service),
):
    """Soft-delete (default) or hard-delete a schedule."""
    _ensure_can_manage(user_data)
    existing = await scheduler_service.get_schedule(job_id)
    if not existing and not hard_delete:
        raise HTTPException(status_code=404, detail="Schedule not found.")
    if existing:
        _ensure_can_access(user_data, existing)
    elif not _is_admin(user_data):
        # Hard-delete on a non-existent (or already soft-deleted) row — only admins may attempt.
        raise HTTPException(status_code=404, detail="Schedule not found.")

    await _check_authz(authorization_service, user_data, "delete")
    ok, error = await scheduler_service.delete_schedule(job_id, hard=hard_delete)
    if not ok:
        raise HTTPException(status_code=400, detail=error or "Delete failed.")
    return None


# ---------------------------------------------------------------------------
# Lifecycle helpers
# ---------------------------------------------------------------------------


@router.post("/{job_id}/pause", response_model=ScheduledJobResponse)
async def pause_schedule_endpoint(
    job_id: str,
    user_data: User = Depends(get_current_user),
    scheduler_service: SchedulerService = Depends(ServiceProvider.get_scheduler_service),
):
    """Pause an active schedule (prevents future fires until resumed)."""
    _ensure_can_manage(user_data)
    existing = await scheduler_service.get_schedule(job_id)
    if not existing:
        raise HTTPException(status_code=404, detail="Schedule not found.")
    _ensure_can_access(user_data, existing)

    ok, error = await scheduler_service.set_active(job_id, is_active=False)
    if not ok:
        raise HTTPException(status_code=400, detail=error or "Pause failed.")
    refreshed = await scheduler_service.get_schedule(job_id)
    return _to_response(refreshed) if refreshed else _to_response(existing)


@router.post("/{job_id}/resume", response_model=ScheduledJobResponse)
async def resume_schedule_endpoint(
    job_id: str,
    user_data: User = Depends(get_current_user),
    scheduler_service: SchedulerService = Depends(ServiceProvider.get_scheduler_service),
):
    """Resume a paused schedule (recomputes the next fire time)."""
    _ensure_can_manage(user_data)
    existing = await scheduler_service.get_schedule(job_id)
    if not existing:
        raise HTTPException(status_code=404, detail="Schedule not found.")
    _ensure_can_access(user_data, existing)

    ok, error = await scheduler_service.set_active(job_id, is_active=True)
    if not ok:
        raise HTTPException(status_code=400, detail=error or "Resume failed.")
    refreshed = await scheduler_service.get_schedule(job_id)
    return _to_response(refreshed) if refreshed else _to_response(existing)


@router.post("/{job_id}/run-now", response_model=RunNowResponse)
async def run_schedule_now_endpoint(
    job_id: str,
    user_data: User = Depends(get_current_user),
    scheduler_service: SchedulerService = Depends(ServiceProvider.get_scheduler_service),
    task_registry_service=Depends(ServiceProvider.get_task_registry_service),
    mq_manager: MessageQueueManager = Depends(ServiceProvider.get_message_queue_manager),
):
    """Trigger an immediate one-shot dispatch of a schedule, bypassing cron timing.

    Useful for manual testing. The job's normal next-run schedule is preserved.
    """
    from src.inference.cron_scheduler_runner import dispatch_job_now

    _ensure_can_manage(user_data)
    existing = await scheduler_service.get_schedule(job_id)
    if not existing:
        raise HTTPException(status_code=404, detail="Schedule not found.")
    _ensure_can_access(user_data, existing)

    if existing.get("is_deleted"):
        raise HTTPException(status_code=400, detail="Cannot run a deleted schedule.")

    result = await dispatch_job_now(
        job=existing,
        scheduler_service=scheduler_service,
        task_registry_service=task_registry_service,
        mq_manager=mq_manager,
    )
    return RunNowResponse(
        job_id=job_id,
        task_id=result["task_id"],
        session_id=result["session_id"],
        execution_id=result.get("execution_id"),
        success=result["success"],
        error=result.get("error"),
    )


# ---------------------------------------------------------------------------
# History
# ---------------------------------------------------------------------------


@router.get("/{job_id}/history", response_model=ScheduleHistoryListResponse)
async def list_schedule_history_endpoint(
    job_id: str,
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    user_data: User = Depends(get_current_user),
    scheduler_service: SchedulerService = Depends(ServiceProvider.get_scheduler_service),
):
    """Return paginated execution history for a schedule."""
    _ensure_can_manage(user_data)
    existing = await scheduler_service.get_schedule(job_id)
    if not existing:
        raise HTTPException(status_code=404, detail="Schedule not found.")
    _ensure_can_access(user_data, existing)

    rows, total = await scheduler_service.list_history(job_id, limit=limit, offset=offset)
    return ScheduleHistoryListResponse(
        total=total, job_id=job_id, executions=rows
    )


@router.get(
    "/{job_id}/history/{execution_id}",
    response_model=ScheduleExecutionDetailResponse,
)
async def get_schedule_execution_endpoint(
    job_id: str,
    execution_id: str,
    user_data: User = Depends(get_current_user),
    scheduler_service: SchedulerService = Depends(ServiceProvider.get_scheduler_service),
    chat_service: ChatService = Depends(ServiceProvider.get_chat_service),
):
    """Return one execution record, plus the live chat history for its session.

    The chat history is fetched on demand from the short-term memory store
    (LangGraph checkpointer / GoogleADK session / Python chat-state manager).
    If the session has since been deleted, `chat_history` will be `null` and
    `chat_history_error` will carry the reason.
    """
    _ensure_can_manage(user_data)
    existing = await scheduler_service.get_schedule(job_id)
    if not existing:
        raise HTTPException(status_code=404, detail="Schedule not found.")
    _ensure_can_access(user_data, existing)

    record = await scheduler_service.get_execution(execution_id)
    if not record or record.get("job_id") != job_id:
        raise HTTPException(status_code=404, detail="Execution not found for this schedule.")

    chat_history: Optional[Dict[str, Any]] = None
    chat_history_error: Optional[str] = None
    session_id = record.get("session_id")
    terminal_statuses = {
        ScheduleExecutionStatus.DISPATCHED.value,
        ScheduleExecutionStatus.SUCCEEDED.value,
        ScheduleExecutionStatus.FAILED.value,
    }
    status_value = record.get("status")
    if hasattr(status_value, "value"):
        status_value = status_value.value
    if session_id and status_value in terminal_statuses:
        try:
            framework_type = FrameworkType(existing["framework_type"])
            history_payload = await chat_service.get_chat_history_from_short_term_memory(
                agentic_application_id=existing["agentic_application_id"],
                session_id=session_id,
                framework_type=framework_type,
                role=user_data.role,
                department_name=user_data.department_name,
            )
            if isinstance(history_payload, dict) and history_payload.get("error"):
                chat_history_error = str(history_payload["error"])
            else:
                chat_history = history_payload
        except Exception as exc:
            chat_history_error = f"Failed to load chat history: {exc}"

    return ScheduleExecutionDetailResponse(
        **record,
        chat_history=chat_history,
        chat_history_error=chat_history_error,
    )
