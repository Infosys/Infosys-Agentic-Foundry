# © 2024-25 Infosys Limited, Bangalore, India. All Rights Reserved.
"""
AgentOS API Schemas - Pydantic models for skill-based agent endpoints.
"""

import os
import re
from pathlib import PurePosixPath, PureWindowsPath
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from typing import List, Optional, Dict, Any


# ============================================================================
# Validation helpers
# ============================================================================

# Paths that are too broad — mounting a drive root, OS dirs, etc. is dangerous
_FORBIDDEN_ROOT_PATTERNS = re.compile(
    r"^[A-Za-z]:[/\\]?$"           # bare drive roots: "C:", "C:/", "C:\"
    r"|^/$"                         # Unix root
    r"|^/[A-Za-z]/?$"              # /C or /C/
    r"|[/\\](windows|system32|program\s?files|etc|boot|usr|bin|sbin|proc|sys|dev)[/\\]?$",
    re.IGNORECASE,
)


def _validate_path_no_traversal(path: str) -> str:
    """Reject path-traversal sequences (``..``) in any position."""
    normalised = path.replace("\\", "/")
    segments = normalised.split("/")
    if ".." in segments:
        raise ValueError(f"Path traversal ('..') is not allowed in paths: {path}")
    return path


def _validate_absolute_root_safe(root: str) -> str:
    """Reject roots that are too broad (drive roots, OS directories)."""
    normalised = root.strip().replace("\\", "/").rstrip("/")
    if not normalised:
        raise ValueError("Empty string is not a valid mount root")
    # Must have at least 2 path segments (e.g. "C:/Users" not just "C:")
    segments = [s for s in normalised.split("/") if s]
    # On Windows "C:/Users" → segments ["C:", "Users"] — need ≥2
    # A bare drive letter like "C:" has only 1 segment
    if len(segments) < 2:
        raise ValueError(
            f"Mount root '{root}' is too broad — must be at least 2 levels deep "
            f"(e.g. 'C:/data' not 'C:/')"
        )
    if _FORBIDDEN_ROOT_PATTERNS.search(normalised):
        raise ValueError(
            f"Mount root '{root}' matches a forbidden system path pattern"
        )
    return root


# ============================================================================
# Shared sub-models
# ============================================================================

class SkillDatabaseConnection(BaseModel):
    """
    A reference to a Data Connector connection that this skill needs.

    The UI sends this as a structured object — the backend embeds it into
    the SKILL.md YAML frontmatter so users never have to write YAML by hand.

    A single skill can declare **multiple** database connections (e.g. a
    read-only analytics DB *and* a read-write transactional DB).
    """
    connection_name: str = Field(
        ...,
        description="Name of the connection registered in the Data Connector (e.g. 'warehouse_db').",
    )
    sql_mode: str = Field(
        "read_only",
        description="Access level: 'read_only' (SELECT only) or 'read_write' (SELECT/INSERT/UPDATE/DELETE).",
    )


class WorkflowStepConfig(BaseModel):
    """
    A step definition for workflow/parallel/chain execution modes.

    Represents one unit of work in a multi-step pipeline.
    """
    name: str = Field(..., description="Unique step name (snake_case).")
    action: str = Field(
        "skill",
        description="Step action type: 'skill' (invoke sub-skill), 'shell' (run command), 'database_query' (run SQL), 'condition' (branch).",
    )
    params: Optional[Dict[str, Any]] = Field(None, description="Parameters for shell/database_query actions (e.g. {'command': '...'} or {'connection_name': '...', 'query': '...'}).")
    depends_on: Optional[List[str]] = Field([], description="List of step names this step depends on. Empty = independent (can run first/in parallel).")
    # Skill action fields
    skill: Optional[str] = Field(None, description="Skill name to invoke (when action='skill').")
    task: Optional[str] = Field(None, description="Task prompt to pass to the skill. Use {{step_name.result}} for dependency injection.")
    # Condition action fields
    condition_if: Optional[str] = Field(None, alias="if", description="Step name whose output to check (when action='condition').")
    condition_contains: Optional[str] = Field(None, alias="contains", description="Substring to check for in the step output.")
    condition_then: Optional[str] = Field(None, alias="then", description="Step name to jump to if condition is true.")
    condition_else: Optional[str] = Field(None, alias="else", description="Step name to jump to if condition is false.")

    model_config = ConfigDict(populate_by_name=True)


