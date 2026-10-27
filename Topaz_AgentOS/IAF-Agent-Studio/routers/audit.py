"""
IAF Agent Studio — Audit, Traces, History, Queue & Tasks Router

Observability endpoints for execution traces, conversation history,
lane queue status, and Redis-backed task tracking.
"""

import asyncio
import json
import logging
import re
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from auth.middleware import require_admin
from security.dependencies import require_scoped_identity
from shared.approval_scoping import effective_observability_user_id, is_admin_principal
from shared.state import state, trace_emitter, queue_manager, task_integration

logger = logging.getLogger(__name__)

router = APIRouter()

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_SAFE_ID_RE = re.compile(r"^[A-Za-z0-9_.@+-]{1,128}$")


def _safe_id(value: str, label: str) -> str:
    if value and (not _SAFE_ID_RE.match(value) or ".." in value):
        raise HTTPException(status_code=400, detail=f"Invalid {label}")
    return value


def _task_visible(task, principal, tenant_id: str, caller_user: str) -> bool:
    """Same tenant, and owned by the caller unless the caller is an admin."""
    if task.tenant_id and task.tenant_id != tenant_id:
        return False
    if is_admin_principal(principal):
        return True
    return task.user_id in {caller_user, principal.user_id, principal.email}


def _readable_user_fallback(uid: str) -> Optional[str]:
    """Best-effort readable label for a ``user_id`` that the auth store could not
    resolve (empty/unseeded store, service principals, external emails).

    Returns ``None`` for opaque *internal* ids (UUIDs / random tokens) so the UI
    keeps its neutral "Unknown user" label — the raw internal id must never be the
    only thing shown (Q4-8 / PR#68 #5). Emails and service principals are
    real-world identifiers (an email is what a person signs in with, and it is
    already surfaced in the login UI), so they are safe to display.
    """
    if not uid:
        return None
    # Emails are how people sign in — human-readable, not an internal id.
    if "@" in uid:
        return uid
    # Service / automation principals, e.g. "service_cron" / "service:cron".
    low = uid.lower()
    if low.startswith(("service_", "service:", "svc_", "svc:")):
        label = uid.split(":", 1)[-1].split("_", 1)[-1] or uid
        return f"Service ({label})"
    # Anything else (UUIDs, hex blobs, opaque tokens) stays hidden.
    return None


async def _attach_user_names(traces: list) -> list:
    """Add a readable ``user_name`` to each trace, resolved from the auth user
    store (display_name → email → neutral label). Raw internal ``user_id`` must
    never be the only thing the UI can show (Q4-8). Resolves each distinct id
    once; when the store has no record we derive a readable fallback from the id
    itself (email / service principal) and leave opaque internal ids unset so the
    UI renders its own neutral label.
    """
    ids = sorted({t.get("user_id") for t in traces if t.get("user_id")})
    if not ids:
        return traces
    names: dict = {}
    try:
        from auth.factory import get_store
        store = await get_store()
        # Resolve each distinct id once, concurrently, to avoid hundreds of serial round trips.
        recs = await asyncio.gather(*(store.get_by_id(uid) for uid in ids))
        for uid, rec in zip(ids, recs):
            if rec:
                # A record with empty display_name AND email must NOT fall back to
                # the raw internal id — use a neutral label.
                names[uid] = getattr(rec, "display_name", "") or getattr(rec, "email", "") or "Unknown user"
    except Exception as e:  # pragma: no cover - best-effort enrichment
        logger.debug(f"user-name enrichment skipped (non-fatal): {e}")
    # A separate pass so a readable fallback is applied even when the store is
    # empty or unreachable (the common case on an unseeded dev/demo box).
    for t in traces:
        uid = t.get("user_id")
        if uid in names:
            t["user_name"] = names[uid]
        elif uid:
            fallback = _readable_user_fallback(uid)
            if fallback:
                t["user_name"] = fallback
    return traces


@router.get("/api/audit")
async def get_audit_log(
    request: Request,
    tenant_id: str | None = None,
    agent_id: str = "enterprise_agent",
    user_id: str = "",
    skill: str = "",
    status: str = "",
    session_id: str = "",
    limit: int = 200,
):
    """Get execution traces (replaces legacy .audit/*.log).

    Returns traces from traces.db with optional filters.
    Each trace represents one agent request with its spans.
    """
    principal, resolved_tenant, _agent_id, caller_user = require_scoped_identity(
        request, requested_tenant=tenant_id, requested_agent=agent_id
    )
    user_id = effective_observability_user_id(principal, caller_user, user_id)
    if trace_emitter:
        traces = trace_emitter.query_traces(
            tenant=resolved_tenant,
            user_id=user_id,
            skill=skill,
            status=status,
            session_id=session_id,
            limit=limit,
        )
        return {"entries": traces}
    return {"entries": []}


