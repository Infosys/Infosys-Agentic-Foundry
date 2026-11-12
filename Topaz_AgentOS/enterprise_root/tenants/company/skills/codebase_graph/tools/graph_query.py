"""
Query a knowledge graph (graph.json) that lives in the tenant's shared storage: a code graph
built by graphify, or a business ontology uploaded through Skill Builder (already converted to the
same node-link format).

Read-only and dependency-free. Reads JSON from stdin, writes JSON to stdout.

The graph is looked up by NAME under <tenant>/shared/graphs/<name>/graph.json (the
tenant folder is derived from IAF_AGENT_ROOT, which the tool loader sets). The name is
pattern-checked and the resolved path must stay inside shared/graphs; no other file can
be read. Nothing is ever written.

Actions: list | stats | search | explain | path | community
"""

TOOL_SPEC = {
    "name": "graph_query",
    "description": (
        "Answer questions from a published knowledge graph (a code graph or an uploaded ontology). "
        "action='list' shows the published graphs; "
        "action='stats' summarises the graph (counts, communities, most-connected nodes); "
        "action='search' finds nodes by keywords in `query`; "
        "action='explain' shows one node (`query`) with its neighbours grouped by relation; "
        "action='path' finds the shortest connection from `query` to `target`; "
        "action='community' lists the members of a community named or numbered in `query`. "
        "Every edge carries a confidence: EXTRACTED = stated in the source, INFERRED = a guess. "
        "Pass empty strings for parameters an action does not use."
    ),
    "parameters": {
        "action": {"type": "str", "description": "One of: list, stats, search, explain, path, community"},
        "graph": {"type": "str", "description": "Graph name (folder under shared/graphs). Empty = the only published graph; use action='list' to see the names"},
        "query": {"type": "str", "description": "Keywords (search), a node name/id (explain), the start node (path), or a community name/number (community). Empty for stats."},
        "target": {"type": "str", "description": "End node for action='path'. Empty otherwise."},
    },
    "timeout": 30,
}

import json
import os
import re
import sys
from collections import Counter, deque
from pathlib import Path

MAX_BYTES = 64 * 1024 * 1024            # keep in sync with MAX_QUERY_BYTES in graph_import/graph_store.py
MAX_SIDECAR_BYTES = 2 * 1024 * 1024     # the community-labels file is a few KB in practice
# The skill loader cuts a tool's stdout at 10 KB (skill_tool_loader.STDOUT_CAP) *before* the
# model sees it, which would turn a bigger reply into invalid JSON. Stay under that limit.
MAX_OUT_CHARS = 10000
LIMIT = 15
NAME_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
STOP = {"a", "an", "and", "the", "of", "to", "in", "is", "for", "how", "what", "does", "do", "with", "on", "or"}


class Err(Exception):
    pass


def graphs_dir():
    root = os.environ.get("IAF_AGENT_ROOT", "")
    if not root:
        raise Err("agent root is not set; this tool must run inside AgentOS")
    return (Path(root).resolve().parents[1] / "shared" / "graphs").resolve()


def denied_graphs():
    """Graph folders this caller may not read, resolved by the agent (which holds the caller's
    entitlements) and passed in IAF_DENIED_GRAPHS. ["*"] means every graph. Unparseable -> deny all."""
    raw = os.environ.get("IAF_DENIED_GRAPHS", "")
    if not raw:
        return set()
    try:
        val = json.loads(raw)
        return {str(x) for x in val} if isinstance(val, list) else {"*"}
    except ValueError:
        return {"*"}


def published():
    """Names of the graphs published for this tenant that this caller may read (folders holding
    a graph.json). Denied graphs are left out, so they are neither listed nor offered as a default."""
    base = graphs_dir()
    denied = denied_graphs()
    if "*" in denied or not base.is_dir():
        return []
    return sorted(d.name for d in base.iterdir()
                  if NAME_RE.match(d.name) and d.name not in denied
                  and (d / "graph.json").resolve().is_relative_to(base)
                  and (d / "graph.json").is_file())


