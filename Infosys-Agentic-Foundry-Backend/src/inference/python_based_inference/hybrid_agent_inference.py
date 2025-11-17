# © 2024-25 Infosys Limited, Bangalore, India. All Rights Reserved.
import asyncio
from typing import Any, Dict, Optional, Literal
from fastapi import HTTPException

from src.models.base_ai_model_service import BaseAIModelService
from src.inference.inference_utils import InferenceUtils
from src.inference.python_based_inference.base_python_based_agent_inference import BasePythonBasedAgentInference
from src.inference.inference_utils import EpisodicMemoryManager

from phoenix.trace import using_project
from telemetry_wrapper import logger as log


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
        with using_project(project_name):
            try:
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
                        user_id = agentic_application_id
                        episodic_memory = EpisodicMemoryManager(user_id)
                        log.info("Fetching relevant examples from episodic memory")
                        relevant = await episodic_memory.find_relevant_examples_for_query(query)
                        pos_examples = relevant.get("positive", [])
                        neg_examples = relevant.get("negative", [])
                        context = await episodic_memory.create_context_from_examples(pos_examples, neg_examples)
                        if context and (pos_examples or neg_examples):
                            messages.append({"role": "user", "content": context})
                            messages.append({"role": "assistant", "content":
                                "I will use positive examples as guidance and explicitly avoid negative examples."})
                            messages.append({"role": "user", "content": query})

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
                        evaluation_results = await self.evaluate_agent_response(agent_response=agent_resp, llm=llm)
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

                        messages = [llm.format_content_with_role(evaluation_feedback, online_evaluation_epoch=current_epoch+1)]
                        config["configurable"]["resume_previous_chat"] = True

                    except Exception as e:
                        log.error(f"Error during evaluation: {e}. Proceeding without further evaluations.")
                        break


                try:
                    agent_steps = agent_resp.get("agent_steps")
                    response_custom_metadata = agent_steps[-1].get("response_custom_metadata", {})
                    final_response_generated_flag = bool(agent_resp["final_response"]) and "plan" not in response_custom_metadata and "tool_calls" not in agent_steps[-1]

                    if final_response_generated_flag:
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

                except Exception as e:
                    log.error(f"Error during response formatting: {e}. Returning unformatted response.")


                log.info(f"Agent invoked successfully for query: {query} with session ID: {session_id}")
                final_response = await self.chat_state_history_manager.get_recent_history(thread_id=thread_id)
                return final_response

            except Exception as e:
                log.error(f"Error occurred during agent invocation: {e}", exc_info=True)
                raise HTTPException(status_code=500, detail=f"Error occurred during agent invocation: {str(e)}")


