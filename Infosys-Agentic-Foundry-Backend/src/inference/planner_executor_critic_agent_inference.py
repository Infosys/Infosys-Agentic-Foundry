# © 2024-25 Infosys Limited, Bangalore, India. All Rights Reserved.
import json
import asyncio
from typing import Dict, List, Optional, Literal
from fastapi import HTTPException
from langgraph.types import interrupt
from langgraph.graph import StateGraph, START, END
from langchain_core.messages import AIMessage, ChatMessage
from langgraph.types import StreamWriter
from src.utils.helper_functions import get_timestamp, build_effective_query_with_user_updates
from src.inference.inference_utils import InferenceUtils
from src.inference.base_agent_inference import BaseWorkflowState, BaseAgentInference
from telemetry_wrapper import logger as log
from src.prompts.prompts import online_agent_evaluation_prompt, feedback_lesson_generation_prompt

class MultiWorkflowState(BaseWorkflowState):
    """
    State specific to the Multi agent workflow.
    Extends BaseWorkflowState with any Multi-Agent specific attributes if needed.
    """
    plan: List[str]
    past_steps_input: List[str]
    past_steps_output: List[str]
    response_quality_score: float
    critique_points: str
    step_idx: int # App Related vars
    preference: str
    tool_feedback: str = None
    is_tool_interrupted: bool = False
    current_query_status: Optional[Literal["plan", "feedback", None]] = None
    epoch: int = 0
    evaluation_score: float = None
    evaluation_feedback: str = None
    validation_score: float = None
    validation_feedback: str = None
    workflow_description: str = None
    user_update_events: list = []

class MultiHITLWorkflowState(MultiWorkflowState):
    is_plan_approved: Optional[Literal["yes", "no", None]] = None
    plan_feedback: Optional[str] = None



