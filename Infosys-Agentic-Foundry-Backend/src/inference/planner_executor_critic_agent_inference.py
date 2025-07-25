# © 2024-25 Infosys Limited, Bangalore, India. All Rights Reserved.
import json
from typing import Dict, List, Optional, Literal
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
    epoch: int
    step_idx: int # App Related vars
    preference: str
    tool_feedback: str = None
    is_tool_interrupted: bool = False
    current_query_status: Optional[Literal["plan", "feedback", None]] = None

class MultiHITLWorkflowState(MultiWorkflowState):
    is_plan_approved: Optional[Literal["yes", "no", None]] = None
    plan_feedback: Optional[str] = None



class MultiAgentInference(BaseAgentInference):
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
                                        interrupt_tool=True
                                    )

        # Planner Agent Chains
        planner_chain_json, planner_chain_str = await self._get_chains(llm, planner_system_prompt)

        # Replanner Agent Chains
        replanner_chain_json, replanner_chain_str = await self._get_chains(llm, replanner_system_prompt)

        # Critic-Based Planner Agent Chains
        critic_planner_chain_json, critic_planner_chain_str = await self._get_chains(llm, critic_based_planner_system_prompt)

        # General Query Handler Agent Chain
        _, general_query_chain = await self._get_chains(llm, general_query_system_prompt, get_json_chain=False)

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
        hitl_flag = flags.get("hitl_flag", False)

        if not llm or not executor_agent or not planner_chain_json or not planner_chain_str or \
                not critic_planner_chain_json or not critic_planner_chain_str or not general_query_chain or \
                not critic_chain_json or not critic_chain_str or not response_gen_chain_json or not response_gen_chain_str or \
                (hitl_flag and (not replanner_chain_json or not replanner_chain_str)):
            raise HTTPException(status_code=500, detail="Required chains or agent executor are missing")

        # Nodes

        async def generate_past_conversation_summary(state: MultiWorkflowState | MultiHITLWorkflowState):
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
                'plan': None,
                'past_steps_input': None,
                'past_steps_output': None,
                'epoch': 0,
                'step_idx': 0,
                'current_query_status': None,
                'errors': errors
            }
            if hitl_flag:
                new_state.update({
                    'is_plan_approved': None,
                    'plan_feedback': None
                })

            return new_state

        async def planner_agent(state: MultiWorkflowState | MultiHITLWorkflowState):
            """
            This function takes the current state of the conversation and generates a plan for the agent to follow.
            """
            feedback_learning_data = await get_feedback_learning_data(agent_id=state["agentic_application_id"])
            feedback_msg = await self.inference_utils.format_feedback_learning_data(feedback_learning_data)

            # Format the query for the planner
            formatted_query = f'''\
Past Conversation Summary:
{state["past_conversation_summary"]}

Ongoing Conversation:
{await self.chat_service.get_formatted_messages(state["ongoing_conversation"])}

Tools Info:
{await self.tool_service.render_text_description_for_tools(tool_list)}


Follow these preferences for every step:
Preferences:
{state["preference"]}
- When applicable, use these instructions to guide your responses to the user's query.

Review the previous feedback carefully and make sure the same mistakes are not repeated
**FEEDBACK**
{feedback_msg}
**END FEEDBACK**

Input Query:
{state["query"]}

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

            response_state = {"plan": planner_response['plan']}
            if planner_response['plan']:
                response_state.update({
                    "executor_messages": ChatMessage(content=planner_response['plan'], role="plan"),
                    "current_query_status": "plan" if hitl_flag else None
                })

            log.info(f"Plan generated for session {state['session_id']}")
            return response_state

        async def replanner_agent(state: MultiHITLWorkflowState):
            """
            This function takes the current state of the conversation and revises the previous plan based on user feedback.
            """
            # Format the query for the replanner
            formatted_query = f'''\
Past Conversation Summary:
{state["past_conversation_summary"]}

Ongoing Conversation:
{await self.chat_service.get_formatted_messages(state["ongoing_conversation"])}

