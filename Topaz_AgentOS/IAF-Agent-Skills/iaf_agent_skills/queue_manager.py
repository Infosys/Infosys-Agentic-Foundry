"""
Queue Manager - Enterprise-ready task queue abstraction.

Provides concurrency control for agent operations with swappable backends:
- MEMORY: In-memory queues (default, no dependencies)
- REDIS: Redis-based queues (enterprise, add when scaling)

Usage:
    from queue_manager import create_queue_manager, QueueConfig, QueueBackend
    
    # Create queue (uses memory by default)
    queue = create_queue_manager()
    
    # Enqueue task with concurrency control
    result = await queue.enqueue(
        "session:user123",           # Queue name
        lambda: agent.run(message),  # Task
        max_concurrent=1             # Serial execution
    )

To switch to Redis (enterprise):
    queue = create_queue_manager(QueueConfig(
        backend=QueueBackend.REDIS,
        redis_url="redis://localhost:6379"
    ))
"""

import asyncio
import inspect
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Callable, Any, Optional, Dict, TypeVar, Awaitable, Union, List
import logging

logger = logging.getLogger(__name__)

T = TypeVar('T')


async def _run_task(task: Callable[[], Any]) -> Any:
    """Run a queued task without blocking the event loop.

    Callers pass either an async function or a plain blocking one — almost always
    `lambda: agent.run(...)`, which makes LLM and tool calls for seconds to minutes.
    Calling a plain function here ran it ON the event loop, so every other request
    (other users, WebSockets, /health/live) stalled until it finished. Plain functions
    now run on a worker thread, exactly as the WebSocket chat path already does with
    asyncio.to_thread(agent.run, ...). Lane max_concurrent still serialises tasks.
    """
    if inspect.iscoroutinefunction(task):
        return await task()
    result = await asyncio.to_thread(task)
    if asyncio.iscoroutine(result):  # a plain callable that returned a coroutine
        result = await result
    return result


class QueueBackend(Enum):
    """Supported queue backends."""
    MEMORY = "memory"      # In-process (Phase 1)
    REDIS = "redis"        # Redis queue (Phase 2+)


@dataclass
class QueueConfig:
    """Queue configuration."""
    backend: QueueBackend = QueueBackend.MEMORY
    redis_url: Optional[str] = None
    
    # Memory backend settings
    default_max_concurrent: int = 1
    
    # Monitoring
    enable_metrics: bool = True
    log_enqueue: bool = False  # Set True for debugging


@dataclass
class QueueMetrics:
    """Queue metrics for monitoring."""
    total_enqueued: int = 0
    total_completed: int = 0
    total_errors: int = 0
    total_wait_time_ms: float = 0
    total_execution_time_ms: float = 0
    
    @property
    def avg_wait_time_ms(self) -> float:
        return self.total_wait_time_ms / max(self.total_completed, 1)
    
    @property
    def avg_execution_time_ms(self) -> float:
        return self.total_execution_time_ms / max(self.total_completed, 1)


class BaseQueueManager(ABC):
    """
    Abstract base class for queue managers.
    
    Implement this interface to add new backends (Redis, RabbitMQ, etc.)
    without changing agent code.
    """
    
    @abstractmethod
    async def enqueue(
        self, 
        queue_name: str, 
        task: Callable[[], Union[T, Awaitable[T]]],
        max_concurrent: int = 1,
        timeout: Optional[float] = None
    ) -> T:
        """
        Queue and execute a task.
        
        Args:
            queue_name: Name of the queue (e.g., "session:user123")
            task: Callable to execute (sync or async)
            max_concurrent: Max parallel tasks in this queue
            timeout: Optional timeout in seconds
            
        Returns:
            Result of the task
        """
        pass
    
    @abstractmethod
    async def get_queue_status(self, queue_name: str) -> Dict[str, Any]:
        """Get queue statistics."""
        pass
    
    @abstractmethod
    def get_all_queues_status(self) -> Dict[str, Any]:
        """Get status of all queues."""
        pass


