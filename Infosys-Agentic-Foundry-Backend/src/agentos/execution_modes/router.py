# © 2024-25 Infosys Limited, Bangalore, India. All Rights Reserved.
"""
Execution Mode Router — Routes skill execution to the appropriate engine.

This module serves as the single entry point for dispatching execution modes.
Instead of embedding all mode logic inside skill_agent_inference.py, this
router validates configuration and delegates to the correct engine.

Architecture (production-ready, inspired by agent_os kernel):
  ─────────────────────────────────────────────────────────────────────
  User-Facing Modes (4 simple choices):
    1. react       — LLM-driven ReAct loop (default)
    2. workflow    — Deterministic sequential steps
    3. parallel   — DAG-based concurrent execution
    4. supervisor — Meta-agent delegates to worker skills

  Auto-Detected Modes (runtime, zero user config):
    5. orchestrator — ALL workers in parallel + synthesis (multi_step)
    6. planned      — DAG planner for multi-domain queries

  Internal Strategies (available but usually auto-selected):
    7. map_reduce  — Split → parallel map → LLM combine
    8. chain       — Sequential LLM pipeline
    9. iterative   — Generate → judge → refine loop
    10. consensus  — Parallel voters → judge merges

  Production Hardening:
    - Rate limiting (sliding window per user)
    - Execution audit trail (JSONL with rotation)
    - Sandbox (timeout + resource gating)
  ─────────────────────────────────────────────────────────────────────
"""

import time
from typing import Any, Dict, List, Optional, Callable, Tuple

from .base import (
    ExecutionMode, StepDefinition, StepResult,
    SupervisorStep, MapReduceResult, ConsensusVote, log,
)
from .workflow import SkillWorkflowEngine
from .parallel import SkillParallelEngine
from .supervisor import SkillSupervisorEngine
from .orchestrator import SkillOrchestratorEngine
from .map_reduce import SkillMapReduceEngine
from .chain import SkillChainEngine
from .iterative import SkillIterativeEngine
from .consensus import SkillConsensusEngine
from .planned import SkillPlannedEngine, ExecutionPlan, PlanStep
from .hardening import (
    get_rate_limiter, get_audit, get_sandbox,
    RateLimitExceeded,
)


class ExecutionResult:
    """Unified result from any execution mode."""

    def __init__(
        self,
        response: str,
        mode: str,
        errors: List[str] = None,
        metadata: Dict[str, Any] = None,
    ):
        self.response = response
        self.mode = mode
        self.errors = errors or []
        self.metadata = metadata or {}


def validate_execution_mode(
    mode: str,
    steps: List[Dict[str, Any]],
    worker_skills: List[Dict[str, str]],
) -> Tuple[bool, str]:
    """
    Validate that the skill has the required configuration for the given mode.

    Returns:
        Tuple of (is_valid, error_message_if_invalid)
    """
    if mode in ("workflow", "parallel", "chain"):
        if not steps:
            return False, f"execution_mode='{mode}' requires 'steps' to be defined in SKILL.md"

    if mode in ("supervisor", "planned", "orchestrator"):
        if not worker_skills:
            return False, f"execution_mode='{mode}' requires 'worker_skills' to be defined in SKILL.md"

    if mode in ("map_reduce", "consensus"):
        # Accept either worker_skills or steps (steps can define the map/vote tasks)
        if not worker_skills and not steps:
            return False, f"execution_mode='{mode}' requires 'worker_skills' or 'steps' to be defined in SKILL.md"

    # iterative and react have no strict requirements
    return True, ""


