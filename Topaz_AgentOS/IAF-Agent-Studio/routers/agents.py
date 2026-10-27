"""
IAF Agent Studio — Agent Management API Router

CRUD for agent configurations and tools listing.
"""

import asyncio
import logging
import shutil
from datetime import datetime, timezone

import yaml

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

import copy
import re

from auth.middleware import require_admin, require_auth, require_permission
from security.dependencies import enforce_entitlement, principal_from_request, bind_request_identity
from shared.config import SERVER_DIR, DATA_ROOT
from shared.file_utils import atomic_write_yaml, locked_rmw_yaml
from shared.hooks_validation import validate_hooks_doc
from shared.models import AgentConfig
from shared.state import (
    state,
    capability_registry,
    trace_emitter,
    twin_emitter,
    queue_manager,
    cron_scheduler,
    approval_store,
)
from iaf_agent_skills.hook_runner import (
    HookRunner,
    ALLOWED_HOOK_EVENTS,
    ALLOWED_HOOK_MODES,
    ALLOWED_FAIL_POLICIES,
    HOOK_EVENT_CATALOGUE,
    MAX_HOOK_OUTPUT_CHARS,
)

logger = logging.getLogger(__name__)

router = APIRouter()

_SENSITIVE_AUTH_KEYS = re.compile(
    r"(token|secret|password|api[_-]?key|auth[_-]?key|private[_-]?key|credential)",
    re.IGNORECASE,
)


def _mask_mcp_connections(connections: list) -> list:
    """Return a copy of MCP connection list with auth credentials redacted."""
    if not connections:
        return connections
    masked = []
    for conn in connections:
        conn = copy.deepcopy(conn)
        # Redact auth sub-object
        auth = conn.get("auth") if isinstance(conn, dict) else None
        if isinstance(auth, dict):
            for k in list(auth.keys()):
                if _SENSITIVE_AUTH_KEYS.search(k):
                    auth[k] = "[REDACTED]"
        # Redact sensitive keys in headers dict
        headers = conn.get("headers") if isinstance(conn, dict) else None
        if isinstance(headers, dict):
            for k in list(headers.keys()):
                if _SENSITIVE_AUTH_KEYS.search(k) or k.lower() in ("authorization", "x-api-key"):
                    headers[k] = "[REDACTED]"
        # Redact top-level env/key fields
        if isinstance(conn, dict):
            for k in list(conn.keys()):
                if k not in ("name", "url", "transport", "auth", "headers", "env") and _SENSITIVE_AUTH_KEYS.search(k):
                    conn[k] = "[REDACTED]"
        masked.append(conn)
    return masked


@router.get("/api/agents")
async def list_agents(
    request: Request,
    tenant_id: str | None = None,
    q: str | None = None,
    user: dict = Depends(require_auth),
):
    """List all agents for a tenant, optionally filtered by a search term.

    `q` matches case-insensitively against the same three fields the Agents page
    used to filter locally — id, display name and description — so moving the
    search server-side does not quietly narrow what is searchable. A blank or
    whitespace-only term is treated as no filter.
    """
    tenant = user.get("tenant_id") or tenant_id or "company"
    agents_path = SERVER_DIR / DATA_ROOT / "tenants" / tenant / "agents"

    if not agents_path.exists():
        return {"agents": []}

    def _scan_agents():
        agents = []
        for agent_dir in agents_path.iterdir():
            if not agent_dir.is_dir() or agent_dir.name.startswith('.'):
                continue

            config_file = agent_dir / "config.yaml"
            if config_file.exists():
                try:
                    config = yaml.safe_load(config_file.read_text(encoding='utf-8'))
                    agents.append({
                        "id": agent_dir.name,
                        "name": config.get("agent", {}).get("name", agent_dir.name),
                        "description": config.get("agent", {}).get("description", ""),
                        "skills_mode": config.get("skills", {}).get("mode", "all"),
                        "skills_list": config.get("skills", {}).get("allowed", []) or config.get("skills", {}).get("denied", []),
                        "tools_allowed": config.get("tools", {}).get("allowed", ["fs", "shell", "write_file", "run_sql_query"]),
                        "mcp_connections": _mask_mcp_connections(config.get("mcp", {}).get("connections", [])),
                        "hooks": config.get("hooks", {}),
                    })
                except Exception as e:
                    agents.append({
                        "id": agent_dir.name,
                        "name": agent_dir.name,
                        "error": str(e),
                    })
            else:
                # Agent without config - default settings
                agents.append({
                    "id": agent_dir.name,
                    "name": agent_dir.name,
                    "description": "No configuration",
                    "skills_mode": "all",
                    "skills_list": [],
                    "tools_allowed": ["fs", "shell", "write_file", "run_sql_query"],
                })
        return agents

    agents = await asyncio.to_thread(_scan_agents)

    term = (q or "").strip().lower()
    if term:
        agents = [
            a for a in agents
            if term in str(a.get("id", "")).lower()
            or term in str(a.get("name", "")).lower()
            or term in str(a.get("description", "")).lower()
        ]
    return {"agents": agents}


