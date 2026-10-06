# © 2024-25 Infosys Limited, Bangalore, India. All Rights Reserved.
"""
Smart Router — Auto-detects the optimal execution mode based on query signals.

Inspired by agent_os, this router analyzes query complexity and automatically
upgrades from react → orchestrator or → planned when appropriate.

Architecture:
    Query → SmartRouter.route()
      ├─ If skill has explicit execution_mode set → use that (user knows best)
      ├─ If execution_mode="react" (default) → analyze query signals:
      │   ├─ multi_domain detected (2+ skills needed) → auto-upgrade to "planned"
      │   ├─ multi_step detected (complex single-skill) → auto-upgrade to "orchestrator"
      │   └─ simple → stay with "react"
      └─ Return routing decision

Auto-routing only fires for skills with execution_mode="react" (default).
Skills with explicit modes (workflow, parallel, supervisor) are respected as-is.
"""

import json
import re
from typing import List, Dict, Any, Optional, Tuple, Callable
from dataclasses import dataclass, field

from .base import log


# ============================================================================
# Data Models
# ============================================================================

@dataclass
class RoutingDecision:
    """Result of the smart routing analysis."""
    execution_mode: str                           # Final mode to use
    complexity_class: str = "simple"              # simple | multi_step | multi_domain
    auto_upgraded: bool = False                   # True if mode was auto-detected
    detected_skills: List[str] = field(default_factory=list)  # Skills that matched
    confidence: float = 0.0                       # Routing confidence (0-1)
    reason: str = ""                              # Human-readable reason


# ============================================================================
# Signal Detection
# ============================================================================

# Multi-step signal keywords — queries that hint at complex multi-step operations
MULTI_STEP_SIGNALS = [
    r"\b(and\s+then|after\s+that|followed\s+by|next|finally|afterwards)\b",
    r"\b(step\s*\d|first.*then|compare.*with|analyze.*and.*recommend)\b",
    r"\b(create.*and.*deploy|build.*and.*test|fetch.*and.*combine)\b",
    r"\b(summarize.*across|correlate|cross-reference|combine\s+all)\b",
    r"\b(generate.*report|end.to.end|comprehensive|in-depth)\b",
    r"\b(based\s+on\s+(that|the\s+above)|using\s+the\s+results?)\b",
]

# Multi-domain conjunctive patterns
MULTI_DOMAIN_SIGNALS = [
    r"\b(as\s+well\s+as|in\s+addition\s+to|along\s+with|plus)\b",
    r"\b(also\s+(check|get|show|find|look\s+up))\b",
    r"\band\b.*\band\b",  # Multiple "and" conjunctions
]


def _count_signal_hits(query: str, patterns: List[str]) -> int:
    """Count how many signal patterns match the query."""
    hits = 0
    query_lower = query.lower()
    for pattern in patterns:
        if re.search(pattern, query_lower):
            hits += 1
    return hits


def _compute_keyword_overlap(
    query: str,
    skills: List[Dict[str, Any]],
) -> List[Tuple[str, float]]:
    """
    Compute keyword overlap between query and each available skill.
    Returns list of (skill_name, score) sorted by score descending.
    
    Scoring:
      - Exact trigger keyword match: +0.4 per match
      - Description word overlap: +0.1 per shared token (capped at 0.5)
      - Name substring match: +0.3
    """
    query_lower = query.lower()
    query_tokens = set(re.findall(r'\b\w{3,}\b', query_lower))
    scored: List[Tuple[str, float]] = []

    for skill in skills:
        score = 0.0
        name = skill.get("name", "")
        description = skill.get("description", "")
        triggers = skill.get("triggers", [])

        # Trigger keyword match
        for trigger in triggers:
            if trigger.lower() in query_lower:
                score += 0.4

        # Description overlap
        if description:
            desc_tokens = set(re.findall(r'\b\w{3,}\b', description.lower()))
            overlap = len(query_tokens & desc_tokens)
            score += min(overlap * 0.1, 0.5)

        # Name match
        name_parts = name.replace("_", " ").split()
        for part in name_parts:
            if part.lower() in query_lower:
                score += 0.3

        if score > 0:
            scored.append((name, score))

    scored.sort(key=lambda x: x[1], reverse=True)
    return scored


