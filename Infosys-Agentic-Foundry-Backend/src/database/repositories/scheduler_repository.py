# © 2024-25 Infosys Limited, Bangalore, India. All Rights Reserved.
"""Repositories for the cron scheduler subsystem.

Two tables, both stored in the main DB:

* `scheduled_jobs`             — one row per schedule (CRUD target).
* `schedule_execution_history` — append-only audit of every dispatch attempt.

Multi-pod safety is achieved via `SELECT ... FOR UPDATE SKIP LOCKED` on the
`scheduled_jobs` table when claiming due jobs. The lock is held only for
the duration of the claim transaction, during which `next_run_at` is
advanced — so other pods naturally skip the same row on their next poll.
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

import asyncpg

from src.config.constants import TableNames
from src.database.repositories import BaseRepository
from telemetry_wrapper import logger as log


# ---------------------------------------------------------------------------
# Scheduled Jobs
# ---------------------------------------------------------------------------


class ScheduledJobRepository(BaseRepository):
    """CRUD + due-job claim operations for `scheduled_jobs`."""

    TABLE_NAME = TableNames.SCHEDULED_JOBS.value

    def __init__(self, pool: asyncpg.Pool, login_pool: asyncpg.Pool):
        super().__init__(pool, login_pool, table_name=self.TABLE_NAME)

    async def create_table(self) -> None:
        """Create the `scheduled_jobs` table and supporting indexes.

        `agentic_application_id` has an `ON DELETE CASCADE` foreign key to
        the agents table — if the parent agent is deleted (hard delete from
        the main agent table; recycle-bin moves count as deletes), every
        schedule referencing it is removed automatically, and the cascade
        continues through to the per-job rows in `schedule_execution_history`.
        """
        create_sql = f"""
        CREATE TABLE IF NOT EXISTS {self.TABLE_NAME} (
            job_id TEXT PRIMARY KEY,
            schedule_name TEXT NOT NULL,
            description TEXT,
            agentic_application_id TEXT NOT NULL
                REFERENCES {TableNames.AGENT.value}(agentic_application_id)
                ON DELETE CASCADE,
            query TEXT NOT NULL,
            model_name TEXT NOT NULL,
            framework_type TEXT NOT NULL,
            cron_expression TEXT NOT NULL,
            timezone TEXT NOT NULL DEFAULT 'Asia/Kolkata',
            is_active BOOLEAN NOT NULL DEFAULT TRUE,
            is_deleted BOOLEAN NOT NULL DEFAULT FALSE,
            max_runs INTEGER,
            run_count INTEGER NOT NULL DEFAULT 0,
            success_count INTEGER NOT NULL DEFAULT 0,
            failure_count INTEGER NOT NULL DEFAULT 0,
            consecutive_failure_count INTEGER NOT NULL DEFAULT 0,
            max_consecutive_failures INTEGER NOT NULL DEFAULT 5,
            end_date TIMESTAMPTZ,
            inference_flags JSONB NOT NULL DEFAULT '{{}}'::jsonb,
            created_by TEXT NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ,
            last_run_at TIMESTAMPTZ,
            next_run_at TIMESTAMPTZ
        );
        CREATE INDEX IF NOT EXISTS idx_scheduled_jobs_due
            ON {self.TABLE_NAME}(next_run_at)
            WHERE is_active = TRUE AND is_deleted = FALSE;
        CREATE INDEX IF NOT EXISTS idx_scheduled_jobs_created_by
            ON {self.TABLE_NAME}(created_by);
        CREATE INDEX IF NOT EXISTS idx_scheduled_jobs_agent
            ON {self.TABLE_NAME}(agentic_application_id);
        CREATE UNIQUE INDEX IF NOT EXISTS uq_scheduled_jobs_name_per_user
            ON {self.TABLE_NAME}(created_by, schedule_name)
            WHERE is_deleted = FALSE;
        """
        try:
            async with self.pool.acquire() as conn:
                await conn.execute(create_sql)
            log.info(f"Table '{self.TABLE_NAME}' is ready.")
        except Exception as exc:
            log.error(f"Failed to create table '{self.TABLE_NAME}': {exc}", exc_info=True)
            raise

    # ------------------------------------------------------------------ create
    async def create_job(self, payload: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Insert a new scheduled job. Returns the created row (or None on failure)."""
        insert_sql = f"""
        INSERT INTO {self.TABLE_NAME} (
            job_id, schedule_name, description, agentic_application_id, query,
            model_name, framework_type, cron_expression, timezone, is_active,
            max_runs, max_consecutive_failures, end_date, inference_flags,
            created_by, next_run_at
        ) VALUES (
            $1, $2, $3, $4, $5,
            $6, $7, $8, $9, $10,
            $11, $12, $13, $14::jsonb,
            $15, $16
        )
        RETURNING *;
        """
        try:
            async with self.pool.acquire() as conn:
                row = await conn.fetchrow(
                    insert_sql,
                    payload["job_id"],
                    payload["schedule_name"],
                    payload.get("description"),
                    payload["agentic_application_id"],
                    payload["query"],
                    payload["model_name"],
                    payload["framework_type"],
                    payload["cron_expression"],
                    payload.get("timezone", "Asia/Kolkata"),
                    payload.get("is_active", True),
                    payload.get("max_runs"),
                    payload.get("max_consecutive_failures", 5),
                    payload.get("end_date"),
                    json.dumps(payload.get("inference_flags") or {}),
                    payload["created_by"],
                    payload.get("next_run_at"),
                )
            log.info(
                f"Scheduled job '{payload['job_id']}' "
                f"('{payload['schedule_name']}') created by {payload['created_by']}."
            )
            return _row_to_dict(row)
        except asyncpg.UniqueViolationError as exc:
            log.warning(
                f"Schedule name '{payload.get('schedule_name')}' already exists "
                f"for user {payload.get('created_by')}: {exc}"
            )
            return None
        except Exception as exc:
            log.error(
                f"Failed to insert scheduled job '{payload.get('job_id')}': {exc}",
                exc_info=True,
            )
            return None

    # -------------------------------------------------------------------- read
    async def get_job(self, job_id: str, include_deleted: bool = False) -> Optional[Dict[str, Any]]:
        """Fetch a single job by id."""
        clause = "" if include_deleted else " AND is_deleted = FALSE"
        sql = f"SELECT * FROM {self.TABLE_NAME} WHERE job_id = $1{clause}"
        try:
            async with self.pool.acquire() as conn:
                row = await conn.fetchrow(sql, job_id)
            return _row_to_dict(row) if row else None
        except Exception as exc:
            log.error(f"Failed to fetch job '{job_id}': {exc}", exc_info=True)
            return None

    async def list_jobs(
        self,
        created_by: Optional[str] = None,
        only_active: bool = False,
        search_value: Optional[str] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> List[Dict[str, Any]]:
        """List jobs (admin: pass `created_by=None`; user: pass their email)."""
        conditions = ["is_deleted = FALSE"]
        params: List[Any] = []
        if created_by is not None:
            params.append(created_by)
            conditions.append(f"created_by = ${len(params)}")
        if only_active:
            conditions.append("is_active = TRUE")
        if search_value:
            params.append(f"%{search_value}%")
            conditions.append(f"schedule_name ILIKE ${len(params)}")

        params.extend([limit, offset])
        sql = (
            f"SELECT * FROM {self.TABLE_NAME} "
            f"WHERE {' AND '.join(conditions)} "
            f"ORDER BY created_at DESC "
            f"LIMIT ${len(params) - 1} OFFSET ${len(params)}"
        )
        try:
            async with self.pool.acquire() as conn:
                rows = await conn.fetch(sql, *params)
            return [_row_to_dict(r) for r in rows]
        except Exception as exc:
            log.error(f"Failed to list scheduled jobs: {exc}", exc_info=True)
            return []

    async def count_jobs(
        self,
        created_by: Optional[str] = None,
        only_active: bool = False,
        search_value: Optional[str] = None,
    ) -> int:
        """Total count matching the same filters as `list_jobs`."""
        conditions = ["is_deleted = FALSE"]
        params: List[Any] = []
        if created_by is not None:
            params.append(created_by)
            conditions.append(f"created_by = ${len(params)}")
        if only_active:
            conditions.append("is_active = TRUE")
        if search_value:
            params.append(f"%{search_value}%")
            conditions.append(f"schedule_name ILIKE ${len(params)}")
        sql = (
            f"SELECT COUNT(*) FROM {self.TABLE_NAME} "
            f"WHERE {' AND '.join(conditions)}"
        )
        try:
            async with self.pool.acquire() as conn:
                value = await conn.fetchval(sql, *params)
            return int(value or 0)
        except Exception as exc:
            log.error(f"Failed to count scheduled jobs: {exc}", exc_info=True)
            return 0

    async def list_upcoming(
        self, created_by: Optional[str] = None, limit: int = 20
    ) -> List[Dict[str, Any]]:
        """Return active jobs sorted by `next_run_at` ascending."""
        conditions = [
            "is_deleted = FALSE",
            "is_active = TRUE",
            "next_run_at IS NOT NULL",
        ]
        params: List[Any] = []
        if created_by is not None:
            params.append(created_by)
            conditions.append(f"created_by = ${len(params)}")
        params.append(limit)
        sql = (
            f"SELECT * FROM {self.TABLE_NAME} "
            f"WHERE {' AND '.join(conditions)} "
            f"ORDER BY next_run_at ASC "
            f"LIMIT ${len(params)}"
        )
        try:
            async with self.pool.acquire() as conn:
                rows = await conn.fetch(sql, *params)
            return [_row_to_dict(r) for r in rows]
        except Exception as exc:
            log.error(f"Failed to list upcoming jobs: {exc}", exc_info=True)
            return []

    # ------------------------------------------------------------------ update
    async def update_job(
        self, job_id: str, updates: Dict[str, Any]
    ) -> Optional[Dict[str, Any]]:
        """Apply a partial update. `updates` keys must already be vetted."""
        if not updates:
            return await self.get_job(job_id)

        set_clauses: List[str] = []
        params: List[Any] = []
        for column, value in updates.items():
            params.append(
                json.dumps(value) if column == "inference_flags" and value is not None else value
            )
            cast = "::jsonb" if column == "inference_flags" else ""
            set_clauses.append(f"{column} = ${len(params)}{cast}")

        set_clauses.append("updated_at = NOW()")
        params.append(job_id)
        sql = (
            f"UPDATE {self.TABLE_NAME} SET {', '.join(set_clauses)} "
            f"WHERE job_id = ${len(params)} AND is_deleted = FALSE "
            f"RETURNING *"
        )
        try:
            async with self.pool.acquire() as conn:
                row = await conn.fetchrow(sql, *params)
            if row:
                log.info(f"Scheduled job '{job_id}' updated. Columns: {list(updates.keys())}")
                return _row_to_dict(row)
            log.warning(f"Update on job '{job_id}' affected zero rows.")
            return None
        except asyncpg.UniqueViolationError as exc:
            log.warning(f"Update on job '{job_id}' violated unique constraint: {exc}")
            return None
        except Exception as exc:
            log.error(f"Failed to update job '{job_id}': {exc}", exc_info=True)
            return None

    async def set_active(self, job_id: str, is_active: bool) -> bool:
        """Pause or resume a job. Returns True iff a row was updated."""
        sql = (
            f"UPDATE {self.TABLE_NAME} SET is_active = $1, updated_at = NOW() "
            f"WHERE job_id = $2 AND is_deleted = FALSE"
        )
        try:
            async with self.pool.acquire() as conn:
                result = await conn.execute(sql, is_active, job_id)
            updated = "UPDATE 1" in result
            log.info(
                f"Scheduled job '{job_id}' set active={is_active}. updated={updated}"
            )
            return updated
        except Exception as exc:
            log.error(
                f"Failed to set active={is_active} on job '{job_id}': {exc}",
                exc_info=True,
            )
            return False

    async def delete_job(self, job_id: str, hard: bool = False) -> bool:
        """Soft-delete (default) or hard-delete a job."""
        try:
            async with self.pool.acquire() as conn:
                if hard:
                    result = await conn.execute(
                        f"DELETE FROM {self.TABLE_NAME} WHERE job_id = $1", job_id
                    )
                else:
                    result = await conn.execute(
                        f"UPDATE {self.TABLE_NAME} SET is_deleted = TRUE, "
                        f"is_active = FALSE, updated_at = NOW() "
                        f"WHERE job_id = $1 AND is_deleted = FALSE",
                        job_id,
                    )
            deleted = "1" in result.split()[-1] if result else False
            log.info(f"Scheduled job '{job_id}' deleted (hard={hard}). result='{result}'")
            return deleted
        except Exception as exc:
            log.error(
                f"Failed to delete job '{job_id}' (hard={hard}): {exc}",
                exc_info=True,
            )
            return False

    # ------------------------------------------------------------------- claim
    async def claim_due_jobs(self, now_utc: datetime, limit: int) -> List[Dict[str, Any]]:
        """Atomically claim due jobs using `FOR UPDATE SKIP LOCKED`.

        Each claimed row's `next_run_at` is set to NULL inside the same
        transaction so other pods will not re-claim it. The caller is
        responsible for computing and persisting the new `next_run_at`
        once the schedule actually fires.
        """
        select_sql = (
            f"SELECT * FROM {self.TABLE_NAME} "
            f"WHERE is_active = TRUE AND is_deleted = FALSE "
            f"AND next_run_at IS NOT NULL AND next_run_at <= $1 "
            f"ORDER BY next_run_at ASC "
            f"LIMIT $2 "
            f"FOR UPDATE SKIP LOCKED"
        )
        update_sql = (
            f"UPDATE {self.TABLE_NAME} SET next_run_at = NULL "
            f"WHERE job_id = ANY($1::text[])"
        )
        try:
            async with self.pool.acquire() as conn:
                async with conn.transaction():
                    rows = await conn.fetch(select_sql, now_utc, limit)
                    if not rows:
                        return []
                    job_ids = [r["job_id"] for r in rows]
                    await conn.execute(update_sql, job_ids)
            return [_row_to_dict(r) for r in rows]
        except Exception as exc:
            log.error(f"Failed to claim due scheduled jobs: {exc}", exc_info=True)
            return []

    async def record_dispatch_success(
        self,
        job_id: str,
        next_run_at: Optional[datetime],
        last_run_at: datetime,
        auto_disable: bool,
    ) -> bool:
        """Update bookkeeping after a successful Kafka publish.

        At this point we only know the request was handed off to Kafka —
        the actual agent execution outcome is unknown. So we deliberately
        do NOT touch `success_count` or `consecutive_failure_count` here;
        those are managed by the worker callback (`record_worker_success`
        / `record_worker_failure`) once the agent actually finishes.
        Otherwise every cycle would reset the consecutive-failure counter
        and auto-pause on `max_consecutive_failures` could never trip.
        """
        sql = (
            f"UPDATE {self.TABLE_NAME} SET "
            f"  next_run_at = $2, last_run_at = $3, "
            f"  run_count = run_count + 1, "
            f"  is_active = CASE WHEN $4 THEN FALSE ELSE is_active END, "
            f"  updated_at = NOW() "
            f"WHERE job_id = $1"
        )
        try:
            async with self.pool.acquire() as conn:
                result = await conn.execute(
                    sql, job_id, next_run_at, last_run_at, auto_disable
                )
            return "UPDATE 1" in result
        except Exception as exc:
            log.error(
                f"Failed to record dispatch success for job '{job_id}': {exc}",
                exc_info=True,
            )
            return False

    async def record_dispatch_failure(
        self,
        job_id: str,
        next_run_at: Optional[datetime],
        last_run_at: datetime,
        max_consecutive_failures: int,
    ) -> bool:
        """Update bookkeeping after a failed dispatch.

        Increments `consecutive_failure_count`; if it reaches
        `max_consecutive_failures` the job is auto-paused.
        """
        sql = (
            f"UPDATE {self.TABLE_NAME} SET "
            f"  next_run_at = $2, last_run_at = $3, "
            f"  run_count = run_count + 1, failure_count = failure_count + 1, "
            f"  consecutive_failure_count = consecutive_failure_count + 1, "
            f"  is_active = CASE "
            f"    WHEN consecutive_failure_count + 1 >= $4 THEN FALSE "
            f"    ELSE is_active END, "
            f"  updated_at = NOW() "
            f"WHERE job_id = $1"
        )
        try:
            async with self.pool.acquire() as conn:
                result = await conn.execute(
                    sql, job_id, next_run_at, last_run_at, max_consecutive_failures
                )
            return "UPDATE 1" in result
        except Exception as exc:
            log.error(
                f"Failed to record dispatch failure for job '{job_id}': {exc}",
                exc_info=True,
            )
            return False

    async def record_worker_failure(
        self,
        job_id: str,
        max_consecutive_failures: int,
    ) -> bool:
        """Record a worker-reported agent failure.

        Bumps `failure_count` and `consecutive_failure_count`, auto-pausing
        the job once the counter crosses `max_consecutive_failures`.
        Does NOT touch `run_count`, `next_run_at`, or `last_run_at` — the
        attempt already happened and the dispatcher already scheduled the
        next run at publish time.
        """
        sql = (
            f"UPDATE {self.TABLE_NAME} SET "
            f"  failure_count = failure_count + 1, "
            f"  consecutive_failure_count = consecutive_failure_count + 1, "
            f"  is_active = CASE "
            f"    WHEN consecutive_failure_count + 1 >= $2 THEN FALSE "
            f"    ELSE is_active END, "
            f"  updated_at = NOW() "
            f"WHERE job_id = $1"
        )
        try:
            async with self.pool.acquire() as conn:
                result = await conn.execute(
                    sql, job_id, max_consecutive_failures
                )
            return "UPDATE 1" in result
        except Exception as exc:
            log.error(
                f"Failed to record worker failure for job '{job_id}': {exc}",
                exc_info=True,
            )
            return False

    async def record_worker_success(self, job_id: str) -> bool:
        """Record a worker-reported agent success.

        Bumps `success_count` and resets `consecutive_failure_count` to 0.
        Does NOT touch `run_count`, `next_run_at`, or `last_run_at`.
        """
        sql = (
            f"UPDATE {self.TABLE_NAME} SET "
            f"  success_count = success_count + 1, "
            f"  consecutive_failure_count = 0, "
            f"  updated_at = NOW() "
            f"WHERE job_id = $1"
        )
        try:
            async with self.pool.acquire() as conn:
                result = await conn.execute(sql, job_id)
            return "UPDATE 1" in result
        except Exception as exc:
            log.error(
                f"Failed to record worker success for job '{job_id}': {exc}",
                exc_info=True,
            )
            return False

    async def reset_next_run(self, job_id: str, next_run_at: Optional[datetime]) -> bool:
        """Set `next_run_at` to a specific value (used after edits)."""
        sql = (
            f"UPDATE {self.TABLE_NAME} SET next_run_at = $2, updated_at = NOW() "
            f"WHERE job_id = $1"
        )
        try:
            async with self.pool.acquire() as conn:
                result = await conn.execute(sql, job_id, next_run_at)
            return "UPDATE 1" in result
        except Exception as exc:
            log.error(
                f"Failed to reset next_run_at for job '{job_id}': {exc}",
                exc_info=True,
            )
            return False


# ---------------------------------------------------------------------------
# Execution History
# ---------------------------------------------------------------------------


class ScheduleExecutionHistoryRepository(BaseRepository):
    """Append-only audit log of every dispatch attempt for every schedule."""

    TABLE_NAME = TableNames.SCHEDULE_EXECUTION_HISTORY.value

    def __init__(self, pool: asyncpg.Pool, login_pool: asyncpg.Pool):
        super().__init__(pool, login_pool, table_name=self.TABLE_NAME)

    async def create_table(self) -> None:
        create_sql = f"""
        CREATE TABLE IF NOT EXISTS {self.TABLE_NAME} (
            execution_id TEXT PRIMARY KEY,
            job_id TEXT NOT NULL
                REFERENCES {TableNames.SCHEDULED_JOBS.value}(job_id)
                ON DELETE CASCADE,
            task_id TEXT,
            session_id TEXT,
            status TEXT NOT NULL,
            scheduled_at TIMESTAMPTZ NOT NULL,
            dispatched_at TIMESTAMPTZ,
            completed_at TIMESTAMPTZ,
            error_message TEXT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
        CREATE INDEX IF NOT EXISTS idx_schedule_history_job
            ON {self.TABLE_NAME}(job_id, scheduled_at DESC);
        CREATE INDEX IF NOT EXISTS idx_schedule_history_status
            ON {self.TABLE_NAME}(status);
        CREATE INDEX IF NOT EXISTS idx_schedule_history_created_at
            ON {self.TABLE_NAME}(created_at);
        CREATE INDEX IF NOT EXISTS idx_schedule_history_task_id
            ON {self.TABLE_NAME}(task_id);
        """
        try:
            async with self.pool.acquire() as conn:
                await conn.execute(create_sql)
            log.info(f"Table '{self.TABLE_NAME}' is ready.")
        except Exception as exc:
            log.error(f"Failed to create table '{self.TABLE_NAME}': {exc}", exc_info=True)
            raise

    async def insert_execution(self, payload: Dict[str, Any]) -> Optional[str]:
        """Insert a new execution row; returns the execution_id."""
        execution_id = payload.get("execution_id") or f"exec_{uuid.uuid4().hex[:16]}"
        insert_sql = f"""
        INSERT INTO {self.TABLE_NAME} (
            execution_id, job_id, task_id, session_id, status,
            scheduled_at, dispatched_at, completed_at, error_message
        ) VALUES (
            $1, $2, $3, $4, $5,
            $6, $7, $8, $9
        )
        """
        try:
            async with self.pool.acquire() as conn:
                await conn.execute(
                    insert_sql,
                    execution_id,
                    payload["job_id"],
                    payload.get("task_id"),
                    payload.get("session_id"),
                    payload["status"],
                    payload["scheduled_at"],
                    payload.get("dispatched_at"),
                    payload.get("completed_at"),
                    payload.get("error_message"),
                )
            return execution_id
        except Exception as exc:
            log.error(
                f"Failed to insert execution row for job '{payload.get('job_id')}': {exc}",
                exc_info=True,
            )
            return None

    async def update_execution_status(
        self,
        execution_id: str,
        status: str,
        dispatched_at: Optional[datetime] = None,
        completed_at: Optional[datetime] = None,
        error_message: Optional[str] = None,
    ) -> bool:
        """Patch an execution row.

        Only the columns whose values are non-None are written, so callers
        can advance the row through QUEUED -> DISPATCHED -> SUCCEEDED /
        FAILED without clobbering earlier timestamps.
        """
        set_clauses: List[str] = ["status = $2"]
        params: List[Any] = [execution_id, status]
        if dispatched_at is not None:
            params.append(dispatched_at)
            set_clauses.append(f"dispatched_at = ${len(params)}")
        if completed_at is not None:
            params.append(completed_at)
            set_clauses.append(f"completed_at = ${len(params)}")
        if error_message is not None:
            params.append(error_message)
            set_clauses.append(f"error_message = ${len(params)}")

        sql = (
            f"UPDATE {self.TABLE_NAME} SET {', '.join(set_clauses)} "
            f"WHERE execution_id = $1"
        )
        try:
            async with self.pool.acquire() as conn:
                result = await conn.execute(sql, *params)
            return "UPDATE 1" in result
        except Exception as exc:
            log.error(
                f"Failed to update execution '{execution_id}' to status '{status}': {exc}",
                exc_info=True,
            )
            return False

    async def update_outcome_by_task_id(
        self,
        task_id: str,
        status: str,
        completed_at: datetime,
        error_message: Optional[str] = None,
    ) -> Optional[str]:
        """Worker-side hook: finalize an execution by `task_id`.

        Returns the `job_id` of the updated row when a row was actually
        transitioned, or `None` if no matching `queued`/`dispatched` row
        was found (idempotent no-op on retries).
        """
        set_clauses: List[str] = ["status = $2", "completed_at = $3"]
        params: List[Any] = [task_id, status, completed_at]
        if error_message is not None:
            params.append(error_message)
            set_clauses.append(f"error_message = ${len(params)}")
        sql = (
            f"UPDATE {self.TABLE_NAME} SET {', '.join(set_clauses)} "
            f"WHERE task_id = $1 AND status IN ('queued', 'dispatched') "
            f"RETURNING job_id"
        )
        try:
            async with self.pool.acquire() as conn:
                row = await conn.fetchrow(sql, *params)
            return row["job_id"] if row else None
        except Exception as exc:
            log.error(
                f"Failed to finalize execution by task_id '{task_id}' "
                f"to status '{status}': {exc}",
                exc_info=True,
            )
            return None

    async def list_for_job(
        self, job_id: str, limit: int = 50, offset: int = 0
    ) -> List[Dict[str, Any]]:
        sql = (
            f"SELECT execution_id, job_id, task_id, session_id, status, "
            f"scheduled_at, dispatched_at, completed_at, error_message "
            f"FROM {self.TABLE_NAME} "
            f"WHERE job_id = $1 ORDER BY scheduled_at DESC LIMIT $2 OFFSET $3"
        )
        try:
            async with self.pool.acquire() as conn:
                rows = await conn.fetch(sql, job_id, limit, offset)
            return [dict(r) for r in rows]
        except Exception as exc:
            log.error(
                f"Failed to list execution history for job '{job_id}': {exc}",
                exc_info=True,
            )
            return []

    async def count_for_job(self, job_id: str) -> int:
        try:
            async with self.pool.acquire() as conn:
                value = await conn.fetchval(
                    f"SELECT COUNT(*) FROM {self.TABLE_NAME} WHERE job_id = $1", job_id
                )
            return int(value or 0)
        except Exception as exc:
            log.error(
                f"Failed to count execution history for job '{job_id}': {exc}",
                exc_info=True,
            )
            return 0

    async def get_execution(self, execution_id: str) -> Optional[Dict[str, Any]]:
        try:
            async with self.pool.acquire() as conn:
                row = await conn.fetchrow(
                    f"SELECT * FROM {self.TABLE_NAME} WHERE execution_id = $1",
                    execution_id,
                )
            return dict(row) if row else None
        except Exception as exc:
            log.error(
                f"Failed to fetch execution '{execution_id}': {exc}", exc_info=True
            )
            return None

    async def purge_older_than(self, retention_days: int) -> int:
        """Delete execution rows older than `retention_days`. Returns row count."""
        cutoff = datetime.now(timezone.utc) - timedelta(days=retention_days)
        sql = f"DELETE FROM {self.TABLE_NAME} WHERE created_at < $1"
        try:
            async with self.pool.acquire() as conn:
                result = await conn.execute(sql, cutoff)
            # `result` looks like 'DELETE <n>'
            try:
                deleted = int(result.split()[-1])
            except (IndexError, ValueError):
                deleted = 0
            log.info(
                f"Schedule history purge complete. cutoff={cutoff.isoformat()} "
                f"deleted={deleted}"
            )
            return deleted
        except Exception as exc:
            log.error(
                f"Failed to purge schedule execution history: {exc}", exc_info=True
            )
            return 0


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _row_to_dict(row: Optional[asyncpg.Record]) -> Optional[Dict[str, Any]]:
    """Convert an asyncpg Record to a plain dict, decoding JSONB string fields."""
    if row is None:
        return None
    data = dict(row)
    flags = data.get("inference_flags")
    if isinstance(flags, str):
        try:
            data["inference_flags"] = json.loads(flags)
        except json.JSONDecodeError:
            log.warning(
                f"Could not decode inference_flags for job '{data.get('job_id')}'."
            )
            data["inference_flags"] = {}
    elif flags is None:
        data["inference_flags"] = {}
    return data
