#!/usr/bin/env python3
"""
Memory Search Module - Grep-based context graph retrieval and agentic search.

EXTRACTED FROM memory.py for modularity (Phase 2.3).
This module handles memory search, context retrieval, and keyword expansion:
- Fast alias expansion for abbreviations
- Grep-based knowledge search (FTS5 + JSONL fallback)
- Format context for LLM prompt injection
- Agentic episode search with relevance scoring
- Combined LLM-based query analysis

Functions:
    expand_search_terms_fast() - Fast alias expansion (no LLM)
    grep_context_graph() - Search confirmed knowledge
    grep_context_graph_jsonl() - JSONL fallback for grep
    format_context_for_prompt() - Format for prompt injection
    extract_topics_entities() - LLM-based topic/entity extraction
    truncate_snippet() - Truncate text around keyword match
    grep_jsonl_files() - Shared grep helper with scoring
    get_search_keywords() - Get keywords with optional expansion
    search_episodes_agentic() - Agentic grep search
    extract_search_keywords() - Direct keyword extraction
    analyze_query_for_memory() - Combined LLM analysis
    get_files_to_search() - Get files for search scope

Usage:
    # Called by AgentMemory methods via delegation
    from iaf_agent_skills.memory_search import grep_context_graph
    
    results = grep_context_graph(
        keywords=["invoice", "approval"],
        knowledge_indexer=memory.knowledge_indexer,
        knowledge_jsonl_path=memory.knowledge_jsonl_path,
    )
"""

import json
import logging
import re
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, Dict, List, Any, Callable

logger = logging.getLogger(__name__)


# Stopwords for keyword filtering
STOPWORDS = {
    'what', 'is', 'the', 'a', 'an', 'how', 'can', 'you', 'me', 'my',
    'about', 'for', 'to', 'of', 'and', 'or', 'in', 'on', 'at', 'show',
    'tell', 'give', 'find', 'get', 'list', 'with', 'was', 'were', 'been',
    'are', 'this', 'that', 'there', 'here', 'have', 'has', 'had', 'do',
    'does', 'did', 'will', 'would', 'could', 'should', 'may', 'might',
    'must', 'shall', 'please', 'help', 'need', 'want', 'like', 'just',
    'also', 'only', 'from', 'into', 'over', 'after', 'before', 'between',
    'under', 'again', 'further', 'then', 'once', 'all', 'any', 'both',
    'each', 'few', 'more', 'most', 'other', 'some', 'such', 'no', 'not'
}


def extract_search_keywords(query: str) -> List[str]:
    """
    Extract meaningful keywords from query for grep search.
    
    Removes stopwords and short words to focus on searchable terms.
    
    Args:
        query: User's search query
        
    Returns:
        List of filtered keywords
    """
    # Split on spaces and common punctuation
    words = re.split(r'[\s,;:!?\'"]+', query.lower())
    
    # Filter: remove stopwords and short words, keep meaningful terms
    keywords = [w for w in words if w and w not in STOPWORDS and len(w) > 2]
    
    return keywords


def expand_search_terms_fast(
    query: str,
    aliases_jsonl_path: Path
) -> List[str]:
    """
    Fast alias expansion - NO LLM call.
    
    Only uses stored aliases.jsonl for known abbreviations.
    Let the ReAct loop handle unknown abbreviations naturally.
    
    Args:
        query: The user's query
        aliases_jsonl_path: Path to aliases.jsonl file
        
    Returns:
        List of search terms including original + alias expansions
    """
    # Start with direct keywords from query
    terms = set()
    words = re.findall(r'\b\w{3,}\b', query.lower())
    terms.update(words)
    
    if aliases_jsonl_path.exists():
        try:
            with open(aliases_jsonl_path, "r", encoding="utf-8") as f:
                for line in f:
                    if line.strip():
                        alias = json.loads(line)
                        short = alias.get("short", "").lower()
                        full = alias.get("full", "").lower()
                        # If query mentions either short or full, add both
                        if short in query.lower() or full in query.lower():
                            terms.add(short)
                            terms.add(full)
                            # Also add full name words
                            terms.update(re.findall(r'\b\w{3,}\b', full))
        except Exception as e:
            logger.warning("Alias lookup failed: %s", e)
    
    result = list(terms)[:15]  # Limit to 15 terms
    logger.debug("Search terms (fast): %s", result)
    return result



