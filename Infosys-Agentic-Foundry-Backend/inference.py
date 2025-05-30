# © 2024-25 Infosys Limited, Bangalore, India. All Rights Reserved.
import os
import json
import pandas as pd
from typing import Annotated, List, Any
from typing_extensions import TypedDict
import sqlite3
import datetime
from fastapi import HTTPException
from pydantic import BaseModel
import time
import psycopg2

from psycopg import Connection

from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.checkpoint.postgres import PostgresSaver
from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import PromptTemplate
from langgraph.prebuilt import create_react_agent
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage, RemoveMessage, AnyMessage, ChatMessage
from langgraph.graph.message import add_messages
from langgraph.graph import StateGraph, START, END

from database_manager import get_agents_by_id, get_tools_by_id, get_long_term_memory_sqlite, delete_by_session_id_sqlite, insert_chat_history_sqlite, log_telemetry, update_token_usage
from multi_agent_inference import generate_response_planner_executor_critic_agent
from src.models.model import load_model
from src.prompts.prompts import conversation_summary_prompt



# Connection string format:
POSTGRESQL_HOST = os.getenv("POSTGRESQL_HOST", "")
POSTGRESQL_USER = os.getenv("POSTGRESQL_USER", "")
POSTGRESQL_PASSWORD = os.getenv("POSTGRESQL_PASSWORD", "")
DATABASE = os.getenv("DATABASE", "")

connection_kwargs = {
    "autocommit": True,
    "prepare_threshold": 0,
}

DATABASE_URL = os.getenv("POSTGRESQL_DATABASE_URL")

def get_conversation_summary(conversation_summary_chain, table_name, session_id, conversation_limit=30) -> str:
    # Retrieve long-term memory (chat history) from Postgres

    conversation_history_df = pd.DataFrame(
        get_long_term_memory_sqlite(
                session_id=session_id,
                table_name=table_name,
                conversation_limit=conversation_limit
            )
    )

    # Process chat history if available
    if len(conversation_history_df):
        conversation_history_df = conversation_history_df.sort_values(
            by=["start_timestamp", "end_timestamp"]
        ).reset_index(drop=True)
        chat_history = "\n\n".join(
            [
                f"""Human Message: {Human_Message}
AI Message: {AI_Message}"""
                for Human_Message, AI_Message in conversation_history_df[
                    ["human_message", "ai_message"]
                ].itertuples(index=False)
            ]
        )
        conversation_summary = conversation_summary_chain.invoke(
            {"chat_history": chat_history}
        )
    else:
        conversation_summary = ""
    return conversation_summary

def format_messages(messages: List[Any], msg_limit: int = 30) -> str:
    """
    Formats a list of messages for display.

    Args:
        messages (list): The list of messages.
        msg_limit (int): The maximum number of messages to display.

    Returns:
        str: The formatted message string.
    """
    msg_formatted = ""
    for m in messages[-msg_limit:]: # Display only the last `msg_limit` messages
        if isinstance(m, HumanMessage):
            hmn_format = f"Human Message: {m.content}"
            msg_formatted += hmn_format + "\n\n"
        elif isinstance(m, ChatMessage) and m.role == "feedback":
            feedback_format = f"Feedback: {m.content}"
            msg_formatted += feedback_format + "\n\n"
        elif isinstance(m, AIMessage):
            ai_format = f"AI Message: {m.content}"
            msg_formatted += ai_format + "\n\n"
        elif isinstance(m, ToolMessage):
            tool_msg_format = f"Tool Message: {m.content}"
            msg_formatted += tool_msg_format + "\n\n"
    return msg_formatted.strip()

