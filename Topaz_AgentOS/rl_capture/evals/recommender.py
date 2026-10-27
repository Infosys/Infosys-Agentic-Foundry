"""Framework-neutral model recommender for eval results."""

from __future__ import annotations

from collections import defaultdict
from typing import Any


def recommend_models(
    case_results: list[dict[str, Any]],
    *,
    role: str = "primary",
    cost_weight: float = 0.15,
    latency_weight: float = 0.10,
) -> dict[str, Any]:
    """Rank model targets using eval score, optional cost, and latency.

    Input rows are intentionally plain dicts so this module stays independent of
    Studio and any specific storage implementation.
    """
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in case_results:
        target_type = str(row.get("target_type") or "").lower()
        if target_type not in {"model_role", "model"}:
            continue
        model = str(row.get("target_name") or row.get("model") or "").strip()
        if model:
            grouped[model].append(row)

    candidates = []
    for model, rows in grouped.items():
        scores = [float(row.get("score") or 0.0) for row in rows]
        costs = [_float_meta(row, "cost_usd") for row in rows]
        latencies = [_float_meta(row, "latency_ms") for row in rows]
        avg_score = sum(scores) / len(scores) if scores else 0.0
        avg_cost = sum(costs) / len(costs) if costs else 0.0
        avg_latency = sum(latencies) / len(latencies) if latencies else 0.0
        rank_score = avg_score - (avg_cost * cost_weight) - ((avg_latency / 1000.0) * latency_weight)
        candidates.append({
            "role": role,
            "model": model,
            "cases": len(rows),
            "avg_eval_score": round(avg_score, 3),
            "avg_cost_usd": round(avg_cost, 6),
            "avg_latency_ms": round(avg_latency, 1),
            "rank_score": round(rank_score, 3),
        })

    candidates.sort(key=lambda item: item["rank_score"], reverse=True)
    return {
        "role": role,
        "recommendation": candidates[0] if candidates else None,
        "candidates": candidates,
        "advisory_only": True,
    }


def _float_meta(row: dict[str, Any], key: str) -> float:
    metadata = row.get("metadata") or {}
    if isinstance(metadata, dict):
        candidate = metadata.get("candidate") or {}
        value = metadata.get(key, candidate.get(key) if isinstance(candidate, dict) else None)
    else:
        value = None
    try:
        return float(value or 0.0)
    except (TypeError, ValueError):
        return 0.0
