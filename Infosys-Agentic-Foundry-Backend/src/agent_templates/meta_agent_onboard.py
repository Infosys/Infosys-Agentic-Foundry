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


    async def _generate_system_prompt(self, agent_name, agent_goal, workflow_description, tool_or_worker_agents_prompt, llm, db_connection_names=None):
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
                llm=llm,
                db_connection_names=db_connection_names
            )
        )
        log.info(f"Generated meta agent system prompt for agent '{agent_name}'")
        
        return {"SYSTEM_PROMPT_META_AGENT": meta_agent_system_prompt}

    async def _generate_and_save_file_context_prompt(self, agent_name, agent_goal, workflow_description, tool_or_worker_agents_prompt, llm, db_connection_names=None):
        """
        Generates and saves the file-context system prompt for AgentShell-based context management.
        This prompt is stored in a separate file and loaded when file_context_management_flag=True.
        
        Note: Memory tools (manage_tool, search_tool) are filtered out from the tool prompt
        because file-based context management uses shell commands for memory operations.
        
        Args:
            db_connection_names: Optional list of database connection names to include in prompt.
        """
        from ..prompts.prompts import file_context_system_prompt_generator
        from langchain.prompts import PromptTemplate
        from langchain_core.output_parsers.string import StrOutputParser
        import os
        
        log.info("Generating file-context prompt for agent: %s", agent_name)
        
        # Filter out memory tool information from tool_or_worker_agents_prompt
        # Use common utility from AgentServiceUtils
        filtered_tool_prompt = AgentServiceUtils.filter_memory_tools_from_prompt(tool_or_worker_agents_prompt)
        
        # Generate database connection info and schema access instructions
        db_connections_info = "No database connections configured."
        db_schema_access_instructions = """- `ls /databases/` - List available database connections
- `cat /databases/{connection_name}/schema.md` - Read database schema (ALWAYS read before SQL queries)
- `cat /databases/{connection_name}/samples.md` - Read sample data for reference"""
        
        if db_connection_names and len(db_connection_names) > 0:
            db_list = ", ".join([f"`{name}`" for name in db_connection_names])
            db_connections_info = f"""The agent has access to the following databases: {db_list}

**IMPORTANT FOR DATABASE QUERIES:**
- ALWAYS read the schema first using `cat /databases/{{connection_name}}/schema.md`
- Use `database_query_tool` to execute SELECT queries
- Only operations NOT in the connection's blocked commands list are allowed (default blocks INSERT, UPDATE, DELETE, DROP etc.)
"""
            schema_instructions = ["- `ls /databases/` - List available database connections"]
            for conn_name in db_connection_names:
                schema_instructions.append(f"- `cat /databases/{conn_name}/schema.md` - Read {conn_name} schema")
                schema_instructions.append(f"- `cat /databases/{conn_name}/samples.md` - Read {conn_name} sample data")
            db_schema_access_instructions = "\n".join(schema_instructions)
            log.info(f"Including {len(db_connection_names)} database connections in file-context prompt: {db_connection_names}")
        
        # Generate file-context prompt using LLM
        file_context_prompt_template = PromptTemplate.from_template(file_context_system_prompt_generator)
        file_context_prompt_gen = file_context_prompt_template | llm | StrOutputParser()
        
        file_context_prompt = await file_context_prompt_gen.ainvoke({
            "agent_name": agent_name,
            "agent_goal": agent_goal,
            "workflow_description": workflow_description,
            "tool_prompt": filtered_tool_prompt,
            "db_connections_info": db_connections_info,
            "db_schema_access_instructions": db_schema_access_instructions
        })
        
        # Save to file (department-segregated)
        safe_agent_name = "".join(c if c.isalnum() or c in ('-', '_') else '_' for c in agent_name)
        from src.utils.secrets_handler import current_user_department
        from src.inference.database_tools_cache import get_file_context_prompts_dir
        user_department = current_user_department.get("General")
        file_context_dir = str(get_file_context_prompts_dir(user_department))
        file_context_path = os.path.join(file_context_dir, f"{safe_agent_name}_file_context_prompt.md")
        
        with open(file_context_path, "w", encoding="utf-8") as f:
            f.write(file_context_prompt)
        
        log.info("File-context prompt saved to: %s", file_context_path)