def build_executor_chains(llm, agent_config):
    """
    Sets up the tools and chains for the executor agent.

    Args:
        llm: The language model used for execution.
        agent_config (dict): Configuration dictionary for the agent.

    Returns:
        tuple: Contains tools, agent executor, and conversation summary chain.
    """
    tools_info = agent_config.get("TOOLS_INFO", "")
    tool_list = []
    for tool_id in tools_info:
        tool = get_tools_by_id(tool_id=tool_id)
        codes = tool[0]["code_snippet"]
        tool_name = tool[0]["tool_name"]
        local_var = {}
        exec(codes, local_var)
        tool_list.append(local_var[tool_name])

    # Executor Agent Chain (Graph)

    agent_executor = create_react_agent(
        llm,
        tool_list,
        state_modifier=agent_config["SYSTEM_PROMPT"]
    )

    # Chat summarization chain
    conversation_summary_prompt_template = PromptTemplate.from_template(conversation_summary_prompt)
    conversation_summary_chain = conversation_summary_prompt_template | llm | StrOutputParser()
    return agent_executor, conversation_summary_chain

def get_timestamp() -> str:
    """
    Generates the current timestamp in a formatted string.

    This can be useful for logging, debugging, or attaching metadata to outputs.

    Returns:
        str: The formatted timestamp in 'YYYY-MM-DD HH:MM:SS' format.
    """
    current_time = datetime.datetime.now()
    formatted_timestamp = current_time.strftime("%Y-%m-%d %H:%M:%S")
    return formatted_timestamp

def build_executor_agent(agent_executor, conversation_summary_chain):
    class Execute(TypedDict):
        # Definition of execution state parameters
        query: str
        response: str
        executor_messages: Annotated[List[AnyMessage], add_messages]
        past_conversation_summary: str
        ongoing_conversation: Annotated[List[AnyMessage], add_messages]
        table_name: str
        session_id: str
        start_timestamp: str
        end_timestamp: str
        reset_conversation: bool
        gen_summary_time: float
        executor_agent_time: float
        final_response_time: float
        errors: list[str]
        model_name: str

    def add_prompt_for_feedback(query: str):

        if query == "[regenerate:][:regenerate]":
            prompt = "The previous response did not meet expectations. Please review the query and provide a new, more accurate response."
            current_state_query = ChatMessage(role="feedback", content=prompt)
        elif query.startswith("[feedback:]") and query.endswith("[:feedback]"):
            prompt = f"""The previous response was not satisfactory. Here is the feedback on your previous response:
{query[11:-11]}

Please review the query and feedback, and provide an appropriate answer.
"""
            current_state_query = ChatMessage(role="feedback", content=prompt)
        else:
            current_state_query = HumanMessage(content=query, role="user_query")

        return current_state_query

    def generate_past_conversation_summary(state: Execute):
        """Generates past conversation summary from the conversation history."""
        try:
            errors = []
            start_time = time.time()
            strt_tmstp = get_timestamp()
            conv_summary = get_conversation_summary(conversation_summary_chain=conversation_summary_chain,
                                                    table_name=state["table_name"],
                                                    session_id=state["session_id"]
                                                )
            if state["reset_conversation"]:
                state["ongoing_conversation"].clear()
                state["executor_messages"].clear()
            end_time = time.time()

        except Exception as e:
            error = "Error Occurred in generate past conversation summary. Error: "
            error+=e
            errors.append(error)

        current_state_query = add_prompt_for_feedback(state["query"])

        return {
            'past_conversation_summary': conv_summary,
            'ongoing_conversation': current_state_query,
            'executor_messages': current_state_query,
            'response': None,
            'start_timestamp': strt_tmstp,
            'gen_summary_time':end_time - start_time,
            'errors':errors
        }

    def executor_agent(state: Execute):
        query = add_prompt_for_feedback(state["query"]).content
        """Handles query execution and returns the agent's response."""
        try:
            errors = state["errors"]
            start_time = time.time()
            formatted_query = f'''\
    Past Conversation Summary:
    {state["past_conversation_summary"]}

    Ongoing Conversation:
    {format_messages(state["ongoing_conversation"])}

    User Query:
    {query}
    '''

            executor_agent_response = agent_executor.invoke({"messages": [("user", formatted_query.strip())]})
            end_time = time.time()
        except Exception as e:
            error = "Error Occurred in Executor Agent. Error: "
            error+=e
            errors.append(error)
        return {
            "response": executor_agent_response["messages"][-1].content,
            "executor_messages": executor_agent_response["messages"],
            "executor_agent_time": end_time - start_time,
            "errors": errors,
        }

    def final_response(state: Execute):
        """Stores the final response and updates the conversation history."""
        try:
            start_time = time.time()
            end_timestamp = get_timestamp()
            errors = []
            insert_chat_history_sqlite(table_name=state["table_name"],
                                    session_id=state["session_id"],
                                    start_timestamp=state["start_timestamp"],
                                    end_timestamp=end_timestamp,
                                    human_message=state["query"],
                                    ai_message=state["response"])
            end_time = time.time()
        except Exception as e:
            error = "Error Occurred in Final response. Error: "
            error+=e
            errors.append(error)

        return {"ongoing_conversation": AIMessage(content=state["response"]),
                "end_timestamp": end_timestamp,
                "final_response_time":end_time - start_time,
                "errors":errors}

    workflow = StateGraph(Execute)
    workflow.add_node("generate_past_conversation_summary", generate_past_conversation_summary)
    workflow.add_node("executor_agent", executor_agent)
    workflow.add_node("final_response", final_response)

    # Define the workflow sequence
    workflow.add_edge(START, "generate_past_conversation_summary")
    workflow.add_edge("generate_past_conversation_summary", "executor_agent")
    workflow.add_edge("executor_agent", "final_response")
    workflow.add_edge("final_response", END)
    return workflow


