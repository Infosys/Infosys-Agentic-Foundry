"""
Hooks document validator for the UI Hooks Builder.

The runtime parser ``HookRunner._validate_external_manifest`` validates a single
hook entry but returns ``None`` (and only logs a warning) on any error — it does
not surface per-field messages. This module mirrors the same rules but collects
human-readable, per-entry error/warning messages so the Security Console can show
authors exactly what is wrong before a ``config.yaml`` write.

This is validation only — it never executes a hook command. The single source of
truth for the accepted field set / enums remains ``hook_runner`` (imported below);
keep the two in sync.
"""

from __future__ import annotations

import re
from typing import Any

from iaf_agent_skills.hook_runner import (
    ALLOWED_HOOK_EVENTS,
    ALLOWED_HOOK_MODES,
    ALLOWED_FAIL_POLICIES,
    ALLOWED_ON_BLOCK_ACTIONS,
    MAX_HOOK_OUTPUT_CHARS,
)

# hook_id / id regex — mirrors hook_runner._validate_external_manifest.
_HOOK_ID_RE = re.compile(r"^[A-Za-z0-9_.:-]{1,128}$")

# Soft denylist — patterns that produce a non-blocking WARNING only. Admin-authored
# server commands are the design intent, so we never refuse the save for these.
_DANGEROUS_PATTERNS: list[tuple[str, str]] = [
    (r"rm\s+-rf\s+/(?:\s|$)", "destructive recursive delete of '/'"),
    (r":\s*\(\s*\)\s*\{", "shell fork-bomb pattern"),
    (r"\bcurl\b[^\n|]*\|\s*(?:ba)?sh\b", "pipes a download straight into a shell"),
    (r">\s*/dev/sd", "writes directly to a block device"),
    (r"\bmkfs\b", "formats a filesystem"),
    (r"\bdd\b[^\n]*\bif=", "raw disk copy (dd)"),
]


def _is_str_or_list(value: Any) -> bool:
    return isinstance(value, str) or (
        isinstance(value, list) and all(isinstance(v, str) for v in value)
    )


