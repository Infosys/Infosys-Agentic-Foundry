"""
Context Graph Builder

Parses enterprise markdown context files into a D3-compatible { nodes, links, stats }
graph for the Knowledge Graph → Context Structure tab.

Scans (all auto-discovered — drop a new file and it appears on next refresh):
  taxonomy/*_taxonomy.md   → L1 domain → L2/L3/L4/L5 hierarchy nodes + hierarchy edges
  skills/**/SKILL.md       → skill nodes + skill_reads + skill_covers edges
  contexts/entities/*.md   → entity nodes + entity_via edges
  contexts/*.md            → context_file nodes (pillar files: judgment, benchmarks, etc.)

Caching: 30-second TTL; rebuilds automatically if any source file's mtime changes.
"""

import re
import time
import yaml
from pathlib import Path

# { cache_key: (built_at_ts, max_mtime_seen, graph_data) }
_cache: dict = {}
_CACHE_TTL = 30  # seconds



def _parse_frontmatter(text: str) -> tuple:
    """Split YAML frontmatter from markdown body. Returns (meta_dict, body_str)."""
    if text.startswith("---"):
        end = text.find("\n---", 3)
        if end != -1:
            try:
                meta = yaml.safe_load(text[3:end]) or {}
            except Exception:
                meta = {}
            return meta, text[end + 4:]
    return {}, text


def _clean_label(raw: str) -> str:
    """'L2: Accounts Payable (PtP) [APQC 9.6.1]' → 'Accounts Payable'"""
    raw = re.sub(r'^L\d+:\s*', '', raw.strip())
    raw = re.sub(r'\[.*?\]', '', raw).strip()
    raw = re.sub(r'\([^)]{1,10}\)', '', raw).strip()
    return raw


def _max_mtime(paths: list) -> float:
    mtimes = []
    for p in paths:
        try:
            mtimes.append(Path(p).stat().st_mtime)
        except Exception:
            pass
    return max(mtimes) if mtimes else 0.0



def build_context_graph(enterprise_root: str, tenant_id: str = "company") -> dict:
    """
    Build and return a D3-compatible graph from the enterprise context files.
    Cached for 30 s; rebuilds if any source file's mtime advances.
    """
    root = Path(enterprise_root).resolve()
    tenant_root = root / "tenants" / tenant_id
    contexts_dir = tenant_root / "shared" / "contexts"
    skills_dir = tenant_root / "skills"
    taxonomy_dir = contexts_dir / "taxonomy"
    entities_dir = contexts_dir / "entities"

    all_files = (
        list(taxonomy_dir.glob("*_taxonomy.md")) +
        list(skills_dir.glob("**/SKILL.md")) +
        list(entities_dir.glob("*.md")) +
        [f for f in contexts_dir.glob("*.md") if f.is_file()]
    )

    cache_key = f"{enterprise_root}:{tenant_id}"
    max_mtime = _max_mtime(all_files)
    now = time.time()

    if cache_key in _cache:
        built_at, cached_mtime, graph_data = _cache[cache_key]
        if now - built_at < _CACHE_TTL and cached_mtime >= max_mtime:
            return graph_data

    graph_data = _build(
        tenant_root, contexts_dir, skills_dir, taxonomy_dir, entities_dir
    )
    _cache[cache_key] = (now, max_mtime, graph_data)
    return graph_data



