"""Provider factory for AgentPro runtime seams.

Defaults preserve today's behavior. Partner providers can be supplied later by
using an import path value such as ``my_pkg.providers:MySkillProvider``.
"""

from __future__ import annotations

import importlib
import os
from dataclasses import dataclass
from typing import Any

from iaf_agent_skills.providers.hook_provider import HookProvider
from iaf_agent_skills.providers.router_provider import RouterProvider
from iaf_agent_skills.providers.skill_provider import SkillProvider
from iaf_agent_skills.providers.tool_provider import ToolProvider
from iaf_agent_skills.providers.trace_provider import TraceProvider
from iaf_agent_skills.providers_default import (
    BuiltinToolProvider,
    DefaultHookProvider,
    DefaultRouterProvider,
    DefaultTraceProvider,
    FileSystemSkillProvider,
)


@dataclass
class RuntimeProviders:
    """Container for the five runtime provider slots."""

    skill: SkillProvider
    router: RouterProvider
    tool: ToolProvider
    hook: HookProvider
    trace: TraceProvider


def build_skill_provider(skills_path: str, provider_name: str | None = None) -> SkillProvider:
    selected = _setting("SKILL_PROVIDER", provider_name, "default")
    if selected in {"default", "filesystem", "skill_loader"}:
        return FileSystemSkillProvider(skills_path)
    return _instantiate_custom(selected, skills_path=skills_path)


def build_router_provider(skills_path: str, provider_name: str | None = None) -> RouterProvider:
    selected = _setting("ROUTER_PROVIDER", provider_name, "default")
    if selected in {"default", "skill_router"}:
        return DefaultRouterProvider(skills_path)
    return _instantiate_custom(selected, skills_path=skills_path)


def build_tool_provider(provider_name: str | None = None) -> ToolProvider:
    selected = _setting("TOOL_PROVIDER", provider_name, "default")
    if selected in {"default", "builtin", "tool_factory"}:
        return BuiltinToolProvider()
    return _instantiate_custom(selected)


def build_hook_provider(provider_name: str | None = None) -> HookProvider:
    selected = _setting("HOOK_PROVIDER", provider_name, "default")
    if selected in {"default", "hook_runner"}:
        return DefaultHookProvider()
    return _instantiate_custom(selected)


def build_trace_provider(provider_name: str | None = None, emitter: Any = None) -> TraceProvider:
    selected = _setting("TRACE_PROVIDER", provider_name, "default")
    if selected in {"default", "trace_emitter"}:
        return DefaultTraceProvider(emitter=emitter)
    return _instantiate_custom(selected, emitter=emitter)


def build_runtime_providers(
    *,
    skills_path: str,
    trace_emitter: Any = None,
) -> RuntimeProviders:
    """Build all runtime provider slots from configuration."""

    return RuntimeProviders(
        skill=build_skill_provider(skills_path),
        router=build_router_provider(skills_path),
        tool=build_tool_provider(),
        hook=build_hook_provider(),
        trace=build_trace_provider(emitter=trace_emitter),
    )


def _setting(name: str, explicit: str | None, default: str) -> str:
    if explicit:
        return _normalize_setting(explicit)
    env_value = os.getenv(name)
    if env_value:
        return _normalize_setting(env_value)
    # Host-injected provider config (registered at startup). No host import.
    try:
        from iaf_agent_skills.runtime_bridge import get_provider_setting

        value = get_provider_setting(name)
        if value:
            return _normalize_setting(str(value))
    except Exception:
        pass
    return _normalize_setting(default)


def _normalize_setting(value: str) -> str:
    stripped = value.strip()
    return stripped if ":" in stripped else stripped.lower()


def _instantiate_custom(path: str, **kwargs: Any) -> Any:
    if ":" not in path:
        raise ValueError(f"Unsupported provider value {path!r}; use 'default' or 'module:Class'")
    module_name, attr_name = path.split(":", 1)
    module = importlib.import_module(module_name)
    provider_cls = getattr(module, attr_name)
    try:
        return provider_cls(**kwargs)
    except TypeError:
        return provider_cls()
