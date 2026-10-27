"""Translate AgentOS trace events into standard OpenTelemetry spans and metrics.

trace_emitter.py reports a run as fragments — trace_begin, one event per step, then
trace_end. OTLP consumers expect complete, nested spans, so this bridge buffers each
run and, when it ends, emits:

  * one root span per agent run   (gen_ai.operation.name = invoke_agent)
  * a child span per step         (chat / execute_tool / chain ...), nested by time
    containment, so tool calls appear inside the model call that made them
  * hook executions as span events on the root (they are very chatty as spans)

Attribute names follow the OpenTelemetry GenAI semantic conventions, plus the
OpenInference names that Arize Phoenix and Langfuse read. AgentOS-specific fields are
prefixed `agentos.`. Prompt/response text is attached ONLY when
OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT=true (and is already redacted and
length-capped by TelemetryProviderFanout before it reaches this class).

Registered as a provider on the existing TelemetryProviderFanout; it is called
synchronously by the emitter, so it only buffers and hands finished spans to the SDK's
BatchSpanProcessor — no network I/O happens on the caller's thread.
"""

from __future__ import annotations

import json
import os
import random
import threading
import time
from collections import OrderedDict
from typing import Any, Dict, List, Optional

from telemetry.otel_setup import _FORCED_SPAN_ID, _FORCED_TRACE_ID, capture_content_enabled

# Span types that can contain other steps (a react loop's model call contains its tools;
# workflow / graph runs contain their steps). Everything else is a leaf.
_CONTAINER_TYPES = {"llm", "workflow", "workflow_resume", "graph", "rlm", "orchestrator", "queue_lifecycle"}
_OPENINFERENCE_KIND = {
    "llm": "LLM", "route": "LLM", "tool": "TOOL", "knowledge": "RETRIEVER",
}
_MAX_OPEN_TRACES = 5000
_OPEN_TTL_SECONDS = 30 * 60
_RECENT_CAP = 5000
_EPS_MS = 1.0


def _hex_id(value: str, bits: int) -> int:
    """Parse an AgentOS hex id as an OTel id; fall back to a random one if unusable."""
    try:
        parsed = int(str(value), 16)
        if 0 < parsed < (1 << bits):
            return parsed
    except (TypeError, ValueError):
        pass
    return random.getrandbits(bits) or 1


def _as_dict(value: Any) -> Dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, str) and value:
        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, dict) else {}
        except (ValueError, TypeError):
            return {}
    return {}


def _num(value: Any) -> Optional[float]:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _provider_name(model: str) -> str:
    m = (model or "").lower()
    if "claude" in m:
        return "anthropic"
    if "gemini" in m:
        return "gcp.vertex_ai"
    if os.getenv("AZURE_OPENAI_ENDPOINT"):
        return "azure.ai.openai"
    return "openai"


def _set(attrs: Dict[str, Any], key: str, value: Any) -> None:
    """OTel attributes must be str/bool/int/float (or homogeneous lists) — skip the rest."""
    if value is None or value == "":
        return
    if isinstance(value, (str, bool, int, float)):
        attrs[key] = value
    elif isinstance(value, (list, tuple)) and all(isinstance(v, str) for v in value):
        attrs[key] = list(value)
    else:
        attrs[key] = json.dumps(value, default=str)[:1024]


class _OpenTrace:
    __slots__ = ("begin", "spans", "start_ns", "otel_trace_id", "root_span_id",
                 "parent_span_id", "link_context", "received")

    def __init__(self, begin: Dict[str, Any], otel_trace_id: int, parent_span_id: int, link_context):
        self.begin = begin
        self.spans: List[Dict[str, Any]] = []
        self.start_ns = time.time_ns()
        self.otel_trace_id = otel_trace_id
        self.root_span_id = random.getrandbits(64) or 1
        self.parent_span_id = parent_span_id
        self.link_context = link_context
        self.received = time.monotonic()


