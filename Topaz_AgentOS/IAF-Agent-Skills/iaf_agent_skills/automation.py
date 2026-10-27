"""Deterministic, no-LLM automation runner.

Automations reuse the existing WorkflowEngine for sequencing, templating, and
conditions, but intentionally do not provide an agent_factory. That keeps
automation definitions separate from skills and prevents LLM-powered skill
steps from running inside this path.
"""

from __future__ import annotations

import shlex
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Iterable, List, Optional

from .execution import Step, StepResult, WorkflowEngine


StatusCallback = Optional[Callable[[Any], None]]


@dataclass
class AutomationRunResult:
    """Structured result returned after an automation run."""

    automation_id: str
    success: bool
    summary: str
    steps: Dict[str, StepResult] = field(default_factory=dict)


class AutomationEngine:
    """Run deterministic shell/python pipelines through SafeKernel.

    The engine supports only deterministic actions:
    - ``shell``: execute a predefined shell command via SafeKernel
    - ``python``: execute a script under ``/shared/scripts`` via SafeKernel's
      guarded ``python3`` command
    - ``condition``: branch based on previous step output
    """

    ALLOWED_ACTIONS = {"shell", "python", "condition"}

    def __init__(self, kernel: Any):
        self.kernel = kernel

    def run(
        self,
        *,
        automation_id: str,
        steps: Iterable[dict[str, Any]],
        initial_context: str | None = None,
        status_callback: StatusCallback = None,
    ) -> AutomationRunResult:
        """Execute automation steps and return a deterministic run result."""

        workflow_steps = [self._normalize_step(step) for step in steps]
        self._validate_steps(workflow_steps)

        engine = WorkflowEngine(self._tools_map(), agent_factory=None)
        results = engine.run(
            [Step.from_dict(step) for step in workflow_steps],
            status_callback=status_callback,
            initial_context=initial_context,
        )
        step_results = {name: result for name, result in results.items() if name != "_input"}
        success = all(result.success for result in step_results.values())
        return AutomationRunResult(
            automation_id=automation_id,
            success=success,
            summary=self._format_summary(step_results),
            steps=step_results,
        )

    def _tools_map(self) -> dict[str, Callable[..., str]]:
        def shell(command: str) -> str:
            if not command:
                return "Error [AUTOMATION]: shell step missing params.command"
            return self.kernel.run_shell_command(str(command), confirmed=True)

        def python(script: str, args: str = "") -> str:
            if not script:
                return "Error [AUTOMATION]: python step missing params.script"
            script_path = str(script).strip()
            if not script_path.startswith("/"):
                script_path = f"/shared/scripts/{script_path}"
            command = f"python3 {shlex.quote(script_path)}"
            if args:
                command = f"{command} {str(args).strip()}"
            return self.kernel.run_shell_command(command, confirmed=True)

        return {"shell": shell, "python": python}

    def _validate_steps(self, steps: List[dict[str, Any]]) -> None:
        names: set[str] = set()
        for idx, step in enumerate(steps, start=1):
            name = str(step.get("name") or f"step_{idx}")
            action = str(step.get("action") or "").strip()
            if action == "skill":
                raise ValueError(
                    f"Automation step '{name}' uses action='skill'. "
                    "Automations are no-LLM and cannot invoke skills."
                )
            if action not in self.ALLOWED_ACTIONS:
                raise ValueError(
                    f"Automation step '{name}' uses unsupported action '{action}'. "
                    f"Allowed actions: {sorted(self.ALLOWED_ACTIONS)}"
                )
            if name in names:
                raise ValueError(f"Duplicate automation step name: {name}")
            names.add(name)

    def _normalize_step(self, raw: dict[str, Any]) -> dict[str, Any]:
        step = dict(raw or {})
        action = str(step.get("action") or "shell").strip()
        step["action"] = action

        params = dict(step.get("params") or {})
        if action == "shell" and "command" in step and "command" not in params:
            params["command"] = step["command"]
        if action == "python":
            if "script" in step and "script" not in params:
                params["script"] = step["script"]
            if "args" in step and "args" not in params:
                params["args"] = step["args"]
        step["params"] = params

        if "then_step" in step and "then" not in step:
            step["then"] = step["then_step"]
        if "else_step" in step and "else" not in step:
            step["else"] = step["else_step"]
        return step

    def _format_summary(self, results: dict[str, StepResult]) -> str:
        if not results:
            return "No automation steps executed."
        successful = sum(1 for result in results.values() if result.success)
        failed = len(results) - successful
        status = "completed" if failed == 0 else "completed with failures"
        lines = [f"Automation {status}: {successful}/{len(results)} step(s) succeeded."]
        for name, result in results.items():
            outcome = "ok" if result.success else "failed"
            detail = result.error or (result.output or "").strip()
            if detail:
                detail = detail[:240] + "..." if len(detail) > 240 else detail
                lines.append(f"- {name}: {outcome} ({result.duration_ms}ms) - {detail}")
            else:
                lines.append(f"- {name}: {outcome} ({result.duration_ms}ms)")
        return "\n".join(lines)
