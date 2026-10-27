"""
memory_md.py
─────────────────────────────────────────────────────────────────────────────
Persistent memory index for the agent framework.

Architecture
────────────
MEMORY.md is an always-loaded one-page index injected into every system prompt
so the agent starts each session already knowing what it has learned — without
calling query_memory or reading files.

Directory structure
────────────────────
  memory/
  ├── MEMORY.md                        ← always-loaded index (≤200 lines)
  ├── skills/
  │   ├── ccdops.md                    ← learned strategies, failure modes
  │   └── invoice.md
  ├── entities/
  │   └── ALPHA_OFFICE_SUPPLIES.md     ← entity-specific learned facts
  ├── org/                             ← mirrors Enterprise_Context.md domain tree
  │   ├── p2p/
  │   │   └── current_state.md
  │   ├── ccdops/
  │   │   └── current_state.md
  │   ├── o2c/
  │   │   └── current_state.md
  │   └── ...
  └── users/
      └── {username}/
          └── preferences.md           ← per-user, never shared

MEMORY.md line prefixes
────────────────────────
  [skill:ccdops]        → memory/skills/ccdops.md
  [org:p2p]             → memory/org/p2p/current_state.md
  [entity:VND-777]      → memory/entities/VND-777.md
  [user:{username}]     → memory/users/{username}/preferences.md (private)

Public API
──────────
  build_classify_config(shared_dir, skills_dir) → MemoryClassifyConfig
  classify_destination(record, user_id=None, config=None) → (dest_type, dest_name)
  write_topic_file(memory_root, dest_type, dest_name, record) → Path
  regenerate_memory_md(memory_root) → None
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

logger = logging.getLogger(__name__)



@dataclass
class MemoryClassifyConfig:
    """
    Validated lists loaded from existing codebase sources.
    Passed into classify_destination() so routing decisions are grounded in
    what actually exists — not hardcoded assumptions.

    Sources:
      entity_id_patterns : entity_validation.yaml → entity_memory.id_patterns
                           Same regex patterns KnowledgeFileRouter L0 uses.
                           Only entity_keys that match one of these are routed
                           to memory/entities/.  Anything else is treated as
                           a non-entity record and falls through to skill/org.

      known_skills       : set of skill names found in skills/ directory
                           (subdirectory names).  Records whose skill field is
                           not in this set fall through to org/shared.

      skill_to_domain       : skill_name → org domain string.
                              Loaded from Enterprise_Context.md routing table.
                              Falls back to DEFAULT_SKILL_TO_DOMAIN.

      domain_to_context_file: domain → actual context filename.
                              e.g. {"p2p": "p2p_context.md",
                                    "ccdops": "ccdops_context.md"}
                              Parsed directly from Enterprise_Context.md column 4.
                              Embedded in stub headers so memory/org/<domain>/
                              files reference their source context file.
    """
    entity_id_patterns:     List[re.Pattern] = field(default_factory=list)
    known_skills:           Set[str]         = field(default_factory=set)
    skill_to_domain:        Dict[str, str]   = field(default_factory=dict)
    domain_to_context_file: Dict[str, str]   = field(default_factory=dict)


def build_classify_config(
    shared_dir: Optional[Path] = None,
    skills_dir: Optional[Path] = None,
) -> MemoryClassifyConfig:
    """
    Build a MemoryClassifyConfig from existing codebase sources.

    shared_dir  — tenant shared/ dir (contains entity_validation.yaml and
                  Enterprise_Context.md).  Example:
                  enterprise_root/tenants/company/shared/
    skills_dir  — skills root dir (contains <skill_name>/SKILL.md).  Example:
                  IAF-Agent-Skills/skills/

    All three data sources degrade gracefully: if a file is missing or
    unparseable the corresponding config field is left empty/default and
    classify_destination() falls back to DEFAULT_SKILL_TO_DOMAIN.
    """
    cfg = MemoryClassifyConfig()

    if shared_dir:
        ev_path = Path(shared_dir) / "entity_validation.yaml"
        if ev_path.exists():
            try:
                import yaml as _yaml
                with open(ev_path, encoding="utf-8") as fh:
                    data = _yaml.safe_load(fh) or {}
                patterns = (data.get("entity_memory") or {}).get("id_patterns") or []
                cfg.entity_id_patterns = [
                    re.compile(p, re.IGNORECASE) for p in patterns if p
                ]
                logger.debug(
                    "build_classify_config: loaded %d entity patterns from %s",
                    len(cfg.entity_id_patterns), ev_path.name,
                )
            except Exception as exc:
                logger.warning("build_classify_config: entity_validation.yaml load failed: %s", exc)

    if skills_dir:
        skills_path = Path(skills_dir)
        if skills_path.is_dir():
            cfg.known_skills = {
                d.name.lower()
                for d in skills_path.iterdir()
                if d.is_dir() and (d / "SKILL.md").exists()
            }
            logger.debug(
                "build_classify_config: found %d skills in %s",
                len(cfg.known_skills), skills_path,
            )

    # ── 3. Skill → domain map + domain → context filename from Enterprise_Context.md
    if shared_dir:
        ec_path = Path(shared_dir) / "Enterprise_Context.md"
        if ec_path.exists():
            cfg.skill_to_domain, cfg.domain_to_context_file = _parse_domain_map(ec_path)
            logger.debug(
                "build_classify_config: parsed %d skill→domain, %d domain→file entries",
                len(cfg.skill_to_domain), len(cfg.domain_to_context_file),
            )

    _STRIP_SUFFIXES = re.compile(
        r"_(?:context|apis?|guide|ref|reference|docs?|overview|spec)$", re.IGNORECASE
    )
    if shared_dir:
        contexts_dir = Path(shared_dir) / "contexts"
        if contexts_dir.is_dir():
            for cf in sorted(contexts_dir.glob("*.md")):
                stem = cf.stem.lower()
                domain = _STRIP_SUFFIXES.sub("", stem) or stem
                cfg.domain_to_context_file.setdefault(domain, cf.name)
                logger.debug(
                    "build_classify_config: contexts/ scan: %s → domain '%s'",
                    cf.name, domain,
                )
            logger.debug(
                "build_classify_config: after contexts/ scan, %d domains total",
                len(cfg.domain_to_context_file),
            )

    # Fall back to built-in map for any skills not found in Enterprise_Context.md
    for skill, domain in DEFAULT_SKILL_TO_DOMAIN.items():
        cfg.skill_to_domain.setdefault(skill, domain)

    return cfg


def _parse_domain_map(ec_path: Path) -> tuple:
    """
    Parse the routing table in Enterprise_Context.md.

    Returns (skill_to_domain, domain_to_context_file):
      skill_to_domain       : {"invoice": "p2p", "ccdops": "ccdops", ...}
      domain_to_context_file: {"p2p": "p2p_context.md", "ccdops": "ccdops_context.md", ...}

    Both are derived from the pipe-delimited table rows where:
      col 3 = skill names   e.g. "invoice, payment_processing"
      col 4 = context path  e.g. "/shared/contexts/p2p_context.md"

    The actual filename (p2p_context.md) is stored as-is so stub headers can
    reference the exact source file without any reconstruction.
    """
    skill_to_domain:        Dict[str, str] = {}
    domain_to_context_file: Dict[str, str] = {}

    row_re  = re.compile(r"^\|([^|]+)\|([^|]+)\|([^|]+)\|([^|]+)\|")
    # Extract filename like p2p_context.md from /shared/contexts/p2p_context.md
    file_re = re.compile(r"(\w+_context\.md)")
    # Extract domain prefix from filename: p2p_context.md → "p2p"
    dom_re  = re.compile(r"^(\w+?)_context\.md$")

    try:
        with open(ec_path, encoding="utf-8") as fh:
            for line in fh:
                m = row_re.match(line.strip())
                if not m:
                    continue
                skills_col = m.group(3).strip()
                file_col   = m.group(4).strip()

                fm = file_re.search(file_col)
                if not fm:
                    continue
                context_filename = fm.group(1)          # "p2p_context.md"
                dm = dom_re.match(context_filename)
                if not dm:
                    continue
                domain = dm.group(1)                    # "p2p"

                domain_to_context_file[domain] = context_filename

                # Map every listed skill to this domain
                for raw_skill in skills_col.split(","):
                    skill = raw_skill.strip().strip("`").lower()
                    if skill and skill != "general":
                        skill_to_domain[skill] = domain

    except Exception as exc:
        logger.warning("_parse_domain_map failed (non-fatal): %s", exc)

    return skill_to_domain, domain_to_context_file



DEFAULT_SKILL_TO_DOMAIN: Dict[str, str] = {
    # Procure to Pay
    "invoice":                   "p2p",
    "invoice_dbs":               "p2p",
    "invoice_processing_ap":     "p2p",
    "payment_processing":        "p2p",
    "ap_account_maintenance":    "p2p",
    "ap_correction_workflow":    "p2p",
    "period_close_check":        "p2p",
    "debit_balance_report":      "p2p",
    # Order to Cash
    "ar_ops":                    "o2c",
    "dispute_management":        "o2c",
    # CCD Kubernetes Ops
    "ccdops":                    "ccdops",
    # Record to Report (R2R already covered by period_close_check)
    # FP&A
    "fpa":                       "fpa",
    # ITOps
    "itops":                     "itops",
}

# knowledge_type values that represent learned strategies / stable rules
# → route to memory/skills/<skill>.md
_STRATEGY_TYPES = frozenset({"rule", "procedure", "correction", "workaround", "pattern"})

# knowledge_type values that represent transient org state
# → route to memory/org/<domain>/current_state.md
_ORG_STATE_TYPES = frozenset({"fact", "observation", "state", "exception"})

# Preference-related summaries are routed to user memory when user_id is set
_PREFERENCE_KEYWORDS = re.compile(
    r"\b(prefer|preference|always use|format|verbosity|output style|shortcut)\b",
    re.IGNORECASE,
)



def classify_destination(
    record: Dict[str, Any],
    user_id: Optional[str] = None,
    config: Optional[MemoryClassifyConfig] = None,
    llm=None,
) -> Tuple[str, str]:
    """
    Classify a knowledge record into (dest_type, dest_name).

    Routing order — mirrors L0→L1→L2→L3 in KnowledgeFileRouter:
      0. User preference signal → "user"
      1. Validated entity_keys  → "entity/<id>"      (deterministic, entity_validation.yaml)
      2. Org-state ktype        → "org/<domain>"      (deterministic, Enterprise_Context.md)
      3. Strategy ktype         → "skill/<skill>"     (deterministic, skills/ directory)
      4. Rule fallback          → "skill/<skill>"     (deterministic)
      5. LLM fallback           → best match from config.known_skills + known domains
                                   fires only when rules land on "org/shared"

    config — built by build_classify_config() from:
               entity_validation.yaml  → entity_id_patterns
               skills/ directory       → known_skills
               Enterprise_Context.md   → skill_to_domain
             When None, falls back to DEFAULT_SKILL_TO_DOMAIN with no validation.

    llm    — LangChain LLM instance (light model).  When provided and rules are
             uncertain, a one-shot prompt picks from the validated skill/domain list.
             Non-fatal: LLM failure falls back to "org/shared".
    """
    skill       = (record.get("skill") or "").strip().lower()
    ktype       = (record.get("knowledge_type") or record.get("type") or "").strip().lower()
    summary     = (record.get("summary") or "").strip()
    entity_keys = record.get("entity_keys") or []

    # Config accessors — degrade gracefully when config is absent
    entity_patterns = config.entity_id_patterns   if config else []
    known_skills    = config.known_skills          if config else set()
    s2d             = config.skill_to_domain       if config else DEFAULT_SKILL_TO_DOMAIN
    d2f             = config.domain_to_context_file if config else {}

    def _org(domain: str) -> Tuple[str, str]:
        """Return ("org", <context_filename>) — filename matches the context/ file."""
        filename = d2f.get(domain, f"{domain}_context.md")
        return ("org", filename)

    _src_ctx = (record.get("scope") or {}).get("source_context_file")
    if _src_ctx:
        filename = Path(_src_ctx).name   # guard against full paths
        logger.debug("classify_destination: source_context_file hit → org:%s", filename)
        return ("org", filename)

    # 0. User preference (highest priority)
    if user_id and ktype == "preference":
        return ("user", user_id)
    if user_id and _PREFERENCE_KEYWORDS.search(summary):
        return ("user", user_id)

    # 1. Entity check — validated against entity_validation.yaml id_patterns
    if entity_keys:
        entity_id = _match_entity_key(entity_keys, entity_patterns)
        if entity_id:
            return ("entity", entity_id)

    # 2. Org state types
    if ktype in _ORG_STATE_TYPES:
        domain = s2d.get(skill, "")
        if domain:
            return _org(domain)
        # skill not in map → LLM can pick the right domain below

    # 3. Strategy types
    if ktype in _STRATEGY_TYPES:
        if skill and (not known_skills or skill in known_skills):
            return ("skill", skill)
        # skill unknown → LLM can pick

    # 4. Rule fallback (known skill, unrecognised ktype)
    if skill and (not known_skills or skill in known_skills):
        return ("skill", skill)

    # 5. LLM fallback — only fires when rules are genuinely uncertain
    if llm is not None and (known_skills or s2d):
        result = _llm_classify(record, known_skills, s2d, llm, d2f)
        if result:
            return result

    return _org("shared")


def _llm_classify(
    record: Dict[str, Any],
    known_skills: Set[str],
    skill_to_domain: Dict[str, str],
    llm,
    domain_to_context_file: Optional[Dict[str, str]] = None,
) -> Optional[Tuple[str, str]]:
    """
    One-shot LLM call to classify a record when deterministic rules are ambiguous.

    Prompt shows the actual available skills and org context files (from config)
    so the LLM picks from what really exists — not hallucinated paths.
    Returns None on failure (caller falls back to "org/shared_context.md").
    """
    try:
        d2f           = domain_to_context_file or {}
        known_domains = sorted(set(skill_to_domain.values()) - {"shared"})
        skill_list    = sorted(known_skills)[:30]   # cap prompt size

        # Build options list — org options use the actual context filename
        options = []
        for i, s in enumerate(skill_list, 1):
            options.append(f"  {i}. skill:{s}  → memory/skills/{s}.md")
        base = len(skill_list)
        for j, d in enumerate(known_domains, base + 1):
            cf = d2f.get(d, f"{d}_context.md")
            options.append(f"  {j}. org:{d}  → memory/org/{cf}")
        shared_cf = d2f.get("shared", "shared_context.md")
        options.append(f"  {base + len(known_domains) + 1}. org:shared  → memory/org/{shared_cf} (fallback)")

        prompt = (
            "You are a memory router for an enterprise AI agent.\n\n"
            "A confirmed knowledge record needs to be stored in the right memory file.\n\n"
            "Knowledge record:\n"
            f"  Summary     : {record.get('summary', '')}\n"
            f"  Type        : {record.get('knowledge_type') or record.get('type', '')}\n"
            f"  Skill       : {record.get('skill', '')}\n"
            f"  Entity keys : {', '.join(record.get('entity_keys') or [])}\n"
            f"  Applies when: {record.get('applies_when', '')}\n\n"
            "Available memory destinations:\n"
            + "\n".join(options) + "\n\n"
            "Rules:\n"
            "- skill:X files store learned strategies, workarounds, and procedures for that skill\n"
            "- org:X files store temporary state, active holds, and domain-wide facts\n"
            "- Pick the MOST specific match. If unsure, pick org:shared.\n\n"
            "Reply with ONLY the destination tag, e.g. 'skill:ccdops' or 'org:p2p'."
        )

        response = llm.invoke(prompt)
        answer   = response.content.strip() if hasattr(response, "content") else str(response).strip()

        # Parse "skill:ccdops" or "org:p2p"
        m = re.match(r"^(skill|org):(\w+)$", answer, re.IGNORECASE)
        if m:
            dest_type = m.group(1).lower()
            dest_name = m.group(2).lower()
            if dest_type == "skill" and (not known_skills or dest_name in known_skills):
                logger.info("LLM memory classify → skill:%s", dest_name)
                return ("skill", dest_name)
            if dest_type == "org" and (dest_name in known_domains or dest_name == "shared"):
                # Return context filename, not domain name
                cf = d2f.get(dest_name, f"{dest_name}_context.md")
                logger.info("LLM memory classify → org:%s (%s)", dest_name, cf)
                return ("org", cf)
            logger.warning("LLM memory classify returned unknown value '%s' — ignoring", answer)

    except Exception as exc:
        logger.warning("_llm_classify failed (non-fatal): %s", exc)

    return None


def _match_entity_key(
    entity_keys: List[str],
    patterns: List[re.Pattern],
) -> Optional[str]:
    """
    Return the normalised entity ID for the first key that matches any pattern.
    If no patterns are configured, accept the first non-empty key as-is
    (backwards-compatible: same as the old unconditional entity_keys[0] path).
    Returns None when patterns exist but nothing matches.
    """
    if not patterns:
        # No validation configured — accept first key (backwards-compatible)
        first = str(entity_keys[0]).strip() if entity_keys else ""
        return _normalise_entity_id(first) if first else None

    for key in entity_keys:
        key_str = str(key).strip()
        if any(rx.search(key_str) for rx in patterns):
            return _normalise_entity_id(key_str)
    return None


def _normalise_entity_id(key: str) -> str:
    """Uppercase + replace non-word characters — safe for use as filename."""
    return re.sub(r"[^\w\-]", "_", str(key).strip()).upper()



def write_topic_file(
    memory_root: Path,
    dest_type: str,
    dest_name: str,
    record: Dict[str, Any],
) -> Path:
    """
    Write (or append) a knowledge record to the appropriate topic file.

    Returns the Path of the file written.
    Raises on I/O failure — caller decides whether to propagate.
    Idempotent by record id.
    """
    target = _topic_file_path(memory_root, dest_type, dest_name)

    # Ensure parent dir exists
    target.parent.mkdir(parents=True, exist_ok=True)

    # Create file with header if it does not exist
    if not target.exists():
        header = _make_file_header(dest_type, dest_name)
        target.write_text(header, encoding="utf-8")
        logger.info("memory_md: created topic file %s", target.relative_to(memory_root))

    record_id = record.get("id", "")
    existing  = target.read_text(encoding="utf-8")

    # Idempotency: skip if this record id is already present
    if record_id and record_id in existing:
        logger.debug("memory_md: record %s already in %s — skip", record_id, target.name)
        return target

    entry = _format_entry(record)

    # Append inside existing section, or create the section
    _SECTION = "## Learned Knowledge"
    if _SECTION in existing:
        new_content = existing.rstrip() + "\n\n" + entry + "\n"
    else:
        new_content = (
            existing.rstrip()
            + f"\n\n---\n\n{_SECTION}\n"
            "<!-- auto-generated by memory_md — do not edit manually -->\n\n"
            + entry + "\n"
        )

    target.write_text(new_content, encoding="utf-8")
    logger.info("memory_md: appended record %s to %s", record_id or "?", target.name)
    return target


def _topic_file_path(memory_root: Path, dest_type: str, dest_name: str) -> Path:
    """Resolve the absolute Path for a (dest_type, dest_name) tuple."""
    if dest_type == "skill":
        return memory_root / "skills" / f"{dest_name}.md"
    if dest_type == "org":
        # dest_name is the context filename: p2p_context.md, ccdops_context.md, …
        # Mirrors shared/contexts/<dest_name> — same filename, different directory.
        return memory_root / "org" / dest_name
    if dest_type == "entity":
        return memory_root / "entities" / f"{dest_name}.md"
    if dest_type == "user":
        # dest_name is the user_id / email — sanitise for path safety
        safe_user = re.sub(r"[^\w@.\-]", "_", dest_name)
        return memory_root / "users" / safe_user / "preferences.md"
    # Unknown type — put in org/shared_context.md to avoid data loss
    logger.warning("memory_md: unknown dest_type '%s', writing to org/shared_context.md", dest_type)
    return memory_root / "org" / "shared_context.md"


def _make_file_header(dest_type: str, dest_name: str, context_file: str = "") -> str:
    today = date.today().isoformat()
    if dest_type == "skill":
        return (
            f"# Skill Memory: {dest_name}\n"
            f"<!-- created {today} -->\n\n"
            "Learned strategies, failure modes, and successful approaches for this skill.\n\n"
        )
    if dest_type == "org":
        # Embed the actual context file name so the stub is linked to its source.
        # e.g. memory/org/p2p/current_state.md → "Source context: p2p_context.md"
        context_ref = f"\nSource context: `{context_file}`" if context_file else ""
        return (
            f"# Org State: {dest_name}\n"
            f"<!-- created {today} -->{context_ref}\n\n"
            "Temporary environment state, active holds, cluster status, and operational facts.\n"
            "Confirmed knowledge about this domain is appended below.\n\n"
        )
    if dest_type == "entity":
        return (
            f"# Entity Memory: {dest_name}\n"
            f"<!-- created {today} -->\n\n"
            "Entity-specific facts confirmed across sessions.\n\n"
        )
    if dest_type == "user":
        return (
            f"# User Preferences: {dest_name}\n"
            f"<!-- created {today} -->\n"
            "<!-- PRIVATE — only injected for this user -->\n\n"
        )
    return f"# Memory: {dest_name}\n<!-- created {today} -->\n\n"


def seed_memory_structure(
    memory_root: Path,
    config: "MemoryClassifyConfig",
) -> None:
    """
    Pre-create stub .md files so the override dropdown shows the full intended
    memory tree from day one — even before any knowledge is approved.

    Sources (all from config, no hardcoding):
      Org domains  — union of:
                       • unique values in config.skill_to_domain  (EC.md-derived)
                       • all keys in config.domain_to_context_file (contexts/ scan)
                     This means every *.md file the customer drops into contexts/
                     gets an org stub, regardless of whether it's in EC.md.
                     Header embeds the actual context filename from
                     config.domain_to_context_file  e.g. "p2p_context.md"
      Skill files  — only skills in config.skill_to_domain (domain-mapped skills)

    Never overwrites existing files. Calls regenerate_memory_md() at the end.
    Fully non-fatal — a failure never blocks the caller.
    """
    if not memory_root:
        return
    try:
        memory_root = Path(memory_root)
        seeded = 0

        org_files: Dict[str, str] = dict(config.domain_to_context_file)  # domain → filename
        org_files.setdefault("shared", "shared_context.md")

        org_dir = memory_root / "org"
        for domain, context_filename in sorted(org_files.items()):
            path = org_dir / context_filename
            if not path.exists():
                org_dir.mkdir(parents=True, exist_ok=True)
                path.write_text(
                    _make_file_header("org", domain, context_file=context_filename),
                    encoding="utf-8",
                )
                logger.info(
                    "seed_memory_structure: created org/%s", context_filename,
                )
                seeded += 1

        for skill in sorted(config.skill_to_domain.keys()):
            path = memory_root / "skills" / f"{skill}.md"
            if not path.exists():
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(_make_file_header("skill", skill), encoding="utf-8")
                logger.info("seed_memory_structure: created skills/%s.md", skill)
                seeded += 1

        if seeded:
            regenerate_memory_md(memory_root)
            logger.info(
                "seed_memory_structure: seeded %d files, MEMORY.md updated", seeded
            )
        else:
            logger.debug("seed_memory_structure: all stubs already present")

    except Exception as exc:
        logger.warning("seed_memory_structure failed (non-fatal): %s", exc)


def _format_entry(record: Dict[str, Any]) -> str:
    """
    Format one knowledge record as a markdown entry.

    Example:
        ### [2026-04-01] Pod restart loop: check OOMKilled → increase memory limits
        **Type**: workaround | **Skill**: ccdops | **ID**: kn_abc123
        **Applies when**: pod in CrashLoopBackOff
        > Pod restart loop: check OOMKilled → increase memory limits
    """
    today     = date.today().isoformat()
    summary   = (record.get("summary") or "").strip()
    ktype     = record.get("knowledge_type") or record.get("type") or "—"
    skill     = record.get("skill") or "—"
    applies   = record.get("applies_when") or "—"
    record_id = record.get("id") or "unknown"

    return "\n".join([
        f"### [{today}] {summary}",
        f"**Type**: {ktype} | **Skill**: {skill} | **ID**: {record_id}",
        f"**Applies when**: {applies}",
        f"> {summary}",
    ])



# Max lines in MEMORY.md — keeps system-prompt cost bounded
_MAX_MEMORY_MD_LINES = 500

# Auto-gen header written at the top of every MEMORY.md
_MEMORY_MD_HEADER = """\
# Memory Index
<!-- auto-generated by memory_md.regenerate_memory_md() — do not edit manually -->
<!-- max {max_lines} lines — older entries pruned automatically -->
<!-- last updated: {ts} -->

