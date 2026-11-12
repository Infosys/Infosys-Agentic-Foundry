"""Amazon Neptune adapter -- openCypher over HTTPS (``POST /openCypher``).

Auth is either IAM SigV4 (service ``neptune-db``; needs ``botocore``, imported
lazily so it stays an optional dependency) or none for clusters with IAM auth off.
Gremlin and SPARQL are intentionally not implemented here (see the council notes in
docs/TAXONOMY_GRAPH_IMPORT.md): the hierarchy fetch needs only openCypher.

Neptune cannot enforce read-only per request, so run it with an IAM identity that
only has ``neptune-db:ReadDataViaQuery``.
"""
from __future__ import annotations

import json
from typing import Any, Dict, List, Optional
from urllib.parse import urlencode

import httpx

from .cypher_base import CypherHierarchyAdapter
from .http_util import map_status, new_client, parse_json, post_capped
from .safety import GraphImportError

_FORM = "application/x-www-form-urlencoded"


class NeptuneAdapter(CypherHierarchyAdapter):
    engine = "neptune"
    id_function = "id"

    def __init__(
        self,
        base_url: str,
        *,
        auth: str = "sigv4",
        region: str = "",
        access_key_id: str = "",
        secret_access_key: str = "",
        session_token: str = "",
        client: Optional[httpx.Client] = None,
    ) -> None:
        self._base = base_url.rstrip("/")
        self._auth = (auth or "none").lower()
        if self._auth not in ("sigv4", "none"):
            raise GraphImportError("bad_auth", "Neptune auth must be 'sigv4' or 'none'", status=500)
        if self._auth == "sigv4" and not (region and access_key_id and secret_access_key):
            raise GraphImportError(
                "missing_credentials",
                "SigV4 needs a region and a credential with access_key_id / secret_access_key",
                status=500,
            )
        self._region = region
        self._creds = (access_key_id, secret_access_key, session_token or None)
        self._client = client or new_client()

    def _run(self, statement: str, params: Dict[str, Any]) -> List[Dict[str, Any]]:
        url = f"{self._base}/openCypher"
        body = urlencode({"query": statement, "parameters": json.dumps(params)})
        headers = {"Content-Type": _FORM, "Accept": "application/json"}
        if self._auth == "sigv4":
            headers.update(self._sign(url, body))
        status, raw = post_capped(self._client, url, content=body.encode("utf-8"), headers=headers)
        doc = parse_json(raw) if raw else {}
        map_status(status, doc)
        results = doc.get("results")
        if not isinstance(results, list):
            raise GraphImportError("bad_response", "The graph returned an unreadable response", status=502)
        return [r for r in results if isinstance(r, dict)]

    def _sign(self, url: str, body: str) -> Dict[str, str]:
        try:
            from botocore.auth import SigV4Auth
            from botocore.awsrequest import AWSRequest
            from botocore.credentials import Credentials
        except ImportError:
            raise GraphImportError(
                "sigv4_unavailable",
                "Neptune IAM auth needs the optional 'botocore' package (see requirements-graph-import.txt)",
                status=501,
            )
        req = AWSRequest(method="POST", url=url, data=body, headers={"Content-Type": _FORM})
        SigV4Auth(Credentials(*self._creds), "neptune-db", self._region).add_auth(req)
        return {k: str(v) for k, v in req.headers.items() if k.lower() != "content-type"}

    def health(self) -> Dict[str, Any]:
        try:
            self._run("RETURN 1 AS ok", {})
        except GraphImportError as exc:
            return {"engine": self.engine, "status": "error", "code": exc.code}
        return {"engine": self.engine, "status": "ok"}
