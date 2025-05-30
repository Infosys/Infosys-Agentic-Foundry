# © 2024-25 Infosys Limited, Bangalore, India. All Rights Reserved.
import os
import json
import sqlite3
from datetime import datetime, timezone
import uuid
import pandas as pd
from langgraph.prebuilt import create_react_agent
from src.models.model import load_model
from src.tools.tool_docstring_generator import generate_docstring_tool_onboarding
from src.agent_templates.react_agent_onboarding import react_system_prompt_gen_func
from src.agent_templates.multi_agent_onboarding import planner_executor_critic_builder
from src.utils.helper_functions import dict_factory
import psycopg2
import psycopg2.extras
from sqlalchemy import create_engine
from psycopg2 import pool



# Connection string format:
POSTGRESQL_HOST = os.getenv("POSTGRESQL_HOST", "")
POSTGRESQL_USER = os.getenv("POSTGRESQL_USER", "")
POSTGRESQL_PASSWORD = os.getenv("POSTGRESQL_PASSWORD", "")
DATABASE = os.getenv("DATABASE", "")
DATABASE_URL = os.getenv("POSTGRESQL_DATABASE_URL", "")

# Create a connection pool
connection_pool = psycopg2.pool.SimpleConnectionPool(
    minconn=10,        # Minimum number of connections
    maxconn=20,       # Maximum number of connections
    dsn=DATABASE_URL  # Using the connection string
)


def return_connection(conn):
    connection_pool.putconn(conn)



def delete_table(table_name):
    """
    Deletes a SQLite table.

    Args:
        table_name (str): Name of the table to delete.
    """

    connection = psycopg2.connect(
            host=POSTGRESQL_HOST,
            database=DATABASE,
            user=POSTGRESQL_USER,
            password=POSTGRESQL_PASSWORD
        )

    try:
        cursor = connection.cursor()

        # Build and execute the DROP TABLE statement
        drop_statement = f"DROP TABLE IF EXISTS {table_name}"
        cursor.execute(drop_statement)
        connection.commit()

    # except sqlite3.DatabaseError as e:
    except psycopg2.errors.DatabaseError as e:
        pass

    finally:
        connection.close()



def truncate_table(table_name):
    """
    Truncates a SQLite table, removing all data while keeping the table structure.

    Args:
        table_name (str): Name of the table to truncate.
    """

    try:
        connection = psycopg2.connect(
            host=POSTGRESQL_HOST,
            database=DATABASE,
            user=POSTGRESQL_USER,
            password=POSTGRESQL_PASSWORD
        )
        cursor = connection.cursor()
        # Build and execute the TRUNCATE TABLE statement
        truncate_statement = f"TRUNCATE TABLE {table_name}"
        cursor.execute(truncate_statement)
        connection.commit()

    except psycopg2.errors.DatabaseError as e:
        pass
    finally:
        if connection:
            cursor.close()
            connection.close()




# Tool Agent Mapping Table

def create_tool_agent_mapping_table_if_not_exists(table_name="tool_agent_mapping_table"):

    connection = psycopg2.connect(
            host=POSTGRESQL_HOST,
            database=DATABASE,
            user=POSTGRESQL_USER,
            password=POSTGRESQL_PASSWORD
        )

    try:
        cursor = connection.cursor()
        # Create the table if it doesn't already exist
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
        cursor.execute(create_statement)
        connection.commit()
    except psycopg2.errors.DatabaseError as e:
        pass
    finally:
        connection.close()


def insert_data_tool_agent_mapping(table_name="tool_agent_mapping_table",
                                   tool_id=None, agentic_application_id=None, tool_created_by=None, agentic_app_created_by=None):

    connection = psycopg2.connect(
            host=POSTGRESQL_HOST,
            database=DATABASE,
            user=POSTGRESQL_USER,
            password=POSTGRESQL_PASSWORD
        )

    try:

        cursor = connection.cursor()
        # Check if the record already exists
        select_statement = f"""
            SELECT 1 FROM {table_name}
            WHERE tool_id = %s AND agentic_application_id = %s
            """
        cursor.execute(select_statement, (tool_id, agentic_application_id))
        result = cursor.fetchone()

        # Insert only if the record doesn't exist
        if not result:
            insert_statement = f"""
                INSERT INTO {table_name} (tool_id, agentic_application_id, tool_created_by, agentic_app_created_by)
                VALUES (%s, %s, %s, %s)
                """
            cursor.execute(insert_statement, (tool_id, agentic_application_id,
                                            tool_created_by, agentic_app_created_by))

            # Commit changes
            connection.commit()

    except psycopg2.errors.DatabaseError as e:
        pass


    finally:
        # Close the connection
        connection.close()



