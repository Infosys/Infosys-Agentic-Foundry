# © 2024-25 Infosys Limited, Bangalore, India. All Rights Reserved.
from typing import Dict, List, Optional, Any
from google.adk.agents import BaseAgent, LlmAgent, SequentialAgent, LoopAgent
from google.adk.models.lite_llm import LiteLlm


from src.inference.inference_utils import InferenceUtils
from src.inference.google_adk_inference.base_agent_gadk_inference import BaseAgentGADKInference
from src.schemas import AdminConfigLimits
from src.config.constants import Limits

from telemetry_wrapper import logger as log



class ReactAgentGADKInference(BaseAgentGADKInference):
    """
    Inference class for React Agent using Google ADK.
    Implements methods to build agents, chains, and workflows specific to the React architecture.
    
    Workflow (with evaluation/validation enabled):
    1. React agent processes the query and uses tools
    2. Quality assessment (evaluator and/or validator) evaluates the response
    3. If scores < threshold and attempts < max, loop back to react agent with feedback
    4. Loop continues until quality threshold is met or max iterations (3) reached
    """

    def __init__(self, inference_utils: InferenceUtils):
        super().__init__(inference_utils)


    async def _build_agent_and_chains(self, llm: LiteLlm, agent_config: dict, tool_interrupt_flag: bool = False, tools_to_interrupt: Optional[List[str]] = None) -> dict:
        """
        Builds the agent and chains for the React workflow.
        Includes evaluator agent when evaluation_flag is enabled.
        """
        tool_ids = agent_config["TOOLS_INFO"]
        tools = await self._get_tools_instances(tool_ids=tool_ids)
        memory_management_tools = await self._get_memory_management_tools_instances(allow_union_annotation=False)
        agent_name = await self.agent_service.agent_service_utils._normalize_agent_name(agent_name=agent_config["AGENT_NAME"])

        system_prompt = agent_config["SYSTEM_PROMPT"]
        description = agent_config.get("AGENT_DESCRIPTION", "")
        react_agent_system_prompt = system_prompt["SYSTEM_PROMPT_REACT_AGENT"]

        tool_interrupt_interpretation_prompt = ""
        tool_calling_llm = llm
        tool_interrupt_flag = tool_interrupt_flag and bool(tools)
        if tool_interrupt_flag:
            tool_interrupt_interpretation_prompt = await self.get_tool_interrupt_interpretation_prompt()
            tool_calling_llm = await self.add_additional_args_to_litellm_object(llm=llm, parallel_tool_calls=False)

        # Enhanced React Agent Instructions with evaluation feedback support
        react_agent_system_prompt = f"""\
{react_agent_system_prompt}

**Notes**:
{tool_interrupt_interpretation_prompt}
- If you receive evaluation feedback, address each feedback point specifically and improve your response.

{{episodic_memory_context?}}

**Quality Assessment Feedback (if any)**:
{{quality_assessment_feedback?}}
"""

        log.info("Creating React Agent instance.")
        react_agent = LlmAgent(
            name=f"executor_for_{agent_name}",
            model=tool_calling_llm,
            description=description,
            instruction=react_agent_system_prompt,
            tools=tools + memory_management_tools,
            output_key="response",
            before_tool_callback=await self.get_before_tool_callback_for_tool_interrupt(tool_verifier_flag=tool_interrupt_flag, tools_to_interrupt=tools_to_interrupt),
            after_tool_callback=await self.get_after_tool_callback_for_tool_interrupt(tool_verifier_flag=tool_interrupt_flag)
        )

        chains = {
            "llm": llm,
            "react_agent": react_agent,

            "tools": tools,
            "agent_name": agent_name,
            "description": description
        }
        return chains

    async def _build_workflow(self, chains: dict, flags: Dict[str, Any] = {}) -> BaseAgent:
        """
        Builds the workflow for the React agent.
        
        Workflow options:
        1. Basic: React Agent only
        2. With Evaluation/Validation: React Agent -> Quality Assessment Agent(s) (in loop for quality improvement)
        3. With Formatting: Adds canvas formatter at the end
        """
        tool_interrupt_flag = flags.get("tool_interrupt_flag", False)
        response_formatting_flag = flags.get("response_formatting_flag", False)
        evaluation_flag = flags.get("evaluation_flag", False)
        validator_flag = flags.get("validator_flag", False)

        inference_config: AdminConfigLimits = flags.get("inference_config", AdminConfigLimits())

        agent_name = chains.get("agent_name", None)
        description = chains.get("description", "")
        validation_criteria = chains.get("validation_criteria", [])

        llm = chains.get("llm", None)
        react_agent = chains.get("react_agent", None)

        if not react_agent:
            log.error("Required agent (react_agent) is missing.")
            raise ValueError("Required agent (react_agent) is missing.")

        log.info(f"Building workflow for React Agent. Evaluation enabled: {evaluation_flag}, Validation enabled: {validator_flag}")

        # Build the core workflow based on flags
        if evaluation_flag or validator_flag:
            # Quality Assessment Loop:
            # 1. React agent processes the query and generates response
            # 2. Quality assessment agent(s) evaluate the response
            # 3. If scores < threshold and attempts < max, loop back with feedback
            # 4. Loop continues until quality threshold is met or max iterations reached
            quality_assessment_agents = await self.get_quality_assessment_agent(
                llm=llm,
                agent_name=agent_name,
                evaluation_flag=evaluation_flag,
                validator_flag=validator_flag,
                validation_criteria=validation_criteria,
                description=description,
                inference_config=inference_config
            )

            react_quality_loop = LoopAgent(
                name=f"react_quality_loop_for_{agent_name}",
                sub_agents=[react_agent, *quality_assessment_agents],
                max_iterations=Limits.MAX_CONFIGURABLE_EPOCHS,  # Max quality assessment attempts
                before_agent_callback=await self.get_before_agent_callback_for_quality_loop()
            )
            core_workflow = react_quality_loop
            log.info("React-Quality Assessment loop workflow created.")
        else:
            # Simple React agent without quality assessment
            core_workflow = react_agent
            log.info("Basic React agent workflow created (no quality assessment).")

        # Add canvas formatter if response_formatting_flag is enabled
        root_agent_sub_agents: List[BaseAgent] = [core_workflow]

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
