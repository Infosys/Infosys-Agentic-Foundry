"""
IAF Agent Studio — Approvals, HITL, & Dashboard WebSocket Router

Dashboard WebSocket (real-time updates), Twin WebSocket,
kernel-level approval queue, HITL approval lifecycle (create/resolve),
and dashboard summary API.
"""

import asyncio
import copy
import logging
import traceback
import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Request, WebSocket, WebSocketDisconnect, BackgroundTasks
from pydantic import BaseModel
from shared.config import AUTH_ENABLED, DATA_ROOT_PATH, TENANT_ID
from security.dependencies import authorise_approver, bind_websocket_identity, require_scoped_identity
from security.models import Principal
from shared.approval_scoping import compute_hitl_stats, is_admin_principal, scope_approval_records
from auth.middleware import require_admin
from shared.state import (
    state, dashboard, twin_broadcaster, approval_store,
    chat_registry, cron_scheduler, task_integration,
    twin_emitter, set_main_loop, get_main_loop,
    stream_intercept_approval_id, reconcile_stream_intercept_durable,
)
from shared.ops_summary import build_default_ops_summary
from iaf_agent_skills.capture_events import emit_agentpro_reward

logger = logging.getLogger(__name__)

router = APIRouter()


def _record_hitl_reward_best_effort(
    *,
    tenant_id: str,
    agent_id: str = "enterprise_agent",
    approval_id: str = "",
    decision: str,
    decided_by: str = "",
    reason: str = "",
    context: dict | None = None,
    status: str = "",
    source: str = "approvals",
) -> None:
    try:
        ctx = context or {}
        trace_id = str(ctx.get("trace_id") or ctx.get("request_trace_id") or approval_id)
        emit_agentpro_reward(
            data_root=DATA_ROOT_PATH,
            tenant_id=tenant_id,
            agent_id=agent_id,
            channel="human_approval",
            raw_label=decision,
            target_id=approval_id,
            trajectory_id=trace_id,
            judge_id=decided_by,
            notes=reason,
            source_event_id=approval_id,
            source_trace_id=trace_id,
            metadata={
                "status": status,
                "source": source,
                "context": ctx,
            },
        )
    except Exception as rl_err:
        logger.debug("RL HITL reward skipped: %s", rl_err)


def _bounded_text(value, limit: int = 1000) -> str:
    text = "" if value is None else str(value)
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 3)] + "..."


def _workstream_ref(resolved) -> tuple[str | None, str | None]:
    ctx = getattr(resolved, "context", None) or {}
    return (
        ctx.get("workstream_name") or ctx.get("workstream"),
        ctx.get("mission_item_id") or ctx.get("item_id") or ctx.get("workstream_item"),
    )


def _approval_workstream_ref(approval) -> tuple[str | None, str | None]:
    ctx = getattr(approval, "context", None) or {}
    return (
        ctx.get("workstream_name") or ctx.get("workstream"),
        ctx.get("mission_item_id") or ctx.get("item_id") or ctx.get("workstream_item"),
    )


def _is_stream_intercept_approval(approval) -> bool:
    ctx = getattr(approval, "context", None) or {}
    return ctx.get("resume_kind") == "stream_intercept"


def _agent_for_hitl_resume(base_agent, *, approval_id: str, ws_name: str | None, item_id: str | None):
    if not ws_name or not item_id:
        return base_agent
    clone_for_session = getattr(base_agent, "clone_for_session", None)
    if not callable(clone_for_session):
        return base_agent
    try:
        session_id = f"hitl_resume_{approval_id[:8]}_{item_id}"
        return clone_for_session(session_id)
    except Exception as clone_err:
        logger.warning(
            "Workstream HITL resume clone failed for %s/%s (%s); using shared agent",
            ws_name, item_id, clone_err,
        )
        return base_agent


def _workstream_store_for(tenant_id: str):
    from iaf_agent_skills.workstream_store import WorkstreamStore
    from pathlib import Path
    from shared.config import SERVER_DIR, DATA_ROOT

    tenant_root = Path(SERVER_DIR) / DATA_ROOT / "tenants" / tenant_id
    return WorkstreamStore(tenant_root)


def _safe_tag(value) -> str:
    text = _bounded_text(value, 120).strip().lower()
    return "".join(ch if ch.isalnum() or ch in {"_", "-", ":"} else "_" for ch in text).strip("_")


def _workstream_hitl_entity_keys(
    *,
    approval_id: str,
    ws_name: str,
    item_id: str,
    resolved,
    item: dict | None,
) -> list[str]:
    keys = [
        f"workstream:{ws_name}",
        f"item:{item_id}",
        f"approval:{approval_id}",
    ]
    ctx = getattr(resolved, "context", None) or {}
    case_summary = (item or {}).get("case_summary") or {}
    candidates = {
        "supplier": (
            ctx.get("supplier_name")
            or ctx.get("vendor_name")
            or case_summary.get("primary_entity")
            or case_summary.get("supplier_name")
            or case_summary.get("vendor_name")
        ),
        "invoice": (
            ctx.get("invoice_id")
            or ctx.get("invoice")
            or case_summary.get("secondary_entity")
            or case_summary.get("invoice_id")
        ),
        "po": ctx.get("po_number") or case_summary.get("po_number"),
    }
    for prefix, value in candidates.items():
        if value:
            safe = _safe_tag(value)
            if safe:
                keys.append(f"{prefix}:{safe}")
    return list(dict.fromkeys(keys))


def _hitl_feedback_knowledge_exists(memory, approval_id: str) -> bool:
    try:
        result = memory.query_knowledge(
            status=None,
            source="hitl_feedback",
            limit=250,
            include_archived=True,
        )
    except Exception as query_err:
        logger.debug("HITL feedback knowledge idempotency query skipped: %s", query_err)
        return False
    approval_key = f"approval:{approval_id}"
    approval_tag = f"approval_{_safe_tag(approval_id)}"
    for record in result.get("items") or []:
        if approval_key in (record.get("entity_keys") or []):
            return True
        tags = ((record.get("scope") or {}).get("tags") or [])
        if approval_tag in tags:
            return True
    return False


def _write_hitl_feedback_knowledge(
    resolved,
    *,
    approval_id: str,
    decision: str,
    decided_by: str,
    decision_note: str = "",
) -> str | None:
    """Create a governed learning candidate from workstream HITL decisions."""
    ws_name, item_id = _workstream_ref(resolved)
    if not ws_name or not item_id:
        return None

    tenant_id = getattr(resolved, "tenant_id", "company")
    user_id = getattr(resolved, "user_id", "demo")
    skill = getattr(resolved, "skill", "") or None
    decision_norm = str(decision or getattr(resolved, "status", "") or "").strip().lower()
    if decision_norm == "approved":
        decision_norm = "approve"
    elif decision_norm == "rejected":
        decision_norm = "reject"

    try:
        agent = state.get_or_create(tenant_id, "enterprise_agent", user_id, user_role="user")
        memory = getattr(agent, "memory", None)
        if not memory:
            logger.debug("HITL feedback knowledge skipped: agent memory unavailable")
            return None

        if _hitl_feedback_knowledge_exists(memory, approval_id):
            logger.info("HITL feedback knowledge already exists for approval %s", approval_id)
            return None

        item = None
        try:
            store = _workstream_store_for(tenant_id)
            ws = store.load(ws_name)
            item = next((candidate for candidate in ws.get("items", []) if candidate.get("id") == item_id), None)
        except Exception as item_err:
            logger.debug("Could not load workstream item for HITL knowledge (%s/%s): %s", ws_name, item_id, item_err)

        reason = _bounded_text(getattr(resolved, "reason", ""), 300)
        note = _bounded_text(decision_note, 300).strip()
        item_title = _bounded_text((item or {}).get("title") or (item or {}).get("description") or "", 180)
        decision_label = decision_norm or "resolved"
        if note:
            summary = (
                f"Workstream {ws_name}/{item_id} was {decision_label} by {decided_by or 'unknown'} "
                f"with human guidance: {note}"
            )
        else:
            reason_part = f" under approval reason: {reason}" if reason else ""
            summary = (
                f"Workstream {ws_name}/{item_id} was {decision_label} by {decided_by or 'unknown'}"
                f"{reason_part}."
            )
        if item_title:
            summary = f"{summary} Item context: {item_title}"

        applies_when_parts = [
            f"Similar workstream item: {ws_name}",
            f"Human decision: {decision_label}",
        ]
        if reason:
            applies_when_parts.append(f"Approval reason: {reason}")

        tags = [
            "workstream",
            "hitl_feedback",
            "hitl_decision",
            _safe_tag(decision_label),
            _safe_tag(ws_name),
            _safe_tag(item_id),
            f"approval_{_safe_tag(approval_id)}",
        ]
        if skill:
            tags.append(_safe_tag(skill))
        tags = [tag for tag in dict.fromkeys(tags) if tag]

        knowledge_type = "correction" if decision_label == "reject" and note else "pattern"
        knowledge_id = memory.write_knowledge(
            knowledge_type=knowledge_type,
            summary=_bounded_text(summary, 700),
            applies_when="; ".join(applies_when_parts),
            source="hitl_feedback",
            status="pending_review",
            skill=skill,
            tags=tags,
            entity_keys=_workstream_hitl_entity_keys(
                approval_id=approval_id,
                ws_name=ws_name,
                item_id=item_id,
                resolved=resolved,
                item=item,
            ),
            user_query=reason,
        )
        logger.info(
            "Created HITL feedback knowledge candidate %s for %s/%s approval %s",
            knowledge_id, ws_name, item_id, approval_id,
        )
        return knowledge_id
    except Exception as knowledge_err:
        logger.warning("HITL feedback knowledge write skipped for %s/%s: %s", ws_name, item_id, knowledge_err)
        return None


def _workstream_suggested_actions(status: str) -> list[dict]:
    base = [{"id": "continue_chat", "label": "Continue", "kind": "chat", "side_effect": False}]
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
    if status == "awaiting_human":
        return base + [
            {"id": "approve", "label": "Approve", "kind": "approval", "side_effect": True},
            {"id": "reject", "label": "Reject", "kind": "approval", "side_effect": True},
        ]
    return base


def _clear_agent_pending_state(agent, *, clear_approval: bool = True) -> None:
    clear_fn = getattr(agent, "_clear_pending_state", None)
    if callable(clear_fn):
        clear_fn(clear_approval=clear_approval)
        return
    try:
        agent.pending_action = None
        agent.pending_tool_call = None
        if clear_approval:
            agent.approval_pending = None
    except Exception:
        pass


