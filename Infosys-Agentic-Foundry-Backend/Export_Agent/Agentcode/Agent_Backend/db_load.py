# © 2024-25 Infosys Limited, Bangalore, India. All Rights Reserved.
import uuid
import json
import asyncpg
from typing import Dict, Any
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from src.utils.cache_utils import CacheableRepository
from src.config.cache_config import EXPIRY_TIME, ENABLE_CACHING
from telemetry_wrapper import logger as log

# --- Base Repository ---


class BaseRepository:
    """
    Base class for all repositories.
    Provides the database connection pool to subclasses.
    """

    def __init__(self, pool: asyncpg.Pool, table_name: str):
        """
        Initializes the BaseRepository with a database connection pool.

        Args:
            pool (asyncpg.Pool): The asyncpg connection pool.
        """
        if not pool:
            raise ValueError("Connection pool is not provided.")
        self.pool = pool
        self.table_name = table_name

class ExportedTagToolMappingRepository(BaseRepository, CacheableRepository):
    """
    Repository for the 'tag_tool_mapping_table'. Handles direct database interactions for tag-tool mappings.
    """

    def __init__(self, pool: asyncpg.Pool, table_name: str = "tag_tool_mapping_table"):
        """
        Initializes the TagToolMappingRepository.

        Args:
            pool (asyncpg.Pool): The asyncpg connection pool.
            table_name (str): The name of the tag-tool mapping table.
        """
        super().__init__(pool, table_name)


    async def create_table_if_not_exists(self):
        """
        Creates the 'tag_tool_mapping_table' if it does not exist.
        The FOREIGN KEY to tool_table.tool_id is intentionally removed here
        to allow mapping of tool IDs from both tool_table and mcp_tool_table.
        """
        try:
            create_statement = f"""
            CREATE TABLE IF NOT EXISTS {self.table_name} (
                tag_id TEXT,
                tool_id TEXT,
                FOREIGN KEY(tag_id) REFERENCES tags_table(tag_id) ON DELETE RESTRICT,
                UNIQUE(tag_id, tool_id)
            );
            """
            async with self.pool.acquire() as conn:
                await conn.execute(create_statement)
            log.info(f"Table '{self.table_name}' created successfully or already exists (without tool_id FK).")
        except Exception as e:
            log.error(f"Error creating table '{self.table_name}': {e}")

    async def assign_tag_to_tool_record(self) -> bool:
        """
        Inserts a mapping between a tag and a tool.

        Args:
            tag_id (str): The ID of the tag.
            tool_id (str): The ID of the tool.

        Returns:
            bool: True if the mapping was inserted successfully, False otherwise.
        """
        from tools_config import tools_data
        tags={}
        for i in tools_data.values():
            tool_id=i['tool_id']
            for tag in i['tags']:
                tag_name=tag['tag_name']
                tags[tool_id]=tag_name
        print("tool tags:",tags)
        for tool_id,tag_name in tags.items():
            fetch_statement = f"""
            SELECT tag_id FROM tags_table WHERE tag_name=$1;
            """
            insert_statement = f"""
            INSERT INTO {self.table_name} (tag_id, tool_id)
            VALUES ($1, $2)
            ON CONFLICT (tag_id, tool_id) DO NOTHING;
            """
            try:
                async with self.pool.acquire() as conn:
                    await conn.execute(fetch_statement, tag_name)
                    row = await conn.fetchrow(fetch_statement, tag_name)
                    tag_id = row['tag_id'] if row else None
                    await conn.execute(insert_statement, tag_id, tool_id)
                log.info(f"Mapping tag '{tag_id}' to tool '{tool_id}' inserted successfully.")
    
            except Exception as e:
                log.error(f"Error assigning tag '{tag_id}' to tool '{tool_id}': {e}")
                return False
        return True

