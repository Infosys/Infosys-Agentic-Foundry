"""Publish a user-supplied graph/ontology JSON so ``graph_query`` can answer from it.

``normalize_graph`` turns the common JSON shapes into graphify's node-link format:

* graphify / NetworkX node-link ``{nodes, links|edges}`` -- passed through (ids are cleaned)
* ontology / knowledge-graph ``{nodes|entities|concepts|classes, edges|relationships|relations}``
  with endpoints given as ``source/target``, ``from/to`` or ``subject/object``
* bare triples ``[{subject, predicate, object}, ...]`` or ``{triples: [...]}``
* a nested tree ``{name, children: [...]}`` (each child becomes a ``has_child`` edge)

``publish_graph`` / ``list_graphs`` / ``delete_graph`` manage ``<tenant>/shared/graphs/<name>/``.
The folder layout, the name pattern and the 64 MB read cap match what ``graph_query`` enforces, so a
published graph is queryable straight away. Everything here is file-only: no network, no credentials.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import tempfile
from collections import Counter
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .safety import GraphImportError

NAME_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
MAX_UPLOAD_BYTES = 16 * 1024 * 1024        # what the upload endpoint accepts
MAX_NODES = 200_000
MAX_ID_CHARS = 200                          # node ids are identity: longer ones are rejected, never cut
# Keep in sync with MAX_BYTES in enterprise_root/tenants/company/skills/codebase_graph/tools/graph_query.py:
# a converted graph.json above this size is refused by the query tool, so never publish one.
MAX_QUERY_BYTES = 64 * 1024 * 1024
MAX_EDGES = 1_000_000
MAX_DEPTH = 64                              # nested ``children`` trees
_NODE_LISTS = ("nodes", "entities", "concepts", "classes", "vertices", "terms")
_EDGE_LISTS = ("links", "edges", "relationships", "relations", "triples", "connections")
_ID_KEYS = ("id", "@id", "iri", "uri", "key", "name", "label", "title")
_LABEL_KEYS = ("label", "name", "title", "id", "@id", "iri")
_SRC_KEYS = ("source", "from", "subject", "src", "start", "head", "parent")
_DST_KEYS = ("target", "to", "object", "dst", "end", "tail", "child")
_REL_KEYS = ("relation", "relationship", "predicate", "type", "label", "name", "kind")
_TYPE_KEYS = ("file_type", "type", "kind", "category", "class")
_DESC_KEYS = ("description", "definition", "comment", "summary", "notes")


def check_name(name: str) -> str:
    name = (name or "").strip()
    if not NAME_RE.match(name):
        raise GraphImportError("bad_name", "Graph name must be 1-64 letters, digits, '_' or '-'", status=422)
    return name


def graphs_root(tenant_root: Path) -> Path:
    return (Path(tenant_root) / "shared" / "graphs").resolve()


def _first(d: Dict[str, Any], keys: Tuple[str, ...]) -> Any:
    for k in keys:
        v = d.get(k)
        if v is not None and v != "" and not isinstance(v, (dict, list)):
            return v
    return None


def _text(v: Any, limit: int = 300) -> str:
    return re.sub(r"\s+", " ", str(v)).strip()[:limit]


def _ident(v: Any) -> str:
    """Whitespace-normalised node identity. Unlike a label it is never truncated: cutting an id would
    silently merge distinct nodes that share a prefix, so an overlong id is rejected instead."""
    s = re.sub(r"\s+", " ", str(v)).strip()
    if len(s) > MAX_ID_CHARS:
        raise GraphImportError(
            "bad_graph",
            f"A node id is longer than {MAX_ID_CHARS} characters (it starts with '{s[:40]}...'); shorten it "
            "or give the node a short id and keep the long text in label/description", status=422)
    return s


def normalize_graph(doc: Any) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Return ``(graphify_doc, report)``. Raises ``GraphImportError`` (422) when nothing usable is found."""
    if isinstance(doc, list):                       # a bare list: triples, or nodes with no edges
        doc = {"triples": doc} if doc and isinstance(doc[0], dict) and any(k in doc[0] for k in _SRC_KEYS) else {"nodes": doc}
    if not isinstance(doc, dict):
        raise GraphImportError("bad_graph", "The file must be a JSON object (or a list of triples)", status=422)

    fmt = "graphify" if isinstance(doc.get("nodes"), list) and isinstance(doc.get("links"), list) else "ontology"
    raw_nodes: List[Any] = next((doc[k] for k in _NODE_LISTS if isinstance(doc.get(k), list)), [])
    raw_edges: List[Any] = next((doc[k] for k in _EDGE_LISTS if isinstance(doc.get(k), list)), [])
    tree_edges: List[Tuple[str, str]] = []
    tree_nodes: List[Dict[str, Any]] = []
    if not raw_nodes and not raw_edges and isinstance(doc.get("children"), list):
        fmt = "tree"
        _walk_tree(doc, None, tree_nodes, tree_edges, 0)
        raw_nodes = tree_nodes
        raw_edges = [{"source": a, "target": b, "relation": "has_child"} for a, b in tree_edges]
    if not raw_nodes and not raw_edges:
        raise GraphImportError(
            "bad_graph",
            "No nodes or edges found. Expected nodes/edges (or entities/relationships, triples, or a children tree)",
            status=422)
    if len(raw_nodes) > MAX_NODES or len(raw_edges) > MAX_EDGES:
        raise GraphImportError("graph_too_large", "The graph has too many nodes or edges", status=413)

    nodes: Dict[str, Dict[str, Any]] = {}
    by_label: Dict[str, str] = {}
    dropped_nodes = 0

    def add_node(src: Any, *, stub: bool = False) -> Optional[str]:
        nonlocal dropped_nodes
        if isinstance(src, (str, int)) and not isinstance(src, bool):
            src = {"id": src}
        if not isinstance(src, dict):
            dropped_nodes += 1
            return None
        nid = _first(src, _ID_KEYS)
        if nid is None:
            dropped_nodes += 1
            return None
        nid = _ident(nid)
        if nid in nodes:
            return nid
        if len(nodes) >= MAX_NODES:             # also counts nodes created from edge endpoints / triples
            raise GraphImportError("graph_too_large", "The graph has too many nodes or edges", status=413)
        out: Dict[str, Any] = {"id": nid, "label": _text(_first(src, _LABEL_KEYS) or nid, 200)}
        t = _first(src, _TYPE_KEYS)
        out["file_type"] = _text(t, 60) if t is not None else ("code" if fmt == "graphify" and not stub else "entity")
        d = _first(src, _DESC_KEYS)
        if d is not None:
            out["description"] = _text(d)
        for k in ("source_file", "source_location"):
            if isinstance(src.get(k), (str, int)):
                out[k] = _text(src[k], 300)
        comm = src.get("community")
        if isinstance(comm, int) and not isinstance(comm, bool):
            out["community"] = comm
        nodes[nid] = out
        by_label.setdefault(out["label"].casefold(), nid)
        by_label.setdefault(nid.casefold(), nid)
        return nid

    for n in raw_nodes:
        add_node(n)

    def resolve(ep: Any) -> Optional[str]:
        if isinstance(ep, dict):
            ep = _first(ep, _ID_KEYS)
        if ep is None or isinstance(ep, bool):
            return None
        key = _ident(ep)
        if key in nodes:
            return key
        hit = by_label.get(key.casefold())
        if hit:
            return hit
        return None

    links: List[Dict[str, Any]] = []
    stubs = dropped_edges = 0
    for e in raw_edges:
        if not isinstance(e, dict):
            dropped_edges += 1
            continue
        s_raw = next((e[k] for k in _SRC_KEYS if e.get(k) not in (None, "")), None)
        t_raw = next((e[k] for k in _DST_KEYS if e.get(k) not in (None, "")), None)
        s, t = resolve(s_raw), resolve(t_raw)
        for which, raw in (("s", s_raw), ("t", t_raw)):
            if (s if which == "s" else t) is None and raw is not None and not isinstance(raw, (list, bool)):
                made = add_node(raw, stub=True)       # an endpoint named only in the edge list
                if made:
                    stubs += 1
                    if which == "s":
                        s = made
                    else:
                        t = made
        if s is None or t is None:
            dropped_edges += 1
            continue
        rel = next((e[k] for k in _REL_KEYS if isinstance(e.get(k), (str, int)) and e.get(k) != ""), "related_to")
        links.append({"source": s, "target": t, "relation": _text(rel, 80),
                      "confidence": _text(e.get("confidence") or "EXTRACTED", 20)})

    if not nodes:
        raise GraphImportError("bad_graph", "No usable nodes found in the file", status=422)

    out = {"directed": True, "multigraph": False, "graph": {"source_format": fmt},
           "nodes": list(nodes.values()), "links": links}
    kinds = Counter(n["file_type"] for n in nodes.values())
    report = {
        "format": fmt, "nodes": len(nodes), "edges": len(links),
        "node_types": dict(kinds.most_common(10)),
        "relations": dict(Counter(l["relation"] for l in links).most_common(10)),
        "notes": [m for m in (
            f"{stubs} node(s) were created from names used only in the edge list" if stubs else "",
            f"{dropped_nodes} node entr{'y' if dropped_nodes == 1 else 'ies'} had no id and {'was' if dropped_nodes == 1 else 'were'} skipped" if dropped_nodes else "",
            f"{dropped_edges} edge(s) skipped (missing or unmatched endpoints)" if dropped_edges else "",
            "No edges found: search and explain work, path finding does not" if not links else "",
        ) if m],
    }
    return out, report


