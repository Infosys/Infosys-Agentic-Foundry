"""Provider contracts for replaceable AgentOS runtime components."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, Protocol, runtime_checkable

from .skill import Skill


@runtime_checkable
class SkillProvider(Protocol):
    """Minimal contract for loading skill definitions and prompt text."""

    skills_path: Path

    def set_personal_path(self, personal_path: Any) -> None:
        """Set an optional per-user skill override location."""

    def load(self, skill_name: str) -> Skill:
        """Load a skill by name."""

    def get_file_content(self, skill: Skill, file_key: str) -> str | None:
        """Return content for one related skill file, if available."""

    def get_prompt(self, skill: Skill, include_files: bool = True) -> str:
        """Build the executable system prompt for a skill."""

    def list_skill_files(self, skill: Skill) -> list[dict[str, str]]:
        """List files attached to a skill."""

    def health(self) -> dict[str, Any]:
        """Return bounded diagnostics for capability snapshots."""

    def snapshot(self) -> dict[str, Any]:
        """Return a redacted runtime snapshot."""


@runtime_checkable
class RouterProvider(Protocol):
    """Contract for routing user input to an executable skill."""

    skills_path: Path
    index_path: Path
    index: dict[str, Any]
    default_skill: str

    def reload(self) -> None:
        """Reload routing metadata."""

    def set_personal_path(self, personal_path: Any) -> None:
        """Set an optional per-user skill override location."""

    def set_skill_filter(self, allowed: list | None = None, denied: list | None = None) -> None:
        """Restrict skills by allowlist or denylist."""

    def _get_filtered_skills(self) -> dict[str, Any]:
        """Return the currently visible skill map."""

    def match(
        self,
        query: str,
        current_skill: str | None = None,
        last_response: str | None = None,
        return_details: bool = False,
        pending_action: dict | None = None,
        entity_hint: str | None = None,
        entity_confidence: float = 0.0,
        process_hint: str | None = None,
        process_matches: list | None = None,
        signals_agree: bool | None = None,
        taxonomy_hints: list | None = None,
    ) -> str | dict:
        """Route a query to a skill name or rich routing details."""

    def list_skills(self) -> list[dict[str, Any]]:
        """List available skills."""

    def get_skill_info(self, skill_name: str) -> dict[str, Any] | None:
        """Return metadata for a single skill."""

    def skill_exists(self, skill_name: str) -> bool:
        """Return whether a skill exists."""

    def health(self) -> dict[str, Any]:
        """Return bounded diagnostics for capability snapshots."""

    def snapshot(self) -> dict[str, Any]:
        """Return a redacted runtime snapshot."""


@runtime_checkable
class ToolProvider(Protocol):
    """Contract for constructing tools used by SkillAgent."""

    def create_shell_tool(self, kernel: Any, auto_run: bool = True) -> Any:
        """Create the shell execution tool."""

    def create_sql_tool(self, kernel: Any, sql_write_allowed: bool = False, indexer: Any = None, connections: Any = None) -> Any:
        """Create the SQL query tool.

        ``indexer`` (optional) enables Postgres-backed db resources. ``connections``
        (optional) is the skill's declared data connections (multi-engine routing).
        Both are keyword-only with ``None`` defaults so existing providers that do
        not implement them remain conformant.
        """

    def create_write_file_tool(self, kernel: Any) -> Any:
        """Create the write-file tool."""

    def create_memory_tool(
        self,
        memory: Any,
        get_retrieval_mode: Callable[[], str],
        get_cached_embedding: Callable[[], list | None] | None = None,
        get_entity_hint: Callable[[], str | None] | None = None,
    ) -> Any:
        """Create the query-memory tool."""

    def create_invoke_skill_tool(self, router: Any, agent_factory_fn: Callable, current_depth: int) -> Any:
        """Create the skill delegation tool."""

    def create_invoke_plan_tool(
        self,
        agent_factory_fn: Callable,
        tools_map_fn: Callable,
        current_depth: int,
        router: Any = None,
    ) -> Any:
        """Create the plan invocation tool."""

    def create_create_plan_tool(self, agent: Any, llm: Any, router: Any) -> Any:
        """Create the plan authoring tool."""

    def load_skill_tools(self, skill_path: Path) -> list[Any]:
        """Load bundled Python tools from a skill folder."""

    def health(self) -> dict[str, Any]:
        """Return bounded diagnostics for capability snapshots."""

    def snapshot(self) -> dict[str, Any]:
        """Return a redacted runtime snapshot."""


@runtime_checkable
class HookProvider(Protocol):
    """Contract for creating the hook runner used by SkillAgent."""

    def build_runner(
        self,
        *,
        agent: Any,
        hooks_config: dict,
        agent_root: str,
        trace_emitter: Any = None,
        tenant_id: str = "",
        agent_id: str = "",
    ) -> Any:
        """Build and attach a hook runner for an agent instance."""

    def health(self) -> dict[str, Any]:
        """Return bounded diagnostics for capability snapshots."""

    def snapshot(self) -> dict[str, Any]:
        """Return a redacted runtime snapshot."""


@runtime_checkable
class TraceProvider(Protocol):
    """Contract for trace emitters consumed by SkillAgent."""

    def get_emitter(self) -> Any:
        """Return the active trace emitter object, or None."""

    def health(self) -> dict[str, Any]:
        """Return bounded diagnostics for capability snapshots."""

    def snapshot(self) -> dict[str, Any]:
        """Return a redacted runtime snapshot."""
