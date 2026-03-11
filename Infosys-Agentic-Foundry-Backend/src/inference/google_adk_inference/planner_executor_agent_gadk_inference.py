# © 2024-25 Infosys Limited, Bangalore, India. All Rights Reserved.
from typing import Dict, Callable, List, Optional
from google.adk.agents import BaseAgent, LlmAgent, SequentialAgent, LoopAgent
from google.adk.models.lite_llm import LiteLlm
from google.adk.sessions.state import State

from .gadk_router_agent import RouterAgent


from src.inference.inference_utils import InferenceUtils
from src.inference.google_adk_inference.base_agent_gadk_inference import BaseAgentGADKInference
from src.schemas import PlanSchema, ResponseSchema, AdminConfigLimits
from src.config.constants import Limits

from telemetry_wrapper import logger as log



class PlannerExecutorAgentGADKInference(BaseAgentGADKInference):
    """
    Inference class for Planner-Executor Agent using Google ADK.
    Implements methods to build agents, chains, and workflows specific to the Planner-Executor architecture.
    This is a simplified version without the Critic component.
    """

    def __init__(self, inference_utils: InferenceUtils):
        super().__init__(inference_utils)


    async def _build_agent_and_chains(self, llm: LiteLlm, agent_config: dict, tool_interrupt_flag: bool = False, tools_to_interrupt: Optional[List[str]] = None) -> dict:
        """
        Builds the agent and its associated chains based on the provided configuration.
        """
        tools = await self._get_tools_instances(tool_ids=agent_config["TOOLS_INFO"] or [])
        memory_management_tools = await self._get_memory_management_tools_instances(allow_union_annotation=False)
        agent_name = await self.agent_service.agent_service_utils._normalize_agent_name(agent_name=agent_config["AGENT_NAME"])
        log.info(f"Building Planner-Executor Agent and chains for agent: {agent_name}")
        description = agent_config["AGENT_DESCRIPTION"]
        system_prompt: Dict[str, str] = agent_config["SYSTEM_PROMPT"]

        log.info("Customizing system prompts for Planner-Executor Agent.")

        # System Prompts
        planner_system_prompt = system_prompt.get("SYSTEM_PROMPT_PLANNER_AGENT", "").replace("```json", "").replace("```", "")
        replanner_system_prompt = system_prompt.get("SYSTEM_PROMPT_REPLANNER_AGENT", "").replace("```json", "").replace("```", "")

        executor_system_prompt = system_prompt.get("SYSTEM_PROMPT_EXECUTOR_AGENT", "")
        general_query_system_prompt = system_prompt.get("SYSTEM_PROMPT_GENERAL_LLM", "")

        response_generator_system_prompt = system_prompt.get("SYSTEM_PROMPT_RESPONSE_GENERATOR_AGENT", "")

        log.info("Enhancing system prompts with additional instructions.")

        tool_interrupt_interpretation_prompt = ""
        tool_calling_llm = llm
        tool_interrupt_flag = tool_interrupt_flag and bool(tools)
        if tool_interrupt_flag:
            tool_interrupt_interpretation_prompt = await self.get_tool_interrupt_interpretation_prompt()
            tool_calling_llm = await self.add_additional_args_to_litellm_object(llm=llm, parallel_tool_calls=False)

        # Addition Instructions
        planner_system_prompt = f"""\
{planner_system_prompt}

**IMPORTANT**: You are just a sub agent of a multi agent workflow so you don't have to generate plan if tool calls are not required to answer the query, so in this case, you can return an empty list as a plan, This is **Very Important** as your response decides the next sub agent that will take over, so when plan is an empty list the general query handler will take over and answer else if the plan is generate the tool caller workflow agents will take over so keep this in mind that **no tool call required means empty list of plan**.

**Note**:
- If the user asks for the agent's goal, agent's role, workflow description, agent's domain, and tools it has access to, do not generate any plan, instead return empty list as plan and let general query handler take over.
- If the user query can be solved using the tools, generate a plan for the agent to follow.
- *Do not* generate plan if they query requires the tool that you do not have.
- *Do not* wrap the response in any markdown or code block or json.
- Generate plan *if and only if** the tool calls are required to answer the query else response with an empty list.
- *Do not* generate plan if tool call is not required to answer the query.
- If no plan can be generated, return:
    {{
        "plan": []
    }}

{{episodic_memory_context?}}
"""

        replanner_system_prompt = f"""\
{replanner_system_prompt}

**Note**:
- *Do not* wrap the response in any markdown or code block or json.
- Update or revise the current plan according to the feedback correctly.
- If you are not able to come up with a plan or input query is greetings, just return empty list:
    {{
        "plan": []
    }}
"""

        user_feedback_state_key = "\n**User Feedback**:\n{plan_feedback?}"
        quality_assessment_feedback_state_key = "\n**Quality Assessment Feedback (if any)**:\n{quality_assessment_feedback?}"

        executor_system_prompt = f"""\
{executor_system_prompt}

**Important Guidelines**:
- Focus solely on executing the current step of the provided plan.
{tool_interrupt_interpretation_prompt}

**CURRENT STEP: ** {{current_step?}}
"""

        general_query_system_prompt = f"""\
{general_query_system_prompt}

NOTE:
- You have to respond when **NO PLAN** is generated, which means it was a general query and you have to answer it, planner agent will play no part in it.
- Give response like the query was suppose to be answered by you directly without any plan.
- Remember: From users perspective all this multi agent system is just a single agent, they asked a query and you would give a response, without any reference to planning or other agent actions done internally.
"""

        response_generator_system_prompt = f"""\
{response_generator_system_prompt}

**Note**:
- *Do not* wrap the response json which is having 'response' key in it, with ```json ... ``` or any other block or wrapper.
- The above given json block wrapper for the response is just for your understanding of the output format, but the final content should not include these wrappers.
- *Do not* wrap the response in any markdown or code block or json.
- **Important**: The user may request to update the plan or modify tool call arguments as part of a human-in-the-loop process. In such cases, the latest update from the user should have the highest priority. Generate the final response based on the latest updates made by the user, even if it deviates from the initial query. Always consider the most recent user modifications when forming the response.
"""


        log.info("Creating Planner-Executor Agent instances.")

        # Agents
        planner_agent = LlmAgent(
            name=f"planner_for_{agent_name}",
            model=llm,
            instruction=planner_system_prompt,
            tools=tools,
            output_schema=PlanSchema,
            after_agent_callback=await self.get_after_planner_agent_callback(),
            output_key="plan"
        )

        replanner_agent = LlmAgent(
            name=f"replanner_for_{agent_name}",
            model=llm,
            instruction=replanner_system_prompt + user_feedback_state_key,
            tools=tools,
            output_schema=PlanSchema,
            after_agent_callback=await self.get_after_planner_agent_callback(),
            output_key="plan"
        )

        # Separate replanner agent for evaluation loop (ADK doesn't allow same agent in multiple parents)
        evaluation_replanner_agent = LlmAgent(
            name=f"evaluation_replanner_for_{agent_name}",
            model=llm,
            instruction=replanner_system_prompt + quality_assessment_feedback_state_key,
            tools=tools,
            output_schema=PlanSchema,
            after_agent_callback=await self.get_after_planner_agent_callback(),
            output_key="plan"
        )

        general_query_handler = LlmAgent(
            name=f"general_query_handler_for_{agent_name}",
            model=llm,
            instruction=general_query_system_prompt,
            tools=tools,
            output_schema=ResponseSchema,
            output_key="response"
        )

        executor_agent = LlmAgent(
            name=f"executor_for_{agent_name}",
            model=tool_calling_llm,
            instruction=executor_system_prompt,
            tools=tools + memory_management_tools,
            before_agent_callback=await self.get_before_executor_agent_callback(),
            before_tool_callback=await self.get_before_tool_callback_for_tool_interrupt(tool_verifier_flag=tool_interrupt_flag, tools_to_interrupt=tools_to_interrupt),
            after_tool_callback=await self.get_after_tool_callback_for_tool_interrupt(tool_verifier_flag=tool_interrupt_flag)
        )

        response_gen_agent = LlmAgent(
            name=f"response_generator_for_{agent_name}",
            model=llm,
            instruction=response_generator_system_prompt,
            tools=tools,
            output_schema=ResponseSchema,
            output_key="response"
        )


        chains = {
            "llm": llm,

            "planner_agent": planner_agent,
            "replanner_agent": replanner_agent,
            "evaluation_replanner_agent": evaluation_replanner_agent,

            "executor_agent": executor_agent,
            "general_query_handler": general_query_handler,

            "response_gen_agent": response_gen_agent,

            "tools": tools,
            "agent_name": agent_name,
            "description": description
        }
        return chains

    @staticmethod
    def get_general_query_router_decision_function(agent_name: str, quality_assessment_enabled: bool = False) -> Callable:
        """
        Returns a decision function for routing between general query handler and execution loop.
        If a plan exists in the state, routes to the appropriate execution loop based on quality assessment flags;
        otherwise, routes to the general query handler.
        
        Args:
            agent_name: Name of the agent
            quality_assessment_enabled: If True, routes to executor_quality_loop; if False, routes to executor_response_sequence
        """
        def _general_router_decision_function(state: State) -> str:
            if state.get("plan", []):
                if quality_assessment_enabled:
                    return f"executor_quality_loop_for_{agent_name}"
                return f"executor_response_sequence_for_{agent_name}"
            return f"general_query_handler_for_{agent_name}"
        return _general_router_decision_function

    async def _build_workflow(self, chains: dict, flags: Dict[str, bool] = {}) -> BaseAgent:
        """
        Builds the workflow for the Planner-Executor agent.
        
        Workflow options:
        1. Basic (quality assessment OFF): Planner -> Executor Loop -> Response Generator
        2. With Quality Assessment (evaluation and/or validation ON): Planner -> Executor-Quality Loop (with replanner for improvement)
        3. With Formatting: Adds canvas formatter at the end
        """
        tool_interrupt_flag = flags.get("tool_interrupt_flag", False)
        plan_verifier_flag = flags.get("plan_verifier_flag", False)
        response_formatting_flag = flags.get("response_formatting_flag", False)
        evaluation_flag = flags.get("evaluation_flag", False)
        validator_flag = flags.get("validator_flag", False)

        inference_config: AdminConfigLimits = flags.get("inference_config", AdminConfigLimits())

        agent_name = chains.get("agent_name", None)
        description = chains.get("description", "")
        validation_criteria = chains.get("validation_criteria", [])
        tools = chains.get("tools", [])

        llm = chains.get("llm", None)

        planner_agent = chains.get("planner_agent", None)
        replanner_agent = chains.get("replanner_agent", None)
        evaluation_replanner_agent = chains.get("evaluation_replanner_agent", None)

        executor_agent = chains.get("executor_agent", None)
        general_query_handler = chains.get("general_query_handler", None)

        response_gen_agent = chains.get("response_gen_agent", None)

        if not all([planner_agent, replanner_agent, executor_agent, response_gen_agent, general_query_handler, llm]):
            log.error("One or more required agents are missing to build the workflow.")
            raise ValueError("One or more required agents are missing to build the workflow.")

        log.info(f"Building workflow for Planner-Executor Agent. Evaluation enabled: {evaluation_flag}, Validation enabled: {validator_flag}")

        # Executor loop: iterates through each step of the plan
        executor_loop_agent = LoopAgent(
            name=f"loop_executor_for_{agent_name}",
            sub_agents=[executor_agent],
            before_agent_callback=await self.get_before_executor_loop_agent_callback()
        )

        # Determine if quality assessment is enabled
        quality_assessment_enabled = evaluation_flag or validator_flag

        # Build execution loop based on quality assessment flags
        # When quality_assessment_enabled is True: Use quality assessment agent with evaluation_replanner_agent for improvement
        # When quality_assessment_enabled is False: Use simple executor -> response sequence
        if quality_assessment_enabled:
            quality_assessment_agents = await self.get_quality_assessment_agent(
                llm=llm,
                agent_name=agent_name,
                evaluation_flag=evaluation_flag,
                validator_flag=validator_flag,
                validation_criteria=validation_criteria,
                description=description,
                inference_config=inference_config
            )
            
            if not evaluation_replanner_agent:
                log.error("Evaluation replanner agent is required when quality assessment is enabled.")
                raise ValueError("Evaluation replanner agent is required when quality assessment is enabled.")
            
            # Executor loop with quality assessment
            # Flow: executor_loop_agent -> response_gen_agent -> quality_assessment_agent -> evaluation_replanner_agent (on failure)
            # Note: Using evaluation_replanner_agent (not replanner_agent) because ADK doesn't allow same agent in multiple parents
            executor_quality_loop = LoopAgent(
                name=f"executor_quality_loop_for_{agent_name}",
                sub_agents=[executor_loop_agent, response_gen_agent, *quality_assessment_agents, evaluation_replanner_agent],
                max_iterations=Limits.MAX_CONFIGURABLE_EPOCHS,  # Max improvement cycles
                before_agent_callback=await self.get_before_agent_callback_for_quality_loop()
            )
            log.info("Created executor-quality loop with evaluation_replanner_agent for improvement iterations.")
            execution_loop = executor_quality_loop
        else:
            # Sequential agent: executor loop followed by response generation (no quality assessment)
            # Flow: executor_loop_agent -> response_gen_agent
            executor_response_sequence = SequentialAgent(
                name=f"executor_response_sequence_for_{agent_name}",
                sub_agents=[executor_loop_agent, response_gen_agent]
            )
            log.info("Created executor-response sequence without quality assessment.")
            execution_loop = executor_response_sequence

        # Router agent: routes to general handler or executor sequence based on plan
        general_router_agent = RouterAgent(
            name=f"general_router_for_{agent_name}",
            sub_agents=[general_query_handler, execution_loop],
            route_sub_agent_decision_function=self.get_general_query_router_decision_function(agent_name=agent_name, quality_assessment_enabled=quality_assessment_enabled)
        )

        plan_verifier_agent = await self.get_plan_verifier_agent(llm=llm, agent_name=agent_name, plan_verifier_flag=plan_verifier_flag)
        # Replanner loop: handles plan verification and replanning based on user feedback
        replanner_loop_agent = LoopAgent(
            name=f"loop_replanner_for_{agent_name}",
            sub_agents=[plan_verifier_agent, replanner_agent],
            max_iterations=20,
            after_agent_callback=await self.get_after_planner_agent_callback()
        )

        # Root agent: the main sequential workflow
        # 1. Planner generates initial plan
        # 2. Replanner loop handles user approval/feedback
        # 3. Router decides between general handler or executor sequence
        root_agent_sub_agents = [planner_agent, replanner_loop_agent, general_router_agent]
        if response_formatting_flag:
            formatter_for_canvas_view_agent = await self.get_canvas_formatter_agent(llm=llm)
            root_agent_sub_agents.append(formatter_for_canvas_view_agent)

        root_agent = SequentialAgent(
            name=agent_name,
            sub_agents=root_agent_sub_agents
        )

        return root_agent
