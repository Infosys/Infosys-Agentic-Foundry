#!/usr/bin/env python3
"""Deterministic evaluator for Central Policy & Control Registry hooks.

This script is intentionally generic: policy authors provide structured
conditions in ``security/policy_control.yaml`` and generated hooks call this
script with ``--policy-id``. The script never executes policy-authored code.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path
from typing import Any

import yaml


def _tenant_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _registry_path() -> Path:
    return (_tenant_root() / "security" / "policy_control.yaml").resolve()


def _load_policy(policy_id: str) -> dict[str, Any] | None:
    path = _registry_path()
    if not path.exists():
        return None
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    for policy in data.get("policies", []):
        if isinstance(policy, dict) and str(policy.get("policy_id")) == policy_id:
            return policy
    return None


def _json_env(name: str) -> Any:
    raw = os.environ.get(name) or ""
    if not raw:
        return {}
    try:
        return json.loads(raw)
    except Exception:
        return raw


def _extract_amount(text: str) -> float | None:
    matches = re.findall(r"(?:[$₹€£]\s*)?(\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?", text or "")
    if not matches:
        return None
    values = []
    for match in matches:
        try:
            values.append(float(match.replace(",", "")))
        except ValueError:
            continue
    return max(values) if values else None


def _context() -> dict[str, Any]:
    tool_input = _json_env("IAF_TOOL_INPUT")
    command = ""
    if isinstance(tool_input, dict):
        command = str(tool_input.get("command") or tool_input.get("cmd") or tool_input.get("query") or "")
    elif isinstance(tool_input, str):
        command = tool_input
    return {
        "env": dict(os.environ),
        "tool_input": tool_input,
        "tool_name": os.environ.get("IAF_TOOL_NAME", ""),
        "current_skill": os.environ.get("IAF_CURRENT_SKILL") or os.environ.get("IAF_SKILL_NAME", ""),
        "trace_id": os.environ.get("IAF_TRACE_ID", ""),
        "tenant_id": os.environ.get("IAF_TENANT_ID", ""),
        "user_id": os.environ.get("IAF_USER_ID", ""),
        "command": command,
        "extracted": {
            "amount": _extract_amount(command),
        },
    }


def _get_path(context: dict[str, Any], field: str) -> Any:
    value: Any = context
    for part in str(field).split("."):
        if isinstance(value, dict):
            value = value.get(part)
        else:
            return None
    return value


def _compare(actual: Any, operator: str, expected: Any) -> bool:
    if operator == "exists":
        return actual not in (None, "")
    if operator == "equals":
        return str(actual) == str(expected)
    if operator == "not_equals":
        return str(actual) != str(expected)
    if operator == "contains":
        return str(expected).lower() in str(actual or "").lower()
    if operator == "not_contains":
        return str(expected).lower() not in str(actual or "").lower()
    if operator == "regex":
        return re.search(str(expected), str(actual or ""), flags=re.IGNORECASE) is not None
    if operator in {"greater_than", "greater_than_or_equal", "less_than", "less_than_or_equal"}:
        try:
            left = float(actual or 0)
            right = float(expected or 0)
        except (TypeError, ValueError):
            return False
        return {
            "greater_than": left > right,
            "greater_than_or_equal": left >= right,
            "less_than": left < right,
            "less_than_or_equal": left <= right,
        }[operator]
    if operator in {"in", "not_in"}:
        values = expected if isinstance(expected, list) else [expected]
        result = str(actual) in {str(v) for v in values}
        return result if operator == "in" else not result
    return False


def _evaluate(policy: dict[str, Any], context: dict[str, Any]) -> tuple[bool, list[dict[str, Any]]]:
    conditions = policy.get("conditions") or {"all": []}
    group = "any" if "any" in conditions else "all"
    checks = []
    for cond in conditions.get(group, []):
        if not isinstance(cond, dict):
            continue
        actual = _get_path(context, str(cond.get("field") or "tool_input.command"))
        matched = _compare(actual, str(cond.get("operator") or "contains"), cond.get("value"))
        checks.append({
            "field": cond.get("field"),
            "operator": cond.get("operator"),
            "value": cond.get("value"),
            "actual": actual,
            "matched": matched,
        })
    if not checks:
        return True, []
    matched = any(c["matched"] for c in checks) if group == "any" else all(c["matched"] for c in checks)
    return matched, checks


def _emit(blocked: bool, reason: str, policy: dict[str, Any], checks: list[dict[str, Any]]) -> None:
    print(json.dumps({
        "blocked": blocked,
        "reason": reason,
        "policy_id": policy.get("policy_id"),
        "policy_name": policy.get("name"),
        "policy_version": policy.get("version", 1),
        "decision": policy.get("decision"),
        "risk_tier": policy.get("risk_tier"),
        "matched_conditions": checks,
        "approval": policy.get("approval", {}),
        "evidence_required": (policy.get("evidence") or {}).get("required", []),
    }))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--policy-id", required=True)
    args = parser.parse_args()

    policy = _load_policy(args.policy_id)
    if not policy:
        print(json.dumps({"blocked": True, "reason": f"Policy '{args.policy_id}' not found"}))
        return 1
    if str(policy.get("status", "draft")).lower() != "active":
        _emit(False, f"Policy {args.policy_id} is not active", policy, [])
        return 0

    context = _context()
    matched, checks = _evaluate(policy, context)
    if not matched:
        _emit(False, f"Policy {args.policy_id} did not match", policy, checks)
        return 0

    decision = str(policy.get("decision") or "deny").lower()
    if decision == "allow":
        _emit(False, f"Policy {args.policy_id} allowed action", policy, checks)
        return 0

    if decision == "approve":
        approval = policy.get("approval") or {}
        reason = (
            f"[policy:{args.policy_id}] Approval required by {policy.get('name')}: "
            f"matched {len([c for c in checks if c.get('matched')])} condition(s); "
            f"approver_role={approval.get('approver_role', 'approver')}; "
            f"sla_minutes={approval.get('sla_minutes', 30)}"
        )
        _emit(True, reason, policy, checks)
        return 1

    reason = f"[policy:{args.policy_id}] Action blocked by {policy.get('name')} decision={decision}"
    _emit(True, reason, policy, checks)
    return 1


if __name__ == "__main__":
    sys.exit(main())

