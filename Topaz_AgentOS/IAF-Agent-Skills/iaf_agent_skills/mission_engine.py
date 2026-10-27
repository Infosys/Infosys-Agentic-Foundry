"""
Mission Mode engine.

A workstream is a multi-item backlog. Mission Mode is the outer loop that
picks one item per cron iteration, hands it to the existing
``SkillAgent.run()`` (for reasoning, tool calls, security gates, HITL,
evidence — all unchanged), and persists the per-item outcome back to the
workstream YAML.

This module owns ONE public function:

    run_iteration(agent, workstream_name, tenant_id, store=None) -> IterationResult

Everything else is private. Nothing in here calls the LLM directly; all
reasoning is delegated to ``agent.run()``.
"""

from __future__ import annotations

import json
import logging
import os
import re
import time
import uuid
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Callable, Optional

from .workstream_store import WorkstreamStore, now_iso
from . import items_source as _items_source
from .runtime_bridge import default_tenant_id, get_mission_bridge

logger = logging.getLogger(__name__)



@dataclass
class IterationResult:
    """What happened in this single iteration."""
    action: str                          # one of: blocked_by_hook | nothing_pending | item_processed
                                         #         | item_escalated | item_failed | workstream_completed
    workstream_name: str
    item_id: Optional[str] = None
    item_status_before: Optional[str] = None
    item_status_after: Optional[str] = None
    attempts: int = 0
    approval_id: Optional[str] = None
    trace_id: Optional[str] = None       # the agent trace for this item attempt
    duration_ms: int = 0
    reason: str = ""                     # human-readable summary
    workstream_status: str = ""          # status after this iteration

    def as_dict(self) -> dict:
        return asdict(self)



def _pick_next_item(ws: dict) -> Optional[dict]:
    """
    Pick the next item to process. Eligible items: status in {pending}.
    Items in {in_progress, done, failed, awaiting_human} are excluded.
    """
    eligible = [it for it in ws.get("items", []) if it.get("status") == "pending"]
    if not eligible:
        return None

    strategy = ws.get("priority_strategy", "sequential")

    if strategy == "highest_amount":
        # parse 'amount_eur' from description as a best-effort numeric extraction.
        # Real users should put `priority_metric: amount` directly on the item.
        def _amount(it):
            return float(it.get("priority_metric", 0) or 0)
        return max(eligible, key=_amount)

    if strategy == "highest_aged_first":
        # oldest creation-side first; falls back to ordering in the list
        def _age(it):
            return it.get("created_at", "0000") or "0000"
        return min(eligible, key=_age)

    if strategy == "round_robin":
        # cycle through items; pick the one with fewest attempts then earliest list pos
        return min(eligible, key=lambda it: it.get("attempts", 0))

    # "sequential" (default): first eligible in list order
    return eligible[0]



# A negator immediately before a signal phrase (up to 3 words of slack), e.g.
#   "No release approval required"  /  "without approval required"
_NEGATOR_BEFORE = re.compile(
    r"(?:\b(?:no|not|non|none|never|without|nil|zero)\b|n't)[\s\W]+(?:\w+[\s\W]+){0,3}$"
)


def _unnegated_signal(low: str, signals: tuple[str, ...]) -> str:
    """Return the first signal phrase present in `low` that is NOT negated.

    A plain substring test is negation-blind: `post_and_close` legitimately reports
    "- No release approval required" for an invoice under the release threshold, which
    contains "approval required" and used to reclassify a fully successful run as
    incomplete (-> pending -> retry -> eventually failed). Every occurrence is checked
    here, and one preceded by a negator is skipped; a genuine gate message
    ("Payment-release approval required for INV-...") still matches.
    """
    for sig in signals:
        for match in re.finditer(re.escape(sig), low):
            preceding = low[max(0, match.start() - 48):match.start()]
            if _NEGATOR_BEFORE.search(preceding):
                continue  # negated mention — the agent is reporting the opposite
            return sig
    return ""


_GRADER_MIN_CONFIDENCE = 0.6

_GRADER_PROMPT = """You are a strict outcome grader for one autonomous enterprise workstream item.
Decide whether the item's work is COMPLETE or INCOMPLETE, judged ONLY against its acceptance
criteria and what the run actually did. Judge OUTCOMES, not wording.

TASK:
{task}

ACCEPTANCE CRITERIA (all must hold for COMPLETE):
{criteria}

FINAL RESULT (the agent's own summary):
{response}

KEY ACTIONS TAKEN:
{actions}

Rules:
- COMPLETE = every criterion is satisfied. A criterion like "posted OR held for approval" is met
  if the item was correctly posted OR correctly held.
- INCOMPLETE = any criterion unmet, the agent stopped early, hit an unresolved error, or is still
  waiting on something it needed.
- "No approval required" / "no gate applied" means the gate did NOT apply — that is NOT a blocker.
- Do not invent facts beyond the result and actions above.

Respond with ONLY this JSON object and nothing else:
{{"status": "complete" | "incomplete", "confidence": 0.0-1.0, "reason": "<=200 chars"}}"""


def _grader_enabled() -> bool:
    return os.getenv("MISSION_OUTCOME_GRADER", "true").strip().lower() not in ("0", "false", "no", "off")


def _extract_json_object(text: str) -> Optional[dict]:
    """Best-effort: pull the first balanced {...} JSON object out of a model reply."""
    if not text:
        return None
    start = text.find("{")
    if start < 0:
        return None
    depth = 0
    for i in range(start, len(text)):
        c = text[i]
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                try:
                    return json.loads(text[start:i + 1])
                except Exception:
                    return None
    return None


def _run_outcome_grader(model_call: Callable[[str], str], task: str,
                        acceptance_criteria: list, response: str, tool_calls: list) -> Optional[dict]:
    """Call the light model once and return a normalised verdict dict, or None on any problem."""
    crit = "\n".join(f"- {c}" for c in (acceptance_criteria or [])) or "- (none declared)"
    actions = "\n".join(
        f"- {(c.get('tool') or c.get('tool_name') or c.get('name') or 'step') if isinstance(c, dict) else str(c)}"
        for c in (tool_calls or [])[:20]
    ) or "- (none recorded)"
    prompt = _GRADER_PROMPT.format(
        task=(task or "(no task text)")[:800],
        criteria=crit[:1200],
        response=(response or "")[:2500],
        actions=actions[:1200],
    )
    raw = model_call(prompt)
    data = _extract_json_object(str(raw or ""))
    if not isinstance(data, dict):
        return None
    status = str(data.get("status", "")).strip().lower()
    if status not in ("complete", "incomplete"):
        return None
    try:
        conf = float(data.get("confidence", 0.0))
    except (TypeError, ValueError):
        conf = 0.0
    return {"status": status, "confidence": max(0.0, min(1.0, conf)),
            "reason": str(data.get("reason", "")).strip()[:200]}


