"""World-model relationship learning (Phase 2b) — domain-agnostic, default-off.

The per-turn LLM reasoning pass (memory._extract_reasoning_and_entities) is extended to
also emit candidate relationship triples. This module confidence-gates them, resolves the
endpoints to FK-valid node_ids, and writes them as **pending_review** edges into the
world-model graph (process_relationships) via EntityRegistryStore.upsert_relationship.

Design (AGENTS.md):
- Composable service module (not inline in the agent runtime); reuses the entity-registry
  seam and the already-existing per-turn LLM extraction (no extra model call).
- Domain-neutral: relation is a free string; the ontology + vocabulary are tenant config.
- Governed: agent-inferred edges are pending_review (hidden from reads until promoted) and
  confidence-gated; endpoints must resolve to existing entities (FK safety).
- Reversible: gated by WORLD_MODEL_LEARN (default off) — zero behaviour change when off.
"""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

_TRUE = {"1", "true", "yes", "on"}


def world_model_learn_enabled() -> bool:
    """True when per-turn relationship learning is switched on (default off)."""
    return os.getenv("WORLD_MODEL_LEARN", "").strip().lower() in _TRUE


def _min_confidence() -> float:
    try:
        return max(0.0, min(1.0, float(os.getenv("WORLD_MODEL_MIN_CONFIDENCE", "0.6"))))
    except Exception:
        return 0.6


def _autoconfirm_threshold() -> Optional[float]:
    """Confidence at/above which an agent-learned edge is written as ``confirmed`` (skips review)
    instead of ``pending_review``. Unset (default) = OFF → everything stays pending_review (the
    safe governance default). Set WORLD_MODEL_AUTOCONFIRM_CONFIDENCE=0.95 to auto-confirm ≥0.95."""
    v = os.getenv("WORLD_MODEL_AUTOCONFIRM_CONFIDENCE", "").strip()
    if not v:
        return None
    try:
        return max(0.0, min(1.0, float(v)))
    except Exception:
        return None


def _resolve_node(entity_registry: Any, ref: str) -> Optional[str]:
    """Resolve a triple endpoint (entity name OR node_id) to an existing node_id.

    A value containing ':' is treated as a node_id and trusted (the FK will reject it at
    write time if it doesn't exist). Otherwise resolve by alias/FTS (no embedding call).
    Returns None when it can't be resolved — the caller then skips the edge (FK-safe).
    """
    ref = (ref or "").strip()
    if not ref:
        return None
    if ":" in ref:
        return ref
    try:
        matches = entity_registry._resolve_by_alias(ref, top_k=1)
        if matches:
            m = matches[0]
            return m.get("node_id") if isinstance(m, dict) else getattr(m, "node_id", None)
    except Exception as exc:
        logger.debug("world_model: alias resolve failed for %r: %s", ref, exc)
    return None


def record_relationships(
    entity_registry: Any,
    triples: List[Dict[str, Any]],
    *,
    source: str = "turn_extractor",
    created_by: str = "agent",
    session_id: Optional[str] = None,
    min_confidence: Optional[float] = None,
    events_path: Optional[str] = None,
) -> Tuple[int, int]:
    """Write confidence-gated, FK-safe, ``pending_review`` edges from extracted triples.

    Returns (written, skipped). Never raises — this runs in the per-turn background path.
    Silent-cap discipline: every skipped candidate is logged at debug (no silent drops).
    """
    if not triples or entity_registry is None:
        return (0, 0)
    if not hasattr(entity_registry, "upsert_relationship"):
        return (0, 0)
    threshold = _min_confidence() if min_confidence is None else min_confidence
    written = skipped = 0
    for t in triples:
        if not isinstance(t, dict):
            skipped += 1
            continue
        frm_raw = str(t.get("from") or "").strip()
        rel = str(t.get("relation") or t.get("rel") or "").strip()
        to_raw = str(t.get("to") or "").strip()
        try:
            conf = float(t.get("confidence", 0.5))
        except Exception:
            conf = 0.5
        if not frm_raw or not rel or not to_raw:
            skipped += 1
            continue
        if conf < threshold:
            skipped += 1
            logger.debug("world_model: below-threshold edge dropped (%.2f<%.2f): %s -%s-> %s",
                         conf, threshold, frm_raw, rel, to_raw)
            continue
        frm = _resolve_node(entity_registry, frm_raw)
        to = _resolve_node(entity_registry, to_raw)
        if not frm or not to:
            skipped += 1
            logger.debug("world_model: unresolved endpoint, edge skipped (%s -%s-> %s)",
                         frm_raw, rel, to_raw)
            continue
        # Auto-confirm knob: high-confidence edges may skip review (default OFF → pending_review).
        _auto = _autoconfirm_threshold()
        _status = "confirmed" if (_auto is not None and conf >= _auto) else "pending_review"
        meta: Dict[str, Any] = {"origin": "per_turn_extraction"}
        if session_id:
            meta["session"] = session_id
        ok = entity_registry.upsert_relationship(
            frm, rel, to,
            metadata=meta,
            status=_status,
            confidence=conf,
            source=source,
            created_by=created_by,
        )
        if ok:
            written += 1
            append_event(events_path, {
                "type": "edge_upsert", "from": frm, "relation": rel, "to": to,
                "status": _status, "confidence": conf,
                "source": source, "created_by": created_by, "session": session_id,
            })
        else:
            skipped += 1
    if written or skipped:
        logger.info("world_model: %d pending edge(s) recorded, %d skipped", written, skipped)
    return (written, skipped)



