"""
Task Executor - Worker that pulls and executes tasks.

The executor is the consumer side of the task system:
1. Polls the queue for tasks
2. Routes to appropriate handler based on task_type
3. Calls handler.execute()
4. Stores result and acks/nacks

Can run in:
- Same process as web server (simple)
- Separate worker process (scalable)
- Multiple instances (distributed)

Usage:
    queue = TaskQueue(redis_url="redis://localhost:6379")
    executor = TaskExecutor(queue)
    
    # Register handlers
    executor.register(SkillHandler(kernel))
    executor.register(ToolHandler(kernel))
    
    # Run (blocks, polling queue)
    await executor.run()
    
    # Or run one iteration (for testing)
    processed = await executor.process_one()
"""

from __future__ import annotations
import asyncio
import time
import traceback
import logging
from datetime import datetime, timezone
from typing import Dict, List, Optional, Set

from .models import TaskDefinition, TaskResult, TaskStatus
from .protocol import TaskHandler
from .queue import TaskQueue

logger = logging.getLogger(__name__)


class TaskExecutor:
    """
    Task executor that polls queue and routes to handlers.
    
    Features:
    - Multiple handler support
    - Graceful shutdown
    - Concurrent execution (configurable)
    - Metrics and logging
    """
    
    def __init__(
        self,
        queue: TaskQueue,
        max_concurrent: int = 10,
        poll_interval: float = 1.0,
        lanes: Optional[List[str]] = None,
    ):
        """
        Initialize executor.
        
        Args:
            queue: TaskQueue to pull from
            max_concurrent: Max tasks to execute in parallel
            poll_interval: Seconds between queue polls
            lanes: List of lanes to process (default: ["default"])
        """
        self.queue = queue
        self.max_concurrent = max_concurrent
        self.poll_interval = poll_interval
        self.lanes = lanes or ["default"]
        
        self._handlers: Dict[str, TaskHandler] = {}
        self._running = False
        self._active_tasks: Set[str] = set()
        self._semaphore: Optional[asyncio.Semaphore] = None
        
        # Metrics
        self._metrics = {
            "tasks_processed": 0,
            "tasks_succeeded": 0,
            "tasks_failed": 0,
            "total_duration_ms": 0.0,
        }
    
    
    def register(self, handler: TaskHandler) -> None:
        """
        Register a handler for its task types.
        
        Args:
            handler: TaskHandler instance
        """
        for task_type in handler.task_types:
            if task_type in self._handlers:
                logger.warning(f"Overwriting handler for task_type '{task_type}'")
            self._handlers[task_type] = handler
            logger.info(f"Registered {handler.name} for task_type '{task_type}'")
    
    def get_handler(self, task_type: str) -> Optional[TaskHandler]:
        """Get handler for a task type."""
        return self._handlers.get(task_type)
    
    
    async def run(self) -> None:
        """
        Run the executor (main loop).
        
        Polls queue continuously until stop() is called.
        """
        self._running = True
        self._semaphore = asyncio.Semaphore(self.max_concurrent)
        
        logger.info(f"TaskExecutor started (lanes={self.lanes}, max_concurrent={self.max_concurrent})")
        
        try:
            while self._running:
                # Try to process tasks from each lane
                processed_any = False
                
                for lane in self.lanes:
                    if len(self._active_tasks) >= self.max_concurrent:
                        break  # At capacity
                    
                    task = await self.queue.dequeue(lane)
                    if task:
                        asyncio.create_task(self._execute_task(task))
                        processed_any = True
                
                # If no tasks, wait before next poll
                if not processed_any:
                    await asyncio.sleep(self.poll_interval)
        
        finally:
            # Wait for active tasks to complete
            while self._active_tasks:
                logger.info(f"Waiting for {len(self._active_tasks)} active tasks...")
                await asyncio.sleep(0.5)
            
            logger.info("TaskExecutor stopped")
    
    async def stop(self) -> None:
        """Signal executor to stop after current tasks complete."""
        self._running = False
    
    async def process_one(self, lane: str = "default") -> bool:
        """
        Process a single task (for testing).
        
        Returns:
            True if a task was processed, False if queue empty
        """
        task = await self.queue.dequeue(lane)
        if not task:
            return False
        
        await self._execute_task(task)
        return True
    
    async def _execute_task(self, task: TaskDefinition) -> None:
        """Execute a single task."""
        self._active_tasks.add(task.id)
        start_time = time.time()
        
        try:
            handler = self.get_handler(task.task_type)
            if not handler:
                raise ValueError(f"No handler for task_type '{task.task_type}'")
            
            logger.info(f"Executing task {task.id} ({task.task_type}) with {handler.name}")
            
            # Before hook
            await handler.before_execute(task)
            
            result = await handler.execute(task)
            
            # After hook
            await handler.after_execute(task, result)
            
            duration_ms = (time.time() - start_time) * 1000
            result.duration_ms = duration_ms
            result.handler_name = handler.name
            
            # Ack success
            await self.queue.ack(task.id, result)
            
            self._metrics["tasks_processed"] += 1
            self._metrics["tasks_succeeded"] += 1
            self._metrics["total_duration_ms"] += duration_ms
            
            logger.info(f"Task {task.id} completed in {duration_ms:.0f}ms")
        
        except Exception as e:
            duration_ms = (time.time() - start_time) * 1000
            error_tb = traceback.format_exc()
            
            logger.error(f"Task {task.id} failed: {e}\n{error_tb}")
            
            # Nack (will retry or DLQ)
            await self.queue.nack(task.id, str(e), error_tb)
            
            self._metrics["tasks_processed"] += 1
            self._metrics["tasks_failed"] += 1
            self._metrics["total_duration_ms"] += duration_ms
        
        finally:
            self._active_tasks.discard(task.id)
    
    
    def get_metrics(self) -> Dict[str, float]:
        """Get executor metrics."""
        metrics = dict(self._metrics)
        metrics["active_tasks"] = len(self._active_tasks)
        metrics["registered_handlers"] = len(self._handlers)
        
        if metrics["tasks_processed"] > 0:
            metrics["avg_duration_ms"] = metrics["total_duration_ms"] / metrics["tasks_processed"]
            metrics["success_rate"] = metrics["tasks_succeeded"] / metrics["tasks_processed"]
        else:
            metrics["avg_duration_ms"] = 0
            metrics["success_rate"] = 0
        
        return metrics