def grep_context_graph(
    keywords: List[str],
    knowledge_indexer,
    knowledge_jsonl_path: Path,
    max_results: int = 50
) -> List[Dict]:
    """
    Search knowledge records matching keywords.
    
    Only searches CONFIRMED knowledge (status filter).
    Tries FTS5 via SQLite first, falls back to JSONL regex scan.
    
    Args:
        keywords: List of search terms
        knowledge_indexer: KnowledgeIndexer for FTS5 search
        knowledge_jsonl_path: Path to knowledge JSONL
        max_results: Maximum matching lines to return
        
    Returns:
        List of parsed knowledge records (deduplicated by ID)
    """
    if not keywords:
        return []
    
    # Try FTS5 via knowledge_indexer (indexed, O(log n))
    try:
        query_str = " ".join(k for k in keywords if k.strip())
        if query_str:
            fts_results = knowledge_indexer._search_by_fts(
                query_str, top_k=max_results, status="confirmed",
                skill=None, knowledge_type=None,
            )
            if fts_results:
                for r in fts_results:
                    r["_source"] = "knowledge"
                logger.info("FTS5 grep found %d matches", len(fts_results))
                return fts_results
    except Exception as e:
        logger.debug("FTS5 search failed, falling back to JSONL grep: %s", e)
    
    return grep_context_graph_jsonl(keywords, knowledge_jsonl_path, max_results)


def grep_context_graph_jsonl(
    keywords: List[str],
    knowledge_jsonl_path: Path,
    max_results: int = 50
) -> List[Dict]:
    """JSONL fallback for grep_context_graph."""
    escaped = [re.escape(k.lower()) for k in keywords if k.strip()]
    if not escaped:
        return []
    pattern = re.compile("|".join(escaped), re.IGNORECASE)
    
    results_by_id = {}
    files_to_search = [
        ("knowledge", knowledge_jsonl_path),
    ]
    
    for source_name, file_path in files_to_search:
        if not file_path.exists():
            continue
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                for line in f:
                    if line.strip() and pattern.search(line):
                        try:
                            record = json.loads(line)
                            record["_source"] = source_name
                            rid = record.get("id", id(record))
                            results_by_id[rid] = record
                        except json.JSONDecodeError:
                            continue
        except Exception as e:
            logger.warning("Grep failed for %s: %s", source_name, e)
    
    results = []
    for record in results_by_id.values():
        status = record.get("status")
        if status and status in ("archived", "pending_review"):
            continue
        results.append(record)
        if len(results) >= max_results:
            break
    
    logger.info("Grep found %d matches", len(results))
    return results


def dedupe_by_latest_timestamp(
    records: List[Dict],
    text_similarity_threshold: float = 0.85
) -> List[Dict]:
    """
    Remove older duplicate records, keeping only the newest version.
    
    Two records are considered duplicates if their summaries are highly similar.
    Uses SequenceMatcher for text similarity (no embeddings needed).
    
    This prevents stale/superseded facts from being injected into prompts
    when a newer version of the same fact exists.
    
    Args:
        records: List of knowledge records (must have 'summary' and 'ts' fields)
        text_similarity_threshold: Minimum similarity to consider duplicate (0-1).
            Default 0.85 catches "Net 60" vs "Net 70" for same entity.
        
    Returns:
        Deduplicated list with only newest versions per semantic group
    """
    if len(records) <= 1:
        return records
    
    from difflib import SequenceMatcher
    
    # Sort by timestamp descending (newest first)
    sorted_records = sorted(
        records,
        key=lambda r: r.get("ts", r.get("timestamp", "")),
        reverse=True
    )
    
    kept = []
    for record in sorted_records:
        summary = record.get("summary", "")
        if not summary:
            kept.append(record)
            continue
        
        # Check if similar to any already-kept record (newer ones)
        is_duplicate = False
        for kept_record in kept:
            kept_summary = kept_record.get("summary", "")
            if not kept_summary:
                continue
            
            # Text similarity check
            similarity = SequenceMatcher(None, summary.lower(), kept_summary.lower()).ratio()
            if similarity > text_similarity_threshold:
                # This older record is superseded by a newer similar one
                logger.debug(
                    "Deduping: '%s' (older) superseded by '%s' (sim=%.2f)",
                    summary[:40], kept_summary[:40], similarity
                )
                is_duplicate = True
                break
        
        if not is_duplicate:
            kept.append(record)
    
    if len(kept) < len(records):
        logger.info("Deduped %d → %d records (kept newest per group)", len(records), len(kept))
    
    return kept


