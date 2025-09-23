# © 2024-25 Infosys Limited, Bangalore, India. All Rights Reserved.
from typing import Dict, List
import asyncio
from langgraph.types import interrupt
from langgraph.graph import StateGraph, START, END
from langchain_core.messages import AIMessage, ChatMessage

from src.utils.helper_functions import get_timestamp
from src.inference.inference_utils import InferenceUtils
from src.inference.base_agent_inference import BaseWorkflowState, BaseMetaTypeAgentInference
from telemetry_wrapper import logger as log

from src.inference.inference_utils import EpisodicMemoryManager

class PlannerMetaWorkflowState(BaseWorkflowState):
    """
    State specific to the Planner Meta Agent workflow.
    Extends BaseWorkflowState with any Meta-specific attributes if needed.
    """
    plan: List[str]
    past_steps_input: List[str]
    past_steps_output: List[str]
    step_idx: int



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
            worker_agent_ids=worker_agent_ids
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
        llm = chains.get("llm", None)
        meta_agent = chains.get("meta_agent", None)
        meta_planner_chain_json = chains.get("meta_planner_chain_json", None)
        meta_planner_chain_str = chains.get("meta_planner_chain_str", None)
        meta_responder_chain = chains.get("meta_responder_chain", None)

        if not llm or not meta_agent or not meta_planner_chain_json or not meta_planner_chain_str or \
                not meta_responder_chain:
            raise ValueError("Required chains (llm, meta_agent, meta_planner_chain_json, meta_planner_chain_str, meta_responder_chain) are missing.")

        # Nodes

        async def generate_past_conversation_summary(state: PlannerMetaWorkflowState):
            """Generates past conversation summary from the conversation history."""
            strt_tmstp = get_timestamp()
            conv_summary = ""
            errors = []
            current_state_query = await self.inference_utils.add_prompt_for_feedback(state["query"])
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
                            'executor_messages': current_state_query,
                            'ongoing_conversation': current_state_query,
                            'response': None,
                            'start_timestamp': strt_tmstp,
                            'plan': [],
                            'past_steps_output': [],
                            'step_idx': 0,
                            'errors': errors
                        }
                    conv_summary = await self.chat_service.get_chat_conversation_summary(
                        agentic_application_id=state["agentic_application_id"],
                        session_id=state["session_id"]
                    )
                conv_summary = conv_summary.get("summary", "") if conv_summary else ""

            except Exception as e:
                error = f"Error occurred while generating past conversation summary: {e}"
                log.error(error)
                errors.append(error)

            log.info(f"Generated past conversation summary for session {state['session_id']}.")
            return {
                'past_conversation_summary': conv_summary,
                'executor_messages': current_state_query,
                'ongoing_conversation': current_state_query,
                'response': None,
                'start_timestamp': strt_tmstp,
                'plan': [],
                'past_steps_output': [],
                'step_idx': 0,
                'errors': errors
            }

        async def meta_planner_agent(state: PlannerMetaWorkflowState):
            """Generates a plan for the supervisor to execute."""

            if state["context_flag"]:
                user_id = state["agentic_application_id"]      
                query = state["query"]
                episodic_memory = EpisodicMemoryManager(user_id)
                relevant = await episodic_memory.find_relevant_examples_for_query(query)
                pos_examples = relevant.get("positive", [])
                neg_examples = relevant.get("negative", [])
                context = await episodic_memory.create_context_from_examples(pos_examples, neg_examples)
                messages = []
                if context:
                    messages.append({"role": "user", "content": context})
                    messages.append({"role": "assistant", "content":
                        "I will use positive examples as guidance and explicitly avoid negative examples."})
                messages.append({"role": "user", "content": query})
                if pos_examples == [] and neg_examples == []:
                    messages = query
            else:
                messages = state["query"]

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
            except Exception as e:
                log.error(f"Error occurred while generating plan: {e}")
                planner_response = {"plan": []}
            response = {"plan": planner_response["plan"]}
            if planner_response["plan"]:
                response["executor_messages"] = ChatMessage(content=planner_response["plan"], role="plan")
            return response

        async def meta_supervisor_executor(state: PlannerMetaWorkflowState):
            """Supervisor executes one step of the plan by delegating to a worker."""
            # Get the current step to execute
            step = state["plan"][state["step_idx"]]
            completed_steps = []
            completed_steps_responses = []
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

            result = await meta_agent.ainvoke({
                "messages": [{
                        "role": "user",
                        "content": task_formatted
                }]
            })
            completed_steps.append(step)
            completed_steps_responses.append(result["messages"][-1].content)
            step_output = result["messages"][-1].content
            log.info(f"Supervisor got result for step {state['step_idx']}: {step_output}")


            return {
                "response": completed_steps_responses[-1],
                "past_steps_input": completed_steps,
                "past_steps_output": completed_steps_responses,
                "executor_messages": result["messages"]
            }

        async def increment_step(state: PlannerMetaWorkflowState):
            """Increments the step counter."""
            new_idx = state["step_idx"] + 1
            log.info(f"Incrementing to step {new_idx}")
            return {"step_idx": new_idx}

        async def meta_response_generator(state: PlannerMetaWorkflowState):
            """Generates the final response by synthesizing all step outputs."""
            formatter_node_prompt = ""
            if state["response_formatting_flag"]:
                formatter_node_prompt = "\n\nYou are an intelligent assistant that provides data for a separate visualization tool. When a user asks for a chart, table, image, or any other visual element, you must not attempt to create the visual yourself in text. Your sole responsibility is to generate the raw, structured data. For example, for a chart, provide the JSON data; for an image, provide the <img> tag with a source URL; for a table, provide the data as a list of lists. Your output will be fed into another program that will handle the final formatting and display."
                    
            if not state["plan"]:
                # If there was no plan, the supervisor was never called.
                # We can create a simple response directly.
                log.info("No plan found. Generating direct response.")
                prompt = f"The user asked: '{state['query']}'. Please provide a direct, helpful response."
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

