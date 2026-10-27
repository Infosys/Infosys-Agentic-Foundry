"""
Observers — Pydantic contracts for the subsystem.

These models are the wire + config contract shared by the router, service,
store, triggers, policy, runtime, and sidecar. Kept pydantic-v1/v2 compatible
(plain fields + defaults, str-enums) exactly like cc_queue/models.py.
"""

from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel


class TrustTier(str, Enum):
    """How much an observer is trusted to trigger action.

    observe_only — may only trigger `notify`; everything else denied.
    recommend    — may trigger skills, but always via human approval.
    auto_act     — low-risk skills may run auto; others forced to human.
    supervised   — may trigger any permitted skill, but always human approval.
    """
    observe_only = "observe_only"
    recommend = "recommend"
    auto_act = "auto_act"
    supervised = "supervised"


class WatchType(str, Enum):
    folder = "folder"
    db = "db"
    api = "api"


class Access(str, Enum):
    ro = "ro"          # read-only folder
    select = "select"  # read-only DB
    get = "get"        # read-only API


class Approval(str, Enum):
    human = "human"
    auto = "auto"


class RuntimeMode(str, Enum):
    dev = "dev"              # Mac / no-Docker — scope NOT enforced (warned)
    container = "container"  # Linux + Docker — read-only mount fence


class WatchScope(BaseModel):
    """One source an observer may read. Compiled to a read-only mount in
    container runtime; stated in the prompt in dev runtime."""
    type: WatchType
    path: Optional[str] = None   # folder path
    dsn: Optional[str] = None    # database dsn
    url: Optional[str] = None    # api url
    access: Access = Access.ro


class TriggerRule(BaseModel):
    """A hard, deterministic rule evaluated by the TriggerEngine.

    Threshold form: set field/op/value (e.g. field='amount', op='>=', value=50000).
    Pattern form:   set pattern (substring/regex matched against the event text).
    """
    name: str = ""
    # threshold condition
    field: Optional[str] = None
    op: Optional[str] = None          # >= > <= < == != (numeric or string)
    value: Optional[Any] = None
    # pattern condition
    pattern: Optional[str] = None     # regex, matched against the event's text
    # action
    skill: str
    task_template: str = ""           # may reference {field}, {value}, {matched}
    approval: Approval = Approval.human
    cooldown_seconds: int = 3600


class ObserverSpec(BaseModel):
    """Full definition of one observer. Loaded from YAML (slice) or DB (later)."""
    name: str
    tenant_id: str = "company"
    agent_id: str = "enterprise_agent"
    user_id: str = "observer"
    focus: str = ""
    vibe: str = ""
    trust_tier: TrustTier = TrustTier.recommend
    allowed_skills: List[str] = []         # explicit allowlist (empty = triggers' skills)
    watch: List[WatchScope] = []
    triggers: List[TriggerRule] = []
    runtime_mode: RuntimeMode = RuntimeMode.dev
    model: Optional[str] = None            # SHELLM_MODEL override
    llm_api_url: Optional[str] = None      # LLM_API_URL override


class ActRequest(BaseModel):
    """A request from an observer (sidecar or Headlong skill) to run an
    AgentOS skill. The ONLY write path into the platform."""
    observer: str                          # observer name (provenance)
    skill: str
    task: str
    context: Dict[str, Any] = {}
    evidence: List[str] = []               # trajectory refs / log lines
    approval: Approval = Approval.human
    # tenant routing (defaulted from the observer spec server-side)
    tenant_id: str = "company"
    agent_id: str = "enterprise_agent"
    user_id: str = "observer"


class ActResponse(BaseModel):
    status: str                            # "pending_approval" | "executed" | "denied"
    approval_id: Optional[str] = None
    message: str = ""
