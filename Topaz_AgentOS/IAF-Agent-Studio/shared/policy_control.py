"""Central Policy & Control Registry helpers.

The registry stores business-friendly policy definitions and compiles active
runtime policies into the existing hook contract. It does not execute arbitrary
code from policy definitions; generated hooks always call the fixed
``policy_engine.py`` evaluator.
"""

from __future__ import annotations

import re
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from shared.config import DATA_ROOT, SERVER_DIR
from shared.hooks_validation import validate_hooks_doc
from iaf_agent_skills.hook_runner import ALLOWED_HOOK_EVENTS


POLICY_GENERATED_PREFIX = "policy."
SUPPORTED_EVENTS = set(ALLOWED_HOOK_EVENTS)
GATEABLE_EVENTS = {
    "BeforeTurn",
    "PreToolUse",
    "PostTurn",
    "BeforeScheduleFire",
    "BeforeQueueItemStart",
    "BeforeApprovalResume",
    "BeforeMissionStart",
    "OnDecompositionComplete",
    "OnResearchWorkstreamCreated",
}
SUPPORTED_DECISIONS = {"allow", "deny", "approve", "escalate"}
SUPPORTED_OPERATORS = {
    "equals",
    "not_equals",
    "contains",
    "not_contains",
    "regex",
    "greater_than",
    "greater_than_or_equal",
    "less_than",
    "less_than_or_equal",
    "in",
    "not_in",
    "exists",
}

EVENT_DESCRIPTIONS = {
    "PreToolUse": "Before a tool/API call executes. Best event for HITL approvals because the call can pause before side effects.",
    "PostToolUse": "After a tool/API call returns. Use for audit, evidence capture, or quality checks.",
    "BeforeTurn": "Before an agent starts processing a user turn. Can block or require approval before reasoning begins.",
    "PostTurn": "After an agent response is produced. Useful for response compliance and review gates.",
    "BeforeScheduleFire": "Before a cron job fires. Can skip or gate scheduled execution.",
    "AfterScheduleFire": "After a cron job finishes successfully. Observe-only audit event.",
    "OnScheduleError": "When a cron job errors. Observe-only remediation/audit event.",
    "BeforeQueueItemStart": "Before a queue item begins processing. Can gate queued work.",
    "AfterQueueItemComplete": "After a queue item completes. Observe-only audit event.",
    "OnQueueItemError": "When a queue item errors. Observe-only remediation/audit event.",
    "BeforeQueueRetry": "Before retrying a failed queue item.",
    "OnQueueDLQ": "When a queue item enters the dead-letter queue.",
    "OnQueueHITLPending": "When queue work pauses for human approval.",
    "PreStep": "Before an orchestrator/workflow step executes.",
    "PostStep": "After an orchestrator/workflow step; can provide feedback.",
    "OnExecutionFailure": "When an execution step fails. Observe-only remediation/audit event.",
    "BeforeApprovalResume": "Before resuming a HITL checkpoint. Can block unsafe resumes.",
    "AfterApprovalResume": "After a HITL checkpoint resume attempt.",
    "OnApprovalResolved": "After an approval decision is recorded.",
    "OnBlocked": "After a blocking hook denies execution.",
    "BeforeModelCall": "Before an LLM/model call. Observe or gate model usage where supported.",
    "AfterModelCall": "After an LLM/model call. Observe-only cost/audit event.",
    "OnTurnEnd": "At the end of a turn. Observe-only lifecycle event.",
    "OnError": "When the agent run errors.",
    "PostSampling": "After model sampling. Observe-only model-output event.",
    "OnKnowledgeEntryPending": "When a knowledge entry is pending review.",
    "OnMemoryWrite": "When memory persistence is attempted.",
    "OnSkillGapDetected": "When the system identifies a missing skill/capability.",
    "OnSelfEvolutionPass": "When self-evolution analysis completes a pass.",
    "OnBackgroundTaskError": "When a background task errors.",
    "BeforeMissionStart": "Before a workstream mission starts. Can gate first activation.",
    "OnMissionItemFailed": "When a workstream item exhausts retries.",
    "OnMissionComplete": "When a workstream reaches terminal state.",
    "OnDecompositionComplete": "After research decomposition. Can gate low-confidence decompositions.",
    "OnResearchWorkstreamCreated": "When a research workstream is about to be created.",
}

REPLAY_SAFE_HITL_EVENTS = {"PreToolUse"}


def tenant_root(tenant_id: str) -> Path:
    return SERVER_DIR / DATA_ROOT / "tenants" / tenant_id


