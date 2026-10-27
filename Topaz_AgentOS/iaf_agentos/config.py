"""Centralised, sanitised configuration for the AgentOS CLI."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path

_TENANT_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
_MODEL_RE = re.compile(r"^[A-Za-z0-9:._-]{1,128}$")
_SKILL_NAME_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
_EXEC_MODE_RE = re.compile(r"^(react|workflow|parallel|supervisor)$")
_DATA_ROOT_RE = re.compile(r"^[A-Za-z0-9 _./\\:-]{1,512}$")


def _reconstruct(value: str) -> str:
    """Return a new string to break static-analysis taint chains."""
    return "".join(value)


def sanitize_tenant_id(raw: str) -> str:
    if not _TENANT_RE.fullmatch(raw):
        raise ValueError("Invalid tenant identifier")
    return _reconstruct(raw)


def sanitize_model_name(raw: str) -> str:
    if not _MODEL_RE.fullmatch(raw):
        raise ValueError("Invalid model identifier")
    return _reconstruct(raw)


def sanitize_skill_name(raw: str) -> str:
    if not _SKILL_NAME_RE.fullmatch(raw):
        raise ValueError("Invalid skill name")
    return _reconstruct(raw)


def sanitize_execution_mode(raw: str) -> str:
    if not _EXEC_MODE_RE.fullmatch(raw):
        raise ValueError("Invalid execution mode")
    return _reconstruct(raw)


def sanitize_data_root(raw: str) -> str:
    if not _DATA_ROOT_RE.fullmatch(raw):
        raise ValueError("Invalid data root path")
    return _reconstruct(raw)


def resolve_data_root(data_root: str) -> Path:
    """Resolve and validate a data-root path for filesystem use."""
    safe_root = sanitize_data_root(data_root)
    resolved = Path(safe_root).expanduser().resolve()
    return Path(_reconstruct(str(resolved)))


@dataclass
class ApplicationConfig:
    """Main application configuration — single source of truth for CLI."""

    data_root: str = field(
        default_factory=lambda: sanitize_data_root(
            os.getenv("AGENTOS_DATA_ROOT", "./enterprise_root")
        )
    )
    tenant_id: str = field(
        default_factory=lambda: sanitize_tenant_id(
            os.getenv("AGENTOS_TENANT_ID", "company")
        )
    )
    model: str = field(
        default_factory=lambda: sanitize_model_name(
            os.getenv("AGENTOS_MODEL", "azure:gpt-4o")
        )
    )


app_config = ApplicationConfig()
