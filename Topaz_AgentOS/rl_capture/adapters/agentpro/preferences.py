"""AgentPro-specific preference signal mapping."""

from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone
from pathlib import Path

from rl_capture.core.schema import (
    CandidateKind,
    CandidateOutput,
    CaptureMeta,
    Message,
    PairProvenance,
    PreferenceSignal,
    RewardChannel,
    Role,
    TargetRef,
    TargetType,
)
from rl_capture.store.sqlite_store import get_rl_store


def rl_capture_enabled() -> bool:
    return os.getenv("RL_CAPTURE", "false").strip().lower() in {"1", "true", "yes", "on"}


def record_revision_preference(
    *,
    data_root: str | Path,
    tenant_id: str,
    agent_id: str,
    trajectory_id: str,
    original_response: str,
    revised_response: str,
    channel: RewardChannel = RewardChannel.CRITIQUE,
    judge_id: str = "critique",
    source: str = "critique_revision",
) -> PreferenceSignal | None:
    if not rl_capture_enabled() or not trajectory_id or not original_response or not revised_response:
        return None
    now = datetime.now(timezone.utc).isoformat()
    db_path = os.getenv("RL_DB_PATH", "").strip() or None
    store = get_rl_store(data_root=data_root, tenant_id=tenant_id, db_path=db_path)
    capture = CaptureMeta(
        adapter_version="agentpro:0.1.0",
        tenant_id=tenant_id,
        agent_id=agent_id,
        source_event_id=trajectory_id,
        source_trace_id=trajectory_id,
        capture_time=now,
    )
    original = CandidateOutput(
        id=f"candidate_{uuid.uuid4().hex}",
        trajectory_id=trajectory_id,
        kind=CandidateKind.ORIGINAL,
        messages=[Message(role=Role.ASSISTANT, content=original_response)],
        source=source,
        created_at=now,
        capture=capture,
    )
    revised = CandidateOutput(
        id=f"candidate_{uuid.uuid4().hex}",
        trajectory_id=trajectory_id,
        kind=CandidateKind.REVISED,
        messages=[Message(role=Role.ASSISTANT, content=revised_response)],
        source=source,
        created_at=now,
        capture=capture,
    )
    store.record_candidate_output(original)
    store.record_candidate_output(revised)
    preference = PreferenceSignal(
        id=f"pref_{uuid.uuid4().hex}",
        context_ref=TargetRef(trajectory_id=trajectory_id, target_type=TargetType.TRAJECTORY, target_id=trajectory_id),
        preferred_ref=TargetRef(trajectory_id=trajectory_id, target_type=TargetType.STEP, target_id=revised.id),
        dispreferred_ref=TargetRef(trajectory_id=trajectory_id, target_type=TargetType.STEP, target_id=original.id),
        provenance=PairProvenance.SYNTHETIC if judge_id != "human" else PairProvenance.HUMAN_EDIT,
        channel=channel,
        judge_id=judge_id,
        created_at=now,
        capture=capture,
        metadata={"source": source},
    )
    store.record_preference_signal(preference)
    return preference
