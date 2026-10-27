"""Automatic trajectory evaluator (Phase 3 follow-up).

Turns captured trajectories into **judgement signal** without waiting on human
volume: each trajectory is scored against a deterministic rubric and the verdict
is written as an ``evaluator``-channel reward event (judge category in the
Phase-3 shaper). Because it is a heuristic proxy — not a human — it emits a
**moderate confidence** so it never overpowers real human feedback: effective
weight is ``judge(0.7) × confidence(0.5) = 0.35``.

The scoring function is pure and deterministic (easy to test); the runner
persists rewards + evaluator results through the store. An LLM-judge can later
replace :func:`score_trajectory` behind the same interface.
"""

from __future__ import annotations

import json
import re
import uuid
from datetime import datetime, timezone
from typing import Any, Callable, Optional

from rl_capture.core.schema import (
    CaptureMeta,
    EvaluatorResult,
    RewardChannel,
    RewardEvent,
    TargetRef,
    TargetType,
)


RUBRIC_VERSION = "heuristic_v1"
LLM_RUBRIC_VERSION = "llm_judge_v1"
DEFAULT_JUDGE_ID = f"auto_evaluator:{RUBRIC_VERSION}"
LLM_JUDGE_ID = "trajectory_judge:llm_judge_v1"
DEFAULT_CONFIDENCE = 0.5
LLM_CONFIDENCE = 0.8

# A scorer maps a trajectory-detail dict to score/verdict/confidence/rubric/reasons; the LLM path passes a judge_fn.
Scorer = Callable[[dict], dict]

_REFUSAL_MARKERS = (
    "i cannot", "i can't", "i am unable", "i'm unable", "unable to",
    "not present", "no matching", "cannot retrieve", "don't have access",
    "do not have access", "is not accessible", "no data",
)
_ERROR_MARKERS = ("traceback", "exception", "stack trace", "failed to", "errno")


def _final_text(trajectory: dict) -> str:
    calls = trajectory.get("model_calls") or []
    if not calls:
        return ""
    last = calls[-1] or {}
    return "\n".join(
        str(m.get("content") or "")
        for m in (last.get("output_messages") or [])
        if isinstance(m, dict)
    ).strip()


def score_trajectory(detail: dict, rubric_config: Optional[dict[str, Any]] = None) -> dict:
    """Score one trajectory (accepts a detail dict or a bare trajectory).

    Returns ``{score in [-1,1], verdict, confidence, rubric, reasons[]}``.
    """
    rubric_config = rubric_config or {}
    trajectory = detail.get("trajectory") if isinstance(detail, dict) and "trajectory" in detail else detail
    trajectory = trajectory or {}
    reasons: list[str] = []
    score = 0.0

    status = str(trajectory.get("terminal_status") or "").lower()
    status_weights = dict(rubric_config.get("status_weights") or {})
    if status in ("success", "done"):
        score += float(status_weights.get("success", 0.5))
        reasons.append("terminal:success")
    elif status in ("failed", "cancelled"):
        score += float(status_weights.get(status, status_weights.get("failed", -0.6)))
        reasons.append(f"terminal:{status}")
    elif status in ("partial", "awaiting_human", "pending"):
        score += float(status_weights.get(status, -0.1))
        reasons.append(f"terminal:{status}")

    final = _final_text(trajectory)
    low = final.lower()
    min_chars = int(rubric_config.get("substantive_min_chars", 40) or 40)
    if final and len(final) >= min_chars:
        score += float(rubric_config.get("substantive_response_weight", 0.3))
        reasons.append("substantive_response")
    elif not final:
        score += float(rubric_config.get("empty_response_weight", -0.3))
        reasons.append("empty_response")

    refusal_markers = tuple(str(marker).lower() for marker in (rubric_config.get("refusal_markers") or _REFUSAL_MARKERS))
    error_markers = tuple(str(marker).lower() for marker in (rubric_config.get("error_markers") or _ERROR_MARKERS))
    if any(marker in low for marker in refusal_markers):
        score += float(rubric_config.get("refusal_weight", -0.4))
        reasons.append("refusal_or_missing_data")
    if any(marker in low for marker in error_markers):
        score += float(rubric_config.get("error_marker_weight", -0.2))
        reasons.append("error_markers")

    tools = trajectory.get("tool_calls") or []
    if tools:
        if any((t or {}).get("status") == "error" for t in tools):
            score += float(rubric_config.get("tool_error_weight", -0.3))
            reasons.append("tool_error")
        else:
            score += float(rubric_config.get("tools_ok_weight", 0.1))
            reasons.append("tools_ok")

    score = round(max(-1.0, min(1.0, score)), 3)
    pass_threshold = float(rubric_config.get("pass_threshold", 0.3))
    fail_threshold = float(rubric_config.get("fail_threshold", -0.3))
    verdict = "pass" if score >= pass_threshold else ("fail" if score <= fail_threshold else "partial")
    return {
        "score": score,
        "verdict": verdict,
        "confidence": float(rubric_config.get("confidence", DEFAULT_CONFIDENCE)),
        "rubric": str(rubric_config.get("version") or RUBRIC_VERSION),
        "reasons": reasons,
    }


def _verdict_from_score(score: float) -> str:
    return "pass" if score >= 0.3 else ("fail" if score <= -0.3 else "partial")


