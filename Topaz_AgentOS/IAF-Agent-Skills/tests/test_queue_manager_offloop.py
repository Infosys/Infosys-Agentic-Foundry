"""A queued blocking task must not freeze the event loop.

Eight call sites enqueue `lambda: agent.run(...)` — a blocking call that makes LLM and
tool calls for seconds to minutes. The queue used to call it directly on the event loop,
so every other request (other users, WebSockets, /health/live) waited until it finished.
These tests prove plain callables now run on a worker thread, async callables still run
on the loop, and per-lane serialisation (max_concurrent=1) is unchanged.
"""

from __future__ import annotations

import asyncio
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from iaf_agent_skills.queue_manager import MemoryQueueManager, QueueConfig  # noqa: E402


def _qm() -> MemoryQueueManager:
    return MemoryQueueManager(QueueConfig())


def test_blocking_task_runs_off_the_event_loop_thread():
    async def main():
        loop_thread = threading.get_ident()
        task_thread = await _qm().enqueue("lane:a", lambda: threading.get_ident())
        return loop_thread, task_thread

    loop_thread, task_thread = asyncio.run(main())
    assert task_thread != loop_thread


def test_event_loop_stays_responsive_while_a_blocking_task_runs():
    """A 1.5 s blocking task; a 50 ms ticker on the loop must keep ticking meanwhile."""
    async def main():
        ticks = []

        async def ticker():
            ticks.append(time.monotonic())  # baseline BEFORE the blocking task starts
            for _ in range(40):
                await asyncio.sleep(0.05)
                ticks.append(time.monotonic())

        t = asyncio.create_task(ticker())
        await asyncio.sleep(0)  # let the ticker take its baseline reading
        result = await _qm().enqueue("lane:b", lambda: (time.sleep(1.5), "done")[1])
        await t
        gaps = [b - a for a, b in zip(ticks, ticks[1:])]
        return result, max(gaps)

    result, worst_gap = asyncio.run(main())
    assert result == "done"
    assert worst_gap < 0.5, f"event loop stalled for {worst_gap:.2f}s"


def test_async_task_still_runs_on_the_loop():
    async def main():
        loop_thread = threading.get_ident()

        async def task():
            return threading.get_ident()

        return loop_thread, await _qm().enqueue("lane:c", task)

    loop_thread, task_thread = asyncio.run(main())
    assert task_thread == loop_thread


def test_lane_still_serialises_blocking_tasks():
    """max_concurrent=1 is SAFETY-CRITICAL (shared agent state); threads must not break it."""
    async def main():
        qm = _qm()
        active = 0
        peak = 0
        lock = threading.Lock()

        def work():
            nonlocal active, peak
            with lock:
                active += 1
                peak = max(peak, active)
            time.sleep(0.1)
            with lock:
                active -= 1
            return True

        await asyncio.gather(*(qm.enqueue("lane:d", work, max_concurrent=1) for _ in range(4)))
        return peak

    assert asyncio.run(main()) == 1


def test_task_exceptions_still_propagate():
    def boom():
        raise ValueError("kaboom")

    async def main():
        try:
            await _qm().enqueue("lane:e", boom)
        except ValueError as exc:
            return str(exc)
        return None

    assert asyncio.run(main()) == "kaboom"