def only_tool_name(tool_call_details):
    tool_names = []
    for tool in tool_call_details:
        tool_names.append(tool["name"])
    return tool_names

def cost_calc(input_tokens, output_tokens, model_name):
    total_cost = 0
    input_token_cost = 0
    output_token_cost = 0
    if model_name=="OpenAI-GPT4":
        input_token_cost = 0.03*0.001
        output_token_cost = 0.06*0.001
    elif model_name=="gemini-1.5-flash":
        conn = sqlite3.connect('telemetry_logs.db')
        cursor = conn.cursor()
        cursor.execute("select tokens_used from token_usage where model_name = 'gemini-1.5-flash';")
        data = cursor.fetchall()
        current_used_tokens = data[0][0]
        cursor.close()
        conn.close()
        if current_used_tokens<128_000:
            input_token_cost = 0.075*0.000001
            output_token_cost = 0.03*0.000001
        else:
            input_token_cost = 0.15*0.000001
            output_token_cost = 0.06*0.000001
    cost = input_token_cost*input_tokens + output_token_cost* output_tokens
    return cost

def generate_response_executor_agent(query,
                                     agent_config,
                                     model_name,
                                     session_id,
                                     table_name,
                                     reset_conversation):
    # Load the language model based on provided use case and context
    llm = load_model(model_name=model_name)

    # Build executor chains and conversation summarization chain
    agent_executor, conversation_summary_chain = build_executor_chains(llm, agent_config)

    # Build the complete executor agent
    if reset_conversation:
        try:
            delete_by_session_id_sqlite(
                table_name=table_name,
                session_id=session_id
                )
        except Exception as e:
            pass
    workflow = build_executor_agent(agent_executor=agent_executor, conversation_summary_chain=conversation_summary_chain)
    with PostgresSaver.from_conn_string(DATABASE_URL) as checkpointer:
        app = workflow.compile(checkpointer=checkpointer)

        # Configuration for the workflow
        graph_config = {"configurable": {"thread_id": f"{table_name}_{session_id}"}, "recursion_limit": 100}
        try:
            # Invoke the executor agent and get the response
            agent_resp = app.invoke(input={'query': query.encode("latin-1").decode("utf-8"),
                                    'table_name': table_name,
                                    'session_id': session_id,
                                    'reset_conversation': reset_conversation,
                                    'model_name': model_name
                                    },
                                config=graph_config)
            return agent_resp
        except Exception as e:
            with PostgresSaver.from_conn_string(DATABASE_URL) as checkpointer:
                checkpointer.setup()
                response = checkpointer.get(graph_config)
                try:
                    if response.get("channel_values","").get("executor_messages",""):
                        error_trace = response["channel_values"]["executor_messages"][-1]
                        return f"Error Occurred while inferring .Error Trace:\n{error_trace}"
                except Exception as e:
                    return "Error Occurred while inferring"