def build_judge_prompt(detail: dict) -> str:
    """Build the one-shot prompt handed to the ``trajectory_judge`` skill."""
    trajectory = detail.get("trajectory") if isinstance(detail, dict) and "trajectory" in detail else detail
    trajectory = trajectory or {}
    task = str(trajectory.get("task") or "")[:2000]
    response = _final_text(trajectory)[:2000]
    tools = trajectory.get("tool_calls") or []
    tool_summary = ", ".join(
        f"{(t or {}).get('name') or 'tool'}={(t or {}).get('status') or '?'}" for t in tools[:12]
    ) or "none"
    status = trajectory.get("terminal_status") or "unknown"
    return (
        "You are grading an AI agent's answer for training-data quality. "
        "Judge correctness, helpfulness, and faithfulness to the task.\n"
        "Respond with STRICT JSON only, no prose, exactly:\n"
        '{"score": <number between -1 and 1>, "verdict": "pass|partial|fail", "rationale": "<one sentence>"}\n\n'
        f"TASK:\n{task}\n\nAGENT RESPONSE:\n{response}\n\n"
        f"TOOLS: {tool_summary}\nTERMINAL_STATUS: {status}\n"
    )


def parse_judge_response(text: str, *, confidence: float = LLM_CONFIDENCE) -> dict:
    """Parse the judge skill's JSON output into a scored dict (robust).

    Extracts the first JSON object, clamps score to [-1, 1], and derives the
    verdict from the score when missing/inconsistent. Raises ValueError if no
    usable score can be found.
    """
    match = re.search(r"\{.*\}", str(text or ""), re.DOTALL)
    if not match:
        raise ValueError("judge response contained no JSON object")
    data = json.loads(match.group(0))
    raw_score = data.get("score")
    if raw_score is None:
        raise ValueError("judge response missing 'score'")
    score = round(max(-1.0, min(1.0, float(raw_score))), 3)
    verdict = str(data.get("verdict") or "").lower()
    if verdict not in ("pass", "partial", "fail"):
        verdict = _verdict_from_score(score)
    rationale = str(data.get("rationale") or data.get("reason") or "").strip()
    return {
        "score": score,
        "verdict": verdict,
        "confidence": confidence,
        "rubric": LLM_RUBRIC_VERSION,
        "reasons": [rationale] if rationale else ["llm_judge"],
    }


def _existing_evaluator_trajectories(store) -> set[str]:
    seen: set[str] = set()
    for reward in store.list_reward_events(limit=5000):
        if str(reward.get("channel") or "") == RewardChannel.EVALUATOR.value:
            seen.add(str((reward.get("target") or {}).get("trajectory_id") or ""))
    return seen


def evaluate_trajectories(
    store,
    *,
    tenant_id: str,
    agent_id: str = "enterprise_agent",
    limit: int = 50,
    overwrite: bool = False,
    trajectory_id: Optional[str] = None,
    judge_fn: Optional[Scorer] = None,
    judge_id: Optional[str] = None,
) -> dict:
    """Score trajectories and persist ``evaluator``-channel rewards.

    - ``judge_fn`` set → use it to score (LLM judge); else rule-based
      :func:`score_trajectory`.
    - ``trajectory_id`` set → evaluate just that one (implies overwrite).
    - otherwise evaluate up to ``limit`` recent trajectories, skipping any that
      already carry an evaluator reward unless ``overwrite`` is True.
    """
    scorer: Scorer = judge_fn or score_trajectory
    resolved_judge_id = judge_id or (LLM_JUDGE_ID if judge_fn else DEFAULT_JUDGE_ID)

    if trajectory_id:
        detail = store.trajectory_detail(trajectory_id)
        trajectories = [detail["trajectory"]] if detail and detail.get("trajectory") else []
        overwrite = True
    else:
        trajectories = store.list_trajectories(limit=limit)

    already = set() if overwrite else _existing_evaluator_trajectories(store)
    evaluated = 0
    skipped = 0
    errors = 0
    results: list[dict[str, Any]] = []

    for trajectory in trajectories:
        tid = str(trajectory.get("id") or "")
        if not tid:
            continue
        if tid in already:
            skipped += 1
            continue
        detail = store.trajectory_detail(tid) or {"trajectory": trajectory}
        try:
            scored = scorer(detail)
        except Exception as exc:  # noqa: BLE001 - a bad judge call shouldn't abort the batch
            errors += 1
            results.append({"trajectory_id": tid, "error": str(exc)})
            continue
        now = datetime.now(timezone.utc).isoformat()
        target = TargetRef(trajectory_id=tid, target_type=TargetType.TRAJECTORY, target_id=tid)
        capture = CaptureMeta(
            adapter_version="agentpro:auto_eval",
            tenant_id=tenant_id,
            agent_id=agent_id,
            source_event_id=tid,
            source_trace_id=tid,
            capture_time=now,
        )
        store.record_reward_event(RewardEvent(
            id=f"reward_{uuid.uuid4().hex}",
            channel=RewardChannel.EVALUATOR,
            target=target,
            raw_label=scored["verdict"],
            raw_value=scored["score"],
            confidence=scored.get("confidence", DEFAULT_CONFIDENCE),
            judge_id=resolved_judge_id,
            created_at=now,
            capture=capture,
            metadata={"rubric": scored.get("rubric"), "reasons": scored.get("reasons", [])},
        ))
        store.record_evaluator_result(EvaluatorResult(
            id=f"eval_{uuid.uuid4().hex}",
            target=target,
            rubric=scored.get("rubric") or RUBRIC_VERSION,
            raw_scores={"score": scored["score"], "verdict": scored["verdict"], "reasons": scored.get("reasons", [])},
            judge_id=resolved_judge_id,
            created_at=now,
            capture=capture,
            metadata={"verdict": scored["verdict"]},
        ))
        evaluated += 1
        results.append({"trajectory_id": tid, **scored})

    return {
        "evaluated": evaluated,
        "skipped": skipped,
        "errors": errors,
        "judge_id": resolved_judge_id,
        "results": results,
    }