def _build_workstream_resume_context(resolved) -> str:
    ws_name, item_id = _workstream_ref(resolved)
    if not ws_name or not item_id:
        return ""

    lines = [
        "WORKSTREAM RESUME CONTEXT - DO NOT SWITCH ITEMS:",
        f"Workstream: {ws_name}",
        f"Item id: {item_id}",
    ]

    item = None
    try:
        store = _workstream_store_for(getattr(resolved, "tenant_id", "company"))
        ws = store.load(ws_name)
        item = next((candidate for candidate in ws.get("items", []) if candidate.get("id") == item_id), None)
    except Exception as ctx_err:
        logger.warning(
            "Could not load workstream item context for HITL resume (%s/%s): %s",
            ws_name, item_id, ctx_err,
        )

    if item:
        description = _bounded_text(item.get("description", ""), 700)
        if description:
            lines.append(f"Original task: {description}")
        title = _bounded_text(item.get("title", ""), 200)
        if title:
            lines.append(f"Title: {title}")
        if item.get("priority_metric") is not None:
            lines.append(f"Priority metric: {_bounded_text(item.get('priority_metric'), 80)}")
        acceptance_criteria = item.get("acceptance_criteria") or []
        if acceptance_criteria:
            lines.append("Acceptance criteria:")
            for criterion in acceptance_criteria[:8]:
                lines.append(f"- {_bounded_text(criterion, 240)}")
    else:
        lines.append("Original task: unavailable from workstream store; use this item id and approval context as the identity anchor.")

    ctx = getattr(resolved, "context", None) or {}
    skip_keys = {"workstream", "workstream_name", "item_id", "mission_item_id", "resume_kind"}
    scalar_context = []
    for key in sorted(ctx):
        value = ctx.get(key)
        if key in skip_keys or value is None or isinstance(value, (dict, list, tuple, set)):
            continue
        scalar_context.append(f"- {key}: {_bounded_text(value, 240)}")
    if scalar_context:
        lines.append("Approval context:")
        lines.extend(scalar_context[:12])

    lines.append(
        "Resume instruction: Complete ONLY the item above. Do not reuse invoice, vendor, "
        "amount, PO, or policy facts from any other workstream item, prior memory, or plan cache. "
        "If facts are missing or conflicting, fetch live evidence for this exact item id before concluding."
    )
    return "\n".join(lines)


def _format_workstream_resolution(
    *,
    status: str,
    decision: str,
    decided_by: str,
    approval_id: str,
    decision_note: str = "",
    result=None,
    error: str = "",
) -> str:
    from iaf_agent_skills.workstream_store import now_iso

    prefix = f"{decision.upper()} by {decided_by or 'unknown'} at {now_iso()}"
    if decision_note:
        prefix += f"; note: {_bounded_text(decision_note, 300)}"
    prefix += f"; approval: {approval_id[:8]}"
    if status == "done":
        return _bounded_text(f"{prefix}; resumed result: {_bounded_text(result, 700)}", 1000)
    return _bounded_text(f"{prefix}; resume failed: {_bounded_text(error, 700)}", 1000)


def _format_workstream_pause_resolution(
    *,
    decision: str,
    decided_by: str,
    approval_id: str,
    followup_approval_id: str,
    decision_note: str = "",
    result=None,
) -> str:
    from iaf_agent_skills.workstream_store import now_iso

    prefix = f"{decision.upper()} by {decided_by or 'unknown'} at {now_iso()}"
    if decision_note:
        prefix += f"; note: {_bounded_text(decision_note, 300)}"
    prefix += f"; approval: {approval_id[:8]}"
    prefix += f"; resumed worker paused for follow-up approval: {followup_approval_id[:8]}"
    return _bounded_text(f"{prefix}; pending result: {_bounded_text(result, 700)}", 1000)


def _prepare_followup_approval(agent, *, ws_name: str, item_id: str) -> dict | None:
    pending = getattr(agent, "approval_pending", None)
    if not isinstance(pending, dict) or not pending.get("approval_id"):
        return None
    pending = copy.deepcopy(pending)
    ctx = pending.get("context")
    if not isinstance(ctx, dict):
        ctx = {}
        pending["context"] = ctx
    ctx_ws = ctx.get("workstream_name") or ctx.get("workstream")
    ctx_item = ctx.get("mission_item_id") or ctx.get("item_id")
    if (ctx_ws and ctx_ws != ws_name) or (ctx_item and ctx_item != item_id):
        raise RuntimeError(
            "Follow-up HITL approval is scoped to a different workstream item: "
            f"pending={ctx_ws}/{ctx_item} current={ws_name}/{item_id} approval={pending.get('approval_id')}"
        )
    ctx["workstream_name"] = ws_name
    ctx["mission_item_id"] = item_id
    ctx["workstream"] = ws_name
    ctx["item_id"] = item_id
    agent.approval_pending = pending
    return pending


def _checkpoint_followup_hitl_sync(agent, tenant_id: str, user_id: str, skill_name: str) -> bool:
    try:
        from shared.state import checkpoint_hitl_if_needed

        loop = get_main_loop()
        if loop:
            future = asyncio.run_coroutine_threadsafe(
                checkpoint_hitl_if_needed(
                    agent,
                    tenant_id,
                    user_id,
                    skill_name or getattr(agent, "current_skill", "") or "general",
                    source="mission_mode",
                ),
                loop,
            )
            future.result(timeout=15)
        else:
            asyncio.run(checkpoint_hitl_if_needed(
                agent,
                tenant_id,
                user_id,
                skill_name or getattr(agent, "current_skill", "") or "general",
                source="mission_mode",
            ))
        return True
    except Exception as checkpoint_err:
        logger.warning("Follow-up HITL checkpoint failed during workstream resume: %s", checkpoint_err)
        return False


def _pause_workstream_item_sync(
    resolved,
    approval_id: str,
    *,
    followup_approval_id: str,
    decision: str,
    decided_by: str,
    decision_note: str = "",
    result=None,
) -> bool:
    ws_name, item_id = _workstream_ref(resolved)
    if not ws_name or not item_id:
        return False

    try:
        store = _workstream_store_for(getattr(resolved, "tenant_id", "company"))
        resolution = _format_workstream_pause_resolution(
            decision=decision,
            decided_by=decided_by,
            decision_note=decision_note,
            approval_id=approval_id,
            followup_approval_id=followup_approval_id,
            result=result,
        )
        store.update_item(
            ws_name,
            item_id,
            status="awaiting_human",
            resolution=resolution,
            escalated_approval_id=followup_approval_id,
            completed_at=None,
        )
        logger.info(
            "Workstream item paused for follow-up HITL after resume: %s/%s -> awaiting_human (%s)",
            ws_name, item_id, followup_approval_id,
        )
        return True
    except Exception as upd_err:
        logger.warning(
            "Failed to pause workstream item after follow-up HITL (%s/%s): %s",
            ws_name, item_id, upd_err,
        )
        return False


def _resume_runtime_continuation(
    *,
    ws_name: str,
    item_id: str,
    approval_id: str,
):
    """Continue the PAUSED runtime execution across a HITL resume.

    Why this exists: the pre-pause execution row stays status='awaiting_human' with
    completed_at=NULL and remains the NEWEST row for the item (get_item_executions
    orders by started_at DESC). The Execution Trace renders that latest runtime
    execution, so without this the trace permanently stops at the gated step and the
    post-approval steps are never persisted or streamed anywhere.

    We append the post-approval steps to that SAME execution and close it out, so the
    trace reads as one continuous run (intake → … → gate → approval → … → post_and_close).

    Returns (execution_id, original_started_at, step_cb, finalize, append_ledger). step_cb /
    finalize / append_ledger are no-ops when the runtime DB or mission-engine helpers are
    unavailable (never fatal).
    """
    def _noop_cb(_msg=None):
        return None

    def _noop_finalize(**_kwargs):
        return None

    def _noop_append(_tool_calls=None):
        return None

    if not ws_name or not item_id:
        return "", "", None, _noop_finalize, _noop_append

    try:
        from shared.config import SERVER_DIR as _SERVER_DIR
        from workstream_runtime.db import get_db, init_db_path
        from iaf_agent_skills.mission_engine import (
            _publish_step_event,
            _runtime_append_step,
            _status_callback_step,
            _tool_call_steps,
        )
        try:
            db = get_db()
        except RuntimeError:
            init_db_path(_SERVER_DIR)
            db = get_db()
    except Exception as exc:
        logger.debug("resume runtime continuation unavailable (non-fatal): %s", exc)
        return "", "", None, _noop_finalize, _noop_append

    # Locate the execution this approval paused — prefer an exact approval_id match,
    # else the newest row still parked on awaiting_human.
    exec_id = ""
    started_at = ""
    base_step = 0
    try:
        rows = db.get_item_executions(ws_name, item_id, limit=10) or []
        chosen = None
        for row in rows:
            ex = row.get("execution") or {}
            if str(ex.get("approval_id") or "") == approval_id:
                chosen = row
                break
        if chosen is None:
            for row in rows:
                ex = row.get("execution") or {}
                if str(ex.get("status") or "") == "awaiting_human":
                    chosen = row
                    break
        if chosen is not None:
            ex = chosen.get("execution") or {}
            exec_id = str(ex.get("execution_id") or "")
            started_at = str(ex.get("started_at") or "")
            for step in (chosen.get("steps") or []):
                try:
                    base_step = max(base_step, int(step.get("step_number") or 0))
                except (TypeError, ValueError):
                    continue
    except Exception as exc:
        logger.debug("resume runtime execution lookup skipped: %s", exc)

    if not exec_id:
        return "", "", None, _noop_finalize, _noop_append

    counter = [base_step]

    def step_cb(msg):
        """Persist + stream one post-approval step (fixes both the trace and live progress)."""
        try:
            counter[0] += 1
            step = _status_callback_step(msg, counter[0])
            step["step_number"] = counter[0]
            step = _runtime_append_step(exec_id, step)
            _publish_step_event(ws_name, item_id, execution_id=exec_id, step=step)
        except Exception as exc:
            logger.debug("resume step capture failed (non-fatal): %s", exc)

    def append_ledger(tool_calls):
        """Persist the post-approval steps under their REAL stage names.

        step_cb above only records the live progress chatter ("💭 Reasoning… step 2",
        "Step 5/5: post_and_close"). The Overview / Stage Outcomes panel deliberately rejects
        those as noise and looks for one row per stage named exactly after it, carrying the
        stage's business conclusion — which only the structured ledger has. Without this the
        stages that ran AFTER a pause show as "not reached" even though they completed.
        Mirrors the non-resumed path (mission_engine: _tool_call_steps -> _runtime_append_step).
        """
        if not tool_calls:
            return
        try:
            for tool_step in _tool_call_steps(tool_calls):
                counter[0] += 1
                numbered = dict(tool_step)
                numbered["step_index"] = counter[0]
                numbered["step_number"] = counter[0]
                step = _runtime_append_step(exec_id, numbered)
                _publish_step_event(ws_name, item_id, execution_id=exec_id, step=step)
        except Exception as exc:
            logger.debug("resume ledger capture failed (non-fatal): %s", exc)

    def finalize(*, status: str, result_summary: str = "", error_summary: str = "", trace_id: str = ""):
        """Close the continued execution with a real completed_at + total duration."""
        from datetime import timezone as _tz
        try:
            from iaf_agent_skills.workstream_store import now_iso
            completed = now_iso()
        except Exception:
            completed = datetime.now(_tz.utc).isoformat()
        duration_ms = 0
        try:
            if started_at:
                begin = datetime.fromisoformat(str(started_at).replace("Z", "+00:00"))
                end = datetime.fromisoformat(str(completed).replace("Z", "+00:00"))
                duration_ms = max(0, int((end - begin).total_seconds() * 1000))
        except Exception:
            duration_ms = 0
        fields = {
            "status": status,
            "completed_at": completed,
            "duration_ms": duration_ms,
            "result_summary": _bounded_text(result_summary, 500),
            "error_summary": _bounded_text(error_summary, 500),
        }
        if trace_id:
            fields["trace_id"] = trace_id
            fields["evidence_trace_id"] = trace_id
        try:
            db.update_execution(exec_id, **fields)
        except Exception as exc:
            logger.debug("resume runtime execution finalize skipped: %s", exc)

    return exec_id, started_at, step_cb, finalize, append_ledger


