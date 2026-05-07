# © 2024-25 Infosys Limited, Bangalore, India. All Rights Reserved.
"""
Database Schema Storage Module (File-Based, Shared/Reusable)

This module provides file storage for database schema and sample data.
Database files are stored in a SHARED location (not per-agent) making them
reusable across multiple agents.

APPROACH:
1. Schema and sample data are stored ONCE per database connection
2. Files are shared across ALL agents that use the same connection
3. Agent uses run_shell_command (cat) to read files during inference
4. No automatic refresh - user manages the files manually

File Structure:
    agent_workspaces/{department}/databases/{connection_name}/
    ├── schema.md       # Schema for the database connection
    └── samples.md      # Sample data for the database connection

Usage:
    - Store schema: save_database_schema(connection_name, schema_text, department="General")
    - Store samples: save_database_samples(connection_name, samples_text, department="General")
    - Agent reads: run_shell_command("cat /databases/{connection_name}/schema.md")
"""

import os
import json
from datetime import datetime
from typing import List, Dict, Any, Optional
from pathlib import Path
from telemetry_wrapper import logger as log


# Base directory for agent workspaces
AGENT_WORKSPACES_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "agent_workspaces")

# Default department name when none is provided
DEFAULT_DEPARTMENT = "General"


def get_department_root(department: str = None) -> Path:
    """
    Get the root directory for a specific department under agent_workspaces.
    
    Structure: agent_workspaces/{department}/
    
    Args:
        department: The department name. Defaults to DEFAULT_DEPARTMENT if not provided.
        
    Returns:
        Path to the department root directory
    """
    dept = department or DEFAULT_DEPARTMENT
    dept_root = Path(AGENT_WORKSPACES_DIR) / dept
    dept_root.mkdir(parents=True, exist_ok=True)
    return dept_root


def get_databases_root(department: str = None) -> Path:
    """
    Get the root directory for all database files within a department.
    
    Structure: agent_workspaces/{department}/databases/
    
    Args:
        department: The department name. Defaults to DEFAULT_DEPARTMENT if not provided.
        
    Returns:
        Path to the databases root directory
    """
    db_root = get_department_root(department) / "databases"
    db_root.mkdir(parents=True, exist_ok=True)
    
    return db_root


def get_database_directory(connection_name: str, department: str = None) -> Path:
    """
    Get the directory for a specific database connection within a department.
    
    Structure: agent_workspaces/{department}/databases/{connection_name}/
    
    Args:
        connection_name: The database connection name
        department: The department name. Defaults to DEFAULT_DEPARTMENT if not provided.
        
    Returns:
        Path to the database directory
    """
    db_dir = get_databases_root(department) / connection_name
    db_dir.mkdir(parents=True, exist_ok=True)
    
    return db_dir


def get_user_preferences_directory(user_email: str, department: str = None) -> Path:
    """
    Get the user preferences directory path within a department.
    
    Structure: agent_workspaces/{department}/users/{user_email}/
    
    Args:
        user_email: The user's email
        department: The department name. Defaults to DEFAULT_DEPARTMENT if not provided.
        
    Returns:
        Path to the user preferences directory
    """
    # Sanitize user email for filesystem
    safe_user = user_email.replace("@", "_at_").replace(".", "_")
    
    user_dir = get_department_root(department) / "users" / safe_user
    user_dir.mkdir(parents=True, exist_ok=True)
    
    return user_dir


def get_agent_directory(agent_id: str, department: str = None) -> Path:
    """
    Get the agent directory path within a department.
    
    Structure: agent_workspaces/{department}/agents/{agent_id}/
    
    Args:
        agent_id: The agent's unique ID
        department: The department name. Defaults to DEFAULT_DEPARTMENT if not provided.
        
    Returns:
        Path to the agent directory
    """
    agent_dir = get_department_root(department) / "agents" / agent_id
    agent_dir.mkdir(parents=True, exist_ok=True)
    
    return agent_dir


def get_file_context_prompts_dir(department: str = None) -> Path:
    """
    Get the file-context prompts directory for a department.
    
    Structure: agent_workspaces/{department}/file_context_prompts/
    
    Args:
        department: The department name. Defaults to DEFAULT_DEPARTMENT if not provided.
        
    Returns:
        Path to the file_context_prompts directory
    """
    prompts_dir = get_department_root(department) / "file_context_prompts"
    prompts_dir.mkdir(parents=True, exist_ok=True)
    return prompts_dir


