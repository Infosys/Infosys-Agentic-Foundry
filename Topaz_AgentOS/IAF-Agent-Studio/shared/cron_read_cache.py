"""Shared cron read model — one cache for scheduler reads.

`/api/cron` is polled every ~30s per focused browser tab AND read by the every-15s
ops-summary provider, and the underlying scheduler calls are synchronous Redis walks.
This module gives both callers ONE place to read jobs/status so a multi-tab burst
collapses into a single Redis walk, and every scheduler mutation — wherever it happens
(the cron router, workstream reconcile, standalone reconcile) — invalidates it so the
next read reflects the write.

Guarantees (all verified in tests/test_cron_read_cache.py):
  * **Offloaded** — the sync scheduler call runs in a worker thread, never on the loop.
  * **Short TTL** (~3s) — a just-created/toggled job surfaces within a couple seconds.
  * **Single-flight** — concurrent misses coalesce onto one in-flight read.
  * **Generation-guarded** — a result whose read started before an ``invalidate()`` is
    discarded, so a slow pre-mutation read can't repopulate stale data afterwards.
  * **Cancellation-safe** — a cancelled read clears its in-flight slot (``finally``),
    so it never poisons the key for later callers.

The caches are bounded by cardinality (jobs keyed by (tenant, enabled_only); status a
single key), so no size purge is needed here. Runs on the single API event loop; the
non-awaiting bookkeeping is atomic under cooperative scheduling, so no lock is required.
(See docs/PERF_NAVIGATION_INVESTIGATION.md, Evidence 6.)
"""

from __future__ import annotations

import asyncio
import time
from typing import Any, Awaitable, Callable

CACHE_TTL = 3.0

_jobs_cache: dict = {}        # (tenant, enabled_only) -> (monotonic_ts, jobs)
_status_cache: dict = {}      # "status" -> (monotonic_ts, status)
_jobs_inflight: dict = {}     # key -> asyncio.Future
_status_inflight: dict = {}   # key -> asyncio.Future
_generation = 0


def invalidate() -> None:
    """Drop cached cron reads and bump the generation.

    Bumping the generation makes any in-flight, pre-mutation read discard its result
    instead of repopulating stale data after the mutation. Call this from EVERY
    scheduler mutation path (create/update/delete/enable/disable/start/stop, plus the
    workstream and standalone reconcilers) for read-your-write.
    """
    global _generation
    _generation += 1
    _jobs_cache.clear()
    _status_cache.clear()


def reset() -> None:
    """Clear all cache/in-flight state (test isolation)."""
    global _generation
    _generation = 0
    _jobs_cache.clear()
    _status_cache.clear()
    _jobs_inflight.clear()
    _status_inflight.clear()


async def _cached_read(
    cache: dict,
    inflight: dict,
    key: Any,
    compute: Callable[[], Awaitable[Any]],
) -> Any:
    """Serve ``key`` from ``cache`` within the TTL, else compute it once (single-flight),
    cancellation-safe, and only publish if no invalidation raced the read."""
    hit = cache.get(key)
    if hit is not None and (time.monotonic() - hit[0]) < CACHE_TTL:
        return hit[1]

    fut = inflight.get(key)
    creator = fut is None
    gen_at_start = _generation
    if creator:
        fut = asyncio.ensure_future(compute())
        inflight[key] = fut
    try:
        value = await fut
    finally:
        # The owner clears the in-flight slot even on error/cancellation, so a failed
        # or cancelled read never strands the key for later callers.
        if creator and inflight.get(key) is fut:
            inflight.pop(key, None)

    # Only the creator publishes, and only if no mutation invalidated mid-read.
    if creator and _generation == gen_at_start:
        cache[key] = (time.monotonic(), value)
    return value


async def get_jobs(
    list_jobs: Callable[..., list], tenant: str, enabled_only: bool
) -> list:
    """Tenant's jobs, offloaded to a thread and served from the shared TTL cache."""
    key = (tenant, enabled_only)
    return await _cached_read(
        _jobs_cache,
        _jobs_inflight,
        key,
        lambda: asyncio.to_thread(list_jobs, tenant_id=tenant, enabled_only=enabled_only),
    )


async def get_status(get_status_fn: Callable[[], dict]) -> dict:
    """Scheduler status, offloaded to a thread and served from the shared TTL cache."""
    return await _cached_read(
        _status_cache,
        _status_inflight,
        "status",
        lambda: asyncio.to_thread(get_status_fn),
    )
