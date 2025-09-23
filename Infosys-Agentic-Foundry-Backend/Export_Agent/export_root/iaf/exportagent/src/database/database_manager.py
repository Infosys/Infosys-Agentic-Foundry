# © 2024-25 Infosys Limited, Bangalore, India. All Rights Reserved.
import os
import asyncpg
from typing import List, Optional, Union, Dict
from exportagent.telemetry_wrapper import logger as log
from dotenv import load_dotenv

load_dotenv()


REQUIRED_DATABASES = [os.getenv("DATABASE", ""),"arize_traces"]


class DatabaseManager:
    """
    Manages asynchronous PostgreSQL database connection pools for multiple databases.

    This class provides methods to:
    - Initialize and store connection pools for various databases.
    - Connect to and disconnect from these databases.
    - Retrieve specific connection pools by name.
    - Perform administrative tasks like checking/creating databases and truncating/deleting tables.

    It uses environment variables for database configuration:
    - DATABASE: The actual name of the primary/main database (e.g., "agentic_workflow_as_service_database").
    - POSTGRESQL_DB_URL_PREFIX: The URL prefix (e.g., "postgresql://user:pass@host:port/")
                                to which database names are appended.
    """

    def __init__(self, alias_to_main_db: str = 'db_main'):
        """
        Initializes the DatabaseManager.

        The `pools` dictionary will store active connection pools, keyed by database name.
        The main database's pool will also be accessible via a configurable alias (default 'db_main').

        Args:
            alias_to_main_db (str): The alias key to use for the main database's connection pool
                                    in the `self.pools` dictionary. Defaults to 'db_main'.
        """
        self.pools: Dict[str, asyncpg.Pool] = {}
        self.db_main: str = os.getenv("DATABASE", "") # Actual name of the main database
        self.db_url_prefix: str = os.getenv("POSTGRESQL_DB_URL_PREFIX", "")
        self.alias: str = alias_to_main_db # The alias key for the main database pool


    async def check_and_create_databases(self, required_db_names: List[str]):
        """
        Connects to the 'postgres' administrative database and creates any missing
        required databases. This function should be called once during application startup
        before attempting to create connection pools to these specific databases.

        Args:
            required_db_names (List[str]): A list of database names that must exist.
                                           This list should include the main database name
                                           (from the DATABASE env var) if it's required.
        """
        if not self.db_url_prefix:
            log.error("Database URL prefix is not configured. Cannot check/create databases.")
            raise ValueError("Database URL prefix is not configured.")

        # Connect to the default 'postgres' database for administrative tasks
        # This connection is temporary and closed immediately after use.
        conn = None
        try:
            conn = await asyncpg.connect(f"{self.db_url_prefix}postgres")
            log.info(f"Connected to 'postgres' database for initial setup.")

            # Ensure all required databases exist
            for db_name in required_db_names:
                if db_name == self.alias:
                    db_name = self.db_main # Resolve alias to actual main DB name
                exists = await conn.fetchval("SELECT 1 FROM pg_database WHERE datname = $1", db_name)
                if not exists:
                    log.info(f"Database '{db_name}' not found. Creating...")
                    await conn.execute(f'CREATE DATABASE "{db_name}"')
                    log.info(f"Database '{db_name}' created successfully.")
                else:
                    log.info(f"Database '{db_name}' already exists.")
        except Exception as e:
            log.error(f"Error during database check and creation: {e}")
            raise # Re-raise to indicate a critical startup failure
        finally:
            if conn:
                await conn.close()
                log.info(f"Disconnected from 'postgres' database.")

    async def connect(self,
                      db_names: Optional[Union[List[str], str]] = None,
                      min_size: int = 10,
                      max_size: int = 15,
                      db_main_min_size: Optional[int] = None,
                      db_main_max_size: Optional[int] = None
                    ):
        """
        Asynchronously creates connection pools for one or more PostgreSQL databases.

        If `db_names` is None, only the main database connection pool is created.
        Otherwise, connection pools are initialized for all specified databases in `db_names`.

        Pool sizes can be configured:
        - `min_size`, `max_size`: Default pool sizes for all databases.
        - `db_main_min_size`, `db_main_max_size`: Custom pool sizes specifically for the main database.
                                                  If provided, these override the global defaults for the main DB.

        The main database's pool is stored under its actual name (from DATABASE env var)
        and also aliased under the key `self.alias` (default 'db_main') in `self.pools` for convenience.

        Args:
            db_names (Optional[Union[List[str], str]]): A list of database names or a single database name to connect to.
                If None, only the main database is connected.
            min_size (int): Minimum size of the connection pool.
            max_size (int): Maximum size of the connection pool.
            db_main_min_size (Optional[int]): Custom minimum size for the main database pool.
            db_main_max_size (Optional[int]): Custom maximum size for the main database pool.
        """
        if not self.db_url_prefix:
            log.error("Database URL prefix is not configured. Cannot create connection pools.")
            raise ValueError("Database URL prefix is not configured.")
        if not self.db_main:
            log.error("Main database name (DATABASE env var) is not configured. Cannot create main database pool.")
            raise ValueError("Main database name is not configured.")

        # Determine the list of databases to connect to
        databases_to_connect_actual_names: List[str] = []
        if not db_names:
            databases_to_connect_actual_names = [self.db_main]
        elif isinstance(db_names, str):
            databases_to_connect_actual_names = [db_names]
        else:
            databases_to_connect_actual_names = db_names


        for db_name_actual in databases_to_connect_actual_names:
            if db_name_actual == self.alias:
                db_name_actual = self.db_main # Resolve alias to actual main DB name
            # Skip if pool already exists for this database name
            if db_name_actual in self.pools:
                log.warning(f"Connection pool for '{db_name_actual}' already exists. Skipping creation.")
                continue

            # Determine pool sizes for the current database
            current_min_size = min_size
            current_max_size = max_size
            if db_name_actual == self.db_main and db_main_min_size is not None and db_main_max_size is not None:
                current_min_size = db_main_min_size
                current_max_size = db_main_max_size
            current_min_size = max(1, current_min_size)
            current_max_size = max(current_min_size, current_max_size)

            try:
                pool = await asyncpg.create_pool(
                    dsn=f"{self.db_url_prefix}{db_name_actual}",
                    min_size=current_min_size,
                    max_size=current_max_size
                )
                self.pools[db_name_actual] = pool
                
                # Alias the main database pool for convenience
                if db_name_actual == self.db_main:
                    self.pools[self.alias] = pool
                
                log.info(f"Connection pool for database '{db_name_actual}' created successfully (min={current_min_size}, max={current_max_size}).")
            except Exception as e:
                log.error(f"Failed to create pool for database '{db_name_actual}': {e}")

    async def get_pool(self, name: str) -> asyncpg.Pool:
        """
        Retrieves a specific connection pool by its name.

        Args:
            name (str): The name of the database (e.g., 'feedback_learning', 'login')
                        or the alias `self.alias` (default 'db_main') for the primary database.

        Returns:
            asyncpg.Pool: The requested connection pool.

        Raises:
            ValueError: If the specified connection pool is not available or not connected.
        """
        pool = self.pools.get(name, None)
        if not pool:
            log.error(f"Attempted to get pool '{name}', but it is not available or not connected.")
            raise ValueError(f"Connection pool '{name}' is not available or not connected.")
        return pool

    async def close(self, db_names: Optional[Union[List[str], str]] = None):
        """
        Closes one or more database connection pools.

        If `db_names` is None, all active connection pools managed by this instance are closed.
        Otherwise, only the specified pools are closed.

        Args:
            db_names (Optional[Union[List[str], str]]): A list of database names or a single database name to close.
                                                        Can use `self.alias` or the actual main database name.
        """
        if db_names is None:
            self.pools.pop(self.alias, None)
            db_names = list(self.pools.keys())
        elif isinstance(db_names, str):
            db_names = [db_names]

        for db_name in db_names:
            pool = self.pools.pop(db_name, None)
            if pool:
                await pool.close()
                if db_name == self.alias:
                    self.pools.pop(self.db_main, None)
                elif db_name == self.db_main:
                    self.pools.pop(self.alias, None)
                log.info(f"Connection pool '{db_name}' closed.")
            else:
                log.warning(f"Connection pool '{db_name}' does not exist or is already closed.")

    async def delete_table(self, table_name: str, db_name: str):
        """
        Deletes a PostgreSQL table asynchronously from a specified database.

        Args:
            table_name (str): The name of the table to delete.
            db_name (str): The name of the database where the table resides.
                           Can be the actual database name or `self.alias`.
        """
        try:
            pool = await self.get_pool(db_name) # Use get_pool to retrieve the correct pool
            
            drop_statement = f"DROP TABLE IF EXISTS {table_name} CASCADE;" # Added CASCADE for safety
            
            async with pool.acquire() as connection:
                await connection.execute(drop_statement)
            log.info(f"Table '{table_name}' deleted successfully from database '{db_name}'.")

        except ValueError as ve:
            log.error(f"Error deleting table '{table_name}': {ve}") # Pool not found
        except Exception as e:
            log.error(f"Error deleting table '{table_name}' from database '{db_name}': {e}")

    async def truncate_table(self, table_name: str, db_name: str):
        """
        Truncates a PostgreSQL table asynchronously, removing all data while keeping the table structure.

        Args:
            table_name (str): The name of the table to truncate.
            db_name (str): The name of the database where the table resides.
                           Can be the actual database name or `self.alias`.
        """
        try:
            pool = await self.get_pool(db_name) # Use get_pool to retrieve the correct pool
            
            truncate_statement = f"TRUNCATE TABLE {table_name} RESTART IDENTITY CASCADE;" # Added RESTART IDENTITY and CASCADE
            
            async with pool.acquire() as connection:
                await connection.execute(truncate_statement)
            log.info(f"Table '{table_name}' truncated successfully in database '{db_name}'.")

        except ValueError as ve:
            log.error(f"Error truncating table '{table_name}': {ve}") # Pool not found
        except Exception as e:
            log.error(f"Error truncating table '{table_name}' in database '{db_name}': {e}")



