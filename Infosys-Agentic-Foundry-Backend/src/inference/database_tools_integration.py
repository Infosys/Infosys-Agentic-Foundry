# © 2024-25 Infosys Limited, Bangalore, India. All Rights Reserved.
"""
Database Tools Integration for IAF Agent Inference (File-Based, Shared Approach)

This module provides auto-injection of database tools during agent inference.
Similar to how knowledgebase_retriever is auto-injected when an agent has
knowledge bases configured, this module auto-injects database tools when
an agent has database connections configured.

APPROACH (v4.0 - File-Based, SHARED/REUSABLE):
    - Schema and sample data are stored ONCE per database connection
    - Files are SHARED across ALL agents (reusable component)
    - Agent uses run_shell_command (cat) to read files during inference
    - Only `database_query_tool` is injected as a tool
    - NO automatic caching or refresh - files are managed manually

File Structure (SHARED):
    agent_workspaces/databases/{connection_name}/
    ├── schema.md       # Schema for the database connection
    └── samples.md      # Sample data for the database connection

Usage:
    Database tools are automatically injected when:
    1. Agent has db_connection_names configured in agent_config
    2. The agent type supports database tools (react_agent, react_critic_agent, etc.)

Only the following tool is injected during inference:
    - database_query_tool: Execute SELECT queries
    
Agent reads schema/sample files using run_shell_command: cat /databases/{conn}/schema.md
"""

from typing import List, Optional, Dict, Any, Callable
from functools import partial
from telemetry_wrapper import logger as log


# System prompt instruction template for database tools (SHARED file-based approach)
DATABASE_TOOLS_INSTRUCTION = """

═══════════════════════════════════════════════════════════════════════════════
                    DATABASE QUERY CAPABILITY (IMPORTANT)
═══════════════════════════════════════════════════════════════════════════════

You have access to query the following database connections: {db_connection_names}

## 📦 AVAILABLE TOOLS FOR DATABASE OPERATIONS:

### 1. `database_query_tool` - Execute SQL Queries
```
database_query_tool(
    connection_name: str,       # Name of the database connection
    query: str,                 # SQL SELECT query to execute
    limit: int = 100,           # Max rows to return (default: 100)
    output_format: str = "table"  # "table", "json", or "summary"
)
```
- **Allowed SQL operations are controlled by the connection's blocked commands list**

### 2. `run_shell_command` - File Operations & Database Info
The `run_shell_command` tool provides Unix-like shell access for reading database metadata files:

**Database Files (SHARED across all agents):**
```
run_shell_command("ls /databases/")                              # List all database connections
run_shell_command("ls /databases/YOUR_CONNECTION/")             # List files for a connection
run_shell_command("cat /databases/YOUR_CONNECTION/schema.md")   # Read stored schema
run_shell_command("cat /databases/YOUR_CONNECTION/samples.md")  # Read sample data
```

**User Files:**
```
run_shell_command("ls /user/")                                   # List user-specific files
run_shell_command("cat /user/preferences.md")                   # Read user preferences
```

**Agent Files:**
```
run_shell_command("ls /agent/")                                  # List agent memory files
run_shell_command("cat /agent/facts/important_facts.md")        # Read agent facts
run_shell_command("echo 'content' > /agent/learnings/note.md")  # Save agent learnings
```

**Session Files:**
```
run_shell_command("ls /session/")                                # List session files
run_shell_command("cat /session/conversation.md")               # View conversation history
```

## 🔄 WORKFLOW FOR DATABASE QUERIES:

**ALWAYS follow these steps in order:**

**Step 1: Discover available database connections**
```
run_shell_command("ls /databases/")
```
→ This shows all available database connections

**Step 2: Read the database schema (REQUIRED before querying)**
```
run_shell_command("cat /databases/{first_connection}/schema.md")
```
→ This gives you table names, column names, data types, and relationships

**Step 3: (Optional) Check sample data for data format understanding**
```
run_shell_command("cat /databases/{first_connection}/samples.md")
```
→ This shows example rows from each table

**Step 4: Write and execute your SQL query**
```
database_query_tool(
    connection_name="{first_connection}",
    query="SELECT column1, column2 FROM table_name WHERE condition",
    limit=100
)
```

**Step 5: If query fails, read samples.md and retry**
If your query returns an error (e.g., column not found, syntax error):
```
run_shell_command("cat /databases/{first_connection}/samples.md")
```
→ Review the sample data to understand actual column names, data formats, and values
→ Then rewrite and execute your query with corrected syntax

## ⚠️ IMPORTANT RULES:

1. **ALWAYS read schema.md FIRST** - Never write queries without knowing the exact table/column names
2. **Blocked commands are configurable** - By default INSERT, UPDATE, DELETE, DROP are blocked, but can be allowed per connection
3. **Use exact names from schema** - Copy table and column names exactly as shown
4. **Blocked commands are dynamic** - Each connection may have custom blocked SQL keywords
5. **If schema doesn't exist** - Tell user to first store the schema using the UI or API

## 📁 FILE STRUCTURE:

```
/databases/                          ← SHARED database files (readable by all agents)
├── {first_connection}/
│   ├── schema.md                    ← Database schema (tables, columns, relationships)
│   └── samples.md                   ← Sample data from each table
└── other_connection/
    ├── schema.md
    └── samples.md

/user/                               ← User-specific files
├── preferences.md
└── ...

/agent/                              ← Agent memory files
├── facts/
├── learnings/
└── entities/

/session/                            ← Current session files
├── conversation.md
└── ...
```

═══════════════════════════════════════════════════════════════════════════════
"""


