# © 2024-25 Infosys Limited, Bangalore, India. All Rights Reserved.
import json
import ast
import re
import pandas as pd
from datetime import datetime, timezone
from typing import Annotated, List, Any, Dict, Literal
from typing_extensions import TypedDict
from pydantic import BaseModel, Field
from fastapi import HTTPException
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from langchain_core.output_parsers import StrOutputParser, JsonOutputParser
from langchain_core.prompts import PromptTemplate
from langchain_core.messages import AIMessage, HumanMessage, ChatMessage, AnyMessage
from langchain_core.prompts import ChatPromptTemplate
from langgraph.prebuilt import create_react_agent
from langgraph.graph.message import add_messages
from langgraph.graph import StateGraph, MessagesState, START, END
from langgraph.prebuilt import InjectedState
from langgraph_supervisor import create_supervisor
from langgraph_supervisor.handoff import create_forward_message_tool
from langgraph.types import Command, Send
from langchain_core.tools import tool

from phoenix.otel import register
from phoenix.trace import using_project

from src.models.model import load_model
from src.utils.helper_functions import get_timestamp
from src.prompts.prompts import conversation_summary_prompt
from inference import (
    AgentInferenceRequest, get_conversation_summary, format_messages,
    segregate_conversation_from_chat_history
)
from multi_agent_inference import render_text_description, format_past_steps_list, format_list_str
from database_manager import (
    get_agents_by_id, get_tools_by_id, delete_by_session_id_from_database, insert_chat_history_in_database,
    worker_agents_config_prompt
)
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


# === Custom task-based handoff tool factory ===
async def agent_as_tool_creation(*, agent_name: str, description: str = None, agent_executor: Any = None) -> Any:
    tool_description = description or f"Delegate task to {agent_name}"
    log.info(f"{agent_name} created as a tool for handoff.")

    @tool
    async def handoff_tool(
        task: Annotated[
            str,
            "Description of what the next agent should do, including all of the relevant context.",
        ],
    ) -> str:
        """Delegate subtask to agent based on task description."""
        agent_response = await agent_executor.ainvoke({"messages":[HumanMessage(content=task)]})
        return agent_response["messages"][-1].content
    
    handoff_tool.name = agent_name
    handoff_tool.description = tool_description

    return handoff_tool

# --- End of handoff tool factory ---


