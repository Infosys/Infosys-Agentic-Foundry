# © 2024-25 Infosys Limited, Bangalore, India. All Rights Reserved.
import ast
import json
import pandas as pd
from langgraph.graph import StateGraph, START, END
from langgraph.types import interrupt, Command
from langchain_core.output_parsers import JsonOutputParser, StrOutputParser
from contextlib import asynccontextmanager
from langchain_core.prompts import PromptTemplate
from typing_extensions import TypedDict
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage, AnyMessage, ChatMessage
from langgraph.graph.message import add_messages
from langgraph.prebuilt import create_react_agent
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from pydantic import BaseModel
from datetime import datetime
from fastapi import HTTPException
from typing import Annotated, List, Any, Dict, Literal
from pydantic import BaseModel, Field
from phoenix.trace import using_project
from langchain_core.tools.base import BaseTool
from langchain_core.tools.structured import StructuredTool
import inspect
import asyncpg

from database_manager import (
    get_agents_by_id, get_tools_by_id,
    insert_chat_history_in_database,
    get_long_term_memory_from_database,
    delete_by_session_id_from_database,
    get_feedback_learning_data
)
from src.prompts.prompts import CONVERSATION_SUMMARY_PROMPT
from src.utils.helper_functions import get_timestamp
from telemetry_wrapper import logger as log, update_session_context 
from src.models.model import load_model
import os

DB_URI = os.getenv("POSTGRESQL_DATABASE_URL", "")

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
    log.info(f"Formatted Feedback Learning Data")
    return formatted_data.strip()
async def json_repair_exception_llm(incorrect_json, exception, llm):
    """
    Attempts to repair an incorrect JSON response using an LLM.

    Args:
        incorrect_json (str): The incorrect JSON response.
        exception (Exception): The exception raised when parsing the JSON.
        llm (LLM): The LLM to use for repairing the JSON.

    Returns:
        dict or str: The repaired JSON response as a dictionary or string.
        If the LLM fails to repair the JSON, the original incorrect JSON is returned.
    """
    class CorrectedJSON(BaseModel):
        """
        Represents a corrected JSON object.

        Attributes:
            repaired_json (Dict): The repaired JSON object.
        """
        repaired_json: Dict = Field(description="Repaired JSON Object")
    json_correction_parser = JsonOutputParser(pydantic_object=CorrectedJSON)
    json_repair_template = """JSON Response to repair:
{json_response}

Exception Raised:
{exception}

Please review and fix the JSON response above based on the exception provided. Return your corrected JSON as an object with the key "repaired_json":
```json
{{
    "repaired_json": <your_corrected_json>
}}
```
"""
    try:
        try:
            json_repair_prompt = PromptTemplate.from_template(json_repair_template, partial_variables={"format_instructions": json_correction_parser.get_format_instructions()})
            json_repair_chain = json_repair_prompt | llm | json_correction_parser
            repaired_json = await json_repair_chain.ainvoke({'json_response': incorrect_json, 'exception': exception})
            data = repaired_json['repaired_json']
            if isinstance(data, dict):
                return data
            else:
                try:
                    return json.loads(data)
                except Exception as e0:
                    try:
                        return ast.literal_eval(data)
                    except Exception as e:

                        return data
        except Exception as e1:
            json_repair_prompt = PromptTemplate.from_template(json_repair_template)
            json_repair_chain = json_repair_prompt | llm | StrOutputParser()
            repaired_json = await json_repair_chain.ainvoke({'json_response': incorrect_json, 'exception': exception}).strip()
            repaired_json = repaired_json.replace('```json', '').replace('```', '')
            try:
                try:
                    repaired_json_response = json.loads(repaired_json)
                except Exception as e2:

                    repaired_json_response = ast.literal_eval(repaired_json)
                return repaired_json_response['repaired_json']
            except Exception as e3:

                return repaired_json
    except Exception as e4:
        return incorrect_json