def _build(tenant_root, contexts_dir, skills_dir, taxonomy_dir, entities_dir) -> dict:
    nodes: list = []
    links: list = []
    node_ids: set = set()
    link_set: set = set()

    def add_node(node_id: str, label: str, node_type: str, **kwargs):
        if node_id not in node_ids:
            nodes.append({"id": node_id, "label": label, "node_type": node_type, **kwargs})
            node_ids.add(node_id)

    def add_link(source: str, target: str, link_type: str, weight: int = 1):
        if source in node_ids and target in node_ids:
            key = (source, target)
            if key not in link_set:
                links.append({"source": source, "target": target,
                               "type": link_type, "weight": weight})
                link_set.add(key)

    skill_to_domains: dict = {}
    # { tax_file.stem: (body, l1_id) } — kept for policy pass in Step 6
    taxonomy_bodies: dict = {}

    for tax_file in sorted(taxonomy_dir.glob("*_taxonomy.md")):
        try:
            text = tax_file.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue
        meta, body = _parse_frontmatter(text)

        domain_raw = meta.get("name", tax_file.stem)
        # "Finance & Accounting Taxonomy" → "Finance & Accounting"
        domain_name = re.sub(r'\s+taxonomy\s*$', '', domain_raw, flags=re.IGNORECASE).strip()
        l1_id = f"l1_{tax_file.stem}"
        add_node(l1_id, domain_name, "domain", file=tax_file.name)

        for sk in (meta.get("skills") or []):
            skill_to_domains.setdefault(str(sk), []).append(l1_id)

        _parse_taxonomy_body(body, l1_id, tax_file.stem, add_node, add_link)
        taxonomy_bodies[tax_file.stem] = (body, l1_id)

    skill_context_files: dict = {}
    skill_keywords: dict = {}

    for skill_file in sorted(skills_dir.glob("**/SKILL.md")):
        try:
            text = skill_file.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue
        meta, _ = _parse_frontmatter(text)

        folder = skill_file.parent.name
        skill_id = f"skill_{folder}"
        label = meta.get("name") or folder
        desc = meta.get("description", "")
        keywords = [str(k) for k in (meta.get("keywords") or [])]
        ctx_files = meta.get("context_files") or []

        add_node(skill_id, label, "skill",
                 description=desc,
                 keywords=keywords,
                 context_files=ctx_files,
                 file=str(skill_file.relative_to(skills_dir.parent.parent)))

        skill_keywords[skill_id] = [k.lower() for k in keywords]
        skill_context_files[skill_id] = ctx_files

    # Skill → L1/L2 domain edges (from taxonomy frontmatter)
    for skill_folder, l1_ids in skill_to_domains.items():
        skill_id = f"skill_{skill_folder}"
        if skill_id in node_ids:
            for l1_id in l1_ids:
                add_link(skill_id, l1_id, "skill_covers")

    # context_files are stored as metadata on each skill node (shown in sidebar only)
    # — not added as graph nodes to keep the visual clean

    for ent_file in sorted(entities_dir.glob("*.md")):
        try:
            text = ent_file.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue
        meta, _ = _parse_frontmatter(text)

        entity_id = meta.get("entity_id") or ent_file.stem
        entity_name = meta.get("entity_name") or ent_file.stem
        category = (meta.get("category") or "entity").lower()
        risk_tier = meta.get("risk_tier", "")
        status = meta.get("status", "active")

        node_id = f"entity_{entity_id}"
        add_node(node_id, entity_name, "entity",
                 category=category,
                 risk_tier=risk_tier,
                 status=status,
                 file=ent_file.name)

        # Link entity to the skill that handles its category
        target = "skill_fa_ar" if category == "customer" else (
                 "skill_fa_ap" if category == "vendor" else None)
        if target and target in node_ids:
            add_link(node_id, target, "entity_via")

    process_nodes = [
        (n["id"], n["label"].lower())
        for n in nodes
        if n["node_type"] in ("process", "subprocess")
    ]
    for n in nodes:
        if n["node_type"] != "skill":
            continue
        kw_text = " | ".join(k.lower() for k in (n.get("keywords") or []))
        for pid, plabel in process_nodes:
            if len(plabel) > 4 and plabel in kw_text:
                add_link(n["id"], pid, "skill_covers")

    # Policies attach to taxonomy nodes for sidebar display only; no nodes or edges are created.
    _attach_policy_refs(taxonomy_bodies, nodes, node_ids, links, link_set)

    type_counts: dict = {}
    for n in nodes:
        t = n["node_type"]
        type_counts[t] = type_counts.get(t, 0) + 1

    link_type_counts: dict = {}
    for lk in links:
        t = lk["type"]
        link_type_counts[t] = link_type_counts.get(t, 0) + 1

    return {
        "nodes": nodes,
        "links": links,
        "stats": {
            "total_nodes": len(nodes),
            "total_links": len(links),
            "hierarchy_links": link_type_counts.get("hierarchy", 0),
            "cooccurrence_links": 0,
            "node_types": type_counts,
            "link_types": link_type_counts,
        },
    }



