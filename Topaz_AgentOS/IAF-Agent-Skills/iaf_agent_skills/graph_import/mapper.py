"""Deterministic GraphSnapshot -> taxonomy draft mapping.

Rules (the same input always yields the same draft, so a re-import diffs cleanly):

* The root node is the taxonomy (L1 = frontmatter ``name``).
* depth 1 -> L2 domain, depth 2 -> L3 section.
* depth >= 3 is flattened into bullet activities under its L3 ancestor
  (``Child / Grandchild``).
* Walk order is breadth-first, siblings sorted by name; a node reached again by
  another parent is kept under the *first* parent only, and every such decision
  is written to the loss report instead of being dropped silently.
* Skills are NOT assigned here. A graph carries no skill information.

Labels from an external graph are untrusted text that ends up inside a markdown
file the router reads, so every string goes through :func:`sanitize_text`.
"""
from __future__ import annotations

import json
import re
import unicodedata
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from agentos_contracts.graph_source import GraphSnapshot

MAX_NAME = 120
MAX_ACTIVITY = 200
MAX_ACTIVITIES_PER_SECTION = 30

# POST /taxonomy-import rejects a body larger than this (413). Kept in step with
# `_TAXONOMY_IMPORT_MAX_BYTES` in routers/context_manager.py (a Studio test asserts they match).
IMPORT_PAYLOAD_MAX_BYTES = 512 * 1024
_PAYLOAD_OVERHEAD = 4096        # provenance, description, JSON braces
_SKILL_ALLOWANCE = 96           # per section: `"skill":"<name>"` plus separators, with the name up to 64 chars

_LEAD_MARKUP = re.compile(r"^[\s#>*+\-=_~|]+")
_LEAD_ENUM = re.compile(r"^\d+[.)]\s+")
_YAML_BAD = re.compile(r"[\[\]{}#|>*&!%@]")


def sanitize_text(value: Any, max_len: int = MAX_NAME, *, yaml_safe: bool = False) -> str:
    """Single-line, markup-inert text. Removes control/format/bidi characters,
    HTML-comment delimiters (which could forge ``<!-- skill: -->`` tags), angle
    brackets and back-ticks, and any leading markdown marker (``#``, ``-``, ``1.``)."""
    s = unicodedata.normalize("NFKC", "" if value is None else str(value))
    out = []
    for c in s:
        cat = unicodedata.category(c)
        if c in ("\n", "\r", "\t") or cat in ("Zl", "Zp"):
            out.append(" ")
        elif cat in ("Cc", "Cf", "Cs", "Co", "Cn"):
            continue
        else:
            out.append(c)
    s = "".join(out)
    s = s.replace("<!--", " ").replace("-->", " ").replace("<", " ").replace(">", " ").replace("`", "'")
    s = re.sub(r"\s+", " ", s).strip()
    s = _LEAD_MARKUP.sub("", s)
    s = _LEAD_ENUM.sub("", s)
    if yaml_safe:
        s = _YAML_BAD.sub(" ", s).replace(": ", " - ")
        s = re.sub(r"\s+", " ", s).strip(" :'\"")
    return s[:max_len].strip()


@dataclass
class LossEntry:
    kind: str       # multi_parent | cycle | unnamed | duplicate_name | promoted_leaf | flattened | truncated | activities_capped | renamed | payload_limit
    node: str
    detail: str = ""

    def to_dict(self) -> Dict[str, str]:
        return {"kind": self.kind, "node": self.node, "detail": self.detail}


@dataclass
class TaxonomyDraft:
    name: str
    description: str
    domains: List[Dict[str, Any]] = field(default_factory=list)
    loss: List[LossEntry] = field(default_factory=list)
    stats: Dict[str, int] = field(default_factory=dict)
    source: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "domains": self.domains,
            "loss": [l.to_dict() for l in self.loss],
            "stats": self.stats,
            "source": self.source,
        }


