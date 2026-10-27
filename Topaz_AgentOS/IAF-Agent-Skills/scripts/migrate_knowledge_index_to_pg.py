#!/usr/bin/env python3
"""Migrate a per-agent knowledge index (SQLite) into its Postgres schema.

Copies the KnowledgeIndexer-owned tables (knowledge_vectors, episode_vectors,
entity_registry, entity_xref, process_relationships, plan_cache, routing_signal_log)
from an agent's ``knowledge_index.db`` into the Postgres schema the live server will
derive for it (``kn_<tenant>_<agent>``). It:

  - reads the SQLite source READ-ONLY (never modifies it — SQLite stays authoritative),
  - computes the ``fts_text``/``entities_text`` feeder columns that back the generated
    tsvector FTS on Postgres (mirrors what upsert_knowledge/upsert_episode/register_entity write),
  - PRESERVES the existing embedding BYTEA verbatim (no re-embedding, no Azure dependency),
  - is idempotent (TRUNCATEs the target schema tables before copying).

Does NOT touch: fts_* (regenerated as tsvector), taxonomy_signal_index and
conversation_sessions (owned by other components that keep their own SQLite connection).

Requires KNOWLEDGE_BACKEND-independent Postgres config: DATABASE_URL (from agent_os/config.env).

Usage:
    KNOWLEDGE_BACKEND=postgres ../.venv/bin/python3 scripts/migrate_knowledge_index_to_pg.py \
        <path/to/agentA/memory/knowledge_index.db> [<path/to/agentB/.../knowledge_index.db> ...]
"""
from __future__ import annotations

import json
import os
import sqlite3
import sys
from pathlib import Path

_HARNESS = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_HARNESS))
sys.path.insert(0, str(_HARNESS / "IAF-Agent-Skills"))

# Load DATABASE_URL from config.env if not already in the environment.
try:
    from dotenv import load_dotenv
    load_dotenv(_HARNESS / "agent_os" / "config.env")
except Exception:
    pass
os.environ["KNOWLEDGE_BACKEND"] = "postgres"           # this process migrates INTO postgres
os.environ.pop("KNOWLEDGE_PG_SCHEMA", None)            # let the schema derive from db_path

from agent_os.safe_path import SecurityError, validated_path
from iaf_agent_skills.knowledge_indexer import KnowledgeIndexer


def _entities_text(entities_json):
    try:
        ents = json.loads(entities_json) if entities_json else []
    except Exception:
        ents = []
    return " ".join(str(e) for e in ents if e)


def _kv_fts_text(row_d):
    ents_text = _entities_text(row_d.get("entities_json"))
    user_query = ""
    applies_to_text = ""
    try:
        raw = json.loads(row_d.get("raw_json") or "{}")
        user_query = raw.get("user_query", "") or ""
        applies_to = raw.get("applies_to", {})
        if isinstance(applies_to, dict):
            applies_to_text = " ".join(str(v) for v in applies_to.values() if v)
    except Exception:
        pass
    parts = [row_d.get("summary"), row_d.get("knowledge_type"), row_d.get("skill"),
             ents_text, row_d.get("applies_when"), user_query, row_d.get("source"), applies_to_text]
    return " ".join(str(x) for x in parts if x), ents_text


def _ep_fts_text(row_d):
    parts = [row_d.get("user_input"), row_d.get("summary"), row_d.get("skill")]
    return " ".join(str(x) for x in parts if x)


def _er_fts_text(row_d):
    if row_d.get("node_type") not in ("ENTITY", "ENTITY_TYPE"):
        return ""
    try:
        aliases = json.loads(row_d.get("aliases_json") or "[]")
    except Exception:
        aliases = []
    alias_text = " ".join(a.lower().strip() for a in aliases if a and str(a).strip())
    return f"{(row_d.get('display_name') or '').lower()} {alias_text}".strip()


