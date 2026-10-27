"""Default TraceProvider backed by the existing Studio TraceEmitter singleton."""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


class DefaultTraceProvider:
    """Return the same TraceEmitter object Studio already injects today."""

    name = "default_trace"

    def __init__(self, emitter: Any = None):
        self._emitter = emitter

    def get_emitter(self) -> Any:
        if self._emitter is not None:
            return self._emitter
        # Resolve from the host-injected trace emitter (registered at startup).
        # No host import here — keeps the engine embeddable.
        try:
            from iaf_agent_skills.runtime_bridge import get_trace_emitter

            self._emitter = get_trace_emitter()
        except Exception as exc:
            logger.debug("Trace provider unavailable (non-fatal): %s", exc)
            self._emitter = None
        return self._emitter

    def health(self) -> dict[str, Any]:
        return {"provider": self.name, "enabled": self.get_emitter() is not None, "status": "ok"}

    def snapshot(self) -> dict[str, Any]:
        return self.health()