@router.get("/api/agents/{agent_id}")
async def get_agent(agent_id: str, tenant_id: str = "company", user: dict = Depends(require_auth)):
    """Get agent details."""
    agent_path = SERVER_DIR / DATA_ROOT / "tenants" / tenant_id / "agents" / agent_id

    if not agent_path.exists():
        raise HTTPException(404, f"Agent '{agent_id}' not found")

    is_admin = user.get("role") == "admin"
    config_file = agent_path / "config.yaml"
    if config_file.exists():
        config = yaml.safe_load(config_file.read_text(encoding='utf-8'))
        resp: dict = {
            "id": agent_id,
            "name": config.get("agent", {}).get("name", agent_id),
            "description": config.get("agent", {}).get("description", ""),
            "skills_mode": config.get("skills", {}).get("mode", "all"),
            "skills_list": config.get("skills", {}).get("allowed", []) or config.get("skills", {}).get("denied", []),
            "tools_allowed": config.get("tools", {}).get("allowed", ["fs", "shell", "write_file", "run_sql_query"]),
            # auth tokens in MCP connections are masked; admins see raw_config
            "mcp_connections": _mask_mcp_connections(config.get("mcp", {}).get("connections", [])),
            "hooks": config.get("hooks", {}),
        }
        if is_admin:
            resp["raw_config"] = config
        return resp
    else:
        return {
            "id": agent_id,
            "name": agent_id,
            "description": "No configuration",
            "skills_mode": "all",
            "skills_list": [],
            "tools_allowed": ["fs", "shell", "write_file", "run_sql_query"],
        }


@router.post("/api/agents")
async def create_agent(request: Request, config: AgentConfig, tenant_id: str = "company", admin: dict = Depends(require_permission("agents.author"))):
    """Create a new agent."""
    agent_id = config.name.lower().replace(" ", "_").replace("-", "_")
    agent_id = ''.join(c for c in agent_id if c.isalnum() or c == '_')
    # Bind the requested tenant to the caller's allowed_tenants before writing,
    # so a developer authorized in one tenant cannot target another via ?tenant_id=.
    principal, tenant_id, _agent, _user = bind_request_identity(request, tenant_id)
    enforce_entitlement(principal, "manage", "agent", agent_id)

    agents_path = SERVER_DIR / DATA_ROOT / "tenants" / tenant_id / "agents"
    agent_path = agents_path / agent_id

    if agent_path.exists():
        raise HTTPException(400, f"Agent '{agent_id}' already exists")

    agent_path.mkdir(parents=True, exist_ok=True)
    (agent_path / "memory").mkdir(exist_ok=True)
    (agent_path / "memory" / "context_graph").mkdir(exist_ok=True)
    (agent_path / "memory" / "history").mkdir(exist_ok=True)
    (agent_path / ".audit").mkdir(exist_ok=True)
    (agent_path / "workspace").mkdir(exist_ok=True)
    (agent_path / "teams").mkdir(exist_ok=True)
    (agent_path / "users").mkdir(exist_ok=True)

    yaml_config = {
        "agent": {
            "name": config.name,
            "description": config.description,
            "version": "1.0",
        },
        "skills": {
            "mode": config.skills_mode,
        },
        "tools": {
            "allowed": config.tools_allowed,
        },
        "audit": {
            "log_queries": True,
            "log_responses": True,
            "log_tool_calls": True,
        },
    }

    if config.skills_mode == "allowlist":
        yaml_config["skills"]["allowed"] = config.skills_list
    elif config.skills_mode == "denylist":
        yaml_config["skills"]["denied"] = config.skills_list

    if config.mcp_connections:
        yaml_config["mcp"] = {"connections": config.mcp_connections}

    # Hooks are authored via PUT /api/agents/{id}/config/hooks; any `hooks` in this payload is ignored.

    config_file = agent_path / "config.yaml"
    atomic_write_yaml(config_file, yaml_config)

    return {"message": f"Created agent '{config.name}'", "agent_id": agent_id, "path": str(agent_path)}


