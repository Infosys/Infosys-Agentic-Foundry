"""Shared tool-call governance firewall for React runtimes."""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any
import uuid

from .hook_approval import wants_hitl
from .react_runtime.types import ToolGovernanceDecision
from . import cancellation as _run_cancel

logger = logging.getLogger(__name__)

# Fail-closed sentinel for the MCP-config attestation: distinguishes "could not
# compute the fingerprint" (e.g. a transient skill-load/config error) from "the skill
# has no MCP connections" (None). A recorded or current value of this sentinel forces
# the stale-approval guard to REFUSE rather than silently skip — a dangerous MCP
# approval must never resume without a verified configuration attestation. Not a valid
# sha256 hex string, so it can never collide with a real fingerprint.
MCP_FP_UNAVAILABLE = "mcp-fp-unavailable"


def _tool_call_parts(tool_call: dict[str, Any]) -> tuple[str, str, dict[str, Any]]:
    call_id = str(tool_call.get("id") or "")
    tool_name = str(tool_call.get("name") or "")
    raw_args = tool_call.get("args") or {}
    tool_args = raw_args if isinstance(raw_args, dict) else {}
    return call_id, tool_name, tool_args


def _pending_target(tool_name: str, tool_args: dict[str, Any]) -> str:
    return str(tool_args.get("path") or tool_args.get("command", "")[:80])


def _stamp_mcp_fingerprint(agent: Any, tool_call: dict[str, Any]) -> None:
    """Record the active skill's MCP-config fingerprint on the held tool call so a
    cold resume can detect (and refuse) a stale approval whose MCP connection config
    changed while it sat in the approval queue. No-op when the skill has no MCP
    connections or the agent lacks the helper (older agents)."""
    fp_fn = getattr(agent, "_skill_mcp_fingerprint", None)
    if fp_fn is None or not isinstance(tool_call, dict):
        return
    try:
        fp = fp_fn(getattr(agent, "current_skill", None))
    except Exception:
        # Fail closed: the attestation could not be produced — stamp the sentinel so
        # the resume refuses, rather than skipping the guard (which would let the call
        # resume unvalidated).
        logger.debug("MCP fingerprint stamp failed; stamping fail-closed sentinel", exc_info=True)
        fp = MCP_FP_UNAVAILABLE
    # None => skill genuinely has no MCP connections (nothing to attest → no stamp).
    # A hash or the fail-closed sentinel is stamped so the resume validates it.
    if fp is not None:
        tool_call["_mcp_config_fp"] = fp


