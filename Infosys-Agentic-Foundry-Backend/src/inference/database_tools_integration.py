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

### 2. `run_shell_command` - Powerful Shell (18 commands + pipe support)
The `run_shell_command` tool provides a Unix-like shell with 18 commands for reading, searching, and managing files:

**Database Files (SHARED across all agents):**
```
run_shell_command("ls /databases/")                                        # List all database connections
run_shell_command("cat /databases/YOUR_CONNECTION/schema.md")              # Read full schema
run_shell_command("cat -n /databases/YOUR_CONNECTION/schema.md")           # Read schema with line numbers
run_shell_command("sed -n '10,30p' /databases/YOUR_CONNECTION/schema.md")  # Read specific line range (efficient!)
run_shell_command("stat /databases/YOUR_CONNECTION/schema.md")             # Check file size before reading
run_shell_command("grep -C 3 'column_name' /databases/YOUR_CONNECTION/schema.md")  # Find column with 3 lines context
run_shell_command("grep -rni 'customer' /databases/")                      # Search across ALL database schemas
run_shell_command("diff /databases/db1/schema.md /databases/db2/schema.md")  # Compare two schemas
run_shell_command("find /databases/ -iname '*.md'")                        # Find all markdown files (case-insensitive)
run_shell_command("grep 'table' schema.md | head -5")                     # First 5 table matches (pipe!)
```

**User Files:**
```
run_shell_command("cat /user/preferences.md")                   # Read user preferences
run_shell_command("echo 'key: value' > /user/facts/prefs.md")  # Store user facts
```

**Agent Files:**
```
run_shell_command("ls /agent/facts/")                            # List agent facts
run_shell_command("cat /agent/facts/important_facts.md")        # Read agent facts
run_shell_command("echo 'content' > /agent/learnings/note.md")  # Save agent learnings
```

**Session Files:**
```
run_shell_command("ls /session/workspace/")                      # List workspace files
run_shell_command("cat /session/conversations/summary.md")      # View conversation summary
```

**Full Command Reference (18 commands):**
- `ls`, `cd`, `pwd` — Navigate directories
- `cat [-n]` — Read file (-n for line numbers)
- `head -n N`, `tail -n N` — First/last N lines
- `sed -n '10,20p'` — Read specific line range (targeted read)
- `stat` — File size, line count, modified time
- `diff` — Compare two files (unified diff)
- `wc [-lwc] file|*.md` — Count lines/words/chars (supports globs)
- `tree [--size]` — Directory tree (--size shows file sizes)
- `grep [-rinlv] [-A/-B/-C N] [-e pat]` — Search with context, multi-pattern, invert
- `semgrep "concept"` — Semantic search by meaning
- `find -name|-iname` — Find files (-iname: case-insensitive)
- `echo "text" > /file` — Write (>> appends)
- `mkdir -p`, `touch` — Create dirs/files
- **Pipes**: `cmd1 | cmd2` (up to 5 stages)

## 🔄 WORKFLOW FOR DATABASE QUERIES:

**ALWAYS follow these steps in order:**

**Step 1: Discover available database connections**
```
run_shell_command("ls /databases/")
```
→ This shows all available database connections

**Step 2: Read the database schema (REQUIRED before querying)**
```
run_shell_command("stat /databases/{first_connection}/schema.md")     # Check size first
run_shell_command("cat /databases/{first_connection}/schema.md")      # Read full schema
```
→ This gives you table names, column names, data types, and relationships
→ For large schemas, use `sed -n '1,50p'` to read in chunks instead of `cat`