def registry_path(tenant_id: str) -> Path:
    return tenant_root(tenant_id) / "security" / "policy_control.yaml"


def agent_config_path(tenant_id: str, agent_id: str) -> Path:
    return tenant_root(tenant_id) / "agents" / agent_id / "config.yaml"


def hooks_doc_from_agent_config(tenant_id: str, agent_id: str) -> dict[str, list[dict[str, Any]]]:
    path = agent_config_path(tenant_id, agent_id)
    if not path.exists():
        return {}
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    hooks = data.get("hooks", {}) if isinstance(data, dict) else {}
    return hooks if isinstance(hooks, dict) else {}


def default_registry() -> dict[str, Any]:
    return {"version": "1.0", "policies": []}


def policy_event_catalog() -> list[dict[str, Any]]:
    """Return hook events with Policy Control guidance metadata."""
    catalog = []
    for event in sorted(SUPPORTED_EVENTS):
        gateable = event in GATEABLE_EVENTS
        catalog.append(
            {
                "event": event,
                "gateable": gateable,
                "observe_only": not gateable,
                "hitl_safe": event in REPLAY_SAFE_HITL_EVENTS,
                "supports_approve": event in GATEABLE_EVENTS,
                "recommended_decisions": ["allow", "deny", "approve", "escalate"] if gateable else ["allow"],
                "description": EVENT_DESCRIPTIONS.get(event, "Runtime hook lifecycle event."),
            }
        )
    return catalog


def extract_policy_authoring_yaml(text: str) -> str:
    """Extract the YAML payload emitted by the Policy Authoring skill."""
    raw = str(text or "").strip()
    if not raw:
        raise ValueError("Policy authoring skill returned an empty response.")
    match = re.search(r"```(?:ya?ml)?\s*(.*?)```", raw, flags=re.IGNORECASE | re.DOTALL)
    return (match.group(1) if match else raw).strip()


def parse_policy_authoring_response(text: str, *, tenant_id: str = "company", agent_id: str = "enterprise_agent") -> dict[str, Any]:
    """Parse LLM-authored YAML into a normalized Policy Control draft."""
    yaml_text = extract_policy_authoring_yaml(text)
    try:
        doc = yaml.safe_load(yaml_text) or {}
    except yaml.YAMLError as exc:
        raise ValueError(f"Policy authoring skill returned invalid YAML: {exc}") from exc
    if not isinstance(doc, dict):
        raise ValueError("Policy authoring YAML must be a mapping.")
    policy_doc = doc.get("policy", doc)
    if not isinstance(policy_doc, dict):
        raise ValueError("Policy authoring YAML must include a policy mapping.")
    policy = normalize_policy(policy_doc)
    policy.setdefault("scope", {})
    policy["scope"]["tenant_id"] = policy["scope"].get("tenant_id") or tenant_id
    policy["scope"]["agent_id"] = policy["scope"].get("agent_id") or agent_id
    sample_context = doc.get("sample_context") if isinstance(doc.get("sample_context"), dict) else {}
    assumptions = doc.get("assumptions") if isinstance(doc.get("assumptions"), list) else []
    if not assumptions:
        assumptions = ["Drafted by the Policy Authoring skill; review, validate, and simulate before publishing."]
    bundle = policy_yaml_bundle(policy, sample_context=sample_context, assumptions=assumptions)
    return {
        "policy": policy,
        "policy_yaml": yaml.safe_dump(policy, sort_keys=False),
        "authoring_yaml": bundle,
        "sample_context": sample_context,
        "assumptions": [str(item) for item in assumptions],
        "event_catalog": policy_event_catalog(),
    }


def policy_yaml_bundle(
    policy: dict[str, Any],
    *,
    sample_context: dict[str, Any] | None = None,
    assumptions: list[Any] | None = None,
) -> str:
    """Return the readable Policy Control YAML bundle shown in the editor."""
    normalized = normalize_policy(policy)
    hooks = compile_hooks_for_policy({**normalized, "status": "active"})
    bundle = {
        "policy": normalized,
        "hooks": hooks,
    }
    if sample_context:
        bundle["sample_context"] = sample_context
    if assumptions:
        bundle["assumptions"] = [str(item) for item in assumptions]
    return yaml.safe_dump(bundle, sort_keys=False)


def load_registry(tenant_id: str) -> dict[str, Any]:
    path = registry_path(tenant_id)
    if not path.exists():
        return default_registry()
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        return default_registry()
    data.setdefault("version", "1.0")
    data.setdefault("policies", [])
    return data


