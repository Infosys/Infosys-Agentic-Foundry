"""AgentPro storage layer.

Config-driven relational storage with two backends:

  * ``sqlite``   - stdlib-only single-node / dev default (no extra installs).
  * ``postgres`` - multi-node / HA enterprise backend (requires
                   ``pip install 'psycopg[binary]' pgvector`` at deploy time).

Public API:
  * :func:`get_engine` - the process-wide :class:`StorageEngine` for the active
    backend, chosen from ``DB_BACKEND`` config.
  * :func:`resolve_backend` - the resolved backend name.
"""

from .engine import (
    StorageEngine,
    SqliteEngine,
    PostgresEngine,
    get_engine,
    resolve_backend,
    reset_engine,
)

__all__ = [
    "StorageEngine",
    "SqliteEngine",
    "PostgresEngine",
    "get_engine",
    "resolve_backend",
    "reset_engine",
]