def get_agent_tool_config_react_agent(agentic_application_id):
    """
    Retrieves the configuration for an agent and its associated tools.

    Args:
        agentic_application_id (str, optional): Agentic application ID.
        agentic_application_name (str, optional): Agentic application name.

    Returns:
        dict: A dictionary containing the system prompt and tool information.
    """
    agent_tools_config = {}
    # Retrieve agent details from the database
    result = get_agents_by_id(agentic_application_id=agentic_application_id)
    # agent_tools_config["SYSTEM_PROMPT"] = json.loads(
    #     result[0]["system_prompt"]
    # )["SYSTEM_PROMPT_REACT_AGENT"]

    agent_tools_config["SYSTEM_PROMPT"] = result[0]["system_prompt"]["SYSTEM_PROMPT_REACT_AGENT"]
    # agent_tools_config["TOOLS_INFO"] = json.loads(
    #     result[0]["tools_id"]
    # )
    agent_tools_config["SYSTEM_PROMPT"] = result[0]["system_prompt"]["SYSTEM_PROMPT_REACT_AGENT"]
    agent_tools_config["TOOLS_INFO"] = result[0]["tools_id"]
    agent_tools_config["AGENT_TYPE"] = result[0]['agentic_application_type']

    return agent_tools_config

def get_agent_tool_config_planner_executor_critic(agentic_application_id):
    """
    Retrieves the configuration for an agent and its associated tools.

    Args:
        agentic_application_id (str): Agentic application ID.

    Returns:
        dict: A dictionary containing the system prompt and tool information.
    """
    agent_tools_config = {}
    # Retrieve agent details from the database
    result = get_agents_by_id(agentic_application_id=agentic_application_id)

    if result:
        # Only extract 'SYSTEM_PROMPT_REACT_AGENT' from the system prompt JSON
        agent_tools_config["SYSTEM_PROMPT"] = result[0]["system_prompt"]
        # Extract tools information
        agent_tools_config["TOOLS_INFO"] = result[0]["tools_id"] 
    return agent_tools_config

class AgentInferenceRequest(BaseModel):
    """
    Pydantic model representing the input request for agent inference.
    This model captures the necessary details for querying the agent,
    including the application ID, query, session ID, and model-related information.
    """
    agentic_application_id: str  # ID of the agentic application
    query: str  # The query to be processed by the agent
    session_id: str  # Unique session identifier
    model_name: str  # Name of the llm model
    reset_conversation: bool