def load(name):
    if not (name or "").strip():             # no name given: use the only published graph
        names = published()
        if len(names) == 1:
            name = names[0]
        else:
            raise Err("say which graph to use: " + (", ".join(names) if names else "none is published yet"))
    if not NAME_RE.match(name or ""):
        raise Err("graph name must be 1-64 letters, digits, '_' or '-'")
    denied = denied_graphs()
    base = graphs_dir()
    path = (base / name / "graph.json").resolve()
    # A denied graph takes the same branch (and the same message) as a missing one, so a
    # restricted graph is not revealed; published() already leaves it out of the suggestions.
    if "*" in denied or name in denied or not path.is_relative_to(base) or not path.is_file():
        names = published()
        raise Err(f"no graph named '{name}' is published for this tenant"
                  + (f"; published: {', '.join(names)}" if names else ""))
    if path.stat().st_size > MAX_BYTES:
        raise Err("the graph file is too large to query")
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        raise Err("the graph file is not valid JSON")
    if not isinstance(doc, dict):        # valid JSON that is not an object ([], null, 123 ...)
        raise Err("the file is not a graphify node-link graph")
    nodes, links = doc.get("nodes"), doc.get("links", doc.get("edges"))
    if not isinstance(nodes, list) or not isinstance(links, list):
        raise Err("the file is not a graphify node-link graph")
    return nodes, links, read_labels(path.parent)


