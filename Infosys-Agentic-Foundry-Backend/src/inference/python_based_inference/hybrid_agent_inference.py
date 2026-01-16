# © 2024-25 Infosys Limited, Bangalore, India. All Rights Reserved.
import asyncio
from typing import Any, Dict, Optional, Literal, AsyncGenerator
from fastapi import HTTPException

from src.models.base_ai_model_service import BaseAIModelService
from src.inference.inference_utils import InferenceUtils
from src.inference.python_based_inference.base_python_based_agent_inference import BasePythonBasedAgentInference
from src.utils.helper_functions import get_timestamp

from telemetry_wrapper import logger as log
from src.utils.phoenix_manager import traced_project_context_sync


class HybridAgentInference(BasePythonBasedAgentInference):
    """
    A hybrid AI agent inference class that combines various services to process user queries.
    """

    def __init__(self, inference_utils: InferenceUtils):
        super().__init__(inference_utils=inference_utils)


    async def _build_agent_and_chains(self, llm: BaseAIModelService, agent_config: Dict) -> Dict[str, Any]:
        """
        Builds the agent and chains for the Hybrid Agent.
        """
        tool_ids = agent_config["TOOLS_INFO"]
        system_prompt = agent_config["SYSTEM_PROMPT"]

        # Use the common helper to get the agent instance
        hybrid_agent, _ = await self._get_python_based_agent_instance(
                                        llm,
                                        system_prompt=system_prompt.get("SYSTEM_PROMPT_HYBRID_AGENT", ""),
                                        tool_ids=tool_ids
                                    )
        chains = {
            "llm": llm,
            "hybrid_agent": hybrid_agent,
            "agent": hybrid_agent # Use generic name 'agent'
        }
        log.info("Built Hybrid Agent successfully")
        return chains

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
        # Record start timestamp for response time tracking
        start_timestamp = get_timestamp()
        
        thread_id = await self.chat_service._get_thread_id(agentic_application_id, session_id)
        
        # Construct config for ainvoke method of BaseAIModelService
        config = {
            "configurable": {
                "thread_id": thread_id,
                "history_lookback": 8 if context_flag else 0,
                "resume_previous_chat": False,
                "store_response_custom_metadata": True
            },
            "tool_choice": "auto",
            "tool_interrupt": tool_interrupt_flag,
            "updated_tool_calls": tool_feedback
        }

        previous_response_feedback_type: Optional[str] = None

        if reset_conversation:
            try:
                await self.chat_state_history_manager.clear_chat_history(thread_id)
                log.info(f"Conversation history for session {session_id} has been reset.")
            except Exception as e:
                log.error(f"Error occurred while resetting conversation: {e}")

        elif query == "[regenerate:][:regenerate]":
            previous_response_feedback_type = "regenerate"
            query = "The previous response did not met user expectations. Please review the query and provide a new, more accurate response."

        elif query.startswith("[feedback:]") and query.endswith("[:feedback]"):
            previous_response_feedback_type = "feedback"
            query = f"""The previous response was not satisfactory. Here is the feedback on your previous response:
{query[11:-11]}

Please review the query and feedback, and provide an appropriate answer.
"""

        llm = await self.model_service.get_llm_model_using_python(model_name=model_name, temperature=temperature)
        chains = await self._build_agent_and_chains(llm, agent_config)
        app: BaseAIModelService = chains.get("hybrid_agent", None)
        if not app:
            log.error("Agent instance not found in chains.")
            raise HTTPException(status_code=500, detail="Agent instance not found in chains.")

        app._temperature = temperature
        log.info("Agent build successfully")

        log.info(f"Invoking agent for query: {query}\n with Session ID: {session_id} and Agent Id: {agentic_application_id}")
        with traced_project_context_sync(project_name):
            try:
                # Track user updates to tool arguments for this query
                user_update_events: list = []
                if query:
                    messages = [app.format_content_with_role(query)]
                    if previous_response_feedback_type:
                        config["configurable"]["resume_previous_chat"] = True
                        messages[0]["previous_response_feedback_type"] = previous_response_feedback_type

                    if evaluation_flag:
                        messages[0]["online_evaluation_epoch"] = 1

                else:
                    messages = None     # Incase of tool interrupt


                # Plan Verification Handling
                if not is_plan_approved:
                    config["tool_choice"] = "none"

                    if context_flag and query:
                        context_messages = await InferenceUtils.prepare_episodic_memory_context(agentic_application_id, query)
                        if context_messages and  isinstance(context_messages, list) and len(context_messages) >= 3:
                            messages.extend(context_messages)

                elif is_plan_approved.lower() == "yes":
                    config["configurable"]["resume_previous_chat"] = True
                    messages = None

                elif is_plan_approved.lower() == "no" and plan_feedback:
                    config["tool_choice"] = "none"
                    config["configurable"]["resume_previous_chat"] = True
                    feedback_content = f"The previous plan was not approved by user.\nUSER FEEDBACK: {plan_feedback}.\n\nPlease generate a revised plan based on user feedback."
                    
                    messages = [app.format_content_with_role(feedback_content)]

                else:
                    log.info("No invocation required.")
                    return await self.chat_state_history_manager.get_recent_history(thread_id=thread_id)

                # If there are no messages (tool interrupt or plan approved), set tool_choice to auto
                if not messages:
                    config["tool_choice"] = "auto"

                # Record tool feedback updates into user_update_events and augment the initial query
                try:
                    if tool_interrupt_flag and tool_feedback and tool_feedback != "yes":
                        import json as _json
                        parsed = _json.loads(tool_feedback)
                        event = {
                            "tool_name": parsed.get("name", "unknown"),
                            "old_args": None,
                            "new_args": parsed,
                            "message": f"User modified tool arguments: {tool_feedback}",
                            "query": query,
                        }
                        user_update_events.append(event)
                except Exception:
                    # Ignore malformed feedback; proceed without recording
                    pass

                # If we have an initial user message and recorded updates, append them for evaluator/agent awareness
                if messages and user_update_events:
                    updates_lines = []
                    for ev in user_update_events:
                        if ev.get("query") and ev.get("query") != query:
                            continue
                        updates_lines.append(
                            f"message : {ev.get('message','N/A')}\n"
                        )
                    if updates_lines:
                        updates_block = "\n".join(updates_lines)
                        # messages[0] is a dict formatted by format_content_with_role
                        content_key = "content" if "content" in messages[0] else next((k for k in messages[0].keys() if isinstance(messages[0][k], str)), None)
                        if content_key:
                            messages[0][content_key] = (
                                f"{messages[0][content_key]}\n\n--- User Tool Feedback Updates ---\n{updates_block}\n--- End Updates ---"
                            )


                evaluation_score = 0.0      # Initial score
                evaluation_threshold = 0.7  # Configurable threshold
                max_evaluation_epochs = 3   # Maximum number of evaluation improvement cycles

                while evaluation_score < evaluation_threshold:

                    agent_resp = await app.ainvoke(messages=messages, config=config)

                    response_custom_metadata = agent_resp["agent_steps"][-1].get("response_custom_metadata", {})
                    if response_custom_metadata and "plan" in response_custom_metadata:
                        if not plan_verifier_flag:
                            config["tool_choice"] = "auto"
                            config["configurable"]["resume_previous_chat"] = True
                            agent_resp = await app.ainvoke(messages=None, config=config)
                        else:
                            break   # plan verifier state - no evaluation needed


                                            # tool verifier state - no evaluation needed
                    if not evaluation_flag or "tool_calls" in agent_resp["agent_steps"][-1] or not agent_resp["final_response"]:
                        break

                    try:
                        # Build effective query with user_update_events for evaluator awareness
                        effective_query = query
                        if user_update_events:
                            updates_lines = []
                            for ev in user_update_events:
                                if ev.get("query") and ev.get("query") != query:
                                    continue
                                tool_name = ev.get('tool_name', 'unknown')
                                old_args = ev.get('old_args', 'N/A')
                                new_args = ev.get('new_args', {})
                                
                                # Format the arguments clearly
                                if isinstance(new_args, dict):
                                    args_str = ', '.join(f"{k}={v}" for k, v in new_args.get('arguments', new_args).items() if k != 'name')
                                    if not args_str:  # If arguments key doesn't exist, try direct keys
                                        args_str = ', '.join(f"{k}={v}" for k, v in new_args.items() if k != 'name')
                                else:
                                    args_str = str(new_args)
                                
                                updates_lines.append(
                                    f"- Tool: {tool_name}\n"
                                    f"  Modified Arguments: {args_str}\n"
                                    f"  Note: {ev.get('message', 'User modified tool arguments')}"
                                )
                            
                            if updates_lines:
                                updates_block = "\n".join(updates_lines)
                                effective_query = (
                                    f"{query}\n\n"
                                    f"--- IMPORTANT: User Tool Feedback Updates ---\n"
                                    f"The user modified the following tool arguments during execution:\n\n"
                                    f"{updates_block}\n\n"
                                    f"EVALUATION INSTRUCTION: Evaluate the response based on the MODIFIED tool arguments shown above, "
                                    f"NOT the original query. The agent correctly executed with the user's updated arguments.\n"
                                    f"--- End Updates ---"
                                )
                        
                        # Temporarily update agent_resp with effective query for evaluation
                        original_query = agent_resp["user_query"]
                        agent_resp["user_query"] = effective_query
                        
                        evaluation_results = await self.evaluate_agent_response(agent_response=agent_resp, llm=llm)
                        
                        # Restore original query
                        agent_resp["user_query"] = original_query
                        
                        await self._add_additional_data_to_final_response(
                                data={"online_evaluation_results": evaluation_results},
                                thread_id=thread_id
                            )

                        current_epoch = await self._get_epoch_value(agent_steps=agent_resp["agent_steps"], key="online_evaluation_epoch")
                        if current_epoch >= max_evaluation_epochs or "error" in evaluation_results:
                            log.info(f"Maximum evaluation epochs {max_evaluation_epochs} reached. Stopping further evaluations.")
                            break

                        evaluation_score = evaluation_results.get("evaluation_score")
                        evaluation_feedback = evaluation_results.get("evaluation_feedback")

                        # Reset any in-progress tool interruption so the agent retries from a fresh state
                        messages = [llm.format_content_with_role(evaluation_feedback, online_evaluation_epoch=current_epoch+1)]
                        config["configurable"]["resume_previous_chat"] = True
                        # Mirror other workflows: ensure tool interruption does not persist across evaluation epochs
                        config["tool_interrupt"] = False
                        # Also prefer not to automatically choose tools during retry; keep control explicit
                        config["tool_choice"] = "none"

                    except Exception as e:
                        log.error(f"Error during evaluation: {e}. Proceeding without further evaluations.")
                        break


                try:
                    agent_steps = agent_resp.get("agent_steps")
                    response_custom_metadata = agent_steps[-1].get("response_custom_metadata", {})
                    final_response_generated_flag = bool(agent_resp["final_response"]) and "plan" not in response_custom_metadata and "tool_calls" not in agent_steps[-1]

                    # Record end timestamp when final response is generated
                    end_timestamp = None
                    response_time = None
                    if final_response_generated_flag:
                        end_timestamp = get_timestamp()
                        # Calculate response time in seconds
                        response_time = (end_timestamp - start_timestamp).total_seconds()
                        asyncio.create_task(
                            self.chat_service.save_chat_message(
                                agentic_application_id=agentic_application_id,
                                session_id=session_id,
                                start_timestamp=start_timestamp,
                                end_timestamp=end_timestamp,
                                human_message=agent_resp["user_query"],
                                ai_message=agent_resp["final_response"],
                                response_time=response_time
                            )
                        )
                        asyncio.create_task(
                            self.chat_service.update_preferences_and_analyze_conversation(
                                user_input=agent_resp["user_query"],
                                llm=llm,
                                agentic_application_id=agentic_application_id,
                                session_id=session_id
                            )
                        )

                    # Formatting for canvas view
                    if response_formatting_flag and final_response_generated_flag:
                        formatted_response = await self.format_final_response_for_canvas_view(
                            query=agent_resp["user_query"],
                            response=agent_resp["final_response"],
                            llm=llm
                        )

                        if formatted_response:
                            log.info("Response formatted successfully.")
                            await self._add_additional_data_to_final_response(data=formatted_response, thread_id=thread_id)

                        else:
                            log.warning("Formatted response could not be parsed as JSON. Returning unformatted response.")

                        # Attach recorded user update events (if any) to the final response metadata
                        if user_update_events:
                            try:
                                await self._add_additional_data_to_final_response(
                                    data={"user_update_events": user_update_events},
                                    thread_id=thread_id
                                )
                            except Exception as e:
                                log.warning(f"Failed to attach user_update_events: {e}")

                except Exception as e:
                    log.error(f"Error during response formatting: {e}. Returning unformatted response.")


                log.info(f"Agent invoked successfully for query: {query} with session ID: {session_id}")
                final_response = await self.chat_state_history_manager.get_recent_history(thread_id=thread_id)
                
                return final_response

            except Exception as e:
                log.error(f"Error occurred during agent invocation: {e}", exc_info=True)
                raise HTTPException(status_code=500, detail=f"Error occurred during agent invocation: {str(e)}")

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
        # Record start timestamp for response time tracking
        start_timestamp = get_timestamp()
        
        thread_id = await self.chat_service._get_thread_id(agentic_application_id, session_id)
        
        # Construct config for astream method of BaseAIModelService
        config = {
            "configurable": {
                "thread_id": thread_id,
                "history_lookback": 8 if context_flag else 0,
                "resume_previous_chat": False,
                "store_response_custom_metadata": True
            },
            "tool_choice": "auto",
            "tool_interrupt": tool_interrupt_flag,
            "updated_tool_calls": tool_feedback
        }

        previous_response_feedback_type: Optional[str] = None

        if reset_conversation:
            try:
                await self.chat_state_history_manager.clear_chat_history(thread_id)
                log.info(f"Conversation history for session {session_id} has been reset.")
            except Exception as e:
                log.error(f"Error occurred while resetting conversation: {e}")

        elif query == "[regenerate:][:regenerate]":
            previous_response_feedback_type = "regenerate"
            query = "The previous response did not met user expectations. Please review the query and provide a new, more accurate response."

        elif query.startswith("[feedback:]") and query.endswith("[:feedback]"):
            previous_response_feedback_type = "feedback"
            query = f"""The previous response was not satisfactory. Here is the feedback on your previous response:
{query[11:-11]}

Please review the query and feedback, and provide an appropriate answer.
"""

        # Yield initial status
        # yield {"Node Name": "Hybrid Agent", "Status": "Started"}

        llm = await self.model_service.get_llm_model_using_python(model_name=model_name, temperature=temperature)
        chains = await self._build_agent_and_chains(llm, agent_config)
        app: BaseAIModelService = chains.get("hybrid_agent", None)
        if not app:
            log.error("Agent instance not found in chains.")
            raise HTTPException(status_code=500, detail="Agent instance not found in chains.")

        app._temperature = temperature
        log.info("Agent build successfully")

        # Yield build completed status
        # yield {"Node Name": "Build Agent", "Status": "Completed"}

        log.info(f"Streaming agent for query: {query}\n with Session ID: {session_id} and Agent Id: {agentic_application_id}")
        with traced_project_context_sync(project_name):
            try:
                # Track user updates to tool arguments for this query
                user_update_events: list = []
                if query:
                    messages = [app.format_content_with_role(query)]
                    if previous_response_feedback_type:
                        config["configurable"]["resume_previous_chat"] = True
                        messages[0]["previous_response_feedback_type"] = previous_response_feedback_type

                    if evaluation_flag:
                        messages[0]["online_evaluation_epoch"] = 1

                else:
                    messages = None     # In case of tool interrupt


                # Plan Verification Handling
                if not is_plan_approved:
                    config["tool_choice"] = "none"

                    if context_flag and query:
                        # Yield context generation status

                        
                        context_messages = await InferenceUtils.prepare_episodic_memory_context(agentic_application_id, query)
                        log.info(f"ID_SIVA: {context_messages}")
                        if context_messages and isinstance(context_messages, list) and len(context_messages) >= 3:
                            messages.extend(context_messages)
                        
                        

                elif is_plan_approved.lower() == "yes":
                    config["configurable"]["resume_previous_chat"] = True
                    messages = None
                    yield {"raw": {"plan_verifier": "User approved the plan."}, "content": "User approved the plan. Continuing with execution."}

                elif is_plan_approved.lower() == "no" and plan_feedback:
                    yield {"raw": {"plan_verifier": "User rejected the plan and provided feedback."}, "content": "User rejected the plan and provided feedback. Regenerating the plan."}
                    config["tool_choice"] = "none"
                    config["configurable"]["resume_previous_chat"] = True
                    feedback_content = f"The previous plan was not approved by user.\nUSER FEEDBACK: {plan_feedback}.\n\nPlease generate a revised plan based on user feedback."
                    yield {"raw": {"plan_feedback": "Regenerating plan based on user feedback."}, "content": "Regenerating plan based on user feedback."}
                    messages = [app.format_content_with_role(feedback_content)]
                    

                else:
                    log.info("No invocation required.")
                    final_response = await self.chat_state_history_manager.get_recent_history(thread_id=thread_id)
                    # yield {"Node Name": "Hybrid Agent", "Status": "Completed"}
                    yield final_response
                    return

                # If there are no messages (tool interrupt or plan approved), set tool_choice to auto
                if not messages:
                    config["tool_choice"] = "auto"

                # Record tool feedback updates into user_update_events and augment the initial query
                try:
                    if tool_interrupt_flag and tool_feedback and tool_feedback != "yes":
                        import json as _json
                        parsed = _json.loads(tool_feedback)
                        event = {
                            "tool_name": parsed.get("name", "unknown"),
                            "old_args": None,
                            "new_args": parsed,
                            "message": f"User modified tool arguments: {tool_feedback}",
                            "query": query,
                        }
                        user_update_events.append(event)
                except Exception:
                    # Ignore malformed feedback; proceed without recording
                    pass

                # If we have an initial user message and recorded updates, append them for evaluator/agent awareness
                if messages and user_update_events:
                    updates_lines = []
                    for ev in user_update_events:
                        if ev.get("query") and ev.get("query") != query:
                            continue
                        updates_lines.append(
                            f"message : {ev.get('message','N/A')}\n"
                        )
                    if updates_lines:
                        updates_block = "\n".join(updates_lines)
                        content_key = "content" if "content" in messages[0] else next((k for k in messages[0].keys() if isinstance(messages[0][k], str)), None)
                        if content_key:
                            messages[0][content_key] = (
                                f"{messages[0][content_key]}\n\n--- User Tool Feedback Updates ---\n{updates_block}\n--- End Updates ---"
                            )


                evaluation_score = 0.0      # Initial score
                evaluation_threshold = 0.7  # Configurable threshold
                max_evaluation_epochs = 3   # Maximum number of evaluation improvement cycles

                agent_resp = None
                final_stream_response = None

                while evaluation_score < evaluation_threshold:
                    # Use astream instead of ainvoke for streaming status updates
                    async for stream_chunk in app.astream(messages=messages, config=config):
                        # Forward streaming status updates
                        yield stream_chunk
                        
                        # Capture the final response (contains user_query, final_response, agent_steps)
                        if "final_response" in stream_chunk or "agent_steps" in stream_chunk:
                            agent_resp = stream_chunk
                            final_stream_response = stream_chunk

                    if not agent_resp:
                        log.error("No response received from agent stream.")
                        yield {"error": "No response received from agent stream."}
                        return

                    response_custom_metadata = agent_resp.get("agent_steps", [{}])[-1].get("response_custom_metadata", {})
                    if response_custom_metadata and "plan" in response_custom_metadata:
                        # Show the generated plan with number of steps
                        plan_steps = response_custom_metadata.get("plan", [])
                        plan_count = len(plan_steps) if isinstance(plan_steps, list) else 0
                        yield {"raw": {"plan_steps": f"Generated execution plan with {plan_count} steps."}, "content": f"Generated execution plan with {plan_count} steps."}
                        
                        if not plan_verifier_flag:
                            config["tool_choice"] = "auto"
                            config["configurable"]["resume_previous_chat"] = True
                            # Continue streaming with plan approved
                            async for stream_chunk in app.astream(messages=None, config=config):
                                yield stream_chunk
                                if "final_response" in stream_chunk or "agent_steps" in stream_chunk:
                                    agent_resp = stream_chunk
                                    final_stream_response = stream_chunk
                        else:
                            # Plan verifier state - yield plan interrupt message for user confirmation
                            yield {"raw": {"plan_verifier": "Is this plan acceptable?"}, "content": "Please review the execution plan and confirm if it is acceptable."}
                            break   # plan verifier state - no evaluation needed


                    # tool verifier state - no evaluation needed
                    if not evaluation_flag or "tool_calls" in agent_resp.get("agent_steps", [{}])[-1] or not agent_resp.get("final_response"):
                        break

                    try:
                        # Build effective query with user_update_events for evaluator awareness
                        effective_query = query
                        if user_update_events:
                            updates_lines = []
                            for ev in user_update_events:
                                if ev.get("query") and ev.get("query") != query:
                                    continue
                                tool_name = ev.get('tool_name', 'unknown')
                                old_args = ev.get('old_args', 'N/A')
                                new_args = ev.get('new_args', {})
                                
                                if isinstance(new_args, dict):
                                    args_str = ', '.join(f"{k}={v}" for k, v in new_args.get('arguments', new_args).items() if k != 'name')
                                    if not args_str:
                                        args_str = ', '.join(f"{k}={v}" for k, v in new_args.items() if k != 'name')
                                else:
                                    args_str = str(new_args)
                                
                                updates_lines.append(
                                    f"- Tool: {tool_name}\n"
                                    f"  Modified Arguments: {args_str}\n"
                                    f"  Note: {ev.get('message', 'User modified tool arguments')}"
                                )
                            
                            if updates_lines:
                                updates_block = "\n".join(updates_lines)
                                effective_query = (
                                    f"{query}\n\n"
                                    f"--- IMPORTANT: User Tool Feedback Updates ---\n"
                                    f"The user modified the following tool arguments during execution:\n\n"
                                    f"{updates_block}\n\n"
                                    f"EVALUATION INSTRUCTION: Evaluate the response based on the MODIFIED tool arguments shown above, "
                                    f"NOT the original query. The agent correctly executed with the user's updated arguments.\n"
                                    f"--- End Updates ---"
                                )
                        
                        # Yield evaluation status
                       
                        yield {"Node Name": "Evaluation", "Status": "Started"}
                        
                        original_query = agent_resp.get("user_query")
                        agent_resp["user_query"] = effective_query
                        
                        evaluation_results = await self.evaluate_agent_response(agent_response=agent_resp, llm=llm)
                        
                        agent_resp["user_query"] = original_query
                        
                        await self._add_additional_data_to_final_response(
                                data={"online_evaluation_results": evaluation_results},
                                thread_id=thread_id
                            )
                        yield {"raw": {"online_evaluation_results": evaluation_results}, "content": f"Evaluation completed with score {evaluation_results.get('evaluation_score', 0)}."}
                      
                        yield {"Node Name": "Evaluation", "Status": "Completed"}
                        

                        current_epoch = await self._get_epoch_value(agent_steps=agent_resp.get("agent_steps", []), key="online_evaluation_epoch")
                        if current_epoch >= max_evaluation_epochs or "error" in evaluation_results:
                            log.info(f"Maximum evaluation epochs {max_evaluation_epochs} reached. Stopping further evaluations.")
                            break

                        evaluation_score = evaluation_results.get("evaluation_score")
                        evaluation_feedback = evaluation_results.get("evaluation_feedback")

                        # Reset for retry
                        messages = [llm.format_content_with_role(evaluation_feedback, online_evaluation_epoch=current_epoch+1)]
                        config["configurable"]["resume_previous_chat"] = True
                        config["tool_interrupt"] = False
                        config["tool_choice"] = "none"

                    except Exception as e:
                        yield {"Node Name": "Evaluation", "Status": "Failed", "Error": str(e)}
                        log.error(f"Error during evaluation: {e}. Proceeding without further evaluations.")
                        break


                try:
                    agent_steps = agent_resp.get("agent_steps", [])
                    response_custom_metadata = agent_steps[-1].get("response_custom_metadata", {}) if agent_steps else {}
                    final_response_generated_flag = bool(agent_resp.get("final_response")) and "plan" not in response_custom_metadata and "tool_calls" not in agent_steps[-1] if agent_steps else False

                    if final_response_generated_flag:
                        end_timestamp = get_timestamp()
                        response_time = (end_timestamp - start_timestamp).total_seconds()
                        asyncio.create_task(
                            self.chat_service.save_chat_message(
                                agentic_application_id=agentic_application_id,
                                session_id=session_id,
                                start_timestamp=start_timestamp,
                                end_timestamp=end_timestamp,
                                human_message=agent_resp.get("user_query"),
                                ai_message=agent_resp.get("final_response"),
                                response_time=response_time
                            )
                        )
                        asyncio.create_task(
                            self.chat_service.update_preferences_and_analyze_conversation(
                                user_input=agent_resp.get("user_query"),
                                llm=llm,
                                agentic_application_id=agentic_application_id,
                                session_id=session_id
                            )
                        )

                    # Formatting for canvas view
                    if response_formatting_flag and final_response_generated_flag:                        
                        formatted_response = await self.format_final_response_for_canvas_view(
                            query=agent_resp.get("user_query"),
                            response=agent_resp.get("final_response"),
                            llm=llm
                        )

                        if formatted_response:
                            log.info("Response formatted successfully.")
                            await self._add_additional_data_to_final_response(data=formatted_response, thread_id=thread_id)
                        else:
                            log.warning("Formatted response could not be parsed as JSON. Returning unformatted response.")

 

                        # Attach recorded user update events (if any) to the final response metadata
                        if user_update_events:
                            try:
                                await self._add_additional_data_to_final_response(
                                    data={"user_update_events": user_update_events},
                                    thread_id=thread_id
                                )
                            except Exception as e:
                                log.warning(f"Failed to attach user_update_events: {e}")

                except Exception as e:
                    log.error(f"Error during response formatting: {e}. Returning unformatted response.")


                log.info(f"Agent streaming completed for query: {query} with session ID: {session_id}")
                
                # Emit Memory Update once at the end
                if final_response_generated_flag:
                    yield {"Node Name": "Memory Update", "Status": "Started"}
                    yield {"raw": {"memory_update": "Chat history updated successfully."}, "content": "Memory updated successfully."}
                    yield {"Node Name": "Memory Update", "Status": "Completed"}
                
                # Yield completion status
                # yield {"Node Name": "Hybrid Agent", "Status": "Completed"}
                
                final_response = await self.chat_state_history_manager.get_recent_history(thread_id=thread_id)
                yield final_response

            except Exception as e:
                log.error(f"Error occurred during agent streaming: {e}", exc_info=True)
                # yield {"Node Name": "Hybrid Agent", "Status": "Failed", "Error": str(e)}
                raise HTTPException(status_code=500, detail=f"Error occurred during agent streaming: {str(e)}")







