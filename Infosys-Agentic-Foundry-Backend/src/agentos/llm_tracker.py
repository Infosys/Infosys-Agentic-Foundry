# © 2024-25 Infosys Limited, Bangalore, India. All Rights Reserved.
"""
LLM Token Tracker — Per-request token and cost tracking.

Provides two integration mechanisms:
  1. LLMTokenTracker — LangChain callback handler for LangGraph agent loops
  2. record() — Manual recording for direct llm.invoke() calls

Uses Python ContextVar for async-safe per-request budget isolation.
Inspired by AgentPro's llm_tracker.py pattern.
"""

import os
import time
from contextvars import ContextVar
from typing import Any, Dict, List, Optional, Union

from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.outputs import LLMResult

try:
    from telemetry_wrapper import logger as log
except ImportError:
    import logging
    log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Model pricing (per 1,000 tokens)
# ---------------------------------------------------------------------------

MODEL_PRICING: Dict[str, Dict[str, float]] = {
    "gpt-4o":        {"input": 0.0025,  "output": 0.0100},
    "gpt-4o-mini":   {"input": 0.00015, "output": 0.0006},
    "gpt-4-turbo":   {"input": 0.0100,  "output": 0.0300},
    "gpt-4":         {"input": 0.0300,  "output": 0.0600},
    "gpt-35-turbo":  {"input": 0.0005,  "output": 0.0015},
    "gpt-3.5-turbo": {"input": 0.0005,  "output": 0.0015},
    "o1-mini":       {"input": 0.0030,  "output": 0.0120},
    "o1":            {"input": 0.0150,  "output": 0.0600},
    "o3-mini":       {"input": 0.0011,  "output": 0.0044},
}

DEFAULT_PRICING = {"input": 0.0025, "output": 0.0100}


def _get_pricing(model_name: str) -> Dict[str, float]:
    """Match model name to pricing (case-insensitive substring match)."""
    name_lower = model_name.lower() if model_name else ""
    for key, pricing in MODEL_PRICING.items():
        if key.lower() in name_lower:
            return pricing
    return DEFAULT_PRICING


def _compute_cost(model: str, prompt_tokens: int, completion_tokens: int) -> float:
    """Compute cost in USD from token counts."""
    pricing = _get_pricing(model)
    return (prompt_tokens * pricing["input"] + completion_tokens * pricing["output"]) / 1000.0


# ---------------------------------------------------------------------------
# Per-request budget (ContextVar — async-safe, no locks)
# ---------------------------------------------------------------------------

_budget: ContextVar[Optional[Dict]] = ContextVar("llm_budget", default=None)


def start_budget(trace_id: str = "") -> Dict:
    """Start a new per-request budget. Call at the beginning of each request."""
    budget = {
        "trace_id": trace_id,
        "calls": [],
        "total_prompt_tokens": 0,
        "total_completion_tokens": 0,
        "total_cost_usd": 0.0,
        "total_llm_calls": 0,
        "total_llm_duration_ms": 0.0,
    }
    _budget.set(budget)
    log.info(f"[LLMTracker] Budget started for trace={trace_id}")
    return budget


def end_budget() -> Optional[Dict]:
    """
    End the current budget and return summary.
    Returns None if no budget was active.
    """
    budget = _budget.get()
    if budget is None:
        return None

    # Build by-purpose summary
    by_purpose: Dict[str, Dict] = {}
    for call in budget["calls"]:
        p = call["purpose"]
        if p not in by_purpose:
            by_purpose[p] = {"calls": 0, "prompt_tokens": 0, "completion_tokens": 0, "cost_usd": 0.0}
        by_purpose[p]["calls"] += 1
        by_purpose[p]["prompt_tokens"] += call.get("prompt_tokens", 0)
        by_purpose[p]["completion_tokens"] += call.get("completion_tokens", 0)
        by_purpose[p]["cost_usd"] += call.get("cost_usd", 0.0)

    summary = {
        "trace_id": budget["trace_id"],
        "total_prompt_tokens": budget["total_prompt_tokens"],
        "total_completion_tokens": budget["total_completion_tokens"],
        "total_cost_usd": round(budget["total_cost_usd"], 6),
        "total_llm_calls": budget["total_llm_calls"],
        "total_llm_duration_ms": round(budget["total_llm_duration_ms"], 1),
        "by_purpose": by_purpose,
        "calls": budget["calls"],
    }

    _budget.set(None)
    log.info(
        f"[LLMTracker] Budget ended: {summary['total_llm_calls']} calls, "
        f"{summary['total_prompt_tokens']}+{summary['total_completion_tokens']} tokens, "
        f"${summary['total_cost_usd']:.4f}"
    )
    return summary


