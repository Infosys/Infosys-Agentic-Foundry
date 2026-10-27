"""
Command Center — FastAPI Router.

All routes are prefixed /api/queue/.

Routes:
  GET  /api/queue/items              — paginated list with filters
  POST /api/queue/items              — manual item creation
  POST /api/queue/ingest             — external webhook (API key auth)
  GET  /api/queue/items/{id}         — full item detail + steps + routing
  GET  /api/queue/hitl/pending       — pending HITL gates for this tenant
  POST /api/queue/hitl/{id}/respond  — human submits HITL response
  POST /api/queue/simulate           — inject demo scenarios
  GET  /api/queue/metrics            — queue health metrics
  WS   /ws/queue                     — real-time event stream
"""

import asyncio
import hashlib
import hmac
import json
import logging
import os
import shlex
import sys
import time
import uuid
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse

from cc_queue.db import get_db
from cc_queue.models import QueueItemCreate, IngestWebhook, HITLResponse
from shared.config import (
    DATA_ROOT_PATH,
    ENTERPRISE_STRICT_MODE,
    QUEUE_INGEST_API_KEY,
    TENANT_ID,
)
from iaf_agent_skills.capture_events import emit_queue_task_lifecycle
from security.dependencies import require_scoped_identity

logger = logging.getLogger(__name__)

router = APIRouter()

# Default dedup window (1h): periodic firings within it collapse to one queue item.
_DEFAULT_BUCKET_SECONDS = int(os.getenv("QUEUE_INGEST_DEFAULT_BUCKET_SECONDS", "3600"))


def _record_queue_reward_best_effort(
    *,
    tenant_id: str,
    item_id: str,
    raw_label: str,
    judge_id: str = "",
    trace_id: str = "",
    notes: str = "",
    metadata: dict | None = None,
) -> None:
    try:
        emit_queue_task_lifecycle(
            data_root=DATA_ROOT_PATH,
            tenant_id=tenant_id,
            task_id=item_id,
            status=raw_label,
            trace_id=trace_id,
            actor=judge_id,
            notes=notes,
            metadata=metadata or {},
        )
    except Exception as rl_err:
        logger.debug("RL queue reward skipped: %s", rl_err)


def _compute_external_id(body, *, source: str) -> str:
    """
    Return a stable external_id for a queue item.

    Idempotency is a platform concern — callers shouldn't have to remember to
    compute a dedup key. If the caller supplies a non-empty external_id we
    honour it. Otherwise we synthesise one from a payload fingerprint plus a
    time bucket so that periodic firings (cron, webhook retries, retry-after
    timeouts) self-deduplicate.

    Formula when synthesised:
        auto:<source>:<sha256(tenant|domain|entity|title|description|priority)[:12]>:<bucketed_ts>
    """
    raw = getattr(body, "external_id", None)
    if raw and raw.strip():
        return raw.strip()

    bucket = getattr(body, "bucket_seconds", None) or _DEFAULT_BUCKET_SECONDS
    if bucket < 1:
        bucket = _DEFAULT_BUCKET_SECONDS

    fingerprint_parts = [
        body.tenant_id or "",
        body.domain or "",
        body.entity_id or "",
        body.title or "",
        body.description or "",
        body.priority or "",
    ]
    digest = hashlib.sha256("|".join(fingerprint_parts).encode("utf-8")).hexdigest()[:12]
    bucketed_ts = int(time.time()) // bucket * bucket
    return f"auto:{source}:{digest}:{bucketed_ts}"


def _tool_result_payload(text: object) -> str:
    stripped = str(text or "").strip()
    if stripped.startswith("✅") and "\n\n" in stripped:
        return stripped.split("\n\n", 1)[1].strip()
    return stripped


def _extract_json_document(text: str):
    if not text:
        return None
    stripped = _tool_result_payload(text)
    if not stripped or stripped[0] not in "[{":
        return None
    try:
        return json.loads(stripped)
    except Exception:
        return None


