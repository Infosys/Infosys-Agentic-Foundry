import os
import json
import uuid
import asyncpg
from typing import List, Dict, Any, Optional, Union
from exportagent.telemetry_wrapper import logger as log
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from datetime import datetime
import difflib
from langgraph.store.postgres.aio import AsyncPostgresStore
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
# --- ModelRepository ---

class ModelRepository(BaseRepository):
    """
    Repository for the 'models' table. Handles direct database interactions for LLM model records.
    """

    def __init__(self, pool: asyncpg.Pool, table_name: str = "models"):
        super().__init__(pool, table_name)


    async def create_table_if_not_exists(self):
        """
        Creates the 'models' table in PostgreSQL if it does not exist.
        """
        create_statement = f"""
        CREATE TABLE IF NOT EXISTS {self.table_name} (
            id SERIAL PRIMARY KEY,                  -- Auto-incrementing ID
            model_name TEXT UNIQUE NOT NULL         -- Unique model name
        );
        """
        try:
            async with self.pool.acquire() as conn:
                await conn.execute(create_statement)
            log.info(f"Table '{self.table_name}' created successfully or already exists.")
        except Exception as e:
            log.error(f"Error creating table '{self.table_name}': {e}")
            raise # Re-raise for service to handle

    async def insert_model_record(self, model_name: str) -> bool:
        """
        Inserts a new model record into the 'models' table.
        Returns True on success, False on unique violation or other error.
        """
        insert_statement = f"""
        INSERT INTO {self.table_name} (model_name)
        VALUES ($1)
        ON CONFLICT (model_name) DO NOTHING;
        """
        try:
            async with self.pool.acquire() as conn:
                result:str = await conn.execute(insert_statement, model_name)
            return not result.startswith("INSERT 0") # True if a row was inserted, False if conflicted
        except Exception as e:
            log.error(f"Error inserting model record '{model_name}': {e}")
            return False

    async def get_all_model_records(self) -> List[Dict[str, Any]]:
        """
        Retrieves all model records from the 'models' table.
        """
        query = f"SELECT model_name FROM {self.table_name} ORDER BY model_name;"
        try:
            async with self.pool.acquire() as conn:
                rows = await conn.fetch(query)
            return [dict(row) for row in rows]
        except Exception as e:
            log.error(f"Error retrieving all model records: {e}")
            return []

    async def delete_model_record(self, model_name: str) -> bool:
        """
        Deletes a model record from the 'models' table by its name.
        """
        delete_query = f"DELETE FROM {self.table_name} WHERE model_name = $1;"
        try:
            async with self.pool.acquire() as conn:
                result = await conn.execute(delete_query, model_name)
            return result != "DELETE 0"
        except asyncpg.ForeignKeyViolationError as e:
            log.error(f"Cannot delete model '{model_name}' due to foreign key constraint: {e}")
            return False
        except Exception as e:
            log.error(f"Error deleting model record '{model_name}': {e}")
            return False
# --- McpToolRepository ---