def _make_outcome_grader(agent) -> Optional[Callable[..., Optional[dict]]]:
    """Build a grader bound to the agent's governed light-model call, or None when disabled /
    no model is reachable. The returned callable never raises (returns None on any failure)."""
    if not _grader_enabled():
        return None
    model_call = None
    if hasattr(agent, "_rlm_leaf_call"):          # governed light call (audit/RL/policy)
        model_call = agent._rlm_leaf_call
    elif getattr(agent, "light_llm", None) is not None:
        def model_call(prompt: str) -> str:       # noqa: E731 — simple adapter
            from langchain_core.messages import HumanMessage
            r = agent.light_llm.invoke([HumanMessage(content=prompt)])
            return getattr(r, "content", "") or str(r)
    if model_call is None:
        return None

    def _grade(task, acceptance_criteria, response, tool_calls) -> Optional[dict]:
        try:
            return _run_outcome_grader(model_call, task, acceptance_criteria, response, tool_calls)
        except Exception as exc:  # unreachable model, 403, parse error — fall back to deterministic
            logger.debug("outcome grader unavailable (non-fatal, using deterministic chain): %s", exc)
            return None
    return _grade


def _classify_outcome(
    response: str,
    tool_calls: list,
    agent_approval_pending: Optional[dict],
    item: dict,
    max_attempts: int,
    *,
    grader: Optional[Callable[..., Optional[dict]]] = None,
    task: str = "",
    grader_min_confidence: float = _GRADER_MIN_CONFIDENCE,
) -> tuple[str, str]:
    """
    Return (new_item_status, reason).

    Decision order:
      1. approval_pending set on agent  → awaiting_human   (structured — always wins)
      2. empty response                 → retry/failed
      3. governed LLM grader (if confident) → done or retry/failed   (authoritative)
      4. deterministic keyword chain    → fallback when the grader is absent/unsure
    """
    if agent_approval_pending:
        return "awaiting_human", "agent requested human approval"

    response_norm = (response or "").strip()
    if not response_norm:
        if item.get("attempts", 0) + 1 >= max_attempts:
            return "failed", "agent returned empty response (max attempts reached)"
        return "pending", "agent returned empty response — will retry"

    # 3. LLM grader — authoritative only when it returns a confident verdict.
    if grader is not None:
        verdict = grader(task, item.get("acceptance_criteria") or [], response_norm, tool_calls)
        if verdict:
            conf = verdict.get("confidence") or 0.0
            why = (verdict.get("reason") or "").strip()
            if isinstance(conf, (int, float)) and conf >= grader_min_confidence:
                if verdict.get("status") == "complete":
                    return "done", (why or response_norm[:500])[:500]
                if verdict.get("status") == "incomplete":
                    tag = f"grader: incomplete — {why}" if why else "grader: incomplete"
                    if item.get("attempts", 0) + 1 >= max_attempts:
                        return "failed", f"{tag} (max attempts reached)"[:200]
                    return "pending", f"{tag} — will retry"[:200]
        # else: no verdict / low confidence → deterministic chain below

    low = response_norm.lower()
    error_signals = ("error:", "failed:", "exception:", "traceback")
    if any(sig in low[:200] for sig in error_signals):
        if item.get("attempts", 0) + 1 >= max_attempts:
            return "failed", f"agent returned error envelope (max attempts reached): {response_norm[:160]}"
        return "pending", f"agent returned error envelope — will retry: {response_norm[:160]}"

    incomplete_signals = (
        "cannot proceed",
        "can't proceed",
        "can not proceed",
        "could not proceed",
        "unable to proceed",
        "mandatory evidence fetch failed",
        "evidence fetch failed",
        "live evidence fetch failed",
        "approval required",
        "requires human approval",
        "requires approval",
    )
    if _unnegated_signal(low, incomplete_signals):
        if item.get("attempts", 0) + 1 >= max_attempts:
            return "failed", f"agent returned incomplete outcome (max attempts reached): {response_norm[:160]}"
        return "pending", f"agent returned incomplete outcome — will retry: {response_norm[:160]}"

    return "done", response_norm[:500]


def _approval_matches_item(approval: dict | None, workstream_name: str, item_id: str) -> bool:
    if not isinstance(approval, dict):
        return False
    ctx = approval.get("context") or {}
    ctx_workstream = ctx.get("workstream_name") or ctx.get("workstream")
    ctx_item = ctx.get("mission_item_id") or ctx.get("item_id") or ctx.get("workstream_item")
    if ctx_workstream or ctx_item:
        return ctx_workstream == workstream_name and ctx_item == item_id

    preview = "\n".join(
        str(ctx.get(key) or "")
        for key in ("query_preview", "input_preview", "response_preview")
    )
    return bool(item_id and item_id in preview and "Workstream:" in preview)


def _as_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "y", "required"}
    return False


def _item_requires_human_approval(item: dict) -> bool:
    case_summary = item.get("case_summary") or {}
    case_insights = item.get("case_insights") or {}
    return (
        _as_bool(item.get("approval_required"))
        or str(item.get("bucket") or "").strip().lower() == "judgement_required"
        or str(case_summary.get("resolution_mode") or "").strip().lower() == "human_required"
        or str(case_summary.get("auto_resolution_status") or "").strip().lower() == "human_required"
        or str(case_insights.get("resolution_mode") or "").strip().lower() == "human_required"
        or str(case_insights.get("auto_resolution_status") or "").strip().lower() == "human_required"
    )


def _approval_urgency(item: dict) -> str:
    case_summary = item.get("case_summary") or {}
    risk = str(case_summary.get("risk_level") or item.get("risk_level") or "").strip().lower()
    if risk in {"critical", "high", "medium", "low"}:
        return risk
    return "high"