def map_snapshot(
    snap: GraphSnapshot,
    *,
    taxonomy_name: str = "",
    description: str = "",
) -> TaxonomyDraft:
    loss: List[LossEntry] = []
    nodes = snap.nodes

    children: Dict[str, List[str]] = {}
    for e in snap.edges:
        children.setdefault(e.parent_id, []).append(e.child_id)
    for pid in children:
        children[pid].sort(key=lambda cid: (nodes[cid].name.casefold() if cid in nodes else "", cid))

    root = snap.root
    name = sanitize_text(taxonomy_name, yaml_safe=True) or sanitize_text(root.name, yaml_safe=True)
    if not name:
        name = "Imported taxonomy"
        loss.append(LossEntry("unnamed", root.id, "Root has no usable name; using a placeholder"))

    # BFS from the root: assigns each node its depth and its (first) parent.
    depth: Dict[str, int] = {root.id: 0}
    parent: Dict[str, str] = {}
    order: List[str] = []
    q = deque([root.id])
    while q:
        cur = q.popleft()
        for cid in children.get(cur, []):
            if cid not in nodes:
                continue
            if cid in depth:
                if cid == root.id or _is_ancestor(cid, cur, parent):
                    loss.append(LossEntry("cycle", _label(nodes[cid]),
                                          f"edge from '{_label(nodes[cur])}' back to an ancestor ignored"))
                else:
                    keeper = _label(nodes[parent[cid]]) if cid in parent else "root"
                    loss.append(LossEntry("multi_parent", _label(nodes[cid]),
                                          f"also under '{_label(nodes[cur])}'; kept under '{keeper}'"))
                continue
            depth[cid] = depth[cur] + 1
            parent[cid] = cur
            order.append(cid)
            q.append(cid)

    kids: Dict[str, List[str]] = {}
    for cid in order:
        kids.setdefault(parent[cid], []).append(cid)

    domains: List[Dict[str, Any]] = []
    dropped_unnamed = 0
    used_domains: set = set()
    for did in kids.get(root.id, []):
        dnode = nodes[did]
        dname = sanitize_text(dnode.name)
        if not dname:
            dropped_unnamed += 1 + _count_subtree(did, kids)
            loss.append(LossEntry("unnamed", did, "Domain-level node without a name; its sub-tree was skipped"))
            continue
        dname = _unique(dname, used_domains, loss, "domain", key=_domain_key)
        sections: List[Dict[str, Any]] = []
        used_sections: set = set()
        for sid in kids.get(did, []):
            snode = nodes[sid]
            sname = sanitize_text(snode.name)
            if not sname:
                dropped_unnamed += 1 + _count_subtree(sid, kids)
                loss.append(LossEntry("unnamed", sid, f"Section under '{dname}' without a name; sub-tree skipped"))
                continue
            sname = _unique(sname, used_sections, loss, f"section in '{dname}'")
            acts: List[str] = []
            d = sanitize_text(snode.description, MAX_ACTIVITY)
            if d:
                acts.append(d)
            flat = list(_flatten(sid, kids, nodes, ()))
            if flat:
                loss.append(LossEntry("flattened", f"{dname} > {sname}",
                                      f"{len(flat)} deeper node(s) turned into activities"))
            acts.extend(flat)
            if len(acts) > MAX_ACTIVITIES_PER_SECTION:
                loss.append(LossEntry("activities_capped", f"{dname} > {sname}",
                                      f"{len(acts) - MAX_ACTIVITIES_PER_SECTION} activities beyond the cap dropped"))
                acts = acts[:MAX_ACTIVITIES_PER_SECTION]
            sections.append({"name": sname, "skill": "", "activities": acts, "source_id": sid})
        if not sections:
            # A domain with no usable children still has to be routable: promote it.
            loss.append(LossEntry("promoted_leaf", dname, "No child sections; domain name reused as its only section"))
            d = sanitize_text(dnode.description, MAX_ACTIVITY)
            sections.append({"name": dname, "skill": "", "activities": [d] if d else [], "source_id": did})
        domains.append({"name": dname, "sections": sections, "source_id": did})

    if snap.truncated:
        loss.append(LossEntry("truncated", root.name,
                              "The graph is larger than the depth/size limits; the draft is partial"))

    section_count = sum(len(d["sections"]) for d in domains)
    stats = {
        "nodes_fetched": len(nodes),
        "domains": len(domains),
        "sections": section_count,
        "activities": sum(len(s["activities"]) for d in domains for s in d["sections"]),
        "loss_entries": len(loss),
        "skipped_unnamed": dropped_unnamed,
    }
    return TaxonomyDraft(
        name=name,
        description=sanitize_text(description, 200, yaml_safe=True),
        domains=domains,
        loss=loss,
        stats=stats,
        source=dict(snap.source),
    )