def get_file_context_recycle_bin_dir(department: str = None) -> Path:
    """
    Get the file-context prompts recycle bin directory for a department.
    
    Structure: agent_workspaces/{department}/file_context_prompts_recycle_bin/
    
    Args:
        department: The department name. Defaults to DEFAULT_DEPARTMENT if not provided.
        
    Returns:
        Path to the file_context_prompts_recycle_bin directory
    """
    recycle_dir = get_department_root(department) / "file_context_prompts_recycle_bin"
    recycle_dir.mkdir(parents=True, exist_ok=True)
    return recycle_dir


def save_database_schema(
    connection_name: str,
    schema_text: str,
    department: str = None
) -> Dict[str, Any]:
    """
    Save database schema to a file (shared/reusable across agents within a department).
    
    Any agent can read this using: cat /databases/{connection_name}/schema.md
    
    Args:
        connection_name: Name of the database connection
        schema_text: The schema text to save (markdown format)
        department: Department name for workspace segregation
        
    Returns:
        Dict with status and file path
    """
    db_dir = get_database_directory(connection_name, department)
    schema_file = db_dir / "schema.md"
    
    try:
        # Add header with metadata
        content = f"""# Database Schema: {connection_name}

**Stored:** {datetime.now().isoformat()}
**Connection:** {connection_name}

---

{schema_text}
"""
        schema_file.write_text(content, encoding="utf-8")
        
        log.info(f"[DB_DATA] Saved schema for {connection_name} to {schema_file}")
        
        return {
            "status": "success",
            "message": f"Schema saved for {connection_name}",
            "file_path": str(schema_file),
            "virtual_path": f"/databases/{connection_name}/schema.md"
        }
        
    except Exception as e:
        log.error(f"[DB_DATA] Error saving schema for {connection_name}: {e}")
        return {
            "status": "error",
            "message": str(e)
        }


def save_database_samples(
    connection_name: str,
    samples_text: str,
    department: str = None
) -> Dict[str, Any]:
    """
    Save database sample data to a file (shared/reusable across agents within a department).
    
    Any agent can read this using: cat /databases/{connection_name}/samples.md
    
    Args:
        connection_name: Name of the database connection
        samples_text: The sample data text to save (markdown format)
        department: Department name for workspace segregation
        
    Returns:
        Dict with status and file path
    """
    db_dir = get_database_directory(connection_name, department)
    samples_file = db_dir / "samples.md"
    
    try:
        # Add header with metadata
        content = f"""# Sample Data: {connection_name}

**Stored:** {datetime.now().isoformat()}
**Connection:** {connection_name}

---

{samples_text}
"""
        samples_file.write_text(content, encoding="utf-8")
        
        log.info(f"[DB_DATA] Saved samples for {connection_name} to {samples_file}")
        
        return {
            "status": "success",
            "message": f"Sample data saved for {connection_name}",
            "file_path": str(samples_file),
            "virtual_path": f"/databases/{connection_name}/samples.md"
        }
        
    except Exception as e:
        log.error(f"[DB_DATA] Error saving samples for {connection_name}: {e}")
        return {
            "status": "error",
            "message": str(e)
        }


def get_database_files(connection_name: str = None, department: str = None) -> List[Dict[str, str]]:
    """
    List database files. If connection_name is provided, list files for that
    connection only. Otherwise, list all database connections and their files.
    
    Args:
        connection_name: Optional - specific connection to list
        department: Department name for workspace segregation
        
    Returns:
        List of file info dicts with name and virtual_path
    """
    db_root = get_databases_root(department)
    
    files = []
    
    if connection_name:
        # List files for specific connection
        db_dir = db_root / connection_name
        if db_dir.exists():
            for f in db_dir.glob("*.md"):
                files.append({
                    "connection_name": connection_name,
                    "name": f.name,
                    "virtual_path": f"/databases/{connection_name}/{f.name}",
                    "real_path": str(f)
                })
    else:
        # List all connections and their files
        if db_root.exists():
            for conn_dir in db_root.iterdir():
                if conn_dir.is_dir():
                    for f in conn_dir.glob("*.md"):
                        files.append({
                            "connection_name": conn_dir.name,
                            "name": f.name,
                            "virtual_path": f"/databases/{conn_dir.name}/{f.name}",
                            "real_path": str(f)
                        })
    
    return files


