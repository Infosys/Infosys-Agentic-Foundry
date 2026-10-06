# © 2024-25 Infosys Limited, Bangalore, India. All Rights Reserved.
import json
import asyncpg
from typing import Dict, Any, Optional

from telemetry_wrapper import logger as log
from src.database.repositories import BaseRepository


class AsyncTaskRepository(BaseRepository):
    """
    Repository for the flag-based async response mode.

    Stores one row per async endpoint invocation (agent onboarding, tool
    onboarding, inference, etc.). The row is created at submission time with
    status 'queued', flipped to 'processing' when a worker slot is acquired,
    and finally set to 'completed' (with the JSON result) or 'failed' (with the
    error). Clients poll by task_id. This is deliberately independent of the
    M2M task_registry table, which is tied to the message-queue subsystem.
    """

    TABLE_NAME = "async_tasks"

    def __init__(self, pool: asyncpg.Pool, login_pool: asyncpg.Pool):
        super().__init__(pool, login_pool, table_name=self.TABLE_NAME)

    async def create_table(self):
        """Creates the async_tasks table if it doesn't exist."""
        create_sql = f"""
        CREATE TABLE IF NOT EXISTS {self.TABLE_NAME} (
            task_id TEXT PRIMARY KEY,
            task_type TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'queued',
            result JSONB,
            error TEXT,
            created_by TEXT,
            created_at TIMESTAMPTZ DEFAULT NOW(),
            started_at TIMESTAMPTZ,
            completed_at TIMESTAMPTZ,
            expires_at TIMESTAMPTZ
        );
        CREATE INDEX IF NOT EXISTS idx_async_tasks_status ON {self.TABLE_NAME}(status);
        CREATE INDEX IF NOT EXISTS idx_async_tasks_created_by ON {self.TABLE_NAME}(created_by);
        CREATE INDEX IF NOT EXISTS idx_async_tasks_expires_at ON {self.TABLE_NAME}(expires_at);
        """
        try:
            async with self.pool.acquire() as conn:
                await conn.execute(create_sql)
            log.info(f"Table '{self.TABLE_NAME}' created successfully or already exists.")
        except Exception as e:
            log.error(f"Error creating table '{self.TABLE_NAME}': {e}")
            raise

    async def create_task(self, task_id: str, task_type: str, created_by: str = None) -> bool:
        """Inserts a new task row with 'queued' status."""
        insert_sql = f"""
        INSERT INTO {self.TABLE_NAME} (task_id, task_type, status, created_by)
        VALUES ($1, $2, 'queued', $3)
        """
        try:
            async with self.pool.acquire() as conn:
                await conn.execute(insert_sql, task_id, task_type, created_by)
            return True
        except Exception as e:
            log.error(f"Error creating async task '{task_id}': {e}")
            return False

    async def mark_processing(self, task_id: str) -> bool:
        """Flips a task to 'processing' once a worker slot is acquired."""
        update_sql = f"""
        UPDATE {self.TABLE_NAME}
        SET status = 'processing', started_at = NOW()
        WHERE task_id = $1
        """
        try:
            async with self.pool.acquire() as conn:
                result = await conn.execute(update_sql, task_id)
            return "UPDATE 1" in result
        except Exception as e:
            log.error(f"Error marking async task '{task_id}' as processing: {e}")
            return False

    async def mark_completed(self, task_id: str, result: Any, retention_hours: float = 24) -> bool:
        """Stores the final result and marks the task 'completed'."""
        update_sql = f"""
        UPDATE {self.TABLE_NAME}
        SET status = 'completed', completed_at = NOW(),
            result = $2::jsonb, expires_at = NOW() + ($3 || ' hours')::interval
        WHERE task_id = $1
        """
        try:
            async with self.pool.acquire() as conn:
                res = await conn.execute(update_sql, task_id, json.dumps(result, default=str), str(retention_hours))
            log.info(f"Async task '{task_id}' marked as completed.")
            return "UPDATE 1" in res
        except Exception as e:
            log.error(f"Error marking async task '{task_id}' as completed: {e}")
            return False

    async def mark_failed(self, task_id: str, error_message: str, retention_hours: float = 24) -> bool:
        """Stores the error and marks the task 'failed'."""
        update_sql = f"""
        UPDATE {self.TABLE_NAME}
        SET status = 'failed', completed_at = NOW(),
            error = $2, expires_at = NOW() + ($3 || ' hours')::interval
        WHERE task_id = $1
        """
        try:
            async with self.pool.acquire() as conn:
                res = await conn.execute(update_sql, task_id, error_message, str(retention_hours))
            log.error(f"Async task '{task_id}' marked as failed: {error_message}")
            return "UPDATE 1" in res
        except Exception as e:
            log.error(f"Error marking async task '{task_id}' as failed: {e}")
            return False

    async def get_task(self, task_id: str) -> Optional[Dict[str, Any]]:
        """Retrieves a task by id. Parses the JSONB result into a Python object."""
        select_sql = f"SELECT * FROM {self.TABLE_NAME} WHERE task_id = $1"
        try:
            async with self.pool.acquire() as conn:
                row = await conn.fetchrow(select_sql, task_id)
            if not row:
                return None
            task = dict(row)
            if isinstance(task.get("result"), str):
                try:
                    task["result"] = json.loads(task["result"])
                except (ValueError, TypeError):
                    pass
            return task
        except Exception as e:
            log.error(f"Error fetching async task '{task_id}': {e}")
            return None

    async def reap_stuck_tasks(self, timeout_minutes: float, retention_hours: float = 24) -> int:
        """
        Marks tasks stuck in 'queued'/'processing' beyond timeout_minutes as
        'failed'. Handles the case where the pod running a task restarted.
        """
        update_sql = f"""
        UPDATE {self.TABLE_NAME}
        SET status = 'failed', completed_at = NOW(),
            error = 'Task timed out or its worker was interrupted.',
            expires_at = NOW() + ($2 || ' hours')::interval
        WHERE status IN ('queued', 'processing')
          AND created_at < NOW() - ($1 || ' minutes')::interval
        """
        try:
            async with self.pool.acquire() as conn:
                result = await conn.execute(update_sql, str(timeout_minutes), str(retention_hours))
            count = int(result.split()[-1]) if result else 0
            if count:
                log.warning(f"Reaper marked {count} stuck async task(s) as failed.")
            return count
        except Exception as e:
            log.error(f"Error reaping stuck async tasks: {e}")
            return 0

    async def delete_expired(self) -> int:
        """Deletes completed/failed task rows whose expires_at has passed."""
        delete_sql = f"""
        DELETE FROM {self.TABLE_NAME}
        WHERE expires_at IS NOT NULL AND expires_at < NOW()
        """
        try:
            async with self.pool.acquire() as conn:
                result = await conn.execute(delete_sql)
            count = int(result.split()[-1]) if result else 0
            if count:
                log.info(f"Cleaned up {count} expired async task(s).")
            return count
        except Exception as e:
            log.error(f"Error cleaning up expired async tasks: {e}")
            return 0

