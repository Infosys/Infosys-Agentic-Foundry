"""
Redis-PostgreSQL Data Manager

This module provides a data management system that:
1. Stores data initially in Redis for short-term memory/caching
2. Persists data to PostgreSQL when cache reaches a threshold
3. Syncs cache with database contents for optimal performance

Features:
- Automatic batch persistence to PostgreSQL
- Cache invalidation and refresh
- Configurable thresholds and TTL
- Connection pooling and error handling
- Data serialization/deserialization
"""

import json
import threading
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any, Union
from dataclasses import dataclass, asdict
import redis
from psycopg2.pool import ThreadedConnectionPool
from psycopg2.extras import RealDictCursor, execute_values
import os
from contextlib import contextmanager
from telemetry_wrapper import logger as log

logger = log


@dataclass
class CacheRecord:
    """Data class for cache records"""
    id: str
    data: Dict[str, Any]
    created_at: datetime
    updated_at: datetime
    category: str = "default"
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization"""
        return {
            'id': self.id,
            'data': self.data,
            'created_at': self.created_at.isoformat(),
            'updated_at': self.updated_at.isoformat(),
            'category': self.category
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'CacheRecord':
        """Create from dictionary"""
        return cls(
            id=data['id'],
            data=data['data'],
            created_at=datetime.fromisoformat(data['created_at']),
            updated_at=datetime.fromisoformat(data['updated_at']),
            category=data.get('category', 'default')
        )


class RedisPostgresManager:
    """
    Manages data flow between Redis cache and PostgreSQL database
    """
    
    def __init__(self, 
            redis_host=os.getenv("REDIS_HOST"),
            redis_port=int(os.getenv("REDIS_PORT")),
            redis_db=int(os.getenv("REDIS_DB")),
            redis_password=os.getenv("REDIS_PASSWORD"),
            postgres_host=os.getenv("POSTGRESQL_HOST"),
            postgres_port=int(os.getenv("POSTGRESQL_PORT")),
            postgres_db="agentic_workflow_as_service_database",
            postgres_user=os.getenv("POSTGRESQL_USER"),
            postgres_password=os.getenv("POSTGRESQL_PASSWORD"),
            postgres_table="memory_records",
            cache_threshold: int = 100,
            cache_ttl: int = 3600):
        """
        Initialize the Redis-PostgreSQL manager
        
        Args:
            redis_host: Redis server host
            redis_port: Redis server port
            redis_db: Redis database number
            redis_password: Redis PWD
            postgres_host: PostgreSQL server host
            postgres_port: PostgreSQL server port
            postgres_db: PostgreSQL database name
            postgres_user: PostgreSQL username
            postgres_password: PostgreSQL PWD
            postgres_table: PostgreSQL table name for storing cache records
            cache_threshold: Number of records before persistence to DB
            cache_ttl: Cache TTL in seconds (default 1 hour)
        """
        self.cache_threshold = cache_threshold
        self.cache_ttl = cache_ttl
        self.postgres_table = postgres_table
        self.cache_key_prefix = "cache_record:"
        self.cache_counter_key = "cache_record_count"
        self.cache_index_key = "cache_record_index"

        
        # Initialize Redis connection
        self.redis_client = redis.Redis(
            host=redis_host,
            port=redis_port,
            db=redis_db,
            password=redis_password,
            decode_responses=True,
            socket_keepalive=True,
            socket_keepalive_options={}
        )
        
        # Initialize PostgreSQL connection pool
        self.postgres_pool = ThreadedConnectionPool(
            minconn=1,
            maxconn=20,
            host=postgres_host,
            port=postgres_port,
            database=postgres_db,
            user=postgres_user,
            password=postgres_password
        )
        
        # Initialize database schema
        self._init_database_schema()
        
        logger.info("RedisPostgresManager initialized successfully")
    
    @contextmanager
    def get_db_connection(self):
        """Context manager for database connections"""
        conn = None
        try:
            conn = self.postgres_pool.getconn()
            yield conn
        finally:
            if conn:
                self.postgres_pool.putconn(conn)
    
    def _init_database_schema(self):
        """Initialize PostgreSQL table schema"""
        create_table_sql = f"""
        CREATE TABLE IF NOT EXISTS {self.postgres_table} (
            id VARCHAR(255) PRIMARY KEY,
            data JSONB NOT NULL,
            created_at TIMESTAMP WITH TIME ZONE NOT NULL,
            updated_at TIMESTAMP WITH TIME ZONE NOT NULL,
            category VARCHAR(100) DEFAULT 'default'
        );
        
        CREATE INDEX IF NOT EXISTS idx_{self.postgres_table}_category ON {self.postgres_table} (category);
        CREATE INDEX IF NOT EXISTS idx_{self.postgres_table}_created_at ON {self.postgres_table} (created_at);
        CREATE INDEX IF NOT EXISTS idx_{self.postgres_table}_updated_at ON {self.postgres_table} (updated_at);
        CREATE INDEX IF NOT EXISTS idx_{self.postgres_table}_data_gin ON {self.postgres_table} USING gin(data);
        """
        
        try:
            with self.get_db_connection() as conn:
                with conn.cursor() as cursor:
                    # Execute each statement separately for better error handling
                    statements = create_table_sql.strip().split(';')
                    for statement in statements:
                        statement = statement.strip()
                        if statement:
                            cursor.execute(statement)
                    conn.commit()
            logger.info(f"Database schema for table '{self.postgres_table}' initialized successfully")
        except Exception as e:
            logger.error(f"Error initializing database schema: {e}")
            raise
    
    async def add_record(self, record_id: str, data: Dict[str, Any], category: str = "default") -> bool:
        """
        Add a new record to cache
        
        Args:
            record_id: Unique identifier for the record
            data: Data to store
            category: Category for organizing records
            
        Returns:
            True if successful, False otherwise
        """
        try:
            now = datetime.now()
            record = CacheRecord(
                id=record_id,
                data=data,
                created_at=now,
                updated_at=now,
                category=category
            )
            
            # Store in Redis
            cache_key = f"{self.cache_key_prefix}{record_id}"
            record_json = json.dumps(record.to_dict())
            
            # Use pipeline for atomic operations
            pipe = self.redis_client.pipeline()
            pipe.setex(cache_key, self.cache_ttl, record_json)
            pipe.sadd(self.cache_index_key, record_id)
            pipe.incr(self.cache_counter_key)
            results = pipe.execute()
            
            if all(results):
                log.info(f"Record {record_id} added to cache")
                
                # Check if we need to persist to database
                current_count = await self.get_cache_count()
                if current_count >= self.cache_threshold:
                    await self._persist_cache_to_database()
                
                return True
            else:
                log.warning(f"Failed to add record {record_id} to cache")
                return False
                
        except Exception as e:
            log.error(f"Error adding record {record_id}: {e}")
            return False
    
    async def get_record(self, record_id: str) -> Optional[CacheRecord]:
        """
        Get a record by ID (checks cache first, then database)
        
        Args:
            record_id: Record identifier
            
        Returns:
            CacheRecord if found, None otherwise
        """
        try:
            # Check cache first
            cache_key = f"{self.cache_key_prefix}{record_id}"
            cached_data = self.redis_client.get(cache_key)
            
            if cached_data:
                record_dict = json.loads(cached_data)
                return CacheRecord.from_dict(record_dict)
            
            # Check database if not in cache
            return await self._get_record_from_database(record_id)
            
        except Exception as e:
            logger.error(f"Error getting record {record_id}: {e}")
            return None
    
    async def delete_record(self, record_id: str) -> bool:
        """
        Delete a record from both cache and database
        
        Args:
            record_id: Record identifier
            
        Returns:
            True if successful, False otherwise
        """
        try:
            cache_key = f"{self.cache_key_prefix}{record_id}"
            
            # Remove from cache
            pipe = self.redis_client.pipeline()
            pipe.delete(cache_key)
            pipe.srem(self.cache_index_key, record_id)
            pipe.decr(self.cache_counter_key)
            cache_results = pipe.execute()
            
            # Remove from database
            db_success = await self._delete_record_from_database(record_id)
            success = any(cache_results) or db_success
            if success:
                logger.info(f"Record {record_id} deleted")
            
            return success
            
        except Exception as e:
            logger.error(f"Error deleting record {record_id}: {e}")
            return False
    
    async def get_records_by_category(self, category: str, limit: int = 100) -> List[CacheRecord]:
        """
        Get records by category (checks both cache and database)
        
        Args:
            category: Category to filter by
            limit: Maximum number of records to return
            
        Returns:
            List of CacheRecord objects
        """
        records = []
        
        try:
            # Get from cache
            cache_records = await self._get_cache_records_by_category(category)
            records.extend(cache_records)
            
            # Get from database if we need more
            if len(records) < limit:
                db_records = await self._get_database_records_by_category(
                    category, 
                    limit - len(records)
                )
                # Avoid duplicates
                cached_ids = {r.id for r in records}
                for db_record in db_records:
                    if db_record.id not in cached_ids:
                        records.append(db_record)
            
            return records[:limit]
            
        except Exception as e:
            logger.error(f"Error getting records by category {category}: {e}")
            return []
    
    async def get_cache_count(self) -> int:
        """Get current number of records in cache"""
        try:
            count = self.redis_client.get(self.cache_counter_key)
            return int(count) if count else 0
        except Exception as e:
            logger.error(f"Error getting cache count: {e}")
            return 0
    
    async def get_cache_stats(self) -> Dict[str, Any]:
        """Get cache statistics"""
        try:
            count = await self.get_cache_count()
            index_size = self.redis_client.scard(self.cache_index_key)
            memory_usage = self.redis_client.memory_usage(self.cache_index_key) or 0
            
            return {
                'record_count': count,
                'index_size': index_size,
                'memory_usage_bytes': memory_usage,
                'threshold': self.cache_threshold,
                'ttl_seconds': self.cache_ttl
            }
        except Exception as e:
            logger.error(f"Error getting cache stats: {e}")
            return {}
    
    async def _persist_cache_to_database(self) -> bool:
        """
        Persist all cache records to PostgreSQL database
        """
        try:
            logger.info("Starting cache persistence to database")
            
            # Get all cached record IDs
            record_ids = self.redis_client.smembers(self.cache_index_key)
            if not record_ids:
                logger.info("No records to persist")
                return True
            
            # Get all cached records
            records_to_persist = []
            for record_id in record_ids:
                cache_key = f"{self.cache_key_prefix}{record_id}"
                cached_data = self.redis_client.get(cache_key)
                if cached_data:
                    record_dict = json.loads(cached_data)
                    records_to_persist.append(record_dict)
            
            if not records_to_persist:
                logger.info("No valid records found in cache")
                return True
            
            # Batch insert to database
            with self.get_db_connection() as conn:
                with conn.cursor() as cursor:
                    # Prepare data for batch insert
                    insert_data = [
                        (
                            record['id'],
                            json.dumps(record['data']),
                            record['created_at'],
                            record['updated_at'],
                            record['category']
                        )
                        for record in records_to_persist
                    ]
                    
                    # Use ON CONFLICT to handle duplicates
                    insert_sql = f"""
                    INSERT INTO {self.postgres_table} (id, data, created_at, updated_at, category)
                    VALUES %s
                    ON CONFLICT (id) DO UPDATE SET
                        data = EXCLUDED.data,
                        updated_at = EXCLUDED.updated_at,
                        category = EXCLUDED.category
                    """
                    
                    execute_values(cursor, insert_sql, insert_data)
                    conn.commit()
            
            logger.info(f"Successfully persisted {len(records_to_persist)} records to database")
            
            # Refresh cache with database contents
            await self._refresh_cache_from_database()
            
            return True
            
        except Exception as e:
            logger.error(f"Error persisting cache to database: {e}")
            return False
    
    async def _refresh_cache_from_database(self, limit: int = None) -> bool:
        """
        Refresh cache with recent records from database
        
        Args:
            limit: Maximum number of records to load (default: cache_threshold)
        """
        try:
            if limit is None:
                limit = self.cache_threshold
            
            logger.info(f"Refreshing cache with {limit} recent records from database")
            
            # Clear current cache
            await self._clear_cache()
            
            # Get recent records from database
            with self.get_db_connection() as conn:
                with conn.cursor(cursor_factory=RealDictCursor) as cursor:
                    cursor.execute(f"""
                        SELECT id, data, created_at, updated_at, category
                        FROM {self.postgres_table}
                        ORDER BY updated_at DESC
                        LIMIT %s
                    """, (limit,))
                    
                    records = cursor.fetchall()
            
            # Load records into cache
            pipe = self.redis_client.pipeline()
            record_count = 0
            
            for record in records:
                cache_record = CacheRecord(
                    id=record['id'],
                    data=record['data'],
                    created_at=record['created_at'],
                    updated_at=record['updated_at'],
                    category=record['category']
                )
                
                cache_key = f"{self.cache_key_prefix}{record['id']}"
                record_json = json.dumps(cache_record.to_dict())
                
                pipe.setex(cache_key, self.cache_ttl, record_json)
                pipe.sadd(self.cache_index_key, record['id'])
                record_count += 1
            
            # Set counter
            pipe.set(self.cache_counter_key, record_count)
            pipe.execute()
            
            logger.info(f"Cache refreshed with {record_count} records")
            return True
            
        except Exception as e:
            logger.error(f"Error refreshing cache from database: {e}")
            return False
    
    async def _clear_cache(self):
        """Clear all cache data"""
        try:
            # Get all cache keys
            record_ids = self.redis_client.smembers(self.cache_index_key)
            if record_ids:
                cache_keys = [f"{self.cache_key_prefix}{rid}" for rid in record_ids]
                self.redis_client.delete(*cache_keys)
            
            # Clear index and counter
            self.redis_client.delete(self.cache_index_key, self.cache_counter_key)
            
        except Exception as e:
            logger.error(f"Error clearing cache: {e}")
    
    async def _get_record_from_database(self, record_id: str) -> Optional[CacheRecord]:
        """Get a single record from database"""
        try:
            with self.get_db_connection() as conn:
                with conn.cursor(cursor_factory=RealDictCursor) as cursor:
                    cursor.execute(f"""
                        SELECT id, data, created_at, updated_at, category
                        FROM {self.postgres_table}
                        WHERE id = %s
                    """, (record_id,))
                    
                    record = cursor.fetchone()
                    if record:
                        return CacheRecord(
                            id=record['id'],
                            data=record['data'],
                            created_at=record['created_at'],
                            updated_at=record['updated_at'],
                            category=record['category']
                        )
            return None
            
        except Exception as e:
            logger.error(f"Error getting record {record_id} from database: {e}")
            return None
    
    async def _delete_record_from_database(self, record_id: str) -> bool:
        """Delete a record from database"""
        try:
            with self.get_db_connection() as conn:
                with conn.cursor() as cursor:
                    del_data = f"DELETE FROM {self.postgres_table} WHERE id = %s"
                    cursor.execute(del_data, (record_id,))
                    conn.commit()
                    return cursor.rowcount > 0
                    
        except Exception as e:
            logger.error(f"Error deleting record {record_id} from database: {e}")
            return False

    async def _update_record_in_database(self, record: CacheRecord) -> bool:
        """Update a record in database"""
        try:
            with self.get_db_connection() as conn:
                with conn.cursor() as cursor:
                    sql_res = f"UPDATE {self.postgres_table} SET data = %s WHERE id = %s"
                    cursor.execute(sql_res, (json.dumps(record.data), record.id))
                    conn.commit()
                    return cursor.rowcount > 0
                    
        except Exception as e:
            logger.error(f"Error updating record {record.id} in database: {e}")
            return False
    
    async def update_record(self, record: CacheRecord) -> bool:
        """
        Update a record in both cache and database
        """
        try:
            record.updated_at = datetime.now()
            # Update in cache
            cache_key = f"{self.cache_key_prefix}{record.id}"
            record_json = json.dumps(record.to_dict())
            cache_updated = self.redis_client.setex(cache_key, self.cache_ttl, record_json)
            
            # Update in database
            db_updated = await self._update_record_in_database(record)
            
            return cache_updated and db_updated
            
        except Exception as e:
            logger.error(f"Error updating record {record.id}: {e}")
            return False
    
    async def _get_cache_records_by_category(self, category: str) -> List[CacheRecord]:
        """Get records by category from cache"""
        records = []
        try:
            record_ids = self.redis_client.smembers(self.cache_index_key)
            for record_id in record_ids:
                cache_key = f"{self.cache_key_prefix}{record_id}"
                cached_data = self.redis_client.get(cache_key)
                if cached_data:
                    record_dict = json.loads(cached_data)
                    if record_dict.get('category') == category:
                        records.append(CacheRecord.from_dict(record_dict))
        except Exception as e:
            logger.error(f"Error getting cache records by category {category}: {e}")
        
        return records
    
    async def _get_database_records_by_category(self, category: str, limit: int) -> List[CacheRecord]:
        """Get records by category from database"""
        records = []
        try:
            with self.get_db_connection() as conn:
                with conn.cursor(cursor_factory=RealDictCursor) as cursor:
                    cursor.execute(f"""
                        SELECT id, data, created_at, updated_at, category
                        FROM {self.postgres_table}
                        WHERE category = %s
                        ORDER BY updated_at DESC
                        LIMIT %s
                    """, (category, limit))
                    
                    for record in cursor.fetchall():
                        records.append(CacheRecord(
                            id=record['id'],
                            data=record['data'],
                            created_at=record['created_at'],
                            updated_at=record['updated_at'],
                            category=record['category']
                        ))
        except Exception as e:
            logger.error(f"Error getting database records by category {category}: {e}")
        
        return records
    
    async def close(self):
        """Close all connections"""
        try:
            self.redis_client.close()
            self.postgres_pool.closeall()
            logger.info("All connections closed")
        except Exception as e:
            logger.error(f"Error closing connections: {e}")


class TimedRedisPostgresManager:
    """Extended Redis-PostgreSQL manager with time-based persistence"""
    
    def __init__(self, base_manager: 'RedisPostgresManager', time_threshold_minutes: int = 15):
        self.base_manager = base_manager
        self.time_threshold = timedelta(minutes=time_threshold_minutes)
        self.last_persistence_time = datetime.now()
        self._lock = threading.Lock()
        
    async def add_record(self, record_id: str, data: Dict[str, Any], category: str = "default") -> bool:
        """Add record with time-based persistence check"""
        with self._lock:
            result = await self.base_manager.add_record(record_id, data, category)
            
            # Check if time threshold has passed
            current_time = datetime.now()
            if current_time - self.last_persistence_time >= self.time_threshold:
                logger.info("Time threshold reached, persisting to PostgreSQL")
                await self.base_manager._persist_cache_to_database()
                self.last_persistence_time = current_time
                
            return result
    
    async def get_records_by_category(self, category: str, limit: int = 100) -> List[CacheRecord]:
        """Get records from both cache and database"""
        return await self.base_manager.get_records_by_category(category, limit)
    
    async def update_record_in_database(self, record: CacheRecord) -> bool:
        """Update a record in both cache and database"""
        return await self.base_manager.update_record(record)
    
    async def get_record(self, record_id: str) -> Optional[CacheRecord]:
        """Get single record"""
        return await self.base_manager.get_record(record_id)
    
    async def delete_record(self, record_id: str) -> bool:
        """Delete a record from both cache and database"""
        return await self.base_manager.delete_record(record_id)
    
    async def get_cache_count(self) -> int:
        """Get current number of records in cache"""
        return await self.base_manager.get_cache_count()
    
    async def get_cache_stats(self) -> Dict[str, Any]:
        """Get cache statistics"""
        return await self.base_manager.get_cache_stats()
    
    async def force_persistence(self):
        """Force immediate persistence to PostgreSQL"""
        with self._lock:
            await self.base_manager._persist_cache_to_database()
            self.last_persistence_time = datetime.now()
    
    async def close(self):
        """Close all connections"""
        await self.base_manager.close()


async def create_manager_from_env() -> RedisPostgresManager:
    """
    Create manager instance from environment variables
    """
    return RedisPostgresManager(
            redis_host=os.getenv("REDIS_HOST"),
            redis_port=int(os.getenv("REDIS_PORT")),
            redis_db=int(os.getenv("REDIS_DB")),
            redis_password=os.getenv("REDIS_PASSWORD"),
            postgres_host=os.getenv("POSTGRESQL_HOST"),
            postgres_port=int(os.getenv("POSTGRESQL_PORT")),
            postgres_db="agentic_workflow_as_service_database",
            postgres_user=os.getenv("POSTGRESQL_USER"),
            postgres_password=os.getenv("POSTGRESQL_PASSWORD"),
            postgres_table="memory_records",
            cache_threshold=int(os.getenv('CACHE_THRESHOLD', 100)),
            cache_ttl=int(os.getenv('CACHE_TTL', 3600))
    )


async def create_timed_manager_from_env(time_threshold_minutes: int = 15) -> TimedRedisPostgresManager:
    """
    Create timed manager instance from environment variables
    
    Args:
        time_threshold_minutes: Time threshold in minutes for automatic persistence
    """
    base_manager = await create_manager_from_env()
    return TimedRedisPostgresManager(base_manager, time_threshold_minutes)


async def main():
    try:
        # Create standard manager
        manager = await create_manager_from_env()
        # Create timed manager with 15-minute persistence interval
        timed_manager = await create_timed_manager_from_env(time_threshold_minutes=15)
        log.info("Testing TimedRedisPostgresManager...")
        # Add your strings with this method using timed manager
        success = await timed_manager.add_record("1", { "string": f"semantic memory string 1"}, "agent0_semanticmemory")
        if not success:
            log.error("Failed to add record 1")
            return
        success = await timed_manager.add_record("2", { "string": f"semantic memory string 2"}, "agent0_semanticmemory")
        if not success:
            log.error("Failed to add record 2")
            return
        success = await timed_manager.add_record("3", { "string": f"thumbs up string"}, "agent0_episodicmemory")
        if not success:
            log.error("Failed to add record 3")
            return
        success = await timed_manager.add_record("4", { "string": f"thumbs down string"}, "agent0_episodicmemory")
        if not success:
            log.error("Failed to add record 4")
            return
        # Get records for vector embeddings and semantic search
        process_for_embeddings_episodic = await timed_manager.get_records_by_category("agent0_episodicmemory")
        log.info(f"Episodic memory records: {process_for_embeddings_episodic}")
        process_for_embeddings_semantics = await timed_manager.get_records_by_category("agent0_semanticmemory")
        log.info(f"Semantic memory records: {process_for_embeddings_semantics}")
        # Display cache statistics
        cache_stats = await timed_manager.get_cache_stats()
        log.info(f"Cache statistics: {cache_stats}")
        # Force persistence for demonstration
        log.info("Forcing persistence to PostgreSQL...")
        await timed_manager.force_persistence()
        log.info("Persistence completed.")
        # Close connections
        await timed_manager.close()
    except Exception as e:
        log.error(f"Error in main: {e}")


if __name__ == "__main__":
    main()