def _result_indicates_tool_failure(result: object) -> bool:
    text = str(result or "").strip()
    if not text:
        return False
    if text.startswith("❌"):
        return True
    parsed = _extract_json_document(text)
    if not isinstance(parsed, dict):
        return False
    status = parsed.get("status") or parsed.get("status_code")
    try:
        if status is not None and int(status) >= 400:
            return True
    except Exception:
        pass
    if parsed.get("error"):
        return True
    detail = parsed.get("detail")
    if isinstance(detail, list):
        return any(isinstance(item, dict) and item.get("type") for item in detail)
    return False


def _queue_replay_result_summary(result: object, failed: bool) -> str:
    if not failed:
        return str(result) or "Completed."
    payload = _tool_result_payload(result)
    if payload.lower().startswith("rejected "):
        return payload
    if payload:
        return f"❌ Tool execution failed after approval\n\n{payload}"
    return "❌ Tool execution failed after approval"


def _curl_request_metadata(command: str) -> dict:
    if not command:
        return {}
    try:
        parts = shlex.split(command)
    except Exception:
        return {}
    if not parts or parts[0] != "curl":
        return {}
    method = "GET"
    url = ""
    saw_body = False
    idx = 1
    while idx < len(parts):
        token = parts[idx]
        if token in {"-X", "--request"} and idx + 1 < len(parts):
            method = parts[idx + 1].upper()
            idx += 2
            continue
        if token.startswith("-X") and len(token) > 2:
            method = token[2:].upper()
        if token in {"-d", "--data", "--data-raw", "--data-binary", "--data-urlencode"}:
            saw_body = True
            idx += 2
            continue
        if token.startswith(("http://", "https://")):
            url = token
        idx += 1
    if method == "GET" and saw_body:
        method = "POST"
    if not url:
        return {}
    return {"method": method, "url": url, "command": command}


def _persist_replay_evidence(db, exec_id: str, item_id: str, tenant_id: str,
                             agent, pending_tool_call: object, result: object,
                             query: str) -> tuple[str, int]:
    if not exec_id:
        return "", 0
    if not isinstance(pending_tool_call, dict):
        return "", 0
    tool_name = str(pending_tool_call.get("name") or "")
    args = pending_tool_call.get("args") if isinstance(pending_tool_call.get("args"), dict) else {}
    command = str(args.get("command") or "")
    http_meta = _curl_request_metadata(command) if tool_name == "shell" else {}
    if not http_meta:
        return "", 0

    try:
        from iaf_agent_skills.evidence_collector_adapter import EvidenceCollectorAdapter
        adapter = EvidenceCollectorAdapter()
        collector = adapter.new_collector()
        collector.record_api_response(
            method=http_meta["method"],
            url=http_meta["url"],
            response_text=_tool_result_payload(result),
            status_code=None,
            metadata={"tool": tool_name, "command": command, "queue_item_id": item_id},
        )
        item_detail = db.get_item_detail(item_id) if hasattr(db, "get_item_detail") else None
        item = (item_detail or {}).get("item") if isinstance(item_detail, dict) else {}
        trace_id = str((item or {}).get("trace_id") or uuid.uuid4().hex)
        bundle = collector.get_bundle(
            response_text=str(result or ""),
            query_text=str(query or ""),
            trace_id=trace_id,
            tenant_id=tenant_id,
            agent_id="enterprise_agent",
            user_id=f"queue:{item_id}",
            execution_source="queue",
        )
        stored = adapter.persist(bundle)
        evidence_count = int(stored.get("evidence_items_count") or len(stored.get("evidence_items") or []))
        if trace_id and evidence_count:
            db.set_execution_evidence(exec_id, trace_id, evidence_count)
            logger.info("Queue HITL replay evidence stored: item=%s trace_id=%s items=%s",
                        item_id, trace_id, evidence_count)
            return trace_id, evidence_count
    except Exception as exc:
        logger.warning("Queue HITL replay evidence persistence failed for %s: %s", item_id, exc)
    return "", 0


def _get_tenant(request: Request) -> str:
    """The caller's tenant as set by the auth middleware, else this server's tenant.

    This used to read request.state.user, which the middleware never sets, so every
    request was attributed to 'company' regardless of who made it.
    """
    return getattr(request.state, "tenant_id", None) or TENANT_ID


