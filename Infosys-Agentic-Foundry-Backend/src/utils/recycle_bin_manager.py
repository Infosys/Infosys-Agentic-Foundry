import os
import sys
import asyncio
import asyncpg
import logging
from datetime import datetime, timedelta, timezone
from typing import List, Dict, Optional, Tuple, Set
from dataclasses import dataclass
from dotenv import load_dotenv
import json
from contextlib import asynccontextmanager

load_dotenv()
logger = logging.getLogger(__name__)


def parse_thread_id(thread_id: str) -> Tuple[Optional[str], Optional[str]]:
    """
    Parse thread_id to extract table name and session ID.
    Args:
        thread_id: The thread ID to parse
        
    Returns:
        Tuple of (table_name, session_id) or (None, None) if parsing fails
    """
    try:
        parts = thread_id.split('_')
        email_index = -1
        for i, part in enumerate(parts):
            if '@' in part:
                email_index = i
                break
        
        if email_index == -1:
            logger.warning(f"Could not find email pattern in thread_id: {thread_id}")
            return None, None
        table_name = '_'.join(parts[:email_index])
        session_id = '_'.join(parts[email_index:])
        
        logger.debug(f"Parsed thread_id: table_name='{table_name}', session_id='{session_id}'")
        return table_name, session_id
        
    except Exception as e:
        logger.error(f"Error parsing thread_id '{thread_id}': {e}")
        return None, None


async def check_table_exists(conn: asyncpg.Connection, table_name: str) -> bool:
    """
    Check if a table exists in the database.
    
    Args:
        conn: Database connection
        table_name: Name of the table to check
        
    Returns:
        True if table exists, False otherwise
    """
    try:
        query = """
        SELECT EXISTS (
            SELECT FROM information_schema.tables 
            WHERE table_schema = 'public' 
            AND table_name = $1
        );
        """
        result = await conn.fetchval(query, table_name)
        return result
    except Exception as e:
        logger.error(f"Error checking if table '{table_name}' exists: {e}")
        return False


@dataclass
class RecycleStats:
    """Statistics for recycle bin operations"""
    checkpoints_backed_up: int = 0
    checkpoint_writes_backed_up: int = 0
    checkpoint_blobs_backed_up: int = 0
    checkpoints_restored: int = 0
    checkpoint_writes_restored: int = 0
    checkpoint_blobs_restored: int = 0
    tools_deleted: int = 0
    agents_deleted: int = 0
    old_recycle_records_deleted: int = 0
    execution_time: float = 0.0
    errors_count: int = 0


