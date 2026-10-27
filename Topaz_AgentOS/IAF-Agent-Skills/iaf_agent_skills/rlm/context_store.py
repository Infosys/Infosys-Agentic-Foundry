"""Per-session offloaded-context store for RLM mode.

Holds the large context text out of the model's window, keyed by session id. Bounded
(LRU eviction) so it can't grow unbounded. In-process only — v1 is single-node; a
distributed backend can replace this behind the same interface later.
"""
from __future__ import annotations

import threading

_MAX_SESSIONS = 128  # bound on retained sessions (LRU-evicted)


class ContextStore:
    def __init__(self, max_sessions: int = _MAX_SESSIONS) -> None:
        self._max = max_sessions
        self._text: dict[str, str] = {}
        self._order: list[str] = []
        self._lock = threading.Lock()

    @staticmethod
    def _key(session_id: str, scope: str) -> str:
        sid = str(session_id or "default")
        return f"{scope}\x1f{sid}" if scope else sid

    def offload(self, session_id: str, text: str, *, scope: str = "") -> str:
        """Store (overwrite) the offloaded context for a session. Returns the handle."""
        key = self._key(session_id, scope)
        with self._lock:
            self._text[key] = text or ""
            if key in self._order:
                self._order.remove(key)
            self._order.append(key)
            while len(self._order) > self._max:
                old = self._order.pop(0)
                self._text.pop(old, None)
        return key

    def get(self, session_id: str, *, scope: str = "") -> str | None:
        key = self._key(session_id, scope)
        with self._lock:
            value = self._text.get(key)
            if value is not None:  # refresh LRU recency so an active session isn't evicted
                self._order.remove(key)
                self._order.append(key)
            return value

    def clear(self, session_id: str, *, scope: str = "") -> None:
        key = self._key(session_id, scope)
        with self._lock:
            self._text.pop(key, None)
            if key in self._order:
                self._order.remove(key)


_STORE = ContextStore()


def get_context_store() -> ContextStore:
    return _STORE
