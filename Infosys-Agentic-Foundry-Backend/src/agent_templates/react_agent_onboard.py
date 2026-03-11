# © 2024-25 Infosys Limited, Bangalore, India. All Rights Reserved.
import asyncio
from pathlib import Path
from langchain.prompts import PromptTemplate
from langchain_core.output_parsers.string import StrOutputParser

from src.prompts.prompts import react_system_prompt_generator, file_context_system_prompt_generator
from telemetry_wrapper import logger as log

from src.database.services import AgentServiceUtils
from src.agent_templates.base_agent_onboard import BaseAgentOnboard
from src.config.constants import AgentType


# Directory to store file-context prompts
FILE_CONTEXT_PROMPTS_DIR = Path("./agent_workspaces/file_context_prompts")


class ReactAgentOnboard(BaseAgentOnboard):
    """
    ReactAgentOnboard is a specialized onboarding service for React agents, extending the BaseAgentOnboard class.
    """

    def __init__(self, agent_service_utils: AgentServiceUtils):
        super().__init__(agent_type=AgentType.REACT_AGENT, agent_service_utils=agent_service_utils)


    async def _generate_system_prompt(self, agent_name, agent_goal, workflow_description, tool_or_worker_agents_prompt, llm):
        # Generate regular system prompt (stored in DB)
        react_system_prompt_template = PromptTemplate.from_template(react_system_prompt_generator)
        react_system_prompt_gen = react_system_prompt_template | llm | StrOutputParser()
        log.info(f"Generating React System Prompt for agent {agent_name}")
        
        # Run both LLM calls in parallel
        react_system_prompt, _ = await asyncio.gather(
            react_system_prompt_gen.ainvoke({
                "agent_name": agent_name,
                "agent_goal": agent_goal,
                "workflow_description": workflow_description,
                "tool_prompt": tool_or_worker_agents_prompt
            }),
            self._generate_and_save_file_context_prompt(
                agent_name=agent_name,
                agent_goal=agent_goal,
                workflow_description=workflow_description,
                tool_or_worker_agents_prompt=tool_or_worker_agents_prompt,
                llm=llm
            )
        )
        
        log.info(f"Generated React System Prompt for agent {agent_name}")
        
        return {"SYSTEM_PROMPT_REACT_AGENT": react_system_prompt}

    async def _generate_and_save_file_context_prompt(self, agent_name, agent_goal, workflow_description, tool_or_worker_agents_prompt, llm):
        """
        Generate file-context-aware system prompt and save it to a file.
        This prompt will be used when file_context_management_flag=True.
        
        Note: Memory tools (manage_tool, search_tool) are filtered out from the tool prompt
        because file-based context management uses shell commands for memory operations.
        """
        try:
            # Filter out memory tool information from tool_or_worker_agents_prompt
            # File-based context management uses shell commands for memory, not manage_tool/search_tool
            filtered_tool_prompt = AgentServiceUtils.filter_memory_tools_from_prompt(tool_or_worker_agents_prompt)
            
            # Generate file-context prompt
            file_context_prompt_template = PromptTemplate.from_template(file_context_system_prompt_generator)
            file_context_prompt_gen = file_context_prompt_template | llm | StrOutputParser()
            
            log.info(f"Generating File-Context System Prompt for agent {agent_name}")
            file_context_prompt = await file_context_prompt_gen.ainvoke({
                "agent_name": agent_name,
                "agent_goal": agent_goal,
                "workflow_description": workflow_description,
                "tool_prompt": filtered_tool_prompt
            })
            log.info(f"Generated File-Context System Prompt for agent {agent_name}")
            
            # Save to file
            FILE_CONTEXT_PROMPTS_DIR.mkdir(parents=True, exist_ok=True)
            
            # Sanitize agent name for filename
            safe_agent_name = "".join(c if c.isalnum() or c in ('-', '_') else '_' for c in agent_name)
            prompt_file_path = FILE_CONTEXT_PROMPTS_DIR / f"{safe_agent_name}_file_context_prompt.md"
            
            prompt_file_path.write_text(file_context_prompt, encoding="utf-8")
            log.info(f"Saved File-Context System Prompt to: {prompt_file_path}")
            
            return str(prompt_file_path)
            
        except Exception as e:
            log.error(f"Error generating/saving file-context prompt for agent {agent_name}: {e}")
            return None


