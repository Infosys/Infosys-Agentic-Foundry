# © 2024-25 Infosys Limited, Bangalore, India. All Rights Reserved.
import uuid
import asyncpg
from typing import List, Dict, Any, Optional
from src.config.constants import TableNames
from src.utils.cache_utils import CacheableRepository
from src.config.cache_config import EXPIRY_TIME

from telemetry_wrapper import logger as log

from src.database.repositories import BaseRepository


class TagRepository(BaseRepository, CacheableRepository):
    """
    Repository for the 'tags_table'. Handles direct database interactions for tags.
    """

    def __init__(self, pool: asyncpg.Pool, login_pool: asyncpg.Pool, table_name: str = TableNames.TAG.value):
        """
        Initializes the TagRepository.

        Args:
            pool (asyncpg.Pool): The asyncpg connection pool.
            login_pool (asyncpg.Pool): The asyncpg connection pool for login database (if needed).
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
                await self._execute_with_retry(conn.execute, create_statement, operation_name="create_tags_table")

                # Migration: Ensure UNIQUE constraint exists on tag_name (for existing tables)
                try:
                    await self._execute_with_retry(conn.execute, f"""
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
                    await self._execute_with_retry(conn.execute, insert_query, str(uuid.uuid4()), default_tag, operation_name="insert_default_tag")

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
                await self._execute_with_retry(conn.execute, insert_statement, tag_id, tag_name.strip(), created_by, operation_name="insert_tag_record")
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
                rows = await self._execute_with_retry(conn.fetch, query, operation_name="get_all_tag_records")
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
            query += "LOWER(tag_name) = LOWER($1)"
            param = tag_name
        else:
            log.warning("No tag_id or tag_name provided to get_tag_record.")
            return {}

        try:
            async with self.pool.acquire() as conn:
                row = await self._execute_with_retry(conn.fetchrow, query, param, operation_name="get_tag_record")
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
                result = await self._execute_with_retry(conn.execute, update_statement, new_tag_name, tag_id, created_by, operation_name="update_tag_record")
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
                result = await self._execute_with_retry(conn.execute, delete_statement, tag_id, created_by, operation_name="delete_tag_record")
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

