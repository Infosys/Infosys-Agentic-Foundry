"""World-model provider contract (Phase 2d).

A stable, domain-agnostic interface for the relationship graph, so different storage
backends plug in behind the same seam:
  - ``relational`` (default) — recursive-CTE reads over entity_registry/process_relationships;
  - ``age`` (opt-in) — Apache AGE / openCypher (needs the AGE Postgres extension).

``EntityRegistryStore`` satisfies this Protocol today. The active backend is chosen by
``GRAPH_BACKEND`` (see ``iaf_agent_skills.world_model.resolve_graph_backend``). Relations and
node types are free strings (domain-neutral); provenance (status/confidence/source/validity)
is carried per edge.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Protocol, runtime_checkable


@runtime_checkable
class WorldModelProvider(Protocol):
    """Read/write verbs for the world-model graph."""

    def upsert_relationship(
        self,
        from_node: str,
        relation: str,
        to_node: str,
        condition: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
        *,
        confidence: float = 1.0,
        status: str = "curated",
        source: Optional[str] = None,
        created_by: Optional[str] = None,
        valid_from: Optional[str] = None,
        valid_to: Optional[str] = None,
    ) -> bool:
        """Write (idempotently update) a directed, provenance-stamped edge."""

    def set_relationship_status(self, rel_id: str, status: str) -> bool:
        """Governance: change an edge's status (e.g. promote pending_review → confirmed, reject)."""

    def list_relationships(self, status: Optional[str] = None, limit: int = 100) -> List[Dict[str, Any]]:
        """Read edges (optionally filtered by status) for review surfaces / read models."""
