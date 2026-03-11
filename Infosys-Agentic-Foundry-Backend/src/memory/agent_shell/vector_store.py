# © 2024-25 Infosys Limited, Bangalore, India. All Rights Reserved.
"""
VectorStore - Local vector database for semantic search.

Uses a simple in-memory store with file persistence.
For production, can be replaced with LanceDB or ChromaDB.
"""

import json
import hashlib
import math
from pathlib import Path
from typing import List, Dict, Any, Optional
from dataclasses import dataclass, field
from datetime import datetime, timezone


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
    For production, use sentence-transformers:
        from sentence_transformers import SentenceTransformer
        model = SentenceTransformer('all-MiniLM-L6-v2')
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
    """
    
    def __init__(
        self,
        storage_path: Optional[Path] = None,
        embedder: Optional[SimpleEmbedder] = None
    ):
        """
        Initialize vector store.
        
        Args:
            storage_path: Path to persist the index (optional).
            embedder: Embedder instance (uses SimpleEmbedder if not provided).
        """
        self.storage_path = Path(storage_path) if storage_path else None
        self.embedder = embedder or SimpleEmbedder()
        self.documents: Dict[str, VectorDocument] = {}
        
        # Load existing index
        if self.storage_path and self.storage_path.exists():
            self._load()
    
    def _cosine_similarity(self, a: List[float], b: List[float]) -> float:
        """Calculate cosine similarity between two vectors."""
        dot = sum(x * y for x, y in zip(a, b))
        mag_a = math.sqrt(sum(x * x for x in a)) or 1.0
        mag_b = math.sqrt(sum(x * x for x in b)) or 1.0
        return dot / (mag_a * mag_b)
    
    def upsert(self, path: str, content: str, metadata: Optional[Dict] = None):
        """
        Add or update a document in the index.
        
        Args:
            path: File path (used as ID).
            content: Document content.
            metadata: Optional metadata.
        """
        doc_id = hashlib.sha256(path.encode()).hexdigest()
        embedding = self.embedder.encode(content)
        
        self.documents[doc_id] = VectorDocument(
            id=doc_id,
            path=path,
            content=content,
            embedding=embedding,
            metadata=metadata or {},
            updated_at=_utc_now()
        )
        
        # Persist
        if self.storage_path:
            self._save()
    
    def delete(self, path: str):
        """Remove a document from the index."""
        doc_id = hashlib.sha256(path.encode()).hexdigest()
        if doc_id in self.documents:
            del self.documents[doc_id]
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
        Search for documents similar to the query.
        
        Args:
            query: Natural language query.
            path_prefix: Optional path prefix to filter results.
            top_k: Number of results to return.
            min_score: Minimum similarity score threshold.
            
        Returns:
            List of SearchResult objects.
        """
        if not self.documents:
            return []
        
        query_embedding = self.embedder.encode(query)
        
        # Calculate similarities
        results = []
        for doc in self.documents.values():
            # Filter by path prefix
            if path_prefix and not doc.path.startswith(path_prefix):
                continue
            
            score = self._cosine_similarity(query_embedding, doc.embedding)
            
            # Filter by minimum score
            if score < min_score:
                continue
            
            # Create snippet (first 200 chars)
            snippet = doc.content[:200].replace("\n", " ")
            if len(doc.content) > 200:
                snippet += "..."
            
            results.append(SearchResult(
                path=doc.path,
                content=doc.content,
                score=score,
                snippet=snippet
            ))
        
        # Sort by score descending
        results.sort(key=lambda x: x.score, reverse=True)
        
        return results[:top_k]
    
    def get_stats(self) -> Dict[str, Any]:
        """Get statistics about the index."""
        return {
            "total_documents": len(self.documents),
            "storage_path": str(self.storage_path) if self.storage_path else None,
            "paths": [doc.path for doc in self.documents.values()]
        }
    
    def _save(self):
        """Persist index to disk."""
        if not self.storage_path:
            return
        
        self.storage_path.parent.mkdir(parents=True, exist_ok=True)
        
        data = {
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
        
        self.storage_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    
    def _load(self):
        """Load index from disk."""
        if not self.storage_path or not self.storage_path.exists():
            return
        
        try:
            data = json.loads(self.storage_path.read_text(encoding="utf-8"))
            self.documents = {
                doc_id: VectorDocument(**doc_data)
                for doc_id, doc_data in data.items()
            }
        except Exception:
            self.documents = {}
    
    def clear(self):
        """Clear all documents from the index."""
        self.documents = {}
        if self.storage_path and self.storage_path.exists():
            self.storage_path.unlink()
