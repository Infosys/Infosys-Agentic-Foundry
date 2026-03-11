# © 2024-25 Infosys Limited, Bangalore, India. All Rights Reserved.
from typing import Dict, List, Optional
from google.adk.agents import BaseAgent, LlmAgent, SequentialAgent, LoopAgent
from google.adk.models.lite_llm import LiteLlm

from src.inference.inference_utils import InferenceUtils
from src.inference.google_adk_inference.base_agent_gadk_inference import BaseAgentGADKInference
from src.schemas import CriticSchema, AdminConfigLimits
from src.config.constants import Limits

from telemetry_wrapper import logger as log



class ReactCriticAgentGADKInference(BaseAgentGADKInference):
    """
    Inference class for React-Critic Agent using Google ADK.
    Implements methods to build agents, chains, and workflows specific to the React-Critic architecture.
    This is a React agent with a Critic loop for response quality evaluation, without the Planner component.
    
    Workflow:
    1. Executor agent processes the query and uses tools
    2. Critic evaluates the response quality
    3. If quality is low (score < 0.7), loop back to executor with critique feedback
    4. Loop continues until quality threshold is met or max iterations (2) reached
    """

    def __init__(self, inference_utils: InferenceUtils):
        super().__init__(inference_utils)


    async def _build_agent_and_chains(self, llm: LiteLlm, agent_config: dict, tool_interrupt_flag: bool = False, tools_to_interrupt: Optional[List[str]] = None) -> dict:
        """
        Builds the agent and its associated chains based on the provided configuration.
        Uses only SYSTEM_PROMPT_EXECUTOR_AGENT and SYSTEM_PROMPT_CRITIC_AGENT.
        """
        tools = await self._get_tools_instances(tool_ids=agent_config["TOOLS_INFO"] or [])
        memory_management_tools = await self._get_memory_management_tools_instances(allow_union_annotation=False)
        agent_name = await self.agent_service.agent_service_utils._normalize_agent_name(agent_name=agent_config["AGENT_NAME"])
        log.info(f"Building React-Critic Agent and chains for agent: {agent_name}")
        description = agent_config["AGENT_DESCRIPTION"]
        system_prompt: Dict[str, str] = agent_config["SYSTEM_PROMPT"]

        inference_config: AdminConfigLimits = agent_config.get("inference_config", AdminConfigLimits())

        log.info("Customizing system prompts for React-Critic Agent.")

        # System Prompts - Use only SYSTEM_PROMPT_EXECUTOR_AGENT and SYSTEM_PROMPT_CRITIC_AGENT
        executor_system_prompt = system_prompt.get("SYSTEM_PROMPT_EXECUTOR_AGENT", "")
        critic_system_prompt = system_prompt.get("SYSTEM_PROMPT_CRITIC_AGENT", "").replace("```json", "").replace("```", "")

        log.info("Enhancing system prompts with additional instructions.")

        tool_interrupt_interpretation_prompt = ""
        tool_calling_llm = llm
        tool_interrupt_flag = tool_interrupt_flag and bool(tools)
        if tool_interrupt_flag:
            tool_interrupt_interpretation_prompt = await self.get_tool_interrupt_interpretation_prompt()
            tool_calling_llm = await self.add_additional_args_to_litellm_object(llm=llm, parallel_tool_calls=False)

        # Enhanced Executor Agent Instructions
        # Include both critic_response and evaluation_feedback placeholders
        # - critic_response is used when evaluation is OFF (critic loop active)
        # - evaluation_feedback is used when evaluation is ON (evaluator loop active)
        executor_system_prompt = f"""\
{executor_system_prompt}

**Important Guidelines**:
- You are the main reasoning and action agent in this workflow.
- Analyze the user's query and use the available tools to gather information or perform actions.
- If the query is a general question that doesn't require tools, respond directly.
- Focus on providing accurate and helpful responses.
{tool_interrupt_interpretation_prompt}
- If you receive feedback, address each feedback point specifically and improve your response.

**Critique Feedback (if any)**:
{{critic_response?}}

{{episodic_memory_context?}}

**Quality Assessment Feedback (if any)**:
{{quality_assessment_feedback?}}
"""

        # Enhanced Critic Agent Instructions
        critic_system_prompt = f"""\
{critic_system_prompt}

**Important Guidelines**:
- **Note**: *Human-in-the-Loop Intervention (Highest Priority)* - During the agent's execution, the user may intervene and modify the workflow. These interventions represent explicit human guidance and **MUST be treated with the highest preference** when evaluating the response:
    1. **Updated Tool Call Arguments**: The user may modify or correct the arguments passed to tool calls. When this happens, the agent's response should be evaluated based on how well it aligns with the **updated arguments**, not the original query alone.
    2. **Plan Feedback or Updated Plans**: For agents with a planner component, the user may provide feedback on the proposed plan or directly update the plan steps. The agent's response should be evaluated based on how well it follows the **user-modified plan**.
    3. **Divergence from Initial Query**: User interventions may cause the agent's execution path to diverge from the initial query's direct interpretation. This is **expected and acceptable** — evaluate the response based on the **final intent** shaped by user interventions, not solely the original query.

    **Rule**: If user interventions are present, prioritize alignment with the user's modifications over strict adherence to the initial query, even if it appears to deviate from the original query.

- *Do not* wrap the response in any markdown or code block or json.
"""

        log.info("Creating React-Critic Agent instances.")

        # Agents - Executor, Critic (for evaluation OFF), and Evaluator (for evaluation ON)
        executor_agent = LlmAgent(
            name=f"executor_for_{agent_name}",
            model=tool_calling_llm,
            description=description,
            instruction=executor_system_prompt,
            tools=tools + memory_management_tools,
            output_key="response",
            before_tool_callback=await self.get_before_tool_callback_for_tool_interrupt(tool_verifier_flag=tool_interrupt_flag, tools_to_interrupt=tools_to_interrupt),
            after_tool_callback=await self.get_after_tool_callback_for_tool_interrupt(tool_verifier_flag=tool_interrupt_flag)
        )

        # Critic agent - used when evaluation is OFF
        critic_agent = LlmAgent(
            name=f"critic_for_{agent_name}",
            model=llm,
            instruction=critic_system_prompt,
            tools=tools,
            output_schema=CriticSchema,
            output_key="critic_response",
            after_tool_callback=await self.get_after_critics_tool_callback(inference_config=inference_config)
        )

        chains = {
            "llm": llm,

            "executor_agent": executor_agent,
            "critic_agent": critic_agent,

            "tools": tools,
            "agent_name": agent_name,
            "description": description,
        }
        return chains

    async def _build_workflow(self, chains: dict, flags: Dict[str, bool] = {}) -> BaseAgent:
        """
        Builds the workflow for the React-Critic agent.
        
        Workflow options:
        - Quality Assessment OFF: Executor -> Critic loop
        - Quality Assessment ON (evaluation and/or validation): Executor -> Quality Assessment loop- critic is skipped
        """
        tool_interrupt_flag = flags.get("tool_interrupt_flag", False)
        response_formatting_flag = flags.get("response_formatting_flag", False)
        evaluation_flag = flags.get("evaluation_flag", False)
        validator_flag = flags.get("validator_flag", False)

        inference_config: AdminConfigLimits = flags.get("inference_config", AdminConfigLimits())

        agent_name = chains.get("agent_name", None)
        description = chains.get("description", "")
        validation_criteria = chains.get("validation_criteria", [])
        tools = chains.get("tools", [])

        llm = chains.get("llm", None)

        executor_agent = chains.get("executor_agent", None)
        critic_agent = chains.get("critic_agent", None)

        if not all([executor_agent, llm]):
            log.error("Required agents are missing to build the workflow.")
            raise ValueError("Required agents are missing to build the workflow.")
        
        log.info(f"Building workflow for React-Critic Agent. Evaluation enabled: {evaluation_flag}, Validation enabled: {validator_flag}")

        # Build the core workflow based on evaluation/validation flags
        if evaluation_flag or validator_flag:
            # Quality Assessment ON: Use Executor -> Quality Assessment loop (skip critic)
            quality_assessment_agents = await self.get_quality_assessment_agent(
                llm=llm,
                agent_name=agent_name,
                evaluation_flag=evaluation_flag,
                validator_flag=validator_flag,
                validation_criteria=validation_criteria,
                description=description,
                inference_config=inference_config
            )

            # React-Quality Assessment Loop:
            # 1. Executor agent processes the query and generates response
            # 2. Quality assessment agent(s) evaluate the response
            # 3. If scores < threshold and attempts < max, loop back with feedback
            # 4. Loop continues until quality threshold is met or max iterations (3) reached
            core_loop = LoopAgent(
                name=f"react_quality_loop_for_{agent_name}",
                sub_agents=[executor_agent, *quality_assessment_agents],
                max_iterations=Limits.MAX_CONFIGURABLE_EPOCHS,  # Max quality assessment attempts
                before_agent_callback=await self.get_before_agent_callback_for_quality_loop()
            )
            log.info("React-Quality Assessment loop workflow created (critic skipped).")
        else:
            # Quality Assessment OFF: Use Executor -> Critic loop
            if not critic_agent:
                log.error("Critic agent is required when quality assessment flags are disabled.")
                raise ValueError("Critic agent is required when quality assessment flags are disabled.")
            
            # React-Critic Loop:
            # 1. Executor agent processes the query and uses tools
            # 2. Critic evaluates the response quality
            # 3. If quality is low, loop back to executor with critique feedback
            # 4. Loop continues until quality threshold is met or max iterations reached
            core_loop = LoopAgent(
                name=f"react_critic_loop_for_{agent_name}",
                sub_agents=[executor_agent, critic_agent],
                max_iterations=inference_config.max_critic_epochs,  # Allow up to max_critic_epochs iterations for improvement
                after_agent_callback=await self.get_after_critic_loop_agent_callback()
            )
            log.info("React-Critic loop workflow created.")

        # Add canvas formatter if response_formatting_flag is enabled
        root_agent_sub_agents: List[BaseAgent] = [core_loop]
        
        if response_formatting_flag:
            formatter_for_canvas_view_agent = await self.get_canvas_formatter_agent(llm=llm)
            root_agent_sub_agents.append(formatter_for_canvas_view_agent)
            log.info("Canvas formatter agent added to workflow.")

        # Create final root agent
        root_agent = SequentialAgent(
            name=agent_name,
            sub_agents=root_agent_sub_agents
        )

        return root_agent
