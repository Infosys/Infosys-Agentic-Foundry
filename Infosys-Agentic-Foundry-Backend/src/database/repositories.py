# © 2024-25 Infosys Limited, Bangalore, India. All Rights Reserved.
import os
import uuid
import json
import asyncpg
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional, Union, Literal
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
import difflib
from src.utils.cache_utils import cache_result, invalidate_entity_cache, CacheableRepository
from src.config.cache_config import EXPIRY_TIME, ENABLE_CACHING
from telemetry_wrapper import logger as log
from src.utils.secrets_handler import current_user_email

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



# --- Tag Repository ---
class TagRepository(BaseRepository, CacheableRepository):
    """
    Repository for the 'tags_table'. Handles direct database interactions for tags.
    """

    def __init__(self, pool: asyncpg.Pool, table_name: str = "tags_table"):
        """
        Initializes the TagRepository.

        Args:
            pool (asyncpg.Pool): The asyncpg connection pool.
            table_name (str): The name of the tags table.
        """
        super().__init__(pool, table_name)


    async def create_table_if_not_exists(self):
        """
        Creates the 'tags_table' in PostgreSQL if it does not exist.
        """
        try:
            create_statement = f"""
            CREATE TABLE IF NOT EXISTS {self.table_name} (
                tag_id TEXT PRIMARY KEY,
                tag_name TEXT UNIQUE NOT NULL,
                created_by TEXT NOT NULL
            );
            """

            default_tags = [
                'General', 'Healthcare & Life Sciences', 'Finance & Banking', 'Education & Training', 'Retail & E-commerce',
                'Insurance', 'Logistics', 'Utilities', 'Travel and Hospitality', 'Agri Industry', 'Manufacturing', 'Metals and Mining',
            ]

            async with self.pool.acquire() as conn:
                await conn.execute(create_statement)

                # Insert the 'Common' tag if the table is newly created
                for default_tag in default_tags:
                    insert_query = f"""
                    INSERT INTO {self.table_name} (tag_id, tag_name, created_by)
                    VALUES ($1, $2, 'system@infosys.com')
                    ON CONFLICT (tag_name) DO NOTHING
                    """
                    await conn.execute(insert_query, str(uuid.uuid4()), default_tag)

            log.info(f"Table '{self.table_name}' created successfully or already exists.")
        except Exception as e:
            log.error(f"Error creating table '{self.table_name}': {e}")

    async def insert_tag_record(self, tag_id: str, tag_name: str, created_by: str) -> bool:
        """
        Inserts a new tag record into the tags table.

        Args:
            tag_id (str): The unique ID of the tag.
            tag_name (str): The name of the tag.
            created_by (str): The creator of the tag.

        Returns:
            bool: True if the tag was inserted successfully, False if a unique violation occurred or on other error.
        """
        insert_statement = f"""
        INSERT INTO {self.table_name} (tag_id, tag_name, created_by)
        VALUES ($1, $2, $3)
        """
        try:
            async with self.pool.acquire() as conn:
                await conn.execute(insert_statement, tag_id, tag_name.strip(), created_by)
            self.invalidate_entity("get_tag_record",tag_id, tag_name)
            self.invalidate_entity("get_all_tag_records")
            log.info(f"Tag record '{tag_name}' inserted successfully.")
            return True
        except asyncpg.UniqueViolationError:
            log.warning(f"Tag record '{tag_name}' already exists (unique violation).")
            return False
        except Exception as e:
            log.error(f"Error inserting tag record '{tag_name}': {e}")
            return False
        
    @CacheableRepository.cache(ttl=EXPIRY_TIME, namespace="TagRepository")
    async def get_all_tag_records(self) -> List[Dict[str, Any]]:
        """
        Retrieves all tag records from the tags table.

        Returns:
            List[Dict[str, Any]]: A list of dictionaries, each representing a tag record.
        """
        query = f"SELECT * FROM {self.table_name}"
        try:
            async with self.pool.acquire() as conn:
                rows = await conn.fetch(query)
            log.info(f"Retrieved {len(rows)} tag records from '{self.table_name}'.")
            return [dict(row) for row in rows]
        except Exception as e:
            log.error(f"Error retrieving all tag records: {e}")
            return []

    @CacheableRepository.cache(ttl=EXPIRY_TIME, namespace="TagRepository")
    async def get_tag_record(self, tag_id: Optional[str] = None, tag_name: Optional[str] = None) -> Dict[str, Any]:
        """
        Retrieves a single tag record by its ID or name.

        Args:
            tag_id (Optional[str]): The ID of the tag.
            tag_name (Optional[str]): The name of the tag.

        Returns:
            Dict[str, Any] | None: A dictionary representing the tag record, or None if not found.
        """
        query = f"SELECT * FROM {self.table_name} WHERE "
        param = None
        if tag_id:
            query += "tag_id = $1"
            param = tag_id
        elif tag_name:
            query += "tag_name = $1"
            param = tag_name
        else:
            log.warning("No tag_id or tag_name provided to get_tag_record.")
            return {}

        try:
            async with self.pool.acquire() as conn:
                row = await conn.fetchrow(query, param)
            if row:
                log.info(f"Tag record '{tag_id or tag_name}' retrieved successfully.")
                return dict(row)
            else:
                log.info(f"Tag record '{tag_id or tag_name}' not found.")
                return {}
        except Exception as e:
            log.error(f"Error retrieving tag record '{tag_id or tag_name}': {e}")
            return {}

    async def update_tag_record(self, tag_id: str, new_tag_name: str, created_by: str) -> bool:
        """
        Updates a tag record by its ID, ensuring it was created by the specified user.

        Args:
            tag_id (str): The ID of the tag to update.
            new_tag_name (str): The new name for the tag.
            created_by (str): The creator of the tag.

        Returns:
            bool: True if the tag was updated successfully, False otherwise.
        """
        update_statement = f"UPDATE {self.table_name} SET tag_name = $1 WHERE tag_id = $2 AND created_by = $3"
        try:
            async with self.pool.acquire() as conn:
                result = await conn.execute(update_statement, new_tag_name, tag_id, created_by)
            self.invalidate_entity("get_tag_record", tag_id)
            self.invalidate_entity("get_all_tag_records")
            if result != "UPDATE 0":
                log.info(f"Tag record '{tag_id}' updated successfully to '{new_tag_name}'.")
                return True
            else:
                log.warning(f"Tag record '{tag_id}' not found or not created by '{created_by}', no update performed.")
                return False
        except Exception as e:
            log.error(f"Error updating tag record '{tag_id}': {e}")
            return False

    async def delete_tag_record(self, tag_id: str, created_by: str) -> bool:
        """
        Deletes a tag record by its ID, ensuring it was created by the specified user.

        Args:
            tag_id (str): The ID of the tag to delete.
            created_by (str): The creator of the tag.

        Returns:
            bool: True if the tag was deleted successfully, False otherwise.
        """
        delete_statement = f"DELETE FROM {self.table_name} WHERE tag_id = $1 AND created_by = $2"
        try:
            async with self.pool.acquire() as conn:
                result = await conn.execute(delete_statement, tag_id, created_by)
            self.invalidate_entity("get_tag_record", tag_id)
            self.invalidate_entity("get_all_tag_records")
            if result != "DELETE 0":
                log.info(f"Tag record '{tag_id}' deleted successfully.")
                return True
            else:
                log.warning(f"Tag record '{tag_id}' not found or not created by '{created_by}', no deletion performed.")
                return False
        except asyncpg.ForeignKeyViolationError as e:
            log.error(f"Cannot delete tag '{tag_id}' due to foreign key constraint: {e}")
            return False
        except Exception as e:
            log.error(f"Error deleting tag record '{tag_id}': {e}")
            return False



# --- TagToolMappingRepository ---

class TagToolMappingRepository(BaseRepository, CacheableRepository):
    """
    Repository for the 'tag_tool_mapping_table'. Handles direct database interactions for tag-tool mappings.
    """

    def __init__(self, pool: asyncpg.Pool, table_name: str = "tag_tool_mapping_table"):
        """
        Initializes the TagToolMappingRepository.

        Args:
            pool (asyncpg.Pool): The asyncpg connection pool.
            table_name (str): The name of the tag-tool mapping table.
        """
        super().__init__(pool, table_name)


    async def create_table_if_not_exists(self):
        """
        Creates the 'tag_tool_mapping_table' if it does not exist.
        The FOREIGN KEY to tool_table.tool_id is intentionally removed here
        to allow mapping of tool IDs from both tool_table and mcp_tool_table.
        """
        try:
            create_statement = f"""
            CREATE TABLE IF NOT EXISTS {self.table_name} (
                tag_id TEXT,
                tool_id TEXT,
                FOREIGN KEY(tag_id) REFERENCES tags_table(tag_id) ON DELETE RESTRICT,
                UNIQUE(tag_id, tool_id)
            );
            """
            async with self.pool.acquire() as conn:
                await conn.execute(create_statement)
            log.info(f"Table '{self.table_name}' created successfully or already exists (without tool_id FK).")
        except Exception as e:
            log.error(f"Error creating table '{self.table_name}': {e}")

    async def assign_tag_to_tool_record(self, tag_id: str, tool_id: str) -> bool:
        """
        Inserts a mapping between a tag and a tool.

        Args:
            tag_id (str): The ID of the tag.
            tool_id (str): The ID of the tool.

        Returns:
            bool: True if the mapping was inserted successfully, False otherwise.
        """
        insert_statement = f"""
        INSERT INTO {self.table_name} (tag_id, tool_id)
        VALUES ($1, $2)
        ON CONFLICT (tag_id, tool_id) DO NOTHING;
        """
        try:
            async with self.pool.acquire() as conn:
                await conn.execute(insert_statement, tag_id, tool_id)
            self.invalidate_entity("get_tool_tag_mappings")
            self.invalidate_entity("get_tags_by_tool_id_records", tool_id=tool_id)
            log.info(f"Mapping tag '{tag_id}' to tool '{tool_id}' inserted successfully.")
            return True
        except Exception as e:
            log.error(f"Error assigning tag '{tag_id}' to tool '{tool_id}': {e}")
            return False

    async def remove_tag_from_tool_record(self, tag_id: str, tool_id: str) -> bool:
        """
        Deletes a mapping between a tag and a tool.

        Args:
            tag_id (str): The ID of the tag.
            tool_id (str): The ID of the tool.

        Returns:
            bool: True if the mapping was deleted successfully, False otherwise.
        """
        delete_statement = f"""
        DELETE FROM {self.table_name}
        WHERE tag_id = $1 AND tool_id = $2;
        """
        try:
            async with self.pool.acquire() as conn:
                result = await conn.execute(delete_statement, tag_id, tool_id)
            if result != "DELETE 0":
                log.info(f"Mapping tag '{tag_id}' from tool '{tool_id}' removed successfully.")
                self.invalidate_entity("get_tool_tag_mappings")
                self.invalidate_entity("get_tags_by_tool_id_records", tool_id=tool_id)
                return True
            else:
                log.warning(f"Mapping tag '{tag_id}' from tool '{tool_id}' not found, no deletion performed.")
                return False
        except Exception as e:
            log.error(f"Error removing tag '{tag_id}' from tool '{tool_id}': {e}")
            return False

    @CacheableRepository.cache(ttl=EXPIRY_TIME, namespace="TagToolMappingRepository")
    async def get_tool_tag_mappings(self) -> List[Dict[str, Any]]:
        """
        Retrieves all raw tool-tag mappings.

        Returns:
            List[Dict[str, Any]]: A list of dictionaries, each representing a tool-tag mapping.
        """
        query = f"SELECT tag_id, tool_id FROM {self.table_name};"
        try:
            async with self.pool.acquire() as conn:
                rows = await conn.fetch(query)
            log.info(f"Retrieved {len(rows)} tool-tag mappings from '{self.table_name}'.")
            return [dict(row) for row in rows]
        except Exception as e:
            log.error(f"Error retrieving tool-tag mappings: {e}")
            return []
        
    @CacheableRepository.cache(ttl=EXPIRY_TIME, namespace="TagToolMappingRepository")
    async def get_tags_by_tool_id_records(self, tool_id: str) -> List[str]:
        """
        Retrieves a list of tag_ids associated with a specific tool_id.

        Args:
            tool_id (str): The ID of the tool.

        Returns:
            List[str]: A list of tag IDs.
        """
        query = f"SELECT tag_id FROM {self.table_name} WHERE tool_id = $1;"
        try:
            async with self.pool.acquire() as conn:
                rows = await conn.fetch(query, tool_id)
            log.info(f"Retrieved {len(rows)} tag IDs for tool '{tool_id}'.")
            return [row['tag_id'] for row in rows]
        except Exception as e:
            log.error(f"Error retrieving tag IDs for tool '{tool_id}': {e}")
            return []

    async def delete_all_tags_for_tool(self, tool_id: str) -> bool:
        """
        Deletes all tag mappings for a given tool.

        Args:
            tool_id (str): The ID of the tool.

        Returns:
            bool: True if mappings were deleted successfully, False otherwise.
        """
        delete_statement = f"DELETE FROM {self.table_name} WHERE tool_id = $1;"
        try:
            async with self.pool.acquire() as conn:
                result = await conn.execute(delete_statement, tool_id)
            if result != "DELETE 0": 
                self.invalidate_entity("get_tool_tag_mappings")
                self.invalidate_entity("get_tags_by_tool_id_records", tool_id=tool_id)
                log.info(f"All tag mappings for tool '{tool_id}' deleted successfully.")
                return True
            else:
                log.warning(f"No tag mappings found for tool '{tool_id}', no deletion performed.")
                return False
        except Exception as e:
            log.error(f"Error deleting all tag mappings for tool '{tool_id}': {e}")
            return False

    async def drop_tool_id_fk_constraint(self):
        """
        Dynamically finds and drops the foreign key constraint on tag_tool_mapping_table.tool_id.
        This is crucial for allowing tool IDs from both tool_table and mcp_tool_table.
        """
        try:
            async with self.pool.acquire() as conn:
                constraint_query = f"""
                SELECT tc.constraint_name
                FROM information_schema.table_constraints AS tc
                JOIN information_schema.key_column_usage AS kcu
                  ON tc.constraint_name = kcu.constraint_name
                WHERE tc.table_schema = current_schema()
                  AND tc.table_name = '{self.table_name}'
                  AND kcu.column_name = 'tool_id'
                  AND tc.constraint_type = 'FOREIGN KEY';
                """
                constraint_record = await conn.fetchrow(constraint_query)

                if constraint_record:
                    constraint_name = constraint_record['constraint_name']
                    drop_fk_statement = f"""
                    ALTER TABLE {self.table_name}
                    DROP CONSTRAINT {constraint_name};
                    """
                    await conn.execute(drop_fk_statement)
                    log.info(f"Successfully dropped foreign key constraint '{constraint_name}' on '{self.table_name}.tool_id'.")
                    return True
                else:
                    log.info(f"No foreign key constraint found on '{self.table_name}.tool_id' to drop. (This is expected if already removed).")
                    return False

        except Exception as e:
            log.error(f"Error attempting to drop foreign key constraint on '{self.table_name}.tool_id': {e}")
            return False



