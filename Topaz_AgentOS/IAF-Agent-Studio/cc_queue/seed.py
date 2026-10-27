"""
Command Center — Demo data seeder.

Inserts 4 pre-built ITOps scenarios into queue_items.
Uses external_id for idempotency — re-running seed never duplicates.

Called by:
  - POST /api/queue/simulate   (dashboard "Simulate Demo" button)
  - Server startup when QUEUE_SEED_DEMO=true in config.env
"""

import uuid
import logging

logger = logging.getLogger(__name__)

_DEMO_ITEMS = [
    {
        "external_id": "DEMO-ITOPS-001",
        "title": "Disk at 91% on prod-app-07",
        "description": (
            "Alert: Disk usage on prod-app-07 has reached 91% on /var/log partition. "
            "Application is throwing DiskWriteException. Orders are failing. "
            "Deployed v2.4.1 approximately 6 hours ago. Need RCA and remediation."
        ),
        "entity_id": "prod-app-07",
        "priority": "P1",
        "domain": "itops",
        "source": "simulated",
    },
    {
        "external_id": "DEMO-ITOPS-002",
        "title": "Batch job failed — billing-reconciliation OOM",
        "description": (
            "billing-reconciliation batch job failed at row 7,823,441 with OutOfMemoryError. "
            "Job was processing 12.4M records. SLA breach in approximately 45 minutes. "
            "Last successful run was yesterday at 02:15 UTC."
        ),
        "entity_id": "prod-batch-01",
        "priority": "P2",
        "domain": "itops",
        "source": "simulated",
    },
    {
        "external_id": "DEMO-ITOPS-003",
        "title": "Memory leak on prod-order-01 — heap at 84%",
        "description": (
            "prod-order-01 heap utilization is at 84% and climbing. "
            "GC pause times increasing (avg 2.3s). Connection pool exhausted intermittently. "
            "Order processing latency up 340%. Pod has been running for 18 days without restart."
        ),
        "entity_id": "prod-order-01",
        "priority": "P2",
        "domain": "itops",
        "source": "simulated",
    },
    {
        "external_id": "DEMO-ITOPS-004",
        "title": "P1 — Multi-host degradation across prod-app-07 and prod-order-01",
        "description": (
            "Multiple production hosts are degraded simultaneously. "
            "prod-app-07: disk 91%, DiskWriteException, orders failing. "
            "prod-order-01: heap 84%, connection pool exhausted. "
            "Downstream impact: payment-gateway timeouts, customer-facing errors. "
            "Need full parallel RCA across all affected hosts."
        ),
        "entity_id": "prod-app-07,prod-order-01",
        "priority": "P1",
        "domain": "itops",
        "source": "simulated",
    },
]


class QueueSeedError(RuntimeError):
    """Raised when the demo seed could not queue any item because of hard
    (DB/backend) failures — lets the API surface a real error instead of a
    misleading 200 with ``queued=0`` (Copilot #7 / RT-4)."""


# Resetting an in-progress status would clear its claim and allow duplicate execution.
_IN_FLIGHT_STATUSES = {"routing", "running", "awaiting_human"}


def _tenant_external_id(tenant_id: str, external_id: str) -> str:
    """Tenant-qualify the demo ``external_id``. ``queue_items.external_id`` is
    globally UNIQUE, so sharing the raw ``DEMO-ITOPS-00N`` id across tenants meant
    one tenant's Simulate Demo re-owned another tenant's rows (Copilot #3). Scoping
    the dedup key by tenant gives every tenant its own isolated demo set."""
    return f"{tenant_id}::{external_id}"


def seed_demo_items(tenant_id: str = "company") -> int:
    """
    Insert (or re-queue) the demo items for ``tenant_id``. Returns the number of
    demo items now sitting in the queue ready to process for THIS tenant.

    Re-runnable by design (RT-4): the demo ``external_id`` is tenant-qualified and
    globally unique, so once a tenant's demo items exist a plain insert is a no-op
    — and if a previous run left them ``failed`` or ``done`` the queue looks empty
    and the button appears broken. When an item already exists for this tenant we
    reset it to ``queued`` so the demo is runnable again, but ONLY if it is not
    currently in-flight (``routing``/``running``/``awaiting_human``) — resetting a
    live item would cause duplicate execution (Copilot #4). Tenant isolation:
    re-seeding never touches another tenant's rows (Copilot #3).

    Raises ``QueueSeedError`` if hard backend failures prevented every item from
    being queued, so the caller can report a real failure (Copilot #7).
    """
    from cc_queue.db import get_db
    db = get_db()
    ready = 0
    errors: list[str] = []

    for template in _DEMO_ITEMS:
        ext_id = _tenant_external_id(tenant_id, template["external_id"])
        item = {
            "id": f"CC-{uuid.uuid4().hex[:8].upper()}",
            "tenant_id": tenant_id,
            "trace_id": uuid.uuid4().hex,
            **template,
            "external_id": ext_id,
            "status": "queued",
        }
        try:
            if db.insert_item(item):
                ready += 1
                logger.info("Seeded demo item: %s", ext_id)
                continue
            # Already present for this tenant. Re-queue it so the demo is runnable
            # again — unless it is currently in-flight, in which case leave it be.
            existing = db.get_item_by_external_id(ext_id)
            if not existing:
                continue
            if existing.get("status") in _IN_FLIGHT_STATUSES:
                ready += 1  # already live and being processed — counts as ready
                logger.info("Demo item in-flight, not resetting: %s", ext_id)
                continue
            db.update_item(
                existing["id"],
                tenant_id=tenant_id,
                status="queued",
                retry_count=0,
                routed_skill=None,
                routing_reason=None,
            )
            ready += 1
            logger.info("Re-queued existing demo item: %s", ext_id)
        except Exception as e:
            logger.warning("Seed failed for %s: %s", ext_id, e)
            errors.append(f"{ext_id}: {e}")

    logger.info("Queue seed complete: %d demo items queued", ready)
    if errors and ready == 0:
        raise QueueSeedError("; ".join(errors))
    return ready
