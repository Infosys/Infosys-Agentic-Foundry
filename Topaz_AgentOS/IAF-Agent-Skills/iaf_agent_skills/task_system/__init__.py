"""
Task System - True Mode 4 with Data-Based Tasks.

This module provides restart-survivable task execution:
- Tasks are DATA (not lambdas) - fully serializable to Redis
- Tasks survive server restarts
- Multi-server support (any server can execute any task)
- At-least-once delivery guaranteed

Architecture:
    ┌──────────────┐     ┌──────────────┐     ┌──────────────┐
    │   Client     │────▶│ TaskQueue    │────▶│ TaskExecutor │
    │  .submit()   │     │ (Redis)      │     │  (Worker)    │
    └──────────────┘     └──────────────┘     └──────────────┘
                                                     │
                         ┌───────────────────────────┼───────────────────────────┐
                         │                           │                           │
                         ▼                           ▼                           ▼
                  ┌──────────────┐           ┌──────────────┐           ┌──────────────┐
                  │ SkillHandler │           │ ToolHandler  │           │ CronHandler  │
                  └──────────────┘           └──────────────┘           └──────────────┘

Usage:
    from iaf_agent_skills.task_system import TaskQueue, TaskExecutor, TaskDefinition
    
    # Submit a task (from API endpoint)
    queue = TaskQueue(redis_url="redis://localhost:6379")
    task_id = await queue.submit(TaskDefinition(
        task_type="skill",
        payload={"skill_name": "dilo", "input": "log my day"},
        context=TaskContext(tenant_id="acme", user_id="john", session_id="abc123")
    ))
    
    # Run executor (in background worker or same process)
    executor = TaskExecutor(queue)
    executor.register(SkillHandler(kernel))
    await executor.run()  # Polls queue and executes
    
    # Get result
    result = await queue.get_result(task_id)
"""

from .models import (
    TaskDefinition,
    TaskContext,
    TaskResult,
    TaskStatus,
    TaskPriority,
)
from .protocol import TaskHandler
from .queue import TaskQueue
from .executor import TaskExecutor
from .handlers import SkillHandler, ToolHandler, CronHandler

__all__ = [
    # Models
    "TaskDefinition",
    "TaskContext", 
    "TaskResult",
    "TaskStatus",
    "TaskPriority",
    # Core
    "TaskHandler",
    "TaskQueue",
    "TaskExecutor",
    # Handlers
    "SkillHandler",
    "ToolHandler",
    "CronHandler",
]
