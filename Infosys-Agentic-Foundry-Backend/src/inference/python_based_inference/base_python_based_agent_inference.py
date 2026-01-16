# © 2024-25 Infosys Limited, Bangalore, India. All Rights Reserved.
import re
import json
import asyncio
from abc import abstractmethod

from typing import Any, Dict, List, Optional, Union, Callable, Literal, Tuple, AsyncGenerator
from fastapi import HTTPException

from src.schemas import AgentInferenceRequest
from src.inference.abstract_base_inference import AbstractBaseInference
from src.models.base_ai_model_service import BaseAIModelService
from src.tools.mcp_tool_adapter import MCPToolAdapter
from src.prompts.prompts import FORMATTER_PROMPT, online_agent_evaluation_prompt
from src.inference.inference_utils import InferenceUtils
from src.utils.helper_functions import get_timestamp

from telemetry_wrapper import logger as log, update_session_context
from src.utils.phoenix_manager import ensure_project_registered, traced_project_context, log_trace_context


class BasePythonBasedAgentInference(AbstractBaseInference):
    """
    Abstract base class for Python-based agent inference workflows.
    Provides common dependencies and helper methods for agents that
    directly use BaseAIModelService (e.g., AzureAIModelService) without LangGraph.
    """

    def __init__(self, inference_utils: InferenceUtils):
        super().__init__(inference_utils)
        self.chat_state_history_manager = self.chat_service.chat_state_history_manager


    # --- Helper Methods ---

    async def _get_mcp_tools_instances(self, tool_ids: List[str] = []) -> list:
        """
        Retrieves MCP tool instances based on the provided tool IDs.
        Args:
            tool_ids (List[str]): A list of tool IDs to retrieve instances for.
        """
        mcp_server_records = await super()._get_mcp_tools_instances(tool_ids=tool_ids)
        mcp_tool_list: List[MCPToolAdapter] = []

        for tool_record in mcp_server_records:
            try:
                tool_name = tool_record["tool_name"]
                mcp_config = tool_record["mcp_config"]

                mcp_client = await MCPToolAdapter.create_mcp_client(mcp_config)
                mcp_tools = await MCPToolAdapter.list_mcp_tools(client=mcp_client, return_adapter_objects=True)
                mcp_tool_list.extend(mcp_tools)

                log.info(f"MCP tool loading completed for: {tool_name}")

            except HTTPException:
                raise # Re-raise HTTPExceptions directly

            except Exception as e:
                log.error(f"Error occurred while loading mcp server {tool_name}: {e}")
                raise HTTPException(status_code=500, detail=f"Error occurred while loading mcp server {tool_name}: {e}")

        return mcp_tool_list

    async def _get_python_based_agent_instance(self,
                                llm: BaseAIModelService,
                                system_prompt: str,
                                tool_ids: List[str] = []
                            ) -> Tuple[BaseAIModelService, Optional[List[Callable]]]:
        """
        Helper method to create a Python-based agent instance with tools loaded dynamically.
        This function supports loading both Python code-based tools and MCP tools.
        """
        tool_list: List[Union[Callable, MCPToolAdapter]] = await self._get_tools_instances(tool_ids=tool_ids)
        memory_management_tools = await self._get_memory_management_tools_instances()
        tool_list.extend(memory_management_tools)

        if not tool_list:
            tool_list = None

        try:
            agent = llm.create_agent(
                system_prompt=system_prompt,
                tools=tool_list
            )
            return agent, tool_list

        except Exception as e:
            log.error(f"Error occurred while creating agent: {e}")
            raise HTTPException(status_code=500, detail=f"Error occurred while creating agent: {e}")

    async def format_final_response_for_canvas_view(self, query: str, response: str, llm: BaseAIModelService) -> str:
        """
        Uses a formatter LLM to format the final response for better readability in canvas view.
        """
        formatter_query = FORMATTER_PROMPT.format(query=query, response=response)
        log.info("Invoking formatter LLM for final response formatting.")
        formatted_response = await llm.ainvoke(messages=[llm.format_content_with_role(formatter_query)])
        log.info("Parsing formatted response from formatter LLM.")
        return self.inference_utils.extract_json_from_code_block(formatted_response["final_response"])

    async def _add_additional_data_to_final_response(self, data: Dict[str, Any], thread_id: str):
        """
        Saves the formatted response back to the chat history.
        """
        last_entry_id, last_entry_data = await self.chat_state_history_manager.get_most_recent_chat_entry(thread_id)
        last_step: dict = last_entry_data["agent_steps"][-1]
        last_step.update(data)
        log.info("Updating chat history with additional data.")
        await self.chat_state_history_manager.update_chat_entry(
            entry_id=last_entry_id,
            thread_id=thread_id,
            agent_steps=last_entry_data["agent_steps"],
            final_response=last_entry_data["final_response"]
        )

    async def evaluate_agent_response(self, agent_response: Dict[str, Any], llm: BaseAIModelService, workflow_description: str = "") -> Dict[str, Any]:
            
        def generate_conversation_string(agent_steps: List[Dict[str, Any]]) -> str:
            log.info("Generating conversation string from agent steps for evaluation.")
            conversation_lines = []
            for step in agent_steps:
                if step.get("role") == "user":
                    conversation_lines.append(f"User: {step.get('content')}")

                elif step.get("role") == "assistant":
                    if step.get("content"):
                        conversation_lines.append(f"Agent: {step.get('content')}")

                    if step.get("tool_calls", None):
                        for tool_call in step["tool_calls"]:
                            tool_name = tool_call["function"]["name"]
                            tool_input = tool_call["function"]["arguments"]
                            conversation_lines.append(f"Tool ({tool_name}) called with input: {tool_input}.")

                elif step.get("role") == "tool":
                    tool_name = step.get("name")
                    tool_output = step.get("content")
                    conversation_lines.append(f"Tool ({tool_name}) returned output: {tool_output}")
            log.info("Conversation string generation completed.")
            return "\n".join(conversation_lines)


        try:
            # Format the evaluation query
            log.info(f"EVALUATOR CALLED")
            formatted_evaluation_query = online_agent_evaluation_prompt.format(
                User_Query=agent_response["user_query"],
                Agent_Response=agent_response["final_response"],
                past_conversation_summary=generate_conversation_string(agent_response["agent_steps"]),
                workflow_description=workflow_description
            )

            # Call the LLM for evaluation
            evaluation_response = await llm.ainvoke([llm.format_content_with_role(formatted_evaluation_query)])
            evaluation_response = evaluation_response["final_response"]


            log.debug(f"Evaluator response received: {evaluation_response}")

            # Parse the JSON response
            evaluation_data = self.inference_utils.extract_json_from_code_block(evaluation_response)

            log.debug(f"Parsed evaluation data: {evaluation_data}")

            # Calculate aggregate score (average of all ratings)
            fluency_score = evaluation_data["fluency_evaluation"]["fluency_rating"]
            relevancy_score = evaluation_data["relevancy_evaluation"]["relevancy_rating"]
            coherence_score = evaluation_data["coherence_evaluation"]["coherence_score"]
            groundedness_score = evaluation_data["groundedness_evaluation"]["groundedness_score"]

            aggregate_score = (fluency_score + relevancy_score + coherence_score + groundedness_score) / 4

            # Compile feedback from all dimensions
            feedback_parts = []
            feedback_parts.append(f"**Fluency Feedback:** {evaluation_data['fluency_evaluation']['feedback']}")
            feedback_parts.append(f"**Relevancy Feedback:** {evaluation_data['relevancy_evaluation']['feedback']}")
            feedback_parts.append(f"**Coherence Feedback:** {evaluation_data['coherence_evaluation']['feedback']}")
            feedback_parts.append(f"**Groundedness Feedback:** {evaluation_data['groundedness_evaluation']['feedback']}")

            compiled_feedback = "\n\n".join(feedback_parts)

            log.info(f"Evaluation completed with aggregate score: {aggregate_score}")

            return {
                "evaluation_score": aggregate_score,
                "evaluation_feedback": compiled_feedback,
                "evaluation_details": evaluation_data,
            }

        except json.JSONDecodeError as e:
            log.error(f"Failed to parse evaluator JSON response: {e}")
            return {
                "evaluation_score": 0.3,
                "evaluation_feedback": "Evaluation failed due to JSON parsing error. Please review the response format and content quality.",
                "evaluation_details": evaluation_response,
                "error": str(e)
            }

        except Exception as e:
            log.error(f"Evaluation failed: {e}")
            return {
                "evaluation_score": 0.3,
                "evaluation_feedback": f"Evaluation failed due to error: {str(e)}",
                "evaluation_details": evaluation_response,
                "error": str(e)
            }
    

    @staticmethod
    async def _get_epoch_value(agent_steps: List[Dict[str, Any]], key: str = "epoch") -> int:
        """
        Retrieves the most recent epoch value from the agent steps.
        """
        for step in reversed(agent_steps):
            value = step.get(key, None)
            if value is not None:
                return value
        inf = int(1e9)
        return inf

    @abstractmethod
    async def _build_agent_and_chains(self, llm: BaseAIModelService, agent_config: Dict) -> Dict[str, Any]:
        """
        Abstract method to build the agent and chains for a specific Python-based agent type.
        Subclasses must implement this.
        """
        pass

    async def _generate_response(
                                self,
                                query: Optional[str],
                                agentic_application_id: str,
                                session_id: str,
                                model_name: str,
                                agent_config: dict,
                                project_name: str,
                                reset_conversation: bool = False,
                                *,
                                plan_verifier_flag: bool = False,
                                is_plan_approved: Optional[Literal["yes", "no", None]] = None,
                                plan_feedback: Optional[str] = None,
                                response_formatting_flag: bool = True,
                                tool_interrupt_flag: bool = False,
                                tool_feedback: str = None,
                                context_flag: bool = True,
                                temperature: float = 0,
                                evaluation_flag: bool = False
                            ) -> Dict[str, Any]:
        """
        Generates a response from the Python-based agent, handling history, tool calls,
        and plan/tool interruption. This is a common method for Python-based agents.
        """
        thread_id = await self.chat_service._get_thread_id(agentic_application_id, session_id)
        
        # Construct config for ainvoke method of BaseAIModelService
        config = {
            "configurable": {
                "thread_id": thread_id,
                "history_lookback": 8 if context_flag else 0,
                "resume_previous_chat": False,
                "store_response_custom_metadata": False
            },
            "tool_choice": "auto",
            "tool_interrupt": tool_interrupt_flag,
            "updated_tool_calls": tool_feedback
        }

        if reset_conversation:
            try:
                await self.chat_state_history_manager.clear_chat_history(thread_id)
                log.info(f"Conversation history for session {session_id} has been reset.")
            except Exception as e:
                log.error(f"Error occurred while resetting conversation: {e}")

        llm = await self.model_service.get_llm_model_using_python(model_name=model_name, temperature=temperature)
        chains = await self._build_agent_and_chains(llm, agent_config)
        app: BaseAIModelService = chains.get("agent", None)
        if not app:
            log.error("Agent instance not found in chains.")
            raise HTTPException(status_code=500, detail="Agent instance not found in chains.")

        app._temperature = temperature
        log.info("Agent build successfully")

        log.info(f"Invoking agent for query: {query}\n with Session ID: {session_id} and Agent Id: {agentic_application_id}")
        
        # Use the context-aware traced context manager to prevent trace mixing
        log_trace_context(f"before_python_agent_invocation_session_{session_id}")
        async with traced_project_context(project_name):
            log_trace_context(f"inside_python_traced_context_session_{session_id}")
            try:
                if query:
                    messages = [app.format_content_with_role(query)]
                else:
                    messages = None
                agent_resp = await app.ainvoke(messages=messages, config=config)
                log.info(f"Agent invoked successfully for query: {query} with session ID: {session_id}")
                final_response = await self.chat_state_history_manager.get_recent_history(thread_id=thread_id)
                return final_response

            except Exception as e:
                log.error(f"Error occurred during agent invocation: {e}", exc_info=True)
                raise HTTPException(status_code=500, detail=f"Error occurred during agent invocation: {str(e)}")
            
            finally:
                log_trace_context(f"after_python_agent_invocation_session_{session_id}")

    async def _generate_response_stream(
                                self,
                                query: Optional[str],
                                agentic_application_id: str,
                                session_id: str,
                                model_name: str,
                                agent_config: dict,
                                project_name: str,
                                reset_conversation: bool = False,
                                *,
                                plan_verifier_flag: bool = False,
                                is_plan_approved: Optional[Literal["yes", "no", None]] = None,
                                plan_feedback: Optional[str] = None,
                                response_formatting_flag: bool = True,
                                tool_interrupt_flag: bool = False,
                                tool_feedback: str = None,
                                context_flag: bool = True,
                                temperature: float = 0,
                                evaluation_flag: bool = False,
                                enable_streaming_flag: bool = False
                            ) -> AsyncGenerator[Dict[str, Any], None]:
        """
        Generates a streaming response from the Hybrid agent, handling history, tool calls,
        and plan/tool interruption. Yields status updates for node progress, tool calls, etc.
        """
        raise NotImplementedError("Streaming response generation is not implemented for this agent type.")

    async def run(self,
                  inference_request: AgentInferenceRequest,
                  *,
                  agent_config: Optional[Union[dict, None]] = None,
                  insert_into_eval_flag: bool = True,
                  role: str = None,
                  **kwargs
                ) -> Any:
        """
        Runs the Agent inference workflow.

        Args:
            request (AgentInferenceRequest): The request object containing all necessary parameters.
            role: Optional user role for response filtering.
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
            try:
                if tool_feedback:
                    query = ""
                    tool_feedback = json.loads(tool_feedback)
                if not isinstance(tool_feedback, (list, dict)):
                    log.error("Tool feedback is not a list or dict, setting to None")
                    tool_feedback = None

            except Exception as e:
                log.error("Error parsing tool feedback JSON, setting to None")
                tool_feedback = None

            plan_verifier_flag = inference_request.plan_verifier_flag
            is_plan_approved = inference_request.is_plan_approved
            plan_feedback = inference_request.plan_feedback

            response_formatting_flag = inference_request.response_formatting_flag
            context_flag = inference_request.context_flag
            evaluation_flag = inference_request.evaluation_flag

            context_flag = inference_request.context_flag
            temperature = inference_request.temperature
            enable_streaming_flag = inference_request.enable_streaming_flag


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

            start_timestamp = get_timestamp()

            # Check if streaming is enabled and _generate_response_stream method exists
            if enable_streaming_flag and hasattr(self, '_generate_response_stream'):
                # Use streaming response generation
                response = None
                async for stream_chunk in self._generate_response_stream(
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
                    tool_interrupt_flag=tool_interrupt_flag,
                    tool_feedback=tool_feedback,
                    context_flag=context_flag,
                    evaluation_flag=evaluation_flag,
                    temperature=temperature,
                    enable_streaming_flag=enable_streaming_flag
                ):
                    # Forward streaming status updates (but not the final history list)
                    if isinstance(stream_chunk, dict) and "executor_messages" not in stream_chunk:
                        yield stream_chunk
                    # Capture final response - it's the list from get_recent_history at the end
                    if isinstance(stream_chunk, list):
                        response = stream_chunk
                    elif isinstance(stream_chunk, dict) and ("final_response" in stream_chunk and "agent_steps" in stream_chunk):
                        # This is an intermediate response from astream, not the final history
                        pass
            else:
                # Use non-streaming response generation
                response = await self._generate_response(
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
                    tool_interrupt_flag=tool_interrupt_flag,
                    tool_feedback=tool_feedback,
                    context_flag=context_flag,
                    evaluation_flag=evaluation_flag,
                    temperature=temperature
                )

            if not response:
                log.error("No response received from agent.")
                yield {"error": "No response received from agent."}
                return


            formatted_response: dict = await self.chat_service._format_python_based_agent_history(response)

            # Adding metadata in response for consistency
            log.info("Adding metadata to the final response.")
            formatted_response["agentic_application_id"] = agentic_application_id
            formatted_response["session_id"] = session_id
            formatted_response["model_name"] = model_name
            formatted_response["reset_conversation"] = reset_conversation
            formatted_response["response_formatting_flag"] = response_formatting_flag
            formatted_response["context_flag"] = context_flag
            formatted_response["is_tool_interrupted"] = tool_interrupt_flag
            formatted_response["workflow_description"] = agent_config.get("WORKFLOW_DESCRIPTION", "")
            formatted_response["evaluation_flag"] = evaluation_flag
            formatted_response["start_timestamp"] = start_timestamp
            end_timestamp = get_timestamp()
            formatted_response["end_timestamp"] = end_timestamp


            if insert_into_eval_flag:
                eval_executor_messages = []
                log.info("Preparing executor messages for evaluation logging.")
                for exe_msg in formatted_response.get("executor_messages", []):
                    eval_executor_messages.append({
                        "user_query": exe_msg["user_query"],
                        "final_response": exe_msg["final_response"],
                        "agent_steps": list(reversed(exe_msg["additional_details"]))
                    })

                response_evaluation = {
                    "query": formatted_response["query"],
                    "response": formatted_response["response"],
                    "executor_messages": eval_executor_messages
                }

                try:
                    log.info("Inserting evaluation data into the database.")
                    asyncio.create_task(self.evaluation_service.log_evaluation_data(session_id, agentic_application_id, agent_config, response_evaluation, model_name))
                except Exception as e:
                    log.error(f"Error Occurred while inserting into evaluation data: {e}")

            yield formatted_response

        except Exception as e:
            # Catch any unhandled exceptions and raise a 500 internal server error
            log.error(f"Error Occurred in agent inference: {e}", exc_info=True)
            raise HTTPException(status_code=500, detail=f"Internal Server Error: {str(e)}")

