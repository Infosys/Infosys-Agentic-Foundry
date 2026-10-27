"""Central Policy & Control Registry APIs."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import yaml
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from auth.middleware import require_admin
from security.dependencies import enforce_entitlement, principal_from_request
from security.dependencies import make_agent_entitlement_checker
from shared.file_utils import atomic_write_yaml, locked_rmw_yaml
from shared.hooks_validation import validate_hooks_doc
from shared.policy_control import (
    agent_config_path,
    compile_hook,
    compile_hooks_for_policy,
    load_registry,
    merge_generated_hook,
    normalize_policy,
    parse_policy_authoring_response,
    policy_event_catalog,
    registry_path,
    unmanaged_hook_controls,
    validate_compiled_hook,
    validate_registry_doc,
)
from shared.state import queue_manager, state
from iaf_agent_skills.queue_manager import QueueNames


router = APIRouter(tags=["policy-control"])


class PolicyRegistrySaveRequest(BaseModel):
    tenant_id: str = "company"
    agent_id: str | None = None
    policies: list[dict[str, Any]] = Field(default_factory=list)


class PolicyValidateRequest(BaseModel):
    tenant_id: str = "company"
    policy: dict[str, Any] | None = None
    policies: list[dict[str, Any]] | None = None


class PolicyPublishRequest(BaseModel):
    tenant_id: str = "company"
    agent_id: str | None = None


class PolicySimulateRequest(BaseModel):
    tenant_id: str = "company"
    policy: dict[str, Any]
    context: dict[str, Any] = Field(default_factory=dict)


class PolicyDraftRequest(BaseModel):
    tenant_id: str = "company"
    agent_id: str = "enterprise_agent"
    prompt: str
    user_id: str | None = None


class PolicyYamlRequest(BaseModel):
    tenant_id: str = "company"
    agent_id: str = "enterprise_agent"
    yaml_text: str


def _require_policy_admin(request: Request, tenant_id: str) -> None:
    enforce_entitlement(principal_from_request(request, tenant_id), "manage", "security", "policies")


def _managed_policy_control(policy: dict[str, Any]) -> dict[str, Any]:
    control = {**policy}
    control.setdefault("control_id", f"policy:{policy['policy_id']}")
    control["source_type"] = "policy_registry"
    control["managed"] = True
    control["read_only"] = False
    return control


def _registry_response(tenant_id: str, agent_id: str = "enterprise_agent") -> dict[str, Any]:
    doc = load_registry(tenant_id)
    policies = [normalize_policy(policy) for policy in doc.get("policies", []) if isinstance(policy, dict)]
    normalized_doc = {"version": doc.get("version", "1.0"), "policies": policies}
    validation = validate_registry_doc(normalized_doc)
    compiled = {p["policy_id"]: compile_hooks_for_policy(p) for p in policies}
    unmanaged = unmanaged_hook_controls(tenant_id, agent_id, policies)
    controls = [_managed_policy_control(policy) for policy in policies] + unmanaged
    return {
        "tenant_id": tenant_id,
        "agent_id": agent_id,
        "path": str(registry_path(tenant_id)),
        "version": normalized_doc["version"],
        "policies": policies,
        "controls": controls,
        "unmanaged_controls": unmanaged,
        "policy_count": len(policies),
        "control_count": len(controls),
        "unmanaged_count": len(unmanaged),
        "active_count": sum(1 for p in policies if p.get("status") == "active"),
        "active_control_count": sum(1 for c in controls if c.get("status") == "active"),
        "validation": validation,
        "compiled_hooks": compiled,
    }


def _find_policy(tenant_id: str, policy_id: str) -> dict[str, Any]:
    for policy in load_registry(tenant_id).get("policies", []):
        if isinstance(policy, dict) and str(policy.get("policy_id")) == policy_id:
            return normalize_policy(policy)
    raise HTTPException(404, f"Policy '{policy_id}' not found")


def _evict_agent(agent_id: str) -> int:
    # Evict template, kernels and session clones so policy changes reach open sessions; keep their history.
    return state.evict_agent(agent_id, preserve_sessions=True)


async def _run_policy_authoring_skill(
    request: Request,
    *,
    tenant_id: str,
    agent_id: str,
    prompt: str,
    user_id: str | None = None,
) -> str:
    """Run the dedicated LLM-backed Policy Authoring skill."""
    principal = principal_from_request(request, tenant_id)
    user_role = principal.roles[0] if principal.roles else "user"
    effective_user = user_id or getattr(request.state, "user_id", None) or "policy_author"
    enforce_entitlement(principal, "use", "agent", agent_id)
    enforce_entitlement(principal, "test", "skill", "policy_authoring")
    agent = state.get_or_create(tenant_id, agent_id, effective_user, user_role=user_role)
    agent.set_entitlement_context(principal, make_agent_entitlement_checker(principal))
    kernel = state.get_kernel(tenant_id, agent_id, effective_user, user_role=user_role)
    kernel.require_confirmation = False
    agent.auto_run = True
    lane_name = QueueNames.session(tenant_id, effective_user)
    response = await queue_manager.enqueue(
        lane_name,
        lambda: agent.run(prompt, skill_name="policy_authoring", light_mode=True, skip_memory=True),
        max_concurrent=1,
    )
    if isinstance(response, dict):
        return str(response.get("response") or response.get("content") or response)
    return str(response)


@router.get("/api/policy-control/policies")
async def list_policy_control_policies(
    request: Request,
    tenant_id: str = "company",
    agent_id: str = "enterprise_agent",
    admin: dict = Depends(require_admin),
):
    """Return managed registry policies plus unmanaged tenant hooks for one agent."""
    _require_policy_admin(request, tenant_id)
    enforce_entitlement(principal_from_request(request, tenant_id), "manage", "agent", agent_id)
    return _registry_response(tenant_id, agent_id)


@router.get("/api/policy-control/events")
async def list_policy_control_events(
    request: Request,
    tenant_id: str = "company",
    admin: dict = Depends(require_admin),
):
    """Return the hook event catalog with Policy Control guidance metadata."""
    _require_policy_admin(request, tenant_id)
    return {"tenant_id": tenant_id, "events": policy_event_catalog()}


@router.post("/api/policy-control/policies/validate")
async def validate_policy_control_policy(body: PolicyValidateRequest, admin: dict = Depends(require_admin)):
    """Validate one policy or a full policy list without writing."""
    policies = body.policies if body.policies is not None else ([body.policy] if body.policy else [])
    normalized = [normalize_policy(policy or {}) for policy in policies]
    registry_validation = validate_registry_doc({"version": "1.0", "policies": normalized})
    hook_validation = {
        policy["policy_id"]: validate_compiled_hook(policy)
        for policy in normalized
    }
    return {
        "valid": registry_validation["valid"] and all(v["valid"] for v in hook_validation.values()),
        "registry": registry_validation,
        "hooks": hook_validation,
        "policies": normalized,
    }


@router.post("/api/policy-control/policies/draft")
async def draft_policy_control_policy(
    request: Request,
    body: PolicyDraftRequest,
    admin: dict = Depends(require_admin),
):
    """Draft a structured policy by running the LLM-backed Policy Authoring skill."""
    _require_policy_admin(request, body.tenant_id)
    try:
        skill_response = await _run_policy_authoring_skill(
            request,
            tenant_id=body.tenant_id,
            agent_id=body.agent_id,
            prompt=body.prompt,
            user_id=body.user_id,
        )
        draft = parse_policy_authoring_response(skill_response, tenant_id=body.tenant_id, agent_id=body.agent_id)
    except ValueError as exc:
        raise HTTPException(400, detail=str(exc)) from exc
    validation = validate_registry_doc({"version": "1.0", "policies": [draft["policy"]]})
    hook_validation = validate_compiled_hook(draft["policy"])
    return {
        **draft,
        "validation": {
            "valid": validation["valid"] and hook_validation["valid"],
            "registry": validation,
            "hook": hook_validation,
        },
        "hook_preview": compile_hooks_for_policy({**draft["policy"], "status": "active"}),
    }


@router.post("/api/policy-control/policies/parse-yaml")
async def parse_policy_control_yaml(
    request: Request,
    body: PolicyYamlRequest,
    admin: dict = Depends(require_admin),
):
    """Parse YAML from the editor into normalized Policy Control form data."""
    _require_policy_admin(request, body.tenant_id)
    try:
        draft = parse_policy_authoring_response(body.yaml_text, tenant_id=body.tenant_id, agent_id=body.agent_id)
    except ValueError as exc:
        raise HTTPException(400, detail=str(exc)) from exc
    validation = validate_registry_doc({"version": "1.0", "policies": [draft["policy"]]})
    hook_validation = validate_compiled_hook(draft["policy"])
    return {
        **draft,
        "validation": {
            "valid": validation["valid"] and hook_validation["valid"],
            "registry": validation,
            "hook": hook_validation,
        },
        "hook_preview": compile_hooks_for_policy({**draft["policy"], "status": "active"}),
    }


@router.put("/api/policy-control/policies")
async def save_policy_control_policies(
    request: Request, body: PolicyRegistrySaveRequest, admin: dict = Depends(require_admin)
):
    """Validate and save the central policy-control registry for a tenant."""
    _require_policy_admin(request, body.tenant_id)
    policies = [normalize_policy(policy) for policy in body.policies]
    doc = {"version": "1.0", "policies": policies}
    validation = validate_registry_doc(doc)
    if not validation["valid"]:
        raise HTTPException(400, detail={"errors": validation["errors"], "warnings": validation["warnings"]})
    atomic_write_yaml(registry_path(body.tenant_id), doc)
    return _registry_response(body.tenant_id, body.agent_id or "enterprise_agent")


@router.get("/api/policy-control/policies/{policy_id}/hook-preview")
async def preview_policy_control_hook(
    request: Request, policy_id: str, tenant_id: str = "company", admin: dict = Depends(require_admin)
):
    """Return the generated hook binding for a saved policy."""
    _require_policy_admin(request, tenant_id)
    policy = _find_policy(tenant_id, policy_id)
    hooks = compile_hooks_for_policy(policy)
    return {
        "tenant_id": tenant_id,
        "policy": policy,
        "hooks": hooks,
        "hook_yaml": yaml.safe_dump({"hooks": hooks}, sort_keys=False),
        "validation": validate_hooks_doc(hooks),
    }


@router.post("/api/policy-control/policies/{policy_id}/publish")
async def publish_policy_control_policy(
    request: Request,
    policy_id: str,
    body: PolicyPublishRequest,
    admin: dict = Depends(require_admin),
):
    """Compile a policy into the target agent's hooks while preserving manual hooks."""
    _require_policy_admin(request, body.tenant_id)
    policy = _find_policy(body.tenant_id, policy_id)
    agent_id = body.agent_id or policy.get("scope", {}).get("agent_id") or "enterprise_agent"
    enforce_entitlement(principal_from_request(request, body.tenant_id), "manage", "agent", agent_id)
    config_path = agent_config_path(body.tenant_id, agent_id)
    if not config_path.exists():
        raise HTTPException(404, f"Agent '{agent_id}' not found")

    hook_validation = validate_compiled_hook(policy)
    if not hook_validation["valid"]:
        raise HTTPException(400, detail={"errors": hook_validation["errors"], "warnings": hook_validation["warnings"]})

    def _merge(cfg: dict) -> dict:
        cfg = cfg or {}
        merged = merge_generated_hook(cfg.get("hooks", {}) or {}, policy)
        validation = validate_hooks_doc(merged)
        if not validation["valid"]:
            raise ValueError("; ".join(validation["errors"]))
        if merged:
            cfg["hooks"] = merged
        else:
            cfg.pop("hooks", None)
        return cfg

    try:
        updated_config = await locked_rmw_yaml(config_path, _merge)
    except ValueError as exc:
        raise HTTPException(400, detail={"errors": [str(exc)]}) from exc

    evicted = _evict_agent(agent_id)
    compiled_hook = compile_hook(policy) if policy.get("status") == "active" else None
    return {
        "published": True,
        "tenant_id": body.tenant_id,
        "agent_id": agent_id,
        "policy_id": policy_id,
        "status": policy.get("status"),
        "generated_hook": compiled_hook,
        "events": sorted((updated_config.get("hooks") or {}).keys()),
        "evicted_agents": evicted,
        "published_at": datetime.now(timezone.utc).isoformat(),
    }