class McpToolRepository(BaseRepository):
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
                mcp_config JSONB NOT NULL, -- Stores the entire MCP config dictionary for the server
                is_public BOOLEAN DEFAULT FALSE,
                status TEXT DEFAULT 'pending',
                comments TEXT,
                approved_at TIMESTAMPTZ,
                approved_by TEXT,
                created_by TEXT,
                created_on TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_on TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                CONSTRAINT {self.table_name}_status_check CHECK (status IN ('pending', 'approved', 'rejected'))
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
            tool_id, tool_name, tool_description, mcp_config,
            is_public, status, comments, approved_at, approved_by,
            created_by, created_on, updated_on
        ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12)
        """
        try:
            async with self.pool.acquire() as conn:
                await conn.execute(
                    insert_statement,
                    tool_data.get("tool_id"),
                    tool_data.get("tool_name"),
                    tool_data.get("tool_description"),
                    json.dumps(tool_data.get("mcp_config")), # Ensure JSONB is dumped
                    tool_data.get("is_public", False),
                    tool_data.get("status", "pending"),
                    tool_data.get("comments"),
                    tool_data.get("approved_at"),
                    tool_data.get("approved_by"),
                    tool_data.get("created_by"),
                    tool_data["created_on"],
                    tool_data["updated_on"]
                )
            log.info(f"MCP tool record '{tool_data.get('tool_name')}' inserted successfully.")
            return True
        except asyncpg.UniqueViolationError:
            log.warning(f"MCP tool record '{tool_data.get('tool_name')}' already exists (unique violation).")
            return False
        except Exception as e:
            log.error(f"Error saving MCP tool record '{tool_data.get('tool_name')}': {e}")
            return False

    async def get_mcp_tool_record(self, tool_id: Optional[str] = None, tool_name: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        Retrieves a single MCP tool (server definition) record by its ID or name.

        Args:
            tool_id (Optional[str]): The ID of the MCP tool.
            tool_name (Optional[str]): The name of the MCP tool.

        Returns:
            List[Dict[str, Any]]: A list of dictionaries representing the MCP tool record, or an empty list if not found.
        """
        query = f"SELECT * FROM {self.table_name} WHERE "
        params = []
        if tool_id:
            query += "tool_id = $1"
            params.append(tool_id)
        elif tool_name:
            query += "tool_name = $1"
            params.append(tool_name)
        else:
            log.warning("No tool_id or tool_name provided to get_mcp_tool_record.")
            return []

        try:
            async with self.pool.acquire() as conn:
                rows = await conn.fetch(query, *params)
            if rows:
                log.info(f"MCP tool record '{tool_id or tool_name}' retrieved successfully.")
                # Ensure JSONB is loaded as Python object (asyncpg usually handles this)
                return [dict(row) for row in rows]
            else:
                log.info(f"MCP tool record '{tool_id or tool_name}' not found.")
                return []
        except Exception as e:
            log.error(f"Error retrieving MCP tool record '{tool_id or tool_name}': {e}")
            return []

    async def get_all_mcp_tool_records(self) -> List[Dict[str, Any]]:
        """
        Retrieves all MCP tool (server definition) records.

        Returns:
            List[Dict[str, Any]]: A list of dictionaries, each representing an MCP tool record.
        """
        query = f"SELECT * FROM {self.table_name} ORDER BY created_on DESC"
        try:
            async with self.pool.acquire() as conn:
                rows = await conn.fetch(query)
            log.info(f"Retrieved {len(rows)} MCP tool records from '{self.table_name}'.")
            # Ensure JSONB is loaded as Python object
            return [dict(row) for row in rows]
        except Exception as e:
            log.error(f"Error retrieving all MCP tool records: {e}")
            return []

    async def get_mcp_tools_by_search_or_page_records(self, search_value: str, limit: int, page: int) -> List[Dict[str, Any]]:
        """
        Retrieves MCP tool (server definition) records with pagination and search filtering.

        Args:
            search_value (str): The value to search for in tool names (case-insensitive, LIKE).
            limit (int): The maximum number of records to return.
            page (int): The page number (1-indexed).

        Returns:
            List[Dict[str, Any]]: A list of dictionaries, each representing an MCP tool record.
        """
        name_filter = f"%{search_value.lower()}%" if search_value else "%"
        offset = limit * max(0, page - 1)

        query = f"""
            SELECT * FROM {self.table_name}
            WHERE LOWER(tool_name) LIKE $1
            ORDER BY created_on DESC
            LIMIT $2 OFFSET $3;
        """
        try:
            async with self.pool.acquire() as conn:
                rows = await conn.fetch(query, name_filter, limit, offset)
            log.info(f"Retrieved {len(rows)} MCP tool records for search '{search_value}', page {page}.")
            # Ensure JSONB is loaded as Python object
            return [dict(row) for row in rows]
        except Exception as e:
            log.error(f"Error retrieving MCP tool records by search/page: {e}")
            return []

    async def get_total_mcp_tool_count(self, search_value: str = "") -> int:
        """
        Retrieves the total count of MCP tool (server definition) records, optionally filtered by name.

        Args:
            search_value (str): The value to search for in tool names (case-insensitive, LIKE).

        Returns:
            int: The total count of matching MCP tool records.
        """
        name_filter = f"%{search_value.lower()}%" if search_value else "%"
        query = f"SELECT COUNT(*) FROM {self.table_name} WHERE LOWER(tool_name) LIKE $1"
        try:
            async with self.pool.acquire() as conn:
                count = await conn.fetchval(query, name_filter)
            log.info(f"Total MCP tool count for search '{search_value}': {count}.")
            return count
        except Exception as e:
            log.error(f"Error getting total MCP tool count: {e}")
            return 0

    async def update_mcp_tool_record(self, tool_data: Dict[str, Any], tool_id: str) -> bool:
        """
        Updates an MCP tool (server definition) record by its ID.

        Args:
            tool_data (Dict[str, Any]): A dictionary containing the fields to update and their new values.
                                        Must include 'updated_on' timestamp.
                                        'mcp_config' should be a Python dict, will be JSON dumped.
            tool_id (str): The ID of the MCP tool record to update.

        Returns:
            bool: True if the record was updated successfully, False otherwise.
        """
        # Prepare data for update, ensuring mcp_config is dumped if present
        update_fields = []
        values = []
        param_idx = 1

        for key, value in tool_data.items():
            if key == "mcp_config":
                update_fields.append(f"mcp_config = ${param_idx}")
                values.append(json.dumps(value))
            else:
                update_fields.append(f"{key} = ${param_idx}")
                values.append(value)
            param_idx += 1
        
        query = f"UPDATE {self.table_name} SET {', '.join(update_fields)} WHERE tool_id = ${param_idx}"
        
        try:
            async with self.pool.acquire() as conn:
                result = await conn.execute(query, *values, tool_id)
            if result != "UPDATE 0":
                log.info(f"MCP tool record '{tool_id}' updated successfully.")
                return True
            else:
                log.warning(f"MCP tool record '{tool_id}' not found, no update performed.")
                return False
        except Exception as e:
            log.error(f"Error updating MCP tool record '{tool_id}': {e}")
            return False

    async def delete_mcp_tool_record(self, tool_id: str) -> bool:
        """
        Deletes an MCP tool (server definition) record from the mcp_tool_table by its ID.

        Args:
            tool_id (str): The ID of the MCP tool record to delete.

        Returns:
            bool: True if the record was deleted successfully, False otherwise.
        """
        delete_query = f"DELETE FROM {self.table_name} WHERE tool_id = $1"
        try:
            async with self.pool.acquire() as conn:
                result = await conn.execute(delete_query, tool_id)
            if result != "DELETE 0":
                log.info(f"MCP tool record '{tool_id}' deleted successfully from '{self.table_name}'.")
                return True
            else:
                log.warning(f"MCP tool record '{tool_id}' not found in '{self.table_name}', no deletion performed.")
                return False
        except asyncpg.ForeignKeyViolationError as e:
            log.error(f"Cannot delete MCP tool '{tool_id}' from '{self.table_name}' due to foreign key constraint: {e}")
            return False
        except Exception as e:
            log.error(f"Error deleting MCP tool record '{tool_id}': {e}")
            return False

class AgentRepository(BaseRepository):
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
                created_by TEXT
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
            
    async def get_agents_details_for_chat_records(self) -> List[Dict[str, Any]]:
        """
        Retrieves basic agent details (ID, name, type) for chat purposes.

        Returns:
            List[Dict[str, Any]]: A list of dictionaries, each containing
                                  'agentic_application_id', 'agentic_application_name',
                                  and 'agentic_application_type'.
        """
        query = f"""
            SELECT agentic_application_id, agentic_application_name, agentic_application_type
            FROM {self.table_name}
        """
        try:
            async with self.pool.acquire() as conn:
                rows = await conn.fetch(query)
            log.info(f"Retrieved {len(rows)} agent chat detail records from '{self.table_name}'.")
            return [dict(row) for row in rows]
        except Exception as e:
            log.error(f"Error retrieving agent chat detail records: {e}")
            return []
    async def get_agent_record(self, agentic_application_id: Optional[str] = None, agentic_application_name: Optional[str] = None, agentic_application_type: Optional[str] = None, created_by: Optional[str] = None) -> Dict[str, Any] | None:
        """
        Retrieves a single agent record by ID, name, type, or creator.

        Args:
            agentic_application_id (Optional[str]): The ID of the agent.
            agentic_application_name (Optional[str]): The name of the agent.
            agentic_application_type (Optional[str]): The type of the agent.
            created_by (Optional[str]): The creator's email ID.

        Returns:
            Dict[str, Any] | None: A dictionary representing the agent record, or None if not found.
        """
        query = f"SELECT * FROM {self.table_name}"
        where_clauses = []
        params = []

        filters = {
            "agentic_application_id": agentic_application_id,
            "agentic_application_name": agentic_application_name,
            "created_by": created_by,
            "agentic_application_type": agentic_application_type
        }

        for idx, (field, value) in enumerate(((f for f in filters.items() if f[1] not in (None, ""))), start=1):
            where_clauses.append(f"{field} = ${idx}")
            params.append(value)

        if where_clauses:
            query += " WHERE " + " AND ".join(where_clauses)
        else:
            log.warning("No filter criteria provided to get_agent_record.")
            return None

        try:
            async with self.pool.acquire() as conn:
                rows = await conn.fetch(query, *params)

            results_as_dicts = [dict(row) for row in rows]

            log.info(f"Retrieved {len(results_as_dicts)} agent records from '{self.table_name}'.")
            return results_as_dicts

        except Exception as e:
            log.error(f"Error retrieving agent record '{agentic_application_id or agentic_application_name}': {e}")
            return None

