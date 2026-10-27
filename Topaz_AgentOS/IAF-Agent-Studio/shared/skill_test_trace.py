"""Trace/evidence extraction for the Skill Builder inline test panel (TC-132).

The inline test previously returned only ``status`` + ``duration_ms``. This pure
helper turns an agent's post-run decision context and evidence bundle into a
compact, JSON-safe summary (trace id, per-span tool calls, token count, evidence
presence) so the UI can surface spans/tokens/evidence or deep-link to the Trace
Explorer entry for that specific run.

Kept dependency-free and pure so it can be unit-tested without a live agent.
"""
from __future__ import annotations

from typing import Any, Optional

# Maximum tool-call spans echoed back inline (matches the chat reasoning panel).
_MAX_SPANS = 20


def _coerce_int(value: Any) -> Optional[int]:
    try:
        if value is None:
            return None
        return int(value)
    except (TypeError, ValueError):
        return None


def _extract_tokens(decision_context: dict) -> Optional[int]:
    """Best-effort total-token count from the decision context.

    Different runtimes stash usage in different places; probe the known ones and
    return ``None`` when no usage was recorded rather than guessing.
    """
    for container_key in ("outcome", "context_used", "usage"):
        container = decision_context.get(container_key)
        if isinstance(container, dict):
            for token_key in ("total_tokens", "tokens", "token_count"):
                tokens = _coerce_int(container.get(token_key))
                if tokens is not None:
                    return tokens
    return _coerce_int(decision_context.get("total_tokens"))


def build_test_trace_evidence(
    decision_context: Optional[dict],
    evidence_bundle: Optional[dict] = None,
) -> Optional[dict]:
    """Build a compact trace/evidence summary for an inline skill test run.

    Args:
        decision_context: The agent's ``_last_decision_context`` (or ``None``).
        evidence_bundle: The agent's ``_evidence_bundle`` (or ``None``).

    Returns:
        A JSON-safe dict with ``trace_id``, ``span_count``, ``spans``,
        ``tokens`` and ``has_evidence``; or ``None`` when there is nothing to
        surface (no decision context and no evidence).
    """
    dc = decision_context if isinstance(decision_context, dict) else {}
    bundle = evidence_bundle if isinstance(evidence_bundle, dict) else {}

    trace_id = str(dc.get("trace_id") or bundle.get("trace_id") or "") or None

    spans = []
    for tc in (dc.get("tool_calls") or [])[:_MAX_SPANS]:
        if not isinstance(tc, dict):
            continue
        spans.append({
            "tool": tc.get("tool", "unknown"),
            "duration_ms": _coerce_int(tc.get("duration_ms")) or 0,
            "has_error": bool(tc.get("has_error", False)),
        })

    has_evidence = bool(bundle.get("documents") or bundle.get("evidence_items"))

    # Nothing meaningful to surface — let the caller omit the field entirely.
    if not trace_id and not spans and not has_evidence:
        return None

    return {
        "trace_id": trace_id,
        "span_count": len(spans),
        "spans": spans,
        "tokens": _extract_tokens(dc),
        "has_evidence": has_evidence,
    }