# --- TagAgentMappingRepository ---

class TagAgentMappingRepository(BaseRepository, CacheableRepository):
    """
    Repository for the 'tag_agentic_app_mapping_table'. Handles direct database interactions for tag-agent mappings.
    """

    def __init__(self, pool: asyncpg.Pool, table_name: str = "tag_agentic_app_mapping_table"):
        """
        Initializes the TagAgentMappingRepository.

        Args:
            pool (asyncpg.Pool): The asyncpg connection pool.
            table_name (str): The name of the tag-agent mapping table.
        """
        super().__init__(pool, table_name)


    async def create_table_if_not_exists(self):
        """
        Creates the 'tag_agentic_app_mapping_table' if it does not exist.
        """
        try:
            create_statement = f"""
            CREATE TABLE IF NOT EXISTS {self.table_name} (
                tag_id TEXT,
                agentic_application_id TEXT,
                FOREIGN KEY(tag_id) REFERENCES tags_table(tag_id) ON DELETE RESTRICT,
                FOREIGN KEY(agentic_application_id) REFERENCES agent_table(agentic_application_id) ON DELETE CASCADE,
                UNIQUE(tag_id, agentic_application_id)
            );
            """
            async with self.pool.acquire() as conn:
                await conn.execute(create_statement)
            log.info(f"Table '{self.table_name}' created successfully or already exists.")
        except Exception as e:
            log.error(f"Error creating table '{self.table_name}': {e}")

    async def assign_tag_to_agent_record(self, tag_id: str, agentic_application_id: str) -> bool:
        """
        Inserts a mapping between a tag and an agent.

        Args:
            tag_id (str): The ID of the tag.
            agentic_application_id (str): The ID of the agent.

        Returns:
            bool: True if the mapping was inserted successfully, False otherwise.
        """
        insert_statement = f"""
        INSERT INTO {self.table_name} (tag_id, agentic_application_id)
        VALUES ($1, $2)
        ON CONFLICT (tag_id, agentic_application_id) DO NOTHING;
        """
        try:
            async with self.pool.acquire() as conn:
                await conn.execute(insert_statement, tag_id, agentic_application_id)
            self.invalidate_entity("get_agent_tag_mappings")
            self.invalidate_entity("get_tags_by_agent_id_records", agent_id=agentic_application_id)
            log.info(f"Mapping tag '{tag_id}' to agent '{agentic_application_id}' inserted successfully.")
            return True
        except Exception as e:
            log.error(f"Error assigning tag '{tag_id}' to agent '{agentic_application_id}': {e}")
            return False

    async def remove_tag_from_agent_record(self, tag_id: str, agentic_application_id: str) -> bool:
        """
        Deletes a mapping between a tag and an agent.

        Args:
            tag_id (str): The ID of the tag.
            agentic_application_id (str): The ID of the agent.

        Returns:
            bool: True if the mapping was deleted successfully, False otherwise.
        """
        delete_statement = f"""
        DELETE FROM {self.table_name}
        WHERE tag_id = $1 AND agentic_application_id = $2;
        """
        try:
            async with self.pool.acquire() as conn:
                result = await conn.execute(delete_statement, tag_id, agentic_application_id)
            if result != "DELETE 0":
                log.info(f"Mapping tag '{tag_id}' from agent '{agentic_application_id}' removed successfully.")
                self.invalidate_entity("get_agent_tag_mappings")
                self.invalidate_entity("get_tags_by_agent_id_records", agent_id=agentic_application_id)
                return True
            else:
                log.warning(f"Mapping tag '{tag_id}' from agent '{agentic_application_id}' not found, no deletion performed.")
                return False
        except Exception as e:
            log.error(f"Error removing tag '{tag_id}' from agent '{agentic_application_id}': {e}")
            return False

    @CacheableRepository.cache(ttl=EXPIRY_TIME, namespace="TagAgentMappingRepository")
    async def get_agent_tag_mappings(self) -> List[Dict[str, Any]]:
        """
        Retrieves all raw agent-tag mappings.

        Returns:
            List[Dict[str, Any]]: A list of dictionaries, each representing an agent-tag mapping.
        """
        query = f"SELECT tag_id, agentic_application_id FROM {self.table_name};"
        try:
            async with self.pool.acquire() as conn:
                rows = await conn.fetch(query)
            log.info(f"Retrieved {len(rows)} agent-tag mappings from '{self.table_name}'.")
            return [dict(row) for row in rows]
        except Exception as e:
            log.error(f"Error retrieving agent-tag mappings: {e}")
            return []
        
    @CacheableRepository.cache(ttl=EXPIRY_TIME, namespace="TagAgentMappingRepository")
    async def get_tags_by_agent_id_records(self, agent_id: str) -> List[str]:
        """
        Retrieves a list of tag_ids associated with a specific agent_id.

        Args:
            agent_id (str): The ID of the agent.

        Returns:
            List[str]: A list of tag IDs.
        """
        query = f"SELECT tag_id FROM {self.table_name} WHERE agentic_application_id = $1;"
        try:
            async with self.pool.acquire() as conn:
                rows = await conn.fetch(query, agent_id)
            log.info(f"Retrieved {len(rows)} tag IDs for agent '{agent_id}'.")
            return [row['tag_id'] for row in rows]
        except Exception as e:
            log.error(f"Error retrieving tag IDs for agent '{agent_id}': {e}")
            return []
        
    async def delete_all_tags_for_agent(self, agent_id: str) -> bool:
        """
        Deletes all tag mappings for a given agent.

        Args:
            agent_id (str): The ID of the agent.

        Returns:
            bool: True if mappings were deleted successfully, False otherwise.
        """
        delete_statement = f"DELETE FROM {self.table_name} WHERE agentic_application_id = $1;"
        try:
            async with self.pool.acquire() as conn:
                result = await conn.execute(delete_statement, agent_id)
            if result != "DELETE 0":
                self.invalidate_entity("get_agent_tag_mappings")
                self.invalidate_entity("get_tags_by_agent_id_records", agent_id=agent_id)
                log.info(f"All tag mappings for agent '{agent_id}' deleted successfully.")
                return True
            else:
                log.warning(f"No tag mappings found for agent '{agent_id}', no deletion performed.")
                return False
        except Exception as e:
            log.error(f"Error deleting all tag mappings for agent '{agent_id}': {e}")
            return False



# --- Tool Repository ---

class ToolRepository(BaseRepository, CacheableRepository):
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
                created_by TEXT,
                created_on TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_on TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                is_public BOOLEAN DEFAULT FALSE,
                status TEXT DEFAULT 'pending',
                comments TEXT,
                approved_at TIMESTAMPTZ,
                approved_by TEXT,
                CHECK (status IN ('pending', 'approved', 'rejected'))
            );
            """
            async with self.pool.acquire() as conn:
                await conn.execute(create_statement)
                alter_statements = [
                    f"ALTER TABLE {self.table_name} ADD COLUMN IF NOT EXISTS is_public BOOLEAN DEFAULT FALSE",
                    f"ALTER TABLE {self.table_name} ADD COLUMN IF NOT EXISTS status TEXT DEFAULT 'pending'",
                    f"ALTER TABLE {self.table_name} ADD COLUMN IF NOT EXISTS comments TEXT",
                    f"ALTER TABLE {self.table_name} ADD COLUMN IF NOT EXISTS approved_at TIMESTAMPTZ",
                    f"ALTER TABLE {self.table_name} ADD COLUMN IF NOT EXISTS approved_by TEXT",
                    f"DO $$ BEGIN "
                    f"IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = '{self.table_name}_status_check') THEN "
                    f"ALTER TABLE {self.table_name} ADD CONSTRAINT {self.table_name}_status_check CHECK (status IN ('pending', 'approved', 'rejected')); "
                    f"END IF; END $$;"
                ]

                for stmt in alter_statements:
                    await conn.execute(stmt)
            log.info(f"Table '{self.table_name}' created successfully or already exists.")
        except Exception as e:
            log.error(f"Error creating table '{self.table_name}': {e}")

    async def save_tool_record(self, tool_data: Dict[str, Any]) -> bool:
        """
        Inserts a new tool record into the tool table.

        Args:
            tool_data (Dict[str, Any]): A dictionary containing the tool data.
                                        Expected keys: tool_id, tool_name, tool_description,
                                        code_snippet, model_name, created_by, created_on, updated_on.

        Returns:
            bool: True if the tool was inserted successfully, False if a unique violation occurred or on other error.
        """
        insert_statement = f"""
        INSERT INTO {self.table_name} (tool_id, tool_name, tool_description, code_snippet, model_name, created_by, created_on, updated_on)
        VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
        """
        try:
            async with self.pool.acquire() as conn:
                await conn.execute(
                    insert_statement,
                    tool_data.get("tool_id"), tool_data.get("tool_name"),
                    tool_data.get("tool_description"), tool_data.get("code_snippet"),
                    tool_data.get("model_name"), tool_data.get("created_by"),
                    tool_data["created_on"], tool_data["updated_on"]
                )
            self.invalidate_entity("get_tool_record", tool_id=tool_data.get("tool_id"))
            self.invalidate_entity("get_tool_record", tool_name=tool_data.get("tool_name"))
            self.invalidate_entity("get_tool_record", tool_id=tool_data.get("tool_id"), tool_name=tool_data.get("tool_name"))
            self.invalidate_entity("get_all_tool_records")
            self.invalidate_all_method_cache("get_tools_by_search_or_page_records")
            log.info(f"Tool record {tool_data.get('tool_name')} inserted successfully.")
            return True
        except asyncpg.UniqueViolationError:
            log.warning(f"Tool record {tool_data.get('tool_name')} already exists (unique violation).")
            return False
        except Exception as e:
            log.error(f"Error saving tool record {tool_data.get('tool_name')}: {e}")
            return False

    @CacheableRepository.cache(ttl=EXPIRY_TIME, namespace="ToolRepository")
    async def get_tool_record(self, tool_id: Optional[str] = None, tool_name: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        Retrieves a single tool record by its ID or name.

        Args:
            tool_id (Optional[str]): The ID of the tool.
            tool_name (Optional[str]): The name of the tool.

        Returns:
            List[Dict[str, Any]]: A list of dictionary representing the tool record, or an empty list if not found.
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
            return []

        try:
            async with self.pool.acquire() as conn:
                rows = await conn.fetch(query, *params)
            if rows:
                log.info(f"Tool record '{tool_id or tool_name}' retrieved successfully.")
                return [dict(row) for row in rows]
            else:
                log.info(f"Tool record '{tool_id or tool_name}' not found.")
                return []
        except Exception as e:
            log.error(f"Error retrieving tool record '{tool_id or tool_name}': {e}")
            return []

    @CacheableRepository.cache(ttl=EXPIRY_TIME, namespace="ToolRepository")
    async def get_all_tool_records(self) -> List[Dict[str, Any]]:
        """
        Retrieves all tool records.

        Returns:
            List[Dict[str, Any]]: A list of dictionaries, each representing a tool record.
        """
        # query = f"SELECT * FROM {self.table_name} WHERE  (status = 'approved' OR created_by = '{current_user_email.get(None)}') ORDER BY created_on DESC"
        
        query = f"SELECT * FROM {self.table_name} ORDER BY created_on DESC"
        log.info(f"Executing query to retrieve all tool records: {query}")
        try:
            async with self.pool.acquire() as conn:
                rows = await conn.fetch(query)
            log.info(f"Retrieved {len(rows)} tool records from '{self.table_name}'.")
            return [dict(row) for row in rows]
        except Exception as e:
            log.error(f"Error retrieving all tool records: {e}")
            return []

    @CacheableRepository.cache(ttl=EXPIRY_TIME, namespace="ToolRepository")
    async def get_tools_by_search_or_page_records(self, search_value: str, limit: int, page: int) -> List[Dict[str, Any]]:
        """
        Retrieves tool records with pagination and search filtering.

        Args:
            search_value (str): The value to search for in tool names (case-insensitive, LIKE).
            limit (int): The maximum number of records to return.
            page (int): The page number (1-indexed).

        Returns:
            List[Dict[str, Any]]: A list of dictionaries, each representing a tool record.
        """
        name_filter = f"%{search_value.lower()}%" if search_value else "%"
        offset = limit * max(0, page - 1)
        # query = f"""
        #     SELECT * FROM {self.table_name}
        #     WHERE  (status = 'approved' OR created_by = '{current_user_email.get(None)}') AND LOWER(tool_name) LIKE $1
        #     ORDER BY created_on DESC
        #     LIMIT $2 OFFSET $3;
        # """
        query = f"""
            SELECT * FROM {self.table_name}
            WHERE LOWER(tool_name) LIKE $1
            ORDER BY created_on DESC
            LIMIT $2 OFFSET $3;
        """
        try:
            async with self.pool.acquire() as conn:
                rows = await conn.fetch(query, name_filter, limit, offset)
            log.info(f"Retrieved {len(rows)} tool records for search '{search_value}', page {page}.")
            return [dict(row) for row in rows]
        except Exception as e:
            log.error(f"Error retrieving tool records by search/page: {e}")
            return []

    async def get_total_tool_count(self, search_value: str = '') -> int:
        """
        Retrieves the total count of tool records, optionally filtered by name.

        Args:
            search_value (str): The value to search for in tool names (case-insensitive, LIKE).

        Returns:
            int: The total count of matching tool records.
        """
        name_filter = f"%{search_value.lower()}%" if search_value else "%"
        # query = f"SELECT COUNT(*) FROM {self.table_name} WHERE  (status = 'approved' OR created_by = '{current_user_email.get(None)}') AND LOWER(tool_name) LIKE $1"
        query = f"SELECT COUNT(*) FROM {self.table_name} WHERE LOWER(tool_name) LIKE $1"
        try:
            async with self.pool.acquire() as conn:
                count = await conn.fetchval(query, name_filter)
            log.info(f"Total tool count for search '{search_value}': {count}.")
            return count
        except Exception as e:
            log.error(f"Error getting total tool count: {e}")
            return 0

    async def update_tool_record(self, tool_data: Dict[str, Any], tool_id: str) -> bool:
        """
        Updates a tool record by its ID.

        Args:
            tool_data (Dict[str, Any]): A dictionary containing the fields to update and their new values.
                                        Must include 'updated_on' timestamp.
            tool_id (str): The ID of the tool record to update.

        Returns:
            bool: True if the record was updated successfully, False otherwise.
        """
        set_clauses = [f"{key} = ${i+2}" for i, key in enumerate(tool_data.keys())]
        values = list(tool_data.values())
        
        query = f"UPDATE {self.table_name} SET {', '.join(set_clauses)} WHERE tool_id = $1"
        
        try:
            async with self.pool.acquire() as conn:
                result = await conn.execute(query, tool_id, *values)
            if result != "UPDATE 0":
                self.invalidate_entity("get_tool_record", tool_id=tool_id)
                self.invalidate_entity("get_tool_record", tool_name=tool_data.get("tool_name"))
                self.invalidate_entity("get_tool_record", tool_id=tool_id, tool_name=tool_data.get("tool_name"))
                self.invalidate_entity("get_all_tool_records")
                self.invalidate_all_method_cache("get_tools_by_search_or_page_records")
                log.info(f"Tool record '{tool_id}' updated successfully.")
                return True
            else:
                log.warning(f"Tool record '{tool_id}' not found, no update performed.")
                return False
        except Exception as e:
            log.error(f"Error updating tool record '{tool_id}': {e}")
            return False

    async def delete_tool_record(self, tool_id: str) -> bool:
        """
        Deletes a tool record from the main tool table by its ID.

        Args:
            tool_id (str): The ID of the tool record to delete.

        Returns:
            bool: True if the record was deleted successfully, False otherwise.
        """
        delete_query = f"DELETE FROM {self.table_name} WHERE tool_id = $1"
        try:
            async with self.pool.acquire() as conn:
                result = await conn.execute(delete_query, tool_id)
            if result != "DELETE 0":
                self.invalidate_entity("get_tool_record", tool_id=tool_id)
                self.invalidate_entity("get_all_tool_records")
                self.invalidate_all_method_cache("get_tools_by_search_or_page_records")
                
                log.info(f"Tool record '{tool_id}' deleted successfully from '{self.table_name}'.")
                return True
            else:
                log.warning(f"Tool record '{tool_id}' not found in '{self.table_name}', no deletion performed.")
                return False
        except asyncpg.ForeignKeyViolationError as e:
            log.error(f"Cannot delete tool '{tool_id}' from '{self.table_name}' due to foreign key constraint: {e}")
            return False
        except Exception as e:
            log.error(f"Error deleting tool record '{tool_id}': {e}")
            return False

    async def get_all_tools_for_approval(self) -> List[Dict[str, Any]]:
        """
        Retrieves all tool records for admin approval purposes.
        No status filtering is applied - returns all tools regardless of status.

        Returns:
            List[Dict[str, Any]]: A list of dictionaries, each representing a tool record.
        """
        query = f"SELECT * FROM {self.table_name} ORDER BY created_on DESC"
        try:
            async with self.pool.acquire() as conn:
                rows = await conn.fetch(query)
            log.info(f"Retrieved {len(rows)} tool records for approval from '{self.table_name}'.")
            return [dict(row) for row in rows]
        except Exception as e:
            log.error(f"Error retrieving all tool records for approval: {e}")
            return []

    async def get_tools_by_search_or_page_records_for_approval(self, search_value: str, limit: int, page: int) -> List[Dict[str, Any]]:
        """
        Retrieves tool records with pagination and search filtering for admin approval purposes.
        No status filtering is applied - returns all tools regardless of status.

        Args:
            search_value (str): The value to search for in tool names (case-insensitive, LIKE).
            limit (int): The maximum number of records to return.
            page (int): The page number (1-indexed).

        Returns:
            List[Dict[str, Any]]: A list of dictionaries, each representing a tool record.
        """
        name_filter = f"%{search_value.lower()}%" if search_value else "%"
        offset = limit * max(0, page - 1)

        query = f"""
            SELECT * FROM {self.table_name}
            WHERE LOWER(tool_name) LIKE $1
            ORDER BY created_on DESC
            LIMIT $2 OFFSET $3
        """
        params = [name_filter, limit, offset]

        try:
            async with self.pool.acquire() as conn:
                rows = await conn.fetch(query, *params)
            log.info(f"Retrieved {len(rows)} tool records for approval with search '{search_value}', page {page}.")
            return [dict(row) for row in rows]
        except Exception as e:
            log.error(f"Error retrieving tool records for approval by search/page: {e}")
            return []

    async def approve_tool(self, tool_id: str, approved_by: str, comments: Optional[str] = None) -> bool:
        """
        Approves a tool by updating its status to 'approved', setting is_public to True,
        recording the approval timestamp and approver information.

        Args:
            tool_id (str): The ID of the tool to approve.
            approved_by (str): The email/identifier of the admin approving the tool.
            comments (Optional[str]): Optional comments about the approval.

        Returns:
            bool: True if the tool was approved successfully, False otherwise.
        """
        update_statement = f"""
        UPDATE {self.table_name} 
        SET status = 'approved', 
            is_public = TRUE, 
            approved_at = $1, 
            approved_by = $2, 
            comments = $3,
            updated_on = $5
        WHERE tool_id = $4
        """
        
        approval_time_utc = datetime.now(timezone.utc)
        approval_time_naive = approval_time_utc.replace(tzinfo=None)
        try:
            async with self.pool.acquire() as conn:
                result = await conn.execute(
                    update_statement, 
                    approval_time_utc, 
                    approved_by, 
                    comments, 
                    tool_id,
                    approval_time_naive
                )
            if result != "UPDATE 0":
                log.info(f"Tool '{tool_id}' approved successfully by '{approved_by}' at {approval_time_utc}.")
                return True
            else:
                log.warning(f"Tool '{tool_id}' not found, no approval performed.")
                return False
        except Exception as e:
            log.error(f"Error approving tool '{tool_id}': {e}")
            return False



