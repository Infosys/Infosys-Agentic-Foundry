#!/usr/bin/env python3
"""Standalone vision worker daemon — the enterprise durable-queue worker.

Drains ``vision_event`` tasks from the durable TaskQueue (Redis) and materializes
each as a Workstream item via WorkstreamStore, gated by the ``vision_allowed``
entitlement. This is a SEPARATE process from the :8082 studio server (exactly like
the scheduler worker), so adding/adjusting it needs no server restart.

    edge → TaskQueue.submit(vision_event) → [THIS DAEMON] TaskExecutor.process_one
        → VisionEventHandler.execute → WorkstreamStore.append_item → visible row

Run (Redis must be up):
    CLONE=<repo_root>
    PYTHONPATH="$CLONE:$CLONE/IAF-Agent-Skills:$CLONE/IAF-Agent-Studio" \
      <venv>/bin/python3 \
      -m iaf_agent_skills.vision_worker_daemon \
        --enterprise-root "$CLONE/enterprise_root" --tenant company --lane vision
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import signal
from pathlib import Path

from .task_system import TaskExecutor, TaskQueue
from .vision_worker import VisionEventHandler, make_platform_entitlement_check

logger = logging.getLogger("iaf.vision_worker")


def build_executor(enterprise_root: str, tenant: str, redis_url: str,
                   key_prefix: str, lane: str, use_entitlement: bool):
    """Wire a TaskExecutor with our VisionEventHandler for the vision lane."""
    queue = TaskQueue(redis_url=redis_url, key_prefix=key_prefix)
    executor = TaskExecutor(queue, lanes=[lane])
    root = Path(enterprise_root)
    handler = VisionEventHandler(
        tenant_root_resolver=lambda t: root / "tenants" / t,
        entitlement_check=make_platform_entitlement_check(tenant) if use_entitlement else None,
        # Entitlement is bound to this one tenant; reject cross-tenant tasks so a task
        # can't be materialized under the wrong principal.
        expected_tenant=tenant if use_entitlement else None,
    )
    executor.register(handler)
    return queue, executor


async def run(args) -> None:
    queue, executor = build_executor(
        args.enterprise_root, args.tenant, args.redis_url,
        args.key_prefix, args.lane, not args.no_entitlement,
    )
    await queue.connect()
    logger.info("vision worker daemon draining lane=%s prefix=%s (entitlement=%s)",
                args.lane, args.key_prefix, not args.no_entitlement)

    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            loop.add_signal_handler(sig, stop.set)
        except NotImplementedError:  # pragma: no cover - platform dependent
            pass

    try:
        while not stop.is_set():
            processed = await executor.process_one(lane=args.lane)
            if not processed:
                await asyncio.sleep(args.poll)   # idle backoff when the lane is empty
    finally:
        await queue.disconnect()
        logger.info("vision worker daemon stopped")


def main() -> None:
    ap = argparse.ArgumentParser(description="Vision worker daemon (durable queue → workstream item).")
    ap.add_argument("--enterprise-root", default=os.environ.get("ENTERPRISE_ROOT", ""),
                    help="Path to enterprise_root (contains tenants/<tenant>/…).")
    ap.add_argument("--tenant", default="company")
    ap.add_argument("--redis-url", default=os.environ.get("REDIS_URL", "redis://localhost:6379"))
    ap.add_argument("--key-prefix", default="iaf:tasks", help="TaskQueue Redis key prefix.")
    ap.add_argument("--lane", default="vision")
    ap.add_argument("--poll", type=float, default=1.0, help="Idle poll interval (s).")
    ap.add_argument("--no-entitlement", action="store_true",
                    help="Skip the vision_allowed check (dev only).")
    args = ap.parse_args()
    if not args.enterprise_root:
        raise SystemExit("--enterprise-root is required (or set ENTERPRISE_ROOT).")

    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
                        datefmt="%Y-%m-%d %H:%M:%S")
    asyncio.run(run(args))


if __name__ == "__main__":
    main()
