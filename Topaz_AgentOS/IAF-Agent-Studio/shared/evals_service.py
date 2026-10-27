"""Thin Studio service for tenant-owned eval suites and golden sets."""

from __future__ import annotations

import uuid
from typing import Any

from rl_capture.adapters.agentpro.eval_candidates import produce_candidate
from rl_capture.adapters.agentpro.evals_paths import eval_storage_engine, evals_dir, evaluators_dir, golden_sets_dir
from rl_capture.evals.evaluators import (
    build_evaluator_input,
    list_evaluators,
    load_evaluator_manifest,
    run_python_evaluator,
)
from rl_capture.evals.runner import run_suite
from rl_capture.evals.recommender import recommend_models
from rl_capture.store.eval_store import EvalStore
from rl_capture.evals.registry import (
    append_golden_case,
    delete_suite,
    get_suite,
    list_golden_cases,
    list_suites,
    save_golden_cases,
    save_suite,
    validate_suite_definition,
)
from rl_capture.evals.rubric import extract_output_text
from rl_capture.store.sqlite_store import get_rl_store
from shared.config import AGENT_ID, DATA_ROOT_PATH, RL_DB_PATH, TENANT_ID


def list_eval_suites(tenant_id: str = TENANT_ID) -> list[dict[str, Any]]:
    return list_suites(evals_dir(tenant_id))


def get_eval_suite(suite_id: str, tenant_id: str = TENANT_ID) -> dict[str, Any]:
    return get_suite(evals_dir(tenant_id), suite_id)


def save_eval_suite(definition: dict[str, Any], tenant_id: str = TENANT_ID) -> dict[str, Any]:
    return save_suite(evals_dir(tenant_id), definition)


def validate_eval_suite(definition: dict[str, Any], tenant_id: str = TENANT_ID) -> dict[str, Any]:
    suite = validate_suite_definition(definition)
    evaluator = suite.get("evaluator") or {}
    warnings: list[str] = []
    if evaluator.get("type") == "python":
        evaluator_id = evaluator.get("id") or ""
        if not evaluator_id:
            raise ValueError("python evaluator requires evaluator.id")
        load_evaluator_manifest(evaluators_dir(tenant_id), evaluator_id)
    if (suite.get("judge") or {}).get("mode") in {"llm", "hybrid"}:
        warnings.append("LLM judge runs are non-deterministic and consume model budget")
    return {"valid": True, "suite": suite, "warnings": warnings}


def delete_eval_suite(suite_id: str, tenant_id: str = TENANT_ID) -> None:
    delete_suite(evals_dir(tenant_id), suite_id)


def list_eval_evaluators(tenant_id: str = TENANT_ID) -> list[dict[str, Any]]:
    return list_evaluators(evaluators_dir(tenant_id))


def get_eval_evaluator(evaluator_id: str, tenant_id: str = TENANT_ID) -> dict[str, Any]:
    return load_evaluator_manifest(evaluators_dir(tenant_id), evaluator_id)


