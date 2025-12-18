# © 2024-25 Infosys Limited, Bangalore, India. All Rights Reserved.
from typing import Dict, List
import asyncio
import json
from langgraph.types import interrupt
from langgraph.graph import StateGraph, START, END
from langchain_core.messages import AIMessage, ChatMessage
import json
from langgraph.types import StreamWriter
from src.utils.helper_functions import get_timestamp
from src.inference.inference_utils import InferenceUtils
from src.inference.base_agent_inference import BaseWorkflowState, BaseMetaTypeAgentInference
from telemetry_wrapper import logger as log

from src.inference.inference_utils import EpisodicMemoryManager
from src.prompts.prompts import online_agent_evaluation_prompt

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


class PlannerMetaAgentInference(BaseMetaTypeAgentInference):
    """
    Implements the LangGraph workflow for 'planner_meta_agent' type.
    """

    def __init__(self, inference_utils: InferenceUtils):
        super().__init__(inference_utils)


    async def _build_agent_and_chains(self, llm, agent_config, checkpointer = None, tool_interrupt_flag: bool = False):
        """
        Builds the agent and chains for the Planner Meta workflow.
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
        meta_agent, _ = await self._get_react_agent_as_supervisor_agent(
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
            "meta_responder_chain": meta_responder_chain
        }
        return chains

    async def _build_workflow(self, chains: dict, flags: Dict[str, bool] = {}) -> StateGraph:
        """
        Builds the LangGraph workflow for a Planner Meta Agent.
        """
        tool_interrupt_flag = flags.get("tool_interrupt_flag", False)
        evaluation_flag = flags.get("evaluation_flag", False)

        llm = chains.get("llm", None)
        meta_agent = chains.get("meta_agent", None)
        meta_planner_chain_json = chains.get("meta_planner_chain_json", None)
        meta_planner_chain_str = chains.get("meta_planner_chain_str", None)
        meta_responder_chain = chains.get("meta_responder_chain", None)

        if not llm or not meta_agent or not meta_planner_chain_json or not meta_planner_chain_str or \
                not meta_responder_chain:
            raise ValueError("Required chains (llm, meta_agent, meta_planner_chain_json, meta_planner_chain_str, meta_responder_chain) are missing.")

        # Nodes

        async def generate_past_conversation_summary(state: PlannerMetaWorkflowState,writer:StreamWriter):
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
                            'start_timestamp': strt_tmstp,
                            'epoch': 0,
                            'plan': [],
                            'past_steps_output': [],
                            'step_idx': 0,
                            'errors': errors,
                            'user_update_events': []
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
                'start_timestamp': strt_tmstp,
                'epoch': 0,
                'plan': [],
                'past_steps_output': [],
                'step_idx': 0,
                'errors': errors,
                'user_update_events': []
            }

        async def meta_planner_agent(state: PlannerMetaWorkflowState,writer:StreamWriter):
            """Generates a plan for the supervisor to execute."""
            writer({"Node Name": "Generating Plan", "Status": "Started"})
            agent_id = state['agentic_application_id']
            # Use the standard episodic memory function
            query = state["query"]
            messages = await InferenceUtils.prepare_episodic_memory_context(state["mentioned_agent_id"] if state["mentioned_agent_id"] else agent_id, query)
            formatted_query = f"""\
Past Conversation Summary:
{state["past_conversation_summary"]}

Ongoing Conversation:
{await self.chat_service.get_formatted_messages(state["ongoing_conversation"]) if state["context_flag"] else 'No ongoing conversation.'}

