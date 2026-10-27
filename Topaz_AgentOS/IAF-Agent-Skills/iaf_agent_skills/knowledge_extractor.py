#!/usr/bin/env python3
"""
Knowledge Extractor Module - Batch extraction pipeline for learning from episodes.

EXTRACTED FROM memory.py for modularity (Phase 2.2).
This module handles the "Nightly Batch Learner" pipeline:
- Collect recent conversation episodes
- Extract reusable knowledge patterns via LLM
- Deduplicate against existing knowledge
- Write as pending_review for human confirmation

Functions:
    read_extraction_cursor() - Read high-water mark cursor
    write_extraction_cursor() - Update cursor after extraction
    get_extraction_status() - API-friendly cursor data
    collect_recent_episodes() - Gather episodes from history
    get_existing_knowledge_summaries() - Fetch summaries for dedup
    batch_extract_knowledge() - Main orchestration function
    extract_knowledge_from_chunk() - LLM call for a chunk of episodes

Usage:
    # Called by AgentMemory.batch_extract_knowledge() via delegation
    from iaf_agent_skills.knowledge_extractor import batch_extract_knowledge
    
    result = batch_extract_knowledge(
        history_path=memory.history_path,
        extraction_cursor_path=memory.extraction_cursor_path,
        knowledge_jsonl_path=memory.knowledge_jsonl_path,
        knowledge_indexer=memory.knowledge_indexer,
        light_llm=memory.light_llm,
        write_knowledge_fn=memory.write_knowledge,
        knowledge_types=memory.KNOWLEDGE_TYPES,
        hours_back=24,
    )
"""

import json
import logging
from datetime import datetime, timedelta

from pathlib import Path
from typing import Optional, Dict, List, Any, Callable

logger = logging.getLogger(__name__)


def read_extraction_cursor(extraction_cursor_path: Path) -> Optional[Dict]:
    """
    Read the extraction cursor file. Returns dict or None if absent.
    
    The cursor tracks the high-water mark for batch extraction:
    - last_extracted_at: timestamp of last extraction run
    - episodes_processed: count from last run
    - knowledge_extracted: count of new knowledge items
    
    Args:
        extraction_cursor_path: Path to the cursor JSON file
        
    Returns:
        Cursor dict or None if file doesn't exist or is invalid
    """
    try:
        if extraction_cursor_path.exists():
            return json.loads(extraction_cursor_path.read_text(encoding='utf-8'))
    except (json.JSONDecodeError, OSError) as e:
        logger.warning("Failed to read extraction cursor: %s", e)
    return None


def write_extraction_cursor(
    extraction_cursor_path: Path,
    episodes_processed: int,
    knowledge_extracted: int
) -> None:
    """
    Write the extraction cursor with current timestamp and counts.
    
    Args:
        extraction_cursor_path: Path to the cursor JSON file
        episodes_processed: Number of episodes processed in this run
        knowledge_extracted: Number of knowledge items extracted
    """
    cursor = {
        "last_extracted_at": datetime.now().isoformat(),
        "episodes_processed": episodes_processed,
        "knowledge_extracted": knowledge_extracted
    }
    try:
        extraction_cursor_path.write_text(json.dumps(cursor, indent=2))
    except OSError as e:
        logger.warning("Failed to write extraction cursor: %s", e)


def get_extraction_status(extraction_cursor_path: Path) -> Optional[Dict]:
    """
    Return the current extraction cursor data for API consumption.
    
    Args:
        extraction_cursor_path: Path to the cursor JSON file
        
    Returns:
        Cursor dict or None if no cursor exists
    """
    return read_extraction_cursor(extraction_cursor_path)