def format_context_for_prompt(
    grep_results: List[Dict],
    max_chars: int = 2000,
    dedupe: bool = True
) -> str:
    """
    Format knowledge records into concise text for LLM prompt injection.
    
    Only injects confirmed knowledge with applies_when context.
    Automatically deduplicates similar records, keeping only the newest version.
    
    Args:
        grep_results: Records from grep_context_graph() or search_similar()
        max_chars: Maximum output length
        dedupe: If True, deduplicate similar records keeping newest (default: True)
        
    Returns:
        Formatted string for prompt injection
    """
    if not grep_results:
        return ""
    
    knowledge = [r for r in grep_results if r.get("_source") == "knowledge"]
    
    # Deduplicate: keep only newest version of similar records
    if dedupe and knowledge:
        knowledge = dedupe_by_latest_timestamp(knowledge)
    
    lines = ["## Relevant Knowledge:"]
    
    if knowledge:
        # Group by type for readability
        by_type = {}
        for k in knowledge:
            ktype = k.get("type", "info")
            if ktype not in by_type:
                by_type[ktype] = []
            by_type[ktype].append(k)
        
        for ktype, items in by_type.items():
            for k in items[:3]:  # Max 3 per type
                summary = k.get("summary", "")[:120]
                applies_when = k.get("scope", {}).get("applies_when", "")
                if applies_when:
                    lines.append(f"- [{ktype}] {summary}")
                    lines.append(f"  ↳ Applies when: {applies_when[:80]}")
                else:
                    lines.append(f"- [{ktype}] {summary}")
    
    result = "\n".join(lines)
    if len(result) > max_chars:
        result = result[:max_chars] + "\n...[truncated]"
    
    return result



def extract_topics_entities(
    user_input: str,
    response: str,
    skill: str,
    llm=None
) -> Dict[str, List[str]]:
    """
    Extract topics and entities from conversation for indexing.
    Uses LLM for intelligent extraction, falls back to simple parsing.
    
    Args:
        user_input: User's query
        response: Agent's response
        skill: Skill used
        llm: Optional LLM for extraction
        
    Returns:
        {"topics": [...], "entities": [...]}
    """
    if llm:
        try:
            prompt = f"""Extract key topics and entities from this conversation for memory indexing.

User Query: {user_input}
Skill Used: {skill}
Response Summary: {response[:300]}

Return JSON with exactly this format (3-5 items each, lowercase):
{{"topics": ["topic1", "topic2"], "entities": ["entity1", "entity2"]}}

Topics = What the conversation is about (e.g., "AR", "aging report", "invoice")
Entities = Specific things mentioned (e.g., "customer_abc", "inv_12345", "ar_receivables.db")

JSON only, no explanation:"""
            
            _ms_resp = llm.invoke(prompt)
            try:
                import llm_tracker as _lt
                _lt.record("memory_search", _ms_resp, 0.0, getattr(llm, 'azure_deployment', getattr(llm, 'model_name', '')))
            except Exception:
                pass
            result = _ms_resp.content.strip()
            # Parse JSON from response
            if "{" in result:
                json_str = result[result.find("{"):result.rfind("}")+1]
                extracted = json.loads(json_str)
                return {
                    "topics": [t.lower().strip() for t in extracted.get("topics", [])[:5]],
                    "entities": [e.lower().strip() for e in extracted.get("entities", [])[:5]]
                }
        except Exception as e:
            logger.warning("Topic extraction failed: %s", e)
    
    # Fallback: Simple word extraction
    words = (user_input + " " + skill).lower().split()
    topics = [w for w in words if len(w) > 3 and w.isalpha()][:3]
    return {"topics": topics, "entities": []}



