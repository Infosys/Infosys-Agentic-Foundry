"""
Enterprise Evidence API.

Provides retrieval and content streaming for evidence bundles produced by chat,
REST API, cron, and queue executions.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import FileResponse, PlainTextResponse, Response

from auth.middleware import require_admin
from security.dependencies import require_scoped_identity
from shared.document_source import get_source, valid_scope_id
from shared.evidence_store import (
    get_evidence_blob,
)
from iaf_agent_skills.evidence_collector_adapter import EvidenceCollectorAdapter

router = APIRouter(prefix="/api/evidence", tags=["evidence"])
_evidence_adapter = EvidenceCollectorAdapter()


@router.post("")
async def store_evidence(bundle: dict, request: Request, _admin: dict = Depends(require_admin)):
    """Store an evidence bundle. Intended for internal/job integrations."""
    trace_id = bundle.get("trace_id")
    if not isinstance(trace_id, str) or not trace_id:
        raise HTTPException(status_code=400, detail="Invalid or empty evidence bundle")
    agent = bundle.get("agent_id")
    agent = agent if isinstance(agent, str) and valid_scope_id(agent) else None
    req_tenant = bundle.get("tenant_id")
    _principal, tenant_id, agent_id, user_id = require_scoped_identity(
        request,
        requested_tenant=req_tenant if isinstance(req_tenant, str) and req_tenant else None,
        requested_agent=agent,
        action="use",
        resource_type="agent",
        resource_id=agent or "enterprise_agent",
    )
    if not (valid_scope_id(tenant_id) and valid_scope_id(agent_id) and valid_scope_id(user_id)):
        raise HTTPException(status_code=400, detail="Invalid tenant/agent/user id")
    # Identity comes from the principal, never from the payload.
    bundle = {**bundle, "tenant_id": tenant_id, "agent_id": agent_id, "user_id": user_id}
    items = []
    for item in bundle.get("evidence_items") or []:
        if not isinstance(item, dict):
            raise HTTPException(status_code=400, detail="Invalid evidence item")
        meta = dict(item.get("metadata") or {}) if isinstance(item.get("metadata") or {}, dict) else {}
        meta.update(tenant_id=tenant_id, agent_id=agent_id, user_id=user_id)
        items.append({**item, "metadata": meta, "tenant_id": tenant_id})
    if items:
        bundle["evidence_items"] = items
    existing = _evidence_adapter.fetch_bundle(trace_id, tenant_id=tenant_id)
    if existing and (existing.get("user_id") or "") != user_id:
        raise HTTPException(status_code=403, detail="Evidence trace_id is owned by another principal")
    result = _evidence_adapter.persist(bundle)
    if not result:
        raise HTTPException(status_code=400, detail="Invalid or empty evidence bundle")
    return {"status": "stored", **result}


@router.get("/{trace_id}")
async def retrieve_evidence(trace_id: str, tenant_id: str = Query("", description="Tenant id override")):
    bundle = _evidence_adapter.fetch_bundle(trace_id, tenant_id=tenant_id)
    if not bundle:
        raise HTTPException(status_code=404, detail="Evidence bundle not found")
    return bundle


@router.get("/{trace_id}/items/{evidence_id}")
async def retrieve_evidence_item(
    trace_id: str,
    evidence_id: str,
    tenant_id: str = Query("", description="Tenant id override"),
):
    item = _evidence_adapter.fetch_item(trace_id, evidence_id, tenant_id=tenant_id)
    if not item:
        raise HTTPException(status_code=404, detail="Evidence item not found")
    return item


@router.get("/{trace_id}/items/{evidence_id}/text")
async def retrieve_evidence_text(
    trace_id: str,
    evidence_id: str,
    tenant_id: str = Query("", description="Tenant id override"),
):
    item = _evidence_adapter.fetch_item(trace_id, evidence_id, tenant_id=tenant_id)
    if not item:
        raise HTTPException(status_code=404, detail="Evidence item not found")

    extracted = item.get("extracted_text") or {}
    if extracted.get("excerpt"):
        return PlainTextResponse(extracted["excerpt"], media_type="text/plain; charset=utf-8")

    blob = get_evidence_blob(trace_id, evidence_id, tenant_id=tenant_id)
    if blob:
        payload, _mime_type = blob
        return PlainTextResponse(payload.decode("utf-8", errors="replace"), media_type="text/plain; charset=utf-8")

    raise HTTPException(status_code=404, detail="No extracted text available for evidence item")


@router.get("/{trace_id}/items/{evidence_id}/content")
async def retrieve_evidence_content(
    trace_id: str,
    evidence_id: str,
    tenant_id: str = Query("", description="Tenant id override"),
):
    item = _evidence_adapter.fetch_item(trace_id, evidence_id, tenant_id=tenant_id)
    if not item:
        raise HTTPException(status_code=404, detail="Evidence item not found")

    blob = get_evidence_blob(trace_id, evidence_id, tenant_id=tenant_id)
    if blob:
        payload, mime_type = blob
        return Response(content=payload, media_type=mime_type)

    if item.get("content_strategy") != "resolve_on_demand":
        raise HTTPException(status_code=404, detail="Evidence content was not stored")

    try:
        source = get_source(item.get("source_uri", ""), item.get("source_type", ""))
        content = source.resolve(
            item.get("source_uri", ""),
            tenant_id=item.get("tenant_id") or tenant_id,
            agent_id=(item.get("metadata") or {}).get("agent_id", ""),
            user_id=(item.get("metadata") or {}).get("user_id", ""),
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except NotImplementedError as exc:
        raise HTTPException(status_code=501, detail=str(exc)) from exc

    if content.payload is not None:
        return Response(
            content=content.payload,
            media_type=content.mime_type,
            headers={"Content-Disposition": f'inline; filename="{content.display_name}"'},
        )

    if content.path is not None:
        return FileResponse(
            content.path,
            media_type=content.mime_type,
            filename=content.display_name,
            headers={"Content-Disposition": f'inline; filename="{content.display_name}"'},
        )

    raise HTTPException(status_code=404, detail="Evidence source returned no content")