def _parse_taxonomy_body(body: str, l1_id: str, file_stem: str, add_node, add_link):
    """
    Try table-based parsing first (it_ops style: Quick Index table with L2/L3/L4 columns).
    Fall back to heading-based parsing (fa_taxonomy style: ## L2: / ### L3: headings).
    """
    if _parse_table_taxonomy(body, l1_id, file_stem, add_node, add_link):
        return
    _parse_heading_taxonomy(body, l1_id, file_stem, add_node, add_link)


def _parse_table_taxonomy(body: str, l1_id: str, file_stem: str, add_node, add_link) -> bool:
    """
    Detect and parse a Quick Index table with L2/L3/L4/L5 columns.
    Returns True if handled.
    """
    lines = body.split("\n")
    header_idx = -1
    col = {"l2": -1, "l3": -1, "l4": -1, "l5": -1}

    for i, line in enumerate(lines):
        if not line.startswith("|"):
            continue
        cols = [c.strip() for c in line.strip("|").split("|")]
        cl = [c.lower() for c in cols]
        if not (any("l2" in c for c in cl) and any("l3" in c for c in cl)):
            continue
        header_idx = i
        for j, c in enumerate(cl):
            if ("l5" in c or "activity" in c) and col["l5"] < 0:
                col["l5"] = j
            elif "l4" in c and col["l4"] < 0:
                col["l4"] = j
            elif "l3" in c and col["l3"] < 0:
                col["l3"] = j
            elif "l2" in c and col["l2"] < 0:
                col["l2"] = j
        break

    if header_idx < 0 or col["l2"] < 0:
        return False

    seen_l2: dict = {}
    seen_l3: dict = {}
    seen_l4: dict = {}
    l5_count = 0

    for line in lines[header_idx + 2:]:
        if not line.startswith("|"):
            # Stop at next section header but continue scanning for more tables
            if line.startswith("#"):
                break
            continue
        parts = [c.strip() for c in line.strip("|").split("|")]
        if re.match(r'^[-:]+$', parts[0] if parts else ""):
            continue

        def get(k):
            c = col[k]
            return parts[c].strip() if c >= 0 and c < len(parts) else ""

        l2n, l3n, l4n, l5n = get("l2"), get("l3"), get("l4"), get("l5")
        if not l2n or l2n.lower().startswith("l2"):
            continue

        if l2n not in seen_l2:
            nid = f"{file_stem}_l2_{len(seen_l2)+1}"
            seen_l2[l2n] = nid
            add_node(nid, l2n, "process", file=file_stem)
            add_link(l1_id, nid, "hierarchy")

        l3k = f"{l2n}::{l3n}"
        if l3n and l3k not in seen_l3:
            nid = f"{file_stem}_l3_{len(seen_l3)+1}"
            seen_l3[l3k] = nid
            add_node(nid, l3n, "subprocess", file=file_stem)
            add_link(seen_l2[l2n], nid, "hierarchy")

        l4k = f"{l3k}::{l4n}"
        if l4n and l4k not in seen_l4:
            nid = f"{file_stem}_l4_{len(seen_l4)+1}"
            seen_l4[l4k] = nid
            add_node(nid, l4n, "activity", file=file_stem)
            parent = seen_l3.get(l3k, seen_l2.get(l2n, l1_id))
            add_link(parent, nid, "hierarchy")

        if l5n and len(l5n) > 2 and not l5n.lower().startswith("l5"):
            l5_count += 1
            nid = f"{file_stem}_l5_{l5_count}"
            parent = seen_l4.get(l4k, seen_l3.get(l3k, seen_l2.get(l2n, l1_id)))
            add_node(nid, l5n, "task", file=file_stem)
            add_link(parent, nid, "hierarchy")

    return len(seen_l2) > 0