def get_database_tools_for_injection(db_connection_names: List[str]) -> List[Callable]:
    """
    Get database tool instances configured for the specified connections.
    
    Only returns database_query_tool. Schema and sample data are read from
    files using run_shell_command.
    
    Args:
        db_connection_names: List of database connection names available to the agent
        
    Returns:
        List containing only the database_query_tool for injection into the agent
    """
    if not db_connection_names:
        return []
    
    tools = []
    
    try:
        from langchain_core.tools import StructuredTool
        from src.tools.database_tools import database_query_tool
        
        # Only inject database_query_tool (schema and sample data are cached)
        query_tool = StructuredTool.from_function(
            func=database_query_tool,
            name="database_query_tool",
            description="Execute a SQL query against a database. Allowed operations depend on the connection's blocked commands configuration. Read schema files first using run_shell_command before writing queries. Args: connection_name (str) - the database connection name, query (str) - the SQL query to execute, limit (int, optional) - max rows to return (default 100)."
        )
        
        tools = [query_tool]
        
        log.info(f"[DB_TOOLS] Loaded database_query_tool for connections: {db_connection_names}")
        log.info(f"[DB_TOOLS] Agent will read schema from files using run_shell_command")
        
    except ImportError as e:
        log.error(f"Failed to import database tools: {e}")
    except Exception as e:
        log.error(f"Error loading database tools: {e}")
    
    return tools


def get_database_tools_system_prompt(
    db_connection_names: List[str],
    agent_id: str = None
) -> str:
    """
    Generate the system prompt instruction for database tools.
    
    SHARED FILE-BASED APPROACH: Agent reads schema/sample files using run_shell_command.
    Files are stored in /databases/{connection_name}/ (shared across all agents).
    
    Args:
        db_connection_names: List of database connection names
        agent_id: The agent's unique ID (kept for compatibility, not used)
        
    Returns:
        Formatted system prompt instruction string
    """
    if not db_connection_names:
        return ""
    
    first_connection = db_connection_names[0] if db_connection_names else "your_db"
    
    return DATABASE_TOOLS_INSTRUCTION.format(
        db_connection_names=db_connection_names,
        first_connection=first_connection
    )


