# © 2024-25 Infosys Limited, Bangalore, India. All Rights Reserved.
import asyncio
from langchain.prompts import PromptTemplate
from langchain_core.output_parsers.string import StrOutputParser

from src.prompts.prompts import meta_agent_system_prompt_generator_prompt
from telemetry_wrapper import logger as log

from src.database.services import AgentServiceUtils
from src.agent_templates.base_agent_onboard import BaseMetaTypeAgentOnboard
from src.config.constants import AgentType



class MetaAgentOnboard(BaseMetaTypeAgentOnboard):
    """
    MetaAgentOnboard is a specialized onboarding service for meta-agents, extending the BaseMetaTypeAgentOnboard class.
    """

    def __init__(self, agent_service_utils: AgentServiceUtils):
        super().__init__(agent_type=AgentType.META_AGENT, agent_service_utils=agent_service_utils)


    async def _generate_system_prompt(self, agent_name, agent_goal, workflow_description, tool_or_worker_agents_prompt, llm):
        """Generates a single system prompt for a standard meta-agent."""
        meta_agent_system_prompt_generator_prompt_template = PromptTemplate.from_template(meta_agent_system_prompt_generator_prompt)
        meta_agent_system_prompt_generator = meta_agent_system_prompt_generator_prompt_template | llm | StrOutputParser()

        # Run both LLM calls in parallel
        meta_agent_system_prompt, _ = await asyncio.gather(
            meta_agent_system_prompt_generator.ainvoke({"agent_name": agent_name,
                                                "agent_goal": agent_goal,
                                                "workflow_description": workflow_description,
                                                "worker_agents_prompt": tool_or_worker_agents_prompt}),
            self._generate_and_save_file_context_prompt(
                agent_name=agent_name,
                agent_goal=agent_goal,
                workflow_description=workflow_description,
                tool_or_worker_agents_prompt=tool_or_worker_agents_prompt,
                llm=llm
            )
        )
        log.info(f"Generated meta agent system prompt for agent '{agent_name}'")
        
        return {"SYSTEM_PROMPT_META_AGENT": meta_agent_system_prompt}

    async def _generate_and_save_file_context_prompt(self, agent_name, agent_goal, workflow_description, tool_or_worker_agents_prompt, llm):
        """
        Generates and saves the file-context system prompt for AgentShell-based context management.
        This prompt is stored in a separate file and loaded when file_context_management_flag=True.
        
        Note: Memory tools (manage_tool, search_tool) are filtered out from the tool prompt
        because file-based context management uses shell commands for memory operations.
        """
        from ..prompts.prompts import file_context_system_prompt_generator
        from langchain.prompts import PromptTemplate
        from langchain_core.output_parsers.string import StrOutputParser
        import os
        
        log.info("Generating file-context prompt for agent: %s", agent_name)
        
        # Filter out memory tool information from tool_or_worker_agents_prompt
        # Use common utility from AgentServiceUtils
        filtered_tool_prompt = AgentServiceUtils.filter_memory_tools_from_prompt(tool_or_worker_agents_prompt)
        
        # Generate file-context prompt using LLM
        file_context_prompt_template = PromptTemplate.from_template(file_context_system_prompt_generator)
        file_context_prompt_gen = file_context_prompt_template | llm | StrOutputParser()
        
        file_context_prompt = await file_context_prompt_gen.ainvoke({
            "agent_name": agent_name,
            "agent_goal": agent_goal,
            "workflow_description": workflow_description,
            "tool_prompt": filtered_tool_prompt
        })
        
        # Save to file
        safe_agent_name = "".join(c if c.isalnum() or c in ('-', '_') else '_' for c in agent_name)
        file_context_dir = os.path.join("agent_workspaces", "file_context_prompts")
        os.makedirs(file_context_dir, exist_ok=True)
        file_context_path = os.path.join(file_context_dir, f"{safe_agent_name}_file_context_prompt.md")
        
        with open(file_context_path, "w", encoding="utf-8") as f:
            f.write(file_context_prompt)
        
        log.info("File-context prompt saved to: %s", file_context_path)


