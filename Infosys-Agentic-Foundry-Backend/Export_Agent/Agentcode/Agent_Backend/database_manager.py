import os
import re
import json
import uuid
import asyncpg
from dotenv import load_dotenv
from typing import List, Optional
from datetime import datetime, timezone

from src.models.model import load_model
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
        log.info(f"Retrieved {len(tools)} tools from '{tool_table_name}' with provided filters.")
        return tools

    except asyncpg.PostgresError as e:
        log.error(f"Error retrieving tools from '{tool_table_name}': {e}")
        return []

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

        log.info(f"Retrieved {len(results_as_dicts)} agents from '{agent_table_name}' with provided filters.")
        return results_as_dicts

    except asyncpg.PostgresError as e:
        log.error(f"Database error: {e}")
        return []  # Return an empty list in case of an error

    finally:
        await connection.close()


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
        database=DATABASE,
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
        database=DATABASE,
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




# Evaluation metrics

async def create_evaluation_logs_table():
    conn = await asyncpg.connect(
        host=POSTGRESQL_HOST,
        database=DATABASE,  # use logs DB here
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
        database=DATABASE,
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
        database=DATABASE,
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
            database=DATABASE,
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
        database=DATABASE,
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
        database=DATABASE,
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
        database=DATABASE,
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
        database=DATABASE,
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
            database=DATABASE,
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
            database=DATABASE,
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
            database=DATABASE,
            user=POSTGRESQL_USER,
            password=POSTGRESQL_PASSWORD
        )
        results = await conn.fetch(query, *params)
        await conn.close()
        return [dict(row) for row in results]
    except Exception as e:
        log.error(f" Error fetching tool metrics: {e}")
        return []

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



