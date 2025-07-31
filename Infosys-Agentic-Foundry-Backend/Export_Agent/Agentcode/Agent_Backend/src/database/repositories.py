import os
import uuid
import asyncpg
from typing import List, Dict, Any, Optional, Union
from telemetry_wrapper import logger as log
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from datetime import datetime

# --- Base Repository ---

class BaseRepository:
    """
    Base class for all repositories.
    Provides the database connection pool to subclasses.
    """

    def __init__(self, pool: asyncpg.Pool, table_name: str):
        """
        Initializes the BaseRepository with a database connection pool.

        Args:
            pool (asyncpg.Pool): The asyncpg connection pool.
        """
        if not pool:
            raise ValueError("Connection pool is not provided.")
        self.pool = pool
        self.table_name = table_name
class AgentRepository(BaseRepository):
    """
    Repository for the 'agent_table'. Handles direct database interactions for agents.
    """

    def __init__(self, pool: asyncpg.Pool, table_name: str = "agent_table"):
        """
        Initializes the AgentRepository.

        Args:
            pool (asyncpg.Pool): The asyncpg connection pool.
            table_name (str): The name of the agents table.
        """
        super().__init__(pool, table_name)
    async def create_table_if_not_exists(self):
        """
        Creates the 'recycle_agent' table if it does not exist.
        """
        try:
            create_statement = f"""
            CREATE TABLE IF NOT EXISTS {self.table_name} (
                agentic_application_id TEXT PRIMARY KEY,
                agentic_application_name TEXT UNIQUE,
                agentic_application_description TEXT,
                agentic_application_workflow_description TEXT,
                agentic_application_type TEXT,
                model_name TEXT,
                system_prompt JSONB,
                tools_id JSONB,
                created_by TEXT
            );
            """
            async with self.pool.acquire() as conn:
                await conn.execute(create_statement)
            log.info(f"Table '{self.table_name}' created successfully or already exists.")
        except Exception as e:
            log.error(f"Error creating table '{self.table_name}': {e}")
            
    async def save_agent_record(self) -> bool:
        from agent_config import agent_data
        from worker_agents_config import worker_agents
        try:
            for agent in agent_data.values():
                agent_id = agent.get("agentic_application_id", str(uuid.uuid4()))
                agent_name = agent.get("agentic_application_name")
                agent_description = agent.get("agentic_application_description", "")
                workflow_description = agent.get("agentic_application_workflow_description", "")
                agent_type = agent.get("agentic_application_type", "default")
                model_name = agent.get("model_name", "default_model")
                system_prompt = agent.get("system_prompt", {})
                tools_id = agent.get("tools_id", [])
                created_by=agent.get("created_by","")

                insert_statement = f"""
                INSERT INTO {self.table_name} (
                    agentic_application_id,
                    agentic_application_name,
                    agentic_application_description,
                    agentic_application_workflow_description,
                    agentic_application_type,
                    model_name,
                    system_prompt,
                    tools_id,
                    created_by
                ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8,$9)
                ON CONFLICT (agentic_application_id) DO UPDATE SET
                    agentic_application_name = EXCLUDED.agentic_application_name,
                    agentic_application_description = EXCLUDED.agentic_application_description,
                    agentic_application_workflow_description = EXCLUDED.agentic_application_workflow_description,
                    agentic_application_type = EXCLUDED.agentic_application_type,
                    model_name = EXCLUDED.model_name,
                    system_prompt = EXCLUDED.system_prompt,
                    tools_id = EXCLUDED.tools_id,
                    created_by = EXCLUDED.created_by;
                """
                
                async with self.pool.acquire() as conn:
                    await conn.execute(insert_statement, 
                                       agent_id, 
                                       agent_name, 
                                       agent_description, 
                                       workflow_description, 
                                       agent_type, 
                                       model_name, 
                                       system_prompt, 
                                       tools_id,
                                       created_by)
            if worker_agents:
                for agent in worker_agents.values():
                    agent_id = agent.get("agentic_application_id", str(uuid.uuid4()))
                    agent_name = agent.get("agentic_application_name")
                    agent_description = agent.get("agentic_application_description", "")
                    workflow_description = agent.get("agentic_application_workflow_description", "")
                    agent_type = agent.get("agentic_application_type", "default")
                    model_name = agent.get("model_name", "default_model")
                    system_prompt = agent.get("system_prompt", {})
                    tools_id = agent.get("tools_id", [])
                    created_by=agent.get("created_by","")

                    insert_statement = f"""
                    INSERT INTO {self.table_name} (
                        agentic_application_id,
                        agentic_application_name,
                        agentic_application_description,
                        agentic_application_workflow_description,
                        agentic_application_type,
                        model_name,
                        system_prompt,
                        tools_id,
                        created_by
                    ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8,$9)
                    ON CONFLICT (agentic_application_id) DO UPDATE SET
                        agentic_application_name = EXCLUDED.agentic_application_name,
                        agentic_application_description = EXCLUDED.agentic_application_description,
                        agentic_application_workflow_description = EXCLUDED.agentic_application_workflow_description,
                        agentic_application_type = EXCLUDED.agentic_application_type,
                        model_name = EXCLUDED.model_name,
                        system_prompt = EXCLUDED.system_prompt,
                        tools_id = EXCLUDED.tools_id,
                        created_by = EXCLUDED.created_by;
                    """
                    
                    async with self.pool.acquire() as conn:
                        await conn.execute(insert_statement, 
                                        agent_id, 
                                        agent_name, 
                                        agent_description, 
                                        workflow_description, 
                                        agent_type, 
                                        model_name, 
                                        system_prompt, 
                                        tools_id,
                                        created_by)
            else:
                log.info("Worker Agents data is empty")
            
            log.info(f"Agent records saved successfully in table '{self.table_name}'.")
        except Exception as e:
            log.error(f"Error inserting into table '{self.table_name}': {e}")
            
    async def get_agents_details_for_chat_records(self) -> List[Dict[str, Any]]:
        """
        Retrieves basic agent details (ID, name, type) for chat purposes.

        Returns:
            List[Dict[str, Any]]: A list of dictionaries, each containing
                                  'agentic_application_id', 'agentic_application_name',
                                  and 'agentic_application_type'.
        """
        query = f"""
            SELECT agentic_application_id, agentic_application_name, agentic_application_type
            FROM {self.table_name}
        """
        try:
            async with self.pool.acquire() as conn:
                rows = await conn.fetch(query)
            log.info(f"Retrieved {len(rows)} agent chat detail records from '{self.table_name}'.")
            return [dict(row) for row in rows]
        except Exception as e:
            log.error(f"Error retrieving agent chat detail records: {e}")
            return []
    async def get_agent_record(self, agentic_application_id: Optional[str] = None, agentic_application_name: Optional[str] = None, agentic_application_type: Optional[str] = None, created_by: Optional[str] = None) -> Dict[str, Any] | None:
        """
        Retrieves a single agent record by ID, name, type, or creator.

        Args:
            agentic_application_id (Optional[str]): The ID of the agent.
            agentic_application_name (Optional[str]): The name of the agent.
            agentic_application_type (Optional[str]): The type of the agent.
            created_by (Optional[str]): The creator's email ID.

        Returns:
            Dict[str, Any] | None: A dictionary representing the agent record, or None if not found.
        """
        query = f"SELECT * FROM {self.table_name}"
        where_clauses = []
        params = []

        filters = {
            "agentic_application_id": agentic_application_id,
            "agentic_application_name": agentic_application_name,
            "created_by": created_by,
            "agentic_application_type": agentic_application_type
        }

        for idx, (field, value) in enumerate(((f for f in filters.items() if f[1] not in (None, ""))), start=1):
            where_clauses.append(f"{field} = ${idx}")
            params.append(value)

        if where_clauses:
            query += " WHERE " + " AND ".join(where_clauses)
        else:
            log.warning("No filter criteria provided to get_agent_record.")
            return None

        try:
            async with self.pool.acquire() as conn:
                rows = await conn.fetch(query, *params)

            results_as_dicts = [dict(row) for row in rows]

            log.info(f"Retrieved {len(results_as_dicts)} agent records from '{self.table_name}'.")
            return results_as_dicts

        except Exception as e:
            log.error(f"Error retrieving agent record '{agentic_application_id or agentic_application_name}': {e}")
            return None