# --- McpToolRepository ---

class McpToolRepository(BaseRepository):
    """
    Repository for the 'mcp_tool_table'. Handles direct database interactions for MCP server definitions.
    """

    def __init__(self, pool: asyncpg.Pool, table_name: str = "mcp_tool_table"):
        """
        Initializes the McpToolRepository.

        Args:
            pool (asyncpg.Pool): The asyncpg connection pool.
            table_name (str): The name of the MCP tools table.
        """
        super().__init__(pool, table_name)


    async def create_table_if_not_exists(self):
        """
        Creates the 'mcp_tool_table' in PostgreSQL if it does not exist.
        Includes new auth-related columns and the CHECK constraint directly.
        """
        try:
            create_statement = f"""
            CREATE TABLE IF NOT EXISTS {self.table_name} (
                tool_id TEXT PRIMARY KEY,
                tool_name TEXT UNIQUE NOT NULL,
                tool_description TEXT,
                mcp_config JSONB NOT NULL, -- Stores the entire MCP config dictionary for the server
                is_public BOOLEAN DEFAULT FALSE,
                status TEXT DEFAULT 'pending',
                comments TEXT,
                approved_at TIMESTAMPTZ,
                approved_by TEXT,
                created_by TEXT,
                created_on TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_on TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                CONSTRAINT {self.table_name}_status_check CHECK (status IN ('pending', 'approved', 'rejected'))
            );
            """
            async with self.pool.acquire() as conn:
                await conn.execute(create_statement)

            log.info(f"Table '{self.table_name}' created successfully or already exists.")
        except Exception as e:
            log.error(f"Error creating table '{self.table_name}': {e}")
            raise # Re-raise to ensure startup failure if table creation fails

    async def save_mcp_tool_record(self, tool_data: Dict[str, Any]) -> bool:
        """
        Inserts a new MCP tool (server definition) record into the mcp_tool_table.

        Args:
            tool_data (Dict[str, Any]): A dictionary containing the MCP tool data.
                                        Expected keys: tool_id, tool_name, tool_description,
                                        mcp_config (JSON dumped), is_public, status, comments,
                                        approved_at, approved_by, created_by, created_on, updated_on.

        Returns:
            bool: True if the tool was inserted successfully, False if a unique violation occurred or on other error.
        """
        insert_statement = f"""
        INSERT INTO {self.table_name} (
            tool_id, tool_name, tool_description, mcp_config,
            is_public, status, comments, approved_at, approved_by,
            created_by, created_on, updated_on
        ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12)
        """
        try:
            async with self.pool.acquire() as conn:
                await conn.execute(
                    insert_statement,
                    tool_data.get("tool_id"),
                    tool_data.get("tool_name"),
                    tool_data.get("tool_description"),
                    json.dumps(tool_data.get("mcp_config")), # Ensure JSONB is dumped
                    tool_data.get("is_public", False),
                    tool_data.get("status", "pending"),
                    tool_data.get("comments"),
                    tool_data.get("approved_at"),
                    tool_data.get("approved_by"),
                    tool_data.get("created_by"),
                    tool_data["created_on"],
                    tool_data["updated_on"]
                )
            log.info(f"MCP tool record '{tool_data.get('tool_name')}' inserted successfully.")
            return True
        except asyncpg.UniqueViolationError:
            log.warning(f"MCP tool record '{tool_data.get('tool_name')}' already exists (unique violation).")
            return False
        except Exception as e:
            log.error(f"Error saving MCP tool record '{tool_data.get('tool_name')}': {e}")
            return False

    async def get_mcp_tool_record(self, tool_id: Optional[str] = None, tool_name: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        Retrieves a single MCP tool (server definition) record by its ID or name.

        Args:
            tool_id (Optional[str]): The ID of the MCP tool.
            tool_name (Optional[str]): The name of the MCP tool.

        Returns:
            List[Dict[str, Any]]: A list of dictionaries representing the MCP tool record, or an empty list if not found.
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
            log.warning("No tool_id or tool_name provided to get_mcp_tool_record.")
            return []

        try:
            async with self.pool.acquire() as conn:
                rows = await conn.fetch(query, *params)
            if rows:
                log.info(f"MCP tool record '{tool_id or tool_name}' retrieved successfully.")
                # Ensure JSONB is loaded as Python object (asyncpg usually handles this)
                return [dict(row) for row in rows]
            else:
                log.info(f"MCP tool record '{tool_id or tool_name}' not found.")
                return []
        except Exception as e:
            log.error(f"Error retrieving MCP tool record '{tool_id or tool_name}': {e}")
            return []

    async def get_all_mcp_tool_records(self) -> List[Dict[str, Any]]:
        """
        Retrieves all MCP tool (server definition) records.

        Returns:
            List[Dict[str, Any]]: A list of dictionaries, each representing an MCP tool record.
        """
        query = f"SELECT * FROM {self.table_name} ORDER BY created_on DESC"
        try:
            async with self.pool.acquire() as conn:
                rows = await conn.fetch(query)
            log.info(f"Retrieved {len(rows)} MCP tool records from '{self.table_name}'.")
            # Ensure JSONB is loaded as Python object
            return [dict(row) for row in rows]
        except Exception as e:
            log.error(f"Error retrieving all MCP tool records: {e}")
            return []

    async def get_mcp_tools_by_search_or_page_records(self, search_value: str, limit: int, page: int, mcp_type: Optional[List[Literal["file", "url", "module"]]] = None) -> List[Dict[str, Any]]:
        """
        Retrieves MCP tool (server definition) records with pagination and search filtering.

        Args:
            search_value (str): The value to search for in tool names (case-insensitive, LIKE).
            limit (int): The maximum number of records to return.
            page (int): The page number (1-indexed).
            mcp_type (Optional[List[Literal["file", "url", "module"]]]): Optional list of MCP types to filter by.

        Returns:
            List[Dict[str, Any]]: A list of dictionaries, each representing an MCP tool record.
        """
        name_filter = f"%{search_value.lower()}%" if search_value else "%"
        offset = limit * max(0, page - 1)

        query = f"""
            SELECT * FROM {self.table_name}
            WHERE LOWER(tool_name) LIKE $1
        """
        params = [name_filter]
        param_idx = 2

        if mcp_type:
            # Construct a list of LIKE patterns for each mcp_type
            type_patterns = [f"mcp_{t}_%" for t in mcp_type]
            
            # Use an array parameter with LIKE ANY for multiple types
            # Example: AND tool_id LIKE ANY(ARRAY['mcp_file_%', 'mcp_url_%'])
            query += f" AND tool_id LIKE ANY(${param_idx}::text[])"
            params.append(type_patterns)
            param_idx += 1
        
        query += f" ORDER BY created_on DESC LIMIT ${param_idx} OFFSET ${param_idx + 1};"
        params.extend([limit, offset])

        try:
            async with self.pool.acquire() as conn:
                rows = await conn.fetch(query, *params)
            log.info(f"Retrieved {len(rows)} MCP tool records for search '{search_value}', page {page}, type '{mcp_type}'.")
            # Ensure JSONB is loaded as Python object
            return [dict(row) for row in rows]
        except Exception as e:
            log.error(f"Error retrieving MCP tool records by search/page: {e}")
            return []

    async def get_total_mcp_tool_count(self, search_value: str = '', mcp_type: Optional[List[Literal["file", "url", "module"]]] = None) -> int:
        """
        Retrieves the total count of MCP tool (server definition) records, optionally filtered by name and type.
        """
        name_filter = f"%{search_value.lower()}%" if search_value else "%"
        query = f"SELECT COUNT(*) FROM {self.table_name} WHERE LOWER(tool_name) LIKE $1"
        params = [name_filter]
        param_idx = 2

        if mcp_type:
            # Construct a list of LIKE patterns for each mcp_type
            type_patterns = [f"mcp_{t}_%" for t in mcp_type]
            
            # Use an array parameter with LIKE ANY for multiple types
            # Example: AND tool_id LIKE ANY(ARRAY['mcp_file_%', 'mcp_url_%'])
            query += f" AND tool_id LIKE ANY(${param_idx}::text[])"
            params.append(type_patterns)
            param_idx += 1

        try:
            async with self.pool.acquire() as conn:
                count = await conn.fetchval(query, *params)
            log.info(f"Total MCP tool count for search '{search_value}', types '{mcp_type}': {count}.")
            return count
        except Exception as e:
            log.error(f"Error getting total MCP tool count: {e}")
            return 0

    async def update_mcp_tool_record(self, tool_data: Dict[str, Any], tool_id: str) -> bool:
        """
        Updates an MCP tool (server definition) record by its ID.

        Args:
            tool_data (Dict[str, Any]): A dictionary containing the fields to update and their new values.
                                        Must include 'updated_on' timestamp.
                                        'mcp_config' should be a Python dict, will be JSON dumped.
            tool_id (str): The ID of the MCP tool record to update.

        Returns:
            bool: True if the record was updated successfully, False otherwise.
        """
        # Prepare data for update, ensuring mcp_config is dumped if present
        update_fields = []
        values = []
        param_idx = 1

        for key, value in tool_data.items():
            if key == "mcp_config":
                update_fields.append(f"mcp_config = ${param_idx}")
                values.append(json.dumps(value))
            else:
                update_fields.append(f"{key} = ${param_idx}")
                values.append(value)
            param_idx += 1
        
        query = f"UPDATE {self.table_name} SET {', '.join(update_fields)} WHERE tool_id = ${param_idx}"
        
        try:
            async with self.pool.acquire() as conn:
                result = await conn.execute(query, *values, tool_id)
            if result != "UPDATE 0":
                log.info(f"MCP tool record '{tool_id}' updated successfully.")
                return True
            else:
                log.warning(f"MCP tool record '{tool_id}' not found, no update performed.")
                return False
        except Exception as e:
            log.error(f"Error updating MCP tool record '{tool_id}': {e}")
            return False

    async def delete_mcp_tool_record(self, tool_id: str) -> bool:
        """
        Deletes an MCP tool (server definition) record from the mcp_tool_table by its ID.

        Args:
            tool_id (str): The ID of the MCP tool record to delete.

        Returns:
            bool: True if the record was deleted successfully, False otherwise.
        """
        delete_query = f"DELETE FROM {self.table_name} WHERE tool_id = $1"
        try:
            async with self.pool.acquire() as conn:
                result = await conn.execute(delete_query, tool_id)
            if result != "DELETE 0":
                log.info(f"MCP tool record '{tool_id}' deleted successfully from '{self.table_name}'.")
                return True
            else:
                log.warning(f"MCP tool record '{tool_id}' not found in '{self.table_name}', no deletion performed.")
                return False
        except asyncpg.ForeignKeyViolationError as e:
            log.error(f"Cannot delete MCP tool '{tool_id}' from '{self.table_name}' due to foreign key constraint: {e}")
            return False
        except Exception as e:
            log.error(f"Error deleting MCP tool record '{tool_id}': {e}")
            return False

    # --- MIGRATION METHOD ---
    async def migrate_file_mcp_tools_config(self) -> Dict[str, Any]:
        """
        Migrates existing 'mcp_file_' type tools from an old file-based config
        to the new inline code execution format (using 'python -c "code_content"').
        This method should be called once during application startup.
        """
        log.info("Starting migration of 'mcp_file_' tools config to inline code execution.")
        migrated_count = 0
        failed_migrations = []

        all_mcp_tools = await self.get_all_mcp_tool_records() # Use service's get_all to ensure JSONB deserialization
        for tool_data in all_mcp_tools:
            if tool_data["tool_id"].startswith("mcp_file_"):
                if isinstance(tool_data.get("mcp_config"), str):
                    tool_data["mcp_config"] = json.loads(tool_data["mcp_config"])
                mcp_config = tool_data["mcp_config"]

                # Check if it's an old-style file-based config and if it still contains the 'code_content' key
                if "code_content" in mcp_config:
                    code_content = mcp_config.pop("code_content", None)

                    try:
                        # Update mcp_config to the new inline code format
                        mcp_config["args"] = ["-c", code_content] # New inline execution

                        update_payload = {"mcp_config": mcp_config}
                        success = await self.update_mcp_tool_record(update_payload, tool_data["tool_id"])

                        if success:
                            migrated_count += 1
                            log.info(f"Migrated MCP file tool config {tool_data['tool_name']} ({tool_data['tool_id']}) to inline code.")
                        else:
                            failed_migrations.append({"tool_id": tool_data["tool_id"], "reason": "DB update failed"})
                            log.error(f"Failed to update DB record for migration of {tool_data['tool_name']} ({tool_data['tool_id']}).")

                    except Exception as e:
                        failed_migrations.append({"tool_id": tool_data["tool_id"], "reason": str(e)})
                        log.error(f"Error during migration of {tool_data['tool_name']} ({tool_data['tool_id']}): {e}")
                else:
                    log.debug(f"MCP file tool {tool_data['tool_name']} ({tool_data['tool_id']}) already in inline format or not file-based.")

        log.info(f"Migration of 'mcp_file_' tools config completed. Migrated: {migrated_count}, Failed: {len(failed_migrations)}.")
        return {"status": "completed", "migrated_count": migrated_count, "failed_migrations": failed_migrations}


# --- ToolAgentMappingRepository ---

class ToolAgentMappingRepository(BaseRepository, CacheableRepository):
    """
    Repository for the 'tool_agent_mapping_table'. Handles direct database interactions for tool-agent mappings.
    """

    def __init__(self, pool: asyncpg.Pool, table_name: str = "tool_agent_mapping_table"):
        """
        Initializes the ToolAgentMappingRepository.

        Args:
            pool (asyncpg.Pool): The asyncpg connection pool.
            table_name (str): The name of the tool-agent mapping table.
        """
        super().__init__(pool, table_name)


    async def create_table_if_not_exists(self):
        """
        Creates the 'tool_agent_mapping_table' if it does not exist.
        NOTE: The FOREIGN KEY to tool_table is intentionally removed here
              to allow mapping of agent IDs (worker agents) as 'tool_id'.
        """
        try:
            create_statement = f"""
            CREATE TABLE IF NOT EXISTS {self.table_name} (
                tool_id TEXT,
                agentic_application_id TEXT,
                tool_created_by TEXT,
                agentic_app_created_by TEXT,
                -- FOREIGN KEY(tool_id) REFERENCES tool_table(tool_id) ON DELETE RESTRICT, -- REMOVED
                FOREIGN KEY(agentic_application_id) REFERENCES agent_table(agentic_application_id) ON DELETE CASCADE
            );
            """
            async with self.pool.acquire() as conn:
                await conn.execute(create_statement)
            log.info(f"Table '{self.table_name}' created successfully or already exists.")
        except Exception as e:
            log.error(f"Error creating table '{self.table_name}': {e}")

    async def assign_tool_to_agent_record(self, tool_id: str, agentic_application_id: str, tool_created_by: str, agentic_app_created_by: str) -> bool:
        """
        Inserts a mapping between a tool/worker_agent and an agent.

        Args:
            tool_id (str): The ID of the tool or worker agent.
            agentic_application_id (str): The ID of the agentic application.
            tool_created_by (str): The creator of the tool/worker agent.
            agentic_app_created_by (str): The creator of the agentic application.

        Returns:
            bool: True if the mapping was inserted successfully, False otherwise.
        """
        insert_statement = f"""
        INSERT INTO {self.table_name} (tool_id, agentic_application_id, tool_created_by, agentic_app_created_by)
        VALUES ($1, $2, $3, $4)
        """
        try:
            async with self.pool.acquire() as conn:
                await conn.execute(insert_statement, tool_id, agentic_application_id, tool_created_by, agentic_app_created_by)
            self.invalidate_entity("get_tool_agent_mappings_record", tool_id=tool_id, agentic_application_id=agentic_application_id)
            self.invalidate_entity("get_tool_agent_mappings_record", tool_id=tool_id)
            self.invalidate_entity("get_tool_agent_mappings_record", agentic_application_id=agentic_application_id)
            log.info(f"Mapping tool/agent '{tool_id}' to agent '{agentic_application_id}' inserted successfully.")
            return True
        except Exception as e:
            log.error(f"Error assigning tool/agent '{tool_id}' to agent '{agentic_application_id}': {e}")
            return False

    @CacheableRepository.cache(ttl=EXPIRY_TIME, namespace="ToolAgentMappingRepository")
    async def get_tool_agent_mappings_record(self, tool_id: Optional[str] = None, agentic_application_id: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        Retrieves raw tool-agent mappings by tool_id or agentic_application_id.

        Args:
            tool_id (Optional[str]): The ID of the tool or worker agent to filter by.
            agentic_application_id (Optional[str]): The ID of the agentic application to filter by.

        Returns:
            List[Dict[str, Any]]: A list of dictionaries, each representing a tool-agent mapping.
        """
        select_statement = f"SELECT * FROM {self.table_name}"
        where_clause = []
        values = []

        filters = {"tool_id": tool_id, "agentic_application_id": agentic_application_id}
        for idx, (field, value) in enumerate((f for f in filters.items() if f[1] is not None), start=1):
            where_clause.append(f"{field} = ${idx}")
            values.append(value)

        if where_clause:
            select_statement += " WHERE " + " AND ".join(where_clause)

        try:
            async with self.pool.acquire() as conn:
                rows = await conn.fetch(select_statement, *values)
            log.info(f"Retrieved {len(rows)} tool-agent mappings from '{self.table_name}'.")
            return [dict(row) for row in rows]
        except Exception as e:
            log.error(f"Error retrieving tool-agent mappings: {e}")
            return []

    async def remove_tool_from_agent_record(self, tool_id: Optional[str] = None, agentic_application_id: Optional[str] = None) -> bool:
        """
        Removes a mapping between a tool/worker_agent and an agent.

        Args:
            tool_id (Optional[str]): The ID of the tool or worker agent to remove.
            agentic_application_id (Optional[str]): The ID of the agentic application to remove the mapping from.

        Returns:
            bool: True if the mapping was removed successfully, False otherwise.
        """
        delete_statement = f"DELETE FROM {self.table_name}"
        where_clause = []
        values = []

        filters = {"tool_id": tool_id, "agentic_application_id": agentic_application_id}
        for idx, (field, value) in enumerate((f for f in filters.items() if f[1] is not None), start=1):
            where_clause.append(f"{field} = ${idx}")
            values.append(value)

        if where_clause:
            delete_statement += " WHERE " + " AND ".join(where_clause)
            try:
                async with self.pool.acquire() as conn:
                    result = await conn.execute(delete_statement, *values)
                if result != "DELETE 0":
                    self.invalidate_entity("get_tool_agent_mappings_record", tool_id=tool_id, agentic_application_id=agentic_application_id)
                    self.invalidate_entity("get_tool_agent_mappings_record", tool_id=tool_id)
                    self.invalidate_entity("get_tool_agent_mappings_record", agentic_application_id=agentic_application_id)
                    log.info(f"Mapping tool/agent '{tool_id}' from agent '{agentic_application_id}' removed successfully.")
                    return True
                else:
                    log.warning(f"Mapping tool/agent '{tool_id}' from agent '{agentic_application_id}' not found, no deletion performed.")
                    return False
            except Exception as e:
                log.error(f"Error removing tool/agent mapping: {e}")
                return False
        log.warning("No criteria provided to remove_tool_from_agent_record, no action taken.")
        return False

    async def drop_tool_id_fk_constraint(self):
        """
        Dynamically finds and drops the foreign key constraint on tool_agent_mapping_table.tool_id.
        This is crucial for allowing agent IDs (worker agents) to be stored in the 'tool_id' column.
        """
        try:
            async with self.pool.acquire() as conn:
                constraint_query = f"""
                SELECT tc.constraint_name
                FROM information_schema.table_constraints AS tc
                JOIN information_schema.key_column_usage AS kcu
                  ON tc.constraint_name = kcu.constraint_name
                WHERE tc.table_schema = current_schema()
                  AND tc.table_name = '{self.table_name}'
                  AND kcu.column_name = 'tool_id'
                  AND tc.constraint_type = 'FOREIGN KEY';
                """
                constraint_record = await conn.fetchrow(constraint_query)

                if constraint_record:
                    constraint_name = constraint_record['constraint_name']
                    drop_fk_statement = f"""
                    ALTER TABLE {self.table_name}
                    DROP CONSTRAINT {constraint_name};
                    """
                    await conn.execute(drop_fk_statement)
                    self.invalidate_all_method_cache("get_tool_agent_mappings_record")
                    log.info(f"Successfully dropped foreign key constraint '{constraint_name}' on '{self.table_name}.tool_id'.")
                    return True
                else:
                    log.info(f"No foreign key constraint found on '{self.table_name}.tool_id' to drop. (This is expected if already removed).")
                    return False

        except Exception as e:
            log.error(f"Error attempting to drop foreign key constraint on '{self.table_name}.tool_id': {e}")
            return False



# --- RecycleToolRepository ---
# --- CACHE NOT IMPLEMENTED FOR THIS CLASS ---
class RecycleToolRepository(BaseRepository):
    """
    Repository for the 'recycle_tool' table. Handles direct database interactions for recycled tools.
    """

    def __init__(self, pool: asyncpg.Pool, table_name: str = "recycle_tool"):
        """
        Initializes the RecycleToolRepository.

        Args:
            pool (asyncpg.Pool): The asyncpg connection pool.
            table_name (str): The name of the recycle tools table.
        """
        super().__init__(pool, table_name)


    async def create_table_if_not_exists(self):
        """
        Creates the 'recycle_tool' table if it doesn't already exist.
        """
        try:
            create_table_sql = f"""
            CREATE TABLE IF NOT EXISTS {self.table_name} (
                tool_id TEXT PRIMARY KEY,
                tool_name TEXT UNIQUE,
                tool_description TEXT,
                code_snippet TEXT,
                model_name TEXT,
                created_by TEXT,
                created_on TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_on TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                is_public BOOLEAN DEFAULT FALSE,
                status TEXT DEFAULT 'pending',
                comments TEXT,
                approved_at TIMESTAMPTZ,
                approved_by TEXT,
                CHECK (status IN ('pending', 'approved', 'rejected'))
            );
            """
            async with self.pool.acquire() as conn:
                await conn.execute(create_table_sql)
                alter_statements = [
                    f"ALTER TABLE {self.table_name} ADD COLUMN IF NOT EXISTS is_public BOOLEAN DEFAULT FALSE",
                    f"ALTER TABLE {self.table_name} ADD COLUMN IF NOT EXISTS status TEXT DEFAULT 'pending'",
                    f"ALTER TABLE {self.table_name} ADD COLUMN IF NOT EXISTS comments TEXT",
                    f"ALTER TABLE {self.table_name} ADD COLUMN IF NOT EXISTS approved_at TIMESTAMPTZ",
                    f"ALTER TABLE {self.table_name} ADD COLUMN IF NOT EXISTS approved_by TEXT",
                    f"DO $$ BEGIN "
                    f"IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = '{self.table_name}_status_check') THEN "
                    f"ALTER TABLE {self.table_name} ADD CONSTRAINT {self.table_name}_status_check CHECK (status IN ('pending', 'approved', 'rejected')); "
                    f"END IF; END $$;"
                ]

                for stmt in alter_statements:
                    await conn.execute(stmt)
            log.info(f"Table '{self.table_name}' created successfully or already exists.")
        except Exception as e:
            log.error(f"Error creating table '{self.table_name}': {e}")

    async def is_tool_in_recycle_bin_record(self, tool_id: Optional[str] = None, tool_name: Optional[str] = None) -> bool:
        """
        Checks if a tool exists in the recycle bin table by ID or name.

        Args:
            tool_id (Optional[str]): The ID of the tool.
            tool_name (Optional[str]): The name of the tool.

        Returns:
            bool: True if the tool exists, False otherwise.
        """
        query = f"SELECT EXISTS(SELECT 1 FROM {self.table_name} WHERE tool_id = $1 OR tool_name = $2)"
        try:
            async with self.pool.acquire() as conn:
                exists = await conn.fetchval(query, tool_id, tool_name)
            log.info(f"Checked if tool '{tool_id or tool_name}' exists in recycle bin: {exists}.")
            return exists
        except Exception as e:
            log.error(f"Error checking tool '{tool_id or tool_name}' in recycle bin: {e}")
            return False

    async def insert_recycle_tool_record(self, tool_data: Dict[str, Any]) -> bool:
        """
        Inserts a tool record into the recycle bin.

        Args:
            tool_data (Dict[str, Any]): A dictionary containing the tool data to insert.

        Returns:
            bool: True if the record was inserted successfully, False otherwise.
        """
        insert_query = f"""
        INSERT INTO {self.table_name} (tool_id, tool_name, tool_description, code_snippet, model_name, created_by, created_on, updated_on)
        VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
        ON CONFLICT (tool_id) DO NOTHING;
        """
        try:
            async with self.pool.acquire() as conn:
                await conn.execute(
                    insert_query,
                    tool_data.get("tool_id"), tool_data.get("tool_name"), tool_data.get("tool_description"),
                    tool_data.get("code_snippet"), tool_data.get("model_name"), tool_data.get("created_by"),
                    tool_data["created_on"], tool_data["updated_on"]
                )
            log.info(f"Tool record {tool_data.get('tool_name')} inserted into recycle bin successfully.")
            return True
        except Exception as e:
            log.error(f"Error inserting recycle tool record {tool_data.get('tool_name')}: {e}")
            return False

    async def delete_recycle_tool_record(self, tool_id: str) -> bool:
        """
        Deletes a tool record from the recycle bin by its ID.

        Args:
            tool_id (str): The ID of the tool record to delete.

        Returns:
            bool: True if the record was deleted successfully, False otherwise.
        """
        delete_query = f"DELETE FROM {self.table_name} WHERE tool_id = $1"
        try:
            async with self.pool.acquire() as conn:
                result = await conn.execute(delete_query, tool_id)
            if result != "DELETE 0":
                log.info(f"Tool record '{tool_id}' deleted successfully from recycle bin.")
                return True
            else:
                log.warning(f"Tool record '{tool_id}' not found in recycle bin, no deletion performed.")
                return False
        except Exception as e:
            log.error(f"Error deleting recycle tool record '{tool_id}': {e}")
            return False

    async def get_all_recycle_tool_records(self) -> List[Dict[str, Any]]:
        """
        Retrieves all tool records from the recycle bin.

        Returns:
            List[Dict[str, Any]]: A list of dictionaries, each representing a recycled tool record.
        """
        query = f"SELECT * FROM {self.table_name} ORDER BY created_on DESC"
        try:
            async with self.pool.acquire() as conn:
                rows = await conn.fetch(query)
            log.info(f"Retrieved {len(rows)} recycle tool records from '{self.table_name}'.")
            return [dict(row) for row in rows]
        except Exception as e:
            log.error(f"Error retrieving all recycle tool records: {e}")
            return []

    async def get_recycle_tool_record(self, tool_id: Optional[str] = None, tool_name: Optional[str] = None) -> Dict[str, Any] | None:
        """
        Retrieves a single tool record from the recycle bin by ID or name.

        Args:
            tool_id (Optional[str]): The ID of the tool.
            tool_name (Optional[str]): The name of the tool.

        Returns:
            Dict[str, Any] | None: A dictionary representing the recycled tool record, or None if not found.
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
            log.warning("No tool_id or tool_name provided to get_recycle_tool_record.")
            return None

        try:
            async with self.pool.acquire() as conn:
                row = await conn.fetchrow(query, *params)
            if row:
                log.info(f"Recycle tool record '{tool_id or tool_name}' retrieved successfully.")
                return dict(row)
            else:
                log.info(f"Recycle tool record '{tool_id or tool_name}' not found.")
                return None
        except Exception as e:
            log.error(f"Error retrieving recycle tool record '{tool_id or tool_name}': {e}")
            return None



# --- Agent Repository ---

class AgentRepository(BaseRepository, CacheableRepository):
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
        Creates the 'agent_table' in PostgreSQL if it does not exist.
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
                created_by TEXT,
                created_on TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
                updated_on TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
                is_public BOOLEAN DEFAULT FALSE,
                status TEXT DEFAULT 'pending',
                comments TEXT,
                approved_at TIMESTAMPTZ,
                approved_by TEXT,
                CHECK (status IN ('pending', 'approved', 'rejected'))
            );
            """
            async with self.pool.acquire() as conn:
                await conn.execute(create_statement)
                alter_statements = [
                    f"ALTER TABLE {self.table_name} ADD COLUMN IF NOT EXISTS is_public BOOLEAN DEFAULT FALSE",
                    f"ALTER TABLE {self.table_name} ADD COLUMN IF NOT EXISTS status TEXT DEFAULT 'pending'",
                    f"ALTER TABLE {self.table_name} ADD COLUMN IF NOT EXISTS comments TEXT",
                    f"ALTER TABLE {self.table_name} ADD COLUMN IF NOT EXISTS approved_at TIMESTAMPTZ",
                    f"ALTER TABLE {self.table_name} ADD COLUMN IF NOT EXISTS approved_by TEXT",
                    f"DO $$ BEGIN "
                    f"IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = '{self.table_name}_status_check') THEN "
                    f"ALTER TABLE {self.table_name} ADD CONSTRAINT {self.table_name}_status_check CHECK (status IN ('pending', 'approved', 'rejected')); "
                    f"END IF; END $$;"
                ]

                for stmt in alter_statements:
                    await conn.execute(stmt)
            log.info(f"Table '{self.table_name}' created successfully or already exists.")
        except Exception as e:
            log.error(f"Error creating table '{self.table_name}': {e}")

    async def save_agent_record(self, agent_data: Dict[str, Any]) -> bool:
        """
        Inserts a new agent record into the agent table.

        Args:
            agent_data (Dict[str, Any]): A dictionary containing the agent data.
                                        Expected keys: agentic_application_id, agentic_application_name,
                                        agentic_application_description, agentic_application_workflow_description,
                                        agentic_application_type, model_name, system_prompt (JSON dumped),
                                        tools_id (JSON dumped), created_by, created_on, updated_on.

        Returns:
            bool: True if the agent was inserted successfully, False if a unique violation occurred or on other error.
        """
        insert_statement = f"""
        INSERT INTO {self.table_name} (agentic_application_id, agentic_application_name, agentic_application_description, agentic_application_workflow_description, agentic_application_type, model_name, system_prompt, tools_id, created_by, created_on, updated_on)
        VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11)
        """
        try:
            async with self.pool.acquire() as conn:
                await conn.execute(
                    insert_statement,
                    agent_data["agentic_application_id"],
                    agent_data["agentic_application_name"],
                    agent_data["agentic_application_description"],
                    agent_data["agentic_application_workflow_description"],
                    agent_data["agentic_application_type"],
                    agent_data["model_name"],
                    agent_data["system_prompt"],
                    agent_data["tools_id"],
                    agent_data["created_by"],
                    agent_data["created_on"],
                    agent_data["updated_on"]
                )
            self.invalidate_entity("get_agent_record", agentic_application_id=agent_data.get("agentic_application_id"))
            self.invalidate_all_method_cache("get_agents_by_search_or_page_records")
            self.invalidate_entity("get_agents_details_for_chat_records")
            self.invalidate_entity("get_all_agent_records", agentic_application_type=agent_data.get("agentic_application_type"))
            self.invalidate_all_method_cache("get_all_agent_records")
            log.info(f"Agent record {agent_data.get('agentic_application_name')} inserted successfully.")
            return True
        except asyncpg.UniqueViolationError:
            log.warning(f"Agent record {agent_data.get('agentic_application_name')} already exists (unique violation).")
            return False
        except Exception as e:
            log.error(f"Error saving agent record {agent_data.get('agentic_application_name')}: {e}")
            return False

    @CacheableRepository.cache(ttl=EXPIRY_TIME, namespace="AgentRepository")
    async def get_agent_record(self, agentic_application_id: Optional[str] = None, agentic_application_name: Optional[str] = None, agentic_application_type: Optional[str] = None, created_by: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        Retrieves a single agent record by ID, name, type, or creator.

        Args:
            agentic_application_id (Optional[str]): The ID of the agent.
            agentic_application_name (Optional[str]): The name of the agent.
            agentic_application_type (Optional[str]): The type of the agent.
            created_by (Optional[str]): The creator's email ID.

        Returns:
            List[Dict[str, Any]]: A list of dictionary representing the agent records, or an empty list if not found.
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
            return []

        try:
            async with self.pool.acquire() as conn:
                rows = await conn.fetch(query, *params)

            results_as_dicts = [dict(row) for row in rows]

            log.info(f"Retrieved {len(results_as_dicts)} agent records from '{self.table_name}'.")
            return results_as_dicts

        except Exception as e:
            log.error(f"Error retrieving agent record '{agentic_application_id or agentic_application_name}': {e}")
            return []

    @CacheableRepository.cache(ttl=EXPIRY_TIME, namespace="AgentRepository")
    async def get_all_agent_records(self, agentic_application_type: Optional[Union[str, List[str]]] = None) -> List[Dict[str, Any]]:
        """
        Retrieves all agent records, optionally filtered by type.

        Args:
            agentic_application_type (Optional[Union[str, List[str]]]): The type(s) of agent to filter by.

        Returns:
            List[Dict[str, Any]]: A list of dictionaries, each representing an agent record.
        """
        # query = f"SELECT * FROM {self.table_name} WHERE  (status = 'approved' OR created_by = '{current_user_email.get(None)}')"
        query = f"SELECT * FROM {self.table_name}"
        parameters = []
        if agentic_application_type:
            if isinstance(agentic_application_type, str):
                agentic_application_type = [agentic_application_type]
            placeholders = ', '.join(f"${i+1}" for i in range(len(agentic_application_type)))
            # query += f" AND agentic_application_type IN ({placeholders})"
            query += f" WHERE agentic_application_type IN ({placeholders})"
            parameters.extend(agentic_application_type)
        query += " ORDER BY created_on DESC"

        try:
            async with self.pool.acquire() as conn:
                rows = await conn.fetch(query, *parameters)
            log.info(f"Retrieved {len(rows)} agent records from '{self.table_name}'.")
            return [dict(row) for row in rows]
        except Exception as e:
            log.error(f"Error retrieving all agent records: {e}")
            return []

    @CacheableRepository.cache(ttl=EXPIRY_TIME, namespace="AgentRepository")
    async def get_agents_by_search_or_page_records(self, search_value: str, limit: int, page: int, agentic_application_type: Optional[Union[str, List[str]]] = None, created_by: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        Retrieves agent records with pagination and search filtering.

        Args:
            search_value (str): The value to search for in agent names (case-insensitive, LIKE).
            limit (int): The maximum number of records to return.
            page (int): The page number (1-indexed).
            agentic_application_type (Optional[Union[str, List[str]]]): The type(s) of agent to filter by.
            created_by (Optional[str]): The creator's email ID to filter by.

        Returns:
            List[Dict[str, Any]]: A list of dictionaries, each representing an agent record.
        """
        name_filter = f"%{search_value.lower()}%" if search_value else "%"
        offset = limit * max(0, page - 1)

        query = f"""
            SELECT * FROM {self.table_name}
            WHERE LOWER(agentic_application_name) LIKE $1
        """
        params = [name_filter]
        idx = 2
        if agentic_application_type:
            if isinstance(agentic_application_type, str):
                agentic_application_type = [agentic_application_type]
            placeholders = ', '.join(f"${i+idx}" for i in range(len(agentic_application_type)))
            query += f" AND agentic_application_type IN ({placeholders})"
            params.extend(agentic_application_type)
            idx += len(agentic_application_type)
        if created_by:
            query += f" AND created_by = ${idx}"
            params.append(created_by)
            idx += 1
        
        # query += f" AND (status = 'approved' OR created_by = '{current_user_email.get(None)}') ORDER BY created_on DESC LIMIT ${idx} OFFSET ${idx + 1}"
        query += f" ORDER BY created_on DESC LIMIT ${idx} OFFSET ${idx + 1}"
        params.extend([limit, offset])

        try:
            async with self.pool.acquire() as conn:
                rows = await conn.fetch(query, *params)
            log.info(f"Retrieved {len(rows)} agent records for search '{search_value}', page {page}.")
            return [dict(row) for row in rows]
        except Exception as e:
            log.error(f"Error retrieving agent records by search/page: {e}")
            return []

    async def get_total_agent_count(self, search_value: str = '', agentic_application_type: Optional[Union[str, List[str]]] = None, created_by: Optional[str] = None) -> int:
        """
        Retrieves the total count of agent records, optionally filtered.

        Args:
            search_value (str): The value to search for in agent names (case-insensitive, LIKE).
            agentic_application_type (Optional[Union[str, List[str]]]): The type(s) of agent to filter by.
            created_by (Optional[str]): The creator's email ID to filter by.

        Returns:
            int: The total count of matching agent records.
        """
        name_filter = f"%{search_value.lower()}%" if search_value else "%"
        # query = f"SELECT COUNT(*) FROM {self.table_name} WHERE (status = 'approved' OR created_by = '{current_user_email.get(None)}') AND LOWER(agentic_application_name) LIKE $1"
        query = f"SELECT COUNT(*) FROM {self.table_name} WHERE LOWER(agentic_application_name) LIKE $1"
        params = [name_filter]
        idx = 2
        if agentic_application_type:
            if isinstance(agentic_application_type, str):
                agentic_application_type = [agentic_application_type]
            placeholders = ', '.join(f"${i+idx}" for i in range(len(agentic_application_type)))
            query += f" AND agentic_application_type IN ({placeholders})"
            params.extend(agentic_application_type)
            idx += len(agentic_application_type)
        if created_by:
            query += f" AND created_by = ${idx}"
            params.append(created_by)

        try:
            async with self.pool.acquire() as conn:
                count = await conn.fetchval(query, *params)
            log.info(f"Total agent count for search '{search_value}': {count}.")
            return count
        except Exception as e:
            log.error(f"Error getting total agent count: {e}")
            return 0

    async def update_agent_record(self, agent_data: Dict[str, Any], agentic_application_id: str) -> bool:
        """
        Updates an agent record by its ID.

        Args:
            agent_data (Dict[str, Any]): A dictionary containing the fields to update and their new values.
                                        Must include 'updated_on' timestamp.
            agentic_application_id (str): The ID of the agent record to update.

        Returns:
            bool: True if the record was updated successfully, False otherwise.
        """
        set_clauses = [f"{column} = ${idx + 1}" for idx, column in enumerate(agent_data.keys())]
        values = list(agent_data.values())
        query = f"UPDATE {self.table_name} SET {', '.join(set_clauses)} WHERE agentic_application_id = ${len(values) + 1}"
        
        try:
            async with self.pool.acquire() as conn:
                result = await conn.execute(query, *values, agentic_application_id)
            if result != "UPDATE 0":
                self.invalidate_entity("get_agent_record", agentic_application_id=agentic_application_id)
                self.invalidate_all_method_cache("get_agents_by_search_or_page_records")
                self.invalidate_entity("get_agents_details_for_chat_records")
                self.invalidate_entity("get_all_agent_records", agentic_application_type=agent_data.get("agentic_application_type"))
                self.invalidate_all_method_cache("get_all_agent_records")
                log.info(f"Agent record '{agentic_application_id}' updated successfully.")
                return True
            else:
                log.warning(f"Agent record '{agentic_application_id}' not found, no update performed.")
                return False
        except Exception as e:
            log.error(f"Error updating agent record '{agentic_application_id}': {e}")
            return False

    async def delete_agent_record(self, agentic_application_id: str) -> bool:
        """
        Deletes an agent record from the main agent table by its ID.

        Args:
            agentic_application_id (str): The ID of the agent record to delete.

        Returns:
            bool: True if the record was deleted successfully, False otherwise.
        """
        delete_query = f"DELETE FROM {self.table_name} WHERE agentic_application_id = $1"
        try:
            async with self.pool.acquire() as conn:
                result = await conn.execute(delete_query, agentic_application_id)
            if result != "DELETE 0":
                self.invalidate_entity("get_agent_record", agentic_application_id=agentic_application_id)
                self.invalidate_all_method_cache("get_agents_by_search_or_page_records")
                self.invalidate_entity("get_agents_details_for_chat_records")
                # self.invalidate_entity("get_all_agent_records", agentic_application_type=agent_data.get("agentic_application_type"))
                self.invalidate_all_method_cache("get_all_agent_records")
                log.info(f"Agent record '{agentic_application_id}' deleted successfully from '{self.table_name}'.")
                return True
            else:
                log.warning(f"Agent record '{agentic_application_id}' not found in '{self.table_name}', no deletion performed.")
                return False
        except asyncpg.ForeignKeyViolationError as e:
            log.error(f"Cannot delete agent '{agentic_application_id}' from '{self.table_name}' due to foreign key constraint: {e}")
            return False
        except Exception as e:
            log.error(f"Error deleting agent record '{agentic_application_id}': {e}")
            return False

    @CacheableRepository.cache(ttl=EXPIRY_TIME, namespace="AgentRepository")
    async def get_agents_details_for_chat_records(self) -> List[Dict[str, Any]]:
        """
        Retrieves basic agent details (ID, name, type) for chat purposes.

        Returns:
            List[Dict[str, Any]]: A list of dictionaries, each containing
                                  'agentic_application_id', 'agentic_application_name',
                                  and 'agentic_application_type'.
        """
        # query = f"""
        #     SELECT agentic_application_id, agentic_application_name, agentic_application_type
        #     FROM {self.table_name}
        #     WHERE (status = 'approved' OR created_by = '{current_user_email.get(None)}')
        #     ORDER BY created_on DESC
        # """
        query = f"""
            SELECT agentic_application_id, agentic_application_name, agentic_application_type
            FROM {self.table_name}
            ORDER BY created_on DESC
        """
        try:
            async with self.pool.acquire() as conn:
                rows = await conn.fetch(query)
            log.info(f"Retrieved {len(rows)} agent chat detail records from '{self.table_name}'.")
            return [dict(row) for row in rows]
        except Exception as e:
            log.error(f"Error retrieving agent chat detail records: {e}")
            return []

    async def get_all_agents_for_approval(self) -> List[Dict[str, Any]]:
        """
        Retrieves all agent records for admin approval purposes.
        No status filtering is applied - returns all agents regardless of status.

        Returns:
            List[Dict[str, Any]]: A list of dictionaries, each representing an agent record.
        """
        query = f"SELECT * FROM {self.table_name} ORDER BY created_on DESC"
        try:
            async with self.pool.acquire() as conn:
                rows = await conn.fetch(query)
            log.info(f"Retrieved {len(rows)} agent records for approval from '{self.table_name}'.")
            return [dict(row) for row in rows]
        except Exception as e:
            log.error(f"Error retrieving all agent records for approval: {e}")
            return []

    async def get_agents_by_search_or_page_records_for_approval(self, search_value: str, limit: int, page: int) -> List[Dict[str, Any]]:
        """
        Retrieves agent records with pagination and search filtering for admin approval purposes.
        No status filtering is applied - returns all agents regardless of status.

        Args:
            search_value (str): The value to search for in agent names (case-insensitive, LIKE).
            limit (int): The maximum number of records to return.
            page (int): The page number (1-indexed).

        Returns:
            List[Dict[str, Any]]: A list of dictionaries, each representing an agent record.
        """
        name_filter = f"%{search_value.lower()}%" if search_value else "%"
        offset = limit * max(0, page - 1)

        query = f"""
            SELECT * FROM {self.table_name}
            WHERE LOWER(agentic_application_name) LIKE $1
            ORDER BY created_on DESC
            LIMIT $2 OFFSET $3
        """
        params = [name_filter, limit, offset]

        try:
            async with self.pool.acquire() as conn:
                rows = await conn.fetch(query, *params)
            log.info(f"Retrieved {len(rows)} agent records for approval with search '{search_value}', page {page}.")
            return [dict(row) for row in rows]
        except Exception as e:
            log.error(f"Error retrieving agent records for approval by search/page: {e}")
            return []

    async def approve_agent(self, agentic_application_id: str, approved_by: str, comments: Optional[str] = None) -> bool:
        """
        Approves an agent by updating its status to 'approved', setting is_public to True,
        recording the approval timestamp and approver information.

        Args:
            agentic_application_id (str): The ID of the agent to approve.
            approved_by (str): The email/identifier of the admin approving the agent.
            comments (Optional[str]): Optional comments about the approval.

        Returns:
            bool: True if the agent was approved successfully, False otherwise.
        """
        update_statement = f"""
        UPDATE {self.table_name} 
        SET status = 'approved', 
            is_public = TRUE, 
            approved_at = $1, 
            approved_by = $2, 
            comments = $3,
            updated_on = $1
        WHERE agentic_application_id = $4
        """
        
        approval_time = datetime.now()
        
        try:
            async with self.pool.acquire() as conn:
                result = await conn.execute(
                    update_statement, 
                    approval_time, 
                    approved_by, 
                    comments, 
                    agentic_application_id
                )
            if result != "UPDATE 0":
                log.info(f"Agent '{agentic_application_id}' approved successfully by '{approved_by}' at {approval_time}.")
                return True
            else:
                log.warning(f"Agent '{agentic_application_id}' not found, no approval performed.")
                return False
        except Exception as e:
            log.error(f"Error approving agent '{agentic_application_id}': {e}")
            return False



