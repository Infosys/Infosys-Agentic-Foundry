"""Rejection-SFT exporter scaffolding."""

from __future__ import annotations

from typing import Iterable

from rl_capture.core.resolver import TargetResolver

from .kto import DEFAULT_DESIRABLE, DEFAULT_UNDESIRABLE


def materialize_rejection_sft_rows(reward_events: Iterable[dict]) -> list[dict]:
    rows: list[dict] = []
    for reward in reward_events:
        label = str(reward.get("raw_label") or "").lower()
        if label in DEFAULT_DESIRABLE:
            bucket = "accepted"
        elif label in DEFAULT_UNDESIRABLE:
            bucket = "rejected"
        else:
            continue
        rows.append({
            "bucket": bucket,
            "target": reward.get("target"),
            "metadata": {
                "reward_event_id": reward.get("id"),
                "channel": reward.get("channel"),
                "raw_label": reward.get("raw_label"),
            },
        })
    return rows


def materialize_rejection_sft_rows_from_targets(
    reward_events: Iterable[dict],
    target_resolver: TargetResolver,
) -> list[dict]:
    rows: list[dict] = []
    for row in materialize_rejection_sft_rows(reward_events):
        resolved = target_resolver.resolve(row.get("target") or {})
        if not resolved or not resolved.text:
            continue
        rows.append({
            "bucket": row["bucket"],
            "text": resolved.text,
            "messages": resolved.messages,
            "metadata": {**row.get("metadata", {}), **resolved.metadata},
        })
    return rows
