# © 2024-25 Infosys Limited, Bangalore, India. All Rights Reserved.
import re
import json
import copy
from datetime import datetime
from copy import deepcopy
from abc import ABC, abstractmethod
from typing_extensions import TypedDict
from typing import Any, List, Dict, Optional, Annotated, Union, Literal
from fastapi import HTTPException

from langchain_core.tools import BaseTool, StructuredTool, tool
from langgraph.types import Command
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import JsonOutputParser, StrOutputParser
from langgraph.prebuilt import create_react_agent
from langchain_core.messages import AIMessage, HumanMessage, ChatMessage, AnyMessage
from langgraph.graph.message import add_messages
from langgraph.graph import START, END
from langgraph.graph.state import CompiledStateGraph, StateGraph

from src.utils.helper_functions import get_timestamp
from src.inference.inference_utils import InferenceUtils
from src.schemas import AgentInferenceRequest
from src.utils.secrets_handler import get_user_secrets, current_user_email, get_public_key

from phoenix.otel import register
from phoenix.trace import using_project
from telemetry_wrapper import logger as log, update_session_context
from src.utils.stream_sse import SSEManager


# Define common TypedDict for state if applicable to all workflows
# This state can be extended by specific workflow implementations
class BaseWorkflowState(TypedDict):
    query: str
    response: str
    past_conversation_summary: str
    executor_messages: Annotated[List[AnyMessage], add_messages]
    ongoing_conversation: Annotated[List[AnyMessage], add_messages]
    agentic_application_id: str
    session_id: str
    model_name: str
    start_timestamp: datetime
    end_timestamp: datetime
    reset_conversation: Optional[bool] = False
    errors: List[str]
    parts: List[Dict[Any, Any]]  # For formatted response parts
    parts_storage_dict: Annotated[Dict[Any, Any], InferenceUtils.add_parts]  # For storing parts temporarily
    response_formatting_flag: bool = True
    context_flag : bool = True

