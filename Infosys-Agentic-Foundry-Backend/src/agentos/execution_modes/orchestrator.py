# © 2024-25 Infosys Limited, Bangalore, India. All Rights Reserved.
"""
Orchestrator Engine — Goal-driven dynamic dispatch with parallel worker execution.

Key differences from Supervisor:
  - Workers execute IN PARALLEL via ThreadPoolExecutor (not one-at-a-time)
  - Auto-detects at runtime (no pre-configuration needed)
  - Can use ALL tenant skills as workers dynamically
  - LLM synthesizes AFTER all workers complete

Architecture:
    1. Manager LLM analyzes goal → decides which workers to dispatch
    2. ALL selected workers execute CONCURRENTLY (ThreadPoolExecutor)
    3. Manager LLM synthesizes all results into final answer

This is the "auto-upgraded" mode when SmartRouter detects multi_step complexity.
"""

import json
import re
import time
import asyncio
import concurrent.futures
from typing import List, Dict, Any, Optional, Callable, Tuple
from dataclasses import dataclass, field

from .base import SupervisorStep, log


# ============================================================================
# Data Models
# ============================================================================

@dataclass
class WorkerDispatch:
    """A dispatched worker task."""
    skill_name: str
    task: str
    priority: int = 0  # Higher = execute first in case of resource limits


@dataclass
class OrchestratorResult:
    """Full orchestrator execution result."""
    response: str
    workers_dispatched: List[WorkerDispatch] = field(default_factory=list)
    worker_results: Dict[str, str] = field(default_factory=dict)
    worker_errors: Dict[str, str] = field(default_factory=dict)
    total_duration_ms: int = 0
    parallel_speedup: float = 1.0  # Sequential time / parallel time


# ============================================================================
# Prompts
# ============================================================================

ORCHESTRATOR_PLAN_PROMPT = """\
You are a dynamic orchestrator. Analyze the user's goal and decide which \
worker skills to dispatch — ALL will run IN PARALLEL.

## Available Worker Skills
{skills_list}

## User Goal
{goal}

## Instructions
Decide which skills need to run and what specific task to give each one.
Respond with ONLY valid JSON — no markdown:

{{
  "workers": [
    {{"skill": "<exact skill name>", "task": "<specific, self-contained task>"}},
    ...
  ],
  "synthesis_strategy": "combine" | "pick_best" | "chain_results"
}}

Rules:
- Only include skills that are ACTUALLY needed for this goal
- Each task must be SELF-CONTAINED (workers cannot see each other's output)
- Workers execute in parallel — no dependencies between them
- Use "combine" strategy when merging multiple aspects
- Use "pick_best" when only one result matters
- Use "chain_results" when results should be presented sequentially
- Minimum 1 worker, maximum {max_workers}
"""

ORCHESTRATOR_SYNTHESIZE_PROMPT = """\
You are synthesizing results from multiple parallel workers into a single \
comprehensive answer.

## Original Goal
{goal}

## Strategy
{strategy}

## Worker Results
{results}

## Instructions
{strategy_instruction}

Provide a clear, complete answer. Use markdown formatting where appropriate.
Do not mention the workers or the orchestration process — just answer directly.
"""

STRATEGY_INSTRUCTIONS = {
    "combine": "Merge all worker outputs into a unified, comprehensive answer. Eliminate redundancy while preserving all unique information.",
    "pick_best": "Select the most complete and accurate worker output. If multiple are good, take the best one and supplement with unique info from others.",
    "chain_results": "Present results sequentially, clearly delineated. Use headers and formatting to organize.",
}


# ============================================================================
# Engine
# ============================================================================

