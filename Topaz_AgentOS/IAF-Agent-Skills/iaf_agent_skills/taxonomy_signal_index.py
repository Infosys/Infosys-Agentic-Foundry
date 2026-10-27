"""
TaxonomySignalIndex — embedding-based skill routing from taxonomy files.

Lifecycle:
  Startup  : load() finds taxonomy files via EC.md → splits at L3 sections →
             LLM extracts L5 nodes → embeds embed_text → stores in SQLite.
             Mtime guard skips re-indexing if file unchanged.
  Query    : find_skill(query_embedding, query_text) does in-memory cosine
             + term boost — zero API calls at query time.

Taxonomy file contract (4 rules only):
  1. YAML frontmatter with  name: <L1 domain>
  2. ### heading for each L2 process area
  3. #### heading for each L3 subprocess
  4. <!-- skill: <name> --> on the line immediately after each #### heading

Everything inside an L3 section (L4, L5, tables, bullets, prose) is handled
by the LLM — no rigid structure required.
"""

import json
import logging
import os
import re
import sqlite3
import struct
import threading
from pathlib import Path
try:
    from .sqlite_util import connect as _sqlite_connect
except ImportError:
    from sqlite_util import connect as _sqlite_connect
from typing import Callable, List, Optional

import os
from contextlib import contextmanager

import yaml

try:
    from .sqlite_util import connect as _sqlite_connect
except ImportError:
    from sqlite_util import connect as _sqlite_connect

logger = logging.getLogger(__name__)

_TSI_REG_GUARD = threading.Lock()
_TSI_WRITE_LOCKS: dict = {}
_TSI_SCHEMA_READY: set = set()


def _tsi_write_lock(key: str) -> threading.Lock:
    """Return the process-wide write lock for a storage key (created on first use)."""
    with _TSI_REG_GUARD:
        lk = _TSI_WRITE_LOCKS.get(key)
        if lk is None:
            lk = threading.Lock()
            _TSI_WRITE_LOCKS[key] = lk
        return lk



COSINE_CLEAR    = 0.65   # confident hit — return immediately
COSINE_FUZZY_LO = 0.45   # below this — don't attempt term boost
TERM_BOOST_PER  = 0.12   # score added per shared exact token
TERM_BOOST_CAP  = 3      # max tokens counted (max boost = 0.36)

SCHEMA = """
CREATE TABLE IF NOT EXISTS taxonomy_signal_index (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    node_id       TEXT NOT NULL UNIQUE,
    embed_text    TEXT NOT NULL,
    skill         TEXT NOT NULL,
    context_files TEXT,
    embedding     BLOB,
    src_file      TEXT,
    src_mtime     REAL
);
CREATE INDEX IF NOT EXISTS idx_tsi_skill   ON taxonomy_signal_index(skill);
CREATE INDEX IF NOT EXISTS idx_tsi_src     ON taxonomy_signal_index(src_file);
"""

# Postgres DDL for the same table (AUTOINCREMENT→IDENTITY, BLOB→BYTEA, REAL→DOUBLE PRECISION).
# Applied per-statement (Postgres has no executescript). Lives in the agent's kn_* schema.
SCHEMA_PG = [
    """CREATE TABLE IF NOT EXISTS taxonomy_signal_index (
        id            BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
        node_id       TEXT NOT NULL UNIQUE,
        embed_text    TEXT NOT NULL,
        skill         TEXT NOT NULL,
        context_files TEXT,
        embedding     BYTEA,
        src_file      TEXT,
        src_mtime     DOUBLE PRECISION
    )""",
    "CREATE INDEX IF NOT EXISTS idx_tsi_skill ON taxonomy_signal_index(skill)",
    "CREATE INDEX IF NOT EXISTS idx_tsi_src   ON taxonomy_signal_index(src_file)",
]