Please synthesize these results into a single, comprehensive, and well-formatted final answer for the user.
"""
            response = await meta_responder_chain.ainvoke({"messages": [("user", prompt)]})
            log.info(f"Final response generated: {response}")
            return {"response": response}

        async def final_response_node(state: PlannerMetaWorkflowState):
            """Stores the final response and updates the conversation history."""
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
                log.error(error)
                errors.append(error)

            final_response_message = AIMessage(content=state["response"])
            log.info(f"Planner Meta Agent's final response generated: {final_response_message.content}")
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

        ### Build Graph (Workflow) ###
        workflow = StateGraph(PlannerMetaWorkflowState)
        workflow.add_node("generate_past_conversation_summary", generate_past_conversation_summary)
        workflow.add_node("meta_planner_agent", meta_planner_agent)
        workflow.add_node("meta_supervisor_executor", meta_supervisor_executor)
        workflow.add_node("increment_step", increment_step)
        workflow.add_node("meta_response_generator", meta_response_generator)
        workflow.add_node("final_response_node", final_response_node)
        if flags["response_formatting_flag"]:
            workflow.add_node("formatter", lambda state: InferenceUtils.format_for_ui_node(state, llm))


        # Define the workflow sequence
        workflow.add_edge(START, "generate_past_conversation_summary")
        workflow.add_edge("generate_past_conversation_summary", "meta_planner_agent")
        
        workflow.add_conditional_edges(
            "meta_planner_agent",
            route_query,
            {"meta_supervisor_executor": "meta_supervisor_executor", "meta_response_generator": "meta_response_generator"},
        )
        
        workflow.add_edge("meta_supervisor_executor", "increment_step")

        workflow.add_conditional_edges(
            "increment_step",
            check_plan_execution_status,
            {"meta_supervisor_executor": "meta_supervisor_executor", "meta_response_generator": "meta_response_generator"}
        )

        workflow.add_edge("meta_response_generator", "final_response_node")
        if flags["response_formatting_flag"]:
            workflow.add_edge("final_response_node", "formatter")
            workflow.add_edge("formatter", END)
        else:
            workflow.add_edge("final_response_node", END)

        return workflow
    


