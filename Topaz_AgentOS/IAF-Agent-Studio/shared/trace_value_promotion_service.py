"""Governed bulk promotion for Trace Value Router recommendations."""

from __future__ import annotations

from typing import Any

from shared.config import AGENT_ID, TENANT_ID
from shared import evals_service
from shared.trace_value_service import record_route_decision, store_for_tenant


KNOWLEDGE_DESTINATIONS = {"skill", "context", "memory"}


def promote(
    *,
    tenant_id: str = TENANT_ID,
    agent_id: str = AGENT_ID,
    reviewer: str,
    items: list[dict[str, Any]],
) -> dict[str, Any]:
    results: list[dict[str, Any]] = []
    for item in items:
        trajectory_id = str(item.get("trajectory_id") or "").strip()
        destination = str(item.get("destination") or "").strip()
        action = str(item.get("action") or "approve").strip() or "approve"
        if not trajectory_id or not destination:
            results.append({"status": "error", "error": "trajectory_id and destination are required", "item": item})
            continue
        try:
            if destination == "golden_eval":
                result = _promote_golden(tenant_id=tenant_id, trajectory_id=trajectory_id, item=item)
                target_ref = str(result.get("case", {}).get("id") or item.get("golden_set") or "")
                status = "promoted"
            elif destination in KNOWLEDGE_DESTINATIONS:
                result = _create_pending_knowledge(
                    tenant_id=tenant_id,
                    agent_id=agent_id,
                    trajectory_id=trajectory_id,
                    destination=destination,
                    item=item,
                )
                target_ref = str(result.get("knowledge_id") or "")
                status = "pending_review"
            elif destination == "model_training":
                result = {"training_pool": item.get("training_pool") or "default", "approved": True}
                target_ref = str(result["training_pool"])
                status = "approved"
            elif destination == "debug_only":
                result = {"archived": True}
                target_ref = "debug_only"
                status = "archived"
            else:
                raise ValueError(f"unsupported destination: {destination}")
            decision = record_route_decision(
                tenant_id=tenant_id,
                trajectory_id=trajectory_id,
                destination=destination,
                action=action,
                status=status,
                reviewer=reviewer,
                target_ref=target_ref,
                reason=str(item.get("reason") or ""),
                metadata={"promotion_result": result, "source": "trace_value_bulk_promote"},
            )
            results.append({"status": status, "trajectory_id": trajectory_id, "destination": destination, "decision": decision, "result": result})
        except Exception as exc:  # noqa: BLE001 - return per-row failure
            results.append({"status": "error", "trajectory_id": trajectory_id, "destination": destination, "error": str(exc)})
    return {
        "tenant_id": tenant_id,
        "total": len(results),
        "succeeded": sum(1 for row in results if row.get("status") != "error"),
        "failed": sum(1 for row in results if row.get("status") == "error"),
        "results": results,
    }


def _promote_golden(*, tenant_id: str, trajectory_id: str, item: dict[str, Any]) -> dict[str, Any]:
    golden_set = str(item.get("golden_set") or item.get("target_ref") or "").strip()
    if not golden_set:
        raise ValueError("golden_eval promotion requires golden_set")
    return evals_service.promote_trajectory_to_golden(
        golden_set,
        trajectory_id=trajectory_id,
        tenant_id=tenant_id,
        case_id=str(item.get("case_id") or ""),
        assertions=item.get("assertions") or [],
        tags=["trace_value_router", "bulk_promoted", *list(item.get("tags") or [])],
        metadata={"source": "trace_value_router", "reason": item.get("reason") or ""},
    )


def _create_pending_knowledge(
    *,
    tenant_id: str,
    agent_id: str,
    trajectory_id: str,
    destination: str,
    item: dict[str, Any],
) -> dict[str, Any]:
    assessment = store_for_tenant(tenant_id).latest_trace_value_assessment(trajectory_id)
    if not assessment:
        raise ValueError("trajectory has no trace value assessment")
    summary = str(item.get("summary") or assessment.get("learning") or "").strip()
    if not summary:
        raise ValueError("knowledge promotion requires extracted learning or summary")
    from shared.state import state

    user_id = str(item.get("user_id") or "trace_value_router")
    agent = state.get_or_create(tenant_id, agent_id, user_id, user_role="admin")
    skill = str(item.get("skill") or ((assessment.get("metadata") or {}).get("skill") or "")) or None
    knowledge_type = "preference" if destination == "memory" else "rule"
    knowledge_id = agent.memory.write_knowledge(
        knowledge_type=knowledge_type,
        summary=summary,
        skill=skill,
        tags=["trace_value_router", destination, "pending_review"],
        applies_when=str(item.get("applies_when") or (assessment.get("rationale") or {}).get(destination) or ""),
        source="trace_value_router",
        status="pending_review",
        episode_id=None,
        entity_keys=item.get("entity_keys") or [],
        source_context_file=item.get("source_context_file") or None,
    )
    return {"knowledge_id": knowledge_id, "status": "pending_review"}
