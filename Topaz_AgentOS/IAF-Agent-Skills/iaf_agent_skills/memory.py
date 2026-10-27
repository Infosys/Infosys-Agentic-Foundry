#!/usr/bin/env python3
"""
Agent Memory System - Comprehensive memory management for agentic applications.

Memory Types:
- Short-term (Working): Current conversation context, in-memory
- Long-term (Semantic): Persistent facts, preferences, entities
- Episodic: Past conversation episodes, searchable history
- Procedural: Learned patterns, successful approaches

Features:
- Optimistic locking for concurrent access
- Automatic context assembly before LLM calls
- Fact extraction after responses
- History summarization pipeline

Usage:
    from iaf_agent_skills.memory import AgentMemory
    
    memory = AgentMemory(kernel=kernel, user_id="user123")
    
    # Knowledge search
    results = memory.grep_context_graph(["search terms"], max_results=10)
    context = memory.format_context_for_prompt(results)
    
    # After LLM response
    memory.log_episode(user_input, response, skill="general")
"""

import logging
import os
import json
import hashlib
import shutil
import uuid
import threading

from agent_os.safe_path import SecurityError, confine_to_root

from .file_lock import portable_lock
from .file_utils import atomic_write_json
from collections import OrderedDict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, Dict, List, Any
from dataclasses import dataclass, field, asdict

from .knowledge_crud import (
    write_knowledge as _write_knowledge_impl,
    confirm_knowledge as _confirm_knowledge_impl,
    reject_knowledge as _reject_knowledge_impl,
    edit_knowledge as _edit_knowledge_impl,
    bulk_confirm_knowledge as _bulk_confirm_knowledge_impl,
    bulk_reject_knowledge as _bulk_reject_knowledge_impl,
    find_knowledge_by_id as _find_knowledge_by_id_impl,
    find_knowledge_by_id_jsonl as _find_knowledge_by_id_jsonl_impl,
    KNOWLEDGE_TYPES as _KNOWLEDGE_TYPES,
    KNOWLEDGE_STATUSES as _KNOWLEDGE_STATUSES,
    KNOWLEDGE_SOURCES as _KNOWLEDGE_SOURCES,
)

from .knowledge_extractor import (
    read_extraction_cursor as _read_extraction_cursor_impl,
    write_extraction_cursor as _write_extraction_cursor_impl,
    get_extraction_status as _get_extraction_status_impl,
    collect_recent_episodes as _collect_recent_episodes_impl,
    get_existing_knowledge_summaries as _get_existing_knowledge_summaries_impl,
    get_existing_knowledge_summaries_jsonl as _get_existing_knowledge_summaries_jsonl_impl,
    extract_knowledge_from_chunk as _extract_knowledge_from_chunk_impl,
    batch_extract_knowledge as _batch_extract_knowledge_impl,
)

from .memory_search import (
    expand_search_terms_fast as _expand_search_terms_fast_impl,
    grep_context_graph as _grep_context_graph_impl,
    grep_context_graph_jsonl as _grep_context_graph_jsonl_impl,
    format_context_for_prompt as _format_context_for_prompt_impl,
    extract_topics_entities as _extract_topics_entities_impl,
    truncate_snippet as _truncate_snippet_impl,
    grep_jsonl_files as _grep_jsonl_files_impl,
    get_search_keywords as _get_search_keywords_impl,
    search_episodes_agentic as _search_episodes_agentic_impl,
    extract_search_keywords as _extract_search_keywords_impl,
    analyze_query_for_memory as _analyze_query_for_memory_impl,
    get_files_to_search as _get_files_to_search_impl,
)

from .knowledge_query import (
    compact_knowledge_jsonl as _compact_knowledge_jsonl_impl,
    get_jsonl_bloat_stats as _get_jsonl_bloat_stats_impl,
    query_knowledge as _query_knowledge_impl,
    get_knowledge_stats as _get_knowledge_stats_impl,
    find_duplicate_groups as _find_duplicate_groups_impl,
    merge_knowledge as _merge_knowledge_impl,
)

logger = logging.getLogger(__name__)


@dataclass
class MemoryEntry:
    """A single memory entry with metadata."""
    content: str
    type: str  # fact, entity, preference, pattern
    source: str  # conversation, extraction, user_stated
    confidence: float = 1.0
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    updated_at: str = field(default_factory=lambda: datetime.now().isoformat())
    version: int = 1
    tags: List[str] = field(default_factory=list)
    
    def to_dict(self) -> dict:
        return asdict(self)
    
    @classmethod
    def from_dict(cls, data: dict) -> "MemoryEntry":
        return cls(**data)


class OptimisticLockError(Exception):
    """Raised when optimistic locking detects a concurrent modification."""
    pass


class _LRUEmbeddingCache:
    """
    Thread-safe LRU cache for embedding vectors.

    Uses OrderedDict for O(1) get/put with automatic eviction of the
    least-recently-used entry when `maxsize` is exceeded. All operations
    are protected by a threading.Lock for safe concurrent access from
    API request threads, cron workers, and daemon threads.

    Memory budget: maxsize × 12KB per embedding (1536 floats × 8 bytes).
    Default 4096 entries ≈ 48MB. Configurable via EMBEDDING_CACHE_MAX_SIZE.
    """

    __slots__ = ("_maxsize", "_cache", "_lock", "_hits", "_misses", "_evictions")

    def __init__(self, maxsize: int = 4096):
        self._maxsize = max(maxsize, 16)  # Floor at 16 to avoid degenerate behavior
        self._cache: OrderedDict[str, List[float]] = OrderedDict()
        self._lock = threading.Lock()
        self._hits = 0
        self._misses = 0
        self._evictions = 0

    def get(self, key: str) -> Optional[List[float]]:
        """Retrieve embedding by key, promoting to most-recently-used. Returns None on miss."""
        with self._lock:
            if key in self._cache:
                self._cache.move_to_end(key)  # Mark as recently used
                self._hits += 1
                return self._cache[key]
            self._misses += 1
            return None

    def put(self, key: str, embedding: List[float]) -> None:
        """Store embedding, evicting LRU entry if at capacity."""
        with self._lock:
            if key in self._cache:
                self._cache.move_to_end(key)
                self._cache[key] = embedding
                return
            if len(self._cache) >= self._maxsize:
                self._cache.popitem(last=False)  # Evict oldest (LRU)
                self._evictions += 1
            self._cache[key] = embedding

    def stats(self) -> Dict[str, Any]:
        """Return cache statistics for observability / health endpoints."""
        with self._lock:
            total = self._hits + self._misses
            return {
                "size": len(self._cache),
                "maxsize": self._maxsize,
                "hits": self._hits,
                "misses": self._misses,
                "evictions": self._evictions,
                "hit_rate": round(self._hits / total, 4) if total > 0 else 0.0,
                "estimated_memory_mb": round(len(self._cache) * 12 / 1024, 2),
            }

    def clear(self) -> None:
        """Flush all cached embeddings and reset counters."""
        with self._lock:
            self._cache.clear()
            self._hits = 0
            self._misses = 0
            self._evictions = 0

    def __len__(self) -> int:
        with self._lock:
            return len(self._cache)


