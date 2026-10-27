"""Registry-backed in-process hooks for the model-call pipeline."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import yaml

from .hook_runner import HOOK_AFTER_MODEL_CALL


_DEFAULT_REDACTIONS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"), "[REDACTED_EMAIL]"),
    (re.compile(r"\b\d{3}-\d{2}-\d{4}\b"), "[REDACTED_SSN]"),
    (re.compile(r"\b(?:\d[ -]*?){13,19}\b"), "[REDACTED_CARD]"),
    (re.compile(r"\b(?:api[_ -]?key|token|secret|password)\s*[:=]\s*['\"]?[^'\"\s,;]+", re.IGNORECASE), "[REDACTED_SECRET]"),
)


def register_policy_control_model_call_hooks(
    hook_runner: Any,
    *,
    agent_root: str,
    tenant_id: str = "",
    agent_id: str = "",
) -> None:
    """Register central-policy model-call hooks for one SkillAgent instance."""
    if hook_runner is None:
        return

    hook_runner.register_internal(
        HOOK_AFTER_MODEL_CALL,
        lambda ctx: _run_after_model_call_policies(
            ctx,
            agent_root=agent_root,
            tenant_id=tenant_id,
            agent_id=agent_id,
        ),
        hook_id="policy_control:model_call_after",
        priority=100,
        mutates=["content"],
        hot_path=True,
    )


def _run_after_model_call_policies(
    ctx: dict[str, Any],
    *,
    agent_root: str,
    tenant_id: str,
    agent_id: str,
) -> dict[str, Any] | None:
    content = str(ctx.get("response_content") or "")
    if not content:
        return None

    matched: list[dict[str, Any]] = []
    scrubbed = content
    for policy in _load_policies(agent_root):
        if str(policy.get("status", "draft")).lower() != "active":
            continue
        if str(policy.get("event") or "") != HOOK_AFTER_MODEL_CALL:
            continue
        if str(policy.get("decision") or "").lower() not in {"redact", "scrub"}:
            continue
        if not _scope_matches(policy, ctx, tenant_id=tenant_id, agent_id=agent_id):
            continue
        policy_ctx = _policy_context(ctx, scrubbed)
        ok, checks = _evaluate(policy, policy_ctx)
        if not ok:
            continue
        before = scrubbed
        scrubbed = _apply_redactions(scrubbed, policy)
        if scrubbed != before:
            matched.append({
                "policy_id": policy.get("policy_id"),
                "policy_name": policy.get("name"),
                "risk_tier": policy.get("risk_tier"),
                "matched_conditions": checks,
            })

    if scrubbed == content:
        return None
    return {
        "response_content": scrubbed,
        "metadata": {
            "policy_control": {
                "model_call_policies": matched,
                "redacted": True,
            }
        },
    }


def _registry_path(agent_root: str) -> Path:
    return (Path(agent_root).resolve() / "../../security/policy_control.yaml").resolve()


def _load_policies(agent_root: str) -> list[dict[str, Any]]:
    path = _registry_path(agent_root)
    if not path.exists():
        return []
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except Exception:
        return []
    policies = data.get("policies", [])
    return [policy for policy in policies if isinstance(policy, dict)]


def _scope_matches(policy: dict[str, Any], ctx: dict[str, Any], *, tenant_id: str, agent_id: str) -> bool:
    scope = policy.get("scope") if isinstance(policy.get("scope"), dict) else {}
    expected_tenant = str(scope.get("tenant_id") or "")
    expected_agent = str(scope.get("agent_id") or "")
    skill_name = str(ctx.get("skill_name") or ctx.get("current_skill") or "")
    skills = scope.get("skills") if isinstance(scope.get("skills"), list) else []
    if expected_tenant and expected_tenant != str(ctx.get("tenant_id") or tenant_id or ""):
        return False
    if expected_agent and expected_agent != str(ctx.get("agent_id") or agent_id or ""):
        return False
    if skills and skill_name not in {str(skill) for skill in skills}:
        return False
    return True


def _policy_context(ctx: dict[str, Any], content: str) -> dict[str, Any]:
    query = str(ctx.get("query") or "")
    return {
        **ctx,
        "query": query,
        "response_content": content,
        "model_name": str(ctx.get("model_name") or ""),
        "model_role": str(ctx.get("model_role") or ""),
        "extracted": {
            "amount": _extract_amount(query + "\n" + content),
        },
    }


def _extract_amount(text: str) -> float | None:
    matches = re.findall(r"(?:[$₹€£]\s*)?(\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?", text or "")
    values: list[float] = []
    for match in matches:
        try:
            values.append(float(match.replace(",", "")))
        except ValueError:
            continue
    return max(values) if values else None


def _evaluate(policy: dict[str, Any], context: dict[str, Any]) -> tuple[bool, list[dict[str, Any]]]:
    conditions = policy.get("conditions") if isinstance(policy.get("conditions"), dict) else {"all": []}
    group = "any" if "any" in conditions else "all"
    checks: list[dict[str, Any]] = []
    for cond in conditions.get(group, []):
        if not isinstance(cond, dict):
            continue
        field = str(cond.get("field") or "response_content")
        actual = _get_path(context, field)
        operator = str(cond.get("operator") or "contains")
        expected = cond.get("value")
        matched = _compare(actual, operator, expected)
        checks.append({
            "field": field,
            "operator": operator,
            "value": expected,
            "actual": actual,
            "matched": matched,
        })
    if not checks:
        return True, []
    ok = any(item["matched"] for item in checks) if group == "any" else all(item["matched"] for item in checks)
    return ok, checks


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
        result = str(actual) in {str(value) for value in values}
        return result if operator == "in" else not result
    return False


def _apply_redactions(content: str, policy: dict[str, Any]) -> str:
    redaction = policy.get("redaction") if isinstance(policy.get("redaction"), dict) else {}
    patterns = redaction.get("patterns") if isinstance(redaction.get("patterns"), list) else []
    text = content
    if patterns:
        for item in patterns:
            if not isinstance(item, dict):
                continue
            pattern = str(item.get("regex") or "")
            replacement = str(item.get("replacement") or "[REDACTED]")
            if not pattern:
                continue
            try:
                text = re.sub(pattern, replacement, text, flags=re.IGNORECASE)
            except re.error:
                continue
        return text
    for pattern, replacement in _DEFAULT_REDACTIONS:
        text = pattern.sub(replacement, text)
    return text
