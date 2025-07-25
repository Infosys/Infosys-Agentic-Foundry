# © 2024-25 Infosys Limited, Bangalore, India. All Rights Reserved.
from langchain.prompts import PromptTemplate
from langchain_core.output_parsers.string import StrOutputParser

from src.prompts.prompts import react_system_prompt_generator
from telemetry_wrapper import logger as log

from src.database.repositories import AgentRepository, RecycleAgentRepository
from src.database.services import TagService, ToolService
from src.agent_templates.base_agent_onboard import BaseAgentOnboard



class ReactAgentOnboard(BaseAgentOnboard):
    """
    ReactAgentOnboard is a specialized onboarding service for React agents, extending the BaseAgentOnboard class.
    """

    def __init__(
        self,
        agent_repo: AgentRepository,
        recycle_agent_repo: RecycleAgentRepository,
        tool_service: ToolService,
        tag_service: TagService,
    ):
        super().__init__(
            agent_type="react_agent",
            agent_repo=agent_repo,
            recycle_agent_repo=recycle_agent_repo,
            tool_service=tool_service,
            tag_service=tag_service
        )


    async def _generate_system_prompt(self, agent_name, agent_goal, workflow_description, tool_or_worker_agents_prompt, llm):
        react_system_prompt_template = PromptTemplate.from_template(react_system_prompt_generator)
        react_system_prompt_gen = react_system_prompt_template | llm | StrOutputParser()
        log.info(f"Generating React System Prompt for agent {agent_name}")
        react_system_prompt = await react_system_prompt_gen.ainvoke({"agent_name": agent_name,
                                    "agent_goal": agent_goal,
                                    "workflow_description": workflow_description,
                                    "tool_prompt": tool_or_worker_agents_prompt})
        log.info(f"Generated React System Prompt for agent {agent_name}")
        return {"SYSTEM_PROMPT_REACT_AGENT": react_system_prompt}

