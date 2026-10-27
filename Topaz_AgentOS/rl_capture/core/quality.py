"""Dataset quality and export safety checks."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable

import json
import re

from rl_capture.core.redaction import BASIC_RE, BEARER_RE


@dataclass
class QualityIssue:
    code: str
    message: str
    row_id: str = ""


@dataclass
class QualityReport:
    ok: bool
    issues: list[QualityIssue] = field(default_factory=list)


# Secret-looking assignment: sensitive key, then : or =, then a captured value (after an optional Bearer/Basic).
SECRET_ASSIGNMENT_RE = re.compile(
    r"\b(?:api[_-]?key|client[_-]?secret|authorization|password|passwd|secret|token)\b"
    r"\s*[:=]\s*(?:bearer\s+|basic\s+)?(?P<val>\S+)",
    re.IGNORECASE,
)

# Safe values: already-redacted markers and documentation placeholders, which must not fail the export secret gate.
_SAFE_SECRET_VALUE_RE = re.compile(
    r"^(?:"
    r"\[redacted[^\]]*\]"               # [REDACTED], [REDACTED_EMAIL], ...
    r"|\$\{?[A-Za-z_][A-Za-z0-9_]*\}?"  # $VAR, ${VAR}, $CRED_NAME_FIELD
    r"|<[^>\s]+>"                       # <your-token>
    r"|\{\{[^}\s]+\}\}"                # {{token}}
    r"|%\([^)\s]+\)s"                  # %(token)s
    r"|%[A-Za-z_][A-Za-z0-9_]*%"       # %TOKEN%
    r"|your[_-][A-Za-z0-9_-]+"          # your_api_key, your-token
    r"|placeholder|changeme|x{3,}|\*{3,}"
    r")",
    re.IGNORECASE,
)


def _is_safe_secret_value(value: str) -> bool:
    """True when a matched secret-assignment value is a placeholder or already redacted."""
    # fullmatch, not match: a safe-looking *prefix* must not exempt the whole value, or
    # `api_key=placeholder-live-secret` would slip a real credential past the export gate.
    return bool(_SAFE_SECRET_VALUE_RE.fullmatch(value.strip().strip("\"'`")))


def validate_export_rows(rows: Iterable[dict], *, require_text: bool = True) -> QualityReport:
    issues: list[QualityIssue] = []
    for idx, row in enumerate(rows):
        row_id = str(row.get("id") or row.get("trajectory_id") or idx)
        text = _row_text(row)
        if require_text and not text.strip():
            issues.append(QualityIssue("empty_text", "Export row has no usable text", row_id))
        if _looks_unredacted(text):
            issues.append(QualityIssue("possible_secret", "Export row may contain an unredacted secret", row_id))
        if {"chosen", "rejected"}.issubset(row) and (not row.get("chosen") or not row.get("rejected")):
            issues.append(QualityIssue("empty_preference_side", "DPO row has empty chosen or rejected value", row_id))
        if {"chosen", "rejected"}.issubset(row) and str(row.get("chosen") or "").strip() == str(row.get("rejected") or "").strip():
            issues.append(QualityIssue("equal_preference_side", "DPO row has identical chosen and rejected value", row_id))
    return QualityReport(ok=not issues, issues=issues)


def assert_quality(report: QualityReport) -> None:
    if report.ok:
        return
    summary = "; ".join(f"{issue.code}:{issue.row_id}" for issue in report.issues[:10])
    raise ValueError(f"Dataset quality check failed: {summary}")


def _row_text(row: dict) -> str:
    parts: list[str] = []
    for key in ("prompt", "completion", "chosen", "rejected", "input", "text"):
        value = row.get(key)
        if value:
            parts.append(str(value))
    for key in ("messages", "actual_output"):
        value = row.get(key)
        if isinstance(value, list):
            for item in value:
                if not isinstance(item, dict):
                    continue
                parts.append(str(item.get("content") or ""))
                # Tool-call arguments can carry credentials; include them so _looks_unredacted sees them.
                if item.get("tool_calls"):
                    parts.append(json.dumps(item["tool_calls"], ensure_ascii=False, default=str))
    # Tool schemas emitted alongside tool-calling SFT rows (names/descriptions/params).
    tools = row.get("tools")
    if tools:
        parts.append(json.dumps(tools, ensure_ascii=False, default=str))
    return "\n".join(parts)


def _looks_unredacted(text: str) -> bool:
    # A raw Bearer/Basic token fails unless its own value is a placeholder/redacted marker (judged per token, not per row).
    for pattern in (BEARER_RE, BASIC_RE):
        for match in pattern.finditer(text):
            parts = match.group(0).split(None, 1)   # ["Bearer", "<token>"]
            token = parts[1] if len(parts) > 1 else parts[0]
            if not _is_safe_secret_value(token):
                return True
    # Otherwise flag only secret assignments whose value is a real credential,
    # not a placeholder or an already-redacted marker.
    return any(
        not _is_safe_secret_value(match.group("val"))
        for match in SECRET_ASSIGNMENT_RE.finditer(text)
    )
