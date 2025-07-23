import re
import os
import asyncpg
import json 
from agent_data import agent_data
from worker_agents_data import worker_agents
from dotenv import load_dotenv
load_dotenv()
Postgre_string = os.getenv("DATABASE_URL")

POSTGRESQL_HOST = os.getenv("POSTGRESQL_HOST", "")
POSTGRESQL_USER = os.getenv("POSTGRESQL_USER", "")
POSTGRESQL_PASSWORD = os.getenv("POSTGRESQL_PASSWORD", "")
DATABASE = os.getenv("DATABASE", "")
DATABASE_URL = os.getenv("POSTGRESQL_DATABASE_URL", "")


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
        return rows_deleted > 0

    except asyncpg.PostgresError as e:
        print(f"Database error: {e}")
        return False

    finally:
        await connection.close()


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
    except asyncpg.PostgresError as e:
        print(f"Database error: {e}")
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

            return chat_history

    except asyncpg.PostgresError as e:
        print(f"Database error: {e}")
        return {"status": "error", "message": str(e)}

    finally:
        await connection.close()

async def worker_agents_config_promptp(agentic_app_ids: list, llm):
    ### Config for the Worker Agents
    agent_configs = {}
    for agent_id in agentic_app_ids:
        agent_config_info = await get_agent_tool_config_by_agent_typep(agentic_application_id=agent_id, llm=llm)
        agent_configs.update(agent_config_info)

    ### Worker Agents Prompt
    members = list(agent_configs.keys())

    worker_agents_prompt = ""
    for k, v in agent_configs.items():
        worker_agents_prompt += f"""Agentic Application Name: {v['AGENT_NAME']}\nAgentic Application Description: {v["agentic_application_description"]}\n\n"""

    return agent_configs, worker_agents_prompt, members

async def get_agent_tool_config_by_agent_typep(agentic_application_id, llm):
    from plannermeta_inference import (
        build_react_agent_as_meta_agent_worker,
        build_planner_executor_critic_chains_for_meta_agent_worker,
        build_planner_executor_critic_agent_as_meta_agent_worker
    )
    agent_tools_config = {}
    # Retrieve agent details from the database

    agent_tools_config_master = {}
    agent_tools_config = {}
    agent_tools_config["SYSTEM_PROMPT"] = json.loads(worker_agents[agentic_application_id]["system_prompt"])
    agent_tools_config["TOOLS_INFO"] = json.loads(worker_agents[agentic_application_id]["tools_id"])
    agent_tools_config["agentic_application_description"] = worker_agents[agentic_application_id]["agentic_application_description"]
    agent_name = worker_agents[agentic_application_id]["agentic_application_name"].strip().lower().replace(" ", "_")
    agent_tools_config["AGENT_NAME"] = re.sub(r'[^a-z0-9_]', '', agent_name)

    if worker_agents[agentic_application_id]['agentic_application_type'] == "react_agent":
        agent_tools_config["agentic_application_executor"] = await build_react_agent_as_meta_agent_worker(llm, agent_tools_config)
    elif worker_agents[agentic_application_id]['agentic_application_type'] == "multi_agent":
        chains_and_tools_data = await build_planner_executor_critic_chains_for_meta_agent_worker(llm=llm, multi_agent_config=agent_tools_config)
        agent_tools_config["agentic_application_executor"] = await build_planner_executor_critic_agent_as_meta_agent_worker(llm=llm, chains_and_tools_data=chains_and_tools_data, agent_name=agent_name)
    agent_tools_config_master[worker_agents[agentic_application_id]["agentic_application_name"]] = agent_tools_config
    return agent_tools_config_master


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
    results_as_dicts = [
            {
                "agentic_application_name": agent_data["agentic_application_name"],
                "agentic_application_id": agent_data["agentic_application_id"],
                "agentic_application_type": agent_data["agentic_application_type"]
            }
            for agent_data in agent_data.values()


        ]

    return results_as_dicts


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

        return {"status": "success", "message": "Memory history deleted successfully."}

    except asyncpg.PostgresError as e:
        return {"status": "error", "message": f"PostgreSQL error occurred: {e}"}
    except Exception as e:
        return {"status": "error", "message": f"Unknown error occurred: {e}"}
    finally:
        if connection:
            await connection.close()

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
        print("Feedback storage tables created successfully or already exist.")
    except asyncpg.PostgresError as e:
        print(f"Error creating feedback storage tables: {e}")
    finally:
        await conn.close()