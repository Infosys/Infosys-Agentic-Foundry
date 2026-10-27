"""
Task Handler Protocol - Interface for task execution handlers.

Handlers are registered with the TaskExecutor and receive
tasks based on their task_type. This is the Strategy pattern
applied to task execution.

Each handler:
1. Declares what task types it can handle
2. Executes the task using the payload data
3. Returns a TaskResult

Example:
    class SkillHandler(TaskHandler):
        task_types = ["skill"]
        
        async def execute(self, task: TaskDefinition) -> TaskResult:
            skill_name = task.payload["skill_name"]
            input_text = task.payload["input"]
            # ... execute skill ...
            return TaskResult(task_id=task.id, status=TaskStatus.COMPLETED, output=result)
"""

from __future__ import annotations
from abc import ABC, abstractmethod
from typing import List, TYPE_CHECKING

if TYPE_CHECKING:
    from .models import TaskDefinition, TaskResult


class TaskHandler(ABC):
    """
    Abstract base class for task handlers.
    
    Subclass this to create handlers for different task types.
    Register handlers with TaskExecutor to enable execution.
    """
    
    @property
    @abstractmethod
    def task_types(self) -> List[str]:
        """
        List of task types this handler can process.
        
        Returns:
            List of task_type strings (e.g., ["skill", "skill_v2"])
        """
        pass
    
    @property
    def name(self) -> str:
        """Handler name for logging/metrics."""
        return self.__class__.__name__
    
    @abstractmethod
    async def execute(self, task: 'TaskDefinition') -> 'TaskResult':
        """
        Execute the task and return result.
        
        This method should:
        1. Extract needed data from task.payload
        2. Perform the work (may be async/long-running)
        3. Return TaskResult with status and output
        
        If an exception is raised, the executor will:
        - Mark task as FAILED
        - Retry if retry_count < max_retries
        - Move to DLQ if max_retries exceeded
        
        Args:
            task: The task definition with all context
            
        Returns:
            TaskResult with execution outcome
        """
        pass
    
    async def before_execute(self, task: 'TaskDefinition') -> None:
        """
        Hook called before execute(). Override for setup.
        
        Use for:
        - Logging
        - Metrics
        - Validation
        """
        pass
    
    async def after_execute(self, task: 'TaskDefinition', result: 'TaskResult') -> None:
        """
        Hook called after execute(). Override for cleanup.
        
        Use for:
        - Logging
        - Metrics
        - Cleanup
        """
        pass
    
    def can_handle(self, task_type: str) -> bool:
        """Check if this handler can process the given task type."""
        return task_type in self.task_types
