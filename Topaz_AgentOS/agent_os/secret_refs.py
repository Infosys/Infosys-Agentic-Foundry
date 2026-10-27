"""Neutral secret-reference expansion.

Expands the following placeholders in a string (or recursively in a dict/list),
given a ``CredentialStore`` and the *consumer* (the requesting skill) used for
consumer-scope enforcement:

    ${VAR}                  -> os.environ lookup.
    ${CRED:name/field}      -> `field` of stored credential `name`.
    ${VAULT:conn@path#key}  -> live `key` read from HashiCorp Vault via a
                               ``type: vault`` connection stored as credential
                               `conn` (addr/namespace/mount/AppRole or token).
                               `path` is the KV path within the connection's mount.

Secrets are fetched below the agent and never logged; unresolved refs are
returned unchanged so the resulting connect error surfaces the misconfiguration
instead of a silent empty value.

This lives in ``agent_os`` (the low-level package) so every secret-consuming
surface — the kernel, the MCP bridge, the tool factory — shares one resolver
instead of each re-implementing it. Callers pass the store + consumer they
already hold; discovery of the store is intentionally left to the caller.
"""

from __future__ import annotations

import logging
import os
import re
from typing import Any, Optional

logger = logging.getLogger(__name__)

# path may contain "/" (and dots/dashes); it stops at the "#" key delimiter.
_VAULT_RE = re.compile(r'\$\{VAULT:([A-Za-z0-9_.\-]+)@([^#}]+)#([A-Za-z0-9_.\-]+)\}')
_CRED_RE = re.compile(r'\$\{CRED:([A-Za-z0-9_.\-]+)/([A-Za-z0-9_.\-]+)\}')
_VAR_RE = re.compile(r'\$\{(\w+)\}')


def _vault_sub(store: Any, consumer: Optional[str], purpose: str, m: "re.Match") -> str:
    conn, path, key, original = m.group(1), m.group(2), m.group(3), m.group(0)
    resolver = getattr(store, "resolve_vault_secret", None) if store is not None else None
    if not callable(resolver):
        return original
    try:
        cred = resolver(conn, path, key, consumer=consumer, purpose=purpose)
    except Exception as exc:  # fail closed — leave the ref so the misconfig surfaces
        logger.warning("secret_refs: vault ref '%s@%s#%s' failed: %s", conn, path, key, type(exc).__name__)
        return original
    if not cred:
        logger.warning(
            "secret_refs: vault ref '%s@%s#%s' unresolved (not found / scope-denied / read failed) for consumer=%r",
            conn, path, key, consumer,
        )
        return original
    val = cred.value.get(key)
    return str(val) if val is not None else original


def _cred_sub(store: Any, consumer: Optional[str], purpose: str, m: "re.Match") -> str:
    name, field, original = m.group(1), m.group(2), m.group(0)
    if store is None:
        return original
    try:
        cred = store.get(name, consumer=consumer, purpose=purpose)
    except Exception as exc:
        logger.warning("secret_refs: credential lookup '%s' failed: %s", name, type(exc).__name__)
        return original
    if not cred:
        logger.warning("secret_refs: credential '%s' not found or scope-denied for consumer=%r", name, consumer)
        return original
    # field lives in either .value (secret dict) or .metadata (non-secret bag)
    val = cred.value.get(field)
    if val is None:
        val = cred.metadata.get(field)
    if val is None:
        logger.warning("secret_refs: credential '%s' has no field '%s'", name, field)
        return original
    return str(val)


def iter_ref_targets(obj: Any):
    """Yield ``(kind, name)`` for every ``${VAULT:...}`` / ``${CRED:...}`` reference
    found in a string/dict/list, where ``kind`` is ``"vault"`` (connection name) or
    ``"cred"`` (credential name). Callers that must authorize each referenced secret
    before expansion (e.g. against an external-access policy) use this so the regex
    that defines a ref stays owned here, not duplicated at every call site.
    """
    if isinstance(obj, str):
        for m in _VAULT_RE.finditer(obj):
            yield ("vault", m.group(1))
        for m in _CRED_RE.finditer(obj):
            yield ("cred", m.group(1))
    elif isinstance(obj, dict):
        for v in obj.values():
            yield from iter_ref_targets(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from iter_ref_targets(v)


def expand_secret_refs(
    value: Any,
    store: Any,
    consumer: Optional[str] = None,
    *,
    purpose: str = "secret ref",
) -> Any:
    """Expand ``${VAULT:...}``, ``${CRED:...}`` and ``${VAR}`` in a single string.

    Non-string values are returned unchanged. A None ``store`` skips CRED/VAULT
    (those refs are left intact) but ``${VAR}`` is still expanded.
    """
    if not isinstance(value, str):
        return value
    # Vault first (live secret), then stored credentials, then plain env vars.
    value = _VAULT_RE.sub(lambda m: _vault_sub(store, consumer, purpose, m), value)
    value = _CRED_RE.sub(lambda m: _cred_sub(store, consumer, purpose, m), value)
    value = _VAR_RE.sub(lambda m: os.environ.get(m.group(1), m.group(0)), value)
    return value


def expand_secret_refs_in_obj(
    obj: Any,
    store: Any,
    consumer: Optional[str] = None,
    *,
    purpose: str = "secret ref",
) -> Any:
    """Recursively expand refs in all string values of a dict/list/str."""
    if isinstance(obj, str):
        return expand_secret_refs(obj, store, consumer, purpose=purpose)
    if isinstance(obj, dict):
        return {k: expand_secret_refs_in_obj(v, store, consumer, purpose=purpose) for k, v in obj.items()}
    if isinstance(obj, list):
        return [expand_secret_refs_in_obj(v, store, consumer, purpose=purpose) for v in obj]
    return obj