def collect_recent_episodes(
    history_path: Path,
    cutoff: datetime,
    skill: Optional[str] = None
) -> List[Dict]:
    """
    Collect all episodic log entries after the cutoff timestamp.
    
    Walks the date-organized history directories and collects episodes
    from JSONL files that are newer than the cutoff.
    
    Args:
        history_path: Root path to episode history (date-organized subdirs)
        cutoff: Only include episodes after this datetime
        skill: If provided, only include episodes matching this skill name
        
    Returns:
        List of episode dicts, sorted chronologically
    """
    episodes = []
    
    if not history_path.exists():
        return episodes
    
    # Walk date directories — only check dates >= cutoff date
    cutoff_date_str = cutoff.strftime("%Y-%m-%d")
    
    for date_dir in sorted(history_path.iterdir()):
        if not date_dir.is_dir():
            continue
        # Skip date folders older than cutoff
        if date_dir.name < cutoff_date_str:
            continue
        
        for jsonl_file in date_dir.glob("*.jsonl"):
            try:
                with open(jsonl_file, "r", encoding="utf-8") as f:
                    for line in f:
                        if not line.strip():
                            continue
                        entry = json.loads(line)
                        ts_str = entry.get("timestamp", "")
                        try:
                            ts = datetime.fromisoformat(ts_str)
                            if ts >= cutoff:
                                if skill and entry.get("skill", "").lower() != skill.lower():
                                    continue
                                episodes.append(entry)
                        except (ValueError, TypeError):
                            # Can't parse timestamp, include it anyway
                            if skill and entry.get("skill", "").lower() != skill.lower():
                                continue
                            episodes.append(entry)
            except Exception as e:
                logger.warning("Error reading %s: %s", jsonl_file, e)
    
    episodes.sort(key=lambda x: x.get("timestamp", ""))
    return episodes



def get_existing_knowledge_summaries(
    knowledge_indexer,
    knowledge_jsonl_path: Path
) -> List[str]:
    """
    Get summaries of all confirmed + pending knowledge for dedup.
    
    Tries SQLite indexer first (fast), falls back to JSONL scan.
    
    Args:
        knowledge_indexer: KnowledgeIndexer instance for SQLite queries
        knowledge_jsonl_path: Path to knowledge JSONL file
        
    Returns:
        List of summary strings from confirmed/pending_review records
    """
    try:
        result = knowledge_indexer.get_summaries_by_status(
            ["confirmed", "pending_review"]
        )
        if result:
            return result
    except Exception as e:
        logger.debug("SQLite summaries query failed, falling back to JSONL: %s", e)
    
    return get_existing_knowledge_summaries_jsonl(knowledge_jsonl_path)