class ToolRepository(BaseRepository):
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
                created_by TEXT
                
                
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
    async def get_tool_record(self, tool_id: Optional[str] = None, tool_name: Optional[str] = None) -> Dict[str, Any] | None:
        """
        Retrieves a single tool record by its ID or name.

        Args:
            tool_id (Optional[str]): The ID of the tool.
            tool_name (Optional[str]): The name of the tool.

        Returns:
            Dict[str, Any] | None: A dictionary representing the tool record, or None if not found.
        """
        query = f"SELECT * FROM {self.table_name} WHERE "
        params = []
        if tool_id:
            query += "tool_id = $1"
            params.append(tool_id)
        elif tool_name:
            query += "tool_name = $1"
            params.append(tool_name)
        else:
            log.warning("No tool_id or tool_name provided to get_tool_record.")
            return None

        try:
            async with self.pool.acquire() as conn:
                rows = await conn.fetch(query, *params)
            if rows:
                log.info(f"Tool record '{tool_id or tool_name}' retrieved successfully.")
                return [dict(row) for row in rows]
            else:
                log.info(f"Tool record '{tool_id or tool_name}' not found.")
                return None
        except Exception as e:
            log.error(f"Error retrieving tool record '{tool_id or tool_name}': {e}")
            return None

    async def get_all_tool_records(self) -> List[Dict[str, Any]]:
        """
        Retrieves all tool records.

        Returns:
            List[Dict[str, Any]]: A list of dictionaries, each representing a tool record.
        """
        query = f"SELECT * FROM {self.table_name} ORDER BY created_on DESC"
        try:
            async with self.pool.acquire() as conn:
                rows = await conn.fetch(query)
            log.info(f"Retrieved {len(rows)} tool records from '{self.table_name}'.")
            return [dict(row) for row in rows]
        except Exception as e:
            log.error(f"Error retrieving all tool records: {e}")
            return []


