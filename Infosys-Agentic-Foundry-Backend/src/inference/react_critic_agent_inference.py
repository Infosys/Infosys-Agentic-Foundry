# © 2024-25 Infosys Limited, Bangalore, India. All Rights Reserved.
import json
from typing import Dict, List, Optional, Literal,Any
from fastapi import HTTPException

from langgraph.types import interrupt
from langgraph.graph import StateGraph, START, END
from langchain_core.messages import AIMessage, ChatMessage

from src.utils.helper_functions import get_timestamp
from src.inference.inference_utils import InferenceUtils
from src.database.services import ChatService, ToolService, AgentService
from src.inference.base_agent_inference import BaseWorkflowState, BaseAgentInference
from telemetry_wrapper import logger as log

# Marked: for later modularization
from database_manager import get_feedback_learning_data



class ReactCriticWorkflowState(BaseWorkflowState):
    """
    State specific to the React agent workflow.
    Extends BaseWorkflowState with any React-specific attributes if needed.
    """
    response_quality_score: float
    critique_points: str
    epoch: int
    preference: str
    tool_feedback: str = None
    is_tool_interrupted: bool = False




class ReactCriticAgentInference(BaseAgentInference):
    """
    Implements the LangGraph workflow for 'multi_agent' type.
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
        Builds the agent and chains for the React-Critic-Agent workflow.
        """
        tool_ids = agent_config["TOOLS_INFO"]
        system_prompt = agent_config["SYSTEM_PROMPT"]

        executor_system_prompt = system_prompt.get("SYSTEM_PROMPT_EXECUTOR_AGENT", "")
        critic_system_prompt = system_prompt.get("SYSTEM_PROMPT_CRITIC_AGENT", "").replace("{", "{{").replace("}", "}}")

        # Executor Agent
        executor_agent, tool_list = await self._get_react_agent_as_executor_agent(
                                        llm,
                                        system_prompt=executor_system_prompt,
                                        checkpointer=checkpointer,
                                        tool_ids=tool_ids,
                                        interrupt_tool=True
                                    )
        # Critic Agent Chains
        critic_chain_json, critic_chain_str = await self._get_chains(llm, critic_system_prompt)

        log.info("React Critic Agent - Chains built successfully")

        chains = {
            "llm": llm,
            "agent_executor": executor_agent,
            "tool_list": tool_list,

            "critic_chain_json": critic_chain_json,
            "critic_chain_str": critic_chain_str,
        }

        return chains

    async def _build_workflow(self, chains: dict, flags: Dict[str, bool] = {}) -> StateGraph:
        """
        Builds the LangGraph workflow for a Planner-Executor-Critic Agent.
        """
        tool_interrupt_flag = flags.get("tool_interrupt_flag", False)

        llm = chains.get("llm", None)
        executor_agent = chains.get("agent_executor", None)
        tool_list = chains.get("tool_list", [])

        critic_chain_json = chains.get("critic_chain_json", None)
        critic_chain_str = chains.get("critic_chain_str", None)


        if not llm or not executor_agent or not critic_chain_json or not critic_chain_str :
            raise HTTPException(status_code=500, detail="Required chains or agent executor are missing")

        # Nodes

        async def generate_past_conversation_summary(state: ReactCriticWorkflowState):
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
                        llm=llm,
                        executor_messages=state["executor_messages"]
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
            new_state = {
                'past_conversation_summary': conv_summary,
                'ongoing_conversation': current_state_query,
                'executor_messages': current_state_query,
                'preference': new_preference,
                'response': None,
                'start_timestamp': strt_tmstp,
                'response_quality_score': None,
                'critique_points': None,
                'epoch': 0,
                'errors': errors
            }
            return new_state

        async def executor_agent_node(state: ReactCriticWorkflowState):
            """Handles query execution and returns the agent's response."""
            query = await self.inference_utils.add_prompt_for_feedback(state["query"])
            query = query.content
            thread_id = await self.chat_service._get_thread_id(state['agentic_application_id'], state['session_id'])
            internal_thread = await self.chat_service._get_thread_config("inside" + thread_id)
            errors = state["errors"]

            try:
                feedback_learning_data = await get_feedback_learning_data(agent_id=state["agentic_application_id"])
                feedback_msg = await self.inference_utils.format_feedback_learning_data(feedback_learning_data)

                critic_messages = ""
                if state.get("response_quality_score", None) is not None:
                    critic_messages = f"""
Final Response Obtained:
{state["response"]}

Critic Agent's Response Quality Score:
{state["response_quality_score"]}

Critic Agent Feedback:
{await self.inference_utils.format_list_str(state["critique_points"])}
"""

                formatted_query = f"""\
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
{critic_messages}
"""

                if state["is_tool_interrupted"]:
                    executor_agent_response = await executor_agent.ainvoke(None, internal_thread)
                else:
                    executor_agent_response = await executor_agent.ainvoke({"messages": [("user", formatted_query.strip())]}, internal_thread)

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

        async def critic_agent(state: ReactCriticWorkflowState):
            """
            This function takes a state object containing information about the conversation and the generated response,
            formats it into a query for the critic model, and returns the critic's evaluation of the response.
            """
            tool_args_update_context = "" if state.get("tool_feedback", None) in (None, "yes") else (
                            f"\nNote:\nTool arguments have been updated by the user: {state['tool_feedback']}. "
                            "So the final response should be based on the updated tool arguments. "
                            "Prioritize this part over the user query if there is a conflict."
                        )
            formatted_query = f'''\
Past Conversation Summary:
{state["past_conversation_summary"]}

Ongoing Conversation:
{await self.chat_service.get_formatted_messages(state["ongoing_conversation"])}

Tools Info:
{await self.tool_service.render_text_description_for_tools(tool_list)}

User Query:
{state["query"]}
{tool_args_update_context}

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

            if critic_response["critique_points"] and "error" in critic_response["critique_points"][0]:
                critic_response = {'response_quality_score': 0, 'critique_points': critic_response["critique_points"]}
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
                ),
                "epoch": state["epoch"]+1
            }

        async def final_response(state: ReactCriticWorkflowState):
            """
            This function handles the final response of the conversation.
            """
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
            log.info(f"Final response generated for session {state['session_id']}")
            return {
                "ongoing_conversation": final_response_message,
                "executor_messages": final_response_message,
                "end_timestamp": end_timestamp,
                "errors": errors
            }

        async def critic_decision(state:ReactCriticWorkflowState):
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
            if state["response_quality_score"]>=0.7 or state["epoch"]==2:
                return "final_response"
            else:
                return "executor_agent_node" 

        async def final_decision(state: ReactCriticWorkflowState):
            thread_id = await self.chat_service._get_thread_id(state['agentic_application_id'], state['session_id'])
            internal_thread = await self.chat_service._get_thread_config("inside" + thread_id)
            a = await executor_agent.aget_state(internal_thread)
            if a.tasks == ():
                return "critic_agent"
            else:
                return "interrupt_node_for_tool"

        async def interrupt_node_for_tool(state: ReactCriticWorkflowState):
            """Asks the human if the plan is ok or not"""
            if tool_interrupt_flag:
                is_approved = interrupt("approved?(yes/feedback)") 
            else:
                is_approved = "yes"
            return {"tool_feedback": is_approved, "is_tool_interrupted": True}

        async def interrupt_node_decision_for_tool(state: ReactCriticWorkflowState):
            if state["tool_feedback"]=='yes':
                return "executor_agent_node"
            else:
                return "tool_interrupt"

        async def tool_interrupt(state: ReactCriticWorkflowState):
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

            # Modify the thread with the new input
            await executor_agent.aupdate_state(
                internal_thread,
                {"messages": [new_ai_msg]}
            )
            # state["executor_messages"].append(new_ai_msg)
            executor_agent_response = await executor_agent.ainvoke(None, internal_thread)
            # for i in executor_agent_response['messages']:
            #     i.pretty_print()
                        
            return {
                "response": executor_agent_response["messages"][-1].content,
                "executor_messages": executor_agent_response["messages"],
                "is_tool_interrupted": False
            }


        ### Build Graph
        workflow = StateGraph(ReactCriticWorkflowState)
        workflow.add_node("generate_past_conversation_summary", generate_past_conversation_summary)
        workflow.add_node("executor_agent_node", executor_agent_node)
        workflow.add_node("critic_agent", critic_agent)
        workflow.add_node("final_response", final_response)
        workflow.add_node("final_decision", final_decision)
        workflow.add_node("tool_interrupt", tool_interrupt)
        workflow.add_node("interrupt_node_for_tool", interrupt_node_for_tool)

        workflow.add_edge(START, "generate_past_conversation_summary")
        workflow.add_edge("generate_past_conversation_summary", "executor_agent_node")
        workflow.add_conditional_edges(
            "executor_agent_node",
            final_decision,
            ["interrupt_node_for_tool", "critic_agent"],
        )
        workflow.add_conditional_edges(
            "interrupt_node_for_tool",
            interrupt_node_decision_for_tool,
            ["executor_agent_node", "tool_interrupt"],
        )
        workflow.add_conditional_edges(
            "tool_interrupt",
            final_decision,
            ["interrupt_node_for_tool", "critic_agent"],
        )
        workflow.add_conditional_edges(
            "critic_agent",
            critic_decision,
            ["final_response", "executor_agent_node"],
        )
        workflow.add_edge("final_response", END)
        log.info(" Executor, Critic agent workflow built successfully.")
        return workflow



