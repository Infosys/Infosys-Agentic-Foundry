"""
Mission Mode — auto-source items from external systems.

A workstream's ``items_source`` config tells the engine where to fetch
items from on each cron tick. The engine calls ``resolve(source, ctx)``
which dispatches to one of four resolvers:

    sql         — SQLite under enterprise_root/tenants/<id>/shared/databases/
    http        — GET/POST against a URL; parses JSON, optional jq filter
    directory   — scan a filesystem path on a glob pattern
    skill       — delegate to a worker skill that returns a JSON list

Each resolver returns a list of item dicts. Required keys per item:

    id           — stable unique identifier
    description  — short human-readable task

Optional:

    priority_metric, acceptance_criteria, metadata, …

The engine then merges these into the workstream YAML according to
``refresh_strategy`` (append_new / replace_all / merge).
"""

from __future__ import annotations

import json
import logging
import re
import sqlite3
try:
    from .sqlite_util import connect as _sqlite_connect
except ImportError:
    from sqlite_util import connect as _sqlite_connect
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)


class SourceBlocked(ValueError):
    """http items_source target or credential use refused by egress policy."""



def resolve(
    source: dict,
    *,
    tenant_root: Path,
    tenant_id: str,
    agent=None,
) -> list[dict]:
    """
    Dispatch to the right resolver. Returns a list of item dicts.

    Raises ValueError for unknown source types or malformed configs;
    resolver-specific failures are logged and return [].
    """
    if not isinstance(source, dict):
        raise ValueError("items_source must be a dict")
    stype = source.get("type")
    if not stype:
        raise ValueError("items_source.type is required")

    if stype == "sql":
        rows = _resolve_sql(source, tenant_root=tenant_root, tenant_id=tenant_id)
    elif stype == "http":
        rows = _resolve_http(source, tenant_root=tenant_root, tenant_id=tenant_id)
    elif stype == "directory":
        rows = _resolve_directory(source, tenant_root=tenant_root, tenant_id=tenant_id)
    elif stype == "skill":
        rows = _resolve_skill(source, agent=agent)
    else:
        raise ValueError(f"items_source.type {stype!r} not supported")

    template = source.get("item_template")
    if template and isinstance(template, dict) and rows:
        rows = [_apply_template(r, template) for r in rows]
        rows = [r for r in rows if r]
    # Always normalize at the end so resolvers can return raw source rows
    return [n for n in (_normalize_item(r) for r in rows) if n]


def merge_items(existing: list[dict], new: list[dict], strategy: str) -> tuple[list[dict], int, int]:
    """
    Apply the refresh strategy. Returns (merged_items, n_appended, n_updated).

    Strategies:
      append_new  — append items whose id isn't already in `existing`
      replace_all — DESTRUCTIVE: drop all existing items; use only `new`
      merge       — for each new item, update fields on the matching existing
                    item (preserving status/attempts/trace); append if new
    """
    existing_by_id = {it.get("id"): it for it in existing if it.get("id")}
    appended, updated = 0, 0

    if strategy == "replace_all":
        # Caller is responsible for understanding this nukes in-flight work.
        return list(new), len(new), 0

    if strategy == "append_new":
        out = list(existing)
        for it in new:
            iid = it.get("id")
            if not iid or iid in existing_by_id:
                continue
            out.append(it)
            appended += 1
        return out, appended, 0

    # strategy == "merge"
    out = list(existing)
    for it in new:
        iid = it.get("id")
        if not iid:
            continue
        if iid in existing_by_id:
            target = existing_by_id[iid]
            # Update description + acceptance_criteria + priority_metric.
            # NEVER touch status/attempts/trace/resolution/escalated_approval_id.
            for k in ("description", "acceptance_criteria", "priority_metric", "metadata"):
                if k in it and it.get(k) is not None:
                    target[k] = it[k]
            updated += 1
        else:
            out.append(it)
            appended += 1
    return out, appended, updated



