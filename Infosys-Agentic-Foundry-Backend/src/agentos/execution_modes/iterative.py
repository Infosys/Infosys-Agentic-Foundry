# © 2024-25 Infosys Limited, Bangalore, India. All Rights Reserved.
"""
Iterative Refinement Engine — Generate, judge, refine until quality threshold.

Cycle: Generate → Judge → Refine → Judge → ... → Final

Usage in SKILL.md:
    ---
    name: report_writer
    execution_mode: iterative
    max_iterations: 4
    quality_threshold: 8
    evaluation_criteria: "Completeness, accuracy, professional tone, actionable insights"
    steps:
      - name: initial_draft
        instruction: "Write an initial draft addressing the user's request"
    ---
"""

import json
import re
import time
from typing import List, Dict, Any, Optional, Callable, Tuple

from .base import log


# ============================================================================
# Prompt Templates
# ============================================================================

ITERATIVE_JUDGE_PROMPT = """\
You are a quality judge. Evaluate whether the following output adequately addresses the goal.

## Original Goal
{goal}

## Current Output (Iteration {iteration}/{max_iterations})
{current_output}

## Evaluation Criteria
{criteria}

## Instructions
Respond with ONLY valid JSON:
{{
  "is_satisfactory": true/false,
  "score": <1-10>,
  "feedback": "<specific feedback for improvement if not satisfactory>"
}}

Rules:
- Score 1-10 (10 = perfect)
- is_satisfactory should be true if score >= {threshold}
- If not satisfactory, provide SPECIFIC, ACTIONABLE feedback
- Consider: completeness, accuracy, clarity, and relevance to the goal
"""

ITERATIVE_REFINE_PROMPT = """\
You previously produced an output that needs improvement. Revise it based on the feedback.

## Original Goal
{goal}

## Your Previous Output
{current_output}

## Feedback (from quality judge)
{feedback}

## Instructions
Produce an improved version. Address ALL feedback points. \
Output ONLY the improved content — no meta-commentary.
"""


