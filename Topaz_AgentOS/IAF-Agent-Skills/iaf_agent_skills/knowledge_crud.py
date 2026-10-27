"""
Knowledge CRUD Operations for AgentMemory.

Extracted from memory.py to improve modularity.
This module handles:
- write_knowledge() → create new knowledge records
- confirm_knowledge() → mark pending_review as confirmed
- reject_knowledge() → archive/reject a knowledge record
- bulk_confirm_knowledge() → bulk confirm multiple records
- bulk_reject_knowledge() → bulk reject multiple records
- edit_knowledge() → edit existing knowledge record
- find_knowledge_by_id() → find record by ID

USAGE:
    from iaf_agent_skills.knowledge_crud import (
        write_knowledge,
        confirm_knowledge,
        reject_knowledge,
        edit_knowledge,
        bulk_confirm_knowledge,
        bulk_reject_knowledge,
        find_knowledge_by_id,
        KNOWLEDGE_TYPES,
        KNOWLEDGE_STATUSES,
        KNOWLEDGE_SOURCES,
    )

DEPENDENCIES:
    - pathlib.Path
    - file_lock.portable_lock (cross-platform file locking)
    - json, uuid, hashlib, logging
    - datetime
"""

import json
import uuid
import hashlib
import logging

from .file_lock import portable_lock
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Any

logger = logging.getLogger(__name__)



# Valid knowledge types for context graph
KNOWLEDGE_TYPES = {
    "exception", "rule", "preference", "workaround",
    "pattern", "correction", "alias", "fact",
    "skill_pattern", "workflow_trace"
}

# Valid status values for knowledge records
KNOWLEDGE_STATUSES = {"confirmed", "pending_review", "archived"}

# Valid source values
KNOWLEDGE_SOURCES = {
    "user_confirmed", "user_taught", "nightly_batch",
    "thumbs_down", "learn_command", "inferred"
}



