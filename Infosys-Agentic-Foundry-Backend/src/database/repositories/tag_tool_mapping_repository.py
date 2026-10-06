# © 2024-25 Infosys Limited, Bangalore, India. All Rights Reserved.
import asyncpg
from typing import List, Dict, Any
from src.config.constants import TableNames
from src.utils.cache_utils import CacheableRepository
from src.config.cache_config import EXPIRY_TIME

from telemetry_wrapper import logger as log

from src.database.repositories import BaseRepository


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
                await self._execute_with_retry(conn.execute, create_statement, operation_name="create_tag_tool_mapping_table")
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
                await self._execute_with_retry(conn.execute, insert_statement, tag_id, tool_id, operation_name="assign_tag_to_tool_record")
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
                result = await self._execute_with_retry(conn.execute, delete_statement, tag_id, tool_id, operation_name="remove_tag_from_tool_record")
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
                rows = await self._execute_with_retry(conn.fetch, query, operation_name="get_tool_tag_mappings")
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
                rows = await self._execute_with_retry(conn.fetch, query, tool_id, operation_name="get_tags_by_tool_id_records")
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
                result = await self._execute_with_retry(conn.execute, delete_statement, tool_id, operation_name="delete_all_tags_for_tool")
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
                constraint_record = await self._execute_with_retry(conn.fetchrow, constraint_query, operation_name="get_tool_id_fk_constraint")

                if constraint_record:
                    constraint_name = constraint_record['constraint_name']
                    drop_fk_statement = f"""
                    ALTER TABLE {self.table_name}
                    DROP CONSTRAINT {constraint_name};
                    """
                    await self._execute_with_retry(conn.execute, drop_fk_statement, operation_name="drop_tool_id_fk_constraint")
                    await self.invalidate_all_method_cache("get_tool_tag_mappings")
                    log.info(f"Successfully dropped foreign key constraint '{constraint_name}' on '{self.table_name}.tool_id'.")
                    return True
                else:
                    log.info(f"No foreign key constraint found on '{self.table_name}.tool_id' to drop. (This is expected if already removed).")
                    return False

        except Exception as e:
            log.error(f"Error attempting to drop foreign key constraint on '{self.table_name}.tool_id': {e}")
            return False

