# © 2024-25 Infosys Limited, Bangalore, India. All Rights Reserved.
from typing import Dict
import asyncio
from langgraph.types import interrupt
from langgraph.graph import StateGraph, START, END
from langchain_core.messages import AIMessage

from src.utils.helper_functions import get_timestamp
from src.inference.inference_utils import InferenceUtils
from src.inference.base_agent_inference import BaseWorkflowState, BaseMetaTypeAgentInference
from telemetry_wrapper import logger as log

from src.inference.inference_utils import EpisodicMemoryManager

class MetaWorkflowState(BaseWorkflowState):
    """
    State specific to the Meta agent workflow.
    Extends BaseWorkflowState with any Meta-specific attributes if needed.
    """
    pass



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
            worker_agent_ids=worker_agent_ids
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
        llm = chains.get("llm", None)
        meta_agent = chains.get("meta_agent", None)

        if not llm or not meta_agent:
            raise ValueError("Required chains (llm, meta_agent) are missing.")

        # Nodes

        async def generate_past_conversation_summary(state: MetaWorkflowState):
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
                    if state["context_flag"]==False:
                        return{
                            'past_conversation_summary': "No past conversation summary available.",
                            'ongoing_conversation': current_state_query,
                            'executor_messages': current_state_query,
                            'response': None,
                            'start_timestamp': strt_tmstp,
                            'errors': errors
                        }
                    # Get summary via ChatService
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
                'ongoing_conversation': current_state_query,
                'executor_messages': current_state_query,
                'response': None,
                'start_timestamp': strt_tmstp,
                'errors': errors
            }

        async def meta_agent_node(state: MetaWorkflowState):
            """
            Creates a meta agent that supervises the worker agents.
            """
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
            formatter_node_prompt = ""
            if state["response_formatting_flag"]:
                formatter_node_prompt = "You are an intelligent assistant that provides data for a separate visualization tool. When a user asks for a chart, table, image, or any other visual element, you must not attempt to create the visual yourself in text. Your sole responsibility is to generate the raw, structured data. For example, for a chart, provide the JSON data; for an image, provide the <img> tag with a source URL; for a table, provide the data as a list of lists. Your output will be fed into another program that will handle the final formatting and display."
                    
            formatted_query = f"""\
**User Input Context**
Past Conversation Summary:
{state["past_conversation_summary"]}

Ongoing Conversation:
{await self.chat_service.get_formatted_messages(state["ongoing_conversation"]) if state["context_flag"] else "No ongoing conversation."}


{formatter_node_prompt}


User Query:
{messages}
"""

            response = await meta_agent.ainvoke({
                "messages": [{
                    "role": "user",
                    "content": formatted_query,
                }]
            })

            final_response = response["messages"][-1].content
            log.info(f"Meta Agent response generated: {final_response}")
            return {
                "response": final_response,
                "executor_messages": response["messages"]
            }

        async def final_response_node(state: MetaWorkflowState):
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
            log.info(f"Meta Agent's final response generated: {final_response_message.content}")
            return {
                "ongoing_conversation": final_response_message,
                "end_timestamp": end_timestamp,
                "errors":errors
            }
        
        ### Build Graph (Workflow)
        workflow = StateGraph(MetaWorkflowState)
        workflow.add_node("generate_past_conversation_summary", generate_past_conversation_summary)
        workflow.add_node("meta_agent_node", meta_agent_node)
        workflow.add_node("final_response_node", final_response_node)
        if flags["response_formatting_flag"]:
            workflow.add_node("formatter", lambda state: InferenceUtils.format_for_ui_node(state, llm))


        # Define the workflow sequence
        workflow.add_edge(START, "generate_past_conversation_summary")
        workflow.add_edge("generate_past_conversation_summary", "meta_agent_node")
        workflow.add_edge("meta_agent_node", "final_response_node")
        if flags["response_formatting_flag"]:
            workflow.add_edge("final_response_node", "formatter")
            workflow.add_edge("formatter", END)
        else:
            workflow.add_edge("final_response_node", END)

        return workflow


