# © 2024-25 Infosys Limited, Bangalore, India. All Rights Reserved.
"""
Workflow Engine — Sequential step execution with conditional branching.

Usage in SKILL.md:
    ---
    name: daily_report
    execution_mode: workflow
    steps:
      - name: fetch_sales
        action: shell
        params:
          command: "cat /skills/daily_report/queries.md"
      - name: query_db
        action: database_query
        params:
          connection_name: sales_db
          query: "SELECT * FROM daily_sales WHERE date = CURRENT_DATE"
      - name: check_threshold
        action: condition
        if: "{{query_db.output}}"
        contains: "0 rows"
        then: no_data_step
        else: generate_report
    ---
"""

import time
from typing import List, Dict, Any, Optional, Callable, Tuple

from .base import (
    StepDefinition, StepResult, resolve_template, log,
)


class SkillWorkflowEngine:
    """
    Executes skill steps sequentially with conditional branching support.

    Steps are executed in order. Condition steps evaluate and jump to
    the specified step (then/else), skipping intermediate steps.

    Supports:
        - Template resolution: {{previous_step.output}} in params
        - HITL pause/resume: a hitl_checker callback can pause execution
          mid-workflow for human approval. After approval, call resume()
          to continue from where it paused.
    """

    def __init__(
        self,
        tool_map: Dict[str, Any],
        skill_runner: Optional[Callable] = None,
        writer: Optional[Callable] = None,
        llm: Any = None,
        hitl_checker: Optional[Callable] = None,
    ):
        """
        Args:
            tool_map: Map of tool_name → tool instance (with ainvoke).
            skill_runner: Async callable (skill_name, task) → str for action=skill.
            writer: Optional StreamWriter for SSE status events.
            llm: Optional LLM instance for action=llm steps.
            hitl_checker: Optional callable(step, resolved_params) → dict or None.
                If it returns a dict with {"needs_approval": True, "reason": "..."},
                the workflow pauses and returns an interrupt. Return None to proceed.
        """
        self.tool_map = tool_map
        self.skill_runner = skill_runner
        self.writer = writer
        self.llm = llm
        self.hitl_checker = hitl_checker
        self.results: Dict[str, StepResult] = {}

        # HITL state
        self.paused_for_approval: bool = False
        self.approval_pending: Optional[Dict[str, Any]] = None
        self.remaining_steps: List[StepDefinition] = []
        self._paused_step_index: int = 0
        self._all_steps: List[StepDefinition] = []

    async def run(
        self,
        steps: List[StepDefinition],
        initial_context: str = "",
    ) -> Tuple[Dict[str, StepResult], str]:
        """
        Execute workflow steps sequentially.

        If hitl_checker triggers a pause, workflow stops and sets
        paused_for_approval=True. Call resume() after approval to continue.

        Returns:
            Tuple of (results_dict, summary_string)
        """
        self.results = {"_input": StepResult(name="_input", success=True, output=initial_context)}
        self._all_steps = steps
        self.paused_for_approval = False
        self.approval_pending = None
        self.remaining_steps = []

        if self.writer:
            self.writer({"Node Name": "Workflow Execution", "Status": "Started"})

        step_index = 0
        step_count = len(steps)

        while step_index < step_count:
            step = steps[step_index]
            log.info(f"[WorkflowEngine] Step {step_index + 1}/{step_count}: {step.name} ({step.action})")

            # --- HITL Check: ask hitl_checker if this step needs approval ---
            if self.hitl_checker and step.action != "condition":
                resolved_params = {
                    k: resolve_template(str(v), self.results) for k, v in step.params.items()
                }
                hitl_result = self.hitl_checker(step, resolved_params)
                if hitl_result and hitl_result.get("needs_approval"):
                    # Pause workflow — save state for resume
                    self.paused_for_approval = True
                    self.approval_pending = {
                        "step_name": step.name,
                        "step_action": step.action,
                        "step_params": resolved_params,
                        "reason": hitl_result.get("reason", "Step requires human approval"),
                        "step_index": step_index,
                    }
                    self.remaining_steps = steps[step_index:]
                    self._paused_step_index = step_index

                    log.info(
                        f"[WorkflowEngine] HITL pause at step '{step.name}': "
                        f"{hitl_result.get('reason', 'approval required')}"
                    )
                    if self.writer:
                        self.writer({
                            "Node Name": f"[Step] {step.name}",
                            "Status": "Awaiting Approval",
                        })

                    # Return partial results + summary so far
                    summary = self._format_summary(paused=True)
                    return self.results, summary

            if self.writer:
                self.writer({"Node Name": f"[Step] {step.name}", "Status": "Started"})

            start = time.time()

            try:
                if step.action == "condition":
                    result = self._evaluate_condition(step)
                    # Jump to target step
                    target = result.output.split("→")[-1].strip() if "→" in result.output else None
                    if target:
                        # Find target step index
                        target_idx = next(
                            (i for i, s in enumerate(steps) if s.name == target),
                            None,
                        )
                        if target_idx is not None:
                            self.results[step.name] = result
                            if self.writer:
                                self.writer({"Node Name": f"[Step] {step.name}", "Status": "Completed"})
                            step_index = target_idx
                            continue

                elif step.action == "skill":
                    result = await self._execute_skill_step(step)

                elif step.action == "shell":
                    result = await self._execute_shell_step(step)

                elif step.action == "database_query":
                    result = await self._execute_db_step(step)

                elif step.action == "llm":
                    result = await self._execute_llm_step(step)

                else:
                    result = StepResult(
                        name=step.name, success=False,
                        error=f"Unknown action: {step.action}",
                    )

            except Exception as e:
                result = StepResult(
                    name=step.name, success=False,
                    error=str(e),
                )
                log.error(f"[WorkflowEngine] Step '{step.name}' failed: {e}")

            result.duration_ms = int((time.time() - start) * 1000)
            self.results[step.name] = result

            if result.success:
                log.info(f"[WorkflowEngine] Step '{step.name}' completed in {result.duration_ms}ms")
            else:
                log.error(f"[WorkflowEngine] Step '{step.name}' failed: {result.error}")

            if self.writer:
                status = "Completed" if result.success else "Failed"
                self.writer({"Node Name": f"[Step] {step.name}", "Status": status})

            step_index += 1

        if self.writer:
            self.writer({"Node Name": "Workflow Execution", "Status": "Completed"})

        summary = self._format_summary()
        return self.results, summary

    # ------------------------------------------------------------------
    # HITL Resume
    # ------------------------------------------------------------------

    async def resume(self, approved: bool = True, modified_params: Optional[Dict[str, Any]] = None) -> Tuple[Dict[str, StepResult], str]:
        """
        Resume workflow execution after HITL approval.

        Args:
            approved: If True, continue from the paused step. If False, skip it.
            modified_params: If provided, use these params for the paused step instead.

        Returns:
            Tuple of (results_dict, summary_string)
        """
        if not self.paused_for_approval or not self.remaining_steps:
            log.warning("[WorkflowEngine] resume() called but workflow not paused")
            return self.results, self._format_summary()

        self.paused_for_approval = False
        steps = self.remaining_steps
        self.remaining_steps = []

        if not approved:
            # Skip the paused step and continue with the rest
            skipped_step = steps[0]
            self.results[skipped_step.name] = StepResult(
                name=skipped_step.name,
                success=False,
                error="Rejected by human reviewer",
                skipped=True,
            )
            log.info(f"[WorkflowEngine] Step '{skipped_step.name}' rejected — skipping")
            steps = steps[1:]

        elif modified_params and steps:
            # Apply modified params to the first step (the paused one)
            steps[0].params.update(modified_params)

        # Continue execution from the paused step
        if self.writer:
            self.writer({"Node Name": "Workflow Execution", "Status": "Resumed"})

        step_index = 0 if approved else 0
        step_count = len(steps)

        while step_index < step_count:
            step = steps[step_index]
            log.info(f"[WorkflowEngine] Resumed step: {step.name} ({step.action})")

            if self.writer:
                self.writer({"Node Name": f"[Step] {step.name}", "Status": "Started"})

            start = time.time()
            try:
                if step.action == "condition":
                    result = self._evaluate_condition(step)
                    target = result.output.split("→")[-1].strip() if "→" in result.output else None
                    if target:
                        target_idx = next((i for i, s in enumerate(steps) if s.name == target), None)
                        if target_idx is not None:
                            self.results[step.name] = result
                            if self.writer:
                                self.writer({"Node Name": f"[Step] {step.name}", "Status": "Completed"})
                            step_index = target_idx
                            continue
                elif step.action == "skill":
                    result = await self._execute_skill_step(step)
                elif step.action == "shell":
                    result = await self._execute_shell_step(step)
                elif step.action == "database_query":
                    result = await self._execute_db_step(step)
                elif step.action == "llm":
                    result = await self._execute_llm_step(step)
                else:
                    result = StepResult(name=step.name, success=False, error=f"Unknown action: {step.action}")
            except Exception as e:
                result = StepResult(name=step.name, success=False, error=str(e))
                log.error(f"[WorkflowEngine] Resumed step '{step.name}' failed: {e}")

            result.duration_ms = int((time.time() - start) * 1000)
            self.results[step.name] = result

            if self.writer:
                status = "Completed" if result.success else "Failed"
                self.writer({"Node Name": f"[Step] {step.name}", "Status": status})

            step_index += 1

        if self.writer:
            self.writer({"Node Name": "Workflow Execution", "Status": "Completed"})

        return self.results, self._format_summary()

    # ------------------------------------------------------------------
    # Step Executors
    # ------------------------------------------------------------------

    def _evaluate_condition(self, step: StepDefinition) -> StepResult:
        """Evaluate a condition step (if/contains/then/else)."""
        value = resolve_template(step.condition_if, self.results)
        contains = step.condition_contains
        matches = contains.lower() in value.lower() if contains else bool(value)

        if matches:
            target = step.condition_then
            log.info(f"[WorkflowEngine] Condition '{step.name}': contains '{contains}' = True")
        else:
            target = step.condition_else
            log.info(f"[WorkflowEngine] Condition '{step.name}': contains '{contains}' = False")

        return StepResult(
            name=step.name,
            success=True,
            output=f"{'TRUE' if matches else 'FALSE'} → {target}",
        )

    async def _execute_shell_step(self, step: StepDefinition) -> StepResult:
        """Execute a shell command step via run_shell_command tool."""
        tool = self.tool_map.get("run_shell_command")
        if not tool:
            return StepResult(name=step.name, success=False, error="run_shell_command not available")

        params = {k: resolve_template(str(v), self.results) for k, v in step.params.items()}
        result = await tool.ainvoke(params)
        return StepResult(name=step.name, success=True, output=str(result))

    async def _execute_db_step(self, step: StepDefinition) -> StepResult:
        """Execute a database query step via database_query_tool."""
        tool = self.tool_map.get("database_query_tool")
        if not tool:
            return StepResult(
                name=step.name, success=False,
                error="database_query_tool not available for database_query action",
            )

        params = {k: resolve_template(str(v), self.results) for k, v in step.params.items()}
        result = await tool.ainvoke(params)
        return StepResult(name=step.name, success=True, output=str(result))

    async def _execute_skill_step(self, step: StepDefinition) -> StepResult:
        """Execute a sub-skill step via skill_runner."""
        if not self.skill_runner:
            return StepResult(
                name=step.name, success=False,
                error="skill_runner not configured for skill action",
            )

        task = resolve_template(step.task_template, self.results)
        result = await self.skill_runner(step.skill_name, task)
        return StepResult(name=step.name, success=True, output=str(result))

    async def _execute_llm_step(self, step: StepDefinition) -> StepResult:
        """Execute an LLM prompt step via direct LLM call."""
        params = {k: resolve_template(str(v), self.results) for k, v in step.params.items()}
        prompt = params.get("prompt", "")
        if not prompt:
            return StepResult(name=step.name, success=False, error="No prompt in llm step params")

        # Use LLM directly if available
        if self.llm:
            try:
                from langchain_core.messages import HumanMessage
                messages = [HumanMessage(content=prompt)]
                response = await self.llm.ainvoke(messages)
                output = response.content if hasattr(response, 'content') else str(response)
                return StepResult(name=step.name, success=True, output=output)
            except Exception as e:
                log.error(f"[WorkflowEngine] LLM step '{step.name}' failed: {e}")
                return StepResult(name=step.name, success=False, error=f"LLM call failed: {str(e)}")

        # Fallback to skill_runner
        if self.skill_runner:
            result = await self.skill_runner(step.name, prompt)
            return StepResult(name=step.name, success=True, output=str(result))

        return StepResult(name=step.name, success=False, error="No LLM executor available for llm action")

    # ------------------------------------------------------------------
    # Reporting
    # ------------------------------------------------------------------

    def _format_summary(self, paused: bool = False) -> str:
        """Format workflow execution summary."""
        lines = ["## Workflow Execution Summary\n"]
        real_results = {k: v for k, v in self.results.items() if k != "_input"}
        successful = sum(1 for r in real_results.values() if r.success)
        failed = len(real_results) - successful
        lines.append(f"**Total Steps:** {len(real_results)}")
        lines.append(f"**Successful:** {successful}")
        lines.append(f"**Failed:** {failed}")

        if paused and self.approval_pending:
            lines.append(f"**Status:** ⏸️ PAUSED — awaiting human approval")
            lines.append(f"**Paused At:** {self.approval_pending.get('step_name', 'unknown')}")
            lines.append(f"**Reason:** {self.approval_pending.get('reason', 'Approval required')}")
            if self.remaining_steps:
                lines.append(f"**Remaining:** {', '.join(s.name for s in self.remaining_steps)}")

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