def get_existing_knowledge_summaries_jsonl(knowledge_jsonl_path: Path) -> List[str]:
    """
    JSONL fallback for get_existing_knowledge_summaries.
    
    Reads all records, deduplicates by ID, returns summaries for
    confirmed/pending_review status.
    
    Args:
        knowledge_jsonl_path: Path to knowledge JSONL file
        
    Returns:
        List of summary strings
    """
    summaries = []
    if not knowledge_jsonl_path.exists():
        return summaries
    
    records_by_id = {}
    try:
        with open(knowledge_jsonl_path, "r", encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    record = json.loads(line)
                    records_by_id[record.get("id", "")] = record
    except Exception:
        return summaries
    
    for record in records_by_id.values():
        status = record.get("status", "")
        if status in ("confirmed", "pending_review"):
            summaries.append(record.get("summary", ""))
    
    return summaries



def extract_knowledge_from_chunk(
    episodes: List[Dict],
    existing_summaries: List[str],
    light_llm,
    knowledge_types: set,
    entity_guide_text: str = "",
) -> List[Dict]:
    """
    Call LLM to extract reusable knowledge from a chunk of episodes.
    Uses self-critique for higher extraction accuracy.
    
    Args:
        episodes: List of episode dicts to analyze
        existing_summaries: Existing knowledge summaries (for dedup)
        light_llm: LLM instance with invoke() method
        knowledge_types: Valid knowledge type values
        
    Returns:
        List of extracted knowledge dicts:
        {type, summary, tags, applies_when, skill, entity_keys,
         user_query, recommended_tools}
    """
    from langchain_core.messages import HumanMessage
    
    # Build entity guide section — use provided guide or fall back to minimal hint
    entity_guide_section = (
        entity_guide_text
        if entity_guide_text
        else "Entity types: vendor, customer, invoice, order, person, process, policy, metric, service, system, report, task"
    )

    # Build dedup context (show max 50 existing summaries)
    dedup_section = ""
    if existing_summaries:
        sample = existing_summaries[:50]
        dedup_section = (
            "\n## EXISTING KNOWLEDGE (do NOT duplicate these):\n"
            + "\n".join(f"- {s}" for s in sample if s)
            + "\n"
        )
    
    prompt = f"""You are a knowledge extraction engine for an enterprise operations agent.

## TASK
Analyze the recent conversation episodes below and extract REUSABLE knowledge patterns.
Only extract knowledge that would be useful for handling FUTURE similar situations.

## WHAT TO EXTRACT
- Business rules discovered during conversations
- Exception handling patterns (what went wrong, what fixed it)
- Workarounds that were applied
- Corrections (agent was wrong, user corrected)
- Preferences (user prefers certain approaches)
- Facts about specific entities (vendors, processes, systems)
- Patterns in how certain types of queries should be handled
- Skill patterns: which skills/tools work best for which question types
- Workflow traces: multi-step resolutions showing cause → action → outcome

## WHAT TO SKIP
- One-off queries with no reusable pattern
- Greetings, small talk, status checks
- Anything already captured in existing knowledge

## ENTITY EXTRACTION
For each knowledge item, identify all real-world entities mentioned.
Format as "type:id" strings.
Examples: "vendor:Alpha Office Supplies", "invoice:INV-050", "order:PO-2026-0042"
These entity_keys will be used to link knowledge to ERP database records.
Use the canonical entity name from the episode (e.g., include vendor IDs if present).
{entity_guide_section}

## TOOL ATTRIBUTION
If the episode shows specific tools that successfully resolved the task,
capture them in recommended_tools. This helps future queries route to
the right tools immediately. Only include tools that produced useful results.
{dedup_section}
## EPISODES ({len(episodes)} conversations):
{json.dumps(episodes, indent=1)}

## EXTRACTION PROCESS (follow these steps internally)

**Step 1 — Extract:** Identify all candidate knowledge items from the episodes above.

**Step 2 — Self-Critique:** Before returning, review each candidate and ask:
  1. Is this truly reusable for future queries, or is it a one-off observation?
  2. Is the summary precise and actionable, or vague and generic?
  3. Are the entity_keys correctly typed (vendor vs customer vs service)?
     - Would these entity_keys match actual ERP database records?
     - Are there entity references I missed?
  4. Does applies_when describe a specific, recognizable trigger condition?
  5. Is this a duplicate or near-duplicate of existing knowledge listed above?
  6. Is the user_query accurately captured from the episode's user_input?
  7. Did I attribute the right tools — the ones that actually produced results?

**Step 3 — Refine:** Drop any items that fail the critique. Sharpen summaries
that are too vague. Fix any entity_keys that use wrong types. Merge items
that are saying the same thing differently.

## OUTPUT FORMAT
Return ONLY the final refined JSON array (after self-critique). Each item:
{{
  "type": "rule|exception|preference|workaround|pattern|correction|fact|skill_pattern|workflow_trace",
  "summary": "Clear, actionable statement of the knowledge",
  "tags": ["tag1", "tag2"],
  "applies_when": "Specific trigger condition for this knowledge",
  "skill": "skill_name or null if global",
  "entity_keys": ["type:id", "type:id"],
  "user_query": "The original user question that produced this insight",
  "recommended_tools": ["tool_name1", "tool_name2"]
}}

If no reusable knowledge survives the critique, return an empty array: []

IMPORTANT: Return ONLY the JSON array, no markdown fencing, no explanation.
Do NOT include your critique reasoning in the output — only the refined results."""

    messages = [HumanMessage(content=prompt)]
    response = light_llm.invoke(messages)
    
    raw = response.content if hasattr(response, 'content') else str(response)
    raw = raw.strip()
    
    # Strip markdown code fencing if present
    if raw.startswith("```"):
        # Remove first line and last line
        lines = raw.split("\n")
        if lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        raw = "\n".join(lines)
    
    try:
        extracted = json.loads(raw)
        if not isinstance(extracted, list):
            extracted = [extracted]
        
        valid = []
        for item in extracted:
            if isinstance(item, dict) and item.get("summary"):
                # Ensure type is valid
                if item.get("type") not in knowledge_types:
                    item["type"] = "pattern"
                valid.append(item)
        
        logger.info("LLM extracted %d knowledge items from %d episodes", len(valid), len(episodes))
        return valid
        
    except json.JSONDecodeError as e:
        logger.warning("Failed to parse LLM response as JSON: %s", e)
        logger.debug("Raw response: %s", raw[:200])
        return []



def extract_temporal_changes_from_chunk(
    episodes: List[Dict],
    existing_summaries: List[str],
    light_llm,
    entity_guide_text: str = "",
) -> List[Dict]:
    """
    Call LLM to detect state changes and fact supersessions from a chunk of episodes.

    This is the "Timeline Tracker" pass — a second parallel LLM call that runs on
    the same episodes as extract_knowledge_from_chunk() but with a different goal:
    find cases where something that was true BEFORE is now different.

    Returns items with an extra `supersedes_summary` field — the old statement that
    this change replaces. This allows the agent to understand "a change happened"
    rather than just seeing two disconnected facts.

    Args:
        episodes: Same stripped episode list as the main extraction call
        existing_summaries: Existing knowledge summaries for dedup
        light_llm: LLM instance
        entity_guide_text: Optional entity type guide

    Returns:
        List of change dicts:
        {type, summary, supersedes_summary, tags, applies_when, skill, entity_keys, user_query}
    """
    from langchain_core.messages import HumanMessage

    entity_guide_section = (
        entity_guide_text
        if entity_guide_text
        else "Entity types: vendor, customer, invoice, order, person, process, policy, metric, service, system, report, task"
    )

    dedup_section = ""
    if existing_summaries:
        sample = existing_summaries[:50]
        dedup_section = (
            "\n## EXISTING KNOWLEDGE (to detect supersessions against):\n"
            + "\n".join(f"- {s}" for s in sample if s)
            + "\n"
        )

    prompt = f"""You are a temporal change detector for an enterprise operations agent.

## TASK
Analyze the conversation episodes below and identify ONLY cases where a fact or state
has CHANGED — where something that was true before is now different.

## WHAT TO DETECT
- Payment terms changed (e.g. Net-60 → Net-30)
- Vendor status changed (e.g. active → blocked, or flagged → cleared)
- A policy or rule was updated or reversed
- A previous correction was itself corrected (chain of updates)
- A preference changed (user now wants X instead of Y)
- Any entity attribute that was one value and is now a different value

## WHAT TO SKIP
- New facts with no prior state (no change, just first mention)
- Routine Q&A with no state transition
- Anything where you cannot identify both the OLD state and the NEW state

## ENTITY EXTRACTION
{entity_guide_section}

## EXISTING KNOWLEDGE (use to identify the old state being superseded):
{dedup_section}

## EPISODES ({len(episodes)} conversations):
{json.dumps(episodes, indent=1)}

## OUTPUT FORMAT
Return ONLY a JSON array. Each item MUST have both old and new state.
If no state changes are found, return [].

Each item:
{{
  "type": "correction",
  "summary": "Clear statement of the NEW state (e.g. FastShip payment terms are now Net-30)",
  "supersedes_summary": "The OLD statement being replaced (e.g. FastShip payment terms are Net-60)",
  "tags": ["state_change", "timeline", "relevant_attribute"],
  "applies_when": "When this new state is relevant",
  "skill": "skill_name or null",
  "entity_keys": ["type:id"],
  "user_query": "The user query that revealed this change"
}}

IMPORTANT: Return ONLY the JSON array, no markdown fencing, no explanation.
Only include items where you can clearly identify BOTH the old value AND the new value."""

    messages = [HumanMessage(content=prompt)]
    try:
        response = light_llm.invoke(messages)
    except Exception as e:
        logger.warning("Timeline tracker LLM call failed: %s", e)
        return []

    raw = response.content if hasattr(response, "content") else str(response)
    raw = raw.strip()

    if raw.startswith("```"):
        lines = raw.split("\n")
        if lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        raw = "\n".join(lines)

    try:
        extracted = json.loads(raw)
        if not isinstance(extracted, list):
            extracted = [extracted]

        valid = []
        for item in extracted:
            if (isinstance(item, dict)
                    and item.get("summary")
                    and item.get("supersedes_summary")):
                item["type"] = "correction"  # always correction type
                item.setdefault("tags", [])
                if "state_change" not in item["tags"]:
                    item["tags"].append("state_change")
                if "timeline" not in item["tags"]:
                    item["tags"].append("timeline")
                valid.append(item)

        logger.info("Timeline tracker: %d state changes from %d episodes", len(valid), len(episodes))
        return valid

    except json.JSONDecodeError as e:
        logger.warning("Timeline tracker: failed to parse LLM response: %s", e)
        return []



def batch_extract_knowledge(
    history_path: Path,
    extraction_cursor_path: Path,
    knowledge_jsonl_path: Path,
    knowledge_indexer,
    light_llm,
    write_knowledge_fn: Callable,
    knowledge_types: set,
    hours_back: int = 24,
    max_tokens_budget: int = 150_000,
    skill: Optional[str] = None,
    force_full: bool = False,
    entity_guide_path: Optional[Path] = None,
) -> Dict:
    """
    Mine recent episodic conversation logs for reusable knowledge patterns.
    
    Philosophy: We don't decide what's valuable — the LLM proposes,
    the human confirms. All extracted knowledge is pending_review.
    
    Approach:
    1. Collect all episodes from the last N hours
    2. Strip to essential fields (user_input, response_summary, skill, 
       tool_calls, learning_signals) to stay within token budget
    3. Load existing confirmed knowledge for dedup context
    4. Single LLM call: "Here are recent episodes + existing knowledge.
       Extract new reusable knowledge. Return JSON array."
    5. Write each as pending_review with source=nightly_batch
    
    If total episode text exceeds max_tokens_budget, chunk by time
    windows and make multiple LLM calls.
    
    Args:
        history_path: Path to episode history directory
        extraction_cursor_path: Path to cursor file
        knowledge_jsonl_path: Path to knowledge JSONL
        knowledge_indexer: KnowledgeIndexer for summary queries
        light_llm: LLM instance for extraction
        write_knowledge_fn: Callable to write knowledge records
        knowledge_types: Set of valid knowledge type values
        hours_back: How far back to look (default 24h)
        max_tokens_budget: Approximate token budget for episodes
        skill: Optional skill filter
        force_full: If True, ignore cursor and extract from full window
        
    Returns:
        Dict with extracted count, skipped count, errors
    """
    result = {
        "status": "ok",
        "episodes_found": 0,
        "knowledge_extracted": 0,
        "knowledge_ids": [],
        "chunks_processed": 0,
        "errors": []
    }
    
    if not light_llm:
        result["status"] = "error"
        result["errors"].append("No LLM configured for batch extraction")
        return result
    
    window_cutoff = datetime.now() - timedelta(hours=hours_back)
    cursor = read_extraction_cursor(extraction_cursor_path) if not force_full else None
    if cursor and cursor.get("last_extracted_at"):
        try:
            cursor_ts = datetime.fromisoformat(cursor["last_extracted_at"])
            # Use the more recent of cursor vs window_cutoff
            if cursor_ts > window_cutoff:
                cutoff = cursor_ts
                logger.info("Using extraction cursor: %s (skipping already-extracted window)",
                            cursor_ts.isoformat())
            else:
                cutoff = window_cutoff
        except (ValueError, TypeError):
            cutoff = window_cutoff
    else:
        cutoff = window_cutoff
    
    episodes = collect_recent_episodes(history_path, cutoff, skill=skill)
    result["episodes_found"] = len(episodes)
    
    if not episodes:
        result["status"] = "no_episodes"
        return result
    
    logger.info("Batch extract: %d episodes from last %dh", len(episodes), hours_back)
    
    stripped = []
    for ep in episodes:
        tool_calls_raw = ep.get("tool_calls") or []
        # Normalize: some episodes store tool_calls as strings, not dicts
        tool_calls_norm = [
            tc if isinstance(tc, dict) else {"tool": str(tc)}
            for tc in (tool_calls_raw if isinstance(tool_calls_raw, list) else [])
        ]
        stripped.append({
            "user_input": (ep.get("user_input") or "")[:200],
            "response": (ep.get("response_summary_llm") 
                        or ep.get("response_summary") or "")[:300],
            "skill": ep.get("skill", "unknown"),
            "tool_calls": tool_calls_norm[:3],
            "learning_signals": ep.get("learning_signals"),
            # Enriched fields for entity/tool extraction
            "routing": ep.get("routing", {}),
            "outcome": ep.get("outcome", ep.get("status", "")),
            "tool_details": [
                {"tool": tc.get("tool", ""), "result_preview": str(tc.get("result", ""))[:100]}
                for tc in tool_calls_norm[:3]
            ],
            "session_id": ep.get("session_id", ""),
            "timestamp": ep.get("timestamp", ""),
        })
    
    for i in range(len(stripped) - 1):
        if (stripped[i].get("session_id") 
            and stripped[i]["session_id"] == stripped[i+1].get("session_id")):
            try:
                ts_a = stripped[i].get("timestamp", "")
                ts_b = stripped[i+1].get("timestamp", "")
                if ts_a and ts_b:
                    dt_a = datetime.fromisoformat(ts_a)
                    dt_b = datetime.fromisoformat(ts_b)
                    if (dt_b - dt_a).total_seconds() <= 300:  # 5 minutes
                        stripped[i]["user_followup"] = (stripped[i+1].get("user_input") or "")[:150]
            except (ValueError, TypeError):
                pass  # Can't parse timestamps, skip pairing
    
    existing_summaries = get_existing_knowledge_summaries(knowledge_indexer, knowledge_jsonl_path)
    
    # ── Step 4: Chunk if needed, then call LLM ─────────────────────
    # Rough estimate: ~4 chars per token
    episodes_text = json.dumps(stripped, indent=1)
    estimated_tokens = len(episodes_text) // 4
    
    if estimated_tokens <= max_tokens_budget:
        # Single chunk — all fits
        chunks = [stripped]
    else:
        chunk_size = max(1, len(stripped) * max_tokens_budget // estimated_tokens)
        chunks = [stripped[i:i+chunk_size] 
                  for i in range(0, len(stripped), chunk_size)]
        logger.info("Episodes exceed budget (%d~tokens), split into %d chunks of ~%d",
                    estimated_tokens, len(chunks), chunk_size)
    
    # Load entity guide once (shared across all chunks)
    _entity_guide_text = ""
    if entity_guide_path:
        try:
            _entity_guide_text = Path(entity_guide_path).read_text(encoding="utf-8").strip()
        except Exception as eg_err:
            logger.warning("entity_guide load failed (non-fatal): %s", eg_err)

    for chunk_idx, chunk in enumerate(chunks):
        try:
            extracted = extract_knowledge_from_chunk(
                chunk, existing_summaries, light_llm, knowledge_types,
                entity_guide_text=_entity_guide_text,
            )
            result["chunks_processed"] += 1

            for item in extracted:
                kid = write_knowledge_fn(
                    knowledge_type=item.get("type", "pattern"),
                    summary=item.get("summary", ""),
                    tags=item.get("tags", []),
                    applies_when=item.get("applies_when", ""),
                    source="nightly_batch",
                    status="pending_review",
                    skill=item.get("skill"),
                    episode_id=None,
                    entity_keys=item.get("entity_keys", []),
                    user_query=item.get("user_query", ""),
                    recommended_tools=item.get("recommended_tools", []),
                    source_context_file=item.get("source_context_file"),
                )
                result["knowledge_ids"].append(kid)
                result["knowledge_extracted"] += 1
                existing_summaries.append(item.get("summary", ""))

        except Exception as e:
            err_msg = f"Chunk {chunk_idx} (Call A): {e}"
            logger.warning("Batch extract error: %s", err_msg)
            result["errors"].append(err_msg)

        try:
            temporal_changes = extract_temporal_changes_from_chunk(
                chunk, existing_summaries, light_llm,
                entity_guide_text=_entity_guide_text,
            )

            for item in temporal_changes:
                supersedes = item.get("supersedes_summary", "")
                tags = item.get("tags", [])

                kid = write_knowledge_fn(
                    knowledge_type="correction",
                    summary=item.get("summary", ""),
                    tags=tags,
                    applies_when=item.get("applies_when", ""),
                    source="nightly_batch",
                    status="pending_review",
                    skill=item.get("skill"),
                    episode_id=None,
                    entity_keys=item.get("entity_keys", []),
                    user_query=item.get("user_query", ""),
                    recommended_tools=[],
                    supersedes_summary=supersedes,
                    source_context_file=item.get("source_context_file"),
                )
                result["knowledge_ids"].append(kid)
                result["knowledge_extracted"] += 1
                existing_summaries.append(item.get("summary", ""))
                logger.info(
                    "Timeline tracker wrote state change: %s (supersedes: %s)",
                    item.get("summary", "")[:60],
                    supersedes[:60] if supersedes else "—",
                )

        except Exception as e:
            err_msg = f"Chunk {chunk_idx} (Call B timeline): {e}"
            logger.warning("Timeline tracker error: %s", err_msg)
            result["errors"].append(err_msg)
    
    write_extraction_cursor(
        extraction_cursor_path,
        episodes_processed=result["episodes_found"],
        knowledge_extracted=result["knowledge_extracted"]
    )
    
    logger.info("Batch extract complete: %d new knowledge from %d episodes",
                 result['knowledge_extracted'], result['episodes_found'])
    
    return result
