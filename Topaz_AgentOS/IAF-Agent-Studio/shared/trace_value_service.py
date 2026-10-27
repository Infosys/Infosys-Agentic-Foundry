"""Trace Value Router orchestration service.

This module is deliberately outside FastAPI routers: it owns trajectory
assessment orchestration, while routers only bind identity/entitlements.
"""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from rl_capture.core.schema import CaptureMeta, TraceValueAssessment
from rl_capture.core.trace_value import (
    RUBRIC_VERSION,
    build_evidence_packet,
    debug_assessment,
    eligibility,
    input_hash,
    parse_assessment_response,
)
from rl_capture.store.sqlite_store import get_rl_store
from shared.config import (
    AGENT_ID,
    DATA_ROOT_PATH,
    RL_DB_PATH,
    TENANT_ID,
    TRACE_VALUE_ROUTER_BATCH_LIMIT,
    TRACE_VALUE_ROUTER_CONCURRENCY,
    TRACE_VALUE_ROUTER_ENABLED,
    TRACE_VALUE_ROUTER_MAX_EVIDENCE_CHARS,
    TRACE_VALUE_ROUTER_RETRY_LIMIT,
    TRACE_VALUE_ROUTER_SKILL,
)

logger = logging.getLogger("iaf_server.trace_value")


_inflight: set[str] = set()


def store_for_tenant(tenant_id: str = TENANT_ID):
    return get_rl_store(data_root=DATA_ROOT_PATH, tenant_id=tenant_id, db_path=RL_DB_PATH.strip() or None)


def summary(tenant_id: str = TENANT_ID, *, limit: int = 25) -> dict[str, Any]:
    store = store_for_tenant(tenant_id)
    base = store.trace_value_summary()
    queues: dict[str, list[dict[str, Any]]] = {}
    for destination in ("skill", "context", "memory", "golden_eval", "model_training", "debug_only"):
        rows = store.list_trace_value_assessments(
            destination=destination,
            include_debug=destination == "debug_only",
            limit=limit,
        )
        for row in rows:
            decisions = store.list_trace_route_decisions(
                trajectory_id=str(row.get("trajectory_id") or ""),
                destination=destination,
                limit=1,
            )
            row["route_destination"] = destination
            row["route_status"] = (decisions[0] if decisions else {}).get("status")
        queues[destination] = rows
    return {"tenant_id": tenant_id, **base, "queues": queues}


def list_assessments(
    tenant_id: str = TENANT_ID,
    *,
    destination: str = "",
    verdict: str = "",
    include_debug: bool = False,
    limit: int = 100,
) -> dict[str, Any]:
    rows = store_for_tenant(tenant_id).list_trace_value_assessments(
        destination=destination or None,
        verdict=verdict or None,
        include_debug=include_debug,
        limit=limit,
    )
    return {"tenant_id": tenant_id, "assessments": rows, "total": len(rows)}


def get_assessment(trajectory_id: str, tenant_id: str = TENANT_ID) -> dict[str, Any] | None:
    return store_for_tenant(tenant_id).latest_trace_value_assessment(trajectory_id)


def evaluate_trajectory(
    trajectory_id: str,
    *,
    tenant_id: str = TENANT_ID,
    agent_id: str = AGENT_ID,
    user_id: str = "trace_value_router",
    judge_skill: str = TRACE_VALUE_ROUTER_SKILL,
    force: bool = False,
    principal: Any = None,
) -> dict[str, Any]:
    store = store_for_tenant(tenant_id)
    detail = store.trajectory_detail(trajectory_id)
    if not detail:
        raise FileNotFoundError(f"trajectory not found: {trajectory_id}")
    packet = build_evidence_packet(detail, max_chars=TRACE_VALUE_ROUTER_MAX_EVIDENCE_CHARS)
    packet_hash = input_hash(packet)
    latest = store.latest_trace_value_assessment(trajectory_id)
    if latest and latest.get("input_hash") == packet_hash and not force:
        return {"status": "skipped", "reason": "unchanged", "assessment": latest}

    gate = eligibility(detail)
    if not gate["eligible"]:
        assessment = debug_assessment(detail, packet_hash=packet_hash, reasons=gate["reasons"])
    else:
        response_text = _run_router_skill(
            packet,
            tenant_id=tenant_id,
            agent_id=agent_id,
            user_id=user_id,
            judge_skill=judge_skill,
            principal=principal,
        )
        parsed = parse_assessment_response(response_text, trajectory_id=trajectory_id, packet_hash=packet_hash)
        assessment = parsed
    now = datetime.now(timezone.utc).isoformat()
    assessment.setdefault("created_at", now)
    assessment.setdefault("capture", CaptureMeta(
        adapter_version="agentpro:trace_value",
        tenant_id=tenant_id,
        agent_id=agent_id,
        source_event_id=trajectory_id,
        source_trace_id=trajectory_id,
        capture_time=now,
    ))
    store.record_trace_value_assessment(TraceValueAssessment(**assessment))
    return {"status": "evaluated", "assessment": store.latest_trace_value_assessment(trajectory_id)}


