# © 2024-25 Infosys Limited, Bangalore, India. All Rights Reserved.
from typing import Dict

from langgraph.types import interrupt
from langgraph.graph import StateGraph, START, END
from langchain_core.messages import AIMessage

from src.utils.helper_functions import get_timestamp
from src.inference.inference_utils import InferenceUtils
from src.database.services import ChatService, ToolService, AgentService
from src.inference.base_agent_inference import BaseWorkflowState, BaseMetaTypeAgentInference
from telemetry_wrapper import logger as log



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

    def __init__(
        self,
        chat_service: ChatService,
        tool_service: ToolService,
        agent_service: AgentService,
        inference_utils: InferenceUtils
    ):
        super().__init__(chat_service, tool_service, agent_service, inference_utils)


    async def _build_agent_and_chains(self, llm, agent_config, checkpointer = None):
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

            try:
                if state["reset_conversation"]:
                    state["ongoing_conversation"].clear()
                    state["executor_messages"].clear()
                    log.info(f"Conversation history for session {state['session_id']} has been reset.")
                else:
                    # Get summary via ChatService
                    conv_summary = await self.chat_service.get_chat_summary(
                        agentic_application_id=state["agentic_application_id"],
                        session_id=state["session_id"],
                        llm=llm
                    )

            except Exception as e:
                error = f"Error occurred while generating past conversation summary: {e}"
                log.error(error)
                errors.append(error)

            current_state_query = await self.inference_utils.add_prompt_for_feedback(state["query"])

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
            formatted_query = f"""\
**User Input Context**
Past Conversation Summary:
{state["past_conversation_summary"]}

Ongoing Conversation:
{await self.chat_service.get_formatted_messages(state["ongoing_conversation"])}

User Query:
{state["query"]}
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
            errors = []
            end_timestamp = get_timestamp()
            try:
                await self.chat_service.save_chat_message(
                                        agentic_application_id=state["agentic_application_id"],
                                        session_id=state["session_id"],
                                        start_timestamp=state["start_timestamp"],
                                        end_timestamp=end_timestamp,
                                        human_message=state["query"],
                                        ai_message=state["response"]
                                    )
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

        # Define the workflow sequence
        workflow.add_edge(START, "generate_past_conversation_summary")
        workflow.add_edge("generate_past_conversation_summary", "meta_agent_node")
        workflow.add_edge("meta_agent_node", "final_response_node")
        workflow.add_edge("final_response_node", END)

        return workflow