async def output_parser(llm, chain_1, chain_2, invocation_input, error_return_key="Error"):
    try:
        formatted_response = await chain_1.ainvoke(invocation_input)
    except Exception as e:
        try:
            formatted_response = await chain_2.ainvoke(invocation_input)
            formatted_response = formatted_response.replace("```json", "").replace("```", "").replace('AI:', '').strip()
            try:
                formatted_response = json.loads(formatted_response)
            except Exception as e:
                try:
                    formatted_response = ast.literal_eval(formatted_response)
                except Exception as e:
                    try:
                        formatted_response = json_repair_exception_llm(incorrect_json=formatted_response, exception=e, llm=llm)
                    except Exception as e:
                        formatted_response = {error_return_key: [f'{formatted_response}']}
        except Exception as e:
            formatted_response = {error_return_key: [f'Processing error: {e}.\n\nPlease try again.']}
    return formatted_response

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
    for m in messages[-msg_limit:]:
        if isinstance(m, HumanMessage):
            hmn_format = f"Human Message: {m.content}"
            msg_formatted += hmn_format + "\n\n"
        if isinstance(m, AIMessage):
            ai_format = f"AI Message: {m.content}"
            msg_formatted += ai_format + "\n\n"
        if isinstance(m, ToolMessage):
            tool_msg_format = f"Tool Message: {m.content}"
            msg_formatted += tool_msg_format + "\n\n"
    return msg_formatted.strip()

def format_list_str(list_input):
    """Formats a list into a string with each element on a new line.

    Args:
        list_input: The list to format.

    Returns:
        A string containing the formatted list.
    """
    frmt_text = ""
    for list_in in list_input:
        frmt_text += list_in + "\n"
    return frmt_text.strip()

def format_past_steps_list(past_input_messages, past_output_messages) -> str:
    """Formats past input and output messages into a string, with "Response:" prefix for output.

    Args:
        past_input_messages: A list of past input messages.
        past_output_messages: A list of past output messages.

    Returns:
        A string containing the formatted past messages.
    """
    msg_formatted = ""
    for in_msg, out_msg in zip(past_input_messages, past_output_messages):
        msg_formatted += in_msg + "\n" + f"Response: {out_msg}" + "\n\n"
    return msg_formatted.strip()

def render_text_description(tools: list[BaseTool]) -> str:
    """Render the tool name and description in plain text.

    Args:
        tools: The tools to render.

    Returns:
        The rendered text.

    Output will be in the format of:

    .. code-block:: markdown

        search: This tool is used for search
        calculator: This tool is used for math
    """
    descriptions = []
    for tool in tools:

        signature = inspect.signature(tool)
        args_list = ""

        for param_name, param in signature.parameters.items():
            args_list +=f"Parameter: {param_name}, Type: {param.annotation}\n"
        description = f"tool name:\n{tool.__name__} \n tool arguments:\n{args_list} \ntool Docstring:\n{tool.__doc__}\n"
        descriptions.append(description)
    return "\n".join(descriptions)

async def get_conversation_summary(conversation_summary_chain, table_name, session_id, limit=30, executor_messages=None) -> str:
    """Retrieves a summary of the conversation history for a given session ID."""

    conversation_history_df = pd.DataFrame(
        await get_long_term_memory_from_database(
                session_id=session_id,
                table_name=table_name
            )
    )

    if len(conversation_history_df):
        conversation_history_df = conversation_history_df.sort_values(
            by=["start_timestamp", "end_timestamp"]
        ).reset_index(drop=True)
        # Limit the number of conversation turns
        conversation_history_df = conversation_history_df.tail(limit)
        chat_history = "\n\n".join(
            [
                f"""Human Message: {Human_Message}
AI Message: {AI_Message}"""
                for Human_Message, AI_Message in conversation_history_df[
                    ["human_message", "ai_message"]
                ].itertuples(index=False)
            ]
        )
        chat_history += "\n\n" + "\n\n".join(format_messages(executor_messages))
        conversation_summary = await conversation_summary_chain.ainvoke(
            {"chat_history": chat_history}
        )
    else:
        conversation_summary = ""
    log.info(f"Conversation Summary retrieved for session {session_id}")
    return conversation_summary

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
    log.info(f"Agent Tools Config retrieved for agent {agentic_application_id}")
    return agent_tools_config

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
    final_response = json.loads(response)["preferences"]
    log.info(f"Preferences updated")
    return final_response