# ============================================================================
# LLM-Based Routing (Tier 1 - for complex cases)
# ============================================================================

ROUTING_PROMPT = """\
You are a routing classifier for a multi-skill agent system.

## User Query
"{query}"

## Available Skills
{skills_list}

## Task
Classify this query and determine which skill(s) are needed. Respond with ONLY valid JSON:

{{
  "complexity": "simple" | "multi_step" | "multi_domain",
  "primary_skill": "<skill name that best handles this query>",
  "secondary_skills": ["<other skills needed, if multi_domain>"],
  "reasoning": "<1-sentence explanation>"
}}

Classification rules:
- "simple": Query can be answered by a single skill in 1-2 steps (e.g., "check invoice 123")
- "multi_step": Query needs a single skill but requires complex orchestration (e.g., "analyze trends and generate a report with recommendations")
- "multi_domain": Query spans 2+ distinct skill domains (e.g., "check invoices AND track shipments")
"""


async def _llm_classify(
    llm: Any,
    query: str,
    skills: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """Use LLM to classify query complexity. Returns parsed classification or fallback."""
    skills_list = "\n".join(
        f"  - **{s['name']}**: {s.get('description', '(no description)')}"
        for s in skills
    )
    prompt = ROUTING_PROMPT.format(query=query, skills_list=skills_list)

    try:
        from langchain_core.messages import HumanMessage
        if hasattr(llm, 'ainvoke'):
            response = await llm.ainvoke([HumanMessage(content=prompt)])
        else:
            response = llm.invoke([HumanMessage(content=prompt)])

        raw = response.content.strip()
        if raw.startswith("```"):
            raw = re.sub(r"^```[a-z]*\n?", "", raw, flags=re.MULTILINE)
            raw = re.sub(r"\n?```$", "", raw, flags=re.MULTILINE)
            raw = raw.strip()

        return json.loads(raw)
    except Exception as e:
        log.warning(f"[SmartRouter] LLM classification failed: {e}")
        return {"complexity": "simple", "primary_skill": "", "secondary_skills": [], "reasoning": "fallback"}


# ============================================================================
# Smart Router
# ============================================================================

class SmartRouter:
    """
    Analyzes query and available skills to determine the optimal execution mode.

    Three-tier routing (fast to slow):
      Tier 1: Keyword/signal analysis (zero-latency)
      Tier 2: LLM classification (if signals are ambiguous)
      Tier 3: Skill configuration override (always wins if explicitly set)

    Auto-upgrade rules:
      - react + multi_domain → planned (fan out to multiple skills)
      - react + multi_step → orchestrator (dynamic LLM-driven delegation)
      - react + simple → react (standard ReAct loop)
    """

    # Thresholds
    MULTI_DOMAIN_MIN_SKILLS = 2        # Need 2+ skills matched to trigger multi_domain
    KEYWORD_CONFIDENCE_THRESHOLD = 0.5  # Below this, use LLM classification
    MULTI_STEP_SIGNAL_THRESHOLD = 2     # Need 2+ multi-step signals

    def __init__(
        self,
        llm: Optional[Any] = None,
        use_llm_routing: bool = True,
    ):
        self.llm = llm
        self.use_llm_routing = use_llm_routing and llm is not None

    async def route(
        self,
        query: str,
        current_skill_name: str,
        current_execution_mode: str,
        all_skills: List[Dict[str, Any]],
        worker_skills: Optional[List[Dict[str, str]]] = None,
    ) -> RoutingDecision:
        """
        Determine the optimal execution mode for this query.

        Args:
            query: User's query text
            current_skill_name: The skill that was explicitly selected/matched
            current_execution_mode: The skill's configured execution_mode
            all_skills: All available skills in this agent (for multi-domain detection)
            worker_skills: Pre-configured worker skills (for supervisor/planned)

        Returns:
            RoutingDecision with the final mode and metadata
        """
        # Tier 3: If skill has explicit non-react mode, respect it
        if current_execution_mode != "react":
            return RoutingDecision(
                execution_mode=current_execution_mode,
                complexity_class="configured",
                auto_upgraded=False,
                detected_skills=[current_skill_name],
                confidence=1.0,
                reason=f"Skill '{current_skill_name}' has explicit execution_mode='{current_execution_mode}'",
            )

        # Tier 1: Fast keyword/signal analysis
        multi_step_hits = _count_signal_hits(query, MULTI_STEP_SIGNALS)
        multi_domain_hits = _count_signal_hits(query, MULTI_DOMAIN_SIGNALS)

        # Check skill keyword overlap (how many skills match this query?)
        other_skills = [s for s in all_skills if s.get("name") != current_skill_name]
        if other_skills:
            skill_matches = _compute_keyword_overlap(query, all_skills)
            high_confidence_matches = [(name, score) for name, score in skill_matches if score >= 0.5]
        else:
            skill_matches = []
            high_confidence_matches = []

        # Fast path: Clear multi-domain (2+ strong skill matches + conjunction signals)
        if len(high_confidence_matches) >= self.MULTI_DOMAIN_MIN_SKILLS and multi_domain_hits >= 1:
            detected = [name for name, _ in high_confidence_matches[:4]]
            # Auto-upgrade to planned — fan out to multiple skills
            return RoutingDecision(
                execution_mode="planned",
                complexity_class="multi_domain",
                auto_upgraded=True,
                detected_skills=detected,
                confidence=0.85,
                reason=f"Query spans {len(detected)} skill domains: {detected}",
            )

        # Fast path: Clear multi-step
        if multi_step_hits >= self.MULTI_STEP_SIGNAL_THRESHOLD:
            # If worker_skills are configured, use orchestrator
            if worker_skills:
                return RoutingDecision(
                    execution_mode="orchestrator",
                    complexity_class="multi_step",
                    auto_upgraded=True,
                    detected_skills=[current_skill_name],
                    confidence=0.75,
                    reason=f"Complex multi-step query detected ({multi_step_hits} signals)",
                )

        # Tier 2: LLM classification (if ambiguous — some signals but not clear)
        ambiguous = (
            (multi_step_hits == 1 and len(high_confidence_matches) >= 1) or
            (multi_domain_hits >= 1 and len(high_confidence_matches) == 1) or
            (len(query.split()) > 30 and len(other_skills) >= 2)  # Long query with multiple skills available
        )

        if ambiguous and self.use_llm_routing:
            classification = await _llm_classify(self.llm, query, all_skills)
            complexity = classification.get("complexity", "simple")

            if complexity == "multi_domain":
                secondary = classification.get("secondary_skills", [])
                primary = classification.get("primary_skill", current_skill_name)
                detected = [primary] + secondary
                return RoutingDecision(
                    execution_mode="planned",
                    complexity_class="multi_domain",
                    auto_upgraded=True,
                    detected_skills=detected,
                    confidence=0.8,
                    reason=f"LLM detected multi-domain: {classification.get('reasoning', '')}",
                )

            if complexity == "multi_step" and worker_skills:
                return RoutingDecision(
                    execution_mode="orchestrator",
                    complexity_class="multi_step",
                    auto_upgraded=True,
                    detected_skills=[current_skill_name],
                    confidence=0.7,
                    reason=f"LLM detected multi-step: {classification.get('reasoning', '')}",
                )

        # Default: Stay with react
        return RoutingDecision(
            execution_mode="react",
            complexity_class="simple",
            auto_upgraded=False,
            detected_skills=[current_skill_name],
            confidence=0.9,
            reason="Simple query — standard ReAct loop",
        )
