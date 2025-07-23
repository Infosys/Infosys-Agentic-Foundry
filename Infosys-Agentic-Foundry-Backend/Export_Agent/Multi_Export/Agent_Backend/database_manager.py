# import asyncio
import uuid
import asyncpg
import os
from dotenv import load_dotenv
load_dotenv()

DB_URI = os.getenv("POSTGRESQL_DATABASE_URL", "")
POSTGRESQL_HOST = os.getenv("POSTGRESQL_HOST", "")
POSTGRESQL_USER = os.getenv("POSTGRESQL_USER", "")
POSTGRESQL_PASSWORD = os.getenv("POSTGRESQL_PASSWORD", "")
DATABASE = os.getenv("DATABASE", "")
DB_URI = os.getenv("POSTGRESQL_DATABASE_URL", "")
from tools_data import tools_data
connection_pool = None
from agent_data import agent_data
async def create_connection_pool():
    global connection_pool
    try:
        connection_pool = await asyncpg.create_pool(
            dsn=DB_URI,
            min_size=10,
            max_size=20
        )
        print("Connection pool created successfully!")
    except Exception as e:
        print(f"Failed to create connection pool: {e}")
 
async def return_connection(connection):
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

        # Get the latest message for the given session_id
        query = f"""
        SELECT rowid, {message_column}
        FROM {table_name}
        WHERE session_id = $1
        ORDER BY end_timestamp DESC
        LIMIT 1
        """
        result = await connection.fetchrow(query, session_id)


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
            update_query = f"UPDATE {table_name} SET {message_column} = $1 WHERE rowid = $2"
            await connection.execute(update_query, updated_message.strip(), rowid)
            return update_status
        return None

    except Exception as e:
        print(f"Error updating query response: {e}")
        return None

    finally:
        await connection.close()

 
 
 
async def insert_into_evaluation_data(session_id, application_id, agent_config, response, model_name):
    if not response['response'] or ('role' in response['executor_messages'][-1]['agent_steps'][-1] and response['executor_messages'][-1]['agent_steps'][-1]['role'] == 'plan'):
        return
    try:
        data = {}
        data["session_id"] = session_id
        data["query"] = response['query']
        data["response"] = response['response']
        data["model_used"] = model_name
        data["agent_id"] = application_id
        data["agent_name"] = agent_data[application_id]['agentic_application_name']
        data["agent_type"] = agent_data[application_id]['agentic_application_type']
        data["agent_goal"] = agent_data[application_id]['agentic_application_description']
        data["workflow_description"] = agent_data[application_id]['agentic_application_workflow_description']
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

    except Exception as e:
        print(e)
 
async def extract_tools_using_tools_id(tools_id):
    """
    Extracts tool information from the database using tool IDs.
 
    Args:
        tools_id (list): List of tool IDs to retrieve details for.
 
    Returns:
        dict: A dictionary containing tool information indexed by tool names.
    """
    tools_info_user = {}

# Loop over tool_ids (assuming you're doing this in a loop with index)
    for idx, tool_id in enumerate(tools_id):
        single_tool_info = {}

        # Look up tool info from tools_data directly
        single_tool = tools_data.get(tool_id)

        if single_tool:
            single_tool_info["Tool_Name"] = single_tool.get("tool_name")
            single_tool_info["Tool_Description"] = single_tool.get("tool_description")
            single_tool_info["code_snippet"] = single_tool.get("code_snippet")
            single_tool_info["tags"] = single_tool.get("tags")
            tools_info_user[f"Tool_{idx+1}"] = single_tool_info
        else:
            tools_info_user[f"Tool_{idx+1}"] = {"error": f"No data found for tool_id: {tool_id}"}
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
        rows_deleted = int(result.split()[-1])
        return rows_deleted > 0
 
    except asyncpg.PostgresError as e:
        print(f"Database error: {e}")
        return False
 
    finally:
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
        database=DATABASE,
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
        database=DATABASE,
        user=POSTGRESQL_USER,
        password=POSTGRESQL_PASSWORD
    )
    try:
        async with conn.transaction():
            await conn.execute(insert_feedback_query, response_id, query, old_final_response, old_steps, feedback, new_final_response, new_steps, approved)
            await conn.execute(insert_agent_feedback_query, agent_id, response_id)
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
        database=DATABASE,
        user=POSTGRESQL_USER,
        password=POSTGRESQL_PASSWORD
    )
    try:
        rows = await conn.fetch(select_feedback_query, agent_id)
        results_as_dicts = [dict(row) for row in rows]
        print("fetched results")
        print(results_as_dicts)
        return results_as_dicts
    finally:
        await conn.close()
 
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

async def get_agents_details_for_chat():
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