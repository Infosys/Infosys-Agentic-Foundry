import os
import sys
import asyncio
import asyncpg
import logging
from datetime import datetime, timedelta
from typing import List, Dict, Optional, Tuple, Set
from dataclasses import dataclass
from dotenv import load_dotenv
import json
import re
import uuid
from contextlib import asynccontextmanager
from .recycle_bin_manager import RecycleBinManager, parse_thread_id, check_table_exists
load_dotenv()


logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)


@dataclass
class CleanupStats:
    """Statistics for cleanup operations"""
    checkpoints_deleted: int = 0
    checkpoint_writes_deleted: int = 0
    checkpoint_blobs_deleted: int = 0
    checkpoints_backed_up: int = 0
    checkpoint_writes_backed_up: int = 0
    checkpoint_blobs_backed_up: int = 0
    old_recycle_records_deleted: int = 0
    total_batches: int = 0
    execution_time: float = 0.0
    errors_count: int = 0


class LangGraphTablesCleaner:
    """
    Manages cleanup of LangGraph checkpoint tables by removing data older than specified days.
    """
    
    def __init__(self, days_to_keep: int = 30, batch_size: int = 1000, dry_run: bool = False):
        """
        Initialize the cleaner with configuration parameters.
        
        Args:
            days_to_keep: Number of days of data to retain (default: 30)
            batch_size: Number of records to process per batch (default: 1000)
            dry_run: If True, only analyze without actual deletion (default: False)
        """
        self.days_to_keep = days_to_keep
        self.batch_size = batch_size
        self.dry_run = dry_run
        self.max_batches = None  
        self.quiet_mode = False  
        from datetime import timezone
        self.cutoff_date = datetime.now(timezone.utc) - timedelta(days=days_to_keep)
        self.recycle_manager = RecycleBinManager(days_to_keep_in_recycle=45, dry_run=dry_run) ###333
        self.db_url = os.getenv("POSTGRESQL_DATABASE_URL", "")
        
        if not self.db_url:
            raise ValueError("POSTGRESQL_DATABASE_URL environment variable is required")
        
        logger.info(f"Initialized LangGraph cleaner:")
        logger.info(f"  - Days to keep: {self.days_to_keep}")
        logger.info(f"  - Cutoff date: {self.cutoff_date}")
        logger.info(f"  - Batch size: {self.batch_size}")
        logger.info(f"  - Dry run mode: {self.dry_run}")
        logger.info(f"  - Recycle bin enabled: True")

    @asynccontextmanager
    async def get_db_connection(self):
        """Context manager for database connections with proper cleanup."""
        conn = None
        try:
            conn = await asyncpg.connect(self.db_url)
            yield conn
        except Exception as e:
            logger.error(f"Database connection error: {e}")
            raise
        finally:
            if conn:
                await conn.close()

    def extract_timestamp_from_checkpoint_id(self, checkpoint_id: str) -> Optional[datetime]:
        """
        Attempt to extract timestamp from checkpoint_id.
        
        LangGraph checkpoint IDs might follow patterns like:
        - UUID with timestamp encoding
        - Timestamp-prefixed IDs
        - Base64 encoded timestamps
        
        Args:
            checkpoint_id: The checkpoint ID to analyze
            
        Returns:
            datetime object if timestamp can be extracted, None otherwise
        """
        try:
            if self._is_uuid_format(checkpoint_id):
                uuid_obj = uuid.UUID(checkpoint_id)
                if uuid_obj.version == 1:
                    timestamp = uuid_obj.time
                    epoch_start = datetime(1582, 10, 15)
                    return epoch_start + timedelta(microseconds=timestamp // 10)
            
            timestamp_patterns = [
                r'(\d{10})',      
                r'(\d{13})',     
                r'(\d{16})',      
            ]
            
            for pattern in timestamp_patterns:
                matches = re.findall(pattern, checkpoint_id)
                if matches:
                    timestamp_str = matches[0]
                    timestamp_val = int(timestamp_str)
                    
                    if len(timestamp_str) == 10: 
                        return datetime.fromtimestamp(timestamp_val)
                    elif len(timestamp_str) == 13: 
                        return datetime.fromtimestamp(timestamp_val / 1000)
                    elif len(timestamp_str) == 16: 
                        return datetime.fromtimestamp(timestamp_val / 1000000)
            
            iso_pattern = r'(\d{4}-\d{2}-\d{2}[T\s]\d{2}:\d{2}:\d{2})'
            iso_matches = re.findall(iso_pattern, checkpoint_id)
            if iso_matches:
                return datetime.fromisoformat(iso_matches[0].replace('T', ' '))
                
        except Exception as e:
            logger.debug(f"Could not extract timestamp from checkpoint_id '{checkpoint_id}': {e}")
            
        return None

    def _is_uuid_format(self, value: str) -> bool:
        """Check if a string is in UUID format."""
        try:
            uuid.UUID(value)
            return True
        except ValueError:
            return False

    async def delete_longterm_records_for_session(self, conn: asyncpg.Connection, table_name: str, session_id: str) -> int:
        """Delete records from long-term table for a specific session ID after backing them up."""
        if self.dry_run:
            try:
                count = await conn.fetchval(f"SELECT COUNT(*) FROM {table_name} WHERE session_id = $1;", session_id)
                logger.info(f"DRY RUN: Would backup and delete {count} records from {table_name}")
                return count or 0
            except Exception as e:
                logger.error(f"Error counting records in {table_name}: {e}")
                return 0
        
        try:
            backup_count = await self.recycle_manager.backup_longterm_records(conn, table_name, session_id)
            result = await conn.execute(f"DELETE FROM {table_name} WHERE session_id = $1;", session_id)
            deleted_count = int(result.split()[-1]) if result.split()[-1].isdigit() else 0
            
            logger.info(f"Backed up {backup_count} and deleted {deleted_count} records from {table_name}")
            return deleted_count
        except Exception as e:
            logger.error(f"Error backing up and deleting records from {table_name}: {e}")
            return 0

    async def analyze_checkpoint_age_patterns(self, conn: asyncpg.Connection) -> Dict[str, any]:
        """
        Analyze patterns in checkpoint data to understand age distribution.
        
        Returns:
            Dictionary with analysis results
        """
        logger.info("Analyzing checkpoint age patterns...")
        sample_query = """
        SELECT checkpoint_id, thread_id, type, 
               jsonb_extract_path_text(metadata, 'created_at') as metadata_created,
               jsonb_extract_path_text(checkpoint, 'ts') as checkpoint_ts,
               jsonb_extract_path_text(checkpoint, 'v') as checkpoint_version,
               jsonb_extract_path_text(checkpoint, 'id') as checkpoint_inner_id
        FROM checkpoints 
        ORDER BY checkpoint_id 
        LIMIT 100;
        """
        
        sample_rows = await conn.fetch(sample_query)
        analysis = {
            'total_samples': len(sample_rows),
            'timestamp_extraction_success': 0,
            'metadata_timestamps_found': 0,
            'checkpoint_timestamps_found': 0,
            'checkpoint_ts_valid': 0,
            'oldest_checkpoint_ts': None,
            'newest_checkpoint_ts': None,
            'patterns_identified': []
        }
        
        valid_timestamps = []
        
        for row in sample_rows:
            checkpoint_id = row['checkpoint_id']
            extracted_ts = self.extract_timestamp_from_checkpoint_id(checkpoint_id)
            if extracted_ts:
                analysis['timestamp_extraction_success'] += 1
            if row['metadata_created']:
                analysis['metadata_timestamps_found'] += 1
            if row['checkpoint_ts']:
                analysis['checkpoint_timestamps_found'] += 1
                try:
                    from datetime import datetime, timezone
                    ts_str = row['checkpoint_ts']
                    if ts_str.endswith('Z'):
                        ts_str = ts_str.replace('Z', '+00:00')
                    elif '+00:00' not in ts_str and 'T' in ts_str:
                        ts_str = ts_str + '+00:00'
                    
                    ts = datetime.fromisoformat(ts_str)
                    if ts.tzinfo is None:
                        ts = ts.replace(tzinfo=timezone.utc)
                    
                    valid_timestamps.append(ts)
                    analysis['checkpoint_ts_valid'] += 1
                except Exception as e:
                    logger.debug(f"Failed to parse timestamp '{row['checkpoint_ts']}': {e}")
        if valid_timestamps:
            analysis['oldest_checkpoint_ts'] = min(valid_timestamps).isoformat()
            analysis['newest_checkpoint_ts'] = max(valid_timestamps).isoformat()
            old_count = sum(1 for ts in valid_timestamps if ts < self.cutoff_date)
            analysis['old_checkpoints_in_sample'] = old_count
            analysis['cutoff_date_used'] = self.cutoff_date.isoformat()
        
        logger.info(f"Analysis complete:")
        logger.info(f"  - Total samples: {analysis['total_samples']}")
        logger.info(f"  - Checkpoint 'ts' fields found: {analysis['checkpoint_timestamps_found']}")
        logger.info(f"  - Valid timestamp parsing: {analysis['checkpoint_ts_valid']}")
        if analysis['oldest_checkpoint_ts']:
            logger.info(f"  - Timestamp range: {analysis['oldest_checkpoint_ts']} to {analysis['newest_checkpoint_ts']}")
            logger.info(f"  - Old checkpoints in sample: {analysis.get('old_checkpoints_in_sample', 0)}")
        
        return analysis

    async def get_old_checkpoints_batch(self, conn: asyncpg.Connection, offset: int = 0) -> List[Tuple[str, str, str]]:
        """
        Get a batch of checkpoint records that are considered old.
        
        Returns:
            List of tuples: (thread_id, checkpoint_ns, checkpoint_id)
        """
        
        query_with_checkpoint_ts = """
        WITH checkpoint_timestamps AS (
            SELECT 
                thread_id, 
                checkpoint_ns, 
                checkpoint_id,
                -- Extract 'ts' timestamp from checkpoint JSONB and normalize to UTC
                CASE 
                    WHEN jsonb_extract_path_text(checkpoint, 'ts') IS NOT NULL THEN
                        (jsonb_extract_path_text(checkpoint, 'ts'))::timestamptz AT TIME ZONE 'UTC'
                    ELSE NULL
                END as checkpoint_timestamp
            FROM checkpoints
        )
        SELECT thread_id, checkpoint_ns, checkpoint_id, checkpoint_timestamp
        FROM checkpoint_timestamps
        WHERE checkpoint_timestamp IS NOT NULL 
          AND checkpoint_timestamp < ($1::timestamptz AT TIME ZONE 'UTC')
        ORDER BY checkpoint_timestamp ASC
        LIMIT $2 OFFSET $3;
        """
        
        try:
            from datetime import timezone
            cutoff_utc = self.cutoff_date.astimezone(timezone.utc)
            old_checkpoints = await conn.fetch(
                query_with_checkpoint_ts, 
                cutoff_utc, 
                self.batch_size, 
                offset
            )
            
            if old_checkpoints:
                logger.info(f"Found {len(old_checkpoints)} old checkpoints using checkpoint 'ts' field")
                if len(old_checkpoints) > 0:
                    sample_ts = old_checkpoints[0]['checkpoint_timestamp']
                    logger.info(f"Sample old timestamp: {sample_ts} (cutoff: {cutoff_utc})")
                return [(row['thread_id'], row['checkpoint_ns'], row['checkpoint_id']) for row in old_checkpoints]
            else:
                logger.info(f"Timestamp method: No records older than {self.cutoff_date} found")
                check_ts_query = """
                SELECT COUNT(*) as total_with_ts,
                       MIN((jsonb_extract_path_text(checkpoint, 'ts'))::timestamptz AT TIME ZONE 'UTC') as oldest_ts,
                       MAX((jsonb_extract_path_text(checkpoint, 'ts'))::timestamptz AT TIME ZONE 'UTC') as newest_ts
                FROM checkpoints 
                WHERE jsonb_extract_path_text(checkpoint, 'ts') IS NOT NULL;
                """
                ts_stats = await conn.fetchrow(check_ts_query)
                if ts_stats['total_with_ts'] > 0:
                    logger.info(f"Found {ts_stats['total_with_ts']} records with 'ts' field")
                    logger.info(f"Timestamp range: {ts_stats['oldest_ts']} to {ts_stats['newest_ts']}")
                    logger.info(f"Cutoff date: {cutoff_utc}")
                    if ts_stats['oldest_ts'] >= cutoff_utc:
                        logger.info("All records are newer than cutoff date - this is expected")
                else:
                    logger.warning("No records found with 'ts' field in checkpoint JSONB")
                return [] 
        except Exception as e:
            logger.warning(f"Checkpoint 'ts' field method failed: {e}")
        query_with_extraction = """
        WITH checkpoint_analysis AS (
            SELECT 
                thread_id, 
                checkpoint_ns, 
                checkpoint_id,
                -- Try to extract Unix timestamp from checkpoint_id (10 digits)
                CASE 
                    WHEN checkpoint_id ~ '^[0-9]{10}' THEN 
                        to_timestamp(substring(checkpoint_id from '^([0-9]{10})')::bigint)
                    WHEN checkpoint_id ~ '[0-9]{10}' THEN 
                        to_timestamp(substring(checkpoint_id from '([0-9]{10})')::bigint)
                    ELSE NULL
                END as extracted_timestamp
            FROM checkpoints
        )
        SELECT thread_id, checkpoint_ns, checkpoint_id
        FROM checkpoint_analysis
        WHERE extracted_timestamp IS NOT NULL 
          AND extracted_timestamp < $1
        ORDER BY thread_id, checkpoint_ns, checkpoint_id
        LIMIT $2 OFFSET $3;
        """
        
        try:
            old_checkpoints = await conn.fetch(
                query_with_extraction, 
                self.cutoff_date, 
                self.batch_size, 
                offset
            )
            
            if old_checkpoints:
                logger.info(f"Found {len(old_checkpoints)} old checkpoints using checkpoint_id timestamp extraction")
                return [(row['thread_id'], row['checkpoint_ns'], row['checkpoint_id']) for row in old_checkpoints]
            else:
                logger.info("Checkpoint ID extraction method: No old records found")
        except Exception as e:
            logger.warning(f"Timestamp extraction method failed: {e}")
        query_with_metadata = """
        WITH checkpoint_metadata AS (
            SELECT 
                thread_id, 
                checkpoint_ns, 
                checkpoint_id,
                CASE 
                    WHEN jsonb_extract_path_text(metadata, 'created_at') IS NOT NULL THEN
                        (jsonb_extract_path_text(metadata, 'created_at'))::timestamptz AT TIME ZONE 'UTC'
                    WHEN jsonb_extract_path_text(metadata, 'timestamp') IS NOT NULL THEN
                        (jsonb_extract_path_text(metadata, 'timestamp'))::timestamptz AT TIME ZONE 'UTC'
                    ELSE NULL
                END as metadata_timestamp
            FROM checkpoints
        )
        SELECT thread_id, checkpoint_ns, checkpoint_id
        FROM checkpoint_metadata
        WHERE metadata_timestamp IS NOT NULL 
          AND metadata_timestamp < ($1::timestamptz AT TIME ZONE 'UTC')
        ORDER BY thread_id, checkpoint_ns, checkpoint_id
        LIMIT $2 OFFSET $3;
        """
        
        try:
            from datetime import timezone
            cutoff_utc = self.cutoff_date.astimezone(timezone.utc)
            old_checkpoints = await conn.fetch(
                query_with_metadata,
                cutoff_utc,
                self.batch_size,
                offset
            )
            
            if old_checkpoints:
                logger.info(f"Found {len(old_checkpoints)} old checkpoints using metadata timestamps")
                return [(row['thread_id'], row['checkpoint_ns'], row['checkpoint_id']) for row in old_checkpoints]
            else:
                logger.info(f"Metadata timestamp method: No records older than {self.cutoff_date} found")
                return []  
        except Exception as e:
            logger.warning(f"Metadata timestamp method failed: {e}")
        logger.warning("Using fallback strategy: selecting oldest records by primary key ordering")
        logger.warning("This may not respect the age criteria accurately!")
        if offset == 0:
            logger.warning("Fallback strategy cannot reliably determine age - checking total record count")
            count_query = "SELECT COUNT(*) as total_count FROM checkpoints;"
            count_result = await conn.fetchrow(count_query)
            total_records = count_result['total_count']
            
            if total_records > 0:
                logger.warning(f"Found {total_records} total records but cannot determine age")
                logger.warning("Stopping cleanup to prevent data loss. Consider:")
                logger.warning("1. Check if 'ts' field exists in checkpoint JSONB data")
                logger.warning("2. Verify timezone settings")
                logger.warning("3. Use --dry-run mode to analyze data patterns")
                logger.warning("4. All records may be newer than cutoff date")
                return [] 
        
        fallback_query = """
        SELECT thread_id, checkpoint_ns, checkpoint_id
        FROM checkpoints
        ORDER BY thread_id, checkpoint_ns, checkpoint_id
        LIMIT $1 OFFSET $2;
        """
        
        old_checkpoints = await conn.fetch(fallback_query, self.batch_size, offset)
        return [(row['thread_id'], row['checkpoint_ns'], row['checkpoint_id']) for row in old_checkpoints]

    async def delete_checkpoints_batch(self, conn: asyncpg.Connection, checkpoints: List[Tuple[str, str, str]]) -> Tuple[int, int]:
        """
        Delete a batch of checkpoints and related data after backing them up to recycle bin.
        Also handles cascade deletion of related long-term table records.
        
        Args:
            conn: Database connection
            checkpoints: List of (thread_id, checkpoint_ns, checkpoint_id) tuples
            
        Returns:
            Tuple of (deleted_count, backed_up_count)
        """
        if not checkpoints:
            return 0, 0
        
        backed_up_count = await self.recycle_manager.backup_checkpoints_batch(checkpoints)
        
        if self.dry_run:
            logger.info(f"DRY RUN: Would delete {len(checkpoints)} checkpoints")
            await self._perform_cascade_deletion(conn, checkpoints, dry_run=True)
            return len(checkpoints), backed_up_count
        
        deleted_count = 0
        
        async with conn.transaction():
            try:
                await conn.execute("""
                    CREATE TEMPORARY TABLE temp_checkpoints_to_delete (
                        thread_id text,
                        checkpoint_ns text,
                        checkpoint_id text
                    );
                """)
            
                await conn.executemany(
                    "INSERT INTO temp_checkpoints_to_delete VALUES ($1, $2, $3);",
                    checkpoints
                )
                
                writes_result = await conn.execute("""
                    DELETE FROM checkpoint_writes cw
                    WHERE EXISTS (
                        SELECT 1 FROM temp_checkpoints_to_delete t
                        WHERE t.thread_id = cw.thread_id 
                        AND t.checkpoint_ns = cw.checkpoint_ns 
                        AND t.checkpoint_id = cw.checkpoint_id
                    );
                """)
                writes_deleted = int(writes_result.split()[-1]) if writes_result.split()[-1].isdigit() else 0
                logger.debug(f"Deleted {writes_deleted} checkpoint_writes records")
                
                checkpoints_result = await conn.execute("""
                    DELETE FROM checkpoints c
                    WHERE EXISTS (
                        SELECT 1 FROM temp_checkpoints_to_delete t
                        WHERE t.thread_id = c.thread_id 
                        AND t.checkpoint_ns = c.checkpoint_ns 
                        AND t.checkpoint_id = c.checkpoint_id
                    );
                """)
                checkpoints_deleted = int(checkpoints_result.split()[-1]) if checkpoints_result.split()[-1].isdigit() else 0
                logger.debug(f"Deleted {checkpoints_deleted} checkpoints records")
                await self._perform_cascade_deletion(conn, checkpoints, dry_run=False)
                
                await conn.execute("DROP TABLE temp_checkpoints_to_delete;")
                deleted_count = checkpoints_deleted
                
            except Exception as e:
                logger.error(f"Error deleting checkpoint batch: {e}")
                raise
        
        return deleted_count, backed_up_count

    async def _perform_cascade_deletion(self, conn: asyncpg.Connection, checkpoints: List[Tuple[str, str, str]], dry_run: bool = False):
        """
        Perform cascade deletion of records from long-term tables based on thread_id.
        """
        logger.info(f"Performing cascade deletion for {len(checkpoints)} checkpoints...")
        
        table_sessions = {}
        
        for thread_id, checkpoint_ns, checkpoint_id in checkpoints:
            table_name, session_id = parse_thread_id(thread_id)
            
            if table_name and session_id:
                if table_name not in table_sessions:
                    table_sessions[table_name] = set()
                table_sessions[table_name].add(session_id)
        
        total_cascade_deleted = 0
        for table_name, session_ids in table_sessions.items():
            table_exists = await check_table_exists(conn, table_name)
            
            if table_exists:
                for session_id in session_ids:
                    deleted = await self.delete_longterm_records_for_session(conn, table_name, session_id)
                    total_cascade_deleted += deleted
        
        if total_cascade_deleted > 0:
            action = "Would delete" if dry_run else "Deleted"
            logger.info(f"{action} {total_cascade_deleted} records from long-term tables")

    async def delete_orphaned_checkpoint_blobs(self, conn: asyncpg.Connection) -> Tuple[int, int]:
        """
        Delete checkpoint_blobs that don't have corresponding checkpoints after backing them up.
        
        Returns:
            Tuple of (orphaned_blobs_deleted, orphaned_blobs_backed_up)
        """
        logger.info("Cleaning up orphaned checkpoint blobs...")
        
        backed_up_count = await self.recycle_manager.backup_orphaned_blobs([])
        
        if self.dry_run:
            count_query = """
            SELECT COUNT(*) as orphaned_count
            FROM checkpoint_blobs cb
            WHERE NOT EXISTS (
                SELECT 1 FROM checkpoints c 
                WHERE c.thread_id = cb.thread_id 
                AND c.checkpoint_ns = cb.checkpoint_ns
            );
            """
            result = await conn.fetchrow(count_query)
            orphaned_count = result['orphaned_count']
            logger.info(f"DRY RUN: Would delete {orphaned_count} orphaned checkpoint blobs")
            return orphaned_count, backed_up_count
        delete_query = """
        DELETE FROM checkpoint_blobs cb
        WHERE NOT EXISTS (
            SELECT 1 FROM checkpoints c 
            WHERE c.thread_id = cb.thread_id 
            AND c.checkpoint_ns = cb.checkpoint_ns
        );
        """
        
        result = await conn.execute(delete_query)
        deleted_count = int(result.split()[-1])
        logger.info(f"Deleted {deleted_count} orphaned checkpoint blobs")
        
        return deleted_count, backed_up_count

    async def get_table_stats(self, conn: asyncpg.Connection) -> Dict[str, int]:
        """Get current row counts for all tables."""
        stats = {}
        
        tables = ['checkpoints', 'checkpoint_writes', 'checkpoint_blobs']
        for table in tables:
            count_query = f"SELECT COUNT(*) as count FROM {table};"
            result = await conn.fetchrow(count_query)
            stats[table] = result['count']
            
        return stats

    async def cleanup_old_data(self) -> CleanupStats:
        """
        Main method to cleanup old data from all LangGraph tables.
        
        Returns:
            CleanupStats object with operation results
        """
        stats = CleanupStats()
        start_time = datetime.now()
        
        logger.info("=" * 60)
        logger.info("Starting LangGraph tables cleanup")
        logger.info("=" * 60)
        logger.info("PERFORMANCE TIP: For billions of records, consider creating indexes:")
        logger.info("   Run: python langraph_indexing.py --create --dry-run")
        logger.info("   Then: python langraph_indexing.py --create")
        logger.info("=" * 60)
        
        async with self.get_db_connection() as conn:
            try:
                await self.recycle_manager.ensure_recycle_tables_exist()
                initial_stats = await self.get_table_stats(conn)
                logger.info("Initial table statistics:")
                for table, count in initial_stats.items():
                    logger.info(f"  {table}: {count:,} records")
                analysis = await self.analyze_checkpoint_age_patterns(conn)
                
                total_processed = 0
                consecutive_empty_batches = 0
                max_consecutive_empty = 3  
                max_dry_run_batches = min(20, (11543 // self.batch_size) + 1) if self.dry_run else None
                
                while True:
                    if self.max_batches and stats.total_batches >= self.max_batches:
                        logger.info(f"Reached batch limit of {self.max_batches} batches for testing")
                        break
                    if self.dry_run and max_dry_run_batches and stats.total_batches >= max_dry_run_batches:
                        logger.info(f"DRY-RUN: Stopping after {max_dry_run_batches} batches to avoid endless loop")
                        logger.info("In dry-run mode, records aren't actually deleted so the same batch keeps being returned")
                        logger.info(f"Estimated total old records: {stats.total_batches * self.batch_size}")
                        break
                    
                    checkpoints_batch = await self.get_old_checkpoints_batch(conn, 0)  
                    
                    if not checkpoints_batch:
                        logger.info("No more old checkpoints found")
                        break
                    
                    if not self.quiet_mode:
                        logger.info(f"Processing batch {stats.total_batches + 1}: {len(checkpoints_batch)} checkpoints")
                    
                    try:
                        deleted_count, backed_up_count = await self.delete_checkpoints_batch(conn, checkpoints_batch)
                        stats.checkpoints_deleted += deleted_count
                        stats.checkpoints_backed_up += backed_up_count
                        total_processed += len(checkpoints_batch)
                        
                        stats.total_batches += 1
                        if self.dry_run:
                            if deleted_count > 0:
                                consecutive_empty_batches = 0 
                            else:
                                consecutive_empty_batches += 1
                                logger.warning(f"No records would be deleted in batch {stats.total_batches}. "
                                            f"Consecutive empty batches: {consecutive_empty_batches}")
                        else:
                            if deleted_count == 0:
                                consecutive_empty_batches += 1
                                logger.warning(f"No records deleted in batch {stats.total_batches}. "
                                            f"Consecutive empty batches: {consecutive_empty_batches}")
                            else:
                                consecutive_empty_batches = 0 
                        
                        if consecutive_empty_batches >= max_consecutive_empty:
                            logger.error(f"Stopping after {consecutive_empty_batches} consecutive batches with no deletions")
                            logger.error("This may indicate:")
                            logger.error("1. All remaining records are newer than cutoff date")
                            logger.error("2. Database constraints preventing deletion") 
                            logger.error("3. Timestamp extraction failing consistently")
                            logger.error("4. Fallback strategy selecting non-old records")
                            if self.dry_run:
                                logger.error("5. DRY-RUN MODE: Same records being returned repeatedly")
                            break
                        
                        if stats.total_batches % 10 == 0:
                            logger.info(f"Progress: {stats.total_batches} batches, {total_processed:,} processed, {stats.checkpoints_deleted:,} deleted, {stats.checkpoints_backed_up:,} backed up")
                        
                    except Exception as e:
                        consecutive_empty_batches += 1
                        logger.error(f"Error processing batch {stats.total_batches + 1}: {e}")
                        stats.errors_count += 1
                        
                        if consecutive_empty_batches >= max_consecutive_empty:
                            logger.error(f"Stopping after {consecutive_empty_batches} consecutive failed batches")
                            break
                
                blobs_deleted, blobs_backed_up = await self.delete_orphaned_checkpoint_blobs(conn)
                stats.checkpoint_blobs_deleted = blobs_deleted
                stats.checkpoint_blobs_backed_up = blobs_backed_up
                old_recycle_deleted = await self.recycle_manager.cleanup_old_recycle_records()
                stats.old_recycle_records_deleted = old_recycle_deleted
                final_stats = await self.get_table_stats(conn)
                logger.info("Final table statistics:")
                for table, count in final_stats.items():
                    initial_count = initial_stats[table]
                    deleted = initial_count - count
                    logger.info(f"  {table}: {count:,} records (-{deleted:,})")
                
            except Exception as e:
                logger.error(f"Critical error during cleanup: {e}")
                stats.errors_count += 1
                raise
        stats.execution_time = (datetime.now() - start_time).total_seconds()
        
        logger.info("=" * 60)
        logger.info("Cleanup Summary:")
        logger.info(f"  Checkpoints deleted: {stats.checkpoints_deleted:,}")
        logger.info(f"  Checkpoints backed up: {stats.checkpoints_backed_up:,}")
        logger.info(f"  Checkpoint blobs deleted: {stats.checkpoint_blobs_deleted:,}")
        logger.info(f"  Checkpoint blobs backed up: {stats.checkpoint_blobs_backed_up:,}")
        logger.info(f"  Old recycle records deleted: {stats.old_recycle_records_deleted:,}")
        logger.info(f"  Total batches processed: {stats.total_batches}")
        logger.info(f"  Execution time: {stats.execution_time:.2f} seconds")
        logger.info(f"  Errors encountered: {stats.errors_count}")
        logger.info(f"  Mode: {'DRY RUN' if self.dry_run else 'LIVE DELETION'}")
        logger.info("=" * 60)
        
        return stats


async def main():
    """
    Main function to run the cleanup process.
    Supports command-line arguments for configuration.
    """
    import argparse
    
    parser = argparse.ArgumentParser(description='Cleanup old LangGraph checkpoint data')
    parser.add_argument('--days', type=int, default=30, 
                       help='Number of days of data to keep (default: 30)')
    parser.add_argument('--batch-size', type=int, default=1000,
                       help='Batch size for processing (default: 1000)')
    parser.add_argument('--dry-run', action='store_true',
                       help='Run in dry-run mode (no actual deletion)')
    
    args = parser.parse_args()
    
    try:
        cleaner = LangGraphTablesCleaner(
            days_to_keep=args.days,
            batch_size=args.batch_size,
            dry_run=args.dry_run
        )
        
        stats = await cleaner.cleanup_old_data()
        
        if stats.errors_count == 0:
            logger.info("Cleanup completed successfully!")
        else:
            logger.warning(f"Cleanup completed with {stats.errors_count} errors. Check logs for details.")
            
    except Exception as e:
        logger.error(f"Cleanup failed: {e}")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