def _resolve_sql(source: dict, *, tenant_root: Path, tenant_id: str) -> list[dict]:
    """
    Run a SELECT against a SQLite database in the tenant's shared/databases/.

    Required keys: database (no .db suffix), query (SELECT only).
    The query MUST return at least an `id` column and a `description` column
    (or columns named `item_id` / `task`); aliased via ``SELECT … AS id``.
    """
    db_name = source.get("database", "").strip()
    query = (source.get("query") or "").strip()
    if not db_name or not query:
        return []

    # Security: only allow single SELECT statements (no writes, no stacking)
    normalized = query.lower().lstrip()
    if not normalized.startswith("select"):
        logger.warning("items_source[sql]: rejecting non-SELECT query")
        return []
    # Block statement stacking / write attempts smuggled after a SELECT
    if ";" in query:
        logger.warning("items_source[sql]: rejecting multi-statement query")
        return []
    _DANGEROUS_KEYWORDS = ("insert ", "update ", "delete ", "drop ", "alter ", "create ", "attach ", "detach ")
    if any(kw in normalized for kw in _DANGEROUS_KEYWORDS):
        logger.warning("items_source[sql]: rejecting query with write/DDL keywords")
        return []

    db_path = tenant_root / "shared" / "databases" / f"{db_name}.db"
    if not db_path.exists():
        logger.warning("items_source[sql]: db not found %s", db_path)
        return []

    try:
        conn = _sqlite_connect(db_path, row_factory=sqlite3.Row)
        # Open in read-only mode to prevent any writes via crafted SQL
        conn.execute("PRAGMA query_only = ON")
        _SAFE_SQL_RE = re.compile(r'^\s*(SELECT|PRAGMA)\s', re.IGNORECASE)
        if not _SAFE_SQL_RE.match(query):
            raise ValueError("Only SELECT queries are permitted")
        cur = conn.execute(query)
        rows = [dict(r) for r in cur.fetchall()]
        conn.close()
    except Exception as exc:
        logger.warning("items_source[sql] query failed: %s", exc)
        return []

    return rows



def _resolve_http(source: dict, *, tenant_root: Path, tenant_id: str) -> list[dict]:
    """
    Fetch items from an HTTP endpoint. Expects JSON response.

    Required: url. Optional: method (GET), headers (dict),
    credential (named entry in credentials.yaml — value used as X-API-Key),
    items_path (dotted path into the JSON to find the items array, e.g.
    "data.invoices"; default = use the response root if it's a list).
    """
    url = source.get("url", "").strip()
    if not url:
        return []
    method = (source.get("method") or "GET").upper()
    headers = dict(source.get("headers") or {})

    import ipaddress
    from urllib.parse import urljoin, urlparse
    from agent_os.egress_ssrf import SSRFBlocked, assert_safe_url
    from agent_os.external_access import match_http_resource

    def _vet(target: str):
        resource = match_http_resource(tenant_root, target, method)
        try:
            return resource, assert_safe_url(target, allow_loopback=bool(resource))
        except SSRFBlocked as exc:
            logger.warning("items_source[http]: blocked by egress policy: %s", exc)
            raise SourceBlocked("blocked by egress policy") from exc

    resource, addrs = _vet(url)

    # Credential only goes to https hosts of an external-access resource that lists it
    cred_name = source.get("credential")
    if cred_name:
        bound = bool(resource) and any(str(c).lower() == str(cred_name).lower() for c in resource.credentials)
        loopback = all(ipaddress.ip_address(a).is_loopback for a in addrs)
        if not bound or not (urlparse(url).scheme.lower() == "https" or loopback):
            logger.warning("items_source[http]: credential %r refused for this URL", cred_name)
            raise SourceBlocked("credential not permitted for this URL")
        try:
            from agent_os.credential_store import get_credential as _get_cred  # type: ignore
            cred = _get_cred(cred_name, consumer="mission_mode", purpose="items_source.http",
                             config_dir=tenant_root / "shared" / "config")
            if cred and getattr(cred, "key", None):
                headers.setdefault("X-API-Key", cred.key)
            elif cred and getattr(cred, "token", None):
                headers.setdefault("Authorization", f"Bearer {cred.token}")
        except Exception as exc:
            logger.debug("items_source[http]: credential lookup failed: %s", exc)

    try:
        import requests
        body = source.get("body")
        target = url
        for _hop in range(4):
            if method == "GET":
                r = requests.get(target, headers=headers, timeout=15, allow_redirects=False)
            else:
                r = requests.request(method, target, json=body, headers=headers, timeout=15, allow_redirects=False)
            if not (r.is_redirect or r.is_permanent_redirect):
                break
            # Revalidate each hop and never forward the credential to it
            target = urljoin(target, r.headers.get("Location", ""))
            _vet(target)
            headers = {k: v for k, v in headers.items() if k.lower() not in ("x-api-key", "authorization")}
        else:
            raise SourceBlocked("too many redirects")
        r.raise_for_status()
        data = r.json()
    except SourceBlocked:
        raise
    except Exception as exc:
        logger.warning("items_source[http] request failed: %s", exc)
        return []

    # Navigate items_path
    items_path = source.get("items_path", "").strip()
    if items_path:
        for part in items_path.split("."):
            if not isinstance(data, dict):
                logger.warning("items_source[http]: items_path %r drilled into non-dict", items_path)
                return []
            data = data.get(part)
            if data is None:
                return []
    if not isinstance(data, list):
        logger.warning("items_source[http]: response (after items_path=%r) is not a list", items_path)
        return []
    return [r for r in data if isinstance(r, dict)]



