"""External access registry helpers for AgentPro.

The registry is intentionally dependency-light so both Studio and the kernel can
use it without importing FastAPI or the Studio security package.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from fnmatch import fnmatch
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import yaml


DEFAULT_REGISTRY = {"version": "1.0", "resources": []}


@dataclass(frozen=True)
class ExternalResource:
    id: str
    label: str = ""
    type: str = "http"
    hosts: tuple[str, ...] = ()
    paths: tuple[str, ...] = ()
    methods: tuple[str, ...] = ()
    databases: tuple[str, ...] = ()
    name: str = ""                          # short handle for named (non-file) db resources
    backend: str = ""                       # "postgres" | "sqlite" | "" (file/sqlite default)
    schema: str = ""                        # Postgres schema; "self" = the agent's own kn_ schema
    allowed_tables: tuple[str, ...] = ()    # table allow-list (defense-in-depth)
    read_only: bool = False                 # refuse writes regardless of the skill's sql_mode
    credentials: tuple[str, ...] = ()
    mcp_connections: tuple[str, ...] = ()
    context_files: tuple[str, ...] = ()
    tools: tuple[str, ...] = ()
    risk: str = ""
    owners: tuple[str, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def resource_type(self) -> str:
        return self.id.split(":", 1)[0] if ":" in self.id else "external"

    @property
    def resource_id(self) -> str:
        return self.id.split(":", 1)[1] if ":" in self.id else self.id


def registry_path(tenant_root: Path) -> Path:
    return Path(tenant_root) / "security" / "external_access.yaml"


def _as_list(value: Any) -> list:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def _as_tuple(value: Any) -> tuple[str, ...]:
    return tuple(str(item) for item in _as_list(value) if str(item).strip())


def parse_external_access_yaml(raw: str) -> tuple[dict, list[str]]:
    try:
        parsed = yaml.safe_load(raw) or {}
    except Exception as exc:
        return {}, [f"YAML parse error: {exc}"]
    if not isinstance(parsed, dict):
        return {}, ["External access registry must be a YAML mapping"]
    return parsed, []


def validate_external_access_doc(doc: dict) -> dict:
    errors: list[str] = []
    warnings: list[str] = []
    resources = doc.get("resources", [])
    if resources is None:
        resources = []
    if not isinstance(resources, list):
        return {"valid": False, "errors": ["resources must be a list"], "warnings": warnings, "resource_count": 0}

    seen: set[str] = set()
    for idx, item in enumerate(resources):
        prefix = f"resources[{idx}]"
        if not isinstance(item, dict):
            errors.append(f"{prefix} must be a mapping")
            continue
        resource_id = str(item.get("id", "")).strip()
        if not resource_id:
            errors.append(f"{prefix}.id is required")
        elif resource_id in seen:
            errors.append(f"{prefix}.id duplicates '{resource_id}'")
        else:
            seen.add(resource_id)
        if resource_id and not resource_id.startswith("external:"):
            errors.append(f"{prefix}.id must start with external:")
        resource_type = str(item.get("type", "") or "http")
        if resource_type not in {"http", "db", "mcp", "cloud", "sharepoint", "other"}:
            warnings.append(f"{prefix}.type '{resource_type}' is not a standard type")
        for list_field in ("hosts", "paths", "methods", "databases", "allowed_tables", "credentials", "mcp_connections", "context_files", "tools", "owners"):
            if list_field in item and not isinstance(item[list_field], list):
                errors.append(f"{prefix}.{list_field} must be a list")
        # An http resource with no `hosts` would match every host.
        if resource_type == "http" and not (item.get("hosts") or []):
            errors.append(
                f"{prefix}.hosts is required for http resources "
                f"(an empty list matches every host and defeats the allowlist)"
            )
    return {
        "valid": not errors,
        "errors": errors,
        "warnings": warnings,
        "resource_count": len(resources),
    }


def validate_external_access_yaml(raw: str) -> dict:
    parsed, errors = parse_external_access_yaml(raw)
    if errors:
        return {"valid": False, "errors": errors, "warnings": [], "resource_count": 0, "parsed": parsed}
    result = validate_external_access_doc(parsed)
    result["parsed"] = parsed
    return result


def load_external_access_doc(tenant_root: Path) -> dict:
    path = registry_path(tenant_root)
    if not path.exists():
        return DEFAULT_REGISTRY.copy()
    parsed, errors = parse_external_access_yaml(path.read_text(encoding="utf-8"))
    if errors:
        return DEFAULT_REGISTRY.copy()
    return parsed


def _to_resource(item: dict) -> ExternalResource:
    return ExternalResource(
        id=str(item.get("id", "")).strip(),
        label=str(item.get("label", "") or ""),
        type=str(item.get("type", "") or "http"),
        hosts=_as_tuple(item.get("hosts")),
        paths=_as_tuple(item.get("paths")),
        methods=tuple(str(m).upper() for m in _as_list(item.get("methods")) if str(m).strip()),
        databases=_as_tuple(item.get("databases")),
        name=str(item.get("name", "") or ""),
        backend=str(item.get("backend", "") or "").lower(),
        schema=str(item.get("schema", "") or ""),
        allowed_tables=_as_tuple(item.get("allowed_tables")),
        read_only=bool(item.get("read_only", False)),
        credentials=_as_tuple(item.get("credentials")),
        mcp_connections=_as_tuple(item.get("mcp_connections")),
        context_files=_as_tuple(item.get("context_files")),
        tools=_as_tuple(item.get("tools")),
        risk=str(item.get("risk", "") or ""),
        owners=_as_tuple(item.get("owners")),
        metadata={k: v for k, v in item.items() if k not in {
            "id", "label", "type", "hosts", "paths", "methods", "databases",
            "name", "backend", "schema", "allowed_tables", "read_only",
            "credentials", "mcp_connections", "context_files", "tools", "risk", "owners",
        }},
    )


def list_external_resources(tenant_root: Path) -> list[ExternalResource]:
    doc = load_external_access_doc(tenant_root)
    return [_to_resource(item) for item in doc.get("resources", []) or [] if isinstance(item, dict) and item.get("id")]


def resources_for_credential(tenant_root: Path, credential_name: str) -> list[ExternalResource]:
    wanted = credential_name.lower()
    return [
        resource for resource in list_external_resources(tenant_root)
        if any(cred.lower() == wanted for cred in resource.credentials)
    ]


def resources_for_mcp(tenant_root: Path, connection_name: str) -> list[ExternalResource]:
    wanted = connection_name.lower()
    return [
        resource for resource in list_external_resources(tenant_root)
        if any(conn.lower() == wanted for conn in resource.mcp_connections)
    ]


def resource_for_database(tenant_root: Path, database: str) -> ExternalResource | None:
    dbstr = str(database).strip()
    db_name = Path(dbstr).name
    candidates = [dbstr, db_name]
    for resource in list_external_resources(tenant_root):
        if resource.type != "db":
            continue
        if dbstr and (dbstr == resource.name or dbstr == resource.resource_id):
            return resource
        for pattern in resource.databases:
            if any(fnmatch(candidate, pattern) for candidate in candidates):
                return resource
    return None


def match_http_resource(tenant_root: Path, url: str, method: str = "GET") -> ExternalResource | None:
    parsed = urlparse(url)
    if not parsed.scheme or not parsed.netloc:
        return None
    host = parsed.netloc.lower()
    path = parsed.path or "/"
    method = method.upper()
    for resource in list_external_resources(tenant_root):
        if resource.type != "http":
            continue
        if resource.methods and method not in resource.methods and "*" not in resource.methods:
            continue
        # Empty hosts must match nothing (fail closed).
        host_match = bool(resource.hosts) and any(fnmatch(host, pattern.lower()) for pattern in resource.hosts)
        path_match = not resource.paths or any(fnmatch(path, pattern) for pattern in resource.paths)
        if host_match and path_match:
            return resource
    return None
