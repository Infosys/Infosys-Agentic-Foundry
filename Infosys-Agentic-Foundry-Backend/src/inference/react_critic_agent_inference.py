# © 2024-25 Infosys Limited, Bangalore, India. All Rights Reserved.
import os
import json
from typing import Dict, List, Optional, Literal,Any
from fastapi import HTTPException
import asyncio
from langgraph.types import interrupt
from langgraph.graph import StateGraph, START, END
from langchain_core.messages import AIMessage, ChatMessage

from langgraph.types import StreamWriter
from src.utils.helper_functions import get_timestamp, build_effective_query_with_user_updates
from src.inference.inference_utils import InferenceUtils
from src.inference.base_agent_inference import BaseWorkflowState, BaseAgentInference
from src.schemas import AdminConfigLimits
from src.config.constants import Limits
from telemetry_wrapper import logger as log
from src.prompts.prompts import online_agent_evaluation_prompt, feedback_lesson_generation_prompt
from src.inference.inference_utils import EpisodicMemoryManager
from src.database.kafka_handler import listen_for_tool_response


class ReactCriticWorkflowState(BaseWorkflowState):
    """
    State specific to the React agent workflow.
    Extends BaseWorkflowState with any React-specific attributes if needed.
    """
    response_quality_score: float
    critique_points: str
    epoch: int = 0
    preference: str
    tool_feedback: str = None
    is_tool_interrupted: bool = False
    tool_calls: Optional[List[str]]
    evaluation_score: float = None
    evaluation_feedback: str = None
    validation_score: float = None
    validation_feedback: str = None
    workflow_description: str = None
    user_update_events: list = []
    tool_result: str = None
    episodic_memory_messages: list = []  # Pre-fetched episodic memory for tracing 




