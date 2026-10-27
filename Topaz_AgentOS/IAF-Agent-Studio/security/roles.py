"""Role → permission projection for RBAC UI gating and role management.

Enforcement of *access* stays in the entitlement engine (``policies.yaml`` via
``security.provider.get_entitlement_provider``). This module is the
**role → permission** source of truth used to:

  * show / hide UI features per signed-in user (``permissions`` on ``/auth/me``),
  * validate which roles an admin may assign, and
  * support dynamic role definitions (add / edit roles at runtime).

Roles are stored per tenant in ``<DATA_ROOT>/tenants/<tenant>/security/roles.yaml``.
When that file is absent, built-in defaults are used so behaviour stays sane.

Keep the permission keys granted here aligned with the allow-rules authored in
the same tenant's ``policies.yaml`` so the UI projection matches real
enforcement.
"""
from __future__ import annotations

import os
import tempfile
from pathlib import Path
from typing import Any, Iterable

import yaml

WILDCARD = "*"

# Permission catalog: key -> {label, category}; key is checked against /auth/me permissions.
PERMISSION_CATALOG: dict[str, dict[str, str]] = {
    "agents.use":       {"label": "Use agents",             "category": "Agents"},
    "agents.author":    {"label": "Create & edit agents",   "category": "Agents"},
    "skills.use":       {"label": "Use skills",             "category": "Skills"},
    "skills.author":    {"label": "Create & edit skills",   "category": "Skills"},
    "skills.publish":   {"label": "Publish / review skills", "category": "Skills"},
    "tools.dev":        {"label": "Developer tools (SQL/MCP)", "category": "Tools"},
    "knowledge.write":  {"label": "Edit knowledge & memory", "category": "Knowledge"},
    "evals.run":        {"label": "Run evaluations",        "category": "Quality"},
    "providers.manage": {"label": "Manage LLM providers",   "category": "Admin"},
    "security.manage":  {"label": "Manage security policies", "category": "Admin"},
    "schedules.manage": {"label": "Manage schedules / cron", "category": "Admin"},
    "users.manage":     {"label": "Manage users & roles",   "category": "Admin"},
}

# Built-in defaults used when a tenant has no roles.yaml.
_DEFAULT_ROLES: dict[str, dict[str, Any]] = {
    "user": {
        "name": "User",
        "description": "Consume agents and skills.",
        "permissions": ["agents.use", "skills.use"],
    },
    "developer": {
        "name": "Developer",
        "description": "Build and test skills, agents, and tools.",
        "permissions": [
            "agents.use", "skills.use", "skills.author", "agents.author",
            "tools.dev", "knowledge.write", "evals.run",
        ],
    },
    "admin": {
        "name": "Administrator",
        "description": "Full control plane.",
        "permissions": [WILDCARD],
    },
}


def _roles_file(tenant_id: str) -> Path:
    """Resolve the tenant roles.yaml path from server config."""
    try:
        from shared.config import SERVER_DIR, DATA_ROOT
        base = Path(SERVER_DIR) / DATA_ROOT
    except Exception:
        base = Path("enterprise_root")
    return base / "tenants" / (tenant_id or "company") / "security" / "roles.yaml"


def load_role_registry(tenant_id: str = "company") -> dict[str, dict[str, Any]]:
    """Return ``{role_id: {name, description, permissions[]}}`` for the tenant."""
    path = _roles_file(tenant_id)
    if not path.exists():
        return {k: dict(v) for k, v in _DEFAULT_ROLES.items()}
    try:
        doc = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except Exception:
        return {k: dict(v) for k, v in _DEFAULT_ROLES.items()}

    registry: dict[str, dict[str, Any]] = {}
    for role in doc.get("roles", []) or []:
        if not isinstance(role, dict):
            continue
        rid = str(role.get("id") or "").strip().lower()
        if not rid:
            continue
        perms = [str(p) for p in (role.get("permissions") or []) if p]
        registry[rid] = {
            "name": role.get("name") or rid.title(),
            "description": role.get("description") or "",
            "permissions": perms,
        }
    # The two structural roles must always resolve.
    registry.setdefault("admin", dict(_DEFAULT_ROLES["admin"]))
    registry.setdefault("user", dict(_DEFAULT_ROLES["user"]))
    return registry