def update_telemetry(state, agentic_application_id, session_id):
    try:
        response_time = datetime.datetime.now() - datetime.datetime.strptime(
                state["start_timestamp"],"%Y-%m-%d %H:%M:%S")
        input_tokens = 0
        total_tokens = 0
        tool_calls = 0
        executor_msgs = state["executor_messages"]
        new_msgs = []
        tool_calls_details = []
        no_of_msgs_exchanged = 0
        for i in range(len(executor_msgs)):
            msg = executor_msgs[-i-1]

            if msg.type=="ai" and msg.tool_calls:
                tool_calls_details.extend(msg.tool_calls)
            if msg.type=="ai":
                no_of_msgs_exchanged+=1
                if state["model_name"]=="OpenAI-GPT4":
                    if "token_usage" in msg.response_metadata:
                        input_tokens +=  msg.response_metadata.get("token_usage")["prompt_tokens"]
                        total_tokens += msg.response_metadata.get("token_usage")["total_tokens"]
                elif state["model_name"]=="gemini-1.5-flash":
                    if msg.usage_metadata:
                        input_tokens += msg.usage_metadata.get("input_tokens")
                        total_tokens += msg.usage_metadata.get("total_tokens")
            if msg.type=="tool":
                tool_calls+=1
            if msg.type=="human":
                break
        new_msgs = list(reversed(new_msgs))

        # Updating token usage table
        update_token_usage(total_tokens=total_tokens, model_name=state["model_name"])
        processing_cost = cost_calc(input_tokens, total_tokens-input_tokens, state["model_name"])
        tool_response_time = state['executor_agent_time']/tool_calls
        log_telemetry(application_id=agentic_application_id,
                        session_id=session_id,
                        total_token_usage=total_tokens,
                        input_tokens=input_tokens,
                        output_tokens=total_tokens-input_tokens,
                        tools_used=only_tool_name(tool_calls_details),
                        total_response_time_ms=response_time.total_seconds(),
                        errors_occurred=state.get("errors"),
                        no_of_tool_calls= tool_calls,
                        no_of_messages_exchanged=no_of_msgs_exchanged,
                        start_timestamp=state["start_timestamp"],
                        end_timestamp=get_timestamp(),
                        model_used=state["model_name"],
                        processing_cost=processing_cost,
                        tool_response_time=tool_response_time,
                        node_response_time_ms={
                            "summary": state['gen_summary_time'],
                            'executor': state['executor_agent_time'],
                            'final reponse': state['final_response_time']
                        }
                        )


    except Exception as e:
        # Raise the exception with a clear message
        raise RuntimeError(f"An error occurred while updating telemetry: {e}") from e

def segregate_conversation_from_chat_history(response):
    error_message = [{"error": "Chat History not compatable with the new version. Please reset your chat."}]
    executor_messages = response.get("executor_messages", [{}])
    # return executor_messages
    if not executor_messages[0] or not hasattr(executor_messages[0], 'role') or executor_messages[0].role != "user_query":
        return error_message

    conversation_list = []
    agent_steps = []

    for message in reversed(executor_messages):
        agent_steps.append(message)
        if message.type == "human" and hasattr(message, 'role') and message.role=="user_query":
            new_conversation = {
                "user_query": message.content,
                "final_response": agent_steps[0].content if agent_steps[0].type == "ai" else "",
                "agent_steps": list(reversed(agent_steps))
            }
            conversation_list.append(new_conversation)
            agent_steps = []

    return list(reversed(conversation_list))


def agent_inference(request: AgentInferenceRequest):
    """
    Endpoint for processing agent inference requests.

    Args:
        request (AgentInferenceRequest):
        Request body containing the agent configuration and query details.

    Returns:
        dict: A dictionary with the agent's response to the query.

    Raises:
        HTTPException: If an error occurs during the inference process.
    """
    try:
        # Extract the details from the request
        agentic_application_id = request.agentic_application_id
        query = request.query
        session_id = request.session_id
        model_name = request.model_name
        reset_conversation = request.reset_conversation

        # Format table name based on the agentic application ID
        table_name = f'table_{agentic_application_id.replace("-", "_")}'

        # Retriving the agent Type
        agent_details = get_agents_by_id(agentic_application_id=agentic_application_id)
        if len(agent_details)>0 and agent_details[0]["agentic_application_type"]=="react_agent":
            try:
                # Retrieve agent configuration based on the application ID
                agent_config = get_agent_tool_config_react_agent(agentic_application_id=agentic_application_id)
            except Exception:
                # Return a message if the application is not found
                return {"response": f"Could not find an application with Agentic Application ID: {agentic_application_id}. Please validate the provided Agentic Application ID"}

            # Call generate_response function
            response = generate_response_executor_agent(query=query,
                                                    agent_config=agent_config,
                                                    session_id=session_id,
                                                    table_name=table_name,                # Use specified Table ID
                                                    model_name=model_name,
                                                    reset_conversation=reset_conversation
                                                    )
        elif len(agent_details)>0 and agent_details[0]["agentic_application_type"]=="multi_agent":
            try:
                multi_agent_config = get_agent_tool_config_planner_executor_critic(agentic_application_id)
            except Exception as e:
                return {"response": f"Could not find an application with Agentic Application ID: {agentic_application_id}. Please validate the provided Agentic Application ID", "state": {}}

            reset_conversation = str(request.reset_conversation).lower() == "true"
            # Generate response using the agent
            response = generate_response_planner_executor_critic_agent(
                query=query,
                multi_agent_config=multi_agent_config,
                session_id=session_id,
                table_name=table_name,
                sqlite_identifier=table_name,
                reset_conversation=reset_conversation,
                model_name=model_name
            )


        response["executor_messages"] = segregate_conversation_from_chat_history(response)
        return response
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Internal Server Error: {str(e)}")


