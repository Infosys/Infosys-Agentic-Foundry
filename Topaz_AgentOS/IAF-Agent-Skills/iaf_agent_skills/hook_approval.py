"""Utilities for converting blocking hook results into HITL approvals."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any


def wants_hitl(result: Any) -> bool:
    """Return True when a blocking hook explicitly asks for an approval checkpoint."""
    return bool(getattr(result, "blocked", False) and getattr(result, "on_block", "") == "hitl")


def wants_retry(result: Any) -> bool:
    """Return True when a blocking hook asks the workflow to re-run the current step
    (auto-correct with feedback, bounded by max_step_retries, then escalate)."""
    return bool(getattr(result, "blocked", False) and getattr(result, "on_block", "") == "retry")


def _string_list(value: Any, default: list[str]) -> list[str]:
    if isinstance(value, str) and value.strip():
        return [value.strip()]
    if isinstance(value, list):
        items = [str(item).strip() for item in value if str(item).strip()]
        if items:
            return items
    return list(default)


def _int_value(value: Any, default: int) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return default
    return number if number > 0 else default


def _agent_context(agent: Any, session_ctx: dict[str, Any]) -> dict[str, Any]:
    context: dict[str, Any] = {}

    attr_names = {
        "entrypoint": "_entrypoint",
        "queue_item_id": "_queue_item_id",
        "exec_id": "_queue_exec_id",
        "tenant_id": "_tenant_id",
        "user_id": "user_id",
        "agent_id": "_agent_id",
    }
    for key, attr_name in attr_names.items():
        value = session_ctx.get(key) or getattr(agent, attr_name, None)
        if value:
            context[key] = str(value)

    workstream_name = (
        session_ctx.get("workstream_name")
        or session_ctx.get("workstream")
        or getattr(agent, "_mission_workstream", None)
    )
    item_id = (
        session_ctx.get("mission_item_id")
        or session_ctx.get("item_id")
        or session_ctx.get("workstream_item")
        or getattr(agent, "_mission_item_id", None)
    )
    if workstream_name:
        context["workstream_name"] = str(workstream_name)
    if item_id:
        context["mission_item_id"] = str(item_id)

    return context


def build_hook_approval(
    agent: Any,
    hook_result: Any,
    *,
    session_ctx: dict[str, Any],
    skill_name: str,
    query: str = "",
    response: str = "",
    extra_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build an approval_pending payload from a blocking hook result."""
    approval_cfg = getattr(hook_result, "approval", None) or {}
    if not isinstance(approval_cfg, dict):
        approval_cfg = {}

    reason = str(getattr(hook_result, "reason", "") or approval_cfg.get("reason") or "Hook policy requires human approval.")
    urgency = str(approval_cfg.get("urgency") or "high")
    options = _string_list(approval_cfg.get("options"), ["Approve", "Reject"])
    sla_minutes = _int_value(approval_cfg.get("sla_minutes"), 60)
    hook_event = str(getattr(hook_result, "hook_event", "") or session_ctx.get("hook_event") or "")
    hook_id = str(getattr(hook_result, "hook_id", "") or hook_event or "hook")

    context = {
        **_agent_context(agent, session_ctx),
        "action": "hook_policy_review",
        "hook_event": hook_event,
        "hook_id": hook_id,
        "skill": skill_name,
    }
    if query:
        context["query_preview"] = str(query)[:1000]
    if response:
        context["response_preview"] = str(response)[:1000]
    if isinstance(approval_cfg.get("context"), dict):
        context.update(approval_cfg["context"])
    if extra_context:
        context.update(extra_context)

    resume_kind = approval_cfg.get("resume_kind")
    if resume_kind:
        context["resume_kind"] = str(resume_kind)

    return {
        "approval_id": str(uuid.uuid4()),
        "reason": reason,
        "context": context,
        "options": options,
        "urgency": urgency,
        "sla_minutes": sla_minutes,
        "skill": skill_name or "unknown",
        "rule_matched": reason,
        "rule_type": str(approval_cfg.get("rule_type") or "hook_policy"),
        "timestamp": datetime.now().isoformat(),
    }


def set_hook_approval(
    agent: Any,
    hook_result: Any,
    *,
    session_ctx: dict[str, Any],
    skill_name: str,
    query: str = "",
    response: str = "",
    extra_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Set agent.approval_pending from a blocking hook and return the payload."""
    approval = build_hook_approval(
        agent,
        hook_result,
        session_ctx=session_ctx,
        skill_name=skill_name,
        query=query,
        response=response,
        extra_context=extra_context,
    )
    agent.approval_pending = approval
    return approval