async def get_db_connections_for_agent(agentic_application_id: str) -> List[str]:
    """
    Retrieve database connection names configured for an agent.
    
    This checks the agent's configuration for any associated database
    connections and returns their names.
    
    Args:
        agentic_application_id: The agent's unique ID
        
    Returns:
        List of database connection names, or empty list if none configured
    """
    log.info(f"[DB_TOOLS] Fetching db_connections for agent: {agentic_application_id}")
    
    try:
        # Use direct database query for reliability
        import os
        import asyncpg
        import json as json_module
        
        conn = await asyncpg.connect(
            host=os.getenv("POSTGRESQL_HOST", "localhost"),
            port=int(os.getenv("POSTGRESQL_PORT", "5432")),
            user=os.getenv("POSTGRESQL_USER", "postgres"),
            password=os.getenv("POSTGRESQL_PASSWORD", "postgres"),
            database=os.getenv("DATABASE", "agentic_workflow_as_service_database")
        )
        
        row = await conn.fetchrow(
            "SELECT db_connection_names FROM agent_table WHERE agentic_application_id = $1",
            agentic_application_id
        )
        await conn.close()
        
        if row and row['db_connection_names']:
            db_connections = row['db_connection_names']
            log.info(f"[DB_TOOLS] Raw db_connection_names: {db_connections} (type: {type(db_connections).__name__})")
            
            # Handle if stored as JSON string
            if isinstance(db_connections, str):
                try:
                    db_connections = json_module.loads(db_connections)
                except:
                    db_connections = [db_connections] if db_connections else []
            
            # Filter out empty/None values
            db_connections = [c for c in (db_connections or []) if c]
            
            if db_connections:
                log.info(f"[DB_TOOLS] Found database connections for agent {agentic_application_id}: {db_connections}")
            
            return db_connections
        
        log.info(f"[DB_TOOLS] No db_connection_names found for agent {agentic_application_id}")
        return []
        
    except Exception as e:
        log.warning(f"[DB_TOOLS] Error fetching database connections for agent '{agentic_application_id}': {e}")
        import traceback
        log.warning(f"[DB_TOOLS] Traceback: {traceback.format_exc()}")
        return []


def inject_database_tools_into_config(
    agent_config: Dict[str, Any],
    db_connection_names: List[str],
    agent_id: str = None
) -> Dict[str, Any]:
    """
    Inject database tools instruction into agent's system prompt.
    
    SHARED FILE-BASED APPROACH: Adds instructions for reading schema from files.
    Files are stored in /databases/{connection_name}/ (shared across all agents).
    The agent will use run_shell_command to read schema/sample data files.
    
    Args:
        agent_config: The agent configuration dictionary
        db_connection_names: List of database connection names
        agent_id: The agent's unique ID (kept for compatibility, not used)
        
    Returns:
        Modified agent_config with database tools instruction added
    """
    if not db_connection_names:
        return agent_config
    
    # Get instruction for file-based schema reading
    db_instruction = get_database_tools_system_prompt(
        db_connection_names,
        agent_id=agent_id
    )
    agent_type = agent_config.get("AGENT_TYPE", "")
    
    # Store connection names in config for tool loading
    agent_config['DB_CONNECTION_NAMES'] = db_connection_names
    
    # Add instruction to the appropriate system prompt based on agent type
    if "SYSTEM_PROMPT" in agent_config:
        if agent_type == "react_agent":
            if "SYSTEM_PROMPT_REACT_AGENT" in agent_config['SYSTEM_PROMPT']:
                agent_config['SYSTEM_PROMPT']['SYSTEM_PROMPT_REACT_AGENT'] += db_instruction
        elif agent_type == "react_critic_agent":
            if "SYSTEM_PROMPT_EXECUTOR_AGENT" in agent_config['SYSTEM_PROMPT']:
                agent_config['SYSTEM_PROMPT']['SYSTEM_PROMPT_EXECUTOR_AGENT'] += db_instruction
        elif agent_type == "planner_executor_agent":
            if "SYSTEM_PROMPT_EXECUTOR_AGENT" in agent_config['SYSTEM_PROMPT']:
                agent_config['SYSTEM_PROMPT']['SYSTEM_PROMPT_EXECUTOR_AGENT'] += db_instruction
        elif agent_type == "planner_executor_critic_agent":
            if "SYSTEM_PROMPT_EXECUTOR_AGENT" in agent_config['SYSTEM_PROMPT']:
                agent_config['SYSTEM_PROMPT']['SYSTEM_PROMPT_EXECUTOR_AGENT'] += db_instruction
    
    log.info(f"[DB_TOOLS] Database instruction injected for connections: {db_connection_names}")
    
    return agent_config


__all__ = [
    "get_database_tools_for_injection",
    "get_database_tools_system_prompt",
    "get_db_connections_for_agent",
    "inject_database_tools_into_config",
    "DATABASE_TOOLS_INSTRUCTION",
]
