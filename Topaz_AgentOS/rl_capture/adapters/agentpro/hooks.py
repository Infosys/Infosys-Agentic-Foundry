"""AgentPro hook outcome mapping for RL/eval capture."""

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


def record_hook_outcome(
    *,
    data_root: str | Path,
    tenant_id: str,
    agent_id: str,
    trace_id: str,
    hook_id: str,
    hook_event: str,
    outcome: str,
    target_id: str = "",
    notes: str = "",
    metadata: dict[str, Any] | None = None,
) -> None:
    if not rl_capture_enabled() or not outcome:
        return
    effective_trace_id = trace_id or target_id or hook_id or f"hook_{uuid.uuid4().hex}"
    effective_target_id = target_id or hook_id or effective_trace_id
    now = datetime.now(timezone.utc).isoformat()
    reward = RewardEvent(
        id=f"reward_{uuid.uuid4().hex}",
        channel=RewardChannel.HOOK,
        target=TargetRef(
            trajectory_id=effective_trace_id,
            target_type=TargetType.TRAJECTORY,
            target_id=effective_target_id,
        ),
        raw_label=outcome,
        judge_id=hook_id or None,
        notes=notes[:1000] if notes else None,
        created_at=now,
        capture=CaptureMeta(
            adapter_version="agentpro:0.1.0",
            tenant_id=tenant_id,
            agent_id=agent_id,
            source_event_id=hook_id or effective_target_id,
            source_trace_id=effective_trace_id,
            capture_time=now,
        ),
        metadata={"hook_event": hook_event, **(metadata or {})},
    )
    db_path = os.getenv("RL_DB_PATH", "").strip() or None
    get_rl_store(data_root=data_root, tenant_id=tenant_id, db_path=db_path).record_reward_event(reward)