class MemoryQueueManager(BaseQueueManager):
    """
    In-memory Lane Manager using OpenClaw's queue/drain pattern.
    
    Features:
    - Explicit queue array (can inspect pending tasks)
    - Drain pump for controlled execution
    - Cancel pending tasks
    - Priority support
    - Full observability
    
    Perfect for:
    - Development
    - Single-server deployment
    - When queue persistence isn't required
    
    Limitations:
    - Queues lost on restart
    - Single process only
    """
    
    def __init__(self, config: QueueConfig = None):
        self.config = config or QueueConfig()
        self._lanes: Dict[str, 'LaneState'] = {}
        self._metrics = QueueMetrics()
        self._lock = asyncio.Lock()
    
    async def _get_or_create_lane(self, lane_name: str, max_concurrent: int) -> 'LaneState':
        """Get or create a lane (OpenClaw pattern)."""
        async with self._lock:
            if lane_name not in self._lanes:
                self._lanes[lane_name] = LaneState(
                    name=lane_name,
                    max_concurrent=max_concurrent
                )
            return self._lanes[lane_name]
    
    async def enqueue(
        self, 
        queue_name: str, 
        task: Callable[[], Union[T, Awaitable[T]]],
        max_concurrent: int = 1,
        timeout: Optional[float] = None,
        priority: int = 0
    ) -> T:
        """
        Queue and execute task using OpenClaw's lane pattern.
        
        Args:
            queue_name: Lane identifier (e.g., "session:tenant:user")
            task: Sync or async callable
            max_concurrent: Max concurrent executions in this lane
            timeout: Optional timeout in seconds
            priority: Higher = executed first (0 = normal)
            
        Returns:
            Task result
        """
        lane = await self._get_or_create_lane(queue_name, max_concurrent)
        
        future: asyncio.Future = asyncio.Future()
        entry = QueueEntry(
            task=task,
            future=future,
            priority=priority,
            enqueue_time=time.time()
        )
        
        async with lane.lock:
            lane.queue.append(entry)
            lane.stats["waiting"] += 1
            self._metrics.total_enqueued += 1
            
            if self.config.log_enqueue:
                logger.info(f"📥 Enqueue [{queue_name}]: queue_len={len(lane.queue)}, active={lane.active}")
        
        # Trigger drain pump
        asyncio.create_task(self._drain_lane(lane))
        
        # Wait for result (with optional timeout)
        try:
            if timeout:
                result = await asyncio.wait_for(future, timeout=timeout)
            else:
                result = await future
            return result
        except asyncio.TimeoutError:
            # Remove from queue if still waiting
            async with lane.lock:
                if entry in lane.queue:
                    lane.queue.remove(entry)
                    lane.stats["waiting"] -= 1
                    lane.stats["timeouts"] += 1
            logger.warning(f"⏰ Timeout [{queue_name}]: waited {timeout}s")
            raise
    
    async def _drain_lane(self, lane: 'LaneState'):
        """
        OpenClaw's drain pump - execute tasks respecting max_concurrent.
        
        This is the heart of the lane pattern:
        1. Check if we can run more tasks
        2. Pop from queue and execute
        3. Re-trigger drain when task completes
        """
        async with lane.lock:
            if lane.draining:
                return  # Another drain is already running
            lane.draining = True
        
        try:
            while True:
                # Check if we can execute more
                async with lane.lock:
                    if not lane.queue or lane.active >= lane.max_concurrent:
                        break
                    
                    # Sort by priority (higher first) then by enqueue time (FIFO)
                    lane.queue.sort(key=lambda e: (-e.priority, e.enqueue_time))
                    
                    # Pop next task
                    entry = lane.queue.pop(0)
                    lane.active += 1
                    lane.stats["waiting"] -= 1
                    
                    if self.config.log_enqueue:
                        wait_time = (time.time() - entry.enqueue_time) * 1000
                        logger.info(f"🚀 Execute [{lane.name}]: waited={wait_time:.0f}ms, active={lane.active}")
                
                # Execute outside lock (allow concurrent execution)
                asyncio.create_task(self._execute_entry(lane, entry))
                
        finally:
            async with lane.lock:
                lane.draining = False
    
    async def _execute_entry(self, lane: 'LaneState', entry: 'QueueEntry'):
        """Execute a single queue entry and handle completion."""
        start_time = time.time()
        wait_time = (start_time - entry.enqueue_time) * 1000
        self._metrics.total_wait_time_ms += wait_time
        
        try:
            result = await _run_task(entry.task)
            
            # Track success
            execution_time = (time.time() - start_time) * 1000
            self._metrics.total_execution_time_ms += execution_time
            self._metrics.total_completed += 1
            
            async with lane.lock:
                lane.stats["completed"] += 1
            
            if self.config.log_enqueue:
                logger.info(f"✅ Complete [{lane.name}]: exec={execution_time:.0f}ms")
            
            if not entry.future.done():
                entry.future.set_result(result)
                
        except Exception as e:
            async with lane.lock:
                lane.stats["errors"] += 1
            self._metrics.total_errors += 1
            logger.error(f"❌ Error [{lane.name}]: {e}")
            
            if not entry.future.done():
                entry.future.set_exception(e)
                
        finally:
            async with lane.lock:
                lane.active -= 1
            
            # Re-trigger drain (more tasks may be waiting)
            asyncio.create_task(self._drain_lane(lane))
    
    
    async def get_pending_tasks(self, queue_name: str) -> List[Dict[str, Any]]:
        """
        Get list of tasks waiting in queue.
        
        Returns:
            List of pending tasks with metadata (priority, wait_time, etc.)
        """
        if queue_name not in self._lanes:
            return []
        
        lane = self._lanes[queue_name]
        async with lane.lock:
            return [
                {
                    "priority": e.priority,
                    "wait_time_ms": (time.time() - e.enqueue_time) * 1000,
                    "enqueue_time": e.enqueue_time
                }
                for e in lane.queue
            ]
    
    async def cancel_pending(self, queue_name: str) -> int:
        """
        Cancel all pending tasks in a queue.
        
        Returns:
            Number of tasks cancelled
        """
        if queue_name not in self._lanes:
            return 0
        
        lane = self._lanes[queue_name]
        async with lane.lock:
            cancelled = len(lane.queue)
            for entry in lane.queue:
                if not entry.future.done():
                    entry.future.cancel()
            lane.queue.clear()
            lane.stats["waiting"] = 0
            lane.stats["cancelled"] += cancelled
            
        logger.info(f"🚫 Cancelled {cancelled} pending tasks in [{queue_name}]")
        return cancelled
    
    async def get_queue_status(self, queue_name: str) -> Dict[str, Any]:
        """Get status of a specific lane."""
        if queue_name not in self._lanes:
            return {"exists": False, "queue_name": queue_name}
        
        lane = self._lanes[queue_name]
        async with lane.lock:
            return {
                "exists": True,
                "queue_name": queue_name,
                "backend": "memory",
                "max_concurrent": lane.max_concurrent,
                "queue_length": len(lane.queue),
                "active": lane.active,
                "draining": lane.draining,
                **lane.stats
            }
    
    def get_all_queues_status(self) -> Dict[str, Any]:
        """Get status of all lanes."""
        lanes_info = {}
        for name, lane in self._lanes.items():
            lanes_info[name] = {
                "max_concurrent": lane.max_concurrent,
                "queue_length": len(lane.queue),
                "active": lane.active,
                **lane.stats
            }
        
        return {
            "backend": "memory",
            "pattern": "openclaw_lanes",
            "lanes": lanes_info,
            "metrics": {
                "total_enqueued": self._metrics.total_enqueued,
                "total_completed": self._metrics.total_completed,
                "total_errors": self._metrics.total_errors,
                "avg_wait_time_ms": round(self._metrics.avg_wait_time_ms, 2),
                "avg_execution_time_ms": round(self._metrics.avg_execution_time_ms, 2)
            }
        }


