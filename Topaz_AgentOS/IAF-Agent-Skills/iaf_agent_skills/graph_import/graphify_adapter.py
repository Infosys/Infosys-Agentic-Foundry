"""graphify adapter -- turn a graphify ``graph.json`` into a GraphSnapshot.

graphify (https://github.com/safishamsi/graphify) writes a NetworkX node-link graph:
``nodes[{id, label, file_type, source_file, source_location, community, ...}]`` and
``links[{source, target, relation, confidence, ...}]``. It is a *code* graph, not a
business hierarchy, so there is no root/edge to traverse. Instead the hierarchy is
derived from the graph's own structure (two modes, see ``FileGraphQuery``):

* ``community`` -- repo -> graphify community -> source file -> symbols
* ``path``      -- repo -> directory -> source file -> symbols

Everything downstream (loss report, sanitiser, skill suggestions, preview/commit) is the
same pipeline the Neo4j / Neptune adapters feed. This adapter is file-only: no network,
no credentials, no SSRF surface -- the only input is a JSON file under the tenant's
``shared/graphs`` folder, confined and size-capped by the caller.
"""
from __future__ import annotations

import json
import re
from collections import defaultdict
from pathlib import Path, PurePosixPath
from typing import Any, Dict, List, Optional, Tuple

from agentos_contracts.graph_source import FileGraphQuery, GraphEdge, GraphNode, GraphSnapshot

from .safety import GraphImportError, clamp_int

MAX_GRAPH_BYTES = 64 * 1024 * 1024
MAX_LABELS_BYTES = 2 * 1024 * 1024        # the community-labels sidecar is a few KB in practice
MODES = ("community", "path")
_LABEL_FILE = ".graphify_labels.json"
_DUNDER = re.compile(r"^\.?__\w+__(\(\))?$")      # __init__, .__init__(), __all__ ...


def read_graph_json(path: Path, *, max_bytes: int = MAX_GRAPH_BYTES) -> Dict[str, Any]:
    """Read and shape-check a graphify graph. Errors are generic (no paths)."""
    try:
        size = path.stat().st_size
    except OSError:
        raise GraphImportError("graph_not_found", "The graph file was not found", status=404)
    if size > max_bytes:
        raise GraphImportError("graph_too_large", "The graph file is too large to import", status=413)
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        raise GraphImportError("bad_graph", "The graph file is not valid JSON", status=422)
    nodes = doc.get("nodes") if isinstance(doc, dict) else None
    links = (doc.get("links") if "links" in doc else doc.get("edges")) if isinstance(doc, dict) else None
    if not isinstance(nodes, list) or not isinstance(links, list):
        raise GraphImportError("bad_graph", "Not a graphify/NetworkX node-link graph (needs nodes and links)", status=422)
    return doc