EXTRACT_PROMPT = """\
You are extracting leaf-level activities from ONE section of a domain taxonomy.

Context (pre-filled — do not re-derive):
  L1    : {l1}
  L2    : {l2}
  L3    : {l3}
  Skill : {skill_instruction}

For EVERY leaf activity in the section below return one JSON object:
{{
  "embed_text":    "<full path> — <description>",
  "skill":         "<skill>",
  "context_files": ["<file.md>", ...]
}}

Rules:
- embed_text MUST start with "{l1} > {l2} > {l3} > "
- Include L4 in the path only when it disambiguates similar activity names:
  "{l1} > {l2} > {l3} > <L4 name> > <activity> — <description>"
  Otherwise: "{l1} > {l2} > {l3} > <activity> — <description>"
- skill MUST be one of: {valid_skills}
- Extract EVERY activity row — tables, bullets, numbered lists, prose — leave nothing out
- context_files: collect .md filenames from blockquote lines like
  "> _Exceptions:_ `fa_exceptions.md`" near this section ([] if none found)
- Return a flat JSON array only — no explanation, no markdown fences

Section content:
---
{content}
---

JSON array:\
"""



class TaxonomySignalIndex:

    def __init__(
        self,
        ec_path: str,
        db_path: str,
        llm,
        skills_path: str,
        embedding_fn: Optional[Callable[[str], Optional[List[float]]]] = None,
    ):
        """
        Args:
            ec_path:      Absolute path to Enterprise_Context.md
            db_path:      Absolute path to knowledge_index.db
            llm:          LangChain LLM instance (same one agent uses)
            skills_path:  Path to skills folder containing _index.yaml
            embedding_fn: Callable(text) -> list[float] | None
                          Pass knowledge_indexer._safe_get_embedding
        """
        self.ec_path      = Path(ec_path)
        self.db_path      = Path(db_path)
        self.llm          = llm
        self.skills_path  = Path(skills_path)
        self.embedding_fn = embedding_fn
        self._nodes: List[dict] = []        # in-memory list for query-time cosine
        self._ready       = threading.Event()  # set when load() completes
        self._loading     = False

        # Backend seam (mirrors KnowledgeIndexer): SQLite by default; Postgres when
        # KNOWLEDGE_BACKEND=postgres, in the agent's per-agent schema (kn_<tenant>_<agent>).
        try:
            from .knowledge_indexer import _resolve_knowledge_backend
        except ImportError:
            from knowledge_indexer import _resolve_knowledge_backend
        self._kbackend = _resolve_knowledge_backend()
        self._ph = "%s" if self._kbackend == "postgres" else "?"
        self._engine = None
        self._pg_schema = None
        if self._kbackend == "postgres":
            try:
                from .storage.engine import get_engine
            except ImportError:
                from storage.engine import get_engine
            self._engine = get_engine()
            self._pg_schema = self._derive_pg_schema()

        # Storage key for process-wide write serialization: the Postgres schema
        # (shared table per agent) or the SQLite db path.
        self._lock_key = self._pg_schema if self._kbackend == "postgres" else str(self.db_path)

    def _derive_pg_schema(self) -> str:
        """Per-agent Postgres schema `kn_<tenant>_<agent>` from db_path — identical to
        KnowledgeIndexer so the taxonomy table co-locates. Overridable via KNOWLEDGE_PG_SCHEMA."""
        import re
        override = os.getenv("KNOWLEDGE_PG_SCHEMA")
        if override:
            raw = override
        else:
            try:
                agent = self.db_path.parent.parent.name           # memory → <agent>
                tenant = self.db_path.parent.parent.parent.parent.name  # → <tenant>
                raw = f"kn_{tenant}_{agent}"
            except Exception:
                raw = "kn_default"
        return re.sub(r"[^a-zA-Z0-9_]", "_", raw).lower()[:63]

    @contextmanager
    def _connect(self):
        """Yield a connection for one operation. SQLite: per-op file connect (unchanged).
        Postgres: scoped pooled connection with search_path set to the agent schema."""
        if self._kbackend == "postgres":
            with self._engine.connect() as conn:
                conn.cursor().execute(f'SET LOCAL search_path TO "{self._pg_schema}"')
                yield conn
        else:
            with _sqlite_connect(self.db_path) as conn:
                yield conn


    def load(self) -> None:
        """
        Starts background indexing thread. Returns immediately — agent startup
        is not blocked. find_skill() works as soon as the thread finishes;
        returns None harmlessly while the thread is still running.
        """
        if self._loading:
            return
        self._loading = True
        t = threading.Thread(target=self._load_worker, daemon=True, name="TaxonomySignalIndex")
        t.start()
        logger.info("TaxonomySignalIndex: background indexing started")

    def _load_worker(self) -> None:
        """Background thread — builds or refreshes the index, then sets _ready."""
        try:
            self._ensure_schema()
            valid_skills = self._load_valid_skills()
            if not valid_skills:
                logger.warning("TaxonomySignalIndex: no skills in _index.yaml — aborting")
                return

            taxonomy_files = self._get_taxonomy_files_from_ec()
            if not taxonomy_files:
                logger.info("TaxonomySignalIndex: no taxonomy files found in EC.md — skipping")
                return

            for tf in taxonomy_files:
                self._refresh_if_stale(tf, valid_skills)

            self._load_into_memory()
            logger.info(
                "TaxonomySignalIndex: ready — %d nodes from %d file(s)",
                len(self._nodes), len(taxonomy_files)
            )
        except Exception as e:
            logger.warning("TaxonomySignalIndex background load failed (non-fatal): %s", e)
        finally:
            self._ready.set()   # always signal done, even on failure

    def find_skill(
        self,
        query_embedding: List[float],
        query_text: str = "",
    ) -> Optional[dict]:
        """
        Cosine + term-boost match against all indexed L5 nodes.

        Returns:
            {skill, embed_text, context_files, score, method}  or  None
        """
        if not self._ready.is_set():
            logger.debug("TaxonomySignalIndex: still loading — skipping lookup")
            return None
        if not self._nodes or not query_embedding:
            return None
        try:
            scored = [
                (_cosine(query_embedding, n["embedding"]), n)
                for n in self._nodes
            ]
            scored.sort(key=lambda x: x[0], reverse=True)

            best_score, best_node = scored[0]

            if best_score >= COSINE_CLEAR:
                return self._result(best_node, best_score, "cosine")

            # Uncertain zone — term boost on top 3
            if best_score >= COSINE_FUZZY_LO and query_text:
                for score, node in scored[:3]:
                    boosted = score + _term_boost(query_text, node["embed_text"])
                    if boosted >= COSINE_CLEAR:
                        return self._result(node, boosted, "cosine+term")

            logger.debug(
                "TaxonomySignalIndex: no hit (best=%.3f threshold=%.2f)",
                best_score, COSINE_CLEAR
            )
            return None

        except Exception as e:
            logger.warning("TaxonomySignalIndex.find_skill() failed (non-fatal): %s", e)
            return None

    def find_skills(
        self,
        query_embedding: List[float],
        query_text: str = "",
        top_k: int = 5,
        min_score: float = 0.55,
    ) -> List[dict]:
        """
        Multi-hit variant of find_skill(). Returns top-N matches deduped by skill.

        Used for multi-domain detection: if the returned list contains 2+ distinct
        skills, the query likely spans multiple domains and should trigger the
        orchestrator/planner instead of a single-skill ReAct loop.

        Returns:
            List of {skill, embed_text, context_files, score, method}, best first.
            Empty list if nothing above min_score.
        """
        if not self._ready.is_set() or not self._nodes or not query_embedding:
            return []
        try:
            # Score every node
            scored = [
                (_cosine(query_embedding, n["embedding"]), n)
                for n in self._nodes
            ]

            # Apply term boost where applicable
            if query_text:
                scored = [
                    (s + _term_boost(query_text, n["embed_text"]), n)
                    for s, n in scored
                ]

            scored = [(s, n) for s, n in scored if s >= min_score]
            scored.sort(key=lambda x: x[0], reverse=True)

            # Deduplicate by skill — keep only the best-scoring node per skill
            seen_skills: dict = {}  # skill -> (score, node)
            for score, node in scored:
                sk = node["skill"]
                if sk not in seen_skills or score > seen_skills[sk][0]:
                    seen_skills[sk] = (score, node)

            # Sort deduped results by score, cap at top_k
            deduped = sorted(seen_skills.values(), key=lambda x: x[0], reverse=True)[:top_k]

            results = [self._result(node, score, "cosine+term" if query_text else "cosine")
                       for score, node in deduped]

            if results:
                logger.info(
                    "TaxonomySignalIndex: find_skills() returned %d hits — skills=%s",
                    len(results), [r["skill"] for r in results]
                )
            return results

        except Exception as e:
            logger.warning("TaxonomySignalIndex.find_skills() failed (non-fatal): %s", e)
            return []



    def _ensure_schema(self) -> None:
        key = self._lock_key
        if key in _TSI_SCHEMA_READY:
            return
        with _tsi_write_lock(key):
            if key in _TSI_SCHEMA_READY:
                return
            with self._connect() as conn:
                if self._kbackend == "postgres":
                    cur = conn.cursor()
                    cur.execute("SET LOCAL lock_timeout = '5s'")
                    cur.execute(f'CREATE SCHEMA IF NOT EXISTS "{self._pg_schema}"')
                    for stmt in SCHEMA_PG:
                        cur.execute(stmt)
                    conn.commit()
                else:
                    conn.executescript(SCHEMA)
            _TSI_SCHEMA_READY.add(key)

    def _load_valid_skills(self) -> List[str]:
        """Read skill names from _index.yaml — ground truth."""
        index_path = self.skills_path / "_index.yaml"
        if not index_path.exists():
            return []
        try:
            data = yaml.safe_load(index_path.read_text(encoding="utf-8")) or {}
            return list(data.get("skills", {}).keys())
        except Exception as e:
            logger.warning("TaxonomySignalIndex: could not read _index.yaml: %s", e)
            return []

    def _get_taxonomy_files_from_ec(self) -> List[Path]:
        """
        Find taxonomy file paths from Enterprise_Context.md.
        Merges BOTH registration forms: the YAML frontmatter `taxonomy:` list and
        the body references to contexts/taxonomy/*.md. Scanning both (rather than
        using the frontmatter list and only falling back to the body when it is
        empty) means a taxonomy registered in one form isn't hidden by the presence
        of the other — e.g. a body-appended entry is still discovered when the
        frontmatter already lists some taxonomies.
        """
        if not self.ec_path.exists():
            logger.warning("TaxonomySignalIndex: EC.md not found at %s", self.ec_path)
            return []

        ec_dir   = self.ec_path.parent
        content  = self.ec_path.read_text(encoding="utf-8")
        found    = set()

        # Frontmatter taxonomy list
        fm = _parse_frontmatter(content)
        for rel in (fm.get("taxonomy") or []):
            p = (ec_dir / rel).resolve()
            if p.exists():
                found.add(p)

        # Body references to contexts/taxonomy/*.md (always scanned, not just as a
        # fallback) so both forms are honoured.
        for m in re.finditer(r'`?(contexts/taxonomy/[^`|\s]+\.md)`?', content):
            p = (ec_dir / m.group(1)).resolve()
            if p.exists():
                found.add(p)

        return sorted(found)

    def _refresh_if_stale(self, taxonomy_path: Path, valid_skills: List[str]) -> None:
        """Re-index this taxonomy file if it changed since last run.

        The whole refresh is serialized per storage key so that when many agent
        workers start at once (cold start / shared schema) only ONE rebuilds a given
        file — the rest re-check the mtime under the lock and return. This both avoids
        the concurrent-writer lock pileup and prevents a duplicate LLM-extraction storm.
        The slow LLM/embedding work holds only this in-process lock, never a DB
        connection.
        """
        mtime_now = taxonomy_path.stat().st_mtime

        with _tsi_write_lock(self._lock_key):
            with self._connect() as conn:
                row = conn.cursor().execute(
                    f"SELECT src_mtime FROM taxonomy_signal_index WHERE src_file={self._ph} LIMIT 1",
                    (str(taxonomy_path),)
                ).fetchone()

            if row and abs(row[0] - mtime_now) < 1.0:
                logger.debug("TaxonomySignalIndex: %s unchanged — using cache", taxonomy_path.name)
                return

            logger.info("TaxonomySignalIndex: (re)indexing %s", taxonomy_path.name)
            self._refresh_locked(taxonomy_path, valid_skills, mtime_now)

    def _refresh_locked(self, taxonomy_path: Path, valid_skills: List[str], mtime_now: float) -> None:
        """Body of _refresh_if_stale — runs while the per-key write lock is held."""
        sections = _parse_file(taxonomy_path)
        if not sections:
            logger.warning("TaxonomySignalIndex: no L3 sections found in %s", taxonomy_path.name)
            return

        all_nodes: List[dict] = []
        for section in sections:
            nodes = self._extract_nodes_via_llm(section, valid_skills)
            all_nodes.extend(nodes)

        if not all_nodes:
            logger.warning("TaxonomySignalIndex: LLM returned 0 nodes for %s", taxonomy_path.name)
            return

        self._embed_and_store(all_nodes, taxonomy_path, mtime_now)

    def _extract_nodes_via_llm(self, section: dict, valid_skills: List[str]) -> List[dict]:
        """
        Send one L3 section to the LLM. Returns list of validated node dicts.
        Each node has: embed_text, skill, context_files.
        """
        skill = section.get("skill")
        if skill:
            skill_instruction = f'"{skill}" (explicitly tagged — use this value)'
        else:
            skill_instruction = (
                f"UNKNOWN — infer from the section content. "
                f"MUST be one of: {', '.join(valid_skills)}"
            )

        prompt = EXTRACT_PROMPT.format(
            l1                 = section["l1"],
            l2                 = section["l2"],
            l3                 = section["l3"],
            skill_instruction  = skill_instruction,
            valid_skills       = ", ".join(f'"{s}"' for s in valid_skills),
            content            = section["content"],
        )

        try:
            response = self.llm.invoke(prompt)
            raw = response.content.strip()

            # Strip markdown fences if LLM wraps output
            raw = re.sub(r"^```[a-z]*\n?", "", raw)
            raw = re.sub(r"\n?```$", "", raw.strip())

            nodes = json.loads(raw.strip())
            if not isinstance(nodes, list):
                raise ValueError(f"Expected JSON array, got {type(nodes)}")

        except json.JSONDecodeError as e:
            logger.warning(
                "TaxonomySignalIndex: JSON parse failed for L3=%s (%s) — skipping section",
                section["l3"], e
            )
            return []
        except Exception as e:
            logger.warning(
                "TaxonomySignalIndex: LLM call failed for L3=%s (%s) — skipping section",
                section["l3"], e
            )
            return []

        valid_set = set(valid_skills)
        validated = []
        for node in nodes:
            node_skill = (node.get("skill") or "").strip()
            if node_skill not in valid_set:
                logger.warning(
                    "TaxonomySignalIndex: dropped node with invalid skill '%s' in L3=%s",
                    node_skill, section["l3"]
                )
                continue
            embed_text = (node.get("embed_text") or "").strip()
            if not embed_text:
                continue
            validated.append({
                "embed_text":    embed_text,
                "skill":         node_skill,
                "context_files": node.get("context_files") or [],
            })

        logger.info(
            "TaxonomySignalIndex: L3=%s → %d/%d nodes valid",
            section["l3"], len(validated), len(nodes)
        )

        # Warn if this L3 had no skill tag — author should add one
        if not section.get("skill"):
            logger.warning(
                "TaxonomySignalIndex: L3 section '%s' in %s has no <!-- skill: --> tag — "
                "LLM inferred skill. Add the tag to make this explicit.",
                section["l3"], section.get("src_file", "")
            )

        return validated

    def _embed_and_store(
        self,
        nodes: List[dict],
        src_path: Path,
        mtime: float,
    ) -> None:
        """Embed each node, then write them in one short transaction.

        Embeddings (a slow, possibly network-bound call) are computed BEFORE any DB
        connection is opened — never inside the transaction. Holding a write
        transaction open across per-node embedding calls is what left a connection
        `idle in transaction` clutching RowExclusiveLock on the table and stalled the
        whole Postgres pool. Callers hold the per-key write lock, so the DELETE +
        bulk INSERT below is the only DB work and completes quickly.
        """
        ph = self._ph

        # 1) Compute all embeddings up front (NO DB connection held here).
        rows_to_write = []
        for node in nodes:
            embed_text    = node["embed_text"]
            node_id       = embed_text[:200]   # truncated slug
            embedding_blob = None
            if self.embedding_fn:
                try:
                    vec = self.embedding_fn(embed_text)
                    if vec:
                        embedding_blob = _pack(vec)
                except Exception as emb_err:
                    logger.debug(
                        "TaxonomySignalIndex: embed failed for '%s': %s",
                        embed_text[:60], emb_err
                    )
            rows_to_write.append((
                node_id,
                embed_text,
                node["skill"],
                json.dumps(node["context_files"]),
                embedding_blob,
                str(src_path),
                mtime,
            ))

        if self._kbackend == "postgres":
            insert_sql = (
                "INSERT INTO taxonomy_signal_index "
                "(node_id, embed_text, skill, context_files, embedding, src_file, src_mtime) "
                f"VALUES ({ph}, {ph}, {ph}, {ph}, {ph}, {ph}, {ph}) "
                "ON CONFLICT (node_id) DO UPDATE SET "
                "embed_text=excluded.embed_text, skill=excluded.skill, "
                "context_files=excluded.context_files, embedding=excluded.embedding, "
                "src_file=excluded.src_file, src_mtime=excluded.src_mtime"
            )
        else:
            insert_sql = (
                "INSERT OR REPLACE INTO taxonomy_signal_index "
                "(node_id, embed_text, skill, context_files, embedding, src_file, src_mtime) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)"
            )

        # 2) Short write transaction: DELETE stale rows + bulk INSERT. A lock_timeout
        #    on Postgres means we fail fast rather than hanging 30s if ever contended.
        with self._connect() as conn:
            cur = conn.cursor()
            if self._kbackend == "postgres":
                cur.execute("SET LOCAL lock_timeout = '5s'")
            cur.execute(
                f"DELETE FROM taxonomy_signal_index WHERE src_file={ph}",
                (str(src_path),)
            )
            if rows_to_write:
                cur.executemany(insert_sql, rows_to_write)
            conn.commit()

        logger.info(
            "TaxonomySignalIndex: stored %d/%d nodes from %s",
            len(rows_to_write), len(nodes), src_path.name
        )

    def _load_into_memory(self) -> None:
        """Load all embedded rows from the DB into _nodes list for fast cosine.

        Rows whose source .md no longer exists are skipped, so a deleted taxonomy
        can never be routed to even if a late background extraction re-inserted its
        rows after the delete purge (the evict+rebuild refreshes only files still
        referenced in EC.md, so stale rows can otherwise survive)."""
        self._nodes = []
        with self._connect() as conn:
            rows = conn.cursor().execute(
                """
                SELECT embed_text, skill, context_files, embedding, src_file
                FROM   taxonomy_signal_index
                WHERE  embedding IS NOT NULL
                """
            ).fetchall()

        _exists_cache: dict = {}
        def _src_exists(p) -> bool:
            if p not in _exists_cache:
                try:
                    _exists_cache[p] = bool(p) and Path(p).exists()
                except Exception:
                    _exists_cache[p] = False
            return _exists_cache[p]

        for embed_text, skill, ctx_json, emb_blob, src_file in rows:
            if not _src_exists(src_file):
                continue
            try:
                vec = _unpack(emb_blob)
                ctx = json.loads(ctx_json or "[]")
            except Exception:
                continue
            self._nodes.append({
                "embed_text":    embed_text,
                "skill":         skill,
                "context_files": ctx,
                "embedding":     vec,
            })


    def _result(self, node: dict, score: float, method: str) -> dict:
        logger.info(
            "TaxonomySignalIndex: %s hit — skill=%s score=%.3f text='%s'",
            method, node["skill"], score, node["embed_text"][:80]
        )
        return {
            "skill":         node["skill"],
            "embed_text":    node["embed_text"],
            "context_files": node["context_files"],
            "score":         score,
            "method":        method,
        }