def get_data_tool_agent_mapping(table_name="tool_agent_mapping_table",
                                tool_id=None,
                                agentic_application_id=None,
                                tool_created_by=None,
                                agentic_app_created_by=None):
    """
    Retrieves data from the tool-agent mapping table in PostgreSQL.

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
        # Connect to the PostgreSQL database
        connection = psycopg2.connect(
            host=POSTGRESQL_HOST,
            database=DATABASE,
            user=POSTGRESQL_USER,
            password=POSTGRESQL_PASSWORD
        )
        cursor = connection.cursor()

        # Build the SELECT query
        select_statement = f"SELECT * FROM {table_name}"
        where_clause = []
        params = []

        # Add filters dynamically
        if tool_id:
            where_clause.append("tool_id = %s")
            params.append(tool_id)
        if agentic_application_id:
            where_clause.append("agentic_application_id = %s")
            params.append(agentic_application_id)
        if tool_created_by:
            where_clause.append("tool_created_by = %s")
            params.append(tool_created_by)
        if agentic_app_created_by:
            where_clause.append("agentic_app_created_by = %s")
            params.append(agentic_app_created_by)

        # Append WHERE clause if any filters are provided
        if where_clause:
            select_statement += " WHERE " + " AND ".join(where_clause)

        # Execute the query
        cursor.execute(select_statement, tuple(params))  # Pass parameters as a tuple
        rows = cursor.fetchall()

        # Fetch column names to structure results
        columns = [column[0] for column in cursor.description]
        data = [dict(zip(columns, row)) for row in rows]

        return data

    except psycopg2.errors.DatabaseError as e:
        return []  # Return an empty list in case of an error

    finally:
        if 'connection' in locals():
            connection.close()


def update_data_tool_agent_mapping(table_name="tool_agent_mapping_table",
                                   tool_id=None, agentic_application_id=None,
                                   tool_created_by=None, agentic_app_created_by=None,
                                   new_tool_id=None, new_agentic_application_id=None,
                                   new_tool_created_by=None, new_agentic_app_created_by=None):
    connection = psycopg2.connect(
        host=POSTGRESQL_HOST,
        database=DATABASE,
        user=POSTGRESQL_USER,
        password=POSTGRESQL_PASSWORD
    )

    try:
        cursor = connection.cursor()

        # Build the SET clause
        set_clause = []
        set_parameters = []

        if new_tool_id:
            set_clause.append("tool_id = %s")
            set_parameters.append(new_tool_id)
        if new_agentic_application_id:
            set_clause.append("agentic_application_id = %s")
            set_parameters.append(new_agentic_application_id)
        if new_tool_created_by:
            set_clause.append("tool_created_by = %s")
            set_parameters.append(new_tool_created_by)
        if new_agentic_app_created_by:
            set_clause.append("agentic_app_created_by = %s")
            set_parameters.append(new_agentic_app_created_by)

        if not set_clause:
            return

        # Build the WHERE clause
        where_clause = []
        where_parameters = []

        if tool_id:
            where_clause.append("tool_id = %s")
            where_parameters.append(tool_id)
        if agentic_application_id:
            where_clause.append("agentic_application_id = %s")
            where_parameters.append(agentic_application_id)
        if tool_created_by:
            where_clause.append("tool_created_by = %s")
            where_parameters.append(tool_created_by)
        if agentic_app_created_by:
            where_clause.append("agentic_app_created_by = %s")
            where_parameters.append(agentic_app_created_by)

        if where_clause:
            where_clause = " WHERE " + " AND ".join(where_clause)
        else:
            where_clause = ""

        # Combine SET and WHERE clauses
        update_statement = f"UPDATE {table_name} SET " + \
            ", ".join(set_clause) + where_clause

        # Combine all parameters
        parameters = set_parameters + where_parameters

        # Execute the update statement
        cursor.execute(update_statement, tuple(parameters))
        connection.commit()

    finally:
        connection.close()



def delete_data_tool_agent_mapping(table_name="tool_agent_mapping_table",
                                   tool_id=None, agentic_application_id=None,
                                   tool_created_by=None, agentic_app_created_by=None):
    connection = psycopg2.connect(
        host=POSTGRESQL_HOST,
        database=DATABASE,
        user=POSTGRESQL_USER,
        password=POSTGRESQL_PASSWORD
    )

    try:
        cursor = connection.cursor()

        # Build DELETE query
        delete_statement = f"DELETE FROM {table_name}"
        where_clause = []
        parameters = []

        if tool_id:
            where_clause.append("tool_id = %s")
            parameters.append(tool_id)
        if agentic_application_id:
            where_clause.append("agentic_application_id = %s")
            parameters.append(agentic_application_id)
        if tool_created_by:
            where_clause.append("tool_created_by = %s")
            parameters.append(tool_created_by)
        if agentic_app_created_by:
            where_clause.append("agentic_app_created_by = %s")
            parameters.append(agentic_app_created_by)

        if where_clause:
            delete_statement += " WHERE " + " AND ".join(where_clause)
            # Execute the delete
            cursor.execute(delete_statement, tuple(parameters))
            connection.commit()

    finally:
        connection.close()


def create_tool_table_if_not_exists(table_name="tool_table"):
    """
    Creates the tool_table in PostgreSQL if it does not exist.

    Args:
        table_name (str): Name of the table to create. Defaults to 'tool_table'.
    """
    connection = psycopg2.connect(
        host=POSTGRESQL_HOST,
        database=DATABASE,
        user=POSTGRESQL_USER,
        password=POSTGRESQL_PASSWORD
    )

    try:
        cursor = connection.cursor()

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
        cursor.execute(create_statement)

        # Commit changes
        connection.commit()

    finally:
        connection.close()


def insert_into_tool_table(tool_data, table_name="tool_table"):
    """
    Inserts data into the tool table in PostgreSQL.

    Args:
        tool_data (dict): A dictionary containing the tool data to insert.
        table_name (str): Name of the PostgreSQL table to insert data into. Defaults to 'tool_table'.

    Returns:
        dict: Status of the operation, including success message or error details.
    """
    # Generate tool_id if not provided
    if not tool_data.get("tool_id"):
        tool_data["tool_id"] = str(uuid.uuid4())

    # Generate Docstring
    llm = load_model(model_name=tool_data["model_name"])
    updated_code_snippet = generate_docstring_tool_onboarding(
        llm=llm,
        tool_code_str=tool_data["code_snippet"],
        tool_description=tool_data["tool_description"]
    )
    if "Tool Onboarding Failed" in updated_code_snippet:
        return {
            "message": f"{updated_code_snippet}",
            "tool_id": "",
            "tool_name": f"{tool_data.get('tool_name', '')}",
            "model_name": f"{tool_data.get('model_name', '')}",
            "created_by": f"{tool_data.get('created_by', '')}",
            "is_created": False
        }
    tool_data["code_snippet"] = updated_code_snippet

    connection = psycopg2.connect(
        host=POSTGRESQL_HOST,
        database=DATABASE,
        user=POSTGRESQL_USER,
        password=POSTGRESQL_PASSWORD
    )

    try:
        cursor = connection.cursor()

        # Get current timestamp for created_on and updated_on
        now = datetime.now(timezone.utc)

        # Update tool_data with created_on and updated_on timestamps
        tool_data['created_on'] = now.isoformat()
        tool_data['updated_on'] = now.isoformat()

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
        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
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
        cursor.execute(insert_statement, values)
        connection.commit()

        # Insert tags into the tag-tool mapping table
        tags_status = insert_into_tag_tool_mapping(
            tag_ids=tool_data['tag_ids'], tool_id=tool_data['tool_id']
        )

        # Return success status
        return {
            "message": f"Successfully onboarded tool with tool_id: {tool_data.get('tool_id', '')}",
            "tool_id": f"{tool_data.get('tool_id', '')}",
            "tool_name": f"{tool_data.get('tool_name', '')}",
            "model_name": f"{tool_data.get('model_name', '')}",
            "tags_status": tags_status,
            "created_by": f"{tool_data.get('created_by', '')}",
            "is_created": True
        }

    except psycopg2.IntegrityError as e:
        # Handle constraints like primary key or unique violations
        return {
            "message": f"Integrity error inserting data into '{table_name}': {e}",
            "tool_id": "",
            "tool_name": f"{tool_data.get('tool_name', '')}",
            "model_name": f"{tool_data.get('model_name', '')}",
            "created_by": f"{tool_data.get('created_by', '')}",
            "is_created": False
        }

    except psycopg2.DatabaseError as e:
        # Handle general database errors
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
        connection.close()



async def get_tools(tool_table_name="tool_table"):
    """
    Retrieves tools from the tool table in PostgreSQL.

    Args:
        tool_table_name (str): The name of the tool table. Defaults to 'tool_table'.

    Returns:
        list: A list of tools from the tool table, represented as dictionaries.
    """
 
    connection = connection_pool.getconn()

    try:
        cursor = connection.cursor()

        # Build and execute the SELECT query
        query = f"""
        SELECT *
        FROM {tool_table_name}
        ORDER BY created_on DESC
        """
        cursor.execute(query)

        # Fetch all results and get column names
        rows = cursor.fetchall()
        columns = [column[0] for column in cursor.description]

        # Convert rows into a list of dictionaries
        results_as_dicts = [dict(zip(columns, row)) for row in rows]
        for result in results_as_dicts:
            result['tags'] = get_tags_by_tool(tool_id=result['tool_id'])
        return results_as_dicts

    except psycopg2.DatabaseError as e:
        if connection:
            connection.rollback()
        return []

    finally:
        # Ensure the connection is properly closed
        if cursor:
            cursor.close()
        if connection:
            connection_pool.putconn(connection)

def get_tools_by_page(tool_table_name="tool_table", name='', limit=20, page=1):
    """
    Retrieves tools from the PostgreSQL database with pagination support.

    Args:
        tool_table_name (str): Name of the tool table.
        name (str, optional): Tool name to filter by. Defaults to '' (no filtering).
        limit (int, optional): Number of results per page. Defaults to 20.
        page (int, optional): Page number for pagination. Defaults to 1.

    Returns:
        dict: A dictionary containing the total count of tools and the paginated tool details.
    """
    connection = psycopg2.connect(
        host=POSTGRESQL_HOST,
        database=DATABASE,
        user=POSTGRESQL_USER,
        password=POSTGRESQL_PASSWORD
    )

    try:
        cursor = connection.cursor()

        # Normalize name for case-insensitive search
        name_filter = f"%{name.lower()}%" if name else "%"

        # Get total count of tools
        total_tools_query = f"""
        SELECT COUNT(*)
        FROM {tool_table_name}
        WHERE LOWER(tool_name) LIKE %s
        """
        cursor.execute(total_tools_query, (name_filter,))
        total_tools = cursor.fetchone()[0]

        # Calculate offset for pagination
        offset = limit * (0 if page < 1 else page - 1)

        # Fetch tools for the current page
        query = f"""
        SELECT *
        FROM {tool_table_name}
        WHERE LOWER(tool_name) LIKE %s
        ORDER BY created_on DESC
        LIMIT %s OFFSET %s
        """
        cursor.execute(query, (name_filter, limit, offset))
        rows = cursor.fetchall()

        # Get column names and structure results
        columns = [column[0] for column in cursor.description]
        tools = [dict(zip(columns, row)) for row in rows]
        for result in tools:
            result['tags'] = get_tags_by_tool(tool_id=result['tool_id'])

        # Return total count and paginated details
        results = {"total_count": total_tools, "details": tools}
        return results

    except psycopg2.DatabaseError as e:
        return {"total_count": 0, "details": []}

    finally:
        connection.close()


def get_tools_by_id(tool_table_name="tool_table", tool_id=None, tool_name=None, created_by=None):
    """
    Retrieves tools from the PostgreSQL database based on provided parameters.

    Args:
        tool_table_name (str): Name of the tool table.
        tool_id (str, optional): Tool ID.
        tool_name (str, optional): Tool name.
        created_by (str, optional): Creator of the tool.

    Returns:
        list: A list of dictionaries representing the retrieved tools, or an empty list on error.
    """
    connection = psycopg2.connect(
        host=POSTGRESQL_HOST,
        database=DATABASE,
        user=POSTGRESQL_USER,
        password=POSTGRESQL_PASSWORD
    )

    try:
        cursor = connection.cursor()

        # Start building the base query
        query = f"SELECT * FROM {tool_table_name}"
        where_clauses = []
        params = []

        # Add filters to the WHERE clause
        if tool_id:
            where_clauses.append("tool_id = %s")
            params.append(tool_id)
        if tool_name:
            where_clauses.append("tool_name = %s")
            params.append(tool_name)
        if created_by:
            where_clauses.append("created_by = %s")
            params.append(created_by)

        # Append WHERE clause to the query if filters are provided
        if where_clauses:
            query += " WHERE " + " AND ".join(where_clauses)

        # Execute the query with parameters
        cursor.execute(query, tuple(params))

        # Fetch all results and get column names
        rows = cursor.fetchall()
        columns = [column[0] for column in cursor.description]

        # Convert rows into a list of dictionaries
        results_as_dicts = [dict(zip(columns, row)) for row in rows]
        for result in results_as_dicts:
            result['tags'] = get_tags_by_tool(tool_id=result['tool_id'])
        return results_as_dicts

    except psycopg2.DatabaseError as e:
        return []  # Return an empty list in case of an error

    finally:
        connection.close()



# Need to update
def update_tool_by_id_util(tool_data, table_name="tool_table", tool_id=None, tool_name=None):
    """
    Updates a tool in the PostgreSQL database based on the provided tool ID or tool name.

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

    connection = psycopg2.connect(
        host=POSTGRESQL_HOST,
        database=DATABASE,
        user=POSTGRESQL_USER,
        password=POSTGRESQL_PASSWORD
    )

    try:
        cursor = connection.cursor()

        # Get current timestamp for updated_on
        now = datetime.now(timezone.utc).isoformat()
        tool_data['updated_on'] = now

        # Build the UPDATE statement dynamically
        update_fields = [f"{column} = %s" for column in tool_data.keys()]
        query = f"UPDATE {table_name} SET {', '.join(update_fields)}"

        # Add the appropriate WHERE clause based on provided identifiers
        if tool_id:
            query += " WHERE tool_id = %s"
            params = list(tool_data.values()) + [tool_id]
        elif tool_name:
            query += " WHERE tool_name = %s"
            params = list(tool_data.values()) + [tool_name]

        # Execute the update statement
        cursor.execute(query, tuple(params))
        connection.commit()

        # Return True if rows were updated
        return cursor.rowcount > 0

    except psycopg2.DatabaseError as e:
        return False

    finally:
        connection.close()