def _approval_config(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _approval_options(config: dict[str, Any]) -> list[str]:
    raw = config.get("options")
    if isinstance(raw, str) and raw.strip():
        return [raw.strip()]
    if isinstance(raw, list):
        options = [str(item).strip() for item in raw if str(item).strip()]
        if options:
            return options
    return ["Approve", "Reject"]


def _approval_sla(config: dict[str, Any], default: int) -> int:
    try:
        value = int(config.get("sla_minutes", default))
    except (TypeError, ValueError):
        return default
    return value if value > 0 else default


def _runtime_context(agent: Any, session_ctx: dict[str, Any] | None = None) -> dict[str, str]:
    """Return runtime attribution when a tool block occurs in chat/cron/queue/workstreams."""
    session_ctx = session_ctx or {}
    context: dict[str, str] = {}
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

    workstream_name = session_ctx.get("workstream_name") or session_ctx.get("workstream") or getattr(agent, "_mission_workstream", None)
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


def _set_pending_action(agent: Any, *, tool_name: str, tool_args: dict[str, Any], reason: str, command: str) -> None:
    operation = "write" if tool_name == "write_file" else "shell"
    if command != "__STREAM_INTERCEPT__":
        operation = "append" if tool_args.get("append") else operation
    agent.pending_action = {
        "operation": operation,
        "target": _pending_target(tool_name, tool_args),
        "command": command,
        "tool_name": tool_name,
        "skill": getattr(agent, "current_skill", "") or "",
        "timestamp": datetime.now(),
        "reason": reason,
    }


def _set_auto_run_approval(
    agent: Any,
    *,
    tool_name: str,
    tool_args: dict[str, Any],
    reason: str,
    rule_type: str,
    approval: dict[str, Any] | None = None,
    session_ctx: dict[str, Any] | None = None,
) -> None:
    approval_cfg = _approval_config(approval)
    context = {
        "tool": tool_name,
        "command": tool_args.get("command", "")[:200] or tool_args.get("path", ""),
        "skill": getattr(agent, "current_skill", "") or "",
    }
    if isinstance(approval_cfg.get("context"), dict):
        context.update(approval_cfg["context"])
    context.update(_runtime_context(agent, session_ctx))
    agent.approval_pending = {
        "approval_id": str(uuid.uuid4()),
        "reason": reason,
        "context": context,
        "options": _approval_options(approval_cfg),
        "urgency": str(approval_cfg.get("urgency") or "high"),
        "sla_minutes": _approval_sla(approval_cfg, 60),
        "skill": getattr(agent, "current_skill", None) or "unknown",
        "rule_matched": reason,
        "rule_type": str(approval_cfg.get("rule_type") or rule_type),
        "timestamp": datetime.now().isoformat(),
    }


def _set_stream_intercept_approval(
    agent: Any,
    *,
    tool_name: str,
    tool_args: dict[str, Any],
    call_id: str,
    reason: str,
    approval: dict[str, Any] | None = None,
    session_ctx: dict[str, Any] | None = None,
) -> None:
    """Arm a DURABLE approval record for an interactive (non-auto_run) stream-intercept
    block so the held call can be resumed after a restart / session eviction.

    The full executable call rides in agent_state.pending_tool_call (serialized via
    export_state), so the durable approval `context` carries only a bounded, redacted
    preview plus the routing keys (resume_kind, tool, tool_call_id). If the same call is
    already armed, reuse its approval_id — never mint a new one (would strand the UI's id).
    """
    existing = getattr(agent, "approval_pending", None)
    if (
        isinstance(existing, dict)
        and (existing.get("context") or {}).get("resume_kind") == "stream_intercept"
        and (existing.get("context") or {}).get("tool_call_id") == call_id
    ):
        existing_context = existing.setdefault("context", {})
        if isinstance(existing_context, dict):
            existing_context.update(_runtime_context(agent, session_ctx))
        return
    preview = ""
    if isinstance(tool_args, dict):
        preview = str(
            tool_args.get("command")
            or tool_args.get("path")
            or tool_args.get("query")
            or tool_args.get("sql")
            or ""
        )[:200]
    approval_cfg = _approval_config(approval)
    context = {
        "resume_kind": "stream_intercept",
        "tool": tool_name,
        "tool_call_id": call_id,
        "preview": preview,
        "skill": getattr(agent, "current_skill", "") or "",
    }
    if isinstance(approval_cfg.get("context"), dict):
        context.update(approval_cfg["context"])
    context.update(_runtime_context(agent, session_ctx))
    agent.approval_pending = {
        "approval_id": str(uuid.uuid4()),
        "reason": reason,
        "context": context,
        "options": _approval_options(approval_cfg),
        "urgency": str(approval_cfg.get("urgency") or "high"),
        "sla_minutes": _approval_sla(approval_cfg, 60),
        "skill": getattr(agent, "current_skill", None) or "unknown",
        "rule_matched": reason,
        "rule_type": str(approval_cfg.get("rule_type") or "stream_intercept"),
        "timestamp": datetime.now().isoformat(),
    }


def mirror_child_pause(parent: Any, child: Any, *, skill_name: str = "", task: str = "") -> str | None:
    """Copy a delegated *child* agent's HITL pause onto the *parent* (session) agent.

    When a skill delegates to another skill (invoke_skill / orchestrator / supervisor)
    and the child pauses for human approval, that pause lives only on the child object,
    which is discarded — so the UI (which reads the *session* agent's ``pending_action`` /
    ``pending_tool_call`` and the durable ``approval_pending``) shows no approval buttons
    and the held call is lost. Mirroring the three pause fields onto the parent surfaces
    the approval and lets ``resume_approved_tool_call`` execute the held call on approval.

    First pause wins: if the parent already has a pending approval, this is a no-op so a
    second delegated pause can't clobber the first. Returns a short notice string for the
    delegating tool to return (so the ReAct loop halts on an observation), or ``None`` when
    there was nothing to mirror.
    """
    child_tc = getattr(child, "pending_tool_call", None)
    child_pa = getattr(child, "pending_action", None)
    child_ap = getattr(child, "approval_pending", None)
    if not (child_tc or child_pa or child_ap):
        return None
    # Don't overwrite a pause the parent already surfaced (first pause wins).
    if getattr(parent, "pending_tool_call", None) or getattr(parent, "pending_action", None):
        return None
    if child_tc is not None:
        parent.pending_tool_call = child_tc
    if child_pa is not None:
        parent.pending_action = child_pa
    if child_ap is not None:
        parent.approval_pending = child_ap
    # Record the CHILD's skill on the mirrored pause. On approval the resume runs on the
    # parent/session agent, which would otherwise scope the held call to the PARENT's skill
    # (kernel current-skill, scope-restricted credentials, and the MCP-config attestation,
    # which the child stamped against ITS skill — a parent-skill comparison fails closed).
    # Stamping the delegated skill lets _restore_kernel_skill + _execute_held_tool_call
    # scope the held call to the context it was actually reviewed under. (#3)
    _child_skill = getattr(child, "current_skill", None) or (skill_name or None)
    if _child_skill and isinstance(getattr(parent, "pending_tool_call", None), dict) \
            and not parent.pending_tool_call.get("skill"):
        try:
            parent.pending_tool_call["skill"] = _child_skill
        except Exception:
            pass
    # The inline approval card + dashboard read pending_action. A child that paused on a
    # write/dangerous call carries pending_tool_call + approval_pending but may not have the
    # legacy pending_action built yet — build it on the parent from the mirrored call so the
    # approval surfaces everywhere, not only in Command Center.
    if getattr(parent, "pending_action", None) is None and getattr(parent, "pending_tool_call", None) is not None:
        _builder = getattr(parent, "_build_stream_intercept_pending", None)
        if callable(_builder):
            try:
                _builder(skill_name)
            except Exception:
                pass
    # Carry the delegated skill onto pending_action too (its resume scope restore reads it).
    if _child_skill and isinstance(getattr(parent, "pending_action", None), dict) \
            and not parent.pending_action.get("skill"):
        try:
            parent.pending_action["skill"] = _child_skill
        except Exception:
            pass
    reason = ""
    if isinstance(child_pa, dict):
        reason = child_pa.get("reason") or child_pa.get("operation") or ""
    elif isinstance(child_ap, dict):
        reason = child_ap.get("reason", "")
    return (
        f"⏸️ Delegated skill '{skill_name or 'worker'}' needs human approval before it "
        f"can continue{(': ' + str(reason)) if reason else ''}. Awaiting your decision — the "
        f"action has NOT run yet."
    )


def govern_tool_call(agent: Any, tool_call: dict[str, Any], *, source: str) -> ToolGovernanceDecision:
    """Apply the existing pre-tool governance sequence to one structured tool call."""
    _run_cancel.check_cancelled()
    call_id, tool_name, tool_args = _tool_call_parts(tool_call)
    session_ctx = agent._build_session_ctx()
    logger.debug("govern[%s] tool=%s skill=%r", source, tool_name, session_ctx.get("skill_name", ""))

    try:
        agent.tool_execution_capability.observe_pre_tool(
            tool_name=tool_name,
            tool_input=tool_args,
            session_ctx=session_ctx,
        )
    except Exception:
        pass

    evidence_collector = getattr(agent, "_evidence_collector", None)
    if evidence_collector is not None:
        evidence_collector.record_tool_call(
            tool_call_id=call_id,
            tool_name=tool_name,
            tool_args=tool_args,
        )

    hook_result = agent.hook_runner.run_pre_tool(
        tool_name=tool_name,
        tool_input=tool_args,
        session_ctx=session_ctx,
    )
    if getattr(hook_result, "blocked", False):
        reason = getattr(hook_result, "reason", "") or f"Hook blocked {tool_name}"
        if not wants_hitl(hook_result):
            return ToolGovernanceDecision.blocked(
                reason=reason,
                tool_call_id=call_id,
                tool_name=tool_name,
                source=source,
            )
        if getattr(agent, "pending_tool_call", None) is not None and getattr(agent, "pending_action", None):
            return ToolGovernanceDecision.pending(
                reason="approval already pending",
                tool_call_id=call_id,
                tool_name=tool_name,
                source=source,
                status="already_pending",
            )
        _stamp_mcp_fingerprint(agent, tool_call)
        agent.pending_tool_call = tool_call
        _set_pending_action(
            agent,
            tool_name=tool_name,
            tool_args=tool_args,
            reason=reason,
            command="__STREAM_INTERCEPT__",
        )
        if getattr(agent, "auto_run", False):
            _set_auto_run_approval(
                agent,
                tool_name=tool_name,
                tool_args=tool_args,
                reason=reason,
                rule_type="pre_tool_hook",
                approval=getattr(hook_result, "approval", {}) or {},
                session_ctx=session_ctx,
            )
        else:
            # Interactive block — write a durable approval record so it survives a
            # restart / session eviction (B1). The auto_run path already persists above.
            _set_stream_intercept_approval(
                agent,
                tool_name=tool_name,
                tool_args=tool_args,
                call_id=call_id,
                reason=reason,
                approval=getattr(hook_result, "approval", {}) or {},
                session_ctx=session_ctx,
            )
        return ToolGovernanceDecision.pending(
            reason=reason,
            tool_call_id=call_id,
            tool_name=tool_name,
            source=source,
        )

    _preauthorised_step = source == "workflow_step"
    is_write = (
        (not _preauthorised_step)
        and (not getattr(agent, "auto_run", False))
        and agent._is_write_call(tool_name, tool_args)
    )
    is_dangerous, danger_reason = agent._is_dangerous_call(tool_name, tool_args)
    if is_write or is_dangerous:
        if getattr(agent, "pending_tool_call", None) is not None and getattr(agent, "pending_action", None):
            return ToolGovernanceDecision.pending(
                reason="approval already pending",
                tool_call_id=call_id,
                tool_name=tool_name,
                source=source,
                status="already_pending",
            )
        _stamp_mcp_fingerprint(agent, tool_call)
        agent.pending_tool_call = tool_call
        if is_dangerous:
            reason = danger_reason
        else:
            operation = "append" if tool_args.get("append") else "write" if tool_name == "write_file" else "shell"
            reason = f"{operation} operation on `{_pending_target(tool_name, tool_args)}`"
        if getattr(agent, "auto_run", False) and is_dangerous:
            _set_auto_run_approval(
                agent,
                tool_name=tool_name,
                tool_args=tool_args,
                reason=reason,
                rule_type=source,
                session_ctx=session_ctx,
            )
        elif not getattr(agent, "auto_run", False):
            # Interactive write/dangerous block — durable record for cold resume (B1).
            _set_stream_intercept_approval(
                agent, tool_name=tool_name, tool_args=tool_args, call_id=call_id, reason=reason, session_ctx=session_ctx,
            )
        return ToolGovernanceDecision.pending(
            reason=reason,
            tool_call_id=call_id,
            tool_name=tool_name,
            source=source,
        )

    return ToolGovernanceDecision.allow(tool_call_id=call_id, tool_name=tool_name, source=source)


def govern_tool_batch(agent: Any, tool_calls: list[dict[str, Any]], *, source: str) -> list[ToolGovernanceDecision]:
    """Govern a batch before execution. Callers should execute none if any decision blocks."""
    decisions: list[ToolGovernanceDecision] = []
    for tool_call in tool_calls:
        decision = govern_tool_call(agent, tool_call, source=source)
        decisions.append(decision)
        if not decision.allowed:
            # The native runtime checkpoints the ENTIRE batch when any one call is
            # gated, and _resume_native_turn later executes every call in it. Stamp
            # the MCP-config fingerprint on ALL calls (not just the gated one) so none
            # can be rebuilt against a changed MCP config without the stale-approval
            # check. The fingerprint is per-skill, so the same value applies to each.
            for _tc in tool_calls:
                _stamp_mcp_fingerprint(agent, _tc)
            break
    return decisions