def _parse_file(taxonomy_path: Path) -> List[dict]:
    """
    Parse a taxonomy markdown file into a list of L3 section dicts.

    Each dict:
        l1, l2, l3  — hierarchy labels
        skill       — from <!-- skill: xxx --> tag, or None if missing
        content     — raw section text (passed to LLM)
        src_file    — source file path string

    Only structural anchors are read by code:
        - YAML frontmatter  → l1
        - ### heading       → current l2
        - #### heading      → l3 boundary
        - <!-- skill: -->   → skill assignment
    Everything inside a section is left for the LLM.
    """
    content  = taxonomy_path.read_text(encoding="utf-8")
    src_str  = str(taxonomy_path)

    # L1 from YAML frontmatter
    fm = _parse_frontmatter(content)
    l1 = (fm.get("name") or "").strip()

    sections: List[dict] = []
    current_l2   = ""
    current_l3   = None
    current_skill= None
    section_lines: List[str] = []

    def flush_section():
        if current_l3 and section_lines:
            sections.append({
                "l1":      l1,
                "l2":      current_l2,
                "l3":      current_l3,
                "skill":   current_skill,
                "content": "\n".join(section_lines),
                "src_file": src_str,
            })

    lines = content.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i]

        if re.match(r'^###\s+(?!#)', line):
            flush_section()
            current_l3    = None
            current_skill = None
            section_lines = []
            # Strip heading markers and inline code/tags for clean l2 name
            current_l2 = re.sub(r'^#{2,4}\s+', '', line)
            current_l2 = re.sub(r'`[^`]*`', '', current_l2).strip()
            # Remove "L2: " prefix if present
            current_l2 = re.sub(r'^L\d+:\s*', '', current_l2).strip()
            # Remove parenthetical suffixes like "(PtP)", "(OtC)"
            current_l2 = re.sub(r'\s*\([^)]*\)\s*$', '', current_l2).strip()
            i += 1
            continue

        if re.match(r'^####\s+(?!#)', line):
            flush_section()
            section_lines = [line]
            l3_raw = re.sub(r'^#{4}\s+', '', line)
            l3_raw = re.sub(r'`[^`]*`', '', l3_raw).strip()
            l3_raw = re.sub(r'^L\d+:\s*', '', l3_raw).strip()
            current_l3    = l3_raw
            current_skill = None

            # Peek at next line for skill tag
            if i + 1 < len(lines):
                next_line = lines[i + 1]
                m = re.search(r'<!--\s*skill:\s*(\S+?)\s*-->', next_line)
                if m:
                    current_skill = m.group(1)
                    i += 1          # consume the skill tag line
                    section_lines.append(lines[i])

            i += 1
            continue

        # All other lines — accumulate into current section
        if current_l3 is not None:
            section_lines.append(line)

        i += 1

    flush_section()   # capture last section
    return sections


