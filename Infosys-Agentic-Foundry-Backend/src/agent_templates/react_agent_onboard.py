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


# Directory to store file-context prompts (department-based, resolved at runtime)
# Legacy constant kept for reference; use get_file_context_prompts_dir(department) instead
FILE_CONTEXT_PROMPTS_DIR = Path("./agent_workspaces/file_context_prompts")


class ReactAgentOnboard(BaseAgentOnboard):
    """
    ReactAgentOnboard is a specialized onboarding service for React agents, extending the BaseAgentOnboard class.
    """

    def __init__(self, agent_service_utils: AgentServiceUtils):
        super().__init__(agent_type=AgentType.REACT_AGENT, agent_service_utils=agent_service_utils)


    async def _generate_system_prompt(self, agent_name, agent_goal, workflow_description, tool_or_worker_agents_prompt, llm, db_connection_names=None):
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
                llm=llm,
                db_connection_names=db_connection_names
            )
        )
        
        log.info(f"Generated React System Prompt for agent {agent_name}")
        
        return {"SYSTEM_PROMPT_REACT_AGENT": react_system_prompt}

    async def _generate_and_save_file_context_prompt(self, agent_name, agent_goal, workflow_description, tool_or_worker_agents_prompt, llm, db_connection_names=None):
        """
        Generate file-context-aware system prompt and save it to a file.
        This prompt will be used when file_context_management_flag=True.
        
        Note: Memory tools (manage_tool, search_tool) are filtered out from the tool prompt
        because file-based context management uses shell commands for memory operations.
        
        Args:
            db_connection_names: Optional list of database connection names to include in prompt.
        """
        try:
            # Filter out memory tool information from tool_or_worker_agents_prompt
            # File-based context management uses shell commands for memory, not manage_tool/search_tool
            filtered_tool_prompt = AgentServiceUtils.filter_memory_tools_from_prompt(tool_or_worker_agents_prompt)
            
            # Generate database connection info and schema access instructions
            db_connections_info = "No database connections configured."
            db_schema_access_instructions = """- `ls /databases/` - List available database connections
- `cat /databases/{connection_name}/schema.md` - Read database schema (ALWAYS read before SQL queries)
- `cat /databases/{connection_name}/samples.md` - Read sample data for reference"""
            
            if db_connection_names and len(db_connection_names) > 0:
                # Generate detailed info about configured databases
                db_list = ", ".join([f"`{name}`" for name in db_connection_names])
                db_connections_info = f"""The agent has access to the following databases: {db_list}

**IMPORTANT FOR DATABASE QUERIES:**
- ALWAYS read the schema first using `cat /databases/{{connection_name}}/schema.md`
- Use `database_query_tool` to execute SELECT queries
- Only operations NOT in the connection's blocked commands list are allowed (default blocks INSERT, UPDATE, DELETE, DROP etc.)
"""
                
                # Generate specific schema access instructions
                schema_instructions = ["- `ls /databases/` - List available database connections"]
                for conn_name in db_connection_names:
                    schema_instructions.append(f"- `cat /databases/{conn_name}/schema.md` - Read {conn_name} schema")
                    schema_instructions.append(f"- `cat /databases/{conn_name}/samples.md` - Read {conn_name} sample data")
                
                db_schema_access_instructions = "\n".join(schema_instructions)
                
                log.info(f"Including {len(db_connection_names)} database connections in file-context prompt: {db_connection_names}")
            
            # Generate file-context prompt
            file_context_prompt_template = PromptTemplate.from_template(file_context_system_prompt_generator)
            file_context_prompt_gen = file_context_prompt_template | llm | StrOutputParser()
            
            log.info(f"Generating File-Context System Prompt for agent {agent_name}")
            file_context_prompt = await file_context_prompt_gen.ainvoke({
                "agent_name": agent_name,
                "agent_goal": agent_goal,
                "workflow_description": workflow_description,
                "tool_prompt": filtered_tool_prompt,
                "db_connections_info": db_connections_info,
                "db_schema_access_instructions": db_schema_access_instructions
            })
            log.info(f"Generated File-Context System Prompt for agent {agent_name}")
            
            # Save to file (department-segregated)
            from src.utils.secrets_handler import current_user_department
            from src.inference.database_tools_cache import get_file_context_prompts_dir
            user_department = current_user_department.get("General")
            dept_prompts_dir = get_file_context_prompts_dir(user_department)
            dept_prompts_dir.mkdir(parents=True, exist_ok=True)
            
            # Sanitize agent name for filename
            safe_agent_name = "".join(c if c.isalnum() or c in ('-', '_') else '_' for c in agent_name)
            prompt_file_path = dept_prompts_dir / f"{safe_agent_name}_file_context_prompt.md"
            
            prompt_file_path.write_text(file_context_prompt, encoding="utf-8")
            log.info(f"Saved File-Context System Prompt to: {prompt_file_path}")
            
            return str(prompt_file_path)
            
        except Exception as e:
            log.error(f"Error generating/saving file-context prompt for agent {agent_name}: {e}")
            return None


