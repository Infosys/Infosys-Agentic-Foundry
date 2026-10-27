"""
Trace Tool Callback — LangChain callback handler for real tool timing.

Captures on_tool_start / on_tool_end / on_tool_error events from LangGraph's
create_react_agent invoke cycle.  After invoke completes, call emit_spans()
to flush captured tool timings as real trace spans.

Usage:
    from .trace_callback import TraceToolCallback

    cb = TraceToolCallback(trace_id=tid, trace_emitter=te)
    result = agent.invoke({"messages": msgs}, config={"callbacks": [cb], ...})
    cb.emit_spans()          # flush captured tool spans
    span_count = cb.count    # number of tool spans emitted
"""

from __future__ import annotations

import time
from typing import Any, Dict, List, Optional, TYPE_CHECKING
from uuid import UUID

from langchain_core.callbacks import BaseCallbackHandler

if TYPE_CHECKING:
    from trace_emitter import TraceEmitter  # type hint only, no runtime import
    from .progress_phases import ProgressTracker  # type hint only

_TOOL_TYPE_MAP = {
    "run_sql_query": "sql",
    "shell": "shell",
    "query_memory": "memory",
    "write_file": "write",
}


def _classify_tool(name: str) -> str:
    """Classify tool name into a semantic type for dashboard display."""
    return _TOOL_TYPE_MAP.get(name, "other")



def _has_error(content: str) -> bool:
    """Check if tool output is an error response.
    Only flags outputs that START with 'Error' — matching the kernel's actual
    error format. Avoids false positives from file content containing these words.
    """
    if not content:
        return False
    return content.strip().startswith("Error")