**Step 2b: (Optional) Search within schema for specific info**
```
run_shell_command("grep -C 3 'customer' /databases/{first_connection}/schema.md")  # Find with context
run_shell_command("grep -rni 'order_id' /databases/")                              # Search across ALL schemas
```

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
6. **Use `stat` before reading** - Check file size before cat-ing large schemas
7. **Use `sed` for targeted reads** - `sed -n '45,60p' /databases/conn/schema.md` instead of reading entire files
8. **Use `grep -C` for context** - Find columns/tables with context instead of reading everything
9. **Use pipes to filter** - `grep 'table' schema.md | head -5` for quick lookups

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
    
    Uses the shared DB pool from app_container when available (fast),
    falling back to a direct asyncpg.connect() only if pool is unavailable.
    
    Args:
        agentic_application_id: The agent's unique ID
        
    Returns:
        List of database connection names, or empty list if none configured
    """
    log.info(f"[DB_TOOLS] Fetching db_connections for agent: {agentic_application_id}")
    
    try:
        import json as json_module
        
        row = None
        # Prefer the shared connection pool (avoids ~600ms fresh TCP connect per request)
        try:
            from src.api.app_container import app_container
            from src.config.constants import DatabaseName
            db_pool = await app_container.db_manager.get_pool(DatabaseName.MAIN.db_name)
            if db_pool:
                async with db_pool.acquire() as conn:
                    row = await conn.fetchrow(
                        "SELECT db_connection_names FROM agent_table WHERE agentic_application_id = $1",
                        agentic_application_id
                    )
        except Exception as pool_err:
            log.debug(f"[DB_TOOLS] Pool unavailable, falling back to direct connect: {pool_err}")
            # Fallback: direct connection
            import os
            import asyncpg
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
        if agent_type in ("react_agent",):
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


async def ensure_database_files_restored(
    db_connection_names: List[str],
    department: str = "General"
) -> None:
    """
    Ensure database schema/samples files exist locally, restoring from blob if missing.
    
    This should be called BEFORE inference starts so the agent can read the files
    via run_shell_command. Without this, if the local files were deleted or the server
    restarted on a fresh node, the agent would get "No such file" errors.
    
    Args:
        db_connection_names: List of database connection names to check/restore
        department: The department name for file path resolution
    """
    import os
    import asyncio
    from pathlib import Path
    
    if not db_connection_names:
        return
    
    workspace_root = Path(os.path.abspath("./agent_workspaces"))
    storage_provider = os.getenv('STORAGE_PROVIDER', '')
    
    if not storage_provider:
        log.debug("[DB_TOOLS_RESTORE] No STORAGE_PROVIDER set, skipping blob restore check")
        return
    
    _BLOB_RESTORE_TIMEOUT = int(os.getenv('BLOB_RESTORE_TIMEOUT', '30'))
    
    for conn_name in db_connection_names:
        db_dir = workspace_root / department / "databases" / conn_name
        schema_file = db_dir / "schema.md"
        samples_file = db_dir / "samples.md"
        
        # Skip if files already exist locally
        if schema_file.exists() or samples_file.exists():
            log.debug(f"[DB_TOOLS_RESTORE] Files exist locally for '{conn_name}', skipping restore")
            continue
        
        # Files missing - attempt blob restore
        log.info(f"[DB_TOOLS_RESTORE] schema.md/samples.md missing for '{conn_name}', attempting blob restore...")
        try:
            from src.utils.workspace_blob_sync import WorkspaceBlobSync
            from src.storage import get_storage_client
            
            _client = get_storage_client(storage_provider)
            _syncer = WorkspaceBlobSync(
                storage_client=_client,
                workspace_root="./agent_workspaces",
                department=department,
            )
            
            try:
                report = await asyncio.wait_for(
                    _syncer.restore_database_cache(connection_name=conn_name),
                    timeout=_BLOB_RESTORE_TIMEOUT
                )
            except asyncio.TimeoutError:
                log.warning(f"[DB_TOOLS_RESTORE] Timed out restoring '{conn_name}' after {_BLOB_RESTORE_TIMEOUT}s")
                continue
            
            if report and report.synced > 0:
                log.info(f"[DB_TOOLS_RESTORE] Restored {report.synced} files for '{conn_name}' from blob")
            else:
                log.info(f"[DB_TOOLS_RESTORE] No files found in blob for '{conn_name}'")
                
            # Also restore the SQLite .db file if it's a sqlite connection
            try:
                from src.api.data_connector_endpoints import db_connection_manager
                config = await db_connection_manager.get_connection_config(conn_name)
                if config and config.get("db_type", "").lower() == "sqlite":
                    db_filename = config.get("database", "")
                    _conn_dept = config.get("department_name") or department
                    if db_filename:
                        db_file_path = os.path.join("uploaded_sqlite_dbs", _conn_dept, db_filename)
                        if not os.path.exists(db_file_path):
                            _syncer_for_db = WorkspaceBlobSync(
                                storage_client=_client,
                                project_root=os.path.abspath("."),
                            )
                            try:
                                restored = await asyncio.wait_for(
                                    asyncio.to_thread(
                                        _syncer_for_db.restore_sqlite_db_sync, _conn_dept, db_filename
                                    ),
                                    timeout=_BLOB_RESTORE_TIMEOUT
                                )
                                if restored:
                                    log.info(f"[DB_TOOLS_RESTORE] Restored SQLite DB '{db_filename}' from blob")
                            except asyncio.TimeoutError:
                                log.warning(f"[DB_TOOLS_RESTORE] Timed out restoring SQLite DB '{db_filename}'")
                            except Exception as _db_err:
                                log.debug(f"[DB_TOOLS_RESTORE] SQLite DB restore failed: {_db_err}")
            except Exception as _cfg_err:
                log.debug(f"[DB_TOOLS_RESTORE] Could not check SQLite config for '{conn_name}': {_cfg_err}")
                
        except Exception as e:
            log.warning(f"[DB_TOOLS_RESTORE] Failed to restore files for '{conn_name}': {e}")


__all__ = [
    "get_database_tools_for_injection",
    "get_database_tools_system_prompt",
    "get_db_connections_for_agent",
    "inject_database_tools_into_config",
    "ensure_database_files_restored",
    "DATABASE_TOOLS_INSTRUCTION",
]