# --- ChatHistoryRepository ---
# --- CACHE NOT IMPLEMENTED FOR THIS CLASS ---
class ChatHistoryRepository(BaseRepository):
    """
    Repository for chat history. Handles direct database interactions with
    dynamically named chat tables and the shared checkpoint tables.
    """

    def __init__(self, pool: asyncpg.Pool):
        """
        Initializes the ChatHistoryRepository.

        Args:
            pool (asyncpg.Pool): The asyncpg connection pool.
        """
        # We pass a empty table_name to super, as this repo handles multiple tables.
        super().__init__(pool, table_name="")
        self.DB_URL = os.getenv("POSTGRESQL_DATABASE_URL")  # Ensure this is correctly loaded
        self.checkpoints_table = "checkpoints"
        self.checkpoint_blobs_table = "checkpoint_blobs"
        self.checkpoint_writes_table = "checkpoint_writes"

    async def create_chat_history_table(self, table_name: str):
        """
        Creates a dedicated chat history table if it doesn't exist.

        Args:
            table_name (str): The specific name of the table to create.
        """
        create_statement = f"""
        CREATE TABLE IF NOT EXISTS {table_name} (
            session_id TEXT,
            start_timestamp TIMESTAMP,
            end_timestamp TIMESTAMP,
            human_message TEXT,
            ai_message TEXT,
            PRIMARY KEY (session_id, end_timestamp)
        );
        """
        try:
            async with self.pool.acquire() as conn:
                await conn.execute(create_statement)
            log.info(f"Table '{table_name}' created successfully or already exists.")
        except Exception as e:
            log.error(f"Error creating table '{table_name}': {e}")
            raise

    async def insert_chat_record(
        self,
        table_name: str,
        session_id: str,
        start_timestamp: str,
        end_timestamp: str,
        human_message: str,
        ai_message: str
    ):
        """
        Inserts a new chat message pair into a specified table.

        Args:
            table_name (str): The table to insert into.
            (all other args are data for the record)
        """
        insert_statement = f"""
        INSERT INTO {table_name} (
            session_id, start_timestamp, end_timestamp, human_message, ai_message
        ) VALUES ($1, $2, $3, $4, $5)
        """
        try:
            async with self.pool.acquire() as conn:
                await conn.execute(
                    insert_statement,
                    session_id,
                    start_timestamp,
                    end_timestamp,
                    human_message,
                    ai_message
                )
            log.info(f"Chat history inserted into '{table_name}' for session '{session_id}'.")
        except Exception as e:
            log.error(f"Failed to insert chat history into '{table_name}': {e}")
            raise

    async def create_agent_conversation_summary_table(self):
        """
        Creates a dedicated agent summary table if it doesn't exist.

        Args:
            agentic_application_id (str): The ID of the agent application.
        """
        table_name = "agent_conversation_summary_table"
        create_statement = f"""
        CREATE TABLE IF NOT EXISTS {table_name} (
            agentic_application_id TEXT,
            session_id TEXT,
            summary TEXT,
            preference TEXT,
            created_on TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(agentic_application_id, session_id)
        );
        """
        try:
            async with self.pool.acquire() as conn:
                await conn.execute(create_statement)
            log.info(f"Table '{table_name}' created successfully or already exists.")
        except Exception as e:
            log.error(f"Error creating table '{table_name}': {e}")
            raise

    async def insert_preference_for_agent_conversation(
        self, agentic_application_id: str, session_id: str, preference: str
        ):
        """ Inserts or updates the preference for a specific agent conversation.
        """
        table_name = "agent_conversation_summary_table"
        insert_statement = f"""
        INSERT INTO {table_name} (agentic_application_id, session_id, preference)
        VALUES ($1, $2, $3)
        ON CONFLICT (agentic_application_id, session_id)
        DO UPDATE SET preference = $3
        """
        try:
            async with self.pool.acquire() as conn:
                await conn.execute(insert_statement, agentic_application_id, session_id, preference)
            log.info(f"Inserted/Updated preference for session '{session_id}' in table '{table_name}'.")
        except Exception as e:
            log.error(f"Failed to insert/update preference in '{table_name}': {e}")
            raise

    async def get_agent_conversation_summary_with_preference(
        self, agentic_application_id: str, session_id: str
    ) -> str | None:
        """
        Retrieves the conversation summary and preference for a specific agent and session.

        Args:
            agentic_application_id (str): The ID of the agent application.
            session_id (str): The ID of the session.

        Returns:
            dict: A dictionary representing the conversation summary and preference, or None if not found.
        """
        table_name = "agent_conversation_summary_table"
        try:
            async with self.pool.acquire() as conn:
                query = f"""
                SELECT summary, preference
                FROM {table_name}
                WHERE agentic_application_id = '{agentic_application_id}' AND session_id = '{session_id}'
                """
                summary = await conn.fetchrow(query)
                if summary:
                    log.info(f"Retrieved agent conversation summary for session '{session_id}'.")
                    return dict(summary)
                else:
                    log.warning(f"No agent conversation summary found for session '{session_id}'.")
                    return None
        except Exception as e:
            log.error(f"Failed to retrieve agent conversation summary from '{table_name}': {e}")
            return None

    async def get_chat_records_by_session_prefix(self, table_name: str, session_id_prefix: str) -> List[Dict[str, Any]]:
        """
        Retrieves chat history records from a specific table where session_id matches a prefix.

        Args:
            table_name (str): The table to query.
            session_id_prefix (str): The prefix for the session_id (e.g., 'user@example.com_%').

        Returns:
            A list of chat history records, or an empty list if not found or on error.
        """
        try:
            async with self.pool.acquire() as conn:
                table_exists = await conn.fetchval(
                    "SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = $1)",
                    table_name
                )
                if not table_exists:
                    log.warning(f"Table '{table_name}' does not exist. Cannot retrieve old chats.")
                    return []

                query = f"""
                SELECT * FROM {table_name}
                WHERE session_id LIKE $1
                ORDER BY end_timestamp ASC; -- Order by timestamp to get chronological history
                """
                records = await conn.fetch(query, session_id_prefix)
                log.info(f"Retrieved {len(records)} records from '{table_name}' for session prefix '{session_id_prefix}'.")
                return [dict(row) for row in records]
        except Exception as e:
            log.error(f"Failed to retrieve chat records by session prefix from '{table_name}': {e}")
            return []

    async def update_agent_conversation_summary(
        self, agentic_application_id: str, session_id: str, summary: str):
        """
        Updates the conversation summary for a specific agent and session.
        Args:
            agentic_application_id (str): The ID of the agent application.
            session_id (str): The ID of the session.
            summary (str): The new summary to set.
        """
        table_name = "agent_conversation_summary_table"
        update_statement = f"""
        UPDATE {table_name}
        SET summary = $1, created_on = CURRENT_TIMESTAMP
        WHERE agentic_application_id = $2 AND session_id = $3
        """
        try:
            async with self.pool.acquire() as conn:
                result = await conn.execute(update_statement, summary, agentic_application_id, session_id)
                if result != "UPDATE 0":
                    log.info(f"Updated agent conversation summary for session '{session_id}' in table '{table_name}'.")
                else:
                    log.warning(f"No agent conversation summary found for session '{session_id}', no update performed.")
                    return True
        except Exception as e:
            log.error(f"Failed to update agent conversation summary in '{table_name}': {e}")
            raise 

    async def get_chat_records_by_session_from_long_term_memory(
        self, table_name: str, session_id: str, limit: int
    ) -> List[Dict[str, Any]]:
        """
        Retrieves recent chat history records for a given session from a specific table.

        Args:
            table_name (str): The table to query.
            session_id (str): The ID of the chat session.
            limit (int): The maximum number of conversation pairs to retrieve.

        Returns:
            A list of chat history records, or an empty list if not found or on error.
        """
        try:
            async with self.pool.acquire() as conn:
                table_exists = await conn.fetchval(
                    "SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = $1)",
                    table_name
                )
                if not table_exists:
                    log.warning(f"Table '{table_name}' does not exist. Cannot retrieve memory.")
                    return []

                query = f"""
                SELECT session_id, start_timestamp, end_timestamp, human_message, ai_message
                FROM {table_name}
                WHERE session_id = $1
                ORDER BY end_timestamp DESC
                LIMIT $2
                """
                records = await conn.fetch(query, session_id, limit)
                log.info(f"Retrieved {len(records)} records from '{table_name}' for session '{session_id}'.")
                return [dict(row) for row in records]
        except Exception as e:
            log.error(f"Failed to retrieve chat records from '{table_name}': {e}")
            return []

    async def delete_session_transactional(self, chat_table_name: str, thread_id: str, session_id: str) -> int:
        """
        Deletes all data for a session (checkpoints and chat history) in a single transaction.

        Args:
            chat_table_name (str): The name of the specific chat history table.
            thread_id (str): The thread_id used in checkpoint tables.
            session_id (str): The session_id used in the chat history table.

        Returns:
            int: The number of rows deleted from the chat history table.
        
        Raises:
            Exception: Propagates any exception that occurs during the transaction.
        """
        internal_thread = f"inside{thread_id}"
        chat_rows_deleted = 0
        async with self.pool.acquire() as conn:
            async with conn.transaction():
                log.info(f"Starting transactional delete for thread_id: {thread_id}")
                await conn.execute(f"DELETE FROM {self.checkpoints_table} WHERE thread_id = $1 OR thread_id = $2", thread_id, internal_thread)
                await conn.execute(f"DELETE FROM {self.checkpoint_blobs_table} WHERE thread_id = $1 OR thread_id = $2", thread_id, internal_thread)
                await conn.execute(f"DELETE FROM {self.checkpoint_writes_table} WHERE thread_id = $1 OR thread_id = $2", thread_id, internal_thread)
                log.info(f"Deleted records from checkpoint tables for thread_id: {thread_id}")

                try:
                    result = await conn.execute(f"DELETE FROM {chat_table_name} WHERE session_id = $1", session_id)
                    chat_rows_deleted = int(result.split()[-1])
                    log.info(f"Deleted {chat_rows_deleted} rows from chat table '{chat_table_name}'.")
                except asyncpg.exceptions.UndefinedTableError:
                    log.warning(f"Chat table '{chat_table_name}' not found. Skipping deletion.")
                    chat_rows_deleted = 0
        return chat_rows_deleted

    async def delete_session_transactional_internal(self, internal_thread: str) -> int:
        """
        deletes all data for a session (checkpoints) in a single transaction.
        This method is used internally to delete checkpoints without affecting chat history.
        Args:
            internal_thread (str): The thread_id used in checkpoint tables.
        Returns:
            int: Always returns 0, as this method does not delete chat history rows.
        Raises:
            Exception: Propagates any exception that occurs during the transaction.
        """
        async with self.pool.acquire() as conn:
            async with conn.transaction():
                log.info(f"Starting transactional delete for thread_id: {internal_thread}")
                await conn.execute(f"DELETE FROM {self.checkpoints_table} WHERE thread_id = $1",internal_thread)
                await conn.execute(f"DELETE FROM {self.checkpoint_blobs_table} WHERE thread_id = $1", internal_thread)
                await conn.execute(f"DELETE FROM {self.checkpoint_writes_table} WHERE thread_id = $1",internal_thread)
                log.info(f"Deleted records from checkpoint tables for thread_id: {internal_thread}")

        return True  # No chat rows to delete in this internal method, as it only handles checkpoints.

    async def get_checkpointer_context_manager(self):
        """
        Returns an asynchronous context manager for LangGraph's PostgresSaver.
        This allows inference services to use 'async with chat_history_repository.get_checkpointer_context_manager() as checkpointer:'
        """
        if not self.DB_URL:
            raise ValueError("POSTGRESQL_DATABASE_URL (for checkpointer) is not configured in environment variables.")

        # AsyncPostgresSaver is itself an async context manager, so we just return its instance.
        # The caller will then use 'async with' on this returned instance.
        return AsyncPostgresSaver.from_conn_string(self.DB_URL)

    async def get_store_context_manager(self):
        """
        Returns an asynchronous context manager for LangGraph's PostgresStore.
        This allows inference services to use 'async with chat_history_repository.get_store_context_manager() as store:'
        """
        if not self.DB_URL:
            raise ValueError("POSTGRESQL_DATABASE_URL (for store) is not configured in environment variables.")

        # AsyncPostgresStore is itself an async context manager, so we just return its instance.
        # The caller will then use 'async with' on this returned instance.
        return AsyncPostgresStore.from_conn_string(self.DB_URL)

    async def get_all_thread_ids_from_checkpoints(self) -> List[Dict[str, str]]:
        """
        Retrieves all unique chat session thread_ids from the checkpoints table.
        """
        try:
            async with self.pool.acquire() as conn:
                records = await conn.fetch(f"SELECT DISTINCT thread_id FROM {self.checkpoints_table};")
                log.info(f"Retrieved {len(records)} unique chat sessions from the database.")
                return [dict(record) for record in records]
        except Exception as e:
            log.error(f"An error occurred while retrieving all chat sessions: {e}")
            return []

    async def get_latest_message_record(
        self, table_name: str, session_id: str, message_column: str
    ) -> Dict[str, Any] | None:
        """
        Retrieves the latest message record (content and timestamp) for a given session and message type.

        Args:
            table_name (str): The name of the chat history table.
            session_id (str): The session ID.
            message_column (str): The column to retrieve ('human_message' or 'ai_message').

        Returns:
            Dict[str, Any] | None: A dictionary with 'message_content' and 'end_timestamp', or None if not found.
        """
        try:
            async with self.pool.acquire() as conn:
                table_exists = await conn.fetchval(
                    "SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = $1)",
                    table_name
                )
                if not table_exists:
                    log.warning(f"Table '{table_name}' does not exist. Cannot retrieve latest message.")
                    return None

                query = f"""
                SELECT {message_column} AS message_content, end_timestamp
                FROM {table_name}
                WHERE session_id = $1
                ORDER BY end_timestamp DESC
                LIMIT 1
                """
                record = await conn.fetchrow(query, session_id)
                return dict(record) if record else None
        except Exception as e:
            log.error(f"Error getting latest message record from '{table_name}': {e}")
            return None

    async def update_message_tag_record(
        self,
        table_name: str,
        session_id: str,
        message_column: str,
        updated_message_content: str,
        end_timestamp: datetime
    ) -> bool:
        """
        Updates a specific message record in a chat history table.

        Args:
            table_name (str): The name of the chat history table.
            session_id (str): The session ID of the message.
            message_column (str): The column to update ('human_message' or 'ai_message').
            updated_message_content (str): The new content for the message.
            end_timestamp (datetime): The timestamp to identify the specific message.

        Returns:
            bool: True if the update was successful, False otherwise.
        """
        update_query = f"""
        UPDATE {table_name}
        SET {message_column} = $1
        WHERE session_id = $2 AND end_timestamp = $3;
        """
        try:
            async with self.pool.acquire() as conn:
                result = await conn.execute(update_query, updated_message_content, session_id, end_timestamp)
            return result != "UPDATE 0"
        except Exception as e:
            log.error(f"Error updating message tag record in '{table_name}': {e}")
            return False
        
    async def fetch_user_query_from_chat_table(self, user_email:str, chat_table_name: str):
        """
        Fetches only the user query from the chat table for a given user_email.

        Args:
            user_email (str): The email of the user to filter the chat records.
            chat_table_name (str): The name of the chat table to query.

        Returns:
            
        """
        def get_unique_messages(messages, similarity_threshold=0.5):
            """
            Filters a list of messages to return only those that are not too similar to each other.
            The `similarity_threshold` is a float from 0 to 1.
            """
            if not messages:
                return []

            unique_messages = []
            # Loop through each message in the original list
            for new_message in messages:
                is_similar = False
                # Compare the new message to all the messages we've already deemed unique
                for existing_message in unique_messages:
                    # Use SequenceMatcher to get a similarity ratio (e.g., 0.95)
                    similarity = difflib.SequenceMatcher(None, new_message.lower(), existing_message.lower()).ratio()
                    if similarity >= similarity_threshold:
                        is_similar = True
                        break  # Found a similar message, no need to check further
                
                # If no similar message was found, add it to our unique list
                if not is_similar:
                    unique_messages.append(new_message)
                    
            return unique_messages

        try:
            async with self.pool.acquire() as conn:
                query = f"""
                SELECT DISTINCT human_message
                FROM {chat_table_name}
                WHERE session_id like $1
                """
                user_history = await conn.fetch(query, f"{user_email}_%")

                query1 = f"""
                SELECT DISTINCT human_message
                FROM {chat_table_name}
                WHERE session_id not like $1;
                """
                agent_history = await conn.fetch(query1, f"{user_email}_%")

                queries = {
                    "user_history": [row['human_message'] for row in user_history],
                    "agent_history": [row['human_message'] for row in agent_history],
                }
                all_message = queries["user_history"] + queries["agent_history"]
                query_library = get_unique_messages(all_message)
                queries["query_library"] = query_library

                return queries
        except Exception as e:
            log.error(f"Error fetching user queries from '{chat_table_name}': {e}")
            return {}




