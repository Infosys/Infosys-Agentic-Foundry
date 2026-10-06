# © 2024-25 Infosys Limited, Bangalore, India. All Rights Reserved.
"""
Chain Engine — Sequential skill pipeline where output of one step feeds the next.

Unlike workflow (which uses tools), chain mode pipes text between
LLM calls without tool execution. Each step is an LLM-powered
transformation/enrichment.

Usage in SKILL.md:
    ---
    name: content_pipeline
    execution_mode: chain
    steps:
      - name: research
        instruction: "Research the topic and gather key facts"
      - name: outline
        instruction: "Create a structured outline from the research"
      - name: draft
        instruction: "Write a full draft based on the outline"
      - name: polish
        instruction: "Polish the draft for clarity and grammar"
    ---
"""

import time
from typing import List, Dict, Any, Optional, Callable, Tuple

from .base import StepResult, log


class SkillChainEngine:
    """
    Sequential skill pipeline — output of one skill feeds as input to the next.
    """

    def __init__(
        self,
        llm: Any,
        writer: Optional[Callable] = None,
    ):
        self.llm = llm
        self.writer = writer
        self.step_results: List[StepResult] = []

    async def run(
        self,
        steps: List[Dict[str, Any]],
        initial_input: str = "",
    ) -> Tuple[List[StepResult], str]:
        """
        Execute the chain pipeline.

        Each step receives the output of the previous step as context.

        Returns:
            Tuple of (step_results, final_output)
        """
        self.step_results = []
        current_input = initial_input

        self._emit_status("Chain Pipeline", "Started")
        self._emit_content(f"Starting chain pipeline with {len(steps)} stages...")

        for idx, step in enumerate(steps):
            step_name = step.get("name", f"step_{idx+1}")
            instruction = step.get("instruction", "Process the input.")

            self._emit_status(f"[Chain] {step_name}", "Started")
            log.info(f"[ChainEngine] Step {idx+1}/{len(steps)}: {step_name}")

            start = time.time()
            try:
                output = await self._execute_chain_step(instruction, current_input, idx, len(steps))
                duration_ms = int((time.time() - start) * 1000)

                result = StepResult(
                    name=step_name, success=True,
                    output=output, duration_ms=duration_ms,
                )
                current_input = output  # Chain output forward
                log.info(f"[ChainEngine] Step '{step_name}' completed ({duration_ms}ms, {len(output)} chars)")

            except Exception as e:
                duration_ms = int((time.time() - start) * 1000)
                result = StepResult(
                    name=step_name, success=False,
                    error=str(e), duration_ms=duration_ms,
                )
                log.error(f"[ChainEngine] Step '{step_name}' failed: {e}")
                # On failure, continue with previous input (best effort)

            self.step_results.append(result)
            status = "Completed" if result.success else "Failed"
            self._emit_status(f"[Chain] {step_name}", status)

        self._emit_status("Chain Pipeline", "Completed")
        summary = self._format_summary()
        return self.step_results, current_input

    async def _execute_chain_step(
        self, instruction: str, current_input: str, step_idx: int, total_steps: int,
    ) -> str:
        """Execute one chain step via LLM."""
        prompt = (
            f"You are step {step_idx + 1} of {total_steps} in a processing pipeline.\n\n"
            f"## Your Instruction\n{instruction}\n\n"
            f"## Input (from previous step)\n{current_input}\n\n"
            f"## Output\nProduce only your output — no meta-commentary about being a step in a pipeline."
        )

        from langchain_core.messages import HumanMessage
        if hasattr(self.llm, 'ainvoke'):
            response = await self.llm.ainvoke([HumanMessage(content=prompt)])
        else:
            response = self.llm.invoke([HumanMessage(content=prompt)])
        return response.content.strip()

    def _format_summary(self) -> str:
        """Format chain execution summary."""
        lines = ["## Chain Pipeline Summary\n"]
        successful = sum(1 for r in self.step_results if r.success)
        lines.append(f"**Total Stages:** {len(self.step_results)}")
        lines.append(f"**Successful:** {successful}")
        lines.append(f"**Failed:** {len(self.step_results) - successful}\n")

        for r in self.step_results:
            status = "✅" if r.success else "❌"
            lines.append(f"{status} **{r.name}** ({r.duration_ms}ms)")
            if r.error:
                lines.append(f"   Error: {r.error}")
            elif r.output:
                preview = r.output[:200] + "..." if len(r.output) > 200 else r.output
                lines.append(f"   Output preview: {preview}")
            lines.append("")

        return "\n".join(lines)

    def get_last_successful_output(self) -> str:
        """Get output from the last successful step."""
        for r in reversed(self.step_results):
            if r.success and r.output:
                return r.output
        return ""

    def _emit_status(self, node_name: str, status: str):
        if self.writer:
            self.writer({"Node Name": node_name, "Status": status})

    def _emit_content(self, content: str):
        if self.writer:
            self.writer({"content": content})
