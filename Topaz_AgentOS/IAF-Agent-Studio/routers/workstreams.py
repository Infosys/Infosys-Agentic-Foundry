"""
Workstream REST + WebSocket API.

Backs Mission Mode's UI surface. State lives in
``enterprise_root/tenants/<tenant_id>/workstreams/<name>.yaml`` — owned by
``iaf_agent_skills.workstream_store.WorkstreamStore``.

Endpoints:
    GET    /api/workstreams                      list summaries
    POST   /api/workstreams                      create (+ optionally provision cron)
    GET    /api/workstreams/{name}               full detail
    PATCH  /api/workstreams/{name}               patch top-level fields
    DELETE /api/workstreams/{name}               delete YAML (+ optionally delete cron)
    POST   /api/workstreams/{name}/pause
    POST   /api/workstreams/{name}/resume
    POST   /api/workstreams/{name}/cancel
    POST   /api/workstreams/{name}/items         append a new item
    POST   /api/workstreams/{name}/items/{id}/retry      reset attempts, mark pending
    POST   /api/workstreams/{name}/items/{id}/skip       mark item as done with reason "skipped"
    WS     /ws/workstreams/{name}                 push Mission Mode lifecycle events
"""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from pathlib import Path
from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Request, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, Field

from iaf_agent_skills.workstream_store import (
    WorkstreamStore,
    validate_workstream,
    now_iso,
)
from iaf_agent_skills.capture_events import emit_workstream_lifecycle
from security.dependencies import bind_websocket_identity, enforce_entitlement, require_scoped_identity
from shared.config import SERVER_DIR, DATA_ROOT, DATA_ROOT_PATH


logger = logging.getLogger(__name__)

router = APIRouter()

DEFAULT_TENANT_ID = "company"

ITEM_CONTEXT_RESULT_LIMIT = 1000
ITEM_CASE_TEXT_LIMIT = 500
ITEM_CASE_LIST_LIMIT = 8
WORKSTREAM_BUSINESS_TEXT_LIMIT = 500
WORKSTREAM_BUSINESS_METRIC_LIMIT = 12
ITEM_CHAT_MESSAGE_LIMIT = 500
ITEM_CHAT_RESPONSE_LIMIT = 8000
ITEM_CHAT_PREVIEW_LIMIT = 10
WORKSTREAM_CHAT_MESSAGE_LIMIT = 700
WORKSTREAM_CHAT_RESPONSE_LIMIT = 8000
WORKSTREAM_CHAT_PREVIEW_LIMIT = 10
WORKSTREAM_CHAT_ITEM_LIMIT = 25


def _scope_workstream(
    request: Request,
    *,
    tenant_id: str,
    action: str,
    resource_id: str,
):
    return require_scoped_identity(
        request,
        requested_tenant=tenant_id,
        action=action,
        resource_type="workstream",
        resource_id=resource_id,
    )


# Fields that change how queued work executes; editable only when nothing is in flight (`automation` overrides `skill`).
_EXECUTION_FIELDS = ("skill", "automation", "batch_size", "parallelism")
_EXECUTION_EDITABLE_STATES = ("paused", "completed")


def _assert_skill_exists(skill_name: str) -> None:
    """Raise 400 if `skill_name` does not resolve to a loadable skill.

    Reads the same source as GET /api/skills so the API cannot accept a skill the
    UI would never offer. Import and provider construction are local to the call
    because this runs only when a patch actually changes the bound skill.

    A provider that cannot be built is treated as "cannot disprove": we log and
    allow the patch rather than blocking an edit on an unrelated loader fault.
    """
    try:
        from shared.config import SERVER_DIR, SKILLS_PATH
        from iaf_agent_skills.providers.factory import build_router_provider

        provider = build_router_provider(str(SERVER_DIR / SKILLS_PATH))
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning("skill validation unavailable, allowing patch: %s", exc)
        return

    try:
        exists = provider.skill_exists(skill_name)
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning("skill_exists(%s) failed, allowing patch: %s", skill_name, exc)
        return

    if not exists:
        raise HTTPException(
            status_code=400,
            detail={"errors": [f"skill {skill_name!r} does not exist"]},
        )


def _record_workstream_reward_best_effort(
    *,
    tenant_id: str,
    workstream_name: str,
    raw_label: str,
    item_id: str = "",
    trace_id: str = "",
    judge_id: str = "",
    notes: str = "",
    metadata: dict[str, Any] | None = None,
) -> None:
    try:
        emit_workstream_lifecycle(
            data_root=DATA_ROOT_PATH,
            tenant_id=tenant_id,
            workstream_id=workstream_name,
            status=raw_label,
            item_id=item_id,
            trace_id=trace_id,
            actor=judge_id,
            notes=notes,
            metadata=metadata or {},
        )
    except Exception as rl_err:
        logger.debug("RL workstream reward skipped: %s", rl_err)


def _record_iteration_rewards(tenant_id: str, results: list[Any], *, source: str) -> None:
    for result in results:
        row = result if isinstance(result, dict) else getattr(result, "__dict__", {})
        if not row:
            continue
        workstream_name = str(row.get("workstream_name") or "")
        if not workstream_name:
            continue
        _record_workstream_reward_best_effort(
            tenant_id=tenant_id,
            workstream_name=workstream_name,
            item_id=str(row.get("item_id") or ""),
            trace_id=str(row.get("trace_id") or ""),
            raw_label=str(row.get("item_status_after") or row.get("action") or "observed"),
            notes=str(row.get("reason") or ""),
            metadata={"source": source, "iteration_result": row},
        )
VALID_ITEM_ACTION_TYPES = {"retry", "skip", "close", "correct", "email", "post", "resend", "mark_done"}
BLOCKED_CONNECTOR_ACTIONS = {"correct", "email", "post", "resend"}
ITEM_ACTION_ALIASES = {
    "retry_item": "retry",
    "skip_item": "skip",
    "close_item": "close",
    "done": "mark_done",
    "mark_item_done": "mark_done",
}


def _tenant_root(tenant_id: str = DEFAULT_TENANT_ID) -> Path:
    return Path(SERVER_DIR) / DATA_ROOT / "tenants" / tenant_id


def _store(tenant_id: str = DEFAULT_TENANT_ID) -> WorkstreamStore:
    return WorkstreamStore(_tenant_root(tenant_id))


def _runtime_executions(name: str, item_id: str, limit: int = 10) -> list[dict[str, Any]]:
    """Return durable runtime executions for one Workstream item."""
    try:
        from workstream_runtime.db import get_db, init_db_path
        try:
            db = get_db()
        except RuntimeError:
            init_db_path(SERVER_DIR)
            db = get_db()
        return db.get_item_executions(name, item_id, limit=limit)
    except Exception as exc:
        logger.debug("workstream runtime executions unavailable for %s/%s: %s", name, item_id, exc)
        return []


def _bounded_text(value: Any, limit: int) -> str:
    text = "" if value is None else str(value)
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 3)] + "..."


def _compact_case_summary(value: Any) -> dict:
    if not isinstance(value, dict):
        return {}
    allowed = {
        "case_id",
        "case_type",
        "title",
        "primary_entity",
        "secondary_entity",
        "category",
        "impact_label",
        "impact_value",
        "age_or_sla",
        "risk_level",
        "priority_reason",
        "recommended_action",
        "recommendation_confidence",
        "policy_trigger",
        "evidence_summary",
    }
    compact: dict[str, Any] = {}
    for key in allowed:
        item = value.get(key)
        if item is None:
            continue
        if isinstance(item, (int, float, bool)):
            compact[key] = item
        else:
            compact[key] = _bounded_text(item, ITEM_CASE_TEXT_LIMIT)
    return compact


def _compact_case_insights(value: Any) -> dict:
    if not isinstance(value, dict):
        return {}

    def compact_list(items: Any, item_limit: int = ITEM_CASE_TEXT_LIMIT) -> list:
        if not isinstance(items, list):
            return []
        compact_items = []
        for row in items[:ITEM_CASE_LIST_LIMIT]:
            if isinstance(row, dict):
                compact_items.append({
                    str(k)[:80]: _bounded_text(v, item_limit)
                    for k, v in row.items()
                    if v is not None
                })
            else:
                compact_items.append(_bounded_text(row, item_limit))
        return compact_items

    return {
        "current_findings": compact_list(value.get("current_findings")),
        "historical_patterns": compact_list(value.get("historical_patterns")),
        "recommendation_reasoning": compact_list(value.get("recommendation_reasoning")),
        "prevention_opportunities": compact_list(value.get("prevention_opportunities")),
        "similar_cases": compact_list(value.get("similar_cases")),
    }


