# © 2024-25 Infosys Limited, Bangalore, India. All Rights Reserved.
import json
import asyncio
from typing import Dict

from langgraph.types import interrupt, StreamWriter
from langgraph.graph import StateGraph, START, END
from langchain_core.messages import AIMessage, ChatMessage

from telemetry_wrapper import logger as log

from src.utils.helper_functions import get_timestamp, build_effective_query_with_user_updates
from src.inference.inference_utils import InferenceUtils
from src.inference.base_agent_inference import BaseWorkflowState, BaseMetaTypeAgentInference
from telemetry_wrapper import logger as log



from src.prompts.prompts import online_agent_evaluation_prompt, feedback_lesson_generation_prompt


class MetaWorkflowState(BaseWorkflowState):
    """
    State specific to the Meta agent workflow.
    Extends BaseWorkflowState with any Meta-specific attributes if needed.
    """
    tool_feedback: str = None
    is_tool_interrupted: bool = False
    epoch: int = 0
    # Each event: {tool_name, old_args, new_args, message, timestamp}
    user_update_events: list = []
    # --- Added for validator/evaluator parity ---
    validation_score: float = None
    validation_feedback: str = None
    workflow_description: str = None


class MetaAgentInference(BaseMetaTypeAgentInference):
    """Implements the LangGraph workflow for 'meta_agent' type."""

    def __init__(self, inference_utils: InferenceUtils):
        super().__init__(inference_utils)


    async def _build_agent_and_chains(self, llm, agent_config, checkpointer = None, tool_interrupt_flag: bool = False):
        """
        Builds the agent and chains for the Meta workflow.
        Returns writer_holder to enable streaming in handoff tools.
        """
        worker_agent_ids = agent_config["TOOLS_INFO"]
        system_prompt = agent_config["SYSTEM_PROMPT"]
        meta_agent, _, writer_holder = await self._get_react_agent_as_supervisor_agent(
            llm=llm,
            system_prompt=system_prompt.get("SYSTEM_PROMPT_META_AGENT", ""),
            worker_agent_ids=worker_agent_ids,
            checkpointer=checkpointer,
            interrupt_tool=tool_interrupt_flag,
        )

        chains = {
            "llm": llm,
            "meta_agent": meta_agent,
            "writer_holder": writer_holder  # Pass to workflow for setting writer
        }
        return chains
    
   

    async def _build_workflow(self, chains: dict, flags: Dict[str, bool] = {}) -> StateGraph:
        """Builds the LangGraph workflow for a Meta agent."""
        tool_interrupt_flag = flags.get("tool_interrupt_flag", False)
        evaluation_flag = flags.get("evaluation_flag", False)
        validator_flag = flags.get("validator_flag", False)
        response_formatting_flag = flags.get("response_formatting_flag", False)

        llm = chains.get("llm", None)
        meta_agent = chains.get("meta_agent", None)
        writer_holder = chains.get("writer_holder", {})  # Get writer_holder for handoff tools

        if not llm or not meta_agent:
            raise ValueError("Required chains (llm, meta_agent) are missing.")

        # ---------------- Nodes ----------------

        
        async def generate_past_conversation_summary(state: MetaWorkflowState, writer: StreamWriter):
            """Generates past conversation summary from the conversation history."""
           
            strt_tmstp = get_timestamp()
            conv_summary = ""
            errors = []

            # Extract original query from ongoing_conversation for regenerate/feedback scenarios
            raw_query = state["query"]
            original_query = None
            if raw_query == "[regenerate:][:regenerate]" or (
                raw_query.startswith("[feedback:]") and raw_query.endswith("[:feedback]")
            ):
                # Find the original user query from ongoing_conversation
                for msg in reversed(state.get("ongoing_conversation", [])):
                    if hasattr(msg, "role") and msg.role == "user_query":
                        original_query = msg.content
                        break

            # Use add_prompt_for_feedback with original_query for proper context (your updated behavior)
            current_state_query = await self.inference_utils.add_prompt_for_feedback(raw_query, original_query)

            try:
                # --- NEW: Fetch workflow description for validator/evaluator parity ---
                agent_details = await self.agent_service.agent_repo.get_agent_record(
                    state["agentic_application_id"]
                )
                workflow_description = (
                    agent_details[0].get("agentic_application_workflow_description", "")
                    if agent_details else ""
                )

                if state["reset_conversation"]:
                    state["ongoing_conversation"].clear()
                    state["executor_messages"].clear()
                    log.info(f"Conversation history for session {state['session_id']} has been reset.")
                else:
                    if state["context_flag"] == False:
                        writer({"Node Name": "Generating Context", "Status": "Completed"})
                        return {
                            "past_conversation_summary": "No past conversation summary available.",
                            # Keep your updated shape: downstream nodes read the rewritten query content
                            "query": getattr(current_state_query, "content", str(current_state_query)),
                            "ongoing_conversation": current_state_query,
                            "executor_messages": current_state_query,

                            # Keep existing fields; add validator/evaluator parity fields
                            "response": None,
                            "evaluation_score": None,
                            "evaluation_feedback": None,
                            "validation_score": None,
                            "validation_feedback": None,

                            # NEW: supply workflow_description for validator/evaluator prompts
                            "workflow_description": workflow_description,

                            "epoch": 0,
                            'validation_attempts': 0,
                            'evaluation_attempts': 0,
                            "start_timestamp": strt_tmstp,
                            "errors": errors,
                            "user_update_events": [],
                        }
                    # Get summary via ChatService
                    writer({"Node Name": "Generating Context", "Status": "Started"})
                    conv_summary = await self.chat_service.get_chat_conversation_summary(
                        agentic_application_id=state["agentic_application_id"],
                        session_id=state["session_id"],
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

            # Return shape aligned with your updated file, plus validator/evaluator parity fields
            return {
                "past_conversation_summary": conv_summary,
                "query": getattr(current_state_query, "content", str(current_state_query)),
                "ongoing_conversation": current_state_query,
                "executor_messages": current_state_query,

                "response": None,
                "evaluation_score": None,
                "evaluation_feedback": None,
                "validation_score": None,
                "validation_feedback": None,

                # Provide workflow description for validator/evaluator prompts
                "workflow_description": workflow_description if "workflow_description" in locals() else "",

                "epoch": 0,
                'validation_attempts': 0,
                'evaluation_attempts': 0,
                "start_timestamp": strt_tmstp,
                "errors": errors,
                "user_update_events": [],
            }


        async def meta_agent_node(state: MetaWorkflowState,writer:StreamWriter):
            """
            Creates a meta agent that supervises the worker agents.
            """
            # Set the writer in the holder so handoff tools can stream
            writer_holder["writer"] = writer
        
            thread_id = await self.chat_service._get_thread_id(state['agentic_application_id'], state['session_id'])
            internal_thread = await self.chat_service._get_thread_config("inside" + thread_id)

            agent_id = state["agentic_application_id"]
            # episodic memory context
            query = state["query"]
            messages = await InferenceUtils.prepare_episodic_memory_context(
                state["mentioned_agent_id"] if state["mentioned_agent_id"] else agent_id, query
            )

            try:
                formatter_node_prompt = ""
                if response_formatting_flag:
                    formatter_node_prompt = (
                        "You are an intelligent assistant that provides data for a separate visualization tool. "
                        "When a user asks for a chart, table, image, or any other visual element, you must not "
                        "attempt to create the visual yourself in text. Your sole responsibility is to generate "
                        "the raw, structured data. For example, for a chart, provide the JSON data; for an image, "
                        "provide the <img> tag with a source URL; for a table, provide the data as a list of lists. "
                        "Your output will be fed into another program that will handle the final formatting and display."
                    )

                evaluation_guidance = ""
                if state["evaluation_feedback"]:
                    evaluation_guidance = f"""
--- Previous Attempt Feedback ---
Based on the last evaluation, improve your response considering the following points:
{state["evaluation_feedback"]}
--- End Previous Attempt Feedback ---
Ensure you address the shortcomings identified above.
"""
                log.info(f"Meta agent incorporating evaluation feedback for epoch {state['epoch']}.")

                formatted_query = f"""\
**User Input Context**
Past Conversation Summary:
{state["past_conversation_summary"]}
Ongoing Conversation:
{await self.chat_service.get_formatted_messages(state["ongoing_conversation"]) if state["context_flag"] else "No ongoing conversation."}
{formatter_node_prompt}
{evaluation_guidance}
User Query:
{messages}
"""
                
                if state["is_tool_interrupted"]:
                    final_content_parts = []
                    stream_source = meta_agent.astream(None, internal_thread)
                else:
                    final_content_parts = [ChatMessage(content=formatted_query, role="context")]
                    writer({"Node Name": "Meta Agent Thinking...", "Status": "Started"})
                    stream_source = meta_agent.astream({"messages": [("user", formatted_query.strip())]}, internal_thread)

                async for msg in stream_source:                    
                    if isinstance(msg, dict) and "agent" in msg:
                        agent_output = msg.get("agent", {})
                        messages = []
                        if isinstance(agent_output, dict) and "messages" in agent_output:
                            messages = agent_output.get("messages", [])
                        for message in messages:
                            # Capture tool call events
                            if message.tool_calls:
                                writer({"raw": {"executor_agent": message.tool_calls}, "content": f"Agent is calling sub-agents"})
                                tool_call = message.tool_calls[0]
                                writer({"Node Name": "Agent Call", "Status": "Started", "Agent Name": tool_call['name'], "Agent Arguments": tool_call['args']})
                                tool_name = tool_call["name"]
                                tool_args = tool_call["args"]
                                if tool_args:
                                    if isinstance(tool_args, dict):
                                        args_str = ", ".join(f"{k}={v}" for k, v in tool_args.items())
                                    else:
                                        args_str = str(tool_args)
                                    tool_call_content = (
                                        f"Agent called the SubAgent '{tool_name}', passing arguments: {args_str}."
                                    )
                                else:
                                    tool_call_content = (
                                        f"Agent called the SubAgent '{tool_name}', passing no arguments."
                                    )
                                writer({"content": tool_call_content})
                        final_content_parts.extend(messages)

                    # Capture tool outputs
                    elif "tools" in msg:
                        tool_messages = msg.get("tools", [])
                        for tool_message in tool_messages["messages"]:
                            writer({"raw": {"Agent Name": tool_message.name, "Agent Output": tool_message.content}, "content": f"Agent {tool_message.name} returned: {tool_message.content}"})
                            if hasattr(tool_message, "name"):
                                writer({"Node Name": "Agent Call", "Status": "Completed", "Agent Name": tool_message.name})
                        final_content_parts.extend(tool_messages["messages"])

                    else:
                        # writer({"raw": {"executor_agent_node": msg}, "content": f"Agent processing: {msg.get('agent', {}).get('messages', [{}])[-1].get('content', 'Agent working...') if isinstance(msg, dict) and 'agent' in msg else str(msg)}"})
                        if "agent" in msg:
                            final_content_parts.extend(msg["agent"]["messages"])

            except Exception as e:
                error = f"Error Occurred in Meta Agent: {e}"
                writer({"Node Name": "Meta Agent Thinking...", "Status": "Failed"})
                log.error(error, exc_info=True) # exc_info=True gives you the full traceback in logs
                return {"errors": error}

            # Fallback handling if agent produced no messages
            if not final_content_parts:
                log.warning(
                    f"Meta Agent produced no messages for session {state['session_id']}. Using fallback response."
                )
                final_ai_message = AIMessage(
                    content=(
                        f"I'm unable to generate a detailed response right now. "
                        f"Reattempting improvement cycle {state.get('epoch', 0)}. Query: {query}"
                    )
                )
                final_content_parts.append(final_ai_message)
            else:
                final_ai_message = final_content_parts[-1]

            log.info(f"Meta Agent response generated: {final_ai_message}")
            # writer({"raw": {"meta_agent": final_ai_message.content}, "content": final_ai_message.content[:50] + ("..." if len(final_ai_message.content) > 50 else "")})

            has_active_tasks = True
            if (
                hasattr(final_ai_message, "type")      # Checks if 'type' attribute exists
                and final_ai_message.type == "ai"      # Checks if type is 'ai'
                and final_ai_message.tool_calls == []  # Checks if tool_calls is empty list
                ):
                has_active_tasks = False
            if has_active_tasks:
                log.info(f"[{state['session_id']}] Agent has active tasks remaining after executor agent completion.")
            else :
                writer({"Node Name": "Meta Agent Thinking...", "Status": "Completed"})  

            return {
                "response": final_ai_message.content,
                "executor_messages":final_content_parts
            }

        async def tool_interrupt_router(state: MetaWorkflowState):
            thread_id = await self.chat_service._get_thread_id(
                state["agentic_application_id"], state["session_id"]
            )
            internal_thread = await self.chat_service._get_thread_config("inside" + thread_id)
            agent_state = await meta_agent.aget_state(internal_thread)
            has_active_tasks = agent_state.tasks != ()
            # Skip validator if evaluator has already run (evaluation_attempts > 0)
            evaluation_attempts = state.get("evaluation_attempts", 0)
            if tool_interrupt_flag and has_active_tasks:
                log.info(
                    f"[{state['session_id']}] Agent planning tool with interruption enabled, routing to tool_interrupt_node."
                )
                return "tool_interrupt_node"
            elif validator_flag and evaluation_attempts == 0:
                return "validator_agent"
            elif evaluation_flag:
                return "evaluator_agent"
            else:
                return "final_response_node"

        async def tool_interrupt_node(state: MetaWorkflowState, writer: StreamWriter):
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

        async def tool_interrupt_node_decision(state: MetaWorkflowState):
            if state["tool_feedback"] == "yes":
                return "meta_agent_node"
            else:
                return "tool_interrupt_update_argument"

        async def tool_interrupt_update_argument(state: MetaWorkflowState, writer: StreamWriter):
            writer({"raw": {"tool_interrupt_update_argument": "User updated the agent arguments"}, "content": "User updated the agent arguments, updating the agent state accordingly."})
            thread_id = await self.chat_service._get_thread_id(state['agentic_application_id'], state['session_id'])
            internal_thread = await self.chat_service._get_thread_config("inside" + thread_id)
            model_name = state["model_name"]
            # writer({"Node Name": "Updating Tool Arguments", "Status": "Started"})

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

            # Attempt JSON parse; if not JSON, treat as raw text
            # feedback_dict = None
            # try:
            feedback_dict = json.loads(tool_feedback)
            # except Exception:
            #     feedback_dict = None

            new_ai_msg = AIMessage(
                content=(
                    f"user modified the tool values, consider the new values. "
                    f"the old values are {old_arg}, and user modified values are {tool_feedback} "
                    f"for the tool {tool_name}"
                ),
                additional_kwargs={
                    "tool_calls": [
                        {
                            "id": tool_call_id,
                            "function": {"arguments": tool_feedback, "name": tool_name},
                            "type": "function",
                        }
                    ],
                    "refusal": None,
                },
                response_metadata=response_metadata,
                id=id_,
                tool_calls=[
                    {
                        "name": tool_name,
                        "args": feedback_dict if feedback_dict is not None else tool_feedback,
                        "id": tool_call_id,
                        "type": "tool_call",
                    }
                ],
                usage_metadata=usage_metadata,
            )

            # track event for evaluator context
            try:
                event = {
                    "tool_name": tool_name,
                    "old_args": old_arg,
                    "new_args": feedback_dict if feedback_dict is not None else tool_feedback,
                    "message": new_ai_msg.content,
                    "timestamp": get_timestamp(),
                }
            except Exception as e:
                event = {
                    "tool_name": tool_name,
                    "message": new_ai_msg.content,
                    "error": str(e),
                    "timestamp": get_timestamp(),
                }

            await meta_agent.aupdate_state(internal_thread, {"messages": [new_ai_msg]})

            final_content_parts = [new_ai_msg]
            stream_source = meta_agent.astream(None, internal_thread)
            async for msg in stream_source:
                if isinstance(msg, dict) and "agent" in msg:
                    agent_output = msg.get("agent", {})
                    if isinstance(agent_output, dict) and "messages" in agent_output:
                        messages = agent_output.get("messages", [])
                
                    for message in messages:
                        # The message can be an object (like AIMessage) with a .content attribute
                        # or it could be a dictionary with a 'content' key. This handles both.
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
                    # writer({"raw": {"executor_agent_node": msg}, "content": f"Agent processing: {msg.get('agent', {}).get('messages', [{}])[-1].get('content', 'Agent working...') if isinstance(msg, dict) and 'agent' in msg else str(msg)}"})
                    if "agent" in msg:
                        final_content_parts.extend(msg["agent"]["messages"])
            
            
            final_ai_message = final_content_parts[-1]

            existing_events = []
            if state.get("user_update_events"):
                existing_events = list(state["user_update_events"])
            existing_events.append(event)
            writer({"raw": {"tool_interrupt_final_response": final_content_parts}, "content": f"Agent execution with user's feedback completed."})
            
            has_active_tasks = True
            if (
                hasattr(final_ai_message, "type")      # Checks if 'type' attribute exists
                and final_ai_message.type == "ai"      # Checks if type is 'ai'
                and final_ai_message.tool_calls == []  # Checks if tool_calls is empty list
                ):
                has_active_tasks = False
            if has_active_tasks:
                log.info(f"[{state['session_id']}] Agent has active tasks remaining after executor agent completion.")
            else :
                writer({"Node Name": "Meta Agent Thinking...", "Status": "Completed"}) 
            return {
                "response": final_ai_message.content,
                "executor_messages": final_content_parts,
                "user_update_events": existing_events,
                "is_tool_interrupted": False,
            }

        async def final_response_node(state: MetaWorkflowState, writer: StreamWriter):
            """Stores the final response and updates the conversation history."""
            writer({"Node Name": "Memory Update", "Status": "Started"})
            thread_id = await self.chat_service._get_thread_id(state['agentic_application_id'], state['session_id'])
            internal_thread_id = f"inside{thread_id}"
            asyncio.create_task(self.chat_service.delete_internal_thread(internal_thread_id))
            errors = []
            end_timestamp = get_timestamp()
            try:
                asyncio.create_task(
                    self.chat_service.save_chat_message(
                        agentic_application_id=state["agentic_application_id"],
                        session_id=state["session_id"],
                        start_timestamp=state["start_timestamp"],
                        end_timestamp=end_timestamp,
                        human_message=state["query"],
                        ai_message=state["response"],
                    )
                )
                asyncio.create_task(
                    self.chat_service.update_preferences_and_analyze_conversation(
                        user_input=state["query"],
                        llm=llm,
                        agentic_application_id=state["agentic_application_id"],
                        session_id=state["session_id"],
                    )
                )
                if (len(state["ongoing_conversation"]) + 1) % 8 == 0:
                    log.debug("Storing chat summary")
                    asyncio.create_task(
                        self.chat_service.get_chat_summary(
                            agentic_application_id=state["agentic_application_id"],
                            session_id=state["session_id"],
                            llm=llm,
                        )
                    )
            except Exception as e:
                error = f"Error occurred in Final response: {e}"
                writer({"Node Name": "Memory Update", "Status": "Failed"})
                log.error(error)
                errors.append(error)

            final_response_message = AIMessage(content=state["response"])
            log.info(f"Meta Agent's final response generated: {final_response_message.content}")
            writer({"raw": {"final_response": "Memory Updated"}, "content": "Memory Updated"})
            writer({"Node Name": "Memory Update", "Status": "Completed"})
            return {
                "executor_messages": final_response_message,
                "ongoing_conversation": final_response_message,
                "end_timestamp": end_timestamp,
                "errors": errors,
            }

        async def evaluator_agent(state: MetaWorkflowState, writer: StreamWriter):
            """Evaluates the agent response across multiple dimensions and provides scores and feedback."""
            writer({"Node Name": "Evaluating Response", "Status": "Started"})
            evaluation_attempts = state.get("evaluation_attempts", 0) + 1
            log.info(f"🎯EVALUATOR AGENT CALLED for session {state['session_id']}")
            agent_evaluation_prompt = online_agent_evaluation_prompt
            try:
                # Build effective query incorporating any user-updated tool feedback/query modifications
                if (
                    state.get("is_tool_interrupted")
                    and state.get("tool_feedback")
                    and state.get("tool_feedback") != "yes"
                    and state.get("user_update_events")
                ):
                    updates_lines = []
                    for ev in state["user_update_events"]:
                        line = (
                            f"Tool: {ev.get('tool_name','unknown')}\n"
                            f"Old Args: {ev.get('old_args','N/A')}\n"
                            f"New Args: {ev.get('new_args','N/A')}\n"
                            f"message : {ev.get('message','N/A')}\n"
                        )
                        updates_lines.append(line)
                    updates_block = "\n".join(updates_lines)
                    effective_query = (
                        f"{state['query']}\n\n--- User Tool Feedback Updates ---\n"
                        f"{updates_block}\n--- End Updates ---"
                    )
                else:
                    effective_query = state["query"]

                # Format the evaluation query
                formatted_evaluation_query = agent_evaluation_prompt.format(
                    User_Query=effective_query,
                    Agent_Response=state["response"],
                    past_conversation_summary=state["past_conversation_summary"],
                    workflow_description=state.get("workflow_description"),
                    evaluation_epoch=state.get("evaluation_attempts", 0),
                )

                # Call the LLM for evaluation
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
                writer({"raw": {"evaluator_agent": evaluation_data}, "content": f"Evaluator agent completed with score: {aggregate_score}"})
                writer({"Node Name": "Evaluating Response", "Status": "Completed"})
                return {
                    "evaluation_score": aggregate_score,
                    "evaluation_feedback": compiled_feedback,
                    "evaluation_attempts": evaluation_attempts,
                    "executor_messages": ChatMessage(
                        content=[
                            {
                                "evaluation_score": aggregate_score,
                                "evaluation_details": evaluation_data,
                                "feedback": compiled_feedback,
                            }
                        ],
                        role="evaluator-response",
                    ),
                }
            except json.JSONDecodeError as e:
                writer({"Node Name": "Evaluating Response", "Status": "Failed"})
                log.error(f"Failed to parse evaluator JSON response for session {state['session_id']}: {e}")
                writer({"raw": {"evaluator_error": str(e)}, "content": "Evaluator agent failed due to JSON parsing error."})
                return {
                    "evaluation_score": 0.3,
                    "evaluation_feedback": "Evaluation failed due to JSON parsing error. Please review the response format and content quality.",
                    "evaluation_attempts": state.get("evaluation_attempts", 0) + 1,
                    "executor_messages": ChatMessage(content="Evaluation failed - JSON parsing error", role="evaluator-error"),
                    "is_tool_interrupted": False
                }
            except Exception as e:
                writer({"Node Name": "Evaluating Response", "Status": "Failed"})
                log.error(f"Evaluator agent failed for session {state['session_id']}: {e}")
                writer({"raw": {"evaluator_error": str(e)}, "content": "Evaluator agent failed due to an error."})
                return {
                    "evaluation_score": 0.3,
                    "evaluation_feedback": f"Evaluation failed due to error: {str(e)}",
                    "evaluation_attempts": state.get("evaluation_attempts", 0) + 1,
                    "executor_messages": ChatMessage(content=f"Evaluation failed: {str(e)}", role="evaluator-error"),
                    "is_tool_interrupted": False
                }

       
        async def evaluator_decision(state: MetaWorkflowState):
            """
            Decides whether to return the final response or continue.
            SAVES feedback ONLY if the score fails the threshold (score < 0.7).
            """
            evaluation_threshold = 0.7
            max_evaluation_epochs = 3
            
            # Using existing attempts counter from MetaWorkflowState
            current_attempts = state.get("evaluation_attempts", 0)
            evaluation_score = state.get("evaluation_score", 0.0)
            evaluation_feedback = state.get("evaluation_feedback", "No evaluation feedback available")

            # Determine if this is the final state for this node
            is_final_attempt = (evaluation_score >= evaluation_threshold or current_attempts >= max_evaluation_epochs)

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
                        
                        status = f"[FAILED_AFTER_{current_attempts}_RETRIES]"

                        # Save failure feedback using existing service instance
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
                        log.info(f"💾 Meta Evaluator failure stored successfully for session {state['session_id']}")
                            
                    except Exception as e:
                        log.error(f"❌ Failed to save evaluator feedback: {e}")
                else:
                    log.info(f"✅ Evaluation passed (Score: {evaluation_score}). Skipping DB feedback save.")

                return "final_response_node"

            # Otherwise, loop back for improvement
            log.info(f"Evaluation failed ({evaluation_score}). Routing for improvement.")
            return "increment_epoch"

        
                
        async def increment_epoch(state: MetaWorkflowState):
                    """Increments the evaluation attempts counter (name kept for graph parity)."""
                    new_attempts = state.get("evaluation_attempts", 0) + 1
                    log.info(f"Incrementing evaluation attempts to {new_attempts}")
                    return {"evaluation_attempts": new_attempts}


        
        async def validator_agent_node(state:   MetaWorkflowState, writer: StreamWriter):
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


      
       
        async def validator_decision_node(state: MetaWorkflowState):
            """
            Decides the next step based on validation results.
            SAVES feedback ONLY if the score fails the threshold (score < 0.7).
            """
            validation_threshold = 0.7
            max_validation_attempts = 3
            
            # Using existing attempts counter from MetaWorkflowState
            current_attempts = state.get("validation_attempts", 0)
            validation_score = state.get("validation_score", 0.0)
            validation_feedback = state.get("validation_feedback", "No validation feedback available")

            # Determine if we are finishing the validation phase
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

                        # Save failure feedback using existing service instance
                        await self.feedback_learning_service.save_feedback(
                            agent_id=state["agentic_application_id"],
                            query=state["query"],
                            old_final_response=state["response"],
                            old_steps="", 
                            new_final_response=status,
                            feedback=f"[VALIDATOR] Score: {validation_score:.2f} - {validation_feedback}", 
                            new_steps=status,
                            lesson=lesson
                        )
                        log.info(f"💾 Meta Validator failure stored successfully for session {state['session_id']}")
                            
                    except Exception as e:
                        log.error(f"❌ Failed to save validator feedback: {e}")
                else:
                    log.info(f"✅ Validation passed (Score: {validation_score}). Skipping DB feedback save.")

                # Proceed to next node based on flags
                if flags.get("evaluation_flag", False):
                    return "evaluator_agent"
                return "final_response_node"

            # Otherwise, loop back for improvement
            log.info(f"Validation failed ({validation_score}). Routing for improvement.")
            return "increment_epoch_validation"



        async def increment_epoch_validation(state: MetaWorkflowState):
            new_epoch = state.get("validation_attempts", 0) + 1
            log.info(f"[Validator] Incrementing epoch to {new_epoch}")
            return {"validation_attempts": new_epoch}
        

        # ---------------- Build Graph (Workflow) ----------------
        workflow = StateGraph(MetaWorkflowState)
        workflow.add_node("generate_past_conversation_summary", generate_past_conversation_summary)
        workflow.add_node("meta_agent_node", meta_agent_node)
        workflow.add_node("final_response_node", final_response_node)
        if response_formatting_flag:
            workflow.add_node("formatter", lambda state: InferenceUtils.format_for_ui_node(state, llm))
        workflow.add_node("tool_interrupt_node", tool_interrupt_node)
        workflow.add_node("tool_interrupt_update_argument", tool_interrupt_update_argument)

        # Add validator nodes when enabled
        if validator_flag:
            workflow.add_node("validator_agent", validator_agent_node)
            workflow.add_node("validator_decision_node", validator_decision_node)
            workflow.add_node("increment_epoch_validation", increment_epoch_validation)

        if evaluation_flag:
            workflow.add_node("evaluator_agent", evaluator_agent)
            workflow.add_node("increment_epoch", increment_epoch)

        # Define the workflow sequence
        workflow.add_edge(START, "generate_past_conversation_summary")
        workflow.add_edge("generate_past_conversation_summary", "meta_agent_node")

        # Router after meta_agent_node
        workflow.add_conditional_edges(
            "meta_agent_node",
            tool_interrupt_router,
            ["tool_interrupt_node", "final_response_node"]
            + (["validator_agent"] if validator_flag else [])
            + (["evaluator_agent"] if evaluation_flag else []),
        )

        workflow.add_conditional_edges(
            "tool_interrupt_node",
            tool_interrupt_node_decision,
            ["meta_agent_node", "tool_interrupt_update_argument"],
        )

        workflow.add_conditional_edges(
            "tool_interrupt_update_argument",
            tool_interrupt_router,
            ["tool_interrupt_node", "final_response_node"]
            + (["validator_agent"] if validator_flag else [])
            + (["evaluator_agent"] if evaluation_flag else []),
        )

        # Evaluation routing
        if evaluation_flag:
            workflow.add_conditional_edges(
                "evaluator_agent",
                evaluator_decision,
                {"increment_epoch": "increment_epoch", "final_response_node": "final_response_node"},
            )
            workflow.add_edge("increment_epoch", "meta_agent_node")

        # Validation routing
        if validator_flag:
            workflow.add_conditional_edges(
                "validator_agent",
                validator_decision_node,
                ["increment_epoch_validation", "evaluator_agent", "final_response_node"]
                if evaluation_flag
                else ["increment_epoch_validation", "final_response_node"],
            )
            workflow.add_edge("increment_epoch_validation", "meta_agent_node")

        # Formatter
        if response_formatting_flag:
            workflow.add_edge("final_response_node", "formatter")
            workflow.add_edge("formatter", END)
        else:
            workflow.add_edge("final_response_node", END)

        log.info("Meta Agent workflow built successfully")
        # Return raw workflow (runner will compile)

        log.info(f"[MetaAgentInference] Validator nodes present: {'validator_agent' in workflow.nodes}")
        return workflow