class ReactCriticAgentInference(BaseAgentInference):
    """
    Implements the LangGraph workflow for 'multi_agent' type.
    """

    def __init__(self, inference_utils: InferenceUtils):
        super().__init__(inference_utils)


    async def _build_agent_and_chains(self, llm, agent_config, checkpointer = None, tool_interrupt_flag: bool = False, message_queue: bool = False, session_id: str = None, agent_id: str = None, context_flag: bool = True, file_context_management_flag: bool = False):
        """
        Builds the agent and chains for the React-Critic-Agent workflow.
        
        Args:
            file_context_management_flag: If True, use file-based context management (AgentShell) instead of old conversation fetching.
        """
        tool_ids = agent_config["TOOLS_INFO"]
        system_prompt_config = agent_config["SYSTEM_PROMPT"]
        # Use agent_id from parameter or fallback to config
        agent_id = agent_id if agent_id else agent_config.get("AGENT_ID", None)
        agent_name = agent_config.get("AGENT_NAME", "")

        # Determine which system prompt to use based on file_context_management_flag
        if file_context_management_flag:
            # Try to load file-context prompt from file (using agent_name, same as onboard)
            safe_agent_name = "".join(c if c.isalnum() or c in ('-', '_') else '_' for c in agent_name)
            file_context_prompt_path = os.path.join(
                "agent_workspaces", "file_context_prompts", f"{safe_agent_name}_file_context_prompt.md"
            )
            if os.path.exists(file_context_prompt_path):
                with open(file_context_prompt_path, "r", encoding="utf-8") as f:
                    executor_system_prompt = f.read()
                log.info(f"📄 Loaded file-context prompt from: {file_context_prompt_path}")
            else:
                # Fallback to DB prompt if file doesn't exist
                executor_system_prompt = system_prompt_config.get("SYSTEM_PROMPT_EXECUTOR_AGENT", "")
                log.warning(f"⚠️ File-context prompt not found at {file_context_prompt_path}, using DB prompt")
        else:
            # Use regular DB prompt
            executor_system_prompt = system_prompt_config.get("SYSTEM_PROMPT_EXECUTOR_AGENT", "")
        
        critic_system_prompt = system_prompt_config.get("SYSTEM_PROMPT_CRITIC_AGENT", "").replace("{", "{{").replace("}", "}}")

        # Executor Agent
        executor_agent, tool_list, fs_memory = await self._get_react_agent_as_executor_agent(
                                        llm,
                                        system_prompt=executor_system_prompt,
                                        checkpointer=checkpointer,
                                        tool_ids=tool_ids,
                                        interrupt_tool=tool_interrupt_flag,
                                        message_queue=message_queue,
                                        session_id=session_id,
                                        agent_id=agent_id,
                                        context_flag=context_flag,
                                        file_context_management_flag=file_context_management_flag
                                    )
        # Critic Agent Chains
        critic_chain_json, critic_chain_str = await self._get_chains(llm, critic_system_prompt)

        log.info("React Critic Agent - Chains built successfully")

        chains = {
            "llm": llm,
            "agent_executor": executor_agent,
            "tool_list": tool_list,
            "fs_memory": fs_memory,

            "critic_chain_json": critic_chain_json,
            "critic_chain_str": critic_chain_str,
        }

        return chains
    
    async def _build_workflow(self, chains: dict, flags: Dict[str, bool] = {}) -> StateGraph:
        """
        Builds the LangGraph workflow for a React-Critic Agent.
        """
        # DEBUG: Log the actual flags received
        
        tool_interrupt_flag = flags.get("tool_interrupt_flag", False)
        evaluation_flag = flags.get("evaluation_flag", False)
        validator_flag = flags.get("validator_flag", False)
        message_queue = flags.get("message_queue", False)
        

        inference_config: AdminConfigLimits = flags.get("inference_config", AdminConfigLimits())

        # DEBUG: Log the extracted flag values
        log.info(f"Extracted flags - validator_flag: {validator_flag}, evaluation_flag: {evaluation_flag}, tool_interrupt_flag: {tool_interrupt_flag}, message_queue: {message_queue}")

        llm = chains.get("llm", None)
        executor_agent = chains.get("agent_executor", None)
        tool_list = chains.get("tool_list", [])

        critic_chain_json = chains.get("critic_chain_json", None)
        critic_chain_str = chains.get("critic_chain_str", None)

        if not llm or not executor_agent or not critic_chain_json or not critic_chain_str :
            raise HTTPException(status_code=500, detail="Required chains or agent executor are missing")

        # Nodes

        async def generate_past_conversation_summary(state: ReactCriticWorkflowState,writer: StreamWriter):
            """Generates past conversation summary from the conversation history."""
           
            strt_tmstp = get_timestamp()
            conv_summary = new_preference = ""
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
            agent_details = await self.agent_service.agent_repo.get_agent_record(state["agentic_application_id"])
            workflow_description = agent_details[0]["agentic_application_workflow_description"]
            try:
                if state["reset_conversation"]:
                    state["executor_messages"].clear()
                    state["ongoing_conversation"].clear()
                    log.info(f"Conversation history for session {state['session_id']} has been reset.")
                else:
                    if state["context_flag"]==False:
                      
                        return{
                        'past_conversation_summary': "",
                        'query': getattr(current_state_query, 'content', ''),
                        'ongoing_conversation': current_state_query,
                        'executor_messages': current_state_query,
                        'preference': "No specific preferences provided.",
                        'response': None,
                        'start_timestamp': strt_tmstp,
                        'response_quality_score': None,
                        'critique_points': None,
                        'epoch': 0,
                        'validation_attempts': 0,
                        'evaluation_attempts': 0,
                        'evaluation_score': None,
                        'evaluation_feedback': None,
                        'validation_score': None,
                        'validation_feedback': None,
                        'workflow_description': workflow_description,
                        'errors': errors,
                        'user_update_events': [],
                        'tool_result': None
                    }
                    
                    # Check file_context_management_flag - if True, use file-based memory tool instead of conversation fetching
                    if state.get("file_context_management_flag", False):
                        log.info(f"File context management flag is set to True for session {state['session_id']}. Using file-based memory tool.")
                        return{
                            'past_conversation_summary': "",
                            'query': getattr(current_state_query, 'content', ''),
                            'ongoing_conversation': [],  # Don't pass ongoing conversation when using file-based memory
                            'executor_messages': current_state_query,
                            'preference': "No specific preferences provided.",
                            'response': None,
                            'start_timestamp': strt_tmstp,
                            'response_quality_score': None,
                            'critique_points': None,
                            'epoch': 0,
                            'validation_attempts': 0,
                            'evaluation_attempts': 0,
                            'evaluation_score': None,
                            'evaluation_feedback': None,
                            'validation_score': None,
                            'validation_feedback': None,
                            'workflow_description': workflow_description,
                            'errors': errors,
                            'user_update_events': [],
                            'tool_result': None
                        }
                    
                    # Get summary via ChatService
                    writer({"Node Name": "Generating Context", "Status": "Started"})
                    conv_summary = await self.chat_service.get_chat_conversation_summary(
                        agentic_application_id=state["agentic_application_id"],
                        session_id=state["session_id"]
                    )
                    log.debug("Chat summary fetched successfully")
                    conv_summary = conv_summary or {}
                
                    log.debug("getting preferences")

                    new_preference = conv_summary.get("preference", "")
                    conv_summary = conv_summary.get("summary", "")
                writer({"raw": {"past_conversation_summary": conv_summary}, "content": conv_summary[:100] + ("..." if len(conv_summary) > 100 else "")}) if conv_summary else writer({"raw": {"past_conversation_summary": conv_summary}, "content": "No past conversation summary available."})
                writer({"Node Name": "Generating Context", "Status": "Completed"})
                log.debug("Preferences updated successfully")
            except Exception as e:
                error = f"Error occurred while generating past conversation summary: {e}"
                writer({"Node Name": "Generating Context", "Status": "Failed"})
                log.error(error)
                errors.append(error)

            log.info(f"Generated past conversation summary for session {state['session_id']}.")
            
            new_state = {
                'past_conversation_summary': conv_summary,
                'query': current_state_query.content,
                'ongoing_conversation': current_state_query,
                'executor_messages': current_state_query,
                'preference': new_preference,
                'response': None,
                'start_timestamp': strt_tmstp,
                'response_quality_score': None,
                'critique_points': None,
                'epoch': 0,
                'errors': errors,
                'validation_attempts': 0,
                'evaluation_attempts': 0,
                'evaluation_score': None,
                'evaluation_feedback': None,
                'validation_score': None,
                'validation_feedback': None,
                'workflow_description': workflow_description,
                'user_update_events': [],
                'tool_result': None,
                'episodic_memory_messages': []
            }        
            return new_state

        async def prepare_episodic_memory_node(state: ReactCriticWorkflowState, writer: StreamWriter):
            """Prepares episodic memory context - traced as a separate node by Phoenix."""
            writer({"Node Name": "Preparing Episodic Memory", "Status": "Started"})
            
            try:
                query = await self.inference_utils.add_prompt_for_feedback(state["query"])
                query = query.content
                agent_id = state['agentic_application_id']
                
                # Fetch episodic memory context
                log.info(f"[{state['session_id']}] Fetching episodic memory context...")
                messages = await InferenceUtils.prepare_episodic_memory_context(
                    state["mentioned_agent_id"] if state["mentioned_agent_id"] else agent_id, 
                    query
                )
                log.info(f"[{state['session_id']}] Episodic memory context prepared: {len(messages)} messages")
                
                writer({"Node Name": "Preparing Episodic Memory", "Status": "Completed"})
                return {"episodic_memory_messages": messages}
            except Exception as e:
                log.error(f"Error preparing episodic memory: {e}", exc_info=True)
                writer({"Node Name": "Preparing Episodic Memory", "Status": "Failed"})
                return {"episodic_memory_messages": [], "errors": state["errors"] + [f"Episodic memory error: {e}"]}

        
        async def executor_agent_node(state: ReactCriticWorkflowState, writer: StreamWriter):
            """Handles query execution and returns the agent's response."""
            
            query = await self.inference_utils.add_prompt_for_feedback(state["query"])
            query = query.content
            thread_id = await self.chat_service._get_thread_id(state['agentic_application_id'], state['session_id'])
            internal_thread = await self.chat_service._get_thread_config("inside" + thread_id)
            errors = state["errors"]
            agent_id = state['agentic_application_id']
            
            # Use pre-fetched episodic memory from state (already prepared in separate traced node)
            messages = state.get("episodic_memory_messages", [])
            log.info(f"[{state['session_id']}] Using {len(messages)} pre-fetched episodic memory messages")

            try:
                critic_messages = ""
                formatter_node_prompt = ""
                context_feedback_message = ""
                # feedback_learning_data = await self.feedback_learning_service.get_approved_feedback(agent_id=state["agentic_application_id"])
                # feedback_msg = await self.inference_utils.format_feedback_learning_data(feedback_learning_data)
                # Add evaluation guidance if available
                if evaluation_flag and state.get("evaluation_feedback"):
                    context_feedback_message = f"""
    **PREVIOUS EVALUATION FEEDBACK:**
    The last response was evaluated with a score of {state["evaluation_score"]:.2f}.
    Here is the detailed feedback:
    {state["evaluation_feedback"]}
    Please carefully review this feedback and adjust your reasoning and response generation to address the identified issues and improve the overall quality.
    """
                
                # Add validation guidance if available  
                validation_guidance = ""
                if state.get("validation_feedback"):
                    validation_guidance = f"""

--- Validation Feedback ---
Based on the validation results, improve your response considering the following points:
{state["validation_feedback"]}
--- End Validation Feedback ---

Ensure you address the validation concerns identified above.
"""
                    log.info(f"Executor agent incorporating validation feedback for epoch {state.get('epoch', 0)}.")
                
                # Handle response formatting flag
                if state["response_formatting_flag"]:
                    formatter_node_prompt = "\n\nYou are an intelligent assistant that provides data for a separate visualization tool. When a user asks for a chart, table, image, or any other visual element, you must not attempt to create the visual yourself in text. Your sole responsibility is to generate the raw, structured data. For example, for a chart, provide the JSON data; for an image, provide the <img> tag with a source URL; for a table, provide the data as a list of lists. Your output will be fed into another program that will handle the final formatting and display."
                    
                # Handle critic feedback if available
                if state.get("response_quality_score", None) is not None:
                    critic_messages = f"""
Final Response Obtained:
{state["response"]}

Critic Agent's Response Quality Score:
{state["response_quality_score"]}

Critic Agent Feedback:
{await self.inference_utils.format_list_str(state["critique_points"]) if state.get("critique_points") else "No critique points available."}
"""

                # Handle tool_result from message queue
                if state['tool_result']:
                    formatted_query = f"Previous tool result={state['tool_result']}"
                else:
                    formatted_query = f"""\
Past Conversation Summary:
{state["past_conversation_summary"]}

Ongoing Conversation:
{await self.chat_service.get_formatted_messages(state["ongoing_conversation"]) if state["context_flag"] else "No ongoing conversation."}


Follow these preferences for every step:
Preferences:
{state["preference"]}
- When applicable, use these instructions to guide your responses to the user's query.



{formatter_node_prompt}

{context_feedback_message}

{validation_guidance}


User Query:
{messages}
{critic_messages}
"""


                
                stream_source = None
                if state["is_tool_interrupted"]:
                    final_content_parts = []
                    stream_source = executor_agent.astream(None, internal_thread)
                else:
                    final_content_parts = [ChatMessage(content=formatted_query, role="context")]
                    writer({"Node Name": "Thinking...", "Status": "Started"})
                    stream_source = executor_agent.astream({"messages": [("user", formatted_query.strip())]}, internal_thread)

                async for msg in stream_source:                            
                    if isinstance(msg, dict) and "agent" in msg:
                        agent_output = msg.get("agent", {})
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
                        # writer({"raw": {"executor_agent_node": msg}, "content": f"Agent processing: {msg.get('agent', {}).get('messages', [{}])[-1].get('content', 'Agent working...') if isinstance(msg, dict) and 'agent' in msg else str(msg)}"})
                        if "agent" in msg:
                            final_content_parts.extend(msg["agent"]["messages"])
                
                
            except Exception as e:
                error = f"Error Occurred in Executor Agent: {e}"
                writer({"Node Name": "Thinking...", "Status": "Failed"})
                log.error(error, exc_info=True) # exc_info=True gives you the full traceback in logs
                errors.append(error)
                return {"errors": errors}
                
            log.info("Executor Agent response generated successfully")
                    
                # 1. Join the collected parts to create the complete final response string.
            

            # 2. **THIS IS THE KEY FIX**: Create a single, clean AI message object from the final string.
            #    This is the valid format LangGraph expects.
            final_ai_message = final_content_parts[-1]
            if  final_ai_message.type=="ai" and final_ai_message.tool_calls==[]:
                final_content_parts = final_content_parts[:-1]
                
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
                # 3. Return a list containing ONLY the valid message object.
                #    Do NOT return the raw `all_stream_chunks`.
                "executor_messages": final_content_parts,
                "errors": errors,
            }

        
        async def evaluator_agent(state: ReactCriticWorkflowState,writer: StreamWriter):
            """
            Evaluates the agent response across multiple dimensions and provides scores and feedback.
            """
            log.info(f"🎯 EVALUATOR AGENT CALLED for session {state['session_id']}")
            
            # Increment evaluation attempts counter at the start
            evaluation_attempts = state.get("evaluation_attempts", 0) + 1
            writer({"Node Name": "Evaluating Response", "Status": "Started"})
            # Increment evaluation attempts counter at the start
            evaluation_attempts = state.get("evaluation_attempts", 0) + 1
            agent_evaluation_prompt = online_agent_evaluation_prompt      
            try:
                # Build effective query considering user_update_events tied to this query
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
                    workflow_description=state.get("workflow_description", "Multi-agent workflow with planner, executor, and critic components")
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
                writer({"raw": {"evaluator_agent_response": evaluation_data}, "content": f"Evaluator agent completed with score {aggregate_score:.2f}"})
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
                    "evaluation_attempts": evaluation_attempts,
                    "executor_messages": ChatMessage(
                        content="Evaluation failed - JSON parsing error",
                        role="evaluator-error"
                    ),
                    "is_tool_interrupted": False
                }
            except Exception as e:
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
                    "is_tool_interrupted": False
                }

        async def validator_agent_node(state: ReactCriticWorkflowState, writer: StreamWriter):
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


    
        async def validator_decision_node(state: ReactCriticWorkflowState):
            """
            Decides the next step based on validation results and current epoch.
            Saves feedback ONLY if the final result fails the criteria.
            """
            validation_threshold = inference_config.validation_score_threshold
            max_validation_epochs = inference_config.max_validation_epochs
            
            current_epoch = state.get("validation_attempts", 0)
            validation_score = state.get("validation_score", 0.0)
            validation_feedback = state.get("validation_feedback", "No validation feedback available")

            # 1. BYPASS LOCK: Prevent double saving if Evaluator loops the graph back here
            if state.get("validator_feedback_response_id"):
                log.info(f"Validator already locked for session {state['session_id']}. Bypassing save.")
                return "evaluator_agent_node" if evaluation_flag else "critic_agent_node"

            # 2. CHECK IF THIS IS THE FINAL STATE (Passed OR exhausted retries)
            is_final_state = (validation_score >= validation_threshold or current_epoch >= max_validation_epochs)

            if is_final_state:
                # 🔄 ONLY Save to DB if it FAILED the threshold
                if validation_score < validation_threshold:
                    try:
                        log.info(f"📉 Validation failed (Score: {validation_score}). Saving failure for learning.")
                        
                        validator_lesson_prompt = feedback_lesson_generation_prompt.format(
                            user_query=state["query"],
                            agent_response=state["response"],
                            feedback_type="VALIDATOR",
                            feedback_score=validation_score,
                            feedback_details=validation_feedback
                        )
                        lesson_response = await llm.ainvoke(validator_lesson_prompt)
                        
                        status = f"[FAILED_AFTER_{current_epoch}_RETRIES]"

                        feedback_result = await self.feedback_learning_service.save_feedback(
                            agent_id=state["agentic_application_id"],
                            query=state["query"],
                            old_final_response=state["response"],
                            old_steps="", 
                            new_final_response=status,
                            feedback=f"[VALIDATOR] Score: {validation_score:.2f} - {validation_feedback}", 
                            new_steps=status,
                            lesson=lesson_response.content,
                            department_name=state.get("department_name")
                        )
                        
                        if feedback_result.get("is_saved") and feedback_result.get("response_id"):
                            state["validator_feedback_response_id"] = feedback_result["response_id"]
                            log.info(f"💾 Validator failure stored with ID: {feedback_result['response_id']}")
                    except Exception as e:
                        log.error(f"❌ Failed to save validator feedback: {e}")
                else:
                    log.info(f"✅ Validation passed (Score: {validation_score}). Skipping DB feedback save.")

                # Proceed to next node (Evaluation or Critic)
                return "evaluator_agent_node" if evaluation_flag else "critic_agent_node"

            # 3. ROUTE FOR IMPROVEMENT (Epoch 0 -> 1)
            else:
                log.info(f"Validation attempt {current_epoch} low ({validation_score}). Retrying.")
                return "executor_agent_node"

            
        async def evaluator_decision(state: ReactCriticWorkflowState):
            """
            Decides whether to return the final response or continue with improvement cycle.
            Saves feedback ONLY if the final result fails the criteria.
            """
            evaluation_threshold = inference_config.evaluation_score_threshold
            max_evaluation_epochs = inference_config.max_evaluation_epochs
            
            current_epoch = state.get("evaluation_attempts", 0)
            evaluation_score = state.get("evaluation_score", 0.0)
            evaluation_feedback = state.get("evaluation_feedback", "No evaluation feedback available")

            # 1. BYPASS LOCK
            if state.get("evaluator_feedback_response_id"):
                log.info(f"Evaluator already locked for session {state['session_id']}. Bypassing save.")
                return "final_response"

            # 2. CHECK IF THIS IS THE FINAL STATE
            is_final_state = (evaluation_score >= evaluation_threshold or current_epoch >= max_evaluation_epochs)

            if is_final_state:
                # 🔄 ONLY Save to DB if it FAILED the threshold
                if evaluation_score < evaluation_threshold:
                    try:
                        log.info(f"📉 Evaluation failed (Score: {evaluation_score}). Saving failure for learning.")
                        
                        evaluator_lesson_prompt = feedback_lesson_generation_prompt.format(
                            user_query=state["query"],
                            agent_response=state["response"],
                            feedback_type="EVALUATOR",
                            feedback_score=evaluation_score,
                            feedback_details=evaluation_feedback
                        )
                        lesson_response = await llm.ainvoke(evaluator_lesson_prompt)
                        
                        status = f"[FAILED_AFTER_{current_epoch}_RETRIES]"

                        feedback_result = await self.feedback_learning_service.save_feedback(
                            agent_id=state["agentic_application_id"],
                            query=state["query"],
                            old_final_response=state["response"],
                            old_steps="", 
                            new_final_response=status,
                            feedback=f"[EVALUATOR] Score: {evaluation_score:.2f} - {evaluation_feedback}", 
                            new_steps=status,
                            lesson=lesson_response.content,
                            department_name=state.get("department_name")
                        )
                        
                        if feedback_result.get("is_saved") and feedback_result.get("response_id"):
                            state["evaluator_feedback_response_id"] = feedback_result["response_id"]
                            log.info(f"💾 Evaluator failure stored with ID: {feedback_result['response_id']}")
                    except Exception as e:
                        log.error(f"❌ Failed to save evaluator feedback: {e}")
                else:
                    log.info(f"✅ Evaluation passed (Score: {evaluation_score}). Skipping DB feedback save.")

                return "final_response"

            # 3. ROUTE FOR IMPROVEMENT
            else:
                log.info(f"Evaluation score low ({evaluation_score}). Routing for retry {current_epoch + 1}.")
                state["epoch"] = current_epoch + 1
                return "executor_agent_node"


        async def critic_agent(state: ReactCriticWorkflowState, writer: StreamWriter):
            """
            This function takes a state object containing information about the conversation and the generated response,
            formats it into a query for the critic model, and returns the critic's evaluation of the response.
            """
            writer({"Node Name": "Reviewing Response", "Status": "Started"})
            tool_args_update_context = "" if state.get("tool_feedback", None) in (None, "yes") else (
                            f"""
original_user_query: {state['query']}
tool_update_feedback: {state['tool_feedback']}


- original_user_query: the user's initial question/instruction.
- tool_update_feedback: a free-form statement describing corrected parameters or revised intent.

Your job:
1) Infer the revised/expected query and parameters solely from tool_update_feedback.
2) Treat the revision as the single source of truth. Do NOT proceed with the original query if there is any conflict.
3) Execute using the revised intent/parameters and produce the answer accordingly.

Rules:
- If tool_update_feedback indicates parameter changes (e.g., "a=8 and b=9 were modified into a=8 and b=8"), infer the corrected query (e.g., "what is 8*8") and use the revised parameters.
- If tool_update_feedback states a direct correction (e.g., "expected question was 8*8", "corrected to 8*8"), answer that."""
                        )
            
            # Extract tool calls and outputs from executor messages
            executor_messages = state["executor_messages"]
            tool_calls_data = []
            
            # Iterate through messages to find AI messages with tool calls and corresponding tool messages
            for i, msg in enumerate(executor_messages):
                if hasattr(msg, 'type') and msg.type == "ai" and hasattr(msg, 'tool_calls') and msg.tool_calls:
                    for tool_call in msg.tool_calls:
                        tool_data = {
                            'name': tool_call['name'],
                            'args': tool_call['args'],
                            'id': tool_call['id'],
                            'output': None
                        }
                        
                        # Look for the corresponding tool message with the output
                        for j in range(i + 1, len(executor_messages)):
                            next_msg = executor_messages[j]
                            if (hasattr(next_msg, 'type') and next_msg.type == "tool" and 
                                hasattr(next_msg, 'tool_call_id') and next_msg.tool_call_id == tool_call['id']):
                                tool_data['output'] = next_msg.content
                                break
                        
                        tool_calls_data.append(tool_data)
            
            # Add tool information to context if any tools were used
            if tool_calls_data:
                tool_args_update_context += "\n\nTools used in the response generation:\n"
                for tool_data in tool_calls_data:
                    tool_name = tool_data['name']
                    tool_args = json.dumps(tool_data['args'])
                    tool_output = tool_data['output'] if tool_data['output'] else "No output captured."
                    tool_args_update_context += f"- Tool Name: {tool_name}\n  Arguments: {tool_args}\n  Output: {tool_output}\n"
            
            # Include any user_update_events tied to this query for critic awareness
            updates_lines = []
            for ev in state.get("user_update_events", []):
                if ev.get("query") and ev.get("query") != state.get("query"):
                    continue
                line = (
                    f"message : {ev.get('message','N/A')}\n"
                )
                updates_lines.append(line)

            updates_block = ("\n".join(updates_lines)) if updates_lines else ""

            formatted_query = f'''\
Past Conversation Summary:
{state["past_conversation_summary"]}

Ongoing Conversation:
{await self.chat_service.get_formatted_messages(state["ongoing_conversation"]) if state["context_flag"] else "No ongoing conversation."}

Tools Info:
{await self.tool_service.render_text_description_for_tools(tool_list)}

User Query:
{state["query"]}
{tool_args_update_context}

User Tool Feedback Updates:
{updates_block if updates_block else "No user tool updates in this query."}

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

            writer({"raw": {"Critic Score": critic_response["response_quality_score"]}, "content": f"Critic evaluation score: {critic_response['response_quality_score']}/1.0"})
            critique_content = ', '.join(critic_response['critique_points']) if isinstance(critic_response['critique_points'], list) else str(critic_response['critique_points'])
            if critique_content:
                writer({"raw": {"Critique Points": critic_response["critique_points"]}, "content": f"Critic feedback: {critique_content[:100] + ('...' if len(critique_content) > 100 else '')}"})
            log.info(f"Critic response generated for session {state['session_id']}")
            writer({"Node Name": "Reviewing Response", "Status": "Completed"})
            return {
                "response_quality_score": critic_response["response_quality_score"],
                "critique_points": critic_response["critique_points"],
                "executor_messages": ChatMessage(
                    content=[{
                            "response_quality_score": critic_response["response_quality_score"],
                            "critique_points": critic_response["critique_points"]
                        }],
                    role="critic-response"
                ),
                "epoch": state.get("epoch", 0) + 1
            }

        async def final_response(state: ReactCriticWorkflowState, writer: StreamWriter):
            """
            This function handles the final response of the conversation.
            """
            writer({"Node Name": "Memory Update", "Status": "Started"})
            thread_id = await self.chat_service._get_thread_id(state['agentic_application_id'], state['session_id'])
            internal_thread_id = f"inside{thread_id}"
            asyncio.create_task(self.chat_service.delete_internal_thread(internal_thread_id))
            errors = []
            end_timestamp = get_timestamp()
            try:
                # Save to database
                asyncio.create_task(self.chat_service.save_chat_message(
                                        agentic_application_id=state["agentic_application_id"],
                                        session_id=state["session_id"],
                                        start_timestamp=state["start_timestamp"],
                                        end_timestamp=end_timestamp,
                                        human_message=state["query"],
                                        ai_message=state["response"]
                                    ))
                
                # Save to file (using ChatService method)
                await self.chat_service.save_chat_to_file(
                    agentic_application_id=state["agentic_application_id"],
                    session_id=state["session_id"],
                    start_timestamp=state["start_timestamp"],
                    end_timestamp=end_timestamp,
                    human_message=state["query"],
                    ai_message=state["response"],
                    llm=llm
                )
                
                asyncio.create_task(self.chat_service.update_preferences_and_analyze_conversation(user_input=state["query"], llm=llm, agentic_application_id=state["agentic_application_id"], session_id=state["session_id"]))
                config_limits = await self.admin_config_service.get_limits()
                if (len(state["ongoing_conversation"])+1) % (2*config_limits.chat_summary_interval) == 0:
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
            log.info(f"Final response generated for session {state['session_id']}")
            writer({"raw":{"final_response":"Memory Updated"}, "content":"Memory Updated"})
            writer({"Node Name": "Memory Update", "Status": "Completed"})
            return {
                "ongoing_conversation": final_response_message,
                "executor_messages": final_response_message,
                "end_timestamp": end_timestamp,
                "errors": errors
            }

        async def critic_decision(state:ReactCriticWorkflowState, writer: StreamWriter):
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
            if state["response_quality_score"]>=inference_config.critic_score_threshold or state["epoch"]==inference_config.max_critic_epochs:
                writer({"raw": {"analyzing": "Moving to final response as response feels fine"}, "content": "Analysis complete: Response quality is acceptable, proceeding to final output"})
                return "final_response"
            else:
                writer({"raw": {"analyzing": "Asking agent to work again as it has not met our expectation"}, "content": "Analysis complete: Response needs improvement, requesting agent to revise output"})
                return "executor_agent_node"

        async def interrupt_node_for_tool(state: ReactCriticWorkflowState, writer: StreamWriter):
            """
            Handles tool interrupt/message queue flow.
            - If message_queue is enabled: waits for async tool execution result from Kafka
            - If tool_interrupt_flag is enabled: asks for human approval before tool execution
            """
            import time as time_module
            
            writer({"Node Name": "Tool Interrupt", "Status": "Started"})
            
            tool_result = None
            is_approved = "yes"  # Default approval
            
            thread_id = await self.chat_service._get_thread_id(state['agentic_application_id'], state['session_id'])
            internal_thread = await self.chat_service._get_thread_config("inside" + thread_id)

            agent_state = await executor_agent.aget_state(internal_thread)

            # Extract tool name from agent_state to check against interrupt_items
            current_tool_name = None
            last_message = agent_state.values.get("messages", [])[-1] if agent_state.values.get("messages") else None
            if last_message and hasattr(last_message, 'tool_calls') and last_message.tool_calls:
                current_tool_name = last_message.tool_calls[0].get('name')
                if current_tool_name and current_tool_name.endswith('_message_queue'):
                    current_tool_name = current_tool_name[:-14]  # Remove '_message_queue' suffix
                    log.info(f"[{state['session_id']}] Extracted tool name for Kafka filtering: {current_tool_name}")

            # Message Queue Flow: Tool was sent to Kafka, wait for result
            if message_queue:
                writer({"raw": {"tool_verifier": "Waiting for tool execution result from message queue..."}, "content": "Tool sent to message queue. Waiting for execution result..."})
                log.info(f"[{state['session_id']}] Listening for tool response from Kafka for tool: {current_tool_name}...")
                
                # Use the request start_timestamp from state to filter out old messages
                request_start_time = state.get('start_timestamp')
                if request_start_time:
                    # Convert to unix timestamp if it's a datetime string
                    if isinstance(request_start_time, str):
                        try:
                            from datetime import datetime
                            dt = datetime.fromisoformat(request_start_time.replace('Z', '+00:00'))
                            request_start_time = dt.timestamp()
                        except:
                            request_start_time = time_module.time() - 60  # Fallback: last 60 seconds
                else:
                    request_start_time = time_module.time() - 60  # Fallback: last 60 seconds
                
                tool_result = await listen_for_tool_response(state['session_id'], current_tool_name, request_start_time=request_start_time)
                
                if tool_result:
                    writer({"raw": {"tool_result": tool_result}, "content": f"Tool execution completed. Result received."})
                    log.info(f"[{state['session_id']}] Tool result received: {tool_result[:100]}...")
                    writer({"Node Name": "Tool Interrupt", "Status": "Completed"})
                    return {"tool_result": tool_result}
                else:
                    writer({"raw": {"tool_verifier": "Timeout waiting for tool result"}, "content": "Timeout waiting for tool execution result."})
                    log.warning(f"[{state['session_id']}] Timeout waiting for tool response from Kafka")
            
            # Human-in-the-loop Flow: Ask for approval (only if not message_queue or if both are enabled)
            elif tool_interrupt_flag:
                # Check if we should interrupt: tool_interrupt_flag AND (no interrupt_items OR tool_name is in interrupt_items)
                interrupt_items = state.get("interrupt_items") or []
                should_interrupt = not interrupt_items or (current_tool_name and current_tool_name in interrupt_items)

                if should_interrupt:
                    log.info(f"[{state['session_id']}] Interrupting for tool: {current_tool_name}")
                    is_approved = interrupt("approved?(yes/feedback)") 
                    writer({"raw": {"tool_verifier": "Please confirm to execute the tool"}, "content": "Tool execution requires confirmation. Please approve to proceed."})
                    if is_approved == "yes":
                        writer({"raw": {"tool_verifier": "User approved the tool execution by clicking the thumbs up button"}, "content": "User approved the tool execution by clicking the thumbs up button"})
                    log.info(f"is_approved {is_approved}")
                else:
                    log.info(f"[{state['session_id']}] Tool '{current_tool_name}' not in interrupt_items {interrupt_items}, auto-approving.")
                    is_approved = "yes"
            else:
                log.info(f"[{state['session_id']}] Neither message_queue nor tool_interrupt enabled, auto-approving.")
            
            writer({"Node Name": "Tool Interrupt", "Status": "Completed"})
            return {"tool_feedback": is_approved, "tool_result": None, "is_tool_interrupted": True}

        async def interrupt_node_decision_for_tool(state: ReactCriticWorkflowState):
            # If we have a tool result from message queue, proceed to executor
            if state.get('tool_result'):
                return "executor_agent_node"
            # If user approved (or auto-approved), proceed to executor
            elif state.get("tool_feedback") == 'yes':
                return "executor_agent_node"
            # Otherwise, user wants to update arguments
            else:
                return "tool_interrupt"

        async def tool_interrupt(state: ReactCriticWorkflowState, writer: StreamWriter):

            writer({"raw": {"tool_interrupt_update_argument": "User updated the tool arguments"}, "content": "User updated the tool arguments, updating the agent state accordingly."})
            thread_id = await self.chat_service._get_thread_id(state['agentic_application_id'], state['session_id'])
            internal_thread = await self.chat_service._get_thread_config("inside" + thread_id)
            model_name = state["model_name"]
           
            agent_state = await executor_agent.aget_state(internal_thread)
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

            # Record a user update event for evaluator awareness
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

            # Modify the thread with the new input
            await executor_agent.aupdate_state(
                internal_thread,
                {"messages": [new_ai_msg]}
            )
            # state["executor_messages"].append(new_ai_msg)
            executor_agent_response = {"messages":[]}
            final_content_parts = [new_ai_msg]
            stream_source = executor_agent.astream(None, internal_thread)
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
                    # writer({"raw": {"executor_agent_node": msg}, "content": f"Agent processing: {msg.get('agent', {}).get('messages', [{}])[-1].get('content', 'Agent working...') if isinstance(msg, dict) and 'agent' in msg else str(msg)}"})
                    if "agent" in msg:
                        final_content_parts.extend(msg["agent"]["messages"])
            

            
            final_ai_message = final_content_parts[-1]

            # Append event to user_update_events without mutating original list
            existing_events = list(state.get("user_update_events", []))
            existing_events.append(event)
            if  final_ai_message.type=="ai" and final_ai_message.tool_calls==[]:
                final_content_parts = final_content_parts[:-1]

            writer({"raw": {"tool_interrupt_final_ai_message": final_ai_message.content}, "content": f"Tool execution with user's feedback completed: {final_ai_message.content[:50] + ('...' if len(final_ai_message.content) > 50 else '')}"}) 
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
                "response": final_ai_message.content,
                "executor_messages": final_content_parts,
                "is_tool_interrupted": False,
                "user_update_events": existing_events
            }
        async def route_after_executor(state: ReactCriticWorkflowState) -> str:
            current_epoch = state.get("epoch", 0)
            if current_epoch >= 3:
                return "final_response"

            thread_id = await self.chat_service._get_thread_id(state['agentic_application_id'], state['session_id'])
            internal_thread = await self.chat_service._get_thread_config("inside" + thread_id)
            a = await executor_agent.aget_state(internal_thread)
            evaluation_attempts = state.get("evaluation_attempts", 0)

            # Fixed operator precedence: use parentheses for clarity
            if (tool_interrupt_flag or message_queue) and a.tasks != ():
                log.info(f"[{state['session_id']}] Agent planning tool with interruption enabled, routing to interrupt_node_for_tool.")
                return "interrupt_node_for_tool"
            elif a.tasks == ():  # No pending tool calls
                # Route based on enabled flags
                if validator_flag and evaluation_attempts == 0:
                    log.info(f"Routing to validator_agent (validation enabled)")
                    return "validator_agent_node"
                elif evaluation_flag:
                    log.info(f"Routing to evaluator_agent (evaluation enabled)")
                    return "evaluator_agent_node"
                else:
                    log.info(f"Routing to critic_agent (no validation or evaluation)")
                    return "critic_agent_node"
            else:
                return "interrupt_node_for_tool"



        ### Build Graph
        workflow = StateGraph(ReactCriticWorkflowState)
        workflow.add_node("generate_past_conversation_summary", generate_past_conversation_summary)
        workflow.add_node("prepare_episodic_memory", prepare_episodic_memory_node)
        workflow.add_node("executor_agent_node", executor_agent_node)
        workflow.add_node("final_response", final_response)
        workflow.add_node("tool_interrupt", tool_interrupt)
        workflow.add_node("interrupt_node_for_tool", interrupt_node_for_tool)
        
        if evaluation_flag:
            workflow.add_node("evaluator_agent_node", evaluator_agent)
            log.info("[SUCCESS] Added evaluator_agent node")
        else:
            workflow.add_node("critic_agent_node", critic_agent)
            log.info("[SUCCESS] Added critic_agent node")

        if validator_flag:
            workflow.add_node("validator_agent_node", validator_agent_node)
            log.info("[SUCCESS] Added validator_agent node")
        
        # Debug logging for flag values
        log.info(f"[INFO] Node addition complete - validator_flag={validator_flag}, evaluation_flag={evaluation_flag}")

        workflow.add_edge(START, "generate_past_conversation_summary")
        workflow.add_edge("generate_past_conversation_summary", "prepare_episodic_memory")
        workflow.add_edge("prepare_episodic_memory", "executor_agent_node")

        # Set up routing targets based on enabled flags
        conditional_targets = ["interrupt_node_for_tool", "final_response"]
        if validator_flag:
            conditional_targets.append("validator_agent_node")
        if evaluation_flag:
            conditional_targets.append("evaluator_agent_node")
        if not validator_flag and not evaluation_flag:
            conditional_targets.append("critic_agent_node")

        workflow.add_conditional_edges(
            "executor_agent_node",
            route_after_executor,
            conditional_targets
        )

        # Validator routing (when enabled)
        if validator_flag:
            # Define possible targets based on enabled flags
            validator_targets = ["executor_agent_node"]
            if evaluation_flag:
                validator_targets.append("evaluator_agent_node")
            else:
                validator_targets.append("critic_agent_node")
            
            workflow.add_conditional_edges(
                "validator_agent_node",
                validator_decision_node,
                validator_targets
            )

        if evaluation_flag:
            workflow.add_conditional_edges(
                "evaluator_agent_node",
                evaluator_decision,
                ["final_response","executor_agent_node"]
            )
        else:
            workflow.add_conditional_edges(
                "critic_agent_node",
                critic_decision,
                ["final_response", "executor_agent_node"]
            )

        workflow.add_conditional_edges(
            "interrupt_node_for_tool",
            interrupt_node_decision_for_tool,
            ["executor_agent_node", "tool_interrupt"],
        )
        workflow.add_conditional_edges(
            "tool_interrupt",
            route_after_executor,
            conditional_targets,
        )

        if flags["response_formatting_flag"]:
            workflow.add_node("formatter", lambda state: InferenceUtils.format_for_ui_node(state, llm))

            workflow.add_edge("final_response", "formatter")
            workflow.add_edge("formatter", END)

        else:
            workflow.add_edge("final_response", END)
        
        log.info(" Executor, Critic agent workflow built successfully.")
        return workflow