def read_labels(folder):
    """Community names from <folder>/.graphify_labels.json, or {}. The sidecar gets the same
    treatment as graph.json: its resolved path (symlinks followed) must stay inside the
    graph's own folder, and it is size-capped, so it cannot be used to read another file."""
    try:
        folder = folder.resolve()
        lf = (folder / ".graphify_labels.json").resolve()
        if not lf.is_relative_to(folder) or not lf.is_file() or lf.stat().st_size > MAX_SIDECAR_BYTES:
            return {}
        raw = json.loads(lf.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            return {}
        return {int(k): str(v) for k, v in raw.items()}
    except (OSError, ValueError, TypeError):
        return {}


class G:
    def __init__(self, nodes, links, labels):
        self.labels = labels
        self.n = {x["id"]: x for x in nodes if isinstance(x, dict) and isinstance(x.get("id"), (str, int))}
        self.adj = {k: [] for k in self.n}
        for e in links:
            if not isinstance(e, dict):
                continue
            s, t = e.get("source"), e.get("target")
            if isinstance(s, (str, int)) and isinstance(t, (str, int)) and s in self.n and t in self.n:
                rel = str(e.get("relation", "related"))
                conf = str(e.get("confidence", ""))
                self.adj[s].append((t, rel, conf, "out"))
                self.adj[t].append((s, rel, conf, "in"))

    def comm(self, node):
        c = node.get("community")
        return self.labels.get(c, f"Community {c}") if isinstance(c, int) else None

    def brief(self, nid):
        x = self.n[nid]
        out = {"id": nid, "label": x.get("label"), "type": x.get("file_type"), "file": x.get("source_file"),
               "location": x.get("source_location"), "community": self.comm(x), "degree": len(self.adj[nid])}
        if x.get("description"):
            out["description"] = str(x["description"])[:160]
        return out

    def ref(self, nid):
        """Smallest identifying citation for a node: id, label, file, location."""
        x = self.n[nid]
        return {"id": nid, "label": x.get("label"), "file": x.get("source_file"), "location": x.get("source_location")}

    def find(self, q):
        """Best matching node ids for a name/id (exact first, then fuzzy)."""
        ql = (q or "").strip().lower()
        if not ql:
            return []
        if q in self.n:
            return [q]

        def norm(s):
            return re.sub(r"\(\)$", "", str(s or "").lower().lstrip(".")).strip()
        qn = norm(ql)
        exact = [k for k, x in self.n.items() if x.get("file_type") != "rationale" and norm(x.get("label")) == qn]
        if exact:
            return sorted(exact, key=lambda k: -len(self.adj[k]))[:5]
        return [k for k, _ in self.score(ql)[:5]]

    def score(self, text):
        toks = [t for t in re.findall(r"[a-z0-9_]+", text.lower()) if t not in STOP and len(t) > 1]
        out = []
        for k, x in self.n.items():
            if x.get("file_type") == "rationale":
                continue
            label = str(x.get("label", "")).lower()
            src = (str(x.get("source_file", "")) + " " + str(x.get("file_type", ""))).lower()
            desc = str(x.get("description", "")).lower()
            sc = sum(3 for t in toks if t in label) + sum(1 for t in toks if t in src) + sum(1 for t in toks if t in desc)
            if toks and all(t in label or t in src or t in desc for t in toks):
                sc += 2
            if sc:
                out.append((k, sc + min(len(self.adj[k]), 50) / 100.0))
        return sorted(out, key=lambda kv: -kv[1])


def stats(g):
    rel = Counter(r for lst in g.adj.values() for _, r, _, d in lst if d == "out")
    comm = Counter(g.comm(x) for x in g.n.values() if g.comm(x))
    real = [k for k, x in g.n.items() if x.get("file_type") != "rationale"]   # code symbols or ontology entities
    gods = sorted(real, key=lambda k: -len(g.adj[k]))[:10]
    kinds = Counter(str(x.get("file_type")) for x in g.n.values() if x.get("file_type") != "rationale")
    return {"nodes": len(g.n), "edges": sum(len(v) for v in g.adj.values()) // 2,
            "files": len({x.get("source_file") for x in g.n.values() if x.get("source_file")}),
            "relations": dict(rel.most_common(10)), "largest_communities": comm.most_common(10),
            "node_types": dict(kinds.most_common(10)),
            "most_connected": [g.brief(k) for k in gods]}


def search(g, q):
    return {"query": q, "matches": [dict(g.brief(k), score=round(s, 2)) for k, s in g.score(q)[:LIMIT]]}


def explain(g, q):
    ids = g.find(q)
    if not ids:
        return {"error": f"no node matches '{q}'"}
    nid = ids[0]
    groups = {}
    for t, rel, conf, d in g.adj[nid]:
        if g.n[t].get("file_type") == "rationale":
            continue
        # id + location let the caller tell apart same-named symbols (many classes define .run())
        # and cite the exact place; confidence says whether the edge was read or guessed.
        groups.setdefault(f"{rel} ({'->' if d == 'out' else '<-'})", []).append(
            {"id": t, "label": g.n[t].get("label"), "file": g.n[t].get("source_file"),
             "location": g.n[t].get("source_location"), "confidence": conf})
    shown = {k: v[:12] for k, v in sorted(groups.items(), key=lambda kv: -len(kv[1]))[:10]}
    doc = [g.n[t].get("label") for t, rel, _, _ in g.adj[nid] if rel == "rationale_for"][:2]
    return {"node": g.brief(nid), "docstring_notes": doc, "neighbours": shown,
            "also_matched": [g.brief(k) for k in ids[1:4]] or None}


def path(g, a, b):
    sa, sb = g.find(a), g.find(b)
    if not sa or not sb:
        return {"error": f"could not find {'the start' if not sa else 'the end'} node"}
    src, dst = sa[0], sb[0]
    prev, seen, dq = {src: None}, {src}, deque([src])
    while dq and dst not in prev and len(seen) < 300000:
        cur = dq.popleft()
        for t, rel, conf, d in g.adj[cur]:
            if t in seen or rel == "rationale_for" or g.n[t].get("file_type") == "rationale":
                continue
            seen.add(t)
            prev[t] = (cur, rel, conf, d)
            dq.append(t)
    if dst not in prev:
        return {"from": g.brief(src), "to": g.brief(dst), "path": None, "note": "no connection found"}
    steps, cur = [], dst
    while prev[cur]:
        p, rel, conf, d = prev[cur]
        steps.append({"from": g.n[p].get("label"), "relation": rel, "direction": d, "to": g.n[cur].get("label"),
                      "confidence": conf, "from_node": g.ref(p), "to_node": g.ref(cur)})
        cur = p
    steps.reverse()
    return {"from": g.brief(src), "to": g.brief(dst), "hops": len(steps), "path": steps}


def community(g, q):
    ql = (q or "").strip().lower()
    cid = None
    # a bare number, or the generated name `stats` shows for an unlabelled community ("Community 12")
    numeric = re.fullmatch(r"(?:community\s+)?(\d{1,9})", ql)
    if numeric:
        cid = int(numeric.group(1))
    else:
        for k, v in g.labels.items():
            if v.lower() == ql:
                cid = k
                break
        if cid is None:
            for k, v in g.labels.items():
                if ql and ql in v.lower():
                    cid = k
                    break
    if cid is None:
        return {"error": f"no community matches '{q}'", "hint": "use action='stats' to list the largest communities"}
    members = [k for k, x in g.n.items() if x.get("community") == cid and x.get("file_type") != "rationale"]
    if not members:
        return {"error": f"no community matches '{q}'", "hint": "use action='stats' to list the largest communities"}
    members.sort(key=lambda k: -len(g.adj[k]))
    files = Counter(g.n[k].get("source_file") for k in members)
    return {"community": g.labels.get(cid, f"Community {cid}"), "id": cid, "size": len(members),
            "files": files.most_common(10), "top_members": [g.brief(k) for k in members[:LIMIT]]}


def main():
    data = json.load(sys.stdin)
    action = str(data.get("action", "")).strip().lower()
    try:
        if action == "list":
            names = published()
            res = {"graphs": names}
            while res["graphs"] and len(json.dumps(res)) > MAX_OUT_CHARS - 50:   # many/long names: list what fits
                res.update(graphs=res["graphs"][:len(res["graphs"]) * 9 // 10], total=len(names), truncated=True)
            sys.stdout.write(fit(res, MAX_OUT_CHARS))
            return
        nodes, links, labels = load(str(data.get("graph", "")).strip())
        g = G(nodes, links, labels)
        q, t = str(data.get("query", "")), str(data.get("target", ""))
        if action == "stats":
            res = stats(g)
        elif action == "search":
            res = search(g, q) if q.strip() else {"error": "search needs keywords in `query`"}
        elif action == "explain":
            res = explain(g, q)
        elif action == "path":
            res = path(g, q, t)
        elif action == "community":
            res = community(g, q)
        else:
            raise Err("action must be one of: list, stats, search, explain, path, community")
    except Err as exc:
        res = {"error": str(exc)}
    except Exception:                 # never let a traceback (it carries file paths) reach the loader
        res = {"error": "the graph could not be queried"}
    sys.stdout.write(fit(res, MAX_OUT_CHARS))


def trim(obj, keep):
    """Copy of `obj` with every list cut to `keep` items and long strings shortened."""
    if isinstance(obj, list):
        return [trim(x, keep) for x in obj[:keep]]
    if isinstance(obj, dict):
        return {k: trim(v, keep) for k, v in obj.items()}
    if isinstance(obj, str) and len(obj) > 160:
        return obj[:157] + "..."
    return obj


def fit(res, cap):
    """JSON text of `res` that is at most `cap` characters AND still valid JSON.

    The loader cuts stdout at 10 KB, so an oversized reply would otherwise arrive as broken
    JSON. Instead shrink the lists step by step (keeping structure and flagging it), and fall
    back to a small explicit error rather than ever cutting a string in the middle."""
    out = json.dumps(res, ensure_ascii=False)
    if len(out) <= cap:
        return out
    for keep in (10, 6, 4, 3, 2, 1):
        shrunk = trim(res, keep)
        if isinstance(shrunk, dict):
            shrunk["truncated"] = True
        out = json.dumps(shrunk, ensure_ascii=False)
        if len(out) <= cap:
            return out
    return json.dumps({"truncated": True, "error": "the result is too large; ask a narrower question"})


if __name__ == "__main__":
    main()