class BaseAgentInference(ABC):
    """
    Abstract base class for LangGraph-based inference workflows.
    Provides common dependencies and defines the interface for building workflows.
    """

    def __init__(self, inference_utils: InferenceUtils):
        self.inference_utils = inference_utils
        self.chat_service = inference_utils.chat_service
        self.tool_service = inference_utils.tool_service
        self.mcp_tool_service = self.tool_service.mcp_tool_service
        self.agent_service = inference_utils.agent_service
        self.model_service = inference_utils.model_service
        self.feedback_learning_service = inference_utils.feedback_learning_service
        self.evaluation_service = inference_utils.evaluation_service


    # --- Helper Methods ---

    async def _get_react_agent_as_executor_agent(self,
                                                 llm: Any,
                                                 system_prompt: str,
                                                 checkpointer: Any = None,
                                                 tool_ids: List[str] = [],
                                                 interrupt_tool: bool = False
                                                ) -> Any:
        """
        Helper method to create a React agent as an executor agent with tools loaded dynamically.
        This function now supports loading both Python code-based tools and MCP tools.
        """
        # local_var for exec() context, including secrets handlers
        local_var = {
            "get_user_secrets": get_user_secrets,
            "current_user_email": current_user_email,
            "get_public_secrets": get_public_key
        }

        tool_list: List[BaseTool | StructuredTool] = []
        manage_memory_tool = await self.inference_utils.create_manage_memory_tool()
        tool_list.append(manage_memory_tool)

        search_memory_tool = await self.inference_utils.create_search_memory_tool(
            embedding_model=self.inference_utils.embedding_model
        )
        tool_list.append(search_memory_tool)

        mcp_server_ids = []

        for tool_id in tool_ids:
            if tool_id.startswith("mcp_"):
                mcp_server_ids.append(tool_id)
                continue

            try:
                log.info(f"Loading Python tool for ID: {tool_id} - CACHE LOG")
                tool_record = await self.tool_service.tool_repo.get_tool_record(tool_id=tool_id)
                log.info(f"Python tool reading completed for ID: {tool_id} - CACHE LOG")
                if tool_record:
                    tool_record = tool_record[0]
                    codes = tool_record["code_snippet"]
                    tool_name = tool_record["tool_name"]
                    exec(codes, local_var)
                    tool_list.append(local_var[tool_name])
                else:
                    log.warning(f"Python tool record for ID {tool_id} not found.")
                    raise HTTPException(status_code=404, detail=f"Python tool record for ID {tool_id} not found.")

            except HTTPException:
                raise # Re-raise HTTPExceptions directly
            except Exception as e:
                log.error(f"Error occurred while loading tool {tool_id}: {e}")
                raise HTTPException(status_code=500, detail=f"Error occurred while loading tool {tool_id}: {e}")

        if mcp_server_ids:
            try:
                mcp_server_details = await self.mcp_tool_service.get_live_mcp_tools_from_servers(tool_ids=mcp_server_ids)
                mcp_live_tools: List[StructuredTool] = mcp_server_details.get("all_live_tools", [])
                if mcp_live_tools:
                    tool_list.extend(mcp_live_tools)

            except Exception as e:
                log.error(f"Error occurred while loading tools from MCP servers {mcp_server_ids}: {e}")
                raise HTTPException(status_code=500, detail=f"Error occurred while loading tools from MCP servers {mcp_server_ids}: {e}")

        interrupt_before = ["tools"] if interrupt_tool and tool_list else None
        try:
            executor_agent = create_react_agent(
                llm,
                tools=tool_list,
                checkpointer=checkpointer,
                interrupt_before=interrupt_before,
                prompt=system_prompt
            )
            return executor_agent, tool_list

        except Exception as e:
            log.error(f"Error occurred while creating agent executor: {e}")
            raise HTTPException(status_code=500, detail=f"Error occurred while creating agent executor: {e}")

    @staticmethod
    async def _get_chains(llm: Any, system_prompt: str, *, get_json_chain: bool = True, get_str_chain: bool = True):
        """
        Helper method to create LangGraph chains for the agent based on the system prompt.
        """
        try:
            system_prompt_template = ChatPromptTemplate.from_messages([
                    ("system", system_prompt),
                    ("placeholder", "{messages}")
                ]
            )
            json_chain = str_chain = None

            if get_json_chain:
                json_chain = system_prompt_template | llm | JsonOutputParser()

            if get_str_chain:
                str_chain = system_prompt_template | llm | StrOutputParser()

            return json_chain, str_chain
        except Exception as e:
            log.error(f"Error occurred while creating chains: {e}")
            raise HTTPException(status_code=500, detail=f"Error occurred while creating chains: {e}")

    async def _get_agent_config(self, agentic_application_id: str) -> dict:
        """
        Retrieves the configuration for an agent and its associated tools.

        Args:
            agentic_application_id (str, optional): Agentic application ID.

        Returns:
            dict: A dictionary containing the system prompt and tool information.
        """
        # Retrieve agent details from the database
        log.info("Retrieving agent details - CACHE LOG")
        result = await self.agent_service.agent_repo.get_agent_record(agentic_application_id=agentic_application_id)
        log.info("Retrieved agent details successfully - CACHE LOG")
        if not result:
            log.error(f"Agentic Application ID {agentic_application_id} not found.")
            raise HTTPException(status_code=404, detail=f"Agentic Application ID {agentic_application_id} not found.")
        result = result[0]

        agent_config = {
            "AGENT_NAME": result["agentic_application_name"],
            "SYSTEM_PROMPT": json.loads(result["system_prompt"]),
            "TOOLS_INFO": json.loads(result["tools_id"]),
            "AGENT_DESCRIPTION": result["agentic_application_description"],
            "AGENT_TYPE": result['agentic_application_type']
        }
        log.info(f"Agent tools configuration retrieved for Agentic Application ID: {agentic_application_id}")
        return agent_config

    # Abstract Methods

    @abstractmethod
    async def _build_agent_and_chains(self, llm, agent_config, checkpointer, tool_interrupt_flag: bool = False) -> Any:
        """
        Abstract method to build and compile the LangGraph chains for a specific agent type.
        """
        pass

    @abstractmethod
    async def _build_workflow(self, chains: dict, flags: Dict[str, bool] = {}) -> StateGraph:
        """
        Abstract method to build the LangGraph workflow for a specific agent type.
        """
        pass

    # Common Inference Method

    @staticmethod
    async def _astream(
        app: CompiledStateGraph,
        invocation_input: dict,
        config: dict,
        *,
        is_plan_approved: Literal["yes", "no", None] = None,
        plan_feedback: str = None,
        tool_feedback: str = None,
        sse_manager: SSEManager = None,
        session_id: str = None
        ):

        def process_output_by_key(output):
            """Process the output dictionary and return formatted data based on specific keys"""
            for key in output.keys():
                if key == "generate_past_conversation_summary":
                    return {
                        "debug_key": "generate_past_conversation_summary",
                        "debug_value": output[key]
                    }
                elif key == "executor_agent":
                    return {
                        "debug_key": "executor_agent", 
                        "debug_value": output[key].get("response", "")
                    }
                elif key == "final_response":
                    return {
                        "debug_key": "final_response",
                        "debug_value": "Data Formatting completed"
                    }
                else:
                    return {
                        "debug_key": key,
                        "debug_value": str(output[key])
                    }
            return {}

        async def process_stream(stream_generator):
            """Helper function to process any stream"""
            nonlocal final_response
            async for output in stream_generator:
                # Send processed output via SSE
                if sse_manager is not None:
                    processed_data = process_output_by_key(output)
                    log.info(f"sending data to {session_id}")
                    if processed_data:
                        await sse_manager.send(session_id, processed_data)
                    else:
                        await sse_manager.send(session_id, output)
                
                # Update final_response
                for k in output.keys():
                    final_response = await InferenceUtils.update_dictionary(final_response, output[k])
        
        final_response = copy.deepcopy(invocation_input)
        
        # Determine which stream to use based on conditions
        if not is_plan_approved and not tool_feedback:
            await process_stream(app.astream(invocation_input, config=config))
        elif is_plan_approved == "yes":
            await process_stream(app.astream(Command(resume="yes"), config=config))
        elif is_plan_approved == "no" and not plan_feedback:
            await process_stream(app.astream(Command(resume="no"), config=config))
        elif is_plan_approved == "no" and plan_feedback is not None:
            await process_stream(app.astream(Command(resume=plan_feedback), config=config))
        elif tool_feedback is not None:
            await process_stream(app.astream(Command(resume=tool_feedback), config=config))
        else:
            return {"error": "Invalid parameters provided for astream."}
        
        return final_response

    @staticmethod
    async def _ainvoke(
                    app: CompiledStateGraph,
                    invocation_input: dict,
                    config: dict,
                    *,
                    is_plan_approved: Literal["yes", "no", None] = None,
                    plan_feedback: str = None,
                    tool_feedback: str = None
                ):
        """
        Asynchronously invokes the agent application with the provided input and configuration.
        """
        if not is_plan_approved and not tool_feedback:
            return await app.ainvoke(invocation_input, config=config)
        if is_plan_approved == 'yes':
            return await app.ainvoke(Command(resume='yes'), config=config)
        if is_plan_approved == 'no' and not plan_feedback:
            return await app.ainvoke(Command(resume='no'), config=config)
        if is_plan_approved == 'no' and plan_feedback is not None:
            return await app.ainvoke(Command(resume=plan_feedback), config=config)
        if tool_feedback is not None:
            return await app.ainvoke(Command(resume=tool_feedback), config=config)
        return {"error": "Invalid parameters provided for ainvoke."}

    async def _generate_response(
                                self,
                                query: str,
                                agentic_application_id: str,
                                session_id: str,
                                model_name: str,
                                agent_config: dict,
                                project_name: str,
                                reset_conversation: bool = False,
                                *,
                                plan_verifier_flag: bool = False,
                                is_plan_approved: Literal["yes", "no", None] = None,
                                response_formatting_flag:bool = True,
                                plan_feedback: str = None,
                                tool_interrupt_flag: bool = False,
                                tool_feedback: str = None,
                                context_flag: bool = True,
                                sse_manager: SSEManager=None
                            ):
        if not plan_verifier_flag:
            is_plan_approved = plan_feedback = None

        llm = await self.model_service.get_llm_model(model_name=model_name)
        agent_resp = {}

        log.debug("Building agent and chains")
        async with await self.chat_service.get_checkpointer_context_manager() as checkpointer:
            chains = await self._build_agent_and_chains(llm, agent_config, checkpointer, tool_interrupt_flag=tool_interrupt_flag)
            if reset_conversation:
                try:
                    await self.chat_service.delete_session(agentic_application_id, session_id)
                    log.info(f"Conversation history for session {session_id} has been reset.")
                except Exception as e:
                    log.error(f"Error occurred while resetting conversation: {e}")

            flags = {
                "plan_verifier_flag": plan_verifier_flag,
                "tool_interrupt_flag": tool_interrupt_flag,
                "response_formatting_flag": response_formatting_flag,
                "context_flag": context_flag
            }
            log.debug("Building workflow")
            workflow = await self._build_workflow(chains, flags)
            log.debug("Workflow built successfully")
            app = workflow.compile(checkpointer=checkpointer)
            log.debug("Workflow compiled successfully")
            # Configuration for the workflow
            thread_id = await self.chat_service._get_thread_id(agentic_application_id, session_id)
            graph_config = await self.chat_service._get_thread_config(thread_id)

            log.info(f"Invoking executor agent for query: {query}\n with Session ID: {session_id} and Agent Id: {agentic_application_id}")
            with using_project(project_name):
                try:
                    invocation_input = {
                        'query': query,
                        'agentic_application_id': agentic_application_id,
                        'session_id': session_id,
                        'reset_conversation': reset_conversation,
                        'model_name': model_name,
                        'is_tool_interrupted': False,
                        "response_formatting_flag": response_formatting_flag,
                        "context_flag": context_flag
                    }

                    # final_step = None
                    # final_step = await self._astream(
                    #     app,
                    #     invocation_input,
                    #     config=graph_config,
                    #     is_plan_approved=is_plan_approved,
                    #     plan_feedback=plan_feedback,
                    #     tool_feedback=tool_feedback,
                    #     sse_manager= sse_manager,
                    #     session_id=session_id
                    # )

                    # agent_resp = final_step if final_step is not None else {"error": "No response received from streaming"}

                    # log.info(f"Agent invoked successfully for query: {query} with session ID: {session_id}")

                    agent_resp = await self._ainvoke(
                        app,
                        invocation_input,
                        config=graph_config,
                        is_plan_approved=is_plan_approved,
                        plan_feedback=plan_feedback,
                        tool_feedback=tool_feedback
                    )

                    log.info(f"Agent invoked successfully for query: {query} with session ID: {session_id}")

                except Exception as e:
                    await checkpointer.setup()
                    response = await checkpointer.aget(graph_config)

                    if response.get("channel_values", {}).get("executor_messages", None):
                        error_trace = response["channel_values"]["executor_messages"][-1]
                        agent_resp = {"error": f"Error Occurred while inferencing: {e}\nError Trace:\n{error_trace}"}
                    else:
                        agent_resp = {"error": f"Error Occurred while inferencing: {e}"}
                    log.error(agent_resp.get("error", "Unknown error occurred during agent inference."))

            return agent_resp

    async def run(self,
                  inference_request: AgentInferenceRequest,
                  *,
                  agent_config: Optional[Union[dict, None]] = None,
                  insert_into_eval_flag: bool = True,
                  sse_manager :SSEManager= None
                ) -> Any:
        """
        Runs the Agent inference workflow.

        Args:
            request (AgentInferenceRequest): The request object containing all necessary parameters.
        """
        agentic_application_id = inference_request.agentic_application_id
        if not agent_config:
            try:
                agent_config = await self._get_agent_config(agentic_application_id)
            except Exception as e:
                log.error(f"Error occurred while retrieving agent configuration: {e}")
                raise HTTPException(status_code=500, detail=f"Error occurred while retrieving agent configuration: {str(e)}")

        try:
            query = inference_request.query
            session_id = inference_request.session_id
            model_name = inference_request.model_name
            reset_conversation = inference_request.reset_conversation
            tool_interrupt_flag = inference_request.tool_verifier_flag
            tool_feedback = inference_request.tool_feedback
            plan_verifier_flag = inference_request.plan_verifier_flag
            response_formatting_flag = inference_request.response_formatting_flag
            context_flag = inference_request.context_flag
            is_plan_approved = inference_request.is_plan_approved
            plan_feedback = inference_request.plan_feedback

            match = re.search(r'([a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+)', session_id)
            user_name = match.group(0) if match else "guest"
            agent_name = agent_config["AGENT_NAME"]
            project_name=agent_name+'_'+user_name

            register(
                project_name=project_name,
                auto_instrument=True,
                set_global_tracer_provider=False,
                batch=True
            )

            update_session_context(agent_type=agent_config["AGENT_TYPE"], agent_name=agent_name)

            # For react agent, we need to add knowledge base retriever tool if knowledgebase_name is provided
            if agent_config["AGENT_TYPE"] == "react_agent" and hasattr(inference_request, "knowledgebase_name") and inference_request.knowledgebase_name:
                knowledgebase_retriever_tool = await self.tool_service.get_tool(tool_name="knowledgebase_retriever")
                knowledgebase_retriever_id = knowledgebase_retriever_tool[0]["tool_id"] if knowledgebase_retriever_tool else None
                if not knowledgebase_retriever_id:
                    log.error("Knowledge Base Retriever tool not found. Please ensure it is registered in the system.")
                    return {"response": "Knowledge Base Retriever tool not found. Please ensure it is registered in the system."}

                agent_config['TOOLS_INFO'].append(knowledgebase_retriever_id)
                agent_config['SYSTEM_PROMPT']['SYSTEM_PROMPT_REACT_AGENT'] += f" ;Use Knowledge Base: {inference_request.knowledgebase_name} regarding the query and if any useful information found use it and pass it to any tools if no useful content is extracted call use the agent as if the knowledgebase tool is not existing, but use the instructions for each of tools and execute the query."


            # Generate response using the React agent workflow
            response = await self._generate_response(
                query=query,
                agentic_application_id=agentic_application_id,
                session_id=session_id,
                model_name=model_name,
                agent_config=agent_config,
                project_name=project_name,
                reset_conversation=reset_conversation,
                plan_verifier_flag=plan_verifier_flag,
                response_formatting_flag=response_formatting_flag,
                context_flag=context_flag,
                is_plan_approved=is_plan_approved,
                plan_feedback=plan_feedback,
                tool_interrupt_flag=tool_interrupt_flag,
                tool_feedback=tool_feedback,
                sse_manager= sse_manager
            )

            if isinstance(response, str):
                update_session_context(response=response)
                response = {"error": response}
            elif "error" in response:
                update_session_context(response=response["error"])
            else:
                update_session_context(response=response['response'])
                response_evaluation = deepcopy(response)
                response_evaluation["executor_messages"] = await self.chat_service.segregate_conversation_from_raw_chat_history_with_json_like_steps(response)
                response["executor_messages"] = await self.chat_service.segregate_conversation_from_raw_chat_history_with_pretty_steps(response)

            if insert_into_eval_flag:
                try:
                    await self.evaluation_service.log_evaluation_data(session_id, agentic_application_id, agent_config, response_evaluation, model_name)
                except Exception as e:
                    log.error(f"Error Occurred while inserting into evaluation data: {e}")

            return response

        except Exception as e:
            # Catch any unhandled exceptions and raise a 500 internal server error
            log.error(f"Error Occurred in agent inference: {e}")
            raise HTTPException(status_code=500, detail=f"Internal Server Error: {str(e)}")