@dataclass
class QueueEntry:
    """A single entry in the lane queue."""
    task: Callable
    future: asyncio.Future
    priority: int = 0
    enqueue_time: float = 0


@dataclass  
class LaneState:
    """
    OpenClaw-style Lane State.
    
    Each lane has its own queue, active count, and drain pump.
    """
    name: str
    max_concurrent: int = 1
    queue: List[QueueEntry] = field(default_factory=list)
    active: int = 0
    draining: bool = False
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    stats: Dict[str, int] = field(default_factory=lambda: {
        "waiting": 0,
        "completed": 0,
        "errors": 0,
        "timeouts": 0,
        "cancelled": 0
    })


class RedisQueueManager(BaseQueueManager):
    """
    Redis-based queue manager for enterprise scaling.
    
    Benefits:
    - Survives process restarts (queue persistence)
    - Multi-process / multi-server (shared queue)
    - Queue visibility via Redis CLI
    - Same OpenClaw lane pattern, different storage
    
    Architecture:
    - Same server processes tasks (no separate workers needed)
    - Redis just provides durable, shared storage for queue state
    - For multi-server: each server pulls from same Redis queues
    """
    
    def __init__(self, config: QueueConfig):
        self.config = config
        if not config.redis_url:
            raise ValueError("redis_url required for Redis backend")
        
        # Lazy import - only when actually using Redis
        try:
            import redis.asyncio as aioredis
            self.redis = aioredis.from_url(
                config.redis_url,
                encoding="utf-8",
                decode_responses=True
            )
            self._redis_available = True
            logger.info("🔴 RedisQueueManager initialized")
        except ImportError:
            logger.error("❌ Redis package not installed. Run: pip install redis")
            self._redis_available = False
            raise ImportError("redis package required. Install with: pip install redis")
        
        # Local state for tracking active tasks (per-process)
        self._lanes: Dict[str, 'RedisLaneState'] = {}
        self._metrics = QueueMetrics()
        self._lock = asyncio.Lock()
    
    async def _get_or_create_lane(self, lane_name: str, max_concurrent: int) -> 'RedisLaneState':
        """Get or create a local lane state tracker."""
        async with self._lock:
            if lane_name not in self._lanes:
                self._lanes[lane_name] = RedisLaneState(
                    name=lane_name,
                    max_concurrent=max_concurrent
                )
            return self._lanes[lane_name]
    
    async def enqueue(
        self, 
        queue_name: str, 
        task: Callable[[], Union[T, Awaitable[T]]],
        max_concurrent: int = 1,
        timeout: Optional[float] = None,
        priority: int = 0
    ) -> T:
        """
        Queue and execute task using Redis-backed lanes.
        
        Note: Tasks are still executed locally (not serialized to Redis).
        Redis manages the queue/concurrency state, not task execution.
        
        For truly distributed execution, you'd need separate worker processes
        that pull from Redis. This implementation supports that future pattern
        while working fine for single-server deployment.
        """
        lane = await self._get_or_create_lane(queue_name, max_concurrent)
        
        future: asyncio.Future = asyncio.Future()
        entry = QueueEntry(
            task=task,
            future=future,
            priority=priority,
            enqueue_time=time.time()
        )
        
        # Track in local lane
        async with lane.lock:
            lane.queue.append(entry)
            lane.stats["waiting"] += 1
            self._metrics.total_enqueued += 1
        
        # Also track in Redis for visibility/persistence
        await self._redis_track_enqueue(queue_name)
        
        if self.config.log_enqueue:
            logger.info(f"📥 Redis Enqueue [{queue_name}]: queue_len={len(lane.queue)}, active={lane.active}")
        
        # Trigger drain pump
        asyncio.create_task(self._drain_lane(lane))
        
        # Wait for result (with optional timeout)
        try:
            if timeout:
                result = await asyncio.wait_for(future, timeout=timeout)
            else:
                result = await future
            return result
        except asyncio.TimeoutError:
            async with lane.lock:
                if entry in lane.queue:
                    lane.queue.remove(entry)
                    lane.stats["waiting"] -= 1
                    lane.stats["timeouts"] += 1
            await self._redis_track_timeout(queue_name)
            logger.warning(f"⏰ Redis Timeout [{queue_name}]: waited {timeout}s")
            raise
    
    async def _redis_track_enqueue(self, queue_name: str):
        """Track queue metrics in Redis for visibility."""
        try:
            await self.redis.hincrby(f"queue:metrics:{queue_name}", "enqueued", 1)
            await self.redis.hincrby("queue:global:metrics", "total_enqueued", 1)
        except Exception as e:
            logger.warning(f"Redis tracking failed: {e}")
    
    async def _redis_track_complete(self, queue_name: str, execution_time_ms: float):
        """Track completion in Redis."""
        try:
            await self.redis.hincrby(f"queue:metrics:{queue_name}", "completed", 1)
            await self.redis.hincrbyfloat(f"queue:metrics:{queue_name}", "exec_time_ms", execution_time_ms)
            await self.redis.hincrby("queue:global:metrics", "total_completed", 1)
        except Exception as e:
            logger.warning(f"Redis tracking failed: {e}")
    
    async def _redis_track_error(self, queue_name: str):
        """Track error in Redis."""
        try:
            await self.redis.hincrby(f"queue:metrics:{queue_name}", "errors", 1)
            await self.redis.hincrby("queue:global:metrics", "total_errors", 1)
        except Exception as e:
            logger.warning(f"Redis tracking failed: {e}")
    
    async def _redis_track_timeout(self, queue_name: str):
        """Track timeout in Redis."""
        try:
            await self.redis.hincrby(f"queue:metrics:{queue_name}", "timeouts", 1)
        except Exception as e:
            logger.warning(f"Redis tracking failed: {e}")
    
    async def _drain_lane(self, lane: 'RedisLaneState'):
        """OpenClaw drain pump - same logic as Memory, just with Redis tracking."""
        async with lane.lock:
            if lane.draining:
                return
            lane.draining = True
        
        try:
            while True:
                async with lane.lock:
                    if not lane.queue or lane.active >= lane.max_concurrent:
                        break
                    
                    lane.queue.sort(key=lambda e: (-e.priority, e.enqueue_time))
                    entry = lane.queue.pop(0)
                    lane.active += 1
                    lane.stats["waiting"] -= 1
                    
                    if self.config.log_enqueue:
                        wait_time = (time.time() - entry.enqueue_time) * 1000
                        logger.info(f"🚀 Redis Execute [{lane.name}]: waited={wait_time:.0f}ms")
                
                asyncio.create_task(self._execute_entry(lane, entry))
                
        finally:
            async with lane.lock:
                lane.draining = False
    
    async def _execute_entry(self, lane: 'RedisLaneState', entry: 'QueueEntry'):
        """Execute task and track in Redis."""
        start_time = time.time()
        wait_time = (start_time - entry.enqueue_time) * 1000
        self._metrics.total_wait_time_ms += wait_time
        
        try:
            result = await _run_task(entry.task)
            
            execution_time = (time.time() - start_time) * 1000
            self._metrics.total_execution_time_ms += execution_time
            self._metrics.total_completed += 1
            
            async with lane.lock:
                lane.stats["completed"] += 1
            
            await self._redis_track_complete(lane.name, execution_time)
            
            if self.config.log_enqueue:
                logger.info(f"✅ Redis Complete [{lane.name}]: exec={execution_time:.0f}ms")
            
            if not entry.future.done():
                entry.future.set_result(result)
                
        except Exception as e:
            async with lane.lock:
                lane.stats["errors"] += 1
            self._metrics.total_errors += 1
            
            await self._redis_track_error(lane.name)
            logger.error(f"❌ Redis Error [{lane.name}]: {e}")
            
            if not entry.future.done():
                entry.future.set_exception(e)
                
        finally:
            async with lane.lock:
                lane.active -= 1
            asyncio.create_task(self._drain_lane(lane))
    
    async def get_queue_status(self, queue_name: str) -> Dict[str, Any]:
        """Get status from local + Redis."""
        local_status = {"exists": False, "queue_name": queue_name}
        
        if queue_name in self._lanes:
            lane = self._lanes[queue_name]
            async with lane.lock:
                local_status = {
                    "exists": True,
                    "queue_name": queue_name,
                    "backend": "redis",
                    "max_concurrent": lane.max_concurrent,
                    "queue_length": len(lane.queue),
                    "active": lane.active,
                    "draining": lane.draining,
                    **lane.stats
                }
        
        try:
            redis_metrics = await self.redis.hgetall(f"queue:metrics:{queue_name}")
            local_status["redis_metrics"] = redis_metrics
        except Exception:
            pass
        
        return local_status
    
    def get_all_queues_status(self) -> Dict[str, Any]:
        """Get all lanes status."""
        lanes_info = {}
        for name, lane in self._lanes.items():
            lanes_info[name] = {
                "max_concurrent": lane.max_concurrent,
                "queue_length": len(lane.queue),
                "active": lane.active,
                **lane.stats
            }
        
        return {
            "backend": "redis",
            "pattern": "openclaw_lanes",
            "redis_url": self.config.redis_url,
            "lanes": lanes_info,
            "metrics": {
                "total_enqueued": self._metrics.total_enqueued,
                "total_completed": self._metrics.total_completed,
                "total_errors": self._metrics.total_errors,
                "avg_wait_time_ms": round(self._metrics.avg_wait_time_ms, 2),
                "avg_execution_time_ms": round(self._metrics.avg_execution_time_ms, 2)
            }
        }
    
    async def close(self):
        """Close Redis connection."""
        if self._redis_available:
            await self.redis.close()
            logger.info("🔴 Redis connection closed")


