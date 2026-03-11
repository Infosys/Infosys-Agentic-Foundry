import json
import numpy as np
from typing import List, Dict, Any, Optional
import asyncpg
from datetime import datetime, timezone
import logging

logger = logging.getLogger(__name__)


class PostgresVectorStoreJSONB:

    def __init__(self, pool: asyncpg.Pool):
        self.pool = pool
        self.kb_table = "knowledgebase_table"
        self.embedding_table = "vector_embeddings_jsonb"

    async def get_or_create_kb_id(self, kb_name: str, created_by: str = "system", list_of_documents: str = "") -> str:
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

    async def semantic_search(
        self,
        query_embedding: np.ndarray,
        kb_id: Optional[str] = None,
        top_k: int = 5
    ) -> List[Dict[str, Any]]:
        select_query = f"""
        SELECT id, kb_id, chunk_text, embedding, metadata
        FROM {self.embedding_table}
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