def _compact_business_lens(ws: dict) -> dict:
    lens = ws.get("business_lens")
    metrics_source = None
    if isinstance(lens, dict):
        metrics_source = lens.get("metrics")
    elif isinstance(ws.get("business_metrics"), list):
        lens = {}
        metrics_source = ws.get("business_metrics")
    else:
        return {}

    compact: dict[str, Any] = {}
    if isinstance(lens, dict):
        for key in (
            "title",
            "subtitle",
            "primary_entity_label",
            "secondary_entity_label",
            "value_label",
        ):
            if lens.get(key) is not None:
                compact[key] = _bounded_text(lens.get(key), WORKSTREAM_BUSINESS_TEXT_LIMIT)

    metrics: list[dict[str, Any]] = []
    if isinstance(metrics_source, list):
        for row in metrics_source[:WORKSTREAM_BUSINESS_METRIC_LIMIT]:
            if not isinstance(row, dict):
                continue
            clean: dict[str, Any] = {}
            for key in ("id", "label", "value", "unit", "trend", "severity", "explanation"):
                value = row.get(key)
                if value is None:
                    continue
                if isinstance(value, (int, float, bool)):
                    clean[key] = value
                else:
                    clean[key] = _bounded_text(value, WORKSTREAM_BUSINESS_TEXT_LIMIT)
            if clean:
                metrics.append(clean)
    if metrics:
        compact["metrics"] = metrics
    return compact


def _item_chat_session_id(name: str, item_id: str) -> str:
    return f"workstream:{name}:item:{item_id}"


def _workstream_chat_session_id(name: str) -> str:
    return f"workstream:{name}:overall"


def _find_item(ws: dict, item_id: str) -> dict | None:
    return next((item for item in ws.get("items", []) if item.get("id") == item_id), None)


def _request_actor(request: Request) -> str:
    state = getattr(request, "state", None)
    return (
        getattr(state, "email", None)
        or getattr(state, "user_id", None)
        or "workstream_user"
    )


def _suggested_actions_for_item_status(status: str) -> list[dict[str, Any]]:
    base = [{"id": "continue_chat", "label": "Continue", "kind": "chat", "side_effect": False}]
    if status == "awaiting_human":
        return base + [
            {"id": "approve", "label": "Approve", "kind": "approval", "side_effect": True},
            {"id": "reject", "label": "Reject", "kind": "approval", "side_effect": True},
            {"id": "mark_done", "label": "Done", "kind": "state", "side_effect": False},
        ]
    if status == "done":
        return base + [
            {"id": "close_item", "label": "Close", "kind": "state", "side_effect": False},
            {"id": "retry_item", "label": "Retry", "kind": "rerun", "side_effect": True},
        ]
    if status == "failed":
        return base + [
            {"id": "retry_item", "label": "Retry", "kind": "rerun", "side_effect": True},
            {"id": "skip_item", "label": "Skip", "kind": "state", "side_effect": False},
        ]
    return base


def _build_item_chat_prompt(ws: dict, item: dict, message: str, selected_skill: str = "") -> str:
    evidence_trace = item.get("evidence_trace_id") or item.get("last_trace_id") or ""
    execution_log = item.get("execution_log") or []
    recent_log = execution_log[-3:]
    case_summary = _compact_case_summary(item.get("case_summary"))
    case_insights = _compact_case_insights(item.get("case_insights"))
    return (
        "You are continuing a Workstream Detail item conversation.\n"
        "Use the bounded item context below as the business case context for the user's request. "
        "If the user explicitly selected a skill, execute through that skill's normal AgentPro capabilities. "
        "Any side-effecting work must remain governed by entitlements, tool policy, Workstream actions, or HITL approval; do not bypass those controls.\n\n"
        f"Workstream: {ws.get('name')}\n"
        f"Display name: {ws.get('display_name') or ws.get('name')}\n"
        f"Workstream skill: {ws.get('skill')}\n"
        f"Selected chat skill: {selected_skill or ws.get('skill') or 'auto'}\n"
        f"Item id: {item.get('id')}\n"
        f"Item status: {item.get('status', 'pending')}\n"
        f"Description: {_bounded_text(item.get('description', ''), 700)}\n"
        f"Case summary: {json.dumps(case_summary, default=str)[:1800]}\n"
        f"Case insights: {json.dumps(case_insights, default=str)[:2600]}\n"
        f"Last result: {_bounded_text(item.get('last_result_summary') or item.get('resolution') or '', 1000)}\n"
        f"Evidence trace: {evidence_trace}\n"
        f"Evidence count: {int(item.get('evidence_count') or 0)}\n"
        f"Recent execution log: {json.dumps(recent_log, default=str)[:1500]}\n\n"
        f"User message: {message}"
    )


def _status_counts(items: list[dict]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for item in items:
        status = item.get("status") or "pending"
        counts[status] = counts.get(status, 0) + 1
    return counts


def _workstream_chat_preview(meta: Any) -> list[dict]:
    if not isinstance(meta, dict):
        return []
    preview = meta.get("workstream_chat_transcript_preview")
    if not isinstance(preview, list):
        return []
    clean: list[dict] = []
    for entry in preview[-WORKSTREAM_CHAT_PREVIEW_LIMIT:]:
        if not isinstance(entry, dict):
            continue
        row = dict(entry)
        row["message"] = _bounded_text(row.get("message", ""), WORKSTREAM_CHAT_MESSAGE_LIMIT)
        row["response"] = _bounded_text(row.get("response", ""), WORKSTREAM_CHAT_RESPONSE_LIMIT)
        clean.append(row)
    return clean


def _compact_workstream_chat_context(ws: dict) -> dict:
    items = ws.get("items") or []
    compact_items = []
    for item in items[:WORKSTREAM_CHAT_ITEM_LIMIT]:
        compact_items.append({
            "id": item.get("id"),
            "status": item.get("status", "pending"),
            "attempts": item.get("attempts", 0),
            "description": _bounded_text(item.get("description", ""), 240),
            "last_result_summary": _bounded_text(
                item.get("last_result_summary") or item.get("resolution") or "",
                320,
            ),
            "evidence_trace_id": item.get("evidence_trace_id") or item.get("last_trace_id"),
            "evidence_count": int(item.get("evidence_count") or 0),
            "escalated_approval_id": item.get("escalated_approval_id"),
        })
    return {
        "name": ws.get("name"),
        "display_name": ws.get("display_name") or ws.get("name"),
        "description": _bounded_text(ws.get("description", ""), 500),
        "status": ws.get("status"),
        "skill": ws.get("skill"),
        "automation": ws.get("automation"),
        "owner": ws.get("owner", ""),
        "business_lens": _compact_business_lens(ws),
        "total_items": len(items),
        "status_counts": _status_counts(items),
        "batch_size": ws.get("batch_size", 1),
        "parallelism": ws.get("parallelism", 1),
        "items_preview": compact_items,
        "items_preview_limit": WORKSTREAM_CHAT_ITEM_LIMIT,
    }


def _build_workstream_chat_prompt(ws: dict, message: str) -> str:
    context = _compact_workstream_chat_context(ws)
    return (
        "You are answering questions in a Workstream Detail sidebar.\n"
        "Use ONLY the bounded Workstream context below. Summarize clearly across items, statuses, approvals, evidence, and recent results. "
        "Do not call tools, do not contact external systems, and do not perform side effects. "
        "If the user asks for side-effecting work, explain that it must use governed Workstream actions or HITL approval flows.\n\n"
        f"Workstream context JSON: {json.dumps(context, default=str)[:6000]}\n\n"
        f"User message: {message}"
    )


async def _run_item_chat_via_existing_chat(
    request: Request,
    *,
    tenant_id: str,
    session_id: str,
    skill_name: str,
    prompt: str,
    workstream_name: str = "",
    item_id: str = "",
) -> dict:
    from shared.models import ChatMessage
    from routers.chat import chat_endpoint

    page_context = None
    if workstream_name:
        page_context = {
            "workstream_name": workstream_name,
            "mission_item_id": item_id,
        }

    msg = ChatMessage(
        content=prompt,
        tenant_id=tenant_id,
        agent_id="enterprise_agent",
        user_id=session_id,
        skill_name=skill_name or None,
        source_page="workstream_item_chat" if page_context else None,
        page_context=page_context,
        human_approval=True,
        light_mode=True,
        knowledge_mode="hybrid",
    )
    return await chat_endpoint(msg, request)


def _compact_item_context(item: dict) -> dict:
    return {
        "id": item.get("id"),
        "description": item.get("description", ""),
        "case_summary": _compact_case_summary(item.get("case_summary")),
        "case_insights": _compact_case_insights(item.get("case_insights")),
        "status": item.get("status", "pending"),
        "attempts": item.get("attempts", 0),
        "last_attempted_at": item.get("last_attempted_at"),
        "last_trace_id": item.get("last_trace_id"),
        "evidence_trace_id": item.get("evidence_trace_id") or item.get("last_trace_id"),
        "evidence_count": int(item.get("evidence_count") or 0),
        "last_result_summary": _bounded_text(
            item.get("last_result_summary") or item.get("resolution") or "",
            ITEM_CONTEXT_RESULT_LIMIT,
        ),
        "last_result_at": item.get("last_result_at"),
        "resolution": _bounded_text(item.get("resolution") or "", ITEM_CONTEXT_RESULT_LIMIT),
        "escalated_approval_id": item.get("escalated_approval_id"),
        "acceptance_criteria": item.get("acceptance_criteria") or [],
        "execution_log": item.get("execution_log") or [],
        "current_execution_id": item.get("current_execution_id"),
        "execution_ledger": item.get("execution_ledger") or [],
        "action_events": item.get("action_events") or [],
        "last_failure_reason": item.get("last_failure_reason"),
        "suggested_actions": item.get("suggested_actions") or [],
        "chat_session_id": item.get("chat_session_id"),
        "chat_last_message_at": item.get("chat_last_message_at"),
        "chat_transcript_preview": item.get("chat_transcript_preview") or [],
        "last_approval_context": item.get("last_approval_context"),
        "closed_at": item.get("closed_at"),
        "closed_by": item.get("closed_by"),
    }


async def _pending_approval_for_item(tenant_id: str, name: str, item: dict) -> Optional[dict]:
    approval_id = item.get("escalated_approval_id")
    if not approval_id:
        return None
    try:
        from shared.state import approval_store
        pending = await approval_store.get_pending(tenant_id)
    except Exception:
        pending = []
    for approval in pending or []:
        payload = approval.to_dict() if hasattr(approval, "to_dict") else dict(approval)
        payload_id = payload.get("id") or payload.get("approval_id")
        ctx = payload.get("context") or {}
        ctx_ws = ctx.get("workstream_name") or ctx.get("workstream")
        ctx_item = ctx.get("mission_item_id") or ctx.get("item_id")
        if payload_id == approval_id or (ctx_ws == name and ctx_item == item.get("id")):
            return payload
    return None


def _approval_matches_item(approval: dict, name: str, item_id: str) -> bool:
    ctx = approval.get("context") or {}
    return (
        (ctx.get("workstream_name") or ctx.get("workstream")) == name
        and (ctx.get("mission_item_id") or ctx.get("item_id") or ctx.get("workstream_item")) == item_id
    )


class WorkstreamItemIn(BaseModel):
    id: str
    description: str
    acceptance_criteria: list[str] = Field(default_factory=list)
    priority_metric: Optional[float] = None
    case_summary: Optional[dict[str, Any]] = None
    case_insights: Optional[dict[str, Any]] = None


class WorkstreamCreate(BaseModel):
    name: str
    display_name: Optional[str] = None
    owner: str = ""
    description: str = ""
    skill: str = ""
    automation: Optional[str] = None
    priority_strategy: str = "sequential"
    max_attempts_per_item: int = 3
    # Cron-tick throughput (default 1/1 = one item per tick); raise when items are independent.
    batch_size: int = Field(default=1, ge=1, le=100,
                             description="Items processed per cron tick. 1 = strict sequential.")
    parallelism: int = Field(default=1, ge=1, le=10,
                              description="Max concurrent workers per cron tick. Capped at batch_size.")
    items: list[WorkstreamItemIn] = Field(default_factory=list)
    items_source: Optional[dict] = None     # see items_source.py for shape
    escalation: list[dict] = Field(default_factory=list)
    business_lens: Optional[dict[str, Any]] = None
    business_metrics: Optional[list[dict[str, Any]]] = None
    meta: Optional[dict] = None             # lineage / provenance — read by hook handler
    tenant_id: str = DEFAULT_TENANT_ID
    # Optional: auto-create a cron job pointing at the mission_mode skill
    cron_schedule: Optional[str] = "*/5 * * * *"   # set None to skip cron provisioning
    cron_user_id: Optional[str] = None             # required if cron_schedule given


class WorkstreamPatch(BaseModel):
    display_name: Optional[str] = None
    owner: Optional[str] = None
    description: Optional[str] = None
    skill: Optional[str] = None
    automation: Optional[str] = None
    status: Optional[str] = None             # active | paused | completed | failed
    priority_strategy: Optional[str] = None
    max_attempts_per_item: Optional[int] = None
    batch_size: Optional[int] = Field(default=None, ge=1, le=100)
    parallelism: Optional[int] = Field(default=None, ge=1, le=10)
    items_source: Optional[dict] = None
    escalation: Optional[list[dict]] = None
    business_lens: Optional[dict[str, Any]] = None
    business_metrics: Optional[list[dict[str, Any]]] = None
    cron_schedule: Optional[str] = None
    cron_user_id: Optional[str] = None
    cron_job_id: Optional[str] = None


class WorkstreamItemChatRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=4000)
    action: Optional[str] = None
    skill_name: Optional[str] = Field(default=None, max_length=120)


class WorkstreamChatRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=3000)
    action: Optional[str] = None


class WorkstreamItemActionRequest(BaseModel):
    action_type: str = Field(..., min_length=1, max_length=40)
    reason: str = Field(default="", max_length=1000)
    payload: dict[str, Any] = Field(default_factory=dict)


class ItemsSourcePreview(BaseModel):
    items_source: dict
    tenant_id: str = DEFAULT_TENANT_ID


@router.get("/api/workstreams")
async def list_workstreams(request: Request, tenant_id: str = DEFAULT_TENANT_ID, status: Optional[str] = None,
                            owner: Optional[str] = None):
    _principal, tenant_id, _agent_id, _user_id = _scope_workstream(
        request, tenant_id=tenant_id, action="read", resource_id="*"
    )
    summaries = _store(tenant_id).list_summaries()
    if status:
        summaries = [s for s in summaries if s.get("status") == status]
    if owner:
        summaries = [s for s in summaries if s.get("owner") == owner]
    return {"workstreams": summaries, "total": len(summaries)}


@router.post("/api/workstreams")
async def create_workstream(payload: WorkstreamCreate, request: Request):
    principal, payload.tenant_id, _agent_id, _user_id = _scope_workstream(
        request,
        tenant_id=payload.tenant_id,
        action="write",
        resource_id=payload.name,
    )
    ws_dict = payload.model_dump(exclude={"tenant_id", "cron_schedule", "cron_user_id"})
    ws_dict["display_name"] = ws_dict.get("display_name") or ws_dict["name"]
    ws_dict["created_at"] = now_iso()
    ws_dict["status"] = "active"

    errors = validate_workstream(ws_dict)
    if errors:
        raise HTTPException(status_code=400, detail={"errors": errors})

    store = _store(payload.tenant_id)
    if store.exists(payload.name):
        raise HTTPException(status_code=409, detail=f"workstream {payload.name!r} already exists")

    meta = payload.meta or {}

    # Stamp parent_user_id from the authenticated caller; an agent-supplied value must never redirect a synthesis report.
    if meta.get("source") == "research_orchestrator":
        caller_id = (
            principal.email
            or principal.user_id
            or meta.get("parent_user_id")
            or payload.owner
            or ""
        )
        if caller_id:
            meta["parent_user_id"] = caller_id
        # Persisted copy of meta lives on ws_dict — keep them in sync.
        ws_dict["meta"] = meta

    # Fire OnResearchWorkstreamCreated before persisting for orchestrator-sourced payloads; a blocking handler can deny.
    if meta.get("source") == "research_orchestrator":
        try:
            from shared.state import capability_registry as _cap
            from iaf_agent_skills.hook_runner import HookRunner  # type: ignore
            # Reuse the agent's singleton HookRunner (capability 'hook_runner') or a transient instance.
            hr = getattr(_cap.get("hook_runner") if hasattr(_cap, "get") else None, "instance", None)
            if hr is None:
                hr = HookRunner({})
            target_skills = sorted({
                target
                for it in (ws_dict.get("items") or [])
                if isinstance(it, dict)
                for target in [it.get("worker_skill") or payload.skill or payload.automation or ""]
                if target
            })
            gate = hr.run_on_research_workstream_created(
                session_ctx={
                    "session_id": meta.get("parent_session_id") or "",
                    "trace_id": meta.get("parent_trace_id") or "",
                    "tenant_id": payload.tenant_id,
                    "user_id": payload.owner or "",
                    "current_skill": "research_orchestrator",
                },
                workstream_name=payload.name,
                source_question=ws_dict.get("description") or "",
                parent_session_id=meta.get("parent_session_id") or "",
                parent_trace_id=meta.get("parent_trace_id") or "",
                item_count=len(ws_dict.get("items") or []),
                estimated_cost_usd=float(meta.get("estimated_cost_usd") or 0.0),
                target_skills=target_skills,
                decomposer_confidence=meta.get("decomposer_confidence") or "",
            )
            if gate and getattr(gate, "blocked", False):
                raise HTTPException(
                    status_code=403,
                    detail=f"OnResearchWorkstreamCreated hook denied: "
                           f"{getattr(gate, 'reason', 'no reason')}",
                )
        except HTTPException:
            raise
        except Exception as hook_err:
            logger.debug("OnResearchWorkstreamCreated hook fire skipped: %s", hook_err)

    # Validate cron config before persisting, else a bad request leaves a half-created workstream.
    if payload.cron_schedule and not payload.cron_user_id:
        raise HTTPException(status_code=400,
                            detail="cron_user_id is required when cron_schedule is set")

    store.save(ws_dict)

    # Optionally provision a cron job pointing at the mission_mode skill
    cron_info = None
    if payload.cron_schedule:
        cron_info = _provision_cron(payload, store)

    return {"workstream": store.load(payload.name), "cron": cron_info}