async def generate_response_meta_agent(query, agentic_application_id, session_id, table_name, model_name, reset_conversation, project_name):
    llm = load_model(model_name=model_name)
    agent_info_list = await get_agents_by_id(agentic_application_id=agentic_application_id)
    agent_info = agent_info_list[0]
    worker_agents = json.loads(agent_info["tools_id"])
    agent_configs, _, _ = await worker_agents_config_prompt(agentic_app_ids=worker_agents, llm=llm)

    # Meta Agent Chain
    meta_agent_system_prompt = json.loads(agent_info['system_prompt'])['SYSTEM_PROMPT_META_AGENT']
    meta_agent_system_prompt_input = """\
**User Input Context**
Past Conversation Summary:
{past_conversation_summary}

Ongoing Conversation:
{ongoing_conversation}

User Query:
{query}
"""

    # Chat summarization chain
    conversation_summary_prompt_template = PromptTemplate.from_template(conversation_summary_prompt)
    conversation_summary_chain = conversation_summary_prompt_template | llm | StrOutputParser()


    # --- Build Graph ---
    class OverallState(TypedDict):
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


    async def generate_past_conversation_summary(state: OverallState):
        """Generates past conversation summary and initializes state."""
        strt_tmstp = get_timestamp()
        if state["reset_conversation"]:
            state["ongoing_conversation"].clear()
            state["executor_messages"].clear()
            try:
                await delete_by_session_id_from_database(
                    table_name=state["table_name"],
                    session_id=state["session_id"]
                )
                conv_summary = ""
                log.info(f"Conversation history for session {state['session_id']} in table {state['table_name']} has been reset.")
            except Exception as e:
                log.error(f"Error resetting conversation history for session {state['session_id']} in table {state['table_name']}: {e}")
        else:
            conv_summary = await get_conversation_summary(
                conversation_summary_chain=conversation_summary_chain,
                table_name=state["table_name"],
                session_id=state["session_id"]
            )

        current_user_message = HumanMessage(content=state["query"], role="user_query")
        log.info(f"Meta Agent: Generated past conversation summary.")
        return {
            'past_conversation_summary': conv_summary,
            'executor_messages': current_user_message,
            'ongoing_conversation': current_user_message,
            'response': None,
            'start_timestamp': strt_tmstp
        }

    async def meta_agent_node(state: OverallState):
        """Creates a meta agent that supervises the worker agents."""
        handoff_tools = [
            await agent_as_tool_creation(
                agent_name=value['AGENT_NAME'],
                description=value['agentic_application_description'],
                agent_executor=value['agentic_application_executor']
            )
            for value in agent_configs.values()
        ]

        # forwarding_tool = create_forward_message_tool("supervisor") # The argument is the name to assign to the resulting forwarded message
        # handoff_tools.append(forwarding_tool)

        # Create supervisor Agent
        meta_agent = create_react_agent(
            model=llm,
            prompt=meta_agent_system_prompt,
            tools=handoff_tools,
        )

        log.info(f"Meta Agent created with {len(handoff_tools)} worker agents.")
        result = await meta_agent.ainvoke({
            "messages": [
                {
                    "role": "user",
                    "content": meta_agent_system_prompt_input.format(
                        past_conversation_summary=state["past_conversation_summary"],
                        ongoing_conversation=format_messages(state["ongoing_conversation"]),
                        query=state["query"]
                    ),
                }
            ]
        })
        final_response = result["messages"][-1].content
        log.info(f"Meta Agent response generated: {final_response}")
        return {
            "response": final_response,
            "executor_messages": result["messages"]
        }

    async def final_response_node(state: OverallState):
        """Stores the final response and updates the conversation history."""
        end_timestamp = get_timestamp()
        await insert_chat_history_in_database(
            table_name=state["table_name"],
            session_id=state["session_id"],
            start_timestamp=state["start_timestamp"],
            end_timestamp=end_timestamp,
            human_message=state["query"],
            ai_message=state["response"]
        )
        final_response_message = AIMessage(content=state["response"])
        log.info(f"Meta Agent's final response generated: {final_response_message.content}")
        return {
            "ongoing_conversation": final_response_message,
            "executor_messages": final_response_message,
            "end_timestamp": end_timestamp
        }


    ### Build Graph (Workflow)
    workflow = StateGraph(OverallState)
    workflow.add_node("generate_past_conversation_summary", generate_past_conversation_summary)
    workflow.add_node("meta_agent_node", meta_agent_node)
    workflow.add_node("final_response_node", final_response_node)

    # Define the workflow sequence
    workflow.add_edge(START, "generate_past_conversation_summary")
    workflow.add_edge("generate_past_conversation_summary", "meta_agent_node")
    workflow.add_edge("meta_agent_node", "final_response_node")
    workflow.add_edge("final_response_node", END)

    # Inference
    invocation_input = {
        "past_conversation_summary": "",
        "ongoing_conversation": [],
        "query": query,
        "table_name": table_name,
        "session_id": session_id,
        "reset_conversation": reset_conversation
    }

    graph_config = {"configurable": {"thread_id": f"{table_name}_{session_id}"}, "recursion_limit": 100}

    try:
        with using_project(project_name):
            async with AsyncPostgresSaver.from_conn_string(DB_URI) as checkpointer:
                app = workflow.compile(checkpointer=checkpointer)
                log.info(f"Meta Agent workflow compiled successfully with {len(agent_configs)} worker agents.")
                log.info(f"Starting inference for Meta Agent with query: {query}")
                agent_resp = await app.ainvoke(input=invocation_input, config=graph_config)
                log.info(f"Meta Agent inference completed successfully.")
                return agent_resp

    except Exception as e:
        # In case of an error, attempt to retrieve an error trace from Checkpoint
        try:
            async with AsyncPostgresSaver.from_conn_string(DB_URI) as checkpointer:
                response = await checkpointer.aget(graph_config)
                if response.get("channel_values", "").get("executor_messages", ""):
                    error_trace = response["channel_values"]["executor_messages"][-1]
                    log.error(f"Error Occurred while inferring.\n\nError Trace: {error_trace}")
                    return {"error": f"Error Occurred while inferring.\n\nError: {e}\nError Trace:\n{error_trace}"}
        except Exception as e2:
            log.error(f"Error while retrieving error trace from Checkpoint: {e2}")
            return {"error": f"Error Occurred while inferring:\n{e}\n{e2}"}