@router.get("/api/traces")
async def list_traces(
    request: Request,
    tenant_id: str | None = None,
    user_id: str = "",
    skill: str = "",
    status: str = "",
    session_id: str = "",
    since: str = "",
    limit: int = 200,
    offset: int = 0,
    skills: list[str] = Query(default=[]),
    users: list[str] = Query(default=[]),
):
    """List execution traces with optional filters and pagination.

    ``skills``/``users`` are the multi-select dropdown filters (repeatable query
    params). ``skill``/``user_id`` remain the legacy single free-text filters.
    """
    principal, resolved_tenant, _agent_id, caller_user = require_scoped_identity(
        request, requested_tenant=tenant_id
    )
    user_id = effective_observability_user_id(principal, caller_user, user_id)
    # Only admins get fuzzy user filtering; a non-admin's user_id stays pinned to their own id.
    fuzzy_user = is_admin_principal(principal)
    # Never honor a cross-user multi-select from a non-admin; it would leak other users' traces.
    eff_users = [u for u in (users or []) if u] if fuzzy_user else []
    eff_skills = [s for s in (skills or []) if s]
    if trace_emitter:
        traces = trace_emitter.query_traces(
            tenant=resolved_tenant,
            user_id=user_id,
            skill=skill,
            status=status,
            session_id=session_id,
            since=since,
            limit=limit,
            offset=offset,
            fuzzy_user=fuzzy_user,
            skills=eff_skills,
            users=eff_users,
        )
        await _attach_user_names(traces)
        # Count under the same scoped predicates so `total` matches the result set.
        total = trace_emitter.count_traces(
            tenant=resolved_tenant,
            user_id=user_id,
            skill=skill,
            status=status,
            session_id=session_id,
            since=since,
            fuzzy_user=fuzzy_user,
            skills=eff_skills,
            users=eff_users,
        )
        return {"traces": traces, "total": total, "limit": limit, "offset": offset}
    return {"traces": [], "total": 0, "limit": limit, "offset": offset}


@router.get("/api/traces/facets")
async def trace_facets(request: Request, tenant_id: str | None = None):
    """Distinct skills + users for the Trace Explorer filter dropdowns, scoped to
    the caller (a non-admin sees only their own activity; an admin sees all).

    Registered BEFORE ``/api/traces/{trace_id}`` so the literal path is matched
    rather than being captured as ``trace_id='facets'``. User entries carry a
    readable ``user_name`` resolved the same way as the trace list, so the
    dropdown labels line up with the USER column.
    """
    principal, resolved_tenant, _agent_id, caller_user = require_scoped_identity(
        request, requested_tenant=tenant_id
    )
    user_id = effective_observability_user_id(principal, caller_user, "")
    fuzzy_user = is_admin_principal(principal)
    if not trace_emitter:
        return {"skills": [], "users": []}
    facets = trace_emitter.distinct_facets(
        tenant=resolved_tenant, user_id=user_id, fuzzy_user=fuzzy_user,
    )
    user_rows = [{"user_id": uid} for uid in facets.get("users", [])]
    await _attach_user_names(user_rows)
    users = [
        {
            "user_id": r["user_id"],
            # Label mirrors the USER column; the raw internal id is only the option value.
            "user_name": r.get("user_name")
            or _readable_user_fallback(r["user_id"])
            or "Unknown user",
        }
        for r in user_rows
    ]
    return {"skills": facets.get("skills", []), "users": users}


@router.get("/api/traces/{trace_id}")
async def get_trace_detail(trace_id: str, request: Request, tenant_id: str | None = None):
    """Get a single trace with all its spans (for waterfall timeline)."""
    principal, resolved_tenant, _agent_id, caller_user = require_scoped_identity(
        request, requested_tenant=tenant_id
    )
    if trace_emitter:
        trace = trace_emitter.get_trace(trace_id)
        if trace:
            if not is_admin_principal(principal):
                trace_user = str(trace.get("user_id") or trace.get("metadata", {}).get("user_id") or "")
                if trace_user and trace_user != caller_user:
                    raise HTTPException(status_code=404, detail="Trace not found")
            await _attach_user_names([trace])
            return trace
        raise HTTPException(status_code=404, detail="Trace not found")
    raise HTTPException(status_code=503, detail="Trace telemetry not enabled")