# --- FeedbackLearningRepository ---
# --- CACHE NOT IMPLEMENTED FOR THIS CLASS ---
class FeedbackLearningRepository(BaseRepository):
    """
    Repository for feedback data. Handles direct database interactions for
    'feedback_response' and 'agent_feedback' tables.
    """

    def __init__(self, pool: asyncpg.Pool,
                 feedback_table_name: str = "feedback_response",
                 agent_feedback_table_name: str = "agent_feedback"):
        super().__init__(pool, table_name=feedback_table_name)
        self.feedback_table_name = feedback_table_name
        self.agent_feedback_table_name = agent_feedback_table_name


    async def create_tables_if_not_exists(self):
        """
        Creates the 'feedback_response' and 'agent_feedback' tables if they don't exist.
        If feedback_response table exists, alters it to add the 'lesson' field if missing.
        """
        create_feedback_table_query = f"""
        CREATE TABLE IF NOT EXISTS {self.feedback_table_name} (
            response_id TEXT PRIMARY KEY,
            query TEXT,
            old_final_response TEXT,
            old_steps TEXT,
            old_response TEXT,
            feedback TEXT,
            new_final_response TEXT,
            new_steps TEXT,
            new_response TEXT,
            lesson TEXT,
            approved BOOLEAN DEFAULT FALSE,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        """
        create_agent_feedback_table_query = f"""
        CREATE TABLE IF NOT EXISTS {self.agent_feedback_table_name} (
            agent_id TEXT,
            response_id TEXT,
            PRIMARY KEY (agent_id, response_id),
            FOREIGN KEY (response_id) REFERENCES {self.feedback_table_name}(response_id) ON DELETE CASCADE
        );
        """
        
        check_column_exists_query = f"""
        SELECT EXISTS (
            SELECT 1
            FROM information_schema.columns
            WHERE table_name = '{self.feedback_table_name}'
            AND column_name = 'lesson'
        );
        """
        
        alter_table_query = f"""
        ALTER TABLE {self.feedback_table_name}
        ADD COLUMN IF NOT EXISTS lesson TEXT;
        """
        
        try:
            async with self.pool.acquire() as conn:
                # First create tables if they don't exist
                await conn.execute(create_feedback_table_query)
                await conn.execute(create_agent_feedback_table_query)
                
                # Check if the feedback_table exists and if it's missing the lesson column
                table_exists = await conn.fetchval(
                    f"SELECT EXISTS(SELECT 1 FROM information_schema.tables WHERE table_name = '{self.feedback_table_name}')"
                )
                
                if table_exists:
                    # If table exists, check if lesson column exists and add it if missing
                    await conn.execute(alter_table_query)
                    log.info(f"Added 'lesson' column to {self.feedback_table_name} table if it was missing.")
                    
            log.info("Feedback storage tables created successfully or already exist.")
        except Exception as e:
            log.error(f"Error creating feedback storage tables: {e}")
            raise # Re-raise for service to handle

    async def insert_feedback_record(self, response_id: str, query: str, old_final_response: str, old_steps: str, feedback: str, new_final_response: str, new_steps: str, lesson: str, approved: bool = False) -> bool:
        """
        Inserts a new feedback response record.
        """
        insert_query = f"""
        INSERT INTO {self.feedback_table_name} (
            response_id, query, old_final_response, old_steps, feedback, new_final_response, new_steps, approved, lesson
        ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9);
        """
        try:
            async with self.pool.acquire() as conn:
                await conn.execute(insert_query, response_id, query, old_final_response, old_steps, feedback, new_final_response, new_steps, approved, lesson)
            return True
        except Exception as e:
            log.error(f"Error inserting feedback record for response_id '{response_id}': {e}")
            return False

    async def insert_agent_feedback_mapping(self, agent_id: str, response_id: str) -> bool:
        """
        Inserts a mapping between an agent and a feedback response.
        """
        insert_query = f"""
        INSERT INTO {self.agent_feedback_table_name} (agent_id, response_id)
        VALUES ($1, $2);
        """
        try:
            async with self.pool.acquire() as conn:
                await conn.execute(insert_query, agent_id, response_id)
            return True
        except Exception as e:
            log.error(f"Error inserting agent feedback mapping for agent_id '{agent_id}', response_id '{response_id}': {e}")
            return False

    async def get_approved_feedback_records(self, agent_id: str) -> List[Dict[str, Any]]:
        """
        Retrieves approved feedback records for a specific agent.
        """
        select_query = f"""
        SELECT fr.response_id, fr.query, fr.old_final_response, fr.old_steps, fr.feedback, fr.new_final_response, fr.new_steps, fr.lesson, fr.approved, fr.created_at FROM {self.feedback_table_name} fr
        JOIN {self.agent_feedback_table_name} af ON fr.response_id = af.response_id
        WHERE af.agent_id = $1 AND fr.approved = TRUE;
        """
        try:
            async with self.pool.acquire() as conn:
                rows = await conn.fetch(select_query, agent_id)
            return [dict(row) for row in rows]
        except Exception as e:
            log.error(f"Error retrieving approved feedback records for agent '{agent_id}': {e}")
            return []

    async def get_all_feedback_records_by_agent(self, agent_id: str) -> List[Dict[str, Any]]:
        """
        Retrieves all feedback records (regardless of approval status) for a given agent.
        """
        select_query = f"""
        SELECT af.response_id, fr.feedback, fr.approved
        FROM {self.feedback_table_name} fr
        JOIN {self.agent_feedback_table_name} af ON fr.response_id = af.response_id
        WHERE af.agent_id = $1;
        """
        try:
            async with self.pool.acquire() as conn:
                rows = await conn.fetch(select_query, agent_id)
            return [dict(row) for row in rows]
        except Exception as e:
            log.error(f"Error retrieving all feedback records for agent '{agent_id}': {e}")
            return []

    async def get_feedback_record_by_response_id(self, response_id: str) -> List[Dict[str, Any]]:
        """
        Retrieves a single feedback record by its response_id.
        """
        select_query = f"""
        SELECT fr.response_id, fr.query, fr.old_final_response, fr.old_steps, fr.feedback, fr.new_final_response, fr.new_steps, fr.lesson, fr.approved, fr.created_at, af.agent_id FROM {self.feedback_table_name} fr
        JOIN {self.agent_feedback_table_name} af ON fr.response_id = af.response_id
        WHERE fr.response_id = $1;
        """
        try:
            async with self.pool.acquire() as conn:
                rows = await conn.fetch(select_query, response_id)
            return [dict(row) for row in rows]
        except Exception as e:
            log.error(f"Error retrieving feedback record for response_id '{response_id}': {e}")
            return []

    async def get_distinct_agents_with_feedback(self) -> List[str]:
        """
        Retrieves a list of distinct agent_ids that have associated feedback.
        """
        select_query = f"SELECT DISTINCT agent_id FROM {self.agent_feedback_table_name};"
        try:
            async with self.pool.acquire() as conn:
                rows = await conn.fetch(select_query)
            return [row['agent_id'] for row in rows]
        except Exception as e:
            log.error(f"Error retrieving distinct agents with feedback: {e}")
            return []

    async def update_feedback_record(self, response_id: str, update_data: Dict[str, Any]) -> bool:
        """
        Updates fields in a feedback_response record.
        `update_data` should be a dictionary of column_name: new_value.
        """
        if not update_data:
            return False

        set_clause = ', '.join([f"{key} = ${i+1}" for i, key in enumerate(update_data.keys())])
        values = list(update_data.values())
        values.append(response_id) # response_id is the last parameter

        update_query = f"""
        UPDATE {self.feedback_table_name}
        SET {set_clause}
        WHERE response_id = ${len(values)};
        """
        try:
            async with self.pool.acquire() as conn:
                result = await conn.execute(update_query, *values)
            return result != "UPDATE 0"
        except Exception as e:
            log.error(f"Error updating feedback record for response_id '{response_id}': {e}")
            return False
        
    async def migrate_agent_ids_to_hyphens(self) -> Dict[str, Any]:
        """
        Migrates agent_id values in the agent_feedback table, replacing all underscores (_) with hyphens (-).
        This is useful for consistency if agent IDs are stored with hyphens elsewhere.

        Returns:
            Dict[str, Any]: A dictionary indicating the status of the migration.
        """
        log.info(f"Starting migration of agent_id underscores to hyphens in '{self.agent_feedback_table_name}'.")
        
        # The REPLACE function will replace ALL occurrences of '_' with '-'
        # The WHERE clause ensures we only attempt to update rows that actually contain an underscore.
        update_query = f"""
        UPDATE {self.agent_feedback_table_name}
        SET agent_id = REPLACE(agent_id, '_', '-')
        WHERE agent_id LIKE '%\\_%' ESCAPE '\\';
        """

        try:
            async with self.pool.acquire() as conn:
                # Execute the update query
                result = await conn.execute(update_query)
                
                # The result string will be like "UPDATE N" where N is the number of rows updated
                rows_updated = int(result.split()[-1])
                
                log.info(f"Migration complete for '{self.agent_feedback_table_name}'. {rows_updated} rows updated.")
                return {"status": "success", "message": f"Successfully migrated {rows_updated} agent_id records."}
        except Exception as e:
            log.error(f"Error during agent_id migration in '{self.agent_feedback_table_name}': {e}", exc_info=True)
            return {"status": "error", "message": f"Failed to migrate agent_id records: {e}"}