class MultiAgentInfernceChains():
    tool_list: List[str]
    agent_executor: Any
    planner_chain_1: Any
    planner_chain_2: Any
    response_gen_chain_1: Any
    response_gen_chain_2: Any
    conversation_summary_chain: Any
    general_llm_chain: Any

async def build_planner_executor_chains(llm, multi_agent_config,checkpointer):
    """
    Builds planner and executor chains for multi-agent inference without any critic logic.
    """
    data = MultiAgentInfernceChains()
    tool_list = []
    local_var = {}
    for tool_id in multi_agent_config["TOOLS_INFO"]:
        try:
            tool = await get_tools_by_id(tool_id=tool_id)
            codes = tool[0]["code_snippet"]
            tool_name = tool[0]["tool_name"]
            exec(codes, local_var)
            tool_list.append(local_var[tool_name])
        except Exception as e:
            log.error(f"Error occurred while loading tool {tool_name}: {e}")
            raise HTTPException(status_code=500, detail=f"Error occurred while loading tool {tool_name}: {e}")
    data.tool_list = tool_list

    # Executor Agent
    try:
        agent_executor = create_react_agent(
            model=llm,
            state_modifier=multi_agent_config["SYSTEM_PROMPT"].get("SYSTEM_PROMPT_EXECUTOR_AGENT", ""),
            tools=tool_list,
            checkpointer=checkpointer,
            interrupt_before=["tools"]
        )
    except Exception as e:
        log.error(f"Error occurred while creating agent executor: {e}")
        raise HTTPException(status_code=500, detail=f"Error occurred while creating agent executor: {e}")

    data.agent_executor = agent_executor
    # Planner Agent
    planner_prompt = ChatPromptTemplate.from_messages([
        (
            "system",
            multi_agent_config["SYSTEM_PROMPT"].get("SYSTEM_PROMPT_PLANNER_AGENT", "").replace("{", "{{").replace("}", "}}"),
        ),
        ("placeholder", "{messages}"),
    ])
    planner_chain_1 = planner_prompt | llm | JsonOutputParser()
    planner_chain_2 = planner_prompt | llm | StrOutputParser()
    data.planner_chain_1 = planner_chain_1
    data.planner_chain_2 = planner_chain_2


    # General Query Handler
    general_prompt = ChatPromptTemplate.from_messages([
        (
            "system",
            multi_agent_config["SYSTEM_PROMPT"].get("SYSTEM_PROMPT_GENERAL_LLM", "").replace("{", "{{").replace("}", "}}"),
        ),
        ("placeholder", "{messages}"),
    ])
    general_llm_chain = general_prompt | llm | StrOutputParser()
    data.general_llm_chain = general_llm_chain

    # Response Generator
    response_generator_prompt = ChatPromptTemplate.from_messages([
        (
            "system",
            multi_agent_config["SYSTEM_PROMPT"].get("SYSTEM_PROMPT_RESPONSE_GENERATOR_AGENT", "").replace("{", "{{").replace("}", "}}"),
        ),
        ("placeholder", "{messages}"),
    ])
    response_gen_chain_1 = response_generator_prompt | llm | JsonOutputParser()
    response_gen_chain_2 = response_generator_prompt | llm | StrOutputParser()
    data.response_gen_chain_1 = response_gen_chain_1
    data.response_gen_chain_2 = response_gen_chain_2
    # Chat summarization
    conversation_summary_prompt_template = PromptTemplate.from_template(CONVERSATION_SUMMARY_PROMPT)
    conversation_summary_chain = conversation_summary_prompt_template | llm | StrOutputParser()
    data.conversation_summary_chain = conversation_summary_chain
    log.info("Planner and Executor chains (no critic) built successfully.")
    return data

