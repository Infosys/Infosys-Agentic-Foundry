"""Validation for ids that become filesystem path segments (tenant, agent, user)."""

from __future__ import annotations

import re

from .safe_path import SecurityError

_PATH_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.@+#-]{0,127}$")


def validate_path_id(value, label: str = "id") -> str:
    """Return `value` if it is a safe single path segment, else raise SecurityError."""
    if not isinstance(value, str) or not _PATH_ID_RE.fullmatch(value) or ".." in value:
        raise SecurityError(f"Error [INVALID_ID]: invalid {label}")
    return value