def write_knowledge(
    *,
    knowledge_type: str,
    summary: str,
    knowledge_jsonl_path: Path,
    knowledge_indexer: Any,
    session_id: str,
    user_id: str,
    tags: List[str] = None,
    applies_when: str = None,
    source: str = "user_confirmed",
    status: str = "confirmed",
    skill: str = None,
    episode_id: str = None,
    entity_keys: List[str] = None,
    user_query: str = None,
    recommended_tools: List[str] = None,
    supersedes_summary: str = None,
    source_context_file: str = None,
) -> str:
    """
    Write a knowledge record to knowledge.jsonl (evolved schema).

    Schema fields:
    - status: confirmed | pending_review | archived
    - source: user_confirmed | user_taught | nightly_batch | thumbs_down | learn_command
    - user_query: original user question that produced this knowledge
    - entity_keys: structured entity refs ["type:id"] for ERP linkage
    - scope: {skill, source_context_file, tags, applies_when, recommended_tools}
    - provenance: {episode_id, session_id, user_id, confirmed_by, confirmed_at}
    - lifecycle: {use_count, last_used, expires_at, superseded_by}

    Args:
        knowledge_type: One of KNOWLEDGE_TYPES
        summary: Human-readable knowledge statement
        knowledge_jsonl_path: Path to knowledge.jsonl file
        knowledge_indexer: KnowledgeIndexer instance for SQLite indexing
        session_id: Current session ID
        user_id: Current user ID
        tags: Flat list of searchable tags (e.g., ["vendor", "ACME", "quality"])
        applies_when: Natural language description of when this knowledge applies
        source: How this knowledge was created
        status: Knowledge lifecycle status
        skill: Skill this knowledge applies to (None = global)
        episode_id: ID of the episode that triggered this knowledge
        entity_keys: Structured entity refs e.g. ["vendor:ACME", "invoice:INV-001"]
        user_query: The original user question that led to this knowledge
        recommended_tools: Tools that worked well e.g. ["sql_query", "read_file"]
        source_context_file: Context .md file that was loaded when learning was captured
                             (basename only, e.g. "p2p_context.md"). Used by routers
                             to skip LLM classification entirely.
        
    Returns:
        Knowledge ID (e.g., "k_20260211_abc123")
    """
    try:
        if knowledge_type not in KNOWLEDGE_TYPES:
            logger.warning("Invalid knowledge type: %s, using 'pattern'", knowledge_type)
            knowledge_type = "pattern"
        
        if status not in KNOWLEDGE_STATUSES:
            status = "pending_review"
        
        # Generate knowledge ID (12-char hash + UUID entropy to avoid collisions at scale)
        ts = datetime.now()
        short_hash = hashlib.sha256(f"{ts.isoformat()}{summary}{uuid.uuid4().hex}".encode()).hexdigest()[:12]
        knowledge_id = f"k_{ts.strftime('%Y%m%d')}_{short_hash}"
        
        record = {
            "id": knowledge_id,
            "ts": ts.isoformat(),
            "type": knowledge_type,
            "summary": summary,
            "status": status,
            "source": source,
            "user_query": (user_query or "")[:200],
            "entity_keys": (entity_keys or [])[:20],
            "scope": {
                "skill": skill,
                "source_context_file": Path(source_context_file).name if source_context_file else None,
                "tags": tags or [],
                "applies_when": applies_when or "",
                "recommended_tools": (recommended_tools or [])[:10]
            },
            "provenance": {
                "episode_id": episode_id,
                "session_id": session_id,
                "user_id": user_id or "unknown",
                "confirmed_by": user_id if status == "confirmed" else None,
                "confirmed_at": ts.isoformat() if status == "confirmed" else None
            },
            "lifecycle": {
                "use_count": 0,
                "last_used": None,
                "expires_at": None,
                "superseded_by": None,
                "supersedes_summary": supersedes_summary or None
            }
        }
        
        knowledge_jsonl_path.parent.mkdir(parents=True, exist_ok=True)
        with portable_lock(knowledge_jsonl_path):
            with open(knowledge_jsonl_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(record) + "\n")
                f.flush()
        
        # Phase 5b: auto-index for semantic search
        try:
            knowledge_indexer.upsert_knowledge(record)
        except Exception as idx_err:
            logger.warning("Knowledge index upsert failed (non-fatal): %s", idx_err)
        
        logger.info("Knowledge [%s]: %s - %s...", status, knowledge_type, summary[:50])
        return knowledge_id
        
    except Exception as e:
        logger.warning("Failed to write knowledge: %s", e)
        return f"k_error_{datetime.now().strftime('%Y%m%d')}"



def find_knowledge_by_id(
    knowledge_id: str,
    knowledge_jsonl_path: Path,
    knowledge_indexer: Any,
) -> Optional[Dict]:
    """
    Find the latest version of a knowledge record by ID.
    Tries SQLite index first (O(log n)), falls back to JSONL scan.
    
    Args:
        knowledge_id: The knowledge ID to find
        knowledge_jsonl_path: Path to knowledge.jsonl file
        knowledge_indexer: KnowledgeIndexer instance
        
    Returns:
        Dict record or None
    """
    try:
        result = knowledge_indexer.get_record_by_id(knowledge_id)
        if result is not None:
            return result
    except Exception as e:
        logger.debug("SQLite lookup failed for %s, falling back to JSONL: %s", knowledge_id, e)
    
    return find_knowledge_by_id_jsonl(knowledge_id, knowledge_jsonl_path)


def find_knowledge_by_id_jsonl(
    knowledge_id: str,
    knowledge_jsonl_path: Path,
) -> Optional[Dict]:
    """JSONL fallback for find_knowledge_by_id."""
    if not knowledge_jsonl_path.exists():
        return None
    
    latest = None
    try:
        with portable_lock(knowledge_jsonl_path):
            with open(knowledge_jsonl_path, "r", encoding="utf-8") as f:
                for line in f:
                    if knowledge_id in line:
                        record = json.loads(line)
                        if record.get("id") == knowledge_id:
                            latest = record
    except Exception as e:
        logger.warning("Error reading knowledge: %s", e)
    
    return latest



