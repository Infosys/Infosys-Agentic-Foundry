"""Graph-source contract (taxonomy graph import).

A stable, vendor-neutral interface for pulling a *hierarchy* out of an external
property graph (Neo4j, Amazon Neptune, ...) so it can be turned into a taxonomy.
Adapters implement :class:`GraphSourceAdapter`; everything downstream (mapping to
L1/L2/L3, skill assignment, writing the taxonomy .md) works on the neutral
:class:`GraphSnapshot` and never sees a driver, a URL or a credential.

Dependency-free on purpose (same rule as the rest of ``agentos_contracts``).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Protocol, Tuple, runtime_checkable

DIRECTION_OUT = "out"   # root -[edge]-> child   (e.g. PARENT_OF, HAS_CHILD)
DIRECTION_IN = "in"     # child -[edge]-> parent (e.g. BROADER, SUBCLASS_OF, CHILD_OF)


@dataclass(frozen=True)
class GraphNode:
    id: str
    name: str
    labels: Tuple[str, ...] = ()
    description: str = ""


@dataclass(frozen=True)
class GraphEdge:
    """A hierarchy edge, always normalised to parent -> child by the adapter."""
    parent_id: str
    child_id: str


@dataclass(frozen=True)
class HierarchyQuery:
    """Fixed-shape request. Every field is validated by the service before an
    adapter sees it (identifiers against a strict regex, ints clamped) -- there is
    deliberately no free-text query field."""
    root_label: str
    root_name: str
    edge_type: str
    direction: str = DIRECTION_OUT
    name_property: str = "name"
    description_property: str = ""
    max_depth: int = 5
    max_nodes: int = 2000


@dataclass(frozen=True)
class FileGraphQuery:
    """Request for a *file-based* engine (a graphify ``graph.json``), where there is no
    root node / relationship to name: the hierarchy is derived from the graph's own
    structure. ``mode`` is ``"community"`` (graphify's detected communities -> source
    files -> symbols) or ``"path"`` (directory tree -> source files -> symbols)."""
    mode: str = "community"
    path_prefix: str = ""         # only files under this path (e.g. "IAF-Agent-Studio/routers")
    domain_depth: int = 2         # path mode: how many leading path segments form a domain
    min_size: int = 3             # community mode: ignore communities smaller than this
    max_domains: int = 40         # keep the N largest domains
    max_nodes: int = 5000


@dataclass
class GraphSnapshot:
    root: GraphNode
    nodes: Dict[str, GraphNode] = field(default_factory=dict)
    edges: List[GraphEdge] = field(default_factory=list)
    truncated: bool = False           # hit max_nodes / max_depth before the graph ended
    source: Dict[str, Any] = field(default_factory=dict)   # engine, connection id (no secrets)


@runtime_checkable
class GraphSourceAdapter(Protocol):
    """Read-only access to one external graph."""

    engine: str

    def fetch_hierarchy(self, query: HierarchyQuery) -> GraphSnapshot:
        """Return the sub-tree under ``query.root_*`` following ``query.edge_type``."""
        ...

    def health(self) -> Dict[str, Any]:
        """Cheap reachability/auth probe. Must not include secrets or URLs."""
        ...
