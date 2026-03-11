# © 2024-25 Infosys Limited, Bangalore, India. All Rights Reserved.
import os
import uuid
import json
import re
import pandas as pd
from datetime import datetime, timezone, timedelta
import asyncpg
import difflib
from typing import List, Dict, Any, Optional, Union, Literal, Tuple
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from src.config.constants import TableNames, DatabaseName
from src.config.application_config import app_config
from src.utils.cache_utils import cache_result, invalidate_entity_cache, CacheableRepository
from src.config.cache_config import EXPIRY_TIME, ENABLE_CACHING
from telemetry_wrapper import logger as log
from src.utils.secrets_handler import current_user_email
from src.auth.models import User, UserRole

# --- Base Repository ---

class BaseRepository:
    """
    Base class for all repositories.
    Provides the database connection pool to subclasses.
    """

    def __init__(self, pool: asyncpg.Pool, login_pool: asyncpg.Pool, table_name: str):
        """
        Initializes the BaseRepository with a database connection pool.

        Args:
            pool (asyncpg.Pool): The asyncpg connection pool.
        """
        if not pool:
            raise ValueError("Connection pool is not provided.")
        if not login_pool:
            raise ValueError("Login connection pool is not provided.")
        self.pool = pool
        self.login_pool = login_pool
        self.table_name = table_name

    async def _transform_emails_to_usernames(self, rows: List[Dict], email_fields: List[str]) -> List[Dict]:
        """
        Batch-transforms email addresses to usernames for specified fields.
        
        Args:
            rows: List of row dictionaries to transform
            email_fields: List of field names containing email addresses to transform
            
        Returns:
            List of transformed row dictionaries with emails replaced by usernames
        """
        if not rows:
            return rows
            
        # Collect unique emails from all specified fields
        emails = set()
        for row in rows:
            for field in email_fields:
                if row.get(field):
                    emails.add(row[field])
        
        # Fetch all usernames in one query
        email_to_username = {}
        if emails:
            async with self.login_pool.acquire() as conn:
                user_records = await conn.fetch(
                    f"SELECT mail_id, user_name FROM {TableNames.LOGIN_CREDENTIAL.value} WHERE mail_id = ANY($1)",
                    list(emails)
                )
                email_to_username = {r['mail_id']: r['user_name'] for r in user_records}
        
        # Transform rows
        for row in rows:
            for field in email_fields:
                if row.get(field):
                    username = email_to_username.get(row[field])
                    if username:
                        row[field] = username
                    elif '@' in row[field]:
                        row[field] = row[field].split('@')[0]
        return rows


# --- Tag Repository ---

class TagRepository(BaseRepository, CacheableRepository):
    """
    Repository for the 'tags_table'. Handles direct database interactions for tags.
    """

    def __init__(self, pool: asyncpg.Pool, login_pool: asyncpg.Pool, table_name: str = TableNames.TAG.value):
        """
        Initializes the TagRepository.

        Args:
            pool (asyncpg.Pool): The asyncpg connection pool.
            table_name (str): The name of the tags table.
        """
        super().__init__(pool, login_pool, table_name)


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

                # Migration: Ensure UNIQUE constraint exists on tag_name (for existing tables)
                try:
                    await conn.execute(f"""
                        DO $$ BEGIN
                        IF NOT EXISTS (
                            SELECT 1 FROM pg_constraint 
                            WHERE conname = '{self.table_name}_tag_name_key'
                        ) THEN
                            ALTER TABLE {self.table_name} ADD CONSTRAINT {self.table_name}_tag_name_key UNIQUE (tag_name);
                        END IF;
                        END $$;
                    """)
                except Exception as e:
                    log.debug(f"Unique constraint on tag_name may already exist or cannot be added: {e}")

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
            await self.invalidate_all_method_cache("get_tag_record")
            await self.invalidate_all_method_cache("get_all_tag_records")
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
        query = f"SELECT * FROM {self.table_name} ORDER BY tag_name ASC"
        try:
            async with self.pool.acquire() as conn:
                rows = await conn.fetch(query)
            log.info(f"Retrieved {len(rows)} tag records from '{self.table_name}'.")
            updated_rows = [dict(row) for row in rows]
            await self._transform_emails_to_usernames(updated_rows, ['created_by'])
            return updated_rows
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
                row = dict(row)
                await self._transform_emails_to_usernames([row], ['created_by'])
                return row
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
            await self.invalidate_all_method_cache("get_tag_record")
            await self.invalidate_all_method_cache("get_all_tag_records")
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
            await self.invalidate_all_method_cache("get_tag_record")
            await self.invalidate_all_method_cache("get_all_tag_records")
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

    def __init__(self, pool: asyncpg.Pool, login_pool: asyncpg.Pool, table_name: str = TableNames.TAG_TOOL_MAPPING.value):
        """
        Initializes the TagToolMappingRepository.

        Args:
            pool (asyncpg.Pool): The asyncpg connection pool.
            login_pool (asyncpg.Pool): The asyncpg connection pool for login-related operations.
            table_name (str): The name of the tag-tool mapping table.
        """
        super().__init__(pool, login_pool, table_name)


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
                FOREIGN KEY(tag_id) REFERENCES {TableNames.TAG.value}(tag_id) ON DELETE RESTRICT,
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
            await self.invalidate_all_method_cache("get_tool_tag_mappings")
            await self.invalidate_all_method_cache("get_tags_by_tool_id_records")
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
                await self.invalidate_all_method_cache("get_tool_tag_mappings")
                await self.invalidate_all_method_cache("get_tags_by_tool_id_records")
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
                await self.invalidate_all_method_cache("get_tool_tag_mappings")
                await self.invalidate_all_method_cache("get_tags_by_tool_id_records")
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
                    await self.invalidate_all_method_cache("get_tool_tag_mappings")
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

    def __init__(self, pool: asyncpg.Pool, login_pool: asyncpg.Pool, table_name: str = TableNames.TAG_AGENTIC_APP_MAPPING.value):
        """
        Initializes the TagAgentMappingRepository.

        Args:
            pool (asyncpg.Pool): The asyncpg connection pool.
            login_pool (asyncpg.Pool): The asyncpg connection pool for login-related operations.
            table_name (str): The name of the tag-agent mapping table.
        """
        super().__init__(pool, login_pool, table_name)


    async def create_table_if_not_exists(self):
        """
        Creates the 'tag_agentic_app_mapping_table' if it does not exist.
        """
        try:
            create_statement = f"""
            CREATE TABLE IF NOT EXISTS {self.table_name} (
                tag_id TEXT,
                agentic_application_id TEXT,
                FOREIGN KEY(tag_id) REFERENCES {TableNames.TAG.value}(tag_id) ON DELETE RESTRICT,
                FOREIGN KEY(agentic_application_id) REFERENCES {TableNames.AGENT.value}(agentic_application_id) ON DELETE CASCADE,
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
            await self.invalidate_all_method_cache("get_agent_tag_mappings")
            await self.invalidate_all_method_cache("get_tags_by_agent_id_records")
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
                await self.invalidate_all_method_cache("get_agent_tag_mappings")
                await self.invalidate_all_method_cache("get_tags_by_agent_id_records")
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
                await self.invalidate_all_method_cache("get_agent_tag_mappings")
                await self.invalidate_all_method_cache("get_tags_by_agent_id_records")
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

    def __init__(self, pool: asyncpg.Pool, login_pool: asyncpg.Pool, table_name: str = TableNames.TOOL.value):
        """
        Initializes the ToolRepository.

        Args:
            pool (asyncpg.Pool): The asyncpg connection pool.
            login_pool (asyncpg.Pool): The asyncpg connection pool for login-related operations.
            table_name (str): The name of the tools table.
        """
        super().__init__(pool, login_pool, table_name)


    async def create_table_if_not_exists(self):
        """
        Creates the 'tool_table' in PostgreSQL if it does not exist.
        """
        try:
            create_statement = f"""
            CREATE TABLE IF NOT EXISTS {self.table_name} (
                tool_id TEXT PRIMARY KEY,
                tool_name TEXT NOT NULL,
                tool_description TEXT,
                code_snippet TEXT,
                model_name TEXT,
                department_name TEXT DEFAULT 'General',
                created_by TEXT,
                created_on TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
                updated_on TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
                last_used TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
                is_public BOOLEAN DEFAULT FALSE,
                status TEXT DEFAULT 'pending',
                comments TEXT,
                approved_at TIMESTAMPTZ,
                approved_by TEXT,
                CHECK (status IN ('pending', 'approved', 'rejected')),
                UNIQUE (tool_name, department_name)
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
                    f"ALTER TABLE {self.table_name} ADD COLUMN IF NOT EXISTS last_used TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP",
                    f"ALTER TABLE {self.table_name} ADD COLUMN IF NOT EXISTS department_name TEXT DEFAULT 'General'",
                    f"ALTER TABLE {self.table_name} ALTER COLUMN created_on TYPE TIMESTAMPTZ",
                    f"ALTER TABLE {self.table_name} ALTER COLUMN updated_on TYPE TIMESTAMPTZ",
                    f"ALTER TABLE {self.table_name} ALTER COLUMN last_used TYPE TIMESTAMPTZ",
                    f"ALTER TABLE {self.table_name} ALTER COLUMN last_used SET DEFAULT CURRENT_TIMESTAMP",
                    f"UPDATE {self.table_name} SET last_used = CURRENT_TIMESTAMP WHERE last_used IS NULL",
                    f"DO $$ BEGIN "
                    f"IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = '{self.table_name}_status_check') THEN "
                    f"ALTER TABLE {self.table_name} ADD CONSTRAINT {self.table_name}_status_check CHECK (status IN ('pending', 'approved', 'rejected')); "
                    f"END IF; END $$;",
                    # Migration: Drop old unique constraint on tool_name only, add composite unique on (tool_name, department_name)
                    f"DO $$ BEGIN "
                    f"IF EXISTS (SELECT 1 FROM pg_constraint WHERE conname = '{self.table_name}_tool_name_key') THEN "
                    f"ALTER TABLE {self.table_name} DROP CONSTRAINT {self.table_name}_tool_name_key; "
                    f"END IF; END $$;",
                    f"DO $$ BEGIN "
                    f"IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = '{self.table_name}_tool_name_department_name_key') THEN "
                    f"ALTER TABLE {self.table_name} ADD CONSTRAINT {self.table_name}_tool_name_department_name_key UNIQUE (tool_name, department_name); "
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
                                        code_snippet, model_name, created_by, created_on, updated_on, is_public.

        Returns:
            bool: True if the tool was inserted successfully, False if a unique violation occurred or on other error.
        """
        insert_statement = f"""
        INSERT INTO {self.table_name} (tool_id, tool_name, tool_description, code_snippet, model_name, created_by, created_on, department_name, is_public)
        VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
        """
        try:
            async with self.pool.acquire() as conn:
                await conn.execute(
                    insert_statement,
                    tool_data.get("tool_id"), tool_data.get("tool_name"),
                    tool_data.get("tool_description"), tool_data.get("code_snippet"),
                    tool_data.get("model_name"), tool_data.get("created_by"),
                    tool_data["created_on"], tool_data.get("department_name"),
                    tool_data.get("is_public", False)
                )
            await self.invalidate_all_method_cache("get_tool_record")
            await self.invalidate_all_method_cache("get_all_tool_records")

            log.info(f"Tool record {tool_data.get('tool_name')} inserted successfully.")
            return True
        except asyncpg.UniqueViolationError:
            log.warning(f"Tool record {tool_data.get('tool_name')} already exists (unique violation).")
            return False
        except Exception as e:
            log.error(f"Error saving tool record {tool_data.get('tool_name')}: {e}")
            return False

    @CacheableRepository.cache(ttl=EXPIRY_TIME, namespace="ToolRepository")
    async def get_tool_record(self, tool_id: Optional[str] = None, tool_name: Optional[str] = None,message_queue_implementation:bool=False, department_name: str = None, include_public: bool = True) -> List[Dict[str, Any]]:
        """
        Retrieves a single tool record by its ID or name, optionally filtered by department_name.
        When department_name is specified and include_public is True, also returns the tool if it's public.

        Args:
            tool_id (Optional[str]): The ID of the tool.
            tool_name (Optional[str]): The name of the tool.
            department_name (str): The department name to filter by.
            include_public (bool): Whether to include public tools from other departments. Defaults to True.

        Returns:
            List[Dict[str, Any]]: A list of dictionary representing the tool record, or an empty list if not found.
        """
        query = f"SELECT * FROM {self.table_name}"
        where_clauses = []
        params = []

        if tool_id:
           # if tool_id.endswith()
            if not message_queue_implementation:
                if tool_id.endswith('_message_queue'):
                    tool_id = tool_id[:-14]
            where_clauses.append(f"tool_id = ${len(params)+1}")
            params.append(tool_id)
        elif tool_name:
            if not message_queue_implementation:
                if tool_name.endswith('_message_queue'):
                    tool_name = tool_name[:-14]
            where_clauses.append(f"tool_name = ${len(params)+1}")
            params.append(tool_name)
        else:
            log.warning("No tool_id or tool_name provided to get_tool_record.")
            return []

        # Include own department tools OR public tools from other departments
        if department_name:
            if include_public:
                where_clauses.append(f"(department_name = ${len(params)+1} OR is_public = TRUE)")
            else:
                where_clauses.append(f"department_name = ${len(params)+1}")
            params.append(department_name)

        if where_clauses:
            query += " WHERE " + " AND ".join(where_clauses)

        try:
            async with self.pool.acquire() as conn:
                rows = await conn.fetch(query, *params)
            if rows:
                log.info(f"Tool record '{tool_id or tool_name}' retrieved successfully.")
                updated_rows = [dict(row) for row in rows]
                await self._transform_emails_to_usernames(updated_rows, ['created_by'])
                return updated_rows
            else:
                log.info(f"Tool record '{tool_id or tool_name}' not found.")
                return []
        except Exception as e:
            log.error(f"Error retrieving tool record '{tool_id or tool_name}': {e}")
            return []

    @CacheableRepository.cache(ttl=EXPIRY_TIME, namespace="ToolRepository")
    async def get_all_tool_records(self, department_name: str = None, include_public: bool = True) -> List[Dict[str, Any]]:
        """
        Retrieves all tool records, optionally filtered by department_name.
        When department_name is specified and include_public is True, also includes public tools from other departments.

        Args:
            department_name (str, optional): Filter by department name.
            include_public (bool): Whether to include public tools from other departments. Defaults to True.

        Returns:
            List[Dict[str, Any]]: A list of dictionaries, each representing a tool record.
        """
        query = f"SELECT * FROM {self.table_name}"
        params = []
        if department_name:
            if include_public:
                query += " WHERE (department_name = $1 OR is_public = TRUE)"
            else:
                query += " WHERE department_name = $1"
            params.append(department_name)
        query += " ORDER BY created_on DESC"
        log.info(f"Executing query to retrieve all tool records: {query}")
        try:
            async with self.pool.acquire() as conn:
                rows = await conn.fetch(query, *params)
            updated_rows = [dict(row) for row in rows]
            await self._transform_emails_to_usernames(updated_rows, ['created_by', 'approved_by'])
            log.info(f"Retrieved {len(rows)} tool records from '{self.table_name}'.")
            return updated_rows
        except Exception as e:
            log.error(f"Error retrieving all tool records: {e}")
            return []

    async def get_all_tool_records_with_shared(
        self, 
        department_name: str, 
        shared_tool_ids: List[str] = None,
        include_public: bool = True
    ) -> List[Dict[str, Any]]:
        """
        Retrieves all tool records for a department including:
        1. Tools owned by the department
        2. Tools shared with the department (via sharing table)
        3. Public tools (is_public=True) from other departments (if include_public=True)

        Args:
            department_name (str): The department to get tools for.
            shared_tool_ids (List[str]): List of tool IDs shared with this department.
            include_public (bool): Whether to include public tools from other departments.

        Returns:
            List[Dict[str, Any]]: A list of tool records with 'is_shared' and 'is_public_access' flags.
        """
        if not department_name:
            return await self.get_all_tool_records()

        shared_tool_ids = shared_tool_ids or []
        
        # Build query to get:
        # 1. Own department tools
        # 2. Shared tools (by ID)
        # 3. Public tools from other departments
        
        if shared_tool_ids and include_public:
            query = f"""
            SELECT *, 
                CASE 
                    WHEN department_name = $1 THEN FALSE
                    WHEN tool_id = ANY($2) THEN TRUE
                    ELSE FALSE
                END as is_shared,
                CASE 
                    WHEN department_name != $1 AND is_public = TRUE AND tool_id != ALL($2) THEN TRUE
                    ELSE FALSE
                END as is_public_access
            FROM {self.table_name}
            WHERE department_name = $1 
               OR tool_id = ANY($2)
               OR (is_public = TRUE AND department_name != $1)
            ORDER BY 
                CASE WHEN department_name = $1 THEN 0 ELSE 1 END,
                created_on DESC
            """
            params = [department_name, shared_tool_ids]
        elif shared_tool_ids:
            query = f"""
            SELECT *, 
                CASE WHEN department_name = $1 THEN FALSE ELSE TRUE END as is_shared,
                FALSE as is_public_access
            FROM {self.table_name}
            WHERE department_name = $1 OR tool_id = ANY($2)
            ORDER BY 
                CASE WHEN department_name = $1 THEN 0 ELSE 1 END,
                created_on DESC
            """
            params = [department_name, shared_tool_ids]
        elif include_public:
            query = f"""
            SELECT *, 
                FALSE as is_shared,
                CASE WHEN department_name != $1 AND is_public = TRUE THEN TRUE ELSE FALSE END as is_public_access
            FROM {self.table_name}
            WHERE department_name = $1 OR (is_public = TRUE AND department_name != $1)
            ORDER BY 
                CASE WHEN department_name = $1 THEN 0 ELSE 1 END,
                created_on DESC
            """
            params = [department_name]
        else:
            query = f"""
            SELECT *, FALSE as is_shared, FALSE as is_public_access
            FROM {self.table_name}
            WHERE department_name = $1
            WHERE tool_id NOT LIKE '%_message_queue'
            ORDER BY created_on DESC
            """
            params = [department_name]

        try:
            async with self.pool.acquire() as conn:
                rows = await conn.fetch(query, *params)
            updated_rows = [dict(row) for row in rows]
            await self._transform_emails_to_usernames(updated_rows, ['created_by', 'approved_by'])
            log.info(f"Retrieved {len(rows)} tool records (including shared/public) for department '{department_name}'.")
            return updated_rows
        except Exception as e:
            log.error(f"Error retrieving tool records with shared: {e}")
            return []


    async def get_tools_by_search_or_page_records(self, search_value: str, limit: int, page: int, created_by: str = None, department_name: str = None, shared_tool_ids: List[str] = None) -> List[Dict[str, Any]]:
        """
        Retrieves tool records with pagination and search filtering.
        Includes public tools and shared tools when department_name is specified.

        Args:
            search_value (str): The value to search for in tool names (case-insensitive, LIKE).
            limit (int): The maximum number of records to return.
            page (int): The page number (1-indexed).
            created_by (str, optional): If provided, include records created by this user even if not approved.
            department_name (str, optional): If provided, filter results by department and include public/shared tools.
            shared_tool_ids (List[str], optional): List of tool IDs shared with the department.

        Returns:
            List[Dict[str, Any]]: A list of dictionaries, each representing a tool record.
        """
        name_filter = f"%{search_value.lower()}%" if search_value else "%"
        offset = limit * max(0, page - 1)
        shared_tool_ids = shared_tool_ids or []

        query = f"SELECT tool_id, tool_name, tool_description, created_by, department_name, is_public FROM {self.table_name}"
        where_clauses: List[str] = []
        params: List[Any] = []

        # name filter (always present)
        where_clauses.append(f"LOWER(tool_name) LIKE ${len(params) + 1}")
        params.append(name_filter)

        # created_by logic: allow either approved or created_by match
        if created_by:
            where_clauses.append(f"(status = 'approved' OR created_by = ${len(params) + 1})")
            params.append(created_by)

        # department filter - include own department tools OR public tools OR shared tools
        if department_name:
            if shared_tool_ids:
                where_clauses.append(f"(department_name = ${len(params) + 1} OR is_public = TRUE OR tool_id = ANY(${len(params) + 2}))")
                params.append(department_name)
                params.append(shared_tool_ids)
            else:
                where_clauses.append(f"(department_name = ${len(params) + 1} OR is_public = TRUE)")
                params.append(department_name)

        if where_clauses:
            query += " WHERE " + " AND ".join(where_clauses)

        # add ordering and pagination - own department tools first, then shared, then public tools
        if department_name:
            query += f" ORDER BY CASE WHEN department_name = ${len(params) + 1} THEN 0 ELSE 1 END, created_on DESC LIMIT ${len(params) + 2} OFFSET ${len(params) + 3}"
            params.extend([department_name, limit, offset])
        else:
            query += f" ORDER BY created_on DESC LIMIT ${len(params) + 1} OFFSET ${len(params) + 2}"
            params.extend([limit, offset])

        try:
            async with self.pool.acquire() as conn:
                rows = await conn.fetch(query, *params)
            updated_rows = [dict(row) for row in rows]
            await self._transform_emails_to_usernames(updated_rows, ['created_by', 'approved_by'])
            log.info(f"Retrieved {len(rows)} tool records for search '{search_value}', page {page}.")
            return updated_rows
        except Exception as e:
            log.error(f"Error retrieving tool records by search/page: {e}")
            return []

    async def get_total_tool_count(self, search_value: str = '', created_by: str = None, department_name: str = None, shared_tool_ids: List[str] = None) -> int:
        """
        Retrieves the total count of tool records, optionally filtered by name, creator and department.
        Includes public tools and shared tools when department_name is specified.

        Args:
            search_value (str): The value to search for in tool names (case-insensitive, LIKE).
            created_by (str, optional): Filter by creator email.
            department_name (str, optional): Filter by department name (also includes public/shared tools).
            shared_tool_ids (List[str], optional): List of tool IDs shared with the department.

        Returns:
            int: The total count of matching tool records.
        """
        name_filter = f"%{search_value.lower()}%" if search_value else "%"
        shared_tool_ids = shared_tool_ids or []
        # Build WHERE clauses and parameter list safely
        where_clauses = ["LOWER(tool_name) LIKE $1"]
        params: List[Any] = [name_filter]
        next_param_idx = 2

        if created_by:
            where_clauses.append(f"created_by = ${next_param_idx}")
            params.append(created_by)
            next_param_idx += 1

        # Include own department tools OR public tools OR shared tools
        if department_name:
            if shared_tool_ids:
                where_clauses.append(f"(department_name = ${next_param_idx} OR is_public = TRUE OR tool_id = ANY(${next_param_idx + 1}))")
                params.append(department_name)
                params.append(shared_tool_ids)
                next_param_idx += 2
            else:
                where_clauses.append(f"(department_name = ${next_param_idx} OR is_public = TRUE)")
                params.append(department_name)
                next_param_idx += 1

        query = f"SELECT COUNT(*) FROM {self.table_name} WHERE " + " AND ".join(where_clauses)
        try:
            async with self.pool.acquire() as conn:
                count = await conn.fetchval(query, *params)
            count = int(count) if count is not None else 0
            log.info(f"Total tool count for search '{search_value}', created_by='{created_by}', department_name='{department_name}': {count}.")
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
        update_data = {k: v for k, v in tool_data.items() if k != 'updated_on'}
        
        # Build SET clauses for the fields we want to update
        set_clauses = [f"{key} = ${i+2}" for i, key in enumerate(update_data.keys())]
        set_clauses.append("updated_on = CURRENT_TIMESTAMP")
        values = list(update_data.values())
        query = f"UPDATE {self.table_name} SET {', '.join(set_clauses)} WHERE tool_id = $1"
        
        try:
            async with self.pool.acquire() as conn:
                result = await conn.execute(query, tool_id, *values)
            if result != "UPDATE 0":
                await self.invalidate_all_method_cache("get_tool_record")
                await self.invalidate_all_method_cache("get_all_tool_records")
    
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
                await self.invalidate_all_method_cache("get_tool_record")
                await self.invalidate_all_method_cache("get_all_tool_records")
    
                
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
            updated_rows = [dict(row) for row in rows]
            await self._transform_emails_to_usernames(updated_rows, ['created_by', 'approved_by'])
            return updated_rows
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
            updated_rows = [dict(row) for row in rows]
            await self._transform_emails_to_usernames(updated_rows, ['created_by', 'approved_by'])
            return updated_rows
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
                await self.invalidate_all_method_cache("get_tool_record")
                await self.invalidate_all_method_cache("get_all_tool_records")
                log.info(f"Tool '{tool_id}' approved successfully by '{approved_by}' at {approval_time_utc}.")
                return True
            else:
                log.warning(f"Tool '{tool_id}' not found, no approval performed.")
                return False
        except Exception as e:
            log.error(f"Error approving tool '{tool_id}': {e}")
            return False
        


    async def update_last_used(self, tool_name: str) -> bool:
        """
        Updates the last_used timestamp for a tool.

        Args:
            tool_id (str): The ID of the tool to update.

        Returns:
            bool: True if the tool was updated successfully, False otherwise.
        """
        log.info(f"REPOSITORY: Attempting to update last_used for tool_id: {tool_name}")
        update_statement = f"""
        UPDATE {self.table_name} 
        SET last_used = $1
        WHERE tool_name = $2
        """
        
        current_time_utc = datetime.now(timezone.utc)
        log.info(f"REPOSITORY: Using timestamp: {current_time_utc}")
        try:
            async with self.pool.acquire() as conn:
                log.info(f"REPOSITORY: Executing UPDATE query for tool_name: {tool_name}")
                result = await conn.execute(update_statement, current_time_utc, tool_name)
                log.info(f"REPOSITORY: Update query result: {result}")
            if result != "UPDATE 0":
                log.info(f"SUCCESS REPOSITORY: Tool '{tool_name}' last_used timestamp updated to {current_time_utc}.")
                return True
            else:
                log.warning(f"WARNING REPOSITORY: Tool '{tool_name}' not found, no last_used update performed.")
                return False
        except Exception as e:
            log.error(f"ERROR REPOSITORY: Error updating last_used for tool '{tool_name}': {e}")
            return False


# --- ToolDepartmentSharingRepository ---

class ToolDepartmentSharingRepository(BaseRepository):
    """
    Repository for managing tool sharing across departments.
    Handles sharing tools from one department to specific other departments.
    """

    def __init__(self, pool: asyncpg.Pool, login_pool: asyncpg.Pool, table_name: str = TableNames.TOOL_DEPARTMENT_SHARING.value):
        """
        Initializes the ToolDepartmentSharingRepository.

        Args:
            pool (asyncpg.Pool): The asyncpg connection pool.
            login_pool (asyncpg.Pool): The asyncpg connection pool for login-related operations.
            table_name (str): The name of the tool department sharing table.
        """
        super().__init__(pool, login_pool, table_name)

    async def create_table_if_not_exists(self):
        """
        Creates the 'tool_department_sharing' table if it does not exist.
        """
        try:
            create_statement = f"""
            CREATE TABLE IF NOT EXISTS {self.table_name} (
                id SERIAL PRIMARY KEY,
                tool_id TEXT NOT NULL,
                tool_name TEXT NOT NULL,
                source_department TEXT NOT NULL,
                target_department TEXT NOT NULL,
                shared_by TEXT NOT NULL,
                shared_on TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
                UNIQUE (tool_id, target_department),
                FOREIGN KEY (tool_id) REFERENCES {TableNames.TOOL.value}(tool_id) ON DELETE CASCADE
            );
            """
            async with self.pool.acquire() as conn:
                await conn.execute(create_statement)
                # Create index for faster lookups
                await conn.execute(
                    f"CREATE INDEX IF NOT EXISTS idx_{self.table_name}_tool_id ON {self.table_name} (tool_id)"
                )
                await conn.execute(
                    f"CREATE INDEX IF NOT EXISTS idx_{self.table_name}_target_dept ON {self.table_name} (target_department)"
                )
            log.info(f"Table '{self.table_name}' created successfully or already exists.")
        except Exception as e:
            log.error(f"Error creating table '{self.table_name}': {e}")

    async def share_tool_with_department(
        self, 
        tool_id: str, 
        tool_name: str,
        source_department: str, 
        target_department: str, 
        shared_by: str
    ) -> bool:
        """
        Shares a tool with a specific department.

        Args:
            tool_id (str): The ID of the tool to share.
            tool_name (str): The name of the tool to share.
            source_department (str): The department that owns the tool.
            target_department (str): The department to share the tool with.
            shared_by (str): The admin email who is sharing the tool.

        Returns:
            bool: True if shared successfully, False otherwise.
        """
        if source_department == target_department:
            log.warning(f"Cannot share tool '{tool_id}' with its own department '{source_department}'.")
            return False

        insert_statement = f"""
        INSERT INTO {self.table_name} (tool_id, tool_name, source_department, target_department, shared_by)
        VALUES ($1, $2, $3, $4, $5)
        ON CONFLICT (tool_id, target_department) DO UPDATE SET tool_name = $2
        """
        try:
            async with self.pool.acquire() as conn:
                result = await conn.execute(insert_statement, tool_id, tool_name, source_department, target_department, shared_by)
            log.info(f"Tool '{tool_name}' ({tool_id}) shared with department '{target_department}' by '{shared_by}'.")
            return True
        except Exception as e:
            log.error(f"Error sharing tool '{tool_id}' with department '{target_department}': {e}")
            return False

    async def share_tool_with_multiple_departments(
        self, 
        tool_id: str, 
        tool_name: str,
        source_department: str, 
        target_departments: List[str], 
        shared_by: str
    ) -> Dict[str, Any]:
        """
        Shares a tool with multiple departments at once.

        Args:
            tool_id (str): The ID of the tool to share.
            tool_name (str): The name of the tool to share.
            source_department (str): The department that owns the tool.
            target_departments (List[str]): List of departments to share the tool with.
            shared_by (str): The admin email who is sharing the tool.

        Returns:
            Dict[str, Any]: Result with success count and any failures.
        """
        success_count = 0
        failures = []

        for target_dept in target_departments:
            if target_dept == source_department:
                failures.append({"department": target_dept, "reason": "Cannot share with own department"})
                continue
            
            success = await self.share_tool_with_department(tool_id, tool_name, source_department, target_dept, shared_by)
            if success:
                success_count += 1
            else:
                failures.append({"department": target_dept, "reason": "Failed to share"})

        return {
            "success_count": success_count,
            "total_requested": len(target_departments),
            "failures": failures
        }

    async def unshare_tool_from_department(self, tool_id: str, target_department: str) -> bool:
        """
        Removes sharing of a tool from a specific department.

        Args:
            tool_id (str): The ID of the tool.
            target_department (str): The department to remove sharing from.

        Returns:
            bool: True if unshared successfully, False otherwise.
        """
        delete_statement = f"""
        DELETE FROM {self.table_name}
        WHERE tool_id = $1 AND target_department = $2
        """
        try:
            async with self.pool.acquire() as conn:
                result = await conn.execute(delete_statement, tool_id, target_department)
            if result != "DELETE 0":
                log.info(f"Tool '{tool_id}' unshared from department '{target_department}'.")
                return True
            else:
                log.warning(f"Tool '{tool_id}' was not shared with department '{target_department}'.")
                return False
        except Exception as e:
            log.error(f"Error unsharing tool '{tool_id}' from department '{target_department}': {e}")
            return False

    async def unshare_tool_from_all_departments(self, tool_id: str) -> int:
        """
        Removes all sharing for a tool (useful when deleting a tool).

        Args:
            tool_id (str): The ID of the tool.

        Returns:
            int: Number of sharing records removed.
        """
        delete_statement = f"""
        DELETE FROM {self.table_name}
        WHERE tool_id = $1
        """
        try:
            async with self.pool.acquire() as conn:
                result = await conn.execute(delete_statement, tool_id)
            count = int(result.split()[-1]) if result else 0
            log.info(f"Removed {count} sharing records for tool '{tool_id}'.")
            return count
        except Exception as e:
            log.error(f"Error removing all sharing for tool '{tool_id}': {e}")
            return 0

    async def get_shared_departments_for_tool(self, tool_id: str) -> List[Dict[str, Any]]:
        """
        Gets all departments a tool is shared with.

        Args:
            tool_id (str): The ID of the tool.

        Returns:
            List[Dict[str, Any]]: List of sharing records.
        """
        query = f"""
        SELECT tool_name, target_department, shared_by, shared_on
        FROM {self.table_name}
        WHERE tool_id = $1
        ORDER BY shared_on DESC
        """
        try:
            async with self.pool.acquire() as conn:
                rows = await conn.fetch(query, tool_id)
            return [dict(row) for row in rows]
        except Exception as e:
            log.error(f"Error getting shared departments for tool '{tool_id}': {e}")
            return []

    async def get_tools_shared_with_department(self, department_name: str) -> List[str]:
        """
        Gets all tool IDs that are shared with a specific department.

        Args:
            department_name (str): The department name.

        Returns:
            List[str]: List of tool IDs shared with this department.
        """
        query = f"""
        SELECT tool_id
        FROM {self.table_name}
        WHERE LOWER(target_department) = LOWER($1)
        """
        try:
            async with self.pool.acquire() as conn:
                rows = await conn.fetch(query, department_name)
            return [row['tool_id'] for row in rows]
        except Exception as e:
            log.error(f"Error getting tools shared with department '{department_name}': {e}")
            return []

    async def get_tools_shared_with_department_details(self, department_name: str) -> List[Dict[str, Any]]:
        """
        Gets all tools that are shared with a specific department with full details.

        Args:
            department_name (str): The department name.

        Returns:
            List[Dict[str, Any]]: List of tool sharing records with tool_id, tool_name, source_department, etc.
        """
        query = f"""
        SELECT tool_id, tool_name, source_department, shared_by, shared_on
        FROM {self.table_name}
        WHERE LOWER(target_department) = LOWER($1)
        ORDER BY shared_on DESC
        """
        try:
            async with self.pool.acquire() as conn:
                rows = await conn.fetch(query, department_name)
            return [dict(row) for row in rows]
        except Exception as e:
            log.error(f"Error getting tools shared with department '{department_name}': {e}")
            return []

    async def is_tool_shared_with_department(self, tool_id: str, department_name: str) -> bool:
        """
        Checks if a specific tool is shared with a department.

        Args:
            tool_id (str): The ID of the tool.
            department_name (str): The department name.

        Returns:
            bool: True if the tool is shared with the department, False otherwise.
        """
        query = f"""
        SELECT EXISTS(
            SELECT 1 FROM {self.table_name}
            WHERE tool_id = $1 AND LOWER(target_department) = LOWER($2)
        )
        """
        try:
            async with self.pool.acquire() as conn:
                result = await conn.fetchval(query, tool_id, department_name)
            return result
        except Exception as e:
            log.error(f"Error checking if tool '{tool_id}' is shared with department '{department_name}': {e}")
            return False


# --- McpToolDepartmentSharingRepository ---

class McpToolDepartmentSharingRepository(BaseRepository):
    """
    Repository for managing MCP tool sharing across departments.
    Handles sharing MCP tools from one department to specific other departments.
    """

    def __init__(self, pool: asyncpg.Pool, login_pool: asyncpg.Pool, table_name: str = TableNames.MCP_TOOL_DEPARTMENT_SHARING.value):
        """
        Initializes the McpToolDepartmentSharingRepository.

        Args:
            pool (asyncpg.Pool): The asyncpg connection pool.
            login_pool (asyncpg.Pool): The asyncpg connection pool for login-related operations.
            table_name (str): The name of the MCP tool department sharing table.
        """
        super().__init__(pool, login_pool, table_name)

    async def create_table_if_not_exists(self):
        """
        Creates the 'mcp_tool_department_sharing' table if it does not exist.
        """
        try:
            create_statement = f"""
            CREATE TABLE IF NOT EXISTS {self.table_name} (
                id SERIAL PRIMARY KEY,
                mcp_tool_id TEXT NOT NULL,
                mcp_tool_name TEXT NOT NULL,
                source_department TEXT NOT NULL,
                target_department TEXT NOT NULL,
                shared_by TEXT NOT NULL,
                shared_on TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
                UNIQUE (mcp_tool_id, target_department),
                FOREIGN KEY (mcp_tool_id) REFERENCES {TableNames.MCP_TOOL.value}(tool_id) ON DELETE CASCADE
            );
            """
            async with self.pool.acquire() as conn:
                await conn.execute(create_statement)
                # Create index for faster lookups
                await conn.execute(
                    f"CREATE INDEX IF NOT EXISTS idx_{self.table_name}_mcp_tool_id ON {self.table_name} (mcp_tool_id)"
                )
                await conn.execute(
                    f"CREATE INDEX IF NOT EXISTS idx_{self.table_name}_target_dept ON {self.table_name} (target_department)"
                )
            log.info(f"Table '{self.table_name}' created successfully or already exists.")
        except Exception as e:
            log.error(f"Error creating table '{self.table_name}': {e}")

    async def share_mcp_tool_with_department(
        self, 
        mcp_tool_id: str, 
        mcp_tool_name: str,
        source_department: str, 
        target_department: str, 
        shared_by: str
    ) -> bool:
        """
        Shares an MCP tool with a specific department.

        Args:
            mcp_tool_id (str): The ID of the MCP tool to share.
            mcp_tool_name (str): The name of the MCP tool to share.
            source_department (str): The department that owns the MCP tool.
            target_department (str): The department to share the MCP tool with.
            shared_by (str): The admin email who is sharing the MCP tool.

        Returns:
            bool: True if shared successfully, False otherwise.
        """
        if source_department == target_department:
            log.warning(f"Cannot share MCP tool '{mcp_tool_id}' with its own department '{source_department}'.")
            return False

        insert_statement = f"""
        INSERT INTO {self.table_name} (mcp_tool_id, mcp_tool_name, source_department, target_department, shared_by)
        VALUES ($1, $2, $3, $4, $5)
        ON CONFLICT (mcp_tool_id, target_department) DO UPDATE SET mcp_tool_name = $2
        """
        try:
            async with self.pool.acquire() as conn:
                result = await conn.execute(insert_statement, mcp_tool_id, mcp_tool_name, source_department, target_department, shared_by)
            log.info(f"MCP tool '{mcp_tool_name}' ({mcp_tool_id}) shared with department '{target_department}' by '{shared_by}'.")
            return True
        except Exception as e:
            log.error(f"Error sharing MCP tool '{mcp_tool_id}' with department '{target_department}': {e}")
            return False

    async def share_mcp_tool_with_multiple_departments(
        self, 
        mcp_tool_id: str, 
        mcp_tool_name: str,
        source_department: str, 
        target_departments: List[str], 
        shared_by: str
    ) -> Dict[str, Any]:
        """
        Shares an MCP tool with multiple departments at once.

        Args:
            mcp_tool_id (str): The ID of the MCP tool to share.
            mcp_tool_name (str): The name of the MCP tool to share.
            source_department (str): The department that owns the MCP tool.
            target_departments (List[str]): List of departments to share the MCP tool with.
            shared_by (str): The admin email who is sharing the MCP tool.

        Returns:
            Dict[str, Any]: Result with success count and any failures.
        """
        success_count = 0
        failures = []

        for target_dept in target_departments:
            if target_dept == source_department:
                failures.append({"department": target_dept, "reason": "Cannot share with own department"})
                continue
            
            success = await self.share_mcp_tool_with_department(mcp_tool_id, mcp_tool_name, source_department, target_dept, shared_by)
            if success:
                success_count += 1
            else:
                failures.append({"department": target_dept, "reason": "Failed to share"})

        return {
            "success_count": success_count,
            "total_requested": len(target_departments),
            "failures": failures
        }

    async def unshare_mcp_tool_from_department(self, mcp_tool_id: str, target_department: str) -> bool:
        """
        Removes sharing of an MCP tool from a specific department.

        Args:
            mcp_tool_id (str): The ID of the MCP tool.
            target_department (str): The department to remove sharing from.

        Returns:
            bool: True if unshared successfully, False otherwise.
        """
        delete_statement = f"""
        DELETE FROM {self.table_name}
        WHERE mcp_tool_id = $1 AND target_department = $2
        """
        try:
            async with self.pool.acquire() as conn:
                result = await conn.execute(delete_statement, mcp_tool_id, target_department)
            if result != "DELETE 0":
                log.info(f"MCP tool '{mcp_tool_id}' unshared from department '{target_department}'.")
                return True
            else:
                log.warning(f"MCP tool '{mcp_tool_id}' was not shared with department '{target_department}'.")
                return False
        except Exception as e:
            log.error(f"Error unsharing MCP tool '{mcp_tool_id}' from department '{target_department}': {e}")
            return False

    async def unshare_mcp_tool_from_all_departments(self, mcp_tool_id: str) -> int:
        """
        Removes all sharing for an MCP tool (useful when deleting an MCP tool).

        Args:
            mcp_tool_id (str): The ID of the MCP tool.

        Returns:
            int: Number of sharing records removed.
        """
        delete_statement = f"""
        DELETE FROM {self.table_name}
        WHERE mcp_tool_id = $1
        """
        try:
            async with self.pool.acquire() as conn:
                result = await conn.execute(delete_statement, mcp_tool_id)
            count = int(result.split()[-1]) if result else 0
            log.info(f"Removed {count} sharing records for MCP tool '{mcp_tool_id}'.")
            return count
        except Exception as e:
            log.error(f"Error removing all sharing for MCP tool '{mcp_tool_id}': {e}")
            return 0

    async def get_shared_departments_for_mcp_tool(self, mcp_tool_id: str) -> List[Dict[str, Any]]:
        """
        Gets all departments an MCP tool is shared with.

        Args:
            mcp_tool_id (str): The ID of the MCP tool.

        Returns:
            List[Dict[str, Any]]: List of sharing records.
        """
        query = f"""
        SELECT mcp_tool_name, target_department, shared_by, shared_on
        FROM {self.table_name}
        WHERE mcp_tool_id = $1
        ORDER BY shared_on DESC
        """
        try:
            async with self.pool.acquire() as conn:
                rows = await conn.fetch(query, mcp_tool_id)
            return [dict(row) for row in rows]
        except Exception as e:
            log.error(f"Error getting shared departments for MCP tool '{mcp_tool_id}': {e}")
            return []

    async def get_mcp_tools_shared_with_department(self, department_name: str) -> List[str]:
        """
        Gets all MCP tool IDs that are shared with a specific department.

        Args:
            department_name (str): The department name.

        Returns:
            List[str]: List of MCP tool IDs shared with this department.
        """
        query = f"""
        SELECT mcp_tool_id
        FROM {self.table_name}
        WHERE LOWER(target_department) = LOWER($1)
        """
        try:
            async with self.pool.acquire() as conn:
                rows = await conn.fetch(query, department_name)
            return [row['mcp_tool_id'] for row in rows]
        except Exception as e:
            log.error(f"Error getting MCP tools shared with department '{department_name}': {e}")
            return []

    async def get_mcp_tools_shared_with_department_details(self, department_name: str) -> List[Dict[str, Any]]:
        """
        Gets all MCP tools that are shared with a specific department with full details.

        Args:
            department_name (str): The department name.

        Returns:
            List[Dict[str, Any]]: List of MCP tool sharing records with mcp_tool_id, mcp_tool_name, source_department, etc.
        """
        query = f"""
        SELECT mcp_tool_id, mcp_tool_name, source_department, shared_by, shared_on
        FROM {self.table_name}
        WHERE LOWER(target_department) = LOWER($1)
        ORDER BY shared_on DESC
        """
        try:
            async with self.pool.acquire() as conn:
                rows = await conn.fetch(query, department_name)
            return [dict(row) for row in rows]
        except Exception as e:
            log.error(f"Error getting MCP tools shared with department '{department_name}': {e}")
            return []

    async def is_mcp_tool_shared_with_department(self, mcp_tool_id: str, department_name: str) -> bool:
        """
        Checks if a specific MCP tool is shared with a department.

        Args:
            mcp_tool_id (str): The ID of the MCP tool.
            department_name (str): The department name.

        Returns:
            bool: True if the MCP tool is shared with the department, False otherwise.
        """
        query = f"""
        SELECT EXISTS(
            SELECT 1 FROM {self.table_name}
            WHERE mcp_tool_id = $1 AND LOWER(target_department) = LOWER($2)
        )
        """
        try:
            async with self.pool.acquire() as conn:
                result = await conn.fetchval(query, mcp_tool_id, department_name)
            return result
        except Exception as e:
            log.error(f"Error checking if MCP tool '{mcp_tool_id}' is shared with department '{department_name}': {e}")
            return False


# --- KbDepartmentSharingRepository ---

class KbDepartmentSharingRepository(BaseRepository):
    """
    Repository for managing knowledge base sharing across departments.
    Handles sharing KBs from one department to specific other departments.
    """

    def __init__(self, pool: asyncpg.Pool, login_pool: asyncpg.Pool, table_name: str = TableNames.KB_DEPARTMENT_SHARING.value):
        """
        Initializes the KbDepartmentSharingRepository.

        Args:
            pool (asyncpg.Pool): The asyncpg connection pool.
            login_pool (asyncpg.Pool): The asyncpg connection pool for login-related operations.
            table_name (str): The name of the KB department sharing table.
        """
        super().__init__(pool, login_pool, table_name)

    async def create_table_if_not_exists(self):
        """
        Creates the 'kb_department_sharing' table if it does not exist.
        """
        try:
            create_statement = f"""
            CREATE TABLE IF NOT EXISTS {self.table_name} (
                id SERIAL PRIMARY KEY,
                knowledgebase_id TEXT NOT NULL,
                knowledgebase_name TEXT NOT NULL,
                source_department TEXT NOT NULL,
                target_department TEXT NOT NULL,
                shared_by TEXT NOT NULL,
                shared_on TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
                UNIQUE (knowledgebase_id, target_department),
                FOREIGN KEY (knowledgebase_id) REFERENCES {TableNames.KNOWLEDGEBASE.value}(knowledgebase_id) ON DELETE CASCADE
            );
            """
            async with self.pool.acquire() as conn:
                await conn.execute(create_statement)
                # Create index for faster lookups
                await conn.execute(
                    f"CREATE INDEX IF NOT EXISTS idx_{self.table_name}_kb_id ON {self.table_name} (knowledgebase_id)"
                )
                await conn.execute(
                    f"CREATE INDEX IF NOT EXISTS idx_{self.table_name}_target_dept ON {self.table_name} (target_department)"
                )
            log.info(f"Table '{self.table_name}' created successfully or already exists.")
        except Exception as e:
            log.error(f"Error creating table '{self.table_name}': {e}")

    async def share_kb_with_department(
        self, 
        knowledgebase_id: str, 
        knowledgebase_name: str,
        source_department: str, 
        target_department: str, 
        shared_by: str
    ) -> bool:
        """
        Shares a knowledge base with a specific department.

        Args:
            knowledgebase_id (str): The ID of the KB to share.
            knowledgebase_name (str): The name of the KB to share.
            source_department (str): The department that owns the KB.
            target_department (str): The department to share the KB with.
            shared_by (str): The admin email who is sharing the KB.

        Returns:
            bool: True if shared successfully, False otherwise.
        """
        if source_department == target_department:
            log.warning(f"Cannot share KB '{knowledgebase_id}' with its own department '{source_department}'.")
            return False

        insert_statement = f"""
        INSERT INTO {self.table_name} (knowledgebase_id, knowledgebase_name, source_department, target_department, shared_by)
        VALUES ($1, $2, $3, $4, $5)
        ON CONFLICT (knowledgebase_id, target_department) DO UPDATE SET knowledgebase_name = $2
        """
        try:
            async with self.pool.acquire() as conn:
                result = await conn.execute(insert_statement, knowledgebase_id, knowledgebase_name, source_department, target_department, shared_by)
            log.info(f"KB '{knowledgebase_name}' ({knowledgebase_id}) shared with department '{target_department}' by '{shared_by}'.")
            return True
        except Exception as e:
            log.error(f"Error sharing KB '{knowledgebase_id}' with department '{target_department}': {e}")
            return False

    async def share_kb_with_multiple_departments(
        self, 
        knowledgebase_id: str, 
        knowledgebase_name: str,
        source_department: str, 
        target_departments: List[str], 
        shared_by: str
    ) -> Dict[str, Any]:
        """
        Shares a KB with multiple departments at once.

        Args:
            knowledgebase_id (str): The ID of the KB to share.
            knowledgebase_name (str): The name of the KB to share.
            source_department (str): The department that owns the KB.
            target_departments (List[str]): List of departments to share the KB with.
            shared_by (str): The admin email who is sharing the KB.

        Returns:
            Dict[str, Any]: Result with success count and any failures.
        """
        success_count = 0
        failures = []

        for target_dept in target_departments:
            if target_dept == source_department:
                failures.append({"department": target_dept, "reason": "Cannot share with own department"})
                continue
            
            success = await self.share_kb_with_department(knowledgebase_id, knowledgebase_name, source_department, target_dept, shared_by)
            if success:
                success_count += 1
            else:
                failures.append({"department": target_dept, "reason": "Failed to share"})

        return {
            "success_count": success_count,
            "total_requested": len(target_departments),
            "failures": failures
        }

    async def unshare_kb_from_department(self, knowledgebase_id: str, target_department: str) -> bool:
        """
        Removes sharing of a KB from a specific department.

        Args:
            knowledgebase_id (str): The ID of the KB.
            target_department (str): The department to remove sharing from.

        Returns:
            bool: True if unshared successfully, False otherwise.
        """
        delete_statement = f"""
        DELETE FROM {self.table_name}
        WHERE knowledgebase_id = $1 AND target_department = $2
        """
        try:
            async with self.pool.acquire() as conn:
                result = await conn.execute(delete_statement, knowledgebase_id, target_department)
            if result != "DELETE 0":
                log.info(f"KB '{knowledgebase_id}' unshared from department '{target_department}'.")
                return True
            else:
                log.warning(f"KB '{knowledgebase_id}' was not shared with department '{target_department}'.")
                return False
        except Exception as e:
            log.error(f"Error unsharing KB '{knowledgebase_id}' from department '{target_department}': {e}")
            return False

    async def unshare_kb_from_all_departments(self, knowledgebase_id: str) -> int:
        """
        Removes all sharing for a KB (useful when deleting a KB).

        Args:
            knowledgebase_id (str): The ID of the KB.

        Returns:
            int: Number of sharing records removed.
        """
        delete_statement = f"""
        DELETE FROM {self.table_name}
        WHERE knowledgebase_id = $1
        """
        try:
            async with self.pool.acquire() as conn:
                result = await conn.execute(delete_statement, knowledgebase_id)
            count = int(result.split()[-1]) if result else 0
            log.info(f"Removed {count} sharing records for KB '{knowledgebase_id}'.")
            return count
        except Exception as e:
            log.error(f"Error removing all sharing for KB '{knowledgebase_id}': {e}")
            return 0

    async def get_shared_departments_for_kb(self, knowledgebase_id: str) -> List[Dict[str, Any]]:
        """
        Gets all departments a KB is shared with.

        Args:
            knowledgebase_id (str): The ID of the KB.

        Returns:
            List[Dict[str, Any]]: List of sharing records.
        """
        query = f"""
        SELECT knowledgebase_name, target_department, shared_by, shared_on
        FROM {self.table_name}
        WHERE knowledgebase_id = $1
        ORDER BY shared_on DESC
        """
        try:
            async with self.pool.acquire() as conn:
                rows = await conn.fetch(query, knowledgebase_id)
            return [dict(row) for row in rows]
        except Exception as e:
            log.error(f"Error getting shared departments for KB '{knowledgebase_id}': {e}")
            return []

    async def get_kbs_shared_with_department(self, department_name: str) -> List[str]:
        """
        Gets all KB IDs that are shared with a specific department.

        Args:
            department_name (str): The department name.

        Returns:
            List[str]: List of KB IDs shared with this department.
        """
        query = f"""
        SELECT knowledgebase_id
        FROM {self.table_name}
        WHERE LOWER(target_department) = LOWER($1)
        """
        try:
            async with self.pool.acquire() as conn:
                rows = await conn.fetch(query, department_name)
            return [row['knowledgebase_id'] for row in rows]
        except Exception as e:
            log.error(f"Error getting KBs shared with department '{department_name}': {e}")
            return []

    async def get_kbs_shared_with_department_details(self, department_name: str) -> List[Dict[str, Any]]:
        """
        Gets all KBs that are shared with a specific department with full details.

        Args:
            department_name (str): The department name.

        Returns:
            List[Dict[str, Any]]: List of KB sharing records with knowledgebase_id, knowledgebase_name, source_department, etc.
        """
        query = f"""
        SELECT knowledgebase_id, knowledgebase_name, source_department, shared_by, shared_on
        FROM {self.table_name}
        WHERE LOWER(target_department) = LOWER($1)
        ORDER BY shared_on DESC
        """
        try:
            async with self.pool.acquire() as conn:
                rows = await conn.fetch(query, department_name)
            return [dict(row) for row in rows]
        except Exception as e:
            log.error(f"Error getting KBs shared with department '{department_name}': {e}")
            return []

    async def is_kb_shared_with_department(self, knowledgebase_id: str, department_name: str) -> bool:
        """
        Checks if a specific KB is shared with a department.

        Args:
            knowledgebase_id (str): The ID of the KB.
            department_name (str): The department name.

        Returns:
            bool: True if the KB is shared with the department, False otherwise.
        """
        query = f"""
        SELECT EXISTS(
            SELECT 1 FROM {self.table_name}
            WHERE knowledgebase_id = $1 AND LOWER(target_department) = LOWER($2)
        )
        """
        try:
            async with self.pool.acquire() as conn:
                result = await conn.fetchval(query, knowledgebase_id, department_name)
            return result
        except Exception as e:
            log.error(f"Error checking if KB '{knowledgebase_id}' is shared with department '{department_name}': {e}")
            return False


# --- AgentDepartmentSharingRepository ---

class AgentDepartmentSharingRepository(BaseRepository):
    """
    Repository for managing agent sharing across departments.
    Handles sharing agents from one department to specific other departments.
    When an agent is shared, its tools are automatically shared too.
    """

    def __init__(self, pool: asyncpg.Pool, login_pool: asyncpg.Pool, table_name: str = TableNames.AGENT_DEPARTMENT_SHARING.value):
        """
        Initializes the AgentDepartmentSharingRepository.

        Args:
            pool (asyncpg.Pool): The asyncpg connection pool.
            login_pool (asyncpg.Pool): The asyncpg connection pool for login-related operations.
            table_name (str): The name of the agent department sharing table.
        """
        super().__init__(pool, login_pool, table_name)
        self.tool_sharing_repo = None  # Will be set by app_container for cascade sharing
        self.mcp_tool_sharing_repo = None  # Will be set by app_container for MCP tools cascade sharing
        self.kb_sharing_repo = None  # Will be set by app_container for KB cascade sharing

    def set_tool_sharing_repo(self, tool_sharing_repo):
        """Sets the tool sharing repository for cascade sharing."""
        self.tool_sharing_repo = tool_sharing_repo

    def set_mcp_tool_sharing_repo(self, mcp_tool_sharing_repo):
        """Sets the MCP tool sharing repository for cascade sharing of MCP tools."""
        self.mcp_tool_sharing_repo = mcp_tool_sharing_repo

    def set_kb_sharing_repo(self, kb_sharing_repo):
        """Sets the KB sharing repository for cascade sharing of knowledge bases."""
        self.kb_sharing_repo = kb_sharing_repo

    async def create_table_if_not_exists(self):
        """
        Creates the 'agent_department_sharing' table if it does not exist.
        """
        try:
            create_statement = f"""
            CREATE TABLE IF NOT EXISTS {self.table_name} (
                id SERIAL PRIMARY KEY,
                agentic_application_id TEXT NOT NULL,
                agentic_application_name TEXT NOT NULL,
                source_department TEXT NOT NULL,
                target_department TEXT NOT NULL,
                shared_by TEXT NOT NULL,
                shared_on TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
                UNIQUE (agentic_application_id, target_department),
                FOREIGN KEY (agentic_application_id) REFERENCES {TableNames.AGENT.value}(agentic_application_id) ON DELETE CASCADE
            );
            """
            async with self.pool.acquire() as conn:
                await conn.execute(create_statement)
                # Create index for faster lookups
                await conn.execute(
                    f"CREATE INDEX IF NOT EXISTS idx_{self.table_name}_agent_id ON {self.table_name} (agentic_application_id)"
                )
                await conn.execute(
                    f"CREATE INDEX IF NOT EXISTS idx_{self.table_name}_target_dept ON {self.table_name} (target_department)"
                )
            log.info(f"Table '{self.table_name}' created successfully or already exists.")
        except Exception as e:
            log.error(f"Error creating table '{self.table_name}': {e}")

    async def share_agent_with_department(
        self, 
        agentic_application_id: str, 
        agentic_application_name: str,
        source_department: str, 
        target_department: str, 
        shared_by: str,
        tools_info: List[Dict[str, str]] = None,
        mcp_tools_info: List[Dict[str, str]] = None,
        kbs_info: List[Dict[str, str]] = None
    ) -> Dict[str, Any]:
        """
        Shares an agent with a specific department. Also shares all the agent's tools (both regular and MCP) and knowledge bases.

        Args:
            agentic_application_id (str): The ID of the agent to share.
            agentic_application_name (str): The name of the agent to share.
            source_department (str): The department that owns the agent.
            target_department (str): The department to share the agent with.
            shared_by (str): The admin email who is sharing the agent.
            tools_info (List[Dict[str, str]]): List of dicts with 'tool_id' and 'tool_name' for agent's regular tools.
            mcp_tools_info (List[Dict[str, str]]): List of dicts with 'tool_id' and 'tool_name' for agent's MCP tools.
            kbs_info (List[Dict[str, str]]): List of dicts with 'kb_id' and 'kb_name' for agent's knowledge bases.

        Returns:
            Dict[str, Any]: Result with agent sharing status and tools sharing details.
        """
        if source_department == target_department:
            log.warning(f"Cannot share agent '{agentic_application_id}' with its own department '{source_department}'.")
            return {"success": False, "reason": "Cannot share with own department"}

        insert_statement = f"""
        INSERT INTO {self.table_name} (agentic_application_id, agentic_application_name, source_department, target_department, shared_by)
        VALUES ($1, $2, $3, $4, $5)
        ON CONFLICT (agentic_application_id, target_department) DO UPDATE SET agentic_application_name = $2
        """
        try:
            async with self.pool.acquire() as conn:
                await conn.execute(insert_statement, agentic_application_id, agentic_application_name, source_department, target_department, shared_by)
            log.info(f"Agent '{agentic_application_name}' ({agentic_application_id}) shared with department '{target_department}' by '{shared_by}'.")
            
            # Cascade: share all agent's regular tools with the same department
            tools_shared = 0
            tools_failed = []
            if tools_info and self.tool_sharing_repo:
                for tool in tools_info:
                    tool_id = tool.get('tool_id')
                    tool_name = tool.get('tool_name', '')
                    tool_dept = tool.get('department_name', source_department)
                    if tool_id:
                        success = await self.tool_sharing_repo.share_tool_with_department(
                            tool_id=tool_id,
                            tool_name=tool_name,
                            source_department=tool_dept,
                            target_department=target_department,
                            shared_by=shared_by
                        )
                        if success:
                            tools_shared += 1
                        else:
                            tools_failed.append(tool_id)
                log.info(f"Cascade shared {tools_shared} regular tools for agent '{agentic_application_id}' with department '{target_department}'.")
            
            # Cascade: share all agent's MCP tools with the same department
            mcp_tools_shared = 0
            mcp_tools_failed = []
            if mcp_tools_info and self.mcp_tool_sharing_repo:
                for mcp_tool in mcp_tools_info:
                    mcp_tool_id = mcp_tool.get('tool_id')
                    mcp_tool_name = mcp_tool.get('tool_name', '')
                    mcp_tool_dept = mcp_tool.get('department_name', source_department)
                    if mcp_tool_id:
                        success = await self.mcp_tool_sharing_repo.share_mcp_tool_with_department(
                            mcp_tool_id=mcp_tool_id,
                            mcp_tool_name=mcp_tool_name,
                            source_department=mcp_tool_dept,
                            target_department=target_department,
                            shared_by=shared_by
                        )
                        if success:
                            mcp_tools_shared += 1
                        else:
                            mcp_tools_failed.append(mcp_tool_id)
                log.info(f"Cascade shared {mcp_tools_shared} MCP tools for agent '{agentic_application_id}' with department '{target_department}'.")
            
            # Cascade: share all agent's knowledge bases with the same department
            kbs_shared = 0
            kbs_failed = []
            if kbs_info and self.kb_sharing_repo:
                for kb in kbs_info:
                    kb_id = kb.get('kb_id')
                    kb_name = kb.get('kb_name', '')
                    kb_dept = kb.get('department_name', source_department)
                    if kb_id:
                        success = await self.kb_sharing_repo.share_kb_with_department(
                            knowledgebase_id=kb_id,
                            knowledgebase_name=kb_name,
                            source_department=kb_dept,
                            target_department=target_department,
                            shared_by=shared_by
                        )
                        if success:
                            kbs_shared += 1
                        else:
                            kbs_failed.append(kb_id)
                log.info(f"Cascade shared {kbs_shared} knowledge bases for agent '{agentic_application_id}' with department '{target_department}'.")
            
            return {
                "success": True,
                "agent_shared": True,
                "tools_shared_count": tools_shared,
                "tools_failed": tools_failed,
                "mcp_tools_shared_count": mcp_tools_shared,
                "mcp_tools_failed": mcp_tools_failed,
                "kbs_shared_count": kbs_shared,
                "kbs_failed": kbs_failed
            }
        except Exception as e:
            log.error(f"Error sharing agent '{agentic_application_id}' with department '{target_department}': {e}")
            return {"success": False, "reason": str(e)}

    async def share_agent_with_multiple_departments(
        self, 
        agentic_application_id: str, 
        agentic_application_name: str,
        source_department: str, 
        target_departments: List[str], 
        shared_by: str,
        tools_info: List[Dict[str, str]] = None,
        mcp_tools_info: List[Dict[str, str]] = None,
        kbs_info: List[Dict[str, str]] = None
    ) -> Dict[str, Any]:
        """
        Shares an agent with multiple departments at once. Also shares all agent's tools (both regular and MCP) and knowledge bases.

        Args:
            agentic_application_id (str): The ID of the agent to share.
            agentic_application_name (str): The name of the agent to share.
            source_department (str): The department that owns the agent.
            target_departments (List[str]): List of departments to share the agent with.
            shared_by (str): The admin email who is sharing the agent.
            tools_info (List[Dict[str, str]]): List of dicts with 'tool_id' and 'tool_name' for agent's regular tools.
            mcp_tools_info (List[Dict[str, str]]): List of dicts with 'tool_id' and 'tool_name' for agent's MCP tools.
            kbs_info (List[Dict[str, str]]): List of dicts with 'kb_id' and 'kb_name' for agent's knowledge bases.

        Returns:
            Dict[str, Any]: Result with success count and any failures.
        """
        success_count = 0
        failures = []
        total_tools_shared = 0
        total_mcp_tools_shared = 0
        total_kbs_shared = 0

        for target_dept in target_departments:
            if target_dept == source_department:
                failures.append({"department": target_dept, "reason": "Cannot share with own department"})
                continue
            
            result = await self.share_agent_with_department(
                agentic_application_id, 
                agentic_application_name,
                source_department, 
                target_dept, 
                shared_by,
                tools_info,
                mcp_tools_info,
                kbs_info
            )
            if result.get("success"):
                success_count += 1
                total_tools_shared += result.get("tools_shared_count", 0)
                total_mcp_tools_shared += result.get("mcp_tools_shared_count", 0)
                total_kbs_shared += result.get("kbs_shared_count", 0)
            else:
                failures.append({"department": target_dept, "reason": result.get("reason", "Failed to share")})

        return {
            "success_count": success_count,
            "total_requested": len(target_departments),
            "total_tools_shared": total_tools_shared,
            "total_mcp_tools_shared": total_mcp_tools_shared,
            "total_kbs_shared": total_kbs_shared,
            "failures": failures
        }

    async def unshare_agent_from_department(self, agentic_application_id: str, target_department: str) -> bool:
        """
        Removes sharing of an agent from a specific department.

        Args:
            agentic_application_id (str): The ID of the agent.
            target_department (str): The department to remove sharing from.

        Returns:
            bool: True if unshared successfully, False otherwise.
        """
        delete_statement = f"""
        DELETE FROM {self.table_name}
        WHERE agentic_application_id = $1 AND target_department = $2
        """
        try:
            async with self.pool.acquire() as conn:
                result = await conn.execute(delete_statement, agentic_application_id, target_department)
            if result != "DELETE 0":
                log.info(f"Agent '{agentic_application_id}' unshared from department '{target_department}'.")
                return True
            else:
                log.warning(f"Agent '{agentic_application_id}' was not shared with department '{target_department}'.")
                return False
        except Exception as e:
            log.error(f"Error unsharing agent '{agentic_application_id}' from department '{target_department}': {e}")
            return False

    async def unshare_agent_from_all_departments(self, agentic_application_id: str) -> int:
        """
        Removes all sharing for an agent (useful when deleting an agent).

        Args:
            agentic_application_id (str): The ID of the agent.

        Returns:
            int: Number of sharing records removed.
        """
        delete_statement = f"""
        DELETE FROM {self.table_name}
        WHERE agentic_application_id = $1
        """
        try:
            async with self.pool.acquire() as conn:
                result = await conn.execute(delete_statement, agentic_application_id)
            count = int(result.split()[-1]) if result else 0
            log.info(f"Removed {count} sharing records for agent '{agentic_application_id}'.")
            return count
        except Exception as e:
            log.error(f"Error removing all sharing for agent '{agentic_application_id}': {e}")
            return 0

    async def get_shared_departments_for_agent(self, agentic_application_id: str) -> List[Dict[str, Any]]:
        """
        Gets all departments an agent is shared with.

        Args:
            agentic_application_id (str): The ID of the agent.

        Returns:
            List[Dict[str, Any]]: List of sharing records.
        """
        query = f"""
        SELECT agentic_application_name, target_department, shared_by, shared_on
        FROM {self.table_name}
        WHERE agentic_application_id = $1
        ORDER BY shared_on DESC
        """
        try:
            async with self.pool.acquire() as conn:
                rows = await conn.fetch(query, agentic_application_id)
            return [dict(row) for row in rows]
        except Exception as e:
            log.error(f"Error getting shared departments for agent '{agentic_application_id}': {e}")
            return []

    async def get_agents_shared_with_department(self, department_name: str) -> List[str]:
        """
        Gets all agent IDs that are shared with a specific department.

        Args:
            department_name (str): The department name.

        Returns:
            List[str]: List of agent IDs shared with this department.
        """
        query = f"""
        SELECT agentic_application_id
        FROM {self.table_name}
        WHERE LOWER(target_department) = LOWER($1)
        """
        try:
            async with self.pool.acquire() as conn:
                rows = await conn.fetch(query, department_name)
            return [row['agentic_application_id'] for row in rows]
        except Exception as e:
            log.error(f"Error getting agents shared with department '{department_name}': {e}")
            return []

    async def get_agents_shared_with_department_details(self, department_name: str) -> List[Dict[str, Any]]:
        """
        Gets all agents that are shared with a specific department with full details.

        Args:
            department_name (str): The department name.

        Returns:
            List[Dict[str, Any]]: List of agent sharing records with agent_id, agent_name, source_department, etc.
        """
        query = f"""
        SELECT agentic_application_id, agentic_application_name, source_department, shared_by, shared_on
        FROM {self.table_name}
        WHERE LOWER(target_department) = LOWER($1)
        ORDER BY shared_on DESC
        """
        try:
            async with self.pool.acquire() as conn:
                rows = await conn.fetch(query, department_name)
            return [dict(row) for row in rows]
        except Exception as e:
            log.error(f"Error getting agents shared with department '{department_name}': {e}")
            return []

    async def is_agent_shared_with_department(self, agentic_application_id: str, department_name: str) -> bool:
        """
        Checks if a specific agent is shared with a department.

        Args:
            agentic_application_id (str): The ID of the agent.
            department_name (str): The department name.

        Returns:
            bool: True if the agent is shared with the department, False otherwise.
        """
        query = f"""
        SELECT EXISTS(
            SELECT 1 FROM {self.table_name}
            WHERE agentic_application_id = $1 AND LOWER(target_department) = LOWER($2)
        )
        """
        try:
            async with self.pool.acquire() as conn:
                result = await conn.fetchval(query, agentic_application_id, department_name)
            return result
        except Exception as e:
            log.error(f"Error checking if agent '{agentic_application_id}' is shared with department '{department_name}': {e}")
            return False
 

# --- McpToolRepository ---

class McpToolRepository(BaseRepository):
    """
    Repository for the 'mcp_tool_table'. Handles direct database interactions for MCP server definitions.
    """
    def __init__(self, pool: asyncpg.Pool, login_pool: asyncpg.Pool, table_name: str = TableNames.MCP_TOOL.value):
        """
        Initializes the McpToolRepository.

        Args:
            pool (asyncpg.Pool): The asyncpg connection pool.
            login_pool (asyncpg.Pool): The asyncpg connection pool for login-related operations.
            table_name (str): The name of the MCP tools table.
        """
        super().__init__(pool, login_pool, table_name)


    async def create_table_if_not_exists(self):
        """
        Creates the 'mcp_tool_table' in PostgreSQL if it does not exist.
        Includes new auth-related columns and the CHECK constraint directly.
        """
        try:
            create_statement = f"""
            CREATE TABLE IF NOT EXISTS {self.table_name} (
                tool_id TEXT PRIMARY KEY,
                tool_name TEXT NOT NULL,
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
                department_name TEXT DEFAULT 'General',
                CONSTRAINT {self.table_name}_status_check CHECK (status IN ('pending', 'approved', 'rejected')),
                UNIQUE (tool_name, department_name)
            );
            """
            async with self.pool.acquire() as conn:
                await conn.execute(create_statement)
                # Add department_name column if it doesn't exist (for existing databases)
                await conn.execute(
                    f"ALTER TABLE {self.table_name} ADD COLUMN IF NOT EXISTS department_name TEXT DEFAULT 'General'"
                )
                # Migration: Drop old unique constraint on tool_name only, add composite unique on (tool_name, department_name)
                await conn.execute(
                    f"DO $$ BEGIN "
                    f"IF EXISTS (SELECT 1 FROM pg_constraint WHERE conname = '{self.table_name}_tool_name_key') THEN "
                    f"ALTER TABLE {self.table_name} DROP CONSTRAINT {self.table_name}_tool_name_key; "
                    f"END IF; END $$;"
                )
                await conn.execute(
                    f"DO $$ BEGIN "
                    f"IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = '{self.table_name}_tool_name_department_name_key') THEN "
                    f"ALTER TABLE {self.table_name} ADD CONSTRAINT {self.table_name}_tool_name_department_name_key UNIQUE (tool_name, department_name); "
                    f"END IF; END $$;"
                )

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
            created_by, created_on, updated_on, department_name
        ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13)
        """
        try:
            # Ensure mcp_config is properly formatted for JSONB
            mcp_config_value = tool_data.get("mcp_config")
            if isinstance(mcp_config_value, str):
                # Already a JSON string, use as-is
                mcp_config_json = mcp_config_value
            else:
                # Dict or other type, convert to JSON string
                mcp_config_json = json.dumps(mcp_config_value)
            
            # Handle datetime fields - strip timezone if present (recycle bin uses TIMESTAMPTZ, main table uses TIMESTAMP)
            created_on = tool_data.get("created_on")
            updated_on = tool_data.get("updated_on")
            approved_at = tool_data.get("approved_at")
            
            # Convert timezone-aware datetimes to naive (remove timezone info)
            if created_on and hasattr(created_on, 'tzinfo') and created_on.tzinfo is not None:
                created_on = created_on.replace(tzinfo=None)
            
            if updated_on and hasattr(updated_on, 'tzinfo') and updated_on.tzinfo is not None:
                updated_on = updated_on.replace(tzinfo=None)
            
            if approved_at and hasattr(approved_at, 'tzinfo') and approved_at.tzinfo is not None:
                approved_at = approved_at.replace(tzinfo=None)
            
            async with self.pool.acquire() as conn:
                await conn.execute(
                    insert_statement,
                    tool_data.get("tool_id"),
                    tool_data.get("tool_name"),
                    tool_data.get("tool_description"),
                    mcp_config_json,
                    tool_data.get("is_public", False),
                    tool_data.get("status", "pending"),
                    tool_data.get("comments"),
                    approved_at,
                    tool_data.get("approved_by"),
                    tool_data.get("created_by"),
                    created_on,
                    updated_on,
                    tool_data.get("department_name")
                )
            log.info(f"MCP tool record '{tool_data.get('tool_name')}' inserted successfully.")
            return True
        except asyncpg.UniqueViolationError as ue:
            log.warning(f"MCP tool record '{tool_data.get('tool_name')}' already exists (unique violation). Error: {ue}")
            return False
        except Exception as e:
            log.error(f"Error saving MCP tool record '{tool_data.get('tool_name')}': {e}. Tool data: {tool_data}")
            return False

    async def get_mcp_tool_record(self, tool_id: Optional[str] = None, tool_name: Optional[str] = None, department_name: str = None) -> List[Dict[str, Any]]:
        """
        Retrieves a single MCP tool (server definition) record by its ID or name, optionally filtered by department_name.

        Args:
            tool_id (Optional[str]): The ID of the MCP tool.
            tool_name (Optional[str]): The name of the MCP tool.
            department_name (str): The department name to filter by.

        Returns:
            List[Dict[str, Any]]: A list of dictionaries representing the MCP tool record, or an empty list if not found.
        """
        query = f"SELECT * FROM {self.table_name}"
        where_clauses = []
        params = []

        if tool_id:
            where_clauses.append(f"tool_id = ${len(params)+1}")
            params.append(tool_id)
        elif tool_name:
            where_clauses.append(f"tool_name = ${len(params)+1}")
            params.append(tool_name)
        else:
            log.warning("No tool_id or tool_name provided to get_mcp_tool_record.")
            return []

        if department_name:
            where_clauses.append(f"department_name = ${len(params)+1}")
            params.append(department_name)

        if where_clauses:
            query += " WHERE " + " AND ".join(where_clauses)

        try:
            async with self.pool.acquire() as conn:
                rows = await conn.fetch(query, *params)
            if rows:
                log.info(f"MCP tool record '{tool_id or tool_name}' retrieved successfully.")
                updated_rows = [dict(row) for row in rows]
                await self._transform_emails_to_usernames(updated_rows, ['created_by', 'approved_by'])
                return updated_rows
            else:
                log.info(f"MCP tool record '{tool_id or tool_name}' not found.")
                return []
        except Exception as e:
            log.error(f"Error retrieving MCP tool record '{tool_id or tool_name}': {e}")
            return []

    async def get_all_mcp_tool_records(self, department_name: str = None, shared_mcp_tool_ids: List[str] = None) -> List[Dict[str, Any]]:
        """
        Retrieves all MCP tool (server definition) records, optionally filtered by department_name.
        Includes public MCP tools and shared MCP tools when department_name is specified.

        Args:
            department_name (str): The department name to filter by.
            shared_mcp_tool_ids (List[str]): List of MCP tool IDs shared with this department.

        Returns:
            List[Dict[str, Any]]: A list of dictionaries, each representing an MCP tool record.
        """
        params = []
        shared_mcp_tool_ids = shared_mcp_tool_ids or []
        
        if department_name:
            if shared_mcp_tool_ids:
                # Include own department tools OR public tools OR shared tools
                query = f"""
                SELECT *,
                    CASE WHEN tool_id = ANY($2) AND department_name != $1 THEN TRUE ELSE FALSE END as is_shared,
                    CASE WHEN is_public = TRUE AND department_name != $1 AND NOT (tool_id = ANY($2)) THEN TRUE ELSE FALSE END as is_public_access
                FROM {self.table_name}
                WHERE department_name = $1 OR is_public = TRUE OR tool_id = ANY($2)
                ORDER BY CASE WHEN department_name = $1 THEN 0 ELSE 1 END, created_on DESC
                """
                params = [department_name, shared_mcp_tool_ids]
            else:
                # Include own department tools OR public tools
                query = f"""
                SELECT *, FALSE as is_shared,
                    CASE WHEN is_public = TRUE AND department_name != $1 THEN TRUE ELSE FALSE END as is_public_access
                FROM {self.table_name}
                WHERE department_name = $1 OR is_public = TRUE
                ORDER BY CASE WHEN department_name = $1 THEN 0 ELSE 1 END, created_on DESC
                """
                params = [department_name]
        else:
            query = f"SELECT *, FALSE as is_shared, FALSE as is_public_access FROM {self.table_name} ORDER BY created_on DESC"
        
        try:
            async with self.pool.acquire() as conn:
                rows = await conn.fetch(query, *params)
            log.info(f"Retrieved {len(rows)} MCP tool records from '{self.table_name}'.")
            updated_rows = [dict(row) for row in rows]
            await self._transform_emails_to_usernames(updated_rows, ['created_by', 'approved_by'])
            return updated_rows
        except Exception as e:
            log.error(f"Error retrieving all MCP tool records: {e}")
            return []

    async def get_mcp_tools_by_search_or_page_records(self, search_value: str, limit: int, page: int, mcp_type: Optional[List[Literal["file", "url", "module"]]] = None, created_by:str = None, department_name: str = None, shared_mcp_tool_ids: List[str] = None) -> List[Dict[str, Any]]:
        """
        Retrieves MCP tool (server definition) records with pagination and search filtering.
        Includes public MCP tools and shared MCP tools when department_name is specified.

        Args:
            search_value (str): The value to search for in tool names (case-insensitive, LIKE).
            limit (int): The maximum number of records to return.
            page (int): The page number (1-indexed).
            mcp_type (Optional[List[Literal["file", "url", "module"]]]): Optional list of MCP types to filter by.
            created_by (str): Optional filter by creator's email.
            department_name (str): Optional filter by department name (also includes public/shared tools).
            shared_mcp_tool_ids (List[str], optional): List of MCP tool IDs shared with the department.

        Returns:
            List[Dict[str, Any]]: A list of dictionaries, each representing an MCP tool record.
        """
        name_filter = f"%{search_value.lower()}%" if search_value else "%"
        offset = limit * max(0, page - 1)
        shared_mcp_tool_ids = shared_mcp_tool_ids or []

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
        if created_by:
            query += f" AND created_by = ${param_idx}"
            params.append(created_by)
            param_idx += 1
        
        # department filter - include own department MCP tools OR public MCP tools OR shared MCP tools
        if department_name:
            if shared_mcp_tool_ids:
                query += f" AND (department_name = ${param_idx} OR is_public = TRUE OR tool_id = ANY(${param_idx + 1}))"
                params.append(department_name)
                params.append(shared_mcp_tool_ids)
                param_idx += 2
            else:
                query += f" AND (department_name = ${param_idx} OR is_public = TRUE)"
                params.append(department_name)
                param_idx += 1
        
        # add ordering - own department tools first, then shared, then public tools
        if department_name:
            query += f" ORDER BY CASE WHEN department_name = ${param_idx} THEN 0 ELSE 1 END, created_on DESC LIMIT ${param_idx + 1} OFFSET ${param_idx + 2}"
            params.extend([department_name, limit, offset])
        else:
            query += f" ORDER BY created_on DESC LIMIT ${param_idx} OFFSET ${param_idx + 1}"
            params.extend([limit, offset])

        try:
            async with self.pool.acquire() as conn:
                rows = await conn.fetch(query, *params)
            log.info(f"Retrieved {len(rows)} MCP tool records for search '{search_value}', page {page}, type '{mcp_type}'.")
            updated_rows = [dict(row) for row in rows]
            await self._transform_emails_to_usernames(updated_rows, ['created_by', 'approved_by'])
            return updated_rows
        except Exception as e:
            log.error(f"Error retrieving MCP tool records by search/page: {e}")
            return []

    async def get_total_mcp_tool_count(self, search_value: str = '', mcp_type: Optional[List[Literal["file", "url", "module"]]] = None, created_by:str=None, department_name: str=None, shared_mcp_tool_ids: List[str] = None) -> int:
        """
        Retrieves the total count of MCP tool (server definition) records, optionally filtered by name and type.
        Includes public MCP tools and shared MCP tools when department_name is specified.
        """
        name_filter = f"%{search_value.lower()}%" if search_value else "%"
        shared_mcp_tool_ids = shared_mcp_tool_ids or []
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
        if created_by:
            query += f" AND created_by = ${param_idx}"
            params.append(created_by)
            param_idx += 1
        
        # Include own department MCP tools OR public MCP tools OR shared MCP tools
        if department_name:
            if shared_mcp_tool_ids:
                query += f" AND (department_name = ${param_idx} OR is_public = TRUE OR tool_id = ANY(${param_idx + 1}))"
                params.append(department_name)
                params.append(shared_mcp_tool_ids)
            else:
                query += f" AND (department_name = ${param_idx} OR is_public = TRUE)"
                params.append(department_name)

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

    async def log_mcp_validation_result(self, tool_id: str, validation_result: Dict[str, Any]) -> None:
        """
        Logs validation results for MCP tool for auditing and debugging purposes.
        
        Args:
            tool_id (str): The MCP tool ID
            validation_result (Dict): Result from validation containing is_valid, errors, warnings, etc.
        """
        try:
            is_valid = validation_result.get("is_valid", False)
            errors = validation_result.get("errors", [])
            warnings = validation_result.get("warnings", [])
            code_hash = validation_result.get("code_hash", "")
            
            if not is_valid:
                log.warning(f"MCP Tool {tool_id} failed validation. Errors: {errors}")
                # Log security violations specifically
                security_errors = [err for err in errors if "SECURITY_VIOLATION" in err]
                if security_errors:
                    log.error(f"SECURITY ALERT: MCP Tool {tool_id} contains malicious operations: {security_errors}")
            else:
                log.info(f"MCP Tool {tool_id} passed validation successfully. Code hash: {code_hash}")
                if warnings:
                    log.info(f"MCP Tool {tool_id} validation warnings: {warnings}")
                    
        except Exception as e:
            log.error(f"Error logging validation result for MCP tool {tool_id}: {e}")

    async def update_mcp_config_metadata(self, tool_id: str, server_type: str, functions: List[str]) -> bool:
        """
        Updates the mcp_config JSONB field to include server_type and function list metadata.
        
        Args:
            tool_id (str): The MCP tool ID
            server_type (str): The server type (LOCAL or REMOTE)
            functions (List[str]): List of function names in the server
            
        Returns:
            bool: True if update was successful
        """
        try:
            update_statement = f"""
            UPDATE {self.table_name}
            SET mcp_config = mcp_config || $1::jsonb,
                updated_on = CURRENT_TIMESTAMP
            WHERE tool_id = $2
            """
            
            metadata = {
                "server_type": server_type,
                "functions": functions,
                "function_count": len(functions)
            }
            
            log.info(f"Preparing to update tool {tool_id} with metadata: {metadata}")
            log.info(f"Server type value: '{server_type}' (type: {type(server_type).__name__})")
            
            async with self.pool.acquire() as conn:
                result = await conn.execute(update_statement, json.dumps(metadata), tool_id)
                log.info(f"Database execute result: {result}")
                
                # Verify what was actually saved
                verify_query = f"SELECT mcp_config FROM {self.table_name} WHERE tool_id = $1"
                row = await conn.fetchrow(verify_query, tool_id)
                if row:
                    actual_config = row['mcp_config']
                    log.info(f"🔍 Verification query result - mcp_config in DB: {actual_config}")
                    log.info(f"🔍 server_type in DB: {actual_config.get('server_type') if isinstance(actual_config, dict) else 'NOT_DICT'}")
                else:
                    log.error(f"🔍 Verification failed - tool {tool_id} not found in DB")
            
            log.info(f"✅ Updated MCP config metadata for tool {tool_id}: type={server_type}, functions={len(functions)}")
            return True
        except Exception as e:
            log.error(f"❌ Error updating MCP config metadata for tool {tool_id}: {e}")
            import traceback
            log.error(f"Traceback: {traceback.format_exc()}")
            return False


# --- ToolAgentMappingRepository ---

class ToolAgentMappingRepository(BaseRepository, CacheableRepository):
    """
    Repository for the 'tool_agent_mapping_table'. Handles direct database interactions for tool-agent mappings.
    """

    def __init__(self, pool: asyncpg.Pool, login_pool: asyncpg.Pool, table_name: str = TableNames.TOOL_AGENT_MAPPING.value):
        """
        Initializes the ToolAgentMappingRepository.

        Args:
            pool (asyncpg.Pool): The asyncpg connection pool.
            login_pool (asyncpg.Pool): The asyncpg connection pool for login-related operations.
            table_name (str): The name of the tool-agent mapping table.
        """
        super().__init__(pool, login_pool, table_name)

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
                -- FOREIGN KEY(tool_id) REFERENCES {TableNames.TOOL.value}(tool_id) ON DELETE RESTRICT, -- REMOVED
                FOREIGN KEY(agentic_application_id) REFERENCES {TableNames.AGENT.value}(agentic_application_id) ON DELETE CASCADE
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
            await self.invalidate_all_method_cache("get_tool_agent_mappings_record")
            await self.invalidate_all_method_cache("get_agent_record", namespace="AgentRepository")
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
            updated_rows = [dict(row) for row in rows]
            await self._transform_emails_to_usernames(updated_rows, ['tool_created_by', 'agentic_app_created_by'])
            return updated_rows
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
                    await self.invalidate_all_method_cache("get_tool_agent_mappings_record")
                    await self.invalidate_all_method_cache("get_agent_record", namespace="AgentRepository")
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
                    await self.invalidate_all_method_cache("get_tool_agent_mappings_record")
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

    def __init__(self, pool: asyncpg.Pool, login_pool: asyncpg.Pool, table_name: str = TableNames.RECYCLE_TOOL.value):
        """
        Initializes the RecycleToolRepository.

        Args:
            pool (asyncpg.Pool): The asyncpg connection pool.
            login_pool (asyncpg.Pool): The asyncpg connection pool for login-related operations.
            table_name (str): The name of the recycle tools table.
        """
        super().__init__(pool, login_pool, table_name)


    async def create_table_if_not_exists(self):
        """
        Creates the 'recycle_tool' table if it doesn't already exist.
        """
        try:
            create_table_sql = f"""
            CREATE TABLE IF NOT EXISTS {self.table_name} (
                tool_id TEXT PRIMARY KEY,
                tool_name TEXT NOT NULL,
                tool_description TEXT,
                code_snippet TEXT,
                model_name TEXT,
                department_name TEXT DEFAULT 'General',
                created_by TEXT,
                created_on TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
                updated_on TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
                last_used TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
                is_public BOOLEAN DEFAULT FALSE,
                status TEXT DEFAULT 'pending',
                comments TEXT,
                approved_at TIMESTAMPTZ,
                approved_by TEXT,
                CHECK (status IN ('pending', 'approved', 'rejected')),
                UNIQUE (tool_name, department_name)
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
                    f"ALTER TABLE {self.table_name} ADD COLUMN IF NOT EXISTS last_used TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP",
                    f"ALTER TABLE {self.table_name} ADD COLUMN IF NOT EXISTS department_name TEXT DEFAULT 'General'",
                    f"ALTER TABLE {self.table_name} ALTER COLUMN created_on TYPE TIMESTAMPTZ",
                    f"ALTER TABLE {self.table_name} ALTER COLUMN updated_on TYPE TIMESTAMPTZ",
                    f"ALTER TABLE {self.table_name} ALTER COLUMN last_used TYPE TIMESTAMPTZ",
                    f"ALTER TABLE {self.table_name} ALTER COLUMN last_used SET DEFAULT CURRENT_TIMESTAMP",
                    f"DO $$ BEGIN "
                    f"IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = '{self.table_name}_status_check') THEN "
                    f"ALTER TABLE {self.table_name} ADD CONSTRAINT {self.table_name}_status_check CHECK (status IN ('pending', 'approved', 'rejected')); "
                    f"END IF; END $$;",
                    # Migration: Drop old unique constraint on tool_name only, add composite unique on (tool_name, department_name)
                    f"DO $$ BEGIN "
                    f"IF EXISTS (SELECT 1 FROM pg_constraint WHERE conname = '{self.table_name}_tool_name_key') THEN "
                    f"ALTER TABLE {self.table_name} DROP CONSTRAINT {self.table_name}_tool_name_key; "
                    f"END IF; END $$;",
                    f"DO $$ BEGIN "
                    f"IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = '{self.table_name}_tool_name_department_name_key') THEN "
                    f"ALTER TABLE {self.table_name} ADD CONSTRAINT {self.table_name}_tool_name_department_name_key UNIQUE (tool_name, department_name); "
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
        If the tool already exists in the recycle bin, updates the record.

        Args:
            tool_data (Dict[str, Any]): A dictionary containing the tool data to insert.

        Returns:
            bool: True if the record was inserted/updated successfully, False otherwise.
        """
        insert_query = f"""
        INSERT INTO {self.table_name} (tool_id, tool_name, tool_description, code_snippet, model_name, created_by, created_on, updated_on, last_used, department_name, is_public, status, comments, approved_at, approved_by)
        VALUES ($1, $2, $3, $4, $5, $6, $7, CURRENT_TIMESTAMP, $8, $9, $10, $11, $12, $13, $14)
        ON CONFLICT (tool_id) DO UPDATE SET 
            updated_on = CURRENT_TIMESTAMP,
            tool_description = EXCLUDED.tool_description,
            code_snippet = EXCLUDED.code_snippet,
            is_public = EXCLUDED.is_public,
            status = EXCLUDED.status,
            comments = EXCLUDED.comments;
        """
        try:
            async with self.pool.acquire() as conn:
                result = await conn.execute(
                    insert_query,
                    tool_data.get("tool_id"), tool_data.get("tool_name"), tool_data.get("tool_description"),
                    tool_data.get("code_snippet"), tool_data.get("model_name"), tool_data.get("created_by"),
                    tool_data.get("created_on"), tool_data.get("last_used"), tool_data.get("department_name"),
                    tool_data.get("is_public", False), tool_data.get("status", "pending"), 
                    tool_data.get("comments"), tool_data.get("approved_at"), tool_data.get("approved_by")
                )
            # Check if insert or update happened
            if result and ("INSERT" in result or "UPDATE" in result):
                log.info(f"Tool record {tool_data.get('tool_name')} inserted/updated in recycle bin successfully.")
                return True
            else:
                log.warning(f"Tool record {tool_data.get('tool_name')} - unexpected result: {result}")
                return False
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

    async def get_all_recycle_tool_records(self, department_name: str = None) -> List[Dict[str, Any]]:
        """
        Retrieves all tool records from the recycle bin, optionally filtered by department_name.

        Returns:
            List[Dict[str, Any]]: A list of dictionaries, each representing a recycled tool record.
        """
        query = f"SELECT * FROM {self.table_name}"
        params = []
        if department_name:
            query += " WHERE department_name = $1"
            params.append(department_name)
        query += " ORDER BY created_on DESC"
        try:
            async with self.pool.acquire() as conn:
                rows = await conn.fetch(query, *params)
            log.info(f"Retrieved {len(rows)} recycle tool records from '{self.table_name}'.")
            updated_rows = [dict(row) for row in rows]
            await self._transform_emails_to_usernames(updated_rows, ['created_by', 'approved_by'])
            return updated_rows
        except Exception as e:
            log.error(f"Error retrieving all recycle tool records: {e}")
            return []

    async def get_recycle_tool_record(self, tool_id: Optional[str] = None, tool_name: Optional[str] = None, department_name: str = None) -> Dict[str, Any] | None:
        """
        Retrieves a single tool record from the recycle bin by ID or name, optionally filtered by department_name.

        Args:
            tool_id (Optional[str]): The ID of the tool.
            tool_name (Optional[str]): The name of the tool.
            department_name (str): The department name to filter by.

        Returns:
            Dict[str, Any] | None: A dictionary representing the recycled tool record, or None if not found.
        """
        query = f"SELECT * FROM {self.table_name}"
        params = []
        where_clauses = []

        if tool_id:
            where_clauses.append(f"tool_id = ${len(params)+1}")
            params.append(tool_id)
        elif tool_name:
            where_clauses.append(f"tool_name = ${len(params)+1}")
            params.append(tool_name)
        else:
            log.warning("No tool_id or tool_name provided to get_recycle_tool_record.")
            return None

        if department_name:
            where_clauses.append(f"department_name = ${len(params)+1}")
            params.append(department_name)

        if where_clauses:
            query += " WHERE " + " AND ".join(where_clauses)

        try:
            async with self.pool.acquire() as conn:
                row = await conn.fetchrow(query, *params)
            if row:
                log.info(f"Recycle tool record '{tool_id or tool_name}' retrieved successfully.")
                row = dict(row)
                await self._transform_emails_to_usernames([row], ['created_by', 'approved_by'])
                return row
            else:
                log.info(f"Recycle tool record '{tool_id or tool_name}' not found.")
                return None
        except Exception as e:
            log.error(f"Error retrieving recycle tool record '{tool_id or tool_name}': {e}")
            return None



# --- RecycleMcpToolRepository ---
# --- CACHE NOT IMPLEMENTED FOR THIS CLASS ---
class RecycleMcpToolRepository(BaseRepository):
    """
    Repository for the 'recycle_mcp_tool' table. Handles direct database interactions for recycled MCP tools.
    """

    def __init__(self, pool: asyncpg.Pool, login_pool: asyncpg.Pool, table_name: str = TableNames.RECYCLE_MCP_TOOL.value):
        """
        Initializes the RecycleMcpToolRepository.

        Args:
            pool (asyncpg.Pool): The asyncpg connection pool.
            login_pool (asyncpg.Pool): The asyncpg connection pool for login-related operations.
            table_name (str): The name of the recycle MCP tools table.
        """
        super().__init__(pool, login_pool, table_name)


    async def create_table_if_not_exists(self):
        """
        Creates the 'recycle_mcp_tool' table if it doesn't already exist.
        """
        try:
            create_table_sql = f"""
            CREATE TABLE IF NOT EXISTS {self.table_name} (
                tool_id TEXT PRIMARY KEY,
                tool_name TEXT NOT NULL,
                tool_description TEXT,
                mcp_config JSONB NOT NULL,
                is_public BOOLEAN DEFAULT FALSE,
                status TEXT DEFAULT 'pending',
                comments TEXT,
                approved_at TIMESTAMPTZ,
                approved_by TEXT,
                created_by TEXT,
                created_on TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
                updated_on TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
                deleted_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
                department_name TEXT DEFAULT 'General',
                CONSTRAINT {self.table_name}_status_check CHECK (status IN ('pending', 'approved', 'rejected')),
                UNIQUE (tool_name, department_name)
            );
            """
            async with self.pool.acquire() as conn:
                await conn.execute(create_table_sql)
                # Add department_name column if it doesn't exist (for existing databases)
                await conn.execute(
                    f"ALTER TABLE {self.table_name} ADD COLUMN IF NOT EXISTS department_name TEXT DEFAULT 'General'"
                )
                # Migration: Drop old unique constraint on tool_name only, add composite unique on (tool_name, department_name)
                await conn.execute(
                    f"DO $$ BEGIN "
                    f"IF EXISTS (SELECT 1 FROM pg_constraint WHERE conname = '{self.table_name}_tool_name_key') THEN "
                    f"ALTER TABLE {self.table_name} DROP CONSTRAINT {self.table_name}_tool_name_key; "
                    f"END IF; END $$;"
                )
                await conn.execute(
                    f"DO $$ BEGIN "
                    f"IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = '{self.table_name}_tool_name_department_name_key') THEN "
                    f"ALTER TABLE {self.table_name} ADD CONSTRAINT {self.table_name}_tool_name_department_name_key UNIQUE (tool_name, department_name); "
                    f"END IF; END $$;"
                )
            log.info(f"Table '{self.table_name}' created successfully or already exists.")
        except Exception as e:
            log.error(f"Error creating table '{self.table_name}': {e}")

    async def is_mcp_tool_in_recycle_bin_record(self, tool_id: Optional[str] = None, tool_name: Optional[str] = None) -> bool:
        """
        Checks if an MCP tool exists in the recycle bin table by ID or name.

        Args:
            tool_id (Optional[str]): The ID of the MCP tool.
            tool_name (Optional[str]): The name of the MCP tool.

        Returns:
            bool: True if the MCP tool exists, False otherwise.
        """
        query = f"SELECT EXISTS(SELECT 1 FROM {self.table_name} WHERE tool_id = $1 OR tool_name = $2)"
        try:
            async with self.pool.acquire() as conn:
                exists = await conn.fetchval(query, tool_id, tool_name)
            log.info(f"Checked if MCP tool '{tool_id or tool_name}' exists in recycle bin: {exists}.")
            return exists
        except Exception as e:
            log.error(f"Error checking MCP tool '{tool_id or tool_name}' in recycle bin: {e}")
            return False

    async def insert_recycle_mcp_tool_record(self, tool_data: Dict[str, Any]) -> bool:
        """
        Inserts an MCP tool record into the recycle bin.
        If the tool already exists in the recycle bin, updates the deleted_at timestamp.

        Args:
            tool_data (Dict[str, Any]): A dictionary containing the MCP tool data to insert.

        Returns:
            bool: True if the record was inserted/updated successfully, False otherwise.
        """
        insert_query = f"""
        INSERT INTO {self.table_name} (
            tool_id, tool_name, tool_description, mcp_config,
            is_public, status, comments, approved_at, approved_by,
            created_by, created_on, updated_on, deleted_at, department_name
        ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, CURRENT_TIMESTAMP, $13)
        ON CONFLICT (tool_id) DO UPDATE SET 
            deleted_at = CURRENT_TIMESTAMP,
            updated_on = CURRENT_TIMESTAMP,
            tool_description = EXCLUDED.tool_description,
            mcp_config = EXCLUDED.mcp_config,
            is_public = EXCLUDED.is_public,
            status = EXCLUDED.status,
            comments = EXCLUDED.comments;
        """
        try:
            async with self.pool.acquire() as conn:
                result = await conn.execute(
                    insert_query,
                    tool_data.get("tool_id"),
                    tool_data.get("tool_name"),
                    tool_data.get("tool_description"),
                    json.dumps(tool_data.get("mcp_config")),
                    tool_data.get("is_public", False),
                    tool_data.get("status", "pending"),
                    tool_data.get("comments"),
                    tool_data.get("approved_at"),
                    tool_data.get("approved_by"),
                    tool_data.get("created_by"),
                    tool_data.get("created_on"),
                    tool_data.get("updated_on"),
                    tool_data.get("department_name")
                )
            # Check if insert or update happened (INSERT 0 1 or UPDATE 1)
            if result and ("INSERT" in result or "UPDATE" in result):
                log.info(f"MCP tool record {tool_data.get('tool_name')} inserted/updated in recycle bin successfully.")
                return True
            else:
                log.warning(f"MCP tool record {tool_data.get('tool_name')} - unexpected result: {result}")
                return False
        except Exception as e:
            log.error(f"Error inserting recycle MCP tool record {tool_data.get('tool_name')}: {e}")
            return False

    async def delete_recycle_mcp_tool_record(self, tool_id: str) -> bool:
        """
        Deletes an MCP tool record from the recycle bin by its ID.

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
                log.info(f"MCP tool record '{tool_id}' deleted successfully from recycle bin.")
                return True
            else:
                log.warning(f"MCP tool record '{tool_id}' not found in recycle bin, no deletion performed.")
                return False
        except Exception as e:
            log.error(f"Error deleting recycle MCP tool record '{tool_id}': {e}")
            return False

    async def get_all_recycle_mcp_tool_records(self, department_name: str = None) -> List[Dict[str, Any]]:
        """
        Retrieves all MCP tool records from the recycle bin, optionally filtered by department_name.

        Args:
            department_name (str): The department name to filter by.

        Returns:
            List[Dict[str, Any]]: A list of dictionaries, each representing a recycled MCP tool record.
        """
        query = f"SELECT * FROM {self.table_name}"
        params = []
        if department_name:
            query += " WHERE department_name = $1"
            params.append(department_name)
        query += " ORDER BY deleted_at DESC"
        try:
            async with self.pool.acquire() as conn:
                rows = await conn.fetch(query, *params)
            log.info(f"Retrieved {len(rows)} recycle MCP tool records from '{self.table_name}'.")
            updated_rows = [dict(row) for row in rows]
            await self._transform_emails_to_usernames(updated_rows, ['created_by', 'approved_by'])
            # Parse mcp_config from JSON
            for row in updated_rows:
                if row.get("mcp_config"):
                    try:
                        row["mcp_config"] = json.loads(row["mcp_config"]) if isinstance(row["mcp_config"], str) else row["mcp_config"]
                    except json.JSONDecodeError:
                        log.warning(f"Failed to parse mcp_config for tool_id {row.get('tool_id')}")
            return updated_rows
        except Exception as e:
            log.error(f"Error retrieving all recycle MCP tool records: {e}")
            return []

    async def get_recycle_mcp_tool_record(self, tool_id: Optional[str] = None, tool_name: Optional[str] = None, department_name: str = None) -> Dict[str, Any] | None:
        """
        Retrieves a single MCP tool record from the recycle bin by ID or name, optionally filtered by department_name.

        Args:
            tool_id (Optional[str]): The ID of the MCP tool.
            tool_name (Optional[str]): The name of the MCP tool.
            department_name (str): The department name to filter by.

        Returns:
            Dict[str, Any] | None: A dictionary representing the recycled MCP tool record, or None if not found.
        """
        query = f"SELECT * FROM {self.table_name}"
        params = []
        where_clauses = []

        if tool_id:
            where_clauses.append(f"tool_id = ${len(params)+1}")
            params.append(tool_id)
        elif tool_name:
            where_clauses.append(f"tool_name = ${len(params)+1}")
            params.append(tool_name)
        else:
            log.warning("No tool_id or tool_name provided to get_recycle_mcp_tool_record.")
            return None

        if department_name:
            where_clauses.append(f"department_name = ${len(params)+1}")
            params.append(department_name)

        if where_clauses:
            query += " WHERE " + " AND ".join(where_clauses)

        try:
            async with self.pool.acquire() as conn:
                row = await conn.fetchrow(query, *params)
            if row:
                log.info(f"Recycle MCP tool record '{tool_id or tool_name}' retrieved successfully.")
                row = dict(row)
                await self._transform_emails_to_usernames([row], ['created_by', 'approved_by'])
                # Parse mcp_config from JSON
                if row.get("mcp_config"):
                    try:
                        row["mcp_config"] = json.loads(row["mcp_config"]) if isinstance(row["mcp_config"], str) else row["mcp_config"]
                    except json.JSONDecodeError:
                        log.warning(f"Failed to parse mcp_config for tool_id {row.get('tool_id')}")
                return row
            else:
                log.info(f"Recycle MCP tool record '{tool_id or tool_name}' not found.")
                return None
        except Exception as e:
            log.error(f"Error retrieving recycle MCP tool record '{tool_id or tool_name}': {e}")
            return None



# --- Agent Repository ---

class AgentRepository(BaseRepository, CacheableRepository):
    """
    Repository for the 'agent_table'. Handles direct database interactions for agents.
    """

    def __init__(self, pool: asyncpg.Pool, login_pool: asyncpg.Pool, table_name: str = TableNames.AGENT.value):
        """
        Initializes the AgentRepository.

        Args:
            pool (asyncpg.Pool): The asyncpg connection pool.
            login_pool (asyncpg.Pool): The asyncpg connection pool for login-related operations.
            table_name (str): The name of the agents table.
        """
        super().__init__(pool, login_pool, table_name)


    async def create_table_if_not_exists(self):
        """
        Creates the 'agent_table' in PostgreSQL if it does not exist.
        """
        try:
            create_statement = f"""
            CREATE TABLE IF NOT EXISTS {self.table_name} (
                agentic_application_id TEXT PRIMARY KEY,
                agentic_application_name TEXT NOT NULL,
                agentic_application_description TEXT,
                agentic_application_workflow_description TEXT,
                agentic_application_type TEXT,
                model_name TEXT,
                system_prompt JSONB,
                tools_id JSONB,
                department_name TEXT DEFAULT 'General',
                created_by TEXT,     
                created_on TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
                updated_on TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
                last_used TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
                is_public BOOLEAN DEFAULT FALSE,
                status TEXT DEFAULT 'pending',
                comments TEXT,
                approved_at TIMESTAMPTZ,
                approved_by TEXT,
                CHECK (status IN ('pending', 'approved', 'rejected')),
                UNIQUE (agentic_application_name, department_name)
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
                    f"ALTER TABLE {self.table_name} ADD COLUMN IF NOT EXISTS last_used TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP",
                    f"ALTER TABLE {self.table_name} ADD COLUMN IF NOT EXISTS department_name TEXT DEFAULT 'General'",
                    f"ALTER TABLE {self.table_name} ALTER COLUMN last_used SET DEFAULT CURRENT_TIMESTAMP",
                    f"UPDATE {self.table_name} SET last_used = CURRENT_TIMESTAMP WHERE last_used IS NULL",
                    f"ALTER TABLE {self.table_name} ADD COLUMN IF NOT EXISTS validation_criteria JSONB DEFAULT '[]'",
                    f"ALTER TABLE {self.table_name} ADD COLUMN IF NOT EXISTS welcome_message TEXT DEFAULT 'Hello, how can I help you?'",
                    f"UPDATE {self.table_name} SET welcome_message = 'Hello, how can I help you?' WHERE welcome_message IS NULL",
                    f"DO $$ BEGIN "
                    f"IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = '{self.table_name}_status_check') THEN "
                    f"ALTER TABLE {self.table_name} ADD CONSTRAINT {self.table_name}_status_check CHECK (status IN ('pending', 'approved', 'rejected')); "
                    f"END IF; END $$;",
                    # Migration: Drop old unique constraint on agentic_application_name only, add composite unique on (agentic_application_name, department_name)
                    f"DO $$ BEGIN "
                    f"IF EXISTS (SELECT 1 FROM pg_constraint WHERE conname = '{self.table_name}_agentic_application_name_key') THEN "
                    f"ALTER TABLE {self.table_name} DROP CONSTRAINT {self.table_name}_agentic_application_name_key; "
                    f"END IF; END $$;",
                    f"DO $$ BEGIN "
                    f"IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = '{self.table_name}_name_department_key') THEN "
                    f"ALTER TABLE {self.table_name} ADD CONSTRAINT {self.table_name}_name_department_key UNIQUE (agentic_application_name, department_name); "
                    f"END IF; END $$;"
                ]

                for stmt in alter_statements:
                    await conn.execute(stmt)
                    
            log.info(f"Table '{self.table_name}' created successfully or already exists.")
        except Exception as e:
            log.error(f"Error creating table '{self.table_name}': {e}")

    async def get_agent_ids_by_creator(self, creator_email: str) -> List[asyncpg.Record]:
        query = f"""
            SELECT agentic_application_id
            FROM {self.table_name}
            WHERE created_by = $1;
        """
        async with self.pool.acquire() as conn:
            return await conn.fetch(query, creator_email)
        
    async def get_agent_name_by_creator(self, creator_email: str) -> List[asyncpg.Record]:
        query = f"""
            SELECT agentic_application_name
            FROM {self.table_name}
            WHERE created_by = $1;
        """
        async with self.pool.acquire() as conn:
            return await conn.fetch(query, creator_email)

    async def get_agent_names_by_department(self, department_name: str) -> List[asyncpg.Record]:
        """
        Get all agent names in a specific department.
        """
        query = f"""
            SELECT agentic_application_name
            FROM {self.table_name}
            WHERE department_name = $1;
        """
        async with self.pool.acquire() as conn:
            return await conn.fetch(query, department_name)

    async def get_agent_names_by_creator_and_department(self, creator_email: str, department_name: str) -> List[asyncpg.Record]:
        """
        Get agent names created by a specific user in a specific department.
        """
        query = f"""
            SELECT agentic_application_name
            FROM {self.table_name}
            WHERE created_by = $1 AND department_name = $2;
        """
        async with self.pool.acquire() as conn:
            return await conn.fetch(query, creator_email, department_name)

    async def save_agent_record(self, agent_data: Dict[str, Any]) -> bool:
        """
        Inserts a new agent record into the agent table.

        Args:
            agent_data (Dict[str, Any]): A dictionary containing the agent data.
                                        Expected keys: agentic_application_id, agentic_application_name,
                                        agentic_application_description, agentic_application_workflow_description,
                                        agentic_application_type, model_name, system_prompt (JSON dumped),
                                        tools_id (JSON dumped), created_by, department_name, created_on, updated_on, is_public.

        Returns:
            bool: True if the agent was inserted successfully, False if a unique violation occurred or on other error.
        """
        insert_statement = f"""
        INSERT INTO {self.table_name} (agentic_application_id, agentic_application_name, agentic_application_description, agentic_application_workflow_description, agentic_application_type, model_name, system_prompt, tools_id, created_by, department_name, created_on, updated_on, validation_criteria, welcome_message, is_public)
        VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14, $15)
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
                    agent_data.get("department_name"),
                    agent_data["created_on"],
                    agent_data["updated_on"],
                    agent_data.get("validation_criteria", "[]"),
                    agent_data.get("welcome_message", "Hello, how can I help you?"),
                    agent_data.get("is_public", False)
                )
            await self.invalidate_all_method_cache("get_agent_record")
            await self.invalidate_all_method_cache("get_agents_details_for_chat_records")
            await self.invalidate_all_method_cache("get_all_agent_records")
            log.info(f"Agent record {agent_data.get('agentic_application_name')} inserted successfully.")
            return True
        except asyncpg.UniqueViolationError:
            log.warning(f"Agent record {agent_data.get('agentic_application_name')} already exists (unique violation).")
            return False
        except Exception as e:
            log.error(f"Error saving agent record {agent_data.get('agentic_application_name')}: {e}")
            return False

    @CacheableRepository.cache(ttl=EXPIRY_TIME, namespace="AgentRepository")
    async def get_agent_record(self, agentic_application_id: Optional[str] = None, agentic_application_name: Optional[str] = None, agentic_application_type: Optional[str] = None, created_by: Optional[str] = None, department_name: str = None, include_public: bool = True) -> List[Dict[str, Any]]:
        """
        Retrieves a single agent record by ID, name, type, or creator.
        When department_name is specified and include_public is True, also returns the agent if it's public.

        Args:
            agentic_application_id (Optional[str]): The ID of the agent.
            agentic_application_name (Optional[str]): The name of the agent.
            agentic_application_type (Optional[str]): The type of the agent.
            created_by (Optional[str]): The creator's email ID.
            department_name (str): The department name to filter by.
            include_public (bool): Whether to include public agents from other departments. Defaults to True.

        Returns:
            List[Dict[str, Any]]: A list of dictionary representing the agent records, or an empty list if not found.
        """
        query = f"SELECT * FROM {self.table_name}"
        where_clauses = []
        params = []

        # Build filters for non-department fields
        filters = {
            "agentic_application_id": agentic_application_id,
            "agentic_application_name": agentic_application_name,
            "created_by": created_by,
            "agentic_application_type": agentic_application_type
        }

        param_idx = 1
        for field, value in filters.items():
            if value not in (None, ""):
                where_clauses.append(f"{field} = ${param_idx}")
                params.append(value)
                param_idx += 1

        # Handle department_name with include_public option
        if department_name:
            if include_public:
                where_clauses.append(f"(department_name = ${param_idx} OR is_public = TRUE)")
            else:
                where_clauses.append(f"department_name = ${param_idx}")
            params.append(department_name)

        if where_clauses:
            query += " WHERE " + " AND ".join(where_clauses)
        else:
            log.warning("No filter criteria provided to get_agent_record.")
            return []

        try:
            async with self.pool.acquire() as conn:
                rows = await conn.fetch(query, *params)

            updated_rows = [dict(row) for row in rows]
            await self._transform_emails_to_usernames(updated_rows, ['created_by', 'approved_by'])

            log.info(f"Retrieved {len(updated_rows)} agent records from '{self.table_name}'.")
            return updated_rows

        except Exception as e:
            log.error(f"Error retrieving agent record '{agentic_application_id or agentic_application_name}': {e}")
            return []

    async def get_agent_records_by_ids(self, agent_ids: List[str]) -> List[Dict[str, Any]]:
        """
        Batch fetch agent records (id, name, type) for a list of agent IDs.
        Returns only agents that exist in agent_table.
        """
        if not agent_ids:
            return []
        query = f"""
            SELECT agentic_application_id, agentic_application_name, agentic_application_type
            FROM {self.table_name}
            WHERE agentic_application_id = ANY($1::text[])
        """
        try:
            async with self.pool.acquire() as conn:
                rows = await conn.fetch(query, agent_ids)
            return [dict(row) for row in rows]
        except Exception as e:
            log.error(f"Error batch fetching agent records: {e}")
            return []

    @CacheableRepository.cache(ttl=EXPIRY_TIME, namespace="AgentRepository")
    async def get_all_agent_records(self, agentic_application_type: Optional[Union[str, List[str]]] = None, department_name: str = None, include_public: bool = True) -> List[Dict[str, Any]]:
        """
        Retrieves all agent records, optionally filtered by type.
        When department_name is specified and include_public is True, also includes public agents from other departments.

        Args:
            agentic_application_type (Optional[Union[str, List[str]]]): The type(s) of agent to filter by.
            department_name (str, optional): Filter by department name.
            include_public (bool): Whether to include public agents from other departments. Defaults to True.

        Returns:
            List[Dict[str, Any]]: A list of dictionaries, each representing an agent record.
        """
        # query = f"SELECT * FROM {self.table_name} WHERE  (status = 'approved' OR created_by = '{current_user_email.get(None)}')"
        columns_to_select = """
            agentic_application_id, agentic_application_name, agentic_application_description, 
            agentic_application_workflow_description, agentic_application_type, model_name, 
            system_prompt, tools_id, created_on, created_by, updated_on, last_used, is_public, 
            status, comments, approved_at, approved_by, department_name
        """
        query = f"SELECT {columns_to_select} FROM {self.table_name}"
        parameters = []
        conditions = []
        if agentic_application_type:
            if isinstance(agentic_application_type, str):
                agentic_application_type = [agentic_application_type]
            placeholders = ', '.join(f"${i+1}" for i in range(len(agentic_application_type)))
            # query += f" AND agentic_application_type IN ({placeholders})"
            conditions.append(f"agentic_application_type IN ({placeholders})")
            parameters.extend(agentic_application_type)
            
        
        if department_name:
            if include_public:
                conditions.append(f"(department_name = ${len(parameters)+1} OR is_public = TRUE)")
            else:
                conditions.append(f"department_name = ${len(parameters)+1}")
            parameters.append(department_name)
            
        
        if conditions:
            query += " WHERE " + " AND ".join(conditions)

        query += " ORDER BY created_on DESC"

        try:
            async with self.pool.acquire() as conn:
                rows = await conn.fetch(query, *parameters)
            log.info(f"Retrieved {len(rows)} agent records from '{self.table_name}'.")
            updated_rows = [dict(row) for row in rows]
            await self._transform_emails_to_usernames(updated_rows, ['created_by', 'approved_by'])
            return updated_rows
        except Exception as e:
            log.error(f"Error retrieving all agent records: {e}")
            return []

    async def get_all_agent_records_with_shared(
        self, 
        department_name: str, 
        shared_agent_ids: List[str] = None,
        include_public: bool = True,
        agentic_application_type: Optional[Union[str, List[str]]] = None
    ) -> List[Dict[str, Any]]:
        """
        Retrieves all agent records for a department including:
        1. Agents owned by the department
        2. Agents shared with the department (via sharing table)
        3. Public agents (is_public=True) from other departments (if include_public=True)

        Args:
            department_name (str): The department to get agents for.
            shared_agent_ids (List[str]): List of agent IDs shared with this department.
            include_public (bool): Whether to include public agents from other departments.
            agentic_application_type (Optional[Union[str, List[str]]]): The type(s) of agent to filter by.

        Returns:
            List[Dict[str, Any]]: A list of agent records with 'is_shared' and 'is_public_access' flags.
        """
        if not department_name:
            return await self.get_all_agent_records(agentic_application_type=agentic_application_type)

        shared_agent_ids = shared_agent_ids or []
        
        columns_to_select = """
            agentic_application_id, agentic_application_name, agentic_application_description, 
            agentic_application_workflow_description, agentic_application_type, model_name, 
            system_prompt, tools_id, created_on, created_by, updated_on, last_used, is_public, 
            status, comments, approved_at, approved_by, department_name
        """
        
        # Build query based on conditions
        params = []
        type_condition = ""
        
        if agentic_application_type:
            if isinstance(agentic_application_type, str):
                agentic_application_type = [agentic_application_type]
        
        if shared_agent_ids and include_public:
            query = f"""
            SELECT {columns_to_select}, 
                CASE 
                    WHEN department_name = $1 THEN FALSE
                    WHEN agentic_application_id = ANY($2) THEN TRUE
                    ELSE FALSE
                END as is_shared,
                CASE 
                    WHEN department_name != $1 AND is_public = TRUE AND agentic_application_id != ALL($2) THEN TRUE
                    ELSE FALSE
                END as is_public_access
            FROM {self.table_name}
            WHERE (department_name = $1 
               OR agentic_application_id = ANY($2)
               OR (is_public = TRUE AND department_name != $1))
            """
            params = [department_name, shared_agent_ids]
            param_idx = 3
        elif shared_agent_ids:
            query = f"""
            SELECT {columns_to_select}, 
                CASE WHEN department_name = $1 THEN FALSE ELSE TRUE END as is_shared,
                FALSE as is_public_access
            FROM {self.table_name}
            WHERE (department_name = $1 OR agentic_application_id = ANY($2))
            """
            params = [department_name, shared_agent_ids]
            param_idx = 3
        elif include_public:
            query = f"""
            SELECT {columns_to_select}, 
                FALSE as is_shared,
                CASE WHEN department_name != $1 AND is_public = TRUE THEN TRUE ELSE FALSE END as is_public_access
            FROM {self.table_name}
            WHERE (department_name = $1 OR (is_public = TRUE AND department_name != $1))
            """
            params = [department_name]
            param_idx = 2
        else:
            query = f"""
            SELECT {columns_to_select}, FALSE as is_shared, FALSE as is_public_access
            FROM {self.table_name}
            WHERE department_name = $1
            """
            params = [department_name]
            param_idx = 2

        # Add type filter if specified
        if agentic_application_type:
            placeholders = ', '.join(f"${i+param_idx}" for i in range(len(agentic_application_type)))
            query += f" AND agentic_application_type IN ({placeholders})"
            params.extend(agentic_application_type)

        query += """
            ORDER BY 
                CASE WHEN department_name = $1 THEN 0 ELSE 1 END,
                created_on DESC
        """

        try:
            async with self.pool.acquire() as conn:
                rows = await conn.fetch(query, *params)
            updated_rows = [dict(row) for row in rows]
            await self._transform_emails_to_usernames(updated_rows, ['created_by', 'approved_by'])
            log.info(f"Retrieved {len(rows)} agent records (including shared/public) for department '{department_name}'.")
            return updated_rows
        except Exception as e:
            log.error(f"Error retrieving agent records with shared: {e}")
            return []

    async def get_agents_by_search_or_page_records(self, search_value: str, limit: int, page: int, agentic_application_type: Optional[Union[str, List[str]]] = None, created_by: Optional[str] = None, department_name: str = None, shared_agent_ids: List[str] = None) -> List[Dict[str, Any]]:
        """
        Retrieves agent records with pagination and search filtering.
        Includes public agents and shared agents when department_name is specified.

        Args:
            search_value (str): The value to search for in agent names (case-insensitive, LIKE).
            limit (int): The maximum number of records to return.
            page (int): The page number (1-indexed).
            agentic_application_type (Optional[Union[str, List[str]]]): The type(s) of agent to filter by.
            created_by (Optional[str]): The creator's email ID to filter by.
            department_name (str): The department name to filter by (also includes public/shared agents).
            shared_agent_ids (List[str], optional): List of agent IDs shared with the department.

        Returns:
            List[Dict[str, Any]]: A list of dictionaries, each representing an agent record.
        """
        columns_to_select = """
            agentic_application_id, agentic_application_name, agentic_application_description, agentic_application_type,
            created_by, department_name, is_public
        """
        name_filter = f"%{search_value.lower()}%" if search_value else "%"
        offset = limit * max(0, page - 1)
        shared_agent_ids = shared_agent_ids or []

        query = f"""
            SELECT {columns_to_select} FROM {self.table_name}
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
        # Include own department agents OR public agents OR shared agents
        if department_name:
            if shared_agent_ids:
                query += f" AND (department_name = ${idx} OR is_public = TRUE OR agentic_application_id = ANY(${idx + 1}))"
                params.append(department_name)
                params.append(shared_agent_ids)
                # Order own department agents first
                query += f" ORDER BY CASE WHEN department_name = ${idx} THEN 0 ELSE 1 END, created_on DESC LIMIT ${idx + 2} OFFSET ${idx + 3}"
                params.extend([limit, offset])
            else:
                query += f" AND (department_name = ${idx} OR is_public = TRUE)"
                params.append(department_name)
                # Order own department agents first
                query += f" ORDER BY CASE WHEN department_name = ${idx} THEN 0 ELSE 1 END, created_on DESC LIMIT ${idx + 1} OFFSET ${idx + 2}"
                params.extend([limit, offset])
        else:
            query += f" ORDER BY created_on DESC LIMIT ${idx} OFFSET ${idx + 1}"
            params.extend([limit, offset])

        try:
            async with self.pool.acquire() as conn:
                rows = await conn.fetch(query, *params)
            log.info(f"Retrieved {len(rows)} agent records for search '{search_value}', page {page}.")
            updated_rows = [dict(row) for row in rows]
            await self._transform_emails_to_usernames(updated_rows, ['created_by'])
            return updated_rows
        except Exception as e:
            log.error(f"Error retrieving agent records by search/page: {e}")
            return []

    async def get_total_agent_count(self, search_value: str = '', agentic_application_type: Optional[Union[str, List[str]]] = None, created_by: Optional[str] = None, department_name: str = None, shared_agent_ids: List[str] = None) -> int:
        """
        Retrieves the total count of agent records, optionally filtered.
        Includes public agents and shared agents when department_name is specified.

        Args:
            search_value (str): The value to search for in agent names (case-insensitive, LIKE).
            agentic_application_type (Optional[Union[str, List[str]]]): The type(s) of agent to filter by.
            created_by (Optional[str]): The creator's email ID to filter by.
            department_name (str): The department name to filter by (also includes public/shared agents).
            shared_agent_ids (List[str], optional): List of agent IDs shared with the department.

        Returns:
            int: The total count of matching agent records.
        """
        name_filter = f"%{search_value.lower()}%" if search_value else "%"
        shared_agent_ids = shared_agent_ids or []
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
            idx += 1
        # Include own department agents OR public agents OR shared agents
        if department_name:
            if shared_agent_ids:
                query += f" AND (department_name = ${idx} OR is_public = TRUE OR agentic_application_id = ANY(${idx + 1}))"
                params.append(department_name)
                params.append(shared_agent_ids)
            else:
                query += f" AND (department_name = ${idx} OR is_public = TRUE)"
                params.append(department_name)

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
                await self.invalidate_all_method_cache("get_agent_record")
                await self.invalidate_all_method_cache("get_agents_details_for_chat_records")
                await self.invalidate_all_method_cache("get_all_agent_records")
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
                await self.invalidate_all_method_cache("get_agent_record")
                await self.invalidate_all_method_cache("get_agents_details_for_chat_records")
                await self.invalidate_all_method_cache("get_all_agent_records")
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
    async def get_agents_details_for_chat_records(self, department_name: str = None, shared_agent_ids: List[str] = None, include_public: bool = True) -> List[Dict[str, Any]]:
        """
        Retrieves basic agent details (ID, name, type) for chat purposes.
        When department_name is specified, also includes shared and public agents.
        No status filtering is applied.

        Args:
            department_name (str): The department to filter by.
            shared_agent_ids (List[str]): List of agent IDs shared with this department.
            include_public (bool): Whether to include public agents from other departments.

        Returns:
            List[Dict[str, Any]]: A list of dictionaries, each containing
                                  'agentic_application_id', 'agentic_application_name',
                                  'agentic_application_type', 'welcome_message', 'is_shared', and 'is_public_access'.
        """
        shared_agent_ids = shared_agent_ids or []
        
        if department_name:
            if shared_agent_ids and include_public:
                # Include own department + shared + public agents
                # Pattern from get_agents_by_search_or_page_records: (department_name = $1 OR is_public = TRUE OR agentic_application_id = ANY($2))
                query = f"""
                    SELECT agentic_application_id, agentic_application_name, agentic_application_type, welcome_message,
                        CASE WHEN agentic_application_id = ANY($2) AND department_name != $1 THEN TRUE ELSE FALSE END as is_shared,
                        CASE WHEN is_public = TRUE AND department_name != $1 AND NOT (agentic_application_id = ANY($2)) THEN TRUE ELSE FALSE END as is_public_access
                    FROM {self.table_name}
                    WHERE (department_name = $1 OR is_public = TRUE OR agentic_application_id = ANY($2))
                    ORDER BY CASE WHEN department_name = $1 THEN 0 ELSE 1 END, created_on DESC
                """
                params = [department_name, shared_agent_ids]
            elif shared_agent_ids:
                # Include own department + shared agents only
                query = f"""
                    SELECT agentic_application_id, agentic_application_name, agentic_application_type, welcome_message,
                        CASE WHEN agentic_application_id = ANY($2) AND department_name != $1 THEN TRUE ELSE FALSE END as is_shared,
                        FALSE as is_public_access
                    FROM {self.table_name}
                    WHERE (department_name = $1 OR agentic_application_id = ANY($2))
                    ORDER BY CASE WHEN department_name = $1 THEN 0 ELSE 1 END, created_on DESC
                """
                params = [department_name, shared_agent_ids]
            elif include_public:
                # Include own department + public agents
                query = f"""
                    SELECT agentic_application_id, agentic_application_name, agentic_application_type, welcome_message,
                        FALSE as is_shared,
                        CASE WHEN is_public = TRUE AND department_name != $1 THEN TRUE ELSE FALSE END as is_public_access
                    FROM {self.table_name}
                    WHERE (department_name = $1 OR is_public = TRUE)
                    ORDER BY CASE WHEN department_name = $1 THEN 0 ELSE 1 END, created_on DESC
                """
                params = [department_name]
            else:
                # Own department only
                query = f"""
                    SELECT agentic_application_id, agentic_application_name, agentic_application_type, welcome_message,
                        FALSE as is_shared, FALSE as is_public_access
                    FROM {self.table_name}
                    WHERE department_name = $1
                    ORDER BY created_on DESC
                """
                params = [department_name]
        else:
            # No department filter - return all
            query = f"""
                SELECT agentic_application_id, agentic_application_name, agentic_application_type, welcome_message,
                    FALSE as is_shared, FALSE as is_public_access
                FROM {self.table_name}
                ORDER BY created_on DESC
            """
            params = []

        log.debug(f"get_agents_details_for_chat_records query: {query}")
        log.debug(f"params: department_name={department_name}, shared_agent_ids={shared_agent_ids}, include_public={include_public}")
        
        try:
            async with self.pool.acquire() as conn:
                rows = await conn.fetch(query, *params)
            log.info(f"Retrieved {len(rows)} agent chat detail records from '{self.table_name}'.")
            return [dict(row) for row in rows]
        except Exception as e:
            log.error(f"Error retrieving agent chat detail records: {e}")
            return []
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
            updated_rows = [dict(row) for row in rows]
            await self._transform_emails_to_usernames(updated_rows, ['created_by', 'approved_by'])
            return updated_rows
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
            updated_rows = [dict(row) for row in rows]
            await self._transform_emails_to_usernames(updated_rows, ['created_by', 'approved_by'])
            return updated_rows
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
                await self.invalidate_all_method_cache("get_agent_record")
                await self.invalidate_all_method_cache("get_agents_details_for_chat_records")
                await self.invalidate_all_method_cache("get_all_agent_records")
                log.info(f"Agent '{agentic_application_id}' approved successfully by '{approved_by}' at {approval_time}.")
                return True
            else:
                log.warning(f"Agent '{agentic_application_id}' not found, no approval performed.")
                return False
        except Exception as e:
            log.error(f"Error approving agent '{agentic_application_id}': {e}")
            return False

    async def update_last_used_agent(self, agentic_application_id: str) -> bool:
        """
        Updates the last_used timestamp for an agent.

        Args:
            agentic_application_id (str): The ID of the agent to update.

        Returns:
            bool: True if the agent was updated successfully, False otherwise.
        """

        log.info(f"REPOSITORY: Attempting to update last_used for agentic_application_id: {agentic_application_id}")
        update_statement = f"""
        UPDATE {self.table_name} 
        SET last_used = $1
        WHERE agentic_application_id = $2
        """
        
        current_time_utc = datetime.now(timezone.utc)
        log.info(f"REPOSITORY: Using timestamp: {current_time_utc}")
        try:
            async with self.pool.acquire() as conn:
                log.info(f"REPOSITORY: Executing UPDATE query for agentic_application_id: {agentic_application_id}")
                result = await conn.execute(update_statement, current_time_utc, agentic_application_id)
                log.info(f"REPOSITORY: Update query result: {result}")
            if result != "UPDATE 0":
                log.info(f"SUCCESS REPOSITORY: Tool '{agentic_application_id}' last_used timestamp updated to {current_time_utc}.")
                return True
            else:
                log.warning(f"WARNING REPOSITORY: Tool '{agentic_application_id}' not found, no last_used update performed.")
                return False
        except Exception as e:
            log.error(f"ERROR REPOSITORY: Error updating last_used for tool '{agentic_application_id}': {e}")
            return False    
        
    async def find_agents_using_validator(self, validator_tool_id: str) -> List[Dict[str, Any]]:
        """
        Efficiently finds agents that reference a specific validator tool in their validation_criteria.
        Uses database LIKE query instead of loading and parsing all agents.

        Args:
            validator_tool_id (str): The ID of the validator tool to search for.

        Returns:
            List[Dict[str, Any]]: List of agent records that use this validator tool.
        """
        # Use PostgreSQL's JSON containment and text search capabilities
        # This is much faster than Python loops over all agents
        query = f"""
            SELECT agentic_application_id, agentic_application_name, created_by
            FROM {self.table_name}
            WHERE validation_criteria IS NOT NULL 
            AND validation_criteria::text LIKE $1
        """
        
        # Search for the validator ID in the JSON text
        search_pattern = f'%{validator_tool_id}%'
        
        try:
            async with self.pool.acquire() as conn:
                rows = await conn.fetch(query, search_pattern)
            
            # Filter to exact matches (LIKE might have false positives)
            exact_matches = []
            for row in rows:
                agent_dict = dict(row)
                # Get the validation_criteria and verify exact match
                agent_full = await self.get_agent_record(agentic_application_id=agent_dict['agentic_application_id'])
                if agent_full:
                    agent_data = agent_full[0]
                    validation_criteria = agent_data.get('validation_criteria')
                    if validation_criteria:
                        # Handle both string and already parsed JSON
                        if isinstance(validation_criteria, str):
                            try:
                                import json
                                validation_criteria = json.loads(validation_criteria)
                            except (json.JSONDecodeError, TypeError):
                                continue
                        
                        # Check for exact match
                        if isinstance(validation_criteria, list):
                            for criteria in validation_criteria:
                                validator_id = criteria.get('validator_tool_id') or criteria.get('validator')
                                if validator_id == validator_tool_id:
                                    exact_matches.append(agent_dict)
                                    break
            
            log.info(f"Found {len(exact_matches)} agents using validator tool '{validator_tool_id}'.")
            return exact_matches
            
        except Exception as e:
            log.error(f"Error finding agents using validator '{validator_tool_id}': {e}")
            return []
        


# --- RecycleAgentRepository ---
# --- CACHE NOT IMPLEMENTED FOR THIS CLASS ---
class RecycleAgentRepository(BaseRepository):
    """
    Repository for the 'recycle_agent' table. Handles direct database interactions for recycled agents.
    """

    def __init__(self, pool: asyncpg.Pool, login_pool: asyncpg.Pool, table_name: str = TableNames.RECYCLE_AGENT.value):
        """
        Initializes the RecycleAgentRepository.

        Args:
            pool (asyncpg.Pool): The asyncpg connection pool.
            login_pool (asyncpg.Pool): The asyncpg connection pool for login-related operations.
            table_name (str): The name of the recycle agents table.
        """
        super().__init__(pool, login_pool, table_name)


    async def create_table_if_not_exists(self):
        """
        Creates the 'recycle_agent' table if it does not exist.
        """
        try:
            create_statement = f"""
            CREATE TABLE IF NOT EXISTS {self.table_name} (
                agentic_application_id TEXT PRIMARY KEY,
                agentic_application_name TEXT NOT NULL,
                agentic_application_description TEXT,
                agentic_application_workflow_description TEXT,
                agentic_application_type TEXT,
                model_name TEXT,
                system_prompt JSONB,
                tools_id JSONB,
                department_name TEXT DEFAULT 'General',
                created_by TEXT,
                created_on TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
                updated_on TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
                last_used TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
                UNIQUE (agentic_application_name, department_name)
            );
            """

            async with self.pool.acquire() as conn:
                await conn.execute(create_statement)
                alter_statements = [
                    f"ALTER TABLE {self.table_name} ADD COLUMN IF NOT EXISTS last_used TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP",
                    f"ALTER TABLE {self.table_name} ADD COLUMN IF NOT EXISTS department_name TEXT DEFAULT 'General'",
                    # Migration: Drop old unique constraint on agentic_application_name only, add composite unique on (agentic_application_name, department_name)
                    f"DO $$ BEGIN "
                    f"IF EXISTS (SELECT 1 FROM pg_constraint WHERE conname = '{self.table_name}_agentic_application_name_key') THEN "
                    f"ALTER TABLE {self.table_name} DROP CONSTRAINT {self.table_name}_agentic_application_name_key; "
                    f"END IF; END $$;",
                    f"DO $$ BEGIN "
                    f"IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = '{self.table_name}_name_department_key') THEN "
                    f"ALTER TABLE {self.table_name} ADD CONSTRAINT {self.table_name}_name_department_key UNIQUE (agentic_application_name, department_name); "
                    f"END IF; END $$;"
                ]
                for stmt in alter_statements:
                    await conn.execute(stmt)
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
        INSERT INTO {self.table_name} (agentic_application_id, agentic_application_name, agentic_application_description, agentic_application_workflow_description, agentic_application_type, model_name, system_prompt, tools_id, created_by, created_on, last_used, department_name)
        VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12)
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
                    agent_data["created_by"], agent_data["created_on"], agent_data["last_used"], agent_data.get("department_name")
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

    async def get_all_recycle_agent_records(self, department_name: str = None) -> List[Dict[str, Any]]:
        """
        Retrieves all agent records from the recycle bin, optionally filtered by department_name.

        Returns:
            List[Dict[str, Any]]: A list of dictionaries, each representing a recycled agent record.
        """
        query = f"SELECT * FROM {self.table_name}"
        params = []
        if department_name:
            query += " WHERE department_name = $1"
            params.append(department_name)
        query += " ORDER BY created_on DESC"
        try:
            async with self.pool.acquire() as conn:
                rows = await conn.fetch(query, *params)
            log.info(f"Retrieved {len(rows)} recycle agent records from '{self.table_name}'.")
            updated_rows = [dict(row) for row in rows]
            await self._transform_emails_to_usernames(updated_rows, ['created_by'])
            return updated_rows
        except Exception as e:
            log.error(f"Error retrieving all recycle agent records: {e}")
            return []

    async def get_recycle_agent_record(self, agentic_application_id: Optional[str] = None, agentic_application_name: Optional[str] = None, department_name: str = None) -> Dict[str, Any] | None:
        """
        Retrieves a single agent record from the recycle bin by ID or name, optionally filtered by department_name.

        Args:
            agentic_application_id (Optional[str]): The ID of the agent.
            agentic_application_name (Optional[str]): The name of the agent.
            department_name (str): The department name to filter by.

        Returns:
            Dict[str, Any] | None: A dictionary representing the recycled agent record, or None if not found.
        """
        query = f"SELECT * FROM {self.table_name}"
        params = []
        where_clauses = []

        if agentic_application_id:
            where_clauses.append(f"agentic_application_id = ${len(params)+1}")
            params.append(agentic_application_id)
        elif agentic_application_name:
            where_clauses.append(f"agentic_application_name = ${len(params)+1}")
            params.append(agentic_application_name)
        else:
            log.warning("No agentic_application_id or agentic_application_name provided to get_recycle_agent_record.")
            return None

        if department_name:
            where_clauses.append(f"department_name = ${len(params)+1}")
            params.append(department_name)

        if where_clauses:
            query += " WHERE " + " AND ".join(where_clauses)

        try:
            async with self.pool.acquire() as conn:
                row = await conn.fetchrow(query, *params)
            if row:
                log.info(f"Recycle agent record '{agentic_application_id or agentic_application_name}' retrieved successfully.")
                row_dict = dict(row)
                await self._transform_emails_to_usernames([row_dict], ['created_by'])
                return row_dict
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
        self.checkpoints_table = TableNames.CHECKPOINTS.value
        self.checkpoint_blobs_table = TableNames.CHECKPOINT_BLOBS.value
        self.checkpoint_writes_table = TableNames.CHECKPOINT_WRITES.value

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


# --- FeedbackLearningRepository ---
# --- CACHE NOT IMPLEMENTED FOR THIS CLASS ---
class FeedbackLearningRepository(BaseRepository):
    """
    Repository for feedback data. Handles direct database interactions for
    'feedback_response' and 'agent_feedback' tables.
    """

    def __init__(self, pool: asyncpg.Pool,
                 login_pool: asyncpg.Pool,
                 feedback_table_name: str = TableNames.FEEDBACK_LEARNING.value,
                 agent_feedback_table_name: str = TableNames.AGENT_FEEDBACK.value):
        super().__init__(pool, login_pool, table_name=feedback_table_name)
        self.feedback_table_name = feedback_table_name
        self.agent_feedback_table_name = agent_feedback_table_name


    async def create_tables_if_not_exists(self):
        """
        Creates the 'feedback_response' and 'agent_feedback' tables if they don't exist.
        If feedback_response table exists, alters it to add the 'lesson' field if missing.
        Also migrates from boolean 'approved' column to text 'status' column if needed.
        Also migrates from boolean 'approved' column to text 'status' column if needed.
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
            department_name TEXT DEFAULT 'General',
            status TEXT DEFAULT 'pending',
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
        
        alter_table_lesson_query = f"""
        ALTER TABLE {self.feedback_table_name}
        ADD COLUMN IF NOT EXISTS lesson TEXT;
        """
        
        alter_table_department_query = f"""
        ALTER TABLE {self.feedback_table_name}
        ADD COLUMN IF NOT EXISTS department_name TEXT DEFAULT 'General';
        """
        
        # Migration: Add status column if not exists
        alter_table_add_status_query = f"""
        ALTER TABLE {self.feedback_table_name}
        ADD COLUMN IF NOT EXISTS status TEXT DEFAULT 'pending';
        """
        
        # Migration: Convert approved boolean to status text if approved column exists
        migrate_approved_to_status_query = f"""
        UPDATE {self.feedback_table_name}
        SET status = CASE 
            WHEN approved = TRUE THEN 'approve'
            ELSE 'pending'
        END
        WHERE status IS NULL OR status = 'pending';
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
                    await conn.execute(alter_table_lesson_query)
                    await conn.execute(alter_table_department_query)
                    
                    # Add status column and migrate from approved if needed
                    await conn.execute(alter_table_add_status_query)
                    
                    # Check if approved column exists and migrate data
                    approved_col_exists = await conn.fetchval(
                        f"SELECT EXISTS(SELECT 1 FROM information_schema.columns WHERE table_name = '{self.feedback_table_name}' AND column_name = 'approved')"
                    )
                    if approved_col_exists:
                        await conn.execute(migrate_approved_to_status_query)
                        log.info(f"Migrated 'approved' boolean values to 'status' text in {self.feedback_table_name} table.")
                    
                    log.info(f"Added 'lesson', 'department_name', and 'status' columns to {self.feedback_table_name} table if they were missing.")
                    
            log.info("Feedback storage tables created successfully or already exist.")
        except Exception as e:
            log.error(f"Error creating feedback storage tables: {e}")
            raise # Re-raise for service to handle

    async def insert_feedback_record(self, response_id: str, query: str, old_final_response: str, old_steps: str, feedback: str, new_final_response: str, new_steps: str, lesson: str, department_name: str = None, status: str = 'pending') -> bool:
        """
        Inserts a new feedback response record.
        status should be one of: 'pending', 'approve', 'reject'
        """
        insert_query = f"""
        INSERT INTO {self.feedback_table_name} (
            response_id, query, old_final_response, old_steps, feedback, new_final_response, new_steps, status, lesson, department_name
        ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10);
        """
        try:
            async with self.pool.acquire() as conn:
                await conn.execute(insert_query, response_id, query, old_final_response, old_steps, feedback, new_final_response, new_steps, status, lesson, department_name)
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

    async def get_approved_feedback_records(self, agent_id: str, department_name: str = None) -> List[Dict[str, Any]]:
        """
        Retrieves approved feedback records for a specific agent, optionally filtered by department_name.
        """
        select_query = f"""
        SELECT fr.response_id, fr.query, fr.old_final_response, fr.old_steps, fr.feedback, fr.new_final_response, fr.new_steps, fr.lesson, fr.status, fr.created_at, fr.department_name 
        FROM {self.feedback_table_name} fr
        INNER JOIN {self.agent_feedback_table_name} af ON fr.response_id = af.response_id
        WHERE af.agent_id = $1 AND fr.status = 'approve'"""
        
        params = [agent_id]
        if department_name:
            select_query += " AND fr.department_name = $2"
            params.append(department_name)
        
        select_query += ";"
        
        try:
            async with self.pool.acquire() as conn:
                rows = await conn.fetch(select_query, *params)
            log.info(f"Retrieved {len(rows)} approved feedback records for agent '{agent_id}' in department '{department_name}'")
            return [dict(row) for row in rows]
        except Exception as e:
            log.error(f"Error retrieving approved feedback records for agent '{agent_id}': {e}")
            return []

    async def get_all_feedback_records_by_agent(self, agent_id: str, department_name: str = None) -> List[Dict[str, Any]]:
        """
        Retrieves all feedback records (regardless of approval status) for a given agent, optionally filtered by department_name.
        """
        select_query = f"""
        SELECT af.response_id, fr.feedback, fr.status, fr.department_name, fr.lesson
        FROM {self.feedback_table_name} fr
        JOIN {self.agent_feedback_table_name} af ON fr.response_id = af.response_id
        WHERE af.agent_id = $1"""
        
        params = [agent_id]
        if department_name:
            select_query += " AND fr.department_name = $2"
            params.append(department_name)
        
        select_query += ";"
        try:
            async with self.pool.acquire() as conn:
                rows = await conn.fetch(select_query, *params)
            return [dict(row) for row in rows]
        except Exception as e:
            log.error(f"Error retrieving all feedback records for agent '{agent_id}': {e}")
            return []

    async def get_feedback_record_by_response_id(self, response_id: str, department_name: str = None) -> List[Dict[str, Any]]:
        """
        Retrieves a single feedback record by its response_id, optionally filtered by department_name.
        """
        select_query = f"""
        SELECT fr.response_id, fr.query, fr.old_final_response, fr.old_steps, fr.feedback, fr.new_final_response, fr.new_steps, fr.lesson, fr.status, fr.created_at, fr.department_name, af.agent_id FROM {self.feedback_table_name} fr
        JOIN {self.agent_feedback_table_name} af ON fr.response_id = af.response_id
        WHERE fr.response_id = $1"""
        
        params = [response_id]
        if department_name:
            select_query += " AND fr.department_name = $2"
            params.append(department_name)
        
        select_query += ";"
        try:
            async with self.pool.acquire() as conn:
                rows = await conn.fetch(select_query, *params)
            return [dict(row) for row in rows]
        except Exception as e:
            log.error(f"Error retrieving feedback record for response_id '{response_id}': {e}")
            return []

    async def get_distinct_agents_with_feedback(self, department_name: str = None) -> List[str]:
        """
        Retrieves a list of distinct agent_ids that have associated feedback, optionally filtered by department_name.
        """
        if department_name:
            select_query = f"""
            SELECT DISTINCT af.agent_id 
            FROM {self.agent_feedback_table_name} af
            JOIN {self.feedback_table_name} fr ON af.response_id = fr.response_id
            WHERE fr.department_name = $1;
            """
            params = [department_name]
        else:
            select_query = f"SELECT DISTINCT agent_id FROM {self.agent_feedback_table_name};"
            params = []
            
        try:
            async with self.pool.acquire() as conn:
                if params:
                    rows = await conn.fetch(select_query, *params)
                else:
                    rows = await conn.fetch(select_query)
            return [row['agent_id'] for row in rows]
        except Exception as e:
            log.error(f"Error retrieving distinct agents with feedback: {e}")
            return []

    async def update_feedback_record(self, response_id: str, update_data: Dict[str, Any], department_name: str= None) -> bool:
        """
        Updates fields in a feedback_response record, optionally filtered by department_name.
        `update_data` should be a dictionary of column_name: new_value.
        """
        if not update_data:
            return False

        set_clause = ', '.join([f"{key} = ${i+1}" for i, key in enumerate(update_data.keys())])
        values = list(update_data.values())
        values.append(response_id) # response_id parameter

        where_clause = f"response_id = ${len(values)}"
        if department_name:
            values.append(department_name)
            where_clause += f" AND department_name = ${len(values)}"

        update_query = f"""
        UPDATE {self.feedback_table_name}
        SET {set_clause}
        WHERE {where_clause};
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
        Migrates agent_id values in the agent_feedback table:
        - Replaces all hyphens with underscores in the prefix (everything before the last 32 characters).
        - Replaces all underscores with hyphens in the last 32 characters (UUID part).

        Returns:
            Dict[str, Any]: A dictionary indicating the status of the migration.
        """
        log.info(f"Starting full migration of agent_id in '{self.agent_feedback_table_name}'.")

        update_query = f"""
        UPDATE {self.agent_feedback_table_name}
        SET agent_id = 
            REPLACE(LEFT(agent_id, LENGTH(agent_id) - 32), '-', '_') || 
            REPLACE(RIGHT(agent_id, 32), '_', '-');
        """

        try:
            async with self.pool.acquire() as conn:
                result = await conn.execute(update_query)
                rows_updated = int(result.split()[-1])

                log.info(f"Migration complete for '{self.agent_feedback_table_name}'. {rows_updated} rows updated.")
                return {"status": "success", "message": f"Successfully migrated {rows_updated} agent_id records."}
        except Exception as e:
            log.error(f"Error during agent_id migration in '{self.agent_feedback_table_name}': {e}", exc_info=True)
            return {"status": "error", "message": f"Failed to migrate agent_id records: {e}"}

    async def get_all_feedback_records(self, department_name: str = None, agent_ids: List[str] = None) -> List[Dict[str, Any]]:
        """
        Retrieves all feedback records, optionally filtered by department_name and agent_ids.
        When agent_ids is provided, only returns feedback for those agents (e.g. agents that exist in main DB).
        """
        select_query = f"""
        SELECT fr.response_id, fr.query, fr.old_final_response, fr.old_steps, fr.feedback, 
               fr.new_final_response, fr.new_steps, fr.lesson, fr.status, fr.created_at, 
               fr.department_name, af.agent_id 
        FROM {self.feedback_table_name} fr
        JOIN {self.agent_feedback_table_name} af ON fr.response_id = af.response_id"""
        
        params = []
        conditions = []
        param_idx = 1
        if department_name:
            conditions.append(f"fr.department_name = ${param_idx}")
            params.append(department_name)
            param_idx += 1
        if agent_ids:
            conditions.append(f"af.agent_id = ANY(${param_idx}::text[])")
            params.append(agent_ids)
        if conditions:
            select_query += " WHERE " + " AND ".join(conditions)
        select_query += " ORDER BY fr.created_at DESC;"
        
        try:
            async with self.pool.acquire() as conn:
                if params:
                    rows = await conn.fetch(select_query, *params)
                else:
                    rows = await conn.fetch(select_query)
            return [dict(row) for row in rows]
        except Exception as e:
            log.error(f"Error retrieving all feedback records: {e}")
            return []

    async def get_total_feedback_count(self, department_name: str = None, agent_ids: List[str] = None) -> int:
        """
        Returns the total count of feedback records, optionally filtered by department_name and agent_ids.
        """
        if agent_ids is not None and len(agent_ids) == 0:
            return 0
        select_query = f"SELECT COUNT(*) FROM {self.feedback_table_name} fr JOIN {self.agent_feedback_table_name} af ON fr.response_id = af.response_id"
        params = []
        conditions = []
        param_idx = 1
        if department_name:
            conditions.append(f"fr.department_name = ${param_idx}")
            params.append(department_name)
            param_idx += 1
        if agent_ids:
            conditions.append(f"af.agent_id = ANY(${param_idx}::text[])")
            params.append(agent_ids)
        if conditions:
            select_query += " WHERE " + " AND ".join(conditions)
        select_query += ";"
        try:
            async with self.pool.acquire() as conn:
                if params:
                    count = await conn.fetchval(select_query, *params)
                else:
                    count = await conn.fetchval(select_query)
            return count or 0
        except Exception as e:
            log.error(f"Error retrieving total feedback count: {e}")
            return 0

    async def get_approved_feedback_count(self, department_name: str = None, agent_ids: List[str] = None) -> int:
        """
        Returns the count of approved feedback records, optionally filtered by department_name and agent_ids.
        """
        if agent_ids is not None and len(agent_ids) == 0:
            return 0
        select_query = f"SELECT COUNT(*) FROM {self.feedback_table_name} fr JOIN {self.agent_feedback_table_name} af ON fr.response_id = af.response_id WHERE fr.approved = TRUE"
        params = []
        conditions = []
        param_idx = 1
        if department_name:
            conditions.append(f"fr.department_name = ${param_idx}")
            params.append(department_name)
            param_idx += 1
        if agent_ids:
            conditions.append(f"af.agent_id = ANY(${param_idx}::text[])")
            params.append(agent_ids)
        if conditions:
            select_query += " AND " + " AND ".join(conditions)
        select_query += ";"
        try:
            async with self.pool.acquire() as conn:
                if params:
                    count = await conn.fetchval(select_query, *params)
                else:
                    count = await conn.fetchval(select_query)
            return count or 0
        except Exception as e:
            log.error(f"Error retrieving approved feedback count: {e}")
            return 0

    async def get_pending_feedback_count(self, department_name: str = None, agent_ids: List[str] = None) -> int:
        """
        Returns the count of pending (not approved) feedback records, optionally filtered by department_name and agent_ids.
        """
        if agent_ids is not None and len(agent_ids) == 0:
            return 0
        select_query = f"SELECT COUNT(*) FROM {self.feedback_table_name} fr JOIN {self.agent_feedback_table_name} af ON fr.response_id = af.response_id WHERE fr.approved = FALSE"
        params = []
        conditions = []
        param_idx = 1
        if department_name:
            conditions.append(f"fr.department_name = ${param_idx}")
            params.append(department_name)
            param_idx += 1
        if agent_ids:
            conditions.append(f"af.agent_id = ANY(${param_idx}::text[])")
            params.append(agent_ids)
        if conditions:
            select_query += " AND " + " AND ".join(conditions)
        select_query += ";"
        try:
            async with self.pool.acquire() as conn:
                if params:
                    count = await conn.fetchval(select_query, *params)
                else:
                    count = await conn.fetchval(select_query)
            return count or 0
        except Exception as e:
            log.error(f"Error retrieving pending feedback count: {e}")
            return 0

    async def get_rejected_feedback_count(self, department_name: str = None) -> int:
        """
        Returns the count of rejected feedback records, optionally filtered by department_name.
        """
        select_query = f"SELECT COUNT(*) FROM {self.feedback_table_name} WHERE status = 'reject'"
        params = []
        if department_name:
            select_query += " AND department_name = $1"
            params.append(department_name)
        select_query += ";"
        
        try:
            async with self.pool.acquire() as conn:
                if params:
                    count = await conn.fetchval(select_query, *params)
                else:
                    count = await conn.fetchval(select_query)
            return count or 0
        except Exception as e:
            log.error(f"Error retrieving rejected feedback count: {e}")
            return 0

    async def get_rejected_feedback_count(self, department_name: str = None) -> int:
        """
        Returns the count of rejected feedback records, optionally filtered by department_name.
        """
        select_query = f"SELECT COUNT(*) FROM {self.feedback_table_name} WHERE status = 'reject'"
        params = []
        if department_name:
            select_query += " AND department_name = $1"
            params.append(department_name)
        select_query += ";"
        
        try:
            async with self.pool.acquire() as conn:
                if params:
                    count = await conn.fetchval(select_query, *params)
                else:
                    count = await conn.fetchval(select_query)
            return count or 0
        except Exception as e:
            log.error(f"Error retrieving rejected feedback count: {e}")
            return 0

    async def get_agents_with_feedback_count(self, department_name: str = None, agent_ids: List[str] = None) -> int:
        """
        Returns the count of distinct agents that have associated feedback, optionally filtered by department_name and agent_ids.
        """
        if agent_ids is not None and len(agent_ids) == 0:
            return 0
        select_query = f"""
            SELECT COUNT(DISTINCT af.agent_id) 
            FROM {self.agent_feedback_table_name} af
            JOIN {self.feedback_table_name} fr ON af.response_id = fr.response_id"""
        params = []
        conditions = []
        param_idx = 1
        if department_name:
            conditions.append(f"fr.department_name = ${param_idx}")
            params.append(department_name)
            param_idx += 1
        if agent_ids:
            conditions.append(f"af.agent_id = ANY(${param_idx}::text[])")
            params.append(agent_ids)
        if conditions:
            select_query += " WHERE " + " AND ".join(conditions)
        select_query += ";"
        try:
            async with self.pool.acquire() as conn:
                if params:
                    count = await conn.fetchval(select_query, *params)
                else:
                    count = await conn.fetchval(select_query)
            return count or 0
        except Exception as e:
            log.error(f"Error retrieving agents with feedback count: {e}")
            return 0

    async def get_feedback_stats(self, department_name: str = None, agent_ids: List[str] = None) -> Dict[str, Any]:
        """
        Returns aggregated feedback statistics including total, approved, pending, rejected counts and agent count.
        Returns aggregated feedback statistics including total, approved, pending, rejected counts and agent count.
        """
        try:
            total_count = await self.get_total_feedback_count(department_name)
            approved_count = await self.get_approved_feedback_count(department_name)
            pending_count = await self.get_pending_feedback_count(department_name)
            rejected_count = await self.get_rejected_feedback_count(department_name)
            rejected_count = await self.get_rejected_feedback_count(department_name)
            agents_count = await self.get_agents_with_feedback_count(department_name)
            
            return {
                "total_feedback": total_count,
                "approved_feedback": approved_count,
                "pending_feedback": pending_count,
                "rejected_feedback": rejected_count,
                "rejected_feedback": rejected_count,
                "agents_with_feedback": agents_count
            }
        except Exception as e:
            log.error(f"Error retrieving feedback stats: {e}")
            return {
                "total_feedback": 0,
                "approved_feedback": 0,
                "pending_feedback": 0,
                "rejected_feedback": 0,
                "rejected_feedback": 0,
                "agents_with_feedback": 0
            }

    async def delete_feedback_by_agent_id(self, agent_id: str) -> Dict[str, Any]:
        """
        Deletes all feedback/learning records for a specific agent.
        
        This method:
        1. Retrieves all response_ids associated with the agent_id from agent_feedback table
        2. Deletes those records from feedback_response table (cascades to agent_feedback)
        
        Args:
            agent_id (str): The ID of the agent whose feedback records should be deleted.
            
        Returns:
            Dict[str, Any]: A dictionary with status and count of deleted records.
        """
        # First, get all response_ids for this agent
        get_response_ids_query = f"""
        SELECT response_id FROM {self.agent_feedback_table_name}
        WHERE agent_id = $1;
        """
        
        try:
            async with self.pool.acquire() as conn:
                # Get all response_ids for this agent
                rows = await conn.fetch(get_response_ids_query, agent_id)
                response_ids = [row['response_id'] for row in rows]
                
                if not response_ids:
                    log.info(f"No feedback records found for agent_id '{agent_id}'.")
                    return {
                        "status": "success",
                        "message": f"No feedback records found for agent_id '{agent_id}'.",
                        "deleted_count": 0
                    }
                
                # Delete from feedback_response table (CASCADE will handle agent_feedback)
                delete_query = f"""
                DELETE FROM {self.feedback_table_name}
                WHERE response_id = ANY($1);
                """
                result = await conn.execute(delete_query, response_ids)
                deleted_count = int(result.split()[-1])
                
                log.info(f"Successfully deleted {deleted_count} feedback records for agent_id '{agent_id}'.")
                return {
                    "status": "success",
                    "message": f"Successfully deleted {deleted_count} feedback records for agent_id '{agent_id}'.",
                    "deleted_count": deleted_count
                }
        except Exception as e:
            log.error(f"Error deleting feedback records for agent_id '{agent_id}': {e}", exc_info=True)
            return {
                "status": "error",
                "message": f"Failed to delete feedback records: {e}",
                "deleted_count": 0
            }

    async def delete_orphaned_feedback_records(self) -> Dict[str, Any]:
        """
        Deletes feedback records where the associated agent_id no longer exists 
        in either the agent table or the recycle_agent table.
        
        This method:
        1. Gets all distinct agent_ids from the agent_feedback table
        2. Identifies orphaned agent_ids (not in agent_table or recycle_agent)
        3. Deletes feedback records for those orphaned agent_ids
        
        Returns:
            Dict[str, Any]: A dictionary with status, message, deleted count, and orphaned agent_ids.
        """
        log.info("Starting cleanup of orphaned feedback records.")
        
        # Query to find orphaned agent_ids (not in agent_table or recycle_agent)
        get_orphaned_agents_query = f"""
        SELECT DISTINCT af.agent_id 
        FROM {self.agent_feedback_table_name} af
        WHERE NOT EXISTS (
            SELECT 1 FROM {TableNames.AGENT.value} a 
            WHERE a.agentic_application_id = af.agent_id
        )
        AND NOT EXISTS (
            SELECT 1 FROM {TableNames.RECYCLE_AGENT.value} ra 
            WHERE ra.agentic_application_id = af.agent_id
        );
        """
        
        try:
            async with self.pool.acquire() as conn:
                # Get all orphaned agent_ids
                rows = await conn.fetch(get_orphaned_agents_query)
                orphaned_agent_ids = [row['agent_id'] for row in rows]
                
                if not orphaned_agent_ids:
                    log.info("No orphaned feedback records found.")
                    return {
                        "status": "success",
                        "message": "No orphaned feedback records found.",
                        "deleted_count": 0,
                        "orphaned_agent_ids": []
                    }
                
                log.info(f"Found {len(orphaned_agent_ids)} orphaned agent_ids: {orphaned_agent_ids}")
                
                # Get all response_ids for orphaned agents
                get_response_ids_query = f"""
                SELECT response_id FROM {self.agent_feedback_table_name}
                WHERE agent_id = ANY($1);
                """
                response_rows = await conn.fetch(get_response_ids_query, orphaned_agent_ids)
                response_ids = [row['response_id'] for row in response_rows]
                
                if not response_ids:
                    log.info("No feedback response records to delete.")
                    return {
                        "status": "success",
                        "message": "No feedback response records to delete.",
                        "deleted_count": 0,
                        "orphaned_agent_ids": orphaned_agent_ids
                    }
                
                # Delete from feedback_response table (CASCADE will handle agent_feedback)
                delete_query = f"""
                DELETE FROM {self.feedback_table_name}
                WHERE response_id = ANY($1);
                """
                result = await conn.execute(delete_query, response_ids)
                deleted_count = int(result.split()[-1])
                
                log.info(f"Successfully deleted {deleted_count} orphaned feedback records for {len(orphaned_agent_ids)} orphaned agents.")
                return {
                    "status": "success",
                    "message": f"Successfully deleted {deleted_count} orphaned feedback records for {len(orphaned_agent_ids)} orphaned agents.",
                    "deleted_count": deleted_count,
                    "orphaned_agent_ids": orphaned_agent_ids
                }
        except Exception as e:
            log.error(f"Error deleting orphaned feedback records: {e}", exc_info=True)
            return {
                "status": "error",
                "message": f"Failed to delete orphaned feedback records: {e}",
                "deleted_count": 0,
                "orphaned_agent_ids": []
            }


# ---------------------------111---------------------------------------
# --- EvaluationDataRepository ---
# --- CACHE NOT IMPLEMENTED FOR THIS CLASS ---
class EvaluationDataRepository(BaseRepository):
    """
    Repository for 'evaluation_data' table. Handles direct database interactions.
    """

    def __init__(self, pool: asyncpg.Pool, login_pool: asyncpg.Pool, agent_repo: AgentRepository,  table_name: str = TableNames.EVALUATION_DATA.value):
        super().__init__(pool, login_pool, table_name)
        self.agent_repo = agent_repo


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
            evaluation_status TEXT DEFAULT 'unprocessed',
            department_name TEXT DEFAULT 'General'
        );
        """
        
        # ALTER TABLE statements for existing databases
        alter_statements = [
            f"ALTER TABLE {self.table_name} ADD COLUMN IF NOT EXISTS department_name TEXT DEFAULT 'General';"
        ]
        
        try:
            async with self.pool.acquire() as conn:
                await conn.execute(create_table_query)
                # Execute ALTER statements for existing databases
                for stmt in alter_statements:
                    await conn.execute(stmt)
            log.info(f"Table '{self.table_name}' created or updated successfully.")
        except Exception as e:
            log.error(f"Error creating or updating table '{self.table_name}': {e}")
            raise

    async def insert_evaluation_record(self, data: Dict[str, Any]) -> bool:
        """
        Inserts a new evaluation data record.
        """
        insert_query = f"""
        INSERT INTO {self.table_name} (
            session_id, query, response, model_used,
            agent_id, agent_name, agent_type, agent_goal,
            workflow_description, tool_prompt, steps, executor_messages, department_name
        ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13);
        """
        try:
            async with self.pool.acquire() as conn:
                await conn.execute(
                    insert_query,
                    data.get("session_id"), data.get("query"), data.get("response"), data.get("model_used"),
                    data.get("agent_id"), data.get("agent_name"), data.get("agent_type"), data.get("agent_goal"),
                    data.get("workflow_description"), data.get("tool_prompt"),
                    data.get("steps"),
                    data.get("executor_messages"),
                    data.get("department_name", "General")
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
                id, query, response, agent_goal, agent_name,agent_type,
                workflow_description, steps, executor_messages, tool_prompt, model_used,
                session_id, agent_id, department_name
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
  
    async def get_unprocessed_record_by_department(self, department_name: str) -> Dict[str, Any] | None:
        """
        Retrieves the next unprocessed evaluation record for a specific department.
        Used by Admin users to access records in their department.
        """
        query = f"""
            SELECT
                id, query, response, agent_goal, agent_name, agent_type,
                workflow_description, steps, executor_messages, tool_prompt, model_used,
                session_id, agent_id, department_name
            FROM {self.table_name}
            WHERE evaluation_status = 'unprocessed'
            AND department_name = $1
            ORDER BY time_stamp
            LIMIT 1;
        """
        try:
            async with self.pool.acquire() as conn:
                row = await conn.fetchrow(query, department_name)
            return dict(row) if row else None
        except Exception as e:
            log.error(f"Error fetching unprocessed record by department {department_name}: {e}")
            return None

    async def count_unprocessed_records_by_department(self, department_name: str) -> int:
        """
        Counts unprocessed evaluation records for a specific department.
        Used by Admin users to count records in their department.
        """
        query = f"""
            SELECT COUNT(*) FROM {self.table_name}
            WHERE evaluation_status = 'unprocessed'
            AND department_name = $1;
        """
        try:
            async with self.pool.acquire() as conn:
                return await conn.fetchval(query, department_name)
        except Exception as e:
            log.error(f"Error counting unprocessed records by department {department_name}: {e}")
            return 0

    async def get_unprocessed_record_by_creator(self, creator_email: str) -> Dict[str, Any] | None:
        """
        Retrieves the next unprocessed evaluation record for agents created by the given user.
        """
        try:
            # Step 1: Get agent IDs from the agent DB
            log.info(f"Calling get_agent_ids_by_creator for: {creator_email}")
            agent_ids_result = await self.agent_repo.get_agent_ids_by_creator(creator_email)
            log.info(f"Received agent IDs: {[row['agentic_application_id'] for row in agent_ids_result]}")

            # agent_ids_result = await self.agent_repo.get_agent_ids_by_creator(creator_email)
            agent_ids = [row["agentic_application_id"] for row in agent_ids_result]

            if not agent_ids:
                log.info(f"No agents found for user {creator_email}")
                return None

            # Step 2: Query evaluation DB for matching unprocessed records
            query = f"""
                SELECT
                    id, query, response, agent_goal, agent_name, agent_type,
                    workflow_description, steps, executor_messages, tool_prompt, model_used,
                    session_id, agent_id, department_name
                FROM {self.table_name}
                WHERE evaluation_status = 'unprocessed'
                AND agent_id = ANY($1::text[])
                ORDER BY time_stamp
                LIMIT 1;
            """
            async with self.pool.acquire() as conn:
                row = await conn.fetchrow(query, agent_ids)

            return dict(row) if row else None

        except Exception as e:
            log.error(f"Error fetching unprocessed record by creator: {e}")
            return None

    async def count_all_unprocessed_records(self) -> int:
        query = f"""
            SELECT COUNT(*) FROM {self.table_name}
            WHERE evaluation_status = 'unprocessed';
        """
        async with self.pool.acquire() as conn:
            return await conn.fetchval(query)
        

    async def count_unprocessed_records_by_agent_ids(self, agent_ids: List[str]) -> int:
        if not agent_ids:
            return 0
        query = f"""
            SELECT COUNT(*) FROM {self.table_name}
            WHERE evaluation_status = 'unprocessed'
            AND agent_id = ANY($1::text[]);
        """
        async with self.pool.acquire() as conn:
            return await conn.fetchval(query, agent_ids)

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

  
    async def get_records_by_agent_names(
        self,
        user: Optional[User],
        agent_names: Optional[List[str]] = None,
        agent_types: Optional[List[str]] = None,
        page: int = 1,
        limit: int = 10
    ) -> List[Dict[str, Any]]:
        """
        Retrieves evaluation data records, optionally filtered by agent names and types.
        - SuperAdmin can access all records across all departments
        - Admin can access all records in their department
        - Regular users can only access records for agents they created
        """
        try:
            offset = (page - 1) * limit
            query = f"""
                SELECT id, session_id, query, response, model_used, agent_id, agent_name, agent_type, evaluation_status
                FROM {self.table_name}
            """
            params = []
            conditions = []

            # Apply filtering based on user role and permissions
            if user:
                if user.role == UserRole.SUPER_ADMIN:
                    # SuperAdmin can see all records - no additional filtering
                    log.info(f"SuperAdmin {user.email} accessing all evaluation records")
                    if agent_names:
                        conditions.append(f"agent_name = ANY(${len(params)+1}::text[])")
                        params.append(agent_names)
                    if agent_types:
                        conditions.append(f"agent_type = ANY(${len(params)+1}::text[])")
                        params.append(agent_types)
                        
                elif user.role == UserRole.ADMIN:
                    # Admin can see all records in their department
                    log.info(f"Admin {user.email} accessing department records: {user.department_name}")
                    
                    # Add department filter
                    conditions.append(f"department_name = ${len(params)+1}")
                    params.append(user.department_name)
                    
                    if agent_names:
                        conditions.append(f"agent_name = ANY(${len(params)+1}::text[])")
                        params.append(agent_names)
                    if agent_types:
                        conditions.append(f"agent_type = ANY(${len(params)+1}::text[])")
                        params.append(agent_types)
                    
                else:
                    # Regular users can only see records for agents they created and in their department
                    log.info(f"User {user.email} accessing own agent records")
                    
                    # Add department filter for regular users
                    conditions.append(f"department_name = ${len(params)+1}")
                    params.append(user.department_name)
                    
                    agent_names_result = await self.agent_repo.get_agent_names_by_creator_and_department(
                        user.email, user.department_name
                    )
                    owned_agent_names = [row["agentic_application_name"] for row in agent_names_result]

                    if not owned_agent_names:
                        log.warning(f"No agents found for user {user.email} in department {user.department_name}")
                        return []

                    # If agent_names is provided, filter only those that the user owns
                    if agent_names:
                        filtered_agent_names = list(set(agent_names) & set(owned_agent_names))
                        if not filtered_agent_names:
                            log.warning(f"User {user.email} does not own any of the requested agent names: {agent_names}")
                            return []
                        conditions.append(f"agent_name = ANY(${len(params)+1}::text[])")
                        params.append(filtered_agent_names)
                    else:
                        conditions.append(f"agent_name = ANY(${len(params)+1}::text[])")
                        params.append(owned_agent_names)
                    
                    if agent_types:
                        conditions.append(f"agent_type = ANY(${len(params)+1}::text[])")
                        params.append(agent_types)

            # Build WHERE clause from conditions
            if conditions:
                query += " WHERE " + " AND ".join(conditions)

            # Add pagination
            limit_param_index = len(params) + 1
            offset_param_index = len(params) + 2
            query += f" ORDER BY id DESC LIMIT ${limit_param_index} OFFSET ${offset_param_index};"
            params.extend([limit, offset])

            log.debug(f"Executing query: {query} with params: {params}")

            # Execute query
            async with self.pool.acquire() as conn:
                rows = await conn.fetch(query, *params)

            return [dict(row) for row in rows]

        except Exception as e:
            log.error(f"Error fetching evaluation data records: {e}")
            return []


# ---------------------------222---------------------------------------
# --- ToolEvaluationMetricsRepository ---
# --- CACHE NOT IMPLEMENTED FOR THIS CLASS ---
class ToolEvaluationMetricsRepository(BaseRepository):
    """
    Repository for 'tool_evaluation_metrics' table. Handles direct database interactions.
    """

    def __init__(self, pool: asyncpg.Pool, login_pool: asyncpg.Pool, agent_repo: AgentRepository, table_name: str = TableNames.TOOL_EVALUATION_METRICS.value):
        super().__init__(pool, login_pool, table_name)
        self.agent_repo = agent_repo


    async def create_table_if_not_exists(self):
        """Creates the 'tool_evaluation_metrics' table if it does not exist."""
        create_table_query = f"""
        CREATE TABLE IF NOT EXISTS {self.table_name} (
            id SERIAL PRIMARY KEY,
            evaluation_id INTEGER REFERENCES {TableNames.EVALUATION_DATA.value}(id) ON DELETE CASCADE,
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
            department_name TEXT DEFAULT 'General',
            time_stamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        """
        
        # ALTER TABLE statements for existing databases
        alter_statements = [
            f"ALTER TABLE {self.table_name} ADD COLUMN IF NOT EXISTS department_name TEXT DEFAULT 'General';"
        ]
        
        try:
            async with self.pool.acquire() as conn:
                await conn.execute(create_table_query)
                # Execute ALTER statements for existing databases
                for stmt in alter_statements:
                    await conn.execute(stmt)
            log.info(f"Table '{self.table_name}' created or updated successfully.")
        except Exception as e:
            log.error(f"Error creating or updating table '{self.table_name}': {e}")
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
            model_used_for_evaluation, department_name
        ) VALUES (
            $1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14, $15
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
                    metrics_data.get("model_used_for_evaluation"),
                    metrics_data.get("department_name", "General")
                )
            return True
        except Exception as e:
            log.error(f"Error inserting tool evaluation metrics record: {e}")
            return False

    async def get_metrics_by_agent_names(
        self,
        user: Optional[User],
        agent_names: Optional[List[str]] = None,
        agent_types: Optional[List[str]] = None,
        page: int = 1,
        limit: int = 10
    ) -> List[Dict[str, Any]]:
        """
        Retrieves tool evaluation metrics records, optionally filtered by agent names and types.
        - SuperAdmin can access all records across all departments
        - Admin can access all records in their department
        - Regular users can only access records for agents they created
        """
        try:
            offset = (page - 1) * limit
            query = f"""
                SELECT tem.*
                FROM {self.table_name} tem
                JOIN {TableNames.EVALUATION_DATA.value} ed ON tem.evaluation_id = ed.id
            """
            params = []
            conditions = []

            # Apply filtering based on user role and permissions
            if user:
                if user.role == UserRole.SUPER_ADMIN:
                    # SuperAdmin can see all records - no additional filtering
                    log.info(f"SuperAdmin {user.email} accessing all tool metrics")
                    if agent_names:
                        conditions.append(f"ed.agent_name = ANY(${len(params)+1}::text[])")
                        params.append(agent_names)
                    if agent_types:
                        conditions.append(f"ed.agent_type = ANY(${len(params)+1}::text[])")
                        params.append(agent_types)
                        
                elif user.role == UserRole.ADMIN:
                    # Admin can see all records in their department
                    log.info(f"Admin {user.email} accessing department tool metrics: {user.department_name}")
                    
                    # Add department filter
                    conditions.append(f"ed.department_name = ${len(params)+1}")
                    params.append(user.department_name)
                    
                    if agent_names:
                        conditions.append(f"ed.agent_name = ANY(${len(params)+1}::text[])")
                        params.append(agent_names)
                    if agent_types:
                        conditions.append(f"ed.agent_type = ANY(${len(params)+1}::text[])")
                        params.append(agent_types)
                    
                else:
                    # Regular users can only see records for agents they created and in their department
                    log.info(f"User {user.email} accessing own agent tool metrics")
                    
                    # Add department filter for regular users
                    conditions.append(f"ed.department_name = ${len(params)+1}")
                    params.append(user.department_name)
                    
                    agent_names_result = await self.agent_repo.get_agent_names_by_creator_and_department(
                        user.email, user.department_name
                    )
                    owned_agent_names = [row["agentic_application_name"] for row in agent_names_result]

                    if not owned_agent_names:
                        log.warning(f"No agents found for user {user.email} in department {user.department_name}")
                        return []

                    # If agent_names is provided, filter only those that the user owns
                    if agent_names:
                        filtered_agent_names = list(set(agent_names) & set(owned_agent_names))
                        if not filtered_agent_names:
                            log.warning(f"User {user.email} does not own any of the requested agent names: {agent_names}")
                            return []
                        conditions.append(f"ed.agent_name = ANY(${len(params)+1}::text[])")
                        params.append(filtered_agent_names)
                    else:
                        conditions.append(f"ed.agent_name = ANY(${len(params)+1}::text[])")
                        params.append(owned_agent_names)
                    
                    if agent_types:
                        conditions.append(f"ed.agent_type = ANY(${len(params)+1}::text[])")
                        params.append(agent_types)
            else:
                # No user provided - this shouldn't happen with proper authentication
                log.warning("No user provided for tool metrics access")
                return []

            # Build WHERE clause from conditions
            if conditions:
                query += " WHERE " + " AND ".join(conditions)

            # Add pagination
            limit_param_index = len(params) + 1
            offset_param_index = len(params) + 2
            query += f" ORDER BY tem.id DESC LIMIT ${limit_param_index} OFFSET ${offset_param_index};"
            params.extend([limit, offset])

            log.debug(f"Executing query: {query} with params: {params}")

            # Step 3: Execute query
            async with self.pool.acquire() as conn:
                rows = await conn.fetch(query, *params)

            return [dict(row) for row in rows]

        except Exception as e:
            log.error(f"Error fetching tool evaluation metrics records: {e}")
            return []


# ---------------------------333---------------------------------------
# --- AgentEvaluationMetricsRepository ---
# --- CACHE NOT IMPLEMENTED FOR THIS CLASS ---
class AgentEvaluationMetricsRepository(BaseRepository):
    """
    Repository for 'agent_evaluation_metrics' table. Handles direct database interactions.
    """

    def __init__(self, pool: asyncpg.Pool, login_pool: asyncpg.Pool, agent_repo :AgentRepository, table_name: str = TableNames.AGENT_EVALUATION_METRICS.value):
        super().__init__(pool, login_pool, table_name)
        self.agent_repo = agent_repo

    async def create_table_if_not_exists(self):
        """Creates the 'agent_evaluation_metrics' table if it does not exist, and adds missing columns if needed."""
        create_table_query = f"""
        CREATE TABLE IF NOT EXISTS {self.table_name} (
            id SERIAL PRIMARY KEY,
            evaluation_id INTEGER REFERENCES {TableNames.EVALUATION_DATA.value}(id) ON DELETE CASCADE,
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
            communication_efficiency_score REAL,
            communication_efficiency_justification TEXT,
            efficiency_category TEXT,
            model_used_for_evaluation TEXT,
            department_name TEXT DEFAULT 'General',
            time_stamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        """
        
        alter_statements = [
            f"ALTER TABLE {self.table_name} ADD COLUMN IF NOT EXISTS communication_efficiency_score REAL DEFAULT NULL;",
            f"ALTER TABLE {self.table_name} ADD COLUMN IF NOT EXISTS communication_efficiency_justification TEXT DEFAULT 'NaN';",
            f"ALTER TABLE {self.table_name} ADD COLUMN IF NOT EXISTS department_name TEXT DEFAULT 'General';"
        ]

        try:
            async with self.pool.acquire() as conn:
                await conn.execute(create_table_query)
                for stmt in alter_statements:
                    await conn.execute(stmt)
            log.info(f"Table '{self.table_name}' created or updated successfully.")
        except Exception as e:
            log.error(f"Error creating or updating table '{self.table_name}': {e}")
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
            communication_efficiency_score, communication_efficiency_justification,
            efficiency_category, model_used_for_evaluation, department_name
        ) VALUES (
            $1, $2, $3, $4, $5, $6, $7, $8, $9, $10,
            $11, $12, $13, $14, $15, $16, $17, $18,
            $19, $20, $21, $22, $23
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
                    metrics_data.get("communication_efficiency_score"),metrics_data.get("communication_efficiency_justification"),
                    metrics_data.get("efficiency_category"), metrics_data.get("model_used_for_evaluation"),
                    metrics_data.get("department_name", "General")
                )
            return True
        except Exception as e:
            log.error(f"Error inserting agent evaluation metrics record: {e}", exc_info=True)
            return False

   
    async def get_metrics_by_agent_names(
        self,
        user: Optional[User],
        agent_names: Optional[List[str]] = None,
        agent_types: Optional[List[str]] = None,
        page: int = 1,
        limit: int = 10
    ) -> List[Dict[str, Any]]:
        """
        Retrieves agent evaluation metrics records, optionally filtered by agent names and types.
        - SuperAdmin can access all records across all departments
        - Admin can access all records in their department
        - Regular users can only access records for agents they created
        """
        try:
            offset = (page - 1) * limit
            query = f"""
                SELECT aem.*
                FROM {self.table_name} aem
                JOIN {TableNames.EVALUATION_DATA.value} ed ON aem.evaluation_id = ed.id
            """
            params = []
            conditions = []

            # Apply filtering based on user role and permissions
            if user:
                if user.role == UserRole.SUPER_ADMIN:
                    # SuperAdmin can see all records - no additional filtering
                    log.info(f"SuperAdmin {user.email} accessing all agent metrics")
                    if agent_names:
                        conditions.append(f"ed.agent_name = ANY(${len(params)+1}::text[])")
                        params.append(agent_names)
                    if agent_types:
                        conditions.append(f"ed.agent_type = ANY(${len(params)+1}::text[])")
                        params.append(agent_types)
                        
                elif user.role == UserRole.ADMIN:
                    # Admin can see all records in their department
                    log.info(f"Admin {user.email} accessing department agent metrics: {user.department_name}")
                    
                    # Add department filter
                    conditions.append(f"ed.department_name = ${len(params)+1}")
                    params.append(user.department_name)
                    
                    if agent_names:
                        conditions.append(f"ed.agent_name = ANY(${len(params)+1}::text[])")
                        params.append(agent_names)
                    if agent_types:
                        conditions.append(f"ed.agent_type = ANY(${len(params)+1}::text[])")
                        params.append(agent_types)
                    
                else:
                    # Regular users can only see records for agents they created and in their department
                    log.info(f"User {user.email} accessing own agent metrics")
                    
                    # Add department filter for regular users
                    conditions.append(f"ed.department_name = ${len(params)+1}")
                    params.append(user.department_name)
                    
                    agent_names_result = await self.agent_repo.get_agent_names_by_creator_and_department(
                        user.email, user.department_name
                    )
                    owned_agent_names = [row["agentic_application_name"] for row in agent_names_result]

                    if not owned_agent_names:
                        log.warning(f"No agents found for user {user.email} in department {user.department_name}")
                        return []

                    # If agent_names is provided, filter only those that the user owns
                    if agent_names:
                        filtered_agent_names = list(set(agent_names) & set(owned_agent_names))
                        if not filtered_agent_names:
                            log.warning(f"User {user.email} does not own any of the requested agent names: {agent_names}")
                            return []
                        conditions.append(f"ed.agent_name = ANY(${len(params)+1}::text[])")
                        params.append(filtered_agent_names)
                    else:
                        conditions.append(f"ed.agent_name = ANY(${len(params)+1}::text[])")
                        params.append(owned_agent_names)
                    
                    if agent_types:
                        conditions.append(f"ed.agent_type = ANY(${len(params)+1}::text[])")
                        params.append(agent_types)
            else:
                # No user provided - this shouldn't happen with proper authentication
                log.warning("No user provided for agent metrics access")
                return []

            # Build WHERE clause from conditions
            if conditions:
                query += " WHERE " + " AND ".join(conditions)

            # Add pagination
            limit_param_index = len(params) + 1
            offset_param_index = len(params) + 2
            query += f" ORDER BY aem.id DESC LIMIT ${limit_param_index} OFFSET ${offset_param_index};"
            params.extend([limit, offset])

            log.debug(f"Executing query: {query} with params: {params}")

            async with self.pool.acquire() as conn:
                rows = await conn.fetch(query, *params)

            return [dict(row) for row in rows]

        except Exception as e:
            log.error(f"Error fetching agent evaluation metrics records: {e}")
            return []



# --- Export Agent Repository ---

class ExportAgentRepository(BaseRepository):

    def __init__(self, pool: asyncpg.Pool, login_pool: asyncpg.Pool, table_name: str = TableNames.EXPORT_AGENT.value):
        super().__init__(pool, login_pool, table_name)


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


#-------------Consistency and Robustness-------------------#


def sanitize_identifier(name: str) -> str:
    """Removes invalid characters from a potential SQL identifier, replacing them with underscores."""
    return re.sub(r'[^a-zA-Z0-9_]', '_', name)


# ---------------------------444---------------------------------------

class AgentMetadataRepository(BaseRepository):
    """
    Handles all interactions with the main 'agent_evaluations' table and
    the 'agent_context_config' table.
    """
    def __init__(self, pool, login_pool):
        # We explicitly provide the table name this repository manages.
        table_name = "agent_evaluations"
        super().__init__(pool, login_pool, table_name)
        log.info(f"AgentMetadataRepository initialized for table: '{table_name}'.")
    
    async def create_agent_consistency_robustness(self):
        """Creates the 'agent_evaluations' table if it doesn't already exist and handles migrations."""
        create_table_query = """
        CREATE TABLE IF NOT EXISTS agent_evaluations (
            agent_id VARCHAR(255) PRIMARY KEY, agent_name VARCHAR(255) NOT NULL,
            agent_type VARCHAR(255) NOT NULL,
            model_name VARCHAR(100), is_enabled BOOLEAN DEFAULT TRUE,
            last_updated_at TIMESTAMP, last_robustness_run_at TIMESTAMP,
            queries_last_updated_at TIMESTAMP, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            department_name VARCHAR(255) DEFAULT 'General',
            created_by VARCHAR(255)
        );
        """
        
        # Migration: Add agent_type column if it doesn't exist
        add_agent_type_column_query = """
        DO $$ 
        BEGIN 
            IF NOT EXISTS (
                SELECT 1 FROM information_schema.columns 
                WHERE table_name = 'agent_evaluations' 
                AND column_name = 'agent_type'
            ) THEN
                ALTER TABLE agent_evaluations ADD COLUMN agent_type VARCHAR(255) NOT NULL DEFAULT 'unknown';
            END IF;
        END $$;
        """
        
        # Migration: Add department_name column if it doesn't exist
        add_department_name_column_query = """
        DO $$ 
        BEGIN 
            IF NOT EXISTS (
                SELECT 1 FROM information_schema.columns 
                WHERE table_name = 'agent_evaluations' 
                AND column_name = 'department_name'
            ) THEN
                ALTER TABLE agent_evaluations ADD COLUMN department_name VARCHAR(255) DEFAULT 'General';
            END IF;
        END $$;
        """
        
        # Migration: Add created_by column if it doesn't exist
        add_created_by_column_query = """
        DO $$ 
        BEGIN 
            IF NOT EXISTS (
                SELECT 1 FROM information_schema.columns 
                WHERE table_name = 'agent_evaluations' 
                AND column_name = 'created_by'
            ) THEN
                ALTER TABLE agent_evaluations ADD COLUMN created_by VARCHAR(255);
            END IF;
        END $$;
        """
        
        async with self.pool.acquire() as conn:
            await conn.execute(create_table_query)
            await conn.execute(add_agent_type_column_query)
            await conn.execute(add_department_name_column_query)
            await conn.execute(add_created_by_column_query)
        log.info("Table 'agent_evaluations' checked/created successfully and migrations applied.")

    async def upsert_agent_record(self, agent_id: str, agent_name: str, agent_type: str, model_name: str, department_name: str = None, created_by: str = None):
        """Inserts a new agent or updates an existing one using UPSERT."""
        query = """
        INSERT INTO agent_evaluations (agent_id, agent_name, agent_type, model_name, department_name, created_by, last_updated_at, created_at)
        VALUES ($1, $2, $3, $4, $5, $6, NOW(), NOW())
        ON CONFLICT (agent_id) DO UPDATE SET
            agent_name = EXCLUDED.agent_name,
            agent_type = EXCLUDED.agent_type,
            model_name = EXCLUDED.model_name,
            department_name = EXCLUDED.department_name,
            last_updated_at = NOW();
        """
        async with self.pool.acquire() as conn:
            await conn.execute(query, agent_id, agent_name, agent_type, model_name, department_name, created_by)
        log.info(f"Successfully upserted record for agent_id: {agent_id}")

    async def get_agent_by_id(self, agent_id: str) -> Optional[Dict[str, Any]]:
        """Fetches a single agent record from the database by its ID."""
        query = "SELECT * FROM agent_evaluations WHERE agent_id = $1"
        async with self.pool.acquire() as conn:
            record = await conn.fetchrow(query, agent_id)
        return dict(record) if record else None

    async def get_agents_by_department(self, department_name: str = None) -> List[Dict[str, Any]]:
        """Fetches agent records filtered by department."""
        if department_name:
            query = "SELECT * FROM agent_evaluations WHERE department_name = $1"
            params = [department_name]
        else:
            query = "SELECT * FROM agent_evaluations"
            params = []
            
        async with self.pool.acquire() as conn:
            records = await conn.fetch(query, *params)
        return [dict(record) for record in records]

    async def get_agents_to_reevaluate(self, interval_minutes: int) -> list:
        """Fetches agents that need a consistency re-evaluation."""
        cutoff_time = datetime.now() - timedelta(minutes=interval_minutes)
        query = "SELECT agent_id, agent_name, model_name FROM agent_evaluations WHERE is_enabled = TRUE AND (last_updated_at IS NULL OR last_updated_at < $1);"
        async with self.pool.acquire() as conn:
            records = await conn.fetch(query, cutoff_time)
        return [dict(r) for r in records]

    async def get_agents_for_robustness_reeval(self, interval_minutes: int) -> list:
        """Finds agents for robustness re-evaluation."""
        cutoff_time = datetime.now() - timedelta(minutes=interval_minutes)
        query = "SELECT agent_id, model_name, queries_last_updated_at, last_robustness_run_at FROM agent_evaluations WHERE is_enabled = TRUE AND (last_robustness_run_at IS NULL OR last_robustness_run_at < $1);"
        async with self.pool.acquire() as conn:
            records = await conn.fetch(query, cutoff_time)
        return [dict(r) for r in records]

    async def update_evaluation_timestamp(self, agent_id: str):
        """Updates the 'last_updated_at' timestamp for an agent."""
        query = "UPDATE agent_evaluations SET last_updated_at = NOW() WHERE agent_id = $1;"
        async with self.pool.acquire() as conn:
            await conn.execute(query, agent_id)

    async def update_robustness_timestamp(self, agent_id: str):
        """Updates the 'last_robustness_run_at' timestamp for an agent."""
        query = "UPDATE agent_evaluations SET last_robustness_run_at = NOW() WHERE agent_id = $1;"
        async with self.pool.acquire() as conn:
            await conn.execute(query, agent_id)

    async def update_queries_timestamp(self, agent_id: str):
        """Updates the 'queries_last_updated_at' timestamp for an agent."""
        query = "UPDATE agent_evaluations SET queries_last_updated_at = NOW() WHERE agent_id = $1;"
        async with self.pool.acquire() as conn:
            await conn.execute(query, agent_id)

    async def update_agent_model_in_db(self, agent_id: str, model_name: str):
        """Updates the model_name for a specific agent."""
        query = "UPDATE agent_evaluations SET model_name = $1, last_updated_at = NOW() WHERE agent_id = $2;"
        async with self.pool.acquire() as conn:
            await conn.execute(query, model_name, agent_id)

    async def delete_agent_record_from_main_table(self, agent_id: str):
        """Deletes the agent's metadata row from the 'agent_evaluations' table."""
        query = "DELETE FROM agent_evaluations WHERE agent_id = $1;"
        async with self.pool.acquire() as conn:
            await conn.execute(query, agent_id)

    async def fetch_agent_context(self, agentic_id: str) -> Optional[Dict[str, Any]]:
        """Fetches the goal and sample queries for a given agent."""
        query = "SELECT agent_goal, sample_queries FROM agent_context_config WHERE agentic_id = $1"
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(query, agentic_id)
        if row:
            return {"agent_goal": row["agent_goal"], "sample_queries": json.loads(row["sample_queries"])}
        return None


# ---------------------------555---------------------------------------

class AgentDataTableRepository(BaseRepository):
    """
    Manages all interactions with dynamic, agent-specific data tables
    (e.g., 'consistency_AGENT_ID', 'robustness_AGENT_ID').
    """

    def __init__(self, pool, login_pool):
        # This repository doesn't have one single table name, as it's dynamic.
        # So, we can pass a placeholder or None to the parent, as its methods
        # will always generate the table name dynamically anyway.
        super().__init__(pool, login_pool, table_name=None) # Pass None for the table_name
        log.info("AgentDataTableRepository initialized (manages dynamic tables).")
    
    def _get_safe_table_name(self, table_name: str) -> str:
        return sanitize_identifier(table_name.replace('-', '_'))

    async def create_and_insert_initial_data(self, table_name: str, initial_dataframe: pd.DataFrame, response_column_name: str):
        """Creates and populates a new consistency table for a first-time approval."""
        safe_table_name = self._get_safe_table_name(table_name)
        create_query = f'CREATE TABLE "{safe_table_name}" (id SERIAL PRIMARY KEY, queries TEXT, "{response_column_name}" TEXT, inserted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP);'
        
        async with self.pool.acquire() as conn:
            await conn.execute(f'DROP TABLE IF EXISTS "{safe_table_name}" CASCADE;')
            await conn.execute(create_query)
            # Convert all values to strings to avoid type mismatch errors
            data_to_insert = [
                (str(row[0]) if row[0] is not None else None, str(row[1]) if row[1] is not None else None)
                for row in initial_dataframe[['queries', response_column_name]].itertuples(index=False, name=None)
            ]
            insert_query = f'INSERT INTO "{safe_table_name}" (queries, "{response_column_name}") VALUES ($1, $2);'
            await conn.executemany(insert_query, data_to_insert)

    async def create_and_insert_robustness_data(self, table_name: str, dataset: list, response_col: str, score_col: str):
        """Creates a new robustness table and inserts the full scored dataset."""
        safe_table_name = self._get_safe_table_name(f"robustness_{table_name}")
        create_query = f"""
        CREATE TABLE "{safe_table_name}" (
            id SERIAL PRIMARY KEY, agentic_id VARCHAR(255), category TEXT, query TEXT,
            "{response_col}" TEXT, "{score_col}" REAL,
            inserted_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
        );
        """
        async with self.pool.acquire() as conn:
            await conn.execute(f'DROP TABLE IF EXISTS "{safe_table_name}" CASCADE;')
            await conn.execute(create_query)
            data_to_insert = [(item['agentic_id'], item['category'], item['query'], item.get(response_col), item.get(score_col)) for item in dataset]
            insert_query = f'INSERT INTO "{safe_table_name}" (agentic_id, category, query, "{response_col}", "{score_col}") VALUES ($1, $2, $3, $4, $5);'
            await conn.executemany(insert_query, data_to_insert)

    async def create_and_insert_robustness_data_initial(self, agent_id: str, dataset: list):
        """Creates a robustness table with only the initial generated queries."""
        safe_table_name = self._get_safe_table_name(f"robustness_{agent_id}")
        create_query = f'CREATE TABLE IF NOT EXISTS "{safe_table_name}" (id SERIAL PRIMARY KEY, agentic_id VARCHAR(255), category TEXT, query TEXT, inserted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP);'
        async with self.pool.acquire() as conn:
            await conn.execute(create_query)
            data_to_insert = [(item['agentic_id'], item['category'], item['query']) for item in dataset]
            insert_query = f'INSERT INTO "{safe_table_name}" (agentic_id, category, query) VALUES ($1, $2, $3);'
            await conn.executemany(insert_query, data_to_insert)

    async def get_full_data_as_dataframe(self, table_name: str) -> pd.DataFrame:
        """Fetches all data from a table and returns it as a pandas DataFrame."""
        safe_table_name = self._get_safe_table_name(table_name)
        query = f'SELECT * FROM "{safe_table_name}";'
        try:
            async with self.pool.acquire() as conn:
                records = await conn.fetch(query)
            return pd.DataFrame(records, columns=records[0].keys()) if records else pd.DataFrame()
        except asyncpg.exceptions.UndefinedTableError:
            return pd.DataFrame()

    async def get_approved_queries_from_db(self, agentic_application_id: str) -> list:
        """Fetches the list of approved queries from a consistency table."""
        safe_table_name = self._get_safe_table_name(agentic_application_id)
        query = f'SELECT queries FROM "{safe_table_name}";'
        try:
            async with self.pool.acquire() as conn:
                records = await conn.fetch(query)
            return [r['queries'] for r in records if r['queries']]
        except asyncpg.exceptions.UndefinedTableError:
            return []

    async def get_latest_response_column_name(self, table_name: str) -> Optional[str]:
        """Finds the name of the most recent _response column in a table."""
        safe_table_name = self._get_safe_table_name(table_name)
        query = f"SELECT column_name FROM information_schema.columns WHERE table_name = '{safe_table_name}' AND column_name LIKE '%_response' ORDER BY column_name DESC;"
        async with self.pool.acquire() as conn:
            return await conn.fetchval(query)

    async def add_column_to_agent_table(self, table_name: str, new_column_name: str, column_type: str = "TEXT"):
        """Adds a new column to a specified table."""
        safe_table_name = self._get_safe_table_name(table_name)
        query = f'ALTER TABLE "{safe_table_name}" ADD COLUMN IF NOT EXISTS "{new_column_name}" {column_type.upper()};'
        async with self.pool.acquire() as conn:
            await conn.execute(query)

    async def rename_column_with_timestamp(self, table_name: str, old_name: str, timestamp: str, new_suffix: str):
        """Renames a column to include a timestamp."""
        safe_table_name = self._get_safe_table_name(table_name)
        new_name = f"{timestamp}_{new_suffix}"
        query = f'ALTER TABLE "{safe_table_name}" RENAME COLUMN "{old_name}" TO "{new_name}";'
        async with self.pool.acquire() as conn:
            await conn.execute(query)

    async def update_data_in_agent_table(self, table_name: str, column_name: str, data_to_update: list):
        """Updates a specific column for multiple rows identified by their IDs."""
        safe_table_name = self._get_safe_table_name(table_name)
        query = f'UPDATE "{safe_table_name}" SET "{column_name}" = $1 WHERE id = $2;'
        async with self.pool.acquire() as conn:
            await conn.executemany(query, data_to_update)

    async def update_column_by_row_id(self, table_name: str, column_name: str, new_data_list: list):
        """Updates a column for existing rows based on their sequential row ID."""
        safe_table_name = self._get_safe_table_name(table_name)
        update_tuples = [(value, index + 1) for index, value in enumerate(new_data_list)]
        query = f'UPDATE "{safe_table_name}" SET "{column_name}" = $1 WHERE id = $2;'
        async with self.pool.acquire() as conn:
            await conn.executemany(query, update_tuples)

    async def drop_agent_results_table(self, table_name: str):
        """Completely deletes (DROPs) an agent's specific results table."""
        safe_table_name = self._get_safe_table_name(table_name)
        query = f'DROP TABLE IF EXISTS "{safe_table_name}";'
        async with self.pool.acquire() as conn:
            await conn.execute(query)

    async def get_all_agent_records(self, user: Optional[User] = None, agent_type: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        Fetches all records from the agent_evaluations table and returns them
        as a list of dictionaries, including the queries from each agent's consistency table.
        Filters based on user role:
        - Admin: All agents in their department
        - Developer: Only agents they created in their department
        
        Optionally filter by agent_type (case-insensitive).
        Valid agent_types: react_agent, multi_agent, planner_executor_agent, 
                          react_critic_agent, hybrid_agent, meta_agent, planner_meta_agent
        """
        base_query = "SELECT * FROM agent_evaluations"
        where_conditions = []
        params = []
        param_index = 1
        
        # Apply user-based filtering
        if user and user.department_name:
            # Always filter by department
            where_conditions.append(f"department_name = ${param_index}")
            params.append(user.department_name)
            param_index += 1
            
            # Developer can only see their own created evaluations
            # Admin can see all in their department
            # Role comes as "Admin", "Developer" etc. (capitalized)
            if user.role == 'Developer':
                where_conditions.append(f"created_by = ${param_index}")
                params.append(user.email)
                param_index += 1
        
        # Apply agent_type filtering if provided (case-insensitive)
        if agent_type:
            where_conditions.append(f"LOWER(agent_type) = LOWER(${param_index})")
            params.append(agent_type)
            param_index += 1
        
        # Build final query
        if where_conditions:
            query = f"{base_query} WHERE {' AND '.join(where_conditions)} ORDER BY created_at DESC;"
        else:
            query = f"{base_query} ORDER BY created_at DESC;"
        
        log.info(f"Executing query: {query} with params: {params}")
        
        async with self.pool.acquire() as conn:
            if params:
                records = await conn.fetch(query, *params)
            else:
                records = await conn.fetch(query)
            
            # Convert records to dictionaries and fetch queries for each agent
            agent_records = []
            for record in records:
                agent_dict = dict(record)
                agent_id = agent_dict['agent_id']
                
                # Fetch queries from the agent's consistency table
                try:
                    safe_table_name = self._get_safe_table_name(agent_id)
                    queries_query = f'SELECT queries FROM "{safe_table_name}" WHERE queries IS NOT NULL AND queries != \'\';'
                    queries_records = await conn.fetch(queries_query)
                    queries_list = [q['queries'] for q in queries_records]
                    agent_dict['queries'] = queries_list
                except Exception as e:
                    # If the table doesn't exist or there's an error, set empty queries list
                    log.warning(f"Could not fetch queries for agent {agent_id}: {e}")
                    agent_dict['queries'] = []
                
                agent_records.append(agent_dict)
        
        log.info(f"Successfully fetched {len(agent_records)} agent evaluation records with queries.")
        return agent_records
    

    async def get_recent_consistency_scores(self, table_name: str, limit: int = 5) -> List[Dict[str, Any]]:
        """
        Fetches the last `limit` consistency score rows from the agent's table.
        """
        safe_table_name = self._get_safe_table_name(table_name)
        query = f"""
            SELECT * FROM "{safe_table_name}"
            ORDER BY inserted_at DESC
            LIMIT {limit};
        """
        async with self.pool.acquire() as conn:
            records = await conn.fetch(query)
            return [dict(r) for r in records]

        
    async def get_all_consistency_records(self, table_name: str) -> List[Dict]:
        safe_table_name = self._get_safe_table_name(table_name)
        query = f'SELECT * FROM "{safe_table_name}" ORDER BY inserted_at DESC;'
        async with self.pool.acquire() as conn:
            records = await conn.fetch(query)
            return [dict(r) for r in records]
        
    async def get_all_robustness_records(self, table_name: str) -> List[Dict]:
        safe_table_name = self._get_safe_table_name(table_name)
        query = f'SELECT * FROM "{safe_table_name}" ORDER BY inserted_at DESC;'
        async with self.pool.acquire() as conn:
            records = await conn.fetch(query)
            return [dict(r) for r in records]


# --- Pending Modules Functions ---
async def create_pending_modules_table(pool: asyncpg.Pool):
    """Create the pending modules table if it doesn't exist."""
    create_table_query = """
        CREATE TABLE IF NOT EXISTS pending_modules_table (
            id SERIAL PRIMARY KEY,
            module_name TEXT NOT NULL UNIQUE,
            tool_name TEXT,
            created_by TEXT,
            tool_code TEXT,
            created_on TIMESTAMP DEFAULT NOW()
        );
    """
    async with pool.acquire() as conn:
        await conn.execute(create_table_query)

async def save_pending_module(pool: asyncpg.Pool, module_name: str, tool_name: str, created_by: str = None, tool_code: str = None):
    """Save a pending module to the database."""
    await create_pending_modules_table(pool)
    insert_query = """
        INSERT INTO pending_modules_table (module_name, tool_name, created_by, tool_code)
        VALUES ($1, $2, $3, $4)
        ON CONFLICT (module_name) DO NOTHING
    """
    async with pool.acquire() as conn:
        await conn.execute(insert_query, module_name, tool_name, created_by, tool_code)

async def get_all_pending_modules(pool: asyncpg.Pool) -> List[Dict[str, Any]]:
    """Get all pending modules from the database."""
    await create_pending_modules_table(pool)
    select_query = """
        SELECT id, module_name, tool_name, created_by, tool_code, created_on
        FROM pending_modules_table
        ORDER BY created_on DESC
    """
    async with pool.acquire() as conn:
        rows = await conn.fetch(select_query)
        return [dict(row) for row in rows]


# --- Pipeline Repository ---

class PipelineRepository(BaseRepository, CacheableRepository):
    """
    Repository for the 'pipelines_table'. Handles direct database interactions for agent pipelines.
    """

    def __init__(self, pool: asyncpg.Pool, login_pool: asyncpg.Pool, table_name: str = TableNames.PIPELINES.value):
        """
        Initializes the PipelineRepository.

        Args:
            pool (asyncpg.Pool): The asyncpg connection pool.
            login_pool (asyncpg.Pool): The asyncpg connection pool for login-related operations.
            table_name (str): The name of the pipelines table.
        """
        super().__init__(pool, login_pool, table_name)

    async def create_table_if_not_exists(self):
        """
        Creates the 'pipelines_table' in PostgreSQL if it does not exist.
        """
        try:
            create_statement = f"""
            CREATE TABLE IF NOT EXISTS {self.table_name} (
                pipeline_id TEXT PRIMARY KEY,
                pipeline_name TEXT NOT NULL,
                pipeline_description TEXT,
                pipeline_definition JSONB NOT NULL,
                created_by TEXT NOT NULL,
                department_name TEXT DEFAULT 'General',
                created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
                is_active BOOLEAN DEFAULT TRUE,
                CONSTRAINT uq_pipeline_name_department UNIQUE (pipeline_name, department_name)
            );
            """
            
            async with self.pool.acquire() as conn:
                await conn.execute(create_statement)
                
                # ALTER statements to add columns/indexes if table already exists
                alter_statements = [
                    f"ALTER TABLE {self.table_name} ADD COLUMN IF NOT EXISTS department_name TEXT DEFAULT 'General'",
                    f"CREATE INDEX IF NOT EXISTS idx_pipelines_created_by ON {self.table_name}(created_by)",
                    f"CREATE INDEX IF NOT EXISTS idx_pipelines_is_active ON {self.table_name}(is_active)",
                    f"CREATE INDEX IF NOT EXISTS idx_pipelines_department_name ON {self.table_name}(department_name)",
                ]
                
                for stmt in alter_statements:
                    try:
                        await conn.execute(stmt)
                    except Exception as alter_error:
                        log.warning(f"ALTER statement warning for '{self.table_name}': {alter_error}")
                
                # Migration: Rename duplicate pipeline names within departments (must run before adding unique constraint)
                await self._migrate_duplicate_pipeline_names(conn)
                
                # Add unique constraint on (pipeline_name, department_name)
                try:
                    await conn.execute(f"""
                        ALTER TABLE {self.table_name} 
                        ADD CONSTRAINT uq_pipeline_name_department 
                        UNIQUE (pipeline_name, department_name)
                    """)
                    log.info(f"Unique constraint on (pipeline_name, department_name) added to '{self.table_name}'")
                except Exception as constraint_error:
                    # Constraint may already exist
                    if "already exists" not in str(constraint_error).lower():
                        log.warning(f"Unique constraint warning for '{self.table_name}': {constraint_error}")
                        
            log.info(f"Table '{self.table_name}' created successfully or already exists.")
        except Exception as e:
            log.error(f"Error creating table '{self.table_name}': {e}")

    async def _migrate_duplicate_pipeline_names(self, conn):
        """
        Migration to rename duplicate pipeline names within each department.
        Appends _dupl_1, _dupl_2, etc. to duplicates.
        """
        try:
            # Find duplicates: pipelines with same name in same department
            find_duplicates_query = f"""
            SELECT pipeline_id, pipeline_name, department_name,
                   ROW_NUMBER() OVER (PARTITION BY pipeline_name, department_name ORDER BY created_at) as rn
            FROM {self.table_name}
            WHERE (pipeline_name, department_name) IN (
                SELECT pipeline_name, department_name
                FROM {self.table_name}
                GROUP BY pipeline_name, department_name
                HAVING COUNT(*) > 1
            )
            """
            
            rows = await conn.fetch(find_duplicates_query)
            
            if not rows:
                log.debug("No duplicate pipeline names found.")
                return
            
            # Update duplicates (skip rn=1 as that's the original)
            updated_count = 0
            for row in rows:
                if row['rn'] > 1:
                    new_name = f"{row['pipeline_name']}_dupl_{row['rn'] - 1}"
                    update_query = f"""
                    UPDATE {self.table_name}
                    SET pipeline_name = $1, updated_at = CURRENT_TIMESTAMP
                    WHERE pipeline_id = $2
                    """
                    await conn.execute(update_query, new_name, row['pipeline_id'])
                    updated_count += 1
                    log.info(f"Renamed duplicate pipeline '{row['pipeline_name']}' to '{new_name}' (ID: {row['pipeline_id']})")
            
            if updated_count > 0:
                log.info(f"Migration complete: Renamed {updated_count} duplicate pipeline names.")
                
        except Exception as e:
            log.warning(f"Pipeline name migration warning: {e}")

    async def check_pipeline_name_exists(
        self,
        pipeline_name: str,
        department_name: str,
        exclude_pipeline_id: Optional[str] = None
    ) -> bool:
        """
        Check if a pipeline with the given name already exists in the department.
        
        Args:
            pipeline_name: Name to check
            department_name: Department to check within
            exclude_pipeline_id: Pipeline ID to exclude (for update operations)
            
        Returns:
            bool: True if name exists, False otherwise
        """
        query = f"""
        SELECT COUNT(*) FROM {self.table_name}
        WHERE LOWER(pipeline_name) = LOWER($1) AND department_name = $2
        """
        params = [pipeline_name.strip(), department_name]
        
        if exclude_pipeline_id:
            query += " AND pipeline_id != $3"
            params.append(exclude_pipeline_id)
        
        try:
            async with self.pool.acquire() as conn:
                count = await conn.fetchval(query, *params)
                return count > 0
        except Exception as e:
            log.error(f"Error checking pipeline name existence: {e}")
            return False

    async def insert_pipeline(
        self,
        pipeline_id: str,
        pipeline_name: str,
        pipeline_description: str,
        pipeline_definition: dict,
        created_by: str,
        department_name: str = None
    ) -> bool:
        """
        Inserts a new pipeline record.

        Args:
            pipeline_id: Unique identifier for the pipeline
            pipeline_name: Name of the pipeline
            pipeline_description: Description of the pipeline
            pipeline_definition: JSON definition of nodes and edges
            created_by: Email of the creator
            department_name: Department name for the pipeline

        Returns:
            bool: True if successful, False otherwise
        """
        insert_statement = f"""
        INSERT INTO {self.table_name} 
        (pipeline_id, pipeline_name, pipeline_description, pipeline_definition, created_by, department_name)
        VALUES ($1, $2, $3, $4, $5, $6)
        """
        try:
            async with self.pool.acquire() as conn:
                await conn.execute(
                    insert_statement,
                    pipeline_id,
                    pipeline_name.strip(),
                    pipeline_description,
                    json.dumps(pipeline_definition),
                    created_by,
                    department_name
                )
            await self.invalidate_all_method_cache("get_pipeline")
            await self.invalidate_all_method_cache("get_all_pipelines")
            log.info(f"Pipeline '{pipeline_name}' inserted successfully with ID: {pipeline_id}")
            return {"success": True}
        except asyncpg.UniqueViolationError as e:
            error_str = str(e).lower()
            if "uq_pipeline_name_department" in error_str or "pipeline_name" in error_str:
                log.warning(f"Pipeline with name '{pipeline_name}' already exists in department '{department_name}'.")
                return {"success": False, "error": "duplicate_name", "message": f"A pipeline with name '{pipeline_name}' already exists in this department."}
            else:
                log.warning(f"Pipeline with ID '{pipeline_id}' already exists.")
                return {"success": False, "error": "duplicate_id", "message": f"Pipeline with ID '{pipeline_id}' already exists."}
        except Exception as e:
            log.error(f"Error inserting pipeline '{pipeline_name}': {e}")
            return {"success": False, "error": "unknown", "message": str(e)}

    @CacheableRepository.cache(ttl=EXPIRY_TIME, namespace="PipelineRepository")
    async def get_all_pipelines(self, created_by: Optional[str] = None, is_active: Optional[bool] = None, department_name: str = None) -> List[Dict[str, Any]]:
        """
        Retrieves all pipeline records with optional filtering.

        Args:
            created_by: Filter by creator email
            is_active: Filter by active status
            department_name: Filter by department name

        Returns:
            List of pipeline dictionaries
        """
        query = f"SELECT * FROM {self.table_name} WHERE 1=1"
        params = []
        param_idx = 1
        
        if created_by:
            query += f" AND created_by = ${param_idx}"
            params.append(created_by)
            param_idx += 1
        
        if is_active is not None:
            query += f" AND is_active = ${param_idx}"
            params.append(is_active)
            param_idx += 1
        
        if department_name:
            query += f" AND department_name = ${param_idx}"
            params.append(department_name)
            param_idx += 1
        
        query += " ORDER BY updated_at DESC"
        
        try:
            async with self.pool.acquire() as conn:
                rows = await conn.fetch(query, *params)
            log.info(f"Retrieved {len(rows)} pipeline records.")
            result = []
            for row in rows:
                row_dict = dict(row)
                if isinstance(row_dict.get('pipeline_definition'), str):
                    row_dict['pipeline_definition'] = json.loads(row_dict['pipeline_definition'])
                result.append(row_dict)
            await self._transform_emails_to_usernames(result, ['created_by'])
            return result
        except Exception as e:
            log.error(f"Error retrieving pipelines: {e}")
            return []

    async def get_pipeline_by_name(self, pipeline_name: str) -> Optional[Dict[str, Any]]:
        """
        Retrieves a single pipeline record by its exact name.

        Args:
            pipeline_name: The exact pipeline name to look up

        Returns:
            Pipeline dictionary if found, None otherwise
        """
        query = f"SELECT * FROM {self.table_name} WHERE pipeline_name = $1 LIMIT 1"
        try:
            async with self.pool.acquire() as conn:
                row = await conn.fetchrow(query, pipeline_name)
            if not row:
                return None
            row_dict = dict(row)
            if isinstance(row_dict.get('pipeline_definition'), str):
                row_dict['pipeline_definition'] = json.loads(row_dict['pipeline_definition'])
            await self._transform_emails_to_usernames([row_dict], ['created_by'])
            log.info(f"Pipeline '{pipeline_name}' retrieved successfully.")
            return row_dict
        except Exception as e:
            log.error(f"Error retrieving pipeline by name '{pipeline_name}': {e}")
            return None

    async def get_total_pipeline_count(
        self,
        search_value: str = '',
        created_by: Optional[str] = None,
        is_active: Optional[bool] = None,
        department_name: str = None
    ) -> int:
        """
        Gets the total count of pipelines matching the search criteria.

        Args:
            search_value: Search string to match against pipeline name
            created_by: Filter by creator email
            is_active: Filter by active status
            department_name: Filter by department name

        Returns:
            int: Total count of matching pipelines
        """
        query = f"SELECT COUNT(*) FROM {self.table_name} WHERE 1=1"
        params = []
        param_idx = 1
        
        if search_value:
            query += f" AND pipeline_name ILIKE ${param_idx}"
            params.append(f"%{search_value}%")
            param_idx += 1
        
        if created_by:
            query += f" AND created_by = ${param_idx}"
            params.append(created_by)
            param_idx += 1
        
        if is_active is not None:
            query += f" AND is_active = ${param_idx}"
            params.append(is_active)
            param_idx += 1
        
        if department_name:
            query += f" AND department_name = ${param_idx}"
            params.append(department_name)
            param_idx += 1
        
        try:
            async with self.pool.acquire() as conn:
                count = await conn.fetchval(query, *params)
            return count or 0
        except Exception as e:
            log.error(f"Error getting pipeline count: {e}")
            return 0

    async def get_pipelines_by_search_or_page(
        self,
        search_value: str = '',
        limit: int = 20,
        page: int = 1,
        created_by: Optional[str] = None,
        is_active: Optional[bool] = None,
        department_name: str = None
    ) -> List[Dict[str, Any]]:
        """
        Retrieves pipelines with pagination and search filtering.

        Args:
            search_value: Search string to match against pipeline name
            limit: Number of results per page
            page: Page number (1-indexed)
            created_by: Filter by creator email
            is_active: Filter by active status
            department_name: Filter by department name

        Returns:
            List of pipeline dictionaries
        """
        offset = limit * max(0, page - 1)
        query = f"SELECT * FROM {self.table_name} WHERE 1=1"
        params = []
        param_idx = 1
        
        if search_value:
            query += f" AND pipeline_name ILIKE ${param_idx}"
            params.append(f"%{search_value}%")
            param_idx += 1
        
        if created_by:
            query += f" AND created_by = ${param_idx}"
            params.append(created_by)
            param_idx += 1
        
        if is_active is not None:
            query += f" AND is_active = ${param_idx}"
            params.append(is_active)
            param_idx += 1
        
        if department_name:
            query += f" AND department_name = ${param_idx}"
            params.append(department_name)
            param_idx += 1
        
        query += f" ORDER BY updated_at DESC LIMIT ${param_idx} OFFSET ${param_idx + 1}"
        params.extend([limit, offset])
        
        try:
            async with self.pool.acquire() as conn:
                rows = await conn.fetch(query, *params)
            log.info(f"Retrieved {len(rows)} pipelines for search '{search_value}' page {page}.")
            result = []
            for row in rows:
                row_dict = dict(row)
                if isinstance(row_dict.get('pipeline_definition'), str):
                    row_dict['pipeline_definition'] = json.loads(row_dict['pipeline_definition'])
                result.append(row_dict)
            await self._transform_emails_to_usernames(result, ['created_by'])
            return result
        except Exception as e:
            log.error(f"Error retrieving pipelines by search/page: {e}")
            return []

    @CacheableRepository.cache(ttl=EXPIRY_TIME, namespace="PipelineRepository")
    async def get_pipeline(self, pipeline_id: str, department_name: str = None) -> Optional[Dict[str, Any]]:
        """
        Retrieves a single pipeline by ID.

        Args:
            pipeline_id: The pipeline ID
            department_name: Filter by department name

        Returns:
            Pipeline dictionary or None if not found
        """
        query = f"SELECT * FROM {self.table_name} WHERE pipeline_id = $1"
        params = [pipeline_id]
        
        if department_name:
            query += " AND department_name = $2"
            params.append(department_name)
        
        try:
            async with self.pool.acquire() as conn:
                row = await conn.fetchrow(query, *params)
            if row:
                row_dict = dict(row)
                if isinstance(row_dict.get('pipeline_definition'), str):
                    row_dict['pipeline_definition'] = json.loads(row_dict['pipeline_definition'])
                await self._transform_emails_to_usernames([row_dict], ['created_by'])
                log.info(f"Pipeline '{pipeline_id}' retrieved successfully.")
                return row_dict
            else:
                log.info(f"Pipeline '{pipeline_id}' not found.")
                return None
        except Exception as e:
            log.error(f"Error retrieving pipeline '{pipeline_id}': {e}")
            return None

    async def update_pipeline(
        self,
        pipeline_id: str,
        pipeline_name: Optional[str] = None,
        pipeline_description: Optional[str] = None,
        pipeline_definition: Optional[dict] = None,
        is_active: Optional[bool] = None
    ) -> Dict[str, Any]:
        """
        Updates a pipeline record.

        Args:
            pipeline_id: The pipeline ID to update
            pipeline_name: New name (optional)
            pipeline_description: New description (optional)
            pipeline_definition: New definition (optional)
            is_active: New active status (optional)

        Returns:
            dict: Result with success status and optional error message
        """
        updates = []
        params = []
        param_idx = 1
        
        if pipeline_name is not None:
            updates.append(f"pipeline_name = ${param_idx}")
            params.append(pipeline_name.strip())
            param_idx += 1
        
        if pipeline_description is not None:
            updates.append(f"pipeline_description = ${param_idx}")
            params.append(pipeline_description)
            param_idx += 1
        
        if pipeline_definition is not None:
            updates.append(f"pipeline_definition = ${param_idx}")
            params.append(json.dumps(pipeline_definition))
            param_idx += 1
        
        if is_active is not None:
            updates.append(f"is_active = ${param_idx}")
            params.append(is_active)
            param_idx += 1
        
        if not updates:
            log.warning("No fields to update for pipeline.")
            return {"success": False, "error": "no_fields", "message": "No fields to update."}
        
        updates.append("updated_at = CURRENT_TIMESTAMP")
        params.append(pipeline_id)
        
        update_statement = f"""
        UPDATE {self.table_name}
        SET {', '.join(updates)}
        WHERE pipeline_id = ${param_idx}
        """
        
        try:
            async with self.pool.acquire() as conn:
                result = await conn.execute(update_statement, *params)
            await self.invalidate_all_method_cache("get_pipeline")
            await self.invalidate_all_method_cache("get_all_pipelines")
            if result != "UPDATE 0":
                log.info(f"Pipeline '{pipeline_id}' updated successfully.")
                return {"success": True}
            else:
                log.warning(f"Pipeline '{pipeline_id}' not found, no update performed.")
                return {"success": False, "error": "not_found", "message": f"Pipeline '{pipeline_id}' not found."}
        except asyncpg.UniqueViolationError as e:
            error_str = str(e).lower()
            if "uq_pipeline_name_department" in error_str or "pipeline_name" in error_str:
                log.warning(f"Cannot update pipeline '{pipeline_id}': name '{pipeline_name}' already exists in department.")
                return {"success": False, "error": "duplicate_name", "message": f"A pipeline with name '{pipeline_name}' already exists in this department."}
            else:
                log.error(f"Unique violation error updating pipeline '{pipeline_id}': {e}")
                return {"success": False, "error": "duplicate", "message": str(e)}
        except Exception as e:
            log.error(f"Error updating pipeline '{pipeline_id}': {e}")
            return {"success": False, "error": "unknown", "message": str(e)}

    async def delete_pipeline(self, pipeline_id: str) -> bool:
        """
        Deletes a pipeline record.

        Args:
            pipeline_id: The pipeline ID to delete

        Returns:
            bool: True if successful, False otherwise
        """
        delete_statement = f"DELETE FROM {self.table_name} WHERE pipeline_id = $1"
        try:
            async with self.pool.acquire() as conn:
                result = await conn.execute(delete_statement, pipeline_id)
            await self.invalidate_all_method_cache("get_pipeline")
            await self.invalidate_all_method_cache("get_all_pipelines")
            if result != "DELETE 0":
                log.info(f"Pipeline '{pipeline_id}' deleted successfully.")
                return True
            else:
                log.warning(f"Pipeline '{pipeline_id}' not found, no deletion performed.")
                return False
        except Exception as e:
            log.error(f"Error deleting pipeline '{pipeline_id}': {e}")
            return False


# --- AgentPipelineMappingRepository ---

class AgentPipelineMappingRepository(BaseRepository, CacheableRepository):
    """
    Repository for the 'agent_pipeline_mapping_table'. Handles direct database interactions for agent-pipeline mappings.
    Similar to ToolAgentMappingRepository, but maps agents to pipelines.
    """

    def __init__(self, pool: asyncpg.Pool, login_pool: asyncpg.Pool, table_name: str = TableNames.AGENT_PIPELINE_MAPPING.value):
        """
        Initializes the AgentPipelineMappingRepository.

        Args:
            pool (asyncpg.Pool): The asyncpg connection pool.
            login_pool (asyncpg.Pool): The asyncpg connection pool for login-related operations.
            table_name (str): The name of the agent-pipeline mapping table.
        """
        super().__init__(pool, login_pool, table_name)

    async def create_table_if_not_exists(self):
        """
        Creates the 'agent_pipeline_mapping_table' if it does not exist.
        NOTE: The FOREIGN KEY to agent_table is intentionally removed here
              to allow mapping of pipeline IDs (worker pipelines) as 'agentic_application_id'.
        """
        try:
            create_statement = f"""
            CREATE TABLE IF NOT EXISTS {self.table_name} (
                agentic_application_id TEXT,
                pipeline_id TEXT,
                agent_created_by TEXT,
                pipeline_created_by TEXT,
                -- FOREIGN KEY(agentic_application_id) REFERENCES {TableNames.AGENT.value}(agentic_application_id) ON DELETE RESTRICT, -- REMOVED
                FOREIGN KEY(pipeline_id) REFERENCES {TableNames.PIPELINES.value}(pipeline_id) ON DELETE CASCADE
            );
            """
            async with self.pool.acquire() as conn:
                await conn.execute(create_statement)
            log.info(f"Table '{self.table_name}' created successfully or already exists.")
        except Exception as e:
            log.error(f"Error creating table '{self.table_name}': {e}")

    async def assign_agent_to_pipeline_record(self, agentic_application_id: str, pipeline_id: str, agent_created_by: str, pipeline_created_by: str) -> bool:
        """
        Inserts a mapping between an agent/worker_pipeline and a pipeline.

        Args:
            agentic_application_id (str): The ID of the agent or worker pipeline.
            pipeline_id (str): The ID of the pipeline.
            agent_created_by (str): The creator of the agent/worker pipeline.
            pipeline_created_by (str): The creator of the pipeline.

        Returns:
            bool: True if the mapping was inserted successfully, False otherwise.
        """
        insert_statement = f"""
        INSERT INTO {self.table_name} (agentic_application_id, pipeline_id, agent_created_by, pipeline_created_by)
        VALUES ($1, $2, $3, $4)
        """
        try:
            async with self.pool.acquire() as conn:
                await conn.execute(insert_statement, agentic_application_id, pipeline_id, agent_created_by, pipeline_created_by)
            await self.invalidate_all_method_cache("get_agent_pipeline_mappings_record")
            await self.invalidate_all_method_cache("get_pipeline", namespace="PipelineRepository")
            log.info(f"Mapping agent/pipeline '{agentic_application_id}' to pipeline '{pipeline_id}' inserted successfully.")
            return True
        except Exception as e:
            log.error(f"Error assigning agent/pipeline '{agentic_application_id}' to pipeline '{pipeline_id}': {e}")
            return False

    @CacheableRepository.cache(ttl=EXPIRY_TIME, namespace="AgentPipelineMappingRepository")
    async def get_agent_pipeline_mappings_record(self, agentic_application_id: Optional[str] = None, pipeline_id: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        Retrieves agent-pipeline mappings by agentic_application_id or pipeline_id, including pipeline_name.

        Args:
            agentic_application_id (Optional[str]): The ID of the agent or worker pipeline to filter by.
            pipeline_id (Optional[str]): The ID of the pipeline to filter by.

        Returns:
            List[Dict[str, Any]]: A list of dictionaries, each representing an agent-pipeline mapping with pipeline_name.
        """
        select_statement = f"""
            SELECT apm.agentic_application_id, apm.pipeline_id, apm.agent_created_by, apm.pipeline_created_by, 
                   p.pipeline_name 
            FROM {self.table_name} apm
            LEFT JOIN {TableNames.PIPELINES.value} p ON apm.pipeline_id = p.pipeline_id
        """
        where_clause = []
        values = []

        filters = {"apm.agentic_application_id": agentic_application_id, "apm.pipeline_id": pipeline_id}
        for idx, (field, value) in enumerate((f for f in filters.items() if f[1] is not None), start=1):
            where_clause.append(f"{field} = ${idx}")
            values.append(value)

        if where_clause:
            select_statement += " WHERE " + " AND ".join(where_clause)

        try:
            async with self.pool.acquire() as conn:
                rows = await conn.fetch(select_statement, *values)
            log.info(f"Retrieved {len(rows)} agent-pipeline mappings from '{self.table_name}'.")
            updated_rows = [dict(row) for row in rows]
            await self._transform_emails_to_usernames(updated_rows, ['agent_created_by', 'pipeline_created_by'])
            return updated_rows
        except Exception as e:
            log.error(f"Error retrieving agent-pipeline mappings: {e}")
            return []

    async def remove_agent_from_pipeline_record(self, agentic_application_id: Optional[str] = None, pipeline_id: Optional[str] = None) -> bool:
        """
        Removes a mapping between an agent/worker_pipeline and a pipeline.

        Args:
            agentic_application_id (Optional[str]): The ID of the agent or worker pipeline to remove.
            pipeline_id (Optional[str]): The ID of the pipeline to remove the mapping from.

        Returns:
            bool: True if the mapping was removed successfully, False otherwise.
        """
        delete_statement = f"DELETE FROM {self.table_name}"
        where_clause = []
        values = []

        filters = {"agentic_application_id": agentic_application_id, "pipeline_id": pipeline_id}
        for idx, (field, value) in enumerate((f for f in filters.items() if f[1] is not None), start=1):
            where_clause.append(f"{field} = ${idx}")
            values.append(value)

        if where_clause:
            delete_statement += " WHERE " + " AND ".join(where_clause)
            try:
                async with self.pool.acquire() as conn:
                    result = await conn.execute(delete_statement, *values)
                if result != "DELETE 0":
                    await self.invalidate_all_method_cache("get_agent_pipeline_mappings_record")
                    await self.invalidate_all_method_cache("get_pipeline", namespace="PipelineRepository")
                    log.info(f"Mapping agent/pipeline '{agentic_application_id}' from pipeline '{pipeline_id}' removed successfully.")
                    return True
                else:
                    log.warning(f"Mapping agent/pipeline '{agentic_application_id}' from pipeline '{pipeline_id}' not found, no deletion performed.")
                    return False
            except Exception as e:
                log.error(f"Error removing agent/pipeline mapping: {e}")
                return False
        log.warning("No criteria provided to remove_agent_from_pipeline_record, no action taken.")
        return False

    async def drop_agent_id_fk_constraint(self):
        """
        Dynamically finds and drops the foreign key constraint on agent_pipeline_mapping_table.agentic_application_id.
        This is crucial for allowing pipeline IDs (worker pipelines) to be stored in the 'agentic_application_id' column.
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
                  AND kcu.column_name = 'agentic_application_id'
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
                    await self.invalidate_all_method_cache("get_agent_pipeline_mappings_record")
                    log.info(f"Successfully dropped foreign key constraint '{constraint_name}' on '{self.table_name}.agentic_application_id'.")
                    return True
                else:
                    log.info(f"No foreign key constraint found on '{self.table_name}.agentic_application_id' to drop. (This is expected if already removed).")
                    return False

        except Exception as e:
            log.error(f"Error attempting to drop foreign key constraint on '{self.table_name}.agentic_application_id': {e}")
            return False

    async def migrate_pipelines_to_agent_mappings(self) -> Dict[str, Any]:
        """
        Migration function that scans all pipelines, extracts agent IDs from pipeline_definition,
        and creates agent-pipeline mappings in agent_pipeline_mapping_table.
        
        This extracts agent IDs from the 'nodes' array in pipeline_definition JSONB where
        each node has a 'data' object containing 'agent_id' or 'agentic_application_id'.
        
        Skips agents that don't exist in the agent_table.
        
        Checks migration-info.json file before running - if migration already completed, skips.
        Updates the file after successful migration.
        
        Returns:
            Dict with migration stats: total_pipelines, mappings_created, mappings_skipped, agents_not_found, errors
        """
        MIGRATION_ID = "pipeline_agent_mapping_v1"
        MIGRATION_INFO_FILE = "migration-info.json"
        
        stats = {
            "total_pipelines": 0,
            "mappings_created": 0,
            "mappings_skipped": 0,
            "agents_not_found": 0,
            "errors": []
        }
        
        # Check if migration already completed
        try:
            if os.path.exists(MIGRATION_INFO_FILE):
                with open(MIGRATION_INFO_FILE, 'r') as f:
                    migration_info = json.load(f)
                if MIGRATION_ID in migration_info.get("completed_migrations", []):
                    log.info(f"Migration '{MIGRATION_ID}' already completed. Skipping.")
                    return {"skipped": True, "reason": f"Migration '{MIGRATION_ID}' already completed"}
        except Exception as e:
            log.warning(f"Could not read migration-info file: {e}. Proceeding with migration.")
        
        try:
            # Fetch all pipelines with their definitions
            fetch_pipelines_query = f"""
                SELECT pipeline_id, pipeline_name, pipeline_definition, created_by 
                FROM {TableNames.PIPELINES.value}
            """
            
            async with self.pool.acquire() as conn:
                pipelines = await conn.fetch(fetch_pipelines_query)
            
            stats["total_pipelines"] = len(pipelines)
            log.info(f"Migration: Found {len(pipelines)} pipelines to process.")
            
            for pipeline in pipelines:
                pipeline_id = pipeline['pipeline_id']
                pipeline_created_by = pipeline['created_by']
                pipeline_definition = pipeline['pipeline_definition']
                
                # Extract agent IDs from pipeline_definition nodes
                agent_ids = set()
                if isinstance(pipeline_definition, str):
                    pipeline_definition = json.loads(pipeline_definition)
                if pipeline_definition and isinstance(pipeline_definition, dict):
                    nodes = pipeline_definition.get('nodes', [])
                    for node in nodes:
                        if isinstance(node, dict) and node.get('node_type') == 'agent':
                            data = node.get('config', {})
                            if isinstance(data, dict):
                                # Try different possible keys for agent ID
                                agent_id = data.get('agent_id')
                                if agent_id:
                                    agent_ids.add(agent_id)
                
                # Create mappings for each agent found
                for agent_id in agent_ids:
                    try:
                        # Check if agent exists in agent_table
                        agent_exists_query = f"""
                            SELECT 1 FROM {TableNames.AGENT.value} 
                            WHERE agentic_application_id = $1
                        """
                        async with self.pool.acquire() as conn:
                            agent_exists = await conn.fetchrow(agent_exists_query, agent_id)
                        
                        if not agent_exists:
                            stats["agents_not_found"] += 1
                            log.warning(f"Migration: Agent '{agent_id}' not found in database, skipping mapping to pipeline '{pipeline_id}'")
                            continue
                        
                        # Check if mapping already exists
                        check_query = f"""
                            SELECT 1 FROM {self.table_name} 
                            WHERE agentic_application_id = $1 AND pipeline_id = $2
                        """
                        async with self.pool.acquire() as conn:
                            existing = await conn.fetchrow(check_query, agent_id, pipeline_id)
                        
                        if existing:
                            stats["mappings_skipped"] += 1
                            log.debug(f"Migration: Mapping already exists for agent '{agent_id}' -> pipeline '{pipeline_id}'")
                            continue
                        
                        # Get the actual agent creator from agent_table
                        agent_creator_query = f"""
                            SELECT created_by FROM {TableNames.AGENT.value} 
                            WHERE agentic_application_id = $1
                        """
                        async with self.pool.acquire() as conn:
                            agent_record = await conn.fetchrow(agent_creator_query, agent_id)
                        
                        agent_created_by = agent_record['created_by'] if agent_record and agent_record['created_by'] else pipeline_created_by
                        
                        # Insert new mapping
                        insert_query = f"""
                            INSERT INTO {self.table_name} (agentic_application_id, pipeline_id, agent_created_by, pipeline_created_by)
                            VALUES ($1, $2, $3, $4)
                        """
                        async with self.pool.acquire() as conn:
                            await conn.execute(insert_query, agent_id, pipeline_id, agent_created_by, pipeline_created_by)
                        
                        stats["mappings_created"] += 1
                        log.info(f"Migration: Created mapping for agent '{agent_id}' -> pipeline '{pipeline_id}'")
                        
                    except Exception as e:
                        error_msg = f"Error creating mapping for agent '{agent_id}' -> pipeline '{pipeline_id}': {str(e)}"
                        stats["errors"].append(error_msg)
                        log.error(f"Migration: {error_msg}")
            
            # Invalidate cache after migration
            await self.invalidate_all_method_cache("get_agent_pipeline_mappings_record")
            
            # Update migration-info file to mark this migration as completed
            try:
                migration_info = {"completed_migrations": []}
                if os.path.exists(MIGRATION_INFO_FILE):
                    with open(MIGRATION_INFO_FILE, 'r') as f:
                        migration_info = json.load(f)
                
                if "completed_migrations" not in migration_info:
                    migration_info["completed_migrations"] = []
                
                if MIGRATION_ID not in migration_info["completed_migrations"]:
                    migration_info["completed_migrations"].append(MIGRATION_ID)
                    migration_info[MIGRATION_ID] = {
                        "completed_at": datetime.now().isoformat(),
                        "stats": stats
                    }
                
                with open(MIGRATION_INFO_FILE, 'w') as f:
                    json.dump(migration_info, f, indent=2)
                log.info(f"Migration '{MIGRATION_ID}' marked as completed in {MIGRATION_INFO_FILE}")
            except Exception as e:
                log.warning(f"Could not update migration-info file: {e}")
            
            log.info(f"Migration completed: {stats}")
            return stats
            
        except Exception as e:
            error_msg = f"Migration failed: {str(e)}"
            stats["errors"].append(error_msg)
            log.error(f"Migration: {error_msg}")
            return stats


# --- Pipeline Run Repository ---

class PipelineRunRepository(BaseRepository):
    """
    Repository for the 'pipelines' run table.
    Handles direct database interactions for pipeline run tracking.
    """

    def __init__(self, pool: asyncpg.Pool, login_pool: asyncpg.Pool, table_name: str = TableNames.PIPELINES_RUN.value):
        """
        Initializes the PipelineRunRepository.

        Args:
            pool (asyncpg.Pool): The asyncpg connection pool.
            login_pool (asyncpg.Pool): The asyncpg connection pool for login-related operations.
            table_name (str): The name of the pipelines run table.
        """
        super().__init__(pool, login_pool, table_name)

    async def create_table_if_not_exists(self) -> None:
        """
        Creates the 'pipelines' run table in PostgreSQL if it does not exist.
        """
        try:
            create_statement = f"""
            CREATE TABLE IF NOT EXISTS {self.table_name} (
                id TEXT PRIMARY KEY,
                pipeline_id TEXT,
                session_id TEXT,
                user_query TEXT NOT NULL,
                final_response TEXT,
                status TEXT NOT NULL,
                response_time FLOAT,
                created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
                completed_at TIMESTAMP WITH TIME ZONE
            );
            CREATE INDEX IF NOT EXISTS idx_pipelines_status ON {self.table_name}(status);
            CREATE INDEX IF NOT EXISTS idx_pipelines_session ON {self.table_name}(session_id);
            CREATE INDEX IF NOT EXISTS idx_pipelines_pipeline_session ON {self.table_name}(pipeline_id, session_id);
            """
            async with self.pool.acquire() as conn:
                await conn.execute(create_statement)
            log.info(f"Table '{self.table_name}' created successfully or already exists.")
        except Exception as e:
            log.error(f"Error creating table '{self.table_name}': {e}")

    async def create_run(self, run_id: str, user_query: str, pipeline_id: str = None, session_id: str = None, status: str = "pending") -> bool:
        """
        Insert a run record into pipelines table.

        Args:
            run_id: Unique identifier for this run
            user_query: The user's input query
            pipeline_id: The pipeline definition ID
            session_id: The user session ID for conversation tracking
            status: Initial status (default: pending)

        Returns:
            bool: True if successful, False otherwise
        """
        await self.create_table_if_not_exists()
        try:
            async with self.pool.acquire() as conn:
                await conn.execute(
                    f"INSERT INTO {self.table_name}(id, pipeline_id, session_id, user_query, status, created_at) VALUES($1, $2, $3, $4, $5, CURRENT_TIMESTAMP) ON CONFLICT(id) DO NOTHING",
                    run_id,
                    pipeline_id,
                    session_id,
                    user_query,
                    status,
                )
            log.info(f"Pipeline run '{run_id}' created successfully with status '{status}'.")
            return True
        except Exception as e:
            log.error(f"Error creating pipeline run '{run_id}': {e}")
            return False

    async def update_status(self, run_id: str, status: str, final_response: Optional[str] = None, response_time: Optional[float] = None) -> bool:
        """
        Update run status and optionally final response.

        Args:
            run_id: The run ID to update
            status: New status value
            final_response: Optional final response text
            response_time: Optional response time in seconds

        Returns:
            bool: True if successful, False otherwise
        """
        await self.create_table_if_not_exists()
        try:
            async with self.pool.acquire() as conn:
                if final_response is not None:
                    await conn.execute(
                        f"UPDATE {self.table_name} SET status = $2, final_response = $3, response_time = $4, completed_at = CURRENT_TIMESTAMP WHERE id = $1",
                        run_id,
                        status,
                        final_response,
                        response_time,
                    )
                else:
                    await conn.execute(
                        f"UPDATE {self.table_name} SET status = $2 WHERE id = $1",
                        run_id,
                        status,
                    )
            log.info(f"Pipeline run '{run_id}' status updated to '{status}'.")
            return True
        except Exception as e:
            log.error(f"Error updating pipeline run status for '{run_id}': {e}")
            return False

    async def get_run(self, run_id: str) -> Optional[Dict[str, Any]]:
        """
        Get a pipeline run by ID.

        Args:
            run_id: The run ID to retrieve

        Returns:
            Dict with run details or None if not found
        """
        query = f"SELECT * FROM {self.table_name} WHERE id = $1"
        try:
            async with self.pool.acquire() as conn:
                row = await conn.fetchrow(query, run_id)
            if row:
                return dict(row)
            return None
        except Exception as e:
            log.error(f"Error retrieving pipeline run '{run_id}': {e}")
            return None

    async def get_runs_by_session(self, pipeline_id: str, session_id: str, limit: int = 50) -> List[Dict[str, Any]]:
        """
        Get pipeline runs by pipeline_id and session_id for conversation history.

        Args:
            pipeline_id: The pipeline definition ID
            session_id: The user session ID
            limit: Maximum number of records to return

        Returns:
            List of run dictionaries ordered by created_at descending
        """
        query = f"SELECT * FROM {self.table_name} WHERE pipeline_id = $1 AND session_id = $2 AND status = 'completed' ORDER BY created_at DESC LIMIT $3"
        try:
            async with self.pool.acquire() as conn:
                rows = await conn.fetch(query, pipeline_id, session_id, limit)
            return [dict(row) for row in rows]
        except Exception as e:
            log.error(f"Error retrieving pipeline runs by session '{session_id}': {e}")
            return []

    async def get_runs_by_status(self, status: str, limit: int = 50) -> List[Dict[str, Any]]:
        """
        Get pipeline runs by status.

        Args:
            status: The status to filter by
            limit: Maximum number of records to return

        Returns:
            List of run dictionaries
        """
        query = f"SELECT * FROM {self.table_name} WHERE status = $1 LIMIT $2"
        try:
            async with self.pool.acquire() as conn:
                rows = await conn.fetch(query, status, limit)
            return [dict(row) for row in rows]
        except Exception as e:
            log.error(f"Error retrieving pipeline runs by status '{status}': {e}")
            return []

    async def delete_runs_by_session(self, pipeline_id: str, session_id: str) -> bool:
        """
        Delete all pipeline runs for a given pipeline_id and session_id.

        Args:
            pipeline_id: The pipeline definition ID
            session_id: The user session ID

        Returns:
            bool: True if successful, False otherwise
        """
        query = f"DELETE FROM {self.table_name} WHERE pipeline_id = $1 AND session_id = $2"
        try:
            async with self.pool.acquire() as conn:
                await conn.execute(query, pipeline_id, session_id)
            log.info(f"Pipeline runs deleted for pipeline '{pipeline_id}' and session '{session_id}'.")
            return True
        except Exception as e:
            log.error(f"Error deleting pipeline runs for session '{session_id}': {e}")
            return False

    async def get_run_ids_by_session(self, pipeline_id: str, session_id: str) -> List[str]:
        """
        Get all run IDs for a given pipeline_id and session_id.

        Args:
            pipeline_id: The pipeline definition ID
            session_id: The user session ID

        Returns:
            List of run IDs
        """
        query = f"SELECT id FROM {self.table_name} WHERE pipeline_id = $1 AND session_id = $2"
        try:
            async with self.pool.acquire() as conn:
                rows = await conn.fetch(query, pipeline_id, session_id)
            return [row['id'] for row in rows]
        except Exception as e:
            log.error(f"Error getting run IDs for session '{session_id}': {e}")
            return []

    async def get_sessions_by_user_and_pipeline(self, user_email: str, pipeline_id: str) -> List[Dict[str, Any]]:
        """
        Get distinct sessions for a user and pipeline.
        Session IDs typically contain the user email (e.g., "user@example.com_sessionname").

        Args:
            user_email: The user's email address
            pipeline_id: The pipeline definition ID

        Returns:
            List of dicts with session_id and latest timestamp
        """
        query = f"""
            SELECT DISTINCT session_id, MAX(created_at) as latest_timestamp
            FROM {self.table_name}
            WHERE pipeline_id = $1 AND session_id LIKE $2 AND status = 'completed'
            GROUP BY session_id
            ORDER BY latest_timestamp DESC
        """
        try:
            async with self.pool.acquire() as conn:
                rows = await conn.fetch(query, pipeline_id, f"{user_email}%")
            return [dict(row) for row in rows]
        except Exception as e:
            log.error(f"Error getting sessions for user '{user_email}' and pipeline '{pipeline_id}': {e}")
            return []


# --- Pipeline Steps Repository ---

class PipelineStepsRepository(BaseRepository):
    """
    Repository for the 'pipeline_steps' table.
    Handles direct database interactions for pipeline step tracking.
    """

    def __init__(self, pool: asyncpg.Pool, login_pool: asyncpg.Pool, table_name: str = TableNames.PIPELINE_STEPS.value):
        """
        Initializes the PipelineStepsRepository.

        Args:
            pool (asyncpg.Pool): The asyncpg connection pool.
            login_pool (asyncpg.Pool): The asyncpg connection pool for login-related operations.
            table_name (str): The name of the pipeline steps table.
        """
        super().__init__(pool, login_pool, table_name)

    async def create_table_if_not_exists(self) -> None:
        """
        Creates the 'pipeline_steps' table in PostgreSQL if it does not exist.
        """
        try:
            create_statement = f"""
            CREATE TABLE IF NOT EXISTS {self.table_name} (
                id TEXT PRIMARY KEY,
                pipeline_id TEXT NOT NULL,
                step_order INT NOT NULL,
                agent_id TEXT,
                step_data JSONB,
                created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
            );
            CREATE INDEX IF NOT EXISTS idx_pipeline_steps_pipeline ON {self.table_name}(pipeline_id);
            CREATE INDEX IF NOT EXISTS idx_pipeline_steps_order ON {self.table_name}(step_order);
            """
            async with self.pool.acquire() as conn:
                await conn.execute(create_statement)
            log.info(f"Table '{self.table_name}' created successfully or already exists.")
        except Exception as e:
            log.error(f"Error creating table '{self.table_name}': {e}")

    async def add_step(self, run_id: str, step_order: int, agent_id: str, step_data: dict) -> bool:
        """
        Insert a step record for a pipeline run.

        Args:
            run_id: The pipeline run ID (foreign key to pipelines table)
            step_order: The order/sequence of this step in the pipeline
            agent_id: The agent ID that executed this step
            step_data: JSON data containing step execution details

        Returns:
            bool: True if successful, False otherwise
        """
        await self.create_table_if_not_exists()
        try:
            step_id = str(uuid.uuid4())
            async with self.pool.acquire() as conn:
                await conn.execute(
                    f"INSERT INTO {self.table_name}(id, pipeline_id, step_order, agent_id, step_data) VALUES($1, $2, $3, $4, $5)",
                    step_id,
                    run_id,
                    step_order,
                    agent_id,
                    json.dumps(step_data) if step_data is not None else json.dumps({}),
                )
            log.info(f"Pipeline step added for run '{run_id}' with order {step_order}.")
            return True
        except Exception as e:
            log.error(f"Error adding pipeline step for run '{run_id}': {e}")
            return False

    async def get_steps_by_run(self, run_id: str) -> List[Dict[str, Any]]:
        """
        Get all steps for a pipeline run.

        Args:
            run_id: The pipeline run ID

        Returns:
            List of step dictionaries ordered by step_order
        """
        query = f"SELECT * FROM {self.table_name} WHERE pipeline_id = $1 ORDER BY step_order ASC"
        try:
            async with self.pool.acquire() as conn:
                rows = await conn.fetch(query, run_id)
            result = []
            for row in rows:
                row_dict = dict(row)
                if row_dict.get('step_data') and isinstance(row_dict['step_data'], str):
                    row_dict['step_data'] = json.loads(row_dict['step_data'])
                result.append(row_dict)
            return result
        except Exception as e:
            log.error(f"Error retrieving pipeline steps for run '{run_id}': {e}")
            return []

    async def get_step(self, step_id: str) -> Optional[Dict[str, Any]]:
        """
        Get a specific step by ID.

        Args:
            step_id: The step ID to retrieve

        Returns:
            Dict with step details or None if not found
        """
        query = f"SELECT * FROM {self.table_name} WHERE id = $1"
        try:
            async with self.pool.acquire() as conn:
                row = await conn.fetchrow(query, step_id)
            if row:
                row_dict = dict(row)
                if row_dict.get('step_data') and isinstance(row_dict['step_data'], str):
                    row_dict['step_data'] = json.loads(row_dict['step_data'])
                return row_dict
            return None
        except Exception as e:
            log.error(f"Error retrieving pipeline step '{step_id}': {e}")
            return None

    async def get_latest_step_order(self, run_id: str) -> int:
        """
        Get the latest step order for a pipeline run.

        Args:
            run_id: The pipeline run ID

        Returns:
            int: The latest step order, or 0 if no steps exist
        """
        query = f"SELECT MAX(step_order) FROM {self.table_name} WHERE pipeline_id = $1"
        try:
            async with self.pool.acquire() as conn:
                result = await conn.fetchval(query, run_id)
            return result or 0
        except Exception as e:
            log.error(f"Error getting latest step order for run '{run_id}': {e}")
            return 0

    async def delete_steps_by_run(self, run_id: str) -> bool:
        """
        Delete all steps for a pipeline run.

        Args:
            run_id: The pipeline run ID

        Returns:
            bool: True if successful, False otherwise
        """
        query = f"DELETE FROM {self.table_name} WHERE pipeline_id = $1"
        try:
            async with self.pool.acquire() as conn:
                await conn.execute(query, run_id)
            log.info(f"Pipeline steps deleted for run '{run_id}'.")
            return True
        except Exception as e:
            log.error(f"Error deleting pipeline steps for run '{run_id}': {e}")
            return False


# --- Knowledgebase Repository ---

class KnowledgebaseRepository(BaseRepository):
    """
    Repository for managing knowledge base records.
    Stores KB metadata in knowledgebase_table.
    """

    def __init__(self, pool: asyncpg.Pool, login_pool: asyncpg.Pool, table_name: str = TableNames.KNOWLEDGEBASE.value):
        super().__init__(pool, login_pool, table_name)

    async def create_table_if_not_exists(self):
        """
        Creates the 'knowledgebase_table' in PostgreSQL if it does not exist.
        """
        try:
            create_statement = f"""
            CREATE TABLE IF NOT EXISTS {self.table_name} (
                knowledgebase_id TEXT PRIMARY KEY,
                knowledgebase_name TEXT NOT NULL,
                list_of_documents TEXT,
                created_by TEXT NOT NULL,
                department_name TEXT DEFAULT 'General',
                is_public BOOLEAN DEFAULT FALSE,
                created_on TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
                updated_on TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(knowledgebase_name, department_name)
            );
            """

            async with self.pool.acquire() as conn:
                await conn.execute(create_statement)
                
                # Migration: Add department_name column if it doesn't exist (for existing tables)
                try:
                    await conn.execute(f"ALTER TABLE {self.table_name} ADD COLUMN IF NOT EXISTS department_name TEXT DEFAULT 'General'")
                except Exception as e:
                    log.debug(f"department_name column may already exist: {e}")
                
                # Migration: Add is_public column if it doesn't exist
                try:
                    await conn.execute(f"ALTER TABLE {self.table_name} ADD COLUMN IF NOT EXISTS is_public BOOLEAN DEFAULT FALSE")
                except Exception as e:
                    log.debug(f"is_public column may already exist: {e}")
                
                # Migration: Drop old unique constraint on knowledgebase_name only, add composite unique on (knowledgebase_name, department_name)
                try:
                    await conn.execute(f"ALTER TABLE {self.table_name} DROP CONSTRAINT IF EXISTS {self.table_name}_knowledgebase_name_key")
                    await conn.execute(f"""
                        DO $$ BEGIN
                        IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = '{self.table_name}_knowledgebase_name_department_name_key') THEN
                        ALTER TABLE {self.table_name} ADD CONSTRAINT {self.table_name}_knowledgebase_name_department_name_key UNIQUE (knowledgebase_name, department_name);
                        END IF;
                        END $$;
                    """)
                    log.info(f"Migrated unique constraint to (knowledgebase_name, department_name) for {self.table_name}")
                except Exception as e:
                    log.debug(f"Unique constraint migration may have already completed: {e}")

            log.info(f"Table '{self.table_name}' created successfully or already exists.")
        except Exception as e:
            log.error(f"Error creating table '{self.table_name}': {e}")

    async def save_knowledgebase_record(self, kb_data: Dict[str, Any]) -> bool:
        """
        Inserts a new knowledgebase record into the knowledgebase table.
        Returns True if inserted, False if already exists.
        """
        insert_statement = f"""
        INSERT INTO {self.table_name} 
        (knowledgebase_id, knowledgebase_name, list_of_documents, created_by, department_name, is_public, created_on)
        VALUES ($1, $2, $3, $4, $5, $6, $7)
        ON CONFLICT (knowledgebase_name, department_name) DO NOTHING
        RETURNING knowledgebase_id
        """
        
        try:
            # Convert list to comma-separated string
            docs_list = kb_data.get("list_of_documents", [])
            docs_str = ",".join(docs_list) if isinstance(docs_list, list) else str(docs_list)
            
            async with self.pool.acquire() as conn:
                result = await conn.fetchrow(
                    insert_statement,
                    kb_data.get("knowledgebase_id"),
                    kb_data.get("knowledgebase_name"),
                    docs_str,
                    kb_data.get("created_by", "system"),
                    kb_data.get("department_name", "General"),
                    kb_data.get("is_public", False),
                    kb_data.get("created_on")
                )
                
                if result:
                    log.info(f"Knowledge base '{kb_data.get('knowledgebase_name')}' created successfully")
                    return True
                else:
                    log.warning(f"Knowledge base '{kb_data.get('knowledgebase_name')}' already exists")
                    return False
                    
        except Exception as e:
            log.error(f"Error saving knowledgebase record: {e}")
            raise

    async def update_kb_visibility(self, kb_id: str, is_public: bool) -> bool:
        """
        Updates the is_public flag for a knowledge base.
        
        Args:
            kb_id (str): The knowledge base ID.
            is_public (bool): Whether the KB should be publicly accessible.
        
        Returns:
            bool: True if updated, False if KB not found.
        """
        update_statement = f"""
        UPDATE {self.table_name}
        SET is_public = $1, updated_on = CURRENT_TIMESTAMP
        WHERE knowledgebase_id = $2
        RETURNING knowledgebase_id
        """
        try:
            async with self.pool.acquire() as conn:
                result = await conn.fetchrow(update_statement, is_public, kb_id)
            if result:
                log.info(f"KB '{kb_id}' visibility updated to is_public={is_public}")
                return True
            else:
                log.warning(f"KB '{kb_id}' not found for visibility update")
                return False
        except Exception as e:
            log.error(f"Error updating KB visibility for '{kb_id}': {e}")
            raise

    async def get_all_knowledgebase_records(self, department_name: str = None) -> List[Dict[str, Any]]:
        """Retrieve all knowledgebase records, optionally filtered by department. Also includes public KBs from other departments."""
        if department_name:
            select_statement = f"SELECT * FROM {self.table_name} WHERE department_name = $1 OR is_public = TRUE ORDER BY created_on DESC"
            params = [department_name]
        else:
            select_statement = f"SELECT * FROM {self.table_name} ORDER BY created_on DESC"
            params = []
        
        try:
            async with self.pool.acquire() as conn:
                records = await conn.fetch(select_statement, *params)
                kb_list = [dict(record) for record in records]
                
                # Transform emails to usernames
                kb_list = await self._transform_emails_to_usernames(kb_list, ['created_by'])
                
                log.info(f"Retrieved {len(kb_list)} knowledge base records")
                return kb_list
                
        except Exception as e:
            log.error(f"Error retrieving knowledgebase records: {e}")
            raise

    async def get_knowledgebase_by_id(self, kb_id: str) -> Optional[Dict[str, Any]]:
        """Retrieve a specific knowledgebase record by ID."""
        select_statement = f"SELECT * FROM {self.table_name} WHERE knowledgebase_id = $1"
        
        try:
            async with self.pool.acquire() as conn:
                record = await conn.fetchrow(select_statement, kb_id)
                
                if record:
                    kb_dict = dict(record)
                    # Transform emails to usernames
                    kb_list = await self._transform_emails_to_usernames([kb_dict], ['created_by'])
                    return kb_list[0] if kb_list else kb_dict
                
                return None
                
        except Exception as e:
            log.error(f"Error retrieving knowledgebase by ID: {e}")
            raise

    async def get_knowledgebase_by_name(self, kb_name: str, department_name: str = None) -> Optional[Dict[str, Any]]:
        """Retrieve a specific knowledgebase record by name, optionally filtered by department."""
        if department_name:
            select_statement = f"SELECT * FROM {self.table_name} WHERE knowledgebase_name = $1 AND department_name = $2"
            params = [kb_name, department_name]
        else:
            select_statement = f"SELECT * FROM {self.table_name} WHERE knowledgebase_name = $1"
            params = [kb_name]
        
        try:
            async with self.pool.acquire() as conn:
                record = await conn.fetchrow(select_statement, *params)
                
                if record:
                    kb_dict = dict(record)
                    # Transform emails to usernames
                    kb_list = await self._transform_emails_to_usernames([kb_dict], ['created_by'])
                    return kb_list[0] if kb_list else kb_dict
                
                return None
                
        except Exception as e:
            log.error(f"Error retrieving knowledgebase by name: {e}")
            raise

    async def delete_knowledgebase(self, kb_id: str) -> bool:
        """Delete a knowledgebase record."""
        delete_statement = f"DELETE FROM {self.table_name} WHERE knowledgebase_id = $1"
        
        try:
            async with self.pool.acquire() as conn:
                result = await conn.execute(delete_statement, kb_id)
                
                deleted = result.split()[-1] != "0" if result else False
                if deleted:
                    log.info(f"Knowledge base {kb_id} deleted successfully")
                else:
                    log.warning(f"Knowledge base {kb_id} not found for deletion")
                
                return deleted
                
        except Exception as e:
            log.error(f"Error deleting knowledgebase: {e}")
            raise

    async def get_all_knowledgebase_records_with_emails(self, department_name: str = None) -> List[Dict[str, Any]]:
        """Retrieve all knowledgebase records without transforming emails to usernames."""
        if department_name:
            select_statement = f"SELECT * FROM {self.table_name} WHERE department_name = $1 ORDER BY created_on DESC"
            params = [department_name]
        else:
            select_statement = f"SELECT * FROM {self.table_name} ORDER BY created_on DESC"
            params = []
        
        try:
            async with self.pool.acquire() as conn:
                records = await conn.fetch(select_statement, *params)
                kb_list = [dict(record) for record in records]
                
                log.info(f"Retrieved {len(kb_list)} knowledge base records with original emails")
                return kb_list
                
        except Exception as e:
            log.error(f"Error retrieving knowledgebase records: {e}")
            raise

    async def get_knowledgebase_by_id_with_email(self, kb_id: str) -> Optional[Dict[str, Any]]:
        """Retrieve a specific knowledgebase record by ID without transforming email to username."""
        select_statement = f"SELECT * FROM {self.table_name} WHERE knowledgebase_id = $1"
        
        try:
            async with self.pool.acquire() as conn:
                record = await conn.fetchrow(select_statement, kb_id)
                
                if record:
                    return dict(record)
                
                return None
                
        except Exception as e:
            log.error(f"Error retrieving knowledgebase by ID: {e}")
            raise

    async def get_knowledgebases_by_ids_with_email(self, kb_ids: List[str]) -> List[Dict[str, Any]]:
        """Retrieve multiple knowledgebase records by IDs in a single query without transforming emails."""
        select_statement = f"SELECT * FROM {self.table_name} WHERE knowledgebase_id = ANY($1)"
        
        try:
            async with self.pool.acquire() as conn:
                records = await conn.fetch(select_statement, kb_ids)
                kb_list = [dict(record) for record in records]
                
                log.info(f"Retrieved {len(kb_list)} knowledge base records with original emails")
                return kb_list
                
        except Exception as e:
            log.error(f"Error retrieving knowledgebases by IDs: {e}")
            raise


# --- Agent Knowledgebase Mapping Repository ---

class AgentKnowledgebaseMappingRepository(BaseRepository):
    """
    Repository for managing agent-to-knowledgebase mappings.
    Links agents to their associated knowledge bases.
    """

    def __init__(self, pool: asyncpg.Pool, login_pool: asyncpg.Pool, table_name: str = TableNames.AGENT_KNOWLEDGEBASE_MAPPING.value):
        super().__init__(pool, login_pool, table_name)

    async def create_table_if_not_exists(self):
        """
        Creates the 'agent_knowledgebase_mapping_table' in PostgreSQL if it does not exist.
        """
        try:
            create_statement = f"""
            CREATE TABLE IF NOT EXISTS {self.table_name} (
                agentic_application_id TEXT PRIMARY KEY,
                knowledgebase_ids TEXT[],
                created_on TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
                updated_on TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
            );
            """

            async with self.pool.acquire() as conn:
                await conn.execute(create_statement)

            log.info(f"Table '{self.table_name}' created successfully or already exists.")
        except Exception as e:
            log.error(f"Error creating table '{self.table_name}': {e}")

    async def set_knowledgebases_for_agent(
        self,
        agentic_application_id: str,
        knowledgebase_ids: List[str]
    ) -> bool:
        """Set knowledge base IDs for an agent (replaces existing)."""
        upsert_statement = f"""
        INSERT INTO {self.table_name} 
        (agentic_application_id, knowledgebase_ids, created_on, updated_on)
        VALUES ($1, $2, $3, $3)
        ON CONFLICT (agentic_application_id) 
        DO UPDATE SET 
            knowledgebase_ids = EXCLUDED.knowledgebase_ids,
            updated_on = EXCLUDED.updated_on
        """
        
        try:
            now = datetime.now(timezone.utc)
            async with self.pool.acquire() as conn:
                await conn.execute(upsert_statement, agentic_application_id, knowledgebase_ids, now)
            
            log.info(f"Set {len(knowledgebase_ids)} knowledge bases for agent {agentic_application_id}")
            return True
            
        except Exception as e:
            log.error(f"Error setting knowledge bases for agent: {e}")
            raise

    async def add_knowledgebases_to_agent(
        self,
        agentic_application_id: str,
        knowledgebase_ids: List[str]
    ) -> bool:
        """Add knowledge base IDs to agent's existing list."""
        update_statement = f"""
        INSERT INTO {self.table_name} 
        (agentic_application_id, knowledgebase_ids, created_on, updated_on)
        VALUES ($1, $2, $3, $3)
        ON CONFLICT (agentic_application_id) 
        DO UPDATE SET 
            knowledgebase_ids = ARRAY(SELECT DISTINCT unnest({self.table_name}.knowledgebase_ids || EXCLUDED.knowledgebase_ids)),
            updated_on = EXCLUDED.updated_on
        """
        
        try:
            now = datetime.now(timezone.utc)
            async with self.pool.acquire() as conn:
                await conn.execute(update_statement, agentic_application_id, knowledgebase_ids, now)
            
            log.info(f"Added {len(knowledgebase_ids)} knowledge bases to agent {agentic_application_id}")
            return True
            
        except Exception as e:
            log.error(f"Error adding knowledge bases to agent: {e}")
            raise

    async def remove_knowledgebases_from_agent(
        self,
        agentic_application_id: str,
        knowledgebase_ids: List[str]
    ) -> bool:
        """Remove knowledge base IDs from agent's list."""
        update_statement = f"""
        UPDATE {self.table_name}
        SET 
            knowledgebase_ids = ARRAY(SELECT unnest(knowledgebase_ids) EXCEPT SELECT unnest($2::TEXT[])),
            updated_on = $3
        WHERE agentic_application_id = $1
        """
        
        try:
            now = datetime.now(timezone.utc)
            async with self.pool.acquire() as conn:
                result = await conn.execute(update_statement, agentic_application_id, knowledgebase_ids, now)
            
            log.info(f"Removed {len(knowledgebase_ids)} knowledge bases from agent {agentic_application_id}")
            return True
            
        except Exception as e:
            log.error(f"Error removing knowledge bases from agent: {e}")
            raise

    async def get_knowledgebases_for_agent(
        self,
        agentic_application_id: str
    ) -> List[Dict[str, Any]]:
        """Retrieve all knowledge bases associated with an agent."""
        query = f"""
        SELECT kb.* FROM knowledgebase_table kb
        WHERE kb.knowledgebase_id = ANY(
            SELECT unnest(knowledgebase_ids) FROM {self.table_name}
            WHERE agentic_application_id = $1
        )
        ORDER BY kb.created_on DESC
        """
        
        try:
            async with self.pool.acquire() as conn:
                records = await conn.fetch(query, agentic_application_id)
                kb_list = [dict(record) for record in records]
                
                # Transform emails to usernames
                kb_list = await self._transform_emails_to_usernames(kb_list, ['created_by'])
                
                log.info(f"Retrieved {len(kb_list)} knowledge bases for agent {agentic_application_id}")
                return kb_list
                
        except Exception as e:
            log.error(f"Error retrieving knowledge bases for agent: {e}")
            raise

    async def get_knowledgebase_ids_for_agent(
        self,
        agentic_application_id: str
    ) -> List[str]:
        """Retrieve knowledge base IDs for an agent."""
        query = f"""
        SELECT knowledgebase_ids FROM {self.table_name}
        WHERE agentic_application_id = $1
        """
        
        try:
            async with self.pool.acquire() as conn:
                record = await conn.fetchrow(query, agentic_application_id)
                
                if record and record['knowledgebase_ids']:
                    return list(record['knowledgebase_ids'])
                return []
                
        except Exception as e:
            log.error(f"Error retrieving knowledge base IDs for agent: {e}")
            raise

    async def unlink_all_knowledgebases_from_agent(self, agentic_application_id: str) -> int:
        """Remove all knowledge base associations from an agent."""
        delete_statement = f"""
        DELETE FROM {self.table_name} 
        WHERE agentic_application_id = $1
        """
        
        try:
            async with self.pool.acquire() as conn:
                result = await conn.execute(delete_statement, agentic_application_id)
            
            deleted_count = int(result.split()[-1]) if result else 0
            
            log.info(f"Unlinked {deleted_count} knowledge bases from agent {agentic_application_id}")
            return deleted_count
            
        except Exception as e:
            log.error(f"Error unlinking all knowledge bases from agent: {e}")
            raise

    async def get_agents_using_knowledgebase(self, kb_id: str) -> List[Dict[str, Any]]:
        """Get all agents that are using a specific knowledgebase."""
        query = f"""
        SELECT akm.agentic_application_id, a.agentic_application_name
        FROM {self.table_name} akm
        JOIN agent_table a ON akm.agentic_application_id = a.agentic_application_id
        WHERE $1 = ANY(akm.knowledgebase_ids)
        """
        
        try:
            async with self.pool.acquire() as conn:
                records = await conn.fetch(query, kb_id)
                return [dict(record) for record in records]
        except Exception as e:
            log.error(f"Error getting agents using knowledgebase {kb_id}: {e}")
            raise


# --- Tool Generation Code Versions Repository ---

class ToolGenerationCodeVersionRepository(BaseRepository):
    """
    Repository for managing code version history in tool generation sessions.
    Allows users to save checkpoints and switch between different code versions.
    """

    def __init__(self, pool: asyncpg.Pool, login_pool: asyncpg.Pool, table_name: str = TableNames.TOOL_GENERATION_CODE_VERSIONS.value):
        """
        Initializes the ToolGenerationCodeVersionRepository.

        Args:
            pool (asyncpg.Pool): The asyncpg connection pool.
            login_pool (asyncpg.Pool): The asyncpg connection pool for login-related operations.
            table_name (str): The name of the code versions table.
        """
        super().__init__(pool, login_pool, table_name)


    async def create_table_if_not_exists(self):
        """
        Creates the 'tool_generation_code_versions' table in PostgreSQL if it does not exist.
        """
        try:
            create_statement = f"""
            CREATE TABLE IF NOT EXISTS {self.table_name} (
                version_id TEXT PRIMARY KEY,
                session_id TEXT NOT NULL,
                pipeline_id TEXT NOT NULL,
                version_number INTEGER NOT NULL,
                code_snippet TEXT NOT NULL,
                label TEXT,
                is_auto_saved BOOLEAN DEFAULT TRUE,
                is_current BOOLEAN DEFAULT FALSE,
                created_by TEXT NOT NULL,
                created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
                metadata JSONB DEFAULT '{{}}'::jsonb
            );
            CREATE INDEX IF NOT EXISTS idx_code_versions_session_id ON {self.table_name}(session_id);
            CREATE INDEX IF NOT EXISTS idx_code_versions_pipeline_id ON {self.table_name}(pipeline_id);
            CREATE INDEX IF NOT EXISTS idx_code_versions_session_version ON {self.table_name}(session_id, version_number);
            CREATE INDEX IF NOT EXISTS idx_code_versions_is_current ON {self.table_name}(session_id, is_current);
            """
            async with self.pool.acquire() as conn:
                await conn.execute(create_statement)
            log.info(f"Table '{self.table_name}' created successfully or already exists.")
        except Exception as e:
            log.error(f"Error creating table '{self.table_name}': {e}")

    async def save_code_version(
        self,
        session_id: str,
        pipeline_id: str,
        code_snippet: str,
        created_by: str,
        label: Optional[str] = None,
        is_auto_saved: bool = True,
        metadata: Optional[dict] = None
    ) -> Optional[Dict[str, Any]]:
        """
        Saves a new code version for a session.
        
        **Duplicate Check:** Before saving, compares with the latest version's code.
        If the code is identical (after stripping whitespace), skips saving and returns
        the existing version instead.

        Args:
            session_id: The user's session ID
            pipeline_id: The pipeline ID
            code_snippet: The code to save
            created_by: Email of the creator
            label: Optional label for the version (e.g., "Initial version", "Added error handling")
            is_auto_saved: Whether this was auto-saved or manually saved
            metadata: Optional metadata (e.g., user_query that generated this code)

        Returns:
            Dict with version details if successful, None otherwise.
            Returns existing version if code is duplicate.
        """
        # First, check if this exact code already exists in ANY version (not just latest)
        # This prevents duplicate versions when user asks for same code again
        existing_code_query = f"""
        SELECT version_id, version_number, code_snippet, created_at 
        FROM {self.table_name} 
        WHERE session_id = $1 AND TRIM(code_snippet) = TRIM($2)
        ORDER BY version_number DESC 
        LIMIT 1
        """
        
        try:
            async with self.pool.acquire() as conn:
                existing_row = await conn.fetchrow(existing_code_query, session_id, code_snippet)
                
                # If this exact code already exists in any version, return that version
                if existing_row:
                    log.info(f"Code already exists as version {existing_row['version_number']}, returning existing version for session '{session_id}'")
                    
                    # Also make this the current version since user is working with it
                    await conn.execute(
                        f"UPDATE {self.table_name} SET is_current = FALSE WHERE session_id = $1",
                        session_id
                    )
                    await conn.execute(
                        f"UPDATE {self.table_name} SET is_current = TRUE WHERE version_id = $1",
                        existing_row["version_id"]
                    )
                    
                    return {
                        "version_id": existing_row["version_id"],
                        "version_number": existing_row["version_number"],
                        "created_at": str(existing_row["created_at"]),
                        "is_current": True,
                        "is_duplicate": True
                    }
        except Exception as e:
            log.warning(f"Error checking for duplicate code: {e}, proceeding with save")
        
        version_id = f"ver_{uuid.uuid4().hex[:16]}"
        
        # Get next version number for this session
        version_number_query = f"SELECT COALESCE(MAX(version_number), 0) + 1 FROM {self.table_name} WHERE session_id = $1"
        
        # First, unset current flag on all versions for this session
        unset_current_query = f"UPDATE {self.table_name} SET is_current = FALSE WHERE session_id = $1"
        
        insert_statement = f"""
        INSERT INTO {self.table_name} 
        (version_id, session_id, pipeline_id, version_number, code_snippet, label, is_auto_saved, is_current, created_by, metadata)
        VALUES ($1, $2, $3, $4, $5, $6, $7, TRUE, $8, $9)
        RETURNING version_id, version_number, created_at
        """
        
        try:
            async with self.pool.acquire() as conn:
                async with conn.transaction():
                    # Get next version number
                    version_number = await conn.fetchval(version_number_query, session_id)
                    
                    # Unset current flag on existing versions
                    await conn.execute(unset_current_query, session_id)
                    
                    # Insert new version
                    row = await conn.fetchrow(
                        insert_statement,
                        version_id,
                        session_id,
                        pipeline_id,
                        version_number,
                        code_snippet,
                        label,
                        is_auto_saved,
                        created_by,
                        json.dumps(metadata or {})
                    )
            
            if row:
                log.info(f"Code version {version_number} saved for session '{session_id}'")
                return {
                    "version_id": row["version_id"],
                    "version_number": row["version_number"],
                    "created_at": str(row["created_at"]),
                    "is_current": True
                }
            return None
        except Exception as e:
            log.error(f"Error saving code version for session '{session_id}': {e}")
            return None

    async def get_all_versions(
        self,
        session_id: str,
        include_code: bool = False
    ) -> List[Dict[str, Any]]:
        """
        Retrieves all code versions for a session.

        Args:
            session_id: The user's session ID
            include_code: Whether to include the full code snippet in response

        Returns:
            List of version dictionaries ordered by version_number descending
        """
        columns = "version_id, session_id, pipeline_id, version_number, label, is_auto_saved, is_current, created_by, created_at, metadata"
        if include_code:
            columns += ", code_snippet"
        
        query = f"""
        SELECT {columns}
        FROM {self.table_name}
        WHERE session_id = $1
        ORDER BY version_number DESC
        """
        
        try:
            async with self.pool.acquire() as conn:
                rows = await conn.fetch(query, session_id)
            
            versions = []
            for row in rows:
                version = dict(row)
                if version.get('metadata') and isinstance(version['metadata'], str):
                    version['metadata'] = json.loads(version['metadata'])
                if version.get('created_at'):
                    version['created_at'] = str(version['created_at'])
                versions.append(version)
            
            return versions
        except Exception as e:
            log.error(f"Error retrieving code versions for session '{session_id}': {e}")
            return []

    async def get_version(
        self,
        version_id: str
    ) -> Optional[Dict[str, Any]]:
        """
        Retrieves a specific code version by ID.

        Args:
            version_id: The version ID

        Returns:
            Version dictionary if found, None otherwise
        """
        query = f"SELECT * FROM {self.table_name} WHERE version_id = $1"
        
        try:
            async with self.pool.acquire() as conn:
                row = await conn.fetchrow(query, version_id)
            
            if row:
                version = dict(row)
                if version.get('metadata') and isinstance(version['metadata'], str):
                    version['metadata'] = json.loads(version['metadata'])
                if version.get('created_at'):
                    version['created_at'] = str(version['created_at'])
                return version
            return None
        except Exception as e:
            log.error(f"Error retrieving code version '{version_id}': {e}")
            return None

    async def get_version_by_number(
        self,
        session_id: str,
        version_number: int
    ) -> Optional[Dict[str, Any]]:
        """
        Retrieves a specific code version by session_id and version_number.

        Args:
            session_id: The user's session ID
            version_number: The version number (1, 2, 3, etc.)

        Returns:
            Version dictionary if found, None otherwise
        """
        query = f"SELECT * FROM {self.table_name} WHERE session_id = $1 AND version_number = $2"
        
        try:
            async with self.pool.acquire() as conn:
                row = await conn.fetchrow(query, session_id, version_number)
            
            if row:
                version = dict(row)
                if version.get('metadata') and isinstance(version['metadata'], str):
                    version['metadata'] = json.loads(version['metadata'])
                if version.get('created_at'):
                    version['created_at'] = str(version['created_at'])
                return version
            return None
        except Exception as e:
            log.error(f"Error retrieving code version {version_number} for session '{session_id}': {e}")
            return None

    async def get_current_version(
        self,
        session_id: str
    ) -> Optional[Dict[str, Any]]:
        """
        Retrieves the current (active) code version for a session.

        Args:
            session_id: The user's session ID

        Returns:
            Current version dictionary if found, None otherwise
        """
        query = f"SELECT * FROM {self.table_name} WHERE session_id = $1 AND is_current = TRUE"
        
        try:
            async with self.pool.acquire() as conn:
                row = await conn.fetchrow(query, session_id)
            
            if row:
                version = dict(row)
                if version.get('metadata') and isinstance(version['metadata'], str):
                    version['metadata'] = json.loads(version['metadata'])
                if version.get('created_at'):
                    version['created_at'] = str(version['created_at'])
                return version
            return None
        except Exception as e:
            log.error(f"Error retrieving current code version for session '{session_id}': {e}")
            return None

    async def switch_to_version(
        self,
        session_id: str,
        version_id: str
    ) -> Optional[Dict[str, Any]]:
        """
        Switches to a specific code version, making it the current version.

        Args:
            session_id: The user's session ID
            version_id: The version ID to switch to

        Returns:
            The switched-to version dictionary if successful, None otherwise
        """
        # First verify the version belongs to this session
        verify_query = f"SELECT * FROM {self.table_name} WHERE version_id = $1 AND session_id = $2"
        unset_current_query = f"UPDATE {self.table_name} SET is_current = FALSE WHERE session_id = $1"
        set_current_query = f"UPDATE {self.table_name} SET is_current = TRUE WHERE version_id = $1"
        
        try:
            async with self.pool.acquire() as conn:
                async with conn.transaction():
                    # Verify version exists and belongs to session
                    row = await conn.fetchrow(verify_query, version_id, session_id)
                    if not row:
                        log.warning(f"Version '{version_id}' not found for session '{session_id}'")
                        return None
                    
                    # Unset current flag on all versions
                    await conn.execute(unset_current_query, session_id)
                    
                    # Set current flag on target version
                    await conn.execute(set_current_query, version_id)
            
            # Return the updated version
            version = dict(row)
            version['is_current'] = True
            if version.get('metadata') and isinstance(version['metadata'], str):
                version['metadata'] = json.loads(version['metadata'])
            if version.get('created_at'):
                version['created_at'] = str(version['created_at'])
            
            log.info(f"Switched to version '{version_id}' (v{version['version_number']}) for session '{session_id}'")
            return version
        except Exception as e:
            log.error(f"Error switching to version '{version_id}': {e}")
            return None

    async def update_version_label(
        self,
        version_id: str,
        label: str
    ) -> bool:
        """
        Updates the label for a specific version.

        Args:
            version_id: The version ID
            label: The new label

        Returns:
            True if successful, False otherwise
        """
        query = f"UPDATE {self.table_name} SET label = $1 WHERE version_id = $2"
        
        try:
            async with self.pool.acquire() as conn:
                result = await conn.execute(query, label, version_id)
            return "UPDATE 1" in result
        except Exception as e:
            log.error(f"Error updating label for version '{version_id}': {e}")
            return False

    async def delete_version(
        self,
        version_id: str,
        session_id: str
    ) -> bool:
        """
        Deletes a specific version. Cannot delete the current version.

        Args:
            version_id: The version ID to delete
            session_id: The session ID for verification

        Returns:
            True if successful, False otherwise
        """
        # First check if it's the current version
        check_query = f"SELECT is_current FROM {self.table_name} WHERE version_id = $1 AND session_id = $2"
        delete_query = f"DELETE FROM {self.table_name} WHERE version_id = $1 AND session_id = $2 AND is_current = FALSE"
        
        try:
            async with self.pool.acquire() as conn:
                row = await conn.fetchrow(check_query, version_id, session_id)
                if not row:
                    log.warning(f"Version '{version_id}' not found for session '{session_id}'")
                    return False
                if row['is_current']:
                    log.warning(f"Cannot delete current version '{version_id}'")
                    return False
                
                result = await conn.execute(delete_query, version_id, session_id)
            
            log.info(f"Version '{version_id}' deleted for session '{session_id}'")
            return "DELETE 1" in result
        except Exception as e:
            log.error(f"Error deleting version '{version_id}': {e}")
            return False

    async def delete_all_versions_for_session(
        self,
        session_id: str
    ) -> bool:
        """
        Deletes all versions for a session (used when resetting conversation).

        Args:
            session_id: The session ID

        Returns:
            True if successful, False otherwise
        """
        query = f"DELETE FROM {self.table_name} WHERE session_id = $1"
        
        try:
            async with self.pool.acquire() as conn:
                await conn.execute(query, session_id)
            log.info(f"All code versions deleted for session '{session_id}'")
            return True
        except Exception as e:
            log.error(f"Error deleting all versions for session '{session_id}': {e}")
            return False

    async def get_version_count(
        self,
        session_id: str
    ) -> int:
        """
        Gets the total number of versions for a session.

        Args:
            session_id: The session ID

        Returns:
            Number of versions
        """
        query = f"SELECT COUNT(*) FROM {self.table_name} WHERE session_id = $1"
        
        try:
            async with self.pool.acquire() as conn:
                count = await conn.fetchval(query, session_id)
            return count or 0
        except Exception as e:
            log.error(f"Error getting version count for session '{session_id}': {e}")
            return 0


# --- Tool Generation Conversation History Repository ---

class ToolGenerationConversationHistoryRepository(BaseRepository):
    """
    Repository for managing conversation history in tool generation sessions.
    Stores user queries and assistant responses with associated code snippets.
    """

    def __init__(self, pool: asyncpg.Pool, login_pool: asyncpg.Pool, table_name: str = TableNames.TOOL_GENERATION_CONVERSATION_HISTORY.value):
        """
        Initializes the ToolGenerationConversationHistoryRepository.

        Args:
            pool (asyncpg.Pool): The asyncpg connection pool.
            login_pool (asyncpg.Pool): The asyncpg connection pool for login-related operations.
            table_name (str): The name of the conversation history table.
        """
        super().__init__(pool, login_pool, table_name)


    async def create_table_if_not_exists(self):
        """
        Creates the 'tool_generation_conversation_history' table in PostgreSQL if it does not exist.
        """
        try:
            create_statement = f"""
            CREATE TABLE IF NOT EXISTS {self.table_name} (
                message_id TEXT PRIMARY KEY,
                session_id TEXT NOT NULL,
                pipeline_id TEXT NOT NULL,
                role TEXT NOT NULL CHECK (role IN ('user', 'assistant')),
                message TEXT NOT NULL,
                code_snippet TEXT,
                created_by TEXT,
                created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
                metadata JSONB DEFAULT '{{}}'::jsonb
            );
            CREATE INDEX IF NOT EXISTS idx_conv_history_session_id ON {self.table_name}(session_id);
            CREATE INDEX IF NOT EXISTS idx_conv_history_pipeline_id ON {self.table_name}(pipeline_id);
            CREATE INDEX IF NOT EXISTS idx_conv_history_session_pipeline ON {self.table_name}(session_id, pipeline_id);
            CREATE INDEX IF NOT EXISTS idx_conv_history_created_at ON {self.table_name}(created_at);
            """
            async with self.pool.acquire() as conn:
                await conn.execute(create_statement)
            log.info(f"Table '{self.table_name}' created successfully or already exists.")
        except Exception as e:
            log.error(f"Error creating table '{self.table_name}': {e}")

    async def save_message(
        self,
        session_id: str,
        pipeline_id: str,
        role: str,
        message: str,
        code_snippet: Optional[str] = None,
        created_by: Optional[str] = None,
        metadata: Optional[dict] = None
    ) -> Optional[Dict[str, Any]]:
        """
        Saves a conversation message.

        Args:
            session_id: The user's session ID
            pipeline_id: The pipeline ID
            role: 'user' or 'assistant'
            message: The message content
            code_snippet: Optional code snippet associated with this message
            created_by: Email of the user (for user messages)
            metadata: Optional additional metadata

        Returns:
            Dict with message details if successful, None otherwise.
        """
        message_id = str(uuid.uuid4())
        
        query = f"""
            INSERT INTO {self.table_name} 
            (message_id, session_id, pipeline_id, role, message, code_snippet, created_by, metadata)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
            RETURNING message_id, session_id, pipeline_id, role, message, code_snippet, created_by, created_at, metadata
        """
        
        try:
            async with self.pool.acquire() as conn:
                row = await conn.fetchrow(
                    query,
                    message_id,
                    session_id,
                    pipeline_id,
                    role,
                    message,
                    code_snippet,
                    created_by,
                    json.dumps(metadata) if metadata else "{}"
                )
            
            if row:
                result = dict(row)
                if result.get("metadata") and isinstance(result["metadata"], str):
                    result["metadata"] = json.loads(result["metadata"])
                if result.get("created_at"):
                    result["created_at"] = result["created_at"].isoformat()
                log.info(f"Conversation message saved: {message_id} (role: {role}) for session '{session_id}'")
                return result
            return None
        except Exception as e:
            log.error(f"Error saving conversation message for session '{session_id}': {e}")
            return None

    async def get_conversation_history(
        self,
        session_id: str,
        pipeline_id: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
        include_code: bool = True
    ) -> List[Dict[str, Any]]:
        """
        Gets conversation history for a session.

        Args:
            session_id: The user's session ID
            pipeline_id: Optional filter by pipeline ID
            limit: Maximum number of messages to return
            offset: Number of messages to skip (for pagination)
            include_code: Whether to include code snippets in response

        Returns:
            List of conversation messages ordered by timestamp (oldest first)
        """
        if include_code:
            select_fields = "message_id, session_id, pipeline_id, role, message, code_snippet, created_by, created_at, metadata"
        else:
            select_fields = "message_id, session_id, pipeline_id, role, message, created_by, created_at, metadata"
        
        if pipeline_id:
            query = f"""
                SELECT {select_fields}
                FROM {self.table_name}
                WHERE session_id = $1 AND pipeline_id = $2
                ORDER BY created_at ASC
                LIMIT $3 OFFSET $4
            """
            params = [session_id, pipeline_id, limit, offset]
        else:
            query = f"""
                SELECT {select_fields}
                FROM {self.table_name}
                WHERE session_id = $1
                ORDER BY created_at ASC
                LIMIT $2 OFFSET $3
            """
            params = [session_id, limit, offset]
        
        try:
            async with self.pool.acquire() as conn:
                rows = await conn.fetch(query, *params)
            
            result = []
            for row in rows:
                entry = dict(row)
                if entry.get("metadata") and isinstance(entry["metadata"], str):
                    entry["metadata"] = json.loads(entry["metadata"])
                if entry.get("created_at"):
                    entry["timestamp"] = entry["created_at"].isoformat()
                    del entry["created_at"]
                result.append(entry)
            
            return result
        except Exception as e:
            log.error(f"Error getting conversation history for session '{session_id}': {e}")
            return []

    async def get_latest_messages(
        self,
        session_id: str,
        pipeline_id: str,
        count: int = 10
    ) -> List[Dict[str, Any]]:
        """
        Gets the latest N messages for a session/pipeline.

        Args:
            session_id: The user's session ID
            pipeline_id: The pipeline ID
            count: Number of latest messages to return

        Returns:
            List of messages (most recent last)
        """
        query = f"""
            SELECT message_id, session_id, pipeline_id, role, message, code_snippet, created_by, created_at, metadata
            FROM {self.table_name}
            WHERE session_id = $1 AND pipeline_id = $2
            ORDER BY created_at DESC
            LIMIT $3
        """
        
        try:
            async with self.pool.acquire() as conn:
                rows = await conn.fetch(query, session_id, pipeline_id, count)
            
            result = []
            for row in rows:
                entry = dict(row)
                if entry.get("metadata") and isinstance(entry["metadata"], str):
                    entry["metadata"] = json.loads(entry["metadata"])
                if entry.get("created_at"):
                    entry["timestamp"] = entry["created_at"].isoformat()
                    del entry["created_at"]
                result.append(entry)
            
            # Reverse to get chronological order (oldest first)
            return list(reversed(result))
        except Exception as e:
            log.error(f"Error getting latest messages for session '{session_id}': {e}")
            return []

    async def clear_conversation_history(
        self,
        session_id: str,
        pipeline_id: Optional[str] = None
    ) -> bool:
        """
        Clears conversation history for a session.

        Args:
            session_id: The session ID
            pipeline_id: Optional pipeline ID - if provided, only clears for that pipeline

        Returns:
            True if successful, False otherwise
        """
        if pipeline_id:
            query = f"DELETE FROM {self.table_name} WHERE session_id = $1 AND pipeline_id = $2"
            params = [session_id, pipeline_id]
        else:
            query = f"DELETE FROM {self.table_name} WHERE session_id = $1"
            params = [session_id]
        
        try:
            async with self.pool.acquire() as conn:
                await conn.execute(query, *params)
            log.info(f"Conversation history cleared for session '{session_id}'" + (f" pipeline '{pipeline_id}'" if pipeline_id else ""))
            return True
        except Exception as e:
            log.error(f"Error clearing conversation history for session '{session_id}': {e}")
            return False

    async def get_message_count(
        self,
        session_id: str,
        pipeline_id: Optional[str] = None
    ) -> int:
        """
        Gets the total number of messages for a session.

        Args:
            session_id: The session ID
            pipeline_id: Optional pipeline ID filter

        Returns:
            Number of messages
        """
        if pipeline_id:
            query = f"SELECT COUNT(*) FROM {self.table_name} WHERE session_id = $1 AND pipeline_id = $2"
            params = [session_id, pipeline_id]
        else:
            query = f"SELECT COUNT(*) FROM {self.table_name} WHERE session_id = $1"
            params = [session_id]
        
        try:
            async with self.pool.acquire() as conn:
                count = await conn.fetchval(query, *params)
            return count or 0
        except Exception as e:
            log.error(f"Error getting message count for session '{session_id}': {e}")
            return 0

    async def get_latest_code_snippet(
        self,
        session_id: str,
        pipeline_id: Optional[str] = None
    ) -> Optional[Dict[str, Any]]:
        """
        Gets the latest code snippet from conversation history.

        Args:
            session_id: The user's session ID
            pipeline_id: Optional filter by pipeline ID

        Returns:
            Dict with code_snippet, message_id, and timestamp, or None if not found
        """
        if pipeline_id:
            query = f"""
                SELECT message_id, code_snippet, created_at
                FROM {self.table_name}
                WHERE session_id = $1 AND pipeline_id = $2 
                    AND code_snippet IS NOT NULL AND code_snippet != ''
                ORDER BY created_at DESC
                LIMIT 1
            """
            params = [session_id, pipeline_id]
        else:
            query = f"""
                SELECT message_id, code_snippet, created_at
                FROM {self.table_name}
                WHERE session_id = $1 
                    AND code_snippet IS NOT NULL AND code_snippet != ''
                ORDER BY created_at DESC
                LIMIT 1
            """
            params = [session_id]
        
        try:
            async with self.pool.acquire() as conn:
                row = await conn.fetchrow(query, *params)
            
            if row:
                return {
                    "message_id": row["message_id"],
                    "code_snippet": row["code_snippet"],
                    "timestamp": row["created_at"].isoformat() if row["created_at"] else None
                }
            return None
        except Exception as e:
            log.error(f"Error getting latest code snippet for session '{session_id}': {e}")
            return None

    async def clear_from_message(
        self,
        session_id: str,
        message_id: str
    ) -> int:
        """
        Clears all messages after a specific message (for restore functionality).
        Keeps the specified message and all messages before it.

        Args:
            session_id: The session ID
            message_id: The message ID to restore to (messages after this will be deleted)

        Returns:
            Number of deleted messages, or -1 on error
        """
        # First, get the sequence_number of the target message
        get_seq_query = f"""
            SELECT sequence_number FROM {self.table_name}
            WHERE session_id = $1 AND message_id = $2
        """
        
        try:
            async with self.pool.acquire() as conn:
                seq_num = await conn.fetchval(get_seq_query, session_id, message_id)
                
                if seq_num is None:
                    log.warning(f"Message '{message_id}' not found in session '{session_id}'")
                    return -1
                
                # Delete all messages with sequence_number greater than the target
                delete_query = f"""
                    DELETE FROM {self.table_name}
                    WHERE session_id = $1 AND sequence_number > $2
                """
                result = await conn.execute(delete_query, session_id, seq_num)
                
                # Extract count from "DELETE n"
                deleted_count = int(result.split()[-1]) if result else 0
                log.info(f"Restored conversation to message '{message_id}', deleted {deleted_count} messages")
                return deleted_count
                
        except Exception as e:
            log.error(f"Error clearing messages from message '{message_id}' in session '{session_id}': {e}")
            return -1




# --- Tool Generation Code Versions Repository ---

class ToolGenerationCodeVersionRepository(BaseRepository):
    """
    Repository for managing code version history in tool generation sessions.
    Allows users to save checkpoints and switch between different code versions.
    """

    def __init__(self, pool: asyncpg.Pool, login_pool: asyncpg.Pool, table_name: str = TableNames.TOOL_GENERATION_CODE_VERSIONS.value):
        """
        Initializes the ToolGenerationCodeVersionRepository.

        Args:
            pool (asyncpg.Pool): The asyncpg connection pool.
            login_pool (asyncpg.Pool): The asyncpg connection pool for login-related operations.
            table_name (str): The name of the code versions table.
        """
        super().__init__(pool, login_pool, table_name)


    async def create_table_if_not_exists(self):
        """
        Creates the 'tool_generation_code_versions' table in PostgreSQL if it does not exist.
        """
        try:
            create_statement = f"""
            CREATE TABLE IF NOT EXISTS {self.table_name} (
                version_id TEXT PRIMARY KEY,
                session_id TEXT NOT NULL,
                pipeline_id TEXT NOT NULL,
                version_number INTEGER NOT NULL,
                code_snippet TEXT NOT NULL,
                label TEXT,
                is_auto_saved BOOLEAN DEFAULT TRUE,
                is_current BOOLEAN DEFAULT FALSE,
                created_by TEXT NOT NULL,
                created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
                metadata JSONB DEFAULT '{{}}'::jsonb
            );
            CREATE INDEX IF NOT EXISTS idx_code_versions_session_id ON {self.table_name}(session_id);
            CREATE INDEX IF NOT EXISTS idx_code_versions_pipeline_id ON {self.table_name}(pipeline_id);
            CREATE INDEX IF NOT EXISTS idx_code_versions_session_version ON {self.table_name}(session_id, version_number);
            CREATE INDEX IF NOT EXISTS idx_code_versions_is_current ON {self.table_name}(session_id, is_current);
            """
            async with self.pool.acquire() as conn:
                await conn.execute(create_statement)
            log.info(f"Table '{self.table_name}' created successfully or already exists.")
        except Exception as e:
            log.error(f"Error creating table '{self.table_name}': {e}")

    async def save_code_version(
        self,
        session_id: str,
        pipeline_id: str,
        code_snippet: str,
        created_by: str,
        label: Optional[str] = None,
        is_auto_saved: bool = True,
        metadata: Optional[dict] = None
    ) -> Optional[Dict[str, Any]]:
        """
        Saves a new code version for a session.
        
        **Duplicate Check:** Before saving, compares with the latest version's code.
        If the code is identical (after stripping whitespace), skips saving and returns
        the existing version instead.

        Args:
            session_id: The user's session ID
            pipeline_id: The pipeline ID
            code_snippet: The code to save
            created_by: Email of the creator
            label: Optional label for the version (e.g., "Initial version", "Added error handling")
            is_auto_saved: Whether this was auto-saved or manually saved
            metadata: Optional metadata (e.g., user_query that generated this code)

        Returns:
            Dict with version details if successful, None otherwise.
            Returns existing version if code is duplicate.
        """
        # First, check if this exact code already exists in ANY version (not just latest)
        # This prevents duplicate versions when user asks for same code again
        existing_code_query = f"""
        SELECT version_id, version_number, code_snippet, created_at 
        FROM {self.table_name} 
        WHERE session_id = $1 AND TRIM(code_snippet) = TRIM($2)
        ORDER BY version_number DESC 
        LIMIT 1
        """
        
        try:
            async with self.pool.acquire() as conn:
                existing_row = await conn.fetchrow(existing_code_query, session_id, code_snippet)
                
                # If this exact code already exists in any version, return that version
                if existing_row:
                    log.info(f"Code already exists as version {existing_row['version_number']}, returning existing version for session '{session_id}'")
                    
                    # Also make this the current version since user is working with it
                    await conn.execute(
                        f"UPDATE {self.table_name} SET is_current = FALSE WHERE session_id = $1",
                        session_id
                    )
                    await conn.execute(
                        f"UPDATE {self.table_name} SET is_current = TRUE WHERE version_id = $1",
                        existing_row["version_id"]
                    )
                    
                    return {
                        "version_id": existing_row["version_id"],
                        "version_number": existing_row["version_number"],
                        "created_at": str(existing_row["created_at"]),
                        "is_current": True,
                        "is_duplicate": True
                    }
        except Exception as e:
            log.warning(f"Error checking for duplicate code: {e}, proceeding with save")
        
        version_id = f"ver_{uuid.uuid4().hex[:16]}"
        
        # Get next version number for this session
        version_number_query = f"SELECT COALESCE(MAX(version_number), 0) + 1 FROM {self.table_name} WHERE session_id = $1"
        
        # First, unset current flag on all versions for this session
        unset_current_query = f"UPDATE {self.table_name} SET is_current = FALSE WHERE session_id = $1"
        
        insert_statement = f"""
        INSERT INTO {self.table_name} 
        (version_id, session_id, pipeline_id, version_number, code_snippet, label, is_auto_saved, is_current, created_by, metadata)
        VALUES ($1, $2, $3, $4, $5, $6, $7, TRUE, $8, $9)
        RETURNING version_id, version_number, created_at
        """
        
        try:
            async with self.pool.acquire() as conn:
                async with conn.transaction():
                    # Get next version number
                    version_number = await conn.fetchval(version_number_query, session_id)
                    
                    # Unset current flag on existing versions
                    await conn.execute(unset_current_query, session_id)
                    
                    # Insert new version
                    row = await conn.fetchrow(
                        insert_statement,
                        version_id,
                        session_id,
                        pipeline_id,
                        version_number,
                        code_snippet,
                        label,
                        is_auto_saved,
                        created_by,
                        json.dumps(metadata or {})
                    )
            
            if row:
                log.info(f"Code version {version_number} saved for session '{session_id}'")
                return {
                    "version_id": row["version_id"],
                    "version_number": row["version_number"],
                    "created_at": str(row["created_at"]),
                    "is_current": True
                }
            return None
        except Exception as e:
            log.error(f"Error saving code version for session '{session_id}': {e}")
            return None

    async def get_all_versions(
        self,
        session_id: str,
        include_code: bool = False
    ) -> List[Dict[str, Any]]:
        """
        Retrieves all code versions for a session.

        Args:
            session_id: The user's session ID
            include_code: Whether to include the full code snippet in response

        Returns:
            List of version dictionaries ordered by version_number descending
        """
        columns = "version_id, session_id, pipeline_id, version_number, label, is_auto_saved, is_current, created_by, created_at, metadata"
        if include_code:
            columns += ", code_snippet"
        
        query = f"""
        SELECT {columns}
        FROM {self.table_name}
        WHERE session_id = $1
        ORDER BY version_number DESC
        """
        
        try:
            async with self.pool.acquire() as conn:
                rows = await conn.fetch(query, session_id)
            
            versions = []
            for row in rows:
                version = dict(row)
                if version.get('metadata') and isinstance(version['metadata'], str):
                    version['metadata'] = json.loads(version['metadata'])
                if version.get('created_at'):
                    version['created_at'] = str(version['created_at'])
                versions.append(version)
            
            return versions
        except Exception as e:
            log.error(f"Error retrieving code versions for session '{session_id}': {e}")
            return []

    async def get_version(
        self,
        version_id: str
    ) -> Optional[Dict[str, Any]]:
        """
        Retrieves a specific code version by ID.

        Args:
            version_id: The version ID

        Returns:
            Version dictionary if found, None otherwise
        """
        query = f"SELECT * FROM {self.table_name} WHERE version_id = $1"
        
        try:
            async with self.pool.acquire() as conn:
                row = await conn.fetchrow(query, version_id)
            
            if row:
                version = dict(row)
                if version.get('metadata') and isinstance(version['metadata'], str):
                    version['metadata'] = json.loads(version['metadata'])
                if version.get('created_at'):
                    version['created_at'] = str(version['created_at'])
                return version
            return None
        except Exception as e:
            log.error(f"Error retrieving code version '{version_id}': {e}")
            return None

    async def get_version_by_number(
        self,
        session_id: str,
        version_number: int
    ) -> Optional[Dict[str, Any]]:
        """
        Retrieves a specific code version by session_id and version_number.

        Args:
            session_id: The user's session ID
            version_number: The version number (1, 2, 3, etc.)

        Returns:
            Version dictionary if found, None otherwise
        """
        query = f"SELECT * FROM {self.table_name} WHERE session_id = $1 AND version_number = $2"
        
        try:
            async with self.pool.acquire() as conn:
                row = await conn.fetchrow(query, session_id, version_number)
            
            if row:
                version = dict(row)
                if version.get('metadata') and isinstance(version['metadata'], str):
                    version['metadata'] = json.loads(version['metadata'])
                if version.get('created_at'):
                    version['created_at'] = str(version['created_at'])
                return version
            return None
        except Exception as e:
            log.error(f"Error retrieving code version {version_number} for session '{session_id}': {e}")
            return None

    async def get_current_version(
        self,
        session_id: str
    ) -> Optional[Dict[str, Any]]:
        """
        Retrieves the current (active) code version for a session.

        Args:
            session_id: The user's session ID

        Returns:
            Current version dictionary if found, None otherwise
        """
        query = f"SELECT * FROM {self.table_name} WHERE session_id = $1 AND is_current = TRUE"
        
        try:
            async with self.pool.acquire() as conn:
                row = await conn.fetchrow(query, session_id)
            
            if row:
                version = dict(row)
                if version.get('metadata') and isinstance(version['metadata'], str):
                    version['metadata'] = json.loads(version['metadata'])
                if version.get('created_at'):
                    version['created_at'] = str(version['created_at'])
                return version
            return None
        except Exception as e:
            log.error(f"Error retrieving current code version for session '{session_id}': {e}")
            return None

    async def switch_to_version(
        self,
        session_id: str,
        version_id: str
    ) -> Optional[Dict[str, Any]]:
        """
        Switches to a specific code version, making it the current version.

        Args:
            session_id: The user's session ID
            version_id: The version ID to switch to

        Returns:
            The switched-to version dictionary if successful, None otherwise
        """
        # First verify the version belongs to this session
        verify_query = f"SELECT * FROM {self.table_name} WHERE version_id = $1 AND session_id = $2"
        unset_current_query = f"UPDATE {self.table_name} SET is_current = FALSE WHERE session_id = $1"
        set_current_query = f"UPDATE {self.table_name} SET is_current = TRUE WHERE version_id = $1"
        
        try:
            async with self.pool.acquire() as conn:
                async with conn.transaction():
                    # Verify version exists and belongs to session
                    row = await conn.fetchrow(verify_query, version_id, session_id)
                    if not row:
                        log.warning(f"Version '{version_id}' not found for session '{session_id}'")
                        return None
                    
                    # Unset current flag on all versions
                    await conn.execute(unset_current_query, session_id)
                    
                    # Set current flag on target version
                    await conn.execute(set_current_query, version_id)
            
            # Return the updated version
            version = dict(row)
            version['is_current'] = True
            if version.get('metadata') and isinstance(version['metadata'], str):
                version['metadata'] = json.loads(version['metadata'])
            if version.get('created_at'):
                version['created_at'] = str(version['created_at'])
            
            log.info(f"Switched to version '{version_id}' (v{version['version_number']}) for session '{session_id}'")
            return version
        except Exception as e:
            log.error(f"Error switching to version '{version_id}': {e}")
            return None

    async def update_version_label(
        self,
        version_id: str,
        label: str
    ) -> bool:
        """
        Updates the label for a specific version.

        Args:
            version_id: The version ID
            label: The new label

        Returns:
            True if successful, False otherwise
        """
        query = f"UPDATE {self.table_name} SET label = $1 WHERE version_id = $2"
        
        try:
            async with self.pool.acquire() as conn:
                result = await conn.execute(query, label, version_id)
            return "UPDATE 1" in result
        except Exception as e:
            log.error(f"Error updating label for version '{version_id}': {e}")
            return False

    async def delete_version(
        self,
        version_id: str,
        session_id: str
    ) -> bool:
        """
        Deletes a specific version. Cannot delete the current version.

        Args:
            version_id: The version ID to delete
            session_id: The session ID for verification

        Returns:
            True if successful, False otherwise
        """
        # First check if it's the current version
        check_query = f"SELECT is_current FROM {self.table_name} WHERE version_id = $1 AND session_id = $2"
        delete_query = f"DELETE FROM {self.table_name} WHERE version_id = $1 AND session_id = $2 AND is_current = FALSE"
        
        try:
            async with self.pool.acquire() as conn:
                row = await conn.fetchrow(check_query, version_id, session_id)
                if not row:
                    log.warning(f"Version '{version_id}' not found for session '{session_id}'")
                    return False
                if row['is_current']:
                    log.warning(f"Cannot delete current version '{version_id}'")
                    return False
                
                result = await conn.execute(delete_query, version_id, session_id)
            
            log.info(f"Version '{version_id}' deleted for session '{session_id}'")
            return "DELETE 1" in result
        except Exception as e:
            log.error(f"Error deleting version '{version_id}': {e}")
            return False

    async def delete_all_versions_for_session(
        self,
        session_id: str
    ) -> bool:
        """
        Deletes all versions for a session (used when resetting conversation).

        Args:
            session_id: The session ID

        Returns:
            True if successful, False otherwise
        """
        query = f"DELETE FROM {self.table_name} WHERE session_id = $1"
        
        try:
            async with self.pool.acquire() as conn:
                await conn.execute(query, session_id)
            log.info(f"All code versions deleted for session '{session_id}'")
            return True
        except Exception as e:
            log.error(f"Error deleting all versions for session '{session_id}': {e}")
            return False

    async def get_version_count(
        self,
        session_id: str
    ) -> int:
        """
        Gets the total number of versions for a session.

        Args:
            session_id: The session ID

        Returns:
            Number of versions
        """
        query = f"SELECT COUNT(*) FROM {self.table_name} WHERE session_id = $1"
        
        try:
            async with self.pool.acquire() as conn:
                count = await conn.fetchval(query, session_id)
            return count or 0
        except Exception as e:
            log.error(f"Error getting version count for session '{session_id}': {e}")
            return 0


# --- Tool Generation Conversation History Repository ---

class ToolGenerationConversationHistoryRepository(BaseRepository):
    """
    Repository for managing conversation history in tool generation sessions.
    Stores user queries and assistant responses with associated code snippets.
    """

    def __init__(self, pool: asyncpg.Pool, login_pool: asyncpg.Pool, table_name: str = TableNames.TOOL_GENERATION_CONVERSATION_HISTORY.value):
        """
        Initializes the ToolGenerationConversationHistoryRepository.

        Args:
            pool (asyncpg.Pool): The asyncpg connection pool.
            login_pool (asyncpg.Pool): The asyncpg connection pool for login-related operations.
            table_name (str): The name of the conversation history table.
        """
        super().__init__(pool, login_pool, table_name)


    async def create_table_if_not_exists(self):
        """
        Creates the 'tool_generation_conversation_history' table in PostgreSQL if it does not exist.
        """
        try:
            create_statement = f"""
            CREATE TABLE IF NOT EXISTS {self.table_name} (
                message_id TEXT PRIMARY KEY,
                session_id TEXT NOT NULL,
                pipeline_id TEXT NOT NULL,
                role TEXT NOT NULL CHECK (role IN ('user', 'assistant')),
                message TEXT NOT NULL,
                code_snippet TEXT,
                created_by TEXT,
                created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
                metadata JSONB DEFAULT '{{}}'::jsonb
            );
            CREATE INDEX IF NOT EXISTS idx_conv_history_session_id ON {self.table_name}(session_id);
            CREATE INDEX IF NOT EXISTS idx_conv_history_pipeline_id ON {self.table_name}(pipeline_id);
            CREATE INDEX IF NOT EXISTS idx_conv_history_session_pipeline ON {self.table_name}(session_id, pipeline_id);
            CREATE INDEX IF NOT EXISTS idx_conv_history_created_at ON {self.table_name}(created_at);
            """
            async with self.pool.acquire() as conn:
                await conn.execute(create_statement)
            log.info(f"Table '{self.table_name}' created successfully or already exists.")
        except Exception as e:
            log.error(f"Error creating table '{self.table_name}': {e}")

    async def save_message(
        self,
        session_id: str,
        pipeline_id: str,
        role: str,
        message: str,
        code_snippet: Optional[str] = None,
        created_by: Optional[str] = None,
        metadata: Optional[dict] = None
    ) -> Optional[Dict[str, Any]]:
        """
        Saves a conversation message.

        Args:
            session_id: The user's session ID
            pipeline_id: The pipeline ID
            role: 'user' or 'assistant'
            message: The message content
            code_snippet: Optional code snippet associated with this message
            created_by: Email of the user (for user messages)
            metadata: Optional additional metadata

        Returns:
            Dict with message details if successful, None otherwise.
        """
        message_id = str(uuid.uuid4())
        
        query = f"""
            INSERT INTO {self.table_name} 
            (message_id, session_id, pipeline_id, role, message, code_snippet, created_by, metadata)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
            RETURNING message_id, session_id, pipeline_id, role, message, code_snippet, created_by, created_at, metadata
        """
        
        try:
            async with self.pool.acquire() as conn:
                row = await conn.fetchrow(
                    query,
                    message_id,
                    session_id,
                    pipeline_id,
                    role,
                    message,
                    code_snippet,
                    created_by,
                    json.dumps(metadata) if metadata else "{}"
                )
            
            if row:
                result = dict(row)
                if result.get("metadata") and isinstance(result["metadata"], str):
                    result["metadata"] = json.loads(result["metadata"])
                if result.get("created_at"):
                    result["created_at"] = result["created_at"].isoformat()
                log.info(f"Conversation message saved: {message_id} (role: {role}) for session '{session_id}'")
                return result
            return None
        except Exception as e:
            log.error(f"Error saving conversation message for session '{session_id}': {e}")
            return None

    async def get_conversation_history(
        self,
        session_id: str,
        pipeline_id: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
        include_code: bool = True
    ) -> List[Dict[str, Any]]:
        """
        Gets conversation history for a session.

        Args:
            session_id: The user's session ID
            pipeline_id: Optional filter by pipeline ID
            limit: Maximum number of messages to return
            offset: Number of messages to skip (for pagination)
            include_code: Whether to include code snippets in response

        Returns:
            List of conversation messages ordered by timestamp (oldest first)
        """
        if include_code:
            select_fields = "message_id, session_id, pipeline_id, role, message, code_snippet, created_by, created_at, metadata"
        else:
            select_fields = "message_id, session_id, pipeline_id, role, message, created_by, created_at, metadata"
        
        if pipeline_id:
            query = f"""
                SELECT {select_fields}
                FROM {self.table_name}
                WHERE session_id = $1 AND pipeline_id = $2
                ORDER BY created_at ASC
                LIMIT $3 OFFSET $4
            """
            params = [session_id, pipeline_id, limit, offset]
        else:
            query = f"""
                SELECT {select_fields}
                FROM {self.table_name}
                WHERE session_id = $1
                ORDER BY created_at ASC
                LIMIT $2 OFFSET $3
            """
            params = [session_id, limit, offset]
        
        try:
            async with self.pool.acquire() as conn:
                rows = await conn.fetch(query, *params)
            
            result = []
            for row in rows:
                entry = dict(row)
                if entry.get("metadata") and isinstance(entry["metadata"], str):
                    entry["metadata"] = json.loads(entry["metadata"])
                if entry.get("created_at"):
                    entry["timestamp"] = entry["created_at"].isoformat()
                    del entry["created_at"]
                result.append(entry)
            
            return result
        except Exception as e:
            log.error(f"Error getting conversation history for session '{session_id}': {e}")
            return []

    async def get_latest_messages(
        self,
        session_id: str,
        pipeline_id: str,
        count: int = 10
    ) -> List[Dict[str, Any]]:
        """
        Gets the latest N messages for a session/pipeline.

        Args:
            session_id: The user's session ID
            pipeline_id: The pipeline ID
            count: Number of latest messages to return

        Returns:
            List of messages (most recent last)
        """
        query = f"""
            SELECT message_id, session_id, pipeline_id, role, message, code_snippet, created_by, created_at, metadata
            FROM {self.table_name}
            WHERE session_id = $1 AND pipeline_id = $2
            ORDER BY created_at DESC
            LIMIT $3
        """
        
        try:
            async with self.pool.acquire() as conn:
                rows = await conn.fetch(query, session_id, pipeline_id, count)
            
            result = []
            for row in rows:
                entry = dict(row)
                if entry.get("metadata") and isinstance(entry["metadata"], str):
                    entry["metadata"] = json.loads(entry["metadata"])
                if entry.get("created_at"):
                    entry["timestamp"] = entry["created_at"].isoformat()
                    del entry["created_at"]
                result.append(entry)
            
            # Reverse to get chronological order (oldest first)
            return list(reversed(result))
        except Exception as e:
            log.error(f"Error getting latest messages for session '{session_id}': {e}")
            return []

    async def clear_conversation_history(
        self,
        session_id: str,
        pipeline_id: Optional[str] = None
    ) -> bool:
        """
        Clears conversation history for a session.

        Args:
            session_id: The session ID
            pipeline_id: Optional pipeline ID - if provided, only clears for that pipeline

        Returns:
            True if successful, False otherwise
        """
        if pipeline_id:
            query = f"DELETE FROM {self.table_name} WHERE session_id = $1 AND pipeline_id = $2"
            params = [session_id, pipeline_id]
        else:
            query = f"DELETE FROM {self.table_name} WHERE session_id = $1"
            params = [session_id]
        
        try:
            async with self.pool.acquire() as conn:
                await conn.execute(query, *params)
            log.info(f"Conversation history cleared for session '{session_id}'" + (f" pipeline '{pipeline_id}'" if pipeline_id else ""))
            return True
        except Exception as e:
            log.error(f"Error clearing conversation history for session '{session_id}': {e}")
            return False

    async def get_message_count(
        self,
        session_id: str,
        pipeline_id: Optional[str] = None
    ) -> int:
        """
        Gets the total number of messages for a session.

        Args:
            session_id: The session ID
            pipeline_id: Optional pipeline ID filter

        Returns:
            Number of messages
        """
        if pipeline_id:
            query = f"SELECT COUNT(*) FROM {self.table_name} WHERE session_id = $1 AND pipeline_id = $2"
            params = [session_id, pipeline_id]
        else:
            query = f"SELECT COUNT(*) FROM {self.table_name} WHERE session_id = $1"
            params = [session_id]
        
        try:
            async with self.pool.acquire() as conn:
                count = await conn.fetchval(query, *params)
            return count or 0
        except Exception as e:
            log.error(f"Error getting message count for session '{session_id}': {e}")
            return 0

    async def get_latest_code_snippet(
        self,
        session_id: str,
        pipeline_id: Optional[str] = None
    ) -> Optional[Dict[str, Any]]:
        """
        Gets the latest code snippet from conversation history.

        Args:
            session_id: The user's session ID
            pipeline_id: Optional filter by pipeline ID

        Returns:
            Dict with code_snippet, message_id, and timestamp, or None if not found
        """
        if pipeline_id:
            query = f"""
                SELECT message_id, code_snippet, created_at
                FROM {self.table_name}
                WHERE session_id = $1 AND pipeline_id = $2 
                    AND code_snippet IS NOT NULL AND code_snippet != ''
                ORDER BY created_at DESC
                LIMIT 1
            """
            params = [session_id, pipeline_id]
        else:
            query = f"""
                SELECT message_id, code_snippet, created_at
                FROM {self.table_name}
                WHERE session_id = $1 
                    AND code_snippet IS NOT NULL AND code_snippet != ''
                ORDER BY created_at DESC
                LIMIT 1
            """
            params = [session_id]
        
        try:
            async with self.pool.acquire() as conn:
                row = await conn.fetchrow(query, *params)
            
            if row:
                return {
                    "message_id": row["message_id"],
                    "code_snippet": row["code_snippet"],
                    "timestamp": row["created_at"].isoformat() if row["created_at"] else None
                }
            return None
        except Exception as e:
            log.error(f"Error getting latest code snippet for session '{session_id}': {e}")
            return None

    async def clear_from_message(
        self,
        session_id: str,
        message_id: str
    ) -> int:
        """
        Clears all messages after a specific message (for restore functionality).
        Keeps the specified message and all messages before it.

        Args:
            session_id: The session ID
            message_id: The message ID to restore to (messages after this will be deleted)

        Returns:
            Number of deleted messages, or -1 on error
        """
        # First, get the sequence_number of the target message
        get_seq_query = f"""
            SELECT sequence_number FROM {self.table_name}
            WHERE session_id = $1 AND message_id = $2
        """
        
        try:
            async with self.pool.acquire() as conn:
                seq_num = await conn.fetchval(get_seq_query, session_id, message_id)
                
                if seq_num is None:
                    log.warning(f"Message '{message_id}' not found in session '{session_id}'")
                    return -1
                
                # Delete all messages with sequence_number greater than the target
                delete_query = f"""
                    DELETE FROM {self.table_name}
                    WHERE session_id = $1 AND sequence_number > $2
                """
                result = await conn.execute(delete_query, session_id, seq_num)
                
                # Extract count from "DELETE n"
                deleted_count = int(result.split()[-1]) if result else 0
                log.info(f"Restored conversation to message '{message_id}', deleted {deleted_count} messages")
                return deleted_count
                
        except Exception as e:
            log.error(f"Error clearing messages from message '{message_id}' in session '{session_id}': {e}")
            return -1




# --- User Agent Access Repository ---
class UserAgentAccessRepository(BaseRepository):
    """
    Repository for the 'user_agent_access' table. Handles direct database interactions for user agent access management.
    """

    def __init__(self, pool: asyncpg.Pool, login_pool: asyncpg.Pool, table_name: str = "user_agent_access"):
        """
        Initializes the UserAgentAccessRepository.

        Args:
            pool (asyncpg.Pool): The asyncpg connection pool.
            login_pool (asyncpg.Pool): The asyncpg connection pool for login-related operations.
            table_name (str): The name of the user agent access table.
        """
        super().__init__(pool, login_pool, table_name)

    async def create_table_if_not_exists(self):
        """
        Creates the 'user_agent_access' table if it does not exist.
        """
        try:
            create_statement = f"""
            CREATE TABLE IF NOT EXISTS {self.table_name} (
                user_email TEXT PRIMARY KEY,
                agent_ids TEXT[] NOT NULL,
                given_access_by TEXT NOT NULL
            );
            """
            async with self.pool.acquire() as conn:
                await conn.execute(create_statement)
                
                # Add department_name column if it doesn't exist (for existing tables)
                try:
                    await conn.execute(f"""
                        ALTER TABLE {self.table_name} 
                        ADD COLUMN IF NOT EXISTS department_name TEXT DEFAULT 'General'
                    """)
                except Exception as alter_error:
                    log.warning(f"Could not add department_name column to {self.table_name}: {alter_error}")
                
            log.info(f"Table '{self.table_name}' created successfully or already exists.")
        except Exception as e:
            log.error(f"Error creating table '{self.table_name}': {e}")

    async def grant_agent_access(self, user_email: str, agent_id: str, given_access_by: str) -> tuple[bool, str]:
        """
        Grants access to an agent for a user. If user already has access record, adds the agent_id to the list.
        
        Args:
            user_email (str): The email of the user to grant access to.
            agent_id (str): The ID of the agent to grant access to.
            given_access_by (str): The admin who is granting the access.
            
        Returns:
            tuple[bool, str]: (success_status, message)
        """
        try:
            async with self.pool.acquire() as conn:
                # Check if user already has an access record
                existing_record = await conn.fetchrow(
                    f"SELECT agent_ids FROM {self.table_name} WHERE user_email = $1",
                    user_email
                )
                
                if existing_record:
                    # User has existing record, add agent_id if not already present
                    current_agent_ids = list(existing_record['agent_ids'])
                    if agent_id not in current_agent_ids:
                        current_agent_ids.append(agent_id)
                        await conn.execute(
                            f"UPDATE {self.table_name} SET agent_ids = $1, given_access_by = $2 WHERE user_email = $3",
                            current_agent_ids, given_access_by, user_email
                        )
                        log.info(f"Added agent '{agent_id}' to existing access for user '{user_email}'.")
                        return True, f"Successfully added agent '{agent_id}' to existing access for user '{user_email}'."
                    else:
                        log.info(f"User '{user_email}' already has access to agent '{agent_id}'.")
                        return True, f"User '{user_email}' already has access to agent '{agent_id}'."
                else:
                    # Create new access record
                    await conn.execute(
                        f"INSERT INTO {self.table_name} (user_email, agent_ids, given_access_by) VALUES ($1, $2, $3)",
                        user_email, [agent_id], given_access_by
                    )
                    log.info(f"Created new access record for user '{user_email}' with agent '{agent_id}'.")
                    
                return True, f"Successfully granted access to agent '{agent_id}' for user '{user_email}'."
                
        except Exception as e:
            log.error(f"Error granting agent access for user '{user_email}': {e}")
            return False, f"Error granting agent access: {str(e)}"

    async def revoke_agent_access(self, user_email: str, agent_id: str) -> bool:
        """
        Revokes access to an agent for a user.
        
        Args:
            user_email (str): The email of the user to revoke access from.
            agent_id (str): The ID of the agent to revoke access to.
            
        Returns:
            bool: True if access was revoked successfully, False otherwise.
        """
        try:
            async with self.pool.acquire() as conn:
                existing_record = await conn.fetchrow(
                    f"SELECT agent_ids FROM {self.table_name} WHERE user_email = $1",
                    user_email
                )
                
                if existing_record:
                    current_agent_ids = list(existing_record['agent_ids'])
                    if agent_id in current_agent_ids:
                        current_agent_ids.remove(agent_id)
                        
                        if current_agent_ids:
                            # Update with remaining agent IDs
                            await conn.execute(
                                f"UPDATE {self.table_name} SET agent_ids = $1 WHERE user_email = $2",
                                current_agent_ids, user_email
                            )
                            log.info(f"Removed agent '{agent_id}' from access for user '{user_email}'.")
                        else:
                            # Remove entire record if no agents left
                            await conn.execute(
                                f"DELETE FROM {self.table_name} WHERE user_email = $1",
                                user_email
                            )
                            log.info(f"Removed entire access record for user '{user_email}' as no agents remain.")
                        
                        return True
                    else:
                        log.warning(f"User '{user_email}' does not have access to agent '{agent_id}'.")
                        return False
                else:
                    log.warning(f"No access record found for user '{user_email}'.")
                    return False
                    
        except Exception as e:
            log.error(f"Error revoking agent access for user '{user_email}': {e}")
            return False

    async def get_user_agent_access(self, user_email: str) -> Dict[str, Any]:
        """
        Retrieves agent access information for a specific user.
        
        Args:
            user_email (str): The email of the user.
            
        Returns:
            Dict[str, Any]: Dictionary containing user's agent access information, or empty dict if not found.
        """
        try:
            async with self.pool.acquire() as conn:
                row = await conn.fetchrow(
                    f"SELECT * FROM {self.table_name} WHERE user_email = $1",
                    user_email
                )
                
                if row:
                    log.info(f"Retrieved agent access for user '{user_email}'.")
                    return dict(row)
                else:
                    log.info(f"No agent access found for user '{user_email}'.")
                    return {}
                    
        except Exception as e:
            log.error(f"Error retrieving agent access for user '{user_email}': {e}")
            return {}

    async def get_all_user_agent_access(self) -> List[Dict[str, Any]]:
        """
        Retrieves all user agent access records.
        
        Returns:
            List[Dict[str, Any]]: List of all user agent access records.
        """
        try:
            async with self.pool.acquire() as conn:
                rows = await conn.fetch(f"SELECT * FROM {self.table_name}")
                
            log.info(f"Retrieved {len(rows)} user agent access records.")
            return [dict(row) for row in rows]
            
        except Exception as e:
            log.error(f"Error retrieving all user agent access records: {e}")
            return []

    async def check_user_agent_access(self, user_email: str, agent_id: str) -> bool:
        """
        Checks if a user has access to a specific agent.
        
        Args:
            user_email (str): The email of the user.
            agent_id (str): The ID of the agent.
            
        Returns:
            bool: True if user has access, False otherwise.
        """
        try:
            async with self.pool.acquire() as conn:
                row = await conn.fetchrow(
                    f"SELECT agent_ids FROM {self.table_name} WHERE user_email = $1",
                    user_email
                )
                
                if row and agent_id in row['agent_ids']:
                    return True
                return False
                
        except Exception as e:
            log.error(f"Error checking agent access for user '{user_email}': {e}")
            return False

    async def get_users_with_agent_access(self, agent_id: str) -> List[str]:
        """
        Retrieves all users who have access to a specific agent.
        
        Args:
            agent_id (str): The ID of the agent.
            
        Returns:
            List[str]: List of user emails who have access to the agent.
        """
        try:
            async with self.pool.acquire() as conn:
                rows = await conn.fetch(
                    f"SELECT user_email FROM {self.table_name} WHERE $1 = ANY(agent_ids)",
                    agent_id
                )
                
            user_emails = [row['user_email'] for row in rows]
            log.info(f"Found {len(user_emails)} users with access to agent '{agent_id}'.")
            return user_emails
            
        except Exception as e:
            log.error(f"Error retrieving users with access to agent '{agent_id}': {e}")
            return []

    async def get_all_tool_ids_for_user(self, user_email: str) -> Dict[str, Any]:
        """
        Retrieves all tool IDs bound to agents that the user has access to.
        
        Args:
            user_email (str): The email of the user.
            
        Returns:
            Dict[str, Any]: Dictionary containing accessible agent IDs and tool IDs.
        """
        try:
            async with self.pool.acquire() as conn:
                # First check if user has any agent access
                user_access_row = await conn.fetchrow(
                    f"SELECT agent_ids FROM {self.table_name} WHERE user_email = $1",
                    user_email
                )
                
                if not user_access_row:
                    log.warning(f"User '{user_email}' has no agent access records.")
                    return {
                        "accessible_agent_ids": [],
                        "tool_ids": []
                    }
                
                user_accessible_agents = list(user_access_row['agent_ids'])
                
                if not user_accessible_agents:
                    log.warning(f"User '{user_email}' has no accessible agents.")
                    return {
                        "accessible_agent_ids": [],
                        "tool_ids": []
                    }
                
                # Get all tool IDs for the user's accessible agents
                query = """
                    SELECT DISTINCT tam.tool_id
                    FROM tool_agent_mapping_table tam
                    WHERE tam.agentic_application_id = ANY($1::text[])
                    AND tam.tool_id IS NOT NULL
                """
                
                rows = await conn.fetch(query, user_accessible_agents)
                
            tool_ids = [row['tool_id'] for row in rows]
            log.info(f"Retrieved {len(tool_ids)} tool IDs for user '{user_email}' across {len(user_accessible_agents)} agents.")
            
            return {
                "accessible_agent_ids": user_accessible_agents,
                "tool_ids": tool_ids
            }
            
        except Exception as e:
            log.error(f"Error retrieving all tool IDs for user '{user_email}': {e}")
            return {
                "accessible_agent_ids": [],
                "tool_ids": []
            }

    async def get_tools_bound_with_agents_for_users(self, user_email: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        Retrieves a comprehensive list of tools bound with agents for different users.
        
        Args:
            user_email (Optional[str]): If provided, filters results for a specific user.
                                      If None, returns data for all users.
            
        Returns:
            List[Dict[str, Any]]: List of dictionaries containing:
                - user_email: Email of the user who has access
                - agent_id: ID of the agent
                - agent_name: Name of the agent
                - agent_description: Description of the agent
                - agent_created_by: Who created the agent
                - tool_id: ID of the tool bound to the agent
                - tool_name: Name of the tool
                - tool_description: Description of the tool
                - tool_created_by: Who created the tool
                - given_access_by: Who granted access to the user
        """
        try:
            async with self.pool.acquire() as conn:
                # Build the base query with JOINs across all relevant tables
                query = f"""
                    SELECT DISTINCT
                        uaa.user_email,
                        uaa.given_access_by,
                        a.agentic_application_id as agent_id,
                        a.agentic_application_name as agent_name,
                        a.agentic_application_description as agent_description,
                        a.created_by as agent_created_by,
                        tam.tool_id,
                        t.tool_name,
                        t.tool_description,
                        t.created_by as tool_created_by
                    FROM {self.table_name} uaa
                    INNER JOIN UNNEST(uaa.agent_ids) AS agent_id_unnest ON true
                    INNER JOIN agent_table a ON a.agentic_application_id = agent_id_unnest
                    LEFT JOIN tool_agent_mapping_table tam ON tam.agentic_application_id = a.agentic_application_id
                    LEFT JOIN tool_table t ON t.tool_id = tam.tool_id
                """
                
                params = []
                if user_email:
                    query += " WHERE uaa.user_email = $1"
                    params.append(user_email)
                
                query += " ORDER BY uaa.user_email, a.agentic_application_name, t.tool_name"
                
                rows = await conn.fetch(query, *params)
                
            result = []
            for row in rows:
                result.append({
                    "user_email": row['user_email'],
                    "given_access_by": row['given_access_by'],
                    "agent_id": row['agent_id'],
                    "agent_name": row['agent_name'],
                    "agent_description": row['agent_description'],
                    "agent_created_by": row['agent_created_by'],
                    "tool_id": row['tool_id'],
                    "tool_name": row['tool_name'],
                    "tool_description": row['tool_description'],
                    "tool_created_by": row['tool_created_by']
                })
                
            if user_email:
                log.info(f"Retrieved {len(result)} tool-agent bindings for user '{user_email}'.")
            else:
                log.info(f"Retrieved {len(result)} tool-agent bindings for all users.")
                
            return result
            
        except Exception as e:
            log.error(f"Error retrieving tools bound with agents for users: {e}")
            return []

    async def get_agents_and_tools_summary_for_users(self, user_email: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        Retrieves a summary of agents and their associated tools for different users.
        Groups tools by agent for easier consumption.
        
        Args:
            user_email (Optional[str]): If provided, filters results for a specific user.
                                      If None, returns data for all users.
            
        Returns:
            List[Dict[str, Any]]: List of dictionaries containing:
                - user_email: Email of the user who has access
                - given_access_by: Who granted access to the user
                - agent_id: ID of the agent
                - agent_name: Name of the agent
                - agent_description: Description of the agent
                - agent_created_by: Who created the agent
                - tools: List of tools bound to this agent, each containing:
                    - tool_id: ID of the tool
                    - tool_name: Name of the tool
                    - tool_description: Description of the tool
                    - tool_created_by: Who created the tool
        """
        try:
            # Get the detailed list first
            detailed_list = await self.get_tools_bound_with_agents_for_users(user_email)
            
            # Group by user and agent
            summary = {}
            for item in detailed_list:
                key = (item['user_email'], item['agent_id'])
                
                if key not in summary:
                    summary[key] = {
                        "user_email": item['user_email'],
                        "given_access_by": item['given_access_by'],
                        "agent_id": item['agent_id'],
                        "agent_name": item['agent_name'],
                        "agent_description": item['agent_description'],
                        "agent_created_by": item['agent_created_by'],
                        "tools": []
                    }
                
                # Add tool if it exists (some agents might not have tools)
                if item['tool_id']:
                    tool_info = {
                        "tool_id": item['tool_id'],
                        "tool_name": item['tool_name'],
                        "tool_description": item['tool_description'],
                        "tool_created_by": item['tool_created_by']
                    }
                    # Avoid duplicates
                    if tool_info not in summary[key]['tools']:
                        summary[key]['tools'].append(tool_info)
            
            result = list(summary.values())
            
            if user_email:
                log.info(f"Retrieved agent-tools summary for user '{user_email}': {len(result)} agents.")
            else:
                log.info(f"Retrieved agent-tools summary for all users: {len(result)} user-agent combinations.")
            
            return result
            
        except Exception as e:
            log.error(f"Error retrieving agents and tools summary for users: {e}")
            return []

    # Pagination methods for search functionality
    async def get_total_user_agent_access_count(self, search_value: str = '', created_by: Optional[str] = None) -> int:
        """
        Returns the total count of user agent access records matching the search criteria.
        
        Args:
            search_value (str, optional): User email or given_access_by to filter by.
            created_by (str, optional): The email ID of the user who granted access.
            
        Returns:
            int: Total count of matching user agent access records.
        """
        try:
            async with self.pool.acquire() as conn:
                conditions = []
                params = []
                param_count = 0
                
                if search_value:
                    param_count += 1
                    conditions.append(f"user_email ILIKE ${param_count}")
                    params.append(f"%{search_value}%")
                
                if created_by:
                    param_count += 1
                    conditions.append(f"given_access_by = ${param_count}")
                    params.append(created_by)
                
                where_clause = " WHERE " + " AND ".join(conditions) if conditions else ""
                
                query = f"SELECT COUNT(*) FROM {self.table_name}{where_clause}"
                count = await conn.fetchval(query, *params)
                return count or 0
                
        except Exception as e:
            log.error(f"Error getting total user agent access count: {e}")
            return 0

    async def get_user_agent_access_by_search_or_page_records(self, search_value: str = '', limit: int = 20, 
                                                           page: int = 1, created_by: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        Retrieves user agent access records with pagination and search filtering.
        
        Args:
            search_value (str, optional): User email or given_access_by to filter by.
            limit (int, optional): Number of results per page.
            page (int, optional): Page number for pagination.
            created_by (str, optional): The email ID of the user who granted access.
            
        Returns:
            List[Dict[str, Any]]: List of user agent access records.
        """
        try:
            async with self.pool.acquire() as conn:
                conditions = []
                params = []
                param_count = 0
                
                if search_value:
                    param_count += 1
                    conditions.append(f"user_email ILIKE ${param_count}")
                    params.append(f"%{search_value}%")
                
                if created_by:
                    param_count += 1
                    conditions.append(f"given_access_by = ${param_count}")
                    params.append(created_by)
                
                where_clause = " WHERE " + " AND ".join(conditions) if conditions else ""
                
                # Calculate offset
                offset = (page - 1) * limit
                param_count += 1
                limit_clause = f" LIMIT ${param_count}"
                params.append(limit)
                
                param_count += 1
                offset_clause = f" OFFSET ${param_count}"
                params.append(offset)
                
                query = f"""
                SELECT user_email, agent_ids, given_access_by
                FROM {self.table_name}
                {where_clause}
                ORDER BY user_email ASC
                {limit_clause}{offset_clause}
                """
                
                rows = await conn.fetch(query, *params)
                return [dict(row) for row in rows]
                
        except Exception as e:
            log.error(f"Error retrieving user agent access records by search or page: {e}")
            return []


# --- Group Management Repository ---
class GroupRepository(BaseRepository):
    """
    Repository for the 'groups' table. Handles direct database interactions for group management.
    Groups are organizational units that contain lists of users and agents, managed by super-admins.
    Groups are scoped within departments for multi-tenant access control.
    
    Schema Design:
    - user_emails: ALL group members (includes admins, developers, and regular users)
    - agent_ids: List of agent IDs belonging to this group
    - department_name: Department context for multi-tenant isolation
    - Role management is handled at the application level, not in the database schema
    """

    def __init__(self, pool: asyncpg.Pool, login_pool: asyncpg.Pool, table_name: str = "groups"):
        """
        Initializes the GroupRepository.

        Args:
            pool (asyncpg.Pool): The asyncpg connection pool.
            login_pool (asyncpg.Pool): The asyncpg connection pool for login-related operations.
            table_name (str): The name of the groups table.
        """
        super().__init__(pool, login_pool, table_name)

    async def create_table_if_not_exists(self):
        """
        Creates the 'groups' table if it does not exist.
        """
        try:
            # Create groups table with department context
            create_groups_statement = f"""
            CREATE TABLE IF NOT EXISTS {self.table_name} (
                group_name TEXT NOT NULL,
                department_name TEXT NOT NULL DEFAULT 'General',
                group_description TEXT,
                user_emails TEXT[] NOT NULL DEFAULT '{{}}',
                agent_ids TEXT[] NOT NULL DEFAULT '{{}}',
                created_by TEXT NOT NULL,
                created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (group_name, department_name)
            );
            """
            
            async with self.pool.acquire() as conn:
                await conn.execute(create_groups_statement)
                
                # Add default value to department_name column if it doesn't have one (for existing tables)
                try:
                    await conn.execute(f"""
                        ALTER TABLE {self.table_name} 
                        ADD COLUMN IF NOT EXISTS department_name TEXT DEFAULT 'General'
                    """)
                except Exception as alter_error:
                    log.warning(f"Could not set default for department_name in {self.table_name}: {alter_error}")
                
            log.info(f"Table '{self.table_name}' created successfully or already exists.")
        except Exception as e:
            log.error(f"Error creating table '{self.table_name}': {e}")

    async def group_exists(self, group_name: str, department_name: str = None) -> bool:
        """
        Checks if a group with the given name already exists in the specified department.
        
        Args:
            group_name (str): The group name to check.
            department_name (str): The department context for the group.
            
        Returns:
            bool: True if group exists, False otherwise.
        """
        try:
            async with self.pool.acquire() as conn:
                result = await conn.fetchval(
                    f"SELECT COUNT(*) FROM {self.table_name} WHERE group_name = $1 AND department_name = $2",
                    group_name, department_name
                )
                return result > 0
        except Exception as e:
            log.error(f"Error checking if group '{group_name}' exists in department '{department_name}': {e}")
            return False

    async def create_group(self, group_name: str, group_description: str, 
                          user_emails: List[str], agent_ids: List[str], created_by: str,
                          department_name: str = None) -> bool:
        """
        Creates a new group within a department.
        
        Args:
            group_name (str): The name of the group (unique within department).
            group_description (str): The description of the group.
            user_emails (List[str]): List of user emails in the group.
            agent_ids (List[str]): List of agent IDs in the group.
            created_by (str): The super-admin who created the group.
            department_name (str): The department context for the group.
            
        Returns:
            bool: True if group was created successfully, False otherwise.
        """
        try:
            async with self.pool.acquire() as conn:
                await conn.execute(
                    f"""INSERT INTO {self.table_name} 
                       (group_name, group_description, user_emails, agent_ids, created_by, department_name) 
                       VALUES ($1, $2, $3, $4, $5, $6)""",
                    group_name, group_description, user_emails, agent_ids, created_by, department_name
                )
            log.info(f"Created group '{group_name}' in department '{department_name}'.")
            return True
        except asyncpg.UniqueViolationError:
            log.warning(f"Group '{group_name}' already exists in department '{department_name}' (unique violation).")
            return False
        except Exception as e:
            log.error(f"Error creating group '{group_name}' in department '{department_name}': {e}")
            return False

    async def get_group(self, group_name: str, department_name: str = None) -> Dict[str, Any]:
        """
        Retrieves a group by its name and optional department.

        Args:
            group_name (str): The group name.
            department_name (str): The department context (optional).

        Returns:
            Dict[str, Any]: Group information or empty dict if not found.
        """
        try:
            query = f"SELECT * FROM {self.table_name} WHERE group_name = $1"
            params: List[Any] = [group_name]

            # Only include department_name condition when a non-empty value is provided
            if department_name is not None and department_name != "":
                query += " AND department_name = $2"
                params.append(department_name)

            async with self.pool.acquire() as conn:
                row = await conn.fetchrow(query, *params)

            if row:
                return dict(row)
            else:
                log.info(f"Group '{group_name}' not found" + (f" in department '{department_name}'." if department_name else "."))
                return {}

        except Exception as e:
            log.error(f"Error retrieving group '{group_name}'" + (f" in department '{department_name}': {e}" if department_name else f": {e}"))
            return {}

    async def get_all_groups(self, department_name: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        Retrieves all groups, optionally filtered by department_name.

        Args:
            department_name (str): The department context to filter groups. If None or empty, returns all groups.

        Returns:
            List[Dict[str, Any]]: List of groups.
        """
        try:
            query = f"SELECT * FROM {self.table_name}"
            params: List[Any] = []

            # Use department_name condition only when a non-empty value is provided
            if department_name is not None and department_name != "":
                query += " WHERE department_name = $1"
                params.append(department_name)

            query += " ORDER BY created_at DESC"

            async with self.pool.acquire() as conn:
                rows = await conn.fetch(query, *params)

            log.info(f"Retrieved {len(rows)} groups for department '{department_name}'.")
            return [dict(row) for row in rows]

        except Exception as e:
            log.error(f"Error retrieving all groups for department '{department_name}': {e}")
            return []

    async def update_group(self, group_name: str, department_name: str = None, new_group_name: Optional[str] = None, 
                           group_description: Optional[str] = None, user_emails: Optional[List[str]] = None,
                           agent_ids: Optional[List[str]] = None) -> bool:
        """
        Updates a group's information.
        
        Args:
            group_name (str): The current group name to update.
            department_name (str): The department context.
            new_group_name (Optional[str]): New group name.
            group_description (Optional[str]): New group description.
            user_emails (Optional[List[str]]): New list of user emails.
            agent_ids (Optional[List[str]]): New list of agent IDs.
            
        Returns:
            bool: True if group was updated successfully, False otherwise.
        """
        try:
            update_fields = []
            params = []
            param_count = 1
            
            if new_group_name is not None:
                update_fields.append(f"group_name = ${param_count}")
                params.append(new_group_name)
                param_count += 1
                
            if group_description is not None:
                update_fields.append(f"group_description = ${param_count}")
                params.append(group_description)
                param_count += 1
                
            if user_emails is not None:
                update_fields.append(f"user_emails = ${param_count}")
                params.append(user_emails)
                param_count += 1
                
            if agent_ids is not None:
                update_fields.append(f"agent_ids = ${param_count}")
                params.append(agent_ids)
                param_count += 1
            
            if not update_fields:
                log.warning(f"No fields to update for group '{group_name}' in department '{department_name}'.")
                return False
            
            update_fields.append(f"updated_at = CURRENT_TIMESTAMP")
            params.append(group_name)
            params.append(department_name)
            
            query = f"UPDATE {self.table_name} SET {', '.join(update_fields)} WHERE group_name = ${param_count} AND department_name = ${param_count + 1}"
            
            async with self.pool.acquire() as conn:
                result = await conn.execute(query, *params)
                
            if result == "UPDATE 1":
                log.info(f"Updated group '{group_name}' in department '{department_name}'.")
                return True
            else:
                log.warning(f"Group '{group_name}' not found for update in department '{department_name}'.")
                return False
                
        except Exception as e:
            log.error(f"Error updating group '{group_name}' in department '{department_name}': {e}")
            return False

    async def delete_group(self, group_name: str, department_name: str = None) -> bool:
        """
        Deletes a group.
        
        Args:
            group_name (str): The group name to delete.
            department_name (str): The department context.
            
        Returns:
            bool: True if group was deleted successfully, False otherwise.
        """
        try:
            async with self.pool.acquire() as conn:
                result = await conn.execute(
                    f"DELETE FROM {self.table_name} WHERE group_name = $1 AND department_name = $2",
                    group_name, department_name
                )
                
            if result == "DELETE 1":
                log.info(f"Deleted group '{group_name}' from department '{department_name}'.")
                return True
            else:
                log.warning(f"Group '{group_name}' not found for deletion in department '{department_name}'.")
                return False
                
        except Exception as e:
            log.error(f"Error deleting group '{group_name}' from department '{department_name}': {e}")
            return False

    async def add_users_to_group(self, group_name: str, user_emails: List[str], department_name: str = None) -> Dict[str, Any]:
        """
        Adds users to a group.
        
        Args:
            group_name (str): The group name.
            user_emails (List[str]): List of user emails to add.
            department_name (str): The department context for the group.
            
        Returns:
            Dict[str, Any]: Result with details about which users were added.
        """
        try:
            async with self.pool.acquire() as conn:
                # Get current users
                current_row = await conn.fetchrow(
                    f"SELECT user_emails FROM {self.table_name} WHERE group_name = $1 AND department_name = $2",
                    group_name, department_name
                )
                
                if not current_row:
                    log.warning(f"Group '{group_name}' not found in department '{department_name}'.")
                    return {
                        "success": False,
                        "message": f"Group '{group_name}' not found in department '{department_name}'.",
                        "users_added": [],
                        "users_already_present": [],
                        "users_requested": user_emails
                    }
                
                current_users = list(current_row['user_emails']) if current_row['user_emails'] else []
                
                # Track which users are new vs already present
                users_added = []
                users_already_present = []
                
                for email in user_emails:
                    if email not in current_users:
                        current_users.append(email)
                        users_added.append(email)
                    else:
                        users_already_present.append(email)
                
                # Update group
                await conn.execute(
                    f"UPDATE {self.table_name} SET user_emails = $1, updated_at = CURRENT_TIMESTAMP WHERE group_name = $2 AND department_name = $3",
                    current_users, group_name, department_name
                )
                
                log.info(f"Added {len(users_added)} new users to group '{group_name}' in department '{department_name}'. {len(users_already_present)} were already present.")
                return {
                    "success": True,
                    "message": f"Processed {len(user_emails)} users for group '{group_name}' in department '{department_name}'.",
                    "users_added": users_added,
                    "users_already_present": users_already_present,
                    "users_requested": user_emails
                }
            
        except Exception as e:
            log.error(f"Error adding users to group '{group_name}' in department '{department_name}': {e}")
            return {
                "success": False,
                "message": f"Error adding users to group: {str(e)}",
                "users_added": [],
                "users_already_present": [],
                "users_requested": user_emails
            }

    async def remove_users_from_group(self, group_name: str, user_emails: List[str], department_name: str = None) -> bool:
        """
        Removes users from a group.
        
        Args:
            group_name (str): The group name.
            user_emails (List[str]): List of user emails to remove.
            department_name (str): The department context for the group.
            
        Returns:
            bool: True if users were removed successfully, False otherwise.
        """
        try:
            async with self.pool.acquire() as conn:
                # Get current users
                current_row = await conn.fetchrow(
                    f"SELECT user_emails FROM {self.table_name} WHERE group_name = $1 AND department_name = $2",
                    group_name, department_name
                )
                
                if not current_row:
                    log.warning(f"Group '{group_name}' not found in department '{department_name}'.")
                    return False
                
                current_users = list(current_row['user_emails']) if current_row['user_emails'] else []
                
                # Remove users
                for email in user_emails:
                    if email in current_users:
                        current_users.remove(email)
                
                # Update group
                await conn.execute(
                    f"UPDATE {self.table_name} SET user_emails = $1, updated_at = CURRENT_TIMESTAMP WHERE group_name = $2 AND department_name = $3",
                    current_users, group_name, department_name
                )
                
            log.info(f"Removed {len(user_emails)} users from group '{group_name}' in department '{department_name}'.")
            return True
            
        except Exception as e:
            log.error(f"Error removing users from group '{group_name}' in department '{department_name}': {e}")
            return False

    async def add_agents_to_group(self, group_name: str, agent_ids: List[str], department_name: str = None) -> Dict[str, Any]:
        """
        Adds agents to a group.
        
        Args:
            group_name (str): The group name.
            agent_ids (List[str]): List of agent IDs to add.
            department_name (str): The department context for the group.
            
        Returns:
            Dict[str, Any]: Result with details about which agents were added.
        """
        try:
            async with self.pool.acquire() as conn:
                # Get current agents
                current_row = await conn.fetchrow(
                    f"SELECT agent_ids FROM {self.table_name} WHERE group_name = $1 AND department_name = $2",
                    group_name, department_name
                )
                
                if not current_row:
                    log.warning(f"Group '{group_name}' not found in department '{department_name}'.")
                    return {
                        "success": False,
                        "message": f"Group '{group_name}' not found in department '{department_name}'.",
                        "agents_added": [],
                        "agents_already_present": [],
                        "agents_requested": agent_ids
                    }
                
                current_agents = list(current_row['agent_ids']) if current_row['agent_ids'] else []
                
                # Track which agents are new vs already present
                agents_added = []
                agents_already_present = []
                
                for agent_id in agent_ids:
                    if agent_id not in current_agents:
                        current_agents.append(agent_id)
                        agents_added.append(agent_id)
                    else:
                        agents_already_present.append(agent_id)
                
                # Update group
                await conn.execute(
                    f"UPDATE {self.table_name} SET agent_ids = $1, updated_at = CURRENT_TIMESTAMP WHERE group_name = $2 AND department_name = $3",
                    current_agents, group_name, department_name
                )
                
                log.info(f"Added {len(agents_added)} new agents to group '{group_name}' in department '{department_name}'. {len(agents_already_present)} were already present.")
                return {
                    "success": True,
                    "message": f"Processed {len(agent_ids)} agents for group '{group_name}' in department '{department_name}'.",
                    "agents_added": agents_added,
                    "agents_already_present": agents_already_present,
                    "agents_requested": agent_ids
                }
            
        except Exception as e:
            log.error(f"Error adding agents to group '{group_name}' in department '{department_name}': {e}")
            return {
                "success": False,
                "message": f"Error adding agents to group: {str(e)}",
                "agents_added": [],
                "agents_already_present": [],
                "agents_requested": agent_ids
            }

    async def remove_agents_from_group(self, group_name: str, agent_ids: List[str], department_name: str = None) -> bool:
        """
        Removes agents from a group.
        
        Args:
            group_name (str): The group name.
            agent_ids (List[str]): List of agent IDs to remove.
            department_name (str): The department context for the group.
            
        Returns:
            bool: True if agents were removed successfully, False otherwise.
        """
        try:
            async with self.pool.acquire() as conn:
                # Get current agents
                current_row = await conn.fetchrow(
                    f"SELECT agent_ids FROM {self.table_name} WHERE group_name = $1 AND department_name = $2",
                    group_name, department_name
                )
                
                if not current_row:
                    log.warning(f"Group '{group_name}' not found in department '{department_name}'.")
                    return False
                
                current_agents = list(current_row['agent_ids']) if current_row['agent_ids'] else []
                
                # Remove agents
                for agent_id in agent_ids:
                    if agent_id in current_agents:
                        current_agents.remove(agent_id)
                
                # Update group
                await conn.execute(
                    f"UPDATE {self.table_name} SET agent_ids = $1, updated_at = CURRENT_TIMESTAMP WHERE group_name = $2 AND department_name = $3",
                    current_agents, group_name, department_name
                )
                
            log.info(f"Removed {len(agent_ids)} agents from group '{group_name}' in department '{department_name}'.")
            return True
            
        except Exception as e:
            log.error(f"Error removing agents from group '{group_name}' in department '{department_name}': {e}")
            return False

    async def get_groups_by_user(self, user_email: str, department_name: str = None) -> List[Dict[str, Any]]:
        """
        Retrieves all groups that contain a specific user, optionally filtered by department.

        Args:
            user_email (str): The user email to search for.
            department_name (str, optional): Department to filter groups by.

        Returns:
            List[Dict[str, Any]]: List of groups containing the user.
        """
        try:
            query = f"SELECT * FROM {self.table_name} WHERE $1 = ANY(user_emails)"
            params = [user_email]

            if department_name:
                query += " AND department_name = $2"
                params.append(department_name)

            query += " ORDER BY created_at DESC"

            async with self.pool.acquire() as conn:
                rows = await conn.fetch(query, *params)

            groups = [dict(row) for row in rows]
            log.info(f"Found {len(groups)} groups containing user '{user_email}'" + (f" in department '{department_name}'." if department_name else "."))
            return groups

        except Exception as e:
            log.error(f"Error retrieving groups for user '{user_email}'" + (f" in department '{department_name}': {e}" if department_name else f": {e}"))
            return []

    async def get_groups_by_agent(self, agent_id: str, department_name: str = None) -> List[Dict[str, Any]]:
        """
        Retrieves all groups that contain a specific agent, optionally filtered by department.

        Args:
            agent_id (str): The agent ID to search for.
            department_name (str, optional): Department to filter groups by.

        Returns:
            List[Dict[str, Any]]: List of groups containing the agent.
        """
        try:
            async with self.pool.acquire() as conn:
                if department_name:
                    rows = await conn.fetch(
                        f"SELECT * FROM {self.table_name} WHERE $1 = ANY(agent_ids) AND department_name = $2 ORDER BY created_at DESC",
                        agent_id,
                        department_name,
                    )
                else:
                    rows = await conn.fetch(
                        f"SELECT * FROM {self.table_name} WHERE $1 = ANY(agent_ids) ORDER BY created_at DESC",
                        agent_id,
                    )

            groups = [dict(row) for row in rows]
            log.info(f"Found {len(groups)} groups containing agent '{agent_id}'" + (f" in department '{department_name}'." if department_name else "."))
            return groups

        except Exception as e:
            log.error(f"Error retrieving groups for agent '{agent_id}'" + (f" in department '{department_name}': {e}" if department_name else f": {e}"))
            return []

    async def check_user_group_access(self, user_email: str, group_name: str, department_name: str = None) -> bool:
        """
        Checks if a user has access to a group.
        
        Args:
            user_email (str): The user's email.
            group_name (str): The group name.
            department_name (str): The department context for the group.
            
        Returns:
            bool: True if user is a group member, False otherwise.
        """
        try:
            async with self.pool.acquire() as conn:
                row = await conn.fetchrow(
                    f"""
                    SELECT user_emails 
                    FROM {self.table_name} 
                    WHERE group_name = $1 AND department_name = $2
                    """,
                    group_name, department_name
                )
            
            if not row:
                return False
            
            # Check if user is a group member
            return bool(row['user_emails'] and user_email in row['user_emails'])
                
        except Exception as e:
            log.error(f"Error checking user group access for '{user_email}' in group '{group_name}' in department '{department_name}': {e}")
            return False

    async def get_total_group_count(self, search_value: str = '', created_by: Optional[str] = None, department_name: str = None) -> int:
        """
        Returns the total count of groups matching the search criteria.

        Args:
            search_value (str, optional): Group name to filter by.
            created_by (str, optional): The email ID of the user who created the group.
            department_name (str, optional): Department to filter groups by.

        Returns:
            int: Total count of matching groups.
        """
        try:
            async with self.pool.acquire() as conn:
                conditions = []
                params: List[Any] = []
                param_count = 0

                if search_value:
                    param_count += 1
                    conditions.append(f"group_name ILIKE ${param_count}")
                    params.append(f"%{search_value}%")

                if created_by:
                    param_count += 1
                    conditions.append(f"created_by = ${param_count}")
                    params.append(created_by)

                if department_name:
                    param_count += 1
                    conditions.append(f"department_name = ${param_count}")
                    params.append(department_name)

                where_clause = " WHERE " + " AND ".join(conditions) if conditions else ""

                query = f"SELECT COUNT(*) FROM {self.table_name}{where_clause}"
                count = await conn.fetchval(query, *params)
                return int(count) if count is not None else 0

        except Exception as e:
            log.error(f"Error getting total group count: {e}")
            return 0

    async def get_groups_by_search_or_page_records(self, search_value: str = '', limit: int = 20, 
                                                   page: int = 1, created_by: Optional[str] = None, department_name: str = None) -> List[Dict[str, Any]]:
        """
        Retrieves groups with pagination and search filtering.
        
        Args:
            search_value (str, optional): Group name to filter by.
            limit (int, optional): Number of results per page.
            page (int, optional): Page number for pagination.
            created_by (str, optional): The email ID of the user who created the group.
            department_name (str, optional): Department to filter groups by.
            
        Returns:
            List[Dict[str, Any]]: List of group records.
        """
        try:
            async with self.pool.acquire() as conn:
                conditions = []
                params = []
                param_count = 0
                
                if search_value:
                    param_count += 1
                    conditions.append(f"group_name ILIKE ${param_count}")
                    params.append(f"%{search_value}%")
                
                if created_by:
                    param_count += 1
                    conditions.append(f"created_by = ${param_count}")
                    params.append(created_by)

                if department_name:
                    param_count += 1
                    conditions.append(f"department_name = ${param_count}")
                    params.append(department_name)
                
                where_clause = " WHERE " + " AND ".join(conditions) if conditions else ""
                
                # Calculate offset
                offset = (page - 1) * limit
                param_count += 1
                limit_clause = f" LIMIT ${param_count}"
                params.append(limit)
                
                param_count += 1
                offset_clause = f" OFFSET ${param_count}"
                params.append(offset)
                
                query = f"""
                SELECT group_name, group_description, user_emails, agent_ids, 
                       created_by, created_at, updated_at, department_name
                FROM {self.table_name}
                {where_clause}
                ORDER BY created_at DESC
                {limit_clause}{offset_clause}
                """
                
                rows = await conn.fetch(query, *params)
                return [dict(row) for row in rows]
                
        except Exception as e:
            log.error(f"Error retrieving groups by search or page: {e}")
            return []


class GroupSecretsRepository(BaseRepository):
    """
    Repository for the 'group_secrets' table. Handles direct database interactions for group secrets management.
    Group secrets are encrypted key-value pairs that can be accessed by group members based on their roles.
    Groups are scoped within departments for multi-tenant access control.
    """

    def __init__(self, pool: asyncpg.Pool, login_pool: asyncpg.Pool, table_name: str = "group_secrets"):
        """
        Initializes the GroupSecretsRepository.

        Args:
            pool (asyncpg.Pool): The asyncpg connection pool.
            login_pool (asyncpg.Pool): The asyncpg connection pool for login-related operations.
            table_name (str): The name of the group_secrets table.
        """
        super().__init__(pool, login_pool, table_name)

    async def create_table_if_not_exists(self):
        """
        Creates the 'group_secrets' table if it does not exist.
        """
        try:
            create_statement = f"""
            CREATE TABLE IF NOT EXISTS {self.table_name} (
                id SERIAL PRIMARY KEY,
                group_name TEXT NOT NULL,
                department_name TEXT NOT NULL DEFAULT 'General',
                key_name TEXT NOT NULL,
                encrypted_value TEXT NOT NULL,
                created_by TEXT NOT NULL,
                created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
                CONSTRAINT fk_group_secrets_group 
                    FOREIGN KEY (group_name, department_name) REFERENCES groups(group_name, department_name) ON DELETE CASCADE,
                CONSTRAINT unique_group_key UNIQUE (group_name, department_name, key_name)
            );
            """
            
            create_index_statement = f"""
            CREATE INDEX IF NOT EXISTS idx_group_secrets_group_name 
            ON {self.table_name}(group_name, department_name);
            """
            
            async with self.pool.acquire() as conn:
                await conn.execute(create_statement)
                await conn.execute(create_index_statement)
                
                # Add default value to department_name column if it doesn't have one (for existing tables)
                try:
                    await conn.execute(f"""
                        ALTER TABLE {self.table_name} 
                        ADD COLUMN IF NOT EXISTS department_name TEXT DEFAULT 'General'
                    """)
                except Exception as alter_error:
                    log.warning(f"Could not set default for department_name in {self.table_name}: {alter_error}")
                
            log.info(f"Table '{self.table_name}' created successfully or already exists.")
        except Exception as e:
            log.error(f"Error creating table '{self.table_name}': {e}")

    async def create_group_secret(self, group_name: str, key_name: str, encrypted_value: str, created_by: str, department_name: str = None) -> bool:
        """
        Creates a new secret_record for a group.
        
        Args:
            group_name (str): The group name.
            key_name (str): The name of the secret_key.
            encrypted_value (str): The encrypted secret_value.
            created_by (str): The email of the user creating the secret_record.
            department_name (str): The department context for the group.
            
        Returns:
            bool: True if secret_record was created successfully, False otherwise.
        """
        try:
            async with self.pool.acquire() as conn:
                await conn.execute(
                    f"""
                    INSERT INTO {self.table_name} (group_name, department_name, key_name, encrypted_value, created_by, created_at, updated_at)
                    VALUES ($1, $2, $3, $4, $5, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                    """,
                    group_name, department_name, key_name, encrypted_value, created_by
                )
            log.info(f"Created group secret '{key_name}' for group '{group_name}' in department '{department_name}' by '{created_by}'.")
            return True
        except Exception as e:
            log.error(f"Error creating group secret '{key_name}' for group '{group_name}' in department '{department_name}': {e}")
            return False

    async def get_group_secret(self, group_name: str, key_name: str, department_name: str = None) -> Optional[Dict[str, Any]]:
        """
        Retrieves a specific group secret_record.
        
        Args:
            group_name (str): The group name.
            key_name (str): The name of the secret_key.
            department_name (str): The department context for the group.
            
        Returns:
            Optional[Dict[str, Any]]: The secret_record if found, None otherwise.
        """
        try:
            async with self.pool.acquire() as conn:
                row = await conn.fetchrow(
                    f"SELECT * FROM {self.table_name} WHERE group_name = $1 AND department_name = $2 AND key_name = $3",
                    group_name, department_name, key_name
                )
            
            if row:
                log.info(f"Retrieved group secret '{key_name}' for group '{group_name}' in department '{department_name}'.")
                return dict(row)
            else:
                log.warning(f"Group secret '{key_name}' not found for group '{group_name}' in department '{department_name}'.")
                return None
                
        except Exception as e:
            log.error(f"Error retrieving group secret '{key_name}' for group '{group_name}' in department '{department_name}': {e}")
            return None

    async def update_group_secret(self, group_name: str, key_name: str, encrypted_value: str, updated_by: str, department_name: str = None) -> bool:
        """
        Updates an existing group secret_record.
        
        Args:
            group_name (str): The group name.
            key_name (str): The name of the secret_key.
            encrypted_value (str): The new encrypted secret_value.
            updated_by (str): The email of the user updating the secret_record.
            department_name (str): The department context for the group.
            
        Returns:
            bool: True if secret_record was updated successfully, False otherwise.
        """
        try:
            async with self.pool.acquire() as conn:
                result = await conn.execute(
                    f"""
                    UPDATE {self.table_name} 
                    SET encrypted_value = $4, updated_at = CURRENT_TIMESTAMP 
                    WHERE group_name = $1 AND department_name = $2 AND key_name = $3
                    """,
                    group_name, department_name, key_name, encrypted_value
                )
            
            if result == "UPDATE 1":
                log.info(f"Updated group secret '{key_name}' for group '{group_name}' in department '{department_name}' by '{updated_by}'.")
                return True
            else:
                log.warning(f"Group secret '{key_name}' not found for group '{group_name}' in department '{department_name}' during update.")
                return False
                
        except Exception as e:
            log.error(f"Error updating group secret '{key_name}' for group '{group_name}' in department '{department_name}': {e}")
            return False

    async def delete_group_secret(self, group_name: str, key_name: str, department_name: str = None) -> bool:
        """
        Deletes a group secret_record.
        
        Args:
            group_name (str): The group name.
            key_name (str): The name of the secret_key.
            department_name (str): The department context for the group.
            
        Returns:
            bool: True if secret_record was deleted successfully, False otherwise.
        """
        try:
            async with self.pool.acquire() as conn:
                result = await conn.execute(
                    f"DELETE FROM {self.table_name} WHERE group_name = $1 AND department_name = $2 AND key_name = $3",
                    group_name, department_name, key_name
                )
            
            if result == "DELETE 1":
                log.info(f"Deleted group secret '{key_name}' for group '{group_name}' in department '{department_name}'.")
                return True
            else:
                log.warning(f"Group secret '{key_name}' not found for group '{group_name}' in department '{department_name}' during deletion.")
                return False
                
        except Exception as e:
            log.error(f"Error deleting group secret '{key_name}' for group '{group_name}' in department '{department_name}': {e}")
            return False

    async def list_group_secrets(self, group_name: str, department_name: str = None) -> List[Dict[str, Any]]:
        """
        Lists all secrets for a group (without encrypted values for security).
        
        Args:
            group_name (str): The group name.
            department_name (str): The department context for the group.
            
        Returns:
            List[Dict[str, Any]]: List of secret_records without encrypted values.
        """
        try:
            async with self.pool.acquire() as conn:
                rows = await conn.fetch(
                    f"""
                    SELECT id, group_name, department_name, key_name, created_by, created_at, updated_at 
                    FROM {self.table_name} 
                    WHERE group_name = $1 AND department_name = $2 
                    ORDER BY created_at DESC
                    """,
                    group_name, department_name
                )
            
            secrets = [dict(row) for row in rows]
            log.info(f"Retrieved {len(secrets)} group secrets for group '{group_name}' in department '{department_name}'.")
            return secrets
            
        except Exception as e:
            log.error(f"Error listing group secrets for group '{group_name}' in department '{department_name}': {e}")
            return []

    async def secret_exists(self, group_name: str, key_name: str, department_name: str = None) -> bool:
        """
        Checks if a group secret_record with the given name already exists.
        
        Args:
            group_name (str): The group name.
            key_name (str): The secret_key name to check.
            department_name (str): The department context for the group.
            
        Returns:
            bool: True if secret_record exists, False otherwise.
        """
        try:
            async with self.pool.acquire() as conn:
                result = await conn.fetchval(
                    f"SELECT COUNT(*) FROM {self.table_name} WHERE group_name = $1 AND department_name = $2 AND key_name = $3",
                    group_name, department_name, key_name
                )
                return result > 0
        except Exception as e:
            log.error(f"Error checking if group secret '{key_name}' exists in group '{group_name}' in department '{department_name}': {e}")
            return False

    async def group_secret_exists(self, group_name: str, key_name: str, department_name: str = None) -> bool:
        """
        Alias for secret_exists method to maintain compatibility with service layer.
        
        Args:
            group_name (str): The group name.
            key_name (str): The secret_key name to check.
            department_name (str): The department context for the group.
            
        Returns:
            bool: True if secret_record exists, False otherwise.
        """
        return await self.secret_exists(group_name, key_name, department_name)


class ToolAccessKeyMappingRepository(BaseRepository):
    """
    Repository for mapping tools to their required access keys.
    
    When a tool is onboarded with @resource_access decorators, this table
    stores which access_keys that tool requires. This enables:
    - Querying what access keys a tool needs
    - Finding all tools that use a specific access key
    - Admin visibility into tool access requirements
    
    Example:
        Tool "get_employee_salary" requires access_key "employees"
        Tool "update_project" requires access_keys ["employees", "projects"]
    """

    def __init__(self, pool: asyncpg.Pool, login_pool: asyncpg.Pool):
        super().__init__(pool, login_pool, "tool_access_key_mapping")

    async def create_table_if_not_exists(self):
        """Create tool_access_key_mapping table if it doesn't exist"""
        create_table_query = f"""
        CREATE TABLE IF NOT EXISTS {self.table_name} (
            tool_id VARCHAR(255) PRIMARY KEY,
            tool_name VARCHAR(255) NOT NULL,
            access_keys TEXT[] NOT NULL DEFAULT '{{}}',
            department_name VARCHAR(255) DEFAULT 'General'
        );
        
        CREATE INDEX IF NOT EXISTS idx_tool_access_key_mapping_tool_name 
        ON {self.table_name}(tool_name);
        
        CREATE INDEX IF NOT EXISTS idx_tool_access_key_mapping_department 
        ON {self.table_name}(department_name);
        """
        
        try:
            async with self.pool.acquire() as conn:
                await conn.execute(create_table_query)
            log.info(f"Table '{self.table_name}' created or already exists.")
        except Exception as e:
            log.error(f"Error creating table '{self.table_name}': {e}")
            raise

    async def save_tool_access_keys(
        self,
        tool_id: str,
        tool_name: str,
        access_keys: List[str],
        department_name: str = None
    ) -> bool:
        """
        Save or update access keys for a tool.
        
        Args:
            tool_id: The tool's unique ID
            tool_name: The tool's name
            access_keys: List of access keys the tool requires
            department_name: The department the tool belongs to
            
        Returns:
            bool: True if successful
        """
        if not access_keys:
            log.debug(f"No access keys to save for tool {tool_name}")
            return True
            
        query = f"""
        INSERT INTO {self.table_name} (tool_id, tool_name, access_keys, department_name)
        VALUES ($1, $2, $3, $4)
        ON CONFLICT (tool_id) 
        DO UPDATE SET 
            tool_name = $2,
            access_keys = $3,
            department_name = $4
        """
        try:
            async with self.pool.acquire() as conn:
                await conn.execute(query, tool_id, tool_name, access_keys, department_name)
            log.info(f"Saved access keys {access_keys} for tool '{tool_name}' (ID: {tool_id}) in department '{department_name}'")
            return True
        except Exception as e:
            log.error(f"Error saving access keys for tool {tool_name}: {e}")
            return False

    async def get_tool_access_keys(self, tool_id: str, department_name: str = None) -> Optional[Dict[str, Any]]:
        """
        Get access keys for a specific tool.
        
        Args:
            tool_id: The tool's unique ID
            department_name: Optional department filter
            
        Returns:
            Dict with tool_id, tool_name, access_keys, department_name or None if not found
        """
        if department_name:
            query = f"SELECT tool_id, tool_name, access_keys, department_name FROM {self.table_name} WHERE tool_id = $1 AND department_name = $2"
            params = (tool_id, department_name)
        else:
            query = f"SELECT tool_id, tool_name, access_keys, department_name FROM {self.table_name} WHERE tool_id = $1"
            params = (tool_id,)
        try:
            async with self.pool.acquire() as conn:
                row = await conn.fetchrow(query, *params)
                if row:
                    return {
                        "tool_id": row["tool_id"],
                        "tool_name": row["tool_name"],
                        "access_keys": list(row["access_keys"]) if row["access_keys"] else [],
                        "department_name": row["department_name"]
                    }
                return None
        except Exception as e:
            log.error(f"Error fetching access keys for tool {tool_id}: {e}")
            return None

    async def get_tool_access_keys_by_name(self, tool_name: str, department_name: str = None) -> Optional[Dict[str, Any]]:
        """
        Get access keys for a tool by its name.
        
        Args:
            tool_name: The tool's name
            department_name: Optional department filter
            
        Returns:
            Dict with tool_id, tool_name, access_keys, department_name or None if not found
        """
        if department_name:
            query = f"SELECT tool_id, tool_name, access_keys, department_name FROM {self.table_name} WHERE tool_name = $1 AND department_name = $2"
            params = (tool_name, department_name)
        else:
            query = f"SELECT tool_id, tool_name, access_keys, department_name FROM {self.table_name} WHERE tool_name = $1"
            params = (tool_name,)
        try:
            async with self.pool.acquire() as conn:
                row = await conn.fetchrow(query, *params)
                if row:
                    return {
                        "tool_id": row["tool_id"],
                        "tool_name": row["tool_name"],
                        "access_keys": list(row["access_keys"]) if row["access_keys"] else [],
                        "department_name": row["department_name"]
                    }
                return None
        except Exception as e:
            log.error(f"Error fetching access keys for tool name {tool_name}: {e}")
            return None

    async def get_tools_by_access_key(self, access_key: str, department_name: str = None) -> List[Dict[str, Any]]:
        """
        Get all tools that require a specific access key.
        
        Args:
            access_key: The access key to search for
            department_name: Optional department filter
            
        Returns:
            List of tools (tool_id, tool_name, access_keys, department_name) that use this access key
        """
        if department_name:
            query = f"""
            SELECT tool_id, tool_name, access_keys, department_name 
            FROM {self.table_name} 
            WHERE $1 = ANY(access_keys) AND department_name = $2
            """
            params = (access_key, department_name)
        else:
            query = f"""
            SELECT tool_id, tool_name, access_keys, department_name 
            FROM {self.table_name} 
            WHERE $1 = ANY(access_keys)
            """
            params = (access_key,)
        try:
            async with self.pool.acquire() as conn:
                rows = await conn.fetch(query, *params)
                return [
                    {
                        "tool_id": row["tool_id"],
                        "tool_name": row["tool_name"],
                        "access_keys": list(row["access_keys"]) if row["access_keys"] else [],
                        "department_name": row["department_name"]
                    }
                    for row in rows
                ]
        except Exception as e:
            log.error(f"Error fetching tools for access key {access_key}: {e}")
            return []

    async def get_all_tool_access_mappings(self, department_name: str = None) -> List[Dict[str, Any]]:
        """
        Get all tool access key mappings.
        
        Args:
            department_name: Optional department filter
        
        Returns:
            List of all mappings (tool_id, tool_name, access_keys, department_name)
        """
        if department_name:
            query = f"SELECT tool_id, tool_name, access_keys, department_name FROM {self.table_name} WHERE department_name = $1 ORDER BY tool_name"
            params = (department_name,)
        else:
            query = f"SELECT tool_id, tool_name, access_keys, department_name FROM {self.table_name} ORDER BY tool_name"
            params = ()
        try:
            async with self.pool.acquire() as conn:
                rows = await conn.fetch(query, *params)
                return [
                    {
                        "tool_id": row["tool_id"],
                        "tool_name": row["tool_name"],
                        "access_keys": list(row["access_keys"]) if row["access_keys"] else [],
                        "department_name": row["department_name"]
                    }
                    for row in rows
                ]
        except Exception as e:
            log.error(f"Error fetching all tool access mappings: {e}")
            return []

    async def delete_tool_access_keys(self, tool_id: str, department_name: str = None) -> bool:
        """
        Delete access key mapping for a tool.
        
        Args:
            tool_id: The tool's unique ID
            department_name: Optional department filter
            
        Returns:
            bool: True if successful
        """
        if department_name:
            query = f"DELETE FROM {self.table_name} WHERE tool_id = $1 AND department_name = $2"
            params = (tool_id, department_name)
        else:
            query = f"DELETE FROM {self.table_name} WHERE tool_id = $1"
            params = (tool_id,)
        try:
            async with self.pool.acquire() as conn:
                await conn.execute(query, *params)
            log.info(f"Deleted access key mapping for tool ID: {tool_id}")
            return True
        except Exception as e:
            log.error(f"Error deleting access keys for tool {tool_id}: {e}")
            return False

    async def delete_by_department(self, department_name: str) -> bool:
        """
        Delete all tool access key mappings for a department.
        
        Args:
            department_name: The department name
            
        Returns:
            bool: True if successful
        """
        query = f"DELETE FROM {self.table_name} WHERE department_name = $1"
        try:
            async with self.pool.acquire() as conn:
                result = await conn.execute(query, department_name)
            log.info(f"Deleted all tool access key mappings for department: {department_name}")
            return True
        except Exception as e:
            log.error(f"Error deleting tool access keys for department {department_name}: {e}")
            return False

    async def get_all_unique_access_keys(self, department_name: str = None) -> List[str]:
        """
        Get all unique access keys used across all tools.
        
        Args:
            department_name: Optional department filter
        
        Returns:
            List of unique access key names
        """
        if department_name:
            query = f"""
            SELECT DISTINCT unnest(access_keys) as access_key 
            FROM {self.table_name}
            WHERE department_name = $1
            ORDER BY access_key
            """
            params = (department_name,)
        else:
            query = f"""
            SELECT DISTINCT unnest(access_keys) as access_key 
            FROM {self.table_name}
            ORDER BY access_key
            """
            params = ()
        try:
            async with self.pool.acquire() as conn:
                rows = await conn.fetch(query, *params)
                return [row["access_key"] for row in rows]
        except Exception as e:
            log.error(f"Error fetching unique access keys: {e}")
            return []


class AccessKeyDefinitionsRepository:
    """
    Repository for managing access key definitions.
    
    This table stores the master list of access keys that exist in the system.
    Access keys are created manually by users and are associated with departments.
    Only the creator can delete an access key.
    
    Example:
        access_key: "employees"
        department_name: "HR"
        created_by: "admin@company.com"
        description: "Employee ID access for HR tools"
    """

    def __init__(self, pool: asyncpg.Pool):
        self.pool = pool
        self.table_name = "access_key_definitions"

    async def create_table_if_not_exists(self):
        """Create access_key_definitions table if it doesn't exist"""
        create_table_query = f"""
        CREATE TABLE IF NOT EXISTS {self.table_name} (
            access_key VARCHAR(100) NOT NULL,
            department_name VARCHAR(255) NOT NULL,
            created_by VARCHAR(255) NOT NULL,
            created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
            description TEXT,
            PRIMARY KEY (access_key, department_name)
        );
        
        CREATE INDEX IF NOT EXISTS idx_access_key_definitions_department 
        ON {self.table_name}(department_name);
        
        CREATE INDEX IF NOT EXISTS idx_access_key_definitions_created_by 
        ON {self.table_name}(created_by);
        """
        try:
            async with self.pool.acquire() as conn:
                await conn.execute(create_table_query)
            log.info(f"Table '{self.table_name}' created or already exists.")
        except Exception as e:
            log.error(f"Error creating table '{self.table_name}': {e}")
            raise

    async def create_access_key(
        self,
        access_key: str,
        department_name: str,
        created_by: str,
        description: str = None
    ) -> Dict[str, Any]:
        """
        Create a new access key definition.
        
        Args:
            access_key: Unique identifier for the access key
            department_name: Department this access key belongs to
            created_by: User who created this access key
            description: Optional description of what this access key controls
            
        Returns:
            Dict with success status and created access key info
        """
        query = f"""
        INSERT INTO {self.table_name} (access_key, department_name, created_by, description)
        VALUES ($1, $2, $3, $4)
        RETURNING access_key, department_name, created_by, created_at, description
        """
        try:
            async with self.pool.acquire() as conn:
                row = await conn.fetchrow(query, access_key, department_name, created_by, description)
                if row:
                    log.info(f"Created access key '{access_key}' for department '{department_name}' by {created_by}")
                    return {
                        "success": True,
                        "access_key": row["access_key"],
                        "department_name": row["department_name"],
                        "created_by": row["created_by"],
                        "created_at": str(row["created_at"]),
                        "description": row["description"]
                    }
                return {"success": False, "error": "Failed to create access key"}
        except asyncpg.UniqueViolationError:
            log.warning(f"Access key '{access_key}' already exists")
            return {"success": False, "error": f"Access key '{access_key}' already exists"}
        except Exception as e:
            log.error(f"Error creating access key '{access_key}': {e}")
            return {"success": False, "error": str(e)}

    async def get_access_keys_by_department(self, department_name: str) -> List[Dict[str, Any]]:
        """
        Get all access keys for a specific department.
        
        Args:
            department_name: Department to filter by
            
        Returns:
            List of access key definitions
        """
        query = f"""
        SELECT access_key, department_name, created_by, created_at, description
        FROM {self.table_name}
        WHERE department_name = $1
        ORDER BY access_key
        """
        try:
            async with self.pool.acquire() as conn:
                rows = await conn.fetch(query, department_name)
                return [
                    {
                        "access_key": row["access_key"],
                        "department_name": row["department_name"],
                        "created_by": row["created_by"],
                        "created_at": str(row["created_at"]),
                        "description": row["description"]
                    }
                    for row in rows
                ]
        except Exception as e:
            log.error(f"Error fetching access keys for department {department_name}: {e}")
            return []

    async def get_all_access_keys(self) -> List[Dict[str, Any]]:
        """
        Get all access key definitions.
        
        Returns:
            List of all access key definitions
        """
        query = f"""
        SELECT access_key, department_name, created_by, created_at, description
        FROM {self.table_name}
        ORDER BY department_name, access_key
        """
        try:
            async with self.pool.acquire() as conn:
                rows = await conn.fetch(query)
                return [
                    {
                        "access_key": row["access_key"],
                        "department_name": row["department_name"],
                        "created_by": row["created_by"],
                        "created_at": str(row["created_at"]),
                        "description": row["description"]
                    }
                    for row in rows
                ]
        except Exception as e:
            log.error(f"Error fetching all access keys: {e}")
            return []

    async def get_access_key(
        self, 
        access_key: str, 
        department_name: str = None
    ) -> Optional[Dict[str, Any]]:
        """
        Get a specific access key definition, optionally filtered by department.
        
        Args:
            access_key: The access key to retrieve
            department_name: Optional department to filter by
            
        Returns:
            Access key definition or None if not found
        """
        if department_name:
            query = f"""
            SELECT access_key, department_name, created_by, created_at, description
            FROM {self.table_name}
            WHERE access_key = $1 AND department_name = $2
            """
            params = [access_key, department_name]
        else:
            query = f"""
            SELECT access_key, department_name, created_by, created_at, description
            FROM {self.table_name}
            WHERE access_key = $1
            """
            params = [access_key]
        
        try:
            async with self.pool.acquire() as conn:
                row = await conn.fetchrow(query, *params)
                if row:
                    return {
                        "access_key": row["access_key"],
                        "department_name": row["department_name"],
                        "created_by": row["created_by"],
                        "created_at": str(row["created_at"]),
                        "description": row["description"]
                    }
                return None
        except Exception as e:
            log.error(f"Error fetching access key '{access_key}': {e}")
            return None

    async def delete_access_key(self, access_key: str, department_name: str, requesting_user: str) -> Dict[str, Any]:
        """
        Delete an access key. Only the creator can delete it.
        
        Args:
            access_key: The access key to delete
            department_name: The department the access key belongs to
            requesting_user: The user attempting to delete
            
        Returns:
            Dict with success status
        """
        # First check if user is the creator
        check_query = f"SELECT created_by FROM {self.table_name} WHERE access_key = $1 AND department_name = $2"
        delete_query = f"DELETE FROM {self.table_name} WHERE access_key = $1 AND department_name = $2 AND created_by = $3"
        
        try:
            async with self.pool.acquire() as conn:
                # Check ownership
                row = await conn.fetchrow(check_query, access_key, department_name)
                if not row:
                    return {"success": False, "error": f"Access key '{access_key}' not found in department '{department_name}'"}
                
                if row["created_by"] != requesting_user:
                    return {
                        "success": False, 
                        "error": f"Only the creator ({row['created_by']}) can delete this access key"
                    }
                
                # Delete
                result = await conn.execute(delete_query, access_key, department_name, requesting_user)
                if "DELETE 1" in result:
                    log.info(f"Deleted access key '{access_key}' in department '{department_name}' by {requesting_user}")
                    return {"success": True, "message": f"Access key '{access_key}' deleted successfully"}
                return {"success": False, "error": "Failed to delete access key"}
        except Exception as e:
            log.error(f"Error deleting access key '{access_key}': {e}")
            return {"success": False, "error": str(e)}

    async def update_access_key(
        self,
        access_key: str,
        department_name: str,
        description: str = None,
        requesting_user: str = None
    ) -> Dict[str, Any]:
        """
        Update an access key description. Only the creator can update it.
        
        Args:
            access_key: The access key to update
            department_name: The department the access key belongs to
            description: New description
            requesting_user: The user attempting to update
            
        Returns:
            Dict with success status
        """
        check_query = f"SELECT created_by FROM {self.table_name} WHERE access_key = $1 AND department_name = $2"
        update_query = f"""
        UPDATE {self.table_name}
        SET description = $3
        WHERE access_key = $1 AND department_name = $2 AND created_by = $4
        RETURNING access_key, department_name, created_by, created_at, description
        """
        
        try:
            async with self.pool.acquire() as conn:
                # Check ownership
                row = await conn.fetchrow(check_query, access_key, department_name)
                if not row:
                    return {"success": False, "error": f"Access key '{access_key}' not found in department '{department_name}'"}
                
                if requesting_user and row["created_by"] != requesting_user:
                    return {
                        "success": False, 
                        "error": f"Only the creator ({row['created_by']}) can update this access key"
                    }
                
                # Update
                updated = await conn.fetchrow(update_query, access_key, department_name, description, requesting_user or row["created_by"])
                if updated:
                    log.info(f"Updated access key '{access_key}' in department '{department_name}'")
                    return {
                        "success": True,
                        "access_key": updated["access_key"],
                        "department_name": updated["department_name"],
                        "created_by": updated["created_by"],
                        "created_at": str(updated["created_at"]),
                        "description": updated["description"]
                    }
                return {"success": False, "error": "Failed to update access key"}
        except Exception as e:
            log.error(f"Error updating access key '{access_key}': {e}")
            return {"success": False, "error": str(e)}