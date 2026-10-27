"""
Lightweight read model for the Knowledge Dashboard.

The dashboard list/stat/status endpoints should not have to construct a full
SkillAgent. Runtime mutations still go through agent.memory so indexes, learning
side effects, and session state remain owned by the agent runtime.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


VALID_STATUSES = {"confirmed", "pending_review", "archived"}


class KnowledgeDashboardStore:
    """Read-only access to one agent's knowledge dashboard files."""

    def __init__(self, memory_root: str | Path):
        self.memory_root = Path(memory_root)
        self.context_graph_path = self.memory_root / "context_graph"
        self.knowledge_jsonl_path = self.context_graph_path / "knowledge.jsonl"
        self.extraction_cursor_path = self.context_graph_path / "extraction_cursor.json"

    def query_knowledge(
        self,
        status: Optional[str] = "confirmed",
        knowledge_type: Optional[str] = None,
        skill: Optional[str] = None,
        tag: Optional[str] = None,
        source: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
        include_archived: bool = False,
    ) -> Dict[str, Any]:
        """Return paginated knowledge records using the dashboard JSONL read model."""
        records = self._load_records()
        results = []
        for record in records:
            rec_status = record.get("status", "unknown")
            if not include_archived and rec_status == "archived":
                continue
            if status and status != "all" and rec_status != status:
                continue
            if knowledge_type and self._record_type(record) != knowledge_type:
                continue
            if source and record.get("source") != source:
                continue
            scope = record.get("scope") or {}
            rec_skill = record.get("skill") or scope.get("skill")
            if skill and rec_skill != skill:
                continue
            if tag:
                tags = record.get("tags") or scope.get("tags") or []
                if tag.lower() not in [str(t).lower() for t in tags]:
                    continue
            results.append(record)

        results.sort(key=lambda x: x.get("ts", ""), reverse=True)
        safe_offset = max(0, offset)
        safe_limit = max(1, limit)
        return {
            "items": results[safe_offset:safe_offset + safe_limit],
            "total": len(results),
            "offset": safe_offset,
            "limit": safe_limit,
        }

    def get_knowledge_stats(self) -> Dict[str, Any]:
        records = self._load_records()
        by_status: Dict[str, int] = {}
        by_type: Dict[str, int] = {}
        by_source: Dict[str, int] = {}
        for record in records:
            status = record.get("status", "unknown")
            by_status[status] = by_status.get(status, 0) + 1
            ktype = self._record_type(record)
            by_type[ktype] = by_type.get(ktype, 0) + 1
            source = record.get("source", "unknown")
            by_source[source] = by_source.get(source, 0) + 1
        return {
            "total": len(records),
            "by_status": by_status,
            "by_type": by_type,
            "by_source": by_source,
            "jsonl_bloat": self.get_jsonl_bloat_stats(),
        }

    def get_extraction_status(self) -> Optional[Dict[str, Any]]:
        try:
            if self.extraction_cursor_path.exists():
                return json.loads(self.extraction_cursor_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning("Failed to read extraction cursor %s: %s", self.extraction_cursor_path, exc)
        return None

    def get_jsonl_bloat_stats(self) -> Dict[str, Any]:
        if not self.knowledge_jsonl_path.exists():
            return {
                "total_lines": 0,
                "unique_ids": 0,
                "duplicate_lines": 0,
                "bloat_pct": 0.0,
                "file_size_bytes": 0,
            }

        total_lines = 0
        seen_ids: Dict[str, int] = {}
        try:
            file_size = self.knowledge_jsonl_path.stat().st_size
            with self.knowledge_jsonl_path.open("r", encoding="utf-8") as fh:
                for line_no, line in enumerate(fh, start=1):
                    stripped = line.strip()
                    if not stripped:
                        continue
                    total_lines += 1
                    try:
                        record = json.loads(stripped)
                        rid = record.get("id") or f"__no_id_{line_no}"
                        seen_ids[rid] = seen_ids.get(rid, 0) + 1
                    except json.JSONDecodeError:
                        continue
            unique_ids = len(seen_ids)
            duplicate_lines = total_lines - unique_ids
            bloat_pct = round((duplicate_lines / total_lines * 100), 1) if total_lines else 0.0
            return {
                "total_lines": total_lines,
                "unique_ids": unique_ids,
                "duplicate_lines": duplicate_lines,
                "bloat_pct": bloat_pct,
                "file_size_bytes": file_size,
            }
        except OSError as exc:
            logger.warning("Failed to compute JSONL bloat stats for %s: %s", self.knowledge_jsonl_path, exc)
            return {
                "total_lines": 0,
                "unique_ids": 0,
                "duplicate_lines": 0,
                "bloat_pct": 0.0,
                "file_size_bytes": 0,
                "error": str(exc),
            }

    def _load_records(self) -> List[Dict[str, Any]]:
        if not self.knowledge_jsonl_path.exists():
            return []
        records_by_id: Dict[str, Dict[str, Any]] = {}
        try:
            with self.knowledge_jsonl_path.open("r", encoding="utf-8") as fh:
                for line_no, line in enumerate(fh, start=1):
                    stripped = line.strip()
                    if not stripped:
                        continue
                    try:
                        record = json.loads(stripped)
                    except json.JSONDecodeError:
                        logger.warning("Skipping invalid knowledge JSONL line %s", line_no)
                        continue
                    rid = record.get("id") or f"__no_id_{line_no}"
                    records_by_id[rid] = self._normalize_record(record)
        except OSError as exc:
            logger.warning("Failed to read knowledge JSONL %s: %s", self.knowledge_jsonl_path, exc)
            return []
        return list(records_by_id.values())

    @staticmethod
    def _normalize_record(record: Dict[str, Any]) -> Dict[str, Any]:
        normalized = dict(record)
        if normalized.get("status") not in VALID_STATUSES:
            normalized["status"] = "unknown"
        if not normalized.get("summary"):
            normalized["summary"] = f"[{normalized.get('type', 'unknown')} record - no summary]"
        return normalized

    @staticmethod
    def _record_type(record: Dict[str, Any]) -> str:
        scope = record.get("scope") or {}
        return (
            record.get("knowledge_type")
            or record.get("type")
            or scope.get("knowledge_type")
            or scope.get("type")
            or "unknown"
        )
