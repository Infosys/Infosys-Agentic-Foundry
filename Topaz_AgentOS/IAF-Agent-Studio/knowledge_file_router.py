"""
knowledge_file_router.py
─────────────────────────────────────────────────────────────────────────────
Routes a confirmed knowledge record to the right enterprise context .md file
and appends it there so that file-mode agents see it on the next run.

Four-layer routing strategy
────────────────────────────
Layer -1 — Memory classify : classify dest_type (skill/org/entity/user) for
            MEMORY.md topic files.  Runs first; result stored on SuggestResult.
Layer 0 — Entity check     : entity_keys → memory/entities/<entity>.md
Layer 3 — LLM fallback     : one-shot LLM call when no direct match found

Entity knowledge goes directly to memory/entities/<entity>.md (not shared/).
Org/context knowledge goes to shared/contexts/<domain>.md and is mirrored to
memory/org/<domain>.md.  Both paths regenerate MEMORY.md on every write.

Append format
─────────────
A clearly-marked section is added at the end of the target file:

    ## Confirmed Knowledge
    <!-- auto-generated – do not edit this section manually -->

    ### [2026-03-21] AP close cutoff is Day 3
    **Type**: rule | **Skill**: period_close_check
    **Applies when**: user asks about AP close cutoff
    > AP invoice cutoff is Day 3 of the month-end close cycle.

Public API
──────────
    router = KnowledgeFileRouter(
        contexts_dir="/path/to/contexts",
        memory_root="/path/to/agents/<agent_id>/memory",  # optional
        skills_dir="/path/to/tenant/skills",              # optional
        user_id="me@company.com",                          # optional
    )
    suggestion = router.suggest(knowledge_record)   # → SuggestResult
    router.append(file_path, knowledge_record)      # → None (raises on failure)
"""

from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any, Dict, List, Optional

from knowledge_bundle_registry import BundleRegistry, KnowledgeBundle

try:
    import yaml as _yaml
except ImportError:
    _yaml = None  # yaml optional — entity memory falls back gracefully

# memory_md is loaded directly by file path to avoid pulling in the full
# iaf_agent_skills package (which requires agent_os, not available in Studio).
try:
    import sys as _sys
    import importlib.util as _ilu
    _memory_md_path = Path(__file__).parent.parent / "IAF-Agent-Skills" / "iaf_agent_skills" / "memory_md.py"
    _spec = _ilu.spec_from_file_location("iaf_agent_skills.memory_md", _memory_md_path)
    _memory_md = _ilu.module_from_spec(_spec)
    _sys.modules["iaf_agent_skills.memory_md"] = _memory_md  # register so @dataclass works
    _spec.loader.exec_module(_memory_md)
    _HAS_MEMORY_MD = True
except Exception as _mme:
    _memory_md = None  # type: ignore[assignment]
    _HAS_MEMORY_MD = False
    import logging as _log
    _log.getLogger(__name__).warning("memory_md not available — MEMORY.md writes disabled: %s", _mme)

logger = logging.getLogger(__name__)



@dataclass
class ContextFileMeta:
    """Metadata extracted from the header of one context .md file."""
    path: Path                      # absolute path to the file
    rel_path: str                   # path relative to contexts_dir (for display)
    tower: str = ""                 # e.g. "Finance & Accounting"
    process: str = ""               # e.g. "Record to Report"
    skills: List[str] = field(default_factory=list)    # e.g. ["period_close_check"]
    aliases: List[str] = field(default_factory=list)   # lower-cased alias tokens


@dataclass
class SuggestResult:
    """Result of a file routing suggestion."""
    file_path: str          # absolute path (or "" when unknown)
    rel_path: str           # display-friendly relative path
    confidence: str         # "high" | "medium" | "low" | "none"
    method: str             # "skill" | "alias" | "llm" | "none"
    candidates: List[Dict[str, Any]] = field(default_factory=list)
    # Layer -1 memory classification (set regardless of context file routing)
    memory_dest_type: str = ""   # "skill" | "org" | "entity" | "user"
    memory_dest_name: str = ""   # domain/skill/entity name for the topic file
    bundle_id: str = ""          # matched knowledge bundle id, if any



