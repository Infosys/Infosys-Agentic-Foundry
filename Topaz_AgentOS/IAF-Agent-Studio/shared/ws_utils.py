"""Small, dependency-light WebSocket helpers.

Kept out of ``routers/chat.py`` so the sendability check can be unit-tested without
importing the whole chat router (which pulls in DB/emitter side effects at import).
"""

from __future__ import annotations


def ws_is_sendable(websocket) -> bool:
    """Return ``True`` only when both peers still consider the socket ``CONNECTED``.

    Used to short-circuit token streaming once a client has navigated away, so a
    closed socket doesn't produce a burst of failed sends for every remaining token.

    Fails **open** (returns ``True``) when the connection state can't be read — if we
    can't prove the socket is closed we still attempt the send rather than silently
    dropping a live one.
    """
    try:
        from starlette.websockets import WebSocketState

        return (
            websocket.application_state == WebSocketState.CONNECTED
            and websocket.client_state == WebSocketState.CONNECTED
        )
    except Exception:
        return True


class WsSendGate:
    """Latching gate for a single WebSocket turn.

    ``allow()`` returns ``True`` only while the socket is worth sending to. Once the
    socket is not ``CONNECTED`` or a send has failed (``mark_closed()``), the gate
    LATCHES closed so the rest of a streaming turn short-circuits instead of
    re-attempting a dead socket for every remaining token. Extracted here (rather than
    living as a closure in the chat router) so the latch behaviour is unit-testable
    without importing the whole router.
    """

    __slots__ = ("_ws", "_closed")

    def __init__(self, websocket) -> None:
        self._ws = websocket
        self._closed = False

    def allow(self) -> bool:
        """True if a send should be attempted now; latches closed once it isn't."""
        if self._closed or not ws_is_sendable(self._ws):
            self._closed = True
            return False
        return True

    def mark_closed(self) -> None:
        """Latch the gate closed (e.g. after a send raised)."""
        self._closed = True
