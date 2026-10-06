# © 2024-25 Infosys Limited, Bangalore, India. All Rights Reserved.
"""
Map-Reduce Engine — Fan-out work to multiple workers in parallel, then combine.

Phases:
    1. SPLIT: LLM splits the goal into N independent sub-tasks
    2. MAP: Execute all sub-tasks in parallel via skill_runner
    3. REDUCE: LLM combines all results into final answer

Usage in SKILL.md:
    ---
    name: market_analysis
    execution_mode: map_reduce
    worker_skills:
      - name: competitor_analysis
        description: "Analyze competitor landscape"
      - name: market_trends
        description: "Research current market trends"
      - name: customer_sentiment
        description: "Analyze customer feedback and sentiment"
    ---
"""

import asyncio
import json
import re
import time
from typing import List, Dict, Any, Optional, Callable, Tuple

from .base import MapReduceResult, log


# ============================================================================
# Prompt Templates
# ============================================================================

MAP_REDUCE_SPLIT_PROMPT = """\
You are a task splitter. Given a user's goal, split it into {num_workers} independent sub-tasks \
that can be processed in parallel by different workers.

## Available Workers
{workers_list}

## User Goal
{goal}

## Instructions
Respond with ONLY valid JSON — no markdown, no explanation:
{{
  "sub_tasks": [
    {{"worker": "<worker_name>", "task": "<specific sub-task for this worker>"}},
    ...
  ]
}}

Rules:
- Assign exactly one sub-task per worker (use every worker)
- Each sub-task must be self-contained and independent
- Sub-tasks should cover different aspects of the goal
- Keep tasks focused and specific
"""

MAP_REDUCE_COMBINE_PROMPT = """\
You are a result combiner. Multiple workers have processed parts of a goal in parallel. \
Combine their results into a single, comprehensive response.

## Original Goal
{goal}

## Worker Results
{results}

## Instructions
Synthesize all results into a single, well-structured answer. Use markdown formatting. \
Do not mention the workers or the process — just provide the combined answer directly.
"""


