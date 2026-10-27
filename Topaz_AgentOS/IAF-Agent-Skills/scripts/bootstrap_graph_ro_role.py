#!/usr/bin/env python3
"""Bootstrap the least-privilege read-only role for the world-model ``graph`` resource.

What it does (idempotent — safe to re-run):
  1. Creates the role ``agentos_graph_ro`` (NOLOGIN — it can never connect, it is only
     a ``SET LOCAL ROLE`` target used by the run_sql_query gateway).
  2. Grants ``agentos_graph_ro`` to the connecting app role so the pooled connection may
     ``SET LOCAL ROLE agentos_graph_ro``.
  3. Grants SELECT on ONLY ``entity_registry`` + ``process_relationships`` in every
     existing ``kn_`` knowledge schema. New schemas pick this up automatically via
     ``knowledge_schema_ddl`` (which grants the same, guarded on role existence).

Effect: when the gateway runs a graph query it drops to this role, so the agent
physically cannot read memory tables (knowledge_vectors / plan_cache / episode_vectors)
even if its SQL names them — the isolation boundary is Postgres privileges, not regex.

Run once per Postgres database with a privileged (CREATEROLE / superuser) DATABASE_URL:
    ../.venv/bin/python3 scripts/bootstrap_graph_ro_role.py
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROLE = "agentos_graph_ro"


def _database_url() -> str | None:
    url = os.getenv("DATABASE_URL")
    if url:
        return url.strip().strip('"').strip("'")
    root = Path(__file__).resolve().parents[2]  # .../IAF_AgentOS_Harness_latest
    cfg = root / "agent_os" / "config.env"
    if cfg.exists():
        for line in cfg.read_text().splitlines():
            line = line.strip()
            if line.startswith("DATABASE_URL="):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    return None


def main() -> int:
    url = _database_url()
    if not url:
        print("ERROR: DATABASE_URL not set and not found in agent_os/config.env", file=sys.stderr)
        return 2
    try:
        import psycopg
    except ImportError:
        print("ERROR: psycopg not installed", file=sys.stderr)
        return 2

    with psycopg.connect(url, autocommit=True) as conn:
        cur = conn.cursor()

        # 1. Create the role if missing.
        cur.execute(
            "DO $$ BEGIN "
            "IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'agentos_graph_ro') THEN "
            "CREATE ROLE agentos_graph_ro NOLOGIN; "
            "END IF; END $$;"
        )

        # 2. Let the connecting app role SET ROLE to it.
        cur.execute("SELECT current_user")
        app_role = cur.fetchone()[0]
        cur.execute(f'GRANT {ROLE} TO "{app_role}"')

        # 3. Retroactively grant SELECT on the graph tables in every kn_ schema.
        cur.execute(
            "SELECT DISTINCT table_schema FROM information_schema.tables "
            "WHERE table_name IN ('entity_registry', 'process_relationships')"
        )
        schemas = sorted({r[0] for r in cur.fetchall()})
        granted = 0
        for schema in schemas:
            try:
                cur.execute(f'GRANT USAGE ON SCHEMA "{schema}" TO {ROLE}')
                cur.execute(f'GRANT SELECT ON "{schema}".entity_registry TO {ROLE}')
                cur.execute(f'GRANT SELECT ON "{schema}".process_relationships TO {ROLE}')
                granted += 1
            except Exception as exc:
                print(f"  WARN: grant on schema {schema} failed: {exc}", file=sys.stderr)

        print(
            f"OK: role '{ROLE}' ready; app_role='{app_role}' can SET ROLE; "
            f"granted SELECT on {granted}/{len(schemas)} schema(s)."
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
