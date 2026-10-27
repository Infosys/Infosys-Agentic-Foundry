"""Framework-neutral eval suite and golden-set registry.

The functions in this module only operate on explicit directories/paths. They
do not know about AgentPro, Studio, tenants, or enterprise_root; adapters provide
those locations.
"""

from __future__ import annotations

import json
import os
import re
import tempfile
from pathlib import Path
from typing import Any

import yaml

_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")


def validate_eval_id(value: str) -> str:
    """Validate an eval suite or golden-set id."""
    clean = str(value or "").strip()
    if not _ID_RE.match(clean):
        raise ValueError(
            "Eval id must be 1-128 chars and contain only letters, numbers, "
            "underscores, hyphens, or dots."
        )
    return clean


def suite_path(evals_dir: Path, suite_id: str) -> Path:
    return Path(evals_dir) / f"{validate_eval_id(suite_id)}.yaml"


def golden_set_path(golden_sets_dir: Path, set_id: str) -> Path:
    return Path(golden_sets_dir) / f"{validate_eval_id(set_id)}.jsonl"


def list_suites(evals_dir: Path) -> list[dict[str, Any]]:
    """List normalized eval suites from a directory."""
    root = Path(evals_dir)
    root.mkdir(parents=True, exist_ok=True)
    suites: list[dict[str, Any]] = []
    for path in sorted(root.glob("*.yaml")):
        try:
            suites.append(_normalize_suite(_read_yaml(path), fallback_id=path.stem, source_file=path.name))
        except Exception as exc:  # noqa: BLE001 - surface a broken suite without hiding the list
            suites.append({
                "id": path.stem,
                "name": path.stem,
                "description": "",
                "enabled": False,
                "source_file": path.name,
                "error": str(exc),
            })
    return suites


def get_suite(evals_dir: Path, suite_id: str) -> dict[str, Any]:
    path = suite_path(evals_dir, suite_id)
    if not path.exists():
        raise FileNotFoundError(f"Eval suite '{suite_id}' not found")
    return _normalize_suite(_read_yaml(path), fallback_id=suite_id, source_file=path.name)


def save_suite(evals_dir: Path, definition: dict[str, Any]) -> dict[str, Any]:
    normalized = _normalize_suite(definition, fallback_id=str(definition.get("id") or ""))
    path = suite_path(evals_dir, normalized["id"])
    _atomic_write_text(path, yaml.safe_dump(_suite_payload(normalized), sort_keys=False, allow_unicode=True))
    normalized["source_file"] = path.name
    return normalized


def validate_suite_definition(definition: dict[str, Any]) -> dict[str, Any]:
    """Normalize a suite definition without writing it to disk."""
    return _normalize_suite(definition, fallback_id=str(definition.get("id") or ""))


def delete_suite(evals_dir: Path, suite_id: str) -> None:
    path = suite_path(evals_dir, suite_id)
    if not path.exists():
        raise FileNotFoundError(f"Eval suite '{suite_id}' not found")
    path.unlink()


def list_golden_cases(golden_sets_dir: Path, set_id: str) -> list[dict[str, Any]]:
    """Read a golden set JSONL file into normalized cases."""
    path = golden_set_path(golden_sets_dir, set_id)
    if not path.exists():
        return []
    cases: list[dict[str, Any]] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        stripped = line.strip()
        if not stripped:
            continue
        try:
            raw = json.loads(stripped)
        except json.JSONDecodeError as exc:
            raise ValueError(f"Invalid JSONL in {path.name} at line {line_number}: {exc}") from exc
        cases.append(_normalize_case(raw, fallback_id=f"case_{line_number}"))
    return cases


def save_golden_cases(golden_sets_dir: Path, set_id: str, cases: list[dict[str, Any]]) -> dict[str, Any]:
    """Replace a golden set with normalized cases."""
    path = golden_set_path(golden_sets_dir, set_id)
    normalized = [_normalize_case(case, fallback_id=f"case_{idx}") for idx, case in enumerate(cases, start=1)]
    content = "".join(json.dumps(case, ensure_ascii=False, sort_keys=False) + "\n" for case in normalized)
    _atomic_write_text(path, content)
    return {"id": validate_eval_id(set_id), "cases": normalized, "total": len(normalized), "source_file": path.name}


def append_golden_case(golden_sets_dir: Path, set_id: str, case: dict[str, Any]) -> dict[str, Any]:
    """Append one case, replacing an existing case with the same id."""
    cases = list_golden_cases(golden_sets_dir, set_id)
    normalized = _normalize_case(case, fallback_id=f"case_{len(cases) + 1}")
    merged = [existing for existing in cases if existing.get("id") != normalized["id"]]
    merged.append(normalized)
    saved = save_golden_cases(golden_sets_dir, set_id, merged)
    return {"case": normalized, "golden_set": saved}


def _read_yaml(path: Path) -> dict[str, Any]:
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        raise ValueError("Eval suite YAML must be a mapping")
    return data