# --- RecycleAgentRepository ---
# --- CACHE NOT IMPLEMENTED FOR THIS CLASS ---
class RecycleAgentRepository(BaseRepository):
    """
    Repository for the 'recycle_agent' table. Handles direct database interactions for recycled agents.
    """

    def __init__(self, pool: asyncpg.Pool, table_name: str = "recycle_agent"):
        """
        Initializes the RecycleAgentRepository.

        Args:
            pool (asyncpg.Pool): The asyncpg connection pool.
            table_name (str): The name of the recycle agents table.
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
                created_by TEXT,
                created_on TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
                updated_on TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
            );
            """
            async with self.pool.acquire() as conn:
                await conn.execute(create_statement)
            log.info(f"Table '{self.table_name}' created successfully or already exists.")
        except Exception as e:
            log.error(f"Error creating table '{self.table_name}': {e}")

    async def is_agent_in_recycle_bin_record(self, agentic_application_id: Optional[str] = None, agentic_application_name: Optional[str] = None) -> bool:
        """
        Checks if an agent exists in the recycle bin table by ID or name.

        Args:
            agentic_application_id (Optional[str]): The ID of the agent.
            agentic_application_name (Optional[str]): The name of the agent.

        Returns:
            bool: True if the agent exists, False otherwise.
        """
        query = f"SELECT EXISTS(SELECT 1 FROM {self.table_name} WHERE agentic_application_id = $1 OR agentic_application_name = $2)"
        try:
            async with self.pool.acquire() as conn:
                exists = await conn.fetchval(query, agentic_application_id, agentic_application_name)
            log.info(f"Checked if agent '{agentic_application_id or agentic_application_name}' exists in recycle bin: {exists}.")
            return exists
        except Exception as e:
            log.error(f"Error checking agent '{agentic_application_id or agentic_application_name}' in recycle bin: {e}")
            return False

    async def insert_recycle_agent_record(self, agent_data: Dict[str, Any]) -> bool:
        """
        Inserts an agent record into the recycle bin.

        Args:
            agent_data (Dict[str, Any]): A dictionary containing the agent data to insert.

        Returns:
            bool: True if the record was inserted successfully, False otherwise.
        """
        insert_query = f"""
        INSERT INTO {self.table_name} (agentic_application_id, agentic_application_name, agentic_application_description, agentic_application_workflow_description, agentic_application_type, model_name, system_prompt, tools_id, created_by, created_on, updated_on)
        VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11)
        ON CONFLICT (agentic_application_id) DO NOTHING;
        """
        try:
            async with self.pool.acquire() as conn:
                await conn.execute(
                    insert_query,
                    agent_data["agentic_application_id"], agent_data["agentic_application_name"],
                    agent_data["agentic_application_description"], agent_data["agentic_application_workflow_description"],
                    agent_data["agentic_application_type"], agent_data["model_name"],
                    agent_data["system_prompt"], agent_data["tools_id"],
                    agent_data["created_by"], agent_data["created_on"], agent_data["updated_on"]
                )
            log.info(f"Agent record {agent_data.get('agentic_application_name')} inserted into recycle bin successfully.")
            return True
        except Exception as e:
            log.error(f"Error inserting recycle agent record {agent_data.get('agentic_application_name')}: {e}")
            return False

    async def delete_recycle_agent_record(self, agentic_application_id: str) -> bool:
        """
        Deletes an agent record from the recycle bin by its ID.

        Args:
            agentic_application_id (str): The ID of the agent record to delete.

        Returns:
            bool: True if the record was deleted successfully, False otherwise.
        """
        delete_query = f"DELETE FROM {self.table_name} WHERE agentic_application_id = $1"
        try:
            async with self.pool.acquire() as conn:
                result = await conn.execute(delete_query, agentic_application_id)
            if result != "DELETE 0":
                log.info(f"Agent record '{agentic_application_id}' deleted successfully from recycle bin.")
                return True
            else:
                log.warning(f"Agent record '{agentic_application_id}' not found in recycle bin, no deletion performed.")
                return False
        except Exception as e:
            log.error(f"Error deleting recycle agent record '{agentic_application_id}': {e}")
            return False

    async def get_all_recycle_agent_records(self) -> List[Dict[str, Any]]:
        """
        Retrieves all agent records from the recycle bin.

        Returns:
            List[Dict[str, Any]]: A list of dictionaries, each representing a recycled agent record.
        """
        query = f"SELECT * FROM {self.table_name} ORDER BY created_on DESC"
        try:
            async with self.pool.acquire() as conn:
                rows = await conn.fetch(query)
            log.info(f"Retrieved {len(rows)} recycle agent records from '{self.table_name}'.")
            return [dict(row) for row in rows]
        except Exception as e:
            log.error(f"Error retrieving all recycle agent records: {e}")
            return []

    async def get_recycle_agent_record(self, agentic_application_id: Optional[str] = None, agentic_application_name: Optional[str] = None) -> Dict[str, Any] | None:
        """
        Retrieves a single agent record from the recycle bin by ID or name.

        Args:
            agentic_application_id (Optional[str]): The ID of the agent.
            agentic_application_name (Optional[str]): The name of the agent.

        Returns:
            Dict[str, Any] | None: A dictionary representing the recycled agent record, or None if not found.
        """
        query = f"SELECT * FROM {self.table_name} WHERE "
        params = []
        if agentic_application_id:
            query += "agentic_application_id = $1"
            params.append(agentic_application_id)
        elif agentic_application_name:
            query += "agentic_application_name = $1"
            params.append(agentic_application_name)
        else:
            log.warning("No agentic_application_id or agentic_application_name provided to get_recycle_agent_record.")
            return None

        try:
            async with self.pool.acquire() as conn:
                row = await conn.fetchrow(query, *params)
            if row:
                log.info(f"Recycle agent record '{agentic_application_id or agentic_application_name}' retrieved successfully.")
                return dict(row)
            else:
                log.info(f"Recycle agent record '{agentic_application_id or agentic_application_name}' not found.")
                return None
        except Exception as e:
            log.error(f"Error retrieving recycle agent record '{agentic_application_id or agentic_application_name}': {e}")
            return None
        


