"""KTO exporter scaffolding for single-sample binary judgments."""

from __future__ import annotations

from typing import Iterable

from rl_capture.core.resolver import TargetResolver


DEFAULT_DESIRABLE = {"approve", "up", "pass", "success", "complete", "candidate_wins"}
DEFAULT_UNDESIRABLE = {"reject", "down", "block", "failed", "dlq", "baseline_wins"}


def materialize_kto_rows(reward_events: Iterable[dict]) -> list[dict]:
    rows: list[dict] = []
    for reward in reward_events:
        label = str(reward.get("raw_label") or "").lower()
        if label in DEFAULT_DESIRABLE:
            desirable = True
        elif label in DEFAULT_UNDESIRABLE:
            desirable = False
        else:
            continue
        rows.append({
            "target": reward.get("target"),
            "desirable": desirable,
            "metadata": {
                "reward_event_id": reward.get("id"),
                "channel": reward.get("channel"),
                "raw_label": reward.get("raw_label"),
            },
        })
    return rows


def materialize_kto_rows_from_targets(
    reward_events: Iterable[dict],
    target_resolver: TargetResolver,
) -> list[dict]:
    rows: list[dict] = []
    for reward in materialize_kto_rows(reward_events):
        resolved = target_resolver.resolve(reward.get("target") or {})
        if not resolved or not resolved.text:
            continue
        rows.append({
            "text": resolved.text,
            "messages": resolved.messages,
            "desirable": reward["desirable"],
            "metadata": {**reward.get("metadata", {}), **resolved.metadata},
        })
    return rows
