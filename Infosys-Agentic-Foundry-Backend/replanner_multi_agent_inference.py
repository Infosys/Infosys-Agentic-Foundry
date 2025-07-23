# © 2024-25 Infosys Limited, Bangalore, India. All Rights Reserved.
import ast
import json
import re
import pandas as pd
from langgraph.graph import StateGraph, START, END
from langchain_core.output_parsers import JsonOutputParser, StrOutputParser
from langchain_core.prompts import PromptTemplate
from typing_extensions import TypedDict
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage, AnyMessage, ChatMessage
from langgraph.graph.message import add_messages
from langgraph.prebuilt import create_react_agent
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from langgraph.types import Command, interrupt
from pydantic import BaseModel
from datetime import datetime
from fastapi import HTTPException
from typing import Annotated, List, Any, Dict, Literal, Optional
from pydantic import BaseModel, Field
from copy import deepcopy

from phoenix.otel import register
from phoenix.trace import using_project
from langchain_core.tools.base import BaseTool
from langchain_core.tools.structured import StructuredTool
import inspect
import asyncpg

from database_manager import get_agents_by_id, get_tools_by_id, insert_chat_history_in_database, get_long_term_memory_from_database, delete_by_session_id_from_database, insert_into_evaluation_data
from src.prompts.prompts import CONVERSATION_SUMMARY_PROMPT
from src.utils.helper_functions import get_timestamp
from inference import segregate_conversation_from_chat_history, segregate_conversation_in_json_format
from src.models.model import load_model
from telemetry_wrapper import logger as log, update_session_context
import os

DB_URI = os.getenv("POSTGRESQL_DATABASE_URL", "")


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

async def get_conversation_summary(conversation_summary_chain, table_name, session_id, limit=30) -> str:
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
        conversation_summary = await conversation_summary_chain.ainvoke(
            {"chat_history": chat_history}
        )
    else:
        conversation_summary = ""
    log.info(f"Conversation Summary generated")
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
        #agent_tools_config["SYSTEM_PROMPT"] = result[0]["system_prompt"]
        # Extract tools information
        agent_tools_config["TOOLS_INFO"] = json.loads(result[0]["tools_id"])
        #agent_tools_config["TOOLS_INFO"] = result[0]["tools_id"]

    log.info(f"Agent Tools Config for {agentic_application_id} retrieved successfully")
    return agent_tools_config

class MultiAgentInfernceChains():
    tool_list: List[str]
    agent_executor: Any
    planner_chain_1: Any
    planner_chain_2: Any
    response_gen_chain_1: Any
    response_gen_chain_2: Any
    critic_chain_1: Any
    critic_chain_2: Any
    critic_planner_chain_1: Any
    critic_planner_chain_2: Any
    conversation_summary_chain: Any
    replanner_chain_1: Any
    replanner_chain_2: Any
    general_llm_chain: Any