def known_roles(tenant_id: str = "company") -> list[str]:
    """Sorted list of role ids defined for the tenant."""
    return sorted(load_role_registry(tenant_id).keys())


def _expand(keys: Iterable[str]) -> list[str]:
    """Expand a permission-key list, resolving ``*`` to the full catalog."""
    keys = list(keys)
    if WILDCARD in keys:
        return list(PERMISSION_CATALOG.keys())
    ordered: dict[str, None] = {}
    for k in keys:
        if k in PERMISSION_CATALOG:
            ordered[k] = None
    return list(ordered.keys())


def effective_permissions(
    role: str,
    groups: Iterable[str] | None = None,
    tenant_id: str = "company",
) -> list[str]:
    """Compute the permission keys granted to ``role`` (plus any group grants).

    Group grants are optional: a role entry with id ``group:<name>`` in
    roles.yaml contributes its permissions to members of that group.
    """
    registry = load_role_registry(tenant_id)
    role_key = (role or "user").strip().lower()
    entry = registry.get(role_key) or registry.get("user") or {}
    keys: list[str] = list(entry.get("permissions") or [])
    for g in (groups or []):
        gk = f"group:{str(g).strip().lower()}"
        g_entry = registry.get(gk)
        if g_entry:
            keys.extend(g_entry.get("permissions") or [])
    return _expand(keys)


def catalog() -> list[dict[str, str]]:
    """Return the full permission catalog as a list for UI rendering."""
    return [{"key": k, **v} for k, v in PERMISSION_CATALOG.items()]


# Enforcement mapping: permission key -> entitlement grants compiled into role allow-rules.
PERMISSION_ENFORCEMENT: dict[str, list[dict[str, list[str]]]] = {
    "agents.use": [
        {"actions": ["access", "call", "use", "read", "test"], "resources": ["agent:*"]},
    ],
    "agents.author": [
        {"actions": ["access", "call", "use", "read", "write", "test", "manage", "delete"],
         "resources": ["agent:*"]},
    ],
    "skills.use": [
        {"actions": ["access", "use", "read", "test"], "resources": ["skill:*"]},
        # Baseline-allow toolset for skill-users; a deny rule in policies.yaml restricts it (deny wins).
        {"actions": ["use", "call"],
         "resources": ["tool:shell", "tool:write_file", "tool:run_sql_query",
                       "tool:query_memory", "tool:invoke_skill", "tool:invoke_plan",
                       "tool:create_plan", "tool:request_human_approval"]},
        # Reading grounding context is intrinsic to running a skill; file-mode agents hard-raise if denied.
        {"actions": ["read", "use"], "resources": ["context:*"]},
    ],
    "skills.author": [
        {"actions": ["access", "call", "use", "read", "write", "test", "submit", "promote", "manage", "delete"],
         "resources": ["skill:*"]},
    ],
    "skills.publish": [
        {"actions": ["promote", "submit", "manage"], "resources": ["skill:*"]},
    ],
    "tools.dev": [
        {"actions": ["use", "call"],
         "resources": ["tool:shell", "tool:query_memory", "tool:run_sql_query",
                       "tool:request_human_approval", "mcp:*", "external:platform.ap_tools_mcp"]},
    ],
    "knowledge.write": [
        {"actions": ["read", "write", "use"],
         "resources": ["knowledge:*", "memory:*", "context:*", "workstream:*", "file:*"]},
    ],
    "evals.run": [
        {"actions": ["use", "read", "write"],
         "resources": ["eval:*", "rl_capture:*", "trace_value:*"]},
    ],
    "providers.manage": [
        {"actions": ["manage", "use", "read"], "resources": ["model:*", "llm_provider:*"]},
    ],
    "security.manage": [
        {"actions": ["manage", "read", "write"], "resources": ["security:*"]},
    ],
    "schedules.manage": [
        {"actions": ["manage", "use", "read"], "resources": ["cron:*", "schedule:*"]},
    ],
    "users.manage": [
        {"actions": ["manage", "read", "write"], "resources": ["user:*"]},
    ],
}