def _validate_source_shape(source: dict) -> list[str]:
    """Format-level checks per source type, returning clear messages.

    Runs before the live probe so obvious mistakes (missing URL, non-SELECT
    query, empty directory path) get a precise message even when the external
    system is unreachable.
    """
    if not isinstance(source, dict):
        return ["items_source must be an object"]
    stype = str(source.get("type") or "").strip()
    if not stype:
        return ["Source type is required"]
    if stype not in ("sql", "http", "directory", "skill"):
        return [f"Unsupported source type {stype!r}"]

    errors: list[str] = []
    if stype == "sql":
        if not str(source.get("database") or "").strip():
            errors.append("SQL source needs a database name")
        query = str(source.get("query") or "").strip()
        if not query:
            errors.append("SQL source needs a SELECT query")
        elif not query.lower().lstrip().startswith("select"):
            errors.append("SQL query must be a read-only SELECT")
    elif stype == "http":
        url = str(source.get("url") or "").strip()
        if not url:
            errors.append("HTTP source needs a URL")
        elif not (url.startswith("http://") or url.startswith("https://")):
            errors.append("HTTP source URL must start with http:// or https://")
    elif stype == "directory":
        if not str(source.get("path") or "").strip():
            errors.append("Directory source needs a path")
    elif stype == "skill":
        if not str(source.get("skill") or "").strip():
            errors.append("Skill source needs a skill")
        if not str(source.get("query") or "").strip():
            errors.append("Skill source needs a query")
    return errors


@router.post("/api/workstreams/preview-source")
async def preview_items_source(payload: ItemsSourcePreview, request: Request):
    """Validate and dry-run a workstream ``items_source`` before the workstream
    is saved.

    The New Workstream page calls this so a broken auto-source (wrong URL,
    missing database, bad directory path, empty query result) is caught upfront
    with a clear message, instead of silently creating a workstream that shows
    0 items after its first cron tick.
    """
    _principal, tenant_id, _agent_id, _user_id = _scope_workstream(
        request, tenant_id=payload.tenant_id, action="write", resource_id="*"
    )
    source = payload.items_source or {}
    shape_errors = _validate_source_shape(source)
    if shape_errors:
        return {"ok": False, "count": 0, "errors": shape_errors, "sample": []}

    stype = str(source.get("type") or "")
    if stype == "skill":
        return {
            "ok": True,
            "count": None,
            "errors": [],
            "sample": [],
            "note": "Skill sources are resolved on the first cron tick; the config looks valid.",
        }

    from iaf_agent_skills.items_source import SourceBlocked as _SourceBlocked
    try:
        from iaf_agent_skills.items_source import resolve as _resolve_source
        items = _resolve_source(
            source, tenant_root=_tenant_root(tenant_id), tenant_id=tenant_id
        )
    except _SourceBlocked:
        raise HTTPException(status_code=400, detail="Source URL or credential use is blocked by egress policy")
    except ValueError as exc:
        return {"ok": False, "count": 0, "errors": [str(exc)], "sample": []}
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning("items_source preview failed: %s", exc)
        return {"ok": False, "count": 0, "errors": ["Source probe failed"], "sample": []}

    count = len(items)
    if count == 0:
        hint = {
            "sql": "The query ran but returned no rows — check the database name, table, and WHERE clause.",
            "http": "The endpoint returned no items — check the URL, credential, and items_path.",
            "directory": "No files matched — check the path and glob pattern.",
        }.get(stype, "The source returned no items — check the configuration.")
        return {"ok": False, "count": 0, "errors": [hint], "sample": []}

    sample = [
        {"id": it.get("id"), "description": _bounded_text(it.get("description"), 160)}
        for it in items[:5]
        if isinstance(it, dict)
    ]
    return {"ok": True, "count": count, "errors": [], "sample": sample}


def _provision_cron(payload: WorkstreamCreate, store: WorkstreamStore) -> dict:
    """Create the cron job that drives this workstream."""
    from iaf_agent_skills.scheduler.models import Job
    from shared.state import cron_scheduler

    job = Job(
        name=f"ws_{payload.name}",
        skill_name="mission_mode",
        task=payload.name,
        cron=payload.cron_schedule,
        description=f"Mission Mode driver for workstream '{payload.name}'",
        tenant_id=payload.tenant_id,
        agent_id="enterprise_agent",
        user_id=payload.cron_user_id,
        max_runtime_seconds=180,
        enabled=True,
        tags=["mission_mode", "workstream"],
    )
    saved = cron_scheduler.add_job(job)
    from shared import cron_read_cache
    cron_read_cache.invalidate()   # read-your-write: the Cron page reflects this at once
    store.update_workstream(payload.name, cron_job_id=saved.id)
    return saved.to_dict()


def reconcile_workstream_cron_jobs(tenant_id: str = DEFAULT_TENANT_ID) -> dict[str, Any]:
    """Ensure YAML-declared workstream schedules exist in the cron scheduler.

    Workstreams can be restored from demo packs, git, or backups with
    ``cron_schedule`` metadata but without a live scheduler row. Reconcile those
    declarations on startup so the Cron Jobs page reflects scheduled workstreams
    after Redis resets or server restarts.
    """
    from iaf_agent_skills.scheduler.models import Job
    from shared.state import cron_scheduler

    store = _store(tenant_id)
    repaired: list[dict[str, Any]] = []
    skipped: list[dict[str, str]] = []

    for summary in store.list_summaries():
        name = str(summary.get("name") or "").strip()
        if not name:
            continue
        try:
            ws = store.load(name)
        except Exception as exc:
            skipped.append({"workstream": name, "reason": f"load failed: {exc}"})
            continue

        cron_schedule = str(ws.get("cron_schedule") or "").strip()
        if not cron_schedule:
            continue
        cron_user_id = str(ws.get("cron_user_id") or "").strip()
        if not cron_user_id:
            skipped.append({"workstream": name, "reason": "cron_user_id missing"})
            continue

        job_name = f"ws_{name}"
        existing = None
        cron_job_id = str(ws.get("cron_job_id") or "").strip()
        if cron_job_id:
            existing = cron_scheduler.get_job(cron_job_id)
        if existing is None:
            existing = cron_scheduler.get_job_by_name(job_name, tenant_id)

        enabled = str(ws.get("status") or "active") == "active"
        if existing is not None:
            existing.name = job_name
            existing.skill_name = "mission_mode"
            existing.task = name
            existing.cron = cron_schedule
            existing.tenant_id = tenant_id
            existing.agent_id = "enterprise_agent"
            existing.user_id = cron_user_id
            existing.max_runtime_seconds = int(ws.get("cron_max_runtime_seconds") or 180)
            existing.enabled = enabled
            existing.description = f"Mission Mode driver for workstream '{name}'"
            existing.tags = sorted(set([*(existing.tags or []), "mission_mode", "workstream", "reconciled"]))
            existing.next_run_at = None
            saved = cron_scheduler.add_job(existing)
            action = "updated"
        else:
            saved = cron_scheduler.add_job(Job(
                name=job_name,
                skill_name="mission_mode",
                task=name,
                cron=cron_schedule,
                description=f"Mission Mode driver for workstream '{name}'",
                tenant_id=tenant_id,
                agent_id="enterprise_agent",
                user_id=cron_user_id,
                max_runtime_seconds=int(ws.get("cron_max_runtime_seconds") or 180),
                enabled=enabled,
                tags=["mission_mode", "workstream", "reconciled"],
            ))
            action = "created"

        if ws.get("cron_job_id") != saved.id:
            store.update_workstream(name, cron_job_id=saved.id)
        repaired.append({
            "workstream": name,
            "job_id": saved.id,
            "job_name": saved.name,
            "cron": saved.cron,
            "enabled": saved.enabled,
            "action": action,
        })

    logger.info(
        "Workstream cron reconcile: %s repaired, %s skipped",
        len(repaired),
        len(skipped),
    )
    if repaired:
        from shared import cron_read_cache
        cron_read_cache.invalidate()   # reconcile mutated the scheduler → drop stale reads
    return {"repaired": repaired, "skipped": skipped, "total": len(repaired)}


# Must stay above '/{name}': FastAPI matches in declaration order.
@router.get("/api/workstreams/capabilities")
async def workstream_capabilities(request: Request, tenant_id: str = DEFAULT_TENANT_ID):
    """Report what the calling principal may do to workstreams.

    Lets the browser derive control visibility from the tenant entitlement policy
    instead of hard-coding a role. The Delete control previously keyed off
    `role === 'admin'`, which is wrong in both directions: the shipped policy
    grants delete to `user` and `manager` too, and re-hardcoding "not auditor"
    would drift again the next time the policy changes.

    Deliberately authenticated-but-not-entitlement-gated: it reports a decision
    rather than performing an action, so gating it on one of the actions it
    reports would make an unprivileged caller unable to discover that they are
    unprivileged.
    """
    from security.dependencies import bind_request_identity
    from security.provider import Resource, get_entitlement_provider

    principal, tenant_id, _agent_id, _user_id = bind_request_identity(
        request, requested_tenant=tenant_id
    )
    provider = get_entitlement_provider()
    resource = Resource("workstream", "*", tenant_id=tenant_id)

    return {
        action: bool(provider.check(principal, action, resource).allowed)
        for action in ("read", "write", "delete")
    }