class TraceToolCallback(BaseCallbackHandler):
    """
    Lightweight LangChain callback that records per-tool start/end timing.

    Thread-safe via run_id keying (LangChain guarantees unique run_id per call).
    Zero I/O during invoke — just dict writes.  Call emit_spans() after invoke.
    """

    def __init__(self, trace_id: str, trace_emitter: Optional[Any] = None,
                 status_callback: Optional[Any] = None,
                 progress_tracker: Optional[Any] = None,
                 hook_runner: Optional[Any] = None,
                 session_ctx: Optional[dict] = None,
                 tool_execution_observer: Optional[Any] = None):
        """
        Args:
            trace_id: Active trace ID for span association.
            trace_emitter: TraceEmitter instance (optional — if None, emit_spans is no-op).
            status_callback: Optional callable(str) for live progress to UI (legacy v1).
            progress_tracker: Optional ProgressTracker for structured visual stepper (v2).
                              When provided, takes precedence over status_callback.
            hook_runner: HookRunner instance for PostToolUse hooks (optional).
            session_ctx: Session context dict built by agent._build_session_ctx() (optional).
            tool_execution_observer: Passive observer for tool boundary events (optional).
        """
        super().__init__()
        self.trace_id = trace_id
        self._emitter = trace_emitter
        self._status_callback = status_callback
        self._progress_tracker = progress_tracker
        self._hook_runner = hook_runner
        self._session_ctx = session_ctx
        self._tool_execution_observer = tool_execution_observer
        self._tools: Dict[str, Dict[str, Any]] = {}  # run_id → tool data
        self._order: List[str] = []  # insertion order of run_ids
        self._span_count = 0


    def on_tool_start(
        self,
        serialized: Dict[str, Any],
        input_str: str,
        *,
        run_id: UUID,
        parent_run_id: Optional[UUID] = None,
        tags: Optional[list] = None,
        metadata: Optional[dict] = None,
        inputs: Optional[dict] = None,
        **kwargs: Any,
    ) -> None:
        """Record tool start time and input."""
        rid = str(run_id)
        self._tools[rid] = {
            "name": serialized.get("name", "unknown"),
            "start_ms": time.time() * 1000,
            "input_str": str(input_str)[:4096],
            "inputs": inputs,  # dict of actual args (may be None)
        }
        self._order.append(rid)
        # Live progress for visual stepper (v2) or legacy status (v1)
        name = serialized.get('name', 'unknown')
        # Build a descriptive display name from tool args (e.g., actual shell command)
        display_name = name
        try:
            if inputs and isinstance(inputs, dict):
                cmd = inputs.get('command', '')
                if cmd:
                    # Shell: show the actual command, first line, truncated
                    display_name = str(cmd).strip().split('\n')[0][:80]
                elif name == 'write_file':
                    path = inputs.get('path', '') or inputs.get('filename', '')
                    if path:
                        display_name = f"write_file → {str(path)[:60]}"
                elif name == 'query_memory':
                    query = inputs.get('query', '')
                    if query:
                        display_name = f"query_memory: {str(query)[:50]}"
                elif name != 'shell':
                    # For other tools, try to show the first meaningful arg
                    first_arg = next(iter(inputs.values()), None)
                    if first_arg and isinstance(first_arg, str) and len(first_arg) < 60:
                        display_name = f"{name}: {first_arg[:50]}"
            elif input_str and input_str != name:
                display_name = f"{name}: {str(input_str).strip()[:60]}"
        except Exception:
            pass  # Fallback to raw tool name
        self._tools[rid]["display_name"] = display_name
        if self._progress_tracker:
            try:
                from .progress_phases import ProgressPhase
                self._progress_tracker.start_phase(
                    ProgressPhase.EXECUTING_TOOLS, sub_step=display_name,
                    detail=f"Running {name}")
            except Exception:
                pass  # Never break agent for status
        elif self._status_callback:
            try:
                self._status_callback(f"🔧 Executing tool: {display_name}...")
            except Exception:
                pass  # Never break agent for status

    def on_tool_end(
        self,
        output: Any,
        *,
        run_id: UUID,
        parent_run_id: Optional[UUID] = None,
        **kwargs: Any,
    ) -> None:
        """Record tool end time and output."""
        rid = str(run_id)
        if rid in self._tools:
            end_ms = time.time() * 1000
            self._tools[rid]["end_ms"] = end_ms
            self._tools[rid]["duration_ms"] = end_ms - self._tools[rid]["start_ms"]
            self._tools[rid]["output"] = str(output)[:4096]
            self._tools[rid]["status"] = "error" if _has_error(str(output)) else "ok"
            # Live progress for visual stepper (v2) or legacy status (v1)
            name = self._tools[rid].get("name", "unknown")
            display_name = self._tools[rid].get("display_name", name)
            duration = round(self._tools[rid]["duration_ms"])
            if self._progress_tracker:
                try:
                    result_preview = str(output)[:80].replace('\n', ' ')
                    self._progress_tracker.sub_step(
                        sub_step=display_name, status="completed",
                        detail=f"Done in {duration}ms — {result_preview}")
                except Exception:
                    pass
            elif self._status_callback:
                try:
                    self._status_callback(f"✅ Tool {display_name} completed ({duration}ms)")
                except Exception:
                    pass
            # HOOKS: PostToolUse — single fire point for successful tool completions
            if self._tool_execution_observer:
                try:
                    self._tool_execution_observer.observe_tool_end(
                        tool_name=self._tools[rid].get("name", ""),
                        tool_input=self._observer_tool_input(rid),
                        tool_output=str(output),
                        session_ctx=self._session_ctx or {},
                        duration_ms=self._tools[rid].get("duration_ms", 0),
                    )
                except Exception:
                    pass
            if self._hook_runner and self._session_ctx:
                self._hook_runner.run_post_tool(
                    tool_name=self._tools[rid].get("name", ""),
                    tool_input=self._tools[rid].get("input_str", ""),
                    tool_output=str(output)[:2000],
                    session_ctx=self._session_ctx,
                )

    def on_tool_error(
        self,
        error: BaseException,
        *,
        run_id: UUID,
        parent_run_id: Optional[UUID] = None,
        **kwargs: Any,
    ) -> None:
        """Record tool error."""
        rid = str(run_id)
        if rid in self._tools:
            end_ms = time.time() * 1000
            self._tools[rid]["end_ms"] = end_ms
            self._tools[rid]["duration_ms"] = end_ms - self._tools[rid]["start_ms"]
            self._tools[rid]["output"] = f"{type(error).__name__}: {str(error)[:500]}"
            self._tools[rid]["status"] = "error"
            # Live progress for visual stepper (v2) or legacy status (v1)
            name = self._tools[rid].get("name", "unknown")
            display_name = self._tools[rid].get("display_name", name)
            if self._progress_tracker:
                try:
                    self._progress_tracker.sub_step(
                        sub_step=display_name, status="error",
                        detail=f"{type(error).__name__}: {str(error)[:100]}")
                except Exception:
                    pass
            elif self._status_callback:
                try:
                    self._status_callback(f"❌ Tool {display_name} failed: {str(error)[:100]}")
                except Exception:
                    pass
            # HOOKS: PostToolUse — single fire point for tool errors too
            if self._tool_execution_observer:
                try:
                    self._tool_execution_observer.observe_tool_error(
                        tool_name=self._tools[rid].get("name", ""),
                        tool_input=self._observer_tool_input(rid),
                        error=f"{type(error).__name__}: {str(error)[:500]}",
                        session_ctx=self._session_ctx or {},
                        duration_ms=self._tools[rid].get("duration_ms", 0),
                    )
                except Exception:
                    pass
            if self._hook_runner and self._session_ctx:
                self._hook_runner.run_post_tool(
                    tool_name=self._tools[rid].get("name", ""),
                    tool_input=self._tools[rid].get("input_str", ""),
                    tool_output=f"ERROR: {type(error).__name__}: {str(error)[:500]}",
                    session_ctx=self._session_ctx,
                )


    def _observer_tool_input(self, run_id: str) -> Any:
        tool = self._tools.get(run_id) or {}
        structured = tool.get("inputs")
        input_str = tool.get("input_str", "")
        if isinstance(structured, dict) and set(structured) == {"command"} and str(structured.get("command", "")) == input_str:
            return input_str
        if structured is not None:
            return structured
        return input_str

    def emit_spans(self) -> int:
        """
        Flush all captured tool events as trace spans.

        Returns number of spans emitted.  Safe to call even if emitter is None.
        """
        if not self._emitter or not self._tools:
            return 0

        emitted = 0
        for rid in self._order:
            tool = self._tools.get(rid)
            if not tool:
                continue

            name = tool["name"]
            tool_type = _classify_tool(name)

            # Build input preview: prefer command for shell, else stringified args
            input_preview = tool.get("input_str", "")
            if tool.get("inputs") and isinstance(tool["inputs"], dict):
                cmd = tool["inputs"].get("command", "")
                if cmd:
                    import re as _re
                    masked = _re.sub(
                        r'(Bearer\s+)[A-Za-z0-9\-_\.]+',
                        r'\1[REDACTED]',
                        str(cmd),
                        flags=_re.IGNORECASE,
                    )
                    input_preview = masked[:4096]

            try:
                self._emitter.add_span(
                    trace_id=self.trace_id,
                    span_type="tool",
                    name=name,
                    start_ms=tool.get("start_ms", 0),
                    duration_ms=tool.get("duration_ms", 0),
                    status=tool.get("status", "ok"),
                    input_preview=input_preview,
                    output_preview=tool.get("output", "")[:4096],
                    metadata={
                        "tool_call_id": rid,
                        "has_error": tool.get("status") == "error",
                        "tool_type": tool_type,
                    },
                )
                emitted += 1
            except Exception:
                pass  # Non-fatal — trace should never break production

        self._span_count = emitted
        return emitted

    @property
    def count(self) -> int:
        """Number of tool spans emitted (available after emit_spans)."""
        return self._span_count

    @property
    def tool_names(self) -> List[str]:
        """Ordered list of tool names captured."""
        return [self._tools[rid]["name"] for rid in self._order if rid in self._tools]

    def reset(self) -> None:
        """Clear all captured state for reuse."""
        self._tools.clear()
        self._order.clear()
        self._span_count = 0
