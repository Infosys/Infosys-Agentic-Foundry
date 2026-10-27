"""
IAF Agent Studio — Pydantic Models

All request/response models for API endpoints.
Extracted from server.py for clean separation.
"""

import os
from typing import Any, Optional, List, Union, Literal
from pydantic import BaseModel, field_validator



class ChatMessage(BaseModel):
    content: str
    tenant_id: str = "company"
    agent_id: str = "enterprise_agent"
    user_id: str = "demo"
    skill_name: Optional[str] = None
    session_id: Optional[str] = None  # Optional chat session scope, used by AskTwin per page
    source_page: Optional[str] = None  # AskTwin/source UI route, e.g. "dashboard_v2"
    page_context: Optional[dict[str, Any]] = None  # Whitelisted page state for contextual help
    human_approval: bool = True  # UI toggle for ask-first mode
    render_ui: bool = False  # If True, include UI generation instructions (browser requests)
    light_mode: bool = False  # If True, skip memory context + async learning (faster responses)
    knowledge_mode: Optional[str] = None  # Knowledge retrieval mode: "scan", "semantic", or "hybrid"
    profile: Optional[str] = None  # Harness execution profile name (None → agent/tenant default)
    plan_requested: bool = False  # UI toggle to explicitly request DAG planner
    force_plan: bool = False      # Plan Mode toggle — same as WS force_plan


class KernelApprovalRequest(BaseModel):
    """Handle user approval/rejection of pending action."""
    approved: bool
    tenant_id: str = "company"
    agent_id: str = "enterprise_agent"
    user_id: str = "demo"
    session_id: str = ""         # Session ID for per-session agent lookup (must match WS session)
    edited_content: str = ""     # User-edited content/command from preview textarea
    approval_id: Optional[str] = None  # durable approval id — resolve cold when warm instance is gone (B4)



class FileOperation(BaseModel):
    path: str
    content: Optional[str] = None
    tenant_id: str = "company"
    agent_id: str = "enterprise_agent"
    user_id: str = "demo"



class CronJobCreate(BaseModel):
    """Create a scheduled cron job."""
    name: str
    skill_name: str
    task: str  # The prompt/task to send to the skill
    cron: str = "0 * * * *"  # Default: every hour
    description: str = ""
    tenant_id: str = "company"
    agent_id: str = "enterprise_agent"
    user_id: str = "scheduler"
    max_runtime_seconds: int = 300
    enabled: bool = True
    tags: List[str] = []
    # Retry policy (optional)
    retry_max_retries: int = 0
    retry_initial_delay: int = 60
    retry_backoff_multiplier: float = 2.0


class CronJobUpdate(BaseModel):
    """Update an existing cron job."""
    name: Optional[str] = None
    skill_name: Optional[str] = None
    task: Optional[str] = None
    cron: Optional[str] = None
    description: Optional[str] = None
    max_runtime_seconds: Optional[int] = None
    enabled: Optional[bool] = None
    tags: Optional[List[str]] = None



class ToolScript(BaseModel):
    """A bundled Python tool script to include in a skill."""
    filename: str  # e.g. "calculate_late_fee.py"
    content: str   # Full Python source code with TOOL_SPEC


class ConnectionDef(BaseModel):
    """Skill-level connection definition (database, API, or ERP)."""
    type: str        # "database" | "api" | "erp"
    name: str        # Human-readable label, e.g. "Invoice DB"
    config: dict = {}  # Type-specific config (engine, host, base_url, etc.)


