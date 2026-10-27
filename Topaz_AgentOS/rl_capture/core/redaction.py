"""Structure-preserving redaction for RL/eval capture payloads.

Two responsibilities:

1. **Capture-time** redaction of obvious credentials on individual
   values (used by the capture adapters).
2. **Export-time** PII redaction gate (Phase 2): every row leaving the store
   via :func:`redact_rows` is scrubbed for structured PII — emails, phone
   numbers, IBANs, Luhn-valid card numbers, and US SSNs — in addition to
   sensitive data. The gate reports which categories were hit so the caller can record
   and display a redaction summary.

Free-text personal names are **not** auto-detected (that needs NER and would
destroy training utility with false positives); reviewers remain responsible
for name-level sign-off before sharing a dataset externally.
"""

from __future__ import annotations

import copy
import re
from collections import Counter
from dataclasses import dataclass, field
from typing import Any


DEFAULT_POLICY_VERSION = "rl_redaction_v2"
REDACTED_VALUE = "[REDACTED]"

# NOTE: ``token\b`` matches secrets but not training fields like prompt_tokens/output_token_ids, which must stay unredacted.
SECRET_KEY_RE = re.compile(
    r"(api[_-]?key|token\b|password|passwd|secret|authorization|client[_-]?secret|"
    r"connection[_-]?string|credential|bearer|basic)",
    re.IGNORECASE,
)

EMAIL_RE = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
BEARER_RE = re.compile(r"\bBearer\s+[A-Za-z0-9._~+/=-]+", re.IGNORECASE)
BASIC_RE = re.compile(r"\bBasic\s+[A-Za-z0-9+/=]+", re.IGNORECASE)
# IBAN: 2 letters + 2 check digits + up to 30 alphanumerics.
IBAN_RE = re.compile(r"\b[A-Z]{2}\d{2}[A-Z0-9]{11,30}\b")
# US SSN: 3-2-4 grouped digits.
SSN_RE = re.compile(r"\b\d{3}-\d{2}-\d{4}\b")
# Candidate card number: 13-19 digits, optionally spaced/dashed (Luhn-checked).
# Separators only appear between digits so a trailing space is never consumed.
CARD_RE = re.compile(r"\b\d(?:[ -]?\d){12,18}\b")
# Phone: require separators/parentheses/leading + so plain 6-digit finance
# figures (amounts, invoice ids) are NOT mistaken for phone numbers.
PHONE_RE = re.compile(
    r"(?<![\w.])(?:\+\d{1,3}[\s.-]?)?(?:\(\d{2,4}\)[\s.-]?|\d{2,4}[\s.-])\d{3,4}[\s.-]\d{3,4}(?:[\s.-]\d{2,4})?(?![\w.])"
)


@dataclass
class RedactionResult:
    value: Any
    redacted: bool = False
    redacted_fields: list[str] = field(default_factory=list)
    categories: dict[str, int] = field(default_factory=dict)
    policy_version: str = DEFAULT_POLICY_VERSION


def _luhn_ok(candidate: str) -> bool:
    digits = [int(c) for c in candidate if c.isdigit()]
    if not (13 <= len(digits) <= 19):
        return False
    checksum = 0
    parity = len(digits) % 2
    for idx, digit in enumerate(digits):
        if idx % 2 == parity:
            digit *= 2
            if digit > 9:
                digit -= 9
        checksum += digit
    return checksum % 10 == 0


def _redact_text(text: str, counts: Counter) -> str:
    """Apply value-based redaction rules to a string, updating category counts."""
    out = text

    def _count_sub(pattern: re.Pattern, replacement: str, category: str, value: str) -> str:
        new_value, n = pattern.subn(replacement, value)
        if n:
            counts[category] += n
        return new_value

    # Credentials first (most sensitive), then structured PII.
    out = _count_sub(BEARER_RE, "Bearer [REDACTED]", "secret", out)
    out = _count_sub(BASIC_RE, "Basic [REDACTED]", "secret", out)
    out = _count_sub(EMAIL_RE, "[REDACTED_EMAIL]", "email", out)

    # Cards need a Luhn check to avoid nuking long non-card digit strings.
    def _card_repl(match: re.Match) -> str:
        if _luhn_ok(match.group(0)):
            counts["credit_card"] += 1
            return "[REDACTED_CC]"
        return match.group(0)

    out = CARD_RE.sub(_card_repl, out)

    out = _count_sub(IBAN_RE, "[REDACTED_IBAN]", "iban", out)
    out = _count_sub(SSN_RE, "[REDACTED_SSN]", "ssn", out)
    out = _count_sub(PHONE_RE, "[REDACTED_PHONE]", "phone", out)
    return out