# How many header lines to read per file (avoids loading entire large files)
_HEADER_SCAN_LINES = 40

# Regex helpers
_SKILL_RE  = re.compile(r"\*\*Skills?\*\*[:\s`]+([^`\n]+)")
_ALIAS_RE  = re.compile(r"\*\*Aliases?\*\*[:\s]+(.+)")
_TOWER_RE  = re.compile(r"\*\*Tower\*\*[:\s]+(.+)")
_PROCESS_RE = re.compile(r"\*\*Process\*\*[:\s]+(.+)")


def _parse_context_file(path: Path, contexts_dir: Path) -> ContextFileMeta:
    """Read the first _HEADER_SCAN_LINES lines of a .md file and extract metadata."""
    meta = ContextFileMeta(
        path=path,
        rel_path=str(path.relative_to(contexts_dir)),
    )
    try:
        with open(path, encoding="utf-8") as fh:
            for i, line in enumerate(fh):
                if i >= _HEADER_SCAN_LINES:
                    break
                line = line.rstrip()

                m = _TOWER_RE.search(line)
                if m and not meta.tower:
                    meta.tower = m.group(1).strip()

                m = _PROCESS_RE.search(line)
                if m and not meta.process:
                    meta.process = m.group(1).strip()

                # Skills: backtick-delimited, possibly multiple per line
                m = _SKILL_RE.search(line)
                if m:
                    raw = m.group(1)
                    # strip backticks and split by comma / whitespace
                    skills = [s.strip("` ") for s in re.split(r"[,\s]+", raw) if s.strip("` ")]
                    meta.skills.extend(s for s in skills if s)

                # Aliases: comma-separated keywords
                m = _ALIAS_RE.search(line)
                if m:
                    raw = m.group(1)
                    tokens = [t.strip().lower() for t in raw.split(",") if t.strip()]
                    meta.aliases.extend(tokens)

    except Exception as exc:
        logger.warning("Failed to parse context file %s: %s", path, exc)

    return meta


def build_file_index(contexts_dir: str | Path) -> List[ContextFileMeta]:
    """
    Scan all *.md files under contexts_dir and return a list of ContextFileMeta.

    Called once at startup (or lazily on first routing request).
    Safe to call multiple times — each call rebuilds from disk.
    """
    contexts_dir = Path(contexts_dir)
    if not contexts_dir.is_dir():
        logger.warning("contexts_dir does not exist: %s", contexts_dir)
        return []

    files = list(contexts_dir.rglob("*.md"))
    index = [_parse_context_file(f, contexts_dir) for f in sorted(files)]
    logger.info("KnowledgeFileRouter: indexed %d context files from %s", len(index), contexts_dir)
    return index