class OtelTraceProvider:
    """TelemetryProvider that mirrors AgentOS traces to OpenTelemetry."""

    name = "otel"
    enabled = True

    def __init__(self, *, capture_content: Optional[bool] = None, tracer_provider=None, meter_provider=None):
        from opentelemetry import metrics, trace

        self._capture = capture_content_enabled() if capture_content is None else capture_content
        tp = tracer_provider or trace.get_tracer_provider()
        mp = meter_provider or metrics.get_meter_provider()
        self._tracer = tp.get_tracer("agentos.trace_bridge")
        meter = mp.get_meter("agentos.trace_bridge")
        # Standard GenAI client metrics + AgentOS run/cost/approval metrics.
        self._m_tokens = meter.create_histogram(
            "gen_ai.client.token.usage", unit="{token}", description="Tokens used per model call")
        self._m_op_duration = meter.create_histogram(
            "gen_ai.client.operation.duration", unit="s", description="Model call duration")
        self._m_runs = meter.create_counter(
            "agentos.agent.runs", unit="{run}", description="Agent runs by skill, status and entrypoint")
        self._m_run_duration = meter.create_histogram(
            "agentos.agent.run.duration", unit="s", description="End-to-end agent run duration")
        self._m_cost = meter.create_counter(
            "agentos.llm.cost", unit="USD", description="Estimated model cost")
        self._m_approvals = meter.create_counter(
            "agentos.approvals", unit="{approval}", description="Human-approval steps recorded in runs")
        self._m_dropped = meter.create_counter(
            "agentos.telemetry.dropped", unit="{item}", description="Telemetry items the bridge could not export")

        self._lock = threading.Lock()
        self._open: "OrderedDict[str, _OpenTrace]" = OrderedDict()
        self._recent: "OrderedDict[str, tuple[int, int]]" = OrderedDict()  # trace_id -> (otel tid, root sid)
        self._stats = {"traces_exported": 0, "spans_exported": 0, "late_spans": 0,
                       "incomplete_traces": 0, "dropped": 0}

    def emit(self, event_type: str, payload: Dict[str, Any], *, source: str = "trace") -> None:
        if source != "trace":
            return
        if event_type == "trace_begin":
            self._on_begin(payload)
        elif event_type == "span":
            self._on_span(payload)
        elif event_type == "trace_end":
            self._on_end(payload)

    def snapshot(self) -> Dict[str, Any]:
        with self._lock:
            open_count = len(self._open)
        return {"name": self.name, "implementation": type(self).__name__, "enabled": self.enabled,
                "capture_content": self._capture, "open_traces": open_count, **self._stats}

    def _on_begin(self, payload: Dict[str, Any]) -> None:
        trace_id = str(payload.get("trace_id") or "")
        if not trace_id:
            return
        link_context = self._current_server_span_context()
        parent_tid = str(payload.get("parent_trace_id") or "")
        expired: List[_OpenTrace] = []
        with self._lock:
            otel_tid, parent_sid = _hex_id(trace_id, 128), 0
            parent = self._open.get(parent_tid) if parent_tid else None
            if parent is not None:
                otel_tid, parent_sid = parent.otel_trace_id, parent.root_span_id
            elif parent_tid in self._recent:
                otel_tid, parent_sid = self._recent[parent_tid]
            self._open[trace_id] = _OpenTrace(dict(payload), otel_tid, parent_sid, link_context)
            expired = self._evict_locked()
        for rec in expired:
            self._finish(rec, end_payload={"status": "incomplete"}, incomplete=True)

    def _on_span(self, payload: Dict[str, Any]) -> None:
        trace_id = str(payload.get("trace_id") or "")
        with self._lock:
            rec = self._open.get(trace_id)
            if rec is not None:
                rec.spans.append(dict(payload))
                return
            late = self._recent.get(trace_id)
        if late is not None:
            # A step reported after its run ended (e.g. async memory extraction): still
            # export it, parented to the run's root span.
            self._stats["late_spans"] += 1
            self._emit_child(late[0], late[1], payload)
            return
        self._stats["dropped"] += 1
        self._m_dropped.add(1, {"reason": "unknown_trace"})

    def _on_end(self, payload: Dict[str, Any]) -> None:
        trace_id = str(payload.get("trace_id") or "")
        with self._lock:
            rec = self._open.pop(trace_id, None)
        if rec is not None:
            self._finish(rec, end_payload=payload, incomplete=False)

    def _evict_locked(self) -> List[_OpenTrace]:
        """Runs that never reported an end (crash, abandoned) are exported as incomplete."""
        out: List[_OpenTrace] = []
        now = time.monotonic()
        while self._open:
            oldest_id, oldest = next(iter(self._open.items()))
            if len(self._open) <= _MAX_OPEN_TRACES and now - oldest.received < _OPEN_TTL_SECONDS:
                break
            self._open.pop(oldest_id)
            out.append(oldest)
        return out

    @staticmethod
    def _current_server_span_context():
        """The HTTP request span this run was started from (linked, not parented)."""
        try:
            from opentelemetry import trace
            from opentelemetry.trace import SpanKind
            span = trace.get_current_span()
            ctx = span.get_span_context()
            if ctx.is_valid and getattr(span, "kind", None) == SpanKind.SERVER:
                return ctx
        except Exception:
            pass
        return None

    def _start_span(self, name: str, otel_tid: int, span_id: int, parent_sid: int,
                    start_ns: int, attributes: Dict[str, Any], links=None, kind=None):
        from opentelemetry import trace
        from opentelemetry.context import Context
        from opentelemetry.trace import NonRecordingSpan, SpanContext, SpanKind, TraceFlags

        # Explicit empty context for roots: context=None would attach to the current HTTP request span.
        context = Context()
        if parent_sid:
            parent_ctx = SpanContext(trace_id=otel_tid, span_id=parent_sid, is_remote=False,
                                     trace_flags=TraceFlags(TraceFlags.SAMPLED))
            context = trace.set_span_in_context(NonRecordingSpan(parent_ctx))
        tok_t = _FORCED_TRACE_ID.set(otel_tid)
        tok_s = _FORCED_SPAN_ID.set(span_id)
        try:
            return self._tracer.start_span(
                name, context=context, kind=kind or SpanKind.INTERNAL,
                attributes=attributes, links=links or (), start_time=start_ns,
            )
        finally:
            _FORCED_SPAN_ID.reset(tok_s)
            _FORCED_TRACE_ID.reset(tok_t)

    def _finish(self, rec: _OpenTrace, *, end_payload: Dict[str, Any], incomplete: bool) -> None:
        try:
            self._export_run(rec, end_payload, incomplete)
        except Exception:
            self._stats["dropped"] += 1
            try:
                self._m_dropped.add(1, {"reason": "export_error"})
            except Exception:
                pass

    def _export_run(self, rec: _OpenTrace, end: Dict[str, Any], incomplete: bool) -> None:
        from opentelemetry.trace import Link, SpanKind, Status, StatusCode

        begin = rec.begin
        begin_meta = _as_dict(begin.get("metadata"))
        end_meta = _as_dict(end.get("metadata"))
        skill = str(end.get("skill") or begin.get("skill") or "")
        status = str(end.get("status") or "success")
        entrypoint = str(begin_meta.get("entrypoint") or "")
        total_ms = _num(end.get("total_ms")) or 0.0
        end_ns = rec.start_ns + int(total_ms * 1e6) if total_ms > 0 else time.time_ns()
        spans = sorted(rec.spans, key=lambda s: (_num(s.get("start_ms")) or 0.0,
                                                  -(_num(s.get("duration_ms")) or 0.0)))
        # Root span covers its children even when total_ms is missing/short.
        for s in spans:
            s_end = int(((_num(s.get("start_ms")) or 0) + (_num(s.get("duration_ms")) or 0)) * 1e6)
            end_ns = max(end_ns, s_end)

        root_attrs: Dict[str, Any] = {}
        _set(root_attrs, "gen_ai.operation.name", "invoke_agent")
        _set(root_attrs, "gen_ai.agent.name", skill)
        _set(root_attrs, "openinference.span.kind", "AGENT")
        _set(root_attrs, "agentos.trace_id", begin.get("trace_id"))
        _set(root_attrs, "agentos.parent_trace_id", begin.get("parent_trace_id"))
        _set(root_attrs, "agentos.skill", skill)
        _set(root_attrs, "agentos.tenant", begin.get("tenant"))
        _set(root_attrs, "agentos.agent", begin.get("agent"))
        _set(root_attrs, "agentos.entrypoint", entrypoint)
        _set(root_attrs, "agentos.status", status)
        _set(root_attrs, "agentos.execution_mode", end_meta.get("execution_mode"))
        _set(root_attrs, "session.id", begin.get("session_id"))
        _set(root_attrs, "enduser.id", begin.get("user_id"))
        prompt_tokens = int(_num(end.get("prompt_tokens")) or 0)
        completion_tokens = int(_num(end.get("completion_tokens")) or 0)
        if prompt_tokens or completion_tokens:
            root_attrs["gen_ai.usage.input_tokens"] = prompt_tokens
            root_attrs["gen_ai.usage.output_tokens"] = completion_tokens
            root_attrs["llm.token_count.prompt"] = prompt_tokens
            root_attrs["llm.token_count.completion"] = completion_tokens
            root_attrs["llm.token_count.total"] = prompt_tokens + completion_tokens
        cost = _num(end.get("cost_usd"))
        if cost:
            root_attrs["agentos.cost_usd"] = cost
        if incomplete:
            root_attrs["agentos.incomplete"] = True
        if self._capture:
            _set(root_attrs, "input.value", begin.get("query_preview"))

        links = [Link(rec.link_context)] if rec.link_context is not None else None
        root = self._start_span(f"invoke_agent {skill}".strip(), rec.otel_trace_id, rec.root_span_id,
                                rec.parent_span_id, rec.start_ns, root_attrs, links=links,
                                kind=SpanKind.INTERNAL)
        if not root.is_recording():  # sampled out — drop the whole run consistently
            root.end(end_time=end_ns)
            self._remember(rec)
            return

        # Children: hooks become events; containers nest the steps that ran inside them.
        placed: List[tuple[float, float, int]] = []  # (start_ms, end_ms, span_id) of containers
        exported = 0
        approvals = 0
        for s in spans:
            span_type = str(s.get("span_type") or "custom")
            start_ms = _num(s.get("start_ms")) or 0.0
            end_ms = start_ms + (_num(s.get("duration_ms")) or 0.0)
            if span_type == "hook":
                meta = _as_dict(s.get("metadata"))
                ev: Dict[str, Any] = {}
                for key in ("hook_event", "hook_id", "hook_kind", "outcome", "reason", "mode"):
                    _set(ev, f"agentos.hook.{key}", meta.get(key))
                _set(ev, "agentos.hook.status", s.get("status"))
                root.add_event(str(s.get("name") or "hook"), attributes=ev, timestamp=int(start_ms * 1e6))
                continue
            parent_sid = rec.root_span_id
            best = None
            for c_start, c_end, c_sid in placed:
                if c_start - _EPS_MS <= start_ms and end_ms <= c_end + _EPS_MS:
                    if best is None or (c_end - c_start) < (best[1] - best[0]):
                        best = (c_start, c_end, c_sid)
            if best is not None:
                parent_sid = best[2]
            span_id = self._emit_child(rec.otel_trace_id, parent_sid, s)
            exported += 1
            if span_type == "hitl":
                approvals += 1
            if span_type in _CONTAINER_TYPES and span_id:
                placed.append((start_ms, end_ms, span_id))

        if status in ("error", "failed"):
            root.set_status(Status(StatusCode.ERROR, f"agent run {status}"))
        root.end(end_time=end_ns)
        self._remember(rec)

        self._stats["traces_exported"] += 1
        self._stats["spans_exported"] += exported + 1
        if incomplete:
            self._stats["incomplete_traces"] += 1
        run_attrs = {"agentos.skill": skill or "unknown", "agentos.status": status,
                     "agentos.entrypoint": entrypoint or "unknown"}
        self._m_runs.add(1, run_attrs)
        self._m_run_duration.record(max(0.0, (end_ns - rec.start_ns) / 1e9), run_attrs)
        if cost:
            self._m_cost.add(cost, {"agentos.skill": skill or "unknown"})
        if approvals:
            self._m_approvals.add(approvals, {"agentos.skill": skill or "unknown"})

    def _emit_child(self, otel_tid: int, parent_sid: int, s: Dict[str, Any]) -> int:
        from opentelemetry.trace import SpanKind, Status, StatusCode

        span_type = str(s.get("span_type") or "custom")
        name = str(s.get("name") or span_type)
        meta = _as_dict(s.get("metadata"))
        start_ms = _num(s.get("start_ms")) or (time.time() * 1000)
        duration_ms = _num(s.get("duration_ms")) or 0.0
        attrs: Dict[str, Any] = {"agentos.span_type": span_type}
        kind = SpanKind.INTERNAL
        model = str(meta.get("model") or "")
        in_tok = _num(meta.get("prompt_tokens"))
        out_tok = _num(meta.get("completion_tokens"))

        if span_type in ("llm", "route") and (model or in_tok is not None):
            kind = SpanKind.CLIENT
            span_name = f"chat {model}".strip()
            _set(attrs, "gen_ai.operation.name", "chat")
            _set(attrs, "gen_ai.provider.name", _provider_name(model))
            _set(attrs, "gen_ai.request.model", model)
            _set(attrs, "llm.model_name", model)
            if in_tok is not None:
                attrs["gen_ai.usage.input_tokens"] = int(in_tok)
                attrs["llm.token_count.prompt"] = int(in_tok)
            if out_tok is not None:
                attrs["gen_ai.usage.output_tokens"] = int(out_tok)
                attrs["llm.token_count.completion"] = int(out_tok)
            if span_type == "route":
                _set(attrs, "agentos.route.method", meta.get("method"))
                _set(attrs, "agentos.route.confidence", _num(meta.get("confidence")))
            self._record_model_metrics(model, in_tok, out_tok, duration_ms)
        elif span_type == "tool":
            span_name = f"execute_tool {name}"
            _set(attrs, "gen_ai.operation.name", "execute_tool")
            _set(attrs, "gen_ai.tool.name", name)
            _set(attrs, "tool.name", name)
            _set(attrs, "gen_ai.tool.call.id", meta.get("tool_call_id"))
            _set(attrs, "gen_ai.tool.type", meta.get("tool_type"))
        else:
            span_name = name if span_type in ("hitl", "queue_lifecycle") else f"{span_type} {name}".strip()
            for key in ("execution_mode", "skill", "processing_time_ms", "tool_count", "method"):
                _set(attrs, f"agentos.{key}", meta.get(key))
        _set(attrs, "openinference.span.kind", _OPENINFERENCE_KIND.get(span_type, "CHAIN"))
        if self._capture:
            _set(attrs, "input.value", s.get("input_preview"))
            _set(attrs, "output.value", s.get("output_preview"))

        span_id = random.getrandbits(64) or 1
        span = self._start_span(span_name, otel_tid, span_id, parent_sid, int(start_ms * 1e6), attrs, kind=kind)
        status = str(s.get("status") or "ok")
        if status == "error" or meta.get("has_error"):
            span.set_status(Status(StatusCode.ERROR, f"{span_type} failed"))
            span.set_attribute("error.type", span_type)
        span.end(end_time=int((start_ms + duration_ms) * 1e6))
        return span_id

    def _record_model_metrics(self, model: str, in_tok, out_tok, duration_ms: float) -> None:
        base = {"gen_ai.operation.name": "chat", "gen_ai.provider.name": _provider_name(model),
                "gen_ai.request.model": model or "unknown"}
        if in_tok is not None:
            self._m_tokens.record(int(in_tok), {**base, "gen_ai.token.type": "input"})
        if out_tok is not None:
            self._m_tokens.record(int(out_tok), {**base, "gen_ai.token.type": "output"})
        if duration_ms:
            self._m_op_duration.record(duration_ms / 1000.0, base)

    def _remember(self, rec: _OpenTrace) -> None:
        trace_id = str(rec.begin.get("trace_id") or "")
        with self._lock:
            self._recent[trace_id] = (rec.otel_trace_id, rec.root_span_id)
            while len(self._recent) > _RECENT_CAP:
                self._recent.popitem(last=False)