User Query:
{messages}
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
                writer({"Node Name": "Generating Plan", "Status": "Failed"})
                planner_response = {"plan": []}
            response = {"plan": planner_response["plan"]}
            planner_response_str= "\n".join(planner_response["plan"])
         
            writer({"raw": {"planner_response": planner_response_str}, "content": planner_response_str})
            writer({"Node Name": "Generating Plan", "Status": "Completed"})
            if planner_response["plan"]:
                response["executor_messages"] = ChatMessage(content=planner_response["plan"], role="plan")

            
            return response

        async def meta_supervisor_executor(state: PlannerMetaWorkflowState,writer:StreamWriter):
            """Supervisor executes one step of the plan by delegating to a worker."""
            
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

            if state["step_idx"]!=0:
                completed_steps = state["past_steps_input"][:state["step_idx"]]
                completed_steps_responses = state["past_steps_output"][:state["step_idx"]]
                task_formatted += f"Past Steps:\n{await self.inference_utils.format_past_steps_list(completed_steps, completed_steps_responses)}"

            task_formatted += f"\n\nCurrent Step:\n{step}"

            

            if state["is_tool_interrupted"]:
                final_content_parts = []
                stream_source = meta_agent.astream(None, internal_thread)
            else:
                final_content_parts = [ChatMessage(content=task_formatted, role="context")]
                writer({"Node Name": "Thinking...", "Status": "Started"})
                stream_source = meta_agent.astream({"messages": [("user", task_formatted.strip())]}, internal_thread)

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
                    
                    for tool_message in tool_messages["messages"]:
                        writer({"raw": {"Agent Name": tool_message.name, "Agent Output": tool_message.content}, "content": f"Agent {tool_message.name} returned: {tool_message.content}"})
                        if hasattr(tool_message, "name"):
                            writer({"Node Name": "Agent Call", "Status": "Completed", "Agent Name": tool_message.name})
                    final_content_parts.extend(tool_messages["messages"])
                else:
                    # writer({"raw": {"executor_agent_node": msg}, "content": f"Agent processing: {msg.get('agent', {}).get('messages', [{}])[-1].get('content', 'Agent working...') if isinstance(msg, dict) and 'agent' in msg else str(msg)}"})
                    if "agent" in msg:
                        final_content_parts.extend(msg["agent"]["messages"])
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
                writer({"Node Name": "Thinking...", "Status": "Completed"}) 
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
            return {"step_idx": new_idx, "is_tool_interrupted": False}

        async def meta_response_generator(state: PlannerMetaWorkflowState,writer:StreamWriter):
            """Generates the final response by synthesizing all step outputs."""
            writer({"Node Name": "Generating Final Response", "Status": "Started"})
            formatter_node_prompt = ""
            if state["response_formatting_flag"]:
                formatter_node_prompt = "\n\nYou are an intelligent assistant that provides data for a separate visualization tool. When a user asks for a chart, table, image, or any other visual element, you must not attempt to create the visual yourself in text. Your sole responsibility is to generate the raw, structured data. For example, for a chart, provide the JSON data; for an image, provide the <img> tag with a source URL; for a table, provide the data as a list of lists. Your output will be fed into another program that will handle the final formatting and display."
            
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
                log.info(f"Planner Meta agent incorporating evaluation feedback for epoch {state['epoch']}.")
                    
            if not state["plan"]:
                # If there was no plan, the supervisor was never called.
                # We can create a simple response directly.
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

        async def final_response_node(state: PlannerMetaWorkflowState,writer:StreamWriter):
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
                writer({"Node Name": "Memory Update", "Status": "Failed"})
                error = f"Error occurred in Final response: {e}"
                log.error(error)
                errors.append(error)

            final_response_message = AIMessage(content=state["response"])
            log.info(f"Planner Meta Agent's final response generated: {final_response_message.content}")
            writer({"raw": {"final_response": "Memory Updated"}, "content": "Memory Updated"})
            writer({"Node Name": "Memory Update", "Status": "Completed"})
            return {
                "ongoing_conversation": final_response_message,
                "executor_messages": final_response_message,
                "end_timestamp": end_timestamp
            }

        async def route_query(state: PlannerMetaWorkflowState):
            """Routes to the executor loop if a plan exists, otherwise to the final responder."""
            if state["plan"]:
                log.info("Routing: Plan detected, starting supervisor execution loop.")
                return "meta_supervisor_executor"
            else:
                log.info("Routing: No plan detected, proceeding to final response generation.")
                return "meta_response_generator"
        
        async def check_plan_execution_status(state: PlannerMetaWorkflowState):
            """Checks if all steps in the plan have been executed."""
            if state["step_idx"] == len(state["plan"]):
                log.info("Routing: Plan execution complete.")
                return "meta_response_generator"
            else:
                log.info("Routing: More steps in plan, continuing execution.")
                return "meta_supervisor_executor"

        async def tool_interrupt_router(state: PlannerMetaWorkflowState,writer:StreamWriter):
            thread_id = await self.chat_service._get_thread_id(state['agentic_application_id'], state['session_id'])
            internal_thread = await self.chat_service._get_thread_config("inside" + thread_id)

            agent_state = await meta_agent.aget_state(internal_thread)
            has_active_tasks = agent_state.tasks != ()
            if tool_interrupt_flag and has_active_tasks:
                log.info(f"[{state['session_id']}] Agent planning tool with interruption enabled, routing to tool_interrupt_node.")
                return "tool_interrupt_node"
            else:
                return "increment_step"
            
        async def tool_interrupt_node(state: PlannerMetaWorkflowState, writer: StreamWriter):
            """Asks the human if the plan is ok or not"""
           
            if tool_interrupt_flag:
                is_approved = interrupt("approved?(yes/feedback)")
                writer({"raw": {"agent_verifier": "Please confirm to execute the agent"}, "content": "Agent execution requires confirmation. Please approve to proceed."})
                if is_approved =="yes":
                    writer({"raw": {"agent_verifier": "User approved the agent execution by clicking the thumbs up button"}, "content": "User approved the agent execution by clicking the thumbs up button"})
  
            else:
                is_approved = "yes"
            return {"tool_feedback": is_approved, "is_tool_interrupted": True}
        
        async def tool_interrupt_node_decision(state: PlannerMetaWorkflowState):
            if state["tool_feedback"] == 'yes':
                return "meta_supervisor_executor"
            else:
                return "tool_interrupt_update_argument"
        
        async def tool_interrupt_update_argument(state: PlannerMetaWorkflowState, writer: StreamWriter):
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
            writer({"raw": {"tool_interrupt_final_response": final_content_parts}, "content": f"Agent execution with user's feedback completed."})
            # writer({"Node Name": "Updating Tool Arguments", "Status": "Completed"})
            
            final_ai_message = final_content_parts[-1]
            # Append event to user_update_events without mutating original list
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

            existing_events = list(state.get("user_update_events", []))
            existing_events.append(event)
            return {
                "response": final_ai_message.content,
                "executor_messages": final_content_parts,
                "user_update_events": existing_events
            }

        async def evaluator_agent(state: PlannerMetaWorkflowState,writer:StreamWriter):
            """
            Evaluates the agent response across multiple dimensions and provides scores and feedback.
            """
            log.info(f"🎯EVALUATOR AGENT CALLED for session {state['session_id']}")
            writer({"Node Name": "Evaluating Response", "Status": "Started"})
            agent_evaluation_prompt = online_agent_evaluation_prompt
            
            try:
                # Build effective query considering user_update_events tied to this query
                updates_lines = []
                for ev in state.get("user_update_events", []):
                    if ev.get("query") and ev.get("query") != state.get("query"):
                        continue
                    line = (
                        f"message : {ev.get('message','N/A')}\n"
                    )
                    updates_lines.append(line)

                if updates_lines:
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
                writer({"raw": {"evaluator_response": evaluation_data}, "content": f"Evaluation completed with score: {aggregate_score}"})
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
                    "is_tool_interrupted": False
                }
                
            except json.JSONDecodeError as e:
                writer({"Node Name": "Evaluating Response", "Status": "Failed"})
                log.error(f"Failed to parse evaluator JSON response for session {state['session_id']}: {e}")
                return {
                    "evaluation_score": 0.3,
                    "evaluation_feedback": "Evaluation failed due to JSON parsing error. Please review the response format and content quality.",
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
                    "executor_messages": ChatMessage(
                        content=f"Evaluation failed: {str(e)}",
                        role="evaluator-error"
                    ),
                    "is_tool_interrupted": False
                }

        async def evaluator_decision(state: PlannerMetaWorkflowState):
            """
            Decides whether to return the final response or continue with improvement cycle
            based on evaluation score and threshold.
            """
            evaluation_threshold = 0.7  # Configurable threshold
            max_evaluation_epochs = 3   # Maximum number of evaluation improvement cycles
            
            # Get current evaluation epoch
            current_epoch = state.get("evaluation_attempts", 0)
            evaluation_score = state.get("evaluation_score", 0.0)
            
            # Decision logic
            if evaluation_score >= evaluation_threshold or current_epoch >= max_evaluation_epochs:
                log.info(f"Evaluation passed for session {state['session_id']} - Score: {evaluation_score}, Epoch: {current_epoch}")
                return "final_response_node"
            else:
                log.info(f"Evaluation failed for session {state['session_id']} - Score: {evaluation_score}, Epoch: {current_epoch}. Routing for improvement.")
                return "increment_epoch"

        async def increment_epoch(state: PlannerMetaWorkflowState):
            """Increments the evaluation epoch counter."""
            new_epoch = state.get("epoch", 0) + 1
            log.info(f"Incrementing evaluation epoch to {new_epoch}")
            return {"epoch": new_epoch}

        ### Build Graph (Workflow) ###
        workflow = StateGraph(PlannerMetaWorkflowState)
        workflow.add_node("generate_past_conversation_summary", generate_past_conversation_summary)
        workflow.add_node("meta_planner_agent", meta_planner_agent)
        workflow.add_node("meta_supervisor_executor", meta_supervisor_executor)
        workflow.add_node("increment_step", increment_step)
        workflow.add_node("meta_response_generator", meta_response_generator)
        workflow.add_node("final_response_node", final_response_node)
        workflow.add_node("tool_interrupt_node", tool_interrupt_node)
        workflow.add_node("tool_interrupt_update_argument", tool_interrupt_update_argument)
        if flags["response_formatting_flag"]:
            workflow.add_node("formatter", lambda state: InferenceUtils.format_for_ui_node(state, llm))

        if evaluation_flag:
            workflow.add_node("evaluator_agent", evaluator_agent)
            # Node to increment evaluation epoch after each failed evaluation cycle
            workflow.add_node("increment_epoch", increment_epoch)

        # Define the workflow sequence
        workflow.add_edge(START, "generate_past_conversation_summary")
        workflow.add_edge("generate_past_conversation_summary", "meta_planner_agent")
        
        workflow.add_conditional_edges(
            "meta_planner_agent",
            route_query,
            {"meta_supervisor_executor": "meta_supervisor_executor", "meta_response_generator": "meta_response_generator"},
        )
        
        workflow.add_conditional_edges(
            "meta_supervisor_executor",
            tool_interrupt_router,
            {"tool_interrupt_node": "tool_interrupt_node", "increment_step": "increment_step"}
        )

        workflow.add_conditional_edges(
            "tool_interrupt_node",
            tool_interrupt_node_decision,
            {"meta_supervisor_executor": "meta_supervisor_executor", "tool_interrupt_update_argument": "tool_interrupt_update_argument"}
        )

        workflow.add_conditional_edges(
            "tool_interrupt_update_argument",
            tool_interrupt_router,
            {"tool_interrupt_node": "tool_interrupt_node", "increment_step": "increment_step"}
        )

        workflow.add_conditional_edges(
            "increment_step",
            check_plan_execution_status,
            {"meta_supervisor_executor": "meta_supervisor_executor", "meta_response_generator": "meta_response_generator"}
        )

        # Add conditional routing from meta_response_generator based on evaluation flag
        if evaluation_flag:
            workflow.add_edge("meta_response_generator", "evaluator_agent")
            workflow.add_conditional_edges(
                "evaluator_agent",
                evaluator_decision,
                ["increment_epoch", "final_response_node"]
            )
            # After incrementing epoch, loop back to regenerate improved response
            workflow.add_edge("increment_epoch", "meta_response_generator")
        else:
            workflow.add_edge("meta_response_generator", "final_response_node")
        
        if flags["response_formatting_flag"]:
            workflow.add_edge("final_response_node", "formatter")
            workflow.add_edge("formatter", END)
        else:
            workflow.add_edge("final_response_node", END)

        log.info("Planner Meta Agent workflow built successfully")
        return workflow
    


