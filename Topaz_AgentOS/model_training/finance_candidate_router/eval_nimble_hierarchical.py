"""Evaluate Bespoke-Nimble-9B on the HIERARCHICAL finance-router split.

Nimble caps at 26 choices per field and rejects prompts > 2048 tokens, so the
direct 50-choice task does not fit; the hierarchical split (<=11 choices, short
prompts) does. Each decision is scored as a Nimble ``enum`` field, and results
are aggregated with the SAME metric math as the Jev/local harnesses (accuracy,
NLL, Brier, ECE, coverage, per-stage, and domain&skill end-to-end).

REQUIRES a CUDA GPU with BF16 (Nimble's reference runner). It CANNOT run on
Apple Silicon. Set up the local base-weight symlink first (see the runbook):

    BASE="$HOME/Downloads/rlm_demo/models/Qwen3.5-9B"
    REV="c202236235762e1c871ad0ccb60c8ee5ba337b9a"
    CACHE="$HOME/.cache/huggingface/hub/models--Qwen--Qwen3.5-9B/snapshots/$REV"
    mkdir -p "$(dirname "$CACHE")" && ln -sfn "$BASE" "$CACHE"

Run (on the CUDA machine, from the repo root):

    python3 -m model_training.finance_candidate_router.eval_nimble_hierarchical \
        --adapter-dir "$HOME/Downloads/rlm_demo/models/Bespoke-Nimble-9B" \
        --data-dir enterprise_root/tenants/company/training_data/finance_router_candidate_v1 \
        --split valid \
        --out artifacts/nimble_hierarchical_valid_report.json [--limit N]
"""

from __future__ import annotations

import argparse
import json
import math
import sys
import time
from pathlib import Path
from typing import Any

from model_training.finance_candidate_router.eval_jev_direct import aggregate


def build_schema(row: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    """One Nimble enum field over this decision's candidate values."""
    values = [c["value"] for c in row["candidates"]]
    descriptions = {c["value"]: c["description"] for c in row["candidates"]}
    schema = {
        "choice": {
            "type": "enum",
            "choices": values,
            "description": row["question"],
            "choice_descriptions": descriptions,
        }
    }
    return schema, values


def score_row(model: Any, row: dict[str, Any]) -> dict[str, Any]:
    """Score one decision with Nimble, matching the shared metric-record shape."""
    schema, values = build_schema(row)
    result = model.score(context=row["context"], schema=schema)
    field = result["fields"]["choice"]
    # choice_key is identity for string enums, so probabilities are keyed by value.
    prob_map = field.get("probabilities") or {}
    probs = [float(prob_map.get(value, 0.0)) for value in values]
    total = sum(probs)
    if total > 0:
        probs = [p / total for p in probs]
    gold = values.index(row["target"])
    prediction = field.get("prediction")
    if prediction in values:
        prediction_index = values.index(prediction)
    else:
        prediction_index = max(range(len(values)), key=lambda i: probs[i])
    ranked = sorted(probs, reverse=True)
    return {
        "id": row["id"],
        "stage": row["stage"],
        "source_id": row.get("metadata", {}).get("source_id"),
        "target": row["target"],
        "prediction": values[prediction_index],
        "correct": prediction_index == gold,
        "confidence": probs[prediction_index],
        "margin": ranked[0] - ranked[1] if len(ranked) > 1 else 1.0,
        "target_probability": probs[gold],
        "nll": -math.log(max(probs[gold], 1e-30)),
        "brier": sum((p - float(i == gold)) ** 2 for i, p in enumerate(probs)),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--adapter-dir", type=Path, required=True)
    parser.add_argument("--data-dir", type=Path, required=True)
    parser.add_argument("--split", default="valid")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--limit", type=int, default=0)
    args = parser.parse_args()

    # Nimble's runner imports parallel_schema relative to the adapter dir.
    sys.path.insert(0, str(args.adapter_dir))
    from inference import NimbleModel

    model = NimbleModel(str(args.adapter_dir))

    rows = [
        json.loads(line)
        for line in (args.data_dir / f"{args.split}.jsonl").read_text().splitlines()
        if line.strip()
    ]
    if args.limit:
        rows = rows[: args.limit]

    results = []
    started = time.perf_counter()
    for index, row in enumerate(rows, start=1):
        scored = score_row(model, row)
        results.append(scored)
        mark = "OK " if scored["correct"] else "XX "
        print(
            f"[{index}/{len(rows)}] {mark} {scored['stage']:<6} "
            f"target={scored['target']} pred={scored['prediction']} "
            f"conf={scored['confidence']:.3f}",
            flush=True,
        )

    report = aggregate(results)
    report["elapsed_seconds"] = time.perf_counter() - started
    report["model"] = "Bespoke-Nimble-9B"
    report["split"] = args.split
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2) + "\n")

    print("\n=== Nimble summary ===")
    print(
        f"per-decision acc={100 * report['accuracy']:.2f}%  nll={report['mean_nll']:.4f}  "
        f"brier={report['mean_brier']:.4f}  ECE={report['expected_calibration_error']:.4f}"
    )
    for stage, stats in report["stages"].items():
        print(f"  {stage:<7} acc={100 * stats['accuracy']:.2f}% ({stats['correct']}/{stats['records']})")
    e2e = report["end_to_end"]
    if e2e["accuracy"] is not None:
        print(f"end-to-end (domain&skill): {100 * e2e['accuracy']:.2f}% ({e2e['correct']}/{e2e['records']})")
    print("thr  coverage  acc_within_covered")
    for threshold, stats in report["coverage_at_confidence"].items():
        acc = f"{100 * stats['accuracy']:.1f}%" if stats["accuracy"] is not None else "n/a"
        print(f"{threshold:>4}  {100 * stats['coverage']:5.1f}% ({stats['records']})   {acc}")
    print(f"\nwrote {args.out}")


if __name__ == "__main__":
    main()