@router.get("/api/workstreams/{name}")
async def get_workstream(name: str, request: Request, tenant_id: str = DEFAULT_TENANT_ID):
    _principal, tenant_id, _agent_id, _user_id = _scope_workstream(
        request, tenant_id=tenant_id, action="read", resource_id=name
    )
    try:
        return _store(tenant_id).load(name)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"workstream {name!r} not found")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.patch("/api/workstreams/{name}")
async def patch_workstream(name: str, patch: WorkstreamPatch, request: Request,
                            tenant_id: str = DEFAULT_TENANT_ID):
    _principal, tenant_id, _agent_id, _user_id = _scope_workstream(
        request, tenant_id=tenant_id, action="write", resource_id=name
    )
    fields = {k: v for k, v in patch.model_dump().items() if v is not None}
    if not fields:
        raise HTTPException(status_code=400, detail="no fields to update")

    store = _store(tenant_id)

    # On re-pointing, confirm the skill exists (validate_workstream only checks non-empty); outside the lock since it touches the skill provider.
    if "skill" in fields and fields["skill"]:
        _assert_skill_exists(str(fields["skill"]))

    # Check inside the write lock against the document being persisted, so concurrent patches cannot validate stale state.
    def _check(current: dict, merged: dict) -> None:
        # Enforce the execution-field lock the edit UI shows; a direct PATCH must not re-point a running workstream.
        changing = [
            f for f in _EXECUTION_FIELDS
            if f in fields and merged.get(f) != current.get(f)
        ]
        if changing and str(current.get("status", "")) not in _EXECUTION_EDITABLE_STATES:
            raise HTTPException(
                status_code=409,
                detail={
                    "errors": [
                        f"cannot change {', '.join(sorted(changing))} while the workstream "
                        f"is {current.get('status')!r}; pause it first"
                    ]
                },
            )

        # Run validate_workstream() as create does; update_workstream() assigns fields blindly.
        errors = validate_workstream(merged)
        if errors:
            raise HTTPException(status_code=400, detail={"errors": errors})

    try:
        return store.update_workstream(name, validator=_check, **fields)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"workstream {name!r} not found")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.delete("/api/workstreams/{name}")
async def delete_workstream(name: str, request: Request, tenant_id: str = DEFAULT_TENANT_ID,
                             also_delete_cron: bool = True):
    _principal, tenant_id, _agent_id, _user_id = _scope_workstream(
        request, tenant_id=tenant_id, action="delete", resource_id=name
    )
    store = _store(tenant_id)
    cron_id = None
    if also_delete_cron:
        try:
            ws = store.load(name)
            cron_id = ws.get("cron_job_id")
        except FileNotFoundError:
            pass
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
    try:
        deleted = store.delete(name)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    if not deleted:
        raise HTTPException(status_code=404, detail=f"workstream {name!r} not found")
    cron_removed = None
    cron_warning = None
    if cron_id:
        # Use delete_job(); CronScheduler has no remove_job.
        try:
            from shared.state import cron_scheduler
            if cron_scheduler.delete_job(cron_id):
                cron_removed = cron_id
                from shared import cron_read_cache
                cron_read_cache.invalidate()   # paired schedule removed → refresh reads
        except Exception as exc:
            logger.warning("could not delete paired cron %s: %s", cron_id, exc)
        if cron_removed is None:
            cron_warning = (
                f"workstream deleted, but its paired schedule {cron_id} could not be "
                f"removed and may still fire — remove it from the Cron page"
            )
            logger.warning(cron_warning)
    return {"deleted": name, "cron_removed": cron_removed, "cron_warning": cron_warning}


@router.post("/api/workstreams/{name}/pause")
async def pause_workstream(name: str, request: Request, tenant_id: str = DEFAULT_TENANT_ID):
    _principal, tenant_id, _agent_id, _user_id = _scope_workstream(
        request, tenant_id=tenant_id, action="write", resource_id=name
    )
    try:
        return _store(tenant_id).update_workstream(name, status="paused")
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"workstream {name!r} not found")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/api/workstreams/{name}/resume")
async def resume_workstream(name: str, request: Request, tenant_id: str = DEFAULT_TENANT_ID):
    _principal, tenant_id, _agent_id, _user_id = _scope_workstream(
        request, tenant_id=tenant_id, action="write", resource_id=name
    )
    try:
        return _store(tenant_id).update_workstream(name, status="active")
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"workstream {name!r} not found")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/api/workstreams/{name}/cancel")
async def cancel_workstream(name: str, request: Request, tenant_id: str = DEFAULT_TENANT_ID):
    _principal, tenant_id, _agent_id, _user_id = _scope_workstream(
        request, tenant_id=tenant_id, action="write", resource_id=name
    )
    try:
        result = _store(tenant_id).update_workstream(name, status="failed", completed_at=now_iso())
        _record_workstream_reward_best_effort(
            tenant_id=tenant_id,
            workstream_name=name,
            raw_label="cancelled",
            metadata={"source": "workstream_cancel"},
        )
        return result
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"workstream {name!r} not found")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/api/workstreams/{name}/items")
async def append_item(name: str, item: WorkstreamItemIn,
                       request: Request,
                       tenant_id: str = DEFAULT_TENANT_ID):
    _principal, tenant_id, _agent_id, _user_id = _scope_workstream(
        request, tenant_id=tenant_id, action="write", resource_id=name
    )
    try:
        return _store(tenant_id).append_item(name, item.model_dump())
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"workstream {name!r} not found")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/api/workstreams/{name}/items/{item_id}/retry")
async def retry_item(name: str, item_id: str, request: Request, tenant_id: str = DEFAULT_TENANT_ID):
    _principal, tenant_id, _agent_id, _user_id = _scope_workstream(
        request, tenant_id=tenant_id, action="write", resource_id=name
    )
    try:
        result = _store(tenant_id).update_item(
            name, item_id,
            status="pending",
            attempts=0,
            resolution=None,
            escalated_approval_id=None,
        )
        _record_workstream_reward_best_effort(
            tenant_id=tenant_id,
            workstream_name=name,
            item_id=item_id,
            raw_label="retry",
            metadata={"source": "workstream_item_retry"},
        )
        return result
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"workstream {name!r} not found")
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@router.post("/api/workstreams/{name}/items/{item_id}/skip")
async def skip_item(name: str, item_id: str,
                     request: Request,
                     tenant_id: str = DEFAULT_TENANT_ID,
                     reason: str = "manually skipped"):
    _principal, tenant_id, _agent_id, _user_id = _scope_workstream(
        request, tenant_id=tenant_id, action="write", resource_id=name
    )
    try:
        result = _store(tenant_id).update_item(
            name, item_id,
            status="done",
            resolution=f"SKIPPED: {reason}",
        )
        _record_workstream_reward_best_effort(
            tenant_id=tenant_id,
            workstream_name=name,
            item_id=item_id,
            raw_label="skipped",
            notes=reason,
            metadata={"source": "workstream_item_skip"},
        )
        return result
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"workstream {name!r} not found")
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@router.post("/api/workstreams/{name}/items/{item_id}/actions")
async def run_item_action(
    name: str,
    item_id: str,
    request: Request,
    body: WorkstreamItemActionRequest,
    tenant_id: str = DEFAULT_TENANT_ID,
):
    _principal, tenant_id, _agent_id, _user_id = _scope_workstream(
        request, tenant_id=tenant_id, action="write", resource_id=name
    )
    store = _store(tenant_id)
    try:
        ws = store.load(name)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"workstream {name!r} not found")

    item = _find_item(ws, item_id)
    if item is None:
        raise HTTPException(status_code=404, detail=f"item {item_id!r} not found in workstream {name!r}")

    raw_action = body.action_type.strip().lower()
    action_type = ITEM_ACTION_ALIASES.get(raw_action, raw_action)
    if action_type not in VALID_ITEM_ACTION_TYPES:
        raise HTTPException(status_code=400, detail=f"unsupported action_type {body.action_type!r}")

    actor = _request_actor(request)
    reason = body.reason.strip() or "manual action"
    action_id = f"wsa_{uuid.uuid4().hex[:12]}"
    requested_at = now_iso()
    side_effect = action_type in {"retry", "correct", "email", "post", "resend"}
    patches: dict[str, Any] = {}
    event_status = "completed"
    side_effect_blocked = False

    if action_type in BLOCKED_CONNECTOR_ACTIONS:
        event_status = "blocked"
        side_effect_blocked = True
        result = (
            f"Action {action_type!r} is governed but no connector/policy-backed executor is configured yet. "
            "Use item chat for analysis, or configure a dedicated action executor before external side effects run."
        )
    elif action_type == "retry":
        result = f"Item {item_id} reset to pending for governed retry."
        patches.update({
            "status": "pending",
            "attempts": 0,
            "resolution": None,
            "escalated_approval_id": None,
            "last_failure_reason": None,
            "closed_at": None,
            "closed_by": None,
            "suggested_actions": _suggested_actions_for_item_status("pending"),
        })
    elif action_type == "skip":
        result = f"Item {item_id} skipped: {reason}"
        patches.update({
            "status": "done",
            "resolution": f"SKIPPED: {reason}",
            "suggested_actions": _suggested_actions_for_item_status("done"),
        })
    elif action_type == "mark_done":
        result = f"Item {item_id} marked done by {actor}: {reason}"
        patches.update({
            "status": "done",
            "resolution": f"Marked done by {actor}: {reason}",
            "closed_at": requested_at,
            "closed_by": actor,
            "escalated_approval_id": None,
            "last_approval_context": None,
            "suggested_actions": _suggested_actions_for_item_status("done"),
        })
    elif action_type == "close":
        if item.get("status") not in {"done", "failed"}:
            event_status = "blocked"
            side_effect_blocked = True
            result = f"Item {item_id} must be done or failed before it can be closed."
        else:
            result = f"Item {item_id} closed by {actor}."
            patches.update({
                "closed_at": requested_at,
                "closed_by": actor,
            })

    event = {
        "action_id": action_id,
        "action_type": action_type,
        "requested_by": actor,
        "requested_at": requested_at,
        "status": event_status,
        "side_effect": side_effect,
        "reason": reason,
        "result": result,
    }

    try:
        refreshed = store.append_item_action_event(name, item_id, event, **patches)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))

    refreshed_item = _find_item(refreshed, item_id) or item
    _record_workstream_reward_best_effort(
        tenant_id=tenant_id,
        workstream_name=name,
        item_id=item_id,
        raw_label=f"action_{event_status}",
        judge_id=actor,
        notes=result,
        metadata={
            "source": "workstream_item_action",
            "action_type": action_type,
            "side_effect": side_effect,
            "side_effect_blocked": side_effect_blocked,
        },
    )
    return {
        "workstream_name": name,
        "item_id": item_id,
        "action_id": action_id,
        "action_type": action_type,
        "status": event_status,
        "side_effect_blocked": side_effect_blocked,
        "result": result,
        "item": _compact_item_context(refreshed_item),
    }


