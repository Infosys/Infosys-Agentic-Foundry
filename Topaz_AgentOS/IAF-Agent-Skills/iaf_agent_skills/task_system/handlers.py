"""
Built-in Task Handlers for common operations.

These handlers cover the most common task types:
- SkillHandler: Execute skills from SKILL.md files
- ToolHandler: Execute individual tools
- CronHandler: Execute scheduled jobs
- EchoHandler: Simple echo for testing

Each handler:
1. Extracts data from task.payload
2. Performs the work
3. Returns TaskResult
"""

from __future__ import annotations
import logging
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, TYPE_CHECKING

from .models import TaskDefinition, TaskResult, TaskStatus
from .protocol import TaskHandler

if TYPE_CHECKING:
    pass  # Import types only for type checking

logger = logging.getLogger(__name__)


class EchoHandler(TaskHandler):
    """
    Simple echo handler for testing.
    
    Just returns the input payload as output.
    Useful for testing the task system without dependencies.
    
    Payload:
        {"message": "Hello"}
        
    Output:
        {"echo": "Hello", "timestamp": "..."}
    """
    
    @property
    def task_types(self) -> List[str]:
        return ["echo", "test"]
    
    async def execute(self, task: TaskDefinition) -> TaskResult:
        message = task.payload.get("message", "")
        delay = task.payload.get("delay", 0)
        
        if delay > 0:
            import asyncio
            await asyncio.sleep(delay)
        
        # Check for intentional failure (for testing)
        if task.payload.get("fail"):
            raise ValueError(f"Intentional failure: {task.payload.get('fail')}")
        
        return TaskResult(
            task_id=task.id,
            status=TaskStatus.COMPLETED,
            output={
                "echo": message,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "context": {
                    "tenant_id": task.context.tenant_id,
                    "user_id": task.context.user_id,
                }
            },
        )


class SkillHandler(TaskHandler):
    """
    Handler for skill execution tasks.
    
    Loads and executes skills defined in SKILL.md files.
    This is the primary handler for agent interactions.
    
    Payload:
        {
            "skill_name": "dilo",           # Required
            "input": "log my day",          # Required
            "auto_run": false,              # Optional
        }
        
    Output:
        {
            "response": "...",              # Agent response
            "skill_used": "dilo",
            "execution_time_ms": 1234,
        }
        
    Dependencies:
        - SkillAgent (from iaf_agent_skills)
        - SafeKernel (from agent_os)
    """
    
    def __init__(
        self,
        kernel_factory = None,
        skills_path: str = "./skills",
    ):
        """
        Initialize skill handler.
        
        Args:
            kernel_factory: Callable that creates SafeKernel given context
                           Signature: (tenant_id, user_id, agent_id) -> SafeKernel
            skills_path: Path to skills directory
        """
        self._kernel_factory = kernel_factory
        self._skills_path = skills_path
    
    @property
    def task_types(self) -> List[str]:
        return ["skill", "skill_execution"]
    
    async def execute(self, task: TaskDefinition) -> TaskResult:
        start_time = time.time()
        
        skill_name = task.payload.get("skill_name")
        input_text = task.payload.get("input", "")
        auto_run = task.payload.get("auto_run", False)
        
        if not skill_name and not input_text:
            return TaskResult(
                task_id=task.id,
                status=TaskStatus.FAILED,
                error_message="Either skill_name or input is required",
            )
        
        try:
            # Create kernel for this context
            if self._kernel_factory:
                kernel = self._kernel_factory(
                    task.context.tenant_id,
                    task.context.user_id,
                    task.context.agent_id,
                )
            else:
                # Deferred import to avoid circular deps
                from agent_os import create_kernel_runtime
                kernel = create_kernel_runtime(
                    data_root="./data",
                    tenant_id=task.context.tenant_id,
                    agent_id=task.context.agent_id,
                    user_id=task.context.user_id,
                )
            
            from iaf_agent_skills import SkillAgent
            agent = SkillAgent(
                kernel=kernel,
                skills_path=self._skills_path,
                user_id=task.context.user_id,
            )
            agent.auto_run = auto_run
            
            if skill_name:
                # Direct skill execution
                response = agent.run_skill(skill_name, input_text)
            else:
                # Auto-route based on input
                response = agent.run(input_text)
            
            execution_time = (time.time() - start_time) * 1000
            
            return TaskResult(
                task_id=task.id,
                status=TaskStatus.COMPLETED,
                output={
                    "response": response,
                    "skill_used": skill_name or agent.current_skill,
                    "execution_time_ms": execution_time,
                },
            )
        
        except Exception as e:
            import traceback
            return TaskResult(
                task_id=task.id,
                status=TaskStatus.FAILED,
                error_message=str(e),
                error_traceback=traceback.format_exc(),
            )


