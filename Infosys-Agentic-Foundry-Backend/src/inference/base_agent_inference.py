# © 2024-25 Infosys Limited, Bangalore, India. All Rights Reserved.
import re
import json
import time
import asyncio
from datetime import datetime
from copy import deepcopy
from abc import ABC, abstractmethod
from typing_extensions import TypedDict
from typing import Any, List, Dict, Optional, Annotated, Union, Literal
from fastapi import HTTPException
from langchain_core.tools import BaseTool, StructuredTool, tool
from langgraph.types import Command
from langgraph.errors import GraphRecursionError
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import JsonOutputParser, StrOutputParser
from langgraph.prebuilt import create_react_agent
from langchain_core.messages import AIMessage, HumanMessage, ChatMessage, AnyMessage
from langgraph.graph.message import add_messages
from langgraph.graph import START, END
from langgraph.graph.state import CompiledStateGraph, StateGraph
from langgraph.types import StreamWriter
from src.utils.helper_functions import get_timestamp
from src.inference.inference_utils import InferenceUtils
from src.schemas import AgentInferenceRequest
from src.utils.secrets_handler import get_user_secrets, current_user_email, get_public_key
from src.auth.models import UserRole
from telemetry_wrapper import logger as log, update_session_context
from src.utils.phoenix_manager import ensure_project_registered, traced_project_context, log_trace_context


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
    validation_score: Optional[float] = None
    validation_feedback: Optional[str] = None
    validation_attempts: int = 0
    mentioned_agent_id: str = None
    evaluation_score: float = None
    evaluation_feedback: str = None
    evaluation_attempts: int = 0
    interrupt_items: Optional[List[str]] = None  # List of tool/node names to interrupt at during execution

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
        session_id: str = None
        ):
        try:
            # Determine which stream to use based on conditions
            if not is_plan_approved and not tool_feedback:
                temp = app.astream(invocation_input, config=config, stream_mode="custom")
                async for state in temp:
                    yield state
            elif is_plan_approved == "yes":
                async for state in app.astream(Command(resume="yes"), config=config,stream_mode="custom"):
                    yield state
            elif is_plan_approved == "no" and not plan_feedback:
                async for state in app.astream(Command(resume="no"), config=config,stream_mode="custom"):
                    yield state
            elif is_plan_approved == "no" and plan_feedback is not None:
                async for state in app.astream(Command(resume=plan_feedback), config=config,stream_mode="custom"):
                    yield state
            elif tool_feedback is not None:
                async for state in app.astream(Command(resume=tool_feedback), config=config,stream_mode="custom"):
                    yield state
            else:
                yield {"error": "Invalid parameters provided for astream."}
        
        except GraphRecursionError as e:
            # LangGraph hit recursion limit during streaming; return controlled error
            log.error(f"GraphRecursionError during streaming: {e}")
            yield {
                "error": "Agent hit recursion limit and was stopped.",
                "error_type": "GRAPH_RECURSION_LIMIT",
                "details": str(e),
            }
        
        except Exception as e:
            log.info(f"Error during streaming: {e}")
            yield {"error": "Having error in astream " + str(e)}

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
                                plan_feedback: str = None,
                                response_formatting_flag:bool = True,
                                tool_interrupt_flag: bool = False,
                                tool_feedback: str = None,
                                context_flag: bool = True,
                                temperature: float = 0.0,
                                enable_streaming_flag: bool = False,
                                evaluation_flag: bool = False,
                                validator_flag: bool = False,
                                mentioned_agent_id: str = None,
                                interrupt_items: List[str] = None
                            ):
        if not plan_verifier_flag:
            is_plan_approved = plan_feedback = None

        llm = await self.model_service.get_llm_model(model_name=model_name, temperature=temperature)
        agent_resp = {}

        log.debug("Building agent and chains")
        async with await self.chat_service.get_checkpointer_context_manager() as checkpointer:
            chains = await self._build_agent_and_chains(
                llm, 
                agent_config, 
                checkpointer, 
                tool_interrupt_flag=tool_interrupt_flag
            )
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
                "context_flag": context_flag,
                "evaluation_flag": evaluation_flag,
                "validator_flag": validator_flag
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
            
            # Use the context-aware traced context manager to prevent trace mixing
            log_trace_context(f"before_agent_invocation_session_{session_id}")
            async with traced_project_context(project_name):
                log_trace_context(f"inside_traced_context_session_{session_id}")
                try:
                    invocation_input = {
                        'query': query,
                        'agentic_application_id': agentic_application_id,
                        'session_id': session_id,
                        'reset_conversation': reset_conversation,
                        'model_name': model_name,
                        'is_tool_interrupted': False,
                        'evaluation_flag': evaluation_flag,
                        "response_formatting_flag": response_formatting_flag,
                        "context_flag": context_flag,
                        "mentioned_agent_id": mentioned_agent_id,
                        "interrupt_items": interrupt_items
                    }
                    if enable_streaming_flag:
                        streammer = self._astream(
                            app,
                            invocation_input,
                            config=graph_config,
                            is_plan_approved=is_plan_approved,
                            plan_feedback=plan_feedback,
                            tool_feedback=tool_feedback,
                            session_id=session_id
                        )
                        async for step in streammer:
                            yield step
                        agent_resp = await checkpointer.aget(graph_config)
                        if agent_resp:
                            agent_resp = agent_resp.get("channel_values", {})
                        else:
                            agent_resp = {}
                        if not agent_resp:
                            log.warning(f"unable to retrive response for this Session Id")
                        yield agent_resp


                        log.info(f"Agent invoked successfully for query: {query} with session ID: {session_id}")
                    else:
                        agent_resp = await self._ainvoke(
                            app,
                            invocation_input,
                            config=graph_config,
                            is_plan_approved=is_plan_approved,
                            plan_feedback=plan_feedback,
                            tool_feedback=tool_feedback
                        )

                        log.info(f"Agent invoked successfully for query: {query} with session ID: {session_id}")
                        yield agent_resp

                except GraphRecursionError as e:
                    # LangGraph hit recursion limit; return controlled error
                    log.error(f"GraphRecursionError during inference: {e}")
                    agent_resp = {
                        "error": "Agent hit recursion limit and was stopped.",
                        "error_type": "GRAPH_RECURSION_LIMIT",
                        "details": str(e),
                    }
                    yield agent_resp

                except Exception as e:
                    await checkpointer.setup()
                    response = await checkpointer.aget(graph_config)

                    if response.get("channel_values", {}).get("executor_messages", None):
                        error_trace = response["channel_values"]["executor_messages"][-1]
                        agent_resp = {"error": f"Error Occurred while inferencing: {e}\nError Trace:\n{error_trace}"}
                    else:
                        agent_resp = {"error": f"Error Occurred while inferencing: {e}"}
                    
                    log.error(agent_resp.get("error", "Unknown error occurred during agent inference."))
                    yield agent_resp
                
                finally:
                    log_trace_context(f"after_agent_invocation_session_{session_id}")


    async def run(self,
                  inference_request: AgentInferenceRequest,
                  *,
                  agent_config: Optional[Union[dict, None]] = None,
                  insert_into_eval_flag: bool = True,
                  role: str = None
                ) -> Any:
        """
        Runs the Agent inference workflow.

        Args:
            request (AgentInferenceRequest): The request object containing all necessary parameters.
        """
        start_time = time.monotonic()
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
            evaluation_flag = inference_request.evaluation_flag
            validator_flag = inference_request.validator_flag
            temperature=inference_request.temperature
            enable_streaming_flag = inference_request.enable_streaming_flag
            mentioned_agent_id = inference_request.mentioned_agentic_application_id
            interrupt_items = inference_request.interrupt_items

            match = re.search(r'([a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+)', session_id)
            user_name = match.group(0) if match else "guest"
            agent_name = agent_config["AGENT_NAME"]
            project_name=agent_name+'_'+user_name

            # Register Phoenix project (only once per unique project name)
            ensure_project_registered(
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
                    yield {"response": "Knowledge Base Retriever tool not found. Please ensure it is registered in the system."}
                    return 

                agent_config['TOOLS_INFO'].append(knowledgebase_retriever_id)
                agent_config['SYSTEM_PROMPT']['SYSTEM_PROMPT_REACT_AGENT'] += f" ;Use Knowledge Base: {inference_request.knowledgebase_name} regarding the query and if any useful information found use it and pass it to any tools if no useful content is extracted call use the agent as if the knowledgebase tool is not existing, but use the instructions for each of tools and execute the query."


            # Generate response using the React agent workflow
            async for response in self._generate_response(
                query=query,
                agentic_application_id=agentic_application_id,
                session_id=session_id,
                model_name=model_name,
                agent_config=agent_config,
                project_name=project_name,
                reset_conversation=reset_conversation,
                plan_verifier_flag=plan_verifier_flag,
                is_plan_approved=is_plan_approved,
                plan_feedback=plan_feedback,
                response_formatting_flag=response_formatting_flag,
                context_flag=context_flag,
                evaluation_flag=evaluation_flag,
                validator_flag=validator_flag,
                tool_interrupt_flag=tool_interrupt_flag,
                tool_feedback=tool_feedback,
                temperature=temperature,
                enable_streaming_flag=enable_streaming_flag,
                mentioned_agent_id=mentioned_agent_id,
                interrupt_items=interrupt_items
            ):
                if "executor_messages" not in response:
                    yield response
            if isinstance(response, str):
                update_session_context(response=response)
                response = {"error": response}
            elif "error" in response:
                update_session_context(response=response["error"])
            else:
                update_session_context(response=response['response'])
                response_evaluation = deepcopy(response)
                
                
                response_evaluation["executor_messages"] = await self.chat_service.segregate_conversation_from_raw_chat_history_with_json_like_steps(response)

                # call segregate to ensure proper formatting
                
                response["executor_messages"] = await self.chat_service.segregate_conversation_from_raw_chat_history_with_pretty_steps(
                    response, 
                    agentic_application_id=agentic_application_id,
                    session_id=session_id,
                    role=role
                )

            if insert_into_eval_flag:
                try:
                    time_start = time.monotonic()
                    asyncio.create_task(self.evaluation_service.log_evaluation_data(session_id, agentic_application_id, agent_config, response_evaluation, model_name))
                    time_end = time.monotonic()
                    log.info(f"Time taken to log evaluation data asynchronously: {time_end - time_start:.2f} seconds")
                except Exception as e:
                    log.error(f"Error Occurred while inserting into evaluation data: {e}")
            end_time = time.monotonic()
            time_taken = end_time - start_time
            log.info(f"Time taken for inference: {time_taken:.2f} seconds")
            response["executor_messages"][-1]["response_time"] = time_taken
            
            # Filter entire response based on user role
            if role == UserRole.USER:
                # For USER role, return only executor_messages with filtered fields
                yield {"executor_messages": response.get("executor_messages", [])}
                return

            yield response

        except Exception as e:
            # Catch any unhandled exceptions and raise a 500 internal server error
            log.error(f"Error Occurred in agent inference: {e}")
            raise HTTPException(status_code=500, detail=f"Internal Server Error: {str(e)}")

    async def update_response_time(self, agent_id: str, session_id: str, start_time: float, time_stamp: Any):
        """Updates the response time in the last executor message for the given session."""
        try:
            async with await self.chat_service.get_checkpointer_context_manager() as checkpointer:
                thread_id = await self.chat_service._get_thread_id(agent_id, session_id)
                graph_config = await self.chat_service._get_thread_config(thread_id)
                workflow = StateGraph(BaseWorkflowState)
                workflow.add_edge(START, END)
                app = workflow.compile(checkpointer=checkpointer)
                current_time = time.monotonic()
                response_time = current_time - start_time
                await app.aupdate_state(config=graph_config, values={"executor_messages":ChatMessage(content=[
                    {
                        "response_time":response_time,
                        "start_timestamp": time_stamp.isoformat()
                    }
                    ], role="response_time")})
                log.info(f"Updated response time for session {session_id} of agent {agent_id}: {response_time} seconds")
                return response_time
        except Exception as e:
            log.error(f"Error occurred while updating response time: {e}")
        

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
                                                                 interrupt_tool: bool = False,
                                                                 writer_holder: dict = None
                                                                 ) -> Any:
        """
        Creates a planner-executor-critic agent as a meta agent worker with tools loaded dynamically.
        Supports streaming via writer_holder for real-time status updates.
        
        Args:
            llm: The language model to use
            system_prompts: Dictionary of system prompts for each agent role
            checkpointer: Optional checkpointer for state persistence
            tool_ids: List of tool IDs to load
            interrupt_tool: Whether to enable tool interruption
            writer_holder: A mutable dict that will hold the StreamWriter reference,
                          set by the parent graph node before execution.
                          Example: {"writer": <StreamWriter instance>}
        """
        
        # Initialize writer_holder if not provided (for standalone usage)
        if writer_holder is None:
            writer_holder = {"writer": None}
        
        # Helper function for safe streaming writes
        def safe_write(data):
            """Safely write to StreamWriter if available."""
            if writer_holder:
                writer = writer_holder.get("writer")
                if writer:
                    try:
                        writer(data)
                    except Exception as e:
                        log.warning(f"Failed to write to stream: {e}")
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
            safe_write({"Node Name": "Planner Agent", "Status": "Started"})
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
            safe_write({"raw": {"plan": planner_response['plan']}, "content": f"Generated execution plan with {len(planner_response['plan'])} steps"})
            log.info(f"Planner Agent generated plan: {planner_response['plan']}")
            safe_write({"Node Name": "Planner Agent", "Status": "Completed"})
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
            safe_write({"Node Name": "Executor Agent", "Status": "Started"})
            step = state["plan"][state["step_idx"]]
            completed_steps = []
            completed_steps_responses = []
            task_formatted = state["query"] + "\n\n"
            if state["step_idx"]!=0:
                completed_steps = state["past_steps_input"][:state["step_idx"]]
                completed_steps_responses = state["past_steps_output"][:state["step_idx"]]
                task_formatted += f"Past Steps:\n{await self.inference_utils.format_past_steps_list(completed_steps, completed_steps_responses)}"
            task_formatted += f"\n\nCurrent Step:\n{step}"
            
            safe_write({"raw": {"Current Step": step}, "content": f"Executing step {state['step_idx']+1}/{len(state['plan'])}: {step}"})
            
            # Stream execution for real-time updates
            final_content_parts = []
            async for msg in executor_agent.astream({"messages": [("user", task_formatted.strip())]}):
                if isinstance(msg, dict) and "agent" in msg:
                    agent_output = msg.get("agent", {})
                    messages = []
                    if isinstance(agent_output, dict) and "messages" in agent_output:
                        messages = agent_output.get("messages", [])
                
                    for message in messages:
                        # Handle tool calls
                        if hasattr(message, 'tool_calls') and message.tool_calls:
                            tool_call = message.tool_calls[0]
                            safe_write({"Node Name": "Tool Call", "Status": "Started", "Tool Name": tool_call['name'], "Tool Arguments": tool_call['args']})
                            tool_name = tool_call["name"]
                            tool_args = tool_call["args"]

                            if tool_args:   # Non-empty dict means arguments exist
                                if isinstance(tool_args, dict):
                                    args_str = ", ".join(f"{k}={v}" for k, v in tool_args.items())
                                else:
                                    args_str = str(tool_args)
                                tool_call_content = f"Agent called the tool '{tool_name}', passing arguments: {args_str}."
                            else:
                                tool_call_content = f"Agent called the tool '{tool_name}', passing no arguments."

                            safe_write({"content": tool_call_content})
                        
                    final_content_parts.extend(messages)
                    
                elif "tools" in msg:
                    tool_messages = msg.get("tools", {})
                    messages_list = tool_messages.get("messages", [])
                    
                    for tool_message in messages_list:
                        safe_write({"raw": {"Tool Name": tool_message.name, "Tool Output": tool_message.content}, "content": f"Tool {tool_message.name} returned: {tool_message.content}"})
                        if hasattr(tool_message, "name"):
                            safe_write({"Node Name": "Tool Call", "Status": "Completed", "Tool Name": tool_message.name})
                    final_content_parts.extend(messages_list)
                else:
                    # Handle other message types
                    if "agent" in msg:
                        final_content_parts.extend(msg["agent"]["messages"])
            
            # Extract final response from last message
            if final_content_parts:
                last_msg = final_content_parts[-1]
                if hasattr(last_msg, 'content'):
                    final_response = last_msg.content
                else:
                    final_response = str(last_msg)
            else:
                final_response = ""
            
            completed_steps.append(step)
            completed_steps_responses.append(final_response)
            log.info(f"Executor Agent executed step {state['step_idx']+1}/{len(state['plan'])}: {step}")
            safe_write({"Node Name": "Executor Agent", "Status": "Completed"})
            return {
                "response": final_response,
                "past_steps_input": completed_steps,
                "past_steps_output": completed_steps_responses,
                "messages": final_content_parts if final_content_parts else [ChatMessage(content=final_response, role="executor")]
            }

        def increment_step(state: PlanExecuteCritic):
            safe_write({"content": f"Incrementing step index from {state['step_idx']} to {state['step_idx']+1}"})
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
            safe_write({"Node Name": "Response Generator", "Status": "Started"})
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
                    safe_write({"response": response_gen_response["response"]})
                    log.info(f"Response Generator Agent generated response: {response_gen_response['response']}")
                    safe_write({"Node Name": "Response Generator", "Status": "Completed"})
                    return {"response": response_gen_response["response"]}
            else:
                log.error(f"Response generation failed")
                safe_write({"Node Name": "Response Generator", "Status": "Failed"})
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
            safe_write({"Node Name": "Critic Agent", "Status": "Started"})
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
            safe_write({"raw": {"response_quality_score": critic_response["response_quality_score"], "critique_points": critic_response["critique_points"]}, "content": f"Response quality score: {critic_response['response_quality_score']}"})
            log.info(f"Critic Agent evaluated response with quality score: {critic_response['response_quality_score']}")
            safe_write({"Node Name": "Critic Agent", "Status": "Completed"})
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
            safe_write({"Node Name": "Critic-Based Planner", "Status": "Started"})
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
{state.get("response_quality_score", "Not yet evaluated")}