def _get_path(context: dict[str, Any], field: str) -> Any:
    value: Any = context
    for part in field.split("."):
        if isinstance(value, dict):
            value = value.get(part)
        else:
            return None
    return value


def _evaluate_condition(actual: Any, operator: str, expected: Any) -> bool:
    if operator == "exists":
        return actual not in (None, "")
    if operator == "equals":
        return str(actual) == str(expected)
    if operator == "not_equals":
        return str(actual) != str(expected)
    if operator == "contains":
        return str(expected).lower() in str(actual or "").lower()
    if operator == "not_contains":
        return str(expected).lower() not in str(actual or "").lower()
    if operator == "regex":
        import re

        # Cap pattern/subject length to bound regex backtracking; fail closed on an invalid pattern.
        _REGEX_PATTERN_MAX_LEN = 200
        _REGEX_SUBJECT_MAX_LEN = 4000
        pattern = str(expected)
        subject = str(actual or "")
        if len(pattern) > _REGEX_PATTERN_MAX_LEN or len(subject) > _REGEX_SUBJECT_MAX_LEN:
            return False
        try:
            return re.search(pattern, subject, flags=re.IGNORECASE) is not None
        except re.error:
            return False
    if operator in {"greater_than", "greater_than_or_equal", "less_than", "less_than_or_equal"}:
        left = float(actual or 0)
        right = float(expected or 0)
        return {
            "greater_than": left > right,
            "greater_than_or_equal": left >= right,
            "less_than": left < right,
            "less_than_or_equal": left <= right,
        }[operator]
    if operator in {"in", "not_in"}:
        values = expected if isinstance(expected, list) else [expected]
        result = str(actual) in {str(v) for v in values}
        return result if operator == "in" else not result
    return False


