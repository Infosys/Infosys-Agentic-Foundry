#!/usr/bin/env python3
"""
Conversation Data Cleanup Script

This script cleans up old conversation data from the main database and backs it up
to a recycle database. It processes records older than a specified number of days
from the agent_conversation_summary_table and related tables.

Author: AI Assistant
Date: November 21, 2025
"""

import psycopg2
import psycopg2.extras
import logging
from datetime import datetime, timedelta
from typing import List, Tuple, Dict, Any
import sys
import argparse
import os
import json
from dotenv import load_dotenv

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)


class ConversationCleanup:
    """
    Handles cleanup of old conversation data with backup to recycle database
    """
    
    def __init__(self, main_db_config: Dict[str, str], recycle_db_config: Dict[str, str]):
        """
        Initialize the cleanup handler
        
        Args:
            main_db_config: Database configuration for main database
            recycle_db_config: Database configuration for recycle database
        """
        self.main_db_config = main_db_config
        self.recycle_db_config = recycle_db_config
        self.main_conn = None
        self.recycle_conn = None
        
    def connect_databases(self):
        """Connect to both main and recycle databases"""
        try:
            # Connect to main database
            self.main_conn = psycopg2.connect(**self.main_db_config)
            self.main_conn.autocommit = False
            logger.info("Connected to main database successfully")
            
            # Connect to recycle database
            self.recycle_conn = psycopg2.connect(**self.recycle_db_config)
            self.recycle_conn.autocommit = False
            logger.info("Connected to recycle database successfully")
            
        except Exception as e:
            logger.error(f"Error connecting to databases: {e}")
            raise
            
    def close_connections(self):
        """Close database connections"""
        if self.main_conn:
            self.main_conn.close()
            logger.info("Main database connection closed")
        if self.recycle_conn:
            self.recycle_conn.close()
            logger.info("Recycle database connection closed")
            
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
                    deleted_date TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
                    CONSTRAINT recycle_agent_conversation_summary_unique 
                        UNIQUE (agentic_application_id, session_id, deleted_date)
                );
            """)
            
            # Create recycle_checkpoints
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS recycle_checkpoints (
                    thread_id TEXT NOT NULL,
                    checkpoint_ns TEXT NOT NULL DEFAULT '',
                    checkpoint_id TEXT NOT NULL,
                    parent_checkpoint_id TEXT,
                    type TEXT,
                    checkpoint JSONB NOT NULL,
                    metadata JSONB NOT NULL DEFAULT '{}',
                    deleted_date TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
                );
            """)
            
            # Create recycle_checkpoint_writes
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS recycle_checkpoint_writes (
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
            
            # Create recycle_checkpoint_blobs
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS recycle_checkpoint_blobs (
                    thread_id TEXT NOT NULL,
                    checkpoint_ns TEXT NOT NULL DEFAULT '',
                    channel TEXT NOT NULL,
                    version TEXT NOT NULL,
                    type TEXT NOT NULL,
                    blob BYTEA,
                    deleted_date TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
                );
            """)
            
            # Create recycle_longterm_memory
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS recycle_longterm_memory (
                    table_name TEXT,
                    session_id TEXT,
                    start_timestamp TIMESTAMP,
                    end_timestamp TIMESTAMP,
                    human_message TEXT,
                    ai_message TEXT,
                    response_time FLOAT,
                    deleted_date TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
                );
            """)
            
            self.recycle_conn.commit()
            logger.info("Recycle tables created successfully")
            
        except Exception as e:
            self.recycle_conn.rollback()
            logger.error(f"Error creating recycle tables: {e}")
            raise
            
    def get_old_conversations(self, days_threshold: int) -> List[Tuple[str, str]]:
        """
        Get conversations older than specified days
        
        Args:
            days_threshold: Number of days threshold
            
        Returns:
            List of tuples (agentic_application_id, session_id)
        """
        try:
            cursor = self.main_conn.cursor()
            cutoff_date = datetime.now() - timedelta(days=days_threshold)
            
            query = """
                SELECT agentic_application_id, session_id, updated_on
                FROM agent_conversation_summary_table
                WHERE updated_on < %s
            """
            
            cursor.execute(query, (cutoff_date,))
            results = cursor.fetchall()
            
            conversations = [(row[0], row[1]) for row in results]
            logger.info(f"Found {len(conversations)} conversations older than {days_threshold} days")
            
            return conversations
            
        except Exception as e:
            logger.error(f"Error getting old conversations: {e}")
            raise
            
    def backup_conversation_summary(self, agentic_application_id: str, session_id: str, deleted_date: datetime = None):
        """Backup conversation summary to recycle database"""
        try:
            # Get data from main database
            main_cursor = self.main_conn.cursor()
            main_cursor.execute("""
                SELECT agentic_application_id, session_id, summary, preference, created_on, updated_on
                FROM agent_conversation_summary_table
                WHERE agentic_application_id = %s AND session_id = %s
            """, (agentic_application_id, session_id))
            
            data = main_cursor.fetchone()
            if data:
                # Insert into recycle database with deleted_date
                if deleted_date is None:
                    deleted_date = datetime.now()
                recycle_cursor = self.recycle_conn.cursor()
                recycle_cursor.execute("""
                    INSERT INTO recycle_agent_conversation_summary_table
                    (agentic_application_id, session_id, summary, preference, created_on, updated_on, deleted_date)
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                """, data + (deleted_date,))
                
                logger.info(f"Backed up conversation summary: {agentic_application_id}, {session_id}")
                
        except Exception as e:
            logger.error(f"Error backing up conversation summary: {e}")
            raise
            
    def backup_longterm_memory(self, agentic_application_id: str, session_id: str, deleted_date: datetime = None):
        """Backup long-term memory records to recycle database"""
        try:
            # Generate table name
            table_name = f"table_{agentic_application_id.replace('-', '_')}"
            
            # Check if table exists
            main_cursor = self.main_conn.cursor()
            main_cursor.execute("""
                SELECT EXISTS (
                    SELECT FROM information_schema.tables 
                    WHERE table_name = %s
                )
            """, (table_name,))
            
            table_exists = main_cursor.fetchone()[0]
            
            if table_exists:
                # Get records from the table
                main_cursor.execute(f"""
                    SELECT session_id, start_timestamp, end_timestamp, human_message, ai_message, response_time
                    FROM {table_name}
                    WHERE session_id = %s
                """, (session_id,))
                
                records = main_cursor.fetchall()
                
                if records:
                    # Insert into recycle database with deleted_date
                    if deleted_date is None:
                        deleted_date = datetime.now()
                    recycle_cursor = self.recycle_conn.cursor()
                    for record in records:
                        recycle_cursor.execute("""
                            INSERT INTO recycle_longterm_memory
                            (table_name, session_id, start_timestamp, end_timestamp, human_message, ai_message, response_time, deleted_date)
                            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                        """, (table_name, *record, deleted_date))
                    
                    logger.info(f"Backed up {len(records)} long-term memory records from {table_name}")
                    
        except Exception as e:
            logger.error(f"Error backing up long-term memory: {e}")
            raise
            
    def backup_checkpoint_data(self, agentic_application_id: str, session_id: str, deleted_date: datetime = None):
        """Backup checkpoint data to recycle database"""
        try:
            if deleted_date is None:
                deleted_date = datetime.now()
                
            # Generate thread_id pattern
            table_name = f"table_{agentic_application_id.replace('-', '_')}"
            thread_id = f"{table_name}_{session_id}"
            
            main_cursor = self.main_conn.cursor()
            recycle_cursor = self.recycle_conn.cursor()
            
            # Backup checkpoints
            main_cursor.execute("""
                SELECT thread_id, checkpoint_ns, checkpoint_id, parent_checkpoint_id, type, checkpoint, metadata
                FROM checkpoints
                WHERE thread_id = %s
            """, (thread_id,))
            
            checkpoint_records = main_cursor.fetchall()
            
            for record in checkpoint_records:
                # Convert JSONB fields to strings if they're dicts
                converted_record = list(record)
                if len(converted_record) >= 6 and isinstance(converted_record[5], dict):
                    converted_record[5] = json.dumps(converted_record[5])  # checkpoint
                if len(converted_record) >= 7 and isinstance(converted_record[6], dict):
                    converted_record[6] = json.dumps(converted_record[6])  # metadata
                    
                recycle_cursor.execute("""
                    INSERT INTO recycle_checkpoints
                    (thread_id, checkpoint_ns, checkpoint_id, parent_checkpoint_id, type, checkpoint, metadata, deleted_date)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                """, converted_record + [deleted_date])
            
            # Backup checkpoint_writes
            main_cursor.execute("""
                SELECT thread_id, checkpoint_ns, checkpoint_id, task_id, idx, channel, type, blob, task_path
                FROM checkpoint_writes
                WHERE thread_id = %s
            """, (thread_id,))
            
            write_records = main_cursor.fetchall()
            
            for record in write_records:
                recycle_cursor.execute("""
                    INSERT INTO recycle_checkpoint_writes
                    (thread_id, checkpoint_ns, checkpoint_id, task_id, idx, channel, type, blob, task_path, deleted_date)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """, record + (deleted_date,))
            
            # Backup checkpoint_blobs
            main_cursor.execute("""
                SELECT thread_id, checkpoint_ns, channel, version, type, blob
                FROM checkpoint_blobs
                WHERE thread_id = %s
            """, (thread_id,))
            
            blob_records = main_cursor.fetchall()
            
            for record in blob_records:
                recycle_cursor.execute("""
                    INSERT INTO recycle_checkpoint_blobs
                    (thread_id, checkpoint_ns, channel, version, type, blob, deleted_date)
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                """, record + (deleted_date,))
            
            logger.info(f"Backed up checkpoint data: {len(checkpoint_records)} checkpoints, "
                       f"{len(write_records)} writes, {len(blob_records)} blobs")
                       
        except Exception as e:
            logger.error(f"Error backing up checkpoint data: {e}")
            raise
            
    def delete_main_data(self, agentic_application_id: str, session_id: str):
        """Delete data from main database"""
        try:
            main_cursor = self.main_conn.cursor()
            
            # Delete from agent_conversation_summary_table
            main_cursor.execute("""
                DELETE FROM agent_conversation_summary_table
                WHERE agentic_application_id = %s AND session_id = %s
            """, (agentic_application_id, session_id))
            
            summary_deleted = main_cursor.rowcount
            
            # Delete from long-term memory table
            table_name = f"table_{agentic_application_id.replace('-', '_')}"
            
            # Check if table exists first
            main_cursor.execute("""
                SELECT EXISTS (
                    SELECT FROM information_schema.tables 
                    WHERE table_name = %s
                )
            """, (table_name,))
            
            table_exists = main_cursor.fetchone()[0]
            longterm_deleted = 0
            
            if table_exists:
                main_cursor.execute(f"""
                    DELETE FROM {table_name}
                    WHERE session_id = %s
                """, (session_id,))
                longterm_deleted = main_cursor.rowcount
            
            # Delete checkpoint data
            thread_id = f"{table_name}_{session_id}"
            
            main_cursor.execute("DELETE FROM checkpoints WHERE thread_id = %s", (thread_id,))
            checkpoints_deleted = main_cursor.rowcount
            
            main_cursor.execute("DELETE FROM checkpoint_writes WHERE thread_id = %s", (thread_id,))
            writes_deleted = main_cursor.rowcount
            
            main_cursor.execute("DELETE FROM checkpoint_blobs WHERE thread_id = %s", (thread_id,))
            blobs_deleted = main_cursor.rowcount
            
            logger.info(f"Deleted from main database - Summary: {summary_deleted}, "
                       f"Long-term: {longterm_deleted}, Checkpoints: {checkpoints_deleted}, "
                       f"Writes: {writes_deleted}, Blobs: {blobs_deleted}")
                       
        except Exception as e:
            logger.error(f"Error deleting main data: {e}")
            raise
            
    def cleanup_conversations(self, days_threshold: int = 30, dry_run: bool = False):
        """
        Main cleanup process
        
        Args:
            days_threshold: Number of days for cleanup threshold
            dry_run: If True, only log what would be deleted without actually deleting
        """
        try:
            logger.info(f"Starting conversation cleanup (days_threshold: {days_threshold}, dry_run: {dry_run})")
            
            # Connect to databases
            self.connect_databases()
            
            # Create recycle tables
            if not dry_run:
                self.create_recycle_tables()
            
            # Get old conversations
            old_conversations = self.get_old_conversations(days_threshold)
            
            if not old_conversations:
                logger.info("No old conversations found for cleanup")
                return
                
            processed = 0
            errors = 0
            
            for agentic_application_id, session_id in old_conversations:
                try:
                    logger.info(f"Processing: {agentic_application_id}, {session_id}")
                    
                    if not dry_run:
                        # Start transactions for this conversation (psycopg2 style)
                        try:
                            # Create consistent deleted_date for this conversation
                            deleted_date = datetime.now()
                            
                            # Backup data
                            self.backup_conversation_summary(agentic_application_id, session_id, deleted_date)
                            self.backup_longterm_memory(agentic_application_id, session_id, deleted_date)
                            self.backup_checkpoint_data(agentic_application_id, session_id, deleted_date)
                            
                            # Delete from main database
                            self.delete_main_data(agentic_application_id, session_id)
                            
                            # Commit transactions
                            self.main_conn.commit()
                            self.recycle_conn.commit()
                            
                            logger.info(f"Successfully processed: {agentic_application_id}, {session_id}")
                        except Exception as inner_e:
                            # Rollback on error
                            self.main_conn.rollback()
                            self.recycle_conn.rollback()
                            raise inner_e
                    else:
                        logger.info(f"[DRY RUN] Would process: {agentic_application_id}, {session_id}")
                        
                    processed += 1
                    
                except Exception as e:
                    if not dry_run:
                        # Additional safety rollback (in case not done above)
                        try:
                            self.main_conn.rollback()
                            self.recycle_conn.rollback()
                        except:
                            pass
                    logger.error(f"Error processing {agentic_application_id}, {session_id}: {e}")
                    errors += 1
                    
            logger.info(f"Cleanup completed - Processed: {processed}, Errors: {errors}")
            
        except Exception as e:
            logger.error(f"Critical error in cleanup process: {e}")
            raise
        finally:
            self.close_connections()

    def permanent_delete_insidetable_records(self, dry_run: bool = False):
        """
        Permanently delete records with thread_id starting with "insidetable" from main database.
        These records are deleted directly without being placed in recycle bin.
        """
        try:
            # Connect to databases if not already connected
            if not self.main_conn:
                self.connect_databases()
                
            with self.main_conn.cursor() as cursor:
                    # Check for records with thread_id starting with "insidetable"
                    cursor.execute("""
                        SELECT COUNT(*) FROM checkpoints 
                        WHERE thread_id LIKE 'insidetable%'
                    """)
                    checkpoint_count = cursor.fetchone()[0]
                    
                    cursor.execute("""
                        SELECT COUNT(*) FROM checkpoint_writes 
                        WHERE thread_id LIKE 'insidetable%'
                    """)
                    checkpoint_writes_count = cursor.fetchone()[0]
                    
                    cursor.execute("""
                        SELECT COUNT(*) FROM checkpoint_blobs 
                        WHERE thread_id LIKE 'insidetable%'
                    """)
                    checkpoint_blobs_count = cursor.fetchone()[0]
                    
                    total_count = checkpoint_count + checkpoint_writes_count + checkpoint_blobs_count
                    
                    if total_count > 0:
                        logger.info(f"Found {total_count} 'insidetable' records to permanently delete:")
                        logger.info(f"  - Checkpoints: {checkpoint_count}")
                        logger.info(f"  - Checkpoint Writes: {checkpoint_writes_count}")
                        logger.info(f"  - Checkpoint Blobs: {checkpoint_blobs_count}")
                        
                        if not dry_run:
                            # Delete from checkpoint_blobs first (foreign key constraints)
                            cursor.execute("""
                                DELETE FROM checkpoint_blobs 
                                WHERE thread_id LIKE 'insidetable%'
                            """)
                            
                            # Delete from checkpoint_writes
                            cursor.execute("""
                                DELETE FROM checkpoint_writes 
                                WHERE thread_id LIKE 'insidetable%'
                            """)
                            
                            # Delete from checkpoints
                            cursor.execute("""
                                DELETE FROM checkpoints 
                                WHERE thread_id LIKE 'insidetable%'
                            """)
                            
                            self.main_conn.commit()
                            logger.info(f"Successfully permanently deleted {total_count} 'insidetable' records from main database")
                        else:
                            logger.info(f"DRY RUN: Would permanently delete {total_count} 'insidetable' records from main database")
                    else:
                        logger.info("No 'insidetable' records found to delete")
                        
        except Exception as e:
            logger.error(f"Error during permanent deletion of 'insidetable' records: {e}")
            raise

    def permanent_delete_from_recycle(self, retention_days: int, dry_run: bool = False):
        """
        Permanently delete records from recycle database that are older than retention_days
        
        Args:
            retention_days: Number of days to retain records in recycle bin
            dry_run: If True, only show what would be deleted without actual deletion
        """
        logger.info(f"Starting permanent deletion from recycle bin (retention: {retention_days} days, dry_run: {dry_run})")
        
        try:
            self.connect_databases()
            
            # Create recycle tables if they don't exist
            if not dry_run:
                self.create_recycle_tables()
            
            recycle_cursor = self.recycle_conn.cursor()
            
            # Calculate cutoff date
            cutoff_date = datetime.now() - timedelta(days=retention_days)
            logger.info(f"Deleting records older than: {cutoff_date}")
            
            # Find records to permanently delete
            recycle_cursor.execute("""
                SELECT agentic_application_id, session_id, deleted_date
                FROM recycle_agent_conversation_summary_table
                WHERE deleted_date < %s
                ORDER BY deleted_date
            """, (cutoff_date,))
            
            records_to_delete = recycle_cursor.fetchall()
            logger.info(f"Found {len(records_to_delete)} conversations for permanent deletion")
            
            deleted_counts = {
                "summaries": 0,
                "longterm_memory": 0, 
                "checkpoints": 0,
                "checkpoint_writes": 0,
                "checkpoint_blobs": 0,
                "agents": 0,
                "tools": 0
            }
            
            # Process conversation records
            if records_to_delete:
                for agentic_application_id, session_id, deleted_date in records_to_delete:
                    logger.info(f"Permanently deleting: {agentic_application_id}, {session_id} (deleted on: {deleted_date})")
                    
                    if not dry_run:
                        try:
                            # Generate thread_id pattern for checkpoint tables
                            table_name = f"table_{agentic_application_id.replace('-', '_')}"
                            thread_id = f"{table_name}_{session_id}"
                            
                            # Delete from recycle_agent_conversation_summary_table
                            recycle_cursor.execute("""
                                DELETE FROM recycle_agent_conversation_summary_table
                                WHERE agentic_application_id = %s AND session_id = %s AND deleted_date = %s
                            """, (agentic_application_id, session_id, deleted_date))
                            deleted_counts["summaries"] += recycle_cursor.rowcount
                            
                            # Delete from recycle_longterm_memory
                            recycle_cursor.execute("""
                                DELETE FROM recycle_longterm_memory
                                WHERE table_name = %s AND session_id = %s AND deleted_date = %s
                            """, (table_name, session_id, deleted_date))
                            deleted_counts["longterm_memory"] += recycle_cursor.rowcount
                            
                            # Delete from recycle_checkpoints
                            recycle_cursor.execute("""
                                DELETE FROM recycle_checkpoints
                                WHERE thread_id = %s AND deleted_date = %s
                            """, (thread_id, deleted_date))
                            deleted_counts["checkpoints"] += recycle_cursor.rowcount
                            
                            # Delete from recycle_checkpoint_writes
                            recycle_cursor.execute("""
                                DELETE FROM recycle_checkpoint_writes
                                WHERE thread_id = %s AND deleted_date = %s
                            """, (thread_id, deleted_date))
                            deleted_counts["checkpoint_writes"] += recycle_cursor.rowcount
                            
                            # Delete from recycle_checkpoint_blobs
                            recycle_cursor.execute("""
                                DELETE FROM recycle_checkpoint_blobs
                                WHERE thread_id = %s AND deleted_date = %s
                            """, (thread_id, deleted_date))
                            deleted_counts["checkpoint_blobs"] += recycle_cursor.rowcount
                            
                            logger.info(f"Permanently deleted: {agentic_application_id}, {session_id}")
                            
                        except Exception as e:
                            self.recycle_conn.rollback()
                            logger.error(f"Error permanently deleting {agentic_application_id}, {session_id}: {e}")
                            continue
                    else:
                        logger.info(f"[DRY RUN] Would permanently delete: {agentic_application_id}, {session_id}")
            else:
                logger.info("No conversation records found for permanent deletion")
            
            # Also permanently delete agents and tools based on updated_on field
            logger.info("Permanently deleting old agents and tools...")
            
            # Delete old agents
            recycle_cursor.execute("""
                SELECT agentic_application_id, updated_on
                FROM recycle_agent
                WHERE updated_on < %s
                ORDER BY updated_on
            """, (cutoff_date,))
            
            agent_records_to_delete = recycle_cursor.fetchall()
            logger.info(f"Found {len(agent_records_to_delete)} agents for permanent deletion")
            
            for agentic_application_id, updated_on in agent_records_to_delete:
                if not dry_run:
                    try:
                        recycle_cursor.execute("""
                            DELETE FROM recycle_agent
                            WHERE agentic_application_id = %s AND updated_on = %s
                        """, (agentic_application_id, updated_on))
                        deleted_counts["agents"] += recycle_cursor.rowcount
                        logger.info(f"Permanently deleted agent: {agentic_application_id} (updated on: {updated_on})")
                    except Exception as e:
                        logger.error(f"Error permanently deleting agent {agentic_application_id}: {e}")
                        continue
                else:
                    logger.info(f"[DRY RUN] Would permanently delete agent: {agentic_application_id} (updated on: {updated_on})")
            
            # Delete old tools
            recycle_cursor.execute("""
                SELECT tool_id, updated_on
                FROM recycle_tool
                WHERE updated_on < %s
                ORDER BY updated_on
            """, (cutoff_date,))
            
            tool_records_to_delete = recycle_cursor.fetchall()
            logger.info(f"Found {len(tool_records_to_delete)} tools for permanent deletion")
            
            for tool_id, updated_on in tool_records_to_delete:
                if not dry_run:
                    try:
                        recycle_cursor.execute("""
                            DELETE FROM recycle_tool
                            WHERE tool_id = %s AND updated_on = %s
                        """, (tool_id, updated_on))
                        deleted_counts["tools"] += recycle_cursor.rowcount
                        logger.info(f"Permanently deleted tool: {tool_id} (updated on: {updated_on})")
                    except Exception as e:
                        logger.error(f"Error permanently deleting tool {tool_id}: {e}")
                        continue
                else:
                    logger.info(f"[DRY RUN] Would permanently delete tool: {tool_id} (updated on: {updated_on})")
            
            if not dry_run:
                self.recycle_conn.commit()
                logger.info(f"Permanent deletion completed - Summaries: {deleted_counts['summaries']}, "
                          f"Long-term: {deleted_counts['longterm_memory']}, "
                          f"Checkpoints: {deleted_counts['checkpoints']}, "
                          f"Writes: {deleted_counts['checkpoint_writes']}, "
                          f"Blobs: {deleted_counts['checkpoint_blobs']}, "
                          f"Agents: {deleted_counts['agents']}, "
                          f"Tools: {deleted_counts['tools']}")
            else:
                total_records = len(records_to_delete) + len(agent_records_to_delete) + len(tool_records_to_delete)
                logger.info(f"[DRY RUN] Would permanently delete {len(records_to_delete)} conversations, "
                          f"{len(agent_records_to_delete)} agents, {len(tool_records_to_delete)} tools "
                          f"(Total: {total_records} records)")
                
        except Exception as e:
            logger.error(f"Error in permanent deletion: {e}")
            raise
        finally:
            if hasattr(self, 'recycle_conn') and self.recycle_conn:
                try:
                    self.recycle_conn.rollback()  # Safety rollback
                except:
                    pass