class RecycleBinManager:
    """
    Manages backup and restoration of LangGraph checkpoint data through a recycle bin system.
    """
    
    def __init__(self, days_to_keep_in_recycle: int = 45, dry_run: bool = False): ###222
        """
        Initialize the recycle bin manager.
        
        Args:
            days_to_keep_in_recycle: Number of days to keep data in recycle bin (default: 45)
            dry_run: If True, only analyze without actual changes (default: False)
        """
        self.days_to_keep_in_recycle = days_to_keep_in_recycle
        self.dry_run = dry_run
        self.recycle_cutoff_date = datetime.now(timezone.utc) - timedelta(days=days_to_keep_in_recycle)
        self.recycle_database_name = "recycle"
        self.main_db_url = os.getenv("POSTGRESQL_DATABASE_URL", "")
        if not self.main_db_url:
            raise ValueError("POSTGRESQL_DATABASE_URL environment variable is required")

        import re
        url_pattern = r'(postgresql://[^/]+/)([^?]+)(.*)'
        match = re.match(url_pattern, self.main_db_url)
        if match:
            self.recycle_db_url = f"{match.group(1)}{self.recycle_database_name}{match.group(3)}"
        else:
            raise ValueError("Could not parse POSTGRESQL_DATABASE_URL")
        
        logger.info(f"Initialized RecycleBinManager:")
        logger.info(f"  - Days to keep in recycle bin: {self.days_to_keep_in_recycle}")
        logger.info(f"  - Recycle cutoff date: {self.recycle_cutoff_date}")
        logger.info(f"  - Main database URL configured: Yes")
        logger.info(f"  - Recycle database: {self.recycle_database_name}")
        logger.info(f"  - Dry run mode: {self.dry_run}")

    @asynccontextmanager
    async def get_main_db_connection(self):
        """Context manager for main database connections."""
        conn = None
        try:
            conn = await asyncpg.connect(self.main_db_url)
            yield conn
        except Exception as e:
            logger.error(f"Main database connection error: {e}")
            raise
        finally:
            if conn:
                await conn.close()

    @asynccontextmanager
    async def get_recycle_db_connection(self):
        """Context manager for recycle database connections."""
        conn = None
        try:
            conn = await asyncpg.connect(self.recycle_db_url)
            yield conn
        except asyncpg.InvalidCatalogNameError:
            logger.info(f"Recycle database '{self.recycle_database_name}' doesn't exist, creating it...")
            await self._create_recycle_database()
            conn = await asyncpg.connect(self.recycle_db_url)
            yield conn
        except Exception as e:
            logger.error(f"Recycle database connection error: {e}")
            raise
        finally:
            if conn:
                await conn.close()

    async def _create_recycle_database(self):
        """Create the recycle database if it doesn't exist."""
        import re
        url_pattern = r'(postgresql://[^/]+/)([^?]+)(.*)'
        match = re.match(url_pattern, self.main_db_url)
        if match:
            postgres_url = f"{match.group(1)}postgres{match.group(3)}"
        else:
            raise ValueError("Could not create postgres connection URL")
        
        conn = None
        try:
            conn = await asyncpg.connect(postgres_url)
            await conn.execute(f'CREATE DATABASE "{self.recycle_database_name}";')
            logger.info(f"Created recycle database: {self.recycle_database_name}")
        except asyncpg.DuplicateDatabaseError:
            logger.info(f"Recycle database '{self.recycle_database_name}' already exists")
        except Exception as e:
            logger.error(f"Error creating recycle database: {e}")
            raise
        finally:
            if conn:
                await conn.close()

    async def ensure_recycle_tables_exist(self):
        """
        Create recycle bin tables if they don't exist.
        Tables mirror the original structure with an additional 'deleted_date' column.
        """
        logger.info("Ensuring recycle bin tables exist...")
        
        async with self.get_recycle_db_connection() as conn:
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS recycle_checkpoints (
                    thread_id text NOT NULL,
                    checkpoint_ns text NOT NULL DEFAULT '',
                    checkpoint_id text NOT NULL,
                    parent_checkpoint_id text,
                    type text,
                    checkpoint jsonb NOT NULL,
                    metadata jsonb NOT NULL DEFAULT '{}',
                    deleted_date timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (thread_id, checkpoint_ns, checkpoint_id)
                );
            """)
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS recycle_checkpoint_writes (
                    thread_id text NOT NULL,
                    checkpoint_ns text NOT NULL DEFAULT '',
                    checkpoint_id text NOT NULL,
                    task_id text NOT NULL,
                    idx integer NOT NULL,
                    channel text NOT NULL,
                    type text,
                    blob bytea,
                    task_path text DEFAULT '',
                    deleted_date timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (thread_id, checkpoint_ns, checkpoint_id, task_id, idx)
                );
            """)
            
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS recycle_checkpoint_blobs (
                    thread_id text NOT NULL,
                    checkpoint_ns text NOT NULL DEFAULT '',
                    channel text NOT NULL,
                    version text NOT NULL,
                    type text NOT NULL,
                    blob bytea,
                    deleted_date timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (thread_id, checkpoint_ns, channel, version)
                );
            """)

            await conn.execute("""
                CREATE TABLE IF NOT EXISTS recycle_longterm_memory (
                    table_name text COLLATE pg_catalog."default" NOT NULL,
                    session_id text COLLATE pg_catalog."default" NOT NULL,
                    start_timestamp timestamp without time zone,
                    end_timestamp timestamp without time zone NOT NULL,
                    human_message text COLLATE pg_catalog."default",
                    ai_message text COLLATE pg_catalog."default",
                    response_time double precision,
                    deleted_date timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    CONSTRAINT recycle_longterm_memory_pkey PRIMARY KEY (table_name, session_id, end_timestamp)
                );
            """)

            await conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_recycle_checkpoints_deleted_date 
                ON recycle_checkpoints (deleted_date);
            """)
            await conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_recycle_longterm_memory_table_session 
                ON recycle_longterm_memory (table_name, session_id);
            """)
            await conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_recycle_longterm_memory_deleted_date 
                ON recycle_longterm_memory (deleted_date);
            """)
            await conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_recycle_longterm_memory_end_timestamp 
                ON recycle_longterm_memory (end_timestamp);
            """)
            await conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_recycle_checkpoint_writes_deleted_date 
                ON recycle_checkpoint_writes (deleted_date);
            """)
            await conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_recycle_checkpoint_blobs_deleted_date 
                ON recycle_checkpoint_blobs (deleted_date);
            """)
            
        logger.info("Recycle bin tables and indexes created successfully")

    async def backup_checkpoints_batch(self, checkpoints: List[Tuple[str, str, str]]) -> int:
        """
        Backup a batch of checkpoints to recycle bin before deletion.
        
        Args:
            checkpoints: List of (thread_id, checkpoint_ns, checkpoint_id) tuples
            
        Returns:
            Number of records backed up
        """
        if not checkpoints or self.dry_run:
            if self.dry_run:
                logger.info(f"DRY RUN: Would backup {len(checkpoints)} checkpoints to recycle bin")
            return len(checkpoints) if checkpoints else 0
        
        logger.info(f"Backing up {len(checkpoints)} checkpoints to recycle bin...")
        
        backed_up_count = 0
        current_time = datetime.now(timezone.utc)
        
        async with self.get_main_db_connection() as main_conn:
            async with self.get_recycle_db_connection() as recycle_conn:
                async with recycle_conn.transaction():
                    try:
                        for thread_id, checkpoint_ns, checkpoint_id in checkpoints:
                            original = await main_conn.fetchrow("""
                                SELECT thread_id, checkpoint_ns, checkpoint_id, 
                                       parent_checkpoint_id, type, checkpoint, metadata
                                FROM checkpoints 
                                WHERE thread_id = $1 AND checkpoint_ns = $2 AND checkpoint_id = $3
                            """, thread_id, checkpoint_ns, checkpoint_id)
                            
                            if original:
                                await recycle_conn.execute("""
                                    INSERT INTO recycle_checkpoints 
                                    (thread_id, checkpoint_ns, checkpoint_id, parent_checkpoint_id, 
                                     type, checkpoint, metadata, deleted_date)
                                    VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
                                    ON CONFLICT (thread_id, checkpoint_ns, checkpoint_id) 
                                    DO UPDATE SET 
                                        parent_checkpoint_id = EXCLUDED.parent_checkpoint_id,
                                        type = EXCLUDED.type,
                                        checkpoint = EXCLUDED.checkpoint,
                                        metadata = EXCLUDED.metadata,
                                        deleted_date = EXCLUDED.deleted_date
                                """, 
                                original['thread_id'], original['checkpoint_ns'], original['checkpoint_id'],
                                original['parent_checkpoint_id'], original['type'], 
                                original['checkpoint'], original['metadata'], current_time)
                                
                                backed_up_count += 1
                    
                        columns_check = await main_conn.fetch("""
                            SELECT column_name 
                            FROM information_schema.columns 
                            WHERE table_name = 'checkpoint_writes' 
                            ORDER BY ordinal_position
                        """)
                        
                        available_columns = [col['column_name'] for col in columns_check]
                        logger.info(f"Available columns in checkpoint_writes: {available_columns}")

                        base_columns = ['thread_id', 'checkpoint_ns', 'checkpoint_id', 'task_id', 'idx', 'channel', 'type']
                        optional_columns = ['blob', 'task_path'] 
                        
                        select_columns = []
                        for col in base_columns + optional_columns:
                            if col in available_columns:
                                select_columns.append(col)
                            else:
                                logger.warning(f"Column '{col}' not found in checkpoint_writes table, using NULL")
                                select_columns.append(f"NULL as {col}")
                        
                        select_query = f"""
                            SELECT {', '.join(select_columns)}
                            FROM checkpoint_writes 
                            WHERE thread_id = $1 AND checkpoint_ns = $2 AND checkpoint_id = $3
                            AND blob IS NOT NULL
                        """
                        
                        for thread_id, checkpoint_ns, checkpoint_id in checkpoints:
                            writes = await main_conn.fetch(select_query, thread_id, checkpoint_ns, checkpoint_id)
                            
                            for write in writes:
                                await recycle_conn.execute("""
                                    INSERT INTO recycle_checkpoint_writes 
                                    (thread_id, checkpoint_ns, checkpoint_id, task_id, idx, 
                                     channel, type, blob, task_path, deleted_date)
                                    VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
                                    ON CONFLICT (thread_id, checkpoint_ns, checkpoint_id, task_id, idx) 
                                    DO UPDATE SET 
                                        channel = EXCLUDED.channel,
                                        type = EXCLUDED.type,
                                        blob = EXCLUDED.blob,
                                        task_path = EXCLUDED.task_path,
                                        deleted_date = EXCLUDED.deleted_date
                                """, 
                                write['thread_id'], write['checkpoint_ns'], write['checkpoint_id'],
                                write['task_id'], write['idx'], write['channel'], 
                                write['type'], write['blob'], write['task_path'], current_time)
                        
                    except Exception as e:
                        logger.error(f"Error backing up checkpoints batch: {e}")
                        raise
        
        logger.info(f"Successfully backed up {backed_up_count} checkpoints to recycle bin")
        return backed_up_count

    async def backup_orphaned_blobs(self, orphaned_blobs: List[Tuple]) -> int:
        """
        Backup orphaned checkpoint blobs to recycle bin before deletion.
        
        Args:
            orphaned_blobs: List of blob identifiers
            
        Returns:
            Number of blobs backed up
        """
        if self.dry_run:
            logger.info(f"DRY RUN: Would backup orphaned blobs to recycle bin")
            return 0
        
        logger.info("Backing up orphaned checkpoint blobs to recycle bin...")
        
        current_time = datetime.now(timezone.utc)
        backed_up_count = 0
        
        async with self.get_main_db_connection() as main_conn:
            async with self.get_recycle_db_connection() as recycle_conn:
                async with recycle_conn.transaction():
                    try:
                        orphaned_blobs_query = """
                        SELECT thread_id, checkpoint_ns, channel, version, type, blob
                        FROM checkpoint_blobs cb
                        WHERE NOT EXISTS (
                            SELECT 1 FROM checkpoints c 
                            WHERE c.thread_id = cb.thread_id 
                            AND c.checkpoint_ns = cb.checkpoint_ns
                        );
                        """
                        
                        blobs = await main_conn.fetch(orphaned_blobs_query)
                        
                        for blob in blobs:
                            await recycle_conn.execute("""
                                INSERT INTO recycle_checkpoint_blobs 
                                (thread_id, checkpoint_ns, channel, version, type, blob, deleted_date)
                                VALUES ($1, $2, $3, $4, $5, $6, $7)
                                ON CONFLICT (thread_id, checkpoint_ns, channel, version) 
                                DO UPDATE SET 
                                    type = EXCLUDED.type,
                                    blob = EXCLUDED.blob,
                                    deleted_date = EXCLUDED.deleted_date
                            """, 
                            blob['thread_id'], blob['checkpoint_ns'], blob['channel'], 
                            blob['version'], blob['type'], blob['blob'], current_time)
                            
                            backed_up_count += 1
                        
                    except Exception as e:
                        logger.error(f"Error backing up orphaned blobs: {e}")
                        raise
        
        logger.info(f"Successfully backed up {backed_up_count} orphaned blobs to recycle bin")
        return backed_up_count

    async def cleanup_old_recycle_records(self) -> int:
        """
        Delete records from recycle bin that are older than the retention period.
        
        Returns:
            Number of old records deleted from recycle bin
        """
        logger.info(f"Cleaning up recycle bin records older than {self.days_to_keep_in_recycle} days...")
        
        if self.dry_run:
            async with self.get_recycle_db_connection() as conn:
                cutoff_naive = self.recycle_cutoff_date.replace(tzinfo=None)
                timestamptz_count = await conn.fetchrow("""
                    SELECT 
                        (SELECT COUNT(*) FROM recycle_checkpoints WHERE deleted_date < $1) as checkpoints,
                        (SELECT COUNT(*) FROM recycle_checkpoint_writes WHERE deleted_date < $1) as writes,
                        (SELECT COUNT(*) FROM recycle_checkpoint_blobs WHERE deleted_date < $1) as blobs,
                        (SELECT COUNT(*) FROM recycle_agent WHERE updated_on < $1) as agents,
                        (SELECT COUNT(*) FROM recycle_tool WHERE updated_on < $1) as tools
                """, self.recycle_cutoff_date)
                
                agents_to_delete = await conn.fetch("""
                    SELECT agentic_application_id 
                    FROM recycle_agent 
                    WHERE updated_on < $1;
                """, self.recycle_cutoff_date)
                
                agent_tables_count = 0
                if agents_to_delete:
                    async with self.get_main_db_connection() as main_conn:
                        for agent in agents_to_delete:
                            agent_id = agent['agentic_application_id']
                            table_name = f"table_{agent_id.replace('-', '_')}"
                            if await check_table_exists(main_conn, table_name):
                                agent_tables_count += 1
                
                total = (timestamptz_count['checkpoints'] + timestamptz_count['writes'] + 
                        timestamptz_count['blobs'] + timestamptz_count['tools'] + timestamptz_count['agents'])
                        
                logger.info(f"DRY RUN: Would delete {total} old records from recycle bin")
                logger.info(f"  - Checkpoints: {timestamptz_count['checkpoints']}")
                logger.info(f"  - Checkpoint writes: {timestamptz_count['writes']}")
                logger.info(f"  - Checkpoint blobs: {timestamptz_count['blobs']}")
                logger.info(f"  - Tools: {timestamptz_count['tools']}")
                logger.info(f"  - Agents: {timestamptz_count['agents']}")
                logger.info(f"  - Agent tables to drop: {agent_tables_count}")
                return total
        
        deleted_count = 0
        
        async with self.get_recycle_db_connection() as conn:
            async with conn.transaction():
                try:
                    writes_result = await conn.execute("""
                        DELETE FROM recycle_checkpoint_writes 
                        WHERE deleted_date < $1;
                    """, self.recycle_cutoff_date)
                    writes_deleted = int(writes_result.split()[-1]) if writes_result.split()[-1].isdigit() else 0
                    
                    checkpoints_result = await conn.execute("""
                        DELETE FROM recycle_checkpoints 
                        WHERE deleted_date < $1;
                    """, self.recycle_cutoff_date)
                    checkpoints_deleted = int(checkpoints_result.split()[-1]) if checkpoints_result.split()[-1].isdigit() else 0

                    blobs_result = await conn.execute("""
                        DELETE FROM recycle_checkpoint_blobs 
                        WHERE deleted_date < $1;
                    """, self.recycle_cutoff_date)
                    blobs_deleted = int(blobs_result.split()[-1]) if blobs_result.split()[-1].isdigit() else 0
                    tools_result = await conn.execute("""
                        DELETE FROM recycle_tool 
                        WHERE updated_on < $1;
                    """, self.recycle_cutoff_date)
                    tools_deleted = int(tools_result.split()[-1]) if tools_result.split()[-1].isdigit() else 0
                    logger.info(f"Deleted {tools_deleted} old tool records from recycle_tool table")
                    
                    agents_to_delete = await conn.fetch("""
                        SELECT agentic_application_id 
                        FROM recycle_agent 
                        WHERE updated_on < $1;
                    """, self.recycle_cutoff_date)
                    
                    tables_dropped = 0
                    if agents_to_delete:
                        async with self.get_main_db_connection() as main_conn:
                            tables_dropped = await self._drop_agent_tables(main_conn, agents_to_delete)
                    
                    agents_result = await conn.execute("""
                        DELETE FROM recycle_agent 
                        WHERE updated_on < $1;
                    """, self.recycle_cutoff_date)
                    agents_deleted = int(agents_result.split()[-1]) if agents_result.split()[-1].isdigit() else 0
                    logger.info(f"Deleted {agents_deleted} old agent records from recycle_agent table")
                    
                    longterm_result = await conn.execute("""
                        DELETE FROM recycle_longterm_memory 
                        WHERE deleted_date < $1;
                    """, self.recycle_cutoff_date)
                    longterm_deleted = int(longterm_result.split()[-1]) if longterm_result.split()[-1].isdigit() else 0
                    logger.info(f"Deleted {longterm_deleted} old longterm memory records from recycle_longterm_memory table")
                    
                    deleted_count = checkpoints_deleted + writes_deleted + blobs_deleted + tools_deleted + agents_deleted + longterm_deleted
                    
                    logger.info(f"Deleted {deleted_count} old records from recycle bin:")
                    logger.info(f"  - Checkpoints: {checkpoints_deleted}")
                    logger.info(f"  - Checkpoint writes: {writes_deleted}")
                    logger.info(f"  - Checkpoint blobs: {blobs_deleted}")
                    logger.info(f"  - Tools: {tools_deleted}")
                    logger.info(f"  - Agents: {agents_deleted}")
                    logger.info(f"  - Longterm memory: {longterm_deleted}")
                    logger.info(f"  - Agent tables dropped: {tables_dropped}")
                    
                except Exception as e:
                    logger.error(f"Error cleaning up old recycle records: {e}")
                    raise
        
        return deleted_count

    async def _drop_agent_tables(self, main_conn, agents_to_delete: List) -> int:
        """
        Drop tables associated with deleted agents from the main database.
        
        Args:
            main_conn: Main database connection
            agents_to_delete: List of agent records with agentic_application_id
            
        Returns:
            Number of tables dropped
        """
        tables_dropped = 0
        
        for agent in agents_to_delete:
            agent_id = agent['agentic_application_id']
            table_name = f"table_{agent_id.replace('-', '_')}"
            
            try:
                table_exists = await check_table_exists(main_conn, table_name)
                
                if table_exists:
                    await main_conn.execute(f'DROP TABLE IF EXISTS "{table_name}" CASCADE;')
                    tables_dropped += 1
                    logger.info(f"Dropped agent table: {table_name} (agent_id: {agent_id})")
                else:
                    logger.debug(f"Table {table_name} does not exist for agent_id: {agent_id}")
                    
            except Exception as e:
                logger.error(f"Error dropping table {table_name} for agent_id {agent_id}: {e}")
                continue
        
        if tables_dropped > 0:
            logger.info(f"Successfully dropped {tables_dropped} agent tables from main database")
        else:
            logger.info("No agent tables found to drop")
            
        return tables_dropped

    async def backup_longterm_records(self, main_conn, table_name: str, session_id: str) -> int:
        """
        Backup long-term table records to recycle_longterm_memory before deletion.
        
        Args:
            main_conn: Main database connection
            table_name: Name of the long-term table
            session_id: Session ID to backup records for
            
        Returns:
            Number of records backed up
        """
        try:
            select_query = f"SELECT * FROM {table_name} WHERE session_id = $1;"
            records = await main_conn.fetch(select_query, session_id)
            
            if not records:
                logger.info(f"No records found in {table_name} for session {session_id}")
                return 0
            
            backup_count = 0
            async with self.get_recycle_db_connection() as recycle_conn:
                for record in records:
                    await recycle_conn.execute("""
                        INSERT INTO recycle_longterm_memory 
                        (table_name, session_id, start_timestamp, end_timestamp, 
                         human_message, ai_message, response_time)
                        VALUES ($1, $2, $3, $4, $5, $6, $7);
                    """, 
                    table_name,
                    record.get('session_id'),
                    record.get('start_timestamp'),
                    record.get('end_timestamp'),
                    record.get('human_message'),
                    record.get('ai_message'),
                    record.get('response_time'))
                    backup_count += 1
            
            logger.info(f"Backed up {backup_count} records from {table_name} to recycle_longterm_memory")
            return backup_count
            
        except Exception as e:
            logger.error(f"Error backing up records from {table_name}: {e}")
            return 0

    async def restore_longterm_records(self, main_conn, table_name: str, session_id: str) -> int:
        """
        Restore long-term table records from recycle_longterm_memory.
        
        Args:
            main_conn: Main database connection
            table_name: Name of the long-term table to restore to
            session_id: Session ID to restore records for
            
        Returns:
            Number of records restored
        """
        try:
            logger.info(f"Starting longterm records restoration for table: {table_name}, session: {session_id}")
            
            async with self.get_recycle_db_connection() as recycle_conn:
                logger.info("Connecting to recycle database to fetch longterm records")
                records = await recycle_conn.fetch("""
                    SELECT session_id, start_timestamp, end_timestamp, 
                           human_message, ai_message, response_time
                    FROM recycle_longterm_memory 
                    WHERE table_name = $1 AND session_id = $2;
                """, table_name, session_id)
                
                if not records:
                    logger.info(f"No records found in recycle_longterm_memory for {table_name} session {session_id}")
                    return 0
                
                logger.info(f"Found {len(records)} records to restore")
                
                table_exists = await check_table_exists(main_conn, table_name)
                if not table_exists:
                    logger.warning(f"Target table {table_name} does not exist, skipping restore")
                    return 0
                
                logger.info(f"Target table {table_name} exists, proceeding with record restoration")
                restored_count = 0
                for record in records:
                    await main_conn.execute(f"""
                        INSERT INTO {table_name} 
                        (session_id, start_timestamp, end_timestamp, 
                         human_message, ai_message, response_time)
                        VALUES ($1, $2, $3, $4, $5, $6)
                        ON CONFLICT (session_id, end_timestamp) DO NOTHING;
                    """, 
                    record['session_id'],
                    record['start_timestamp'],
                    record['end_timestamp'],
                    record['human_message'],
                    record['ai_message'],
                    record['response_time'])
                    restored_count += 1
                
                logger.info(f"Successfully restored {restored_count} records to {table_name}")
                logger.info("Cleaning up restored records from recycle_longterm_memory")
                
                await recycle_conn.execute("""
                    DELETE FROM recycle_longterm_memory 
                    WHERE table_name = $1 AND session_id = $2;
                """, table_name, session_id)
                
                logger.info(f"Cleanup completed for {table_name} session {session_id}")
                logger.info(f"Longterm records restoration completed: {restored_count} records restored to {table_name}")
                return restored_count
                
        except Exception as e:
            logger.error(f"Error during longterm records restoration for table {table_name}, session {session_id}: {e}")
            return 0

    async def _perform_cascade_restoration(self, main_conn, thread_id: str, dry_run: bool = False) -> int:
        """Perform cascade restoration of records from recycle_longterm_memory to long-term tables."""
        try:
            logger.info(f"Starting cascade restoration for thread_id: {thread_id} (dry_run: {dry_run})")
            table_name, session_id = parse_thread_id(thread_id)
            
            if not table_name or not session_id:
                logger.warning(f"Failed to parse thread_id: {thread_id}, skipping cascade restoration")
                return 0
            
            logger.info(f"Parsed thread_id - table_name: {table_name}, session_id: {session_id}")
            
            if not await check_table_exists(main_conn, table_name):
                logger.warning(f"Target table {table_name} does not exist, skipping cascade restoration")
                return 0
            
            if dry_run:
                logger.info("Performing dry run cascade restoration check")
                async with self.get_recycle_db_connection() as recycle_conn:
                    count = await recycle_conn.fetchval("""
                        SELECT COUNT(*) FROM recycle_longterm_memory 
                        WHERE table_name = $1 AND session_id = $2;
                    """, table_name, session_id)
                    logger.info(f"DRY RUN: Would restore {count} records to {table_name} from longterm backup")
                    return count or 0
            
            logger.info(f"Performing actual cascade restoration for {table_name}")
            restored_count = await self.restore_longterm_records(main_conn, table_name, session_id)
            logger.info(f"Cascade restoration completed: {restored_count} records restored")
            return restored_count
            
        except Exception as e:
            logger.error(f"Error during cascade restoration for thread_id {thread_id}: {e}")
            return 0

    async def restore_records_by_thread_id(self, thread_id: str) -> RecycleStats:
        """
        Restore all records for a specific thread_id from recycle bin back to main tables.
        
        Args:
            thread_id: The thread ID to restore
            
        Returns:
            RecycleStats object with restoration results
        """
        try:
            logger.info(f"Starting restore operation for thread_id: {thread_id}")
            
            stats = RecycleStats()
            start_time = datetime.now()
            
            if self.dry_run:
                logger.info("Running in DRY RUN mode for thread-specific restore")
                async with self.get_recycle_db_connection() as conn:
                    logger.info("Connecting to recycle database to fetch record counts")
                    checkpoints_count = await conn.fetchval("SELECT COUNT(*) FROM recycle_checkpoints WHERE thread_id = $1", thread_id)
                    writes_count = await conn.fetchval("SELECT COUNT(*) FROM recycle_checkpoint_writes WHERE thread_id = $1", thread_id)
                    blobs_count = await conn.fetchval("SELECT COUNT(*) FROM recycle_checkpoint_blobs WHERE thread_id = $1", thread_id)
                    
                    async with self.get_main_db_connection() as main_conn:
                        cascade_count = await self._perform_cascade_restoration(main_conn, thread_id, dry_run=True)
                    
                    total_count = checkpoints_count + writes_count + blobs_count + cascade_count
                    logger.info(f"DRY RUN: Would restore {total_count} records ({checkpoints_count} checkpoints, {writes_count} writes, {blobs_count} blobs, {cascade_count} cascade)")
                    return stats
            
            logger.info("Establishing database connections for restore operation")
            async with self.get_recycle_db_connection() as recycle_conn:
                async with self.get_main_db_connection() as main_conn:
                    logger.info("Starting database transaction for restore operation")
                    async with main_conn.transaction():
                        async with recycle_conn.transaction():
                            try:
                                logger.info("Fetching checkpoints from recycle bin")
                                checkpoints = await recycle_conn.fetch("""
                                    SELECT thread_id, checkpoint_ns, checkpoint_id, parent_checkpoint_id,
                                           type, checkpoint, metadata
                                    FROM recycle_checkpoints WHERE thread_id = $1
                                """, thread_id)
                                
                                logger.info(f"Found {len(checkpoints)} checkpoints to restore")
                                for checkpoint in checkpoints:
                                    await main_conn.execute("""
                                        INSERT INTO checkpoints 
                                        (thread_id, checkpoint_ns, checkpoint_id, parent_checkpoint_id,
                                         type, checkpoint, metadata)
                                        VALUES ($1, $2, $3, $4, $5, $6, $7)
                                        ON CONFLICT (thread_id, checkpoint_ns, checkpoint_id) DO NOTHING
                                    """, 
                                    checkpoint['thread_id'], checkpoint['checkpoint_ns'], 
                                    checkpoint['checkpoint_id'], checkpoint['parent_checkpoint_id'],
                                    checkpoint['type'], checkpoint['checkpoint'], checkpoint['metadata'])
                                    
                                    stats.checkpoints_restored += 1
                                
                                logger.info(f"Restored {stats.checkpoints_restored} checkpoints to main database")
                                logger.info("Fetching checkpoint writes from recycle bin")
                                writes = await recycle_conn.fetch("""
                                    SELECT thread_id, checkpoint_ns, checkpoint_id, task_id, idx,
                                           channel, type, blob, task_path
                                    FROM recycle_checkpoint_writes 
                                    WHERE thread_id = $1 AND blob IS NOT NULL
                                """, thread_id)
                                
                                logger.info(f"Found {len(writes)} checkpoint writes to restore")
                                for write in writes:
                                    await main_conn.execute("""
                                        INSERT INTO checkpoint_writes 
                                        (thread_id, checkpoint_ns, checkpoint_id, task_id, idx,
                                         channel, type, blob, task_path)
                                        VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
                                        ON CONFLICT (thread_id, checkpoint_ns, checkpoint_id, task_id, idx) DO NOTHING
                                    """, 
                                    write['thread_id'], write['checkpoint_ns'], write['checkpoint_id'],
                                    write['task_id'], write['idx'], write['channel'], 
                                    write['type'], write['blob'], write['task_path'])
                                    
                                    stats.checkpoint_writes_restored += 1
                                
                                logger.info(f"Restored {stats.checkpoint_writes_restored} checkpoint writes to main database")
                                logger.info("Fetching checkpoint blobs from recycle bin")
                                blobs = await recycle_conn.fetch("""
                                    SELECT thread_id, checkpoint_ns, channel, version, type, blob
                                    FROM recycle_checkpoint_blobs WHERE thread_id = $1
                                """, thread_id)
                                
                                logger.info(f"Found {len(blobs)} checkpoint blobs to restore")
                                for blob in blobs:
                                    await main_conn.execute("""
                                        INSERT INTO checkpoint_blobs 
                                        (thread_id, checkpoint_ns, channel, version, type, blob)
                                        VALUES ($1, $2, $3, $4, $5, $6)
                                        ON CONFLICT (thread_id, checkpoint_ns, channel, version) DO NOTHING
                                    """, 
                                    blob['thread_id'], blob['checkpoint_ns'], blob['channel'],
                                    blob['version'], blob['type'], blob['blob'])
                                    
                                    stats.checkpoint_blobs_restored += 1
                                
                                logger.info(f"Restored {stats.checkpoint_blobs_restored} checkpoint blobs to main database")
                                logger.info("Cleaning up restored records from recycle bin")
                                await recycle_conn.execute(
                                    "DELETE FROM recycle_checkpoint_writes WHERE thread_id = $1", thread_id)
                                await recycle_conn.execute(
                                    "DELETE FROM recycle_checkpoints WHERE thread_id = $1", thread_id)
                                await recycle_conn.execute(
                                    "DELETE FROM recycle_checkpoint_blobs WHERE thread_id = $1", thread_id)
                                
                                logger.info("Cleanup completed from recycle bin")
                                cascade_restored = await self._perform_cascade_restoration(main_conn, thread_id, dry_run=False)
                                if cascade_restored > 0:
                                    logger.info(f"Cascade restored {cascade_restored} records")
                                
                            except Exception as e:
                                logger.error(f"Error during restore operation for thread_id {thread_id}: {e}")
                                stats.errors_count += 1
                                raise
            
            stats.execution_time = (datetime.now() - start_time).total_seconds()
            
            logger.info(f"Successfully completed restore operation for thread_id {thread_id}:")
            logger.info(f"  - Checkpoints: {stats.checkpoints_restored}")
            logger.info(f"  - Checkpoint writes: {stats.checkpoint_writes_restored}")
            logger.info(f"  - Checkpoint blobs: {stats.checkpoint_blobs_restored}")
            logger.info(f"  - Execution time: {stats.execution_time:.2f} seconds")
            
            return stats
            
        except Exception as e:
            logger.error(f"Failed to restore records for thread_id {thread_id}: {e}")
            return stats

    async def restore_records_by_days(self, days_back: int) -> RecycleStats:
        """
        Restore all records deleted within the last N days from recycle bin back to main tables.
        
        Args:
            days_back: Number of days back from now to restore records (e.g., 7 = restore all records deleted in last 7 days)
            
        Returns:
            RecycleStats object with restoration results
        """
        try:
            from datetime import timezone
            restore_cutoff_date = datetime.now(timezone.utc) - timedelta(days=days_back)
            
            logger.info(f"Starting restore operation for records deleted within the last {days_back} days (since {restore_cutoff_date})")
            
            stats = RecycleStats()
            start_time = datetime.now()
            
            if self.dry_run:
                logger.info("Running in DRY RUN mode - no actual restore operations will be performed")
                async with self.get_recycle_db_connection() as conn:
                    logger.info("Connecting to recycle database to fetch record counts")
                    checkpoints_count = await conn.fetchval(
                        "SELECT COUNT(*) FROM recycle_checkpoints WHERE deleted_date >= $1", restore_cutoff_date)
                    writes_count = await conn.fetchval(
                        "SELECT COUNT(*) FROM recycle_checkpoint_writes WHERE deleted_date >= $1", restore_cutoff_date)
                    blobs_count = await conn.fetchval(
                        "SELECT COUNT(*) FROM recycle_checkpoint_blobs WHERE deleted_date >= $1", restore_cutoff_date)
                    longterm_count = await conn.fetchval(
                        "SELECT COUNT(*) FROM recycle_longterm_memory WHERE deleted_date >= $1", restore_cutoff_date)

                    thread_ids = await conn.fetch("""
                        SELECT DISTINCT thread_id 
                        FROM recycle_checkpoints 
                        WHERE deleted_date >= $1
                        ORDER BY thread_id
                    """, restore_cutoff_date)
                    
                    total_count = checkpoints_count + writes_count + blobs_count + longterm_count
                    logger.info(f"DRY RUN: Would restore {total_count} records from {len(thread_ids)} thread(s)")
                    logger.info(f"  - Checkpoints: {checkpoints_count}")
                    logger.info(f"  - Checkpoint writes: {writes_count}")
                    logger.info(f"  - Checkpoint blobs: {blobs_count}")
                    logger.info(f"  - Longterm memory: {longterm_count}")
                    logger.info(f"  - Affected thread IDs: {[row['thread_id'] for row in thread_ids]}")
                    return stats
            
            logger.info("Establishing database connections for restore operation")
            async with self.get_recycle_db_connection() as recycle_conn:
                async with self.get_main_db_connection() as main_conn:
                    logger.info("Starting database transaction for restore operation")
                    async with main_conn.transaction():
                        async with recycle_conn.transaction():
                            try:
                                logger.info("Fetching checkpoints from recycle bin")
                                checkpoints = await recycle_conn.fetch("""
                                    SELECT thread_id, checkpoint_ns, checkpoint_id, parent_checkpoint_id,
                                           type, checkpoint, metadata
                                    FROM recycle_checkpoints WHERE deleted_date >= $1
                                    ORDER BY thread_id, checkpoint_ns, checkpoint_id
                                """, restore_cutoff_date)
                                
                                logger.info(f"Found {len(checkpoints)} checkpoints to restore")
                                for checkpoint in checkpoints:
                                    await main_conn.execute("""
                                        INSERT INTO checkpoints 
                                        (thread_id, checkpoint_ns, checkpoint_id, parent_checkpoint_id,
                                         type, checkpoint, metadata)
                                        VALUES ($1, $2, $3, $4, $5, $6, $7)
                                        ON CONFLICT (thread_id, checkpoint_ns, checkpoint_id) DO NOTHING
                                    """, 
                                    checkpoint['thread_id'], checkpoint['checkpoint_ns'], 
                                    checkpoint['checkpoint_id'], checkpoint['parent_checkpoint_id'],
                                    checkpoint['type'], checkpoint['checkpoint'], checkpoint['metadata'])
                                    
                                    stats.checkpoints_restored += 1
                                
                                logger.info(f"Restored {stats.checkpoints_restored} checkpoints to main database")
                                logger.info("Fetching checkpoint writes from recycle bin")
                                writes = await recycle_conn.fetch("""
                                    SELECT thread_id, checkpoint_ns, checkpoint_id, task_id, idx,
                                           channel, type, blob, task_path
                                    FROM recycle_checkpoint_writes 
                                    WHERE deleted_date >= $1 AND blob IS NOT NULL
                                    ORDER BY thread_id, checkpoint_ns, checkpoint_id, task_id, idx
                                """, restore_cutoff_date)
                                
                                logger.info(f"Found {len(writes)} checkpoint writes to restore")
                                for write in writes:
                                    await main_conn.execute("""
                                        INSERT INTO checkpoint_writes 
                                        (thread_id, checkpoint_ns, checkpoint_id, task_id, idx,
                                         channel, type, blob, task_path)
                                        VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
                                        ON CONFLICT (thread_id, checkpoint_ns, checkpoint_id, task_id, idx) DO NOTHING
                                    """, 
                                    write['thread_id'], write['checkpoint_ns'], write['checkpoint_id'],
                                    write['task_id'], write['idx'], write['channel'], 
                                    write['type'], write['blob'], write['task_path'])
                                    
                                    stats.checkpoint_writes_restored += 1
                                
                                logger.info(f"Restored {stats.checkpoint_writes_restored} checkpoint writes to main database")
                                logger.info("Fetching checkpoint blobs from recycle bin")
                                blobs = await recycle_conn.fetch("""
                                    SELECT thread_id, checkpoint_ns, channel, version, type, blob
                                    FROM recycle_checkpoint_blobs WHERE deleted_date >= $1
                                    ORDER BY thread_id, checkpoint_ns, channel, version
                                """, restore_cutoff_date)
                                
                                logger.info(f"Found {len(blobs)} checkpoint blobs to restore")
                                for blob in blobs:
                                    await main_conn.execute("""
                                        INSERT INTO checkpoint_blobs 
                                        (thread_id, checkpoint_ns, channel, version, type, blob)
                                        VALUES ($1, $2, $3, $4, $5, $6)
                                        ON CONFLICT (thread_id, checkpoint_ns, channel, version) DO NOTHING
                                    """, 
                                    blob['thread_id'], blob['checkpoint_ns'], blob['channel'],
                                    blob['version'], blob['type'], blob['blob'])
                                    
                                    stats.checkpoint_blobs_restored += 1
                                
                                logger.info(f"Restored {stats.checkpoint_blobs_restored} checkpoint blobs to main database")
                                logger.info("Fetching longterm memory records from recycle bin")
                                longterm_records = await recycle_conn.fetch("""
                                    SELECT table_name, session_id, start_timestamp, end_timestamp, 
                                           human_message, ai_message, response_time
                                    FROM recycle_longterm_memory 
                                    WHERE deleted_date >= $1
                                    ORDER BY table_name, session_id, end_timestamp
                                """, restore_cutoff_date)
                                
                                logger.info(f"Found {len(longterm_records)} longterm memory records to restore")
                                longterm_restored = 0
                                for longterm in longterm_records:
                                    table_exists = await check_table_exists(main_conn, longterm['table_name'])
                                    if not table_exists:
                                        logger.warning(f"Target table {longterm['table_name']} does not exist, skipping restore")
                                        continue
                                    
                                    await main_conn.execute(f"""
                                        INSERT INTO {longterm['table_name']} 
                                        (session_id, start_timestamp, end_timestamp, 
                                         human_message, ai_message, response_time)
                                        VALUES ($1, $2, $3, $4, $5, $6)
                                        ON CONFLICT (session_id, end_timestamp) DO NOTHING;
                                    """, 
                                    longterm['session_id'],
                                    longterm['start_timestamp'],
                                    longterm['end_timestamp'],
                                    longterm['human_message'],
                                    longterm['ai_message'],
                                    longterm['response_time'])
                                    longterm_restored += 1
                                
                                logger.info(f"Restored {longterm_restored} longterm memory records to main database")
                                logger.info("Cleaning up restored records from recycle bin")
                                writes_removed = await recycle_conn.execute(
                                    "DELETE FROM recycle_checkpoint_writes WHERE deleted_date >= $1", restore_cutoff_date)
                                checkpoints_removed = await recycle_conn.execute(
                                    "DELETE FROM recycle_checkpoints WHERE deleted_date >= $1", restore_cutoff_date)
                                blobs_removed = await recycle_conn.execute(
                                    "DELETE FROM recycle_checkpoint_blobs WHERE deleted_date >= $1", restore_cutoff_date)
                                longterm_removed = await recycle_conn.execute(
                                    "DELETE FROM recycle_longterm_memory WHERE deleted_date >= $1", restore_cutoff_date)
                                
                                logger.info(f"Cleanup completed - removed {writes_removed} checkpoint_writes, {checkpoints_removed} checkpoints, {blobs_removed} blobs, {longterm_removed} longterm records from recycle bin")
                                
                            except Exception as e:
                                logger.error(f"Error during restore operation for records from last {days_back} days: {e}")
                                stats.errors_count += 1
                                raise
            
            stats.execution_time = (datetime.now() - start_time).total_seconds()
            
            logger.info(f"Successfully completed restore operation for records from last {days_back} days:")
            logger.info(f"  - Checkpoints: {stats.checkpoints_restored}")
            logger.info(f"  - Checkpoint writes: {stats.checkpoint_writes_restored}")
            logger.info(f"  - Checkpoint blobs: {stats.checkpoint_blobs_restored}")
            logger.info(f"  - Longterm memory: {longterm_restored}")
            logger.info(f"  - Execution time: {stats.execution_time:.2f} seconds")
            
            return stats
        
        except Exception as e:
            logger.error(f"Failed to restore records from last {days_back} days: {e}")
            return stats

    async def get_recycle_bin_stats(self) -> Dict[str, int]:
        """Get current record counts in recycle bin tables."""
        stats = {}
        
        async with self.get_recycle_db_connection() as conn:
            tables = ['recycle_checkpoints', 'recycle_checkpoint_writes', 'recycle_checkpoint_blobs', 
                     'recycle_longterm_memory', 'recycle_tool', 'recycle_agent']
            for table in tables:
                count_query = f"SELECT COUNT(*) as count FROM {table};"
                result = await conn.fetchrow(count_query)
                stats[table] = result['count']
        
        return stats

    async def list_available_thread_ids(self, limit: int = 100) -> List[str]:
        """
        List thread IDs available in the recycle bin for restoration.
        
        Args:
            limit: Maximum number of thread IDs to return
            
        Returns:
            List of thread IDs available for restoration
        """
        async with self.get_recycle_db_connection() as conn:
            thread_ids = await conn.fetch("""
                SELECT DISTINCT thread_id, MAX(deleted_date) as latest_deletion
                FROM recycle_checkpoints 
                GROUP BY thread_id 
                ORDER BY latest_deletion DESC 
                LIMIT $1
            """, limit)
            
            return [row['thread_id'] for row in thread_ids]

    async def list_records_by_deletion_date(self, days_back: int = 7) -> Dict[str, any]:
        """
        List records available for restoration within the specified number of days.
        
        Args:
            days_back: Number of days back from now to check for records
            
        Returns:
            Dictionary with statistics about available records
        """
        from datetime import timezone
        cutoff_date = datetime.now(timezone.utc) - timedelta(days=days_back)
        
        logger.info(f"Listing records deleted within the last {days_back} days (since {cutoff_date})")
        
        async with self.get_recycle_db_connection() as conn:
            stats = await conn.fetchrow("""
                SELECT 
                    (SELECT COUNT(*) FROM recycle_checkpoints WHERE deleted_date >= $1) as checkpoints,
                    (SELECT COUNT(*) FROM recycle_checkpoint_writes WHERE deleted_date >= $1) as writes,
                    (SELECT COUNT(*) FROM recycle_checkpoint_blobs WHERE deleted_date >= $1) as blobs,
                    (SELECT COUNT(*) FROM recycle_longterm_memory WHERE deleted_date >= $1) as longterm,
                    (SELECT COUNT(DISTINCT thread_id) FROM recycle_checkpoints WHERE deleted_date >= $1) as unique_threads
            """, cutoff_date)

            thread_details = await conn.fetch("""
                SELECT 
                    thread_id,
                    MIN(deleted_date) as first_deletion,
                    MAX(deleted_date) as last_deletion,
                    COUNT(*) as checkpoint_count
                FROM recycle_checkpoints 
                WHERE deleted_date >= $1
                GROUP BY thread_id
                ORDER BY last_deletion DESC
            """, cutoff_date)
            
            result = {
                'total_checkpoints': stats['checkpoints'],
                'total_writes': stats['writes'],
                'total_blobs': stats['blobs'],
                'total_longterm': stats['longterm'],
                'unique_threads': stats['unique_threads'],
                'days_back': days_back,
                'cutoff_date': cutoff_date,
                'thread_details': []
            }
            
            for thread in thread_details:
                result['thread_details'].append({
                    'thread_id': thread['thread_id'],
                    'first_deletion': thread['first_deletion'],
                    'last_deletion': thread['last_deletion'],
                    'checkpoint_count': thread['checkpoint_count']
                })
            
            return result


async def main():
    """
    Main function for command-line usage of the recycle bin manager.
    """
    import argparse
    
    parser = argparse.ArgumentParser(description='Recycle Bin Manager for LangGraph Tables')
    parser.add_argument('--action', choices=['setup', 'cleanup', 'restore', 'restore-by-days', 'stats', 'list-threads', 'list-by-days'],
                       default='setup', help='Action to perform')
    parser.add_argument('--thread-id', type=str, help='Thread ID for restoration (use with --action restore)')
    parser.add_argument('--days', type=int, default=0, 
                       help='Days to keep in recycle bin for cleanup, or days back for restoration (default: 0)')
    parser.add_argument('--restore-days', type=int, 
                       help='Number of days back to restore records from (use with --action restore-by-days)')
    parser.add_argument('--dry-run', action='store_true',
                       help='Run in dry-run mode (no actual changes)')
    
    args = parser.parse_args()
    
    try:
        days_for_recycle_bin = 45 
        if args.action == 'cleanup' and args.days > 0:
            days_for_recycle_bin = args.days
        
        manager = RecycleBinManager(
            days_to_keep_in_recycle=days_for_recycle_bin,
            dry_run=args.dry_run
        )
        
        if args.action == 'setup':
            await manager.ensure_recycle_tables_exist()
            logger.info("Recycle bin setup completed successfully!")
            
        elif args.action == 'cleanup':
            deleted_count = await manager.cleanup_old_recycle_records()
            logger.info(f"Cleanup completed: {deleted_count} old records removed from recycle bin")
            
        elif args.action == 'restore':
            if not args.thread_id:
                logger.error("Thread ID is required for restoration")
                sys.exit(1)
            stats = await manager.restore_records_by_thread_id(args.thread_id)
            logger.info(f"Restoration completed for thread_id: {args.thread_id}")
            
        elif args.action == 'restore-by-days':
            restore_days = args.restore_days if args.restore_days is not None else args.days
            if restore_days <= 0:
                logger.error("Number of days must be specified and greater than 0 for restoration by days")
                logger.info("Use --restore-days N or --days N (where N > 0)")
                sys.exit(1)
            stats = await manager.restore_records_by_days(restore_days)
            logger.info(f"Restoration completed for records from last {restore_days} days")
            
        elif args.action == 'stats':
            stats = await manager.get_recycle_bin_stats()
            logger.info("Recycle bin statistics:")
            for table, count in stats.items():
                logger.info(f"  {table}: {count:,} records")
                
        elif args.action == 'list-threads':
            thread_ids = await manager.list_available_thread_ids()
            logger.info(f"Available thread IDs for restoration ({len(thread_ids)}):")
            for thread_id in thread_ids:
                logger.info(f"  {thread_id}")
                
        elif args.action == 'list-by-days':
            list_days = args.restore_days if args.restore_days is not None else (args.days if args.days > 0 else 7)
            records_info = await manager.list_records_by_deletion_date(list_days)
            logger.info(f"Records available for restoration from last {list_days} days:")
            logger.info(f"  - Total checkpoints: {records_info['total_checkpoints']:,}")
            logger.info(f"  - Total writes: {records_info['total_writes']:,}")
            logger.info(f"  - Total blobs: {records_info['total_blobs']:,}")
            logger.info(f"  - Total longterm memory: {records_info['total_longterm']:,}")
            logger.info(f"  - Unique threads: {records_info['unique_threads']}")
            logger.info(f"Thread details:")
            for thread in records_info['thread_details']:
                logger.info(f"    {thread['thread_id']}: {thread['checkpoint_count']} checkpoints, deleted {thread['last_deletion']}")
            
    except Exception as e:
        logger.error(f"Error running recycle bin manager: {e}")
        sys.exit(1)


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[
            logging.StreamHandler(sys.stdout)
        ]
    )

    asyncio.run(main())