class WorkerSkillConfig(BaseModel):
    """
    A worker skill reference for supervisor/planned/map_reduce/consensus modes.

    Points to another skill that the orchestrator can delegate work to.
    """
    name: str = Field(..., description="Name of the worker skill (must exist in the same agent or be a valid skill name).")
    description: str = Field("", description="Short description of what this worker skill handles (helps the LLM decide when to delegate).")


# ============================================================================
# Skill-Based Agent Onboarding
# ============================================================================

class SkillDefinition(BaseModel):
    """
    A single skill definition to include in the agent.

    The UI can supply **either**:
      • ``skill_md_content`` — a pre-built SKILL.md string, **or**
      • the structured fields ``description``, ``keywords``, ``details``
        (and optionally ``execution_mode``, ``category``) and the backend
        will generate SKILL.md automatically.

    If both are supplied, ``skill_md_content`` takes precedence.
    """
    skill_name: str = Field(..., description="Unique name for the skill (snake_case).")

    # --- Option A: raw SKILL.md (advanced / power-user) ---
    skill_md_content: Optional[str] = Field(
        None,
        description="Full content of the SKILL.md file (YAML frontmatter + markdown body). Takes precedence over structured fields.",
    )

    # --- Option B: structured fields (UI-friendly) ---
    description: Optional[str] = Field(None, description="Short description of what this skill does.")
    keywords: Optional[List[Any]] = Field(None, description="Trigger keywords for routing. Accepts strings and numbers (e.g. ['leave', 404, 'error_500']).")
    details: Optional[str] = Field(None, description="Markdown body with detailed instructions / knowledge for the skill.")
    execution_mode: Optional[str] = Field("react", description="Execution mode: react, workflow, parallel, supervisor, map_reduce, chain, iterative, consensus, planned.")
    category: Optional[str] = Field("general", description="Skill category for grouping.")

    # --- Mode-specific structured fields ---
    steps: Optional[List[WorkflowStepConfig]] = Field(
        None,
        description=(
            "Step definitions for workflow, parallel, or chain modes. "
            "Each step defines an action (skill/shell/database_query/condition), "
            "dependencies, and parameters."
        ),
    )
    worker_skills: Optional[List[WorkerSkillConfig]] = Field(
        None,
        description=(
            "Worker skill references for supervisor, planned, map_reduce, or consensus modes. "
            "Each entry names a skill the orchestrator can delegate to."
        ),
    )
    max_steps: Optional[int] = Field(
        None,
        description="Maximum steps for supervisor/planned mode (default: 10). Caps how many delegation rounds the LLM can perform.",
    )
    max_iterations: Optional[int] = Field(
        None,
        description="Maximum iterations for iterative mode (default: 3).",
    )
    quality_threshold: Optional[int] = Field(
        None,
        description="Quality score threshold (1-10) for iterative mode (default: 7). Once the judge scores above this, iteration stops.",
    )
    evaluation_criteria: Optional[str] = Field(
        None,
        description="Evaluation criteria string for iterative mode (e.g. 'Completeness, accuracy, clarity').",
    )

    @field_validator("keywords", mode="before")
    @classmethod
    def coerce_keywords_to_str(cls, v):
        """Accept numeric keywords (e.g. 404, 500) and coerce to strings."""
        if v is None:
            return v
        return [str(item) for item in v]

    @model_validator(mode="after")
    def validate_mode_requirements(self):
        """Validate that mode-specific fields are provided when needed."""
        mode = self.execution_mode or "react"
        if mode in ("workflow", "parallel", "chain"):
            # steps required (unless user provides raw skill_md_content)
            if not self.steps and not self.skill_md_content:
                raise ValueError(
                    f"execution_mode='{mode}' requires 'steps' to be defined "
                    f"(or provide 'skill_md_content' with steps in YAML frontmatter)"
                )
        if mode in ("supervisor", "planned", "map_reduce", "consensus"):
            if not self.worker_skills and not self.skill_md_content:
                raise ValueError(
                    f"execution_mode='{mode}' requires 'worker_skills' to be defined "
                    f"(or provide 'skill_md_content' with worker_skills in YAML frontmatter)"
                )
        return self

    # --- Database connections (structured, UI-friendly) ---
    databases: Optional[List[SkillDatabaseConnection]] = Field(
        None,
        description=(
            "Data Connector connections this skill needs. "
            "Each entry is {connection_name, sql_mode}. "
            "The backend writes them into the SKILL.md frontmatter automatically."
        ),
    )

    # --- Skill-level lifecycle hooks ---
    hooks: Optional[Dict[str, Any]] = Field(
        None,
        description=(
            "Skill-level lifecycle hooks. Merged with agent-level hooks at runtime. "
            "Keys are event names (PreToolUse, PostToolUse, PreResponse, etc.). "
            "Values are lists of hook definitions. "
            "Example: {'PreToolUse': [{'command': 'python hooks/audit.py', 'matcher': '*'}]}"
        ),
    )

    # --- Companion files ---
    instructions_md_content: Optional[str] = Field(None, description="Optional INSTRUCTIONS.md content.")
    examples_md_content: Optional[str] = Field(None, description="Optional EXAMPLES.md content.")
    additional_files: Optional[Dict[str, str]] = Field(
        None,
        description="Map of filename → content for extra files (e.g. {'api.md': '...', 'credentials.md': '...'})."
    )


