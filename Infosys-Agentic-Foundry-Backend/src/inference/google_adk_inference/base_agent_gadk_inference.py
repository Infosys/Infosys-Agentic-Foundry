# © 2024-25 Infosys Limited, Bangalore, India. All Rights Reserved.
import json
import asyncio
from uuid import uuid4
from abc import abstractmethod
from typing import Any, List, Dict, Optional, Union, Literal, Callable, Tuple, AsyncGenerator
from fastapi import HTTPException

from google.adk.agents import BaseAgent, LlmAgent, LoopAgent
from google.adk.models.lite_llm import LiteLlm
from google.adk.runners import Runner
from google.adk.apps import App, ResumabilityConfig
from google.genai import types
from google.genai.types import Content, Part
from google.adk.tools.mcp_tool.mcp_toolset import MCPToolset, StreamableHTTPConnectionParams, StdioConnectionParams, StdioServerParameters
from google.adk.tools.base_tool import BaseTool
from google.adk.tools.tool_context import ToolContext
from google.adk.tools import LongRunningFunctionTool
from google.adk.agents.callback_context import CallbackContext
from google.adk.models import LlmRequest, LlmResponse
from google.adk.events.event import Event
from google.adk.sessions.session import Session

from src.inference.abstract_base_inference import AbstractBaseInference
from src.inference.inference_utils import InferenceUtils
from src.schemas import AgentInferenceRequest, CanvasFormatSchema, EvaluationSchema, ValidationSchema, AdminConfigLimits
from src.prompts.prompts import FORMATTER_PROMPT, GADK_EVALUATION_PROMPT, GADK_VALIDATOR_AGENT_SYSTEM_PROMPT
from src.utils.helper_functions import convert_value_type_of_candidate_as_given_in_reference
from src.config.constants import Limits, AgentType

from phoenix.otel import register
from phoenix.trace import using_project
from telemetry_wrapper import logger as log, update_session_context