Tools Info:
{await self.tool_service.render_text_description_for_tools(tool_list)}

Previous Plan:
{state["plan"]}

Input Query:
{state["query"]}

User Feedback:
{state["plan_feedback"]}

**Note**:
- Update or revise the current plan according to the user's feedback correctly.
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
            log.info(f"New plan generated for session {state['session_id']}")
            return {
                "plan": replanner_response.get('plan', []),
                "response": replanner_response.get('response', ''),
                "executor_messages": ChatMessage(content=replanner_response.get('plan', []), role="re-plan"),
                "current_query_status": "plan"
            }

        async def general_llm_call(state: MultiWorkflowState | MultiHITLWorkflowState):
            """
            This function calls the LLM with the user's query and returns the LLM's response.
            """
            formatted_query = f'''\
Past Conversation Summary:
{state["past_conversation_summary"]}

User Query:
{state["query"]}

Note:
    -Only respond if the above User Query including greetings, feedback, and appreciation, engage in getting to know each other type of conversation, or queries related to the agent itself, such as its expertise or purpose.
    - If the query is not related to the agent's expertise, agent's goal, agent's role, workflow description, and tools it has access to and it requires external knowledge, DO NOT provide a answer to such a query, just politely inform the user that you are not capable to answer such queries.
'''
            response = await general_query_chain.ainvoke({"messages": [("user", formatted_query)]})
            log.info(f"General LLM response generated for session {state['session_id']}")
            return {
                "response": response
            }

        async def executor_agent_node(state: MultiWorkflowState | MultiHITLWorkflowState):
            """
            Executes the current step in the plan using the executor agent.
            """
            thread_id = await self.chat_service._get_thread_id(state['agentic_application_id'], state['session_id'])
            internal_thread = await self.chat_service._get_thread_config("inside" + thread_id)

            step = state["plan"][state["step_idx"]]
            completed_steps = []
            completed_steps_responses = []
            feedback_learning_data = await get_feedback_learning_data(agent_id=state["agentic_application_id"])
            feedback_msg = await self.inference_utils.format_feedback_learning_data(feedback_learning_data)

            task_formatted = f"""\
Past Conversation Summary:
{state['past_conversation_summary']}

Ongoing Conversation:
{await self.chat_service.get_formatted_messages(state['ongoing_conversation'])}

Review the previous feedback carefully and make sure the same mistakes are not repeated
**FEEDBACK**
{feedback_msg}
**END FEEDBACK**

"""

            if state["step_idx"]!=0:
                completed_steps = state["past_steps_input"][:state["step_idx"]]
                completed_steps_responses = state["past_steps_output"][:state["step_idx"]]
                task_formatted += f"Past Steps:\n{await self.inference_utils.format_past_steps_list(completed_steps, completed_steps_responses)}"
            task_formatted += f"\n\nCurrent Step:\n{step}"

            if state["is_tool_interrupted"]:
                executor_agent_response = await executor_agent.ainvoke(None, internal_thread)
            else:
                executor_agent_response = await executor_agent.ainvoke({"messages": [("user", task_formatted.strip())]}, internal_thread)

            completed_steps.append(step)
            completed_steps_responses.append(executor_agent_response["messages"][-1].content)
            log.info(f"Executor Agent response generated for session {state['session_id']} at step {state['step_idx']}")
            return {
                "response": completed_steps_responses[-1],
                "past_steps_input": completed_steps,
                "past_steps_output": completed_steps_responses,
                "executor_messages": executor_agent_response["messages"]
            }

        async def increment_step(state: MultiWorkflowState | MultiHITLWorkflowState):
            log.info(f"Incrementing step index for session {state['session_id']} to {state['step_idx'] + 1}")
            return {"step_idx": state["step_idx"]+1, "is_tool_interrupted": False}

        async def response_generator_agent(state: MultiWorkflowState | MultiHITLWorkflowState):
            """
            This function takes the current state of the conversation and generates a response using a response generation chain.
            """
            feedback_context = "" if not hitl_flag else f"""
User Feedback (prioritize this over the user Query for final response ):
{state["plan_feedback"]}
"""

            formatted_query = f'''\
Past Conversation Summary:
{state["past_conversation_summary"]}

Ongoing Conversation:
{await self.chat_service.get_formatted_messages(state["ongoing_conversation"])}

Follow these preferences for every step:
Preferences:
{state["preference"]}
- When applicable, use these instructions to guide your responses to the user's query.


User Query:
{state["query"]}
{feedback_context}

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
            if isinstance(response_gen_response, dict) and "response" in response_gen_response:
                log.info(f"Response generated for session {state['session_id']}")
                return {"response": response_gen_response["response"]}
            else:
                log.error(f"Response generation failed for session {state['session_id']}")
                result = await llm.ainvoke(f"Format the response in Markdown Format.\n\nResponse: {response_gen_response}")
                return {"response": result.content}

        async def critic_agent(state: MultiWorkflowState | MultiHITLWorkflowState):
            """
            This function takes a state object containing information about the conversation and the generated response,
            formats it into a query for the critic model, and returns the critic's evaluation of the response.
            """
            feedback_context = "" if not hitl_flag else f"""
Now user want to modify above query with below modification:
{state["tool_feedback"]}
"""

            formatted_query = f'''\