class PrevSessionRequest(BaseModel):
    """
    Pydantic model representing the input request for retriving previous conversations.
    """
    session_id: str  # session id of the user
    agent_id: str  # agent id user is working on


def retrive_previous_conversation(request: PrevSessionRequest):
    """
    Takes the request and returns the conversation list.
    """
    try:
        session_id = request.session_id
        agent_id = request.agent_id
        table_name = f'table_{agent_id.replace("-", "_")}'

        with PostgresSaver.from_conn_string(DATABASE_URL) as checkpointer:
            checkpointer.setup()
            #memory.setup()
            config = {"configurable": {"thread_id": f"{table_name}_{session_id}"}}
            data =  checkpointer.get(config)
            if data:
            # data = data.channel_values
                data = data["channel_values"]
                data["executor_messages"] = segregate_conversation_from_chat_history(data)
                return data
            return {}
    except Exception as e:
        return {"error": f"Unknown error occurred: {e}"}


def delete_chat_history_by_session_id(request: PrevSessionRequest):
    """
    Takes the request and deletes the conversation history.
    """
    try:
        session_id = request.session_id
        agent_id = request.agent_id
        table_name = f'table_{agent_id.replace("-", "_")}'
        # connection = sqlite3.connect("agentic_workflow_as_service_database.db", check_same_thread=False)
        connection = psycopg2.connect(
        host=POSTGRESQL_HOST,
        database=DATABASE,
        user=POSTGRESQL_USER,
        password=POSTGRESQL_PASSWORD
    )

        # Clear the data from the table
        cursor = connection.cursor()
        cursor.execute(f"DELETE FROM checkpoints WHERE thread_id = %s", (f"{table_name}_{session_id}",))

        # Commit the changes
        connection.commit()

        return {"status": "success", "message": "Memory history deleted successfully."}
    except Exception as e:
        return {"error": f"Unknown error occurred: {e}"}
    finally:
        if "cursor" in locals():
            cursor.close()
        if "connection" in locals():
            connection.close()


def get_all_chat_sessions():
    import sqlite3
    try:
        # conn = sqlite3.Connection("agentic_workflow_as_service_database.db")
        conn = psycopg2.connect(
        host=POSTGRESQL_HOST,
        database=DATABASE,
        user=POSTGRESQL_USER,
        password=POSTGRESQL_PASSWORD
    )
        cur = conn.cursor()
        cur.execute("SELECT DISTINCT thread_id FROM checkpoints;")
        res = cur.fetchall()
        columns = [column[0] for column in cur.description]
        data = [dict(zip(columns, row)) for row in res]
        return data
    except Exception as e:
        return []
    finally:
        if "cur" in locals():
            cur.close()
        if "conn" in locals():
            conn.close()

def get_agent_id_and_session_id_from_thread_id(thread_id: str):
    agent_id = thread_id[6:42].replace("_", "-")
    session_id = thread_id[43:]
    return { "agent_id": agent_id, "session_id": session_id }