class ExportedTagAgentMappingRepository(BaseRepository, CacheableRepository):
    """
    Repository for the 'tag_agentic_app_mapping_table'. Handles direct database interactions for tag-agent mappings.
    """

    def __init__(self, pool: asyncpg.Pool, table_name: str = "tag_agentic_app_mapping_table"):
        """
        Initializes the TagAgentMappingRepository.

        Args:
            pool (asyncpg.Pool): The asyncpg connection pool.
            table_name (str): The name of the tag-agent mapping table.
        """
        super().__init__(pool, table_name)


    async def create_table_if_not_exists(self):
        """
        Creates the 'tag_agentic_app_mapping_table' if it does not exist.
        """
        try:
            create_statement = f"""
            CREATE TABLE IF NOT EXISTS {self.table_name} (
                tag_id TEXT,
                agentic_application_id TEXT,
                FOREIGN KEY(tag_id) REFERENCES tags_table(tag_id) ON DELETE RESTRICT,
                FOREIGN KEY(agentic_application_id) REFERENCES agent_table(agentic_application_id) ON DELETE CASCADE,
                UNIQUE(tag_id, agentic_application_id)
            );
            """
            async with self.pool.acquire() as conn:
                await conn.execute(create_statement)
            log.info(f"Table '{self.table_name}' created successfully or already exists.")
        except Exception as e:
            log.error(f"Error creating table '{self.table_name}': {e}")

    async def assign_tag_to_agent_record(self) -> bool:
        """
        Inserts a mapping between a tag and an agent.

        Args:
            tag_id (str): The ID of the tag.
            agentic_application_id (str): The ID of the agent.

        Returns:
            bool: True if the mapping was inserted successfully, False otherwise.
        """
        from agent_config import agent_data
        from worker_agents_config import worker_agents
        tags={}
        for i in agent_data.values():
            agentic_application_id=i['agentic_application_id']
            for tag in i['tags']:
                tag_name=tag['tag_name']
                tags[agentic_application_id]=tag_name
        for i in worker_agents.values():
            agentic_application_id=i['agentic_application_id']
            for tag in i['tags']:
                tag_name=tag['tag_name']
                tags[agentic_application_id]=tag_name
        print("Agent tags:",tags)
        for agentic_application_id,tag_name in tags.items():
            fetch_statement=f"""
            SELECT tag_id FROM tags_table WHERE tag_name=$1;
            """
            insert_statement = f"""
            INSERT INTO {self.table_name} (tag_id, agentic_application_id)
            VALUES ($1, $2)
            ON CONFLICT (tag_id, agentic_application_id) DO NOTHING;
            """
            try:
                async with self.pool.acquire() as conn:
                    await conn.execute(fetch_statement, tag_name)
                    row = await conn.fetchrow(fetch_statement, tag_name)
                    tag_id = row['tag_id'] if row else None
                    await conn.execute(insert_statement, tag_id, agentic_application_id)
                log.info(f"Mapping tag '{tag_id}' to agent '{agentic_application_id}' inserted successfully.")
            except Exception as e:
                log.error(f"Error assigning tag '{tag_id}' to agent '{agentic_application_id}': {e}")
                return False
        return True
              
class ExportedToolRepository(BaseRepository, CacheableRepository):
    """
    Repository for the 'tool_table'. Handles direct database interactions for tools.
    """

    def __init__(self, pool: asyncpg.Pool, table_name: str = "tool_table"):
        """
        Initializes the ToolRepository.

        Args:
            pool (asyncpg.Pool): The asyncpg connection pool.
            table_name (str): The name of the tools table.
        """
        super().__init__(pool, table_name)


    async def create_table_if_not_exists(self):
        """
        Creates the 'tool_table' in PostgreSQL if it does not exist.
        """
        try:
            create_statement = f"""
            CREATE TABLE IF NOT EXISTS {self.table_name} (
                tool_id TEXT PRIMARY KEY,
                tool_name TEXT UNIQUE,
                tool_description TEXT,
                code_snippet TEXT,
                model_name TEXT,
                created_by TEXT,
                created_on TIMESTAMPTZ DEFAULT NOW()
                
                
            );
            """
            async with self.pool.acquire() as conn:
                await conn.execute(create_statement)
            log.info(f"Table '{self.table_name}' created successfully or already exists.")
        except Exception as e:
            log.error(f"Error creating table '{self.table_name}': {e}")
    async def save_tool_record(self) -> bool:
        """
        Inserts a new tool record into the tool table.

        Args:
            tool_data (Dict[str, Any]): A dictionary containing the tool data.
                                        Expected keys: tool_id, tool_name, tool_description,
                                        code_snippet, model_name, created_by, created_on, updated_on.

        Returns:
            bool: True if the tool was inserted successfully, False if a unique violation occurred or on other error.
        """
        from tools_config import tools_data
        insert_statement = f"""
        INSERT INTO {self.table_name} (tool_id, tool_name, tool_description, code_snippet, model_name,created_by)
        VALUES ($1, $2, $3, $4, $5,$6) ON CONFLICT (tool_id) DO UPDATE SET
                    tool_name = EXCLUDED.tool_name,
                    tool_description = EXCLUDED.tool_description,
                    code_snippet = EXCLUDED.code_snippet,
                    model_name = EXCLUDED.model_name,
                    created_by = EXCLUDED.created_by;
        """
        try:
            for tool_data in tools_data.values():
                # print("in tool repo",tool_data)
                if (tool_data.get('tool_id')).startswith("mcp_file_") or (tool_data.get('tool_id')).startswith("mcp_url_"):
                    mrepo=ExportedMcpToolRepository(self.pool)
                    await mrepo.create_table_if_not_exists()
                    await mrepo.save_mcp_tool_record(tool_data)
                else:
                    path= tool_data.get("code_snippet", "")
                    with open(path, 'r', encoding='utf-8') as f:
                        code_snippet = f.read()
                    async with self.pool.acquire() as conn:
                        await conn.execute(
                            insert_statement,
                            tool_data.get("tool_id"), tool_data.get("tool_name"),
                            tool_data.get("tool_description"), code_snippet,
                            tool_data.get("model_name"),
                            tool_data["created_by"]
                        )
                    log.info(f"Tool record {tool_data.get('tool_name')} inserted successfully.")
            return True
        except asyncpg.UniqueViolationError:
            log.warning(f"Tool record {tool_data.get('tool_name')} already exists (unique violation).")
            return False
        except Exception as e:
            log.error(f"Error saving tool record {tool_data.get('tool_name')}: {e}")
            return False

