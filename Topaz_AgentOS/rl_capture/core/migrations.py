"""SQLite schema migration helpers for RL capture stores."""

from __future__ import annotations

import sqlite3


def ensure_migration_table(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS schema_migrations (
            version INTEGER PRIMARY KEY,
            applied_at TEXT NOT NULL
        )
        """
    )


def applied_versions(conn: sqlite3.Connection) -> set[int]:
    ensure_migration_table(conn)
    return {int(row[0]) for row in conn.execute("SELECT version FROM schema_migrations").fetchall()}


def mark_applied(conn: sqlite3.Connection, version: int) -> None:
    ensure_migration_table(conn)
    conn.execute(
        "INSERT OR IGNORE INTO schema_migrations (version, applied_at) VALUES (?, datetime('now'))",
        (version,),
    )