def evaluate_batch(
    *,
    tenant_id: str = TENANT_ID,
    agent_id: str = AGENT_ID,
    user_id: str = "trace_value_router",
    limit: int = TRACE_VALUE_ROUTER_BATCH_LIMIT,
    force: bool = False,
    trajectory_id: str = "",
    principal: Any = None,
) -> dict[str, Any]:
    store = store_for_tenant(tenant_id)
    if trajectory_id:
        candidates = [{"id": trajectory_id}]
    elif force:
        candidates = store.list_trajectories(limit=limit, tenant_id=tenant_id, agent_id=agent_id)
    else:
        candidates = store.list_unassessed_trajectories(limit=limit)
    results: list[dict[str, Any]] = []
    errors = 0
    for row in candidates[: max(1, int(limit))]:
        tid = str(row.get("id") or "")
        if not tid:
            continue
        try:
            results.append(evaluate_trajectory(
                tid,
                tenant_id=tenant_id,
                agent_id=agent_id,
                user_id=user_id,
                force=force or bool(trajectory_id),
                principal=principal,
            ))
        except Exception as exc:  # noqa: BLE001 - batch should report per-row failures
            errors += 1
            results.append({"status": "error", "trajectory_id": tid, "error": str(exc)})
    return {
        "tenant_id": tenant_id,
        "evaluated": sum(1 for row in results if row.get("status") == "evaluated"),
        "skipped": sum(1 for row in results if row.get("status") == "skipped"),
        "errors": errors,
        "results": results,
    }


async def evaluate_batch_async(
    *,
    tenant_id: str = TENANT_ID,
    agent_id: str = AGENT_ID,
    user_id: str = "trace_value_router",
    limit: int = TRACE_VALUE_ROUTER_BATCH_LIMIT,
    force: bool = False,
    trajectory_id: str = "",
    principal: Any = None,
) -> dict[str, Any]:
    """Bounded-async batch evaluation for startup reconciliation and API callers."""
    store = store_for_tenant(tenant_id)
    if trajectory_id:
        candidates = [{"id": trajectory_id}]
    elif force:
        candidates = store.list_trajectories(limit=limit, tenant_id=tenant_id, agent_id=agent_id)
    else:
        candidates = store.list_unassessed_trajectories(limit=limit)
    candidate_ids = [str(row.get("id") or "") for row in candidates[: max(1, int(limit))]]
    candidate_ids = [tid for tid in candidate_ids if tid]
    if not candidate_ids:
        return {
            "tenant_id": tenant_id,
            "evaluated": 0,
            "skipped": 0,
            "errors": 0,
            "results": [],
        }

    semaphore = asyncio.Semaphore(TRACE_VALUE_ROUTER_CONCURRENCY)

    async def _evaluate_one(tid: str) -> dict[str, Any]:
        async with semaphore:
            try:
                return await asyncio.to_thread(
                    evaluate_trajectory,
                    tid,
                    tenant_id=tenant_id,
                    agent_id=agent_id,
                    user_id=user_id,
                    force=force or bool(trajectory_id),
                    principal=principal,
                )
            except Exception as exc:  # noqa: BLE001 - batch should report per-row failures
                logger.warning("Trace value evaluation failed for %s: %s", tid, exc, exc_info=True)
                return {"status": "error", "trajectory_id": tid, "error": "evaluation failed"}

    results = await asyncio.gather(*(_evaluate_one(tid) for tid in candidate_ids))
    errors = sum(1 for row in results if row.get("status") == "error")
    return {
        "tenant_id": tenant_id,
        "evaluated": sum(1 for row in results if row.get("status") == "evaluated"),
        "skipped": sum(1 for row in results if row.get("status") == "skipped"),
        "errors": errors,
        "results": list(results),
    }


