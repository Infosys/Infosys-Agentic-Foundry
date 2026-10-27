"""Vision worker — plugs the vision event materializer into the durable queue.

This is the transport layer that turns a queued ``vision_event`` task into a
Workstreams row. It deliberately reuses the platform's existing task system
(``TaskExecutor`` / ``TaskHandler`` / DLQ) instead of a bespoke loop:

    edge → TaskQueue.submit(vision_event task)
         → TaskExecutor dequeues → VisionEventHandler.execute(task)   ← HERE
         → handle_vision_event(...) → WorkstreamStore.append_item(...)

Retry/dead-letter semantics (enterprise-correct poison-message handling):
  * MATERIALIZED / DEDUPED  → COMPLETED (ack). Row created (or already there).
  * REJECTED / DENIED       → COMPLETED (ack) but ``materialized=False``. These
    are *permanent* — malformed input or a refused entitlement — so we do NOT
    spin pointless retries; we record the reason in the result output.
  * ERROR (transient)       → raise VisionTransientError → executor retries and
    finally dead-letters after ``max_retries``.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Callable, Optional

from .vision_event_handler import (
    AppendItem,
    EntitlementCheck,
    VisionOutcome,
    handle_vision_event,
)
from .task_system.models import TaskContext, TaskDefinition, TaskPriority, TaskResult, TaskStatus
from .task_system.protocol import TaskHandler

logger = logging.getLogger(__name__)

# The routing key the edge stamps on a task and the executor routes on.
VISION_TASK_TYPE = "vision_event"


class VisionTransientError(RuntimeError):
    """Raised for retryable failures so the executor retries then dead-letters."""


class VisionEventHandler(TaskHandler):
    """TaskHandler for ``vision_event`` tasks. Register it with a TaskExecutor.

    Wiring options (pick one):
      * ``append_item``          — a ready callable (tests / single-tenant).
      * ``tenant_root_resolver`` — ``(tenant_id) -> Path`` to a tenant root; the
        handler lazily builds one ``WorkstreamStore`` per tenant and caches it.
    ``entitlement_check`` is optional and enforces ``vision_allowed`` before any
    row is written.
    """

    def __init__(
        self,
        *,
        append_item: Optional[AppendItem] = None,
        tenant_root_resolver: Optional[Callable[[str], Path]] = None,
        entitlement_check: Optional[EntitlementCheck] = None,
        expected_tenant: Optional[str] = None,
    ):
        if append_item is None and tenant_root_resolver is None:
            raise ValueError("VisionEventHandler needs append_item or tenant_root_resolver")
        self._append_item = append_item
        self._tenant_root_resolver = tenant_root_resolver
        self._entitlement_check = entitlement_check
        self._expected_tenant = expected_tenant
        self._store_cache: dict[str, AppendItem] = {}

    @property
    def task_types(self) -> list[str]:
        return [VISION_TASK_TYPE]

    def _resolve_append_item(self, tenant_id: str) -> AppendItem:
        """Return an append_item bound to the right tenant's WorkstreamStore."""
        if self._append_item is not None:
            return self._append_item
        cached = self._store_cache.get(tenant_id)
        if cached is None:
            from .workstream_store import WorkstreamStore  # lazy: keeps import light
            store = WorkstreamStore(self._tenant_root_resolver(tenant_id))  # type: ignore[misc]
            cached = store.append_item
            self._store_cache[tenant_id] = cached
        return cached

    async def execute(self, task: TaskDefinition) -> TaskResult:
        tenant_id = (getattr(task.context, "tenant_id", "") or "company")
        if self._expected_tenant is not None and tenant_id != self._expected_tenant:
            logger.warning(
                "vision task %s rejected: task tenant %r != handler tenant %r",
                task.id, tenant_id, self._expected_tenant,
            )
            return TaskResult(
                task_id=task.id,
                status=TaskStatus.COMPLETED,
                output={
                    "outcome": VisionOutcome.DENIED.value,
                    "materialized": False,
                    "reason": f"task tenant '{tenant_id}' not served by this worker "
                              f"(tenant '{self._expected_tenant}')",
                },
                handler_name=self.name,
                retry_count=task.retry_count,
            )
        payload = dict(task.payload or {})
        payload.setdefault("tenant_id", tenant_id)

        append_item = self._resolve_append_item(tenant_id)
        result = handle_vision_event(
            payload,
            append_item=append_item,
            entitlement_check=self._entitlement_check,
        )

        output = {
            "outcome": result.outcome.value,
            "materialized": result.ok,
            "workstream": result.workstream,
            "item_id": result.item_id,
            "reason": result.reason,
        }

        if result.outcome == VisionOutcome.ERROR:
            # Transient — let the executor retry and eventually dead-letter.
            raise VisionTransientError(result.reason or "transient vision ingest failure")

        if not result.ok:
            logger.warning("vision task %s not materialized: %s (%s)",
                           task.id, result.outcome.value, result.reason)
        return TaskResult(
            task_id=task.id,
            status=TaskStatus.COMPLETED,
            output=output,
            handler_name=self.name,
            retry_count=task.retry_count,
        )


def make_vision_task(
    event: dict,
    *,
    tenant_id: str = "company",
    user_id: str = "system:vision",
    session_id: str = "vision",
    priority: TaskPriority = TaskPriority.HIGH,
    lane: str = "vision",
    max_retries: int = 3,
) -> TaskDefinition:
    """Build a durable ``vision_event`` task from an event dict (producer side).

    The edge sensor calls this then ``TaskQueue.submit(task)``. Priority defaults
    to HIGH (physical events are usually time-sensitive) on a dedicated ``vision``
    lane so camera bursts don't starve other work.
    """
    return TaskDefinition(
        task_type=VISION_TASK_TYPE,
        payload=dict(event),
        context=TaskContext(tenant_id=tenant_id, user_id=user_id, session_id=session_id),
        priority=priority,
        lane=lane,
        max_retries=max_retries,
    )


def register_vision_handler(executor, **handler_kwargs) -> VisionEventHandler:
    """Convenience: build + register the handler on a TaskExecutor."""
    handler = VisionEventHandler(**handler_kwargs)
    executor.register(handler)
    return handler


def make_platform_entitlement_check(
    tenant_id: str,
    *,
    service: str = "queue",
    action: str = "run",
    resource_type: str = "vision",
    _enforce=None,
    _principal=None,
) -> EntitlementCheck:
    """Build an ``entitlement_check`` backed by the platform entitlement provider.

    This is the ``vision_allowed`` wiring: a camera event is gated by
    ``enforce_entitlement(principal, action, resource_type, workstream)`` under a
    background *service principal* (group ``service:<service>``) before any row is
    written. Grant it via the ``vision-allowed-run-vision-events`` policy.

    ``security.dependencies`` lives on the Studio side, so it is imported lazily —
    the skills-side unit tests inject ``_enforce`` / ``_principal`` and never touch it.
    """
    def check(evt) -> tuple[bool, str]:
        enforce, principal = _enforce, _principal
        if enforce is None or principal is None:
            from security.dependencies import enforce_entitlement, make_service_principal  # lazy
            enforce = enforce or enforce_entitlement
            principal = principal or make_service_principal(tenant_id, service)
        try:
            enforce(principal, action, resource_type, evt.workstream)
            return (True, "")
        except Exception as exc:  # HTTPException(403) or any provider error → deny
            return (False, getattr(exc, "detail", str(exc)))
    return check
