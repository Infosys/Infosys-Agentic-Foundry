"""DPO exporter scaffolding.

The core stores PreferenceSignal references, not materialized DPO rows. This
stub intentionally requires a resolver so export-time policy decides how to turn
references into prompt/chosen/rejected text.
"""

from __future__ import annotations

from typing import Callable, Iterable

from rl_capture.core.resolver import TargetResolver


def materialize_dpo_rows(preference_signals: Iterable[dict], resolver: Callable[[dict], dict]) -> list[dict]:
    rows: list[dict] = []
    for signal in preference_signals:
        row = resolver(signal)
        if {"prompt", "chosen", "rejected"}.issubset(row) and str(row["chosen"]).strip() != str(row["rejected"]).strip():
            rows.append({
                "prompt": row["prompt"],
                "chosen": row["chosen"],
                "rejected": row["rejected"],
                "metadata": row.get("metadata", {"preference_signal_id": signal.get("id")}),
            })
    return rows


def materialize_dpo_rows_from_targets(
    preference_signals: Iterable[dict],
    target_resolver: TargetResolver,
) -> list[dict]:
    rows: list[dict] = []
    for signal in preference_signals:
        prompt = target_resolver.prompt_for_context(signal.get("context_ref") or {})
        preferred = target_resolver.resolve(signal.get("preferred_ref") or {})
        dispreferred = target_resolver.resolve(signal.get("dispreferred_ref") or {})
        if not prompt or preferred is None or dispreferred is None:
            continue
        if not preferred.text or not dispreferred.text:
            continue
        if preferred.text.strip() == dispreferred.text.strip():
            # Degenerate pair (both sides resolved to the same text) carries no
            # preference signal and would poison DPO/ORPO/IPO training.
            continue
        rows.append({
            "prompt": prompt,
            "chosen": preferred.text,
            "rejected": dispreferred.text,
            "metadata": {
                "preference_signal_id": signal.get("id"),
                "channel": signal.get("channel"),
                "provenance": signal.get("provenance"),
            },
        })
    return rows
