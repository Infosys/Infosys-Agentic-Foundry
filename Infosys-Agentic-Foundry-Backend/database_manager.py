# © 2024-25 Infosys Limited, Bangalore, India. All Rights Reserved.
import os
import re
import json
from datetime import datetime, timezone
import uuid
import pandas as pd
from langgraph.prebuilt import create_react_agent
from src.models.model import load_model
from src.tools.tool_docstring_generator import generate_docstring_tool_onboarding
from src.agent_templates.react_agent_onboarding import react_system_prompt_gen_func
from src.agent_templates.multi_agent_onboarding import planner_executor_critic_builder
from src.agent_templates.meta_agent_onboarding import meta_agent_system_prompt_gen_func
from src.agent_templates.meta_agent_with_planner_onboarding import onboard_meta_agent_with_planner
from sqlalchemy import create_engine
import asyncio
import asyncpg
from telemetry_wrapper import logger as log, update_session_context
from dotenv import load_dotenv
from urllib.parse import urlparse, urlunparse
from src.agent_templates.planner_executor_onboarding import planner_executor_builder
from typing import List, Optional
from src.agent_templates.react_critic_agent_onboarding import executor_critic_builder


load_dotenv()
# Connection string format:

Postgre_string = os.getenv("DATABASE_URL")

POSTGRESQL_HOST = os.getenv("POSTGRESQL_HOST", "")
POSTGRESQL_USER = os.getenv("POSTGRESQL_USER", "")
POSTGRESQL_PASSWORD = os.getenv("POSTGRESQL_PASSWORD", "")
DATABASE = os.getenv("DATABASE", "")
DATABASE_URL = os.getenv("POSTGRESQL_DATABASE_URL", "")


REQUIRED_DATABASES = ["feedback_learning", "telemetry_logs", "agentic_workflow_as_service_database", "login", "logs", "arize_traces","recycle"]




def get_postgres_url():
    """
    Adjust the DATABASE_URL to always connect to 'postgres' database,
    so we can create/check other databases.
    """
    url = urlparse(Postgre_string)
    # Replace path with '/postgres'
    new_url = url._replace(path="/postgres")
    return urlunparse(new_url)


async def check_and_create_databases():
    """
    Connects to 'postgres' database and creates any missing required databases.
    """
    conn = await asyncpg.connect(get_postgres_url())
    try:
        for db_name in REQUIRED_DATABASES:
            exists = await conn.fetchval(
                "SELECT 1 FROM pg_database WHERE datname = $1", db_name
            )
            if not exists:
                log.info(f"Database '{db_name}' not found. Creating...")
                await conn.execute(f'CREATE DATABASE "{db_name}"')
            else:
                log.info(f"Database '{db_name}' already exists.")
    finally:
        await conn.close()



# Global variable to store the connection pool
connection_pool = None

async def create_connection_pool():
    global connection_pool
    try:
        connection_pool = await asyncpg.create_pool(
            dsn=DATABASE_URL,
            min_size=10,
            max_size=20
        )
        log.info("Connection pool created successfully!")
    except Exception as e:
        log.info(f"Failed to create connection pool: {e}")

async def return_connection(connection):
    await connection.close()  # Optional, asyncpg manages the pool lifecycle internally



async def delete_table(table_name: str):
    """
    Deletes a PostgreSQL table asynchronously.

    Args:
        table_name (str): Name of the table to delete.
    """
    try:
        # Create a connection to the PostgreSQL database
        connection = await asyncpg.connect(
            host=POSTGRESQL_HOST,
            database=DATABASE,
            user=POSTGRESQL_USER,
            password=POSTGRESQL_PASSWORD
        )

        # Build and execute the DROP TABLE statement
        drop_statement = f"DROP TABLE IF EXISTS {table_name}"
        await connection.execute(drop_statement)
        log.info(f"Table '{table_name}' deleted successfully.")

    except asyncpg.PostgresError as e:
        log.error(f"Error deleting table '{table_name}': {e}")

    finally:
        await connection.close()



async def truncate_table(table_name: str):
    """
    Truncates a PostgreSQL table asynchronously, removing all data while keeping the table structure.

    Args:
        table_name (str): Name of the table to truncate.
    """
    try:
        # Create a connection to the PostgreSQL database
        connection = await asyncpg.connect(
            host=POSTGRESQL_HOST,
            database=DATABASE,
            user=POSTGRESQL_USER,
            password=POSTGRESQL_PASSWORD
        )

        # Build and execute the TRUNCATE TABLE statement
        truncate_statement = f"TRUNCATE TABLE {table_name}"
        await connection.execute(truncate_statement)
        log.info(f"Table '{table_name}' truncated successfully.")

    except Exception as e:
        log.error(f"Error truncating table '{table_name}': {e}")

    finally:
        # Close the connection
        await connection.close()




async def create_tool_agent_mapping_table_if_not_exists(table_name="tool_agent_mapping_table"):
    try:
        connection = await asyncpg.connect(
            host=POSTGRESQL_HOST,
            database=DATABASE,
            user=POSTGRESQL_USER,
            password=POSTGRESQL_PASSWORD
        )

        create_statement = f"""
        CREATE TABLE IF NOT EXISTS {table_name} (
            tool_id TEXT,
            agentic_application_id TEXT,
            tool_created_by TEXT,
            agentic_app_created_by TEXT,
            FOREIGN KEY(tool_id) REFERENCES tool_table(tool_id) ON DELETE RESTRICT,
            FOREIGN KEY(agentic_application_id) REFERENCES agent_table(agentic_application_id) ON DELETE CASCADE
        )
        """

        await connection.execute(create_statement)
        log.info(f"Table '{table_name}' created successfully or already exists.")

    except Exception as e:
        log.error(f"Error creating table '{table_name}': {e}")
    finally:
        await connection.close()




async def insert_data_tool_agent_mapping(
    table_name="tool_agent_mapping_table",
    tool_id=None, agentic_application_id=None, tool_created_by=None, agentic_app_created_by=None
):
    """
    Insert data into the PostgreSQL tool-agent mapping table asynchronously.

    Args:
        table_name (str): Name of the table to insert data into.
        tool_id (str): Tool ID.
        agentic_application_id (str): Agentic application ID.
        tool_created_by (str): Who created the tool.
        agentic_app_created_by (str): Who created the agentic app.
    """
    try:
        # Create a connection to the PostgreSQL database
        connection = await asyncpg.connect(
            host=POSTGRESQL_HOST,
            database=DATABASE,
            user=POSTGRESQL_USER,
            password=POSTGRESQL_PASSWORD
        )

        # Check if the record already exists
        select_statement = f"""
            SELECT 1 FROM {table_name}
            WHERE tool_id = $1 AND agentic_application_id = $2
        """
        result = await connection.fetch(select_statement, tool_id, agentic_application_id)

        # Insert only if the record doesn't exist
        if not result:
            insert_statement = f"""
                INSERT INTO {table_name} (tool_id, agentic_application_id, tool_created_by, agentic_app_created_by)
                VALUES ($1, $2, $3, $4)
            """
            await connection.execute(insert_statement, tool_id, agentic_application_id, tool_created_by, agentic_app_created_by)
            log.info(f"Data inserted into '{table_name}' successfully.")

    except Exception as e:
        log.error(f"Error inserting data into '{table_name}': {e}")

    finally:
        # Close the connection
        await connection.close()



async def get_data_tool_agent_mapping(
    table_name="tool_agent_mapping_table",
    tool_id=None,
    agentic_application_id=None,
    tool_created_by=None,
    agentic_app_created_by=None
):
    """
    Retrieves data from the tool-agent mapping table in PostgreSQL asynchronously.

    Args:
        table_name (str): The name of the table.
        tool_id (str, optional): The ID of the tool to filter by. Defaults to None.
        agentic_application_id (str, optional): The ID of the agentic application to filter by. Defaults to None.
        tool_created_by (str, optional): The creator of the tool to filter by. Defaults to None.
        agentic_app_created_by (str, optional): The creator of the agentic application to filter by. Defaults to None.

    Returns:
        list: A list of dictionaries containing the retrieved data.
    """
    try:
        # Connect to the PostgreSQL database asynchronously
        connection = await asyncpg.connect(
            host=POSTGRESQL_HOST,
            database=DATABASE,
            user=POSTGRESQL_USER,
            password=POSTGRESQL_PASSWORD
        )

        # Build the SELECT query
        select_statement = f"SELECT * FROM {table_name}"
        where_clause = []
        values = []

        # Dynamically build the WHERE clause with correct param positions
        # Mapping fields to values
        filters = {
            "tool_id": tool_id,
            "agentic_application_id": agentic_application_id,
            "tool_created_by": tool_created_by,
            "agentic_app_created_by": agentic_app_created_by
        }

        # Build WHERE clause with parameter placeholders
        for idx, (field, value) in enumerate((f for f in filters.items() if f[1] is not None), start=1):
            where_clause.append(f"{field} = ${idx}")
            values.append(value)

        if where_clause:
            select_statement += " WHERE " + " AND ".join(where_clause)

        # Execute the query and fetch results asynchronously
        rows = await connection.fetch(select_statement, *values)

        # Convert rows to list of dictionaries
        data = [dict(row) for row in rows]
        log.info(f"Data retrieved from '{table_name}' successfully.")

        return data

    except Exception as e:
        log.error(f"Error retrieving data from '{table_name}': {e}")
        return []  # Return an empty list in case of an error

    finally:
        await connection.close()




async def update_data_tool_agent_mapping(
    table_name="tool_agent_mapping_table",
    tool_id=None, agentic_application_id=None,
    tool_created_by=None, agentic_app_created_by=None,
    new_tool_id=None, new_agentic_application_id=None,
    new_tool_created_by=None, new_agentic_app_created_by=None
):
    try:
        # Connect to the PostgreSQL database asynchronously
        connection = await asyncpg.connect(
            host=POSTGRESQL_HOST,
            database=DATABASE,
            user=POSTGRESQL_USER,
            password=POSTGRESQL_PASSWORD
        )

        # Build SET clause
        set_clause = []
        set_values = []

        update_fields = {
            "tool_id": new_tool_id,
            "agentic_application_id": new_agentic_application_id,
            "tool_created_by": new_tool_created_by,
            "agentic_app_created_by": new_agentic_app_created_by,
        }

        for field, value in update_fields.items():
            if value is not None:
                set_clause.append(f"{field} = ${len(set_values) + 1}")
                set_values.append(value)

        if not set_clause:
            return

        # Build the WHERE clause
        where_clause = []
        where_values = []

        filter_fields = {
            "tool_id": tool_id,
            "agentic_application_id": agentic_application_id,
            "tool_created_by": tool_created_by,
            "agentic_app_created_by": agentic_app_created_by,
        }

        for field, value in filter_fields.items():
            if value is not None:
                param_index = len(set_values) + len(where_values) + 1
                where_clause.append(f"{field} = ${param_index}")
                where_values.append(value)

        # Combine the full query
        update_query = f"UPDATE {table_name} SET " + ", ".join(set_clause)
        if where_clause:
            update_query += " WHERE " + " AND ".join(where_clause)

        # Execute the query
        await connection.execute(update_query, *(set_values + where_values))
        log.info(f"Data in '{table_name}' updated successfully.")

    except Exception as e:
        log.error(f"Error updating data in '{table_name}': {e}")

    finally:
        await connection.close()



async def delete_data_tool_agent_mapping(
    table_name="tool_agent_mapping_table",
    tool_id=None, agentic_application_id=None,
    tool_created_by=None, agentic_app_created_by=None
):
    """
    Asynchronously deletes data from the tool-agent mapping table in PostgreSQL.

    Args:
        table_name (str): The name of the table.
        tool_id (str, optional): Filter by tool ID.
        agentic_application_id (str, optional): Filter by agentic application ID.
        tool_created_by (str, optional): Filter by tool creator.
        agentic_app_created_by (str, optional): Filter by agentic app creator.
    """
    try:
        # Connect asynchronously
        connection = await asyncpg.connect(
            host=POSTGRESQL_HOST,
            database=DATABASE,
            user=POSTGRESQL_USER,
            password=POSTGRESQL_PASSWORD
        )

        # Build the DELETE statement dynamically
        delete_statement = f"DELETE FROM {table_name}"
        where_clause = []
        values = []

        # Mapping fields to values
        filters = {
            "tool_id": tool_id,
            "agentic_application_id": agentic_application_id,
            "tool_created_by": tool_created_by,
            "agentic_app_created_by": agentic_app_created_by
        }

        # Build WHERE clause with parameter placeholders
        for idx, (field, value) in enumerate((f for f in filters.items() if f[1] is not None), start=1):
            where_clause.append(f"{field} = ${idx}")
            values.append(value)

        if where_clause:
            delete_statement += " WHERE " + " AND ".join(where_clause)
            await connection.execute(delete_statement, *values)
            log.info(f"Data deleted from '{table_name}' successfully.")
        else:
            log.info("No criteria specified. No rows deleted.")

    except Exception as e:
        log.error(f"Error deleting data from '{table_name}': {e}")

    finally:
        await connection.close()




async def create_tool_table_if_not_exists(table_name="tool_table"):
    """
    Creates the tool_table in PostgreSQL if it does not exist.

    Args:
        table_name (str): Name of the table to create. Defaults to 'tool_table'.
    """
    try:
        # Connect asynchronously
        connection = await asyncpg.connect(
            host=POSTGRESQL_HOST,
            database=DATABASE,
            user=POSTGRESQL_USER,
            password=POSTGRESQL_PASSWORD
        )

        # SQL to create the table
        create_statement = f"""
        CREATE TABLE IF NOT EXISTS {table_name} (
            tool_id TEXT PRIMARY KEY,                     -- Unique identifier for each tool
            tool_name TEXT UNIQUE,                       -- Unique name for the tool
            tool_description TEXT,                       -- Description of the tool
            code_snippet TEXT,                           -- Optional code snippet associated with the tool
            model_name TEXT,                             -- Name of the model used
            created_by TEXT,                             -- User who created the entry
            created_on TIMESTAMP DEFAULT CURRENT_TIMESTAMP, -- Timestamp for when the record is created
            updated_on TIMESTAMP DEFAULT CURRENT_TIMESTAMP -- Timestamp for when the record is updated
        )
        """

        # Execute the SQL statement
        await connection.execute(create_statement)
        log.info(f"Table '{table_name}' created successfully or already exists.")


    except Exception as e:
        log.error(f"Error creating table '{table_name}': {e}")

    finally:
        # Close the connection
        await connection.close()

async def check_recycle_tool_name_if_exist(tool_name):
    """
    Checks if a tool name exists in the recycle bin table.

    Args:
        tool_name (str): The name of the tool to check.
        table_name (str): Name of the PostgreSQL table to check. Defaults to 'tool_table'.

    Returns:
        bool: True if the tool name exists, False otherwise.
    """
    try:
        # Connect asynchronously
        connection_recycle = await asyncpg.connect(
            host=POSTGRESQL_HOST,
            database='recycle',
            user=POSTGRESQL_USER,
            password=POSTGRESQL_PASSWORD
        )

        # SQL to check if the tool name exists
        query = f"SELECT EXISTS(SELECT 1 FROM recycle_tool WHERE tool_name = $1)"
        exists = await connection_recycle.fetchval(query, tool_name)

        return exists

    except Exception as e:
        log.error(f"Error checking tool name '{tool_name}' in 'recycle_tool': {e}")
        return False

    finally:
        await connection_recycle.close()

async def insert_into_tool_table(tool_data, table_name="tool_table"):
    """
    Inserts data into the tool table in PostgreSQL asynchronously.

    Args:
        tool_data (dict): A dictionary containing the tool data to insert.
        table_name (str): Name of the PostgreSQL table to insert data into. Defaults to 'tool_table'.

    Returns:
        dict: Status of the operation, including success message or error details.
    """
    # Generate tool_id if not provided
    if await check_recycle_tool_name_if_exist(tool_data.get("tool_name", "")):
        log.info(f"Tool Insertion Status: Integrity error inserting data into '{table_name}': This Tool name already exist in recycle bin.")
        return {
            "message": f"Integrity error inserting data into '{table_name}': This Tool name already exist in recycle bin.",
            "tool_id": "",
            "tool_name": f"{tool_data.get('tool_name', '')}",
            "model_name": f"{tool_data.get('model_name', '')}",
            "created_by": f"{tool_data.get('created_by', '')}",
            "is_created": False
        }
    if not tool_data.get("tool_id"):
        tool_data["tool_id"] = str(uuid.uuid4())
        update_session_context(tool_id=tool_data.get("tool_id", None))
        log.info(f"Generated new tool_id: {tool_data['tool_id']}") 

    # Generate Docstring
    llm = load_model(model_name=tool_data["model_name"])
    updated_code_snippet = await generate_docstring_tool_onboarding(
        llm=llm,
        tool_code_str=tool_data["code_snippet"],
        tool_description=tool_data["tool_description"]
    )
    if "Tool Onboarding Failed" in updated_code_snippet:
        status = {
            "message": f"{updated_code_snippet}",
            "tool_id": "",
            "tool_name": f"{tool_data.get('tool_name', '')}",
            "model_name": f"{tool_data.get('model_name', '')}",
            "created_by": f"{tool_data.get('created_by', '')}",
            "is_created": False
        }
        log.error(f"Tool Onboarding Failed: {updated_code_snippet}")
        return status
    tool_data["code_snippet"] = updated_code_snippet

    try:
        # Connect asynchronously
        connection = await asyncpg.connect(
            host=POSTGRESQL_HOST,
            database=DATABASE,
            user=POSTGRESQL_USER,
            password=POSTGRESQL_PASSWORD
        )

        # Get current timestamp for created_on and updated_on
        now = datetime.now(timezone.utc).replace(tzinfo=None)

        # Update tool_data with created_on and updated_on timestamps
        # tool_data['created_on'] = now.isoformat()
        # tool_data['updated_on'] = now.isoformat()
        tool_data['updated_on'] = now
        tool_data['created_on'] = now

        # Build SQL INSERT statement
        insert_statement = f"""
        INSERT INTO {table_name} (
            tool_id,
            tool_name,
            tool_description,
            code_snippet,
            model_name,
            created_by,
            created_on,
            updated_on
        ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
        """

        # Extract values from tool_data for insertion
        values = (
            tool_data.get("tool_id"),
            tool_data.get("tool_name"),
            tool_data.get("tool_description"),
            tool_data.get("code_snippet"),
            tool_data.get("model_name"),
            tool_data.get("created_by"),
            tool_data["created_on"],
            tool_data["updated_on"]
        )

        # Execute the insert statement
        await connection.execute(insert_statement, *values)

        # Insert tags into the tag-tool mapping table
        tags_status = await insert_into_tag_tool_mapping(
            tag_ids=tool_data['tag_ids'], tool_id=tool_data['tool_id']
        )

        # Return success status
        log.info(f"Tool Insertion Status: Successfully onboarded tool with tool_id: {tool_data.get('tool_id', '')}")
        return {
            "message": f"Successfully onboarded tool with tool_id: {tool_data.get('tool_id', '')}",
            "tool_id": f"{tool_data.get('tool_id', '')}",
            "tool_name": f"{tool_data.get('tool_name', '')}",
            "model_name": f"{tool_data.get('model_name', '')}",
            "tags_status": tags_status,
            "created_by": f"{tool_data.get('created_by', '')}",
            "is_created": True
        }

    except asyncpg.UniqueViolationError as e:
        # Handle constraints like primary key or unique violations
        log.info(f"Tool Insertion Status: Integrity error inserting data into '{table_name}': {e}")
        return {
            "message": f"Integrity error inserting data into '{table_name}': {e}",
            "tool_id": "",
            "tool_name": f"{tool_data.get('tool_name', '')}",
            "model_name": f"{tool_data.get('model_name', '')}",
            "created_by": f"{tool_data.get('created_by', '')}",
            "is_created": False
        }

    except Exception as e:
        # Handle general database errors
        log.info(f"Tool Insertion Status: Error inserting data into '{table_name}' table: {e}")
        return {
            "message": f"Error inserting data into '{table_name}' table: {e}",
            "tool_id": "",
            "tool_name": f"{tool_data.get('tool_name', '')}",
            "model_name": f"{tool_data.get('model_name', '')}",
            "created_by": f"{tool_data.get('created_by', '')}",
            "is_created": False
        }

    finally:
        # Ensure the connection is properly closed
        await connection.close()



async def get_tools(tool_table_name="tool_table", tag_table_name="tags_table", mapping_table_name="tag_tool_mapping_table"):
    """
    Retrieves tools from the tool table in PostgreSQL asynchronously.

    Args:
        tool_table_name (str): The name of the tool table. Defaults to 'tool_table'.

    Returns:
        list: A list of tools from the tool table, represented as dictionaries.
    """
    try:
        # Connect asynchronously to the database
        connection = await asyncpg.connect(
            host=POSTGRESQL_HOST,
            database=DATABASE,
            user=POSTGRESQL_USER,
            password=POSTGRESQL_PASSWORD
        )

        # Build and execute the SELECT query asynchronously
        query = f"""
        SELECT
            t.tool_id,
            t.tool_name,
            t.tool_description,
            t.code_snippet,
            t.model_name,
            t.created_by,
            t.created_on,
            t.updated_on,
            COALESCE(
                JSON_AGG(
                    JSON_BUILD_OBJECT(
                        'tag_id', tg.tag_id,
                        'tag_name', tg.tag_name,
                        'created_by', tg.created_by
                    )
                ) FILTER (WHERE tg.tag_id IS NOT NULL),
                '[]'
            ) AS tags
        FROM {tool_table_name} t
        LEFT JOIN {mapping_table_name} m ON t.tool_id = m.tool_id
        LEFT JOIN {tag_table_name} tg ON m.tag_id = tg.tag_id
        GROUP BY t.tool_id
        ORDER BY t.created_on DESC
        """

        rows = await connection.fetch(query)  # Using fetch for multiple rows

        results_as_dicts = []
        for row in rows:
            result = dict(row)
            # Deserialize the tags field from JSON string to a Python list
            result['tags'] = json.loads(result['tags']) if isinstance(result['tags'], str) else result['tags']
            results_as_dicts.append(result)
        log.info(f"Retrieved {len(results_as_dicts)} tools from '{tool_table_name}'.") 

        return results_as_dicts

    except asyncpg.PostgresError as e:
        log.error(f"Error retrieving tools from '{tool_table_name}': {e}")
        return []

    finally:
        # Ensure the connection is properly closed
        await connection.close()




async def get_tools_by_page(tool_table_name="tool_table", name='', limit=20, page=1, tag_table_name="tags_table", mapping_table_name="tag_tool_mapping_table"):
    """
    Retrieves tools from the PostgreSQL database with pagination support (asynchronously).

    Args:
        tool_table_name (str): Name of the tool table.
        name (str, optional): Tool name to filter by. Defaults to '' (no filtering).
        limit (int, optional): Number of results per page. Defaults to 20.
        page (int, optional): Page number for pagination. Defaults to 1.

    Returns:
        dict: A dictionary containing the total count of tools and the paginated tool details.
    """
    try:
        connection = await asyncpg.connect(
            host=POSTGRESQL_HOST,
            database=DATABASE,
            user=POSTGRESQL_USER,
            password=POSTGRESQL_PASSWORD
        )

        # Normalize name for case-insensitive filtering
        name_filter = f"%{name.lower()}%" if name else "%"

        # Get total count of matching tools
        total_query = f"""
            SELECT COUNT(*)
            FROM {tool_table_name}
            WHERE LOWER(tool_name) LIKE $1
        """
        total_result = await connection.fetchval(total_query, name_filter)

        # Calculate offset for pagination
        offset = limit * max(0, page - 1)

        # Query tools for the given page
        page_query = f"""
            SELECT
                t.tool_id,
                t.tool_name,
                t.tool_description,
                t.code_snippet,
                t.model_name,
                t.created_by,
                t.created_on,
                t.updated_on,
                COALESCE(
                    JSON_AGG(
                        JSON_BUILD_OBJECT(
                            'tag_id', tg.tag_id,
                            'tag_name', tg.tag_name,
                            'created_by', tg.created_by
                        )
                    ) FILTER (WHERE tg.tag_id IS NOT NULL),
                    '[]'
                ) AS tags
            FROM {tool_table_name} t
            LEFT JOIN {mapping_table_name} m ON t.tool_id = m.tool_id
            LEFT JOIN {tag_table_name} tg ON m.tag_id = tg.tag_id
            WHERE LOWER(t.tool_name) LIKE $1
            GROUP BY t.tool_id
            ORDER BY t.created_on DESC
            LIMIT $2 OFFSET $3
        """
        rows = await connection.fetch(page_query, name_filter, limit, offset)

        tools = []
        for row in rows:
            tool = dict(row)
            # Deserialize the tags field from JSON string to a Python list
            tool['tags'] = json.loads(tool['tags']) if isinstance(tool['tags'], str) else tool['tags']
            tools.append(tool)
        log.info(f"Retrieved {len(tools)} tools from '{tool_table_name}' for page {page}.")

        return {
            "total_count": total_result,
            "details": tools
        }

    except asyncpg.PostgresError as e:
        log.error(f"Error retrieving tools from '{tool_table_name}': {e}")
        return {"total_count": 0, "details": []}

    finally:
        await connection.close()


