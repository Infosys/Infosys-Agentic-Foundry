"""Build the direct 49-finance-skill-plus-no-match candidate dataset."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from model_training.finance_candidate_router.build_dataset import (
    DEFAULT_SOURCE,
    PACKAGE_ROOT,
    REPO_ROOT,
    file_sha256,
    load_json,
    load_jsonl,
    repo_relative_str,
    validate_hierarchy,
)
from model_training.finance_candidate_router.common import (
    assert_family_separation,
    canonical_json,
    sha256_json,
    write_jsonl,
)
from model_training.finance_candidate_router.direct_common import DIRECT_CANDIDATE_CODES


DEFAULT_DIRECT_OUTPUT = (
    REPO_ROOT
    / "enterprise_root/tenants/company/training_data/finance_router_direct_candidate_v1"
)


def direct_candidates(
    catalog: dict[str, Any], hierarchy: dict[str, Any]
) -> list[dict[str, str]]:
    candidates = [
        {"value": skill, "description": description}
        for skill, description in catalog["skills"].items()
    ]
    candidates.append(dict(hierarchy["no_match"]))
    if len(candidates) != 50:
        raise ValueError(f"Expected 49 skills plus no-match, got {len(candidates)} candidates")
    return candidates


def direct_row(
    *,
    source_id: str,
    family: str,
    split: str,
    context: str,
    target: str,
    candidates: list[dict[str, str]],
    metadata: dict[str, Any],
    skill_to_domain: dict[str, str],
) -> dict[str, Any]:
    target_domain = "no-match" if target == "no-match" else skill_to_domain[target]
    return {
        "id": f"{source_id}::direct",
        "split": split,
        "family": family,
        "stage": "direct",
        "context": context,
        "question": (
            "Which finance skill should handle this request? "
            "Choose no-match when none applies."
        ),
        "candidates": candidates,
        "target": target,
        "metadata": {
            **metadata,
            "source_id": source_id,
            "target_skill": None if target == "no-match" else target,
            "target_domain": target_domain,
            "synthetic": True,
            "human_reviewed": False,
        },
    }


def validate_direct_rows(rows: list[dict[str, Any]], split: str) -> dict[str, Any]:
    if not rows:
        raise ValueError(f"{split}: dataset is empty")
    ids: set[str] = set()
    for row in rows:
        if row["id"] in ids:
            raise ValueError(f"{split}: duplicate id {row['id']}")
        ids.add(row["id"])
        if row["split"] != split or row["stage"] != "direct":
            raise ValueError(f"{row['id']}: invalid split or stage")
        values = [item["value"] for item in row["candidates"]]
        if len(values) != 50 or len(values) != len(set(values)):
            raise ValueError(f"{row['id']}: expected 50 unique candidates")
        if row["target"] not in values:
            raise ValueError(f"{row['id']}: target absent from candidates")
        if any(not item.get("description", "").strip() for item in row["candidates"]):
            raise ValueError(f"{row['id']}: empty candidate description")
    return {
        "records": len(rows),
        "families": len({row["family"] for row in rows}),
        "stage_counts": {"direct": len(rows)},
        "target_counts": dict(
            sorted(
                (target, sum(row["target"] == target for row in rows))
                for target in {row["target"] for row in rows}
            )
        ),
        "sha256": sha256_json(rows),
    }


def build_direct(source_dir: Path, output_dir: Path) -> dict[str, Any]:
    catalog = load_json(source_dir / "catalog.json")
    hierarchy_path = PACKAGE_ROOT / "hierarchy.json"
    contrastive_path = PACKAGE_ROOT / "contrastive_pairs.json"
    no_match_path = PACKAGE_ROOT / "no_match_examples.json"
    hierarchy = load_json(hierarchy_path)
    contrastive = load_json(contrastive_path)
    no_match = load_json(no_match_path)
    skill_to_domain = validate_hierarchy(catalog, hierarchy)
    candidates = direct_candidates(catalog, hierarchy)
    splits: dict[str, list[dict[str, Any]]] = {"train": [], "valid": [], "test": []}

    for filename, split in {
        "train.jsonl": "train",
        "calibration.jsonl": "valid",
        "test.jsonl": "test",
    }.items():
        for source in load_jsonl(source_dir / filename):
            source_id = f"base::{source['id']}"
            splits[split].append(
                direct_row(
                    source_id=source_id,
                    family=source_id,
                    split=split,
                    context=source["state"]["user_message"],
                    target=source["target"],
                    candidates=candidates,
                    metadata={
                        "origin": "finance_router_synthetic_v1",
                        "original_id": source["id"],
                    },
                    skill_to_domain=skill_to_domain,
                )
            )

    for pair in contrastive["pairs"]:
        for variant_index, (left_context, right_context) in enumerate(
            pair["variants"], start=1
        ):
            family = f"contrastive::{pair['id']}::{variant_index:02d}"
            for role, context, target in (
                ("left", left_context, pair["left_skill"]),
                ("right", right_context, pair["right_skill"]),
            ):
                source_id = f"{family}::{role}"
                splits["train"].append(
                    direct_row(
                        source_id=source_id,
                        family=family,
                        split="train",
                        context=context,
                        target=target,
                        candidates=candidates,
                        metadata={
                            "origin": contrastive["version"],
                            "contrastive_pair": pair["id"],
                            "contrastive_role": role,
                            "variant_index": variant_index,
                        },
                        skill_to_domain=skill_to_domain,
                    )
                )

    for index, context in enumerate(no_match["examples"], start=1):
        source_id = f"no-match::{index:03d}"
        splits["train"].append(
            direct_row(
                source_id=source_id,
                family=source_id,
                split="train",
                context=context,
                target="no-match",
                candidates=candidates,
                metadata={"origin": no_match["version"]},
                skill_to_domain=skill_to_domain,
            )
        )

    reports = {name: validate_direct_rows(rows, name) for name, rows in splits.items()}
    assert_family_separation(splits)
    output_dir.mkdir(parents=True, exist_ok=True)
    for name, rows in splits.items():
        write_jsonl(output_dir / f"{name}.jsonl", rows)
    (output_dir / "catalog.json").write_text(canonical_json(catalog) + "\n", encoding="utf-8")
    manifest = {
        "dataset": "finance_router_direct_candidate_v1",
        "method": "direct_50_choice_candidate_logit_sft",
        "stages": ["direct"],
        "candidate_codes": "A-Z, 0-9, a-n; assigned after deterministic per-record shuffling",
        "candidate_code_count": len(DIRECT_CANDIDATE_CODES[:50]),
        "shuffle_seed": 17,
        "target_in_prompt": False,
        "loss": "cross_entropy_over_allowed_candidate_logits_at_final_prompt_position",
        "source_catalog": repo_relative_str(source_dir / "catalog.json"),
        "hierarchy_sha256": file_sha256(hierarchy_path),
        "contrastive_spec_sha256": file_sha256(contrastive_path),
        "no_match_spec_sha256": file_sha256(no_match_path),
        "catalog_sha256": sha256_json(catalog),
        "splits": reports,
        "limitations": [
            "All examples are synthetic and have not been reviewed by finance subject-matter experts.",
            "Every prompt contains all 49 skills plus no-match and is materially longer than hierarchical prompts.",
            "The final test split must not be used for checkpoint or hyperparameter selection.",
        ],
    }
    (output_dir / "manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-dir", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_DIRECT_OUTPUT)
    args = parser.parse_args()
    manifest = build_direct(args.source_dir.resolve(), args.output_dir.resolve())
    print(json.dumps(manifest["splits"], indent=2))
    print(f"Wrote {args.output_dir.resolve()}")


if __name__ == "__main__":
    main()
