# © 2024-25 Infosys Limited, Bangalore, India. All Rights Reserved.
import os
import re
import json
import uuid
import asyncpg
from dotenv import load_dotenv
from typing import List, Optional
from datetime import datetime, timezone

from src.models.model import load_model
from src.database.services import ToolService
from telemetry_wrapper import logger as log
from motor.motor_asyncio import AsyncIOMotorClient
import asyncio


load_dotenv()
# Connection string format:

Postgre_string = os.getenv("DATABASE_URL")

POSTGRESQL_HOST = os.getenv("POSTGRESQL_HOST", "")
POSTGRESQL_USER = os.getenv("POSTGRESQL_USER", "")
POSTGRESQL_PASSWORD = os.getenv("POSTGRESQL_PASSWORD", "")
DATABASE = os.getenv("DATABASE", "")
DATABASE_URL = os.getenv("POSTGRESQL_DATABASE_URL", "")



async def assign_general_tag_to_untagged_items(general_tag_name="General"):
    """
    Assigns a general tag to all agents and tools that currently have no tags.

    Args:
        general_tag_name (str): The name of the general tag. Defaults to 'General'.

    Returns:
        bool: True if the operation was successful, False otherwise.
    """
    connection = None
    try:
        # PostgreSQL connection
        connection = await asyncpg.connect(
            host=POSTGRESQL_HOST,
            database=DATABASE,
            user=POSTGRESQL_USER,
            password=POSTGRESQL_PASSWORD
        )

        # Table names
        tag_table_name = "tags_table"
        tool_table_name = "tool_table"
        agent_table_name = "agent_table"
        tool_tag_mapping_table_name = "tag_tool_mapping_table"
        agent_tag_mapping_table_name = "tag_agentic_app_mapping_table"

        async with connection.transaction():
            # 1️ Check if the general tag exists
            query = f"SELECT tag_id FROM {tag_table_name} WHERE tag_name = $1"
            result = await connection.fetchrow(query, general_tag_name)

            if result:
                general_tag_id = result["tag_id"]
            else:
                # Insert general tag if it doesn't exist
                query = f"INSERT INTO {tag_table_name} (tag_name) VALUES ($1) RETURNING tag_id"
                result = await connection.fetchrow(query, general_tag_name)
                general_tag_id = result["tag_id"]

            # 2️ Assign general tag to untagged tools
            query = f"""
                SELECT tl.tool_id
                FROM {tool_table_name} tl
                LEFT JOIN {tool_tag_mapping_table_name} m ON tl.tool_id = m.tool_id
                WHERE m.tag_id IS NULL
            """
            rows = await connection.fetch(query)
            untagged_tools = [row["tool_id"] for row in rows]

            # Batch insert for tools
            if untagged_tools:
                insert_values = [(tool_id, general_tag_id) for tool_id in untagged_tools]
                await connection.executemany(
                        f"""
                        INSERT INTO {tool_tag_mapping_table_name} (tool_id, tag_id)
                        VALUES ($1, $2)
                        """,
                        insert_values
                    )
            # 3️ Assign general tag to untagged agents
            query = f"""
                SELECT a.agentic_application_id
                FROM {agent_table_name} a
                LEFT JOIN {agent_tag_mapping_table_name} m ON a.agentic_application_id = m.agentic_application_id
                WHERE m.tag_id IS NULL
            """
            rows = await connection.fetch(query)
            untagged_agents = [row["agentic_application_id"] for row in rows]

            # Batch insert for agents
            insert_values = [(agent_id, general_tag_id) for agent_id in untagged_agents]
            await connection.executemany(
                        f"""
                        INSERT INTO {agent_tag_mapping_table_name} (agentic_application_id, tag_id)
                        VALUES ($1, $2)
                        """,
                        insert_values
                    )

        log.info("Assigned all empty tags with General tag successfully")
        return True

    except asyncpg.PostgresError as e:
        log.error(f"Error assigning general tag: {e}")
        return False

    finally:
        if connection:  # Make sure connection is not None before closing
            await connection.close()



