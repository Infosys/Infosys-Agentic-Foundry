"""Tenant-owned eval registry, rubrics, and runners.

This package is intentionally framework-neutral. Host applications provide
paths, candidate producers, and storage engines through adapters.
"""

from .registry import (
    append_golden_case,
    delete_suite,
    get_suite,
    list_golden_cases,
    list_suites,
    save_golden_cases,
    save_suite,
    validate_eval_id,
)
from .rubric import evaluate_assertions, score_expected_output
from .runner import run_suite

__all__ = [
    "append_golden_case",
    "delete_suite",
    "evaluate_assertions",
    "get_suite",
    "list_golden_cases",
    "list_suites",
    "save_golden_cases",
    "save_suite",
    "score_expected_output",
    "run_suite",
    "validate_eval_id",
]
