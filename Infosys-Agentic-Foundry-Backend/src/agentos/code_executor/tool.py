"""
LangChain tool wrappers for Smart Code Executor.

Exposes code execution capabilities as StructuredTools that can be
included in any LangGraph/LangChain agent's toolset — especially
in SKILL.md-based agents via `tools: [execute_code, execute_task]`.
"""

import asyncio
import json
import logging
from typing import Dict, List, Optional

from langchain_core.tools import BaseTool, StructuredTool
from pydantic import BaseModel, Field

from src.agentos.code_executor.executor import SmartCodeExecutor

logger = logging.getLogger("agentos.code_executor.tool")


# ---------------------------------------------------------------------------
# Pydantic input schemas for tools
# ---------------------------------------------------------------------------

class ExecuteTaskInput(BaseModel):
    """Input for the execute_task tool."""
    goal: str = Field(description="Natural-language description of what the code should accomplish.")
    language: Optional[str] = Field(
        None, description="Programming language: python, javascript, or bash. Auto-detected if omitted."
    )
    files: Optional[Dict[str, str]] = Field(
        None, description="Optional dict of filename → file content to place in the execution workspace."
    )


class ExecuteCodeInput(BaseModel):
    """Input for the execute_code tool."""
    code: str = Field(description="The exact source code to execute.")
    language: str = Field(default="python", description="Programming language: python, javascript, or bash.")


class GetTaskStatusInput(BaseModel):
    """Input for the get_task_status tool."""
    task_id: str = Field(description="The task ID returned from an async execute_task call.")


class CancelTaskInput(BaseModel):
    """Input for the cancel_task tool."""
    task_id: str = Field(description="The task ID to cancel.")


class ExecuteTaskAsyncInput(BaseModel):
    """Input for async task submission."""
    goal: str = Field(description="Natural-language description of what the code should accomplish.")
    language: Optional[str] = Field(
        None, description="Programming language: python, javascript, or bash."
    )
    files: Optional[Dict[str, str]] = Field(
        None, description="Optional dict of filename → file content."
    )


# ---------------------------------------------------------------------------
# Tool factory
# ---------------------------------------------------------------------------

