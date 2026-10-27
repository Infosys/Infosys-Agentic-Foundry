"""
Convention-based registry for tenant knowledge bundles.

A knowledge bundle is any directory under shared/knowledge/ that contains both
manifest.yaml and index.md. The platform owns this discovery and matching
contract; tenants own the bundle contents.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

try:
    import yaml as _yaml
except ImportError:  # pragma: no cover - optional dependency guard
    _yaml = None

logger = logging.getLogger(__name__)


_WORD_RE = re.compile(r"[a-z0-9][a-z0-9_\-]*", re.IGNORECASE)


@dataclass
class KnowledgeBundle:
    """Metadata and helpers for one shared/knowledge/<bundle_id> bundle."""

    bundle_id: str
    root: Path
    domain: str = ""
    skills: Set[str] = field(default_factory=set)
    tags: Set[str] = field(default_factory=set)
    write_targets: Dict[str, str] = field(default_factory=dict)

    @property
    def index_path(self) -> Path:
        return self.root / "index.md"

    @property
    def log_path(self) -> Path:
        return self.root / "log.md"

    @property
    def manifest_path(self) -> Path:
        return self.root / "manifest.yaml"

    def target_dir_for(self, knowledge_type: str) -> Path:
        rel = (
            self.write_targets.get((knowledge_type or "").strip().lower())
            or self.write_targets.get("default")
            or "notes/"
        )
        return self.root / rel.strip("/")

    def choose_page(self, record: Dict[str, Any]) -> Path:
        """Choose an existing target page by token overlap, or a generated page."""
        knowledge_type = _record_knowledge_type(record) or "note"
        target_dir = self.target_dir_for(knowledge_type)

        tokens = _record_tokens(record)
        candidates = []
        if target_dir.is_dir():
            candidates = [
                p
                for p in sorted(target_dir.glob("*.md"))
                if p.name not in {"index.md", "log.md", "MAINTAINER.md"}
            ]
        best: Optional[Path] = None
        best_score = 0
        for path in candidates:
            score = len(tokens.intersection(_page_tokens(path)))
            if score > best_score:
                best = path
                best_score = score
        if best and best_score > 0:
            return best

        name = _default_page_name(knowledge_type)
        return target_dir / name


@dataclass
class BundleSuggestion:
    bundle: KnowledgeBundle
    file_path: Path
    method: str
    confidence: str


class BundleRegistry:
    """Discover and match convention-based knowledge bundles."""

    def __init__(self, knowledge_dir: str | Path):
        self.knowledge_dir = Path(knowledge_dir)
        self._bundles: Optional[List[KnowledgeBundle]] = None

    @property
    def bundles(self) -> List[KnowledgeBundle]:
        if self._bundles is None:
            self._bundles = self._scan()
        return self._bundles

    def refresh(self) -> None:
        self._bundles = self._scan()

    def list_bundles(self) -> List[KnowledgeBundle]:
        return list(self.bundles)

    def is_bundle_path(self, file_path: str | Path) -> Optional[KnowledgeBundle]:
        path = Path(file_path).resolve()
        for bundle in self.bundles:
            try:
                path.relative_to(bundle.root.resolve())
                return bundle
            except ValueError:
                continue
        return None

    def list_files(self) -> List[Dict[str, str]]:
        files: List[Dict[str, str]] = []
        for bundle in self.bundles:
            for md in sorted(bundle.root.rglob("*.md")):
                if md.name in {"log.md", "MAINTAINER.md"}:
                    continue
                files.append({
                    "file_path": str(md),
                    "rel_path": f"knowledge/{bundle.bundle_id}/{md.relative_to(bundle.root)}",
                    "category": f"bundle:{bundle.bundle_id}",
                    "tower": bundle.domain or bundle.bundle_id,
                    "process": md.stem,
                    "skills": ", ".join(sorted(bundle.skills)),
                })
        return files

    def resolve_bundle_for(self, record: Dict[str, Any]) -> Optional[BundleSuggestion]:
        skill, record_tags = _record_skill_and_tags(record)

        for bundle in self.bundles:
            if skill and skill in bundle.skills:
                return BundleSuggestion(
                    bundle=bundle,
                    file_path=bundle.choose_page(record),
                    method="bundle_skill",
                    confidence="high",
                )

        best: Optional[KnowledgeBundle] = None
        best_overlap = 0
        for bundle in self.bundles:
            overlap = len(record_tags.intersection(bundle.tags))
            if overlap > best_overlap:
                best = bundle
                best_overlap = overlap

        if best and best_overlap:
            return BundleSuggestion(
                bundle=best,
                file_path=best.choose_page(record),
                method="bundle_tags",
                confidence="medium",
            )
        return None

    def _scan(self) -> List[KnowledgeBundle]:
        if not self.knowledge_dir.is_dir():
            return []
        bundles: List[KnowledgeBundle] = []
        for root in sorted(p for p in self.knowledge_dir.iterdir() if p.is_dir()):
            manifest = root / "manifest.yaml"
            index = root / "index.md"
            if not manifest.exists() or not index.exists():
                continue
            bundle = _load_bundle_manifest(root, manifest)
            if bundle:
                bundles.append(bundle)
        logger.info("BundleRegistry: discovered %d knowledge bundles from %s", len(bundles), self.knowledge_dir)
        return bundles


def _load_bundle_manifest(root: Path, manifest_path: Path) -> Optional[KnowledgeBundle]:
    if _yaml is None:
        logger.warning("BundleRegistry: yaml unavailable, skipping %s", manifest_path)
        return None
    try:
        data = _yaml.safe_load(manifest_path.read_text(encoding="utf-8")) or {}
        if data.get("kind") != "knowledge_bundle":
            return None
        bundle_id = str(data.get("bundle_id") or root.name).strip() or root.name
        write_targets = data.get("write_targets") or {}
        if not isinstance(write_targets, dict):
            write_targets = {}
        return KnowledgeBundle(
            bundle_id=bundle_id,
            root=root,
            domain=str(data.get("domain") or ""),
            skills={str(s).strip() for s in (data.get("skills") or []) if str(s).strip()},
            tags={str(t).strip().lower() for t in (data.get("tags") or []) if str(t).strip()},
            write_targets={str(k).strip().lower(): str(v).strip() for k, v in write_targets.items()},
        )
    except Exception as exc:
        logger.warning("BundleRegistry: failed to read %s: %s", manifest_path, exc)
        return None


def _record_skill_and_tags(record: Dict[str, Any]) -> tuple[str, Set[str]]:
    """Read skill/tags from top-level fields or nested scope (knowledge.jsonl shape)."""
    scope = record.get("scope") or {}
    skill = str(record.get("skill") or scope.get("skill") or "").strip()
    raw_tags = record.get("tags") or scope.get("tags") or []
    record_tags = {str(t).strip().lower() for t in raw_tags if str(t).strip()}
    return skill, record_tags


def _record_knowledge_type(record: Dict[str, Any]) -> str:
    scope = record.get("scope") or {}
    return str(
        record.get("knowledge_type")
        or record.get("type")
        or scope.get("knowledge_type")
        or scope.get("type")
        or ""
    ).strip().lower()


def _record_tokens(record: Dict[str, Any]) -> Set[str]:
    skill, record_tags = _record_skill_and_tags(record)
    raw_parts = [
        str(record.get("summary") or ""),
        _record_knowledge_type(record),
        skill,
        " ".join(sorted(record_tags)),
        " ".join(str(e) for e in (record.get("entity_keys") or [])),
    ]
    return {m.group(0).lower().replace("_", "-") for m in _WORD_RE.finditer(" ".join(raw_parts))}


def _page_tokens(path: Path) -> Set[str]:
    stem_tokens = set(path.stem.lower().replace("_", "-").split("-"))
    try:
        text = path.read_text(encoding="utf-8")[:1000]
    except Exception:
        text = ""
    text_tokens = {m.group(0).lower().replace("_", "-") for m in _WORD_RE.finditer(text)}
    return stem_tokens.union(text_tokens)


def _default_page_name(knowledge_type: str) -> str:
    normalized = re.sub(r"[^a-z0-9]+", "_", (knowledge_type or "note").lower()).strip("_") or "note"
    if normalized.endswith("s"):
        return f"learned_{normalized}.md"
    return f"learned_{normalized}s.md"