async def route_execution(
    mode: str,
    *,
    # Common params
    query: str,
    writer: Optional[Callable] = None,
    # Workflow/Parallel params
    tool_map: Optional[Dict[str, Any]] = None,
    steps: Optional[List[Dict[str, Any]]] = None,
    skill_runner: Optional[Callable] = None,
    # Supervisor/MapReduce/Consensus/Planned params
    llm: Any = None,
    worker_skills: Optional[List[Dict[str, str]]] = None,
    max_steps: int = 10,
    # Iterative params
    max_iterations: int = 3,
    quality_threshold: int = 7,
    evaluation_criteria: str = "Completeness, accuracy, clarity, and relevance",
    initial_instruction: str = "",
    # HITL params (for workflow/parallel)
    hitl_checker: Optional[Callable] = None,
    # Hook params (for supervisor)
    hook_runner: Optional[Any] = None,
    session_ctx: Optional[Dict[str, Any]] = None,
    # Planned mode params
    confirmed_plan: Optional[Dict[str, Any]] = None,
    plan_modifications: Optional[str] = None,
) -> ExecutionResult:
    """
    Route to the appropriate execution engine based on mode.

    This is the single dispatch point — skill_agent_inference.py calls this
    function instead of importing individual engines.

    Args:
        mode: The execution mode string (workflow, parallel, supervisor, etc.)
        query: The user's goal/query
        writer: Optional SSE writer for streaming status
        tool_map: Map of tool_name → tool (for workflow/parallel)
        steps: Step definitions (for workflow/parallel/chain)
        skill_runner: Async callable to invoke sub-skills
        llm: LLM instance (for supervisor/map_reduce/chain/iterative/consensus/planned)
        worker_skills: Worker skill definitions (for supervisor/map_reduce/consensus/planned)
        max_steps: Max supervisor/iterative/planned steps
        max_iterations: Max iterations for iterative mode
        quality_threshold: Score threshold for iterative mode
        evaluation_criteria: Criteria string for iterative mode
        initial_instruction: Initial instruction for iterative mode
        hitl_checker: Optional HITL callback for workflow/parallel (step, params) → dict or None
        hook_runner: Optional HookRunner instance for supervisor PreStep/PostStep
        session_ctx: Optional session context dict for hooks
        confirmed_plan: If mode=planned and plan was confirmed, pass the plan dict
        plan_modifications: If mode=planned and user wants to change the plan, pass
            the modification instructions as a string (e.g., "remove step 2",
            "add a validation step after step 1"). Must also pass confirmed_plan
            as the current plan dict to modify.

    Returns:
        ExecutionResult with response, mode, errors, and metadata
    """
    errors: List[str] = []
    metadata: Dict[str, Any] = {"execution_mode": mode}
    _start_time = time.time()

    # --- Production Hardening: Rate Limiting ---
    _session_id = session_ctx.get("session_id", "") if session_ctx else ""
    _user_id = session_ctx.get("user_id", "") if session_ctx else ""
    _agent_id = session_ctx.get("agent_id", "") if session_ctx else ""

    rate_limiter = get_rate_limiter()
    try:
        rate_limiter.check(_user_id or _session_id or "anonymous")
    except RateLimitExceeded as e:
        metadata["rate_limited"] = True
        metadata["retry_after"] = e.retry_after
        return ExecutionResult(
            response=f"Rate limit exceeded. Please wait {e.retry_after:.0f}s before trying again.",
            mode=mode,
            errors=[str(e)],
            metadata=metadata,
        )

    # --- Production Hardening: Audit Trail ---
    audit = get_audit()
    audit.log_event(
        "dispatch",
        execution_mode=mode,
        agent_id=_agent_id,
        session_id=_session_id,
        user_id=_user_id,
        query=query,
        metadata={"worker_count": len(worker_skills or []), "steps_count": len(steps or [])},
    )

    # --- Workflow Mode ---
    if mode == "workflow":
        parsed_steps = [StepDefinition.from_dict(s) for s in (steps or [])]
        engine = SkillWorkflowEngine(
            tool_map=tool_map or {},
            skill_runner=skill_runner,
            writer=writer,
            llm=llm,
            hitl_checker=hitl_checker,
        )
        wf_results, summary = await engine.run(steps=parsed_steps, initial_context=query)

        # Check if workflow paused for HITL
        if engine.paused_for_approval:
            metadata["paused_for_approval"] = True
            metadata["approval_pending"] = engine.approval_pending
            metadata["remaining_steps"] = [s.name for s in engine.remaining_steps]
            return ExecutionResult(response=summary, mode=mode, errors=[], metadata=metadata)

        # Use last successful output if it's richer than the summary
        last_output = engine.get_last_successful_output()
        response = last_output + "\n\n---\n" + summary if last_output and len(last_output) > len(summary) else summary

        errors = [r.error for r in wf_results.values() if r.name != "_input" and not r.success and r.error]
        metadata["steps_executed"] = len([r for r in wf_results.values() if r.name != "_input"])
        metadata["steps_successful"] = sum(1 for r in wf_results.values() if r.name != "_input" and r.success)

        return ExecutionResult(response=response, mode=mode, errors=errors, metadata=metadata)

    # --- Parallel Mode ---
    if mode == "parallel":
        parsed_steps = [StepDefinition.from_dict(s) for s in (steps or [])]
        engine = SkillParallelEngine(
            tool_map=tool_map or {},
            skill_runner=skill_runner,
            writer=writer,
            llm=llm,
            hitl_checker=hitl_checker,
        )
        par_results, summary = await engine.run(steps=parsed_steps, initial_context=query)

        # Check if parallel paused for HITL
        if engine.paused_for_approval:
            metadata["paused_for_approval"] = True
            metadata["approval_pending"] = engine.approval_pending
            return ExecutionResult(response=summary, mode=mode, errors=[], metadata=metadata)

        last_output = engine.get_last_successful_output()
        response = last_output + "\n\n---\n" + summary if last_output and len(last_output) > len(summary) else summary

        errors = [r.error for r in par_results.values() if r.name != "_input" and not r.success and r.error]
        metadata["steps_executed"] = len([r for r in par_results.values() if r.name != "_input"])

        return ExecutionResult(response=response, mode=mode, errors=errors, metadata=metadata)

    # --- Supervisor Mode ---
    if mode == "supervisor":
        engine = SkillSupervisorEngine(
            llm=llm,
            skill_runner=skill_runner,
            worker_skills=worker_skills or [],
            max_steps=max_steps,
            writer=writer,
            hook_runner=hook_runner,
            session_ctx=session_ctx,
        )
        response, step_log = await engine.run(goal=query)

        errors = [s.result for s in step_log if not s.success]
        metadata["steps_executed"] = len(step_log)
        metadata["steps_successful"] = sum(1 for s in step_log if s.success)

        return ExecutionResult(response=response, mode=mode, errors=errors, metadata=metadata)

    # --- Orchestrator Mode (auto-detected or explicit) ---
    # Key difference from Supervisor: ALL workers execute in PARALLEL
    # then LLM synthesizes. Much faster for multi-worker scenarios.
    if mode == "orchestrator":
        sandbox = get_sandbox()
        _orch_workers = worker_skills or []

        # Sandbox check
        limit_error = sandbox.check_limits(
            session_id=session_ctx.get("session_id", "") if session_ctx else "",
            num_workers=len(_orch_workers),
        )
        if limit_error:
            return ExecutionResult(
                response=f"Execution blocked: {limit_error}",
                mode=mode,
                errors=[limit_error],
                metadata=metadata,
            )

        engine = SkillOrchestratorEngine(
            llm=llm,
            skill_runner=skill_runner,
            worker_skills=_orch_workers,
            max_workers=sandbox.max_workers,
            writer=writer,
            timeout_per_worker=sandbox.worker_timeout,
        )
        response, step_log = await engine.run(goal=query)

        errors = [s.result for s in step_log if not s.success]
        metadata["steps_executed"] = len(step_log)
        metadata["steps_successful"] = sum(1 for s in step_log if s.success)
        metadata["parallel_execution"] = True

        return ExecutionResult(response=response, mode=mode, errors=errors, metadata=metadata)

    # --- Map-Reduce Mode ---
    if mode == "map_reduce":
        # If worker_skills is empty but steps are defined, convert steps to workers
        _mr_workers = worker_skills or []
        if not _mr_workers and steps:
            _mr_workers = [
                {"name": s.get("name", f"worker_{i}"), "description": s.get("description", s.get("params", {}).get("prompt", "")[:100])}
                for i, s in enumerate(steps)
            ]
        engine = SkillMapReduceEngine(
            llm=llm,
            skill_runner=skill_runner,
            worker_skills=_mr_workers,
            writer=writer,
        )
        response, mr_results = await engine.run(goal=query)

        errors = [r.output for r in mr_results if not r.success]
        metadata["workers_total"] = len(mr_results)
        metadata["workers_successful"] = sum(1 for r in mr_results if r.success)

        return ExecutionResult(response=response, mode=mode, errors=errors, metadata=metadata)

    # --- Chain Mode ---
    if mode == "chain":
        engine = SkillChainEngine(llm=llm, writer=writer)
        chain_results, final_output = await engine.run(steps=steps or [], initial_input=query)

        errors = [r.error for r in chain_results if not r.success and r.error]
        metadata["stages_total"] = len(chain_results)
        metadata["stages_successful"] = sum(1 for r in chain_results if r.success)

        return ExecutionResult(response=final_output, mode=mode, errors=errors, metadata=metadata)

    # --- Iterative Mode ---
    if mode == "iterative":
        engine = SkillIterativeEngine(
            llm=llm,
            max_iterations=max_iterations,
            quality_threshold=quality_threshold,
            evaluation_criteria=evaluation_criteria,
            writer=writer,
        )
        response, iterations = await engine.run(goal=query, initial_instruction=initial_instruction)

        metadata["iterations_used"] = len(iterations)
        metadata["final_score"] = iterations[-1]["score"] if iterations else 0
        metadata["met_threshold"] = iterations[-1]["is_satisfactory"] if iterations else False

        return ExecutionResult(response=response, mode=mode, errors=errors, metadata=metadata)

    # --- Consensus Mode ---
    if mode == "consensus":
        # If worker_skills is empty but steps are defined, convert steps to workers
        _cs_workers = worker_skills or []
        if not _cs_workers and steps:
            _cs_workers = [
                {"name": s.get("name", f"voter_{i}"), "description": s.get("description", s.get("params", {}).get("prompt", "")[:100])}
                for i, s in enumerate(steps)
            ]
        engine = SkillConsensusEngine(
            llm=llm,
            skill_runner=skill_runner,
            worker_skills=_cs_workers,
            writer=writer,
        )
        response, votes = await engine.run(goal=query)

        errors = [v.response for v in votes if not v.success]
        metadata["workers_total"] = len(votes)
        metadata["workers_successful"] = sum(1 for v in votes if v.success)

        return ExecutionResult(response=response, mode=mode, errors=errors, metadata=metadata)

    # --- Planned Mode ---
    if mode == "planned":
        engine = SkillPlannedEngine(
            llm=llm,
            skill_runner=skill_runner,
            worker_skills=worker_skills or [],
            max_steps=max_steps,
            writer=writer,
        )

        # Phase 1.5: Modify an existing plan based on user feedback
        if confirmed_plan and plan_modifications:
            current_plan = ExecutionPlan.from_dict(confirmed_plan)
            modified_plan = await engine.modify_plan(current_plan, plan_modifications)
            preview = engine.format_plan_preview(modified_plan)

            metadata["plan_pending_confirmation"] = True
            metadata["plan_modified"] = True
            metadata["plan"] = modified_plan.to_dict()
            metadata["plan_id"] = modified_plan.plan_id

            return ExecutionResult(response=preview, mode=mode, errors=[], metadata=metadata)

        # Phase 2: Execute a previously confirmed plan
        if confirmed_plan:
            plan = ExecutionPlan.from_dict(confirmed_plan)
            response, executed_plan = await engine.execute_plan(plan)

            successful = sum(1 for s in executed_plan.steps if s.status == "done")
            failed = sum(1 for s in executed_plan.steps if s.status == "failed")
            metadata["plan_id"] = executed_plan.plan_id
            metadata["steps_total"] = len(executed_plan.steps)
            metadata["steps_successful"] = successful
            metadata["steps_failed"] = failed
            errors = [s.error for s in executed_plan.steps if s.status == "failed" and s.error]

            return ExecutionResult(response=response, mode=mode, errors=errors, metadata=metadata)

        # Phase 1: Generate plan and return for user confirmation
        plan = await engine.generate_plan(query)
        preview = engine.format_plan_preview(plan)

        metadata["plan_pending_confirmation"] = True
        metadata["plan"] = plan.to_dict()
        metadata["plan_id"] = plan.plan_id

        return ExecutionResult(response=preview, mode=mode, errors=[], metadata=metadata)

    # --- Unknown mode (should not reach here) ---
    log.error(f"[Router] Unknown execution mode: '{mode}'")
    return ExecutionResult(
        response=f"Unknown execution mode: '{mode}'",
        mode=mode,
        errors=[f"Unsupported execution mode: {mode}"],
    )