def normalize_policy(policy: dict[str, Any]) -> dict[str, Any]:
    out = deepcopy(policy or {})
    out["policy_id"] = str(out.get("policy_id") or slugify(out.get("name") or "policy"))
    out["name"] = str(out.get("name") or out["policy_id"].replace("_", " ").title())
    out["description"] = str(out.get("description") or "")
    out["owner"] = str(out.get("owner") or "Governance")
    out["version"] = int(out.get("version") or 1)
    out["status"] = str(out.get("status") or "draft").lower()
    out["risk_tier"] = str(out.get("risk_tier") or "L2").upper()
    out["event"] = str(out.get("event") or "PreToolUse")
    out["matcher"] = str(out.get("matcher") or ".*")
    out["decision"] = str(out.get("decision") or "deny").lower()
    out["fail_policy"] = str(out.get("fail_policy") or "closed").lower()
    out["block_on_nonzero"] = bool(out.get("block_on_nonzero", out["decision"] in {"deny", "approve", "escalate"}))
    out["mode"] = str(out.get("mode") or ("blocking" if out["event"] in GATEABLE_EVENTS else "observe"))
    out["timeout_seconds"] = int(out.get("timeout_seconds") or 10)
    out["priority"] = int(out.get("priority") or 150)
    out["scope"] = out.get("scope") if isinstance(out.get("scope"), dict) else {}
    out["scope"].setdefault("tenant_id", "company")
    out["scope"].setdefault("agent_id", "enterprise_agent")
    skills = out["scope"].get("skills") or []
    if isinstance(skills, str):
        skills = [skills]
    out["scope"]["skills"] = [str(s) for s in skills if str(s).strip()]
    out["conditions"] = normalize_conditions(out.get("conditions"))
    evidence = out.get("evidence") if isinstance(out.get("evidence"), dict) else {}
    required = evidence.get("required") or ["trace_id", "tool_input", "matched_conditions"]
    if isinstance(required, str):
        required = [required]
    out["evidence"] = {"required": [str(item) for item in required]}
    approval = out.get("approval") if isinstance(out.get("approval"), dict) else {}
    out["approval"] = {
        "approver_role": str(approval.get("approver_role") or "approver"),
        "sla_minutes": int(approval.get("sla_minutes") or 30),
        "on_timeout": str(approval.get("on_timeout") or "escalate"),
    }
    now = datetime.now(timezone.utc).isoformat()
    out.setdefault("created_at", now)
    out["updated_at"] = now
    return out


def normalize_conditions(value: Any) -> dict[str, list[dict[str, Any]]]:
    if isinstance(value, dict):
        raw = value.get("all", value.get("any", []))
        key = "any" if "any" in value else "all"
    elif isinstance(value, list):
        raw = value
        key = "all"
    else:
        raw = []
        key = "all"
    conditions = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        conditions.append(
            {
                "field": str(item.get("field") or "tool_input.command"),
                "operator": str(item.get("operator") or "contains"),
                "value": item.get("value", ""),
            }
        )
    return {key: conditions}


def slugify(value: Any) -> str:
    text = str(value or "policy").strip().lower()
    text = re.sub(r"[^a-z0-9]+", "_", text).strip("_")
    return text[:80] or "policy"


def titleize_identifier(value: Any) -> str:
    return str(value or "hook").replace("_", " ").replace("-", " ").strip().title()


def is_generated_policy_hook(hook: dict[str, Any]) -> bool:
    return str(hook.get("hook_id") or "").startswith(POLICY_GENERATED_PREFIX)


def infer_hook_decision(hook: dict[str, Any]) -> str:
    haystack = " ".join(
        str(hook.get(key) or "").lower()
        for key in ("hook_id", "command", "description")
    )
    if any(token in haystack for token in ("hitl", "approval", "approve")):
        return "approve"
    if hook.get("block_on_nonzero") or str(hook.get("mode") or "").lower() == "blocking":
        return "deny"
    return "allow"


