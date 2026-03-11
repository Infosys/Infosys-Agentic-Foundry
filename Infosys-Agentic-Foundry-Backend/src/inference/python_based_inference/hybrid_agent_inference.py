# © 2024-25 Infosys Limited, Bangalore, India. All Rights Reserved.
import asyncio
from typing import Any, List, Dict, Optional, Literal, AsyncGenerator
from fastapi import HTTPException

from src.models.base_ai_model_service import BaseAIModelService
from src.inference.inference_utils import InferenceUtils
from src.inference.python_based_inference.base_python_based_agent_inference import BasePythonBasedAgentInference
from src.schemas import AdminConfigLimits
from src.config.constants import Limits
from src.utils.helper_functions import get_timestamp, build_effective_query_with_user_updates

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
                                tools_to_interrupt: Optional[List[str]] = None,
                                tool_feedback: str = None,
                                context_flag: bool = True,
                                temperature: float = 0,
                                evaluation_flag: bool = False,
                                validator_flag: bool = False,
                                inference_config: AdminConfigLimits = AdminConfigLimits()
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
                "history_lookback": Limits.PYTHON_BASED_AGENT_CHAT_HISTORY_LOOKBACK if context_flag else 0,
                "resume_previous_chat": False,
                "store_response_custom_metadata": True
            },
            "tool_choice": "auto",
            "tool_interrupt": tool_interrupt_flag,
            "tools_to_interrupt": tools_to_interrupt,
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

        log.info("Agent build successfully")

        workflow_description = agent_config.get("WORKFLOW_DESCRIPTION", "")

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
                    
                    # Load any previously saved user_update_events from chat history (from plan feedback)
                    try:
                        last_entry_id, last_entry_data = await self.chat_state_history_manager.get_most_recent_chat_entry(thread_id)
                        if last_entry_data and last_entry_data.get("agent_steps"):
                            for step in last_entry_data["agent_steps"]:
                                if isinstance(step, dict) and step.get("user_update_events"):
                                    user_update_events.extend(step["user_update_events"])
                                    log.info(f"[USER_UPDATE] Loaded {len(step['user_update_events'])} user update events from chat history")
                    except Exception as e:
                        log.warning(f"[USER_UPDATE] Failed to load user_update_events from chat history: {e}")

                elif is_plan_approved.lower() == "no" and plan_feedback:
                    config["tool_choice"] = "none"
                    config["configurable"]["resume_previous_chat"] = True
                    feedback_content = f"The previous plan was not approved by user.\nUSER FEEDBACK: {plan_feedback}.\n\nPlease generate a revised plan based on user feedback."
                    
                    messages = [app.format_content_with_role(feedback_content)]
                    
                    # Record plan feedback as user update event for validation context
                    plan_update_event = {
                        "tool_name": "plan_update",
                        "old_args": None,
                        "new_args": {"plan_feedback": plan_feedback},
                        "message": f"User rejected the plan and provided feedback: {plan_feedback}",
                        "query": query,
                    }
                    user_update_events.append(plan_update_event)
                    log.info(f"[USER_UPDATE] Recorded plan feedback event: {plan_update_event}")
                    
                    # Save user_update_events immediately to chat history (for next request when plan is approved)
                    try:
                        await self._add_additional_data_to_final_response(
                            data={"user_update_events": user_update_events},
                            thread_id=thread_id
                        )
                        log.info(f"[USER_UPDATE] Saved {len(user_update_events)} user update events to chat history")
                    except Exception as e:
                        log.warning(f"[USER_UPDATE] Failed to save user_update_events to chat history: {e}")

                else:
                    log.info("No invocation required.")
                    return await self.chat_state_history_manager.get_recent_history(thread_id=thread_id)

                # If there are no messages (tool interrupt or plan approved), set tool_choice to auto
                if not messages:
                    config["tool_choice"] = "auto"

                # Load user_update_events from chat history for tool interrupt cases
                # This ensures plan feedback context is preserved when tool interrupt happens after plan approval
                if tool_interrupt_flag and not user_update_events:
                    try:
                        last_entry_id, last_entry_data = await self.chat_state_history_manager.get_most_recent_chat_entry(thread_id)
                        if last_entry_data and last_entry_data.get("agent_steps"):
                            for step in last_entry_data["agent_steps"]:
                                if isinstance(step, dict) and step.get("user_update_events"):
                                    user_update_events.extend(step["user_update_events"])
                                    log.info(f"[USER_UPDATE] Loaded {len(step['user_update_events'])} user update events from chat history (tool interrupt)")
                    except Exception as e:
                        log.warning(f"[USER_UPDATE] Failed to load user_update_events for tool interrupt: {e}")

                # Record tool feedback updates into user_update_events and augment the initial query
                try:
                    if tool_interrupt_flag and tool_feedback and tool_feedback != "yes":
                        # tool_feedback may already be parsed as dict/list from base class
                        if isinstance(tool_feedback, (dict, list)):
                            parsed = tool_feedback
                        else:
                            import json as _json
                            parsed = _json.loads(tool_feedback)
                        event = {
                            "tool_name": parsed.get("name", "unknown") if isinstance(parsed, dict) else "unknown",
                            "old_args": None,
                            "new_args": parsed,
                            "message": f"User modified tool arguments: {parsed}",
                            "query": query,
                        }
                        user_update_events.append(event)
                        log.info(f"[USER_UPDATE] Recorded user update event: {event}")
                except Exception as e:
                    # Log the error for debugging
                    log.error(f"[USER_UPDATE] Failed to record user update event: {e}")
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
                evaluation_threshold = inference_config.evaluation_score_threshold  # Configurable threshold
                max_evaluation_epochs = inference_config.max_evaluation_epochs   # Maximum number of evaluation improvement cycles

                # Validation configuration
                validation_score = 0.0
                validation_threshold = inference_config.validation_score_threshold
                max_validation_attempts = inference_config.max_validation_epochs
                validation_attempts = 0
                validation_completed = False  # Track if validation phase is done

                # Main agent execution and improvement loop
                while True:
                    agent_resp = await app.ainvoke(messages=messages, config=config)

                    response_custom_metadata = agent_resp["agent_steps"][-1].get("response_custom_metadata", {})
                    if response_custom_metadata and "plan" in response_custom_metadata:
                        if not plan_verifier_flag:
                            config["tool_choice"] = "auto"
                            config["configurable"]["resume_previous_chat"] = True
                            agent_resp = await app.ainvoke(messages=None, config=config)
                        else:
                            break   # plan verifier state - no evaluation/validation needed

                    # tool verifier state - no evaluation/validation needed
                    if "tool_calls" in agent_resp["agent_steps"][-1] or not agent_resp["final_response"]:
                        break

                    # === VALIDATION LOGIC (only run if not already completed) ===
                    if validator_flag and not validation_completed:
                        validation_attempts += 1
                        log.info(f"[VALIDATOR] Starting validation attempt {validation_attempts} for session {session_id}")

                        try:
                            # Get the original query - use agent_resp's user_query if query is empty (tool interrupt case)
                            original_query = query if query else agent_resp.get("user_query", "")
                            
                            # Build effective query with user updates for validation (use for_validation=True for simpler format)
                            effective_query_for_validation = build_effective_query_with_user_updates(
                                original_query,
                                user_update_events,
                                original_query,
                                for_validation=True
                            )

                            # Get agent configuration for validation criteria
                            agent_data = await self.inference_utils.agent_service.agent_repo.get_agent_record(agentic_application_id)

                            if not agent_data:
                                log.warning(f"No agent config found for {agentic_application_id}, falling back to general relevancy validation")
                                validation_result = await self.inference_utils.validate_general_relevancy(
                                    effective_query_for_validation, 
                                    agent_resp["final_response"], 
                                    llm
                                )
                            else:
                                agent_config_data = agent_data[0]
                                validation_criteria = agent_config_data.get("validation_criteria", [])

                                # Handle case where validation_criteria might be a string
                                if isinstance(validation_criteria, str):
                                    try:
                                        import json as _json
                                        validation_criteria = _json.loads(validation_criteria)
                                    except:
                                        validation_criteria = []

                                if not validation_criteria:
                                    log.info("No validation criteria found, falling back to general relevancy validation.")
                                    validation_result = await self.inference_utils.validate_general_relevancy(
                                        effective_query_for_validation, 
                                        agent_resp["final_response"], 
                                        llm
                                    )
                                else:
                                    # Find all matching validation patterns
                                    matching_patterns = await self.inference_utils.find_all_matching_validation_patterns(
                                        effective_query_for_validation, validation_criteria, llm
                                    )

                                    if not matching_patterns:
                                        log.info("No matching validation patterns found, falling back to general relevancy validation")
                                        validation_result = await self.inference_utils.validate_general_relevancy(
                                            effective_query_for_validation, 
                                            agent_resp["final_response"], 
                                            llm
                                        )
                                    else:
                                        # Process each matching pattern
                                        validation_results_list = []
                                        for pattern in matching_patterns:
                                            pattern_result = await self.inference_utils.process_validation_pattern(
                                                pattern=pattern,
                                                state={"query": effective_query_for_validation, "response": agent_resp["final_response"]},
                                                llm=llm,
                                                effective_query=effective_query_for_validation
                                            )
                                            validation_results_list.append(pattern_result)

                                        # Aggregate validation results
                                        validation_result = self.inference_utils.aggregate_validation_results(validation_results_list)

                            validation_score = validation_result.get("validation_score", 0.0)
                            validation_feedback = validation_result.get("feedback", "")

                            log.info(f"[VALIDATOR] Validation completed - Score: {validation_score}, Status: {validation_result.get('validation_status', 'unknown')}")

                            # Store validation results
                            await self._add_additional_data_to_final_response(
                                data={"online_validation_results": validation_result},
                                thread_id=thread_id
                            )

                            # Check if validation passed
                            if validation_score >= validation_threshold:
                                log.info(f"[VALIDATOR] Validation passed with score {validation_score}")
                                validation_completed = True  # Mark validation as done
                                # Validation passed, proceed to evaluation (if enabled) or exit
                            elif validation_attempts >= max_validation_attempts:
                                log.info(f"[VALIDATOR] Maximum validation attempts {max_validation_attempts} reached. Stopping further validations.")
                                validation_completed = True  # Mark validation as done
                                # Max attempts reached, proceed to evaluation (if enabled) or exit
                            else:
                                # Validation failed, retry with feedback
                                log.info(f"[VALIDATOR] Validation failed (score: {validation_score}), retrying with feedback...")
                                validation_guidance = f"""
--- Validation Feedback ---
Based on the validation results, improve your response considering the following points:
{validation_feedback}
--- End Validation Feedback ---

IMPORTANT: Provide ONLY the improved answer/response directly. Do NOT include acknowledgments like "Thank you for the feedback" or explanations about the validation process. Just provide the correct answer.
"""
                                messages = [llm.format_content_with_role(validation_guidance)]
                                config["configurable"]["resume_previous_chat"] = True
                                config["tool_interrupt"] = False
                                config["tool_choice"] = "none"
                                continue  # Retry with validation feedback

                        except Exception as e:
                            log.error(f"[VALIDATOR] Error during validation: {e}. Proceeding without further validations.")
                            validation_completed = True  # Mark validation as done even on error

                    # === EVALUATION LOGIC ===
                    if not evaluation_flag:
                        break  # No evaluation needed, exit the loop

                    # Check if we've already exceeded evaluation threshold
                    if evaluation_score >= evaluation_threshold:
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
                        
                        evaluation_results = await self.evaluate_agent_response(agent_response=agent_resp, llm=llm, workflow_description=workflow_description)
                        
                        # Restore original query
                        agent_resp["user_query"] = original_query
                        
                        await self._add_additional_data_to_final_response(
                                data={"online_evaluation_results": evaluation_results},
                                thread_id=thread_id
                            )

                        current_epoch = await self._get_epoch_value(agent_steps=agent_resp["agent_steps"], key="online_evaluation_epoch")
                        log.info(f"[EVALUATION] Current epoch: {current_epoch}, Max epochs: {max_evaluation_epochs}, Score: {evaluation_results.get('evaluation_score')}, Threshold: {evaluation_threshold}")
                        if current_epoch >= max_evaluation_epochs or "error" in evaluation_results:
                            log.info(f"Maximum evaluation epochs {max_evaluation_epochs} reached. Stopping further evaluations.")
                            break

                        evaluation_score = evaluation_results.get("evaluation_score")
                        
                        # Check if evaluation passed - break BEFORE sending retry message
                        if evaluation_score >= evaluation_threshold:
                            log.info(f"[EVALUATION] Evaluation passed with score {evaluation_score} >= threshold {evaluation_threshold}. No retry needed.")
                            break
                        
                        evaluation_feedback = evaluation_results.get("evaluation_feedback")

                        # Reset for retry - include user modifications context to prevent reverting to original query
                        retry_message = evaluation_feedback
                        if user_update_events:
                            mods_context = []
                            for ev in user_update_events:
                                if ev.get("tool_name") == "plan_update":
                                    plan_fb = ev.get("new_args", {}).get("plan_feedback", "")
                                    if plan_fb:
                                        mods_context.append(f"User modified the plan: {plan_fb}")
                                else:
                                    mods_context.append(ev.get("message", "User made modifications"))
                            if mods_context:
                                retry_message = (
                                    f"{evaluation_feedback}\n\n"
                                    f"IMPORTANT: Remember the user's modifications:\n"
                                    f"{chr(10).join('- ' + m for m in mods_context)}\n"
                                    f"Your improved response must address the MODIFIED request, not the original query."
                                )
                        
                        messages = [llm.format_content_with_role(retry_message, online_evaluation_epoch=current_epoch+1)]
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
                        
                        # Save to database
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
                        
                        # Save to file (using ChatService method)
                        asyncio.create_task(
                            self.chat_service.save_chat_to_file(
                                agentic_application_id=agentic_application_id,
                                session_id=session_id,
                                start_timestamp=start_timestamp,
                                end_timestamp=end_timestamp,
                                human_message=agent_resp["user_query"],
                                ai_message=agent_resp["final_response"],
                                llm=llm
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
                                tools_to_interrupt: Optional[List[str]] = None,
                                tool_feedback: str = None,
                                context_flag: bool = True,
                                temperature: float = 0,
                                evaluation_flag: bool = False,
                                validator_flag: bool = False,
                                enable_streaming_flag: bool = False,
                                inference_config: AdminConfigLimits = AdminConfigLimits()
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
                "history_lookback": Limits.PYTHON_BASED_AGENT_CHAT_HISTORY_LOOKBACK if context_flag else 0,
                "resume_previous_chat": False,
                "store_response_custom_metadata": True
            },
            "tool_choice": "auto",
            "tool_interrupt": tool_interrupt_flag,
            "tools_to_interrupt": tools_to_interrupt,
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

        log.info("Agent build successfully")

        workflow_description = agent_config.get("WORKFLOW_DESCRIPTION", "")

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
                    
                    # Load any previously saved user_update_events from chat history (from plan feedback)
                    try:
                        last_entry_id, last_entry_data = await self.chat_state_history_manager.get_most_recent_chat_entry(thread_id)
                        if last_entry_data and last_entry_data.get("agent_steps"):
                            for step in last_entry_data["agent_steps"]:
                                if isinstance(step, dict) and step.get("user_update_events"):
                                    user_update_events.extend(step["user_update_events"])
                                    log.info(f"[USER_UPDATE] Loaded {len(step['user_update_events'])} user update events from chat history")
                    except Exception as e:
                        log.warning(f"[USER_UPDATE] Failed to load user_update_events from chat history: {e}")

                elif is_plan_approved.lower() == "no" and plan_feedback:
                    yield {"raw": {"plan_verifier": "User rejected the plan and provided feedback."}, "content": "User rejected the plan and provided feedback. Regenerating the plan."}
                    config["tool_choice"] = "none"
                    config["configurable"]["resume_previous_chat"] = True
                    feedback_content = f"The previous plan was not approved by user.\nUSER FEEDBACK: {plan_feedback}.\n\nPlease generate a revised plan based on user feedback."
                    yield {"raw": {"plan_feedback": "Regenerating plan based on user feedback."}, "content": "Regenerating plan based on user feedback."}
                    messages = [app.format_content_with_role(feedback_content)]
                    
                    # Record plan feedback as user update event for validation context
                    plan_update_event = {
                        "tool_name": "plan_update",
                        "old_args": None,
                        "new_args": {"plan_feedback": plan_feedback},
                        "message": f"User rejected the plan and provided feedback: {plan_feedback}",
                        "query": query,
                    }
                    user_update_events.append(plan_update_event)
                    log.info(f"[USER_UPDATE] Recorded plan feedback event: {plan_update_event}")
                    
                    # Save user_update_events immediately to chat history (for next request when plan is approved)
                    try:
                        await self._add_additional_data_to_final_response(
                            data={"user_update_events": user_update_events},
                            thread_id=thread_id
                        )
                        log.info(f"[USER_UPDATE] Saved {len(user_update_events)} user update events to chat history")
                    except Exception as e:
                        log.warning(f"[USER_UPDATE] Failed to save user_update_events to chat history: {e}")
                    

                else:
                    log.info("No invocation required.")
                    final_response = await self.chat_state_history_manager.get_recent_history(thread_id=thread_id)
                    # yield {"Node Name": "Hybrid Agent", "Status": "Completed"}
                    yield final_response
                    return

                # If there are no messages (tool interrupt or plan approved), set tool_choice to auto
                if not messages:
                    config["tool_choice"] = "auto"
                
                # Load user_update_events from chat history for tool interrupt cases
                # This ensures plan feedback context is preserved when tool interrupt happens after plan approval
                if tool_interrupt_flag and not user_update_events:
                    try:
                        last_entry_id, last_entry_data = await self.chat_state_history_manager.get_most_recent_chat_entry(thread_id)
                        if last_entry_data and last_entry_data.get("agent_steps"):
                            for step in last_entry_data["agent_steps"]:
                                if isinstance(step, dict) and step.get("user_update_events"):
                                    user_update_events.extend(step["user_update_events"])
                                    log.info(f"[USER_UPDATE] Loaded {len(step['user_update_events'])} user update events from chat history (tool interrupt)")
                    except Exception as e:
                        log.warning(f"[USER_UPDATE] Failed to load user_update_events for tool interrupt: {e}")

                # Record tool feedback updates into user_update_events and augment the initial query
                try:
                    if tool_interrupt_flag and tool_feedback and tool_feedback != "yes":
                        # tool_feedback may already be parsed as dict/list from base class
                        if isinstance(tool_feedback, (dict, list)):
                            parsed = tool_feedback
                        else:
                            import json as _json
                            parsed = _json.loads(tool_feedback)
                        event = {
                            "tool_name": parsed.get("name", "unknown") if isinstance(parsed, dict) else "unknown",
                            "old_args": None,
                            "new_args": parsed,
                            "message": f"User modified tool arguments: {parsed}",
                            "query": query,
                        }
                        user_update_events.append(event)
                        log.info(f"[USER_UPDATE] Recorded user update event: {event}")
                except Exception as e:
                    # Log the error for debugging
                    log.error(f"[USER_UPDATE] Failed to record user update event: {e}")
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
                evaluation_threshold = inference_config.evaluation_score_threshold  # Configurable threshold
                max_evaluation_epochs = inference_config.max_evaluation_epochs   # Maximum number of evaluation improvement cycles

                # Validation configuration
                validation_score = 0.0
                validation_threshold = inference_config.validation_score_threshold
                max_validation_attempts = inference_config.max_validation_epochs
                validation_attempts = 0
                validation_completed = False  # Track if validation phase is done

                agent_resp = None
                final_stream_response = None

                # Main agent execution and improvement loop
                while True:
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
                        log.info(f"[Plan Detection] Plan detected with {plan_count} steps. plan_verifier_flag={plan_verifier_flag}")
                        yield {"raw": {"plan_steps": f"Generated execution plan with {plan_count} steps."}, "content": f"Generated execution plan with {plan_count} steps."}
                        
                        if not plan_verifier_flag:
                            log.info(f"[Plan Auto-Approval] Auto-approving plan since plan_verifier_flag=False")
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
                            log.info(f"[Plan Verifier] Yielding plan_verifier prompt for user confirmation")
                            yield {"raw": {"plan_verifier": "Is this plan acceptable?"}, "content": "Please review the execution plan and confirm if it is acceptable."}
                            break   # plan verifier state - no evaluation/validation needed

                    # tool verifier state - no evaluation/validation needed
                    if "tool_calls" in agent_resp.get("agent_steps", [{}])[-1] or not agent_resp.get("final_response"):
                        break

                    # === VALIDATION LOGIC (only run if not already completed) ===
                    if validator_flag and not validation_completed:
                        validation_attempts += 1
                        log.info(f"[VALIDATOR] Starting validation attempt {validation_attempts} for session {session_id}")
                        yield {"Node Name": "Validation", "Status": "Started"}

                        try:
                            # Get the original query - use agent_resp's user_query if query is empty (tool interrupt case)
                            original_query = query if query else agent_resp.get("user_query", "")
                            
                            # Build effective query with user updates for validation (use for_validation=True for simpler format)
                            effective_query_for_validation = build_effective_query_with_user_updates(
                                original_query,
                                user_update_events,
                                original_query,
                                for_validation=True
                            )
                            
                            log.info(f"[VALIDATOR] original_query='{original_query}', user_update_events={user_update_events}")
                            log.info(f"[VALIDATOR] effective_query_for_validation='{effective_query_for_validation}'")
                            log.info(f"[VALIDATOR] final_response='{agent_resp.get('final_response')}'")

                            # Get agent configuration for validation criteria
                            agent_data = await self.inference_utils.agent_service.agent_repo.get_agent_record(agentic_application_id)

                            if not agent_data:
                                log.warning(f"No agent config found for {agentic_application_id}, falling back to general relevancy validation")
                                validation_result = await self.inference_utils.validate_general_relevancy(
                                    effective_query_for_validation, 
                                    agent_resp.get("final_response"), 
                                    llm
                                )
                            else:
                                agent_config_data = agent_data[0]
                                validation_criteria = agent_config_data.get("validation_criteria", [])

                                # Handle case where validation_criteria might be a string
                                if isinstance(validation_criteria, str):
                                    try:
                                        import json as _json
                                        validation_criteria = _json.loads(validation_criteria)
                                    except:
                                        validation_criteria = []

                                if not validation_criteria:
                                    log.info("No validation criteria found, falling back to general relevancy validation.")
                                    validation_result = await self.inference_utils.validate_general_relevancy(
                                        effective_query_for_validation, 
                                        agent_resp.get("final_response"), 
                                        llm
                                    )
                                else:
                                    # Find all matching validation patterns
                                    matching_patterns = await self.inference_utils.find_all_matching_validation_patterns(
                                        effective_query_for_validation, validation_criteria, llm
                                    )

                                    if not matching_patterns:
                                        log.info("No matching validation patterns found, falling back to general relevancy validation")
                                        validation_result = await self.inference_utils.validate_general_relevancy(
                                            effective_query_for_validation, 
                                            agent_resp.get("final_response"), 
                                            llm
                                        )
                                    else:
                                        # Process each matching pattern
                                        validation_results_list = []
                                        for pattern in matching_patterns:
                                            pattern_result = await self.inference_utils.process_validation_pattern(
                                                pattern=pattern,
                                                state={"query": effective_query_for_validation, "response": agent_resp.get("final_response")},
                                                llm=llm,
                                                effective_query=effective_query_for_validation
                                            )
                                            validation_results_list.append(pattern_result)

                                        # Aggregate validation results
                                        validation_result = self.inference_utils.aggregate_validation_results(validation_results_list)

                            validation_score = validation_result.get("validation_score", 0.0)
                            validation_feedback = validation_result.get("feedback", "")

                            log.info(f"[VALIDATOR] Validation completed - Score: {validation_score}, Status: {validation_result.get('validation_status', 'unknown')}")
                            yield {"raw": {"online_validation_results": validation_result}, "content": f"Validation completed with score {validation_score}."}
                            yield {"Node Name": "Validation", "Status": "Completed"}

                            # Store validation results
                            await self._add_additional_data_to_final_response(
                                data={"online_validation_results": validation_result},
                                thread_id=thread_id
                            )

                            # Check if validation passed
                            if validation_score >= validation_threshold:
                                log.info(f"[VALIDATOR] Validation passed with score {validation_score}")
                                validation_completed = True  # Mark validation as done
                                # Validation passed, proceed to evaluation (if enabled) or exit
                            elif validation_attempts >= max_validation_attempts:
                                log.info(f"[VALIDATOR] Maximum validation attempts {max_validation_attempts} reached. Stopping further validations.")
                                validation_completed = True  # Mark validation as done
                                # Max attempts reached, proceed to evaluation (if enabled) or exit
                            else:
                                # Validation failed, retry with feedback
                                log.info(f"[VALIDATOR] Validation failed (score: {validation_score}), retrying with feedback...")
                                yield {"raw": {"validation_retry": f"Validation failed, retrying with feedback (attempt {validation_attempts})"}, "content": f"Validation failed (score: {validation_score}), retrying..."}
                                validation_guidance = f"""
--- Validation Feedback ---
Based on the validation results, improve your response considering the following points:
{validation_feedback}
--- End Validation Feedback ---

IMPORTANT: Provide ONLY the improved answer/response directly. Do NOT include acknowledgments like "Thank you for the feedback" or explanations about the validation process. Just provide the correct answer.
"""
                                messages = [llm.format_content_with_role(validation_guidance)]
                                config["configurable"]["resume_previous_chat"] = True
                                config["tool_interrupt"] = False
                                config["tool_choice"] = "none"
                                continue  # Retry with validation feedback

                        except Exception as e:
                            log.error(f"[VALIDATOR] Error during validation: {e}. Proceeding without further validations.")
                            validation_completed = True  # Mark validation as done even on error
                            yield {"Node Name": "Validation", "Status": "Failed", "Error": str(e)}

                    # === EVALUATION LOGIC ===
                    if not evaluation_flag:
                        break  # No evaluation needed, exit the loop

                    # Check if we've already exceeded evaluation threshold
                    if evaluation_score >= evaluation_threshold:
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
                        
                        evaluation_results = await self.evaluate_agent_response(agent_response=agent_resp, llm=llm, workflow_description=workflow_description)
                        
                        agent_resp["user_query"] = original_query
                        
                        await self._add_additional_data_to_final_response(
                                data={"online_evaluation_results": evaluation_results},
                                thread_id=thread_id
                            )
                        yield {"raw": {"online_evaluation_results": evaluation_results}, "content": f"Evaluation completed with score {evaluation_results.get('evaluation_score', 0)}."}
                      
                        yield {"Node Name": "Evaluation", "Status": "Completed"}
                        

                        current_epoch = await self._get_epoch_value(agent_steps=agent_resp.get("agent_steps", []), key="online_evaluation_epoch")
                        log.info(f"[EVALUATION] Current epoch: {current_epoch}, Max epochs: {max_evaluation_epochs}, Score: {evaluation_results.get('evaluation_score')}, Threshold: {evaluation_threshold}")
                        if current_epoch >= max_evaluation_epochs or "error" in evaluation_results:
                            log.info(f"Maximum evaluation epochs {max_evaluation_epochs} reached. Stopping further evaluations.")
                            break

                        evaluation_score = evaluation_results.get("evaluation_score")
                        
                        # Check if evaluation passed - break BEFORE sending retry message
                        if evaluation_score >= evaluation_threshold:
                            log.info(f"[EVALUATION] Evaluation passed with score {evaluation_score} >= threshold {evaluation_threshold}. No retry needed.")
                            break
                        
                        evaluation_feedback = evaluation_results.get("evaluation_feedback")

                        # Reset for retry - include user modifications context to prevent reverting to original query
                        retry_message = evaluation_feedback
                        if user_update_events:
                            mods_context = []
                            for ev in user_update_events:
                                if ev.get("tool_name") == "plan_update":
                                    plan_fb = ev.get("new_args", {}).get("plan_feedback", "")
                                    if plan_fb:
                                        mods_context.append(f"User modified the plan: {plan_fb}")
                                else:
                                    mods_context.append(ev.get("message", "User made modifications"))
                            if mods_context:
                                retry_message = (
                                    f"{evaluation_feedback}\n\n"
                                    f"IMPORTANT: Remember the user's modifications:\n"
                                    f"{chr(10).join('- ' + m for m in mods_context)}\n"
                                    f"Your improved response must address the MODIFIED request, not the original query."
                                )
                        
                        messages = [llm.format_content_with_role(retry_message, online_evaluation_epoch=current_epoch+1)]
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
                        
                        # Save to database
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
                        
                        # Save to file (using ChatService method)
                        asyncio.create_task(
                            self.chat_service.save_chat_to_file(
                                agentic_application_id=agentic_application_id,
                                session_id=session_id,
                                start_timestamp=start_timestamp,
                                end_timestamp=end_timestamp,
                                human_message=agent_resp.get("user_query"),
                                ai_message=agent_resp.get("final_response"),
                                llm=llm
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







