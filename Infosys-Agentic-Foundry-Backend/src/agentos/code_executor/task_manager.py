"""
Async task manager for Smart Code Executor.

Provides a queue-based system for submitting, polling, and cancelling
long-running code execution tasks. Workers pick tasks off the queue
and execute them asynchronously.
"""

import asyncio
import logging
import uuid
from collections import OrderedDict
from datetime import datetime
from typing import Any, Callable, Coroutine, Dict, List, Optional

from src.agentos.code_executor.config import AsyncConfig
from src.agentos.code_executor.models import Task, TaskResult, TaskStatus

logger = logging.getLogger("agentos.code_executor.task_manager")


class TaskQueue:
    """In-memory async task queue backed by asyncio.Queue + OrderedDict."""

    def __init__(self, max_size: int = 100):
        self._queue: asyncio.Queue = asyncio.Queue(maxsize=max_size)
        self._tasks: OrderedDict[str, Task] = OrderedDict()
        self._max_size = max_size

    async def enqueue(self, task: Task):
        """Add a task to the queue."""
        # Evict oldest completed tasks if at capacity
        while len(self._tasks) >= self._max_size * 2:
            oldest_id = next(iter(self._tasks))
            oldest = self._tasks[oldest_id]
            if oldest.status in (TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELLED):
                del self._tasks[oldest_id]
            else:
                break

        self._tasks[task.task_id] = task
        await self._queue.put(task.task_id)

    async def dequeue(self, timeout: float = 1.0) -> Optional[str]:
        """Get the next task ID from the queue, with timeout."""
        try:
            task_id = await asyncio.wait_for(self._queue.get(), timeout=timeout)
            return task_id
        except asyncio.TimeoutError:
            return None

    def get_task(self, task_id: str) -> Optional[Task]:
        return self._tasks.get(task_id)

    def update_task(self, task: Task):
        if task.task_id in self._tasks:
            self._tasks[task.task_id] = task

    def list_tasks(self, tenant_id: Optional[str] = None) -> List[Task]:
        tasks = list(self._tasks.values())
        if tenant_id:
            tasks = [t for t in tasks if t.tenant_id == tenant_id]
        return tasks

    def cleanup_old(self, max_age_seconds: int = 3600):
        """Remove completed/failed/cancelled tasks older than threshold."""
        now = datetime.utcnow()
        to_remove = []
        for task_id, task in self._tasks.items():
            if task.status in (TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELLED):
                if task.completed_at:
                    try:
                        completed = datetime.fromisoformat(task.completed_at)
                        if (now - completed).total_seconds() > max_age_seconds:
                            to_remove.append(task_id)
                    except ValueError:
                        pass
        for task_id in to_remove:
            del self._tasks[task_id]
        if to_remove:
            logger.info(f"Cleaned up {len(to_remove)} old tasks")