def _parse_frontmatter(content: str) -> dict:
    """Extract YAML frontmatter from markdown content. Returns {} if none."""
    m = re.match(r'^---\s*\n(.*?)\n---\s*\n', content, re.DOTALL)
    if not m:
        return {}
    try:
        return yaml.safe_load(m.group(1)) or {}
    except Exception:
        return {}



def _pack(vec: List[float]) -> bytes:
    return struct.pack(f"{len(vec)}f", *vec)


def _unpack(blob: bytes) -> List[float]:
    blob = bytes(blob)  # psycopg returns memoryview on Postgres; struct wants bytes
    n = len(blob) // 4
    return list(struct.unpack(f"{n}f", blob))


def _cosine(a: List[float], b: List[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na  = sum(x * x for x in a) ** 0.5
    nb  = sum(x * x for x in b) ** 0.5
    if na == 0.0 or nb == 0.0:
        return 0.0
    return dot / (na * nb)


def _term_boost(query: str, embed_text: str) -> float:
    """
    Boost score when query contains exact tokens that appear in embed_text.
    Targets technical jargon (CrashLoopBackOff, GR/IR, DPO) that may score
    borderline on cosine alone.
    Only tokens of 4+ characters are counted to avoid noise from stop words.
    """
    q_tokens = set(re.findall(r'\b\w{4,}\b', query.lower()))
    e_tokens = set(re.findall(r'\b\w{4,}\b', embed_text.lower()))
    overlap  = len(q_tokens & e_tokens)
    return TERM_BOOST_PER * min(overlap, TERM_BOOST_CAP)