def hook_to_adoptable_policy(
    tenant_id: str,
    agent_id: str,
    event: str,
    hook: dict[str, Any],
    index: int,
) -> dict[str, Any]:
    hook_id = str(hook.get("hook_id") or f"{event.lower()}_{index + 1}")
    decision = infer_hook_decision(hook)
    return normalize_policy(
        {
            "policy_id": f"adopted_{slugify(hook_id)}",
            "name": titleize_identifier(hook_id),
            "description": f"Adopted from Skill Builder hook '{hook_id}'.",
            "owner": "Governance",
            "status": "draft",
            "risk_tier": "L2",
            "event": event,
            "matcher": str(hook.get("matcher") or ".*"),
            "decision": decision,
            "fail_policy": str(hook.get("fail_policy") or "closed"),
            "block_on_nonzero": bool(hook.get("block_on_nonzero", decision in {"deny", "approve", "escalate"})),
            "mode": str(hook.get("mode") or ("blocking" if decision in {"deny", "approve", "escalate"} else "observe")),
            "timeout_seconds": int(hook.get("timeout_seconds") or 10),
            "priority": int(hook.get("priority") or 150),
            "scope": {
                "tenant_id": tenant_id,
                "agent_id": agent_id,
                "skills": hook.get("skills") or [],
            },
            "conditions": {"all": []},
            "evidence": {"required": ["trace_id", "tool_input", "hook_id", "hook_result"]},
            "approval": {"approver_role": "approver", "sla_minutes": 30, "on_timeout": "escalate"},
        }
    )


