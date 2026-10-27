"""
Task Integration Layer - Bridges server.py with task_system for Redis visibility.

This module provides a drop-in replacement for queue_manager.enqueue() that:
1. Stores task data in Redis (you can see it in RedisInsight!)
2. Executes the task immediately (no separate worker needed)
3. Records the result in Redis
4. Falls back gracefully if Redis is unavailable

Usage in server.py:
    from iaf_agent_skills.task_integration import TaskIntegration
    
    # Initialize once
    task_integration = TaskIntegration(redis_url="redis://localhost:6379")
    
    # Use instead of queue_manager.enqueue()
    response = await task_integration.execute_chat(
        content="Log my day",
        skill_name="dilo-agent",
        tenant_id="acme",
        user_id="john",
        session_id="s123",
        agent_runner=lambda: agent.run(content)
    )
"""

import asyncio
import json
import time
import traceback
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Callable, Dict, Optional, Union, Awaitable
from uuid import uuid4
import logging

logger = logging.getLogger(__name__)


class TaskStatus(str, Enum):
    """Task lifecycle states."""
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


class TaskPriority(str, Enum):
    """Task priority levels."""
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


@dataclass
class ChatTask:
    """
    A chat task that can be stored in Redis.
    
    This is what you'll see when you inspect Redis!
    """
    id: str
    content: str  # The user's message
    skill_name: str
    tenant_id: str
    user_id: str
    session_id: str
    agent_id: str = "enterprise_agent"
    priority: TaskPriority = TaskPriority.MEDIUM
    status: TaskStatus = TaskStatus.PENDING
    created_at: str = ""
    started_at: str = ""
    completed_at: str = ""
    response: str = ""
    error: str = ""
    duration_ms: float = 0.0
    
    def __post_init__(self):
        if not self.created_at:
            self.created_at = datetime.now(timezone.utc).isoformat()
    
    def to_redis_hash(self) -> Dict[str, str]:
        """Convert to Redis HASH format (all values must be strings)."""
        return {
            "id": self.id,
            "content": self.content,
            "skill_name": self.skill_name,
            "tenant_id": self.tenant_id,
            "user_id": self.user_id,
            "session_id": self.session_id,
            "agent_id": self.agent_id,
            "priority": self.priority.value,
            "status": self.status.value,
            "created_at": self.created_at,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "response": self.response[:10000] if self.response else "",  # Truncate long responses
            "error": self.error,
            "duration_ms": str(self.duration_ms),
        }
    
    @classmethod
    def from_redis_hash(cls, data: Dict[str, str]) -> 'ChatTask':
        """Reconstruct from Redis HASH."""
        return cls(
            id=data.get("id", ""),
            content=data.get("content", ""),
            skill_name=data.get("skill_name", ""),
            tenant_id=data.get("tenant_id", ""),
            user_id=data.get("user_id", ""),
            session_id=data.get("session_id", ""),
            agent_id=data.get("agent_id", "enterprise_agent"),
            priority=TaskPriority(data.get("priority", "medium")),
            status=TaskStatus(data.get("status", "pending")),
            created_at=data.get("created_at", ""),
            started_at=data.get("started_at", ""),
            completed_at=data.get("completed_at", ""),
            response=data.get("response", ""),
            error=data.get("error", ""),
            duration_ms=float(data.get("duration_ms", 0)),
        )


