"""Migrate RL capture data from SQLite → PostgreSQL.

Usage:
    python -m scripts.migrate_rl_to_postgres

Reads the SQLite database (RL_DB_PATH or default tenant path) and copies all
rows into the PostgreSQL database configured by DATABASE_URL / DB_BACKEND.
Schema is auto-created by PGRLStore on first instantiation.
"""

from __future__ import annotations

import json
import os
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "IAF-Agent-Skills"))

# Load .env file if present (so DATABASE_URL is available without manual export)
_env_file = Path(__file__).resolve().parent.parent / ".env"
if _env_file.exists():
    for line in _env_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, _, value = line.partition("=")
            os.environ.setdefault(key.strip(), value.strip())

from agent_os.safe_path import SecurityError, validated_path  # noqa: E402


def _get_sqlite_path() -> Path:
    """Resolve the SQLite RL database path."""
    db_path = os.getenv("RL_DB_PATH", "").strip()
    if db_path:
        return validated_path(db_path, label="RL_DB_PATH")
    data_root = validated_path(
        os.getenv(
            "ENTERPRISE_DATA_ROOT",
            str(Path(__file__).resolve().parent.parent / "enterprise_root"),
        ),
        label="ENTERPRISE_DATA_ROOT",
    )
    return (data_root / "tenants" / "company" / "shared" / "databases" / "rl.db").resolve()


def _connect_sqlite(path: Path) -> sqlite3.Connection:
    if not path.exists():
        raise FileNotFoundError(f"SQLite DB not found: {path}")
    conn = sqlite3.connect(str(path), timeout=30)
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
    row = conn.execute(
        "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name=?",
        (table,),
    ).fetchone()
    return bool(row and row[0])


def _migrate_table(
    sqlite_conn: sqlite3.Connection,
    pg_conn,
    table: str,
    columns: list[str],
) -> int:
    """Copy all rows from SQLite table to Postgres. Returns row count."""
    if not _table_exists(sqlite_conn, table):
        print(f"  [skip] {table} (not in SQLite)")
        return 0

    rows = sqlite_conn.execute(
        f"SELECT {', '.join(columns)} FROM {table}"
    ).fetchall()
    if not rows:
        print(f"  [skip] {table} (0 rows)")
        return 0

    placeholders = ", ".join(["%s"] * len(columns))
    conflict_cols = [c for c in columns if c != "id"]
    update_clause = ", ".join(f"{c} = EXCLUDED.{c}" for c in conflict_cols)

    sql = (
        f"INSERT INTO {table} ({', '.join(columns)}) VALUES ({placeholders})"
        f" ON CONFLICT (id) DO UPDATE SET {update_clause}"
    )

    count = 0
    for row in rows:
        pg_conn.execute(sql, row)
        count += 1

    return count


def main():
    os.environ["DB_BACKEND"] = "postgres"

    try:
        sqlite_path = _get_sqlite_path()
    except SecurityError as exc:
        raise SystemExit(f"ERROR: {exc}") from None
    print(f"Source SQLite: {sqlite_path}")

    if not sqlite_path.exists():
        # Try the alternate writable path
        alt = Path("D:/Agent_os_b/enterprise_root/tenants/company/shared/databases/rl_capture_rw.db")
        if alt.exists():
            sqlite_path = alt
            print(f"  (using alternate): {sqlite_path}")
        else:
            print("ERROR: No SQLite RL database found to migrate.")
            sys.exit(1)

    sqlite_conn = _connect_sqlite(sqlite_path)

    from iaf_agent_skills.storage.engine import get_engine
    from rl_capture.store.pg_store import PGRLStore

    engine = get_engine()
    print(f"Target PostgreSQL: {engine.dsn.split('@')[1] if '@' in (engine.dsn or '') else 'configured'}")

    store = PGRLStore(engine)
    print("Schema created/verified in PostgreSQL.")

    tables = [
        ("trajectories", [
            "id", "tenant_id", "agent_id", "session_id", "task", "fidelity",
            "terminal_status", "started_at", "ended_at", "capture_time",
            "trajectory_json", "metadata_json",
        ]),
        ("trajectory_steps", [
            "id", "trajectory_id", "step_index", "kind", "target_json", "metadata_json",
        ]),
        ("model_calls", [
            "id", "trajectory_id", "provider", "model", "fidelity",
            "prompt_tokens", "completion_tokens", "cost_usd", "latency_ms", "model_call_json",
        ]),
        ("tool_calls", [
            "id", "trajectory_id", "name", "status", "duration_ms", "tool_call_json",
        ]),
        ("observations", [
            "id", "trajectory_id", "source", "observation_json",
        ]),
        ("reward_events", [
            "id", "trajectory_id", "target_type", "target_id", "channel",
            "raw_label", "raw_value", "confidence", "reward_json", "created_at",
        ]),
        ("preference_signals", [
            "id", "trajectory_id", "provenance", "channel", "preference_json", "created_at",
        ]),
        ("candidate_outputs", [
            "id", "trajectory_id", "kind", "source", "candidate_json", "created_at",
        ]),
        ("evaluator_results", [
            "id", "trajectory_id", "rubric", "evaluator_json", "created_at",
        ]),
        ("trace_value_assessments", [
            "id", "trajectory_id", "input_hash", "rubric", "quality_score",
            "quality_verdict", "top_destination", "debug_only", "assessment_json", "created_at",
        ]),
        ("trace_route_decisions", [
            "id", "trajectory_id", "assessment_id", "destination", "action",
            "status", "reviewer", "target_ref", "decision_json", "created_at",
        ]),
        ("shadow_runs", [
            "id", "baseline_trajectory_id", "candidate_provider",
            "candidate_model", "shadow_json", "created_at",
        ]),
        ("exports", [
            "id", "kind", "params_json", "file_path", "checksum",
            "row_count", "export_json", "created_at",
        ]),
    ]

    print("\nMigrating tables...")
    total = 0
    with engine.connect() as pg_conn:
        for table, columns in tables:
            count = _migrate_table(sqlite_conn, pg_conn, table, columns)
            if count:
                print(f"  [done] {table}: {count} rows")
                total += count

    sqlite_conn.close()
    print(f"\nMigration complete: {total} total rows copied to PostgreSQL.")

    health = store.dataset_health()
    print("\nPostgreSQL dataset_health():")
    for table, count in health.items():
        if count > 0:
            print(f"  {table}: {count}")


if __name__ == "__main__":
    main()
