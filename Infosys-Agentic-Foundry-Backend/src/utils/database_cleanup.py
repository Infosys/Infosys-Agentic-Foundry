#!/usr/bin/env python3
"""
Database Cleanup Script

This script performs hard delete or soft delete operations on core tables:
- agent_conversation_summary_table
- checkpoints, checkpoint_writes, checkpoint_blobs
- All tables with prefix 'table_' (long-term memory tables)

Hard Delete Mode:
    - Deletes all records from agent_conversation_summary_table and checkpoints tables
    - Drops all tables with prefix 'table_'
    
Soft Delete Mode:
    - Moves all records to recycle database
    - Also provides permanent deletion from recycle database

Author: AI Assistant
Date: February 3, 2026
"""

import psycopg2
import psycopg2.extras
import logging
from datetime import datetime
from typing import List, Dict, Any
import sys
import argparse
import os
from dotenv import load_dotenv

from src.config.constants import TableNames

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)


class DatabaseCleanup:
    """
    Handles hard delete and soft delete operations on core database tables
    """
    
    def __init__(self, main_db_config: Dict[str, str], recycle_db_config: Dict[str, str] = None):
        """
        Initialize the cleanup handler
        
        Args:
            main_db_config: Database configuration for main database
            recycle_db_config: Database configuration for recycle database (required for soft delete)
        """
        self.main_db_config = main_db_config
        self.recycle_db_config = recycle_db_config
        self.main_conn = None
        self.recycle_conn = None
        
        # Define target tables
        self.summary_table = "agent_conversation_summary_table"
        self.checkpoint_tables = {
            "checkpoints": TableNames.CHECKPOINTS.value,
            "checkpoint_writes": TableNames.CHECKPOINT_WRITES.value,
            "checkpoint_blobs": TableNames.CHECKPOINT_BLOBS.value
        }
        
    def connect_main_database(self):
        """Connect to main database"""
        try:
            if self.main_conn is None or self.main_conn.closed:
                self.main_conn = psycopg2.connect(**self.main_db_config)
                self.main_conn.autocommit = False
                logger.info("Connected to main database successfully")
        except Exception as e:
            logger.error(f"Error connecting to main database: {e}")
            raise
            
    def connect_recycle_database(self):
        """Connect to recycle database"""
        try:
            if self.recycle_conn is None or self.recycle_conn.closed:
                self.recycle_conn = psycopg2.connect(**self.recycle_db_config)
                self.recycle_conn.autocommit = False
                logger.info("Connected to recycle database successfully")
        except Exception as e:
            logger.error(f"Error connecting to recycle database: {e}")
            raise
            
    def close_connections(self):
        """Close database connections"""
        if self.main_conn and not self.main_conn.closed:
            self.main_conn.close()
            logger.info("Main database connection closed")
        if self.recycle_conn and not self.recycle_conn.closed:
            self.recycle_conn.close()
            logger.info("Recycle database connection closed")
            
    def get_tables_with_prefix(self, prefix: str = "table_") -> List[str]:
        """
        Get all table names that start with the specified prefix
        
        Args:
            prefix: Table name prefix to search for
            
        Returns:
            List of table names
        """
        try:
            cursor = self.main_conn.cursor()
            cursor.execute("""
                SELECT tablename 
                FROM pg_tables 
                WHERE schemaname = 'public' 
                AND tablename LIKE %s
            """, (f"{prefix}%",))
            
            tables = [row[0] for row in cursor.fetchall()]
            cursor.close()
            logger.info(f"Found {len(tables)} tables with prefix '{prefix}'")
            return tables
            
        except Exception as e:
            logger.error(f"Error getting tables with prefix '{prefix}': {e}")
            raise
    
    def get_record_counts(self) -> Dict[str, int]:
        """
        Get record counts from all target tables
        
        Returns:
            Dictionary mapping table names to record counts
        """
        counts = {}
        
        try:
            cursor = self.main_conn.cursor()
            
            # Count summary table records
            cursor.execute(f"SELECT COUNT(*) FROM {self.summary_table}")
            counts[self.summary_table] = cursor.fetchone()[0]
            
            # Count checkpoint table records
            for name, table in self.checkpoint_tables.items():
                cursor.execute(f"SELECT COUNT(*) FROM {table}")
                counts[name] = cursor.fetchone()[0]
            
            # Count records in tables with 'table_' prefix
            table_prefix_tables = self.get_tables_with_prefix("table_")
            for table in table_prefix_tables:
                cursor.execute(f"SELECT COUNT(*) FROM {table}")
                counts[table] = cursor.fetchone()[0]
            
            cursor.close()
            return counts
            
        except Exception as e:
            logger.error(f"Error getting record counts: {e}")
            raise
    
    def hard_delete_all(self, dry_run: bool = False) -> Dict[str, Any]:
        """
        Perform hard delete on all target tables
        
        Args:
            dry_run: If True, only show what would be deleted without actually deleting
            
        Returns:
            Dictionary with deletion results
        """
        logger.info("=" * 80)
        logger.info("HARD DELETE MODE")
        logger.info("=" * 80)
        
        self.connect_main_database()
        
        results = {
            "mode": "hard_delete",
            "dry_run": dry_run,
            "deleted_records": {},
            "dropped_tables": [],
            "errors": []
        }
        
        try:
            # Get initial counts
            logger.info("\nGetting record counts before deletion...")
            counts = self.get_record_counts()
            
            logger.info("\nCurrent record counts:")
            total_records = 0
            for table, count in counts.items():
                logger.info(f"  {table}: {count:,} records")
                total_records += count
            logger.info(f"  TOTAL: {total_records:,} records")
            
            if dry_run:
                logger.info("\n[DRY RUN] - No actual deletions will be performed")
                results["would_delete_records"] = total_records
                return results
            
            cursor = self.main_conn.cursor()
            
            # Truncate agent_conversation_summary_table
            logger.info(f"\nTruncating {self.summary_table}...")
            cursor.execute(f"TRUNCATE TABLE {self.summary_table} RESTART IDENTITY CASCADE")
            results["deleted_records"][self.summary_table] = counts.get(self.summary_table, 0)
            logger.info(f"✓ Truncated {self.summary_table} ({counts.get(self.summary_table, 0):,} records)")
            
            # Truncate checkpoint tables
            for name, table in self.checkpoint_tables.items():
                logger.info(f"\nTruncating {name} ({table})...")
                cursor.execute(f"TRUNCATE TABLE {table} RESTART IDENTITY CASCADE")
                results["deleted_records"][name] = counts.get(name, 0)
                logger.info(f"✓ Truncated {name} ({counts.get(name, 0):,} records)")
            
            # Drop tables with 'table_' prefix
            logger.info("\nDropping tables with 'table_' prefix...")
            table_prefix_tables = self.get_tables_with_prefix("table_")
            
            for table in table_prefix_tables:
                try:
                    logger.info(f"  Dropping table: {table}")
                    cursor.execute(f"DROP TABLE IF EXISTS {table} CASCADE")
                    results["dropped_tables"].append(table)
                    logger.info(f"  ✓ Dropped table: {table}")
                except Exception as e:
                    error_msg = f"Failed to drop table {table}: {e}"
                    logger.error(f"  ✗ {error_msg}")
                    results["errors"].append(error_msg)
            
            # Commit transaction
            self.main_conn.commit()
            cursor.close()
            
            logger.info("\n" + "=" * 80)
            logger.info("HARD DELETE COMPLETED SUCCESSFULLY")
            logger.info("=" * 80)
            logger.info(f"Total records deleted: {sum(results['deleted_records'].values()):,}")
            logger.info(f"Total tables dropped: {len(results['dropped_tables'])}")
            
            if results["errors"]:
                logger.warning(f"Errors encountered: {len(results['errors'])}")
            
        except Exception as e:
            self.main_conn.rollback()
            logger.error(f"Error during hard delete: {e}")
            results["errors"].append(str(e))
            raise
        finally:
            self.close_connections()
        
        return results
    
    def create_recycle_tables(self):
        """Create recycle tables if they don't exist"""
        try:
            cursor = self.recycle_conn.cursor()
            
            # Create recycle_agent_conversation_summary_table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS recycle_agent_conversation_summary_table (
                    agentic_application_id TEXT,
                    session_id TEXT,
                    summary TEXT,
                    preference TEXT,
                    created_on TIMESTAMPTZ,
                    updated_on TIMESTAMPTZ,
                    deleted_date TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
                );
            """)
            logger.info("✓ Created/verified recycle_agent_conversation_summary_table")
            
            # Create recycle_checkpoints
            cursor.execute(f"""
                CREATE TABLE IF NOT EXISTS {TableNames.RECYCLE_CHECKPOINTS.value} (
                    thread_id TEXT NOT NULL,
                    checkpoint_ns TEXT NOT NULL DEFAULT '',
                    checkpoint_id TEXT NOT NULL,
                    parent_checkpoint_id TEXT,
                    type TEXT,
                    checkpoint JSONB NOT NULL,
                    metadata JSONB NOT NULL DEFAULT '{{}}'::jsonb,
                    deleted_date TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
                );
            """)
            logger.info(f"✓ Created/verified {TableNames.RECYCLE_CHECKPOINTS.value}")
            
            # Create recycle_checkpoint_writes
            cursor.execute(f"""
                CREATE TABLE IF NOT EXISTS {TableNames.RECYCLE_CHECKPOINT_WRITES.value} (
                    thread_id TEXT NOT NULL,
                    checkpoint_ns TEXT NOT NULL DEFAULT '',
                    checkpoint_id TEXT NOT NULL,
                    task_id TEXT NOT NULL,
                    idx INTEGER NOT NULL,
                    channel TEXT NOT NULL,
                    type TEXT,
                    blob BYTEA NOT NULL,
                    task_path TEXT NOT NULL DEFAULT '',
                    deleted_date TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
                );
            """)
            logger.info(f"✓ Created/verified {TableNames.RECYCLE_CHECKPOINT_WRITES.value}")
            
            # Create recycle_checkpoint_blobs
            cursor.execute(f"""
                CREATE TABLE IF NOT EXISTS {TableNames.RECYCLE_CHECKPOINT_BLOBS.value} (
                    thread_id TEXT NOT NULL,
                    checkpoint_ns TEXT NOT NULL DEFAULT '',
                    channel TEXT NOT NULL,
                    version TEXT NOT NULL,
                    type TEXT NOT NULL,
                    blob BYTEA,
                    deleted_date TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
                );
            """)
            logger.info(f"✓ Created/verified {TableNames.RECYCLE_CHECKPOINT_BLOBS.value}")
            
            # Create recycle_longterm_memory
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS recycle_longterm_memory (
                    table_name TEXT NOT NULL,
                    session_id TEXT NOT NULL,
                    start_timestamp TIMESTAMP,
                    end_timestamp TIMESTAMP NOT NULL,
                    human_message TEXT,
                    ai_message TEXT,
                    response_time DOUBLE PRECISION,
                    deleted_date TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
            """)
            logger.info("✓ Created/verified recycle_longterm_memory")
            
            self.recycle_conn.commit()
            cursor.close()
            
        except Exception as e:
            self.recycle_conn.rollback()
            logger.error(f"Error creating recycle tables: {e}")
            raise
    
    def soft_delete_all(self, dry_run: bool = False) -> Dict[str, Any]:
        """
        Perform soft delete by moving all records to recycle database
        
        Args:
            dry_run: If True, only show what would be moved without actually moving
            
        Returns:
            Dictionary with deletion results
        """
        logger.info("=" * 80)
        logger.info("SOFT DELETE MODE")
        logger.info("=" * 80)
        
        if not self.recycle_db_config:
            raise ValueError("Recycle database configuration required for soft delete")
        
        self.connect_main_database()
        self.connect_recycle_database()
        
        results = {
            "mode": "soft_delete",
            "dry_run": dry_run,
            "moved_records": {},
            "moved_tables": {},
            "errors": []
        }
        
        try:
            # Create recycle tables
            logger.info("\nEnsuring recycle tables exist...")
            self.create_recycle_tables()
            
            # Get initial counts
            logger.info("\nGetting record counts before soft deletion...")
            counts = self.get_record_counts()
            
            logger.info("\nCurrent record counts:")
            total_records = 0
            for table, count in counts.items():
                logger.info(f"  {table}: {count:,} records")
                total_records += count
            logger.info(f"  TOTAL: {total_records:,} records")
            
            if dry_run:
                logger.info("\n[DRY RUN] - No actual moves will be performed")
                results["would_move_records"] = total_records
                return results
            
            deleted_date = datetime.now()
            main_cursor = self.main_conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
            recycle_cursor = self.recycle_conn.cursor()
            
            # Move agent_conversation_summary_table records
            logger.info(f"\nMoving records from {self.summary_table}...")
            main_cursor.execute(f"SELECT * FROM {self.summary_table}")
            records = main_cursor.fetchall()
            
            moved_count = 0
            for record in records:
                try:
                    recycle_cursor.execute("""
                        INSERT INTO recycle_agent_conversation_summary_table 
                        (agentic_application_id, session_id, summary, preference, created_on, updated_on, deleted_date)
                        VALUES (%s, %s, %s, %s, %s, %s, %s)
                    """, (
                        record['agentic_application_id'],
                        record['session_id'],
                        record.get('summary'),
                        record.get('preference'),
                        record.get('created_on'),
                        record.get('updated_on'),
                        deleted_date
                    ))
                    moved_count += 1
                except Exception as e:
                    logger.error(f"Error moving summary record: {e}")
                    results["errors"].append(f"Summary record move error: {e}")
            
            # Delete from main database
            main_cursor.execute(f"DELETE FROM {self.summary_table}")
            results["moved_records"][self.summary_table] = moved_count
            logger.info(f"✓ Moved {moved_count:,} records from {self.summary_table}")
            
            # Move checkpoint records
            for name, table in self.checkpoint_tables.items():
                logger.info(f"\nMoving records from {name} ({table})...")
                main_cursor.execute(f"SELECT * FROM {table}")
                records = main_cursor.fetchall()
                
                moved_count = 0
                recycle_table = f"recycle_{table}"
                
                for record in records:
                    try:
                        if name == "checkpoints":
                            recycle_cursor.execute(f"""
                                INSERT INTO {recycle_table}
                                (thread_id, checkpoint_ns, checkpoint_id, parent_checkpoint_id, type, checkpoint, metadata, deleted_date)
                                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                            """, (
                                record['thread_id'],
                                record.get('checkpoint_ns', ''),
                                record['checkpoint_id'],
                                record.get('parent_checkpoint_id'),
                                record.get('type'),
                                psycopg2.extras.Json(record['checkpoint']) if isinstance(record['checkpoint'], dict) else record['checkpoint'],
                                psycopg2.extras.Json(record.get('metadata', {})) if isinstance(record.get('metadata'), dict) else record.get('metadata'),
                                deleted_date
                            ))
                        elif name == "checkpoint_writes":
                            recycle_cursor.execute(f"""
                                INSERT INTO {recycle_table}
                                (thread_id, checkpoint_ns, checkpoint_id, task_id, idx, channel, type, blob, task_path, deleted_date)
                                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                            """, (
                                record['thread_id'],
                                record.get('checkpoint_ns', ''),
                                record['checkpoint_id'],
                                record['task_id'],
                                record['idx'],
                                record['channel'],
                                record.get('type'),
                                record['blob'],
                                record.get('task_path', ''),
                                deleted_date
                            ))
                        elif name == "checkpoint_blobs":
                            recycle_cursor.execute(f"""
                                INSERT INTO {recycle_table}
                                (thread_id, checkpoint_ns, channel, version, type, blob, deleted_date)
                                VALUES (%s, %s, %s, %s, %s, %s, %s)
                            """, (
                                record['thread_id'],
                                record.get('checkpoint_ns', ''),
                                record['channel'],
                                record['version'],
                                record['type'],
                                record.get('blob'),
                                deleted_date
                            ))
                        moved_count += 1
                    except Exception as e:
                        logger.error(f"Error moving {name} record: {e}")
                        results["errors"].append(f"{name} record move error: {e}")
                
                # Delete from main database
                main_cursor.execute(f"DELETE FROM {table}")
                results["moved_records"][name] = moved_count
                logger.info(f"✓ Moved {moved_count:,} records from {name}")
            
            # Move records from tables with 'table_' prefix
            logger.info("\nMoving records from tables with 'table_' prefix...")
            table_prefix_tables = self.get_tables_with_prefix("table_")
            
            for table in table_prefix_tables:
                try:
                    logger.info(f"  Processing table: {table}")
                    main_cursor.execute(f"SELECT * FROM {table}")
                    records = main_cursor.fetchall()
                    
                    moved_count = 0
                    for record in records:
                        try:
                            recycle_cursor.execute("""
                                INSERT INTO recycle_longterm_memory
                                (table_name, session_id, start_timestamp, end_timestamp, human_message, ai_message, response_time, deleted_date)
                                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                            """, (
                                table,
                                record['session_id'],
                                record.get('start_timestamp'),
                                record['end_timestamp'],
                                record.get('human_message'),
                                record.get('ai_message'),
                                record.get('response_time'),
                                deleted_date
                            ))
                            moved_count += 1
                        except Exception as e:
                            logger.error(f"Error moving record from {table}: {e}")
                            results["errors"].append(f"{table} record move error: {e}")
                    
                    # Delete from main database
                    main_cursor.execute(f"DELETE FROM {table}")
                    results["moved_tables"][table] = moved_count
                    logger.info(f"  ✓ Moved {moved_count:,} records from {table}")
                    
                except Exception as e:
                    error_msg = f"Failed to process table {table}: {e}"
                    logger.error(f"  ✗ {error_msg}")
                    results["errors"].append(error_msg)
            
            # Commit both connections
            self.main_conn.commit()
            self.recycle_conn.commit()
            main_cursor.close()
            recycle_cursor.close()
            
            logger.info("\n" + "=" * 80)
            logger.info("SOFT DELETE COMPLETED SUCCESSFULLY")
            logger.info("=" * 80)
            total_moved = sum(results['moved_records'].values()) + sum(results['moved_tables'].values())
            logger.info(f"Total records moved: {total_moved:,}")
            
            if results["errors"]:
                logger.warning(f"Errors encountered: {len(results['errors'])}")
            
        except Exception as e:
            self.main_conn.rollback()
            self.recycle_conn.rollback()
            logger.error(f"Error during soft delete: {e}")
            results["errors"].append(str(e))
            raise
        finally:
            self.close_connections()
        
        return results
    
    def permanent_delete_from_recycle(self, dry_run: bool = False) -> Dict[str, Any]:
        """
        Permanently delete all records from recycle database
        
        Args:
            dry_run: If True, only show what would be deleted without actually deleting
            
        Returns:
            Dictionary with deletion results
        """
        logger.info("=" * 80)
        logger.info("PERMANENT DELETE FROM RECYCLE DATABASE")
        logger.info("=" * 80)
        
        if not self.recycle_db_config:
            raise ValueError("Recycle database configuration required")
        
        self.connect_recycle_database()
        
        results = {
            "mode": "permanent_delete_from_recycle",
            "dry_run": dry_run,
            "deleted_records": {},
            "errors": []
        }
        
        try:
            cursor = self.recycle_conn.cursor()
            
            # Get counts
            recycle_tables = {
                "recycle_agent_conversation_summary_table": "recycle_agent_conversation_summary_table",
                "recycle_checkpoints": TableNames.RECYCLE_CHECKPOINTS.value,
                "recycle_checkpoint_writes": TableNames.RECYCLE_CHECKPOINT_WRITES.value,
                "recycle_checkpoint_blobs": TableNames.RECYCLE_CHECKPOINT_BLOBS.value,
                "recycle_longterm_memory": "recycle_longterm_memory"
            }
            
            logger.info("\nCurrent record counts in recycle database:")
            total_records = 0
            for name, table in recycle_tables.items():
                try:
                    cursor.execute(f"SELECT COUNT(*) FROM {table}")
                    count = cursor.fetchone()[0]
                    logger.info(f"  {name}: {count:,} records")
                    total_records += count
                except Exception as e:
                    logger.warning(f"  {name}: Table not found or error: {e}")
            
            logger.info(f"  TOTAL: {total_records:,} records")
            
            if dry_run:
                logger.info("\n[DRY RUN] - No actual deletions will be performed")
                results["would_delete_records"] = total_records
                return results
            
            # Delete from recycle tables
            for name, table in recycle_tables.items():
                try:
                    logger.info(f"\nDeleting records from {name}...")
                    cursor.execute(f"DELETE FROM {table}")
                    deleted_count = cursor.rowcount
                    results["deleted_records"][name] = deleted_count
                    logger.info(f"✓ Deleted {deleted_count:,} records from {name}")
                except Exception as e:
                    error_msg = f"Failed to delete from {name}: {e}"
                    logger.error(f"✗ {error_msg}")
                    results["errors"].append(error_msg)
            
            # Commit transaction
            self.recycle_conn.commit()
            cursor.close()
            
            logger.info("\n" + "=" * 80)
            logger.info("PERMANENT DELETE COMPLETED SUCCESSFULLY")
            logger.info("=" * 80)
            logger.info(f"Total records permanently deleted: {sum(results['deleted_records'].values()):,}")
            
            if results["errors"]:
                logger.warning(f"Errors encountered: {len(results['errors'])}")
            
        except Exception as e:
            self.recycle_conn.rollback()
            logger.error(f"Error during permanent delete: {e}")
            results["errors"].append(str(e))
            raise
        finally:
            self.close_connections()
        
        return results
    
    def restore_all_from_recycle(self, dry_run: bool = False) -> Dict[str, Any]:
        """
        Restore ALL records from recycle database back to main database
        
        Args:
            dry_run: If True, only show what would be restored without actually restoring
            
        Returns:
            Dictionary with restoration results
        """
        logger.info("=" * 80)
        logger.info("RESTORE ALL FROM RECYCLE DATABASE")
        logger.info("=" * 80)
        
        if not self.recycle_db_config:
            raise ValueError("Recycle database configuration required")
        
        self.connect_main_database()
        self.connect_recycle_database()
        
        results = {
            "mode": "restore_all",
            "dry_run": dry_run,
            "restored_records": {},
            "restored_tables": [],
            "errors": []
        }
        
        try:
            main_cursor = self.main_conn.cursor()
            recycle_cursor = self.recycle_conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
            
            # Get counts from recycle database
            logger.info("\nCurrent record counts in recycle database:")
            
            # Count summary records
            recycle_cursor.execute("SELECT COUNT(*) FROM recycle_agent_conversation_summary_table")
            summary_count = recycle_cursor.fetchone()[0]
            logger.info(f"  recycle_agent_conversation_summary_table: {summary_count:,} records")
            
            # Count checkpoint records
            recycle_cursor.execute(f"SELECT COUNT(*) FROM {TableNames.RECYCLE_CHECKPOINTS.value}")
            checkpoints_count = recycle_cursor.fetchone()[0]
            logger.info(f"  recycle_checkpoints: {checkpoints_count:,} records")
            
            recycle_cursor.execute(f"SELECT COUNT(*) FROM {TableNames.RECYCLE_CHECKPOINT_WRITES.value}")
            writes_count = recycle_cursor.fetchone()[0]
            logger.info(f"  recycle_checkpoint_writes: {writes_count:,} records")
            
            recycle_cursor.execute(f"SELECT COUNT(*) FROM {TableNames.RECYCLE_CHECKPOINT_BLOBS.value}")
            blobs_count = recycle_cursor.fetchone()[0]
            logger.info(f"  recycle_checkpoint_blobs: {blobs_count:,} records")
            
            # Count longterm memory records and get unique table names
            recycle_cursor.execute("SELECT COUNT(*) FROM recycle_longterm_memory")
            longterm_count = recycle_cursor.fetchone()[0]
            logger.info(f"  recycle_longterm_memory: {longterm_count:,} records")
            
            recycle_cursor.execute("SELECT DISTINCT table_name FROM recycle_longterm_memory")
            longterm_tables = [row[0] for row in recycle_cursor.fetchall()]
            logger.info(f"  Unique table_ tables to restore: {len(longterm_tables)}")
            
            total_records = summary_count + checkpoints_count + writes_count + blobs_count + longterm_count
            logger.info(f"  TOTAL: {total_records:,} records")
            
            if dry_run:
                logger.info("\n[DRY RUN] - No actual restoration will be performed")
                results["would_restore_records"] = total_records
                return results
            
            # Restore agent_conversation_summary_table
            logger.info(f"\nRestoring agent_conversation_summary_table...")
            recycle_cursor.execute("""
                SELECT agentic_application_id, session_id, summary, preference, created_on, updated_on
                FROM recycle_agent_conversation_summary_table
            """)
            records = recycle_cursor.fetchall()
            
            restored_count = 0
            for record in records:
                try:
                    main_cursor.execute("""
                        INSERT INTO agent_conversation_summary_table
                        (agentic_application_id, session_id, summary, preference, created_on, updated_on)
                        VALUES (%s, %s, %s, %s, %s, %s)
                        ON CONFLICT DO NOTHING
                    """, (
                        record['agentic_application_id'],
                        record['session_id'],
                        record.get('summary'),
                        record.get('preference'),
                        record.get('created_on'),
                        record.get('updated_on')
                    ))
                    if main_cursor.rowcount > 0:
                        restored_count += 1
                except Exception as e:
                    logger.error(f"Error restoring summary record: {e}")
                    results["errors"].append(f"Summary restore error: {e}")
            
            results["restored_records"]["agent_conversation_summary_table"] = restored_count
            logger.info(f"✓ Restored {restored_count:,} records to agent_conversation_summary_table")
            
            # Restore checkpoints
            logger.info(f"\nRestoring checkpoints...")
            recycle_cursor.execute(f"""
                SELECT thread_id, checkpoint_ns, checkpoint_id, parent_checkpoint_id, type, checkpoint, metadata
                FROM {TableNames.RECYCLE_CHECKPOINTS.value}
            """)
            records = recycle_cursor.fetchall()
            
            restored_count = 0
            for record in records:
                try:
                    checkpoint_data = record['checkpoint']
                    metadata_data = record.get('metadata', {})
                    
                    # Handle JSON serialization
                    if isinstance(checkpoint_data, dict):
                        checkpoint_data = psycopg2.extras.Json(checkpoint_data)
                    if isinstance(metadata_data, dict):
                        metadata_data = psycopg2.extras.Json(metadata_data)
                    
                    main_cursor.execute(f"""
                        INSERT INTO {TableNames.CHECKPOINTS.value}
                        (thread_id, checkpoint_ns, checkpoint_id, parent_checkpoint_id, type, checkpoint, metadata)
                        VALUES (%s, %s, %s, %s, %s, %s, %s)
                        ON CONFLICT DO NOTHING
                    """, (
                        record['thread_id'],
                        record.get('checkpoint_ns', ''),
                        record['checkpoint_id'],
                        record.get('parent_checkpoint_id'),
                        record.get('type'),
                        checkpoint_data,
                        metadata_data
                    ))
                    if main_cursor.rowcount > 0:
                        restored_count += 1
                except Exception as e:
                    logger.error(f"Error restoring checkpoint record: {e}")
                    results["errors"].append(f"Checkpoint restore error: {e}")
            
            results["restored_records"]["checkpoints"] = restored_count
            logger.info(f"✓ Restored {restored_count:,} records to checkpoints")
            
            # Restore checkpoint_writes
            logger.info(f"\nRestoring checkpoint_writes...")
            recycle_cursor.execute(f"""
                SELECT thread_id, checkpoint_ns, checkpoint_id, task_id, idx, channel, type, blob, task_path
                FROM {TableNames.RECYCLE_CHECKPOINT_WRITES.value}
            """)
            records = recycle_cursor.fetchall()
            
            restored_count = 0
            for record in records:
                try:
                    main_cursor.execute(f"""
                        INSERT INTO {TableNames.CHECKPOINT_WRITES.value}
                        (thread_id, checkpoint_ns, checkpoint_id, task_id, idx, channel, type, blob, task_path)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                        ON CONFLICT DO NOTHING
                    """, (
                        record['thread_id'],
                        record.get('checkpoint_ns', ''),
                        record['checkpoint_id'],
                        record['task_id'],
                        record['idx'],
                        record['channel'],
                        record.get('type'),
                        record['blob'],
                        record.get('task_path', '')
                    ))
                    if main_cursor.rowcount > 0:
                        restored_count += 1
                except Exception as e:
                    logger.error(f"Error restoring checkpoint_writes record: {e}")
                    results["errors"].append(f"Checkpoint writes restore error: {e}")
            
            results["restored_records"]["checkpoint_writes"] = restored_count
            logger.info(f"✓ Restored {restored_count:,} records to checkpoint_writes")
            
            # Restore checkpoint_blobs
            logger.info(f"\nRestoring checkpoint_blobs...")
            recycle_cursor.execute(f"""
                SELECT thread_id, checkpoint_ns, channel, version, type, blob
                FROM {TableNames.RECYCLE_CHECKPOINT_BLOBS.value}
            """)
            records = recycle_cursor.fetchall()
            
            restored_count = 0
            for record in records:
                try:
                    main_cursor.execute(f"""
                        INSERT INTO {TableNames.CHECKPOINT_BLOBS.value}
                        (thread_id, checkpoint_ns, channel, version, type, blob)
                        VALUES (%s, %s, %s, %s, %s, %s)
                        ON CONFLICT DO NOTHING
                    """, (
                        record['thread_id'],
                        record.get('checkpoint_ns', ''),
                        record['channel'],
                        record['version'],
                        record['type'],
                        record.get('blob')
                    ))
                    if main_cursor.rowcount > 0:
                        restored_count += 1
                except Exception as e:
                    logger.error(f"Error restoring checkpoint_blobs record: {e}")
                    results["errors"].append(f"Checkpoint blobs restore error: {e}")
            
            results["restored_records"]["checkpoint_blobs"] = restored_count
            logger.info(f"✓ Restored {restored_count:,} records to checkpoint_blobs")
            
            # Restore longterm memory tables (table_* prefix)
            logger.info(f"\nRestoring longterm memory tables...")
            
            for table_name in longterm_tables:
                try:
                    # Create table if not exists
                    main_cursor.execute(f"""
                        CREATE TABLE IF NOT EXISTS {table_name} (
                            session_id TEXT,
                            start_timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                            end_timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                            human_message TEXT,
                            ai_message TEXT,
                            response_time DOUBLE PRECISION
                        )
                    """)
                    
                    # Get records for this table
                    recycle_cursor.execute("""
                        SELECT session_id, start_timestamp, end_timestamp, human_message, ai_message, response_time
                        FROM recycle_longterm_memory
                        WHERE table_name = %s
                    """, (table_name,))
                    records = recycle_cursor.fetchall()
                    
                    restored_count = 0
                    for record in records:
                        try:
                            main_cursor.execute(f"""
                                INSERT INTO {table_name}
                                (session_id, start_timestamp, end_timestamp, human_message, ai_message, response_time)
                                VALUES (%s, %s, %s, %s, %s, %s)
                            """, (
                                record['session_id'],
                                record.get('start_timestamp'),
                                record['end_timestamp'],
                                record.get('human_message'),
                                record.get('ai_message'),
                                record.get('response_time')
                            ))
                            restored_count += 1
                        except Exception as e:
                            logger.error(f"Error restoring record to {table_name}: {e}")
                            results["errors"].append(f"{table_name} restore error: {e}")
                    
                    results["restored_tables"].append({"table": table_name, "records": restored_count})
                    logger.info(f"  ✓ Restored {restored_count:,} records to {table_name}")
                    
                except Exception as e:
                    error_msg = f"Failed to restore table {table_name}: {e}"
                    logger.error(f"  ✗ {error_msg}")
                    results["errors"].append(error_msg)
            
            # Commit main database changes
            self.main_conn.commit()
            
            # Clear recycle database after successful restore
            logger.info("\nClearing recycle database after restore...")
            recycle_cursor.execute("DELETE FROM recycle_agent_conversation_summary_table")
            recycle_cursor.execute(f"DELETE FROM {TableNames.RECYCLE_CHECKPOINTS.value}")
            recycle_cursor.execute(f"DELETE FROM {TableNames.RECYCLE_CHECKPOINT_WRITES.value}")
            recycle_cursor.execute(f"DELETE FROM {TableNames.RECYCLE_CHECKPOINT_BLOBS.value}")
            recycle_cursor.execute("DELETE FROM recycle_longterm_memory")
            self.recycle_conn.commit()
            logger.info("✓ Recycle database cleared")
            
            main_cursor.close()
            recycle_cursor.close()
            
            logger.info("\n" + "=" * 80)
            logger.info("RESTORE COMPLETED SUCCESSFULLY")
            logger.info("=" * 80)
            total_restored = sum(results['restored_records'].values())
            for table_info in results['restored_tables']:
                total_restored += table_info['records']
            logger.info(f"Total records restored: {total_restored:,}")
            
            if results["errors"]:
                logger.warning(f"Errors encountered: {len(results['errors'])}")
            
        except Exception as e:
            self.main_conn.rollback()
            self.recycle_conn.rollback()
            logger.error(f"Error during restore: {e}")
            results["errors"].append(str(e))
            raise
        finally:
            self.close_connections()
        
        return results


