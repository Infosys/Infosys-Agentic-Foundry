# © 2024-25 Infosys Limited, Bangalore, India. All Rights Reserved.
import json
import asyncio
from typing import Dict, List

from langgraph.types import interrupt, StreamWriter
from langgraph.graph import StateGraph, START, END
from langchain_core.messages import AIMessage, ChatMessage

from src.utils.helper_functions import get_timestamp, build_effective_query_with_user_updates
from src.inference.inference_utils import InferenceUtils
from src.inference.base_agent_inference import BaseWorkflowState, BaseMetaTypeAgentInference
from telemetry_wrapper import logger as log

from src.prompts.prompts import online_agent_evaluation_prompt, feedback_lesson_generation_prompt


class PlannerMetaWorkflowState(BaseWorkflowState):
    """
    State specific to the Planner Meta Agent workflow.
    Extends BaseWorkflowState with any Meta-specific attributes if needed.
    """
    plan: List[str]
    past_steps_input: List[str]
    past_steps_output: List[str]
    step_idx: int
    tool_feedback: str = None
    is_tool_interrupted: bool = False
    evaluation_score: float = None
    evaluation_feedback: str = None
    epoch: int = 0
    user_update_events: list = []

    
    evaluation_attempts: int = 0
    validation_attempts: int = 0


    # --- Plan verifier HITL fields (parity with original git) ---
    is_plan_approved: str = None
    plan_feedback: str = None
    current_query_status: str = None

    # --- Validator parity + richer context ---
    validation_score: float = None
    validation_feedback: str = None
    workflow_description: str = None


