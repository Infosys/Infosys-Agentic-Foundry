"""Standardized hook context construction.

The builder adds Phase 2 correlation fields while preserving legacy keys used by
existing internal hooks and external hook environment variables.
"""

from __future__ import annotations

import json
import re
from typing import Any, Mapping


MAX_PREVIEW_CHARS = 4096
REDACTED = "[REDACTED]"
_VIRTUAL_PATH_RE = re.compile(r"(?<!\w)(/(?:local|shared|me)/[^\s'\";,)]*)")
_SENSITIVE_KEY_RE = re.compile(
    r"(password|passwd|pwd|secret|token|api[_-]?key|access[_-]?key|authorization|credential|private[_-]?key)",
    re.IGNORECASE,
)
_SECRET_KEY_VALUE_RE = re.compile(
    r"(?P<prefix>['\"]?(?:password|passwd|pwd|secret|token|api[_-]?key|access[_-]?key|authorization|credential|private[_-]?key)['\"]?\s*:\s*)"
    r"(?P<quote>['\"]?)"
    r"(?P<value>[^'\",}\]\n\r]+)"
    r"(?P=quote)",
    re.IGNORECASE,
)
_AUTH_TEXT_RE = re.compile(r"\b(Bearer|Basic)\s+[^\s'\";,}]+", re.IGNORECASE)
_ASSIGNMENT_SECRET_RE = re.compile(r"\b(token|api[_-]?key|password|secret)=([^\s'\";&]+)", re.IGNORECASE)

_TOOL_SUBTYPE_PATTERNS = (
    ("get_credential", re.compile(r"^\s*get_credential\b", re.IGNORECASE)),
    ("curl", re.compile(r"^\s*curl\b", re.IGNORECASE)),
    ("wget", re.compile(r"^\s*wget\b", re.IGNORECASE)),
    ("kubectl", re.compile(r"^\s*kubectl\b", re.IGNORECASE)),
    ("ssh", re.compile(r"^\s*ssh\b", re.IGNORECASE)),
    ("scp", re.compile(r"^\s*scp\b", re.IGNORECASE)),
    ("rsync", re.compile(r"^\s*rsync\b", re.IGNORECASE)),
)


def _detect_tool_subtype(tool_name: str, tool_input: Any) -> str:
    """Return a coarse subtype label for shell-like tool calls.

    Returns "" when no specific subtype applies. The label lets observer
    hooks filter on, e.g., outbound HTTP without parsing the command
    themselves. Only inspects the ``command`` field of dict inputs (and
    strings); never the file body or arbitrary payload fields.
    """
    if (tool_name or "").lower() != "shell":
        return ""
    command = None
    if isinstance(tool_input, Mapping):
        command = tool_input.get("command")
    elif isinstance(tool_input, str):
        command = tool_input
    if not isinstance(command, str) or not command.strip():
        return ""
    for label, pattern in _TOOL_SUBTYPE_PATTERNS:
        if pattern.search(command):
            return label
    return ""


