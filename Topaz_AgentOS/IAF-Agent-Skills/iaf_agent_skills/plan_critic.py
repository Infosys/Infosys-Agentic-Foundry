"""
Plan Critic — Post-generation semantic validation of execution plans.

Validates a generated plan against:
  1. Entity registry taxonomy  (skill ownership per entity)
  2. Process relationships     (ordering / trigger rules)
  3. Similar past episodes     (empirical precedent via KnowledgeIndexer)

Designed to be MODULAR — the critic is enabled/disabled via the
agent.enable_critique flag, which the UI exposes as a toggle.
Nothing in the planner or tool_factory hard-depends on this module;
it is imported and called only when the flag is True.

Usage:
    from .plan_critic import PlanCritic

    critic = PlanCritic(llm=light_llm, indexer=knowledge_indexer)
    critique = critic.critique(plan, entity_context_text, query)
    display += critic.format_for_display(critique)
"""

import json
import logging
import re
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# Minimum episode similarity score — slightly lower than knowledge threshold
# because episode embeddings are sparser than indexed knowledge records.
_EPISODE_MIN_SCORE = 0.65
_EPISODE_TOP_K = 3


class PlanCritic:
    """
    Semantic validator for AI-generated execution plans.

    Runs as an optional post-generation pass after PlannerEngine.generate_plan().
    Returns structured feedback (confidence + issues list) that is appended
    to the plan display shown to the user.

    The critic uses light_llm (fast/cheap model) — it does not need the
    full reasoning power of the primary LLM since the taxonomy and episode
    context are already structured and concise.
    """

    def __init__(self, llm, indexer=None):
        """
        Args:
            llm:     LangChain-compatible chat model. Recommend light_llm
                     (e.g. gpt-4o-mini) — critique prompts are short and
                     the task is classification, not generation.
            indexer: KnowledgeIndexer instance for episode search.
                     Optional — critic still works without it but skips
                     the empirical precedent check.
        """
        self.llm = llm
        self.indexer = indexer


    def critique(
        self,
        plan: Dict[str, Any],
        entity_context_text: str,
        query: str,
    ) -> Dict[str, Any]:
        """
        Validate a generated plan against taxonomy and past episodes.

        Args:
            plan:                Plan dict from PlannerEngine.generate_plan().
            entity_context_text: Output of build_planner_context() — structured NL.
                                 This is the same text already passed to the planner,
                                 so no extra DB calls are needed.
            query:               Original user query.

        Returns:
            {
                "confidence": "high" | "medium" | "low",
                "issues": [
                    {
                        "step_id":   str | None,   # None = plan-level issue
                        "type":      str,           # see types below
                        "message":   str,           # specific issue with evidence
                        "suggestion": str           # concrete fix
                    },
                    ...
                ],
                "summary": str    # 1-2 sentence overall assessment
            }

        Issue types:
            wrong_skill       — entity taxonomy maps to a different skill
            missing_coverage  — resolved entity has no corresponding step
            bad_dependency    — ordering contradicts process relationships
            vague_task        — task description too vague for the skill to act on

        On LLM failure: returns {"confidence": "high", "issues": [], "summary": ""}
        so the plan display is unaffected.
        """
        episodes_text = self._fetch_similar_episodes(query)
        plan_text = self._format_plan_for_critique(plan)

        prompt = f"""You are a plan reviewer for a multi-skill AI agent system.
Your job: validate the plan against the taxonomy and past episodes.
Flag ONLY real issues backed by specific evidence from the context below.
Do NOT invent problems that are not supported by the taxonomy or episodes.

USER QUERY: "{query}"

GENERATED PLAN:
{plan_text}

TAXONOMY (entity → skill mapping and ordering rules):
{entity_context_text if entity_context_text else "No taxonomy context available."}

SIMILAR PAST EPISODES (empirical precedent):
{episodes_text if episodes_text else "No similar past episodes found."}

Check for:
1. wrong_skill       — an entity in the taxonomy maps to a different skill than the plan uses
2. missing_coverage  — a resolved entity from taxonomy has no step covering it
3. bad_dependency    — step order contradicts a process relationship (e.g. B before A when A TRIGGERS B)
4. vague_task        — task description gives the skill no actionable detail

Confidence rules:
- high:   0 issues found
- medium: 1-2 minor issues (vague_task or partial coverage)
- low:    any wrong_skill or bad_dependency issue

IMPORTANT JSON rules — the parser is strict:
- Use double quotes only. No single quotes anywhere.
- No apostrophes inside string values (write "does not" not "doesn't").
- No newlines inside string values — keep each value on one line.
- The issues array must be [] when there are no issues.

{{
  "confidence": "high",
  "issues": [],
  "summary": "Plan looks correct."
}}

Or with issues:
{{
  "confidence": "medium",
  "issues": [
    {{
      "step_id": "step_2",
      "type": "wrong_skill",
      "message": "Entity maps to finance skill but plan uses general",
      "suggestion": "Change skill to finance"
    }}
  ],
  "summary": "One skill assignment needs review."
}}"""

        try:
            response = self.llm.invoke(prompt)
            raw = response.content.strip()
            result = self._safe_parse_json(raw)
            result.setdefault("confidence", "high")
            result.setdefault("issues", [])
            result.setdefault("summary", "")
            return result

        except Exception as e:
            logger.warning("PlanCritic: LLM call failed: %s", e)
            return {"confidence": "high", "issues": [], "summary": ""}

    def format_for_display(self, critique: Dict[str, Any]) -> str:
        """
        Format a critique result as markdown for appending to the plan display.

        Returns empty string when there are no issues (confidence=high),
        so the plan display is unchanged for clean plans.
        """
        issues = critique.get("issues", [])
        confidence = critique.get("confidence", "high")

        if not issues and confidence == "high":
            return ""

        icon = {"high": "✅", "medium": "⚠️", "low": "🔴"}.get(confidence, "⚠️")
        lines = [
            f"\n---",
            f"{icon} **Plan Review** — confidence: **{confidence.upper()}**",
        ]

        for issue in issues:
            step = issue.get("step_id")
            step_str = f" `{step}`" if step else ""
            itype = issue.get("type", "issue").replace("_", " ")
            lines.append(f"\n- **{itype}**{step_str}: {issue.get('message', '')}")
            if issue.get("suggestion"):
                lines.append(f"  💡 _{issue['suggestion']}_")

        if critique.get("summary"):
            lines.append(f"\n_{critique['summary']}_")

        return "\n".join(lines)


    @staticmethod
    def _safe_parse_json(raw: str) -> dict:
        """
        Robustly parse JSON from LLM output.

        LLMs (especially smaller models like gpt-4o-mini) commonly produce:
          - Markdown code fences (```json ... ```)
          - Apostrophes inside string values  ("doesn't" breaks strict JSON)
          - Trailing commas before closing braces
          - Literal newlines inside string values

        Strategy:
          1. Strip markdown fences
          2. Extract outermost { ... } block via regex
          3. Try strict json.loads first
          4. On failure, apply light cleanup (trailing commas) and retry
          5. Log raw on final failure so we can diagnose patterns
        """
        # Step 1 — strip markdown fences
        if "```" in raw:
            parts = raw.split("```")
            for part in parts:
                part = part.strip()
                if part.startswith("json"):
                    part = part[4:].strip()
                if part.startswith("{"):
                    raw = part
                    break

        # Step 2 — extract outermost JSON object
        match = re.search(r"\{[\s\S]*\}", raw)
        if match:
            raw = match.group(0)

        # Step 3 — strict parse
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            pass

        # Step 4 — light cleanup: trailing commas before ] or }
        cleaned = re.sub(r",\s*([}\]])", r"\1", raw)
        try:
            return json.loads(cleaned)
        except json.JSONDecodeError as e:
            logger.warning("PlanCritic: LLM returned invalid JSON: %s", e)
            raise

    def _fetch_similar_episodes(self, query: str) -> str:
        """
        Fetch top-k similar past episodes via KnowledgeIndexer and format
        as concise NL lines for the critic prompt.

        Includes both successes and failures — failures with their outcomes
        are the most useful signal for the critic.
        """
        if not self.indexer:
            return ""
        try:
            episodes = self.indexer.search_similar_episodes(
                query=query,
                top_k=_EPISODE_TOP_K,
                min_score=_EPISODE_MIN_SCORE,
                success_only=False,
            )
            if not episodes:
                return ""

            lines = []
            for ep in episodes:
                outcome = ep.get("outcome", {})
                status = (
                    outcome.get("status", "unknown")
                    if isinstance(outcome, dict)
                    else str(outcome)
                )
                skill = ep.get("skill", "unknown")
                user_input = (ep.get("user_input") or "")[:100]
                score = ep.get("score", 0.0)
                lines.append(
                    f'  - "{user_input}" → skill: {skill}, outcome: {status}'
                    f" (similarity: {score:.2f})"
                )
            return "\n".join(lines)

        except Exception as e:
            logger.warning("PlanCritic: Episode fetch failed: %s", e)
            return ""

    @staticmethod
    def _format_plan_for_critique(plan: Dict[str, Any]) -> str:
        """
        Compact plan representation for the critic prompt.
        One line per step: [id] skill=X (after: Y,Z): task description
        """
        lines = []
        for step in plan.get("steps", []):
            deps = step.get("depends_on", [])
            dep_str = f" (after: {', '.join(deps)})" if deps else ""
            lines.append(
                f"  [{step.get('id', '?')}] skill={step.get('skill', '?')}"
                f"{dep_str}: {step.get('task', '')}"
            )
        return "\n".join(lines) if lines else "  (no steps)"


    def critique_response(
        self,
        query: str,
        response_text: str,
        tool_outputs: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """
        Validate a final agent response against the actual tool outputs used.

        Checks whether factual claims in the response are traceable to tool
        output data. Flags unsupported claims, contradictions, and hallucinated
        entity names not present in any tool result.

        Args:
            query:         Original user query.
            response_text: Final answer generated by the agent.
            tool_outputs:  List of {tool, input, output_preview, has_error}
                           dicts — agent.py tool_results_detail.

        Returns same structure as critique():
            {
                "confidence": "high" | "medium" | "low",
                "issues": [
                    {
                        "type":       str,   # unsupported_claim | contradicts_data | hallucinated_entity
                        "claim":      str,   # the specific claim in the answer
                        "evidence":   str,   # what the tool output actually says
                        "suggestion": str    # how to fix it
                    }
                ],
                "summary": str,
                "was_revised": bool   # set to True externally after a revision pass
            }

        On LLM failure: returns {"confidence": "high", "issues": [], "summary": ""}
        so the response is unaffected.
        """
        if not tool_outputs:
            return {"confidence": "high", "issues": [], "summary": "No tool outputs to verify against."}

        tool_text = self._format_tool_outputs(tool_outputs)
        episodes_text = self._fetch_similar_episodes(query)

        prompt = f"""You are a grounding verifier for an AI agent system.
Your job: check if the agent final answer is faithful to the tool outputs below.
Flag ONLY real issues backed by specific evidence. Do NOT invent problems.
Skip general explanations and process descriptions — only check specific factual claims.

USER QUERY: "{query}"

TOOL OUTPUTS (actual data retrieved during this request):
{tool_text}

SIMILAR PAST EPISODES (for context):
{episodes_text if episodes_text else "None."}

AGENT ANSWER:
{response_text[:3000]}

Check for these issue types only:
1. unsupported_claim   — a specific fact (number, status, date, count) stated as certain
                         that does not appear in any tool output
2. contradicts_data    — the answer states something that directly contradicts a tool output
                         (e.g. answer says 89% but tool returned 67%)
3. hallucinated_entity — a specific entity name (hostname, record ID, username, filename)
                         in the answer that does not appear in any tool output

Confidence rules:
- high:   0 issues — answer is fully grounded
- medium: 1 minor unsupported_claim (vague statement, not a hard number or specific name)
- low:    any contradicts_data or hallucinated_entity, or 2+ unsupported_claims

IMPORTANT JSON rules:
- Use double quotes only. No apostrophes inside string values.
- No newlines inside string values.
- issues array must be [] when there are no issues.

Return ONLY valid JSON in one of these two forms:

{{"confidence": "high", "issues": [], "summary": "Answer is fully grounded in tool outputs."}}

{{"confidence": "low", "issues": [{{"type": "contradicts_data", "claim": "89% disk usage", "evidence": "tool returned disk_usage_pct=67", "suggestion": "Use the value from the query result"}}], "summary": "Answer contradicts the SQL result."}}"""

        try:
            resp = self.llm.invoke(prompt)
            raw = resp.content.strip()
            result = self._safe_parse_json(raw)
            result.setdefault("confidence", "high")
            result.setdefault("issues", [])
            result.setdefault("summary", "")
            return result
        except Exception as e:
            logger.warning("PlanCritic.critique_response: LLM call failed: %s", e)
            return {"confidence": "high", "issues": [], "summary": ""}

    def format_response_critique_for_display(self, critique: Dict[str, Any]) -> str:
        """Format response critique as markdown for appending to the agent answer."""
        issues = critique.get("issues", [])
        confidence = critique.get("confidence", "high")

        if not issues and confidence == "high":
            return ""

        icon = {"high": "✅", "medium": "⚠️", "low": "🔴"}.get(confidence, "⚠️")
        lines = [
            "\n---",
            f"{icon} **Grounding Check** — confidence: **{confidence.upper()}**",
        ]
        for issue in issues:
            itype = issue.get("type", "issue").replace("_", " ")
            claim = issue.get("claim", "")
            evidence = issue.get("evidence", "")
            lines.append(f"\n- **{itype}**: {claim}")
            if evidence:
                lines.append(f"  Evidence: _{evidence}_")
            if issue.get("suggestion"):
                lines.append(f"  💡 _{issue['suggestion']}_")
        if critique.get("summary"):
            lines.append(f"\n_{critique['summary']}_")
        return "\n".join(lines)

    def critique_consistency(
        self,
        query: str,
        response_a: str,
        response_b: str,
    ) -> Dict[str, Any]:
        """
        Compare two independent agent runs on the same query.

        Run A = original response shown to user.
        Run B = cold re-run (no history, no memory) — independent verification.

        Checks for:
          contradicts_run2   — Run A states a fact Run B contradicts
          missing_in_run1    — Run B found/cited something important Run A missed
          low_reproducibility — runs reached different conclusions overall

        Returns same structure as critique_response() so the UI renders it
        in the same Grounding panel without any frontend changes.

        On LLM failure: returns {"confidence": "high", "issues": [], "summary": ""}
        """
        if not response_b or not response_b.strip():
            return {"confidence": "high", "issues": [], "summary": "Second run returned no output."}

        prompt = f"""You are a consistency verifier for an AI agent system.
Two independent agent runs answered the same query. Compare them and flag real differences only.
Do NOT flag stylistic differences or reordering — only factual contradictions or meaningful omissions.

QUERY: "{query}"

RUN 1 (shown to user):
{response_a[:2000]}

RUN 2 (independent cold re-run, no conversation history):
{response_b[:2000]}

Check for these issue types only:
1. contradicts_run2     — Run 1 states a specific fact (number, step, filename, status) that Run 2 contradicts
2. missing_in_run1      — Run 2 cited a specific source or finding that Run 1 did not include and that materially changes the answer
3. low_reproducibility  — the two runs reached clearly different overall conclusions

Confidence rules:
- high:   no issues — both runs agree on all key facts and sources
- medium: 1 missing_in_run1 that is minor or supplementary
- low:    any contradicts_run2 or low_reproducibility, or 2+ missing_in_run1

IMPORTANT JSON rules:
- Double quotes only. No apostrophes inside string values.
- No newlines inside string values.
- issues array must be [] when there are no issues.

Return ONLY valid JSON:
{{"confidence": "high", "issues": [], "summary": "Both runs agree."}}

Or with issues:
{{"confidence": "low", "issues": [{{"type": "contradicts_run2", "claim": "Run 1 says 3 approval levels", "evidence": "Run 2 found 2 approval levels in the standard flow", "suggestion": "Verify approval levels in the standard process flow file"}}], "summary": "Runs contradict on approval levels."}}"""

        try:
            resp = self.llm.invoke(prompt)
            raw = resp.content.strip()
            result = self._safe_parse_json(raw)
            result.setdefault("confidence", "high")
            result.setdefault("issues", [])
            result.setdefault("summary", "")
            result["is_consistency_check"] = True   # flag so UI can label it differently
            return result
        except Exception as e:
            logger.warning("PlanCritic.critique_consistency: LLM call failed: %s", e)
            return {"confidence": "high", "issues": [], "summary": "", "is_consistency_check": True}

    @staticmethod
    def _format_tool_outputs(tool_outputs: List[Dict[str, Any]]) -> str:
        """Format tool_results_detail list for the critique prompt.

        Tuning guide (adjust these if critique is too slow or missing facts):
          _MAX_TOOLS        — how many tool calls to include. More = better coverage
                              but larger prompt and slower LLM call. 5 is enough for
                              most single-skill ReAct runs which use 3-6 tools.
          _MAX_INPUT_CHARS  — chars kept from each tool's input (command / SQL / query).
                              200 is enough to identify what was asked.
          _MAX_OUTPUT_CHARS — chars kept from each tool's output (actual data returned).
                              400 covers a typical SQL result row or incident record.
                              Increase to 800 if the critic misses facts in longer outputs.
        """
        _MAX_TOOLS        = 5    # increase if agent uses many tools and coverage matters more than speed
        _MAX_INPUT_CHARS  = 200  # increase if inputs are truncated in a way that loses context
        _MAX_OUTPUT_CHARS = 400  # increase to 800 if critic misses facts in longer tool outputs

        lines = []
        for i, t in enumerate(tool_outputs[:_MAX_TOOLS]):
            tool_name = t.get("tool", "unknown")
            tool_input = (t.get("input") or "")[:_MAX_INPUT_CHARS]
            output     = (t.get("output_preview") or "")[:_MAX_OUTPUT_CHARS]
            status     = "ERROR" if t.get("has_error") else "ok"
            lines.append(f"[{i + 1}] tool={tool_name} status={status}")
            if tool_input:
                lines.append(f"    input:  {tool_input}")
            if output:
                lines.append(f"    output: {output}")
        return "\n".join(lines) if lines else "  (no tool outputs)"