class ToolRepository(BaseRepository):
    """
    Repository for the 'tool_table'. Handles direct database interactions for tools.
    """

    def __init__(self, pool: asyncpg.Pool, table_name: str = "tool_table"):
        """
        Initializes the ToolRepository.

        Args:
            pool (asyncpg.Pool): The asyncpg connection pool.
            table_name (str): The name of the tools table.
        """
        super().__init__(pool, table_name)

    async def create_table_if_not_exists(self):
        """
        Creates the 'tool_table' in PostgreSQL if it does not exist.
        """
        try:
            create_statement = f"""
            CREATE TABLE IF NOT EXISTS {self.table_name} (
                tool_id TEXT PRIMARY KEY,
                tool_name TEXT UNIQUE,
                tool_description TEXT,
                code_snippet TEXT,
                model_name TEXT,
                created_by TEXT
                
                
            );
            """
            async with self.pool.acquire() as conn:
                await conn.execute(create_statement)
            log.info(f"Table '{self.table_name}' created successfully or already exists.")
        except Exception as e:
            log.error(f"Error creating table '{self.table_name}': {e}")
    async def save_tool_record(self) -> bool:
        """
        Inserts a new tool record into the tool table.

        Args:
            tool_data (Dict[str, Any]): A dictionary containing the tool data.
                                        Expected keys: tool_id, tool_name, tool_description,
                                        code_snippet, model_name, created_by, created_on, updated_on.

        Returns:
            bool: True if the tool was inserted successfully, False if a unique violation occurred or on other error.
        """
        from tools_config import tools_data
        insert_statement = f"""
        INSERT INTO {self.table_name} (tool_id, tool_name, tool_description, code_snippet, model_name,created_by)
        VALUES ($1, $2, $3, $4, $5,$6) ON CONFLICT (tool_id) DO UPDATE SET
                    tool_name = EXCLUDED.tool_name,
                    tool_description = EXCLUDED.tool_description,
                    code_snippet = EXCLUDED.code_snippet,
                    model_name = EXCLUDED.model_name,
                    created_by = EXCLUDED.created_by;
        """
        try:
            for tool_data in tools_data.values():
                path= tool_data.get("code_snippet", "")
                with open(path, 'r', encoding='utf-8') as f:
                    code_snippet = f.read()
                async with self.pool.acquire() as conn:
                    await conn.execute(
                        insert_statement,
                        tool_data.get("tool_id"), tool_data.get("tool_name"),
                        tool_data.get("tool_description"), code_snippet,
                        tool_data.get("model_name"),
                        tool_data["created_by"]
                    )
                log.info(f"Tool record {tool_data.get('tool_name')} inserted successfully.")
            return True
        except asyncpg.UniqueViolationError:
            log.warning(f"Tool record {tool_data.get('tool_name')} already exists (unique violation).")
            return False
        except Exception as e:
            log.error(f"Error saving tool record {tool_data.get('tool_name')}: {e}")
            return False
    async def get_tool_record(self, tool_id: Optional[str] = None, tool_name: Optional[str] = None) -> Dict[str, Any] | None:
        """
        Retrieves a single tool record by its ID or name.

        Args:
            tool_id (Optional[str]): The ID of the tool.
            tool_name (Optional[str]): The name of the tool.

        Returns:
            Dict[str, Any] | None: A dictionary representing the tool record, or None if not found.
        """
        query = f"SELECT * FROM {self.table_name} WHERE "
        params = []
        if tool_id:
            query += "tool_id = $1"
            params.append(tool_id)
        elif tool_name:
            query += "tool_name = $1"
            params.append(tool_name)
        else:
            log.warning("No tool_id or tool_name provided to get_tool_record.")
            return None

        try:
            async with self.pool.acquire() as conn:
                rows = await conn.fetch(query, *params)
            if rows:
                log.info(f"Tool record '{tool_id or tool_name}' retrieved successfully.")
                return [dict(row) for row in rows]
            else:
                log.info(f"Tool record '{tool_id or tool_name}' not found.")
                return None
        except Exception as e:
            log.error(f"Error retrieving tool record '{tool_id or tool_name}': {e}")
            return None

    async def get_all_tool_records(self) -> List[Dict[str, Any]]:
        """
        Retrieves all tool records.

        Returns:
            List[Dict[str, Any]]: A list of dictionaries, each representing a tool record.
        """
        query = f"SELECT * FROM {self.table_name} ORDER BY created_on DESC"
        try:
            async with self.pool.acquire() as conn:
                rows = await conn.fetch(query)
            log.info(f"Retrieved {len(rows)} tool records from '{self.table_name}'.")
            return [dict(row) for row in rows]
        except Exception as e:
            log.error(f"Error retrieving all tool records: {e}")
            return []

