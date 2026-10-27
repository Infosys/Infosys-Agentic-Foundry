"""Framework-neutral eval suite runner."""

from __future__ import annotations

import time
import uuid
from datetime import datetime, timezone
from typing import Any, Callable

from rl_capture.core.auto_evaluator import score_trajectory
from rl_capture.core.schema import (
    CaptureMeta,
    EvaluatorResult,
    RewardChannel,
    RewardEvent,
    TargetRef,
    TargetType,
)
from rl_capture.evals.rubric import extract_output_text, score_expected_output

CandidateProducer = Callable[[dict[str, Any], dict[str, Any]], dict[str, Any]]
JudgeFn = Callable[[dict[str, Any]], dict[str, Any]]
EvaluatorFn = Callable[[dict[str, Any]], dict[str, Any]]


def run_suite(
    *,
    suite: dict[str, Any],
    cases: list[dict[str, Any]],
    eval_store: Any,
    candidate_producer: CandidateProducer,
    tenant_id: str,
    agent_id: str = "",
    trigger: str = "manual",
    run_id: str | None = None,
    rl_store: Any = None,
    judge_fn: JudgeFn | None = None,
    evaluator_fn: EvaluatorFn | None = None,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Run a suite and persist run/case rows through the injected stores."""
    resolved_run_id = run_id or f"eval_run_{uuid.uuid4().hex[:12]}"
    started = time.time()
    eval_store.create_run(
        run_id=resolved_run_id,
        suite=suite,
        tenant_id=tenant_id,
        agent_id=agent_id,
        trigger=trigger,
        metadata=metadata or {},
    )
    counts = {"pass": 0, "partial": 0, "fail": 0}
    scores: list[float] = []
    errors = 0
    llm_used = 0
    case_results: list[dict[str, Any]] = []
    error_summary = ""

    try:
        for index, case in enumerate(cases, start=1):
            case_started = time.time()
            case_id = str(case.get("id") or f"case_{index}")
            target = suite.get("target") or {}
            try:
                candidate = candidate_producer(case, suite)
                output_text = extract_output_text(candidate)
                scored = _score_case(
                    case=case,
                    suite=suite,
                    candidate=candidate,
                    judge_fn=judge_fn,
                    evaluator_fn=evaluator_fn,
                    llm_used=llm_used,
                )
                llm_used += int(scored.pop("_llm_used", False))
                verdict = scored["verdict"]
                counts[verdict if verdict in counts else "partial"] += 1
                scores.append(float(scored.get("score") or 0.0))
                duration_ms = int((time.time() - case_started) * 1000)
                row = eval_store.append_case(
                    run_id=resolved_run_id,
                    case_id=case_id,
                    tenant_id=tenant_id,
                    suite_id=suite["id"],
                    status="success",
                    verdict=verdict,
                    score=float(scored.get("score") or 0.0),
                    target_type=str(target.get("type") or ""),
                    target_name=str(target.get("name") or target.get("role") or ""),
                    output_text=output_text,
                    duration_ms=duration_ms,
                    case=case,
                    assertions=scored.get("assertions") or {},
                    evaluator=scored,
                    metadata={"candidate": candidate.get("metadata") or {}},
                )
                _record_rl_signals(
                    rl_store=rl_store,
                    run_id=resolved_run_id,
                    suite=suite,
                    case=case,
                    candidate=candidate,
                    scored=scored,
                    tenant_id=tenant_id,
                    agent_id=agent_id,
                )
                case_results.append(row)
            except Exception as exc:  # noqa: BLE001 - one bad case must not abort the suite
                errors += 1
                counts["fail"] += 1
                duration_ms = int((time.time() - case_started) * 1000)
                row = eval_store.append_case(
                    run_id=resolved_run_id,
                    case_id=case_id,
                    tenant_id=tenant_id,
                    suite_id=suite["id"],
                    status="failed",
                    verdict="fail",
                    score=-1.0,
                    target_type=str(target.get("type") or ""),
                    target_name=str(target.get("name") or target.get("role") or ""),
                    error=str(exc),
                    duration_ms=duration_ms,
                    case=case,
                    evaluator={"score": -1.0, "verdict": "fail", "reasons": [str(exc)]},
                )
                scores.append(-1.0)
                case_results.append(row)
        status = "success" if errors == 0 else ("failed" if errors == len(cases) else "partial")
    except Exception as exc:  # pragma: no cover - run-level defensive path
        status = "failed"
        error_summary = str(exc)

    duration_ms = int((time.time() - started) * 1000)
    avg_score = round(sum(scores) / len(scores), 3) if scores else 0.0
    summary = (
        f"{counts['pass']} passed, {counts['partial']} partial, "
        f"{counts['fail']} failed out of {len(cases)} cases"
    )
    eval_store.finish_run(
        resolved_run_id,
        status=status,
        duration_ms=duration_ms,
        total_cases=len(cases),
        passed=counts["pass"],
        partial=counts["partial"],
        failed=counts["fail"],
        score=avg_score,
        summary=summary,
        error_summary=error_summary,
    )
    trace = eval_store.get_run(resolved_run_id) or {"run": {"run_id": resolved_run_id}, "cases": case_results}
    return {
        "run_id": resolved_run_id,
        "status": status,
        "summary": summary,
        "score": avg_score,
        "counts": counts,
        "errors": errors,
        "llm_judge_used": llm_used,
        "trace": trace,
    }


def _score_case(
    *,
    case: dict[str, Any],
    suite: dict[str, Any],
    candidate: dict[str, Any],
    judge_fn: JudgeFn | None,
    evaluator_fn: EvaluatorFn | None,
    llm_used: int,
) -> dict[str, Any]:
    detail = _candidate_as_trajectory(candidate, case)
    judge = suite.get("judge") or {}
    assertion_score = score_expected_output(
        candidate,
        expected=case.get("expected"),
        assertions=[*(suite.get("assertions") or []), *(case.get("assertions") or [])],
    )
    evaluator = suite.get("evaluator") or {}
    weights = evaluator.get("weights") or {}
    components: list[dict[str, Any]] = []
    heuristic = score_trajectory(detail, rubric_config=suite.get("rubric") or {})
    components.append(_component("rule", heuristic, weight=float(weights.get("rule", 1.0))))
    if assertion_score.get("assertions", {}).get("total", 0):
        components.append(_component("assertions", assertion_score, weight=float(weights.get("assertions", 1.0))))
    python_result: dict[str, Any] | None = None
    if evaluator.get("type") == "python":
        if evaluator_fn is None:
            python_result = {
                "score": -1.0,
                "verdict": "fail",
                "confidence": 1.0,
                "reasons": [f"python evaluator '{evaluator.get('id')}' is not configured"],
                "error": "missing evaluator_fn",
            }
        else:
            python_result = evaluator_fn({
                "suite": suite,
                "case": case,
                "candidate": candidate,
                "assertions": assertion_score,
            })
        components.append(_component("python", python_result, weight=float(weights.get("python", 1.0))))
    pre_judge = _combine_components(components)
    use_llm = _should_use_llm(
        judge,
        judge_fn=judge_fn,
        case_index=llm_used,
        preliminary=pre_judge,
        case=case,
        python_result=python_result,
    )
    llm_result: dict[str, Any] | None = None
    if use_llm and judge_fn:
        llm_result = judge_fn(detail)
        components.append(_component("judge", llm_result, weight=float(weights.get("judge", 1.0))))
    combined = _combine_components(components)
    critical_failures = _critical_failures(assertion_score, python_result=python_result, evaluator=evaluator)
    if critical_failures:
        combined["score"] = min(float(combined.get("score") or 0.0), -1.0)
        combined["reasons"].extend([f"critical:{item}" for item in critical_failures])
    pass_threshold = float((suite.get("thresholds") or {}).get("pass_score", (suite.get("rubric") or {}).get("pass_threshold", 0.3)))
    fail_threshold = float((suite.get("thresholds") or {}).get("fail_score", (suite.get("rubric") or {}).get("fail_threshold", -0.3)))
    verdict = "fail" if critical_failures else ("pass" if combined["score"] >= pass_threshold else ("fail" if combined["score"] <= fail_threshold else "partial"))
    return {
        "score": combined["score"],
        "verdict": verdict,
        "confidence": combined["confidence"],
        "rubric": "eval_runner_v2",
        "reasons": combined["reasons"],
        "assertions": assertion_score.get("assertions") or {},
        "components": components,
        "critical_failures": critical_failures,
        "python": python_result or {},
        "judge": llm_result or {},
        "_llm_used": use_llm,
    }


def _should_use_llm(
    judge: dict[str, Any],
    *,
    judge_fn: JudgeFn | None,
    case_index: int,
    preliminary: dict[str, Any],
    case: dict[str, Any],
    python_result: dict[str, Any] | None,
) -> bool:
    if judge_fn is None:
        return False
    mode = str(judge.get("mode") or "rule").lower()
    if mode == "llm":
        max_cases = int(judge.get("max_llm_cases") or 0)
        return max_cases <= 0 or case_index < max_cases
    if mode == "hybrid":
        sample_size = int(judge.get("sample_size") or 0)
        max_cases = int(judge.get("max_llm_cases") or sample_size or 0)
        limit = min(sample_size or max_cases, max_cases or sample_size)
        if limit > 0 and case_index >= limit:
            return False
        if python_result and python_result.get("error") and bool(judge.get("escalate_on_error", True)):
            return True
        tags = set(str(tag) for tag in (case.get("tags") or []))
        judge_tags = set(str(tag) for tag in (judge.get("case_tags") or []))
        if tags.intersection(judge_tags):
            return True
        confidence_below = judge.get("confidence_below")
        if confidence_below is not None and float(preliminary.get("confidence") or 0.0) < float(confidence_below):
            return True
        score = float(preliminary.get("score") or 0.0)
        lower = judge.get("borderline_min")
        upper = judge.get("borderline_max")
        if lower is not None and upper is not None and float(lower) <= score <= float(upper):
            return True
        return limit <= 0
    return False


def _component(name: str, result: dict[str, Any], *, weight: float) -> dict[str, Any]:
    return {
        "name": name,
        "score": _clamp(float(result.get("score") or 0.0)),
        "verdict": result.get("verdict") or "",
        "confidence": max(0.0, min(1.0, float(result.get("confidence") or 0.0))),
        "weight": max(0.0, float(weight or 0.0)),
        "reasons": [str(item) for item in (result.get("reasons") or [])],
        "rubric": result.get("rubric") or name,
        "result": result,
    }


def _combine_components(components: list[dict[str, Any]]) -> dict[str, Any]:
    weighted = [item for item in components if float(item.get("weight") or 0.0) > 0]
    if not weighted:
        return {"score": 0.0, "confidence": 0.0, "reasons": [], "components": []}
    denom = sum(float(item["weight"]) for item in weighted)
    score = round(sum(float(item["score"]) * float(item["weight"]) for item in weighted) / denom, 3)
    confidence = round(max(float(item.get("confidence") or 0.0) for item in weighted), 3)
    reasons: list[str] = []
    for item in weighted:
        reasons.extend(f"{item['name']}:{reason}" for reason in item.get("reasons") or [])
    return {"score": _clamp(score), "confidence": confidence, "reasons": reasons, "components": components}


def _critical_failures(
    assertion_score: dict[str, Any],
    *,
    python_result: dict[str, Any] | None,
    evaluator: dict[str, Any],
) -> list[str]:
    failures: list[str] = []
    for result in ((assertion_score.get("assertions") or {}).get("results") or []):
        if result.get("critical") and not result.get("passed"):
            failures.append(str(result.get("id") or result.get("type") or "assertion"))
    for name in evaluator.get("critical") or []:
        components = (python_result or {}).get("components") or {}
        component = components.get(name)
        if isinstance(component, dict) and component.get("passed") is False:
            failures.append(name)
        elif isinstance(component, (int, float)) and float(component) < 0:
            failures.append(name)
    if python_result and python_result.get("verdict") == "fail" and "python" in (evaluator.get("critical") or []):
        failures.append("python")
    return failures


def _clamp(value: float) -> float:
    return round(max(-1.0, min(1.0, value)), 3)


def _candidate_as_trajectory(candidate: dict[str, Any], case: dict[str, Any]) -> dict[str, Any]:
    output = extract_output_text(candidate)
    return {
        "trajectory": {
            "id": str((candidate.get("metadata") or {}).get("trajectory_id") or case.get("id") or ""),
            "task": case.get("task") or "",
            "terminal_status": "success" if not candidate.get("error") else "failed",
            "model_calls": [{"output_messages": [{"role": "assistant", "content": output}]}] if output else [],
            "tool_calls": candidate.get("tool_calls") or [],
            "metadata": candidate.get("metadata") or {},
        }
    }


def _record_rl_signals(
    *,
    rl_store: Any,
    run_id: str,
    suite: dict[str, Any],
    case: dict[str, Any],
    candidate: dict[str, Any],
    scored: dict[str, Any],
    tenant_id: str,
    agent_id: str,
) -> None:
    if rl_store is None:
        return
    now = datetime.now(timezone.utc).isoformat()
    metadata = {**(case.get("metadata") or {}), **(candidate.get("metadata") or {})}
    trajectory_id = str(metadata.get("trajectory_id") or (case.get("inputs") or {}).get("trajectory_id") or f"{run_id}:{case.get('id')}")
    target = TargetRef(trajectory_id=trajectory_id, target_type=TargetType.TRAJECTORY, target_id=trajectory_id)
    capture = CaptureMeta(
        adapter_version="agentpro:eval_runner",
        tenant_id=tenant_id,
        agent_id=agent_id,
        source_event_id=run_id,
        source_trace_id=trajectory_id,
        capture_time=now,
    )
    channel = RewardChannel.SHADOW_EVAL if str((suite.get("target") or {}).get("type") or "") == "model_role" else RewardChannel.EVALUATOR
    try:
        rl_store.record_reward_event(RewardEvent(
            id=f"reward_{uuid.uuid4().hex}",
            channel=channel,
            target=target,
            raw_label=str(scored.get("verdict") or ""),
            raw_value=float(scored.get("score") or 0.0),
            confidence=float(scored.get("confidence") or 0.0),
            judge_id=f"eval_suite:{suite.get('id')}",
            created_at=now,
            capture=capture,
            metadata={"run_id": run_id, "case_id": case.get("id"), "reasons": scored.get("reasons") or []},
        ))
        rl_store.record_evaluator_result(EvaluatorResult(
            id=f"eval_{uuid.uuid4().hex}",
            target=target,
            rubric=str(scored.get("rubric") or "eval_runner_v1"),
            raw_scores={"score": scored.get("score"), "verdict": scored.get("verdict"), "reasons": scored.get("reasons") or []},
            judge_id=f"eval_suite:{suite.get('id')}",
            created_at=now,
            capture=capture,
            metadata={"run_id": run_id, "case_id": case.get("id")},
        ))
        shadow_run = candidate.get("shadow_run")
        if shadow_run is not None:
            rl_store.record_shadow_run(shadow_run)
    except Exception:
        # RL capture is a judgement mirror here; eval_store remains authoritative
        # for suite execution and must not fail because capture is unavailable.
        return
