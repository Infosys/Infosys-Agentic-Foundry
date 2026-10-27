#!/usr/bin/env python3
"""Migrate Command Center queue rows from SQLite into the Postgres claim store."""

from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path


STUDIO_ROOT = Path(__file__).resolve().parents[1]
HARNESS_ROOT = STUDIO_ROOT.parent
for path in (HARNESS_ROOT, STUDIO_ROOT, HARNESS_ROOT / "IAF-Agent-Skills"):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from cc_queue.postgres import PostgresQueueBackend  # noqa: E402


TABLES = ("queue_items", "job_executions", "job_steps", "routing_log", "dlq_items")


def _sqlite_tables(connection: sqlite3.Connection) -> set[str]:
    return {
        row[0]
        for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
        )
    }


def _columns(connection: sqlite3.Connection, table: str) -> list[str]:
    return [row[1] for row in connection.execute(f'PRAGMA table_info("{table}")')]


def _copy_table(source: sqlite3.Connection, backend: PostgresQueueBackend, table: str, batch: int) -> int:
    columns = _columns(source, table)
    if not columns:
        return 0
    column_list = ", ".join(f'"{column}"' for column in columns)
    placeholders = ", ".join(["%s"] * len(columns))
    sql = f'INSERT INTO "{table}" ({column_list}) VALUES ({placeholders}) ON CONFLICT DO NOTHING'
    total = 0
    rows = source.execute(f'SELECT {column_list} FROM "{table}"')
    with backend.engine.connect() as target:
        cursor = target.cursor()
        pending: list[tuple] = []
        for row in rows:
            pending.append(tuple(row))
            if len(pending) >= batch:
                cursor.executemany(sql, pending)
                total += len(pending)
                pending = []
        if pending:
            cursor.executemany(sql, pending)
            total += len(pending)
    return total


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sqlite", required=True, type=Path, help="Source command_center.db")
    parser.add_argument("--postgres", required=True, help="Target Postgres DSN")
    parser.add_argument("--batch", type=int, default=500)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    source_path = args.sqlite.expanduser().resolve()
    if not source_path.exists():
        raise SystemExit(f"SQLite source not found: {source_path}")

    source = sqlite3.connect(source_path)
    source.row_factory = sqlite3.Row
    try:
        available = _sqlite_tables(source)
        selected = [table for table in TABLES if table in available]
        print(f"[cc-queue-migrate] source={source_path}")
        print(f"[cc-queue-migrate] tables={selected}")
        for table in selected:
            count = source.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0]
            print(f"[cc-queue-migrate]  {table}: {count} row(s)")
        if args.dry_run:
            print("[cc-queue-migrate] dry-run complete (no writes).")
            return 0

        backend = PostgresQueueBackend(dsn=args.postgres)
        copied = 0
        for table in selected:
            copied += _copy_table(source, backend, table, max(1, args.batch))
        print(f"[cc-queue-migrate] copied {copied} row(s)")
        print("[cc-queue-migrate] start one Postgres queue worker and verify before scaling replicas.")
        return 0
    finally:
        source.close()


if __name__ == "__main__":
    raise SystemExit(main())