@router.put("/api/agents/{agent_id}")
async def update_agent(request: Request, agent_id: str, config: AgentConfig, tenant_id: str = "company", admin: dict = Depends(require_permission("agents.author"))):
    """Update agent configuration."""
    _require_safe_agent_id(agent_id)
    principal, tenant_id, _agent, _user = bind_request_identity(request, tenant_id)
    enforce_entitlement(principal, "manage", "agent", agent_id)
    agent_path = SERVER_DIR / DATA_ROOT / "tenants" / tenant_id / "agents" / agent_id

    if not agent_path.exists():
        raise HTTPException(404, f"Agent '{agent_id}' not found")

    yaml_config = {
        "agent": {
            "name": config.name,
            "description": config.description,
            "version": "1.0",
        },
        "skills": {
            "mode": config.skills_mode,
        },
        "tools": {
            "allowed": config.tools_allowed,
        },
        "audit": {
            "log_queries": True,
            "log_responses": True,
            "log_tool_calls": True,
        },
    }

    if config.skills_mode == "allowlist":
        yaml_config["skills"]["allowed"] = config.skills_list
    elif config.skills_mode == "denylist":
        yaml_config["skills"]["denied"] = config.skills_list

    if config.mcp_connections:
        yaml_config["mcp"] = {"connections": config.mcp_connections}

    # Hooks are authored via PUT /api/agents/{id}/config/hooks; any `hooks` in this payload is ignored.

    config_file = agent_path / "config.yaml"
    # Carry over the `hooks:` and `mcp:` sections so this endpoint cannot wipe them.
    if config_file.exists():
        try:
            _existing = yaml.safe_load(config_file.read_text(encoding="utf-8")) or {}
            if _existing.get("hooks"):
                yaml_config["hooks"] = _existing["hooks"]
            if not config.mcp_connections and _existing.get("mcp"):
                yaml_config["mcp"] = _existing["mcp"]
        except Exception as _exc:  # pragma: no cover - defensive
            logger.warning("Could not read existing config to preserve hooks/mcp for %s: %s", agent_id, _exc)
    atomic_write_yaml(config_file, yaml_config)

    # Evict every cached instance (templates, kernels, session clones); keep open-session history.
    state.evict_agent(agent_id, preserve_sessions=True)

    return {"message": f"Updated agent '{agent_id}'", "agent_id": agent_id}


HOOKS_AUDIT_CATEGORY = "agent_config_change"


class HooksDocRequest(BaseModel):
    """A TENANT `hooks:` document — {event: [entry,...]}.

    `tenant_hooks` is the canonical field; `hooks` is accepted as a back-compat alias.
    Platform hooks are never accepted here — they live in the framework manifest.
    """
    tenant_hooks: dict | None = None
    hooks: dict = {}

    def doc(self) -> dict:
        return self.tenant_hooks if self.tenant_hooks is not None else (self.hooks or {})


# Manifest-only metadata that must never be persisted into a tenant config.yaml entry.
_PLATFORM_ONLY_FIELDS = ("applies_to", "source")