# --- ChatHistoryRepository ---
# --- CACHE NOT IMPLEMENTED FOR THIS CLASS ---
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
            UNIQUE(agentic_application_id, session_id)
        );
        """
        try:
            async with self.pool.acquire() as conn:
                await conn.execute(create_statement)
            log.info(f"Table '{table_name}' created successfully or already exists.")
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
        INSERT INTO {table_name} (agentic_application_id, session_id, preference)
        VALUES ($1, $2, $3)
        ON CONFLICT (agentic_application_id, session_id)
        DO UPDATE SET preference = $3
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
        SET summary = $1, created_on = CURRENT_TIMESTAMP
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

    async def get_checkpointer_context_manager(self):
        """
        Returns an asynchronous context manager for LangGraph's PostgresSaver.
        This allows inference services to use 'async with chat_history_repository.get_checkpointer_context_manager() as checkpointer:'
        """
        if not self.DB_URL:
            raise ValueError("POSTGRESQL_DATABASE_URL (for checkpointer) is not configured in environment variables.")

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
            
        """
        def get_unique_messages(messages, similarity_threshold=0.5):
            """
            Filters a list of messages to return only those that are not too similar to each other.
            The `similarity_threshold` is a float from 0 to 1.
            """
            if not messages:
                return []

            unique_messages = []
            # Loop through each message in the original list
            for new_message in messages:
                is_similar = False
                # Compare the new message to all the messages we've already deemed unique
                for existing_message in unique_messages:
                    # Use SequenceMatcher to get a similarity ratio (e.g., 0.95)
                    similarity = difflib.SequenceMatcher(None, new_message.lower(), existing_message.lower()).ratio()
                    if similarity >= similarity_threshold:
                        is_similar = True
                        break  # Found a similar message, no need to check further
                
                # If no similar message was found, add it to our unique list
                if not is_similar:
                    unique_messages.append(new_message)
                    
            return unique_messages

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

                queries = {
                    "user_history": [row['human_message'] for row in user_history],
                    "agent_history": [row['human_message'] for row in agent_history],
                }
                all_message = queries["user_history"] + queries["agent_history"]
                query_library = get_unique_messages(all_message)
                queries["query_library"] = query_library

                return queries
        except Exception as e:
            log.error(f"Error fetching user queries from '{chat_table_name}': {e}")
            return {}

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