"""


def regenerate_memory_md(memory_root: Path) -> None:
    """
    Rebuild MEMORY.md from all topic files under memory_root.

    Scans:
      memory/skills/*.md           — shared across all users
      memory/org/**/*.md           — shared across all users
      memory/entities/*.md         — shared across all users
      memory/users/*/*.md          — ALL users indexed; load_memory_md()
                                     strips other users' lines at read time

    Each section entry is ≤150 chars and uses a typed prefix:
      [skill:ccdops]   memory/skills/ccdops.md   — <hint>
      [org:p2p]        memory/org/p2p/current_state.md — <hint>
      [entity:VND-777] memory/entities/VND-777.md — <hint>
      [user:me@x.com]  memory/users/me@x.com/preferences.md — <hint>

    Silently no-ops if memory_root doesn't exist.
    """
    if not memory_root.is_dir():
        return

    lines: list[str] = []

    _ORG_LABEL_RE  = re.compile(r"_(?:context|apis?|guide|ref|reference|docs?|overview|spec)$", re.I)
    _EC_STEMS      = {"enterprise_context", "ec"}

    def _render_file_block(prefix: str, label: str, rel_path, entries: list) -> list[str]:
        """
        Render a multi-line block for one topic file.

        Format:
          **<prefix>:<label>** [<rel_path>] — <N> entr(y|ies)
            - [<type>] <summary>
            ...
        Returns [] when entries is empty (caller skips file entirely).
        """
        if not entries:
            return []
        count = len(entries)
        noun  = "entry" if count == 1 else "entries"
        block = [f"**{prefix}:{label}** [{rel_path}] — {count} {noun}"]
        for e in entries:
            ktype   = f"[{e['type']}] " if e.get("type") else ""
            summary = e.get("summary", "")[:120]
            block.append(f"  - {ktype}{summary}")
        return block

    org_dir = memory_root / "org"
    if org_dir.is_dir():
        section: list[str] = []
        for md in sorted(org_dir.glob("*.md")):
            if md.stem.lower() in _EC_STEMS:
                continue  # skip EC.md — master index, not a domain context
            stem    = md.stem.lower()
            label   = _ORG_LABEL_RE.sub("", stem) or stem
            entries = _extract_entries(md)
            block   = _render_file_block("org", label, md.relative_to(memory_root), entries)
            if block:
                section.extend(block)
                section.append("")
        if section:
            lines.append("## Org State")
            lines.extend(section)

    skills_dir = memory_root / "skills"
    if skills_dir.is_dir():
        section = []
        for md in sorted(skills_dir.glob("*.md")):
            entries = _extract_entries(md)
            block   = _render_file_block("skill", md.stem, md.relative_to(memory_root), entries)
            if block:
                section.extend(block)
                section.append("")
        if section:
            lines.append("## Skills")
            lines.extend(section)

    entities_dir = memory_root / "entities"
    if entities_dir.is_dir():
        section = []
        for md in sorted(entities_dir.glob("*.md")):
            entries = _extract_entries(md)
            block   = _render_file_block("entity", md.stem, md.relative_to(memory_root), entries)
            if block:
                section.extend(block)
                section.append("")
        if section:
            lines.append("## Entities")
            lines.extend(section)

    users_root = memory_root / "users"
    if users_root.is_dir():
        section = []
        for user_dir in sorted(users_root.iterdir()):
            if not user_dir.is_dir():
                continue
            dir_user_id = user_dir.name
            for md in sorted(user_dir.glob("*.md")):
                entries = _extract_entries(md)
                block   = _render_file_block("user", dir_user_id, md.relative_to(memory_root), entries)
                if block:
                    section.extend(block)
                    section.append("")
        if section:
            lines.append("## User Preferences (private — see only your own entries)")
            lines.extend(section)

    if not lines:
        # Nothing to index — remove stale MEMORY.md if present
        md_path = memory_root / "MEMORY.md"
        if md_path.exists():
            md_path.unlink()
        return

    # Cap at _MAX_MEMORY_MD_LINES
    if len(lines) > _MAX_MEMORY_MD_LINES:
        lines = lines[:_MAX_MEMORY_MD_LINES]
        lines.append("<!-- truncated — see topic files for full history -->")

    ts      = datetime.now().isoformat(timespec="seconds")
    header  = _MEMORY_MD_HEADER.format(max_lines=_MAX_MEMORY_MD_LINES, ts=ts)
    content = header + "\n".join(lines) + "\n"

    md_path = memory_root / "MEMORY.md"
    md_path.write_text(content, encoding="utf-8")
    logger.info("memory_md: regenerated MEMORY.md (%d lines)", len(lines))


def _extract_entries(md_path: Path) -> list:
    """
    Return all knowledge entries from a topic file's '## Learned Knowledge' section.

    Each entry is a dict: {"summary": str, "type": str, "skill": str}
    Returns [] if the section is absent or empty.
    """
    entries = []
    try:
        in_section = False
        current: dict = {}
        with open(md_path, encoding="utf-8") as fh:
            for raw_line in fh:
                line = raw_line.strip()
                if line.startswith("## Learned Knowledge"):
                    in_section = True
                    continue
                if line.startswith("## ") and in_section:
                    break
                if not in_section:
                    continue
                if line.startswith("### "):
                    if current.get("summary"):
                        entries.append(current)
                    summary = re.sub(r"^###\s*\[\d{4}-\d{2}-\d{2}\]\s*", "", line).strip()
                    current = {"summary": summary, "type": "", "skill": ""}
                # **Type**: rule | **Skill**: p2p_consultant | **ID**: ...
                elif line.startswith("**Type**") and current:
                    m_type  = re.search(r"\*\*Type\*\*:\s*([^\|]+)", line)
                    m_skill = re.search(r"\*\*Skill\*\*:\s*([^\|]+)", line)
                    if m_type:
                        t = m_type.group(1).strip()
                        current["type"] = t if t != "—" else ""
                    if m_skill:
                        s = m_skill.group(1).strip()
                        current["skill"] = s if s != "—" else ""
        if current.get("summary"):
            entries.append(current)
    except Exception:
        pass
    return entries


def _extract_hint(md_path: Path) -> str:
    """
    Return a ≤80-char hint from a topic file.

    Only reads entries inside the '## Learned Knowledge' section so the file
    header description (e.g. "Temporary environment state...") is never used
    as the hint.

    Tries in order:
    1. First ### [date] entry title inside Learned Knowledge section
    2. First > blockquote line inside the section
    3. Filename stem (fallback)
    """
    try:
        in_section = False
        with open(md_path, encoding="utf-8") as fh:
            for raw_line in fh:
                line = raw_line.strip()
                if not line:
                    continue
                # Enter the learned knowledge section
                if line.startswith("## Learned Knowledge"):
                    in_section = True
                    continue
                # Exit on any other ## heading
                if line.startswith("## ") and in_section:
                    break
                if not in_section:
                    continue
                # Skip auto-gen comment and separators
                if line.startswith("<!--") or line.startswith("---"):
                    continue
                if line.startswith("###"):
                    text = re.sub(r"^###\s*\[\d{4}-\d{2}-\d{2}\]\s*", "", line).strip()
                    if text:
                        return text[:80]
                # > blockquote — fallback summary line
                if line.startswith("> "):
                    return line[2:].strip()[:80]
    except Exception:
        pass
    return md_path.stem



def load_memory_md(
    memory_root: Path,
    user_id: Optional[str] = None,
) -> str:
    """
    Load MEMORY.md and filter out [user:X] lines that don't belong to user_id.

    Returns empty string if the file doesn't exist or is empty.
    Called from agent.py _load_prompt() to inject as '## What I Know'.
    """
    md_path = memory_root / "MEMORY.md"
    if not md_path.exists():
        return ""

    raw = md_path.read_text(encoding="utf-8").strip()
    if not raw:
        return ""

    visible: list[str] = []
    for line in raw.splitlines():
        # Detect user-tagged lines: - [user:<id>](...)
        m = re.match(r"^\s*-\s*\[user:([^\]]+)\]", line)
        if m:
            line_user = m.group(1)
            # Include only if it matches the current user
            if user_id and line_user == user_id:
                visible.append(line)
            # Always include the section header above user lines
        else:
            visible.append(line)

    # Strip trailing blank lines left by user-line removal
    while visible and not visible[-1].strip():
        visible.pop()

    return "\n".join(visible)