def _synthesize_workstream_approval(agent, ws: dict, item: dict, workstream_name: str, response: str) -> None:
    if getattr(agent, "approval_pending", None) or not _item_requires_human_approval(item):
        return

    item_id = str(item.get("id") or "")
    skill = ws.get("skill") or getattr(agent, "current_skill", None) or "unknown"
    case_summary = item.get("case_summary") or {}
    case_insights = item.get("case_insights") or {}
    reason_source = (
        case_summary.get("policy_trigger")
        or case_summary.get("priority_reason")
        or case_insights.get("auto_resolution_reason")
        or item.get("description")
        or "Workstream policy marks this item as approval-required."
    )
    reason = (
        f"Workstream policy requires human approval before completing item {item_id}: "
        f"{str(reason_source)[:500]}"
    )
    context = {
        "workstream_name": workstream_name,
        "workstream": workstream_name,
        "mission_item_id": item_id,
        "item_id": item_id,
        "skill": skill,
        "approval_trigger": "workstream_policy",
        "approval_required": True,
        "bucket": item.get("bucket"),
        "case_id": case_summary.get("case_id") or item_id,
        "invoice_id": item.get("invoice_id") or case_summary.get("secondary_entity"),
        "supplier_name": item.get("supplier_name") or case_summary.get("primary_entity"),
        "agent_response_preview": (response or "")[:500],
    }
    agent.approval_pending = {
        "approval_id": str(uuid.uuid4()),
        "reason": reason,
        "context": context,
        "options": ["Approve", "Reject", "Escalate"],
        "urgency": _approval_urgency(item),
        "sla_minutes": 60,
        "skill": skill,
        "rule_matched": "workstream approval_required",
        "rule_type": "workstream_policy",
        "timestamp": now_iso(),
    }
    logger.info(
        "mission_engine: synthesized HITL approval for approval-gated item %s/%s",
        workstream_name,
        item_id,
    )


def _clear_stale_item_approval(agent, workstream_name: str, item_id: str, *, phase: str) -> None:
    pending = getattr(agent, "approval_pending", None)
    if not pending or _approval_matches_item(pending, workstream_name, item_id):
        return
    logger.warning(
        "mission_engine: clearing stale in-memory HITL approval (%s): "
        "current=%s/%s pending_context=%s approval=%s",
        phase,
        workstream_name,
        item_id,
        (pending.get("context") or {}) if isinstance(pending, dict) else pending,
        pending.get("approval_id") if isinstance(pending, dict) else "",
    )
    agent.approval_pending = None


# ── WebSocket push (best-effort live updates to workstream detail page) ──

# Maps engine IterationResult.action → browser-side event name
# (workstream_detail.html's handleEvent() listens for these exact types)
_ACTION_TO_WS_EVENT = {
    "item_processed":      "mission_item_processed",
    "item_escalated":      "mission_item_escalated",
    "item_failed":         "mission_item_failed",
    "workstream_completed":"mission_complete",
}


def _publish_workstream_event(workstream_name: str, payload: dict[str, Any]) -> None:
    """
    Best-effort push to /ws/workstreams/<name> subscribers.

    Mission Mode can run from Studio, tests, or CLI scripts. Only a host that
    registered a Mission runtime bridge (Studio) can deliver live events; when
    no bridge is registered this is a no-op (the UI poll still catches changes).
    """
    bridge = get_mission_bridge()
    if bridge is None:
        return
    try:
        bridge.publish_workstream_event(workstream_name, payload)
    except Exception as exc:  # observe-only — never block the engine
        logger.debug("ws publish failed (non-fatal): %s", exc)


def _publish_ws_event(result: "IterationResult") -> None:
    """
    Best-effort push to /ws/workstreams/<name> subscribers when an item
    flipped state. Cron runs in a thread separate from the FastAPI event
    loop, so we use run_coroutine_threadsafe against the studio's main loop.

    Safe to call from anywhere — if the studio isn't the parent process
    (e.g. running mission_engine from a CLI script), the imports fail and
    we no-op. The 15s UI poll still catches the change.
    """
    event_type = _ACTION_TO_WS_EVENT.get(result.action)
    if not event_type:
        return  # nothing_pending / blocked_by_hook — no visible state change

    payload = {
        "type": event_type,
        "workstream_name": result.workstream_name,
        "item_id": result.item_id,
        "item_status_before": result.item_status_before,
        "item_status_after": result.item_status_after,
        "attempts": result.attempts,
        "approval_id": result.approval_id,
        "trace_id": result.trace_id,
        "reason": result.reason,
        "duration_ms": result.duration_ms,
        "workstream_status": result.workstream_status,
        # `summary` is shown in the activity feed; build a one-liner
        "summary": _build_summary(result),
        "ts": now_iso(),
    }
    _publish_workstream_event(result.workstream_name, payload)


def _publish_item_started(
    workstream_name: str,
    item_id: str,
    *,
    execution_id: str,
    attempts: int,
) -> None:
    """Tell open workstream detail pages that an item attempt has started."""
    _publish_workstream_event(workstream_name, {
        "type": "mission_item_started",
        "workstream_name": workstream_name,
        "item_id": item_id,
        "execution_id": execution_id,
        "attempts": attempts,
        "summary": f"item {item_id} -> running",
        "ts": now_iso(),
    })


def _publish_step_event(
    workstream_name: str,
    item_id: str,
    *,
    execution_id: str,
    step: dict[str, Any],
) -> None:
    """Stream one live execution step to open workstream detail pages."""
    _publish_workstream_event(workstream_name, {
        "type": "mission_item_step",
        "workstream_name": workstream_name,
        "item_id": item_id,
        "execution_id": execution_id,
        "step": step,
        "summary": step.get("output_preview") or step.get("tool_name") or "execution step",
        "ts": now_iso(),
    })


def _build_summary(result: "IterationResult") -> str:
    """Compose a short human-readable line for the activity feed."""
    if result.action == "workstream_completed":
        return f"workstream complete — {result.reason}"
    item = result.item_id or "?"
    after = result.item_status_after or "?"
    if result.action == "item_processed":
        return f"item {item} → done ({result.duration_ms} ms)"
    if result.action == "item_escalated":
        return f"item {item} → awaiting human (approval {result.approval_id})"
    if result.action == "item_failed":
        return f"item {item} → failed after {result.attempts} attempts"
    return f"item {item} → {after}"