def _rows(scon, table):
    # Some agents never created every table (e.g. no routing_signal_log yet) — skip cleanly.
    exists = scon.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)
    ).fetchone()
    if not exists:
        return
    cur = scon.execute(f"SELECT * FROM {table}")
    cols = [d[0] for d in cur.description]
    for r in cur.fetchall():
        yield dict(zip(cols, r))


def _copy(sconn, pconn, ph, schema):
    pcur = pconn.cursor()
    counts = {}
    q = lambda t: f'"{schema}".{t}'  # fully-qualified — no reliance on search_path

    # Clean slate (idempotent). CASCADE handles the process_relationships FK.
    pcur.execute(
        f"TRUNCATE {q('knowledge_vectors')}, {q('episode_vectors')}, {q('entity_registry')}, "
        f"{q('entity_xref')}, {q('process_relationships')}, {q('plan_cache')}, "
        f"{q('routing_signal_log')} RESTART IDENTITY CASCADE"
    )

    def insert(table, cols, values_iter):
        vals = list(values_iter)
        if not vals:
            counts[table] = 0
            return
        collist = ", ".join(cols)
        placeholders = ", ".join([ph] * len(cols))
        pcur.executemany(
            f"INSERT INTO {q(table)} ({collist}) VALUES ({placeholders})", vals
        )
        counts[table] = len(vals)

    # entity_registry FIRST (process_relationships FKs to it)
    insert("entity_registry",
           ["node_id", "node_type", "display_name", "parent_id", "skill_name",
            "embedding", "metadata_json", "aliases_json", "updated_at", "fts_text"],
           ([d["node_id"], d["node_type"], d["display_name"], d["parent_id"], d["skill_name"],
             d["embedding"], d["metadata_json"], d["aliases_json"], d["updated_at"], _er_fts_text(d)]
            for d in _rows(sconn, "entity_registry")))

    insert("process_relationships",
           ["id", "from_node", "relation", "to_node", "condition", "metadata_json", "updated_at"],
           ([d["id"], d["from_node"], d["relation"], d["to_node"], d["condition"],
             d["metadata_json"], d["updated_at"]]
            for d in _rows(sconn, "process_relationships")))

    def _kv_vals():
        for d in _rows(sconn, "knowledge_vectors"):
            fts, ents_text = _kv_fts_text(d)
            yield [d["id"], d["summary"], d["knowledge_type"], d["skill"], d["status"],
                   d["source_file"], d["embedding"], d["ts"], d["entities_json"], d["tags_json"],
                   d["source"], d["applies_when"], d["raw_json"], d["written_to"], fts, ents_text]
    insert("knowledge_vectors",
           ["id", "summary", "knowledge_type", "skill", "status", "source_file", "embedding",
            "ts", "entities_json", "tags_json", "source", "applies_when", "raw_json",
            "written_to", "fts_text", "entities_text"],
           _kv_vals())

    insert("episode_vectors",
           ["id", "file_path", "session_id", "user_input", "summary", "embedding", "ts",
            "skill", "trace_id", "entities", "reasoning", "fts_text"],
           ([d["id"], d["file_path"], d["session_id"], d["user_input"], d["summary"],
             d["embedding"], d["ts"], d["skill"], d["trace_id"], d["entities"], d["reasoning"],
             _ep_fts_text(d)]
            for d in _rows(sconn, "episode_vectors")))

    insert("entity_xref", ["entity", "record_id", "record_type"],
           ([d["entity"], d["record_id"], d["record_type"]] for d in _rows(sconn, "entity_xref")))

    insert("plan_cache",
           ["plan_id", "goal", "embedding", "fingerprint", "detected_domains", "entity_types",
            "process_nodes", "plan_steps", "critique_json", "execution_mode", "status",
            "session_id", "tenant_id", "agent_id", "created_at", "approved_at", "approved_by",
            "executed_at", "use_count", "last_used_at", "context_hints"],
           ([d.get(c) for c in ["plan_id", "goal", "embedding", "fingerprint", "detected_domains",
             "entity_types", "process_nodes", "plan_steps", "critique_json", "execution_mode",
             "status", "session_id", "tenant_id", "agent_id", "created_at", "approved_at",
             "approved_by", "executed_at", "use_count", "last_used_at", "context_hints"]]
            for d in _rows(sconn, "plan_cache")))

    # routing_signal_log: skip the IDENTITY `id`; preserve original timestamp.
    insert("routing_signal_log",
           ["timestamp", "query_text", "entity_hint", "entity_confidence", "process_hint",
            "process_matches_json", "signals_agree", "routed_skill", "resolved_entities_json"],
           ([d["timestamp"], d["query_text"], d["entity_hint"], d["entity_confidence"],
             d["process_hint"], d["process_matches_json"], d["signals_agree"], d["routed_skill"],
             d["resolved_entities_json"]]
            for d in _rows(sconn, "routing_signal_log")))

    pconn.commit()
    return counts