async def build_replanner_executor_critic_chains(llm, multi_agent_config, checkpointer):
    # Setup Executor Tools
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

    ### Define the chains
    # Executor Agent Chain (Graph)
    try:
        # async with AsyncPostgresSaver.from_conn_string(DB_URI) as memory:
        agent_executor  = create_react_agent(model=llm,
                                            state_modifier=multi_agent_config["SYSTEM_PROMPT"].get("SYSTEM_PROMPT_EXECUTOR_AGENT", ""),
                                            tools=tool_list, interrupt_before=["tools"], checkpointer=checkpointer)
    except Exception as e:
        log.error(f"Error occurred while creating agent executor: {e}")
        raise HTTPException(status_code=500, detail=f"Error occurred while creating agent executor: {e}")

    data.agent_executor = agent_executor

    # Planner Agent Chain
    planner_prompt = ChatPromptTemplate.from_messages(
        [
            (
                "system",
                multi_agent_config["SYSTEM_PROMPT"].get("SYSTEM_PROMPT_PLANNER_AGENT", "").replace("{", "{{").replace("}", "}}"),
            ),
            ("placeholder", "{messages}"),
        ]
    )
    planner_chain_1 = planner_prompt | llm | JsonOutputParser()
    planner_chain_2 = planner_prompt | llm | StrOutputParser()
    data.planner_chain_1 = planner_chain_1
    data.planner_chain_2 = planner_chain_2

    # General Query Handler Agent Chain
    general_prompt = ChatPromptTemplate.from_messages(
        [
            (
                "system",
                multi_agent_config["SYSTEM_PROMPT"].get("SYSTEM_PROMPT_GENERAL_LLM", "").replace("{", "{{").replace("}", "}}"),
            ),
            ("placeholder", "{messages}"),
        ]
    )
    general_llm_chain = general_prompt | llm | StrOutputParser()
    data.general_llm_chain = general_llm_chain

    # Response Generator Agent Chain
    response_generator_prompt = ChatPromptTemplate.from_messages(
        [
            (
                "system",
                multi_agent_config["SYSTEM_PROMPT"].get("SYSTEM_PROMPT_RESPONSE_GENERATOR_AGENT", "").replace("{", "{{").replace("}", "}}"),
            ),
            ("placeholder", "{messages}"),
        ]
    )
    response_gen_chain_1 = response_generator_prompt | llm | JsonOutputParser()
    response_gen_chain_2 = response_generator_prompt | llm | StrOutputParser()
    data.response_gen_chain_1 = response_gen_chain_1
    data.response_gen_chain_2 = response_gen_chain_2

    # Critic Agent Chain
    critic_agent_prompt = ChatPromptTemplate.from_messages(
        [
            (
                "system",
                multi_agent_config["SYSTEM_PROMPT"].get("SYSTEM_PROMPT_CRITIC_AGENT", "").replace("{", "{{").replace("}", "}}"),
            ),
            ("placeholder", "{messages}"),
        ]
    )
    critic_chain_1 = critic_agent_prompt | llm | JsonOutputParser()
    critic_chain_2 = critic_agent_prompt | llm | StrOutputParser()
    data.critic_chain_1 = critic_chain_1
    data.critic_chain_2 = critic_chain_2

    # Critic-Based Planner Agent chain
    critic_planner_agent_prompt = ChatPromptTemplate.from_messages(
        [
            (
                "system",
                multi_agent_config["SYSTEM_PROMPT"].get("SYSTEM_PROMPT_CRITIC_BASED_PLANNER_AGENT", "").replace("{", "{{").replace("}", "}}"),
            ),
            ("placeholder", "{messages}"),
        ]
    )
    critic_planner_chain_1 = critic_planner_agent_prompt | llm | JsonOutputParser()
    critic_planner_chain_2 = critic_planner_agent_prompt | llm | StrOutputParser()
    data.critic_planner_chain_1 = critic_planner_chain_1
    data.critic_planner_chain_2 = critic_planner_chain_2

    # Chat summarization chain
    conversation_summary_prompt_template = PromptTemplate.from_template(CONVERSATION_SUMMARY_PROMPT)
    conversation_summary_chain = conversation_summary_prompt_template | llm | StrOutputParser()
    data.conversation_summary_chain = conversation_summary_chain

    # Replanner Agent Chain
    replanner_prompt = ChatPromptTemplate.from_messages(
        [
            (
                "system",
                multi_agent_config["SYSTEM_PROMPT"].get("SYSTEM_PROMPT_REPLANNER_AGENT", "").replace("{", "{{").replace("}", "}}"),
            ),
            ("placeholder", "{messages}"),
        ]
    )
    replanner_chain_1 = replanner_prompt | llm | JsonOutputParser()
    replanner_chain_2 = replanner_prompt | llm | StrOutputParser()
    data.replanner_chain_1 = replanner_chain_1
    data.replanner_chain_2 = replanner_chain_2
    log.info("Planner, Executor, Critic, Replanner Chains built successfully")
    return data

