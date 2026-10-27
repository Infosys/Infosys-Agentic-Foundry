"""Cooperative run-cancellation registry.

Why this exists
---------------
The WebSocket chat handler runs ``agent.run`` synchronously in a worker thread
(``asyncio.to_thread``). When the user clicks "Stop" in the UI, the handler can
only cancel the *asyncio task* that is awaiting the thread — it cannot forcibly
kill the thread itself (Python has no safe thread-kill). So without cooperation
the agent keeps making LLM calls, running tools, SQL and shell commands in the
background even though the UI says "Stopped".

This module is that cooperation point: the caller registers a ``run_id`` before
starting the agent, passes ``make_check(run_id)`` into ``agent.run`` as
``cancel_check``, and on Stop calls ``request_cancel(run_id)``. The agent polls
the flag at its loop boundaries (before each LLM call / tool batch / step) and
aborts by raising :class:`RunCancelled`, which ``agent.run`` turns into a clean
partial "stopped" response.

The registry is process-local and thread-safe. run_ids are short-lived (one per
chat turn); ``end()`` clears them so the set never grows unbounded.
"""

from __future__ import annotations

import threading
from typing import Callable

_lock = threading.Lock()
_cancelled: set[str] = set()
_active: set[str] = set()

_tls = threading.local()


class RunCancelled(BaseException):
    """Raised inside ``agent.run`` when a cooperative cancel has been requested.

    Subclasses ``BaseException`` (like ``asyncio.CancelledError``) on purpose so
    the many ``except Exception:`` blocks in the agent's stream/tool/governance
    loops do NOT swallow it — it must propagate up to ``run()``, which converts it
    into a clean "stopped" response. Only ``run()`` catches it.
    """


def begin(run_id: str) -> None:
    """Mark a run as active and clear any stale cancel flag for a reused id."""
    if not run_id:
        return
    with _lock:
        _cancelled.discard(run_id)
        _active.add(run_id)


def request_cancel(run_id: str) -> bool:
    """Flag a run for cancellation. Returns True if the run was currently active."""
    if not run_id:
        return False
    with _lock:
        was_active = run_id in _active
        _cancelled.add(run_id)
        return was_active


def is_cancelled(run_id: str) -> bool:
    """Cheap poll used by the agent loop; safe to call very frequently."""
    if not run_id:
        return False
    with _lock:
        return run_id in _cancelled


def end(run_id: str) -> None:
    """Remove all state for a finished run (call in a finally block)."""
    if not run_id:
        return
    with _lock:
        _active.discard(run_id)
        _cancelled.discard(run_id)


def make_check(run_id: str) -> Callable[[], bool]:
    """Return a zero-arg predicate the agent can poll to see if it should stop."""
    return lambda: is_cancelled(run_id)



def get_current() -> "Callable[[], bool] | None":
    """Return the cancel predicate bound to the current thread (or None)."""
    return getattr(_tls, "check", None)


def bind_current(check: "Callable[[], bool] | None") -> None:
    """Bind a cancel predicate to the current thread for this run.

    A None check does NOT clear an existing binding — that way a nested
    agent.run() (e.g. via the invoke_skill tool) invoked without its own
    cancel_check inherits the parent run's cancel flag instead of wiping it.
    """
    if check is not None:
        _tls.check = check


def restore_current(previous: "Callable[[], bool] | None") -> None:
    """Restore the thread's cancel predicate to a previously-captured value.

    Use with get_current() around a run so nested runs restore the parent's
    binding on exit rather than clearing it. Worker threads are pooled and
    reused, so top-level runs must restore to None to avoid leaking a stale
    predicate into the next run on the same thread.
    """
    _tls.check = previous


def unbind_current() -> None:
    """Clear the current thread's cancel predicate."""
    _tls.check = None


def check_cancelled() -> None:
    """Raise :class:`RunCancelled` if the current thread's run was cancelled.

    Cheap enough to call at every loop iteration and before every tool call.
    """
    check = getattr(_tls, "check", None)
    if check is not None and check():
        raise RunCancelled()