def _normalize_suite(raw: dict[str, Any], *, fallback_id: str, source_file: str = "") -> dict[str, Any]:
    suite_id = validate_eval_id(raw.get("id") or fallback_id)
    target = raw.get("target") or {}
    if not isinstance(target, dict):
        raise ValueError("target must be a mapping")
    rubric = raw.get("rubric") or {}
    if not isinstance(rubric, dict):
        raise ValueError("rubric must be a mapping")
    assertions = raw.get("assertions") or []
    if not isinstance(assertions, list):
        raise ValueError("assertions must be a list")
    judge = raw.get("judge") or {}
    if not isinstance(judge, dict):
        raise ValueError("judge must be a mapping")
    evaluator = raw.get("evaluator") or {}
    if not isinstance(evaluator, dict):
        raise ValueError("evaluator must be a mapping")
    thresholds = raw.get("thresholds") or {}
    if not isinstance(thresholds, dict):
        raise ValueError("thresholds must be a mapping")
    return {
        "id": suite_id,
        "name": str(raw.get("name") or suite_id),
        "description": str(raw.get("description") or ""),
        "enabled": bool(raw.get("enabled", True)),
        "target": dict(target),
        "golden_set": str(raw.get("golden_set") or ""),
        "rubric": dict(rubric),
        "assertions": [_normalize_assertion(item) for item in assertions],
        "thresholds": dict(thresholds),
        "judge": _normalize_judge(judge),
        "evaluator": _normalize_evaluator(evaluator),
        "tags": [str(tag) for tag in (raw.get("tags") or [])],
        "metadata": dict(raw.get("metadata") or {}),
        "source_file": source_file,
    }


def _suite_payload(suite: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": suite["id"],
        "name": suite.get("name") or suite["id"],
        "description": suite.get("description") or "",
        "enabled": bool(suite.get("enabled", True)),
        "target": dict(suite.get("target") or {}),
        "golden_set": suite.get("golden_set") or "",
        "rubric": dict(suite.get("rubric") or {}),
        "assertions": list(suite.get("assertions") or []),
        "thresholds": dict(suite.get("thresholds") or {}),
        "judge": _normalize_judge(suite.get("judge") or {}),
        "evaluator": _normalize_evaluator(suite.get("evaluator") or {}),
        "tags": list(suite.get("tags") or []),
        "metadata": dict(suite.get("metadata") or {}),
    }


def _normalize_judge(raw: dict[str, Any]) -> dict[str, Any]:
    mode = str(raw.get("mode") or raw.get("judge_mode") or "rule").strip().lower()
    if mode not in {"rule", "llm", "hybrid"}:
        raise ValueError("judge.mode must be one of: rule, llm, hybrid")
    return {
        "mode": mode,
        "sample_size": _positive_int(raw.get("sample_size"), default=0),
        "max_llm_cases": _positive_int(raw.get("max_llm_cases"), default=0),
        "borderline_min": _optional_float(raw.get("borderline_min")),
        "borderline_max": _optional_float(raw.get("borderline_max")),
        "confidence_below": _optional_float(raw.get("confidence_below")),
        "escalate_on_error": bool(raw.get("escalate_on_error", True)),
        "case_tags": [str(tag) for tag in (raw.get("case_tags") or [])],
        "max_tokens": _positive_int(raw.get("max_tokens"), default=0),
        "budget_usd": _optional_float(raw.get("budget_usd")),
    }


def _normalize_evaluator(raw: dict[str, Any]) -> dict[str, Any]:
    evaluator_type = str(raw.get("type") or "rule").strip().lower()
    if evaluator_type not in {"rule", "python", "none"}:
        raise ValueError("evaluator.type must be one of: rule, python, none")
    weights = raw.get("weights") or {}
    if not isinstance(weights, dict):
        raise ValueError("evaluator.weights must be a mapping")
    config = raw.get("config") or {}
    if not isinstance(config, dict):
        raise ValueError("evaluator.config must be a mapping")
    critical = raw.get("critical") or []
    if not isinstance(critical, list):
        raise ValueError("evaluator.critical must be a list")
    return {
        "type": evaluator_type,
        "id": str(raw.get("id") or "").strip(),
        "version": str(raw.get("version") or "").strip(),
        "config": dict(config),
        "weights": {
            "rule": _positive_float(weights.get("rule"), default=1.0),
            "assertions": _positive_float(weights.get("assertions"), default=1.0),
            "python": _positive_float(weights.get("python"), default=1.0),
            "judge": _positive_float(weights.get("judge"), default=1.0),
        },
        "critical": [str(item) for item in critical],
        "min_confidence": _optional_float(raw.get("min_confidence")),
    }


def _normalize_case(raw: dict[str, Any], *, fallback_id: str) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise ValueError("golden case must be a mapping")
    case_id = validate_eval_id(raw.get("id") or fallback_id)
    assertions = raw.get("assertions") or []
    if not isinstance(assertions, list):
        raise ValueError(f"golden case '{case_id}' assertions must be a list")
    return {
        "id": case_id,
        "task": str(raw.get("task") or raw.get("input") or ""),
        "inputs": raw.get("inputs") if isinstance(raw.get("inputs"), dict) else {},
        "expected": raw.get("expected"),
        "assertions": [_normalize_assertion(item) for item in assertions],
        "tags": [str(tag) for tag in (raw.get("tags") or [])],
        "metadata": dict(raw.get("metadata") or {}),
    }


def _normalize_assertion(raw: Any) -> dict[str, Any]:
    if isinstance(raw, str):
        raw = {"type": "contains", "value": raw}
    if not isinstance(raw, dict):
        raise ValueError("assertion must be a mapping or string")
    assertion_type = str(raw.get("type") or "contains").strip().lower()
    if assertion_type not in {"exact", "contains", "not_contains", "numeric", "regex"}:
        raise ValueError("assertion.type must be one of: exact, contains, not_contains, numeric, regex")
    item = dict(raw)
    item["type"] = assertion_type
    item["critical"] = bool(item.get("critical", False))
    if item.get("id") is not None:
        item["id"] = validate_eval_id(str(item.get("id")))
    return item


def _positive_int(value: Any, *, default: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return max(0, parsed)


def _positive_float(value: Any, *, default: float) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return default
    return max(0.0, parsed)


def _optional_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _atomic_write_text(path: Path, content: str) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", dir=path.parent, delete=False, suffix=".tmp", encoding="utf-8") as handle:
        handle.write(content)
        tmp = handle.name
    os.replace(tmp, path)
