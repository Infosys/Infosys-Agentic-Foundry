#!/usr/bin/env python3
"""
Conversation Data Restore Script

This script restores conversation data from the recycle database back to the main database
based on the deleted_date timestamp. It can restore data that was deleted within a
specified number of days.

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


class ConversationRestore:
    """
    Handles restoration of conversation data from recycle database to main database
    """
    
    def __init__(self, main_db_config: Dict[str, str], recycle_db_config: Dict[str, str]):
        """
        Initialize the restore handler
        
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
            
    def get_conversations_to_restore(self, days_back: int) -> List[Tuple[str, str, str]]:
        """
        Get conversations that were deleted within the specified days
        
        Args:
            days_back: Number of days back to look for deleted conversations
            
        Returns:
            List of tuples (agentic_application_id, session_id, deleted_date)
        """
        try:
            cursor = self.recycle_conn.cursor()
            cutoff_date = datetime.now() - timedelta(days=days_back)
            
            query = """
                SELECT DISTINCT agentic_application_id, session_id, deleted_date
                FROM recycle_agent_conversation_summary_table
                WHERE deleted_date >= %s
                ORDER BY deleted_date DESC
            """
            
            cursor.execute(query, (cutoff_date,))
            results = cursor.fetchall()
            
            conversations = [(row[0], row[1], row[2]) for row in results]
            logger.info(f"Found {len(conversations)} conversations deleted within {days_back} days")
            
            return conversations
            
        except Exception as e:
            logger.error(f"Error getting conversations to restore: {e}")
            raise
            
    def restore_conversation_summary(self, agentic_application_id: str, session_id: str, deleted_date: datetime):
        """Restore conversation summary from recycle to main database"""
        try:
            # Get data from recycle database
            recycle_cursor = self.recycle_conn.cursor()
            recycle_cursor.execute("""
                SELECT agentic_application_id, session_id, summary, preference, created_on, updated_on
                FROM recycle_agent_conversation_summary_table
                WHERE agentic_application_id = %s AND session_id = %s AND deleted_date = %s
            """, (agentic_application_id, session_id, deleted_date))
            
            data = recycle_cursor.fetchone()
            if data:
                # Check if record already exists in main database
                main_cursor = self.main_conn.cursor()
                main_cursor.execute("""
                    SELECT COUNT(*) FROM agent_conversation_summary_table
                    WHERE agentic_application_id = %s AND session_id = %s
                """, (agentic_application_id, session_id))
                
                exists = main_cursor.fetchone()[0] > 0
                
                if not exists:
                    # Insert into main database with updated_on set to current timestamp
                    restore_data = list(data)  # Convert to list for modification
                    # Update the updated_on field (index 5) to current timestamp
                    restore_data[5] = datetime.now()
                    
                    main_cursor.execute("""
                        INSERT INTO agent_conversation_summary_table
                        (agentic_application_id, session_id, summary, preference, created_on, updated_on)
                        VALUES (%s, %s, %s, %s, %s, %s)
                    """, restore_data)
                    
                    logger.info(f"Restored conversation summary with updated timestamp: {agentic_application_id}, {session_id}")
                    return True
                else:
                    logger.warning(f"Conversation summary already exists in main database: {agentic_application_id}, {session_id}")
                    return False
            else:
                logger.warning(f"No conversation summary found in recycle database for: {agentic_application_id}, {session_id}")
                return False
                
        except Exception as e:
            logger.error(f"Error restoring conversation summary: {e}")
            raise
            
    def restore_longterm_memory(self, agentic_application_id: str, session_id: str, deleted_date: datetime):
        """Restore long-term memory records from recycle to main database"""
        try:
            # Generate table name
            table_name = f"table_{agentic_application_id.replace('-', '_')}"
            
            # Get records from recycle database
            recycle_cursor = self.recycle_conn.cursor()
            recycle_cursor.execute("""
                SELECT session_id, start_timestamp, end_timestamp, human_message, ai_message, response_time
                FROM recycle_longterm_memory
                WHERE table_name = %s AND session_id = %s
            """, (table_name, session_id))
            
            records = recycle_cursor.fetchall()
            
            if records:
                # Check if table exists in main database
                main_cursor = self.main_conn.cursor()
                main_cursor.execute("""
                    SELECT EXISTS (
                        SELECT FROM information_schema.tables 
                        WHERE table_name = %s
                    )
                """, (table_name,))
                
                table_exists = main_cursor.fetchone()[0]
                
                if not table_exists:
                    # Create the table if it doesn't exist
                    main_cursor.execute(f"""
                        CREATE TABLE {table_name} (
                            session_id TEXT,
                            start_timestamp TIMESTAMP,
                            end_timestamp TIMESTAMP,
                            human_message TEXT,
                            ai_message TEXT,
                            response_time FLOAT,
                            PRIMARY KEY (session_id, end_timestamp)
                        )
                    """)
                    logger.info(f"Created table {table_name} in main database")
                
                # Check for existing records to avoid duplicates
                main_cursor.execute(f"""
                    SELECT COUNT(*) FROM {table_name}
                    WHERE session_id = %s
                """, (session_id,))
                
                existing_count = main_cursor.fetchone()[0]
                
                if existing_count == 0:
                    # Insert records into main database
                    for record in records:
                        main_cursor.execute(f"""
                            INSERT INTO {table_name}
                            (session_id, start_timestamp, end_timestamp, human_message, ai_message, response_time)
                            VALUES (%s, %s, %s, %s, %s, %s)
                            ON CONFLICT (session_id, end_timestamp) DO NOTHING
                        """, record)
                    
                    logger.info(f"Restored {len(records)} long-term memory records to {table_name}")
                    return len(records)
                else:
                    logger.warning(f"Long-term memory records already exist for session {session_id} in {table_name}")
                    return 0
            else:
                logger.info(f"No long-term memory records found for restoration: {table_name}, {session_id}")
                return 0
                
        except Exception as e:
            logger.error(f"Error restoring long-term memory: {e}")
            raise
            
    def restore_checkpoint_data(self, agentic_application_id: str, session_id: str, deleted_date: datetime):
        """Restore checkpoint data from recycle to main database"""
        try:
            # Generate thread_id pattern
            table_name = f"table_{agentic_application_id.replace('-', '_')}"
            thread_id = f"{table_name}_{session_id}"
            
            main_cursor = self.main_conn.cursor()
            recycle_cursor = self.recycle_conn.cursor()
            
            restored_counts = {"checkpoints": 0, "writes": 0, "blobs": 0}
            
            # Restore checkpoints - match by thread_id (like cleanup does)
            recycle_cursor.execute("""
                SELECT thread_id, checkpoint_ns, checkpoint_id, parent_checkpoint_id, type, checkpoint, metadata
                FROM recycle_checkpoints
                WHERE thread_id = %s
            """, (thread_id,))
            
            checkpoint_records = recycle_cursor.fetchall()
            logger.info(f"Found {len(checkpoint_records)} checkpoint records for thread_id: {thread_id}")
            
            for record in checkpoint_records:
                # Serialize dict objects to JSON strings for JSONB columns
                converted_record = list(record)
                if len(converted_record) >= 6 and converted_record[5] is not None:
                    if isinstance(converted_record[5], dict):
                        converted_record[5] = json.dumps(converted_record[5])  # checkpoint
                if len(converted_record) >= 7 and converted_record[6] is not None:
                    if isinstance(converted_record[6], dict):
                        converted_record[6] = json.dumps(converted_record[6])  # metadata
                
                result = main_cursor.execute("""
                    INSERT INTO checkpoints
                    (thread_id, checkpoint_ns, checkpoint_id, parent_checkpoint_id, type, checkpoint, metadata)
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (thread_id, checkpoint_ns, checkpoint_id) DO NOTHING
                """, converted_record)
                
                # Check if row was actually inserted (not conflicted)
                if main_cursor.rowcount > 0:
                    restored_counts["checkpoints"] += 1
            
            # Restore checkpoint_writes - match by thread_id (like cleanup does)
            recycle_cursor.execute("""
                SELECT thread_id, checkpoint_ns, checkpoint_id, task_id, idx, channel, type, blob, task_path
                FROM recycle_checkpoint_writes
                WHERE thread_id = %s
            """, (thread_id,))
            
            write_records = recycle_cursor.fetchall()
            logger.info(f"Found {len(write_records)} checkpoint_writes records for thread_id: {thread_id}")
            
            for record in write_records:
                # The blob column in checkpoint_writes is actually binary data (memory objects),
                # not JSON, so we don't need to serialize it
                converted_record = list(record)
                
                result = main_cursor.execute("""
                    INSERT INTO checkpoint_writes
                    (thread_id, checkpoint_ns, checkpoint_id, task_id, idx, channel, type, blob, task_path)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (thread_id, checkpoint_ns, checkpoint_id, task_id, idx) DO NOTHING
                """, converted_record)
                
                # Check if row was actually inserted (not conflicted)
                if main_cursor.rowcount > 0:
                    restored_counts["writes"] += 1
            
            # Restore checkpoint_blobs - match by thread_id (like cleanup does)
            recycle_cursor.execute("""
                SELECT thread_id, checkpoint_ns, channel, version, type, blob
                FROM recycle_checkpoint_blobs
                WHERE thread_id = %s
            """, (thread_id,))
            
            blob_records = recycle_cursor.fetchall()
            logger.info(f"Found {len(blob_records)} checkpoint_blobs records for thread_id: {thread_id}")
            
            for record in blob_records:
                # Convert JSON strings back to JSONB if needed
                converted_record = list(record)
                if len(converted_record) >= 6 and isinstance(converted_record[5], str):
                    try:
                        converted_record[5] = json.loads(converted_record[5])  # blob
                    except (json.JSONDecodeError, TypeError):
                        pass  # Keep as is if not valid JSON
                
                result = main_cursor.execute("""
                    INSERT INTO checkpoint_blobs
                    (thread_id, checkpoint_ns, channel, version, type, blob)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    ON CONFLICT (thread_id, checkpoint_ns, channel, version) DO NOTHING
                """, converted_record)
                
                # Check if row was actually inserted (not conflicted)
                if main_cursor.rowcount > 0:
                    restored_counts["blobs"] += 1
            
            logger.info(f"Restored checkpoint data: {restored_counts['checkpoints']} checkpoints, "
                       f"{restored_counts['writes']} writes, {restored_counts['blobs']} blobs")
            
            return restored_counts
                       
        except Exception as e:
            logger.error(f"Error restoring checkpoint data: {e}")
            raise
            
    def remove_from_recycle(self, agentic_application_id: str, session_id: str, deleted_date: datetime):
        """Remove restored data from recycle database"""
        try:
            recycle_cursor = self.recycle_conn.cursor()
            
            # Remove from recycle_agent_conversation_summary_table
            recycle_cursor.execute("""
                DELETE FROM recycle_agent_conversation_summary_table
                WHERE agentic_application_id = %s AND session_id = %s AND deleted_date = %s
            """, (agentic_application_id, session_id, deleted_date))
            
            summary_removed = recycle_cursor.rowcount
            
            # Remove from recycle_longterm_memory
            table_name = f"table_{agentic_application_id.replace('-', '_')}"
            recycle_cursor.execute("""
                DELETE FROM recycle_longterm_memory
                WHERE table_name = %s AND session_id = %s
            """, (table_name, session_id))
            
            longterm_removed = recycle_cursor.rowcount
            
            # Remove checkpoint data
            thread_id = f"{table_name}_{session_id}"
            
            recycle_cursor.execute("""
                DELETE FROM recycle_checkpoints 
                WHERE thread_id = %s
            """, (thread_id,))
            checkpoints_removed = recycle_cursor.rowcount
            
            recycle_cursor.execute("""
                DELETE FROM recycle_checkpoint_writes 
                WHERE thread_id = %s
            """, (thread_id,))
            writes_removed = recycle_cursor.rowcount
            
            recycle_cursor.execute("""
                DELETE FROM recycle_checkpoint_blobs 
                WHERE thread_id = %s
            """, (thread_id,))
            blobs_removed = recycle_cursor.rowcount
            
            logger.info(f"Removed from recycle database - Summary: {summary_removed}, "
                       f"Long-term: {longterm_removed}, Checkpoints: {checkpoints_removed}, "
                       f"Writes: {writes_removed}, Blobs: {blobs_removed}")
                       
        except Exception as e:
            logger.error(f"Error removing from recycle database: {e}")
            raise
            
    def list_available_conversations(self, days_back: int = 30):
        """
        List conversations available for restoration
        
        Args:
            days_back: Number of days back to look for deleted conversations
        """
        try:
            conversations = self.get_conversations_to_restore(days_back)
            
            if not conversations:
                print(f"No conversations found for restoration within {days_back} days")
                return
                
            print(f"\nAvailable conversations for restoration (deleted within {days_back} days):")
            print("-" * 80)
            print(f"{'Agent ID':<50} {'Session ID':<30} {'Deleted Date'}")
            print("-" * 80)
            
            for agent_id, session_id, deleted_date in conversations:
                # Truncate long IDs for display
                display_agent_id = agent_id[:47] + "..." if len(agent_id) > 50 else agent_id
                display_session_id = session_id[:27] + "..." if len(session_id) > 30 else session_id
                print(f"{display_agent_id:<50} {display_session_id:<30} {deleted_date}")
                
        except Exception as e:
            logger.error(f"Error listing available conversations: {e}")
            raise
            
    def restore_conversations(self, days_back: int = 3, dry_run: bool = False, remove_after_restore: bool = True):
        """
        Main restore process
        
        Args:
            days_back: Number of days back to look for deleted conversations
            dry_run: If True, only log what would be restored without actually restoring
            remove_after_restore: If True, remove from recycle database after successful restore
        """
        try:
            logger.info(f"Starting conversation restore (days_back: {days_back}, dry_run: {dry_run})")
            
            # Connect to databases
            self.connect_databases()
            
            # Get conversations to restore
            conversations_to_restore = self.get_conversations_to_restore(days_back)
            
            if not conversations_to_restore:
                logger.info("No conversations found for restoration")
                return
                
            processed = 0
            errors = 0
            
            for agentic_application_id, session_id, deleted_date in conversations_to_restore:
                try:
                    logger.info(f"Processing: {agentic_application_id}, {session_id}, deleted: {deleted_date}")
                    
                    if not dry_run:
                        # Start transactions for this conversation (psycopg2 style)
                        try:
                            # Restore data
                            summary_restored = self.restore_conversation_summary(agentic_application_id, session_id, deleted_date)
                            longterm_count = self.restore_longterm_memory(agentic_application_id, session_id, deleted_date)
                            checkpoint_counts = self.restore_checkpoint_data(agentic_application_id, session_id, deleted_date)
                            
                            # Remove from recycle database if requested
                            if remove_after_restore and (summary_restored or longterm_count > 0 or sum(checkpoint_counts.values()) > 0):
                                self.remove_from_recycle(agentic_application_id, session_id, deleted_date)
                            
                            # Commit transactions
                            self.main_conn.commit()
                            self.recycle_conn.commit()
                            
                            logger.info(f"Successfully restored: {agentic_application_id}, {session_id}")
                        except Exception as inner_e:
                            # Rollback on error
                            self.main_conn.rollback()
                            self.recycle_conn.rollback()
                            raise inner_e
                    else:
                        logger.info(f"[DRY RUN] Would restore: {agentic_application_id}, {session_id}, deleted: {deleted_date}")
                        
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
                    
            logger.info(f"Restore completed - Processed: {processed}, Errors: {errors}")
            
        except Exception as e:
            logger.error(f"Critical error in restore process: {e}")
            raise
        finally:
            self.close_connections()


