# © 2024-25 Infosys Limited, Bangalore, India. All Rights Reserved.
from typing import Dict, List, Optional
from google.adk.agents import BaseAgent, LlmAgent, SequentialAgent, LoopAgent
from google.adk.models.lite_llm import LiteLlm


from src.inference.inference_utils import InferenceUtils
from src.inference.google_adk_inference.base_meta_type_agent_gadk_inference import BaseMetaTypeAgentGADKInference
from src.schemas import AdminConfigLimits
from src.config.constants import Limits

from telemetry_wrapper import logger as log


class MetaAgentGADKInference(BaseMetaTypeAgentGADKInference):
    """
    Inference class for Meta Agent using Google ADK.
    Implements methods to build agents, chains, and workflows specific to the Meta architecture.
    """

    def __init__(self, inference_utils: InferenceUtils):
        super().__init__(inference_utils)


    async def _build_agent_and_chains(self, llm: LiteLlm, agent_config: dict, tool_interrupt_flag: bool = False, tools_to_interrupt: Optional[List[str]] = None) -> dict:
        """
        Builds the agent and chains for the Supervisor workflow.
        Includes evaluator agent for online evaluation support.
        """
        worker_agent_ids = agent_config["TOOLS_INFO"]
        worker_agents_as_tools = await self._get_agents_as_tool_list(llm=llm, worker_agent_ids=worker_agent_ids)
        memory_management_tools = await self._get_memory_management_tools_instances(allow_union_annotation=False)
        agent_name = await self.agent_service.agent_service_utils._normalize_agent_name(agent_name=agent_config["AGENT_NAME"])
        description = agent_config.get("AGENT_DESCRIPTION", "")

        system_prompt: dict = agent_config["SYSTEM_PROMPT"]
        meta_agent_system_prompt = system_prompt.get("SYSTEM_PROMPT_META_AGENT", "")

        tool_interrupt_interpretation_prompt = ""
        tool_calling_llm = llm
        tool_interrupt_flag = tool_interrupt_flag and bool(worker_agents_as_tools)
        if tool_interrupt_flag:
            tool_interrupt_interpretation_prompt = await self.get_tool_interrupt_interpretation_prompt()
            tool_calling_llm = await self.add_additional_args_to_litellm_object(llm=llm, parallel_tool_calls=False)

        # Enhanced Meta Agent Instructions with evaluation feedback support
        meta_agent_system_prompt = f"""\
{meta_agent_system_prompt}

**Important Guidelines**:
- You are the supervisor/meta agent coordinating worker agents.
- Delegate tasks to appropriate worker agents and synthesize their responses.
- Focus on providing accurate and helpful final responses.
{tool_interrupt_interpretation_prompt}
- If you receive evaluation feedback, address each feedback point specifically and improve your response.

{{episodic_memory_context?}}

**Quality Assessment Feedback (if any)**:
{{quality_assessment_feedback?}}
"""

        log.info("Creating Meta Agent instance.")
        meta_agent = LlmAgent(
            name=f"supervisor_for_{agent_name}",
            model=tool_calling_llm,
            instruction=meta_agent_system_prompt,
            tools=worker_agents_as_tools + memory_management_tools,
            output_key="response",
            before_tool_callback=await self.get_before_tool_callback_for_tool_interrupt(tool_verifier_flag=tool_interrupt_flag, tools_to_interrupt=tools_to_interrupt),
            after_tool_callback=await self.get_after_tool_callback_for_tool_interrupt(tool_verifier_flag=tool_interrupt_flag)
        )


        chains = {
            "llm": llm,
            "meta_agent": meta_agent,

            "tools": worker_agents_as_tools,
            "agent_name": agent_name,
            "description": description
        }
        return chains

    async def _build_workflow(self, chains: dict, flags: Dict[str, bool] = {}) -> BaseAgent:
        """
        Builds the workflow for the Meta agent.
        
        Workflow options:
        1. Basic: Meta Agent only
        2. With Quality Assessment: Meta Agent -> Quality Assessment Agent(s) (in loop for quality improvement)
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
        meta_agent = chains.get("meta_agent", None)

        if not meta_agent:
            log.error("Required agent (meta_agent) is missing.")
            raise ValueError("Required agent (meta_agent) is missing.")

        log.info(f"Building workflow for Meta Agent. Evaluation enabled: {evaluation_flag}, Validation enabled: {validator_flag}")

        # Build the core workflow based on flags
        if evaluation_flag or validator_flag:
            quality_assessment_agents = await self.get_quality_assessment_agent(
                llm=llm,
                agent_name=agent_name,
                evaluation_flag=evaluation_flag,
                validator_flag=validator_flag,
                validation_criteria=validation_criteria,
                description=description,
                inference_config=inference_config
            )
            # Meta-Quality Assessment Loop:
            # 1. Meta agent processes the query and coordinates worker agents
            # 2. Quality assessment agent(s) evaluate the response
            # 3. If scores < threshold and attempts < max, loop back with feedback
            # 4. Loop continues until quality threshold is met or max iterations reached
            meta_quality_loop = LoopAgent(
                name=f"meta_quality_loop_for_{agent_name}",
                sub_agents=[meta_agent, *quality_assessment_agents],
                max_iterations=Limits.MAX_CONFIGURABLE_EPOCHS,  # Max quality assessment attempts
                before_agent_callback=await self.get_before_agent_callback_for_quality_loop()
            )
            core_workflow = meta_quality_loop
            log.info("Meta-Quality Assessment loop workflow created.")
        else:
            # Simple Meta agent without quality assessment
            core_workflow = meta_agent
            log.info("Basic Meta agent workflow created (no quality assessment).")

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