@router.get("/api/workstreams/{name}/items/{item_id}/context")
async def get_item_context(
    name: str,
    item_id: str,
    request: Request,
    tenant_id: str = DEFAULT_TENANT_ID,
):
    _principal, tenant_id, _agent_id, _user_id = _scope_workstream(
        request, tenant_id=tenant_id, action="read", resource_id=name
    )
    try:
        ws = _store(tenant_id).load(name)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"workstream {name!r} not found")

    item = _find_item(ws, item_id)
    if item is None:
        raise HTTPException(status_code=404, detail=f"item {item_id!r} not found in workstream {name!r}")

    return {
        "workstream": {
            "name": ws.get("name"),
            "display_name": ws.get("display_name") or ws.get("name"),
            "status": ws.get("status"),
            "skill": ws.get("skill"),
            "automation": ws.get("automation"),
            "owner": ws.get("owner", ""),
        },
        "item": _compact_item_context(item),
        "runtime_executions": _runtime_executions(name, item_id),
        "approval": await _pending_approval_for_item(tenant_id, name, item),
    }


@router.get("/api/workstreams/{name}/items/{item_id}/executions")
async def get_item_executions(
    name: str,
    item_id: str,
    request: Request,
    tenant_id: str = DEFAULT_TENANT_ID,
):
    _principal, tenant_id, _agent_id, _user_id = _scope_workstream(
        request, tenant_id=tenant_id, action="read", resource_id=name
    )
    try:
        ws = _store(tenant_id).load(name)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"workstream {name!r} not found")

    item = _find_item(ws, item_id)
    if item is None:
        raise HTTPException(status_code=404, detail=f"item {item_id!r} not found in workstream {name!r}")

    return {
        "workstream_name": name,
        "item_id": item_id,
        "current_execution_id": item.get("current_execution_id"),
        "runtime_executions": _runtime_executions(name, item_id),
    }


@router.post("/api/workstreams/{name}/items/{item_id}/chat")
async def chat_item(
    name: str,
    item_id: str,
    request: Request,
    body: WorkstreamItemChatRequest,
    tenant_id: str = DEFAULT_TENANT_ID,
):
    _principal, tenant_id, _agent_id, _user_id = _scope_workstream(
        request, tenant_id=tenant_id, action="write", resource_id=name
    )
    store = _store(tenant_id)
    try:
        ws = store.load(name)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"workstream {name!r} not found")

    item = _find_item(ws, item_id)
    if item is None:
        raise HTTPException(status_code=404, detail=f"item {item_id!r} not found in workstream {name!r}")

    session_id = item.get("chat_session_id") or _item_chat_session_id(name, item_id)
    message = body.message.strip()
    side_effect_blocked = False
    result_summary = item.get("last_result_summary") or item.get("resolution") or "No result summary is available yet."

    requested_skill = (body.skill_name or "").strip()
    selected_skill = requested_skill or (ws.get("skill") or "")
    prompt = _build_item_chat_prompt(ws, item, message, selected_skill)
    chat_result = await _run_item_chat_via_existing_chat(
        request,
        tenant_id=tenant_id,
        session_id=session_id,
        skill_name=selected_skill,
        prompt=prompt,
        workstream_name=name,
        item_id=item_id,
    )
    response = chat_result.get("response") or chat_result.get("content") or ""
    if not response:
        response = (
            f"Item {item_id} is {item.get('status', 'pending')}. "
            f"Last result: {_bounded_text(result_summary, 480)}"
        )

    now = now_iso()
    preview = list(item.get("chat_transcript_preview") or [])
    preview.append({
        "at": now,
        "message": _bounded_text(message, ITEM_CHAT_MESSAGE_LIMIT),
        "response": _bounded_text(response, ITEM_CHAT_RESPONSE_LIMIT),
        "action": body.action or "chat",
        "skill": selected_skill,
        "side_effect_blocked": side_effect_blocked,
    })
    preview = preview[-ITEM_CHAT_PREVIEW_LIMIT:]

    patches: dict[str, Any] = {
        "chat_session_id": session_id,
        "chat_last_message_at": now,
        "chat_transcript_preview": preview,
    }
    hitl_approval = chat_result.get("hitl_approval") or {}
    approval_id = hitl_approval.get("approval_id")
    if approval_id:
        if _approval_matches_item(hitl_approval, name, item_id):
            patches.update({
                "status": "awaiting_human",
                "escalated_approval_id": approval_id,
                "last_approval_context": hitl_approval.get("context") or {},
                "last_result_summary": _bounded_text(response, ITEM_CONTEXT_RESULT_LIMIT),
                "last_result_at": now,
                "suggested_actions": _suggested_actions_for_item_status("awaiting_human"),
            })
        else:
            logger.warning(
                "Ignoring mismatched HITL approval returned to item chat: current=%s/%s approval=%s context=%s",
                name,
                item_id,
                approval_id,
                hitl_approval.get("context") or {},
            )
            hitl_approval = {}

    store.update_item(name, item_id, **patches)
    if approval_id:
        _record_workstream_reward_best_effort(
            tenant_id=tenant_id,
            workstream_name=name,
            item_id=item_id,
            trace_id=str(chat_result.get("evidence_trace_id") or ""),
            raw_label="awaiting_human",
            notes=response,
            metadata={"source": "workstream_item_chat", "approval_id": approval_id},
        )

    refreshed = store.load(name)
    refreshed_item = _find_item(refreshed, item_id) or item
    return {
        "workstream_name": name,
        "item_id": item_id,
        "chat_session_id": session_id,
        "response": response,
        "side_effect_blocked": side_effect_blocked,
        "chat_backend": "api_chat",
        "chat_skill": chat_result.get("skill") or selected_skill,
        "hitl_approval": hitl_approval or None,
        "evidence_trace_id": chat_result.get("evidence_trace_id"),
        "item": _compact_item_context(refreshed_item),
    }


def _business_stage_rows(name: str, item_id: str, limit: int = 12) -> list[dict[str, str]]:
    """The per-stage business conclusions from the newest run, without the progress chatter.

    Domain-agnostic: a stage row is one named exactly after a workflow step (no "a / b"
    composite, no "Step 3/9:" counter) whose output is real text rather than a status word.
    """
    progress_words = {"running", "active", "completed", "pending", "success", ""}
    rows: list[dict[str, str]] = []
    seen: dict[str, dict[str, str]] = {}
    for run in _runtime_executions(name, item_id, limit=1):
        for step in run.get("steps") or []:
            step_name = str(step.get("step_name") or "").strip()
            output = str(step.get("output") or step.get("output_preview") or "").strip()
            if not step_name or "/" in step_name or ":" in step_name:
                continue
            if output.lower() in progress_words or output.startswith(("Running", "Step ")):
                continue
            if "💭" in output or "🔧" in output:
                continue
            seen[step_name] = {"stage": step_name, "conclusion": _bounded_text(output, 700)}
    rows = list(seen.values())[:limit]
    return rows


