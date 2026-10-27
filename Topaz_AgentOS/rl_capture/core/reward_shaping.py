"""Reward shaping for RFT / RL exports (Phase 3).

The raw ``reward_events`` stream mixes two very different kinds of signal:

* **Judgement** — genuine quality signal about *how good an answer was*:
  human thumbs/approval/edits, LLM-judge / verifier / critique / shadow-eval
  results, and business-outcome signals.
* **Operational** — process/plumbing traces that say *the machinery ran*, not
  whether the answer was good: policy `allow` decisions, hook `ok` outcomes,
  queue transitions, etc. These must **not** drive the RL reward or they teach
  the policy to optimise for "the pipeline didn't error".

This module classifies each channel, maps labels to scalar values, and folds
the judgement events into a single **bounded, confidence-weighted** reward in
``[-1, 1]`` with a transparent per-event component breakdown. Operational events
are counted but contribute zero weight.
"""

from __future__ import annotations

from typing import Any, Optional


# category -> weight applied to that channel's contribution.
CATEGORY_WEIGHTS: dict[str, float] = {
    "human": 1.0,       # strongest signal we have
    "judge": 0.7,       # LLM judge / verifier / critique / shadow eval
    "business": 0.6,    # business KPI / outcome
    "operational": 0.0, # process traces — excluded from the reward
}

CHANNEL_CATEGORY: dict[str, str] = {
    "human_approval": "human",
    "human_edit": "human",
    "thumbs": "human",
    "critique": "judge",
    "verifier": "judge",
    "evaluator": "judge",
    "shadow_eval": "judge",
    "business": "business",
    "hook": "operational",
    "model_call_policy": "operational",
    "queue": "operational",
    "operational": "operational",
    "workstream": "operational",
}


def classify_channel(channel: Optional[str]) -> str:
    """Return the shaping category for a reward channel (default operational)."""
    return CHANNEL_CATEGORY.get(str(channel or "").lower(), "operational")


def is_judgement_channel(channel: Optional[str]) -> bool:
    return classify_channel(channel) != "operational"


# Values live in [-1, 1]. "allow"/"ok" are intentionally absent: they are
# operational and must never read as positive quality.
DEFAULT_LABEL_VALUES: dict[str, float] = {
    "approve": 1.0, "up": 1.0, "success": 1.0, "complete": 1.0,
    "accept": 1.0, "accepted": 1.0, "candidate_wins": 1.0, "win": 1.0,
    "pass": 0.5, "partial": 0.25,
    "tie": 0.0, "neutral": 0.0,
    "fail": -1.0, "failed": -1.0, "reject": -1.0, "rejected": -1.0,
    "down": -1.0, "block": -1.0, "deny": -1.0, "dlq": -1.0,
    "error": -1.0, "baseline_wins": -1.0, "lose": -1.0,
}


def label_to_value(label: Optional[str], label_values: Optional[dict[str, float]] = None) -> Optional[float]:
    values = label_values or DEFAULT_LABEL_VALUES
    return values.get(str(label or "").lower())


def _event_value(reward: dict, label_values: Optional[dict[str, float]]) -> Optional[float]:
    """Prefer an explicit numeric ``raw_value`` (clipped), else map the label."""
    raw_value = reward.get("raw_value")
    if raw_value is not None:
        try:
            return max(-1.0, min(1.0, float(raw_value)))
        except (TypeError, ValueError):
            return None
    return label_to_value(reward.get("raw_label"), label_values)


def shape_trajectory_reward(
    reward_events: list[dict],
    *,
    category_weights: Optional[dict[str, float]] = None,
    label_values: Optional[dict[str, float]] = None,
    terminal_status: Optional[str] = None,
) -> dict:
    """Fold judgement reward events into one bounded scalar reward.

    Returns a dict with:
        reward            float in [-1, 1] or None when no judgement signal
        policy            shaping policy version tag
        components        per-event breakdown (channel/category/value/weight/…)
        n_judgement       number of judgement events that contributed
        n_operational     number of operational events (excluded)
        by_category       summed effective weight per category
        terminal_status   echoed for downstream fallback logic
    """
    weights = category_weights or CATEGORY_WEIGHTS
    components: list[dict[str, Any]] = []
    weighted_sum = 0.0
    weight_total = 0.0
    n_judgement = 0
    n_operational = 0
    by_category: dict[str, float] = {}

    for reward in reward_events:
        channel = reward.get("channel")
        category = classify_channel(channel)
        weight = float(weights.get(category, 0.0))
        value = _event_value(reward, label_values)

        if category == "operational":
            n_operational += 1
        if value is None or weight <= 0.0:
            # Unmapped label or zero-weight (operational) event: recorded only.
            if value is not None:
                components.append({
                    "channel": channel, "category": category, "label": reward.get("raw_label"),
                    "value": value, "weight": weight, "confidence": reward.get("confidence"),
                    "contribution": 0.0, "included": False,
                })
            continue

        confidence = reward.get("confidence")
        try:
            conf = 1.0 if confidence is None else max(0.0, min(1.0, float(confidence)))
        except (TypeError, ValueError):
            conf = 1.0
        effective_weight = weight * conf
        if effective_weight <= 0.0:
            continue

        contribution = value * effective_weight
        weighted_sum += contribution
        weight_total += effective_weight
        by_category[category] = by_category.get(category, 0.0) + effective_weight
        n_judgement += 1
        components.append({
            "channel": channel, "category": category, "label": reward.get("raw_label"),
            "value": round(value, 6), "weight": weight, "confidence": conf,
            "contribution": round(contribution, 6), "included": True,
        })

    reward: Optional[float] = None
    if weight_total > 0.0:
        # Round to avoid float artifacts (0.7999999999999999) that trip the Luhn card detector and block RFT export.
        reward = round(max(-1.0, min(1.0, weighted_sum / weight_total)), 6)

    return {
        "reward": reward,
        "policy": "rl_reward_shaping_v1",
        "components": components,
        "n_judgement": n_judgement,
        "n_operational": n_operational,
        "by_category": {key: round(val, 6) for key, val in by_category.items()},
        "terminal_status": terminal_status,
    }
