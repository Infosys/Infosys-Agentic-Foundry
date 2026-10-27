"""
Approval Rule Evaluator — Pure-function engine for HITL rules.

Evaluates skill.approval_rules against runtime context to determine
whether human approval is required. Used by:

1. Prompt compiler (compile_rules_to_prompt) → inject natural-language instructions
2. Tool guard (evaluate_rules) → framework-level enforcement
3. Post-action audit (evaluate_rules) → detect violations

All functions are stateless and side-effect free.
"""

import json
import operator
from typing import Any, Dict, List, Optional, Tuple



_OPS = {
    ">": operator.gt,
    ">=": operator.ge,
    "<": operator.lt,
    "<=": operator.le,
    "==": operator.eq,
    "!=": operator.ne,
}


def _compare(value: Any, op: str, threshold: Any) -> bool:
    """Safe comparison with type coercion."""
    try:
        fn = _OPS.get(op)
        if fn is None:
            return False
        # Try numeric comparison
        return fn(float(value), float(threshold))
    except (ValueError, TypeError):
        # Fall back to string comparison
        return fn(str(value), str(threshold))



def evaluate_rules(
    context: Dict[str, Any],
    rules: Dict[str, Any],
) -> Optional[Tuple[str, str, str]]:
    """
    Evaluate approval rules against runtime context.

    Args:
        context: Runtime context dict with keys like 'action', 'amount', etc.
        rules: The approval_rules dict from skill YAML.

    Returns:
        Tuple of (reason, urgency, rule_type) if approval required, else None.
    """
    if not rules:
        return None

    action = str(context.get("action", "")).lower().strip()
    default_urgency = rules.get("default_urgency", "medium")

    never = [s.lower().replace('_', ' ') for s in rules.get("never_require", [])]
    action_normalized = action.replace('_', ' ')
    if action and (action in never or action_normalized in never):
        return None

    always = [s.lower().replace('_', ' ') for s in rules.get("always_require", [])]
    if action and (action in always or action_normalized in always):
        return (
            f"Policy: '{action}' always requires human approval",
            default_urgency,
            "always_require",
        )

    for t in rules.get("thresholds", []):
        field_name = t.get("field", "")
        value = context.get(field_name)
        if value is not None:
            if _compare(value, t.get("operator", ">="), t.get("value", 0)):
                return (
                    t.get("reason", f"{field_name} {t.get('operator')} {t.get('value')}"),
                    t.get("urgency", default_urgency),
                    "threshold",
                )

    context_text = json.dumps(context, default=str).lower()
    context_text_normalized = context_text.replace("_", " ")
    for c in rules.get("conditions", []):
        keyword = c.get("when", "").lower()
        keyword_normalized = keyword.replace("_", " ")
        if keyword and (keyword in context_text or keyword_normalized in context_text_normalized):
            return (
                c.get("reason", f"Condition matched: {keyword}"),
                c.get("urgency", default_urgency),
                "condition",
            )

    return None



def escalate_urgency(
    context: Dict[str, Any],
    rules: Dict[str, Any],
    base_urgency: str = "medium",
) -> str:
    """
    Return the highest urgency from rules matching this context.
    If no rules match, return base_urgency.
    """
    result = evaluate_rules(context, rules)
    if result:
        _, matched_urgency, _ = result
        return _max_urgency(matched_urgency, base_urgency)
    return base_urgency


_URGENCY_RANK = {"low": 0, "medium": 1, "high": 2, "critical": 3}

def _max_urgency(a: str, b: str) -> str:
    return a if _URGENCY_RANK.get(a, 1) >= _URGENCY_RANK.get(b, 1) else b



DEFAULT_SLA = {"low": 480, "medium": 120, "high": 30, "critical": 10}

def get_sla_minutes(urgency: str, rules: Dict[str, Any] = None) -> int:
    """Get SLA in minutes based on urgency and optional custom rules."""
    if rules and "sla_minutes" in rules:
        return int(rules["sla_minutes"])
    return DEFAULT_SLA.get(urgency, 120)



def compile_rules_to_prompt(rules: Dict[str, Any]) -> str:
    """
    Compile approval_rules YAML into natural-language prompt instructions.

    This is injected into the system prompt so the LLM knows when to call
    the request_human_approval tool.
    """
    if not rules:
        return ""

    lines = [
        "",
        "# APPROVAL POLICY (MANDATORY)",
        "",
        "You have a `request_human_approval` tool. You MUST call it BEFORE taking action when any of these rules match.",
        "Do NOT proceed with the action until approval is received.",
        "",
    ]

    # Thresholds
    thresholds = rules.get("thresholds", [])
    if thresholds:
        lines.append("## Threshold Rules")
        for t in thresholds:
            urgency = t.get("urgency", rules.get("default_urgency", "medium"))
            lines.append(
                f"- When `{t.get('field')}` {t.get('operator', '>=')} {t.get('value')}: "
                f'"{t.get("reason", "threshold exceeded")}" (urgency: {urgency})'
            )
        lines.append("")

    # Conditions
    conditions = rules.get("conditions", [])
    if conditions:
        lines.append("## Condition Rules")
        for c in conditions:
            urgency = c.get("urgency", rules.get("default_urgency", "medium"))
            lines.append(
                f'- When action involves **{c.get("when")}**: '
                f'"{c.get("reason", "condition matched")}" (urgency: {urgency})'
            )
        lines.append("")

    # Always require
    always = rules.get("always_require", [])
    if always:
        lines.append(f"## Always Require Approval: {', '.join(always)}")
        lines.append("")

    # Never require
    never = rules.get("never_require", [])
    if never:
        lines.append(f"## Never Require Approval (proceed freely): {', '.join(never)}")
        lines.append("")

    # Tool usage
    lines.extend([
        "## How to Request Approval",
        "",
        "Call request_human_approval with:",
        "- `reason`: Why approval is needed (reference the rule above)",
        "- `context`: JSON with relevant data (amounts, entities, identifiers)",
        "- `options`: List of choices, e.g. [\"Approve\", \"Reject\", \"Approve with conditions\"]",
        "- `urgency`: As specified by the rule (low/medium/high/critical)",
        "",
        "After calling request_human_approval, STOP and wait. Do NOT continue the action.",
        "",
    ])

    return "\n".join(lines)