_INSIGHTS_PROMPT = """You are a finance/operations analyst briefing a BUSINESS colleague about ONE case.

CASE
{case_block}

WHAT THE PROCESS RECORDED, STAGE BY STAGE
{stage_block}

Write insights about the CASE AND THE BUSINESS — the invoice/order/account itself, the
counterparty, the money at risk, the control that fired, and how to stop this recurring.

ABSOLUTE RULES
- Your reader is a business user (AP manager, controller, analyst). Write in their language.
- NEVER mention agents, AI, models, prompts, skills, steps, hooks, retries, workflows,
  automation internals, or this system. If a control or approval mattered, describe it in
  business terms ("a controller waived the goods-receipt requirement"), never mechanically.
- Ground every statement in the case facts above. Do not invent amounts, dates or vendors.
- If you genuinely have nothing for a section, return an empty list for it.

Return ONLY a JSON object, no prose, with exactly these keys:
{{
  "current_findings": ["short factual statements about this case"],
  "recommendation_reasoning": ["why the recommended business action is the right one"],
  "historical_patterns": [{{"label": "short pattern name", "explanation": "what it means for the business"}}],
  "prevention_opportunities": ["concrete process/control changes that would prevent a repeat"],
  "similar_cases": [{{"id": "case id or type", "summary": "why it is similar", "outcome": "how it ended"}}]
}}
Keep each string under 220 characters. 2-4 entries per list."""


@router.post("/api/workstreams/{name}/items/{item_id}/insights")
async def generate_item_insights(
    name: str,
    item_id: str,
    request: Request,
    tenant_id: str = DEFAULT_TENANT_ID,
):
    """Generate business insights for one item from its recorded stage outcomes, and persist
    them to case_insights so the Insights & Patterns panel keeps them across reloads."""
    _principal, tenant_id, _agent_id, _user_id = _scope_workstream(
        request, tenant_id=tenant_id, action="write", resource_id=name
    )
    store = _store(tenant_id)
    try:
        ws = store.load(name)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"workstream {name!r} not found")
    item = _find_item(ws, item_id)
    if item is None:
        raise HTTPException(status_code=404, detail=f"item {item_id!r} not found in workstream {name!r}")

    stages = _business_stage_rows(name, item_id)
    outcome = item.get("resolution") or item.get("last_result_summary") or ""
    if not stages and not outcome:
        raise HTTPException(
            status_code=409,
            detail="This item has not produced any recorded outcome yet — run it first.",
        )

    summary = item.get("case_summary") if isinstance(item.get("case_summary"), dict) else {}
    case_lines = [f"Item id: {item_id}", f"Status: {item.get('status') or 'pending'}"]
    for key in ("title", "case_type", "primary_entity", "impact_label", "impact_value",
                "policy_trigger", "recommended_action", "risk_level", "category"):
        if summary.get(key):
            case_lines.append(f"{key.replace('_', ' ').title()}: {summary[key]}")
    if item.get("description"):
        case_lines.append(f"Description: {_bounded_text(item['description'], 400)}")
    if outcome:
        case_lines.append(f"Final outcome recorded: {_bounded_text(outcome, 600)}")

    stage_block = "\n".join(f"- {r['stage']}: {r['conclusion']}" for r in stages) or "(no stage detail recorded)"
    prompt = _INSIGHTS_PROMPT.format(case_block="\n".join(case_lines), stage_block=stage_block)

    chat_result = await _run_item_chat_via_existing_chat(
        request,
        tenant_id=tenant_id,
        session_id=f"{_item_chat_session_id(name, item_id)}_insights",
        # Not the workstream's own skill (the orchestrator): pinning it re-executes the workflow instead of answering.
        skill_name="",
        prompt=prompt,
        workstream_name=name,
        item_id=item_id,
    )
    raw = chat_result.get("response") or chat_result.get("content") or ""

    try:
        from iaf_agent_skills.mission_engine import _extract_json_object
        parsed = _extract_json_object(raw)
    except Exception:
        parsed = None
    if not isinstance(parsed, dict):
        logger.warning("Insights for %s/%s: no JSON object in response: %s",
                       name, item_id, _bounded_text(raw, 400))
        raise HTTPException(status_code=502, detail="Could not read insights from the model response.")

    insights = _compact_case_insights(parsed)
    if not any(insights.get(k) for k in insights):
        logger.warning("Insights for %s/%s: parsed JSON had no usable lists (keys=%s): %s",
                       name, item_id, sorted(parsed), _bounded_text(raw, 400))
        raise HTTPException(status_code=502, detail="The model returned no usable insights.")

    # NB: only the five list keys survive — the read path re-applies _compact_case_insights,
    # so any extra field (e.g. a timestamp) would be stored but never returned.
    store.update_item(name, item_id, case_insights=insights)
    logger.info("Generated case insights for %s/%s (%d findings)",
                name, item_id, len(insights.get("current_findings") or []))
    return {"workstream_name": name, "item_id": item_id, "case_insights": insights}


@router.post("/api/workstreams/{name}/chat")
async def chat_workstream(
    name: str,
    request: Request,
    body: WorkstreamChatRequest,
    tenant_id: str = DEFAULT_TENANT_ID,
):
    _principal, tenant_id, _agent_id, _user_id = _scope_workstream(
        request, tenant_id=tenant_id, action="write", resource_id=name
    )
    store = _store(tenant_id)
    try:
        ws = store.load(name)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"workstream {name!r} not found")

    session_id = _workstream_chat_session_id(name)
    message = body.message.strip()
    side_effect_blocked = False

    prompt = _build_workstream_chat_prompt(ws, message)
    chat_result = await _run_item_chat_via_existing_chat(
        request,
        tenant_id=tenant_id,
        session_id=session_id,
        skill_name=ws.get("skill") or "",
        prompt=prompt,
    )
    response = chat_result.get("response") or chat_result.get("content") or ""
    if not response:
        counts = _status_counts(ws.get("items") or [])
        response = f"Workstream {name} has {len(ws.get('items') or [])} item(s): {counts}."

    now = now_iso()
    meta = dict(ws.get("meta") or {})
    preview = _workstream_chat_preview(meta)
    preview.append({
        "at": now,
        "message": _bounded_text(message, WORKSTREAM_CHAT_MESSAGE_LIMIT),
        "response": _bounded_text(response, WORKSTREAM_CHAT_RESPONSE_LIMIT),
        "action": body.action or "chat",
        "side_effect_blocked": side_effect_blocked,
    })
    meta["workstream_chat_session_id"] = session_id
    meta["workstream_chat_last_message_at"] = now
    meta["workstream_chat_transcript_preview"] = preview[-WORKSTREAM_CHAT_PREVIEW_LIMIT:]
    refreshed = store.update_workstream(name, meta=meta)

    return {
        "workstream_name": name,
        "chat_session_id": session_id,
        "response": response,
        "side_effect_blocked": side_effect_blocked,
        "chat_backend": "api_chat",
        "chat_skill": chat_result.get("skill"),
        "evidence_trace_id": chat_result.get("evidence_trace_id"),
        "workstream": _compact_workstream_chat_context(refreshed),
        "chat_transcript_preview": _workstream_chat_preview(refreshed.get("meta")),
    }


class RunNowRequest(BaseModel):
    count: int = Field(default=10, ge=1, le=100, description="Max items to drain in this call")
    parallel: int = Field(default=3, ge=1, le=10, description="Max items in flight concurrently")


# Shared by /run (drain) and /iterate (single item): keeps Mission Mode on one code path.

def _make_workstream_agent_factory(name: str, tenant_id: str, owner: str,
                                    execution_source: str):
    """Build a thread-safe SkillAgent factory for Mission Mode iteration.

    mission_engine.run_n spawns a fresh agent per concurrent slot — never
    share one across asyncio tasks because SkillAgent has per-run mutable
    state (_active_trace_id, _evidence_bundle, approval_pending) that
    would race. Each call produces a brand-new agent with the
    service-cron principal attached.
    """
    def _factory():
        from shared.config import SERVER_DIR, DATA_ROOT, SKILLS_PATH
        from agent_os import create_kernel_runtime
        from iaf_agent_skills.agent import SkillAgent
        from shared.state import trace_emitter

        kernel = create_kernel_runtime(
            data_root=str(SERVER_DIR / DATA_ROOT),
            tenant_id=tenant_id,
            agent_id="enterprise_agent",
            user_id=owner,
            require_confirmation=False,
        )
        agent = SkillAgent(
            kernel=kernel,
            skills_path=str(SERVER_DIR / SKILLS_PATH),
            user_id=owner,
            trace_emitter=trace_emitter,
            enterprise_root=str(SERVER_DIR / DATA_ROOT),
        )
        agent.auto_run = True
        agent._evidence_execution_source = execution_source

        # Attach service-cron principal — same gates as the cron path.
        try:
            from security.dependencies import make_service_principal, make_agent_entitlement_checker
            principal = make_service_principal(tenant_id, "cron", user_id=owner)
            agent.set_entitlement_context(principal, make_agent_entitlement_checker(principal))
        except Exception as ent_err:
            logger.warning(
                "Workstream agent factory: entitlement context setup failed (non-fatal): %s",
                ent_err,
            )

        return agent

    return _factory


