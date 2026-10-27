"""AgentPro candidate producers for Private Learning Loop eval runs."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from rl_capture.core.schema import CaptureMeta, Message, PolicyRef, Role, ShadowRun, TargetRef, TargetType


def produce_candidate(
    case: dict[str, Any],
    suite: dict[str, Any],
    *,
    tenant_id: str,
    agent_id: str,
    user_id: str = "eval_runner",
) -> dict[str, Any]:
    target = suite.get("target") or {}
    target_type = str(target.get("type") or "").strip().lower()
    if target_type == "skill":
        return _run_skill(case, target=target, tenant_id=tenant_id, agent_id=agent_id, user_id=user_id)
    if target_type == "automation":
        return _run_automation(case, target=target, tenant_id=tenant_id, agent_id=agent_id, user_id=user_id)
    if target_type in {"model_role", "model"}:
        return _run_model_role(case, target=target, tenant_id=tenant_id, agent_id=agent_id)
    raise ValueError("eval target.type must be one of: skill, automation, model_role")


def _case_prompt(case: dict[str, Any]) -> str:
    task = str(case.get("task") or "")
    inputs = case.get("inputs") if isinstance(case.get("inputs"), dict) else {}
    if not inputs:
        return task
    return f"{task}\n\nInputs:\n{inputs}"


def _run_skill(
    case: dict[str, Any],
    *,
    target: dict[str, Any],
    tenant_id: str,
    agent_id: str,
    user_id: str,
) -> dict[str, Any]:
    skill_name = str(target.get("name") or target.get("skill") or "").strip()
    if not skill_name:
        raise ValueError("skill eval target requires target.name")
    from agent_os import create_kernel_runtime
    from iaf_agent_skills import SkillAgent
    from shared.config import DATA_ROOT_PATH, SKILLS_PATH_PATH

    # Use the factory so a sandboxed kernel backend (AGENTOS_KERNEL_BACKEND) is honoured.
    kernel = create_kernel_runtime(
        data_root=str(DATA_ROOT_PATH),
        tenant_id=tenant_id,
        agent_id=agent_id,
        user_id=user_id,
        require_confirmation=False,
    )
    agent = SkillAgent(
        kernel=kernel,
        skills_path=str(SKILLS_PATH_PATH),
        user_id=user_id,
        enterprise_root=str(DATA_ROOT_PATH),
    )
    agent.auto_run = True
    result = agent.run(_case_prompt(case), skill_name=skill_name, skip_memory=True)
    output = result[0] if isinstance(result, tuple) else result
    return {
        "output": str(output or ""),
        "metadata": {"target_type": "skill", "target_name": skill_name},
    }


def _run_automation(
    case: dict[str, Any],
    *,
    target: dict[str, Any],
    tenant_id: str,
    agent_id: str,
    user_id: str,
) -> dict[str, Any]:
    automation_id = str(target.get("name") or target.get("automation") or "").strip()
    if not automation_id:
        raise ValueError("automation eval target requires target.name")
    from shared.automations_service import run_automation

    result = run_automation(
        automation_id,
        tenant_id=tenant_id,
        agent_id=agent_id,
        user_id=user_id,
        trigger="eval",
        input_text=_case_prompt(case),
        context={"case": case},
    )
    return {
        "output": result.get("summary") or "",
        "metadata": {
            "target_type": "automation",
            "target_name": automation_id,
            "automation_run_id": result.get("run_id"),
        },
    }


def _run_model_role(
    case: dict[str, Any],
    *,
    target: dict[str, Any],
    tenant_id: str,
    agent_id: str,
) -> dict[str, Any]:
    role = str(target.get("role") or target.get("name") or "primary").strip()
    from agentos_model.model_registry import ModelRegistry

    llm = ModelRegistry.get(role)
    if llm is None:
        raise ValueError(f"model role '{role}' is not configured")
    response = llm.invoke(_case_prompt(case)) if hasattr(llm, "invoke") else llm(_case_prompt(case))
    output = str(getattr(response, "content", response) or "")
    metadata = {"target_type": "model_role", "target_name": role}
    shadow_run = _shadow_run_for_case(case, role=role, output=output, tenant_id=tenant_id, agent_id=agent_id)
    return {
        "output": output,
        "metadata": metadata,
        "shadow_run": shadow_run,
    }


def _shadow_run_for_case(
    case: dict[str, Any],
    *,
    role: str,
    output: str,
    tenant_id: str,
    agent_id: str,
) -> ShadowRun | None:
    metadata = case.get("metadata") or {}
    inputs = case.get("inputs") if isinstance(case.get("inputs"), dict) else {}
    baseline_trajectory_id = str(metadata.get("trajectory_id") or inputs.get("trajectory_id") or "")
    if not baseline_trajectory_id:
        return None
    now = datetime.now(timezone.utc).isoformat()
    target = TargetRef(
        trajectory_id=baseline_trajectory_id,
        target_type=TargetType.TRAJECTORY,
        target_id=baseline_trajectory_id,
    )
    return ShadowRun(
        id=f"shadow_{baseline_trajectory_id}_{role}_{now}",
        baseline_trajectory_id=baseline_trajectory_id,
        baseline_response_ref=target,
        candidate_policy=PolicyRef(provider="model_role", model=role),
        candidate_messages=[Message(role=Role.ASSISTANT, content=output)],
        created_at=now,
        capture=CaptureMeta(
            adapter_version="agentpro:eval_candidate",
            tenant_id=tenant_id,
            agent_id=agent_id,
            source_event_id=str(case.get("id") or ""),
            source_trace_id=baseline_trajectory_id,
            capture_time=now,
        ),
        metadata={"case_id": case.get("id"), "target_role": role},
    )