class InlineExecutor:
    """
    Synchronous inline executor for simple use cases.
    
    Instead of polling a queue, this executes tasks immediately.
    Useful for development or when you don't need persistence.
    
    Usage:
        executor = InlineExecutor()
        executor.register(SkillHandler(kernel))
        
        result = await executor.execute(task)
    """
    
    def __init__(self):
        self._handlers: Dict[str, TaskHandler] = {}
    
    def register(self, handler: TaskHandler) -> None:
        """Register a handler."""
        for task_type in handler.task_types:
            self._handlers[task_type] = handler
    
    async def execute(self, task: TaskDefinition) -> TaskResult:
        """Execute a task immediately (no queue)."""
        handler = self._handlers.get(task.task_type)
        if not handler:
            return TaskResult(
                task_id=task.id,
                status=TaskStatus.FAILED,
                error_message=f"No handler for task_type '{task.task_type}'",
            )
        
        start_time = time.time()
        
        try:
            await handler.before_execute(task)
            result = await handler.execute(task)
            await handler.after_execute(task, result)
            
            result.duration_ms = (time.time() - start_time) * 1000
            result.handler_name = handler.name
            return result
        
        except Exception as e:
            return TaskResult(
                task_id=task.id,
                status=TaskStatus.FAILED,
                error_message=str(e),
                error_traceback=traceback.format_exc(),
                duration_ms=(time.time() - start_time) * 1000,
            )
