"""The OpenTelemetry bridge turns AgentOS trace events into standard, nested OTel spans.

Driven through the real TraceEmitter + TelemetryProviderFanout, with the SDK's in-memory
exporters, so these prove what a vendor would actually receive:
  * the AgentOS trace id IS the OTel trace id (same id in our UI and the vendor's)
  * one root span per run, steps nested by time (tools inside the model call)
  * OpenTelemetry GenAI + OpenInference attribute names (tokens, model, tool)
  * no prompt/response text unless content capture is switched on; secrets redacted
  * sub-agent runs nest under their parent run
  * a hung exporter cannot slow add_span
"""

from __future__ import annotations

import asyncio
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

pytest.importorskip("opentelemetry.sdk")

from opentelemetry.sdk.metrics import MeterProvider  # noqa: E402
from opentelemetry.sdk.metrics.export import InMemoryMetricReader  # noqa: E402
from opentelemetry.sdk.trace import TracerProvider  # noqa: E402
from opentelemetry.sdk.trace.export import BatchSpanProcessor, SimpleSpanProcessor, SpanExporter  # noqa: E402
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter  # noqa: E402

from telemetry.otel_setup import make_id_generator  # noqa: E402
from telemetry.otel_trace_bridge import OtelTraceProvider  # noqa: E402
from telemetry_providers import TelemetryProviderFanout  # noqa: E402
from trace_emitter import TraceEmitter  # noqa: E402


@pytest.fixture(autouse=True)
def _local_trace_store(monkeypatch):
    """These tests use a temporary SQLite trace store. If another test loaded config.env
    first, TRACE_BACKEND=postgres would send their fake runs into the live trace store."""
    monkeypatch.setenv("TRACE_BACKEND", "sqlite")


def _bridge(capture=False, processor_cls=SimpleSpanProcessor, exporter=None):
    exporter = exporter or InMemorySpanExporter()
    tp = TracerProvider(id_generator=make_id_generator())
    tp.add_span_processor(processor_cls(exporter))
    reader = InMemoryMetricReader()
    mp = MeterProvider(metric_readers=[reader])
    bridge = OtelTraceProvider(capture_content=capture, tracer_provider=tp, meter_provider=mp)
    return bridge, exporter, reader, tp


def _run_one(tmp_path, bridge, *, nested_child=False):
    """A realistic run: route -> model call containing a tool -> hook -> end."""
    async def run():
        fanout = TelemetryProviderFanout([bridge])
        em = TraceEmitter(str(tmp_path / "traces.db"), telemetry_providers=fanout)
        await em.start()
        t0 = TraceEmitter.now_ms()
        tid = em.begin_trace(session_id="s1", tenant="company", user_id="u@x", skill="invoice",
                             query="pay vendor password=hunter2 now",
                             metadata={"entrypoint": "chat_ws"})
        em.add_span(trace_id=tid, span_type="route", name="skill_router", start_ms=t0, duration_ms=5,
                    metadata={"model": "gpt-5.2-chat", "prompt_tokens": 100, "completion_tokens": 7,
                              "method": "llm", "confidence": 0.9})
        em.add_span(trace_id=tid, span_type="llm", name="agent_invoke", start_ms=t0 + 10, duration_ms=200,
                    input_preview="api_key=abc123 list invoices", output_preview="done",
                    metadata={"model": "gpt-5.2-chat", "prompt_tokens": 900, "completion_tokens": 50,
                              "reasoning_preview": "secret chain of thought"})
        em.add_span(trace_id=tid, span_type="tool", name="run_sql_query", start_ms=t0 + 50, duration_ms=20,
                    metadata={"tool_call_id": "call_1", "tool_type": "sql"})
        em.add_span(trace_id=tid, span_type="hook", name="PreToolUse:policy", start_ms=t0 + 49, duration_ms=1,
                    metadata={"hook_event": "PreToolUse", "hook_id": "policy", "outcome": "allow"})
        child = None
        if nested_child:
            child = em.begin_trace(session_id="s1", tenant="company", user_id="u@x", skill="sub_step")
            em.add_span(trace_id=child, span_type="tool", name="lookup", start_ms=t0 + 60, duration_ms=5)
            em.end_trace(trace_id=child, status="success", skill="sub_step", total_ms=10)
        em.end_trace(trace_id=tid, status="success", skill="invoice", span_count=4, total_ms=250,
                     prompt_tokens=1000, completion_tokens=57, cost_usd=0.0123,
                     metadata={"execution_mode": "react"})
        await em.stop()
        return tid, child
    return asyncio.run(run())


