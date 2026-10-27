"""AgentPro adapter for passive RL/eval trajectory capture."""

from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from rl_capture.core.redaction import redact_value
from rl_capture.core.schema import (
    CandidateKind,
    CandidateOutput,
    CaptureFidelity,
    CaptureMeta,
    Message,
    ModelCall,
    Observation,
    PolicyRef,
    RedactionMeta,
    Role,
    StepKind,
    ToolCall,
    Trajectory,
    TrajectoryStep,
)
from rl_capture.store.sqlite_store import get_rl_store


ADAPTER_VERSION = "agentpro:0.1.0"


def rl_capture_enabled() -> bool:
    return os.getenv("RL_CAPTURE", "false").strip().lower() in {"1", "true", "yes", "on"}


def rl_redact_enabled() -> bool:
    return os.getenv("RL_REDACT", "true").strip().lower() not in {"0", "false", "no", "off"}


def capture_chat_turn(
    *,
    data_root: str | Path,
    tenant_id: str,
    agent_id: str,
    user_id: str,
    session_id: str,
    trace_id: str,
    user_query: str,
    final_response: str,
    skill_name: str,
    decision_context: dict[str, Any] | None = None,
    model_name: str = "",
    provider: str = "",
    status: str = "success",
    started_at: str | None = None,
    ended_at: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> None:
    """Capture one completed AgentPro chat turn.

    Best-effort by design: any exception is swallowed by callers. This function
    also returns normally when ``RL_CAPTURE`` is disabled.
    """
    if not rl_capture_enabled():
        return
    dc = decision_context or {}
    now = datetime.now(timezone.utc).isoformat()
    trajectory_id = str(trace_id or dc.get("trace_id") or uuid.uuid4().hex)
    capture_meta = CaptureMeta(
        adapter_version=ADAPTER_VERSION,
        tenant_id=tenant_id,
        agent_id=agent_id,
        source_event_id=trajectory_id,
        source_trace_id=trajectory_id,
        capture_time=now,
        redaction_policy_id="rl_redaction_v1" if rl_redact_enabled() else None,
    )

    query_value, query_redaction = _maybe_redact(user_query)
    response_value, response_redaction = _maybe_redact(final_response)

    routing = dc.get("routing") if isinstance(dc.get("routing"), dict) else {}
    outcome = dc.get("outcome") if isinstance(dc.get("outcome"), dict) else {}
    native_reasoning = dc.get("native_reasoning") if isinstance(dc.get("native_reasoning"), dict) else {}
    policy = PolicyRef(
        provider=provider or str(native_reasoning.get("provider") or ""),
        model=model_name or str(dc.get("model") or ""),
        decoding_id=str((dc.get("reasoning_ref") or {}).get("response_id") or "") or None
        if isinstance(dc.get("reasoning_ref"), dict)
        else None,
    )
    input_message = Message(
        role=Role.USER,
        content=str(query_value),
        redaction=query_redaction,
    )
    output_message = Message(
        role=Role.ASSISTANT,
        content=str(response_value),
        redaction=response_redaction,
    )
    model_call = ModelCall(
        id=f"{trajectory_id}:model:final",
        policy=policy,
        input_messages=[input_message],
        output_messages=[output_message],
        fidelity=CaptureFidelity.REASONING_PARTIAL if native_reasoning else CaptureFidelity.TEXT_ONLY,
        reasoning_ref=str(native_reasoning.get("preview_source") or native_reasoning.get("provider") or "") or None,
        prompt_tokens=_int_or_none(outcome.get("prompt_tokens") or dc.get("prompt_tokens")),
        completion_tokens=_int_or_none(outcome.get("completion_tokens") or dc.get("completion_tokens")),
        cost_usd=_float_or_none(outcome.get("cost_usd") or dc.get("cost_usd")),
        latency_ms=_int_or_none(outcome.get("processing_time_ms")),
        redaction=_combine_redactions(query_redaction, response_redaction),
        metadata={
            "routing": routing,
            "reasoning_summary": dc.get("reasoning_summary", ""),
            "native_reasoning": native_reasoning,
        },
    )

    steps: list[TrajectoryStep] = [
        TrajectoryStep(
            id=f"{trajectory_id}:step:route",
            index=0,
            kind=StepKind.ROUTER_DECISION,
            decision={
                "skill": skill_name,
                "routing": routing,
            },
        ),
        TrajectoryStep(
            id=f"{trajectory_id}:step:model_final",
            index=1,
            kind=StepKind.MODEL_CALL,
            model_call_id=model_call.id,
        ),
    ]
    tool_calls, observations, tool_steps = _tool_calls_from_decision_context(trajectory_id, dc, start_index=2)
    steps.extend(tool_steps)

    trajectory = Trajectory(
        id=trajectory_id,
        session_id=session_id,
        task=str(query_value),
        policy=policy,
        fidelity=model_call.fidelity,
        steps=steps,
        model_calls=[model_call],
        tool_calls=tool_calls,
        observations=observations,
        terminal_status=status,
        started_at=started_at,
        ended_at=ended_at or now,
        adapter="agentpro",
        tenant=tenant_id,
        capture=capture_meta,
        metadata={
            **(metadata or {}),
            "skill": skill_name,
            "user_id": user_id,
            "outcome": outcome,
            "redacted": model_call.redaction.redacted,
        },
    )
    db_path = os.getenv("RL_DB_PATH", "").strip() or None
    store = get_rl_store(data_root=data_root, tenant_id=tenant_id, db_path=db_path)
    store.record_trajectory(trajectory)
    store.record_candidate_output(
        CandidateOutput(
            id=f"{trajectory_id}:candidate:final",
            trajectory_id=trajectory_id,
            kind=CandidateKind.ORIGINAL,
            messages=[output_message],
            target=None,
            policy=policy,
            source="agentpro_final_response",
            created_at=now,
            capture=capture_meta,
            metadata={"model_call_id": model_call.id},
        )
    )


def record_tool_call_incremental(
    *,
    data_root: str | Path,
    tenant_id: str,
    trajectory_id: str,
    tool_call_id: str,
    name: str,
    arguments: Any = None,
    output: Any = None,
    status: str = "ok",
    duration_ms: int | None = None,
    error: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> None:
    """Capture one tool call/observation before UI preview truncation."""
    if not rl_capture_enabled() or not trajectory_id or not tool_call_id:
        return
    redacted_args, args_redaction = _maybe_redact(arguments or {})
    redacted_output, output_redaction = _maybe_redact(output)
    tool_call = ToolCall(
        id=tool_call_id,
        name=name or "unknown",
        arguments=redacted_args if isinstance(redacted_args, dict) else {"input": redacted_args},
        output=redacted_output,
        error=error,
        status=status,
        duration_ms=duration_ms,
        redaction=_combine_redactions(args_redaction, output_redaction),
        metadata=metadata or {},
    )
    observation = Observation(
        id=f"{tool_call_id}:observation",
        source=tool_call.name,
        payload=redacted_output,
        error=error,
        redaction=output_redaction,
        metadata={"tool_call_id": tool_call_id, **(metadata or {})},
    )
    db_path = os.getenv("RL_DB_PATH", "").strip() or None
    store = get_rl_store(data_root=data_root, tenant_id=tenant_id, db_path=db_path)
    store.record_tool_call(trajectory_id, tool_call)
    store.record_observation(trajectory_id, observation)


def _tool_calls_from_decision_context(
    trajectory_id: str,
    dc: dict[str, Any],
    *,
    start_index: int,
) -> tuple[list[ToolCall], list[Observation], list[TrajectoryStep]]:
    tool_calls: list[ToolCall] = []
    observations: list[Observation] = []
    steps: list[TrajectoryStep] = []
    for idx, raw in enumerate(dc.get("tool_calls") or []):
        if not isinstance(raw, dict):
            continue
        tool_id = str(raw.get("id") or f"{trajectory_id}:tool:{idx}")
        observation_id = f"{tool_id}:observation"
        raw_input, input_redaction = _maybe_redact(raw.get("input", ""))
        raw_output, output_redaction = _maybe_redact(raw.get("output") or raw.get("output_preview") or "")
        tool_call = ToolCall(
            id=tool_id,
            name=str(raw.get("tool") or raw.get("name") or "unknown"),
            arguments={"input": raw_input},
            output=raw_output,
            error=str(raw.get("error") or "") or None,
            status="error" if raw.get("has_error") else "ok",
            duration_ms=_int_or_none(raw.get("duration_ms")),
            redaction=_combine_redactions(input_redaction, output_redaction),
            metadata={k: v for k, v in raw.items() if k not in {"input", "output", "output_preview"}},
        )
        observation = Observation(
            id=observation_id,
            source=tool_call.name,
            payload=raw_output,
            error=tool_call.error,
            redaction=output_redaction,
        )
        tool_calls.append(tool_call)
        observations.append(observation)
        steps.append(
            TrajectoryStep(
                id=f"{trajectory_id}:step:tool:{idx}",
                index=start_index + idx,
                kind=StepKind.TOOL_CALL,
                tool_call_id=tool_id,
                observation_id=observation_id,
            )
        )
    return tool_calls, observations, steps


def _maybe_redact(value: Any) -> tuple[Any, RedactionMeta]:
    if not rl_redact_enabled():
        return value, RedactionMeta()
    result = redact_value(value)
    return result.value, RedactionMeta(
        redacted=result.redacted,
        redacted_fields=result.redacted_fields,
        structure_preserved=True,
        policy_version=result.policy_version,
    )


def _combine_redactions(*items: RedactionMeta) -> RedactionMeta:
    fields: list[str] = []
    for item in items:
        fields.extend(item.redacted_fields)
    return RedactionMeta(
        redacted=bool(fields),
        redacted_fields=fields,
        structure_preserved=True,
        policy_version="rl_redaction_v1" if fields else None,
    )


def _int_or_none(value: Any) -> int | None:
    try:
        if value is None or value == "":
            return None
        return int(value)
    except (TypeError, ValueError):
        return None


def _float_or_none(value: Any) -> float | None:
    try:
        if value is None or value == "":
            return None
        return float(value)
    except (TypeError, ValueError):
        return None
