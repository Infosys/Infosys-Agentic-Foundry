"""Pass-through MemoryCapability facade over the existing AgentMemory runtime.

Phase 2 intentionally keeps the filesystem JSONL, SQLite index, vector backend,
and implicit learning behavior owned by the current modules. This facade is the
adapter boundary only; it delegates to the same locked write paths.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional


MEMORY_CAPABILITY_FLAG = "IAF_MEMORY_CAPABILITY_ENABLED"


class MemoryCapabilityContextError(RuntimeError):
    """Raised when a background memory write lacks explicit runtime context."""


def memory_capability_enabled(env: Optional[Dict[str, str]] = None) -> bool:
    """Return True only when the staged memory adapter flag is explicitly enabled."""
    source = env if env is not None else os.environ
    value = str(source.get(MEMORY_CAPABILITY_FLAG, "false")).strip().lower()
    return value in {"1", "true", "yes", "on"}


class MemoryCapability:
    """Thin pass-through adapter over AgentMemory and implicit learning writes."""

    _SUPPORTED = [
        "append_learning",
        "format_context_for_prompt",
        "grep_context_graph",
        "log_episode",
        "query_knowledge",
        "upsert_session",
        "write_knowledge",
    ]

    def __init__(
        self,
        agent_memory: Any,
        *,
        append_learning_fn: Optional[Callable[..., Path]] = None,
        agent_root: Optional[Path] = None,
        session_id: Optional[str] = None,
        user_id: Optional[str] = None,
    ) -> None:
        self._memory = agent_memory
        self._append_learning_fn = append_learning_fn
        self._agent_root = Path(agent_root) if agent_root is not None else None
        self._session_id = session_id
        self._user_id = user_id

    def metadata(self) -> Dict[str, Any]:
        """Return snapshot-safe capability metadata without provider objects."""
        return {
            "mode": "pass_through",
            "backing_store": "filesystem+sqlite",
            "writes_default": "direct_memory",
            "enable_flag": MEMORY_CAPABILITY_FLAG,
            "provider_status": "deferred_parity_required",
            "runtime_resolution": "direct_memory_until_flag_enabled",
            "defer_reason": "memory changes alter agent behavior and require corpus parity evidence",
            "supports": list(self._SUPPORTED),
        }

    @property
    def agent_memory(self) -> Any:
        return self._memory

    def log_episode(self, **kwargs: Any) -> Any:
        return self._memory.log_episode(**kwargs)

    def write_knowledge(self, **kwargs: Any) -> str:
        return self._memory.write_knowledge(**kwargs)

    def query_knowledge(self, **kwargs: Any) -> Dict[str, Any]:
        return self._memory.query_knowledge(**kwargs)

    def grep_context_graph(self, keywords: List[str], max_results: int = 50) -> List[Dict[str, Any]]:
        return self._memory.grep_context_graph(keywords, max_results=max_results)

    def format_context_for_prompt(self, grep_results: List[Dict[str, Any]], max_chars: int = 2000) -> str:
        return self._memory.format_context_for_prompt(grep_results, max_chars=max_chars)

    def append_learning(
        self,
        *,
        learning_type: str,
        content: dict,
        skill_name: Optional[str] = None,
    ) -> Path:
        missing = []
        if self._append_learning_fn is None:
            missing.append("append_learning_fn")
        if self._agent_root is None:
            missing.append("agent_root")
        if missing:
            raise MemoryCapabilityContextError(
                "background_context_missing: " + ", ".join(missing) + " required for append_learning"
            )

        session_id = self._session_id or getattr(self._memory, "session_id", None)
        if not session_id:
            raise MemoryCapabilityContextError(
                "background_context_missing: session_id is required for append_learning"
            )

        user_id = self._user_id if self._user_id is not None else getattr(self._memory, "user_id", None)
        return self._append_learning_fn(
            learning_type=learning_type,
            content=content,
            skill_name=skill_name,
            session_id=session_id,
            user_id=user_id,
            agent_root=self._agent_root,
        )

    def upsert_session(self, **kwargs: Any) -> Any:
        session_id = kwargs.get("session_id") or getattr(self._memory, "session_id", None)
        if not session_id:
            raise MemoryCapabilityContextError(
                "background_context_missing: session_id is required for upsert_session"
            )

        payload = dict(kwargs)
        payload.setdefault("session_id", session_id)
        payload.setdefault("tenant_id", getattr(self._memory, "tenant_id", ""))
        payload.setdefault("agent_id", getattr(self._memory, "agent_id", ""))
        payload.setdefault("user_id", getattr(self._memory, "user_id", None))
        payload.setdefault("title", "")
        payload.setdefault("first_message", "")
        payload.setdefault("skill", "")
        payload.setdefault("parent_session_id", None)
        payload.setdefault("jsonl_path", "")
        return self._memory.conversation_manager.upsert_session(**payload)


__all__ = [
    "MEMORY_CAPABILITY_FLAG",
    "MemoryCapability",
    "MemoryCapabilityContextError",
    "memory_capability_enabled",
]