def _run_workstream_automation(**kwargs: Any) -> dict[str, Any]:
    """Host callback used by mission_engine to run no-LLM automations."""
    from shared.automations_service import run_automation

    return run_automation(**kwargs)


async def _iterate_workstream(name: str, tenant_id: str, *,
                               count: int = 1, parallel: int = 1,
                               execution_source: str = "manual_run_now") -> list:
    """Internal helper. Drain up to ``count`` items via mission_engine.run_n.

    Returns a list of IterationResult dataclasses.

    Raises HTTPException on workstream-state errors (404 / 409) and 500
    on infrastructure failures.
    """
    try:
        ws = _store(tenant_id).load(name)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"workstream {name!r} not found")

    pending_count = sum(1 for item in ws.get("items", []) if item.get("status", "pending") == "pending")
    if ws.get("status") != "active" and pending_count > 0 and ws.get("status") in {"completed", "failed"}:
        logger.info(
            "Run-now reactivating workstream %r from status=%r because %d pending item(s) exist",
            name,
            ws.get("status"),
            pending_count,
        )
        ws = _store(tenant_id).update_workstream(name, status="active", completed_at=None)

    if ws.get("status") != "active":
        raise HTTPException(
            status_code=409,
            detail=f"workstream {name!r} status is {ws.get('status')!r} — "
                   f"only 'active' workstreams can be run. Resume it first.",
        )

    owner = ws.get("owner") or "service:cron"
    factory = _make_workstream_agent_factory(name, tenant_id, owner, execution_source)

    try:
        from iaf_agent_skills import mission_engine
    except ImportError as imp_err:
        raise HTTPException(status_code=500, detail=f"mission_engine import failed: {imp_err}")

    try:
        return await asyncio.to_thread(
            mission_engine.run_n,
            factory,
            name,
            tenant_id,
            count=count,
            parallel=parallel,
            automation_runner=_run_workstream_automation,
        )
    except Exception as exc:
        logger.exception("workstream iterate failed for %r", name)
        raise HTTPException(status_code=500, detail="An internal error occurred")


@router.post("/api/workstreams/{name}/run")
async def run_now(name: str, body: RunNowRequest, request: Request, tenant_id: str = DEFAULT_TENANT_ID):
    """Drain up to ``body.count`` items from the workstream synchronously,
    with at most ``body.parallel`` concurrent. Returns aggregated results.

    User-triggered (Run-now button on the detail page). For the
    single-item path used by the mission_mode skill, see /iterate.
    """
    _principal, tenant_id, _agent_id, _user_id = _scope_workstream(
        request, tenant_id=tenant_id, action="use", resource_id=name
    )
    results = await _iterate_workstream(
        name, tenant_id,
        count=body.count, parallel=body.parallel,
        execution_source="manual_run_now",
    )
    _record_iteration_rewards(tenant_id, results, source="manual_run_now")

    from dataclasses import asdict
    return {
        "workstream_name": name,
        "requested": {"count": body.count, "parallel": body.parallel},
        "results_count": len(results),
        "results": [asdict(r) for r in results],
    }


@router.post("/api/workstreams/{name}/iterate")
async def iterate(name: str, request: Request, tenant_id: str = DEFAULT_TENANT_ID):
    """Process up to ``batch_size`` items from the workstream per call,
    with up to ``parallelism`` workers concurrent. Both values are read
    from the workstream's YAML (defaults: 1/1, preserving the original
    single-item-per-tick behaviour for any workstream that doesn't
    explicitly opt in).

    This is the HTTP equivalent of the removed ``process_workstream_item``
    agent tool. The mission_mode skill calls this from its ReAct loop
    via shell+curl with $IAF_AGENT_SELF_AUTH_TOKEN — same code path
    as Run-now, just driven by the cron scheduler instead of a human.

    For workstreams with batch_size=1, returns a single IterationResult
    JSON (back-compat shape). For batch_size>1, returns an envelope
    {workstream_name, results_count, results: [...]}.
    """
    from dataclasses import asdict

    _principal, tenant_id, _agent_id, _user_id = _scope_workstream(
        request, tenant_id=tenant_id, action="use", resource_id=name
    )
    try:
        ws = _store(tenant_id).load(name)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"workstream {name!r} not found")
    batch = int(ws.get("batch_size", 1) or 1)
    parallelism = int(ws.get("parallelism", 1) or 1)
    parallelism = max(1, min(parallelism, batch))  # belt-and-braces

    results = await _iterate_workstream(
        name, tenant_id,
        count=batch, parallel=parallelism,
        execution_source="cron_iteration",
    )
    _record_iteration_rewards(tenant_id, results, source="cron_iteration")

    # Back-compat: single-item workstreams (the default) get the original
    # flat envelope. Batched workstreams get the multi-result envelope.
    if batch == 1:
        if not results:
            return {
                "workstream_name": name,
                "action": "nothing_pending",
                "reason": "no eligible items",
            }
        return asdict(results[0])

    return {
        "workstream_name": name,
        "config": {"batch_size": batch, "parallelism": parallelism},
        "results_count": len(results),
        "results": [asdict(r) for r in results],
    }


class WorkstreamSubscriptions:
    """One subscriber set per workstream. Mission engine pushes events here."""

    def __init__(self):
        self._subs: dict[str, set[WebSocket]] = {}
        self._lock = asyncio.Lock()

    async def add(self, name: str, ws: WebSocket) -> None:
        async with self._lock:
            self._subs.setdefault(name, set()).add(ws)

    async def remove(self, name: str, ws: WebSocket) -> None:
        async with self._lock:
            if name in self._subs:
                self._subs[name].discard(ws)
                if not self._subs[name]:
                    del self._subs[name]

    async def publish(self, name: str, event: dict) -> None:
        async with self._lock:
            targets = list(self._subs.get(name, ()))
        if not targets:
            return
        msg = json.dumps(event, default=str)
        dead: list[WebSocket] = []
        for ws in targets:
            try:
                await ws.send_text(msg)
            except Exception:
                dead.append(ws)
        for ws in dead:
            await self.remove(name, ws)

    async def publish_all(self, event: dict) -> None:
        """Used for non-targeted events (e.g. a brand-new workstream just got created)."""
        async with self._lock:
            all_targets: list[WebSocket] = []
            for v in self._subs.values():
                all_targets.extend(v)
        for ws in all_targets:
            try:
                await ws.send_text(json.dumps(event, default=str))
            except Exception:
                pass


workstream_subscriptions = WorkstreamSubscriptions()


@router.websocket("/ws/workstreams/{name}")
async def workstream_ws(websocket: WebSocket, name: str):
    tenant_id = websocket.query_params.get("tenant_id") or DEFAULT_TENANT_ID
    try:
        principal, tenant_id, _user_id = await bind_websocket_identity(
            websocket,
            requested_tenant=tenant_id,
        )
        enforce_entitlement(principal, "read", "workstream", name)
    except HTTPException as exc:
        await websocket.close(code=4403 if exc.status_code == 403 else 4401)
        return
    # WebSockets bypass AuthMiddleware (BaseHTTPMiddleware sees only the http
    # scope), so the temporary-password gate is applied explicitly here.
    from auth.middleware import account_is_disabled, password_rotation_outstanding
    # Disabled-account cutoff for the live push socket, as in the HTTP gate and /ws/chat.
    if await account_is_disabled(principal.user_id):
        await websocket.close(code=4401)
        return
    if await password_rotation_outstanding(principal.user_id):
        await websocket.close(code=4403)
        return
    await websocket.accept()
    await workstream_subscriptions.add(name, websocket)
    try:
        # On connect, send a snapshot
        try:
            snapshot = _store(tenant_id).load(name)
            await websocket.send_text(json.dumps({"type": "snapshot", "workstream": snapshot},
                                                  default=str))
        except FileNotFoundError:
            await websocket.send_text(json.dumps({"type": "error",
                                                  "reason": f"{name} not found"}))
        # Keep alive — ignore inbound; we only push
        while True:
            try:
                await asyncio.wait_for(websocket.receive_text(), timeout=30)
            except asyncio.TimeoutError:
                # heartbeat to keep connection alive
                try:
                    await websocket.send_text(json.dumps({"type": "heartbeat"}))
                except Exception:
                    break
    except WebSocketDisconnect:
        pass
    finally:
        await workstream_subscriptions.remove(name, websocket)
