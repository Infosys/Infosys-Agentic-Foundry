"""Stable AgentOS extension contracts.

This package is intentionally dependency-free. It defines the descriptor types
and Protocols that external adapters can implement without importing the full
AgentPro engine.
"""

from .host import (
    EvidenceSink,
    MissionRuntimeBridge,
)
from .providers import (
    HookProvider,
    RouterProvider,
    SkillProvider,
    ToolProvider,
    TraceProvider,
)
from .react_runtime import (
    DEFAULT_REACT_RUNTIME,
    VALID_REACT_RUNTIMES,
    ReactRuntimeSelection,
    resolve_react_runtime,
)
from .skill import Skill
from .storage import (
    BACKEND_POSTGRES,
    BACKEND_SQLITE,
    VALID_BACKENDS,
    KnowledgeStore,
    StorageEngine,
)

__all__ = [
    "Skill",
    "SkillProvider",
    "RouterProvider",
    "ToolProvider",
    "HookProvider",
    "TraceProvider",
    "EvidenceSink",
    "MissionRuntimeBridge",
    "DEFAULT_REACT_RUNTIME",
    "VALID_REACT_RUNTIMES",
    "ReactRuntimeSelection",
    "resolve_react_runtime",
    "StorageEngine",
    "KnowledgeStore",
    "BACKEND_SQLITE",
    "BACKEND_POSTGRES",
    "VALID_BACKENDS",
]