class AdditionalPathConfig(BaseModel):
    """
    An additional filesystem path to mount into the agent's virtual shell.

    The virtual mount name is auto-derived from the last segment of the path.
    For example, ``path="shared_data/reports"`` mounts as ``/reports/``.

    For absolute paths (e.g. ``C:/Users/me/Desktop/reports``), set
    ``absolute=True``.  The resolved path must fall under a root listed in
    ``allowed_absolute_mount_roots`` (agent-level).  If the server also sets
    the ``ALLOWED_ABSOLUTE_MOUNT_ROOTS`` environment variable, the agent-level
    roots must additionally be within those server-level roots.
    """
    path: str = Field(
        ...,
        description=(
            "Relative path (from the department root) to the folder to mount, "
            "OR an absolute path when 'absolute' is True. "
            "Example relative: 'shared_data/reports'. "
            "Example absolute: 'C:/Users/me/Desktop/reports'."
        ),
    )
    permission: str = Field(
        "read",
        description="Access level: 'read' (default, read-only) or 'read-write'.",
    )
    absolute: bool = Field(
        False,
        description=(
            "When True, 'path' is treated as an absolute filesystem path "
            "instead of relative to the department root. Requires "
            "allowed_absolute_mount_roots to be set on the agent."
        ),
    )

    @field_validator("path")
    @classmethod
    def validate_path(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("Path must not be empty")
        return _validate_path_no_traversal(v)

    @field_validator("permission")
    @classmethod
    def validate_permission(cls, v: str) -> str:
        allowed = {"read", "read-write"}
        v = v.strip().lower()
        if v not in allowed:
            raise ValueError(f"Permission must be one of {allowed}, got '{v}'")
        return v


class EnterpriseContextConfig(BaseModel):
    """Enterprise context configuration for the agent."""
    enterprise_context_md: Optional[str] = Field(None, description="Content for Enterprise_Context.md (company-wide context injected into every prompt).")
    skill_contexts: Optional[Dict[str, str]] = Field(None, description="Map of skill_name → context content for skill-specific context files.")
    policies: Optional[Dict[str, str]] = Field(None, description="Map of policy_name → policy content for business rules / policies.")
    entity_guide: Optional[str] = Field(None, description="Content for entity_guide.md (entity recognition rules).")


class SkillAgentOnboardingRequest(BaseModel):
    """Request to create a new skill-based agent."""
    agent_name: str = Field(..., description="Display name for the agent.")
    agent_description: str = Field("", description="Description of what this agent does.")
    model_name: str = Field("gpt-4o", description="LLM model name to use.")
    
    # Skills
    skills: List[SkillDefinition] = Field(..., description="List of skill definitions (SKILL.md files).", min_length=1)
    default_skill: str = Field("general", description="Default skill to use when no other skill matches.")

    # Database connections (agent-level, in addition to per-skill databases)
    db_connection_names: Optional[List[str]] = Field(
        None,
        description="Data Connector connection names for database access. Per-skill databases from SkillDefinition.databases are also collected automatically.",
    )
    
    # Enterprise Context (optional)
    enterprise_context: Optional[EnterpriseContextConfig] = Field(None, description="Enterprise context configuration.")

    # Additional filesystem paths (optional)
    additional_paths: Optional[List[AdditionalPathConfig]] = Field(
        None,
        description=(
            "Optional list of additional folder paths to mount into the agent's "
            "virtual shell. Each entry specifies a relative path (from the department "
            "root) and an optional permission ('read' or 'read-write', default 'read'). "
            "The virtual mount name is auto-derived from the last folder segment."
        ),
    )

    # Allowed absolute-mount roots (agent-level allowlist)
    allowed_absolute_mount_roots: Optional[List[str]] = Field(
        None,
        description=(
            "List of absolute directory roots this agent is permitted to mount "
            "when additional_paths entries have absolute=True. "
            "Each entry must be an absolute path (e.g. 'C:/Users/me/Desktop'). "
            "If the server sets ALLOWED_ABSOLUTE_MOUNT_ROOTS in .env, agent-level "
            "roots must also fall within those server-level roots."
        ),
    )

    # Lifecycle hooks configuration
    hooks: Optional[Dict[str, Any]] = Field(
        None,
        description=(
            "Lifecycle hooks configuration. "
            "Top-level keys: 'external' (shell command hooks), or Python event names "
            "(pre_hook, post_hook, pre_response, post_sampling, on_agent_start, on_agent_end, on_agent_error). "
            "\n\n"
            "External hooks (under 'external' key) are a list of dicts with fields:\n"
            "  - 'event': One of PreToolUse, PostToolUse, PreResponse, PostSampling, "
            "OnAgentStart, OnAgentEnd, OnAgentError\n"
            "  - 'command': Shell command to run (e.g. 'python /hooks/audit.py')\n"
            "  - 'hook_id': Alternatively, a Hook Repository ID (e.g. 'hk_abc123def456') "
            "that resolves to a stored hook script. Use 'command' OR 'hook_id', not both.\n"
            "  - 'matcher': Regex pattern matched against tool_name (default '.*', PreToolUse/PostToolUse only)\n"
            "  - 'block_on_nonzero': bool — if true, non-zero exit code blocks the operation\n"
            "  - 'timeout_seconds': int (default 10)\n"
            "  - 'skills': list of skill names to scope this hook to\n"
            "\n"
            "Exit code semantics: 0=ALLOW, 1=BLOCK (if block_on_nonzero), 2=APPROVAL_REQUIRED (triggers HITL).\n"
            "\n"
            "Example:\n"
            "  {'external': [\n"
            "    {'event': 'PreToolUse', 'hook_id': 'hk_abc123', 'matcher': 'run_shell_command', 'block_on_nonzero': true},\n"
            "    {'event': 'OnAgentStart', 'command': 'python /hooks/gate.py', 'block_on_nonzero': true}\n"
            "  ]}"
        ),
    )

    @field_validator("allowed_absolute_mount_roots")
    @classmethod
    def validate_abs_roots(cls, v: Optional[List[str]]) -> Optional[List[str]]:
        if v is None:
            return v
        validated = []
        for root in v:
            root = root.strip()
            if root:
                _validate_absolute_root_safe(root)
                validated.append(root)
        return validated or None

    @field_validator("agent_name")
    @classmethod
    def validate_agent_name(cls, v: str) -> str:
        v = v.strip()
        if not v or len(v) < 2:
            raise ValueError("Agent name must be at least 2 characters")
        if len(v) > 200:
            raise ValueError("Agent name must be at most 200 characters")
        return v


class SkillAgentFromFolderRequest(BaseModel):
    """Request to create a skill-based agent from a pre-existing folder structure."""
    agent_name: str = Field(..., description="Display name for the agent.")
    agent_description: str = Field("", description="Description of what this agent does.")
    model_name: str = Field("gpt-4o", description="LLM model name to use.")
    folder_path: str = Field(..., description="Path to the folder containing skills/, enterprise_context/, etc.")




    # Additional filesystem paths (optional)
    additional_paths: Optional[List[AdditionalPathConfig]] = Field(
        None,
        description=(
            "Optional list of additional folder paths to mount into the agent's "
            "virtual shell. Each entry specifies a relative path (from the department "
            "root) and an optional permission ('read' or 'read-write', default 'read'). "
            "The virtual mount name is auto-derived from the last folder segment."
        ),
    )

    # Allowed absolute-mount roots (agent-level allowlist)
    allowed_absolute_mount_roots: Optional[List[str]] = Field(
        None,
        description=(
            "List of absolute directory roots this agent is permitted to mount "
            "when additional_paths entries have absolute=True. "
            "If the server sets ALLOWED_ABSOLUTE_MOUNT_ROOTS in .env, agent-level "
            "roots must also fall within those server-level roots."
        ),
    )

    @field_validator("allowed_absolute_mount_roots")
    @classmethod
    def validate_abs_roots(cls, v: Optional[List[str]]) -> Optional[List[str]]:
        if v is None:
            return v
        validated = []
        for root in v:
            root = root.strip()
            if root:
                _validate_absolute_root_safe(root)
                validated.append(root)
        return validated or None


# ============================================================================
# Skill Management
# ============================================================================

class AddSkillRequest(BaseModel):
    """Request to add a skill to an existing agent."""
    skill: SkillDefinition = Field(..., description="The skill definition to add.")


class UpdateSkillRequest(BaseModel):
    """
    Request to update an existing skill.

    Like ``SkillDefinition``, the UI can send **either** ``skill_md_content``
    (raw SKILL.md) **or** the structured fields (``description``, ``keywords``,
    ``details``).  If structured fields are provided without ``skill_md_content``,
    the backend regenerates SKILL.md while preserving the skill name/version.
    """
    # --- Option A: raw SKILL.md ---
    skill_md_content: Optional[str] = Field(None, description="Updated SKILL.md content (takes precedence over structured fields).")

    # --- Option B: structured fields (UI-friendly) ---
    description: Optional[str] = Field(None, description="Updated short description.")
    keywords: Optional[List[Any]] = Field(None, description="Updated trigger keywords. Accepts strings and numbers.")
    details: Optional[str] = Field(None, description="Updated markdown body / instructions.")
    execution_mode: Optional[str] = Field(None, description="Updated execution mode: react, workflow, parallel, supervisor, map_reduce, chain, iterative, consensus, planned.")
    category: Optional[str] = Field(None, description="Updated category.")

    # --- Mode-specific structured fields ---
    steps: Optional[List[WorkflowStepConfig]] = Field(
        None,
        description="Updated step definitions for workflow/parallel/chain modes.",
    )
    worker_skills: Optional[List[WorkerSkillConfig]] = Field(
        None,
        description="Updated worker skill references for supervisor/planned/map_reduce/consensus modes.",
    )
    max_steps: Optional[int] = Field(None, description="Updated max steps for supervisor/planned mode.")
    max_iterations: Optional[int] = Field(None, description="Updated max iterations for iterative mode.")
    quality_threshold: Optional[int] = Field(None, description="Updated quality threshold for iterative mode.")
    evaluation_criteria: Optional[str] = Field(None, description="Updated evaluation criteria for iterative mode.")

    @field_validator("keywords", mode="before")
    @classmethod
    def coerce_keywords_to_str(cls, v):
        """Accept numeric keywords (e.g. 404, 500) and coerce to strings."""
        if v is None:
            return v
        return [str(item) for item in v]

    # --- Database connections (structured, UI-friendly) ---
    databases: Optional[List[SkillDatabaseConnection]] = Field(
        None,
        description=(
            "Updated Data Connector connections. "
            "Replaces the full list — send ALL connections, not just changed ones."
        ),
    )

    # --- Skill-level lifecycle hooks ---
    hooks: Optional[Dict[str, Any]] = Field(
        None,
        description=(
            "Updated skill-level lifecycle hooks. "
            "When provided, replaces the entire hooks section in SKILL.md. "
            "Pass an empty dict {} to remove all skill-level hooks."
        ),
    )

    # --- Companion files ---
    instructions_md_content: Optional[str] = Field(None, description="Updated INSTRUCTIONS.md content.")
    examples_md_content: Optional[str] = Field(None, description="Updated EXAMPLES.md content.")
    additional_files: Optional[Dict[str, str]] = Field(
        None,
        description="Map of filename → content for extra files to add/overwrite."
    )
    remove_files: Optional[List[str]] = Field(
        None,
        description="List of filenames to remove from the skill folder."
    )


class RemoveSkillRequest(BaseModel):
    """Request to remove a skill from an agent."""
    agent_id: str = Field(..., description="ID of the agent.")
    skill_name: str = Field(..., description="Name of the skill to remove.")


# ============================================================================
# Agent Update
# ============================================================================

class UpdateAgentRequest(BaseModel):
    """Request to update an existing skill-based agent's config and/or enterprise context."""
    agent_name: Optional[str] = Field(None, description="Updated display name.")
    agent_description: Optional[str] = Field(None, description="Updated description.")
    model_name: Optional[str] = Field(None, description="Updated LLM model name.")
    default_skill: Optional[str] = Field(None, description="Updated default skill name.")
    enterprise_context: Optional[EnterpriseContextConfig] = Field(
        None,
        description=(
            "Enterprise context update. If enterprise_context_md is provided and "
            "differs from the saved version it replaces the file; otherwise the "
            "Available Skills table is regenerated automatically."
        ),
    )
    additional_paths: Optional[List[AdditionalPathConfig]] = Field(
        None,
        description=(
            "Updated list of additional folder paths to mount. "
            "Replaces the entire previous list when provided. "
            "Pass an empty list to remove all additional paths."
        ),
    )
    allowed_absolute_mount_roots: Optional[List[str]] = Field(
        None,
        description=(
            "Updated list of absolute directory roots this agent is permitted "
            "to mount. Pass an empty list to remove all allowed roots."
        ),
    )
    hooks: Optional[Dict[str, Any]] = Field(
        None,
        description=(
            "Updated lifecycle hooks configuration. Keys are event names "
            "(PreToolUse, PostToolUse, PreResponse, PostSampling, etc.). "
            "Pass an empty dict {} to remove all hooks. "
            "When provided, replaces the entire hooks section."
        ),
    )

    @field_validator("allowed_absolute_mount_roots")
    @classmethod
    def validate_abs_roots(cls, v: Optional[List[str]]) -> Optional[List[str]]:
        if v is None:
            return v
        validated = []
        for root in v:
            root = root.strip()
            if root:
                _validate_absolute_root_safe(root)
                validated.append(root)
        return validated or None


# ============================================================================
# Enterprise Context Management
# ============================================================================

class UpdateEnterpriseContextRequest(BaseModel):
    """Request to update enterprise context for an agent."""
    enterprise_context_md: Optional[str] = Field(None, description="Updated Enterprise_Context.md content.")
    skill_contexts: Optional[Dict[str, str]] = Field(None, description="Updated skill-specific contexts.")
    policies: Optional[Dict[str, str]] = Field(None, description="Updated policies.")
    entity_guide: Optional[str] = Field(None, description="Updated entity guide.")


# ============================================================================
# Skill Chat (DEPRECATED — use standard POST /chat/inference endpoint)
# ============================================================================

# SkillChatRequest is no longer needed. Skill-based agents use the standard
# AgentInferenceRequest via POST /chat/inference, which provides proper SSE
# streaming, the same response format, and full pipeline integration.


# ============================================================================
# Audit & Monitoring
# ============================================================================

class AuditLogRequest(BaseModel):
    """Request for audit logs."""
    agent_id: Optional[str] = Field(None, description="Filter by agent ID.")
    date: Optional[str] = Field(None, description="Date filter (YYYY-MM-DD). Defaults to today.")
    limit: int = Field(100, description="Maximum entries to return.")