def _get_username(request: Request) -> str:
    return (
        getattr(request.state, "email", None)
        or getattr(request.state, "user_id", None)
        or "unknown"
    )


def _service_token_allowed(request: Request) -> bool:
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        return False
    try:
        from auth.identity import resolve_access_token_identity

        identity = resolve_access_token_identity(auth_header[7:].strip())
    except Exception:
        return False
    return bool(
        identity.is_service_principal
        and set(identity.groups).intersection({"service:cron", "service:queue"})
    )


def _require_queue_surface_auth(request: Request, *, allow_service_token: bool) -> None:
    """Authenticate operational queue surfaces that bypass JWT middleware."""
    incoming_key = request.headers.get("X-API-Key", "")
    if QUEUE_INGEST_API_KEY and hmac.compare_digest(incoming_key, QUEUE_INGEST_API_KEY):
        return
    if allow_service_token and _service_token_allowed(request):
        return
    if not ENTERPRISE_STRICT_MODE and not QUEUE_INGEST_API_KEY:
        return
    if ENTERPRISE_STRICT_MODE and not QUEUE_INGEST_API_KEY:
        raise HTTPException(status_code=503, detail="QUEUE_INGEST_API_KEY is not configured")
    raise HTTPException(status_code=401, detail="Invalid API key")


def _get_client_ip(request: Request) -> str:
    xff = request.headers.get("X-Forwarded-For")
    if xff:
        return xff.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


