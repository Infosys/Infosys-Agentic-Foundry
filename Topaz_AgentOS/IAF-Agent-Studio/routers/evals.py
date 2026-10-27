"""Private Learning Loop eval registry API."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from shared.eval_dashboard_store import dashboard_summary
from shared import evals_service as service
from shared.config import AGENT_ID, TENANT_ID
from security.dependencies import enforce_entitlement, principal_from_request

router = APIRouter()


class EvalSuiteDefinition(BaseModel):
    id: str = Field(..., min_length=1)
    name: str = ""
    description: str = ""
    enabled: bool = True
    target: dict[str, Any] = Field(default_factory=dict)
    golden_set: str = ""
    rubric: dict[str, Any] = Field(default_factory=dict)
    assertions: list[dict[str, Any]] = Field(default_factory=list)
    thresholds: dict[str, Any] = Field(default_factory=dict)
    judge: dict[str, Any] = Field(default_factory=dict)
    evaluator: dict[str, Any] = Field(default_factory=dict)
    tags: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class GoldenSetRequest(BaseModel):
    cases: list[dict[str, Any]] = Field(default_factory=list)


class PromoteTrajectoryRequest(BaseModel):
    trajectory_id: str = Field(..., min_length=1)
    tenant_id: str = TENANT_ID
    case_id: str = ""
    expected: Any = None
    assertions: list[dict[str, Any]] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class EvalRunRequest(BaseModel):
    tenant_id: str = TENANT_ID
    agent_id: str = AGENT_ID
    user_id: str = "eval_runner"
    trigger: str = "manual"
    metadata: dict[str, Any] = Field(default_factory=dict)


class EvaluatorTestRequest(BaseModel):
    tenant_id: str = TENANT_ID
    payload: dict[str, Any] = Field(default_factory=dict)
    config: dict[str, Any] = Field(default_factory=dict)


class GateDecisionRequest(BaseModel):
    tenant_id: str = TENANT_ID
    run_id: str = Field(..., min_length=1)
    decision: str = Field(..., min_length=1)
    reviewer: str = ""
    reason: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)


@router.get("/api/evals")
async def list_eval_suites(tenant_id: str = TENANT_ID):
    suites = service.list_eval_suites(tenant_id)
    return {"evals": suites, "total": len(suites)}


@router.post("/api/evals")
async def save_eval_suite(request: Request, definition: EvalSuiteDefinition, tenant_id: str = TENANT_ID):
    try:
        payload = definition.model_dump() if hasattr(definition, "model_dump") else definition.dict()
        principal = principal_from_request(request, tenant_id)
        enforce_entitlement(principal, "write", "eval", payload.get("id") or "*")
        saved = service.save_eval_suite(payload, tenant_id)
        return {"message": f"Saved eval suite '{saved['id']}'", "eval": saved}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/api/evals/validate")
async def validate_eval_suite(request: Request, definition: EvalSuiteDefinition, tenant_id: str = TENANT_ID):
    try:
        payload = definition.model_dump() if hasattr(definition, "model_dump") else definition.dict()
        principal = principal_from_request(request, tenant_id)
        enforce_entitlement(principal, "write", "eval", payload.get("id") or "*")
        return service.validate_eval_suite(payload, tenant_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/api/evals/golden/{set_id}")
async def get_golden_set(set_id: str, tenant_id: str = TENANT_ID):
    try:
        return service.get_golden_set(set_id, tenant_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/api/evals/golden/{set_id}")
async def save_golden_set(set_id: str, body: GoldenSetRequest, request: Request, tenant_id: str = TENANT_ID):
    try:
        principal = principal_from_request(request, tenant_id)
        enforce_entitlement(principal, "write", "eval", f"golden/{set_id}")
        return service.save_golden_set(set_id, body.cases, tenant_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/api/evals/golden/{set_id}/promote")
async def promote_trajectory_to_golden(set_id: str, body: PromoteTrajectoryRequest, request: Request):
    try:
        principal = principal_from_request(request, body.tenant_id)
        enforce_entitlement(principal, "write", "eval", f"golden/{set_id}")
        return service.promote_trajectory_to_golden(
            set_id,
            trajectory_id=body.trajectory_id,
            tenant_id=body.tenant_id,
            case_id=body.case_id,
            expected=body.expected,
            assertions=body.assertions,
            tags=body.tags,
            metadata=body.metadata,
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/api/evals/dashboard/summary")
async def get_eval_dashboard_summary(tenant_id: str = TENANT_ID, limit: int = 10):
    return dashboard_summary(tenant_id, limit=limit)


@router.get("/api/evals/recommendations")
async def get_eval_model_recommendations(
    tenant_id: str = TENANT_ID,
    role: str = "primary",
    limit: int = 50,
):
    return service.model_recommendations(tenant_id=tenant_id, role=role, limit=limit)


@router.get("/api/evals/evaluators")
async def list_eval_evaluators(tenant_id: str = TENANT_ID):
    evaluators = service.list_eval_evaluators(tenant_id)
    return {"evaluators": evaluators, "total": len(evaluators)}


@router.get("/api/evals/evaluators/{evaluator_id}")
async def get_eval_evaluator(evaluator_id: str, tenant_id: str = TENANT_ID):
    try:
        return service.get_eval_evaluator(evaluator_id, tenant_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/api/evals/evaluators/{evaluator_id}/test")
async def test_eval_evaluator(evaluator_id: str, body: EvaluatorTestRequest, request: Request):
    try:
        principal = principal_from_request(request, body.tenant_id)
        enforce_entitlement(principal, "test", "eval", f"evaluator/{evaluator_id}")
        return service.test_eval_evaluator(
            evaluator_id,
            tenant_id=body.tenant_id,
            payload=body.payload or None,
            config=body.config,
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/api/evals/runs/{run_id}")
async def get_eval_run(run_id: str, tenant_id: str = TENANT_ID):
    try:
        return service.get_run(run_id, tenant_id=tenant_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/api/evals/{suite_id}/run")
async def run_eval_suite(suite_id: str, body: EvalRunRequest, request: Request):
    try:
        principal = principal_from_request(request, body.tenant_id)
        enforce_entitlement(principal, "use", "eval", suite_id)
        suite = service.get_eval_suite(suite_id, body.tenant_id)
        target = suite.get("target") or {}
        if str(target.get("type") or "") == "skill":
            enforce_entitlement(principal, "use", "skill", str(target.get("name") or ""))
        return service.run_eval_suite(
            suite_id,
            tenant_id=body.tenant_id,
            agent_id=body.agent_id,
            user_id=body.user_id,
            trigger=body.trigger,
            metadata=body.metadata,
            principal=principal,
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/api/evals/{suite_id}/runs")
async def list_eval_runs(suite_id: str, tenant_id: str = TENANT_ID, limit: int = 25):
    try:
        service.get_eval_suite(suite_id, tenant_id)
        runs = service.list_runs(suite_id=suite_id, tenant_id=tenant_id, limit=limit)
        return {"runs": runs, "total": len(runs)}
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/api/evals/{suite_id}/gates")
async def list_gate_decisions(suite_id: str, tenant_id: str = TENANT_ID, limit: int = 25):
    try:
        service.get_eval_suite(suite_id, tenant_id)
        gates = service.list_gate_decisions(suite_id=suite_id, tenant_id=tenant_id, limit=limit)
        return {"gates": gates, "total": len(gates)}
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/api/evals/{suite_id}/gates")
async def record_gate_decision(suite_id: str, body: GateDecisionRequest, request: Request):
    try:
        principal = principal_from_request(request, body.tenant_id)
        enforce_entitlement(principal, "approve", "eval", suite_id)
        reviewer = body.reviewer or principal.email or principal.user_id
        gate = service.record_gate_decision(
            suite_id,
            run_id=body.run_id,
            decision=body.decision,
            tenant_id=body.tenant_id,
            reviewer=reviewer,
            reason=body.reason,
            metadata=body.metadata,
        )
        return {"gate": gate}
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/api/evals/{suite_id}")
async def get_eval_suite(suite_id: str, tenant_id: str = TENANT_ID):
    try:
        return service.get_eval_suite(suite_id, tenant_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.delete("/api/evals/{suite_id}")
async def delete_eval_suite(suite_id: str, request: Request, tenant_id: str = TENANT_ID):
    try:
        principal = principal_from_request(request, tenant_id)
        enforce_entitlement(principal, "delete", "eval", suite_id)
        service.delete_eval_suite(suite_id, tenant_id)
        return {"message": f"Deleted eval suite '{suite_id}'"}
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
