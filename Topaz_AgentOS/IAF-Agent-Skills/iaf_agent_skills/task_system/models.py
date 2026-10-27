"""
Task Models - Serializable data structures for Mode 4.

All models are JSON-serializable, meaning they survive Redis storage
and server restarts. No lambdas, no closures, just data.
"""

from __future__ import annotations
import json
import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, Optional, List


class TaskStatus(str, Enum):
    """Task lifecycle states."""
    PENDING = "pending"          # In queue, waiting to execute
    PROCESSING = "processing"    # Being executed
    COMPLETED = "completed"      # Successfully finished
    FAILED = "failed"            # Failed, may retry
    DLQ = "dlq"                  # Max retries exceeded, in dead letter queue
    CANCELLED = "cancelled"      # Manually cancelled


class TaskPriority(str, Enum):
    """Task priority levels."""
    CRITICAL = "critical"  # Execute immediately (score: 0)
    HIGH = "high"          # Execute soon (score: 1)
    MEDIUM = "medium"      # Normal priority (score: 2)
    LOW = "low"            # Background work (score: 3)
    
    @property
    def score(self) -> int:
        """Get numeric score for Redis ZSET ordering (lower = higher priority)."""
        return {"critical": 0, "high": 1, "medium": 2, "low": 3}[self.value]


@dataclass
class TaskContext:
    """
    Execution context for a task.
    
    Contains all the identity and session info needed to execute
    a task in the correct context, even on a different server.
    """
    tenant_id: str
    user_id: str
    session_id: str
    agent_id: str = "default"
    
    # Optional: for A2A (Agent-to-Agent) communication
    source_agent: str = ""
    callback_url: str = ""
    correlation_id: str = ""
    
    # Execution preferences
    timeout_seconds: int = 300  # 5 minute default
    
    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> TaskContext:
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


