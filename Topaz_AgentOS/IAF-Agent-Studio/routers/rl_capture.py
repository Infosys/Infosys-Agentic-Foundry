"""RL/eval capture inspection, drill-down, correction, and export endpoints."""

from __future__ import annotations

import asyncio
import ast
import logging
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from security.dependencies import require_scoped_identity
from shared.config import DATA_ROOT_PATH, PROJECT_ROOT, RL_DB_PATH, TENANT_ID
from iaf_agent_skills.capture_events import emit_correction
from rl_capture.cli import EXPORT_FORMATS, EXPORT_KINDS, preview_export_counts, run_export
from rl_capture.core.reward_shaping import classify_channel, is_judgement_channel
from rl_capture.store.sqlite_store import get_rl_store

logger = logging.getLogger(__name__)
router = APIRouter()


class RLCorrectionRequest(BaseModel):
    tenant_id: str = TENANT_ID
    agent_id: str = "enterprise_agent"
    user_id: str = "demo"
    trajectory_id: str = Field(..., min_length=1)
    original_response: str = Field(..., min_length=1)
    corrected_response: str = Field(..., min_length=1)
    source: str = "api_correction"


class RLExportRequest(BaseModel):
    tenant_id: str = TENANT_ID
    kind: str = Field(..., description="Export kind: sft, eval, dpo, kto, rejection_sft, rft, tool_sft")
    format: str = Field("prompt_completion", description="SFT format: chat | prompt_completion")
    limit: int = Field(1000, ge=1, le=100_000)
    eval_verdict: str = Field("", description="Optional evaluator verdict filter: pass, partial, fail")
    golden_set: str = Field("", description="Optional golden-set id used to filter promoted trajectories")
    trace_destination: str = Field("", description="Optional trace-value destination filter, e.g. model_training")
    trace_route_status: str = Field("approved", description="Trace-value route status required when trace_destination is set")
    since: str = Field("", description="Optional ISO timestamp lower bound")
    until: str = Field("", description="Optional ISO timestamp upper bound")


class RLEvaluateRequest(BaseModel):
    tenant_id: str = TENANT_ID
    agent_id: str = "enterprise_agent"
    mode: str = Field("rule", description="Judge mode: rule (deterministic heuristic) | llm (trajectory_judge skill)")
    limit: int = Field(50, ge=1, le=2000)
    overwrite: bool = False
    trajectory_id: Optional[str] = None
    judge_skill: str = "trajectory_judge"


@router.get("/api/rl-capture/health")
async def rl_capture_health(request: Request, tenant_id: str = TENANT_ID):
    """Return dataset counts for the tenant RL capture store."""
    _principal, tenant_id, _agent_id, _user_id = require_scoped_identity(
        request,
        requested_tenant=tenant_id,
        action="read",
        resource_type="rl_capture",
        resource_id="health",
    )
    store = _store_for_tenant(tenant_id)
    return {
        "tenant_id": tenant_id,
        "db_path": _store_db_path(tenant_id),
        "health": store.dataset_health(),
    }


@router.post("/api/rl-capture/correction")
async def rl_capture_correction(req: RLCorrectionRequest, request: Request):
    """Record a human correction as an RL preference signal through the bridge."""
    _principal, tenant_id, agent_id, user_id = require_scoped_identity(
        request,
        requested_tenant=req.tenant_id,
        requested_agent=req.agent_id,
        requested_user=req.user_id,
        action="write",
        resource_type="rl_capture",
        resource_id=req.trajectory_id,
    )
    if req.original_response.strip() == req.corrected_response.strip():
        raise HTTPException(status_code=400, detail="corrected_response must differ from original_response")
    emit_correction(
        data_root=DATA_ROOT_PATH,
        tenant_id=tenant_id,
        agent_id=agent_id,
        trajectory_id=req.trajectory_id,
        original=req.original_response,
        corrected=req.corrected_response,
        actor=user_id,
        channel="human_edit",
        source=req.source,
    )
    store = _store_for_tenant(tenant_id)
    preferences = store.list_preference_signals(trajectory_id=req.trajectory_id, limit=10)
    return {
        "status": "recorded",
        "tenant_id": tenant_id,
        "trajectory_id": req.trajectory_id,
        "preference_signals": len(preferences),
    }


