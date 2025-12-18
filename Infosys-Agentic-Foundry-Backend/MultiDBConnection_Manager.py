# © 2024-25 Infosys Limited, Bangalore, India. All Rights Reserved.
import uuid
import asyncpg
from sqlalchemy import create_engine,text
from sqlalchemy.orm import sessionmaker
from fastapi import HTTPException
from motor.motor_asyncio import AsyncIOMotorClient
from telemetry_wrapper import logger as log, update_session_context
import os


class MultiDBConnectionManager:
    def __init__(self):
        self.sql_engines = {}
        self.sql_sessions = {}
        self.mongo_clients = {}
        self.mongo_databases = {}

        self.pg_host = os.getenv("POSTGRESQL_HOST", "localhost")
        self.pg_port = os.getenv("POSTGRESQL_PORT", "5432")
        self.pg_user = os.getenv("POSTGRESQL_USER", "postgres")
        self.pg_password = os.getenv("POSTGRESQL_PASSWORD", "postgres")
        self.pg_database = os.getenv("DATABASE", "agentic_workflow_as_Service_database")
        self.table_name = "db_connections_table"
        # ✅ Add metadata engine attributes
        self._metadata_engine = None
        self._metadata_session_factory = None

    # SQL management
    def _fetch_connection_config_sync(self, connection_name: str) -> dict:
        """
        Synchronously fetch connection config from PostgreSQL using SQLAlchemy.
        
        Args:
            connection_name: Name of the connection to retrieve
            
        Returns:
            dict: Connection configuration
            
        Raises:
            Exception: If connection not found or database error
        """
        session = None
        try:
            # ✅ Create metadata engine if not exists
            if self._metadata_engine is None:
                db_url = f"postgresql://{self.pg_user}:{self.pg_password}@{self.pg_host}:{self.pg_port}/{self.pg_database}"
                self._metadata_engine = create_engine(db_url, pool_size=5, max_overflow=5, echo=False, future=True)
                self._metadata_session_factory = sessionmaker(bind=self._metadata_engine, autocommit=False, autoflush=False)
                log.debug("[SQL] Created metadata engine for connection config queries")
            
            # Get session
            session = self._metadata_session_factory()
            
            # Check if connection exists
            check_query = text(f"SELECT 1 FROM {self.table_name} WHERE connection_name = :name LIMIT 1")
            exists = session.execute(check_query, {"name": connection_name}).fetchone()
            
            if not exists:
                raise Exception(
                    f"Connection '{connection_name}' does not exist in the database. "
                    "Please create the connection first or check the connection name."
                )
            
            # Fetch connection configuration
            fetch_query = text(f"""
                SELECT connection_name, connection_database_type, connection_host,
                       connection_port, connection_username, connection_password, 
                       connection_database_name, connection_created_by
                FROM {self.table_name}
                WHERE connection_name = :name
            """)
            
            result = session.execute(fetch_query, {"name": connection_name})
            row = result.fetchone()
            
            if not row:
                raise Exception(f"Connection '{connection_name}' not found")
            
            # Convert Row to dict
            if hasattr(row, '_mapping'):
                row_dict = dict(row._mapping)
            else:
                row_dict = {
                    "connection_name": row[0],
                    "connection_database_type": row[1],
                    "connection_host": row[2],
                    "connection_port": row[3],
                    "connection_username": row[4],
                    "connection_password": row[5],
                    "connection_database_name": row[6],
                    "connection_created_by": row[7] if len(row) > 7 else None
                }
            
            config = {
                "name": row_dict.get("connection_name"),
                "db_type": row_dict.get("connection_database_type"),
                "host": row_dict.get("connection_host"),
                "port": row_dict.get("connection_port"),
                "username": row_dict.get("connection_username"),
                "password": row_dict.get("connection_password"),
                "database": row_dict.get("connection_database_name"),
                "created_by": row_dict.get("connection_created_by")
            }
            
            return config
            
        except Exception as e:
            log.error(f"[SQL] Error fetching connection config for '{connection_name}': {e}")
            raise
        finally:
            if session:
                session.close()
    
    def add_sql_database(self, db_key, db_url, pool_size=20, max_overflow=10):
        if db_key in self.sql_engines:
            return  # already exists
        engine = create_engine(db_url, pool_size=pool_size, max_overflow=max_overflow, echo=False, future=True)
        Session = sessionmaker(bind=engine, autocommit=False, autoflush=False)
        self.sql_engines[db_key] = engine
        self.sql_sessions[db_key] = Session
        log.debug(f"[SQL] Initialized engine for '{db_key}'")

    def get_sql_session(self, db_key):
        """
        Get SQL session. If not exists, fetch config from DB and initialize.
        
        Args:
            db_key: Name of the connection to retrieve
            
        Returns:
            SQLAlchemy session instance
            
        Raises:
            Exception: If connection name doesn't exist in database or initialization fails
        """
        # If session already exists, return it
        if db_key in self.sql_sessions:
            log.debug(f"[SQL] Returning existing session for '{db_key}'")
            return self.sql_sessions[db_key]()
        
        try:
            log.debug(f"[SQL] Fetching connection configuration for '{db_key}'")
            # Fetch connection details from database synchronously
            config = self._fetch_connection_config_sync(db_key)
            
            # Build database URL based on database type
            db_type = config['db_type'].lower()
            username = config['username']
            password = config['password']
            host = config['host']
            port = config['port']
            database = config['database']
            
            log.debug(f"[SQL] Building connection URL for '{db_key}' (type: {db_type})")
            # Construct database URL based on type
            if db_type == 'postgresql':
                db_url = f"postgresql://{username}:{password}@{host}:{port}/{database}"
            elif db_type == 'mysql':
                db_url = f"mysql+pymysql://{username}:{password}@{host}:{port}/{database}"
            elif db_type == 'sqlite':
                db_url = f"sqlite:///{database}"
            else:
                log.error(f"[SQL] Unsupported database type '{db_type}' for connection '{db_key}'")
                raise Exception(
                    f"Unsupported database type '{db_type}' for connection '{db_key}'. "
                    "Supported types are: postgresql, mysql, sqlite"
                )
            
            # Initialize the connection
            log.info(f"[SQL] Auto-initializing connection '{db_key}' from database config")
            self.add_sql_database(db_key, db_url)
            
            # Return the session
            log.info(f"[SQL] Successfully initialized and returning session for '{db_key}'")
            return self.sql_sessions[db_key]()
            
        except KeyError as e:
            # Handle missing keys in config
            log.error(f"[SQL] Invalid connection configuration for '{db_key}': Missing field {str(e)}")
            raise Exception(f"Invalid connection configuration for '{db_key}': Missing field {str(e)}")
        except Exception as e:
            # Handle any other exceptions
            if "does not exist in the database" in str(e):
                raise  # Re-raise connection not found errors
            log.error(f"[SQL] Failed to initialize SQL session for '{db_key}': {str(e)}")
            raise Exception(f"Failed to initialize SQL session for '{db_key}': {str(e)}")

    def dispose_sql_engine(self, db_key):
        # if db_key in self.sql_engines:
        #     self.sql_engines[db_key].dispose()
        #     log.debug(f"[SQL] Disposed engine for '{db_key}'")
        if db_key in self.sql_sessions:
            session = self.sql_sessions[db_key]()
            session.close()
            del self.sql_sessions[db_key]

        if db_key in self.sql_engines:
            self.sql_engines[db_key].dispose()
            del self.sql_engines[db_key]
            log.debug(f"[SQL] Disposed engine for '{db_key}'")

    # MongoDB management
    def add_mongo_database(self, db_key, uri, db_name, max_pool_size=30):
        if db_key in self.mongo_clients:
            return  # already exists
        client = AsyncIOMotorClient(uri, maxPoolSize=max_pool_size)
        self.mongo_clients[db_key] = client
        self.mongo_databases[db_key] = client[db_name]
        log.debug(f"[MongoDB] Initialized client for '{db_key}'")

    # def get_mongo_database(self, db_key):
    #     if db_key not in self.mongo_databases:
    #         raise Exception(f"No MongoDB database found for key '{db_key}'")
    #     return self.mongo_databases[db_key]
    def get_mongo_database(self, db_key):
        """
        Get MongoDB database. If not exists, fetch config from DB and initialize.
        
        Args:
            db_key: Name of the connection to retrieve
            
        Returns:
            MongoDB database instance
            
        Raises:
            Exception: If connection name doesn't exist in database or initialization fails
        """
        # If database already exists, return it
        if db_key in self.mongo_databases:
            log.debug(f"[MongoDB] Returning existing database for '{db_key}'")
            return self.mongo_databases[db_key]
        
        try:
            log.debug(f"[MongoDB] Fetching connection configuration for '{db_key}'")
            # Fetch connection details from database synchronously
            config = self._fetch_connection_config_sync(db_key)
            
            # Build MongoDB URI based on configuration
            db_type = config['db_type'].lower()
            
            if db_type != 'mongodb':
                log.error(f"[MongoDB] Invalid database type '{db_type}' for connection '{db_key}'")
                raise Exception(
                    f"Connection '{db_key}' is not a MongoDB connection (type: {db_type}). "
                    "Use get_sql_session() for SQL databases."
                )
            
            username = config['username']
            password = config['password']
            host = config['host']
            port = config['port']
            database_name = config['database']
            
            log.debug(f"[MongoDB] Building connection URI for '{db_key}'")
            
            # Construct MongoDB URI
            # Format: mongodb://username:<PWD>@host:port/
            if username and password:
                mongo_uri = f"mongodb://{username}:{password}@{host}:{port}/"
            else:
                mongo_uri = f"mongodb://{host}:{port}/"
            
            # Initialize the MongoDB connection
            log.info(f"[MongoDB] Auto-initializing connection '{db_key}' from database config")
            self.add_mongo_database(db_key, mongo_uri, database_name)
            
            # Return the database
            log.info(f"[MongoDB] Successfully initialized and returning database for '{db_key}'")
            return self.mongo_databases[db_key]
            
        except KeyError as e:
            # Handle missing keys in config
            log.error(f"[MongoDB] Invalid connection configuration for '{db_key}': Missing field {str(e)}")
            raise Exception(f"Invalid connection configuration for '{db_key}': Missing field {str(e)}")
        except Exception as e:
            # Handle any other exceptions
            if "does not exist in the database" in str(e):
                raise  # Re-raise connection not found errors
            log.error(f"[MongoDB] Failed to initialize MongoDB database for '{db_key}': {str(e)}")
            raise Exception(f"Failed to initialize MongoDB database for '{db_key}': {str(e)}")

    async def close_mongo_client(self, db_key):
        if db_key in self.mongo_clients:
            # Close the client
            self.mongo_clients[db_key].close()
            # Remove from dictionaries
            del self.mongo_clients[db_key]
            del self.mongo_databases[db_key]
            log.debug(f"[MongoDB] Closed and removed client for '{db_key}'")

    async def close_all(self):
        # Close all SQL sessions and engines
        for key in list(self.sql_sessions.keys()):
            if key in self.sql_sessions:
                session = self.sql_sessions[key]()
                session.close()
                del self.sql_sessions[key]
        
        for key in list(self.sql_engines.keys()):
            if key in self.sql_engines:
                self.sql_engines[key].dispose()
                del self.sql_engines[key]
                log.debug(f"[SQL] Disposed engine for '{key}'")
    
        # Close all MongoDB clients and databases
        for key in list(self.mongo_clients.keys()):
            if key in self.mongo_clients:
                self.mongo_clients[key].close()
                del self.mongo_clients[key]
                log.debug(f"[MongoDB] Closed client for '{key}'")
        
        for key in list(self.mongo_databases.keys()):
            if key in self.mongo_databases:
                del self.mongo_databases[key]

    # ✅ Singleton instance