def _update_workstream_item_sync(
    resolved,
    approval_id: str,
    *,
    status: str,
    decision: str,
    decided_by: str,
    decision_note: str = "",
    result=None,
    error: str = "",
    resume_started_at: str = "",
    resume_trace_id: str = "",
    resume_execution_id: str = "",
) -> bool:
    ws_name, item_id = _workstream_ref(resolved)
    if not ws_name or not item_id:
        return False

    try:
        from iaf_agent_skills.workstream_store import now_iso

        store = _workstream_store_for(getattr(resolved, "tenant_id", "company"))
        now = now_iso()
        try:
            ws = store.load(ws_name)
            item_before = next((candidate for candidate in ws.get("items", []) if candidate.get("id") == item_id), {})
        except Exception:
            item_before = {}
        resolution = _format_workstream_resolution(
            status=status,
            decision=decision,
            decided_by=decided_by,
            decision_note=decision_note,
            approval_id=approval_id,
            result=result,
            error=error,
        )
        execution_id = resume_execution_id or f"wse_{uuid.uuid4().hex[:12]}"
        result_summary = _bounded_text(result if result is not None else resolution, 1000)
        started_at = resume_started_at or now
        duration_ms = 0
        try:
            if resume_started_at:
                _begin = datetime.fromisoformat(str(resume_started_at).replace("Z", "+00:00"))
                _end = datetime.fromisoformat(str(now).replace("Z", "+00:00"))
                duration_ms = max(0, int((_end - _begin).total_seconds() * 1000))
        except Exception:
            duration_ms = 0
        # Prefer the trace the resume actually ran under; fall back to the pre-pause trace.
        trace_id = (
            resume_trace_id
            or item_before.get("last_trace_id")
            or item_before.get("evidence_trace_id")
            or ""
        )
        ledger_entry = {
            "execution_id": execution_id,
            "execution_source": "hitl_resume",
            "attempt": int(item_before.get("attempts", 0) or 0),
            "status_before": item_before.get("status") or "awaiting_human",
            "status_after": status,
            "started_at": started_at,
            "completed_at": now,
            "duration_ms": duration_ms,
            "trace_id": trace_id,
            "evidence_trace_id": trace_id,
            "evidence_count": item_before.get("evidence_count") or 0,
            "approval_id": approval_id,
            "result_preview": result_summary if status == "done" else "",
            "error_preview": _bounded_text(error, 500),
            "steps": [],
        }
        patches = {
            "status": status,
            "resolution": resolution,
            "completed_at": now,
            "current_execution_id": execution_id,
            "last_result_summary": result_summary,
            "last_result_at": now,
            "suggested_actions": _workstream_suggested_actions(status),
        }
        if status == "done":
            patches.update({
                "escalated_approval_id": None,
                "last_failure_reason": None,
            })
        elif status == "failed":
            patches.update({
                "last_failure_reason": _bounded_text(error or resolution, 500),
            })
        store.append_item_execution(ws_name, item_id, ledger_entry, **patches)
        logger.info(
            "Workstream item finalized after HITL resume: %s/%s -> %s",
            ws_name, item_id, status,
        )
        return True
    except Exception as upd_err:
        logger.warning(
            "Failed to finalize workstream item after HITL resume (%s/%s): %s",
            ws_name, item_id, upd_err,
        )
        return False


async def _publish_workstream_event(
    ws_name: str,
    *,
    event_type: str,
    item_id: str,
    status: str,
    decision: str,
    decided_by: str,
    decision_note: str = "",
):
    try:
        from routers.workstreams import workstream_subscriptions

        await workstream_subscriptions.publish(ws_name, {
            "type": event_type,
            "workstream_name": ws_name,
            "item_id": item_id,
            "status": status,
            "decision": decision,
            "decided_by": decided_by,
            "decision_note": decision_note,
        })
    except Exception:
        pass


def _publish_workstream_event_sync(
    ws_name: str,
    *,
    event_type: str,
    item_id: str,
    status: str,
    decision: str,
    decided_by: str,
    decision_note: str = "",
):
    try:
        loop = asyncio.new_event_loop()
        loop.run_until_complete(_publish_workstream_event(
            ws_name,
            event_type=event_type,
            item_id=item_id,
            status=status,
            decision=decision,
            decided_by=decided_by,
            decision_note=decision_note,
        ))
        loop.close()
    except Exception:
        pass


async def _notify_chat_of_resolution(
    *,
    tenant_id: str,
    user_id: str,
    approval_id: str,
    status: str,
    decision: str,
    decided_by: str,
    reason: str = "",
    skill: str = "",
) -> bool:
    """Immediately tell the requesting user's chat session the approval outcome.

    A user waiting in chat for an urgent approval must learn approved/rejected in
    real time even when the decision is made elsewhere (e.g. an admin in the
    Command Center). The dashboard broadcast only reaches dashboard sockets; this
    pushes to the *originating* chat session via ``chat_registry`` (keyed by
    tenant+user). It fires at resolve time, independent of — and ahead of — the
    slower background resume, and covers reject / skip-resume paths that never
    produced a resume result. Best-effort: a disconnected socket must never break
    resolution, so failures are swallowed and reported as ``False``.
    """
    try:
        return await chat_registry.send_to_user(
            tenant_id or TENANT_ID,
            user_id or "",
            {
                "type": "hitl_approval_resolved",
                "approval_id": approval_id,
                "status": status,
                "decision": decision,
                "decided_by": decided_by,
                "reason": reason,
                "skill": skill,
                "timestamp": datetime.now().isoformat(),
            },
        )
    except Exception as notify_err:  # pragma: no cover - defensive
        logger.warning("chat resolution notify failed for %s: %s", user_id, notify_err)
        return False


def _trigger_workstream_synthesis_sync(ws_name: str, tenant_id: str) -> None:
    try:
        from shared.state import maybe_synthesize_research_workstream

        loop = get_main_loop()
        if loop:
            asyncio.run_coroutine_threadsafe(
                maybe_synthesize_research_workstream(ws_name, tenant_id),
                loop,
            )
    except Exception as syn_err:
        logger.debug("research synthesis trigger skipped: %s", syn_err)


@router.websocket("/ws/dashboard")
async def websocket_dashboard(websocket: WebSocket):
    """
    WebSocket for real-time dashboard updates.

    Pushes events:
      - approval_new / approval_resolved
      - task_started / task_completed
      - cron_started / cron_completed
      - snapshot (periodic full state refresh)
    """
    await websocket.accept()
    await dashboard.connect(websocket)

    # No identity binding on this socket: scope to the configured default tenant.
    ws_tenant = TENANT_ID
    try:
        _principal, ws_tenant, _user = await bind_websocket_identity(
            websocket, requested_tenant=websocket.query_params.get("tenant_id")
        )
    except HTTPException:
        await dashboard.disconnect(websocket)
        await websocket.close(code=4401)
        return
    except Exception as exc:
        logger.warning("Dashboard WS identity binding failed: %s", exc)
        await dashboard.disconnect(websocket)
        await websocket.close(code=4401)
        return

    try:
        summary = await _build_dashboard_summary(ws_tenant)
        await websocket.send_json({"type": "snapshot", **summary})

        # Keep alive — listen for pings or close
        while True:
            try:
                data = await websocket.receive_json()
                # Client can request a refresh
                if data.get("type") == "refresh":
                    summary = await _build_dashboard_summary(ws_tenant)
                    await websocket.send_json({"type": "snapshot", **summary})
            except Exception:
                break
    except WebSocketDisconnect:
        pass
    finally:
        await dashboard.disconnect(websocket)


@router.websocket("/ws/twin")
async def websocket_twin(websocket: WebSocket):
    """
    WebSocket for live Digital Twin dashboard updates.

    Pushes events:
      - task_started / task_completed / task_error
      - hitl_resolved
      - refresh (periodic snapshot from twin_telemetry.db)
    """
    if not twin_broadcaster:
        await websocket.close(code=1008, reason="Twin telemetry disabled")
        return

    await websocket.accept()
    await twin_broadcaster.connect(websocket)

    try:
        while True:
            try:
                data = await websocket.receive_json()
                if data.get("type") == "ping":
                    await websocket.send_json({"type": "pong"})
            except Exception:
                break
    except WebSocketDisconnect:
        pass
    finally:
        await twin_broadcaster.disconnect(websocket)


