"""
EntityGuideSeeder — seeds entity_registry from entity_guide.md at startup.

Reads the entity guide markdown file, parses every entity table, and
registers each entity with its aliases into the SQLite entity_registry.

Mtime-guarded: stores the file's mtime in a small SQLite table inside the
existing knowledge_index.db. On next startup the mtime is compared — if the
file has not changed the seed step is skipped entirely (~0ms). Re-seeding
triggers automatically whenever the file is edited and the server restarted.

Runs in a background daemon thread so agent startup is not blocked.
All errors are non-fatal — worst case the registry stays empty and the
query_memory xref path falls through to semantic search as before.
"""

import logging
import re
import threading
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


_SEED_TABLE_DDL = """
CREATE TABLE IF NOT EXISTS entity_guide_seed (
    src_file     TEXT PRIMARY KEY,
    src_mtime    REAL NOT NULL,
    entity_count INTEGER DEFAULT 0
)
"""


def _slugify(name: str) -> str:
    """
    Convert a display name to a canonical node_id slug.
    "Northfield Foods Corporation" → "entity:northfield_foods_corporation"
    """
    slug = name.lower().strip()
    slug = re.sub(r"[^\w\s-]", "", slug)   # strip punctuation except hyphen
    slug = re.sub(r"[\s-]+", "_", slug)     # spaces and hyphens → underscore
    slug = re.sub(r"_+", "_", slug).strip("_")
    return f"entity:{slug}"


def _parse_entity_guide(path: Path) -> List[Dict[str, Any]]:
    """
    Parse all markdown tables in entity_guide.md.

    Expected column names (case-insensitive):
      "Canonical Name" | "Aliases" | "Entity Type" | "Skill"

    Returns list of dicts ready to pass to entity_registry.register_entity().
    """
    text = path.read_text(encoding="utf-8")
    entities: List[Dict[str, Any]] = []

    current_headers: List[str] = []

    for raw_line in text.splitlines():
        line = raw_line.strip()

        # Only process markdown table rows
        if not line.startswith("|") or not line.endswith("|"):
            current_headers = []
            continue

        if re.match(r"^\|[\s\-|:]+\|$", line):
            continue

        cells = [c.strip() for c in line.strip("|").split("|")]

        # Detect header row by looking for known column name in first few cells
        lower_cells = [c.lower() for c in cells]
        if any("canonical" in c or "entity name" in c for c in lower_cells[:3]):
            current_headers = lower_cells
            continue

        if not current_headers:
            continue

        # Map cells to headers (zip stops at shorter list)
        row = dict(zip(current_headers, cells))

        # Pull canonical name — required
        canonical = (
            row.get("canonical name")
            or row.get("entity name")
            or row.get("name", "")
        ).strip()

        if not canonical or re.match(r"^[-:]+$", canonical):
            continue

        # Pull aliases — comma-separated string
        aliases_raw = row.get("aliases", "")
        aliases = [
            a.strip()
            for a in aliases_raw.split(",")
            if a.strip() and a.strip() != canonical
        ]
        # Always include the canonical name itself so exact-string lookup works
        aliases = [canonical] + aliases

        # Entity type — store as metadata, not used for node_type (always ENTITY)
        entity_type = row.get("entity type", "").strip() or None

        # Skill — take first if multiple ("fa_ap, fa_gl" → "fa_ap")
        skill_raw = row.get("skill", "").strip()
        skill_name = skill_raw.split(",")[0].strip() if skill_raw else None

        node_id = _slugify(canonical)

        entities.append({
            "node_id":      node_id,
            "display_name": canonical,
            "node_type":    "ENTITY",
            "aliases":      aliases,
            "skill_name":   skill_name,
            "metadata":     {"entity_type": entity_type} if entity_type else {},
        })

    return entities


def _resolve_ref(ref: str) -> str:
    """Resolve a From/To cell to a node_id.

    Authors may write either a full node_id ("entity:northfield_foods_corporation",
    "process:period_close") or a display name ("Northfield Foods Corporation"). A value
    that already contains ':' is treated as a node_id; otherwise it is slugified
    to ``entity:<slug>`` to match the entity rows seeded from the same file.
    """
    ref = ref.strip()
    if not ref:
        return ref
    if ":" in ref:
        return ref
    return _slugify(ref)