class BaseMetaTypeAgentInference(BaseAgentInference):
    """
    Base class for meta-type agent inference.
    """

    def __init__(self, inference_utils: InferenceUtils):
        super().__init__(inference_utils)


    # --- Helper Methods ---

    async def _get_planner_executor_critic_agent_as_worker_agent(self,
                                                                 llm: Any,
                                                                 system_prompts: str,
                                                                 checkpointer: Any = None,
                                                                 tool_ids: List[str] = [],
                                                                 interrupt_tool: bool = False
                                                                 ) -> Any:
        """
        Creates a planner-executor-critic agent as a meta agent worker with tools loaded dynamically.
        """
        # System Prompts
        planner_system_prompt = system_prompts.get("SYSTEM_PROMPT_PLANNER_AGENT", "").replace("{", "{{").replace("}", "}}")
        critic_based_planner_system_prompt = system_prompts.get("SYSTEM_PROMPT_CRITIC_BASED_PLANNER_AGENT", "").replace("{", "{{").replace("}", "}}")
        executor_system_prompt = system_prompts.get("SYSTEM_PROMPT_EXECUTOR_AGENT", "")
        critic_system_prompt = system_prompts.get("SYSTEM_PROMPT_CRITIC_AGENT", "").replace("{", "{{").replace("}", "}}")
        response_generator_system_prompt = system_prompts.get("SYSTEM_PROMPT_RESPONSE_GENERATOR_AGENT", "").replace("{", "{{").replace("}", "}}")

        # Agents and Chains
        planner_chain_json, planner_chain_str = await self._get_chains(llm, planner_system_prompt)
        executor_agent, tool_list = await self._get_react_agent_as_executor_agent(
                                        llm,
                                        system_prompt=executor_system_prompt,
                                        checkpointer=checkpointer,
                                        tool_ids=tool_ids,
                                        interrupt_tool=interrupt_tool
                                    )
        critic_chain_json, critic_chain_str = await self._get_chains(llm, critic_system_prompt)
        response_gen_chain_json, response_gen_chain_str = await self._get_chains(llm, response_generator_system_prompt)
        critic_planner_chain_json, critic_planner_chain_str = await self._get_chains(llm, critic_based_planner_system_prompt)

        if not llm or not executor_agent or not planner_chain_json or not planner_chain_str or \
                not critic_planner_chain_json or not critic_planner_chain_str or not critic_chain_json or \
                not critic_chain_str or not response_gen_chain_json or not response_gen_chain_str:
            raise HTTPException(status_code=500, detail="Required chains or agent executor are missing")

        # State Schema
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

        # Nodes

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
{await self.tool_service.render_text_description_for_tools(tool_list)}