@router.get("/api/queue/items")
async def list_queue_items(
    request: Request,
    status: Optional[str] = None,
    priority: Optional[str] = None,
    page: int = 1,
    limit: int = 20,
):
    """Paginated list of queue items with optional status filter."""
    tenant_id = _get_tenant(request)
    db = get_db()
    items, total = db.list_items(tenant_id, status, page, min(limit, 100))

    if priority:
        items = [i for i in items if i.get("priority") == priority]

    return {
        "items": items,
        "total": total,
        "page": page,
        "limit": limit,
        "pages": max(1, (total + limit - 1) // limit),
    }


@router.post("/api/queue/items", status_code=201)
async def create_queue_item(request: Request, body: QueueItemCreate):
    """Manual item creation from dashboard."""
    tenant_id = _get_tenant(request)
    db = get_db()

    item = {
        "id": f"CC-{uuid.uuid4().hex[:8].upper()}",
        "tenant_id": body.tenant_id or tenant_id,
        "external_id": _compute_external_id(body, source=(body.source or "manual")),
        "domain": body.domain,
        "entity_id": body.entity_id,
        "title": body.title,
        "description": body.description,
        "priority": body.priority,
        "trace_id": uuid.uuid4().hex,
        "source": body.source or "manual",
    }
    db.insert_item(item)
    _record_queue_reward_best_effort(
        tenant_id=item["tenant_id"],
        item_id=item["id"],
        raw_label="queued",
        judge_id=_get_username(request),
        trace_id=item.get("trace_id", ""),
        metadata={"source": item.get("source"), "domain": item.get("domain"), "priority": item.get("priority")},
    )

    await _broadcast({"type": "item_created", "item": item})

    logger.info("Manual queue item created: %s — %s", item["id"], item["title"])
    return item


@router.post("/api/queue/ingest", status_code=201)
async def ingest_webhook(request: Request, body: IngestWebhook):
    """
    External webhook endpoint for PagerDuty / ServiceNow / Kafka etc.
    Requires X-API-Key header matching QUEUE_INGEST_API_KEY (if configured).
    """
    _require_queue_surface_auth(request, allow_service_token=False)
    if ENTERPRISE_STRICT_MODE and body.tenant_id != TENANT_ID:
        raise HTTPException(status_code=403, detail="Tenant access denied")

    db = get_db()
    item = {
        "id": f"CC-{uuid.uuid4().hex[:8].upper()}",
        "tenant_id": body.tenant_id,
        "external_id": _compute_external_id(body, source="webhook"),
        "domain": body.domain,
        "entity_id": body.entity_id,
        "title": body.title,
        "description": body.description,
        "priority": body.priority,
        "trace_id": uuid.uuid4().hex,
        "source": "webhook",
    }
    db.insert_item(item)
    _record_queue_reward_best_effort(
        tenant_id=item["tenant_id"],
        item_id=item["id"],
        raw_label="ingested",
        trace_id=item.get("trace_id", ""),
        metadata={"source": item.get("source"), "domain": item.get("domain"), "priority": item.get("priority")},
    )

    await _broadcast({"type": "item_created", "item": item})
    logger.info("Webhook ingest: %s from external_id=%s", item["id"], body.external_id)
    return {"id": item["id"], "status": "queued"}


@router.get("/api/queue/items/{item_id}")
async def get_queue_item(item_id: str, request: Request):
    """Full item detail including all execution steps and routing decision."""
    db = get_db()
    detail = db.get_item_detail(item_id)
    if not detail:
        raise HTTPException(status_code=404, detail="Item not found")
    return detail


@router.get("/api/queue/hitl/pending")
async def get_pending_hitl(request: Request):
    """
    Return all queue items in awaiting_human status.
    The actual approval objects live in the existing ApprovalStore (Redis).
    We surface them here enriched with queue context.
    """
    tenant_id = _get_tenant(request)
    db = get_db()
    items, _ = db.list_items(tenant_id, status="awaiting_human", page=1, limit=50)

    enriched = []
    for item in items:
        detail = db.get_item_detail(item["id"])
        enriched.append({
            "queue_item": item,
            "executions": detail["executions"] if detail else [],
        })

    return {"pending": enriched, "count": len(enriched)}


@router.post("/api/queue/hitl/{item_id}/respond")
async def respond_to_hitl(
    item_id: str,
    request: Request,
    body: HITLResponse,
    background_tasks: BackgroundTasks,
):
    """
    Human submits a HITL response for a queue item.
    Loads the checkpointed agent state, injects the decision, resumes workflow.
    """
    db = get_db()
    detail = db.get_item_detail(item_id)
    if not detail:
        raise HTTPException(status_code=404, detail="Item not found")

    item = detail["item"]
    # The responder is the authenticated principal; request.state.user is never set by the auth middleware.
    _principal, tenant_id, _agent, username = require_scoped_identity(
        request,
        requested_tenant=item.get("tenant_id") or None,
        action="approve",
        resource_type="approval",
        resource_id=f"queue:{item_id}",
        context={"source": "queue_hitl", "skill": item.get("skill") or ""},
    )
    if item.get("status") != "awaiting_human":
        raise HTTPException(
            status_code=409,
            detail=f"Item is not awaiting human input (status: {item.get('status')})"
        )
    client_ip = _get_client_ip(request)

    # Find the approval_id stored by the processor at HITL pause time
    from shared.state import approval_store
    approval_id = None
    agent_state = None
    try:
        pending = await approval_store.get_pending(tenant_id)
        for appr in pending:
            # The processor stored _queue_item_id in the agent state metadata
            state_blob = await approval_store.get_agent_state(appr.id)
            if state_blob and state_blob.get("_queue_item_id") == item_id:
                approval_id = appr.id
                agent_state = state_blob
                break
    except Exception as e:
        logger.warning("ApprovalStore lookup failed: %s", e)

    # Mark item as running — only if it is STILL awaiting a human. Two concurrent responses
    # both pass the status check above; this compare-and-set lets exactly one resume it.
    if not db.update_item(item_id, expected_status="awaiting_human", status="running"):
        raise HTTPException(status_code=409, detail="Item was already answered by another response")
    _record_queue_reward_best_effort(
        tenant_id=tenant_id,
        item_id=item_id,
        raw_label=f"hitl_{str(body.response).strip().lower()}",
        judge_id=username,
        trace_id=str(item.get("trace_id") or item_id),
        notes=body.notes or "",
        metadata={"source": "queue_hitl", "client_ip": client_ip, "resuming": bool(agent_state), "approval_id": approval_id},
    )

    await _broadcast({
        "type": "hitl_resolved",
        "item_id": item_id,
        "response": body.response,
        "resolved_by": username,
    })

    # Resume agent in background if we have a checkpoint
    if agent_state:
        background_tasks.add_task(
            _resume_queue_agent,
            item_id, approval_id, agent_state,
            body.response, username,
            body.notes or "",
        )
        logger.info("HITL resolved for %s — resuming agent from checkpoint (approval %s)",
                    item_id, approval_id)
        resuming = True
    else:
        # No checkpoint — re-queue so processor re-runs from scratch with decision context
        decision_tag = f"[HUMAN DECISION: {body.response.upper()} by {username}]"
        if body.notes:
            decision_tag += f" Notes: {body.notes}"
        original_desc = item.get("description") or item.get("title") or ""
        db.update_item(item_id, status="queued",
                       description=f"{original_desc}\n\n{decision_tag}",
                       retry_count=0)
        _record_queue_reward_best_effort(
            tenant_id=tenant_id,
            item_id=item_id,
            raw_label="requeued_after_hitl",
            judge_id=username,
            trace_id=str(item.get("trace_id") or item_id),
            notes=body.notes or "",
            metadata={"source": "queue_hitl", "approval_id": approval_id},
        )
        logger.info("HITL resolved for %s — no checkpoint, re-queued with decision context", item_id)
        resuming = False

    logger.info("HITL respond: %s → %s by %s from %s",
                item_id, body.response, username, client_ip)
    return {
        "status": "resolved",
        "response": body.response,
        "resolved_by": username,
        "resuming": resuming,
    }


def _resume_queue_agent(
    item_id: str, approval_id: str, agent_state: dict,
    decision: str, decided_by: str, decision_note: str,
):
    """
    Background task: restore checkpointed agent and resume the queue item.

    If the checkpoint carries a concrete pending tool call, replay that exact
    captured call instead of asking the LLM to reconstruct it from a decision
    prompt. Business/workflow approvals without a pending tool call keep the
    existing natural-language continuation path.
    Mirrors approvals.py _resume_agent_from_hitl_sync.
    """
    import traceback
    from cc_queue.db import get_db as _get_db
    from shared.state import state, approval_store, _main_loop
    import asyncio as _aio

    db = _get_db()
    skill_name = agent_state.get("_skill_name", "")
    query      = agent_state.get("_query", "")
    exec_id    = agent_state.get("_exec_id", "")

    try:
        tenant_id = agent_state.get("tenant_id", "company")
        # Per-job session — avoids shared state race when multiple HITL jobs are approved concurrently
        resume_session_id = f"queue_{item_id}_resume"
        agent = state.get_or_create(tenant_id, "enterprise_agent", resume_session_id)
        # Same service principal as the original queue run, so the resumed half is governed identically.
        from security.dependencies import make_agent_entitlement_checker, make_service_principal
        _queue_principal = make_service_principal(tenant_id, "queue")
        agent.set_entitlement_context(_queue_principal, make_agent_entitlement_checker(_queue_principal))
        agent._telemetry_entrypoint = "queue_resume"
        # Not preserve_history: this agent is private to the job, so the snapshot is the state to resume from.
        agent.import_state(agent_state)
        approval_context = {}
        approval_pending = getattr(agent, "approval_pending", None)
        if isinstance(approval_pending, dict):
            approval_context = approval_pending.get("context") or {}

        pending_tool_call = getattr(agent, "pending_tool_call", None)
        resume_kind = approval_context.get("resume_kind")
        exact_tool_replay = bool(pending_tool_call) or resume_kind == "stream_intercept"
        approved = str(decision).strip().lower() in {"approve", "approved", "yes", "y"}
        final_item_status = "done"
        final_execution_status = "completed"

        if exact_tool_replay:
            agent.approval_pending = None
            if approved:
                result = agent.resume_approved_tool_call()
                if str(result).startswith("❌ No pending tool call"):
                    raise RuntimeError("Missing checkpointed pending tool call for queue approval")
                _persist_replay_evidence(
                    db, exec_id, item_id, tenant_id, agent, pending_tool_call, result, query
                )
                if _result_indicates_tool_failure(result):
                    final_item_status = "failed"
                    final_execution_status = "failed"
                logger.info(
                    "Queue HITL exact tool replay complete: item=%s approval=%s tool=%s",
                    item_id,
                    approval_id,
                    (pending_tool_call or {}).get("name") if isinstance(pending_tool_call, dict) else "unknown",
                )
            else:
                result = agent.reject_pending_tool_call()
                final_item_status = "failed"
                final_execution_status = "failed"
                logger.info("Queue HITL rejected exact tool replay: item=%s approval=%s", item_id, approval_id)
        else:
            agent.approval_pending = None
            agent._hitl_decision_injected = True

            note_part = f"\nNote: {decision_note}" if decision_note else ""
            injection = (
                f"[HUMAN DECISION] The approval was {decision.upper()} by {decided_by}.{note_part}\n"
                f"Please continue the workflow from where it paused."
            )
            if approved:
                injection += " The action is authorized — proceed with remaining steps."
            else:
                injection += " The action was denied — skip execution, inform the outcome."

            try:
                result = agent.run(injection, skill_name=skill_name, skip_memory=True)
            finally:
                agent._hitl_decision_injected = False

        db.update_item(item_id, status=final_item_status)
        _record_queue_reward_best_effort(
            tenant_id=tenant_id,
            item_id=item_id,
            raw_label=final_item_status,
            judge_id=decided_by,
            trace_id=str(agent_state.get("trace_id") or agent_state.get("_active_trace_id") or item_id),
            notes=decision_note,
            metadata={
                "source": "queue_hitl_resume",
                "approval_id": approval_id,
                "decision": decision,
                "execution_status": final_execution_status,
                "exec_id": exec_id,
            },
        )
        if exec_id:
            db.update_execution(exec_id, status=final_execution_status,
                                result_summary=_queue_replay_result_summary(
                                    result, final_execution_status == "failed"
                                ))

        if approval_id and _main_loop and not _main_loop.is_closed():
            _aio.run_coroutine_threadsafe(
                approval_store.delete_agent_state(approval_id), _main_loop
            ).result(timeout=10)

        try:
            state.remove(tenant_id, user_id=resume_session_id)
        except Exception:
            pass
        logger.info("Queue HITL resume complete: item=%s decision=%s", item_id, decision)

    except Exception as e:
        traceback.print_exc()
        logger.error("Queue HITL resume failed for %s: %s", item_id, e)
        db.update_item(item_id, status="failed")
        _record_queue_reward_best_effort(
            tenant_id=str(agent_state.get("tenant_id") or "company"),
            item_id=item_id,
            raw_label="failed",
            judge_id=decided_by,
            trace_id=str(agent_state.get("trace_id") or agent_state.get("_active_trace_id") or item_id),
            notes=str(e),
            metadata={"source": "queue_hitl_resume", "approval_id": approval_id, "decision": decision},
        )


@router.post("/api/queue/simulate")
async def simulate_demo(request: Request):
    """Inject 4 pre-built ITOps demo scenarios. Idempotent (deduped by external_id)."""
    from cc_queue.seed import seed_demo_items, QueueSeedError
    tenant_id = _get_tenant(request)
    try:
        queued = seed_demo_items(tenant_id)
    except QueueSeedError as exc:
        # Hard backend failure: surface an error, not a misleading 200 with queued=0.
        logger.error("Simulate demo failed for tenant %s: %s", tenant_id, exc)
        raise HTTPException(status_code=502, detail=f"Could not seed demo items: {exc}")
    await _broadcast({"type": "demo_seeded", "inserted": queued})
    return {"inserted": queued, "queued": queued,
            "message": f"{queued} demo items queued and ready to process"}


@router.post("/api/queue/feed")
async def run_feeder(
    request: Request,
    path: Optional[str] = None,
    dry_run: bool = False,
):
    """
    Server-side queue feeder — reads a JSON/CSV feed file and ingests items.
    Called by the queue_feeder cron skill via curl.
    Falls back to QUEUE_FEED_FILE_PATH env var, then the built-in sample_feed.json.
    """
    import asyncio as _asyncio
    from pathlib import Path as _Path

    _require_queue_surface_auth(request, allow_service_token=True)
    # Resolve file path: explicit → env var → bundled sample
    _server_dir = _Path(__file__).resolve().parent.parent
    feed_path = (
        path
        or os.getenv("QUEUE_FEED_FILE_PATH", "")
        or str(_server_dir / "cc_queue" / "sample_feed.json")
    )

    feeder_script = str(_server_dir / "cc_queue" / "feeder.py")
    api_url = f"http://localhost:{os.getenv('PORT', '8080')}"

    cmd = [sys.executable, feeder_script, "--source", "file", "--path", feed_path, "--api-url", api_url]
    if dry_run:
        cmd.append("--dry-run")

    try:
        proc = await _asyncio.create_subprocess_exec(
            *cmd,
            stdout=_asyncio.subprocess.PIPE,
            stderr=_asyncio.subprocess.PIPE,
        )
        stdout, stderr = await _asyncio.wait_for(proc.communicate(), timeout=60)
        import json as _json
        summary = _json.loads(stdout.decode())
        logger.info("Queue feeder ran: inserted=%s skipped=%s errors=%s",
                    summary.get("inserted"), summary.get("skipped_duplicate"), summary.get("errors"))
        if summary.get("inserted", 0) > 0:
            await _broadcast({"type": "items_ingested", "count": summary["inserted"]})
        return summary
    except Exception as e:
        logger.warning("Queue feeder error: %s", e)
        raise HTTPException(status_code=500, detail="An internal error occurred")


@router.get("/api/queue/metrics")
async def get_metrics(request: Request):
    """Queue health metrics for the dashboard footer strip."""
    from cc_queue.processor import get_processor
    tenant_id = _get_tenant(request)
    db = get_db()
    metrics = db.get_metrics(tenant_id)
    local_heartbeat = get_processor().heartbeat
    metrics["processor_online"] = bool(metrics.get("processor_online") or local_heartbeat)
    metrics["processor_heartbeat"] = get_processor().heartbeat
    metrics["domain_label"] = os.getenv("QUEUE_DOMAIN_LABEL", "Item")
    metrics["header_title"] = os.getenv("QUEUE_HEADER_TITLE", "Command Center")
    return metrics


@router.get("/api/queue/dlq")
async def list_dlq(request: Request, limit: int = 50):
    """List Dead Letter Queue items with original item metadata."""
    db = get_db()
    items = db.list_dlq(limit=limit)
    return {"items": items, "count": len(items)}


@router.post("/api/queue/dlq/{dlq_id}/retry")
async def retry_dlq_item(dlq_id: int, request: Request):
    """Move a DLQ item back to queued status for retry."""
    db = get_db()
    item_id = db.requeue_from_dlq(dlq_id)
    if not item_id:
        raise HTTPException(404, f"DLQ item {dlq_id} not found")
    _record_queue_reward_best_effort(
        tenant_id=_get_tenant(request),
        item_id=item_id,
        raw_label="dlq_retry",
        judge_id=_get_username(request),
        metadata={"source": "dlq", "dlq_id": dlq_id},
    )
    from shared.state import queue_broadcaster
    import asyncio
    asyncio.create_task(queue_broadcaster.broadcast({
        "type": "item_updated", "item_id": item_id, "status": "queued"
    }))
    return {"message": f"Item {item_id} re-queued for retry", "item_id": item_id}


@router.websocket("/ws/queue")
async def websocket_queue(websocket: WebSocket):
    """Real-time event stream for Command Center dashboard."""
    from shared.state import queue_broadcaster
    await websocket.accept()
    await queue_broadcaster.connect(websocket)

    try:
        db = get_db()
        metrics = db.get_metrics("company")
        await websocket.send_json({"type": "snapshot", "metrics": metrics})
    except Exception:
        pass

    try:
        while True:
            try:
                data = await websocket.receive_json()
                if data.get("type") == "refresh":
                    db = get_db()
                    metrics = db.get_metrics("company")
                    await websocket.send_json({"type": "snapshot", "metrics": metrics})
            except Exception:
                break
    except WebSocketDisconnect:
        pass
    finally:
        await queue_broadcaster.disconnect(websocket)


async def _broadcast(payload: dict):
    try:
        from shared.state import queue_broadcaster
        await queue_broadcaster.broadcast(payload)
    except Exception:
        pass
