# © 2024-25 Infosys Limited, Bangalore, India. All Rights Reserved.
"""
Consensus Engine — Multiple workers independently answer the same query,
then a judge picks the best or merges responses.

Useful for:
- Reducing hallucination (majority vote)
- Getting diverse perspectives
- Combining expert knowledge from different domains

Usage in SKILL.md:
    ---
    name: fact_checker
    execution_mode: consensus
    worker_skills:
      - name: analyst_1
        instruction: "Analyze from a technical perspective"
      - name: analyst_2
        instruction: "Analyze from a business perspective"
      - name: analyst_3
        instruction: "Analyze from a risk/compliance perspective"
    ---
"""

import asyncio
import json
import re
import time
from typing import List, Dict, Any, Optional, Callable, Tuple

from .base import ConsensusVote, log


# ============================================================================
# Prompt Template
# ============================================================================

CONSENSUS_JUDGE_PROMPT = """\
You are an impartial judge. Multiple workers have independently answered the same question. \
Evaluate their responses and produce the best possible answer.

## Original Goal
{goal}

## Worker Responses
{responses}

## Instructions
Respond with ONLY valid JSON:
{{
  "best_worker": "<name of worker with best response, or 'merged' if combining>",
  "strategy": "pick_best" | "merge_all" | "majority_vote",
  "reasoning": "<brief explanation of your choice>",
  "final_answer": "<the final, best answer — either picked or merged>"
}}

Rules:
- If one response is clearly superior, pick it (strategy: "pick_best")
- If responses have complementary information, merge them (strategy: "merge_all")
- If responses agree on key points, use majority vote logic (strategy: "majority_vote")
- final_answer must be a complete, self-contained response
- Use markdown formatting in final_answer where appropriate
"""


class SkillConsensusEngine:
    """
    Consensus/Ensemble execution — multiple workers independently answer
    the same query, then a judge picks the best or merges responses.
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
        self.votes: List[ConsensusVote] = []
        self.judge_result: Dict[str, Any] = {}

    async def run(self, goal: str) -> Tuple[str, List[ConsensusVote]]:
        """
        Execute consensus pipeline.

        1. All workers answer independently and in parallel
        2. Judge evaluates and produces final answer

        Returns:
            Tuple of (final_judged_answer, list_of_worker_votes)
        """
        self.votes = []
        self._emit_status("Consensus", "Started")

        # --- Phase 1: Parallel independent responses ---
        self._emit_content(
            f"**Phase 1/2: Gathering** — {len(self.worker_skills)} workers answering independently..."
        )
        self._emit_status("Gathering Responses", "Started")

        async def _get_response(worker: Dict[str, str]) -> ConsensusVote:
            name = worker["name"]
            instruction = worker.get("instruction", worker.get("description", "Answer the query"))
            # Build task that includes the worker's specific perspective
            task = f"{instruction}\n\nQuery: {goal}"
            start = time.time()
            try:
                output = await self.skill_runner(name, task)
                duration = int((time.time() - start) * 1000)
                return ConsensusVote(
                    worker_name=name, instruction=instruction,
                    response=output, success=True, duration_ms=duration,
                )
            except Exception as e:
                duration = int((time.time() - start) * 1000)
                return ConsensusVote(
                    worker_name=name, instruction=instruction,
                    response=str(e), success=False, duration_ms=duration,
                )

        results = await asyncio.gather(*[_get_response(w) for w in self.worker_skills])
        self.votes = list(results)
        self._emit_status("Gathering Responses", "Completed")

        successful = sum(1 for v in self.votes if v.success)
        log.info(f"[ConsensusEngine] Gathered {successful}/{len(self.votes)} responses")

        if successful == 0:
            self._emit_status("Consensus", "Failed")
            return "All workers failed to produce a response.", self.votes

        # --- Phase 2: Judge evaluates and decides ---
        self._emit_content(f"**Phase 2/2: Judging** — Evaluating {successful} responses...")
        self._emit_status("Judging", "Started")
        final_answer = await self._judge(goal)
        self._emit_status("Judging", "Completed")
        self._emit_status("Consensus", "Completed")

        return final_answer, self.votes

    async def _judge(self, goal: str) -> str:
        """Judge evaluates all worker responses and produces final answer."""
        responses_text = "\n\n".join(
            f"### Worker: {v.worker_name}\n"
            f"**Perspective:** {v.instruction}\n"
            f"**Response:** {v.response[:2000]}"
            for v in self.votes if v.success
        )

        prompt = CONSENSUS_JUDGE_PROMPT.format(goal=goal, responses=responses_text)

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

            self.judge_result = json.loads(raw)
            final_answer = self.judge_result.get("final_answer", "")
            if not final_answer:
                # Fallback: use the best worker's response
                best = self.judge_result.get("best_worker", "")
                for v in self.votes:
                    if v.worker_name == best and v.success:
                        return v.response
                # Last resort: return first successful
                for v in self.votes:
                    if v.success:
                        return v.response
            return final_answer

        except Exception as e:
            log.error(f"[ConsensusEngine] Judge failed: {e}")
            # Fallback: return longest successful response
            successful = [v for v in self.votes if v.success]
            if successful:
                return max(successful, key=lambda v: len(v.response)).response
            return "Judge evaluation failed and no worker responses available."

    def format_summary(self) -> str:
        """Format consensus execution summary."""
        lines = ["## Consensus Execution Summary\n"]
        successful = sum(1 for v in self.votes if v.success)
        lines.append(f"**Workers:** {len(self.votes)}")
        lines.append(f"**Successful Responses:** {successful}")
        if self.judge_result:
            lines.append(f"**Strategy:** {self.judge_result.get('strategy', 'N/A')}")
            lines.append(f"**Best Worker:** {self.judge_result.get('best_worker', 'N/A')}")
        lines.append("")

        for v in self.votes:
            status = "✅" if v.success else "❌"
            lines.append(f"{status} **{v.worker_name}** ({v.duration_ms}ms)")
            lines.append(f"   Perspective: {v.instruction[:150]}")
            if not v.success:
                lines.append(f"   Error: {v.response[:200]}")
            lines.append("")

        if self.judge_result.get("reasoning"):
            lines.append(f"**Judge Reasoning:** {self.judge_result['reasoning']}")

        return "\n".join(lines)

    def _emit_status(self, node_name: str, status: str):
        if self.writer:
            self.writer({"Node Name": node_name, "Status": status})

    def _emit_content(self, content: str):
        if self.writer:
            self.writer({"content": content})