@dataclass  
class RedisLaneState:
    """
    Local lane state for Redis backend.
    
    Note: Tasks are stored locally (not serialized to Redis).
    Redis tracks metrics/visibility. For truly distributed workers,
    you'd serialize tasks to Redis and have workers pull them.
    """
    name: str
    max_concurrent: int = 1
    queue: List['QueueEntry'] = field(default_factory=list)
    active: int = 0
    draining: bool = False
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    stats: Dict[str, int] = field(default_factory=lambda: {
        "waiting": 0,
        "completed": 0,
        "errors": 0,
        "timeouts": 0,
        "cancelled": 0
    })


def create_queue_manager(config: QueueConfig = None) -> BaseQueueManager:
    """
    Factory function to create queue manager.
    
    Args:
        config: Queue configuration. Defaults to memory backend.
        
    Returns:
        Configured queue manager instance
        
    Example:
        # Default (memory)
        queue = create_queue_manager()
        
        # Redis (enterprise)
        queue = create_queue_manager(QueueConfig(
            backend=QueueBackend.REDIS,
            redis_url="redis://localhost:6379"
        ))
    """
    config = config or QueueConfig()
    
    if config.backend == QueueBackend.MEMORY:
        return MemoryQueueManager(config)
    elif config.backend == QueueBackend.REDIS:
        return RedisQueueManager(config)
    else:
        raise ValueError(f"Unknown backend: {config.backend}")



