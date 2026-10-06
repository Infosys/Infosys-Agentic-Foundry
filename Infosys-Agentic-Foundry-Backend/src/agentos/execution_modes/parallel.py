# © 2024-25 Infosys Limited, Bangalore, India. All Rights Reserved.
"""
Parallel Engine — DAG-based concurrent step execution.

Steps without dependencies run immediately in parallel.
Steps with depends_on wait for all dependencies to complete.

Usage in SKILL.md:
    ---
    name: data_pipeline
    execution_mode: parallel
    steps:
      - name: a
        action: shell
        params: {command: "echo A"}
      - name: b
        action: shell
        params: {command: "echo B"}
      - name: c
        action: shell
        params: {command: "echo {{a.output}} + {{b.output}}"}
        depends_on: [a, b]
    ---
"""

import asyncio
import time
from typing import List, Dict, Any, Optional, Callable, Tuple

from .base import (
    StepDefinition, StepResult, resolve_template, log,
)


class SkillParallelEngine:
    """
    Executes skill steps concurrently based on a dependency DAG.

    Steps without dependencies run immediately in parallel.
    Steps with depends_on wait for all dependencies to complete.

    Supports HITL: a hitl_checker callback is invoked for each step before
    execution. If ANY step in a wave triggers HITL, the wave pauses and the
    engine returns with paused_for_approval=True. Call resume() after approval.
    """

    MAX_CONCURRENCY = 10

    def __init__(
        self,
        tool_map: Dict[str, Any],
        skill_runner: Optional[Callable] = None,
        writer: Optional[Callable] = None,
        llm: Any = None,
        hitl_checker: Optional[Callable] = None,
    ):
        self.tool_map = tool_map
        self.skill_runner = skill_runner
        self.writer = writer
        self.llm = llm
        self.hitl_checker = hitl_checker
        self.results: Dict[str, StepResult] = {}

        # HITL state
        self.paused_for_approval: bool = False
        self.approval_pending: Optional[Dict[str, Any]] = None
        self._remaining_steps_map: Dict[str, StepDefinition] = {}
        self._completed_names: set = set()

    async def run(
        self,
        steps: List[StepDefinition],
        initial_context: str = "",
    ) -> Tuple[Dict[str, StepResult], str]:
        """Execute steps following the DAG dependency order."""
        self.results = {"_input": StepResult(name="_input", success=True, output=initial_context)}
        self.paused_for_approval = False
        self.approval_pending = None
        self._remaining_steps_map = {}
        self._completed_names = {"_input"}

        if self.writer:
            self.writer({"Node Name": "Parallel Execution", "Status": "Started"})

        # Build dependency tracking
        remaining = {s.name: s for s in steps}
        completed_names = self._completed_names
        sem = asyncio.Semaphore(self.MAX_CONCURRENCY)

        while remaining:
            # Find steps whose dependencies are all satisfied
            ready = [
                s for s in remaining.values()
                if all(dep in completed_names for dep in s.depends_on)
            ]

            if not ready:
                # Deadlock: remaining steps have unsatisfied deps
                for s in remaining.values():
                    self.results[s.name] = StepResult(
                        name=s.name, success=False,
                        error=f"Deadlock: unresolved deps {s.depends_on}",
                    )
                break

            # --- HITL Check: check each ready step before executing ---
            if self.hitl_checker:
                for step in ready:
                    resolved_params = {
                        k: resolve_template(str(v), self.results) for k, v in step.params.items()
                    }
                    hitl_result = self.hitl_checker(step, resolved_params)
                    if hitl_result and hitl_result.get("needs_approval"):
                        # Pause — save state for resume
                        self.paused_for_approval = True
                        self.approval_pending = {
                            "step_name": step.name,
                            "step_action": step.action,
                            "step_params": resolved_params,
                            "reason": hitl_result.get("reason", "Step requires human approval"),
                            "wave_steps": [s.name for s in ready],
                        }
                        self._remaining_steps_map = remaining.copy()

                        log.info(f"[ParallelEngine] HITL pause at step '{step.name}'")
                        if self.writer:
                            self.writer({
                                "Node Name": f"[Parallel] {step.name}",
                                "Status": "Awaiting Approval",
                            })

                        summary = self._format_summary(paused=True)
                        return self.results, summary

            # Execute ready steps in parallel
            async def _run_one(step: StepDefinition):
                async with sem:
                    return await self._execute_step(step)

            tasks = [_run_one(s) for s in ready]
            batch_results = await asyncio.gather(*tasks, return_exceptions=True)

            for step, result in zip(ready, batch_results):
                if isinstance(result, Exception):
                    self.results[step.name] = StepResult(
                        name=step.name, success=False, error=str(result),
                    )
                else:
                    self.results[step.name] = result
                completed_names.add(step.name)
                del remaining[step.name]

                # Emit status
                status = "Completed" if self.results[step.name].success else "Failed"
                if self.writer:
                    self.writer({"Node Name": f"[Parallel] {step.name}", "Status": status})

        if self.writer:
            self.writer({"Node Name": "Parallel Execution", "Status": "Completed"})

        summary = self._format_summary()
        return self.results, summary

    async def resume(self, approved: bool = True) -> Tuple[Dict[str, StepResult], str]:
        """
        Resume parallel execution after HITL approval.

        Args:
            approved: If True, continue execution. If False, skip the flagged step.

        Returns:
            Tuple of (results_dict, summary_string)
        """
        if not self.paused_for_approval or not self._remaining_steps_map:
            log.warning("[ParallelEngine] resume() called but engine not paused")
            return self.results, self._format_summary()

        self.paused_for_approval = False
        remaining = self._remaining_steps_map
        self._remaining_steps_map = {}

        if not approved and self.approval_pending:
            # Skip the flagged step
            skipped_name = self.approval_pending["step_name"]
            if skipped_name in remaining:
                self.results[skipped_name] = StepResult(
                    name=skipped_name, success=False,
                    error="Rejected by human reviewer", skipped=True,
                )
                self._completed_names.add(skipped_name)
                del remaining[skipped_name]

        self.approval_pending = None

        if self.writer:
            self.writer({"Node Name": "Parallel Execution", "Status": "Resumed"})

        # Continue the DAG loop
        completed_names = self._completed_names
        sem = asyncio.Semaphore(self.MAX_CONCURRENCY)

        while remaining:
            ready = [
                s for s in remaining.values()
                if all(dep in completed_names for dep in s.depends_on)
            ]

            if not ready:
                for s in remaining.values():
                    self.results[s.name] = StepResult(
                        name=s.name, success=False,
                        error=f"Deadlock: unresolved deps {s.depends_on}",
                    )
                break

            async def _run_one(step: StepDefinition):
                async with sem:
                    return await self._execute_step(step)

            tasks = [_run_one(s) for s in ready]
            batch_results = await asyncio.gather(*tasks, return_exceptions=True)

            for step, result in zip(ready, batch_results):
                if isinstance(result, Exception):
                    self.results[step.name] = StepResult(
                        name=step.name, success=False, error=str(result),
                    )
                else:
                    self.results[step.name] = result
                completed_names.add(step.name)
                del remaining[step.name]

                status = "Completed" if self.results[step.name].success else "Failed"
                if self.writer:
                    self.writer({"Node Name": f"[Parallel] {step.name}", "Status": status})

        if self.writer:
            self.writer({"Node Name": "Parallel Execution", "Status": "Completed"})

        return self.results, self._format_summary()

    async def _execute_step(self, step: StepDefinition) -> StepResult:
        """Execute a single step (reuses workflow engine logic)."""
        start = time.time()
        try:
            if step.action == "shell":
                tool = self.tool_map.get("run_shell_command")
                if not tool:
                    return StepResult(name=step.name, success=False, error="run_shell_command not available")
                params = {k: resolve_template(str(v), self.results) for k, v in step.params.items()}
                output = await tool.ainvoke(params)
                duration_ms = int((time.time() - start) * 1000)
                return StepResult(name=step.name, success=True, output=str(output), duration_ms=duration_ms)

            elif step.action == "database_query":
                tool = self.tool_map.get("database_query_tool")
                if not tool:
                    return StepResult(name=step.name, success=False, error="database_query_tool not available")
                params = {k: resolve_template(str(v), self.results) for k, v in step.params.items()}
                output = await tool.ainvoke(params)
                duration_ms = int((time.time() - start) * 1000)
                return StepResult(name=step.name, success=True, output=str(output), duration_ms=duration_ms)

            elif step.action == "skill":
                if not self.skill_runner:
                    return StepResult(name=step.name, success=False, error="skill_runner not configured")
                task = resolve_template(step.task_template, self.results)
                output = await self.skill_runner(step.skill_name, task)
                duration_ms = int((time.time() - start) * 1000)
                return StepResult(name=step.name, success=True, output=str(output), duration_ms=duration_ms)

            elif step.action == "llm":
                params = {k: resolve_template(str(v), self.results) for k, v in step.params.items()}
                prompt = params.get("prompt", "")
                if not prompt:
                    return StepResult(name=step.name, success=False, error="No prompt in llm step params")
                if self.llm:
                    from langchain_core.messages import HumanMessage
                    messages = [HumanMessage(content=prompt)]
                    response = await self.llm.ainvoke(messages)
                    output = response.content if hasattr(response, 'content') else str(response)
                    duration_ms = int((time.time() - start) * 1000)
                    return StepResult(name=step.name, success=True, output=output, duration_ms=duration_ms)
                elif self.skill_runner:
                    output = await self.skill_runner(step.name, prompt)
                    duration_ms = int((time.time() - start) * 1000)
                    return StepResult(name=step.name, success=True, output=str(output), duration_ms=duration_ms)
                else:
                    return StepResult(name=step.name, success=False, error="No LLM executor available for llm action")

            else:
                return StepResult(name=step.name, success=False, error=f"Unknown action: {step.action}")

        except Exception as e:
            duration_ms = int((time.time() - start) * 1000)
            return StepResult(name=step.name, success=False, error=str(e), duration_ms=duration_ms)

    def _format_summary(self, paused: bool = False) -> str:
        """Format parallel execution summary."""
        lines = ["## Parallel Execution Summary\n"]
        real_results = {k: v for k, v in self.results.items() if k != "_input"}
        successful = sum(1 for r in real_results.values() if r.success)
        failed = len(real_results) - successful
        lines.append(f"**Total Steps:** {len(real_results)}")
        lines.append(f"**Successful:** {successful}")
        lines.append(f"**Failed:** {failed}")

        if paused and self.approval_pending:
            lines.append(f"**Status:** ⏸️ PAUSED — awaiting human approval")
            lines.append(f"**Paused At:** {self.approval_pending.get('step_name', 'unknown')}")
            lines.append(f"**Reason:** {self.approval_pending.get('reason', '')}")

        lines.append("")

        for name, result in real_results.items():
            status = "✅" if result.success else ("⏭️" if result.skipped else "❌")
            lines.append(f"{status} **{name}** ({result.duration_ms}ms)")
            if result.error:
                lines.append(f"   Error: {result.error}")
            elif result.output:
                output = result.output[:300] + "..." if len(result.output) > 300 else result.output
                lines.append(f"   Output: {output}")
            lines.append("")

        return "\n".join(lines)

    def get_last_successful_output(self) -> str:
        """Get the output from the last successfully completed step."""
        for step_name in reversed(list(self.results.keys())):
            if step_name == "_input":
                continue
            result = self.results[step_name]
            if result.success and result.output:
                return result.output
        return ""
