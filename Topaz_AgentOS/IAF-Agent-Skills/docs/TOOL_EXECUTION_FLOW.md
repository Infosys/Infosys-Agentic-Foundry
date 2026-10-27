# Tool Execution Flow

This note captures the current ReAct tool chokepoint before any capability
adapter migration. It is intentionally descriptive: behavior still lives in the
existing `SkillAgent`, `TraceToolCallback`, tool factory, and SafeKernel paths.

## Current Flow

```text
SkillAgent.run(query)
  |
  |-- begin TraceEmitter trace, store _active_trace_id
  |-- build prompt, tools, progress tracker, evidence collector
  |-- create passive ToolExecutionCapability observer
  |
  |-- TraceToolCallback(trace_id, trace_emitter, hook_runner, session_ctx)
  |
  |-- _run_with_sufficiency(...)
        |
        |-- _run_with_stream_intercept(...)
              |
              |-- agent.stream(...)
                    |
                    |-- agent chunk with tool_calls
                    |     |
                    |     |-- ToolExecutionCapability.observe_pre_tool(...)
                    |     |-- EvidenceCollector.record_tool_call(...)
                    |     |-- HookRunner.run_pre_tool(...) for every tool
                    |     |-- stream HITL gates: ask-first write + dangerous policy
                    |     |-- blocked => pending_tool_call / approval_pending / __PENDING__
                    |
                    |-- LangGraph executes selected LangChain tool
                    |     |
                    |     |-- tool_factory closure
                    |     |-- SafeKernel / SQLite / memory / child-agent delegation
                    |     |-- kernel entitlements and external-access gates remain hard checks
                    |
                    |-- TraceToolCallback.on_tool_end/on_tool_error(...)
                    |     |
                    |     |-- ToolExecutionCapability.observe_tool_end/error(...)
                    |     |-- HookRunner.run_post_tool(...)
                    |     |-- records timing/status in callback memory
                    |
                    |-- tools chunk with ToolMessage
                          |
                          |-- EvidenceCollector.record_tool_result(...)
  |
  |-- response parsing, pending approval sentinel handling, tool learning summary
  |-- _tool_cb.emit_spans() => TraceEmitter span_type="tool"
  |-- _finalize_evidence_bundle(...)
  |-- memory/decision context/plan cache writes
  |-- PostSampling hook after async episode + implicit-feedback writes
  |-- TraceEmitter memory/response spans and end_trace(...)
```

## Migration Boundaries

`TraceToolCallback` is the current single PostToolUse fire point. Do not add a
second PostToolUse call in `agent.py` result parsing; that would double-count
hook side effects. The focused regression is
`IAF-Agent-Skills/tests/test_trace_callback_tool_hooks.py`.

`ToolExecutionCapability` is currently passive. It records bounded, redacted
observations of pre-tool, successful completion, and tool error events. It does
not execute tools, block requests, mutate inputs, or replace the stream
intercept. The focused contract tests are
`IAF-Agent-Skills/tests/test_tool_execution_capability.py`.

Studio registers `tool_execution` in the passive `CapabilityRegistry` as a
per-agent observer provider. This is diagnostic visibility only: each
`SkillAgent` still owns its own observer instance, and execution remains in the
existing LangGraph/tool factory/SafeKernel path.

`SkillAgent._run_with_stream_intercept()` is the current pre-execution gate. It
records planned evidence, fires PreToolUse for every tool, and then applies the
existing write/dangerous HITL checks. Any future `ToolExecutionCapability` must
preserve this order.

`tool_factory.py` remains the execution implementation boundary. It delegates to
SafeKernel, SQLite, memory, code execution, or child agents. Capability adapters
must not bypass kernel entitlement checks, database policy checks, external
access checks, or result-budget truncation.

`TraceEmitter` receives two different span families from this flow:
- `span_type="hook"` from HookRunner audit sink when hook context has a parent
  `trace_id`.
- `span_type="tool"` from `TraceToolCallback.emit_spans()` after the ReAct turn.

## Extraction Rule

The current `ToolExecutionCapability` is observational only. It may report what
the current flow is doing, but it must not execute tools or replace the stream
intercept until parity tests cover PreToolUse, HITL blocking, tool result
capture, PostToolUse success/error, trace spans, evidence bundles, tool learning,
and SafeKernel entitlement denial.