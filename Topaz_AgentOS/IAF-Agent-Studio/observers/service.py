"""
Observers — gateway service (the only write path).

`ObserverService.act()` governs an observer's request to run a skill. Two modes:

  - AUTO  (trust tier / trigger allows auto): run the skill immediately through
    the existing lane queue; still checkpoint any HITL the skill itself raises.

  - HUMAN (the deterministic "hook"): when the observer's trust tier or the
    detected trigger marks the action as human-approval, the gateway creates a
    REAL approval in the platform's Redis approval_store (source="observer") and
    returns pending_approval WITHOUT running the skill. The pending item shows in
    the dashboard (/dashboard/v2 → HITL Approvals). The deferred action is stored
    on the approval; `resolve()` runs the skill only after a human approves.

This is pattern-detection → HITL, enforced at the gateway (not left to the LLM).
"""

import json
import logging
import uuid
from typing import Any, Optional

from observers import policy
from observers.models import ActRequest, ActResponse, Approval
from observers.store import ObserverStore, get_observer_store


def _bind_observer_principal(agent, tenant_id: str, user_id: str) -> None:
    """Run observer-triggered skills as the `service:observer` principal.

    Without this the agent kept whatever principal it last had (or none), and the kernel's
    egress / SQL / credential gates were skipped. Grants for service:observer live in the
    tenant's policies.yaml; with none, governed actions are denied (fail closed).
    """
    from security.dependencies import make_agent_entitlement_checker, make_service_principal
    principal = make_service_principal(tenant_id, "observer", user_id=user_id)
    agent.set_entitlement_context(principal, make_agent_entitlement_checker(principal))


logger = logging.getLogger(__name__)