class GraphifyAdapter:
    engine = "graphify"

    def __init__(self, graph_path: Path) -> None:
        self._path = Path(graph_path)

    # -- public ---------------------------------------------------------------
    def health(self) -> Dict[str, Any]:
        try:
            doc = read_graph_json(self._path)
        except GraphImportError as exc:
            return {"engine": self.engine, "status": "error", "code": exc.code}
        return {"engine": self.engine, "status": "ok", "nodes": len(doc["nodes"])}

    def fetch_snapshot(self, q: FileGraphQuery, *, root_name: str = "Codebase") -> GraphSnapshot:
        if q.mode not in MODES:
            raise GraphImportError("bad_mode", "Mode must be 'community' or 'path'")
        doc = read_graph_json(self._path)
        max_nodes = clamp_int(q.max_nodes, 10, 5000, 5000)
        max_domains = clamp_int(q.max_domains, 1, 200, 40)
        prefix = _clean_prefix(q.path_prefix)

        symbols_by_file = self._symbols_by_file(doc["nodes"], prefix)
        if not symbols_by_file:
            raise GraphImportError("root_not_found", "No code files in the graph match that path prefix", status=404)

        if q.mode == "community":
            domains = self._community_domains(doc["nodes"], symbols_by_file, prefix,
                                              labels=self._labels(), min_size=clamp_int(q.min_size, 1, 10_000, 3))
        else:
            domains = self._path_domains(symbols_by_file, clamp_int(q.domain_depth, 1, 6, 2))

        # keep the largest domains (by symbol count); stable tie-break on name
        ranked = sorted(domains.items(), key=lambda kv: (-sum(len(v) for v in kv[1].values()), kv[0].casefold()))
        truncated = len(ranked) > max_domains
        ranked = ranked[:max_domains]

        root = GraphNode(id="root", name=root_name)
        snap = GraphSnapshot(root=root, nodes={"root": root})
        for di, (dname, files) in enumerate(ranked):
            did = f"d{di}"
            if len(snap.nodes) + 1 > max_nodes:
                truncated = True
                break
            snap.nodes[did] = GraphNode(id=did, name=dname)
            snap.edges.append(GraphEdge("root", did))
            for fi, (fname, syms) in enumerate(sorted(files.items(), key=lambda kv: kv[0].casefold())):
                fid = f"{did}f{fi}"
                if len(snap.nodes) + 1 > max_nodes:
                    truncated = True
                    break
                snap.nodes[fid] = GraphNode(id=fid, name=fname)
                snap.edges.append(GraphEdge(did, fid))
                for si, sname in enumerate(sorted(set(syms), key=str.casefold)):
                    if len(snap.nodes) + 1 > max_nodes:
                        truncated = True
                        break
                    sid = f"{fid}s{si}"
                    snap.nodes[sid] = GraphNode(id=sid, name=sname)
                    snap.edges.append(GraphEdge(fid, sid))
        snap.truncated = truncated
        return snap

    # -- helpers ---------------------------------------------------------------
    def _labels(self) -> Dict[int, str]:
        """Community names from the sidecar next to graph.json. It gets the same treatment as
        graph.json: its resolved path (symlinks followed) must stay inside the graph's own
        folder and it is size-capped, so it cannot be used to read some other JSON file and
        surface its values as domain names."""
        try:
            folder = self._path.parent.resolve()
            f = (folder / _LABEL_FILE).resolve()
            if not f.is_relative_to(folder) or not f.is_file() or f.stat().st_size > MAX_LABELS_BYTES:
                return {}
            raw = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        out: Dict[int, str] = {}
        for k, v in (raw.items() if isinstance(raw, dict) else []):
            try:
                out[int(k)] = str(v)
            except (TypeError, ValueError):
                continue
        return out

    @staticmethod
    def _symbols_by_file(nodes: List[Any], prefix: str) -> Dict[str, List[Tuple[str, Optional[int]]]]:
        """source_file -> [(symbol label, community)] for code nodes. A graphify "file"
        node (label == file basename) is a container, not a symbol; docstring/rationale
        nodes and dunder methods (``.__init__()``) are skipped, and so are files left
        with no symbols (empty ``__init__.py`` would only add noise to a routing taxonomy)."""
        out: Dict[str, List[Tuple[str, Optional[int]]]] = defaultdict(list)
        for n in nodes:
            if not isinstance(n, dict) or n.get("file_type") != "code":
                continue
            src = re.sub(r"^(\./)+", "", str(n.get("source_file") or "").replace("\\", "/")).lstrip("/")
            label = str(n.get("label") or "").strip()
            if not src or not label or (prefix and not (src == prefix or src.startswith(prefix + "/"))):
                continue
            comm = n.get("community")
            comm = comm if isinstance(comm, int) else None
            if label == PurePosixPath(src).name or _DUNDER.match(label):
                continue
            out[src].append((label, comm))
        return out

    @staticmethod
    def _community_domains(nodes, symbols_by_file, prefix, *, labels, min_size):
        per_comm_files: Dict[int, Dict[str, List[str]]] = defaultdict(lambda: defaultdict(list))
        for src, syms in symbols_by_file.items():
            for label, comm in syms:
                if comm is not None:
                    per_comm_files[comm][src].append(label)
        domains: Dict[str, Dict[str, List[str]]] = {}
        used: set = set()                           # every name actually emitted, casefolded
        for comm in sorted(per_comm_files):         # fixed order: the same graph always names things the same way
            files = per_comm_files[comm]
            size = sum(len(v) for v in files.values())
            if size < min_size:
                continue
            base = labels.get(comm) or f"Community {comm}"
            name, n = base, 0
            while name.casefold() in used:          # check against EVERY emitted name, not just the originals,
                n += 1                              # so a generated "Same (1)" can't clobber a real "Same (1)"
                # Not parenthetical: the taxonomy parser drops a trailing "(...)" from a domain
                # heading, which would turn "Core (3)" back into "Core" and merge the two.
                name = f"{base} - {comm}" if n == 1 else f"{base} - {comm}-{n}"
            used.add(name.casefold())
            domains[name] = {f: list(v) for f, v in files.items()}
        return domains

    @staticmethod
    def _path_domains(symbols_by_file, depth):
        domains: Dict[str, Dict[str, List[str]]] = defaultdict(dict)
        for src, syms in symbols_by_file.items():
            parts = [p for p in src.split("/") if p]
            dirs = parts[:-1]
            # "(root)" would be stripped to an empty name by the taxonomy parser (it drops a
            # trailing parenthetical from L2 headings), so use a plain visible name.
            domain = "/".join(dirs[:depth]) if dirs else "Root files"
            domains[domain][src] = [label for label, _ in syms]
        return dict(domains)


def _clean_prefix(p: str) -> str:
    p = (p or "").replace("\\", "/").strip().strip("/")
    if p and not re.fullmatch(r"[A-Za-z0-9_.\-/ ]{1,200}", p) or ".." in p.split("/"):
        raise GraphImportError("bad_prefix", "Path prefix may only contain letters, digits, '_', '-', '.', '/' and spaces")
    return p
