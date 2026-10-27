"""Shared SQLite connection helper.

Central place that applies the concurrency-safe PRAGMAs every opener in the
codebase should use. Historically each module called ``sqlite3.connect`` with
its own (often missing) pragmas, which caused ``database is locked`` errors and
index drift on the shared knowledge index. Route all SQLite opens through
``connect()`` so WAL + a generous ``busy_timeout`` are always applied.

This module intentionally has no dependencies on ``shared`` / ``routers`` or any
host package so the engine can use it standalone.
"""

from __future__ import annotations

import logging
import sqlite3
from pathlib import Path
from typing import Optional, Union

logger = logging.getLogger(__name__)

DEFAULT_BUSY_TIMEOUT_MS = 30000


def connect(
    db_path: Union[str, Path],
    *,
    check_same_thread: bool = False,
    isolation_level: Optional[str] = "DEFERRED",
    timeout: float = 30.0,
    wal: bool = True,
    busy_timeout_ms: int = DEFAULT_BUSY_TIMEOUT_MS,
    row_factory: Optional[type] = None,
) -> sqlite3.Connection:
    """Open a SQLite connection with concurrency-safe pragmas applied.

    Args:
        db_path: Path to the database file.
        check_same_thread: Passed to ``sqlite3.connect`` (default False so a
            single connection can be shared across threads with app-level care).
        isolation_level: Transaction isolation; ``None`` = autocommit.
        timeout: Python-level connect timeout (seconds).
        wal: Enable Write-Ahead Logging (allows concurrent readers + 1 writer).
        busy_timeout_ms: Milliseconds to wait for a lock before erroring.
        row_factory: Optional ``sqlite3.Row`` for dict-like access.
    """
    conn = sqlite3.connect(
        str(db_path),
        check_same_thread=check_same_thread,
        isolation_level=isolation_level,
        timeout=timeout,
    )
    if row_factory is not None:
        conn.row_factory = row_factory
    if wal:
        try:
            conn.execute("PRAGMA journal_mode=WAL")
        except sqlite3.OperationalError as exc:
            if "readonly" in str(exc).lower():
                logger.warning(
                    "sqlite_util: cannot enable WAL on %s (read-only filesystem) — "
                    "falling back to DELETE journal mode: %s",
                    db_path,
                    exc,
                )
            else:
                raise
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA busy_timeout=%d" % int(busy_timeout_ms))
    return conn