def _resolve_directory(source: dict, *, tenant_root: Path, tenant_id: str) -> list[dict]:
    """
    Scan a directory under enterprise_root for files matching a glob.

    Required: path (under tenant_root for safety),
              pattern (glob, e.g. ``*.pdf``).
    Optional: id_template (default ``{stem}``), description_template
              (default ``Review {filename}``).
    """
    path = source.get("path", "").strip()
    pattern = source.get("pattern", "*").strip() or "*"
    if not path:
        return []

    # Sandbox: only allow paths under tenant_root (use resolved absolute paths
    # so the prefix check works regardless of whether tenant_root was given as relative)
    tenant_root_abs = Path(tenant_root).resolve()
    rel = path.lstrip("/")
    scan_root = (tenant_root_abs / rel).resolve()
    if not str(scan_root).startswith(str(tenant_root_abs)):
        logger.warning("items_source[directory]: %s is outside tenant_root — refusing", scan_root)
        return []
    if not scan_root.exists():
        logger.warning("items_source[directory]: %s does not exist", scan_root)
        return []

    id_template = source.get("id_template", "{stem}")
    desc_template = source.get("description_template", "Review {filename}")

    items: list[dict] = []
    for f in sorted(scan_root.glob(pattern)):
        if not f.is_file():
            continue
        ctx = {
            "filename": f.name,
            "stem": f.stem,
            "path": str(f.resolve().relative_to(tenant_root_abs)),
            "size": f.stat().st_size,
            "ext": f.suffix.lstrip("."),
        }
        try:
            iid = id_template.format(**ctx)
            desc = desc_template.format(**ctx)
        except KeyError as exc:
            logger.warning("items_source[directory]: template key missing: %s", exc)
            continue
        items.append(_normalize_item({"id": iid, "description": desc, "metadata": ctx}))
    return [it for it in items if it]



def _resolve_skill(source: dict, *, agent=None) -> list[dict]:
    """
    Delegate to a worker skill that returns a JSON list of items.

    The skill is called via agent.run() with the configured query.
    The response is expected to contain a JSON array — we look for one
    using a tolerant regex (handles ```json fenced blocks too).
    """
    if agent is None:
        logger.warning("items_source[skill]: no agent provided — cannot delegate")
        return []
    skill_name = source.get("skill", "").strip()
    query = source.get("query", "list items").strip()
    if not skill_name:
        return []
    try:
        result = agent.run(query=query, skill_name=skill_name, return_tool_calls=False)
        text = result if isinstance(result, str) else (result[0] if isinstance(result, tuple) else "")
    except Exception as exc:
        logger.warning("items_source[skill]: agent.run failed: %s", exc)
        return []

    # Try to extract a JSON list from the response
    import re as _re
    match = _re.search(r"```(?:json)?\s*(\[.*?\])\s*```", text, _re.DOTALL)
    if match:
        text = match.group(1)
    try:
        data = json.loads(text)
    except Exception:
        # Try to find a bare JSON array
        match = _re.search(r"(\[[\s\S]*\])", text)
        if not match:
            logger.warning("items_source[skill]: no JSON array found in response")
            return []
        try:
            data = json.loads(match.group(1))
        except Exception as exc:
            logger.warning("items_source[skill]: JSON parse failed: %s", exc)
            return []
    if not isinstance(data, list):
        logger.warning("items_source[skill]: parsed data is not a list")
        return []
    return [r for r in data if isinstance(r, dict)]