def test_eval_evaluator(
    evaluator_id: str,
    *,
    tenant_id: str = TENANT_ID,
    payload: dict[str, Any] | None = None,
    config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    default_payload = {
        "suite": {"id": "test", "target": {"type": "test"}},
        "case": {"id": "test_case", "task": "test evaluator", "expected": "ok"},
        "candidate": {"output_text": "ok", "raw": {"output": "ok"}, "metadata": {}},
        "expected": "ok",
        "assertions": {},
        "metadata": {"source": "evaluator_test"},
    }
    return run_python_evaluator(
        registry_dir=evaluators_dir(tenant_id),
        evaluator_id=evaluator_id,
        payload=payload or default_payload,
        config=config or {},
    )


def get_golden_set(set_id: str, tenant_id: str = TENANT_ID) -> dict[str, Any]:
    cases = list_golden_cases(golden_sets_dir(tenant_id), set_id)
    return {"id": set_id, "cases": cases, "total": len(cases)}


def save_golden_set(set_id: str, cases: list[dict[str, Any]], tenant_id: str = TENANT_ID) -> dict[str, Any]:
    return save_golden_cases(golden_sets_dir(tenant_id), set_id, cases)


def run_eval_suite(
    suite_id: str,
    *,
    tenant_id: str = TENANT_ID,
    agent_id: str = AGENT_ID,
    user_id: str = "eval_runner",
    trigger: str = "manual",
    metadata: dict[str, Any] | None = None,
    principal: Any = None,
) -> dict[str, Any]:
    suite = get_eval_suite(suite_id, tenant_id)
    cases = list_golden_cases(golden_sets_dir(tenant_id), suite.get("golden_set") or "")
    eval_store = EvalStore(eval_storage_engine(tenant_id))
    rl_store = get_rl_store(
        data_root=DATA_ROOT_PATH,
        tenant_id=tenant_id,
        db_path=RL_DB_PATH.strip() or None,
    )
    evaluator_fn = _build_python_evaluator_fn(suite, tenant_id=tenant_id)
    judge_fn = _build_suite_judge_fn(
        suite,
        tenant_id=tenant_id,
        agent_id=agent_id,
        user_id=user_id,
        trigger=trigger,
        principal=principal,
    )
    return run_suite(
        suite=suite,
        cases=cases,
        eval_store=eval_store,
        candidate_producer=lambda case, active_suite: produce_candidate(
            case,
            active_suite,
            tenant_id=tenant_id,
            agent_id=agent_id,
            user_id=user_id,
        ),
        tenant_id=tenant_id,
        agent_id=agent_id,
        trigger=trigger,
        rl_store=rl_store,
        judge_fn=judge_fn,
        evaluator_fn=evaluator_fn,
        metadata=metadata or {},
    )


def list_runs(suite_id: str | None = None, *, tenant_id: str = TENANT_ID, limit: int = 25) -> list[dict[str, Any]]:
    return EvalStore(eval_storage_engine(tenant_id)).list_runs(suite_id=suite_id, tenant_id=tenant_id, limit=limit)


def get_run(run_id: str, *, tenant_id: str = TENANT_ID) -> dict[str, Any]:
    run = EvalStore(eval_storage_engine(tenant_id)).get_run(run_id)
    if run is None:
        raise FileNotFoundError(f"Eval run '{run_id}' not found")
    return run


def record_gate_decision(
    suite_id: str,
    *,
    run_id: str,
    decision: str,
    tenant_id: str = TENANT_ID,
    reviewer: str = "",
    reason: str = "",
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    decision = str(decision or "").strip().lower()
    if decision not in {"approve", "reject"}:
        raise ValueError("gate decision must be approve or reject")
    suite = get_eval_suite(suite_id, tenant_id)
    run = get_run(run_id, tenant_id=tenant_id)["run"]
    if run.get("suite_id") != suite_id:
        raise ValueError("gate run does not belong to suite")
    target = suite.get("target") or {}
    evaluator = suite.get("evaluator") or {}
    versions = {
        "suite_source": suite.get("source_file"),
        "evaluator": {
            "type": evaluator.get("type"),
            "id": evaluator.get("id"),
            "version": evaluator.get("version"),
        },
        "judge": suite.get("judge") or {},
    }
    return EvalStore(eval_storage_engine(tenant_id)).record_gate_decision(
        decision_id=f"gate_{uuid.uuid4().hex[:12]}",
        tenant_id=tenant_id,
        suite_id=suite_id,
        run_id=run_id,
        target_type=str(target.get("type") or ""),
        target_name=str(target.get("name") or target.get("role") or ""),
        decision=decision,
        reviewer=reviewer,
        reason=reason,
        score=float(run.get("score") or 0.0),
        thresholds=suite.get("thresholds") or suite.get("rubric") or {},
        evaluator_versions=versions,
        metadata=metadata or {},
    )


def list_gate_decisions(
    suite_id: str | None = None,
    *,
    tenant_id: str = TENANT_ID,
    limit: int = 25,
) -> list[dict[str, Any]]:
    return EvalStore(eval_storage_engine(tenant_id)).list_gate_decisions(
        suite_id=suite_id,
        tenant_id=tenant_id,
        limit=limit,
    )


def model_recommendations(*, tenant_id: str = TENANT_ID, role: str = "primary", limit: int = 50) -> dict[str, Any]:
    store = EvalStore(eval_storage_engine(tenant_id), init_schema=False)
    rows: list[dict[str, Any]] = []
    try:
        runs = store.list_runs(tenant_id=tenant_id, limit=limit)
        for run in runs:
            trace = store.get_run(run["run_id"]) or {}
            rows.extend(trace.get("cases") or [])
    except Exception:
        rows = []
    return recommend_models(rows, role=role)


def _build_python_evaluator_fn(suite: dict[str, Any], *, tenant_id: str):
    evaluator = suite.get("evaluator") or {}
    if evaluator.get("type") != "python":
        return None
    evaluator_id = evaluator.get("id") or ""
    if not evaluator_id:
        raise ValueError("python evaluator requires evaluator.id")

    def evaluate(request: dict[str, Any]) -> dict[str, Any]:
        payload = build_evaluator_input(
            suite=request["suite"],
            case=request["case"],
            candidate=request["candidate"],
            assertion_result=request.get("assertions") or {},
        )
        return run_python_evaluator(
            registry_dir=evaluators_dir(tenant_id),
            evaluator_id=evaluator_id,
            payload=payload,
            config=evaluator.get("config") or {},
        )

    return evaluate


def _build_suite_judge_fn(
    suite: dict[str, Any],
    *,
    tenant_id: str,
    agent_id: str,
    user_id: str,
    trigger: str,
    principal: Any = None,
):
    judge = suite.get("judge") or {}
    if str(judge.get("mode") or "rule").lower() == "rule":
        return None
    from rl_capture.core.auto_evaluator import build_judge_prompt, parse_judge_response
    from security.dependencies import make_agent_entitlement_checker, make_service_principal
    from shared.state import state

    if principal is None:
        principal = make_service_principal(tenant_id, "cron" if trigger == "cron" else "queue")
    user_role = principal.roles[0] if getattr(principal, "roles", None) else "service"
    agent = state.get_or_create(tenant_id, agent_id, user_id, user_role=user_role)
    agent.set_entitlement_context(principal, make_agent_entitlement_checker(principal))
    agent.auto_run = True
    judge_skill = str(judge.get("skill") or "trajectory_judge")

    def judge_case(detail: dict[str, Any]) -> dict[str, Any]:
        prompt = build_judge_prompt(detail)
        # skip_memory: a background judge must not be recorded into the agent's conversation.
        response = agent.run(prompt, skill_name=judge_skill, light_mode=True, skip_memory=True)
        text = response if isinstance(response, str) else (
            response.get("response") if isinstance(response, dict) else str(response)
        )
        return parse_judge_response(text)

    return judge_case


def promote_trajectory_to_golden(
    set_id: str,
    *,
    trajectory_id: str,
    tenant_id: str = TENANT_ID,
    case_id: str = "",
    expected: Any = None,
    assertions: list[dict[str, Any]] | None = None,
    tags: list[str] | None = None,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Promote a captured trajectory into a tenant-owned golden case."""
    store = get_rl_store(
        data_root=DATA_ROOT_PATH,
        tenant_id=tenant_id,
        db_path=RL_DB_PATH.strip() or None,
    )
    detail = store.trajectory_detail(trajectory_id)
    if not detail or not detail.get("trajectory"):
        raise FileNotFoundError(f"Trajectory '{trajectory_id}' not found")

    trajectory = detail["trajectory"]
    final_text = extract_output_text(detail)
    resolved_case_id = case_id or f"case_{uuid.uuid4().hex[:12]}"
    case = {
        "id": resolved_case_id,
        "task": trajectory.get("task") or "",
        "inputs": {
            "trajectory_id": trajectory_id,
            "session_id": trajectory.get("session_id"),
            "tenant": trajectory.get("tenant"),
        },
        "expected": final_text if expected is None else expected,
        "assertions": assertions or [],
        "tags": tags or [],
        "metadata": {
            "source": "trajectory",
            "trajectory_id": trajectory_id,
            "terminal_status": trajectory.get("terminal_status"),
            "adapter": trajectory.get("adapter"),
            **(metadata or {}),
        },
    }
    return append_golden_case(golden_sets_dir(tenant_id), set_id, case)