# --- FeedbackLearningRepository ---
# --- CACHE NOT IMPLEMENTED FOR THIS CLASS ---
class FeedbackLearningRepository(BaseRepository):
    """
    Repository for feedback data. Handles direct database interactions for
    'feedback_response' and 'agent_feedback' tables.
    """

    def __init__(self, pool: asyncpg.Pool,
                 feedback_table_name: str = "feedback_response",
                 agent_feedback_table_name: str = "agent_feedback"):
        super().__init__(pool, table_name=feedback_table_name)
        self.feedback_table_name = feedback_table_name
        self.agent_feedback_table_name = agent_feedback_table_name


    async def create_tables_if_not_exists(self):
        """
        Creates the 'feedback_response' and 'agent_feedback' tables if they don't exist.
        If feedback_response table exists, alters it to add the 'lesson' field if missing.
        """
        create_feedback_table_query = f"""
        CREATE TABLE IF NOT EXISTS {self.feedback_table_name} (
            response_id TEXT PRIMARY KEY,
            query TEXT,
            old_final_response TEXT,
            old_steps TEXT,
            old_response TEXT,
            feedback TEXT,
            new_final_response TEXT,
            new_steps TEXT,
            new_response TEXT,
            lesson TEXT,
            approved BOOLEAN DEFAULT FALSE,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        """
        create_agent_feedback_table_query = f"""
        CREATE TABLE IF NOT EXISTS {self.agent_feedback_table_name} (
            agent_id TEXT,
            response_id TEXT,
            PRIMARY KEY (agent_id, response_id),
            FOREIGN KEY (response_id) REFERENCES {self.feedback_table_name}(response_id) ON DELETE CASCADE
        );
        """
        
        check_column_exists_query = f"""
        SELECT EXISTS (
            SELECT 1
            FROM information_schema.columns
            WHERE table_name = '{self.feedback_table_name}'
            AND column_name = 'lesson'
        );
        """
        
        alter_table_query = f"""
        ALTER TABLE {self.feedback_table_name}
        ADD COLUMN IF NOT EXISTS lesson TEXT;
        """
        
        try:
            async with self.pool.acquire() as conn:
                # First create tables if they don't exist
                await conn.execute(create_feedback_table_query)
                await conn.execute(create_agent_feedback_table_query)
                
                # Check if the feedback_table exists and if it's missing the lesson column
                table_exists = await conn.fetchval(
                    f"SELECT EXISTS(SELECT 1 FROM information_schema.tables WHERE table_name = '{self.feedback_table_name}')"
                )
                
                if table_exists:
                    # If table exists, check if lesson column exists and add it if missing
                    await conn.execute(alter_table_query)
                    log.info(f"Added 'lesson' column to {self.feedback_table_name} table if it was missing.")
                    
            log.info("Feedback storage tables created successfully or already exist.")
        except Exception as e:
            log.error(f"Error creating feedback storage tables: {e}")
            raise # Re-raise for service to handle

    async def insert_feedback_record(self, response_id: str, query: str, old_final_response: str, old_steps: str, feedback: str, new_final_response: str, new_steps: str, lesson: str, approved: bool = False) -> bool:
        """
        Inserts a new feedback response record.
        """
        insert_query = f"""
        INSERT INTO {self.feedback_table_name} (
            response_id, query, old_final_response, old_steps, feedback, new_final_response, new_steps, approved, lesson
        ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9);
        """
        try:
            async with self.pool.acquire() as conn:
                await conn.execute(insert_query, response_id, query, old_final_response, old_steps, feedback, new_final_response, new_steps, approved, lesson)
            return True
        except Exception as e:
            log.error(f"Error inserting feedback record for response_id '{response_id}': {e}")
            return False

    async def insert_agent_feedback_mapping(self, agent_id: str, response_id: str) -> bool:
        """
        Inserts a mapping between an agent and a feedback response.
        """
        insert_query = f"""
        INSERT INTO {self.agent_feedback_table_name} (agent_id, response_id)
        VALUES ($1, $2);
        """
        try:
            async with self.pool.acquire() as conn:
                await conn.execute(insert_query, agent_id, response_id)
            return True
        except Exception as e:
            log.error(f"Error inserting agent feedback mapping for agent_id '{agent_id}', response_id '{response_id}': {e}")
            return False

    async def get_approved_feedback_records(self, agent_id: str) -> List[Dict[str, Any]]:
        """
        Retrieves approved feedback records for a specific agent.
        """
        select_query = f"""
        SELECT fr.response_id, fr.query, fr.old_final_response, fr.old_steps, fr.feedback, fr.new_final_response, fr.new_steps, fr.lesson, fr.approved, fr.created_at FROM {self.feedback_table_name} fr
        JOIN {self.agent_feedback_table_name} af ON fr.response_id = af.response_id
        WHERE af.agent_id = $1 AND fr.approved = TRUE;
        """
        try:
            async with self.pool.acquire() as conn:
                rows = await conn.fetch(select_query, agent_id)
            return [dict(row) for row in rows]
        except Exception as e:
            log.error(f"Error retrieving approved feedback records for agent '{agent_id}': {e}")
            return []

    async def get_all_feedback_records_by_agent(self, agent_id: str) -> List[Dict[str, Any]]:
        """
        Retrieves all feedback records (regardless of approval status) for a given agent.
        """
        select_query = f"""
        SELECT af.response_id, fr.feedback, fr.approved
        FROM {self.feedback_table_name} fr
        JOIN {self.agent_feedback_table_name} af ON fr.response_id = af.response_id
        WHERE af.agent_id = $1;
        """
        try:
            async with self.pool.acquire() as conn:
                rows = await conn.fetch(select_query, agent_id)
            return [dict(row) for row in rows]
        except Exception as e:
            log.error(f"Error retrieving all feedback records for agent '{agent_id}': {e}")
            return []

    async def get_feedback_record_by_response_id(self, response_id: str) -> List[Dict[str, Any]]:
        """
        Retrieves a single feedback record by its response_id.
        """
        select_query = f"""
        SELECT fr.response_id, fr.query, fr.old_final_response, fr.old_steps, fr.feedback, fr.new_final_response, fr.new_steps, fr.lesson, fr.approved, fr.created_at, af.agent_id FROM {self.feedback_table_name} fr
        JOIN {self.agent_feedback_table_name} af ON fr.response_id = af.response_id
        WHERE fr.response_id = $1;
        """
        try:
            async with self.pool.acquire() as conn:
                rows = await conn.fetch(select_query, response_id)
            return [dict(row) for row in rows]
        except Exception as e:
            log.error(f"Error retrieving feedback record for response_id '{response_id}': {e}")
            return []

    async def get_distinct_agents_with_feedback(self) -> List[str]:
        """
        Retrieves a list of distinct agent_ids that have associated feedback.
        """
        select_query = f"SELECT DISTINCT agent_id FROM {self.agent_feedback_table_name};"
        try:
            async with self.pool.acquire() as conn:
                rows = await conn.fetch(select_query)
            return [row['agent_id'] for row in rows]
        except Exception as e:
            log.error(f"Error retrieving distinct agents with feedback: {e}")
            return []

    async def update_feedback_record(self, response_id: str, update_data: Dict[str, Any]) -> bool:
        """
        Updates fields in a feedback_response record.
        `update_data` should be a dictionary of column_name: new_value.
        """
        if not update_data:
            return False

        set_clause = ', '.join([f"{key} = ${i+1}" for i, key in enumerate(update_data.keys())])
        values = list(update_data.values())
        values.append(response_id) # response_id is the last parameter

        update_query = f"""
        UPDATE {self.feedback_table_name}
        SET {set_clause}
        WHERE response_id = ${len(values)};
        """
        try:
            async with self.pool.acquire() as conn:
                result = await conn.execute(update_query, *values)
            return result != "UPDATE 0"
        except Exception as e:
            log.error(f"Error updating feedback record for response_id '{response_id}': {e}")
            return False
        
    async def migrate_agent_ids_to_hyphens(self) -> Dict[str, Any]:
        """
        Migrates agent_id values in the agent_feedback table, replacing all underscores (_) with hyphens (-).
        This is useful for consistency if agent IDs are stored with hyphens elsewhere.

        Returns:
            Dict[str, Any]: A dictionary indicating the status of the migration.
        """
        log.info(f"Starting migration of agent_id underscores to hyphens in '{self.agent_feedback_table_name}'.")
        
        # The REPLACE function will replace ALL occurrences of '_' with '-'
        # The WHERE clause ensures we only attempt to update rows that actually contain an underscore.
        update_query = f"""
        UPDATE {self.agent_feedback_table_name}
        SET agent_id = REPLACE(agent_id, '_', '-')
        WHERE agent_id LIKE '%\\_%' ESCAPE '\\';
        """

        try:
            async with self.pool.acquire() as conn:
                # Execute the update query
                result = await conn.execute(update_query)
                
                # The result string will be like "UPDATE N" where N is the number of rows updated
                rows_updated = int(result.split()[-1])
                
                log.info(f"Migration complete for '{self.agent_feedback_table_name}'. {rows_updated} rows updated.")
                return {"status": "success", "message": f"Successfully migrated {rows_updated} agent_id records."}
        except Exception as e:
            log.error(f"Error during agent_id migration in '{self.agent_feedback_table_name}': {e}", exc_info=True)
            return {"status": "error", "message": f"Failed to migrate agent_id records: {e}"}



