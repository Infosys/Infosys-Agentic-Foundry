"""Recursive Language Model (RLM) support for AgentOS — Phase 0-1 (analytical, read-only).

This package keeps large context OUT of the model's window: the context is offloaded into a
per-session store and queried on demand by a recursive, read-only RLM (``context_query`` tool).
It is additive and opt-in via ``context_loading_mode: rlm`` (+ env ``RLM_ENABLED``); with the flag
off nothing here runs and behaviour is unchanged.

Public API:
    run_rlm(model_call, context, query, ...)  -> (answer, metrics)
    get_context_store()                        -> ContextStore singleton
"""
from .context_store import ContextStore, get_context_store
from .engine import RLMCancelled, run_rlm

__all__ = ["run_rlm", "RLMCancelled", "ContextStore", "get_context_store"]