def scan_pii(text: str) -> set[str]:
    """Return the set of PII/sensitive-data categories detectable in ``text``.

    Used as the residual-PII gate after redaction (should be empty).
    """
    found: set[str] = set()
    if BEARER_RE.search(text) or BASIC_RE.search(text):
        found.add("secret")
    if EMAIL_RE.search(text):
        found.add("email")
    for match in CARD_RE.finditer(text):
        if _luhn_ok(match.group(0)):
            found.add("credit_card")
            break
    if IBAN_RE.search(text):
        found.add("iban")
    if SSN_RE.search(text):
        found.add("ssn")
    if PHONE_RE.search(text):
        found.add("phone")
    return found


def redact_value(value: Any, *, path: str = "") -> RedactionResult:
    """Return a redacted copy of a nested JSON-like value."""
    fields: list[str] = []
    counts: Counter = Counter()

    def _redact(item: Any, current_path: str) -> Any:
        if isinstance(item, dict):
            out: dict[str, Any] = {}
            for key, child in item.items():
                key_text = str(key)
                child_path = f"{current_path}.{key_text}" if current_path else key_text
                if SECRET_KEY_RE.search(key_text):
                    fields.append(child_path)
                    counts["secret"] += 1
                    out[key] = REDACTED_VALUE
                else:
                    out[key] = _redact(child, child_path)
            return out
        if isinstance(item, list):
            return [_redact(child, f"{current_path}[{idx}]") for idx, child in enumerate(item)]
        if isinstance(item, tuple):
            return tuple(_redact(child, f"{current_path}[{idx}]") for idx, child in enumerate(item))
        if isinstance(item, str):
            redacted = _redact_text(item, counts)
            if redacted != item:
                fields.append(current_path or "$")
            return redacted
        return item

    original = copy.deepcopy(value)
    redacted_value = _redact(original, path)
    return RedactionResult(
        value=redacted_value,
        redacted=bool(fields),
        redacted_fields=fields,
        categories=dict(counts),
        policy_version=DEFAULT_POLICY_VERSION,
    )


def redact_rows(rows: list[dict]) -> tuple[list[dict], dict]:
    """Redact every export row, returning ``(redacted_rows, summary)``.

    ``summary`` records how many rows/fields were touched and a per-category
    breakdown, plus the policy version — suitable for storing on the export
    record and displaying in the UI.
    """
    redacted_rows: list[dict] = []
    categories: Counter = Counter()
    residual: set[str] = set()
    rows_redacted = 0
    fields_redacted = 0
    for row in rows:
        result = redact_value(row)
        redacted_rows.append(result.value)
        if result.redacted:
            rows_redacted += 1
            fields_redacted += len(result.redacted_fields)
            for cat, n in result.categories.items():
                categories[cat] += n
        # Residual-PII gate: re-scan the redacted row so a miss (nested
        # encoding, HTML entity, etc.) is surfaced rather than shipped silently.
        residual |= scan_pii(str(result.value))
    summary = {
        "policy_version": DEFAULT_POLICY_VERSION,
        "rows_total": len(rows),
        "rows_redacted": rows_redacted,
        "fields_redacted": fields_redacted,
        "categories": dict(categories),
        "residual_pii": sorted(residual),
        # Free-text personal names are NOT auto-detected (needs NER). A human
        # reviewer must sign off before sharing a dataset externally.
        "names_review_required": True,
    }
    return redacted_rows, summary
