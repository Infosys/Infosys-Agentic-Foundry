# © 2024-25 Infosys Limited, Bangalore, India. All Rights Reserved.
import os
import json
import asyncpg
import time
from datetime import datetime, timezone
import io
import re
import asyncio
import pandas as pd
from fastapi import HTTPException
from pydantic import BaseModel
from typing import Annotated, List, Any
from typing_extensions import TypedDict
from copy import deepcopy
from phoenix.otel import register
from phoenix.trace import using_project

#conn_string = "postgres://postgres:postgres@10.208.85.72:5432/agentic_workflow_as_service_database"

from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from langgraph.types import interrupt, Command
from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import PromptTemplate
from langgraph.prebuilt import create_react_agent
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage, AnyMessage, ChatMessage
from langgraph.graph.message import add_messages
from langgraph.graph import StateGraph, START, END

from src.models.model import load_model
from src.utils.helper_functions import get_timestamp
from src.prompts.prompts import conversation_summary_prompt
from multi_agent_inference import generate_response_planner_executor_critic_agent
from planner_executor_inference import generate_response_planner_executor_agent
from database_manager import (
    get_agents_by_id, get_tools_by_id,get_long_term_memory_from_database, delete_by_session_id_from_database,
    insert_chat_history_in_database, log_telemetry, update_token_usage, get_feedback_learning_data,
    insert_into_evaluation_data
)
from react_critic_inference import generate_response_executor_critic_agent
from src.utils.secrets_handler import get_user_secrets, current_user_email
from telemetry_wrapper import logger as log, update_session_context

connection_kwargs = {
    "autocommit": True,
    "prepare_threshold": 0,
}
# DB_URI = POSTGRESQL_DATABASE_URL
POSTGRESQL_HOST = os.getenv("POSTGRESQL_HOST", "")
POSTGRESQL_USER = os.getenv("POSTGRESQL_USER", "")
POSTGRESQL_PASSWORD = os.getenv("POSTGRESQL_PASSWORD", "")
DATABASE = os.getenv("DATABASE", "")

DB_URI = os.getenv("POSTGRESQL_DATABASE_URL", "")