# Model initialization
async def create_models_table_if_not_exists(models_table="models"):
    connection = None  
    try:
        connection = await asyncpg.connect(
            host=POSTGRESQL_HOST,
            database=DATABASE,
            user=POSTGRESQL_USER,
            password=POSTGRESQL_PASSWORD
        )

        create_statement = f"""
        CREATE TABLE IF NOT EXISTS {models_table} (
            id SERIAL PRIMARY KEY,                  -- Auto-incrementing ID
            model_name TEXT UNIQUE NOT NULL         -- Unique model name
        );
        """
        await connection.execute(create_statement)
        # Insert a new model into the 'models' table
        for model_name in ["gpt4-8k","gpt-4o-mini","gpt-4o","gpt-35-turbo","gpt-4o-2","gpt-4o-3"]:
            insert_statement = f"""
            INSERT INTO {models_table} (model_name)
            VALUES ($1)
            ON CONFLICT (model_name) DO NOTHING
            """
            await connection.execute(insert_statement, model_name)

        log.info("Models inserted successfully or already exists.")
    except asyncpg.PostgresError as e:
        log.error(f"Error creating models table or inserting models: {e}")
    finally:
        if connection:
            await connection.close()




async def create_login_credential_table_if_not_exists():
    """
    Connects to a PostgreSQL database and creates the 'login_credential' table
    if it doesn't already exist.
    """
    conn = None
    try:
        # Connect to the PostgreSQL database
        conn = await asyncpg.connect(
            host=POSTGRESQL_HOST,
            database='login',
            user=POSTGRESQL_USER,
            password=POSTGRESQL_PASSWORD
        )

        # SQL statement to create the login_credential table
        create_table_sql = """
        CREATE TABLE IF NOT EXISTS login_credential (
            mail_id TEXT PRIMARY KEY,
            user_name TEXT NOT NULL,
            password TEXT NOT NULL,
            role TEXT NOT NULL DEFAULT 'user'
        );
        """

        # Execute the CREATE TABLE statement
        await conn.execute(create_table_sql)
        log.info("Table 'login_credential' created successfully (or already exists).")

    except asyncpg.PostgresError as e:
        log.error(f"Error creating table: {e}")
    finally:
        # Close the database connection
        if conn:
            await conn.close()



from pathlib import Path
async def get_tool_data(agent_data, export_path, tools=[], tool_service: ToolService = None):
    if not tool_service:
        raise ValueError("ToolService instance is required to fetch tool data.")
    import json
    if not tools:
        tools_id_str = agent_data.get("tools_id")
        tool_ids = tools_id_str
    else:
        tool_ids = tools
    tools_data = {}  
    for tool_id in tool_ids:
        tool_data = await tool_service.get_tool(tool_id=tool_id)
        if tool_data:
            tool_dict= tool_data[0]
            processed_tool_dict = {}
            for key, value in tool_dict.items():
                if key not in ["created_on", "updated_on", "tags","db_connection_name","is_public","status","comments","approved_at","approved_by"]:
                    if isinstance(value, datetime):
                        processed_tool_dict[key] = value.isoformat()
                    else:
                        processed_tool_dict[key] = value
            name=tool_dict["tool_name"]
            raw_code=tool_dict["code_snippet"]
            final_code=format_python_code_string(raw_code)
            file_path=os.path.join(export_path,f'Agent_Backend/tools_codes/{name}.py')         
            try:
                path_obj = Path(file_path)
                parent_directory = path_obj.parent
                parent_directory.mkdir(parents=True, exist_ok=True)
                with open(path_obj, 'w', encoding='utf-8') as f:
                    f.write(final_code)
            except Exception as e:
                pass
            processed_tool_dict["code_snippet"]=f'tools_codes/{name}.py'
            # del processed_tool_dict["code_snippet"]
            tools_data[tool_id] = processed_tool_dict
        else:
            tools_data[tool_id] = None
    tool_data_file_path=os.path.join(export_path, 'Agent_Backend/tools_config.py')
    tools_data_json_str = json.dumps(tools_data, indent=4)
    with open(tool_data_file_path, 'w') as f:
            f.write('tools_data = ')
            f.write(tools_data_json_str)