def create_code_executor_tools(
    executor: SmartCodeExecutor,
    tenant_id: str = "default",
) -> List[BaseTool]:
    """
    Create LangChain StructuredTools that wrap the SmartCodeExecutor.

    These tools can be injected into any agent's toolset. For SKILL.md agents,
    add `execute_task` and/or `execute_code` to the skill's `tools:` list.

    Args:
        executor: A SmartCodeExecutor instance.
        tenant_id: Tenant ID for workspace isolation.

    Returns:
        List of 5 LangChain tools:
          - execute_task: Goal → LLM code gen → execute → result
          - execute_code: Direct code execution
          - execute_task_async: Submit goal for background execution
          - get_task_status: Poll async task
          - cancel_task: Cancel async task
    """
    tools: List[BaseTool] = []

    # ----- execute_task (sync) -----
    def execute_task_func(
        goal: str,
        language: Optional[str] = None,
        files: Optional[Dict[str, str]] = None,
    ) -> str:
        """Execute a goal: describe what you want in English, and code will be generated and run automatically.
        Returns the execution output or error. Best for data analysis, file processing, calculations, and automation."""
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                import concurrent.futures
                with concurrent.futures.ThreadPoolExecutor() as pool:
                    result = pool.submit(
                        asyncio.run,
                        executor.execute_task(
                            goal=goal, tenant_id=tenant_id,
                            files=files, language=language,
                            async_mode=False, use_cache=True,
                        )
                    ).result(timeout=executor.config.execution.total_timeout + 10)
            else:
                result = loop.run_until_complete(
                    executor.execute_task(
                        goal=goal, tenant_id=tenant_id,
                        files=files, language=language,
                        async_mode=False, use_cache=True,
                    )
                )
            return json.dumps(result, indent=2, default=str)
        except Exception as exc:
            return json.dumps({"success": False, "error": str(exc)})

    tools.append(StructuredTool.from_function(
        func=execute_task_func,
        name="execute_task",
        description=(
            "Generate and execute code from a natural-language goal. "
            "Describe what you want (e.g., 'analyze sales data in sales.csv and show top products'), "
            "and code will be automatically generated and run. "
            "Supports Python, JavaScript, and Bash. Auto-recovers from errors."
        ),
        args_schema=ExecuteTaskInput,
    ))

    # ----- execute_code (direct) -----
    def execute_code_func(code: str, language: str = "python") -> str:
        """Execute exact code directly. Use when you have specific code to run rather than a goal."""
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                import concurrent.futures
                with concurrent.futures.ThreadPoolExecutor() as pool:
                    result = pool.submit(
                        asyncio.run,
                        executor.execute_code(
                            code=code, language=language, tenant_id=tenant_id,
                        )
                    ).result(timeout=executor.config.execution.timeout_per_attempt + 10)
            else:
                result = loop.run_until_complete(
                    executor.execute_code(
                        code=code, language=language, tenant_id=tenant_id,
                    )
                )
            return json.dumps(result, indent=2, default=str)
        except Exception as exc:
            return json.dumps({"success": False, "error": str(exc)})

    tools.append(StructuredTool.from_function(
        func=execute_code_func,
        name="execute_code",
        description=(
            "Execute exact code in a sandboxed environment. "
            "Provide the complete source code and language. "
            "Use this when you already have code to run, not for goal-based generation."
        ),
        args_schema=ExecuteCodeInput,
    ))

    # ----- execute_task_async -----
    def execute_task_async_func(
        goal: str,
        language: Optional[str] = None,
        files: Optional[Dict[str, str]] = None,
    ) -> str:
        """Submit a goal for background execution. Returns a task_id for polling."""
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                import concurrent.futures
                with concurrent.futures.ThreadPoolExecutor() as pool:
                    result = pool.submit(
                        asyncio.run,
                        executor.execute_task(
                            goal=goal, tenant_id=tenant_id,
                            files=files, language=language,
                            async_mode=True,
                        )
                    ).result(timeout=10)
            else:
                result = loop.run_until_complete(
                    executor.execute_task(
                        goal=goal, tenant_id=tenant_id,
                        files=files, language=language,
                        async_mode=True,
                    )
                )
            return json.dumps(result, indent=2, default=str)
        except Exception as exc:
            return json.dumps({"success": False, "error": str(exc)})

    tools.append(StructuredTool.from_function(
        func=execute_task_async_func,
        name="execute_task_async",
        description=(
            "Submit a goal for background code execution. "
            "Returns a task_id immediately. Use get_task_status to poll for results."
        ),
        args_schema=ExecuteTaskAsyncInput,
    ))

    # ----- get_task_status -----
    def get_task_status_func(task_id: str) -> str:
        """Check the status of an async code execution task."""
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                import concurrent.futures
                with concurrent.futures.ThreadPoolExecutor() as pool:
                    result = pool.submit(
                        asyncio.run,
                        executor.get_task_status(task_id, tenant_id)
                    ).result(timeout=5)
            else:
                result = loop.run_until_complete(
                    executor.get_task_status(task_id, tenant_id)
                )
            if result is None:
                return json.dumps({"error": f"Task {task_id} not found"})
            return json.dumps(result, indent=2, default=str)
        except Exception as exc:
            return json.dumps({"error": str(exc)})

    tools.append(StructuredTool.from_function(
        func=get_task_status_func,
        name="get_task_status",
        description="Check the status and result of an async code execution task by task_id.",
        args_schema=GetTaskStatusInput,
    ))

    # ----- cancel_task -----
    def cancel_task_func(task_id: str) -> str:
        """Cancel a running or queued async task."""
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                import concurrent.futures
                with concurrent.futures.ThreadPoolExecutor() as pool:
                    success = pool.submit(
                        asyncio.run,
                        executor.cancel_task(task_id, tenant_id)
                    ).result(timeout=5)
            else:
                success = loop.run_until_complete(
                    executor.cancel_task(task_id, tenant_id)
                )
            return json.dumps({"success": success, "task_id": task_id})
        except Exception as exc:
            return json.dumps({"success": False, "error": str(exc)})

    tools.append(StructuredTool.from_function(
        func=cancel_task_func,
        name="cancel_task",
        description="Cancel a running or queued async code execution task.",
        args_schema=CancelTaskInput,
    ))

    return tools