def truncate_snippet(
    text: str,
    keywords: List[str],
    max_chars: int = 300
) -> tuple:
    """
    Truncate text centered on keyword match.
    
    Args:
        text: Full text to truncate
        keywords: Keywords to center the snippet around
        max_chars: Maximum characters in snippet
        
    Returns:
        tuple: (snippet, was_truncated, matched_keyword)
    """
    if not text or len(text) <= max_chars:
        return text, False, None
    
    # Find first keyword match position
    text_lower = text.lower()
    match_pos = -1
    matched_keyword = None
    
    for kw in keywords:
        pos = text_lower.find(kw.lower())
        if pos != -1:
            if match_pos == -1 or pos < match_pos:
                match_pos = pos
                matched_keyword = kw
    
    if match_pos == -1:
        # No keyword found, truncate from start
        return text[:max_chars] + "...", True, None
    
    # Center window around matched keyword
    half_window = max_chars // 2
    start = max(0, match_pos - half_window)
    end = min(len(text), match_pos + half_window)
    
    snippet = ""
    if start > 0:
        snippet += "..."
    snippet += text[start:end]
    if end < len(text):
        snippet += "..."
    
    return snippet, True, matched_keyword


def grep_jsonl_files(
    keywords: List[str],
    files: List[Path],
    compute_relevance_fn: Callable,
    history_path: Path,
    max_results: int = 10,
    type_filter: str = None,
    original_keywords: List[str] = None,
    expanded_keywords: List[str] = None,
    truncate_snippets: bool = True,
    max_snippet_chars: int = 300
) -> List[Dict]:
    """
    Shared grep helper - used by both episodes and learnings search.
    
    Args:
        keywords: List of lowercase keywords to search for
        files: List of JSONL files to search
        compute_relevance_fn: Function to compute relevance score
        history_path: Path to history directory (for pointer generation)
        max_results: Maximum results (early exit when reached)
        type_filter: Optional filter by 'feedback_type' field
        original_keywords: Keywords from user's actual query (weighted higher)
        expanded_keywords: LLM-expanded keywords (weighted lower)
        truncate_snippets: If True, truncate long responses
        max_snippet_chars: Maximum chars for truncated snippets
        
    Returns:
        List of matching entries with metadata, relevance scores, and pointers
    """
    results = []
    
    # Default: all keywords are original if not specified
    if original_keywords is None:
        original_keywords = keywords
    if expanded_keywords is None:
        expanded_keywords = []
    
    original_kws_lower = [k.lower() for k in original_keywords]
    expanded_kws_lower = [k.lower() for k in expanded_keywords]
    
    for jsonl_file in files:
        try:
            with open(jsonl_file, encoding="utf-8") as f:
                for line_num, line in enumerate(f, 1):
                    line_lower = line.lower()
                    
                    matched_kws = [kw for kw in keywords if kw.lower() in line_lower]
                    
                    if matched_kws:
                        try:
                            entry = json.loads(line)
                            
                            # Apply type filter if specified
                            if type_filter and entry.get("feedback_type") != type_filter:
                                continue
                            
                            # Separate original vs expanded matches
                            matched_original = [k for k in matched_kws if k.lower() in original_kws_lower]
                            matched_expanded = [k for k in matched_kws if k.lower() in expanded_kws_lower]
                            
                            # Check if match in query field (user_input)
                            user_input = entry.get("user_input", "").lower()
                            matched_in_query = any(kw.lower() in user_input for kw in matched_kws)
                            
                            entry_timestamp = entry.get("timestamp") or entry.get("created_at")
                            
                            relevance_score = compute_relevance_fn(
                                matched_original=matched_original,
                                matched_expanded=matched_expanded,
                                total_original=len(original_keywords),
                                total_expanded=len(expanded_keywords),
                                entry_timestamp=entry_timestamp,
                                match_type="keyword",
                                matched_in_query=matched_in_query
                            )
                            
                            entry["_source_file"] = str(jsonl_file)
                            entry["_line_num"] = line_num
                            entry["_matched_keywords"] = matched_kws
                            entry["_matched_original"] = matched_original
                            entry["_matched_expanded"] = matched_expanded
                            entry["_matched_in_query"] = matched_in_query
                            entry["_relevance_score"] = relevance_score
                            entry["_search_method"] = "agentic_grep"
                            entry["_is_primary_match"] = True
                            
                            # Snippet truncation + pointer
                            if truncate_snippets:
                                response_text = entry.get("response", "")
                                if response_text:
                                    original_len = len(response_text)
                                    snippet, was_truncated, matched_kw = truncate_snippet(
                                        response_text, matched_kws, max_snippet_chars
                                    )
                                    if was_truncated:
                                        entry["response"] = snippet
                                        entry["_truncated"] = True
                                        # Pointer for agent drill-down
                                        try:
                                            rel_path = jsonl_file.relative_to(history_path.parent)
                                            virtual_path = f"/memory/{rel_path}"
                                        except (ValueError, AttributeError):
                                            virtual_path = f"/memory/history/{jsonl_file.name}"
                                        entry["_pointer"] = f"{virtual_path}:{line_num}"
                                        # Grep hint for agent
                                        hint_kw = matched_kw or (matched_kws[0] if matched_kws else "")
                                        if hint_kw:
                                            entry["_grep_hint"] = f"grep -C 3 '{hint_kw}' {virtual_path}"
                                        logger.debug("Truncated: %d->%d chars, keyword='%s', pointer=%s",
                                                     original_len, len(snippet), matched_kw, entry['_pointer'])
                            
                            results.append(entry)
                                
                        except json.JSONDecodeError:
                            continue
                            
        except Exception as e:
            logger.warning("Grep: Failed to read %s: %s", jsonl_file, e)
            continue
    
    # Sort by relevance score (descending) and return top results
    results = sorted(results, key=lambda x: x.get("_relevance_score", 0), reverse=True)
    
    return results[:max_results]


