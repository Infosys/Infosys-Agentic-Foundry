"""
REST API endpoints for Smart Code Executor.

All endpoints are under /agentos/code-executor/* and follow the same
patterns as the existing AgentOS endpoints.
"""

import logging
import uuid
from typing import Dict, List, Optional

from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel, Field

from src.agentos.code_executor.config import CodeExecutorConfig
from src.agentos.code_executor.executor import SmartCodeExecutor
from src.auth.dependencies import get_current_user
from src.auth.models import User
from telemetry_wrapper import update_session_context

logger = logging.getLogger("agentos.code_executor.endpoints")

# ---------------------------------------------------------------------------
# Router
# ---------------------------------------------------------------------------

code_executor_router = APIRouter(
    prefix="/code-executor",
    tags=["AgentOS - Smart Code Executor"],
)

# Singleton executor instance (lazy-initialized)
_executor: Optional[SmartCodeExecutor] = None


def _get_executor() -> SmartCodeExecutor:
    """Get or create the singleton SmartCodeExecutor."""
    global _executor
    if _executor is None:
        _executor = SmartCodeExecutor()
    return _executor


# ---------------------------------------------------------------------------
# Request / Response schemas
# ---------------------------------------------------------------------------

class ExecuteTaskRequest(BaseModel):
    """Request to execute a goal-driven task."""
    goal: str = Field(..., description="Natural-language description of what the code should do.")
    language: Optional[str] = Field(None, description="Language hint: python, javascript, bash. Auto-detected if omitted.")
    files: Optional[Dict[str, str]] = Field(None, description="Optional input files: {filename: content}.")
    tenant_id: str = Field(default="default", description="Tenant ID for workspace isolation.")
    async_mode: bool = Field(default=False, description="If true, queues the task and returns a task_id for polling.")
    use_cache: bool = Field(default=True, description="Whether to use cached results.")


class ExecuteCodeRequest(BaseModel):
    """Request to execute exact code."""
    code: str = Field(..., description="Source code to execute.")
    language: str = Field(default="python", description="Programming language.")
    tenant_id: str = Field(default="default", description="Tenant ID.")


class TaskActionRequest(BaseModel):
    """Request for task operations."""
    tenant_id: Optional[str] = Field(default=None, description="Tenant ID for access control.")


class ConfigUpdateRequest(BaseModel):
    """Partial config update."""
    config: Dict = Field(..., description="Config dict (partial, merged into existing).")


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@code_executor_router.post("/execute", summary="Execute a goal-driven task")
async def execute_task(request: ExecuteTaskRequest, user_data: User = Depends(get_current_user)):
    """
    Generate and execute code from a natural-language goal.

    The executor:
    1. Detects the programming language (or uses the hint)
    2. Checks cache for identical prior executions
    3. Generates code via LLM
    4. Executes in a sandboxed subprocess
    5. Auto-recovers from errors (installs packages, fixes code via LLM)
    6. Returns the output, generated code, and any created files

    If `async_mode=True`, returns a task_id immediately for polling via GET /task/{task_id}.
    """
    # Generate correlation ID for LLM tracking
    correlation_request_id = f"code_exec_{request.tenant_id}_{str(uuid.uuid4())[:8]}"
    
    # Set session context for LLM tracking (using authenticated user's email)
    update_session_context(
        user_id=user_data.email,
        session_id=f"{user_data.email}_{request.tenant_id}",
        user_session=f"{user_data.email}_{request.tenant_id}",
        call_category="agentos_code_execution",
        request_id=correlation_request_id
    )
    
    executor = _get_executor()
    try:
        result = await executor.execute_task(
            goal=request.goal,
            tenant_id=request.tenant_id,
            files=request.files,
            language=request.language,
            async_mode=request.async_mode,
            use_cache=request.use_cache,
        )
        return result
    except Exception as exc:
        logger.error(f"Execute task error: {exc}")
        raise HTTPException(status_code=500, detail=str(exc))
    finally:
        # Cleanup session context
        update_session_context(
            user_id='Unassigned',
            session_id='Unassigned',
            user_session='Unassigned',
            call_category='Unassigned',
            request_id='Unassigned'
        )