class ChatHistoryRepository(BaseRepository):
    """
    Repository for chat history. Handles direct database interactions with
    dynamically named chat tables and the shared checkpoint tables.
    """

    def __init__(self, pool: asyncpg.Pool):
        """
        Initializes the ChatHistoryRepository.

        Args:
            pool (asyncpg.Pool): The asyncpg connection pool.
        """
        # We pass a empty table_name to super, as this repo handles multiple tables.
        super().__init__(pool, table_name="")
        self.DB_URL = os.getenv("POSTGRESQL_DATABASE_URL")  # Ensure this is correctly loaded
        self.checkpoints_table = "checkpoints"
        self.checkpoint_blobs_table = "checkpoint_blobs"
        self.checkpoint_writes_table = "checkpoint_writes"

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
            PRIMARY KEY (session_id, end_timestamp)
        );
        """
        try:
            async with self.pool.acquire() as conn:
                await conn.execute(create_statement)
            log.info(f"Table '{table_name}' created successfully or already exists.")
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
        ai_message: str
    ):
        """
        Inserts a new chat message pair into a specified table.

        Args:
            table_name (str): The table to insert into.
            (all other args are data for the record)
        """
        insert_statement = f"""
        INSERT INTO {table_name} (
            session_id, start_timestamp, end_timestamp, human_message, ai_message
        ) VALUES ($1, $2, $3, $4, $5)
        """
        try:
            async with self.pool.acquire() as conn:
                await conn.execute(
                    insert_statement,
                    session_id,
                    start_timestamp,
                    end_timestamp,
                    human_message,
                    ai_message
                )
            log.info(f"Chat history inserted into '{table_name}' for session '{session_id}'.")
        except Exception as e:
            log.error(f"Failed to insert chat history into '{table_name}': {e}")
            raise

    async def get_checkpointer_context_manager(self) -> AsyncPostgresSaver:
        """
        Returns an asynchronous context manager for LangGraph's PostgresSaver.
        This allows inference services to use 'async with chat_history_repository.get_checkpointer_context_manager() as checkpointer:'
        """
        if not self.DB_URL:
            raise ValueError("POSTGRESQL_DATABASE_URL (for checkpointer) is not configured in DatabaseManager.")
        
        # AsyncPostgresSaver is itself an async context manager, so we just return its instance.
        # The caller will then use 'async with' on this returned instance.
        return AsyncPostgresSaver.from_conn_string(self.DB_URL)
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
                SELECT session_id, start_timestamp, end_timestamp, human_message, ai_message
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