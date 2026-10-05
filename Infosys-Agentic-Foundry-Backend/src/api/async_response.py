# © 2024-25 Infosys Limited, Bangalore, India. All Rights Reserved.
"""
Flag-based async response mode for long-running endpoints.

Some deployments sit behind a gateway with a hard request timeout (e.g. 60s),
and certain endpoints (agent/tool onboarding, LLM-heavy inference) can exceed
it. Instead of holding the HTTP connection open, an endpoint decorated with
``@supports_async(...)`` can — when the client passes ``?async_response_mode=true``
— return a ``task_id`` immediately (HTTP 202) and run the actual work in the
background. The client then polls ``GET /tasks/async/{task_id}`` for the result.

This is intentionally independent of the message-queue / M2M subsystem: the work
runs in-process on the pod that accepted the request, and all coordination state
lives in the ``async_tasks`` database table so any pod can serve a poll.

Concurrency is bounded PER POD by an in-memory admission controller:
- ``N`` (ASYNC_RESPONSE_MAX_RUNNING): tasks allowed to execute concurrently.
- ``M`` (ASYNC_RESPONSE_MAX_QUEUED): tasks allowed to wait in memory for a slot.
Once ``N + M`` is exceeded, new submissions are rejected with HTTP 429.
"""
import asyncio
import contextvars
import functools
import inspect
import uuid
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import JSONResponse

from src.api.dependencies import ServiceProvider
from src.auth.dependencies import get_current_user
from src.auth.models import User
from src.config.constants import AsyncResponseConfig
from src.database.services.async_task_service import AsyncTaskService
from telemetry_wrapper import logger as log

# Values the query param may take to enable async mode.
_TRUTHY = {"true", "1", "yes", "on"}

# Keeps strong references to in-flight background tasks so they are not garbage
# collected before completion (asyncio only holds weak references).
_BACKGROUND_TASKS: set = set()


class AsyncModeController:
    """
    Per-pod admission and concurrency controller for async-mode tasks.

    - ``_sem`` caps how many tasks EXECUTE at once (N).
    - ``_inflight`` counts admitted tasks (running + queued) to enforce N + M
      and decide when to reject with 429.
    """

    def __init__(self, max_running: int, max_queued: int):
        self._sem = asyncio.Semaphore(max(1, max_running))
        self._limit = max(1, max_running) + max(0, max_queued)
        self._inflight = 0
        self._lock = asyncio.Lock()

    async def try_admit(self) -> bool:
        """Reserve a slot. Returns False if the pod is at capacity (N + M)."""
        async with self._lock:
            if self._inflight >= self._limit:
                return False
            self._inflight += 1
            return True

    async def release(self):
        """Release a previously admitted slot."""
        async with self._lock:
            if self._inflight > 0:
                self._inflight -= 1

    def running_slot(self):
        """Async context manager that occupies one of the N running slots."""
        return self._sem


# Single per-process controller instance.
controller = AsyncModeController(
    max_running=AsyncResponseConfig.ASYNC_RESPONSE_MAX_RUNNING,
    max_queued=AsyncResponseConfig.ASYNC_RESPONSE_MAX_QUEUED,
)


def _extract_request(args, kwargs) -> Optional[Request]:
    """Locate the FastAPI Request among the handler's resolved parameters."""
    req = kwargs.get("request")
    if isinstance(req, Request):
        return req
    for value in list(kwargs.values()) + list(args):
        if isinstance(value, Request):
            return value
    return None


def _is_async_mode(request: Optional[Request]) -> bool:
    if request is None:
        return False
    return request.query_params.get("async_response_mode", "").strip().lower() in _TRUTHY