def _require_safe_agent_id(agent_id: str) -> None:
    """Reject path separators / traversal in an agent id taken straight from the
    URL before it is used to build a filesystem path. The create route derives
    and sanitises its own id, but update/delete accept the raw path parameter."""
    if not agent_id or not all(c.isalnum() or c in "_-" for c in agent_id):
        raise HTTPException(400, f"Invalid agent id '{agent_id}'")


def _agent_dir(tenant_id: str, agent_id: str):
    return SERVER_DIR / DATA_ROOT / "tenants" / tenant_id / "agents" / agent_id


def _sanitize_tenant_hooks(doc: dict) -> dict:
    """Force tenant ownership and strip platform-only fields so the UI/API can't
    smuggle `owner: platform`/`applies_to`/`source` into tenant config.yaml."""
    clean: dict = {}
    for event, entries in (doc or {}).items():
        if not isinstance(entries, list):
            continue
        out = []
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            e2 = {k: v for k, v in entry.items() if k not in _PLATFORM_ONLY_FIELDS}
            e2.pop("owner", None)  # never let a tenant claim platform ownership
            out.append(e2)
        clean[event] = out
    return clean


def _shared_hook_scripts(tenant_id: str) -> list[dict]:
    """Tenant-owned hook scripts under shared/hooks/ — suggested command paths for the UI."""
    hooks_dir = SERVER_DIR / DATA_ROOT / "tenants" / tenant_id / "shared" / "hooks"
    if not hooks_dir.is_dir():
        return []
    scripts: list[dict] = []
    for path in sorted(hooks_dir.iterdir()):
        if not path.is_file() or path.suffix not in {".py", ".sh"}:
            continue
        if path.name.startswith("_"):
            continue  # private helper modules (leading underscore), not hooks
        runner = "python3" if path.suffix == ".py" else "bash"
        scripts.append({
            "name": path.name,
            "command": f"{runner} $IAF_AGENT_ROOT/../../shared/hooks/{path.name}",
        })
    return scripts


def _platform_hooks_view(agent_id: str, tenant_id: str) -> list:
    """Read-only view of the platform hooks that apply to this agent (for UI display)."""
    from iaf_agent_skills.platform_hooks import applicable_platform_hooks
    view = []
    for e in applicable_platform_hooks(agent_id, tenant_id):
        view.append({
            "hook_id": e.get("hook_id"),
            "event": e.get("event"),
            "command": e.get("command"),
            "matcher": e.get("matcher", ".*"),
            "owner": "platform",
            "block_on_nonzero": bool(e.get("block_on_nonzero", False)),
            "timeout_seconds": e.get("timeout_seconds", 10),
            "applies_to": e.get("applies_to", {"scope": "all"}),
            "source": "platform-manifest",
        })
    return view


@router.get("/api/agents/{agent_id}/config/hooks")
async def get_agent_hooks(
    request: Request, agent_id: str, tenant_id: str = "company", admin: dict = Depends(require_admin)
):
    """Return the agent's `hooks:` section plus the metadata the UI needs
    (allowed events/modes/fail-policies, kill-switch state, current validation)."""
    enforce_entitlement(principal_from_request(request, tenant_id), "manage", "agent", agent_id)
    agent_path = _agent_dir(tenant_id, agent_id)
    if not agent_path.exists():
        raise HTTPException(404, f"Agent '{agent_id}' not found")

    tenant_hooks: dict = {}
    config_file = agent_path / "config.yaml"
    if config_file.exists():
        cfg = yaml.safe_load(config_file.read_text(encoding="utf-8")) or {}
        tenant_hooks = cfg.get("hooks", {}) or {}

    return {
        "agent_id": agent_id,
        "tenant_hooks": tenant_hooks,                          # editable (config.yaml)
        "platform_hooks": _platform_hooks_view(agent_id, tenant_id),  # read-only (framework manifest)
        "shared_hook_scripts": _shared_hook_scripts(tenant_id),       # tenant shared/hooks/*.py|sh
        "hooks": tenant_hooks,                                 # deprecated alias = tenant only
        "allowed_events": sorted(ALLOWED_HOOK_EVENTS),
        "event_catalogue": HOOK_EVENT_CATALOGUE,
        "allowed_modes": sorted(ALLOWED_HOOK_MODES),
        "allowed_fail_policies": sorted(ALLOWED_FAIL_POLICIES),
        "max_output_chars": MAX_HOOK_OUTPUT_CHARS,
        "capability_hooks_enabled": HookRunner.capability_hooks_enabled(),
        "validation": validate_hooks_doc(tenant_hooks),
    }


