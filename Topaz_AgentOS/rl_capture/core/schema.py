"""Framework-neutral capture schema for RL / preference / eval datasets.

The core records raw, fully attributed facts. It does not choose reward
magnitudes, channel weights, preference pair materialization, or training
format. Those choices belong in exporters.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field, is_dataclass
from enum import Enum
from typing import Any, Optional


SCHEMA_VERSION = "0.1.0"


class Role(str, Enum):
    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"
    TOOL = "tool"


class CaptureFidelity(str, Enum):
    TEXT_ONLY = "text_only"
    TOKEN_FAITHFUL = "token_faithful"
    REASONING_PARTIAL = "reasoning_partial"
    REASONING_FULL = "reasoning_full"


class RewardChannel(str, Enum):
    HUMAN_APPROVAL = "human_approval"
    HUMAN_EDIT = "human_edit"
    THUMBS = "thumbs"
    HOOK = "hook"
    MODEL_CALL_POLICY = "model_call_policy"
    WORKSTREAM = "workstream"
    QUEUE = "queue"
    CRITIQUE = "critique"
    VERIFIER = "verifier"
    EVALUATOR = "evaluator"
    SHADOW_EVAL = "shadow_eval"
    BUSINESS = "business"
    OPERATIONAL = "operational"


class TargetType(str, Enum):
    TRAJECTORY = "trajectory"
    STEP = "step"
    MODEL_CALL = "model_call"
    TOOL_CALL = "tool_call"
    OBSERVATION = "observation"


class StepKind(str, Enum):
    MODEL_CALL = "model_call"
    TOOL_CALL = "tool_call"
    OBSERVATION = "observation"
    ROUTER_DECISION = "router_decision"
    POLICY_CHECK = "policy_check"
    APPROVAL = "approval"


class PairProvenance(str, Enum):
    ON_POLICY_BOTH = "on_policy_both"
    OFF_POLICY = "off_policy"
    HUMAN_EDIT = "human_edit"
    SHADOW = "shadow"
    SYNTHETIC = "synthetic"


class CandidateKind(str, Enum):
    ORIGINAL = "original"
    REVISED = "revised"
    HUMAN_CORRECTION = "human_correction"
    REJECTED_ACTION = "rejected_action"
    APPROVED_ACTION = "approved_action"
    SHADOW = "shadow"
    SYNTHETIC = "synthetic"


@dataclass(frozen=True)
class PolicyRef:
    provider: str
    model: str
    model_version: Optional[str] = None
    decoding_id: Optional[str] = None
    params_hash: Optional[str] = None


@dataclass(frozen=True)
class SamplingParams:
    temperature: Optional[float] = None
    top_p: Optional[float] = None
    top_k: Optional[int] = None
    max_tokens: Optional[int] = None
    seed: Optional[int] = None
    stop: tuple[str, ...] = ()
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass
class RedactionMeta:
    redacted: bool = False
    redacted_fields: list[str] = field(default_factory=list)
    structure_preserved: bool = True
    policy_version: Optional[str] = None


@dataclass
class CaptureMeta:
    schema_version: str = SCHEMA_VERSION
    adapter_version: str = "agentpro:0.1.0"
    tenant_id: Optional[str] = None
    agent_id: Optional[str] = None
    source_event_id: Optional[str] = None
    source_trace_id: Optional[str] = None
    source_span_id: Optional[str] = None
    capture_time: Optional[str] = None
    retention_class: str = "standard"
    redaction_policy_id: Optional[str] = None


@dataclass
class ToolCallSpec:
    call_id: str
    name: str
    arguments: dict[str, Any] = field(default_factory=dict)


@dataclass
class Message:
    role: Role
    content: Optional[str] = None
    name: Optional[str] = None
    tool_calls: list[ToolCallSpec] = field(default_factory=list)
    tool_call_id: Optional[str] = None
    redaction: RedactionMeta = field(default_factory=RedactionMeta)


@dataclass
class ModelCall:
    id: str
    policy: PolicyRef
    input_messages: list[Message] = field(default_factory=list)
    output_messages: list[Message] = field(default_factory=list)
    sampling: SamplingParams = field(default_factory=SamplingParams)
    fidelity: CaptureFidelity = CaptureFidelity.TEXT_ONLY
    rendered_prompt_text: Optional[str] = None
    prompt_token_ids: Optional[list[int]] = None
    output_token_ids: Optional[list[int]] = None
    output_logprobs: Optional[list[float]] = None
    reasoning_ref: Optional[str] = None
    prompt_tokens: Optional[int] = None
    completion_tokens: Optional[int] = None
    cost_usd: Optional[float] = None
    latency_ms: Optional[int] = None
    redaction: RedactionMeta = field(default_factory=RedactionMeta)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: dict[str, Any] = field(default_factory=dict)
    output: Optional[Any] = None
    error: Optional[str] = None
    status: Optional[str] = None
    duration_ms: Optional[int] = None
    redaction: RedactionMeta = field(default_factory=RedactionMeta)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class Observation:
    id: str
    source: str
    payload: Optional[Any] = None
    error: Optional[str] = None
    redaction: RedactionMeta = field(default_factory=RedactionMeta)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class TrajectoryStep:
    id: str
    index: int
    kind: StepKind
    turn: Optional[int] = None
    parent_index: Optional[int] = None
    model_call_id: Optional[str] = None
    tool_call_id: Optional[str] = None
    observation_id: Optional[str] = None
    decision: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class Trajectory:
    id: str
    session_id: Optional[str] = None
    task: Optional[str] = None
    policy: Optional[PolicyRef] = None
    fidelity: CaptureFidelity = CaptureFidelity.TEXT_ONLY
    steps: list[TrajectoryStep] = field(default_factory=list)
    model_calls: list[ModelCall] = field(default_factory=list)
    tool_calls: list[ToolCall] = field(default_factory=list)
    observations: list[Observation] = field(default_factory=list)
    terminal_status: Optional[str] = None
    started_at: Optional[str] = None
    ended_at: Optional[str] = None
    adapter: Optional[str] = None
    tenant: Optional[str] = None
    capture: CaptureMeta = field(default_factory=CaptureMeta)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class TargetRef:
    trajectory_id: str
    target_type: TargetType
    target_id: Optional[str] = None
    turn: Optional[int] = None


@dataclass
class RewardEvent:
    id: str
    channel: RewardChannel
    target: TargetRef
    raw_label: str
    raw_value: Optional[float] = None
    confidence: Optional[float] = None
    judge_id: Optional[str] = None
    rubric: Optional[str] = None
    notes: Optional[str] = None
    created_at: Optional[str] = None
    capture: CaptureMeta = field(default_factory=CaptureMeta)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class PreferenceSignal:
    id: str
    context_ref: TargetRef
    preferred_ref: TargetRef
    dispreferred_ref: TargetRef
    provenance: PairProvenance
    channel: RewardChannel
    judge_id: Optional[str] = None
    margin: Optional[float] = None
    created_at: Optional[str] = None
    capture: CaptureMeta = field(default_factory=CaptureMeta)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class CandidateOutput:
    id: str
    trajectory_id: str
    kind: CandidateKind
    messages: list[Message] = field(default_factory=list)
    target: Optional[TargetRef] = None
    policy: Optional[PolicyRef] = None
    source: Optional[str] = None
    created_at: Optional[str] = None
    capture: CaptureMeta = field(default_factory=CaptureMeta)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class EvaluatorResult:
    id: str
    target: TargetRef
    rubric: str
    raw_scores: dict[str, Any] = field(default_factory=dict)
    judge_id: Optional[str] = None
    created_at: Optional[str] = None
    capture: CaptureMeta = field(default_factory=CaptureMeta)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class TraceValueAssessment:
    id: str
    trajectory_id: str
    input_hash: str
    rubric: str
    quality: dict[str, Any] = field(default_factory=dict)
    destinations: dict[str, float] = field(default_factory=dict)
    learning: str = ""
    rationale: dict[str, str] = field(default_factory=dict)
    risks: list[str] = field(default_factory=list)
    evidence_refs: list[dict[str, Any]] = field(default_factory=list)
    human_approval_required: bool = True
    created_at: Optional[str] = None
    capture: CaptureMeta = field(default_factory=CaptureMeta)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class TraceRouteDecision:
    id: str
    trajectory_id: str
    destination: str
    action: str
    status: str = "pending"
    assessment_id: Optional[str] = None
    reviewer: str = ""
    target_ref: Optional[str] = None
    reason: str = ""
    created_at: Optional[str] = None
    capture: CaptureMeta = field(default_factory=CaptureMeta)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class ShadowRun:
    id: str
    baseline_trajectory_id: str
    baseline_response_ref: TargetRef
    candidate_policy: PolicyRef
    candidate_messages: list[Message] = field(default_factory=list)
    candidate_token_ids: Optional[list[int]] = None
    comparison: Optional[PreferenceSignal] = None
    candidate_cost_usd: Optional[float] = None
    candidate_latency_ms: Optional[int] = None
    created_at: Optional[str] = None
    capture: CaptureMeta = field(default_factory=CaptureMeta)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class DatasetExport:
    id: str
    kind: str
    params: dict[str, Any] = field(default_factory=dict)
    reward_shaping_ref: Optional[str] = None
    file_path: Optional[str] = None
    checksum: Optional[str] = None
    row_count: Optional[int] = None
    created_at: Optional[str] = None
    capture: CaptureMeta = field(default_factory=CaptureMeta)
    metadata: dict[str, Any] = field(default_factory=dict)


def to_jsonable(value: Any) -> Any:
    """Convert schema objects to JSON-safe dictionaries."""
    if isinstance(value, Enum):
        return value.value
    if is_dataclass(value):
        return {key: to_jsonable(item) for key, item in asdict(value).items()}
    if isinstance(value, dict):
        return {str(key): to_jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [to_jsonable(item) for item in value]
    return value
