"""
Enterprise Evidence store (SQLite by default; Postgres when EVIDENCE_BACKEND=postgres).

The store persists normalized evidence bundles for chat, REST, cron, and queue
executions. File evidence can be resolved on demand; ephemeral API/DB/email
payloads may be stored as blobs when collectors include them.

Backend seam (mirrors ConversationManager / KnowledgeIndexer):
  - SQLite (default): one per-tenant `evidence.db` file, pragma-hardened connection.
  - Postgres (EVIDENCE_BACKEND=postgres): the three evidence tables live in a
    per-tenant schema (`ev_<tenant>`) on the shared pooled engine, so evidence is
    shared across every app instance instead of being pinned to one machine's disk.
    Tenant-scoped (structural isolation via `SET LOCAL search_path`), which is
    deliberately distinct from the per-agent knowledge schema (`kn_<tenant>_<agent>`).

`EVIDENCE_BACKEND=postgres` uses the shared Postgres engine, so `DB_BACKEND=postgres`
(DATABASE_URL) must be configured too — identical to the knowledge/conversation seam.
"""

from __future__ import annotations

import json
import os
import sqlite3
import hashlib
from iaf_agent_skills.sqlite_util import connect as _sqlite_connect
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from shared.config import DATA_ROOT, SERVER_DIR, TENANT_ID

from agent_os.safe_path import safe_join_under_root, validated_path

SCHEMA_VERSION = "1.1"


def _resolve_evidence_backend() -> str:
    """Own opt-in flag, independent of the queue/knowledge flags. Default sqlite so the
    live server is unaffected until an operator explicitly sets EVIDENCE_BACKEND=postgres."""
    raw = (os.getenv("EVIDENCE_BACKEND", "sqlite") or "sqlite").strip().lower()
    return "postgres" if raw in ("postgres", "postgresql", "pg") else "sqlite"


def evidence_db_path(tenant_id: str = "") -> Path:
    # SQLite only: EVIDENCE_DB_ROOT keeps the file off shared network mounts (lock/WAL-fragile).
    override = os.getenv("EVIDENCE_DB_ROOT", "").strip()
    if override:
        data_root = validated_path(override, label="EVIDENCE_DB_ROOT")
    else:
        root = Path(DATA_ROOT)
        data_root = root if root.is_absolute() else (SERVER_DIR / root).resolve()
    # Tenant id is a single validated segment; the joined dir stays under data_root.
    db_dir = safe_join_under_root(
        data_root,
        f"tenants/{tenant_id or TENANT_ID}/shared/databases",
        label="evidence DB directory",
    )
    db_dir.mkdir(parents=True, exist_ok=True)
    return db_dir / "evidence.db"