@router.post("/api/policy-control/policies/simulate")
async def simulate_policy_control_decision(
    request: Request, body: PolicySimulateRequest, admin: dict = Depends(require_admin)
):
    """Run a lightweight deterministic policy simulation for UI testing."""
    _require_policy_admin(request, body.tenant_id)
    policy = normalize_policy(body.policy)
    validation = validate_registry_doc({"version": "1.0", "policies": [policy]})
    if not validation["valid"]:
        raise HTTPException(400, detail={"errors": validation["errors"]})
    conditions = policy.get("conditions") or {}
    group_key = "any" if "any" in conditions else "all"
    checks = []
    for cond in conditions.get(group_key, []):
        actual = _get_path(body.context, cond["field"])
        matched = _evaluate_condition(actual, cond["operator"], cond.get("value"))
        checks.append({**cond, "actual": actual, "matched": matched})
    matched = any(c["matched"] for c in checks) if group_key == "any" else all(c["matched"] for c in checks)
    decision = policy["decision"] if matched and policy["status"] != "disabled" else "allow"
    return {
        "policy_id": policy["policy_id"],
        "matched": matched,
        "decision": decision,
        "checks": checks,
        "reason": (
            f"Policy {policy['name']} matched; decision={decision}."
            if matched
            else f"Policy {policy['name']} did not match; decision=allow."
        ),
        "generated_hook": compile_hook(policy) if policy["status"] == "active" else None,
    }

