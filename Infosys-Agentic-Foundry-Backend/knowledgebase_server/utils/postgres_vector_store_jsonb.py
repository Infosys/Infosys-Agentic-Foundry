import json
import os
import numpy as np
from typing import List, Dict, Any, Optional
import asyncpg
from datetime import datetime, timezone
import logging

logger = logging.getLogger(__name__)

ENVIRONMENT = os.getenv("ENVIRONMENT", "development").lower()

# BM25 hybrid search configuration
KB_HYBRID_SEARCH_ENABLED = os.getenv("KB_HYBRID_SEARCH_ENABLED", "true").lower() == "true"
KB_BM25_WEIGHT = float(os.getenv("KB_BM25_WEIGHT", "0.3"))
KB_SEMANTIC_WEIGHT = float(os.getenv("KB_SEMANTIC_WEIGHT", "0.7"))

try:
    from rank_bm25 import BM25Okapi
    BM25_AVAILABLE = True
except ImportError:
    BM25_AVAILABLE = False
    BM25Okapi = None  # type: ignore


def _format_error(e: Exception) -> str:
    """Format exception based on environment."""
    if ENVIRONMENT == "development":
        return repr(e)
    return str(e)


class PostgresVectorStoreJSONB:

    def __init__(self, pool: asyncpg.Pool):
        self.pool = pool
        self.kb_table = "knowledgebase_table"
        self.embedding_table = "vector_embeddings_jsonb"
        logger.info(f"PostgresVectorStoreJSONB initialized (kb_table={self.kb_table}, embedding_table={self.embedding_table})")

    async def get_or_create_kb_id(self, kb_name: str, created_by: str = "system", list_of_documents: str = "") -> str:
        logger.debug(f"Looking up knowledgebase: name='{kb_name}', created_by='{created_by}'")
        async with self.pool.acquire() as conn:
            result = await conn.fetchrow(
                f"SELECT knowledgebase_id, list_of_documents FROM {self.kb_table} WHERE knowledgebase_name = $1",
                kb_name
            )
            
            if result:
                kb_id = result['knowledgebase_id']
                existing_docs = result['list_of_documents'] or ""
                
                if list_of_documents and list_of_documents not in existing_docs:
                    updated_docs = f"{existing_docs},{list_of_documents}" if existing_docs else list_of_documents
                    await conn.execute(
                        f"UPDATE {self.kb_table} SET list_of_documents = $1, updated_on = $2 WHERE knowledgebase_id = $3",
                        updated_docs, datetime.now(timezone.utc), kb_id
                    )
                    logger.info(f"Updated documents for KB '{kb_name}'")
                
                logger.info(f"Found existing KB '{kb_name}' with ID {kb_id}")
                return kb_id
            
            import uuid
            from datetime import datetime, timezone
            
            kb_id = str(uuid.uuid4())
            now = datetime.now(timezone.utc)
            
            result = await conn.fetchrow(
                f"""INSERT INTO {self.kb_table} 
                (knowledgebase_id, knowledgebase_name, list_of_documents, created_by, created_on, updated_on) 
                VALUES ($1, $2, $3, $4, $5, $6) 
                RETURNING knowledgebase_id""",
                kb_id, kb_name, list_of_documents, created_by, now, now
            )
            kb_id = result['knowledgebase_id']
            logger.info(f"Created new KB '{kb_name}' with ID {kb_id}")
            return kb_id

    async def store_embeddings(
        self,
        kb_name: str,
        chunks: List[str],
        embeddings: np.ndarray,
        metadata_list: Optional[List[Dict[str, Any]]] = None,
        created_by: str = "system",
        list_of_documents: str = ""
    ) -> Dict[str, Any]:
        logger.info(f"Storing embeddings: kb_name='{kb_name}', chunks_count={len(chunks)}, created_by='{created_by}'")
        if len(chunks) != len(embeddings):
            raise ValueError("Number of chunks must match number of embeddings")
        
        if metadata_list is None:
            metadata_list = [{}] * len(chunks)
        
        kb_id = await self.get_or_create_kb_id(kb_name, created_by, list_of_documents)
        
        insert_query = f"""
        INSERT INTO {self.embedding_table} 
        (kb_id, chunk_text, embedding, metadata, created_on, updated_on)
        VALUES ($1, $2, $3, $4, $5, $6)
        """
        
        now = datetime.now(timezone.utc)
        records = []
        
        for chunk, embedding, metadata in zip(chunks, embeddings, metadata_list):
            embedding_list = embedding.tolist() if isinstance(embedding, np.ndarray) else embedding
            
            records.append((
                kb_id,
                chunk,
                json.dumps(embedding_list),
                json.dumps(metadata),
                now,
                now
            ))
        
        async with self.pool.acquire() as conn:
            await conn.executemany(insert_query, records)
        
        logger.info(f"Stored {len(chunks)} chunks for KB '{kb_name}' (ID: {kb_id})")
        
        return {
            "status": "success",
            "kb_id": kb_id,
            "kb_name": kb_name,
            "chunks_stored": len(chunks)
        }
    
    async def store_embeddings_by_id(
        self,
        kb_id: str,
        chunks: List[str],
        embeddings: np.ndarray,
        metadata_list: Optional[List[Dict[str, Any]]] = None,
        created_by: str = "system",
        filename: str = ""
    ) -> Dict[str, Any]:
        """
        Store embeddings directly using kb_id without needing kb_name
        """
        logger.info(f"Storing embeddings by ID: kb_id='{kb_id}', chunks_count={len(chunks)}, filename='{filename}'")
        if len(chunks) != len(embeddings):
            raise ValueError("Number of chunks must match number of embeddings")
        
        if metadata_list is None:
            metadata_list = [{}] * len(chunks)
        
        # Verify kb_id exists
        async with self.pool.acquire() as conn:
            kb_exists = await conn.fetchrow(
                f"SELECT knowledgebase_id FROM {self.kb_table} WHERE knowledgebase_id = $1",
                kb_id
            )
            if not kb_exists:
                raise ValueError(f"KB ID {kb_id} does not exist")
            
            # Update list_of_documents if filename provided
            if filename:
                await conn.execute(
                    f"""UPDATE {self.kb_table} 
                    SET list_of_documents = CASE 
                        WHEN list_of_documents IS NULL OR list_of_documents = '' THEN $1
                        WHEN list_of_documents NOT LIKE '%' || $1 || '%' THEN list_of_documents || ',' || $1
                        ELSE list_of_documents
                    END,
                    updated_on = $2
                    WHERE knowledgebase_id = $3""",
                    filename, datetime.now(timezone.utc), kb_id
                )
        
        insert_query = f"""
        INSERT INTO {self.embedding_table} 
        (kb_id, chunk_text, embedding, metadata, created_on, updated_on)
        VALUES ($1, $2, $3, $4, $5, $6)
        """
        
        now = datetime.now(timezone.utc)
        records = []
        
        for chunk, embedding, metadata in zip(chunks, embeddings, metadata_list):
            embedding_list = embedding.tolist() if isinstance(embedding, np.ndarray) else embedding
            
            records.append((
                kb_id,
                chunk,
                json.dumps(embedding_list),
                json.dumps(metadata),
                now,
                now
            ))
        
        async with self.pool.acquire() as conn:
            await conn.executemany(insert_query, records)
        
        logger.info(f"Stored {len(chunks)} chunks for KB ID: {kb_id}")
        
        return {
            "status": "success",
            "kb_id": kb_id,
            "chunks_stored": len(chunks)
        }

    def _cosine_similarity(self, vec1: np.ndarray, vec2: np.ndarray) -> float:
        dot_product = np.dot(vec1, vec2)
        norm1 = np.linalg.norm(vec1)
        norm2 = np.linalg.norm(vec2)
        
        if norm1 == 0 or norm2 == 0:
            return 0.0
        
        return dot_product / (norm1 * norm2)

    async def check_file_indexed(self, kb_id: str, filename: str, file_hash: str) -> bool:
        """Return True if a chunk with this exact file_hash already exists for the given kb_id + filename."""
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(
                f"""SELECT id FROM {self.embedding_table}
                    WHERE kb_id = $1
                    AND metadata->>'filename' = $2
                    AND metadata->>'file_hash' = $3
                    LIMIT 1""",
                kb_id, filename, file_hash
            )
        return row is not None

    async def delete_file_chunks(self, kb_id: str, filename: str) -> int:
        """Delete all chunks for a specific filename within a KB. Returns the number deleted."""
        async with self.pool.acquire() as conn:
            result = await conn.execute(
                f"""DELETE FROM {self.embedding_table}
                    WHERE kb_id = $1 AND metadata->>'filename' = $2""",
                kb_id, filename
            )
        # asyncpg returns "DELETE N" — extract the count
        try:
            return int(result.split()[-1])
        except (ValueError, IndexError):
            return 0

    async def semantic_search(
        self,
        query_embedding: np.ndarray,
        kb_id: Optional[str] = None,
        top_k: int = 5,
        query_text: Optional[str] = None,
        hybrid: Optional[bool] = None,
    ) -> List[Dict[str, Any]]:
        use_hybrid = (KB_HYBRID_SEARCH_ENABLED if hybrid is None else hybrid) and BM25_AVAILABLE and bool(query_text)
        logger.info(f"Semantic search: kb_id='{kb_id}', top_k={top_k}, hybrid={use_hybrid}")

        select_query = f"SELECT id, kb_id, chunk_text, embedding, metadata FROM {self.embedding_table} WHERE 1=1"
        params: list = []
        if kb_id:
            params.append(kb_id)
            select_query += f" AND kb_id = ${len(params)}"

        async with self.pool.acquire() as conn:
            rows = await conn.fetch(select_query, *params)

        if not rows:
            logger.info("Semantic search: no rows found")
            return []

        query_emb = np.array(query_embedding)

        # Semantic scores for every row
        semantic_scores = [
            float(self._cosine_similarity(query_emb, np.array(json.loads(row['embedding']))))
            for row in rows
        ]

        # BM25 scores (only when hybrid is active)
        bm25_scores_norm = [0.0] * len(rows)
        if use_hybrid:
            corpus = [row['chunk_text'].lower().split() for row in rows]
            bm25 = BM25Okapi(corpus)
            raw = bm25.get_scores(query_text.lower().split())
            bm25_max = float(max(raw)) if max(raw) > 0 else 1.0
            bm25_scores_norm = [float(s) / bm25_max for s in raw]

        # Weighted combination
        bw = KB_BM25_WEIGHT if use_hybrid else 0.0
        sw = KB_SEMANTIC_WEIGHT if use_hybrid else 1.0
        total_w = bw + sw
        bw, sw = bw / total_w, sw / total_w

        results = []
        for i, row in enumerate(rows):
            sem = semantic_scores[i]
            bm = bm25_scores_norm[i]
            combined = bw * bm + sw * sem
            try:
                metadata = json.loads(row['metadata']) if row['metadata'] else {}
            except Exception:
                metadata = {}
            results.append({
                'id': row['id'],
                'text': row['chunk_text'],
                'metadata': metadata,
                'kb_id': row['kb_id'],
                'similarity': sem,
                'bm25_score': round(bm, 4),
                'combined_score': round(combined, 4),
            })

        results.sort(key=lambda x: x['combined_score'], reverse=True)
        top_results = results[:top_k]
        top_score = f"{top_results[0]['combined_score']:.4f}" if top_results else "N/A"
        logger.info(f"Search done: candidates={len(rows)}, returned={len(top_results)}, top_score={top_score}")
        return top_results
