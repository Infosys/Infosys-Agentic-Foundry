# © 2024-25 Infosys Limited, Bangalore, India. All Rights Reserved.
from typing import Any, Dict

from src.database.repositories.async_task_repository import AsyncTaskRepository
from telemetry_wrapper import logger as log

class AsyncTaskService:
    """
    Service layer for the flag-based async response mode.

    Provides the lifecycle operations used by the `supports_async` decorator and
    the generic polling endpoint: create a task, flip it to processing, store the
    result/error, fetch status, and the reaper/cleanup housekeeping.
    """

    def __init__(self, async_task_repo: AsyncTaskRepository):
        self.repo: AsyncTaskRepository = async_task_repo

    async def initialize(self):
        """Creates the async_tasks table if it doesn't exist."""
        await self.repo.create_table()

    async def create_task(self, task_id: str, task_type: str, created_by: str = None) -> bool:
        """Registers a new async task with 'queued' status."""
        return await self.repo.create_task(task_id=task_id, task_type=task_type, created_by=created_by)

    async def mark_processing(self, task_id: str) -> bool:
        """Marks a task as 'processing' when a worker slot is acquired."""
        return await self.repo.mark_processing(task_id=task_id)

    async def mark_completed(self, task_id: str, result: Any, retention_hours: float = 24) -> bool:
        """Stores the result and marks the task 'completed'."""
        return await self.repo.mark_completed(task_id=task_id, result=result, retention_hours=retention_hours)

    async def mark_failed(self, task_id: str, error_message: str, retention_hours: float = 24) -> bool:
        """Stores the error and marks the task 'failed'."""
        return await self.repo.mark_failed(task_id=task_id, error_message=error_message, retention_hours=retention_hours)

    async def get_task(self, task_id: str, requesting_user: str = None) -> Dict[str, Any]:
        """
        Gets the current status/result of a task.

        If requesting_user is provided, enforces that only the creator can read
        the task (returns a not-authorized error otherwise).
        """
        task = await self.repo.get_task(task_id)
        if not task:
            return {"success": False, "task_id": task_id, "message": f"Task '{task_id}' not found."}

        if requesting_user and task.get("created_by") and task["created_by"] != requesting_user:
            return {"success": False, "task_id": task_id, "message": "You are not authorized to view this task."}

        for key in ("created_at", "started_at", "completed_at", "expires_at"):
            if task.get(key):
                task[key] = str(task[key])

        return {"success": True, **task}

    async def reap_stuck_tasks(self, timeout_minutes: float, retention_hours: float = 24) -> int:
        """Marks orphaned queued/processing tasks as failed."""
        return await self.repo.reap_stuck_tasks(timeout_minutes=timeout_minutes, retention_hours=retention_hours)

    async def cleanup_expired(self) -> int:
        """Deletes expired completed/failed task rows."""
        return await self.repo.delete_expired()