@router.get("/api/rl-capture/latest")
async def rl_capture_latest(request: Request, tenant_id: str = TENANT_ID):
    """Return a compact preview of the latest captured trajectory."""
    _principal, tenant_id, _agent_id, _user_id = require_scoped_identity(
        request,
        requested_tenant=tenant_id,
        action="read",
        resource_type="rl_capture",
        resource_id="latest",
    )
    store = _store_for_tenant(tenant_id)
    trajectories = store.list_trajectories(limit=1)
    if not trajectories:
        return {"tenant_id": tenant_id, "trajectory": None}
    trajectory = trajectories[0]
    return {
        "tenant_id": tenant_id,
        "trajectory": {
            "id": trajectory.get("id"),
            "session_id": trajectory.get("session_id"),
            "task": trajectory.get("task"),
            "fidelity": trajectory.get("fidelity"),
            "terminal_status": trajectory.get("terminal_status"),
            "metadata": trajectory.get("metadata"),
            "model_calls": len(trajectory.get("model_calls") or []),
            "tool_calls": len(trajectory.get("tool_calls") or []),
            "observations": len(trajectory.get("observations") or []),
        },
    }


@router.get("/api/rl-capture/summary")
async def rl_capture_summary(request: Request, tenant_id: str = TENANT_ID, limit: int = 12):
    """Return executive summary data for the standalone RL/Eval Center."""
    _principal, tenant_id, _agent_id, _user_id = require_scoped_identity(
        request,
        requested_tenant=tenant_id,
        action="read",
        resource_type="rl_capture",
        resource_id="summary",
    )
    store = _store_for_tenant(tenant_id)
    health = store.dataset_health()
    trajectories = store.list_trajectories(limit=max(1, min(limit, 50)))
    rewards = store.list_reward_events(limit=500)
    preferences = store.list_preference_signals(limit=100)
    exports = store.list_exports(limit=20)
    reward_channels = Counter(str(row.get("channel") or "") for row in rewards)
    reward_labels = Counter(str(row.get("raw_label") or "") for row in rewards)
    terminal_status = Counter(str(row.get("terminal_status") or "unknown") for row in trajectories)
    total_reward_signals = sum(reward_channels.values())
    # Only genuine judgement (not operational process traces) drives richness and readiness.
    judgement_reward_signals = sum(1 for row in rewards if is_judgement_channel(row.get("channel")))
    operational_reward_signals = total_reward_signals - judgement_reward_signals
    channel_categories = {channel: classify_channel(channel) for channel in reward_channels}
    preference_count = int(health.get("preference_signals", 0) or 0)
    trajectory_count = int(health.get("trajectories", 0) or 0)
    model_call_count = int(health.get("model_calls", 0) or 0)
    judgement_signal_count = judgement_reward_signals + preference_count
    signal_richness = min(
        100,
        round(
            (
                min(trajectory_count, 10) * 3
                + min(model_call_count, 20) * 2
                + min(judgement_reward_signals, 25) * 2
                + min(preference_count, 10) * 3
            )
            / 1.4
        ),
    )
    return {
        "tenant_id": tenant_id,
        "db_path": _store_db_path(tenant_id),
        "health": health,
        "effectiveness": {
            "signal_richness_score": signal_richness,
            "trajectory_coverage": trajectory_count,
            "model_call_depth": model_call_count,
            "judgement_signals": judgement_signal_count,
            "reward_breakdown": {
                "judgement": judgement_reward_signals,
                "operational": operational_reward_signals,
            },
            "export_readiness": {
                "sft": trajectory_count > 0,
                "eval": trajectory_count > 0,
                "dpo": preference_count > 0,
                "kto": judgement_reward_signals > 0,
                "rejection_sft": judgement_reward_signals > 0,
                "rft": trajectory_count > 0 and judgement_reward_signals > 0,
            },
        },
        "breakdowns": {
            "reward_channels": dict(reward_channels),
            "reward_labels": dict(reward_labels.most_common(12)),
            "terminal_status": dict(terminal_status),
            "channel_categories": channel_categories,
        },
        "recent": {
            "trajectories": [_trajectory_preview(row) for row in trajectories[:8]],
            "rewards": [_reward_preview(row) for row in rewards[:10]],
            "preferences": [_preference_preview(row) for row in preferences[:8]],
            "exports": exports[:5],
        },
    }