@router.post("/api/agents/{agent_id}/config/hooks/validate")
async def validate_agent_hooks(
    request: Request,
    agent_id: str,
    body: HooksDocRequest,
    tenant_id: str = "company",
    admin: dict = Depends(require_admin),
):
    """Validate a tenant hooks document without writing it."""
    enforce_entitlement(principal_from_request(request, tenant_id), "manage", "agent", agent_id)
    return validate_hooks_doc(body.doc())


@router.put("/api/agents/{agent_id}/config/hooks")
async def save_agent_hooks(
    request: Request,
    agent_id: str,
    body: HooksDocRequest,
    tenant_id: str = "company",
    admin: dict = Depends(require_admin),
):
    """Validate then persist ONLY the `hooks:` subtree of config.yaml (preserving
    every other section), evict the cached agent so it reloads, and audit the change."""
    enforce_entitlement(principal_from_request(request, tenant_id), "manage", "agent", agent_id)
    agent_path = _agent_dir(tenant_id, agent_id)
    if not agent_path.exists():
        raise HTTPException(404, f"Agent '{agent_id}' not found")

    doc = body.doc()
    result = validate_hooks_doc(doc)
    if not result["valid"]:
        raise HTTPException(400, detail={"errors": result["errors"], "warnings": result["warnings"]})

    # Reject tenant entries that reuse a reserved platform hook_id.
    from iaf_agent_skills.platform_hooks import platform_hook_ids
    reserved = platform_hook_ids()
    collisions = [
        e.get("hook_id")
        for entries in doc.values() if isinstance(entries, list)
        for e in entries if isinstance(e, dict) and e.get("hook_id") in reserved
    ]
    if collisions:
        raise HTTPException(400, detail={"errors": [
            f"'{c}' is a reserved platform hook id and cannot be used by a tenant hook"
            for c in collisions
        ]})

    # Force tenant ownership + strip platform-only fields before persisting.
    hooks = _sanitize_tenant_hooks(doc)

    # Read-merge-write: replace only the `hooks` key; drop it entirely when empty.
    def _merge(cfg: dict) -> dict:
        cfg = cfg or {}
        if hooks:
            cfg["hooks"] = hooks
        else:
            cfg.pop("hooks", None)
        return cfg

    config_file = agent_path / "config.yaml"
    await locked_rmw_yaml(config_file, _merge)

    # Evict every cached instance so open sessions reload config; keep session history.
    evicted_count = state.evict_agent(agent_id, preserve_sessions=True)

    # Audit (best-effort; never block the save). Do NOT log full command bodies.
    try:
        from shared.audit_evidence_sinks import get_audit_sink_fanout

        get_audit_sink_fanout().write(
            {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "tenant_id": tenant_id,
                "user_id": admin.get("user_id", ""),
                "email": admin.get("email", ""),
                "role": admin.get("role", ""),
                "action": "update",
                "resource": f"agent:{agent_id}",
                "section": "hooks",
                "scope": "tenant",
                "hook_count": result["hook_count"],
                "events": sorted(hooks.keys()),
                "warnings": result["warnings"],
                "evicted_agents": evicted_count,
            },
            tenant_id=tenant_id,
            category=HOOKS_AUDIT_CATEGORY,
        )
    except Exception as exc:  # noqa: BLE001 — audit failure must not break the save
        logger.warning("hooks save audit failed for agent %s: %s", agent_id, exc)

    return {
        "message": f"Saved hooks for agent '{agent_id}'",
        "agent_id": agent_id,
        "tenant_hooks": hooks,
        "hooks": hooks,  # deprecated alias = tenant only
        "validation": result,
        "capability_hooks_enabled": HookRunner.capability_hooks_enabled(),
        "evicted": evicted_count,
    }