def get_search_keywords(
    query: str,
    expand_keywords: bool,
    skill: str,
    llm=None,
    analyze_fn: Callable = None
) -> List[str]:
    """
    Get search keywords with optional LLM expansion.
    
    Args:
        query: User's query
        expand_keywords: Whether to expand using LLM
        skill: Current skill
        llm: LLM for expansion
        analyze_fn: Function for combined analysis
        
    Returns:
        List of search keywords
    """
    if expand_keywords and llm and analyze_fn:
        # Use combined analysis (keywords + entities in one call)
        analysis = analyze_fn(query, skill=skill)
        search_keywords = analysis.get("search_terms", [])
        if search_keywords:
            return search_keywords
    
    # Fallback to direct keyword extraction
    direct_keywords = extract_search_keywords(query)
    return direct_keywords


def search_episodes_agentic(
    query: str,
    history_path: Path,
    session_id: str,
    compute_relevance_fn: Callable,
    max_results: int = 10,
    expand_keywords: bool = True,
    scope: str = "all",
    days_back: int = None,
    skill_filter: str = None,
    _precomputed_keywords: List[str] = None,
    llm=None,
    analyze_fn: Callable = None
) -> List[Dict]:
    """
    Claude Code-style grep search: Direct file scanning with relevance scoring.
    
    This bypasses the master index and greps directly on JSONL files,
    providing line-level precision and ranked results by relevance.
    
    Args:
        query: User's search query
        history_path: Path to episode history
        session_id: Current session ID
        compute_relevance_fn: Function to compute relevance scores
        max_results: Maximum episodes to return
        expand_keywords: If True, ask LLM for related terms
        scope: "all" | "today" | "session" | "recent"
        days_back: Days to look back (for scope="recent")
        skill_filter: Only search episodes for this skill
        _precomputed_keywords: Pre-expanded keywords
        llm: LLM for keyword expansion
        analyze_fn: Function for query analysis
        
    Returns:
        List of matching episodes with metadata and relevance scores
    """
    # Step 1: Extract original keywords from query
    original_keywords = extract_search_keywords(query)
    
    # Step 2: Get LLM-expanded keywords if enabled
    if _precomputed_keywords:
        all_keywords = _precomputed_keywords
    elif expand_keywords and llm and analyze_fn:
        all_keywords = get_search_keywords(query, expand_keywords=True, 
                                           skill=skill_filter, llm=llm, analyze_fn=analyze_fn)
    else:
        all_keywords = original_keywords
    
    # Step 3: Separate expanded keywords
    original_kws_lower = set(k.lower() for k in original_keywords)
    expanded_keywords = [k for k in all_keywords if k.lower() not in original_kws_lower]
    
    if expanded_keywords:
        logger.debug("Search: original=%s, expanded=%s", original_keywords, expanded_keywords)
    
    if not all_keywords:
        logger.debug("Grep: No searchable keywords in query")
        return []
    
    if skill_filter:
        all_keywords.append(skill_filter.lower())
    
    # Step 4: Get files to search based on scope
    history_files = get_files_to_search(history_path, session_id, scope, days_back)
    
    if not history_files:
        logger.debug("Grep: No history files found for scope=%s", scope)
        return []
    
    # Step 5: Use grep helper with keyword separation for scoring
    results = grep_jsonl_files(
        keywords=all_keywords,
        files=history_files,
        compute_relevance_fn=compute_relevance_fn,
        history_path=history_path,
        max_results=max_results * 2,  # Get more, then rank
        original_keywords=original_keywords,
        expanded_keywords=expanded_keywords
    )
    
    if skill_filter:
        results = [r for r in results 
                  if r.get("skill", "").lower() == skill_filter.lower()]
    
    top_results = results[:max_results]
    
    # Log results — use os.path.basename to avoid Path construction from untrusted content
    files_matched = set(os.path.basename(r['_source_file']) for r in top_results
                        if r.get('_source_file') and '..' not in r['_source_file']) if top_results else set()
    top_score = top_results[0].get('_relevance_score', 'N/A') if top_results else 'N/A'
    logger.info("Grep: Found %d episodes (top score=%s) in files: %s",
                 len(top_results), top_score, list(files_matched))
    
    return top_results