def _tool_call_steps(tool_calls: list) -> list[dict[str, Any]]:
    steps: list[dict[str, Any]] = []
    for idx, call in enumerate(tool_calls or [], start=1):
        if isinstance(call, dict):
            getter = call.get
        else:
            getter = lambda key, default=None, _call=call: getattr(_call, key, default)
        tool_name = getter("tool") or getter("tool_name") or getter("name") or "tool"
        input_value = getter("input") or getter("args") or getter("command") or getter("query") or ""
        output_value = getter("output") or getter("result") or getter("response") or ""
        error_value = getter("error") or getter("exception") or ""
        status = getter("status") or ("failed" if error_value else "completed")
        duration_ms = getter("duration_ms") or getter("elapsed_ms") or 0
        action = getter("action") or ""
        skill = getter("skill") or ""
        try:
            duration_ms = int(duration_ms or 0)
        except (TypeError, ValueError):
            duration_ms = 0
        steps.append({
            "step_index": idx,
            "tool_name": str(tool_name),
            "status": str(status),
            "duration_ms": duration_ms,
            "input_preview": str(input_value)[:500],
            "output_preview": str(output_value)[:500],
            "error_preview": str(error_value)[:500],
            "action": str(action or "tool"),
            "skill": str(skill or ""),
        })
    return steps


def _status_callback_step(msg: Any, step_index: int) -> dict[str, Any]:
    """Normalize SkillAgent status callbacks into the workstream ledger shape."""
    if isinstance(msg, dict) and msg.get("__progress__"):
        phase = str(msg.get("phase") or "")
        sub_step = str(msg.get("sub_step") or "")
        workflow_step = str(msg.get("workflow_step") or "")
        skill = str(msg.get("skill") or "")
        workflow_action = str(msg.get("workflow_action") or "")
        name_parts = [part for part in (workflow_step, sub_step or skill or phase) if part]
        tool_name = " / ".join(dict.fromkeys(name_parts)) or f"step_{step_index}"
        detail = str(msg.get("detail") or msg.get("status") or "")
        status = str(msg.get("status") or "running")
        duration_ms = msg.get("elapsed_ms") or 0
        try:
            duration_ms = int(duration_ms or 0)
        except (TypeError, ValueError):
            duration_ms = 0
        return {
            "step_index": step_index,
            "tool_name": tool_name,
            "status": status,
            "duration_ms": duration_ms,
            "input_preview": "",
            "output_preview": detail[:500],
            "error_preview": "",
            "action": workflow_action or "progress",
            "phase": phase,
            "skill": skill,
        }

    text = str(msg)
    lower = text.lower()
    status = "awaiting_human" if ("human" in lower and "approval" in lower) else "running"
    return {
        "step_index": step_index,
        "tool_name": text[:80] if len(text) > 80 else text,
        "status": status,
        "duration_ms": 0,
        "input_preview": "",
        "output_preview": text[:500],
        "error_preview": "",
        "action": "agent_step",
        "phase": "",
    }


def _runtime_db():
    """Return the host's durable Workstream runtime DB, or None outside a host."""
    bridge = get_mission_bridge()
    if bridge is None:
        return None
    try:
        return bridge.get_runtime_db()
    except Exception as exc:
        logger.debug("workstream runtime DB unavailable (non-fatal): %s", exc)
        return None


def _runtime_create_execution(
    *,
    execution_id: str,
    workstream_name: str,
    item_id: str,
    tenant_id: str,
    skill_name: str,
    attempt: int,
    started_at: str,
) -> None:
    db = _runtime_db()
    if db is None:
        return
    try:
        db.create_execution(
            execution_id=execution_id,
            workstream_name=workstream_name,
            item_id=item_id,
            tenant_id=tenant_id,
            skill_name=skill_name,
            attempt=attempt,
            status="running",
            started_at=started_at,
        )
    except Exception as exc:
        logger.debug("workstream runtime execution create skipped: %s", exc)


def _runtime_append_step(execution_id: str, step: dict[str, Any]) -> dict[str, Any]:
    db = _runtime_db()
    if db is None:
        return step
    try:
        step_no = int(step.get("step_number") or step.get("step_index") or 0)
        stored = db.append_step(
            execution_id=execution_id,
            step_number=step_no,
            step_name=str(step.get("tool_name") or step.get("step_name") or step.get("name") or f"step_{step_no}"),
            action=str(step.get("action") or step.get("type") or "agent_step"),
            input_value=str(step.get("input_preview") or step.get("input") or ""),
            output=str(step.get("output_preview") or step.get("output") or step.get("detail") or ""),
            status=str(step.get("status") or "completed"),
            duration_ms=int(step.get("duration_ms") or 0),
            phase=str(step.get("phase") or ""),
            skill=str(step.get("skill") or ""),
            timestamp=str(step.get("timestamp") or "") or None,
        )
        merged = dict(step)
        merged.update(stored)
        return merged
    except Exception as exc:
        logger.debug("workstream runtime step append skipped: %s", exc)
        return step


def _runtime_finalize_execution(execution_id: str, **fields: Any) -> None:
    db = _runtime_db()
    if db is None:
        return
    try:
        db.update_execution(execution_id, **fields)
    except Exception as exc:
        logger.debug("workstream runtime execution finalize skipped: %s", exc)