# --- EvaluationDataRepository ---
# --- CACHE NOT IMPLEMENTED FOR THIS CLASS ---
class EvaluationDataRepository(BaseRepository):
    """
    Repository for 'evaluation_data' table. Handles direct database interactions.
    """

    def __init__(self, pool: asyncpg.Pool, table_name: str = "evaluation_data"):
        super().__init__(pool, table_name)


    async def create_table_if_not_exists(self):
        """Creates the 'evaluation_data' table if it does not exist."""
        create_table_query = f"""
        CREATE TABLE IF NOT EXISTS {self.table_name} (
            id SERIAL PRIMARY KEY,
            time_stamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            session_id TEXT,
            query TEXT,
            response TEXT,
            model_used TEXT,
            agent_id TEXT,
            agent_name TEXT,
            agent_type TEXT,
            agent_goal TEXT,
            workflow_description TEXT,
            tool_prompt TEXT,
            steps JSONB,
            executor_messages JSONB,
            evaluation_status TEXT DEFAULT 'unprocessed'
        );
        """
        try:
            async with self.pool.acquire() as conn:
                await conn.execute(create_table_query)
            log.info(f"Table '{self.table_name}' created successfully or already exists.")
        except Exception as e:
            log.error(f"Error creating table '{self.table_name}': {e}")
            raise

    async def insert_evaluation_record(self, data: Dict[str, Any]) -> bool:
        """
        Inserts a new evaluation data record.
        """
        insert_query = f"""
        INSERT INTO {self.table_name} (
            session_id, query, response, model_used,
            agent_id, agent_name, agent_type, agent_goal,
            workflow_description, tool_prompt, steps, executor_messages
        ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12);
        """
        try:
            async with self.pool.acquire() as conn:
                await conn.execute(
                    insert_query,
                    data.get("session_id"), data.get("query"), data.get("response"), data.get("model_used"),
                    data.get("agent_id"), data.get("agent_name"), data.get("agent_type"), data.get("agent_goal"),
                    data.get("workflow_description"), data.get("tool_prompt"),
                    data.get("steps"),
                    data.get("executor_messages")
                )
            return True
        except Exception as e:
            log.error(f"Error inserting evaluation record: {e}")
            return False

    async def get_unprocessed_record(self) -> Dict[str, Any] | None:
        """
        Retrieves the next unprocessed evaluation record.
        """
        query = f"""
            SELECT
                id, query, response, agent_goal, agent_name,
                workflow_description, steps, executor_messages, tool_prompt, model_used,
                session_id, agent_id
            FROM {self.table_name}
            WHERE evaluation_status = 'unprocessed'
            ORDER BY time_stamp
            LIMIT 1;
        """
        try:
            async with self.pool.acquire() as conn:
                row = await conn.fetchrow(query)
            return dict(row) if row else None
        except Exception as e:
            log.error(f"Error fetching unprocessed evaluation record: {e}")
            return None

    async def update_status(self, evaluation_id: int, status: str) -> bool:
        """
        Updates the processing status of an evaluation record.
        """
        update_query = f"""
        UPDATE {self.table_name}
        SET evaluation_status = $1
        WHERE id = $2;
        """
        try:
            async with self.pool.acquire() as conn:
                result = await conn.execute(update_query, status, evaluation_id)
            return result != "UPDATE 0"
        except Exception as e:
            log.error(f"Error updating evaluation status for ID {evaluation_id}: {e}")
            return False

    async def get_records_by_agent_names(self, agent_names: Optional[List[str]] = None, page: int = 1, limit: int = 10) -> List[Dict[str, Any]]:
        """
        Retrieves evaluation data records, optionally filtered by agent names, with pagination.
        """
        offset = (page - 1) * limit
        query = f"""
            SELECT session_id, query, response, model_used, agent_id, agent_name, agent_type
            FROM {self.table_name}
        """
        params = []
        if agent_names:
            query += " WHERE agent_name = ANY($1::text[])"
            params.append(agent_names)
        
        query += f" ORDER BY id DESC LIMIT ${len(params) + 1} OFFSET ${len(params) + 2};"
        params.extend([limit, offset])

        try:
            async with self.pool.acquire() as conn:
                rows = await conn.fetch(query, *params)
            return [dict(row) for row in rows]
        except Exception as e:
            log.error(f"Error fetching evaluation data records: {e}")
            return []