# --- EvaluationDataRepository ---
# --- CACHE NOT IMPLEMENTED FOR THIS CLASS ---
class EvaluationDataRepository(BaseRepository):
    """
    Repository for 'evaluation_data' table. Handles direct database interactions.
    """

    def __init__(self, pool: asyncpg.Pool, table_name: str = "evaluation_data"):
        super().__init__(pool, table_name)


    async def create_table_if_not_exists(self):
        """Creates the 'evaluation_data' table if it does not exist."""
        create_table_query = f"""
        CREATE TABLE IF NOT EXISTS {self.table_name} (
            id SERIAL PRIMARY KEY,
            time_stamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            session_id TEXT,
            query TEXT,
            response TEXT,
            model_used TEXT,
            agent_id TEXT,
            agent_name TEXT,
            agent_type TEXT,
            agent_goal TEXT,
            workflow_description TEXT,
            tool_prompt TEXT,
            steps JSONB,
            executor_messages JSONB,
            evaluation_status TEXT DEFAULT 'unprocessed'
        );
        """
        try:
            async with self.pool.acquire() as conn:
                await conn.execute(create_table_query)
            log.info(f"Table '{self.table_name}' created successfully or already exists.")
        except Exception as e:
            log.error(f"Error creating table '{self.table_name}': {e}")
            raise

    async def insert_evaluation_record(self, data: Dict[str, Any]) -> bool:
        """
        Inserts a new evaluation data record.
        """
        insert_query = f"""
        INSERT INTO {self.table_name} (
            session_id, query, response, model_used,
            agent_id, agent_name, agent_type, agent_goal,
            workflow_description, tool_prompt, steps, executor_messages
        ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12);
        """
        try:
            async with self.pool.acquire() as conn:
                await conn.execute(
                    insert_query,
                    data.get("session_id"), data.get("query"), data.get("response"), data.get("model_used"),
                    data.get("agent_id"), data.get("agent_name"), data.get("agent_type"), data.get("agent_goal"),
                    data.get("workflow_description"), data.get("tool_prompt"),
                    data.get("steps"),
                    data.get("executor_messages")
                )
            return True
        except Exception as e:
            log.error(f"Error inserting evaluation record: {e}")
            return False

    async def get_unprocessed_record(self) -> Dict[str, Any] | None:
        """
        Retrieves the next unprocessed evaluation record.
        """
        query = f"""
            SELECT
                id, query, response, agent_goal, agent_name,
                workflow_description, steps, executor_messages, tool_prompt, model_used,
                session_id, agent_id
            FROM {self.table_name}
            WHERE evaluation_status = 'unprocessed'
            ORDER BY time_stamp
            LIMIT 1;
        """
        try:
            async with self.pool.acquire() as conn:
                row = await conn.fetchrow(query)
            return dict(row) if row else None
        except Exception as e:
            log.error(f"Error fetching unprocessed evaluation record: {e}")
            return None

    async def update_status(self, evaluation_id: int, status: str) -> bool:
        """
        Updates the processing status of an evaluation record.
        """
        update_query = f"""
        UPDATE {self.table_name}
        SET evaluation_status = $1
        WHERE id = $2;
        """
        try:
            async with self.pool.acquire() as conn:
                result = await conn.execute(update_query, status, evaluation_id)
            return result != "UPDATE 0"
        except Exception as e:
            log.error(f"Error updating evaluation status for ID {evaluation_id}: {e}")
            return False

    async def get_records_by_agent_names(self, agent_names: Optional[List[str]] = None, page: int = 1, limit: int = 10) -> List[Dict[str, Any]]:
        """
        Retrieves evaluation data records, optionally filtered by agent names, with pagination.
        """
        offset = (page - 1) * limit
        query = f"""
            SELECT session_id, query, response, model_used, agent_id, agent_name, agent_type
            FROM {self.table_name}
        """
        params = []
        if agent_names:
            query += " WHERE agent_name = ANY($1::text[])"
            params.append(agent_names)
        
        query += f" ORDER BY id DESC LIMIT ${len(params) + 1} OFFSET ${len(params) + 2};"
        params.extend([limit, offset])

        try:
            async with self.pool.acquire() as conn:
                rows = await conn.fetch(query, *params)
            return [dict(row) for row in rows]
        except Exception as e:
            log.error(f"Error fetching evaluation data records: {e}")
            return []



