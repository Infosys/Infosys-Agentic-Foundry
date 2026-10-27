"""Default HookProvider backed by the existing HookRunner stack."""

from __future__ import annotations

import logging
from typing import Any

from iaf_agent_skills.hook_runner import HookRunner
from iaf_agent_skills.model_call_pipeline import ModelCallPipeline, model_call_pipeline_enabled
from iaf_agent_skills.model_call_policy_hooks import register_policy_control_model_call_hooks

logger = logging.getLogger(__name__)


class DefaultHookProvider:
    """Build the same HookRunner wiring SkillAgent used before providers."""

    name = "default_hook"

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
        from iaf_agent_skills.platform_hooks import resolve_effective_hooks

        effective_hooks = resolve_effective_hooks(
            hooks_config or {},
            agent_id or "",
            tenant_id or "",
        )
        runner = HookRunner(
            hooks_config=effective_hooks,
            agent_root=agent_root,
            hook_audit_sink=trace_emitter,
            platform_hooks_dir="",
        )
        try:
            kernel = getattr(agent, "kernel", None)
            if kernel is not None and hasattr(kernel, "attach_hook_runner"):
                kernel.attach_hook_runner(
                    runner,
                    session_ctx_provider=lambda: agent._build_session_ctx(),
                )
        except Exception as exc:  # pragma: no cover - defensive
            logger.debug("Kernel hook-runner attach failed (non-fatal): %s", exc)

        try:
            from iaf_agent_skills import background_hooks as bg

            bg.register_background_runner(runner)
        except Exception as exc:  # pragma: no cover - defensive
            logger.debug("background_hooks register failed (non-fatal): %s", exc)

        pipeline = ModelCallPipeline(runner)
        setattr(agent, "_model_call_pipeline", pipeline)
        if model_call_pipeline_enabled():
            register_policy_control_model_call_hooks(
                runner,
                agent_root=agent_root,
                tenant_id=tenant_id,
                agent_id=agent_id,
            )
        return runner

    def health(self) -> dict[str, Any]:
        return {"provider": self.name, "status": "ok"}

    def snapshot(self) -> dict[str, Any]:
        return self.health()