def compile_role_policies(tenant_id: str = "company") -> list[dict[str, Any]]:
    """Synthesize entitlement allow-rules for every defined role from its permissions.

    Every role gets a built-in baseline so that an empty, missing, or incomplete
    ``policies.yaml`` can never lock a role out (the old behaviour skipped
    ``admin``/``user`` entirely, so an empty policy file left them fully denied
    under fail-closed enforcement):

      * ``admin`` receives a hard wildcard allow (``*`` on ``*``) that does not
        depend on the tenant file, so admins can never be accidentally bricked.
      * ``user`` and every other role are compiled from their permission keys via
        PERMISSION_ENFORCEMENT (e.g. ``skills.use`` -> read/use on ``skill:*``).

    These are all ``allow`` rules. Tenants layer restrictions on top in
    ``policies.yaml``: because ``deny`` wins over ``allow`` in the evaluator
    (see YamlEntitlementProvider.can), an explicit ``deny`` rule overrides any
    baseline grant here — including admin's — so full tunability is preserved.
    """
    registry = load_role_registry(tenant_id)
    compiled: list[dict[str, Any]] = []

    # Built-in admin baseline: complete access, independent of policies.yaml.
    # Restrict admins, if ever needed, with explicit deny rules (deny wins).
    if "admin" in registry:
        compiled.append({
            "id": "role-auto:admin:full",
            "effect": "allow",
            "roles": ["admin"],
            "actions": ["*"],
            "resources": ["*"],
            "reason": "Built-in admin baseline (full access; override with explicit deny rules).",
        })

    for rid, meta in registry.items():
        if rid == "admin":
            continue  # covered by the explicit wildcard baseline above
        perms = _expand(meta.get("permissions") or [])
        for pk in perms:
            for gi, grant in enumerate(PERMISSION_ENFORCEMENT.get(pk, [])):
                # group:<name> must compile to a groups selector; a roles selector would never match.
                is_group = rid.startswith("group:")
                compiled.append({
                    "id": f"role-auto:{rid}:{pk}:{gi}",
                    "effect": "allow",
                    "roles": [] if is_group else [rid],
                    "groups": [rid[len("group:"):]] if is_group else [],
                    "actions": list(grant.get("actions") or []),
                    "resources": list(grant.get("resources") or []),
                    "reason": f"Auto-compiled from role '{rid}' permission '{pk}'.",
                })
    return compiled




def _write_registry(tenant_id: str, registry: dict[str, dict[str, Any]]) -> None:
    path = _roles_file(tenant_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    doc = {
        "version": "1.0",
        "description": f"Role → permission definitions for tenant '{tenant_id}'.",
        "roles": [
            {
                "id": rid,
                "name": meta.get("name") or rid.title(),
                "description": meta.get("description") or "",
                "permissions": list(meta.get("permissions") or []),
            }
            for rid, meta in registry.items()
        ],
    }
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            yaml.safe_dump(doc, fh, sort_keys=False, default_flow_style=False)
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def upsert_role(
    role_id: str,
    permissions: list[str],
    name: str = "",
    description: str = "",
    tenant_id: str = "company",
) -> dict[str, Any]:
    """Create or update a role definition. Unknown permission keys are rejected."""
    rid = (role_id or "").strip().lower()
    if not rid or not rid.replace("-", "").replace("_", "").isalnum():
        raise ValueError("role id must be alphanumeric (dashes/underscores allowed)")
    # admin is the fixed wildcard role; do not persist an edited copy.
    if rid == "admin":
        raise ValueError("cannot modify the built-in 'admin' role")
    bad = [p for p in permissions if p != WILDCARD and p not in PERMISSION_CATALOG]
    if bad:
        raise ValueError(f"unknown permission keys: {', '.join(sorted(bad))}")
    registry = load_role_registry(tenant_id)
    registry[rid] = {
        "name": name or rid.title(),
        "description": description,
        "permissions": list(dict.fromkeys(permissions)),
    }
    _write_registry(tenant_id, registry)
    return {"id": rid, **registry[rid]}


def delete_role(role_id: str, tenant_id: str = "company") -> None:
    """Remove a role definition. The structural roles cannot be deleted."""
    rid = (role_id or "").strip().lower()
    if rid in ("user", "admin"):
        raise ValueError("cannot delete the built-in 'user' or 'admin' role")
    registry = load_role_registry(tenant_id)
    if rid not in registry:
        raise ValueError(f"role '{rid}' not found")
    del registry[rid]
    _write_registry(tenant_id, registry)
