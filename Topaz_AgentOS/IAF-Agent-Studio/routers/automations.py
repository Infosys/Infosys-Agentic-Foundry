"""Deterministic Automation API.

Automations are no-LLM pipelines stored as YAML under enterprise_root.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from shared import automations_service as service
from shared.config import AGENT_ID, TENANT_ID

router = APIRouter()


class AutomationDefinition(BaseModel):
    id: str = Field(..., min_length=1)
    name: str = ""
    description: str = ""
    enabled: bool = True
    steps: list[dict[str, Any]] = Field(default_factory=list)


class AutomationRunRequest(BaseModel):
    tenant_id: str = TENANT_ID
    agent_id: str = AGENT_ID
    user_id: str = "automation"
    trigger: str = "manual"
    input: str = ""
    context: dict[str, Any] = Field(default_factory=dict)


@router.get("/api/automations")
async def list_automations(tenant_id: str = TENANT_ID):
    automations = service.list_automations(tenant_id)
    return {
        "automations": automations,
        "total": len(automations),
    }


@router.get("/api/automations/runs/{run_id}")
async def get_automation_run(run_id: str):
    try:
        return service.get_run(run_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/api/automations/{automation_id}")
async def get_automation(automation_id: str, tenant_id: str = TENANT_ID):
    try:
        return service.get_automation(automation_id, tenant_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/api/automations")
async def save_automation(definition: AutomationDefinition, tenant_id: str = TENANT_ID):
    try:
        payload = definition.model_dump() if hasattr(definition, "model_dump") else definition.dict()
        saved = service.save_automation(payload, tenant_id)
        return {"message": f"Saved automation '{saved['id']}'", "automation": saved}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.delete("/api/automations/{automation_id}")
async def delete_automation(automation_id: str, tenant_id: str = TENANT_ID):
    try:
        service.delete_automation(automation_id, tenant_id)
        return {"message": f"Deleted automation '{automation_id}'"}
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/api/automations/{automation_id}/run")
async def run_automation(automation_id: str, request: AutomationRunRequest):
    try:
        return service.run_automation(
            automation_id,
            tenant_id=request.tenant_id,
            agent_id=request.agent_id,
            user_id=request.user_id,
            trigger=request.trigger,
            input_text=request.input,
            context=request.context,
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/api/automations/{automation_id}/runs")
async def list_automation_runs(
    automation_id: str,
    tenant_id: str = TENANT_ID,
    limit: int = 25,
):
    try:
        service.get_automation(automation_id, tenant_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    runs = service.list_runs(automation_id=automation_id, limit=limit)
    return {"runs": runs, "total": len(runs)}
