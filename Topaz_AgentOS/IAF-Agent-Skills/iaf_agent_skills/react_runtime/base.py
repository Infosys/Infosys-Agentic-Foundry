"""Runtime protocol for React execution backends."""

from __future__ import annotations

from typing import Any, Protocol

from .types import NativeTurn


class ReactRuntime(Protocol):
    """Minimal provider-neutral protocol implemented by React runtimes."""

    name: str

    def invoke_turn(self, *, messages: list[Any], tools: list[Any], options: dict[str, Any]) -> NativeTurn:
        """Invoke one model turn and return a normalized native turn."""
        ...