Critique Points:
{await self.inference_utils.format_list_str(state["critique_points"]) if state.get("critique_points") else "No critique points available yet."}
'''

            invocation_input = {"messages": [("user", formatted_query)]}
            critic_planner_response = await self.inference_utils.output_parser(
                                                                    llm=llm,
                                                                    chain_1=critic_planner_chain_json,
                                                                    chain_2=critic_planner_chain_str,
                                                                    invocation_input=invocation_input,
                                                                    error_return_key="plan"
                                                                )
            safe_write({"raw": {"revised_plan": critic_planner_response['plan']}, "content": f"Generated revised plan with {len(critic_planner_response['plan'])} steps based on critique"})
            log.info(f"Critic-Based Planner Agent generated plan: {critic_planner_response['plan']}")
            safe_write({"Node Name": "Critic-Based Planner", "Status": "Completed"})
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
            safe_write({"Node Name": "Final Response", "Status": "Started"})
            end_timestamp = get_timestamp()
            response = state['response']
            response = response if response else "No plans to execute"

            final_response_message = AIMessage(content=response)
            safe_write({"raw": {"final_response": response}, "content": f"Final response generated successfully"})
            log.info(f"Final response generated: {final_response_message.content}")
            safe_write({"Node Name": "Final Response", "Status": "Completed"})
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
            decision = "final_response" if state["response_quality_score"]>=0.7 or state["epoch"]==3 else "critic_based_planner_agent"
            safe_write({"content": f"Critic decision: {decision} (score: {state['response_quality_score']}, epoch: {state['epoch']})"})
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
            safe_write({"content": f"Plan execution status: Step {state['step_idx']}/{len(state['plan'])}"})
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
                safe_write({"content": "No actionable plan generated, routing to final response"})
                return "final_response"
            else:
                safe_write({"content": f"Plan has {len(state['plan'])} steps, routing to executor"})
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
        log.info(f"Planner-Executor-Critic Agent created as Meta Agent Worker with streaming support.")
        return app, tool_list, writer_holder

    async def _get_planner_executor_agent_as_worker_agent(self,
                                                          llm: Any,
                                                          system_prompts: str,
                                                          checkpointer: Any = None,
                                                          tool_ids: List[str] = [],
                                                          interrupt_tool: bool = False,
                                                          writer_holder: dict = None
                                                          ) -> Any:
        """
        Creates a planner-executor agent (without critic) as a meta agent worker with tools loaded dynamically.
        Supports streaming via writer_holder for real-time status updates.
        
        Args:
            llm: The language model to use
            system_prompts: Dictionary of system prompts for each agent role
            checkpointer: Optional checkpointer for state persistence
            tool_ids: List of tool IDs to load
            interrupt_tool: Whether to enable tool interruption
            writer_holder: A mutable dict that will hold the StreamWriter reference
        """
        
        # Initialize writer_holder if not provided
        if writer_holder is None:
            writer_holder = {"writer": None}
        
        # Helper function for safe streaming writes
        def safe_write(data):
            """Safely write to StreamWriter if available."""
            if writer_holder:
                writer = writer_holder.get("writer")
                if writer:
                    try:
                        writer(data)
                    except Exception as e:
                        log.warning(f"Failed to write to stream: {e}")

        # System Prompts
        planner_system_prompt = system_prompts.get("SYSTEM_PROMPT_PLANNER_AGENT", "").replace("{", "{{").replace("}", "}}")
        executor_system_prompt = system_prompts.get("SYSTEM_PROMPT_EXECUTOR_AGENT", "")
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
        response_gen_chain_json, response_gen_chain_str = await self._get_chains(llm, response_generator_system_prompt)

        if not llm or not executor_agent or not planner_chain_json or not planner_chain_str or \
                not response_gen_chain_json or not response_gen_chain_str:
            raise HTTPException(status_code=500, detail="Required chains or agent executor are missing")

        # State Schema
        class PlanExecute(TypedDict):
            query: str
            messages: Annotated[List[AnyMessage], add_messages]
            plan: List[str]
            past_steps_input: List[str]
            past_steps_output: List[str]
            response: str
            step_idx: int
            start_timestamp: datetime
            end_timestamp: datetime

        # Nodes
        async def planner_agent(state: PlanExecute):
            """Generates a plan for the agent to follow."""
            safe_write({"Node Name": "Planner Agent", "Status": "Started"})
            strt_tmstp = get_timestamp()
            state["query"] = state["messages"][0].content
            
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
            safe_write({"raw": {"plan": planner_response['plan']}, "content": f"Generated execution plan with {len(planner_response['plan'])} steps"})
            log.info(f"Planner Agent generated plan: {planner_response['plan']}")
            safe_write({"Node Name": "Planner Agent", "Status": "Completed"})
            return {
                "query": state["query"],
                "messages": ChatMessage(content=planner_response['plan'], role="plan"),
                "plan": planner_response['plan'],
                'response': None,
                'past_steps_input': None,
                'past_steps_output': None,
                'step_idx': 0,
                'start_timestamp': strt_tmstp
            }

        async def executor_agent_node(state: PlanExecute):
            """Executes the current step in the plan."""
            safe_write({"Node Name": "Executor Agent", "Status": "Started"})
            step = state["plan"][state["step_idx"]]
            completed_steps = []
            completed_steps_responses = []
            task_formatted = state["query"] + "\n\n"
            
            if state["step_idx"] != 0:
                completed_steps = state["past_steps_input"][:state["step_idx"]]
                completed_steps_responses = state["past_steps_output"][:state["step_idx"]]
                task_formatted += f"Past Steps:\n{await self.inference_utils.format_past_steps_list(completed_steps, completed_steps_responses)}"
            task_formatted += f"\n\nCurrent Step:\n{step}"
            
            safe_write({"raw": {"Current Step": step}, "content": f"Executing step {state['step_idx']+1}/{len(state['plan'])}: {step}"})
            
            final_content_parts = []
            async for msg in executor_agent.astream({"messages": [("user", task_formatted.strip())]}):
                if isinstance(msg, dict) and "agent" in msg:
                    agent_output = msg.get("agent", {})
                    messages = []
                    if isinstance(agent_output, dict) and "messages" in agent_output:
                        messages = agent_output.get("messages", [])
                
                    for message in messages:
                        if hasattr(message, 'tool_calls') and message.tool_calls:
                            tool_call = message.tool_calls[0]
                            safe_write({"Node Name": "Tool Call", "Status": "Started", "Tool Name": tool_call['name'], "Tool Arguments": tool_call['args']})
                            tool_name = tool_call["name"]
                            tool_args = tool_call["args"]
                            if tool_args:
                                if isinstance(tool_args, dict):
                                    args_str = ", ".join(f"{k}={v}" for k, v in tool_args.items())
                                else:
                                    args_str = str(tool_args)
                                tool_call_content = f"Agent called the tool '{tool_name}', passing arguments: {args_str}."
                            else:
                                tool_call_content = f"Agent called the tool '{tool_name}', passing no arguments."
                            safe_write({"content": tool_call_content})
                        
                    final_content_parts.extend(messages)
                    
                elif "tools" in msg:
                    tool_messages = msg.get("tools", {})
                    messages_list = tool_messages.get("messages", [])
                    for tool_message in messages_list:
                        safe_write({"raw": {"Tool Name": tool_message.name, "Tool Output": tool_message.content}, "content": f"Tool {tool_message.name} returned: {tool_message.content}"})
                        if hasattr(tool_message, "name"):
                            safe_write({"Node Name": "Tool Call", "Status": "Completed", "Tool Name": tool_message.name})
                    final_content_parts.extend(messages_list)
                else:
                    if "agent" in msg:
                        final_content_parts.extend(msg["agent"]["messages"])
            
            if final_content_parts:
                last_msg = final_content_parts[-1]
                final_response = last_msg.content if hasattr(last_msg, 'content') else str(last_msg)
            else:
                final_response = ""
            
            completed_steps.append(step)
            completed_steps_responses.append(final_response)
            log.info(f"Executor Agent executed step {state['step_idx']+1}/{len(state['plan'])}: {step}")
            safe_write({"Node Name": "Executor Agent", "Status": "Completed"})
            return {
                "response": final_response,
                "past_steps_input": completed_steps,
                "past_steps_output": completed_steps_responses,
                "messages": final_content_parts if final_content_parts else [ChatMessage(content=final_response, role="executor")]
            }

        def increment_step(state: PlanExecute):
            safe_write({"content": f"Incrementing step index from {state['step_idx']} to {state['step_idx']+1}"})
            log.info(f"Incrementing step index from {state['step_idx']} to {state['step_idx']+1}")
            return {"step_idx": state["step_idx"]+1}

        async def response_generator_agent(state: PlanExecute):
            """Generates final response from completed steps."""
            safe_write({"Node Name": "Response Generator", "Status": "Started"})
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
                safe_write({"response": response_gen_response["response"]})
                log.info(f"Response Generator Agent generated response")
                safe_write({"Node Name": "Response Generator", "Status": "Completed"})
                return {"response": response_gen_response["response"]}
            else:
                log.error(f"Response generation failed")
                safe_write({"Node Name": "Response Generator", "Status": "Failed"})
                result = await llm.ainvoke(f"Format the response in Markdown Format.\n\nResponse: {response_gen_response}")
                return {"response": result.content}

        def final_response(state: PlanExecute):
            """Handles the final response."""
            safe_write({"Node Name": "Final Response", "Status": "Started"})
            end_timestamp = get_timestamp()
            response = state['response'] if state['response'] else "No plans to execute"
            final_response_message = AIMessage(content=response)
            safe_write({"raw": {"final_response": response}, "content": f"Final response generated successfully"})
            log.info(f"Final response generated")
            safe_write({"Node Name": "Final Response", "Status": "Completed"})
            return {"messages": final_response_message, "end_timestamp": end_timestamp}

        def check_plan_execution_status(state: PlanExecute):
            """Checks if all steps are executed."""
            safe_write({"content": f"Plan execution status: Step {state['step_idx']}/{len(state['plan'])}"})
            if state["step_idx"] == len(state["plan"]):
                return "response_generator_agent"
            else:
                return "executor_agent_node"

        def route_non_planner_question(state: PlanExecute):
            """Routes based on plan availability."""
            if not state["plan"] or "STEP" not in state["plan"][0]:
                safe_write({"content": "No actionable plan generated, routing to final response"})
                return "final_response"
            else:
                safe_write({"content": f"Plan has {len(state['plan'])} steps, routing to executor"})
                return "executor_agent_node"

        # Build Graph
        workflow = StateGraph(PlanExecute)
        workflow.add_node("planner_agent", planner_agent)
        workflow.add_node("executor_agent_node", executor_agent_node)
        workflow.add_node("increment_step", increment_step)
        workflow.add_node("response_generator_agent", response_generator_agent)
        workflow.add_node("final_response", final_response)

        workflow.add_edge(START, "planner_agent")
        workflow.add_conditional_edges("planner_agent", route_non_planner_question, ["final_response", "executor_agent_node"])
        workflow.add_edge("executor_agent_node", "increment_step")
        workflow.add_conditional_edges("increment_step", check_plan_execution_status, ["executor_agent_node", "response_generator_agent"])
        workflow.add_edge("response_generator_agent", "final_response")
        workflow.add_edge("final_response", END)

        app = workflow.compile()
        log.info(f"Planner-Executor Agent created as Meta Agent Worker with streaming support.")
        return app, tool_list, writer_holder

    async def _get_react_critic_agent_as_worker_agent(self,
                                                      llm: Any,
                                                      system_prompts: str,
                                                      checkpointer: Any = None,
                                                      tool_ids: List[str] = [],
                                                      interrupt_tool: bool = False,
                                                      writer_holder: dict = None
                                                      ) -> Any:
        """
        Creates a react-critic agent as a meta agent worker with tools loaded dynamically.
        Supports streaming via writer_holder for real-time status updates.
        
        Args:
            llm: The language model to use
            system_prompts: Dictionary of system prompts for each agent role
            checkpointer: Optional checkpointer for state persistence
            tool_ids: List of tool IDs to load
            interrupt_tool: Whether to enable tool interruption
            writer_holder: A mutable dict that will hold the StreamWriter reference
        """
        
        # Initialize writer_holder if not provided
        if writer_holder is None:
            writer_holder = {"writer": None}
        
        # Helper function for safe streaming writes
        def safe_write(data):
            """Safely write to StreamWriter if available."""
            if writer_holder:
                writer = writer_holder.get("writer")
                if writer:
                    try:
                        writer(data)
                    except Exception as e:
                        log.warning(f"Failed to write to stream: {e}")

        # System Prompts
        executor_system_prompt = system_prompts.get("SYSTEM_PROMPT_EXECUTOR_AGENT", "")
        critic_system_prompt = system_prompts.get("SYSTEM_PROMPT_CRITIC_AGENT", "").replace("{", "{{").replace("}", "}}")

        # Agents and Chains
        executor_agent, tool_list = await self._get_react_agent_as_executor_agent(
                                        llm,
                                        system_prompt=executor_system_prompt,
                                        checkpointer=checkpointer,
                                        tool_ids=tool_ids,
                                        interrupt_tool=interrupt_tool
                                    )
        critic_chain_json, critic_chain_str = await self._get_chains(llm, critic_system_prompt)

        if not llm or not executor_agent or not critic_chain_json or not critic_chain_str:
            raise HTTPException(status_code=500, detail="Required chains or agent executor are missing")

        # State Schema
        class ReactCritic(TypedDict):
            query: str
            messages: Annotated[List[AnyMessage], add_messages]
            response: str
            response_quality_score: float
            critique_points: str
            epoch: int
            start_timestamp: datetime
            end_timestamp: datetime

        # Nodes
        async def executor_agent_node(state: ReactCritic):
            """Executes query using the react agent."""
            safe_write({"Node Name": "Executor Agent", "Status": "Started"})
            strt_tmstp = get_timestamp()
            query = state["messages"][0].content
            
            # Add critic feedback if available
            critic_context = ""
            if state.get("response_quality_score") is not None:
                critic_context = f"""
Previous Response:
{state["response"]}

Critic Score: {state["response_quality_score"]}
Critique Points: {await self.inference_utils.format_list_str(state["critique_points"]) if state.get("critique_points") else "No critique points"}

Please improve your response based on the feedback above.
"""
            
            formatted_query = f"{query}{critic_context}"
            safe_write({"content": f"Executing query: {query[:100]}..."})
            
            final_content_parts = []
            async for msg in executor_agent.astream({"messages": [("user", formatted_query.strip())]}):
                if isinstance(msg, dict) and "agent" in msg:
                    agent_output = msg.get("agent", {})
                    messages = []
                    if isinstance(agent_output, dict) and "messages" in agent_output:
                        messages = agent_output.get("messages", [])
                
                    for message in messages:
                        if hasattr(message, 'tool_calls') and message.tool_calls:
                            tool_call = message.tool_calls[0]
                            safe_write({"Node Name": "Tool Call", "Status": "Started", "Tool Name": tool_call['name'], "Tool Arguments": tool_call['args']})
                            tool_name = tool_call["name"]
                            tool_args = tool_call["args"]
                            if tool_args:
                                if isinstance(tool_args, dict):
                                    args_str = ", ".join(f"{k}={v}" for k, v in tool_args.items())
                                else:
                                    args_str = str(tool_args)
                                tool_call_content = f"Agent called the tool '{tool_name}', passing arguments: {args_str}."
                            else:
                                tool_call_content = f"Agent called the tool '{tool_name}', passing no arguments."
                            safe_write({"content": tool_call_content})
                        
                    final_content_parts.extend(messages)
                    
                elif "tools" in msg:
                    tool_messages = msg.get("tools", {})
                    messages_list = tool_messages.get("messages", [])
                    for tool_message in messages_list:
                        safe_write({"raw": {"Tool Name": tool_message.name, "Tool Output": tool_message.content}, "content": f"Tool {tool_message.name} returned: {tool_message.content}"})
                        if hasattr(tool_message, "name"):
                            safe_write({"Node Name": "Tool Call", "Status": "Completed", "Tool Name": tool_message.name})
                    final_content_parts.extend(messages_list)
                else:
                    if "agent" in msg:
                        final_content_parts.extend(msg["agent"]["messages"])
            
            if final_content_parts:
                last_msg = final_content_parts[-1]
                final_response = last_msg.content if hasattr(last_msg, 'content') else str(last_msg)
            else:
                final_response = ""
            
            log.info(f"Executor Agent generated response")
            safe_write({"Node Name": "Executor Agent", "Status": "Completed"})
            
            return_state = {
                "query": query,
                "response": final_response,
                "messages": final_content_parts if final_content_parts else [ChatMessage(content=final_response, role="executor")],
                "start_timestamp": strt_tmstp
            }
            
            # Initialize epoch if first run
            if state.get("epoch") is None:
                return_state["epoch"] = 0
                
            return return_state

        async def critic_agent(state: ReactCritic):
            """Evaluates the response quality."""
            safe_write({"Node Name": "Critic Agent", "Status": "Started"})
            formatted_query = f'''\
