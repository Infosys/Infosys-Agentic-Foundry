# © 2024-25 Infosys Limited, Bangalore, India. All Rights Reserved.
"""
VectorStore - Local vector database for semantic search.

Uses a simple in-memory store with file persistence.
For production, can be replaced with LanceDB or ChromaDB.

The embedder is **pluggable**: any object with an
``encode(text: str) -> List[float]`` method can be passed to VectorStore.
The built-in ``SimpleEmbedder`` uses hash-based TF-IDF (good for testing,
poor for real semantic similarity).  Swap it with sentence-transformers or
OpenAI embeddings for production quality.
"""

import json
import hashlib
import math
import os
import threading
import tempfile
from abc import ABC, abstractmethod
from pathlib import Path
from typing import List, Dict, Any, Optional, Protocol, runtime_checkable
from dataclasses import dataclass, field
from datetime import datetime, timezone

try:
    from telemetry_wrapper import logger as log
except ImportError:
    import logging
    log = logging.getLogger(__name__)


def _utc_now() -> str:
    """Get current UTC time as ISO string."""
    return datetime.now(timezone.utc).isoformat()


@dataclass
class VectorDocument:
    """A document with its embedding."""
    id: str
    path: str
    content: str
    embedding: List[float]
    metadata: Dict[str, Any] = field(default_factory=dict)
    updated_at: str = field(default_factory=_utc_now)


@dataclass
class SearchResult:
    """A search result."""
    path: str
    content: str
    score: float
    snippet: str


class SimpleEmbedder:
    """
    Simple TF-IDF-like embedder for semantic search.
    
    Uses hash-based embeddings that capture word presence.
    
    **Not suitable for production semantic search.** Replace with a real
    embedding model by implementing the ``Embedder`` protocol::
    
        class SentenceTransformerEmbedder:
            def __init__(self, model_name: str = "all-MiniLM-L6-v2"):
                from sentence_transformers import SentenceTransformer
                self._model = SentenceTransformer(model_name)
            def encode(self, text: str) -> List[float]:
                return self._model.encode(text).tolist()
    
    Then pass it to VectorStore:
        ``VectorStore(storage_path=..., embedder=SentenceTransformerEmbedder())``
    """
    
    def __init__(self, dim: int = 256):
        self.dim = dim
    
    def encode(self, text: str) -> List[float]:
        """Create a hash-based embedding."""
        # Normalize text
        text = text.lower()
        
        # Tokenize into words and n-grams
        words = text.split()
        
        # Add bigrams for better semantic capture
        bigrams = [f"{words[i]}_{words[i+1]}" for i in range(len(words)-1)]
        tokens = words + bigrams
        
        # Create embedding based on token hashes
        embedding = [0.0] * self.dim
        
        for token in tokens:
            # Hash the token to get positions (using SHA-256 for compliance)
            token_hash = int(hashlib.sha256(token.encode()).hexdigest(), 16)
            
            # Use multiple hash positions for better distribution
            pos1 = token_hash % self.dim
            pos2 = (token_hash >> 8) % self.dim
            
            embedding[pos1] += 1.0
            embedding[pos2] += 0.5
        
        # Normalize to unit vector
        magnitude = math.sqrt(sum(x*x for x in embedding)) or 1.0
        embedding = [x / magnitude for x in embedding]
        
        return embedding


