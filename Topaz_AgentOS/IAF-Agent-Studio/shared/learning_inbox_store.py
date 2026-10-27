"""Read-only Learning Inbox aggregation."""

from __future__ import annotations

from typing import Any

from knowledge_dashboard_store import KnowledgeDashboardStore
from rl_capture.store.sqlite_store import get_rl_store
from shared.config import AGENT_ID, DATA_ROOT_PATH, RL_DB_PATH, TENANT_ID


def learning_inbox(
    *,
    tenant_id: str = TENANT_ID,
    agent_id: str = AGENT_ID,
    limit: int = 50,
) -> dict[str, Any]:
    """Aggregate reviewable learning signals without mutating memory."""
    memory_root = DATA_ROOT_PATH / "tenants" / tenant_id / "agents" / agent_id / "memory"
    knowledge_store = KnowledgeDashboardStore(memory_root)
    pending = knowledge_store.query_knowledge(
        status="pending_review",
        limit=limit,
        include_archived=False,
    ).get("items", [])
    knowledge_items = [_knowledge_item(row) for row in pending]
    rl_items = _rl_feedback_items(tenant_id=tenant_id, limit=limit)
    trace_value_items = _trace_value_items(tenant_id=tenant_id, limit=limit)
    signal_counts = _signal_counts(tenant_id=tenant_id, rl_items=rl_items, limit=limit)
    items = [*knowledge_items, *rl_items, *trace_value_items]
    items.sort(key=lambda row: str(row.get("created_at") or row.get("ts") or ""), reverse=True)
    return {
        "tenant_id": tenant_id,
        "agent_id": agent_id,
        "total": len(items[:limit]),
        "pending_knowledge": len(knowledge_items),
        "feedback_signals": len(rl_items),
        "trace_value_recommendations": len(trace_value_items),
        "signal_counts": {
            "pending_knowledge": len(knowledge_items),
            "trace_value_recommendations": len(trace_value_items),
            **signal_counts,
        },
        "attention": [
            {
                "key": "pending_knowledge",
                "label": "pending knowledge items",
                "count": len(knowledge_items),
                "action": "review_table",
            },
            {
                "key": "thumbs_down",
                "label": "thumbs-down responses",
                "count": signal_counts["thumbs_down"],
                "action": "view_signals",
            },
            {
                "key": "corrected_answers",
                "label": "corrected answers",
                "count": signal_counts["corrected_answers"],
                "action": "view_signals",
            },
            {
                "key": "eval_failures",
                "label": "eval failures",
                "count": signal_counts["eval_failures"],
                "action": "open_evals",
            },
            {
                "key": "trace_value_recommendations",
                "label": "trace value recommendations",
                "count": len(trace_value_items),
                "action": "route_trace",
            },
        ],
        "items": items[:limit],
    }


def _knowledge_item(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": row.get("id"),
        "kind": "knowledge",
        "status": row.get("status"),
        "source": row.get("source") or "",
        "summary": row.get("summary") or "",
        "knowledge_type": row.get("knowledge_type") or row.get("type") or "",
        "skill": row.get("skill") or "",
        "tags": row.get("tags") or [],
        "created_at": row.get("ts") or row.get("created_at") or "",
        "trajectory_id": row.get("trajectory_id") or (row.get("scope") or {}).get("trajectory_id") or "",
        "actionable": True,
        "record": row,
    }


def _rl_feedback_items(*, tenant_id: str, limit: int) -> list[dict[str, Any]]:
    try:
        store = get_rl_store(
            data_root=DATA_ROOT_PATH,
            tenant_id=tenant_id,
            db_path=RL_DB_PATH.strip() or None,
        )
        rewards = store.list_reward_events(limit=limit)
    except Exception:
        return []
    items: list[dict[str, Any]] = []
    for reward in rewards:
        channel = str(reward.get("channel") or "")
        label = str(reward.get("raw_label") or "")
        if channel not in {"thumbs", "human_edit", "human_approval"} and "correction" not in label.lower():
            continue
        target = reward.get("target") or {}
        items.append({
            "id": reward.get("id"),
            "kind": "feedback",
            "status": "captured",
            "source": channel,
            "summary": f"{channel}: {label}",
            "knowledge_type": "feedback",
            "skill": (reward.get("metadata") or {}).get("skill") or "",
            "tags": [channel],
            "created_at": reward.get("created_at") or "",
            "trajectory_id": target.get("trajectory_id") or "",
            "actionable": False,
            "record": reward,
        })
    return items


def _trace_value_items(*, tenant_id: str, limit: int) -> list[dict[str, Any]]:
    try:
        store = get_rl_store(
            data_root=DATA_ROOT_PATH,
            tenant_id=tenant_id,
            db_path=RL_DB_PATH.strip() or None,
        )
        assessments = store.list_trace_value_assessments(limit=limit)
    except Exception:
        return []
    items: list[dict[str, Any]] = []
    for row in assessments:
        destinations = row.get("destinations") or {}
        top = max(destinations.items(), key=lambda item: float(item[1] or 0))[0] if destinations else ""
        if top == "debug_only":
            continue
        items.append({
            "id": row.get("id"),
            "kind": "trace_value",
            "status": "recommended",
            "source": top,
            "summary": row.get("learning") or f"Trace recommended for {top}",
            "knowledge_type": "trace_value",
            "skill": ((row.get("metadata") or {}).get("skill") or ""),
            "tags": ["trace_value", top],
            "created_at": row.get("created_at") or "",
            "trajectory_id": row.get("trajectory_id") or "",
            "actionable": True,
            "record": row,
        })
    return items


def _signal_counts(*, tenant_id: str, rl_items: list[dict[str, Any]], limit: int) -> dict[str, int]:
    thumbs_down = sum(
        1
        for item in rl_items
        if item.get("source") == "thumbs"
        and str((item.get("record") or {}).get("raw_label") or "").lower() == "down"
    )
    corrected_answers = 0
    eval_failures = 0
    try:
        store = get_rl_store(
            data_root=DATA_ROOT_PATH,
            tenant_id=tenant_id,
            db_path=RL_DB_PATH.strip() or None,
        )
        corrected_answers = len(store.list_preference_signals(limit=limit))
        eval_failures = sum(
            1
            for reward in store.list_reward_events(limit=limit)
            if str(reward.get("channel") or "") in {"evaluator", "shadow_eval"}
            and str(reward.get("raw_label") or "").lower() == "fail"
        )
    except Exception:
        pass
    return {
        "thumbs_down": thumbs_down,
        "corrected_answers": corrected_answers,
        "eval_failures": eval_failures,
    }