@code_executor_router.post("/execute-code", summary="Execute exact code")
async def execute_code(request: ExecuteCodeRequest):
    """
    Execute exact code in a sandboxed subprocess (no LLM generation).
    Use this when you already have the code to run.
    """
    executor = _get_executor()
    try:
        result = await executor.execute_code(
            code=request.code,
            language=request.language,
            tenant_id=request.tenant_id,
        )
        return result
    except Exception as exc:
        logger.error(f"Execute code error: {exc}")
        raise HTTPException(status_code=500, detail=str(exc))


@code_executor_router.get("/task/{task_id}", summary="Get async task status")
async def get_task_status(task_id: str, tenant_id: Optional[str] = None):
    """Poll the status of an async code execution task."""
    executor = _get_executor()
    result = await executor.get_task_status(task_id, tenant_id)
    if result is None:
        raise HTTPException(status_code=404, detail=f"Task {task_id} not found")
    return result


@code_executor_router.delete("/task/{task_id}", summary="Cancel async task")
async def cancel_task(task_id: str, tenant_id: Optional[str] = None):
    """Cancel a running or queued async task."""
    executor = _get_executor()
    success = await executor.cancel_task(task_id, tenant_id)
    if not success:
        raise HTTPException(status_code=404, detail=f"Task {task_id} not found or already finished")
    return {"success": True, "task_id": task_id, "message": "Task cancelled"}


@code_executor_router.get("/tasks", summary="List all tasks")
async def list_tasks(tenant_id: Optional[str] = None):
    """List all tasks, optionally filtered by tenant_id."""
    executor = _get_executor()
    tasks = executor.list_tasks(tenant_id)
    return {"tasks": tasks, "count": len(tasks)}


@code_executor_router.get("/health", summary="Health check")
async def health_check():
    """Check the health of all executor components (LLM, backend, cache)."""
    executor = _get_executor()
    try:
        health = await executor.health_check()
        return health
    except Exception as exc:
        return {"status": "error", "error": str(exc)}


@code_executor_router.get("/capabilities", summary="Get executor capabilities")
async def get_capabilities():
    """Return supported languages, features, and limits."""
    executor = _get_executor()
    return executor.get_capabilities()


@code_executor_router.get("/cache/stats", summary="Cache statistics")
async def cache_stats():
    """Return hit/miss statistics for both cache layers."""
    executor = _get_executor()
    return executor._cache.stats()


@code_executor_router.post("/cache/clear", summary="Clear all caches")
async def clear_caches():
    """Clear both the goal→code and goal→result caches."""
    executor = _get_executor()
    executor._cache.clear_all()
    return {"status": "success", "message": "All caches cleared"}


@code_executor_router.post("/config", summary="Update executor configuration")
async def update_config(request: ConfigUpdateRequest):
    """
    Update executor configuration at runtime.
    Accepts a partial config dict that gets merged into the current config.
    Restarts async workers if async config changes.
    """
    global _executor
    try:
        new_config = CodeExecutorConfig.from_dict(request.config)

        # Shut down existing executor
        if _executor:
            await _executor.shutdown()

        _executor = SmartCodeExecutor(config=new_config)
        await _executor.initialize()

        return {"status": "success", "message": "Configuration updated, executor restarted"}
    except Exception as exc:
        logger.error(f"Config update error: {exc}")
        raise HTTPException(status_code=400, detail=str(exc))


@code_executor_router.get("/config", summary="Get current configuration")
async def get_config():
    """Return the current executor configuration (sanitized)."""
    executor = _get_executor()
    cfg = executor.config
    return {
        "llm": {
            "model_name": cfg.llm.model_name,
            "temperature": cfg.llm.temperature,
            "max_tokens": cfg.llm.max_tokens,
        },
        "execution": {
            "backend": cfg.execution.backend,
            "timeout_per_attempt": cfg.execution.timeout_per_attempt,
            "total_timeout": cfg.execution.total_timeout,
            "max_attempts": cfg.execution.max_attempts,
        },
        "cache": {
            "enabled": cfg.cache.enabled,
            "goal_cache_ttl": cfg.cache.goal_cache_ttl,
            "result_cache_ttl": cfg.cache.result_cache_ttl,
        },
        "async": {
            "enabled": cfg.async_config.enabled,
            "worker_count": cfg.async_config.worker_count,
        },
        "workspace": {
            "base_path": cfg.workspace.base_path,
            "cleanup_policy": cfg.workspace.cleanup_policy,
        },
        "auto_recovery": {
            "install_packages": cfg.auto_recovery.install_packages,
            "max_install_retries": cfg.auto_recovery.max_install_retries,
        },
    }