Tools Info:
{await self.tool_service.render_text_description_for_tools(tool_list)}

User Query:
{state["query"]}

Response:
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

            if critic_response.get("critique_points") and isinstance(critic_response["critique_points"], list) and len(critic_response["critique_points"]) > 0 and "error" in str(critic_response["critique_points"][0]):
                critic_response = {'response_quality_score': 0, 'critique_points': critic_response["critique_points"]}
            
            safe_write({"raw": {"response_quality_score": critic_response["response_quality_score"], "critique_points": critic_response["critique_points"]}, "content": f"Response quality score: {critic_response['response_quality_score']}"})
            log.info(f"Critic Agent evaluated response with quality score: {critic_response['response_quality_score']}")
            safe_write({"Node Name": "Critic Agent", "Status": "Completed"})
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
                "epoch": state["epoch"] + 1
            }

        def final_response(state: ReactCritic):
            """Handles the final response."""
            safe_write({"Node Name": "Final Response", "Status": "Started"})
            end_timestamp = get_timestamp()
            response = state['response'] if state['response'] else "Unable to generate response"
            final_response_message = AIMessage(content=response)
            safe_write({"raw": {"final_response": response}, "content": f"Final response generated successfully"})
            log.info(f"Final response generated")
            safe_write({"Node Name": "Final Response", "Status": "Completed"})
            return {"messages": final_response_message, "end_timestamp": end_timestamp}

        def critic_decision(state: ReactCritic):
            """Decides whether to finalize or retry."""
            decision = "final_response" if state["response_quality_score"] >= 0.7 or state["epoch"] >= 3 else "executor_agent_node"
            safe_write({"content": f"Critic decision: {decision} (score: {state['response_quality_score']}, epoch: {state['epoch']})"})
            if state["response_quality_score"] >= 0.7 or state["epoch"] >= 3:
                return "final_response"
            else:
                return "executor_agent_node"

        # Build Graph
        workflow = StateGraph(ReactCritic)
        workflow.add_node("executor_agent_node", executor_agent_node)
        workflow.add_node("critic_agent", critic_agent)
        workflow.add_node("final_response", final_response)

        workflow.add_edge(START, "executor_agent_node")
        workflow.add_edge("executor_agent_node", "critic_agent")
        workflow.add_conditional_edges("critic_agent", critic_decision, ["final_response", "executor_agent_node"])
        workflow.add_edge("final_response", END)

        app = workflow.compile()
        log.info(f"React-Critic Agent created as Meta Agent Worker with streaming support.")
        return app, tool_list, writer_holder

    # === Custom task-based handoff tool factory ===
    @staticmethod
    async def _create_agent_as_tool(*, agent_name: str, description: str = None, worker_agent: Any = None, writer_holder: dict = None) -> Any:
        """
        Creates a tool that delegates tasks to a specified agent.
        This tool can be used to hand off tasks to the specified agent based on the task description.
        
        Args:
            agent_name: Name of the worker agent
            description: Description for the tool
            worker_agent: The compiled worker agent graph
            writer_holder: A mutable dict that will hold the StreamWriter reference, 
                          set by the parent graph node before tool execution.
                          Example: {"writer": <StreamWriter instance>}
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
            log.info(f"Handoff tool '{agent_name}' invoked with task")
            
            # Get writer from the shared holder (set by parent node)
            writer = writer_holder.get("writer") if writer_holder else None
            
            def safe_write(data):
                """Safely write to StreamWriter if available."""
                if writer:
                    try:
                        writer(data)
                    except Exception as e:
                        log.warning(f"Failed to write to stream: {e}")
            
            try:
                final_content_parts = []
                final_response = None
                
                safe_write({"Node Name": f"Worker Agent: {agent_name} Thinking..", "Status": "Started"})
                
                async for msg in worker_agent.astream({"messages": [HumanMessage(content=task)]}):
                    log.debug(f"Worker agent '{agent_name}' streamed message keys: {msg.keys() if isinstance(msg, dict) else type(msg)}")
                    
                    # Handle react agent format (keys: "agent", "tools")
                    if isinstance(msg, dict) and "agent" in msg:
                        agent_output = msg.get("agent", {})
                        messages = []
                        if isinstance(agent_output, dict) and "messages" in agent_output:
                            messages = agent_output.get("messages", [])
                    
                        for message in messages:
                            safe_write({"raw": {"executor_agent": message.tool_calls}, "content": f"Agent is calling tools"})
                            # Handle tool calls
                            if hasattr(message, 'tool_calls') and message.tool_calls:
                                tool_call = message.tool_calls[0]
                                safe_write({"Node Name": "Tool Call", "Status": "Started", "Tool Name": tool_call['name'], "Tool Arguments": tool_call['args']})
                                tool_name = tool_call["name"]
                                tool_args = tool_call["args"]

                                if tool_args:   # Non-empty dict means arguments exist
                                    if isinstance(tool_args, dict):
                                        args_str = ", ".join(f"{k}={v}" for k, v in tool_args.items())
                                    else:
                                        args_str = str(tool_args)
                                    tool_call_content = f"Agent called the tool '{tool_name}', passing arguments: {args_str}."
                                else:
                                    tool_call_content = f"Agent called the tool '{tool_name}', passing no arguments."

                                safe_write({"content": tool_call_content})
                            
                            # Track the last message content for final response
                            if hasattr(message, 'content') and message.content:
                                final_response = message.content
                            
                        final_content_parts.extend(messages)
                        
                    elif isinstance(msg, dict) and "tools" in msg:
                        tool_messages = msg.get("tools", {})
                        messages_list = tool_messages.get("messages", [])
                        
                        for tool_message in messages_list:
                            safe_write({"raw": {"Tool Name": tool_message.name, "Tool Output": tool_message.content}, "content": f"Tool {tool_message.name} returned: {tool_message.content}"})
                            if hasattr(tool_message, "name"):
                                safe_write({"Node Name": "Tool Call", "Status": "Completed", "Tool Name": tool_message.name})
                        final_content_parts.extend(messages_list)
                    
                    # Handle custom workflow format (planner-executor-critic, planner-executor, react-critic)
                    # These emit messages with node names as keys: "planner_agent", "executor_agent_node", "final_response", etc.
                    elif isinstance(msg, dict) and "final_response" in msg:
                        # Extract final response from the final_response node
                        log.debug(f"Worker agent '{agent_name}' received final_response node output")
                        final_response_output = msg.get("final_response", {})
                        if isinstance(final_response_output, dict) and "messages" in final_response_output:
                            messages = final_response_output.get("messages")
                            log.debug(f"final_response messages type: {type(messages)}, value: {messages}")
                            if messages:
                                # Handle both single message and list of messages
                                last_msg = messages[-1] if isinstance(messages, list) else messages
                                if hasattr(last_msg, 'content') and last_msg.content:
                                    final_response = last_msg.content
                                    log.debug(f"Extracted final_response content: {final_response[:100] if final_response else 'None'}...")
                                elif isinstance(last_msg, str):
                                    final_response = last_msg
                                final_content_parts.extend(messages if isinstance(messages, list) else [messages])
                    
                    elif isinstance(msg, dict):
                        # Handle other node outputs from custom workflows
                        # Look for any node that has a "messages" key with content or "response" key
                        for node_name, node_output in msg.items():
                            if isinstance(node_output, dict) and "messages" in node_output:
                                messages = node_output.get("messages", [])
                                if messages:
                                    if isinstance(messages, list):
                                        for message in messages:
                                            if hasattr(message, 'content') and message.content:
                                                final_response = message.content
                                        final_content_parts.extend(messages)
                                    else:
                                        if hasattr(messages, 'content') and messages.content:
                                            final_response = messages.content
                                        final_content_parts.append(messages)
                            
                            # Also check for "response" key directly in node output
                            if isinstance(node_output, dict) and "response" in node_output:
                                response_val = node_output.get("response")
                                if response_val and isinstance(response_val, str):
                                    final_response = response_val
                                    log.debug(f"Found response in node '{node_name}': {response_val[:100] if response_val else 'None'}...")
                            
                safe_write({"Node Name": f"Worker Agent: {agent_name} Thinking..", "Status": "Completed"})
                
                log.debug(f"Worker agent '{agent_name}' final_response: {final_response[:100] if final_response else 'None'}, final_content_parts count: {len(final_content_parts)}")
                
                # Return the final response from streaming
                if final_response:
                    return final_response
                elif final_content_parts:
                    # Get content from last message if available
                    last_msg = final_content_parts[-1]
                    if hasattr(last_msg, 'content'):
                        return last_msg.content
                    return str(last_msg)
                else:
                    return f"Worker agent '{agent_name}' completed but returned no response."

            except Exception as e:
                log.error(f"Error during streaming execution of worker agent '{agent_name}': {e}")
                safe_write({"error": f"Error during execution of agent '{agent_name}': {e}"})
                return f"Error during execution of agent '{agent_name}': {e}"
        
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
        Helper method to create a React agent as a supervisor or meta agent with agents loaded dynamically.
        
        Returns:
            tuple: (supervisor_agent, worker_agents_as_tools_list, writer_holder)
                   The writer_holder dict should have its "writer" key set by the parent 
                   graph node before tool execution to enable streaming.
        """
        worker_agents_as_tools_list = []
        # Shared holder for StreamWriter - will be set by the meta agent node
        writer_holder = {"writer": None}
        
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
                worker_agent, _, _ = await self._get_planner_executor_critic_agent_as_worker_agent(
                    llm=llm,
                    system_prompts=worker_agent_system_prompt,
                    tool_ids=worker_agent_tool_ids,
                    writer_holder=writer_holder  # Pass the shared writer_holder for streaming
                )
            elif worker_agent_type == "planner_executor_agent":
                worker_agent, _, _ = await self._get_planner_executor_agent_as_worker_agent(
                    llm=llm,
                    system_prompts=worker_agent_system_prompt,
                    tool_ids=worker_agent_tool_ids,
                    writer_holder=writer_holder  # Pass the shared writer_holder for streaming
                )
            elif worker_agent_type == "react_critic_agent":
                worker_agent, _, _ = await self._get_react_critic_agent_as_worker_agent(
                    llm=llm,
                    system_prompts=worker_agent_system_prompt,
                    tool_ids=worker_agent_tool_ids,
                    writer_holder=writer_holder  # Pass the shared writer_holder for streaming
                )
            else:
                err = f"Meta agent does not support worker agent of type '{worker_agent_type}' yet."
                log.error(err)
                raise HTTPException(status_code=501, detail=err)

            worker_agents_as_tools_list.append(
                await self._create_agent_as_tool(
                    agent_name=worker_agent_name,
                    description=worker_agent_description,
                    worker_agent=worker_agent,
                    writer_holder=writer_holder
                )
            )

        try:
            interrupt_before = ["tools"] if interrupt_tool and worker_agents_as_tools_list else None
            supervisor_agent = create_react_agent(
                model=llm,
                prompt=system_prompt,
                tools=worker_agents_as_tools_list,
                interrupt_before=interrupt_before,
                checkpointer=checkpointer
            )
            return supervisor_agent, worker_agents_as_tools_list, writer_holder

        except Exception as e:
            log.error(f"Error occurred while creating meta agent: {e}")
            raise HTTPException(status_code=500, detail=f"Error occurred while creating meta agent\nError: {e}")