def test_same_trace_id_root_and_nesting(tmp_path):
    bridge, exporter, _reader, _tp = _bridge()
    tid, _ = _run_one(tmp_path, bridge)
    spans = {s.name: s for s in exporter.get_finished_spans()}
    root = spans["invoke_agent invoice"]
    assert format(root.context.trace_id, "032x") == tid, "OTel trace id must equal the AgentOS trace id"
    assert root.parent is None
    # two model spans share the name; find the one with 900 input tokens (the react loop)
    model_spans = [s for s in exporter.get_finished_spans() if s.name == "chat gpt-5.2-chat"]
    react = next(s for s in model_spans if s.attributes["gen_ai.usage.input_tokens"] == 900)
    router = next(s for s in model_spans if s.attributes["gen_ai.usage.input_tokens"] == 100)
    tool = spans["execute_tool run_sql_query"]
    assert router.parent.span_id == root.context.span_id
    assert react.parent.span_id == root.context.span_id
    assert tool.parent.span_id == react.context.span_id, "the tool call must nest inside the model call"
    assert all(s.context.trace_id == root.context.trace_id for s in exporter.get_finished_spans())
    # hooks are events on the root, not spans
    assert "PreToolUse:policy" not in spans
    assert any(e.name == "PreToolUse:policy" for e in root.events)


def test_standard_genai_and_openinference_attributes(tmp_path):
    bridge, exporter, _reader, _tp = _bridge()
    _run_one(tmp_path, bridge)
    by_name = {}
    for s in exporter.get_finished_spans():
        by_name.setdefault(s.name, s)
    root = by_name["invoke_agent invoice"]
    assert root.attributes["gen_ai.operation.name"] == "invoke_agent"
    assert root.attributes["gen_ai.agent.name"] == "invoice"
    assert root.attributes["agentos.entrypoint"] == "chat_ws"
    assert root.attributes["agentos.execution_mode"] == "react"
    assert root.attributes["gen_ai.usage.input_tokens"] == 1000
    assert root.attributes["agentos.cost_usd"] == pytest.approx(0.0123)
    assert root.attributes["openinference.span.kind"] == "AGENT"
    model = by_name["chat gpt-5.2-chat"]
    assert model.attributes["gen_ai.operation.name"] == "chat"
    assert model.attributes["gen_ai.request.model"] == "gpt-5.2-chat"
    assert model.attributes["openinference.span.kind"] == "LLM"
    tool = by_name["execute_tool run_sql_query"]
    assert tool.attributes["gen_ai.tool.name"] == "run_sql_query"
    assert tool.attributes["gen_ai.tool.call.id"] == "call_1"
    assert tool.attributes["openinference.span.kind"] == "TOOL"


def test_no_content_by_default_and_secrets_redacted_when_on(tmp_path):
    bridge, exporter, _r, _tp = _bridge(capture=False)
    (tmp_path / "off").mkdir()
    _run_one(tmp_path / "off", bridge)
    blob = repr([dict(s.attributes) for s in exporter.get_finished_spans()])
    assert "list invoices" not in blob and "pay vendor" not in blob, "content leaked with capture off"
    assert "chain of thought" not in blob

    bridge2, exporter2, _r2, _tp2 = _bridge(capture=True)
    (tmp_path / "on").mkdir()
    _run_one(tmp_path / "on", bridge2)
    blob2 = repr([dict(s.attributes) for s in exporter2.get_finished_spans()])
    assert "list invoices" in blob2, "content capture opt-in did not attach previews"
    assert "hunter2" not in blob2 and "abc123" not in blob2, "a secret survived redaction"
    assert "chain of thought" not in blob2, "model reasoning must never be exported"


