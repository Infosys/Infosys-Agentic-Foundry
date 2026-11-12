"""Taxonomy graph import service.

Orchestrates: registered connection -> credential -> adapter -> snapshot -> taxonomy
draft (+ skill suggestions). It never writes a taxonomy file: the caller commits a
reviewed draft through the existing ``/taxonomy-import`` path so indexing,
Enterprise_Context registration and permission checks stay in one place.

Connections are the tenant's ``external_access.yaml`` resources with ``type: graph``
-- the same registry that already allowlists hosts and names credentials for skills.
One entry can therefore serve both jobs:

* taxonomy import (this module, an adapter reads the hierarchy), and
* runtime use by a skill (``mcp_connections`` on the same entry names the MCP server
  the skill declares in its SKILL.md).
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

import httpx

from agent_os.external_access import ExternalResource, list_external_resources
from agentos_contracts.graph_source import (
    DIRECTION_IN,
    DIRECTION_OUT,
    FileGraphQuery,
    GraphSourceAdapter,
    HierarchyQuery,
)

from .graphify_adapter import MODES, GraphifyAdapter
from .mapper import fit_import_payload, map_snapshot, sanitize_text
from .neo4j_adapter import Neo4jAdapter
from .neptune_adapter import NeptuneAdapter
from .safety import (
    GraphImportError,
    check_endpoint,
    clamp_int,
    split_host_port,
    validate_identifier,
)
from .suggest import suggest_skills

logger = logging.getLogger(__name__)

CONSUMER = "taxonomy_graph_import"      # scope name a credential must list to be used here
CredentialLookup = Callable[[str], Optional[Any]]   # name -> object with a ``.value`` dict


@dataclass(frozen=True)
class GraphConnection:
    id: str
    label: str
    engine: str
    host: str
    database: str
    auth: str
    credential: str
    scheme: str
    region: str
    mcp_connections: tuple
    risk: str
    path: str = ""            # graphify engine only: /shared/graphs/<name>/graph.json

    def public(self) -> Dict[str, Any]:
        """Safe for API responses: no host, no credential name, no secrets (skill authors
        pick a connection by label; they are not necessarily infra admins)."""
        return {
            "id": self.id,
            "label": self.label or self.id,
            "engine": self.engine,
            "auth": self.auth,
            "has_credential": bool(self.credential),
            "mcp_connections": list(self.mcp_connections),
            "risk": self.risk,
        }


def _to_connection(r: ExternalResource) -> Optional[GraphConnection]:
    if r.type != "graph":
        return None
    md = r.metadata or {}
    engine = str(md.get("engine", "")).lower()
    if engine == "graphify":
        # File engine: no host, no credential -- a graph.json under the tenant's shared/graphs.
        path = str(md.get("path", "") or "")
        if not path:
            return None
        return GraphConnection(
            id=r.id, label=r.label, engine=engine, host="", database="", auth="none",
            credential="", scheme="", region="", mcp_connections=tuple(r.mcp_connections),
            risk=r.risk, path=path,
        )
    if engine not in ("neo4j", "neptune") or len(r.hosts) != 1:
        return None
    default_auth = "basic" if engine == "neo4j" else "sigv4"
    return GraphConnection(
        id=r.id,
        label=r.label,
        engine=engine,
        host=r.hosts[0],
        database=str(md.get("database", "") or "neo4j"),
        auth=str(md.get("auth", "") or default_auth).lower(),
        credential=r.credentials[0] if r.credentials else "",
        scheme=str(md.get("scheme", "") or "https").lower(),
        region=str(md.get("region", "") or ""),
        mcp_connections=tuple(r.mcp_connections),
        risk=r.risk,
    )


def list_connections(tenant_root: Path) -> List[GraphConnection]:
    out = [c for c in (_to_connection(r) for r in list_external_resources(tenant_root)) if c]
    return sorted(out, key=lambda c: c.id)


def get_connection(tenant_root: Path, connection_id: str) -> GraphConnection:
    wanted = (connection_id or "").strip()
    for c in list_connections(tenant_root):
        if wanted in (c.id, c.id.split(":", 1)[-1]):
            return c
    raise GraphImportError("unknown_connection", "No such graph connection is registered", status=404)


def build_adapter(
    conn: GraphConnection,
    credential_lookup: CredentialLookup,
    *,
    client: Optional[httpx.Client] = None,
) -> GraphSourceAdapter:
    if conn.scheme not in ("https", "http"):
        raise GraphImportError("bad_scheme", "Connection scheme must be https or http", status=500)
    default_port = 443 if conn.scheme == "https" else 80
    host, port = split_host_port(conn.host, default_port)
    addrs = check_endpoint(conn.scheme, host, port)
    if conn.scheme == "http" and not all(a.is_loopback or a.is_private for a in addrs):
        # Credentials would cross the network in clear text to a non-private host.
        raise GraphImportError("insecure_scheme", "Plain http is only allowed for private or loopback hosts", status=400)
    base = f"{conn.scheme}://{conn.host}"

    cred_value: Dict[str, Any] = {}
    if conn.auth != "none":
        if not conn.credential:
            raise GraphImportError("missing_credentials", "This connection has no credential configured", status=500)
        cred = credential_lookup(conn.credential)
        if cred is None:
            raise GraphImportError(
                "credential_unavailable",
                f"Credential could not be resolved; it must exist and list '{CONSUMER}' in its scope",
                status=502,
            )
        cred_value = dict(getattr(cred, "value", None) or {})

    if conn.engine == "neo4j":
        if conn.auth != "basic":
            raise GraphImportError("bad_auth", "Neo4j connections use auth: basic", status=500)
        return Neo4jAdapter(
            base, conn.database,
            str(cred_value.get("username", "")), str(cred_value.get("password", "")),
            client=client,
        )
    if conn.engine == "neptune":
        return NeptuneAdapter(
            base,
            auth=conn.auth,
            region=conn.region,
            access_key_id=str(cred_value.get("access_key_id", "")),
            secret_access_key=str(cred_value.get("secret_access_key", "")),
            session_token=str(cred_value.get("session_token", "")),
            client=client,
        )
    raise GraphImportError("bad_engine", "Unsupported graph engine", status=500)


def build_query(params: Dict[str, Any]) -> HierarchyQuery:
    root_name = str(params.get("root_name") or "").strip()
    if not root_name or len(root_name) > 200:
        raise GraphImportError("bad_root", "Root name is required (max 200 characters)")
    direction = str(params.get("direction") or DIRECTION_OUT).lower()
    if direction not in (DIRECTION_OUT, DIRECTION_IN):
        raise GraphImportError("bad_direction", "Direction must be 'out' or 'in'")
    desc = str(params.get("description_property") or "").strip()
    return HierarchyQuery(
        root_label=validate_identifier(params.get("root_label"), "Root label"),
        root_name=root_name,
        edge_type=validate_identifier(params.get("edge_type"), "Relationship type"),
        direction=direction,
        name_property=validate_identifier(params.get("name_property") or "name", "Name property"),
        description_property=validate_identifier(desc, "Description property") if desc else "",
        max_depth=clamp_int(params.get("max_depth"), 1, 8, 5),
        max_nodes=clamp_int(params.get("max_nodes"), 10, 5000, 2000),
    )


_GRAPH_VPATH = re.compile(r"^/shared/graphs/[A-Za-z0-9_.\-]+(/[A-Za-z0-9_.\-]+)*\.json$")


def resolve_graph_path(tenant_root: Path, virtual_path: str) -> Path:
    """Map a registered ``/shared/graphs/.../graph.json`` to a real file, confined to
    ``<tenant>/shared/graphs`` (CWE-22): the virtual path is pattern-checked, then the
    resolved path (symlinks followed) must still sit under that folder."""
    if not _GRAPH_VPATH.match(virtual_path or "") or ".." in virtual_path.split("/"):
        raise GraphImportError("bad_graph_path", "Connection graph path is misconfigured", status=500)
    shared = (Path(tenant_root) / "shared").resolve()
    graphs = (shared / "graphs").resolve()
    real = (shared / virtual_path[len("/shared/"):]).resolve()
    if not real.is_relative_to(graphs) or not real.is_file():
        raise GraphImportError("graph_not_found", "The graph file was not found", status=404)
    return real


def build_file_query(params: Dict[str, Any]) -> FileGraphQuery:
    mode = str(params.get("mode") or "community").lower()
    if mode not in MODES:
        raise GraphImportError("bad_mode", "Mode must be 'community' or 'path'")
    return FileGraphQuery(
        mode=mode,
        path_prefix=str(params.get("path_prefix") or "").strip(),
        domain_depth=clamp_int(params.get("domain_depth"), 1, 6, 2),
        min_size=clamp_int(params.get("min_size"), 1, 10_000, 3),
        max_domains=clamp_int(params.get("max_domains"), 1, 200, 40),
        max_nodes=clamp_int(params.get("max_nodes"), 10, 5000, 5000),
    )


def preview_taxonomy(
    tenant_root: Path,
    *,
    connection_id: str,
    params: Dict[str, Any],
    credential_lookup: CredentialLookup,
    skills_index: Dict[str, Dict[str, Any]],
    client: Optional[httpx.Client] = None,
) -> Dict[str, Any]:
    """Fetch + map + suggest. Read-only; writes nothing."""
    conn = get_connection(tenant_root, connection_id)
    if conn.engine == "graphify":
        return _preview_graphify(tenant_root, conn, params, skills_index)
    query = build_query(params)
    adapter = build_adapter(conn, credential_lookup, client=client)
    snap = adapter.fetch_hierarchy(query)
    snap.source = {"connection": conn.id, "engine": conn.engine}
    return _finish_preview(conn, snap, params, skills_index,
                           echo={"root_label": query.root_label, "root_name": query.root_name,
                                 "edge_type": query.edge_type, "direction": query.direction,
                                 "max_depth": query.max_depth},
                           source_root=f"{query.root_label}:{query.root_name}")


def _preview_graphify(tenant_root: Path, conn: GraphConnection, params: Dict[str, Any],
                      skills_index: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
    fq = build_file_query(params)
    adapter = GraphifyAdapter(resolve_graph_path(tenant_root, conn.path))
    root_name = sanitize_text(params.get("taxonomy_name") or conn.label or "Codebase graph", 120, yaml_safe=True)
    snap = adapter.fetch_snapshot(fq, root_name=root_name or "Codebase graph")
    snap.source = {"connection": conn.id, "engine": conn.engine}
    return _finish_preview(conn, snap, params, skills_index,
                           echo={"mode": fq.mode, "path_prefix": fq.path_prefix,
                                 "domain_depth": fq.domain_depth, "max_domains": fq.max_domains},
                           source_root=f"{fq.mode}:{fq.path_prefix or 'all'}")


def _finish_preview(conn: GraphConnection, snap, params: Dict[str, Any],
                    skills_index: Dict[str, Dict[str, Any]], *, echo: Dict[str, Any],
                    source_root: str) -> Dict[str, Any]:
    draft = map_snapshot(
        snap,
        taxonomy_name=str(params.get("taxonomy_name") or ""),
        description=str(params.get("description") or ""),
    )
    fit_import_payload(draft)      # a draft the import endpoint would reject is trimmed here, with a loss entry
    suggest_skills(draft.domains, skills_index)

    out = draft.to_dict()
    out["connection"] = conn.public()
    out["query"] = echo
    # Echoed back by the UI on commit and written to the file's frontmatter.
    out["provenance"] = {
        "source_connection": conn.id,
        "source_engine": conn.engine,
        "source_root": sanitize_text(source_root, 120, yaml_safe=True),
        "imported_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    out["unmapped_sections"] = sum(1 for d in draft.domains for s in d["sections"] if not s["skill"])
    return out


def audit(tenant_root: Path, *, tenant_id: str, user_id: str, action: str,
          connection_id: str, ok: bool, detail: str = "") -> None:
    """Append to the same external-access audit stream the kernel uses."""
    try:
        path = Path(tenant_root) / "shared" / "databases" / "external_access_audit.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "tenant_id": tenant_id,
            "agent_id": "studio",
            "user_id": user_id,
            "skill": CONSUMER,
            "action": action,
            "resource": connection_id,
            "allowed": ok,
            "reason": detail[:200],
            "command_preview": "",
            "metadata": {},
        }
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, default=str) + "\n")
        from agent_os.audit_log import emit_audit
        emit_audit("external_access", entry)
    except Exception as exc:   # audit must never break the request
        logger.debug("graph import audit skipped: %s", exc)
