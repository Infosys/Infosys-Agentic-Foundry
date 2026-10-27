"""
Knowledge Query Module

Extracted from memory.py for modularity.
Contains: compaction, bloat stats, querying, stats, duplicate detection, and merge operations.

Usage:
    from iaf_agent_skills.knowledge_query import (
        compact_knowledge_jsonl,
        get_jsonl_bloat_stats,
        query_knowledge,
        get_knowledge_stats,
        find_duplicate_groups,
        merge_knowledge,
    )
"""

import json
import os
import shutil
import logging

from .file_lock import portable_lock
from pathlib import Path
from datetime import datetime
from typing import Dict, Any, List, Optional

logger = logging.getLogger(__name__)



def compact_knowledge_jsonl(
    knowledge_jsonl_path: Path,
) -> Dict[str, Any]:
    """
    Compact the knowledge JSONL file by deduplicating records.

    Workflow:
        1. Archive the current file to context_graph/archive/ (timestamped copy).
        2. Read all lines, keeping only the last-write per ID (append-only semantics).
        3. Write deduplicated records to a .tmp file.
        4. Atomic rename .tmp → knowledge.jsonl (crash-safe).

    Returns:
        Dict with keys: total_before, unique_after, removed, archive_path.
        On error or missing file, returns a dict with removed=0 and an error key.
    """
    jsonl_path = knowledge_jsonl_path

    if not jsonl_path.exists():
        logger.info("compact_knowledge_jsonl: file does not exist, nothing to compact")
        return {"total_before": 0, "unique_after": 0, "removed": 0, "archive_path": None}

    try:
        archive_dir = jsonl_path.parent / "archive"
        archive_dir.mkdir(parents=True, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        archive_path = archive_dir / f"knowledge_{ts}.jsonl"
        shutil.copy2(str(jsonl_path), str(archive_path))
        logger.info("compact_knowledge_jsonl: archived to %s", archive_path)

        records_by_id: Dict[str, str] = {}  # id -> raw line (preserves original JSON)
        total_lines = 0
        skipped_lines = 0

        with portable_lock(jsonl_path):
            with open(jsonl_path, "r", encoding="utf-8") as f:
                for line in f:
                    stripped = line.strip()
                    if not stripped:
                        continue
                    total_lines += 1
                    try:
                        record = json.loads(stripped)
                        rid = record.get("id")
                        if rid:
                            records_by_id[rid] = stripped
                        else:
                            # Keep lines without an 'id' field (append at end)
                            skipped_lines += 1
                            records_by_id[f"__no_id_{skipped_lines}"] = stripped
                    except json.JSONDecodeError as je:
                        skipped_lines += 1
                        logger.warning("compact_knowledge_jsonl: skipping corrupt line: %s", je)

        unique_count = len(records_by_id)
        removed = total_lines - unique_count

        tmp_path = jsonl_path.with_suffix(".jsonl.tmp")
        with portable_lock(tmp_path):
            with open(tmp_path, "w", encoding="utf-8") as f:
                for raw_line in records_by_id.values():
                    f.write(raw_line + "\n")
                f.flush()

        os.replace(str(tmp_path), str(jsonl_path))

        logger.info(
            "compact_knowledge_jsonl: %d → %d records (removed %d duplicates)",
            total_lines, unique_count, removed,
        )
        return {
            "total_before": total_lines,
            "unique_after": unique_count,
            "removed": removed,
            "archive_path": str(archive_path),
        }

    except Exception as e:
        logger.error("compact_knowledge_jsonl failed: %s", e)
        return {"total_before": 0, "unique_after": 0, "removed": 0, "archive_path": None, "error": "An internal error occurred"}



def get_jsonl_bloat_stats(
    knowledge_jsonl_path: Path,
) -> Dict[str, Any]:
    """
    Return bloat statistics for the knowledge JSONL file without modifying it.

    Returns:
        Dict with: total_lines, unique_ids, duplicate_lines, bloat_pct, file_size_bytes.
    """
    jsonl_path = knowledge_jsonl_path
    if not jsonl_path.exists():
        return {"total_lines": 0, "unique_ids": 0, "duplicate_lines": 0, "bloat_pct": 0.0, "file_size_bytes": 0}

    try:
        file_size = jsonl_path.stat().st_size
        seen_ids: Dict[str, int] = {}
        total_lines = 0

        with open(jsonl_path, "r", encoding="utf-8") as f:
            for line in f:
                stripped = line.strip()
                if not stripped:
                    continue
                total_lines += 1
                try:
                    record = json.loads(stripped)
                    rid = record.get("id", f"__no_id_{total_lines}")
                    seen_ids[rid] = seen_ids.get(rid, 0) + 1
                except json.JSONDecodeError:
                    pass  # corrupt lines counted in total but not in unique

        unique_ids = len(seen_ids)
        duplicate_lines = total_lines - unique_ids
        bloat_pct = round((duplicate_lines / total_lines * 100), 1) if total_lines > 0 else 0.0

        return {
            "total_lines": total_lines,
            "unique_ids": unique_ids,
            "duplicate_lines": duplicate_lines,
            "bloat_pct": bloat_pct,
            "file_size_bytes": file_size,
        }
    except Exception as e:
        logger.error("get_jsonl_bloat_stats failed: %s", e)
        return {"total_lines": 0, "unique_ids": 0, "duplicate_lines": 0, "bloat_pct": 0.0, "file_size_bytes": 0, "error": "An internal error occurred"}



def query_knowledge(
    knowledge_jsonl_path: Path,
    knowledge_indexer,
    status: str = "confirmed",
    knowledge_type: str = None,
    skill: str = None,
    tag: str = None,
    source: str = None,
    limit: int = 50,
    offset: int = 0,
    include_archived: bool = False,
) -> Dict:
    """
    Query knowledge records with structured filters.
    Used by dashboard and API endpoints.
    
    Tries SQLite index first (O(log n) via B-tree), falls back to JSONL scan.
    
    Args:
        status: Filter by status (default: confirmed only). Use None or 'all' for all.
        knowledge_type: Filter by type (e.g., "rule", "preference")
        skill: Filter by skill scope
        tag: Filter by tag presence
        source: Filter by source (e.g., "user_taught", "inferred", "thumbs_down")
        limit: Max records to return per page
        offset: Number of records to skip (for pagination)
        include_archived: If True, include archived records
        
    Returns:
        Dict with 'items' (list of records), 'total' (filtered count), 'offset', 'limit'
    """
    try:
        result = knowledge_indexer.query_records(
            status=status, knowledge_type=knowledge_type, skill=skill,
            tag=tag, source=source, limit=limit, offset=offset,
            include_archived=include_archived,
        )
        if result.get("total", 0) > 0 or not knowledge_jsonl_path.exists():
            return result
    except Exception as e:
        logger.debug("SQLite query_records failed, falling back to JSONL: %s", e)
    
    return _query_knowledge_jsonl(
        knowledge_jsonl_path,
        status, knowledge_type, skill, tag, source, limit, offset, include_archived
    )


def _query_knowledge_jsonl(
    knowledge_jsonl_path: Path,
    status: str,
    knowledge_type: str,
    skill: str,
    tag: str,
    source: str,
    limit: int,
    offset: int,
    include_archived: bool,
) -> Dict:
    """JSONL fallback for query_knowledge."""
    empty_result = {"items": [], "total": 0, "offset": offset, "limit": limit}
    if not knowledge_jsonl_path.exists():
        return empty_result
    
    records_by_id = {}
    try:
        with open(knowledge_jsonl_path, "r", encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    record = json.loads(line)
                    records_by_id[record.get("id", "")] = record
    except Exception as e:
        logger.warning("Error reading knowledge: %s", e)
        return empty_result
    
    VALID_STATUSES = {"confirmed", "pending_review", "archived"}
    for record in records_by_id.values():
        if record.get("status") not in VALID_STATUSES:
            record["status"] = "unknown"
        if not record.get("summary"):
            record["summary"] = f"[{record.get('type', 'unknown')} record — no summary]"
    
    results = []
    for record in records_by_id.values():
        rec_status = record.get("status", "unknown")
        if not include_archived and rec_status == "archived":
            continue
        if status and status != 'all' and rec_status != status:
            continue
        if knowledge_type and record.get("type") != knowledge_type:
            continue
        if source and record.get("source") != source:
            continue
        scope = record.get("scope", {})
        if skill and scope.get("skill") and scope["skill"] != skill:
            continue
        if tag:
            tags = scope.get("tags", [])
            if tag.lower() not in [t.lower() for t in tags]:
                continue
        results.append(record)
    
    results.sort(key=lambda x: x.get("ts", ""), reverse=True)
    total_filtered = len(results)
    safe_offset = max(0, offset)
    safe_limit = max(1, limit)
    paginated = results[safe_offset:safe_offset + safe_limit]
    
    return {"items": paginated, "total": total_filtered, "offset": safe_offset, "limit": safe_limit}



def get_knowledge_stats(
    knowledge_jsonl_path: Path,
    knowledge_indexer,
    get_bloat_stats_fn,
) -> Dict:
    """
    Get statistics about the knowledge store.
    Used by dashboard and brain stats.
    
    Tries SQLite index first, falls back to JSONL scan.
    Includes JSONL bloat metrics for operational visibility.
    
    Args:
        get_bloat_stats_fn: Function to compute bloat stats (injected for testability)
    
    Returns:
        Dict with counts by status, type, source, and jsonl_bloat sub-dict.
    """
    try:
        stats = knowledge_indexer.get_stats()
        total = stats.get("knowledge_records", 0)
        if total > 0:
            result = {
                "total": total,
                "by_status": stats.get("by_status", {}),
                "by_type": stats.get("by_type", {}),
                "by_source": stats.get("by_source", {}),
            }
            result["jsonl_bloat"] = get_bloat_stats_fn()
            return result
    except Exception as e:
        logger.debug("SQLite get_stats failed, falling back to JSONL: %s", e)
    
    return _get_knowledge_stats_jsonl(knowledge_jsonl_path, get_bloat_stats_fn)


def _get_knowledge_stats_jsonl(
    knowledge_jsonl_path: Path,
    get_bloat_stats_fn,
) -> Dict:
    """JSONL fallback for get_knowledge_stats."""
    if not knowledge_jsonl_path.exists():
        return {"total": 0, "by_status": {}, "by_type": {}, "by_source": {}}
    
    records_by_id = {}
    try:
        with open(knowledge_jsonl_path, "r", encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    record = json.loads(line)
                    records_by_id[record.get("id", "")] = record
    except Exception:
        return {"total": 0, "by_status": {}, "by_type": {}, "by_source": {}}
    
    by_status = {}
    by_type = {}
    by_source = {}
    
    for record in records_by_id.values():
        status = record.get("status", "unknown")
        by_status[status] = by_status.get(status, 0) + 1
        
        ktype = record.get("type", "unknown")
        by_type[ktype] = by_type.get(ktype, 0) + 1
        
        source = record.get("source", "unknown")
        by_source[source] = by_source.get(source, 0) + 1
    
    return {
        "total": len(records_by_id),
        "by_status": by_status,
        "by_type": by_type,
        "by_source": by_source,
        "jsonl_bloat": get_bloat_stats_fn(),
    }



def find_duplicate_groups(
    knowledge_jsonl_path: Path,
    knowledge_indexer,
    light_llm,
    status: str = "all",
    min_group_size: int = 2,
    max_records: int = 200,
) -> Dict:
    """
    Use LLM to semantically cluster knowledge records into duplicate groups.
    
    This is an on-demand, review-time operation — NOT run at write time.
    The LLM reads record summaries and groups semantically equivalent ones.
    Human then decides which to keep/merge/dismiss via the dashboard.
    
    Args:
        status: Filter records by status before scanning.
                "all" = confirmed + pending_review (not archived).
                Or a specific status string.
        min_group_size: Minimum group size to report (default 2 = pairs).
        max_records: Safety cap on how many records to send to LLM.
        
    Returns:
        Dict with:
          - groups: List of {group_id, theme, record_ids, suggested_merge}
          - total_scanned: Number of records analyzed
          - error: Optional error message
    """
    from langchain_core.messages import HumanMessage
    
    empty_result = {"groups": [], "total_scanned": 0}
    
    if not light_llm:
        return {**empty_result, "error": "No LLM configured for duplicate detection"}
    
    # ── Step 1: Collect active records (SQLite first, JSONL fallback) ──
    candidates = []
    try:
        candidates = knowledge_indexer.get_records_for_dedup(
            status=status, max_records=max_records
        )
    except Exception as e:
        logger.debug("SQLite dedup query failed, falling back to JSONL: %s", e)
    
    if not candidates:
        if not knowledge_jsonl_path.exists():
            return empty_result
        records_by_id = {}
        try:
            with portable_lock(knowledge_jsonl_path):
                with open(knowledge_jsonl_path, "r", encoding="utf-8") as f:
                    for line in f:
                        if line.strip():
                            record = json.loads(line)
                            records_by_id[record.get("id", "")] = record
        except Exception as e:
            logger.error("Failed to read knowledge: %s", e, exc_info=True)
            return {**empty_result, "error": "Failed to read knowledge"}
        for record in records_by_id.values():
            rec_status = record.get("status", "unknown")
            if rec_status == "archived":
                continue
            if status and status != "all" and rec_status != status:
                continue
            candidates.append(record)
    
    total_scanned = len(candidates)
    if total_scanned < min_group_size:
        return {"groups": [], "total_scanned": total_scanned}
    
    # Cap records sent to LLM to avoid token explosion
    if len(candidates) > max_records:
        # Prefer newer records (they're more likely to be duplicates of older ones)
        candidates.sort(key=lambda x: x.get("ts", ""), reverse=True)
        candidates = candidates[:max_records]
    
    record_summaries = []
    for r in candidates:
        record_summaries.append({
            "id": r.get("id", ""),
            "summary": (r.get("summary") or "")[:200],
            "type": r.get("type", "unknown"),
            "status": r.get("status", "unknown"),
        })
    
    prompt = f"""You are a duplicate detection engine for a knowledge base.

## TASK
Analyze the knowledge records below and group semantically DUPLICATE or NEAR-DUPLICATE entries.
Two records are duplicates if they express the SAME rule, preference, fact, or correction — 
even if worded differently.

## RECORDS ({len(record_summaries)} items):
{json.dumps(record_summaries, indent=1)}

## RULES
1. Only group records that are TRUE semantic duplicates (same meaning, same intent).
2. Do NOT group records that are merely related but distinct.
3. Each record can appear in at most ONE group.
4. For each group, suggest a clean merged summary that captures the best wording.
5. min_group_size = {min_group_size} — only return groups with at least this many records.

## OUTPUT FORMAT
Return ONLY a JSON array. Each element:
{{
  "group_id": "dup_001",
  "theme": "Short description of what these duplicates are about",
  "record_ids": ["k_xxx", "k_yyy"],
  "suggested_merge": "The best single summary that captures the meaning of all records in this group"
}}

If no duplicates found, return an empty array: []
IMPORTANT: Return ONLY the JSON array, no markdown fencing, no explanation."""

    try:
        messages = [HumanMessage(content=prompt)]
        response = light_llm.invoke(messages)
        try:
            import llm_tracker as _lt
            _lt.record("knowledge_query", response, 0.0, getattr(light_llm, 'azure_deployment', getattr(light_llm, 'model_name', '')))
        except Exception:
            pass
        raw = response.content if hasattr(response, 'content') else str(response)
        raw = raw.strip()
        
        # Strip markdown code fencing if present
        if raw.startswith("```"):
            lines = raw.split("\n")
            # Remove first line (```json) and last line (```)
            lines = [l for l in lines if not l.strip().startswith("```")]
            raw = "\n".join(lines).strip()
        
        groups = json.loads(raw)
        if not isinstance(groups, list):
            groups = []
        
        # Validate: filter out groups referencing non-existent IDs
        valid_ids = {r["id"] for r in record_summaries}
        validated_groups = []
        for g in groups:
            valid_record_ids = [rid for rid in g.get("record_ids", []) if rid in valid_ids]
            if len(valid_record_ids) >= min_group_size:
                g["record_ids"] = valid_record_ids
                validated_groups.append(g)
        
        return {
            "groups": validated_groups,
            "total_scanned": total_scanned,
        }
        
    except json.JSONDecodeError as e:
        logger.error("LLM returned invalid JSON: %s", e, exc_info=True)
        return {**empty_result, "total_scanned": total_scanned,
                "error": "LLM returned invalid JSON"}
    except Exception as e:
        logger.error("Duplicate detection failed: %s", e, exc_info=True)
        return {**empty_result, "total_scanned": total_scanned,
                "error": "Duplicate detection failed"}



def merge_knowledge(
    keep_id: str,
    archive_ids: List[str],
    find_knowledge_by_id_fn,
    edit_knowledge_fn,
    confirm_knowledge_fn,
    reject_knowledge_fn,
    merged_summary: str = None,
) -> Dict:
    """
    Merge duplicate knowledge records: keep one winner, archive the rest.
    
    Optionally updates the winner's summary with a cleaner merged text.
    Uses existing confirm/reject/edit methods for consistency.
    
    Args:
        keep_id: ID of the record to keep (the "winner")
        archive_ids: IDs of records to archive (the "losers")
        find_knowledge_by_id_fn: Function to find record by ID
        edit_knowledge_fn: Function to edit a record
        confirm_knowledge_fn: Function to confirm a record
        reject_knowledge_fn: Function to reject/archive a record
        merged_summary: Optional improved summary for the winner
        
    Returns:
        Dict with status, archived_count, errors
    """
    result = {"status": "ok", "kept": keep_id, "archived": [], "errors": []}
    
    # Validation: keep_id must not be in archive_ids
    if keep_id in archive_ids:
        return {"status": "error", "errors": ["keep_id cannot be in archive_ids"]}
    
    if not archive_ids:
        return {"status": "error", "errors": ["At least one archive_id required"]}
    
    # Verify keep_id exists
    winner = find_knowledge_by_id_fn(keep_id)
    if not winner:
        return {"status": "error", "errors": [f"Keep record {keep_id} not found"]}
    
    # Optionally update the winner's summary with merged text
    if merged_summary and merged_summary.strip():
        edit_ok = edit_knowledge_fn(keep_id, summary=merged_summary.strip())
        if not edit_ok:
            result["errors"].append(f"Failed to update summary for {keep_id}")
    
    # If winner is pending_review, auto-confirm it (user chose to keep it)
    if winner.get("status") == "pending_review":
        confirm_knowledge_fn(keep_id)
    
    # Archive each loser
    for aid in archive_ids:
        loser = find_knowledge_by_id_fn(aid)
        if not loser:
            result["errors"].append(f"Record {aid} not found, skipped")
            continue
        if loser.get("status") == "archived":
            result["errors"].append(f"Record {aid} already archived, skipped")
            continue
        ok = reject_knowledge_fn(aid)
        if ok:
            result["archived"].append(aid)
        else:
            result["errors"].append(f"Failed to archive {aid}")
    
    result["archived_count"] = len(result["archived"])
    logger.info("Knowledge merge: kept %s, archived %d records", keep_id, len(result['archived']))
    return result
