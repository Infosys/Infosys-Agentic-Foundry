"""RunContext — per-request run state as a value that travels through a run.

Deepening of the shared ``SkillAgent``: today a single agent instance is reused
across a user's requests, and each ``run()`` writes transient state onto
``self.*`` (``render_ui``, ``light_mode``, ``auto_run``, ``pending_action``,
``_plan_requested``, ``_active_trace_id``, ``_inflight_query`` …). That shared
mutation is why the per-user lane is pinned to ``max_concurrent=1``.

This module introduces the *value* that a request's state can live in instead of
on the instance, plus duck-typed :func:`bind_run_context` / :func:`restore_run_context`
helpers that apply a context onto an agent and snapshot the previous values so a
run never leaks into the next. This is the EXPAND step: the type and the seam
exist and are tested; call sites migrate onto it batch by batch, and only once
every reader uses the context can the ``self.*`` mirrors be removed and the lane
parallelised.

Duck-typed on purpose: the helpers work on any object exposing the attributes,
so they are unit-testable without constructing a real ``SkillAgent``.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Optional

# RunContext field -> agent attribute it currently maps to on SkillAgent.
# (Names verified against SkillAgent.__init__ / run()/_run_impl().)
_AGENT_ATTRS: dict[str, str] = {
    "query": "_inflight_query",
    "render_ui": "render_ui",
    "light_mode": "light_mode",
    "auto_run": "auto_run",
    "plan_requested": "_plan_requested",
    "trace_id": "_active_trace_id",
    "pending_action": "pending_action",
    "approval_pending": "approval_pending",
    "hitl_decision_injected": "_hitl_decision_injected",
}


@dataclass
class RunContext:
    """Everything a single ``run()`` needs that must NOT be shared across runs."""

    query: str = ""
    # request inputs
    render_ui: bool = False
    light_mode: bool = False
    auto_run: bool = False
    plan_requested: bool = False
    knowledge_mode: Optional[str] = None
    profile: Optional[str] = None
    trace_id: str = ""
    # run-scoped mutable state (HITL gate etc.) — per run, never shared
    pending_action: Any = None
    approval_pending: Any = None
    hitl_decision_injected: bool = False
    # profile knob restore map captured during _apply_profile
    profile_restore: Dict[str, Any] = field(default_factory=dict)


def bind_run_context(agent: Any, ctx: RunContext) -> Dict[str, Any]:
    """Apply ``ctx``'s request state onto ``agent``; return a snapshot of the
    previous attribute values so :func:`restore_run_context` can undo it.

    ``knowledge_mode`` only overrides when provided (mirrors current run() logic).
    """
    prev: Dict[str, Any] = {}
    for cfield, attr in _AGENT_ATTRS.items():
        prev[attr] = getattr(agent, attr, None)
        setattr(agent, attr, getattr(ctx, cfield))
    if ctx.knowledge_mode is not None:
        prev["knowledge_retrieval_mode"] = getattr(agent, "knowledge_retrieval_mode", None)
        setattr(agent, "knowledge_retrieval_mode", ctx.knowledge_mode)
    return prev


def restore_run_context(agent: Any, snapshot: Dict[str, Any]) -> None:
    """Restore attribute values captured by :func:`bind_run_context`."""
    for attr, value in snapshot.items():
        setattr(agent, attr, value)


def context_from_request(
    query: str,
    *,
    render_ui: bool = False,
    light_mode: bool = False,
    auto_run: bool = False,
    plan_requested: bool = False,
    knowledge_mode: Optional[str] = None,
    profile: Optional[str] = None,
    trace_id: str = "",
) -> RunContext:
    """Build a RunContext from the parameters the chat/API edge already has."""
    return RunContext(
        query=query,
        render_ui=render_ui,
        light_mode=light_mode,
        auto_run=auto_run,
        plan_requested=plan_requested,
        knowledge_mode=knowledge_mode,
        profile=profile,
        trace_id=trace_id,
    )