def main():
    """Main function"""
    # Load environment variables from the project root
    project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
    env_path = os.path.join(project_root, '.env')
    load_dotenv(env_path)
    
    parser = argparse.ArgumentParser(description='Cleanup old conversation data')
    parser.add_argument('--days', type=int, default=30, 
                       help='Days threshold for cleanup (default: 30)')
    parser.add_argument('--dry-run', action='store_true',
                       help='Perform dry run without actual deletion')
    parser.add_argument('--recycle-db', type=str, default='recycle',
                       help='Recycle database name (default: recycle)')
    
    args = parser.parse_args()
    
    # Get database configuration from environment variables
    db_host = os.getenv("POSTGRESQL_HOST", "localhost")
    db_port = os.getenv("POSTGRESQL_PORT", "5432")
    db_user = os.getenv("POSTGRESQL_USER", "postgres")
    db_password = os.getenv("POSTGRESQL_PASSWORD", "postgres")
    main_db_name = os.getenv("DATABASE", "iaf_database")
    recycle_retention_days = int(os.getenv("RECYCLE_BIN_RETENTION_DAYS", "15"))
    
    # Database configurations
    main_db_config = {
        "dbname": main_db_name,
        "user": db_user,
        "password": db_password,
        "host": db_host,
        "port": db_port
    }
    
    recycle_db_config = {
        "dbname": args.recycle_db,
        "user": db_user,
        "password": db_password,
        "host": db_host,
        "port": db_port
    }
    
    logger.info(f"Using main database: {main_db_name}")
    logger.info(f"Using recycle database: {args.recycle_db}")
    logger.info(f"Database host: {db_host}:{db_port}")
    logger.info(f"Recycle retention period: {recycle_retention_days} days")
    
    try:
        cleanup_handler = ConversationCleanup(main_db_config, recycle_db_config)
        
        # First, permanently delete "insidetable" records from main database (no recycle)
        logger.info("Step 1: Permanently deleting 'insidetable' records from main database...")
        cleanup_handler.permanent_delete_insidetable_records(args.dry_run)
        
        # Second, perform permanent deletion from recycle bin
        logger.info("Step 2: Performing permanent deletion from recycle bin...")
        cleanup_handler.permanent_delete_from_recycle(recycle_retention_days, args.dry_run)
        
        # Then, perform cleanup of old conversations
        logger.info("Step 3: Cleaning up old conversations...")
        cleanup_handler.cleanup_conversations(args.days, args.dry_run)
        
    except Exception as e:
        logger.error(f"Failed to run cleanup: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()