@router.delete("/api/agents/{agent_id}")
async def delete_agent(request: Request, agent_id: str, tenant_id: str = "company", admin: dict = Depends(require_admin)):
    """Delete an agent (careful - removes all data!). Admin-only: deletion wipes the
    whole agent directory and there is no per-agent owner to scope it to a developer."""
    _require_safe_agent_id(agent_id)
    principal, tenant_id, _agent, _user = bind_request_identity(request, tenant_id)
    enforce_entitlement(principal, "manage", "agent", agent_id)
    if agent_id in ["enterprise_agent", "studio_agent"]:
        raise HTTPException(400, f"Cannot delete protected agent '{agent_id}'")

    agent_path = SERVER_DIR / DATA_ROOT / "tenants" / tenant_id / "agents" / agent_id

    if not agent_path.exists():
        raise HTTPException(404, f"Agent '{agent_id}' not found")

    # Evict template, kernels and live session clones.
    state.evict_agent(agent_id)

    shutil.rmtree(agent_path)

    return {"message": f"Deleted agent '{agent_id}'"}


@router.get("/api/agents/{agent_id}/connectors/health")
async def get_agent_connector_health(agent_id: str, tenant_id: str = "company", user: dict = Depends(require_auth)):
    """Validate configured MCP connector definitions without launching them."""
    from iaf_agent_skills.tools.mcp_bridge import validate_connection

    agent_path = SERVER_DIR / DATA_ROOT / "tenants" / tenant_id / "agents" / agent_id
    if not agent_path.exists():
        raise HTTPException(404, f"Agent '{agent_id}' not found")

    config_file = agent_path / "config.yaml"
    if not config_file.exists():
        return {"agent_id": agent_id, "status": "not_configured", "connectors": []}

    config = yaml.safe_load(config_file.read_text(encoding="utf-8")) or {}
    connections = config.get("mcp", {}).get("connections", []) or []
    if not connections:
        return {"agent_id": agent_id, "status": "not_configured", "connectors": []}

    connector_results = []
    for idx, conn in enumerate(connections):
        errors = validate_connection(conn)
        connector_results.append({
            "index": idx,
            "name": conn.get("name") or f"connection_{idx + 1}",
            "type": conn.get("type", ""),
            "transport": conn.get("transport", ""),
            "status": "valid_config" if not errors else "invalid_config",
            "errors": errors,
        })

    overall = "valid_config" if all(item["status"] == "valid_config" for item in connector_results) else "invalid_config"
    return {"agent_id": agent_id, "status": overall, "connectors": connector_results}


@router.get("/api/agents/{agent_id}/tool-execution/snapshot")
async def get_agent_tool_execution_snapshot(
    agent_id: str,
    tenant_id: str = "company",
    user_id: str = "",
    limit: int = 50,
    user: dict = Depends(require_auth),
):
    """Return a bounded read-only snapshot of an agent's passive tool observations."""
    if limit < 0:
        raise HTTPException(400, "limit must be non-negative")
    bounded_limit = min(int(limit), 500)
    effective_user_id = str((user or {}).get("sub") or (user or {}).get("id") or user_id or "")
    user_role = str((user or {}).get("role") or "user")
    agent = state.get_or_create(tenant_id, agent_id, effective_user_id, user_role=user_role)

    if hasattr(agent, "get_tool_execution_snapshot"):
        snapshot = agent.get_tool_execution_snapshot(limit=bounded_limit)
    else:
        observer = getattr(agent, "tool_execution_capability", None)
        events = observer.snapshot(limit=bounded_limit) if observer and hasattr(observer, "snapshot") else []
        snapshot = {
            "events": events,
            "count": len(events),
            "dropped_count": getattr(observer, "dropped_count", 0) if observer else 0,
        }

    events = list(snapshot.get("events", [])) if isinstance(snapshot, dict) else []
    return {
        "tenant_id": tenant_id,
        "agent_id": agent_id,
        "user_id": effective_user_id,
        "limit": bounded_limit,
        "count": int(snapshot.get("count", len(events))) if isinstance(snapshot, dict) else len(events),
        "dropped_count": int(snapshot.get("dropped_count", 0)) if isinstance(snapshot, dict) else 0,
        "events": events,
    }


