# © 2024-25 Infosys Limited, Bangalore, India. All Rights Reserved.
import json
import asyncpg
from typing import List, Dict, Any, Optional, Tuple
from src.config.constants import TableNames

from telemetry_wrapper import logger as log

from src.database.repositories import BaseRepository

# --- Chat State History Manager Repository Class ---

class ChatStateHistoryManagerRepository(BaseRepository):
    """
    Manages chat state history storage and retrieval in a PostgreSQL database.
    Each entry represents a single turn of interaction (user query + agent steps + final response).
    """

    def __init__(self, pool: asyncpg.Pool, login_pool: asyncpg.Pool, table_name: str = TableNames.AGENT_CHAT_STATE_HISTORY.value):
        """
        Initializes the ChatHistoryManager with a database connection pool and table name.
        """
        super().__init__(pool, login_pool, table_name)

    async def create_table_if_not_exists(self):
        """
        Creates the chat history table and necessary indexes if they don't exist.
        """
        create_table_statement = f"""
            CREATE TABLE IF NOT EXISTS {self.table_name} (
                id SERIAL PRIMARY KEY,
                thread_id TEXT NOT NULL,
                user_query TEXT NOT NULL,
                agent_steps JSONB NOT NULL,
                final_response TEXT, -- Can be NULL if interrupted
                timestamp TIMESTAMP WITH TIME ZONE DEFAULT NOW()
            );
        """
        # Add an index on thread_id for faster lookups
        # A composite index on (thread_id, timestamp) is even better for queries
        # that filter by thread_id and order by timestamp (like get_recent_history)
        create_index_statement = f"""
            CREATE INDEX IF NOT EXISTS idx_{self.table_name}_thread_id_timestamp
            ON {self.table_name} (thread_id, timestamp DESC);
        """

        try:
            async with self.pool.acquire() as conn:
                await conn.execute(create_table_statement)
                await conn.execute(create_index_statement)
            log.info(f"[DB] Table '{self.table_name}' and index ensured to exist.")

        except Exception as e:
            log.error(f"[DB] Error creating table or index '{self.table_name}': {e}")
            raise

    async def add_chat_entry(
        self,
        thread_id: str,
        user_query: str,
        agent_steps: List[Dict[str, Any]],
        final_response: Optional[str] = None
    ) -> int:
        """Adds a new chat entry to the database."""
        insert_statement = f"""
            INSERT INTO {self.table_name} (thread_id, user_query, agent_steps, final_response)
            VALUES ($1, $2, $3, $4)
            RETURNING id;
        """
        try:
            async with self.pool.acquire() as conn:
                entry_id = await conn.fetchval(insert_statement, thread_id, user_query, json.dumps(agent_steps), final_response)
            log.info(f"[DB] Added chat entry {entry_id} for thread '{thread_id}'.")

        except Exception as e:
            log.error(f"[DB] Error adding chat entry for thread '{thread_id}': {e}")
            return -1
        return entry_id

    async def update_chat_entry(
        self,
        entry_id: int,
        thread_id: str,
        agent_steps: List[Dict[str, Any]],
        final_response: Optional[str] = None
    ):
        """Updates an existing chat entry."""
        try:
            async with self.pool.acquire() as conn:
                await conn.execute(f"""
                    UPDATE {self.table_name}
                    SET agent_steps = $1, final_response = $2, timestamp = NOW()
                    WHERE id = $3 AND thread_id = $4;
                """, json.dumps(agent_steps), final_response, entry_id, thread_id)
            log.info(f"[DB] Updated chat entry {entry_id} for thread '{thread_id}'.")
            return True
        except Exception as e:
            log.error(f"[DB] Error updating chat entry {entry_id} for thread '{thread_id}': {e}")
            return False

    async def get_recent_history(self, thread_id: str, num_entries: Optional[int] = None) -> List[Dict[str, Any]]:
        """
        Retrieves recent chat history entries for a given thread_id.
        If num_entries is None, retrieves all entries.
        Returns a list of dictionaries, each representing an 'executor_message' turn.
        """
        try:
            async with self.pool.acquire() as conn:
                query = f"""
                    SELECT user_query, agent_steps, final_response
                    FROM {self.table_name}
                    WHERE thread_id = $1
                    ORDER BY timestamp DESC
                """
                if isinstance(num_entries, int) and num_entries >= 0:
                    query += f" LIMIT {num_entries}"

                records = await conn.fetch(query, thread_id)

                history = []
                for record in reversed(records):
                    history.append({
                        "user_query": record["user_query"],
                        "final_response": record["final_response"],
                        "agent_steps": json.loads(record["agent_steps"])
                    })
            log.info(f"[DB] Retrieved {len(history)} history entries for thread '{thread_id}'.")
            return history
        except Exception as e:
            log.error(f"[DB] Error retrieving chat history for thread '{thread_id}': {e}")
            return []

    async def get_chat_records_by_thread_id_prefix(self, thread_id_prefix: str) -> List[Dict[str, Any]]:
        """
        Retrieves chat history records from the table where thread_id matches a prefix.

        Args:
            thread_id_prefix (str): The prefix for the thread_id (e.g., 'hybrid_agent_uuid_user@example.com_%').

        Returns:
            A list of chat history records, or an empty list if not found or on error.
        """
        try:
            if not thread_id_prefix.endswith('%'):
                thread_id_prefix += '%'
            async with self.pool.acquire() as conn:
                query = f"""
                    SELECT thread_id, user_query, agent_steps, final_response, timestamp
                    FROM {self.table_name}
                    WHERE thread_id LIKE $1
                    ORDER BY timestamp ASC;
                """
                records = await conn.fetch(query, thread_id_prefix)
                log.info(f"[DB] Retrieved {len(records)} records from '{self.table_name}' for thread_id prefix '{thread_id_prefix}'.")
                
                records = [dict(row) for row in records]
                # Deserialize agent_steps from JSONB
                for record in records:
                    record["agent_steps"] = json.loads(record["agent_steps"])

                return records
                
        except Exception as e:
            log.error(f"[DB] Failed to retrieve chat records by thread_id prefix from '{self.table_name}': {e}")
            return []

    async def get_most_recent_chat_entry(self, thread_id: str) -> Optional[Tuple[int, Dict[str, Any]]]:
        """
        Retrieves the most recent chat entry for a given thread_id, regardless of its final_response status.
        Returns (entry_id, chat_entry_dict) or (None, None) if not found or error.
        """
        try:
            async with self.pool.acquire() as conn:
                record = await conn.fetchrow(f"""
                    SELECT id, user_query, agent_steps, final_response
                    FROM {self.table_name}
                    WHERE thread_id = $1
                    ORDER BY timestamp DESC
                    LIMIT 1;
                """, thread_id)
                if record:
                    log.info(f"[DB] Found most recent chat entry {record['id']} for thread '{thread_id}'.")
                    return record["id"], {
                        "user_query": record["user_query"],
                        "final_response": record["final_response"],
                        "agent_steps": json.loads(record["agent_steps"])
                    }
                log.info(f"[DB] No recent chat entry found for thread '{thread_id}'.")
                return None, None

        except Exception as e:
            log.error(f"[DB] Error retrieving most recent chat entry for thread '{thread_id}': {e}")
            return None, None

    async def clear_chat_history(self, thread_id: str):
        """Deletes all chat entries for a given thread_id."""
        try:
            async with self.pool.acquire() as conn:
                await conn.execute(f"""
                    DELETE FROM {self.table_name}
                    WHERE thread_id = $1;
                """, thread_id)
            log.info(f"[DB] Cleared chat history for thread '{thread_id}'.")
            return True

        except Exception as e:
            log.error(f"[DB] Error clearing chat history for thread '{thread_id}': {e}")
            return False

    async def delete_chat_entry(self, entry_id: int, thread_id: str) -> bool:
        """
        Deletes a specific chat entry by its ID and thread_id.
        """
        try:
            async with self.pool.acquire() as conn:
                result = await conn.execute(f"""
                    DELETE FROM {self.table_name}
                    WHERE id = $1 AND thread_id = $2;
                """, entry_id, thread_id)
            if result == "DELETE 1":
                log.info(f"[DB] Deleted chat entry {entry_id} for thread '{thread_id}'.")
                return True
            else:
                log.warning(f"[DB] Chat entry {entry_id} for thread '{thread_id}' not found for deletion.")
                return False
        except Exception as e:
            log.error(f"[DB] Error deleting chat entry {entry_id} for thread '{thread_id}': {e}")
            return False