def _apply_template(row: dict, template: dict) -> dict:
    """
    Map raw source fields to workstream item schema using a user-provided
    template. Each template value is either:
      - a string with {field} placeholders → resolved via str.format(**row)
      - a bare string matching a row key → that field's value is copied

    Example template:
      {id: invoice_id,
       description: "Resolve {invoice_id} ({amount_eur} EUR)",
       priority_metric: amount_eur}
    """
    out: dict = {}
    for target_key, tmpl in template.items():
        if not isinstance(tmpl, str):
            out[target_key] = tmpl
            continue
        if "{" in tmpl:
            try:
                out[target_key] = tmpl.format(**row)
            except (KeyError, IndexError) as exc:
                logger.debug("item_template: format failed for %s: %s", target_key, exc)
                out[target_key] = ""
        elif tmpl in row:
            out[target_key] = row[tmpl]
        else:
            out[target_key] = tmpl  # treat as literal
    return out


def _normalize_item(row: Any) -> Optional[dict]:
    """
    Map a raw row (from any source) to the workstream item schema.

    Accepted id aliases: id, item_id, key, invoice_id, account_id,
                          ticket_id, vendor_id, customer_id, doc_id, uid
    Accepted description aliases: description, task, summary, title,
                                   reason, note, exception_code
    """
    if not isinstance(row, dict):
        return None
    iid = (row.get("id") or row.get("item_id") or row.get("key")
           or row.get("invoice_id") or row.get("account_id") or row.get("ticket_id")
           or row.get("vendor_id") or row.get("customer_id") or row.get("doc_id")
           or row.get("uid"))
    desc = (row.get("description") or row.get("task") or row.get("summary")
            or row.get("title") or row.get("reason") or row.get("note"))
    # Fallback: synthesize a description from common business fields
    if not desc and iid:
        bits = []
        for k in ("invoice_id", "amount_eur", "amount", "vendor_id", "vendor",
                  "exception_code", "status", "due_date"):
            if k in row and row[k] not in (None, ""):
                bits.append(f"{k}={row[k]}")
        if bits:
            desc = "; ".join(bits)
    if not iid or not desc:
        return None
    out: dict = {
        "id": str(iid),
        "description": str(desc),
    }
    pm = row.get("priority_metric") or row.get("amount_eur") or row.get("amount")
    if pm is not None:
        try:
            out["priority_metric"] = float(pm)
        except (TypeError, ValueError):
            pass
    if "acceptance_criteria" in row and isinstance(row["acceptance_criteria"], list):
        out["acceptance_criteria"] = [str(c) for c in row["acceptance_criteria"]]
    if "metadata" in row and isinstance(row["metadata"], dict):
        out["metadata"] = row["metadata"]
    for key in ("case_summary", "case_insights", "metadata"):
        parsed = _coerce_json_object(row.get(key))
        if parsed:
            out[key] = parsed
    criteria = _coerce_json_list(row.get("acceptance_criteria"))
    if criteria:
        out["acceptance_criteria"] = [str(c) for c in criteria]
    return out


def _coerce_json_object(value: Any) -> Optional[dict]:
    if isinstance(value, dict):
        return value
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = json.loads(value)
    except Exception:
        return None
    return parsed if isinstance(parsed, dict) else None


def _coerce_json_list(value: Any) -> Optional[list]:
    if isinstance(value, list):
        return value
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = json.loads(value)
    except Exception:
        return None
    return parsed if isinstance(parsed, list) else None