class TaskIntegration:
    """
    Integration layer that makes tasks visible in Redis.
    
    This is a "hybrid" approach:
    - Tasks are recorded in Redis (for visibility)
    - Execution happens inline (no separate worker needed)
    - Original queue_manager still handles concurrency
    
    Redis Keys Created:
    - iaf:chat:task:<id>     - Task details (HASH)
    - iaf:chat:history:<user> - Recent task IDs (LIST)
    - iaf:chat:active        - Currently processing (SET)
    """
    
    def __init__(
        self,
        redis_url: str = "redis://localhost:6379",
        key_prefix: str = "iaf:chat",
        history_limit: int = 100,
        enabled: bool = True
    ):
        self.redis_url = redis_url
        self.key_prefix = key_prefix
        self.history_limit = history_limit
        self.enabled = enabled
        self._redis = None
        self._connected = False
    
    async def connect(self):
        """Connect to Redis (lazy, will retry if failed)."""
        if self._connected:
            return True
        
        try:
            import redis.asyncio as aioredis
            self._redis = aioredis.from_url(
                self.redis_url,
                encoding="utf-8",
                decode_responses=True
            )
            await self._redis.ping()
            self._connected = True
            logger.info("✅ TaskIntegration connected to configured Redis endpoint")
            return True
        except Exception as e:
            logger.warning(f"⚠️ TaskIntegration Redis unavailable: {e}")
            self._connected = False
            return False
    
    async def disconnect(self):
        """Disconnect from Redis."""
        if self._redis:
            await self._redis.aclose()
            self._connected = False
    
    # Redis key helpers
    def _task_key(self, task_id: str) -> str:
        return f"{self.key_prefix}:task:{task_id}"
    
    def _history_key(self, user_id: str) -> str:
        return f"{self.key_prefix}:history:{user_id}"
    
    def _active_key(self) -> str:
        return f"{self.key_prefix}:active"
    
    async def _store_task(self, task: ChatTask):
        """Store task in Redis."""
        if not self._connected:
            await self.connect()
        
        if not self._connected:
            return  # Redis unavailable, skip
        
        try:
            await self._redis.hset(
                self._task_key(task.id),
                mapping=task.to_redis_hash()
            )
            
            # Add to user's history (trim to limit)
            await self._redis.lpush(self._history_key(task.user_id), task.id)
            await self._redis.ltrim(self._history_key(task.user_id), 0, self.history_limit - 1)
            
            await self._redis.expire(self._task_key(task.id), 7 * 24 * 3600)
            
        except Exception as e:
            logger.warning(f"Failed to store task in Redis: {e}")
    
    async def _update_task(self, task: ChatTask):
        """Update task status in Redis."""
        if not self._connected:
            return
        
        try:
            await self._redis.hset(
                self._task_key(task.id),
                mapping=task.to_redis_hash()
            )
        except Exception as e:
            logger.warning(f"Failed to update task in Redis: {e}")
    
    async def _mark_active(self, task_id: str):
        """Mark task as actively processing."""
        if self._connected:
            try:
                await self._redis.sadd(self._active_key(), task_id)
            except Exception:
                pass
    
    async def _unmark_active(self, task_id: str):
        """Remove task from active set."""
        if self._connected:
            try:
                await self._redis.srem(self._active_key(), task_id)
            except Exception:
                pass
    
    async def execute_chat(
        self,
        content: str,
        skill_name: str,
        tenant_id: str,
        user_id: str,
        session_id: str,
        agent_runner: Callable[[], Union[Any, Awaitable[Any]]],
        agent_id: str = "enterprise_agent",
        priority: TaskPriority = TaskPriority.MEDIUM,
    ) -> Any:
        """
        Execute a chat task with Redis tracking.
        
        This is the main entry point - use instead of queue_manager.enqueue().
        
        Args:
            content: User's message
            skill_name: Skill being used
            tenant_id: Tenant ID
            user_id: User ID
            session_id: Session ID
            agent_runner: Function that runs the agent (sync or async)
            agent_id: Agent ID
            priority: Task priority
        
        Returns:
            Whatever agent_runner returns
        """
        task = ChatTask(
            id=str(uuid4()),
            content=content,
            skill_name=skill_name,
            tenant_id=tenant_id,
            user_id=user_id,
            session_id=session_id,
            agent_id=agent_id,
            priority=priority,
            status=TaskStatus.PENDING,
        )
        
        # Store in Redis (non-blocking)
        if self.enabled:
            await self._store_task(task)
            logger.info(f"📝 Task created: {task.id[:8]}... [{skill_name}]")
        
        # Mark as processing
        task.status = TaskStatus.PROCESSING
        task.started_at = datetime.now(timezone.utc).isoformat()
        if self.enabled:
            await self._update_task(task)
            await self._mark_active(task.id)
        
        start_time = time.time()
        
        try:
            if asyncio.iscoroutinefunction(agent_runner):
                result = await agent_runner()
            elif asyncio.iscoroutine(agent_runner):
                result = await agent_runner
            else:
                # Run sync function in thread
                result = await asyncio.to_thread(agent_runner)
            
            # Record success
            task.status = TaskStatus.COMPLETED
            task.completed_at = datetime.now(timezone.utc).isoformat()
            task.duration_ms = (time.time() - start_time) * 1000
            
            # Store response (handle tuple from return_tool_calls=True)
            if isinstance(result, tuple):
                task.response = str(result[0])  # First element is the response
            else:
                task.response = str(result)
            
            if self.enabled:
                await self._update_task(task)
                await self._unmark_active(task.id)
                logger.info(f"✅ Task completed: {task.id[:8]}... ({task.duration_ms:.0f}ms)")
            
            return result
            
        except Exception as e:
            # Record failure
            task.status = TaskStatus.FAILED
            task.completed_at = datetime.now(timezone.utc).isoformat()
            task.duration_ms = (time.time() - start_time) * 1000
            task.error = str(e)
            
            if self.enabled:
                await self._update_task(task)
                await self._unmark_active(task.id)
                logger.error(f"❌ Task failed: {task.id[:8]}... - {e}")
            
            raise
    
    
    async def get_task(self, task_id: str) -> Optional[ChatTask]:
        """Get a specific task by ID."""
        if not self._connected:
            await self.connect()
        
        if not self._connected:
            return None
        
        try:
            data = await self._redis.hgetall(self._task_key(task_id))
            if data:
                return ChatTask.from_redis_hash(data)
        except Exception as e:
            logger.warning(f"Failed to get task: {e}")
        
        return None
    
    async def get_user_history(self, user_id: str, limit: int = 20) -> list[ChatTask]:
        """Get recent tasks for a user."""
        if not self._connected:
            await self.connect()
        
        if not self._connected:
            return []
        
        try:
            task_ids = await self._redis.lrange(self._history_key(user_id), 0, limit - 1)
            tasks = []
            for tid in task_ids:
                task = await self.get_task(tid)
                if task:
                    tasks.append(task)
            return tasks
        except Exception as e:
            logger.warning(f"Failed to get user history: {e}")
            return []
    
    async def get_active_tasks(self) -> list[ChatTask]:
        """Get currently processing tasks."""
        if not self._connected:
            await self.connect()
        
        if not self._connected:
            return []
        
        try:
            task_ids = await self._redis.smembers(self._active_key())
            tasks = []
            for tid in task_ids:
                task = await self.get_task(tid)
                if task:
                    tasks.append(task)
            return tasks
        except Exception as e:
            logger.warning(f"Failed to get active tasks: {e}")
            return []
    
    async def get_stats(self) -> Dict[str, Any]:
        """Get task statistics."""
        if not self._connected:
            await self.connect()
        
        if not self._connected:
            return {"error": "Redis not connected"}
        
        try:
            # Count keys
            keys = await self._redis.keys(f"{self.key_prefix}:task:*")
            active = await self._redis.scard(self._active_key())
            
            return {
                "total_tasks": len(keys),
                "active_tasks": active,
                "redis_connected": True,
                "key_prefix": self.key_prefix,
            }
        except Exception as e:
            logger.error("Failed to get task stats: %s", e, exc_info=True)
            return {"error": "An internal error occurred"}


# Singleton instance for easy import
_default_integration: Optional[TaskIntegration] = None


def get_task_integration(redis_url: str = "redis://localhost:6379") -> TaskIntegration:
    """Get or create the default TaskIntegration instance."""
    global _default_integration
    if _default_integration is None:
        _default_integration = TaskIntegration(redis_url=redis_url)
    return _default_integration