@router.get("/api/rl-capture/timeseries")
async def rl_capture_timeseries(request: Request, tenant_id: str = TENANT_ID, hours: int = 24):
    """Return hourly bucketed counts for sparkline rendering."""
    _principal, tenant_id, _agent_id, _user_id = require_scoped_identity(
        request,
        requested_tenant=tenant_id,
        action="read",
        resource_type="rl_capture",
        resource_id="timeseries",
    )
    store = _store_for_tenant(tenant_id)
    return {
        "tenant_id": tenant_id,
        "hours": hours,
        "series": store.time_series(hours=hours),
    }


@router.get("/api/rl-capture/trajectories")
async def rl_capture_trajectories(
    request: Request,
    tenant_id: str = TENANT_ID,
    limit: int = 100,
    terminal_status: Optional[str] = None,
    skill: Optional[str] = None,
    q: Optional[str] = None,
    session_id: Optional[str] = None,
    include_debug: bool = False,
    trace_assessment_status: Optional[str] = None,
    trace_destination: Optional[str] = None,
    trace_route_status: Optional[str] = None,
    trace_min_score: float = 0.0,
):
    """List trajectories with lightweight preview fields and Trace Value filters."""
    _principal, tenant_id, _agent_id, _user_id = require_scoped_identity(
        request,
        requested_tenant=tenant_id,
        action="read",
        resource_type="rl_capture",
        resource_id="trajectories",
    )
    limit = max(1, min(int(limit), 500))
    trace_min_score = max(0.0, min(float(trace_min_score), 1.0))
    store = _store_for_tenant(tenant_id)
    fetch_limit = min(max(limit * 10, 500), 5_000)
    trace_rows = store.list_trajectories_with_trace_filters(
        limit=fetch_limit,
        tenant_id=tenant_id,
        session_id=session_id or None,
        assessment_status=trace_assessment_status or None,
        destination=trace_destination or None,
        route_status=trace_route_status or None,
        min_destination_score=trace_min_score,
        include_debug=include_debug,
    )

    rows: list[dict] = []
    needle = (q or "").strip().lower()
    for trace_row in trace_rows:
        trajectory = trace_row["trajectory"]
        preview_source = _hydrate_sparse_trajectory(store, trajectory)
        if terminal_status and str(trajectory.get("terminal_status") or "") != terminal_status:
            continue
        metadata = preview_source.get("metadata") or {}
        row_skill = str(metadata.get("skill") or "")
        if skill and row_skill != skill:
            continue
        task = _trajectory_task_label(preview_source)
        trace_value = trace_row.get("trace_value")
        destinations = (trace_value or {}).get("destinations") or {}
        debug_score = float(destinations.get("debug_only") or 0)
        route_decisions = trace_row.get("route_decisions") or []
        is_debug = not task.strip() or float(((trace_value or {}).get("destinations") or {}).get("debug_only") or 0) >= 0.5
        if is_debug and not include_debug and trace_assessment_status != "debug_only":
            continue
        if needle and needle not in task.lower() and needle not in row_skill.lower():
            continue
        rows.append(_trajectory_preview(
            preview_source,
            trace_value=trace_value,
            route_decisions=route_decisions,
        ))
        if len(rows) >= limit:
            break
    return {"tenant_id": tenant_id, "count": len(rows), "trajectories": rows}


@router.get("/api/rl-capture/trajectories/{trajectory_id}")
async def rl_capture_trajectory_detail(trajectory_id: str, request: Request, tenant_id: str = TENANT_ID):
    """Return full drill-down detail for a single trajectory."""
    _principal, tenant_id, _agent_id, _user_id = require_scoped_identity(
        request,
        requested_tenant=tenant_id,
        action="read",
        resource_type="rl_capture",
        resource_id=trajectory_id,
    )
    store = _store_for_tenant(tenant_id)
    detail = store.trajectory_detail(trajectory_id)
    if not detail:
        raise HTTPException(status_code=404, detail=f"trajectory not found: {trajectory_id}")
    return {"tenant_id": tenant_id, **detail}