# --- ToolEvaluationMetricsRepository ---
# --- CACHE NOT IMPLEMENTED FOR THIS CLASS ---
class ToolEvaluationMetricsRepository(BaseRepository):
    """
    Repository for 'tool_evaluation_metrics' table. Handles direct database interactions.
    """

    def __init__(self, pool: asyncpg.Pool, table_name: str = "tool_evaluation_metrics"):
        super().__init__(pool, table_name)


    async def create_table_if_not_exists(self):
        """Creates the 'tool_evaluation_metrics' table if it does not exist."""
        create_table_query = f"""
        CREATE TABLE IF NOT EXISTS {self.table_name} (
            id SERIAL PRIMARY KEY,
            evaluation_id INTEGER REFERENCES evaluation_data(id) ON DELETE CASCADE,
            user_query TEXT,
            agent_response TEXT,
            model_used TEXT,
            tool_selection_accuracy REAL,
            tool_usage_efficiency REAL,
            tool_call_precision REAL,
            tool_call_success_rate REAL,
            tool_utilization_efficiency REAL,
            tool_utilization_efficiency_category TEXT,
            tool_selection_accuracy_justification TEXT,
            tool_usage_efficiency_justification TEXT,
            tool_call_precision_justification TEXT,
            model_used_for_evaluation TEXT,
            time_stamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        """
        try:
            async with self.pool.acquire() as conn:
                await conn.execute(create_table_query)
            log.info(f"Table '{self.table_name}' created successfully or already exists.")
        except Exception as e:
            log.error(f"Error creating table '{self.table_name}': {e}")
            raise

    async def insert_metrics_record(self, metrics_data: Dict[str, Any]) -> bool:
        """
        Inserts a new tool evaluation metrics record.
        """
        insert_query = f"""
        INSERT INTO {self.table_name} (
            evaluation_id, user_query, agent_response, model_used,
            tool_selection_accuracy, tool_usage_efficiency, tool_call_precision,
            tool_call_success_rate, tool_utilization_efficiency,
            tool_utilization_efficiency_category,
            tool_selection_accuracy_justification,
            tool_usage_efficiency_justification,
            tool_call_precision_justification,
            model_used_for_evaluation
        ) VALUES (
            $1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14
        );
        """
        try:
            async with self.pool.acquire() as conn:
                await conn.execute(
                    insert_query,
                    metrics_data.get("evaluation_id"), metrics_data.get("user_query"), metrics_data.get("agent_response"), metrics_data.get("model_used"),
                    metrics_data.get("tool_selection_accuracy"), metrics_data.get("tool_usage_efficiency"), metrics_data.get("tool_call_precision"),
                    metrics_data.get("tool_call_success_rate"), metrics_data.get("tool_utilization_efficiency"),
                    metrics_data.get("tool_utilization_efficiency_category"),
                    metrics_data.get("tool_selection_accuracy_justification"),
                    metrics_data.get("tool_usage_efficiency_justification"),
                    metrics_data.get("tool_call_precision_justification"),
                    metrics_data.get("model_used_for_evaluation")
                )
            return True
        except Exception as e:
            log.error(f"Error inserting tool evaluation metrics record: {e}")
            return False

    async def get_metrics_by_agent_names(self, agent_names: Optional[List[str]] = None, page: int = 1, limit: int = 10) -> List[Dict[str, Any]]:
        """
        Retrieves tool evaluation metrics records, optionally filtered by agent names, with pagination.
        """
        offset = (page - 1) * limit
        query = f"""
            SELECT tem.*
            FROM {self.table_name} tem
            JOIN evaluation_data ed ON tem.evaluation_id = ed.id
        """
        params = []
        if agent_names:
            query += " WHERE ed.agent_name = ANY($1::text[])"
            params.append(agent_names)
        
        query += f" ORDER BY tem.id DESC LIMIT ${len(params) + 1} OFFSET ${len(params) + 2};"
        params.extend([limit, offset])

        try:
            async with self.pool.acquire() as conn:
                rows = await conn.fetch(query, *params)
            return [dict(row) for row in rows]
        except Exception as e:
            log.error(f"Error fetching tool evaluation metrics records: {e}")
            return []