def list_database_connections(department: str = None) -> List[str]:
    """
    List all database connections that have stored files within a department.
    
    Args:
        department: Department name for workspace segregation
        
    Returns:
        List of connection names
    """
    db_root = get_databases_root(department)
    
    connections = []
    if db_root.exists():
        for conn_dir in db_root.iterdir():
            if conn_dir.is_dir():
                connections.append(conn_dir.name)
    
    return connections


def delete_database_file(connection_name: str, file_type: str = "schema", department: str = None) -> bool:
    """
    Delete a database file.
    
    Args:
        connection_name: Name of the database connection
        file_type: "schema" or "samples"
        department: Department name for workspace segregation
        
    Returns:
        True if deleted successfully
    """
    db_dir = get_database_directory(connection_name, department)
    
    filename = "schema.md" if file_type == "schema" else "samples.md"
    file_path = db_dir / filename
    
    try:
        if file_path.exists():
            file_path.unlink()
            log.info(f"[DB_DATA] Deleted {file_type} for {connection_name}")
            return True
        return False
    except Exception as e:
        log.error(f"[DB_DATA] Error deleting {file_type} for {connection_name}: {e}")
        return False


def clear_database_files(connection_name: str, department: str = None) -> bool:
    """
    Clear all files for a database connection within a department.
    
    Args:
        connection_name: Name of the database connection
        department: Department name for workspace segregation
        
    Returns:
        True if cleared successfully
    """
    db_dir = get_database_directory(connection_name, department)
    
    try:
        import shutil
        if db_dir.exists():
            shutil.rmtree(db_dir)
            log.info(f"[DB_DATA] Cleared all files for connection {connection_name}")
        return True
    except Exception as e:
        log.error(f"[DB_DATA] Error clearing files for {connection_name}: {e}")
        return False


def clear_all_database_files(department: str = None) -> bool:
    """
    Clear all database files for all connections within a department.
    
    Args:
        department: Department name for workspace segregation
        
    Returns:
        True if cleared successfully
    """
    db_root = get_databases_root(department)
    
    try:
        import shutil
        if db_root.exists():
            shutil.rmtree(db_root)
            db_root.mkdir(parents=True, exist_ok=True)
            log.info(f"[DB_DATA] Cleared all database files")
        return True
    except Exception as e:
        log.error(f"[DB_DATA] Error clearing all database files: {e}")
        return False


