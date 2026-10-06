"""
Data models for Smart Code Executor.
All result types, task states, and error analysis structures.
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional


# ---------------------------------------------------------------------------
# Execution results
# ---------------------------------------------------------------------------

@dataclass
class ExecutionResult:
    """Result of a single code execution attempt."""
    success: bool
    output: str = ""
    error: str = ""
    exit_code: int = -1
    execution_time_ms: float = 0.0
    files_created: List[str] = field(default_factory=list)


@dataclass
class TaskResult:
    """Final result of a goal-driven task (may span multiple attempts)."""
    success: bool
    result: str = ""
    error: str = ""
    code: str = ""
    language: str = "python"
    files_created: List[str] = field(default_factory=list)
    execution_time_ms: float = 0.0
    cached: bool = False
    attempts: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "success": self.success,
            "result": self.result,
            "error": self.error,
            "code": self.code,
            "language": self.language,
            "files_created": self.files_created,
            "execution_time_ms": self.execution_time_ms,
            "cached": self.cached,
            "attempts": self.attempts,
        }


# ---------------------------------------------------------------------------
# Error analysis
# ---------------------------------------------------------------------------

class ErrorType(str, Enum):
    MISSING_PACKAGE = "missing_package"
    SYNTAX_ERROR = "syntax_error"
    NAME_ERROR = "name_error"
    TYPE_ERROR = "type_error"
    FILE_NOT_FOUND = "file_not_found"
    TIMEOUT = "timeout"
    RUNTIME_ERROR = "runtime_error"
    PERMISSION_ERROR = "permission_error"


class RecoveryAction(str, Enum):
    INSTALL_PACKAGE = "install_package"
    FIX_CODE = "fix_code"
    RETRY = "retry"
    ABORT = "abort"


@dataclass
class ErrorAnalysis:
    """Result of analyzing an execution error."""
    error_type: ErrorType
    action: RecoveryAction
    recoverable: bool
    package_name: Optional[str] = None  # For install_package actions
    details: str = ""


# ---------------------------------------------------------------------------
# Async task management
# ---------------------------------------------------------------------------

class TaskStatus(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class Task:
    """Represents an async code execution task."""
    task_id: str
    tenant_id: str
    goal: str
    status: TaskStatus = TaskStatus.QUEUED
    progress: int = 0  # 0-100
    result: Optional[TaskResult] = None
    error: Optional[str] = None
    created_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    attempts: int = 0
    language: Optional[str] = None
    files: Optional[Dict[str, str]] = None  # filename → content

    def to_dict(self) -> Dict[str, Any]:
        d = {
            "task_id": self.task_id,
            "tenant_id": self.tenant_id,
            "goal": self.goal,
            "status": self.status.value,
            "progress": self.progress,
            "created_at": self.created_at,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "attempts": self.attempts,
            "language": self.language,
        }
        if self.result:
            d["result"] = self.result.to_dict()
        if self.error:
            d["error"] = self.error
        return d