async def build_planner_executor_agent(llm, chains_and_tools_data: MultiAgentInfernceChains,interrupt_flag=False):
    class PlanExecute(TypedDict):
        query: str
        plan: List[str]
        past_steps_input: List[str]
        past_steps_output: List[str]
        response: str
        executor_messages: Annotated[List[AnyMessage], add_messages]  # Simplified for example
        past_conversation_summary: str
        ongoing_conversation: Annotated[List[AnyMessage], add_messages]
        table_name: str
        session_id: str
        start_timestamp: datetime
        end_timestamp: datetime
        preference: str
        reset_conversation: bool
        model_name: str
        preference: str
        feedback : str = None
        is_interrupted : bool = False
        step_idx: int  # Current execution step index

    def add_prompt_for_feedback(query: str):
        if query == "[regenerate:][:regenerate]":
            prompt = "The previous response did not meet expectations. Please review the query and provide a new, more accurate response."
            return ChatMessage(role="feedback", content=prompt)
        elif query.startswith("[feedback:]") and query.endswith("[:feedback]"):
            prompt = f"""The previous response was not satisfactory. Here is the feedback on your previous response:
{query[11:-11]}

Please review the query and feedback, and provide an appropriate answer.
"""
            return ChatMessage(role="feedback", content=prompt)
        else:
            return HumanMessage(content=query, role="user_query")

    async def generate_past_conversation_summary(state: PlanExecute):
        strt_tmstp = get_timestamp()
        if str(state.get("reset_conversation", False)).lower() == "true":
            state["ongoing_conversation"].clear()
            state["executor_messages"].clear()
        conv_summary = await get_conversation_summary(
            conversation_summary_chain=conversation_summary_chain,
            table_name=state["table_name"],
            session_id=state["session_id"],
            executor_messages=state["executor_messages"],
        )
        if "preference" not in state:
            new_preference = await update_preferences("no preferences yet", state["query"], state["model_name"])
        else:
            new_preference = await update_preferences(state["preference"], state["query"], state["model_name"])
        current_state_query = add_prompt_for_feedback(state["query"])
        log.info(f"Generating past conversation summary for session {state['session_id']}")
        return {
            "past_conversation_summary": conv_summary,
            "ongoing_conversation": current_state_query,
            "executor_messages": current_state_query,
            "preference": new_preference,
            "response": None,
            "plan": None,
            "past_steps_input": None,
            "past_steps_output": None,
            "step_idx": 0,
            "start_timestamp": strt_tmstp,
        }

    async def planner_agent(state: PlanExecute):
        data = await get_feedback_learning_data(agent_id=state["table_name"][6:])
        feedback_msg = format_feedback_learning_data(data) if data else ""
        formatted_query = f'''\
Past Conversation Summary:
{state["past_conversation_summary"]}

Ongoing Conversation:
{format_messages(state["ongoing_conversation"])}

Tools Info:
{render_text_description(tools)}


Follow these preferences for every step:
Preferences:
{state["preference"]}
- When applicable, use these instructions to guide your responses to the user's query.

Review the previous feedback carefully and make sure the same mistakes are not repeated
**FEEDBACK**
{feedback_msg}
**END FEEDBACK**

Input Query:
{state["query"]}

**Note**:
- If the user query can be solved using the tools, generate a plan for the agent to follow.
- If the user query is related to agent's goal, role, workflow, domain, and tools, generate a plan.
- *Do not* generate plan if they require tools you don't have.
- If no plan can be generated, return:
    ```json
    {{
        "plan": []
    }}
    ```
'''
        invocation_input = {"messages": [("user", formatted_query)]}
        planner_response = await output_parser(
            llm=llm,
            chain_1=planner_chain_1,
            chain_2=planner_chain_2,
            invocation_input=invocation_input,
            error_return_key="plan"
        )
        response_state = {"plan": planner_response["plan"]}
        if planner_response["plan"]:
            response_state["executor_messages"] = ChatMessage(content=planner_response["plan"], role="plan")
        log.info(f"Planner agent generated plan for session {state['session_id']}")
        return response_state

    async def general_llm_call(state: PlanExecute):
        formatted_query = f'''\
Past Conversation Summary:
{state["past_conversation_summary"]}

User Query:
{state["query"]}

Note:
    -Only respond if the query is greetings, feedback, appreciation, small talk, or about the agent itself.
    -If query requires external knowledge or tools you don't have, politely decline.
'''
        response = await general_llm_chain.ainvoke({"messages": [("user", formatted_query)]})
        log.info(f"General LLM call made for session {state['session_id']}")
        return {"response": response}


    async def executor_agent(state: PlanExecute):
        """
        Executes the current step in the plan using the executor agent.

        Args:
            state: The current state of the plan execution.

        Returns:
            A dictionary containing the response from the executor agent,
            the updated past steps, and the executor messages.
        """
        thread = {"configurable": {"thread_id": "inside"+f"{state['table_name']}_{state['session_id']}"}}
        step = state["plan"][state["step_idx"]]
        completed_steps = []
        completed_steps_responses = []
        data = await get_feedback_learning_data(agent_id=state["table_name"][6:])
        # data = ""
        if data==[]:
            feedback_msg = ""
        else:
            feedback_msg = format_feedback_learning_data(data)

        task_formatted = ""

        # Include past conversation summary
        task_formatted += f"Past Conversation Summary:\n{state['past_conversation_summary']}\n\n"
        # Include ongoing conversation
        task_formatted += f"Ongoing Conversation:\n{format_messages(state['ongoing_conversation'])}\n\n"
        task_formatted += f"""

Review the previous feedback carefully and make sure the same mistakes are not repeated
**FEEDBACK**
{feedback_msg}
**END FEEDBACK**

"""
        if state["step_idx"]!=0:
            completed_steps = state["past_steps_input"][:state["step_idx"]]
            completed_steps_responses = state["past_steps_output"][:state["step_idx"]]
            task_formatted += f"Past Steps:\n{format_past_steps_list(completed_steps, completed_steps_responses)}"
        task_formatted += f"\n\nCurrent Step:\n{step}"
        if state["is_interrupted"]:
            executor_agent_response = await agent_executor.ainvoke(None,thread)
        else:
            executor_agent_response = await agent_executor.ainvoke({"messages": [("user", task_formatted.strip())]}, thread)

        completed_steps.append(step)
        completed_steps_responses.append(executor_agent_response["messages"][-1].content)
        log.info(f"Executor agent executed step {state['step_idx']} for session {state['session_id']}")
        return {
            "response": completed_steps_responses[-1],
            "past_steps_input": completed_steps,
            "past_steps_output": completed_steps_responses,
            "executor_messages": executor_agent_response["messages"]
        }

    def increment_step(state: PlanExecute):
        log.info(f"Incrementing step index for session {state['session_id']}")
        return {"step_idx": state["step_idx"] + 1,"is_interrupted": False}

    async def response_generator_agent(state: PlanExecute):
        formatted_query = f'''\
Past Conversation Summary:
{state["past_conversation_summary"]}

Ongoing Conversation:
{format_messages(state["ongoing_conversation"])}

Follow these preferences for every step:
Preferences:
{state["preference"]}
- When applicable, use these instructions to guide your responses to the user's query.


User Query:
{state["query"]}

Steps Completed to generate final response:
{format_past_steps_list(state["past_steps_input"], state["past_steps_output"])}

Final Response from Executor Agent:
{state["response"]}
'''
        invocation_input = {"messages": [("user", formatted_query)]}
        response_gen_response = await output_parser(
            llm=llm,
            chain_1=response_gen_chain_1,
            chain_2=response_gen_chain_2,
            invocation_input=invocation_input,
            error_return_key="response"
        )
        if isinstance(response_gen_response, dict) and "response" in response_gen_response:
            log.info(f"Response generator agent generated response for session {state['session_id']}")
            return {"response": response_gen_response["response"]}
        else:
            log.error(f"Response generator agent failed for session {state['session_id']}")
            result = await llm.ainvoke(f"Format the response in Markdown Format.\n\nResponse: {str(response_gen_response)}")
            return {"response": result.content}

    async def final_response(state: PlanExecute):
        end_timestamp = get_timestamp()
        await insert_chat_history_in_database(
            table_name=state["table_name"],
            session_id=state["session_id"],
            start_timestamp=state["start_timestamp"],
            end_timestamp=end_timestamp,
            human_message=state["query"],
            ai_message=state["response"],
        )
        final_response_message = AIMessage(content=state["response"])
        log.info(f"Final response generated for session {state['session_id']}")
        return {
            "ongoing_conversation": final_response_message,
            "executor_messages": final_response_message,
            "end_timestamp": end_timestamp
        }

    def check_plan_execution_status(state: PlanExecute):
        if state["step_idx"] == len(state["plan"]):
            return "response_generator_agent"
        else:
            return "executor_agent"

    def route_general_question(state: PlanExecute):
        if not state["plan"] or "STEP" not in state["plan"][0]:
            return "general_llm_call"
        else:
            return "executor_agent"

    # Unpack tools and chains
    tools = chains_and_tools_data.tool_list
    agent_executor = chains_and_tools_data.agent_executor
    planner_chain_1 = chains_and_tools_data.planner_chain_1
    planner_chain_2 = chains_and_tools_data.planner_chain_2
    response_gen_chain_1 = chains_and_tools_data.response_gen_chain_1
    response_gen_chain_2 = chains_and_tools_data.response_gen_chain_2
    conversation_summary_chain = chains_and_tools_data.conversation_summary_chain
    general_llm_chain = chains_and_tools_data.general_llm_chain
    
    
    async def final_decision(state: PlanExecute):
        thread = {"configurable": {"thread_id": "inside"+f"{state['table_name']}_{state['session_id']}"}}
        a = await agent_executor.aget_state(thread)
        if a.tasks == ():
            response = a.values["messages"][-1].content
            # checking_res = reversed(state["executor_messages"])
            # for i in checking_res:
            #     if i.type == "tool":
            #         if i.status == "error":
            #             is_successful = "no"
            #             break
            #         else:
            #             is_successful = "yes"
            checking_promopt = f"""
            You are a critic agent, your task is to check if the tool call is 
            successful or not. If the tool call is successful, return "yes", otherwise return "no".
            Tool Call Response: {response}
            Instructions:
            - If the response content "ERROR" or something similar to error or something like Null value or undefined value or something that indicates failure, then return "no".
            - If the response content is a valid response, then return "yes".

            output should be only one word either "yes" or "no"
            Do not return any other text or explanation.
            """
            is_successful = llm.invoke(checking_promopt).content.strip().lower()
            if "yes" in is_successful:
                return "increment_step" 
            else:
                return "final_response"
        else:
            
            return "interrupt_node" #Command(goto="interrupt_node")
            
        
    async def interrupt_node(state: PlanExecute):
        """Asks the human if the plan is ok or not"""
        if interrupt_flag:
            is_approved = interrupt("approved?(yes/feedback)") 
        else:
            is_approved= "yes"
        state["feedback"] = is_approved
        return {"feedback": is_approved, "is_interrupted": True}


    async def interrupt_node_decision(state: PlanExecute):
        if state["feedback"]=='yes':
            return "executor_agent" #Command(goto="executor_agent")
        else:
            return "tool_interrupt" #Command(goto="feedback_collector")
        
    async def tool_interrupt(agent_state: PlanExecute):
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
            # old_arg = value.additional_kwargs["tool_calls"][0]["function"]["arguments"]
        response_metadata = value.response_metadata
        id = value.id
        usage_metadata = value.usage_metadata
        feedback = agent_state["feedback"]
        feedback_dict = json.loads(feedback)
        new_ai_msg = AIMessage(
                        # content=f"user modified the tool values, consider the new values. the old values are {old_arg}, and user modified values are {feedback} for the tool {tool_name}",
                        content="",
                        additional_kwargs={"tool_calls": [{"id": tool_call_id, "function": {"arguments": feedback, "name": tool_name}, "type": "function"}], "refusal": None},
                        response_metadata=response_metadata,
                        id=id,
                        tool_calls=[{'name': tool_name, 'args': feedback_dict, 'id': tool_call_id, 'type': 'tool_call'}],
                        usage_metadata=usage_metadata
                    )

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
        # for i in executor_agent_response['messages']:
        #     i.pretty_print()
                    
        return {
            "response": executor_agent_response["messages"][-1].content,
            "executor_messages": executor_agent_response["messages"],
        }

    # Build workflow graph
    workflow = StateGraph(PlanExecute)
    workflow.add_node("generate_past_conversation_summary", generate_past_conversation_summary)
    workflow.add_node("planner_agent", planner_agent)
    workflow.add_node("general_llm_call", general_llm_call)
    workflow.add_node("executor_agent", executor_agent)
    workflow.add_node("increment_step", increment_step)
    workflow.add_node("response_generator_agent", response_generator_agent)
    workflow.add_node("final_response", final_response)
    workflow.add_node("final_decision", final_decision)
    workflow.add_node("interrupt_node", interrupt_node)
    workflow.add_node("tool_interrupt", tool_interrupt)

    workflow.add_edge(START, "generate_past_conversation_summary")
    workflow.add_edge("generate_past_conversation_summary", "planner_agent")
    workflow.add_conditional_edges("planner_agent", route_general_question, ["general_llm_call", "executor_agent"])
    #workflow.add_edge("executor_agent", "increment_step")
    workflow.add_conditional_edges(
    "executor_agent",
    final_decision,
    ["interrupt_node", "increment_step","final_response"],
    )
    workflow.add_conditional_edges(
    "interrupt_node",
    interrupt_node_decision,
    ["executor_agent", "tool_interrupt"],
    )
    workflow.add_conditional_edges(
    "tool_interrupt",
    final_decision,
    ["interrupt_node", "increment_step","final_response"],
    )

    # workflow.add_edge("executor_agent", "increment_step")
    workflow.add_conditional_edges(
        "increment_step",
        check_plan_execution_status,
        ["executor_agent", "response_generator_agent"],
    )
    
   
    workflow.add_edge("response_generator_agent", "final_response")
    workflow.add_edge("general_llm_call", "final_response")
    workflow.add_edge("final_response", END)

    log.info("Planner and Executor agent workflow built successfully.")
    return workflow