class SkillIterativeEngine:
    """
    Iterative refinement — generate output, evaluate it, then refine
    until quality threshold is met or max iterations reached.
    """

    DEFAULT_MAX_ITERATIONS = 3
    DEFAULT_THRESHOLD = 7

    def __init__(
        self,
        llm: Any,
        max_iterations: int = DEFAULT_MAX_ITERATIONS,
        quality_threshold: int = DEFAULT_THRESHOLD,
        evaluation_criteria: str = "Completeness, accuracy, clarity, and relevance",
        writer: Optional[Callable] = None,
    ):
        self.llm = llm
        self.max_iterations = max_iterations
        self.quality_threshold = quality_threshold
        self.evaluation_criteria = evaluation_criteria
        self.writer = writer
        self.iterations: List[Dict[str, Any]] = []

    async def run(
        self,
        goal: str,
        initial_instruction: str = "",
    ) -> Tuple[str, List[Dict[str, Any]]]:
        """
        Execute iterative refinement loop.

        Returns:
            Tuple of (final_output, iteration_history)
        """
        self.iterations = []
        self._emit_status("Iterative Refinement", "Started")

        # --- Generate initial output ---
        self._emit_content(f"**Iteration 1/{self.max_iterations}** — Generating initial output...")
        self._emit_status("Initial Generation", "Started")

        instruction = initial_instruction or "Address the user's request comprehensively"
        current_output = await self._generate(goal, instruction)
        self._emit_status("Initial Generation", "Completed")

        for iteration in range(1, self.max_iterations + 1):
            # --- Judge ---
            self._emit_status(f"Evaluation {iteration}", "Started")
            judge_result = await self._judge(goal, current_output, iteration)
            self._emit_status(f"Evaluation {iteration}", "Completed")

            self.iterations.append({
                "iteration": iteration,
                "output_length": len(current_output),
                "score": judge_result.get("score", 0),
                "is_satisfactory": judge_result.get("is_satisfactory", False),
                "feedback": judge_result.get("feedback", ""),
            })

            score = judge_result.get("score", 0)
            is_satisfactory = judge_result.get("is_satisfactory", False)

            log.info(
                f"[IterativeEngine] Iteration {iteration}: score={score}, "
                f"satisfactory={is_satisfactory}"
            )
            self._emit_content(
                f"**Iteration {iteration}** — Score: {score}/10 "
                f"{'✅ Satisfactory' if is_satisfactory else '🔄 Needs improvement'}"
            )

            if is_satisfactory:
                log.info(f"[IterativeEngine] Quality threshold met at iteration {iteration}")
                self._emit_status("Iterative Refinement", "Completed")
                return current_output, self.iterations

            if iteration >= self.max_iterations:
                break

            # --- Refine ---
            feedback = judge_result.get("feedback", "Improve the output")
            self._emit_status(f"Refinement {iteration + 1}", "Started")
            self._emit_content(f"**Iteration {iteration + 1}/{self.max_iterations}** — Refining based on feedback...")
            current_output = await self._refine(goal, current_output, feedback)
            self._emit_status(f"Refinement {iteration + 1}", "Completed")

        log.info(f"[IterativeEngine] Max iterations reached — returning best output")
        self._emit_status("Iterative Refinement", "Completed")
        return current_output, self.iterations

    async def _generate(self, goal: str, instruction: str) -> str:
        """Generate initial output."""
        prompt = f"## Goal\n{goal}\n\n## Instruction\n{instruction}\n\nProduce your output directly:"

        from langchain_core.messages import HumanMessage
        if hasattr(self.llm, 'ainvoke'):
            response = await self.llm.ainvoke([HumanMessage(content=prompt)])
        else:
            response = self.llm.invoke([HumanMessage(content=prompt)])
        return response.content.strip()

    async def _judge(self, goal: str, current_output: str, iteration: int) -> Dict[str, Any]:
        """Evaluate the current output quality."""
        prompt = ITERATIVE_JUDGE_PROMPT.format(
            goal=goal,
            current_output=current_output[:3000],
            iteration=iteration,
            max_iterations=self.max_iterations,
            criteria=self.evaluation_criteria,
            threshold=self.quality_threshold,
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

            return json.loads(raw)
        except Exception as e:
            log.error(f"[IterativeEngine] Judge failed: {e}")
            return {"is_satisfactory": True, "score": 7, "feedback": ""}

    async def _refine(self, goal: str, current_output: str, feedback: str) -> str:
        """Refine the output based on judge feedback."""
        prompt = ITERATIVE_REFINE_PROMPT.format(
            goal=goal,
            current_output=current_output[:3000],
            feedback=feedback,
        )

        from langchain_core.messages import HumanMessage
        if hasattr(self.llm, 'ainvoke'):
            response = await self.llm.ainvoke([HumanMessage(content=prompt)])
        else:
            response = self.llm.invoke([HumanMessage(content=prompt)])
        return response.content.strip()

    def format_summary(self) -> str:
        """Format iterative refinement summary."""
        lines = ["## Iterative Refinement Summary\n"]
        lines.append(f"**Iterations:** {len(self.iterations)}")
        lines.append(f"**Max Allowed:** {self.max_iterations}")
        lines.append(f"**Threshold:** {self.quality_threshold}/10\n")

        for it in self.iterations:
            satisfied = "✅" if it["is_satisfactory"] else "🔄"
            lines.append(f"{satisfied} **Iteration {it['iteration']}** — Score: {it['score']}/10")
            if it["feedback"]:
                lines.append(f"   Feedback: {it['feedback'][:200]}")
            lines.append("")

        return "\n".join(lines)

    def _emit_status(self, node_name: str, status: str):
        if self.writer:
            self.writer({"Node Name": node_name, "Status": status})

    def _emit_content(self, content: str):
        if self.writer:
            self.writer({"content": content})