def _build_kernel_queue(tenant_id: str) -> list[dict]:
    """Collect kernel pending_action rows for one tenant (unscoped)."""
    queue = []
    now = datetime.now()
    prefix = f"{tenant_id}:"

    # Scan templates and per-session clones so a user's multiple pending sessions
    # each surface as a distinct row that can be discarded by session_id.
    candidates: list[tuple[str, object]] = [
        (key, agent) for key, agent in state.agents.items() if key.startswith(prefix)
    ]
    for key, pool in getattr(state, "_session_pool", {}).items():
        if key.startswith(prefix):
            candidates.extend((key, agent) for agent in pool.values())

    seen: set[int] = set()
    for key, agent in candidates:
        if id(agent) in seen:
            continue
        seen.add(id(agent))
        if not agent.pending_action:
            continue
        if stream_intercept_approval_id(agent):
            continue
        parts = key.split(":", 3)
        row_tenant = parts[0] if len(parts) > 0 else "unknown"
        agent_id = parts[1] if len(parts) > 1 else "unknown"
        user_id = parts[2] if len(parts) > 2 else "unknown"

        ts = agent.pending_action.get("timestamp")
        if ts:
            if isinstance(ts, str):
                try:
                    created = datetime.fromisoformat(ts)
                except ValueError:
                    created = now
            elif isinstance(ts, datetime):
                created = ts
            else:
                created = now
            wait_seconds = (now - created).total_seconds()
        else:
            wait_seconds = 0

        queue.append({
            "tenant_id": row_tenant,
            "agent_id": agent_id,
            "user_id": user_id,
            "session_id": getattr(agent, "session_id", "") or "",
            "operation": agent.pending_action.get("operation", "unknown"),
            "target": agent.pending_action.get("target", "unknown"),
            "command": agent.pending_action.get("command", ""),
            "skill": agent.pending_action.get("skill", ""),
            "wait_seconds": round(wait_seconds),
            "sla_remaining_seconds": max(0, round(600 - wait_seconds)),
            "created_at": str(ts) if ts else None,
        })

    queue.sort(key=lambda x: x["wait_seconds"], reverse=True)
    return queue


@router.get("/api/approvals/queue")
async def get_approval_queue(request: Request, tenant_id: str | None = None):
    """
    Get pending kernel approvals for the caller's tenant (and user unless admin).

    Scans SessionState for agents with non-null pending_action.
    Returns a prioritized list with SLA countdown.
    """
    principal, resolved_tenant, _agent_id, _user_id = require_scoped_identity(
        request, requested_tenant=tenant_id
    )
    queue = scope_approval_records(
        _build_kernel_queue(resolved_tenant),
        principal=principal,
        tenant_id=resolved_tenant,
    )
    return {"queue": queue, "total": len(queue)}


@router.post("/api/approvals/{user_id}/approve")
async def approve_user_action(user_id: str, request: Request, tenant_id: str = "company", agent_id: str = "enterprise_agent"):
    """Approve a pending action for a specific user (cross-user approval for ops team)."""
    # Deciding another user's held action is the approver right from policies.yaml, scoped
    # to the caller's own tenant (the query-string tenant is only honoured if it matches).
    _principal, tenant_id, _agent, _approver = require_scoped_identity(
        request,
        requested_tenant=tenant_id,
        action="approve",
        resource_type="approval",
        resource_id=f"pending:{user_id}",
        context={"requested_by": user_id, "source": "kernel_approval", "decision": "approve"},
    )
    user_role = getattr(request.state, "role", None) or "user"
    # Target the agent instance that actually holds the pending (a session clone),
    # not the bare template (state.get_or_create) which usually has none.
    pendings = state.find_agents_with_pending(tenant_id, agent_id, user_id, user_role=user_role)
    # Fallback: an admin approving a regular user's pending action — the target
    # agent is keyed under role="user", not the approver's role.
    if not pendings and user_role != "user":
        pendings = state.find_agents_with_pending(tenant_id, agent_id, user_id, user_role="user")
    if not pendings:
        raise HTTPException(404, "No pending action for this user")
    if len(pendings) > 1:
        raise HTTPException(409, "Multiple pending actions for this user — resolve from the specific chat session (pass session_id)")
    agent = pendings[0]

    _resolved_uid = getattr(agent, "user_id", None) or user_id
    _prior_id = stream_intercept_approval_id(agent)
    response = agent.execute_approved_action()
    # Reconcile the durable row (resolve+delete; re-checkpoint if re-paused), then persist
    # the cleaned state so a Redis reload can't resurrect the consumed pending.
    await reconcile_stream_intercept_durable(agent, _prior_id, tenant_id, _resolved_uid, "approve")
    _record_hitl_reward_best_effort(
        tenant_id=tenant_id,
        agent_id=agent_id,
        approval_id=str(_prior_id or getattr(agent, "session_id", "") or user_id),
        decision="approve",
        decided_by=_resolved_uid,
        status="resolved",
        source="kernel_approval",
    )
    await state.save_agent_state(agent, tenant_id, agent_id, _resolved_uid)

    await dashboard.broadcast({
        "type": "approval_resolved",
        "user_id": user_id,
        "action": "approved",
        "operation": "approved_action",
    })

    # A resumed turn may re-pause on a new dangerous call; surface it immediately.
    _pa = getattr(agent, "pending_action", None)
    if _pa:
        await dashboard.broadcast({
            "type": "approval_new",
            "user_id": user_id,
            "skill": _pa.get("skill"),
            "operation": _pa.get("operation"),
            "target": _pa.get("target"),
        })
        return {"response": response, "approved": True, "user_id": user_id, "pending_again": True}

    return {"response": response, "approved": True, "user_id": user_id}


@router.post("/api/approvals/{user_id}/reject")
async def reject_user_action(user_id: str, request: Request, tenant_id: str = "company", agent_id: str = "enterprise_agent"):
    """Reject a pending action for a specific user (cross-user rejection for ops team)."""
    # Deciding another user's held action is the approver right from policies.yaml, scoped
    # to the caller's own tenant (the query-string tenant is only honoured if it matches).
    _principal, tenant_id, _agent, _approver = require_scoped_identity(
        request,
        requested_tenant=tenant_id,
        action="approve",
        resource_type="approval",
        resource_id=f"pending:{user_id}",
        context={"requested_by": user_id, "source": "kernel_approval", "decision": "reject"},
    )
    user_role = getattr(request.state, "role", None) or "user"
    pendings = state.find_agents_with_pending(tenant_id, agent_id, user_id, user_role=user_role)
    if not pendings and user_role != "user":
        pendings = state.find_agents_with_pending(tenant_id, agent_id, user_id, user_role="user")
    if not pendings:
        raise HTTPException(404, "No pending action for this user")
    if len(pendings) > 1:
        raise HTTPException(409, "Multiple pending actions for this user — resolve from the specific chat session (pass session_id)")
    agent = pendings[0]

    _resolved_uid = getattr(agent, "user_id", None) or user_id
    _prior_id = stream_intercept_approval_id(agent)
    response = agent.reject_pending_action()
    await reconcile_stream_intercept_durable(agent, _prior_id, tenant_id, _resolved_uid, "reject")
    _record_hitl_reward_best_effort(
        tenant_id=tenant_id,
        agent_id=agent_id,
        approval_id=str(_prior_id or getattr(agent, "session_id", "") or user_id),
        decision="reject",
        decided_by=_resolved_uid,
        status="resolved",
        source="kernel_approval",
    )
    await state.save_agent_state(agent, tenant_id, agent_id, _resolved_uid)

    await dashboard.broadcast({
        "type": "approval_resolved",
        "user_id": user_id,
        "action": "rejected",
        "operation": "rejected_action",
    })

    return {"response": response, "approved": False, "user_id": user_id}


@router.delete("/api/approvals/{user_id}")
async def delete_user_action(
    user_id: str, request: Request, tenant_id: str | None = None,
    agent_id: str = "enterprise_agent", session_id: str | None = None,
    admin: dict = Depends(require_admin),
):
    """Discard a pending kernel action without executing it (admin-only).

    Unlike reject, this drops the held action and clears the durable
    stream-intercept row so the queue no longer surfaces it. When a user has
    multiple pending sessions, pass ``session_id`` to target a specific one.
    """
    _principal, tenant_id, agent_id, _caller = require_scoped_identity(
        request, requested_tenant=tenant_id, requested_agent=agent_id
    )
    user_role = getattr(request.state, "role", None) or "user"
    pendings = state.find_agents_with_pending(tenant_id, agent_id, user_id, user_role=user_role)
    if not pendings and user_role != "user":
        pendings = state.find_agents_with_pending(tenant_id, agent_id, user_id, user_role="user")
    if session_id and pendings:
        pendings = [a for a in pendings if getattr(a, "session_id", None) == session_id]
    if not pendings:
        raise HTTPException(404, "No pending action for this user")
    if len(pendings) > 1:
        raise HTTPException(409, "Multiple pending actions for this user — pass session_id to target a specific chat session")
    agent = pendings[0]

    _resolved_uid = getattr(agent, "user_id", None) or user_id
    _prior_id = stream_intercept_approval_id(agent)
    # Delete the durable row first (the pending-only CAS refuses if a resolver already won); clear memory only after.
    if _prior_id:
        deleted = await approval_store.delete_approval(_prior_id, expected_tenant_id=tenant_id)
        if not deleted:
            raise HTTPException(409, "Pending action was resolved concurrently \u2014 not discarded")
    _clear_agent_pending_state(agent, clear_approval=True)
    await state.save_agent_state(agent, tenant_id, agent_id, _resolved_uid)

    await dashboard.broadcast({
        "type": "approval_resolved",
        "user_id": user_id,
        "action": "deleted",
        "operation": "deleted_action",
    })

    return {"deleted": True, "user_id": user_id}


@router.get("/api/dashboard/summary")
async def get_dashboard_summary(request: Request, tenant_id: str | None = None):
    """
    Aggregated dashboard summary for initial load, scoped to the caller's tenant.

    Returns:
      - Active sessions count
      - Pending approvals count
      - Task stats from Redis
      - Cron job summary
      - Dashboard WebSocket client count
      - Per-agent liveness for the resolved tenant
    """
    _principal, resolved_tenant, _agent_id, _user_id = require_scoped_identity(
        request, requested_tenant=tenant_id
    )
    return await _build_dashboard_summary(resolved_tenant)


@router.get("/api/dashboard/ops-summary")
async def get_dashboard_ops_summary(request: Request, tenant_id: str | None = None):
    """Richer Dashboard V2 command-center summary.

    This additive endpoint preserves the legacy `/api/dashboard/summary`
    contract while giving the V2 Overview a bounded, adapter-composed
    operations snapshot.
    """
    _principal, resolved_tenant, _agent_id, user_id = require_scoped_identity(
        request, requested_tenant=tenant_id
    )
    scoped_user = None if is_admin_principal(_principal) else (_principal.email or user_id)
    return await build_default_ops_summary(tenant_id=resolved_tenant, user_id=scoped_user)


