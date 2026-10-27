"""SSRF guard for outbound HTTP — scheme allowlist + resolve-once address filtering.

Why this exists
---------------
Before this module the deployment had *no* SSRF controls at all: no scheme
allowlist, no DNS pre-resolution, and no blocking of private / loopback /
link-local / cloud-metadata addresses. A URL such as
``http://169.254.169.254/latest/meta-data/`` — or any hostname whose DNS record
points there — was fetched without question, and the allowlist itself compared
the *literal* hostname string, so ``169.254.169.254.nip.io`` also sailed through.

Design
------
``assert_safe_url()`` is the single entry point. It:

1. requires an ``http``/``https`` scheme (no ``file://``, ``dict://``, ``gopher://``);
2. resolves the hostname **once** and returns the pinned address set, so the
   caller can connect to a checked address rather than re-resolving (which is
   what makes DNS-rebinding possible);
3. rejects the request if **any** resolved address is private, loopback,
   link-local, multicast, reserved, unspecified, or cloud-metadata.

Rejecting on *any* bad address (rather than requiring all to be bad) is the
conservative choice: a split-horizon record that returns one public and one
internal address must not be reachable.

This is deliberately dependency-free (stdlib only) so it can be imported from
the kernel, a router, or a future sandbox/egress backend without new packages.
"""

from __future__ import annotations

import ipaddress
import socket
from urllib.parse import urlparse

ALLOWED_SCHEMES = frozenset({"http", "https"})

# Link-local, but listed so audit messages name the real risk.
METADATA_ADDRESSES = frozenset({
    "169.254.169.254",   # AWS / Azure / GCP / OpenStack IMDS
    "fd00:ec2::254",     # AWS IMDS over IPv6
})
METADATA_HOSTNAMES = frozenset({
    "metadata.google.internal",
    "metadata",
    "instance-data",
})


class SSRFBlocked(ValueError):
    """Raised when a URL is rejected by the egress guard."""


def _address_verdict(ip: ipaddress._BaseAddress) -> str:
    """Return a rejection reason for `ip`, or "" when the address is acceptable."""
    if str(ip) in METADATA_ADDRESSES:
        return "cloud instance-metadata address"
    if ip.is_loopback:
        return "loopback address"
    if ip.is_link_local:
        return "link-local address"
    if ip.is_multicast:
        return "multicast address"
    if ip.is_unspecified:
        return "unspecified address"
    if ip.is_reserved:
        return "reserved address"
    if ip.is_private:
        return "private address"
    return ""


def resolve_pinned(host: str, port: int) -> list[str]:
    """Resolve `host` once and return the de-duplicated address list."""
    try:
        infos = socket.getaddrinfo(host, port, proto=socket.IPPROTO_TCP)
    except socket.gaierror as exc:
        raise SSRFBlocked(f"hostname does not resolve: {host} ({exc})") from exc
    seen: list[str] = []
    for info in infos:
        addr = info[4][0]
        if addr not in seen:
            seen.append(addr)
    if not seen:
        raise SSRFBlocked(f"hostname resolved to no addresses: {host}")
    return seen


def assert_safe_url(url: str, *, allow_loopback: bool = False) -> list[str]:
    """Validate `url` for outbound fetching. Returns the pinned address list.

    Raises SSRFBlocked with a human-readable reason when the target is unsafe.

    allow_loopback: set True only for deliberate self-API calls (the platform's
    own loopback endpoints), never for a user- or model-supplied URL.
    """
    parsed = urlparse((url or "").strip())
    scheme = (parsed.scheme or "").lower()
    if scheme not in ALLOWED_SCHEMES:
        raise SSRFBlocked(
            f"scheme '{scheme or '(none)'}' is not permitted; allowed: {sorted(ALLOWED_SCHEMES)}"
        )
    host = parsed.hostname
    if not host:
        raise SSRFBlocked("URL has no host")
    if host.lower() in METADATA_HOSTNAMES:
        raise SSRFBlocked(f"metadata hostname is not permitted: {host}")

    port = parsed.port or (443 if scheme == "https" else 80)
    addresses = resolve_pinned(host, port)
    for addr in addresses:
        try:
            ip = ipaddress.ip_address(addr)
        except ValueError:  # pragma: no cover - getaddrinfo returned a non-IP
            raise SSRFBlocked(f"unparseable resolved address: {addr}") from None
        reason = _address_verdict(ip)
        if reason == "loopback address" and allow_loopback:
            continue
        if reason:
            raise SSRFBlocked(f"{host} resolves to {addr} — {reason} is not permitted")
    return addresses


def is_safe_url(url: str, *, allow_loopback: bool = False) -> tuple[bool, str]:
    """Non-raising variant: returns (ok, reason)."""
    try:
        assert_safe_url(url, allow_loopback=allow_loopback)
        return True, ""
    except SSRFBlocked as exc:
        return False, str(exc)
