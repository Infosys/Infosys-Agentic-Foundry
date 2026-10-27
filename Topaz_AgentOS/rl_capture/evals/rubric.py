"""Deterministic rubric and expected-output assertions for eval suites."""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class AssertionResult:
    assertion_type: str
    passed: bool
    reason: str
    expected: Any = None
    actual: Any = None
    assertion_id: str = ""
    critical: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "type": self.assertion_type,
            "passed": self.passed,
            "reason": self.reason,
            "expected": self.expected,
            "actual": self.actual,
            "id": self.assertion_id,
            "critical": self.critical,
        }


def extract_output_text(value: Any) -> str:
    """Return comparable text from a candidate result or trajectory detail."""
    if isinstance(value, str):
        return value
    if not isinstance(value, dict):
        return "" if value is None else str(value)
    for key in ("output", "response", "answer", "text", "summary"):
        if value.get(key) is not None:
            return str(value.get(key) or "")
    trajectory = value.get("trajectory") if "trajectory" in value else value
    calls = trajectory.get("model_calls") or [] if isinstance(trajectory, dict) else []
    if calls:
        last = calls[-1] or {}
        return "\n".join(
            str(message.get("content") or "")
            for message in (last.get("output_messages") or [])
            if isinstance(message, dict)
        ).strip()
    return ""


def evaluate_assertions(
    candidate: Any,
    *,
    expected: Any = None,
    assertions: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Evaluate assertion checks against a candidate output.

    Supported types: exact, contains, not_contains, numeric, regex.
    """
    candidate_text = extract_output_text(candidate)
    checks = list(assertions or [])
    if expected is not None and not checks:
        checks = [{"type": "contains", "value": expected}]
    results = [_evaluate_one(candidate_text, expected=expected, assertion=check).to_dict() for check in checks]
    passed = sum(1 for result in results if result["passed"])
    total = len(results)
    score = 1.0 if total == 0 else round(passed / total, 3)
    verdict = "pass" if score == 1.0 else ("fail" if score == 0.0 else "partial")
    return {
        "score": score,
        "verdict": verdict,
        "passed": passed,
        "total": total,
        "results": results,
    }


def score_expected_output(
    candidate: Any,
    *,
    expected: Any = None,
    assertions: list[dict[str, Any]] | None = None,
    weight: float = 1.0,
) -> dict[str, Any]:
    """Return a score in [-1, 1] from expected-output assertions."""
    evaluated = evaluate_assertions(candidate, expected=expected, assertions=assertions)
    if evaluated["total"] == 0:
        raw_score = 0.0
    else:
        raw_score = (evaluated["score"] * 2.0) - 1.0
    weighted = round(max(-1.0, min(1.0, raw_score * float(weight))), 3)
    return {
        "score": weighted,
        "verdict": evaluated["verdict"],
        "confidence": 0.9 if evaluated["total"] else 0.0,
        "rubric": "expected_assertions_v1",
        "reasons": [
            f"assertions:{evaluated['passed']}/{evaluated['total']}",
            *[
                f"{item['type']}:{'pass' if item['passed'] else 'fail'}"
                for item in evaluated["results"]
            ],
        ],
        "assertions": evaluated,
    }


def _evaluate_one(candidate_text: str, *, expected: Any, assertion: dict[str, Any]) -> AssertionResult:
    assertion_type = str(assertion.get("type") or "contains").strip().lower()
    value = assertion.get("value", expected)
    case_sensitive = bool(assertion.get("case_sensitive", False))
    assertion_id = str(assertion.get("id") or assertion_type)
    critical = bool(assertion.get("critical", False))
    actual = candidate_text if case_sensitive else candidate_text.lower()
    comparable = "" if value is None else str(value)
    expected_text = comparable if case_sensitive else comparable.lower()

    if assertion_type == "exact":
        passed = actual.strip() == expected_text.strip()
        return AssertionResult(assertion_type, passed, "exact match" if passed else "text did not exactly match", comparable, candidate_text, assertion_id, critical)

    if assertion_type == "contains":
        passed = expected_text in actual
        return AssertionResult(assertion_type, passed, "expected text present" if passed else "expected text missing", comparable, candidate_text, assertion_id, critical)

    if assertion_type == "not_contains":
        passed = expected_text not in actual
        return AssertionResult(assertion_type, passed, "forbidden text absent" if passed else "forbidden text present", comparable, candidate_text, assertion_id, critical)

    if assertion_type == "regex":
        flags = 0 if case_sensitive else re.IGNORECASE
        try:
            passed = re.search(str(value or ""), candidate_text, flags=flags) is not None
        except re.error as exc:
            return AssertionResult(assertion_type, False, f"invalid regex: {exc}", value, candidate_text, assertion_id, critical)
        return AssertionResult(assertion_type, passed, "regex matched" if passed else "regex did not match", value, candidate_text, assertion_id, critical)

    if assertion_type == "numeric":
        return _numeric_assertion(candidate_text, assertion=assertion, fallback_expected=value)

    return AssertionResult(assertion_type, False, f"unsupported assertion type: {assertion_type}", value, candidate_text, assertion_id, critical)


def _numeric_assertion(candidate_text: str, *, assertion: dict[str, Any], fallback_expected: Any) -> AssertionResult:
    expected_raw = assertion.get("expected", fallback_expected)
    actual_raw = assertion.get("actual")
    tolerance = float(assertion.get("tolerance", 0))
    assertion_id = str(assertion.get("id") or "numeric")
    critical = bool(assertion.get("critical", False))
    try:
        expected_num = float(expected_raw)
        actual_num = float(actual_raw) if actual_raw is not None else _closest_number(candidate_text, expected_num)
    except (TypeError, ValueError):
        return AssertionResult("numeric", False, "could not parse numeric values", expected_raw, actual_raw or candidate_text, assertion_id, critical)
    if actual_num is None or not math.isfinite(actual_num):
        return AssertionResult("numeric", False, "candidate did not contain a number", expected_num, candidate_text, assertion_id, critical)
    passed = abs(actual_num - expected_num) <= tolerance
    reason = "numeric value within tolerance" if passed else "numeric value outside tolerance"
    return AssertionResult("numeric", passed, reason, expected_num, actual_num, assertion_id, critical)


def _closest_number(text: str, expected: float) -> float | None:
    matches = [float(match.group(0)) for match in re.finditer(r"[-+]?\d+(?:\.\d+)?", str(text or ""))]
    if not matches:
        return None
    return min(matches, key=lambda item: abs(item - expected))