# --- AgentEvaluationMetricsRepository ---
# --- CACHE NOT IMPLEMENTED FOR THIS CLASS ---
class AgentEvaluationMetricsRepository(BaseRepository):
    """
    Repository for 'agent_evaluation_metrics' table. Handles direct database interactions.
    """

    def __init__(self, pool: asyncpg.Pool, table_name: str = "agent_evaluation_metrics"):
        super().__init__(pool, table_name)


    async def create_table_if_not_exists(self):
        """Creates the 'agent_evaluation_metrics' table if it does not exist."""
        create_table_query = f"""
        CREATE TABLE IF NOT EXISTS {self.table_name} (
            id SERIAL PRIMARY KEY,
            evaluation_id INTEGER REFERENCES evaluation_data(id) ON DELETE CASCADE,
            user_query TEXT,
            response TEXT,
            model_used TEXT,
            task_decomposition_efficiency REAL,
            task_decomposition_justification TEXT,
            reasoning_relevancy REAL,
            reasoning_relevancy_justification TEXT,
            reasoning_coherence REAL,
            reasoning_coherence_justification TEXT,
            answer_relevance REAL,
            answer_relevance_justification TEXT,
            groundedness REAL,
            groundedness_justification TEXT,
            response_fluency REAL,
            response_fluency_justification TEXT,
            response_coherence REAL,
            response_coherence_justification TEXT,
            efficiency_category TEXT,
            model_used_for_evaluation TEXT,
            time_stamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        """
        try:
            async with self.pool.acquire() as conn:
                await conn.execute(create_table_query)
            log.info(f"Table '{self.table_name}' created successfully or already exists.")
        except Exception as e:
            log.error(f"Error creating table '{self.table_name}': {e}")
            raise

    async def insert_metrics_record(self, metrics_data: Dict[str, Any]) -> bool:
        """
        Inserts a new agent evaluation metrics record into the database.
        """
        insert_query = f"""
        INSERT INTO {self.table_name} (
            evaluation_id, user_query, response, model_used,
            task_decomposition_efficiency, task_decomposition_justification,
            reasoning_relevancy, reasoning_relevancy_justification,
            reasoning_coherence, reasoning_coherence_justification,
            answer_relevance, answer_relevance_justification,
            groundedness, groundedness_justification,
            response_fluency, response_fluency_justification,
            response_coherence, response_coherence_justification,
            efficiency_category, model_used_for_evaluation
        ) VALUES (
            $1, $2, $3, $4, $5, $6, $7, $8, $9, $10,
            $11, $12, $13, $14, $15, $16, $17, $18,
            $19, $20
        );
        """
        try:
            async with self.pool.acquire() as conn:
                await conn.execute(
                    insert_query,
                    metrics_data.get("evaluation_id"), metrics_data.get("user_query"), metrics_data.get("response"), metrics_data.get("model_used"),
                    metrics_data.get("task_decomposition_efficiency"), metrics_data.get("task_decomposition_justification"),
                    metrics_data.get("reasoning_relevancy"), metrics_data.get("reasoning_relevancy_justification"),
                    metrics_data.get("reasoning_coherence"), metrics_data.get("reasoning_coherence_justification"),
                    metrics_data.get("answer_relevance"), metrics_data.get("answer_relevance_justification"),
                    metrics_data.get("groundedness"), metrics_data.get("groundedness_justification"),
                    metrics_data.get("response_fluency"), metrics_data.get("response_fluency_justification"),
                    metrics_data.get("response_coherence"), metrics_data.get("response_coherence_justification"),
                    metrics_data.get("efficiency_category"), metrics_data.get("model_used_for_evaluation")
                )
            return True
        except Exception as e:
            log.error(f"Error inserting agent evaluation metrics record: {e}", exc_info=True)
            return False

    async def get_metrics_by_agent_names(self, agent_names: Optional[List[str]] = None, page: int = 1, limit: int = 10) -> List[Dict[str, Any]]:
        """
        Retrieves agent evaluation metrics records, optionally filtered by agent names, with pagination.
        """
        offset = (page - 1) * limit
        query = f"""
            SELECT aem.*
            FROM {self.table_name} aem
            JOIN evaluation_data ed ON aem.evaluation_id = ed.id
        """
        params = []
        if agent_names:
            query += " WHERE ed.agent_name = ANY($1::text[])"
            params.append(agent_names)
        
        query += f" ORDER BY aem.id DESC LIMIT ${len(params) + 1} OFFSET ${len(params) + 2};"
        params.extend([limit, offset])

        try:
            async with self.pool.acquire() as conn:
                rows = await conn.fetch(query, *params)
            return [dict(row) for row in rows]
        except Exception as e:
            log.error(f"Error fetching agent evaluation metrics records: {e}")
            return []