# © 2024-25 Infosys Limited, Bangalore, India. All Rights Reserved.
import json
import asyncio
from typing import Dict
from langgraph.types import interrupt
from langgraph.graph import StateGraph, START, END
from langchain_core.messages import AIMessage, ChatMessage

from langgraph.types import StreamWriter
from src.utils.helper_functions import get_timestamp
from src.inference.inference_utils import InferenceUtils
from src.inference.base_agent_inference import BaseWorkflowState, BaseMetaTypeAgentInference
from telemetry_wrapper import logger as log

from src.inference.inference_utils import EpisodicMemoryManager
from src.prompts.prompts import online_agent_evaluation_prompt

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




class MetaAgentInference(BaseMetaTypeAgentInference):
    """
    Implements the LangGraph workflow for 'meta_agent' type.
    """

    def __init__(self, inference_utils: InferenceUtils):
        super().__init__(inference_utils)


    async def _build_agent_and_chains(self, llm, agent_config, checkpointer = None, tool_interrupt_flag: bool = False):
        """
        Builds the agent and chains for the Meta workflow.
        """
        worker_agent_ids = agent_config["TOOLS_INFO"]
        system_prompt = agent_config["SYSTEM_PROMPT"]
        meta_agent, _ = await self._get_react_agent_as_supervisor_agent(
            llm=llm,
            system_prompt=system_prompt.get("SYSTEM_PROMPT_META_AGENT", ""),
            worker_agent_ids=worker_agent_ids,
            checkpointer=checkpointer,
            interrupt_tool=tool_interrupt_flag
        )

        chains = {
            "llm": llm,
            "meta_agent": meta_agent
        }
        return chains

    async def _build_workflow(self, chains: dict, flags: Dict[str, bool] = {}) -> StateGraph:
        """
        Builds the LangGraph workflow for a Meta agent.
        """
        tool_interrupt_flag = flags.get("tool_interrupt_flag", False)
        evaluation_flag = flags.get("evaluation_flag", False)

        llm = chains.get("llm", None)
        meta_agent = chains.get("meta_agent", None)

        if not llm or not meta_agent:
            raise ValueError("Required chains (llm, meta_agent) are missing.")

        # Nodes

        async def generate_past_conversation_summary(state: MetaWorkflowState, writer:StreamWriter):
            """Generates past conversation summary from the conversation history."""
           
            strt_tmstp = get_timestamp()
            conv_summary = ""
            errors = []
            
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
            try:
                if state["reset_conversation"]:
                    state["ongoing_conversation"].clear()
                    state["executor_messages"].clear()
                    log.info(f"Conversation history for session {state['session_id']} has been reset.")
                else:
                    if state["context_flag"]==False:
                    
                        return{
                            'past_conversation_summary': "No past conversation summary available.",
                            'query': current_state_query.content,
                            'ongoing_conversation': current_state_query,
                            'executor_messages': current_state_query,
                            'response': None,
                            'evaluation_score': None,
                            'evaluation_feedback': None,
                            'epoch': 0,
                            'start_timestamp': strt_tmstp,
                            'errors': errors,
                            'user_update_events': []
                        }
                    # Get summary via ChatService
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
                'ongoing_conversation': current_state_query,
                'executor_messages': current_state_query,
                'response': None,
                'evaluation_score': None,
                'evaluation_feedback': None,
                'epoch': 0,
                'start_timestamp': strt_tmstp,
                'errors': errors,
                'user_update_events': []
            }

        async def meta_agent_node(state: MetaWorkflowState,writer:StreamWriter):
            """
            Creates a meta agent that supervises the worker agents.
            """
            
            thread_id = await self.chat_service._get_thread_id(state['agentic_application_id'], state['session_id'])
            internal_thread = await self.chat_service._get_thread_config("inside" + thread_id)
            agent_id = state['agentic_application_id']
            # Use the standard episodic memory function
            query = state["query"]
            messages = await InferenceUtils.prepare_episodic_memory_context(state["mentioned_agent_id"] if state["mentioned_agent_id"] else agent_id, query)
            
            try:
                formatter_node_prompt = ""
                if state["response_formatting_flag"]:
                    formatter_node_prompt = "You are an intelligent assistant that provides data for a separate visualization tool. When a user asks for a chart, table, image, or any other visual element, you must not attempt to create the visual yourself in text. Your sole responsibility is to generate the raw, structured data. For example, for a chart, provide the JSON data; for an image, provide the <img> tag with a source URL; for a table, provide the data as a list of lists. Your output will be fed into another program that will handle the final formatting and display."
                
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
                    writer({"Node Name": "Thinking...", "Status": "Started"})
                    stream_source = meta_agent.astream({"messages": [("user", formatted_query.strip())]}, internal_thread)

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
                                writer({"raw": {"executor_agent": message.tool_calls}, "content": f"Agent is calling sub-agents"})
                                tool_call = message.tool_calls[0]
                                writer({"Node Name": "Agent Call", "Status": "Started", "Agent Name": tool_call['name'], "Agent Arguments": tool_call['args']})
                                tool_name = tool_call["name"]
                                tool_args = tool_call["args"]

                                if tool_args:   # Non-empty dict means arguments exist
                                    if isinstance(tool_args, dict):
                                        args_str = ", ".join(f"{k}={v}" for k, v in tool_args.items())
                                    else:
                                        args_str = str(tool_args)
                                    tool_call_content = f"Agent called the SubAgent  '{tool_name}', passing arguments: {args_str}."
                                else:
                                    tool_call_content = f"Agent called the SubAgent '{tool_name}', passing no arguments."

                                writer({"content": tool_call_content})
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
            except Exception as e:
                error = f"Error Occurred in Meta Agent: {e}"
                writer({"Node Name": "Thinking...", "Status": "Failed"})
                log.error(error, exc_info=True) # exc_info=True gives you the full traceback in logs
                return {"errors": error}
                
            # Fallback handling if agent produced no messages
            if not final_content_parts:
                log.warning(f"Meta Agent produced no messages for session {state['session_id']}. Using fallback response.")
                final_ai_message = AIMessage(content=f"I'm unable to generate a detailed response right now. Reattempting improvement cycle {state.get('epoch',0)}. Query: {query}")
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
                writer({"Node Name": "Thinking...", "Status": "Completed"})  

            return {
                "response": final_ai_message.content,
                "executor_messages":final_content_parts
            }

        async def tool_interrupt_router(state: MetaWorkflowState):
            thread_id = await self.chat_service._get_thread_id(state['agentic_application_id'], state['session_id'])
            internal_thread = await self.chat_service._get_thread_config("inside" + thread_id)

            agent_state = await meta_agent.aget_state(internal_thread)
            has_active_tasks = agent_state.tasks != ()
            if tool_interrupt_flag and has_active_tasks:
                log.info(f"[{state['session_id']}] Agent planning tool with interruption enabled, routing to tool_interrupt_node.")
                return "tool_interrupt_node"
            elif evaluation_flag:
                return "evaluator_agent"
            else:
                return "final_response_node"

        async def tool_interrupt_node(state: MetaWorkflowState, writer: StreamWriter):
            """Asks the human if the plan is ok or not"""
            if tool_interrupt_flag:
              
                is_approved = interrupt("approved?(yes/feedback)")
                writer({"raw": {"agent_verifier": "Please confirm to execute the agent"}, "content": "Agent execution requires confirmation. Please approve to proceed."})
                if is_approved =="yes":
                    writer({"raw": {"agent_verifier": "User approved the agent execution by clicking the thumbs up button"}, "content": "User approved the agent execution by clicking the thumbs up button"})
            else:
                is_approved = "yes"
            return {"tool_feedback": is_approved, "is_tool_interrupted": True}
        
        async def tool_interrupt_node_decision(state: MetaWorkflowState):
            if state["tool_feedback"] == 'yes':
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
                    "timestamp": get_timestamp()
                }
            except Exception as e:
                event = {"tool_name": tool_name, "message": new_ai_msg.content, "error": str(e), "timestamp": get_timestamp()}


            await meta_agent.aupdate_state(
                internal_thread,
                {"messages": [new_ai_msg]}
            )
            
            #executor_agent_response = await react_agent.ainvoke(None, internal_thread)
            executor_agent_response = {"messages":[]}
            final_content_parts=[new_ai_msg]
            stream_source = meta_agent.astream(None, internal_thread)
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

            # Build structured event for multi-update tracking and persist into workflow state
            
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
                writer({"Node Name": "Thinking...", "Status": "Completed"}) 
            return {
                "response": final_ai_message.content,
                #"response": executor_agent_response.get("messages", [{}])[-1].get("content", ""),
                "executor_messages": final_content_parts,
                "user_update_events": existing_events
            }

        async def final_response_node(state: MetaWorkflowState,writer:StreamWriter):
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
                asyncio.create_task(self.chat_service.update_preferences_and_analyze_conversation(user_input=state["query"], llm=llm, agentic_application_id=state["agentic_application_id"], session_id=state["session_id"]))
                if (len(state["ongoing_conversation"])+1)%8 == 0:
                    log.debug("Storing chat summary")
                    asyncio.create_task(self.chat_service.get_chat_summary(
                        agentic_application_id=state["agentic_application_id"],
                        session_id=state["session_id"],
                        llm=llm
                    ))
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
                "errors":errors
            }
        
        async def evaluator_agent(state: MetaWorkflowState,writer:StreamWriter):
            """
            Evaluates the agent response across multiple dimensions and provides scores and feedback.
            """
            writer({"Node Name": "Evaluating Response", "Status": "Started"})
            log.info(f"🎯EVALUATOR AGENT CALLED for session {state['session_id']}")
            
            agent_evaluation_prompt = online_agent_evaluation_prompt
            
            try:
                # Build effective query incorporating any user-updated tool feedback/query modifications
                if (
                    state.get("is_tool_interrupted")
                    and state.get("tool_feedback")
                    and state.get("tool_feedback") != 'yes'
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
                writer({"raw": {"evaluator_agent": evaluation_data}, "content": f"Evaluator agent completed with score: {aggregate_score}"})
                writer({"Node Name": "Evaluating Response", "Status": "Completed"})
                return {
                    "evaluation_score": aggregate_score,
                    "evaluation_feedback": compiled_feedback,
                    "executor_messages": ChatMessage(
                        content=[{
                            "evaluation_score": aggregate_score,
                            "evaluation_details": evaluation_data,
                            "feedback": compiled_feedback
                        }],
                        role="evaluator-response"
                    ),
                    "is_tool_interrupted": False  # Reset to allow fresh execution
                }
                
            except json.JSONDecodeError as e:
                writer({"Node Name": "Evaluating Response", "Status": "Failed"})
                log.error(f"Failed to parse evaluator JSON response for session {state['session_id']}: {e}")
                writer({"raw": {"evaluator_error": str(e)}, "content": "Evaluator agent failed due to JSON parsing error."})
                return {
                    "evaluation_score": 0.3,
                    "evaluation_feedback": "Evaluation failed due to JSON parsing error. Please review the response format and content quality.",
                    "executor_messages": ChatMessage(
                        content="Evaluation failed - JSON parsing error",
                        role="evaluator-error"
                    ),
                    "is_tool_interrupted": False  # Reset to allow fresh execution
                }
            except Exception as e:
                writer({"Node Name": "Evaluating Response", "Status": "Failed"})
                log.error(f"Evaluator agent failed for session {state['session_id']}: {e}")
                writer({"raw": {"evaluator_error": str(e)}, "content": "Evaluator agent failed due to an error."})
                return {
                    "evaluation_score": 0.3,
                    "evaluation_feedback": f"Evaluation failed due to error: {str(e)}",
                    "executor_messages": ChatMessage(
                        content=f"Evaluation failed: {str(e)}",
                        role="evaluator-error"
                    ),
                    "is_tool_interrupted": False  # Reset to allow fresh execution
                }

        async def evaluator_decision(state: MetaWorkflowState):
            """
            Decides whether to return the final response or continue with improvement cycle
            based on evaluation score and threshold.
            """
            evaluation_threshold = 0.7  # Configurable threshold
            max_evaluation_epochs = 3   # Maximum number of evaluation improvement cycles
            
            # Get current evaluation epoch
            current_epoch = state.get("evaluation_attempts", 0)
            evaluation_score = state.get("evaluation_score", 0.0)
            response_content = state.get("response")
           
            
            # Decision logic
            if evaluation_score >= evaluation_threshold or current_epoch >= max_evaluation_epochs:
                log.info(f"Evaluation passed for session {state['session_id']} - Score: {evaluation_score}, Epoch: {current_epoch}")
                return "final_response_node"
            else:
                log.info(f"Evaluation failed for session {state['session_id']} - Score: {evaluation_score}, Epoch: {current_epoch}. Routing for improvement (increment epoch).")
                return "increment_epoch"

        async def increment_epoch(state: MetaWorkflowState):
            """Increments the evaluation epoch counter."""
            new_epoch = state.get("epoch", 0) + 1
            log.info(f"Incrementing evaluation epoch to {new_epoch}")
            return {"epoch": new_epoch}
        
        ### Build Graph (Workflow)
        workflow = StateGraph(MetaWorkflowState)
        workflow.add_node("generate_past_conversation_summary", generate_past_conversation_summary)
        workflow.add_node("meta_agent_node", meta_agent_node)
        workflow.add_node("final_response_node", final_response_node)

        if flags["response_formatting_flag"]:
            workflow.add_node("formatter", lambda state: InferenceUtils.format_for_ui_node(state, llm))

        workflow.add_node("tool_interrupt_node", tool_interrupt_node)
        workflow.add_node("tool_interrupt_update_argument", tool_interrupt_update_argument)

        if evaluation_flag:
            workflow.add_node("evaluator_agent", evaluator_agent)
            workflow.add_node("increment_epoch", increment_epoch)

        # Define the workflow sequence
        workflow.add_edge(START, "generate_past_conversation_summary")
        workflow.add_edge("generate_past_conversation_summary", "meta_agent_node")
        

        workflow.add_conditional_edges(
            "meta_agent_node",
            tool_interrupt_router,
            ["tool_interrupt_node", "final_response_node"] + (["evaluator_agent"] if evaluation_flag else [])
        )
        workflow.add_conditional_edges(
            "tool_interrupt_node",
            tool_interrupt_node_decision,
            ["meta_agent_node", "tool_interrupt_update_argument"]
        )
        workflow.add_conditional_edges(
            "tool_interrupt_update_argument",
            tool_interrupt_router,
            ["tool_interrupt_node", "final_response_node"] + (["evaluator_agent"] if evaluation_flag else [])
        )
        # Add conditional routing from meta_agent_node based on evaluation flag
        if evaluation_flag:
            workflow.add_conditional_edges(
                "evaluator_agent",
                evaluator_decision,
                {"increment_epoch": "increment_epoch", "final_response_node": "final_response_node"}
            )
            workflow.add_edge("increment_epoch", "meta_agent_node")
        
        if flags["response_formatting_flag"]:
            workflow.add_edge("final_response_node", "formatter")
            workflow.add_edge("formatter", END)
        else:
            workflow.add_edge("final_response_node", END)

        log.info("Meta Agent workflow built successfully")
        return workflow



