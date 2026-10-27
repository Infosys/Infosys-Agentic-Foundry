"""
Task Queue - Redis-based persistent task queue for Mode 4.

This is the heart of the persistence layer:
- Tasks stored as Redis HASHes (survive restart)
- Priority ordering via Redis ZSETs
- Visibility timeout for at-least-once delivery
- Dead Letter Queue for failed tasks
- Result storage for async retrieval

Key Design:
- submit() is fast (just writes to Redis)
- dequeue() is called by executor/workers
- Results stored separately for efficient retrieval
"""

from __future__ import annotations
import asyncio
import time
import logging
from datetime import datetime, timezone
from typing import Optional, List, Dict, Any

from .models import (
    TaskDefinition,
    TaskResult,
    TaskStatus,
    TaskPriority,
)

logger = logging.getLogger(__name__)


class TaskQueue:
    """
    Persistent task queue backed by Redis.
    
    Redis Key Structure:
        {prefix}:task:{id}           - HASH: Task definition
        {prefix}:result:{id}         - HASH: Task result
        {prefix}:queue:{lane}        - ZSET: Priority queue per lane
        {prefix}:processing          - ZSET: Tasks being processed (visibility timeout)
        {prefix}:dlq                 - LIST: Dead letter queue
        {prefix}:metrics             - HASH: Counters
    
    Usage:
        queue = TaskQueue(redis_url="redis://localhost:6379")
        await queue.connect()
        
        # Submit task
        task_id = await queue.submit(task)
        
        # Dequeue (called by executor)
        task = await queue.dequeue(lane="default")
        
        # Acknowledge completion
        await queue.ack(task_id, result)
        
        # Or negative ack (retry)
        await queue.nack(task_id, error_message)
    """
    
    def __init__(
        self,
        redis_url: str = "redis://localhost:6379",
        key_prefix: str = "iaf:tasks",
        visibility_timeout: int = 300,  # 5 minutes
        poll_interval: float = 1.0,
    ):
        self.redis_url = redis_url
        self.key_prefix = key_prefix
        self.visibility_timeout = visibility_timeout
        self.poll_interval = poll_interval
        self._redis = None
        self._connected = False
    
    
    async def connect(self) -> None:
        """Connect to Redis."""
        if self._connected:
            return
        
        import redis.asyncio as aioredis
        self._redis = aioredis.from_url(
            self.redis_url,
            encoding="utf-8",
            decode_responses=True,
        )
        await self._redis.ping()
        self._connected = True
        logger.info("TaskQueue connected to configured Redis endpoint")
    
    async def disconnect(self) -> None:
        """Disconnect from Redis."""
        if self._redis:
            await self._redis.aclose()
            self._connected = False
            logger.info("TaskQueue disconnected")
    
    async def __aenter__(self) -> 'TaskQueue':
        await self.connect()
        return self
    
    async def __aexit__(self, *args) -> None:
        await self.disconnect()
    
    
    def _task_key(self, task_id: str) -> str:
        return f"{self.key_prefix}:task:{task_id}"
    
    def _result_key(self, task_id: str) -> str:
        return f"{self.key_prefix}:result:{task_id}"
    
    def _queue_key(self, lane: str) -> str:
        return f"{self.key_prefix}:queue:{lane}"
    
    def _processing_key(self) -> str:
        return f"{self.key_prefix}:processing"
    
    def _dlq_key(self) -> str:
        return f"{self.key_prefix}:dlq"
    
    def _metrics_key(self) -> str:
        return f"{self.key_prefix}:metrics"
    
    
    async def submit(self, task: TaskDefinition) -> str:
        """
        Submit a task to the queue.
        
        The task is immediately persisted to Redis and will survive
        server restarts. Any executor can pick it up.
        
        Args:
            task: The task definition to enqueue
            
        Returns:
            task_id for tracking
        """
        await self.connect()
        
        await self._redis.hset(self._task_key(task.id), mapping=task.to_dict())
        
        # Add to priority queue
        # Score = priority_score + (timestamp / 1e12) for FIFO within priority
        score = task.priority.score + (task.created_at.timestamp() / 1e12)
        await self._redis.zadd(self._queue_key(task.lane), {task.id: score})
        
        await self._redis.hincrby(self._metrics_key(), "total_submitted", 1)
        
        logger.debug(f"Submitted task {task.id} to lane {task.lane}")
        return task.id
    
    
    async def dequeue(self, lane: str = "default") -> Optional[TaskDefinition]:
        """
        Dequeue the highest priority task from a lane.
        
        The task is moved to "processing" set with visibility timeout.
        If not ack'd within timeout, it becomes available again.
        
        Args:
            lane: The queue lane to pull from
            
        Returns:
            TaskDefinition if available, None if queue empty
        """
        await self.connect()
        
        # First, recover any stale tasks (visibility timeout expired)
        await self._recover_stale_tasks()
        
        # Pop highest priority task (lowest score)
        result = await self._redis.zpopmin(self._queue_key(lane), count=1)
        if not result:
            return None
        
        task_id = result[0][0]
        
        data = await self._redis.hgetall(self._task_key(task_id))
        if not data:
            logger.warning(f"Task {task_id} in queue but data missing")
            return None
        
        # Reconstruct task
        task = TaskDefinition.from_dict(data)
        
        task.status = TaskStatus.PROCESSING
        task.started_at = datetime.now(timezone.utc)
        await self._redis.hset(self._task_key(task_id), mapping={
            "status": TaskStatus.PROCESSING.value,
            "started_at": task.started_at.isoformat(),
        })
        
        visibility_deadline = time.time() + self.visibility_timeout
        await self._redis.zadd(self._processing_key(), {task_id: visibility_deadline})
        
        await self._redis.hincrby(self._metrics_key(), "total_dequeued", 1)
        
        logger.debug(f"Dequeued task {task_id} from lane {lane}")
        return task
    
    async def _recover_stale_tasks(self) -> int:
        """
        Recover tasks that exceeded visibility timeout.
        
        These are tasks that were dequeued but never ack'd (executor crashed).
        They get re-queued for another attempt.
        
        Returns:
            Number of tasks recovered
        """
        now = time.time()
        
        expired = await self._redis.zrangebyscore(
            self._processing_key(),
            min=0,
            max=now,
        )
        
        recovered = 0
        for task_id in expired:
            data = await self._redis.hgetall(self._task_key(task_id))
            if not data:
                await self._redis.zrem(self._processing_key(), task_id)
                continue
            
            task = TaskDefinition.from_dict(data)
            
            task.retry_count += 1
            
            if task.retry_count >= task.max_retries:
                # Move to DLQ
                task.status = TaskStatus.DLQ
                await self._redis.hset(self._task_key(task_id), mapping={
                    "status": TaskStatus.DLQ.value,
                    "retry_count": str(task.retry_count),
                    "error_message": "Visibility timeout exceeded after max retries",
                })
                await self._redis.rpush(self._dlq_key(), task_id)
                await self._redis.hincrby(self._metrics_key(), "total_dlq", 1)
                logger.warning(f"Task {task_id} moved to DLQ after {task.retry_count} retries")
            else:
                # Re-queue
                task.status = TaskStatus.PENDING
                await self._redis.hset(self._task_key(task_id), mapping={
                    "status": TaskStatus.PENDING.value,
                    "retry_count": str(task.retry_count),
                })
                score = task.priority.score + (time.time() / 1e12)
                await self._redis.zadd(self._queue_key(task.lane), {task_id: score})
                await self._redis.hincrby(self._metrics_key(), "total_retried", 1)
                logger.info(f"Task {task_id} re-queued (retry {task.retry_count})")
            
            # Remove from processing set
            await self._redis.zrem(self._processing_key(), task_id)
            recovered += 1
        
        return recovered
    
    
    async def ack(self, task_id: str, result: TaskResult) -> None:
        """
        Acknowledge successful task completion.
        
        Removes task from processing set and stores result.
        
        Args:
            task_id: The task ID
            result: The execution result
        """
        await self.connect()
        
        await self._redis.hset(self._result_key(task_id), mapping=result.to_dict())
        
        await self._redis.hset(self._task_key(task_id), mapping={
            "status": TaskStatus.COMPLETED.value,
            "completed_at": datetime.now(timezone.utc).isoformat(),
        })
        
        # Remove from processing set
        await self._redis.zrem(self._processing_key(), task_id)
        
        await self._redis.hincrby(self._metrics_key(), "total_completed", 1)
        
        logger.debug(f"Task {task_id} completed successfully")
    
    async def nack(self, task_id: str, error_message: str, error_traceback: str = "") -> None:
        """
        Negative acknowledgment - task failed.
        
        Will retry if under max_retries, otherwise moves to DLQ.
        
        Args:
            task_id: The task ID
            error_message: Error description
            error_traceback: Full traceback (optional)
        """
        await self.connect()
        
        data = await self._redis.hgetall(self._task_key(task_id))
        if not data:
            logger.error(f"Cannot nack unknown task {task_id}")
            return
        
        task = TaskDefinition.from_dict(data)
        task.retry_count += 1
        task.error_message = error_message
        task.error_traceback = error_traceback
        
        if task.retry_count >= task.max_retries:
            # Move to DLQ
            task.status = TaskStatus.DLQ
            await self._redis.hset(self._task_key(task_id), mapping={
                "status": TaskStatus.DLQ.value,
                "retry_count": str(task.retry_count),
                "error_message": error_message,
                "error_traceback": error_traceback,
            })
            await self._redis.rpush(self._dlq_key(), task_id)
            await self._redis.hincrby(self._metrics_key(), "total_dlq", 1)
            logger.warning(f"Task {task_id} moved to DLQ: {error_message}")
        else:
            # Re-queue for retry
            task.status = TaskStatus.PENDING
            await self._redis.hset(self._task_key(task_id), mapping={
                "status": TaskStatus.PENDING.value,
                "retry_count": str(task.retry_count),
                "error_message": error_message,
            })
            score = task.priority.score + (time.time() / 1e12)
            await self._redis.zadd(self._queue_key(task.lane), {task_id: score})
            await self._redis.hincrby(self._metrics_key(), "total_retried", 1)
            logger.info(f"Task {task_id} queued for retry {task.retry_count}")
        
        await self._redis.zrem(self._processing_key(), task_id)
        await self._redis.hincrby(self._metrics_key(), "total_failed", 1)
    
    
    async def get_result(self, task_id: str, timeout: float = 0) -> Optional[TaskResult]:
        """
        Get the result of a completed task.
        
        Args:
            task_id: The task ID
            timeout: If > 0, wait up to this many seconds for completion
            
        Returns:
            TaskResult if available, None otherwise
        """
        await self.connect()
        
        deadline = time.time() + timeout if timeout > 0 else 0
        
        while True:
            data = await self._redis.hgetall(self._result_key(task_id))
            if data:
                return TaskResult.from_dict(data)
            
            if timeout <= 0 or time.time() >= deadline:
                return None
            
            await asyncio.sleep(0.1)
    
    async def get_task(self, task_id: str) -> Optional[TaskDefinition]:
        """Get a task by ID."""
        await self.connect()
        data = await self._redis.hgetall(self._task_key(task_id))
        if not data:
            return None
        return TaskDefinition.from_dict(data)
    
    
    async def get_queue_depth(self, lane: str = "default") -> int:
        """Get number of pending tasks in a lane."""
        await self.connect()
        return await self._redis.zcard(self._queue_key(lane))
    
    async def get_processing_count(self) -> int:
        """Get number of tasks currently being processed."""
        await self.connect()
        return await self._redis.zcard(self._processing_key())
    
    async def get_dlq_size(self) -> int:
        """Get number of tasks in dead letter queue."""
        await self.connect()
        return await self._redis.llen(self._dlq_key())
    
    async def get_dlq_tasks(self, limit: int = 100) -> List[TaskDefinition]:
        """Get tasks from dead letter queue."""
        await self.connect()
        task_ids = await self._redis.lrange(self._dlq_key(), 0, limit - 1)
        tasks = []
        for tid in task_ids:
            task = await self.get_task(tid)
            if task:
                tasks.append(task)
        return tasks
    
    async def get_metrics(self) -> Dict[str, int]:
        """Get queue metrics."""
        await self.connect()
        data = await self._redis.hgetall(self._metrics_key())
        return {k: int(v) for k, v in data.items()}
    
    
    async def purge_lane(self, lane: str) -> int:
        """Remove all tasks from a lane. Returns count purged."""
        await self.connect()
        task_ids = await self._redis.zrange(self._queue_key(lane), 0, -1)
        for tid in task_ids:
            await self._redis.delete(self._task_key(tid))
            await self._redis.delete(self._result_key(tid))
        await self._redis.delete(self._queue_key(lane))
        return len(task_ids)
    
    async def retry_dlq_task(self, task_id: str) -> bool:
        """Move a DLQ task back to the queue for retry."""
        await self.connect()
        
        # Check it's in DLQ
        data = await self._redis.hgetall(self._task_key(task_id))
        if not data or data.get("status") != TaskStatus.DLQ.value:
            return False
        
        task = TaskDefinition.from_dict(data)
        
        # Reset and re-queue
        task.status = TaskStatus.PENDING
        task.retry_count = 0
        task.error_message = ""
        task.error_traceback = ""
        
        await self._redis.hset(self._task_key(task_id), mapping=task.to_dict())
        score = task.priority.score + (time.time() / 1e12)
        await self._redis.zadd(self._queue_key(task.lane), {task_id: score})
        await self._redis.lrem(self._dlq_key(), 1, task_id)
        
        logger.info(f"Task {task_id} moved from DLQ back to queue")
        return True