_connection_manager = MultiDBConnectionManager()
 
def get_connection_manager():
    return _connection_manager


class MultiDBConnectionRepository:
    def __init__(self, pool: asyncpg.Pool, table_name: str = "db_connections_table"):
        # super().__init__()
        self.pool = pool
        self.table_name = table_name

    async def create_db_connections_table_if_not_exists(self):
        """
        Creates the db_connections_table in PostgreSQL if it does not exist.
        """
        try:
            # SQL to create the table with appropriate data types
            create_statement = f"""
            CREATE TABLE IF NOT EXISTS {self.table_name} (
                connection_id TEXT PRIMARY KEY,                      -- Unique identifier for each connection
                connection_name TEXT UNIQUE,                        -- Unique name for the connection
                connection_database_type VARCHAR(50),                          -- Type of the database (e.g., PostgreSQL, MySQL)
                connection_host VARCHAR(255),                       -- Host address of the database
                connection_port INTEGER,                            -- Port number of the database
                connection_username VARCHAR(100),                   -- Username for the database
                connection_password TEXT,                           -- Password (store securely or encrypted in real systems)
                connection_database_name VARCHAR(255),            -- Name of the database    
                connection_created_by VARCHAR(255)                         -- email of the user
            )
            """

            # Execute the SQL statement
            # async with self.pool.acquire() as connection:
            #     await connection.execute(create_statement)

            # log.debug(f"Table '{self.table_name}' created successfully or already exists.")

            async with self.pool.acquire() as conn:
                await conn.execute(create_statement)
                alter_statements = [
                    f"ALTER TABLE {self.table_name} ADD COLUMN IF NOT EXISTS connection_created_by TEXT"
                ]

                for stmt in alter_statements:
                    await conn.execute(stmt)
            log.info(f"Table '{self.table_name}' created successfully or already exists.")

        except Exception as e:
            log.debug(f"Error creating table '{self.table_name}': {e}")

    async def insert_into_db_connections_table(self, connection_data: dict):
        """
        Inserts data into the db_connections_table in PostgreSQL asynchronously.

        Args:
            connection_data (dict): A dictionary containing the connection details to insert.

        Returns:
            dict: Status of the operation, including success message or error details.
        """
        # Generate connection_id if not provided
        if not connection_data.get("connection_id"):
            connection_data["connection_id"] = str(uuid.uuid4())

        try:
            # Build SQL INSERT statement
            insert_statement = f"""
            INSERT INTO {self.table_name} (
                connection_id,
                connection_name,
                connection_database_type,
                connection_host,
                connection_port,
                connection_username,
                connection_password,
                connection_database_name,
                connection_created_by
            ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
            """

            # Extract values from connection_data for insertion
            values = (
                connection_data.get("connection_id"),
                connection_data.get("connection_name"),
                connection_data.get("connection_database_type"),
                connection_data.get("connection_host"),
                int(connection_data.get("connection_port", 0)),
                connection_data.get("connection_username"),
                connection_data.get("connection_password"),
                connection_data.get("connection_database_name"),
                connection_data.get("connection_created_by")
            )

            # Execute the insert statement
            async with self.pool.acquire() as connection:
                await connection.execute(insert_statement, *values)

            return {
                "message": f"Successfully inserted connection with connection name: {connection_data.get('connection_name', '')}",
                
                "connection_name": connection_data.get("connection_name", ""),
                "database_type": connection_data.get("database_type", ""),
                "is_created": True
            }

        except asyncpg.UniqueViolationError as e:
            return {
                "message": f"Integrity error inserting data into '{self.table_name}': {e}",
                "connection_name": connection_data.get("connection_name", ""),
                "database_type": connection_data.get("database_type", ""),
                "is_created": False
            }

        except Exception as e:
            return {
                "message": f"Error inserting data into '{self.table_name}': {e}",
                "connection_name": connection_data.get("connection_name", ""),
                "database_type": connection_data.get("database_type", ""),
                "is_created": False
            }

    async def check_connection_name_exists(self, name: str) -> bool:
        try:
            query = f"SELECT 1 FROM {self.table_name} WHERE connection_name = $1 LIMIT 1"
            async with self.pool.acquire() as connection:
                result = await connection.fetchrow(query, name)
            return result is not None
        except Exception as e:
            # Log or handle error if necessary
            raise HTTPException(status_code=500, detail=f"Error checking connection name: {e}")

    async def delete_connection_by_name(self, name: str):
        try:
            delete_query = f"DELETE FROM {self.table_name} WHERE connection_name = $1"
            async with self.pool.acquire() as connection:
                result = await connection.execute(delete_query, name)

            return {"message": f"Deleted: {name}", "result": result}

        except Exception as e:
            return {"error": str(e)}

    async def get_connection_config(self, connection_name: str):
        try:
            query = f"""
                SELECT connection_name, connection_database_type, connection_host,
                    connection_port, connection_username, connection_password,connection_database_name,connection_created_by
                FROM {self.table_name}
                WHERE connection_name = $1
            """
            async with self.pool.acquire() as conn:
                row = await conn.fetchrow(query, connection_name)

            if not row:
                raise HTTPException(status_code=404, detail="Connection not found")

            config = {
                "name": row["connection_name"],
                "db_type": row["connection_database_type"],
                "host": row["connection_host"],
                "port": row["connection_port"],
                "username": row["connection_username"],
                "password": row["connection_password"],
                "database": row["connection_database_name"],
                "created_by": row["connection_created_by"]
            }

            return config

        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))

    async def get_connections_sql(self):
        try:
            async with self.pool.acquire() as conn:
                rows = await conn.fetch(f"SELECT connection_name,connection_database_type FROM {self.table_name} WHERE connection_database_type='mysql' OR connection_database_type='postgresql' OR connection_database_type='sqlite'")
            connections = [
                {
                    "connection_name": row["connection_name"],
                    "connection_database_type": row["connection_database_type"]
                }
                for row in rows
            ]
            return {"connections": connections}
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))

    async def get_connections_mongodb(self):
        try:
            async with self.pool.acquire() as conn:
                # Fetch all MongoDB connections
                rows = await conn.fetch(f"SELECT connection_name , connection_database_type FROM {self.table_name} where connection_database_type='mongodb'")
            connections = [
                {
                    "connection_name": row["connection_name"],
                    "connection_database_type": row["connection_database_type"]
                    
                }
                for row in rows
            ]
            return {"connections": connections}
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))

    async def get_connections(self):
        try:
            async with self.pool.acquire() as conn:
                rows = await conn.fetch("SELECT connection_name, connection_database_type FROM db_connections_table")
            connections = [
                {
                    "connection_name": row["connection_name"],
                    "connection_database_type": row["connection_database_type"]
                    
                }
                for row in rows
            ]
            return {"connections": connections}
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))

    async def get_user_email(self, connection_name: str):
        try:
            query = f"""
                SELECT connection_created_by
                FROM {self.table_name}
                WHERE connection_name = $1
            """
            async with self.pool.acquire() as conn:
                row = await conn.fetchrow(query, connection_name)

            if not row:
                raise HTTPException(status_code=404, detail="Connection not found")

            config = {
                "created_by": row["connection_created_by"]
            }

            return config

        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))

 