def _append_call(
    purpose: str,
    model: str,
    prompt_tokens: int,
    completion_tokens: int,
    duration_ms: float,
    error: str = "",
):
    """Append a completed LLM call to the current budget."""
    budget = _budget.get()
    if budget is None:
        return  # No active budget — silently skip

    cost = _compute_cost(model, prompt_tokens, completion_tokens)
    call_entry = {
        "purpose": purpose,
        "model": model or "unknown",
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "cost_usd": round(cost, 6),
        "duration_ms": round(duration_ms, 1),
        "call_index": len(budget["calls"]),
        "error": error or "",
    }
    budget["calls"].append(call_entry)
    budget["total_prompt_tokens"] += prompt_tokens
    budget["total_completion_tokens"] += completion_tokens
    budget["total_cost_usd"] += cost
    budget["total_llm_calls"] += 1
    budget["total_llm_duration_ms"] += duration_ms

    # Also feed into the litellm_standalone_tracker per-request accumulator so
    # the Kafka worker can persist skill-agent token usage to token_usage_logs.
    # Wrapped in try/except so it never affects existing budget tracking.
    if not error and (prompt_tokens > 0 or completion_tokens > 0):
        try:
            from telemetry_wrapper import _session_context
            from litellm_standalone_tracker import record_to_accumulator, calculate_cost
            ctx = _session_context.get()
            session_id = ctx.get('session_id')
            if session_id and session_id != 'Unassigned':
                costs = calculate_cost(model, prompt_tokens, completion_tokens, 0)
                record_to_accumulator(session_id, {
                    "model":             model or "unknown",
                    "agent_name":        ctx.get('agent_name'),
                    "prompt_tokens":     prompt_tokens,
                    "completion_tokens": completion_tokens,
                    "total_tokens":      prompt_tokens + completion_tokens,
                    "cached_tokens":     0,
                    "prompt_cost":       costs["prompt_cost"],
                    "completion_cost":   costs["completion_cost"],
                    "cached_cost":       costs.get("cached_cost", 0.0),
                    "total_cost":        costs["total_cost"],
                    "call_category":     ctx.get('call_category') or "agent_inference",
                    "call_sub_category": purpose,  # e.g. "agent", "router", "memory"
                    "status":            "success",
                })
        except Exception:
            pass  # Never break existing budget tracking


# ---------------------------------------------------------------------------
# Manual record() — for direct llm.invoke() calls
# ---------------------------------------------------------------------------

def record(
    purpose: str,
    response: Any,
    duration_ms: float,
    model: str = "",
) -> None:
    """
    Record an LLM invocation from a direct llm.invoke() call.

    Args:
        purpose: Label like "router", "memory", "skill_executor", etc.
        response: The LangChain response (AIMessage or LLMResult).
        duration_ms: Wall-clock duration of the call.
        model: Model name (optional — extracted from response if available).
    """
    prompt_tokens = 0
    completion_tokens = 0
    error = ""

    try:
        # Try to extract from response_metadata (AIMessage)
        if hasattr(response, "response_metadata"):
            meta = response.response_metadata or {}
            usage = meta.get("token_usage") or meta.get("usage") or {}
            prompt_tokens = usage.get("prompt_tokens", 0) or usage.get("input_tokens", 0)
            completion_tokens = usage.get("completion_tokens", 0) or usage.get("output_tokens", 0)
            if not model:
                model = meta.get("model_name", meta.get("model", ""))

        # Try usage_metadata (newer LangChain)
        elif hasattr(response, "usage_metadata"):
            usage = response.usage_metadata or {}
            prompt_tokens = usage.get("input_tokens", 0)
            completion_tokens = usage.get("output_tokens", 0)

    except Exception as e:
        error = str(e)
        log.warning(f"[LLMTracker] Failed to extract tokens from response: {e}")

    _append_call(purpose, model, prompt_tokens, completion_tokens, duration_ms, error)