def _walk_tree(node: Dict[str, Any], parent: Optional[str], nodes: List[Dict[str, Any]],
               edges: List[Tuple[str, str]], depth: int) -> None:
    if depth > MAX_DEPTH or not isinstance(node, dict):
        return
    nid = _ident(_first(node, _ID_KEYS) or f"n{len(nodes)}")
    item = {k: v for k, v in node.items() if k != "children"}
    item["id"] = nid
    nodes.append(item)
    if parent is not None:
        edges.append((parent, nid))
    for c in node.get("children") or []:
        _walk_tree(c, nid, nodes, edges, depth + 1)


# -- publish / list / delete ---------------------------------------------------

def _atomic_write(path: Path, text: str, *, overwrite: bool = True) -> None:
    """Write ``text`` to ``path`` via a temp file in the same folder.

    ``overwrite=True`` replaces atomically (``os.replace``). ``overwrite=False`` is create-if-absent:
    the temp file is hard-linked to ``path`` (``os.link`` fails if ``path`` exists, atomically, on POSIX
    and NTFS), so two concurrent uploads cannot both win; the loser gets the 409 ``exists`` error."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".tmp-", suffix=".json")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(text)
        if overwrite:
            os.replace(tmp, path)
            return
        try:
            os.link(tmp, path)
        except FileExistsError:
            raise GraphImportError("exists", f"A graph named '{path.parent.name}' already exists", status=409)
        except (OSError, NotImplementedError):   # filesystem without hard links: exclusive create instead
            try:
                with open(path, "x", encoding="utf-8") as fh:
                    fh.write(text)
            except FileExistsError:
                raise GraphImportError("exists", f"A graph named '{path.parent.name}' already exists", status=409)
    finally:
        try:
            os.unlink(tmp)
        except OSError:
            pass


def _folder(tenant_root: Path, name: str) -> Path:
    base = graphs_root(tenant_root)
    # check_name() allows only [A-Za-z0-9_-], so the name cannot contain a separator or "..".
    # Do NOT resolve() the folder and compare it with a base resolved at another moment: on Windows
    # resolve() is not stable while another thread is creating the folder, and under concurrent uploads
    # that rejected valid names intermittently. A symlinked folder is refused outright instead, which
    # keeps the "stay under shared/graphs" guarantee without resolving.
    folder = base / check_name(name)
    if folder.is_symlink():
        raise GraphImportError("bad_name", "Invalid graph name", status=422)
    return folder


def publish_graph(tenant_root: Path, name: str, content: str, *, overwrite: bool = False) -> Dict[str, Any]:
    """Validate + convert ``content`` (JSON text) and write it as ``shared/graphs/<name>/graph.json``."""
    if len((content or "").encode("utf-8")) > MAX_UPLOAD_BYTES:
        raise GraphImportError("graph_too_large", "The graph file is too large (16 MB limit)", status=413)
    folder = _folder(tenant_root, name)
    try:
        doc = json.loads(content)
    except (ValueError, TypeError):
        raise GraphImportError("bad_graph", "The file is not valid JSON", status=422)
    graph, report = normalize_graph(doc)
    text = json.dumps(graph, ensure_ascii=False)
    if len(text.encode("utf-8")) > MAX_QUERY_BYTES:        # checked before anything is written or replaced
        raise GraphImportError(
            "graph_too_large",
            "The converted graph is too large to query (64 MB limit); upload a smaller graph", status=413)
    target = folder / "graph.json"
    if target.exists() and not overwrite:
        raise GraphImportError("exists", f"A graph named '{name}' already exists", status=409)
    _atomic_write(target, text, overwrite=overwrite)
    deg = Counter(x for l in graph["links"] for x in (l["source"], l["target"]))
    labels = {n["id"]: n["label"] for n in graph["nodes"]}
    top = deg.most_common(1)[0][0] if deg else graph["nodes"][0]["id"]
    return {"name": name, **report, "example": labels[top], "path": f"/shared/graphs/{name}/graph.json"}


def list_graphs(tenant_root: Path) -> List[Dict[str, Any]]:
    base = graphs_root(tenant_root)
    out: List[Dict[str, Any]] = []
    if not base.is_dir():
        return out
    for d in sorted(base.iterdir(), key=lambda p: p.name.casefold()):
        f = (d / "graph.json").resolve()
        if not NAME_RE.match(d.name) or not f.is_relative_to(base) or not f.is_file():
            continue
        item: Dict[str, Any] = {"name": d.name, "updated": int(f.stat().st_mtime), "bytes": f.stat().st_size}
        try:
            if f.stat().st_size <= MAX_QUERY_BYTES:
                doc = json.loads(f.read_text(encoding="utf-8"))
                links = doc.get("links", doc.get("edges")) or []
                item.update(nodes=len(doc.get("nodes") or []), edges=len(links),
                            format=(doc.get("graph") or {}).get("source_format", "graphify"))
        except (OSError, ValueError, AttributeError):
            item["error"] = "unreadable"
        out.append(item)
    return out


def delete_graph(tenant_root: Path, name: str) -> None:
    folder = _folder(tenant_root, name)
    if not (folder / "graph.json").is_file():
        raise GraphImportError("graph_not_found", "No graph with that name", status=404)
    shutil.rmtree(folder)
