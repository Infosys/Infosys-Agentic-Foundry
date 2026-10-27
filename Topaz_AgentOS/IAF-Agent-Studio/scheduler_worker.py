#!/usr/bin/env python3
"""Standalone scheduler-leader process for enterprise deployments."""

from __future__ import annotations

import asyncio
import os
import signal

os.environ.setdefault("STUDIO_RUNTIME_ROLES", "scheduler")

from server import app, lifespan  # noqa: E402


def _install_signal_handlers(loop: asyncio.AbstractEventLoop, stop_event: asyncio.Event) -> None:
    """Install SIGTERM/SIGINT handlers that trip ``stop_event``.

    Uses ``loop.add_signal_handler`` where available (POSIX) and falls back to
    ``signal.signal`` elsewhere (e.g. Windows), so a normal service stop or
    Ctrl+C unwinds the ``async with lifespan(app)`` block and runs its
    post-yield cleanup instead of killing the process abruptly.
    """
    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            loop.add_signal_handler(sig, stop_event.set)
        except (NotImplementedError, AttributeError, ValueError, RuntimeError):
            try:
                signal.signal(sig, lambda *_: loop.call_soon_threadsafe(stop_event.set))
            except (ValueError, OSError, RuntimeError):
                pass


async def main() -> None:
    loop = asyncio.get_running_loop()
    stop_event = asyncio.Event()
    _install_signal_handlers(loop, stop_event)
    async with lifespan(app):
        await stop_event.wait()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
