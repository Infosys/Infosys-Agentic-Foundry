"""Passive observation capability for the current tool execution boundary.

This module does not execute tools and does not make policy decisions. It records
bounded, redacted snapshots of the existing ReAct tool path so later adapter
migration has a stable contract to compare against.
"""

from __future__ import annotations

import copy
import json
import threading
from collections import deque
from datetime import datetime
from typing import Any, Mapping

try:
    from .hook_context import redact_hook_value
except Exception:  # pragma: no cover - direct test loading fallback
    import importlib.util as _importlib_util
    import sys as _sys
    from pathlib import Path as _Path

    _hook_context_path = _Path(__file__).with_name("hook_context.py")
    _hook_context_spec = _importlib_util.spec_from_file_location(
        "iaf_agent_skills.hook_context", _hook_context_path
    )
    _hook_context_module = _importlib_util.module_from_spec(_hook_context_spec)
    _sys.modules["iaf_agent_skills.hook_context"] = _hook_context_module
    _hook_context_spec.loader.exec_module(_hook_context_module)
    redact_hook_value = _hook_context_module.redact_hook_value


DEFAULT_MAX_EVENTS = 500
DEFAULT_MAX_PREVIEW_CHARS = 4096


class ToolExecutionCapability:
    """Thread-safe ring buffer for passive tool boundary observations."""

    def __init__(self, max_events: int = DEFAULT_MAX_EVENTS, max_preview_chars: int = DEFAULT_MAX_PREVIEW_CHARS):
        self.max_events = max(1, int(max_events or DEFAULT_MAX_EVENTS))
        self.max_preview_chars = max(1, int(max_preview_chars or DEFAULT_MAX_PREVIEW_CHARS))
        self._events = deque(maxlen=self.max_events)
        self._lock = threading.Lock()
        self._sequence = 0
        self._dropped_count = 0

    @property
    def dropped_count(self) -> int:
        return self._dropped_count

    def observe_pre_tool(self, tool_name: str, tool_input: Any, session_ctx: Mapping[str, Any] | None = None) -> dict[str, Any]:
        return self._record(
            event="pre_tool",
            tool_name=tool_name,
            status="pending",
            session_ctx=session_ctx,
            tool_input=tool_input,
        )

    def observe_tool_end(
        self,
        *,
        tool_name: str,
        tool_input: Any,
        tool_output: Any,
        session_ctx: Mapping[str, Any] | None = None,
        duration_ms: float = 0,
    ) -> dict[str, Any]:
        return self._record(
            event="tool_end",
            tool_name=tool_name,
            status="ok",
            session_ctx=session_ctx,
            tool_input=tool_input,
            tool_output=tool_output,
            duration_ms=duration_ms,
        )

    def observe_tool_error(
        self,
        *,
        tool_name: str,
        tool_input: Any,
        error: Any,
        session_ctx: Mapping[str, Any] | None = None,
        duration_ms: float = 0,
    ) -> dict[str, Any]:
        return self._record(
            event="tool_error",
            tool_name=tool_name,
            status="error",
            session_ctx=session_ctx,
            tool_input=tool_input,
            tool_output=error,
            duration_ms=duration_ms,
        )

    def snapshot(self, limit: int | None = None) -> list[dict[str, Any]]:
        with self._lock:
            events = list(self._events)
        if limit is not None:
            events = events[-max(0, int(limit)):]
        return copy.deepcopy(events)

    def reset(self) -> None:
        with self._lock:
            self._events.clear()
            self._sequence = 0
            self._dropped_count = 0

    def _record(
        self,
        *,
        event: str,
        tool_name: str,
        status: str,
        session_ctx: Mapping[str, Any] | None,
        tool_input: Any = None,
        tool_output: Any = None,
        duration_ms: float = 0,
    ) -> dict[str, Any]:
        context = dict(session_ctx or {})
        with self._lock:
            self._sequence += 1
            sequence = self._sequence
            if len(self._events) == self.max_events:
                self._dropped_count += 1

            record = {
                "sequence": sequence,
                "timestamp": datetime.now().isoformat(),
                "event": event,
                "tool_name": str(tool_name or ""),
                "status": status,
                "trace_id": str(context.get("trace_id") or ""),
                "session_id": str(context.get("session_id") or ""),
                "tenant_id": str(context.get("tenant_id") or ""),
                "agent_id": str(context.get("agent_id") or ""),
                "user_id": str(context.get("user_id") or ""),
                "current_skill": str(context.get("current_skill") or context.get("skill_name") or ""),
                "entrypoint": str(context.get("entrypoint") or context.get("source") or ""),
                "duration_ms": float(duration_ms or 0),
                "input_preview": self._preview(tool_input),
                "output_preview": self._preview(tool_output),
            }
            self._events.append(record)
            return copy.deepcopy(record)

    def _preview(self, value: Any) -> str:
        if value is None:
            return ""
        redacted = redact_hook_value(value)
        if isinstance(redacted, str):
            text = redacted
        else:
            try:
                text = json.dumps(redacted, sort_keys=True, default=str)
            except Exception:
                text = str(redacted)
        return text[:self.max_preview_chars]