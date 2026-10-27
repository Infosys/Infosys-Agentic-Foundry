"""AgentPro-specific reward signal mapping."""

from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from rl_capture.core.schema import CaptureMeta, RewardChannel, RewardEvent, TargetRef, TargetType
from rl_capture.store.sqlite_store import get_rl_store


def rl_capture_enabled() -> bool:
    return os.getenv("RL_CAPTURE", "false").strip().lower() in {"1", "true", "yes", "on"}


def record_thumbs_reward(
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
    if not rl_capture_enabled() or not trajectory_id:
        return
    raw_label = "up" if direction == "up" else "down"
    target = TargetRef(
        trajectory_id=trajectory_id,
        target_type=TargetType.MODEL_CALL if model_call_id else TargetType.TRAJECTORY,
        target_id=model_call_id or trajectory_id,
    )
    now = datetime.now(timezone.utc).isoformat()
    reward = RewardEvent(
        id=f"reward_{uuid.uuid4().hex}",
        channel=RewardChannel.THUMBS,
        target=target,
        raw_label=raw_label,
        judge_id=user_id,
        created_at=now,
        capture=CaptureMeta(
            adapter_version="agentpro:0.1.0",
            tenant_id=tenant_id,
            agent_id=agent_id,
            source_event_id=trajectory_id,
            source_trace_id=trajectory_id,
            capture_time=now,
        ),
        metadata={
            "skill": skill,
            "query": query[:500],
            "response_snippet": response_snippet[:500],
        },
    )
    db_path = os.getenv("RL_DB_PATH", "").strip() or None
    get_rl_store(data_root=data_root, tenant_id=tenant_id, db_path=db_path).record_reward_event(reward)


def record_agentpro_reward(
    *,
    data_root: str | Path,
    tenant_id: str,
    agent_id: str,
    channel: RewardChannel | str,
    raw_label: str,
    target_id: str,
    trajectory_id: str = "",
    target_type: TargetType = TargetType.TRAJECTORY,
    judge_id: str = "",
    raw_value: float | None = None,
    notes: str = "",
    source_event_id: str = "",
    source_trace_id: str = "",
    metadata: dict[str, Any] | None = None,
) -> None:
    """Record a generic AgentPro operational reward signal."""
    if not rl_capture_enabled() or not raw_label or not target_id:
        return
    reward_channel = channel if isinstance(channel, RewardChannel) else RewardChannel(str(channel))
    effective_trajectory_id = trajectory_id or source_trace_id or target_id
    now = datetime.now(timezone.utc).isoformat()
    reward = RewardEvent(
        id=f"reward_{uuid.uuid4().hex}",
        channel=reward_channel,
        target=TargetRef(
            trajectory_id=effective_trajectory_id,
            target_type=target_type,
            target_id=target_id,
        ),
        raw_label=raw_label,
        raw_value=raw_value,
        judge_id=judge_id or None,
        notes=notes[:1000] if notes else None,
        created_at=now,
        capture=CaptureMeta(
            adapter_version="agentpro:0.1.0",
            tenant_id=tenant_id,
            agent_id=agent_id,
            source_event_id=source_event_id or target_id,
            source_trace_id=source_trace_id or effective_trajectory_id,
            capture_time=now,
        ),
        metadata=metadata or {},
    )
    db_path = os.getenv("RL_DB_PATH", "").strip() or None
    get_rl_store(data_root=data_root, tenant_id=tenant_id, db_path=db_path).record_reward_event(reward)
