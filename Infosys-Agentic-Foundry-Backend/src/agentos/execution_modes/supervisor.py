# © 2024-25 Infosys Limited, Bangalore, India. All Rights Reserved.
"""
Supervisor Engine — LLM-driven orchestrator that delegates to worker skills.

The supervisor LLM decides which skill(s) to call next based on accumulated
results. Supports both sequential AND parallel worker dispatch.

Key improvement: When the manager LLM determines multiple independent skills
are needed, they execute IN PARALLEL via asyncio.gather (like agent_os's
ThreadPoolExecutor pattern). This gives the best of both worlds:
  - Smart sequential reasoning when steps depend on each other
  - Parallel speedup when workers are independent

Usage in SKILL.md:
    ---
    name: supply_chain_ops
    execution_mode: supervisor
    worker_skills:
      - name: inventory_check
        description: "Check inventory levels and stock alerts"
      - name: shipping_tracker
        description: "Track shipments and delivery status"
    max_steps: 8
    ---
"""

import json
import time
import asyncio
from typing import List, Dict, Any, Optional, Callable, Tuple

from .base import (
    SupervisorStep, SupervisorDecision, log,
)


# ============================================================================
# Prompt Template
# ============================================================================

SUPERVISOR_MANAGER_PROMPT = """\
You are a supervisor agent. Your job is to achieve a goal by delegating to \
specialized worker skills.

## Available Worker Skills
{skills_list}

## Work Completed So Far
{step_log}

## Original Goal
{goal}

## Instructions
Decide what to do next. Respond with ONLY valid JSON — no markdown, no explanation:

If you need to call ONE worker skill:
{{"action": "call_skill", "skill_name": "<exact skill name>", "task": "<specific task for this skill>", "reason": "<why this skill next>"}}

If you need MULTIPLE INDEPENDENT skills (they will run in PARALLEL for speed):
{{"action": "parallel_dispatch", "workers": [{{"skill_name": "<name>", "task": "<task>"}}, ...], "reason": "<why these skills together>"}}

If you have enough information to provide a complete answer:
{{"action": "synthesize", "reason": "<brief summary of what you gathered>"}}

If you cannot proceed (repeated failures, no suitable skill):
{{"action": "fail", "reason": "<what went wrong>"}}

## Rules
- skill_name MUST be exactly one of the available skill names listed above
- task must be self-contained — include all relevant context from prior steps
- Do NOT call the same skill with the identical task twice
- You may call the same skill with DIFFERENT tasks if needed
- Use "parallel_dispatch" when workers are INDEPENDENT of each other
- Call "synthesize" as soon as you have enough data — do not over-call skills
- If a skill fails, try an alternative approach or synthesize with partial data
- Worker skills CANNOT interact with the user — make reasonable assumptions
"""