async def get_tools_by_id(tool_table_name="tool_table", tool_id=None, tool_name=None, created_by=None):
    """
    Retrieves tools from the PostgreSQL database based on provided parameters asynchronously.

    Args:
        tool_table_name (str): Name of the tool table.
        tool_id (str, optional): Tool ID.
        tool_name (str, optional): Tool name.
        created_by (str, optional): Creator of the tool.

    Returns:
        list: A list of dictionaries representing the retrieved tools, or an empty list on error.
    """
    try:
        connection = await asyncpg.connect(
            host=POSTGRESQL_HOST,
            database=DATABASE,
            user=POSTGRESQL_USER,
            password=POSTGRESQL_PASSWORD
        )

        # Start building the query
        query = f"SELECT * FROM {tool_table_name}"
        where_clauses = []
        values = []

        filters = {
        "tool_id": tool_id,
        "tool_name": tool_name,
        "created_by": created_by
        }

        # Build WHERE clause with parameter placeholders
        for idx, (field, value) in enumerate((f for f in filters.items() if f[1] is not None), start=1):
            where_clauses.append(f"{field} = ${idx}")
            values.append(value)

        # Add WHERE clause if filters exist
        if where_clauses:
            query += " WHERE " + " AND ".join(where_clauses)

        # Execute the query
        rows = await connection.fetch(query, *values)

        # Convert result rows to dictionaries
        tools = [dict(row) for row in rows]

        # Add tags to each tool
        tool_id_to_tags = await get_tool_tags_from_mapping_as_dict()
        for tool in tools:
            tool["tags"] = tool_id_to_tags.get(tool['tool_id'], [])
        log.info(f"Retrieved {len(tools)} tools from '{tool_table_name}' with provided filters.")
        return tools

    except asyncpg.PostgresError as e:
        log.error(f"Error retrieving tools from '{tool_table_name}': {e}")
        return []

    finally:
        await connection.close()




#This function's return value changed compared to previous sync function please check if it is correct
async def update_tool_by_id_util(tool_data, table_name="tool_table", tool_id=None, tool_name=None):
    """
    Asynchronously updates a tool in PostgreSQL based on the provided tool ID or tool name.

    Args:
        tool_data (dict): A dictionary containing the tool data to update.
        table_name (str): Name of the PostgreSQL table to update. Defaults to 'tool_table'.
        tool_id (str, optional): The ID of the tool to update.
        tool_name (str, optional): The name of the tool to update.

    Returns:
        bool: True if the update was successful, False otherwise.
    """
    if not tool_id and not tool_name:
        return False

    try:
        connection = await asyncpg.connect(
            host=POSTGRESQL_HOST,
            database=DATABASE,
            user=POSTGRESQL_USER,
            password=POSTGRESQL_PASSWORD
        )

        # Add updated_on timestamp
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        tool_data["updated_on"] = now

        # Build dynamic SET clause
        set_clauses = []
        values = []

        for key, value in tool_data.items():
            set_clauses.append(f"{key} = ${len(values) + 1}")
            values.append(value)

        # Add WHERE clause
        if tool_id:
            where_clause = f"tool_id = ${len(values) + 1}"
            values.append(tool_id)
        else:
            where_clause = f"tool_name = ${len(values) + 1}"
            values.append(tool_name)

        query = f"""
            UPDATE {table_name}
            SET {', '.join(set_clauses)}
            WHERE {where_clause}
        """

        result = await connection.execute(query, *values)
        log.info(f"Tool with {'tool_id' if tool_id else 'tool_name'} updated successfully in '{table_name}'.")

        # 'UPDATE x' is returned if rows were updated
        return result != "UPDATE 0"  # Checks if any rows were updated

    except asyncpg.PostgresError as e:
        log.error(f"Error updating tool in '{table_name}': {e}")
        return False

    finally:
        await connection.close()



async def update_tool_by_id(model_name,
                             user_email_id="",
                             is_admin=False,
                             table_name="tool_table",
                             tool_id_to_modify=None,
                             tool_name_to_modify=None,
                             tool_description=None,
                             code_snippet=None,
                             created_by=None,
                             updated_tag_id_list=None):
    """
    Updates a tool in the PostgreSQL database based on the provided tool ID or tool name asynchronously.

    Args:
        model_name (str): The name of the model.
        user_email_id (str): The email ID of the user performing the update.
        is_admin (bool): Whether the user is an admin.
        table_name (str): Name of the PostgreSQL table to update. Defaults to 'tool_table'.
        tool_id_to_modify (str, optional): The ID of the tool to update.
        tool_name_to_modify (str, optional): The name of the tool to update.
        tool_description (str, optional): New description for the tool.
        code_snippet (str, optional): New code snippet for the tool.
        created_by (str, optional): New creator for the tool.
        updated_tag_id_list (list, optional): List of updated tag IDs.

    Returns:
        dict: Status of the operation, including success message or error details.
    """
    # Validate if tool ID or tool name is provided for modification
    if not tool_id_to_modify and not tool_name_to_modify:
        log.error("Error: Must provide 'tool_id' or 'tool_name' to update a tool.")
        return {
            "status_message": "Error: Must provide 'tool_id' or 'tool_name' to update a tool.",
            "details": [],
            "is_update": False
        }

    # Database connection configuration
    connection = await asyncpg.connect(
        host=POSTGRESQL_HOST,
        database=DATABASE,
        user=POSTGRESQL_USER,
        password=POSTGRESQL_PASSWORD
    )

    try:
        # Fetch tool data asynchronously
        query = f"SELECT * FROM {table_name} WHERE "
        if tool_id_to_modify:
            query += "tool_id = $1"
            params = (tool_id_to_modify,)
        else:
            query += "tool_name = $1"
            params = (tool_name_to_modify,)

        tool_data = await connection.fetchrow(query, *params)
        if not tool_data:
            log.error(f"Error: Tool not found with ID: {tool_id_to_modify if tool_id_to_modify else tool_name_to_modify}")
            return {
                "status_message": "Error: Tool not found.",
                "details": [],
                "is_update": False
            }

        tool_data = dict(tool_data)

        if not is_admin and tool_data["created_by"] != user_email_id:
            log.error(f"Permission denied: Only the admin or the tool's creator can perform this action for Tool ID: {tool_data['tool_id']}.")
            return {
                "status_message": "Permission denied: Only the admin or the tool's creator can perform this action.",
                "details": [],
                "is_update": False
            }

        if not tool_description and not code_snippet and not created_by and updated_tag_id_list is None:
            log.error("Error: Please specify at least one of the following fields to modify: tool_description, code_snippet, tags.")
            return {
                "status_message": "Error: Please specify at least one of the following fields to modify: tool_description, code_snippet, tags.",
                "details": [],
                "is_update": False
            }

        # Update tags if provided
        tag_status = None
        if updated_tag_id_list is not None:
            if not await clear_tags(tool_id=tool_data['tool_id']):
                log.error("Failed to clear existing tags for the tool.")
                return {
                    "status_message": "Failed to update the tool.",
                    "details": [],
                    "is_update": False
                }
            if not updated_tag_id_list:
                tags = await get_tags_by_id_or_name(tag_name="General")
                updated_tag_id_list = tags["tag_id"]
            tag_status = await insert_into_tag_tool_mapping(tag_ids=updated_tag_id_list, tool_id=tool_data['tool_id'])

        if not tool_description and not code_snippet and not created_by:
            log.info("No modifications made to the tool attributes.")
            return {
                "status_message": "Tags updated successfully",
                "details": [],
                "tag_update_status": tag_status,
                "is_update": True
            }

        # Check if the tool is currently being used by any agentic applications
        df_tool_fil = pd.DataFrame(await get_data_tool_agent_mapping(
            tool_id=tool_data["tool_id"],
            agentic_application_id=None,
            tool_created_by=None,
            agentic_app_created_by=None
        )).drop_duplicates(subset="agentic_application_id")

        # If tool is being used by any applications, return details and prevent update
        if len(df_tool_fil) > 0:
            async def get_agent_name(app_id):
                result = await get_agents_by_id(agentic_application_id=app_id, agentic_application_type="")
                if result:
                    return result[0]["agentic_application_name"]
                return None  # In case no result is found

            # Create a list of tasks to run concurrently
            tasks = [get_agent_name(app_id) for app_id in df_tool_fil["agentic_application_id"]]

            # Run all tasks concurrently
            agent_names = await asyncio.gather(*tasks)

            # Add the agent names to the DataFrame
            df_tool_fil["agentic_application_name"] = agent_names

        if len(df_tool_fil) == 0:
            tool_update_eligibility = True
            agentic_application_id_list = []
        else:
            app_using_tool = len(df_tool_fil)
            info_display = df_tool_fil[[ 'agentic_application_id', 'agentic_application_name', 'agentic_app_created_by']].to_dict(orient="records")
            tool_update_eligibility = False
            response = {
                "status_message": f"The tool you are trying to update is being referenced by {app_using_tool} agentic applications.",
                "details": info_display,
                "is_update": False
            }
            log.error(f"Tool update failed: Tool is being used by {app_using_tool} agentic applications.")
            return response

        # Update tool attributes if modification fields are provided
        if tool_description:
            tool_data["tool_description"] = tool_description
        if code_snippet:
            tool_data["code_snippet"] = code_snippet
        if created_by:
            tool_data["created_by"] = created_by

        # Generate Docstring
        tool_data["model_name"] = model_name
        llm = load_model(model_name=model_name)
        updated_code_snippet = await generate_docstring_tool_onboarding(
            llm=llm,
            tool_code_str=tool_data["code_snippet"],
            tool_description=tool_data["tool_description"]
        )
        if "Tool Onboarding Failed" in updated_code_snippet:
            log.error(f"Tool Update Failed: {updated_code_snippet}")
            return {
                "status_message": f"{updated_code_snippet.replace('Tool Onboarding Failed', 'Tool Update Failed')}",
                "details": [],
                "is_update": False
            }
            
        tool_data["code_snippet"] = updated_code_snippet

        # Update the tool in the database
        success = await update_tool_by_id_util(
            tool_data, table_name, tool_id=tool_id_to_modify, tool_name=tool_name_to_modify)
        if success:
            status = {
                "status_message": "Successfully updated the tool.",
                "details": [],
                "is_update": True
            }
        else:
            status = {
                "status_message": "Failed to update the tool.",
                "details": [],
                "is_update": False
            }

        if tag_status:
            status['tag_update_status'] = tag_status
        log.info(f"Tool update status: {status['status_message']}")
        return status

    except asyncpg.PostgresError as e:
        log.error(f"Error updating tool: {e}")
        return {
            "status_message": "An error occurred while updating the tool.",
            "details": [],
            "is_update": False
        }

    finally:
        await connection.close()




async def delete_tools_by_id(user_email_id,
                              is_admin=False,
                              tool_table_name="tool_table",
                              tool_id=None,
                              tool_name=None):
    """
    Deletes a tool from the PostgreSQL database based on the provided tool ID or tool name asynchronously.

    Args:
        user_email_id (str): The email ID of the user performing the deletion.
        is_admin (bool): Whether the user is an admin.
        tool_table_name (str): Name of the PostgreSQL table containing tools.
        tool_id (str, optional): The ID of the tool to delete.
        tool_name (str, optional): The name of the tool to delete.

    Returns:
        dict: Status of the operation, including success message or error details.
    """
    if not tool_id and not tool_name:
        log.error("Error: Must provide 'tool_id' or 'tool_name' to delete a tool.")
        return {
            "status_message": "Error: Must provide 'tool_id' or 'tool_name' to delete a tool.",
            "details": [],
            "is_delete": False
        }

    connection = await asyncpg.connect(
        host=POSTGRESQL_HOST,
        database=DATABASE,
        user=POSTGRESQL_USER,
        password=POSTGRESQL_PASSWORD
    )

    connection_recycle = await asyncpg.connect(
        host=POSTGRESQL_HOST,
        database="recycle",
        user=POSTGRESQL_USER,
        password=POSTGRESQL_PASSWORD
    )

    try:
        # Fetch tool details asynchronously
        query = f"SELECT * FROM {tool_table_name} WHERE "
        if tool_id:
            query += "tool_id = $1"
            params = (tool_id,)
        else:
            query += "tool_name = $1"
            params = (tool_name,)

        tool = await connection.fetchrow(query, *params)
        if not tool:
            log.error(f"No Tool available with ID: {tool_id if tool_id else tool_name}")
            return {
                "status_message": f"No Tool available with ID: {tool_id if tool_id else tool_name}",
                "details": [],
                "is_delete": False
            }

        tool_data = dict(tool)

        #insert the tool in recycle-bin DB
        recycle_query = f"""
            INSERT INTO recycle_tool (
                tool_id,
                tool_name,
                tool_description,
                code_snippet,
                model_name,
                created_by,
                created_on,
                updated_on
            ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
        """
        recycle_values = (
            tool_data.get("tool_id"),
            tool_data.get("tool_name"),
            tool_data.get("tool_description"),
            tool_data.get("code_snippet"),
            tool_data.get("model_name"),
            tool_data.get("created_by"),
            tool_data["created_on"],
            tool_data["updated_on"]
        )


        if not is_admin and tool_data["created_by"] != user_email_id:
            log.error(f"You do not have permission to delete Tool with Tool ID: {tool_data['tool_id']}. Only the admin or the tool's creator can perform this action.")
            return {
                "status_message": f"You do not have permission to delete Tool with Tool ID: {tool_data['tool_id']}. Only the admin or the tool's creator can perform this action.",
                "details": [],
                "is_delete": False
            }

        # Check for agentic application dependencies
        df_tool_fil = pd.DataFrame(await get_data_tool_agent_mapping(
            tool_id=tool_data["tool_id"],
            agentic_application_id=None,
            tool_created_by=None,
            agentic_app_created_by=None
        )).drop_duplicates(subset="agentic_application_id")

        if len(df_tool_fil) > 0:
            async def get_agent_name(app_id):
                result = await get_agents_by_id(agentic_application_id=app_id, agentic_application_type="")
                if result:
                    return result[0]["agentic_application_name"]
                return None  # In case no result is found

            # Create a list of tasks to run concurrently
            tasks = [get_agent_name(app_id) for app_id in df_tool_fil["agentic_application_id"]]

            # Run all tasks concurrently
            agent_names = await asyncio.gather(*tasks)

            # Add the agent names to the DataFrame
            df_tool_fil["agentic_application_name"] = agent_names

            app_using_tool = len(df_tool_fil)
            info_display = df_tool_fil[[ 'agentic_application_id', 'agentic_application_name', 'agentic_app_created_by']].to_dict(orient="records")
            log.error(f"Tool deletion failed: Tool is being used by {app_using_tool} agentic applications.")
            return {
                "status_message": f"The tool you are trying to delete is being referenced by {app_using_tool} agentic application(s).",
                "details": info_display,
                "is_delete": False
            }

        # Delete the tool
        delete_query = f"DELETE FROM {tool_table_name} WHERE tool_id = $1"
        await connection.execute(delete_query, tool_data["tool_id"])
        await connection_recycle.execute(recycle_query, *recycle_values)

        # Clean up associated tool-agent mappings
        await delete_data_tool_agent_mapping(tool_id=tool_data["tool_id"])
        await clear_tags(tool_id=tool_data['tool_id'])

        log.info(f"Successfully deleted tool with ID: {tool_data['tool_id']}")
        return {
            "status_message": f"Successfully Deleted Record for Tool with Tool ID: {tool_data['tool_id']}",
            "details": [],
            "is_delete": True
        }

    except asyncpg.PostgresError as e:
        log.error(f"Error deleting tool: {e}")
        return {
            "status_message": f"An error occurred while deleting the tool: {e}",
            "details": [],
            "is_delete": False
        }

    finally:
        await connection_recycle.close()
        await connection.close()



# Agent Table Management
async def create_agent_table_if_not_exists(table_name="agent_table"):
    """
    Creates the agent_table in PostgreSQL if it does not exist.

    Args:
        table_name (str): Name of the table to create. Defaults to 'agent_table'.
    """
    connection = await asyncpg.connect(
        host=POSTGRESQL_HOST,
        database=DATABASE,
        user=POSTGRESQL_USER,
        password=POSTGRESQL_PASSWORD
    )

    try:

        # Create the table if it doesn't already exist
        create_statement = f"""
        CREATE TABLE IF NOT EXISTS {table_name} (
            agentic_application_id TEXT PRIMARY KEY,                     -- Unique identifier for each agentic application
            agentic_application_name TEXT UNIQUE,                       -- Unique name for the agentic application
            agentic_application_description TEXT,                       -- Description of the agentic application
            agentic_application_workflow_description TEXT,              -- Workflow description of the agentic application
            agentic_application_type TEXT,                              -- Type of the agentic application
            model_name TEXT,                                            -- Name of the model used
            system_prompt JSONB,                                         -- JSON object for system prompts
            tools_id JSONB,                                              -- JSON object for associated tools
            created_by TEXT,                                            -- User who created the entry
            created_on TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,             -- Timestamp for when the record is created
            updated_on TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP              -- Timestamp for when the record is updated
        )
        """
        await connection.execute(create_statement)

        log.info(f"Table '{table_name}' created successfully or already exists.")

    except asyncpg.PostgresError as e:
        log.error(f"Error creating table '{table_name}': {e}")

    finally:
        # Close the connection
        await connection.close()