class AgentMemory:
    """
    Comprehensive memory system for agentic applications.
    
    Memory is stored in the SafeKernel filesystem:
    - memory/context_graph/  → Entities, decisions, knowledge (cross-session world model)
    - memory/history/        → Episodic conversation logs (by date/session)
    - memory/learnings/      → Procedural learnings (by type)
    
    Search is handled by KnowledgeIndexer (SQLite + FTS5 + embeddings).
    Live search mode is controlled by `knowledge_retrieval_mode` in agent config.
    """
    
    def __init__(
        self,
        kernel,  # SafeKernel instance
        user_id: str = None,
        session_id: str = None,
        llm = None,  # For knowledge extraction and summarization
        light_llm = None,  # For cheap classification tasks (gpt-4o-mini)
        tenant_id: str = "",  # For conversation_manager.upsert_session()
        agent_id: str = "",   # For conversation_manager.upsert_session()
    ):
        self.kernel = kernel
        self.user_id = user_id
        self.session_id = session_id or datetime.now().strftime("%Y%m%d_%H%M%S")
        self.llm = llm
        self.light_llm = light_llm or llm  # Fall back to main LLM if not provided
        self.tenant_id = tenant_id  # Used by log_episode() Phase 8
        self.agent_id = agent_id    # Used by log_episode() Phase 8
        
        # In-memory short-term (working) memory
        self.short_term: List[Dict] = []
        self.max_short_term = 20  # Keep last N turns
        
        # Cache for frequently accessed long-term memory
        self._cache: Dict[str, Any] = {}
        
        # Memory paths (simplified structure)
        self.memory_root = self.kernel.agent_root / "memory"

        self.history_path = self.memory_root / "history"

        _is_real_user = bool(user_id) and user_id not in ("demo", "anon", "anonymous", "") and ":" not in user_id
        self.user_prefs_path = (
            self.memory_root / "users" / user_id / "preferences"
            if _is_real_user else None
        )

        self.learnings_path = self.memory_root / "learnings"  # Procedural learnings (shared)
        self.master_index_path = self.memory_root / "master_index.json"  # Brain-like index
        
        # Knowledge store: JSONL-based (simplified from old Context Graph)
        self.context_graph_path = self.memory_root / "context_graph"
        
        # Primary JSONL files (knowledge + aliases only)
        self.knowledge_jsonl_path = self.context_graph_path / "knowledge.jsonl"
        self.aliases_jsonl_path = self.context_graph_path / "aliases.jsonl"
        self.extraction_cursor_path = self.context_graph_path / "extraction_cursor.json"
        
        # Ensure minimal directories exist
        for path in [self.history_path, self.learnings_path, self.context_graph_path]:
            path.mkdir(parents=True, exist_ok=True)
        if self.user_prefs_path:
            self.user_prefs_path.mkdir(parents=True, exist_ok=True)
        
        # Initialize master index if not exists
        if not self.master_index_path.exists():
            self._save_master_index({"sessions": {}, "topic_index": {}, "entity_index": {}})
        
        # Knowledge index (SQLite with embeddings + FTS5)
        self.knowledge_index_path = self.memory_root / "knowledge_index.db"
        self._knowledge_indexer = None  # Lazy — call .knowledge_indexer property
        self._conversation_manager = None  # Lazy — call .conversation_manager property


    @property
    def conversation_manager(self):
        """
        Lazy-initialized ConversationManager.
        Reuses the same knowledge_index.db to avoid adding new DB files.
        Creates the conversation_sessions table on first access.
        """
        if self._conversation_manager is None:
            try:
                from .conversation_manager import ConversationManager
            except ImportError:
                from conversation_manager import ConversationManager
            self._conversation_manager = ConversationManager(
                db_path=self.knowledge_index_path,
            )
        return self._conversation_manager


    @property
    def knowledge_indexer(self):
        """
        Lazy-initialized KnowledgeIndexer.
        Creates the SQLite index DB on first access.
        Uses Azure OpenAI embeddings if available, else FTS5-only.
        
        Vector backend selection via VECTOR_BACKEND env var:
          - "brute_force" (default): Pure Python cosine scan, zero deps
          - "sqlite_vec": sqlite-vec extension for in-DB ANN search
          - "pgvector": (future) PostgreSQL + pgvector
        """
        if self._knowledge_indexer is None:
            try:
                from .knowledge_indexer import KnowledgeIndexer
            except ImportError:
                from knowledge_indexer import KnowledgeIndexer
            try:
                from .vector_backend import create_vector_backend
            except ImportError:
                from vector_backend import create_vector_backend

            emb_fn = self._create_embedding_fn()

            # Create the indexer first (initializes SQLite DB connection)
            indexer = KnowledgeIndexer(
                db_path=self.knowledge_index_path,
                get_embedding_fn=emb_fn,
            )

            vector_backend = create_vector_backend(
                db_connection=indexer._db,
                scoped_connect=(
                    indexer._scoped_connect if indexer._kbackend == "postgres" else None
                ),
                # Per-agent isolation for the shared pgvector table (ignored by the
                # SQLite backends, which are already file/schema-scoped).
                namespace=(indexer._pg_schema if indexer._kbackend == "postgres" else ""),
            )
            indexer._vector_backend = vector_backend

            self._knowledge_indexer = indexer
        return self._knowledge_indexer

    def _create_embedding_fn(self):
        """
        Build an embedding callable using Azure OpenAI text-embedding-3-small.
        Returns None if credentials are missing (indexer falls back to FTS5).
        """
        import os as _os
        
        _emb_enabled = _os.getenv("KNOWLEDGE_EMBEDDINGS_ENABLED", "true").strip().lower()
        if _emb_enabled in {"0", "false", "no", "off"}:
            logger.info("KnowledgeIndexer: embeddings disabled (KNOWLEDGE_EMBEDDINGS_ENABLED) -- FTS5-only mode")
            return None
 
        api_key = _os.getenv("AZURE_OPENAI_API_KEY")
        endpoint = _os.getenv("AZURE_OPENAI_ENDPOINT")
        if not api_key or not endpoint:
            logger.info("KnowledgeIndexer: No Azure OpenAI credentials -- FTS5-only mode")
            return None

        api_version = _os.getenv("AZURE_OPENAI_API_VERSION", "2024-12-01-preview")
        model = _os.getenv("AZURE_OPENAI_EMBEDDING_MODEL", "text-embedding-ada-002")

        max_cache_size = int(_os.getenv("EMBEDDING_CACHE_MAX_SIZE", "4096"))
        _cache = _LRUEmbeddingCache(maxsize=max_cache_size)

        def _get_embedding(text: str) -> List[float]:
            cache_key = hashlib.sha256(text.encode()).hexdigest()
            cached = _cache.get(cache_key)
            if cached is not None:
                return cached
            try:
                import httpx as _httpx
                from openai import AzureOpenAI
                _ssl_val = (_os.getenv("PUBLIC_CA_BUNDLE") or _os.getenv("OPENAI_SSL_VERIFY") or "true").strip()
                _verify = False if _ssl_val.lower() in {"0", "false", "no", "off"} else (_ssl_val if _os.path.isfile(_ssl_val) else True)
                client = AzureOpenAI(
                    api_key=api_key,
                    api_version=api_version,
                    azure_endpoint=endpoint,
                    http_client=_httpx.Client(verify=_verify, timeout=30.0),
                )
                response = client.embeddings.create(input=text[:8000], model=model)
                embedding = response.data[0].embedding
                _cache.put(cache_key, embedding)
                return embedding
            except Exception as e:
                logger.error("Embedding call failed: %s", e)
                return []

        return _get_embedding

    
    def _compute_relevance_score(
        self,
        matched_original,  # int or List[str] - count of matched original keywords
        matched_expanded,  # int or List[str] - count of matched expanded keywords  
        total_original: int,
        total_expanded: int,
        entry_timestamp: Optional[str] = None,
        match_type: str = "keyword",
        matched_in_query: bool = False
    ) -> float:
        """
        Compute relevance score (0.0 - 1.0) for search result ranking.
        
        Original query keywords weighted higher (60%) than LLM expansions (40%).
        
        Args:
            matched_original: Count (int) or list of keywords from user's query that matched
            matched_expanded: Count (int) or list of LLM-expanded keywords that matched
            total_original: Total keywords from user's query
            total_expanded: Total LLM-expanded keywords
            entry_timestamp: When the entry was created (ISO format string)
            match_type: "entity", "topic", "keyword", or "fuzzy"
            matched_in_query: True if match found in user_input field
        
        Returns:
            float: Relevance score between 0.0 and 1.0
        """
        try:
            score = 0.0
            
            # Normalize inputs - accept both int and List[str]
            orig_count = matched_original if isinstance(matched_original, int) else len(matched_original)
            exp_count = matched_expanded if isinstance(matched_expanded, int) else len(matched_expanded)
            
            if total_original > 0:
                original_ratio = orig_count / total_original
                score += original_ratio * 0.24
            
            if total_expanded > 0:
                expanded_ratio = exp_count / total_expanded
                score += expanded_ratio * 0.16
            
            # 2. Recency (0 - 0.30)
            #    Today = 0.30, loses 0.01 per day, floor at 0.0
            if entry_timestamp:
                try:
                    if isinstance(entry_timestamp, str):
                        # Handle various ISO format variations
                        ts = entry_timestamp.replace("Z", "+00:00")
                        if "+" not in ts and "-" in ts[10:]:
                            # Simple date or datetime without timezone
                            entry_dt = datetime.fromisoformat(ts.split("+")[0].split("Z")[0])
                        else:
                            entry_dt = datetime.fromisoformat(ts)
                        # Make naive for comparison
                        if entry_dt.tzinfo is not None:
                            entry_dt = entry_dt.replace(tzinfo=None)
                    else:
                        entry_dt = entry_timestamp
                    
                    days_old = (datetime.now() - entry_dt).days
                    score += max(0.0, 0.30 - (days_old * 0.01))
                except (ValueError, TypeError):
                    score += 0.15  # Unknown = middle value
            else:
                score += 0.15  # Unknown = middle value
            
            # 3. Match Type (0 - 0.20)
            #    Entity match is strongest signal
            match_weights = {
                "entity": 0.20,
                "topic": 0.15,
                "keyword": 0.10,
                "fuzzy": 0.05
            }
            score += match_weights.get(match_type, 0.10)
            
            # 4. Field Bonus (0 - 0.10)
            #    Match in user_input field more relevant than response
            score += 0.10 if matched_in_query else 0.05
            
            return round(min(1.0, score), 2)
            
        except Exception as e:
            logger.error("Score computation failed: %s, using default", e)
            return 0.50
    
    
    def add_to_short_term(self, role: str, content: str, skill: str = None, 
                          tool_calls: List[str] = None):
        """Add an entry to short-term memory (current conversation)."""
        entry = {
            "timestamp": datetime.now().isoformat(),
            "role": role,
            "content": content,
            "skill": skill,
            "tool_calls": tool_calls or []
        }
        self.short_term.append(entry)
        
        # Trim to max size
        if len(self.short_term) > self.max_short_term:
            self.short_term = self.short_term[-self.max_short_term:]
    
    def get_short_term_context(self, last_n: int = 10) -> str:
        """Get recent conversation as context string."""
        recent = self.short_term[-last_n:] if self.short_term else []
        lines = []
        for entry in recent:
            role = entry["role"].upper()
            content = entry["content"][:500]  # Truncate long content
            skill_tag = f"[{entry['skill']}]" if entry.get("skill") else ""
            lines.append(f"{role}{skill_tag}: {content}")
        return "\n".join(lines)
    
    def export_short_term(self) -> List[Dict]:
        """
        Export short-term memory for Redis persistence.
        
        Returns a copy of the short_term list that can be JSON serialized.
        Used by SkillAgent.export_state() for horizontal scaling.
        """
        return [entry.copy() for entry in self.short_term]
    
    def import_short_term(self, data: List[Dict]) -> None:
        """
        Import short-term memory from Redis snapshot.
        
        Restores the working memory after agent is recreated on a
        different server in a load-balanced environment.
        
        Args:
            data: List of short-term memory entries from export_short_term()
        """
        self.short_term = [entry.copy() for entry in data] if data else []
        # Ensure we don't exceed max_short_term
        if len(self.short_term) > self.max_short_term:
            self.short_term = self.short_term[-self.max_short_term:]
        logger.info("Imported %d short-term memory entries", len(self.short_term))
    
    
    def log_episode(self, user_input: str, response: str, skill: str,
                    tool_calls: List[str] = None, decision_context: Dict = None,
                    summary_mode: str = "truncate",
                    update_brain_index: bool = False):
        """
        Log a conversation episode to history with FULL BUSINESS DECISION SCHEMA.
        
        The decision_context now contains the complete business schema:
        - routing: How query was routed to skill
        - entity: The primary business entity with status transitions
        - stakeholders: Who is involved
        - decision: Action taken with factors, alternatives, rules
        - context_used: Data sources and facts referenced
        - outcome: Processing metrics
        - learning_signals: Patterns to extract
        
        Args:
            summary_mode: How to summarize the response for episodic context
                - "truncate": First 200 chars (fast, lossy)
                - "llm": LLM-generated summary (slower, lossless semantic)
            update_brain_index: If True, update master index with topics/entities (LLM call)
                - Default False to save LLM costs. Grep search works without index.
        """
        date_str = datetime.now().strftime("%Y-%m-%d")
        try:
            # session_id is caller-supplied (may contain ':' e.g. workstream ids), so
            # confine the resolved history file under history/ rather than allowlisting.
            history_file = confine_to_root(
                self.history_path / date_str / f"{self.session_id}.jsonl",
                self.history_path, label="history file",
            )
        except SecurityError as exc:
            logger.warning("Episode not logged — rejected history path: %s", exc)
            return
        history_dir = history_file.parent
        history_dir.mkdir(parents=True, exist_ok=True)
        
        response_summary_truncate = response[:500]  # Always store truncated version
        response_summary_llm = None
        
        if summary_mode == "llm" and self.llm:
            # Pre-compute LLM summary at save time (not at context assembly)
            response_summary_llm = self._generate_episode_summary_llm(
                user_input, response, skill
            )
        
        # Build optimized entry - response is summarized, full schema in decision_context
        entry = {
            "timestamp": datetime.now().isoformat(),
            "user_id": self.user_id,
            "session_id": self.session_id,
            "skill": skill,
            "user_input": user_input,
            "response": response,                           # Full response for audit/replay
            "response_summary": response_summary_truncate,  # 500 chars for tiered context
            "response_summary_llm": response_summary_llm,   # LLM summary if enabled
            "tool_calls": tool_calls or []                   # Full tool calls (no truncation)
        }
        
        if decision_context:
            # Extract trace_id as top-level field (DecisionTrace common key)
            if decision_context.get("trace_id"):
                entry["trace_id"] = decision_context["trace_id"]
            # Write enriched tool_calls from decision_context (with input/output)
            enriched_tool_calls = decision_context.get("tool_calls")
            if enriched_tool_calls:
                entry["tool_calls"] = enriched_tool_calls
            entry.update({
                "routing": decision_context.get("routing"),
                "entity": (decision_context.get("routing") or {}).get("entity_hint"),
                "stakeholders": decision_context.get("stakeholders"),
                "decision": decision_context.get("decision"),
                "context_used": decision_context.get("context_used"),
                "outcome": decision_context.get("outcome"),
                "learning_signals": decision_context.get("learning_signals")
            })
        
        # Append-only write with file lock (prevents interleaved writes from concurrent threads)
        with portable_lock(history_file):
            with open(history_file, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry) + "\n")
                f.flush()
        
        # Phase 5d: auto-index episode for semantic search
        try:
            self.knowledge_indexer.upsert_episode(entry, file_path=str(history_file))
        except Exception as idx_err:
            logger.error("Episode index upsert failed (non-fatal): %s", idx_err)
        
        # Phase 8: Update conversation session index (sidebar metadata)
        try:
            parent_sid = getattr(self, '_parent_session_id', None)
            self.conversation_manager.upsert_session(
                session_id=self.session_id,
                tenant_id=self.tenant_id,
                agent_id=self.agent_id,
                user_id=self.user_id,
                title=user_input[:80] if user_input else "",
                first_message=user_input or "",
                skill=skill or "",
                parent_session_id=parent_sid,
                jsonl_path=str(history_file),
            )
        except Exception as conv_err:
            logger.warning("Conversation session upsert failed (non-fatal): %s", conv_err)

        # Transcript tiering: durable copy of this turn (no-op unless TRANSCRIPT_HOT_DAYS>0),
        # so cold history JSONL files can be pruned and still load from the store.
        try:
            self.conversation_manager.append_turn(
                session_id=self.session_id, entry=entry,
                tenant_id=self.tenant_id, agent_id=self.agent_id,
            )
        except Exception as turn_err:
            logger.warning("Conversation turn append failed (non-fatal): %s", turn_err)
        
        # Phase 7: Extract LLM reasoning + entities (background-safe, non-blocking)
        # This enriches the SQLite episode with high-quality reasoning
        try:
            llm_result = self._extract_reasoning_and_entities(entry)
            if llm_result:
                reasoning = llm_result.get("reasoning")
                entities = llm_result.get("entities", [])
                if reasoning or entities:
                    self.knowledge_indexer.update_episode_reasoning(
                        entry, reasoning=reasoning, entities=entities
                    )
                    logger.info("LLM reasoning stored (%d entities)", len(entities))
                _rels = llm_result.get("relationships") or []
                if _rels:
                    try:
                        from .world_model import record_relationships
                        from pathlib import Path as _Path
                        _er = getattr(self.knowledge_indexer, "entity_registry", None)
                        if _er is not None:
                            _dbp = getattr(self.knowledge_indexer, "db_path", None)
                            _events_path = None
                            if _dbp:
                                try:
                                    _events_path = str(confine_to_root(
                                        _Path(_dbp).parent / "world_events.jsonl",
                                        self.memory_root, label="world events log",
                                    ))
                                except SecurityError as _path_err:
                                    logger.warning("world_model events log skipped: %s", _path_err)
                            record_relationships(
                                _er, _rels,
                                source="turn_extractor",
                                created_by=(getattr(self, "user_id", None) or "agent"),
                                session_id=self.session_id,
                                events_path=_events_path,
                            )
                    except Exception as _wm_err:
                        logger.debug("world_model edge write failed (non-fatal): %s", _wm_err)
        except Exception as reason_err:
            logger.warning("Reasoning extraction failed (non-fatal): %s", reason_err)
        
        # Update master index (brain-like hierarchical memory) - optional
        # Disabled by default since grep search works without it
        if update_brain_index:
            file_rel_path = f"history/{date_str}/{self.session_id}.jsonl"
            self.update_master_index(user_input, response, skill, 
                                      self.session_id, file_rel_path)

    def _generate_episode_summary_llm(self, user_input: str, response: str, 
                                       skill: str) -> Optional[str]:
        """
        Generate a lossless semantic summary of the episode using LLM.
        
        This is pre-computed at episode save time (not at context assembly)
        to avoid async latency during prompt building.
        
        Returns:
            A concise but semantically complete summary, or None on failure.
        """
        if not self.llm:
            return None
        
        prompt = f"""Summarize this conversation exchange in 1-2 sentences.
Preserve: key entities, numbers, decisions made, actions taken.
Be specific - this summary will be used to recall this interaction later.

Skill: {skill}
User Query: {user_input}
Response: {response[:1500]}

Summary:"""
        
        try:
            # Use sync LLM call since we're in save path
            # Use invoke with messages format for better compatibility
            from langchain_core.messages import HumanMessage
            messages = [HumanMessage(content=prompt)]
            summary = self.llm.invoke(messages)
            try:
                import llm_tracker as _lt
                _lt.record("memory_summary", summary, 0.0, getattr(self.llm, 'azure_deployment', getattr(self.llm, 'model_name', '')))
            except Exception:
                pass
            if hasattr(summary, 'content'):
                result = summary.content.strip()
                logger.info("LLM summary generated: %s...", result[:80])
                return result
            return str(summary).strip()
        except Exception as e:
            logger.error("Episode summary generation failed: %s", e)
            return None
    

    def _extract_reasoning_and_entities(self, entry: Dict) -> Optional[Dict]:
        """
        Extract LLM-quality reasoning + entities from an episode using light LLM.
        
        Uses enriched tool_io from context_used to give the LLM full visibility
        into what the agent saw, did, and decided.
        
        Returns:
            {"reasoning": "...", "entities": ["...", ...]} or None on failure.
        """
        if not self.llm:
            return None
        
        user_input = entry.get("user_input", "")
        response_summary = entry.get("response_summary", entry.get("response", "")[:500])
        skill = entry.get("skill", "")
        context_used = entry.get("context_used", {})
        
        # Build tool IO section from enriched tool_calls (fallback to context_used.tool_io for old episodes)
        tool_io_lines = []
        tool_io = entry.get("tool_calls", []) or context_used.get("tool_io", [])
        for t in tool_io[:5]:
            tool_name = t.get("tool", "unknown")
            tool_input = t.get("input", "N/A")
            output = t.get("output_preview", "")[:600]
            tool_io_lines.append(f"  - Tool: {tool_name}\n    Input: {tool_input}\n    Output: {output}")
        tool_section = "\n".join(tool_io_lines) if tool_io_lines else "  (no tools used — pure LLM response)"
        
        facts = context_used.get("facts_referenced", [])
        knowledge_section = "\n".join(f"  - {f}" for f in facts[:5]) if facts else "  (no knowledge facts retrieved)"
        
        _learn = False
        try:
            from .world_model import world_model_learn_enabled
            _learn = world_model_learn_enabled()
        except Exception:
            _learn = False
        _rel_field = (
            ', "relationships": [{"from": "<an entity from the entities list>", '
            '"relation": "<UPPER_SNAKE_CASE verb, e.g. OWNS, DEPENDS_ON, BILLS, SUBMITS_VIA>", '
            '"to": "<an entity from the entities list>", "confidence": 0.0}]'
        ) if _learn else ""
        _rel_instr = (
            "\nAlso extract RELATIONSHIPS the interaction explicitly established or confirmed "
            "(never guesses). from/to MUST be entities from the entities list; confidence in "
            "[0,1] reflects certainty. Return an empty list if none.\n"
        ) if _learn else ""

        prompt = f"""Analyze this agent interaction and return ONLY a JSON object (no markdown, no explanation).

User query: {user_input}
Skill: {skill}
Prior skill: {context_used.get("prior_skill", "none")}
Short-term context turns: {context_used.get("short_term_turns", 0)}

Tools executed:
{tool_section}

Knowledge retrieved:
{knowledge_section}

Agent response (summary): {response_summary[:600]}
{_rel_instr}
Return this exact JSON structure:
{{"reasoning": "2-3 sentences: what approach the agent chose, what data it examined, what decisions it made and why", "entities": ["extract SPECIFIC named entities: company names, vendor names, people, database tables, invoice IDs, amounts, payment terms like Net60, statuses — NOT skill names or generic labels like invoice_processing_ap"]{_rel_field}}}"""
        
        try:
            from langchain_core.messages import HumanMessage
            result = self.llm.invoke([HumanMessage(content=prompt)])
            try:
                import llm_tracker as _lt
                _lt.record("memory_analysis", result, 0.0, getattr(self.llm, 'azure_deployment', getattr(self.llm, 'model_name', '')))
            except Exception:
                pass
            text = result.content.strip() if hasattr(result, 'content') else str(result).strip()
            
            # Parse JSON — handle markdown code fences
            if text.startswith("```"):
                text = text.split("\n", 1)[1] if "\n" in text else text[3:]
                text = text.rsplit("```", 1)[0]
            
            parsed = json.loads(text)
            reasoning = parsed.get("reasoning", "")
            entities = parsed.get("entities", [])
            
            if not isinstance(entities, list):
                entities = []
            entities = [str(e).lower().strip() for e in entities if e][:20]

            relationships = []
            if _learn:
                _rels = parsed.get("relationships", [])
                if isinstance(_rels, list):
                    relationships = [r for r in _rels if isinstance(r, dict)][:20]

            logger.info("LLM reasoning extracted: %s...", reasoning[:80])
            logger.debug("Entities: %s", entities)
            return {"reasoning": reasoning, "entities": entities, "relationships": relationships}
        except Exception as e:
            logger.warning("Reasoning extraction failed (non-fatal): %s", e)
            return None
    
    
    def _load_master_index(self) -> Dict:
        """Load the master memory index (the 'brain' that knows what it knows)."""
        if self.master_index_path.exists():
            try:
                with open(self.master_index_path, encoding="utf-8") as f:
                    return json.load(f)
            except (json.JSONDecodeError, IOError):
                pass
        return {"sessions": {}, "topic_index": {}, "entity_index": {}}
    
    def _save_master_index(self, index: Dict):
        """Save the master memory index — locked + atomic write."""
        index["last_updated"] = datetime.now().isoformat()
        with portable_lock(self.master_index_path):
            atomic_write_json(self.master_index_path, index)
    
    # Class-level aliases to module constants (for backward compatibility)
    KNOWLEDGE_TYPES = _KNOWLEDGE_TYPES
    KNOWLEDGE_STATUSES = _KNOWLEDGE_STATUSES
    KNOWLEDGE_SOURCES = _KNOWLEDGE_SOURCES
    
    def write_knowledge(self, knowledge_type: str, summary: str,
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
                        source_context_file: str = None) -> str:
        """
        Write a knowledge record to knowledge.jsonl.

        DELEGATED to knowledge_crud.write_knowledge().
        See that module for implementation details.
        """
        return _write_knowledge_impl(
            knowledge_type=knowledge_type,
            summary=summary,
            knowledge_jsonl_path=self.knowledge_jsonl_path,
            knowledge_indexer=self.knowledge_indexer,
            session_id=self.session_id,
            user_id=self.user_id,
            tags=tags,
            applies_when=applies_when,
            source=source,
            status=status,
            skill=skill,
            episode_id=episode_id,
            entity_keys=entity_keys,
            user_query=user_query,
            recommended_tools=recommended_tools,
            supersedes_summary=supersedes_summary,
            source_context_file=source_context_file,
        )
    
    def confirm_knowledge(self, knowledge_id: str, written_to: str = None) -> bool:
        """
        Mark a pending_review knowledge record as confirmed.

        DELEGATED to knowledge_crud.confirm_knowledge().
        See that module for implementation details.
        """
        return _confirm_knowledge_impl(
            knowledge_id=knowledge_id,
            knowledge_jsonl_path=self.knowledge_jsonl_path,
            knowledge_indexer=self.knowledge_indexer,
            user_id=self.user_id,
            written_to=written_to,
        )
    
    def reject_knowledge(self, knowledge_id: str) -> bool:
        """
        Archive/reject a knowledge record.
        
        DELEGATED to knowledge_crud.reject_knowledge().
        See that module for implementation details.
        """
        return _reject_knowledge_impl(
            knowledge_id=knowledge_id,
            knowledge_jsonl_path=self.knowledge_jsonl_path,
            knowledge_indexer=self.knowledge_indexer,
        )
    
    def bulk_confirm_knowledge(self, knowledge_ids: List[str]) -> dict:
        """
        Bulk confirm multiple pending_review knowledge records.
        
        DELEGATED to knowledge_crud.bulk_confirm_knowledge().
        See that module for implementation details.
        """
        return _bulk_confirm_knowledge_impl(
            knowledge_ids=knowledge_ids,
            knowledge_jsonl_path=self.knowledge_jsonl_path,
            knowledge_indexer=self.knowledge_indexer,
            user_id=self.user_id,
        )
    
    def bulk_reject_knowledge(self, knowledge_ids: List[str]) -> dict:
        """
        Bulk reject/archive multiple knowledge records.
        
        DELEGATED to knowledge_crud.bulk_reject_knowledge().
        See that module for implementation details.
        """
        return _bulk_reject_knowledge_impl(
            knowledge_ids=knowledge_ids,
            knowledge_jsonl_path=self.knowledge_jsonl_path,
            knowledge_indexer=self.knowledge_indexer,
        )
    
    def edit_knowledge(self, knowledge_id: str, summary: str = None,
                       knowledge_type: str = None,
                       applies_when: str = None,
                       tags: List[str] = None,
                       entity_keys: List[str] = None,
                       written_to: str = None,
                       suggested_file: str = None) -> bool:
        """
        Edit a knowledge record in place.

        DELEGATED to knowledge_crud.edit_knowledge().
        See that module for implementation details.
        """
        return _edit_knowledge_impl(
            knowledge_id=knowledge_id,
            knowledge_jsonl_path=self.knowledge_jsonl_path,
            knowledge_indexer=self.knowledge_indexer,
            summary=summary,
            knowledge_type=knowledge_type,
            applies_when=applies_when,
            tags=tags,
            entity_keys=entity_keys,
            written_to=written_to,
            suggested_file=suggested_file,
        )


    def compact_knowledge_jsonl(self) -> Dict[str, Any]:
        """
        Compact the knowledge JSONL file by deduplicating records.

        DELEGATED to knowledge_query.compact_knowledge_jsonl().
        See that module for implementation details.
        """
        return _compact_knowledge_jsonl_impl(
            knowledge_jsonl_path=self.knowledge_jsonl_path,
        )

    def get_jsonl_bloat_stats(self) -> Dict[str, Any]:
        """
        Return bloat statistics for the knowledge JSONL file without modifying it.

        DELEGATED to knowledge_query.get_jsonl_bloat_stats().
        See that module for implementation details.
        """
        return _get_jsonl_bloat_stats_impl(
            knowledge_jsonl_path=self.knowledge_jsonl_path,
        )

    def _find_knowledge_by_id(self, knowledge_id: str) -> Optional[Dict]:
        """
        Find the latest version of a knowledge record by ID.
        
        DELEGATED to knowledge_crud.find_knowledge_by_id().
        See that module for implementation details.
        """
        return _find_knowledge_by_id_impl(
            knowledge_id=knowledge_id,
            knowledge_indexer=self.knowledge_indexer,
            knowledge_jsonl_path=self.knowledge_jsonl_path,
        )
    
    def _find_knowledge_by_id_jsonl(self, knowledge_id: str) -> Optional[Dict]:
        """
        JSONL fallback for _find_knowledge_by_id.
        
        DELEGATED to knowledge_crud.find_knowledge_by_id_jsonl().
        See that module for implementation details.
        """
        return _find_knowledge_by_id_jsonl_impl(
            knowledge_id=knowledge_id,
            knowledge_jsonl_path=self.knowledge_jsonl_path,
        )
    
    def query_knowledge(self, status: str = "confirmed",
                        knowledge_type: str = None,
                        skill: str = None,
                        tag: str = None,
                        source: str = None,
                        limit: int = 50,
                        offset: int = 0,
                        include_archived: bool = False) -> Dict:
        """
        Query knowledge records with structured filters.
        
        DELEGATED to knowledge_query.query_knowledge().
        See that module for implementation details.
        """
        return _query_knowledge_impl(
            knowledge_jsonl_path=self.knowledge_jsonl_path,
            knowledge_indexer=self.knowledge_indexer,
            status=status,
            knowledge_type=knowledge_type,
            skill=skill,
            tag=tag,
            source=source,
            limit=limit,
            offset=offset,
            include_archived=include_archived,
        )
    
    def get_knowledge_stats(self) -> Dict:
        """
        Get statistics about the knowledge store.
        
        DELEGATED to knowledge_query.get_knowledge_stats().
        See that module for implementation details.
        """
        return _get_knowledge_stats_impl(
            knowledge_jsonl_path=self.knowledge_jsonl_path,
            knowledge_indexer=self.knowledge_indexer,
            get_bloat_stats_fn=self.get_jsonl_bloat_stats,
        )
    

    def find_duplicate_groups(self, status: str = "all",
                               min_group_size: int = 2,
                               max_records: int = 200) -> Dict:
        """
        Use LLM to semantically cluster knowledge records into duplicate groups.
        
        DELEGATED to knowledge_query.find_duplicate_groups().
        See that module for implementation details.
        """
        return _find_duplicate_groups_impl(
            knowledge_jsonl_path=self.knowledge_jsonl_path,
            knowledge_indexer=self.knowledge_indexer,
            light_llm=self.light_llm,
            status=status,
            min_group_size=min_group_size,
            max_records=max_records,
        )

    def merge_knowledge(self, keep_id: str, archive_ids: List[str],
                         merged_summary: str = None) -> Dict:
        """
        Merge duplicate knowledge records: keep one winner, archive the rest.
        
        DELEGATED to knowledge_query.merge_knowledge().
        See that module for implementation details.
        """
        return _merge_knowledge_impl(
            keep_id=keep_id,
            archive_ids=archive_ids,
            find_knowledge_by_id_fn=self._find_knowledge_by_id,
            edit_knowledge_fn=self.edit_knowledge,
            confirm_knowledge_fn=self.confirm_knowledge,
            reject_knowledge_fn=self.reject_knowledge,
            merged_summary=merged_summary,
        )


    def _read_extraction_cursor(self) -> Optional[Dict]:
        """
        Read the extraction cursor file.
        
        DELEGATED to knowledge_extractor.read_extraction_cursor().
        """
        return _read_extraction_cursor_impl(self.extraction_cursor_path)

    def _write_extraction_cursor(self, episodes_processed: int, knowledge_extracted: int) -> None:
        """
        Write the extraction cursor.
        
        DELEGATED to knowledge_extractor.write_extraction_cursor().
        """
        _write_extraction_cursor_impl(
            self.extraction_cursor_path,
            episodes_processed,
            knowledge_extracted
        )

    def get_extraction_status(self) -> Optional[Dict]:
        """
        Return extraction cursor data for API.
        
        DELEGATED to knowledge_extractor.get_extraction_status().
        """
        return _get_extraction_status_impl(self.extraction_cursor_path)

    
    def batch_extract_knowledge(self, hours_back: int = 24,
                                 max_tokens_budget: int = 150_000,
                                 skill: Optional[str] = None,
                                 force_full: bool = False) -> Dict:
        """
        Mine recent episodic logs for reusable knowledge patterns.
        
        DELEGATED to knowledge_extractor.batch_extract_knowledge().
        See that module for implementation details.
        """
        # Derive shared dir: agent_root/../../shared (tenants/company/shared)
        _entity_guide_path = None
        try:
            _shared = self.memory_root.parent.parent.parent / "shared"
            _gp = _shared / "entity_guide.md"
            if _gp.exists():
                _entity_guide_path = _gp
        except Exception:
            pass

        return _batch_extract_knowledge_impl(
            history_path=self.history_path,
            extraction_cursor_path=self.extraction_cursor_path,
            knowledge_jsonl_path=self.knowledge_jsonl_path,
            knowledge_indexer=self.knowledge_indexer,
            light_llm=self.light_llm,
            write_knowledge_fn=self.write_knowledge,
            knowledge_types=self.KNOWLEDGE_TYPES,
            hours_back=hours_back,
            max_tokens_budget=max_tokens_budget,
            skill=skill,
            force_full=force_full,
            entity_guide_path=_entity_guide_path,
        )
    
    def _collect_recent_episodes(self, cutoff, skill: Optional[str] = None) -> List[Dict]:
        """
        Collect episodic log entries after cutoff.
        
        DELEGATED to knowledge_extractor.collect_recent_episodes().
        """
        return _collect_recent_episodes_impl(
            history_path=self.history_path,
            cutoff=cutoff,
            skill=skill,
        )
    
    def _get_existing_knowledge_summaries(self) -> List[str]:
        """
        Get summaries of confirmed + pending knowledge for dedup.
        
        DELEGATED to knowledge_extractor.get_existing_knowledge_summaries().
        """
        return _get_existing_knowledge_summaries_impl(
            knowledge_indexer=self.knowledge_indexer,
            knowledge_jsonl_path=self.knowledge_jsonl_path,
        )
    
    def _get_existing_knowledge_summaries_jsonl(self) -> List[str]:
        """
        JSONL fallback for _get_existing_knowledge_summaries.
        
        DELEGATED to knowledge_extractor.get_existing_knowledge_summaries_jsonl().
        """
        return _get_existing_knowledge_summaries_jsonl_impl(self.knowledge_jsonl_path)
    
    def _extract_knowledge_from_chunk(self, episodes: List[Dict],
                                       existing_summaries: List[str]) -> List[Dict]:
        """
        Call LLM to extract reusable knowledge from a chunk of episodes.
        
        DELEGATED to knowledge_extractor.extract_knowledge_from_chunk().
        """
        return _extract_knowledge_from_chunk_impl(
            episodes=episodes,
            existing_summaries=existing_summaries,
            light_llm=self.light_llm,
            knowledge_types=self.KNOWLEDGE_TYPES,
        )
    
    def _expand_search_terms_fast(self, query: str) -> List[str]:
        """
        Fast alias expansion - NO LLM call.
        
        DELEGATED to memory_search.expand_search_terms_fast().
        """
        return _expand_search_terms_fast_impl(query, self.aliases_jsonl_path)
    
    def grep_context_graph(self, keywords: List[str], max_results: int = 50) -> List[Dict]:
        """
        Search knowledge records matching keywords.
        
        DELEGATED to memory_search.grep_context_graph().
        """
        return _grep_context_graph_impl(
            keywords, self.knowledge_indexer, self.knowledge_jsonl_path, max_results
        )
    
    def _grep_context_graph_jsonl(self, keywords: List[str], max_results: int = 50) -> List[Dict]:
        """
        JSONL fallback for grep_context_graph.
        
        DELEGATED to memory_search.grep_context_graph_jsonl().
        """
        return _grep_context_graph_jsonl_impl(
            keywords, self.knowledge_jsonl_path, max_results
        )
    
    def format_context_for_prompt(self, grep_results: List[Dict], 
                                   max_chars: int = 2000) -> str:
        """
        Format knowledge records for LLM prompt injection.
        
        DELEGATED to memory_search.format_context_for_prompt().
        """
        return _format_context_for_prompt_impl(grep_results, max_chars)

    def _extract_topics_entities(self, user_input: str, response: str, 
                                  skill: str) -> Dict[str, List[str]]:
        """
        Extract topics and entities from conversation for indexing.
        
        DELEGATED to memory_search.extract_topics_entities().
        """
        return _extract_topics_entities_impl(user_input, response, skill, self.llm)
    
    def update_master_index(self, user_input: str, response: str, skill: str,
                            session_id: str = None, file_path: str = None):
        """
        Update the master index after logging an episode.
        Called automatically after log_episode() to maintain the brain's index.
        
        NOTE: This function has side effects (loads/saves index), 
        so it remains in memory.py with a local implementation.
        """
        session_key = (session_id or self.session_id).replace("_", "")[:20]
        date_str = datetime.now().strftime("%Y-%m-%d")
        
        # Extract topics and entities (delegated)
        extracted = self._extract_topics_entities(user_input, response, skill)
        topics = extracted.get("topics", [])
        entities = extracted.get("entities", [])
        
        index = self._load_master_index()
        
        if session_key not in index["sessions"]:
            index["sessions"][session_key] = {
                "date": date_str,
                "user_id": self.user_id,
                "topics": [],
                "entities": [],
                "skills": [],
                "episode_count": 0,
                "file": file_path or f"history/{date_str}/{self.session_id}.jsonl"
            }
        
        session = index["sessions"][session_key]
        session["topics"] = list(set(session["topics"] + topics))[:10]
        session["entities"] = list(set(session["entities"] + entities))[:10]
        if skill and skill not in session["skills"]:
            session["skills"].append(skill)
        session["episode_count"] = session.get("episode_count", 0) + 1
        session["last_updated"] = datetime.now().isoformat()
        
        # Update topic index (reverse lookup)
        for topic in topics:
            if topic not in index["topic_index"]:
                index["topic_index"][topic] = []
            if session_key not in index["topic_index"][topic]:
                index["topic_index"][topic].append(session_key)
        
        # Update entity index (reverse lookup)
        for entity in entities:
            if entity not in index["entity_index"]:
                index["entity_index"][entity] = []
            if session_key not in index["entity_index"][entity]:
                index["entity_index"][entity].append(session_key)
        
        self._save_master_index(index)
        logger.info("Brain: Indexed session with %d topics, %d entities", len(topics), len(entities))

    
    def _truncate_snippet(self, text: str, keywords: List[str], 
                          max_chars: int = 300) -> tuple:
        """
        Truncate text centered on keyword match.
        
        DELEGATED to memory_search.truncate_snippet().
        """
        return _truncate_snippet_impl(text, keywords, max_chars)
    
    def _grep_jsonl_files(self, keywords: List[str], files: List[Path], 
                          max_results: int = 10, 
                          type_filter: str = None,
                          original_keywords: List[str] = None,
                          expanded_keywords: List[str] = None,
                          truncate_snippets: bool = True,
                          max_snippet_chars: int = 300) -> List[Dict]:
        """
        Shared grep helper for episodes/learnings search.
        
        DELEGATED to memory_search.grep_jsonl_files().
        """
        return _grep_jsonl_files_impl(
            keywords=keywords,
            files=files,
            compute_relevance_fn=self._compute_relevance_score,
            history_path=self.history_path,
            max_results=max_results,
            type_filter=type_filter,
            original_keywords=original_keywords,
            expanded_keywords=expanded_keywords,
            truncate_snippets=truncate_snippets,
            max_snippet_chars=max_snippet_chars,
        )
    
    def _get_search_keywords(self, query: str, expand_keywords: bool = True,
                              skill: str = None) -> List[str]:
        """
        Get search keywords with optional LLM expansion.
        
        DELEGATED to memory_search.get_search_keywords().
        """
        return _get_search_keywords_impl(
            query=query,
            expand_keywords=expand_keywords,
            skill=skill,
            llm=self.llm,
            analyze_fn=self._analyze_query_for_memory,
        )

    def _get_recent_episode_files(self, days: int = 7, entity_hint: str = None) -> List[Path]:
        """
        Return episode JSONL file paths from the last N days, newest first.

        If entity_hint provided, filters to files where at least one record
        mentions the entity in its 'entity' or 'routing.entity_hint' field.
        Uses fast string scan (no full JSON parse) for speed.

        Returns at most 10 paths.
        """
        from datetime import timedelta
        cutoff = datetime.now() - timedelta(days=days)
        candidate_files: List[Path] = []

        if not self.history_path.exists():
            return []

        for date_dir in sorted(self.history_path.iterdir(), reverse=True):
            if not date_dir.is_dir():
                continue
            try:
                dir_date = datetime.strptime(date_dir.name, "%Y-%m-%d")
            except ValueError:
                continue
            if dir_date < cutoff:
                break
            for jf in sorted(date_dir.glob("*.jsonl"), key=lambda p: p.stat().st_mtime, reverse=True):
                candidate_files.append(jf)

        if not entity_hint:
            return candidate_files[:10]

        needle = entity_hint.lower()
        matched: List[Path] = []
        for jf in candidate_files:
            try:
                content = jf.read_text(encoding="utf-8", errors="ignore").lower()
                if needle in content:
                    matched.append(jf)
                    if len(matched) >= 10:
                        break
            except Exception:
                continue
        return matched

    def search_episodes_agentic(self, query: str, max_results: int = 10,
                                 expand_keywords: bool = True,
                                 scope: str = "all",
                                 days_back: int = None,
                                 skill_filter: str = None,
                                 _precomputed_keywords: List[str] = None) -> List[Dict]:
        """
        Claude Code-style grep search with relevance scoring.
        
        DELEGATED to memory_search.search_episodes_agentic().
        """
        return _search_episodes_agentic_impl(
            query=query,
            history_path=self.history_path,
            session_id=self.session_id,
            compute_relevance_fn=self._compute_relevance_score,
            max_results=max_results,
            expand_keywords=expand_keywords,
            scope=scope,
            days_back=days_back,
            skill_filter=skill_filter,
            _precomputed_keywords=_precomputed_keywords,
            llm=self.llm,
            analyze_fn=self._analyze_query_for_memory,
        )
    
    def _extract_search_keywords(self, query: str) -> List[str]:
        """
        Extract meaningful keywords from query for grep search.
        
        DELEGATED to memory_search.extract_search_keywords().
        """
        return _extract_search_keywords_impl(query)
    
    def _analyze_query_for_memory(self, query: str, skill: str = None,
                                   response: str = None) -> Dict:
        """
        Combined LLM call: Extract search terms AND entities.
        
        DELEGATED to memory_search.analyze_query_for_memory().
        """
        return _analyze_query_for_memory_impl(
            query=query,
            skill=skill,
            response=response,
            llm=self.llm,
            light_llm=self.light_llm,
        )

    def _get_files_to_search(self, scope: str = "all", 
                              days_back: int = None) -> List[Path]:
        """
        Determine which history files to search.
        
        DELEGATED to memory_search.get_files_to_search().
        """
        return _get_files_to_search_impl(
            self.history_path, self.session_id, scope, days_back
        )
    



def create_memory(kernel, user_id: str = None, llm=None) -> AgentMemory:
    """Factory function to create an AgentMemory instance."""
    return AgentMemory(kernel=kernel, user_id=user_id, llm=llm)
