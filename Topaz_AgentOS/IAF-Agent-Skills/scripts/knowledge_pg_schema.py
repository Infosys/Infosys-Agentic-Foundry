"""Postgres schema for the knowledge index (SQLite → Postgres migration, Phase 0).

Validated in isolation 2026-07-21: generated tsvector FTS + GIN + bytea embeddings +
FK enforcement + GENERATED IDENTITY all confirmed against PostgreSQL 18.

Design notes:
  - FTS5 virtual tables (fts_knowledge/fts_episodes/fts_entities) are replaced by an
    app-filled `fts_text`/`entities_text` column + a GENERATED ALWAYS AS ... STORED
    `tsvector` column + a GIN index. The tsvector auto-maintains on INSERT/UPDATE, so the
    old delete-then-insert FTS sync code does NOT run on Postgres.
  - Reads use `search_tsv @@ websearch_to_tsquery(%s)` + `ts_rank_cd(...)`. The entity
    AND/OR sanitizer emits tsquery `&`/`|` and casts `::tsquery`.
  - Embeddings stay struct.pack float32 in BYTEA + Python brute-force cosine (parity with
    SQLite today). pgvector is the future upgrade (not installable in this environment yet).
  - Multi-agent isolation = schema-per-agent (SET LOCAL search_path). One schema per
    tenant/agent keeps every existing query unqualified/unchanged (lowest parity risk).
"""
from __future__ import annotations