Past Conversation Summary:
{state["past_conversation_summary"]}

Ongoing Conversation:
{await self.chat_service.get_formatted_messages(state["ongoing_conversation"])}

Tools Info:
{await self.tool_service.render_text_description_for_tools(tool_list)}

User Query:
{state["query"]}
{feedback_context}

Steps Completed to generate final response:
{await self.inference_utils.format_past_steps_list(state["past_steps_input"], state["past_steps_output"])}

Final Response:
{state["response"]}

##Instructions
- Consider the modifications given by user along with actual query
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

        async def critic_based_planner_agent(state: MultiWorkflowState | MultiHITLWorkflowState):
            """
            This function takes a state object containing information about the current conversation, tools, and past steps,
            and uses a critic-based planner to generate a plan for the next step.
            """
            feedback_context = "" if not hitl_flag else f"""
*Now user want to modify above query with below modification:
{state["tool_feedback"]}
"""

            formatted_query = f'''
Past Conversation Summary:
{state["past_conversation_summary"]}

Ongoing Conversation:
{await self.chat_service.get_formatted_messages(state["ongoing_conversation"])}

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
{state["response_quality_score"]}

Critique Points:
{await self.inference_utils.format_list_str(state["critique_points"])}
'''

            invocation_input = {"messages": [("user", formatted_query)]}
            critic_planner_response = await self.inference_utils.output_parser(
                                                                    llm=llm,
                                                                    chain_1=critic_planner_chain_json,
                                                                    chain_2=critic_planner_chain_str,
                                                                    invocation_input=invocation_input,
                                                                    error_return_key="plan"
                                                                )
            log.info(f"Critic-based planner response generated for session {state['session_id']}")
            return {
                "plan": critic_planner_response["plan"],
                "executor_messages": ChatMessage(content=critic_planner_response['plan'], role="critic-plan"),
                "step_idx": 0
            }

        async def final_response(state: MultiWorkflowState | MultiHITLWorkflowState):
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

        async def critic_decision(state: MultiWorkflowState | MultiHITLWorkflowState):
            """
            Decides whether to return the final response or continue
            with the critic-based planner agent.
            """
            if state["response_quality_score"]>=0.7 or state["epoch"]==3:
                return "final_response"
            else:
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
                return "interrupt_node" if hitl_flag else "executor_agent_node"

        async def interrupt_node(state: MultiHITLWorkflowState):
            """Asks the human if the plan is ok or not"""
            is_plan_approved = interrupt("Is this plan acceptable?").lower()
            return {
                "is_plan_approved": is_plan_approved,
                "current_query_status": "feedback" if is_plan_approved == 'no' else None,
            }

        async def interrupt_node_decision(state: MultiHITLWorkflowState):
            if state["is_plan_approved"]=='no':
                return "feedback_collector"
            else:
                return "executor_agent_node"

        async def feedback_collector(state: MultiHITLWorkflowState):
            feedback = interrupt("What went wrong??")
            return {
                'plan_feedback': feedback,
                'current_query_status': None
            }



        async def final_decision(state: MultiWorkflowState | MultiHITLWorkflowState):
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
                    return "final_response"
            else:
                return "interrupt_node_for_tool"

        async def interrupt_node_for_tool(state: MultiWorkflowState | MultiHITLWorkflowState):
            """Asks the human if the plan is ok or not"""
            if tool_interrupt_flag:
                is_plan_approved = interrupt("approved?(yes/feedback)") 
            else:
                is_plan_approved = "yes"
            return {"tool_feedback": is_plan_approved, "is_tool_interrupted": True}

        async def interrupt_node_decision_for_tool(state: MultiWorkflowState | MultiHITLWorkflowState):
            if state["tool_feedback"]=='yes':
                return "executor_agent_node"
            else:
                return "tool_interrupt"

        async def tool_interrupt(state: MultiWorkflowState | MultiHITLWorkflowState):
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
            }


        ### Build Graph
        workflow = StateGraph(MultiWorkflowState if not hitl_flag else MultiHITLWorkflowState)

        workflow.add_node("generate_past_conversation_summary", generate_past_conversation_summary)
        workflow.add_node("planner_agent", planner_agent)

        if hitl_flag:
            workflow.add_node("replanner_agent", replanner_agent)
            workflow.add_node("interrupt_node", interrupt_node)
            workflow.add_node("feedback_collector", feedback_collector)

        workflow.add_node("general_llm_call", general_llm_call)
        workflow.add_node("executor_agent_node", executor_agent_node)
        workflow.add_node("increment_step", increment_step)
        workflow.add_node("response_generator_agent", response_generator_agent)
        workflow.add_node("critic_agent", critic_agent)
        workflow.add_node("critic_based_planner_agent", critic_based_planner_agent)
        workflow.add_node("final_response", final_response)
        workflow.add_node("final_decision", final_decision)
        workflow.add_node("interrupt_node_for_tool", interrupt_node_for_tool)
        workflow.add_node("tool_interrupt", tool_interrupt)


        workflow.add_edge(START, "generate_past_conversation_summary")
        workflow.add_edge("generate_past_conversation_summary", "planner_agent")
        workflow.add_conditional_edges(
            "planner_agent",
            route_general_question,
            ["general_llm_call", "executor_agent_node" if not hitl_flag else "interrupt_node"],
        )

        if hitl_flag:
            workflow.add_conditional_edges(
                "interrupt_node",
                interrupt_node_decision,
                ["executor_agent_node", "feedback_collector"],
            )
            workflow.add_edge("feedback_collector", "replanner_agent")
            workflow.add_edge("replanner_agent", "interrupt_node")

        workflow.add_conditional_edges(
            "executor_agent_node",
            final_decision,
            ["interrupt_node_for_tool", "increment_step","final_response"],
        )
        workflow.add_conditional_edges(
            "interrupt_node_for_tool",
            interrupt_node_decision_for_tool,
            ["executor_agent_node", "tool_interrupt"],
        )
        workflow.add_conditional_edges(
            "tool_interrupt",
            final_decision,
            ["interrupt_node_for_tool", "increment_step","final_response"],
        )

        workflow.add_conditional_edges(
            "increment_step",
            check_plan_execution_status,
            ["executor_agent_node", "response_generator_agent"],
        )
        workflow.add_edge("response_generator_agent", "critic_agent")
        workflow.add_conditional_edges(
            "critic_agent",
            critic_decision,
            ["final_response", "critic_based_planner_agent"],
        )
        workflow.add_edge("critic_based_planner_agent", "executor_agent_node")
        workflow.add_edge("general_llm_call", "final_response")
        workflow.add_edge("final_response", END)

        log.info("Planner, Executor, Critic Agent built successfully")
        return workflow