def get_db_configs(recycle_db_name: str = "recycle") -> tuple:
    """
    Get database configurations from environment variables
    
    Args:
        recycle_db_name: Name of the recycle database (default: 'recycle')
        
    Returns:
        Tuple of (main_db_config, recycle_db_config)
    """
    # Get common database connection parameters
    db_host = os.getenv("POSTGRESQL_HOST", "")
    db_port = os.getenv("POSTGRESQL_PORT", "")
    db_user = os.getenv("POSTGRESQL_USER", "")
    db_password = os.getenv("POSTGRESQL_PASSWORD", "")
    main_db_name = os.getenv("DATABASE", "")
    
    main_db_config = {
        "dbname": main_db_name,
        "user": db_user,
        "password": db_password,
        "host": db_host,
        "port": db_port
    }
    
    recycle_db_config = {
        "dbname": recycle_db_name,
        "user": db_user,
        "password": db_password,
        "host": db_host,
        "port": db_port
    }
    
    return main_db_config, recycle_db_config


def main():
    """Main execution function"""
    # Load environment variables from the project root
    project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
    env_path = os.path.join(project_root, '.env')
    load_dotenv(env_path)
    
    parser = argparse.ArgumentParser(
        description='Database Cleanup Script - Hard Delete, Soft Delete, or Restore Operations',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Dry run hard delete (see what would be deleted)
  python -m src.utils.database_cleanup --mode hard --dry-run

  # Perform hard delete (PERMANENT - truncates tables and drops table_* tables)
  python -m src.utils.database_cleanup --mode hard

  # Dry run soft delete (see what would be moved)
  python -m src.utils.database_cleanup --mode soft --dry-run

  # Perform soft delete (move to recycle database)
  python -m src.utils.database_cleanup --mode soft

  # Restore all data from recycle database back to main database
  python -m src.utils.database_cleanup --mode restore --dry-run
  python -m src.utils.database_cleanup --mode restore

  # Permanently delete from recycle database
  python -m src.utils.database_cleanup --mode permanent-recycle --dry-run
  python -m src.utils.database_cleanup --mode permanent-recycle
        """
    )
    
    parser.add_argument(
        '--mode',
        required=True,
        choices=['hard', 'soft', 'restore', 'permanent-recycle'],
        help='Operation mode: hard (permanent delete), soft (move to recycle), restore (restore from recycle), permanent-recycle (delete from recycle)'
    )
    
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Perform a dry run without making changes'
    )
    
    parser.add_argument(
        '--recycle-db',
        type=str,
        default='recycle',
        help='Recycle database name (default: recycle)'
    )
    
    args = parser.parse_args()
    
    try:
        # Get database configurations
        main_db_config, recycle_db_config = get_db_configs(args.recycle_db)
        
        # Log database info
        logger.info(f"Using main database: {main_db_config['dbname']}")
        logger.info(f"Using recycle database: {recycle_db_config['dbname']}")
        logger.info(f"Database host: {main_db_config['host']}:{main_db_config['port']}")
        
        # For hard delete, we don't need recycle db config
        if args.mode == 'hard':
            recycle_db_config = None
        
        # Create cleanup instance
        cleanup = DatabaseCleanup(main_db_config, recycle_db_config)
        
        # Execute based on mode
        if args.mode == 'hard':
            results = cleanup.hard_delete_all(dry_run=args.dry_run)
        elif args.mode == 'soft':
            results = cleanup.soft_delete_all(dry_run=args.dry_run)
        elif args.mode == 'restore':
            results = cleanup.restore_all_from_recycle(dry_run=args.dry_run)
        elif args.mode == 'permanent-recycle':
            results = cleanup.permanent_delete_from_recycle(dry_run=args.dry_run)
        
        # Print summary
        if not results.get("cancelled"):
            logger.info("\n" + "=" * 80)
            logger.info("OPERATION SUMMARY")
            logger.info("=" * 80)
            logger.info(f"Mode: {results['mode']}")
            logger.info(f"Dry Run: {results['dry_run']}")
            
            if 'deleted_records' in results and results['deleted_records']:
                logger.info(f"\nDeleted Records:")
                for table, count in results['deleted_records'].items():
                    logger.info(f"  {table}: {count:,}")
            
            if 'restored_records' in results and results['restored_records']:
                logger.info(f"\nRestored Records:")
                for table, count in results['restored_records'].items():
                    logger.info(f"  {table}: {count:,}")
            
            if 'restored_tables' in results and results['restored_tables']:
                logger.info(f"\nRestored Table Records:")
                for table_info in results['restored_tables']:
                    logger.info(f"  {table_info['table']}: {table_info['records']:,}")
            
            if 'moved_records' in results and results['moved_records']:
                logger.info(f"\nMoved Records:")
                for table, count in results['moved_records'].items():
                    logger.info(f"  {table}: {count:,}")
            
            if 'moved_tables' in results and results['moved_tables']:
                logger.info(f"\nMoved Table Records:")
                for table, count in results['moved_tables'].items():
                    logger.info(f"  {table}: {count:,}")
            
            if 'dropped_tables' in results and results['dropped_tables']:
                logger.info(f"\nDropped Tables: {len(results['dropped_tables'])}")
            
            if 'errors' in results and results['errors']:
                logger.error(f"\nErrors: {len(results['errors'])}")
                for error in results['errors']:
                    logger.error(f"  - {error}")
            
            if args.dry_run:
                logger.info("\n[DRY RUN COMPLETE] - No changes were made to the database")
        
        sys.exit(0)
        
    except KeyboardInterrupt:
        logger.info("\nOperation cancelled by user")
        sys.exit(1)
    except Exception as e:
        logger.error(f"\nFatal error: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
