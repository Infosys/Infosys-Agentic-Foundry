"""Neo4j adapter -- Query API v2 over HTTPS (Neo4j 5.19+ and Aura).

Uses the HTTP Query API rather than the Bolt driver so no new dependency is added
to the Fortify/CVE surface (httpx is already pinned). Statements are sent with
``accessMode: READ``; the query shapes themselves are fixed MATCH/RETURN templates.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

import httpx

from .cypher_base import CypherHierarchyAdapter
from .http_util import map_status, new_client, parse_json, post_capped
from .safety import GraphImportError, validate_database_name


class Neo4jAdapter(CypherHierarchyAdapter):
    engine = "neo4j"
    id_function = "elementId"

    def __init__(
        self,
        base_url: str,
        database: str,
        username: str,
        password: str,
        *,
        client: Optional[httpx.Client] = None,
    ) -> None:
        self._base = base_url.rstrip("/")
        self._database = validate_database_name(database or "neo4j")
        self._auth = (username, password)
        self._client = client or new_client()

    def _run(self, statement: str, params: Dict[str, Any]) -> List[Dict[str, Any]]:
        status, body = post_capped(
            self._client,
            f"{self._base}/db/{self._database}/query/v2",
            json={"statement": statement, "parameters": params, "accessMode": "READ"},
            auth=self._auth,
            headers={"Accept": "application/json", "Content-Type": "application/json"},
        )
        # Neo4j returns 202 for a successful Query API call; 2xx are all fine.
        doc = parse_json(body) if body else {}
        map_status(status, doc)
        # The Query API can answer 202 and still report a failed query (or a failure
        # while streaming results) in a top-level `errors` array. Treating that as an
        # empty result would show a missing root or silently drop branches. The
        # upstream error text is never forwarded (it can echo queries or hostnames).
        if isinstance(doc, dict) and doc.get("errors"):
            raise GraphImportError("query_failed", "The graph reported an error while running the query", status=502)
        data = doc.get("data") or {}
        fields = data.get("fields") or []
        return [dict(zip(fields, (_plain(v) for v in row))) for row in (data.get("values") or [])]

    def health(self) -> Dict[str, Any]:
        try:
            self._run("RETURN 1 AS ok", {})
        except GraphImportError as exc:
            return {"engine": self.engine, "status": "error", "code": exc.code}
        return {"engine": self.engine, "status": "ok"}


def _plain(v: Any) -> Any:
    """Unwrap typed-JSON values (``{"$type": "String", "_value": "x"}``) in case the
    server answers in typed form; plain JSON passes through untouched."""
    if isinstance(v, dict) and "$type" in v and "_value" in v:
        return _plain(v["_value"])
    return v