@router.get("/api/traces/{trace_id}/sources")
async def get_trace_sources(trace_id: str, request: Request, tenant_id: str | None = None):
    """Get document sources referenced during a trace.

    Parses tool/knowledge/memory spans and returns structured source entries
    with query (input_preview) and result (output_preview) for each reference,
    so users can see exactly which files, SQL queries, and memory lookups were
    used to arrive at the answer.
    """
    # Same tenant and owner scoping as get_trace_detail: span previews expose other users' data.
    principal, _resolved_tenant, _agent_id, caller_user = require_scoped_identity(
        request, requested_tenant=tenant_id
    )
    if not trace_emitter:
        raise HTTPException(status_code=503, detail="Trace telemetry not enabled")

    trace = trace_emitter.get_trace(trace_id)
    if not trace:
        raise HTTPException(status_code=404, detail="Trace not found")
    if not is_admin_principal(principal):
        trace_user = str(trace.get("user_id") or trace.get("metadata", {}).get("user_id") or "")
        if trace_user and trace_user != caller_user:
            raise HTTPException(status_code=404, detail="Trace not found")

    sources = []
    for span in trace.get("spans", []):
        span_type = span.get("span_type", "")
        name = span.get("name", "")
        input_preview = (span.get("input_preview") or "").strip()
        output_preview = (span.get("output_preview") or "").strip()

        # Only emit spans that carry meaningful content
        if not input_preview and not output_preview:
            continue

        # Classify by span_type / name
        if span_type == "tool":
            name_lower = name.lower()
            if "sql" in name_lower or "run_sql" in name_lower:
                category, icon, label = "sql", "🗄", "SQL Query"
            elif "memory" in name_lower or "query_memory" in name_lower:
                category, icon, label = "memory", "🧠", "Memory Lookup"
            elif name_lower == "shell" or "shell" in name_lower:
                category, icon, label = "file", "📄", "File / Shell"
            elif "invoke_skill" in name_lower:
                category, icon, label = "skill", "⚡", "Skill Invocation"
            else:
                category, icon, label = "tool", "🔧", name
        elif span_type == "knowledge":
            category, icon, label = "knowledge", "📚", "Context / Knowledge"
        elif span_type == "memory":
            category, icon, label = "memory", "🧠", "Memory"
        else:
            # Skip route, llm, response, hitl spans — not document sources
            continue

        meta = span.get("metadata") or {}
        if isinstance(meta, str):
            try:
                meta = json.loads(meta)
            except Exception:
                meta = {}

        sources.append({
            "category":    category,
            "icon":        icon,
            "label":       label,
            "name":        name,
            "status":      span.get("status", "ok"),
            "has_error":   bool(meta.get("has_error", False)),
            "duration_ms": span.get("duration_ms"),
            "query":       input_preview,
            "result":      output_preview,
        })

    return {"trace_id": trace_id, "sources": sources, "count": len(sources)}


@router.get("/api/history")
async def get_history(
    request: Request,
    tenant_id: str = "company",
    agent_id: str = "enterprise_agent",
    user_id: str = "demo",
    date: Optional[str] = None,
):
    """Get conversation history."""
    if date and not _DATE_RE.match(date):
        raise HTTPException(status_code=400, detail="Invalid date")
    _principal, tenant_id, agent_id, user_id = require_scoped_identity(
        request,
        requested_tenant=tenant_id,
        requested_agent=_safe_id(agent_id, "agent_id"),
        requested_user=_safe_id(user_id, "user_id"),
    )
    kernel = state.get_kernel(tenant_id, agent_id, user_id)
    history_dir = kernel.agent_root / "memory" / "history"

    def _load_sessions():
        sessions = []
        if not history_dir.exists():
            return sessions
        if date:
            date_dir = history_dir / date
            if date_dir.resolve().parent == history_dir.resolve() and date_dir.is_dir():
                for session_file in sorted(date_dir.glob("*.jsonl"), reverse=True):
                    entries = []
                    for line in session_file.read_text(encoding='utf-8').strip().split("\n"):
                        if line:
                            try:
                                entries.append(json.loads(line))
                            except Exception:
                                pass
                    sessions.append({
                        "session_id": session_file.stem,
                        "date": date,
                        "entries": entries,
                    })
        else:
            for date_dir in sorted(history_dir.iterdir(), reverse=True):
                if date_dir.is_dir():
                    session_count = len(list(date_dir.glob("*.jsonl")))
                    sessions.append({
                        "date": date_dir.name,
                        "session_count": session_count,
                    })
        return sessions

    sessions = await asyncio.to_thread(_load_sessions)
    return {"sessions": sessions}