@router.get("/api/rl-capture/exports")
async def rl_capture_exports_list(request: Request, tenant_id: str = TENANT_ID, kind: Optional[str] = None, limit: int = 50):
    """List recorded export runs for the tenant."""
    _principal, tenant_id, _agent_id, _user_id = require_scoped_identity(
        request,
        requested_tenant=tenant_id,
        action="read",
        resource_type="rl_capture",
        resource_id="exports",
    )
    store = _store_for_tenant(tenant_id)
    return {
        "tenant_id": tenant_id,
        "exports": store.list_exports(kind=kind, limit=max(1, min(int(limit), 500))),
    }


@router.get("/api/rl-capture/exports/preview")
async def rl_capture_exports_preview(
    request: Request,
    tenant_id: str = TENANT_ID,
    format: str = "prompt_completion",
    eval_verdict: str = "",
    golden_set: str = "",
    trace_destination: str = "",
    trace_route_status: str = "approved",
    since: str = "",
    until: str = "",
    limit: int = 1000,
):
    """Return live export eligibility counts for the active UI filters."""
    _principal, tenant_id, _agent_id, _user_id = require_scoped_identity(
        request,
        requested_tenant=tenant_id,
        action="read",
        resource_type="rl_capture",
        resource_id="exports",
    )
    if format not in EXPORT_FORMATS:
        raise HTTPException(status_code=400, detail=f"format must be one of {sorted(EXPORT_FORMATS)}")
    store = _store_for_tenant(tenant_id)
    preview = preview_export_counts(
        store,
        limit=max(1, min(int(limit), 100_000)),
        format=format,
        eval_verdict=eval_verdict,
        since=since,
        until=until,
        include_trajectory_ids=_golden_trajectory_ids(tenant_id, golden_set),
        trace_destination=trace_destination,
        trace_route_status=trace_route_status,
    )
    return {
        "tenant_id": tenant_id,
        "filters": {
            "format": format,
            "eval_verdict": eval_verdict,
            "golden_set": golden_set,
            "trace_destination": trace_destination,
            "trace_route_status": trace_route_status if trace_destination else "",
            "since": since,
            "until": until,
        },
        **preview,
    }