class BaseAgentGADKInference(AbstractBaseInference):
    """
    Abstract base class for Google ADK Agent Inference implementations.
    Defines common methods and properties for agent inference workflows.
    """

    def __init__(self, inference_utils: InferenceUtils):
        super().__init__(inference_utils)
        self.gadk_session_service = self.chat_service.gadk_session_service


    # --- Helper Methods ---

    @staticmethod
    async def _get_mcp_toolset_from_config(mcp_config: dict, timeout: float = 5) -> MCPToolset:
        """
        Helper method to create an MCPToolset instance from the given configuration.
        """
        try:
            transport = mcp_config.get("transport", "stdio")
            if transport == "stdio":
                server_params = StdioServerParameters(
                    command=mcp_config["command"],
                    args=mcp_config.get("args")
                )
                connection_params = StdioConnectionParams(server_params=server_params, timeout=timeout)

            elif transport == "streamable_http":
                connection_params = StreamableHTTPConnectionParams(
                    url=mcp_config["url"],
                    headers=mcp_config.get("headers", None),
                    timeout=timeout
                )

            else:
                raise ValueError(f"Unsupported transport type: {transport}")

            mcp_toolset = MCPToolset(connection_params=connection_params)
            return mcp_toolset

        except Exception as e:
            log.error(f"Error occurred while creating MCPToolset: {e}")
            raise HTTPException(status_code=500, detail=f"Error occurred while creating MCPToolset: {e}")

    async def _get_mcp_tools_instances(self, tool_ids: List[str] = []) -> list:
        """
        Retrieves MCP tool instances based on the provided tool IDs.
        Args:
            tool_ids (List[str], optional): List of tool IDs. Defaults to [].
        """
        mcp_server_records = await super()._get_mcp_tools_instances(tool_ids=tool_ids)

        mcp_tool_list: List[MCPToolset] = []

        for tool_record in mcp_server_records:
            try:
                tool_name = tool_record["tool_name"]
                mcp_config = tool_record["mcp_config"]

                mcp_toolset = await self._get_mcp_toolset_from_config(mcp_config=mcp_config)
                mcp_tool_list.append(mcp_toolset)
                log.info(f"MCP tools loading completed for: {tool_name}")

            except HTTPException:
                raise # Re-raise HTTPExceptions directly

            except Exception as e:
                log.error(f"Error occurred while loading mcp server {tool_name}: {e}")
                raise HTTPException(status_code=500, detail=f"Error occurred while loading mcp server {tool_name}: {e}")

        return mcp_tool_list

    async def _get_gadk_runner_instance(self, agent: BaseAgent, agent_id: str, session_id: str) -> Tuple[Runner, Session]:
        """
        Creates and returns a GADK Runner instance for the given agent and session ID.
        """
        try:
            user_id = self._extract_user_email_from_session_id(session_id=session_id)

            session = await self.gadk_session_service.get_session(
                app_name=agent_id,
                user_id=user_id,
                session_id=session_id
            )
            if not session:
                session = await self.gadk_session_service.create_session(
                    app_name=agent_id,
                    user_id=user_id,
                    session_id=session_id
                )

            root_agent_app = App(
                name=agent_id,
                root_agent=agent,
                resumability_config=ResumabilityConfig(is_resumable=True)
            )

            runner = Runner(
                app=root_agent_app,
                session_service=self.gadk_session_service
            )
            log.info(f"GADK Runner created successfully for session ID: {session_id}")
            return runner, session

        except Exception as e:
            log.error(f"Error occurred while creating GADK Runner: {e}")
            raise HTTPException(status_code=500, detail=f"Error occurred while creating GADK Runner: {e}")
        
    async def _delete_adk_session(self, agent_id: str, session_id: str):
        """
        Deletes the ADK session for the given agent and session ID.
        """
        try:
            user_id = self._extract_user_email_from_session_id(session_id=session_id)

            await self.gadk_session_service.delete_session(
                app_name=agent_id,
                user_id=user_id,
                session_id=session_id
            )
            log.info(f"ADK session deleted successfully for session ID: {session_id}")

        except Exception as e:
            log.error(f"Error occurred while deleting ADK session: {e}")
            raise HTTPException(status_code=500, detail=f"Error occurred while deleting ADK session: {e}")


    # --- SSE Streaming Helper Methods ---

    @staticmethod
    async def _parse_gadk_event_for_sse(event: Event) -> Optional[Dict[str, Any]]:
        """
        Parses a Google ADK Event and formats it for SSE streaming.
        
        Args:
            event: Google ADK Event object containing content from the agent
            
        Returns:
            Dictionary formatted for SSE streaming, or None if event has no relevant content
        """
        if not event or not event.content or not event.content.parts:
            return None
        
        sse_data = {
            "author": event.author if hasattr(event, "author") else "agent",
            "invocation_id": event.invocation_id if hasattr(event, "invocation_id") else None,
        }
        
        for part in event.content.parts:
            # Handle text content
            if hasattr(part, "text") and part.text:
                sse_data["type"] = "text"
                sse_data["content"] = part.text
                sse_data["Node Name"] = sse_data.get("author", "Agent")
                sse_data["Status"] = "Thinking"
                
                # Format validator and critic responses for cleaner SSE output
                author = sse_data.get("author", "")
                content = part.text
                
                # Check if this is a validator response
                if "validator_for_" in author:
                    formatted_content = await BaseAgentGADKInference._format_validator_response(content)
                    if formatted_content:
                        sse_data["content"] = formatted_content
                        sse_data["Node Name"] = "Validating Response"
                
                # Check if this is a critic response
                elif "critic_for_" in author or "critic_planner_for_" in author:
                    formatted_content = await BaseAgentGADKInference._format_critic_response(content)
                    if formatted_content:
                        sse_data["content"] = formatted_content
                        sse_data["Node Name"] = "Critic Evaluation"
                
                return sse_data
            
            # Handle function calls (tool invocations)
            if hasattr(part, "function_call") and part.function_call:
                func_call = part.function_call
                sse_data["type"] = "tool_call"
                sse_data["Node Name"] = "Tool Call"
                sse_data["Status"] = "Started"
                sse_data["Tool Name"] = func_call.name if hasattr(func_call, "name") else "unknown"
                sse_data["Tool Arguments"] = dict(func_call.args) if hasattr(func_call, "args") and func_call.args else {}
                sse_data["content"] = f"Agent is calling tool: {sse_data['Tool Name']}"
                return sse_data
            
            # Handle function responses (tool results)
            if hasattr(part, "function_response") and part.function_response:
                func_resp = part.function_response
                sse_data["type"] = "tool_response"
                sse_data["Node Name"] = "Tool Call"
                sse_data["Status"] = "Completed"
                sse_data["Tool Name"] = func_resp.name if hasattr(func_resp, "name") else "unknown"
                response_content = func_resp.response if hasattr(func_resp, "response") else {}
                sse_data["Tool Output"] = response_content
                sse_data["content"] = f"Tool {sse_data['Tool Name']} returned results"
                return sse_data
        
        return None

    @staticmethod
    async def _create_sse_status_event(node_name: str, status: str, additional_info: Optional[Dict] = None) -> Dict[str, Any]:
        """
        Creates a standardized SSE status event.
        
        Args:
            node_name: Name of the workflow node/agent
            status: Status of the node (Started, Completed, In Progress, etc.)
            additional_info: Optional additional information to include
            
        Returns:
            Dictionary formatted for SSE streaming
        """
        event = {
            "Node Name": node_name,
            "Status": status
        }
        if additional_info:
            event.update(additional_info)
        return event

    @staticmethod
    async def _format_validator_response(content: str) -> Optional[str]:
        """
        Formats validator agent JSON response into a clean, readable format.
        
        Args:
            content: Raw JSON response from validator agent
            
        Returns:
            Formatted string with validation score, or None if parsing fails
        """
        try:
            import json
            data = json.loads(content)
            
            validation_score = data.get("aggregate_score", None)
            if validation_score is not None:
                return f"Validation score: {validation_score}"
            
            # Fallback: try to extract from validation_results
            validation_results = data.get("validation_results", [])
            if validation_results and len(validation_results) > 0:
                score = validation_results[0].get("validation_score", None)
                if score is not None:
                    return f"Validation score: {score}"
            
            return None
        except (json.JSONDecodeError, KeyError, TypeError):
            return None

    @staticmethod
    async def _format_critic_response(content: str) -> Optional[str]:
        """
        Formats critic agent JSON response into a clean, readable format.
        
        Args:
            content: Raw JSON response from critic agent
            
        Returns:
            Formatted string with critic evaluation details, or None if parsing fails
        """
        try:
            import json
            data = json.loads(content)
            
            score = data.get("response_quality_score", None)
            critique_points = data.get("critique_points", [])
            
            if score is not None:
                lines = [f"Critic evaluation score: {score}/1.0"]
                
                # Add first critique point as feedback (truncated if too long)
                if critique_points and len(critique_points) > 0:
                    feedback = critique_points[0]
                    if len(feedback) > 150:
                        feedback = feedback[:147] + "..."
                    lines.append(f"Critic feedback: {feedback}")
                
                # Add analysis status
                if score >= 0.7:
                    lines.append("Analysis complete: Response quality is acceptable, proceeding to final output")
                else:
                    lines.append("Analysis complete: Response needs improvement, requesting refinement")
                
                return "\n".join(lines)
            
            return None
        except (json.JSONDecodeError, KeyError, TypeError):
            return None

    # --- Additional Helper Methods for GADK ---

    @staticmethod
    async def get_parts_with_feedback_prompt_if_required(query: str) -> List[Part]:
        """
        Checks if the query contains feedback indicators and formats the parts accordingly.
        """
        parts = []
        if query == "[regenerate:][:regenerate]":
            parts.append(Part(text="FEEDBACK:"))
            query = "The previous response did not meet expectations. Please review the query and provide a new, more accurate response."

        elif query.startswith("[feedback:]") and query.endswith("[:feedback]"):
            parts.append(Part(text="FEEDBACK:"))
            user_feedback = query[11:-11]
            query = f"""The previous response was not satisfactory. Here is the feedback given by the user on your previous response:
{user_feedback}

Please review the query and feedback, and provide an appropriate answer.
"""
        parts.append(Part(text=query))
        return parts

    @staticmethod
    async def get_formatted_gadk_content(
                    *,
                    role: str="user",
                    query: Optional[str]=None,
                    function_response: Optional[Dict[str, Any]]=None
                ) -> Content:
        """
        Formats the GADK Content based on the provided query or function response.

        Args:
            role (str, optional): The role of the content. Defaults to "user".
            query (Optional[str], optional): The user query. Defaults to None.
            function_response (Optional[Dict[str, Any]], optional): The function response. Defaults to None.

        Returns:
            Content: The formatted GADK Content object.
        """
        if query:
            parts = await BaseAgentGADKInference.get_parts_with_feedback_prompt_if_required(query=query)
            return Content(role=role, parts=parts)

        if function_response:
            response_key = 'response' if 'response' in function_response else 'result'
            return Content(
                role=role,
                parts=[
                    Part(
                        function_response=types.FunctionResponse(
                            id=function_response['id'],
                            name=function_response['name'],
                            response={response_key: function_response[response_key]}
                        )
                    )
                ]
            )

        raise ValueError("Either query or function_response must be provided.")

    @staticmethod
    async def get_new_function_call_id() -> str:
        return f"call_{uuid4().hex[:24]}"

    @staticmethod
    async def get_last_pending_function_call_event(events: List[Event], function_name: str = "get_user_approval_or_feedback") -> Optional[Event]:
        """
        Retrieves the last event from the list of events that contains a pending function call with the specified function name.
        """
        for event in reversed(events):
            if not event.content or not event.content.parts:
                continue
            part = event.content.parts[0]
            if part.function_call:
                if part.function_call.name == function_name:
                    return event
                return None
        return None

    @staticmethod
    async def add_additional_args_to_litellm_object(llm: LiteLlm, **additional_args: Dict[str, Any]) -> LiteLlm:
        """
        Adds additional arguments to the LiteLlm object and return a copy of it.
        """
        if not isinstance(llm, LiteLlm):
            return llm
        llm_copy = llm.model_copy(deep=True)
        llm_copy._additional_args.update(additional_args)
        log.info(f"Added additional args to LiteLlm object: {additional_args}")
        return llm_copy

    @staticmethod
    async def get_tool_interrupt_interpretation_prompt():
        return (
            "- The user might interrupt the tool execution to change the parameters. "
            "If the user modifies the parameters, proceed directly with the updated arguments and generate the response based on the results from the new parameters. "
            "Do not execute the tool with the original, outdated arguments. "
            "Additionally, if the user modifies the arguments during interruption, "
            "the tool execution will include a note indicating that the arguments were changed by the user. Pay attention to this note to correctly interpret the tool response."
        )

    # --- Get Callback Methods ---

    @staticmethod
    async def get_before_tool_callback_for_tool_interrupt(tool_verifier_flag: bool = False, tools_to_interrupt: List[str] = None) -> Optional[Callable]:
        if not tool_verifier_flag:
            return None

        tool_call_to_ignore = ["manage_memory", "search_memory", "adk_request_confirmation", "set_model_response", "get_user_approval_or_feedback", "exit_replanner_loop"]
        async def _before_tool_callback_for_tool_interrupt(tool: BaseTool, args: Dict[str, Any], tool_context: ToolContext) -> Optional[Dict]:
            """
            Callback to intercept tool calls and request user confirmation for tool arguments if needed.
            """
            tool_name = tool.name
            if tool_name in tool_call_to_ignore or (tools_to_interrupt and tool_name not in tools_to_interrupt):
                log.info(f"[Callback] Tool '{tool_name}' is not in the interrupt list, proceeding without confirmation.")
                return None

            events = tool_context._invocation_context.session.events

            log.info(f"[Callback] Before tool call for '{tool_name}'")
            log.info(f"[Callback] Original args: {args}")
            log.info(f"[Callback] Tool confirmed: {tool_context.tool_confirmation}")
            if not tool_context.tool_confirmation:
                tool_context.request_confirmation(
                    hint=f"Please confirm the following arguments for the tool '{tool_name}' before proceeding: {args}. If not approved please provide updated arguments to be used for tool parameters in the given format.",
                    payload=args
                )
                tool_context.state["tool_interrupt_old_args"] = [tool_name, args.copy()]
                return {"status": f"Pending tool confirmation for tool '{tool_name}' with args: {args}."}

            new_args = tool_context.tool_confirmation.payload
            if new_args:
                new_args = convert_value_type_of_candidate_as_given_in_reference(reference=args, candidate=new_args)
                log.info(f"[Callback] New args from confirmation: {new_args}")

            if not new_args or new_args == args:
                log.info(f"[Callback] Tool call was approved proceeding with original args.")
                tool_context.state["tool_interrupt_old_args"] = None
                return None

            args.update(new_args)
            tool_context.state["tool_interrupt_new_args"] = [tool_name, args.copy()]
            log.info(f"[Callback] Modified args after confirmation: {args}")

            return None
        return _before_tool_callback_for_tool_interrupt

    @staticmethod
    async def get_after_tool_callback_for_tool_interrupt(tool_verifier_flag: bool = False) -> Optional[Callable]:
        if not tool_verifier_flag:
            return None

        async def _after_tool_callback_for_tool_interrupt(tool: BaseTool, args: Dict[str, Any], tool_context: ToolContext, tool_response: Any) -> Optional[Dict]:
            """
            Callback to modify tool response based on user-confirmed arguments if needed.
            """
            tool_name = tool.name
            log.info(f"[Callback] After tool call for '{tool_name}'")
            log.info(f"[Callback] Args used: {args}")
            log.info(f"[Callback] Original response: {tool_response}")

            state = tool_context.state

            old_args = state.get("tool_interrupt_old_args")
            new_args = state.get("tool_interrupt_new_args")

            if old_args and new_args and old_args[0] == new_args[0] == tool_name:
                state["tool_interrupt_old_args"] = state["tool_interrupt_new_args"] = None
                note_msg = f"The tool '{tool_name}' was originally called with arguments {old_args[1]}. However, as part of the human-in-the-loop process, the user explicitly updated the arguments to {new_args[1]}. Consequently, the tool was executed using these updated arguments ({new_args[1]}). Please proceed with the understanding that the operation was performed using the user-specified values."
                log.info(note_msg)
                return {
                    "tool_response": tool_response,
                    "Note": note_msg
                }
        return _after_tool_callback_for_tool_interrupt

    @staticmethod
    async def get_after_planner_agent_callback() -> Callable:
        async def _after_planner_agent_callback(callback_context: CallbackContext) -> Optional[Content]:
            """
            Simple callback that initializes the plan index in the session state after the planner agent has run.
            """
            # Get the session state
            state = callback_context.state
            plan = state.get("plan", {})
            if isinstance(plan, dict):
                plan = plan.get("plan", [])
            state["plan"] = plan
            state["plan_idx"] = 0
            state["plan_feedback"] = None
            return None
        return _after_planner_agent_callback

    @staticmethod
    async def get_before_plan_verifier_model_callback_function(plan_verifier_flag: bool) -> Callable:
        async def _before_plan_verifier_model_callback_function(callback_context: CallbackContext, llm_request: LlmRequest) -> Optional[LlmResponse]:
            state = callback_context.state

            plan = state.get("plan", {})
            if isinstance(plan, dict):
                plan = plan.get("plan", [])

            plan_feedback: str = state.get("plan_feedback", None)

            if not plan_verifier_flag or not plan:
                callback_context._event_actions.escalate = True
                state["plan_feedback"] = None
                return LlmResponse(content=types.Content(parts=[types.Part(text="Verification not required.")]))

            if not plan_feedback:
                function_call_id = await BaseAgentGADKInference.get_new_function_call_id()
                return LlmResponse(
                    content=types.Content(
                        role='model',
                        parts=[types.Part(
                            function_call=types.FunctionCall(
                                id=function_call_id,
                                args={},
                                name='get_user_approval_or_feedback'
                            )
                        )],
                    )
                )
            return None
        return _before_plan_verifier_model_callback_function

    @staticmethod
    async def get_before_executor_loop_agent_callback() -> Callable:
        async def _before_executor_loop_agent_callback(callback_context: CallbackContext):
            state = callback_context.state
            plan = state.get("plan", [])
            if not plan:
                return Content(parts=[Part(text="No plan available to execute.")])
            max_iterations = max(1, len(plan))
            executor_loop_agent: LoopAgent = callback_context._invocation_context.agent
            executor_loop_agent.max_iterations = max_iterations
        return _before_executor_loop_agent_callback

    @staticmethod
    async def get_before_executor_agent_callback() -> Callable:
        async def _before_executor_agent_callback(callback_context: CallbackContext):
            state = callback_context.state
            plan = state.get("plan", [])
            idx = state.get("plan_idx", 0)

            current_step = plan[idx] if idx < len(plan) else "No more steps remaining."
            state["current_step"] = current_step
            state["plan_idx"] = idx + 1
        return _before_executor_agent_callback

    @staticmethod
    async def get_after_critics_tool_callback(inference_config: AdminConfigLimits = AdminConfigLimits()) -> Callable:
        async def _after_critics_tool_callback(tool: BaseTool, args: Dict[str, Any], tool_context: ToolContext, tool_response: Dict) -> Optional[Dict]:
            if isinstance(tool_response, dict) and tool.name == "set_model_response":
                response_quality_score = tool_response.get("response_quality_score", 1)
                critic_evaluation_attempts = tool_context.state.get("critic_evaluation_attempts", 0) + 1
                tool_context.state["critic_evaluation_attempts"] = critic_evaluation_attempts
                parent_agent: LoopAgent = tool_context._invocation_context.agent.parent_agent
                if response_quality_score >= inference_config.critic_score_threshold or critic_evaluation_attempts >= getattr(parent_agent, "max_iterations", inference_config.max_critic_epochs):
                    tool_context.actions.escalate = True
        return _after_critics_tool_callback

    @staticmethod
    async def get_after_critic_loop_agent_callback() -> Callable:
        async def _after_critic_loop_agent_callback(callback_context: CallbackContext):
            state = callback_context.state
            state["critic_response"] = ""
            state["critic_evaluation_attempts"] = 0
        return _after_critic_loop_agent_callback

    @staticmethod
    async def get_before_agent_callback_for_quality_loop() -> Callable:
        """
        Returns a callback function that resets both evaluation and validation related state 
        before the agent processes a new query. This ensures that attempts are reset for each 
        new user query, not accumulated across queries.
        """
        async def _before_agent_callback_for_quality_loop(callback_context: CallbackContext) -> Optional[Content]:
            state = callback_context.state
            # Reset quality loop attempts
            state["quality_loop_attempts"] = 0
            state["quality_assessment_feedback"] = ""
            state["evaluation_result"] = state["validation_result"] = None
            log.info("Reset evaluation and validation state for new query.")

        return _before_agent_callback_for_quality_loop

    @staticmethod
    async def get_after_quality_assessment_agent_callback(
                evaluation_threshold: Optional[float] = None,
                validation_threshold: Optional[float] = None,
                max_iterations: Optional[int] = None
            ) -> Callable:
        """
        Returns a callback function for the quality assessment loop that handles both
        evaluation and validation results.
        
        This callback decides whether to:
        1. Accept the response (all enabled checks pass or max iterations reached) -> escalate to exit loop
        2. Reject and retry (any enabled check fails and iterations remaining) -> continue loop with combined feedback
        
        Args:
            evaluation_threshold: Minimum evaluation score (0-1) to accept.
            validation_threshold: Minimum validation score (0-1) to accept.
            max_iterations: Maximum number of quality loop attempts.
        """
        config_limits = AdminConfigLimits()
        if evaluation_threshold is None:
            evaluation_threshold = config_limits.evaluation_score_threshold
        if validation_threshold is None:
            validation_threshold = config_limits.validation_score_threshold
        if max_iterations is None:
            max_iterations = max(config_limits.max_evaluation_epochs, config_limits.max_validation_epochs)

        async def _after_quality_assessment_agent_callback(callback_context: CallbackContext) -> Optional[Content]:
            state = callback_context.state

            # Track quality loop attempts
            quality_loop_attempts = state.get("quality_loop_attempts", 0) + 1
            state["quality_loop_attempts"] = quality_loop_attempts

            evaluation_result: dict = state.get("evaluation_result", None)
            validation_result: dict = state.get("validation_result", None)

            evaluation_score = 0.0 if evaluation_result else 1.0
            validation_score = 0.0 if validation_result else 1.0
            evaluation_passed = validation_passed = True  # Default to True if checks are not performed

            feedback_parts = []

            if evaluation_result and isinstance(evaluation_result, dict):
                fluency = evaluation_result.get("fluency_evaluation", {})
                relevancy = evaluation_result.get("relevancy_evaluation", {})
                coherence = evaluation_result.get("coherence_evaluation", {})
                groundedness = evaluation_result.get("groundedness_evaluation", {})

                fluency_score = fluency.get("fluency_rating", 0.0) if isinstance(fluency, dict) else 0.0
                relevancy_score = relevancy.get("relevancy_rating", 0.0) if isinstance(relevancy, dict) else 0.0
                coherence_score = coherence.get("coherence_score", 0.0) if isinstance(coherence, dict) else 0.0
                groundedness_score = groundedness.get("groundedness_score", 0.0) if isinstance(groundedness, dict) else 0.0

                evaluation_score = (fluency_score + relevancy_score + coherence_score + groundedness_score) / 4
                state["evaluation_result"]["aggregate_score"] = evaluation_score

                evaluation_passed = evaluation_score >= evaluation_threshold

                if not evaluation_passed:
                    eval_feedback = []
                    if isinstance(fluency, dict) and fluency.get("feedback"):
                        eval_feedback.append(f"**Fluency ({fluency.get('fluency_rating', 'N/A')}):** {fluency.get('feedback')}")
                    if isinstance(relevancy, dict) and relevancy.get("feedback"):
                        eval_feedback.append(f"**Relevancy ({relevancy.get('relevancy_rating', 'N/A')}):** {relevancy.get('feedback')}")
                    if isinstance(coherence, dict) and coherence.get("feedback"):
                        eval_feedback.append(f"**Coherence ({coherence.get('coherence_score', 'N/A')}):** {coherence.get('feedback')}")
                    if isinstance(groundedness, dict) and groundedness.get("feedback"):
                        eval_feedback.append(f"**Groundedness ({groundedness.get('groundedness_score', 'N/A')}):** {groundedness.get('feedback')}")
                    
                    if eval_feedback:
                        feedback_parts.append("**[Evaluation Feedback]**\n" + "\n".join(eval_feedback))

                log.info(f"Evaluation check - Score: {evaluation_score}, Passed: {evaluation_passed}")

            if validation_result and isinstance(validation_result, dict):
                validation_score = validation_result.get("aggregate_score", 0.0)
                validation_passed = validation_score >= validation_threshold

                if not validation_passed:
                    validation_feedback = validation_result.get("validation_feedback", "")
                    if validation_feedback:
                        feedback_parts.append(f"**[Validation Feedback]** (Score: {validation_score})\n{validation_feedback}")

                log.info(f"Validation check - Score: {validation_score}, Passed: {validation_passed}")

            # Decision logic: pass if all enabled checks pass OR max iterations reached
            all_passed = evaluation_passed and validation_passed
            max_reached = quality_loop_attempts >= max_iterations

            if all_passed or max_reached:
                # Clear feedback so the next query will trigger a reset
                state["quality_assessment_feedback"] = ""
                callback_context._event_actions.escalate = True
                log.info(f"Quality loop completed - Evaluation Passed: {evaluation_passed}, Validation Passed: {validation_passed}, Attempts: {quality_loop_attempts}, Max Reached: {max_reached}")

            else:
                # Compile combined feedback for the next iteration
                combined_feedback = "\n\n".join(feedback_parts) if feedback_parts else "Please improve the response quality."
                state["quality_assessment_feedback"] = combined_feedback                
                log.info(f"Quality loop continuing - Evaluation Score: {evaluation_score}, Validation Score: {validation_score}, Attempts: {quality_loop_attempts}")

            return None
        return _after_quality_assessment_agent_callback

    async def get_after_validator_model_callback(self, validation_criteria: List[dict] = None) -> Callable:
        """
        Returns a callback function that processes the validator agent's response.
        It handles tool-based validation for criteria that have validator tools,
        calculates aggregate scores, and returns the final validation result.
        
        Args:
            validation_criteria: List of validation criteria with optional validator tool IDs
            
        Returns:
            Callable: The after_model_callback function for the validator agent
        """
        # Store reference to self for use in nested function
        inference_instance = self

        async def _after_validator_model_callback(callback_context: CallbackContext, llm_response: LlmResponse) -> Optional[LlmResponse]:
            """
            Process the validator agent's response:
            1. Parse the LLM response
            2. For each validation result with index >= 0, check if validator tool exists
            3. If validator tool exists, execute it and update the result
            4. Calculate aggregate score and validation_passed status
            5. Return the final LlmResponse
            """
            try:
                # Parse the LLM response content
                response_text = llm_response.content.parts[0].text if llm_response.content and llm_response.content.parts else ""

                # Clean the response if it has markdown code blocks
                if response_text.startswith("```json"):
                    response_text = response_text.replace("```json", "").replace("```", "").strip()
                elif response_text.startswith("```"):
                    response_text = response_text.replace("```", "").strip()

                validation_data: dict = json.loads(response_text)
                validation_results: List[dict] = validation_data.get("validation_results", [])
                
                # Process each validation result
                processed_results = []
                total_score = 0.0
                matched_patterns_count = 0
                feedback_parts = []
                
                for result in validation_results:
                    validation_index = result.get("validation_index", -1)

                    if validation_index == -1:
                        # General relevancy score - use as is
                        processed_results.append(result)
                        total_score += result.get("validation_score", 0.0)
                        if result.get("feedback"):
                            feedback_parts.append(f"[General Relevancy] {result.get('feedback')}")
                        log.info(f"General relevancy validation - Score: {result.get('validation_score', 0.0)}")

                    else:
                        # Matched criteria - check if we have a validator tool
                        matched_patterns_count += 1

                        # Get the corresponding criteria
                        if validation_criteria and 0 <= validation_index < len(validation_criteria):
                            criteria = validation_criteria[validation_index]
                            validator_tool_id = criteria.get("validator")
                            
                            if validator_tool_id:
                                # We have a validator tool - execute it
                                try:
                                    state = callback_context.state
                                    query = state.get("query", "")
                                    response = state.get("response", "")
                                    
                                    # Get the validator function
                                    validator_function = await inference_instance._get_validator_tool_instance(validator_tool_id)
                                    
                                    if validator_function:
                                        # Execute the validator tool
                                        tool_result: dict = validator_function(query=query, response=response)
                                        
                                        # Handle async functions
                                        if hasattr(tool_result, '__await__'):
                                            tool_result = await tool_result
                                        
                                        # Update result with tool output
                                        result["validation_status"] = tool_result.get("validation_status", result.get("validation_status", "fail"))
                                        result["validation_score"] = float(tool_result.get("validation_score", result.get("validation_score", 0.0)))
                                        result["feedback"] = tool_result.get("feedback", result.get("feedback", ""))
                                        result["validation_type"] = "tool_validator"
                                        
                                        log.info(f"Tool validator executed for index {validation_index} - Score: {result['validation_score']}")
                                    else:
                                        log.warning(f"Validator function not found for tool ID: {validator_tool_id}, using LLM result")
                                        result["validation_type"] = "llm_validator"
                                        
                                except Exception as tool_error:
                                    log.error(f"Error executing validator tool {validator_tool_id}: {tool_error}")
                                    # Keep the LLM's result but mark as error
                                    result["validation_type"] = "tool_validator_error"
                                    result["feedback"] = f"{result.get('feedback', '')} [Tool execution error: {str(tool_error)}]"
                            else:
                                # No validator tool - use LLM's validation result as is
                                result["validation_type"] = "llm_validator"
                                log.info(f"LLM validation for index {validation_index} - Score: {result.get('validation_score', 0.0)}")
                        else:
                            # Invalid index - use as is
                            result["validation_type"] = "llm_validator"
                            log.warning(f"Invalid validation index {validation_index}, using LLM result")
                        
                        processed_results.append(result)
                        total_score += result.get("validation_score", 0.0)
                        
                        if result.get("feedback"):
                            criteria_query = validation_criteria[validation_index].get("query", "Unknown") if validation_criteria and 0 <= validation_index < len(validation_criteria) else "Unknown"
                            feedback_parts.append(f"[Criteria {validation_index}: {criteria_query[:50]}...] {result.get('feedback')}")
                
                # Calculate aggregate score
                num_results = len(processed_results) if processed_results else 1
                aggregate_score = total_score / num_results
                
                # Determine validation passed status (threshold: 0.7)
                validation_passed = aggregate_score >= 0.7
                
                # Compile validation feedback
                validation_feedback = "; ".join(feedback_parts) if feedback_parts else "Validation completed."
                
                # Build final response
                final_validation_data = {
                    "validation_results": processed_results,
                    "aggregate_score": round(aggregate_score, 3),
                    "validation_passed": validation_passed,
                    "validation_feedback": validation_feedback,
                    "matched_patterns_count": matched_patterns_count
                }
                
                log.info(f"Validation completed - Aggregate Score: {aggregate_score:.3f}, Passed: {validation_passed}, Matched Patterns: {matched_patterns_count}")

                # Modified the response
                llm_response.content.parts[0].text = json.dumps(final_validation_data)

            except json.JSONDecodeError as json_error:
                log.error(f"Failed to parse validator response as JSON: {json_error}")
                # Return a fallback response
                fallback_response = {
                    "validation_results": [{
                        "validation_index": -1,
                        "validation_status": "error",
                        "validation_score": 0.3,
                        "feedback": f"Failed to parse validation response: {str(json_error)}",
                        "validation_type": "parse_error"
                    }],
                    "aggregate_score": 0.3,
                    "validation_passed": False,
                    "validation_feedback": f"Validation parsing error: {str(json_error)}",
                    "matched_patterns_count": 0
                }

                llm_response.content.parts[0].text = json.dumps(fallback_response)

            except Exception as e:
                log.error(f"Error in after_validator_model_callback: {e}")
                # Return original response if processing fails
                return None

        return _after_validator_model_callback

    # --- Get Common Agent Instance Methods ---

    @staticmethod
    async def get_plan_verifier_agent(llm: LiteLlm, agent_name: str, plan_verifier_flag: bool = False) -> LlmAgent:
        """
        Creates and returns a plan verifier LlmAgent.
        """
        async def get_user_approval_or_feedback():
            """
            Use this tool to get the user approval or feedback for the generated plan.
            If user does not approves the plan, they provide feedback for re-planning.
            """
            return None

        async def exit_replanner_loop(tool_context: ToolContext) -> Dict[str, Any]:
            """
            Signal the workflow to terminate once the planning phase is finalized.
            Use this tool ONLY when:
            - There is no plan to verify (i.e the plan is an empty list), or
            - The current plan has been reviewed and explicitly approved.

            Args:
                tool_context: Context for tool execution

            Returns:
                Empty dictionary
            """
            tool_context.actions.escalate = True
            return {}

        plan_verifier_agent_system_prompt = """\
You are the Plan Verification Agent.

Goal:
Decide whether to request user approval for a newly generated plan or terminate verification.

State:
- plan: May be a dict with key 'plan' or a direct list of steps.
- plan_feedback: When equal to 'approved' the plan is already approved.

Logic:
1. If plan is missing, is an empty list, or plan_feedback == 'approved' -> call exit_replanner_loop.
2. Otherwise (non-empty plan and not yet approved) -> call get_user_approval_or_feedback.
3. If get_user_approval_or_feedback returns 'approved' -> call exit_replanner_loop.
4. If get_user_approval_or_feedback returns some feedback -> pass it on to replanner agent.
5. Never modify or execute the plan. Only ask for approval or exit.

Plan:
{plan?}
"""

        plan_verifier_agent = LlmAgent(
            name=f"plan_verifier_for_{agent_name}",
            model=llm,
            instruction=plan_verifier_agent_system_prompt,
            tools=[LongRunningFunctionTool(func=get_user_approval_or_feedback), exit_replanner_loop],
            before_model_callback=await BaseAgentGADKInference.get_before_plan_verifier_model_callback_function(plan_verifier_flag=plan_verifier_flag)
        )
        return plan_verifier_agent

    @staticmethod
    async def get_online_evaluator_agent(llm: LiteLlm, agent_name: str, description: str = "") -> LlmAgent:
        # Create Evaluator Agent with GADK-compatible prompt
        evaluator_system_prompt = f"""\
{GADK_EVALUATION_PROMPT}

**Additional Context**:
- Agent Name: {agent_name}
- Agent Description: {description}
"""

        return LlmAgent(
            name=f"evaluator_for_{agent_name}",
            model=llm,
            instruction=evaluator_system_prompt,
            output_schema=EvaluationSchema,
            output_key="evaluation_result"
        )

    async def get_validator_agent(self, llm: LiteLlm, agent_name: str, validation_criteria: List[dict] = None) -> LlmAgent:
        """
        Creates and returns a validator LlmAgent.
        
        The validator agent evaluates responses against defined validation criteria or performs
        general relevancy validation when no criteria match the query.
        
        Args:
            llm: The LiteLlm model instance
            agent_name: Name of the agent being validated
            validation_criteria: List of validation criteria dictionaries containing:
                - query: The query pattern to match
                - validator: Tool ID (optional) for custom validation
                - expected_answer: Expected behavior description
                
        Returns:
            LlmAgent: The configured validator agent
        """
        # Build validation criteria string for the prompt
        criteria_str = "No specific validation criteria defined for this agent go ahead with General relevancy assessment."
        if validation_criteria:
            criteria_str = ""
            for idx, criteria in enumerate(validation_criteria):
                query_pattern = criteria.get("query", "N/A")
                expected_answer = criteria.get("expected_answer", "N/A")
                criteria_str += f"""\n{idx}. Query Pattern: {query_pattern}
   Expected Behavior: {expected_answer}\n"""

        validator_agent_system_prompt = GADK_VALIDATOR_AGENT_SYSTEM_PROMPT.format(criteria_str=criteria_str)

        # Get the after_model_callback for processing validation results
        after_validator_model_callback = await self.get_after_validator_model_callback(validation_criteria)

        return LlmAgent(
            name=f"validator_for_{agent_name}",
            model=llm,
            instruction=validator_agent_system_prompt,
            output_schema=ValidationSchema,
            output_key="validation_result",
            after_model_callback=after_validator_model_callback
        )

    @staticmethod
    async def get_canvas_formatter_agent(llm: LiteLlm) -> LlmAgent:
        """
        Creates and returns a canvas formatter LlmAgent.
        """
        async def before_canvas_agent_callback(callback_context: CallbackContext):
            state = callback_context.state
            response = state.get("response", "")
            if isinstance(response, dict) and "response" in response:
                response = response["response"]
            state["response"] = response

        canvas_formatter_agent_system_prompt = f"""\
{FORMATTER_PROMPT}

**IMPORTANT**: Focus only on formatting the response the we get for the user query, ignore all other sub-agent responses like planner, critic etc if there are any.
"""

        return LlmAgent(
            name="formatter_for_canvas_view",
            model=llm,
            instruction=canvas_formatter_agent_system_prompt,
            output_schema=CanvasFormatSchema,
            before_agent_callback=before_canvas_agent_callback,
            output_key="canvas_parts",
            include_contents="none"
        )

    async def get_quality_assessment_agent(
        self,
        llm: LiteLlm,
        agent_name: str,
        *,
        evaluation_flag: bool = False,
        validator_flag: bool = False,
        validation_criteria: List[dict] = None,
        description: str = "",
        inference_config: AdminConfigLimits = AdminConfigLimits()
    ) -> List[BaseAgent]:
        """
        Creates and returns a list of quality assessment agents (evaluator and/or validator) based on the provided flags.
        Args:
            llm: The LiteLlm model instance
            agent_name: Name of the agent being assessed
            evaluation_flag: Whether to include an evaluator agent
            validator_flag: Whether to include a validator agent
            validation_criteria: List of validation criteria for the validator agent
            description: Description of the agent being assessed
            inference_config: AdminConfigLimits = AdminConfigLimits()
        Returns:
            List[BaseAgent]: List of quality assessment agents
        """
        quality_assessment_agents: List[BaseAgent] = []

        if validator_flag:
            validator_agent = await self.get_validator_agent(llm=llm, agent_name=agent_name, validation_criteria=validation_criteria)
            quality_assessment_agents.append(validator_agent)

        if evaluation_flag:
            evaluator_agent = await self.get_online_evaluator_agent(llm=llm, agent_name=agent_name, description=description)
            quality_assessment_agents.append(evaluator_agent)

        if quality_assessment_agents:
            max_iterations = max(
                inference_config.max_evaluation_epochs if evaluation_flag else 0,
                inference_config.max_validation_epochs if validator_flag else 0
            )
            after_agent_callback = await self.get_after_quality_assessment_agent_callback(
                            evaluation_threshold=inference_config.evaluation_score_threshold,
                            validation_threshold=inference_config.validation_score_threshold,
                            max_iterations=max_iterations
                        )
            quality_assessment_agents[-1].after_agent_callback = after_agent_callback

        return quality_assessment_agents

    # Abstract Methods

    @abstractmethod
    async def _build_agent_and_chains(self, llm: LiteLlm, agent_config: dict, tool_interrupt_flag: bool = False, tools_to_interrupt: Optional[List[str]] = None) -> dict:
        """
        Abstract method to build the agent and chains for a specific agent type.
        """
        pass

    @abstractmethod
    async def _build_workflow(self, chains: dict, flags: Dict[str, bool] = {}) -> BaseAgent:
        """
        Abstract method to build the workflow for a specific agent type.
        """
        pass

    # Common Inference Method

    async def _ainvoke(
                    self,
                    runner_app: Runner,
                    session: Session,
                    query: Optional[str] = None,
                    *,
                    is_plan_approved: Literal["yes", "no", None] = None,
                    plan_feedback: Optional[str] = None,
                    tool_feedback: Optional[str] = None
                ):
        """
        Asynchronously invokes the agent application with the provided input and configuration.
        """
        if is_plan_approved == "no" and not plan_feedback:
            log.info("Invalid case, returning empty response.")
            return {
                "query": query or "",
                "response": "",
                "steps": []
            }

        run_async_params = {
            "user_id": session.user_id,
            "session_id": session.id,
            "new_message": None,
            "state_delta": None,
            "invocation_id": None,
        }

        if not is_plan_approved and not tool_feedback:
            run_async_params["new_message"] = await self.get_formatted_gadk_content(query=query)
            parts_list = run_async_params["new_message"].parts
            if len(parts_list) == 2 and parts_list[0].text == "FEEDBACK:":
                query = parts_list[1].text
                log.info("Processing user feedback for regeneration.")

            episodic_memory_context = ""
            context_messages = await InferenceUtils.prepare_episodic_memory_context(agent_id=session.app_name, query=query)
            if context_messages and isinstance(context_messages, list) and len(context_messages) >= 3:
                episodic_memory_context = f"""
**Episodic Memory Context (Previous similar interactions)**:
{context_messages[0].get("content", "")}

Use positive examples as guidance and explicitly avoid negative examples.
"""

            run_async_params["state_delta"] = {
                "query": query,
                "response": "",
                "episodic_memory_context": episodic_memory_context
            }
            log.info("No plan approval feedback provided, proceeding with user query.")

        elif tool_feedback:
            log.info("Processing tool execution feedback.")
            function_call_event = await self.get_last_pending_function_call_event(events=session.events, function_name="adk_request_confirmation")
            function_call_part = function_call_event.content.parts[0].function_call
            if tool_feedback.lower() == "yes":
                tool_feedback = "null"
            feedback_content = f'{{"confirmed": true, "payload": {tool_feedback}}}'

            run_async_params["new_message"] = await self.get_formatted_gadk_content(
                                                    function_response={
                                                        "id": function_call_part.id,
                                                        "name": function_call_part.name,
                                                        "response": feedback_content
                                                    }
                                                )
            run_async_params["invocation_id"] = function_call_event.invocation_id

        else:
            log.info("Processing plan approval or feedback.")
            function_call_event = await self.get_last_pending_function_call_event(session.events)
            function_call_part = function_call_event.content.parts[0].function_call
            feedback_content = "Approved" if is_plan_approved == "yes" else plan_feedback

            run_async_params["new_message"] = await self.get_formatted_gadk_content(
                                                    function_response={
                                                        "id": function_call_part.id,
                                                        "name": function_call_part.name,
                                                        "result": feedback_content
                                                    }
                                                )
            run_async_params["state_delta"] = {"plan_feedback": feedback_content}
            run_async_params["invocation_id"] = function_call_event.invocation_id


        response: List[Content] = [run_async_params["new_message"]]

        response_stream = runner_app.run_async(**run_async_params)

        print("|"*10, " Streaming Response Started ", "|"*10, "\n")
        async for event in response_stream:
            if event.content:
                print(event.content)
                response.append(event.content)
                print("==="*30, "\n")
        print("|"*10, " Streaming Response Ended ", "|"*10, "\n")

        if not response:
            return {"error": "Invalid parameters provided for ainvoke."}

        return {
            "query": query or "",
            "response": "",
            "steps": response
        }

    async def _astream(
                    self,
                    runner_app: Runner,
                    session: Session,
                    query: Optional[str] = None,
                    *,
                    is_plan_approved: Literal["yes", "no", None] = None,
                    plan_feedback: Optional[str] = None,
                    tool_feedback: Optional[str] = None
                ) -> AsyncGenerator[Dict[str, Any], None]:
        """
        Asynchronously streams events from the agent application, yielding each event 
        and optionally sending them to SSE for real-time client updates.
        
        Args:
            runner_app: Google ADK Runner instance
            session: Current session object
            query: User query string
            is_plan_approved: Plan approval status ('yes', 'no', or None)
            plan_feedback: Feedback for plan modification
            tool_feedback: Feedback for tool execution

        Yields:
            Dictionary containing parsed event data for each step
        """
        if is_plan_approved == "no" and not plan_feedback:
            log.info("Invalid case, returning empty response.")
            return

        run_async_params = {
            "user_id": session.user_id,
            "session_id": session.id,
            "new_message": None,
            "state_delta": None,
            "invocation_id": None,
        }


        yield await self._create_sse_status_event("Agent", "Started", {"content": "Processing your request..."})
        # Send initial status event
        if not is_plan_approved and not tool_feedback:
            run_async_params["new_message"] = await self.get_formatted_gadk_content(query=query)
            parts_list = run_async_params["new_message"].parts
            if len(parts_list) == 2 and parts_list[0].text == "FEEDBACK:":
                query = parts_list[1].text
                log.info("Processing user feedback for regeneration.")

            episodic_memory_context = ""
            context_messages = await InferenceUtils.prepare_episodic_memory_context(agent_id=session.app_name, query=query)
            if context_messages and isinstance(context_messages, list) and len(context_messages) >= 3:
                episodic_memory_context = f"""
**Episodic Memory Context (Previous similar interactions)**:
{context_messages[0].get("content", "")}

Use positive examples as guidance and explicitly avoid negative examples.
"""

            run_async_params["state_delta"] = {
                "query": query,
                "response": "",
                "episodic_memory_context": episodic_memory_context
            }
            log.info("No plan approval feedback provided, proceeding with user query.")

        elif tool_feedback:
            log.info("Processing tool execution feedback.")
            function_call_event = await self.get_last_pending_function_call_event(events=session.events, function_name="adk_request_confirmation")
            function_call_part = function_call_event.content.parts[0].function_call
            if tool_feedback.lower() == "yes":
                tool_feedback = "null"
            feedback_content = f'{{"confirmed": true, "payload": {tool_feedback}}}'

            run_async_params["new_message"] = await self.get_formatted_gadk_content(
                                                    function_response={
                                                        "id": function_call_part.id,
                                                        "name": function_call_part.name,
                                                        "response": feedback_content
                                                    }
                                                )
            run_async_params["invocation_id"] = function_call_event.invocation_id

        else:
            log.info("Processing plan approval or feedback.")
            function_call_event = await self.get_last_pending_function_call_event(session.events)
            function_call_part = function_call_event.content.parts[0].function_call
            feedback_content = "Approved" if is_plan_approved == "yes" else plan_feedback

            run_async_params["new_message"] = await self.get_formatted_gadk_content(
                                                    function_response={
                                                        "id": function_call_part.id,
                                                        "name": function_call_part.name,
                                                        "result": feedback_content
                                                    }
                                                )
            run_async_params["state_delta"] = {"plan_feedback": feedback_content}
            run_async_params["invocation_id"] = function_call_event.invocation_id


        try:
            response_stream = runner_app.run_async(**run_async_params)

            log.info("Streaming Response Started")
            yield await self._create_sse_status_event("Thinking...", "Started")

            async for event in response_stream:
                if event.content:
                    # Parse event for SSE streaming
                    sse_event = await self._parse_gadk_event_for_sse(event)
                    if sse_event:
                        # Set status to Completed for content events (avoid duplicate yields)
                        if sse_event.get("Status") == "Thinking":
                            sse_event["Status"] = "Completed"
                        yield sse_event
                    log.debug(f"Streamed event: {sse_event}")
            log.info("Streaming Response Ended")

            yield await self._create_sse_status_event("Thinking...", "Completed")
            yield await self._create_sse_status_event("Agent", "Completed", {"content": "Response generated successfully"})

        except Exception as e:
            log.error(f"Error during streaming: {e}", exc_info=True)
            error_event = {
                "error": f"Streaming error: {str(e)}",
                "Node Name": "Agent",
                "Status": "Error"
            }
            yield error_event

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

                                tool_interrupt_flag: bool = False,
                                tools_to_interrupt: Optional[List[str]] = None,
                                tool_feedback: str = None,

                                response_formatting_flag:bool = True,
                                context_flag: bool = True,
                                evaluation_flag: bool = False,
                                validator_flag: bool = False,

                                temperature: float = 0.0,
                                enable_streaming_flag: bool = False,

                                inference_config: AdminConfigLimits = AdminConfigLimits()
                            ) -> AsyncGenerator[Dict[str, Any], None]:
        if not plan_verifier_flag:
            is_plan_approved = plan_feedback = None

        llm = await self.model_service.get_llm_model_using_google_adk(model_name=model_name, temperature=temperature)
        agent_resp = {}

        if reset_conversation:
            try:
                await self._delete_adk_session(agent_id=agentic_application_id, session_id=session_id)
                log.info(f"Conversation history for session {session_id} has been reset.")
            except Exception as e:
                log.error(f"Error occurred while resetting conversation: {e}")

        log.debug("Building agent and chains")
        agent_config["inference_config"] = inference_config
        chains_and_metadata = await self._build_agent_and_chains(
            llm=llm,
            agent_config=agent_config,
            tool_interrupt_flag=tool_interrupt_flag,
            tools_to_interrupt=tools_to_interrupt
        )
        chains_and_metadata["validation_criteria"] = agent_config.get("VALIDATION_CRITERIA", [])

        flags_and_config = {
            "tool_interrupt_flag": tool_interrupt_flag,
            "plan_verifier_flag": plan_verifier_flag,
            "response_formatting_flag": response_formatting_flag,
            "context_flag": context_flag,
            "evaluation_flag": evaluation_flag,
            "validator_flag": validator_flag,

            "inference_config": inference_config
        }
        log.debug("Building workflow")
        root_agent = await self._build_workflow(chains_and_metadata, flags_and_config)
        log.debug("Workflow built successfully")

        runner_app, current_session = await self._get_gadk_runner_instance(root_agent, agentic_application_id, session_id)
        log.debug("GADK Runner instance created successfully")

        log.info(f"Invoking executor agent for query: {query}\n with Session ID: {session_id} and Agent Id: {agentic_application_id}")
        with using_project(project_name):
            try:
                if enable_streaming_flag:
                    # Use streaming mode - yield events as they come
                    streamer = self._astream(
                        runner_app=runner_app,
                        session=current_session,
                        query=query,
                        is_plan_approved=is_plan_approved,
                        plan_feedback=plan_feedback,
                        tool_feedback=tool_feedback,
                    )
                    async for step in streamer:
                        yield step
                    
                    log.info(f"Agent streaming completed for query: {query} with session ID: {session_id}")
                else:
                    # Use batch mode - wait for complete response
                    agent_resp = await self._ainvoke(
                        runner_app=runner_app,
                        session=current_session,
                        query=query,
                        is_plan_approved=is_plan_approved,
                        plan_feedback=plan_feedback,
                        tool_feedback=tool_feedback
                    )

                    log.info(f"Agent invoked successfully for query: {query} with session ID: {session_id}")
                    yield agent_resp

            except Exception as e:
                log.error(f"Error occurred during agent inference: {e}", exc_info=True)
                yield {"error": f"Error during inference: {str(e)}"}

    async def run(self,
                  inference_request: AgentInferenceRequest,
                  *,
                  agent_config: Optional[Union[dict, None]] = None,
                  insert_into_eval_flag: bool = True,
                  **kwargs
                ) -> AsyncGenerator[Dict[str, Any], None]:
        """
        Runs the Agent inference workflow.

        Args:
            request (AgentInferenceRequest): The request object containing all necessary parameters.
            agent_config: Optional pre-loaded agent configuration
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
            tools_to_interrupt = inference_request.interrupt_items
            tool_feedback = inference_request.tool_feedback

            plan_verifier_flag = inference_request.plan_verifier_flag
            is_plan_approved = inference_request.is_plan_approved
            plan_feedback = inference_request.plan_feedback

            response_formatting_flag = inference_request.response_formatting_flag
            context_flag = inference_request.context_flag
            evaluation_flag = inference_request.evaluation_flag
            validator_flag = inference_request.validator_flag
            enable_streaming_flag = inference_request.enable_streaming_flag
            temperature = inference_request.temperature

            inference_config = await self.admin_config_service.get_limits()

            user_name = self._extract_user_email_from_session_id(session_id=session_id)
            agent_name = agent_config["AGENT_NAME"]
            project_name = agent_name + '_' + user_name

            register(
                project_name=project_name,
                auto_instrument=True,
                set_global_tracer_provider=False,
                batch=True
            )

            update_session_context(agent_type=agent_config["AGENT_TYPE"], agent_name=agent_name)

            # For react agent, we need to add knowledge base retriever tool if knowledgebase_name is provided
            if agent_config["AGENT_TYPE"] == AgentType.REACT_AGENT and hasattr(inference_request, "knowledgebase_name") and inference_request.knowledgebase_name:
                knowledgebase_retriever_tool = await self.tool_service.get_tool(tool_name="knowledgebase_retriever")
                knowledgebase_retriever_id = knowledgebase_retriever_tool[0]["tool_id"] if knowledgebase_retriever_tool else None
                if not knowledgebase_retriever_id:
                    log.error("Knowledge Base Retriever tool not found. Please ensure it is registered in the system. Proceeding without it.")

                else:
                    agent_config['TOOLS_INFO'].append(knowledgebase_retriever_id)
                    agent_config['SYSTEM_PROMPT']['SYSTEM_PROMPT_REACT_AGENT'] += f"\n\nUse Knowledge Base: {inference_request.knowledgebase_name} regarding the query and if any useful information found use it and pass it to any tools if no useful content is extracted call use the agent as if the knowledgebase tool is not existing, but use the instructions for each of tools and execute the query."

            # Generate response using the agent workflow
            response_generator = self._generate_response(
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

                tool_interrupt_flag=tool_interrupt_flag,
                tools_to_interrupt=tools_to_interrupt,
                tool_feedback=tool_feedback,

                response_formatting_flag=response_formatting_flag,
                context_flag=context_flag,
                evaluation_flag=evaluation_flag,
                validator_flag=validator_flag,

                temperature=temperature,
                enable_streaming_flag=enable_streaming_flag,

                inference_config=inference_config
            )

            # If streaming is enabled, yield intermediate events
            if enable_streaming_flag:
                async for step in response_generator:
                    # Yield intermediate streaming events (for SSE)
                    yield step
                    # The last yielded item is the aggregated response
                    agent_response = step
            else:
                # Non-streaming mode: consume generator to get final response
                async for step in response_generator:
                    agent_response = step

            user_id = self._extract_user_email_from_session_id(session_id=session_id)
            current_chat_session = await self.gadk_session_service.get_session(user_id=user_id, app_name=agentic_application_id, session_id=session_id)

            log.info(f"Formatting final response for session ID: {session_id}")
            final_formatted_response = await self.chat_service._format_google_adk_agent_history(current_chat_session)
            final_formatted_response["model_name"] = model_name
            final_formatted_response["reset_conversation"] = reset_conversation
            final_formatted_response["response_formatting_flag"] = response_formatting_flag
            final_formatted_response["context_flag"] = context_flag
            final_formatted_response["is_tool_interrupted"] = tool_interrupt_flag
            final_formatted_response["workflow_description"] = agent_config.get("WORKFLOW_DESCRIPTION", "")
            log.info(f"Final response formatted successfully for session ID: {session_id}")

            if insert_into_eval_flag:
                eval_executor_messages = []
                log.info("Preparing executor messages for evaluation logging.")
                for exe_msg in final_formatted_response.get("executor_messages", []):
                    eval_executor_messages.append({
                        "user_query": exe_msg["user_query"],
                        "final_response": exe_msg["final_response"],
                        "agent_steps": list(reversed(exe_msg["additional_details"]))
                    })

                response_evaluation = {
                    "query": final_formatted_response["query"],
                    "response": final_formatted_response["response"],
                    "executor_messages": eval_executor_messages
                }

                try:
                    log.info("Inserting evaluation data for Google ADK inference into the database.")
                    asyncio.create_task(self.evaluation_service.log_evaluation_data(session_id, agentic_application_id, agent_config, response_evaluation, model_name))
                except Exception as e:
                    log.error(f"Error Occurred while inserting into evaluation data of Google ADK inference: {e}")

            yield final_formatted_response

        except Exception as e:
            # Catch any unhandled exceptions and raise a 500 internal server error
            log.error(f"Error Occurred in agent inference: {e}")
            raise HTTPException(status_code=500, detail=f"Internal Server Error: {str(e)}")


