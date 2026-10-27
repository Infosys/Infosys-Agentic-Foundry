"""AgentPro evaluator result mapping for RL/eval capture."""

from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from rl_capture.core.schema import CaptureMeta, EvaluatorResult, TargetRef, TargetType
from rl_capture.store.sqlite_store import get_rl_store


def rl_capture_enabled() -> bool:
    return os.getenv("RL_CAPTURE", "false").strip().lower() in {"1", "true", "yes", "on"}


def record_evaluator_result(
    *,
    data_root: str | Path,
    tenant_id: str,
    agent_id: str,
    trace_id: str,
    target_id: str = "",
    rubric: str,
    evaluator: str = "",
    verdict: str = "",
    score: float | None = None,
    details: dict[str, Any] | None = None,
) -> None:
    if not rl_capture_enabled() or not trace_id or not rubric:
        return
    now = datetime.now(timezone.utc).isoformat()
    result = EvaluatorResult(
        id=f"eval_{uuid.uuid4().hex}",
        target=TargetRef(
            trajectory_id=trace_id,
            target_type=TargetType.TRAJECTORY,
            target_id=target_id or trace_id,
        ),
        rubric=rubric,
        raw_scores={
            "score": score,
            "verdict": verdict,
            "details": details or {},
        },
        judge_id=evaluator or None,
        created_at=now,
        capture=CaptureMeta(
            adapter_version="agentpro:0.1.0",
            tenant_id=tenant_id,
            agent_id=agent_id,
            source_event_id=target_id or trace_id,
            source_trace_id=trace_id,
            capture_time=now,
        ),
        metadata={"verdict": verdict, **(details or {})},
    )
    db_path = os.getenv("RL_DB_PATH", "").strip() or None
    get_rl_store(data_root=data_root, tenant_id=tenant_id, db_path=db_path).record_evaluator_result(result)
