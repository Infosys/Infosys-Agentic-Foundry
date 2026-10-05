# © 2024-25 Infosys Limited, Bangalore, India. All Rights Reserved.
"""Business logic for the cron scheduler subsystem.

Sits between the FastAPI endpoints and the repositories. Owns the rules
for cron expression resolution, RBAC visibility, and bookkeeping after
each dispatch attempt.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from src.config.constants import CronSchedulerConfig, FrameworkType
from src.database.repositories.scheduler_repository import (
    ScheduleExecutionHistoryRepository,
    ScheduledJobRepository,
)
from src.schemas.scheduler_schemas import (
    InferenceFlags,
    ScheduledJobCreateRequest,
    ScheduledJobUpdateRequest,
    ScheduleExecutionStatus,
)
from src.utils.cron_expression_helper import (
    describe_cron_expression,
    get_next_n_runs,
    get_next_run,
    parse_cron_to_structured,
    resolve_cron_expression,
    resolve_timezone,
)
from telemetry_wrapper import logger as log


class SchedulerService:
    """Orchestrates scheduler CRUD + dispatch bookkeeping."""

    def __init__(
        self,
        job_repo: ScheduledJobRepository,
        history_repo: ScheduleExecutionHistoryRepository,
    ) -> None:
        self.job_repo = job_repo
        self.history_repo = history_repo

    async def initialize(self) -> None:
        """Ensure underlying tables exist."""
        await self.job_repo.create_table()
        await self.history_repo.create_table()

    # ------------------------------------------------------------------ create
    async def create_schedule(
        self,
        payload: ScheduledJobCreateRequest,
        created_by: str,
    ) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
        """Create a new schedule. Returns `(record, error_message)`."""
        try:
            cron_expression, error = resolve_cron_expression(
                payload.cron_expression, payload.schedule
            )
            if error:
                return None, error

            try:
                resolve_timezone(payload.timezone)
            except ValueError as exc:
                return None, str(exc)

            try:
                next_run = get_next_run(cron_expression, payload.timezone)
            except ValueError as exc:
                return None, str(exc)

            if payload.end_date is not None and next_run > payload.end_date:
                return (
                    None,
                    "Computed next run is after `end_date`; schedule would never fire.",
                )

            row = {
                "job_id": f"sched_{uuid.uuid4().hex[:16]}",
                "schedule_name": payload.schedule_name,
                "description": payload.description,
                "agentic_application_id": payload.agentic_application_id,
                "query": payload.query,
                "model_name": payload.model_name,
                "framework_type": payload.framework_type.value
                if isinstance(payload.framework_type, FrameworkType)
                else str(payload.framework_type),
                "cron_expression": cron_expression,
                "timezone": payload.timezone,
                "is_active": payload.is_active,
                "max_runs": payload.max_runs,
                "max_consecutive_failures": payload.max_consecutive_failures,
                "end_date": payload.end_date,
                "inference_flags": payload.inference_flags.model_dump(),
                "created_by": created_by,
                "next_run_at": next_run if payload.is_active else None,
            }

            created = await self.job_repo.create_job(row)
            if created is None:
                return (
                    None,
                    f"A schedule named '{payload.schedule_name}' already exists "
                    f"for this user.",
                )
            return self._enrich(created), None
        except Exception as exc:
            log.error(f"create_schedule failed: {exc}", exc_info=True)
            return None, f"Internal error while creating schedule: {exc}"

    # -------------------------------------------------------------------- read
    async def get_schedule(self, job_id: str) -> Optional[Dict[str, Any]]:
        try:
            row = await self.job_repo.get_job(job_id)
            return self._enrich(row) if row else None
        except Exception as exc:
            log.error(f"get_schedule failed for '{job_id}': {exc}", exc_info=True)
            return None

    async def list_schedules(
        self,
        viewer_email: str,
        viewer_is_admin: bool,
        only_mine: bool = False,
        only_active: bool = False,
        search_value: Optional[str] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> Tuple[List[Dict[str, Any]], int]:
        """List schedules visible to the viewer.

        - Admins see everyone's schedules unless they pass `only_mine`.
        - Non-admins always see only their own.
        """
        try:
            scope = None if (viewer_is_admin and not only_mine) else viewer_email
            rows = await self.job_repo.list_jobs(
                created_by=scope,
                only_active=only_active,
                search_value=search_value,
                limit=limit,
                offset=offset,
            )
            total = await self.job_repo.count_jobs(
                created_by=scope,
                only_active=only_active,
                search_value=search_value,
            )
            return [self._enrich(r) for r in rows], total
        except Exception as exc:
            log.error(f"list_schedules failed: {exc}", exc_info=True)
            return [], 0

    async def list_upcoming(
        self,
        viewer_email: str,
        viewer_is_admin: bool,
        only_mine: bool = False,
        limit: int = 20,
    ) -> List[Dict[str, Any]]:
        try:
            scope = None if (viewer_is_admin and not only_mine) else viewer_email
            rows = await self.job_repo.list_upcoming(created_by=scope, limit=limit)
            return [self._enrich(r) for r in rows]
        except Exception as exc:
            log.error(f"list_upcoming failed: {exc}", exc_info=True)
            return []

    # ------------------------------------------------------------------ update
    async def update_schedule(
        self,
        job_id: str,
        payload: ScheduledJobUpdateRequest,
    ) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
        try:
            existing = await self.job_repo.get_job(job_id)
            if not existing:
                return None, "Schedule not found."

            updates: Dict[str, Any] = {}

            for column in (
                "schedule_name",
                "description",
                "query",
                "model_name",
                "is_active",
                "max_runs",
                "end_date",
                "max_consecutive_failures",
            ):
                value = getattr(payload, column)
                if value is not None:
                    updates[column] = value

            if payload.framework_type is not None:
                updates["framework_type"] = (
                    payload.framework_type.value
                    if isinstance(payload.framework_type, FrameworkType)
                    else str(payload.framework_type)
                )

            if payload.inference_flags is not None:
                updates["inference_flags"] = payload.inference_flags.model_dump()

            cron_changed = False
            new_cron = existing["cron_expression"]
            new_tz = existing["timezone"]

            if payload.timezone is not None:
                try:
                    resolve_timezone(payload.timezone)
                except ValueError as exc:
                    return None, str(exc)
                new_tz = payload.timezone
                updates["timezone"] = new_tz
                cron_changed = True

            if payload.cron_expression is not None or payload.schedule is not None:
                resolved, error = resolve_cron_expression(
                    payload.cron_expression, payload.schedule
                )
                if error:
                    return None, error
                new_cron = resolved
                updates["cron_expression"] = new_cron
                cron_changed = True

            updated = await self.job_repo.update_job(job_id, updates) if updates else existing
            if updated is None:
                return None, "Update failed (possible name conflict or row gone)."

            # Recompute next_run if timing changed or job was just (re)activated.
            should_recompute = (
                cron_changed
                or (payload.is_active is True and not existing["is_active"])
            )
            if should_recompute and updated["is_active"]:
                try:
                    next_run = get_next_run(new_cron, new_tz)
                    await self.job_repo.reset_next_run(job_id, next_run)
                    updated["next_run_at"] = next_run
                except ValueError as exc:
                    log.warning(
                        f"Updated job '{job_id}' but could not compute next run: {exc}"
                    )

            if payload.is_active is False:
                # Pausing — clear next_run_at so claim_due_jobs ignores it.
                await self.job_repo.reset_next_run(job_id, None)
                updated["next_run_at"] = None

            return self._enrich(updated), None
        except Exception as exc:
            log.error(f"update_schedule failed for '{job_id}': {exc}", exc_info=True)
            return None, f"Internal error while updating schedule: {exc}"

    async def set_active(self, job_id: str, is_active: bool) -> Tuple[bool, Optional[str]]:
        try:
            existing = await self.job_repo.get_job(job_id)
            if not existing:
                return False, "Schedule not found."

            ok = await self.job_repo.set_active(job_id, is_active)
            if not ok:
                return False, "State change had no effect."

            if is_active:
                try:
                    next_run = get_next_run(
                        existing["cron_expression"], existing["timezone"]
                    )
                    await self.job_repo.reset_next_run(job_id, next_run)
                except ValueError as exc:
                    log.warning(
                        f"Resumed job '{job_id}' but next-run computation failed: {exc}"
                    )
            else:
                await self.job_repo.reset_next_run(job_id, None)
            return True, None
        except Exception as exc:
            log.error(f"set_active failed for '{job_id}': {exc}", exc_info=True)
            return False, f"Internal error: {exc}"

    async def delete_schedule(self, job_id: str, hard: bool = False) -> Tuple[bool, Optional[str]]:
        try:
            existing = await self.job_repo.get_job(job_id, include_deleted=hard)
            if not existing:
                return False, "Schedule not found."
            ok = await self.job_repo.delete_job(job_id, hard=hard)
            return (ok, None) if ok else (False, "Delete had no effect.")
        except Exception as exc:
            log.error(
                f"delete_schedule failed for '{job_id}' (hard={hard}): {exc}",
                exc_info=True,
            )
            return False, f"Internal error: {exc}"

    # ----------------------------------------------------------------- history
    async def list_history(
        self, job_id: str, limit: int = 50, offset: int = 0
    ) -> Tuple[List[Dict[str, Any]], int]:
        try:
            rows = await self.history_repo.list_for_job(job_id, limit=limit, offset=offset)
            total = await self.history_repo.count_for_job(job_id)
            return rows, total
        except Exception as exc:
            log.error(
                f"list_history failed for '{job_id}': {exc}", exc_info=True
            )
            return [], 0

    async def get_execution(self, execution_id: str) -> Optional[Dict[str, Any]]:
        try:
            return await self.history_repo.get_execution(execution_id)
        except Exception as exc:
            log.error(
                f"get_execution failed for '{execution_id}': {exc}", exc_info=True
            )
            return None

    # ----------------------------------------------------------------- preview
    def preview_runs(
        self, cron_expression: str, timezone_name: str, count: Optional[int] = None
    ) -> Tuple[List[datetime], Optional[str]]:
        try:
            n = count or CronSchedulerConfig.VALIDATE_PREVIEW_COUNT
            return get_next_n_runs(cron_expression, timezone_name, n), None
        except ValueError as exc:
            return [], str(exc)
        except Exception as exc:
            log.error(f"preview_runs failed: {exc}", exc_info=True)
            return [], f"Internal error: {exc}"

    # -------------------------------------------------------- runner-only APIs
    async def claim_due_jobs(self, now_utc: Optional[datetime] = None) -> List[Dict[str, Any]]:
        """Used by the background runner only."""
        try:
            now = now_utc or datetime.now(timezone.utc)
            return await self.job_repo.claim_due_jobs(
                now, CronSchedulerConfig.MAX_JOBS_PER_POLL
            )
        except Exception as exc:
            log.error(f"claim_due_jobs failed: {exc}", exc_info=True)
            return []

    async def record_execution_attempt(
        self,
        job: Dict[str, Any],
        task_id: str,
        session_id: str,
        scheduled_at: datetime,
    ) -> Optional[str]:
        """Insert a 'queued' history row right before Kafka dispatch."""
        try:
            return await self.history_repo.insert_execution(
                {
                    "job_id": job["job_id"],
                    "task_id": task_id,
                    "session_id": session_id,
                    "status": ScheduleExecutionStatus.QUEUED.value,
                    "scheduled_at": scheduled_at,
                }
            )
        except Exception as exc:
            log.error(
                f"record_execution_attempt failed for job '{job.get('job_id')}': {exc}",
                exc_info=True,
            )
            return None

    async def finalize_dispatch_success(
        self, job: Dict[str, Any], execution_id: Optional[str], dispatched_at: datetime
    ) -> None:
        """Update bookkeeping after a successful Kafka publish.

        Note: 'dispatched' here means the request was handed off to Kafka — the
        actual agent execution outcome is recorded later by the worker.
        """
        try:
            if execution_id:
                await self.history_repo.update_execution_status(
                    execution_id,
                    status=ScheduleExecutionStatus.DISPATCHED.value,
                    dispatched_at=dispatched_at,
                )

            new_run_count = (job.get("run_count") or 0) + 1
            auto_disable = bool(
                job.get("max_runs") and new_run_count >= job["max_runs"]
            ) or bool(
                job.get("end_date")
                and datetime.now(timezone.utc) >= job["end_date"]
            )

            next_run: Optional[datetime] = None
            if not auto_disable:
                try:
                    candidate = get_next_run(
                        job["cron_expression"], job.get("timezone") or "Asia/Kolkata"
                    )
                    if job.get("end_date") and candidate > job["end_date"]:
                        auto_disable = True
                    else:
                        next_run = candidate
                except ValueError as exc:
                    log.warning(
                        f"Could not compute next run for job '{job['job_id']}' "
                        f"after success: {exc}"
                    )

            await self.job_repo.record_dispatch_success(
                job_id=job["job_id"],
                next_run_at=next_run,
                last_run_at=dispatched_at,
                auto_disable=auto_disable,
            )
        except Exception as exc:
            log.error(
                f"finalize_dispatch_success failed for job '{job.get('job_id')}': {exc}",
                exc_info=True,
            )

    async def finalize_dispatch_failure(
        self,
        job: Dict[str, Any],
        execution_id: Optional[str],
        error_message: str,
        attempted_at: datetime,
    ) -> None:
        """Update bookkeeping after a failed Kafka publish."""
        try:
            if execution_id:
                await self.history_repo.update_execution_status(
                    execution_id,
                    status=ScheduleExecutionStatus.FAILED.value,
                    completed_at=attempted_at,
                    error_message=error_message,
                )

            next_run: Optional[datetime] = None
            try:
                next_run = get_next_run(
                    job["cron_expression"], job.get("timezone") or "Asia/Kolkata"
                )
            except ValueError as exc:
                log.warning(
                    f"Could not compute next run for failed job "
                    f"'{job['job_id']}': {exc}"
                )

            await self.job_repo.record_dispatch_failure(
                job_id=job["job_id"],
                next_run_at=next_run,
                last_run_at=attempted_at,
                max_consecutive_failures=job.get("max_consecutive_failures")
                or CronSchedulerConfig.DEFAULT_MAX_CONSECUTIVE_FAILURES,
            )
        except Exception as exc:
            log.error(
                f"finalize_dispatch_failure failed for job '{job.get('job_id')}': {exc}",
                exc_info=True,
            )

    async def purge_history(self) -> int:
        try:
            return await self.history_repo.purge_older_than(
                CronSchedulerConfig.HISTORY_RETENTION_DAYS
            )
        except Exception as exc:
            log.error(f"purge_history failed: {exc}", exc_info=True)
            return 0

    async def finalize_worker_outcome(
        self,
        task_id: str,
        success: bool,
        error_message: Optional[str] = None,
    ) -> bool:
        """Worker-side hook: record the actual execution outcome.

        Called by the agent worker (`AgentWorker._process_and_publish`) once
        the agent finishes running for a `task_id` produced by the cron
        dispatcher (i.e. starts with `cron_`).
        """
        try:
            status = (
                ScheduleExecutionStatus.SUCCEEDED.value
                if success
                else ScheduleExecutionStatus.FAILED.value
            )
            job_id = await self.history_repo.update_outcome_by_task_id(
                task_id=task_id,
                status=status,
                completed_at=datetime.now(timezone.utc),
                error_message=error_message if not success else None,
            )
            if job_id is None:
                # No matching row in queued/dispatched \u2014 nothing to roll up.
                return False

            # Roll the outcome up into scheduled_jobs so success/failure
            # counters and the auto-pause threshold reflect what the agent
            # actually did (not just what Kafka publish did).
            try:
                if success:
                    await self.job_repo.record_worker_success(job_id=job_id)
                else:
                    job = await self.job_repo.get_job(job_id)
                    if job is not None:
                        await self.job_repo.record_worker_failure(
                            job_id=job_id,
                            max_consecutive_failures=(
                                job.get("max_consecutive_failures")
                                or CronSchedulerConfig.DEFAULT_MAX_CONSECUTIVE_FAILURES
                            ),
                        )
            except Exception as exc:
                log.error(
                    f"Could not roll up worker outcome for job '{job_id}' "
                    f"(task '{task_id}', success={success}): {exc}",
                    exc_info=True,
                )
            return True
        except Exception as exc:
            log.error(
                f"finalize_worker_outcome failed for task '{task_id}': {exc}",
                exc_info=True,
            )
            return False

    # ----------------------------------------------------------------- helpers
    def _enrich(self, row: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        """Attach a human-readable description of the cron expression."""
        if row is None:
            return None
        try:
            row.setdefault(
                "human_readable", describe_cron_expression(row["cron_expression"])
            )
        except Exception:  # description is optional, never fail enrichment
            row.setdefault("human_readable", None)
        # Reverse-map the cron expression to a structured form when possible.
        try:
            structured = parse_cron_to_structured(row.get("cron_expression"))
            row["schedule"] = structured.model_dump() if structured else None
        except Exception:
            row["schedule"] = None
        # Normalize inference_flags shape for response model.
        flags = row.get("inference_flags") or {}
        if isinstance(flags, dict):
            try:
                row["inference_flags"] = InferenceFlags(**flags).model_dump()
            except Exception:
                row["inference_flags"] = InferenceFlags().model_dump()
        return row
