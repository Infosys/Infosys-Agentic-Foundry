# © 2024-25 Infosys Limited, Bangalore, India. All Rights Reserved.
import re
import json
from typing import Dict, List, Optional
import asyncio
from langgraph.types import interrupt
from langgraph.graph import StateGraph, START, END
from langchain_core.messages import AIMessage, ChatMessage
from langgraph.types import StreamWriter
from src.utils.helper_functions import get_timestamp, build_effective_query_with_user_updates
from src.inference.inference_utils import InferenceUtils
from src.inference.base_agent_inference import BaseWorkflowState, BaseAgentInference
from telemetry_wrapper import logger as log
from src.prompts.prompts import online_agent_evaluation_prompt, feedback_lesson_generation_prompt



class ReactWorkflowState(BaseWorkflowState):
    """
    State specific to the React agent workflow.
    Extends BaseWorkflowState with any React-specific attributes if needed.
    """
    preference: str
    tool_feedback: str = None
    is_tool_interrupted: bool = False
    tool_calls: Optional[List[str]]
    epoch: int = 0
    evaluation_score: float = None
    evaluation_feedback: str = None
    validation_score: float = None
    validation_feedback: str = None
    workflow_description: str = None
    user_update_events: list = [] 



class ReactAgentInference(BaseAgentInference):
    """
    Implements the LangGraph workflow for 'react_agent' type.
    """

    def __init__(self, inference_utils: InferenceUtils):
        super().__init__(inference_utils)


    async def _build_agent_and_chains(self, llm, agent_config, checkpointer = None, tool_interrupt_flag: bool = False):
        """
        Builds the agent and chains for the React workflow.
        """
        tool_ids = agent_config["TOOLS_INFO"]
        system_prompt = agent_config["SYSTEM_PROMPT"]
        react_agent, _ = await self._get_react_agent_as_executor_agent(
                                        llm,
                                        system_prompt=system_prompt.get("SYSTEM_PROMPT_REACT_AGENT", ""),
                                        checkpointer=checkpointer,
                                        tool_ids=tool_ids,
                                        interrupt_tool=tool_interrupt_flag
                                    )
        chains = {
            "llm": llm,
            "react_agent": react_agent
        }
        return chains

    async def _build_workflow(self, chains: dict, flags: Dict[str, bool] = {}) -> StateGraph:
        """
        Builds the LangGraph workflow for a React agent.
        """
        tool_interrupt_flag = flags.get("tool_interrupt_flag", False)
        evaluation_flag = flags.get("evaluation_flag", False)
        validator_flag = flags.get("validator_flag", False)
        
        llm = chains.get("llm", None)
        react_agent = chains.get("react_agent", None)

        if not llm or not react_agent:
            raise ValueError("Required chains (llm, react_agent) are missing.")

        # Nodes

        async def generate_past_conversation_summary(state: ReactWorkflowState, writer: StreamWriter):
            """Generates past conversation summary from the conversation history."""

            strt_tmstp = get_timestamp()
            conv_summary = new_preference = ""
            preference_and_conv_summary_dict = dict()
            errors = []
            workflow_description = ""  # Initialize workflow_description

            try:
                log.debug("Adding prompt for feedback")
                
                # Extract original query from ongoing_conversation for regenerate/feedback scenarios
                raw_query = state["query"]
                original_query = None
                if raw_query == "[regenerate:][:regenerate]" or (raw_query.startswith("[feedback:]") and raw_query.endswith("[:feedback]")):
                    # Find the original user query from ongoing_conversation
                    for msg in reversed(state.get("ongoing_conversation", [])):
                        if hasattr(msg, 'role') and msg.role == "user_query":
                            original_query = msg.content
                            break
                
                # Use add_prompt_for_feedback with original_query for proper context
                current_state_query = await self.inference_utils.add_prompt_for_feedback(raw_query, original_query)
                log.debug("Prompt for feedback added successfully")
                
                # Get agent details to fetch workflow description
                agent_details = await self.agent_service.agent_repo.get_agent_record(state["agentic_application_id"])
                workflow_description = agent_details[0]["agentic_application_workflow_description"] if agent_details else ""
                
                if state["reset_conversation"]:
                    state["executor_messages"].clear()
                    state["ongoing_conversation"].clear()
                    log.info(f"Conversation history for session {state['session_id']} has been reset.")
                else:
                    if state["context_flag"]==False:
                        log.info(f"Context flag is set to False, skipping past conversation summary generation for session {state['session_id']}.")
            
                        return{
                            'past_conversation_summary': "No past conversation summary available.",
                            'query': current_state_query.content,
                            'ongoing_conversation': current_state_query,
                            'executor_messages': current_state_query,
                            'preference': "No specific preferences provided.",
                            'response': None,
                            'start_timestamp': strt_tmstp,
                            'errors': errors,
                            'evaluation_score': None,
                            'evaluation_feedback': None,
                            'validation_score': None,
                            'validation_feedback': None,
                            'workflow_description': workflow_description,
                            'epoch': 0,
                            'validation_attempts': 0,
                            'evaluation_attempts': 0,
                            'user_update_events': []
                        }
                    # Get summary via ChatService
                    log.debug("Fetching chat summary")
                    writer({"Node Name": "Generating Context", "Status": "Started"})
                    preference_and_conv_summary_dict = await self.chat_service.get_chat_conversation_summary(
                        agentic_application_id=state["agentic_application_id"],
                        session_id=state["session_id"]
                    )
                    log.debug("Chat summary fetched successfully")
                    preference_and_conv_summary_dict = preference_and_conv_summary_dict or {}
                
                    log.debug("getting preferences")
                    new_preference = preference_and_conv_summary_dict.get("preference", "")
                    conv_summary = preference_and_conv_summary_dict.get("summary", "")
                    log.debug("Preferences updated successfully")

                    writer({"raw": {"past_conversation_summary": conv_summary}, "content": conv_summary[:100] + ("..." if len(conv_summary) > 100 else "")}) if conv_summary else writer({"raw": {"past_conversation_summary": conv_summary}, "content": "No past conversation summary available."})
                    writer({"Node Name": "Generating Context", "Status": "Completed"})
                    
            except Exception as e:
                writer({"Node Name": "Generating Context", "Status": "Failed"})
                error = f"Error occurred while generating past conversation summary: {e}"
                log.error(error)
                errors.append(error)

            log.debug("Prompt for feedback added successfully")

            log.info(f"Generated past conversation summary for session {state['session_id']}.")
            return {
                'past_conversation_summary': conv_summary,
                'query': current_state_query.content,
                'ongoing_conversation': current_state_query,
                'executor_messages': current_state_query,
                'preference': new_preference,
                'response': None,
                'start_timestamp': strt_tmstp,
                'errors': errors,
                'evaluation_score': None,
                'evaluation_feedback': None,
                'validation_score': None,
                'validation_feedback': None,
                'workflow_description': workflow_description,
                'epoch': 0,
                'user_update_events': [],
                'validation_attempts': 0,
                'evaluation_attempts': 0
            }
            
        async def executor_agent(state: ReactWorkflowState, writer: StreamWriter):
            """Handles query execution and returns the agent's response."""
            
            query = await self.inference_utils.add_prompt_for_feedback(state["query"])
            query = query.content
            agent_id = state['agentic_application_id']
            thread_id = await self.chat_service._get_thread_id(agent_id, state['session_id'])
            internal_thread = await self.chat_service._get_thread_config("inside" + thread_id)
            errors = state["errors"]
            
            # Use the standard episodic memory function
            messages = await InferenceUtils.prepare_episodic_memory_context(state["mentioned_agent_id"] if state["mentioned_agent_id"] else agent_id, query)
            
            try:
                log.info("Fetching feedback learning data")
                formatter_node_prompt = ""
                if state["response_formatting_flag"]:
                    formatter_node_prompt = "\n\nYou are an intelligent assistant that provides data for a separate visualization tool. When a user asks for a chart, table, image, or any other visual element, you must not attempt to create the visual yourself in text. Your sole responsibility is to generate the raw, structured data. For example, for a chart, provide the JSON data; for an image, provide the <img> tag with a source URL; for a table, provide the data as a list of lists. Your output will be fed into another program that will handle the final formatting and display."
                        
                # feedback_learning_data = await self.feedback_learning_service.get_approved_feedback(agent_id=state["agentic_application_id"])
                # feedback_msg = await self.inference_utils.format_feedback_learning_data(feedback_learning_data)
                log.info("Feedback learning data fetched successfully")
                evaluation_guidance = ""
                if state["evaluation_feedback"]:
                    evaluation_guidance = f"""
    --- Previous Attempt Feedback ---
    Based on the last evaluation, improve your response considering the following points:
    {state["evaluation_feedback"]}
    --- End Previous Attempt Feedback ---

    Ensure you address the shortcomings identified above.
    """
                    log.info(f"Executor agent incorporating evaluation feedback for epoch {state['epoch']}.")
                
                validation_guidance = ""
                if state["validation_feedback"]:
                    validation_guidance = f"""
    --- Validation Feedback ---
    Based on the validation results, improve your response considering the following points:
    {state["validation_feedback"]}
    --- End Validation Feedback ---

    Ensure you address the validation concerns identified above.
    """
                    log.info(f"Executor agent incorporating validation feedback for epoch {state['epoch']}.")
                # --- MODIFICATION END ---
                formatted_query = f'''\
Past Conversation Summary:
{state["past_conversation_summary"]}

Ongoing Conversation:
{await self.chat_service.get_formatted_messages(state["ongoing_conversation"])if state["context_flag"] else "No ongoing conversation."} 


Follow these preferences for every step:
Preferences:
{state["preference"]}
- When applicable, use these instructions to guide your responses to the user's query.


- Provide Response in markdown format with all the information included.
{formatter_node_prompt}

{evaluation_guidance}

{validation_guidance}

User Query:
{messages}
'''

                
                stream_source = None
                
                if state["is_tool_interrupted"]:
                    final_content_parts = []
                    stream_source = react_agent.astream(None, internal_thread)
                else:
                    final_content_parts = [ChatMessage(content=formatted_query, role="context")]
                    writer({"Node Name": "Thinking...", "Status": "Started"})
                    stream_source = react_agent.astream({"messages": [("user", formatted_query.strip())]}, internal_thread)

                async for msg in stream_source:
                    if isinstance(msg, dict) and "agent" in msg:
                        agent_output = msg.get("agent", {})
                        messages = []
                        if isinstance(agent_output, dict) and "messages" in agent_output:
                            messages = agent_output.get("messages", [])
                    
                        for message in messages:
                            # The message can be an object (like AIMessage) with a .content attribute
                            # or it could be a dictionary with a 'content' key. This handles both.
                            
                            if message.tool_calls:
                                writer({"raw": {"executor_agent": message.tool_calls}, "content": f"Agent is calling tools"})
                                if not tool_interrupt_flag:
                                    for tool_call in message.tool_calls:
                                        writer({"Node Name": "Tool Call", "Status": "Started", "Tool Name": tool_call['name'], "Tool Arguments": tool_call['args']})
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

                                        writer({"content": tool_call_content})
                                else:
                                    tool_call = message.tool_calls[0]
                                    writer({"Node Name": "Tool Call", "Status": "Started", "Tool Name": tool_call['name'], "Tool Arguments": tool_call['args']})
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

                                    writer({"content": tool_call_content})
                            
                        final_content_parts.extend(messages)
                    elif "tools" in msg:
                        tool_messages = msg.get("tools", [])
                        
                        for tool_message in tool_messages["messages"]:
                            writer({"raw": {"Tool Name": tool_message.name, "Tool Output": tool_message.content}, "content": f"Tool {tool_message.name} returned: {tool_message.content}"})
                            if hasattr(tool_message, "name"):
                                writer({"Node Name": "Tool Call", "Status": "Completed", "Tool Name": tool_message.name})
                        
                        final_content_parts.extend(tool_messages["messages"])
                    else:                       
                        if "agent" in msg:
                            final_content_parts.extend(msg["agent"]["messages"])


            except Exception as e:
                error = f"Error Occurred in Executor Agent: {e}"
                writer({"Node Name": "Thinking...", "Status": "Failed"})
                log.error(error, exc_info=True) # exc_info=True gives you the full traceback in logs
                errors.append(error)
                return {"errors": errors}
                
            log.info("Executor Agent response generated successfully")
            
            # Handle empty final_content_parts
            if not final_content_parts:
                error_msg = "No response generated from agent - final_content_parts is empty"
                log.error(error_msg)
                errors.append(error_msg)
                
                # Return a default response instead of crashing
                default_message = AIMessage(content="I apologize, but I couldn't generate a response. Please try again.")
                return {
                    "response": default_message.content,
                    "executor_messages": [default_message],
                    "errors": errors
                }

            # Extract the final AI message and content
            final_ai_message = final_content_parts[-1]
            if  final_ai_message.type=="ai" and final_ai_message.tool_calls==[]:
                final_content_parts = final_content_parts[:-1]
            
            # Safely extract content
            response_content = ""
            if hasattr(final_ai_message, 'content'):
                response_content = final_ai_message.content
            elif isinstance(final_ai_message, dict):
                response_content = final_ai_message.get('content', str(final_ai_message))
            else:
                response_content = str(final_ai_message)
                log.warning("final_ai_message doesn't have expected structure, converting to string")
                
           
            
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
                writer({"Node Name": "Thinking...", "Status": "Completed"})

            return {
                    "response": response_content,
                    "executor_messages": final_content_parts,
                    "errors": errors
                }

        async def tool_interrupt_router(state: ReactWorkflowState):
            thread_id = await self.chat_service._get_thread_id(state['agentic_application_id'], state['session_id'])
            internal_thread = await self.chat_service._get_thread_config("inside" + thread_id)

            agent_state = await react_agent.aget_state(internal_thread)
            has_active_tasks = agent_state.tasks != ()
            
            # Check if we're coming from evaluator (evaluation_attempts > 0 means evaluator has run)
            evaluation_attempts = state.get("evaluation_attempts", 0)
            
            if tool_interrupt_flag and has_active_tasks:
                log.info(f"[{state['session_id']}] Agent planning tool with interruption enabled, routing to tool_interrupt_node.")
                return "tool_interrupt_node"
            elif validator_flag and evaluation_attempts == 0:
                # Skip validator if coming from evaluator (evaluation_attempts > 0)
                log.info(f"[{state['session_id']}] Routing to validator_agent (validation_flag: {validator_flag}, evaluation_flag: {evaluation_flag})")
                return "validator_agent"
            elif evaluation_flag:
                log.info(f"[{state['session_id']}] Routing to evaluator_agent (evaluation_attempts: {evaluation_attempts}, evaluation_flag: {evaluation_flag})")
                return "evaluator_agent"
            else:
                log.info(f"[{state['session_id']}] No validation or evaluation flags enabled, routing to final_response")
                return "final_response"
                        
        async def tool_interrupt_node(state: ReactWorkflowState, writer: StreamWriter):

            """Asks the human if the plan is ok or not"""

            thread_id = await self.chat_service._get_thread_id(state['agentic_application_id'], state['session_id'])
            internal_thread = await self.chat_service._get_thread_config("inside" + thread_id)

            agent_state = await react_agent.aget_state(internal_thread)

            # Extract tool name from agent_state to check against interrupt_items
            tool_name_in_task = None
            last_message = agent_state.values.get("messages", [])[-1] if agent_state.values.get("messages") else None
            if last_message and hasattr(last_message, 'tool_calls') and last_message.tool_calls:
                tool_name_in_task = last_message.tool_calls[0].get('name')

            # Check if we should interrupt: tool_interrupt_flag AND (no interrupt_items OR tool_name is in interrupt_items)
            interrupt_items = state.get("interrupt_items") or []
            should_interrupt = tool_interrupt_flag and (not interrupt_items or (tool_name_in_task and tool_name_in_task in interrupt_items))

            if should_interrupt:
                log.info(f"[{state['session_id']}] Interrupting for tool: {tool_name_in_task}")
                is_approved = interrupt("approved?(yes/feedback)")
                writer({"raw": {"tool_verifier": "Please confirm to execute the tool"}, "content": "Tool execution requires confirmation. Please approve to proceed."})
                if is_approved == "yes":
                    writer({"raw": {"tool_verifier": "User approved the tool execution by clicking the thumbs up button"}, "content": "User approved the tool execution by clicking the thumbs up button"})

                log.info(f"is_approved {is_approved}")
            else:
                log.info(f"[{state['session_id']}] Tool '{tool_name_in_task}' not in interrupt_items {interrupt_items}, auto-approving.")
                is_approved = "yes"
            return {"tool_feedback": is_approved, "is_tool_interrupted": True}

        async def tool_interrupt_node_decision(state: ReactWorkflowState):
            if state["tool_feedback"] == 'yes':
                return "executor_agent"
            else:
                return "tool_interrupt_update_argument"

        async def tool_interrupt_update_argument(state: ReactWorkflowState, writer: StreamWriter):
            writer({"raw": {"tool_interrupt_update_argument": "User updated the tool arguments"}, "content": "User updated the tool arguments, updating the agent state accordingly."})
            thread_id = await self.chat_service._get_thread_id(state['agentic_application_id'], state['session_id'])
            internal_thread = await self.chat_service._get_thread_config("inside" + thread_id)
            model_name = state["model_name"]
            # writer({"Node Name": "Updating Tool Arguments", "Status": "Started"})

            agent_state = await react_agent.aget_state(internal_thread)
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
            id = value.id
            usage_metadata = value.usage_metadata
            tool_feedback = state["tool_feedback"]
            feedback_dict = json.loads(tool_feedback)
            new_ai_msg = AIMessage(
                            content=f"user modified the tool values, consider the new values. the old values are {old_arg}, and user modified values are {tool_feedback} for the tool {tool_name}",
                            additional_kwargs={"tool_calls": [{"id": tool_call_id, "function": {"arguments": tool_feedback, "name": tool_name}, "type": "function"}], "refusal": None},
                            response_metadata=response_metadata,
                            id=id,
                            tool_calls=[{'name': tool_name, 'args': feedback_dict, 'id': tool_call_id, 'type': 'tool_call'}],
                            usage_metadata=usage_metadata
                        )
            try:
                event = {
                    "tool_name": tool_name,
                    "old_args": old_arg,
                    "new_args": feedback_dict,
                    "message": new_ai_msg.content,
                    "timestamp": get_timestamp(),
                    "query": state.get("query")
                }
            except Exception as e:
                event = {"tool_name": tool_name, "message": new_ai_msg.content, "error": str(e), "timestamp": get_timestamp(), "query": state.get("query")}


            await react_agent.aupdate_state(
                internal_thread,
                {"messages": [new_ai_msg]}
            )
            
            executor_agent_response = {"messages":[]}
            final_content_parts=[new_ai_msg]
            
            stream_source = react_agent.astream(None, internal_thread)
            async for msg in stream_source :
                executor_agent_response["messages"].append(msg)
                # writer({"raw": {"tool_interrupt": msg}, "content": f"Tool execution with user feedback: {str(msg)[:100]}..."})

                if isinstance(msg, dict) and "agent" in msg:
                    agent_output = msg.get("agent", {})
                    if isinstance(agent_output, dict) and "messages" in agent_output:
                        messages = agent_output.get("messages", [])
                
                    for message in messages:
                        # The message can be an object (like AIMessage) with a .content attribute
                        # or it could be a dictionary with a 'content' key. This handles both.
                        if message.tool_calls:
                            tool_call = message.tool_calls[0]                           
                            writer({"Node Name": "Tool Call", "Status": "Started", "Tool Name": tool_call['name'], "Tool Arguments": tool_call['args']})
                        
                        
                    final_content_parts.extend(messages)
                elif "tools" in msg:
                    tool_messages = msg.get("tools", [])
                    
                    for tool_message in tool_messages["messages"]:
                        writer({"raw": {"Tool Name": tool_message.name, "Tool Output": tool_message.content}, "content": f"Tool {tool_message.name} returned: {tool_message.content}"})
                        if hasattr(tool_message, "name"):
                            writer({"Node Name": "Tool Call", "Status": "Completed", "Tool Name": tool_message.name})
                    final_content_parts.extend(tool_messages["messages"])
                else:
                    writer({"raw": {"Updating Tool Arguments": msg}, "content": f"Agent processing: {msg.get('agent', {}).get('messages', [{}])[-1].get('content', 'Agent working...') if isinstance(msg, dict) and 'agent' in msg else str(msg)}"})
                    if "agent" in msg:
                        final_content_parts.extend(msg["agent"]["messages"])
            
            
            # Handle empty final_content_parts
            if not final_content_parts:
                error_msg = "No response generated after tool interrupt update"
                log.error(error_msg)
                
                # Return a default response
                default_message = AIMessage(content="Tool execution completed but no response was generated.")
                existing_events = list(state.get("user_update_events", []))
                existing_events.append(event)
                writer({"raw": {"tool_interrupt_final_response": "Tool execution with user's feedback completed."}, "content": "Tool execution with user's feedback completed."})
                # writer({"Node Name": "Updating Tool Arguments", "Status": "Completed"})
                return {
                    "response": default_message.content,
                    "executor_messages": [default_message],
                    "user_update_events": existing_events
                }
            
            final_ai_message = final_content_parts[-1]
            
            # Safely extract content
            response_content = ""
            if hasattr(final_ai_message, 'content'):
                response_content = final_ai_message.content
            elif isinstance(final_ai_message, dict):
                response_content = final_ai_message.get('content', str(final_ai_message))
            else:
                response_content = str(final_ai_message)
                log.warning("Tool interrupt final_ai_message doesn't have expected structure")
            
            # Safely append to user_update_events without mutating the original state
            existing_events = list(state.get("user_update_events", []))
            existing_events.append(event)

            if final_ai_message.type=="ai" and final_ai_message.tool_calls==[]:
                final_content_parts = final_content_parts[:-1]
            
                
            writer({"raw": {"tool_interrupt_final_response": "Tool execution with user's feedback completed."}, "content": "Tool execution with user's feedback completed."})
            writer({"raw": {"tool_interrupt_final_response": response_content}, "content": response_content[:50] + ("..." if len(response_content) > 50 else "")})
            # writer({"Node Name": "Updating Tool Arguments", "Status": "Completed"})

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
                writer({"Node Name": "Thinking...", "Status": "Completed"})      

            return {
                "response": response_content,
                "executor_messages": final_content_parts,
                "user_update_events": existing_events
            }

        async def final_response(state: ReactWorkflowState,writer:StreamWriter):
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
                # asyncio.create_task(self.chat_service.update_preferences(user_input=state["query"], llm=llm, agentic_application_id=state["agentic_application_id"], session_id=state["session_id"]))
                asyncio.create_task(self.chat_service.update_preferences_and_analyze_conversation(user_input=state["query"], llm=llm, agentic_application_id=state["agentic_application_id"], session_id=state["session_id"]))
                if (len(state["ongoing_conversation"])+1)%8 == 0:
                    log.debug("Storing chat summary")
                    asyncio.create_task(self.chat_service.get_chat_summary(
                        agentic_application_id=state["agentic_application_id"],
                        session_id=state["session_id"],
                        llm=llm
                    ))
                # asyncio.create_task(self.chat_service.analyze_conversation_for_episodic_storage(llm=llm, agentic_application_id=state["agentic_application_id"], session_id=state["session_id"]))
                writer({"raw": {"final_response": "Memory Updated"}, "content": "Memory Updated"})
                writer({"Node Name": "Memory Update", "Status": "Completed"})
            except Exception as e:
                writer({"Node Name": "Memory Update", "Status": "Failed"})
                error = f"Error occurred in Final response: {e}"
                log.error(error)
                errors.append(error)

            final_response_message = AIMessage(content=state["response"])

            log.info("Executor Agent Final response stored successfully") 

            return {
                "ongoing_conversation": AIMessage(content=state["response"]),
                "executor_messages": final_response_message,
                "end_timestamp": end_timestamp,
                "errors":errors
            }
        
        async def evaluator_agent(state: ReactWorkflowState,writer:StreamWriter):
            """
            Evaluates the agent response across multiple dimensions and provides scores and feedback.
            """
            log.info(f"[INFO] EVALUATOR AGENT CALLED for session {state['session_id']}")
            
            # Increment evaluation attempts counter
            evaluation_attempts = state.get("evaluation_attempts", 0) + 1
            writer({"Node Name": "Evaluating Response", "Status": "Started"})
            
            agent_evaluation_prompt = online_agent_evaluation_prompt
            
            try:
                # Always consider any recorded user tool argument changes in evaluation,
                # but only those associated with the current query to avoid cross-query leakage.
                effective_query = build_effective_query_with_user_updates(
                    state["query"], 
                    state.get("user_update_events", []), 
                    state.get("query")
                )
                
                # Format the evaluation query
                formatted_evaluation_query = agent_evaluation_prompt.format(
                    User_Query=effective_query,
                    Agent_Response=state["response"],
                    past_conversation_summary=state["past_conversation_summary"],
                    workflow_description=state.get("workflow_description"),
                    evaluation_epoch=state.get("epoch", 0)
                )
                
                # Call the LLM for evaluation
                evaluation_response = await llm.ainvoke(formatted_evaluation_query)
                
                # Parse the JSON response
                evaluation_data = json.loads(evaluation_response.content.replace("```json", "").replace("```", "").strip())
                
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
                writer({"raw": {"Evaluation Score": aggregate_score}, "content": f"Evaluation completed with score: {aggregate_score}"})
                writer({"Node Name": "Evaluating Response", "Status": "Completed"})
                
                # Reset tool interrupt flag when returning for improvement
                # This ensures the agent starts fresh instead of trying to resume
                return {
                    "evaluation_score": aggregate_score,
                    "evaluation_feedback": compiled_feedback,
                    "evaluation_attempts": evaluation_attempts,
                    "is_tool_interrupted": False,  # Reset to allow fresh execution
                    "executor_messages": ChatMessage(
                        content=str([{
                            "evaluation_score": aggregate_score,
                            "evaluation_details": evaluation_data,
                            "feedback": compiled_feedback
                        }]),
                        role="evaluator-response"
                    )
                }
                
            except json.JSONDecodeError as e:
                writer({"raw": {"Evaluator Error": "JSON Parsing Error"}, "content": "Evaluation failed due to JSON parsing error."})
                writer({"Node Name": "Evaluating Response", "Status": "Failed"})
                log.error(f"Failed to parse evaluator JSON response for session {state['session_id']}: {e}")
                return {
                    "evaluation_score": 0.3,
                    "evaluation_feedback": "Evaluation failed due to JSON parsing error. Please review the response format and content quality.",
                    "evaluation_attempts": evaluation_attempts,
                    "executor_messages": ChatMessage(
                        content="Evaluation failed - JSON parsing error",
                        role="evaluator-error"
                    ),
                    "is_tool_interrupted": False  # Reset to allow fresh execution
                }
            except Exception as e:
                writer({"raw": {"Evaluator Error": str(e)}, "content": f"Evaluation failed due to error: {str(e)}"})
                writer({"Node Name": "Evaluating Response", "Status": "Failed"})
                log.error(f"Evaluator agent failed for session {state['session_id']}: {e}")
                return {
                    "evaluation_score": 0.3,
                    "evaluation_feedback": f"Evaluation failed due to error: {str(e)}",
                    "evaluation_attempts": evaluation_attempts,
                    "executor_messages": ChatMessage(
                        content=f"Evaluation failed: {str(e)}",
                        role="evaluator-error"
                    ),
                    "is_tool_interrupted": False  # Reset to allow fresh execution
                }
        async def evaluator_decision(state: ReactWorkflowState):
            """
            Decides the next step and saves evaluation feedback for learning ONLY if it fails.
            """
            evaluation_threshold = 0.7
            max_evaluation_epochs = 3
            
            current_epoch = state.get("evaluation_attempts", 0)
            evaluation_score = state.get("evaluation_score", 0.0)
            evaluation_feedback = state.get("evaluation_feedback", "No evaluation feedback available")

            # 🔄 Save evaluator feedback ONLY if it fails the criteria
            if evaluation_score < evaluation_threshold:
                try:
                    log.info(f"📉 Evaluation failed (Score: {evaluation_score}). Saving feedback for learning.")
                    evaluator_lesson_prompt = feedback_lesson_generation_prompt.format(
                        user_query=state["query"],
                        agent_response=state["response"],
                        feedback_type="EVALUATOR",
                        feedback_score=evaluation_score,
                        feedback_details=evaluation_feedback
                    )
                    
                    lesson_response = await llm.ainvoke(evaluator_lesson_prompt)
                    lesson = lesson_response.content
                    
                    status = "[PENDING_IMPROVEMENT]"

                    feedback_result = await self.feedback_learning_service.save_feedback(
                        agent_id=state["agentic_application_id"],
                        query=state["query"],
                        old_final_response=state["response"],
                        old_steps=state.get("last_step", ""),
                        new_final_response=status,
                        feedback=f"[EVALUATOR] Score: {evaluation_score:.2f} - {evaluation_feedback}", 
                        new_steps=status,
                        lesson=lesson
                    )
                    
                    if feedback_result.get("is_saved") and feedback_result.get("response_id"):
                        state["evaluator_feedback_response_id"] = feedback_result["response_id"]
                        log.info(f"💾 Evaluator failure saved with ID: {feedback_result['response_id']}")
                        
                except Exception as e:
                    log.error(f"❌ Failed to save evaluator feedback: {e}")
            else:
                log.info(f"✅ Evaluation passed (Score: {evaluation_score}). Skipping feedback save.")

            # 🛤️ Decision logic
            if evaluation_score >= evaluation_threshold or current_epoch >= max_evaluation_epochs:
                log.info(f"Evaluation finished for session {state['session_id']} - Score: {evaluation_score}")
                return "final_response"
            else:
                log.info(f"Evaluation score low. Routing for improvement. Epoch: {current_epoch}")
                state["epoch"] = current_epoch + 1
                return "executor_agent"

    
        
        async def validator_agent_node(state: ReactWorkflowState, writer: StreamWriter):
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



        async def validator_decision_node(state: ReactWorkflowState):
            """
            Decides the next step based on validation results. 
            Saves feedback ONLY if validation fails the threshold.
            """
            validation_threshold = 0.7
            max_validation_attempts = 3
            
            current_attempts = state.get("validation_attempts", 0)
            validation_score = state.get("validation_score", 0.0)
            validation_feedback = state.get("validation_feedback", "No validation feedback available")

            # Bypass if already locked
            if state.get("validator_feedback_response_id"):
                return "evaluator_agent" if evaluation_flag else "final_response"

            is_exiting = (validation_score >= validation_threshold or current_attempts >= max_validation_attempts)

            if is_exiting:
                # 🔄 Save feedback ONLY if it fails the criteria (but we are stopping retries)
                if validation_score < validation_threshold:
                    try:
                        log.info(f"📉 Validation failed after {current_attempts} attempts. Saving feedback.")
                        
                        validator_lesson_prompt = feedback_lesson_generation_prompt.format(
                            user_query=state["query"],
                            agent_response=state["response"],
                            feedback_type="VALIDATOR",
                            feedback_score=validation_score,
                            feedback_details=validation_feedback
                        )
                        
                        lesson_response = await llm.ainvoke(validator_lesson_prompt)
                        status = f"[FAILED_AFTER_{current_attempts}_RETRIES]"

                        feedback_result = await self.feedback_learning_service.save_feedback(
                            agent_id=state["agentic_application_id"],
                            query=state["query"],
                            old_final_response=state["response"],
                            old_steps=state.get("last_step", ""),
                            new_final_response=status,
                            feedback=f"[VALIDATOR] Score: {validation_score:.2f} - {validation_feedback}", 
                            new_steps=status,
                            lesson=lesson_response.content
                        )
                        
                        if feedback_result.get("is_saved") and feedback_result.get("response_id"):
                            state["validator_feedback_response_id"] = feedback_result["response_id"]
                            log.info(f"💾 Validator failure saved with ID: {feedback_result['response_id']}")
                    except Exception as e:
                        log.error(f"❌ Failed to save validator feedback: {e}")
                else:
                    log.info(f"✅ Validation passed (Score: {validation_score}). Skipping feedback save.")

                # Routing logic
                return "evaluator_agent" if evaluation_flag else "final_response"

            else:
                # Route for improvement
                log.info(f"Validation attempt {current_attempts} low (Score: {validation_score}). Retrying.")
                state["epoch"] = state.get("epoch", 0) + 1
                return "executor_agent"

        ### Build Graph (Workflow)
        workflow = StateGraph(ReactWorkflowState)

        workflow.add_node("generate_past_conversation_summary", generate_past_conversation_summary)
        workflow.add_node("executor_agent", executor_agent)
        workflow.add_node("tool_interrupt_node", tool_interrupt_node)
        workflow.add_node("tool_interrupt_update_argument", tool_interrupt_update_argument)
        workflow.add_node("final_response", final_response)
        if flags["response_formatting_flag"]:
            workflow.add_node("formatter", lambda state: InferenceUtils.format_for_ui_node(state, llm))

        if evaluation_flag:
            workflow.add_node("evaluator_agent", evaluator_agent)
        if validator_flag:
            workflow.add_node("validator_agent", validator_agent_node)
        
        # Define the workflow sequence
        workflow.add_edge(START, "generate_past_conversation_summary")
        workflow.add_edge("generate_past_conversation_summary", "executor_agent") 
 
        workflow.add_conditional_edges(
            "executor_agent",
            tool_interrupt_router, # Use the consolidated router
            ["tool_interrupt_node", "final_response"] + (["validator_agent"] if validator_flag else []) + (["evaluator_agent"] if evaluation_flag else [])
        )
       
 
        workflow.add_conditional_edges(
            "tool_interrupt_node",
            tool_interrupt_node_decision,
            ["tool_interrupt_update_argument", "executor_agent"]
        )
 
        workflow.add_conditional_edges(
            "tool_interrupt_update_argument",
            tool_interrupt_router, # Use the consolidated router here as well
            ["tool_interrupt_node", "final_response"] + (["validator_agent"] if validator_flag else []) + (["evaluator_agent"] if evaluation_flag else [])
        )
       
     
        if evaluation_flag:
            workflow.add_conditional_edges(
                "evaluator_agent",
                evaluator_decision,
                ["executor_agent", "final_response"]
            )

        if validator_flag:
            # Define possible targets based on enabled flags
            validator_targets = ["executor_agent", "final_response"]
            if evaluation_flag:
                validator_targets.append("evaluator_agent")
            
            workflow.add_conditional_edges(
                "validator_agent",
                validator_decision_node,
                validator_targets
            )
       
        if flags["response_formatting_flag"]:
            workflow.add_edge("final_response", "formatter")
            workflow.add_edge("formatter", END)
        else:
            workflow.add_edge("final_response", END)
 
        log.info("Executor Agent workflow built successfully")
        return workflow
    

