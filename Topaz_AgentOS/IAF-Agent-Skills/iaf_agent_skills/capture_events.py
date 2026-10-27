"""Neutral capture event bridge for optional RL/eval projection.

Core AgentOS/AgentPro runtime code should call these ``emit_*`` functions
instead of importing ``rl_capture`` directly. This module is the single lazy
import boundary: when ``RL_CAPTURE`` is disabled every function is a no-op, and
when enabled adapter failures are suppressed so capture never breaks runtime
execution.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

from .runtime_bridge import default_agent_id, default_tenant_id

logger = logging.getLogger(__name__)


def _rl_on() -> bool:
    return os.getenv("RL_CAPTURE", "false").strip().lower() in {"1", "true", "yes", "on"}


def _debug_skip(event_name: str, exc: Exception) -> None:
    logger.debug("capture event %s suppressed: %s", event_name, exc)


def _target_type(value: Any):
    from rl_capture.core.schema import TargetType

    raw = getattr(value, "value", value) or TargetType.TRAJECTORY.value
    return TargetType(str(raw))


def _reward_channel(value: Any):
    from rl_capture.core.schema import RewardChannel

    raw = getattr(value, "value", value)
    return RewardChannel(str(raw))


def emit_chat_turn(**kwargs: Any) -> None:
    if not _rl_on():
        return
    try:
        from rl_capture.adapters.agentpro.capture import capture_chat_turn

        capture_chat_turn(**kwargs)
    except Exception as exc:
        _debug_skip("chat_turn", exc)


def emit_model_call(*, request: Any, response: Any, status: str = "success", error: str = "") -> None:
    if not _rl_on():
        return
    try:
        from rl_capture.adapters.agentpro.model_calls import record_model_call_event

        record_model_call_event(request=request, response=response, status=status, error=error)
    except Exception as exc:
        _debug_skip("model_call", exc)


def emit_tool_call(
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
    if not _rl_on():
        return
    try:
        from rl_capture.adapters.agentpro.capture import record_tool_call_incremental

        record_tool_call_incremental(
            data_root=data_root,
            tenant_id=tenant_id,
            trajectory_id=trajectory_id,
            tool_call_id=tool_call_id,
            name=name,
            arguments=arguments,
            output=output,
            status=status,
            duration_ms=duration_ms,
            error=error,
            metadata=metadata or {},
        )
    except Exception as exc:
        _debug_skip("tool_call", exc)


def emit_agentpro_reward(
    *,
    data_root: str | Path,
    tenant_id: str,
    agent_id: str,
    channel: str,
    raw_label: str,
    target_id: str,
    trajectory_id: str = "",
    target_type: str = "trajectory",
    judge_id: str = "",
    raw_value: float | None = None,
    notes: str = "",
    source_event_id: str = "",
    source_trace_id: str = "",
    metadata: dict[str, Any] | None = None,
) -> None:
    if not _rl_on():
        return
    try:
        from rl_capture.adapters.agentpro.rewards import record_agentpro_reward

        record_agentpro_reward(
            data_root=data_root,
            tenant_id=tenant_id,
            agent_id=agent_id,
            channel=channel,
            raw_label=raw_label,
            target_id=target_id,
            trajectory_id=trajectory_id,
            target_type=_target_type(target_type),
            judge_id=judge_id,
            raw_value=raw_value,
            notes=notes,
            source_event_id=source_event_id,
            source_trace_id=source_trace_id,
            metadata=metadata or {},
        )
    except Exception as exc:
        _debug_skip("agentpro_reward", exc)


def emit_feedback_thumbs(
    *,
    data_root: str | Path,
    tenant_id: str,
    agent_id: str,
    user_id: str,
    direction: str,
    trajectory_id: str,
    model_call_id: str = "",
    query: str = "",
    response_snippet: str = "",
    skill: str | None = None,
) -> None:
    if not _rl_on():
        return
    try:
        from rl_capture.adapters.agentpro.rewards import record_thumbs_reward

        record_thumbs_reward(
            data_root=data_root,
            tenant_id=tenant_id,
            agent_id=agent_id,
            user_id=user_id,
            direction=direction,
            trajectory_id=trajectory_id,
            model_call_id=model_call_id,
            query=query,
            response_snippet=response_snippet,
            skill=skill,
        )
    except Exception as exc:
        _debug_skip("feedback_thumbs", exc)


def emit_revision_preference(
    *,
    data_root: str | Path,
    tenant_id: str,
    agent_id: str,
    trajectory_id: str,
    original_response: str,
    revised_response: str,
    channel: str = "critique",
    judge_id: str = "critique",
    source: str = "critique_revision",
) -> None:
    if not _rl_on():
        return
    try:
        from rl_capture.adapters.agentpro.preferences import record_revision_preference

        record_revision_preference(
            data_root=data_root,
            tenant_id=tenant_id,
            agent_id=agent_id,
            trajectory_id=trajectory_id,
            original_response=original_response,
            revised_response=revised_response,
            channel=_reward_channel(channel),
            judge_id=judge_id,
            source=source,
        )
    except Exception as exc:
        _debug_skip("revision_preference", exc)


def emit_chat_critique(**kwargs: Any) -> None:
    emit_revision_preference(**kwargs)


def emit_correction(
    *,
    data_root: str | Path,
    tenant_id: str,
    agent_id: str,
    trajectory_id: str,
    original: str,
    corrected: str,
    actor: str = "human",
    channel: str = "human_edit",
    source: str = "human_correction",
    **_: Any,
) -> None:
    emit_revision_preference(
        data_root=data_root,
        tenant_id=tenant_id,
        agent_id=agent_id,
        trajectory_id=trajectory_id,
        original_response=original,
        revised_response=corrected,
        channel=channel,
        judge_id=actor,
        source=source,
    )


def emit_approval_resolved(
    *,
    data_root: str | Path,
    tenant_id: str,
    agent_id: str,
    approval_id: str,
    decision: str,
    actor: str = "",
    trace_id: str = "",
    notes: str = "",
    metadata: dict[str, Any] | None = None,
    correction: dict[str, Any] | None = None,
) -> None:
    emit_agentpro_reward(
        data_root=data_root,
        tenant_id=tenant_id,
        agent_id=agent_id,
        channel="human_approval",
        raw_label=decision,
        target_id=approval_id,
        trajectory_id=trace_id or approval_id,
        judge_id=actor,
        notes=notes,
        source_event_id=approval_id,
        source_trace_id=trace_id or approval_id,
        metadata=metadata or {},
    )
    if correction:
        emit_correction(
            data_root=data_root,
            tenant_id=tenant_id,
            agent_id=agent_id,
            trajectory_id=trace_id or approval_id,
            original=str(correction.get("original") or ""),
            corrected=str(correction.get("corrected") or ""),
            actor=actor or "human",
            source="approval_correction",
        )


def emit_queue_task_lifecycle(
    *,
    data_root: str | Path,
    tenant_id: str,
    task_id: str,
    status: str,
    trace_id: str = "",
    actor: str = "",
    notes: str = "",
    metadata: dict[str, Any] | None = None,
) -> None:
    emit_agentpro_reward(
        data_root=data_root,
        tenant_id=tenant_id,
        agent_id=default_agent_id(),
        channel="queue",
        raw_label=status,
        target_id=task_id,
        trajectory_id=trace_id or task_id,
        judge_id=actor,
        notes=notes,
        source_event_id=task_id,
        source_trace_id=trace_id or task_id,
        metadata=metadata or {},
    )


def emit_workstream_lifecycle(
    *,
    data_root: str | Path,
    tenant_id: str,
    workstream_id: str,
    status: str,
    item_id: str = "",
    trace_id: str = "",
    actor: str = "",
    notes: str = "",
    metadata: dict[str, Any] | None = None,
) -> None:
    target_id = f"{workstream_id}:{item_id}" if item_id else workstream_id
    emit_agentpro_reward(
        data_root=data_root,
        tenant_id=tenant_id,
        agent_id=default_agent_id(),
        channel="workstream",
        raw_label=status,
        target_id=target_id,
        trajectory_id=trace_id or target_id,
        judge_id=actor,
        notes=notes,
        source_event_id=target_id,
        source_trace_id=trace_id or target_id,
        metadata=metadata or {},
    )


def emit_hook_outcome(
    *,
    data_root: str | Path = "enterprise_root",
    tenant_id: str = "",
    agent_id: str = "",
    trace_id: str = "",
    hook_id: str = "",
    hook_event: str = "",
    outcome: str,
    target_id: str = "",
    notes: str = "",
    metadata: dict[str, Any] | None = None,
) -> None:
    if not _rl_on():
        return
    tenant_id = tenant_id or default_tenant_id()
    try:
        from rl_capture.adapters.agentpro.hooks import record_hook_outcome

        record_hook_outcome(
            data_root=data_root,
            tenant_id=tenant_id,
            agent_id=agent_id,
            trace_id=trace_id,
            hook_id=hook_id,
            hook_event=hook_event,
            outcome=outcome,
            target_id=target_id,
            notes=notes,
            metadata=metadata or {},
        )
    except Exception as exc:
        _debug_skip("hook_outcome", exc)


def emit_evaluator_result(
    *,
    data_root: str | Path = "enterprise_root",
    tenant_id: str = "",
    agent_id: str = "",
    trace_id: str,
    target_id: str = "",
    rubric: str,
    evaluator: str = "",
    verdict: str = "",
    score: float | None = None,
    details: dict[str, Any] | None = None,
) -> None:
    if not _rl_on():
        return
    tenant_id = tenant_id or default_tenant_id()
    try:
        from rl_capture.adapters.agentpro.evaluator import record_evaluator_result

        record_evaluator_result(
            data_root=data_root,
            tenant_id=tenant_id,
            agent_id=agent_id,
            trace_id=trace_id,
            target_id=target_id,
            rubric=rubric,
            evaluator=evaluator,
            verdict=verdict,
            score=score,
            details=details or {},
        )
    except Exception as exc:
        _debug_skip("evaluator_result", exc)