def analyze_query_for_memory(
    query: str,
    skill: str = None,
    response: str = None,
    llm=None,
    light_llm=None
) -> Dict:
    """
    Combined LLM call: Extract search terms AND entities in one call.
    
    This replaces separate calls for keyword expansion and entity extraction.
    
    Args:
        query: User's query
        skill: Current skill
        response: Agent's response (optional)
        llm: Primary LLM
        light_llm: Light LLM (faster, cheaper)
        
    Returns:
        {"search_terms": [...], "entities": [...]}
    """
    direct_keywords = extract_search_keywords(query)
    
    if not llm and not light_llm:
        return {"search_terms": direct_keywords, "entities": []}
    
    # Use light_llm if available (faster, cheaper)
    llm_to_use = light_llm if light_llm else llm
    
    response_context = ""
    if response:
        response_context = f'\nResponse Preview: "{response[:300]}"'
    
    prompt = f"""Analyze this query for memory search and entity extraction.

Query: "{query}"
Skill: {skill or "unknown"}
Direct keywords: {direct_keywords}{response_context}

Return ONLY a JSON object with two parts:

1. "search_terms": 5-7 related terms/synonyms for finding similar past conversations
   Think: synonyms, abbreviations (AR, DSO, PO), related business concepts
   
2. "entities": Named business entities mentioned in the query (if any)
   Examples: invoice, customer, vendor, person, project, task, contract, order, metric, report, system
   NOTE: Only extract NAMED things (e.g., "ACME Corp", "INV-12345", "John Smith")
   Do NOT extract values like amounts ($10,000), dates, percentages, or counts
   Include action if clear from context: queried, rejected, approved, calculated, reviewed

Example output:
{{
  "search_terms": ["dso", "days sales outstanding", "ar aging", "collection days", "receivables"],
  "entities": [
    {{"type": "metric", "id": "DSO", "action": "queried"}},
    {{"type": "customer", "id": "ACME Corp", "action": null}}
  ]
}}

If no specific entities mentioned, return empty entities array.
JSON only, no explanation:"""

    try:
        from langchain_core.messages import HumanMessage
        messages = [HumanMessage(content=prompt)]
        llm_response = llm_to_use.invoke(messages)
        content = llm_response.content if hasattr(llm_response, 'content') else str(llm_response)
        
        # Parse JSON object from response
        json_match = re.search(r'\{[\s\S]*\}', content)
        if json_match:
            result = json.loads(json_match.group())
            
            search_terms = result.get("search_terms", [])
            if isinstance(search_terms, list):
                search_terms = [t.lower().strip() for t in search_terms 
                                if isinstance(t, str) and len(t) > 2][:7]
            else:
                search_terms = []
            
            # Combine with direct keywords
            all_terms = list(set(direct_keywords + search_terms))
            
            entities = result.get("entities", [])
            if not isinstance(entities, list):
                entities = []
            
            valid_entities = []
            for e in entities:
                if isinstance(e, dict) and "type" in e and "id" in e:
                    entity_id = e.get("id")
                    entity_type = str(e.get("type", "")).lower().strip()
                    
                    # Skip empty/null IDs
                    if not entity_id or str(entity_id).strip() in ["", "None", "null"]:
                        continue
                    
                    # Skip pure numeric/currency values
                    if re.match(r'^[\d,.$€£¥₹%\s]+$', str(entity_id)):
                        continue
                        
                    valid_entities.append({
                        "type": entity_type,
                        "id": str(entity_id).strip(),
                        "action": e.get("action")
                    })
            
            logger.debug("Memory Analysis: terms=%s, entities=%s", all_terms, [e['id'] for e in valid_entities])
            return {"search_terms": all_terms, "entities": valid_entities}
            
    except Exception as e:
        logger.warning("Query analysis failed: %s", e)
    
    return {"search_terms": direct_keywords, "entities": []}