class TaskManager:
    """
    Manages async code execution tasks.

    Submits tasks to a queue, spawns background workers that execute them,
    and provides status polling + cancellation.
    """

    def __init__(
        self,
        config: AsyncConfig,
        executor_func: Callable[..., Coroutine[Any, Any, TaskResult]],
    ):
        """
        Args:
            config: Async configuration.
            executor_func: Coroutine that takes (goal, tenant_id, files, language)
                          and returns a TaskResult.
        """
        self.config = config
        self._executor_func = executor_func
        self._queue = TaskQueue(max_size=config.max_queue_size)
        self._workers: List[asyncio.Task] = []
        self._cancel_events: Dict[str, asyncio.Event] = {}
        self._running = False

    async def start(self):
        """Start background worker tasks."""
        if self._running:
            return
        self._running = True
        for i in range(self.config.worker_count):
            worker = asyncio.create_task(self._worker_loop(i))
            self._workers.append(worker)
        logger.info(f"TaskManager started with {self.config.worker_count} workers")

    async def stop(self):
        """Stop all workers."""
        self._running = False
        for worker in self._workers:
            worker.cancel()
        if self._workers:
            await asyncio.gather(*self._workers, return_exceptions=True)
        self._workers.clear()
        logger.info("TaskManager stopped")

    async def submit_task(
        self,
        goal: str,
        tenant_id: str = "default",
        files: Optional[Dict[str, str]] = None,
        language: Optional[str] = None,
    ) -> Task:
        """
        Submit a new task for async execution.

        Returns:
            Task object with task_id for polling.
        """
        task = Task(
            task_id=str(uuid.uuid4()),
            tenant_id=tenant_id,
            goal=goal,
            status=TaskStatus.QUEUED,
            language=language,
            files=files,
        )

        # Set up cancel event
        self._cancel_events[task.task_id] = asyncio.Event()

        await self._queue.enqueue(task)
        logger.info(f"Task {task.task_id} queued for: {goal[:80]}")
        return task

    async def get_status(self, task_id: str, tenant_id: Optional[str] = None) -> Optional[Dict]:
        """Get task status. Enforces tenant isolation if tenant_id provided."""
        task = self._queue.get_task(task_id)
        if task is None:
            return None
        if tenant_id and task.tenant_id != tenant_id:
            return None  # Tenant isolation
        return task.to_dict()

    async def cancel_task(self, task_id: str, tenant_id: Optional[str] = None) -> bool:
        """Cancel a running or queued task."""
        task = self._queue.get_task(task_id)
        if task is None:
            return False
        if tenant_id and task.tenant_id != tenant_id:
            return False

        if task.status in (TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELLED):
            return False  # Already finished

        # Signal cancellation
        cancel_event = self._cancel_events.get(task_id)
        if cancel_event:
            cancel_event.set()

        task.status = TaskStatus.CANCELLED
        task.completed_at = datetime.utcnow().isoformat()
        self._queue.update_task(task)
        logger.info(f"Task {task_id} cancelled")
        return True

    def list_tasks(self, tenant_id: Optional[str] = None) -> List[Dict]:
        """List all tasks, optionally filtered by tenant."""
        tasks = self._queue.list_tasks(tenant_id)
        return [t.to_dict() for t in tasks]

    async def cleanup(self):
        """Remove old completed tasks."""
        self._queue.cleanup_old(max_age_seconds=self.config.result_ttl)

    # -------------------------------------------------------------------
    # Worker loop
    # -------------------------------------------------------------------

    async def _worker_loop(self, worker_id: int):
        """Background worker that processes tasks from the queue."""
        logger.info(f"Worker {worker_id} started")

        while self._running:
            try:
                task_id = await self._queue.dequeue(timeout=1.0)
                if task_id is None:
                    continue

                task = self._queue.get_task(task_id)
                if task is None or task.status == TaskStatus.CANCELLED:
                    continue

                # Mark running
                task.status = TaskStatus.RUNNING
                task.started_at = datetime.utcnow().isoformat()
                task.progress = 10
                self._queue.update_task(task)

                cancel_event = self._cancel_events.get(task_id)

                try:
                    # Check for cancellation before starting
                    if cancel_event and cancel_event.is_set():
                        task.status = TaskStatus.CANCELLED
                        task.completed_at = datetime.utcnow().isoformat()
                        self._queue.update_task(task)
                        continue

                    # Execute the task
                    task.progress = 30
                    self._queue.update_task(task)

                    result: TaskResult = await self._executor_func(
                        goal=task.goal,
                        tenant_id=task.tenant_id,
                        files=task.files,
                        language=task.language,
                        use_cache=True,
                    )

                    # Check cancellation after execution
                    if cancel_event and cancel_event.is_set():
                        task.status = TaskStatus.CANCELLED
                        task.completed_at = datetime.utcnow().isoformat()
                        self._queue.update_task(task)
                        continue

                    task.result = result
                    task.status = TaskStatus.COMPLETED if result.success else TaskStatus.FAILED
                    task.error = result.error if not result.success else None
                    task.attempts = result.attempts
                    task.progress = 100
                    task.completed_at = datetime.utcnow().isoformat()
                    self._queue.update_task(task)

                    logger.info(
                        f"Worker {worker_id}: Task {task_id} "
                        f"{'completed' if result.success else 'failed'}"
                    )

                except Exception as exc:
                    task.status = TaskStatus.FAILED
                    task.error = str(exc)
                    task.completed_at = datetime.utcnow().isoformat()
                    task.progress = 100
                    self._queue.update_task(task)
                    logger.error(f"Worker {worker_id}: Task {task_id} error: {exc}")

                finally:
                    # Clean up cancel event
                    self._cancel_events.pop(task_id, None)

            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.error(f"Worker {worker_id} error: {exc}")
                await asyncio.sleep(1)

        logger.info(f"Worker {worker_id} stopped")