class PlannerMetaAgentInference(BaseMetaTypeAgentInference):
    """
    Implements the LangGraph workflow for 'planner_meta_agent' type.
    """

    def __init__(self, inference_utils: InferenceUtils):
        super().__init__(inference_utils)

    async def _build_agent_and_chains(self, llm, agent_config, checkpointer=None, tool_interrupt_flag: bool = False):
        """
        Builds the agent and chains for the Planner Meta workflow.
        Returns writer_holder to enable streaming in handoff tools.
        """
        worker_agent_ids = agent_config["TOOLS_INFO"]
        system_prompts = agent_config["SYSTEM_PROMPT"]

        # Load system prompts from your config
        meta_agent_planner_prompt = system_prompts.get('SYSTEM_PROMPT_META_AGENT_PLANNER', "").replace("{", "{{").replace("}", "}}")
        meta_agent_supervisor_prompt = system_prompts.get('SYSTEM_PROMPT_META_AGENT_SUPERVISOR', "").replace("{", "{{").replace("}", "}}")
        meta_agent_responder_prompt = system_prompts.get('SYSTEM_PROMPT_META_AGENT_RESPONDER', "").replace("{", "{{").replace("}", "}}")

        # --- Define Chains ---
        meta_planner_chain_json, meta_planner_chain_str = await self._get_chains(llm, meta_agent_planner_prompt)
        _, meta_responder_chain = await self._get_chains(llm, meta_agent_responder_prompt, get_json_chain=False)

        meta_agent, _ ,writer_holder= await self._get_react_agent_as_supervisor_agent(
            llm=llm,
            system_prompt=meta_agent_supervisor_prompt,
            worker_agent_ids=worker_agent_ids,
            checkpointer=checkpointer,
            interrupt_tool=tool_interrupt_flag
        )

        chains = {
            "llm": llm,
            "meta_agent": meta_agent,
            "meta_planner_chain_json": meta_planner_chain_json,
            "meta_planner_chain_str": meta_planner_chain_str,
            "meta_responder_chain": meta_responder_chain,
            "writer_holder": writer_holder
        }
        return chains

    async def _build_workflow(self, chains: dict, flags: Dict[str, bool] = {}) -> StateGraph:
        """
        Builds the LangGraph workflow for a Planner Meta Agent.
        """
        tool_interrupt_flag = flags.get("tool_interrupt_flag", False)
        evaluation_flag = flags.get("evaluation_flag", False)
        plan_verifier_flag = flags.get("plan_verifier_flag", False)
        validator_flag = flags.get("validator_flag", False)
        response_formatting_flag = flags.get("response_formatting_flag", False)

        llm = chains.get("llm", None)
        meta_agent = chains.get("meta_agent", None)
        meta_planner_chain_json = chains.get("meta_planner_chain_json", None)
        meta_planner_chain_str = chains.get("meta_planner_chain_str", None)
        meta_responder_chain = chains.get("meta_responder_chain", None)
        writer_holder = chains.get("writer_holder", {})  # Get writer_holder for handoff tools

        writer_holder = chains.get("writer_holder", {})

        if not llm or not meta_agent or not meta_planner_chain_json or not meta_planner_chain_str or not meta_responder_chain:
            raise ValueError("Required chains (llm, meta_agent, meta_planner_chain_json, meta_planner_chain_str, meta_responder_chain) are missing.")

    
        async def generate_past_conversation_summary(state: PlannerMetaWorkflowState, writer: StreamWriter):
            """Generates past conversation summary from the conversation history."""
            
            strt_tmstp = get_timestamp()
            conv_summary = ""
            errors = []
            
            # PRESERVE plan_feedback ONLY if it's part of an active HITL approval flow
            # plan_feedback should only exist when:
            # 1. User rejected a plan (is_plan_approved="no") and is providing feedback, OR
            # 2. User is submitting feedback to regenerate plan (plan_feedback is explicitly provided)
            # For NEW queries (where user just types a question), feedback should be None
            # We detect new queries by checking if BOTH is_plan_approved and plan_feedback are absent or None
            input_plan_feedback = state.get("plan_feedback", None)
            input_is_plan_approved = state.get("is_plan_approved", None)
            
            # If this is a brand new query (no approval status, no feedback), ensure feedback is None
            # This prevents stale feedback from previous queries being carried forward
            if input_is_plan_approved is None and (input_plan_feedback is None or input_plan_feedback == ""):
                input_plan_feedback = None
                log.debug(f"New query detected - clearing plan_feedback for session {state['session_id']}")
            elif input_plan_feedback:
                log.info(f"Preserving plan_feedback for HITL flow in session {state['session_id']}: {input_plan_feedback[:50]}...")
            
            
            # Extract original query from ongoing_conversation for regenerate/feedback scenarios
            raw_query = state["query"]
            original_query = None
            if raw_query == "[regenerate:][:regenerate]" or (raw_query.startswith("[feedback:]") and raw_query.endswith("[:feedback]")):
                for msg in reversed(state.get("ongoing_conversation", [])):
                    if hasattr(msg, 'role') and msg.role == "user_query":
                        original_query = msg.content
                        break
            current_state_query = await self.inference_utils.add_prompt_for_feedback(raw_query, original_query)

            try:
                # NEW: fetch optional workflow description for validator/evaluator parity
                agent_details = await self.agent_service.agent_repo.get_agent_record(state["agentic_application_id"])
                workflow_description = (
                    agent_details[0].get("agentic_application_workflow_description", "")
                    if agent_details else ""
                )

                if state["reset_conversation"]:
                    state["ongoing_conversation"].clear()
                    state["executor_messages"].clear()
                    log.info(f"Conversation history for session {state['session_id']} has been reset.")
                else:
                    # Get summary via ChatService
                    if state["context_flag"] == False:
                        return{
                            'past_conversation_summary': "No past conversation summary available.",
                            'query': current_state_query.content,
                            'executor_messages': current_state_query,
                            'ongoing_conversation': current_state_query,
                            'response': None,
                            'evaluation_score': None,
                            'evaluation_feedback': None,

                            # Validator parity
                            'validation_score': None,
                            'validation_feedback': None,
                            'workflow_description': workflow_description,

                            'start_timestamp': strt_tmstp,
                            'epoch': 0,
                            'evaluation_attempts': 0,
                            'validation_attempts': 0,  
                            'plan': [],
                            'past_steps_input': [],
                            'past_steps_output': [],
                            'step_idx': 0,
                            'errors': errors,
                            'user_update_events': [],

                            # HITL
                            'is_plan_approved': None,
                            'plan_feedback': input_plan_feedback,
                            'current_query_status': None
                        }
                    writer({"Node Name": "Generating Context", "Status": "Started"})
                    conv_summary = await self.chat_service.get_chat_conversation_summary(
                        agentic_application_id=state["agentic_application_id"],
                        session_id=state["session_id"]
                    )
                conv_summary = conv_summary.get("summary", "") if conv_summary else ""
                writer({"raw": {"past_conversation_summary": conv_summary}, "content": conv_summary[:100] + ("..." if len(conv_summary) > 100 else "")}) if conv_summary else writer({"raw": {"past_conversation_summary": conv_summary}, "content": "No past conversation summary available."})
                writer({"Node Name": "Generating Context", "Status": "Completed"})

            except Exception as e:
                error = f"Error occurred while generating past conversation summary: {e}"
                writer({"Node Name": "Generating Context", "Status": "Failed"})
                log.error(error)
                errors.append(error)

            log.info(f"Generated past conversation summary for session {state['session_id']}.")
            return {
                'past_conversation_summary': conv_summary,
                'query': current_state_query.content,
                'executor_messages': current_state_query,
                'ongoing_conversation': current_state_query,
                'response': None,
                'evaluation_score': None,
                'evaluation_feedback': None,

                # Validator parity
                'validation_score': None,
                'validation_feedback': None,
                'workflow_description': workflow_description if "workflow_description" in locals() else "",

                'start_timestamp': strt_tmstp,
                'epoch': 0,
                'evaluation_attempts': 0,
                'validation_attempts': 0,  # <-- added
                'plan': [],
                'past_steps_input': [],
                'past_steps_output': [],
                'step_idx': 0,
                'errors': errors,
                'user_update_events': [],

                # HITL
                'is_plan_approved': None,
                'plan_feedback': input_plan_feedback,
                'current_query_status': None
            }



        async def meta_planner_agent(state: PlannerMetaWorkflowState, writer: StreamWriter):
            """Generates a plan for the supervisor to execute."""
            writer({"Node Name": "Generating Plan", "Status": "Started"})
            agent_id = state['agentic_application_id']

            # Use the standard episodic memory function
            query = state["query"]
            messages = await InferenceUtils.prepare_episodic_memory_context(
                state["mentioned_agent_id"] if state["mentioned_agent_id"] else agent_id, query
            )

            # Include feedback block if user provided feedback on the plan
            feedback_block = ""
            if state.get("plan_feedback"):
                feedback_block = f"""
User Feedback About Plan (apply these changes before re-generating the plan):
{state['plan_feedback']}
Previous Plan That Was Rejected:
{state.get('plan', [])}
"""

            formatted_query = f"""\
Past Conversation Summary:
{state["past_conversation_summary"]}
Ongoing Conversation:
{await self.chat_service.get_formatted_messages(state["ongoing_conversation"]) if state["context_flag"] else 'No ongoing conversation.'}
User Query:
{messages}
{feedback_block}

Note: If you cannot produce a valid plan, return an empty list in JSON format: {{"plan": []}}
    """
            invocation_input = {"messages": [("user", formatted_query)]}
            try:
                planner_response = await self.inference_utils.output_parser(
                    llm=llm,
                    chain_1=meta_planner_chain_json,
                    chain_2=meta_planner_chain_str,
                    invocation_input=invocation_input,
                    error_return_key="plan"
                )
                log.info(f"Meta Planner generated plan: {planner_response['plan']}")
                writer({"raw": {"generated_plan": planner_response['plan']}, "content": f"Generated plan with {len(planner_response['plan'])} steps."}) if planner_response['plan'] else writer({"raw": {"generated_plan": planner_response['plan']}, "content": "No plan generated."})
                
                
            except Exception as e:
                log.error(f"Error occurred while generating plan: {e}")
                writer({"Node Name": "Generating Plan", "Status": "Failed", "content": f"Failed to generate plan: {str(e)}"})
                planner_response = {"plan": []}

            response = {"plan": planner_response["plan"]}
            planner_response_str= "\n".join(planner_response["plan"])
         
            writer({"raw": {"planner_response": planner_response_str}, "content": planner_response_str})
            writer({"Node Name": "Generating Plan", "Status": "Completed"})
            if planner_response["plan"]:
                response["executor_messages"] = ChatMessage(content=planner_response["plan"], role="plan")
                response["current_query_status"] = "plan" if plan_verifier_flag else None
            else:
                response["current_query_status"] = None
            return response

        async def meta_supervisor_executor(state: PlannerMetaWorkflowState, writer: StreamWriter):
            """Supervisor executes one step of the plan by delegating to a worker."""
            # Set the writer in the holder so handoff tools can stream
            writer_holder["writer"] = writer
            
            # Get the current step to execute
            step = state["plan"][state["step_idx"]]
            completed_steps = []
            completed_steps_responses = []

            thread_id = await self.chat_service._get_thread_id(state['agentic_application_id'], state['session_id'])
            internal_thread = await self.chat_service._get_thread_config("inside" + thread_id)

            current_step = state["plan"][state["step_idx"]]
            log.info(f"Supervisor executing step {state['step_idx']}: {current_step}")

            task_formatted = ""
            task_formatted += f"Past Conversation Summary:\n{state['past_conversation_summary']}\n\n"
            task_formatted += f"Ongoing Conversation:\n{await self.chat_service.get_formatted_messages(state['ongoing_conversation']) if state['context_flag'] else 'No ongoing conversation.'}\n\n"

            if state["step_idx"] != 0:
                completed_steps = state["past_steps_input"][:state["step_idx"]]
                completed_steps_responses = state["past_steps_output"][:state["step_idx"]]
                task_formatted += f"Past Steps:\n{await self.inference_utils.format_past_steps_list(completed_steps, completed_steps_responses)}"

            task_formatted += f"\n\nCurrent Step:\n{step}"

            if state["is_tool_interrupted"]:
                final_content_parts = []
                stream_source = meta_agent.astream(None, internal_thread)
            else:
                final_content_parts = [ChatMessage(content=task_formatted, role="context")]
                writer({"Node Name": "Meta Agent Thinking...", "Status": "Started"})
                stream_source = meta_agent.astream({"messages": [("user", task_formatted.strip())]}, internal_thread)

            async for msg in stream_source:
                if isinstance(msg, dict) and "agent" in msg:
                    agent_output = msg.get("agent", {})
                    messages = agent_output.get("messages", []) if isinstance(agent_output, dict) else []

                    for message in messages:
                        # Announce tool calls with original SSE labels
                        if getattr(message, "tool_calls", None):
                            writer({"raw": {"Agent Call": "Agent is calling sub-agents"}, "content": f"Agent is calling sub-agents"})
                            tool_call = message.tool_calls[0]
                            writer({"Node Name": "Agent Call", "Status": "Started", "Agent Name": tool_call['name'], "Agent Arguments": tool_call['args']})
                            tool_name = tool_call["name"]
                            tool_args = tool_call["args"]

                            if tool_args:   # Non-empty dict means arguments exist
                                if isinstance(tool_args, dict):
                                    args_str = ", ".join(f"{k}={v}" for k, v in tool_args.items())
                                else:
                                    args_str = str(tool_args)
                                tool_call_content = f"Agent called the SubAgent '{tool_name}', passing arguments: {args_str}."
                            else:
                                tool_call_content = f"Agent called the SubAgent '{tool_name}', passing no arguments."

                            writer({"content": tool_call_content})
                        
                    final_content_parts.extend(messages)
                elif "tools" in msg:
                    tool_messages = msg.get("tools", [])
                    for tool_message in tool_messages.get("messages", []):
                        writer({
                            "raw": {"Agent Name": tool_message.name, "Agent Output": tool_message.content},
                            "content": f"Agent {tool_message.name} returned: {tool_message.content}"
                        })
                        if hasattr(tool_message, "name"):
                            writer({"Node Name": "Agent Call", "Status": "Completed", "Agent Name": tool_message.name})
                    final_content_parts.extend(tool_messages.get("messages", []))
                else:
                    # Original behavior: only append messages; no extra SSE line here
                    if isinstance(msg, dict) and "agent" in msg:
                        final_content_parts.extend(msg["agent"]["messages"])

            # Mark step complete and finish
            completed_steps.append(step)
            completed_steps_responses.append(final_content_parts[-1].content)
            step_output = final_content_parts[-1].content
            log.info(f"Supervisor got result for step {state['step_idx']}: {step_output}")
            # writer({"raw": {"Meta Supervisor": completed_steps_responses[-1]}, "content": f"{completed_steps_responses[-1][:50] + ('...' if len(step_output) > 50 else '')}"})
            has_active_tasks = True
            if (
                hasattr(final_content_parts[-1], "type")      # Checks if 'type' attribute exists
                and final_content_parts[-1].type == "ai"      # Checks if type is 'ai'
                and final_content_parts[-1].tool_calls == []  # Checks if tool_calls is empty list
                ):
                has_active_tasks = False
            if has_active_tasks:
                log.info(f"[{state['session_id']}] Agent has active tasks remaining after executor agent completion.")
            else :
                writer({"Node Name": "Meta Agent Thinking...", "Status": "Completed"}) 
            return {
                "response": completed_steps_responses[-1],
                "past_steps_input": completed_steps,
                "past_steps_output": completed_steps_responses,
                "executor_messages": final_content_parts
            }

        async def increment_step(state: PlannerMetaWorkflowState):
            """Increments the step counter."""
            new_idx = state["step_idx"] + 1
            log.info(f"Incrementing to step {new_idx}")
            # Preserve original – clear tool interruption flag here
            return {"step_idx": new_idx, "is_tool_interrupted": False}

        async def meta_response_generator(state: PlannerMetaWorkflowState, writer: StreamWriter):
            """Generates the final response by synthesizing all step outputs."""
            writer({"Node Name": "Generating Final Response", "Status": "Started"})

            formatter_node_prompt = ""
            if state["response_formatting_flag"]:
                formatter_node_prompt = "\n\nYou are an intelligent assistant that provides data for a separate visualization tool. When a user asks for a chart, table, image, or any other visual element, you must not attempt to create the visual yourself in text. Your sole responsibility is to generate the raw, structured data. For example, for a chart, provide the JSON data; for an image, provide the <img> tag with a source URL; for a table, provide the data as a list of lists. Your output will be fed into another program that will handle the final formatting and display."

            # Build tool modifications context from user_update_events (only when tool interruption is enabled)
            tool_modifications_context = ""
            if tool_interrupt_flag:
                user_updates = state.get("user_update_events", [])
                if user_updates and isinstance(user_updates, list):
                    query_updates = [ev for ev in user_updates if isinstance(ev, dict) and ev.get("query") == state.get("query")]
                    if query_updates:
                        modifications = []
                        for ev in query_updates:
                            message = ev.get("message", "")
                            if message and isinstance(message, str) and message.strip():
                                modifications.append(message)
                        if modifications:
                            mods_text = "\n- ".join(modifications)
                            tool_modifications_context = f"\n\n⚠️ USER MODIFIED TOOLS:\n- {mods_text}\n**Use these actual executed values in your response.**\n"
                            log.info(f"Tool modifications context built with {len(modifications)} modifications")
                        else:
                            log.debug(f"No valid tool modifications found")
                    else:
                        log.debug(f"No query-specific tool updates found")
                else:
                    log.debug(f"No user_update_events or invalid format")
            else:
                log.debug(f"Tool interrupt flag is False, skipping tool modifications context")

            evaluation_guidance = ""
            if state["evaluation_feedback"]:
                evaluation_guidance = f"""
--- Previous Attempt Feedback ---
Based on the last evaluation, improve your response considering the following points:
{state["evaluation_feedback"]}
--- End Previous Attempt Feedback ---
Ensure you address the shortcomings identified above.
"""
                
            log.info(f"Planner Meta agent incorporating evaluation feedback (attempt {state.get('evaluation_attempts', 0)}).")



            if not state["plan"]:
                # If there was no plan, create a direct response
                log.info("No plan found. Generating direct response.")
                prompt = f"The user asked: '{state['query']}'. Please provide a direct, helpful response.{evaluation_guidance}{tool_modifications_context}"
            else:
                log.info("Synthesizing final response from executed plan.")
                plan_steps_str = "\n".join([f"Step {i+1}: {s}" for i, s in enumerate(state["plan"])])
                step_outputs_str = "\n".join([f"Result of Step {i+1}:\n{o}" for i, o in enumerate(state["past_steps_output"])])
                prompt = f"""\
The user's original query was:
{state["query"]}
To answer this, the following plan was executed:
{plan_steps_str}
The results from each step are as follows:
{step_outputs_str}
{formatter_node_prompt}
{evaluation_guidance}
{tool_modifications_context}
Please synthesize these results into a single, comprehensive, and well-formatted final answer for the user.
"""

            response = await meta_responder_chain.ainvoke({"messages": [("user", prompt)]})
            log.info(f"Final response generated: {response}")
            writer({"raw": {"final_response": "Final Response Generated"}, "content": "Final response generated."})
            writer({"raw": {"final_response": response}, "content": response[:100] + ("..." if len(response) > 100 else "")})
            writer({"Node Name": "Generating Final Response", "Status": "Completed"})
            return {"response": response}

        async def final_response_node(state: PlannerMetaWorkflowState, writer: StreamWriter):
            """Stores the final response and updates the conversation history."""
            writer({"Node Name": "Memory Update", "Status": "Started"})
            thread_id = await self.chat_service._get_thread_id(state['agentic_application_id'], state['session_id'])
            internal_thread_id = f"inside{thread_id}"
            asyncio.create_task(self.chat_service.delete_internal_thread(internal_thread_id))

            errors = []
            end_timestamp = get_timestamp()
            try:
                asyncio.create_task(self.chat_service.save_chat_message(
                    agentic_application_id=state["agentic_application_id"],
                    session_id=state["session_id"],
                    start_timestamp=state["start_timestamp"],
                    end_timestamp=end_timestamp,
                    human_message=state["query"],
                    ai_message=state["response"]
                ))
                asyncio.create_task(self.chat_service.update_preferences_and_analyze_conversation(
                    user_input=state["query"], llm=llm, agentic_application_id=state["agentic_application_id"], session_id=state["session_id"]
                ))
                if (len(state["ongoing_conversation"]) + 1) % 8 == 0:
                    log.debug("Storing chat summary")
                    asyncio.create_task(self.chat_service.get_chat_summary(
                        agentic_application_id=state["agentic_application_id"],
                        session_id=state["session_id"],
                        llm=llm
                    ))
            except Exception as e:
                writer({"Node Name": "Memory Update", "Status": "Failed"})
                error = f"Error occurred in Final response: {e}"
                log.error(error)
                errors.append(error)

            final_response_message = AIMessage(content=state.get("response", ""))
            log.info(f"Planner Meta Agent's final response generated: {final_response_message.content}")
            writer({"raw": {"final_response": "Memory Updated"}, "content": "Memory Updated"})
            writer({"Node Name": "Memory Update", "Status": "Completed"})
            return {
                "ongoing_conversation": final_response_message,
                "executor_messages": final_response_message,
                "end_timestamp": end_timestamp,

                # Clear HITL state for next query (parity)
                "is_plan_approved": None,
                "plan_feedback": None,
                "current_query_status": None
            }

        async def route_query(state: PlannerMetaWorkflowState):
            """Routes to the executor loop if a plan exists, otherwise to the final responder."""
            if state["plan"]:
                log.info("Routing: Plan detected, starting supervisor execution loop.")
                # Route to interrupt node for approval if plan verifier is enabled
                if plan_verifier_flag:
                    return "interrupt_node"
                return "meta_supervisor_executor"
            else:
                log.info("Routing: No plan detected, proceeding to final response generation.")
                return "meta_response_generator"
        
        async def interrupt_node(state: PlannerMetaWorkflowState, writer: StreamWriter):
            """HITL: Ask human if the plan is acceptable."""
            writer({"Node Name": "Plan Approval", "Status": "Started"})
            # Send the plan content to UI for display
            plan_content = "\n".join([f"{i+1}. {step}" for i, step in enumerate(state["plan"])])
            writer({"Node Name": "Plan Approval", "Status": "In Progress", "content": f"Please review the following plan:\n\n{plan_content}"})
            
            if plan_verifier_flag:
                is_plan_approved = interrupt("Is this plan acceptable? (yes/no)").lower()
            else:
                is_plan_approved = "yes"
            writer({"Node Name": "Plan Approval", "Status": "Completed"})
            return {
                "is_plan_approved": is_plan_approved,
                "current_query_status": "feedback" if is_plan_approved == "no" else None
            }

        async def interrupt_node_decision(state: PlannerMetaWorkflowState):
            """Route based on approval result."""
            if state.get("is_plan_approved") == "no":
                log.info("Plan rejected by user, collecting feedback.")
                return "feedback_collector"
            log.info("Plan approved by user, proceeding to execution.")
            return "meta_supervisor_executor"

        async def feedback_collector(state: PlannerMetaWorkflowState, writer: StreamWriter):
            """Collects user feedback and routes back to planner to regenerate plan."""
            writer({"Node Name": "Collecting Feedback", "Status": "Started"})
            writer({"Node Name": "Collecting Feedback", "Status": "In Progress", "content": "Waiting for your feedback to improve the plan..."})
            feedback = interrupt("Please provide feedback to fix the plan:")
            writer({"Node Name": "Collecting Feedback", "Status": "Completed", "content": f"Feedback received: {feedback}"})
            log.info(f"User feedback collected: {feedback}")
            return {
                "plan_feedback": feedback,
                "executor_messages": ChatMessage(content=feedback, role="re-plan-feedback"),
                "current_query_status": None
            }
        
        async def check_plan_execution_status(state: PlannerMetaWorkflowState):
            """Checks if all steps in the plan have been executed."""
            if state["step_idx"] == len(state["plan"]):
                log.info("Routing: Plan execution complete.")
                return "meta_response_generator"
            else:
                log.info("Routing: More steps in plan, continuing execution.")
                return "meta_supervisor_executor"

        async def tool_interrupt_router(state: PlannerMetaWorkflowState, writer: StreamWriter):
            thread_id = await self.chat_service._get_thread_id(state['agentic_application_id'], state['session_id'])
            internal_thread = await self.chat_service._get_thread_config("inside" + thread_id)

            # Original behavior: decide based on agent's planning tasks (not state flag)
            agent_state = await meta_agent.aget_state(internal_thread)
            has_active_tasks = agent_state.tasks != ()
            if tool_interrupt_flag and has_active_tasks:
                log.info(f"[{state['session_id']}] Agent planning tool with interruption enabled, routing to tool_interrupt_node.")
                return "tool_interrupt_node"
            else:
                return "increment_step"

        async def tool_interrupt_node(state: PlannerMetaWorkflowState, writer: StreamWriter):
            """Asks the human if the plan is ok or not"""
            thread_id = await self.chat_service._get_thread_id(state['agentic_application_id'], state['session_id'])
            internal_thread = await self.chat_service._get_thread_config("inside" + thread_id)

            agent_state = await meta_agent.aget_state(internal_thread)

            # Extract tool name from agent_state to check against interrupt_items
            tool_name_in_task = None
            last_message = agent_state.values.get("messages", [])[-1] if agent_state.values.get("messages") else None
            if last_message and hasattr(last_message, 'tool_calls') and last_message.tool_calls:
                tool_name_in_task = last_message.tool_calls[0].get('name')

            # Check if we should interrupt: tool_interrupt_flag AND (no interrupt_items OR tool_name is in interrupt_items)
            interrupt_items = state.get("interrupt_items") or []
            should_interrupt = tool_interrupt_flag and (not interrupt_items or (tool_name_in_task and tool_name_in_task in interrupt_items))

            if should_interrupt:
                log.info(f"[{state['session_id']}] Interrupting for agent/tool: {tool_name_in_task}")
                is_approved = interrupt("approved?(yes/feedback)")
                writer({"raw": {"agent_verifier": "Please confirm to execute the agent"}, "content": "Agent execution requires confirmation. Please approve to proceed."})
                if is_approved == "yes":
                    writer({"raw": {"agent_verifier": "User approved the agent execution by clicking the thumbs up button"}, "content": "User approved the agent execution by clicking the thumbs up button"})
            else:
                log.info(f"[{state['session_id']}] Agent/Tool '{tool_name_in_task}' not in interrupt_items {interrupt_items}, auto-approving.")
                is_approved = "yes"
            return {"tool_feedback": is_approved, "is_tool_interrupted": True}

        async def tool_interrupt_node_decision(state: PlannerMetaWorkflowState):
            if state["tool_feedback"] == 'yes':
                return "meta_supervisor_executor"
            else:
                return "tool_interrupt_update_argument"

        async def tool_interrupt_update_argument(state: PlannerMetaWorkflowState, writer: StreamWriter):
            # Set the writer in the holder so handoff tools can stream
            writer_holder["writer"] = writer
            
            writer({"raw": {"tool_interrupt_update_argument": "User updated the agent arguments"}, "content": "User updated the agent arguments, updating the agent state accordingly."})
            thread_id = await self.chat_service._get_thread_id(state['agentic_application_id'], state['session_id'])
            internal_thread = await self.chat_service._get_thread_config("inside" + thread_id)
            model_name = state["model_name"]

            agent_state = await meta_agent.aget_state(internal_thread)
            value = agent_state.values["messages"][-1]

            if model_name.startswith("gemini"):
                tool_call_id = value.tool_calls[-1]["id"]
                tool_name = value.additional_kwargs["function_call"]["name"]
                old_arg = ""
            else:
                tool_call_id = value.additional_kwargs["tool_calls"][-1]["id"]
                tool_name = value.additional_kwargs["tool_calls"][0]["function"]["name"]
                old_arg = value.additional_kwargs["tool_calls"][0]["function"]["arguments"]

            response_metadata = value.response_metadata
            id_ = value.id
            usage_metadata = value.usage_metadata
            tool_feedback = state["tool_feedback"]

            try:
                feedback_dict = json.loads(tool_feedback)
            except Exception:
                feedback_dict = None

            new_args_text = tool_feedback if tool_feedback else "{}"

            new_ai_msg = AIMessage(
                content=f"user modified the tool values, consider the new values. the old values are {old_arg}, and user modified values are {new_args_text} for the tool {tool_name}",
                additional_kwargs={"tool_calls": [{"id": tool_call_id, "function": {"arguments": new_args_text, "name": tool_name}, "type": "function"}], "refusal": None},
                response_metadata=response_metadata,
                id=id_,
                tool_calls=[{'name': tool_name, 'args': feedback_dict if feedback_dict is not None else new_args_text, 'id': tool_call_id, 'type': 'tool_call'}],
                usage_metadata=usage_metadata
            )

            await meta_agent.aupdate_state(
                internal_thread,
                {"messages": [new_ai_msg]}
            )

            final_content_parts = [new_ai_msg]
            stream_source = meta_agent.astream(None, internal_thread)
            async for msg in stream_source:
                if isinstance(msg, dict) and "agent" in msg:
                    agent_output = msg.get("agent", {})
                    if isinstance(agent_output, dict) and "messages" in agent_output:
                        messages = agent_output.get("messages", [])
                        for message in messages:
                            if message.tool_calls:
                                triggered_tool_calls = message.tool_calls
                                for tool_call in triggered_tool_calls:
                                    writer({"Node Name": "Agent Call", "Status": "Started", "Agent Name": tool_call['name'], "Agent Arguments": tool_call['args']})
                        final_content_parts.extend(messages)
                elif "tools" in msg:
                    tool_messages = msg.get("tools", [])
                    for tool_message in tool_messages["messages"]:
                        writer({"raw": {"Agent Name": tool_message.name, "Agent Output": tool_message.content}, "content": f"Agent {tool_message.name} returned: {tool_message.content}"})
                        if hasattr(tool_message, "name"):
                            writer({"Node Name": "Agent Call", "Status": "Completed", "Agent Name": tool_message.name})
                    final_content_parts.extend(tool_messages["messages"])
                else:
                    if "agent" in msg:
                        final_content_parts.extend(msg["agent"]["messages"])

            # Record a user update event for evaluator awareness
            try:
                event = {
                    "tool_name": tool_name,
                    "old_args": old_arg,
                    "new_args": feedback_dict if feedback_dict is not None else new_args_text,
                    "message": new_ai_msg.content,
                    "timestamp": get_timestamp(),
                    "query": state.get("query")
                }
            except Exception as e:
                event = {"tool_name": tool_name, "message": new_ai_msg.content, "error": str(e), "timestamp": get_timestamp(), "query": state.get("query")}

            writer({"raw": {"tool_interrupt_final_response": final_content_parts}, "content": f"Agent execution with user's feedback completed."})

            final_ai_message = final_content_parts[-1]
            has_active_tasks = True
            if (
                hasattr(final_ai_message, "type")  # Checks if 'type' attribute exists
                and final_ai_message.type == "ai"  # Checks if type is 'ai'
                and final_ai_message.tool_calls == []  # Checks if tool_calls is empty list
            ):
                has_active_tasks = False

            if has_active_tasks:
                log.info(f"[{state['session_id']}] Agent has active tasks remaining after executor agent completion.")
            else :
                writer({"Node Name": "Meta Agent Thinking...", "Status": "Completed"}) 

            existing_events = list(state.get("user_update_events", []))
            existing_events.append(event)
            return {
                "response": final_ai_message.content,
                "executor_messages": final_content_parts,
                "user_update_events": existing_events,
                "is_tool_interrupted": False
            }

      
        async def evaluator_agent(state: PlannerMetaWorkflowState, writer: StreamWriter):
            """
            Evaluates the agent response across multiple dimensions and provides scores and feedback.
            """
            log.info(f"🎯EVALUATOR AGENT CALLED for session {state['session_id']}")
            writer({"Node Name": "Evaluating Response", "Status": "Started"})
            evaluation_attempts = state.get("evaluation_attempts", 0) + 1
            agent_evaluation_prompt = online_agent_evaluation_prompt
            try:
                # Build effective query considering user modifications (tool + plan feedback)

               

                updates_lines = []
                for ev in state.get("user_update_events", []):
                    if ev.get("query") and ev.get("query") != state.get("query"):
                        continue
                    line = f"message : {ev.get('message','N/A')}\n"
                    updates_lines.append(line)

                plan_feedback_block = ""
                if state.get("plan_feedback"):
                    plan_feedback_block = (
                        f"\n\n--- User Plan Modifications ---\n"
                        f"The user reviewed the initial plan and requested changes:\n"
                        f"{state['plan_feedback']}\n"
                        f"--- End Plan Modifications ---\n"
                    )

                if updates_lines:
                    updates_block = "\n".join(updates_lines)
                    effective_query = (
                        f"{state['query']}\n\n--- User Tool Feedback Updates ---\n"
                        f"{updates_block}\n--- End Updates ---{plan_feedback_block}"
                    )
                elif plan_feedback_block:
                    effective_query = f"{state['query']}{plan_feedback_block}"
                else:
                    # No user modifications
                    effective_query = state["query"]

                if effective_query != state["query"]:
                    log.info(f"Evaluator using modified query (includes user feedback) for session {state['session_id']}")

                # ✅ Pass attempts as evaluation_epoch so your prompt sees the same nomenclature everywhere
                formatted_evaluation_query = agent_evaluation_prompt.format(
                    User_Query=effective_query,
                    Agent_Response=state["response"],
                    past_conversation_summary=state["past_conversation_summary"],
                    workflow_description=state.get("workflow_description"),
                    evaluation_epoch=state.get("evaluation_attempts", 0)  # <-- attempts, not epoch
                )

                evaluation_response = await llm.ainvoke(formatted_evaluation_query)

                # Parse the JSON response
                evaluation_data = json.loads(
                    evaluation_response.content.replace("```json", "").replace("```", "").strip()
                )

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

                log.info(f"Evaluator completed for session {state['session_id']} with aggregate score: {aggregate_score}")
                writer({"raw": {"evaluator_response": evaluation_data}, "content": f"Evaluation completed with score: {aggregate_score}"})
                writer({"Node Name": "Evaluating Response", "Status": "Completed"})

                return {
                    "evaluation_score": aggregate_score,
                    "evaluation_feedback": compiled_feedback,
                    "evaluation_attempts": evaluation_attempts,
                    "executor_messages": ChatMessage(
                        content=[{
                            "evaluation_score": aggregate_score,
                            "evaluation_details": evaluation_data,
                            "feedback": compiled_feedback
                        }],
                        role="evaluator-response"
                    ),
                    "is_tool_interrupted": False
                }

            except json.JSONDecodeError as e:
                writer({"Node Name": "Evaluating Response", "Status": "Failed"})
                log.error(f"Failed to parse evaluator JSON response for session {state['session_id']}: {e}")
                return {
                    "evaluation_score": 0.3,
                    "evaluation_feedback": "Evaluation failed due to JSON parsing error. Please review the response format and content quality.",
                    "evaluation_attempts": state.get("evaluation_attempts", 0) + 1,
                    "executor_messages": ChatMessage(
                        content="Evaluation failed - JSON parsing error",
                        role="evaluator-error"
                    ),
                    "is_tool_interrupted": False
                }
            except Exception as e:
                log.error(f"Evaluator agent failed for session {state['session_id']}: {e}")
                writer({"Node Name": "Evaluating Response", "Status": "Failed"})
                return {
                    "evaluation_score": 0.3,
                    "evaluation_feedback": f"Evaluation failed due to error: {str(e)}",
                    "evaluation_attempts": state.get("evaluation_attempts", 0) + 1,
                    "executor_messages": ChatMessage(
                        content=f"Evaluation failed: {str(e)}",
                        role="evaluator-error"
                    ),
                    "is_tool_interrupted": False
                }

        async def evaluator_decision(state: PlannerMetaWorkflowState):
            """
            Decides whether to return the final response or continue with improvement cycle.
            SAVES feedback ONLY if the score fails the threshold (score < 0.7).
            """
            evaluation_threshold = 0.7
            max_evaluation_epochs = 3

            current_epoch = state.get("evaluation_attempts", 0)
            evaluation_score = state.get("evaluation_score", 0.0)
            evaluation_feedback = state.get("evaluation_feedback", "No evaluation feedback available")

            # Check if this is the final state (passed OR hit max retries)
            is_final_attempt = (evaluation_score >= evaluation_threshold or current_epoch >= max_evaluation_epochs)

            if is_final_attempt:
                # 🔄 ONLY Save to DB if it FAILED the threshold
                if evaluation_score < evaluation_threshold:
                    try:
                        log.info(f"📉 Evaluation failed (Score: {evaluation_score}). Generating lesson and saving failure.")
                        
                        evaluator_lesson_prompt = feedback_lesson_generation_prompt.format(
                            user_query=state["query"],
                            agent_response=state["response"],
                            feedback_type="EVALUATOR",
                            feedback_score=evaluation_score,
                            feedback_details=evaluation_feedback
                        )
                        
                        lesson_response = await llm.ainvoke(evaluator_lesson_prompt)
                        lesson = lesson_response.content
                        status = f"[FAILED_AFTER_{current_epoch}_RETRIES]"

                        await self.feedback_learning_service.save_feedback(
                            agent_id=state["agentic_application_id"],
                            query=state["query"],
                            old_final_response=state["response"],
                            old_steps="", 
                            new_final_response=status,
                            feedback=f"[EVALUATOR] Score: {evaluation_score:.2f} - {evaluation_feedback}", 
                            new_steps=status,
                            lesson=lesson
                        )
                        log.info(f"💾 Planner Meta Evaluator failure stored for session {state['session_id']}")
                            
                    except Exception as e:
                        log.error(f"❌ Failed to save evaluator feedback: {e}")
                else:
                    log.info(f"✅ Evaluation passed (Score: {evaluation_score}). Skipping feedback save.")

                return "final_response_node"

            # If not final, route back for synthesis improvement
            log.info(f"Evaluation failed ({evaluation_score}). Routing for synthesis improvement.")
            return "increment_epoch"

        
                
        async def increment_epoch(state: PlannerMetaWorkflowState):
            """Increments the evaluation attempts counter (name kept for graph parity)."""
            new_attempts = state.get("evaluation_attempts", 0) + 1
            log.info(f"Incrementing evaluation attempts to {new_attempts}")
            

        async def validator_agent_node(state: PlannerMetaWorkflowState, writer: StreamWriter):
            """
            Validates the agent response using validator tools or LLM-based validation.
            Returns `executor_messages` similar to evaluator_agent for downstream consumers.
            """

            if not validator_flag:
                # Skipped: validator disabled
                exec_msg = ChatMessage(
                    content=str([{
                        "validation_score": 1.0,
                        "validation_details": {"status": "skipped", "reason": "validator_flag disabled"},
                        "feedback": "Validation skipped (validator disabled)"
                    }]),
                    role="validator-response"
                )
                return {
                    "validation_score": 1.0,
                    "validation_feedback": "Validation skipped (validator disabled)",
                    "validation_attempts": state.get("validation_attempts", 0),  # do not increment when skipped
                    "is_tool_interrupted": False,
                    "executor_messages": exec_msg
                }

            writer({"Node Name": "Validating Response", "Status": "Started"})
            log.info(f"[INFO] VALIDATOR AGENT CALLED for session {state['session_id']}")
            log.info(f"VALIDATOR AGENT CALLED for session {state['session_id']}")

            # Increment validation attempts counter
            validation_attempts = state.get("validation_attempts", 0) + 1

            try:
                # Get agent configuration for validation criteria
                # Use mentioned_agent_id if present, otherwise agentic_application_id
                agent_id_for_validation = state.get("mentioned_agent_id") if state.get("mentioned_agent_id") else state["agentic_application_id"]
                agent_config = await self.agent_service.agent_repo.get_agent_record(agent_id_for_validation)

                if not agent_config:
                    log.warning(f"No agent config found for {agent_id_for_validation}, falling back to general relevancy validation")
                    result = await self.inference_utils.validate_general_relevancy(state["query"], state["response"], llm)
                    writer({"raw": {"Validation Score": result.get("validation_score", 0.0)}, "content": f"Validation score: {result.get('validation_score', 0.0)}"})
                    writer({"Node Name": "Validating Response", "Status": "Completed"})

                    exec_msg = ChatMessage(
                        content=str([{
                            "validation_score": result.get("validation_score", 0.0),
                            "validation_details": result,
                            "feedback": result.get("feedback", "No agent config found")
                        }]),
                        role="validator-response"
                    )
                    return {
                        "validation_score": result.get("validation_score", 0.0),
                        "validation_feedback": result.get("feedback", "No agent config found"),
                        "is_tool_interrupted": False,
                        "validation_attempts": validation_attempts,
                        "executor_messages": exec_msg
                    }

                # Consider any recorded user tool argument changes in validation (only for current query)
                effective_query_for_validation = build_effective_query_with_user_updates(
                    state["query"],
                    state.get("user_update_events", []),
                    state.get("query")
                )

                agent_data = agent_config[0]
                validation_criteria = agent_data.get("validation_criteria", [])

                # Handle case where validation_criteria might be a string
                if isinstance(validation_criteria, str):
                    try:
                        import json as _json
                        validation_criteria = _json.loads(validation_criteria)
                    except _json.JSONDecodeError:
                        log.warning(f"Failed to parse validation_criteria string: {validation_criteria}")
                        validation_criteria = []

                if not validation_criteria:
                    log.info("No validation criteria found, falling back to general relevancy validation")
                    result = await self.inference_utils.validate_general_relevancy(effective_query_for_validation, state["response"], llm)
                    log.info(f"General relevancy result: {result}")
                    writer({"raw": {"Validation Score": result.get("validation_score", 0.0)}, "content": f"Validation score: {result.get('validation_score', 0.0)}"})
                    writer({"Node Name": "Validating Response", "Status": "Completed"})

                    exec_msg = ChatMessage(
                        content=str([{
                            "validation_score": result.get("validation_score", 0.0),
                            "validation_details": result,
                            "feedback": result.get("feedback", "No validation criteria found")
                        }]),
                        role="validator-response"
                    )
                    return {
                        "validation_score": result.get("validation_score", 0.0),
                        "validation_feedback": result.get("feedback", "No validation criteria found"),
                        "is_tool_interrupted": False,
                        "validation_attempts": validation_attempts,
                        "executor_messages": exec_msg
                    }

                # Find all matching validation patterns
                matching_patterns = await self.inference_utils.find_all_matching_validation_patterns(
                    effective_query_for_validation, validation_criteria, llm
                )

                if not matching_patterns:
                    log.info("No matching validation patterns found, falling back to general relevancy validation")
                    result = await self.inference_utils.validate_general_relevancy(effective_query_for_validation, state["response"], llm)
                    log.info(f"General relevancy fallback result: {result}")
                    writer({"raw": {"Validation Score": result.get("validation_score", 0.0)}, "content": f"Validation score: {result.get('validation_score', 0.0)}"})
                    writer({"Node Name": "Validating Response", "Status": "Completed"})

                    exec_msg = ChatMessage(
                        content=str([{
                            "validation_score": result.get("validation_score", 0.0),
                            "validation_details": result,
                            "feedback": result.get("feedback", "No matching validation patterns found")
                        }]),
                        role="validator-response"
                    )
                    return {
                        "validation_score": result.get("validation_score", 0.0),
                        "validation_feedback": result.get("feedback", "No matching validation patterns found"),
                        "is_tool_interrupted": False,
                        "validation_attempts": validation_attempts,
                        "executor_messages": exec_msg
                    }

                # Process each matching pattern
                validation_results = []
                for pattern in matching_patterns:
                    pattern_result = await self.inference_utils.process_validation_pattern(
                        pattern, state, llm, effective_query_for_validation
                    )
                    validation_results.append(pattern_result)

                # Aggregate all validation results
                final_result = self.inference_utils.aggregate_validation_results(validation_results)
                log.info(f"Validator completed for session {state['session_id']} with status: {final_result['validation_status']}")

                writer({
                    "raw": {"Validation Score": final_result["validation_score"]},
                    "content": f"Validation score: {final_result['validation_score']}"
                })
                writer({"Node Name": "Validating Response", "Status": "Completed"})

                exec_msg = ChatMessage(
                    content=str([{
                        "validation_score": final_result["validation_score"],
                        "validation_details": final_result,
                        "feedback": final_result["feedback"]
                    }]),
                    role="validator-response"
                )
                return {
                    "validation_score": final_result["validation_score"],
                    "validation_feedback": final_result["feedback"],
                    "validation_attempts": validation_attempts,
                    "is_tool_interrupted": False,
                    "executor_messages": exec_msg
                }

            except Exception as e:
                log.error(f"Validator agent failed for session {state['session_id']}: {e}")
                writer({"raw": {"Validation Error": str(e)}, "content": f"Validation failed due to error: {str(e)}"})
                writer({"Node Name": "Validating Response", "Status": "Failed"})

                exec_msg = ChatMessage(
                    content=f"Validation failed: {str(e)}",
                    role="validator-error"
                )
                return {
                    "validation_score": 0.3,
                    "validation_feedback": f"Validation failed due to error: {str(e)}",
                    "validation_attempts": validation_attempts,
                    "is_tool_interrupted": False,
                    "executor_messages": exec_msg
                }



        async def validator_decision_node(state: PlannerMetaWorkflowState):
            """
            Decides the next step based on validation results and current attempts.
            SAVES feedback ONLY if the score fails the threshold (score < 0.7).
            """
            validation_threshold = 0.7
            max_validation_attempts = 3

            current_attempts = state.get("validation_attempts", 0)
            validation_score = state.get("validation_score", 0.0)
            validation_feedback = state.get("validation_feedback", "No validation feedback available")

            # Final state check
            is_exiting = (validation_score >= validation_threshold or current_attempts >= max_validation_attempts)

            if is_exiting:
                # 🔄 ONLY Save to DB if it FAILED the threshold
                if validation_score < validation_threshold:
                    try:
                        log.info(f"📉 Validation failed (Score: {validation_score}). Generating lesson and saving failure.")
                        
                        validator_lesson_prompt = feedback_lesson_generation_prompt.format(
                            user_query=state["query"],
                            agent_response=state["response"],
                            feedback_type="VALIDATOR",
                            feedback_score=validation_score,
                            feedback_details=validation_feedback
                        )
                        
                        lesson_response = await llm.ainvoke(validator_lesson_prompt)
                        lesson = lesson_response.content
                        status = f"[FAILED_AFTER_{current_attempts}_RETRIES]"

                        await self.feedback_learning_service.save_feedback(
                            agent_id=state["agentic_application_id"],
                            query=state["query"],
                            old_final_response=state["response"],
                            old_steps=str(state.get("plan", [])), 
                            new_final_response=status,
                            feedback=f"[VALIDATOR] Score: {validation_score:.2f} - {validation_feedback}", 
                            new_steps=status,
                            lesson=lesson
                        )
                        log.info(f"💾 Planner Meta Validator failure stored for session {state['session_id']}")
                            
                    except Exception as e:
                        log.error(f"❌ Failed to save validator feedback: {e}")
                else:
                    log.info(f"✅ Validation passed (Score: {validation_score}). Skipping feedback save.")

                # Proceed to next node based on flags
                if evaluation_flag:
                    return "evaluator_agent"
                return "final_response_node"

            # If not exiting, loop back for re-planning
            log.info(f"Validation failed ({validation_score}). Routing back for re-planning.")
            return "increment_epoch_validation"
            
        
        async def increment_epoch_validation(state: PlannerMetaWorkflowState):
            new_attempts = state.get("validation_attempts", 0) + 1
            log.info(f"[Validator] Incrementing validation attempts to {new_attempts}")
            return {"validation_attempts": new_attempts}

        async def post_response_router(state: PlannerMetaWorkflowState):
            """
            Routes from meta_response_generator to validator, evaluator, or final_response
            based on flags and evaluation history. Prevents re-running validator after evaluator has completed.
            """
            # Skip validator if evaluator has already run (evaluation_attempts > 0)
            evaluation_attempts = state.get("evaluation_attempts", 0)
            
            if validator_flag and evaluation_attempts == 0:
                log.info(f"[ROUTE] Routing to validator_agent (validation enabled and evaluator hasn't run yet)")
                return "validator_agent"
            elif evaluation_flag:
                log.info(f"[ROUTE] Routing to evaluator_agent (evaluation enabled, skipping validator)")
                return "evaluator_agent"
            else:
                log.info(f"[ROUTE] Routing to final_response_node (no validation or evaluation)")
                return "final_response_node"

                
        # ---- Build Graph (Workflow) ----
        workflow = StateGraph(PlannerMetaWorkflowState)

        # ----- Nodes -----
        workflow.add_node("generate_past_conversation_summary", generate_past_conversation_summary)
        workflow.add_node("meta_planner_agent", meta_planner_agent)

        # Plan verifier nodes (conditional parity)
        if plan_verifier_flag:
            workflow.add_node("interrupt_node", interrupt_node)
            workflow.add_node("feedback_collector", feedback_collector)

        # Core nodes (always)
        workflow.add_node("meta_supervisor_executor", meta_supervisor_executor)
        workflow.add_node("increment_step", increment_step)
        workflow.add_node("meta_response_generator", meta_response_generator)
        workflow.add_node("final_response_node", final_response_node)
        workflow.add_node("tool_interrupt_node", tool_interrupt_node)
        workflow.add_node("tool_interrupt_update_argument", tool_interrupt_update_argument)

        # Formatter (optional)
        if response_formatting_flag:
            workflow.add_node("formatter", lambda state: InferenceUtils.format_for_ui_node(state, llm))

        # Evaluator nodes (optional)
        if evaluation_flag:
            workflow.add_node("evaluator_agent", evaluator_agent)
            workflow.add_node("increment_epoch", increment_epoch)  # increments evaluation_attempts only on failure

        # Validator nodes (optional)
        if validator_flag:
            workflow.add_node("validator_agent", validator_agent_node)
            workflow.add_node("validator_decision_node", validator_decision_node)
            workflow.add_node("increment_epoch_validation", increment_epoch_validation)  # NEW: increments validation_attempts only on failure

        # ----- Edges -----
        workflow.add_edge(START, "generate_past_conversation_summary")
        workflow.add_edge("generate_past_conversation_summary", "meta_planner_agent")

        if plan_verifier_flag:
            workflow.add_conditional_edges(
                "meta_planner_agent",
                route_query,
                {
                    "interrupt_node": "interrupt_node",
                    "meta_supervisor_executor": "meta_supervisor_executor",
                    "meta_response_generator": "meta_response_generator",
                },
            )
            workflow.add_conditional_edges(
                "interrupt_node",
                interrupt_node_decision,
                {"meta_supervisor_executor": "meta_supervisor_executor", "feedback_collector": "feedback_collector"},
            )
            # After feedback, go back to planner to regenerate plan with feedback included
            workflow.add_edge("feedback_collector", "meta_planner_agent")
        else:
            workflow.add_conditional_edges(
                "meta_planner_agent",
                route_query,
                {"meta_supervisor_executor": "meta_supervisor_executor", "meta_response_generator": "meta_response_generator"},
            )

        # Supervisor → tool interrupt routing
        workflow.add_conditional_edges(
            "meta_supervisor_executor",
            tool_interrupt_router,
            {"tool_interrupt_node": "tool_interrupt_node", "increment_step": "increment_step"},
        )
        workflow.add_conditional_edges(
            "tool_interrupt_node",
            tool_interrupt_node_decision,
            {"meta_supervisor_executor": "meta_supervisor_executor", "tool_interrupt_update_argument": "tool_interrupt_update_argument"},
        )
        workflow.add_conditional_edges(
            "tool_interrupt_update_argument",
            tool_interrupt_router,
            {"tool_interrupt_node": "tool_interrupt_node", "increment_step": "increment_step"},
        )
        workflow.add_conditional_edges(
            "increment_step",
            check_plan_execution_status,
            {"meta_supervisor_executor": "meta_supervisor_executor", "meta_response_generator": "meta_response_generator"},
        )

        # ----- Validation + Evaluation routing after final synthesis -----
        # Use dynamic router instead of static edges to prevent validator re-execution after evaluator
        response_router_targets = ["final_response_node"]
        if validator_flag:
            response_router_targets.insert(0, "validator_agent")
        if evaluation_flag:
            response_router_targets.insert(0 if not validator_flag else 1, "evaluator_agent")
        
        workflow.add_conditional_edges(
            "meta_response_generator",
            post_response_router,
            response_router_targets
        )
        
        # Validator routing (when validator is enabled)
        if validator_flag:
            validator_targets = ["increment_epoch_validation", "final_response_node"]
            if evaluation_flag:
                validator_targets.insert(1, "evaluator_agent")
            
            workflow.add_conditional_edges(
                "validator_agent",
                validator_decision_node,
                validator_targets,
            )
            # After validator failure increment, re-plan
            workflow.add_edge("increment_epoch_validation", "meta_planner_agent")

        # Evaluator routing (when evaluator is enabled)
        if evaluation_flag:
            workflow.add_conditional_edges(
                "evaluator_agent",
                evaluator_decision,
                ["increment_epoch", "final_response_node"],
            )
            # After evaluator failure increment, go back to synthesis
            workflow.add_edge("increment_epoch", "meta_response_generator")


        # Formatter routing
        if flags["response_formatting_flag"]:
            workflow.add_edge("final_response_node", "formatter")
            workflow.add_edge("formatter", END)
        else:
            workflow.add_edge("final_response_node", END)

        log.info("Planner Meta Agent workflow built successfully")
        return workflow

  
  