def fit_import_payload(draft: TaxonomyDraft, budget: int = IMPORT_PAYLOAD_MAX_BYTES) -> TaxonomyDraft:
    """Trim the draft so the JSON the UI will post to /taxonomy-import fits the import limit.

    The preview used to accept up to 5,000 nodes, which can serialise past the import's
    512 KiB cap; the user would only find out after assigning every skill. Domains are kept
    in order; once the budget is used up the remaining sections/domains are dropped and the
    loss report says how many. The estimate adds an allowance per section for the skill name
    that is assigned after the preview."""
    def size(obj) -> int:
        return len(json.dumps(obj, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))

    used = _PAYLOAD_OVERHEAD + size(draft.name) + size(draft.description)
    kept: List[Dict[str, Any]] = []
    dropped_sections = dropped_domains = 0
    full = False
    for dom in draft.domains:
        if full:
            dropped_domains += 1
            dropped_sections += len(dom["sections"])
            continue
        dom_cost = size(dom["name"]) + 48        # {"name":..,"sections":[..]} wrapper
        keep_secs: List[Dict[str, Any]] = []
        for sec in dom["sections"]:
            cost = size({"name": sec["name"], "activities": sec["activities"]}) + _SKILL_ALLOWANCE
            if used + dom_cost + cost > budget:
                full = True
                dropped_sections += 1
                continue
            dom_cost += cost
            keep_secs.append(sec)
        if keep_secs:
            used += dom_cost
            kept.append({**dom, "sections": keep_secs})
        else:
            dropped_domains += 1
    if dropped_sections or dropped_domains:
        draft.domains = kept
        draft.loss.append(LossEntry(
            "payload_limit", draft.name,
            f"{dropped_sections} section(s) in {dropped_domains} domain(s) were left out so the draft fits the "
            f"{budget // 1024} KiB import limit; narrow the root, depth or path prefix to import them"))
        draft.stats.update({
            "domains": len(kept),
            "sections": sum(len(d["sections"]) for d in kept),
            "activities": sum(len(s["activities"]) for d in kept for s in d["sections"]),
            "loss_entries": len(draft.loss),
        })
    return draft


def _label(n) -> str:
    return sanitize_text(n.name) or n.id


def _is_ancestor(candidate: str, node: str, parent: Dict[str, str]) -> bool:
    seen = 0
    while node in parent and seen < 10_000:
        node = parent[node]
        if node == candidate:
            return True
        seen += 1
    return False


def _count_subtree(nid: str, kids: Dict[str, List[str]]) -> int:
    n, stack = 0, list(kids.get(nid, []))
    while stack:
        c = stack.pop()
        n += 1
        stack.extend(kids.get(c, []))
    return n


def _flatten(nid: str, kids: Dict[str, List[str]], nodes, trail):
    for cid in kids.get(nid, []):
        label = sanitize_text(nodes[cid].name, MAX_ACTIVITY)
        if not label:
            continue
        path = trail + (label,)
        yield " / ".join(path)[:MAX_ACTIVITY]
        yield from _flatten(cid, kids, nodes, path)


_L_PREFIX = re.compile(r"^L\d+:\s*")
_TRAILING_PAREN = re.compile(r"\s*\([^)]*\)\s*$")


def _domain_key(name: str) -> str:
    """The name as the taxonomy parser will read it back: a leading ``L2:`` and a
    trailing parenthetical (``(PtP)``) are dropped. Two domains with the same key
    become ONE domain in the index, so uniqueness is judged on this, not on the text."""
    return _TRAILING_PAREN.sub("", _L_PREFIX.sub("", name).strip()).strip().casefold()


def _section_key(name: str) -> str:
    return _L_PREFIX.sub("", name).strip().casefold()


def _unique(name: str, used: set, loss: List[LossEntry], where: str, key=_section_key) -> str:
    """Return `name`, or `name - N` when its parsed form is already taken.

    The suffix is NOT parenthetical (the parser strips trailing parentheses from domain
    names, which would undo it) and the base is shortened so the whole name still fits
    MAX_NAME (the renderer truncates longer headings, which would undo it too)."""
    if key(name) not in used:
        used.add(key(name))
        return name
    n = 2
    while True:
        suffix = f" - {n}"
        new = f"{name[:MAX_NAME - len(suffix)].rstrip()}{suffix}"
        if key(new) not in used:
            break
        n += 1
    used.add(key(new))
    loss.append(LossEntry("duplicate_name", name, f"duplicate {where}; renamed '{new}'"))
    return new
