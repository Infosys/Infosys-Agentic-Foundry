"""
LLM Token Tracker — per-request cost and attribution tracking.

Design
------
Two mechanisms work together, covering all 18 LLM call sites:

1. LLMTokenTracker (BaseCallbackHandler)
   For LangGraph agent invocations. LangGraph propagates callbacks through
   every node and every LLM call in the graph automatically.
   Usage: pass via config={"callbacks": [LLMTokenTracker("agent")]}

2. record() function
   For direct llm.invoke() calls outside LangGraph (router, memory, planner, etc.).
   Call after any llm.invoke() with the response object.
   Usage: llm_tracker.record("router", response, duration_ms, model)

Both write into a ContextVar budget dict — async-safe, per-request, no locks.
Python 3.9+ asyncio.to_thread() propagates ContextVar automatically.

Budget lifecycle
----------------
  start_budget(trace_id)   — call at trace begin (agent.py)
  ... LLM calls happen ...
  end_budget()             — call at trace end, returns summary for trace metadata
"""

from __future__ import annotations

import time
from contextvars import ContextVar
from pathlib import Path
from typing import Any, Dict, List, Optional


_PRICING: Dict[str, Dict[str, float]] = {}

def _load_pricing() -> None:
    global _PRICING
    # Search for model_pricing.yaml relative to this file
    candidates = [
        Path(__file__).parent.parent.parent / "agent_os" / "model_pricing.yaml",
        Path(__file__).parent.parent / "agent_os" / "model_pricing.yaml",
        Path(__file__).parent / "model_pricing.yaml",
    ]
    for path in candidates:
        if path.exists():
            try:
                import yaml
                with open(path, encoding="utf-8") as f:
                    data = yaml.safe_load(f) or {}
                _PRICING = data.get("models", {})
                return
            except Exception:
                pass

_load_pricing()

_DEFAULT_PRICING = {"input": 0.002500, "output": 0.010000}  # gpt-5.2-chat fallback (update when pricing known)


def _calc_cost(model: str, prompt: int, completion: int) -> float:
    model_lower = (model or "").lower()
    pricing = _DEFAULT_PRICING
    for key, val in _PRICING.items():
        if key in model_lower:
            pricing = val
            break
    return round(
        (prompt / 1000) * pricing.get("input", 0)
        + (completion / 1000) * pricing.get("output", 0),
        8,
    )



_budget: ContextVar[Optional[Dict]] = ContextVar("llm_budget", default=None)


def start_budget(trace_id: str) -> Dict:
    """Call at the start of each trace (after begin_trace). Returns the budget dict."""
    budget: Dict = {
        "trace_id": trace_id,
        "calls": [],
        "summary": {
            "total_prompt_tokens": 0,
            "total_completion_tokens": 0,
            "total_cost_usd": 0.0,
            "total_llm_calls": 0,
            "total_llm_duration_ms": 0.0,
            "by_purpose": {},
        },
    }
    _budget.set(budget)
    return budget


def end_budget() -> Optional[Dict]:
    """Call at trace end. Returns the final budget dict and clears the ContextVar."""
    budget = _budget.get()
    _budget.set(None)
    return budget


def get_budget() -> Optional[Dict]:
    """Read current budget without clearing (for inspection)."""
    return _budget.get()


def extract_usage(response: Any) -> tuple[int, int]:
    """Public wrapper for callers that need to carry usage across boundaries."""
    return _extract_usage(response)


def estimate_cost(model: str, prompt_tokens: int, completion_tokens: int) -> float:
    """Estimate USD cost using the same pricing table as tracked LLM calls."""
    return _calc_cost(model, prompt_tokens, completion_tokens)


def record_usage(
    purpose: str,
    *,
    model: str = "",
    prompt_tokens: int = 0,
    completion_tokens: int = 0,
    duration_ms: float = 0.0,
    error: Optional[str] = None,
) -> None:
    """Record already-extracted token usage into the active request budget."""
    _append_call(purpose, model, int(prompt_tokens or 0), int(completion_tokens or 0), duration_ms, error)


def _append_call(purpose: str, model: str, prompt_tokens: int,
                 completion_tokens: int, duration_ms: float, error: Optional[str]) -> None:
    """Append one call record to the active budget. Called by both record() and the callback."""
    budget = _budget.get()
    if budget is None:
        return

    cost = _calc_cost(model, prompt_tokens, completion_tokens)

    budget["calls"].append({
        "purpose": purpose,
        "model": model,
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "cost_usd": cost,
        "duration_ms": round(duration_ms, 1),
        "call_index": len(budget["calls"]) + 1,
        "error": error,
    })

    s = budget["summary"]
    s["total_prompt_tokens"] += prompt_tokens
    s["total_completion_tokens"] += completion_tokens
    s["total_cost_usd"] = round(s["total_cost_usd"] + cost, 8)
    s["total_llm_calls"] += 1
    s["total_llm_duration_ms"] += duration_ms

    bp = s["by_purpose"].setdefault(purpose, {
        "calls": 0, "prompt_tokens": 0, "completion_tokens": 0,
        "cost_usd": 0.0, "duration_ms": 0.0,
    })
    bp["calls"] += 1
    bp["prompt_tokens"] += prompt_tokens
    bp["completion_tokens"] += completion_tokens
    bp["cost_usd"] = round(bp["cost_usd"] + cost, 8)
    bp["duration_ms"] += duration_ms


def _extract_usage(response: Any) -> tuple[int, int]:
    """Extract (prompt_tokens, completion_tokens) from any LangChain response object."""
    if response is None:
        return 0, 0
    usage = (
        getattr(response, "usage_metadata", None)
        or getattr(response, "response_metadata", {}).get("token_usage")
    )
    if usage and isinstance(usage, dict):
        p = int(usage.get("input_tokens") or usage.get("prompt_tokens") or 0)
        c = int(usage.get("output_tokens") or usage.get("completion_tokens") or 0)
        return p, c
    return 0, 0