Input Query:
{state["query"]}
'''
            invocation_input = {"messages": [("user", formatted_query)]}
            planner_response = await self.inference_utils.output_parser(
                                                            llm=llm,
                                                            chain_1=planner_chain_json,
                                                            chain_2=planner_chain_str,
                                                            invocation_input=invocation_input,
                                                            error_return_key="plan"
                                                        )
            log.info(f"Planner Agent generated plan: {planner_response['plan']}")
            return {
                "query": state["query"],
                "messages": ChatMessage(content=planner_response['plan'], role="plan"),
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

        async def executor_agent_node(state: PlanExecuteCritic):
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
                task_formatted += f"Past Steps:\n{await self.inference_utils.format_past_steps_list(completed_steps, completed_steps_responses)}"
            task_formatted += f"\n\nCurrent Step:\n{step}"
            executor_agent_response = await executor_agent.ainvoke({"messages": [("user", task_formatted.strip())]})
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
{await self.inference_utils.format_past_steps_list(state["past_steps_input"], state["past_steps_output"])}

Final Response from Executor Agent:
{state["response"]}
'''
            invocation_input = {"messages": [("user", formatted_query)]}
            response_gen_response = await self.inference_utils.output_parser(
                                                                llm=llm,
                                                                chain_1=response_gen_chain_json,
                                                                chain_2=response_gen_chain_str,
                                                                invocation_input=invocation_input,
                                                                error_return_key="response"
                                                            )
            if isinstance(response_gen_response, dict) and "response" in response_gen_response:
                    log.info(f"Response Generator Agent generated response: {response_gen_response['response']}")
                    return {"response": response_gen_response["response"]}
            else:
                log.error(f"Response generation failed for session {state['session_id']}")
                result = await llm.ainvoke(f"Format the response in Markdown Format.\n\nResponse: {response_gen_response}")
                return {"response": result.content}

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
{await self.tool_service.render_text_description_for_tools(tool_list)}