def _suggested_actions_for_status(status: str) -> list[dict[str, Any]]:
    base = [{
        "id": "continue_chat",
        "label": "Continue",
        "kind": "chat",
        "side_effect": False,
    }]
    if status == "awaiting_human":
        return base + [
            {"id": "approve", "label": "Approve", "kind": "approval", "side_effect": True},
            {"id": "reject", "label": "Reject", "kind": "approval", "side_effect": True},
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



def _refresh_items_from_source(
    store: WorkstreamStore,
    ws: dict,
    agent,
    tenant_root: Path,
) -> int:
    """
    Pull items from the workstream's configured items_source and merge them
    into the workstream YAML per its refresh_strategy.

    Returns the number of newly-appended items (0 if nothing changed or on
    error). Observe-only: never raises.
    """
    src = ws.get("items_source")
    if not isinstance(src, dict):
        return 0
    tenant_id = ws.get("tenant_id") or getattr(agent.kernel, "tenant_id", default_tenant_id()) if agent else default_tenant_id()
    strategy = src.get("refresh_strategy", "append_new")

    try:
        fetched = _items_source.resolve(
            src,
            tenant_root=tenant_root,
            tenant_id=tenant_id,
            agent=agent,
        )
    except Exception as exc:
        logger.warning("items_source refresh failed for %s: %s", ws.get("name"), exc)
        return 0

    if not fetched:
        logger.debug("items_source: 0 items fetched for %s", ws.get("name"))
        store.update_workstream(ws["name"], last_source_refresh_at=now_iso())
        return 0

    existing = ws.get("items", [])
    merged, appended, updated = _items_source.merge_items(existing, fetched, strategy)

    if appended == 0 and updated == 0:
        store.update_workstream(ws["name"], last_source_refresh_at=now_iso())
        return 0

    # Persist via direct full save (update_item is per-item; we need bulk replace)
    ws_full = store.load(ws["name"])
    ws_full["items"] = merged
    ws_full["last_source_refresh_at"] = now_iso()
    store.save(ws_full)
    logger.info(
        "items_source[%s]: refreshed workstream %s — appended=%d updated=%d "
        "(strategy=%s, total_items=%d)",
        src.get("type"), ws.get("name"), appended, updated, strategy, len(merged),
    )
    return appended



def _fire_before_mission_start(agent, ws: dict) -> Optional[str]:
    """Fire BeforeMissionStart hook on first activation. Returns deny reason or None."""
    runner = getattr(agent, "hook_runner", None)
    if runner is None:
        return None
    try:
        result = runner.run_before_mission_start(
            session_ctx=agent._build_session_ctx() if hasattr(agent, "_build_session_ctx") else {},
            workstream_name=ws.get("name", ""),
            owner=ws.get("owner", ""),
            total_items=len(ws.get("items", [])),
            skill=ws.get("skill", ""),
        )
        if getattr(result, "blocked", False):
            return getattr(result, "reason", "blocked by BeforeMissionStart hook")
    except Exception as exc:
        logger.debug("BeforeMissionStart hook fire failed: %s", exc)
    return None


def _fire_on_mission_item_failed(agent, ws: dict, item: dict, error_msg: str) -> None:
    runner = getattr(agent, "hook_runner", None)
    if runner is None:
        return
    try:
        runner.run_on_mission_item_failed(
            session_ctx=agent._build_session_ctx() if hasattr(agent, "_build_session_ctx") else {},
            workstream_name=ws.get("name", ""),
            item_id=item.get("id", ""),
            attempts=int(item.get("attempts", 0)),
            error_msg=error_msg[:500],
        )
    except Exception as exc:
        logger.debug("OnMissionItemFailed hook fire failed: %s", exc)


def _fire_on_mission_complete(agent, ws: dict, started_at_iso: Optional[str]) -> None:
    runner = getattr(agent, "hook_runner", None)
    if runner is None:
        return
    try:
        items = ws.get("items", [])
        done = sum(1 for it in items if it.get("status") == "done")
        failed = sum(1 for it in items if it.get("status") == "failed")
        escalated = sum(1 for it in items if it.get("status") == "awaiting_human")
        duration = 0
        if started_at_iso:
            try:
                from datetime import datetime
                started = datetime.fromisoformat(started_at_iso.replace("Z", "+00:00"))
                duration = max(0, int((datetime.now(started.tzinfo) - started).total_seconds()))
            except Exception:
                duration = 0
        runner.run_on_mission_complete(
            session_ctx=agent._build_session_ctx() if hasattr(agent, "_build_session_ctx") else {},
            workstream_name=ws.get("name", ""),
            duration_total_sec=duration,
            items_done=done,
            items_failed=failed,
            items_escalated=escalated,
        )
    except Exception as exc:
        logger.debug("OnMissionComplete hook fire failed: %s", exc)

    try:
        meta = ws.get("meta") or {}
        if meta.get("source") == "research_orchestrator":
            bridge = get_mission_bridge()
            if bridge is not None:
                tenant_id_ = getattr(getattr(agent, "memory", None), "tenant_id", "") or default_tenant_id()
                ws_name_ = ws.get("name", "")
                bridge.on_mission_complete(ws_name_, tenant_id_)
                logger.info(
                    "mission_engine: scheduled research synthesis for %s",
                    ws_name_,
                )
    except Exception as syn_err:
        logger.debug("research synthesis trigger skipped: %s", syn_err)



def run_iteration(
    agent,
    workstream_name: str,
    tenant_id: str,
    store: Optional[WorkstreamStore] = None,
    tenant_root: Optional[Path] = None,
    automation_runner: Optional[Callable[..., dict[str, Any]]] = None,
) -> IterationResult:
    """
    Process exactly ONE eligible item from the named workstream.

    Args:
        agent:           A SkillAgent instance (the one the cron handed us)
        workstream_name: Name of the workstream YAML (without .yaml suffix)
        tenant_id:       Tenant id (used for store path resolution if store omitted)
        store:           Optional WorkstreamStore (constructed from tenant_root if absent)
        tenant_root:     Required if store is None. Path to enterprise_root/tenants/<id>/
        automation_runner: Optional host callback for deterministic automations.

    Returns:
        IterationResult describing what happened.
    """
    if store is None:
        if tenant_root is None:
            tenant_root = Path(getattr(agent.kernel, "tenant_root", "."))
        store = WorkstreamStore(tenant_root)

    started = time.time()
    started_at_iso = now_iso()

    try:
        ws = store.load(workstream_name)
    except FileNotFoundError as exc:
        return IterationResult(
            action="nothing_pending",
            workstream_name=workstream_name,
            reason=str(exc),
            duration_ms=int((time.time() - started) * 1000),
        )

    # Status gate
    if ws.get("status") != "active":
        return IterationResult(
            action="nothing_pending",
            workstream_name=workstream_name,
            workstream_status=ws.get("status", ""),
            reason=f"workstream status is {ws.get('status')!r}",
            duration_ms=int((time.time() - started) * 1000),
        )

    # Refresh items from source (if configured)
    if ws.get("items_source"):
        _refresh_items_from_source(store, ws, agent, tenant_root or Path(getattr(agent.kernel, "tenant_root", ".")))
        ws = store.load(workstream_name)  # reload to see merged items

    # First-activation hook (gateable)
    if not ws.get("started_at"):
        block_reason = _fire_before_mission_start(agent, ws)
        if block_reason:
            return IterationResult(
                action="blocked_by_hook",
                workstream_name=workstream_name,
                workstream_status=ws.get("status", ""),
                reason=f"BeforeMissionStart denied: {block_reason}",
                duration_ms=int((time.time() - started) * 1000),
            )
        store.mark_started_if_first(workstream_name)
        ws = store.load(workstream_name)  # reload with started_at populated

    item = store.claim_next_item(workstream_name)
    if item is None:
        ws_after = store.load(workstream_name)
        if WorkstreamStore.is_terminal(ws_after):
            fired_now = store.mark_completed_once(workstream_name)
            ws_after = store.load(workstream_name)
            if fired_now:
                _fire_on_mission_complete(agent, ws_after, ws.get("started_at"))
            _complete_result = IterationResult(
                action="workstream_completed",
                workstream_name=workstream_name,
                workstream_status="completed",
                reason="all items terminal",
                duration_ms=int((time.time() - started) * 1000),
            )
            _publish_ws_event(_complete_result)
            return _complete_result
        return IterationResult(
            action="nothing_pending",
            workstream_name=workstream_name,
            workstream_status=ws_after.get("status", ""),
            reason="no pending items (some may be awaiting_human)",
            duration_ms=int((time.time() - started) * 1000),
        )

    item_id = item["id"]
    execution_id = f"wse_{uuid.uuid4().hex[:12]}"
    max_attempts = int(ws.get("max_attempts_per_item", 3))
    status_before = "pending"  # claim_next_item only picks from pending
    attempt_no = int(item.get("attempts", 0) or 0)
    _runtime_create_execution(
        execution_id=execution_id,
        workstream_name=workstream_name,
        item_id=item_id,
        tenant_id=tenant_id,
        skill_name=ws.get("skill") or ws.get("automation") or "",
        attempt=attempt_no,
        started_at=started_at_iso,
    )
    try:
        store.update_item(workstream_name, item_id, current_execution_id=execution_id)
    except Exception as exc:
        logger.debug("current_execution_id update skipped for %s: %s", item_id, exc)
    _publish_item_started(
        workstream_name,
        item_id,
        execution_id=execution_id,
        attempts=attempt_no,
    )

    # Build the prompt for the worker skill
    ac = item.get("acceptance_criteria") or []
    ac_block = ""
    if ac:
        ac_block = "\n\nAcceptance criteria (you must satisfy ALL of these):\n" + \
                   "\n".join(f"- {c}" for c in ac)

    evidence_block = (
        "\n\nEVIDENCE REQUIREMENT — non-negotiable for audit compliance:\n"
        "Before recommending any action or calling request_human_approval you MUST:\n"
        "  1. Fetch the LIVE invoice data — do NOT trust the description text.\n"
        "     For AP items, query the secure finance API. Example:\n"
        "       curl -s -H \"X-API-Key: read_demo_key_abc123\" "
        "http://localhost:9092/invoices/<INVOICE_ID>\n"
        "  2. Read the relevant policy file via the shell tool. Example:\n"
        "       cat /shared/contexts/judgment/fa_judgment.md\n"
        "  3. Cite BOTH in your approval reason as: "
        "'Live amount=X EUR (per /invoices/INV-XYZ); policy threshold=Y (per fa_judgment.md §<section>)'.\n"
        "Skipping these steps produces an empty evidence bundle and the approval "
        "will be rejected by the audit hook."
    )
    approval_gate_block = ""
    if _item_requires_human_approval(item):
        approval_gate_block = (
            "\n\nHUMAN APPROVAL GATE — mandatory:\n"
            "This workstream item is marked approval-required by policy. After collecting "
            "the required evidence, call request_human_approval and wait for a human "
            "decision before treating the item as complete."
        )

    prompt = (
        f"You are processing a Mission Mode workstream item.\n"
        f"Workstream: {ws.get('display_name') or ws['name']}\n"
        f"Item id: {item_id}\n"
        f"Task: {item.get('description', '')}{ac_block}{evidence_block}{approval_gate_block}\n\n"
        f"After fetching the evidence, decide:\n"
        f"  - If the live data confirms the policy requires human approval → call "
        f"request_human_approval with reason citing your evidence sources.\n"
        f"  - Otherwise perform the resolution action and return a concise summary."
    )

    _clear_stale_item_approval(agent, workstream_name, item_id, phase="before_run")
    agent._mission_workstream = workstream_name
    agent._mission_item_id = item_id

    # Hand off to existing agent.run() — all reasoning, security, evidence, HITL
    # flows through the regular code path.
    response = ""
    tool_calls: list = []
    live_steps: list[dict[str, Any]] = []
    step_counter = [0]
    error_caught: Optional[Exception] = None
    evidence_count = 0

    def step_callback(msg: Any) -> None:
        """Capture and stream agent progress without affecting execution."""
        try:
            step_counter[0] += 1
            step = _status_callback_step(msg, step_counter[0])
            step = _runtime_append_step(execution_id, step)
            live_steps.append(step)
            _publish_step_event(
                workstream_name,
                item_id,
                execution_id=execution_id,
                step=step,
            )
        except Exception as exc:
            logger.debug("mission step capture failed (non-fatal): %s", exc)

    try:
        automation_id = str(ws.get("automation") or "").strip()
        if automation_id:
            if automation_runner is None:
                raise RuntimeError(
                    f"Workstream '{workstream_name}' declares automation '{automation_id}' "
                    "but no automation runner was provided by the host."
                )
            automation_result = automation_runner(
                automation_id=automation_id,
                tenant_id=tenant_id,
                agent_id=getattr(getattr(agent, "kernel", None), "agent_id", "enterprise_agent"),
                user_id=getattr(agent, "user_id", "") or "service:workstream",
                trigger="workstream",
                input_text=prompt,
                context={
                    "workstream_name": workstream_name,
                    "item_id": item_id,
                    "item": item,
                    "acceptance_criteria": ac,
                },
            )
            for auto_step in ((automation_result.get("trace") or {}).get("steps") or []):
                step_callback({
                    "__progress__": True,
                    "workflow_step": auto_step.get("step_name") or auto_step.get("name") or "",
                    "workflow_action": auto_step.get("action") or "automation",
                    "status": auto_step.get("status") or "",
                    "elapsed_ms": auto_step.get("duration_ms") or 0,
                    "detail": auto_step.get("error") or auto_step.get("output") or "",
                })
            response = automation_result.get("summary") or ""
            if automation_result.get("status") == "failed":
                response = f"Error: {response}"
        else:
            result = agent.run(
                query=prompt,
                skill_name=ws["skill"],
                return_tool_calls=True,
                skip_memory=False,
                status_callback=step_callback,
            )
            if isinstance(result, tuple) and len(result) >= 2:
                response, tool_calls = result[0], (result[1] or [])
            else:
                response = result or ""
    except Exception as exc:
        error_caught = exc
        response = f"Error: {exc}"
        logger.warning("workstream execution failed for item %s: %s", item_id, exc)

    trace_id = getattr(agent, "_active_trace_id", "") or ""
    _clear_stale_item_approval(agent, workstream_name, item_id, phase="after_run")
    _synthesize_workstream_approval(agent, ws, item, workstream_name, response)
    approval_pending = getattr(agent, "approval_pending", None)
    approval_id = (approval_pending or {}).get("approval_id") if approval_pending else None

    if approval_pending and approval_id:
        try:
            # Delegate to the host Mission bridge. The host owns event-loop
            # scheduling and Redis persistence; no-op without a bridge (tests/CLI).
            bridge = get_mission_bridge()
            if bridge is not None:
                tenant_id_ = getattr(getattr(agent, "memory", None), "tenant_id", "") or ""
                user_id_ = getattr(agent, "user_id", "") or "service:cron"
                skill_name_ = ws.get("skill") or "general"
                bridge.checkpoint_hitl(
                    agent, tenant_id_, user_id_, skill_name_,
                    source="mission_mode",
                )
                logger.info(
                    "mission_engine: HITL approval persisted to Redis: %s [item=%s]",
                    approval_id[:8], item_id,
                )
        except Exception as _hitl_err:
            logger.warning(
                "mission_engine: HITL Redis persist failed for item %s: %s",
                item_id, _hitl_err,
            )

    try:
        ec = getattr(agent, "_evidence_collector", None)
        bundle = getattr(agent, "_evidence_bundle", None) or {}
        if ec is not None and not (bundle.get("documents") or bundle.get("evidence_items")):
            # Bundle was never finalized (likely the PENDING path) — build it now.
            mem = getattr(agent, "memory", None)
            bundle = ec.get_bundle(
                response_text=response or "",
                query_text=prompt,
                trace_id=str(trace_id or ""),
                tenant_id=getattr(mem, "tenant_id", "") or "",
                agent_id=getattr(mem, "agent_id", "") or "",
                user_id=getattr(agent, "user_id", "") or "",
                execution_source="mission",
                highlight_config={},
            )
        if bundle and (bundle.get("documents") or bundle.get("evidence_items")):
            bundle["execution_source"] = "mission"
            bundle["trace_id"] = trace_id  # ensure it matches item.last_trace_id
            evidence_count = len(bundle.get("documents") or []) + len(bundle.get("evidence_items") or [])
            from iaf_agent_skills.evidence_collector_adapter import EvidenceCollectorAdapter
            EvidenceCollectorAdapter().persist(bundle)
            logger.info(
                "mission_engine: persisted evidence bundle trace=%s docs=%d items=%d",
                trace_id[:8] if trace_id else "?",
                len(bundle.get("documents") or []),
                len(bundle.get("evidence_items") or []),
            )
    except Exception as _ev_err:  # observe-only — bundle persistence MUST not block the loop
        logger.debug("mission_engine evidence persistence skipped: %s", _ev_err)

    # Classify — governed LLM grader against the item's acceptance_criteria, with the
    # deterministic keyword chain as a self-healing fallback (grader off / model unreachable).
    new_status, reason = _classify_outcome(
        response=response,
        tool_calls=tool_calls,
        agent_approval_pending=approval_pending,
        item=item,
        max_attempts=max_attempts,
        grader=_make_outcome_grader(agent),
        task=str(item.get("description") or ""),
    )
    completed_at_iso = now_iso()
    duration_ms = int((time.time() - started) * 1000)
    tool_steps: list[dict[str, Any]] = []
    for tool_step in _tool_call_steps(tool_calls):
        step_counter[0] += 1
        numbered = dict(tool_step)
        numbered["step_index"] = step_counter[0]
        numbered["step_number"] = step_counter[0]
        tool_steps.append(_runtime_append_step(execution_id, numbered))
    runtime_status = {
        "done": "completed",
        "awaiting_human": "awaiting_human",
        "failed": "failed",
        "pending": "pending",
    }.get(new_status, new_status)
    _runtime_finalize_execution(
        execution_id,
        status=runtime_status,
        completed_at=None if runtime_status == "awaiting_human" else completed_at_iso,
        duration_ms=duration_ms,
        result_summary=reason,
        error_summary=str(error_caught or ""),
        trace_id=trace_id or "",
        evidence_trace_id=trace_id or "",
        evidence_count=evidence_count,
        approval_id=approval_id or "",
    )

    execution_log = list(item.get("execution_log") or [])
    execution_log.append({
        "attempt": int(item.get("attempts", 0) or 0),
        "status_before": status_before,
        "status_after": new_status,
        "started_at": started_at_iso,
        "completed_at": completed_at_iso,
        "duration_ms": duration_ms,
        "trace_id": trace_id or "",
        "evidence_trace_id": trace_id or "",
        "evidence_count": evidence_count,
        "approval_id": approval_id or "",
        "result_preview": reason,
        "error_preview": str(error_caught or ""),
    })

    ledger_entry = {
        "execution_id": execution_id,
        "attempt": int(item.get("attempts", 0) or 0),
        "status_before": status_before,
        "status_after": new_status,
        "started_at": started_at_iso,
        "completed_at": completed_at_iso,
        "duration_ms": duration_ms,
        "trace_id": trace_id or "",
        "evidence_trace_id": trace_id or "",
        "evidence_count": evidence_count,
        "approval_id": approval_id or "",
        "result_preview": reason,
        "error_preview": str(error_caught or ""),
        "steps": live_steps + tool_steps,
    }

    # Persist outcome
    patch: dict[str, Any] = {
        "status": new_status,
        "last_trace_id": trace_id,
        "evidence_trace_id": trace_id or None,
        "evidence_count": evidence_count,
        "last_result_summary": reason,
        "last_result_at": completed_at_iso,
        "execution_log": execution_log,
        "current_execution_id": execution_id,
        "suggested_actions": _suggested_actions_for_status(new_status),
    }
    if new_status == "done":
        patch["resolution"] = reason
        patch["escalated_approval_id"] = None
        patch["last_approval_context"] = None
    elif new_status == "awaiting_human":
        patch["escalated_approval_id"] = approval_id
        patch["last_approval_context"] = (approval_pending or {}).get("context") or None
    elif new_status == "failed":
        patch["resolution"] = reason
        patch["last_failure_reason"] = reason
    # for "pending" (retry) we leave resolution untouched
    store.append_item_execution(workstream_name, item_id, ledger_entry, **patch)

    # OnMissionItemFailed hook (terminal failure only — not retries)
    if new_status == "failed":
        ws_after = store.load(workstream_name)
        item_after = next((i for i in ws_after["items"] if i["id"] == item_id), item)
        _fire_on_mission_item_failed(agent, ws_after, item_after, reason)

    workstream_status_after = ws.get("status", "active")
    ws_after = store.load(workstream_name)
    if WorkstreamStore.is_terminal(ws_after) and store.mark_completed_once(workstream_name):
        ws_final = store.load(workstream_name)
        _fire_on_mission_complete(agent, ws_final, ws_final.get("started_at"))
        workstream_status_after = "completed"

    action = {
        "done": "item_processed",
        "awaiting_human": "item_escalated",
        "failed": "item_failed",
        "pending": "item_processed",  # retry-pending
    }.get(new_status, "item_processed")

    _final_result = IterationResult(
        action=action,
        workstream_name=workstream_name,
        item_id=item_id,
        item_status_before=status_before,
        item_status_after=new_status,
        attempts=int(item.get("attempts", 0)) + 1,
        approval_id=approval_id,
        trace_id=trace_id,
        duration_ms=duration_ms,
        reason=reason[:500],
        workstream_status=workstream_status_after,
    )
    _publish_ws_event(_final_result)
    return _final_result



def run_n(
    agent_factory,
    workstream_name: str,
    tenant_id: str,
    *,
    count: int = 1,
    parallel: int = 1,
    store: Optional[WorkstreamStore] = None,
    tenant_root: Optional[Path] = None,
    automation_runner: Optional[Callable[..., dict[str, Any]]] = None,
) -> list:
    """Drain up to ``count`` items from a workstream, with at most ``parallel``
    items in flight concurrently.

    Each item is processed by a fresh SkillAgent built via ``agent_factory()``
    — using one shared agent across concurrent calls would race on
    ``_active_trace_id`` / ``_evidence_bundle`` / ``approval_pending``.
    The factory is invoked per worker slot, not per item.

    Args:
        agent_factory:   ``Callable[[], SkillAgent]`` — must return a fresh
                         agent each call. Service principal binding (cron /
                         queue) should already be baked into the factory.
        workstream_name: Name of the workstream YAML (without .yaml suffix).
        tenant_id:       Tenant id for store path resolution.
        count:           Max items to drain in this call (default 1).
        parallel:        Max items in flight concurrently (default 1).
                         Clamped to [1, count]. Each slot uses its own agent.
        store:           Optional pre-built WorkstreamStore.
        tenant_root:     Required if store is None.
        automation_runner: Optional host callback for no-LLM automations.

    Returns:
        List[IterationResult] — one per item attempted, in completion order.
        May be shorter than ``count`` if the workstream drains to terminal
        state (``action == "nothing_pending"`` short-circuits the loop).

    Backwards compatibility:
        ``count=1, parallel=1`` produces the same single-item behaviour as
        a direct ``run_iteration()`` call. Existing cron callers remain on
        ``run_iteration`` — this function is opt-in for batch drains via
        the ``/api/workstreams/{name}/run`` endpoint.
    """
    import asyncio

    count = max(1, int(count or 1))
    parallel = max(1, min(int(parallel or 1), count))

    if store is None:
        if tenant_root is None:
            tenant_root = Path(getattr(
                # Probe one agent to find tenant_root if caller omitted it.
                # Factory should be cheap — this is a one-shot peek.
                agent_factory().kernel, "tenant_root", "."
            ))
        store = WorkstreamStore(tenant_root)

    semaphore = asyncio.Semaphore(parallel)
    results: list = []
    stop = asyncio.Event()

    async def _drain_one(slot_idx: int, ordinal: int):
        if stop.is_set():
            return None
        async with semaphore:
            if stop.is_set():
                return None
            # Fresh agent per concurrent attempt — never share an agent.
            agent = await asyncio.to_thread(agent_factory)
            result = await asyncio.to_thread(
                run_iteration,
                agent,
                workstream_name,
                tenant_id,
                store=store,
                tenant_root=tenant_root,
                automation_runner=automation_runner,
            )
            if result.action == "nothing_pending":
                stop.set()  # workstream drained — abort remaining slots
            return result

    async def _run_all():
        coros = [_drain_one(i % parallel, i) for i in range(count)]
        outcomes = await asyncio.gather(*coros, return_exceptions=True)
        return outcomes

    try:
        loop = asyncio.get_running_loop()
        # In a running event loop (e.g. called from an async route) — bridge
        # via a thread so we don't deadlock the loop with .run_until_complete.
        import concurrent.futures
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            outcomes = pool.submit(asyncio.run, _run_all()).result(timeout=600)
    except RuntimeError:
        outcomes = asyncio.run(_run_all())

    for out in outcomes:
        if isinstance(out, Exception):
            logger.warning("run_n slot failed: %s", out)
            continue
        if out is None:
            continue
        results.append(out)

    return results