def confirm_knowledge(
    knowledge_id: str,
    knowledge_jsonl_path: Path,
    knowledge_indexer: Any,
    user_id: str,
    written_to: str = None,
) -> bool:
    """
    Mark a pending_review knowledge record as confirmed.

    Rewrites the record in-place by appending an updated version.
    The reader always takes the LAST record with a given ID.

    Args:
        knowledge_id: The ID to confirm (e.g., "k_20260211_abc123")
        knowledge_jsonl_path: Path to knowledge.jsonl file
        knowledge_indexer: KnowledgeIndexer instance
        user_id: User performing the confirmation
        written_to: Optional path of the .md context file this entry was appended to

    Returns:
        True if confirmed, False if not found or error
    """
    record = find_knowledge_by_id(knowledge_id, knowledge_jsonl_path, knowledge_indexer)
    if not record:
        logger.warning("Knowledge %s not found", knowledge_id)
        return False

    record["status"] = "confirmed"
    record["provenance"]["confirmed_by"] = user_id
    record["provenance"]["confirmed_at"] = datetime.now().isoformat()
    record["ts"] = datetime.now().isoformat()
    if written_to:
        record["written_to"] = written_to
    
    # Append updated record (last write wins) — file-locked for concurrency
    try:
        with portable_lock(knowledge_jsonl_path):
            with open(knowledge_jsonl_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(record) + "\n")
                f.flush()
        # Phase 5b: update index with new status
        try:
            knowledge_indexer.upsert_knowledge(record)
        except Exception as idx_err:
            logger.warning("Knowledge index upsert failed (non-fatal): %s", idx_err)
        logger.info("Knowledge confirmed: %s", knowledge_id)
        return True
    except Exception as e:
        logger.warning("Failed to confirm knowledge: %s", e)
        return False


def reject_knowledge(
    knowledge_id: str,
    knowledge_jsonl_path: Path,
    knowledge_indexer: Any,
) -> bool:
    """
    Archive/reject a knowledge record (thumbs down or explicit rejection).
    
    Args:
        knowledge_id: The ID to reject
        knowledge_jsonl_path: Path to knowledge.jsonl file
        knowledge_indexer: KnowledgeIndexer instance
        
    Returns:
        True if archived, False if not found or error
    """
    record = find_knowledge_by_id(knowledge_id, knowledge_jsonl_path, knowledge_indexer)
    if not record:
        logger.warning("Knowledge %s not found", knowledge_id)
        return False
    
    record["status"] = "archived"
    record["ts"] = datetime.now().isoformat()
    
    try:
        with portable_lock(knowledge_jsonl_path):
            with open(knowledge_jsonl_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(record) + "\n")
                f.flush()
        # Phase 5b: update index with archived status
        try:
            knowledge_indexer.upsert_knowledge(record)
        except Exception as idx_err:
            logger.warning("Knowledge index upsert failed (non-fatal): %s", idx_err)
        logger.info("Knowledge archived: %s", knowledge_id)
        return True
    except Exception as e:
        logger.warning("Failed to archive knowledge: %s", e)
        return False



def bulk_confirm_knowledge(
    knowledge_ids: List[str],
    knowledge_jsonl_path: Path,
    knowledge_indexer: Any,
    user_id: str,
) -> Dict[str, List[str]]:
    """
    Bulk confirm multiple pending_review knowledge records.
    
    Args:
        knowledge_ids: List of knowledge IDs to confirm
        knowledge_jsonl_path: Path to knowledge.jsonl file
        knowledge_indexer: KnowledgeIndexer instance
        user_id: User performing the confirmation
        
    Returns:
        {"success": [...ids confirmed], "failed": [...ids that failed]}
    """
    success = []
    failed = []
    for kn_id in knowledge_ids:
        if confirm_knowledge(kn_id, knowledge_jsonl_path, knowledge_indexer, user_id):
            success.append(kn_id)
        else:
            failed.append(kn_id)
    logger.info("Bulk confirm: %d success, %d failed", len(success), len(failed))
    return {"success": success, "failed": failed}