async def generate_response_planner_executor_agent(query,
                                                    multi_agent_config,
                                                    session_id,
                                                    table_name,
                                                    db_identifier,
                                                    reset_conversation,
                                                    model_name,
                                                    project_name,
                                                    interrupt_flag=False,
                                                    feedback=None
                                                    ):
    # Loading the model
    llm = load_model(model_name=model_name)
    agent_resp = {}
    async with AsyncPostgresSaver.from_conn_string(DB_URI) as checkpointer:
        try:

            # Build the planner, executor, and critic chains
           
            chains_and_tools_data = await build_planner_executor_chains(llm=llm,
                                                                        multi_agent_config=multi_agent_config,checkpointer=checkpointer,)

            #print("chains and tools data",chains_and_tools_data)
            workflow = await build_planner_executor_agent(llm,
                                                    chains_and_tools_data=chains_and_tools_data,interrupt_flag=interrupt_flag
                                                    )
            # Set up the graph configuration
            #print("workflow",workflow)
            graph_config = {"configurable": {"thread_id": f"{db_identifier}_{session_id}"}, "recursion_limit": 100}

            if str(reset_conversation).lower()=="true":
                try:
                    # Delete the conversation history from the database
                    await delete_by_session_id_from_database(
                        table_name=table_name,
                        session_id=session_id
                        )
                except Exception as e:
                    log.error(f"Error deleting conversation history for session {session_id}: {e}")
                    print(e)
                    pass


                
            app=workflow.compile(checkpointer=checkpointer)
            log.info(f"Invoking agent for session {session_id} with query: {query}")
            with using_project(project_name):
                try:
                    if feedback:
                        agent_resp = await app.ainvoke(Command(resume=feedback),config=graph_config)
                    else:
                        agent_resp = await app.ainvoke(input={
                            'query': query,
                            'table_name': table_name,
                            'session_id': session_id,
                            'reset_conversation': reset_conversation,
                            'model_name': model_name,
                            'is_interrupted': False
                        },
                        config=graph_config)
                except Exception as e:
                    agent_resp =  {"error": f"Error Occurred while inferring:\n{e}"}
                
        except Exception as e:
            log.error(f"Error occurred during agent invocation for session {session_id}: {e}")
            agent_resp = {"error": f"Error occurred:\n{e}"}
            raise HTTPException(status_code=500, detail=f"Error occurred:\n{e}")
        return agent_resp


