# © 2024-25 Infosys Limited, Bangalore, India. All Rights Reserved.
import re
import json
from typing import Dict

from langgraph.types import interrupt
from langgraph.graph import StateGraph, START, END
from langchain_core.messages import AIMessage

from src.utils.helper_functions import get_timestamp
from src.inference.inference_utils import InferenceUtils
from src.database.services import ChatService, ToolService, AgentService
from src.inference.base_agent_inference import BaseWorkflowState, BaseAgentInference
from telemetry_wrapper import logger as log

# Marked: for later modularization
from database_manager import get_feedback_learning_data



class ReactWorkflowState(BaseWorkflowState):
    """
    State specific to the React agent workflow.
    Extends BaseWorkflowState with any React-specific attributes if needed.
    """
    preference: str
    tool_feedback: str = None
    is_tool_interrupted: bool = False



class ReactAgentInference(BaseAgentInference):
    """
    Implements the LangGraph workflow for 'react_agent' type.
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
        Builds the agent and chains for the React workflow.
        """
        tool_ids = agent_config["TOOLS_INFO"]
        system_prompt = agent_config["SYSTEM_PROMPT"]
        react_agent, _ = await self._get_react_agent_as_executor_agent(
                                        llm,
                                        system_prompt=system_prompt.get("SYSTEM_PROMPT_REACT_AGENT", ""),
                                        checkpointer=checkpointer,
                                        tool_ids=tool_ids,
                                        interrupt_tool=True
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
        llm = chains.get("llm", None)
        react_agent = chains.get("react_agent", None)

        if not llm or not react_agent:
            raise ValueError("Required chains (llm, react_agent) are missing.")

        # Nodes

        async def generate_past_conversation_summary(state: ReactWorkflowState):
            """Generates past conversation summary from the conversation history."""
            strt_tmstp = get_timestamp()
            conv_summary = new_preference = ""
            errors = []

            try:
                if state["reset_conversation"]:
                    state["executor_messages"].clear()
                    state["ongoing_conversation"].clear()
                    log.info(f"Conversation history for session {state['session_id']} has been reset.")
                else:
                    # Get summary via ChatService
                    conv_summary = await self.chat_service.get_chat_summary(
                        agentic_application_id=state["agentic_application_id"],
                        session_id=state["session_id"],
                        llm=llm
                    )

                new_preference = await self.inference_utils.update_preferences(
                    preferences=state.get("preference", "no preferences yet"),
                    user_input=state["query"],
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
                'preference': new_preference,
                'response': None,
                'start_timestamp': strt_tmstp,
                'errors': errors
            }

        async def executor_agent(state: ReactWorkflowState):
            """Handles query execution and returns the agent's response."""
            query = await self.inference_utils.add_prompt_for_feedback(state["query"])
            query = query.content
            thread_id = await self.chat_service._get_thread_id(state['agentic_application_id'], state['session_id'])
            internal_thread = await self.chat_service._get_thread_config("inside" + thread_id)
            errors = state["errors"]

            try:
                feedback_learning_data = await get_feedback_learning_data(agent_id=state["agentic_application_id"])
                feedback_msg = await self.inference_utils.format_feedback_learning_data(feedback_learning_data)

                formatted_query = f'''\
Past Conversation Summary:
{state["past_conversation_summary"]}

Ongoing Conversation:
{await self.chat_service.get_formatted_messages(state["ongoing_conversation"])}


Follow these preferences for every step:
Preferences:
{state["preference"]}
- When applicable, use these instructions to guide your responses to the user's query.


Review the previous feedback carefully and make sure the same mistakes are not repeated
**FEEDBACK**
{feedback_msg}
**END FEEDBACK**



User Query:
{query}
'''

                if state["is_tool_interrupted"]:
                    executor_agent_response = await react_agent.ainvoke(None, internal_thread)
                else:
                    executor_agent_response = await react_agent.ainvoke({"messages": [("user", formatted_query.strip())]}, internal_thread)

            except Exception as e:
                error = f"Error Occurred in Executor Agent: {e}"
                log.error(error)
                errors.append(error)
                return {"errors": errors}
            log.info("Executor Agent response generated successfully")
            return {
                "response": executor_agent_response["messages"][-1].content,
                "executor_messages": executor_agent_response["messages"],
                "errors": errors,
            }

        async def tool_interrupt_router(state: ReactWorkflowState):
            thread_id = await self.chat_service._get_thread_id(state['agentic_application_id'], state['session_id'])
            internal_thread = await self.chat_service._get_thread_config("inside" + thread_id)

            agent_state = await react_agent.aget_state(internal_thread)
            if agent_state.tasks == ():
                return "final_response"
            else:
                return "tool_interrupt_node"

        async def tool_interrupt_node(state: ReactWorkflowState):
            """Asks the human if the plan is ok or not"""
            if tool_interrupt_flag:
                is_approved = interrupt("approved?(yes/feedback)")
                log.info(f"is_approved {is_approved}")
            else:
                is_approved = "yes"
            return {"tool_feedback": is_approved, "is_tool_interrupted": True}

        async def tool_interrupt_node_decision(state: ReactWorkflowState):
            if state["tool_feedback"] == 'yes':
                return "executor_agent"
            else:
                return "tool_interrupt_update_argument"

        async def tool_interrupt_update_argument(state: ReactWorkflowState):
            thread_id = await self.chat_service._get_thread_id(state['agentic_application_id'], state['session_id'])
            internal_thread = await self.chat_service._get_thread_config("inside" + thread_id)
            model_name = state["model_name"]

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

            await react_agent.aupdate_state(
                internal_thread,
                {"messages": [new_ai_msg]}
            )
            # agent_state["executor_messages"].append(new_ai_msg)
            executor_agent_response = await react_agent.ainvoke(None, internal_thread)
            # executor_agent_response["messages"].pop()
            # for i in executor_agent_response['messages']:
            #     i.pretty_print()
            return {
                "response": executor_agent_response["messages"][-1].content,
                "executor_messages": executor_agent_response["messages"],
            }

        async def final_response(state: ReactWorkflowState):
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

            log.info("Executor Agent Final response stored successfully") 
            return {
                "ongoing_conversation": AIMessage(content=state["response"]),
                "end_timestamp": end_timestamp,
                "errors":errors
            }


        ### Build Graph (Workflow)
        workflow = StateGraph(ReactWorkflowState)

        workflow.add_node("generate_past_conversation_summary", generate_past_conversation_summary)
        workflow.add_node("executor_agent", executor_agent)
        workflow.add_node("tool_interrupt_node", tool_interrupt_node)
        workflow.add_node("tool_interrupt_update_argument", tool_interrupt_update_argument)
        workflow.add_node("final_response", final_response)

        # Define the workflow sequence
        workflow.add_edge(START, "generate_past_conversation_summary")
        workflow.add_edge("generate_past_conversation_summary", "executor_agent")

        workflow.add_conditional_edges(
            "executor_agent",
            tool_interrupt_router,
            ["tool_interrupt_node", "final_response"],
        )
        workflow.add_conditional_edges(
            "tool_interrupt_node",
            tool_interrupt_node_decision,
            ["tool_interrupt_update_argument", "executor_agent"],
        )
        workflow.add_conditional_edges(
            "tool_interrupt_update_argument",
            tool_interrupt_router,
            ["tool_interrupt_node", "final_response"],
        )
        workflow.add_edge("final_response", END)

        log.info("Executor Agent workflow built successfully")
        return workflow



