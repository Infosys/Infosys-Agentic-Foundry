"""Admin APIs for deterministic enterprise recovery verification."""

from __future__ import annotations

import asyncio
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from auth.middleware import require_admin
from security.dependencies import require_scoped_identity
from shared import recovery_readiness_service as recovery_service
from shared.config import TENANT_ID


router = APIRouter(prefix="/api/recovery-readiness", tags=["recovery-readiness"])


class VerifyRecoveryRequest(BaseModel):
    tenant_id: str = TENANT_ID
    root_id: str
    evidence_id: str | None = None


class DrillEvidenceRequest(BaseModel):
    tenant_id: str = TENANT_ID
    root_id: str
    evidence: dict[str, Any]


def _scope(request: Request, tenant_id: str, action: str, resource_id: str):
    return require_scoped_identity(
        request,
        requested_tenant=tenant_id,
        action=action,
        resource_type="recovery",
        resource_id=resource_id,
    )


@router.get("/summary")
async def recovery_summary(
    request: Request,
    tenant_id: str = TENANT_ID,
    _admin: dict = Depends(require_admin),
):
    _principal, tenant_id, _agent_id, _user_id = _scope(
        request, tenant_id, "read", "summary"
    )
    return recovery_service.summary(tenant_id)


@router.get("/roots")
async def recovery_roots(
    request: Request,
    tenant_id: str = TENANT_ID,
    _admin: dict = Depends(require_admin),
):
    _principal, tenant_id, _agent_id, _user_id = _scope(
        request, tenant_id, "read", "roots"
    )
    return {"tenant_id": tenant_id, "roots": recovery_service.roots()}


@router.get("/reports")
async def recovery_reports(
    request: Request,
    tenant_id: str = TENANT_ID,
    limit: int = 50,
    _admin: dict = Depends(require_admin),
):
    _principal, tenant_id, _agent_id, _user_id = _scope(
        request, tenant_id, "read", "reports"
    )
    rows = recovery_service.reports(tenant_id, limit=max(1, min(limit, 200)))
    return {"tenant_id": tenant_id, "reports": rows, "count": len(rows)}


@router.get("/reports/{report_id}")
async def recovery_report(
    report_id: str,
    request: Request,
    tenant_id: str = TENANT_ID,
    _admin: dict = Depends(require_admin),
):
    _principal, tenant_id, _agent_id, _user_id = _scope(
        request, tenant_id, "read", report_id
    )
    row = recovery_service.report(tenant_id, report_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Recovery report not found")
    return row


@router.get("/evidence")
async def recovery_evidence_list(
    request: Request,
    tenant_id: str = TENANT_ID,
    limit: int = 50,
    _admin: dict = Depends(require_admin),
):
    _principal, tenant_id, _agent_id, _user_id = _scope(
        request, tenant_id, "read", "evidence"
    )
    rows = recovery_service.list_drill_evidence(tenant_id, limit=max(1, min(limit, 200)))
    return {"tenant_id": tenant_id, "evidence": rows, "count": len(rows)}


@router.get("/evidence/{evidence_id}")
async def recovery_evidence_detail(
    evidence_id: str,
    request: Request,
    tenant_id: str = TENANT_ID,
    _admin: dict = Depends(require_admin),
):
    _principal, tenant_id, _agent_id, _user_id = _scope(
        request, tenant_id, "read", evidence_id
    )
    row = recovery_service.get_drill_evidence(tenant_id, evidence_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Recovery drill evidence not found")
    return row


@router.post("/evidence")
async def recovery_evidence_submit(
    body: DrillEvidenceRequest,
    request: Request,
    _admin: dict = Depends(require_admin),
):
    principal, tenant_id, _agent_id, _user_id = _scope(
        request, body.tenant_id, "manage", "evidence"
    )
    try:
        row = await asyncio.to_thread(
            recovery_service.persist_drill_evidence,
            tenant_id=tenant_id,
            root_id=body.root_id,
            evidence=body.evidence,
            submitted_by=principal.user_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return row


@router.post("/verify")
async def verify_recovery(
    body: VerifyRecoveryRequest,
    request: Request,
    _admin: dict = Depends(require_admin),
):
    principal, tenant_id, _agent_id, _user_id = _scope(
        request, body.tenant_id, "manage", "verify"
    )
    try:
        return await asyncio.to_thread(
            recovery_service.run_verification,
            tenant_id=tenant_id,
            root_id=body.root_id,
            triggered_by=principal.user_id,
            evidence_id=body.evidence_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