class SkillMapReduceEngine:
    """
    Map-Reduce execution — fan out work to multiple workers in parallel,
    then combine all results into a single response.
    """

    def __init__(
        self,
        llm: Any,
        skill_runner: Callable,
        worker_skills: List[Dict[str, str]],
        writer: Optional[Callable] = None,
    ):
        self.llm = llm
        self.skill_runner = skill_runner
        self.worker_skills = worker_skills
        self.writer = writer
        self.map_results: List[MapReduceResult] = []

    async def run(self, goal: str) -> Tuple[str, List[MapReduceResult]]:
        """
        Execute map-reduce pipeline.

        Returns:
            Tuple of (final_combined_response, list_of_map_results)
        """
        self.map_results = []
        self._emit_status("Map-Reduce", "Started")

        # --- Phase 1: SPLIT ---
        self._emit_content("**Phase 1/3: Splitting** — Dividing goal into sub-tasks...")
        sub_tasks = await self._split(goal)

        if not sub_tasks:
            log.warning("[MapReduceEngine] Split produced no sub-tasks — falling back to single worker")
            sub_tasks = [{"worker": self.worker_skills[0]["name"], "task": goal}]

        log.info(f"[MapReduceEngine] Split into {len(sub_tasks)} sub-tasks")

        # --- Phase 2: MAP (parallel execution) ---
        self._emit_content(f"**Phase 2/3: Mapping** — Executing {len(sub_tasks)} workers in parallel...")
        self._emit_status("Map Phase", "Started")

        async def _run_worker(item: Dict[str, str]) -> MapReduceResult:
            worker_name = item["worker"]
            task = item["task"]
            start = time.time()
            try:
                output = await self.skill_runner(worker_name, task)
                duration = int((time.time() - start) * 1000)
                return MapReduceResult(
                    worker_name=worker_name, task=task,
                    output=output, success=True, duration_ms=duration,
                )
            except Exception as e:
                duration = int((time.time() - start) * 1000)
                return MapReduceResult(
                    worker_name=worker_name, task=task,
                    output=str(e), success=False, duration_ms=duration,
                )

        results = await asyncio.gather(*[_run_worker(st) for st in sub_tasks])
        self.map_results = list(results)
        self._emit_status("Map Phase", "Completed")

        successful = sum(1 for r in self.map_results if r.success)
        log.info(f"[MapReduceEngine] Map complete: {successful}/{len(self.map_results)} succeeded")

        # --- Phase 3: REDUCE (combine) ---
        self._emit_content(f"**Phase 3/3: Reducing** — Combining {successful} results...")
        self._emit_status("Reduce Phase", "Started")
        final_response = await self._reduce(goal)
        self._emit_status("Reduce Phase", "Completed")
        self._emit_status("Map-Reduce", "Completed")

        return final_response, self.map_results

    async def _split(self, goal: str) -> List[Dict[str, str]]:
        """Use LLM to split the goal into sub-tasks for each worker."""
        workers_list = "\n".join(
            f"  - **{w['name']}**: {w.get('description', '(no description)')}"
            for w in self.worker_skills
        )
        prompt = MAP_REDUCE_SPLIT_PROMPT.format(
            num_workers=len(self.worker_skills),
            workers_list=workers_list,
            goal=goal,
        )

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
            sub_tasks = data.get("sub_tasks", [])

            # Validate worker names
            valid_names = {w["name"] for w in self.worker_skills}
            validated = [
                st for st in sub_tasks
                if st.get("worker") in valid_names and st.get("task")
            ]
            return validated
        except Exception as e:
            log.error(f"[MapReduceEngine] Split failed: {e}")
            # Fallback: assign the full goal to each worker
            return [{"worker": w["name"], "task": goal} for w in self.worker_skills]

    async def _reduce(self, goal: str) -> str:
        """Use LLM to combine all map results into a single answer."""
        results_text = "\n\n".join(
            f"### {r.worker_name}\n"
            f"**Task:** {r.task}\n"
            f"**{'Result' if r.success else 'Error'}:** {r.output[:1500]}"
            for r in self.map_results
        )

        prompt = MAP_REDUCE_COMBINE_PROMPT.format(goal=goal, results=results_text)

        try:
            from langchain_core.messages import HumanMessage
            if hasattr(self.llm, 'ainvoke'):
                response = await self.llm.ainvoke([HumanMessage(content=prompt)])
            else:
                response = self.llm.invoke([HumanMessage(content=prompt)])
            return response.content.strip()
        except Exception as e:
            log.error(f"[MapReduceEngine] Reduce failed: {e}")
            return results_text

    def format_summary(self) -> str:
        """Format map-reduce execution summary."""
        lines = ["## Map-Reduce Execution Summary\n"]
        successful = sum(1 for r in self.map_results if r.success)
        lines.append(f"**Workers:** {len(self.map_results)}")
        lines.append(f"**Successful:** {successful}")
        lines.append(f"**Failed:** {len(self.map_results) - successful}\n")

        for r in self.map_results:
            status = "✅" if r.success else "❌"
            lines.append(f"{status} **{r.worker_name}** ({r.duration_ms}ms)")
            lines.append(f"   Task: {r.task[:200]}")
            if not r.success:
                lines.append(f"   Error: {r.output[:200]}")
            lines.append("")

        return "\n".join(lines)

    def get_final_output(self) -> str:
        """Get combined output from all successful workers."""
        outputs = [r.output for r in self.map_results if r.success and r.output]
        return "\n\n".join(outputs) if outputs else ""

    def _emit_status(self, node_name: str, status: str):
        if self.writer:
            self.writer({"Node Name": node_name, "Status": status})

    def _emit_content(self, content: str):
        if self.writer:
            self.writer({"content": content})