def unmanaged_hook_controls(
    tenant_id: str,
    agent_id: str,
    managed_policies: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    managed_hook_ids = {
        generated_hook_id(normalize_policy(policy))
        for policy in (managed_policies or [])
        if isinstance(policy, dict)
    }
    controls: list[dict[str, Any]] = []
    hooks = hooks_doc_from_agent_config(tenant_id, agent_id)
    for event, entries in hooks.items():
        if not isinstance(entries, list):
            continue
        for index, raw_hook in enumerate(entries):
            if not isinstance(raw_hook, dict):
                continue
            hook = deepcopy(raw_hook)
            hook_id = str(hook.get("hook_id") or f"{event.lower()}_{index + 1}")
            if is_generated_policy_hook(hook) or hook_id in managed_hook_ids:
                continue
            decision = infer_hook_decision(hook)
            controls.append(
                {
                    "control_id": f"hook:{tenant_id}:{agent_id}:{event}:{hook_id}",
                    "policy_id": f"hook:{hook_id}",
                    "name": titleize_identifier(hook_id),
                    "description": "Tenant hook authored in Skill Builder V2 Hooks.",
                    "owner": "Skill Builder V2",
                    "status": "active",
                    "risk_tier": "L2",
                    "event": event,
                    "matcher": str(hook.get("matcher") or ".*"),
                    "decision": decision,
                    "fail_policy": str(hook.get("fail_policy") or "closed"),
                    "block_on_nonzero": bool(hook.get("block_on_nonzero", decision in {"deny", "approve", "escalate"})),
                    "mode": str(hook.get("mode") or ("blocking" if decision in {"deny", "approve", "escalate"} else "observe")),
                    "timeout_seconds": int(hook.get("timeout_seconds") or 10),
                    "priority": int(hook.get("priority") or 150),
                    "scope": {"tenant_id": tenant_id, "agent_id": agent_id, "skills": hook.get("skills") or []},
                    "source_type": "unmanaged_hook",
                    "managed": False,
                    "read_only": True,
                    "source": {
                        "type": "skill_builder_hook",
                        "tenant_id": tenant_id,
                        "agent_id": agent_id,
                        "event": event,
                        "hook_id": hook_id,
                    },
                    "hook": hook,
                    "adoptable_policy": hook_to_adoptable_policy(tenant_id, agent_id, event, hook, index),
                }
            )
    return controls


def validate_registry_doc(doc: dict[str, Any]) -> dict[str, Any]:
    errors: list[str] = []
    warnings: list[str] = []
    policies = doc.get("policies")
    if not isinstance(policies, list):
        return {"valid": False, "errors": ["Top-level 'policies' must be a list."], "warnings": [], "policy_count": 0}
    seen: set[str] = set()
    for idx, raw_policy in enumerate(policies):
        prefix = f"policies[{idx}]"
        if not isinstance(raw_policy, dict):
            errors.append(f"{prefix}: policy must be a mapping.")
            continue
        policy = normalize_policy(raw_policy)
        pid = policy["policy_id"]
        if not re.match(r"^[A-Za-z0-9_.:-]{1,96}$", pid):
            errors.append(f"{prefix}: policy_id must use letters, numbers, underscore, dot, colon, or dash.")
        if pid in seen:
            errors.append(f"{prefix}: duplicate policy_id '{pid}'.")
        seen.add(pid)
        if policy["status"] not in {"draft", "active", "disabled"}:
            errors.append(f"{prefix}: status must be draft, active, or disabled.")
        if policy["event"] not in SUPPORTED_EVENTS:
            errors.append(f"{prefix}: event '{policy['event']}' is not supported by the registry UI.")
        if policy["decision"] not in SUPPORTED_DECISIONS:
            errors.append(f"{prefix}: decision must be one of {', '.join(sorted(SUPPORTED_DECISIONS))}.")
        if policy["fail_policy"] not in {"open", "closed"}:
            errors.append(f"{prefix}: fail_policy must be open or closed.")
        if policy["decision"] in {"deny", "approve", "escalate"} and policy["event"] not in GATEABLE_EVENTS:
            errors.append(f"{prefix}: decision '{policy['decision']}' needs a gateable event.")
        for group_key in ("all", "any"):
            for c_idx, cond in enumerate(policy["conditions"].get(group_key, [])):
                op = cond.get("operator")
                if op not in SUPPORTED_OPERATORS:
                    errors.append(f"{prefix}: condition {group_key}[{c_idx}] has unsupported operator '{op}'.")
        if policy["decision"] == "approve" and policy["event"] != "PreToolUse":
            warnings.append(f"{prefix}: approval policies are most reliable on PreToolUse because tool replay is already checkpointed.")
    return {"valid": not errors, "errors": errors, "warnings": warnings, "policy_count": len(policies)}


def generated_hook_id(policy: dict[str, Any]) -> str:
    return f"{POLICY_GENERATED_PREFIX}{policy['policy_id']}.v{policy['version']}"


def compile_hook(policy: dict[str, Any]) -> dict[str, Any]:
    normalized = normalize_policy(policy)
    decision = normalized["decision"]
    approval_cfg = normalized.get("approval") or {}
    on_block = "hitl" if decision == "approve" else "deny"
    hook = {
        "hook_id": generated_hook_id(normalized),
        "command": (
            "python3 $IAF_AGENT_ROOT/../../shared/hooks/policy_engine.py "
            f"--policy-id {normalized['policy_id']}"
        ),
        "matcher": normalized["matcher"],
        "mode": normalized["mode"],
        "fail_policy": normalized["fail_policy"],
        "block_on_nonzero": normalized["block_on_nonzero"],
        "on_block": on_block,
        "timeout_seconds": normalized["timeout_seconds"],
        "priority": normalized["priority"],
    }
    if decision == "approve":
        hook["approval"] = {
            "reason": normalized.get("description") or f"{normalized['name']} requires human approval.",
            "urgency": "critical" if normalized.get("risk_tier") == "CRITICAL" else "high",
            "sla_minutes": int(approval_cfg.get("sla_minutes") or 30),
            "options": ["Approve", "Reject"],
            "rule_type": "policy_control",
            "context": {
                "policy_id": normalized["policy_id"],
                "policy_name": normalized["name"],
                "approver_role": approval_cfg.get("approver_role") or "approver",
                "on_timeout": approval_cfg.get("on_timeout") or "escalate",
                "risk_tier": normalized.get("risk_tier") or "L2",
            },
        }
    skills = normalized.get("scope", {}).get("skills") or []
    if skills:
        hook["skills"] = skills
    return hook


def compile_hooks_for_policy(policy: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    normalized = normalize_policy(policy)
    if normalized["status"] != "active":
        return {}
    return {normalized["event"]: [compile_hook(normalized)]}


def merge_generated_hook(existing_hooks: dict[str, Any], policy: dict[str, Any]) -> dict[str, Any]:
    """Replace this policy's generated hook while preserving all manual hooks."""
    normalized = normalize_policy(policy)
    target_id = generated_hook_id(normalized)
    merged: dict[str, list[dict[str, Any]]] = {}
    for event, entries in (existing_hooks or {}).items():
        if not isinstance(entries, list):
            continue
        kept = [
            entry
            for entry in entries
            if not (isinstance(entry, dict) and str(entry.get("hook_id", "")) == target_id)
        ]
        if kept:
            merged[event] = kept
    if normalized["status"] == "active":
        merged.setdefault(normalized["event"], []).append(compile_hook(normalized))
    return merged


def validate_compiled_hook(policy: dict[str, Any]) -> dict[str, Any]:
    hooks = compile_hooks_for_policy(policy)
    if not hooks:
        return {"valid": True, "errors": [], "warnings": ["Policy is not active; no hook will be generated."], "hook_count": 0}
    return validate_hooks_doc(hooks)

