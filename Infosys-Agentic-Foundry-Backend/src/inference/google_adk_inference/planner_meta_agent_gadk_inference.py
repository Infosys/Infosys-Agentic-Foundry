# © 2024-25 Infosys Limited, Bangalore, India. All Rights Reserved.
from typing import Dict, List, Optional
from google.adk.agents import BaseAgent, LlmAgent, SequentialAgent, LoopAgent
from google.adk.models.lite_llm import LiteLlm

from src.inference.inference_utils import InferenceUtils
from src.inference.google_adk_inference.base_meta_type_agent_gadk_inference import BaseMetaTypeAgentGADKInference
from src.schemas import PlanSchema, ResponseSchema, AdminConfigLimits
from src.config.constants import Limits

from telemetry_wrapper import logger as log



class PlannerMetaAgentGADKInference(BaseMetaTypeAgentGADKInference):
    """
    Inference class for Planner Meta Agent using Google ADK.
    
    This agent type combines:
    1. A Planner agent that generates a plan based on the user query
    2. A Meta/Supervisor agent that delegates execution to worker sub-agents
    3. A Response Generator agent that synthesizes the final response
    
    Workflow:
    1. Planner generates a plan (list of steps) based on the user query
    2. If plan is empty, the response generator responds directly
    3. If plan exists and plan_verifier_flag is enabled, user approval is requested
    4. Supervisor/Executor iterates through plan steps, delegating to worker agents
    5. Response generator synthesizes all step outputs into final response
    """

    def __init__(self, inference_utils: InferenceUtils):
        super().__init__(inference_utils)


    async def _build_agent_and_chains(self, llm: LiteLlm, agent_config: dict, tool_interrupt_flag: bool = False, tools_to_interrupt: Optional[List[str]] = None) -> dict:
        """
        Builds the agent and its associated chains based on the provided configuration.
        
        This creates:
        - planner_agent: Generates the execution plan
        - replanner_agent: Regenerates plan based on user feedback
        - meta_supervisor_executor: Supervisor that delegates to worker agents
        - response_gen_agent: Synthesizes final response from step outputs or provide direct answer if no plan was generated.
        """
        worker_agent_ids = agent_config["TOOLS_INFO"]
        worker_agents_as_tools = await self._get_agents_as_tool_list(llm=llm, worker_agent_ids=worker_agent_ids)
        memory_management_tools = await self._get_memory_management_tools_instances(allow_union_annotation=False)
        agent_name = await self.agent_service.agent_service_utils._normalize_agent_name(agent_name=agent_config["AGENT_NAME"])
        
        log.info(f"Building Planner Meta Agent and chains for agent: {agent_name}")
        description = agent_config.get("AGENT_DESCRIPTION", "")
        system_prompt: Dict[str, str] = agent_config["SYSTEM_PROMPT"]

        log.info("Customizing system prompts for Planner Meta Agent.")

        # System Prompts
        planner_system_prompt = system_prompt.get("SYSTEM_PROMPT_META_AGENT_PLANNER", "").replace("```json", "").replace("```", "")
        supervisor_system_prompt = system_prompt.get("SYSTEM_PROMPT_META_AGENT_SUPERVISOR", "")
        response_generator_system_prompt = system_prompt.get("SYSTEM_PROMPT_META_AGENT_RESPONDER", "")

        log.info("Enhancing system prompts with additional instructions.")

        tool_interrupt_interpretation_prompt = ""
        tool_calling_llm = llm
        tool_interrupt_flag = tool_interrupt_flag and bool(worker_agents_as_tools)
        if tool_interrupt_flag:
            tool_interrupt_interpretation_prompt = await self.get_tool_interrupt_interpretation_prompt()
            tool_calling_llm = await self.add_additional_args_to_litellm_object(llm=llm, parallel_tool_calls=False)

        # Enhanced Planner Instructions
        planner_system_prompt = f"""\
{planner_system_prompt}

**IMPORTANT**: You are the planner for a multi-agent system. Generate a plan ONLY when the user query requires tool/worker agent execution. Return an empty plan list for simple queries.

**Note**:
- If the user asks about the agent's capabilities, role, or general information, return an empty list (no plan needed).
- Each step should be a clear, actionable instruction that can be delegated to a worker agent.
- *Do not* wrap the response in any markdown or code block or json.
- If no plan can be generated, return:
    {{
        "plan": []
    }}

{{episodic_memory_context?}}
"""

        # Enhanced Re-Planner Instructions
        replanner_system_prompt = f"""\
{planner_system_prompt}

**Note**:
- *Do not* wrap the response in any markdown or code block or json.
- Update or revise the current plan according to the user's feedback correctly.
- Each step should be a clear, actionable instruction that can be delegated to a worker agent.
- If no plan can be generated, return:
    {{
        "plan": []
    }}

**Important**: Your current task is to revise the existing plan based on the feedback, feedback is provided below.
"""

        user_feedback_state_key = "\n**User Feedback**:\n{plan_feedback?}"
        quality_assessment_feedback_state_key = "\n**Quality Assessment Feedback (if any)**:\n{quality_assessment_feedback?}"

        # Enhanced Supervisor/Executor Instructions
        supervisor_system_prompt = f"""\
{supervisor_system_prompt}

**Important Guidelines**: 
- You are the supervisor agent responsible for delegating tasks to worker sub-agents.
- Focus solely on executing the current step of the provided plan.
- Choose the most appropriate worker agent for each step.
{tool_interrupt_interpretation_prompt}

**CURRENT STEP: ** {{current_step?}}
"""

        # Enhanced Response Generator Instructions
        response_generator_system_prompt = f"""\
{response_generator_system_prompt}

**Note**:
- Synthesize the results from all executed steps into a comprehensive response if plan was executed else present the final answer as if you directly answered the user's query.
- *Do not* wrap the response in any markdown or code block or json.
- **Important**: The user may request to update the plan or modify tool call arguments as part of a human-in-the-loop process. In such cases, the latest update from the user should have the highest priority. Generate the final response based on the latest updates made by the user, even if it deviates from the initial query. Always consider the most recent user modifications when forming the response.
"""


        log.info("Creating Planner Meta Agent instances.")

        # Agents
        planner_agent = LlmAgent(
            name=f"planner_for_{agent_name}",
            model=llm,
            instruction=planner_system_prompt,
            tools=worker_agents_as_tools,
            output_schema=PlanSchema,
            after_agent_callback=await self.get_after_planner_agent_callback(),
            output_key="plan"
        )

        replanner_agent = LlmAgent(
            name=f"replanner_for_{agent_name}",
            model=llm,
            instruction=replanner_system_prompt + user_feedback_state_key,
            tools=worker_agents_as_tools,
            output_schema=PlanSchema,
            after_agent_callback=await self.get_after_planner_agent_callback(),
            output_key="plan"
        )

        # Separate replanner agent for evaluation loop (ADK doesn't allow same agent in multiple parents)
        evaluation_replanner_agent = LlmAgent(
            name=f"evaluation_replanner_for_{agent_name}",
            model=llm,
            instruction=replanner_system_prompt + quality_assessment_feedback_state_key,
            tools=worker_agents_as_tools,
            output_schema=PlanSchema,
            after_agent_callback=await self.get_after_planner_agent_callback(),
            output_key="plan"
        )

        # Meta Supervisor Executor - uses worker agents as tools
        meta_supervisor_executor = LlmAgent(
            name=f"supervisor_for_{agent_name}",
            model=tool_calling_llm,
            instruction=supervisor_system_prompt,
            tools=worker_agents_as_tools + memory_management_tools,
            before_agent_callback=await self.get_before_executor_agent_callback(),
            before_tool_callback=await self.get_before_tool_callback_for_tool_interrupt(tool_verifier_flag=tool_interrupt_flag, tools_to_interrupt=tools_to_interrupt),
            after_tool_callback=await self.get_after_tool_callback_for_tool_interrupt(tool_verifier_flag=tool_interrupt_flag)
        )

        response_gen_agent = LlmAgent(
            name=f"response_generator_for_{agent_name}",
            model=llm,
            instruction=response_generator_system_prompt,
            tools=worker_agents_as_tools,
            output_schema=ResponseSchema,
            output_key="response"
        )

        chains = {
            "llm": llm,

            "planner_agent": planner_agent,
            "replanner_agent": replanner_agent,
            "evaluation_replanner_agent": evaluation_replanner_agent,

            "meta_supervisor_executor": meta_supervisor_executor,
            "response_gen_agent": response_gen_agent,

            "tools": worker_agents_as_tools,
            "agent_name": agent_name,
            "description": description
        }
        return chains

    async def _build_workflow(self, chains: dict, flags: Dict[str, bool] = {}) -> BaseAgent:
        """
        Builds the workflow for the Planner Meta Agent.
        
        Workflow options:
        1. Basic (quality assessment OFF): Planner -> Supervisor Executor Loop -> Response Generator
        2. With Quality Assessment (evaluation and/or validation ON): Planner -> Supervisor-Quality Loop (with replanner for improvement)
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

        llm = chains.get("llm", None)

        planner_agent = chains.get("planner_agent", None)
        replanner_agent = chains.get("replanner_agent", None)
        evaluation_replanner_agent = chains.get("evaluation_replanner_agent", None)

        meta_supervisor_executor = chains.get("meta_supervisor_executor", None)        
        response_gen_agent = chains.get("response_gen_agent", None)

        if not all([planner_agent, replanner_agent, meta_supervisor_executor, response_gen_agent, llm]):
            log.error("One or more required agents are missing to build the workflow.")
            raise ValueError("One or more required agents are missing to build the workflow.")

        log.info(f"Building workflow for Planner Meta Agent. Evaluation enabled: {evaluation_flag}, Validation enabled: {validator_flag}")

        # Supervisor Executor loop: iterates through each step of the plan
        supervisor_executor_loop = LoopAgent(
            name=f"loop_supervisor_for_{agent_name}",
            sub_agents=[meta_supervisor_executor],
            before_agent_callback=await self.get_before_executor_loop_agent_callback()
        )

        # Determine if quality assessment is enabled
        quality_assessment_enabled = evaluation_flag or validator_flag

        # Build execution sequence based on quality assessment flags
        # When quality_assessment_enabled is True: Use quality assessment with evaluation_replanner_agent for improvement
        # When quality_assessment_enabled is False: Use simple supervisor -> response sequence
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
            
            # Supervisor loop with quality assessment
            # Flow: supervisor_executor_loop -> response_gen_agent -> quality_assessment_agent -> evaluation_replanner_agent (on failure)
            # Note: Using evaluation_replanner_agent (not replanner_agent) because ADK doesn't allow same agent in multiple parents
            supervisor_quality_loop = LoopAgent(
                name=f"supervisor_quality_loop_for_{agent_name}",
                sub_agents=[supervisor_executor_loop, response_gen_agent, *quality_assessment_agents, evaluation_replanner_agent],
                max_iterations=Limits.MAX_CONFIGURABLE_EPOCHS,  # Max improvement cycles
                before_agent_callback=await self.get_before_agent_callback_for_quality_loop()
            )
            log.info("Created supervisor-quality loop with evaluation_replanner_agent for improvement iterations.")
            execution_sequence = supervisor_quality_loop
        else:
            # Sequential agent: supervisor loop followed by response generation (no quality assessment)
            # Flow: supervisor_executor_loop -> response_gen_agent
            supervisor_response_sequence = SequentialAgent(
                name=f"supervisor_response_sequence_for_{agent_name}",
                sub_agents=[supervisor_executor_loop, response_gen_agent]
            )
            log.info("Created supervisor-response sequence without quality assessment.")
            execution_sequence = supervisor_response_sequence

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
        # 3. Execution sequence (supervisor loop + response gen, or supervisor-quality loop with replanner)
        root_agent_sub_agents: List[BaseAgent] = [planner_agent, replanner_loop_agent, execution_sequence]
        if response_formatting_flag:
            formatter_for_canvas_view_agent = await self.get_canvas_formatter_agent(llm=llm)
            root_agent_sub_agents.append(formatter_for_canvas_view_agent)

        root_agent = SequentialAgent(
            name=agent_name,
            sub_agents=root_agent_sub_agents
        )

        return root_agent


