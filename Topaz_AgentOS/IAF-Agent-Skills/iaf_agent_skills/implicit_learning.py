"""
Implicit Learning Functions for SkillAgent.

Extracted from agent.py to improve modularity.
This module handles:
- append_learning() → safely append learning entries to JSONL files
- _analyze_implicit_feedback() → LLM-based implicit signal detection
- _triage_implicit_signal() → determine if signal gets auto-confirmed

USAGE:
    from iaf_agent_skills.implicit_learning import (
        append_learning,
        analyze_implicit_feedback,
        triage_implicit_signal,
        IMPLICIT_CONFIDENCE_THRESHOLDS,
        IMPLICIT_TYPE_MAP,
    )

DEPENDENCIES:
    - SafeKernel (for agent_root path)
    - datetime, json, os, logging, file_lock.portable_lock
    - LangChain (for LLM calls in analyze)
"""

import os
import json
import logging

from agent_os.safe_path import safe_join_under_root, validated_path

from .file_lock import portable_lock
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, List, Optional

logger = logging.getLogger(__name__)



IMPLICIT_CONFIDENCE_THRESHOLDS = {
    "correction":        1.0,
    "preference_update": 1.0,
    "skill_error":       1.0,
    "rephrase":          1.0,
    "more_detail":       1.0,
    "successful_pattern": 1.0,
}

# Map implicit feedback signal type → knowledge_type for write_knowledge()
IMPLICIT_TYPE_MAP = {
    "correction":        "correction",
    "preference_update": "preference",
    "skill_error":       "exception",
    "rephrase":          "pattern",
    "more_detail":       "pattern",
    "successful_pattern": "skill_pattern",
}



def append_learning(
    *,
    learning_type: str,
    content: dict,
    skill_name: Optional[str],
    session_id: str,
    user_id: Optional[str],
    agent_root: Path,
) -> Path:
    """
    Safely append a learning entry to memory files.
    Uses file locking to prevent concurrent write corruption.
    
    Args:
        learning_type: Category of learning (e.g., "tool_execution", "agent_error", "feedback")
        content: The learning data to append
        skill_name: Optional skill name for skill-scoped learnings.
                   If provided, learning is stored in learnings/{skill_name}/{type}.jsonl
                   If None, stored in learnings/general/{type}.jsonl
        session_id: Current session ID for tracking
        user_id: Current user ID for tracking
        agent_root: Path to agent root directory
        
    Returns:
        Path to the learning file
    """
    entry = {
        "timestamp": datetime.now().isoformat(),
        "session_id": session_id,
        "user_id": user_id,
        "type": learning_type,
        "skill": skill_name,  # Track skill even in general folder
        "content": content
    }
    
    learnings_root = validated_path(agent_root, label="agent_root") / "memory" / "learnings"
    learning_dir = safe_join_under_root(
        learnings_root, skill_name or "general", label="learning skill dir"
    )
    learning_file = safe_join_under_root(
        learning_dir, f"{learning_type}.jsonl", label="learning file"
    )
    learning_dir.mkdir(parents=True, exist_ok=True)
    
    # Use file locking to prevent concurrent write corruption
    with portable_lock(learning_file):
        with open(learning_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry) + "\n")
            f.flush()
    
    return learning_file