def bulk_reject_knowledge(
    knowledge_ids: List[str],
    knowledge_jsonl_path: Path,
    knowledge_indexer: Any,
) -> Dict[str, List[str]]:
    """
    Bulk reject/archive multiple knowledge records.
    
    Args:
        knowledge_ids: List of knowledge IDs to reject/archive
        knowledge_jsonl_path: Path to knowledge.jsonl file
        knowledge_indexer: KnowledgeIndexer instance
        
    Returns:
        {"success": [...ids archived], "failed": [...ids that failed]}
    """
    success = []
    failed = []
    for kn_id in knowledge_ids:
        if reject_knowledge(kn_id, knowledge_jsonl_path, knowledge_indexer):
            success.append(kn_id)
        else:
            failed.append(kn_id)
    logger.info("Bulk reject: %d success, %d failed", len(success), len(failed))
    return {"success": success, "failed": failed}



def edit_knowledge(
    knowledge_id: str,
    knowledge_jsonl_path: Path,
    knowledge_indexer: Any,
    summary: str = None,
    knowledge_type: str = None,
    applies_when: str = None,
    tags: List[str] = None,
    entity_keys: List[str] = None,
    written_to: str = None,
    suggested_file: str = None,
) -> bool:
    """
    Edit a knowledge record in place, preserving its status and provenance.
    
    Uses JSONL append with same ID (last-write-wins dedup).
    
    Args:
        knowledge_id: The ID to edit
        knowledge_jsonl_path: Path to knowledge.jsonl file
        knowledge_indexer: KnowledgeIndexer instance
        summary: New summary text (None = keep existing)
        knowledge_type: New type (None = keep existing)
        applies_when: New condition (None = keep existing)
        tags: New tags list (None = keep existing)
        entity_keys: New entity references (None = keep existing)
        
    Returns:
        True if updated, False if not found or error
    """
    record = find_knowledge_by_id(knowledge_id, knowledge_jsonl_path, knowledge_indexer)
    if not record:
        logger.warning("Knowledge %s not found", knowledge_id)
        return False
    
    # Update only provided fields
    if summary is not None:
        record["summary"] = summary
    if knowledge_type is not None:
        if knowledge_type in KNOWLEDGE_TYPES:
            record["type"] = knowledge_type
    if applies_when is not None:
        if "scope" not in record:
            record["scope"] = {}
        record["scope"]["applies_when"] = applies_when
    if tags is not None:
        if "scope" not in record:
            record["scope"] = {}
        record["scope"]["tags"] = tags
    if entity_keys is not None:
        record["entity_keys"] = entity_keys[:20]  # Limit to 20 entities
    if written_to is not None:
        record["written_to"] = written_to or None  # empty string → clear it
    if suggested_file is not None:
        if "scope" not in record:
            record["scope"] = {}
        record["scope"]["suggested_file"] = suggested_file or None

    record["ts"] = datetime.now().isoformat()
    
    # Append updated record (last write wins — same ID) — file-locked for concurrency
    try:
        with portable_lock(knowledge_jsonl_path):
            with open(knowledge_jsonl_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(record) + "\n")
                f.flush()
        # Phase 5b: update index with edited content
        try:
            knowledge_indexer.upsert_knowledge(record)
        except Exception as idx_err:
            logger.warning("Knowledge index upsert failed (non-fatal): %s", idx_err)
        logger.info("Knowledge edited: %s (status preserved: %s)", knowledge_id, record.get('status'))
        return True
    except Exception as e:
        logger.warning("Failed to edit knowledge: %s", e)
        return False