class ToolHandler(TaskHandler):
    """
    Handler for individual tool execution.
    
    Executes a single tool with given arguments.
    Useful for background tool calls or A2A.
    
    Payload:
        {
            "tool_name": "read_file",
            "arguments": {"path": "/tmp/test.txt"},
        }
        
    Output:
        {
            "result": "file contents...",
            "tool_name": "read_file",
        }
    """
    
    def __init__(self, tool_registry: Optional[Dict[str, Any]] = None):
        """
        Initialize tool handler.
        
        Args:
            tool_registry: Dict mapping tool names to callables
        """
        self._tools = tool_registry or {}
    
    @property
    def task_types(self) -> List[str]:
        return ["tool", "tool_execution"]
    
    def register_tool(self, name: str, func: Any) -> None:
        """Register a tool function."""
        self._tools[name] = func
    
    async def execute(self, task: TaskDefinition) -> TaskResult:
        tool_name = task.payload.get("tool_name")
        arguments = task.payload.get("arguments", {})
        
        if not tool_name:
            return TaskResult(
                task_id=task.id,
                status=TaskStatus.FAILED,
                error_message="tool_name is required",
            )
        
        if tool_name not in self._tools:
            return TaskResult(
                task_id=task.id,
                status=TaskStatus.FAILED,
                error_message=f"Unknown tool: {tool_name}",
            )
        
        try:
            tool_func = self._tools[tool_name]
            
            # Call tool (handle sync and async)
            import asyncio
            if asyncio.iscoroutinefunction(tool_func):
                result = await tool_func(**arguments)
            else:
                result = tool_func(**arguments)
            
            return TaskResult(
                task_id=task.id,
                status=TaskStatus.COMPLETED,
                output={
                    "result": result,
                    "tool_name": tool_name,
                },
            )
        
        except Exception as e:
            import traceback
            return TaskResult(
                task_id=task.id,
                status=TaskStatus.FAILED,
                error_message=str(e),
                error_traceback=traceback.format_exc(),
            )


class CronHandler(TaskHandler):
    """
    Handler for cron/scheduled job execution.
    
    Executes scheduled jobs by looking up job config
    and running the appropriate action.
    
    Payload:
        {
            "job_id": "daily-report",
            "config": {
                "action": "run_skill",
                "skill_name": "report",
                "input": "generate daily report",
            }
        }
        
    Output:
        {
            "job_id": "daily-report",
            "result": {...},
        }
    """
    
    def __init__(self, job_registry: Optional[Dict[str, Any]] = None):
        """
        Initialize cron handler.
        
        Args:
            job_registry: Dict mapping job_id to job configs
        """
        self._jobs = job_registry or {}
    
    @property
    def task_types(self) -> List[str]:
        return ["cron", "scheduled_job"]
    
    async def execute(self, task: TaskDefinition) -> TaskResult:
        job_id = task.payload.get("job_id")
        config = task.payload.get("config", {})
        
        if not job_id:
            return TaskResult(
                task_id=task.id,
                status=TaskStatus.FAILED,
                error_message="job_id is required",
            )
        
        # Merge with registered config if exists
        if job_id in self._jobs:
            registered_config = self._jobs[job_id]
            config = {**registered_config, **config}
        
        action = config.get("action", "log")
        
        try:
            if action == "log":
                # Simple logging action
                logger.info(f"Cron job {job_id} executed: {config}")
                result = {"logged": True, "config": config}
            
            elif action == "run_skill":
                # Delegate to skill execution
                skill_name = config.get("skill_name")
                input_text = config.get("input", "")
                
                if not skill_name:
                    raise ValueError("skill_name required for run_skill action")
                
                # Create skill task and execute inline
                from .models import TaskContext
                skill_task = TaskDefinition(
                    task_type="skill",
                    payload={"skill_name": skill_name, "input": input_text},
                    context=task.context,
                )
                
                # Use SkillHandler (simplified - would need proper injection)
                result = {"delegated_to": "skill", "skill_name": skill_name}
            
            elif action == "webhook":
                import aiohttp
                url = config.get("url")
                if not url:
                    raise ValueError("url required for webhook action")
                
                async with aiohttp.ClientSession() as session:
                    async with session.post(url, json=config.get("data", {})) as resp:
                        result = {"status": resp.status, "body": await resp.text()}
            
            else:
                raise ValueError(f"Unknown action: {action}")
            
            return TaskResult(
                task_id=task.id,
                status=TaskStatus.COMPLETED,
                output={
                    "job_id": job_id,
                    "action": action,
                    "result": result,
                },
            )
        
        except Exception as e:
            import traceback
            return TaskResult(
                task_id=task.id,
                status=TaskStatus.FAILED,
                error_message=str(e),
                error_traceback=traceback.format_exc(),
            )
