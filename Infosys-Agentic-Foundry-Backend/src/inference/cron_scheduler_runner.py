# © 2024-25 Infosys Limited, Bangalore, India. All Rights Reserved.
"""Background loops for the cron scheduler subsystem.

Two long-running coroutines are launched from the FastAPI lifespan when
`CronSchedulerConfig.ENABLED` is true:

1. `run_scheduler_loop`        — polls for due jobs and dispatches them.
2. `run_history_cleanup_loop`  — periodically purges old execution rows.

Multi-pod safety: `claim_due_jobs` uses `FOR UPDATE SKIP LOCKED`, so
multiple replicas can run this loop concurrently without double-firing.
"""
from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timezone
from typing import Any, Dict

from src.config.constants import CronSchedulerConfig
from src.database.services.scheduler_service import SchedulerService
from src.database.services import TaskRegistryService
from src.utils.message_queue_factory.message_queue_manager import MessageQueueManager
from telemetry_wrapper import logger as log


async def dispatch_job_now(
    job: Dict[str, Any],
    scheduler_service: SchedulerService,
    task_registry_service: TaskRegistryService,
    mq_manager: MessageQueueManager,
) -> Dict[str, Any]:
    """Dispatch a single claimed job and update bookkeeping.

    Returns a dict ``{task_id, session_id, execution_id, success, error}``
    so the run-now endpoint can surface the result.
    """
    job_id = job["job_id"]
    framework_code = (job.get("framework_type") or "").lower() or "lg"
    task_id = f"cron_{framework_code}_{uuid.uuid4().hex[:12]}"
    session_id = f"{task_id}_{job['created_by']}"
    scheduled_at = datetime.now(timezone.utc)
    flags = job.get("inference_flags") or {}

    execution_id = await scheduler_service.record_execution_attempt(
        job=job,
        task_id=task_id,
        session_id=session_id,
        scheduled_at=scheduled_at,
    )

    try:
        await task_registry_service.register_task(
            task_id=task_id,
            agentic_application_id=job["agentic_application_id"],
            user_session_id=session_id,
            query=job["query"],
            model_name=job["model_name"],
            created_by=job["created_by"],
        )
    except Exception as exc:
        log.error(
            f"[scheduler] Failed to register task '{task_id}' for job '{job_id}': {exc}",
            exc_info=True,
        )
        await scheduler_service.finalize_dispatch_failure(
            job=job,
            execution_id=execution_id,
            error_message=f"Task registration failed: {exc}",
            attempted_at=datetime.now(timezone.utc),
        )
        return {
            "task_id": task_id,
            "session_id": session_id,
            "execution_id": execution_id,
            "success": False,
            "error": f"Task registration failed: {exc}",
        }

    try:
        success = mq_manager.send_agent_request(
            agent_call_id=task_id,
            agentic_application_id=job["agentic_application_id"],
            session_id=session_id,
            model_name=job["model_name"],
            query=job["query"],
            user_email=job["created_by"],
            framework_type=job["framework_type"],
            evaluation_flag=bool(flags.get("evaluation_flag", False)),
            validator_flag=bool(flags.get("validator_flag", False)),
            context_flag=bool(flags.get("context_flag", True)),
            file_context_management_flag=bool(
                flags.get("file_context_management_flag", False)
            ),
            response_formatting_flag=bool(flags.get("response_formatting_flag", False)),
            temperature=flags.get("temperature"),
        )
    except Exception as exc:
        log.error(
            f"[scheduler] Kafka publish raised for job '{job_id}': {exc}",
            exc_info=True,
        )
        success = False
        error_message = str(exc)
    else:
        error_message = None if success else "Kafka publish returned False."

    attempt_finished_at = datetime.now(timezone.utc)
    if success:
        log.info(
            f"[scheduler] Dispatched job '{job_id}' as task '{task_id}' "
            f"(session '{session_id}')."
        )
        await scheduler_service.finalize_dispatch_success(
            job=job,
            execution_id=execution_id,
            dispatched_at=attempt_finished_at,
        )
    else:
        log.warning(
            f"[scheduler] Failed to dispatch job '{job_id}' "
            f"(task '{task_id}'): {error_message}"
        )
        try:
            await task_registry_service.mark_task_failed(
                task_id=task_id, error_message=error_message
            )
        except Exception as exc:
            log.error(
                f"[scheduler] Could not mark task '{task_id}' failed: {exc}",
                exc_info=True,
            )
        await scheduler_service.finalize_dispatch_failure(
            job=job,
            execution_id=execution_id,
            error_message=error_message or "Unknown dispatch error.",
            attempted_at=attempt_finished_at,
        )

    return {
        "task_id": task_id,
        "session_id": session_id,
        "execution_id": execution_id,
        "success": bool(success),
        "error": None if success else error_message,
    }


async def run_scheduler_loop(
    scheduler_service: SchedulerService,
    task_registry_service: TaskRegistryService,
    mq_manager: MessageQueueManager,
) -> None:
    """Forever-loop that claims due jobs and dispatches them via message queue."""
    interval = max(1, CronSchedulerConfig.POLL_INTERVAL_SECONDS)
    log.info(
        f"[scheduler] Loop starting. poll_interval={interval}s "
        f"max_jobs_per_poll={CronSchedulerConfig.MAX_JOBS_PER_POLL}"
    )

    while True:
        try:
            jobs = await scheduler_service.claim_due_jobs()
            if jobs:
                log.info(f"[scheduler] Claimed {len(jobs)} due job(s).")
                for job in jobs:
                    try:
                        await dispatch_job_now(
                            job, scheduler_service, task_registry_service, mq_manager
                        )
                    except Exception as exc:
                        log.error(
                            f"[scheduler] Unhandled error dispatching job "
                            f"'{job.get('job_id')}': {exc}",
                            exc_info=True,
                        )
        except asyncio.CancelledError:
            log.info("[scheduler] Loop cancelled. Exiting.")
            raise
        except Exception as exc:
            log.error(f"[scheduler] Iteration failed: {exc}", exc_info=True)

        try:
            await asyncio.sleep(interval)
        except asyncio.CancelledError:
            log.info("[scheduler] Loop cancelled during sleep. Exiting.")
            raise


async def run_history_cleanup_loop(scheduler_service: SchedulerService) -> None:
    """Forever-loop that purges schedule_execution_history rows older than retention."""
    interval_hours = max(1, CronSchedulerConfig.HISTORY_CLEANUP_INTERVAL_HOURS)
    interval_seconds = interval_hours * 3600
    log.info(
        f"[scheduler] History cleanup loop starting. interval={interval_hours}h "
        f"retention_days={CronSchedulerConfig.HISTORY_RETENTION_DAYS}"
    )

    while True:
        try:
            deleted = await scheduler_service.purge_history()
            if deleted:
                log.info(f"[scheduler] History cleanup deleted {deleted} row(s).")
        except asyncio.CancelledError:
            log.info("[scheduler] History cleanup loop cancelled. Exiting.")
            raise
        except Exception as exc:
            log.error(f"[scheduler] History cleanup failed: {exc}", exc_info=True)

        try:
            await asyncio.sleep(interval_seconds)
        except asyncio.CancelledError:
            log.info("[scheduler] History cleanup cancelled during sleep. Exiting.")
            raise