def _parse_heading_taxonomy(body: str, l1_id: str, file_stem: str, add_node, add_link):
    """Parse ## L2: / ### L3: / #### L4: headings and L5 table rows beneath L4."""
    current = {"l2": None, "l3": None, "l4": None}
    counts = {"l2": 0, "l3": 0, "l4": 0, "l5": 0}

    for line in body.split("\n"):
        # L2
        m = re.match(r'^#{1,3}\s+L2:\s+(.+)', line)
        if m:
            name = _clean_label(m.group(1))
            counts["l2"] += 1
            nid = f"{file_stem}_l2_{counts['l2']}"
            current["l2"], current["l3"], current["l4"] = nid, None, None
            add_node(nid, name, "process", file=file_stem)
            add_link(l1_id, nid, "hierarchy")
            continue

        # L3
        m = re.match(r'^#{2,4}\s+L3:\s+(.+)', line)
        if m:
            name = _clean_label(m.group(1))
            counts["l3"] += 1
            nid = f"{file_stem}_l3_{counts['l3']}"
            current["l3"], current["l4"] = nid, None
            parent = current["l2"] or l1_id
            add_node(nid, name, "subprocess", file=file_stem)
            add_link(parent, nid, "hierarchy")
            continue

        # L4
        m = re.match(r'^#{3,5}\s+L4:\s+(.+)', line)
        if m:
            name = _clean_label(m.group(1))
            counts["l4"] += 1
            nid = f"{file_stem}_l4_{counts['l4']}"
            current["l4"] = nid
            parent = current["l3"] or current["l2"] or l1_id
            add_node(nid, name, "activity", file=file_stem)
            add_link(parent, nid, "hierarchy")
            continue

        # L5 table rows under an L4 section
        if current["l4"]:
            m = re.match(r'^\|\s*([^|]{3,60}?)\s*\|', line)
            if m and not re.match(r'^\|\s*[-:L]', line):
                name = m.group(1).strip()
                if name and len(name) > 2:
                    counts["l5"] += 1
                    nid = f"{file_stem}_l5_{counts['l5']}"
                    add_node(nid, name, "task", file=file_stem)
                    add_link(current["l4"], nid, "hierarchy")



def _attach_policy_refs(taxonomy_bodies: dict, nodes: list, node_ids: set,
                        links: list, link_set: set):
    """
    Scan each taxonomy body for blockquote policy lines of the form:
      > _PolicyLabel:_ `filename.md` → optional section
    or:
      > _PolicyLabel:_ `filename.md`

    For each such line, determine the nearest L1/L2/L3 heading above it and:
      1. Append a policy entry to that node's `policies` list
      2. Create a `governed_by` edge: taxonomy_node → ctxfile_<filename>

    Nodes are mutated in-place (nodes list elements are dicts).
    """
    # Build a quick lookup: node_id → node dict for mutation
    node_lookup = {n["id"]: n for n in nodes}

    # Regex: match `> _Label:_ `file.md` → optional section text
    _POLICY_RE = re.compile(
        r'^>\s*_([^_]+?)_:?\s*`([^`]+\.md)`\s*(?:→\s*(.+))?$'
    )
    # Heading patterns for tracking current taxonomy node
    _L2_RE = re.compile(r'^#{1,3}\s+L2:\s+(.+)')
    _L3_RE = re.compile(r'^#{2,4}\s+L3:\s+(.+)')
    _L4_RE = re.compile(r'^#{3,5}\s+L4:\s+(.+)')

    for file_stem, (body, l1_id) in taxonomy_bodies.items():
        current = {"l2": None, "l3": None, "l4": None}
        counts = {"l2": 0, "l3": 0, "l4": 0}

        for line in body.split("\n"):
            # Track heading cursor (mirrors _parse_heading_taxonomy counters)
            if _L2_RE.match(line):
                counts["l2"] += 1
                current["l2"] = f"{file_stem}_l2_{counts['l2']}"
                current["l3"] = None
                current["l4"] = None
                continue
            if _L3_RE.match(line):
                counts["l3"] += 1
                current["l3"] = f"{file_stem}_l3_{counts['l3']}"
                current["l4"] = None
                continue
            if _L4_RE.match(line):
                counts["l4"] += 1
                current["l4"] = f"{file_stem}_l4_{counts['l4']}"
                continue

            # Blockquote policy line
            m = _POLICY_RE.match(line.strip())
            if not m:
                continue

            policy_label = m.group(1).strip().rstrip(":")
            policy_file  = m.group(2).strip()
            section_ref  = (m.group(3) or "").strip()

            # Nearest taxonomy node (most specific first)
            owner_id = (current["l4"] or current["l3"] or current["l2"] or l1_id)
            if owner_id not in node_ids:
                continue

            # Append policy entry to owner node (sidebar only — no graph edge)
            owner_node = node_lookup[owner_id]
            if "policies" not in owner_node:
                owner_node["policies"] = []
            entry = {"label": policy_label, "file": policy_file}
            if section_ref:
                entry["section"] = section_ref
            # Deduplicate
            if entry not in owner_node["policies"]:
                owner_node["policies"].append(entry)



