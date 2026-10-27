"""
IAF Agent Studio — WebSocket fan-out broadcaster.

Deliberately has zero dependency on Redis/Postgres/kernel bootstrap so it
can be imported and unit-tested in isolation from the rest of `shared.state`.

Used for the dashboard, twin, and command-center queue push channels, where
each client is a `starlette.websockets.WebSocket`.
"""

import asyncio
import logging
from datetime import datetime

logger = logging.getLogger("iaf_server")

_DEFAULT_SEND_TIMEOUT = 5.0  # seconds — bounds one stuck/dead client's impact on everyone else


class WebSocketBroadcaster:
    """Fan-out broadcaster for a set of WebSocket clients.

    connect()/disconnect() only ever hold the lock for an in-memory set
    mutation. broadcast() snapshots the client set under the lock, then
    sends OUTSIDE the lock with a bounded per-client timeout — a slow or
    dead client can no longer stall delivery to everyone else, nor block a
    concurrent connect()/disconnect() waiting on the same lock.
    """

    def __init__(self, label: str, send_timeout: float = _DEFAULT_SEND_TIMEOUT):
        self._clients: set = set()
        self._lock = asyncio.Lock()
        self._label = label
        self._send_timeout = send_timeout

    async def connect(self, ws) -> None:
        """Register a client."""
        async with self._lock:
            self._clients.add(ws)
        logger.info("%s client connected (%d total)", self._label, len(self._clients))

    async def disconnect(self, ws) -> None:
        """Unregister a client."""
        async with self._lock:
            self._clients.discard(ws)
        logger.info("%s client disconnected (%d total)", self._label, len(self._clients))

    async def broadcast(self, event: dict) -> None:
        """Send event to all connected clients."""
        async with self._lock:
            targets = list(self._clients)
        if not targets:
            return
        event["server_ts"] = datetime.now().isoformat()
        dead: list = []
        for ws in targets:
            try:
                await asyncio.wait_for(ws.send_json(event), timeout=self._send_timeout)
            except Exception:
                dead.append(ws)
        if dead:
            async with self._lock:
                for ws in dead:
                    self._clients.discard(ws)

    @property
    def client_count(self) -> int:
        return len(self._clients)


class DashboardBroadcaster(WebSocketBroadcaster):
    """
    Broadcasts real-time events to all connected dashboard WebSocket clients.

    Events:
      - approval_new / approval_resolved
      - task_started / task_completed
      - cron_started / cron_completed
      - agent_active
    """

    def __init__(self):
        super().__init__(label="Dashboard")


class TwinBroadcaster(WebSocketBroadcaster):
    """
    Broadcasts real-time operational events to Digital Twin dashboard clients.

    Connected via /ws/twin — pushes task lifecycle, HITL, and skill usage
    events so the twin.html dashboard updates live without polling.
    """

    def __init__(self):
        super().__init__(label="Twin")