def _parse_relationships(path: Path) -> List[Dict[str, Any]]:
    """Parse an optional 'Relationships' markdown table into world-model edges.

    Expected columns (case-insensitive): From | Relation | To | Condition | Note
    'From'/'To' accept a node_id or a display name (see ``_resolve_ref``). A header
    row is recognised only when it contains both a 'from' and a 'to' column plus a
    'relation' column — so it never collides with the entity tables.

    Returns dicts ready for ``entity_registry.upsert_relationship()``.
    """
    text = path.read_text(encoding="utf-8")
    edges: List[Dict[str, Any]] = []
    headers: List[str] = []

    for raw_line in text.splitlines():
        line = raw_line.strip()

        if not line.startswith("|") or not line.endswith("|"):
            headers = []
            continue

        if re.match(r"^\|[\s\-|:]+\|$", line):
            continue

        cells = [c.strip() for c in line.strip("|").split("|")]
        lower = [c.lower() for c in cells]

        # Relationship header: must have from + to + a relation column
        if "from" in lower and "to" in lower and any("relation" in c for c in lower):
            headers = lower
            continue

        if not headers:
            continue

        row = dict(zip(headers, cells))
        frm = (row.get("from") or "").strip()
        rel = (row.get("relation") or row.get("relationship") or "").strip()
        to = (row.get("to") or "").strip()
        if not frm or not rel or not to:
            continue
        cond = (row.get("condition") or "").strip() or None
        note = (row.get("note") or row.get("notes") or "").strip()

        edges.append({
            "from_node": _resolve_ref(frm),
            "relation":  rel,
            "to_node":   _resolve_ref(to),
            "condition": cond,
            "metadata":  {"note": note} if note else {},
        })

    return edges