class ExportedAgentRepository(BaseRepository, CacheableRepository):
    """
    Repository for the 'agent_table'. Handles direct database interactions for agents.
    """

    def __init__(self, pool: asyncpg.Pool, table_name: str = "agent_table"):
        """
        Initializes the AgentRepository.

        Args:
            pool (asyncpg.Pool): The asyncpg connection pool.
            table_name (str): The name of the agents table.
        """
        super().__init__(pool, table_name)


    async def create_table_if_not_exists(self):
        """
        Creates the 'recycle_agent' table if it does not exist.
        """
        try:
            create_statement = f"""
            CREATE TABLE IF NOT EXISTS {self.table_name} (
                agentic_application_id TEXT PRIMARY KEY,
                agentic_application_name TEXT UNIQUE,
                agentic_application_description TEXT,
                agentic_application_workflow_description TEXT,
                agentic_application_type TEXT,
                model_name TEXT,
                system_prompt JSONB,
                tools_id JSONB,
                created_by TEXT,
                created_on TIMESTAMPTZ DEFAULT NOW()
            );
            """
            async with self.pool.acquire() as conn:
                await conn.execute(create_statement)
            log.info(f"Table '{self.table_name}' created successfully or already exists.")
        except Exception as e:
            log.error(f"Error creating table '{self.table_name}': {e}")
            
    async def save_agent_record(self) -> bool:
        from agent_config import agent_data
        from worker_agents_config import worker_agents
        try:
            for agent in agent_data.values():
                agent_id = agent.get("agentic_application_id", str(uuid.uuid4()))
                agent_name = agent.get("agentic_application_name")
                agent_description = agent.get("agentic_application_description", "")
                workflow_description = agent.get("agentic_application_workflow_description", "")
                agent_type = agent.get("agentic_application_type", "default")
                model_name = agent.get("model_name", "default_model")
                system_prompt = agent.get("system_prompt", {})
                system_prompt = json.dumps(system_prompt)
                tools_id = agent.get("tools_id", [])
                tools_id=json.dumps(tools_id)
                created_by=agent.get("created_by","")

                insert_statement = f"""
                INSERT INTO {self.table_name} (
                    agentic_application_id,
                    agentic_application_name,
                    agentic_application_description,
                    agentic_application_workflow_description,
                    agentic_application_type,
                    model_name,
                    system_prompt,
                    tools_id,
                    created_by
                ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8,$9)
                ON CONFLICT (agentic_application_id) DO UPDATE SET
                    agentic_application_name = EXCLUDED.agentic_application_name,
                    agentic_application_description = EXCLUDED.agentic_application_description,
                    agentic_application_workflow_description = EXCLUDED.agentic_application_workflow_description,
                    agentic_application_type = EXCLUDED.agentic_application_type,
                    model_name = EXCLUDED.model_name,
                    system_prompt = EXCLUDED.system_prompt,
                    tools_id = EXCLUDED.tools_id,
                    created_by = EXCLUDED.created_by;
                """
                
                async with self.pool.acquire() as conn:
                    await conn.execute(insert_statement, 
                                       agent_id, 
                                       agent_name, 
                                       agent_description, 
                                       workflow_description, 
                                       agent_type, 
                                       model_name, 
                                       system_prompt, 
                                       tools_id,
                                       created_by)
            if worker_agents:
                for agent in worker_agents.values():
                    agent_id = agent.get("agentic_application_id", str(uuid.uuid4()))
                    agent_name = agent.get("agentic_application_name")
                    agent_description = agent.get("agentic_application_description", "")
                    workflow_description = agent.get("agentic_application_workflow_description", "")
                    agent_type = agent.get("agentic_application_type", "default")
                    model_name = agent.get("model_name", "default_model")
                    system_prompt = agent.get("system_prompt", {})
                    system_prompt = json.dumps(system_prompt)
                    tools_id = agent.get("tools_id", [])
                    tools_id=json.dumps(tools_id)
                    # tools_id = agent.get("tools_id", [])
                    created_by=agent.get("created_by","")

                    insert_statement = f"""
                    INSERT INTO {self.table_name} (
                        agentic_application_id,
                        agentic_application_name,
                        agentic_application_description,
                        agentic_application_workflow_description,
                        agentic_application_type,
                        model_name,
                        system_prompt,
                        tools_id,
                        created_by
                    ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8,$9)
                    ON CONFLICT (agentic_application_id) DO UPDATE SET
                        agentic_application_name = EXCLUDED.agentic_application_name,
                        agentic_application_description = EXCLUDED.agentic_application_description,
                        agentic_application_workflow_description = EXCLUDED.agentic_application_workflow_description,
                        agentic_application_type = EXCLUDED.agentic_application_type,
                        model_name = EXCLUDED.model_name,
                        system_prompt = EXCLUDED.system_prompt,
                        tools_id = EXCLUDED.tools_id,
                        created_by = EXCLUDED.created_by;
                    """
                    
                    async with self.pool.acquire() as conn:
                        await conn.execute(insert_statement, 
                                        agent_id, 
                                        agent_name, 
                                        agent_description, 
                                        workflow_description, 
                                        agent_type, 
                                        model_name, 
                                        system_prompt, 
                                        tools_id,
                                        created_by)
            else:
                log.info("Worker Agents data is empty")
            
            log.info(f"Agent records saved successfully in table '{self.table_name}'.")
        except Exception as e:
            log.error(f"Error inserting into table '{self.table_name}': {e}")   