async def meta_agent_inference(request: AgentInferenceRequest):
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
        try:
            # Retrieve agent configuration based on the application ID
            agent_config = await get_agents_by_id(agentic_application_id=agentic_application_id)
            match = re.search(r'([a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+)', session_id)
            user_name = match.group(0) if match else "guest"
            agent_name = agent_config[0]['agentic_application_name']
            project_name=agent_name+'_'+user_name
            register(
                project_name=project_name,
                auto_instrument=True,
                set_global_tracer_provider=False,
                batch=True
            )
            update_session_context(agent_type=agent_config[0]["agentic_application_type"],agent_name=agent_config[0]["agentic_application_name"])
            if not agent_config:
                log.error(f"Could not find an application with Agentic Application ID: {agentic_application_id}")
                return {"response": f"Could not find an application with Agentic Application ID: {agentic_application_id}. Please validate the provided Agentic Application ID"}

        except Exception:
            # Return a message if the application is not found
            return {"response": f"Could not find an application with Agentic Application ID: {agentic_application_id}. Please validate the provided Agentic Application ID"}

        # Call generate_response function
        response = await generate_response_meta_agent(query=query,
                                                agentic_application_id=agentic_application_id,
                                                session_id=session_id,
                                                table_name=table_name,
                                                model_name=model_name,
                                                reset_conversation=reset_conversation,
                                                project_name=project_name
                                                )
        response["executor_messages"] = segregate_conversation_from_chat_history(response)
        # Return the generated response from the agent
        update_session_context(response=response['response'])
        log.info(f"Meta Agent response generated successfully for query: {query}")
        return response
    except Exception as e:
        # Catch any unhandled exceptions and raise a 500 internal server error
        log.error(f"Error occurred during meta agent inference: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"Internal Server Error: {str(e)}")




# For binding react agent to meta agent

async def build_react_agent_as_meta_agent_worker(llm, agent_config):
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
    local_var = {}
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


    agent_executor = create_react_agent(
        llm,
        tool_list,
        name=agent_config["AGENT_NAME"],
        state_modifier=agent_config["SYSTEM_PROMPT"]["SYSTEM_PROMPT_REACT_AGENT"]
    )
    log.info(f"React Agent {agent_config['AGENT_NAME']} created with tools: {', '.join([tool.__name__ for tool in tool_list])} built as Meta Agent Worker.")
    return agent_executor


# For binding multi agent to meta agent

class MultiAgentInfernceChainsForMetaAgentWorker():
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


async def build_planner_executor_critic_chains_for_meta_agent_worker(llm, multi_agent_config):
    # Setup Executor Tools
    data = MultiAgentInfernceChainsForMetaAgentWorker()
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
    agent_executor  = create_react_agent(model=llm,
                                         state_modifier=multi_agent_config["SYSTEM_PROMPT"].get("SYSTEM_PROMPT_EXECUTOR_AGENT", ""),
                                         tools=tool_list)
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
    log.info(f"Multi-Agent Inference Chains for Meta Agent Worker created with {len(tool_list)} tools.")
    return data


async def build_planner_executor_critic_agent_as_meta_agent_worker(llm, chains_and_tools_data: MultiAgentInfernceChainsForMetaAgentWorker, agent_name: str):
    class PlanExecuteCritic(TypedDict):
        query: str
        messages: Annotated[List[AnyMessage], add_messages]
        plan: List[str]
        past_steps_input: List[str]
        past_steps_output: List[str]
        response: str
        response_quality_score: float
        critique_points: str
        epoch: int
        step_idx: int # App Related vars
        start_timestamp: datetime
        end_timestamp: datetime

    async def planner_agent(state: PlanExecuteCritic):
        """
        This function takes the current state of the conversation and generates a plan for the agent to follow.

        Args:
            state (PlanExecuteCritic): The current state of the conversation, including past conversation summary, ongoing conversation, tools info, and the input query.

        Returns:
            dict: A dictionary containing the plan for the agent to follow.
        """
        strt_tmstp = get_timestamp()
        state["query"] = state["messages"][0].content
        # Format the query for the planner
        formatted_query = f'''\
Tools Info:
{render_text_description(tools)}

Input Query:
{state["query"]}
'''
        invocation_input = {"messages": [("user", formatted_query)]}
        planner_response = await output_parser(llm=llm,
                                         chain_1=planner_chain_1,
                                         chain_2=planner_chain_2,
                                        invocation_input=invocation_input,
                                        error_return_key="plan")
        log.info(f"Planner Agent generated plan: {planner_response['plan']}")
        return {
            "query": state["query"],
            "messages": ChatMessage(content="", plan=planner_response['plan'], role="assistant", category="plan"),
            "plan": planner_response['plan'],
            'response': None,
            'response_quality_score': None,
            'critique_points': None,
            'past_steps_input': None,
            'past_steps_output': None,
            'epoch': 0,
            'step_idx': 0,
            'start_timestamp': strt_tmstp
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
        step = state["plan"][state["step_idx"]]
        completed_steps = []
        completed_steps_responses = []
        task_formatted = state["query"] + "\n\n"
        if state["step_idx"]!=0:
            completed_steps = state["past_steps_input"][:state["step_idx"]]
            completed_steps_responses = state["past_steps_output"][:state["step_idx"]]
            task_formatted += f"Past Steps:\n{format_past_steps_list(completed_steps, completed_steps_responses)}"
        task_formatted += f"\n\nCurrent Step:\n{step}"
        executor_agent_response = await agent_executor.ainvoke({"messages": [("user", task_formatted.strip())]})
        completed_steps.append(step)
        completed_steps_responses.append(executor_agent_response["messages"][-1].content)
        log.info(f"Executor Agent executed step {state['step_idx']+1}/{len(state['plan'])}: {step}")
        return {
            "response": completed_steps_responses[-1],
            "past_steps_input": completed_steps,
            "past_steps_output": completed_steps_responses,
            "messages": executor_agent_response["messages"]
        }

    def increment_step(state: PlanExecuteCritic):
        log.info(f"Incrementing step index from {state['step_idx']} to {state['step_idx']+1}")
        return {"step_idx": state["step_idx"]+1}

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
User Query:
{state["query"]}

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
                log.info(f"Response Generator Agent generated response: {response_gen_response['response']}")
                return {"response": response_gen_response["response"]}
            else:
                log.error(f"Response Generator Agent failed to generate a valid response: {response_gen_response}")
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
Tools Info:
{render_text_description(tools)}

User Query:
{state["query"]}

Steps Completed to generate final response:
{format_past_steps_list(state["past_steps_input"], state["past_steps_output"])}

Final Response:
{state["response"]}
'''
        invocation_input = {"messages": [("user", formatted_query)]}
        critic_response = await output_parser(llm=llm,
                                              chain_1=critic_chain_1,
                                              chain_2=critic_chain_2,
                                              invocation_input=invocation_input,
                                              error_return_key="critique_points")

        if critic_response["critique_points"] and "error" in critic_response["critique_points"][0]:
            critic_response = {'response_quality_score': 0, 'critique_points': critic_response["critique_points"]}
        log.info(f"Critic Agent evaluated response with quality score: {critic_response['response_quality_score']}")
        return {
            "response_quality_score": critic_response["response_quality_score"],
            "critique_points": critic_response["critique_points"],
            "messages": ChatMessage(
                content="",
                critique_points=critic_response["critique_points"],
                critic_response_quality_score=critic_response["response_quality_score"],
                role="assistant",
                category="critic-response"
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
Tools Info:
{render_text_description(tools)}

User Query:
{state["query"]}

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
        log.info(f"Critic-Based Planner Agent generated plan: {critic_planner_response['plan']}")
        return {
            "plan": critic_planner_response["plan"],
            "messages": ChatMessage(content="", plan=critic_planner_response['plan'], role="assistant", category="critic-plan"),
            "step_idx": 0
        }

    def final_response(state: PlanExecuteCritic):
        """
        This function handles the final response of the conversation.
        Args:
            state: A PlanExecuteCritic object containing the state of the conversation.
        Returns:
            A dictionary containing the final response and the end timestamp.
        """
        end_timestamp = get_timestamp()
        response = state['response']
        response = response if response else "No plans to execute"

        final_response_message = AIMessage(content=response)
        log.info(f"Final response generated: {final_response_message.content}")
        return {
            "messages": final_response_message,
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

    def route_non_planner_question(state: PlanExecuteCritic):
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
            return "final_response"
        else:
            return "executor_agent"

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

    ### Build Graph
    workflow = StateGraph(PlanExecuteCritic)
    workflow.add_node("planner_agent", planner_agent)
    workflow.add_node("executor_agent", executor_agent)
    workflow.add_node("increment_step", increment_step)
    workflow.add_node("response_generator_agent", response_generator_agent)
    workflow.add_node("critic_agent", critic_agent)
    workflow.add_node("critic_based_planner_agent", critic_based_planner_agent)
    workflow.add_node("final_response", final_response)

    workflow.add_edge(START, "planner_agent")
    workflow.add_conditional_edges(
        "planner_agent",
        route_non_planner_question,
        ["final_response", "executor_agent"],
    )
    workflow.add_edge("executor_agent", "increment_step")
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
    workflow.add_edge("final_response", END)

    app = workflow.compile(name=agent_name)
    log.info(f"Planner-Executor-Critic Agent {agent_name} created as Meta Agent Worker.")
    return app