@router.post("/api/rl-capture/exports")
async def rl_capture_export_create(req: RLExportRequest, request: Request):
    """Materialize an RL/eval dataset through the shared runner and record it."""
    _principal, tenant_id, _agent_id, _user_id = require_scoped_identity(
        request,
        requested_tenant=req.tenant_id,
        action="write",
        resource_type="rl_capture",
        resource_id=f"export:{req.kind}",
    )
    if req.kind not in EXPORT_KINDS:
        raise HTTPException(status_code=400, detail=f"kind must be one of {sorted(EXPORT_KINDS)}")
    if req.format not in EXPORT_FORMATS:
        raise HTTPException(status_code=400, detail=f"format must be one of {sorted(EXPORT_FORMATS)}")
    store = _store_for_tenant(tenant_id)
    output_dir = PROJECT_ROOT / "exports" / tenant_id
    output_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    output_path = output_dir / f"{req.kind}_{stamp}.jsonl"
    include_trajectory_ids = _golden_trajectory_ids(tenant_id, req.golden_set)
    try:
        result = run_export(
            store,
            kind=req.kind,
            output_path=output_path,
            tenant_id=tenant_id,
            limit=req.limit,
            format=req.format,
            eval_verdict=req.eval_verdict,
            golden_set=req.golden_set,
            since=req.since,
            until=req.until,
            include_trajectory_ids=include_trajectory_ids,
            trace_destination=req.trace_destination,
            trace_route_status=req.trace_route_status,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001 - surface quality failures cleanly
        logger.exception("Export failed")
        raise HTTPException(status_code=422, detail="Export failed") from exc
    return {"tenant_id": tenant_id, "export": result.to_dict()}


@router.post("/api/rl-capture/evaluate")
async def rl_capture_evaluate(req: RLEvaluateRequest, request: Request):
    """Score trajectories and persist evaluator-channel judgement rewards.

    mode=rule  → deterministic heuristic (no model calls).
    mode=llm   → invokes the ``trajectory_judge`` skill per trajectory.
    """
    from rl_capture.core.auto_evaluator import evaluate_trajectories

    _principal, tenant_id, agent_id, _user_id = require_scoped_identity(
        request,
        requested_tenant=req.tenant_id,
        requested_agent=req.agent_id,
        action="use",
        resource_type="rl_capture",
        resource_id="evaluate",
    )
    if req.mode not in ("rule", "llm"):
        raise HTTPException(status_code=400, detail="mode must be 'rule' or 'llm'")
    store = _store_for_tenant(tenant_id)

    judge_fn = None
    if req.mode == "llm":
        judge_fn = _build_llm_judge(request, req)

    try:
        summary = await asyncio.to_thread(
            evaluate_trajectories,
            store,
            tenant_id=tenant_id,
            agent_id=agent_id,
            limit=req.limit,
            overwrite=req.overwrite,
            trajectory_id=req.trajectory_id,
            judge_fn=judge_fn,
        )
    except Exception as exc:  # noqa: BLE001 - surface judge/store failures cleanly
        logger.exception("RL capture evaluation failed")
        raise HTTPException(status_code=422, detail="Evaluation failed") from exc
    summary["mode"] = req.mode
    summary["tenant_id"] = tenant_id
    return summary


def _build_llm_judge(request: Request, req: RLEvaluateRequest):
    """Build a judge_fn that grades a trajectory via the trajectory_judge skill."""
    from shared.state import state
    from security.dependencies import bind_request_identity, make_agent_entitlement_checker
    from rl_capture.core.auto_evaluator import build_judge_prompt, parse_judge_response

    principal, tenant_id, agent_id, user_id = bind_request_identity(
        request,
        requested_tenant=req.tenant_id,
        requested_agent=req.agent_id,
        requested_user="rl_evaluator",
    )
    user_role = principal.roles[0] if principal.roles else "admin"
    agent = state.get_or_create(tenant_id, agent_id, user_id, user_role=user_role)
    agent.set_entitlement_context(principal, make_agent_entitlement_checker(principal))
    agent.auto_run = True

    def judge(detail: dict) -> dict:
        prompt = build_judge_prompt(detail)
        # skip_memory: a background judge must not be recorded into the live session it was handed.
        response = agent.run(prompt, skill_name=req.judge_skill, light_mode=True, skip_memory=True)
        text = response if isinstance(response, str) else (
            response.get("response") if isinstance(response, dict) else str(response)
        )
        return parse_judge_response(text)

    return judge


@router.get("/api/rl-capture/exports/{export_id}/download")
async def rl_capture_export_download(export_id: str, request: Request, tenant_id: str = TENANT_ID):
    """Stream the JSONL artifact for a recorded export."""
    _principal, tenant_id, _agent_id, _user_id = require_scoped_identity(
        request,
        requested_tenant=tenant_id,
        action="read",
        resource_type="rl_capture",
        resource_id=f"export:{export_id}",
    )
    store = _store_for_tenant(tenant_id)
    exports = store.list_exports(limit=500)
    match = next((row for row in exports if row.get("id") == export_id), None)
    if not match:
        raise HTTPException(status_code=404, detail=f"export not found: {export_id}")
    file_path = Path(str(match.get("file_path") or ""))
    if not file_path.exists():
        raise HTTPException(status_code=410, detail="export file no longer exists on disk")
    return FileResponse(
        path=str(file_path),
        media_type="application/x-jsonlines",
        filename=file_path.name,
    )


def _store_for_tenant(tenant_id: str):
    return get_rl_store(
        data_root=DATA_ROOT_PATH,
        tenant_id=tenant_id,
        db_path=RL_DB_PATH.strip() or None,
    )


def _store_db_path(tenant_id: str) -> str:
    return str(_store_for_tenant(tenant_id).db_path)


def _golden_trajectory_ids(tenant_id: str, golden_set: str) -> list[str] | None:
    if not golden_set:
        return None
    try:
        from shared import evals_service

        golden = evals_service.get_golden_set(golden_set, tenant_id)
    except Exception:
        return []
    ids: list[str] = []
    for case in golden.get("cases") or []:
        inputs = case.get("inputs") if isinstance(case.get("inputs"), dict) else {}
        metadata = case.get("metadata") if isinstance(case.get("metadata"), dict) else {}
        trajectory_id = str(inputs.get("trajectory_id") or metadata.get("trajectory_id") or "")
        if trajectory_id:
            ids.append(trajectory_id)
    return ids


def _trajectory_preview(
    row: dict,
    *,
    trace_value: dict | None = None,
    route_decisions: list[dict] | None = None,
) -> dict:
    metadata = row.get("metadata") or {}
    capture = row.get("capture") or {}
    destinations = (trace_value or {}).get("destinations") or {}
    ranked_destinations = sorted(
        (
            {"destination": str(key), "score": float(value or 0)}
            for key, value in destinations.items()
        ),
        key=lambda item: item["score"],
        reverse=True,
    )
    decisions = route_decisions or []
    latest_decision = decisions[0] if decisions else None
    return {
        "id": row.get("id"),
        "session_id": row.get("session_id"),
        "task": _trajectory_task_label(row)[:260],
        "fidelity": row.get("fidelity"),
        "terminal_status": row.get("terminal_status"),
        "capture_time": capture.get("capture_time"),
        "started_at": row.get("started_at"),
        "ended_at": row.get("ended_at"),
        "skill": metadata.get("skill"),
        "transport": metadata.get("transport"),
        "user_id": metadata.get("user_id"),
        "model_calls": len(row.get("model_calls") or []),
        "tool_calls": len(row.get("tool_calls") or []),
        "observations": len(row.get("observations") or []),
        "trace_value": {
            "assessment_id": (trace_value or {}).get("id"),
            "assessment_status": (
                "debug_only"
                if float(destinations.get("debug_only") or 0) >= 0.5
                else ("assessed" if trace_value else "unassessed")
            ),
            "quality_verdict": ((trace_value or {}).get("quality") or {}).get("verdict"),
            "top_destination": ranked_destinations[0]["destination"] if ranked_destinations else None,
            "top_score": ranked_destinations[0]["score"] if ranked_destinations else 0.0,
            "destinations": destinations,
            "route_status": (latest_decision or {}).get("status"),
            "route_destination": (latest_decision or {}).get("destination"),
            "route_decision_count": len(decisions),
        },
    }


def _hydrate_sparse_trajectory(store: Any, trajectory: dict) -> dict:
    if _trajectory_task_label(trajectory) and any(trajectory.get(key) for key in ("model_calls", "tool_calls", "observations")):
        return trajectory
    trajectory_id = str(trajectory.get("id") or "")
    if not trajectory_id:
        return trajectory
    try:
        detail = store.trajectory_detail(trajectory_id)
    except Exception:
        return trajectory
    hydrated = (detail or {}).get("trajectory") or {}
    return hydrated or trajectory


def _trajectory_task_label(row: dict) -> str:
    task = str(row.get("task") or "").strip()
    if task:
        return task
    fallback = ""
    for model_call in row.get("model_calls") or []:
        for message in model_call.get("input_messages") or []:
            content = _clean_task_label(message.get("content"))
            if not content:
                continue
            role = str(message.get("role") or "").lower()
            if role == "user":
                return content
            if not fallback and role not in {"system", "tool"}:
                fallback = content
    if fallback:
        return fallback
    metadata = row.get("metadata") or {}
    outcome = metadata.get("outcome") if isinstance(metadata.get("outcome"), dict) else {}
    for key in ("query", "input", "task", "message", "content"):
        content = _clean_task_label(outcome.get(key) or metadata.get(key))
        if content:
            return content
    return ""


def _clean_task_label(value: Any) -> str:
    content = str(value or "").strip()
    if not content:
        return ""
    if content.startswith(("('user',", '("user",')):
        try:
            parsed = ast.literal_eval(content)
        except (SyntaxError, ValueError):
            parsed = None
        if isinstance(parsed, (list, tuple)) and len(parsed) >= 2:
            return str(parsed[1] or "").strip()
    return content


def _reward_preview(row: dict) -> dict:
    target = row.get("target") or {}
    return {
        "id": row.get("id"),
        "channel": row.get("channel"),
        "category": classify_channel(row.get("channel")),
        "is_judgement": is_judgement_channel(row.get("channel")),
        "raw_label": row.get("raw_label"),
        "judge_id": row.get("judge_id"),
        "created_at": row.get("created_at"),
        "target_type": target.get("target_type"),
        "target_id": target.get("target_id"),
        "trajectory_id": target.get("trajectory_id"),
        "metadata": row.get("metadata") or {},
    }


def _preference_preview(row: dict) -> dict:
    return {
        "id": row.get("id"),
        "channel": row.get("channel"),
        "provenance": row.get("provenance"),
        "judge_id": row.get("judge_id"),
        "created_at": row.get("created_at"),
        "metadata": row.get("metadata") or {},
    }
