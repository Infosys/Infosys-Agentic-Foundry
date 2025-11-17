# © 2024-25 Infosys Limited, Bangalore, India. All Rights Reserved.
from typing import Dict
from src.prompts.prompts import hybrid_agent_system_prompt_generator_prompt

from src.database.services import AgentServiceUtils
from src.agent_templates.base_agent_onboard import BaseAgentOnboard
from src.models.base_ai_model_service import BaseAIModelService

from telemetry_wrapper import logger as log


class HybridAgentOnboard(BaseAgentOnboard):
    """
    HybridAgentOnboard is a specialized onboarding service for a hybrid agent,
    extending the BaseAgentOnboard class. This agent can intelligently decide
    between direct response and planning, and execute tools.
    """

    def __init__(self, agent_service_utils: AgentServiceUtils):
        super().__init__(agent_type="hybrid_agent", agent_service_utils=agent_service_utils)


    async def _get_llm_model(self, model_name: str, temperature: float = 0):
        """
        Retrieves the LLM model instance for the specified model name and temperature.
        """
        return await self.model_service.get_llm_model_using_python(model_name=model_name, temperature=temperature)

    async def _generate_system_prompt(self, agent_name: str, agent_goal: str,
                                      workflow_description: str,
                                      tool_or_worker_agents_prompt: str, llm: BaseAIModelService) -> Dict[str, str]:
        """
        Generates a system prompt for the Hybrid Agent using the provided parameters and LLM model.
        """
        hybrid_system_prompt_gen = hybrid_agent_system_prompt_generator_prompt.format(
                                                                        agent_name=agent_name,
                                                                        agent_goal=agent_goal,
                                                                        workflow_description=workflow_description,
                                                                        tool_prompt=tool_or_worker_agents_prompt
                                                                    )
        messages = [llm.format_content_with_role(hybrid_system_prompt_gen)]

        log.info(f"Generating Hybrid Agent System Prompt for agent {agent_name}")
        hybrid_agent_system_prompt = await llm.ainvoke(messages=messages)

        log.info(f"Generated Hybrid Agent System Prompt for agent {agent_name}")
        return {"SYSTEM_PROMPT_HYBRID_AGENT": hybrid_agent_system_prompt["final_response"]}


