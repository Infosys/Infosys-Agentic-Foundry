"""Single storage-mode seam — one ``STORAGE_MODE`` knob cascades to every store.

Deepening of the previously scattered backend resolvers. Seven independent
``os.getenv`` reads decided the relational store, knowledge store, evidence
store, trace store, vector store, command-center queue store, and lane queue —
each with its own default. Setting ``DB_BACKEND=postgres`` alone left the other
six silently on SQLite/brute-force/memory (a split-brain "go Postgres").

This module makes ``STORAGE_MODE`` the single decision. When set, it fills any
backend variable the operator did **not** explicitly set (per-store overrides
still win), so the choice is coherent end-to-end. A coherence validator rejects
unsupported mixes (e.g. ``pgvector`` on a non-Postgres relational store) at
startup instead of surfacing them as a runtime error on the first query.

Byte-identical when ``STORAGE_MODE`` is unset: :func:`apply_storage_mode`
fills nothing and only validates the already-resolved combination.

Mirrors the real per-module defaults:
    DB_BACKEND               sqlite       shared/config.py
    KNOWLEDGE_BACKEND        sqlite       IAF-Agent-Skills/.../knowledge_indexer.py
    EVIDENCE_BACKEND         sqlite       shared/evidence_store.py
    TRACE_BACKEND            sqlite       trace_emitter.py
    VECTOR_BACKEND           brute_force  IAF-Agent-Skills/.../vector_backend.py
    CC_QUEUE_STORAGE_BACKEND sqlite       cc_queue/db.py
    QUEUE_BACKEND            memory       shared/state.py
"""
from __future__ import annotations

import logging
import os
from typing import Mapping, MutableMapping, Optional

logger = logging.getLogger("iaf_server")


class IncoherentStorageConfig(RuntimeError):
    """Raised when backend flags form an unsupported combination."""


# STORAGE_MODE -> canonical backend values. Only fills vars the operator did not
# set, so an explicit per-store override always wins over the cascade.
_CASCADE: dict[str, dict[str, str]] = {
    "postgres": {
        "DB_BACKEND": "postgres",
        "KNOWLEDGE_BACKEND": "postgres",
        "EVIDENCE_BACKEND": "postgres",
        "TRACE_BACKEND": "postgres",
        "VECTOR_BACKEND": "pgvector",
        "CC_QUEUE_STORAGE_BACKEND": "postgres",
        "QUEUE_BACKEND": "redis",
    },
    "sqlite": {
        "DB_BACKEND": "sqlite",
        "KNOWLEDGE_BACKEND": "sqlite",
        "EVIDENCE_BACKEND": "sqlite",
        "TRACE_BACKEND": "sqlite",
        "VECTOR_BACKEND": "brute_force",
        "CC_QUEUE_STORAGE_BACKEND": "sqlite",
        "QUEUE_BACKEND": "memory",
    },
}

# Per-var defaults used to build the resolved view when a var is left unset and
# no STORAGE_MODE cascade applies (matches each module's own getenv default).
_DEFAULTS = dict(_CASCADE["sqlite"])
BACKEND_VARS: tuple[str, ...] = tuple(_DEFAULTS.keys())


def apply_storage_mode(
    environ: Optional[MutableMapping[str, str]] = None,
) -> dict[str, str]:
    """Cascade ``STORAGE_MODE`` into any unset backend var, then validate.

    No-op fill when ``STORAGE_MODE`` is unset. Returns the resolved
    ``{var: value}`` map for the seven backend vars (whether or not this call
    changed them) for logging/inspection. Raises
    :class:`IncoherentStorageConfig` on an unsupported mode or an incoherent
    combination.
    """
    env: MutableMapping[str, str] = os.environ if environ is None else environ
    mode = (env.get("STORAGE_MODE") or "").strip().lower()

    if mode:
        if mode not in _CASCADE:
            raise IncoherentStorageConfig(
                f"STORAGE_MODE={mode!r} is not supported "
                f"(use {' | '.join(sorted(_CASCADE))})"
            )
        filled: list[str] = []
        for var, value in _CASCADE[mode].items():
            if not (env.get(var) or "").strip():
                env[var] = value
                filled.append(var)
        if filled:
            logger.info("STORAGE_MODE=%s cascaded to: %s", mode, ", ".join(filled))

    resolved = {
        var: ((env.get(var) or "").strip().lower() or _DEFAULTS[var])
        for var in BACKEND_VARS
    }
    validate_storage_coherence(resolved)
    return resolved


def validate_storage_coherence(resolved: Mapping[str, str]) -> None:
    """Reject unsupported backend combinations. Raises IncoherentStorageConfig."""
    if (
        resolved.get("VECTOR_BACKEND") == "pgvector"
        and resolved.get("DB_BACKEND") != "postgres"
    ):
        raise IncoherentStorageConfig(
            "VECTOR_BACKEND=pgvector requires DB_BACKEND=postgres "
            "(set STORAGE_MODE=postgres, or DB_BACKEND=postgres)."
        )


def resolved_storage_backends(
    environ: Optional[Mapping[str, str]] = None,
) -> dict[str, str]:
    """Read-only view of the currently resolved backend for each of the 7 stores.

    Applies each store's documented default for any unset var. Does NOT mutate
    the environment or cascade — use :func:`apply_storage_mode` for that. Intended
    for observability surfaces (metrics/health) so backend drift is visible.
    """
    env: Mapping[str, str] = os.environ if environ is None else environ
    return {
        var: ((env.get(var) or "").strip().lower() or _DEFAULTS[var])
        for var in BACKEND_VARS
    }
