# © 2024-25 Infosys Limited, Bangalore, India. All Rights Reserved.
import uuid
import asyncpg
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from fastapi import HTTPException
from motor.motor_asyncio import AsyncIOMotorClient
 
class MultiDBConnectionManager:
    def __init__(self):
        self.sql_engines = {}
        self.sql_sessions = {}
        self.mongo_clients = {}
        self.mongo_databases = {}

    # SQL management
    def add_sql_database(self, db_key, db_url, pool_size=20, max_overflow=10):
        if db_key in self.sql_engines:
            return  # already exists
        engine = create_engine(db_url, pool_size=pool_size, max_overflow=max_overflow, echo=False, future=True)
        Session = sessionmaker(bind=engine, autocommit=False, autoflush=False)
        self.sql_engines[db_key] = engine
        self.sql_sessions[db_key] = Session
        print(f"[SQL] Initialized engine for '{db_key}'")

    def get_sql_session(self, db_key):
        if db_key not in self.sql_sessions:
            raise Exception(f"No SQL session found for key '{db_key}'")
        return self.sql_sessions[db_key]()

    def dispose_sql_engine(self, db_key):
        # if db_key in self.sql_engines:
        #     self.sql_engines[db_key].dispose()
        #     print(f"[SQL] Disposed engine for '{db_key}'")
        if db_key in self.sql_sessions:
            session = self.sql_sessions[db_key]()
            session.close()
            del self.sql_sessions[db_key]

        if db_key in self.sql_engines:
            self.sql_engines[db_key].dispose()
            del self.sql_engines[db_key]
            print(f"[SQL] Disposed engine for '{db_key}'")

    # MongoDB management
    def add_mongo_database(self, db_key, uri, db_name, max_pool_size=30):
        if db_key in self.mongo_clients:
            return  # already exists
        client = AsyncIOMotorClient(uri, maxPoolSize=max_pool_size)
        self.mongo_clients[db_key] = client
        self.mongo_databases[db_key] = client[db_name]
        print(f"[MongoDB] Initialized client for '{db_key}'")

    def get_mongo_database(self, db_key):
        if db_key not in self.mongo_databases:
            raise Exception(f"No MongoDB database found for key '{db_key}'")
        return self.mongo_databases[db_key]

    async def close_mongo_client(self, db_key):
        if db_key in self.mongo_clients:
            # Close the client
            self.mongo_clients[db_key].close()
            # Remove from dictionaries
            del self.mongo_clients[db_key]
            del self.mongo_databases[db_key]
            print(f"[MongoDB] Closed and removed client for '{db_key}'")

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
                print(f"[SQL] Disposed engine for '{key}'")
    
        # Close all MongoDB clients and databases
        for key in list(self.mongo_clients.keys()):
            if key in self.mongo_clients:
                self.mongo_clients[key].close()
                del self.mongo_clients[key]
                print(f"[MongoDB] Closed client for '{key}'")
        
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
                connection_database_name VARCHAR(255)            -- Name of the database    
            )
            """

            # Execute the SQL statement
            async with self.pool.acquire() as connection:
                await connection.execute(create_statement)

            print(f"Table '{self.table_name}' created successfully or already exists.")

        except Exception as e:
            print(f"Error creating table '{self.table_name}': {e}")

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
                connection_database_name
            ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
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
                connection_data.get("connection_database_name")
            )

            # Execute the insert statement
            async with self.pool.acquire() as connection:
                await connection.execute(insert_statement, *values)

            return {
                "message": f"Successfully inserted connection with ID: {connection_data['connection_id']}",
                "connection_id": connection_data["connection_id"],
                "connection_name": connection_data.get("connection_name", ""),
                "database_type": connection_data.get("database_type", ""),
                "is_created": True
            }

        except asyncpg.UniqueViolationError as e:
            return {
                "message": f"Integrity error inserting data into '{self.table_name}': {e}",
                "connection_id": "",
                "connection_name": connection_data.get("connection_name", ""),
                "database_type": connection_data.get("database_type", ""),
                "is_created": False
            }

        except Exception as e:
            return {
                "message": f"Error inserting data into '{self.table_name}': {e}",
                "connection_id": "",
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
                    connection_port, connection_username, connection_password,connection_database_name
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
                "database": row["connection_database_name"]
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
                rows = await conn.fetch("SELECT connection_name, connection_database_type, connection_host, connection_port, connection_username , connection_password, connection_database_name FROM db_connections_table")
            connections = [
                {
                    "connection_name": row["connection_name"],
                    "connection_database_type": row["connection_database_type"],
                    "connection_host": row["connection_host"],
                    "connection_port": row["connection_port"],
                    "connection_username": row["connection_username"],
                    "connection_password": row["connection_password"],
                    "connection_database_name": row["connection_database_name"]
                }
                for row in rows
            ]
            return {"connections": connections}
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))