@router.get("/api/capabilities/snapshot")
async def get_capability_registry_snapshot(
    tenant_id: str = "company",
    include_tenant_overrides: bool = True,
    user: dict = Depends(require_auth),
):
    """Return redacted capability registry metadata and dependency health."""
    dependency_valid = True
    dependency_error = None
    try:
        capability_registry.validate_dependencies()
    except Exception as exc:
        dependency_valid = False
        dependency_error = str(exc)

    capabilities = capability_registry.snapshot()
    tenant_overrides = capability_registry.tenant_snapshot(tenant_id) if include_tenant_overrides else []
    return {
        "tenant_id": tenant_id,
        "count": len(capabilities),
        "capabilities": capabilities,
        "tenant_override_count": len(tenant_overrides),
        "tenant_overrides": tenant_overrides,
        "dependency_valid": dependency_valid,
        "dependency_error": dependency_error,
    }


def _build_capability_parity_report(registry, runtime_objects: dict) -> dict:
    checks = []
    drift_count = 0
    for item in registry.snapshot():
        name = item.get("name", "")
        status = "metadata_only"
        expected = item.get("implementation") or "registered"
        actual = "not_checked"

        if name == "model_provider":
            status = "ok"
            actual = expected
        elif name in runtime_objects:
            expected_present = bool(item.get("enabled", True))
            actual_present = runtime_objects.get(name) is not None
            if expected_present == actual_present:
                status = "ok"
            else:
                status = "drift"
                drift_count += 1
            expected = "present" if expected_present else "absent"
            actual = "present" if actual_present else "absent"

        checks.append({
            "name": name,
            "status": status,
            "expected": expected,
            "actual": actual,
            "implementation": item.get("implementation"),
            "enabled": item.get("enabled", True),
        })

    return {
        "status": "drift" if drift_count else "ok",
        "capability_count": len(checks),
        "check_count": len(checks),
        "drift_count": drift_count,
        "checks": checks,
    }


@router.get("/api/capabilities/parity")
async def get_capability_parity_report(user: dict = Depends(require_auth)):
    """Compare registry metadata with live runtime singletons where possible."""
    runtime_objects = {
        "trace_emitter": trace_emitter,
        "twin_emitter": twin_emitter,
        "execution_router": {"queue_manager": queue_manager, "cron_scheduler": cron_scheduler},
        "approval_store": approval_store,
    }
    return _build_capability_parity_report(capability_registry, runtime_objects)


@router.get("/api/tools")
async def list_tools():
    """List all available tools that can be assigned to agents."""
    tools = [
        {"id": "shell", "name": "Shell", "description": "File system access (ls, cat, echo, mkdir, rm, grep, etc.)", "category": "core"},
        {"id": "write_file", "name": "Write File", "description": "Direct file writing without shell escaping issues", "category": "core"},
        {"id": "run_sql_query", "name": "SQL Query", "description": "Execute SQL queries on databases — routes by the connection's engine (SQLite file, or SQL Server / PostgreSQL / MySQL / Oracle via a Connection defined in the Connections tab)", "category": "core"},
        {"id": "invoke_skill", "name": "Invoke Skill", "description": "Call another skill from within this skill. Enables multi-skill composition and delegation.", "category": "core"},
        {"id": "query_memory", "name": "Query Memory", "description": "Search this agent's conversation history and memory store for past context.", "category": "core"},
        {"id": "request_human_approval", "name": "Admin Approval → Command Center", "description": "Routes to the Command Center board for an admin/approver to review and decide (async, survives restart). Use for governed, high-value, or irreversible actions — payments, deletions, spend.", "category": "governance", "scope": "skill"},
        {"id": "pause_in_chat", "name": "In-Chat Approval (user decides)", "description": "Pauses in the chat and shows the skill's own output (tables/summary) with Approve/Reject buttons; the user in the conversation decides inline. For low-risk, visibility-first gates — not real writes (those stay on Admin Approval).", "category": "governance", "scope": "skill"},
    ]
    return {"tools": tools}