def analyze_implicit_feedback(
    *,
    query: str,
    response: str,
    prev_user_msg: Optional[str],
    skill_name: str,
    tool_calls_log: list,
    light_llm: Any,
    confidence_thresholds: Dict[str, float] = None,
) -> List[Dict[str, Any]]:
    """
    Analyze a conversation exchange for implicit learning signals.

    Uses light_llm (cheap/fast model) to detect corrections, preference
    changes, rephrases, and other learning opportunities that the explicit
    <!-- LEARN --> marker system may miss.

    Args:
        query: Current user query
        response: Agent's response
        prev_user_msg: Previous user message for context
        skill_name: Current skill name
        tool_calls_log: List of tool calls made
        light_llm: LangChain LLM instance for analysis
        confidence_thresholds: Override default thresholds (optional)

    Returns:
        List of dicts: [{"type", "summary", "applies_when", "confidence"}]
        Returns [] when nothing is worth learning or on any error.
    """
    # Feature flag — env var opt-out
    if os.getenv("IMPLICIT_FEEDBACK", "true").lower() != "true":
        return []

    # Require light_llm
    if not light_llm:
        logger.warning("Implicit feedback: light_llm not available, skipping")
        return []

    thresholds = confidence_thresholds or IMPLICIT_CONFIDENCE_THRESHOLDS

    from langchain_core.messages import HumanMessage

    prompt = f"""Analyze this conversation exchange for implicit learning signals.
Return a JSON array of objects (empty [] if nothing worth learning).

Previous user message: {(prev_user_msg or 'N/A')[:200]}
Current user message:  {query[:500]}
Agent response:        {response[:2000]}
Tools used:            {', '.join(str(t) for t in (tool_calls_log or []))[:300]}

Signal types to detect:
- correction:         User corrects the agent ("no, I meant...", "that's wrong", "don't do X")
- preference_update:  User states a preference ("I prefer X", "always use Y", "never do Z")
- skill_error:        Tool failed and user had to intervene or retry
- rephrase:           User rephrased the same request (agent may have misunderstood first time)
- more_detail:        User asks for elaboration ("can you explain?", "give me more detail")
- successful_pattern: User accepted the response and it reveals a reusable fact or pattern

Rules:
- Return ONLY a JSON array. No markdown, no explanation.
- Each object: {{"type": "...", "summary": "<concise actionable learning, max 100 chars>", "applies_when": "<context>", "confidence": 0.0-1.0}}
- Return [] if this is a routine Q&A with no learning signal.
- Maximum 2 signals per exchange.
- Be conservative — only flag clear, unambiguous signals."""

    try:
        result = light_llm.invoke(
            [HumanMessage(content=prompt)],
            timeout=15,  # Hard timeout to avoid blocking background thread
        )
        raw = result.content.strip()

        # Strip markdown code fences if present (e.g., ```json ... ```)
        if raw.startswith("```"):
            raw = raw.split("\n", 1)[-1].rsplit("```", 1)[0].strip()

        signals = json.loads(raw)
        if not isinstance(signals, list):
            return []

        # Validate each signal has required fields
        valid = []
        for s in signals[:2]:  # Cap at 2
            if (isinstance(s, dict)
                    and s.get("type") in thresholds
                    and s.get("summary")):
                s.setdefault("confidence", 0.5)
                s.setdefault("applies_when", "")
                valid.append(s)
        return valid

    except json.JSONDecodeError:
        logger.warning("Implicit feedback: LLM returned non-JSON, skipping")
        return []
    except Exception as e:
        logger.warning("Implicit feedback analysis failed (non-fatal): %s", e)
        return []


def triage_implicit_signal(
    signal: dict,
    confidence_thresholds: Dict[str, float] = None,
) -> str:
    """
    Determine knowledge status based on signal type and confidence.

    High-confidence signals (above per-type threshold) are auto-confirmed.
    Low-confidence signals go to pending_review for human approval in the
    Knowledge dashboard.

    Args:
        signal: Dict with "type" and "confidence" keys
        confidence_thresholds: Override default thresholds (optional)

    Returns:
        "confirmed" or "pending_review"
    """
    thresholds = confidence_thresholds or IMPLICIT_CONFIDENCE_THRESHOLDS
    sig_type = signal.get("type", "")
    confidence = float(signal.get("confidence", 0.0))
    threshold = thresholds.get(sig_type, 0.8)
    return "confirmed" if confidence >= threshold else "pending_review"


# Type hint for Any (avoid full typing import for light_llm)
from typing import Any
