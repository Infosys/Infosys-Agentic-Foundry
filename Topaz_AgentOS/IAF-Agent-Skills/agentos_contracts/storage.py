"""Contracts for the pluggable storage layer.

AgentPro persists runtime state (knowledge index, evidence, traces, queues,
auth, RL capture, etc.) in a relational store. Historically that store was
always local SQLite, which cannot handle multi-process / multi-node writers and
is prone to ``database is locked`` and index drift under concurrency.

These Protocols describe the seam that lets the same code target either:

  * ``sqlite``   - the zero-dependency single-node / dev default (stdlib only).
  * ``postgres`` - the multi-node / HA enterprise backend (psycopg + pgvector),
                   installed only when a deployment selects it.

The engine never imports the host; the active backend is chosen from
configuration (``DB_BACKEND``) resolved through the runtime bridge. When nothing
is configured, callers fall back to SQLite so existing deployments are
unaffected.

This module is intentionally dependency-free.
"""

from __future__ import annotations

from typing import Any, ContextManager, Optional, Protocol, runtime_checkable

BACKEND_SQLITE = "sqlite"
BACKEND_POSTGRES = "postgres"
VALID_BACKENDS = (BACKEND_SQLITE, BACKEND_POSTGRES)


@runtime_checkable
class StorageEngine(Protocol):
    """A connection factory + SQL dialect for one configured backend.

    Implementations own connection creation (and pooling for Postgres) and
    expose just enough dialect metadata for repositories to emit portable SQL
    without a full ORM.
    """

    #: One of ``VALID_BACKENDS``.
    backend: str

    @property
    def is_postgres(self) -> bool:
        """True when the active backend is PostgreSQL."""

    def connect(self) -> ContextManager[Any]:
        """Yield a live DB connection as a context manager.

        For SQLite this opens a pragma-hardened ``sqlite3.Connection``; for
        Postgres it checks a connection out of the pool. The connection is
        committed on clean exit and rolled back on exception.
        """

    def placeholder(self, index: int) -> str:
        """Return the positional bind placeholder for the dialect.

        SQLite uses ``?``; Postgres uses ``%s``. ``index`` is 0-based to allow
        numbered placeholders if ever needed.
        """

    def health(self) -> dict[str, Any]:
        """Return bounded diagnostics (backend, reachable, pool stats)."""


@runtime_checkable
class KnowledgeStore(Protocol):
    """Persistence + search for the knowledge/episode index.

    Backs :class:`KnowledgeIndexer`. Vector similarity is delegated to a
    :class:`VectorBackend` (see ``vector_backend.py``); keyword search uses
    FTS5 on SQLite and ``tsvector``/GIN on Postgres, hidden behind
    ``search_keyword``.
    """

    def upsert_knowledge(self, record: dict, *, tenant_id: str, agent_id: str) -> bool: ...

    def upsert_episode(self, episode: dict, *, tenant_id: str, agent_id: str,
                       file_path: str = "") -> bool: ...

    def search_semantic(self, query_embedding: list[float], *, tenant_id: str,
                        agent_id: str, top_k: int = 10) -> list[dict]: ...

    def search_keyword(self, query: str, *, tenant_id: str, agent_id: str,
                       top_k: int = 10) -> list[dict]: ...

    def delete_record(self, record_id: str, *, tenant_id: str, agent_id: str) -> None: ...

    def health(self) -> dict[str, Any]: ...