def record(purpose: str, response: Any, duration_ms: float = 0.0,
           model: str = "", error: Optional[str] = None) -> None:
    """
    Record a direct llm.invoke() call.

    Call immediately after any llm.invoke() / light_llm.invoke() that lives
    outside of LangGraph (router, memory, planner, knowledge_query, etc.).

    Example:
        t0 = time.time() * 1000
        result = self.llm.invoke(messages)
        llm_tracker.record("router", result, time.time()*1000 - t0,
                           getattr(self.llm, 'azure_deployment', ''))
    """
    if error:
        _append_call(purpose, model, 0, 0, duration_ms, error)
        return
    prompt_tokens, completion_tokens = _extract_usage(response)
    _append_call(purpose, model, prompt_tokens, completion_tokens, duration_ms, None)



try:
    from langchain_core.callbacks import BaseCallbackHandler

    class LLMTokenTracker(BaseCallbackHandler):
        """
        LangChain callback handler for LangGraph agent invocations.

        LangGraph propagates callbacks to every LLM node in the graph,
        including all tool-use loop iterations. Add alongside TraceToolCallback:

            config={"callbacks": [_tool_cb, LLMTokenTracker("agent")]}

        Each instance tags calls with `purpose` so the budget can distinguish
        agent vs router vs memory calls even if they share the same callback list.
        """

        def __init__(self, purpose: str = "agent") -> None:
            super().__init__()
            self._purpose = purpose
            self._starts: Dict[str, float] = {}   # run_id → start epoch ms
            self._models: Dict[str, str] = {}     # run_id → model name (captured at start)

        def on_llm_start(self, serialized: Dict, prompts: List, *,
                         run_id: Any, **kwargs: Any) -> None:
            rid = str(run_id)
            self._starts[rid] = time.time() * 1000
            self._models[rid] = (serialized or {}).get("kwargs", {}).get("model", "") or ""

        def on_chat_model_start(self, serialized: Dict, messages: List, *,
                                run_id: Any, **kwargs: Any) -> None:
            rid = str(run_id)
            self._starts[rid] = time.time() * 1000
            # Capture model name at start — available before on_llm_end fires
            kwargs_dict = (serialized or {}).get("kwargs", {})
            self._models[rid] = (
                kwargs_dict.get("model")
                or kwargs_dict.get("model_name")
                or kwargs_dict.get("azure_deployment")
                or ""
            )

        def on_llm_end(self, response: Any, *, run_id: Any, **kwargs: Any) -> None:
            rid = str(run_id)
            start = self._starts.pop(rid, time.time() * 1000)
            duration_ms = time.time() * 1000 - start

            # Model name: prefer llm_output → generation_info → captured at start
            llm_out = getattr(response, "llm_output", None) or {}
            model = (
                llm_out.get("model_name")
                or llm_out.get("azure_deployment")
                or llm_out.get("model")
                or ""
            )

            # Tokens: try llm_output first.
            # OpenAI uses "token_usage"; Anthropic uses "usage" with input_tokens/output_tokens.
            prompt_tokens, completion_tokens = 0, 0
            token_usage = llm_out.get("token_usage") or llm_out.get("usage") or {}
            if token_usage:
                prompt_tokens = int(token_usage.get("prompt_tokens") or token_usage.get("input_tokens") or 0)
                completion_tokens = int(token_usage.get("completion_tokens") or token_usage.get("output_tokens") or 0)

            if not prompt_tokens:
                for gen_list in (getattr(response, "generations", None) or []):
                    for gen in gen_list:
                        # Try AIMessage.usage_metadata first (ChatAnthropicThinking and similar custom models)
                        msg = getattr(gen, "message", None)
                        if msg is not None:
                            um = getattr(msg, "usage_metadata", None)
                            if um and isinstance(um, dict):
                                prompt_tokens += int(um.get("input_tokens") or um.get("prompt_tokens") or 0)
                                completion_tokens += int(um.get("output_tokens") or um.get("completion_tokens") or 0)
                            if not model:
                                rm = getattr(msg, "response_metadata", None) or {}
                                model = rm.get("model") or rm.get("model_name") or ""
                        if not prompt_tokens:
                            info = getattr(gen, "generation_info", None) or {}
                            u = (
                                info.get("usage")
                                or info.get("usage_metadata")
                                or info.get("token_usage")
                                or {}
                            )
                            if u:
                                prompt_tokens += int(u.get("input_tokens") or u.get("prompt_tokens") or 0)
                                completion_tokens += int(u.get("output_tokens") or u.get("completion_tokens") or 0)
                            if not model:
                                model = info.get("model") or info.get("model_name") or ""

            # Final fallback: model name saved at on_chat_model_start / on_llm_start
            if not model:
                model = self._models.pop(rid, "")
            else:
                self._models.pop(rid, None)

            _append_call(self._purpose, model, prompt_tokens, completion_tokens, duration_ms, None)

        def on_llm_error(self, error: Any, *, run_id: Any, **kwargs: Any) -> None:
            rid = str(run_id)
            start = self._starts.pop(rid, time.time() * 1000)
            model = self._models.pop(rid, "")
            duration_ms = time.time() * 1000 - start
            _append_call(self._purpose, model, 0, 0, duration_ms,
                         f"{type(error).__name__}: {str(error)[:200]}")

except ImportError:
    # langchain_core not available — define no-op stub so imports don't fail
    class LLMTokenTracker:  # type: ignore
        def __init__(self, purpose: str = "agent") -> None:
            pass
