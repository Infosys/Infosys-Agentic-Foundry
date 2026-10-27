"""Skill descriptor contract shared by AgentOS packages and adapters."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class Skill:
    """Loaded skill metadata and executable prompt body.

    This intentionally mirrors the historical ``iaf_agent_skills.loader.Skill``
    surface so partner registries can return one stable descriptor type without
    depending on the full engine package.
    """

    name: str
    version: str = "1.0"
    description: str = ""
    files: dict[str, str] = field(default_factory=dict)
    knowledge: list[str] = field(default_factory=list)
    user_data: dict[str, str] = field(default_factory=dict)
    mcp_tools: list[dict[str, Any]] = field(default_factory=list)
    mcp_connections: list[dict[str, Any]] = field(default_factory=list)
    connections: list[dict[str, Any]] = field(default_factory=list)  # data connections (database/api/erp)
    tools: list[str] = field(default_factory=list)
    business_context: dict[str, Any] = field(default_factory=dict)
    approval_rules: dict[str, Any] = field(default_factory=dict)
    evidence_highlights: dict[str, Any] = field(default_factory=dict)
    sql_mode: str = "read_only"
    execution_mode: str = "react"
    react_runtime: str = ""
    profile: str = ""  # Harness execution profile name; "" → resolves to the agent/tenant default
    context_file: str = ""  # Per-skill context doc auto-injected when this skill is active ("" = none)
    steps: list[dict[str, Any]] = field(default_factory=list)
    worker_skills: list[dict[str, str]] = field(default_factory=list)
    max_steps: int = 10
    graph_ref: str = ""  # For execution_mode 'graph': path to a stored process-graph YAML ("" = none)
    body: str = ""
    path: Path | None = None
