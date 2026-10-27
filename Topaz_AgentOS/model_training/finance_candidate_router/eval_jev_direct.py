"""Evaluate the Jev (TypeSafe System One) API on the direct finance-router split.

Runs the SAME validation records the local LoRA model was scored on, sends each
as a 50-way choice to the Jev API, and scores the responses with the same metric
definitions as ``train_mlx.evaluate_accuracy`` so the two are directly
comparable.

The comparison is "as idiomatically used": the local model chooses among
shuffled one-character codes it was trained on, while Jev chooses among the
semantic candidate value keys (its native contract). Both see the same request
text and the same candidate descriptions.

Usage (from repo root, normal Terminal):

    export TYPESAFE_API_KEY=...   # or it is read from agent_os/config.env
    python3 -m model_training.finance_candidate_router.eval_jev_direct \
        --data-dir enterprise_root/tenants/company/training_data/finance_router_direct_candidate_v1 \
        --split valid \
        --out artifacts/jev_direct_valid_report.json \
        --limit 2      # omit --limit for the full split
"""

from __future__ import annotations

import argparse
import json
import math
import os
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any

API_URL = "https://api.typesafe.ai/v1/systemone"
COVERAGE_THRESHOLDS = (0.5, 0.6, 0.7, 0.8, 0.9, 0.95)


def load_api_key() -> str:
    """Return the TypeSafe API key from the environment or agent_os/config.env."""
    key = os.environ.get("TYPESAFE_API_KEY", "").strip()
    if key:
        return key
    config = Path("agent_os/config.env")
    if config.exists():
        for line in config.read_text().splitlines():
            line = line.strip()
            if line.startswith("TYPESAFE_API_KEY=") and not line.startswith("#"):
                return line.split("=", 1)[1].strip()
    raise SystemExit("TYPESAFE_API_KEY not found in environment or agent_os/config.env")


def write_curl_auth_config(key: str) -> Path:
    """Write the Authorization header to an owner-only curl config file.

    The key must never appear in curl's argv: on macOS and other Unix systems
    process listings expose command arguments to other users, leaking the
    credential on every request. A ``--config`` file (created 0600 by mkstemp)
    keeps it off the command line.
    """
    fd, name = tempfile.mkstemp(prefix="jev_curl_auth_", suffix=".cfg")
    os.close(fd)
    path = Path(name)
    # Escape backslashes and quotes for curl's config quoting rules.
    escaped = key.replace("\\", "\\\\").replace('"', '\\"')
    path.write_text(f'header = "Authorization: Bearer {escaped}"\n', encoding="utf-8")
    return path


def read_split(data_dir: Path, split: str) -> list[dict[str, Any]]:
    path = data_dir / f"{split}.jsonl"
    rows = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
    if not rows:
        raise SystemExit(f"no records in {path}")
    return rows


def call_jev(auth_config: Path, model: str, row: dict[str, Any], *, retries: int = 3) -> dict[str, Any]:
    """Send one record as a 50-way choice and return the parsed answer object.

    Uses curl rather than urllib because the corporate proxy injects a CA that
    Python's cert bundle rejects; curl trusts the macOS system keychain. The
    Authorization header is supplied via ``auth_config`` (a ``--config`` file) so
    the API key never appears in curl's argv.
    """
    criteria = {c["value"]: c["description"] for c in row["candidates"]}
    body = {
        "model": model,
        "state": {"request": row["context"]},
        "questions": {
            "skill": {
                "type": "choice",
                "criteria": criteria,
                "instructions": {"goal": row["question"]},
            }
        },
    }
    payload = json.dumps(body).encode("utf-8")
    command = [
        "curl", "-sS", "--max-time", "30", "-X", "POST", API_URL,
        "--config", str(auth_config),
        "-H", "Content-Type: application/json",
        "--data-binary", "@-",
    ]
    for attempt in range(retries):
        proc = subprocess.run(command, input=payload, capture_output=True)
        if proc.returncode == 0 and proc.stdout:
            try:
                parsed = json.loads(proc.stdout.decode("utf-8"))
            except json.JSONDecodeError:
                if attempt < retries - 1:
                    time.sleep(0.5 * 2**attempt)
                    continue
                raise RuntimeError(f"non-JSON response: {proc.stdout[:200]!r}")
            if "answers" in parsed:
                return parsed["answers"]["skill"]
            if attempt < retries - 1:
                time.sleep(0.5 * 2**attempt)
                continue
            raise RuntimeError(f"Jev error: {json.dumps(parsed)[:300]}")
        if attempt < retries - 1:
            time.sleep(0.5 * 2**attempt)
            continue
        raise RuntimeError(f"curl failed rc={proc.returncode}: {proc.stderr.decode()[:200]}")
    raise RuntimeError("Jev API unavailable after retries")


def score_record(row: dict[str, Any], answer: dict[str, Any]) -> dict[str, Any]:
    """Score one Jev answer with the same math as train_mlx.evaluate_accuracy."""
    values = [c["value"] for c in row["candidates"]]
    raw = answer.get("probabilities") or {}
    # Map probabilities onto the full candidate set; missing keys get 0.
    probs = [float(raw.get(value, 0.0)) for value in values]
    total = sum(probs)
    if total > 0:
        probs = [p / total for p in probs]  # renormalize so Brier/NLL match a distribution
    gold = values.index(row["target"])
    prediction_index = max(range(len(values)), key=lambda i: probs[i])
    ranked = sorted(probs, reverse=True)
    nll = -math.log(max(probs[gold], 1e-30))
    brier = sum((p - float(i == gold)) ** 2 for i, p in enumerate(probs))
    return {
        "id": row["id"],
        "stage": row["stage"],
        "source_id": row.get("metadata", {}).get("source_id"),
        "target": row["target"],
        "prediction": values[prediction_index],
        "jev_choice": answer.get("choice"),
        "jev_confidence": answer.get("confidence"),
        "correct": prediction_index == gold,
        "confidence": probs[prediction_index],
        "margin": ranked[0] - ranked[1] if len(ranked) > 1 else 1.0,
        "target_probability": probs[gold],
        "nll": nll,
        "brier": brier,
        "returned_prob_mass": total,
        "returned_key_count": len(raw),
    }