User Query:
{state["query"]}

Steps Completed to generate final response:
{await self.inference_utils.format_past_steps_list(state["past_steps_input"], state["past_steps_output"])}

Final Response:
{state["response"]}
'''
            invocation_input = {"messages": [("user", formatted_query)]}
            critic_response = await self.inference_utils.output_parser(
                                                            llm=llm,
                                                            chain_1=critic_chain_json,
                                                            chain_2=critic_chain_str,
                                                            invocation_input=invocation_input,
                                                            error_return_key="critique_points"
                                                        )

            if critic_response["critique_points"] and "error" in critic_response["critique_points"][0]:
                critic_response = {'response_quality_score': 0, 'critique_points': critic_response["critique_points"]}
            log.info(f"Critic Agent evaluated response with quality score: {critic_response['response_quality_score']}")
            return {
                "response_quality_score": critic_response["response_quality_score"],
                "critique_points": critic_response["critique_points"],
                "messages": ChatMessage(
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
Tools Info:
{await self.tool_service.render_text_description_for_tools(tool_list)}

User Query:
{state["query"]}

Steps Completed Previously to Generate Final Response:
{await self.inference_utils.format_past_steps_list(state["past_steps_input"], state["past_steps_output"])}

Final Response:
{state["response"]}

Response Quality Score:
{state["response_quality_score"]}

Critique Points:
{await self.inference_utils.format_list_str(state["critique_points"])}
'''

            invocation_input = {"messages": [("user", formatted_query)]}
            critic_planner_response = await self.inference_utils.output_parser(
                                                                    llm=llm,
                                                                    chain_1=critic_planner_chain_json,
                                                                    chain_2=critic_planner_chain_str,
                                                                    invocation_input=invocation_input,
                                                                    error_return_key="plan"
                                                                )
            log.info(f"Critic-Based Planner Agent generated plan: {critic_planner_response['plan']}")
            return {
                "plan": critic_planner_response["plan"],
                "messages": ChatMessage(content=critic_planner_response['plan'], role="critic-plan"),
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
                "executor_agent_node": Otherwise.
            """
            if state["step_idx"]==len(state["plan"]):
                return "response_generator_agent"
            else:
                return "executor_agent_node"

        def route_non_planner_question(state: PlanExecuteCritic):
            """
            Determines the appropriate agent to handle a general question based on the current state.
            Args:
                state: The current state of the PlanExecuteCritic object.

            Returns:
                A string representing the agent to call:
                    - "general_llm_call": If there is no plan or the first step in the plan does not have a "STEP" key.
                    - "executor_agent_node": If there is a plan and the first step has a "STEP" key.
            """
            if not state["plan"] or "STEP" not in state["plan"][0]:
                return "final_response"
            else:
                return "executor_agent_node"

        ### Build Graph

        workflow = StateGraph(PlanExecuteCritic)
        workflow.add_node("planner_agent", planner_agent)
        workflow.add_node("executor_agent_node", executor_agent_node)
        workflow.add_node("increment_step", increment_step)
        workflow.add_node("response_generator_agent", response_generator_agent)
        workflow.add_node("critic_agent", critic_agent)
        workflow.add_node("critic_based_planner_agent", critic_based_planner_agent)
        workflow.add_node("final_response", final_response)

        workflow.add_edge(START, "planner_agent")
        workflow.add_conditional_edges(
            "planner_agent",
            route_non_planner_question,
            ["final_response", "executor_agent_node"],
        )
        workflow.add_edge("executor_agent_node", "increment_step")
        workflow.add_conditional_edges(
            "increment_step",
            check_plan_execution_status,
            ["executor_agent_node", "response_generator_agent"],
        )
        workflow.add_edge("response_generator_agent", "critic_agent")
        workflow.add_conditional_edges(
            "critic_agent",
            critic_decision,
            ["final_response", "critic_based_planner_agent"],
        )
        workflow.add_edge("critic_based_planner_agent", "executor_agent_node")
        workflow.add_edge("final_response", END)

        app = workflow.compile()
        log.info(f"Planner-Executor-Critic Agent created as Meta Agent Worker.")
        return app, tool_list

    # === Custom task-based handoff tool factory ===
    @staticmethod
    async def _create_agent_as_tool(*, agent_name: str, description: str = None, worker_agent: Any = None) -> Any:
        """
        Creates a tool that delegates tasks to a specified agent.
        This tool can be used to hand off tasks to the specified agent based on the task description.
        """
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
            agent_response = await worker_agent.ainvoke({"messages":[HumanMessage(content=task)]})
            return agent_response["messages"][-1].content
        
        handoff_tool.name = agent_name
        handoff_tool.description = tool_description

        return handoff_tool

    async def _get_react_agent_as_supervisor_agent(self,
                                                   llm: Any,
                                                   system_prompt: str,
                                                   checkpointer: Any = None,
                                                   worker_agent_ids: List[str] = [],
                                                   interrupt_tool: bool = False
                                                   ) -> Any:
        """
        Helper method to create a React agent as an supervisor or meta agent with agents loaded dynamically.
        """
        worker_agents_as_tools_list = []
        manage_memory_tool = await self.inference_utils.create_manage_memory_tool()
        worker_agents_as_tools_list.append(manage_memory_tool)

        search_memory_tool = await self.inference_utils.create_search_memory_tool(
            embedding_model=self.inference_utils.embedding_model
        )
        worker_agents_as_tools_list.append(search_memory_tool)

        for worker_agent_id in worker_agent_ids:
            worker_agent_config = await self._get_agent_config(agentic_application_id=worker_agent_id)

            worker_agent_type = worker_agent_config["AGENT_TYPE"]
            worker_agent_description = worker_agent_config.get("AGENT_DESCRIPTION")
            worker_agent_system_prompt = worker_agent_config.get("SYSTEM_PROMPT")
            worker_agent_tool_ids = worker_agent_config.get("TOOLS_INFO")
            worker_agent_name = worker_agent_config.get("AGENT_NAME")
            worker_agent_name = await self.agent_service.agent_service_utils._normalize_agent_name(worker_agent_name)

            if worker_agent_type == "react_agent":
                worker_agent, _ = await self._get_react_agent_as_executor_agent(
                                        llm=llm,
                                        system_prompt=worker_agent_system_prompt.get("SYSTEM_PROMPT_REACT_AGENT", ""),
                                        tool_ids=worker_agent_tool_ids
                                    )
            elif worker_agent_type == "multi_agent":
                worker_agent, _ = await self._get_planner_executor_critic_agent_as_worker_agent(
                    llm=llm,
                    system_prompts=worker_agent_system_prompt,
                    tool_ids=worker_agent_tool_ids,
                )
            else:
                err = f"Meta agent does not support worker agent of type '{worker_agent_type}' yet."
                log.error(err)
                raise HTTPException(status_code=501, detail=err)

            worker_agents_as_tools_list.append(
                await self._create_agent_as_tool(
                    agent_name=worker_agent_name,
                    description=worker_agent_description,
                    worker_agent=worker_agent
                )
            )

        try:
            supervisor_agent = create_react_agent(
                model=llm,
                prompt=system_prompt,
                tools=worker_agents_as_tools_list
            )
            return supervisor_agent, worker_agents_as_tools_list

        except Exception as e:
            log.error(err)
            raise HTTPException(status_code=500, detail=f"Error occured while creating meta agent\nError: {e}")


