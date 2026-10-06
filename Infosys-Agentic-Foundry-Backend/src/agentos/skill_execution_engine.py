# © 2024-25 Infosys Limited, Bangalore, India. All Rights Reserved.
"""
Skill Execution Engines — Backward-compatibility shim.

This module re-exports all symbols from the new modular execution_modes package.
New code should import directly from src.agentos.execution_modes instead.

The actual implementations now live in:
    src/agentos/execution_modes/
        base.py        -> Shared models, enums, utilities
        workflow.py    -> SkillWorkflowEngine
        parallel.py    -> SkillParallelEngine
        supervisor.py  -> SkillSupervisorEngine
        map_reduce.py  -> SkillMapReduceEngine
        chain.py       -> SkillChainEngine
        iterative.py   -> SkillIterativeEngine
        consensus.py   -> SkillConsensusEngine
        planned.py     -> SkillPlannedEngine
        router.py      -> route_execution() dispatcher
"""

# Re-export everything for backward compatibility
from src.agentos.execution_modes import (  # noqa: F401
    # Enums & Models
    ExecutionMode,
    StepDefinition,
    StepResult,
    SupervisorStep,
    SupervisorDecision,
    MapReduceResult,
    ConsensusVote,
    resolve_template,
    # Engines
    SkillWorkflowEngine,
    SkillParallelEngine,
    SkillSupervisorEngine,
    SkillMapReduceEngine,
    SkillChainEngine,
    SkillIterativeEngine,
    SkillConsensusEngine,
    SkillPlannedEngine,
    ExecutionPlan,
    PlanStep,
    # Router
    route_execution,
    validate_execution_mode,
    ExecutionResult,
)

__all__ = [
    "ExecutionMode",
    "StepDefinition",
    "StepResult",
    "SupervisorStep",
    "SupervisorDecision",
    "MapReduceResult",
    "ConsensusVote",
    "resolve_template",
    "SkillWorkflowEngine",
    "SkillParallelEngine",
    "SkillSupervisorEngine",
    "SkillMapReduceEngine",
    "SkillChainEngine",
    "SkillIterativeEngine",
    "SkillConsensusEngine",
    "SkillPlannedEngine",
    "ExecutionPlan",
    "PlanStep",
    "route_execution",
    "validate_execution_mode",
    "ExecutionResult",
]