@dataclass
class TaskDefinition:
    """
    A fully serializable task definition.
    
    This is THE key to Mode 4: instead of passing a lambda,
    we pass data that describes what to execute.
    
    The TaskExecutor reads this data and routes to the
    appropriate handler based on task_type.
    
    Attributes:
        id: Unique task identifier (auto-generated)
        task_type: Handler routing key ("skill", "tool", "cron", etc.)
        payload: Task-specific data (must be JSON-serializable)
        context: Execution context (tenant, user, session)
        priority: Execution priority
        
    Example:
        task = TaskDefinition(
            task_type="skill",
            payload={"skill_name": "dilo", "input": "log my day"},
            context=TaskContext(tenant_id="acme", user_id="john", session_id="s1")
        )
    """
    task_type: str
    payload: Dict[str, Any]
    context: TaskContext
    
    # Identity
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    
    # Priority & ordering
    priority: TaskPriority = TaskPriority.MEDIUM
    
    # Lifecycle
    status: TaskStatus = TaskStatus.PENDING
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    
    # Retry handling
    retry_count: int = 0
    max_retries: int = 3
    
    # Error tracking
    error_message: str = ""
    error_traceback: str = ""
    
    # Lane/queue routing
    lane: str = "default"
    
    def to_dict(self) -> Dict[str, Any]:
        """Serialize to JSON-compatible dict for Redis storage."""
        return {
            "id": self.id,
            "task_type": self.task_type,
            "payload": json.dumps(self.payload),  # JSON string for nested dict
            "context": json.dumps(self.context.to_dict()),
            "priority": self.priority.value,
            "status": self.status.value,
            "created_at": self.created_at.isoformat(),
            "started_at": self.started_at.isoformat() if self.started_at else "",
            "completed_at": self.completed_at.isoformat() if self.completed_at else "",
            "retry_count": str(self.retry_count),
            "max_retries": str(self.max_retries),
            "error_message": self.error_message,
            "error_traceback": self.error_traceback,
            "lane": self.lane,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> TaskDefinition:
        """Deserialize from Redis storage."""
        return cls(
            id=data["id"],
            task_type=data["task_type"],
            payload=json.loads(data["payload"]),
            context=TaskContext.from_dict(json.loads(data["context"])),
            priority=TaskPriority(data.get("priority", "medium")),
            status=TaskStatus(data.get("status", "pending")),
            created_at=datetime.fromisoformat(data["created_at"]) if data.get("created_at") else datetime.now(timezone.utc),
            started_at=datetime.fromisoformat(data["started_at"]) if data.get("started_at") else None,
            completed_at=datetime.fromisoformat(data["completed_at"]) if data.get("completed_at") else None,
            retry_count=int(data.get("retry_count", 0)),
            max_retries=int(data.get("max_retries", 3)),
            error_message=data.get("error_message", ""),
            error_traceback=data.get("error_traceback", ""),
            lane=data.get("lane", "default"),
        )
    
    def to_json(self) -> str:
        """Serialize to JSON string."""
        return json.dumps(self.to_dict())
    
    @classmethod
    def from_json(cls, json_str: str) -> TaskDefinition:
        """Deserialize from JSON string."""
        return cls.from_dict(json.loads(json_str))


@dataclass
class TaskResult:
    """
    Result of task execution.
    
    Stored separately from TaskDefinition so results can be
    retrieved without loading the full task data.
    """
    task_id: str
    status: TaskStatus
    
    # Success data
    output: Any = None
    
    # Timing
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    duration_ms: float = 0.0
    
    # Error data (if failed)
    error_message: str = ""
    error_traceback: str = ""
    
    # Metadata
    handler_name: str = ""
    retry_count: int = 0
    
    def to_dict(self) -> Dict[str, Any]:
        """Serialize for Redis storage."""
        return {
            "task_id": self.task_id,
            "status": self.status.value,
            "output": json.dumps(self.output) if self.output else "",
            "started_at": self.started_at.isoformat() if self.started_at else "",
            "completed_at": self.completed_at.isoformat() if self.completed_at else "",
            "duration_ms": str(self.duration_ms),
            "error_message": self.error_message,
            "error_traceback": self.error_traceback,
            "handler_name": self.handler_name,
            "retry_count": str(self.retry_count),
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> TaskResult:
        """Deserialize from Redis."""
        output = None
        if data.get("output"):
            try:
                output = json.loads(data["output"])
            except json.JSONDecodeError:
                output = data["output"]
        
        return cls(
            task_id=data["task_id"],
            status=TaskStatus(data.get("status", "pending")),
            output=output,
            started_at=datetime.fromisoformat(data["started_at"]) if data.get("started_at") else None,
            completed_at=datetime.fromisoformat(data["completed_at"]) if data.get("completed_at") else None,
            duration_ms=float(data.get("duration_ms", 0)),
            error_message=data.get("error_message", ""),
            error_traceback=data.get("error_traceback", ""),
            handler_name=data.get("handler_name", ""),
            retry_count=int(data.get("retry_count", 0)),
        )
    
    @property
    def is_success(self) -> bool:
        return self.status == TaskStatus.COMPLETED
    
    @property
    def is_failure(self) -> bool:
        return self.status in (TaskStatus.FAILED, TaskStatus.DLQ)


# Convenience factory functions
def skill_task(
    skill_name: str,
    input_text: str,
    context: TaskContext,
    priority: TaskPriority = TaskPriority.MEDIUM,
) -> TaskDefinition:
    """Create a skill execution task."""
    return TaskDefinition(
        task_type="skill",
        payload={"skill_name": skill_name, "input": input_text},
        context=context,
        priority=priority,
        lane=f"skill:{context.tenant_id}",
    )


def tool_task(
    tool_name: str,
    arguments: Dict[str, Any],
    context: TaskContext,
    priority: TaskPriority = TaskPriority.HIGH,
) -> TaskDefinition:
    """Create a tool execution task."""
    return TaskDefinition(
        task_type="tool",
        payload={"tool_name": tool_name, "arguments": arguments},
        context=context,
        priority=priority,
        lane=f"tool:{context.tenant_id}",
    )


def cron_task(
    job_id: str,
    job_config: Dict[str, Any],
    context: TaskContext,
    priority: TaskPriority = TaskPriority.LOW,
) -> TaskDefinition:
    """Create a cron/scheduled job task."""
    return TaskDefinition(
        task_type="cron",
        payload={"job_id": job_id, "config": job_config},
        context=context,
        priority=priority,
        lane=f"cron:{context.tenant_id}",
    )
