"""Distill Jev (teacher) labels onto the direct training split.

Runs the Jev API over the TRAIN split, relabels each record with Jev's
prediction where Jev is confident (a teacher correction), keeps the original
label otherwise, and stores Jev's full probability distribution per record so a
future soft-target trainer can use it. valid/test are copied unchanged as
ground truth.

The output dataset keeps the identical schema as the input, so the existing
trainer (``train_mlx train --routing-mode direct``) can train on it with no
changes (hard-label distillation). Soft-target (dark-knowledge) training that
consumes ``teacher_probabilities`` is a later enhancement.

Usage:

    /usr/local/bin/python3 -m model_training.finance_candidate_router.distill_jev \
        --data-dir enterprise_root/tenants/company/training_data/finance_router_direct_candidate_v1 \
        --out-dir  enterprise_root/tenants/company/training_data/finance_router_direct_candidate_v1_distilled \
        --confidence 0.6 [--limit N]
"""

from __future__ import annotations

import argparse
import json
import shutil
import time
from pathlib import Path
from typing import Any

from model_training.finance_candidate_router.eval_jev_direct import (
    call_jev,
    load_api_key,
    write_curl_auth_config,
)


def teacher_distribution(
    row: dict[str, Any], answer: dict[str, Any]
) -> tuple[list[str], list[float], str | None, float]:
    """Return (candidate values, normalized probs, teacher choice, confidence)."""
    values = [c["value"] for c in row["candidates"]]
    raw = answer.get("probabilities") or {}
    probs = [float(raw.get(value, 0.0)) for value in values]
    total = sum(probs)
    if total > 0:
        probs = [p / total for p in probs]
    choice = answer.get("choice")
    if choice not in values:
        choice = values[max(range(len(values)), key=lambda i: probs[i])] if values else None
    confidence = answer.get("confidence")
    if confidence is None and values:
        confidence = max(probs)
    return values, probs, choice, float(confidence or 0.0)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, required=True)
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--split", default="train", help="split to relabel (valid/test copied unchanged)")
    parser.add_argument("--model", default="jev-latest")
    parser.add_argument("--confidence", type=float, default=0.6)
    parser.add_argument("--limit", type=int, default=0)
    args = parser.parse_args()

    src, out = args.data_dir, args.out_dir
    out.mkdir(parents=True, exist_ok=True)
    key = load_api_key()

    rows = [
        json.loads(line)
        for line in (src / f"{args.split}.jsonl").read_text().splitlines()
        if line.strip()
    ]
    if args.limit:
        rows = rows[: args.limit]

    relabeled = agree = kept_low_conf = 0
    started = time.perf_counter()
    out_rows = []
    # call_jev takes the owner-only curl config holding the auth header, never the
    # key itself (which curl would treat as a filename and expose in argv).
    auth_config = write_curl_auth_config(key)
    try:
        for index, row in enumerate(rows, start=1):
            answer = call_jev(auth_config, args.model, row)
            values, probs, choice, confidence = teacher_distribution(row, answer)
            original = row["target"]
            row = dict(row)
            row["original_target"] = original
            row["teacher_choice"] = choice
            row["teacher_confidence"] = confidence
            row["teacher_probabilities"] = {value: prob for value, prob in zip(values, probs)}
            if confidence >= args.confidence and choice in values:
                row["target"] = choice
            else:
                kept_low_conf += 1
            if choice == original:
                agree += 1
            if row["target"] != original:
                relabeled += 1
            out_rows.append(row)
            mark = "==" if choice == original else "!="
            print(
                f"[{index}/{len(rows)}] {mark} orig={original} teacher={choice} "
                f"conf={confidence:.2f} target={row['target']}",
                flush=True,
            )
    finally:
        auth_config.unlink(missing_ok=True)

    with (out / f"{args.split}.jsonl").open("w") as handle:
        for row in out_rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")

    # Copy the untouched splits + catalog so eval stays on ground-truth data.
    for name in ("train", "valid", "test"):
        if name == args.split:
            continue
        source_file = src / f"{name}.jsonl"
        if source_file.exists():
            shutil.copyfile(source_file, out / f"{name}.jsonl")
    if (src / "catalog.json").exists():
        shutil.copyfile(src / "catalog.json", out / "catalog.json")

    manifest = {
        "dataset": out.name,
        "method": "jev_teacher_distillation",
        "source": str(src),
        "relabeled_split": args.split,
        "jev_model": args.model,
        "confidence_threshold": args.confidence,
        "splits": {args.split: {"records": len(rows)}},
        "counts": {
            "records": len(rows),
            "teacher_agrees_with_original": agree,
            "relabeled_by_teacher": relabeled,
            "kept_original_low_confidence": kept_low_conf,
        },
        "elapsed_seconds": time.perf_counter() - started,
        "note": (
            "target uses Jev's confident prediction; teacher_probabilities stored "
            "for future soft-target training; valid/test unchanged."
        ),
    }
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print(
        f"\nteacher agrees with original on {agree}/{len(rows)}; "
        f"relabeled {relabeled}; kept-original(low-conf) {kept_low_conf}"
    )
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
