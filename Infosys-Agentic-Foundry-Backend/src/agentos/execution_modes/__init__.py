# © 2024-25 Infosys Limited, Bangalore, India. All Rights Reserved.
"""
Execution Modes Package — Modular execution engines for skill agents.

Architecture (production-ready):
─────────────────────────────────────────────────────────────────────
User-Facing Modes (4 simple choices):
  react       — LLM-driven ReAct loop (default)
  workflow    — Deterministic sequential steps
  parallel   — DAG-based concurrent execution
  supervisor — Meta-agent delegates to worker skills

Auto-Detected Modes (runtime, zero user config):
  orchestrator — ALL workers in parallel + synthesis (multi_step queries)
  planned      — DAG planner for multi-domain queries

Internal Strategies (available explicitly):
  map_reduce  — Split → parallel map → LLM combine
  chain       — Sequential LLM pipeline
  iterative   — Generate → judge → refine loop
  consensus   — Parallel voters → judge merges

Production Hardening:
  Smart Router — Auto-detects optimal mode from query signals
  Rate Limiter — Sliding-window per user
  Audit Trail — JSONL with rotation
  Sandbox     — Timeout + resource gating
─────────────────────────────────────────────────────────────────────

Usage:
    from src.agentos.execution_modes import route_execution, validate_execution_mode
    from src.agentos.execution_modes import SmartRouter, ExecutionMode, ExecutionResult
"""

# Base models and enums
from .base import (
    ExecutionMode,
    StepDefinition,
    StepResult,
    SupervisorStep,
    SupervisorDecision,
    MapReduceResult,
    ConsensusVote,
    resolve_template,
)

# Individual engines
from .workflow import SkillWorkflowEngine
from .parallel import SkillParallelEngine
from .supervisor import SkillSupervisorEngine
from .orchestrator import SkillOrchestratorEngine
from .map_reduce import SkillMapReduceEngine
from .chain import SkillChainEngine
from .iterative import SkillIterativeEngine
from .consensus import SkillConsensusEngine
from .planned import SkillPlannedEngine, ExecutionPlan, PlanStep

# Smart Router (auto-detection)
from .smart_router import SmartRouter, RoutingDecision

# Production Hardening
from .hardening import (
    RateLimiter,
    RateLimitExceeded,
    ExecutionAudit,
    ExecutionSandbox,
    SandboxConfig,
    get_rate_limiter,
    get_audit,
    get_sandbox,
)

# Router
from .router import route_execution, validate_execution_mode, ExecutionResult

__all__ = [
    # Enums & Models
    "ExecutionMode",
    "StepDefinition",
    "StepResult",
    "SupervisorStep",
    "SupervisorDecision",
    "MapReduceResult",
    "ConsensusVote",
    "resolve_template",
    # Engines
    "SkillWorkflowEngine",
    "SkillParallelEngine",
    "SkillSupervisorEngine",
    "SkillOrchestratorEngine",
    "SkillMapReduceEngine",
    "SkillChainEngine",
    "SkillIterativeEngine",
    "SkillConsensusEngine",
    "SkillPlannedEngine",
    "ExecutionPlan",
    "PlanStep",
    # Smart Router
    "SmartRouter",
    "RoutingDecision",
    # Production Hardening
    "RateLimiter",
    "RateLimitExceeded",
    "ExecutionAudit",
    "ExecutionSandbox",
    "SandboxConfig",
    "get_rate_limiter",
    "get_audit",
    "get_sandbox",
    # Router
    "route_execution",
    "validate_execution_mode",
    "ExecutionResult",
]