@router.get("/api/queue/status")
async def get_queue_status():
    """Get lane queue status for monitoring."""
    return queue_manager.get_all_queues_status()


@router.get("/api/queue/{queue_name}/pending")
async def get_pending_tasks(queue_name: str):
    """Get pending tasks for a specific queue/lane."""
    try:
        pending = await queue_manager.get_pending_tasks(queue_name)
        return {
            "queue_name": queue_name,
            "pending_count": len(pending),
            "pending_tasks": pending,
        }
    except Exception as e:
        logger.error("get_pending_tasks failed for %r: %s", queue_name, e, exc_info=True)
        return {
            "queue_name": queue_name,
            "pending_count": 0,
            "pending_tasks": [],
            "error": "An internal error occurred",
        }


@router.post("/api/queue/{queue_name}/cancel")
async def cancel_pending_tasks(queue_name: str, admin: dict = Depends(require_admin)):
    """Cancel all pending tasks in a queue.
    Use with caution - useful for stuck sessions.
    """
    cancelled = await queue_manager.cancel_pending(queue_name)
    return {
        "queue_name": queue_name,
        "cancelled_count": cancelled,
    }


@router.get("/api/tasks")
async def get_tasks(request: Request, user_id: str = "demo", limit: int = 20):
    """Get recent tasks for a user from Redis."""
    principal, tenant_id, _agent, caller_user = require_scoped_identity(request)
    user_id = _safe_id(user_id, "user_id") if is_admin_principal(principal) else caller_user
    tasks = await task_integration.get_user_history(user_id, limit)
    tasks = [t for t in tasks if _task_visible(t, principal, tenant_id, caller_user)]
    return {
        "user_id": user_id,
        "count": len(tasks),
        "tasks": [
            {
                "id": t.id,
                "content": t.content[:100] + "..." if len(t.content) > 100 else t.content,
                "skill": t.skill_name,
                "status": t.status.value,
                "duration_ms": t.duration_ms,
                "created_at": t.created_at,
                "completed_at": t.completed_at,
                "error": t.error if t.error else None,
            }
            for t in tasks
        ],
    }


# NOTE: Fixed routes MUST come before parameterised /api/tasks/{task_id}
# so FastAPI doesn't capture "stats" or "active" as a task_id.

@router.get("/api/tasks/active/list")
async def get_active_tasks(request: Request):
    """Get currently processing tasks."""
    principal, tenant_id, _agent, caller_user = require_scoped_identity(request)
    tasks = await task_integration.get_active_tasks()
    tasks = [t for t in tasks if _task_visible(t, principal, tenant_id, caller_user)]
    return {
        "count": len(tasks),
        "active": [
            {
                "id": t.id,
                "content": t.content[:50],
                "skill": t.skill_name,
                "user_id": t.user_id,
                "started_at": t.started_at,
            }
            for t in tasks
        ],
    }


@router.get("/api/tasks/stats")
async def get_task_stats():
    """Get task system statistics."""
    return await task_integration.get_stats()


@router.get("/api/tasks/{task_id}")
async def get_task_detail(task_id: str, request: Request):
    """Get full details of a specific task."""
    principal, tenant_id, _agent, caller_user = require_scoped_identity(request)
    task = await task_integration.get_task(task_id)
    if not task or not _task_visible(task, principal, tenant_id, caller_user):
        raise HTTPException(status_code=404, detail="Task not found")

    return {
        "id": task.id,
        "content": task.content,
        "skill": task.skill_name,
        "status": task.status.value,
        "response": task.response,
        "error": task.error,
        "duration_ms": task.duration_ms,
        "tenant_id": task.tenant_id,
        "user_id": task.user_id,
        "session_id": task.session_id,
        "created_at": task.created_at,
        "started_at": task.started_at,
        "completed_at": task.completed_at,
    }