async def insert_into_agent_table(agent_data, table_name="agent_table"):
    """
    Inserts data into the agent table in PostgreSQL.

    Args:
        agent_data (dict): A dictionary containing the agent data to insert.
        table_name (str): Name of the PostgreSQL table to insert data into. Defaults to 'agent_table'.

    Returns:
        dict: Status of the operation, including success message or error details.
    """
    # Convert system_prompt and tools_id to JSON strings
    agent_data['system_prompt'] = json.dumps(agent_data['system_prompt'])
    agent_data['tools_id'] = json.dumps(agent_data['tools_id'])

    # Get current timestamp for created_on and updated_on
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    agent_data["created_on"] = now
    agent_data["updated_on"] = now

    # Generate agentic_application_id if not provided
    if not agent_data.get("agentic_application_id"):
        agent_data["agentic_application_id"] = str(uuid.uuid4())

    connection = await asyncpg.connect(
        host=POSTGRESQL_HOST,
        database=DATABASE,
        user=POSTGRESQL_USER,
        password=POSTGRESQL_PASSWORD
    )

    try:

        # Insert into the agent table
        insert_statement = f"""
        INSERT INTO {table_name} (
            agentic_application_id,
            agentic_application_name,
            agentic_application_description,
            agentic_application_workflow_description,
            agentic_application_type,
            model_name,
            system_prompt,
            tools_id,
            created_by,
            created_on,
            updated_on
        ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11)
        """

        # Strip whitespace from string fields
        for key in agent_data.keys():
            if isinstance(agent_data[key], str):
                agent_data[key] = agent_data[key].strip()

        await connection.execute(insert_statement,
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


        # Insert related tool-agent mapping data
        for tool_id in json.loads(agent_data["tools_id"]):
            tool = await get_tools_by_id(tool_id=tool_id)
            tool_data = tool[0] if tool else None
            await insert_data_tool_agent_mapping(
                tool_id=tool_id,
                agentic_application_id=agent_data["agentic_application_id"],
                tool_created_by=tool_data["created_by"],
                agentic_app_created_by=agent_data["created_by"]
            )

        # Insert tags into the tag-agent mapping table
        tags_status = await insert_into_tag_agentic_app_mapping(
            tag_ids=agent_data["tag_ids"],
            agentic_application_id=agent_data["agentic_application_id"]
        )

        # Return success status
        log.info(f"Successfully onboarded Agentic Application with ID: {agent_data['agentic_application_id']}")
        return {
            "message": f"Successfully onboarded Agentic Application with ID: {agent_data['agentic_application_id']}",
            "agentic_application_id": agent_data["agentic_application_id"],
            "agentic_application_name": agent_data["agentic_application_name"],
            "agentic_application_type": agent_data["agentic_application_type"],
            "model_name": agent_data.get("model_name", ""),
            "tags_status": tags_status,
            "created_by": agent_data["created_by"],
            "is_created": True
        }

    except asyncpg.PostgresError as e:
        # Return failure status in case of error
        log.error(f"Error inserting data into '{table_name}': {e}")
        return {
            "message": f"Error inserting data into '{table_name}': {e}",
            "agentic_application_id": "",
            "agentic_application_name": agent_data.get("agentic_application_name", ""),
            "agentic_application_type": agent_data.get("agentic_application_type", ""),
            "model_name": agent_data.get("model_name", ""),
            "created_by": agent_data.get("created_by", ""),
            "is_created": False
        }

    finally:
        # Ensure the connection is closed
        await connection.close()



async def insert_into_agent_table_meta(agent_data, table_name="agent_table"):
    """
    Inserts data into the agent table in PostgreSQL for meta agents.

    Args:
        agent_data (dict): A dictionary containing the agent data to insert.
        table_name (str): Name of the PostgreSQL table to insert data into. Defaults to 'agent_table'.

    Returns:
        dict: Status of the operation, including success message or error details.
    """
    # Convert system_prompt and tools_id to JSON strings
    agent_data['system_prompt'] = json.dumps(agent_data['system_prompt'])
    agent_data['tools_id'] = json.dumps(agent_data['tools_id'])

    # Get current timestamp for created_on and updated_on
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    agent_data["created_on"] = now
    agent_data["updated_on"] = now

    # Generate agentic_application_id if not provided
    if not agent_data.get("agentic_application_id"):
        agent_data["agentic_application_id"] = str(uuid.uuid4())

    connection = await asyncpg.connect(
        host=POSTGRESQL_HOST,
        database=DATABASE,
        user=POSTGRESQL_USER,
        password=POSTGRESQL_PASSWORD
    )

    try:

        # Insert into the agent table
        insert_statement = f"""
        INSERT INTO {table_name} (
            agentic_application_id,
            agentic_application_name,
            agentic_application_description,
            agentic_application_workflow_description,
            agentic_application_type,
            model_name,
            system_prompt,
            tools_id,
            created_by,
            created_on,
            updated_on
        ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11)
        """

        # Strip whitespace from string fields
        for key in agent_data.keys():
            if isinstance(agent_data[key], str):
                agent_data[key] = agent_data[key].strip()

        await connection.execute(insert_statement,
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


        # Insert related tool-agent mapping data
        for tool_id in json.loads(agent_data["tools_id"]):
            tool = await get_agents_by_id(agentic_application_id=tool_id)
            tool_data = tool[0] if tool else None
            await insert_data_tool_agent_mapping(
                tool_id=tool_id,
                agentic_application_id=agent_data["agentic_application_id"],
                tool_created_by=tool_data["created_by"],
                agentic_app_created_by=agent_data["created_by"]
            )

        # Insert tags into the tag-agent mapping table
        tags_status = await insert_into_tag_agentic_app_mapping(
            tag_ids=agent_data["tag_ids"],
            agentic_application_id=agent_data["agentic_application_id"]
        )

        # Return success status
        log.info(f"Successfully onboarded Agentic Application with ID: {agent_data['agentic_application_id']}")
        return {
            "message": f"Successfully onboarded Agentic Application with ID: {agent_data['agentic_application_id']}",
            "agentic_application_id": agent_data["agentic_application_id"],
            "agentic_application_name": agent_data["agentic_application_name"],
            "agentic_application_type": agent_data["agentic_application_type"],
            "model_name": agent_data.get("model_name", ""),
            "tags_status": tags_status,
            "created_by": agent_data["created_by"],
            "is_created": True
        }

    except asyncpg.PostgresError as e:
        # Return failure status in case of error
        log.error(f"Error inserting data into '{table_name}': {e}")
        return {
            "message": f"Error inserting data into '{table_name}': {e}",
            "agentic_application_id": "",
            "agentic_application_name": agent_data.get("agentic_application_name", ""),
            "agentic_application_type": agent_data.get("agentic_application_type", ""),
            "model_name": agent_data.get("model_name", ""),
            "created_by": agent_data.get("created_by", ""),
            "is_created": False
        }

    finally:
        # Ensure the connection is closed
        await connection.close()



async def get_agents(agentic_application_type=None, agent_table_name="agent_table", tag_table_name="tags_table", mapping_table_name="tag_agentic_app_mapping_table"):
    """
    Retrieves agents from the agent table in PostgreSQL.

    Args:
        agentic_application_type (str, optional): The type of agentic application to filter by. Defaults to None.
        agent_table_name (str): The name of the agent table. Defaults to 'agent_table'.

    Returns:
        list: A list of agents from the agent table, represented as dictionaries.
    """
    connection = await asyncpg.connect(
        host=POSTGRESQL_HOST,
        database=DATABASE,
        user=POSTGRESQL_USER,
        password=POSTGRESQL_PASSWORD
    )

    try:


        query = f"""
        SELECT
            a.agentic_application_id,
            a.agentic_application_name,
            a.agentic_application_description,
            a.agentic_application_workflow_description,
            a.agentic_application_type,
            a.model_name,
            a.system_prompt,
            a.tools_id,
            a.created_by,
            a.created_on,
            a.updated_on,
            COALESCE(
                JSON_AGG(
                    JSON_BUILD_OBJECT(
                        'tag_id', tg.tag_id,
                        'tag_name', tg.tag_name,
                        'created_by', tg.created_by
                    )
                ) FILTER (WHERE tg.tag_id IS NOT NULL),
                '[]'
            ) AS tags
        FROM {agent_table_name} a
        LEFT JOIN {mapping_table_name} m ON a.agentic_application_id = m.agentic_application_id
        LEFT JOIN {tag_table_name} tg ON m.tag_id = tg.tag_id
        """

        # Add filtering for agentic_application_type if provided
        parameters = []
        if agentic_application_type:
            if isinstance(agentic_application_type, str):
                agentic_application_type = [agentic_application_type]

            placeholders = ', '.join(f"${i+1}" for i in range(len(agentic_application_type)))
            query += f" WHERE a.agentic_application_type IN ({placeholders})"
            parameters.extend(agentic_application_type)

        # Group by agent ID to aggregate tags
        query += " GROUP BY a.agentic_application_id ORDER BY a.created_on DESC"

        # Execute the query
        rows = await connection.fetch(query, *parameters)

        # Convert rows into list of dictionaries
        results_as_dicts = []
        for row in rows:
            agent = dict(row)
            # Deserialize the tags field from JSON string to a Python list
            agent['tags'] = json.loads(agent['tags']) if isinstance(agent['tags'], str) else agent['tags']
            results_as_dicts.append(agent)
        log.info(f"Retrieved {len(results_as_dicts)} agents from '{agent_table_name}' with type filter: {agentic_application_type if agentic_application_type else 'None'}")

        return results_as_dicts

    except asyncpg.PostgresError as e:
        # Handle database error and return an empty list
        log.error(f"Database error: {e}")
        return []

    finally:
        # Ensure the database connection is closed
        await connection.close()



async def get_agents_by_page(user_email_id,
                       agentic_application_type=None,
                       agent_table_name="agent_table",
                       name='',
                       limit=20,
                       page=1,
                       is_admin=False,
                       tag_table_name="tags_table",
                       mapping_table_name="tag_agentic_app_mapping_table"):
    """
    Retrieves agents from the PostgreSQL database with pagination support.

    Args:
        user_email_id (str): The email ID of the user performing the query.
        agentic_application_type (str, optional): The type of agentic application to filter by. Defaults to None.
        agent_table_name (str): Name of the agent table. Defaults to 'agent_table'.
        name (str, optional): Agent name to filter by. Defaults to '' (no filtering).
        limit (int, optional): Number of results per page. Defaults to 20.
        page (int, optional): Page number for pagination. Defaults to 1.
        is_admin (bool): Whether the user is an admin.
        tag_table_name (str): The name of the tags table. Defaults to 'tags_table'.
        mapping_table_name (str): The name of the mapping table. Defaults to 'tag_agentic_app_mapping_table'.


    Returns:
        dict: A dictionary containing the total count of agents and the paginated agent details.
    """
    connection = await asyncpg.connect(
        host=POSTGRESQL_HOST,
        database=DATABASE,
        user=POSTGRESQL_USER,
        password=POSTGRESQL_PASSWORD
    )

    try:

        # Normalize input for case-insensitive search
        name_filter = f"%{name.lower()}%" if name else "%"
        type_filter = agentic_application_type if agentic_application_type else None

        # Build total count query
        total_count_query = f"""
        SELECT COUNT(*)
        FROM {agent_table_name}
        WHERE LOWER(agentic_application_name) LIKE $1
        """
        params = [name_filter]
        idx = 2
        if type_filter:
            total_count_query += f" AND agentic_application_type = ${idx}"
            params.append(type_filter)
            idx += 1
        if not is_admin:
            total_count_query += f" AND created_by = ${idx}"
            params.append(user_email_id)

        # Execute total count query
        total_agents = await connection.fetchval(total_count_query, *params)

        # Calculate offset for pagination
        offset = limit * (0 if page < 1 else page - 1)

        # Build paginated query
        paginated_query = f"""
        SELECT
            a.agentic_application_id,
            a.agentic_application_name,
            a.agentic_application_description,
            a.agentic_application_workflow_description,
            a.agentic_application_type,
            a.model_name,
            a.system_prompt,
            a.tools_id,
            a.created_by,
            a.created_on,
            a.updated_on,
            COALESCE(
                JSON_AGG(
                    JSON_BUILD_OBJECT(
                        'tag_id', tg.tag_id,
                        'tag_name', tg.tag_name,
                        'created_by', tg.created_by
                    )
                ) FILTER (WHERE tg.tag_id IS NOT NULL),
                '[]'
            ) AS tags
        FROM {agent_table_name} a
        LEFT JOIN {mapping_table_name} m ON a.agentic_application_id = m.agentic_application_id
        LEFT JOIN {tag_table_name} tg ON m.tag_id = tg.tag_id
        WHERE LOWER(a.agentic_application_name) LIKE $1
        """
        params = [name_filter]
        idx = 2
        if type_filter:
            paginated_query += f" AND a.agentic_application_type = ${idx}"
            params.append(type_filter)
            idx += 1
        if not is_admin:
            paginated_query += f" AND a.created_by = ${idx}"
            params.append(user_email_id)
            idx += 1
        paginated_query += f" GROUP BY a.agentic_application_id ORDER BY a.created_on DESC LIMIT ${idx} OFFSET ${idx + 1}"
        params.extend([limit, offset])


        # Execute the query and fetch all rows
        rows = await connection.fetch(paginated_query, *params)


        agents = []
        for row in rows:
            agent = dict(row)
            # Deserialize the tags field from JSON string to a Python list
            agent['tags'] = json.loads(agent['tags']) if isinstance(agent['tags'], str) else agent['tags']
            agents.append(agent)

        # Return results
        log.info(f"Retrieved {len(agents)} agents from '{agent_table_name}' for page {page} with type filter: {type_filter} and name filter: {name}.")

        return {"total_count": total_agents, "details": agents}

    except asyncpg.PostgresError as e:
        log.error(f"Database error: {e}")
        return {"total_count": 0, "details": []}

    finally:
        await connection.close()


async def get_agents_by_id(agentic_application_type="",
                     agent_table_name="agent_table",
                     agentic_application_id=None,
                     agentic_application_name=None,
                     created_by=None):
    """
    Retrieves agents from the PostgreSQL database based on provided parameters.

    Args:
        agentic_application_type (str, optional): The type of agentic application to filter by. Defaults to ''.
        agent_table_name (str): Name of the agent table. Defaults to 'agent_table'.
        agentic_application_id (str, optional): The ID of the agentic application to filter by. Defaults to None.
        agentic_application_name (str, optional): The name of the agentic application to filter by. Defaults to None.
        created_by (str, optional): The creator of the agentic application to filter by. Defaults to None.

    Returns:
        list: A list of dictionaries representing the retrieved agents, or an empty list on error.
    """
    connection = await asyncpg.connect(
        host=POSTGRESQL_HOST,
        database=DATABASE,
        user=POSTGRESQL_USER,
        password=POSTGRESQL_PASSWORD
    )
    

    try:

        # Start building the base query
        query = f"SELECT * FROM {agent_table_name}"
        where_clauses = []
        params = []

        filters = {
            "agentic_application_id": agentic_application_id,
            "agentic_application_name": agentic_application_name,
            "created_by": created_by,
            "agentic_application_type": agentic_application_type
        }

        # Build WHERE clause with parameter placeholders
        for idx, (field, value) in enumerate(((f for f in filters.items() if f[1] not in (None, ""))), start=1):
            where_clauses.append(f"{field} = ${idx}")
            params.append(value)


        # Append WHERE clause if filters are provided
        if where_clauses:
            query += " WHERE " + " AND ".join(where_clauses)

        # Execute the query with parameters
        rows = await connection.fetch(query, *params)
        # Convert results to list of dictionaries
        results_as_dicts = [dict(row) for row in rows]

        # Add tags for each agent
        agent_id_to_tags = await get_agent_tags_from_mapping_as_dict()
        for result in results_as_dicts:
            result["tags"] = agent_id_to_tags.get(result['agentic_application_id'], [])

        log.info(f"Retrieved {len(results_as_dicts)} agents from '{agent_table_name}' with provided filters.")
        return results_as_dicts

    except asyncpg.PostgresError as e:
        log.error(f"Database error: {e}")
        return []  # Return an empty list in case of an error

    finally:
        await connection.close()

async def check_recycle_agent_name_if_exist(agentic_application_name):
    """
    Checks if the recycle_agent table exists in the PostgreSQL database.

    Returns:
        bool: True if the table exists, False otherwise.
    """
    connection = await asyncpg.connect(
        host=POSTGRESQL_HOST,
        database="recycle",
        user=POSTGRESQL_USER,
        password=POSTGRESQL_PASSWORD
    )

    try:
        # Check if the recycle_agent table exists
        query = f"SELECT EXISTS(SELECT 1 FROM recycle_agent WHERE agentic_application_name = $1)"
        exists = await connection.fetchval(query,agentic_application_name)
        return exists

    except asyncpg.PostgresError as e:
        log.error(f"Error checking recycle_agent table existence: {e}")
        return False

    finally:
        await connection.close()



async def get_agents_by_id_studio(agentic_application_id, agent_table_name="agent_table", tool_table_name="tool_table"):
    """
    Retrieves agent details along with tool information from the PostgreSQL database.

    Args:
        agentic_application_id (str): The agentic application ID.
        agent_table_name (str): Name of the agent table (default is "agent_table").
        tool_table_name (str): Name of the tool table (default is "tool_table").

    Returns:
        dict: A dictionary with agent details and associated tools information.
    """
    connection = await asyncpg.connect(
        host=POSTGRESQL_HOST,
        database=DATABASE,
        user=POSTGRESQL_USER,
        password=POSTGRESQL_PASSWORD
    )

    try:


        # Retrieve agent details
        query = f"SELECT * FROM {agent_table_name} WHERE agentic_application_id = $1"
        agent_row = await connection.fetchrow(query, agentic_application_id)


        if not agent_row:
            return {}  # Return an empty dictionary if the agent is not found

        # Structure result as a dictionary
        # agent_row is already a dictionary-like object, no need to manually extract columns
        agent_details = dict(agent_row)

        # Parse tools_id from the agent details
        tools_id = json.loads(agent_details.get("tools_id", "[]"))

        # Retrieve tool information for each tool_id
        tool_id_to_tags = await get_tool_tags_from_mapping_as_dict()
        tool_info_list = []
        for tool_id in tools_id:
            tool_query = f"""
            SELECT tool_id, tool_name, tool_description, created_by, created_on
            FROM {tool_table_name}
            WHERE tool_id = $1
            """
            tool_row = await connection.fetchrow(tool_query, tool_id)


            if tool_row:
                # Fetch tool column names and structure result as a dictionary
                tool_info_list.append(dict(tool_row))
                tool_info_list[-1]['tags'] = tool_id_to_tags.get(tool_info_list[-1]['tool_id'], [])


        # Update agent details with tool information
        agent_details["tools_id"] = tool_info_list

        log.info(f"Retrieved agent details for Agentic Application ID: {agentic_application_id} with {len(tool_info_list)} associated tools.")
        return agent_details

    except asyncpg.PostgresError as e:
        log.error(f"Database error: {e}")
        return {}

    finally:
        await connection.close()


async def update_agent_by_id_util(agent_data, table_name="agent_table", agentic_application_id=None, agentic_application_name=None):
    """
    Updates an agent in the PostgreSQL database based on the provided agentic application ID or name.

    Args:
        agent_data (dict): A dictionary containing the agent data to update.
        table_name (str): Name of the PostgreSQL table to update. Defaults to 'agent_table'.
        agentic_application_id (str, optional): The ID of the agentic application to update.
        agentic_application_name (str, optional): The name of the agentic application to update.

    Returns:
        bool: True if the update was successful, False otherwise.
    """
    if not agentic_application_id and not agentic_application_name:
        return False

    connection = await asyncpg.connect(
        host=POSTGRESQL_HOST,
        database=DATABASE,
        user=POSTGRESQL_USER,
        password=POSTGRESQL_PASSWORD
    )

    try:

        # Get current timestamp for `updated_on`
        agent_data["updated_on"] = datetime.now(timezone.utc).replace(tzinfo=None)

        # Prepare the update query dynamically
        update_fields = [f"{column} = ${idx + 1}" for idx, column in enumerate(agent_data.keys())]
        query = f"UPDATE {table_name} SET {', '.join(update_fields)}"


        # Add WHERE clause based on the identifier
        params = list(agent_data.values())
        if agentic_application_id:
            # query += " WHERE agentic_application_id = ${{" + str(len(params) + 1) + "}}"
            query += f" WHERE agentic_application_id = ${len(params) + 1}"
            params.append(agentic_application_id)
        elif agentic_application_name:
            # query += " WHERE agentic_application_name = ${{" + str(len(params) + 1) + "}}"
            query += f" WHERE agentic_application_name = ${len(params) + 1}"
            params.append(agentic_application_name)

        # Execute the query
        result = await connection.execute(query, *params)

        # Clean up associated tool-agent mappings
        await delete_data_tool_agent_mapping(agentic_application_id=agent_data['agentic_application_id'])
        for tool_id in json.loads(agent_data['tools_id']):
            tool_data = await get_tools_by_id(tool_id=tool_id)
            if tool_data:
                created_by = tool_data[0]["created_by"]
            await insert_data_tool_agent_mapping(
                tool_id=tool_id,
                agentic_application_id=agent_data["agentic_application_id"],
                tool_created_by= created_by,
                agentic_app_created_by=agent_data["created_by"]
            )

        log.info(f"Successfully updated Agentic Application with ID: {agentic_application_id if agentic_application_id else agentic_application_name}")
        return result != "UPDATE 0"

    except asyncpg.PostgresError as e:
        log.error(f"Database error: {e}")
        return False

    finally:
        await connection.close()


async def update_agent_by_id(model_name,
                       agentic_application_type,
                       table_name="agent_table",
                       user_email_id="",
                       is_admin=False,
                       agentic_application_id_to_modify="",
                       agentic_application_name_to_modify="",
                       agentic_application_description="",
                       agentic_application_workflow_description="",
                       system_prompt={},
                       tools_id=[],
                       tools_id_to_add=[],
                       tools_id_to_remove=[],
                       created_by="",
                       updated_tag_id_list=None):
    # Check if the necessary identifiers are provided
    if not agentic_application_id_to_modify:
        log.error("Error: Must provide 'agentic_application_id' to update an agentic application.")
        return {
            "status_message": "Error: Must provide 'agentic_application_id' to update an agentic application.",
            "is_update": False
        }

    # Fetch current agent data
    agents = await get_agents_by_id(
        agentic_application_type="",
        agent_table_name=table_name,
        agentic_application_id=agentic_application_id_to_modify,
        agentic_application_name=agentic_application_name_to_modify
    )
    if not agents:
        log.error(f"No Agentic Application found with ID: {agentic_application_id_to_modify}")
        return {
            "status_message": "Please validate the AGENTIC APPLICATION ID.",
            "is_update": False
        }
    agent = agents[0]
    agent["tools_id"] = json.loads(agent["tools_id"])
    #agent["tools_id"] = agent["tools_id"]
    agent["system_prompt"] = json.loads(agent["system_prompt"])

    if not agentic_application_description and not agentic_application_workflow_description and not system_prompt and not tools_id and not tools_id_to_add and not tools_id_to_remove and not created_by and not updated_tag_id_list:
        log.error("Error: Please specify at least one field to modify.")
        return {
            "status_message": "Error: Please specify at least one of the following fields to modify: application description, application workflow description, system prompt, tools id, tools id to add, tools id to remove, tags.",
            "is_update": False
        }

    # Check permissions
    if not is_admin and agent["created_by"] != user_email_id:
        log.error(f"You do not have permission to update Agentic Application with ID: {agent['agentic_application_id']}. Only the admin or the agent's creator can perform this action.")
        return {
            "status_message": f"You do not have permission to update Agentic Application with ID: {agent['agentic_application_id']}.",
            "is_update": False
        }

    tag_status = None
    if updated_tag_id_list != None:
        if not await clear_tags(agent_id=agentic_application_id_to_modify):
            log.error(f"Failed to clear tags for Agentic Application ID: {agentic_application_id_to_modify}")
            return {
                    "status_message": "Failed to update the agent.",
                    "is_update": False
                }
        if not updated_tag_id_list:
            tags = await get_tags_by_id_or_name(tag_name="General")
            updated_tag_id_list = tags["tag_id"]
        tag_status = await insert_into_tag_agentic_app_mapping(tag_ids=updated_tag_id_list,
                                                         agentic_application_id=agentic_application_id_to_modify)

    if not agentic_application_description and not agentic_application_workflow_description and not system_prompt and not tools_id and not tools_id_to_add and not tools_id_to_remove and not created_by:
        log.info("No fields to update. Returning current agent data.")
        return {
            "status_message": "Tags updated successfully",
            "tag_update_status": tag_status,
            "is_update": True
        }

    # Validate tool IDs (all tools to add, remove, and current ones)
    val_tools_id = tools_id + tools_id_to_add + tools_id_to_remove
    val_tools_id = list(set(val_tools_id))
    val_tools_resp = await validate_tool_id(tools_id=val_tools_id)
    if "Error" in val_tools_resp:
        log.error(f"Validation error: {val_tools_resp}")
        return {
            "status_message": val_tools_resp,
            "is_update": False
        }

    # Update fields
    if agentic_application_description:
        agent["agentic_application_description"] = agentic_application_description
    if agentic_application_workflow_description:
        agent["agentic_application_workflow_description"] = agentic_application_workflow_description
    if system_prompt:
        agent["system_prompt"] = {
            **agent.get("system_prompt", {}), **system_prompt}
    if tools_id:
        agent["tools_id"] = list(set(tools_id))
    if tools_id_to_add:
        agent["tools_id"] = list(
            set(agent.get("tools_id", []) + tools_id_to_add))
    if tools_id_to_remove:
        agent["tools_id"] = [tool for tool in agent["tools_id"]
                             if tool not in tools_id_to_remove]
    if created_by:
        agent["created_by"] = created_by
    if agentic_application_type:
        agent["agentic_application_type"] = agentic_application_type
    agent["model_name"] = model_name

    # If system prompt is not provided, update it based on current configuration
    if not system_prompt:
        if agent["agentic_application_type"] == "react_agent":
            response = await react_agent_onboarding(
                agent_name=agent["agentic_application_name"],
                agent_goal=agent["agentic_application_description"],
                workflow_description=agent["agentic_application_workflow_description"],
                model_name=agent["model_name"],
                tools_id=agent["tools_id"],
                user_email_id=agent["created_by"],
                only_return_prompt=True
            )
            agent['system_prompt'] = {"SYSTEM_PROMPT_REACT_AGENT": response}
        elif agent["agentic_application_type"] == "multi_agent":
            response = await react_multi_agent_onboarding(
                agent_name=agent["agentic_application_name"],
                agent_goal=agent["agentic_application_description"],
                workflow_description=agent["agentic_application_workflow_description"],
                model_name=agent["model_name"],
                tools_id=agent["tools_id"],
                user_email_id=agent["created_by"],
                only_return_prompt=True
            )
            agent['system_prompt'] = response['MULTI_AGENT_SYSTEM_PROMPTS']

    # Perform the database update
    agent['system_prompt'] = json.dumps(agent['system_prompt'])
    agent['tools_id'] = json.dumps(agent['tools_id'])
    tags = agent.pop("tags", None)
    success = await update_agent_by_id_util(
        agent_data=agent,
        table_name=table_name,
        agentic_application_id=agentic_application_id_to_modify,
        agentic_application_name=agentic_application_name_to_modify
    )
    if success:
        status = {
            "status_message": f"Successfully updated Agentic Application with ID: {agentic_application_id_to_modify}.",
            "is_update": True
        }
    else:
        status = {
            "status_message": "Failed to update the Agentic Application.",
            "is_update": False
        }
    if tag_status:
        status['tag_update_status'] = tag_status
    log.info(f"Update status: {status['status_message']}")
    return status


async def update_agent_by_id_util_meta(agent_data, table_name="agent_table", agentic_application_id=None, agentic_application_name=None):
    """
    Updates a meta-agent in the PostgreSQL database based on the provided agentic application ID or name.

    Args:
        agent_data (dict): A dictionary containing the agent data to update.
        table_name (str): Name of the PostgreSQL table to update. Defaults to 'agent_table'.
        agentic_application_id (str, optional): The ID of the agentic application to update.
        agentic_application_name (str, optional): The name of the agentic application to update.

    Returns:
        bool: True if the update was successful, False otherwise.
    """
    if not agentic_application_id and not agentic_application_name:
        return False

    connection = await asyncpg.connect(
        host=POSTGRESQL_HOST,
        database=DATABASE,
        user=POSTGRESQL_USER,
        password=POSTGRESQL_PASSWORD
    )

    try:

        # Get current timestamp for `updated_on`
        agent_data["updated_on"] = datetime.now(timezone.utc).replace(tzinfo=None)

        # Prepare the update query dynamically
        update_fields = [f"{column} = ${idx + 1}" for idx, column in enumerate(agent_data.keys())]
        query = f"UPDATE {table_name} SET {', '.join(update_fields)}"



        # Add WHERE clause based on the identifier

        params = list(agent_data.values())
        if agentic_application_id:
            query += f" WHERE agentic_application_id = ${len(params) + 1}"
            params.append(agentic_application_id)
        elif agentic_application_name:
            query += f" WHERE agentic_application_name = ${len(params) + 1}"
            params.append(agentic_application_name)

        # Execute the query
        result = await connection.execute(query, *params)

        # Clean up associated tool-agent mappings
        await delete_data_tool_agent_mapping(agentic_application_id=agent_data['agentic_application_id'])
        for tool_id in json.loads(agent_data['tools_id']):
            tool = await get_agents_by_id(agentic_application_id=tool_id)
            tool_data = tool[0] if tool else None
            insert_data_tool_agent_mapping(
                tool_id=tool_id,
                agentic_application_id=agent_data["agentic_application_id"],
                tool_created_by= tool_data["created_by"],
                agentic_app_created_by=agent_data["created_by"]
            )

        log.info(f"Successfully updated Agentic Application with ID: {agentic_application_id if agentic_application_id else agentic_application_name}")
        return result != "Update 0"

    except asyncpg.PostgresError as e:
        log.error(f"Database error: {e}")
        return False

    finally:
        await connection.close()


async def update_agent_by_id_meta(model_name,
                       agentic_application_type,
                       table_name="agent_table",
                       user_email_id="",
                       is_admin=False,
                       agentic_application_id_to_modify="",
                       agentic_application_name_to_modify="",
                       agentic_application_description="",
                       agentic_application_workflow_description="",
                       system_prompt={},
                       worker_agents_id=[],
                       worker_agents_id_to_add=[],
                       worker_agents_id_to_remove=[],
                       created_by="",
                       updated_tag_id_list=None):
    # Check if the necessary identifiers are provided
    if not agentic_application_id_to_modify:
        log.error("Error: Must provide 'agentic_application_id' to update an agentic application.")
        return {
            "status_message": "Error: Must provide 'agentic_application_id' to update an agentic application.",
            "is_update": False
        }

    # Fetch current agent data
    agents = await get_agents_by_id(
        agentic_application_type="",
        agent_table_name=table_name,
        agentic_application_id=agentic_application_id_to_modify,
        agentic_application_name=agentic_application_name_to_modify
    )
    if not agents:
        log.error(f"No Agentic Application found with ID: {agentic_application_id_to_modify}")
        return {
            "status_message": "Please validate the AGENTIC APPLICATION ID.",
            "is_update": False
        }
    agent = agents[0]
    agent["tools_id"] = json.loads(agent["tools_id"])
    agent["system_prompt"] = json.loads(agent["system_prompt"])

    if not agentic_application_description and not agentic_application_workflow_description and not system_prompt and not worker_agents_id and not worker_agents_id_to_add and not worker_agents_id_to_remove and not created_by and not updated_tag_id_list:
        log.error("Error: Please specify at least one field to modify.")
        return {
            "status_message": "Error: Please specify at least one of the following fields to modify: application description, application workflow description, system prompt, tools id, tools id to add, tools id to remove, tags.",
            "is_update": False
        }

    # Check permissions
    if not is_admin and agent["created_by"] != user_email_id:
        log.error(f"You do not have permission to update Agentic Application with ID: {agent['agentic_application_id']}. Only the admin or the agent's creator can perform this action.")
        return {
            "status_message": f"You do not have permission to update Agentic Application with ID: {agent['agentic_application_id']}.",
            "is_update": False
        }

    tag_status = None
    if updated_tag_id_list != None:
        if not await clear_tags(agent_id=agentic_application_id_to_modify):
            log.error(f"Failed to clear tags for Agentic Application ID: {agentic_application_id_to_modify}")
            return {
                    "status_message": "Failed to update the agent.",
                    "is_update": False
                }
        if not updated_tag_id_list:
            tags = await get_tags_by_id_or_name(tag_name="General")
            updated_tag_id_list = tags["tag_id"]
        tag_status = await insert_into_tag_agentic_app_mapping(tag_ids=updated_tag_id_list,
                                                         agentic_application_id=agentic_application_id_to_modify)

    if not agentic_application_description and not agentic_application_workflow_description and not system_prompt and not worker_agents_id and not worker_agents_id_to_add and not worker_agents_id_to_remove and not created_by:
        log.info("No fields to update. Returning current agent data.")
        return {
            "status_message": "Tags updated successfully",
            "tag_update_status": tag_status,
            "is_update": True
        }

    # Validate Worker IDs (all Workers to add, remove, and current ones)
    val_workers_id = worker_agents_id + worker_agents_id_to_add + worker_agents_id_to_remove
    val_workers_id = list(set(val_workers_id))
    val_workers_resp = await validate_agent_id(agents_id=val_workers_id)
    if "Error" in val_workers_resp:
        log.error(f"Validation error: {val_workers_resp}")
        return {
            "status_message": val_workers_resp,
            "is_update": False
        }

    # Update fields
    if agentic_application_description:
        agent["agentic_application_description"] = agentic_application_description
    if agentic_application_workflow_description:
        agent["agentic_application_workflow_description"] = agentic_application_workflow_description
    if system_prompt:
        agent["system_prompt"] = {
            **agent.get("system_prompt", {}), **system_prompt}
    if worker_agents_id:
        agent["tools_id"] = list(set(worker_agents_id))
    if worker_agents_id_to_add:
        agent["tools_id"] = list(
            set(agent.get("tools_id", []) + worker_agents_id_to_add))
    if worker_agents_id_to_remove:
        agent["tools_id"] = [tool for tool in agent["tools_id"]
                             if tool not in worker_agents_id_to_remove]
    if created_by:
        agent["created_by"] = created_by
    if agentic_application_type:
        agent["agentic_application_type"] = agentic_application_type
    agent["model_name"] = model_name

    # If system prompt is not provided, update it based on current configuration
    if not system_prompt:
        if agent["agentic_application_type"] == "meta_agent":
            response = await meta_agent_onboarding(
                agent_name=agent["agentic_application_name"],
                agent_goal=agent["agentic_application_description"],
                workflow_description=agent["agentic_application_workflow_description"],
                model_name=agent["model_name"],
                agentic_app_ids=agent["tools_id"],
                user_email_id=agent["created_by"],
                only_return_prompt=True
            )
            agent['system_prompt'] = {"SYSTEM_PROMPT_META_AGENT": response}
        elif agent["agentic_application_type"] == "planner_meta_agent":
            response = await meta_agent_with_planner_onboarding(
                agent_name=agent["agentic_application_name"],
                agent_goal=agent["agentic_application_description"],
                workflow_description=agent["agentic_application_workflow_description"],
                model_name=agent["model_name"],
                agentic_app_ids=agent["tools_id"],
                user_email_id=agent["created_by"],
                only_return_prompt=True
            )
            agent['system_prompt'] = response

    # Perform the database update
    agent['system_prompt'] = json.dumps(agent['system_prompt'])
    agent['tools_id'] = json.dumps(agent['tools_id'])
    tags = agent.pop("tags", None)
    success = await update_agent_by_id_util_meta(
        agent_data=agent,
        table_name=table_name,
        agentic_application_id=agentic_application_id_to_modify,
        agentic_application_name=agentic_application_name_to_modify
    )
    if success:
        status = {
            "status_message": f"Successfully updated Agentic Application with ID: {agentic_application_id_to_modify}.",
            "is_update": True
        }
    else:
        status = {
            "status_message": "Failed to update the Agentic Application.",
            "is_update": False
        }
    if tag_status:
        status['tag_update_status'] = tag_status
    log.info(f"Update status: {status['status_message']}")
    return status

async def delete_agent_by_id(user_email_id,
                       is_admin=False,
                       agent_table_name="agent_table",
                       agentic_application_id=None,
                       agentic_application_name=None):
    """
    Deletes an agentic application from the PostgreSQL database based on the provided agentic application ID or name.

    Args:
        user_email_id (str): The email ID of the user performing the deletion.
        is_admin (bool): Whether the user is an admin.
        agent_table_name (str): Name of the PostgreSQL table containing agents.
        agentic_application_id (str, optional): The ID of the agentic application to delete.
        agentic_application_name (str, optional): The name of the agentic application to delete.

    Returns:
        dict: Status of the operation, including success message or error details.
    """
    if not agentic_application_id and not agentic_application_name:
        log.error("Error: Must provide 'agentic_application_id' to delete an agentic application.")
        return {
            "status_message": "Error: Must provide 'agentic_application_id' or 'agentic_application_name' to delete an agentic application.",
            "is_delete": False
        }

    connection = await asyncpg.connect(
        host=POSTGRESQL_HOST,
        database=DATABASE,
        user=POSTGRESQL_USER,
        password=POSTGRESQL_PASSWORD
    )

    connection_recycle = await asyncpg.connect(
        host=POSTGRESQL_HOST,
        database='recycle',
        user=POSTGRESQL_USER,
        password=POSTGRESQL_PASSWORD
    )

    try:

        # Retrieve agentic application details
        query = f"SELECT * FROM {agent_table_name} WHERE "
        params = []
        idx = 1
        if agentic_application_id:
            query += f"agentic_application_id = ${idx}"
            params.append(agentic_application_id)
            idx += 1
        elif agentic_application_name:
            query += f"agentic_application_name = ${idx}"
            params.append(agentic_application_name)

        agent = await connection.fetchrow(query, *params)


        if not agent:
            log.error(f"No Agentic Application found with ID: {agentic_application_id}")
            return {
                "status_message": f"No Agentic Application available with ID: {agentic_application_id or agentic_application_name}",
                "is_delete": False
            }

        agent_data = dict(agent)

        #insert into recycle bin

        recycle_query = f"""
        INSERT INTO recycle_agent(agentic_application_id, agentic_application_name, agentic_application_description, agentic_application_workflow_description, agentic_application_type, model_name, system_prompt, tools_id, created_by, created_on, updated_on)
        VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11)
        """
        recycle_params = (
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


         # Check permissions
        if is_admin or agent_data["created_by"] == user_email_id:
            can_delete = True
        else:
            can_delete = False

        if not can_delete:
            log.error(f"You do not have permission to delete Agentic Application with ID: {agent_data['agentic_application_id']}. Only the admin or the creator can perform this action.")
            return {
                "status_message": f"""You do not have permission to delete Agentic Application with ID: {agent_data['agentic_application_id']}. Only the admin or the creator can perform this action.""",
                "is_delete": False
            }

        # Delete the agentic application
        delete_query = f"DELETE FROM {agent_table_name} WHERE "
        params = []

        if agentic_application_id:
            delete_query += "agentic_application_id = $1"
            params = [agentic_application_id]
        elif agentic_application_name:
            delete_query += "agentic_application_name = $1"
            params = [agentic_application_name]
        else:
            raise ValueError("Must provide either agentic_application_id or agentic_application_name")

        await connection.execute(delete_query, *params)
        await connection_recycle.execute(recycle_query, *recycle_params)

        # Clean up associated tool-agent mappings
        await delete_data_tool_agent_mapping(
            agentic_application_id=agent_data["agentic_application_id"]
        )
        await clear_tags(agent_id=agent_data["agentic_application_id"])

        log.info(f"Successfully deleted Agentic Application with ID: {agentic_application_id or agent_data['agentic_application_id']}")
        return {
            "status_message": f"Successfully Deleted Record for Agentic Application with ID: {agentic_application_id or agent_data['agentic_application_id']}.",
            "is_delete": True
        }

    except asyncpg.PostgresError as e:
        log.error(f"Database error: {e}")
        return {
            "status_message": f"An error occurred while deleting the agent: {e}",
            "is_delete": False
        }

    finally:
        await connection_recycle.close()
        await connection.close()


# Agent Onboarding Helper Functions
async def validate_tool_id(tools_id: list):
    """
    Validates whether the given tool IDs exist in the database.

    Args:
        tools_id (list): A list of tool IDs to validate.

    Returns:
        str: Validation result message indicating success or failure.
    """
    if tools_id:
        for tool_id in tools_id:
            try:
                tools = await get_tools_by_id(tool_id=tool_id)
                if not tools:  # If no result is returned
                    log.error(f"Tool with ID {tool_id} not found.")
                    return f"Error: The tool with Tool ID: {tool_id} is not available. Please validate the provided tool id."
            except Exception as e:
                log.error(f"Error validating tool ID {tool_id}: {str(e)}")
                return f"Error: The tool with Tool ID: {tool_id} caused an exception: {str(e)}"
        log.info("All tools are available for onboarding.")
        return "Tool Check Complete. All tools are available."
    log.info("No tools provided for validation.")
    return "No Tool ID to check"


async def validate_agent_id(agents_id: list):
    """
    Validates whether the given agent IDs exist in the database.

    Args:
        agents_id (list): A list of tool IDs to validate.

    Returns:
        str: Validation result message indicating success or failure.
    """
    if agents_id:
        for agent_id in agents_id:
            try:
                agent = await get_agents_by_id(agentic_application_id=agent_id)
                if not agent:  # If no result is returned
                    log.error(f"Agent with ID {agent_id} not found.")
                    return f"Error: The agent with Agentic Application ID: {agent_id} is not available. Please validate the provided agent id."
            except Exception as e:
                log.error(f"Error validating agent ID {agent_id}: {str(e)}")
                return f"Error: The agent with Agentic Application ID: {agent_id} is not available. Please validate the provided agent id."
        log.info("All agents are available for onboarding.")
        return "Agent Check Complete. All agents are available."
    log.info("No agents provided for validation.")
    return "No Agentic Application ID to check"


async def extract_tools_using_tools_id(tools_id):
    """
    Extracts tool information from the database using tool IDs.

    Args:
        tools_id (list): List of tool IDs to retrieve details for.

    Returns:
        dict: A dictionary containing tool information indexed by tool names.
    """
    tools_info_user = {}

    for idx, tool_id in enumerate(tools_id):
        single_tool_info = {}
        single_tool = await get_tools_by_id(tool_id=tool_id)

        if single_tool:  # Check if any result is returned
            single_tool_info_df = single_tool[0]
            single_tool_info["Tool_Name"] = single_tool_info_df.get("tool_name")
            single_tool_info["Tool_Description"] = single_tool_info_df.get("tool_description")
            single_tool_info["code_snippet"] = single_tool_info_df.get("code_snippet")
            single_tool_info["tags"] = single_tool_info_df.get("tags")
            tools_info_user[f"Tool_{idx+1}"] = single_tool_info
        else:
            tools_info_user[f"Tool_{idx+1}"] = {"error": f"No data found for tool_id: {tool_id}"}

    log.info(f"Extracted {len(tools_info_user)} tools using provided tool IDs.")
    return tools_info_user


def generate_tool_prompt(tools_info):
    """Generates a prompt for the agent describing the available tools.

    Args:
        tools_info (dict): A dictionary containing information about each tool.

    Returns:
        str: A prompt string describing the tools.
    """
    tool_prompt = ""
    for tool_id, tool_info_desc in tools_info.items():
        tool_nm = tool_info_desc.get("Tool_Name", "")
        tool_desc = tool_info_desc.get("Tool_Description", "")
        tool_code = tool_info_desc.get("code_snippet", "")
        tool_prompt_temp = f"""{tool_id}
-------------------------
Tool Name: {tool_nm}

Tool Description: {tool_desc}

Tool Code Snippet:
{tool_code}"""
        tool_prompt = tool_prompt + tool_prompt_temp + "\n\n\n\n"
    if not tools_info:
        log.warning("No tools available for onboarding.")
        tool_prompt = "No tools are available"
    log.info(f"Generated tool prompt with {len(tools_info)} tools.")
    return tool_prompt


async def react_agent_onboarding(agent_name: str,
                           agent_goal: str,
                           workflow_description: str,
                           model_name: str,
                           tools_id: list = [],
                           user_email_id: str = "",
                           only_return_prompt=False,
                           tag_ids=None
                           ):
    if not only_return_prompt:
        # Check if an agent with the same name already exists
        if await check_recycle_agent_name_if_exist(agentic_application_name=agent_name):
            log.error(f"Agentic Application with name {agent_name} already exists in recycle bin.")
            return {
                "message": "Agentic Application with the same name already exists in recycle bin.",
                "agentic_application_id": "",
                "agentic_application_name": agent_name,
                "agentic_application_type": "react_agent",
                "model_name": model_name,
                "created_by": user_email_id,
                "is_created": False
            }
        agent_check = await get_agents_by_id(agentic_application_name=agent_name,
                                        agentic_application_type='')

        if agent_check :
            status = {
                "message": "Agentic Application with the same name already exists.",
                "agentic_application_id": agent_check[0]["agentic_application_id"],
                "agentic_application_name": agent_check[0]["agentic_application_name"],
                "agentic_application_type": agent_check[0]["agentic_application_type"],
                "model_name": agent_check[0]["model_name"],
                "created_by": agent_check[0]["created_by"],
                "is_created": False
            }
            log.error(f"Agentic Application with name {agent_name} already exists.")
            return status

    tools_id = list(set(tools_id))
    # Validate tool IDs if provided
    if tools_id:
        val_tools_resp = await validate_tool_id(tools_id=tools_id)
        if "Error" in val_tools_resp:
            status = {
                "message": val_tools_resp,
                "agentic_application_id": "",
                "agentic_application_name": agent_name,
                "agentic_application_type": "react_agent",
                "model_name": model_name,
                "created_by": user_email_id,
                "is_created": False
            }
            log.error(f"Validation error: {val_tools_resp}")
            return status

    tools_info = await extract_tools_using_tools_id(tools_id)
    tool_prompt = generate_tool_prompt(tools_info)
    llm = load_model(model_name=model_name)
    react_system_prompt = await react_system_prompt_gen_func(agent_name=agent_name,
                                                       agent_goal=agent_goal,
                                                       workflow_description=workflow_description,
                                                       tool_prompt=tool_prompt,
                                                       llm=llm)
    if only_return_prompt:
        log.info("Returning only the system prompt for the React Agent.")
        return react_system_prompt

    # Insert agent data into the database
    agent_data = {
        "agentic_application_name": agent_name,
        "agentic_application_description": agent_goal,
        "agentic_application_workflow_description": workflow_description,
        "agentic_application_type": "react_agent",
        "model_name": model_name,
        "system_prompt": {"SYSTEM_PROMPT_REACT_AGENT": react_system_prompt},
        "tools_id": tools_id,
        "created_by": user_email_id,
        "tag_ids": tag_ids
    }
    agent_creation_status = await insert_into_agent_table(agent_data)
    log.info(f"React Agentic Application '{agent_name}' created successfully.")
    return agent_creation_status

async def react_critic_agent_onboarding(agent_name: str,
                           agent_goal: str,
                           workflow_description: str,
                           model_name: str,
                           tools_id: list = [],
                           user_email_id: str = "",
                           only_return_prompt=False,
                           tag_ids=None
                           ):
    if not only_return_prompt:
        # Check if an agent with the same name already exists
        agent_check = await get_agents_by_id(agentic_application_name=agent_name,
                                       agentic_application_type='')
        if agent_check:
            status = {
                "message": "Agentic Application with the same name already exists.",
                "agentic_application_id": agent_check[0]["agentic_application_id"],
                "agentic_application_name": agent_check[0]["agentic_application_name"],
                "agentic_application_type": agent_check[0]["agentic_application_type"],
                "model_name": agent_check[0]["model_name"],
                "created_by": agent_check[0]["created_by"],
                "is_created": False
            }
            log.error(f"Agentic Application with name {agent_name} already exists.")
            return status

    tools_id = list(set(tools_id))
    # Validate tool IDs if provided
    if tools_id:
        val_tools_resp = await validate_tool_id(tools_id=tools_id)
        if "Error" in val_tools_resp:
            status = {
                "message": val_tools_resp,
                "agentic_application_id": "",
                "agentic_application_name": agent_name,
                "agentic_application_type": "react_critic_agent",
                "model_name": model_name,
                "created_by": user_email_id,
                "is_created": False
            }
            log.error(f"Validation error: {val_tools_resp}")
            return status

    tools_info = await extract_tools_using_tools_id(tools_id)
    tool_prompt = generate_tool_prompt(tools_info)
    llm = load_model(model_name=model_name)
    react_critic_system_prompt = await executor_critic_builder(agent_name=agent_name,
                                                       agent_goal=agent_goal,
                                                       workflow_description=workflow_description,
                                                       tool_prompt=tool_prompt,
                                                       llm=llm)
    if only_return_prompt:
        log.info("Returning only the system prompt for the React Agent.")
        return react_critic_system_prompt

    # Insert agent data into the database
    agent_data = {
        "agentic_application_name": agent_name,
        "agentic_application_description": agent_goal,
        "agentic_application_workflow_description": workflow_description,
        "agentic_application_type": "react_critic_agent",
        "model_name": model_name,
        "system_prompt": react_critic_system_prompt["MULTI_AGENT_SYSTEM_PROMPTS_RE"],
        "tools_id": tools_id,
        "created_by": user_email_id,
        "tag_ids": tag_ids
    }
    agent_creation_status = await insert_into_agent_table(agent_data)
    log.info(f"React Agentic Application '{agent_name}' created successfully.")
    return agent_creation_status

async def get_agent_tool_config_by_agent_type(agentic_application_id, llm):
    from inference_meta import (
        build_react_agent_as_meta_agent_worker,
        build_planner_executor_critic_chains_for_meta_agent_worker,
        build_planner_executor_critic_agent_as_meta_agent_worker
    )
    agent_tools_config = {}
    # Retrieve agent details from the database
    agentic_app_info = await get_agents_by_id(agentic_application_id=agentic_application_id)
    agentic_app_info = agentic_app_info[0]

    agent_tools_config_master = {}
    agent_tools_config = {}
    agent_tools_config["SYSTEM_PROMPT"] = json.loads(agentic_app_info["system_prompt"])
    agent_tools_config["TOOLS_INFO"] = json.loads(agentic_app_info["tools_id"])
    agent_tools_config["agentic_application_description"] = agentic_app_info["agentic_application_description"]
    agent_name = agentic_app_info["agentic_application_name"].strip().lower().replace(" ", "_")
    agent_tools_config["AGENT_NAME"] = re.sub(r'[^a-z0-9_]', '', agent_name)

    if agentic_app_info['agentic_application_type'] == "react_agent":
        agent_tools_config["agentic_application_executor"] = await build_react_agent_as_meta_agent_worker(llm, agent_tools_config)
    elif agentic_app_info['agentic_application_type'] == "multi_agent":
        chains_and_tools_data = await build_planner_executor_critic_chains_for_meta_agent_worker(llm=llm, multi_agent_config=agent_tools_config)
        agent_tools_config["agentic_application_executor"] = await build_planner_executor_critic_agent_as_meta_agent_worker(llm=llm, chains_and_tools_data=chains_and_tools_data, agent_name=agent_name)
    agent_tools_config_master[agentic_app_info["agentic_application_name"]] = agent_tools_config

    log.info(f"Retrieved tool configuration for Agentic Application ID: {agentic_application_id}")
    return agent_tools_config_master

async def worker_agents_config_prompt(agentic_app_ids: list, llm):
    ### Config for the Worker Agents
    agent_configs = {}
    for agent_id in agentic_app_ids:
        agent_config_info = await get_agent_tool_config_by_agent_type(agentic_application_id=agent_id, llm=llm)
        agent_configs.update(agent_config_info)

    ### Worker Agents Prompt
    members = list(agent_configs.keys())

    worker_agents_prompt = ""
    for k, v in agent_configs.items():
        worker_agents_prompt += f"""Agentic Application Name: {v['AGENT_NAME']}\nAgentic Application Description: {v["agentic_application_description"]}\n\n"""

    log.info(f"Generated worker agents prompt for {len(agent_configs)} agents.")
    return agent_configs, worker_agents_prompt, members

async def meta_agent_onboarding(agent_name: str,
                           agent_goal: str,
                           workflow_description: str,
                           model_name: str,
                           agentic_app_ids: list = [],
                           user_email_id: str = "",
                           only_return_prompt=False,
                           tag_ids=None
                           ):
    if not tag_ids:
        tag_data= await get_tags_by_id_or_name(tag_name="General")
        tag_ids = tag_data.get("tag_id", [])
    if not only_return_prompt:
        # Check if an agent with the same name already exists
        if await check_recycle_agent_name_if_exist(agentic_application_name=agent_name):
            log.error(f"Agentic Application with name {agent_name} already exists in recycle bin.")
            return {
                "message": "Agentic Application with the same name already exists in recycle bin.",
                "agentic_application_id": "",
                "agentic_application_name": agent_name,
                "agentic_application_type": "meta_agent",
                "model_name": model_name,
                "created_by": user_email_id,
                "is_created": False
            }
        agent_check = await get_agents_by_id(agentic_application_name=agent_name,
                                       agentic_application_type='')
        if agent_check:
            status = {
                "message": "Agentic Application with the same name already exists.",
                "agentic_application_id": agent_check[0]["agentic_application_id"],
                "agentic_application_name": agent_check[0]["agentic_application_name"],
                "agentic_application_type": agent_check[0]["agentic_application_type"],
                "model_name": agent_check[0]["model_name"],
                "created_by": agent_check[0]["created_by"],
                "is_created": False
            }
            log.error(f"Agentic Application with name {agent_name} already exists.")
            return status

    # Validate Agent IDs if provided
    if agentic_app_ids:
        val_tools_resp = await validate_agent_id(agents_id=agentic_app_ids)
        if "Error" in val_tools_resp:
            status = {
                "message": val_tools_resp,
                "agentic_application_id": "",
                "agentic_application_name": agent_name,
                "agentic_application_type": "meta_agent",
                "model_name": model_name,
                "created_by": user_email_id,
                "is_created": False
            }
            log.error(f"Validation error: {val_tools_resp}")
            return status

    llm = load_model(model_name=model_name)
    agent_configs, worker_agents_prompt, members = await worker_agents_config_prompt(agentic_app_ids=agentic_app_ids, llm=llm)
    meta_agent_system_prompt = await meta_agent_system_prompt_gen_func(agent_name=agent_name,
                                                                 agent_goal=agent_goal,
                                                                 workflow_description=workflow_description,
                                                                 worker_agents_prompt=worker_agents_prompt,
                                                                 llm=llm)
    if only_return_prompt:
        log.info("Returning only the system prompt for the Meta Agent.")
        return meta_agent_system_prompt

    # Insert agent data into the database
    agent_data = {
        "agentic_application_name": agent_name,
        "agentic_application_description": agent_goal,
        "agentic_application_workflow_description": workflow_description,
        "agentic_application_type": "meta_agent",
        "model_name": model_name,
        "system_prompt": {"SYSTEM_PROMPT_META_AGENT": meta_agent_system_prompt},
        "tools_id": agentic_app_ids,
        "created_by": user_email_id,
        "tag_ids": tag_ids
    }
    agent_creation_status = await insert_into_agent_table_meta(agent_data)
    log.info(f"Meta Agentic Application '{agent_name}' created successfully.")
    return agent_creation_status

async def meta_agent_with_planner_onboarding(agent_name: str,
                           agent_goal: str,
                           workflow_description: str,
                           model_name: str,
                           agentic_app_ids: list = [],
                           user_email_id: str = "",
                           only_return_prompt=False,
                           tag_ids=None
                           ):
    if not tag_ids:
        tag_data= await get_tags_by_id_or_name(tag_name="General")
        tag_ids = tag_data.get("tag_id", [])
    if not only_return_prompt:
        # Check if an agent with the same name already exists
        if await check_recycle_agent_name_if_exist(agentic_application_name=agent_name):
            log.error(f"Agentic Application with name {agent_name} already exists in recycle bin.")
            return {
                "message": "Agentic Application with the same name already exists in recycle bin.",
                "agentic_application_id": "",
                "agentic_application_name": agent_name,
                "agentic_application_type": "planner_meta_agent",
                "model_name": model_name,
                "created_by": user_email_id,
                "is_created": False
            }
        agent_check = await get_agents_by_id(agentic_application_name=agent_name,
                                       agentic_application_type='')
        if agent_check:
            status = {
                "message": "Agentic Application with the same name already exists.",
                "agentic_application_id": agent_check[0]["agentic_application_id"],
                "agentic_application_name": agent_check[0]["agentic_application_name"],
                "agentic_application_type": agent_check[0]["agentic_application_type"],
                "model_name": agent_check[0]["model_name"],
                "created_by": agent_check[0]["created_by"],
                "is_created": False
            }
            log.error(f"Agentic Application with name {agent_name} already exists.")
            return status

    # Validate Agent IDs if provided
    if agentic_app_ids:
        val_tools_resp = await validate_agent_id(agents_id=agentic_app_ids)
        if "Error" in val_tools_resp:
            status = {
                "message": val_tools_resp,
                "agentic_application_id": "",
                "agentic_application_name": agent_name,
                "agentic_application_type": "planner_meta_agent",
                "model_name": model_name,
                "created_by": user_email_id,
                "is_created": False
            }
            log.error(f"Validation error: {val_tools_resp}")
            return status

    llm = load_model(model_name=model_name)
    agent_configs, worker_agents_prompt, members = await worker_agents_config_prompt(agentic_app_ids=agentic_app_ids, llm=llm)
    meta_agent_system_prompt = await onboard_meta_agent_with_planner(agent_name=agent_name,
                                                                 agent_goal=agent_goal,
                                                                 workflow_description=workflow_description,
                                                                 worker_agents_prompt=worker_agents_prompt,
                                                                 llm=llm)
    if only_return_prompt:
        log.info("Returning only the system prompt for the Meta Agent.")
        return meta_agent_system_prompt

    # Insert agent data into the database
    agent_data = {
        "agentic_application_name": agent_name,
        "agentic_application_description": agent_goal,
        "agentic_application_workflow_description": workflow_description,
        "agentic_application_type": "planner_meta_agent",
        "model_name": model_name,
        "system_prompt": meta_agent_system_prompt,
        "tools_id": agentic_app_ids,
        "created_by": user_email_id,
        "tag_ids": tag_ids
    }
    agent_creation_status = await insert_into_agent_table_meta(agent_data)
    log.info(f"Meta Agentic Application '{agent_name}' created successfully.")
    return agent_creation_status



async def react_multi_agent_onboarding(agent_name: str,
                           agent_goal: str,
                           workflow_description: str,
                           model_name: str,
                           tools_id: list = [],
                           user_email_id: str = "",
                           only_return_prompt=False,
                           tag_ids=None
                           ):
    if not only_return_prompt:
        # Check if an agent with the same name already exists
        if await check_recycle_agent_name_if_exist(agentic_application_name=agent_name):
            log.error(f"Agentic Application with name {agent_name} already exists in recycle bin.")
            return {
                "message": "Agentic Application with the same name already exists in recycle bin.",
                "agentic_application_id": "",
                "agentic_application_name": agent_name,
                "agentic_application_type": "multi_agent",
                "model_name": model_name,
                "created_by": user_email_id,
                "is_created": False
            }
        agent_check = await get_agents_by_id(agentic_application_name=agent_name,
                                       agentic_application_type='')
        if agent_check:
            status = {
                "message": "Agentic Application with the same name already exists.",
                "agentic_application_id": agent_check[0]["agentic_application_id"],
                "agentic_application_name": agent_check[0]["agentic_application_name"],
                "agentic_application_type": agent_check[0]["agentic_application_type"],
                "model_name": agent_check[0]["model_name"],
                "created_by": agent_check[0]["created_by"],
                "is_created": False
            }
            log.error(f"Agentic Application with name {agent_name} already exists.")
            return status

    tools_id = list(set(tools_id))
    # Validate tool IDs if provided
    if tools_id:
        val_tools_resp = await validate_tool_id(tools_id=tools_id)
        if "Error" in val_tools_resp:
            status = {
                "message": val_tools_resp,
                "agentic_application_id": "",
                "agentic_application_name": agent_name,
                "agentic_application_type": "multi_agent",
                "model_name": model_name,
                "created_by": user_email_id,
                "is_created": False
            }
            log.error(f"Validation error: {val_tools_resp}")
            return status

    tools_info = await extract_tools_using_tools_id(tools_id)
    tool_prompt = generate_tool_prompt(tools_info)
    llm = load_model(model_name=model_name)
    react_multi_system_prompt = await planner_executor_critic_builder(agent_name=agent_name,
                                                       agent_goal=agent_goal,
                                                       workflow_description=workflow_description,
                                                       tool_prompt=tool_prompt,
                                                       llm=llm)
    if only_return_prompt:
        log.info("Returning only the system prompt for the Multi-Agent React Agent.")
        return react_multi_system_prompt

    # Insert agent data into the database
    agent_data = {
        "agentic_application_name": agent_name,
        "agentic_application_description": agent_goal,
        "agentic_application_workflow_description": workflow_description,
        "agentic_application_type": "multi_agent",
        "model_name": model_name,
        "system_prompt": react_multi_system_prompt["MULTI_AGENT_SYSTEM_PROMPTS"],
        "tools_id": tools_id,
        "created_by": user_email_id,
        "tag_ids": tag_ids
    }
    agent_creation_status = await insert_into_agent_table(agent_data)
    log.info(f"Multi-Agent React Agentic Application '{agent_name}' created successfully.")
    return agent_creation_status


async def react_multi_pe_agent_onboarding(agent_name: str,
                           agent_goal: str,
                           workflow_description: str,
                           model_name: str,
                           tools_id: list = [],
                           user_email_id: str = "",
                           only_return_prompt=False,
                           tag_ids=None
                           ):
    if not only_return_prompt:
        # Check if an agent with the same name already exists
        agent_check = await get_agents_by_id(agentic_application_name=agent_name,
                                       agentic_application_type='')
        if agent_check:
            status = {
                "message": "Agentic Application with the same name already exists.",
                "agentic_application_id": agent_check[0]["agentic_application_id"],
                "agentic_application_name": agent_check[0]["agentic_application_name"],
                "agentic_application_type": agent_check[0]["agentic_application_type"],
                "model_name": agent_check[0]["model_name"],
                "created_by": agent_check[0]["created_by"],
                "is_created": False
            }
            log.error(f"Agentic Application with name {agent_name} already exists.")
            return status

    tools_id = list(set(tools_id))
    # Validate tool IDs if provided
    if tools_id:
        val_tools_resp = await validate_tool_id(tools_id=tools_id)
        if "Error" in val_tools_resp:
            status = {
                "message": val_tools_resp,
                "agentic_application_id": "",
                "agentic_application_name": agent_name,
                "agentic_application_type": "planner_executor_agent",
                "model_name": model_name,
                "created_by": user_email_id,
                "is_created": False
            }
            log.error(f"Validation error: {val_tools_resp}")
            return status

    tools_info = await extract_tools_using_tools_id(tools_id)
    tool_prompt = generate_tool_prompt(tools_info)
    llm = load_model(model_name=model_name)
    react_multi_system_prompt = await planner_executor_builder(agent_name=agent_name,
                                                       agent_goal=agent_goal,
                                                       workflow_description=workflow_description,
                                                       tool_prompt=tool_prompt,
                                                       llm=llm)
    if only_return_prompt:
        log.info("Returning only the system prompt for the Multi-Planner-Executor-Agent React Agent.")
        return react_multi_system_prompt

    # Insert agent data into the database
    agent_data = {
        "agentic_application_name": agent_name,
        "agentic_application_description": agent_goal,
        "agentic_application_workflow_description": workflow_description,
        "agentic_application_type": "planner_executor_agent",
        "model_name": model_name,
        "system_prompt": react_multi_system_prompt["MULTI_AGENT_SYSTEM_PROMPTS"],
        "tools_id": tools_id,
        "created_by": user_email_id,
        "tag_ids": tag_ids
    }
    agent_creation_status = await insert_into_agent_table(agent_data)
    log.info(f"Multi-Agent React Agentic Application '{agent_name}' created successfully.")
    return agent_creation_status


async def insert_chat_history_in_database(table_name,
                                 session_id,
                                 start_timestamp,
                                 end_timestamp,
                                 human_message,
                                 ai_message):
    """
    Inserts chat history into a PostgreSQL table.

    Args:
        table_name (str): The name of the table to insert into.
        session_id (str): The ID of the chat session.
        start_timestamp (str): The timestamp when the session started.
        end_timestamp (str): The timestamp when the session ended.
        human_message (str): The message from the human user.
        ai_message (str): The response from the AI.

    Returns:
        dict: Status of the operation, including success message or error details.
    """


    try:
        connection = await asyncpg.connect(
            host=POSTGRESQL_HOST,
            database=DATABASE,
            user=POSTGRESQL_USER,
            password=POSTGRESQL_PASSWORD
        )

        # Create the table if it doesn't already exist
        create_statement = f"""
        CREATE TABLE IF NOT EXISTS {table_name} (
            session_id TEXT,                          -- Stores session ID of the current session
            start_timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP, -- Timestamp for when the user message is created
            end_timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,   -- Timestamp for when the AI response is delivered
            human_message TEXT,                      -- Stores the message sent by the user
            ai_message TEXT                          -- Stores the response of the AI
        );
        """
        await connection.execute(create_statement)

        # Insert the chat history into the table
        insert_statement = f"""
        INSERT INTO {table_name} (
            session_id,
            start_timestamp,
            end_timestamp,
            human_message,
            ai_message
        ) VALUES ($1, $2, $3, $4, $5)
        """
        await connection.execute(
            insert_statement,
            session_id,
            start_timestamp,
            end_timestamp,
            human_message,
            ai_message
        )

        log.info(f"Chat history inserted successfully into {table_name} for session {session_id}.")
    except asyncpg.PostgresError as e:
        log.error(f"Database error: {e}")
        return {"status": "error", "message": str(e)}

    finally:
        await connection.close()


async def get_long_term_memory_from_database(table_name, session_id, conversation_limit=30):
    """
    Retrieves the most recent chat history for a given session from a PostgreSQL table.

    Args:
        table_name (str): The name of the table to query.
        session_id (str): The ID of the chat session.
        conversation_limit (int, optional): The maximum number of conversations to retrieve. Defaults to 30.

    Returns:
        list of dict: A list of chat history records sorted by end_timestamp in descending order.
    """


    try:
        connection = await asyncpg.connect(
            host=POSTGRESQL_HOST,
            database=DATABASE,
            user=POSTGRESQL_USER,
            password=POSTGRESQL_PASSWORD
        )

       # Check if the table exists
        check_table_query = """
        SELECT EXISTS (
            SELECT 1
            FROM information_schema.tables
            WHERE table_name = $1
        );
        """
        table_exists = await connection.fetchval(check_table_query, table_name)

        if table_exists:

            # Query to retrieve the most recent chat history for the session
            query = f"""
            SELECT session_id, start_timestamp, end_timestamp, human_message, ai_message
            FROM {table_name}
            WHERE session_id = $1
            ORDER BY end_timestamp DESC
            LIMIT $2
            """
            records = await connection.fetch(query, session_id, conversation_limit)



            # Convert the retrieved records into a list of dictionaries
            chat_history = [
                {
                    "session_id": row["session_id"],
                    "start_timestamp": row["start_timestamp"],
                    "end_timestamp": row["end_timestamp"],
                    "human_message": row["human_message"],
                    "ai_message": row["ai_message"]
                }
                for row in records
            ]

            log.info(f"Retrieved {len(chat_history)} records from {table_name} for session {session_id}.")
            return chat_history

    except asyncpg.PostgresError as e:
        log.error(f"Database error: {e}")
        return {"status": "error", "message": str(e)}

    finally:
        await connection.close()


async def delete_by_session_id_from_database(table_name, session_id):
    """
    Deletes records from a PostgreSQL table by session_id.

    Args:
        table_name (str): The name of the table.
        session_id (str): The session ID to delete records for.

    Returns:
        bool: True if deletion was successful, False otherwise.
    """

    try:
        connection = await asyncpg.connect(
            host=POSTGRESQL_HOST,
            database=DATABASE,
            user=POSTGRESQL_USER,
            password=POSTGRESQL_PASSWORD
        )

        # Delete query
        delete_query = f"""
        DELETE FROM {table_name} WHERE session_id = $1;
        """
        result = await connection.execute(delete_query, session_id)

        # Result looks like: "DELETE <n_rows>"
        rows_deleted = int(result.split()[-1])
        log.info(f"Records deleted successfully from {table_name} for session {session_id}.")
        return rows_deleted > 0

    except asyncpg.PostgresError as e:
        log.error(f"Database error: {e}")
        return False

    finally:
        await connection.close()

async def delete_chat_history_by_session_id(agentic_application_id, session_id):
    """
    Deletes the conversation history from PostgreSQL for a specific session ID.
    """
    connection = None
    try:
        # Construct dynamic table and thread ID
        table_name = f'table_{agentic_application_id.replace("-", "_")}'
        thread_id = f"{table_name}_{session_id}"

        # Connect to the PostgreSQL database
        connection = await asyncpg.connect(
            host=POSTGRESQL_HOST,
            database=DATABASE,
            user=POSTGRESQL_USER,
            password=POSTGRESQL_PASSWORD
        )

        # Start a transaction block
        async with connection.transaction():
            # Delete from checkpoints and writes tables
            await connection.execute("DELETE FROM checkpoints WHERE thread_id = $1", thread_id)
            await connection.execute("DELETE FROM checkpoint_blobs WHERE thread_id = $1", thread_id)
            await connection.execute("DELETE FROM checkpoint_writes WHERE thread_id = $1", thread_id)

            # If necessary, delete additional related data
            await delete_by_session_id_from_database(table_name=table_name, session_id=session_id)

        log.info(f"Memory history deleted successfully for session {session_id} in table {table_name}.")
        return {"status": "success", "message": "Memory history deleted successfully."}

    except asyncpg.PostgresError as e:
        return {"status": "error", "message": f"PostgreSQL error occurred: {e}"}
    except Exception as e:
        log.error(f"Error deleting memory history: {e}")
        return {"status": "error", "message": f"Unknown error occurred: {e}"}
    finally:
        if connection:
            await connection.close()

 

async def get_all_chat_sessions():
    try:
        # PostgreSQL connection settings (replace with your real credentials)
        connection = await asyncpg.connect(
            host=POSTGRESQL_HOST,
            database=DATABASE,
            user=POSTGRESQL_USER,
            password=POSTGRESQL_PASSWORD
        )

        res = await connection.fetch("SELECT DISTINCT thread_id FROM checkpoints;")
        data = [dict(record) for record in res]
        log.info(f"Retrieved {len(data)} unique chat sessions from the database.")
        return data
    except Exception as e:
        log.error(f"An error occurred while retrieving chat sessions: {e}")
        return []
    finally:
        await connection.close()

async def update_latest_query_response_with_tag(agentic_application_id, session_id, message_type="ai", start_tag="[liked_by_user:]", end_tag="[:liked_by_user]"):
    """
    Updates the latest query response with the given session ID by adding or removing the specified tags around the ai_message or human_message.

    Args:
        agentic_application_id (str): The ID of the agentic application.
        session_id (str): The session ID to identify the conversation.
        message_type (str): The type of message to update ('ai' or 'human'). Defaults to 'ai'.
        start_tag (str): The starting tag to add or remove in the message. Defaults to '[liked_by_user:]'.
        end_tag (str): The ending tag to add or remove in the message. Defaults to '[:liked_by_user]'.

    Returns:
        bool: True if the message was liked, False if the like was removed, None if the update was not done.
    """
    # Table name based on agentic_application_id
    table_name = f"table_{agentic_application_id}".replace("-", "_")

    try:
        connection = await asyncpg.connect(
            host=POSTGRESQL_HOST,
            database=DATABASE,
            user=POSTGRESQL_USER,
            password=POSTGRESQL_PASSWORD
        )


        # Determine the column to update based on message_type
        message_type = message_type.lower()
        if message_type == "human":
            message_column = "human_message"
        elif message_type == "ai":
            message_column = "ai_message"
        else:
            return None

        # Fetch latest message for the session
        query = f"""
        SELECT {message_column}, end_timestamp
        FROM {table_name}
        WHERE session_id = $1
        ORDER BY end_timestamp DESC
        LIMIT 1
        """
        result = await connection.fetchrow(query, session_id)


        if result:
            message, end_timestamp = result

            # Check if the tags are already present
            if message.startswith(start_tag) and message.endswith(end_tag):
                # Remove the tags
                updated_message = message[len(start_tag):-len(end_tag)]
                update_status = False
            else:
                # Add the tags
                updated_message = f"{start_tag}{message}{end_tag}"
                update_status = True

            # Use session_id and end_timestamp as composite key for update
            update_query = f"""
            UPDATE {table_name}
            SET {message_column} = $1
            WHERE session_id = $2 AND end_timestamp = $3
            """
            await connection.execute(update_query, updated_message.strip(), session_id, end_timestamp)

            log.info(f"Updated {message_type} message for session {session_id} in table {table_name}.")
            return update_status

        log.warning(f"No message found for session {session_id} in table {table_name}.")
        return None

    except Exception as e:
        log.error(f"Error updating query response: {e}")
        return None

    finally:
        await connection.close()



# Tags Table

async def create_tags_table_if_not_exists(table_name="tags_table"):
    connection = await asyncpg.connect(
            host=POSTGRESQL_HOST,
            database=DATABASE,
            user=POSTGRESQL_USER,
            password=POSTGRESQL_PASSWORD
        )
    try:
        create_statement = f"""
        CREATE TABLE IF NOT EXISTS {table_name} (
            tag_id TEXT PRIMARY KEY,
            tag_name TEXT UNIQUE NOT NULL,
            created_by TEXT NOT NULL
        )
        """
        await connection.execute(create_statement)

        # Insert the 'Common' tag if the table is newly created
        default_tags = [
            'General', 'Healthcare & Life Sciences', 'Finance & Banking', 'Education & Training', 'Retail & E-commerce',
            'Insurance', 'Logistics', 'Utilities', 'Travel and Hospitality', 'Agri Industry', 'Manufacturing', 'Metals and Mining',
        ]

        for default_tag in default_tags:
            insert_query = f"""
            INSERT INTO {table_name} (tag_id, tag_name, created_by)
            VALUES ($1, $2, 'system@infosys.com')
            ON CONFLICT (tag_id) DO NOTHING
            """
            await connection.execute(insert_query, str(uuid.uuid4()), default_tag)

        log.info(f"Table '{table_name}' created successfully or already exists.")
    except asyncpg.PostgresError as e:
        log.error(f"Error creating table: {e}")
    finally:
        await connection.close()

async def insert_into_tags_table(tag_data, table_name="tags_table"):
    """
    Inserts data into the tags table.

    Args:
        tag_data (dict): A dictionary containing the tag data to insert.
        table_name (str): Name of the table to insert data into. Defaults to 'tags_table'.

    Returns:
        dict: Status of the operation, including success message or error details.
    """
    # Generate tag_id if not provided
    if not tag_data.get("tag_id", None):
        tag_data["tag_id"] = str(uuid.uuid4())

    connection = await asyncpg.connect(
            host=POSTGRESQL_HOST,
            database=DATABASE,
            user=POSTGRESQL_USER,
            password=POSTGRESQL_PASSWORD
        )


    try:

        # Build SQL INSERT statement
        insert_statement = f"""
        INSERT INTO {table_name} (
            tag_id,
            tag_name,
            created_by
        ) VALUES ($1, $2, $3)
        """

        # Extract values from tag_data for insertion
        values = (
            tag_data.get("tag_id"),
            tag_data.get("tag_name").strip(),
            tag_data.get("created_by")
        )

        # Execute the insert statement
        await connection.execute(insert_statement, *values)

        # Return success status
        status = {
            "message": f"Successfully inserted tag with tag_id: {tag_data.get('tag_id', '')}",
            "tag_id": f"{tag_data.get('tag_id', '')}",
            "tag_name": f"{tag_data.get('tag_name', '')}",
            "created_by": f"{tag_data.get('created_by', '')}",
            "is_created": True
        }

    except asyncpg.UniqueViolationError as e:
        # Handle unique constraint violations (e.g., primary key or unique column constraint)
        status = {
            "message": f"Unique violation error inserting data into '{table_name}': {e}",
            "tag_id": "",
            "tag_name": f"{tag_data.get('tag_name', '')}",
            "created_by": f"{tag_data.get('created_by', '')}",
            "is_created": False
        }

    except Exception as e:
        # Handle general database errors
        status = {
            "message": f"Error inserting data into '{table_name}' table: {e}",
            "tag_id": "",
            "tag_name": f"{tag_data.get('tag_name', '')}",
            "created_by": f"{tag_data.get('created_by', '')}",
            "is_created": False
        }

    finally:
        # Ensure the connection is properly closed
        await connection.close()
    log.info(f"Tag insertion status: {status['message']}")
    return status

async def get_tags(tag_table_name="tags_table"):
    """
    Retrieves tags from the tags table.

    Args:
        tag_table_name (str): The name of the tags table. Defaults to 'tags_table'.

    Returns:
        list: A list of tags from the tags table, represented as dictionaries.
    """
    connection = await asyncpg.connect(
            host=POSTGRESQL_HOST,
            database=DATABASE,
            user=POSTGRESQL_USER,
            password=POSTGRESQL_PASSWORD
        )


    try:

        # Build and execute the SELECT query
        query = f"""
        SELECT *
        FROM {tag_table_name}
        """

        # Fetch all results and get column names
        rows = await connection.fetch(query)

        # Convert each row into a dictionary directly
        result_dict = [dict(row) for row in rows]

        log.info(f"Retrieved {len(result_dict)} tags from the '{tag_table_name}' table.")
        return result_dict

    except asyncpg.PostgresError as e:
        log.error(f"Error retrieving tags: {e}")
        return []

    finally:
        # Ensure the connection is properly closed
        await connection.close()

async def get_tags_by_id_or_name(tag_id=None, tag_name=None, tag_table_name="tags_table"):
    """
    Retrieves tags from the database based on provided parameters.

    Args:
        tag_table_name (str): Name of the tags table.
        tag_id (str, optional): Tag ID.
        tag_name (str, optional): Tag name.

    Returns:
        list: A list of dictionaries representing the retrieved tags, or an empty list on error.
    """
    connection = await asyncpg.connect(
            host=POSTGRESQL_HOST,
            database=DATABASE,
            user=POSTGRESQL_USER,
            password=POSTGRESQL_PASSWORD
        )

    try:


        # Start building the base query
        query = f"SELECT * FROM {tag_table_name}"
        where_clauses = []
        params = []

        # Add filters to the WHERE clause
        idx = 1
        if tag_id:
            where_clauses.append(f"tag_id = ${idx}")
            params.append(tag_id)
            idx += 1
        if tag_name:
            where_clauses.append(f"tag_name = ${idx}")
            params.append(tag_name)

        # Append WHERE clause to the query if filters are provided
        if where_clauses:
            query += " WHERE " + " AND ".join(where_clauses)


        # Execute the query with parameters
        rows = await connection.fetch(query, *params)

        # Convert rows into a list of dictionaries
        results_as_dicts = [dict(row) for row in rows]

        log.info(f"Retrieved tags: {results_as_dicts}")
        # Return the first result, or an empty dictionary if no results
        return results_as_dicts[0] if results_as_dicts else {}

    except asyncpg.PostgresError as e:
        log.error(f"Error retrieving tags: {e}")
        return {}  # Return an empty dictionary in case of an error

    finally:
        await connection.close()

async def update_tag_name_by_id_or_name(tag_id=None, tag_name=None, new_tag_name=None, created_by=None, table_name="tags_table"):
    """
    Updates the tag name in the tags table if the given tag ID or tag name is present and created by the given user ID.

    Args:
        tag_id (str, optional): The ID of the tag to update.
        tag_name (str, optional): The name of the tag to update.
        new_tag_name (str): The new name for the tag.
        created_by (str): The ID of the user performing the update.
        table_name (str): The name of the tags table. Defaults to 'tags_table'.

    Returns:
        dict: Status of the operation, including success message or error details.
    """
    if not created_by:
        return {"message": "User ID is required.", "is_updated": False}

    connection = await asyncpg.connect(
            host=POSTGRESQL_HOST,
            database=DATABASE,
            user=POSTGRESQL_USER,
            password=POSTGRESQL_PASSWORD
        )


    try:


        # Start building the base query
        update_statement = f"UPDATE {table_name} SET tag_name = $1"
        where_clauses = []
        params = [new_tag_name]

        # Add filters to the WHERE clause
        idx = 2
        if tag_id:
            where_clauses.append(f"tag_id = ${idx}")
            params.append(tag_id)
            idx += 1
        if tag_name:
            where_clauses.append(f"tag_name = ${idx}")
            params.append(tag_name)
            idx += 1

        where_clauses.append(f"created_by = ${idx}")
        params.append(created_by)

        # Append WHERE clause to the query if filters are provided
        if where_clauses:
            update_statement += " WHERE " + " AND ".join(where_clauses)


        # Execute the update statement
        result = await connection.execute(update_statement, *params)

        # If no rows were updated, result will be an empty string, so check the result accordingly
        if result.startswith("UPDATE 0"):
            status = {
                "message": f"No tag found with tag_id: {tag_id} or tag_name: {tag_name} created by created_by: {created_by}",
                "tag_id": tag_id,
                "tag_name": tag_name,
                "is_updated": False
            }
        else:
            status = {
                "message": f"Successfully updated tag with tag_id: {tag_id} or tag_name: {tag_name}",
                "tag_id": tag_id,
                "tag_name": tag_name,
                "is_updated": True
            }

    except asyncpg.PostgresError as e:
        # Handle general database errors
        status = {
            "message": f"Error updating tag in '{table_name}' table: {e}",
            "tag_id": tag_id,
            "tag_name": tag_name,
            "is_updated": False
        }

    finally:
        # Ensure the connection is properly closed
        await connection.close()

    log.info(f"Tag update status: {status['message']}")
    return status

async def delete_tag_by_id_or_name(tag_id=None, tag_name=None, created_by=None, table_name="tags_table"):
    """
    Deletes a tag from the tags table if the given tag ID or tag name is present and created by the given user ID.

    Args:
        tag_id (str, optional): The ID of the tag to delete.
        tag_name (str, optional): The name of the tag to delete.
        created_by (str): The ID of the user performing the deletion.
        table_name (str): The name of the tags table. Defaults to 'tags_table'.

    Returns:
        dict: Status of the operation, including success message or error details.
    """
    if not created_by:
        return {"message": "User ID is required.", "is_deleted": False}

    connection = await asyncpg.connect(
            host=POSTGRESQL_HOST,
            database=DATABASE,
            user=POSTGRESQL_USER,
            password=POSTGRESQL_PASSWORD
        )

    try:
        # Start building the base query
        delete_statement = f"DELETE FROM {table_name}"
        where_clauses = []
        params = []

        # Add filters to the WHERE clause
        idx = 1
        if tag_id:
            where_clauses.append(f"tag_id = ${idx}")
            params.append(tag_id)
            idx += 1
        if tag_name:
            where_clauses.append(f"tag_name = ${idx}")
            params.append(tag_name)
            idx += 1

        where_clauses.append(f"created_by = ${idx}")
        params.append(created_by)

        # Append WHERE clause to the query if filters are provided
        if where_clauses:
            delete_statement += " WHERE " + " AND ".join(where_clauses)



        if await is_tag_in_use(tag_id=tag_id, tag_name=tag_name):
            log.warning(f"Tag with tag_id: {tag_id} or tag_name: {tag_name} is in use by an agent or a tool.")
            return {
                "message": f"Cannot delete tag, it is begin used by an agent or a tool",
                "tag_id": tag_id,
                "tag_name": tag_name,
                "is_deleted": False
            }

        # Execute the delete statement
        result = await connection.execute(delete_statement, *params)


        # Check if any row was deleted
        if result.startswith("UPDATE 0"):
            status = {
                "message": f"No tag found with tag_id: {tag_id} or tag_name: {tag_name} created by user_id: {created_by}",
                "tag_id": tag_id,
                "tag_name": tag_name,
                "is_deleted": False
            }
        else:
            status = {
                "message": f"Successfully deleted tag with tag_id: {tag_id} or tag_name: {tag_name}",
                "tag_id": tag_id,
                "tag_name": tag_name,
                "is_deleted": True
            }

    except asyncpg.PostgresError as e:
        # Handle general database errors
        status = {
            "message": f"Error deleting tag from '{table_name}' table: {e}",
            "tag_id": tag_id,
            "tag_name": tag_name,
            "is_deleted": False
        }

    finally:
        # Ensure the connection is properly closed
        await connection.close()

    log.info(f"Tag deletion status: {status['message']}")  
    return status



# Tags Helper functions

async def clear_tags(tool_id=None, agent_id=None, tool_tag_mapping_table_name="tag_tool_mapping_table", agent_tag_mapping_table_name="tag_agentic_app_mapping_table"):
    """
    Clears all tags associated with a given tool ID or agent ID.

    Args:
        tool_id (str, optional): The ID of the tool. Defaults to None.
        agent_id (str, optional): The ID of the agent. Defaults to None.
        tool_tag_mapping_table_name (str): The name of the tool tag mapping table. Defaults to 'tag_tool_mapping_table'.
        agent_tag_mapping_table_name (str): The name of the agent tag mapping table. Defaults to 'tag_agentic_app_mapping_table'.

    Returns:
        bool: True if the operation was successful, False otherwise.
    """
    if not tool_id and not agent_id:
        log.error("Either tool_id or agent_id must be provided.")
        return False

    connection = await asyncpg.connect(
            host=POSTGRESQL_HOST,
            database=DATABASE,
            user=POSTGRESQL_USER,
            password=POSTGRESQL_PASSWORD
        )
    try:

        async with connection.transaction():
            if tool_id:
                # Clear tags for the given tool_id
                query = f"DELETE FROM {tool_tag_mapping_table_name} WHERE tool_id = $1"
                await connection.execute(query, tool_id)
            elif agent_id:
            # Clear tags for the given agent_id
                query = f"DELETE FROM {agent_tag_mapping_table_name} WHERE agentic_application_id = $1"
                await connection.execute(query, agent_id)

            log.info(f"Cleared tags for {'tool_id' if tool_id else 'agent_id'}: {tool_id or agent_id} in the database.")
            return True

    except asyncpg.PostgresError as e:
        log.error(f"Error clearing tags: {e}")
        return False

    finally:
        await connection.close()


async def is_tag_in_use(tag_id=None, tag_name=None, tag_table_name="tags_table", tool_tag_mapping_table_name="tag_tool_mapping_table", agent_tag_mapping_table_name="tag_agentic_app_mapping_table"):
    """
    Checks if a given tag ID or tag name is being used by any agent or tool.

    Args:
        tag_id (str, optional): The ID of the tag. Defaults to None.
        tag_name (str, optional): The name of the tag. Defaults to None.
        tag_table_name (str): The name of the tags table. Defaults to 'tags_table'.
        tool_tag_mapping_table_name (str): The name of the tool tag mapping table. Defaults to 'tag_tool_mapping_table'.
        agent_tag_mapping_table_name (str): The name of the agent tag mapping table. Defaults to 'tag_agentic_app_mapping_table'.

    Returns:
        bool: True if the tag is in use, False otherwise.
    """
    if not tag_id and not tag_name:
        log.error("Either tag_id or tag_name must be provided.")
        return False

    connection = await asyncpg.connect(
            host=POSTGRESQL_HOST,
            database=DATABASE,
            user=POSTGRESQL_USER,
            password=POSTGRESQL_PASSWORD
        )

    try:

        # Get the tag_id if tag_name is provided
        if tag_name:
            query = f"SELECT tag_id FROM {tag_table_name} WHERE tag_name = $1"
            result = await connection.execute(query, tag_name)
            if result:
                tag_id = result[0]
            else:
                return False

        # Check if the tag_id is used in the tool_tag_mapping_table
        query1 = f"SELECT 1 FROM {tool_tag_mapping_table_name} WHERE tag_id = $1 LIMIT 1"
        row1 = await connection.fetchrow(query1, tag_id)
        if row1:
            return True

        # Check if the tag_id is used in the agent_tag_mapping_table
        query2 = f"SELECT 1 FROM {agent_tag_mapping_table_name} WHERE tag_id = $1 LIMIT 1"
        row2 = await connection.fetchrow(query2, tag_id)
        if row2:
            log.info(f"Tag with tag_id: {tag_id} is in use by an agent or a tool.")
            return True

        log.info(f"Tag with tag_id: {tag_id} is not in use by any agent or tool.")
        return False

    except asyncpg.PostgresError as e:
        log.error(f"Error checking tag usage: {e}")
        return False

    finally:
        await connection.close()

async def get_tags_as_dict_by_id(tags_table="tags_table"):
    """
    Fetches all tags from the specified tags table and returns them as a dictionary
    keyed by tag_id.

    Args:
        tags_table (str): The name of the table containing tag records. Defaults to "tags_table".

    Returns:
        dict: A dictionary where each key is a tag_id and the value is a dictionary
              of the tag's details (column names as keys).
              Returns an empty dictionary if no tags are found or on error.
    """
    connection = None
    tags_dict = {}
    try:
        connection = await asyncpg.connect(
            host=POSTGRESQL_HOST,
            database=DATABASE,
            user=POSTGRESQL_USER,
            password=POSTGRESQL_PASSWORD
        )
        
        # This query assumes the old schema with 'tag_id' exists.
        query = f"SELECT * FROM {tags_table}"
        rows = await connection.fetch(query)

        for row in rows:
            tag_id = row['tag_id']
            tags_dict[tag_id] = dict(row)
        
        log.info(f"Fetched {len(tags_dict)} tags.")
        return tags_dict

    except Exception as e:
        log.error(f"Error fetching tags: {e}")
        return {}
    finally:
        if connection:
            await connection.close()


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


# Tags and Tools mapping

async def create_tag_tool_mapping_table_if_not_exists(table_name="tag_tool_mapping_table"):

    connection = await asyncpg.connect(
            host=POSTGRESQL_HOST,
            database=DATABASE,
            user=POSTGRESQL_USER,
            password=POSTGRESQL_PASSWORD
        )
    try:

        create_statement = f"""
        CREATE TABLE IF NOT EXISTS {table_name} (
            tag_id TEXT,
            tool_id TEXT,
            FOREIGN KEY(tag_id) REFERENCES tags_table(tag_id) ON DELETE RESTRICT,
            FOREIGN KEY(tool_id) REFERENCES tool_table(tool_id) ON DELETE CASCADE,
            UNIQUE(tag_id, tool_id)
        )
        """
        await connection.execute(create_statement)
        log.info(f"Table '{table_name}' created successfully or already exists.")
    except asyncpg.PostgresError as e:
        log.error(f"Error creating table: {e}")
    finally:
        await connection.close()

async def insert_into_tag_tool_mapping(tag_ids, tool_id, table_name="tag_tool_mapping_table"):
    """
    Inserts mappings between tag(s) and a tool into the tag_tool_mapping_table.

    Args:
        tag_ids (str or list): The ID(s) of the tag(s).
        tool_id (str): The ID of the tool.
        table_name (str): The name of the mapping table. Defaults to 'tag_tool_mapping_table'.

    Returns:
        dict: Status of the operation, including success message or error details.
    """
    if isinstance(tag_ids, str):
        tag_ids = [tag_ids]

    connection = await asyncpg.connect(
            host=POSTGRESQL_HOST,
            database=DATABASE,
            user=POSTGRESQL_USER,
            password=POSTGRESQL_PASSWORD
        )

    inserted_tags = []
    failed_tags = []

    try:

        # Build SQL INSERT statement
        insert_statement = f"""
        INSERT INTO {table_name} (
            tag_id,
            tool_id
        ) VALUES ($1, $2)
        ON CONFLICT (tag_id, tool_id) DO NOTHING
        """

        # Execute the insert statement for each tag_id
        for tag_id in tag_ids:
            try:
                await connection.execute(insert_statement, tag_id, tool_id)
                inserted_tags.append(tag_id)
            except asyncpg.UniqueViolationError as e:
                failed_tags.append((tag_id, str(e)))

        # Return status
        status = {
            "message": f"Inserted mappings for tag_ids: {inserted_tags}. Failed for tag_ids: {failed_tags}",
            "inserted_tag_ids": inserted_tags,
            "failed_tag_ids": failed_tags,
            "tool_id": tool_id,
            "is_created": len(inserted_tags) > 0
        }

    except asyncpg.PostgresError as e:
        # Handle general database errors
        status = {
            "message": f"Error inserting data into '{table_name}' table: {e}",
            "tag_ids": tag_ids,
            "tool_id": tool_id,
            "is_created": False
        }

    finally:
        # Ensure the connection is properly closed
        await connection.close()

    log.info(f"Tag-Tool mapping insertion status: {status['message']}")   
    return status

async def delete_from_tag_tool_mapping(tag_ids, tool_id, table_name="tag_tool_mapping_table"):
    """
    Deletes mappings between tag(s) and a tool from the tag_tool_mapping_table.

    Args:
        tag_ids (str or list): The ID(s) of the tag(s).
        tool_id (str): The ID of the tool.
        table_name (str): The name of the mapping table. Defaults to 'tag_tool_mapping_table'.

    Returns:
        dict: Status of the operation, including success message or error details.
    """
    if isinstance(tag_ids, str):
        tag_ids = [tag_ids]

    # Full path to the database file
    connection = await asyncpg.connect(
            host=POSTGRESQL_HOST,
            database=DATABASE,
            user=POSTGRESQL_USER,
            password=POSTGRESQL_PASSWORD
        )

    try:

        # Build SQL DELETE statement
        delete_statement = f"""
        DELETE FROM {table_name}
        WHERE tag_id = $1 AND tool_id = $2
        """

        # Execute the delete statement for each tag_id
        for tag_id in tag_ids:
            result = await connection.execute(delete_statement,tag_id, tool_id)

        # Check if any row was deleted
        if result == "Delete 0":
            status = {
                "message": f"No mapping found between tag_ids: {tag_ids} and tool_id: {tool_id}",
                "tag_ids": tag_ids,
                "tool_id": tool_id,
                "is_deleted": False
            }
        else:
            status = {
                "message": f"Successfully deleted mappings between tag_ids: {tag_ids} and tool_id: {tool_id}",
                "tag_ids": tag_ids,
                "tool_id": tool_id,
                "is_deleted": True
            }

    except asyncpg.PostgresError as e:
        # Handle general database errors
        status = {
            "message": f"Error deleting mapping from '{table_name}' table: {e}",
            "tag_ids": tag_ids,
            "tool_id": tool_id,
            "is_deleted": False
        }

    finally:
        # Ensure the connection is properly closed
        await connection.close()

    log.info(f"Tag-Tool mapping deletion status: {status['message']}")
    return status

async def get_tool_tags_from_mapping_as_dict(tags_dict=None, mapping_table="tag_tool_mapping_table"):
    """
    Fetches the mapping between tools and their associated tags from the specified mapping table.

    Args:
        tags_dict (dict, optional): A pre-fetched dictionary of all tags, where keys are tag IDs and values are tag details.
                                    If not provided, the function will fetch it using get_tags_as_dict_by_id().
        mapping_table (str): The name of the table containing the tool-to-tag mappings. Defaults to "tag_tool_mapping_table".

    Returns:
        dict: A dictionary where each key is a tool_id and the value is a list of tag detail dictionaries associated with that tool.
    """
    connection = None
    tool_to_tags_map = {}
    try:
        connection = await asyncpg.connect(
            host=POSTGRESQL_HOST,
            database=DATABASE,
            user=POSTGRESQL_USER,
            password=POSTGRESQL_PASSWORD
        )

        # If a dictionary of all tags wasn't provided, fetch it now.
        if tags_dict is None:
            tags_dict = await get_tags_as_dict_by_id()
        
        if not tags_dict:
            log.warning("No tags available to build the tool-tag mapping.")
            return {}

        query = f"SELECT * FROM {mapping_table}"
        rows = await connection.fetch(query)

        for row in rows:
            tool_id = row['tool_id']
            tag_id = row['tag_id']
            
            # Get the full tag details from the pre-fetched dictionary
            tag_details = tags_dict.get(tag_id)
            
            if tag_details:
                if tool_id not in tool_to_tags_map:
                    tool_to_tags_map[tool_id] = []
                tool_to_tags_map[tool_id].append(tag_details)
        
        log.info(f"Built tag mapping for {len(tool_to_tags_map)} tools.")
        return tool_to_tags_map

    except Exception as e:
        log.error(f"Error building tool-tag map: {e}")
        return {}
    finally:
        if connection:
            await connection.close()

async def get_tags_by_tool(tool_id=None, tool_name=None, tag_table_name="tags_table", mapping_table_name="tag_tool_mapping_table", tool_table_name="tool_table"):
    """
    Retrieves tags associated with a given tool ID or tool name.

    Args:
        tool_id (str, optional): The ID of the tool.
        tool_name (str, optional): The name of the tool.
        tag_table_name (str): The name of the tags table. Defaults to 'tags_table'.
        mapping_table_name (str): The name of the mapping table. Defaults to 'tag_tool_mapping_table'.
        tool_table_name (str): The name of the tool table. Defaults to 'tool_table'.

    Returns:
        list: A list of tags associated with the tool, represented as dictionaries.
    """
    # Full path to the database file
    connection = await asyncpg.connect(
            host=POSTGRESQL_HOST,
            database=DATABASE,
            user=POSTGRESQL_USER,
            password=POSTGRESQL_PASSWORD
        )
    try:

        # Build the query to get tag_ids
        query = f"""
        SELECT m.tag_id
        FROM {mapping_table_name} m
        JOIN {tool_table_name} tl ON m.tool_id = tl.tool_id
        """
        where_clauses = []
        params = []

        # Add filters to the WHERE clause
        idx = 1
        if tool_id:
            where_clauses.append(f"tl.tool_id = ${idx}")
            params.append(tool_id)
            idx += 1
        if tool_name:
            where_clauses.append(f"tl.tool_name = ${idx}")
            params.append(tool_name)

        # Append WHERE clause to the query if filters are provided
        if where_clauses:
            query += " WHERE " + " AND ".join(where_clauses)

        # Execute the query with parameters
        rows = await connection.fetch(query, *params)

        # Fetch all tag_ids
        tag_ids = [row['tag_id'] for row in rows]

        # If no tag_ids found, return an empty list
        if not tag_ids:
            log.info(f"No tags found for tool_id: {tool_id} or tool_name: {tool_name}.")
            return []


        query = f"""
        SELECT *
        FROM {tag_table_name}
        WHERE tag_id = ANY($1)
        """

        # Execute the query with tag_ids as parameters
        rows = await connection.fetch(query, tag_ids)

        results_as_dicts = [dict(row) for row in rows]
        log.info(f"Retrieved {len(results_as_dicts)} tags for tool_id: {tool_id} or tool_name: {tool_name}.")
        return results_as_dicts

    except asyncpg.PostgresError as e:
        log.error(f"Error retrieving tags: {e}")
        return []

    finally:
        await connection.close()

async def get_tools_by_tag(tag_ids=None, tag_names=None, tool_table_name="tool_table", mapping_table_name="tag_tool_mapping_table", tag_table_name="tags_table"):
    """
    Retrieves tools associated with given tag IDs or tag names.

    Args:
        tag_ids (list, optional): A list of tag IDs or a single tag ID.
        tag_names (list, optional): A list of tag names or a single tag name.
        tool_table_name (str): The name of the tool table. Defaults to 'tool_table'.
        mapping_table_name (str): The name of the mapping table. Defaults to 'tag_tool_mapping_table'.
        tag_table_name (str): The name of the tags table. Defaults to 'tags_table'.

    Returns:
        list: A list of tools associated with the tags, represented as dictionaries.
    """
    # Ensure tag_ids and tag_names are lists
    if tag_ids and isinstance(tag_ids, str):
        tag_ids = [tag_ids]
    if tag_names and isinstance(tag_names, str):
        tag_names = [tag_names]

    # Full path to the database file
    connection = await asyncpg.connect(
            host=POSTGRESQL_HOST,
            database=DATABASE,
            user=POSTGRESQL_USER,
            password=POSTGRESQL_PASSWORD
        )

    try:

        # Get tag_ids if tag_names are provided
        if tag_names:
            query = f"SELECT tag_id FROM {tag_table_name} WHERE tag_name = ANY($1)"
            rows = await connection.fetch(query, tag_names)
            tag_ids_from_names = [row['tag_id'] for row in rows]
            if tag_ids:
                tag_ids.extend(tag_ids_from_names)
            else:
                tag_ids = tag_ids_from_names
        # If no tag_ids found, return an empty list
        if not tag_ids:
            log.info("No tag_ids or tag_names provided, returning empty list.")
            return []

        # Build the query to get tools based on tag_ids
        query = f"""
        SELECT DISTINCT tl.*
        FROM {tool_table_name} tl
        JOIN {mapping_table_name} m ON tl.tool_id = m.tool_id
        WHERE m.tag_id = ANY($1)
        """
        rows = await connection.fetch(query, tag_ids)

        results_as_dicts = [dict(row) for row in rows]

        tool_id_to_tags = await get_tool_tags_from_mapping_as_dict()
        for result in results_as_dicts:
            result['tags'] = tool_id_to_tags.get(result['tool_id'], [])

        log.info(f"Retrieved {len(results_as_dicts)} tools for tag_ids: {tag_ids} or tag_names: {tag_names}.")
        return results_as_dicts

    except asyncpg.PostgresError as e:
        log.error(f"Error retrieving tools: {e}")
        return []

    finally:
        await connection.close()




# Tags and Agent mapping

async def create_tag_agentic_app_mapping_table_if_not_exists(table_name="tag_agentic_app_mapping_table"):

    connection = await asyncpg.connect(
            host=POSTGRESQL_HOST,
            database=DATABASE,
            user=POSTGRESQL_USER,
            password=POSTGRESQL_PASSWORD
        )
    try:

        create_statement = f"""
        CREATE TABLE IF NOT EXISTS {table_name} (
            tag_id TEXT,
            agentic_application_id TEXT,
            FOREIGN KEY(tag_id) REFERENCES tags_table(tag_id) ON DELETE RESTRICT,
            FOREIGN KEY(agentic_application_id) REFERENCES agent_table(agentic_application_id) ON DELETE CASCADE,
            UNIQUE(tag_id, agentic_application_id)
        )
        """
        await connection.execute(create_statement)
        log.info(f"Table '{table_name}' created successfully or already exists.")
    except asyncpg.PostgresError as e:
        log.error(f"Error creating table: {e}")
    finally:
        await connection.close()

async def insert_into_tag_agentic_app_mapping(tag_ids, agentic_application_id, table_name="tag_agentic_app_mapping_table"):
    """
    Inserts mappings between tag(s) and an agentic application into the tag_agentic_app_mapping_table.

    Args:
        tag_ids (str or list): The ID(s) of the tag(s).
        agentic_application_id (str): The ID of the agentic application.
        table_name (str): The name of the mapping table. Defaults to 'tag_agentic_app_mapping_table'.

    Returns:
        dict: Status of the operation, including success message or error details.
    """
    if isinstance(tag_ids, str):
        tag_ids = [tag_ids]

    # Full path to the database file
    connection = await asyncpg.connect(
            host=POSTGRESQL_HOST,
            database=DATABASE,
            user=POSTGRESQL_USER,
            password=POSTGRESQL_PASSWORD
        )

    inserted_tags = []
    failed_tags = []

    try:

        # Build SQL INSERT statement
        insert_statement = f"""
        INSERT INTO {table_name} (
            tag_id,
            agentic_application_id
        ) VALUES ($1, $2)
        ON CONFLICT (tag_id, agentic_application_id) DO NOTHING
        """

        # Execute the insert statement for each tag_id
        for tag_id in tag_ids:
            try:
                await connection.execute(insert_statement, tag_id, agentic_application_id)
                inserted_tags.append(tag_id)
            except asyncpg.UniqueViolationError as e:
                failed_tags.append((tag_id, str(e)))


        # Return status
        status = {
            "message": f"Inserted mappings for tag_ids: {inserted_tags}. Failed for tag_ids: {failed_tags}",
            "inserted_tag_ids": inserted_tags,
            "failed_tag_ids": failed_tags,
            "agentic_application_id": agentic_application_id,
            "is_created": len(inserted_tags) > 0
        }

    except asyncpg.PostgresError as e:
        # Handle general database errors
        status = {
            "message": f"Error inserting data into '{table_name}' table: {e}",
            "tag_ids": tag_ids,
            "agentic_application_id": agentic_application_id,
            "is_created": False
        }

    finally:
        # Ensure the connection is properly closed
        await connection.close()

    log.info(f"Tag-Agentic App mapping insertion status: {status['message']}")
    return status

async def delete_from_tag_agentic_app_mapping(tag_ids, agentic_application_id, table_name="tag_agentic_app_mapping_table"):
    """
    Deletes mappings between tag(s) and an agentic application from the tag_agentic_app_mapping_table.

    Args:
        tag_ids (str or list): The ID(s) of the tag(s).
        agentic_application_id (str): The ID of the agentic application.
        table_name (str): The name of the mapping table. Defaults to 'tag_agentic_app_mapping_table'.

    Returns:
        dict: Status of the operation, including success message or error details.
    """
    if isinstance(tag_ids, str):
        tag_ids = [tag_ids]

    # Full path to the database file
    connection = await asyncpg.connect(
            host=POSTGRESQL_HOST,
            database=DATABASE,
            user=POSTGRESQL_USER,
            password=POSTGRESQL_PASSWORD
        )

    try:

        # Build SQL DELETE statement
        delete_statement = f"""
        DELETE FROM {table_name}
        WHERE tag_id = $1 AND agentic_application_id = $2
        """

        # Execute the delete statement for each tag_id
        for tag_id in tag_ids:
            result = await connection.execute(delete_statement, tag_id, agentic_application_id)

        # Check if any row was deleted
        if result == "Delete 0":
            status = {
                "message": f"No mapping found between tag_ids: {tag_ids} and agentic_application_id: {agentic_application_id}",
                "tag_ids": tag_ids,
                "agentic_application_id": agentic_application_id,
                "is_deleted": False
            }
        else:
            status = {
                "message": f"Successfully deleted mappings between tag_ids: {tag_ids} and agentic_application_id: {agentic_application_id}",
                "tag_ids": tag_ids,
                "agentic_application_id": agentic_application_id,
                "is_deleted": True
            }

    except Exception as e:
        # Handle general database errors
        status = {
            "message": f"Error deleting mapping from '{table_name}' table: {e}",
            "tag_ids": tag_ids,
            "agentic_application_id": agentic_application_id,
            "is_deleted": False
        }

    finally:
        # Ensure the connection is properly closed
        await connection.close()
    log.info(f"Tag-Agentic App mapping deletion status: {status['message']}")
    return status

async def get_agent_tags_from_mapping_as_dict(tags_dict=None, mapping_table="tag_agentic_app_mapping_table"):
    """
    Fetches the agent-to-tags mapping from the mapping table and formats it
    into a dictionary.

    Args:
        tags_dict (dict, optional): A pre-fetched dictionary of all tags,
                                    from get_tags_as_dict_by_id(). Providing this
                                    is more efficient.
        mapping_table (str): The name of the tag_agentic_app_mapping_table.

    Returns:
        dict: A dictionary where each key is an agentic_application_id and the value is a
              list of dictionaries, with each dictionary being a tag's details.
    """
    connection = None
    agent_to_tags_map = {}
    try:
        connection = await asyncpg.connect(
            host=POSTGRESQL_HOST,
            database=DATABASE,
            user=POSTGRESQL_USER,
            password=POSTGRESQL_PASSWORD
        )

        if tags_dict is None:
            tags_dict = await get_tags_as_dict_by_id()

        if not tags_dict:
            log.warning("No tags available to build the agent-tag mapping.")
            return {}

        query = f"SELECT * FROM {mapping_table}"
        rows = await connection.fetch(query)

        for row in rows:
            agent_id = row['agentic_application_id']
            tag_id = row['tag_id']
            
            tag_details = tags_dict.get(tag_id)
            
            if tag_details:
                if agent_id not in agent_to_tags_map:
                    agent_to_tags_map[agent_id] = []
                agent_to_tags_map[agent_id].append(tag_details)
        
        log.info(f"Built tag mapping for {len(agent_to_tags_map)} agents.")
        return agent_to_tags_map

    except Exception as e:
        log.error(f"Error building agent-tag map: {e}")
        return {}
    finally:
        if connection:
            await connection.close()

async def get_tags_by_agent(agent_id=None, agent_name=None, tag_table_name="tags_table", mapping_table_name="tag_agentic_app_mapping_table", agent_table_name="agent_table"):
    """
    Retrieves tags associated with a given agent ID or agent name.

    Args:
        agent_id (str, optional): The ID of the agent.
        agent_name (str, optional): The name of the agent.
        tag_table_name (str): The name of the tags table. Defaults to 'tags_table'.
        mapping_table_name (str): The name of the mapping table. Defaults to 'tag_agentic_app_mapping_table'.
        agent_table_name (str): The name of the agent table. Defaults to 'agent_table'.

    Returns:
        list: A list of tags associated with the agent, represented as dictionaries.
    """
    # Connect to the Postgres database
    connection = await asyncpg.connect(
            host=POSTGRESQL_HOST,
            database=DATABASE,
            user=POSTGRESQL_USER,
            password=POSTGRESQL_PASSWORD
        )

    try:

        # Build the query to get tag_ids
        query = f"""
        SELECT m.tag_id
        FROM {mapping_table_name} m
        JOIN {agent_table_name} a ON m.agentic_application_id = a.agentic_application_id
        """
        where_clauses = []
        params = []

        # Add filters to the WHERE clause
        idx = 1
        if agent_id:
            where_clauses.append(f"a.agentic_application_id = ${idx}")
            params.append(agent_id)
            idx += 1
        if agent_name:
            where_clauses.append(f"a.agentic_application_name = ${idx}")
            params.append(agent_name)

        # Append WHERE clause to the query if filters are provided
        if where_clauses:
            query += " WHERE " + " AND ".join(where_clauses)

        # Execute the query with parameters
        rows = await connection.fetch(query, *params)

        # Fetch all tag_ids
        tag_ids = [row['tag_id'] for row in rows]

        # If no tag_ids found, return an empty list
        if not tag_ids:
            log.info(f"No tags found for agent_id: {agent_id} or agent_name: {agent_name}.")
            return []


        query = f"""
        SELECT *
        FROM {tag_table_name}
        WHERE tag_id = ANY($1)
        """

        # Execute the query with tag_ids as parameters
        rows = await connection.fetch(query, tag_ids)

        results_as_dicts = [dict(row) for row in rows]
        log.info(f"Retrieved {len(results_as_dicts)} tags for agent_id: {agent_id} or agent_name: {agent_name}.")
        return results_as_dicts

    except asyncpg.PostgresError as e:
        log.error(f"Error retrieving tags: {e}")
        return []

    finally:
        await connection.close()

async def get_agents_by_tag(tag_ids=None, tag_names=None, agent_table_name="agent_table", mapping_table_name="tag_agentic_app_mapping_table", tag_table_name="tags_table"):
    """
    Retrieves agents associated with given tag IDs or tag names.

    Args:
        tag_ids (list, optional): A list of tag IDs or a single tag ID.
        tag_names (list, optional): A list of tag names or a single tag name.
        agent_table_name (str): The name of the agent table. Defaults to 'agent_table'.
        mapping_table_name (str): The name of the mapping table. Defaults to 'tag_agentic_app_mapping_table'.
        tag_table_name (str): The name of the tags table. Defaults to 'tags_table'.

    Returns:
        list: A list of agents associated with the tags, represented as dictionaries.
    """
    # Ensure tag_ids and tag_names are lists
    if tag_ids and isinstance(tag_ids, str):
        tag_ids = [tag_ids]
    if tag_names and isinstance(tag_names, str):
        tag_names = [tag_names]

    connection = await asyncpg.connect(
            host=POSTGRESQL_HOST,
            database=DATABASE,
            user=POSTGRESQL_USER,
            password=POSTGRESQL_PASSWORD
        )

    try:

        # Get tag_ids if tag_names are provided
        if tag_names:
            query = f"SELECT tag_id FROM {tag_table_name} WHERE tag_name = ANY($1)"
            rows = await connection.fetch(query, tag_names)
            tag_ids_from_names = [row['tag_id'] for row in rows]

            if tag_ids:
                tag_ids.extend(tag_ids_from_names)
            else:
                tag_ids = tag_ids_from_names

        # If no tag_ids found, return an empty list
        if not tag_ids:
            log.info("No tag_ids or tag_names provided, returning empty list.")
            return []


        query = f"""
        SELECT DISTINCT a.*
        FROM {agent_table_name} a
        JOIN {mapping_table_name} m ON a.agentic_application_id = m.agentic_application_id
        WHERE m.tag_id = ANY($1)
        """

        # Execute the query with tag_ids as parameters
        rows = await connection.fetch(query, tag_ids)

        results_as_dicts = [dict(row) for row in rows]
        agent_id_to_tags = await get_agent_tags_from_mapping_as_dict()
        for result in results_as_dicts:
            result['tags'] = agent_id_to_tags.get(result['agentic_application_id'], [])
        log.info(f"Retrieved {len(results_as_dicts)} agents for tag_ids: {tag_ids} or tag_names: {tag_names}.") 
        return results_as_dicts

    except asyncpg.PostgresError as e:
        log.error(f"Error retrieving agents: {e}")
        return []

    finally:
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



# Telemetry

async def log_telemetry(
    application_id, session_id, total_token_usage, input_tokens, output_tokens, tools_used,
    total_response_time_ms, no_of_tool_calls, no_of_messages_exchanged, errors_occurred, start_timestamp, end_timestamp,
    model_used, processing_cost, tool_response_time_ms, node_response_time_ms
):
    conn = await asyncpg.connect(
        host=POSTGRESQL_HOST,
        database='telemetry_logs',
        user=POSTGRESQL_USER,
        password=POSTGRESQL_PASSWORD
    )
    try:
        tools_used_json = json.dumps(tools_used)
        errors_occurred_json = json.dumps(errors_occurred)
        node_response_time_json = json.dumps(node_response_time_ms)

        query = """
        INSERT INTO telemetry_log (
            application_id, session_id, total_token_usage, input_tokens, output_tokens, tools_used,
            total_response_time_ms, no_of_tool_calls, no_of_messages_exchanged, errors_occurred,
            start_timestamp, end_timestamp, created_timestamp, model_used,
            processing_cost, tool_response_time_ms, node_response_time_ms
        )
        VALUES (
            $1, $2, $3, $4, $5, $6,
            $7, $8, $9, $10,
            $11, $12, CURRENT_TIMESTAMP, $13,
            $14, $15, $16
        );
        """

        await conn.execute(query,
            application_id, session_id, total_token_usage, input_tokens, output_tokens, tools_used_json,
            total_response_time_ms, no_of_tool_calls, no_of_messages_exchanged, errors_occurred_json,
            start_timestamp, end_timestamp, model_used, processing_cost, tool_response_time_ms, node_response_time_json
        )
        log.info("Telemetry data logged successfully.")
    finally:
        await conn.close()




async def update_token_usage(total_tokens, model_name):
    try:
        conn = await asyncpg.connect(
            host=POSTGRESQL_HOST,
            database='telemetry_logs',
            user=POSTGRESQL_USER,
            password=POSTGRESQL_PASSWORD
        )

        # Fetch current tokens used
        row = await conn.fetchrow(
            "SELECT tokens_used FROM token_usage WHERE model_name = $1;", model_name
        )
        current_tokens = row['tokens_used'] if row else 0
        current_tokens += total_tokens

        # Update tokens_used
        await conn.execute(
            "UPDATE token_usage SET tokens_used = $1 WHERE model_name = $2;",
            current_tokens,
            model_name
        )
        log.info(f"Token usage updated successfully for model: {model_name}. New total: {current_tokens}")
    except Exception as e:
        log.error(f"Error updating token usage for model {model_name}: {e}")
    finally:
        if 'conn' in locals():
            await conn.close()
# -----------------------------------------------

async def create_feedback_storage_table_if_not_exists():
    """Creates the feedback storage table if it doesn't exist using asyncpg"""

    create_feedback_table_query = """
    CREATE TABLE IF NOT EXISTS feedback_response (
        response_id TEXT PRIMARY KEY,
        query TEXT,
        old_final_response TEXT,
        old_steps TEXT,
        old_response TEXT,
        feedback TEXT,
        new_final_response TEXT,
        new_steps TEXT,
        new_response TEXT,
        approved BOOLEAN DEFAULT FALSE,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    """
    create_agent_feedback_table_query = """
    CREATE TABLE IF NOT EXISTS agent_feedback (
        agent_id TEXT,
        response_id TEXT,
        PRIMARY KEY (agent_id, response_id),
        FOREIGN KEY (response_id) REFERENCES feedback_response(response_id)
    );
    """

    conn = await asyncpg.connect(
        host=POSTGRESQL_HOST,
        database='feedback_learning',
        user=POSTGRESQL_USER,
        password=POSTGRESQL_PASSWORD
    )
    try:
        async with conn.transaction():
            await conn.execute(create_feedback_table_query)
            await conn.execute(create_agent_feedback_table_query)
        log.info("Feedback storage tables created successfully or already exist.")
    except asyncpg.PostgresError as e:
        log.error(f"Error creating feedback storage tables: {e}")
    finally:
        await conn.close()


async def insert_into_feedback_table(agent_id, query, old_final_response, old_steps, feedback, new_final_response, new_steps, approved=False):
    """Inserts feedback into the feedback storage table asynchronously using asyncpg"""
    insert_feedback_query = """
    INSERT INTO feedback_response (
        response_id,
        query,
        old_final_response,
        old_steps,
        feedback,
        new_final_response,
        new_steps,
        approved
    )
    VALUES ($1, $2, $3, $4, $5, $6, $7, $8);
    """
    insert_agent_feedback_query = """
    INSERT INTO agent_feedback (agent_id, response_id)
    VALUES ($1, $2);
    """
    response_id = str(uuid.uuid4()).replace("-", "_")  # Generate a unique response ID
    agent_id = str(agent_id).replace("-", "_")  # Ensure agent_id is a string and replace dashes with underscores

    conn = await asyncpg.connect(
        host=POSTGRESQL_HOST,
        database='feedback_learning',
        user=POSTGRESQL_USER,
        password=POSTGRESQL_PASSWORD
    )
    try:
        async with conn.transaction():
            await conn.execute(insert_feedback_query, response_id, query, old_final_response, old_steps, feedback, new_final_response, new_steps, approved)
            await conn.execute(insert_agent_feedback_query, agent_id, response_id)
        log.info(f"Feedback inserted successfully for agent_id: {agent_id} with response_id: {response_id}.")
    finally:
        await conn.close()


async def get_feedback_learning_data(agent_id):
    """
    Retrieves feedback for a specific agent where approved = 1
    """
    select_feedback_query = """
    SELECT * FROM feedback_response fr
    JOIN agent_feedback af ON fr.response_id = af.response_id
    WHERE af.agent_id = $1 AND fr.approved = TRUE;
    """

    conn = await asyncpg.connect(
        host=POSTGRESQL_HOST,
        database='feedback_learning',
        user=POSTGRESQL_USER,
        password=POSTGRESQL_PASSWORD
    )
    try:
        rows = await conn.fetch(select_feedback_query, agent_id)
        results_as_dicts = [dict(row) for row in rows]
        log.info(f"Retrieved {len(results_as_dicts)} feedback entries for agent_id: {agent_id}.")
        return results_as_dicts
    finally:
        await conn.close()


async def get_approvals(agent_id):
    """
    Retrieves all feedbacks and their approval status for a given agent_id.
    """
    select_feedback_query = """
    SELECT af.response_id, fr.feedback
    FROM feedback_response fr
    JOIN agent_feedback af ON fr.response_id = af.response_id
    WHERE af.agent_id = $1;
    """

    # Use your asyncpg connection setup
    conn = await asyncpg.connect(
        host=POSTGRESQL_HOST,
        database='feedback_learning',
        user=POSTGRESQL_USER,
        password=POSTGRESQL_PASSWORD
    )

    try:
        rows = await conn.fetch(select_feedback_query, agent_id)
        log.info(f"Retrieved {len([dict(row) for row in rows])} approval entries for agent_id: {agent_id}.")
        return [dict(row) for row in rows]
    finally:
        await conn.close()


async def get_response_data(response_id):
    """
    Retrieves all feedbacks and their approval status, including agent names.
    """
    select_feedback_query = """
    SELECT * FROM feedback_response fr
    JOIN agent_feedback af ON fr.response_id = af.response_id
    WHERE af.response_id = $1;
    """

    conn = await asyncpg.connect(
            host=POSTGRESQL_HOST,
            database='feedback_learning',
            user=POSTGRESQL_USER,
            password=POSTGRESQL_PASSWORD
        )
    try:
        rows = await conn.fetch(select_feedback_query, response_id)

        results_as_dicts = [dict(row) for row in rows]

        # Add agent_name to each result
        for result in results_as_dicts:
            agent_id = result.get("agent_id", "").replace("_", "-")
            # Assuming this is an async function
            agent_details = await get_agents_by_id(agentic_application_id=agent_id)
            result["agent_name"] = agent_details[0].get("agentic_application_name", "Unknown") if agent_details else "Unknown"
        log.info(f"Retrieved {len(results_as_dicts)} response entries for response_id: {response_id}.")
        return results_as_dicts
    finally:
        await conn.close()


async def get_approval_agents():
    """
    Retrieves all agents who have given feedback along with their names.
    Assumes get_agents_by_id is an async function that takes agentic_application_id.
    """
    select_feedback_query = """
    SELECT DISTINCT agent_id FROM agent_feedback;
    """

    conn = await asyncpg.connect(
            host=POSTGRESQL_HOST,
            database='feedback_learning',
            user=POSTGRESQL_USER,
            password=POSTGRESQL_PASSWORD
        )
    try:
        rows = await conn.fetch(select_feedback_query)
        agent_data = []
        for row in rows:
            agent_id = row['agent_id']
            # Assuming get_agents_by_id is async
            agent_details = await get_agents_by_id(agentic_application_id=agent_id.replace("_", "-"))
            agent_name = agent_details[0].get("agentic_application_name", "Unknown") if agent_details else "Unknown"
            agent_data.append({
                "agent_id": agent_id,
                "agent_name": agent_name
            })
        log.info(f"Retrieved {len(agent_data)} agents who have given feedback.")
        return agent_data
    finally:
        await conn.close()

async def update_feedback_response(response_id, data_dictionary):
    """
    Updates a feedback_response row by response_id.
    data_dictionary: dict with keys as column names and values as the new values.
    """
    set_clause = ', '.join([f"{key} = ${i+1}" for i, key in enumerate(data_dictionary.keys())])
    values = list(data_dictionary.values())
    values.append(response_id)  # Add response_id as the last parameter

    update_query = f"""
    UPDATE feedback_response
    SET {set_clause}
    WHERE response_id = ${len(values)};
    """

    conn = await asyncpg.connect(
            host=POSTGRESQL_HOST,
            database='feedback_learning',
            user=POSTGRESQL_USER,
            password=POSTGRESQL_PASSWORD
        )
    try:
        await conn.execute(update_query, *values)
        log.info(f"Feedback response with response_id: {response_id} updated successfully.")
        return {"is_update": True}
    finally:
        await conn.close()


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


# Evaluation metrics

async def create_evaluation_logs_table():
    conn = await asyncpg.connect(
        host=POSTGRESQL_HOST,
        database='logs',  # use logs DB here
        user=POSTGRESQL_USER,
        password=POSTGRESQL_PASSWORD
    )
    try:
        create_table_query = """
        CREATE TABLE IF NOT EXISTS evaluation_data (
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
        await conn.execute(create_table_query)
        log.info("Table 'evaluation_data' created (if not existed).")
    finally:
        await conn.close()


async def create_agent_evaluation_table():
    conn = await asyncpg.connect(
        host=POSTGRESQL_HOST,
        database='logs',
        user=POSTGRESQL_USER,
        password=POSTGRESQL_PASSWORD
    )
    try:
        create_table_query = """
        CREATE TABLE IF NOT EXISTS agent_evaluation_metrics (
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
            agent_robustness REAL,
            agent_robustness_justification TEXT,
            agent_consistency REAL,
            agent_consistency_justification TEXT,
            answer_relevance REAL,
            answer_relevance_justification TEXT,
            groundedness REAL,
            groundedness_justification TEXT,
            response_fluency REAL,
            response_fluency_justification TEXT,
            response_coherence REAL,
            response_coherence_justification TEXT,
            efficiency_category TEXT,
            consistency_queries TEXT,
            robustness_queries TEXT,
            model_used_for_evaluation TEXT,
            time_stamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        """
        await conn.execute(create_table_query)
        log.info("Table 'agent_evaluation_metrics' created (if not existed).")
    except Exception as e:
        log.error(f"Error creating table: {e}")
    finally:
        await conn.close()


async def create_tool_evaluation_table():
    conn = await asyncpg.connect(
        host=POSTGRESQL_HOST,
        database='logs',
        user=POSTGRESQL_USER,
        password=POSTGRESQL_PASSWORD
    )
    try:
        create_table_query = """
        CREATE TABLE IF NOT EXISTS tool_evaluation_metrics (
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
        await conn.execute(create_table_query)
        log.info("Table 'tool_evaluation_metrics' created (if not existed).")
    except Exception as e:
        log.error(f"Error creating table: {e}")
    finally:
        await conn.close()


def serialize_executor_messages(messages):
    serialized = []
    for msg in messages:
        if hasattr(msg, 'dict'):
            serialized.append(msg.dict())
        elif hasattr(msg, '__dict__'):
            serialized.append(vars(msg))  # fallback
        else:
            serialized.append(str(msg))   # last resort
    return serialized


async def insert_log_entry(data=None):
    if data is None:
        log.error("No data provided for insertion.")
        return
    
    conn = None
    try:
        conn = await asyncpg.connect(
            host=POSTGRESQL_HOST,
            database='logs',
            user=POSTGRESQL_USER,
            password=POSTGRESQL_PASSWORD
        )

        insert_query = """
        INSERT INTO evaluation_data (
            session_id, query, response, model_used,
            agent_id, agent_name, agent_type, agent_goal,
            workflow_description, tool_prompt, steps, executor_messages
        )
        VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12)
        """

        await conn.execute(insert_query,
            data.get("session_id"),
            data.get("query"),
            data.get("response"),
            data.get("model_used"),
            data.get("agent_id"),
            data.get("agent_name"),
            data.get("agent_type"),
            data.get("agent_goal"),
            data.get("workflow_description"),
            data.get("tool_prompt"),
            json.dumps(serialize_executor_messages(data.get("steps", {}))),
            json.dumps(serialize_executor_messages(data.get("executor_messages", {})))
        )
        log.info("Log entry inserted successfully.")

    except Exception as e:
        log.error(f"Error inserting log entry: {e}")
    finally:
        if conn:
            await conn.close()


async def insert_into_evaluation_data(session_id, application_id, agent_config, response, model_name):
    if not response['response'] or ('role' in response['executor_messages'][-1]['agent_steps'][-1] and response['executor_messages'][-1]['agent_steps'][-1]['role'] == 'plan'):
        log.info("Skipping insertion due to empty response or planner role in last step.")
        return
    try:
        data = {}
        data["session_id"] = session_id
        data["query"] = response['query']
        data["response"] = response['response']
        data["model_used"] = model_name
        data["agent_id"] = application_id
        
        # Await get_agents_by_id if async
        agent_details = await get_agents_by_id(agentic_application_id=application_id)
        
        data["agent_name"] = agent_details[0]['agentic_application_name']
        data["agent_type"] = agent_details[0]['agentic_application_type']
        data["agent_goal"] = agent_details[0]['agentic_application_description']
        data["workflow_description"] = agent_details[0]['agentic_application_workflow_description']
        
        tools = agent_config['TOOLS_INFO']
        tools_info = await extract_tools_using_tools_id(tools)
        tool_prompt = generate_tool_prompt(tools_info)
        data["tool_prompt"] = tool_prompt
        
        data["executor_messages"] = response['executor_messages']
        data["steps"] = response['executor_messages'][-1]['agent_steps']
        
        if data['query'].startswith("[feedback:]") and data['query'].endswith("[:feedback]"):
            feedback = data['query'][11:-11]
            data['query'] = "Query:" + data["steps"][0].content + "\nFeedback: " + feedback
        elif data['query'].startswith("[regenerate:]"):
            data['query'] = "Query:" + data["steps"][0].content + "(Regenerate)"
        
        # Await the async insert_log_entry function
        await insert_log_entry(data=data)
        log.info("Data inserted into evaluation_data table successfully.")
    except Exception as e:
        log.error(f"Error inserting data into evaluation_data table: {e}")


async def update_processing_status_id(evaluation_id, status):
    """Update the status of an evaluation record in the evaluation_data table."""
    try:
        conn = await asyncpg.connect(
        host=POSTGRESQL_HOST,
        database='logs',
        user=POSTGRESQL_USER,
        password=POSTGRESQL_PASSWORD
    )
        update_query = """
        UPDATE evaluation_data
        SET evaluation_status = $1
        WHERE id = $2;
        """
        await conn.execute(update_query, status, evaluation_id)
        log.info(f"Status for evaluation_id {evaluation_id} updated to '{status}'.")
    except Exception as e:
        log.error(f"Error updating status for evaluation_id {evaluation_id}: {e}")
    finally:
        await conn.close()


async def fetch_next_unprocessed_evaluation():
    """Fetch the next unprocessed evaluation entry, including session_id and agent_id."""
    try:
        conn = await asyncpg.connect(
        host=POSTGRESQL_HOST,
        database='logs',
        user=POSTGRESQL_USER,
        password=POSTGRESQL_PASSWORD
    )

        query = """
            SELECT 
                id,
                query,
                response,
                agent_goal,
                agent_name,
                workflow_description,
                steps,
                tool_prompt,
                model_used,
                session_id,
                agent_id
            FROM evaluation_data
            WHERE evaluation_status = 'unprocessed'
            ORDER BY time_stamp
            LIMIT 1
        """

        row = await conn.fetchrow(query)

        await conn.close()

        if not row:
            log.info("No unprocessed evaluations found.")
            return None

        # 'steps' might be stored as JSON or JSONB, asyncpg auto-converts JSONB to Python object
        steps = row['steps']
        if isinstance(steps, str):
            steps = json.loads(steps)
        log.info(f" Fetched unprocessed evaluation entry with ID: {row['id']}")
        return {
            "id": row['id'],
            "query": row['query'],
            "response": row['response'],
            "agent_goal": row['agent_goal'],
            "agent_name": row['agent_name'],
            "workflow_description": row['workflow_description'],
            "steps": steps,
            "tool_prompt": row['tool_prompt'],
            "model_used": row['model_used'],
            "session_id": row['session_id'],
            "agent_id": row['agent_id']
        }

    except Exception as e:
        log.error(f"Error fetching data: {e}")
        return None
   

async def insert_evaluation_metrics(evaluation_id, user_query, response, model_used, scores, justifications, consistency_queries, robustness_queries, model_used_for_evaluation):
    if not isinstance(justifications, dict):
        log.error("Invalid justifications: Expected a dictionary, but got", type(justifications))
        justifications = {}

    consistency_queries_json = json.dumps(consistency_queries)
    robustness_queries_json = json.dumps(robustness_queries)

    # Extract scores with defaults
    task_decomposition_efficiency = scores.get('Task Decomposition', 0.0)
    reasoning_relevancy = scores.get('Reasoning Relevancy', 0.0)
    reasoning_coherence = scores.get('Reasoning Coherence', 0.0)
    agent_robustness = scores.get('Agent Robustness', 0.0)
    agent_consistency = scores.get('Agent Consistency', 0.0)
    answer_relevance = scores.get('Relevancy', 0.0)
    groundedness = scores.get('Groundness', 0.0)
    response_fluency = scores.get('Fluency', 0.0)
    response_coherence = scores.get('Coherence', 0.0)
    efficiency_category = scores.get('Efficiency Category', 'Unknown')

    # Extract justifications with defaults
    task_decomposition_just = justifications.get('Task Decomposition', '')
    reasoning_relevancy_just = justifications.get('Reasoning Relevancy', '')
    reasoning_coherence_just = justifications.get('Reasoning Coherence', '')
    agent_robustness_just = justifications.get('Agent Robustness', '')
    agent_consistency_just = justifications.get('Agent Consistency', '')
    answer_relevance_just = justifications.get('Relevancy', '')
    groundedness_just = justifications.get('Groundness', '')
    response_fluency_just = justifications.get('Fluency', '')
    response_coherence_just = justifications.get('Coherence', '')

    insert_query = """
        INSERT INTO agent_evaluation_metrics (
            evaluation_id, user_query, response, model_used, 
            task_decomposition_efficiency, task_decomposition_justification,
            reasoning_relevancy, reasoning_relevancy_justification,
            reasoning_coherence, reasoning_coherence_justification,
            agent_robustness, agent_robustness_justification,
            agent_consistency, agent_consistency_justification,
            answer_relevance, answer_relevance_justification,
            groundedness, groundedness_justification,
            response_fluency, response_fluency_justification,
            response_coherence, response_coherence_justification,
            efficiency_category, consistency_queries, robustness_queries, model_used_for_evaluation
        ) VALUES (
            $1, $2, $3, $4, $5, $6, $7, $8, $9, $10,
            $11, $12, $13, $14, $15, $16, $17, $18,
            $19, $20, $21, $22, $23, $24, $25, $26
        )
    """

    args = (
        evaluation_id, user_query, response, model_used,
        task_decomposition_efficiency, task_decomposition_just,
        reasoning_relevancy, reasoning_relevancy_just,
        reasoning_coherence, reasoning_coherence_just,
        agent_robustness, agent_robustness_just,
        agent_consistency, agent_consistency_just,
        answer_relevance, answer_relevance_just,
        groundedness, groundedness_just,
        response_fluency, response_fluency_just,
        response_coherence, response_coherence_just,
        efficiency_category, consistency_queries_json, robustness_queries_json, model_used_for_evaluation
    )

    try:
        conn = await asyncpg.connect(
        host=POSTGRESQL_HOST,
        database='logs',
        user=POSTGRESQL_USER,
        password=POSTGRESQL_PASSWORD
    )
        await conn.execute(insert_query, *args)
        log.info(f"Agent Evaluation metrics inserted successfully for evaluation_id: {evaluation_id}")
        await conn.close()
    except Exception as e:
        log.error(f"Error inserting evaluation metrics for evaluation_id {evaluation_id}: {e}")


async def insert_tool_evaluation_metrics(
    evaluation_id, user_query, agent_response, model_used, result_dict, 
    tsa_justification, tue_justification, tcp_justification, model_used_for_evaluation
):
    required_keys = [
        "tool_selection_accuracy", "tool_usage_efficiency", "tool_call_precision",
        "tool_call_success_rate", "tool_utilization_efficiency", "tool_utilization_efficiency_category"
    ]
    
    # Check for missing keys in the result_dict
    for key in required_keys:
        if key not in result_dict:
            log.error(f"Missing key in result_dict: {key}")
            return  # Exit if any required key is missing

    tool_call_success_rate = result_dict.get("tool_call_success_rate")

    query = """
    INSERT INTO tool_evaluation_metrics (
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
    )
    """

    values = (
        evaluation_id,
        user_query,
        agent_response,
        model_used,
        result_dict["tool_selection_accuracy"],
        result_dict["tool_usage_efficiency"],
        result_dict["tool_call_precision"],
        tool_call_success_rate,
        result_dict["tool_utilization_efficiency"],
        result_dict["tool_utilization_efficiency_category"],
        tsa_justification,
        tue_justification,
        tcp_justification,
        model_used_for_evaluation
    )

    try:
        conn = await asyncpg.connect(
        host=POSTGRESQL_HOST,
        database='logs',
        user=POSTGRESQL_USER,
        password=POSTGRESQL_PASSWORD
    )
        await conn.execute(query, *values)
        log.info(f"Inserted tool evaluation metrics for evaluation_id: {evaluation_id}")
        await conn.close()
    except Exception as e:
        log.error(f"Failed to insert tool evaluation metrics for evaluation_id {evaluation_id}: {e}")
 
 
async def get_evaluation_data_by_agent_names(
    agent_names: Optional[List[str]] = None, 
    page: int = 1, 
    limit: int = 10
):
    # Calculate offset for pagination
    offset = (page - 1) * limit
    
    if agent_names and len(agent_names) > 0:
        query = """
            SELECT session_id, query, response, model_used, agent_id, agent_name, agent_type
            FROM evaluation_data
            WHERE agent_name = ANY($1::text[])
            ORDER BY id DESC
            LIMIT $2 OFFSET $3
        """
        params = (agent_names, limit, offset)
    else:
        query = """
            SELECT session_id, query, response, model_used, agent_id, agent_name, agent_type
            FROM evaluation_data
            ORDER BY id DESC
            LIMIT $1 OFFSET $2
        """
        params = (limit, offset)

    try:
        conn = await asyncpg.connect(
            host=POSTGRESQL_HOST,
            database='logs',
            user=POSTGRESQL_USER,
            password=POSTGRESQL_PASSWORD
        )
        results = await conn.fetch(query, *params)
        await conn.close()
        return [dict(row) for row in results]
    except Exception as e:
        log.error(f" Error fetching evaluation_data: {e}")
        return []


async def get_agent_metrics_by_agent_names(
    agent_names: Optional[List[str]] = None, 
    page: int = 1, 
    limit: int = 10
):
    # Calculate offset for pagination
    offset = (page - 1) * limit
    
    if agent_names and len(agent_names) > 0:
        query = """
            SELECT aem.*
            FROM agent_evaluation_metrics aem
            JOIN evaluation_data ed ON aem.evaluation_id = ed.id
            WHERE ed.agent_name = ANY($1::text[])
            ORDER BY aem.id DESC
            LIMIT $2 OFFSET $3
        """
        params = (agent_names, limit, offset)
    else:
        query = """
            SELECT aem.*
            FROM agent_evaluation_metrics aem
            JOIN evaluation_data ed ON aem.evaluation_id = ed.id
            ORDER BY aem.id DESC
            LIMIT $1 OFFSET $2
        """
        params = (limit, offset)

    try:
        conn = await asyncpg.connect(
            host=POSTGRESQL_HOST,
            database='logs',
            user=POSTGRESQL_USER,
            password=POSTGRESQL_PASSWORD
        )
        results = await conn.fetch(query, *params)
        await conn.close()
        return [dict(row) for row in results]
    except Exception as e:
        log.error(f" Error fetching agent metrics: {e}")
        return []


async def get_tool_metrics_by_agent_names(
    agent_names: Optional[List[str]] = None, 
    page: int = 1, 
    limit: int = 10
):
    # Calculate offset for pagination
    offset = (page - 1) * limit
    
    if agent_names and len(agent_names) > 0:
        query = """
            SELECT tem.*
            FROM tool_evaluation_metrics tem
            JOIN evaluation_data ed ON tem.evaluation_id = ed.id
            WHERE ed.agent_name = ANY($1::text[])
            ORDER BY tem.id DESC
            LIMIT $2 OFFSET $3
        """
        params = (agent_names, limit, offset)
    else:
        query = """
            SELECT tem.*
            FROM tool_evaluation_metrics tem
            JOIN evaluation_data ed ON tem.evaluation_id = ed.id
            ORDER BY tem.id DESC
            LIMIT $1 OFFSET $2
        """
        params = (limit, offset)

    try:
        conn = await asyncpg.connect(
            host=POSTGRESQL_HOST,
            database='logs',
            user=POSTGRESQL_USER,
            password=POSTGRESQL_PASSWORD
        )
        results = await conn.fetch(query, *params)
        await conn.close()
        return [dict(row) for row in results]
    except Exception as e:
        log.error(f" Error fetching tool metrics: {e}")
        return []


async def get_agents_details_for_chat(agent_table_name="agent_table"):
    """
    Fetches agent details (ID, name, type) from a PostgreSQL database for chat purposes.

    Args:
        agent_table_name (str): The name of the table containing agent data.

    Returns:
        list[dict]: A list of dictionaries, where each dictionary contains
                    'agentic_application_id', 'agentic_application_name',
                    and 'agentic_application_type'.
    """
    # Connect to the PostgreSQL database asynchronously
    # In a production environment, consider using an asyncpg connection pool
    # instead of creating a new connection for each call.
    connection = await asyncpg.connect(
        host=POSTGRESQL_HOST,
        database=DATABASE,
        user=POSTGRESQL_USER,
        password=POSTGRESQL_PASSWORD
    )

    try:
        # Build the query to select specific columns
        query = f"""
            SELECT agentic_application_id, agentic_application_name, agentic_application_type
            FROM {agent_table_name}
            ORDER BY created_on DESC
        """

        # Execute the query asynchronously
        # asyncpg.fetch returns a list of asyncpg.Record objects
        rows = await connection.fetch(query)

        # Convert asyncpg.Record objects to dictionaries
        results_as_dicts = [
            {
                "agentic_application_name": row["agentic_application_name"],
                "agentic_application_id": row["agentic_application_id"],
                "agentic_application_type": row["agentic_application_type"]
            }
            for row in rows
        ]

        return results_as_dicts

    except asyncpg.PostgresError as e:
        log.error(f"PostgreSQL error: {e}")
        return []
    except Exception as e:
        log.error(f"An unexpected error occurred: {e}")
        return []
    finally:
        # Close the connection asynchronously
        if connection:
            await connection.close()


async def create_recycle_tool_table_if_not_exists():
    """
    Connects to a PostgreSQL database and creates the 'recycle_tool' table
    if it doesn't already exist.
    """
    conn = None
    try:
        # Connect to the PostgreSQL database asynchronously
        conn = await asyncpg.connect(
            host=POSTGRESQL_HOST,
            database='recycle',
            user=POSTGRESQL_USER,
            password=POSTGRESQL_PASSWORD
        )

        # SQL statement to create the recycle_tool table
        create_table_sql = """
        CREATE TABLE IF NOT EXISTS recycle_tool (
            tool_id TEXT PRIMARY KEY,                     -- Unique identifier for each tool
            tool_name TEXT UNIQUE,                       -- Unique name for the tool
            tool_description TEXT,                       -- Description of the tool
            code_snippet TEXT,                           -- Optional code snippet associated with the tool
            model_name TEXT,                             -- Name of the model used
            created_by TEXT,                             -- User who created the entry
            created_on TIMESTAMP DEFAULT CURRENT_TIMESTAMP, -- Timestamp for when the record is created
            updated_on TIMESTAMP DEFAULT CURRENT_TIMESTAMP -- Timestamp for when the record is updated
        )
        """

        # Execute the CREATE TABLE statement
        await conn.execute(create_table_sql)
        print("Table 'recycle_tool' created successfully (or already exists).")

    except asyncpg.PostgresError as e:
        print(f"An error occurred while creating the table: {e}")
    finally:
        # Close the database connection asynchronously
        if conn:
            await conn.close()

async def create_recycle_agent_table_if_not_exists():
    """Connects to a PostgreSQL database and creates the 'recycle_agent' table"""
    conn = None
    try:
        # Connect to the PostgreSQL database asynchronously
        conn = await asyncpg.connect(
            host=POSTGRESQL_HOST,
            database='recycle',
            user=POSTGRESQL_USER,
            password=POSTGRESQL_PASSWORD
        )

        # SQL statement to create the recycle_agent table
        create_table_sql = """
        CREATE TABLE IF NOT EXISTS recycle_agent (
            agentic_application_id TEXT PRIMARY KEY,                     -- Unique identifier for each agentic application
            agentic_application_name TEXT UNIQUE,                       -- Unique name for the agentic application
            agentic_application_description TEXT,                       -- Description of the agentic application
            agentic_application_workflow_description TEXT,              -- Workflow description of the agentic application
            agentic_application_type TEXT,                              -- Type of the agentic application
            model_name TEXT,                                            -- Name of the model used
            system_prompt JSONB,                                         -- JSON object for system prompts
            tools_id JSONB,                                              -- JSON object for associated tools
            created_by TEXT,                                            -- User who created the entry
            created_on TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,             -- Timestamp for when the record is created
            updated_on TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP              -- Timestamp for when the record is updated
        )
        """

        # Execute the CREATE TABLE statement
        await conn.execute(create_table_sql)
        print("Table 'recycle_agent' created successfully (or already exists).")

    except asyncpg.PostgresError as e:
        print(f"An error occurred while creating the table: {e}")
    finally:
        # Close the database connection asynchronously
        if conn:
            await conn.close()


async def restore_recycle_tool_by_id(tool_id):
    """
    Deletes a tool from the PostgreSQL database based on the provided tool ID or tool name asynchronously.

    Args:
        user_email_id (str): The email ID of the user performing the deletion.
        is_admin (bool): Whether the user is an admin.
        tool_table_name (str): Name of the PostgreSQL table containing tools.
        tool_id (str, optional): The ID of the tool to delete.
        tool_name (str, optional): The name of the tool to delete.

    Returns:
        dict: Status of the operation, including success message or error details.
    """

    connection = await asyncpg.connect(
        host=POSTGRESQL_HOST,
        database=DATABASE,
        user=POSTGRESQL_USER,
        password=POSTGRESQL_PASSWORD
    )

    connection_recycle = await asyncpg.connect(
        host=POSTGRESQL_HOST,
        database="recycle",
        user=POSTGRESQL_USER,
        password=POSTGRESQL_PASSWORD
    )

    try:
        # Fetch tool details asynchronously
        query = f"SELECT * FROM recycle_tool WHERE "
        if tool_id:
            query += "tool_id = $1"
            params = [tool_id]

        tool = await connection_recycle.fetchrow(query, *params)
        if not tool:
            log.error(f"No Tool available with ID: {tool_id}")
            return {
                "status_message": f"No Tool available with ID: {tool_id}",
                "details": [],
                "is_delete": False
            }

        tool_data = dict(tool)

        #insert the tool in recycle-bin DB
        recycle_query = f"""
            INSERT INTO tool_table (
                tool_id,
                tool_name,
                tool_description,
                code_snippet,
                model_name,
                created_by,
                created_on,
                updated_on
            ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
        """
        recycle_values = (
            tool_data.get("tool_id"),
            tool_data.get("tool_name"),
            tool_data.get("tool_description"),
            tool_data.get("code_snippet"),
            tool_data.get("model_name"),
            tool_data.get("created_by"),
            tool_data["created_on"],
            tool_data["updated_on"]
        )

            
        # Delete the tool
        delete_query = "DELETE FROM recycle_tool WHERE tool_id = $1"
        await connection_recycle.execute(delete_query, tool_data["tool_id"])
        await connection.execute(recycle_query, *recycle_values)
        # Clean up associated tool-agent mappings

        log.info(f"Successfully deleted tool with ID: {tool_data['tool_id']}")
        return {
            "status_message": f"Successfully Deleted Record for Tool with Tool ID: {tool_data['tool_id']}",
            "details": [],
            "is_delete": True
        }

    except asyncpg.PostgresError as e:
        log.error(f"Error deleting tool: {e}")
        return {
            "status_message": f"An error occurred while deleting the tool: {e}",
            "details": [],
            "is_delete": False
        }

    finally:
        await connection.close()
        await connection_recycle.close()

async def restore_recycle_agent_by_id(agentic_application_id):
    """
    Deletes an agentic application from the PostgreSQL database based on the provided agentic application ID or name.

    Args:
        user_email_id (str): The email ID of the user performing the deletion.
        is_admin (bool): Whether the user is an admin.
        agent_table_name (str): Name of the PostgreSQL table containing agents.
        agentic_application_id (str, optional): The ID of the agentic application to delete.
        agentic_application_name (str, optional): The name of the agentic application to delete.

    Returns:
        dict: Status of the operation, including success message or error details.
    """

    connection = await asyncpg.connect(
        host=POSTGRESQL_HOST,
        database=DATABASE,
        user=POSTGRESQL_USER,
        password=POSTGRESQL_PASSWORD
    )

    connection_recycle = await asyncpg.connect(
        host=POSTGRESQL_HOST,
        database='recycle',
        user=POSTGRESQL_USER,
        password=POSTGRESQL_PASSWORD
    )

    try:

        # Retrieve agentic application details
        query = "SELECT * FROM recycle_agent WHERE "
        params = []
        idx = 1
        if agentic_application_id:
            query += f"agentic_application_id = ${idx}"
            params.append(agentic_application_id)
            idx += 1

        agent = await connection_recycle.fetchrow(query, *params)


        if not agent:
            log.error(f"No Agentic Application found with ID: {agentic_application_id}")
            return {
                "status_message": f"No Agentic Application available with ID: {agentic_application_id}",
                "is_delete": False
            }

        agent_data = dict(agent)

        #insert into recycle bin

        recycle_query = f"""
        INSERT INTO agent_table(agentic_application_id, agentic_application_name, agentic_application_description, agentic_application_workflow_description, agentic_application_type, model_name, system_prompt, tools_id, created_by, created_on, updated_on)
        VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11)
        """

        new_tool_id_list = []
        new_tool_list_data = []
        for tool_id in json.loads(agent_data["tools_id"]):
            tool = await get_tools_by_id(tool_id=tool_id)
            tool_data = tool[0] if tool else None
            if tool_data:
                new_tool_id_list.append(tool_id)
                new_tool_list_data.append(tool_data)
            else:
                log.error(f"Tool with ID {tool_id} not found. Removing tool from the agent {agent_data['agentic_application_name']}.")

        agent_data['tools_id'] = json.dumps(new_tool_id_list)

        recycle_params = (
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


        #insert data in tool_agent_mapping
        for tool_id, tool_data in zip(new_tool_id_list, new_tool_list_data):
            await insert_data_tool_agent_mapping(
                tool_id=tool_id,
                agentic_application_id=agent_data["agentic_application_id"],
                tool_created_by=tool_data["created_by"],
                agentic_app_created_by=agent_data["created_by"]
            )
        # Close the recycle connection

        # Delete the agentic application
        delete_query = "DELETE FROM recycle_agent WHERE "
        params = []

        if agentic_application_id:
            delete_query += "agentic_application_id = $1"
            params = [agentic_application_id]

        await connection_recycle.execute(delete_query, *params)
        await connection.execute(recycle_query, *recycle_params)

        


        log.info(f"Successfully deleted Agentic Application with ID: {agentic_application_id}")
        return {
            "status_message": f"Successfully Deleted Record for Agentic Application with ID: {agentic_application_id or agent_data['agentic_application_id']}.",
            "is_delete": True
        }

    except asyncpg.PostgresError as e:
        log.error(f"Database error: {e}")
        return {
            "status_message": f"An error occurred while deleting the agent: {e}",
            "is_delete": False
        }

    finally:
        await connection.close()
        await connection_recycle.close()
 

async def delete_recycle_agent_by_id(agentic_application_id):
    """
    Deletes an agentic application from the PostgreSQL database based on the provided agentic application ID or name.

    Args:
        user_email_id (str): The email ID of the user performing the deletion.
        is_admin (bool): Whether the user is an admin.
        agent_table_name (str): Name of the PostgreSQL table containing agents.
        agentic_application_id (str, optional): The ID of the agentic application to delete.
        agentic_application_name (str, optional): The name of the agentic application to delete.

    Returns:
        dict: Status of the operation, including success message or error details.
    """

    connection_recycle = await asyncpg.connect(
        host=POSTGRESQL_HOST,
        database='recycle',
        user=POSTGRESQL_USER,
        password=POSTGRESQL_PASSWORD
    )

    try:

        # Retrieve agentic application details
        query = "SELECT * FROM recycle_agent WHERE "
        params = []
        idx = 1
        if agentic_application_id:
            query += f"agentic_application_id = ${idx}"
            params.append(agentic_application_id)
            idx += 1

        agent = await connection_recycle.fetchrow(query, *params)


        if not agent:
            log.error(f"No Agentic Application found with ID: {agentic_application_id}")
            return {
                "status_message": f"No Agentic Application available with ID: {agentic_application_id}",
                "is_delete": False
            }

        agent_data = dict(agent)

        # Delete the agentic application
        delete_query = "DELETE FROM recycle_agent WHERE "
        params = []

        if agentic_application_id:
            delete_query += "agentic_application_id = $1"
            params = [agentic_application_id]

        await connection_recycle.execute(delete_query, *params)


        log.info(f"Successfully deleted Agentic Application with ID: {agentic_application_id}")
        return {
            "status_message": f"Successfully Deleted Record for Agentic Application with ID: {agentic_application_id or agent_data['agentic_application_id']}.",
            "is_delete": True
        }

    except asyncpg.PostgresError as e:
        log.error(f"Database error: {e}")
        return {
            "status_message": f"An error occurred while deleting the agent: {e}",
            "is_delete": False
        }

    finally:
        await connection_recycle.close()

async def delete_recycle_tool_by_id(tool_id):
    """
    Deletes a tool from the PostgreSQL database based on the provided tool ID or tool name asynchronously.

    Args:
        user_email_id (str): The email ID of the user performing the deletion.
        is_admin (bool): Whether the user is an admin.
        tool_table_name (str): Name of the PostgreSQL table containing tools.
        tool_id (str, optional): The ID of the tool to delete.
        tool_name (str, optional): The name of the tool to delete.

    Returns:
        dict: Status of the operation, including success message or error details.
    """

    connection_recycle = await asyncpg.connect(
        host=POSTGRESQL_HOST,
        database="recycle",
        user=POSTGRESQL_USER,
        password=POSTGRESQL_PASSWORD
    )

    try:
        # Fetch tool details asynchronously
        query = f"SELECT * FROM recycle_tool WHERE "
        if tool_id:
            query += "tool_id = $1"
            params = [tool_id]

        tool = await connection_recycle.fetchrow(query, *params)
        if not tool:
            log.error(f"No Tool available with ID: {tool_id}")
            return {
                "status_message": f"No Tool available with ID: {tool_id}",
                "details": [],
                "is_delete": False
            }

        tool_data = dict(tool)
            
        # Delete the tool
        delete_query = "DELETE FROM recycle_tool WHERE tool_id = $1"
        await connection_recycle.execute(delete_query, tool_data["tool_id"])

        # Clean up associated tool-agent mappings

        log.info(f"Successfully deleted tool with ID: {tool_data['tool_id']}")
        return {
            "status_message": f"Successfully Deleted Record for Tool with Tool ID: {tool_data['tool_id']}",
            "details": [],
            "is_delete": True
        }

    except asyncpg.PostgresError as e:
        log.error(f"Error deleting tool: {e}")
        return {
            "status_message": f"An error occurred while deleting the tool: {e}",
            "details": [],
            "is_delete": False
        }

    finally:
        await connection_recycle.close()


async def get_tool_data(agent_data,export_path,tools=[]):
    import json
    if not tools:
        tools_id_str = agent_data.get("tools_id")
        tool_ids = json.loads(tools_id_str)
    else:
        tool_ids = tools 
    tools_data = {}   
    for tool_id in tool_ids:
        tool_data = await get_tools_by_id(tool_id=tool_id)
        if tool_data:
            tool_dict= tool_data[0]
            processed_tool_dict = {}
            for key, value in tool_dict.items():
                if isinstance(value, datetime):
                    processed_tool_dict[key] = value.isoformat()
                else:
                    processed_tool_dict[key] = value
            tools_data[tool_id] = processed_tool_dict
        else:
            tools_data[tool_id] = None
    tool_data_file_path=os.path.join(export_path, 'Agent_Backend/tools_data.py')
    tools_data_json_str = json.dumps(tools_data, indent=4)
    with open(tool_data_file_path, 'w') as f:
            f.write('tools_data = ')
            f.write(tools_data_json_str)
