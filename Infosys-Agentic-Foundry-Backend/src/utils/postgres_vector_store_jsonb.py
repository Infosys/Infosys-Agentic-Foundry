import json
import numpy as np
from typing import List, Dict, Any, Optional
import asyncpg
from datetime import datetime, timezone
from telemetry_wrapper import logger as log


class PostgresVectorStoreJSONB:

    def __init__(self, pool: asyncpg.Pool):
        self.pool = pool
        self.table_name = "vector_embeddings_jsonb"

    async def create_table(self):
        create_table_query = f"""
        CREATE TABLE IF NOT EXISTS {self.table_name} (
            id SERIAL PRIMARY KEY,
            kb_id TEXT NOT NULL,
            chunk_text TEXT NOT NULL,
            embedding JSONB NOT NULL,
            metadata JSONB DEFAULT '{{}}',
            created_on TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
            updated_on TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
        );
        """
        
        create_indexes_query = f"""
        CREATE INDEX IF NOT EXISTS idx_vector_embeddings_jsonb_kb_id 
        ON {self.table_name} (kb_id);
        """
        
        async with self.pool.acquire() as conn:
            await conn.execute(create_table_query)
            await conn.execute(create_indexes_query)
            log.info(f"Table '{self.table_name}' and indexes created successfully")

    async def store_embeddings(
        self,
        kb_id: str,
        chunks: List[str],
        embeddings: np.ndarray,
        metadata_list: Optional[List[Dict[str, Any]]] = None
    ) -> Dict[str, Any]:
        if len(chunks) != len(embeddings):
            raise ValueError("Number of chunks must match number of embeddings")
        
        if metadata_list is None:
            metadata_list = [{}] * len(chunks)
        
        insert_query = f"""
        INSERT INTO {self.table_name} 
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
        
        log.info(f"Stored {len(chunks)} chunks for KB (ID: {kb_id})")
        
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

    async def semantic_search(
        self,
        query_embedding: np.ndarray,
        kb_id: Optional[str] = None,
        top_k: int = 5
    ) -> List[Dict[str, Any]]:
        select_query = f"""
        SELECT id, kb_id, chunk_text, embedding, metadata
        FROM {self.table_name}
        WHERE 1=1
        """
        params = []
        
        if kb_id:
            params.append(kb_id)
            select_query += f" AND kb_id = ${len(params)}"
        
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(select_query, *params)
        
        results = []
        for row in rows:
            stored_embedding = np.array(json.loads(row['embedding']))
            similarity = self._cosine_similarity(query_embedding, stored_embedding)
            
            results.append({
                'id': row['id'],
                'text': row['chunk_text'],
                'metadata': json.loads(row['metadata']) if row['metadata'] else {},
                'kb_id': row['kb_id'],
                'similarity': float(similarity)
            })
        
        results.sort(key=lambda x: x['similarity'], reverse=True)
        return results[:top_k]

    async def delete_kb(self, kb_id: str) -> int:
        delete_query = f"DELETE FROM {self.table_name} WHERE kb_id = $1"
        params = [kb_id]
        
        async with self.pool.acquire() as conn:
            result = await conn.execute(delete_query, *params)
        
        deleted_count = int(result.split()[-1]) if result else 0
        log.info(f"Deleted {deleted_count} embeddings for KB")
        
        return deleted_count

    async def get_kb_stats(self, kb_id: str) -> Dict[str, Any]:
        stats_query = f"""
        SELECT 
            COUNT(*) as chunk_count,
            kb_id,
            MIN(created_on) as first_added,
            MAX(updated_on) as last_updated
        FROM {self.table_name}
        WHERE kb_id = $1
        GROUP BY kb_id
        """
        
        params = [kb_id]
        
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(stats_query, *params)
        
        if not row:
            return {
                "chunk_count": 0,
                "kb_id": kb_id
            }
        
        return {
            "chunk_count": row['chunk_count'],
            "kb_id": row['kb_id'],
            "first_added": row['first_added'],
            "last_updated": row['last_updated']
        }