def _agent_summary_entry(key: str, agent) -> dict:
    """One session's summary row, with its identifiers served rather than implied.

    The key is ``tenant:agent:user:role``. This used to be parsed with
    ``key.split(":", 2)``, which is wrong for a four-part key — it left the role
    glued onto the user id ("amy@iaf.local:admin") — and the agent id was never
    emitted at all, so the browser reconstructed it from ``key`` itself. That
    made an internal cache key an unversioned API contract; both ends are now
    given the fields explicitly.
    """
    parts = key.split(":")
    tenant_id = parts[0] if len(parts) > 0 else ""
    agent_id = parts[1] if len(parts) > 1 else ""
    user_id = parts[2] if len(parts) > 2 else key
    user_role = parts[3] if len(parts) > 3 else ""
    return {
        "key": key,
        "tenant_id": tenant_id,
        "agent_id": agent_id,
        "user_id": user_id,
        "user_role": user_role,
        "current_skill": agent.current_skill,
        "has_pending": agent.pending_action is not None,
        "history_length": len(agent.conversation_history),
        "auto_run": agent.auto_run,
    }


async def _build_dashboard_summary(tenant_id: str | None = None) -> dict:
    """Build dashboard summary dict (reused by HTTP + WS snapshot).

    Always called from an async context (WS handler / async route), so both
    lookups below run as real awaits — neither may block the event loop.

    Everything is scoped to one tenant. `state.agents` is a process-wide cache
    keyed `tenant:agent:user:role`, so an unscoped read reported other tenants'
    sessions in `agents`/`active_sessions` while liveness was computed for the
    configured default — inconsistent with each other and a cross-tenant leak.
    Callers pass the authenticated tenant; the configured default is only the
    fallback for callers that genuinely have no principal.
    """
    scope = tenant_id or TENANT_ID
    prefix = f"{scope}:"
    scoped_agents = {k: a for k, a in state.agents.items() if k.startswith(prefix)}

    active_sessions = len(scoped_agents)

    pending_count = sum(1 for a in scoped_agents.values() if a.pending_action)

    # Task stats from Redis (task_integration uses an async Redis client)
    try:
        task_stats = await task_integration.get_stats()
    except Exception:
        task_stats = {"error": "Redis unavailable"}

    # Offload to a thread: the cron store is a synchronous Redis client.
    try:
        cron_status = await asyncio.to_thread(cron_scheduler.get_status)
    except Exception:
        cron_status = {"total_jobs": 0, "running_jobs": 0, "error": "Redis unavailable"}

    # Active agent details — same tenant scope as the counts above
    agents_detail = [_agent_summary_entry(key, agent) for key, agent in scoped_agents.items()]

    # Per-agent liveness, decided by the state service against a bounded idle
    # window rather than by the browser observing that a cache entry exists.
    try:
        agent_liveness = state.agent_liveness(scope)
    except Exception:
        agent_liveness = {}

    return {
        "tenant_id": scope,
        "active_sessions": active_sessions,
        "pending_approvals": pending_count,
        "task_stats": task_stats,
        "cron_jobs": cron_status.get("total_jobs", 0),
        "cron_running": cron_status.get("running_jobs", 0),
        "dashboard_clients": dashboard.client_count,
        "agents": agents_detail,
        "agent_liveness": agent_liveness,
        "timestamp": datetime.now().isoformat(),
    }


@router.get("/api/hitl/pending")
async def get_hitl_pending(
    request: Request,
    tenant_id: str | None = None,
    workstream: str | None = None,
):
    """
    Get pending HITL approvals from Redis, scoped to the caller.

    Returns richer approval cards than the kernel-level approval queue.
    Includes: reason, context, options, urgency, SLA, rule info.
    """
    principal, resolved_tenant, _agent_id, _user_id = require_scoped_identity(
        request, requested_tenant=tenant_id
    )
    try:
        # newest_first + a generous limit so a recent approval is never starved behind a
        # backlog of older/stale entries (the "no approve button" bug), then filter by workstream.
        approvals = await approval_store.get_pending(resolved_tenant, limit=500, newest_first=True)
        cards = []
        for approval in approvals:
            ws_name, _item_id = _approval_workstream_ref(approval)
            if workstream:
                if ws_name == workstream:
                    cards.append(approval.to_dict())
                continue
            if not _is_stream_intercept_approval(approval):
                cards.append(approval.to_dict())
        scoped = scope_approval_records(cards, principal=principal, tenant_id=resolved_tenant)
        return {"approvals": scoped, "total": len(scoped)}
    except Exception as e:
        logger.error("get_hitl_pending failed: %s", e, exc_info=True)
        return {"approvals": [], "total": 0, "error": "An internal error occurred"}


@router.get("/api/hitl/history")
async def get_hitl_history(request: Request, tenant_id: str | None = None, limit: int = 50):
    """Get recent resolved HITL approvals, scoped to the caller."""
    principal, resolved_tenant, _agent_id, _user_id = require_scoped_identity(
        request, requested_tenant=tenant_id
    )
    history = await approval_store.get_history(resolved_tenant, limit)
    scoped = scope_approval_records(history, principal=principal, tenant_id=resolved_tenant)
    # History entries are snapshots from resolve time; overlay the live outcome from the approval hash.
    for entry in scoped:
        aid = entry.get("id") if isinstance(entry, dict) else None
        if not aid:
            continue
        try:
            live = await approval_store.get_approval(aid)
            if not live:
                continue
            for _f in ("execution_status", "result_summary", "trace_id",
                       "error_preview", "completed_at"):
                _val = getattr(live, _f, None)
                if _val:
                    entry[_f] = _val
        except Exception:
            continue
    return {"history": scoped, "total": len(scoped)}


@router.get("/api/hitl/stats")
async def get_hitl_stats(request: Request, tenant_id: str | None = None, limit: int = 200):
    """Get HITL approval queue statistics from the caller's scoped view."""
    principal, resolved_tenant, _agent_id, _user_id = require_scoped_identity(
        request, requested_tenant=tenant_id
    )
    try:
        pending_objs = await approval_store.get_pending(resolved_tenant, limit=limit)
        pending_cards = [
            approval.to_dict()
            for approval in pending_objs
            if not _is_stream_intercept_approval(approval)
        ]
        history = await approval_store.get_history(resolved_tenant, limit=limit)
        scoped_pending = scope_approval_records(
            pending_cards, principal=principal, tenant_id=resolved_tenant
        )
        scoped_history = scope_approval_records(
            history, principal=principal, tenant_id=resolved_tenant
        )
        return compute_hitl_stats(
            scoped_pending,
            scoped_history,
            tenant_id=resolved_tenant,
        )
    except Exception as e:
        logger.error("get_hitl_stats failed: %s", e, exc_info=True)
        return {"connected": False, "error": "An internal error occurred"}


@router.get("/api/hitl/{approval_id}")
async def get_hitl_approval(approval_id: str):
    """Get a single HITL approval by ID."""
    approval = await approval_store.get_approval(approval_id)
    if not approval:
        raise HTTPException(404, f"Approval {approval_id} not found")
    return approval.to_dict()


def _annotate_outcome_sync(approval_id, execution_status, *, result_summary="", trace_id="", error_preview=""):
    """Best-effort: write the post-approval execution outcome onto the approval
    record (Quick Win 'A'). Runs from the sync resume thread via the main loop.
    Never raises — outcome visibility must not break the resume."""
    try:
        _loop = get_main_loop()
        if not _loop:
            return
        fut = asyncio.run_coroutine_threadsafe(
            approval_store.annotate_outcome(
                approval_id,
                execution_status=execution_status,
                result_summary=_bounded_text(result_summary, 1000) if result_summary else "",
                trace_id=trace_id or "",
                error_preview=_bounded_text(error_preview, 500) if error_preview else "",
            ),
            _loop,
        )
        fut.result(timeout=10)
    except Exception as exc:
        logger.warning("annotate_outcome_sync failed for %s: %s", approval_id, exc)


@router.delete("/api/hitl/history/{approval_id}")
async def delete_hitl_history_entry(
    request: Request, approval_id: str, tenant_id: str | None = None,
    admin: dict = Depends(require_admin),
):
    """Remove a single resolved approval from the tenant's HITL history."""
    _principal, resolved_tenant, _agent_id, _user_id = require_scoped_identity(
        request, requested_tenant=tenant_id
    )
    removed = await approval_store.delete_history_entry(resolved_tenant, approval_id)
    if not removed:
        raise HTTPException(404, f"History entry {approval_id} not found")
    return {"deleted": True, "approval_id": approval_id}


@router.delete("/api/hitl/{approval_id}")
async def delete_hitl_approval(
    request: Request, approval_id: str, tenant_id: str | None = None,
    admin: dict = Depends(require_admin),
):
    """Permanently discard a pending HITL approval and its checkpointed state."""
    _principal, resolved_tenant, _agent_id, _user_id = require_scoped_identity(
        request, requested_tenant=tenant_id
    )
    # Stream-intercept rows back a paused agent: use the discard path that clears its state.
    existing = await approval_store.get_approval(approval_id)
    if (
        existing
        and getattr(existing, "tenant_id", None) == resolved_tenant
        and _is_stream_intercept_approval(existing)
    ):
        raise HTTPException(
            409,
            "Stream-intercept approval is bound to a paused interactive agent; "
            "discard it via DELETE /api/approvals/{user_id} so the agent state is cleared.",
        )
    deleted = await approval_store.delete_approval(
        approval_id, expected_tenant_id=resolved_tenant
    )
    if not deleted:
        raise HTTPException(404, f"Approval {approval_id} not found")
    return {"deleted": True, "approval_id": approval_id}