def update_tool_by_id(model_name,
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
    Updates a tool in the PostgreSQL database based on the provided tool ID or tool name.

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
        return {
            "status_message": "Error: Must provide 'tool_id' or 'tool_name' to update a tool.",
            "details": [],
            "is_update": False
        }

    connection = psycopg2.connect(
        host=POSTGRESQL_HOST,
        database=DATABASE,
        user=POSTGRESQL_USER,
        password=POSTGRESQL_PASSWORD
    )

    try:
        cursor = connection.cursor()

        # Fetch tool data
        query = f"SELECT * FROM {table_name} WHERE "
        if tool_id_to_modify:
            query += "tool_id = %s"
            params = (tool_id_to_modify,)
        else:
            query += "tool_name = %s"
            params = (tool_name_to_modify,)

        cursor.execute(query, params)
        tool_data = cursor.fetchone()
        if not tool_data:
            return {
                "status_message": "Error: Tool not found.",
                "details": [],
                "is_update": False
            }

        # Check permissions
        columns = [col[0] for col in cursor.description]
        tool_data = dict(zip(columns, tool_data))

        if not is_admin and tool_data["created_by"] != user_email_id:
            return {
                "status_message": "Permission denied: Only the admin or the tool's creator can perform this action.",
                "details": [],
                "is_update": False
            }

        if not tool_description and not code_snippet and not created_by and updated_tag_id_list is None:
            return {
                "status_message": "Error: Please specify at least one of the following fields to modify: tool_description, code_snippet, tags.",
                "details": [],
                "is_update": False
            }

        # Update tags if provided
        tag_status = None
        if updated_tag_id_list is not None:
            if not clear_tags(tool_id=tool_data['tool_id']):
                return {
                    "status_message": "Failed to update the tool.",
                    "details": [],
                    "is_update": False
                }
            if not updated_tag_id_list:
                updated_tag_id_list = get_tags_by_id_or_name(tag_name="General")["tag_id"]
            tag_status = insert_into_tag_tool_mapping(tag_ids=updated_tag_id_list, tool_id=tool_data['tool_id'])

        if not tool_description and not code_snippet and not created_by:
            return {
                "status_message": "Tags updated successfully",
                "details": [],
                "tag_update_status": tag_status,
                "is_update": True
            }

        # Check if the tool is currently being used by any agentic applications
        df_tool_fil = pd.DataFrame(get_data_tool_agent_mapping(
            tool_id=tool_data["tool_id"],
            agentic_application_id=None,
            tool_created_by=None,
            agentic_app_created_by=None
        )).drop_duplicates(subset="agentic_application_id")

        # If tool is being used by any applications, return details and prevent update
        if len(df_tool_fil) > 0:
            df_tool_fil["agentic_application_name"] = df_tool_fil["agentic_application_id"].apply(lambda app_id: get_agents_by_id(
                agentic_application_id=app_id, agentic_application_type="")[0]["agentic_application_name"])

        if len(df_tool_fil) == 0:
            tool_update_eligibility = True
            agentic_application_id_list = []
        else:
            app_using_tool = len(df_tool_fil)
            info_display = df_tool_fil[[
                'agentic_application_id', 'agentic_application_name', 'agentic_app_created_by']].to_dict(orient="records")
            tool_update_eligibility = False
            response = {
                "status_message": f"The tool you are trying to update is being referenced by {app_using_tool} agentic applications.",
                "details": info_display,
                "is_update": False
            }
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
        updated_code_snippet = generate_docstring_tool_onboarding(
            llm=llm,
            tool_code_str=tool_data["code_snippet"],
            tool_description=tool_data["tool_description"]
        )
        if "Tool Onboarding Failed" in updated_code_snippet:
            return {
                "status_message": f"{updated_code_snippet.replace('Tool Onboarding Failed', 'Tool Update Failed')}",
                "details": [],
                "is_update": False
            }
        tool_data["code_snippet"] = updated_code_snippet

        # Update the tool in the database
        success = update_tool_by_id_util(
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
        return status

    except psycopg2.DatabaseError as e:
        return {
            "status_message": "An error occurred while updating the tool.",
            "details": [],
            "is_update": False
        }

    finally:
        connection.close()


def delete_tools_by_id(user_email_id,
                       is_admin=False,
                       tool_table_name="tool_table",
                       tool_id=None,
                       tool_name=None):
    """
    Deletes a tool from the PostgreSQL database based on the provided tool ID or tool name.

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
        return {
            "status_message": "Error: Must provide 'tool_id' or 'tool_name' to delete a tool.",
            "details": [],
            "is_delete": False
        }

    connection = psycopg2.connect(
        host=POSTGRESQL_HOST,
        database=DATABASE,
        user=POSTGRESQL_USER,
        password=POSTGRESQL_PASSWORD
    )

    try:
        cursor = connection.cursor()

        # Fetch tool details
        query = f"SELECT * FROM {tool_table_name} WHERE "
        if tool_id:
            query += "tool_id = %s"
            params = (tool_id,)
        else:
            query += "tool_name = %s"
            params = (tool_name,)

        cursor.execute(query, params)
        tool = cursor.fetchone()
        if not tool:
            return {
                "status_message": f"No Tool available with ID: {tool_id if tool_id else tool_name}",
                "details": [],
                "is_delete": False
            }

        # Check permissions
        columns = [col[0] for col in cursor.description]
        tool_data = dict(zip(columns, tool))

        if not is_admin and tool_data["created_by"] != user_email_id:
            return {
                "status_message": f"You do not have permission to delete Tool with Tool ID: {tool_data['tool_id']}. Only the admin or the tool's creator can perform this action.",
                "details": [],
                "is_delete": False
            }

        # Check for agentic application dependencies
        df_tool_fil = pd.DataFrame(get_data_tool_agent_mapping(
            tool_id=tool_data["tool_id"],
            agentic_application_id=None,
            tool_created_by=None,
            agentic_app_created_by=None
        )).drop_duplicates(subset="agentic_application_id")

        if len(df_tool_fil) > 0:
            df_tool_fil["agentic_application_name"] = df_tool_fil["agentic_application_id"].apply(
                lambda app_id: get_agents_by_id(agentic_application_id=app_id, agentic_application_type="")[0]["agentic_application_name"]
            )
            app_using_tool = len(df_tool_fil)
            info_display = df_tool_fil[[
                'agentic_application_id', 'agentic_application_name', 'agentic_app_created_by']].to_dict(orient="records")
            return {
                "status_message": f"The tool you are trying to delete is being referenced by {app_using_tool} agentic application(s).",
                "details": info_display,
                "is_delete": False
            }

        # Delete the tool
        delete_query = f"DELETE FROM {tool_table_name} WHERE tool_id = %s"
        cursor.execute(delete_query, (tool_data["tool_id"],))
        connection.commit()

        # Clean up associated tool-agent mappings
        delete_data_tool_agent_mapping(tool_id=tool_data["tool_id"])
        clear_tags(tool_id=tool_data['tool_id'])

        return {
            "status_message": f"Successfully Deleted Record for Tool with Tool ID: {tool_data['tool_id']}",
            "details": [],
            "is_delete": True
        }

    except psycopg2.DatabaseError as e:
        return {
            "status_message": f"An error occurred while deleting the tool: {e}",
            "details": [],
            "is_delete": False
        }

    finally:
        connection.close()


# Agent Table Management
def create_agent_table_if_not_exists(table_name="agent_table"):
    """
    Creates the agent_table in PostgreSQL if it does not exist.

    Args:
        table_name (str): Name of the table to create. Defaults to 'agent_table'.
    """
    connection = psycopg2.connect(
        host=POSTGRESQL_HOST,
        database=DATABASE,
        user=POSTGRESQL_USER,
        password=POSTGRESQL_PASSWORD
    )

    try:
        cursor = connection.cursor()

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
        cursor.execute(create_statement)

        # Commit changes
        connection.commit()

    finally:
        # Close the connection
        connection.close()


def insert_into_agent_table(agent_data, table_name="agent_table"):
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
    now = datetime.now(timezone.utc).isoformat()
    agent_data["created_on"] = now
    agent_data["updated_on"] = now

    # Generate agentic_application_id if not provided
    if not agent_data.get("agentic_application_id"):
        agent_data["agentic_application_id"] = str(uuid.uuid4())

    connection = psycopg2.connect(
        host=POSTGRESQL_HOST,
        database=DATABASE,
        user=POSTGRESQL_USER,
        password=POSTGRESQL_PASSWORD
    )

    try:
        cursor = connection.cursor()

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
        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """

        # Strip whitespace from string fields
        for key in agent_data.keys():
            if isinstance(agent_data[key], str):
                agent_data[key] = agent_data[key].strip()

        cursor.execute(insert_statement, (
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
        ))

        # Commit the transaction
        connection.commit()

        # Insert related tool-agent mapping data
        for tool_id in json.loads(agent_data["tools_id"]):
            tool_data = get_tools_by_id(tool_id=tool_id)[0]
            insert_data_tool_agent_mapping(
                tool_id=tool_id,
                agentic_application_id=agent_data["agentic_application_id"],
                tool_created_by=tool_data["created_by"],
                agentic_app_created_by=agent_data["created_by"]
            )

        # Insert tags into the tag-agent mapping table
        tags_status = insert_into_tag_agentic_app_mapping(
            tag_ids=agent_data["tag_ids"],
            agentic_application_id=agent_data["agentic_application_id"]
        )

        # Return success status
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

    except psycopg2.DatabaseError as e:
        # Return failure status in case of error
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
        connection.close()


def get_agents(agentic_application_type=None, agent_table_name="agent_table"):
    """
    Retrieves agents from the agent table in PostgreSQL.

    Args:
        agentic_application_type (str, optional): The type of agentic application to filter by. Defaults to None.
        agent_table_name (str): The name of the agent table. Defaults to 'agent_table'.

    Returns:
        list: A list of agents from the agent table, represented as dictionaries.
    """
    connection = psycopg2.connect(
        host=POSTGRESQL_HOST,
        database=DATABASE,
        user=POSTGRESQL_USER,
        password=POSTGRESQL_PASSWORD
    )

    try:
        cursor = connection.cursor()

        # Build the query based on whether a filter is provided
        if agentic_application_type:
            query = f"""
                SELECT *
                FROM {agent_table_name}
                WHERE agentic_application_type = %s
                ORDER BY created_on DESC
            """
            parameters = (agentic_application_type,)
        else:
            query = f"""
                SELECT *
                FROM {agent_table_name}
                ORDER BY created_on DESC
            """
            parameters = ()

        # Execute the query
        cursor.execute(query, parameters)
        rows = cursor.fetchall()

        # Fetch column names to convert results into a list of dictionaries
        columns = [column[0] for column in cursor.description]
        results_as_dicts = [dict(zip(columns, row)) for row in rows]

        # Add tags for each agent
        for result in results_as_dicts:
            result['tags'] = get_tags_by_agent(agent_id=result['agentic_application_id'])

        return results_as_dicts

    except psycopg2.DatabaseError as e:
        return []

    finally:
        # Ensure the database connection is closed
        connection.close()


def get_agents_by_page(user_email_id,
                       agentic_application_type=None,
                       agent_table_name="agent_table",
                       name='',
                       limit=20,
                       page=1,
                       is_admin=False):
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

    Returns:
        dict: A dictionary containing the total count of agents and the paginated agent details.
    """
    connection = psycopg2.connect(
        host=POSTGRESQL_HOST,
        database=DATABASE,
        user=POSTGRESQL_USER,
        password=POSTGRESQL_PASSWORD
    )

    try:
        cursor = connection.cursor()

        # Normalize input for case-insensitive search
        name_filter = f"%{name.lower()}%" if name else "%"
        type_filter = agentic_application_type if agentic_application_type else None

        # Build total count query
        total_count_query = f"""
        SELECT COUNT(*)
        FROM {agent_table_name}
        WHERE LOWER(agentic_application_name) LIKE %s
        """
        params = [name_filter]
        if type_filter:
            total_count_query += " AND agentic_application_type = %s"
            params.append(type_filter)
        if not is_admin:
            total_count_query += " AND created_by = %s"
            params.append(user_email_id)

        # Execute total count query
        cursor.execute(total_count_query, tuple(params))
        total_agents = cursor.fetchone()[0]

        # Calculate offset for pagination
        offset = limit * (0 if page < 1 else page - 1)

        # Build paginated query
        paginated_query = f"""
        SELECT *
        FROM {agent_table_name}
        WHERE LOWER(agentic_application_name) LIKE %s
        """
        params = [name_filter]
        if type_filter:
            paginated_query += " AND agentic_application_type = %s"
            params.append(type_filter)
        if not is_admin:
            paginated_query += " AND created_by = %s"
            params.append(user_email_id)
        paginated_query += " ORDER BY created_on DESC LIMIT %s OFFSET %s"
        params.extend([limit, offset])

        # Execute paginated query
        cursor.execute(paginated_query, tuple(params))
        rows = cursor.fetchall()

        # Fetch column names and structure results
        columns = [column[0] for column in cursor.description]
        agents = [dict(zip(columns, row)) for row in rows]
        for result in agents:
            result['tags'] = get_tags_by_agent(agent_id=result['agentic_application_id'])

        # Return results
        return {"total_count": total_agents, "details": agents}

    except psycopg2.DatabaseError as e:
        return {"total_count": 0, "details": []}

    finally:
        if 'connection' in locals():
            connection.close()


def get_agents_by_id(agentic_application_type="",
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
    connection = psycopg2.connect(
        host=POSTGRESQL_HOST,
        database=DATABASE,
        user=POSTGRESQL_USER,
        password=POSTGRESQL_PASSWORD
    )

    try:
        cursor = connection.cursor()

        # Start building the base query
        query = f"SELECT * FROM {agent_table_name}"
        where_clauses = []
        params = []

        # Add filters dynamically
        if agentic_application_id:
            where_clauses.append("agentic_application_id = %s")
            params.append(agentic_application_id)
        if agentic_application_name:
            where_clauses.append("agentic_application_name = %s")
            params.append(agentic_application_name)
        if created_by:
            where_clauses.append("created_by = %s")
            params.append(created_by)
        if agentic_application_type:
            where_clauses.append("agentic_application_type = %s")
            params.append(agentic_application_type)

        # Append WHERE clause if filters are provided
        if where_clauses:
            query += " WHERE " + " AND ".join(where_clauses)

        # Execute the query with parameters
        cursor.execute(query, tuple(params))
        rows = cursor.fetchall()

        # Fetch column names to structure results
        columns = [column[0] for column in cursor.description]
        results_as_dicts = [dict(zip(columns, row)) for row in rows]

        # Add tags for each agent
        for result in results_as_dicts:
            result['tags'] = get_tags_by_agent(agent_id=result['agentic_application_id'])

        return results_as_dicts

    except psycopg2.DatabaseError as e:
        return []  # Return an empty list in case of an error

    finally:
        if connection in locals():
            connection.close()


def get_agents_by_id_studio(agentic_application_id, agent_table_name="agent_table", tool_table_name="tool_table"):
    """
    Retrieves agent details along with tool information from the PostgreSQL database.

    Args:
        agentic_application_id (str): The agentic application ID.
        agent_table_name (str): Name of the agent table (default is "agent_table").
        tool_table_name (str): Name of the tool table (default is "tool_table").

    Returns:
        dict: A dictionary with agent details and associated tools information.
    """
    connection = psycopg2.connect(
        host=POSTGRESQL_HOST,
        database=DATABASE,
        user=POSTGRESQL_USER,
        password=POSTGRESQL_PASSWORD
    )

    try:
        cursor = connection.cursor()

        # Retrieve agent details
        query = f"SELECT * FROM {agent_table_name} WHERE agentic_application_id = %s"
        cursor.execute(query, (agentic_application_id,))
        agent_row = cursor.fetchone()

        if not agent_row:
            return {}  # Return an empty dictionary if the agent is not found

        # Fetch column names and structure result as a dictionary
        agent_columns = [column[0] for column in cursor.description]
        agent_details = dict(zip(agent_columns, agent_row))

        # Parse tools_id from the agent details
        tools_id = json.loads(agent_details.get("tools_id", "[]"))

        # Retrieve tool information for each tool_id
        tool_info_list = []
        for tool_id in tools_id:
            tool_query = f"""
            SELECT tool_id, tool_name, tool_description, created_by, created_on
            FROM {tool_table_name}
            WHERE tool_id = %s
            """
            cursor.execute(tool_query, (tool_id,))
            tool_row = cursor.fetchone()

            if tool_row:
                # Fetch tool column names and structure result as a dictionary
                tool_columns = [column[0] for column in cursor.description]
                tool_info_list.append(dict(zip(tool_columns, tool_row)))
                tool_info_list[-1]['tags'] = get_tags_by_tool(tool_info_list[-1]['tool_id'])


        # Update agent details with tool information
        agent_details["tools_id"] = tool_info_list

        return agent_details

    except psycopg2.DatabaseError as e:
        return {}

    finally:
        connection.close()


def update_agent_by_id_util(agent_data, table_name="agent_table", agentic_application_id=None, agentic_application_name=None):
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

    connection = psycopg2.connect(
        host=POSTGRESQL_HOST,
        database=DATABASE,
        user=POSTGRESQL_USER,
        password=POSTGRESQL_PASSWORD
    )

    try:
        cursor = connection.cursor()

        # Get current timestamp for `updated_on`
        agent_data["updated_on"] = datetime.now(timezone.utc).isoformat()

        # Prepare the update query dynamically
        update_fields = [f"{column} = %s" for column in agent_data.keys()]
        query = f"UPDATE {table_name} SET {', '.join(update_fields)}"

        # Add WHERE clause based on the identifier
        if agentic_application_id:
            query += " WHERE agentic_application_id = %s"
            params = list(agent_data.values()) + [agentic_application_id]
        elif agentic_application_name:
            query += " WHERE agentic_application_name = %s"
            params = list(agent_data.values()) + [agentic_application_name]

        # Execute the query
        cursor.execute(query, tuple(params))
        connection.commit()

        # Clean up associated tool-agent mappings
        delete_data_tool_agent_mapping(agentic_application_id=agent_data['agentic_application_id'])
        for tool_id in json.loads(agent_data['tools_id']):
            insert_data_tool_agent_mapping(
                tool_id=tool_id,
                agentic_application_id=agent_data["agentic_application_id"],
                tool_created_by=get_tools_by_id(tool_id=tool_id)[0]["created_by"],
                agentic_app_created_by=agent_data["created_by"]
            )

        return cursor.rowcount > 0

    except psycopg2.DatabaseError as e:
        return False

    finally:
        connection.close()


def update_agent_by_id(model_name,
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
        return {
            "status_message": "Error: Must provide 'agentic_application_id' to update an agentic application.",
            "is_update": False
        }

    # Fetch current agent data
    agents = get_agents_by_id(
        agentic_application_type="",
        agent_table_name=table_name,
        agentic_application_id=agentic_application_id_to_modify,
        agentic_application_name=agentic_application_name_to_modify
    )
    if not agents:
        return {
            "status_message": "Please validate the AGENTIC APPLICATION ID.",
            "is_update": False
        }
    agent = agents[0]
    #agent["tools_id"] = json.loads(agent["tools_id"])
    agent["tools_id"] = agent["tools_id"]
    agent["system_prompt"] = agent["system_prompt"]

    if not agentic_application_description and not agentic_application_workflow_description and not system_prompt and not tools_id and not tools_id_to_add and not tools_id_to_remove and not created_by and not updated_tag_id_list:
        return {
            "status_message": "Error: Please specify at least one of the following fields to modify: application description, application workflow description, system prompt, tools id, tools id to add, tools id to remove, tags.",
            "is_update": False
        }

    # Check permissions
    if not is_admin and agent["created_by"] != user_email_id:
        return {
            "status_message": f"You do not have permission to update Agentic Application with ID: {agent['agentic_application_id']}.",
            "is_update": False
        }

    tag_status = None
    if updated_tag_id_list != None:
        if not clear_tags(agent_id=agentic_application_id_to_modify):
            return {
                    "status_message": "Failed to update the agent.",
                    "is_update": False
                }
        if not updated_tag_id_list:
            updated_tag_id_list = get_tags_by_id_or_name(tag_name="General")["tag_id"]
        tag_status = insert_into_tag_agentic_app_mapping(tag_ids=updated_tag_id_list,
                                                         agentic_application_id=agentic_application_id_to_modify)

    if not agentic_application_description and not agentic_application_workflow_description and not system_prompt and not tools_id and not tools_id_to_add and not tools_id_to_remove and not created_by:
        return {
            "status_message": "Tags updated successfully",
            "tag_update_status": tag_status,
            "is_update": True
        }

    # Validate tool IDs (all tools to add, remove, and current ones)
    val_tools_id = tools_id + tools_id_to_add + tools_id_to_remove
    val_tools_id = list(set(val_tools_id))
    val_tools_resp = validate_tool_id(tools_id=val_tools_id)
    if "Error" in val_tools_resp:
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
            response = react_agent_onboarding(
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
            response = react_multi_agent_onboarding(
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
    success = update_agent_by_id_util(
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
    return status

def delete_agent_by_id(user_email_id,
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
        return {
            "status_message": "Error: Must provide 'agentic_application_id' or 'agentic_application_name' to delete an agentic application.",
            "is_delete": False
        }

    connection = psycopg2.connect(
        host=POSTGRESQL_HOST,
        database=DATABASE,
        user=POSTGRESQL_USER,
        password=POSTGRESQL_PASSWORD
    )

    try:
        cursor = connection.cursor()

        # Retrieve agentic application details
        query = f"SELECT * FROM {agent_table_name} WHERE "
        params = []
        if agentic_application_id:
            query += "agentic_application_id = %s"
            params.append(agentic_application_id)
        elif agentic_application_name:
            query += "agentic_application_name = %s"
            params.append(agentic_application_name)

        cursor.execute(query, tuple(params))
        agent = cursor.fetchone()

        if not agent:
            return {
                "status_message": f"No Agentic Application available with ID: {agentic_application_id or agentic_application_name}",
                "is_delete": False
            }

        # Fetch column names to structure agent as a dictionary
        columns = [column[0] for column in cursor.description]
        agent_data = dict(zip(columns, agent))

         # Check permissions
        if is_admin or agent_data["created_by"] == user_email_id:
            can_delete = True
        else:
            can_delete = False

        if not can_delete:
            return {
                "status_message": f"""You do not have permission to delete Agentic Application with ID: {agent_data['agentic_application_id']}. Only the admin or the creator can perform this action.""",
                "is_delete": False
            }

        # Delete the agentic application
        delete_query = f"DELETE FROM {agent_table_name} WHERE "
        if agentic_application_id:
            delete_query += "agentic_application_id = %s"
            params = [agentic_application_id]
        elif agentic_application_name:
            delete_query += "agentic_application_name = %s"
            params = [agentic_application_name]

        cursor.execute(delete_query, tuple(params))
        connection.commit()

        # Clean up associated tool-agent mappings
        delete_data_tool_agent_mapping(
            agentic_application_id=agent_data["agentic_application_id"]
        )
        clear_tags(agent_id=agent_data["agentic_application_id"])

        return {
            "status_message": f"Successfully Deleted Record for Agentic Application with ID: {agentic_application_id or agent_data['agentic_application_id']}.",
            "is_delete": True
        }

    except psycopg2.DatabaseError as e:
        return {
            "status_message": f"An error occurred while deleting the agent: {e}",
            "is_delete": False
        }

    finally:
        connection.close()


# Agent Onboarding Helper Functions
def validate_tool_id(tools_id: list):
    """
    Validates whether the given tool IDs exist in the database.

    Args:
        tools_id (list): A list of tool IDs to validate.

    Returns:
        str: Validation result message indicating success or failure.
    """
    if tools_id:
        for idx, tool_id in enumerate(tools_id):
            try:
                # Check if the tool exists
                get_tools_by_id(tool_id=tool_id)[0]
            except Exception as e:
                return f"Error: The tool with Tool ID: {tool_id} is not available. Please validate the provided tool id."
        return "Tool Check Complete. All tools are available."
    return "No Tool ID to check"


def validate_agent_id(agents_id: list):
    """
    Validates whether the given agent IDs exist in the database.

    Args:
        agents_id (list): A list of tool IDs to validate.

    Returns:
        str: Validation result message indicating success or failure.
    """
    if agents_id:
        for idx, agent_id in enumerate(agents_id):
            try:
                # Check if the agent exists
                get_agents_by_id(agentic_application_id=agent_id)[0]
            except Exception as e:
                return f"Error: The agent with Agentic Application ID: {agent_id} is not available. Please validate the provided agent id."
        return "Agent Check Complete. All agents are available."
    return "No Agentic Application ID to check"


def extract_tools_using_tools_id(tools_id):
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
        single_tool_info_df = get_tools_by_id(tool_id=tool_id)[0]
        single_tool_info["Tool_Name"] = single_tool_info_df["tool_name"]
        single_tool_info["Tool_Description"] = single_tool_info_df["tool_description"]
        single_tool_info["code_snippet"] = single_tool_info_df["code_snippet"]
        single_tool_info['tags'] = single_tool_info_df['tags']
        tools_info_user[f"Tool_{idx+1}"] = single_tool_info

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
        tool_prompt = "No tools are available"
    return tool_prompt


def react_agent_onboarding(agent_name: str,
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
        agent_check = get_agents_by_id(agentic_application_name=agent_name,
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
            return status

    tools_id = list(set(tools_id))
    # Validate tool IDs if provided
    if tools_id:
        val_tools_resp = validate_tool_id(tools_id=tools_id)
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
            return status

    tools_info = extract_tools_using_tools_id(tools_id)
    tool_prompt = generate_tool_prompt(tools_info)
    llm = load_model(model_name=model_name)
    react_system_prompt = react_system_prompt_gen_func(agent_name=agent_name,
                                                       agent_goal=agent_goal,
                                                       workflow_description=workflow_description,
                                                       tool_prompt=tool_prompt,
                                                       llm=llm)
    if only_return_prompt:
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
    agent_creation_status = insert_into_agent_table(agent_data)
    return agent_creation_status

def get_agent_tool_config_react_agent(agentic_application_id, llm):
    agent_tools_config = {}
    # Retrieve agent details from the database
    agentic_app_info = get_agents_by_id(agentic_application_id=agentic_application_id)

    agent_tools_config_master = {}
    agent_tools_config = {}
    agent_tools_config["SYSTEM_PROMPT"] = json.loads(agentic_app_info[0]["system_prompt"])["SYSTEM_PROMPT_REACT_AGENT"]
    agent_tools_config["TOOLS_INFO"] = json.loads(agentic_app_info[0]["tools_id"])
    agent_tools_config["agentic_application_description"] = agentic_app_info[0]["agentic_application_description"]
    # agent_tools_config["agentic_application_executor"] = build_executor_chains_meta_agent(llm, agent_tools_config)

    agent_tools_config_master[agentic_app_info[0]["agentic_application_name"]] = agent_tools_config
    return agent_tools_config_master

def worker_agents_config_prompt(agentic_app_ids: list, llm):
    ### Config for the Worker Agents
    agent_configs = {}
    for agent_id in agentic_app_ids:
        agent_config_info = get_agent_tool_config_react_agent(agentic_application_id=agent_id, llm=llm)
        agent_configs.update(agent_config_info)

    ### Worker Agents Prompt
    members = list(agent_configs.keys())

    agent_configs_lower_case_copy = {}
    worker_agents_prompt = ""
    for k, v in agent_configs.items():
        worker_agents_prompt += f"""Agentic Application Name: {k}\nAgentic Application Description: {v["agentic_application_description"]}\n\n"""
        agent_configs_lower_case_copy[str(k).lower()] = v
    agent_configs.update(agent_configs_lower_case_copy)
    return agent_configs, worker_agents_prompt, members


def react_multi_agent_onboarding(agent_name: str,
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
        agent_check = get_agents_by_id(agentic_application_name=agent_name,
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
            return status

    tools_id = list(set(tools_id))
    # Validate tool IDs if provided
    if tools_id:
        val_tools_resp = validate_tool_id(tools_id=tools_id)
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
            return status

    tools_info = extract_tools_using_tools_id(tools_id)
    tool_prompt = generate_tool_prompt(tools_info)
    llm = load_model(model_name=model_name)
    react_multi_system_prompt = planner_executor_critic_builder(agent_name=agent_name,
                                                       agent_goal=agent_goal,
                                                       workflow_description=workflow_description,
                                                       tool_prompt=tool_prompt,
                                                       llm=llm)
    if only_return_prompt:
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
    agent_creation_status = insert_into_agent_table(agent_data)
    return agent_creation_status



def insert_chat_history_sqlite(table_name,
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
    connection = psycopg2.connect(
        host=POSTGRESQL_HOST,
        database=DATABASE,
        user=POSTGRESQL_USER,
        password=POSTGRESQL_PASSWORD
    )

    try:
        cursor = connection.cursor()

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
        cursor.execute(create_statement)

        # Insert the chat history into the table
        insert_statement = f"""
        INSERT INTO {table_name} (
            session_id,
            start_timestamp,
            end_timestamp,
            human_message,
            ai_message
        ) VALUES (%s, %s, %s, %s, %s)
        """
        cursor.execute(insert_statement, (
            session_id,
            start_timestamp,
            end_timestamp,
            human_message,
            ai_message
        ))

        # Commit the transaction
        connection.commit()

    except psycopg2.DatabaseError as e:
        return {"total_count": 0, "details": []}

    finally:
        if 'connection' in locals():
            connection.close()


def get_long_term_memory_sqlite(table_name, session_id, conversation_limit=30):
    """
    Retrieves the most recent chat history for a given session from a PostgreSQL table.

    Args:
        table_name (str): The name of the table to query.
        session_id (str): The ID of the chat session.
        conversation_limit (int, optional): The maximum number of conversations to retrieve. Defaults to 30.

    Returns:
        list of dict: A list of chat history records sorted by end_timestamp in descending order.
    """
    connection = psycopg2.connect(
        host=POSTGRESQL_HOST,
        database=DATABASE,
        user=POSTGRESQL_USER,
        password=POSTGRESQL_PASSWORD
    )

    try:
        cursor = connection.cursor()

       # Check if the table exists
        check_table_query = """
        SELECT EXISTS (
            SELECT 1
            FROM information_schema.tables
            WHERE table_name = %s
        );
        """
        cursor.execute(check_table_query, (table_name,))
        table_exists = cursor.fetchone()[0]

        if table_exists:

            # Query to retrieve the most recent chat history for the session
            query = f"""
            SELECT session_id, start_timestamp, end_timestamp, human_message, ai_message
            FROM {table_name}
            WHERE session_id = %s
            ORDER BY end_timestamp DESC
            LIMIT %s
            """
            cursor.execute(query, (session_id, conversation_limit))
            records = cursor.fetchall()

            # Convert the retrieved records into a list of dictionaries
            chat_history = [
                {
                    "session_id": row[0],
                    "start_timestamp": row[1],
                    "end_timestamp": row[2],
                    "human_message": row[3],
                    "ai_message": row[4]
                }
                for row in records
            ]

            return chat_history

    except psycopg2.DatabaseError as e:
        return []

    finally:
        connection.close()


def delete_by_session_id_sqlite(table_name, session_id):
    """
    Deletes records from a PostgreSQL table by session_id.

    Args:
        table_name (str): The name of the table.
        session_id (str): The session ID to delete records for.

    Returns:
        bool: True if deletion was successful, False otherwise.
    """
    connection = psycopg2.connect(
        host=POSTGRESQL_HOST,
        database=DATABASE,
        user=POSTGRESQL_USER,
        password=POSTGRESQL_PASSWORD
    )

    try:
        cursor = connection.cursor()

        # Delete query
        delete_query = f"""
        DELETE FROM {table_name} WHERE session_id = %s;
        """
        cursor.execute(delete_query, (session_id,))
        connection.commit()

        return cursor.rowcount > 0  # Returns True if rows were deleted, False otherwise

    except psycopg2.DatabaseError as e:
        return False

    finally:
        connection.close()


def update_latest_query_response_with_tag(agentic_application_id, session_id, message_type="ai", start_tag="[liked_by_user:]", end_tag="[:liked_by_user]"):
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

    connection = psycopg2.connect(
        host=POSTGRESQL_HOST,
        database=DATABASE,
        user=POSTGRESQL_USER,
        password=POSTGRESQL_PASSWORD
    )

    try:
        cursor = connection.cursor()

        # Determine the column to update based on message_type
        message_type = message_type.lower()
        if message_type == "human":
            message_column = "human_message"
        elif message_type == "ai":
            message_column = "ai_message"
        else:
            return None

        # Get the latest message for the given session_id
        query = f"""
        SELECT rowid, {message_column}
        FROM {table_name}
        WHERE session_id = %s
        ORDER BY end_timestamp DESC
        LIMIT 1
        """
        cursor.execute(query, (session_id,))
        result = cursor.fetchone()

        if result:
            rowid, message = result

            # Check if the tags are already present
            if message.startswith(start_tag) and message.endswith(end_tag):
                # Remove the tags
                updated_message = message[len(start_tag):-len(end_tag)]
                update_status = False
            else:
                # Add the tags
                updated_message = f"{start_tag}{message}{end_tag}"
                update_status = True

            # Update the message in the database
            update_query = f"UPDATE {table_name} SET {message_column} = ? WHERE rowid = ?"
            cursor.execute(update_query, (updated_message.strip(), rowid))

            # Commit the changes
            connection.commit()
            return update_status

        return None

    except psycopg2.DatabaseError as e:
        return None

    finally:
        connection.close()


import psycopg2
import uuid
from psycopg2 import sql

def create_tags_table_if_not_exists(table_name="tags_table"):
    connection = psycopg2.connect(
        host=POSTGRESQL_HOST,
        database=DATABASE,
        user=POSTGRESQL_USER,
        password=POSTGRESQL_PASSWORD
    )
    try:
        cursor = connection.cursor()

        # Using sql.SQL to safely insert the table name
        create_statement = sql.SQL("""
        CREATE TABLE IF NOT EXISTS {table_name} (
            tag_id TEXT PRIMARY KEY,
            tag_name TEXT UNIQUE NOT NULL,
            created_by TEXT NOT NULL
        )
        """).format(table_name=sql.Identifier(table_name))

        cursor.execute(create_statement)

        # Default tags to insert
        default_tags = [
            'General', 'Healthcare & Life Sciences', 'Finance & Banking', 'Education & Training', 'Retail & E-commerce',
            'Insurance', 'Logistics', 'Utilities', 'Travel and Hospitality', 'Agri Industry', 'Manufacturing', 'Metals and Mining',
        ]

        for default_tag in default_tags:
            # Use ON CONFLICT DO NOTHING to prevent inserting duplicates based on tag_name
            insert_statement = sql.SQL("""
            INSERT INTO {table_name} (tag_id, tag_name, created_by)
            VALUES (%s, %s, 'system@infosys.com')
            ON CONFLICT (tag_name) DO NOTHING
            """).format(table_name=sql.Identifier(table_name))

            cursor.execute(insert_statement, (str(uuid.uuid4()), default_tag))

        connection.commit()

    finally:
        connection.close()


def insert_into_tags_table(tag_data, table_name="tags_table"):
    """
    Inserts data into the tags table in SQLite.

    Args:
        tag_data (dict): A dictionary containing the tag data to insert.
        table_name (str): Name of the SQLite table to insert data into. Defaults to 'tags_table'.

    Returns:
        dict: Status of the operation, including success message or error details.
    """
    # Generate tag_id if not provided
    if not tag_data.get("tag_id", None):
        tag_data["tag_id"] = str(uuid.uuid4())

    connection = psycopg2.connect(
        host=POSTGRESQL_HOST,
        database=DATABASE,
        user=POSTGRESQL_USER,
        password=POSTGRESQL_PASSWORD
    )

    try:
        cursor = connection.cursor()

        # Build SQL INSERT statement
        insert_statement = f"""
        INSERT INTO {table_name} (
            tag_id,
            tag_name,
            created_by
        ) VALUES (&s, %s, %s)
        """

        # Extract values from tag_data for insertion
        values = (
            tag_data.get("tag_id"),
            tag_data.get("tag_name").strip(),
            tag_data.get("created_by")
        )

        # Execute the insert statement
        cursor.execute(insert_statement, values)
        connection.commit()

        # Return success status
        status = {
            "message": f"Successfully inserted tag with tag_id: {tag_data.get('tag_id', '')}",
            "tag_id": f"{tag_data.get('tag_id', '')}",
            "tag_name": f"{tag_data.get('tag_name', '')}",
            "created_by": f"{tag_data.get('created_by', '')}",
            "is_created": True
        }

    except psycopg2.IntegrityError as e:
        # Handle constraints like primary key or unique violations
        status = {
            "message": f"Integrity error inserting data into '{table_name}': {e}",
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
        connection.close()

    return status

def get_tags(tag_table_name="tags_table"):
    """
    Retrieves tags from the tags table in SQLite.

    Args:
        tag_table_name (str): The name of the tags table. Defaults to 'tags_table'.

    Returns:
        list: A list of tags from the tags table, represented as dictionaries.
    """
    connection = psycopg2.connect(
        host=POSTGRESQL_HOST,
        database=DATABASE,
        user=POSTGRESQL_USER,
        password=POSTGRESQL_PASSWORD
    )

    try:
        cursor = connection.cursor()

        # Build and execute the SELECT query
        query = f"""
        SELECT *
        FROM {tag_table_name}
        """
        cursor.execute(query)

        # Fetch all results and get column names
        rows = cursor.fetchall()
        columns = [column[0] for column in cursor.description]

        # Convert rows into a list of dictionaries
        results_as_dicts = [dict(zip(columns, row)) for row in rows]
        return results_as_dicts

    except psycopg2.DatabaseError as e:
        return []

    finally:
        # Ensure the connection is properly closed
        connection.close()

def get_tags_by_id_or_name(tag_id=None, tag_name=None, tag_table_name="tags_table"):
    """
    Retrieves tags from the SQLite database based on provided parameters.

    Args:
        tag_table_name (str): Name of the tags table.
        tag_id (str, optional): Tag ID.
        tag_name (str, optional): Tag name.

    Returns:
        list: A list of dictionaries representing the retrieved tags, or an empty list on error.
    """
    connection = psycopg2.connect(
        host=POSTGRESQL_HOST,
        database=DATABASE,
        user=POSTGRESQL_USER,
        password=POSTGRESQL_PASSWORD
    )
    try:
        cursor = connection.cursor()

        # Start building the base query
        query = f"SELECT * FROM {tag_table_name}"
        where_clauses = []
        params = []

        # Add filters to the WHERE clause
        if tag_id:
            where_clauses.append("tag_id = %s")
            params.append(tag_id)
        if tag_name:
            where_clauses.append("tag_name = %s")
            params.append(tag_name)

        # Append WHERE clause to the query if filters are provided
        if where_clauses:
            query += " WHERE " + " AND ".join(where_clauses)

        # Execute the query with parameters
        cursor.execute(query, params)

        # Fetch all results and get column names
        rows = cursor.fetchall()
        columns = [column[0] for column in cursor.description]

        # Convert rows into a list of dictionaries
        results_as_dicts = [dict(zip(columns, row)) for row in rows]
        return results_as_dicts[0]

    except psycopg2.DatabaseError as e:
        return {}  # Return an empty dictionary in case of an error

    finally:
        connection.close()

def update_tag_name_by_id_or_name(tag_id=None, tag_name=None, new_tag_name=None, created_by=None, table_name="tags_table"):
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

    connection = psycopg2.connect(
        host=POSTGRESQL_HOST,
        database=DATABASE,
        user=POSTGRESQL_USER,
        password=POSTGRESQL_PASSWORD
    )

    try:
        cursor = connection.cursor()

        # Build SQL UPDATE statement
        update_statement = f"""
        UPDATE {table_name}
        SET tag_name = %s
        WHERE (tag_id = %s OR tag_name = %s) AND created_by = %s
        """

        # Execute the update statement
        cursor.execute(update_statement, (new_tag_name, tag_id, tag_name, created_by))
        connection.commit()

        # Check if any row was updated
        if cursor.rowcount == 0:
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

    except psycopg2.DatabaseError as e:
        # Handle general database errors
        status = {
            "message": f"Error updating tag in '{table_name}' table: {e}",
            "tag_id": tag_id,
            "tag_name": tag_name,
            "is_updated": False
        }

    finally:
        # Ensure the connection is properly closed
        connection.close()

    return status

def delete_tag_by_id_or_name(tag_id=None, tag_name=None, created_by=None, table_name="tags_table"):
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

    connection = psycopg2.connect(
        host=POSTGRESQL_HOST,
        database=DATABASE,
        user=POSTGRESQL_USER,
        password=POSTGRESQL_PASSWORD
    )

    try:
        cursor = connection.cursor()

        # Build SQL DELETE statement
        delete_statement = f"""
        DELETE FROM {table_name}
        WHERE (tag_id = %s OR tag_name = %s) AND created_by = %s
        """
        if is_tag_in_use(tag_id=tag_id, tag_name=tag_name):
            return {
                "message": f"Cannot delete tag, it is begin used by an agent or a tool",
                "tag_id": tag_id,
                "tag_name": tag_name,
                "is_deleted": False
            }

        # Execute the delete statement
        cursor.execute(delete_statement, (tag_id, tag_name, created_by))
        connection.commit()

        # Check if any row was deleted
        if cursor.rowcount == 0:
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

    except psycopg2.DatabaseError as e:
        # Handle general database errors
        status = {
            "message": f"Error deleting tag from '{table_name}' table: {e}",
            "tag_id": tag_id,
            "tag_name": tag_name,
            "is_deleted": False
        }

    finally:
        # Ensure the connection is properly closed
        connection.close()

    return status



# Tags Helper functions

def clear_tags(tool_id=None, agent_id=None, tool_tag_mapping_table_name="tag_tool_mapping_table", agent_tag_mapping_table_name="tag_agentic_app_mapping_table"):
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
        return False

    connection = psycopg2.connect(
        host=POSTGRESQL_HOST,
        database=DATABASE,
        user=POSTGRESQL_USER,
        password=POSTGRESQL_PASSWORD
    )
    try:
        cursor = connection.cursor()

        if tool_id:
            # Clear tags for the given tool_id
            query = f"DELETE FROM {tool_tag_mapping_table_name} WHERE tool_id = %s"
            cursor.execute(query, (tool_id,))
        elif agent_id:
            # Clear tags for the given agent_id
            query = f"DELETE FROM {agent_tag_mapping_table_name} WHERE agentic_application_id = %s"
            cursor.execute(query, (agent_id,))

        # Commit the changes
        connection.commit()
        return True

    except psycopg2.DatabaseError as e:
        return False

    finally:
        connection.close()

def is_tag_in_use(tag_id=None, tag_name=None, tag_table_name="tags_table", tool_tag_mapping_table_name="tag_tool_mapping_table", agent_tag_mapping_table_name="tag_agentic_app_mapping_table"):
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
        return False

    connection = psycopg2.connect(
        host=POSTGRESQL_HOST,
        database=DATABASE,
        user=POSTGRESQL_USER,
        password=POSTGRESQL_PASSWORD
    )

    try:
        cursor = connection.cursor()

        # Get the tag_id if tag_name is provided
        if tag_name:
            query = f"SELECT tag_id FROM {tag_table_name} WHERE tag_name = %s"
            cursor.execute(query, (tag_name,))
            result = cursor.fetchone()
            if result:
                tag_id = result[0]
            else:
                return False

        # Check if the tag_id is used in the tool_tag_mapping_table
        query = f"SELECT 1 FROM {tool_tag_mapping_table_name} WHERE tag_id = %s LIMIT 1"
        cursor.execute(query, (tag_id,))
        if cursor.fetchone():
            return True

        # Check if the tag_id is used in the agent_tag_mapping_table
        query = f"SELECT 1 FROM {agent_tag_mapping_table_name} WHERE tag_id = %s LIMIT 1"
        cursor.execute(query, (tag_id,))
        if cursor.fetchone():
            return True

        return False

    except psycopg2.DatabaseError as e:
        return False

    finally:
        connection.close()


import psycopg2
from psycopg2 import sql

def assign_general_tag_to_untagged_items(general_tag_name="General"):
    """
    Assigns a general tag to all agents and tools that currently have no tags.

    Args:
        general_tag_name (str): The name of the general tag. Defaults to 'General'.

    Returns:
        bool: True if the operation was successful, False otherwise.
    """
    try:
        # PostgreSQL connection
        connection = psycopg2.connect(
            host=POSTGRESQL_HOST,
            database=DATABASE,
            user=POSTGRESQL_USER,
            password=POSTGRESQL_PASSWORD
        )
        cursor = connection.cursor()

        # Table names
        tag_table_name = "tags_table"
        tool_table_name = "tool_table"
        agent_table_name = "agent_table"
        tool_tag_mapping_table_name = "tag_tool_mapping_table"
        agent_tag_mapping_table_name = "tag_agentic_app_mapping_table"

        # 1️⃣ Check if the general tag exists
        query = f"SELECT tag_id FROM {tag_table_name} WHERE tag_name = %s"
        cursor.execute(query, (general_tag_name,))
        result = cursor.fetchone()

        if result:
            general_tag_id = result[0]
        else:
            # Insert general tag if it doesn't exist
            query = f"INSERT INTO {tag_table_name} (tag_name) VALUES (%s) RETURNING tag_id"
            cursor.execute(query, (general_tag_name,))
            general_tag_id = cursor.fetchone()[0]

        # 2️⃣ Assign general tag to untagged tools
        query = f"""
            SELECT tl.tool_id
            FROM {tool_table_name} tl
            LEFT JOIN {tool_tag_mapping_table_name} m ON tl.tool_id = m.tool_id
            WHERE m.tag_id IS NULL
        """
        cursor.execute(query)
        untagged_tools = [row[0] for row in cursor.fetchall()]

        # Batch insert for tools
        if untagged_tools:
            insert_query = f"""
                INSERT INTO {tool_tag_mapping_table_name} (tool_id, tag_id)
                VALUES %s
            """
            values = [(tool_id, general_tag_id) for tool_id in untagged_tools]
            psycopg2.extras.execute_values(cursor, insert_query, values)

        # 3️⃣ Assign general tag to untagged agents
        query = f"""
            SELECT a.agentic_application_id
            FROM {agent_table_name} a
            LEFT JOIN {agent_tag_mapping_table_name} m ON a.agentic_application_id = m.agentic_application_id
            WHERE m.tag_id IS NULL
        """
        cursor.execute(query)
        untagged_agents = [row[0] for row in cursor.fetchall()]

        # Batch insert for agents
        if untagged_agents:
            insert_query = f"""
                INSERT INTO {agent_tag_mapping_table_name} (agentic_application_id, tag_id)
                VALUES %s
            """
            values = [(agent_id, general_tag_id) for agent_id in untagged_agents]
            psycopg2.extras.execute_values(cursor, insert_query, values)

        # Commit the transaction
        connection.commit()
        return True

    except psycopg2.DatabaseError as e:
        connection.rollback()  # Rollback on error
        return False

    finally:
        if cursor:
            cursor.close()
        if connection:
            connection.close()


# Tags and Tools mapping

def create_tag_tool_mapping_table_if_not_exists(table_name="tag_tool_mapping_table"):
    connection = psycopg2.connect(
        host=POSTGRESQL_HOST,
        database=DATABASE,
        user=POSTGRESQL_USER,
        password=POSTGRESQL_PASSWORD
    )

    try:
        cursor = connection.cursor()
        create_statement = f"""
        CREATE TABLE IF NOT EXISTS {table_name} (
            tag_id TEXT,
            tool_id TEXT,
            FOREIGN KEY(tag_id) REFERENCES tags_table(tag_id) ON DELETE RESTRICT,
            FOREIGN KEY(tool_id) REFERENCES tool_table(tool_id) ON DELETE CASCADE,
            UNIQUE(tag_id, tool_id)
        )
        """
        cursor.execute(create_statement)

    finally:
        connection.close()

def insert_into_tag_tool_mapping(tag_ids, tool_id, table_name="tag_tool_mapping_table"):
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

    connection = psycopg2.connect(
        host=POSTGRESQL_HOST,
        database=DATABASE,
        user=POSTGRESQL_USER,
        password=POSTGRESQL_PASSWORD
    )

    inserted_tags = []
    failed_tags = []

    try:
        cursor = connection.cursor()

        # Build SQL INSERT statement
        insert_statement = f"""
        INSERT INTO {table_name} (
            tag_id,
            tool_id
        ) VALUES (%s, %s)
        ON CONFLICT (tag_id, tool_id) DO NOTHING
        """

        # Execute the insert statement for each tag_id
        for tag_id in tag_ids:
            try:
                cursor.execute(insert_statement, (tag_id, tool_id))
                inserted_tags.append(tag_id)
            except psycopg2.IntegrityError as e:
                failed_tags.append((tag_id, str(e)))

        connection.commit()

        # Return status
        status = {
            "message": f"Inserted mappings for tag_ids: {inserted_tags}. Failed for tag_ids: {failed_tags}",
            "inserted_tag_ids": inserted_tags,
            "failed_tag_ids": failed_tags,
            "tool_id": tool_id,
            "is_created": len(inserted_tags) > 0
        }

    except psycopg2.DatabaseError as e:
        # Handle general database errors
        status = {
            "message": f"Error inserting data into '{table_name}' table: {e}",
            "tag_ids": tag_ids,
            "tool_id": tool_id,
            "is_created": False
        }

    finally:
        # Ensure the connection is properly closed
        connection.close()

    return status

def delete_from_tag_tool_mapping(tag_ids, tool_id, table_name="tag_tool_mapping_table"):
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
    connection = psycopg2.connect(
        host=POSTGRESQL_HOST,
        database=DATABASE,
        user=POSTGRESQL_USER,
        password=POSTGRESQL_PASSWORD
    )

    try:
        cursor = connection.cursor()

        # Build SQL DELETE statement
        delete_statement = f"""
        DELETE FROM {table_name}
        WHERE tag_id = %s AND tool_id = %s
        """

        # Execute the delete statement for each tag_id
        for tag_id in tag_ids:
            cursor.execute(delete_statement, (tag_id, tool_id))
        connection.commit()

        # Check if any row was deleted
        if cursor.rowcount == 0:
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

    except psycopg2.DatabaseError as e:
        # Handle general database errors
        status = {
            "message": f"Error deleting mapping from '{table_name}' table: {e}",
            "tag_ids": tag_ids,
            "tool_id": tool_id,
            "is_deleted": False
        }

    finally:
        # Ensure the connection is properly closed
        connection.close()

    return status

def get_tags_by_tool(tool_id=None, tool_name=None, tag_table_name="tags_table", mapping_table_name="tag_tool_mapping_table", tool_table_name="tool_table"):
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
    connection = psycopg2.connect(
        host=POSTGRESQL_HOST,
        database=DATABASE,
        user=POSTGRESQL_USER,
        password=POSTGRESQL_PASSWORD
    )
    try:
        cursor = connection.cursor()

        # Build the query to get tag_ids
        query = f"""
        SELECT m.tag_id
        FROM {mapping_table_name} m
        JOIN {tool_table_name} tl ON m.tool_id = tl.tool_id
        """
        where_clauses = []
        params = []

        # Add filters to the WHERE clause
        if tool_id:
            where_clauses.append("tl.tool_id = %s")
            params.append(tool_id)
        if tool_name:
            where_clauses.append("tl.tool_name = %s")
            params.append(tool_name)

        # Append WHERE clause to the query if filters are provided
        if where_clauses:
            query += " WHERE " + " AND ".join(where_clauses)

        # Execute the query with parameters
        cursor.execute(query, tuple(params))

        # Fetch all tag_ids
        tag_ids = [row[0] for row in cursor.fetchall()]

        # If no tag_ids found, return an empty list
        if not tag_ids:
            return []

        query = f"""
        SELECT *
        FROM {tag_table_name}
        WHERE tag_id = ANY(%s)
        """

        # Execute the query with tag_ids as parameters
        cursor.execute(query, (tag_ids,))

        # Fetch all results and get column names
        rows = cursor.fetchall()
        columns = [column[0] for column in cursor.description]

        # Convert rows into a list of dictionaries
        results_as_dicts = [dict(zip(columns, row)) for row in rows]
        return results_as_dicts

    except psycopg2.DatabaseError as e:
        return []

    finally:
        connection.close()

def get_tools_by_tag(tag_ids=None, tag_names=None, tool_table_name="tool_table", mapping_table_name="tag_tool_mapping_table", tag_table_name="tags_table"):
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
    connection = psycopg2.connect(
        host=POSTGRESQL_HOST,
        database=DATABASE,
        user=POSTGRESQL_USER,
        password=POSTGRESQL_PASSWORD
    )

    try:
        cursor = connection.cursor()

        # Get tag_ids if tag_names are provided
        if tag_names:
            #query = f"SELECT tag_id FROM {tag_table_name} WHERE tag_name IN ({','.join(['?'] * len(tag_names))})"
            query = f"SELECT tag_id FROM {tag_table_name} WHERE tag_name = ANY(%s)"
            cursor.execute(query, (tag_names,))
            tag_ids_from_names = [row[0] for row in cursor.fetchall()]
            if tag_ids:
                tag_ids.extend(tag_ids_from_names)
            else:
                tag_ids = tag_ids_from_names
        # If no tag_ids found, return an empty list
        if not tag_ids:
            return []

        # Build the query to get tools based on tag_ids
        query = f"""
        SELECT DISTINCT tl.*
        FROM {tool_table_name} tl
        JOIN {mapping_table_name} m ON tl.tool_id = m.tool_id
        WHERE m.tag_id = ANY(%s)
        """

        cursor.execute(query, (tag_ids,))

        # Fetch all results and get column names
        rows = cursor.fetchall()
        columns = [column[0] for column in cursor.description]

        # Convert rows into a list of dictionaries
        results_as_dicts = [dict(zip(columns, row)) for row in rows]
        for result in results_as_dicts:
            result['tags'] = get_tags_by_tool(tool_id=result['tool_id'])
        return results_as_dicts

    except psycopg2.DatabaseError as e:
        return []

    finally:
        connection.close()




# Tags and Agent mapping

def create_tag_agentic_app_mapping_table_if_not_exists(table_name="tag_agentic_app_mapping_table"):

    connection = psycopg2.connect(
        host=POSTGRESQL_HOST,
        database=DATABASE,
        user=POSTGRESQL_USER,
        password=POSTGRESQL_PASSWORD
    )

    try:
        cursor = connection.cursor()
        create_statement = f"""
        CREATE TABLE IF NOT EXISTS {table_name} (
            tag_id TEXT,
            agentic_application_id TEXT,
            FOREIGN KEY(tag_id) REFERENCES tags_table(tag_id) ON DELETE RESTRICT,
            FOREIGN KEY(agentic_application_id) REFERENCES agent_table(agentic_application_id) ON DELETE CASCADE,
            UNIQUE(tag_id, agentic_application_id)
        )
        """
        cursor.execute(create_statement)
        connection.commit()

    finally:
        connection.close()

def insert_into_tag_agentic_app_mapping(tag_ids, agentic_application_id, table_name="tag_agentic_app_mapping_table"):
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
    connection = psycopg2.connect(
        host=POSTGRESQL_HOST,
        database=DATABASE,
        user=POSTGRESQL_USER,
        password=POSTGRESQL_PASSWORD
    )

    inserted_tags = []
    failed_tags = []

    try:
        cursor = connection.cursor()

        # Build SQL INSERT statement
        insert_statement = f"""
        INSERT INTO {table_name} (
            tag_id,
            agentic_application_id
        ) VALUES (%s, %s)
        ON CONFLICT (tag_id, agentic_application_id) DO NOTHING
        """

        # Execute the insert statement for each tag_id
        for tag_id in tag_ids:
            try:
                cursor.execute(insert_statement, (tag_id, agentic_application_id))
                inserted_tags.append(tag_id)
            except psycopg2.IntegrityError as e:
                failed_tags.append((tag_id, str(e)))

        connection.commit()

        # Return status
        status = {
            "message": f"Inserted mappings for tag_ids: {inserted_tags}. Failed for tag_ids: {failed_tags}",
            "inserted_tag_ids": inserted_tags,
            "failed_tag_ids": failed_tags,
            "agentic_application_id": agentic_application_id,
            "is_created": len(inserted_tags) > 0
        }

    except psycopg2.DatabaseError as e:
        # Handle general database errors
        status = {
            "message": f"Error inserting data into '{table_name}' table: {e}",
            "tag_ids": tag_ids,
            "agentic_application_id": agentic_application_id,
            "is_created": False
        }

    finally:
        # Ensure the connection is properly closed
        connection.close()

    return status

def delete_from_tag_agentic_app_mapping(tag_ids, agentic_application_id, table_name="tag_agentic_app_mapping_table"):
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
    connection = psycopg2.connect(
        host=POSTGRESQL_HOST,
        database=DATABASE,
        user=POSTGRESQL_USER,
        password=POSTGRESQL_PASSWORD
    )

    try:
        cursor = connection.cursor()

        # Build SQL DELETE statement
        delete_statement = f"""
        DELETE FROM {table_name}
        WHERE tag_id = %s AND agentic_application_id = %s
        """

        # Execute the delete statement for each tag_id
        for tag_id in tag_ids:
            cursor.execute(delete_statement, (tag_id, agentic_application_id))
        connection.commit()

        # Check if any row was deleted
        if cursor.rowcount == 0:
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
        connection.close()

    return status

def get_tags_by_agent(agent_id=None, agent_name=None, tag_table_name="tags_table", mapping_table_name="tag_agentic_app_mapping_table", agent_table_name="agent_table"):
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
    connection = psycopg2.connect(
        host=POSTGRESQL_HOST,
        database=DATABASE,
        user=POSTGRESQL_USER,
        password=POSTGRESQL_PASSWORD
    )

    try:
        cursor = connection.cursor()

        # Build the query to get tag_ids
        query = f"""
        SELECT m.tag_id
        FROM {mapping_table_name} m
        JOIN {agent_table_name} a ON m.agentic_application_id = a.agentic_application_id
        """
        where_clauses = []
        params = []

        # Add filters to the WHERE clause
        if agent_id:
            where_clauses.append("a.agentic_application_id = %s")
            params.append(agent_id)
        if agent_name:
            where_clauses.append("a.agentic_application_name = %s")
            params.append(agent_name)

        # Append WHERE clause to the query if filters are provided
        if where_clauses:
            query += " WHERE " + " AND ".join(where_clauses)

        # Execute the query with parameters
        cursor.execute(query, params)

        # Fetch all tag_ids
        tag_ids = [row[0] for row in cursor.fetchall()]

        # If no tag_ids found, return an empty list
        if not tag_ids:
            return []


        query = f"""
        SELECT *
        FROM {tag_table_name}
        WHERE tag_id = ANY(%s)
        """

        # Execute the query with tag_ids as parameters
        # cursor.execute(query, tag_ids)
        cursor.execute(query, (tag_ids,))

        # Fetch all results and get column names
        rows = cursor.fetchall()
        columns = [column[0] for column in cursor.description]

        # Convert rows into a list of dictionaries
        results_as_dicts = [dict(zip(columns, row)) for row in rows]
        return results_as_dicts

    except psycopg2.DatabaseError as e:
        return []

    finally:
        connection.close()

def get_agents_by_tag(tag_ids=None, tag_names=None, agent_table_name="agent_table", mapping_table_name="tag_agentic_app_mapping_table", tag_table_name="tags_table"):
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

    connection = psycopg2.connect(
        host=POSTGRESQL_HOST,
        database=DATABASE,
        user=POSTGRESQL_USER,
        password=POSTGRESQL_PASSWORD
    )

    try:
        cursor = connection.cursor()

        # Get tag_ids if tag_names are provided
        if tag_names:
            # query = f"SELECT tag_id FROM {tag_table_name} WHERE tag_name IN ({','.join(['?'] * len(tag_names))})"
            # cursor.execute(query, tag_names)
            tag_ids_from_names = [row[0] for row in cursor.fetchall()]
            query = f"SELECT tag_id FROM {tag_table_name} WHERE tag_name = ANY(%s)"
            cursor.execute(query, (tag_names,))
            if tag_ids:
                tag_ids.extend(tag_ids_from_names)
            else:
                tag_ids = tag_ids_from_names

        # If no tag_ids found, return an empty list
        if not tag_ids:
            return []

        query = f"""
        SELECT DISTINCT a.*
        FROM {agent_table_name} a
        JOIN {mapping_table_name} m ON a.agentic_application_id = m.agentic_application_id
        WHERE m.tag_id = ANY(%s)
        """

        # Execute the query with tag_ids as parameters
        cursor.execute(query, tag_ids)

        # Fetch all results and get column names
        rows = cursor.fetchall()
        columns = [column[0] for column in cursor.description]

        # Convert rows into a list of dictionaries
        results_as_dicts = [dict(zip(columns, row)) for row in rows]
        for result in results_as_dicts:
            result['tags'] = get_tags_by_agent(agent_id=result['agentic_application_id'])
        return results_as_dicts

    except psycopg2.DatabaseError as e:
        return []

    finally:
        connection.close()



# Model initialization
def create_models_table_if_not_exists(models_table="models"):
    try:
        connection = psycopg2.connect(
            host=POSTGRESQL_HOST,
            database=DATABASE,
            user=POSTGRESQL_USER,
            password=POSTGRESQL_PASSWORD
        )
        cursor = connection.cursor()

        create_statement = f"""
        CREATE TABLE IF NOT EXISTS {models_table} (
            id SERIAL PRIMARY KEY,                  -- Auto-incrementing ID
            model_name TEXT UNIQUE NOT NULL         -- Unique model name
        );
        """
        cursor.execute(create_statement)
        # Insert a new model into the 'models' table
        for model_name in ["gpt4-8k","gpt-4o-mini","gpt-4o","gpt-35-turbo","gpt-4o-2","gpt-4o-3","gemini-1.5-flash"]:
            # model_name = 'ExampleModel'  # The model name you want to insert
            # cursor.execute(f"INSERT OR IGNORE INTO {models_table} (model_name) VALUES (?);", (model_name,))
            insert_statement = f"""
            INSERT INTO {models_table} (model_name)
            VALUES (%s)
            ON CONFLICT (model_name) DO NOTHING
            """
            cursor.execute(insert_statement, (model_name,))

        connection.commit()
    finally:
        if "cursor" in locals():
            cursor.close()
        if "connection" in locals():
            connection.close()




# Login and Registration Table creation
def create_login_registration_table_if_not_exists():
    try:
        connection = psycopg2.connect(
            host=POSTGRESQL_HOST,
            database=DATABASE,
            user=POSTGRESQL_USER,
            password=POSTGRESQL_PASSWORD
        )
        cursor = connection.cursor()

        table_name="login_credential"
        create_statement = f"""
        CREATE TABLE IF NOT EXISTS {table_name} (
            mail_id TEXT PRIMARY KEY,       -- Unique identifier for each user
            user_name TEXT NOT NULL,        -- User's name
            password TEXT NOT NULL,         -- User's password
            role TEXT NOT NULL              -- User's role
        );
        """
        cursor.execute(create_statement)
        connection.commit()
    finally:
        if "cursor" in locals():
            cursor.close()
        if "connection" in locals():
            connection.close()





# CSRF-Token 

def create_csrf_token_table_if_not_exists():
    try:
        connection = psycopg2.connect(
            host=POSTGRESQL_HOST,
            database=DATABASE,
            user=POSTGRESQL_USER,
            password=POSTGRESQL_PASSWORD
        )
        cursor = connection.cursor()

        table_name="csrf_authentication"
        create_statement = f"""
        CREATE TABLE IF NOT EXISTS {table_name} (
            session_id TEXT PRIMARY KEY,       -- Unique identifier for each session
            csrf_token TEXT NOT NULL          -- CSRF token for the session
        );
        """
        cursor.execute(create_statement)
        connection.commit()
    finally:
        if "cursor" in locals():
            cursor.close()
        if "connection" in locals():
            connection.close()

def register_csrf_token(session_id, csrf_token):
    """
    Registers a CSRF token for a given session ID in the csrf_authentication table.

    Args:
        session_id (str): The session ID.
        csrf_token (str): The CSRF token to register.

    Returns:
        bool: True if the operation was successful, False otherwise.
    """
    connection = psycopg2.connect(
        host=POSTGRESQL_HOST,
        database=DATABASE,
        user=POSTGRESQL_USER,
        password=POSTGRESQL_PASSWORD
    )
    try:
        cursor = connection.cursor()

        # Insert or update the CSRF token for the session ID
        query = """
        INSERT INTO csrf_authentication (session_id, csrf_token)
        VALUES (%s, %s)
        ON CONFLICT (session_id) DO UPDATE
        SET csrf_token = EXCLUDED.csrf_token
        """
        cursor.execute(query, (session_id, csrf_token))
        connection.commit()
        return True

    except psycopg2.DatabaseError as e:
        return False

    finally:
        connection.close()

def is_valid_session_and_token(session_id, csrf_token):
    """
    Validates if the given session ID exists and the associated CSRF token matches.

    Args:
        session_id (str): The session ID to validate.
        csrf_token (str): The CSRF token to validate.

    Returns:
        bool: True if the session ID exists and the CSRF token matches, False otherwise.
    """
    connection = psycopg2.connect(
        host=POSTGRESQL_HOST,
        database=DATABASE,
        user=POSTGRESQL_USER,
        password=POSTGRESQL_PASSWORD
    )
    try:
        cursor = connection.cursor()
        # Check if the session ID exists
        query = """
        SELECT csrf_token
        FROM csrf_authentication
        WHERE session_id = %s
        """
        cursor.execute(query, (session_id,))
        result = cursor.fetchone()

        if not result:
            return {"is_valid": False, "message": "Session ID not found. Please log in again."}

        # Check if the CSRF token matches
        stored_token = result[0]
        if stored_token != csrf_token:
            return {"is_valid": False, "message": "Invalid CSRF token."}

        return {"is_valid": True, "message": "CSRF token is valid."}

    except psycopg2.DatabaseError as e:
        return False

    finally:
        connection.close()

def expire_token(session_id=None, user_id=None):
    """
    Expires a token by removing it from the csrf_authentication table based on session_id or user_id.

    Args:
        session_id (str, optional): The session ID to remove.
        user_id (str, optional): The user ID to check for associated session IDs and remove.

    Returns:
        dict: Status of the operation, including success message or error details.
    """
    if not session_id and not user_id:
        return {"message": "Error: Must provide either 'session_id' or 'user_id' to expire a token.", "is_expired": False}

    try:
        connection = psycopg2.connect(
            host=POSTGRESQL_HOST,
            database=DATABASE,
            user=POSTGRESQL_USER,
            password=POSTGRESQL_PASSWORD
        )

        cursor = connection.cursor()

        if session_id:
            # Remove the specific session ID
            query = "DELETE FROM csrf_authentication WHERE session_id = %s"
            cursor.execute(query, (session_id,))
        elif user_id:
            # Remove all session IDs that start with the user ID
            query = "DELETE FROM csrf_authentication WHERE session_id LIKE %s"
            cursor.execute(query, (f"{user_id}%",))

        connection.commit()

        if cursor.rowcount == 0:
            return {"message": "No matching session ID or user ID found.", "is_expired": False}
        else:
            return {"message": "Token(s) successfully expired.", "is_expired": True}

    except psycopg2.DatabaseError as e:
        return {"message": f"Error expiring token: {e}", "is_expired": False}

    finally:
        connection.close()






# Telemetry


def log_telemetry(application_id, session_id, total_token_usage, input_tokens, output_tokens, tools_used,
                  total_response_time_ms, no_of_tool_calls,no_of_messages_exchanged, errors_occurred, start_timestamp, end_timestamp,
                  model_used, processing_cost, tool_response_time_ms, node_response_time_ms):

    # Connect to the SQLite database
    conn = sqlite3.connect('telemetry_logs.db')
    cursor = conn.cursor()

    # Convert tools_used list (or any other structure) to JSON string if it's not already
    tools_used_json = json.dumps(tools_used)
    node_response_time_json = json.dumps(node_response_time_ms)

    # Prepare the query to insert the telemetry data
    query = """
    INSERT INTO telemetry_log (
        application_id, session_id, total_token_usage, input_tokens, output_tokens, tools_used,
        total_response_time_ms, no_of_tool_calls, no_of_messages_exchanged, errors_occurred,
        start_timestamp, end_timestamp, created_timestamp, model_used,
        processing_cost, tool_response_time_ms, node_response_time_ms
    )
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP, ?, ?, ?, ?);
    """

    # Execute the insertion, using the provided parameters
    cursor.execute(query, (

        application_id, session_id, total_token_usage, input_tokens, output_tokens, json.dumps(tools_used_json),
        total_response_time_ms, no_of_tool_calls, no_of_messages_exchanged, json.dumps(errors_occurred), start_timestamp,
        end_timestamp, model_used, processing_cost, tool_response_time_ms, json.dumps(node_response_time_json)
    ))

    # Commit the changes and close the connection
    conn.commit()
    conn.close()


def update_token_usage(total_tokens, model_name):
    try:
        connection = sqlite3.connect("telemetry_logs.db")
        cursor = connection.cursor()
        cursor.execute("select tokens_used from token_usage where model_name=?;",(model_name,))
        current_tokens = cursor.fetchall()[0][0]
        current_tokens+=total_tokens
        cursor.execute("update token_usage set tokens_used=? where model_name=?;",(current_tokens, model_name))
        connection.commit()
        cursor.close()
    finally:
        if "connection" in locals():
            connection.close()
