# © 2024-25 Infosys Limited, Bangalore, India. All Rights Reserved.
import asyncpg
from typing import List, Dict, Any
from datetime import datetime

from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from src.config.constants import TableNames, DatabaseName
from src.config.application_config import app_config

from telemetry_wrapper import logger as log

from src.database.repositories import BaseRepository


class ChatHistoryRepository(BaseRepository):
    """
    Repository for chat history. Handles direct database interactions with
    dynamically named chat tables and the shared checkpoint tables.
    """

    def __init__(self, pool: asyncpg.Pool, login_pool: asyncpg.Pool):
        """
        Initializes the ChatHistoryRepository.

        Args:
            pool (asyncpg.Pool): The asyncpg connection pool.
            login_pool (asyncpg.Pool): The asyncpg connection pool for login-related operations.
        """
        # We pass a empty table_name to super, as this repo handles multiple tables.
        super().__init__(pool, login_pool, table_name="")
        postgres_db = app_config.postgres_db
        self.DB_URL = postgres_db.connection_string(database=DatabaseName.MAIN, disable_ssl=postgres_db.disable_ssl_for_chat_connections)
        self.DB_URL_ASYNC = postgres_db.connection_string(database=DatabaseName.MAIN, async_str=True)
        self.checkpoints_table = TableNames.CHECKPOINTS.value
        self.checkpoint_blobs_table = TableNames.CHECKPOINT_BLOBS.value
        self.checkpoint_writes_table = TableNames.CHECKPOINT_WRITES.value

    async def migrate_adk_session_tables(self):
        """
        Checks if the ADK session schema needs migration from old (V0) to new (V1).
        If adk_internal_metadata table does not exist but old ADK tables do,
        drops them so DatabaseSessionService can recreate with the V1 schema.
        """
        try:
            async with self.pool.acquire() as conn:
                has_metadata = await conn.fetchval(
                    "SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema = 'public' AND table_name = 'adk_internal_metadata')"
                )
                if has_metadata:
                    log.info("ADK session tables are already on V1 schema. No migration needed.")
                    return

                has_events = await conn.fetchval(
                    "SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema = 'public' AND table_name = 'events')"
                )
                if not has_events:
                    log.info("No existing ADK session tables found. Fresh setup will be handled by DatabaseSessionService.")
                    return

                log.warning("Detected old ADK V0 session schema. Dropping old tables for V1 recreation...")
                await conn.execute("DROP TABLE IF EXISTS events CASCADE")
                await conn.execute("DROP TABLE IF EXISTS sessions CASCADE")
                await conn.execute("DROP TABLE IF EXISTS app_states CASCADE")
                await conn.execute("DROP TABLE IF EXISTS user_states CASCADE")
                log.info("Old ADK session tables dropped successfully. DatabaseSessionService will recreate V1 schema on first use.")
        except Exception as e:
            log.error(f"Error during ADK session table migration check: {e}")
            raise

    async def create_chat_history_table(self, table_name: str):
        """
        Creates a dedicated chat history table if it doesn't exist.

        Args:
            table_name (str): The specific name of the table to create.
        """
        create_statement = f"""
        CREATE TABLE IF NOT EXISTS {table_name} (
            session_id TEXT,
            start_timestamp TIMESTAMP,
            end_timestamp TIMESTAMP,
            human_message TEXT,
            ai_message TEXT,
            response_time FLOAT,
            PRIMARY KEY (session_id, end_timestamp)
        );
        """
        try:
            async with self.pool.acquire() as conn:
                await conn.execute(create_statement)
                check_column_query = f"""
                SELECT column_name 
                FROM information_schema.columns 
                WHERE table_name = '{table_name}' AND column_name = 'response_time';
                """
                result = await conn.fetch(check_column_query)
                
                if not result:  # Column doesn't exist, add it
                    alter_statement = f"""
                    ALTER TABLE {table_name} 
                    ADD COLUMN response_time FLOAT;
                    """
                    await conn.execute(alter_statement)
                    log.info(f"Added response_time column to existing table '{table_name}'.")
                
            log.info(f"Table '{table_name}' created successfully or already exists with response_time column.")
        except Exception as e:
            log.error(f"Error creating table '{table_name}': {e}")
            raise

    async def insert_chat_record(
        self,
        table_name: str,
        session_id: str,
        start_timestamp: str,
        end_timestamp: str,
        human_message: str,
        ai_message: str,
        response_time: float = None
    ):
        """
        Inserts a new chat message pair into a specified table.

        Args:
            table_name (str): The table to insert into.
            response_time (float): The response time in seconds for this request.
            (all other args are data for the record)
        """
        insert_statement = f"""
        INSERT INTO {table_name} (
            session_id, start_timestamp, end_timestamp, human_message, ai_message, response_time
        ) VALUES ($1, $2, $3, $4, $5, $6)
        """
        try:
            async with self.pool.acquire() as conn:
                await conn.execute(
                    insert_statement,
                    session_id,
                    start_timestamp,
                    end_timestamp,
                    human_message,
                    ai_message,
                    response_time
                )
            log.info(f"Chat history inserted into '{table_name}' for session '{session_id}'.")
        except Exception as e:
            log.error(f"Failed to insert chat history into '{table_name}': {e}")
            raise

    async def update_latest_response_time(
        self,
        table_name: str,
        session_id: str,
        response_time: float
    ) -> bool:
        """
        Updates the response time for the most recent chat record for a given session.
        
        Args:
            table_name (str): The name of the table to update.
            session_id (str): The session ID.
            response_time (float): The calculated response time in seconds.
            
        Returns:
            bool: True if successful, False otherwise.
        """
        update_statement = f"""
        UPDATE {table_name}
        SET response_time = $1
        WHERE session_id = $2
        AND end_timestamp = (
            SELECT MAX(end_timestamp)
            FROM {table_name}
            WHERE session_id = $2
        )
        """
        
        try:
            async with self.pool.acquire() as conn:
                result = await conn.execute(update_statement, response_time, session_id)
                if result == "UPDATE 1":
                    log.info(f"Updated response time ({response_time:.2f}s) for session '{session_id}' in table '{table_name}'.")
                    return True
                else:
                    log.warning(f"No record found to update response time for session '{session_id}' in table '{table_name}'.")
                    return False
        except Exception as e:
            log.error(f"Repository-level error updating response time for session '{session_id}': {e}")
            return False

    async def create_agent_conversation_summary_table(self):
        """
        Creates a dedicated agent summary table if it doesn't exist.

        Args:
            agentic_application_id (str): The ID of the agent application.
        """
        table_name = "agent_conversation_summary_table"
        create_statement = f"""
        CREATE TABLE IF NOT EXISTS {table_name} (
            agentic_application_id TEXT,
            session_id TEXT,
            summary TEXT,
            preference TEXT,
            created_on TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
            updated_on TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(agentic_application_id, session_id)
        );
        """
        try:
            async with self.pool.acquire() as conn:
                await conn.execute(create_statement)
                # Add updated_on column if table already exists without it
                alter_statement = f"""
                ALTER TABLE {table_name} ADD COLUMN IF NOT EXISTS updated_on TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP;
                """
                await conn.execute(alter_statement)
            log.info(f"Table '{table_name}' created successfully or already exists with updated_on column.")
        except Exception as e:
            log.error(f"Error creating table '{table_name}': {e}")
            raise

    async def insert_preference_for_agent_conversation(
        self, agentic_application_id: str, session_id: str, preference: str
        ):
        """ Inserts or updates the preference for a specific agent conversation.
        """
        table_name = "agent_conversation_summary_table"
        insert_statement = f"""
        INSERT INTO {table_name} (agentic_application_id, session_id, preference, updated_on)
        VALUES ($1, $2, $3, CURRENT_TIMESTAMP)
        ON CONFLICT (agentic_application_id, session_id)
        DO UPDATE SET preference = $3, updated_on = CURRENT_TIMESTAMP
        """
        try:
            async with self.pool.acquire() as conn:
                await conn.execute(insert_statement, agentic_application_id, session_id, preference)
            log.info(f"Inserted/Updated preference for session '{session_id}' in table '{table_name}'.")
        except Exception as e:
            log.error(f"Failed to insert/update preference in '{table_name}': {e}")
            raise

    async def get_agent_conversation_summary_with_preference(
        self, agentic_application_id: str, session_id: str
    ) -> str | None:
        """
        Retrieves the conversation summary and preference for a specific agent and session.

        Args:
            agentic_application_id (str): The ID of the agent application.
            session_id (str): The ID of the session.

        Returns:
            dict: A dictionary representing the conversation summary and preference, or None if not found.
        """
        table_name = "agent_conversation_summary_table"
        try:
            async with self.pool.acquire() as conn:
                query = f"""
                SELECT summary, preference
                FROM {table_name}
                WHERE agentic_application_id = '{agentic_application_id}' AND session_id = '{session_id}'
                """
                summary = await conn.fetchrow(query)
                if summary:
                    log.info(f"Retrieved agent conversation summary for session '{session_id}'.")
                    return dict(summary)
                else:
                    log.warning(f"No agent conversation summary found for session '{session_id}'.")
                    return None
        except Exception as e:
            log.error(f"Failed to retrieve agent conversation summary from '{table_name}': {e}")
            return None

    async def get_chat_records_by_session_prefix(self, table_name: str, session_id_prefix: str) -> List[Dict[str, Any]]:
        """
        Retrieves chat history records from a specific table where session_id matches a prefix.

        Args:
            table_name (str): The table to query.
            session_id_prefix (str): The prefix for the session_id (e.g., 'user@example.com_%').

        Returns:
            A list of chat history records, or an empty list if not found or on error.
        """
        try:
            async with self.pool.acquire() as conn:
                table_exists = await conn.fetchval(
                    "SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = $1)",
                    table_name
                )
                if not table_exists:
                    log.warning(f"Table '{table_name}' does not exist. Cannot retrieve old chats.")
                    return []

                query = f"""
                SELECT * FROM {table_name}
                WHERE session_id LIKE $1
                ORDER BY end_timestamp ASC; -- Order by timestamp to get chronological history
                """
                records = await conn.fetch(query, session_id_prefix)
                log.info(f"Retrieved {len(records)} records from '{table_name}' for session prefix '{session_id_prefix}'.")
                return [dict(row) for row in records]
        except Exception as e:
            log.error(f"Failed to retrieve chat records by session prefix from '{table_name}': {e}")
            return []

    async def update_agent_conversation_summary(
        self, agentic_application_id: str, session_id: str, summary: str):
        """
        Updates the conversation summary for a specific agent and session.
        Args:
            agentic_application_id (str): The ID of the agent application.
            session_id (str): The ID of the session.
            summary (str): The new summary to set.
        """
        table_name = "agent_conversation_summary_table"
        update_statement = f"""
        UPDATE {table_name}
        SET summary = $1, updated_on = CURRENT_TIMESTAMP
        WHERE agentic_application_id = $2 AND session_id = $3
        """
        try:
            async with self.pool.acquire() as conn:
                result = await conn.execute(update_statement, summary, agentic_application_id, session_id)
                if result != "UPDATE 0":
                    log.info(f"Updated agent conversation summary for session '{session_id}' in table '{table_name}'.")
                else:
                    log.warning(f"No agent conversation summary found for session '{session_id}', no update performed.")
                    return True
        except Exception as e:
            log.error(f"Failed to update agent conversation summary in '{table_name}': {e}")
            raise 

    async def get_chat_records_by_session_from_long_term_memory(
        self, table_name: str, session_id: str, limit: int
    ) -> List[Dict[str, Any]]:
        """
        Retrieves recent chat history records for a given session from a specific table.

        Args:
            table_name (str): The table to query.
            session_id (str): The ID of the chat session.
            limit (int): The maximum number of conversation pairs to retrieve.

        Returns:
            A list of chat history records, or an empty list if not found or on error.
        """
        try:
            async with self.pool.acquire() as conn:
                table_exists = await conn.fetchval(
                    "SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = $1)",
                    table_name
                )
                if not table_exists:
                    log.warning(f"Table '{table_name}' does not exist. Cannot retrieve memory.")
                    return []

                query = f"""
                SELECT session_id, start_timestamp, end_timestamp, human_message, ai_message, response_time
                FROM {table_name}
                WHERE session_id = $1
                ORDER BY end_timestamp DESC
                LIMIT $2
                """
                records = await conn.fetch(query, session_id, limit)
                log.info(f"Retrieved {len(records)} records from '{table_name}' for session '{session_id}'.")
                return [dict(row) for row in records]
        except Exception as e:
            log.error(f"Failed to retrieve chat records from '{table_name}': {e}")
            return []

    async def delete_session_transactional(self, chat_table_name: str, thread_id: str, session_id: str) -> int:
        """
        Deletes all data for a session (checkpoints and chat history) in a single transaction.

        Args:
            chat_table_name (str): The name of the specific chat history table.
            thread_id (str): The thread_id used in checkpoint tables.
            session_id (str): The session_id used in the chat history table.

        Returns:
            int: The number of rows deleted from the chat history table.
        
        Raises:
            Exception: Propagates any exception that occurs during the transaction.
        """
        internal_thread = f"inside{thread_id}"
        chat_rows_deleted = 0
        async with self.pool.acquire() as conn:
            async with conn.transaction():
                log.info(f"Starting transactional delete for thread_id: {thread_id}")
                await conn.execute(f"DELETE FROM {self.checkpoints_table} WHERE thread_id = $1 OR thread_id = $2", thread_id, internal_thread)
                await conn.execute(f"DELETE FROM {self.checkpoint_blobs_table} WHERE thread_id = $1 OR thread_id = $2", thread_id, internal_thread)
                await conn.execute(f"DELETE FROM {self.checkpoint_writes_table} WHERE thread_id = $1 OR thread_id = $2", thread_id, internal_thread)
                log.info(f"Deleted records from checkpoint tables for thread_id: {thread_id}")

                try:
                    result = await conn.execute(f"DELETE FROM {chat_table_name} WHERE session_id = $1", session_id)
                    chat_rows_deleted = int(result.split()[-1])
                    log.info(f"Deleted {chat_rows_deleted} rows from chat table '{chat_table_name}'.")
                except asyncpg.exceptions.UndefinedTableError:
                    log.warning(f"Chat table '{chat_table_name}' not found. Skipping deletion.")
                    chat_rows_deleted = 0
        return chat_rows_deleted

    async def delete_session_transactional_internal(self, internal_thread: str) -> int:
        """
        deletes all data for a session (checkpoints) in a single transaction.
        This method is used internally to delete checkpoints without affecting chat history.
        Args:
            internal_thread (str): The thread_id used in checkpoint tables.
        Returns:
            int: Always returns 0, as this method does not delete chat history rows.
        Raises:
            Exception: Propagates any exception that occurs during the transaction.
        """
        async with self.pool.acquire() as conn:
            async with conn.transaction():
                log.info(f"Starting transactional delete for thread_id: {internal_thread}")
                await conn.execute(f"DELETE FROM {self.checkpoints_table} WHERE thread_id = $1",internal_thread)
                await conn.execute(f"DELETE FROM {self.checkpoint_blobs_table} WHERE thread_id = $1", internal_thread)
                await conn.execute(f"DELETE FROM {self.checkpoint_writes_table} WHERE thread_id = $1",internal_thread)
                log.info(f"Deleted records from checkpoint tables for thread_id: {internal_thread}")

        return True  # No chat rows to delete in this internal method, as it only handles checkpoints.

    async def delete_agent_conversation_summary(self, agentic_application_id: str, session_id: str) -> bool:
        """
        Deletes the conversation summary for a specific agent and session.
        """
        table_name = "agent_conversation_summary_table"
        delete_statement = f"""
        DELETE FROM {table_name}
        WHERE agentic_application_id = $1 AND session_id = $2
        """
        try:
            async with self.pool.acquire() as conn:
                result = await conn.execute(delete_statement, agentic_application_id, session_id)
                if result != "DELETE 0":
                    log.info(f"Deleted agent conversation summary for session '{session_id}' in table '{table_name}'.")
                    return True
                else:
                    log.warning(f"No agent conversation summary found for session '{session_id}', no deletion performed.")
                    return False
        except Exception as e:
            log.error(f"Failed to delete agent conversation summary in '{table_name}': {e}")
            return False

    async def get_checkpointer_context_manager(self):
        """
        Returns an asynchronous context manager for LangGraph's PostgresSaver.
        This allows inference services to use 'async with chat_history_repository.get_checkpointer_context_manager() as checkpointer:'
        """
        if not self.DB_URL:
            raise ValueError("Could not get the database connection string for the checkpointer.")

        # AsyncPostgresSaver is itself an async context manager, so we just return its instance.
        # The caller will then use 'async with' on this returned instance.
        return AsyncPostgresSaver.from_conn_string(self.DB_URL)

    async def get_all_thread_ids_from_checkpoints(self) -> List[Dict[str, str]]:
        """
        Retrieves all unique chat session thread_ids from the checkpoints table.
        """
        try:
            async with self.pool.acquire() as conn:
                records = await conn.fetch(f"SELECT DISTINCT thread_id FROM {self.checkpoints_table};")
                log.info(f"Retrieved {len(records)} unique chat sessions from the database.")
                return [dict(record) for record in records]
        except Exception as e:
            log.error(f"An error occurred while retrieving all chat sessions: {e}")
            return []

    async def get_latest_message_record(
        self, table_name: str, session_id: str, message_column: str
    ) -> Dict[str, Any] | None:
        """
        Retrieves the latest message record (content and timestamp) for a given session and message type.

        Args:
            table_name (str): The name of the chat history table.
            session_id (str): The session ID.
            message_column (str): The column to retrieve ('human_message' or 'ai_message').

        Returns:
            Dict[str, Any] | None: A dictionary with 'message_content' and 'end_timestamp', or None if not found.
        """
        try:
            async with self.pool.acquire() as conn:
                table_exists = await conn.fetchval(
                    "SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = $1)",
                    table_name
                )
                if not table_exists:
                    log.warning(f"Table '{table_name}' does not exist. Cannot retrieve latest message.")
                    return None

                query = f"""
                SELECT {message_column} AS message_content, end_timestamp
                FROM {table_name}
                WHERE session_id = $1
                ORDER BY end_timestamp DESC
                LIMIT 1
                """
                record = await conn.fetchrow(query, session_id)
                return dict(record) if record else None
        except Exception as e:
            log.error(f"Error getting latest message record from '{table_name}': {e}")
            return None

    async def update_message_tag_record(
        self,
        table_name: str,
        session_id: str,
        message_column: str,
        updated_message_content: str,
        end_timestamp: datetime
    ) -> bool:
        """
        Updates a specific message record in a chat history table.

        Args:
            table_name (str): The name of the chat history table.
            session_id (str): The session ID of the message.
            message_column (str): The column to update ('human_message' or 'ai_message').
            updated_message_content (str): The new content for the message.
            end_timestamp (datetime): The timestamp to identify the specific message.

        Returns:
            bool: True if the update was successful, False otherwise.
        """
        update_query = f"""
        UPDATE {table_name}
        SET {message_column} = $1
        WHERE session_id = $2 AND end_timestamp = $3;
        """
        try:
            async with self.pool.acquire() as conn:
                result = await conn.execute(update_query, updated_message_content, session_id, end_timestamp)
            return result != "UPDATE 0"
        except Exception as e:
            log.error(f"Error updating message tag record in '{table_name}': {e}")
            return False

    async def fetch_user_query_from_chat_table(self, user_email:str, chat_table_name: str):
        """
        Fetches only the user query from the chat table for a given user_email.

        Args:
            user_email (str): The email of the user to filter the chat records.
            chat_table_name (str): The name of the chat table to query.

        Returns:
            dict: A dictionary with 'user_history' and 'agent_history' lists of user queries.
        """
        try:
            async with self.pool.acquire() as conn:
                query = f"""
                SELECT DISTINCT human_message
                FROM {chat_table_name}
                WHERE session_id like $1
                """
                user_history = await conn.fetch(query, f"{user_email}_%")

                query1 = f"""
                SELECT DISTINCT human_message
                FROM {chat_table_name}
                WHERE session_id not like $1;
                """
                agent_history = await conn.fetch(query1, f"{user_email}_%")

                return {
                    "user_history": [row['human_message'] for row in user_history],
                    "agent_history": [row['human_message'] for row in agent_history],
                }

        except Exception as e:
            log.error(f"Error fetching user queries from '{chat_table_name}': {e}")
            return {"user_history": [], "agent_history": []}

    async def fetch_memory_from_postgres(self):
            """
            Fetches memory data from PostgreSQL for a specific agent and key.

            Args:
                agent_id (str): The ID of the agent.

            Returns:
                dict: The memory data for the specified agent.
            """
            try:
                async with self.pool.acquire() as conn:
                    query = f"""
                    SELECT * FROM memory_records
                    """
                    result = await conn.fetch(query)
                    return {"data": result}
            except Exception as e:
                log.error(f"Error fetching memory from PostgreSQL: {e}")
                return {"error": str(e)}