class ObserverService:
    def __init__(self, store: Optional[ObserverStore] = None):
        self.store = store or get_observer_store()

    async def act(self, req: ActRequest) -> ActResponse:
        """Govern an observer action: gate at the gateway, then auto-run or defer."""
        from shared.state import (
            state, queue_manager, checkpoint_hitl_if_needed, QueueNames,
        )

        # 1. Authority: the ObserverSpec is the source of truth, not the caller.
        spec = self.store.get_spec(req.observer)
        if spec is None:
            logger.warning("act() for unknown observer '%s' — denied", req.observer)
            return ActResponse(status="denied", message=f"unknown observer '{req.observer}'")

        # An empty allowed_skills means the trigger skills, not any skill.
        effective_allowed = spec.allowed_skills or [
            t.skill for t in spec.triggers if getattr(t, "skill", "")
        ]
        # Deny when neither an allowlist nor trigger skills are configured — an observer
        # with no declared skills must not become an open /act gateway (notify aside).
        if not effective_allowed and req.skill not in policy.NOTIFY_SKILLS:
            logger.info("Observer '%s' DENIED skill '%s': no allowed_skills/trigger skills",
                        spec.name, req.skill)
            return ActResponse(status="denied",
                               message=f"observer '{spec.name}' declares no actionable skills")
        decision = policy.evaluate(
            trust_tier=spec.trust_tier,
            skill=req.skill,
            requested_approval=req.approval,
            allowed_skills=effective_allowed,
        )
        if decision.denied:
            logger.info("Observer '%s' DENIED skill '%s': %s",
                        spec.name, req.skill, decision.reason)
            return ActResponse(status="denied", message=decision.reason)

        effective_approval = decision.approval
        tenant_id, agent_id, user_id = spec.tenant_id, spec.agent_id, spec.user_id

        # 3. HOOK: human-approval actions create a real gateway approval and STOP
        #    here (the skill runs on approval, in resolve()).
        if effective_approval == Approval.human:
            return await self._create_gateway_approval(spec, req)

        # KNOWN LIMITATION: reuses the pooled agent of the spec-configured user_id; needs an isolated observer identity.
        agent = state.get_or_create(tenant_id, agent_id, user_id)
        # Force auto_run for this action and restore the prior value in the finally below.
        _prev_auto_run = getattr(agent, "auto_run", False)
        agent.auto_run = True
        agent._telemetry_entrypoint = "observer"
        _bind_observer_principal(agent, tenant_id, user_id)
        lane_name = QueueNames.session(tenant_id, user_id)
        try:
            response = await queue_manager.enqueue(
                lane_name,
                lambda: agent.run(req.task, skill_name=req.skill),
                max_concurrent=1,  # SAFETY-CRITICAL — see routers/chat.py
            )
        finally:
            # Restore before persistence/return (runs on success and on exception).
            agent.auto_run = _prev_auto_run
        # A skill may still raise its own HITL — persist it if so.
        hitl = await checkpoint_hitl_if_needed(
            agent, tenant_id, user_id, req.skill, source="observer"
        )
        try:
            await state.save_agent_state(agent, tenant_id, agent_id, user_id)
        except Exception as exc:
            logger.warning("save_agent_state failed (non-fatal): %s", exc)

        if hitl:
            return ActResponse(status="pending_approval",
                               approval_id=hitl.get("approval_id"),
                               message=hitl.get("reason", "Awaiting human approval"))
        logger.info("Observer '%s' -> skill '%s' EXECUTED", spec.name, req.skill)
        return ActResponse(status="executed", message=str(response)[:2000])

    async def _create_gateway_approval(self, spec, req: ActRequest) -> ActResponse:
        from shared.state import approval_store, ApprovalRequest, dashboard

        approval_id = uuid.uuid4().hex[:12]
        reason = f"Observer '{spec.name}' requests approval to run '{req.skill}'"
        context = {
            "task": req.task,
            "evidence": req.evidence,
            "observer": spec.name,
            "trigger": req.context.get("rule") if isinstance(req.context, dict) else None,
        }
        # Store the deferred action so resolve() can run the skill on approval.
        deferred = {
            "observer_deferred": {
                "skill": req.skill, "task": req.task,
                "tenant_id": spec.tenant_id, "agent_id": spec.agent_id,
                "user_id": spec.user_id,
            }
        }
        try:
            approval_req = ApprovalRequest(
                id=approval_id,
                tenant_id=spec.tenant_id,
                user_id=spec.user_id,
                skill=req.skill,
                reason=reason,
                context=context,
                options=["Approve", "Reject"],
                urgency="high",
                rule_matched=context.get("trigger"),
                rule_type="observer_hook",
                sla_minutes=30,
                source="observer",
            )
            ok = await approval_store.create_approval(approval_req, agent_state=deferred)
            if not ok:
                logger.warning("approval_store.create_approval returned falsy (Redis down?)")
        except Exception as exc:
            logger.error("Failed to create gateway approval: %s", exc)
            return ActResponse(status="denied", message=f"approval store error: {exc}")

        # Live-update the dashboard.
        try:
            await dashboard.broadcast({
                "type": "hitl_approval_new",
                "approval_id": approval_id,
                "user_id": spec.user_id,
                "skill": req.skill,
                "reason": reason,
                "urgency": "high",
                "context": context,
                "sla_minutes": 30,
                "source": "observer",
            })
        except Exception:
            pass

        logger.info("Observer '%s' HOOK -> HITL approval %s created for skill '%s'",
                    spec.name, approval_id, req.skill)
        return ActResponse(status="pending_approval", approval_id=approval_id,
                           message=reason)

    async def resolve(self, approval_id: str, decision: str,
                      decided_by: str = "observer-admin", note: str = "") -> ActResponse:
        """Resolve an observer approval; on approve, run the deferred skill."""
        from shared.state import (
            approval_store, state, queue_manager, QueueNames,
        )

        appr = await approval_store.get_approval(approval_id)
        if not appr:
            return ActResponse(status="denied", message="approval not found")

        try:
            _resolved, decided_now = await approval_store.claim_resolution(
                approval_id, decision, decided_by, note
            )
        except Exception as exc:
            logger.error("claim_resolution failed: %s", exc)
            return ActResponse(status="denied", message="could not record the decision")
        if not decided_now:
            # Already decided (a repeat click or a concurrent request): never re-run the skill.
            return ActResponse(
                status="denied",
                message=f"approval already {getattr(_resolved, 'status', 'resolved')}",
            )

        if decision.lower() not in ("approved", "approve"):
            logger.info("Observer approval %s REJECTED by %s", approval_id, decided_by)
            # Quick Win 'A': record the rejected outcome so the UI shows it clearly.
            try:
                await approval_store.annotate_outcome(approval_id, execution_status="rejected")
            except Exception:
                pass
            return ActResponse(status="rejected",
                               message=f"Action rejected by {decided_by}")

        # Approved — load + run the deferred action.
        try:
            await approval_store.annotate_outcome(approval_id, execution_status="executing")
        except Exception:
            pass
        raw = await approval_store.get_agent_state(approval_id)
        data: Any = raw
        if isinstance(raw, str):
            try:
                data = json.loads(raw)
            except Exception:
                data = {}
        deferred = (data or {}).get("observer_deferred") if isinstance(data, dict) else None
        if not deferred:
            return ActResponse(status="approved",
                               message="Approved, but no deferred action was stored.")

        agent = state.get_or_create(deferred["tenant_id"], deferred["agent_id"],
                                    deferred["user_id"])
        # Force auto_run for this deferred action; restored in the finally.
        _prev_auto_run = getattr(agent, "auto_run", False)
        agent.auto_run = True
        agent._telemetry_entrypoint = "observer"
        _bind_observer_principal(agent, deferred["tenant_id"], deferred["user_id"])
        lane = QueueNames.session(deferred["tenant_id"], deferred["user_id"])
        try:
            response = await queue_manager.enqueue(
                lane,
                lambda: agent.run(deferred["task"], skill_name=deferred["skill"]),
                max_concurrent=1,
            )
        finally:
            agent.auto_run = _prev_auto_run
        try:
            await approval_store.delete_agent_state(approval_id)
        except Exception:
            pass
        # Quick Win 'A': persist the outcome + trace of the executed deferred skill.
        try:
            await approval_store.annotate_outcome(
                approval_id,
                execution_status="done",
                result_summary=str(response),
                trace_id=getattr(agent, "_active_trace_id", "") or "",
            )
        except Exception as exc:
            logger.warning("observer annotate_outcome failed: %s", exc)
        logger.info("Observer approval %s APPROVED by %s -> skill '%s' EXECUTED",
                    approval_id, decided_by, deferred["skill"])
        return ActResponse(status="executed", approval_id=approval_id,
                           message=str(response)[:2000])


# Singleton factory (mirrors get_observer_store / get_db).
_service: Optional[ObserverService] = None


def get_observer_service() -> ObserverService:
    global _service
    if _service is None:
        _service = ObserverService()
    return _service