class EntityGuideSeeder:
    """
    Seeds entity_registry from entity_guide.md at server startup.

    Usage (mirrors TaxonomySignalIndex):
        seeder = EntityGuideSeeder(guide_path, entity_registry, db_path)
        seeder.load()   # returns immediately; seeding runs in background
    """

    def __init__(
        self,
        guide_path: str,
        entity_registry: Any,
        db_path: str,
    ) -> None:
        self.guide_path      = Path(guide_path)
        self.entity_registry = entity_registry
        self.db_path         = Path(db_path)
        # Route all DB work through the entity_registry's backend-agnostic seam so we
        # never open a competing handle, and so it works on SQLite *and* Postgres.
        self._connect        = getattr(entity_registry, '_connect', None)
        self._ph             = getattr(entity_registry, '_ph', '?')
        self._kbackend       = getattr(entity_registry, '_kbackend', 'sqlite')
        self._ready          = threading.Event()


    def load(self) -> None:
        """Start background seeding thread. Returns immediately."""
        t = threading.Thread(
            target=self._seed_worker,
            daemon=True,
            name="EntityGuideSeeder",
        )
        t.start()
        logger.info("EntityGuideSeeder: background seed started for %s", self.guide_path.name)


    def _ensure_schema(self) -> None:
        with self._connect() as conn:
            conn.execute(_SEED_TABLE_DDL)
            conn.commit()

    def _get_cached_mtime(self) -> Optional[float]:
        try:
            with self._connect() as conn:
                row = conn.execute(
                    f"SELECT src_mtime, entity_count FROM entity_guide_seed WHERE src_file={self._ph}",
                    (str(self.guide_path),),
                ).fetchone()
            return row if row else None
        except Exception:
            return None

    def _save_mtime(self, mtime: float, entity_count: int) -> None:
        with self._connect() as conn:
            if self._kbackend == "postgres":
                conn.execute(
                    f"INSERT INTO entity_guide_seed (src_file, src_mtime, entity_count)"
                    f" VALUES ({self._ph}, {self._ph}, {self._ph})"
                    f" ON CONFLICT (src_file) DO UPDATE SET"
                    f" src_mtime = excluded.src_mtime, entity_count = excluded.entity_count",
                    (str(self.guide_path), mtime, entity_count),
                )
            else:
                conn.execute(
                    "INSERT OR REPLACE INTO entity_guide_seed (src_file, src_mtime, entity_count)"
                    " VALUES (?, ?, ?)",
                    (str(self.guide_path), mtime, entity_count),
                )
            conn.commit()

    def _purge_fragments(self, seeded_entities: List[Dict[str, Any]]) -> None:
        """
        After seeding, remove any fragment entities whose display_name or any
        alias appears in a seeded canonical's alias set (case-insensitive).

        For each fragment found:
          1. Re-point entity_xref rows to the canonical node_id.
          2. Delete the fragment from entity_registry and fts_entities.
        """
        import json as _json

        if self._connect is None:
            return

        # Build lookup: alias_lower → canonical node_id
        alias_to_canonical: Dict[str, str] = {}
        for ent in seeded_entities:
            for alias in ent.get("aliases", []):
                alias_to_canonical[alias.lower()] = ent["node_id"]

        canonical_ids = {ent["node_id"] for ent in seeded_entities}
        purged = 0

        with self._connect() as conn:
            try:
                rows = conn.execute(
                    "SELECT node_id, display_name, aliases_json FROM entity_registry"
                    " WHERE node_type IN ('ENTITY', 'ENTITY_TYPE')"
                ).fetchall()
            except Exception as _e:
                logger.debug("EntityGuideSeeder._purge_fragments: scan failed: %s", _e)
                return

            for node_id, display_name, aliases_str in rows:
                if node_id in canonical_ids:
                    continue  # never delete a canonical

                try:
                    stored_aliases: List[str] = _json.loads(aliases_str) if aliases_str else []
                except Exception:
                    stored_aliases = []

                # Check if display_name or any alias collides with a canonical's aliases
                candidate_strings = [display_name] + stored_aliases
                target_canonical = None
                for s in candidate_strings:
                    target_canonical = alias_to_canonical.get(s.lower())
                    if target_canonical:
                        break

                if not target_canonical:
                    continue

                try:
                    conn.execute(
                        f"UPDATE entity_xref SET entity={self._ph} WHERE entity={self._ph}",
                        (target_canonical, node_id),
                    )
                    conn.execute(
                        f"DELETE FROM entity_registry WHERE node_id={self._ph}", (node_id,)
                    )
                    if self._kbackend != "postgres":
                        try:
                            conn.execute(
                                "DELETE FROM fts_entities WHERE node_id=?", (node_id,)
                            )
                        except Exception:
                            pass  # fts table may not exist yet — non-fatal
                    purged += 1
                    logger.info(
                        "EntityGuideSeeder: purged fragment %r → canonical %r",
                        node_id, target_canonical,
                    )
                except Exception as _pe:
                    logger.debug(
                        "EntityGuideSeeder: failed to purge fragment %r: %s", node_id, _pe
                    )

            if purged:
                conn.commit()
                logger.info("EntityGuideSeeder: dedup sweep removed %d fragment(s)", purged)
            else:
                logger.info("EntityGuideSeeder: dedup sweep — no fragments found")

    def _seed_worker(self) -> None:
        try:
            self._ensure_schema()

            if not self.guide_path.exists():
                logger.warning("EntityGuideSeeder: guide file not found: %s", self.guide_path)
                return

            mtime_now = self.guide_path.stat().st_mtime
            cached    = self._get_cached_mtime()

            if cached and abs(cached[0] - mtime_now) < 1.0:
                logger.info(
                    "EntityGuideSeeder: %s unchanged — %d entities already in registry",
                    self.guide_path.name, cached[1],
                )
                return

            logger.info("EntityGuideSeeder: (re)seeding from %s", self.guide_path.name)
            entities = _parse_entity_guide(self.guide_path)

            if not entities:
                logger.warning(
                    "EntityGuideSeeder: no entities parsed from %s — check table format",
                    self.guide_path.name,
                )
                return

            seeded = 0
            for ent in entities:
                try:
                    ok = self.entity_registry.register_entity(
                        node_id      = ent["node_id"],
                        node_type    = ent["node_type"],
                        display_name = ent["display_name"],
                        aliases      = ent["aliases"],
                        skill_name   = ent["skill_name"],
                        metadata     = ent["metadata"],
                    )
                    if ok:
                        seeded += 1
                except Exception as _re:
                    logger.debug(
                        "EntityGuideSeeder: register_entity failed for %r: %s",
                        ent["node_id"], _re,
                    )

            self._save_mtime(mtime_now, seeded)
            logger.info(
                "EntityGuideSeeder: seeded %d/%d entities from %s ✓",
                seeded, len(entities), self.guide_path.name,
            )

            self._purge_fragments(entities)

            edges = _parse_relationships(self.guide_path)
            edge_ok = 0
            for e in edges:
                try:
                    if self.entity_registry.upsert_relationship(
                        from_node  = e["from_node"],
                        relation   = e["relation"],
                        to_node    = e["to_node"],
                        condition  = e["condition"],
                        metadata   = e["metadata"],
                        status     = "curated",          # tenant-authored ontology = trusted
                        confidence = 1.0,
                        source     = "entity_guide",
                        created_by = "seeder",
                    ):
                        edge_ok += 1
                except Exception as _ee:
                    logger.debug("EntityGuideSeeder: upsert_relationship failed for %r: %s", e, _ee)
            if edges:
                logger.info(
                    "EntityGuideSeeder: seeded %d/%d relationships from %s ✓",
                    edge_ok, len(edges), self.guide_path.name,
                )

        except Exception as exc:
            logger.warning("EntityGuideSeeder: seed failed (non-fatal): %s", exc)
        finally:
            self._ready.set()
