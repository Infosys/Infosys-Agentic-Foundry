"""Default ToolProvider backed by existing tool factory functions."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, Optional

from iaf_agent_skills.tool_factory import (
    create_create_plan_tool,
    create_fetch_canonical_tool,
    create_invoke_plan_tool,
    create_invoke_skill_tool,
    create_jev_tool,
    create_jev_verify_tool,
    create_jev_vision_tool,
    create_jev_vision_verify_tool,
    create_memory_tool,
    create_shell_tool,
    create_sql_tool,
    create_write_file_tool,
)
from iaf_agent_skills.tools.skill_tool_loader import load_skill_tools


class BuiltinToolProvider:
    """Compatibility wrapper around the built-in AgentPro tool factory."""

    name = "builtin"

    def create_shell_tool(self, kernel: Any, auto_run: bool = True) -> Any:
        return create_shell_tool(kernel, auto_run=auto_run)

    def create_sql_tool(self, kernel: Any, sql_write_allowed: bool = False, indexer: Any = None, connections: Any = None) -> Any:
        return create_sql_tool(kernel, sql_write_allowed=sql_write_allowed, indexer=indexer, connections=connections)

    def create_fetch_canonical_tool(self, kernel: Any) -> Any:
        return create_fetch_canonical_tool(kernel)

    def create_write_file_tool(self, kernel: Any) -> Any:
        return create_write_file_tool(kernel)

    def create_jev_tool(self, confidence_threshold: float = 0.90) -> Any:
        return create_jev_tool(confidence_threshold=confidence_threshold)

    def create_jev_verify_tool(self, kernel: Any, confidence_threshold: float = 0.80) -> Any:
        return create_jev_verify_tool(kernel, confidence_threshold=confidence_threshold)

    def create_jev_vision_tool(self, confidence_threshold: float = 0.80) -> Any:
        return create_jev_vision_tool(confidence_threshold=confidence_threshold)

    def create_jev_vision_verify_tool(self, kernel: Any, confidence_threshold: float = 0.65) -> Any:
        return create_jev_vision_verify_tool(kernel, confidence_threshold=confidence_threshold)

    def create_memory_tool(
        self,
        memory: Any,
        get_retrieval_mode: Callable[[], str],
        get_cached_embedding: Callable[[], Optional[list]] | None = None,
        get_entity_hint: Callable[[], Optional[str]] | None = None,
    ) -> Any:
        return create_memory_tool(
            memory=memory,
            get_retrieval_mode=get_retrieval_mode,
            get_cached_embedding=get_cached_embedding,
            get_entity_hint=get_entity_hint,
        )

    def create_invoke_skill_tool(self, router: Any, agent_factory_fn: Callable, current_depth: int) -> Any:
        return create_invoke_skill_tool(
            router=router,
            agent_factory_fn=agent_factory_fn,
            current_depth=current_depth,
        )

    def create_invoke_plan_tool(
        self,
        agent_factory_fn: Callable,
        tools_map_fn: Callable,
        current_depth: int,
        router: Any = None,
    ) -> Any:
        return create_invoke_plan_tool(
            agent_factory_fn=agent_factory_fn,
            tools_map_fn=tools_map_fn,
            current_depth=current_depth,
            router=router,
        )

    def create_create_plan_tool(self, agent: Any, llm: Any, router: Any) -> Any:
        return create_create_plan_tool(agent=agent, llm=llm, router=router)

    def load_skill_tools(self, skill_path: Path, agent_root: Any = None) -> list[Any]:
        return load_skill_tools(skill_path, agent_root=agent_root)

    def health(self) -> dict[str, Any]:
        return {"provider": self.name, "status": "ok"}

    def snapshot(self) -> dict[str, Any]:
        return self.health()
