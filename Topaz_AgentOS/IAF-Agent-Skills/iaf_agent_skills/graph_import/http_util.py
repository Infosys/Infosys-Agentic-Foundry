"""Bounded, redirect-free HTTP helper shared by the graph adapters."""
from __future__ import annotations

import json
import logging
from typing import Any, Dict, Optional, Tuple

import httpx

from .safety import GraphImportError

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT = 20.0
MAX_RESPONSE_BYTES = 10 * 1024 * 1024


def new_client(timeout: float = DEFAULT_TIMEOUT) -> httpx.Client:
    # follow_redirects=False: a registered endpoint must not be able to bounce us
    # to an unregistered host. TLS verification stays on (SSL_CERT_FILE is honoured).
    return httpx.Client(timeout=timeout, follow_redirects=False)


def post_capped(
    client: httpx.Client,
    url: str,
    *,
    max_bytes: int = MAX_RESPONSE_BYTES,
    **kwargs: Any,
) -> Tuple[int, bytes]:
    """POST and read at most ``max_bytes`` of the body. Transport errors are
    mapped to ``GraphImportError`` with generic text (httpx messages can echo the
    URL, so they are logged server-side only)."""
    try:
        with client.stream("POST", url, **kwargs) as resp:
            total, chunks = 0, []
            for chunk in resp.iter_bytes():
                total += len(chunk)
                if total > max_bytes:
                    raise GraphImportError("response_too_large", "The graph returned too much data", status=502)
                chunks.append(chunk)
            return resp.status_code, b"".join(chunks)
    except GraphImportError:
        raise
    except httpx.TimeoutException:
        logger.warning("graph import: upstream timeout")
        raise GraphImportError("timeout", "The graph did not respond in time", status=504)
    except httpx.HTTPError:
        logger.warning("graph import: upstream transport error", exc_info=True)
        raise GraphImportError("unreachable", "Could not connect to the graph endpoint", status=502)


def parse_json(body: bytes) -> Dict[str, Any]:
    try:
        doc = json.loads(body.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        raise GraphImportError("bad_response", "The graph returned an unreadable response", status=502)
    if not isinstance(doc, dict):
        raise GraphImportError("bad_response", "The graph returned an unreadable response", status=502)
    return doc


def map_status(status: int, doc: Optional[Dict[str, Any]] = None) -> None:
    """Raise a safe error for non-2xx responses. Upstream error bodies are never
    forwarded (they can echo queries, hostnames or credentials)."""
    if 200 <= status < 300:
        return
    if status in (401, 403):
        raise GraphImportError("auth_failed", "The graph rejected the credentials", status=502)
    if status == 404:
        raise GraphImportError("not_found", "Graph endpoint or database not found", status=502)
    if status == 400:
        raise GraphImportError("query_rejected", "The graph rejected the query", status=502)
    raise GraphImportError("upstream_error", f"The graph returned an error (HTTP {status})", status=502)