_CONV_COLS = ["session_id", "tenant_id", "agent_id", "user_id", "parent_session_id",
              "title", "first_message", "created_at", "last_active_at",
              "turn_count", "skills_used", "status", "jsonl_path"]


def _copy_conversations(db_path: str, schema: str) -> int:
    """Copy conversation_sessions SQLite→PG. SAFE on an already-cutover agent — touches
    only the conversation_sessions table, never the live knowledge tables."""
    from iaf_agent_skills.conversation_manager import ConversationManager
    cm = ConversationManager(db_path=db_path)  # KNOWLEDGE_BACKEND=postgres → creates the table in schema
    sconn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=10)
    try:
        rows = list(_rows(sconn, "conversation_sessions"))
    finally:
        sconn.close()
    with cm._connect() as pconn:
        pcur = pconn.cursor()
        pcur.execute(f'TRUNCATE "{schema}".conversation_sessions')
        if rows:
            _ph = ", ".join([cm._ph] * len(_CONV_COLS))
            pcur.executemany(
                f'INSERT INTO "{schema}".conversation_sessions ({", ".join(_CONV_COLS)}) VALUES ({_ph})',
                [[d.get(c) for c in _CONV_COLS] for d in rows],
            )
        pconn.commit()
    return len(rows)


def migrate(db_path: str, force: bool = False):
    try:
        safe_db = validated_path(db_path, label="db_path")
    except SecurityError:
        safe_db = None
    if safe_db is None or not safe_db.exists():
        print(f"  SKIP (missing): {db_path}")
        return
    db_path = str(safe_db)
    idx = KnowledgeIndexer(db_path=db_path, get_embedding_fn=None)  # creates the PG schema+tables
    schema = idx._pg_schema
    print(f"\n=== {db_path}\n    → schema {schema}")

    # CLOBBER GUARD: refuse to overwrite a populated PG schema from stale SQLite unless --force (sessions still copy).
    with idx._scoped_connect() as pconn:
        pcur = pconn.cursor()
        pcur.execute(f'SELECT count(*) FROM "{schema}".knowledge_vectors')
        existing = pcur.fetchone()[0]
    if existing > 0 and not force:
        print(f"    PG already has {existing} knowledge rows — SKIP knowledge copy (pass --force to overwrite).")
        conv = _copy_conversations(db_path, schema)
        print(f"    copied {conv:>6}  conversation_sessions (safe, non-clobbering)")
        return

    sconn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=10)
    try:
        with idx._scoped_connect() as pconn:
            counts = _copy(sconn, pconn, idx._ph, schema)
            pconn.commit()
    finally:
        sconn.close()
    counts["conversation_sessions"] = _copy_conversations(db_path, schema)
    for t, c in counts.items():
        print(f"    copied {c:>6}  {t}")


if __name__ == "__main__":
    force = "--force" in sys.argv
    targets = [a for a in sys.argv[1:] if not a.startswith("--")]
    if not targets:
        print(__doc__)
        sys.exit(2)
    for t in targets:
        migrate(t, force=force)
    print("\nDONE. SQLite sources untouched (read-only).")
    print("\nDONE. SQLite sources untouched (read-only). Flip KNOWLEDGE_BACKEND=postgres to use them.")
