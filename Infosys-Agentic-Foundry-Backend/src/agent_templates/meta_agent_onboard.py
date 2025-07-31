# © 2024-25 Infosys Limited, Bangalore, India. All Rights Reserved.
from langchain.prompts import PromptTemplate
from langchain_core.output_parsers.string import StrOutputParser

from src.prompts.prompts import meta_agent_system_prompt_generator_prompt
from telemetry_wrapper import logger as log

from src.database.repositories import AgentRepository, RecycleAgentRepository
from src.database.services import TagService, ToolService
from src.agent_templates.base_agent_onboard import BaseMetaTypeAgentOnboard



class MetaAgentOnboard(BaseMetaTypeAgentOnboard):
    """
    MetaAgentOnboard is a specialized onboarding service for meta-agents, extending the BaseMetaTypeAgentOnboard class.
    """

    def __init__(
        self,
        agent_repo: AgentRepository,
        recycle_agent_repo: RecycleAgentRepository,
        tool_service: ToolService,
        tag_service: TagService,
    ):
        super().__init__(
            agent_type="meta_agent",
            agent_repo=agent_repo,
            recycle_agent_repo=recycle_agent_repo,
            tool_service=tool_service,
            tag_service=tag_service
        )


    async def _generate_system_prompt(self, agent_name, agent_goal, workflow_description, tool_or_worker_agents_prompt, llm):
        """Generates a single system prompt for a standard meta-agent."""
        meta_agent_system_prompt_generator_prompt_template = PromptTemplate.from_template(meta_agent_system_prompt_generator_prompt)
        meta_agent_system_prompt_generator = meta_agent_system_prompt_generator_prompt_template | llm | StrOutputParser()

        meta_agent_system_prompt = await meta_agent_system_prompt_generator.ainvoke({"agent_name": agent_name,
                                                "agent_goal": agent_goal,
                                                "workflow_description": workflow_description,
                                                "worker_agents_prompt": tool_or_worker_agents_prompt})
        meta_agent_system_prompt = meta_agent_system_prompt
        log.info(f"Generated meta agent system prompt for agent '{agent_name}'")
        return {"SYSTEM_PROMPT_META_AGENT": meta_agent_system_prompt}