class SkillOrchestratorEngine:
    """
    Dynamic orchestrator with parallel worker execution via ThreadPoolExecutor.

    Key advantage over Supervisor:
      - ALL workers run concurrently → faster total execution time
      - Manager decides once, then parallel fan-out
      - No sequential "pick next skill" loop
    """

    DEFAULT_MAX_WORKERS = 6

    def __init__(
        self,
        llm: Any,
        skill_runner: Callable,
        worker_skills: List[Dict[str, str]],
        max_workers: int = DEFAULT_MAX_WORKERS,
        writer: Optional[Callable] = None,
        timeout_per_worker: int = 120,  # seconds
    ):
        self.llm = llm
        self.skill_runner = skill_runner
        self.worker_skills = worker_skills
        self.max_workers = min(max_workers, len(worker_skills))
        self.writer = writer
        self.timeout_per_worker = timeout_per_worker
        self._skill_names = {s["name"] for s in worker_skills}

    async def run(self, goal: str) -> Tuple[str, List[SupervisorStep]]:
        """
        Execute the orchestrator flow:
          1. Manager LLM decides worker dispatch
          2. All workers execute in parallel
          3. Manager LLM synthesizes results

        Returns:
            Tuple of (final_response, step_log)
        """
        step_log: List[SupervisorStep] = []
        start_time = time.time()

        self._emit_status("Orchestrator", "Started")
        self._emit_content(
            f"Orchestrator analyzing goal — {len(self.worker_skills)} skills available..."
        )

        # Phase 1: Plan — decide which workers to dispatch
        dispatch_plan = await self._plan_dispatch(goal)
        if not dispatch_plan:
            self._emit_status("Orchestrator", "Failed")
            return "Unable to determine which skills to use for this query.", step_log

        workers = dispatch_plan.get("workers", [])
        strategy = dispatch_plan.get("synthesis_strategy", "combine")

        # Validate worker names
        valid_workers = [
            w for w in workers
            if w.get("skill") in self._skill_names
        ]
        if not valid_workers:
            log.warning(f"[OrchestratorEngine] No valid workers in plan: {workers}")
            self._emit_status("Orchestrator", "Failed")
            return "No valid worker skills could be identified for this query.", step_log

        log.info(
            f"[OrchestratorEngine] Dispatching {len(valid_workers)} workers in parallel: "
            f"{[w['skill'] for w in valid_workers]}"
        )
        self._emit_content(
            f"**Dispatching {len(valid_workers)} workers in parallel:** "
            + ", ".join(f"`{w['skill']}`" for w in valid_workers)
        )

        # Phase 2: Parallel execution via ThreadPoolExecutor
        self._emit_status("Parallel Execution", "Started")
        worker_results: Dict[str, str] = {}
        worker_errors: Dict[str, str] = {}

        # Create async tasks for all workers
        async def _run_worker(worker_config: Dict[str, str]) -> Tuple[str, str, bool, int]:
            """Run a single worker and return (skill_name, result, success, duration_ms)."""
            skill_name = worker_config["skill"]
            task = worker_config["task"]
            w_start = time.time()
            try:
                result = await asyncio.wait_for(
                    self.skill_runner(skill_name, task),
                    timeout=self.timeout_per_worker,
                )
                duration_ms = int((time.time() - w_start) * 1000)
                return skill_name, result, True, duration_ms
            except asyncio.TimeoutError:
                duration_ms = int((time.time() - w_start) * 1000)
                return skill_name, f"Worker timed out after {self.timeout_per_worker}s", False, duration_ms
            except Exception as e:
                duration_ms = int((time.time() - w_start) * 1000)
                return skill_name, f"Error: {str(e)}", False, duration_ms

        # Execute ALL workers concurrently
        results = await asyncio.gather(
            *[_run_worker(w) for w in valid_workers],
            return_exceptions=True,
        )

        # Process results
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                skill_name = valid_workers[i]["skill"]
                worker_errors[skill_name] = str(result)
                step_log.append(SupervisorStep(
                    step_num=i + 1, skill_name=skill_name,
                    task=valid_workers[i]["task"],
                    result=str(result), success=False, duration_ms=0,
                ))
            else:
                skill_name, output, success, duration_ms = result
                if success:
                    worker_results[skill_name] = output
                else:
                    worker_errors[skill_name] = output
                step_log.append(SupervisorStep(
                    step_num=i + 1, skill_name=skill_name,
                    task=valid_workers[i]["task"],
                    result=output, success=success, duration_ms=duration_ms,
                ))
                self._emit_content(
                    f"  {'✅' if success else '❌'} `{skill_name}` "
                    f"({'done' if success else 'failed'}, {duration_ms}ms)"
                )

        self._emit_status("Parallel Execution", "Completed")

        successful_count = len(worker_results)
        total_count = len(valid_workers)
        log.info(
            f"[OrchestratorEngine] Parallel execution complete: "
            f"{successful_count}/{total_count} succeeded"
        )

        if not worker_results:
            self._emit_status("Orchestrator", "Failed")
            error_summary = "; ".join(f"{k}: {v[:100]}" for k, v in worker_errors.items())
            return f"All workers failed: {error_summary}", step_log

        # Phase 3: Synthesize
        self._emit_status("Synthesizing", "Started")
        self._emit_content(
            f"**Synthesizing** {successful_count} results (strategy: {strategy})..."
        )
        final_response = await self._synthesize(goal, worker_results, strategy)
        self._emit_status("Synthesizing", "Completed")

        total_duration = int((time.time() - start_time) * 1000)

        # Calculate parallel speedup
        sequential_time = sum(s.duration_ms for s in step_log)
        parallel_time = max(s.duration_ms for s in step_log) if step_log else 1
        speedup = sequential_time / parallel_time if parallel_time > 0 else 1.0

        self._emit_content(
            f"\n---\n*Orchestrator: {successful_count}/{total_count} workers, "
            f"{total_duration}ms total, {speedup:.1f}x parallel speedup*"
        )
        self._emit_status("Orchestrator", "Completed")

        return final_response, step_log

    # ------------------------------------------------------------------
    # Planning
    # ------------------------------------------------------------------

    async def _plan_dispatch(self, goal: str) -> Optional[Dict[str, Any]]:
        """Use manager LLM to decide which workers to dispatch."""
        skills_list = "\n".join(
            f"  - **{s['name']}**: {s.get('description', '(no description)')}"
            for s in self.worker_skills
        )
        prompt = ORCHESTRATOR_PLAN_PROMPT.format(
            skills_list=skills_list,
            goal=goal,
            max_workers=self.max_workers,
        )

        for attempt in range(2):
            try:
                from langchain_core.messages import HumanMessage
                if hasattr(self.llm, 'ainvoke'):
                    response = await self.llm.ainvoke([HumanMessage(content=prompt)])
                else:
                    response = self.llm.invoke([HumanMessage(content=prompt)])

                raw = response.content.strip()
                if raw.startswith("```"):
                    raw = re.sub(r"^```[a-z]*\n?", "", raw, flags=re.MULTILINE)
                    raw = re.sub(r"\n?```$", "", raw, flags=re.MULTILINE)
                    raw = raw.strip()

                data = json.loads(raw)
                workers = data.get("workers", [])
                if workers:
                    return data
            except (json.JSONDecodeError, Exception) as e:
                if attempt == 0:
                    log.warning(f"[OrchestratorEngine] Plan parse failed ({e}) — retrying")
                    continue
                log.error(f"[OrchestratorEngine] Plan failed after retry: {e}")

        # Fallback: dispatch all workers with the full goal
        log.warning("[OrchestratorEngine] Planning failed — dispatching all workers with full goal")
        return {
            "workers": [{"skill": s["name"], "task": goal} for s in self.worker_skills[:self.max_workers]],
            "synthesis_strategy": "combine",
        }

    # ------------------------------------------------------------------
    # Synthesis
    # ------------------------------------------------------------------

    async def _synthesize(
        self,
        goal: str,
        worker_results: Dict[str, str],
        strategy: str,
    ) -> str:
        """Synthesize all parallel worker results into final answer."""
        results_text = "\n\n".join(
            f"### {skill_name}\n{result[:2000]}"
            for skill_name, result in worker_results.items()
        )

        strategy_instruction = STRATEGY_INSTRUCTIONS.get(
            strategy, STRATEGY_INSTRUCTIONS["combine"]
        )

        prompt = ORCHESTRATOR_SYNTHESIZE_PROMPT.format(
            goal=goal,
            strategy=strategy,
            results=results_text,
            strategy_instruction=strategy_instruction,
        )

        try:
            from langchain_core.messages import HumanMessage
            if hasattr(self.llm, 'ainvoke'):
                response = await self.llm.ainvoke([HumanMessage(content=prompt)])
            else:
                response = self.llm.invoke([HumanMessage(content=prompt)])
            return response.content.strip()
        except Exception as e:
            log.error(f"[OrchestratorEngine] Synthesis failed: {e}")
            # Fallback: return concatenated results
            return "\n\n---\n\n".join(
                f"## {name}\n{result}" for name, result in worker_results.items()
            )

    # ------------------------------------------------------------------
    # SSE Helpers
    # ------------------------------------------------------------------

    def _emit_status(self, node_name: str, status: str):
        if self.writer:
            self.writer({"Node Name": node_name, "Status": status})

    def _emit_content(self, content: str):
        if self.writer:
            self.writer({"content": content})