class SkillCreate(BaseModel):
    """Skill creation/update model with multi-agentic support."""
    name: str
    description: str
    prompt: str = ""
    version: str = "1.0"
    execution_mode: str = "react"  # react, workflow, parallel, supervisor, orchestrator, rlm, graph
    profile: str = ""  # Harness execution profile (empty → agent/tenant default)
    keywords: List[str] = []
    steps: List[dict] = []  # for workflow/parallel
    worker_skills: List[dict] = []  # for supervisor
    tools: List[str] = ["shell"]  # shell, run_sql_query
    business_context: Optional[dict] = None  # domain, process, activities
    tool_scripts: List[ToolScript] = []  # Bundled Python tool scripts
    connections: List[ConnectionDef] = []  # Skill-level data connections
    mcp_connections: List[dict] = []    # Skill-level MCP servers (stdio/http/sse/registry)
    mcp_tools: List[str] = []           # Optional allowlist filter for discovered MCP tools
    context_file: Optional[str] = None  # e.g. "shared/contexts/invoice_context.md"
    category: Optional[str] = None      # e.g. "operations", "platform", "personal"
    sql_mode: str = "read_only"         # run_sql_query write control: read_only | read_write
    approval_rules: Optional[dict] = None  # HITL policy (thresholds/conditions → urgency/SLA)
    knowledge: List[str] = []           # /shared/knowledge/<bundle> paths this skill may read
    max_steps: Optional[int] = None     # orchestrator mode: max LLM steps before forced stop
    graph_ref: str = ""                 # graph mode: filename of the process-graph YAML (default graph.yaml)
    graph_yaml: str = ""                # graph mode: the process-graph v1 YAML content (written to graph.yaml)

    @field_validator("graph_ref")
    @classmethod
    def _graph_ref_is_bare_filename(cls, v: str) -> str:
        # graph_ref is joined to the skill dir on write; reject path separators/traversal
        # so it can only ever name a file inside the skill directory (default graph.yaml).
        if v and (v in (".", "..") or "/" in v or "\\" in v or v != os.path.basename(v)):
            raise ValueError("graph_ref must be a bare filename (no path separators or traversal)")
        return v
    save_mode: Literal["current", "new"] = "current"  # "current" = overwrite active version; "new" = save as a new (inactive) version
    version_note: Optional[str] = None  # optional change note recorded on the version


class ToolScriptValidateRequest(BaseModel):
    """Validate a Python tool script's syntax and TOOL_SPEC."""
    filename: str
    content: str


class ToolScriptTestRunRequest(BaseModel):
    """Test-run a Python tool script with sample JSON input."""
    content: str
    test_input: dict = {}


class SkillTestRequest(BaseModel):
    """Test a skill with a prompt."""
    prompt: str
    tenant_id: str = "company"
    agent_id: str = "enterprise_agent"
    user_id: str = "skill_tester"


class SkillCloneRequest(BaseModel):
    """Clone a skill to a new name."""
    new_name: str


class SkillStatusUpdate(BaseModel):
    """Update skill lifecycle status."""
    status: str  # draft, active, deprecated



class ThumbsFeedback(BaseModel):
    """User thumbs up/down on an assistant message."""
    message_index: int  # Index of the message in the current conversation
    direction: str  # "up" or "down"
    query: str = ""  # The user query that produced this response
    response_snippet: str = ""  # First ~200 chars of the response
    skill: Optional[str] = None
    rl_trajectory_id: Optional[str] = None
    rl_model_call_id: Optional[str] = None
    request_trace_id: Optional[str] = None
    tenant_id: str = "company"
    agent_id: str = "enterprise_agent"
    user_id: str = "demo"


class LearnRequest(BaseModel):
    """User explicitly teaches the agent via /learn command or learning card."""
    summary: str  # What to learn
    knowledge_type: str = "rule"  # rule/exception/preference/workaround/pattern/correction/alias/fact
    skill: Optional[str] = None  # None = global
    tags: List[str] = []
    applies_when: str = ""  # Natural language condition
    status: str = "confirmed"       # "confirmed" | "pending_review" — for Review Later
    source: Optional[str] = None   # Override default (e.g. "llm_suggested" when review_later)
    entity_keys: Optional[List[str]] = None  # Structured entity refs e.g. ["vendor:global_freight"]
    source_context_file: Optional[str] = None  # Context .md loaded when learning was captured
    tenant_id: str = "company"
    agent_id: str = "enterprise_agent"
    user_id: str = "demo"