async def build_replanner_executor_critic_agent(llm, chains_and_tools_data: MultiAgentInfernceChains, interrupt_flag):
    class PlanExecuteCritic(TypedDict):
        query: str
        plan: List[str]
        past_steps_input: List[str]
        past_steps_output: List[str]
        response: str
        executor_messages: Annotated[List[AnyMessage], add_messages]
        past_conversation_summary: str
        ongoing_conversation: Annotated[List[AnyMessage], add_messages]
        response_quality_score: float
        critique_points: str
        epoch: int
        step_idx: int # App Related vars
        table_name: str
        session_id: str
        start_timestamp: datetime
        end_timestamp: datetime
        reset_conversation: bool
        is_approved: Optional[str] = None
        feedback: Optional[str] = None
        current_query_status: Optional[Literal["plan", "feedback", None]] = None
        tool_feedback: str
        is_interrupted : bool = False
        model_name: str

    async def generate_past_conversation_summary(state: PlanExecuteCritic):
        """
        Generates a summary of the past conversation for the given state.
        Args:
            state: The current state of the PlanExecuteCritic object.
        Returns:
            A dictionary containing the past conversation summary, ongoing conversation,
            and other relevant information.
        """
        strt_tmstp = get_timestamp()
        conv_summary = await get_conversation_summary(conversation_summary_chain=conversation_summary_chain,
                                                table_name=state["table_name"],
                                                session_id=state["session_id"]
                                            )
        if str(state["reset_conversation"]).lower()=="true":
            state["ongoing_conversation"].clear()
            state["executor_messages"].clear()
        # Construct the return dictionary with the conversation summary and other relevant information
        current_state_query = HumanMessage(content=state["query"], role="user_query")
        log.info(f"Past Conversation Summary generated for session {state['session_id']}")
        return {
            'past_conversation_summary': conv_summary,
            'ongoing_conversation': current_state_query,
            'executor_messages': current_state_query,
            'response': None,
            'response_quality_score': None,
            'critique_points': None,
            'plan': None,
            'past_steps_input': None,
            'past_steps_output': None,
            'epoch': 0,
            'step_idx': 0,
            'start_timestamp': strt_tmstp,
            'is_approved': None,
            'feedback': None,
            'current_query_status': None
        }

    async def planner_agent(state: PlanExecuteCritic):
        """
        This function takes the current state of the conversation and generates a plan for the agent to follow.

        Args:
            state (PlanExecuteCritic): The current state of the conversation, including past conversation summary, ongoing conversation, tools info, and the input query.

        Returns:
            dict: A dictionary containing the plan for the agent to follow.
        """
        # Format the query for the planner
        formatted_query = f'''\
Past Conversation Summary:
{state["past_conversation_summary"]}

Ongoing Conversation:
{format_messages(state["ongoing_conversation"])}

Tools Info:
{render_text_description(tools)}

Input Query:
{state["query"]}

**Note**:
- If the user query can be solved using the tools, generate a plan for the agent to follow.
- If the user query is related to agent's goal, agent's role, workflow description, agent's domain, and tools it has access to, generate a plan for the agent to follow.
- *Do not* generate plan if they query requires the tool that you do not have.
- If no plan can be generated, return:
    ```json
    {{
        "plan": []
    }}
    ```
'''
        invocation_input = {"messages": [("user", formatted_query)]}
        planner_response = await output_parser(llm=llm,
                                         chain_1=planner_chain_1,
                                         chain_2=planner_chain_2,
                                        invocation_input=invocation_input,
                                        error_return_key="plan")
        response_state = {"plan": planner_response['plan']}
        if planner_response['plan']:
            response_state["executor_messages"] = ChatMessage(content=planner_response['plan'], role="plan")
            response_state["current_query_status"] = "plan"
        log.info(f"Plan generated for session {state['session_id']}")
        return response_state

    async def replanner_agent(state: PlanExecuteCritic):
        """
        This function takes the current state of the conversation and revises the previous plan based on user feedback.

        Args:
            state (PlanExecuteCritic): The current state of the conversation, including past conversation summary, ongoing conversation, tools info, input query, and previous plan.

        Returns:
            dict: A dictionary containing the revised plan or final response.
        """
    # Format the query for the replanner
        formatted_query = f'''\
Past Conversation Summary:
{state["past_conversation_summary"]}

Ongoing Conversation:
{format_messages(state["ongoing_conversation"])}

Tools Info:
{render_text_description(tools)}

Previous Plan:
{state["plan"]}

Input Query:
{state["query"]}

User Feedback:
{state["feedback"]}

**Note**:
- Update or revise the current plan according to the user's feedback correctly.
- If you are not able to come up with a plan or input query is greetings, just return empty list:
    ```json
    {{
        "plan": []
    }}
    ```
'''
        invocation_input = {"messages": [("user", formatted_query)]}
        replanner_response = await output_parser(llm=llm,
                                         chain_1=replanner_chain_1,
                                         chain_2=replanner_chain_2,
                                        invocation_input=invocation_input,
                                        error_return_key="plan")
        log.info(f"Replanner response generated for session {state['session_id']}")
        return {
            "plan": replanner_response.get('plan', []),
            "response": replanner_response.get('response', ''),
            "executor_messages": ChatMessage(content=replanner_response.get('plan', []), role="re-plan"),
            "current_query_status": "plan"
        }
    async def general_llm_call(state: PlanExecuteCritic):
        """
        This function calls the LLM with the user's query and returns the LLM's response.

        Args:
            state: A PlanExecuteCritic object containing the user's query.

        Returns:
            A dictionary containing the LLM's response.
        """
        # Invoke the agent executor with the user's query.
        # The agent executor is responsible for interacting with the LLM.
        formatted_query = f'''\
Past Conversation Summary:
{state["past_conversation_summary"]}

User Query:
{state["query"]}

Note:
    -Only respond if the above User Query including greetings, feedback, and appreciation, engage in getting to know each other type of conversation, or queries related to the agent itself, such as its expertise or purpose.
    - If the query is not related to the agent's expertise, agent's goal, agent's role, workflow description, and tools it has access to and it requires external knowledge, DO NOT provide a answer to such a query, just politely inform the user that you are not capable to answer such queries.
'''
        response = await general_llm_chain.ainvoke({"messages": [("user", formatted_query)]})
        log.info(f"General LLM response generated for session {state['session_id']}")
        return {
            "response": response
        }

    async def executor_agent(state: PlanExecuteCritic):
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
        task_formatted = ""

        # Include past conversation summary
        task_formatted += f"Past Conversation Summary:\n{state['past_conversation_summary']}\n\n"
        # Include ongoing conversation
        task_formatted += f"Ongoing Conversation:\n{format_messages(state['ongoing_conversation'])}\n\n"

        if state["step_idx"]!=0:
            completed_steps = state["past_steps_input"][:state["step_idx"]]
            completed_steps_responses = state["past_steps_output"][:state["step_idx"]]
            task_formatted += f"Past Steps:\n{format_past_steps_list(completed_steps, completed_steps_responses)}"
        task_formatted += f"\n\nCurrent Step:\n{step}"

        if state["is_interrupted"]:
            executor_agent_response = await agent_executor.ainvoke(None,thread)

        else:
            executor_agent_response = await agent_executor.ainvoke({"messages": [("user", task_formatted.strip())]}, thread)


        # executor_agent_response = agent_executor.invoke({"messages": [("user", task_formatted.strip())]})
        completed_steps.append(step)
        completed_steps_responses.append(executor_agent_response["messages"][-1].content)
        log.info(f"Executor Agent response generated for session {state['session_id']} at step {state['step_idx']}")
        return {
            "response": completed_steps_responses[-1],
            "past_steps_input": completed_steps,
            "past_steps_output": completed_steps_responses,
            "executor_messages": executor_agent_response["messages"]
        }

    def increment_step(state: PlanExecuteCritic):
        log.info(f"Incrementing step index for session {state['session_id']} to {state['step_idx'] + 1}")
        return {"step_idx": state["step_idx"]+1, "is_interrupted": False}

    async def response_generator_agent(state: PlanExecuteCritic):
        """
        This function takes the current state of the conversation
        and generates a response using a response generation chain.
        Args:
            state (PlanExecuteCritic): The current state of the conversation,
            containing information about the past conversation,
            ongoing conversation, user query, completed steps,
            and the response from the executor agent.
        Returns:
            dict: A dictionary containing the generated response.
        """
        formatted_query = f'''\
Past Conversation Summary:
{state["past_conversation_summary"]}

Ongoing Conversation:
{format_messages(state["ongoing_conversation"])}



User Query:
{state["query"]}

User Feedback (prioritize this over the user Query for final response ):
{state["feedback"]} 

Steps Completed to generate final response:
{format_past_steps_list(state["past_steps_input"], state["past_steps_output"])}

Final Response from Executor Agent:
{state["response"]}
'''
        invocation_input = {"messages": [("user", formatted_query)]}
        response_gen_response = await output_parser(llm=llm,
                                              chain_1=response_gen_chain_1,
                                              chain_2=response_gen_chain_2,
                                              invocation_input=invocation_input,
                                              error_return_key="response")
        if isinstance(response_gen_response, dict):
            if "response" in response_gen_response:
                log.info(f"Response generated for session {state['session_id']}")
                return {"response": response_gen_response["response"]}
            else:
                log.error(f"Response generation failed for session {state['session_id']}")
                return {"response": await llm.ainvoke(f"Format the response in Markdown Format.\n\nResponse: {str(response_gen_response)}").content}

    async def critic_agent(state: PlanExecuteCritic):
        """
        This function takes a state object containing information about the conversation and the generated response,
        formats it into a query for the critic model, and returns the critic's evaluation of the response.

        Args:
            state (PlanExecuteCritic): A dictionary containing information about the conversation and the generated response.

        Returns:
            dict: A dictionary containing the critic's evaluation of the response, including the response quality score and critique points.
        """
        formatted_query = f'''\
Past Conversation Summary:
{state["past_conversation_summary"]}

Ongoing Conversation:
{format_messages(state["ongoing_conversation"])}

Tools Info:
{render_text_description(tools)}

User Query:
{state["query"]}

Now user want to modify above query with below modification:
{state["feedback"]} 

Steps Completed to generate final response:
{format_past_steps_list(state["past_steps_input"], state["past_steps_output"])}

Generated Plan:
{state["plan"]}

Final Response:
{state["response"]}

##Instructions
- Consider the modifications given by user along with actual query
- Only Verify Final Response which is aligned to the query and make sure all the data in final response are grounded from the past steps output
- Consider plan and final response as a whole and verify if the final response is aligned with the user query.

'''
        invocation_input = {"messages": [("user", formatted_query)]}
        critic_response = await output_parser(llm=llm,
                                              chain_1=critic_chain_1,
                                              chain_2=critic_chain_2,
                                              invocation_input=invocation_input,
                                              error_return_key="critique_points")

        if critic_response["critique_points"] and "error" in critic_response["critique_points"][0]:
            critic_response = {'response_quality_score': 0, 'critique_points': critic_response["critique_points"]}
        log.info(f"Critic response generated for session {state['session_id']}")
        return {
            "response_quality_score": critic_response["response_quality_score"],
            "critique_points": critic_response["critique_points"],
            "executor_messages": ChatMessage(
                content=[{
                        "response_quality_score": critic_response["response_quality_score"],
                        "critique_points": critic_response["critique_points"]
                    }],
                role="critic-response"
            ),
            "epoch": state["epoch"]+1
        }

    async def critic_based_planner_agent(state: PlanExecuteCritic):
        """
        This function takes a state object containing information about the current conversation, tools, and past steps,
        and uses a critic-based planner to generate a plan for the next step.

        Args:
            state (PlanExecuteCritic): A dictionary containing information about the current conversation, tools, and past steps.

        Returns:
            dict: A dictionary containing the plan for the next step and the index of the current step.
        """
        formatted_query = f'''
Past Conversation Summary:
{state["past_conversation_summary"]}

Ongoing Conversation:
{format_messages(state["ongoing_conversation"])}

Tools Info:
{render_text_description(tools)}

User Query:
{state["query"]}

*Now user want to modify above query with below modification:
{state["feedback"]} 

Steps Completed Previously to Generate Final Response:
{format_past_steps_list(state["past_steps_input"], state["past_steps_output"])}

Final Response:
{state["response"]}

Response Quality Score:
{state["response_quality_score"]}

Critique Points:
{format_list_str(state["critique_points"])}
'''
        invocation_input = {"messages": [("user", formatted_query)]}
        critic_planner_response = await output_parser(llm=llm,
                                              chain_1=critic_planner_chain_1,
                                              chain_2=critic_planner_chain_2,
                                              invocation_input=invocation_input,
                                              error_return_key="plan")
        log.info(f"Critic-based planner response generated for session {state['session_id']}")
        return {
            "plan": critic_planner_response["plan"],
            "executor_messages": ChatMessage(content=critic_planner_response['plan'], role="critic-plan"),
            "step_idx": 0
        }
    async def final_response(state: PlanExecuteCritic):
        """
        This function handles the final response of the conversation.
        Args:
            state: A PlanExecuteCritic object containing the state of the conversation.
        Returns:
            A dictionary containing the final response and the end timestamp.
        """
        end_timestamp = get_timestamp()

        await insert_chat_history_in_database(table_name=state["table_name"],
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

    def critic_decision(state: PlanExecuteCritic):
        """
        Decides whether to return the final response or continue
        with the critic-based planner agent.

        Args:
            state: The current state of the plan execution process.

        Returns:
            "final_response": If the response quality score is
            high enough or the maximum number of epochs has been reached.
            "critic_based_planner_agent": Otherwise.
        """
        if state["response_quality_score"]>=0.7 or state["epoch"]==3:
            return "final_response"
        else:
            return "critic_based_planner_agent"

    def check_plan_execution_status(state: PlanExecuteCritic):
        """
        Checks the status of the plan execution and decides which agent should be called next.
        Args:
            state: The current state of the plan execution process.
        Returns:
            "response_generator_agent": If the plan has been fully executed.
            "executor_agent": Otherwise.
        """
        if state["step_idx"]==len(state["plan"]):
            return "response_generator_agent"
        else:
            return "executor_agent"

    def route_general_question(state: PlanExecuteCritic):
        """
        Determines the appropriate agent to handle a general question based on the current state.
        Args:
            state: The current state of the PlanExecuteCritic object.

        Returns:
            A string representing the agent to call:
                - "general_llm_call": If there is no plan or the first step in the plan does not have a "STEP" key.
                - "executor_agent": If there is a plan and the first step has a "STEP" key.
        """
        if not state["plan"] or "STEP" not in state["plan"][0]:
            return "general_llm_call"
        else:
            return "interrupt_node"

    def interrupt_node(state: PlanExecuteCritic):
        """Asks the human if the plan is ok or not"""
        is_approved = interrupt("Is this plan acceptable?").lower()
        state = {"is_approved": is_approved}
        if is_approved=='no':
            state["current_query_status"] = "feedback"
        else:
            state["current_query_status"] = None
        return state

    def interrupt_node_decision(state: PlanExecuteCritic):
        if state["is_approved"]=='yes':
            return "executor_agent" #Command(goto="executor_agent")
        elif state["is_approved"]=='no':
            return "feedback_collector" #Command(goto="feedback_collector")

    def feedback_collector(state: PlanExecuteCritic):
        feedback = interrupt("What went wrong??")

        return {
            'feedback': feedback,
            'current_query_status': None
        }

    tools = chains_and_tools_data.tool_list
    agent_executor = chains_and_tools_data.agent_executor
    planner_chain_1 = chains_and_tools_data.planner_chain_1
    planner_chain_2 = chains_and_tools_data.planner_chain_2
    response_gen_chain_1 = chains_and_tools_data.response_gen_chain_1
    response_gen_chain_2 = chains_and_tools_data.response_gen_chain_2
    critic_chain_1 = chains_and_tools_data.critic_chain_1
    critic_chain_2 = chains_and_tools_data.critic_chain_2
    critic_planner_chain_1 = chains_and_tools_data.critic_planner_chain_1
    critic_planner_chain_2 = chains_and_tools_data.critic_planner_chain_2
    conversation_summary_chain = chains_and_tools_data.conversation_summary_chain
    replanner_chain_1 = chains_and_tools_data.replanner_chain_1
    replanner_chain_2 = chains_and_tools_data.replanner_chain_2
    general_llm_chain = chains_and_tools_data.general_llm_chain

    async def final_decision(state: PlanExecuteCritic):
            thread = {"configurable": {"thread_id": "inside"+f"{state['table_name']}_{state['session_id']}"}}
            a = await agent_executor.aget_state(thread)
            if a.tasks == ():
                response = a.values["messages"][-1].content
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
                return "interrupt_node_for_tool" #Command(goto="interrupt_node")    
    async def interrupt_node_for_tool(state: PlanExecuteCritic):
        """Asks the human if the plan is ok or not"""
        if interrupt_flag:
            is_approved = interrupt("approved?(yes/feedback)") 
        else:
            is_approved= "yes"
        state["tool_feedback"] = is_approved
        return {"tool_feedback": is_approved, "is_interrupted": True}


    async def interrupt_node_decision_for_tool(state: PlanExecuteCritic):
        if state["tool_feedback"]=='yes':
            return "executor_agent" #Command(goto="executor_agent")
        else:
            return "tool_interrupt" #Command(goto="feedback_collector")
        
    async def tool_interrupt(agent_state: PlanExecuteCritic):
        # Step 1: Get the current state of the agent
        thread = {"configurable": {"thread_id": "inside"+f"{agent_state['table_name']}_{agent_state['session_id']}"}}
            # Check if the agent is in a state where it can be interrupted
        # a = await agent_executor.aget_state(thread)
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
        feedback = agent_state["tool_feedback"]
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
        for i in executor_agent_response['messages']:
            i.pretty_print()
                    
        return {
            "response": executor_agent_response["messages"][-1].content,
            "executor_messages": executor_agent_response["messages"],
        }

    ### Build Graph
    workflow = StateGraph(PlanExecuteCritic)
    workflow.add_node("generate_past_conversation_summary", generate_past_conversation_summary)
    workflow.add_node("planner_agent", planner_agent)
    workflow.add_node("replanner_agent", replanner_agent)
    workflow.add_node("interrupt_node", interrupt_node)
    workflow.add_node("feedback_collector", feedback_collector)
    workflow.add_node("general_llm_call", general_llm_call)
    workflow.add_node("executor_agent", executor_agent)
    workflow.add_node("increment_step", increment_step)
    workflow.add_node("response_generator_agent", response_generator_agent)
    workflow.add_node("critic_agent", critic_agent)
    workflow.add_node("critic_based_planner_agent", critic_based_planner_agent)
    workflow.add_node("final_response", final_response)

    workflow.add_node("final_decision", final_decision)
    workflow.add_node("interrupt_node_for_tool", interrupt_node_for_tool)
    workflow.add_node("tool_interrupt", tool_interrupt)

    workflow.add_edge(START, "generate_past_conversation_summary")
    workflow.add_edge("generate_past_conversation_summary", "planner_agent")
    workflow.add_conditional_edges(
        "planner_agent",
        route_general_question,
        ["general_llm_call", "interrupt_node"],
    )
    workflow.add_conditional_edges(
        "interrupt_node",
        interrupt_node_decision,
        ["executor_agent", "feedback_collector"],
    )
    workflow.add_edge("feedback_collector", "replanner_agent")
    workflow.add_edge("replanner_agent", "interrupt_node")

    workflow.add_conditional_edges(
    "executor_agent",
    final_decision,
    ["interrupt_node_for_tool", "increment_step","final_response"],
    # ["interrupt_node_for_tool", "increment_step"],
    )
    workflow.add_conditional_edges(
    "interrupt_node_for_tool",
    interrupt_node_decision_for_tool,
    ["executor_agent", "tool_interrupt"],
    )
    workflow.add_conditional_edges(
    "tool_interrupt",
    final_decision,
    ["interrupt_node_for_tool", "increment_step","final_response"],
    )

    # workflow.add_edge("executor_agent", "increment_step")
    workflow.add_conditional_edges(
        "increment_step",
        check_plan_execution_status,
        ["executor_agent", "response_generator_agent"],
    )
    workflow.add_edge("response_generator_agent", "critic_agent")
    workflow.add_conditional_edges(
        "critic_agent",
        critic_decision,
        ["final_response", "critic_based_planner_agent"],
    )
    workflow.add_edge("critic_based_planner_agent", "executor_agent")
    workflow.add_edge("general_llm_call", "final_response")
    workflow.add_edge("final_response", END)

    log.info("Replanner, Executor, Critic Agent built successfully")
    return workflow

async def generate_response_replanner_executor_critic_agent(query,
                                                    multi_agent_config,
                                                    session_id,
                                                    table_name,
                                                    db_identifier,
                                                    reset_conversation,
                                                    model_name,
                                                    approval,
                                                    feedback,
                                                    project_name,
                                                    interrupt_flag=False,
                                                    tool_feedback=None
                                                    ):
    # Loading the model
    llm = load_model(model_name=model_name)
    async with AsyncPostgresSaver.from_conn_string(DB_URI) as checkpointer:
        agent_resp = ""
        try:

            # Build the planner, executor, and critic chains
            chains_and_tools_data = await build_replanner_executor_critic_chains(llm=llm,
                                                                        multi_agent_config=multi_agent_config,checkpointer=checkpointer,)

            workflow = await build_replanner_executor_critic_agent(llm,
                                                        chains_and_tools_data=chains_and_tools_data,
                                                        interrupt_flag=interrupt_flag)

            # Set up the graph configuration
            graph_config = {"configurable": {"thread_id": f"{db_identifier}_{session_id}"}, "recursion_limit": 100}

            if str(reset_conversation).lower()=="true":
                try:
                    # Delete the conversation history from the database
                    await delete_by_session_id_from_database(table_name=table_name,
                                                session_id=session_id
                                                )
                except Exception as e:
                    log.error(f"Error occurred while deleting conversation history for session {session_id}: {e}")
                    pass

            async def invoke(arg, approval, feedback,tool_feedback):
                app=workflow.compile(checkpointer=checkpointer)
                if not approval and not feedback:
                    with using_project(project_name):
                        return await app.ainvoke(arg, config=graph_config)
                elif approval=='yes':
                    with using_project(project_name):
                        return await app.ainvoke(Command(resume='yes'), config=graph_config)
                elif approval=='no' and not feedback:
                    with using_project(project_name):
                        return await app.ainvoke(Command(resume='no'), config=graph_config)
                elif approval=='no' and feedback is not None:
                    with using_project(project_name):
                        return await app.ainvoke(Command(resume=feedback), config=graph_config)
                elif tool_feedback is not None:
                    with using_project(project_name):
                        return await app.ainvoke(Command(resume=tool_feedback), config=graph_config)

            # Invoke the agent and get the response
            try:
                log.info(f"Invoking agent with query: {query}, session_id: {session_id}, reset_conversation: {reset_conversation}")
                agent_resp = await invoke({
                                'query': query,
                                'table_name': table_name,
                                'session_id': session_id,
                                'reset_conversation': reset_conversation,
                                'model_name': model_name,
                                "is_interrupted": False
                            },
                            approval,
                            feedback,
                            tool_feedback)
            except Exception as e:
                log.error(f"Error occurred during agent inference: {e}")
                agent_resp =  {"error": f"Error Occurred while inferring:\n{e}"}
        except asyncpg.PostgresError as e:
            log.error(f"Database error occurred: {e}")
            agent_resp =  {"error": f"Database error:\n{e}"}
        except Exception as e:
            log.error(f"Unknown error occurred: {e}")
            {"error": f"Unknown error occurred:\n{e}"}
        log.info(f"Agent response generated for session {session_id} and query {query}")
        return agent_resp


class ReplannerAgentInferenceRequest(BaseModel):
    """
    Pydantic model representing the input request for agent inference.
    This model captures the necessary details for querying the agent,
    including the application ID, query, session ID, and model-related information.
    """
    agentic_application_id: str  # ID of the agentic application
    query: str  # The query to be processed by the agent
    session_id: str  # Unique session identifier
    model_name: str  # Name of the llm model
    reset_conversation: bool = False# If true need to reset the conversation
    approval: str = None
    feedback: str = None
    prev_response: Dict = {}
    interrupt_flag: bool = False
    tool_feedback: str = None

async def human_in_the_loop_replanner_inference(request: ReplannerAgentInferenceRequest):
    """
    Handles the inference request for the Planner-Executor-Critic-replanner agent.

    Args:
        request (ReplannerAgentInferenceRequest): The request object containing the query, session ID, and other parameters.

    Returns:
        JSONResponse: A JSON response containing the agent's response and state.

    Raises:
        HTTPException: If an error occurs during processing.
    """
    try:
        # Extract request parameters
        agentic_application_id = request.agentic_application_id
        query = request.query
        session_id = request.session_id
        model_name = request.model_name
        reset_conversation = request.reset_conversation
        approval=request.approval
        feedback=request.feedback
        interrupt_flag = request.interrupt_flag
        tool_feedback=request.tool_feedback

        # Construct table and db identifier
        table_name = f'table_{agentic_application_id.replace("-","_")}'
        db_identifier = table_name
        # Retrieve agent tool configuration
        try:
            multi_agent_config = await get_agent_tool_config_planner_executor_critic(agentic_application_id=agentic_application_id)
            config=multi_agent_config
            agent_details= await get_agents_by_id(agentic_application_id=agentic_application_id)
            update_session_context(agent_type=agent_details[0]["agentic_application_type"],agent_name=agent_details[0]["agentic_application_name"])

        except Exception as e:
            log.error(f"Error retrieving agent tool configuration for Agentic Application ID {agentic_application_id}: {e}")
            return {"response": f"Could not find an application with Agentic Application ID: {agentic_application_id}. Please validate the provided Agentic Application ID", "state": {}}

        reset_conversation = str(request.reset_conversation).lower() == "true"
        match = re.search(r'([a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+)', session_id)
        user_name = match.group(0) if match else "guest"
        agent_name = agent_details[0]['agentic_application_name']
        project_name=agent_name+'-hitl_'+user_name
        register(
            project_name=project_name,
            auto_instrument=True,
            set_global_tracer_provider=False,
            batch=True
        )
        # Generate response using the agent
        response = await generate_response_replanner_executor_critic_agent(
            query=query,
            multi_agent_config=multi_agent_config,
            session_id=session_id,
            table_name=table_name,
            db_identifier=db_identifier,
            reset_conversation=reset_conversation,
            model_name=model_name,
            approval=approval,
            feedback=feedback,
            project_name=project_name,
            interrupt_flag=interrupt_flag,
            tool_feedback=tool_feedback

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
            # Insert the response into the evaluation data
            await insert_into_evaluation_data(session_id, agentic_application_id, config, response_evaluation, model_name)
        except Exception as e:
            log.error(f"Error inserting into evaluation data: {e}")
        log.info(f"Response generated for session {session_id} with query: {query}")
        return response

    except Exception as e:
        log.error(f"Error occurred during human-in-the-loop inference: {e}")
        raise HTTPException(status_code=500, detail=f"Internal Server Error: {str(e)}")

