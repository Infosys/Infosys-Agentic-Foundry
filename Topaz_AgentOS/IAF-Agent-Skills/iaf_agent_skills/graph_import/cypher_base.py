"""Shared level-by-level hierarchy fetch for openCypher engines.

Neo4j and Amazon Neptune (openCypher) accept the same statements apart from the
node-identity function and the HTTP transport, so the traversal lives here and each
adapter only implements ``_run``. Fetching one tree level per round-trip (instead
of a variable-length ``*1..N`` pattern) keeps result sizes bounded, lets us enforce
``max_nodes`` precisely, and makes the "first parent wins" ordering deterministic.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List

from agentos_contracts.graph_source import (
    DIRECTION_IN,
    DIRECTION_OUT,
    GraphEdge,
    GraphNode,
    GraphSnapshot,
    HierarchyQuery,
)

from .safety import GraphImportError, clamp_int, validate_identifier

logger = logging.getLogger(__name__)

_BATCH = 500   # ids per children query


class CypherHierarchyAdapter:
    engine = "cypher"
    id_function = "id"          # overridden: Neo4j 5 -> elementId, Neptune -> id

    # -- transport (adapter specific) ------------------------------------------
    def _run(self, statement: str, params: Dict[str, Any]) -> List[Dict[str, Any]]:  # pragma: no cover
        raise NotImplementedError

    # -- statements -------------------------------------------------------------
    def _root_statement(self, q: HierarchyQuery) -> str:
        label = validate_identifier(q.root_label, "Root label")
        prop = validate_identifier(q.name_property, "Name property")
        idf = self.id_function
        desc = (
            f"r.`{validate_identifier(q.description_property, 'Description property')}`"
            if q.description_property else "null"
        )
        return (
            f"MATCH (r:`{label}`) WHERE r.`{prop}` = $root_name "
            f"RETURN {idf}(r) AS id, r.`{prop}` AS name, {desc} AS description LIMIT 2"
        )

    def _children_statement(self, q: HierarchyQuery, row_cap: int) -> str:
        edge = validate_identifier(q.edge_type, "Relationship type")
        prop = validate_identifier(q.name_property, "Name property")
        idf = self.id_function
        desc = (
            f"c.`{validate_identifier(q.description_property, 'Description property')}`"
            if q.description_property else "null"
        )
        if q.direction == DIRECTION_OUT:
            pattern = f"(p)-[:`{edge}`]->(c)"
        elif q.direction == DIRECTION_IN:
            pattern = f"(c)-[:`{edge}`]->(p)"
        else:
            raise GraphImportError("bad_direction", "Direction must be 'out' or 'in'")
        return (
            f"MATCH {pattern} WHERE {idf}(p) IN $ids "
            f"RETURN {idf}(p) AS pid, {idf}(c) AS id, c.`{prop}` AS name, {desc} AS description "
            # Deterministic cut: without ORDER BY the server may keep a different subset of
            # rows on each run when a batch exceeds row_cap (sorting in Python afterwards
            # cannot change which rows were fetched). id is the final tie-breaker.
            f"ORDER BY pid, name, id LIMIT {int(row_cap)}"
        )

    # -- traversal --------------------------------------------------------------
    def fetch_hierarchy(self, query: HierarchyQuery) -> GraphSnapshot:
        max_depth = clamp_int(query.max_depth, 1, 8, 5)
        max_nodes = clamp_int(query.max_nodes, 10, 5000, 2000)
        row_cap = max_nodes * 3

        # Build (and thereby validate) every statement before the first request so a
        # bad identifier can never cause a partial round-trip.
        root_stmt = self._root_statement(query)
        stmt = self._children_statement(query, row_cap)

        rows = self._run(root_stmt, {"root_name": query.root_name})
        if not rows:
            raise GraphImportError("root_not_found", "No node matches that root label and name", status=404)
        if len(rows) > 1:
            raise GraphImportError(
                "root_ambiguous",
                "More than one node matches that root label and name; pick a more specific root",
                status=409,
            )
        r = rows[0]
        root = GraphNode(
            id=str(r.get("id")),
            name=_text(r.get("name")),
            labels=(query.root_label,),
            description=_text(r.get("description")),
        )
        snap = GraphSnapshot(root=root, nodes={root.id: root})
        frontier: List[str] = [root.id]

        # One extra level (index == max_depth) is only *probed*: if it returns rows
        # the graph continues past the depth limit, so we flag truncation but do
        # not add those nodes.
        for level in range(max_depth + 1):
            if not frontier:
                break
            probing = level == max_depth
            batch_rows: List[Dict[str, Any]] = []
            for i in range(0, len(frontier), _BATCH):
                got = self._run(stmt, {"ids": frontier[i:i + _BATCH]})
                if len(got) >= row_cap:
                    snap.truncated = True
                batch_rows.extend(got)
            if probing:
                if batch_rows:
                    snap.truncated = True
                break

            order = {pid: n for n, pid in enumerate(frontier)}
            batch_rows.sort(key=lambda x: (order.get(str(x.get("pid")), 1 << 30),
                                           _text(x.get("name")).casefold(), str(x.get("id"))))
            nxt: List[str] = []
            for x in batch_rows:
                pid, cid = str(x.get("pid")), str(x.get("id"))
                if pid not in snap.nodes:
                    continue
                snap.edges.append(GraphEdge(parent_id=pid, child_id=cid))
                if cid in snap.nodes:
                    continue                      # multi-parent / cycle: mapper reports it
                if len(snap.nodes) >= max_nodes:
                    snap.truncated = True
                    continue
                snap.nodes[cid] = GraphNode(
                    id=cid,
                    name=_text(x.get("name")),
                    description=_text(x.get("description")),
                )
                nxt.append(cid)
            frontier = nxt
        return snap


def _text(v: Any) -> str:
    if v is None:
        return ""
    if isinstance(v, (list, tuple)):
        v = ", ".join(str(i) for i in v)
    return str(v)