class SkillSupervisorEngine:
    """
    LLM-driven supervisor — a manager LLM decides which skill to call next
    based on accumulated results. Execution path is determined dynamically
    at runtime, not at design time.

    Supports lifecycle hooks (PreStep/PostStep) via hook_runner integration:
      - PreStep: fires before each worker skill call. Can block the step.
      - PostStep: fires after each step. Collects feedback for manager LLM.
    """

    DEFAULT_MAX_STEPS = 10

    def __init__(
        self,
        llm: Any,
        skill_runner: Callable,
        worker_skills: List[Dict[str, str]],
        max_steps: int = DEFAULT_MAX_STEPS,
        writer: Optional[Callable] = None,
        supervisor_prompt_override: Optional[str] = None,
        hook_runner: Optional[Any] = None,
        session_ctx: Optional[Dict[str, Any]] = None,
    ):
        self.llm = llm
        self.skill_runner = skill_runner
        self.worker_skills = worker_skills
        self.max_steps = max_steps
        self.writer = writer
        self.supervisor_prompt_override = supervisor_prompt_override
        self.hook_runner = hook_runner
        self.session_ctx = session_ctx or {}
        self.step_log: List[SupervisorStep] = []
        self._skill_names = {s["name"] for s in worker_skills}

    async def run(self, goal: str) -> Tuple[str, List[SupervisorStep]]:
        """
        Execute the supervisor loop.

        Supports both sequential and parallel worker dispatch:
        - "call_skill" → single worker (sequential reasoning)
        - "parallel_dispatch" → multiple workers at once (speed)

        Returns:
            Tuple of (final_response, step_log)
        """
        self.step_log = []
        self._emit_status("Supervisor", "Started")
        self._emit_content(
            f"Supervisor analyzing goal with {len(self.worker_skills)} available skills..."
        )

        log.info(
            f"[SupervisorEngine] Starting | goal='{goal[:100]}' | "
            f"workers={[s['name'] for s in self.worker_skills]} | max_steps={self.max_steps}"
        )

        step_num = 0
        while step_num < self.max_steps:
            decision = await self._decide(goal)

            if decision.action == "synthesize":
                log.info(f"[SupervisorEngine] Synthesizing after {step_num} steps: {decision.reason}")
                self._emit_status("Synthesizing", "Started")
                final_response = await self._synthesize(goal)
                self._emit_status("Synthesizing", "Completed")
                self._emit_status("Supervisor", "Completed")
                return final_response, self.step_log

            if decision.action == "fail":
                log.warning(f"[SupervisorEngine] Failed: {decision.reason}")
                self._emit_content(f"Supervisor could not complete: {decision.reason}")
                self._emit_status("Supervisor", "Failed")
                return f"Unable to complete the request: {decision.reason}", self.step_log

            # --- Parallel dispatch: run multiple workers concurrently ---
            if decision.action == "parallel_dispatch":
                batch_workers = getattr(decision, '_parallel_workers', [])
                if batch_workers:
                    self._emit_content(
                        f"**Parallel dispatch** — Running {len(batch_workers)} workers concurrently: "
                        + ", ".join(f"`{w['skill_name']}`" for w in batch_workers)
                    )
                    self._emit_status("Parallel Dispatch", "Started")

                    # Execute all workers in parallel
                    async def _run_parallel_worker(w_config, w_step_num):
                        return await self._execute_step(w_step_num, SupervisorDecision(
                            action="call_skill",
                            skill_name=w_config["skill_name"],
                            task=w_config["task"],
                            reason="parallel_dispatch",
                        ))

                    await asyncio.gather(*[
                        _run_parallel_worker(w, step_num + i + 1)
                        for i, w in enumerate(batch_workers)
                    ])
                    step_num += len(batch_workers)
                    self._emit_status("Parallel Dispatch", "Completed")
                    continue

            # --- Single skill call (sequential) ---
            if decision.action == "call_skill":
                step_num += 1
                await self._execute_step(step_num, decision)

        # Reached max_steps — force synthesis
        log.warning(f"[SupervisorEngine] Hit max_steps={self.max_steps} — forcing synthesis")
        self._emit_status("Synthesizing (step limit)", "Started")
        final_response = await self._synthesize(goal)
        self._emit_status("Synthesizing (step limit)", "Completed")
        self._emit_status("Supervisor", "Completed")
        return final_response, self.step_log

    # ------------------------------------------------------------------
    # Decision Making
    # ------------------------------------------------------------------

    async def _decide(self, goal: str) -> SupervisorDecision:
        """Call manager LLM and parse its decision. Supports parallel_dispatch."""
        prompt = self._build_manager_prompt(goal)

        for attempt in range(2):
            try:
                from langchain_core.messages import HumanMessage
                if hasattr(self.llm, 'ainvoke'):
                    response = await self.llm.ainvoke([HumanMessage(content=prompt)])
                else:
                    response = self.llm.invoke([HumanMessage(content=prompt)])
                raw = response.content.strip()

                # Strip markdown code fences if present
                if raw.startswith("```"):
                    import re
                    raw = re.sub(r"^```[a-z]*\n?", "", raw, flags=re.MULTILINE)
                    raw = re.sub(r"\n?```$", "", raw, flags=re.MULTILINE)
                    raw = raw.strip()

                data = json.loads(raw)
                action = data.get("action", "fail")
                if action not in ("call_skill", "parallel_dispatch", "synthesize", "fail"):
                    action = "fail"

                # Handle parallel_dispatch — validate all workers
                if action == "parallel_dispatch":
                    workers = data.get("workers", [])
                    valid_workers = []
                    for w in workers:
                        w_skill = w.get("skill_name", "")
                        if w_skill in self._skill_names and w.get("task"):
                            valid_workers.append(w)
                        else:
                            log.warning(f"[SupervisorEngine] Dropping invalid parallel worker: {w}")

                    if valid_workers:
                        decision = SupervisorDecision(
                            action="parallel_dispatch",
                            reason=data.get("reason", ""),
                        )
                        # Attach workers list as attribute
                        decision._parallel_workers = valid_workers
                        log.info(
                            f"[SupervisorEngine] Parallel dispatch: {len(valid_workers)} workers "
                            f"({[w['skill_name'] for w in valid_workers]})"
                        )
                        return decision
                    else:
                        return SupervisorDecision(
                            action="fail",
                            reason="parallel_dispatch had no valid workers",
                        )

                # Validate skill name for single call
                if action == "call_skill":
                    skill = data.get("skill_name", "")
                    if skill not in self._skill_names:
                        log.warning(
                            f"[SupervisorEngine] Manager requested unknown skill '{skill}'. "
                            f"Available: {sorted(self._skill_names)}"
                        )
                        return SupervisorDecision(
                            action="fail",
                            reason=f"Unknown skill '{skill}'. Available: {sorted(self._skill_names)}",
                        )

                return SupervisorDecision(
                    action=action,
                    skill_name=data.get("skill_name", ""),
                    task=data.get("task", ""),
                    reason=data.get("reason", ""),
                )

            except (json.JSONDecodeError, AttributeError, KeyError) as exc:
                if attempt == 0:
                    log.warning(f"[SupervisorEngine] Manager JSON parse failed ({exc}) — retrying")
                    continue
                log.error(f"[SupervisorEngine] Manager JSON parse failed after retry")
                return SupervisorDecision(
                    action="fail",
                    reason=f"Manager LLM returned unparseable response: {exc}",
                )

        return SupervisorDecision(action="fail", reason="Unexpected _decide() exit")

    # ------------------------------------------------------------------
    # Step Execution
    # ------------------------------------------------------------------

    async def _execute_step(self, step_num: int, decision: SupervisorDecision) -> None:
        """
        Execute one supervisor step: invoke a worker skill and log the result.

        Lifecycle:
          1. Fire PreStep hook (can block the step)
          2. Call worker skill via skill_runner
          3. Fire PostStep hook (collects feedback for manager LLM)
          4. Append to step_log
        """
        skill_name = decision.skill_name
        task = decision.task

        # ── [1] PreStep Hook ──────────────────────────────────────────────
        if self.hook_runner:
            try:
                step_ctx = {
                    **self.session_ctx,
                    "execution_mode": "supervisor",
                    "step_num": step_num,
                    "skill_name": skill_name,
                    "task": task[:500],
                }
                self.hook_runner.run_before_node(
                    node_name=f"supervisor_step_{step_num}_{skill_name}",
                    state=step_ctx,
                )
            except Exception as e:
                log.warning(f"[SupervisorEngine] PreStep hook error: {e}")

        self._emit_status(f"Step {step_num}: {skill_name}", "Started")
        self._emit_content(
            f"**Step {step_num}** — Calling skill **{skill_name}**: {task[:200]}"
        )
        log.info(f"[SupervisorEngine] Step {step_num}: {skill_name} | task='{task[:100]}'")

        # ── [2] Execute worker skill ──────────────────────────────────────
        start_time = time.time()
        result = ""
        success = False

        try:
            result = await self.skill_runner(skill_name, task)
            duration_ms = int((time.time() - start_time) * 1000)
            success = True
            log.info(f"[SupervisorEngine] Step {step_num} completed: {skill_name} ({duration_ms}ms)")
            self._emit_status(f"Step {step_num}: {skill_name}", "Completed")
        except Exception as e:
            duration_ms = int((time.time() - start_time) * 1000)
            result = f"Error: {str(e)}"
            log.error(f"[SupervisorEngine] Step {step_num} failed: {skill_name} — {e}")
            self._emit_status(f"Step {step_num}: {skill_name}", "Failed")

        # ── [3] PostStep Hook ─────────────────────────────────────────────
        if self.hook_runner:
            try:
                step_ctx = {
                    **self.session_ctx,
                    "execution_mode": "supervisor",
                    "step_num": step_num,
                    "skill_name": skill_name,
                    "task": task[:500],
                    "result_preview": result[:500],
                    "success": success,
                    "duration_ms": duration_ms,
                }
                self.hook_runner.run_after_node(
                    node_name=f"supervisor_step_{step_num}_{skill_name}",
                    state=step_ctx,
                    result=result,
                    duration_ms=duration_ms,
                )
            except Exception as e:
                log.warning(f"[SupervisorEngine] PostStep hook error: {e}")

        # ── [4] Append to step log ───────────────────────────────────────
        self.step_log.append(SupervisorStep(
            step_num=step_num,
            skill_name=skill_name,
            task=task,
            result=result,
            success=success,
            duration_ms=duration_ms,
        ))

    # ------------------------------------------------------------------
    # Synthesis
    # ------------------------------------------------------------------

    async def _synthesize(self, goal: str) -> str:
        """Final LLM call — reads full step_log, produces user-facing answer."""
        if not self.step_log:
            return "No steps were executed — unable to answer."

        prompt = (
            f"You have completed an orchestrated task by delegating to specialized skills. "
            f"Based on the results below, provide a clear, complete answer to the original goal.\n\n"
            f"**Original Goal:**\n{goal}\n\n"
            f"**Results Gathered:**\n{self._format_step_log()}\n\n"
            f"Provide a comprehensive final answer. Do not prefix with 'based on the results' "
            f"— just answer directly and completely. Use markdown formatting where appropriate."
        )

        try:
            from langchain_core.messages import HumanMessage
            if hasattr(self.llm, 'ainvoke'):
                response = await self.llm.ainvoke([HumanMessage(content=prompt)])
            else:
                response = self.llm.invoke([HumanMessage(content=prompt)])
            return response.content.strip()
        except Exception as e:
            log.error(f"[SupervisorEngine] Synthesis failed: {e}")
            return self._format_step_log()

    # ------------------------------------------------------------------
    # Prompt Building
    # ------------------------------------------------------------------

    def _build_manager_prompt(self, goal: str) -> str:
        """Build the prompt for the manager LLM's decision-making."""
        if self.supervisor_prompt_override:
            template = self.supervisor_prompt_override
        else:
            template = SUPERVISOR_MANAGER_PROMPT

        skills_list = "\n".join(
            f"  - **{s['name']}**: {s.get('description', '(no description)')}"
            for s in self.worker_skills
        )
        step_log_text = self._format_step_log() if self.step_log else "  (none yet — this is the first step)"

        return template.format(
            skills_list=skills_list,
            step_log=step_log_text,
            goal=goal,
        )

    def _format_step_log(self) -> str:
        """Format step log for inclusion in prompts."""
        if not self.step_log:
            return "(no steps completed)"

        lines = []
        for s in self.step_log:
            status = "✅" if s.success else "❌"
            lines.append(f"  {status} Step {s.step_num} [{s.skill_name}]: {s.task}")
            preview = s.result[:800] + ("..." if len(s.result) > 800 else "")
            lines.append(f"     Result: {preview}")
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # SSE / Writer Helpers
    # ------------------------------------------------------------------

    def _emit_status(self, node_name: str, status: str):
        if self.writer:
            self.writer({"Node Name": node_name, "Status": status})

    def _emit_content(self, content: str):
        if self.writer:
            self.writer({"content": content})

    # ------------------------------------------------------------------
    # Public accessors
    # ------------------------------------------------------------------

    def get_final_output(self) -> str:
        """Get the output from the last successful step (for fallback)."""
        for step in reversed(self.step_log):
            if step.success and step.result:
                return step.result
        return ""

    def format_summary(self) -> str:
        """Format a markdown summary of all steps."""
        lines = ["## Supervisor Execution Summary\n"]
        successful = sum(1 for s in self.step_log if s.success)
        failed = len(self.step_log) - successful
        lines.append(f"**Total Steps:** {len(self.step_log)}")
        lines.append(f"**Successful:** {successful}")
        lines.append(f"**Failed:** {failed}\n")

        for s in self.step_log:
            status = "✅" if s.success else "❌"
            lines.append(f"{status} **Step {s.step_num}: {s.skill_name}** ({s.duration_ms}ms)")
            lines.append(f"   Task: {s.task[:200]}")
            if not s.success:
                lines.append(f"   Error: {s.result}")
            lines.append("")

        return "\n".join(lines)