def _resume_agent_from_hitl_sync(resolved, agent_state, decision, decided_by, decision_note, approval_id):
    """
    Background task: resume agent after HITL approval.
    Runs synchronously in a thread pool (agent.run is blocking).
    """
    try:
        tenant_id = resolved.tenant_id
        user_id = resolved.user_id
        agent_id = "enterprise_agent"

        ws_name, item_id = _workstream_ref(resolved)
        resume_ctx = getattr(resolved, "context", None) or {}
        resume_kind = resume_ctx.get("resume_kind")

        base_agent = state.get_or_create(tenant_id, agent_id, user_id, user_role="user")
        agent = _agent_for_hitl_resume(base_agent, approval_id=approval_id, ws_name=ws_name, item_id=item_id)
        # Keep the live history unless a fresh clone was made; the approval snapshot may be stale.
        agent.import_state(agent_state, preserve_history=(agent is base_agent))
        _annotate_outcome_sync(approval_id, "executing")
        if resume_kind == "stream_intercept":
            agent.approval_pending = None
        else:
            _clear_agent_pending_state(agent, clear_approval=True)
        agent._hitl_decision_injected = True
        hook_runner = getattr(agent, "hook_runner", None)
        try:
            session_ctx = agent._build_session_ctx() if hasattr(agent, "_build_session_ctx") else {}
        except Exception:
            session_ctx = {}
        session_ctx = {
            **(session_ctx or {}),
            "tenant_id": tenant_id,
            "agent_id": agent_id,
            "user_id": user_id,
            "skill_name": getattr(resolved, "skill", "") or session_ctx.get("skill_name", ""),
            "current_skill": getattr(resolved, "skill", "") or session_ctx.get("current_skill", "") or session_ctx.get("skill_name", ""),
            "entrypoint": "hitl_resume",
        }
        if ws_name and item_id:
            session_ctx.update({
                "workstream_name": ws_name,
                "mission_item_id": item_id,
            })

        if hook_runner:
            try:
                hook_runner.run_on_approval_resolved(
                    approval_id=approval_id,
                    decision=decision,
                    decided_by=decided_by,
                    decision_note=decision_note,
                    reason=getattr(resolved, "reason", ""),
                    session_ctx=session_ctx,
                )
            except Exception as hook_err:
                logger.warning("HITL approval resolved hook failed (non-fatal): %s", hook_err)

        # Attach service principal so external access gates are enforced during resume
        try:
            from security.dependencies import make_service_principal, make_agent_entitlement_checker
            _hitl_principal = make_service_principal(tenant_id, "hitl_resume", user_id=user_id)
            agent.set_entitlement_context(_hitl_principal, make_agent_entitlement_checker(_hitl_principal))
            agent._telemetry_entrypoint = "hitl_resume"
        except Exception as _ent_err:
            logger.warning("HITL resume entitlement context setup failed (non-fatal): %s", _ent_err)

        decision_upper = decision.upper()
        note_part = f"\nNote: {decision_note}" if decision_note else ""
        injection = (
            f"[HUMAN DECISION] The approval '{resolved.reason}' was {decision_upper} "
            f"by {decided_by}.{note_part}\n"
            f"Please continue with the task accordingly."
        )
        if resolved.status == "approved":
            injection += (
                f" Human approval was granted by {decided_by}. "
                "Approval decision: approve. The requested action is authorized — proceed."
            )
        else:
            injection += " The requested action was denied — do NOT proceed. Inform the user."
        workstream_resume_context = _build_workstream_resume_context(resolved)
        if workstream_resume_context:
            injection += f"\n\n{workstream_resume_context}"

        if hook_runner:
            try:
                gate = hook_runner.run_before_approval_resume(
                    approval_id=approval_id,
                    decision=decision,
                    decided_by=decided_by,
                    decision_note=decision_note,
                    reason=getattr(resolved, "reason", ""),
                    session_ctx=session_ctx,
                )
            except Exception as hook_err:
                logger.warning("HITL before-resume hook failed (non-fatal): %s", hook_err)
                gate = None
            if getattr(gate, "blocked", False):
                block_reason = getattr(gate, "reason", "") or "approval resume blocked by policy"
                agent._hitl_decision_injected = False
                _annotate_outcome_sync(approval_id, "failed", error_preview=block_reason)
                ws_name, item_id = _workstream_ref(resolved)
                if _update_workstream_item_sync(
                    resolved,
                    approval_id,
                    status="failed",
                    decision=decision,
                    decided_by=decided_by,
                    decision_note=decision_note,
                    error=block_reason,
                ) and ws_name and item_id:
                    _publish_workstream_event_sync(
                        ws_name,
                        event_type="item_resolved",
                        item_id=item_id,
                        status="failed",
                        decision=decision,
                        decided_by=decided_by,
                        decision_note=decision_note,
                    )
                    _trigger_workstream_synthesis_sync(ws_name, tenant_id)
                try:
                    hook_runner.run_after_approval_resume(
                        approval_id=approval_id,
                        decision=decision,
                        decided_by=decided_by,
                        decision_note=decision_note,
                        reason=getattr(resolved, "reason", ""),
                        resume_status="blocked",
                        session_ctx=session_ctx,
                        error_msg=block_reason,
                    )
                except Exception as hook_err:
                    logger.warning("HITL after-resume blocked hook failed (non-fatal): %s", hook_err)
                try:
                    import asyncio as _aio
                    _loop = _aio.new_event_loop()
                    _loop.run_until_complete(
                        chat_registry.send_to_user(tenant_id, user_id, {
                            "type": "response",
                            "content": f"Approval processed, but resume was blocked: {block_reason}",
                            "skill": resolved.skill,
                            "hitl_resumed": False,
                            "approval_id": approval_id,
                            "decision": decision,
                            "decided_by": decided_by,
                            "timestamp": datetime.now().isoformat(),
                        })
                    )
                    _loop.close()
                except Exception as push_err:
                    logger.warning("Could not push blocked HITL resume to chat WS: %s", push_err)
                _record_hitl_reward_best_effort(
                    tenant_id=tenant_id,
                    agent_id=agent_id,
                    approval_id=approval_id,
                    decision="resume_blocked",
                    decided_by=decided_by,
                    reason=block_reason,
                    context=resume_ctx,
                    status="blocked",
                    source="hitl_resume",
                )
                try:
                    _loop = get_main_loop()  # live ref — imported _main_loop copy stays None
                    if _loop:
                        delete_future = asyncio.run_coroutine_threadsafe(
                            approval_store.delete_agent_state(approval_id),
                            _loop,
                        )
                        delete_future.result(timeout=15)
                except Exception as cleanup_err:
                    logger.warning("HITL blocked cleanup warning: %s", cleanup_err)
                return

        # Defaults so the error handler below can reference these even if the resume
        # blows up before they are assigned.
        _resume_exec_id = ""
        _resume_exec_started = ""
        _resume_step_cb = None

        def _resume_finalize(**_kwargs):
            return None

        def _resume_append_ledger(_tool_calls=None):
            return None

        try:
            _resume_skill = getattr(resolved, "skill", "") or session_ctx.get("skill_name", "") or None
            # Continue the paused execution so post-approval steps append to the same trace.
            _rs_ws, _rs_item = _workstream_ref(resolved)
            (
                _resume_exec_id,
                _resume_exec_started,
                _resume_step_cb,
                _resume_finalize,
                _resume_append_ledger,
            ) = _resume_runtime_continuation(
                ws_name=_rs_ws,
                item_id=_rs_item,
                approval_id=approval_id,
            )
            # Cold resume of a stream-intercept block runs the exact held call, not a natural-language re-plan.
            if resume_kind == "stream_intercept":
                if str(decision).lower() == "approve" or getattr(resolved, "status", "") == "approved":
                    result = agent.resume_approved_tool_call()
                    if workstream_resume_context and ws_name and item_id:
                        if str(result).startswith("❌ No pending tool call"):
                            raise RuntimeError("Missing checkpointed pending tool call for follow-up approval")
                        _clear_agent_pending_state(agent, clear_approval=True)
                        continuation = (
                            "[APPROVED FOLLOW-UP TOOL RESULT] The previously blocked tool action "
                            f"for approval '{resolved.reason}' was APPROVED by {decided_by}.\n"
                            f"Tool execution result:\n{_bounded_text(result, 1200)}\n\n"
                            "Use this tool result as already-verified evidence. Continue the workstream item "
                            "to completion; do not re-run the same tool unless genuinely necessary.\n\n"
                            f"{workstream_resume_context}"
                        )
                        run_kwargs = {"skip_memory": True, "light_mode": True}
                        if _resume_step_cb:
                            run_kwargs["status_callback"] = _resume_step_cb
                        if _resume_skill:
                            result = agent.run(continuation, skill_name=_resume_skill, **run_kwargs)
                        else:
                            result = agent.run(continuation, **run_kwargs)
                else:
                    result = agent.reject_pending_tool_call()
            else:
                # Pin the resume to the approval's skill so it is not re-routed as a fresh query.
                run_kwargs = {"skip_memory": True, "light_mode": True} if workstream_resume_context else {}
                if _resume_step_cb:
                    run_kwargs["status_callback"] = _resume_step_cb
                if workstream_resume_context:
                    run_kwargs["return_tool_calls"] = True
                if _resume_skill:
                    result = agent.run(injection, skill_name=_resume_skill, **run_kwargs)
                else:
                    result = agent.run(injection, **run_kwargs)
                if isinstance(result, tuple):
                    result, _resume_tool_calls = result[0], (result[1] or [])
                    _resume_append_ledger(_resume_tool_calls)

            ws_name, item_id = _workstream_ref(resolved)
            followup_approval = None
            if workstream_resume_context and ws_name and item_id:
                followup_approval = _prepare_followup_approval(agent, ws_name=ws_name, item_id=item_id)
                if not followup_approval and "Confirmation Required" in str(result):
                    raise RuntimeError("Resumed worker requested follow-up approval but no durable approval was created")
            if followup_approval:
                followup_id = followup_approval["approval_id"]
                _checkpoint_followup_hitl_sync(
                    agent,
                    tenant_id,
                    user_id,
                    followup_approval.get("skill") or _resume_skill or getattr(resolved, "skill", ""),
                )
                if hook_runner:
                    try:
                        hook_runner.run_after_approval_resume(
                            approval_id=approval_id,
                            decision=decision,
                            decided_by=decided_by,
                            decision_note=decision_note,
                            reason=getattr(resolved, "reason", ""),
                            resume_status="paused_for_followup_approval",
                            session_ctx=session_ctx,
                        )
                    except Exception as hook_err:
                        logger.warning("HITL after-resume paused hook failed (non-fatal): %s", hook_err)
                if _pause_workstream_item_sync(
                    resolved,
                    approval_id,
                    followup_approval_id=followup_id,
                    decision=decision,
                    decided_by=decided_by,
                    decision_note=decision_note,
                    result=result,
                ) and ws_name and item_id:
                    _publish_workstream_event_sync(
                        ws_name,
                        event_type="item_resolved",
                        item_id=item_id,
                        status="awaiting_human",
                        decision=decision,
                        decided_by=decided_by,
                        decision_note=decision_note,
                    )
                _record_hitl_reward_best_effort(
                    tenant_id=tenant_id,
                    agent_id=agent_id,
                    approval_id=approval_id,
                    decision="paused_for_followup_approval",
                    decided_by=decided_by,
                    reason=getattr(resolved, "reason", ""),
                    context=resume_ctx,
                    status="awaiting_human",
                    source="hitl_resume",
                )
                return
            if hook_runner:
                try:
                    hook_runner.run_after_approval_resume(
                        approval_id=approval_id,
                        decision=decision,
                        decided_by=decided_by,
                        decision_note=decision_note,
                        reason=getattr(resolved, "reason", ""),
                        resume_status="success",
                        session_ctx=session_ctx,
                    )
                except Exception as hook_err:
                    logger.warning("HITL after-resume success hook failed (non-fatal): %s", hook_err)
            final_status = "done" if getattr(resolved, "status", "") == "approved" else "failed"
            final_error = "" if final_status == "done" else "approval was rejected"
            _outcome_status = ("done" if getattr(resolved, "status", "") == "approved"
                               else "rejected" if getattr(resolved, "status", "") == "rejected"
                               else "failed")
            _annotate_outcome_sync(
                approval_id,
                _outcome_status,
                result_summary=str(result) if result is not None else "",
                trace_id=getattr(agent, "_active_trace_id", "") or "",
                error_preview=final_error,
            )
            # Close the continued runtime execution (real completed_at + total duration),
            # so it stops looking like it is still parked on awaiting_human.
            _resume_finalize(
                status="completed" if final_status == "done" else "failed",
                result_summary=str(result) if result is not None else "",
                error_summary=final_error,
                trace_id=getattr(agent, "_active_trace_id", "") or "",
            )
            if _update_workstream_item_sync(
                resolved,
                approval_id,
                status=final_status,
                decision=decision,
                decided_by=decided_by,
                decision_note=decision_note,
                result=result,
                error=final_error,
                resume_started_at=_resume_exec_started,
                resume_trace_id=getattr(agent, "_active_trace_id", "") or "",
                resume_execution_id=_resume_exec_id,
            ) and ws_name and item_id:
                _publish_workstream_event_sync(
                    ws_name,
                    event_type="item_resolved",
                    item_id=item_id,
                    status=final_status,
                    decision=decision,
                    decided_by=decided_by,
                    decision_note=decision_note,
                )
                _trigger_workstream_synthesis_sync(ws_name, tenant_id)
            _record_hitl_reward_best_effort(
                tenant_id=tenant_id,
                agent_id=agent_id,
                approval_id=approval_id,
                decision=f"resume_{final_status}",
                decided_by=decided_by,
                reason=getattr(resolved, "reason", ""),
                context=resume_ctx,
                status=final_status,
                source="hitl_resume",
            )
        except Exception as run_err:
            _annotate_outcome_sync(approval_id, "failed", error_preview=str(run_err))
            if hook_runner:
                try:
                    hook_runner.run_after_approval_resume(
                        approval_id=approval_id,
                        decision=decision,
                        decided_by=decided_by,
                        decision_note=decision_note,
                        reason=getattr(resolved, "reason", ""),
                        resume_status="error",
                        session_ctx=session_ctx,
                        error_msg=str(run_err)[:500],
                    )
                except Exception as hook_err:
                    logger.warning("HITL after-resume error hook failed (non-fatal): %s", hook_err)
            ws_name, item_id = _workstream_ref(resolved)
            try:
                _resume_finalize(
                    status="failed",
                    error_summary=str(run_err),
                    trace_id=getattr(agent, "_active_trace_id", "") or "",
                )
            except Exception:
                pass
            if _update_workstream_item_sync(
                resolved,
                approval_id,
                status="failed",
                decision=decision,
                decided_by=decided_by,
                decision_note=decision_note,
                error=str(run_err),
                resume_started_at=_resume_exec_started,
                resume_trace_id=getattr(agent, "_active_trace_id", "") or "",
                resume_execution_id=_resume_exec_id,
            ) and ws_name and item_id:
                _publish_workstream_event_sync(
                    ws_name,
                    event_type="item_resolved",
                    item_id=item_id,
                    status="failed",
                    decision=decision,
                    decided_by=decided_by,
                    decision_note=decision_note,
                )
                _trigger_workstream_synthesis_sync(ws_name, tenant_id)
            _record_hitl_reward_best_effort(
                tenant_id=tenant_id,
                agent_id=agent_id,
                approval_id=approval_id,
                decision="resume_error",
                decided_by=decided_by,
                reason=str(run_err),
                context=resume_ctx,
                status="failed",
                source="hitl_resume",
            )
            raise
        finally:
            agent._hitl_decision_injected = False

        try:
            import asyncio as _aio
            _loop = _aio.new_event_loop()
            delivered = _loop.run_until_complete(
                chat_registry.send_to_user(tenant_id, user_id, {
                    "type": "response",
                    "content": str(result) if result else "Approval processed.",
                    "skill": resolved.skill,
                    "hitl_resumed": True,
                    "approval_id": approval_id,
                    "decision": decision,
                    "decided_by": decided_by,
                    "timestamp": datetime.now().isoformat(),
                })
            )
            _loop.close()
            if delivered:
                logger.info("Resume result pushed to chat WS: %s", user_id)
            else:
                logger.info("Chat WS not connected for %s - result saved but not pushed", user_id)
        except Exception as push_err:
            logger.warning("Could not push to chat WS: %s", push_err)

        # Save updated state & cleanup via main event loop
        # (async Redis client is bound to the main loop, not a new one)
        try:
            _loop = get_main_loop()  # live ref — the imported _main_loop copy is None
            if _loop:
                save_future = asyncio.run_coroutine_threadsafe(
                    state.save_agent_state(agent, tenant_id, agent_id, user_id),
                    _loop,
                )
                save_future.result(timeout=15)

                delete_future = asyncio.run_coroutine_threadsafe(
                    approval_store.delete_agent_state(approval_id),
                    _loop,
                )
                delete_future.result(timeout=15)
            else:
                logger.warning("HITL cleanup skipped: main event loop unavailable")
        except Exception as cleanup_err:
            logger.warning("HITL cleanup warning: %s", cleanup_err)

        logger.info("HITL resume complete (bg): %s -> %s", approval_id, resolved.status)

    except Exception as e:
        traceback.print_exc()
        logger.error("HITL resume failed (bg): %s", e)


