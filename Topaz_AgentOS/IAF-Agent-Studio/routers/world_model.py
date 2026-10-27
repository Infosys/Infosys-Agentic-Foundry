"""
IAF Agent Studio — World-Model Graph Review Router

Governance surface for the living world model (Phase 2). Agent-learned relationship
edges land as ``pending_review`` (hidden from graph reads until vetted). This router lets
a reviewer list those pending edges and promote (→ ``confirmed``, now visible) or reject
(→ ``rejected``, kept as an audit record) them. Every decision is logged to the agent's
append-only ``world_events.jsonl`` spine by the world_model service.

Mirrors the knowledge-review pattern in routers/knowledge.py: scoped identity →
state.get_or_create → agent.memory.knowledge_indexer.entity_registry.
"""

import logging
import traceback
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from security.dependencies import require_scoped_identity
from shared.state import state
from iaf_agent_skills import world_model

logger = logging.getLogger(__name__)

router = APIRouter()


class GraphEdgeAction(BaseModel):
    rel_id: str
    tenant_id: str = "company"
    agent_id: str = "enterprise_agent"
    user_id: str = "demo"


def _scope(request: Request, *, tenant_id: str, agent_id: str, user_id: str,
           action: str = "read", resource_id: str = "*"):
    return require_scoped_identity(
        request,
        requested_tenant=tenant_id,
        requested_agent=agent_id,
        requested_user=user_id,
        action=action,
        resource_type="memory",
        resource_id=resource_id,
    )


def _entity_store_and_events(principal, tenant_id: str, agent_id: str, user_id: str):
    """Resolve the agent's EntityRegistryStore + its world_events.jsonl path.

    Returns (entity_store, events_path). entity_store is None when the agent has no
    knowledge index / entity registry (e.g. a brand-new agent) — callers degrade gracefully.
    """
    user_role = principal.roles[0] if principal.roles else "user"
    agent = state.get_or_create(tenant_id, agent_id, user_id, user_role=user_role)
    indexer = getattr(agent.memory, "knowledge_indexer", None)
    entity_store = getattr(indexer, "entity_registry", None) if indexer else None
    events_path = None
    memory_root = getattr(agent.memory, "memory_root", None)
    if memory_root is not None:
        events_path = str(Path(memory_root) / "world_events.jsonl")
    return entity_store, events_path


@router.get("/api/world-model/pending")
async def list_pending_edges(
    request: Request,
    tenant_id: str = "company",
    agent_id: str = "enterprise_agent",
    user_id: str = "demo",
    limit: int = 100,
):
    """List agent-learned edges awaiting a promote/reject decision."""
    principal, tenant_id, agent_id, user_id = _scope(
        request, tenant_id=tenant_id, agent_id=agent_id, user_id=user_id,
        action="read", resource_id="world_model",
    )
    try:
        entity_store, _ = _entity_store_and_events(principal, tenant_id, agent_id, user_id)
        if entity_store is None:
            return {"pending": [], "count": 0}
        pending = world_model.list_pending(entity_store, limit=max(1, min(int(limit), 500)))
        return {"pending": pending, "count": len(pending)}
    except Exception as e:
        traceback.print_exc()
        return {"pending": [], "count": 0, "error": "An internal error occurred"}


@router.post("/api/world-model/promote")
async def promote_edge(req: GraphEdgeAction, request: Request):
    """Promote a pending_review edge to confirmed (now visible to graph reads)."""
    principal, tenant_id, agent_id, user_id = _scope(
        request, tenant_id=req.tenant_id, agent_id=req.agent_id, user_id=req.user_id,
        action="write", resource_id=req.rel_id,
    )
    try:
        entity_store, events_path = _entity_store_and_events(principal, tenant_id, agent_id, user_id)
        if entity_store is None:
            raise HTTPException(404, "Entity registry not available for this agent")
        ok = world_model.promote_relationship(
            entity_store, req.rel_id, events_path=events_path, promoted_by=(user_id or "reviewer"))
        if not ok:
            raise HTTPException(400, f"Could not promote edge {req.rel_id}")
        return {"status": "confirmed", "rel_id": req.rel_id}
    except HTTPException:
        raise
    except Exception as e:
        traceback.print_exc()
        logger.exception("promote_edge failed")
        raise HTTPException(500, "An internal error occurred")


@router.post("/api/world-model/reject")
async def reject_edge(req: GraphEdgeAction, request: Request):
    """Reject a pending_review edge (kept as an audit record; never returned by reads)."""
    principal, tenant_id, agent_id, user_id = _scope(
        request, tenant_id=req.tenant_id, agent_id=req.agent_id, user_id=req.user_id,
        action="write", resource_id=req.rel_id,
    )
    try:
        entity_store, events_path = _entity_store_and_events(principal, tenant_id, agent_id, user_id)
        if entity_store is None:
            raise HTTPException(404, "Entity registry not available for this agent")
        ok = world_model.reject_relationship(
            entity_store, req.rel_id, events_path=events_path, rejected_by=(user_id or "reviewer"))
        if not ok:
            raise HTTPException(400, f"Could not reject edge {req.rel_id}")
        return {"status": "rejected", "rel_id": req.rel_id}
    except HTTPException:
        raise
    except Exception as e:
        traceback.print_exc()
        logger.exception("reject_edge failed")
        raise HTTPException(500, "An internal error occurred")