class VectorStore:
    """
    Simple vector store with cosine similarity search.
    
    Features:
    - In-memory storage with optional file persistence
    - Cosine similarity search
    - Path-based filtering
    - Automatic re-indexing on content change
    - Thread-safe operations with locking
    - Atomic writes (write-to-temp-then-rename) to prevent data loss
    - Debounced saves to reduce I/O under rapid upserts
    """
    
    # Maximum mutations before forcing a flush even if debounce hasn't elapsed
    _MAX_DIRTY_COUNT = 20
    # Schema version — bump when the persisted JSON structure changes.
    # _load() uses this to detect incompatible data and re-index instead of crashing.
    _SCHEMA_VERSION = 1

    def __init__(
        self,
        storage_path: Optional[Path] = None,
        embedder: Optional[Any] = None
    ):
        """
        Initialize vector store.
        
        Args:
            storage_path: Path to persist the index (optional).
            embedder: Any object with an ``encode(text: str) -> List[float]``
                      method.  Defaults to ``SimpleEmbedder`` (hash-based).
                      For production, pass a sentence-transformers or OpenAI
                      embedder instance.
        """
        self.storage_path = Path(storage_path) if storage_path else None
        self.embedder = embedder or SimpleEmbedder()
        self.documents: Dict[str, VectorDocument] = {}
        self._lock = threading.Lock()
        self._dirty_count = 0  # Number of mutations since last save
        
        # Load existing index
        if self.storage_path and self.storage_path.exists():
            self._load()
        log.info(f"VectorStore initialized: storage={self.storage_path}, docs={len(self.documents)}")
    
    def _cosine_similarity(self, a: List[float], b: List[float]) -> float:
        """Calculate cosine similarity between two vectors."""
        dot = sum(x * y for x, y in zip(a, b))
        mag_a = math.sqrt(sum(x * x for x in a)) or 1.0
        mag_b = math.sqrt(sum(x * x for x in b)) or 1.0
        return dot / (mag_a * mag_b)
    
    def upsert(self, path: str, content: str, metadata: Optional[Dict] = None):
        """
        Add or update a document in the index (thread-safe).
        
        Args:
            path: File path (used as ID).
            content: Document content.
            metadata: Optional metadata.
        """
        doc_id = hashlib.sha256(path.encode()).hexdigest()
        embedding = self.embedder.encode(content)
        
        doc = VectorDocument(
            id=doc_id,
            path=path,
            content=content,
            embedding=embedding,
            metadata=metadata or {},
            updated_at=_utc_now()
        )
        
        with self._lock:
            self.documents[doc_id] = doc
            self._dirty_count += 1
            should_flush = self._dirty_count >= self._MAX_DIRTY_COUNT
        
        # Flush to disk if enough mutations have accumulated
        if should_flush and self.storage_path:
            self._save()
    
    def delete(self, path: str):
        """Remove a document from the index (thread-safe)."""
        doc_id = hashlib.sha256(path.encode()).hexdigest()
        with self._lock:
            if doc_id in self.documents:
                del self.documents[doc_id]
                self._dirty_count += 1
        if self.storage_path:
            self._save()
    
    def search(
        self,
        query: str,
        path_prefix: Optional[str] = None,
        top_k: int = 10,
        min_score: float = 0.1
    ) -> List[SearchResult]:
        """
        Search for documents similar to the query (thread-safe).
        
        Args:
            query: Natural language query.
            path_prefix: Optional path prefix to filter results.
            top_k: Number of results to return.
            min_score: Minimum similarity score threshold.
            
        Returns:
            List of SearchResult objects.
        """
        query_embedding = self.embedder.encode(query)
        
        # Snapshot documents under lock to avoid dict-changed-size errors
        with self._lock:
            docs_snapshot = list(self.documents.values())
        
        if not docs_snapshot:
            return []
        
        # Calculate similarities (outside lock — read-only on snapshot)
        results = []
        for doc in docs_snapshot:
            if path_prefix and not doc.path.startswith(path_prefix):
                continue
            
            score = self._cosine_similarity(query_embedding, doc.embedding)
            if score < min_score:
                continue
            
            snippet = doc.content[:200].replace("\n", " ")
            if len(doc.content) > 200:
                snippet += "..."
            
            results.append(SearchResult(
                path=doc.path,
                content=doc.content,
                score=score,
                snippet=snippet
            ))
        
        results.sort(key=lambda x: x.score, reverse=True)
        return results[:top_k]
    
    def flush(self):
        """Force-flush any pending changes to disk."""
        if self.storage_path and self._dirty_count > 0:
            self._save()
    
    def get_stats(self) -> Dict[str, Any]:
        """Get statistics about the index."""
        with self._lock:
            return {
                "total_documents": len(self.documents),
                "storage_path": str(self.storage_path) if self.storage_path else None,
                "paths": [doc.path for doc in self.documents.values()]
            }
    
    def _save(self):
        """Persist index to disk using atomic write (write-to-temp-then-rename)."""
        if not self.storage_path:
            return
        
        try:
            self.storage_path.parent.mkdir(parents=True, exist_ok=True)
            
            with self._lock:
                docs = {
                    doc_id: {
                        "id": doc.id,
                        "path": doc.path,
                        "content": doc.content,
                        "embedding": doc.embedding,
                        "metadata": doc.metadata,
                        "updated_at": doc.updated_at
                    }
                    for doc_id, doc in self.documents.items()
                }
                self._dirty_count = 0
            
            # Wrap in versioned envelope
            envelope = {
                "schema_version": self._SCHEMA_VERSION,
                "documents": docs,
            }
            
            # Atomic write: write to temp file, then rename
            dir_path = self.storage_path.parent
            fd, tmp_path = tempfile.mkstemp(
                suffix=".tmp", prefix=".vectors_", dir=str(dir_path)
            )
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as f:
                    json.dump(envelope, f)
                # Atomic rename (on POSIX this is atomic; on Windows it replaces)
                os.replace(tmp_path, str(self.storage_path))
                log.debug(f"VectorStore saved: {len(docs)} docs to {self.storage_path}")
            except Exception:
                # Clean up temp file on failure
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass
                raise
        except Exception as e:
            log.error(f"VectorStore failed to save index: {e}")
    
    def _load(self):
        """Load index from disk.
        
        Handles both legacy (v0, no envelope) and versioned formats.
        If the schema version is newer than what this code understands,
        the file is discarded and a warning is logged.
        """
        if not self.storage_path or not self.storage_path.exists():
            return
        
        try:
            raw = self.storage_path.read_text(encoding="utf-8")
            data = json.loads(raw)
            
            # Detect versioned envelope vs legacy flat dict
            if isinstance(data, dict) and "schema_version" in data:
                version = data["schema_version"]
                if version > self._SCHEMA_VERSION:
                    log.warning(
                        f"VectorStore index at {self.storage_path} uses schema v{version} "
                        f"(this code supports v{self._SCHEMA_VERSION}) — discarding and re-indexing"
                    )
                    with self._lock:
                        self.documents = {}
                    return
                doc_data = data.get("documents", {})
            else:
                # Legacy format (pre-versioning): flat dict of doc_id -> doc
                log.info("VectorStore: migrating legacy (unversioned) index to versioned format")
                doc_data = data
            
            loaded = {
                doc_id: VectorDocument(**doc_fields)
                for doc_id, doc_fields in doc_data.items()
            }
            with self._lock:
                self.documents = loaded
            log.info(f"VectorStore loaded: {len(loaded)} docs from {self.storage_path}")
        except Exception as e:
            log.warning(f"VectorStore failed to load index from {self.storage_path}: {e} — starting empty")
            with self._lock:
                self.documents = {}
    
    def clear(self):
        """Clear all documents from the index."""
        with self._lock:
            self.documents = {}
            self._dirty_count = 0
        if self.storage_path and self.storage_path.exists():
            try:
                self.storage_path.unlink()
            except Exception as e:
                log.warning(f"VectorStore failed to delete index file: {e}")