class MultiAgentInference(BaseAgentInference):
    """
    Implements the LangGraph workflow for 'multi_agent' type.
    """

    def __init__(self, inference_utils: InferenceUtils):
        super().__init__(inference_utils)


    async def _build_agent_and_chains(self, llm, agent_config, checkpointer = None, tool_interrupt_flag: bool = False):
        """
        Builds the agent and chains for the Multi-Agent workflow.
        """
        tool_ids = agent_config["TOOLS_INFO"]
        system_prompt = agent_config["SYSTEM_PROMPT"]

        planner_system_prompt = system_prompt.get("SYSTEM_PROMPT_PLANNER_AGENT", "").replace("{", "{{").replace("}", "}}")
        replanner_system_prompt = system_prompt.get("SYSTEM_PROMPT_REPLANNER_AGENT", "").replace("{", "{{").replace("}", "}}")
        critic_based_planner_system_prompt = system_prompt.get("SYSTEM_PROMPT_CRITIC_BASED_PLANNER_AGENT", "").replace("{", "{{").replace("}", "}}")

        executor_system_prompt = system_prompt.get("SYSTEM_PROMPT_EXECUTOR_AGENT", "")
        general_query_system_prompt = system_prompt.get("SYSTEM_PROMPT_GENERAL_LLM", "").replace("{", "{{").replace("}", "}}")

        critic_system_prompt = system_prompt.get("SYSTEM_PROMPT_CRITIC_AGENT", "").replace("{", "{{").replace("}", "}}")
        response_generator_system_prompt = system_prompt.get("SYSTEM_PROMPT_RESPONSE_GENERATOR_AGENT", "").replace("{", "{{").replace("}", "}}")

        # Executor Agent
        executor_agent, tool_list = await self._get_react_agent_as_executor_agent(
                                        llm,
                                        system_prompt=executor_system_prompt,
                                        checkpointer=checkpointer,
                                        tool_ids=tool_ids,
                                        interrupt_tool=tool_interrupt_flag
                                    )
        memory_tool_list = []

        manage_memory_tool = await self.inference_utils.create_manage_memory_tool()
        memory_tool_list.append(manage_memory_tool)

        search_memory_tool = await self.inference_utils.create_search_memory_tool(
            embedding_model=self.inference_utils.embedding_model
        )
        memory_tool_list.append(search_memory_tool)
        log.info(f"Successfully created {len(memory_tool_list)} memory tools")

        llm_with_memory_tools = llm.bind_tools(tools = memory_tool_list) if memory_tool_list else llm

        # Planner Agent Chains
        planner_chain_json, planner_chain_str = await self._get_chains(llm, planner_system_prompt)

        # Replanner Agent Chains
        replanner_chain_json, replanner_chain_str = await self._get_chains(llm, replanner_system_prompt)

        # Critic-Based Planner Agent Chains
        critic_planner_chain_json, critic_planner_chain_str = await self._get_chains(llm, critic_based_planner_system_prompt)

        # General Query Handler Agent Chain
        _, general_query_chain = await self._get_chains(llm = llm_with_memory_tools, system_prompt=general_query_system_prompt, get_json_chain=False)

        # Critic Agent Chains
        critic_chain_json, critic_chain_str = await self._get_chains(llm, critic_system_prompt)

        # Response Generator Agent Chains
        response_gen_chain_json, response_gen_chain_str = await self._get_chains(llm, response_generator_system_prompt)

        log.info("Multi Agent - Chains built successfully")

        chains = {
            "llm": llm,
            "agent_executor": executor_agent,
            "tool_list": tool_list,

            "planner_chain_json": planner_chain_json,
            "planner_chain_str": planner_chain_str,

            "replanner_chain_json": replanner_chain_json,
            "replanner_chain_str": replanner_chain_str,

            "critic_planner_chain_json": critic_planner_chain_json,
            "critic_planner_chain_str": critic_planner_chain_str,

            "general_query_chain": general_query_chain,

            "critic_chain_json": critic_chain_json,
            "critic_chain_str": critic_chain_str,

            "response_gen_chain_json": response_gen_chain_json,
            "response_gen_chain_str": response_gen_chain_str,
        }

        return chains

    async def _build_workflow(self, chains: dict, flags: Dict[str, bool] = {}) -> StateGraph:
        """
        Builds the LangGraph workflow for a Planner-Executor-Critic Agent.
        """
        
        
        llm = chains.get("llm", None)
        executor_agent = chains.get("agent_executor", None)
        tool_list = chains.get("tool_list", [])

        planner_chain_json = chains.get("planner_chain_json", None)
        planner_chain_str = chains.get("planner_chain_str", None)

        replanner_chain_json = chains.get("replanner_chain_json", None)
        replanner_chain_str = chains.get("replanner_chain_str", None)

        critic_planner_chain_json = chains.get("critic_planner_chain_json", None)
        critic_planner_chain_str = chains.get("critic_planner_chain_str", None)

        general_query_chain = chains.get("general_query_chain", None)

        critic_chain_json = chains.get("critic_chain_json", None)
        critic_chain_str = chains.get("critic_chain_str", None)

        response_gen_chain_json = chains.get("response_gen_chain_json", None)
        response_gen_chain_str = chains.get("response_gen_chain_str", None)

        tool_interrupt_flag = flags.get("tool_interrupt_flag", False)
        plan_verifier_flag = flags.get("plan_verifier_flag", False)
        evaluation_flag = flags.get("evaluation_flag", False)
        validator_flag = flags.get("validator_flag", False)
        
        # DEBUG: Log the extracted flag values
        log.info(f"Extracted flags - validator_flag: {validator_flag}, evaluation_flag: {evaluation_flag}, tool_interrupt_flag: {tool_interrupt_flag}, plan_verifier_flag: {plan_verifier_flag}")

        if not llm or not executor_agent or not planner_chain_json or not planner_chain_str or \
                not critic_planner_chain_json or not critic_planner_chain_str or not general_query_chain or \
                not critic_chain_json or not critic_chain_str or not response_gen_chain_json or not response_gen_chain_str or \
                (plan_verifier_flag and (not replanner_chain_json or not replanner_chain_str)):
            raise HTTPException(status_code=500, detail="Required chains or agent executor are missing")

        # Nodes

        async def generate_past_conversation_summary(state: MultiWorkflowState | MultiHITLWorkflowState, writer:StreamWriter):
            """Generates past conversation summary from the conversation history."""
            
            strt_tmstp = get_timestamp()
            conv_summary = new_preference = ""
            errors = []
            
            # Handle regenerate/feedback scenarios - extract original query from ongoing_conversation
            raw_query = state["query"]
            original_query = None
            is_regenerate = raw_query == "[regenerate:][:regenerate]"
            is_feedback = raw_query.startswith("[feedback:]") and raw_query.endswith("[:feedback]")
            
            if is_regenerate or is_feedback:
                # For regenerate/feedback, get original query from existing ongoing_conversation
                for msg in reversed(state.get("ongoing_conversation", [])):
                    if hasattr(msg, 'role') and msg.role == "user_query":
                        original_query = msg.content
                        break
                log.info(f"[CONTEXT] Regenerate/Feedback detected. Original query: {original_query}")
            
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
                    if state["context_flag"] == False:
                        new_state = {
                            'past_conversation_summary': "No past conversation summary available.",
                            'query': current_state_query.content,
                            'ongoing_conversation': current_state_query,
                            'executor_messages': current_state_query,
                            'preference': "No specific preferences provided.",
                            'response': None,
                            'start_timestamp': strt_tmstp,
                            'response_quality_score': None,
                            'critique_points': None,
                            'plan': None,
                            'past_steps_input': None,
                            'past_steps_output': None,
                            'epoch': 0,
                            'validation_attempts': 0,
                            'evaluation_attempts': 0,
                            'step_idx': 0,
                            'current_query_status': None,
                            'validation_score': None,
                            'validation_feedback': None,
                            'errors': errors,
                            'evaluation_score': None,
                            'evaluation_feedback': None,
                            'workflow_description': workflow_description,
                            'user_update_events': []
                        }
                        if plan_verifier_flag:
                            new_state.update({
                                'is_plan_approved': None,
                                'plan_feedback': None
                            })
                       
                        return new_state
                    writer({"Node Name": "Generating Context", "Status": "Started"})
                    # Get summary via ChatService
                    conv_summary = await self.chat_service.get_chat_conversation_summary(
                        agentic_application_id=state["agentic_application_id"],
                        session_id=state["session_id"]
                    )
                    conv_summary = conv_summary or {}

                    log.debug("Chat summary fetched successfully")
                
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
                'plan': None,
                'past_steps_input': None,
                'past_steps_output': None,
                'epoch': 0,
                'validation_attempts': 0,
                'evaluation_attempts': 0,
                'step_idx': 0,
                'current_query_status': None,
                'errors': errors,
                'evaluation_score': None,
                'evaluation_feedback': None,
                'validation_score': None,
                'validation_feedback': None,
                'workflow_description': workflow_description,
                'user_update_events': []
            }
            
            if plan_verifier_flag:
                new_state.update({
                    'is_plan_approved': None,
                    'plan_feedback': None
                })

            return new_state

        async def planner_agent(state: MultiWorkflowState | MultiHITLWorkflowState, writer: StreamWriter):
            """
            This function takes the current state of the conversation and generates a plan for the agent to follow.
            """
            writer({"Node Name": "Generating Plan", "Status": "Started"})
            # feedback_learning_data = await self.feedback_learning_service.get_approved_feedback(agent_id=state["agentic_application_id"])
            # feedback_msg = await self.inference_utils.format_feedback_learning_data(feedback_learning_data)
            agent_id = state['agentic_application_id']
            # Use the standard episodic memory function
            query = state["query"]
            messages = await InferenceUtils.prepare_episodic_memory_context(state["mentioned_agent_id"] if state["mentioned_agent_id"] else agent_id, query)

            # Format the query for the planner
            formatted_query = f'''\
Past Conversation Summary:
{state["past_conversation_summary"]}

Ongoing Conversation:
{await self.chat_service.get_formatted_messages(state["ongoing_conversation"]) if state["context_flag"] else 'No ongoing conversation.'}

Tools Info:
{await self.tool_service.render_text_description_for_tools(tool_list)}


Follow these preferences for every step:
Preferences:
{state["preference"]}
- When applicable, use these instructions to guide your responses to the user's query.


Input Query:
{messages}

**Note**:
- If the user query can be solved using the tools, generate a plan for the agent to follow.
- If the user query is related to agent's goal, agent's role, workflow description, agent's domain, and tools it has access to, generate a plan for the agent to follow.
- *Do not* generate plan if they query requires the tool that you do not have.
- If no plan can be generated, return:
    ```json
    {{
        "plan": []
    }}
    ```
'''

            invocation_input = {"messages": [("user", formatted_query)]}
            planner_response = await self.inference_utils.output_parser(
                                                            llm=llm,
                                                            chain_1=planner_chain_json,
                                                            chain_2=planner_chain_str,
                                                            invocation_input=invocation_input,
                                                            error_return_key="plan"
                                                        )

            response_state = {
                "plan": planner_response['plan'],
                "step_idx": 0,  # Always reset step index when generating new plan
                "is_tool_interrupted": False  # Reset to allow fresh execution
            }
            if planner_response['plan']:
                response_state.update({
                    "executor_messages": ChatMessage(content=planner_response['plan'], role="plan"),
                    "current_query_status": "plan" if plan_verifier_flag else None
                })

          
            writer({"raw": {"plan": response_state["plan"]}, "content": f"Generated execution plan with {len(response_state['plan'])} steps"})
            # if planner_response['plan']:
            #     writer({"raw": {"planner_response": planner_response['plan']}, "content": f"{planner_response['plan']})"})
            
            log.info(f"Plan generated for session {state['session_id']} with reset step_idx")
            writer({"Node Name": "Generating Plan", "Status": "Completed"})
            
            return response_state

        async def replanner_agent(state: MultiWorkflowState | MultiHITLWorkflowState, writer: StreamWriter):
            """
            This function takes the current state of the conversation and revises the previous plan based on user feedback,
            evaluation feedback, or validation feedback.
            """
            writer({"Node Name": "Replanning", "Status": "Started"})
            
            # Build feedback section from various sources
            feedback_parts = []
            if state.get("plan_feedback"):
                feedback_parts.append(f"User Feedback:\n{state['plan_feedback']}")
            if state.get("evaluation_feedback"):
                feedback_parts.append(f"Evaluation Feedback:\n{state['evaluation_feedback']}")
            if state.get("validation_feedback"):
                feedback_parts.append(f"Validation Feedback:\n{state['validation_feedback']}")
            
            combined_feedback = "\n\n".join(feedback_parts) if feedback_parts else "No specific feedback provided."
            
            # Format the query for the replanner
            formatted_query = f'''\
Past Conversation Summary:
{state["past_conversation_summary"]}

Ongoing Conversation:
{await self.chat_service.get_formatted_messages(state["ongoing_conversation"]) if state["context_flag"] else 'No ongoing conversation.'}

Tools Info:
{await self.tool_service.render_text_description_for_tools(tool_list)}

Previous Plan:
{state["plan"]}

Input Query:
{state["query"]}

{combined_feedback}

**Note**:
- Update or revise the current plan according to the feedback provided above.
- If you are not able to come up with a plan or input query is greetings, just return empty list:
    ```json
    {{
        "plan": []
    }}
    ```
'''

            invocation_input = {"messages": [("user", formatted_query)]}
            replanner_response = await self.inference_utils.output_parser(
                                                                llm=llm,
                                                                chain_1=replanner_chain_json,
                                                                chain_2=replanner_chain_str,
                                                                invocation_input=invocation_input,
                                                                error_return_key="plan"
            )

            writer({"raw": {"replan": replanner_response.get('plan', [])}, "content": f"Generated revised plan with {len(replanner_response.get('plan', []))} steps"})
            writer({"Node Name": "Replanning", "Status": "Completed"})
            
            log.info(f"New plan generated for session {state['session_id']}")
            return {
                "plan": replanner_response.get('plan', []),
                "response": replanner_response.get('response', ''),
                "executor_messages": ChatMessage(content=replanner_response.get('plan', []), role="re-plan"),
                "current_query_status": "plan" if plan_verifier_flag and state.get("plan_feedback") else None,
                "step_idx": 0,
                "is_tool_interrupted": False
            }

        async def replanner_decision(state: MultiWorkflowState | MultiHITLWorkflowState):
            """
            Decides where to route after replanning based on source of feedback.
            - If plan is empty, go to general_llm_call
            - If plan_feedback is set (HITL flow), go to interrupt_node for approval
            - If evaluation/validation feedback (automated flow), go directly to executor
            """
            # Check if plan is empty - route to general_llm_call
            if not state["plan"] or (isinstance(state["plan"], list) and len(state["plan"]) == 0):
                log.info(f"Replanner routing to general_llm_call (empty plan) for session {state['session_id']}")
                return "general_llm_call"
            
            if plan_verifier_flag and state.get("plan_feedback"):
                log.info(f"Replanner routing to interrupt_node (HITL flow) for session {state['session_id']}")
                return "interrupt_node"
            else:
                log.info(f"Replanner routing to executor_agent_node (evaluation/validation flow) for session {state['session_id']}")
                return "executor_agent_node"


        async def general_llm_call(state: MultiWorkflowState | MultiHITLWorkflowState, writer: StreamWriter):
            """
            This function calls the LLM with the user's query and returns the LLM's response.
            """
            writer({"Node Name": "Processing...", "Status": "Started"})
            formatted_query = f'''\
Past Conversation Summary:
{state["past_conversation_summary"]}

User Query:
{state["query"]}

Note:
    -Only respond if the above User Query including greetings, feedback, and appreciation, engage in getting to know each other type of conversation, or queries related to the agent itself, such as its expertise or purpose.
    - If the query is not related to the agent's expertise, agent's goal, agent's role, workflow description, and tools it has access to and it requires external knowledge, DO NOT provide a answer to such a query, just politely inform the user that you are not capable to answer such queries.
'''
            final_content_parts = []
            invocation_input = {"messages": [("user", formatted_query)]}

    
    # 2. Loop through the stream. Each item is a "chunk".
            async for chunk in general_query_chain.astream(invocation_input):
                # The chunk object from a chain usually has a `.content` attribute.
                # We check for it to be safe.
                content_piece = ""
                if hasattr(chunk, 'content'):
                    # This handles the case where the chunk is an object like AIMessageChunk
                    content_piece = chunk.content
                elif isinstance(chunk, str):
                    # This handles the case where the chunk IS the string token itself
                    content_piece = chunk
                else:
                    # This handles any other unexpected data types by ignoring them
                    continue
                
                # Add the extracted string piece to our list.
                final_content_parts.append(content_piece)
        
        # Stream the piece out to the frontend for a real-time typing effect
                
            
            # Join all the collected parts together to form the complete response string.
            full_response = "".join(final_content_parts)
            writer({"raw": {"general_llm_response": full_response}, "content": full_response[:50] + ("..." if len(full_response) > 50 else "")})
            writer({"Node Name": "Processing...", "Status": "Completed"})
            log.info(f"General LLM response generated for session {state['session_id']}")
            
            return {
                "response": full_response.strip() # Use .strip() to remove any leading/trailing whitespace
            }
        
        async def executor_agent_node(state: MultiWorkflowState | MultiHITLWorkflowState, writer: StreamWriter):
            """
            Executes the current step in the plan using the executor agent.
            """
            
            thread_id = await self.chat_service._get_thread_id(state['agentic_application_id'], state['session_id'])
            internal_thread = await self.chat_service._get_thread_config("inside" + thread_id)
            formatter_node_prompt = ""
            if state["response_formatting_flag"]:
                formatter_node_prompt = "You are an intelligent assistant that provides data for a separate visualization tool. When a user asks for a chart, table, image, or any other visual element, you must not attempt to create the visual yourself in text. Your sole responsibility is to generate the raw, structured data. For example, for a chart, provide the JSON data; for an image, provide the <img> tag with a source URL; for a table, provide the data as a list of lists. Your output will be fed into another program that will handle the final formatting and display."
                    
            step = state["plan"][state["step_idx"]]
            completed_steps = []
            completed_steps_responses = []
            feedback_learning_data = await self.feedback_learning_service.get_approved_feedback(agent_id=state["agentic_application_id"])
            feedback_msg = await self.inference_utils.format_feedback_learning_data(feedback_learning_data)

            # Add evaluation guidance if available
            evaluation_guidance = ""
            if state.get("evaluation_feedback"):
                evaluation_guidance = f"""

--- Previous Evaluation Feedback ---
Based on the last evaluation, improve your response considering the following points:
{state["evaluation_feedback"]}
--- End Previous Evaluation Feedback ---

Ensure you address the shortcomings identified above.
"""
                log.info(f"Executor agent incorporating evaluation feedback for epoch {state.get('epoch', 0)}.")

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

            task_formatted = f"""\
Past Conversation Summary:
{state['past_conversation_summary']}

Ongoing Conversation:
{await self.chat_service.get_formatted_messages(state['ongoing_conversation']) if state["context_flag"] else 'No ongoing conversation.'}

Review the previous feedback carefully and make sure the same mistakes are not repeated
**FEEDBACK**
{feedback_msg}
**END FEEDBACK**

{evaluation_guidance}

{validation_guidance}

{formatter_node_prompt}


"""

            if state["step_idx"]!=0:
                completed_steps = state["past_steps_input"][:state["step_idx"]]
                completed_steps_responses = state["past_steps_output"][:state["step_idx"]]
                task_formatted += f"Past Steps:\n{await self.inference_utils.format_past_steps_list(completed_steps, completed_steps_responses)}"
            task_formatted += f"\n\nCurrent Step:\n{step}"

            # --- Start of Corrected Logic ---

            if state["is_tool_interrupted"]:
                final_content_parts = []                
                stream_source = executor_agent.astream(None, internal_thread)
            else:
                final_content_parts = [ChatMessage(content=task_formatted, role="context")]
                writer({"Node Name": "Thinking...", "Status": "Started"})
                stream_source = executor_agent.astream({"messages": [("user", task_formatted.strip())]}, internal_thread)
            writer({"raw": {"Current Step": step}, "content": f"Executing step: {step}"})
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
                        writer({"Tool Name": tool_message.name, "Tool Output": tool_message.content})
                        if hasattr(tool_message, "name"):
                            writer({"Node Name": "Tool Call", "Status": "Completed", "Tool Name": tool_message.name})
                    final_content_parts.extend(tool_messages["messages"])
                else:
                    writer({"executor_agent_node": msg})
                    if "agent" in msg:
                        final_content_parts.extend(msg["agent"]["messages"])
            completed_steps.append(step)
            completed_steps_responses.append(final_content_parts[-1].content)
            log.info(f"Executor Agent response generated for session {state['session_id']} at step {state['step_idx']}")
            # writer({"raw": {"Executor Agent": final_content_parts[-1].content}, "content": final_content_parts[-1].content[:50] + ("..." if len(final_content_parts[-1].content) > 50 else "")})

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
                writer({"Node Name": "Thinking...", "Status": "Completed"})  
            
            return {
                "response": final_content_parts[-1].content,
                "past_steps_input": completed_steps,
                "past_steps_output": completed_steps_responses,
                "executor_messages": final_content_parts
            }

        async def increment_step(state: MultiWorkflowState | MultiHITLWorkflowState, writer: StreamWriter):
            writer({"increment_step": f"Incrementing step index for session {state['session_id']} to {state['step_idx'] + 1}"})
            log.info(f"Incrementing step index for session {state['session_id']} to {state['step_idx'] + 1}")
            return {"step_idx": state["step_idx"]+1, "is_tool_interrupted": False}

        async def response_generator_agent(state: MultiWorkflowState | MultiHITLWorkflowState, writer: StreamWriter):
            """
            This function takes the current state of the conversation and generates a response using a response generation chain.
            """
            writer({"Node Name": "Generating Response", "Status": "Started"})
            formatter_node_prompt = ""
            if state["response_formatting_flag"]:
                formatter_node_prompt = "You are an intelligent assistant that provides data for a separate visualization tool. When a user asks for a chart, table, image, or any other visual element, you must not attempt to create the visual yourself in text. Your sole responsibility is to generate the raw, structured data. For example, for a chart, provide the JSON data; for an image, provide the <img> tag with a source URL; for a table, provide the data as a list of lists. Your output will be fed into another program that will handle the final formatting and display."
            
            feedback_context = "" if not plan_verifier_flag else f"""
User Feedback (prioritize this over the user Query for final response ):
{state["plan_feedback"]}
"""
            
            # Build tool modifications context from user_update_events (CONCISE & CLEAR VERSION with enhanced safeguards)
            tool_modifications_context = ""
            
            # Safeguard 1: Check if tool_interrupt_flag is enabled
            # Only process user_update_events if tool interruption is actually enabled
            if tool_interrupt_flag:
                user_updates = state.get("user_update_events", [])
                
                # Safeguard 2: Verify user_updates is a list and not empty
                if user_updates and isinstance(user_updates, list):
                    # Safeguard 3: Filter events for current query to prevent cross-contamination
                    query_updates = [ev for ev in user_updates if isinstance(ev, dict) and ev.get("query") == state.get("query")]
                    
                    # Safeguard 4: Only proceed if there are relevant query-specific updates
                    if query_updates:
                        modifications = []
                        for ev in query_updates:
                            # Safeguard 5: Verify event structure and message content
                            message = ev.get("message", "")
                            if message and isinstance(message, str) and message.strip():
                                modifications.append(message)
                        
                        # Safeguard 6: Only build context if there are valid modifications
                        if modifications:
                            mods_text = "\n- ".join(modifications)
                            tool_modifications_context = f"\n\n⚠️ USER MODIFIED TOOLS:\n- {mods_text}\n**Use these actual executed values in your response.**\n"
                            log.info(f"Tool modifications context built with {len(modifications)} modifications for session {state['session_id']}")
                        else:
                            log.debug(f"No valid tool modifications found for session {state['session_id']}")
                    else:
                        log.debug(f"No query-specific tool updates found for session {state['session_id']}")
                else:
                    log.debug(f"No user_update_events or invalid format for session {state['session_id']}")
            else:
                log.debug(f"Tool interrupt flag is False, skipping tool modifications context for session {state['session_id']}")
            
            # Safeguard 7: Only add tool feedback section if conditions are met
            if tool_interrupt_flag and state.get("tool_feedback") and state["tool_feedback"] != "yes":
                feedback_context += f"""\n\nTool Feedback:
user modified the tool values, consider the new values. 
{state["tool_feedback"]}

"""
            formatted_query = f'''\
Past Conversation Summary:
{state["past_conversation_summary"]}

Ongoing Conversation:
{await self.chat_service.get_formatted_messages(state["ongoing_conversation"]) if state["context_flag"] else 'No ongoing conversation.'}

Follow these preferences for every step:
Preferences:
{state["preference"]}
- When applicable, use these instructions to guide your responses to the user's query.

{formatter_node_prompt}

User Query:
{state["query"]}
{feedback_context}
{tool_modifications_context}

Steps Completed to generate final response:
{await self.inference_utils.format_past_steps_list(state["past_steps_input"], state["past_steps_output"])}

Final Response from Executor Agent:
{state["response"]}
'''

            invocation_input = {"messages": [("user", formatted_query)]}
            response_gen_response = await self.inference_utils.output_parser(
                                                                llm=llm,
                                                                chain_1=response_gen_chain_json,
                                                                chain_2=response_gen_chain_str,
                                                                invocation_input=invocation_input,
                                                                error_return_key="response"
                                                            )
            # writer({"raw": {"response_gen_response": response_gen_response}, "content": str(response_gen_response)[:50] + ("..." if len(str(response_gen_response)) > 50 else "")})
            if isinstance(response_gen_response, dict) and "response" in response_gen_response:
                writer({"raw": {"Generated Response": response_gen_response["response"]}, "content": response_gen_response["response"][:50] + ("..." if len(response_gen_response["response"]) > 50 else "")})
                writer({"Node Name": "Generating Response", "Status": "Completed"})
                log.info(f"Response generated for session {state['session_id']}")
                return {"response": response_gen_response["response"]}
            else:
                writer({"Node Name": "Generating Response", "Status": "Failed"})
                log.error(f"Response generation failed for session {state['session_id']}")
                result = await llm.ainvoke(f"Format the response in Markdown Format.\n\nResponse: {response_gen_response}")
                return {"response": result.content}

        async def critic_agent(state: MultiWorkflowState | MultiHITLWorkflowState, writer: StreamWriter):
            """
            This function takes a state object containing information about the conversation and the generated response,
            formats it into a query for the critic model, and returns the critic's evaluation of the response.
            """
            writer({"Node Name": "Reviewing Response", "Status": "Started"})
            feedback_context = "" if not plan_verifier_flag else f"""
Now user want to modify above query with below modification:
{state["plan_feedback"]}
"""
            
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
            
            # Add tool execution information to context
            tool_execution_context = ""
            if tool_calls_data:
                tool_execution_context += "\n\nTools used in the response generation:\n"
                for tool_data in tool_calls_data:
                    tool_name = tool_data['name']
                    tool_args = json.dumps(tool_data['args'])
                    tool_output = tool_data['output'] if tool_data['output'] else "No output captured."
                    tool_execution_context += f"- Tool Name: {tool_name}\n  Arguments: {tool_args}\n  Output: {tool_output}\n"
            
            # Include user_update_events (from tool interruptions)
            # THIS SHOWS: What the user manually modified during tool execution
            updates_lines = []
            for ev in state.get("user_update_events", []):
                if ev.get("query") and ev.get("query") != state.get("query"):
                    continue
                line = f"tool_update_feedback : {ev.get('message','N/A')}\n"
                updates_lines.append(line)

            user_modifications_context = ""
            if updates_lines:
                join_updates="\n".join(updates_lines)
                user_modifications_context = f"""\n\nUser Tool Modifications (Manual Interruptions):\n
original_user_query: {state['query']}
{join_updates}

- original_user_query: the user's initial question/instruction.
- tool_update_feedback: a free-form statement describing corrected parameters or revised intent.

Your job:
1) Infer the revised/expected query and parameters solely from tool_update_feedback.
2) Treat the revision as the single source of truth. Do NOT proceed with the original query if there is any conflict.
3) Execute using the revised intent/parameters and produce the answer accordingly.

Rules:
- If tool_update_feedback indicates parameter changes (e.g., "a=8 and b=9 were modified into a=8 and b=8"), infer the corrected query (e.g., "what is 8*8") and use the revised parameters.
- If tool_update_feedback states a direct correction (e.g., "expected question was 8*8", "corrected to 8*8"), answer that.\n
                """

            formatted_query = f'''\
Past Conversation Summary:
{state["past_conversation_summary"]}

Ongoing Conversation:
{await self.chat_service.get_formatted_messages(state["ongoing_conversation"]) if state["context_flag"] else 'No ongoing conversation.'}

Tools Info:
{await self.tool_service.render_text_description_for_tools(tool_list)}

User Query:
{state["query"]}
{feedback_context}
{tool_execution_context}
{user_modifications_context}

Steps Completed to generate final response:
{await self.inference_utils.format_past_steps_list(state["past_steps_input"], state["past_steps_output"])}

Final Response:
{state["response"]}

##Instructions
- Consider the modifications given by user along with actual query
- Review the tool execution details to ensure proper tool usage
- Consider any user modifications to tool arguments during execution
- Only Verify Final Response which is aligned to the query and make sure all the data in final response are grounded from the past steps output
- Consider plan and final response as a whole and verify if the final response is aligned with the user query.
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
            
            writer({"Node Name": "Reviewing Response", "Status": "Completed"})
            log.info(f"Critic response generated for session {state['session_id']}")
            return {
                "response_quality_score": critic_response["response_quality_score"],
                "critique_points": critic_response["critique_points"],
                "executor_messages": ChatMessage(
                    content=[{
                            "response_quality_score": critic_response["response_quality_score"],
                            "critique_points": critic_response["critique_points"]
                        }],
                    role="critic-response"
                )
            }

        async def critic_based_planner_agent(state: MultiWorkflowState | MultiHITLWorkflowState, writer: StreamWriter):
            """
            This function takes a state object containing information about the current conversation, tools, and past steps,
            and uses a critic-based planner to generate a plan for the next step.
            """
            writer({"Node Name": "Refactoring Plan", "Status": "Started"})
            feedback_context = "" if not plan_verifier_flag else f"""
*Now user want to modify above query with below modification:
{state["plan_feedback"]}

"""
             # Include evaluator feedback if available
            evaluator_context = ""
            if evaluation_flag and state.get("evaluation_feedback"):
                evaluator_context = f"""

    **EVALUATOR FEEDBACK FOR IMPROVEMENT:**
    {state["evaluation_feedback"]}
    **Please address the above evaluator feedback in your new plan.**

    """

            # Include validator feedback if available
            validator_context = ""
            if validator_flag and state.get("validation_feedback"):
                validator_context = f"""

    **VALIDATOR FEEDBACK FOR IMPROVEMENT:**
    {state["validation_feedback"]}
    **Please address the above validation feedback in your new plan.**

    """

            formatted_query = f'''
