"""Input/endpoint safety for graph import.

Two rules keep this feature small and safe:

1. **No free-text queries.** The only caller-influenced pieces of a statement are
   identifiers (label / relationship type / property name), which cannot be bound
   as Cypher parameters, so they are validated against a strict regex and
   back-tick quoted. Values (root name, id lists) are always bound parameters.
2. **Callers pick a registered connection id, never a URL.** The endpoint comes from
   the tenant's external-access registry (admin controlled). ``check_endpoint`` is
   defense in depth via the shared ``agent_os.egress_ssrf`` guard: it refuses
   cloud-metadata / link-local / unspecified targets even if one were ever registered.
"""
from __future__ import annotations

import ipaddress
import re
from typing import List, Tuple

from agent_os.egress_ssrf import SSRFBlocked, assert_safe_url

_IDENT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,63}$")
_DBNAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,62}$")


class GraphImportError(Exception):
    """Carries a stable ``code`` and a message that is safe to show to a user.

    Never put URLs, credentials or upstream response bodies in ``message``.
    """

    def __init__(self, code: str, message: str, status: int = 400):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status


def validate_identifier(value: str, what: str) -> str:
    v = (value or "").strip()
    if not _IDENT_RE.match(v):
        raise GraphImportError(
            "bad_identifier",
            f"{what} must be 1-64 characters: letters, digits or underscore, not starting with a digit",
        )
    return v


def validate_database_name(value: str) -> str:
    v = (value or "").strip()
    if not _DBNAME_RE.match(v):
        raise GraphImportError("bad_database", "Database name contains unsupported characters")
    return v


def clamp_int(value, lo: int, hi: int, default: int) -> int:
    try:
        n = int(value)
    except (TypeError, ValueError):
        return default
    return max(lo, min(hi, n))


def split_host_port(host_port: str, default_port: int) -> Tuple[str, int]:
    hp = (host_port or "").strip()
    if not hp or "/" in hp or "@" in hp or " " in hp:
        raise GraphImportError("bad_endpoint", "Connection endpoint is misconfigured", status=500)
    if hp.startswith("["):  # [v6]:port
        host, _, rest = hp[1:].partition("]")
        port_s = rest.lstrip(":")
    else:
        host, _, port_s = hp.partition(":")
    if not host:
        raise GraphImportError("bad_endpoint", "Connection endpoint is misconfigured", status=500)
    try:
        port = int(port_s) if port_s else default_port
    except ValueError:
        raise GraphImportError("bad_endpoint", "Connection endpoint is misconfigured", status=500)
    return host, port


def check_endpoint(scheme: str, host: str, port: int) -> List[ipaddress._BaseAddress]:
    """Defense in depth on a *registered* endpoint, via the platform's shared SSRF
    guard (``agent_os.egress_ssrf``): resolves once and refuses cloud-metadata,
    link-local, multicast, reserved and unspecified targets. Private and loopback
    ranges are allowed on purpose (``allow_private``): Neptune lives in a VPC and a
    local Neo4j is a normal dev setup -- the registry is the allowlist.
    Returns the resolved addresses so callers can apply further policy."""
    netloc = f"[{host}]" if ":" in host else host
    try:
        addrs = assert_safe_url(f"{scheme}://{netloc}:{port}", allow_private=True)
    except SSRFBlocked as exc:
        # The guard's message names the host/address; keep it out of API responses.
        if "does not resolve" in str(exc) or "resolved to no addresses" in str(exc):
            raise GraphImportError("unreachable", "Could not resolve the graph endpoint", status=502)
        raise GraphImportError("endpoint_blocked", "The graph endpoint resolves to a blocked address", status=400)
    return [ipaddress.ip_address(a.split("%")[0]) for a in addrs]