# --- ToolEvaluationMetricsRepository ---
# --- CACHE NOT IMPLEMENTED FOR THIS CLASS ---
class ToolEvaluationMetricsRepository(BaseRepository):
    """
    Repository for 'tool_evaluation_metrics' table. Handles direct database interactions.
    """

    def __init__(self, pool: asyncpg.Pool, table_name: str = "tool_evaluation_metrics"):
        super().__init__(pool, table_name)


    async def create_table_if_not_exists(self):
        """Creates the 'tool_evaluation_metrics' table if it does not exist."""
        create_table_query = f"""
        CREATE TABLE IF NOT EXISTS {self.table_name} (
            id SERIAL PRIMARY KEY,
            evaluation_id INTEGER REFERENCES evaluation_data(id) ON DELETE CASCADE,
            user_query TEXT,
            agent_response TEXT,
            model_used TEXT,
            tool_selection_accuracy REAL,
            tool_usage_efficiency REAL,
            tool_call_precision REAL,
            tool_call_success_rate REAL,
            tool_utilization_efficiency REAL,
            tool_utilization_efficiency_category TEXT,
            tool_selection_accuracy_justification TEXT,
            tool_usage_efficiency_justification TEXT,
            tool_call_precision_justification TEXT,
            model_used_for_evaluation TEXT,
            time_stamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        """
        try:
            async with self.pool.acquire() as conn:
                await conn.execute(create_table_query)
            log.info(f"Table '{self.table_name}' created successfully or already exists.")
        except Exception as e:
            log.error(f"Error creating table '{self.table_name}': {e}")
            raise

    async def insert_metrics_record(self, metrics_data: Dict[str, Any]) -> bool:
        """
        Inserts a new tool evaluation metrics record.
        """
        insert_query = f"""
        INSERT INTO {self.table_name} (
            evaluation_id, user_query, agent_response, model_used,
            tool_selection_accuracy, tool_usage_efficiency, tool_call_precision,
            tool_call_success_rate, tool_utilization_efficiency,
            tool_utilization_efficiency_category,
            tool_selection_accuracy_justification,
            tool_usage_efficiency_justification,
            tool_call_precision_justification,
            model_used_for_evaluation
        ) VALUES (
            $1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14
        );
        """
        try:
            async with self.pool.acquire() as conn:
                await conn.execute(
                    insert_query,
                    metrics_data.get("evaluation_id"), metrics_data.get("user_query"), metrics_data.get("agent_response"), metrics_data.get("model_used"),
                    metrics_data.get("tool_selection_accuracy"), metrics_data.get("tool_usage_efficiency"), metrics_data.get("tool_call_precision"),
                    metrics_data.get("tool_call_success_rate"), metrics_data.get("tool_utilization_efficiency"),
                    metrics_data.get("tool_utilization_efficiency_category"),
                    metrics_data.get("tool_selection_accuracy_justification"),
                    metrics_data.get("tool_usage_efficiency_justification"),
                    metrics_data.get("tool_call_precision_justification"),
                    metrics_data.get("model_used_for_evaluation")
                )
            return True
        except Exception as e:
            log.error(f"Error inserting tool evaluation metrics record: {e}")
            return False

    async def get_metrics_by_agent_names(self, agent_names: Optional[List[str]] = None, page: int = 1, limit: int = 10) -> List[Dict[str, Any]]:
        """
        Retrieves tool evaluation metrics records, optionally filtered by agent names, with pagination.
        """
        offset = (page - 1) * limit
        query = f"""
            SELECT tem.*
            FROM {self.table_name} tem
            JOIN evaluation_data ed ON tem.evaluation_id = ed.id
        """
        params = []
        if agent_names:
            query += " WHERE ed.agent_name = ANY($1::text[])"
            params.append(agent_names)
        
        query += f" ORDER BY tem.id DESC LIMIT ${len(params) + 1} OFFSET ${len(params) + 2};"
        params.extend([limit, offset])

        try:
            async with self.pool.acquire() as conn:
                rows = await conn.fetch(query, *params)
            return [dict(row) for row in rows]
        except Exception as e:
            log.error(f"Error fetching tool evaluation metrics records: {e}")
            return []



# --- AgentEvaluationMetricsRepository ---
# --- CACHE NOT IMPLEMENTED FOR THIS CLASS ---
class AgentEvaluationMetricsRepository(BaseRepository):
    """
    Repository for 'agent_evaluation_metrics' table. Handles direct database interactions.
    """

    def __init__(self, pool: asyncpg.Pool, table_name: str = "agent_evaluation_metrics"):
        super().__init__(pool, table_name)


    async def create_table_if_not_exists(self):
        """Creates the 'agent_evaluation_metrics' table if it does not exist."""
        create_table_query = f"""
        CREATE TABLE IF NOT EXISTS {self.table_name} (
            id SERIAL PRIMARY KEY,
            evaluation_id INTEGER REFERENCES evaluation_data(id) ON DELETE CASCADE,
            user_query TEXT,
            response TEXT,
            model_used TEXT,
            task_decomposition_efficiency REAL,
            task_decomposition_justification TEXT,
            reasoning_relevancy REAL,
            reasoning_relevancy_justification TEXT,
            reasoning_coherence REAL,
            reasoning_coherence_justification TEXT,
            answer_relevance REAL,
            answer_relevance_justification TEXT,
            groundedness REAL,
            groundedness_justification TEXT,
            response_fluency REAL,
            response_fluency_justification TEXT,
            response_coherence REAL,
            response_coherence_justification TEXT,
            efficiency_category TEXT,
            model_used_for_evaluation TEXT,
            time_stamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        """
        try:
            async with self.pool.acquire() as conn:
                await conn.execute(create_table_query)
            log.info(f"Table '{self.table_name}' created successfully or already exists.")
        except Exception as e:
            log.error(f"Error creating table '{self.table_name}': {e}")
            raise

    async def insert_metrics_record(self, metrics_data: Dict[str, Any]) -> bool:
        """
        Inserts a new agent evaluation metrics record into the database.
        """
        insert_query = f"""
        INSERT INTO {self.table_name} (
            evaluation_id, user_query, response, model_used,
            task_decomposition_efficiency, task_decomposition_justification,
            reasoning_relevancy, reasoning_relevancy_justification,
            reasoning_coherence, reasoning_coherence_justification,
            answer_relevance, answer_relevance_justification,
            groundedness, groundedness_justification,
            response_fluency, response_fluency_justification,
            response_coherence, response_coherence_justification,
            efficiency_category, model_used_for_evaluation
        ) VALUES (
            $1, $2, $3, $4, $5, $6, $7, $8, $9, $10,
            $11, $12, $13, $14, $15, $16, $17, $18,
            $19, $20
        );
        """
        try:
            async with self.pool.acquire() as conn:
                await conn.execute(
                    insert_query,
                    metrics_data.get("evaluation_id"), metrics_data.get("user_query"), metrics_data.get("response"), metrics_data.get("model_used"),
                    metrics_data.get("task_decomposition_efficiency"), metrics_data.get("task_decomposition_justification"),
                    metrics_data.get("reasoning_relevancy"), metrics_data.get("reasoning_relevancy_justification"),
                    metrics_data.get("reasoning_coherence"), metrics_data.get("reasoning_coherence_justification"),
                    metrics_data.get("answer_relevance"), metrics_data.get("answer_relevance_justification"),
                    metrics_data.get("groundedness"), metrics_data.get("groundedness_justification"),
                    metrics_data.get("response_fluency"), metrics_data.get("response_fluency_justification"),
                    metrics_data.get("response_coherence"), metrics_data.get("response_coherence_justification"),
                    metrics_data.get("efficiency_category"), metrics_data.get("model_used_for_evaluation")
                )
            return True
        except Exception as e:
            log.error(f"Error inserting agent evaluation metrics record: {e}", exc_info=True)
            return False

    async def get_metrics_by_agent_names(self, agent_names: Optional[List[str]] = None, page: int = 1, limit: int = 10) -> List[Dict[str, Any]]:
        """
        Retrieves agent evaluation metrics records, optionally filtered by agent names, with pagination.
        """
        offset = (page - 1) * limit
        query = f"""
            SELECT aem.*
            FROM {self.table_name} aem
            JOIN evaluation_data ed ON aem.evaluation_id = ed.id
        """
        params = []
        if agent_names:
            query += " WHERE ed.agent_name = ANY($1::text[])"
            params.append(agent_names)
        
        query += f" ORDER BY aem.id DESC LIMIT ${len(params) + 1} OFFSET ${len(params) + 2};"
        params.extend([limit, offset])

        try:
            async with self.pool.acquire() as conn:
                rows = await conn.fetch(query, *params)
            return [dict(row) for row in rows]
        except Exception as e:
            log.error(f"Error fetching agent evaluation metrics records: {e}")
            return []



# --- Export Agent Repository ---

class ExportAgentRepository(BaseRepository):

    def __init__(self, pool: asyncpg.Pool, table_name: str = "export_agent"):
        super().__init__(pool, table_name)


    async def create_table_if_not_exists(self):
        """
        Creates the 'export_agent_logs' table if it does not exist.
        """
        create_table_query = f"""
        CREATE TABLE IF NOT EXISTS {self.table_name} (
            export_id TEXT PRIMARY KEY,
            agent_id TEXT NOT NULL,
            agent_name TEXT NOT NULL,
            user_name TEXT NOT NULL,
            user_email TEXT NOT NULL,
            export_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        """
        try:
            async with self.pool.acquire() as conn:
                await conn.execute(create_table_query)
            log.info(f"Table '{self.table_name}' created successfully or already exists.")
        except Exception as e:
            log.error(f"Error creating table '{self.table_name}': {e}")
            raise

    async def insert_export_log_record(self, export_id, agent_id: str, agent_name: str, user_name: str, user_email: str, export_time: datetime) -> bool:
        """
        Inserts a new export log record into the 'export_agent' table.
       
        Args:
            agent_id (str): The ID of the agent being exported.
            agent_name (str): The name of the agent being exported.
            user_name (str): The name of the user who initiated the export.
            user_email (str): The email of the user who initiated the export.
            export_time (datetime): The timestamp of the export operation.
 
        Returns:
            bool: True if the insert was successful, False otherwise.
        """
        insert_query = f"""
        INSERT INTO {self.table_name} (export_id, agent_id, agent_name, user_name, user_email, export_time)
        VALUES ($1, $2, $3, $4, $5, $6);
        """
        try:
            async with self.pool.acquire() as conn:
                await conn.execute(insert_query, export_id, agent_id, agent_name, user_name, user_email, export_time)
            return True
        except Exception as e:
            log.error(f"Error inserting export log for agent '{agent_id}': {e}")
            return False
        
    async def get_unique_exporters_record_by_agent_id(self, agent_id: str) -> List[str]:
        """
        Retrieves a list of unique user emails who have exported a specific agent.

        Args:
            agent_id (str): The ID of the agent to query.

        Returns:
            List[str]: A list of unique user emails.
        """
        query = f"""
        SELECT DISTINCT user_email
        FROM {self.table_name}
        WHERE agent_id = $1;
        """
        try:
            async with self.pool.acquire() as conn:
                # fetch all rows
                records = await conn.fetch(query, agent_id)
                
                # Extract the 'user_email' from each row and return as a list
                return [record['user_email'] for record in records]

        except Exception as e:
            log.error(f"Error retrieving unique exporters for agent '{agent_id}': {e}")
            raise