class HitlResolveBody(BaseModel):
    """Request body for resolving a HITL approval.

    All fields optional via query-string fallback for backward compat.
    UI clients should prefer the JSON body so free-text feedback can
    include newlines, quotes, and unicode without URL-encoding pain.
    """
    decision: str = "Approve"
    decided_by: str = "ops_user"
    decision_note: str = ""  # free-text feedback from the approver


def _execute_recon_clear(ctx: dict, resolved, decided_by) -> str:
    """Deterministically apply an approved bank-reconciliation decision (propose-then-apply).

    Treasury sibling of ``_execute_rlm_hold``: the RLM analyst can only PROPOSE what to do with a
    reconciliation break; this is the only thing that writes, and it runs from the stored context
    args alone — no LLM re-plan on approval.

    The bank line id is parsed out of the proposal args (``BK-0000123``) rather than being scraped
    upstream, so nothing in the skills engine needs to know about treasury.
    """
    import re
    import sqlite3
    from pathlib import Path
    from datetime import datetime, timezone

    args = str(ctx.get("args") or "")
    m = re.search(r"BK-\d+(?:-\d+)?", args)
    if not m:
        return f"skipped: no bank line id in args ({args[:80]!r})"
    line_id = m.group(0)
    outcome = "escalated" if "escalat" in args.lower() else "written_off"

    tenant = getattr(resolved, "tenant_id", None) or "company"
    db_path = Path(str(DATA_ROOT_PATH)) / "tenants" / tenant / "shared" / "databases" / "treasury_demo.db"
    if not db_path.exists():
        return f"skipped: ledger not found at {db_path}"

    ts = datetime.now(timezone.utc).isoformat()
    con = sqlite3.connect(str(db_path))
    try:
        con.execute(
            "CREATE TABLE IF NOT EXISTS recon_decisions ("
            "approval_id TEXT, line_id TEXT, outcome TEXT, amount REAL, "
            "rationale TEXT, approved_by TEXT, approved_at TEXT)"
        )
        # Idempotency guard: one decision per bank line, so a double-approve cannot
        # double-write the audit trail or re-clear a line.
        already = con.execute(
            "SELECT COUNT(*) FROM recon_decisions WHERE line_id=?", (line_id,)
        ).fetchone()[0]
        if already:
            return f"idempotent: {line_id} already decided — no duplicate recorded"
        con.execute(
            "INSERT INTO recon_decisions VALUES (?,?,?,?,?,?,?)",
            (getattr(resolved, "id", ""), line_id, outcome, float(ctx.get("amount") or 0),
             getattr(resolved, "reason", "") or "", str(decided_by or ""), ts),
        )
        con.execute("UPDATE recon_bank_lines SET status=? WHERE line_id=?", (outcome, line_id))
        con.commit()
        return f"{line_id} -> {outcome}"
    finally:
        con.close()


def _execute_rlm_hold(ctx: dict, resolved, decided_by) -> str:
    """Deterministically apply an approved RLM payment hold (propose-then-apply).

    Self-contained: audit-logs the hold and flips the invoice status in the demo AP ledger.
    No agent_state / LLM re-plan — executes from the stored context args only. Raises on hard
    failure (caught by the caller so a resolve never 500s).
    """
    import sqlite3
    from pathlib import Path
    from datetime import datetime, timezone

    inv = str(ctx.get("invoice_id") or "").strip()
    tenant = getattr(resolved, "tenant_id", None) or "company"
    db_path = Path(str(DATA_ROOT_PATH)) / "tenants" / tenant / "shared" / "databases" / "rlm_demo.db"
    if not db_path.exists():
        return f"skipped: ledger not found at {db_path}"
    ts = datetime.now(timezone.utc).isoformat()
    con = sqlite3.connect(str(db_path))
    try:
        con.execute(
            "CREATE TABLE IF NOT EXISTS payment_holds ("
            "approval_id TEXT, invoice_id TEXT, vendor TEXT, amount REAL, "
            "rationale TEXT, approved_by TEXT, approved_at TEXT)"
        )
        # Idempotency guard: one active hold per invoice; re-approval must not duplicate audit rows.
        if inv:
            already = con.execute(
                "SELECT COUNT(*) FROM payment_holds WHERE invoice_id=?", (inv,)
            ).fetchone()[0]
            if already:
                return f"idempotent: {inv} already on hold — no duplicate recorded"
        con.execute(
            "INSERT INTO payment_holds VALUES (?,?,?,?,?,?,?)",
            (getattr(resolved, "id", ""), inv, str(ctx.get("vendor") or ""),
             float(ctx.get("amount") or 0), getattr(resolved, "reason", "") or "",
             str(decided_by or ""), ts),
        )
        if inv:
            con.execute("UPDATE invoices SET status='ON_HOLD' WHERE id=?", (inv,))
        con.commit()
        return f"hold recorded; {inv or '(no id)'} set ON_HOLD"
    finally:
        con.close()