# ---------------------------------------------------------------------------
# LangChain Callback Handler — for LangGraph agent loops
# ---------------------------------------------------------------------------

class LLMTokenTracker(BaseCallbackHandler):
    """
    LangChain BaseCallbackHandler that records token usage to the
    per-request budget.

    Usage:
        tracker = LLMTokenTracker("agent")
        config = {"callbacks": [tracker]}
        # Pass to LangGraph .invoke() or .ainvoke()
    """

    def __init__(self, purpose: str = "agent"):
        super().__init__()
        self.purpose = purpose
        self._call_starts: Dict[str, float] = {}

    def on_llm_start(self, serialized: Dict, prompts: List[str], *, run_id, **kwargs):
        self._call_starts[str(run_id)] = time.time()

    def on_chat_model_start(self, serialized: Dict, messages: List, *, run_id, **kwargs):
        self._call_starts[str(run_id)] = time.time()

    def on_llm_end(self, response: LLMResult, *, run_id, **kwargs):
        start_time = self._call_starts.pop(str(run_id), None)
        duration_ms = (time.time() - start_time) * 1000 if start_time else 0.0

        prompt_tokens = 0
        completion_tokens = 0
        model = ""

        try:
            if response.llm_output:
                usage = response.llm_output.get("token_usage", {})
                prompt_tokens = usage.get("prompt_tokens", 0)
                completion_tokens = usage.get("completion_tokens", 0)
                model = response.llm_output.get("model_name", "")

            # Fallback: check generation info
            if not prompt_tokens and response.generations:
                for gen_list in response.generations:
                    for gen in gen_list:
                        info = getattr(gen, "generation_info", {}) or {}
                        usage = info.get("usage", {})
                        prompt_tokens += usage.get("prompt_tokens", 0)
                        completion_tokens += usage.get("completion_tokens", 0)
        except Exception as e:
            log.warning(f"[LLMTokenTracker] Error extracting tokens: {e}")

        _append_call(self.purpose, model, prompt_tokens, completion_tokens, duration_ms)

    def on_llm_error(self, error: BaseException, *, run_id, **kwargs):
        start_time = self._call_starts.pop(str(run_id), None)
        duration_ms = (time.time() - start_time) * 1000 if start_time else 0.0
        _append_call(self.purpose, "", 0, 0, duration_ms, str(error))


# ---------------------------------------------------------------------------
# Utility: Format budget summary for user display
# ---------------------------------------------------------------------------

def format_budget_summary(budget: Optional[Dict]) -> str:
    """Format a budget summary dict into a human-readable string."""
    if not budget:
        return "No LLM usage data available."

    total = budget["total_prompt_tokens"] + budget["total_completion_tokens"]
    lines = [
        f"LLM Usage: {budget['total_llm_calls']} calls, {total:,} tokens "
        f"({budget['total_prompt_tokens']:,} in + {budget['total_completion_tokens']:,} out), "
        f"${budget['total_cost_usd']:.4f} USD, "
        f"{budget['total_llm_duration_ms']:.0f}ms",
    ]

    if budget.get("by_purpose"):
        lines.append("  Breakdown:")
        for purpose, stats in budget["by_purpose"].items():
            t = stats["prompt_tokens"] + stats["completion_tokens"]
            lines.append(f"    {purpose}: {stats['calls']} calls, {t:,} tokens, ${stats['cost_usd']:.4f}")

    return "\n".join(lines)
