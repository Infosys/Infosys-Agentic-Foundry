"""Build the hierarchical, contrastive finance candidate-router dataset."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

from model_training.finance_candidate_router.common import (
    assert_family_separation,
    canonical_json,
    sha256_json,
    validate_rows,
    write_jsonl,
)


REPO_ROOT = Path(__file__).resolve().parents[2]
PACKAGE_ROOT = Path(__file__).resolve().parent
DEFAULT_SOURCE = (
    REPO_ROOT
    / "enterprise_root/tenants/company/training_data/finance_router_synthetic_v1"
)
DEFAULT_OUTPUT = (
    REPO_ROOT
    / "enterprise_root/tenants/company/training_data/finance_router_candidate_v1"
)


def repo_relative_str(path: Path) -> str:
    """Repo-relative path when ``path`` is under REPO_ROOT, else its absolute form.

    ``--source-dir`` (and Router Studio) may point outside the checkout, so an
    unconditional ``relative_to(REPO_ROOT)`` would raise ValueError after the
    dataset is already built. Fall back to the absolute path for external sources.
    """
    try:
        return str(path.relative_to(REPO_ROOT))
    except ValueError:
        return str(path.resolve())


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def validate_hierarchy(catalog: dict[str, Any], hierarchy: dict[str, Any]) -> dict[str, str]:
    skill_to_domain: dict[str, str] = {}
    for domain, definition in hierarchy["domains"].items():
        skills = definition["skills"]
        if not 1 <= len(skills) <= 26:
            raise ValueError(f"Domain {domain} has {len(skills)} skills; expected 1..26")
        for skill in skills:
            if skill in skill_to_domain:
                raise ValueError(f"Skill {skill} appears in multiple domains")
            skill_to_domain[skill] = domain
    catalog_skills = set(catalog["skills"])
    hierarchy_skills = set(skill_to_domain)
    if catalog_skills != hierarchy_skills:
        raise ValueError(
            "Hierarchy/catalog mismatch: "
            f"missing={sorted(catalog_skills - hierarchy_skills)}, "
            f"extra={sorted(hierarchy_skills - catalog_skills)}"
        )
    return skill_to_domain


def domain_candidates(hierarchy: dict[str, Any]) -> list[dict[str, str]]:
    candidates = [
        {"value": domain, "description": definition["description"]}
        for domain, definition in hierarchy["domains"].items()
    ]
    candidates.append(dict(hierarchy["no_match"]))
    return candidates


def skill_candidates(
    domain: str,
    catalog: dict[str, Any],
    hierarchy: dict[str, Any],
) -> list[dict[str, str]]:
    return [
        {"value": skill, "description": catalog["skills"][skill]}
        for skill in hierarchy["domains"][domain]["skills"]
    ]


def expand_source(
    *,
    source_id: str,
    family: str,
    split: str,
    context: str,
    target_skill: str,
    metadata: dict[str, Any],
    catalog: dict[str, Any],
    hierarchy: dict[str, Any],
    skill_to_domain: dict[str, str],
) -> list[dict[str, Any]]:
    domain = skill_to_domain[target_skill]
    shared_metadata = {
        **metadata,
        "source_id": source_id,
        "target_skill": target_skill,
        "target_domain": domain,
        "synthetic": True,
        "human_reviewed": False,
    }
    return [
        {
            "id": f"{source_id}::domain",
            "split": split,
            "family": family,
            "stage": "domain",
            "context": context,
            "question": "Which finance domain should handle this request? Choose no-match when none applies.",
            "candidates": domain_candidates(hierarchy),
            "target": domain,
            "metadata": shared_metadata,
        },
        {
            "id": f"{source_id}::skill",
            "split": split,
            "family": family,
            "stage": "skill",
            "context": context,
            "question": f"Which skill inside the {domain} finance domain should handle this request?",
            "candidates": skill_candidates(domain, catalog, hierarchy),
            "target": target_skill,
            "metadata": shared_metadata,
        },
    ]


def existing_rows(
    source_dir: Path,
    catalog: dict[str, Any],
    hierarchy: dict[str, Any],
    skill_to_domain: dict[str, str],
) -> dict[str, list[dict[str, Any]]]:
    output: dict[str, list[dict[str, Any]]] = {"train": [], "valid": [], "test": []}
    file_map = {"train.jsonl": "train", "calibration.jsonl": "valid", "test.jsonl": "test"}
    for filename, split in file_map.items():
        for row in load_jsonl(source_dir / filename):
            source_id = f"base::{row['id']}"
            output[split].extend(
                expand_source(
                    source_id=source_id,
                    family=source_id,
                    split=split,
                    context=row["state"]["user_message"],
                    target_skill=row["target"],
                    metadata={
                        "origin": "finance_router_synthetic_v1",
                        "original_id": row["id"],
                    },
                    catalog=catalog,
                    hierarchy=hierarchy,
                    skill_to_domain=skill_to_domain,
                )
            )
    return output


def add_contrastive_rows(
    train: list[dict[str, Any]],
    catalog: dict[str, Any],
    hierarchy: dict[str, Any],
    skill_to_domain: dict[str, str],
    contrastive: dict[str, Any],
) -> None:
    for pair in contrastive["pairs"]:
        for variant_index, (left_context, right_context) in enumerate(pair["variants"], start=1):
            family = f"contrastive::{pair['id']}::{variant_index:02d}"
            for role, context, target in (
                ("left", left_context, pair["left_skill"]),
                ("right", right_context, pair["right_skill"]),
            ):
                source_id = f"{family}::{role}"
                train.extend(
                    expand_source(
                        source_id=source_id,
                        family=family,
                        split="train",
                        context=context,
                        target_skill=target,
                        metadata={
                            "origin": contrastive["version"],
                            "contrastive_pair": pair["id"],
                            "contrastive_role": role,
                            "variant_index": variant_index,
                        },
                        catalog=catalog,
                        hierarchy=hierarchy,
                        skill_to_domain=skill_to_domain,
                    )
                )


def add_no_match_rows(
    train: list[dict[str, Any]],
    hierarchy: dict[str, Any],
    no_match: dict[str, Any],
) -> None:
    for index, context in enumerate(no_match["examples"], start=1):
        source_id = f"no-match::{index:03d}"
        train.append(
            {
                "id": f"{source_id}::domain",
                "split": "train",
                "family": source_id,
                "stage": "domain",
                "context": context,
                "question": "Which finance domain should handle this request? Choose no-match when none applies.",
                "candidates": domain_candidates(hierarchy),
                "target": "no-match",
                "metadata": {
                    "origin": no_match["version"],
                    "source_id": source_id,
                    "target_domain": "no-match",
                    "target_skill": None,
                    "synthetic": True,
                    "human_reviewed": False,
                },
            }
        )


def build(source_dir: Path, output_dir: Path) -> dict[str, Any]:
    catalog = load_json(source_dir / "catalog.json")
    hierarchy_path = PACKAGE_ROOT / "hierarchy.json"
    contrastive_path = PACKAGE_ROOT / "contrastive_pairs.json"
    no_match_path = PACKAGE_ROOT / "no_match_examples.json"
    hierarchy = load_json(hierarchy_path)
    contrastive = load_json(contrastive_path)
    no_match = load_json(no_match_path)
    skill_to_domain = validate_hierarchy(catalog, hierarchy)

    splits = existing_rows(source_dir, catalog, hierarchy, skill_to_domain)
    add_contrastive_rows(splits["train"], catalog, hierarchy, skill_to_domain, contrastive)
    add_no_match_rows(splits["train"], hierarchy, no_match)

    reports = {name: validate_rows(rows, name) for name, rows in splits.items()}
    assert_family_separation(splits)

    output_dir.mkdir(parents=True, exist_ok=True)
    for name, rows in splits.items():
        write_jsonl(output_dir / f"{name}.jsonl", rows)
    (output_dir / "catalog.json").write_text(canonical_json(catalog) + "\n", encoding="utf-8")
    (output_dir / "hierarchy.json").write_text(canonical_json(hierarchy) + "\n", encoding="utf-8")

    manifest = {
        "dataset": "finance_router_candidate_v1",
        "method": "hierarchical_candidate_logit_sft",
        "stages": ["domain", "skill"],
        "candidate_codes": "A-Z, assigned after deterministic per-record candidate shuffling",
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
            "The original 49-skill data supplies only six examples per skill across all splits.",
            "Contrastive pairs are authored routing examples, not production outcome labels.",
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
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    manifest = build(args.source_dir.resolve(), args.output_dir.resolve())
    print(json.dumps(manifest["splits"], indent=2))
    print(f"Wrote {args.output_dir.resolve()}")


if __name__ == "__main__":
    main()