def build_hook_context(
    *,
    event: str,
    session_ctx: Mapping[str, Any] | None = None,
    tool_name: str = "",
    tool_input: Any = None,
    tool_output: str = "",
    response: str = "",
    step_result: str = "",
    step_success: bool | None = None,
    step_duration_ms: int = 0,
    step_trace_id: str = "",
    error_msg: str = "",
    decision: str = "",
    duration_ms: int | None = None,
    credential_bearing: bool = False,
) -> dict[str, Any]:
    """Build a normalized hook context with compatibility fields.

    When ``credential_bearing=True`` the builder additionally:
      * Adds ``"current_skill"`` to ``context_missing`` if the skill identity is empty.
      * Sets ``enforce_fail_closed=True`` so the HookRunner can short-circuit the
        operation to a deny before any hook fires. This is the Batch 1 fail-closed
        enforcement for credential-bearing tool calls without a propagated skill
        identity — see plan ``Batch 1 — Critical security/correctness`` and the
        non-negotiable constraint #6 in ``luminous-yawning-stardust.md``.
    """
    base = dict(session_ctx or {})
    trace_id = str(base.get("trace_id") or "")
    current_skill = str(base.get("current_skill") or base.get("skill_name") or "")
    missing = []
    if not trace_id:
        missing.append("trace_id")
    enforce_fail_closed = bool(base.get("enforce_fail_closed", False))
    if credential_bearing and not current_skill:
        missing.append("current_skill")
        enforce_fail_closed = True

    ctx = {
        **base,
        "hook_event": event,
        "trace_id": trace_id,
        "parent_trace_id": str(base.get("parent_trace_id") or trace_id),
        "session_id": str(base.get("session_id") or ""),
        "run_id": str(base.get("run_id") or ""),
        "queue_item_id": str(base.get("queue_item_id") or base.get("queue_id") or ""),
        "cron_job_id": str(base.get("cron_job_id") or base.get("job_id") or ""),
        "tenant_id": str(base.get("tenant_id") or ""),
        "user_id": str(base.get("user_id") or ""),
        "agent_id": str(base.get("agent_id") or ""),
        "skill_name": str(base.get("skill_name") or ""),
        "current_skill": current_skill,
        "entrypoint": str(base.get("entrypoint") or base.get("source") or ""),
        "execution_mode": str(base.get("execution_mode") or ""),
        "tool_name": tool_name or "",
        "tool_input": tool_input,
        "tool_output": tool_output or "",
        "response": response or base.get("response", ""),
        "input_preview": str(base.get("input_preview") or _preview(tool_input))[:MAX_PREVIEW_CHARS],
        "output_preview": str(base.get("output_preview") or _preview(tool_output))[:MAX_PREVIEW_CHARS],
        "response_preview": str(base.get("response_preview") or _preview(response or base.get("response", "")))[:MAX_PREVIEW_CHARS],
        "evidence_trace_id": str(base.get("evidence_trace_id") or ""),
        "decision": decision or str(base.get("decision") or ""),
        "duration_ms": duration_ms if duration_ms is not None else base.get("duration_ms", ""),
        "error": error_msg or str(base.get("error") or base.get("error_msg") or ""),
        "step_result": step_result,
        "step_success": step_success,
        "step_duration_ms": step_duration_ms,
        "step_trace_id": step_trace_id,
        "error_msg": error_msg or str(base.get("error_msg") or ""),
        "virtual_paths": _extract_virtual_paths(tool_input),
        "context_missing": missing,
        "credential_bearing": bool(credential_bearing or base.get("credential_bearing", False)),
        "enforce_fail_closed": enforce_fail_closed,
        "tool_subtype": _detect_tool_subtype(tool_name, tool_input),
    }
    return ctx


def _preview(value: Any) -> str:
    if value is None:
        return ""
    value = redact_hook_value(value)
    if isinstance(value, str):
        text = value
    else:
        try:
            text = json.dumps(value, sort_keys=True, default=str)
        except Exception:
            text = str(value)
    return text[:MAX_PREVIEW_CHARS]


def redact_hook_value(value: Any) -> Any:
    """Return a redacted copy suitable for external hook payloads and previews."""
    if value is None:
        return None
    if isinstance(value, Mapping):
        redacted = {}
        for key, nested in value.items():
            key_text = str(key)
            if _SENSITIVE_KEY_RE.search(key_text):
                redacted[key] = REDACTED
            else:
                redacted[key] = redact_hook_value(nested)
        return redacted
    if isinstance(value, list):
        return [redact_hook_value(item) for item in value]
    if isinstance(value, tuple):
        return tuple(redact_hook_value(item) for item in value)
    if isinstance(value, set):
        return [redact_hook_value(item) for item in value]
    if isinstance(value, str):
        text = value
        text = _SECRET_KEY_VALUE_RE.sub(
            lambda match: f"{match.group('prefix')}{match.group('quote')}{REDACTED}{match.group('quote')}",
            text,
        )
        text = _AUTH_TEXT_RE.sub(lambda match: f"{match.group(1)} {REDACTED}", text)
        text = _ASSIGNMENT_SECRET_RE.sub(lambda match: f"{match.group(1)}={REDACTED}", text)
        return text
    return value


def _extract_virtual_paths(value: Any) -> list[str]:
    paths: list[str] = []

    def add(path: str) -> None:
        cleaned = path.strip().rstrip(".,;:)")
        if cleaned and cleaned not in paths:
            paths.append(cleaned)

    def visit(item: Any) -> None:
        if isinstance(item, Mapping):
            for key, nested in item.items():
                if key in {"path", "filename", "file", "filepath"} and isinstance(nested, str):
                    for match in _VIRTUAL_PATH_RE.findall(nested):
                        add(match)
                else:
                    visit(nested)
        elif isinstance(item, (list, tuple, set)):
            for nested in item:
                visit(nested)
        elif isinstance(item, str):
            for match in _VIRTUAL_PATH_RE.findall(item):
                add(match)

    visit(value)
    return paths