def knowledge_schema_ddl(schema: str) -> str:
    """Return the full DDL that (re)creates the knowledge-index schema `schema` in Postgres.
    Caller runs it inside a connection; use with autocommit or commit at block end."""
    return f"""
CREATE SCHEMA IF NOT EXISTS {schema};
SET search_path TO {schema};

CREATE TABLE IF NOT EXISTS knowledge_vectors (
    id TEXT PRIMARY KEY,
    summary TEXT NOT NULL,
    knowledge_type TEXT, skill TEXT, status TEXT, source_file TEXT,
    embedding BYTEA,
    ts TEXT, entities_json TEXT, tags_json TEXT, written_to TEXT,
    source TEXT, applies_when TEXT, raw_json TEXT,
    fts_text TEXT,
    entities_text TEXT,
    search_tsv tsvector GENERATED ALWAYS AS (to_tsvector('english', coalesce(fts_text,''))) STORED,
    entities_tsv tsvector GENERATED ALWAYS AS (to_tsvector('simple', coalesce(entities_text,''))) STORED
);
CREATE INDEX IF NOT EXISTS idx_kv_search_tsv ON knowledge_vectors USING GIN(search_tsv);
CREATE INDEX IF NOT EXISTS idx_kv_entities_tsv ON knowledge_vectors USING GIN(entities_tsv);
CREATE INDEX IF NOT EXISTS idx_kv_skill ON knowledge_vectors(skill);
CREATE INDEX IF NOT EXISTS idx_kv_status ON knowledge_vectors(status);
CREATE INDEX IF NOT EXISTS idx_kv_type ON knowledge_vectors(knowledge_type);
CREATE INDEX IF NOT EXISTS idx_kv_ts ON knowledge_vectors(ts);
CREATE INDEX IF NOT EXISTS idx_kv_source ON knowledge_vectors(source);

CREATE TABLE IF NOT EXISTS episode_vectors (
    id TEXT PRIMARY KEY,
    file_path TEXT NOT NULL, session_id TEXT, user_input TEXT, summary TEXT,
    embedding BYTEA, ts TEXT, skill TEXT, trace_id TEXT, entities TEXT, reasoning TEXT,
    fts_text TEXT,
    search_tsv tsvector GENERATED ALWAYS AS (to_tsvector('english', coalesce(fts_text,''))) STORED
);
CREATE INDEX IF NOT EXISTS idx_ev_search_tsv ON episode_vectors USING GIN(search_tsv);
CREATE INDEX IF NOT EXISTS idx_ev_skill ON episode_vectors(skill);
CREATE INDEX IF NOT EXISTS idx_ev_ts ON episode_vectors(ts);

-- entity_registry BEFORE process_relationships/entity_xref (PG enforces FKs)
CREATE TABLE IF NOT EXISTS entity_registry (
    node_id TEXT PRIMARY KEY,
    node_type TEXT NOT NULL, display_name TEXT NOT NULL, parent_id TEXT,
    skill_name TEXT, embedding BYTEA, metadata_json TEXT DEFAULT '{{}}',
    aliases_json TEXT DEFAULT '[]', updated_at TEXT NOT NULL,
    fts_text TEXT,
    search_tsv tsvector GENERATED ALWAYS AS (to_tsvector('simple', coalesce(fts_text,''))) STORED
);
CREATE INDEX IF NOT EXISTS idx_er_search_tsv ON entity_registry USING GIN(search_tsv);
CREATE INDEX IF NOT EXISTS idx_er_parent ON entity_registry(parent_id);
CREATE INDEX IF NOT EXISTS idx_er_type ON entity_registry(node_type);
CREATE INDEX IF NOT EXISTS idx_er_skill ON entity_registry(skill_name);

CREATE TABLE IF NOT EXISTS entity_xref (
    entity TEXT NOT NULL, record_id TEXT NOT NULL,
    record_type TEXT NOT NULL DEFAULT 'knowledge',
    PRIMARY KEY (entity, record_id)
);
CREATE INDEX IF NOT EXISTS idx_ex_entity ON entity_xref(entity);
CREATE INDEX IF NOT EXISTS idx_ex_record ON entity_xref(record_id);

CREATE TABLE IF NOT EXISTS process_relationships (
    id TEXT PRIMARY KEY, from_node TEXT NOT NULL, relation TEXT NOT NULL,
    to_node TEXT NOT NULL, condition TEXT, metadata_json TEXT DEFAULT '{{}}',
    updated_at TEXT NOT NULL,
    confidence REAL DEFAULT 1.0, status TEXT DEFAULT 'curated',
    source TEXT, created_by TEXT, valid_from TEXT, valid_to TEXT,
    FOREIGN KEY (from_node) REFERENCES entity_registry(node_id),
    FOREIGN KEY (to_node)   REFERENCES entity_registry(node_id)
);
-- World-model provenance/temporal columns for existing tables. Idempotent. Postgres
-- backfills existing rows via the column DEFAULT, so prior seeder edges read as curated / 1.0.
-- IMPORTANT the knowledge-index DDL runner splits on the semicolon character, so neither these
-- comment lines nor the ALTERs below may contain an inline semicolon.
ALTER TABLE process_relationships ADD COLUMN IF NOT EXISTS confidence REAL DEFAULT 1.0;
ALTER TABLE process_relationships ADD COLUMN IF NOT EXISTS status TEXT DEFAULT 'curated';
ALTER TABLE process_relationships ADD COLUMN IF NOT EXISTS source TEXT;
ALTER TABLE process_relationships ADD COLUMN IF NOT EXISTS created_by TEXT;
ALTER TABLE process_relationships ADD COLUMN IF NOT EXISTS valid_from TEXT;
ALTER TABLE process_relationships ADD COLUMN IF NOT EXISTS valid_to TEXT;
CREATE INDEX IF NOT EXISTS idx_pr_from ON process_relationships(from_node);
CREATE INDEX IF NOT EXISTS idx_pr_to   ON process_relationships(to_node);
CREATE INDEX IF NOT EXISTS idx_pr_status ON process_relationships(status);

CREATE TABLE IF NOT EXISTS plan_cache (
    plan_id TEXT PRIMARY KEY, goal TEXT NOT NULL, embedding BYTEA, fingerprint TEXT,
    detected_domains TEXT, entity_types TEXT, process_nodes TEXT, plan_steps TEXT NOT NULL,
    critique_json TEXT, execution_mode TEXT DEFAULT 'react', status TEXT DEFAULT 'pending_review',
    session_id TEXT, tenant_id TEXT, agent_id TEXT, created_at TEXT NOT NULL,
    approved_at TEXT, approved_by TEXT, executed_at TEXT, use_count INTEGER DEFAULT 0,
    last_used_at TEXT, context_hints TEXT DEFAULT '[]'
);

CREATE TABLE IF NOT EXISTS routing_signal_log (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    timestamp TEXT DEFAULT (now()::text),
    query_text TEXT, entity_hint TEXT, entity_confidence REAL, process_hint TEXT,
    process_matches_json TEXT, signals_agree INTEGER, routed_skill TEXT, resolved_entities_json TEXT
);
"""
# Read-only-role GRANTs live in KnowledgeIndexer._init_db_postgres: this DDL is split on ';' so it cannot hold a plpgsql DO block.


# Concatenations the app must write into the feeder columns (mirrors the SQLite FTS5 inserts).
FTS_FEEDER_FIELDS = {
    "knowledge_vectors.fts_text": ["summary", "knowledge_type", "skill", "entities_text",
                                    "applies_when", "user_query", "source", "applies_to_text"],
    "knowledge_vectors.entities_text": ["entities_text (structured entity tokens, 'simple' tokenizer)"],
    "episode_vectors.fts_text": ["user_input", "summary", "skill"],
    "entity_registry.fts_text": ["display_name", "aliases_text"],
}