def schedule_assessment_after_capture(
    *,
    tenant_id: str,
    agent_id: str,
    user_id: str,
    trajectory_id: str,
) -> None:
    """Best-effort async trigger after chat capture; never blocks runtime."""
    if not TRACE_VALUE_ROUTER_ENABLED or not trajectory_id:
        return
    key = f"{tenant_id}:{trajectory_id}"
    if key in _inflight:
        return
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return
    _inflight.add(key)
    loop.create_task(_assess_background(
        tenant_id=tenant_id,
        agent_id=agent_id,
        user_id=user_id,
        trajectory_id=trajectory_id,
        key=key,
    ))


async def _assess_background(*, tenant_id: str, agent_id: str, user_id: str, trajectory_id: str, key: str) -> None:
    try:
        attempts = TRACE_VALUE_ROUTER_RETRY_LIMIT + 1
        for attempt in range(attempts):
            try:
                await asyncio.to_thread(
                    evaluate_trajectory,
                    trajectory_id,
                    tenant_id=tenant_id,
                    agent_id=agent_id,
                    user_id=user_id,
                )
                return
            except Exception as exc:  # noqa: BLE001 - logged and retried best-effort
                if attempt >= attempts - 1:
                    logger.warning("Trace value assessment failed for %s: %s", trajectory_id, exc)
                else:
                    await asyncio.sleep(1 + attempt)
    finally:
        _inflight.discard(key)


def _run_router_skill(
    packet: dict[str, Any],
    *,
    tenant_id: str,
    agent_id: str,
    user_id: str,
    judge_skill: str,
    principal: Any = None,
) -> str:
    from shared.state import state

    user_role = "admin"
    if principal is not None:
        roles = getattr(principal, "roles", ()) or ()
        user_role = roles[0] if roles else "user"
    agent = state.get_or_create(tenant_id, agent_id, user_id, user_role=user_role)
    if principal is not None:
        try:
            from security.dependencies import make_agent_entitlement_checker

            agent.set_entitlement_context(principal, make_agent_entitlement_checker(principal))
        except Exception:
            logger.debug("Trace value entitlement context could not be set", exc_info=True)
    agent.auto_run = True
    prompt = (
        "Evaluate this captured trajectory for learning destination routing. "
        "Return strict JSON only using the schema in the trace_value_router skill.\n\n"
        f"TRACE_PACKET:\n{json.dumps(packet, ensure_ascii=False, default=str)}"
    )
    # light_mode skips heavy memory/context; swap to the light model role for the judge call.
    _orig_llm = agent.llm
    light_llm = getattr(agent, "light_llm", None)
    try:
        if light_llm is not None:
            deployment = (
                getattr(light_llm, "azure_deployment", "")
                or getattr(light_llm, "model_name", "")
                or "light"
            )
            agent.llm = agent._policy_wrap_llm(light_llm, role="light")
            agent.agent = None
            logger.info("Trace value router using light model: %s", deployment)
        # skip_memory: a background judge must not be recorded into the agent's conversation.
        response = agent.run(prompt, skill_name=judge_skill, light_mode=True, skip_memory=True)
    finally:
        agent.llm = _orig_llm
        agent.agent = None
    return response if isinstance(response, str) else str(response.get("response") if isinstance(response, dict) else response)


def record_route_decision(
    *,
    tenant_id: str,
    trajectory_id: str,
    destination: str,
    action: str,
    status: str,
    reviewer: str,
    target_ref: str = "",
    reason: str = "",
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    store = store_for_tenant(tenant_id)
    assessment = store.latest_trace_value_assessment(trajectory_id)
    now = datetime.now(timezone.utc).isoformat()
    decision = {
        "id": f"tvr_{uuid.uuid4().hex[:16]}",
        "trajectory_id": trajectory_id,
        "assessment_id": (assessment or {}).get("id"),
        "destination": destination,
        "action": action,
        "status": status,
        "reviewer": reviewer,
        "target_ref": target_ref,
        "reason": reason,
        "created_at": now,
        "capture": CaptureMeta(
            adapter_version="agentpro:trace_value",
            tenant_id=tenant_id,
            source_event_id=trajectory_id,
            source_trace_id=trajectory_id,
            capture_time=now,
        ),
        "metadata": metadata or {},
    }
    store.record_trace_route_decision(decision)
    return decision
