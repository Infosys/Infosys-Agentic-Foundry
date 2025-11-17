# © 2024-25 Infosys Limited, Bangalore, India. All Rights Reserved.
from src.prompts.prompts import react_system_prompt_generator

from src.database.services import AgentServiceUtils
from src.agent_templates.base_agent_onboard import BaseAgentOnboard
from src.models.base_ai_model_service import BaseAIModelService

from telemetry_wrapper import logger as log


class SimpleAIAgentOnboard(BaseAgentOnboard):
    """
    ReactAgentOnboard is a specialized onboarding service for React agents, extending the BaseAgentOnboard class.
    """

    def __init__(self, agent_service_utils: AgentServiceUtils):
        super().__init__(agent_type="simple_ai_agent", agent_service_utils=agent_service_utils)


    async def _get_llm_model(self, model_name: str, temperature: float = 0):
        """
        Retrieves the LLM model instance for the specified model name and temperature.
        """
        return await self.model_service.get_llm_model_using_python(model_name=model_name, temperature=temperature)

    async def _generate_system_prompt(self, agent_name: str, agent_goal: str, workflow_description: str, tool_or_worker_agents_prompt: str, llm: BaseAIModelService):
        """
        Generates a system prompt for the agent using the provided parameters and LLM model.
        """
        
        simple_ai_agent_system_prompt_gen = react_system_prompt_generator.format(
                                                                        agent_name=agent_name,
                                                                        agent_goal=agent_goal,
                                                                        workflow_description=workflow_description,
                                                                        tool_prompt=tool_or_worker_agents_prompt
                                                                    )
        messages = [llm.format_content_with_role(simple_ai_agent_system_prompt_gen)]

        log.info("Generating Simple AI Agent System Prompt")
        simple_ai_agent_system_prompt = await llm.ainvoke(messages=messages)

        log.info(f"Generated Simple AI Agent System Prompt for agent {agent_name}")
        return {"SYSTEM_PROMPT_SIMPLE_AI_AGENT": simple_ai_agent_system_prompt["final_response"]}