def supports_async(task_type: str):
    """
    Decorator that adds opt-in async-response behaviour to an endpoint.

    When ``?async_response_mode=true`` is present, the wrapped handler is run in
    a background task and a ``task_id`` is returned immediately; otherwise the
    handler runs synchronously exactly as before (zero behaviour change).

    Args:
        task_type: A short label stored with the task (e.g. ``"agent_onboard"``)
            so the generic polling endpoint can identify the operation type.
    """
    retention = AsyncResponseConfig.ASYNC_RESPONSE_RESULT_RETENTION_HOURS

    def decorator(func):
        # Inspect the real handler signature once. Only inject the query param
        # if the endpoint doesn't already declare it itself.
        orig_sig = inspect.signature(func)
        _injected = "async_response_mode" not in orig_sig.parameters

        @functools.wraps(func)
        async def wrapper(*args, **kwargs):
            # Pull the flag. If WE injected it, pop it so it isn't forwarded to
            # the wrapped handler (which doesn't declare it); otherwise leave it.
            if _injected:
                async_flag = kwargs.pop("async_response_mode", False)
            else:
                async_flag = kwargs.get("async_response_mode", False)

            request = _extract_request(args, kwargs)

            # Synchronous path — unchanged existing behaviour.
            if not (bool(async_flag) or _is_async_mode(request)):
                return await func(*args, **kwargs)

            # Admission control (per-pod). Reject early if at capacity.
            if not await controller.try_admit():
                raise HTTPException(
                    status_code=429,
                    detail="Server is at capacity for async tasks. Please retry shortly.",
                )

            user_data = kwargs.get("user_data")
            created_by = getattr(user_data, "email", None)
            task_id = f"async_{task_type}_{uuid.uuid4().hex[:12]}"

            async_task_service = ServiceProvider.get_async_task_service()
            registered = await async_task_service.create_task(
                task_id=task_id, task_type=task_type, created_by=created_by
            )
            if not registered:
                await controller.release()
                raise HTTPException(status_code=500, detail="Failed to register async task.")

            async def _run():
                try:
                    async with controller.running_slot():
                        await async_task_service.mark_processing(task_id)
                        try:
                            result = await func(*args, **kwargs)
                        except HTTPException as he:
                            await async_task_service.mark_failed(
                                task_id, f"HTTP {he.status_code}: {he.detail}", retention
                            )
                            return
                        except Exception as exc:  # noqa: BLE001
                            log.error(f"Async task '{task_id}' failed: {exc}", exc_info=True)
                            await async_task_service.mark_failed(task_id, str(exc), retention)
                            return
                        await async_task_service.mark_completed(task_id, result, retention)
                finally:
                    await controller.release()

            # Run within a copy of the current context so ContextVars (user,
            # session, request-id, telemetry) propagate into the background task.
            ctx = contextvars.copy_context()
            try:
                bg = asyncio.create_task(_run(), context=ctx)
            except TypeError:
                # Older event loops without the context kwarg still copy the
                # current context by default.
                bg = asyncio.create_task(_run())
            _BACKGROUND_TASKS.add(bg)
            bg.add_done_callback(_BACKGROUND_TASKS.discard)

            log.info(f"Async task '{task_id}' ({task_type}) accepted for background processing.")
            return JSONResponse(
                status_code=202,
                content={
                    "task_id": task_id,
                    "task_type": task_type,
                    "status": "queued",
                    "message": (
                        f"Task accepted for async processing. "
                        f"Poll GET /tasks/async/{task_id} for status and result."
                    ),
                },
            )

        # Advertise `async_response_mode` as a query parameter on the wrapper's
        # signature so FastAPI renders it in Swagger — without each endpoint
        # having to declare it. FastAPI builds its schema from inspect.signature.
        if _injected:
            extra_param = inspect.Parameter(
                "async_response_mode",
                kind=inspect.Parameter.KEYWORD_ONLY,
                default=Query(
                    False,
                    description="If true, return a task_id immediately and process the request in the background.",
                ),
                annotation=bool,
            )
            params = list(orig_sig.parameters.values())
            var_kw = [p for p in params if p.kind == inspect.Parameter.VAR_KEYWORD]
            non_var = [p for p in params if p.kind != inspect.Parameter.VAR_KEYWORD]
            wrapper.__signature__ = orig_sig.replace(parameters=non_var + [extra_param] + var_kw)

        return wrapper

    return decorator


# ---------------------------------------------------------------------------
# Generic polling endpoint (shared by every async-enabled endpoint)
# ---------------------------------------------------------------------------

router = APIRouter(prefix="/tasks/async", tags=["Async Tasks"])


@router.get("/{task_id}")
async def get_async_task_endpoint(
    task_id: str,
    async_task_service: AsyncTaskService = Depends(ServiceProvider.get_async_task_service),
    user_data: User = Depends(get_current_user),
):
    """
    Poll the status/result of an async task submitted with
    ``?async_response_mode=true``.

    Returns ``status`` of ``queued`` | ``processing`` | ``completed`` | ``failed``.
    When ``completed``, the original endpoint's response is under ``result``.
    Only the user who created the task may read it.
    """
    result = await async_task_service.get_task(task_id, requesting_user=user_data.email)
    if not result.get("success"):
        message = result.get("message", "")
        if "not authorized" in message.lower():
            raise HTTPException(status_code=403, detail=message)
        raise HTTPException(status_code=404, detail=message or f"Task '{task_id}' not found.")
    return result


# ---------------------------------------------------------------------------
# Housekeeping: reaper (mark orphaned tasks failed) + cleanup (delete expired)
# ---------------------------------------------------------------------------

async def run_async_task_housekeeping_loop(async_task_service: AsyncTaskService):
    """
    Periodic background loop: marks tasks stuck in queued/processing (e.g. after
    a pod restart) as failed, and deletes expired completed/failed rows.

    Multi-pod safe: both operations are idempotent single UPDATE/DELETE
    statements guarded by time conditions.
    """
    interval_seconds = 300  # run every 5 minutes
    timeout_minutes = AsyncResponseConfig.ASYNC_RESPONSE_STUCK_TIMEOUT_MINUTES
    retention_hours = AsyncResponseConfig.ASYNC_RESPONSE_RESULT_RETENTION_HOURS
    while True:
        try:
            await async_task_service.reap_stuck_tasks(timeout_minutes, retention_hours)
            await async_task_service.cleanup_expired()
        except Exception as exc:  # noqa: BLE001
            log.error(f"Async task housekeeping loop error: {exc}", exc_info=True)
        await asyncio.sleep(interval_seconds)