def get_files_to_search(
    history_path: Path,
    session_id: str,
    scope: str = "all",
    days_back: int = None
) -> List[Path]:
    """
    Determine which history files to search based on scope.
    
    Args:
        history_path: Path to episode history
        session_id: Current session ID
        scope: "all" | "today" | "session" | "recent"
        days_back: Days to look back (for scope="recent")
        
    Returns:
        Files sorted by modification time (recent first)
    """
    all_files = list(history_path.glob("**/*.jsonl"))
    
    if not all_files:
        return []
    
    # Sort by modification time (most recent first)
    all_files_sorted = sorted(
        all_files,
        key=lambda f: f.stat().st_mtime,
        reverse=True
    )
    
    if scope == "session":
        # Only current session file
        today = datetime.now().strftime("%Y-%m-%d")
        session_file = history_path / today / f"{session_id}.jsonl"
        return [session_file] if session_file.exists() else []
    
    elif scope == "today":
        # Only today's files
        today = datetime.now().strftime("%Y-%m-%d")
        today_dir = history_path / today
        if today_dir.exists():
            today_files = list(today_dir.glob("*.jsonl"))
            return sorted(today_files, key=lambda f: f.stat().st_mtime, reverse=True)
        return []
    
    elif scope == "recent" and days_back:
        # Last N days
        cutoff = datetime.now() - timedelta(days=days_back)
        cutoff_ts = cutoff.timestamp()
        return [f for f in all_files_sorted if f.stat().st_mtime > cutoff_ts]
    
    else:  # scope == "all"
        return all_files_sorted