@router.post("/api/hitl/{approval_id}/resolve")
async def resolve_hitl_approval(
    approval_id: str,
    request: Request,
    body: HitlResolveBody | None = None,
    # Query-string fallback (back-compat with older callers that pass via URL params)
    decision: str | None = None,
    decided_by: str | None = None,
    decision_note: str | None = None,
    background_tasks: BackgroundTasks = None,
):
    """Resolve a HITL approval as the authenticated, entitled caller."""
    # Body wins over query string. Both empty → use defaults.
    body = body or HitlResolveBody()
    decision = decision or body.decision
    decision_note = decision_note if decision_note is not None else body.decision_note

    # Authorize first: bind identity and tenant scope (foreign ids return 404), then the approver entitlement check.
    principal, resolved_tenant, _agent_id, _caller = require_scoped_identity(request)
    approval = await approval_store.get_approval(approval_id)
    if not approval or not scope_approval_records(
        [approval.to_dict()], principal=principal, tenant_id=resolved_tenant
    ):
        raise HTTPException(404, f"Approval {approval_id} not found")

    # Already resolved: return the prior decision to an in-scope caller (reading needs scope, not approve rights).
    if approval.status in ("approved", "rejected"):
        return {
            "approval_id": approval_id,
            "status": approval.status,
            "decision": approval.decision or decision,
            "decided_by": approval.decided_by or decided_by or body.decided_by,
            "resuming": False,
            "already_resolved": True,
            "message": f"Already {approval.status}.",
        }

    approver = authorise_approver(request, approval)
    if not AUTH_ENABLED:
        # Dev mode has no real identity; keep the client's label so local demos read sensibly.
        approver = decided_by or body.decided_by or approver
    return await resolve_hitl_decision(
        approval_id,
        decision=decision,
        decided_by=approver,
        decision_note=decision_note,
        background_tasks=background_tasks,
    )


async def resolve_hitl_decision(
    approval_id: str,
    *,
    decision: str,
    decided_by: str,
    decision_note: str = "",
    background_tasks: BackgroundTasks | None = None,
):
    """
    Apply an already-authorised HITL decision (returns immediately, resumes agent in background).

    1. Updates approval status in Redis — exactly once (a repeat gets 409, no side effects)
    2. Loads checkpointed agent state
    3. Broadcasts resolution to dashboard
    4. Schedules agent resume as a background task
    """
    logger.info("HITL resolve received: %s, decision=%s, by=%s", approval_id, decision, decided_by)

    # 1. Resolve in Redis (fast). Only the call that actually decided runs the side effects
    # below (apply-phase writes, workstream transitions, agent resume).
    resolved, decided_now = await approval_store.claim_resolution(
        approval_id=approval_id,
        decision=decision,
        decided_by=decided_by,
        decision_note=decision_note,
    )

    if not resolved:
        raise HTTPException(404, f"Approval {approval_id} not found")

    if not decided_now:
        raise HTTPException(
            409,
            f"Approval {approval_id} was already decided: {resolved.status}"
            + (f" by {resolved.decided_by}" if getattr(resolved, "decided_by", None) else ""),
        )

    if resolved.status not in ("approved", "rejected"):
        raise HTTPException(400, f"Could not resolve: already {resolved.status}")

    _record_hitl_reward_best_effort(
        tenant_id=getattr(resolved, "tenant_id", "company"),
        approval_id=approval_id,
        decision=str(decision or resolved.status or "").strip().lower(),
        decided_by=decided_by or "",
        reason=getattr(resolved, "reason", ""),
        context=getattr(resolved, "context", None) or {},
        status=getattr(resolved, "status", ""),
        source="hitl_resolve",
    )

    # Builds an agent and writes a knowledge record (embedding call) — keep it off the loop.
    await asyncio.to_thread(
        _write_hitl_feedback_knowledge,
        resolved,
        approval_id=approval_id,
        decision=decision,
        decided_by=decided_by,
        decision_note=decision_note or "",
    )

    agent_state = await approval_store.get_agent_state(approval_id)

    await dashboard.broadcast({
        "type": "hitl_approval_resolved",
        "approval_id": approval_id,
        "status": resolved.status,
        "decided_by": decided_by,
        "user_id": resolved.user_id,
        "reason": resolved.reason,
    })

    # 3a-rlm. RLM apply-phase: deterministic execution on Approve, dispatched on the proposal's
    # own kind. Self-contained (no workstream, no agent_state); Reject → nothing side-effecting runs.
    try:
        _rlm_ctx = getattr(resolved, "context", None) or {}
        _rlm_action = str(_rlm_ctx.get("action") or "")
        if resolved.status == "approved":
            if _rlm_action == "hold_payment":
                _hold_result = _execute_rlm_hold(_rlm_ctx, resolved, decided_by)
                logger.info("RLM apply-phase: hold_payment %s → %s",
                            _rlm_ctx.get("invoice_id"), _hold_result)
            elif _rlm_action == "clear_recon_break":
                _clr_result = _execute_recon_clear(_rlm_ctx, resolved, decided_by)
                logger.info("RLM apply-phase: clear_recon_break → %s", _clr_result)
    except Exception as _rlm_hold_err:
        logger.warning("RLM apply-phase execution failed: %s", _rlm_hold_err)

    # Notify the originating chat session now, including reject/skip-resume paths.
    await _notify_chat_of_resolution(
        tenant_id=getattr(resolved, "tenant_id", "") or "",
        user_id=getattr(resolved, "user_id", "") or "",
        approval_id=approval_id,
        status=resolved.status,
        decision=decision or resolved.status,
        decided_by=decided_by or "",
        reason=getattr(resolved, "reason", "") or "",
        skill=getattr(resolved, "skill", "") or "",
    )

    # Mission Mode: approval only releases the gate; the resume helper owns the final transition.
    skip_background_resume = False
    try:
        ws_name, item_id = _workstream_ref(resolved)
        if ws_name and item_id:
            from iaf_agent_skills.workstream_store import now_iso

            store = _workstream_store_for(resolved.tenant_id)
            decision_summary = (
                f"{decision.upper()} by {decided_by or 'unknown'} at {now_iso()}"
                + (f"; note: {_bounded_text(decision_note, 300)}" if decision_note else "")
            )
            try:
                ctx = getattr(resolved, "context", None) or {}
                if (
                    resolved.status == "approved"
                    and ctx.get("resume_kind") == "connector_action"
                    and ctx.get("action") == "post_to_sap"
                ):
                    skip_background_resume = True
                    document_id = f"BP-SAP-MOCK-{uuid.uuid4().hex[:10].upper()}"
                    store.update_item(
                        ws_name,
                        item_id,
                        status="done",
                        resolution=f"{decision_summary}; mock SAP post approved and accepted as {document_id}",
                        last_result_summary=f"Mock SAP post accepted as {document_id}",
                        last_result_at=now_iso(),
                        escalated_approval_id=None,
                        completed_at=now_iso(),
                        suggested_actions=_workstream_suggested_actions("done"),
                    )
                    logger.info(
                        "Connector approval completed mock SAP post: %s/%s -> done (%s)",
                        ws_name, item_id, document_id,
                    )
                    await _publish_workstream_event(
                        ws_name,
                        event_type="item_resolved",
                        item_id=item_id,
                        status="done",
                        decision=decision,
                        decided_by=decided_by,
                        decision_note=decision_note,
                    )
                    _trigger_workstream_synthesis_sync(ws_name, resolved.tenant_id)
                elif resolved.status == "approved" and agent_state:
                    store.update_item(
                        ws_name, item_id,
                        status="in_progress",
                        resolution=f"{decision_summary}; resume in progress",
                        completed_at=None,
                    )
                    try:
                        ws_after = store.load(ws_name)
                        if ws_after.get("status") == "completed":
                            store.update_workstream(ws_name, status="active", completed_at=None)
                    except Exception as revive_err:
                        logger.debug("workstream active-state revive skipped: %s", revive_err)
                    logger.info(
                        "Workstream item approved and resuming: %s/%s -> in_progress",
                        ws_name, item_id,
                    )
                    await _publish_workstream_event(
                        ws_name,
                        event_type="item_resuming",
                        item_id=item_id,
                        status="in_progress",
                        decision=decision,
                        decided_by=decided_by,
                        decision_note=decision_note,
                    )
                elif resolved.status == "approved" and not agent_state:
                    skip_background_resume = True
                    store.update_item(
                        ws_name, item_id,
                        status="failed",
                        resolution=(
                            f"{decision_summary}; resume failed: missing checkpointed "
                            "agent state for post-approval work"
                        ),
                        completed_at=now_iso(),
                    )
                    logger.warning(
                        "Workstream approval missing checkpoint; item failed: %s/%s",
                        ws_name, item_id,
                    )
                    await _publish_workstream_event(
                        ws_name,
                        event_type="item_resolved",
                        item_id=item_id,
                        status="failed",
                        decision=decision,
                        decided_by=decided_by,
                        decision_note=decision_note,
                    )
                    _trigger_workstream_synthesis_sync(ws_name, resolved.tenant_id)
                else:
                    skip_background_resume = True
                    store.update_item(
                        ws_name, item_id,
                        status="failed",
                        resolution=f"{decision_summary}; approval rejected; post-approval work not run",
                        completed_at=now_iso(),
                    )
                    logger.info(
                        "Workstream item rejected after HITL approval: %s/%s -> failed",
                        ws_name, item_id,
                    )
                    await _publish_workstream_event(
                        ws_name,
                        event_type="item_resolved",
                        item_id=item_id,
                        status="failed",
                        decision=decision,
                        decided_by=decided_by,
                        decision_note=decision_note,
                    )
                    _trigger_workstream_synthesis_sync(ws_name, resolved.tenant_id)
            except Exception as upd_err:
                logger.warning(
                    "Failed to update workstream item during approval resolve (%s/%s): %s",
                    ws_name, item_id, upd_err,
                )
    except Exception as ws_err:
        logger.warning("Workstream approval gate update skipped: %s", ws_err)

    has_resume = False
    if agent_state and background_tasks and not skip_background_resume:
        background_tasks.add_task(
            _resume_agent_from_hitl_sync,
            resolved, agent_state, decision, decided_by, decision_note, approval_id,
        )
        has_resume = True
        logger.info("HITL agent resume scheduled in background: %s", approval_id)
    elif not agent_state:
        logger.info("HITL resolved (no agent state to resume): %s", approval_id)

    return {
        "approval_id": approval_id,
        "status": resolved.status,
        "decision": decision,
        "decided_by": decided_by,
        "resuming": has_resume,
        "message": "Resolved. Agent resuming in background." if has_resume else "Resolved (no checkpoint to resume).",
    }
