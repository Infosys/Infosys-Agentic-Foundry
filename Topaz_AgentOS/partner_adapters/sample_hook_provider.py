"""Example HookProvider that decorates the built-in HookRunner wiring."""

from __future__ import annotations

from typing import Any

from iaf_agent_skills.providers_default import DefaultHookProvider


class SampleHookProvider:
    """Starter for partner policy engine integrations."""

    def __init__(self):
        self._default = DefaultHookProvider()

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
        runner = self._default.build_runner(
            agent=agent,
            hooks_config=hooks_config,
            agent_root=agent_root,
            trace_emitter=trace_emitter,
            tenant_id=tenant_id,
            agent_id=agent_id,
        )
        # Replace or decorate runner methods here to call an external policy engine.
        return runner

    def health(self) -> dict[str, Any]:
        return {"provider": "sample_hook_provider", "status": "ok"}

    def snapshot(self) -> dict[str, Any]:
        return self.health()