def format_python_code_string(code_string: str) -> str:
    import black
    try:
        mode = black.Mode(line_length=88)
        formatted_code = black.format_str(code_string, mode=mode)      
        return formatted_code
    except black.InvalidInput as e:
        raise e
    except Exception as e:
        raise e

async def create_db_connections_table_if_not_exists(table_name="db_connections_table"):
    """
    Creates the db_connections_table in PostgreSQL if it does not exist.

    Args:
        table_name (str): Name of the table to create. Defaults to 'db_connections_table'.
    """
    try:
        # Connect asynchronously
        connection = await asyncpg.connect(
            host=POSTGRESQL_HOST,
            database=DATABASE,
            user=POSTGRESQL_USER,
            password=POSTGRESQL_PASSWORD
        )

        # SQL to create the table with appropriate data types
        create_statement = f"""
        CREATE TABLE IF NOT EXISTS {table_name} (
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
        await connection.execute(create_statement)

        print(f"Table '{table_name}' created successfully or already exists.")

    except Exception as e:
        print(f"Error creating table '{table_name}': {e}")

    finally:
        # Close the connection
        await connection.close()


import uuid
from datetime import datetime, timezone

async def insert_into_db_connections_table(connection_data, table_name="db_connections_table"):
    """
    Inserts data into the db_connections_table in PostgreSQL asynchronously.

    Args:
        connection_data (dict): A dictionary containing the connection details to insert.
        table_name (str): Name of the PostgreSQL table to insert data into. Defaults to 'db_connections_table'.

    Returns:
        dict: Status of the operation, including success message or error details.
    """
    # Generate connection_id if not provided
    print("heyyyyyyy")
    if not connection_data.get("connection_id"):
        connection_data["connection_id"] = str(uuid.uuid4())

    try:
        # Connect asynchronously
        connection = await asyncpg.connect(
            host=POSTGRESQL_HOST,
            database=DATABASE,
            user=POSTGRESQL_USER,
            password=POSTGRESQL_PASSWORD
        )

        # Build SQL INSERT statement
        insert_statement = f"""
        INSERT INTO {table_name} (
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
            "message": f"Integrity error inserting data into '{table_name}': {e}",
            "connection_id": "",
            "connection_name": connection_data.get("connection_name", ""),
            "database_type": connection_data.get("database_type", ""),
            "is_created": False
        }

    except Exception as e:
        return {
            "message": f"Error inserting data into '{table_name}': {e}",
            "connection_id": "",
            "connection_name": connection_data.get("connection_name", ""),
            "database_type": connection_data.get("database_type", ""),
            "is_created": False
        }

    finally:
        # Ensure the connection is closed properly
        await connection.close()
        

def generate_connection_code(connection_config):
    """
    Generates Python code snippet for get_connection() helper based on connection config.
    Supports postgres, sqlite, mongodb, mysql, etc.
    """
    if not connection_config:
        return "# No database connection selected. get_connection() unavailable."

    db_type = connection_config.get("connection_database_type")
    if db_type == "postgresql":
        return f"""import psycopg2
from psycopg2.extras import RealDictCursor

def get_connection():
    return psycopg2.connect(
        dbname="{connection_config.get('connection_database_name')}",
        user="{connection_config.get('connection_username')}",
        password="{connection_config.get('connection_password')}",
        host="{connection_config.get('connection_host')}",
        port="{connection_config.get('connection_port')}"
    )
"""

    elif db_type == "sqlite":
        return f"""import sqlite3

def get_connection():
    return sqlite3.connect("{connection_config.get('connection_database_name')}")
"""

    elif db_type == "mongodb":
        return f"""from pymongo import MongoClient

def get_connection():
    client = MongoClient("{connection_config.get('connection_database_name')}")
    return client
"""

    elif db_type == "mysql":
        return f"""import mysql.connector

def get_connection():
    return mysql.connector.connect(
        host="{connection_config.get('connection_host')}",
        user="{connection_config.get('connection_username')}",
        password="{connection_config.get('connection_password')}",
        database="{connection_config.get('connection_database_name')}",
        port={connection_config.get('connection_port', 3306)}
    )
"""

    else:
        return "# Unsupported database type. get_connection() unavailable."


