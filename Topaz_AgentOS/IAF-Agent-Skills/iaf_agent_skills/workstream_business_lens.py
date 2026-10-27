"""Business-lens aggregation for Workstream state.

The UI renders ``business_lens`` as-is, but the numbers should be owned by the
backend workstream lifecycle. This module computes generic rollups from
domain-neutral item metadata such as ``case_summary.primary_entity`` and
``case_summary.impact_value``.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any


_CURRENCY_RE = re.compile(r"([$€£₹])?\s*([-+]?\d[\d,]*(?:\.\d+)?)\s*([kKmMbB])?")
_AGE_RE = re.compile(r"(\d+)\s*\+?\s*(?:days?|d)\b", re.IGNORECASE)
_APPROVAL_RE = re.compile(r"\b(approval|approve|escalat|manager|controller|cfo|review)\b", re.IGNORECASE)
_NO_APPROVAL_RE = re.compile(r"\b(no|not|without)\s+(?:\w+\s+){0,2}(?:approval|approve|escalation|review)\b", re.IGNORECASE)
_READY_RE = re.compile(r"\b(offset|refund|follow[- ]?up|recover|collect|close|apply|credit)\b", re.IGNORECASE)


def _case_summary(item: dict[str, Any]) -> dict[str, Any]:
    value = item.get("case_summary")
    return value if isinstance(value, dict) else {}


def parse_impact_value(value: Any) -> float:
    """Best-effort conversion for values like ``$12,000`` or ``€1.2M``."""
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value or "").strip()
    match = _CURRENCY_RE.search(text)
    if not match:
        return 0.0
    amount = float(match.group(2).replace(",", ""))
    suffix = (match.group(3) or "").lower()
    if suffix == "k":
        amount *= 1_000
    elif suffix == "m":
        amount *= 1_000_000
    elif suffix == "b":
        amount *= 1_000_000_000
    return amount


def parse_age_days(value: Any) -> int | None:
    """Extract a day count from generic age/SLA strings."""
    if isinstance(value, (int, float)):
        return int(value)
    text = str(value or "").strip()
    match = _AGE_RE.search(text)
    if match:
        return int(match.group(1))
    return None


def _currency_symbol(items: list[dict[str, Any]]) -> str:
    for item in items:
        impact = str(_case_summary(item).get("impact_value") or "")
        match = _CURRENCY_RE.search(impact)
        if match and match.group(1):
            return match.group(1)
    return ""


def _format_number(value: float) -> str:
    if value >= 1_000_000:
        return f"{value / 1_000_000:.1f}M".replace(".0M", "M")
    if value >= 1_000:
        return f"{value / 1_000:.1f}K".replace(".0K", "K")
    if value == int(value):
        return str(int(value))
    return f"{value:.1f}"


def _format_value(value: float, *, unit: str = "", symbol: str = "") -> str:
    if unit == "currency" or symbol:
        return f"{symbol or '$'}{_format_number(value)}"
    return _format_number(value)


def _severity_for_value(value: float, total: float) -> str:
    if value <= 0:
        return "low"
    if total > 0 and value / total >= 0.5:
        return "critical"
    if total > 0 and value / total >= 0.25:
        return "high"
    return "medium"


def _active_items(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        item for item in items
        if (item.get("status") or "pending") not in {"done"}
    ]


def _is_aged_or_high_risk(item: dict[str, Any]) -> bool:
    summary = _case_summary(item)
    age = parse_age_days(summary.get("age_or_sla"))
    risk = str(summary.get("risk_level") or "").lower()
    return (age is not None and age >= 60) or risk in {"high", "critical"}


def _is_approval_gated(item: dict[str, Any]) -> bool:
    if item.get("escalated_approval_id") or item.get("status") == "awaiting_human":
        return True
    summary = _case_summary(item)
    text = " ".join(str(summary.get(key) or "") for key in ("policy_trigger", "recommended_action", "priority_reason"))
    if _NO_APPROVAL_RE.search(text):
        return False
    return bool(_APPROVAL_RE.search(text))


def _is_action_ready(item: dict[str, Any]) -> bool:
    if _is_approval_gated(item):
        return False
    summary = _case_summary(item)
    action = str(summary.get("recommended_action") or "")
    return bool(_READY_RE.search(action))


def _metric_value(metric_id: str, unit: str, stats: dict[str, Any]) -> tuple[str, str]:
    mid = metric_id.lower()
    symbol = stats["currency_symbol"]
    total = stats["total_value"]
    all_items = stats.get("all_items", [])
    active = stats.get("active_items", [])

    if any(token in mid for token in ("readiness", "completion", "progress")):
        total_count = len(all_items) if all_items else len(active)
        done_count = stats.get("done_count", 0)
        if total_count > 0:
            pct = round(done_count / total_count * 100)
        else:
            pct = 0
        sev = "low" if pct >= 80 else ("medium" if pct >= 50 else "critical")
        return f"{pct}%", sev

    if any(token in mid for token in ("open", "exception", "pending")):
        count = stats.get("open_count", len(active))
        if unit in {"currency"}:
            return _format_value(total, unit=unit, symbol=symbol), _severity_for_value(total, total)
        return str(count), "critical" if count else "low"

    if any(token in mid for token in ("customer", "vendor", "entity", "impacted")):
        count = stats["primary_entity_count"]
        return str(count), "medium" if count else "low"

    if any(token in mid for token in ("aged", "sla", "risk")):
        if unit in {"cases", "tickets", "items"}:
            count = stats["aged_count"]
            return str(count), "critical" if count else "low"
        value = stats["aged_value"]
        return _format_value(value, unit=unit, symbol=symbol), _severity_for_value(value, total)

    if any(token in mid for token in ("auto", "eligible")):
        count = stats.get("auto_approve_count", 0)
        value = stats.get("auto_approve_value", 0.0)
        if unit in {"cases", "tickets", "items"}:
            return str(count), "low" if count <= 2 else "medium"
        return _format_value(value, unit=unit, symbol=symbol), _severity_for_value(value, total)

    if any(token in mid for token in ("approval", "approve", "gated")):
        value = stats["approval_value"]
        return _format_value(value, unit=unit, symbol=symbol), _severity_for_value(value, total)

    if any(token in mid for token in ("ready", "offset", "action")):
        value = stats["action_ready_value"]
        return _format_value(value, unit=unit, symbol=symbol), _severity_for_value(value, total)

    if any(token in mid for token in ("total", "exposure", "impact")):
        return _format_value(total, unit=unit, symbol=symbol), _severity_for_value(total, total)

    return _format_value(total, unit=unit, symbol=symbol), _severity_for_value(total, total)


def _is_auto_approve_eligible(item: dict[str, Any]) -> bool:
    """Low-risk items below threshold that can be auto-approved."""
    summary = _case_summary(item)
    risk = str(summary.get("risk_level") or "").lower()
    mode = str(summary.get("resolution_mode") or "").lower()
    return mode == "auto_approve" or risk == "low"


def _stats(items: list[dict[str, Any]]) -> dict[str, Any]:
    active = _active_items(items)
    done_items = [item for item in items if (item.get("status") or "") == "done"]
    entity_values = {
        str(_case_summary(item).get("primary_entity") or "").strip()
        for item in active
        if _case_summary(item).get("primary_entity")
    }
    total_value = sum(parse_impact_value(_case_summary(item).get("impact_value") or item.get("priority_metric")) for item in active)
    aged_items = [item for item in active if _is_aged_or_high_risk(item)]
    approval_items = [item for item in active if _is_approval_gated(item)]
    action_ready_items = [item for item in active if _is_action_ready(item)]
    auto_approve_items = [item for item in active if _is_auto_approve_eligible(item)]
    return {
        "all_items": items,
        "active_items": active,
        "total_value": total_value,
        "done_count": len(done_items),
        "open_count": len(active),
        "aged_count": len(aged_items),
        "aged_value": sum(parse_impact_value(_case_summary(item).get("impact_value") or item.get("priority_metric")) for item in aged_items),
        "approval_value": sum(parse_impact_value(_case_summary(item).get("impact_value") or item.get("priority_metric")) for item in approval_items),
        "action_ready_value": sum(parse_impact_value(_case_summary(item).get("impact_value") or item.get("priority_metric")) for item in action_ready_items),
        "auto_approve_count": len(auto_approve_items),
        "auto_approve_value": sum(parse_impact_value(_case_summary(item).get("impact_value") or item.get("priority_metric")) for item in auto_approve_items),
        "primary_entity_count": len(entity_values),
        "currency_symbol": _currency_symbol(active),
    }


def _default_metrics() -> list[dict[str, Any]]:
    return [
        {
            "id": "total_impact",
            "label": "Total Impact",
            "unit": "currency",
            "explanation": "Open business value across active workstream cases.",
        },
        {
            "id": "aged_or_sla_risk",
            "label": "Aged / SLA Risk",
            "unit": "currency",
            "explanation": "Value tied to aged, high-risk, or SLA-sensitive cases.",
        },
        {
            "id": "entities_impacted",
            "label": "Entities Impacted",
            "unit": "entities",
            "explanation": "Distinct primary entities represented in active cases.",
        },
        {
            "id": "approval_gated_value",
            "label": "Approval-Gated Value",
            "unit": "currency",
            "explanation": "Value that appears blocked by approval, escalation, or review policy.",
        },
        {
            "id": "action_ready_value",
            "label": "Action-Ready Value",
            "unit": "currency",
            "explanation": "Value with a non-approval recommended action path.",
        },
    ]


def refresh_business_lens(workstream: dict[str, Any]) -> dict[str, Any]:
    """Return a workstream copy with refreshed ``business_lens.metrics``.

    If the workstream has no item ``case_summary`` metadata and no existing
    business lens, the input is returned with only a shallow copy/default pass.
    Existing lens labels, titles, units, and explanations are preserved; values
    and severities are overwritten from current item state.
    """
    ws = dict(workstream)
    items = [item for item in ws.get("items") or [] if isinstance(item, dict)]
    has_case_summary = any(isinstance(item.get("case_summary"), dict) for item in items)
    existing_lens = ws.get("business_lens") if isinstance(ws.get("business_lens"), dict) else {}
    existing_metrics = existing_lens.get("metrics") if isinstance(existing_lens, dict) else None
    alias_metrics = ws.get("business_metrics") if isinstance(ws.get("business_metrics"), list) else None

    if not has_case_summary and not existing_metrics and not alias_metrics:
        return ws

    lens = dict(existing_lens or {})
    lens.setdefault("title", "Business Impact")
    lens.setdefault("subtitle", "Business KPIs generated from active workstream cases")
    lens.setdefault("primary_entity_label", "Primary entity")
    lens.setdefault("secondary_entity_label", "Case")
    lens.setdefault("value_label", "Impact")

    definitions = existing_metrics if isinstance(existing_metrics, list) and existing_metrics else alias_metrics
    if not definitions:
        definitions = _default_metrics()

    stats = _stats(items)
    refreshed_metrics: list[dict[str, Any]] = []
    for row in definitions[:12]:
        if not isinstance(row, dict):
            continue
        metric = dict(row)
        metric_id = str(metric.get("id") or metric.get("label") or "total_impact")
        unit = str(metric.get("unit") or "")
        value, severity = _metric_value(metric_id, unit, stats)
        metric["id"] = metric_id
        metric.setdefault("label", metric_id.replace("_", " ").title())
        metric["value"] = value
        metric["severity"] = severity
        metric.setdefault("explanation", "Generated from current active workstream case metadata.")
        refreshed_metrics.append(metric)

    lens["metrics"] = refreshed_metrics
    lens["generated_at"] = datetime.now(timezone.utc).isoformat()
    lens["generated_by"] = "workstream_business_lens.refresh_business_lens"
    ws["business_lens"] = lens
    ws.pop("business_metrics", None)
    return ws