Past Conversation Summary:
{state["past_conversation_summary"]}

Ongoing Conversation:
{await self.chat_service.get_formatted_messages(state["ongoing_conversation"]) if state["context_flag"] else 'No ongoing conversation.'}

Tools Info:
{await self.tool_service.render_text_description_for_tools(tool_list)}

User Query:
{state["query"]}
{feedback_context}

Steps Completed Previously to Generate Final Response:
{await self.inference_utils.format_past_steps_list(state["past_steps_input"], state["past_steps_output"])}

Final Response:
{state["response"]}

Response Quality Score:
{state.get("response_quality_score", "Not yet evaluated")}

Critique Points:
{await self.inference_utils.format_list_str(state["critique_points"]) if state.get("critique_points") else "No critique points available yet."}
{evaluator_context}
{validator_context}
'''

            invocation_input = {"messages": [("user", formatted_query)]}
            critic_planner_response = await self.inference_utils.output_parser(
                                                                    llm=llm,
                                                                    chain_1=critic_planner_chain_json,
                                                                    chain_2=critic_planner_chain_str,
                                                                    invocation_input=invocation_input,
                                                                    error_return_key="plan"
                                                                )
            writer({"raw": {"critic_based_planner_agent": critic_planner_response["plan"]}, "content": f"Generated refactored plan with {len(critic_planner_response['plan'])} steps"})
            writer({"raw": {"critic_based_planner_agent_full_response": critic_planner_response}, "content": f"{critic_planner_response['plan']}"})
            writer({"Node Name": "Refactoring Plan", "Status": "Completed"})
            log.info(f"Critic-based planner response generated for session {state['session_id']}")

            return {
                "plan": critic_planner_response["plan"],
                "executor_messages": ChatMessage(content=critic_planner_response['plan'], role="critic-plan"),
                "step_idx": 0,
                "is_tool_interrupted": False,  # Reset to allow fresh execution
                "epoch": state.get('epoch', 0) + 1
            }

        async def final_response(state: MultiWorkflowState | MultiHITLWorkflowState,writer: StreamWriter):
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
            except Exception as e:
                error = f"Error occurred in Final response: {e}"
                writer({"Node Name": "Memory Update", "Status": "Failed"})
                log.error(error)
                errors.append(error)

            final_response_message = AIMessage(content=state["response"])
            writer({"raw":{"final_response":"Memory Updated"}, "content":"Memory Updated"})
            writer({"Node Name": "Memory Update", "Status": "Completed"})
            log.info(f"Final response generated for session {state['session_id']}")
            return {
                "ongoing_conversation": final_response_message,
                "executor_messages": final_response_message,
                "end_timestamp": end_timestamp,
                "errors": errors
            }

        async def critic_decision(state: MultiWorkflowState | MultiHITLWorkflowState, writer: StreamWriter):
            """
            Decides whether to return the final response or continue
            with the critic-based planner agent.
            """
            if state["response_quality_score"]>=0.7 or state["epoch"]==3:
                writer({"raw": {"analyzing": "Moving to final response as response feels fine"}, "content": "Analysis complete: Response quality is acceptable, proceeding to final output"})
                return "final_response"
            else:
                writer({"raw": {"analyzing": "Asking agent to work again as it has not met our expectation"}, "content": "Analysis complete: Response needs improvement, requesting agent to revise output"})
                return "critic_based_planner_agent"

        async def check_plan_execution_status(state: MultiWorkflowState | MultiHITLWorkflowState):
            """
            Checks the status of the plan execution and decides which agent should be called next.
            """
            if state["step_idx"]==len(state["plan"]):
                return "response_generator_agent"
            else:
                return "executor_agent_node"

        async def route_general_question(state: MultiWorkflowState | MultiHITLWorkflowState):
            """
            Determines the appropriate agent to handle a general question based on the current state.
            """
            if not state["plan"] or "STEP" not in state["plan"][0]:
                return "general_llm_call"
            else:
                return "interrupt_node" if plan_verifier_flag else "executor_agent_node"

        async def interrupt_node(state: MultiHITLWorkflowState, writer: StreamWriter):
            """Asks the human if the plan is ok or not"""
           
            is_plan_approved = interrupt("Is this plan acceptable?").lower()

            writer({"raw": {"plan_verifier": "Is this plan acceptable? yes/no"}, "content": "Please review the execution plan and confirm if it's acceptable"})
            if is_plan_approved =="yes":
                writer({"raw": {"plan_verifier": "User approved the plan by clicking the thumbs up button"}, "content": "User approved the plan by clicking the thumbs up button"})
            else:
                writer({"raw": {"plan_verifier": "User clicked the thumbs down button and provided feedback for plan execution"}, "content": "User clicked the thumbs down button and provided feedback for plan execution"})
             
                log.info(f"is_approved {is_plan_approved}")
            return {
                "is_plan_approved": is_plan_approved,
                "current_query_status": "feedback" if is_plan_approved == 'no' else None,
            }

        async def interrupt_node_decision(state: MultiHITLWorkflowState):
            if state["is_plan_approved"]=='no':
                return "feedback_collector"
            else:
                return "executor_agent_node"

        async def feedback_collector(state: MultiHITLWorkflowState, writer: StreamWriter):
            # writer({"raw": {"feedback_collector": "Please confirm your feedback for the plan"}, "content": "Please provide your feedback on the proposed execution plan"})
            feedback = interrupt("What went wrong??")
            return {
                'plan_feedback': feedback,
                'executor_messages': ChatMessage(content=feedback, role="re-plan-feedback"),
                'current_query_status': None
            }



        async def final_decision(state: MultiWorkflowState | MultiHITLWorkflowState, writer: StreamWriter):
            # writer({"Node Name": "Final Decision", "Status": "Started"})
            thread_id = await self.chat_service._get_thread_id(state['agentic_application_id'], state['session_id'])
            internal_thread = await self.chat_service._get_thread_config("inside" + thread_id)
            a = await executor_agent.aget_state(internal_thread)
            if a.tasks == ():
                response = a.values["messages"][-1].content
                # checking_res = reversed(state["executor_messages"])
                # for i in checking_res:
                #     if i.type == "tool":
                #         if i.status == "error":
                #             is_successful = "no"
                #             break
                #         else:
                #             is_successful = "yes"
                checking_promopt = f"""
                You are a critic agent, your task is to check if the tool call is 
                successful or not. If the tool call is successful, return "yes", otherwise return "no".
                Tool Call Response: {response}
                
                Instructions:
                - If the response content "ERROR" or something similar to error then return "no".
                - If the response content is a valid response, then return "yes".

                output should be only one word either "yes" or "no"
                Do not return any other text or explanation.
                """
                is_successful = llm.invoke(checking_promopt).content.strip().lower()

                if "yes" in is_successful:
                    return "increment_step" 
                else:
                    return "response_generator_agent"
            else:
                return "interrupt_node_for_tool"

        async def interrupt_node_for_tool(state: MultiWorkflowState | MultiHITLWorkflowState, writer: StreamWriter):
            """Asks the human if the plan is ok or not"""
            thread_id = await self.chat_service._get_thread_id(state['agentic_application_id'], state['session_id'])
            internal_thread = await self.chat_service._get_thread_config("inside" + thread_id)

            agent_state = await executor_agent.aget_state(internal_thread)

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
                is_plan_approved = interrupt("approved?(yes/feedback)") 
                writer({"raw": {"tool_verifier": "Please confirm to execute the tool"}, "content": "Tool execution requires confirmation. Please approve to proceed."})
                if is_plan_approved == "yes":
                    writer({"raw": {"tool_verifier": "User approved the tool execution by clicking the thumbs up button"}, "content": "User approved the tool execution by clicking the thumbs up button"})
            else:
                log.info(f"[{state['session_id']}] Tool '{tool_name_in_task}' not in interrupt_items {interrupt_items}, auto-approving.")
                is_plan_approved = "yes"
            return {"tool_feedback": is_plan_approved, "is_tool_interrupted": True}

        async def interrupt_node_decision_for_tool(state: MultiWorkflowState | MultiHITLWorkflowState):
            if state["tool_feedback"]=='yes':
                return "executor_agent_node"
            else:
                return "tool_interrupt"

        async def tool_interrupt(state: MultiWorkflowState | MultiHITLWorkflowState, writer: StreamWriter):

            # writer({"Node Name": "Updating Tool Arguments", "Status": "Started"}) 
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

            # Record a user update event for evaluator/critic awareness
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
            executor_agent_response = {"messages":[]}
            final_content_parts=[new_ai_msg]
            stream_source = executor_agent.astream(None, internal_thread)
            async for msg in stream_source :
                executor_agent_response["messages"].append(msg)
                # writer({"raw": {"tool_interrupt": msg}, "content": f"Tool execution interrupted for manual input: {msg}"})

                if isinstance(msg, dict) and "agent" in msg:
                    agent_output = msg.get("agent", {})
                    if isinstance(agent_output, dict) and "messages" in agent_output:
                        messages = agent_output.get("messages", [])
                
                    for message in messages:
                        # The message can be an object (like AIMessage) with a .content attribute
                        # or it could be a dictionary with a 'content' key. This handles both.
                        if message.tool_calls:
                            writer({"raw": {"executor_agent": "Agent is calling tools"}, "content": f"Agent is calling tools"})
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
                    writer({"executor_agent_node": msg})
                    if "agent" in msg:
                        final_content_parts.extend(msg["agent"]["messages"])

            
            # writer({"Node Name": "Updating Tool Arguments", "Status": "Completed"})   
            
            final_ai_message = final_content_parts[-1]
            writer({"raw": {"tool_interrupt_final_ai_message": final_ai_message.content}, "content": f"Tool execution with user's feedback completed"})
            
            # Safely append to user_update_events without mutating the original state
            existing_events = list(state.get("user_update_events", []))
            existing_events.append(event)

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
                "user_update_events": existing_events
            }
        
         # NEW EVALUATOR AGENT NODE
        async def evaluator_agent(state: MultiWorkflowState | MultiHITLWorkflowState,writer: StreamWriter):
            """
            Evaluates the agent response across multiple dimensions and provides scores and feedback.
            """
            log.info(f"EVALUATOR AGENT CALLED for session {state['session_id']}")
            
            # Increment evaluation attempts counter at the start
            evaluation_attempts = state.get("evaluation_attempts", 0) + 1
            writer({"Node Name": "Evaluating Response", "Status": "Started"})
            
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
                writer({"raw": {"Evaluator Aggregate Score": aggregate_score}, "content": f"Evaluator completed with aggregate score: {aggregate_score}"})
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
                    )
                }
                
            except json.JSONDecodeError as e:
                log.error(f"Failed to parse evaluator JSON response for session {state['session_id']}: {e}")
                writer({"Node Name": "Evaluating Response", "Status": "Failed"})
                return {
                    "evaluation_score": 0.3,
                    "evaluation_feedback": "Evaluation failed due to JSON parsing error. Please review the response format and content quality.",
                    "evaluation_attempts": evaluation_attempts,
                    "executor_messages": ChatMessage(
                        content="Evaluation failed - JSON parsing error",
                        role="evaluator-error"
                    )
                }
            except Exception as e:
                log.error(f"Evaluator agent failed for session {state['session_id']}: {e}")
                writer({"Node Name": "Evaluating Response", "Status": "Failed"})
                return {
                    "evaluation_score": 0.3,
                    "evaluation_feedback": f"Evaluation failed due to error: {str(e)}",
                    "evaluation_attempts": evaluation_attempts,
                    "executor_messages": ChatMessage(
                        content=f"Evaluation failed: {str(e)}",
                        role="evaluator-error"
                    )
                }

        async def evaluator_decision(state: MultiWorkflowState | MultiHITLWorkflowState):
            """
            Decides whether to return the final response or continue with improvement cycle.
            SAVES feedback ONLY if the score fails the threshold (score < 0.7).
            """
            evaluation_threshold = 0.7
            max_evaluation_epochs = 3
            
            current_epoch = state.get("evaluation_attempts", 0)
            evaluation_score = state.get("evaluation_score", 0.0)
            evaluation_feedback = state.get("evaluation_feedback", "No evaluation feedback available")

            # Check if this is the final attempt (either passed or out of retries)
            is_final_attempt = (evaluation_score >= evaluation_threshold or current_epoch >= max_evaluation_epochs)

            if is_final_attempt:
                # 🔄 ONLY Save to DB if it FAILED the threshold
                if evaluation_score < evaluation_threshold:
                    try:
                        log.info(f"📉 Evaluation failed (Score: {evaluation_score}). Generating lesson and saving for learning.")
                        
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

                        # Save failure feedback
                        await self.feedback_learning_service.save_feedback(
                            agent_id=state["agentic_application_id"],
                            query=state["query"],
                            old_final_response=state["response"],
                            old_steps=str(state.get("plan", [])),
                            new_final_response=status,
                            feedback=f"[EVALUATOR] Score: {evaluation_score:.2f} - {evaluation_feedback}", 
                            new_steps=status,
                            lesson=lesson
                        )
                        log.info(f"💾 Multi-Agent Evaluator failure stored successfully for session {state['session_id']}")
                            
                    except Exception as e:
                        log.error(f"❌ Failed to save evaluator feedback: {e}")
                else:
                    log.info(f"✅ Evaluation passed (Score: {evaluation_score}). Skipping DB feedback save.")

                return "final_response"

            # If not final, route to replanner for improvement
            log.info(f"Evaluation failed ({evaluation_score}). Routing to replanner.")
            return "replanner_agent"

        
                        
        async def validator_agent_node(state: MultiWorkflowState | MultiHITLWorkflowState, writer: StreamWriter):
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



    
        async def validator_decision_node(state: MultiWorkflowState | MultiHITLWorkflowState):
            """
            Decides the next step based on validation results and current epoch.
            SAVES feedback ONLY if the score fails the threshold (score < 0.7).
            """
            validation_threshold = 0.7
            max_validation_epochs = 3
            
            current_epoch = state.get("validation_attempts", 0)
            validation_score = state.get("validation_score", 0.0)
            validation_feedback = state.get("validation_feedback", "No validation feedback available")

            # Check if we are finishing the validation phase
            is_exiting = (validation_score >= validation_threshold or current_epoch >= max_validation_epochs)

            if is_exiting:
                # 🔄 ONLY Save to DB if it FAILED the threshold
                if validation_score < validation_threshold:
                    try:
                        log.info(f"📉 Validation failed (Score: {validation_score}). Generating lesson and saving for learning.")
                    
                        validator_lesson_prompt = feedback_lesson_generation_prompt.format(
                            user_query=state["query"],
                            agent_response=state["response"],
                            feedback_type="VALIDATOR",
                            feedback_score=validation_score,
                            feedback_details=validation_feedback
                        )
                        
                        lesson_response = await llm.ainvoke(validator_lesson_prompt)
                        lesson = lesson_response.content
                        
                        status = f"[FAILED_AFTER_{current_epoch}_RETRIES]"

                        # Save failure feedback
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
                        log.info(f"💾 Multi-Agent Validator failure stored successfully for session {state['session_id']}")
                            
                    except Exception as e:
                        log.error(f"❌ Failed to save validator feedback: {e}")
                else:
                    log.info(f"✅ Validation passed (Score: {validation_score}). Skipping DB feedback save.")

                # Determine next route based on flags
                if evaluation_flag:
                    return "evaluator_agent"
                else:
                    return "critic_agent"

            # If not exiting, loop back to replanner for improvement
            log.info(f"Validation failed ({validation_score}). Routing to replanner.")
            return "replanner_agent"


        ### Build Graph
        workflow = StateGraph(MultiWorkflowState if not plan_verifier_flag else MultiHITLWorkflowState)

        workflow.add_node("generate_past_conversation_summary", generate_past_conversation_summary)
        workflow.add_node("planner_agent", planner_agent)
        workflow.add_node("replanner_agent", replanner_agent)

        if plan_verifier_flag:
            workflow.add_node("interrupt_node", interrupt_node)
            workflow.add_node("feedback_collector", feedback_collector)

        workflow.add_node("general_llm_call", general_llm_call)
        workflow.add_node("executor_agent_node", executor_agent_node)
        workflow.add_node("increment_step", increment_step)
        workflow.add_node("response_generator_agent", response_generator_agent)
        # workflow.add_node("critic_agent", critic_agent)
        workflow.add_node("critic_based_planner_agent", critic_based_planner_agent)
        workflow.add_node("final_response", final_response)
        workflow.add_node("interrupt_node_for_tool", interrupt_node_for_tool)
        workflow.add_node("tool_interrupt", tool_interrupt)
        if flags["response_formatting_flag"]:
            workflow.add_node("formatter", lambda state: InferenceUtils.format_for_ui_node(state, llm))

        if evaluation_flag:
            workflow.add_node("evaluator_agent", evaluator_agent)
            log.info("[SUCCESS] Added evaluator_agent node")
        else:
            workflow.add_node("critic_agent", critic_agent)
            log.info("[SUCCESS] Added critic_agent node")

        if validator_flag:
            workflow.add_node("validator_agent", validator_agent_node)
            log.info("[SUCCESS] Added validator_agent node")
        
        # Debug logging for flag values
        log.info(f"[INFO] Node addition complete - validator_flag={validator_flag}, evaluation_flag={evaluation_flag}")


        workflow.add_edge(START, "generate_past_conversation_summary")
        workflow.add_edge("generate_past_conversation_summary", "planner_agent")
        workflow.add_conditional_edges(
            "planner_agent",
            route_general_question,
            ["general_llm_call", "executor_agent_node" if not plan_verifier_flag else "interrupt_node"],
        )

        if plan_verifier_flag:
            workflow.add_conditional_edges(
                "interrupt_node",
                interrupt_node_decision,
                ["executor_agent_node", "feedback_collector"],
            )
            workflow.add_edge("feedback_collector", "replanner_agent")
            # Replanner has conditional routing when plan_verifier_flag is True
            workflow.add_conditional_edges(
                "replanner_agent",
                replanner_decision,
                ["interrupt_node", "executor_agent_node", "general_llm_call"],
            )
        else:
            # When plan_verifier_flag is False, replanner has conditional routing for empty plans
            workflow.add_conditional_edges(
                "replanner_agent",
                replanner_decision,
                ["executor_agent_node", "general_llm_call"],
            )

        workflow.add_conditional_edges(
            "executor_agent_node",
            final_decision,
            ["interrupt_node_for_tool", "increment_step","response_generator_agent"],
        )
        workflow.add_conditional_edges(
            "interrupt_node_for_tool",
            interrupt_node_decision_for_tool,
            ["executor_agent_node", "tool_interrupt"],
        )
        workflow.add_conditional_edges(
            "tool_interrupt",
            final_decision,
            ["interrupt_node_for_tool", "increment_step","response_generator_agent"],
        )

        workflow.add_conditional_edges(
            "increment_step",
            check_plan_execution_status,
            ["executor_agent_node", "response_generator_agent"],
        )

        # Add a router to decide between validation and evaluation/critic
        async def post_response_router(state: MultiWorkflowState | MultiHITLWorkflowState):
            """Routes after response generation to validation or evaluation/critic"""
            log.info(f"[{state['session_id']}] post_response_router called - validator_flag={validator_flag}, evaluation_flag={evaluation_flag}")
            
            # Skip validator if evaluator has already run (evaluation_attempts > 0)
            evaluation_attempts = state.get("evaluation_attempts", 0)
            
            if validator_flag and evaluation_attempts == 0:
                log.info(f"[{state['session_id']}] Routing to validator_agent (validation_flag: {validator_flag}, evaluation_attempts: {evaluation_attempts})")
                return "validator_agent"
            elif evaluation_flag:
                log.info(f"[{state['session_id']}] Routing to evaluator_agent (evaluation_flag: {evaluation_flag})")
                return "evaluator_agent"
            else:
                log.info(f"[{state['session_id']}] Routing to critic_agent (no validation or evaluation flags)")
                return "critic_agent"

        if evaluation_flag:
            log.info("[SUCCESS] Setting up evaluation routing path")
            # Route from response_generator_agent - targets based on what router can return
            # Router returns: validator_agent if validator_flag, else evaluator_agent
            post_response_targets = []
            if validator_flag:
                post_response_targets.append("validator_agent")
            post_response_targets.append("evaluator_agent")
            
            log.info(f"[DEBUG] post_response_targets for evaluation path: {post_response_targets}")
            
            workflow.add_conditional_edges(
                "response_generator_agent",
                post_response_router,
                post_response_targets
            )
            
            # Evaluator decision routing
            workflow.add_conditional_edges(
                "evaluator_agent",
                evaluator_decision,
                ["final_response", "replanner_agent"],
            )
        else:
            log.info("[SUCCESS] Setting up critic routing path")
            # Route from response_generator_agent - targets based on what router can return
            # Router returns: validator_agent if validator_flag, else critic_agent
            post_response_targets = []
            if validator_flag:
                post_response_targets.append("validator_agent")
            post_response_targets.append("critic_agent")
            
            log.info(f"[DEBUG] post_response_targets for critic path: {post_response_targets}")
                
            workflow.add_conditional_edges(
                "response_generator_agent", 
                post_response_router,
                post_response_targets
            )
            
            workflow.add_conditional_edges(
                "critic_agent",
                critic_decision,
                ["final_response", "critic_based_planner_agent"],
            )

        # Validator routing (when enabled)
        if validator_flag:
            # Define possible targets based on enabled flags
            validator_targets = ["replanner_agent"]
            if evaluation_flag:
                validator_targets.append("evaluator_agent")
            else:
                validator_targets.append("critic_agent")
            
            workflow.add_conditional_edges(
                "validator_agent",
                validator_decision_node,
                validator_targets
            )

        workflow.add_edge("critic_based_planner_agent", "executor_agent_node")
        workflow.add_edge("general_llm_call","final_response")
        if flags["response_formatting_flag"]:
            workflow.add_edge("final_response", "formatter")
            workflow.add_edge("formatter", END)
        else:
            workflow.add_edge("final_response", END)

        log.info("Planner, Executor, Critic Agent built successfully")
        return workflow