class ExportedMcpToolRepository(BaseRepository):
    """
    Repository for the 'mcp_tool_table'. Handles direct database interactions for MCP server definitions.
    """
    def __init__(self, pool: asyncpg.Pool, table_name: str = "mcp_tool_table"):
        """
        Initializes the McpToolRepository.

        Args:
            pool (asyncpg.Pool): The asyncpg connection pool.
            table_name (str): The name of the MCP tools table.
        """
        super().__init__(pool, table_name)


    async def create_table_if_not_exists(self):
        """
        Creates the 'mcp_tool_table' in PostgreSQL if it does not exist.
        Includes new auth-related columns and the CHECK constraint directly.
        """
        try:
            create_statement = f"""
            CREATE TABLE IF NOT EXISTS {self.table_name} (
                tool_id TEXT PRIMARY KEY,
                tool_name TEXT UNIQUE NOT NULL,
                tool_description TEXT,
                mcp_config JSONB NOT NULL, 
                created_by TEXT,
                created_on TIMESTAMPTZ DEFAULT NOW()
            );
            """
            async with self.pool.acquire() as conn:
                await conn.execute(create_statement)

            log.info(f"Table '{self.table_name}' created successfully or already exists.")
        except Exception as e:
            log.error(f"Error creating table '{self.table_name}': {e}")
            raise # Re-raise to ensure startup failure if table creation fails
    async def save_mcp_tool_record(self, tool_data: Dict[str, Any]) -> bool:
        """
        Inserts a new MCP tool (server definition) record into the mcp_tool_table.

        Args:
            tool_data (Dict[str, Any]): A dictionary containing the MCP tool data.
                                        Expected keys: tool_id, tool_name, tool_description,
                                        mcp_config (JSON dumped), is_public, status, comments,
                                        approved_at, approved_by, created_by, created_on, updated_on.

        Returns:
            bool: True if the tool was inserted successfully, False if a unique violation occurred or on other error.
        """
        insert_statement = f"""
        INSERT INTO {self.table_name} (
            tool_id, tool_name, tool_description,mcp_config,
            created_by
        ) VALUES ($1, $2, $3, $4, $5) ON CONFLICT (tool_id) DO UPDATE SET
            tool_name = EXCLUDED.tool_name,
            tool_description = EXCLUDED.tool_description,
            mcp_config = EXCLUDED.mcp_config,
            created_by = EXCLUDED.created_by
        """
        try:
            print(tool_data)
            async with self.pool.acquire() as conn:
                await conn.execute(
                    insert_statement,
                    tool_data.get("tool_id"),
                    tool_data.get("tool_name"),
                    tool_data.get("tool_description"),
                    json.dumps(tool_data.get("mcp_config")), # Ensure JSONB is dumped
                    tool_data.get("created_by")
                )
            log.info(f"MCP tool record '{tool_data.get('tool_name')}' inserted successfully.")
            return True
        except asyncpg.UniqueViolationError:
            log.warning(f"MCP tool record '{tool_data.get('tool_name')}' already exists (unique violation).")
            return False
        except Exception as e:
            log.error(f"Error saving MCP tool record '{tool_data.get('tool_name')}': {e}")
            return False