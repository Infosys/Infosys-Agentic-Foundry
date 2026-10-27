"""Security Console APIs for entitlement operations."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import yaml
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from auth.middleware import require_admin, require_auth, require_permission
from security.dependencies import enforce_entitlement, principal_from_request, bind_request_identity
from security.models import Principal, Resource
from security.yaml_provider import (
    YamlEntitlementProvider,
    parse_policy_yaml,
    validate_policy_doc,
    validate_policy_yaml,
)
from shared.config import DATA_ROOT, SERVER_DIR, SKILLS_PATH
from shared.file_utils import atomic_write_text
from shared.user_display import apply_display_names as _apply_owner_display_names
from agent_os.external_access import (
    list_external_resources,
    parse_external_access_yaml,
    registry_path as external_registry_path,
    validate_external_access_doc,
)


router = APIRouter(tags=["security"])


class PolicySaveRequest(BaseModel):
    tenant_id: str = "company"
    raw: str


class ExternalAccessSaveRequest(BaseModel):
    tenant_id: str = "company"
    raw: str


class ExternalAccessValidateRequest(BaseModel):
    raw: str


class CredentialSaveRequest(BaseModel):
    tenant_id: str = "company"
    type: str = "bearer"
    value: dict[str, str] = Field(default_factory=dict)
    scope: list[str] = Field(default_factory=list)
    ttl: int | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class PolicyValidateRequest(BaseModel):
    raw: str


class SimulatedPrincipal(BaseModel):
    user_id: str
    email: str = ""
    roles: list[str] = Field(default_factory=list)
    groups: list[str] = Field(default_factory=list)
    allowed_tenants: list[str] | None = None


class SimulatedResource(BaseModel):
    type: str
    id: str


class SimulateRequest(BaseModel):
    tenant_id: str = "company"
    principal: SimulatedPrincipal
    action: str
    resource: SimulatedResource
    context: dict[str, Any] = Field(default_factory=dict)


class EffectiveAccessRequest(BaseModel):
    tenant_id: str = "company"
    principal: SimulatedPrincipal
    include_denied: bool = True


def _policy_path(tenant_id: str) -> Path:
    return SERVER_DIR / DATA_ROOT / "tenants" / tenant_id / "security" / "policies.yaml"


def _audit_path(tenant_id: str) -> Path:
    return SERVER_DIR / DATA_ROOT / "tenants" / tenant_id / "shared" / "databases" / "entitlements_audit.jsonl"


def _external_audit_path(tenant_id: str) -> Path:
    return SERVER_DIR / DATA_ROOT / "tenants" / tenant_id / "shared" / "databases" / "external_access_audit.jsonl"


def _credential_config_dir(tenant_id: str) -> Path:
    return SERVER_DIR / DATA_ROOT / "tenants" / tenant_id / "shared" / "config"


def _tenant_root(tenant_id: str) -> Path:
    return SERVER_DIR / DATA_ROOT / "tenants" / tenant_id


def _external_registry_response(tenant_id: str, raw: str) -> dict:
    parsed, parse_errors = parse_external_access_yaml(raw)
    validation = validate_external_access_doc(parsed) if not parse_errors else {
        "valid": False,
        "errors": parse_errors,
        "warnings": [],
        "resource_count": 0,
    }
    resources = [
        {
            "id": resource.id,
            "type": resource.type,
            "label": resource.label,
            "risk": resource.risk,
            "credentials": list(resource.credentials),
            "mcp_connections": list(resource.mcp_connections),
            "context_files": list(resource.context_files),
            "tools": list(resource.tools),
            "owners": list(resource.owners),
        }
        for resource in list_external_resources(_tenant_root(tenant_id))
    ]
    return {
        "tenant_id": tenant_id,
        "path": str(external_registry_path(_tenant_root(tenant_id))),
        "raw": raw,
        "parsed": parsed,
        "validation": validation,
        "resources": resources,
        "resource_count": validation.get("resource_count", 0),
    }


def _skills_root(tenant_id: str) -> Path:
    tenant_skills = _tenant_root(tenant_id) / "skills"
    return tenant_skills if tenant_skills.exists() else SERVER_DIR / SKILLS_PATH


def _require_security_admin(request: Request, tenant_id: str) -> None:
    enforce_entitlement(principal_from_request(request, tenant_id), "manage", "security", "policies")


def _require_credential_owner_or_admin(request: Request, tenant_id: str, owner: str | None) -> None:
    """Only a credential's creator or an admin may update/delete it. Any
    authenticated user may create a new credential (shared for others to
    reference). Legacy credentials with no recorded creator are admin-owned."""
    principal = principal_from_request(request, tenant_id)
    if "admin" in (getattr(principal, "roles", ()) or ()):
        return
    idents = {v for v in (getattr(principal, "email", None), getattr(principal, "user_id", None)) if v}
    cred_owner = owner or "admin@iaf.local"
    if cred_owner not in idents:
        raise HTTPException(
            status_code=403,
            detail=f"Only the owner ({cred_owner}) or an admin can modify this credential.",
        )


def _policy_response(tenant_id: str, raw: str, *, q: str | None = None, effect: str | None = None) -> dict:
    parsed, parse_errors = parse_policy_yaml(raw)
    validation = validate_policy_doc(parsed) if not parse_errors else {
        "valid": False,
        "errors": parse_errors,
        "warnings": [],
        "policy_count": 0,
    }
    policies = parsed.get("policies", []) if isinstance(parsed, dict) else []
    filtered_policy_ids: list[str] = []
    filtered_policy_indexes: list[int] = []
    if q or effect:
        term = (q or "").strip().lower()
        wanted_effect = (effect or "").strip().lower()
        for index, policy in enumerate(policies):
            if not isinstance(policy, dict):
                continue
            if wanted_effect and str(policy.get("effect", "")).lower() != wanted_effect:
                continue
            haystack = " ".join(
                str(value)
                for value in [
                    policy.get("id", ""),
                    policy.get("reason", ""),
                    " ".join(str(item) for item in (policy.get("roles", []) or [])),
                    " ".join(str(item) for item in (policy.get("groups", []) or [])),
                    " ".join(str(item) for item in (policy.get("resources", []) or [])),
                ]
            ).lower()
            if term and term not in haystack:
                continue
            filtered_policy_ids.append(str(policy.get("id", "")))
            filtered_policy_indexes.append(index)
    return {
        "tenant_id": tenant_id,
        "path": str(_policy_path(tenant_id)),
        "raw": raw,
        "parsed": parsed,
        "validation": validation,
        "policy_count": validation.get("policy_count", 0),
        "filtered_policy_ids": filtered_policy_ids,
        "filtered_policy_indexes": filtered_policy_indexes,
        "filtered_policy_count": len(filtered_policy_ids),
    }


def _principal_from_body(tenant_id: str, body: SimulatedPrincipal) -> Principal:
    return Principal(
        user_id=body.user_id,
        email=body.email,
        tenant_id=tenant_id,
        roles=tuple(body.roles or ["user"]),
        groups=tuple(body.groups or []),
        allowed_tenants=tuple(body.allowed_tenants or [tenant_id]),
    )


def _decision_payload(provider: YamlEntitlementProvider, principal: Principal, action: str, resource: Resource) -> dict:
    decision = provider.can(principal, action, resource, {})
    return {
        "action": action,
        "allowed": decision.allowed,
        "reason": decision.reason,
        "matched_policy": decision.matched_policy,
        "metadata": decision.metadata,
    }


def _read_skill_names(tenant_id: str) -> list[str]:
    skills_root = _skills_root(tenant_id)
    names: set[str] = set()
    index_path = skills_root / "_index.yaml"
    if index_path.exists():
        try:
            index = yaml.safe_load(index_path.read_text(encoding="utf-8")) or {}
            names.update(str(name) for name in (index.get("skills") or {}).keys())
        except Exception:
            pass
    if skills_root.exists():
        for child in skills_root.iterdir():
            if child.is_dir() and (child / "SKILL.md").exists():
                names.add(child.name)
    return sorted(names)


def _read_agent_ids(tenant_id: str) -> list[str]:
    agents_root = _tenant_root(tenant_id) / "agents"
    if not agents_root.exists():
        return []
    return sorted(child.name for child in agents_root.iterdir() if child.is_dir() and not child.name.startswith("."))


def _read_tool_ids(tenant_id: str) -> list[str]:
    tools = {
        "shell",
        "write_file",
        "run_sql_query",
        "query_memory",
        "invoke_skill",
        "invoke_plan",
        "create_plan",
    }
    for skill_name in _read_skill_names(tenant_id):
        skill_file = _skills_root(tenant_id) / skill_name / "SKILL.md"
        if not skill_file.exists():
            continue
        try:
            raw = skill_file.read_text(encoding="utf-8")
            if raw.startswith("---"):
                parts = raw.split("---", 2)
                if len(parts) >= 3:
                    frontmatter = yaml.safe_load(parts[1]) or {}
                    tools.update(str(tool) for tool in (frontmatter.get("tools") or []))
        except Exception:
            continue
    return sorted(tools)


def _read_context_ids(tenant_id: str) -> list[str]:
    shared_root = _tenant_root(tenant_id) / "shared"
    if not shared_root.exists():
        return []
    contexts: set[str] = set()
    master = shared_root / "Enterprise_Context.md"
    if master.exists():
        contexts.add("/shared/Enterprise_Context.md")
    contexts_dir = shared_root / "contexts"
    if contexts_dir.exists():
        for path in sorted(contexts_dir.rglob("*.md"))[:300]:
            rel = path.relative_to(shared_root).as_posix()
            contexts.add(f"/shared/{rel}")
    return sorted(contexts)


def _read_external_ids(tenant_id: str) -> list[str]:
    return sorted(
        resource.resource_id for resource in list_external_resources(_tenant_root(tenant_id))
        if resource.type not in {"db"}
    )


def _read_external_db_ids(tenant_id: str) -> list[str]:
    return sorted(
        resource.resource_id for resource in list_external_resources(_tenant_root(tenant_id))
        if resource.type == "db"
    )


def _read_mcp_ids(tenant_id: str) -> list[str]:
    names = set()
    for resource in list_external_resources(_tenant_root(tenant_id)):
        names.update(resource.mcp_connections)
    for skill_name in _read_skill_names(tenant_id):
        skill_file = _skills_root(tenant_id) / skill_name / "SKILL.md"
        if not skill_file.exists():
            continue
        try:
            raw = skill_file.read_text(encoding="utf-8")
            if raw.startswith("---"):
                parts = raw.split("---", 2)
                if len(parts) >= 3:
                    frontmatter = yaml.safe_load(parts[1]) or {}
                    for conn in (frontmatter.get("mcp_connections") or []):
                        if isinstance(conn, dict) and conn.get("name"):
                            names.add(str(conn["name"]))
        except Exception:
            continue
    return sorted(names)


def _evaluate_resources(
    provider: YamlEntitlementProvider,
    principal: Principal,
    resource_type: str,
    resource_ids: list[str],
    actions: list[str],
    include_denied: bool,
) -> dict:
    allowed: list[dict] = []
    denied: list[dict] = []
    for resource_id in resource_ids:
        resource = Resource(resource_type, resource_id, tenant_id=principal.tenant_id)
        decisions = [_decision_payload(provider, principal, action, resource) for action in actions]
        allowed_actions = [item["action"] for item in decisions if item["allowed"]]
        row = {
            "id": resource_id,
            "key": resource.key,
            "allowed": bool(allowed_actions),
            "allowed_actions": allowed_actions,
            "denied_actions": [item["action"] for item in decisions if not item["allowed"]],
            "decisions": decisions,
        }
        if allowed_actions:
            allowed.append(row)
        elif include_denied:
            denied.append(row)
    return {"allowed": allowed, "denied": denied, "total": len(resource_ids)}


@router.get("/api/security/policies")
async def get_security_policies(
    request: Request,
    tenant_id: str = "company",
    q: str | None = None,
    effect: str | None = None,
    admin: dict = Depends(require_admin),
):
    """Return raw and parsed tenant entitlement policies."""
    _require_security_admin(request, tenant_id)
    path = _policy_path(tenant_id)
    raw = path.read_text(encoding="utf-8") if path.exists() else "version: \"1.0\"\npolicies: []\n"
    return _policy_response(tenant_id, raw, q=q, effect=effect)


@router.post("/api/security/policies/validate")
async def validate_security_policies(body: PolicyValidateRequest, admin: dict = Depends(require_admin)):
    """Validate entitlement policy YAML without saving it."""
    return validate_policy_yaml(body.raw)


@router.get("/api/security/external-access")
async def get_external_access_registry(request: Request, tenant_id: str = "company", admin: dict = Depends(require_admin)):
    """Return tenant external access registry and linked enforcement objects."""
    _require_security_admin(request, tenant_id)
    path = external_registry_path(_tenant_root(tenant_id))
    raw = path.read_text(encoding="utf-8") if path.exists() else "version: \"1.0\"\nresources: []\n"
    return _external_registry_response(tenant_id, raw)


@router.put("/api/security/policies")
async def save_security_policies(request: Request, body: PolicySaveRequest, admin: dict = Depends(require_admin)):
    """Validate and atomically save tenant entitlement policies."""
    _require_security_admin(request, body.tenant_id)
    validation = validate_policy_yaml(body.raw)
    if not validation["valid"]:
        raise HTTPException(
            status_code=400,
            detail={
                "errors": validation["errors"],
                "conflict_details": validation.get("conflict_details", []),
            },
        )
    # Preserve admin-authored formatting so temporary policy changes can be
    # restored byte-for-byte after integration tests or break-glass edits.
    atomic_write_text(_policy_path(body.tenant_id), body.raw)
    return _policy_response(body.tenant_id, body.raw)


@router.post("/api/security/simulate")
async def simulate_security_decision(request: Request, body: SimulateRequest, admin: dict = Depends(require_admin)):
    """Evaluate a policy decision for an arbitrary principal/action/resource tuple."""
    _require_security_admin(request, body.tenant_id)
    principal = _principal_from_body(body.tenant_id, body.principal)
    resource = Resource(body.resource.type, body.resource.id, tenant_id=body.tenant_id)
    decision = YamlEntitlementProvider().can(principal, body.action, resource, body.context)
    return {
        "allowed": decision.allowed,
        "reason": decision.reason,
        "matched_policy": decision.matched_policy,
        "metadata": decision.metadata,
        "principal": {
            "user_id": principal.user_id,
            "email": principal.email,
            "roles": list(principal.roles),
            "groups": list(principal.groups),
            "tenant_id": principal.tenant_id,
        },
        "action": body.action,
        "resource": resource.key,
    }


@router.post("/api/security/effective-access")
async def get_effective_access(request: Request, body: EffectiveAccessRequest, admin: dict = Depends(require_admin)):
    """Return effective access for a principal across live tenant resources."""
    _require_security_admin(request, body.tenant_id)
    principal = _principal_from_body(body.tenant_id, body.principal)
    provider = YamlEntitlementProvider()
    resources = {
        "agents": _evaluate_resources(provider, principal, "agent", _read_agent_ids(body.tenant_id), ["use"], body.include_denied),
        "skills": _evaluate_resources(provider, principal, "skill", _read_skill_names(body.tenant_id), ["use", "read", "test"], body.include_denied),
        "tools": _evaluate_resources(provider, principal, "tool", _read_tool_ids(body.tenant_id), ["use"], body.include_denied),
        "contexts": _evaluate_resources(provider, principal, "context", _read_context_ids(body.tenant_id), ["read"], body.include_denied),
        "external_resources": _evaluate_resources(provider, principal, "external", _read_external_ids(body.tenant_id), ["access"], body.include_denied),
        "databases": _evaluate_resources(provider, principal, "external", _read_external_db_ids(body.tenant_id), ["read", "write", "delete"], body.include_denied),
        "mcp_connections": _evaluate_resources(provider, principal, "mcp", _read_mcp_ids(body.tenant_id), ["call"], body.include_denied),
    }
    summary = {
        key: {
            "allowed": len(value["allowed"]),
            "denied": len(value["denied"]),
            "total": value["total"],
        }
        for key, value in resources.items()
    }
    return {
        "tenant_id": body.tenant_id,
        "principal": {
            "user_id": principal.user_id,
            "email": principal.email,
            "roles": list(principal.roles),
            "groups": list(principal.groups),
            "tenant_id": principal.tenant_id,
        },
        "summary": summary,
        "resources": resources,
        "external_inventory": [
            {
                "id": resource.id,
                "type": resource.type,
                "label": resource.label,
                "risk": resource.risk,
                "credentials": list(resource.credentials),
                "mcp_connections": list(resource.mcp_connections),
            }
            for resource in list_external_resources(_tenant_root(body.tenant_id))
        ],
    }


@router.get("/api/security/audit")
async def list_security_audit(
    request: Request,
    tenant_id: str = "company",
    user_id: str = "",
    action: str = "",
    resource: str = "",
    allowed: str = "",
    limit: int = 100,
    admin: dict = Depends(require_admin),
):
    """Read recent entitlement audit events with lightweight filters."""
    _require_security_admin(request, tenant_id)
    paths = [path for path in (_audit_path(tenant_id), _external_audit_path(tenant_id)) if path.exists()]
    if not paths:
        return {"tenant_id": tenant_id, "events": [], "count": 0}

    max_rows = max(1, min(limit, 500))
    allowed_filter = None
    if allowed.lower() in {"true", "1", "yes", "allowed"}:
        allowed_filter = True
    elif allowed.lower() in {"false", "0", "no", "denied"}:
        allowed_filter = False

    candidates = []
    for path in paths:
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                event = json.loads(line)
            except Exception:
                continue
            event.setdefault("audit_source", path.name)
            candidates.append(event)
    candidates.sort(key=lambda item: str(item.get("timestamp", "")), reverse=True)

    events = []
    for event in candidates:
        if user_id and user_id.lower() not in str(event.get("user_id", "")).lower() and user_id.lower() not in str(event.get("email", "")).lower():
            continue
        if action and action.lower() not in str(event.get("action", "")).lower():
            continue
        if resource and resource.lower() not in str(event.get("resource", "")).lower():
            continue
        if allowed_filter is not None and bool(event.get("allowed")) is not allowed_filter:
            continue
        events.append(event)
        if len(events) >= max_rows:
            break
    return {"tenant_id": tenant_id, "events": events, "count": len(events)}


@router.post("/api/security/external-access/validate")
async def validate_external_access(request: Request, body: ExternalAccessValidateRequest, admin: dict = Depends(require_admin)):
    """Validate external access YAML without saving."""
    parsed, parse_errors = parse_external_access_yaml(body.raw)
    if parse_errors:
        return {"valid": False, "errors": parse_errors, "warnings": [], "resource_count": 0}
    return validate_external_access_doc(parsed)


@router.put("/api/security/external-access")
async def save_external_access(request: Request, body: ExternalAccessSaveRequest, admin: dict = Depends(require_admin)):
    """Validate and atomically save tenant external access registry."""
    _require_security_admin(request, body.tenant_id)
    parsed, parse_errors = parse_external_access_yaml(body.raw)
    if parse_errors:
        raise HTTPException(status_code=400, detail={"errors": parse_errors})
    validation = validate_external_access_doc(parsed)
    if not validation["valid"]:
        raise HTTPException(status_code=400, detail={"errors": validation["errors"]})
    path = external_registry_path(_tenant_root(body.tenant_id))
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_text(path, body.raw)
    return _external_registry_response(body.tenant_id, body.raw)


@router.get("/api/credentials")
async def list_credentials(request: Request, tenant_id: str = "company", user: dict = Depends(require_auth)):
    """List credential metadata for a tenant. Sensitive values are NEVER returned.
    Any authenticated user may read credential names/types/scope for reference in skills.
    Mutating operations (PUT, DELETE) remain admin-only."""
    # Bind the tenant to allowed_tenants; require_auth does not, so ?tenant_id= could enumerate another tenant.
    bind_request_identity(request, tenant_id)
    config_dir = _credential_config_dir(tenant_id)
    cred_path = config_dir / "credentials.yaml"
    if not cred_path.exists():
        return {"tenant_id": tenant_id, "credentials": [], "count": 0}
    from agent_os.credential_store import FernetFileBackend
    backend = FernetFileBackend(cred_path)
    items = backend.list_metadata()
    # Owner is stored under item["metadata"]["created_by"]; resolve display names
    # on the nested mapping and leave the raw identity intact for ownership checks.
    await _apply_owner_display_names(
        [item["metadata"] for item in items if isinstance(item.get("metadata"), dict)]
    )
    return {"tenant_id": tenant_id, "credentials": items, "count": len(items)}


@router.put("/api/credentials/{name}")
async def save_credential(request: Request, name: str, body: CredentialSaveRequest, user: dict = Depends(require_permission("skills.author"))):
    """Create or update a credential. Values are encrypted at rest.

    Requires the developer 'skills.author' capability (plain 'user' role is
    excluded). A new credential is shared so other users' skills can reference
    it; updating an existing credential is further restricted to its creator or
    an admin."""
    # Bind the tenant to allowed_tenants; require_permission checks only the role (blocks cross-tenant writes and traversal).
    bind_request_identity(request, body.tenant_id)
    if not name or not name.strip():
        raise HTTPException(status_code=400, detail="Credential name is required")
    if not body.type:
        raise HTTPException(status_code=400, detail="Credential type is required")
    cred_data: dict[str, Any] = {"type": body.type}
    # Merge value fields (token, key, username, PWD, etc.) into top level
    for k, v in body.value.items():
        if v:  # Only write non-empty sensitive fields
            cred_data[k] = v
    if body.scope:
        cred_data["scope"] = body.scope
    if body.ttl is not None:
        cred_data["ttl"] = body.ttl
    if body.metadata:
        cred_data["metadata"] = body.metadata

    config_dir = _credential_config_dir(body.tenant_id)
    config_dir.mkdir(parents=True, exist_ok=True)
    cred_path = config_dir / "credentials.yaml"
    from agent_os.credential_store import FernetFileBackend
    backend = FernetFileBackend(cred_path)

    # If updating and no new sensitive values provided, preserve existing sensitive
    existing = backend.get(name)
    if existing:
        # Updating an existing credential is restricted to its creator or an admin.
        _require_credential_owner_or_admin(
            request, body.tenant_id, (existing.get("metadata") or {}).get("created_by")
        )
        # Vault connections carry secret_id (AppRole) — include it so a blank-on-edit
        # keeps the stored value instead of dropping it.
        sensitive = {"token", "password", "key", "secret", "api_key", "secret_id"}
        for field in sensitive:
            if field not in cred_data and field in existing.get("value", {}):
                cred_data[field] = existing["value"][field]

    # Ownership: stamp the creator on first save; preserve it on updates so the
    # original owner is never overwritten by a later editor.
    _principal = principal_from_request(request, body.tenant_id)
    _ident = getattr(_principal, "email", None) or getattr(_principal, "user_id", None) or "unknown"
    _meta = dict(cred_data.get("metadata") or {})
    _prev_meta = (existing or {}).get("metadata") or {}
    _meta["created_by"] = _prev_meta.get("created_by") or _ident
    cred_data["metadata"] = _meta

    ok = backend.set(name, cred_data)
    if not ok:
        raise HTTPException(status_code=500, detail="Failed to save credential")
    meta = backend.get_metadata(name)
    return {"saved": True, "credential": meta}


@router.delete("/api/credentials/{name}")
async def delete_credential(request: Request, name: str, tenant_id: str = "company", user: dict = Depends(require_permission("skills.author"))):
    """Delete a credential from the tenant store. Requires the developer
    'skills.author' capability, and is further restricted to its creator or an admin."""
    # Validate the requested tenant against the caller's allowed_tenants before
    # touching the backend (require_permission checks the role, not the tenant).
    bind_request_identity(request, tenant_id)
    config_dir = _credential_config_dir(tenant_id)
    cred_path = config_dir / "credentials.yaml"
    if not cred_path.exists():
        raise HTTPException(status_code=404, detail=f"Credential '{name}' not found")
    from agent_os.credential_store import FernetFileBackend
    backend = FernetFileBackend(cred_path)
    existing = backend.get(name)
    if not existing:
        raise HTTPException(status_code=404, detail=f"Credential '{name}' not found")
    _require_credential_owner_or_admin(
        request, tenant_id, (existing.get("metadata") or {}).get("created_by")
    )
    ok = backend.delete(name)
    if not ok:
        raise HTTPException(status_code=404, detail=f"Credential '{name}' not found")
    return {"deleted": True, "name": name}