_STOPWORDS = {
    "a", "an", "the", "is", "are", "was", "were", "be", "been", "being",
    "for", "of", "in", "on", "at", "to", "do", "does", "did", "has", "have",
    "can", "will", "would", "could", "should", "i", "we", "you", "he", "she",
    "it", "they", "what", "which", "who", "when", "where", "how", "why",
    "and", "or", "but", "not", "with", "from", "by", "as", "that", "this",
    "me", "my", "our", "its", "their", "about", "get", "give", "tell",
    # Task/action words that are too generic to route on
    "per", "extract", "analyse", "analyze", "show", "list", "find", "check",
    "run", "create", "update", "view", "generate", "calculate", "review",
    "internal", "external", "new", "old", "all", "any", "some", "please",
    "need", "want", "using", "use", "based", "according", "current", "latest",
}


def simulate_context_query(query: str, graph_data: dict) -> dict:
    """
    Score every node in graph_data against the query tokens.
    Returns matched node IDs (score > 0) + their 1-hop neighbours + match details.
    """
    if not query or not graph_data:
        return {"matched_ids": [], "neighbor_ids": [], "match_details": [], "query_tokens": []}

    tokens = [
        t.lower() for t in re.split(r'\W+', query)
        if len(t) > 1 and t.lower() not in _STOPWORDS
    ]
    if not tokens:
        return {"matched_ids": [], "neighbor_ids": [], "match_details": [], "query_tokens": []}

    scores: dict = {}
    reasons: dict = {}

    for node in graph_data.get("nodes", []):
        nid = node["id"]
        name = (node.get("label") or "").lower()
        name_words = set(re.split(r'\W+', name))
        keywords = node.get("keywords") or []
        kw_text = " ".join(str(k).lower() for k in keywords)

        score = 0
        hits: list = []

        for tok in tokens:
            # Exact name word match — high value
            if tok in name_words:
                score += 3
                hits.append(f"name:{tok}")
            # Substring of name
            elif tok in name:
                score += 2
                hits.append(f"name~:{tok}")
            # In keywords
            if tok in kw_text:
                score += 2
                hits.append(f"kw:{tok}")

        if score > 0:
            scores[nid] = score
            reasons[nid] = hits

    matched_ids = set(scores.keys())

    # 1-hop neighbours
    neighbor_ids: set = set()
    for link in graph_data.get("links", []):
        src = link["source"] if isinstance(link["source"], str) else link["source"].get("id", "")
        tgt = link["target"] if isinstance(link["target"], str) else link["target"].get("id", "")
        if src in matched_ids and tgt not in matched_ids:
            neighbor_ids.add(tgt)
        elif tgt in matched_ids and src not in matched_ids:
            neighbor_ids.add(src)

    sorted_matches = sorted(scores.items(), key=lambda x: x[1], reverse=True)

    node_lookup = {n["id"]: n for n in graph_data.get("nodes", [])}
    match_details = [
        {
            "node_id": nid,
            "score": sc,
            "reasons": reasons.get(nid, []),
            "label": node_lookup.get(nid, {}).get("label", nid),
            "node_type": node_lookup.get(nid, {}).get("node_type", ""),
        }
        for nid, sc in sorted_matches[:20]
    ]

    return {
        "matched_ids": list(matched_ids),
        "neighbor_ids": list(neighbor_ids),
        "match_details": match_details,
        "query_tokens": tokens,
    }
