"""Trace Value Router API."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from shared.config import AGENT_ID, TENANT_ID, TRACE_VALUE_ROUTER_BATCH_LIMIT
from shared import trace_value_service as service
from shared import trace_value_promotion_service as promotion_service
from security.dependencies import enforce_entitlement, principal_from_request


logger = logging.getLogger(__name__)
router = APIRouter()


class TraceValueEvaluateRequest(BaseModel):
    tenant_id: str = TENANT_ID
    agent_id: str = AGENT_ID
    user_id: str = "trace_value_router"
    trajectory_id: str = ""
    limit: int = TRACE_VALUE_ROUTER_BATCH_LIMIT
    force: bool = False


class TraceValuePromotionRequest(BaseModel):
    tenant_id: str = TENANT_ID
    agent_id: str = AGENT_ID
    items: list[dict[str, Any]] = Field(default_factory=list)


@router.get("/api/trace-value/summary")
async def trace_value_summary(request: Request, tenant_id: str = TENANT_ID, limit: int = 25):
    principal = principal_from_request(request, tenant_id)
    enforce_entitlement(principal, "read", "trace_value", "summary")
    return service.summary(tenant_id, limit=max(1, min(int(limit), 100)))


@router.get("/api/trace-value/assessments")
async def trace_value_assessments(
    request: Request,
    tenant_id: str = TENANT_ID,
    destination: str = "",
    verdict: str = "",
    include_debug: bool = False,
    limit: int = 100,
):
    principal = principal_from_request(request, tenant_id)
    enforce_entitlement(principal, "read", "trace_value", "assessments")
    return service.list_assessments(
        tenant_id,
        destination=destination,
        verdict=verdict,
        include_debug=include_debug,
        limit=max(1, min(int(limit), 500)),
    )


@router.get("/api/trace-value/assessments/{trajectory_id}")
async def trace_value_assessment(trajectory_id: str, request: Request, tenant_id: str = TENANT_ID):
    principal = principal_from_request(request, tenant_id)
    enforce_entitlement(principal, "read", "trace_value", trajectory_id)
    assessment = service.get_assessment(trajectory_id, tenant_id)
    if not assessment:
        raise HTTPException(status_code=404, detail=f"assessment not found: {trajectory_id}")
    return {"tenant_id": tenant_id, "assessment": assessment}


@router.post("/api/trace-value/evaluate")
async def trace_value_evaluate(body: TraceValueEvaluateRequest, request: Request):
    principal = principal_from_request(request, body.tenant_id)
    enforce_entitlement(principal, "use", "trace_value", "evaluate")
    enforce_entitlement(principal, "use", "skill", "trace_value_router")
    try:
        return await service.evaluate_batch_async(
            tenant_id=body.tenant_id,
            agent_id=body.agent_id,
            user_id=body.user_id,
            limit=body.limit,
            force=body.force,
            trajectory_id=body.trajectory_id,
            principal=principal,
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001 - surface judge/store errors cleanly
        logger.exception("Trace value evaluation failed")
        raise HTTPException(status_code=422, detail="Trace value evaluation failed") from exc


@router.post("/api/trace-value/promote")
async def trace_value_promote(body: TraceValuePromotionRequest, request: Request):
    principal = principal_from_request(request, body.tenant_id)
    enforce_entitlement(principal, "promote", "trace_value", "bulk")
    for item in body.items:
        destination = str(item.get("destination") or "*")
        if destination == "golden_eval":
            enforce_entitlement(principal, "write", "eval", f"golden/{item.get('golden_set') or '*'}")
        elif destination in {"skill", "context", "memory"}:
            enforce_entitlement(principal, "write", "knowledge", destination)
        elif destination == "model_training":
            enforce_entitlement(principal, "write", "trace_value", "model_training")
    reviewer = principal.email or principal.user_id
    return promotion_service.promote(
        tenant_id=body.tenant_id,
        agent_id=body.agent_id,
        reviewer=reviewer,
        items=body.items,
    )