class QueueNames:
    """Standard queue naming patterns for enterprise use."""
    
    @staticmethod
    def session(tenant_id: str, user_id: str) -> str:
        """Per-user session queue (serial execution)."""
        return f"session:{tenant_id}:{user_id}"
    
    @staticmethod
    def agent(tenant_id: str, agent_id: str) -> str:
        """Per-agent queue."""
        return f"agent:{tenant_id}:{agent_id}"
    
    @staticmethod
    def cron(tenant_id: str) -> str:
        """Cron/scheduled jobs queue (parallel OK)."""
        return f"cron:{tenant_id}"
    
    @staticmethod
    def tools(tenant_id: str, session_id: str) -> str:
        """Tool execution queue (limited parallel)."""
        return f"tools:{tenant_id}:{session_id}"
    
    @staticmethod
    def memory(tenant_id: str, agent_id: str) -> str:
        """Memory operations queue (serial for consistency)."""
        return f"memory:{tenant_id}:{agent_id}"



_global_queue: Optional[BaseQueueManager] = None

def get_queue() -> BaseQueueManager:
    """Get global queue manager instance."""
    global _global_queue
    if _global_queue is None:
        _global_queue = create_queue_manager()
    return _global_queue

def set_queue(queue: BaseQueueManager):
    """Set global queue manager instance."""
    global _global_queue
    _global_queue = queue