def main():
    """Main function"""
    # Load environment variables from the project root
    project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
    env_path = os.path.join(project_root, '.env')
    load_dotenv(env_path)
    
    parser = argparse.ArgumentParser(description='Restore conversation data from recycle database')
    parser.add_argument('--days', type=int, default=3, 
                       help='Number of days back to look for deleted conversations (default: 3)')
    parser.add_argument('--dry-run', action='store_true',
                       help='Perform dry run without actual restoration')
    parser.add_argument('--keep-in-recycle', action='store_true',
                       help='Keep data in recycle database after restoration (default: remove after restore)')
    parser.add_argument('--list-only', action='store_true',
                       help='Only list available conversations for restoration')
    parser.add_argument('--recycle-db', type=str, default='recycle',
                       help='Recycle database name (default: recycle)')
    
    args = parser.parse_args()
    
    # Get database configuration from environment variables
    db_host = os.getenv("POSTGRESQL_HOST", "localhost")
    db_port = os.getenv("POSTGRESQL_PORT", "5432")
    db_user = os.getenv("POSTGRESQL_USER", "postgres")
    db_password = os.getenv("POSTGRESQL_PASSWORD", "postgres")
    main_db_name = os.getenv("DATABASE", "iaf_database")
    
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
    
    try:
        restore_handler = ConversationRestore(main_db_config, recycle_db_config)
        
        if args.list_only:
            restore_handler.connect_databases()
            restore_handler.list_available_conversations(args.days)
            restore_handler.close_connections()
        else:
            restore_handler.restore_conversations(
                days_back=args.days, 
                dry_run=args.dry_run,
                remove_after_restore=not args.keep_in_recycle
            )
        
    except Exception as e:
        logger.error(f"Failed to run restore: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()