class KnowledgeAction(BaseModel):
    """Confirm or reject a pending knowledge record."""
    knowledge_id: str
    tenant_id: str = "company"
    agent_id: str = "enterprise_agent"
    user_id: str = "demo"
    # Optional: absolute path of the context .md file to append the knowledge to.
    # Provided by the dashboard after the user confirms (or overrides) the suggestion.
    target_file: Optional[str] = None
    # new_file_type: entity -> memory/entities/<name>.md, org -> memory/org/<name>.md.
    new_file_name: Optional[str] = None
    new_file_type: Optional[str] = None   # "entity" | "org"
    # Set only by the dashboard's explicit advanced-target confirmation.
    # Direct API callers cannot write into SKILL.md accidentally.
    allow_skill_definition: bool = False
    # Distinguishes an intentional status-only confirmation from a missing
    # target. Status-only confirmation never auto-routes to a bundle/file.
    skip_file_write: bool = False


class KnowledgeEdit(BaseModel):
    """Edit a knowledge record in place (preserves status)."""
    knowledge_id: str
    summary: Optional[str] = None
    knowledge_type: Optional[str] = None
    applies_when: Optional[str] = None
    tags: Optional[List[str]] = None
    entity_keys: Optional[List[str]] = None  # Editable entity references
    written_to: Optional[str] = None          # Context .md file path (empty string = clear)
    tenant_id: str = "company"
    agent_id: str = "enterprise_agent"
    user_id: str = "demo"


class KnowledgeMerge(BaseModel):
    """Request body for merging duplicate knowledge records."""
    keep_id: str                           # ID of the record to keep
    archive_ids: List[str]                 # IDs of records to archive
    merged_summary: Optional[str] = None   # Optional improved summary for the winner
    tenant_id: str = "company"
    agent_id: str = "enterprise_agent"
    user_id: str = "demo"


class KnowledgeBulkAction(BaseModel):
    """Bulk confirm or reject multiple knowledge records."""
    knowledge_ids: List[str]               # IDs to confirm or reject
    tenant_id: str = "company"
    agent_id: str = "enterprise_agent"
    user_id: str = "demo"
    # Confirm each record and publish deterministic/high-confidence suggestions.
    # Records without a safe suggestion are confirmed status-only and reported.
    publish_to_suggested_file: bool = True


class BatchExtractRequest(BaseModel):
    """Trigger batch knowledge extraction from recent episodes."""
    hours_back: int = 24
    max_tokens_budget: int = 150_000
    skill: Optional[str] = None
    force_full: bool = False
    tenant_id: str = "company"
    agent_id: str = "enterprise_agent"
    user_id: str = "demo"



class AgentConfig(BaseModel):
    """Agent configuration model."""
    name: str
    description: str = ""
    skills_mode: str = "all"  # "all" | "allowlist" | "denylist"
    skills_list: List[str] = []  # allowed or denied skills
    tools_allowed: List[str] = ["fs", "shell", "write_file", "run_sql_query"]  # allowed tools
    mcp_connections: List[dict] = []  # Unified MCP connections (direct/registry)
    hooks: dict = {}  # Lifecycle hooks keyed by event (PreToolUse/PostToolUse/PostTurn/PostSampling)



class BatchRequest(BaseModel):
    """Single item in a batch."""
    content: str
    skill_name: Optional[str] = None
    item_id: Optional[str] = None  # Optional ID for tracking


class BatchJobRequest(BaseModel):
    """Batch job request with multiple items."""
    items: List[BatchRequest]
    tenant_id: str = "company"
    agent_id: str = "enterprise_agent"
    user_id: str = "batch"
    max_concurrent: int = 3  # How many to process in parallel
    human_approval: bool = False  # Batch jobs typically run unattended
    default_skill: Optional[str] = None  # Skip router if specified (faster!)



class EvolutionRequest(BaseModel):
    tier: Union[int, str] = 4
    days_back: int = 30
    lookback_hours: Optional[int] = None
    start_time: Optional[str] = None
    end_time: Optional[str] = None
    max_sessions: Optional[int] = None
    sources: Optional[List[str]] = None
    tenant_id: Optional[str] = None
    agent_id: Optional[str] = None
    skill_filter: Optional[str] = None
    context_pack_id: Optional[str] = None
    context_docs: Optional[List[str]] = None
    analysis_mode: Optional[str] = None
    confidence_threshold: Optional[float] = None
    dedup_threshold: Optional[float] = None
    force_fresh: bool = False  # If True, bypass LLM response cache (forces re-analysis)