async def get_conversation_summary(conversation_summary_chain, table_name, session_id, conversation_limit=30) -> str:
    # Retrieve long-term memory (chat history) from Postgres

    conversation_history_df = pd.DataFrame(
        await get_long_term_memory_from_database(
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
        conversation_summary = await conversation_summary_chain.ainvoke(
            {"chat_history": chat_history}
        )
    else:
        conversation_summary = ""
    log.info(f"Conversation Summary generated for session {session_id} in table {table_name}")
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

async def build_executor_chains(llm, agent_config, checkpointer):
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
    local_var = {"get_user_secrets": get_user_secrets, "current_user_email": current_user_email}
    for tool_id in tools_info:
        try:
            tool = await get_tools_by_id(tool_id=tool_id)
            codes = tool[0]["code_snippet"]
            tool_name = tool[0]["tool_name"]
            exec(codes, local_var)
            tool_list.append(local_var[tool_name])
        except Exception as e:
            log.error(f"Error occurred while loading tool {tool_name}: {e}")
            raise HTTPException(status_code=500, detail=f"Error occurred while loading tool {tool_name}: {e}")
 

    # Executor Agent Chain (Graph)
    #async with AsyncPostgresSaver.from_conn_string(DB_URI) as checkpointer:
    agent_executor = create_react_agent(
        llm,
        tools=tool_list,
        checkpointer=checkpointer,
        interrupt_before=["tools"],
        state_modifier=agent_config["SYSTEM_PROMPT"]
    )

# Chat summarization chain
    conversation_summary_prompt_template = PromptTemplate.from_template(conversation_summary_prompt)
    conversation_summary_chain = conversation_summary_prompt_template | llm | StrOutputParser()
    log.info("Executor Agent and Conversation Summary Chain built successfully")
    return agent_executor, conversation_summary_chain


def format_feedback_learning_data(data: list) -> str:
    """
    Formats feedback learning data into a structured string.

    Args:
        data (list): List of feedback learning data.

    Returns:
        str: Formatted feedback learning data string.
    """
    formatted_data = ""
    for item in data:
        formatted_data += f"question: {item['query']}\n"
        formatted_data += f"first_response: {item['old_steps']}\n"
        formatted_data += f"user feedback: {item['feedback']}\n"
        formatted_data += f"final approved response: {item['new_steps']}\n"
        formatted_data += "------------------------\n"
    log.info("Feedback learning data formatted successfully")
    return formatted_data.strip()

async def update_preferences(prefernces: str, user_input: str, model_name: str) -> str:
    """
    Update the preferences based on user input.
    """
    llm = load_model(model_name=model_name)

    prompt = f"""
Current Preferences:
{prefernces}

User Input:
{user_input}


Instructions:
- Understand the User query, now analyze is the user intention with query is to provide feedback or related to task.
- Understand the feedback points from the given query and add them into the feedback.
- Inputs related to any task are not preferences. Don't consider them.
- If user intention is providing feed back then update the preferences based on below guidelines.
- Update the preferences based on the user input.
- If it's a new preference or feedback, add it as a new line.
- If it modifies an existing preference or feedback, update the relevant line with detailed preference context.
- User input can include new preferences, feedback on mistakes, or corrections to model behavior.
- Store these preferences or feedback as lessons to help the model avoid repeating the same mistakes.
- The output should contain only the updated preferences, with no extra explanation or commentary.
- if no preferences are there then output should is "no preferences available".

Examples:
user query: output should in markdown format
- the user query is related to preference and should be added to the preferences.
user query: a person is running at 5km per hour how much distance he can cover by 2 hours
- The user query is related to task and should not be added to the preferences.
user query: give me the response in meters.
- This is a perference and should be added to the preferences.
"""+"""
Output:
```json
{
"preferences": "all new preferences with new line as separator are added here"
}
```

"""
    response = await llm.ainvoke(prompt)
    response = response.content.strip()
    if "```json" in response:
        response = response[response.find("```json") + len("```json"):]
    response = response.replace('```json', '').replace('```', '').strip()
    try:
        final_response = json.loads(response)["preferences"]
    except json.JSONDecodeError:
        log.error("Failed to decode JSON response from model.")
        return response
    log.info("Preferences updated successfully")
    return final_response

async def build_executor_agent(agent_executor, conversation_summary_chain,interrupt_flag):
    class Execute(TypedDict):
        # Definition of execution state parameters
        query: str
        response: str
        executor_messages: Annotated[List[AnyMessage], add_messages]
        past_conversation_summary: str
        ongoing_conversation: Annotated[List[AnyMessage], add_messages]
        table_name: str
        session_id: str
        start_timestamp: datetime
        end_timestamp: datetime
        reset_conversation: bool
        gen_summary_time: float
        executor_agent_time: float
        final_response_time: float
        errors: list[str]
        model_name: str
        preference: str
        feedback : str = None
        is_interrupted : bool = False

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

    async def generate_past_conversation_summary(state: Execute):
        """Generates past conversation summary from the conversation history."""
        try:
            errors = []
            start_time = time.time()
            strt_tmstp = get_timestamp()
            conv_summary = await get_conversation_summary(conversation_summary_chain=conversation_summary_chain,
                                                    table_name=state["table_name"],
                                                    session_id=state["session_id"]
                                                )

            

            if state["reset_conversation"]:
                state["ongoing_conversation"].clear()
                state["executor_messages"].clear()
            end_time = time.time()
            if "preference" not in state:
                new_preference = await update_preferences(
                    "no preferences yet",
                    state["query"],
                    state["model_name"]
                )
            else:
                new_preference = await update_preferences(
                    state["preference"],
                    state["query"],
                    state["model_name"]
                )

        except Exception as e:
            log.error(f"Error occurred while generating past conversation summary: {e}")
            error = "Error Occurred in generate past conversation summary. Error: "
            error+=str(e)
            errors.append(error)

        current_state_query = add_prompt_for_feedback(state["query"])

        log.info("Executor Agent past conversation summary generated successfully")
        return {
            'past_conversation_summary': conv_summary,
            'preference': new_preference,
            'ongoing_conversation': current_state_query,
            'executor_messages': current_state_query,
            'response': None,
            'start_timestamp': strt_tmstp,
            'gen_summary_time':end_time - start_time,
            'errors':errors
        }

    async def executor_agent(state: Execute):
        query = add_prompt_for_feedback(state["query"]).content
        """Handles query execution and returns the agent's response."""
        thread = {"configurable": {"thread_id": "inside"+f"{state['table_name']}_{state['session_id']}"}}
        try:
            errors = state["errors"]
            start_time = time.time()
            # loop = asyncio.get_running_loop()
            data = await get_feedback_learning_data(agent_id=state["table_name"][6:])
            # data = ""
            if data==[]:
                feedback_msg = ""
            else:
                feedback_msg = format_feedback_learning_data(data)

            formatted_query = f'''\
Past Conversation Summary:
{state["past_conversation_summary"]}

Ongoing Conversation:
{format_messages(state["ongoing_conversation"])}


Follow these preferences for every step:
Preferences:
{state["preference"]}
- When applicable, use these instructions to guide your responses to the user's query.


Review the previous feedback carefully and make sure the same mistakes are not repeated
**FEEDBACK**
{feedback_msg}
**END FEEDBACK**



User Query:
{query}
    '''
            # async with AsyncPostgresSaver.from_conn_string(DB_URI) as checkpointer:
            if state["is_interrupted"]:
                executor_agent_response = await agent_executor.ainvoke(None,thread)
            else:
                executor_agent_response = await agent_executor.ainvoke({"messages": [("user", formatted_query.strip())]}, thread)
            # executor_agent_response = agent_executor.invoke({"messages": [("user", formatted_query.strip())]})
            end_time = time.time()
        except Exception as e:
            log.error(f"Error Occurred in Executor Agent: {e}")
            error = "Error Occurred in Executor Agent. Error: "
            error+=str(e)
            errors.append(error)
            return {"errors":errors}
        log.info("Executor Agent response generated successfully")
        return {
            "response": executor_agent_response["messages"][-1].content,
            "executor_messages": executor_agent_response["messages"],
            "executor_agent_time": end_time - start_time,
            "errors": errors,
        }

    async def final_response(state: Execute):
        """Stores the final response and updates the conversation history."""
        try:
            start_time = time.time()
            end_timestamp = get_timestamp()
            errors = []
            await insert_chat_history_in_database(table_name=state["table_name"],
                                    session_id=state["session_id"],
                                    start_timestamp=state["start_timestamp"],
                                    end_timestamp=end_timestamp,
                                    human_message=state["query"],
                                    ai_message=state["response"])
            end_time = time.time()
        except Exception as e:
            log.error(f"Error occurred in Final response: {e}")
            error = "Error Occurred in Final response. Error: "
            error+=e
            errors.append(error)

        log.info("Executor Agent Final response stored successfully") 
        return {"ongoing_conversation": AIMessage(content=state["response"]),
                "end_timestamp": end_timestamp,
                "final_response_time":end_time - start_time,
                "errors":errors}

    async def interrupt_node(state: Execute):
        """Asks the human if the plan is ok or not"""
        if interrupt_flag:
            is_approved = interrupt("approved?(yes/feedback)")
            log.info(f"is_approved {is_approved}")
        else:
            is_approved= "yes"
        state["feedback"] = is_approved
        return {"feedback": is_approved,"is_interrupted": True}


    async def interrupt_node_decision(state: Execute):
        if state["feedback"]=='yes':
            return "executor_agent" #Command(goto="executor_agent")
        else:
            return "tool_interrupt" #Command(goto="feedback_collector")

    async def final_decision(state: Execute):
        thread = {"configurable": {"thread_id": "inside"+f"{state['table_name']}_{state['session_id']}"}}
        a=await agent_executor.aget_state(thread)
        if a.tasks == ():
            return "final_response" #Command(goto="final_response")
        else:
            # print(agent.get_state(thread).tasks)
            return "interrupt_node" #Command(goto="interrupt_node")

    async def tool_interrupt(agent_state: Execute):
        # Step 1: Get the current state of the agent
        thread = {"configurable": {"thread_id": "inside"+f"{agent_state['table_name']}_{agent_state['session_id']}"}}
            # Check if the agent is in a state where it can be interrupted
        state = await agent_executor.aget_state(thread)
        model = agent_state["model_name"]
        model_name = model.split("-")[0]
        value = state.values["messages"][-1]
        if model_name == "gemini":
            tool_call_id = value.tool_calls[-1]["id"]
            tool_name = value.additional_kwargs["function_call"]["name"]
        else:
            tool_call_id = value.additional_kwargs["tool_calls"][-1]["id"]
            tool_name = value.additional_kwargs["tool_calls"][0]["function"]["name"]
            old_arg = value.additional_kwargs["tool_calls"][0]["function"]["arguments"]
        response_metadata = value.response_metadata
        id = value.id
        usage_metadata = value.usage_metadata
        feedback = agent_state["feedback"]
        feedback_dict = json.loads(feedback)
        new_ai_msg = AIMessage(
                        content=f"user modified the tool values, consider the new values. the old values are {old_arg}, and user modified values are {feedback} for the tool {tool_name}",
                        # content="",
                        additional_kwargs={"tool_calls": [{"id": tool_call_id, "function": {"arguments": feedback, "name": tool_name}, "type": "function"}], "refusal": None},
                        response_metadata=response_metadata,
                        id=id,
                        tool_calls=[{'name': tool_name, 'args': feedback_dict, 'id': tool_call_id, 'type': 'tool_call'}],
                        usage_metadata=usage_metadata
                    )
                #hiiiii

                # Modify the thread with the new input

        await agent_executor.aupdate_state(
            thread,
            {
                "messages": [
                    new_ai_msg
                ]
            }
        )
        # agent_state["executor_messages"].append(new_ai_msg)
        executor_agent_response = await agent_executor.ainvoke(None, thread)
        # executor_agent_response["messages"].pop()
        for i in executor_agent_response['messages']:
            i.pretty_print()

        return {
            "response": executor_agent_response["messages"][-1].content,
            "executor_messages": executor_agent_response["messages"],
        }

    ### Build Graph (Workflow)

    workflow = StateGraph(Execute)
    workflow.add_node("generate_past_conversation_summary", generate_past_conversation_summary)
    workflow.add_node("executor_agent", executor_agent)
    workflow.add_node("final_response", final_response)

    workflow.add_node("interrupt_node", interrupt_node)
    workflow.add_node("tool_interrupt", tool_interrupt)

    # Define the workflow sequence
    workflow.add_edge(START, "generate_past_conversation_summary")
    workflow.add_edge("generate_past_conversation_summary", "executor_agent")

    workflow.add_conditional_edges(
    "executor_agent",
    final_decision,
    ["interrupt_node", "final_response"],
    )
    workflow.add_conditional_edges(
    "interrupt_node",
    interrupt_node_decision,
    ["executor_agent", "tool_interrupt"],
    )
    workflow.add_conditional_edges(
    "tool_interrupt",
    final_decision,
    ["interrupt_node", "final_response"],
    )
    workflow.add_edge("final_response", END)
    log.info("Executor Agent workflow built successfully")
    return workflow

def only_tool_name(tool_call_details):
    tool_names = []
    for tool in tool_call_details:
        tool_names.append(tool["name"])
    return tool_names



async def cost_calc(input_tokens, output_tokens, model_name):
    total_cost = 0
    input_token_cost = 0
    output_token_cost = 0
    if model_name=="OpenAI-GPT4":
        input_token_cost = 0.03*0.001
        output_token_cost = 0.06*0.001
    elif model_name=="gemini-1.5-flash":
        conn = await asyncpg.connect(dsn=DB_URI)
        data = await conn.fetchrow("""
            SELECT tokens_used
            FROM token_usage
            WHERE model_name = 'gemini-1.5-flash'
        """)
        await conn.close()

        current_used_tokens = data['tokens_used'] if data else 0

        if current_used_tokens < 128_000:
            input_token_cost = 0.075 * 0.000001
            output_token_cost = 0.03 * 0.000001
        else:
            input_token_cost = 0.15 * 0.000001
            output_token_cost = 0.06 * 0.000001

    cost = input_token_cost * input_tokens + output_token_cost * output_tokens
    log.info(f"Cost calculated for {model_name}: Input Tokens Cost: {input_token_cost*input_tokens}, Output Tokens Cost: {output_token_cost*output_tokens}, Total Cost: {cost}")
    return cost

async def generate_response_executor_agent(query,
                                    agent_config,
                                    model_name,
                                    session_id,
                                    table_name,
                                    reset_conversation,
                                    project_name,
                                    interrupt_flag=False,
                                    feedback=None):
    # Load the language model based on provided use case and context
    llm = load_model(model_name=model_name)
    async with AsyncPostgresSaver.from_conn_string(DB_URI) as checkpointer:

        # Build executor chains and conversation summarization chain
        agent_executor, conversation_summary_chain = await build_executor_chains(llm, agent_config,checkpointer=checkpointer)
        # Build the complete executor agent
        if reset_conversation:
            try:
                await delete_by_session_id_from_database(
                    table_name=table_name,
                    session_id=session_id
                    )
            except Exception as e:
                log.error(f"Error Occurred while deleting session data: {e}")
                pass
        workflow = await build_executor_agent(agent_executor=agent_executor, conversation_summary_chain=conversation_summary_chain, interrupt_flag=interrupt_flag)
        #with PostgresSaver.from_conn_string(DB_URI) as checkpointer:
        #async with AsyncPostgresSaver.from_conn_string(DB_URI) as checkpointer:
        app = workflow.compile(checkpointer=checkpointer)

        # Configuration for the workflow
        graph_config = {"configurable": {"thread_id": f"{table_name}_{session_id}"}, "recursion_limit": 100}
        try:
            log.info(f"Invoking executor agent for query: {query} with session ID: {session_id} and table name: {table_name}")
            if feedback:
                agent_resp = await app.ainvoke(Command(resume=feedback),config=graph_config)

            else:
            # Invoke the executor agent and get the response
                with using_project(project_name):
                    agent_resp = await app.ainvoke(input={'query': query.encode("latin-1").decode("utf-8"),
                                            'table_name': table_name,
                                            'session_id': session_id,
                                            'reset_conversation': reset_conversation,
                                            'model_name': model_name,
                                            'is_interrupted': False,
                                            },
                                        config=graph_config)
            log.info(f"Executor agent invoked successfully for query: {query} with session ID: {session_id}")
            return agent_resp
        except Exception as e:

            await checkpointer.setup()
            response = await checkpointer.aget(graph_config)
            try:
                if response.get("channel_values","").get("executor_messages",""):
                    error_trace = response["channel_values"]["executor_messages"][-1]
                    log.error(f"Error Occurred while inferring: {e}\nError Trace: {error_trace}")
                    return f"Error Occurred while inferring .Error Trace:\n{error_trace}"
            except Exception as e:
                log.error(f"Error Occurred while retrieving error trace: {e}")
                return "Error Occurred while inferring"

async def get_agent_tool_config_react_agent(agentic_application_id):
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
    result = await get_agents_by_id(agentic_application_id=agentic_application_id)

    agent_tools_config["SYSTEM_PROMPT"] = json.loads(result[0]["system_prompt"])["SYSTEM_PROMPT_REACT_AGENT"]
    agent_tools_config["TOOLS_INFO"] = json.loads(
        result[0]["tools_id"]
    )
    agent_tools_config["AGENT_TYPE"] = result[0]['agentic_application_type']
    log.info(f"Agent tools configuration retrieved for Agentic Application ID: {agentic_application_id}")
    return agent_tools_config

async def get_agent_tool_config_planner_executor_critic(agentic_application_id):
    """
    Retrieves the configuration for an agent and its associated tools.

    Args:
        agentic_application_id (str): Agentic application ID.

    Returns:
        dict: A dictionary containing the system prompt and tool information.
    """
    agent_tools_config = {}
    # Retrieve agent details from the database
    result = await get_agents_by_id(agentic_application_id=agentic_application_id)

    if result:
        # Only extract 'SYSTEM_PROMPT_REACT_AGENT' from the system prompt JSON
        agent_tools_config["SYSTEM_PROMPT"] = json.loads(result[0]["system_prompt"])
        # Extract tools information
        agent_tools_config["TOOLS_INFO"] = json.loads(result[0]["tools_id"])
    log.info(f"Agent tools configuration retrieved for Agentic Application ID: {agentic_application_id}")
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
    feedback: str = None  # Optional feedback for the agent
    interrupt_flag: bool = False

async def update_telemetry(state, agentic_application_id, session_id):
    try:
        response_time = datetime.now() - state["start_timestamp"]
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
        await update_token_usage(total_tokens=total_tokens, model_name=state["model_name"])
        processing_cost = await cost_calc(input_tokens, total_tokens-input_tokens, state["model_name"])

        tool_response_time = state['executor_agent_time']/tool_calls

        await log_telemetry(application_id=agentic_application_id,
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
        log.error(f"Exception {e}")

def segregate_conversation_from_chat_history(response):
    if "error" in response:
        log.error(f"Error in response")
        return [response]
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
            data = ""

            # Pretty-print each message to the buffer
            for msg in list(reversed(agent_steps)):
                data += "\n"+ msg.pretty_repr()


            new_conversation = {
                "user_query": message.content,
                "final_response": agent_steps[0].content if (agent_steps[0].type == "ai") and ("tool_calls" not in agent_steps[0].additional_kwargs) and ("function_call" not in agent_steps[0].additional_kwargs) else "",
                "agent_steps": data,
                "additional_details": agent_steps
            }
            conversation_list.append(new_conversation)
            agent_steps = []
    log.info("Conversation segregated from chat history successfully")
    return list(reversed(conversation_list))


def segregate_conversation_in_json_format(response):
    if "error" in response:
        log.error(f"Error in response")
        return [response]
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
                "final_response": agent_steps[0].content if (agent_steps[0].type == "ai") and ("tool_calls" not in agent_steps[0].additional_kwargs) and ("function_call" not in agent_steps[0].additional_kwargs) else "",
                "agent_steps": list(reversed(agent_steps)),

            }
            conversation_list.append(new_conversation)
            agent_steps = []
    log.info("Conversation segregated in JSON format successfully")
    return list(reversed(conversation_list))


async def agent_inference(request: AgentInferenceRequest):
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
        feedback = request.feedback
        interrupt_flag = request.interrupt_flag

        # Format table name based on the agentic application ID
        table_name = f'table_{agentic_application_id.replace("-", "_")}'

        # Retriving the agent Type
        agent_details = await get_agents_by_id(agentic_application_id=agentic_application_id)
        match = re.search(r'([a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+)', session_id)
        user_name = match.group(0) if match else "guest"
        agent_name = agent_details[0]['agentic_application_name']
        project_name=agent_name+'_'+user_name
        register(
            project_name=project_name,
            auto_instrument=True,
            set_global_tracer_provider=False,
            batch=True
        )

        update_session_context(agent_type=agent_details[0]["agentic_application_type"],agent_name=agent_details[0]["agentic_application_name"])
        config={}
        if len(agent_details)>0 and agent_details[0]["agentic_application_type"]=="react_agent":
            try:
                # Retrieve agent configuration based on the application ID
                agent_config = await get_agent_tool_config_react_agent(agentic_application_id=agentic_application_id)
                config = agent_config
            except Exception:
                # Return a message if the application is not found
                log.error(f"Could not find an application with Agentic Application ID: {agentic_application_id}. Please validate the provided Agentic Application ID")
                return {"response": f"Could not find an application with Agentic Application ID: {agentic_application_id}. Please validate the provided Agentic Application ID"}
            log.info(f"Agent configuration retrieved for Agentic Application ID: {agentic_application_id}")
            # Call generate_response function
            response = await generate_response_executor_agent(query=query,
                                                    agent_config=agent_config,
                                                    session_id=session_id,
                                                    table_name=table_name,                # Use specified Table ID
                                                    model_name=model_name,
                                                    reset_conversation=reset_conversation,
                                                    project_name=project_name,
                                                    interrupt_flag=request.interrupt_flag,
                                                    feedback=feedback
                                                    )
        elif len(agent_details)>0 and agent_details[0]["agentic_application_type"]=="multi_agent":
            try:
                multi_agent_config = await get_agent_tool_config_planner_executor_critic(agentic_application_id)
                config = multi_agent_config
            except Exception as e:
                log.error(f"Could not find an application with Agentic Application ID: {agentic_application_id}. Please validate the provided Agentic Application ID")
                return {"response": f"Could not find an application with Agentic Application ID: {agentic_application_id}. Please validate the provided Agentic Application ID", "state": {}}

            reset_conversation = str(request.reset_conversation).lower() == "true"
            # Generate response using the agent
            response = await generate_response_planner_executor_critic_agent(
                query=query,
                multi_agent_config=multi_agent_config,
                session_id=session_id,
                table_name=table_name,
                db_identifier=table_name,
                reset_conversation=reset_conversation,
                model_name=model_name,
                project_name=project_name,
                interrupt_flag=interrupt_flag,
                feedback=feedback
            )

        elif len(agent_details)>0 and agent_details[0]["agentic_application_type"]=="planner_executor_agent":
            try:
                multi_agent_config = await get_agent_tool_config_planner_executor_critic(agentic_application_id)
                config = multi_agent_config
            except Exception as e:
                log.error(f"Could not find an application with Agentic Application ID: {agentic_application_id}. Please validate the provided Agentic Application ID")
                return {"response": f"Could not find an application with Agentic Application ID: {agentic_application_id}. Please validate the provided Agentic Application ID", "state": {}}

            reset_conversation = str(request.reset_conversation).lower() == "true"
            # Generate response using the agent
            response = await generate_response_planner_executor_agent(
                query=query,
                multi_agent_config=multi_agent_config,
                session_id=session_id,
                table_name=table_name,
                db_identifier=table_name,
                reset_conversation=reset_conversation,
                model_name=model_name,
                project_name=project_name,
                interrupt_flag=interrupt_flag,
                feedback=feedback
            )
        elif len(agent_details)>0 and agent_details[0]["agentic_application_type"]=="react_critic_agent":
            try:
                # Retrieve agent configuration based on the application ID
                agent_config = await get_agent_tool_config_planner_executor_critic(agentic_application_id=agentic_application_id)
                config = agent_config
            except Exception:
                # Return a message if the application is not found
                log.error(f"Could not find an application with Agentic Application ID: {agentic_application_id}. Please validate the provided Agentic Application ID")
                return {"response": f"Could not find an application with Agentic Application ID: {agentic_application_id}. Please validate the provided Agentic Application ID"}
            # Call generate_response function
            response = await generate_response_executor_critic_agent(query=query,
                                                    multi_agent_config=agent_config,
                                                    session_id=session_id,
                                                    table_name=table_name, 
                                                    db_identifier=table_name,# Use specified Table ID
                                                    model_name=model_name,
                                                    reset_conversation=reset_conversation,
                                                    project_name=project_name,
                                                    interrupt_flag=request.interrupt_flag,
                                                    feedback=feedback
                                                    )
        if isinstance(response, str):
            update_session_context(response=response)
            response = {"error": response}
        else:
            update_session_context(response=response['response'])
            response_evaluation = deepcopy(response)
            response_evaluation["executor_messages"] = segregate_conversation_in_json_format(response)
            response["executor_messages"] = segregate_conversation_from_chat_history(response)
        try:
            await insert_into_evaluation_data(session_id, agentic_application_id, config, response_evaluation, model_name)
        except Exception as e:
            log.error(f"Error Occurred while inserting into evaluation data: {e}")
        return response
    except Exception as e:
        # Catch any unhandled exceptions and raise a 500 internal server error
        log.error(f"Error Occurred in agent inference: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Internal Server Error: {str(e)}")


async def evaluation_agent_inference(request: AgentInferenceRequest):
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
        agent_details = await get_agents_by_id(agentic_application_id=agentic_application_id)
        update_session_context(agent_type=agent_details[0]["agentic_application_type"],agent_name=agent_details[0]["agentic_application_name"])
        config={}
        if len(agent_details)>0 and agent_details[0]["agentic_application_type"]=="react_agent":
            try:
                # Retrieve agent configuration based on the application ID
                agent_config = await get_agent_tool_config_react_agent(agentic_application_id=agentic_application_id)
                config=agent_config
            except Exception:
                # Return a message if the application is not found
                return {"response": f"Could not find an application with Agentic Application ID: {agentic_application_id}. Please validate the provided Agentic Application ID"}

            # Call generate_response function
            response = await generate_response_executor_agent(query=query,
                                                    agent_config=agent_config,
                                                    session_id=session_id,
                                                    table_name=table_name,                # Use specified Table ID
                                                    model_name=model_name,
                                                    reset_conversation=reset_conversation
                                                    )
        elif len(agent_details)>0 and agent_details[0]["agentic_application_type"]=="multi_agent":
            try:
                multi_agent_config = await get_agent_tool_config_planner_executor_critic(agentic_application_id)
                config=multi_agent_config
            except Exception as e:
                return {"response": f"Could not find an application with Agentic Application ID: {agentic_application_id}. Please validate the provided Agentic Application ID", "state": {}}

            reset_conversation = str(request.reset_conversation).lower() == "true"
            # Generate response using the agent
            response = await generate_response_planner_executor_critic_agent(
                query=query,
                multi_agent_config=multi_agent_config,
                session_id=session_id,
                table_name=table_name,
                db_identifier=table_name,
                reset_conversation=reset_conversation,
                model_name=model_name
            )

        if isinstance(response, str):
            update_session_context(response=response)
            response = {"error": response}
        else:
            update_session_context(response=response['response'])
            response["executor_messages"] = segregate_conversation_from_chat_history(response)

        log.info(f"Evaluation agent inference completed successfully for query: {query} with session ID: {session_id} and table name: {table_name}")
        return response
    except Exception as e:
        # Catch any unhandled exceptions and raise a 500 internal server error
        log.error(f"Error Occurred in evaluation agent inference: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Internal Server Error: {str(e)}")


async def evaluation_agent_inference(request: AgentInferenceRequest):
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
        agent_details = await get_agents_by_id(agentic_application_id=agentic_application_id)
        update_session_context(agent_type=agent_details[0]["agentic_application_type"],agent_name=agent_details[0]["agentic_application_name"])
        config={}
        if len(agent_details)>0 and agent_details[0]["agentic_application_type"]=="react_agent":
            try:
                # Retrieve agent configuration based on the application ID
                agent_config = await get_agent_tool_config_react_agent(agentic_application_id=agentic_application_id)
                config=agent_config
            except Exception:
                # Return a message if the application is not found
                return {"response": f"Could not find an application with Agentic Application ID: {agentic_application_id}. Please validate the provided Agentic Application ID"}

            # Call generate_response function
            response = await generate_response_executor_agent(query=query,
                                                    agent_config=agent_config,
                                                    session_id=session_id,
                                                    table_name=table_name,                # Use specified Table ID
                                                    model_name=model_name,
                                                    reset_conversation=reset_conversation,
                                                    project_name='evaluation-metrics'
                                                    )
        elif len(agent_details)>0 and agent_details[0]["agentic_application_type"]=="multi_agent":
            try:
                multi_agent_config = await get_agent_tool_config_planner_executor_critic(agentic_application_id)
                config=multi_agent_config
            except Exception as e:
                return {"response": f"Could not find an application with Agentic Application ID: {agentic_application_id}. Please validate the provided Agentic Application ID", "state": {}}

            reset_conversation = str(request.reset_conversation).lower() == "true"
            # Generate response using the agent
            response = await generate_response_planner_executor_critic_agent(
                query=query,
                multi_agent_config=multi_agent_config,
                session_id=session_id,
                table_name=table_name,
                db_identifier=table_name,
                reset_conversation=reset_conversation,
                model_name=model_name,
                project_name='evaluation-metrics'
            )
           
        if isinstance(response, str):
            update_session_context(response=response)
            response = {"error": response}
        else:
            update_session_context(response=response['response'])
            response["executor_messages"] = segregate_conversation_from_chat_history(response)
        
        log.info(f"Evaluation agent inference completed successfully for query: {query} with session ID: {session_id} and table name: {table_name}")
        return response
    except Exception as e:
        # Catch any unhandled exceptions and raise a 500 internal server error
        log.error(f"Error Occurred in evaluation agent inference: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Internal Server Error: {str(e)}")
    

class PrevSessionRequest(BaseModel):
    """
    Pydantic model representing the input request for retriving previous conversations.
    """
    session_id: str  # session id of the user
    agent_id: str  # agent id user is working on



async def retrive_previous_conversation(request: PrevSessionRequest):
    """
    Takes the request and returns the conversation list.
    """
    try:
        session_id = request.session_id
        agent_id = request.agent_id
        table_name = f'table_{agent_id.replace("-", "_")}'

        async with AsyncPostgresSaver.from_conn_string(DB_URI) as checkpointer:
            await checkpointer.setup()
            #memory.setup()
            config = {"configurable": {"thread_id": f"{table_name}_{session_id}"}}
            data =  await checkpointer.aget(config)
            if data:
            # data = data.channel_values
                data = data["channel_values"]
                data["executor_messages"] = segregate_conversation_from_chat_history(data)
                log.info(f"Previous conversation retrieved successfully for session ID: {session_id} and agent ID: {agent_id}")
                return data
            log.warning(f"No previous conversation found for session ID: {session_id} and agent ID: {agent_id}")
            return {}
    except Exception as e:
        log.error(f"Error Occurred while retrieving previous conversation: {e}")
        return { "error": f"Unknow error occured: {e}" }
    finally:
        update_session_context(session_id='Unassigned',agent_id='Unassigned')

