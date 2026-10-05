# © 2024-25 Infosys Limited, Bangalore, India. All Rights Reserved.
import asyncpg
from typing import List, Dict, Any
from src.config.constants import TableNames
from src.utils.cache_utils import CacheableRepository
from src.config.cache_config import EXPIRY_TIME

from telemetry_wrapper import logger as log

from src.database.repositories import BaseRepository


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
                await self._execute_with_retry(conn.execute, insert_statement, tag_id, agentic_application_id, operation_name="assign_tag_to_agent_record")
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
                result = await self._execute_with_retry(conn.execute, delete_statement, tag_id, agentic_application_id, operation_name="remove_tag_from_agent_record")
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
                rows = await self._execute_with_retry(conn.fetch, query, operation_name="get_agent_tag_mappings")
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
                rows = await self._execute_with_retry(conn.fetch, query, agent_id, operation_name="get_tags_by_agent_id_records")
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
                result = await self._execute_with_retry(conn.execute, delete_statement, agent_id, operation_name="delete_all_tags_for_agent")
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