def test_sub_agent_run_nests_under_parent(tmp_path):
    bridge, exporter, _r, _tp = _bridge()
    tid, child = _run_one(tmp_path, bridge, nested_child=True)
    spans = exporter.get_finished_spans()
    root = next(s for s in spans if s.name == "invoke_agent invoice")
    sub = next(s for s in spans if s.name == "invoke_agent sub_step")
    assert sub.context.trace_id == root.context.trace_id, "sub-agent run must share the parent's OTel trace"
    assert sub.parent.span_id == root.context.span_id
    assert sub.attributes["agentos.parent_trace_id"] == tid
    assert sub.attributes["agentos.trace_id"] == child


def test_metrics_use_standard_names(tmp_path):
    bridge, _e, reader, _tp = _bridge()
    _run_one(tmp_path, bridge)
    names = {m.name for rm in reader.get_metrics_data().resource_metrics
             for sm in rm.scope_metrics for m in sm.metrics}
    assert {"gen_ai.client.token.usage", "gen_ai.client.operation.duration",
            "agentos.agent.runs", "agentos.agent.run.duration", "agentos.llm.cost"} <= names


class _HungExporter(SpanExporter):
    def export(self, spans):
        time.sleep(5)
        from opentelemetry.sdk.trace.export import SpanExportResult
        return SpanExportResult.SUCCESS

    def shutdown(self):
        pass


def test_a_hung_collector_never_slows_the_caller(tmp_path):
    bridge, _e, _r, tp = _bridge(processor_cls=BatchSpanProcessor, exporter=_HungExporter())
    fanout = TelemetryProviderFanout([bridge])

    async def run():
        em = TraceEmitter(str(tmp_path / "t.db"), telemetry_providers=fanout)
        await em.start()
        worst = 0.0
        for _ in range(20):
            t = time.perf_counter()
            tid = em.begin_trace(skill="s")
            em.add_span(trace_id=tid, span_type="tool", name="x", start_ms=TraceEmitter.now_ms(), duration_ms=1)
            em.end_trace(trace_id=tid, total_ms=2)
            worst = max(worst, time.perf_counter() - t)
        await em.stop()
        return worst

    worst = asyncio.run(run())
    assert worst < 0.05, f"a hung collector slowed a trace by {worst*1000:.0f} ms"
    # tp is deliberately not shut down: that would block on the hung exporter.


def test_run_that_never_ends_is_exported_as_incomplete(tmp_path, monkeypatch):
    import telemetry.otel_trace_bridge as b
    monkeypatch.setattr(b, "_OPEN_TTL_SECONDS", 0)
    bridge, exporter, _r, _tp = _bridge()
    bridge.emit("trace_begin", {"trace_id": "a" * 32, "skill": "crashed"}, source="trace")
    bridge.emit("trace_begin", {"trace_id": "b" * 32, "skill": "next"}, source="trace")  # triggers eviction
    crashed = [s for s in exporter.get_finished_spans() if s.name == "invoke_agent crashed"]
    assert crashed and crashed[0].attributes["agentos.incomplete"] is True


def test_root_ignores_the_active_http_span_but_links_to_it(tmp_path):
    """In the server, agent runs execute inside an HTTP request span. The run must keep
    its own trace id (not join the request's trace) and carry a Link to the request."""
    from opentelemetry.trace import SpanKind

    bridge, exporter, _r, tp = _bridge()
    tracer = tp.get_tracer("test.http")
    with tracer.start_as_current_span("POST /api/chat", kind=SpanKind.SERVER) as http_span:
        tid, _ = _run_one(tmp_path, bridge)
    root = next(s for s in exporter.get_finished_spans() if s.name == "invoke_agent invoice")
    assert format(root.context.trace_id, "032x") == tid, "agent run was pulled into the HTTP trace"
    assert root.parent is None
    assert [l.context.span_id for l in root.links] == [http_span.get_span_context().span_id]
