# © 2024-25 Infosys Limited, Bangalore, India. All Rights Reserved.
"""
Shared data models, enums, and utilities for all execution modes.
"""

import re
from typing import List, Dict, Any, Optional, Callable, Tuple
from dataclasses import dataclass, field
from enum import Enum

try:
    from telemetry_wrapper import logger as log
except ImportError:
    import logging
    log = logging.getLogger(__name__)


# ============================================================================
# Enums
# ============================================================================

class ExecutionMode(str, Enum):
    """Supported execution modes for skills."""
    REACT = "react"
    WORKFLOW = "workflow"
    PARALLEL = "parallel"
    SUPERVISOR = "supervisor"
    ORCHESTRATOR = "orchestrator"  # Auto-detected: parallel workers + synthesis
    MAP_REDUCE = "map_reduce"
    CHAIN = "chain"
    ITERATIVE = "iterative"
    CONSENSUS = "consensus"
    PLANNED = "planned"            # Auto-detected: multi-domain DAG planner


# ============================================================================
# Data Models
# ============================================================================

@dataclass
class StepDefinition:
    """
    Parsed step from SKILL.md frontmatter.

    Actions:
        shell      → run_shell_command tool
        database_query → database_query_tool
        skill      → invoke a sub-skill via skill_runner
        condition  → conditional branch (if/contains/then/else)
    """
    name: str
    action: str                            # shell | database_query | skill | condition
    params: Dict[str, Any] = field(default_factory=dict)
    depends_on: List[str] = field(default_factory=list)
    # Condition-specific fields
    condition_if: str = ""
    condition_contains: str = ""
    condition_then: str = ""
    condition_else: str = ""
    # Skill-action fields
    skill_name: str = ""
    task_template: str = ""

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "StepDefinition":
        """Parse a step definition dictionary from YAML frontmatter."""
        return cls(
            name=d["name"],
            action=d.get("action", "shell"),
            params=d.get("params", {}),
            depends_on=d.get("depends_on", []),
            condition_if=d.get("if", ""),
            condition_contains=d.get("contains", ""),
            condition_then=d.get("then", ""),
            condition_else=d.get("else", ""),
            skill_name=d.get("skill", ""),
            task_template=d.get("task", ""),
        )


@dataclass
class StepResult:
    """Result of executing a single step."""
    name: str
    success: bool
    output: str = ""
    error: str = ""
    duration_ms: int = 0
    skipped: bool = False


@dataclass
class SupervisorStep:
    """One completed step in a supervisor execution."""
    step_num: int
    skill_name: str
    task: str
    result: str
    success: bool
    duration_ms: int


@dataclass
class SupervisorDecision:
    """Parsed manager LLM decision for one supervisor iteration."""
    action: str          # "call_skill" | "synthesize" | "fail"
    skill_name: str = ""
    task: str = ""
    reason: str = ""


@dataclass
class MapReduceResult:
    """Result from one map-phase worker."""
    worker_name: str
    task: str
    output: str
    success: bool
    duration_ms: int = 0


@dataclass
class ConsensusVote:
    """One worker's independent response in the consensus process."""
    worker_name: str
    instruction: str
    response: str
    success: bool
    duration_ms: int = 0


# ============================================================================
# Template Resolution Utility
# ============================================================================

def resolve_template(template: str, results: Dict[str, StepResult]) -> str:
    """
    Resolve {{step_name.output}} placeholders in a template string.

    Examples:
        "{{fetch.output}}" → result from "fetch" step
        "Combine: {{a.output}} and {{b.output}}" → multi-step interpolation
    """
    pattern = r"\{\{(\w+)\.output\}\}"

    def replacer(match):
        ref_name = match.group(1)
        if ref_name in results:
            return results[ref_name].output or ""
        return match.group(0)  # Leave unresolved if not found

    return re.sub(pattern, replacer, template)