def append_event(events_path: Optional[str], event: Dict[str, Any]) -> bool:
    """Append one world event as a JSON line. Non-fatal; single-writer per agent."""
    if not events_path:
        return False
    try:
        p = Path(events_path)
        p.parent.mkdir(parents=True, exist_ok=True)
        record = {"ts": datetime.now().isoformat(), **event}
        line = json.dumps(record, default=str) + "\n"
        try:
            from .file_lock import file_lock  # advisory lock for shared/NFS mounts
            with file_lock(str(p)):
                with open(p, "a", encoding="utf-8") as f:
                    f.write(line)
        except Exception:
            with open(p, "a", encoding="utf-8") as f:
                f.write(line)
        return True
    except Exception as exc:
        logger.debug("world_model: append_event failed: %s", exc)
        return False


def record_outcome_event(
    events_path: Optional[str],
    subject: str,
    verb: str,
    obj: str,
    *,
    outcome: Optional[str] = None,
    source: str = "outcome",
    created_by: str = "agent",
    session_id: Optional[str] = None,
    confidence: float = 1.0,
    metadata: Optional[Dict[str, Any]] = None,
) -> bool:
    """Append an outcome/feedback event (e.g. plan RESOLVED issue, human CORRECTED edge).

    Extension point for the RL/feedback path (capture_events consumers): outcomes are logged
    to the world_events spine here; promotion into graph edges is governed (2d).
    """
    return append_event(events_path, {
        "type": "outcome", "from": subject, "relation": verb, "to": obj,
        "outcome": outcome, "confidence": confidence,
        "source": source, "created_by": created_by, "session": session_id,
        "metadata": metadata or {},
    })


def rebuild_graph_from_events(entity_registry: Any, events_path: str) -> int:
    """Projector: replay world_events.jsonl into process_relationships (idempotent).

    For recovery/audit — the log is truth, the graph is its projection. Only ``edge_upsert``
    events are replayed (outcomes are promoted separately, under governance). Returns the
    number of edges (re)applied. Endpoints that no longer resolve are skipped (FK-safe).
    """
    if entity_registry is None or not events_path or not Path(events_path).exists():
        return 0
    applied = 0
    with open(events_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                ev = json.loads(line)
            except Exception:
                continue
            if ev.get("type") != "edge_upsert":
                continue
            if entity_registry.upsert_relationship(
                ev.get("from"), ev.get("relation"), ev.get("to"),
                metadata=ev.get("metadata") or {},
                status=ev.get("status", "pending_review"),
                confidence=ev.get("confidence", 0.5),
                source=ev.get("source"),
                created_by=ev.get("created_by"),
            ):
                applied += 1
    logger.info("world_model: rebuilt %d edge(s) from %s", applied, events_path)
    return applied



def list_pending(entity_registry: Any, limit: int = 100) -> List[Dict[str, Any]]:
    """Pending-review edges awaiting a promote/reject decision (for the review surface)."""
    if entity_registry is None or not hasattr(entity_registry, "list_relationships"):
        return []
    return entity_registry.list_relationships(status="pending_review", limit=limit)


def promote_relationship(entity_registry: Any, rel_id: str, *,
                         events_path: Optional[str] = None, promoted_by: str = "reviewer") -> bool:
    """Promote a pending_review edge to confirmed (now visible to graph reads)."""
    if entity_registry is None or not rel_id:
        return False
    ok = entity_registry.set_relationship_status(rel_id, "confirmed")
    if ok:
        append_event(events_path, {"type": "promote", "id": rel_id,
                                   "status": "confirmed", "created_by": promoted_by})
    return ok


def reject_relationship(entity_registry: Any, rel_id: str, *,
                        events_path: Optional[str] = None, rejected_by: str = "reviewer") -> bool:
    """Reject a pending_review edge (kept as an audit record; never returned by reads)."""
    if entity_registry is None or not rel_id:
        return False
    ok = entity_registry.set_relationship_status(rel_id, "rejected")
    if ok:
        append_event(events_path, {"type": "reject", "id": rel_id,
                                   "status": "rejected", "created_by": rejected_by})
    return ok



def resolve_graph_backend() -> str:
    """Active graph backend, mirroring resolve_backend for the storage engine.

    Default ``relational`` = the recursive-CTE reads over entity_registry/process_relationships
    (the only wired impl today). ``age`` is the opt-in Apache AGE / openCypher seam — it requires
    the AGE Postgres extension to be installed (infra), so it is a documented extension point, not
    yet implemented; selecting it logs a warning and falls back to relational.
    """
    backend = os.getenv("GRAPH_BACKEND", "relational").strip().lower() or "relational"
    if backend == "age":
        logger.warning("GRAPH_BACKEND=age requested but the Apache AGE backend is not yet "
                       "implemented (needs the AGE extension); falling back to 'relational'.")
        return "relational"
    if backend != "relational":
        logger.warning("Unknown GRAPH_BACKEND %r; using 'relational'.", backend)
        return "relational"
    return "relational"