class EvidenceStore:
    def __init__(self, tenant_id: str = ""):
        self.tenant_id = tenant_id or TENANT_ID
        # db_path stays set on both backends (some callers read it); on Postgres it is
        # only advisory — no SQLite file is opened.
        self.db_path = evidence_db_path(self.tenant_id)

        self._backend = _resolve_evidence_backend()
        self._ph = "%s" if self._backend == "postgres" else "?"
        self._engine = None
        self._pg_schema = None
        if self._backend == "postgres":
            from iaf_agent_skills.storage.engine import get_engine
            self._engine = get_engine()  # shared pooled engine (DSN from DATABASE_URL)
            self._pg_schema = self._derive_pg_schema()

        self._init_db()

    def _derive_pg_schema(self) -> str:
        """Per-tenant Postgres schema `ev_<tenant>` (overridable via EVIDENCE_PG_SCHEMA).
        Tenant-scoped, distinct from the per-agent knowledge schema `kn_<tenant>_<agent>`."""
        import re
        raw = os.getenv("EVIDENCE_PG_SCHEMA") or f"ev_{self.tenant_id}"
        return re.sub(r"[^a-zA-Z0-9_]", "_", raw).lower()[:63]

    def _cursor(self, conn):
        """Dict-row cursor on BOTH backends so `row["col"]` / `_row_to_item(row)` work
        unchanged (SQLite via connection row_factory; Postgres via dict_row)."""
        if self._backend == "postgres":
            from psycopg.rows import dict_row
            return conn.cursor(row_factory=dict_row)
        return conn.cursor()

    def store_bundle(self, bundle: dict[str, Any]) -> dict[str, Any]:
        if not bundle or not bundle.get("trace_id"):
            return {}

        trace_id = str(bundle["trace_id"])
        tenant_id = str(bundle.get("tenant_id") or self.tenant_id)
        items = _normalize_items(bundle)
        now = _now()

        # Merge normalized items back so get_bundle() returns a complete payload.
        bundle_to_store = dict(bundle)
        bundle_to_store["evidence_items"] = items
        bundle_to_store.setdefault("schema_version", SCHEMA_VERSION)

        ph = self._ph
        with self._connect() as conn:
            cur = self._cursor(conn)
            cur.execute(f"SELECT user_id FROM evidence_bundles WHERE trace_id = {ph}", (trace_id,))
            existing = cur.fetchone()
            # A trace id is owned by its first writer; another principal cannot overwrite it.
            if existing and (existing["user_id"] or "") != str(bundle_to_store.get("user_id") or ""):
                raise PermissionError("Evidence trace_id is owned by another principal")
            cur.execute(
                f"""
                INSERT INTO evidence_bundles
                  (trace_id, tenant_id, agent_id, user_id, execution_source,
                   schema_version, source_documents_count, evidence_items_count,
                   bundle_json, generated_at, stored_at)
                VALUES ({", ".join([ph] * 11)})
                ON CONFLICT(trace_id) DO UPDATE SET
                  tenant_id=excluded.tenant_id,
                  agent_id=excluded.agent_id,
                  user_id=excluded.user_id,
                  execution_source=excluded.execution_source,
                  schema_version=excluded.schema_version,
                  source_documents_count=excluded.source_documents_count,
                  evidence_items_count=excluded.evidence_items_count,
                  bundle_json=excluded.bundle_json,
                  generated_at=excluded.generated_at,
                  stored_at=excluded.stored_at
                """,
                (
                    trace_id,
                    tenant_id,
                    bundle_to_store.get("agent_id", ""),
                    bundle_to_store.get("user_id", ""),
                    bundle_to_store.get("execution_source", ""),
                    bundle_to_store.get("schema_version", SCHEMA_VERSION),
                    int(bundle_to_store.get("source_documents_count") or len(bundle_to_store.get("documents") or [])),
                    len(items),
                    json.dumps(_strip_private_payloads(bundle_to_store), ensure_ascii=False),
                    bundle_to_store.get("generated_at") or now,
                    now,
                ),
            )
            # Delete child (blobs) before parent (items): Postgres enforces the FK,
            # so the parent-first order the SQLite path tolerated would fail on PG.
            cur.execute(f"DELETE FROM evidence_blobs WHERE trace_id = {ph}", (trace_id,))
            cur.execute(f"DELETE FROM evidence_items WHERE trace_id = {ph}", (trace_id,))

            for item in items:
                evidence_id = str(item.get("evidence_id") or "")
                if not evidence_id:
                    continue
                cur.execute(
                    f"""
                    INSERT INTO evidence_items
                      (evidence_id, trace_id, tenant_id, capture_seq,
                       source_type, artifact_type, source_uri, source_fingerprint,
                       content_hash, content_strategy, display_name, mime_type,
                       metadata_json, provenance_json, extracted_text_json,
                       structured_data_json, highlights_json, content_url, text_url,
                       created_at)
                    VALUES ({", ".join([ph] * 20)})
                    """,
                    (
                        evidence_id,
                        trace_id,
                        tenant_id,
                        int(item.get("capture_seq") or 0),
                        item.get("source_type", ""),
                        item.get("artifact_type", ""),
                        item.get("source_uri", ""),
                        item.get("source_fingerprint", ""),
                        item.get("content_hash", ""),
                        item.get("content_strategy", ""),
                        item.get("display_name", ""),
                        item.get("mime_type", ""),
                        json.dumps(item.get("metadata") or {}, ensure_ascii=False),
                        json.dumps(item.get("provenance") or {}, ensure_ascii=False),
                        json.dumps(item.get("extracted_text") or {}, ensure_ascii=False),
                        json.dumps(item.get("structured_data") or {}, ensure_ascii=False),
                        json.dumps(item.get("highlights") or [], ensure_ascii=False),
                        item.get("content_url", ""),
                        item.get("text_url", ""),
                        now,
                    ),
                )
                payload = item.get("stored_payload")
                if payload is not None:
                    blob = payload if isinstance(payload, bytes) else str(payload).encode("utf-8")
                    cur.execute(
                        f"""
                        INSERT INTO evidence_blobs
                          (evidence_id, trace_id, tenant_id, mime_type, payload, created_at)
                        VALUES ({", ".join([ph] * 6)})
                        """,
                        (evidence_id, trace_id, tenant_id, item.get("mime_type", "text/plain"), blob, now),
                    )

        return {"trace_id": trace_id, "evidence_items_count": len(items)}

    def get_bundle(self, trace_id: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            cur = self._cursor(conn)
            cur.execute(
                f"SELECT bundle_json FROM evidence_bundles WHERE trace_id = {self._ph}",
                (trace_id,),
            )
            row = cur.fetchone()
        if not row:
            return None
        return json.loads(row["bundle_json"])

    def get_item(self, trace_id: str, evidence_id: str) -> dict[str, Any] | None:
        ph = self._ph
        with self._connect() as conn:
            cur = self._cursor(conn)
            cur.execute(
                f"SELECT * FROM evidence_items WHERE trace_id = {ph} AND evidence_id = {ph}",
                (trace_id, evidence_id),
            )
            row = cur.fetchone()
        if not row:
            return None
        return _row_to_item(row)

    def get_blob(self, trace_id: str, evidence_id: str) -> tuple[bytes, str] | None:
        ph = self._ph
        with self._connect() as conn:
            cur = self._cursor(conn)
            cur.execute(
                f"SELECT payload, mime_type FROM evidence_blobs WHERE trace_id = {ph} AND evidence_id = {ph}",
                (trace_id, evidence_id),
            )
            row = cur.fetchone()
        if not row:
            return None
        return bytes(row["payload"]), row["mime_type"] or "application/octet-stream"

    @contextmanager
    def _connect(self):
        """Yield a connection for one logical operation.
        SQLite: a fresh pragma-hardened WAL connection, auto-committed on success
        (byte-identical to the legacy `_conn()` context usage).
        Postgres: a scoped pooled connection with search_path set to the tenant schema;
        the engine commits on clean exit (one transaction per operation)."""
        if self._backend == "postgres":
            with self._engine.connect() as conn:
                conn.cursor().execute(f'SET LOCAL search_path TO "{self._pg_schema}"')
                yield conn
        else:
            conn = sqlite3.connect(self.db_path, timeout=30.0)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA synchronous=NORMAL")
            conn.execute("PRAGMA busy_timeout=30000")
            try:
                yield conn
                conn.commit()
            except Exception:
                conn.rollback()
                raise
            finally:
                conn.close()

    def _init_db(self) -> None:
        if self._backend == "postgres":
            self._init_db_postgres()
            return
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS evidence_bundles (
                    trace_id TEXT PRIMARY KEY,
                    tenant_id TEXT NOT NULL,
                    agent_id TEXT,
                    user_id TEXT,
                    execution_source TEXT,
                    schema_version TEXT,
                    source_documents_count INTEGER DEFAULT 0,
                    evidence_items_count INTEGER DEFAULT 0,
                    bundle_json TEXT NOT NULL,
                    generated_at TEXT,
                    stored_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS evidence_items (
                    evidence_id TEXT PRIMARY KEY,
                    trace_id TEXT NOT NULL,
                    tenant_id TEXT NOT NULL,
                    capture_seq INTEGER DEFAULT 0,
                    source_type TEXT,
                    artifact_type TEXT,
                    source_uri TEXT,
                    source_fingerprint TEXT,
                    content_hash TEXT,
                    content_strategy TEXT,
                    display_name TEXT,
                    mime_type TEXT,
                    metadata_json TEXT,
                    provenance_json TEXT,
                    extracted_text_json TEXT,
                    structured_data_json TEXT,
                    highlights_json TEXT,
                    content_url TEXT,
                    text_url TEXT,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(trace_id) REFERENCES evidence_bundles(trace_id)
                );

                CREATE INDEX IF NOT EXISTS idx_evidence_items_trace
                    ON evidence_items(trace_id);
                CREATE INDEX IF NOT EXISTS idx_evidence_items_source
                    ON evidence_items(tenant_id, source_fingerprint);

                CREATE TABLE IF NOT EXISTS evidence_blobs (
                    evidence_id TEXT PRIMARY KEY,
                    trace_id TEXT NOT NULL,
                    tenant_id TEXT NOT NULL,
                    mime_type TEXT,
                    payload BLOB NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(evidence_id) REFERENCES evidence_items(evidence_id)
                );
                """
            )

    def _init_db_postgres(self) -> None:
        """Create the per-tenant schema + the three evidence tables on Postgres.
        Tables are fully schema-qualified so DDL does not depend on search_path.
        BLOB → BYTEA; everything else maps 1:1 with the SQLite schema."""
        sch = self._pg_schema
        with self._connect() as conn:
            cur = conn.cursor()
            cur.execute(f'CREATE SCHEMA IF NOT EXISTS "{sch}"')
            cur.execute(
                f"""
                CREATE TABLE IF NOT EXISTS "{sch}".evidence_bundles (
                    trace_id TEXT PRIMARY KEY,
                    tenant_id TEXT NOT NULL,
                    agent_id TEXT,
                    user_id TEXT,
                    execution_source TEXT,
                    schema_version TEXT,
                    source_documents_count INTEGER DEFAULT 0,
                    evidence_items_count INTEGER DEFAULT 0,
                    bundle_json TEXT NOT NULL,
                    generated_at TEXT,
                    stored_at TEXT NOT NULL
                )
                """
            )
            cur.execute(
                f"""
                CREATE TABLE IF NOT EXISTS "{sch}".evidence_items (
                    evidence_id TEXT PRIMARY KEY,
                    trace_id TEXT NOT NULL,
                    tenant_id TEXT NOT NULL,
                    capture_seq INTEGER DEFAULT 0,
                    source_type TEXT,
                    artifact_type TEXT,
                    source_uri TEXT,
                    source_fingerprint TEXT,
                    content_hash TEXT,
                    content_strategy TEXT,
                    display_name TEXT,
                    mime_type TEXT,
                    metadata_json TEXT,
                    provenance_json TEXT,
                    extracted_text_json TEXT,
                    structured_data_json TEXT,
                    highlights_json TEXT,
                    content_url TEXT,
                    text_url TEXT,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(trace_id) REFERENCES "{sch}".evidence_bundles(trace_id)
                )
                """
            )
            cur.execute(
                f'CREATE INDEX IF NOT EXISTS idx_evidence_items_trace '
                f'ON "{sch}".evidence_items(trace_id)'
            )
            cur.execute(
                f'CREATE INDEX IF NOT EXISTS idx_evidence_items_source '
                f'ON "{sch}".evidence_items(tenant_id, source_fingerprint)'
            )
            cur.execute(
                f"""
                CREATE TABLE IF NOT EXISTS "{sch}".evidence_blobs (
                    evidence_id TEXT PRIMARY KEY,
                    trace_id TEXT NOT NULL,
                    tenant_id TEXT NOT NULL,
                    mime_type TEXT,
                    payload BYTEA NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(evidence_id) REFERENCES "{sch}".evidence_items(evidence_id)
                )
                """
            )
            conn.commit()


def store_evidence_bundle(bundle: dict[str, Any]) -> dict[str, Any]:
    if not bundle:
        return {}
    return EvidenceStore(str(bundle.get("tenant_id") or TENANT_ID)).store_bundle(bundle)


def get_evidence_bundle(trace_id: str, tenant_id: str = "") -> dict[str, Any] | None:
    return EvidenceStore(tenant_id or TENANT_ID).get_bundle(trace_id)


def get_evidence_item(trace_id: str, evidence_id: str, tenant_id: str = "") -> dict[str, Any] | None:
    return EvidenceStore(tenant_id or TENANT_ID).get_item(trace_id, evidence_id)


def get_evidence_blob(trace_id: str, evidence_id: str, tenant_id: str = "") -> tuple[bytes, str] | None:
    return EvidenceStore(tenant_id or TENANT_ID).get_blob(trace_id, evidence_id)


def _normalize_items(bundle: dict[str, Any]) -> list[dict[str, Any]]:
    items = list(bundle.get("evidence_items") or [])
    if items:
        return items

    trace_id = str(bundle.get("trace_id") or "")
    tenant_id = str(bundle.get("tenant_id") or "")
    agent_id = str(bundle.get("agent_id") or "")
    user_id = str(bundle.get("user_id") or "")
    normalized = []
    for seq, doc in enumerate(bundle.get("documents") or [], start=1):
        reads = doc.get("reads") or []
        # evidence_id: prefer UUID from read record, fall back to doc_id, finally generate one
        evidence_id = (
            (reads[0] or {}).get("evidence_id")
            or doc.get("evidence_id")
            or doc.get("doc_id")
            or str(uuid.uuid4())
        )
        source_uri = doc.get("source_uri", "")
        excerpt = doc.get("excerpt", "")
        urls = _build_evidence_urls(trace_id, evidence_id)
        normalized.append({
            "evidence_id": evidence_id,
            "capture_seq": seq,
            "source_type": doc.get("source_type", "local"),
            "artifact_type": _artifact_from_mime(doc.get("mime_type", "")),
            "source_uri": source_uri,
            "source_fingerprint": doc.get("source_fingerprint", "") or _sha256(source_uri),
            "content_hash": doc.get("content_hash", "") or _sha256(excerpt),
            "content_strategy": "resolve_on_demand",
            "display_name": doc.get("display_name", ""),
            "mime_type": doc.get("mime_type", ""),
            "metadata": {
                "tenant_id": tenant_id,
                "agent_id": agent_id,
                "user_id": user_id,
            },
            "provenance": {"reads": reads},
            "extracted_text": {
                "available": bool(excerpt),
                "excerpt": excerpt,
                "truncated": False,
                "observed_chars": len(excerpt),
            },
            "structured_data": {},
            "highlights": doc.get("highlights", []),
            "content_url": urls["content_url"],
            "text_url": urls["text_url"],
        })
    return normalized


def _row_to_item(row: Any) -> dict[str, Any]:  # sqlite3.Row or psycopg dict_row
    return {
        "evidence_id": row["evidence_id"],
        "trace_id": row["trace_id"],
        "tenant_id": row["tenant_id"],
        "capture_seq": row["capture_seq"],
        "source_type": row["source_type"],
        "artifact_type": row["artifact_type"],
        "source_uri": row["source_uri"],
        "source_fingerprint": row["source_fingerprint"],
        "content_hash": row["content_hash"],
        "content_strategy": row["content_strategy"],
        "display_name": row["display_name"],
        "mime_type": row["mime_type"],
        "metadata": json.loads(row["metadata_json"] or "{}"),
        "provenance": json.loads(row["provenance_json"] or "{}"),
        "extracted_text": json.loads(row["extracted_text_json"] or "{}"),
        "structured_data": json.loads(row["structured_data_json"] or "{}"),
        "highlights": json.loads(row["highlights_json"] or "[]"),
        "content_url": row["content_url"],
        "text_url": row["text_url"],
    }


def _strip_private_payloads(bundle: dict[str, Any]) -> dict[str, Any]:
    clean = dict(bundle)
    clean["evidence_items"] = []
    for item in bundle.get("evidence_items") or []:
        item_copy = dict(item)
        item_copy.pop("stored_payload", None)
        clean["evidence_items"].append(item_copy)
    return clean


def _artifact_from_mime(mime_type: str) -> str:
    if mime_type == "application/pdf":
        return "pdf"
    if (
        mime_type in ("application/msword", "application/vnd.ms-powerpoint")
        or "wordprocessingml" in mime_type
        or "presentationml" in mime_type
    ):
        return "document"
    if mime_type == "application/json":
        return "json"
    if mime_type.startswith("image/"):
        return "image"
    if mime_type.startswith("text/"):
        return "text"
    return "binary"


def _build_evidence_urls(trace_id: str, evidence_id: str) -> dict[str, str]:
    if not trace_id or not evidence_id:
        return {"content_url": "", "text_url": ""}
    base = f"/api/evidence/{trace_id}/items/{evidence_id}"
    return {"content_url": f"{base}/content", "text_url": f"{base}/text"}


def _sha256(value: str) -> str:
    if not value:
        return ""
    return hashlib.sha256(value.encode("utf-8", errors="replace")).hexdigest()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()