def aggregate(results: list[dict[str, Any]]) -> dict[str, Any]:
    n = len(results)
    calibration_bins = []
    for lower_index in range(10):
        lower, upper = lower_index / 10, (lower_index + 1) / 10
        selected = [
            r for r in results
            if lower <= r["confidence"] < upper or (upper == 1.0 and r["confidence"] == 1.0)
        ]
        if not selected:
            continue
        accuracy = sum(r["correct"] for r in selected) / len(selected)
        mean_conf = sum(r["confidence"] for r in selected) / len(selected)
        calibration_bins.append({"records": len(selected), "absolute_gap": abs(accuracy - mean_conf)})
    ece = sum(b["records"] * b["absolute_gap"] for b in calibration_bins) / n
    coverage = {}
    for threshold in COVERAGE_THRESHOLDS:
        selected = [r for r in results if r["confidence"] >= threshold]
        coverage[str(threshold)] = {
            "records": len(selected),
            "coverage": len(selected) / n,
            "accuracy": (sum(r["correct"] for r in selected) / len(selected)) if selected else None,
        }
    confusion_counts: dict[tuple[str, str], int] = {}
    for r in results:
        if not r["correct"]:
            confusion_counts[(r["target"], r["prediction"])] = confusion_counts.get((r["target"], r["prediction"]), 0) + 1
    confusions = [
        {"target": t, "prediction": p, "count": c}
        for (t, p), c in sorted(confusion_counts.items(), key=lambda kv: (-kv[1], kv[0]))
    ]
    stages: dict[str, Any] = {}
    for stage in sorted({r["stage"] for r in results}):
        selected = [r for r in results if r["stage"] == stage]
        stages[stage] = {
            "records": len(selected),
            "correct": sum(r["correct"] for r in selected),
            "accuracy": sum(r["correct"] for r in selected) / len(selected),
            "mean_nll": sum(r["nll"] for r in selected) / len(selected),
            "mean_brier": sum(r["brier"] for r in selected) / len(selected),
        }
    # Hierarchical end-to-end: a source is correct only if BOTH its domain and
    # skill decisions are correct. Empty/None for single-stage (direct) splits.
    paired: dict[str, list[dict[str, Any]]] = {}
    for r in results:
        if r.get("source_id"):
            paired.setdefault(r["source_id"], []).append(r)
    e2e_rows = [v for v in paired.values() if {x["stage"] for x in v} == {"domain", "skill"}]
    e2e_correct = sum(all(x["correct"] for x in v) for v in e2e_rows)
    end_to_end = {
        "records": len(e2e_rows),
        "correct": e2e_correct,
        "accuracy": (e2e_correct / len(e2e_rows)) if e2e_rows else None,
    }
    return {
        "records": n,
        "correct": sum(r["correct"] for r in results),
        "accuracy": sum(r["correct"] for r in results) / n,
        "mean_nll": sum(r["nll"] for r in results) / n,
        "mean_brier": sum(r["brier"] for r in results) / n,
        "expected_calibration_error": ece,
        "stages": stages,
        "end_to_end": end_to_end,
        "coverage_at_confidence": coverage,
        "confusions": confusions,
        "rows": results,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, required=True)
    parser.add_argument("--split", default="valid")
    parser.add_argument("--model", default="jev-latest")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--limit", type=int, default=0, help="score only the first N records (0 = all)")
    args = parser.parse_args()

    key = load_api_key()
    rows = read_split(args.data_dir, args.split)
    if args.limit:
        rows = rows[: args.limit]

    auth_config = write_curl_auth_config(key)
    results = []
    started = time.perf_counter()
    try:
        for index, row in enumerate(rows, start=1):
            answer = call_jev(auth_config, args.model, row)
            scored = score_record(row, answer)
            results.append(scored)
            mark = "OK " if scored["correct"] else "XX "
            print(
                f"[{index}/{len(rows)}] {mark} target={scored['target']} "
                f"pred={scored['prediction']} conf={scored['confidence']:.3f} "
                f"keys={scored['returned_key_count']} mass={scored['returned_prob_mass']:.3f}",
                flush=True,
            )
    finally:
        auth_config.unlink(missing_ok=True)

    report = aggregate(results)
    report["elapsed_seconds"] = time.perf_counter() - started
    report["model"] = args.model
    report["split"] = args.split
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2) + "\n")

    print("\n=== Jev summary ===")
    print(
        f"acc={100 * report['accuracy']:.2f}%  nll={report['mean_nll']:.4f}  "
        f"brier={report['mean_brier']:.4f}  ECE={report['expected_calibration_error']:.4f}"
    )
    e2e = report.get("end_to_end", {})
    if e2e.get("accuracy") is not None:
        print(f"end-to-end (domain&skill): {100 * e2e['accuracy']:.2f}% ({e2e['correct']}/{e2e['records']})")
    print("thr  coverage  acc_within_covered")
    for threshold, stats in report["coverage_at_confidence"].items():
        acc = f"{100 * stats['accuracy']:.1f}%" if stats["accuracy"] is not None else "n/a"
        print(f"{threshold:>4}  {100 * stats['coverage']:5.1f}% ({stats['records']})   {acc}")
    print(f"\nwrote {args.out}")


if __name__ == "__main__":
    main()