def validate_hooks_doc(hooks: Any) -> dict[str, Any]:
    """Validate a ``hooks:`` document (``{event: [entry, ...]}``).

    Returns ``{"valid": bool, "errors": [str], "warnings": [str], "hook_count": int}``.
    ``valid`` is False only when there are structural/field errors; denylist hits
    and uncompilable matchers are warnings and never set ``valid=False``.
    """
    errors: list[str] = []
    warnings: list[str] = []
    hook_count = 0

    if not isinstance(hooks, dict):
        return {
            "valid": False,
            "errors": ["Top-level 'hooks' must be a mapping of event name -> list of hooks."],
            "warnings": [],
            "hook_count": 0,
        }

    for event_name, entries in hooks.items():
        if event_name not in ALLOWED_HOOK_EVENTS:
            errors.append(
                f"{event_name}: unknown event. Allowed: {', '.join(sorted(ALLOWED_HOOK_EVENTS))}"
            )
            # Still try to validate the entries' shapes below if it's a list.
        if not isinstance(entries, list):
            errors.append(f"{event_name}: value must be a list of hook entries.")
            continue

        for idx, entry in enumerate(entries):
            prefix = f"{event_name}[{idx}]"
            hook_count += 1

            if not isinstance(entry, dict):
                errors.append(f"{prefix}: each hook entry must be a mapping.")
                continue

            # command (required)
            command = entry.get("command")
            if not isinstance(command, str) or not command.strip():
                errors.append(f"{prefix}: 'command' is required and must be a non-empty string.")
            else:
                for pat, why in _DANGEROUS_PATTERNS:
                    if re.search(pat, command):
                        warnings.append(f"{prefix}: command looks risky — {why}. It will still be saved.")
                        break

            # hook_id / id (optional)
            hid = entry.get("hook_id", entry.get("id"))
            if hid is not None:
                if not isinstance(hid, str) or not _HOOK_ID_RE.match(hid):
                    errors.append(
                        f"{prefix}: 'hook_id' must match [A-Za-z0-9_.:-] (1-128 chars)."
                    )

            # priority (optional)
            if "priority" in entry:
                pr = entry["priority"]
                if not isinstance(pr, int) or isinstance(pr, bool) or pr < 0:
                    errors.append(f"{prefix}: 'priority' must be an integer >= 0.")

            # mode (optional)
            if "mode" in entry and entry["mode"] not in ALLOWED_HOOK_MODES:
                errors.append(
                    f"{prefix}: 'mode' must be one of {', '.join(sorted(ALLOWED_HOOK_MODES))}."
                )

            # fail_policy (optional)
            if "fail_policy" in entry and entry["fail_policy"] not in ALLOWED_FAIL_POLICIES:
                errors.append(
                    f"{prefix}: 'fail_policy' must be one of {', '.join(sorted(ALLOWED_FAIL_POLICIES))}."
                )

            # on_block (optional)
            if "on_block" in entry and entry["on_block"] not in ALLOWED_ON_BLOCK_ACTIONS:
                errors.append(
                    f"{prefix}: 'on_block' must be one of {', '.join(sorted(ALLOWED_ON_BLOCK_ACTIONS))}."
                )

            # skills / permissions (optional) — str or list[str]
            if "skills" in entry and not _is_str_or_list(entry["skills"]):
                errors.append(f"{prefix}: 'skills' must be a string or a list of strings.")
            if "permissions" in entry and not _is_str_or_list(entry["permissions"]):
                errors.append(f"{prefix}: 'permissions' must be a string or a list of strings.")

            # input_schema / output_schema (optional) — dict
            for schema_key in ("input_schema", "output_schema"):
                if schema_key in entry and not isinstance(entry[schema_key], dict):
                    errors.append(f"{prefix}: '{schema_key}' must be a mapping.")

            # approval (optional) — dict with conservative field checks
            if "approval" in entry:
                approval = entry["approval"]
                if not isinstance(approval, dict):
                    errors.append(f"{prefix}: 'approval' must be a mapping.")
                else:
                    if "options" in approval and not _is_str_or_list(approval["options"]):
                        errors.append(f"{prefix}: 'approval.options' must be a string or a list of strings.")
                    if "sla_minutes" in approval:
                        sla = approval["sla_minutes"]
                        if not isinstance(sla, int) or isinstance(sla, bool) or sla <= 0:
                            errors.append(f"{prefix}: 'approval.sla_minutes' must be an integer > 0.")
                    if "context" in approval and not isinstance(approval["context"], dict):
                        errors.append(f"{prefix}: 'approval.context' must be a mapping.")

            # timeout_seconds (optional)
            if "timeout_seconds" in entry:
                ts = entry["timeout_seconds"]
                if not isinstance(ts, int) or isinstance(ts, bool) or ts <= 0:
                    errors.append(f"{prefix}: 'timeout_seconds' must be an integer > 0.")

            # max_output_chars (optional)
            if "max_output_chars" in entry:
                moc = entry["max_output_chars"]
                if (
                    not isinstance(moc, int)
                    or isinstance(moc, bool)
                    or moc < 1
                    or moc > MAX_HOOK_OUTPUT_CHARS
                ):
                    errors.append(
                        f"{prefix}: 'max_output_chars' must be an integer between 1 and {MAX_HOOK_OUTPUT_CHARS}."
                    )

            # block_on_nonzero (optional) — bool
            if "block_on_nonzero" in entry and not isinstance(entry["block_on_nonzero"], bool):
                errors.append(f"{prefix}: 'block_on_nonzero' must be true or false.")

            # matcher (optional) — must compile as a regex (warning, since default is ".*")
            if "matcher" in entry:
                matcher = entry["matcher"]
                if not isinstance(matcher, str):
                    errors.append(f"{prefix}: 'matcher' must be a string.")
                else:
                    try:
                        re.compile(matcher)
                    except re.error as exc:
                        warnings.append(
                            f"{prefix}: 'matcher' is not a valid regex ({exc}); it will fall back to '.*' at runtime."
                        )

    return {
        "valid": not errors,
        "errors": errors,
        "warnings": warnings,
        "hook_count": hook_count,
    }