# =============================================================================
# auto_generate_schema_and_samples — Temporarily disabled, will be used later
# =============================================================================
# async def auto_generate_schema_and_samples(
#     connection_name: str,
#     db_type: str,
#     connection_manager=None,
#     department: str = None
# ) -> Dict[str, Any]:
#     """
#     Auto-generate schema and sample files when a data connector is created.
#
#     This function:
#     1. Gets the list of tables from the database
#     2. Gets column information for each table (from sample query)
#     3. Gets sample data (LIMIT 3) from each table
#     4. Saves schema.md and samples.md files
#
#     Args:
#         connection_name: Name of the database connection
#         db_type: Type of database (sqlite, postgresql, mysql, mongodb)
#         connection_manager: The connection manager instance
#         department: Department name for workspace segregation
#
#     Returns:
#         Dict with status and file paths
#     """
#     from MultiDBConnection_Manager import get_connection_manager
#
#     if connection_manager is None:
#         connection_manager = get_connection_manager()
#
#     schema_md = f"# Database Schema: {connection_name}\n\n"
#     samples_md = f"# Sample Data: {connection_name}\n\n"
#
#     tables_processed = []
#     errors = []
#
#     try:
#         if db_type.lower() == "mongodb":
#             # MongoDB: Get collections
#             try:
#                 mongo_db = connection_manager.get_mongo_database(connection_name)
#                 collections = await mongo_db.list_collection_names()
#
#                 schema_md += f"**Database Type:** MongoDB\n\n"
#
#                 for collection_name in collections:
#                     if collection_name.startswith('system.'):
#                         continue
#
#                     schema_md += f"## Collection: {collection_name}\n\n"
#                     samples_md += f"## Collection: {collection_name}\n\n"
#
#                     # Get sample document to infer schema
#                     collection = mongo_db[collection_name]
#                     sample_docs = await collection.find().limit(3).to_list(length=3)
#
#                     if sample_docs:
#                         # Infer fields and types from sample documents
#                         first_doc = sample_docs[0]
#                         fields = list(first_doc.keys())
#
#                         schema_md += f"**Fields:**\n\n"
#                         schema_md += "| Field | Type | Sample Value |\n"
#                         schema_md += "| --- | --- | --- |\n"
#                         for field in fields:
#                             val = first_doc.get(field)
#                             # Infer BSON/Python type
#                             if val is None:
#                                 ftype = "null"
#                             elif hasattr(val, '__str__') and 'ObjectId' in str(type(val)):
#                                 ftype = "ObjectId"
#                             elif isinstance(val, bool):
#                                 ftype = "Boolean"
#                             elif isinstance(val, int):
#                                 ftype = "Int"
#                             elif isinstance(val, float):
#                                 ftype = "Double"
#                             elif isinstance(val, str):
#                                 ftype = "String"
#                             elif isinstance(val, list):
#                                 ftype = "Array"
#                             elif isinstance(val, dict):
#                                 ftype = "Object"
#                             else:
#                                 ftype = type(val).__name__
#                             sample_val = str(val)[:60] if val is not None else "null"
#                             schema_md += f"| `{field}` | {ftype} | {sample_val} |\n"
#                         schema_md += "\n"
#
#                         # Add sample documents
#                         samples_md += "**Sample Documents:**\n```json\n"
#                         import json
#                         for doc in sample_docs:
#                             # Convert ObjectId to string for serialization
#                             for k, v in doc.items():
#                                 if hasattr(v, '__str__') and 'ObjectId' in str(type(v)):
#                                     doc[k] = str(v)
#                             samples_md += json.dumps(doc, indent=2, default=str) + "\n"
#                         samples_md += "```\n\n"
#                     else:
#                         schema_md += "*No documents found*\n\n"
#                         samples_md += "*No documents found*\n\n"
#
#                     tables_processed.append(collection_name)
#
#             except Exception as e:
#                 errors.append(f"MongoDB error: {str(e)}")
#                 log.error(f"[AUTO_SCHEMA] MongoDB error for {connection_name}: {e}")
#
#         else:
#             # SQL databases (SQLite, PostgreSQL, MySQL)
#             try:
#                 from sqlalchemy import text, inspect as sa_inspect
#                 session = connection_manager.get_sql_session(connection_name)
#
#                 # Get the engine for SQLAlchemy inspector (full metadata)
#                 engine = session.get_bind()
#                 inspector = sa_inspect(engine)
#
#                 schema_md += f"**Database Type:** {db_type}\n\n"
#
#                 # Get tables using inspector (works for all SQL backends)
#                 tables = inspector.get_table_names()
#
#                 for table_name in tables:
#                     if table_name.startswith('sqlite_'):
#                         continue
#
#                     schema_md += f"## Table: {table_name}\n\n"
#                     samples_md += f"## Table: {table_name}\n\n"
#
#                     try:
#                         # --- Full column metadata via inspector ---
#                         columns_info = inspector.get_columns(table_name)
#                         pk_info = inspector.get_pk_constraint(table_name)
#                         pk_columns = set(pk_info.get('constrained_columns', []) if pk_info else [])
#                         fk_list = inspector.get_foreign_keys(table_name)
#                         unique_constraints = inspector.get_unique_constraints(table_name)
#                         indexes = inspector.get_indexes(table_name)
#
#                         # Build a lookup for foreign key columns
#                         fk_map = {}  # column_name -> "references table(column)"
#                         for fk in fk_list:
#                             ref_table = fk.get('referred_table', '')
#                             for local_col, ref_col in zip(
#                                 fk.get('constrained_columns', []),
#                                 fk.get('referred_columns', [])
#                             ):
#                                 fk_map[local_col] = f"{ref_table}({ref_col})"
#
#                         # Build unique columns set
#                         unique_columns = set()
#                         for uc in unique_constraints:
#                             for col in uc.get('column_names', []):
#                                 unique_columns.add(col)
#
#                         # Build indexed columns set
#                         indexed_columns = set()
#                         for idx in indexes:
#                             for col in idx.get('column_names', []):
#                                 if col:
#                                     indexed_columns.add(col)
#
#                         # Schema table header
#                         schema_md += f"**Columns:**\n\n"
#                         schema_md += "| Column | Type | Nullable | Default | Key | Extra |\n"
#                         schema_md += "| --- | --- | --- | --- | --- | --- |\n"
#
#                         column_names = []
#                         for col in columns_info:
#                             col_name = col['name']
#                             column_names.append(col_name)
#                             col_type = str(col.get('type', 'UNKNOWN'))
#                             nullable = 'YES' if col.get('nullable', True) else 'NO'
#                             default = str(col.get('default', '')) if col.get('default') is not None else ''
#
#                             # Key info
#                             key_parts = []
#                             if col_name in pk_columns:
#                                 key_parts.append('PK')
#                             if col_name in fk_map:
#                                 key_parts.append('FK')
#                             if col_name in unique_columns:
#                                 key_parts.append('UQ')
#                             key_str = ', '.join(key_parts) if key_parts else ''
#
#                             # Extra info
#                             extra_parts = []
#                             if col.get('autoincrement', False) and col.get('autoincrement') != 'auto':
#                                 extra_parts.append('auto_increment')
#                             if col_name in fk_map:
#                                 extra_parts.append(f'→ {fk_map[col_name]}')
#                             if col_name in indexed_columns:
#                                 extra_parts.append('indexed')
#                             extra_str = ', '.join(extra_parts) if extra_parts else ''
#
#                             schema_md += f"| `{col_name}` | {col_type} | {nullable} | {default} | {key_str} | {extra_str} |\n"
#
#                         schema_md += "\n"
#
#                         # --- Sample data ---
#                         sample_result = session.execute(text(f"SELECT * FROM \"{table_name}\" LIMIT 3"))
#                         rows = sample_result.fetchall()
#
#                         samples_md += f"**Columns:** {', '.join(column_names)}\n\n"
#                         if rows:
#                             samples_md += "| " + " | ".join(column_names) + " |\n"
#                             samples_md += "| " + " | ".join(["---"] * len(column_names)) + " |\n"
#                             for row in rows:
#                                 values = [str(v) if v is not None else "NULL" for v in row]
#                                 samples_md += "| " + " | ".join(values) + " |\n"
#                         else:
#                             samples_md += "*No data found*\n"
#                         samples_md += "\n"
#
#                         tables_processed.append(table_name)
#
#                     except Exception as table_error:
#                         errors.append(f"Table {table_name}: {str(table_error)}")
#                         log.warning(f"[AUTO_SCHEMA] Error processing table {table_name}: {table_error}")
#                         schema_md += f"*Error reading table*\n\n"
#                         samples_md += f"*Error reading table*\n\n"
#
#                 session.close()
#
#             except Exception as e:
#                 errors.append(f"SQL error: {str(e)}")
#                 log.error(f"[AUTO_SCHEMA] SQL error for {connection_name}: {e}")
#
#         # Save the schema and samples files
#         schema_result = save_database_schema(connection_name, schema_md, department)
#         samples_result = save_database_samples(connection_name, samples_md, department)
#
#         log.info(f"[AUTO_SCHEMA] Generated schema and samples for {connection_name}: {len(tables_processed)} tables")
#
#         return {
#             "status": "success",
#             "message": f"Auto-generated schema and samples for {connection_name}",
#             "tables_processed": tables_processed,
#             "schema_file": schema_result.get("virtual_path"),
#             "samples_file": samples_result.get("virtual_path"),
#             "errors": errors if errors else None
#         }
#
#     except Exception as e:
#         log.error(f"[AUTO_SCHEMA] Failed to auto-generate for {connection_name}: {e}")
#         return {
#             "status": "error",
#             "message": str(e),
#             "errors": errors
#         }


__all__ = [
    "AGENT_WORKSPACES_DIR",
    "DEFAULT_DEPARTMENT",
    "get_department_root",
    "get_databases_root",
    "get_database_directory",
    "get_user_preferences_directory",
    "get_agent_directory",
    "get_file_context_prompts_dir",
    "get_file_context_recycle_bin_dir",
    "save_database_schema",
    "save_database_samples",
    "get_database_files",
    "list_database_connections",
    "delete_database_file",
    "clear_database_files",
    "clear_all_database_files",
    # "auto_generate_schema_and_samples",  # Temporarily disabled
]
