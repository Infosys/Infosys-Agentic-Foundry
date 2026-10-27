"""Example ToolProvider that decorates the built-in provider."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, Optional

from iaf_agent_skills.providers_default import BuiltinToolProvider


class SampleToolProvider:
    """Starter for partner tool catalog integrations.

    This example delegates to built-ins. Replace selected methods to source
    tools from an external catalog while keeping SkillAgent orchestration intact.
    """

    def __init__(self):
        self._default = BuiltinToolProvider()

    def create_shell_tool(self, kernel: Any, auto_run: bool = True) -> Any:
        return self._default.create_shell_tool(kernel, auto_run=auto_run)

    def create_sql_tool(self, kernel: Any, sql_write_allowed: bool = False) -> Any:
        return self._default.create_sql_tool(kernel, sql_write_allowed=sql_write_allowed)

    def create_write_file_tool(self, kernel: Any) -> Any:
        return self._default.create_write_file_tool(kernel)

    def create_memory_tool(
        self,
        memory: Any,
        get_retrieval_mode: Callable[[], str],
        get_cached_embedding: Callable[[], Optional[list]] | None = None,
        get_entity_hint: Callable[[], Optional[str]] | None = None,
    ) -> Any:
        return self._default.create_memory_tool(
            memory,
            get_retrieval_mode,
            get_cached_embedding=get_cached_embedding,
            get_entity_hint=get_entity_hint,
        )

    def create_invoke_skill_tool(self, router: Any, agent_factory_fn: Callable, current_depth: int) -> Any:
        return self._default.create_invoke_skill_tool(router, agent_factory_fn, current_depth)

    def create_invoke_plan_tool(
        self,
        agent_factory_fn: Callable,
        tools_map_fn: Callable,
        current_depth: int,
        router: Any = None,
    ) -> Any:
        return self._default.create_invoke_plan_tool(agent_factory_fn, tools_map_fn, current_depth, router)

    def create_create_plan_tool(self, agent: Any, llm: Any, router: Any) -> Any:
        return self._default.create_create_plan_tool(agent, llm, router)

    def load_skill_tools(self, skill_path: Path) -> list[Any]:
        return self._default.load_skill_tools(skill_path)

    def health(self) -> dict[str, Any]:
        return {"provider": "sample_tool_provider", "status": "ok"}

    def snapshot(self) -> dict[str, Any]:
        return self.health()