class KnowledgeFileRouter:
    """
    Routes a knowledge record to the best context .md file and appends it.

    Usage
    ─────
        router = KnowledgeFileRouter(contexts_dir="enterprise_root/.../contexts")
        result = router.suggest(record)
        if result.confidence in ("high", "medium"):
            router.append(result.file_path, record)
    """

    def __init__(
        self,
        contexts_dir: str | Path,
        memory_root: Optional[str | Path] = None,
        knowledge_dir: Optional[str | Path] = None,
        skills_dir: Optional[str | Path] = None,
        user_id: Optional[str] = None,
    ):
        self.contexts_dir = Path(contexts_dir)
        self._index: Optional[List[ContextFileMeta]] = None   # lazy-loaded
        # Load entity id_patterns from entity_validation.yaml
        self._entity_memory_cfg = self._load_entity_memory_config()
        # Optional MEMORY.md integration
        self.memory_root: Optional[Path] = Path(memory_root) if memory_root else None
        # Entity files live in memory/entities/ (not shared/entities/)
        self.entities_dir: Optional[Path] = (self.memory_root / "entities") if self.memory_root else None
        self.user_id: Optional[str] = user_id
        self.knowledge_dir: Optional[Path] = Path(knowledge_dir) if knowledge_dir else None
        self.bundle_registry: Optional[BundleRegistry] = (
            BundleRegistry(self.knowledge_dir) if self.knowledge_dir else None
        )
        self.skills_dir: Optional[Path] = Path(skills_dir) if skills_dir else None
        # Lazy-built classify config (uses entity_validation.yaml + skills dir)
        self._classify_config = None

    def _load_entity_memory_config(self) -> Dict[str, Any]:
        """
        Read the entity_memory section from entity_validation.yaml.

        The file is expected at shared/entity_validation.yaml — one level above
        the contexts/ directory.  Returns an empty dict (feature disabled) if the
        file is missing, yaml is unavailable, or the section is absent.
        """
        cfg_path = self.contexts_dir.parent / "entity_validation.yaml"
        if not cfg_path.exists() or _yaml is None:
            return {}
        try:
            with open(cfg_path, encoding="utf-8") as fh:
                data = _yaml.safe_load(fh) or {}
            return data.get("entity_memory") or {}
        except Exception as exc:
            logger.warning("Could not load entity_memory config from %s: %s", cfg_path, exc)
            return {}


    @property
    def index(self) -> List[ContextFileMeta]:
        """Lazy-load the file index on first access."""
        if self._index is None:
            self._index = build_file_index(self.contexts_dir)
        return self._index

    def refresh_index(self) -> None:
        """Force a rebuild of the in-memory index (e.g. after a new file is added)."""
        self._index = build_file_index(self.contexts_dir)


    def _match_entity_id(self, entity_keys: List[str]) -> Optional[str]:
        """
        Return the first entity_key that matches any id_pattern from config.

        Patterns are defined in entity_validation.yaml → entity_memory.id_patterns.
        No patterns hardcoded here — entirely driven by customer config.
        Returns None when entity memory is disabled or no key matches.
        """
        if not self._entity_memory_cfg.get("enabled", True):
            return None
        patterns = self._entity_memory_cfg.get("id_patterns") or []
        compiled = [re.compile(p, re.IGNORECASE) for p in patterns]
        for key in entity_keys:
            key_str = str(key).strip()
            if any(rx.search(key_str) for rx in compiled):
                # Normalise to uppercase, safe for a filename
                return re.sub(r"[^\w\-]", "_", key_str).upper()
        return None

    def _layer_source_context(self, record: Dict[str, Any]) -> Optional[SuggestResult]:
        """
        Layer -0.5 (fastest): if the record carries scope.source_context_file, route
        directly to that file — no LLM, no alias matching needed.

        source_context_file is set at knowledge-creation time by agent.py from
        agent._context_file_path (the context .md loaded for that session).
        It is the basename only (e.g. "p2p_context.md").
        """
        ctx_file = (record.get("scope") or {}).get("source_context_file")
        if not ctx_file:
            return None
        path = self.contexts_dir / Path(ctx_file).name
        if not path.exists():
            logger.debug("_layer_source_context: %s not found under contexts_dir — skip", ctx_file)
            return None
        rel = str(path.relative_to(self.contexts_dir))
        logger.info("KnowledgeFileRouter source_context hit: %s", rel)
        return SuggestResult(
            file_path=str(path),
            rel_path=rel,
            confidence="high",
            method="source_context",
            candidates=[],
        )

    def _layer0_entity_check(self, record: Dict[str, Any]) -> Optional[SuggestResult]:
        """
        Layer 0: if entity_keys contains a key matching any id_pattern in config,
        route directly to memory/entities/<entity_id>.md.

        The file is created on first write by write_topic_file — no pre-creation here.
        Skipped when entity_memory.enabled = false or memory_root is not configured.
        """
        if not self.memory_root or not self.entities_dir:
            return None
        entity_keys = record.get("entity_keys") or []
        entity_id = self._match_entity_id(entity_keys)
        if not entity_id:
            return None

        entity_file = self.entities_dir / f"{entity_id}.md"
        logger.info("KnowledgeFileRouter L0: routing to entity memory file %s", entity_file.name)
        return SuggestResult(
            file_path=str(entity_file),
            rel_path=f"memory/entities/{entity_id}.md",
            confidence="high",
            method="entity",
            candidates=[],
        )

    def _layer1_bundle_check(self, record: Dict[str, Any]) -> Optional[SuggestResult]:
        """
        Layer 1: route domain knowledge to a convention-discovered bundle.

        Bundles live under shared/knowledge/<bundle_id>/ and are matched by
        manifest skill first, then tag overlap. This is domain-agnostic and
        does not hardcode any bundle id.
        """
        if not self.bundle_registry:
            return None
        suggestion = self.bundle_registry.resolve_bundle_for(record)
        if not suggestion:
            return None
        rel = f"knowledge/{suggestion.bundle.bundle_id}/{suggestion.file_path.relative_to(suggestion.bundle.root).as_posix()}"
        return SuggestResult(
            file_path=str(suggestion.file_path),
            rel_path=rel,
            confidence=suggestion.confidence,
            method=suggestion.method,
            candidates=[],
            bundle_id=suggestion.bundle.bundle_id,
        )

    def list_files(self) -> List[Dict[str, str]]:
        """
        Return all available target files for the dashboard override picker.

        Groups:
          Context files  — shared/contexts/*.md  (org/process domain context)
          Memory files   — memory/skills/*.md, memory/org/**/*.md,
                           memory/entities/*.md, memory/users/*/*.md
                           grouped under category = "memory:<type>"
          Skill files    — skills/<skill>/SKILL.md (advanced skill definition target)
        """
        files: List[Dict[str, str]] = []

        for m in self.index:
            files.append({
                "file_path": str(m.path),
                "rel_path": m.rel_path,
                "category": "context",
                "tower": m.tower,
                "process": m.process,
                "skills": ", ".join(m.skills),
            })

        if self.memory_root and self.memory_root.is_dir():
            for md in sorted(self.memory_root.rglob("*.md")):
                # Skip MEMORY.md index itself — not a writable target
                if md.name == "MEMORY.md":
                    continue
                rel = md.relative_to(self.memory_root)
                parts = rel.parts
                # Determine category from first folder: skills/org/entities/users
                mem_type = parts[0] if parts else "memory"
                category = f"memory:{mem_type}"
                files.append({
                    "file_path": str(md),
                    "rel_path": f"memory/{rel}",
                    "category": category,
                    "tower": mem_type,
                    "process": md.stem,
                    "skills": "",
                })

        if self.bundle_registry:
            files.extend(self.bundle_registry.list_files())

        if self.skills_dir and self.skills_dir.is_dir():
            for skill_dir in sorted(p for p in self.skills_dir.iterdir() if p.is_dir()):
                skill_md = skill_dir / "SKILL.md"
                if not skill_md.exists():
                    continue
                files.append({
                    "file_path": str(skill_md),
                    "rel_path": f"skills/{skill_dir.name}/SKILL.md",
                    "category": "skill-definition",
                    "tower": "skill-definition",
                    "process": skill_dir.name,
                    "skills": skill_dir.name,
                })

        return files


    def _get_classify_config(self):
        """
        Build (once) the MemoryClassifyConfig from existing codebase sources.

        Sources wired here:
          shared_dir  — contexts_dir.parent  (contains entity_validation.yaml
                        and Enterprise_Context.md)
          skills_dir  — two levels up from contexts_dir, then into skills/
                        (IAF-Agent-Skills/skills/ relative to repo root)

        Returns None when memory_md package is unavailable.
        """
        if not _HAS_MEMORY_MD:
            return None
        if self._classify_config is not None:
            return self._classify_config

        shared_dir = self.contexts_dir.parent  # …/tenants/company/shared/

        # Prefer the tenant skill registry; bundled platform skills are an incomplete registry.
        skills_dir = self.skills_dir
        if not skills_dir or not skills_dir.is_dir():
            repo_root = self.contexts_dir.parents[4]
            bundled_skills = repo_root / "IAF-Agent-Skills" / "skills"
            skills_dir = bundled_skills if bundled_skills.is_dir() else None

        try:
            self._classify_config = _memory_md.build_classify_config(
                shared_dir=shared_dir,
                skills_dir=skills_dir,
            )
        except Exception as exc:
            logger.warning("_get_classify_config failed (non-fatal): %s", exc)
            self._classify_config = _memory_md.MemoryClassifyConfig()  # empty — use defaults

        # Non-fatal: memory seeding must never block routing.
        if self.memory_root:
            try:
                _memory_md.seed_memory_structure(self.memory_root, self._classify_config)
            except Exception as exc:
                logger.warning("seed_memory_structure failed (non-fatal): %s", exc)

        return self._classify_config

    def _layer_minus1_classify(self, record: Dict[str, Any]) -> tuple:
        """
        Layer -1: classify the knowledge record's destination type for MEMORY.md.

        Returns (dest_type, dest_name) — e.g. ("skill", "ccdops") or ("org", "p2p").
        Returns ("", "") when memory_md is not available.

        This classification is independent of context file routing.  It always
        runs so SuggestResult carries the memory destination even when the
        context file routing is fully confident.
        """
        if not _HAS_MEMORY_MD:
            return ("", "")
        try:
            cfg = self._get_classify_config()
            # Pass light LLM for L5 fallback — same model L3 context routing uses
            llm = None
            try:
                from iaf_agent_skills.model_provider import default_model_provider
                llm = default_model_provider.get("light")
            except Exception:
                pass
            return _memory_md.classify_destination(
                record, user_id=self.user_id, config=cfg, llm=llm
            )
        except Exception as exc:
            logger.warning("Layer -1 classify failed (non-fatal): %s", exc)
            return ("", "")

    def _layer3_llm_fallback(
        self,
        record: Dict[str, Any],
        candidates: List[ContextFileMeta],
    ) -> Optional[ContextFileMeta]:
        """
        One-shot LLM call to pick the best file from a list of candidates.

        We pass only file summaries (tower + process + top aliases) to keep
        the prompt short.  Returns None if the LLM is unavailable or fails.
        """
        try:
            from iaf_agent_skills.model_provider import default_model_provider
            llm = default_model_provider.get("light")
            if llm is None:
                return None

            # Build a compact summary of each candidate
            file_options = "\n".join(
                f"{i+1}. {m.rel_path} — Tower: {m.tower}, Process: {m.process}, "
                f"Aliases: {', '.join(m.aliases[:6])}"
                for i, m in enumerate(candidates)
            )

            prompt = (
                f"You are a file router for an enterprise knowledge base.\n\n"
                f"Knowledge entry:\n"
                f"  Summary    : {record.get('summary', '')}\n"
                f"  Type       : {record.get('knowledge_type', '')}\n"
                f"  Skill      : {record.get('skill', '')}\n"
                f"  Entity keys: {', '.join(record.get('entity_keys') or [])}\n"
                f"  Applies when: {record.get('applies_when', '')}\n\n"
                f"Available context files:\n{file_options}\n\n"
                f"Reply with ONLY the number (e.g. '2') of the best matching file. "
                f"If none fit, reply '0'."
            )

            response = llm.invoke(prompt)
            answer = response.content.strip() if hasattr(response, "content") else str(response).strip()

            # Parse the integer from the response
            match = re.search(r"\d+", answer)
            if match:
                idx = int(match.group()) - 1
                if 0 <= idx < len(candidates):
                    logger.info("LLM routing chose candidate %d: %s", idx + 1, candidates[idx].rel_path)
                    return candidates[idx]

        except Exception as exc:
            logger.warning("LLM routing fallback failed (non-fatal): %s", exc)

        return None


    def suggest(self, record: Dict[str, Any]) -> SuggestResult:
        """
        Suggest the best target .md file for a knowledge record.

        Returns a SuggestResult with:
            - file_path       : absolute path to the best context file (empty if none found)
            - rel_path        : display path shown in the dashboard
            - confidence      : "high" / "medium" / "low" / "none"
            - method          : which layer resolved it
            - candidates      : all candidate files (for the dashboard override picker)
            - memory_dest_type: Layer -1 dest_type ("skill" / "org" / "entity" / "user")
            - memory_dest_name: Layer -1 dest_name (skill/domain/entity/user_id)
        """
        mem_type, mem_name = self._layer_minus1_classify(record)

        # Layer 0: entity-specific knowledge goes to its own .md file.
        entity_result = self._layer0_entity_check(record)
        if entity_result:
            entity_result.memory_dest_type = mem_type
            entity_result.memory_dest_name = mem_name
            return entity_result

        all_candidates = self.list_files()

        # Layer 1: convention-discovered knowledge bundle (additive; MEMORY.md behavior unchanged).
        bundle_result = self._layer1_bundle_check(record)
        if bundle_result:
            bundle_result.candidates = all_candidates
            bundle_result.memory_dest_type = mem_type
            bundle_result.memory_dest_name = mem_name
            return bundle_result

        src_result = self._layer_source_context(record)
        if src_result:
            src_result.candidates = all_candidates
            src_result.memory_dest_type = mem_type
            src_result.memory_dest_name = mem_name
            return src_result

        # Layer 3: the LLM picks the context file when no source file or entity matches.
        chosen = self._layer3_llm_fallback(record, self.index)
        if chosen:
            return SuggestResult(
                file_path=str(chosen.path), rel_path=chosen.rel_path,
                confidence="low", method="llm",
                candidates=all_candidates,
                memory_dest_type=mem_type, memory_dest_name=mem_name,
            )

        logger.warning("KnowledgeFileRouter: no match for record %s", record.get("id"))
        return SuggestResult(
            file_path="", rel_path="",
            confidence="none", method="none",
            candidates=all_candidates,
            memory_dest_type=mem_type, memory_dest_name=mem_name,
        )


    def write_to_memory(
        self,
        record: Dict[str, Any],
        dest_type: Optional[str] = None,
        dest_name: Optional[str] = None,
    ) -> None:
        """
        Write a knowledge record to the MEMORY.md topic tree and regenerate
        the MEMORY.md index.

        dest_type / dest_name can be pre-computed by suggest() (stored on
        SuggestResult) or left None to recompute via Layer -1.

        Silently no-ops when:
          - self.memory_root is not set (caller didn't configure memory)
          - memory_md package is unavailable
        Never raises — memory writes must never block the confirm flow.
        """
        if not self.memory_root or not _HAS_MEMORY_MD:
            return
        try:
            if not dest_type:
                dest_type, dest_name = _memory_md.classify_destination(
                    record, user_id=self.user_id, config=self._get_classify_config()
                )
            if dest_type and dest_name:
                _memory_md.write_topic_file(
                    self.memory_root, dest_type, dest_name, record
                )
                _memory_md.regenerate_memory_md(self.memory_root)
                logger.info(
                    "write_to_memory: wrote record %s → %s/%s, MEMORY.md regenerated",
                    record.get("id", "?"), dest_type, dest_name,
                )
        except Exception as exc:
            logger.warning("write_to_memory failed (non-fatal): %s", exc)


    _SECTION_HEADER = "## Confirmed Knowledge"
    _SECTION_MARKER = "<!-- auto-generated – do not edit this section manually -->"
    _SKILL_SECTION_HEADER = "## Confirmed Operating Notes"

    def append(self, file_path: str | Path, record: Dict[str, Any]) -> None:
        """
        Append a formatted knowledge entry to the target .md file.

        Creates the '## Confirmed Knowledge' section if it doesn't exist.
        Idempotent by record id — will not duplicate an entry already present.

        Also writes to the MEMORY.md topic tree (if memory_root is configured)
        so the agent sees the knowledge on the next session start.
        """
        file_path = Path(file_path)

        if self.bundle_registry:
            bundle = self.bundle_registry.is_bundle_path(file_path)
            if bundle:
                appended = self._append_to_bundle(file_path, record, bundle)
                if appended:
                    self._append_bundle_log(bundle, file_path, record)
                self.write_to_memory(record)
                return

        # Skill definition path: explicit override appends to an operating-notes section.
        skill_name = self._skill_definition_name(file_path)
        if skill_name:
            self._append_to_skill_definition(file_path, record, skill_name)
            self.write_to_memory(record)
            return

        # Memory topic files use write_topic_file format; MEMORY.md is regenerated directly.
        if self.memory_root and self.memory_root in file_path.parents:
            if not _HAS_MEMORY_MD:
                raise RuntimeError("Memory topic writer is unavailable")
            try:
                parts = file_path.relative_to(self.memory_root).parts
                _mem_type = parts[0] if len(parts) > 1 else "entity"
                _memory_md.write_topic_file(self.memory_root, _mem_type, file_path.stem, record)
                _memory_md.regenerate_memory_md(self.memory_root)
                logger.info(
                    "KnowledgeFileRouter: wrote %s to memory/%s/%s",
                    record.get("id", "?"), _mem_type, file_path.name,
                )
            except Exception:
                logger.exception("append to memory file failed: %s", file_path)
                raise
            return

        if not file_path.exists():
            raise FileNotFoundError(f"Context file not found: {file_path}")

        record_id = record.get("id", "unknown")

        # Idempotency: skip if this record_id is already in the file
        existing = file_path.read_text(encoding="utf-8")
        if record_id in existing:
            logger.info("Knowledge %s already present in %s — skipping append", record_id, file_path.name)
            return

        entry = self._format_entry(record)

        # If the section already exists, append inside it.
        # Otherwise create the section at the end of the file.
        if self._SECTION_HEADER in existing:
            new_content = existing.rstrip() + "\n\n" + entry + "\n"
        else:
            new_content = (
                existing.rstrip()
                + f"\n\n---\n\n{self._SECTION_HEADER}\n{self._SECTION_MARKER}\n\n"
                + entry + "\n"
            )

        file_path.write_text(new_content, encoding="utf-8")
        logger.info(
            "KnowledgeFileRouter: appended record %s to %s",
            record_id, file_path.name,
        )

        _mem_type: Optional[str] = None
        _mem_name: Optional[str] = None
        if self.contexts_dir and file_path.parent == self.contexts_dir:
            _mem_type = "org"
            _mem_name = file_path.name
        self.write_to_memory(record, dest_type=_mem_type, dest_name=_mem_name)

    def _skill_definition_name(self, file_path: Path) -> Optional[str]:
        """Return the skill name when file_path is exactly skills/<skill>/SKILL.md."""
        if not self.skills_dir or file_path.name != "SKILL.md":
            return None
        try:
            root = self.skills_dir.resolve()
            path = file_path.resolve()
            rel = path.relative_to(root)
        except Exception:
            return None
        if len(rel.parts) == 2 and rel.parts[1] == "SKILL.md":
            return rel.parts[0]
        return None

    def _append_to_skill_definition(
        self,
        file_path: Path,
        record: Dict[str, Any],
        skill_name: str,
    ) -> bool:
        """Append confirmed operating notes to a SKILL.md without rewriting the skill body."""
        if not file_path.exists():
            raise FileNotFoundError(f"Skill definition file not found: {file_path}")

        record_id = record.get("id", "unknown")
        existing = file_path.read_text(encoding="utf-8")
        if record_id in existing:
            logger.info("Knowledge %s already present in skill definition %s", record_id, file_path)
            return False

        entry = self._format_entry(record)
        if self._SKILL_SECTION_HEADER in existing:
            new_content = existing.rstrip() + "\n\n" + entry + "\n"
        else:
            new_content = (
                existing.rstrip()
                + f"\n\n{self._SKILL_SECTION_HEADER}\n{self._SECTION_MARKER}\n\n"
                + "Use these notes as reviewer-approved additions to this skill's operating behavior.\n\n"
                + entry + "\n"
            )
        file_path.write_text(new_content, encoding="utf-8")
        logger.info(
            "KnowledgeFileRouter: appended record %s to skill definition %s",
            record_id, skill_name,
        )
        return True

    def _append_to_bundle(
        self,
        file_path: Path,
        record: Dict[str, Any],
        bundle: KnowledgeBundle,
    ) -> bool:
        """Append a confirmed entry to a bundle page, creating it if needed."""
        record_id = record.get("id", "unknown")
        if not file_path.exists():
            file_path.parent.mkdir(parents=True, exist_ok=True)
            file_path.write_text(self._new_bundle_page_content(file_path, record, bundle), encoding="utf-8")

        existing = file_path.read_text(encoding="utf-8")
        if record_id in existing:
            logger.info("Knowledge %s already present in bundle page %s", record_id, file_path)
            return False

        entry = self._format_entry(record)
        if self._SECTION_HEADER in existing:
            new_content = existing.rstrip() + "\n\n" + entry + "\n"
        else:
            new_content = (
                existing.rstrip()
                + f"\n\n---\n\n{self._SECTION_HEADER}\n{self._SECTION_MARKER}\n\n"
                + entry + "\n"
            )
        file_path.write_text(new_content, encoding="utf-8")
        logger.info(
            "KnowledgeFileRouter: appended record %s to bundle %s page %s",
            record_id, bundle.bundle_id, file_path.name,
        )
        return True

    @staticmethod
    def _new_bundle_page_content(
        file_path: Path,
        record: Dict[str, Any],
        bundle: KnowledgeBundle,
    ) -> str:
        title = file_path.stem.replace("_", " ").replace("-", " ").title()
        scope = record.get("scope") or {}
        knowledge_type = (
            record.get("knowledge_type")
            or record.get("type")
            or scope.get("knowledge_type")
            or scope.get("type")
            or "knowledge"
        )
        rel_path = f"/shared/knowledge/{bundle.bundle_id}/{file_path.relative_to(bundle.root).as_posix()}"
        today = date.today().isoformat()
        return (
            "---\n"
            f"type: {knowledge_type}\n"
            f"title: {title}\n"
            f"description: Confirmed knowledge collected for the {bundle.bundle_id} bundle.\n"
            f"resource: {rel_path}\n"
            f"tags: [{bundle.bundle_id}, knowledge-bundle]\n"
            f"timestamp: {today}\n"
            "status: active\n"
            "---\n\n"
            f"# {title}\n"
        )

    def _append_bundle_log(
        self,
        bundle: KnowledgeBundle,
        file_path: Path,
        record: Dict[str, Any],
    ) -> None:
        """Append one changelog line for a bundle page write."""
        log_path = bundle.log_path
        today = date.today().isoformat()
        summary = (record.get("summary") or "").strip()
        record_id = record.get("id", "unknown")
        rel_path = file_path.relative_to(bundle.root)
        line = f"- {today}: Added confirmed knowledge `{record_id}` to `{rel_path}` - {summary}\n"

        if not log_path.exists():
            log_path.write_text(
                "---\n"
                "type: log\n"
                f"title: {bundle.bundle_id} Knowledge Bundle Change Log\n"
                f"resource: /shared/knowledge/{bundle.bundle_id}/log.md\n"
                f"tags: [{bundle.bundle_id}, knowledge-bundle, changelog]\n"
                f"timestamp: {today}\n"
                "status: active\n"
                "---\n\n"
                f"# {bundle.bundle_id} Knowledge Bundle Change Log\n\n",
                encoding="utf-8",
            )
        existing = log_path.read_text(encoding="utf-8")
        if str(record_id) in existing:
            logger.info("Knowledge %s already present in bundle log %s", record_id, log_path)
            return
        log_path.write_text(existing.rstrip() + "\n\n" + line, encoding="utf-8")


    @staticmethod
    def _format_entry(record: Dict[str, Any]) -> str:
        """
        Produce a clean markdown block for one knowledge record.

        Example output:
            ### [2026-03-21] AP close cutoff is Day 3
            **Type**: rule | **Skill**: period_close_check | **ID**: kn_abc123
            **Applies when**: user asks about AP close cutoff
            > AP invoice cutoff is Day 3 of the month-end close cycle.
        """
        today       = date.today().isoformat()
        scope       = record.get("scope") or {}
        summary     = record.get("summary", "").strip()
        ktype       = record.get("knowledge_type") or record.get("type") or scope.get("knowledge_type") or scope.get("type") or "—"
        skill       = record.get("skill") or scope.get("skill") or "—"
        applies     = record.get("applies_when") or scope.get("applies_when") or "—"
        record_id   = record.get("id", "unknown")

        lines = [
            f"### [{today}] {summary}",
            f"**Type**: {ktype} | **Skill**: {skill} | **ID**: {record_id}",
            f"**Applies when**: {applies}",
            f"> {summary}",
        ]
        return "\n".join(lines)
