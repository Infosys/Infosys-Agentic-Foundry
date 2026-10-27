"""
Plan Library router — CRUD for plan_cache entries.
Provides list, approve, reject, and stats endpoints for the dashboard.
"""
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel
from typing import Optional, List, Any
import logging
import uuid as _uuid

from security.dependencies import enforce_entitlement, require_scoped_identity

logger = logging.getLogger("iaf_server")
router = APIRouter(prefix="/api/plans", tags=["plans"])


def _scope_plan(request: Request, *, tenant_id: str, agent_id: str, action: str, resource_id: str = "*"):
    """Bind request identity and enforce one route-level permission.

    Previously absent from this router. AuthMiddleware is AuthN only — it validates the
    JWT and stamps request.state, then calls through — so without this the client-supplied
    `tenant_id` query parameter was honoured verbatim and any authenticated user could
    read, and APPROVE, another tenant's plan library. Approval is the dangerous half: an
    approved plan is retrieved into later runs, so writing to another tenant's library is
    a persistence primitive, not just a data leak.

    Binds the agent too: the plan cache is per-(tenant, agent), so a caller-supplied
    `agent_id` must be authorised, or a user could read/mutate another agent's cache
    within their tenant by changing the query parameter.

    Returns the BOUND (tenant, agent), which callers MUST use in place of the requested ones.
    """
    principal, bound_tenant, bound_agent, _user_id = require_scoped_identity(
        request,
        requested_tenant=tenant_id,
        requested_agent=agent_id,
        action=action,
        resource_type="plan",
        resource_id=resource_id,
    )
    # Enforce 'use' on the agent (default-deny) as chat.py does; identity binding alone does not authorise.
    enforce_entitlement(principal, "use", "agent", bound_agent)
    return bound_tenant, bound_agent


def _get_indexer(tenant_id: str, agent_id: str):
    """Resolve KnowledgeIndexer via the live agent state (same instance the agent uses)."""
    try:
        from routers.chat import state
        agent = state.get_or_create(tenant_id, agent_id, "admin", user_role="admin")
        indexer = getattr(agent.memory, 'knowledge_indexer', None)
        return indexer
    except Exception as e:
        logger.warning("_get_indexer failed: %s", e)
        return None


@router.get("")
async def list_plans(
    request: Request,
    tenant_id: str = "company",
    agent_id: str = "enterprise_agent",
    status: Optional[str] = None,
    limit: int = 100,
):
    """List plan_cache entries. Filter by status if provided."""
    tenant_id, agent_id = _scope_plan(request, tenant_id=tenant_id, agent_id=agent_id, action="read", resource_id="*")
    indexer = _get_indexer(tenant_id, agent_id)
    if not indexer:
        return {"plans": [], "total": 0}
    plans = indexer.list_plan_cache(status=status, tenant_id=tenant_id, agent_id=agent_id, limit=limit)
    return {"plans": plans, "total": len(plans)}


@router.get("/stats")
async def plan_stats(
    request: Request,
    tenant_id: str = "company",
    agent_id: str = "enterprise_agent",
):
    """Return counts by status — used for dashboard badge."""
    tenant_id, agent_id = _scope_plan(request, tenant_id=tenant_id, agent_id=agent_id, action="read", resource_id="*")
    indexer = _get_indexer(tenant_id, agent_id)
    if not indexer:
        return {"pending_review": 0, "approved": 0, "rejected": 0, "total": 0}
    return indexer.get_plan_cache_stats(tenant_id=tenant_id, agent_id=agent_id)


class StatusUpdate(BaseModel):
    approved_by: Optional[str] = "admin"


class PlanUpdate(BaseModel):
    goal: str
    plan_steps: List[Any]
    execution_mode: Optional[str] = None
    detected_domains: Optional[List[str]] = None
    context_hints: Optional[List[Any]] = None


class PlanCreate(BaseModel):
    goal: str
    plan_steps: List[Any]
    execution_mode: str = "planned"
    detected_domains: Optional[List[str]] = None
    plan_id: Optional[str] = None


@router.put("/{plan_id}")
async def update_plan(
    request: Request,
    plan_id: str,
    body: PlanUpdate,
    tenant_id: str = "company",
    agent_id: str = "enterprise_agent",
):
    """Edit a plan's goal, steps, mode, or domains."""
    tenant_id, agent_id = _scope_plan(request, tenant_id=tenant_id, agent_id=agent_id, action="write", resource_id=plan_id)
    indexer = _get_indexer(tenant_id, agent_id)
    if not indexer:
        raise HTTPException(status_code=404, detail="Indexer not found")
    ok = indexer.edit_plan_cache(
        plan_id=plan_id,
        goal=body.goal,
        plan_steps=body.plan_steps,
        execution_mode=body.execution_mode,
        detected_domains=body.detected_domains,
        context_hints=body.context_hints,
    )
    if not ok:
        raise HTTPException(status_code=404, detail="Plan not found")
    return {"status": "updated", "plan_id": plan_id}


@router.post("")
async def create_plan(
    request: Request,
    body: PlanCreate,
    tenant_id: str = "company",
    agent_id: str = "enterprise_agent",
):
    """Manually create a new plan cache entry from the dashboard."""
    tenant_id, agent_id = _scope_plan(request, tenant_id=tenant_id, agent_id=agent_id, action="write", resource_id="*")
    indexer = _get_indexer(tenant_id, agent_id)
    if not indexer:
        raise HTTPException(status_code=404, detail="Indexer not found")
    new_id = body.plan_id or f"plan_{_uuid.uuid4().hex[:12]}"
    ok = indexer.insert_plan_cache(
        plan_id=new_id,
        goal=body.goal,
        plan_steps=body.plan_steps,
        execution_mode=body.execution_mode,
        detected_domains=body.detected_domains,
        tenant_id=tenant_id,
        agent_id=agent_id,
    )
    if not ok:
        raise HTTPException(status_code=409, detail="Plan already exists with that fingerprint")
    return {"status": "created", "plan_id": new_id}


@router.post("/{plan_id}/approve")
async def approve_plan(
    request: Request,
    plan_id: str,
    body: StatusUpdate = StatusUpdate(),
    tenant_id: str = "company",
    agent_id: str = "enterprise_agent",
):
    """Approve a plan for retrieval."""
    tenant_id, agent_id = _scope_plan(request, tenant_id=tenant_id, agent_id=agent_id, action="approve", resource_id=plan_id)
    indexer = _get_indexer(tenant_id, agent_id)
    if not indexer:
        raise HTTPException(status_code=404, detail="Indexer not found")
    ok = indexer.update_plan_cache_status(plan_id, "approved", body.approved_by)
    if not ok:
        raise HTTPException(status_code=404, detail="Plan not found")
    return {"status": "approved", "plan_id": plan_id}


@router.post("/{plan_id}/reject")
async def reject_plan(
    request: Request,
    plan_id: str,
    body: StatusUpdate = StatusUpdate(),
    tenant_id: str = "company",
    agent_id: str = "enterprise_agent",
):
    """Reject a plan — it will never resurface for retrieval."""
    tenant_id, agent_id = _scope_plan(request, tenant_id=tenant_id, agent_id=agent_id, action="approve", resource_id=plan_id)
    indexer = _get_indexer(tenant_id, agent_id)
    if not indexer:
        raise HTTPException(status_code=404, detail="Indexer not found")
    ok = indexer.update_plan_cache_status(plan_id, "rejected", body.approved_by)
    if not ok:
        raise HTTPException(status_code=404, detail="Plan not found")
    return {"status": "rejected", "plan_id": plan_id}
