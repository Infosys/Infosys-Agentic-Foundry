"""
Scheduler Data Models

Enterprise-grade job and run tracking with full audit trail.
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional, Dict, Any, List
from enum import Enum
import uuid


class RunStatus(str, Enum):
    """Job run status."""
    PENDING = "pending"      # Scheduled but not yet started
    RUNNING = "running"      # Currently executing
    SUCCESS = "success"      # Completed successfully
    FAILED = "failed"        # Completed with error
    TIMEOUT = "timeout"      # Exceeded max runtime
    CANCELLED = "cancelled"  # Manually cancelled
    SKIPPED = "skipped"      # Skipped (e.g., previous run still going)


@dataclass
class Schedule:
    """Cron schedule with human-readable helpers."""
    cron: str  # Standard cron expression (5 or 6 fields)
    timezone: str = "UTC"
    
    # Common presets
    @classmethod
    def every_minute(cls) -> "Schedule":
        return cls(cron="* * * * *")
    
    @classmethod
    def every_5_minutes(cls) -> "Schedule":
        return cls(cron="*/5 * * * *")
    
    @classmethod
    def every_hour(cls) -> "Schedule":
        return cls(cron="0 * * * *")
    
    @classmethod
    def daily_at(cls, hour: int, minute: int = 0) -> "Schedule":
        return cls(cron=f"{minute} {hour} * * *")
    
    @classmethod
    def weekly_on(cls, day: str, hour: int = 9) -> "Schedule":
        """day: mon, tue, wed, thu, fri, sat, sun"""
        days = {"mon": 1, "tue": 2, "wed": 3, "thu": 4, "fri": 5, "sat": 6, "sun": 0}
        day_num = days.get(day.lower(), 1)
        return cls(cron=f"0 {hour} * * {day_num}")
    
    @classmethod
    def monthly_on(cls, day: int, hour: int = 9) -> "Schedule":
        return cls(cron=f"0 {hour} {day} * *")
    
    def describe(self) -> str:
        """Human-readable description of the schedule."""
        parts = self.cron.split()
        if len(parts) < 5:
            return self.cron
        
        minute, hour, dom, month, dow = parts[:5]
        
        # Common patterns
        if self.cron == "* * * * *":
            return "Every minute"
        if minute.startswith("*/") and hour == "*":
            interval = minute.split("/")[1]
            return f"Every {interval} minutes"
        if minute == "0" and hour == "*":
            return "Every hour"
        if minute == "0" and dom == "*" and month == "*" and dow == "*":
            return f"Daily at {hour}:00"
        if dow != "*" and dom == "*":
            days = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"]
            day_name = days[int(dow)] if dow.isdigit() else dow
            return f"Weekly on {day_name} at {hour}:{minute.zfill(2)}"
        if dom != "*" and dow == "*":
            return f"Monthly on day {dom} at {hour}:{minute.zfill(2)}"
        
        return self.cron


@dataclass
class RetryPolicy:
    """Retry configuration for failed jobs."""
    max_retries: int = 3
    initial_delay_seconds: int = 60
    max_delay_seconds: int = 3600
    backoff_multiplier: float = 2.0
    
    def get_delay(self, attempt: int) -> int:
        """Calculate delay for given attempt (1-indexed)."""
        delay = self.initial_delay_seconds * (self.backoff_multiplier ** (attempt - 1))
        return min(int(delay), self.max_delay_seconds)


@dataclass
class Job:
    """
    Scheduled job definition.
    
    Immutable job configuration that defines what to run and when.
    """
    # Core identity
    id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    name: str = ""
    
    # What to run
    skill_name: str = ""  # Skill to execute
    task: str = ""        # Task/prompt to send to the skill
    params: Dict[str, Any] = field(default_factory=dict)  # Additional parameters
    
    # When to run
    cron: str = "0 * * * *"  # Default: every hour
    timezone: str = "UTC"
    
    # Context
    tenant_id: str = "company"
    agent_id: str = "enterprise_agent"
    user_id: str = "scheduler"
    
    # Configuration
    enabled: bool = True
    max_runtime_seconds: int = 300  # 5 minute timeout
    retry_policy: Optional[RetryPolicy] = None
    
    # Metadata
    description: str = ""
    tags: List[str] = field(default_factory=list)
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    created_by: str = ""
    
    # Runtime state (not persisted in job, but tracked separately)
    last_run_at: Optional[datetime] = None
    next_run_at: Optional[datetime] = None
    consecutive_failures: int = 0
    
    @property
    def schedule(self) -> Schedule:
        return Schedule(cron=self.cron, timezone=self.timezone)
    
    def to_dict(self) -> Dict[str, Any]:
        """Serialize for storage."""
        return {
            "id": self.id,
            "name": self.name,
            "skill_name": self.skill_name,
            "task": self.task,
            "params": self.params,
            "cron": self.cron,
            "timezone": self.timezone,
            "tenant_id": self.tenant_id,
            "agent_id": self.agent_id,
            "user_id": self.user_id,
            "enabled": self.enabled,
            "max_runtime_seconds": self.max_runtime_seconds,
            "retry_policy": {
                "max_retries": self.retry_policy.max_retries,
                "initial_delay_seconds": self.retry_policy.initial_delay_seconds,
                "max_delay_seconds": self.retry_policy.max_delay_seconds,
                "backoff_multiplier": self.retry_policy.backoff_multiplier,
            } if self.retry_policy else None,
            "description": self.description,
            "tags": self.tags,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "created_by": self.created_by,
            "last_run_at": self.last_run_at.isoformat() if self.last_run_at else None,
            "next_run_at": self.next_run_at.isoformat() if self.next_run_at else None,
            "consecutive_failures": self.consecutive_failures,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Job":
        """Deserialize from storage."""
        retry_data = data.get("retry_policy")
        retry_policy = RetryPolicy(**retry_data) if retry_data else None
        
        return cls(
            id=data.get("id", str(uuid.uuid4())[:8]),
            name=data.get("name", ""),
            skill_name=data.get("skill_name", ""),
            task=data.get("task", ""),
            params=data.get("params", {}),
            cron=data.get("cron", "0 * * * *"),
            timezone=data.get("timezone", "UTC"),
            tenant_id=data.get("tenant_id", "company"),
            agent_id=data.get("agent_id", "enterprise_agent"),
            user_id=data.get("user_id", "scheduler"),
            enabled=data.get("enabled", True),
            max_runtime_seconds=data.get("max_runtime_seconds", 300),
            retry_policy=retry_policy,
            description=data.get("description", ""),
            tags=data.get("tags", []),
            created_at=datetime.fromisoformat(data["created_at"]) if data.get("created_at") else datetime.now(timezone.utc),
            updated_at=datetime.fromisoformat(data["updated_at"]) if data.get("updated_at") else datetime.now(timezone.utc),
            created_by=data.get("created_by", ""),
            last_run_at=datetime.fromisoformat(data["last_run_at"]) if data.get("last_run_at") else None,
            next_run_at=datetime.fromisoformat(data["next_run_at"]) if data.get("next_run_at") else None,
            consecutive_failures=data.get("consecutive_failures", 0),
        )


@dataclass
class JobRun:
    """
    Record of a single job execution.
    
    Immutable after creation - represents historical run.
    """
    id: str = field(default_factory=lambda: str(uuid.uuid4())[:12])
    job_id: str = ""
    job_name: str = ""  # Denormalized for easier querying
    
    # Execution details
    status: RunStatus = RunStatus.PENDING
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    duration_seconds: Optional[float] = None
    
    # Input/Output
    input_task: str = ""
    output_response: Optional[str] = None
    error_message: Optional[str] = None
    
    # Retry info
    attempt: int = 1
    retry_of: Optional[str] = None  # ID of failed run this is retrying
    
    # Trigger info
    triggered_by: str = "scheduler"  # "scheduler" | "manual" | "retry"
    scheduled_time: Optional[datetime] = None  # When it was supposed to run
    
    def to_dict(self) -> Dict[str, Any]:
        """Serialize for storage."""
        return {
            "id": self.id,
            "job_id": self.job_id,
            "job_name": self.job_name,
            "status": self.status.value,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "duration_seconds": self.duration_seconds,
            "input_task": self.input_task,
            "output_response": self.output_response,
            "error_message": self.error_message,
            "attempt": self.attempt,
            "retry_of": self.retry_of,
            "triggered_by": self.triggered_by,
            "scheduled_time": self.scheduled_time.isoformat() if self.scheduled_time else None,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "JobRun":
        """Deserialize from storage."""
        return cls(
            id=data.get("id", str(uuid.uuid4())[:12]),
            job_id=data.get("job_id", ""),
            job_name=data.get("job_name", ""),
            status=RunStatus(data.get("status", "pending")),
            started_at=datetime.fromisoformat(data["started_at"]) if data.get("started_at") else None,
            completed_at=datetime.fromisoformat(data["completed_at"]) if data.get("completed_at") else None,
            duration_seconds=data.get("duration_seconds"),
            input_task=data.get("input_task", ""),
            output_response=data.get("output_response"),
            error_message=data.get("error_message"),
            attempt=data.get("attempt", 1),
            retry_of=data.get("retry_of"),
            triggered_by=data.get("triggered_by", "scheduler"),
            scheduled_time=datetime.fromisoformat(data["scheduled_time"]) if data.get("scheduled_time") else None,
        )
