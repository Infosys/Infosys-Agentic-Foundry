# © 2024-25 Infosys Limited, Bangalore, India. All Rights Reserved.
"""
Database Tools for IAF Foundry Agents

This module provides general-purpose database tools that can be used by any agent
in the Infosys Agent Foundry. It supports schema discovery, query execution,
and natural language to SQL conversion.

Supported Databases:
- PostgreSQL
- MySQL
- SQLite
- Azure SQL
- MongoDB

Usage:
    These tools can be onboarded to agents via the IAF tool onboarding process.
    Each tool is designed to work with pre-configured database connections
    stored in the db_connections_table.

Security:
    - SQL operations are controlled by a configurable blocked commands list per connection
    - By default: DROP, DELETE, UPDATE, INSERT, ALTER, CREATE, TRUNCATE, EXEC, GRANT, REVOKE are blocked
    - Remove keywords from the blocked list to allow specific operations (e.g., remove INSERT to allow inserts)
    - Result sets are limited to prevent token overflow
    - Connection credentials are managed centrally
"""

import json
import re
from typing import Optional, Dict, Any, List, Union
from sqlalchemy import text, inspect
from src.utils.helper_functions import getenv_using_indirect_method
from telemetry_wrapper import logger as log


# =============================================================================
# CONSTANTS & CONFIGURATION
# =============================================================================

MAX_ROWS_LIMIT = 100  # Maximum rows to return to prevent token overflow
DANGEROUS_KEYWORDS = [
    "DROP", "DELETE", "UPDATE", "INSERT", "ALTER", "CREATE", 
    "TRUNCATE", "EXEC", "EXECUTE", "--", ";--", "/*", "*/",
    "GRANT", "REVOKE", "COMMIT", "ROLLBACK"
]

# Schema queries for different database types
SCHEMA_QUERIES = {
    "postgresql": {
        "tables": """
            SELECT table_name, table_type 
            FROM information_schema.tables 
            WHERE table_schema = 'public'
            ORDER BY table_name
        """,
        "columns": """
            SELECT column_name, data_type, is_nullable, column_default,
                   character_maximum_length
            FROM information_schema.columns 
            WHERE table_schema = 'public' AND table_name = :table_name
            ORDER BY ordinal_position
        """,
        "primary_keys": """
            SELECT kcu.column_name
            FROM information_schema.table_constraints tc
            JOIN information_schema.key_column_usage kcu 
                ON tc.constraint_name = kcu.constraint_name
            WHERE tc.table_name = :table_name 
                AND tc.constraint_type = 'PRIMARY KEY'
        """,
        "foreign_keys": """
            SELECT 
                kcu.column_name,
                ccu.table_name AS foreign_table,
                ccu.column_name AS foreign_column
            FROM information_schema.table_constraints tc
            JOIN information_schema.key_column_usage kcu 
                ON tc.constraint_name = kcu.constraint_name
            JOIN information_schema.constraint_column_usage ccu 
                ON tc.constraint_name = ccu.constraint_name
            WHERE tc.table_name = :table_name 
                AND tc.constraint_type = 'FOREIGN KEY'
        """
    },
    "mysql": {
        "tables": """
            SELECT table_name, table_type 
            FROM information_schema.tables 
            WHERE table_schema = DATABASE()
            ORDER BY table_name
        """,
        "columns": """
            SELECT column_name, data_type, is_nullable, column_default,
                   character_maximum_length
            FROM information_schema.columns 
            WHERE table_schema = DATABASE() AND table_name = :table_name
            ORDER BY ordinal_position
        """,
        "primary_keys": """
            SELECT column_name
            FROM information_schema.key_column_usage
            WHERE table_schema = DATABASE() 
                AND table_name = :table_name 
                AND constraint_name = 'PRIMARY'
        """,
        "foreign_keys": """
            SELECT 
                column_name,
                referenced_table_name AS foreign_table,
                referenced_column_name AS foreign_column
            FROM information_schema.key_column_usage
            WHERE table_schema = DATABASE() 
                AND table_name = :table_name 
                AND referenced_table_name IS NOT NULL
        """
    },
    "sqlite": {
        "tables": """
            SELECT name as table_name, type as table_type 
            FROM sqlite_master 
            WHERE type IN ('table', 'view') AND name NOT LIKE 'sqlite_%'
            ORDER BY name
        """,
        "columns": "PRAGMA table_info(:table_name)",
        "primary_keys": "PRAGMA table_info(:table_name)",  # pk column in result
        "foreign_keys": "PRAGMA foreign_key_list(:table_name)"
    }
}


# =============================================================================
# HELPER FUNCTIONS
# =============================================================================

def _get_db_manager():
    """Get the MultiDBConnectionManager instance."""
    from MultiDBConnection_Manager import get_connection_manager
    return get_connection_manager()


def _validate_query_safety(query: str, blocked_keywords: List[str] = None) -> Dict[str, Any]:
    """
    Validate that a query is safe to execute.
    
    The blocked_keywords list is the **single source of truth** for what SQL operations
    are allowed or blocked. If a keyword (e.g., INSERT, UPDATE) is in the blocked list,
    the query is rejected. If it's NOT in the blocked list, the query is allowed.
    
    Args:
        query: SQL query string to validate
        blocked_keywords: Optional list of keywords to block. If None, uses DANGEROUS_KEYWORDS default.
        
    Returns:
        Dict with 'is_safe' boolean and 'error' message if unsafe
    """
    query_upper = query.strip().upper()
    
    # Use provided blocked keywords or default
    keywords_to_check = blocked_keywords if blocked_keywords is not None else DANGEROUS_KEYWORDS
    
    # Check for blocked keywords — this is the single source of truth
    for keyword in keywords_to_check:
        # Use word boundary check to avoid false positives
        pattern = r'\b' + re.escape(keyword.upper()) + r'\b'
        if re.search(pattern, query_upper):
            return {
                "is_safe": False,
                "error": f"Query contains blocked keyword '{keyword}'. This operation is not allowed for this connection."
            }
    
    return {"is_safe": True, "error": None}


async def _get_connection_blocked_commands(connection_name: str) -> List[str]:
    """
    Get the blocked SQL commands for a specific connection (async version).
    Falls back to default DANGEROUS_KEYWORDS if not configured.
    
    Args:
        connection_name: Name of the database connection
        
    Returns:
        List of blocked SQL keywords
    """
    try:
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
            "SELECT blocked_sql_commands FROM db_connections_table WHERE connection_name = $1",
            connection_name
        )
        await conn.close()
        
        if row and row['blocked_sql_commands']:
            blocked = row['blocked_sql_commands']
            if isinstance(blocked, str):
                return json_module.loads(blocked)
            return blocked
            
    except Exception as e:
        log.warning(f"[DB_TOOLS] Could not fetch blocked commands for {connection_name}: {e}")
    
    # Return default blocked commands
    return DANGEROUS_KEYWORDS


def _get_connection_blocked_commands_sync(connection_name: str) -> List[str]:
    """
    Get the blocked SQL commands for a specific connection (sync version).
    Falls back to default DANGEROUS_KEYWORDS if not configured.
    
    Args:
        connection_name: Name of the database connection
        
    Returns:
        List of blocked SQL keywords
    """
    try:
        import os
        import psycopg2
        import json as json_module
        
        conn = psycopg2.connect(
            host=os.getenv("POSTGRESQL_HOST", "localhost"),
            port=int(os.getenv("POSTGRESQL_PORT", "5432")),
            user=os.getenv("POSTGRESQL_USER", "postgres"),
            password=getenv_using_indirect_method("POSTGRESQL_PASSWORD", "postgres"),
            database=os.getenv("DATABASE", "agentic_workflow_as_service_database")
        )
        
        cursor = conn.cursor()
        cursor.execute(
            "SELECT blocked_sql_commands FROM db_connections_table WHERE connection_name = %s",
            (connection_name,)
        )
        row = cursor.fetchone()
        cursor.close()
        conn.close()
        
        if row and row[0]:
            blocked = row[0]
            if isinstance(blocked, str):
                return json_module.loads(blocked)
            return blocked
            
    except Exception as e:
        log.warning(f"[DB_TOOLS] Could not fetch blocked commands for {connection_name}: {e}")
    
    # Return default blocked commands
    return DANGEROUS_KEYWORDS


def _format_results_as_table(columns: List[str], rows: List[tuple]) -> str:
    """Format query results as a markdown table."""
    if not rows:
        return "No data returned."
    
    # Calculate column widths
    widths = [len(str(c)) for c in columns]
    for row in rows:
        for i, val in enumerate(row):
            widths[i] = max(widths[i], len(str(val) if val is not None else "NULL"))
    
    # Build table
    lines = []
    
    # Header
    header = "| " + " | ".join(str(c).ljust(widths[i]) for i, c in enumerate(columns)) + " |"
    lines.append(header)
    
    # Separator
    sep = "|" + "|".join("-" * (w + 2) for w in widths) + "|"
    lines.append(sep)
    
    # Rows
    for row in rows:
        line = "| " + " | ".join(
            str(v if v is not None else "NULL").ljust(widths[i]) 
            for i, v in enumerate(row)
        ) + " |"
        lines.append(line)
    
    return "\n".join(lines)


def _detect_db_type(connection_name: str) -> str:
    """Detect database type from connection configuration."""
    try:
        db_manager = _get_db_manager()
        config = db_manager._fetch_connection_config_sync(connection_name)
        return config.get('db_type', 'postgresql').lower()
    except Exception:
        return 'postgresql'  # Default fallback


# =============================================================================
# MAIN DATABASE TOOLS (For Agent Onboarding)
# =============================================================================

def database_schema_discovery(
    connection_name: str,
    table_name: Optional[str] = None,
    include_relationships: bool = True
) -> str:
    """
    Discover database schema for a configured connection. Use this BEFORE writing SQL queries
    to understand the table structure, column names, data types, and relationships.
    
    This tool helps agents understand database structure by returning:
    - List of all tables (if no table_name specified)
    - Column details with data types
    - Primary keys and foreign key relationships
    
    Args:
        connection_name (str): Name of the pre-configured database connection 
                               (e.g., 'sales_db', 'crm_database', 'inventory_db').
                               This must match a connection name in the foundry's
                               database connections.
        table_name (str, optional): Specific table to get schema for. If not provided,
                                    returns list of all tables in the database.
        include_relationships (bool): Whether to include foreign key relationships.
                                      Default is True.
    
    Returns:
        str: Schema information formatted as markdown, including:
             - Table list or specific table columns
             - Data types and constraints
             - Primary and foreign key information
    
    Example:
        # Get list of all tables
        schema = database_schema_discovery(connection_name="sales_db")
        
        # Get specific table schema
        schema = database_schema_discovery(
            connection_name="sales_db",
            table_name="orders"
        )
        
        # Get schema without relationships (faster)
        schema = database_schema_discovery(
            connection_name="sales_db",
            table_name="customers",
            include_relationships=False
        )
    """
    try:
        db_manager = _get_db_manager()
        db_type = _detect_db_type(connection_name)
        
        log.info(f"[DB Tool] Schema discovery for '{connection_name}' (type: {db_type})")
        
        # Get appropriate schema queries
        if db_type not in SCHEMA_QUERIES:
            db_type = 'postgresql'  # Fallback
        queries = SCHEMA_QUERIES[db_type]
        
        session = db_manager.get_sql_session(connection_name)
        
        try:
            if table_name is None:
                # Return list of all tables
                result = session.execute(text(queries["tables"]))
                tables = result.fetchall()
                
                if not tables:
                    return f"No tables found in database '{connection_name}'."
                
                output = f"# Database Schema: {connection_name}\n\n"
                output += f"**Database Type:** {db_type}\n\n"
                output += "## Tables\n\n"
                output += "| Table Name | Type |\n"
                output += "|------------|------|\n"
                
                for table in tables:
                    output += f"| {table[0]} | {table[1] if len(table) > 1 else 'TABLE'} |\n"
                
                output += f"\n**Total Tables:** {len(tables)}\n\n"
                output += "Use `database_schema_discovery(connection_name, table_name='<table>')` to get column details."
                
                return output
            
            else:
                # Return specific table schema
                output = f"# Table Schema: {table_name}\n\n"
                output += f"**Connection:** {connection_name}\n"
                output += f"**Database Type:** {db_type}\n\n"
                
                # Get columns
                output += "## Columns\n\n"
                
                if db_type == 'sqlite':
                    # SQLite uses PRAGMA
                    result = session.execute(text(f"PRAGMA table_info({table_name})"))
                    columns = result.fetchall()
                    
                    output += "| Column | Type | Nullable | Default | Primary Key |\n"
                    output += "|--------|------|----------|---------|-------------|\n"
                    
                    for col in columns:
                        # PRAGMA returns: cid, name, type, notnull, dflt_value, pk
                        nullable = "NO" if col[3] else "YES"
                        pk = "YES" if col[5] else "NO"
                        output += f"| {col[1]} | {col[2]} | {nullable} | {col[4] or '-'} | {pk} |\n"
                else:
                    # Standard INFORMATION_SCHEMA query
                    result = session.execute(
                        text(queries["columns"]), 
                        {"table_name": table_name}
                    )
                    columns = result.fetchall()
                    
                    if not columns:
                        return f"Table '{table_name}' not found in connection '{connection_name}'."
                    
                    output += "| Column | Type | Nullable | Default | Max Length |\n"
                    output += "|--------|------|----------|---------|------------|\n"
                    
                    for col in columns:
                        max_len = col[4] if col[4] else "-"
                        output += f"| {col[0]} | {col[1]} | {col[2]} | {col[3] or '-'} | {max_len} |\n"
                
                # Get primary keys
                if include_relationships and db_type != 'sqlite':
                    try:
                        result = session.execute(
                            text(queries["primary_keys"]), 
                            {"table_name": table_name}
                        )
                        pks = result.fetchall()
                        
                        if pks:
                            output += "\n## Primary Key\n\n"
                            output += ", ".join([pk[0] for pk in pks]) + "\n"
                    except Exception:
                        pass  # Primary key info not available
                
                # Get foreign keys
                if include_relationships and db_type != 'sqlite':
                    try:
                        result = session.execute(
                            text(queries["foreign_keys"]), 
                            {"table_name": table_name}
                        )
                        fks = result.fetchall()
                        
                        if fks:
                            output += "\n## Foreign Keys\n\n"
                            output += "| Column | References Table | References Column |\n"
                            output += "|--------|------------------|-------------------|\n"
                            for fk in fks:
                                output += f"| {fk[0]} | {fk[1]} | {fk[2]} |\n"
                    except Exception:
                        pass  # Foreign key info not available
                
                return output
                
        finally:
            session.close()
            
    except Exception as e:
        error_msg = str(e)
        log.error(f"[DB Tool] Schema discovery error: {error_msg}")
        
        if "does not exist" in error_msg.lower():
            return f"Error: Connection '{connection_name}' does not exist. Please check the connection name."
        
        return f"Error discovering schema: {error_msg}"


def database_query_tool(
    connection_name: str,
    query: str,
    limit: Optional[int] = None,
    output_format: str = "table"
) -> str:
    """
    Execute a SQL SELECT query against a pre-configured database connection and return results.
    
    This tool allows agents to execute SQL queries against databases. Query safety is enforced
    by a configurable blocked commands list per connection. Use database_schema_discovery first
    to understand table structure.
    
    IMPORTANT: Always use database_schema_discovery BEFORE writing queries to ensure
    you use correct table and column names.
    
    Args:
        connection_name (str): Name of the pre-configured database connection
                               (e.g., 'sales_db', 'crm_database', 'analytics_db').
                               This must match a connection in the foundry's database connections.
        query (str): The SQL query to execute. Allowed operations depend on the connection's
                     blocked commands configuration. By default only SELECT is allowed.
                     Supports standard SQL including JOINs, GROUP BY, ORDER BY, etc.
        limit (int, optional): Maximum number of rows to return. Defaults to 100.
                               Use smaller limits for large result sets.
        output_format (str): Output format - 'table' (markdown table), 'json' (JSON array),
                             or 'summary' (count + sample rows). Default is 'table'.
    
    Returns:
        str: Query results in the specified format, or error message if query fails.
    
    Example:
        # Simple query
        result = database_query_tool(
            connection_name="sales_db",
            query="SELECT customer_name, email FROM customers WHERE status = 'active'"
        )
        
        # Query with aggregation
        result = database_query_tool(
            connection_name="sales_db",
            query="SELECT category, COUNT(*) as count, SUM(amount) as total FROM orders GROUP BY category",
            output_format="json"
        )
        
        # Query with limit
        result = database_query_tool(
            connection_name="analytics_db",
            query="SELECT * FROM events ORDER BY created_at DESC",
            limit=50
        )
    
    Security Notes:
        - Allowed operations are controlled by the connection's blocked commands list
        - By default: DROP, DELETE, UPDATE, INSERT, ALTER, CREATE, TRUNCATE, EXEC, GRANT, REVOKE are blocked
        - Remove a keyword from blocked list to allow that operation (e.g., remove INSERT to permit inserts)
        - Custom blocked commands can be configured per connection via the API
        - Results are limited to prevent token overflow
    """
    # Get connection-specific blocked commands (falls back to defaults if not configured)
    blocked_commands = _get_connection_blocked_commands_sync(connection_name)
    
    # Validate query safety with connection-specific blocked commands
    validation = _validate_query_safety(query, blocked_commands)
    if not validation["is_safe"]:
        return f"🚫 **Security Error:** {validation['error']}"
    
    # Set default limit
    if limit is None:
        limit = MAX_ROWS_LIMIT
    limit = min(limit, MAX_ROWS_LIMIT)  # Enforce maximum
    
    try:
        db_manager = _get_db_manager()
        db_type = _detect_db_type(connection_name)
        
        log.info(f"[DB Tool] Executing query on '{connection_name}'")
        
        session = db_manager.get_sql_session(connection_name)
        
        try:
            # Only add LIMIT for SELECT queries (not for INSERT, UPDATE, DELETE, etc.)
            query_upper = query.strip().upper()
            is_select = query_upper.startswith("SELECT") or query_upper.startswith("WITH")
            
            if is_select and "LIMIT" not in query_upper:
                query = f"{query.rstrip().rstrip(';')} LIMIT {limit}"
            
            result = session.execute(text(query))
            
            # For non-SELECT queries (INSERT, UPDATE, DELETE), commit and return affected rows
            if not is_select:
                session.commit()
                affected = result.rowcount if result.rowcount >= 0 else 0
                return f"\u2705 Query executed successfully on `{connection_name}`.\n\n**Rows affected:** {affected}"
            
            rows = result.fetchall()
            columns = list(result.keys())
            
            if not rows:
                return f"✅ Query executed successfully on `{connection_name}`.\n\n**Result:** No rows returned."
            
            # Format output based on requested format
            if output_format == "json":
                data = [dict(zip(columns, [str(v) if v is not None else None for v in row])) for row in rows]
                output = f"✅ Query executed successfully on `{connection_name}`.\n\n"
                output += f"**Rows returned:** {len(rows)}\n\n"
                output += "```json\n"
                output += json.dumps(data, indent=2, default=str)
                output += "\n```"
                return output
            
            elif output_format == "summary":
                output = f"✅ Query executed successfully on `{connection_name}`.\n\n"
                output += f"**Total rows:** {len(rows)}\n"
                output += f"**Columns:** {', '.join(columns)}\n\n"
                output += "**Sample (first 5 rows):**\n\n"
                output += _format_results_as_table(columns, rows[:5])
                return output
            
            else:  # table format (default)
                output = f"✅ Query executed successfully on `{connection_name}`.\n\n"
                output += f"**Rows returned:** {len(rows)}\n\n"
                output += _format_results_as_table(columns, rows)
                return output
                
        finally:
            session.close()
            
    except Exception as e:
        error_msg = str(e)
        log.error(f"[DB Tool] Query execution error: {error_msg}")
        
        if "does not exist" in error_msg.lower():
            return f"🚫 **Connection Error:** Connection '{connection_name}' does not exist."
        elif "syntax" in error_msg.lower():
            return f"🚫 **SQL Syntax Error:** {error_msg}\n\nPlease check your query syntax."
        elif "column" in error_msg.lower() and "not found" in error_msg.lower():
            return f"🚫 **Column Error:** {error_msg}\n\nUse `database_schema_discovery` to check valid column names."
        elif "table" in error_msg.lower() or "relation" in error_msg.lower():
            return f"🚫 **Table Error:** {error_msg}\n\nUse `database_schema_discovery` to check valid table names."
        
        return f"🚫 **Database Error:** {error_msg}"


def database_sample_data(
    connection_name: str,
    table_name: str,
    num_rows: int = 5
) -> str:
    """
    Get sample rows from a database table to understand the data format and content.
    
    This is useful for understanding what kind of data is in a table before
    writing complex queries. Returns a few sample rows with all columns.
    
    Args:
        connection_name (str): Name of the database connection.
        table_name (str): Name of the table to sample from.
        num_rows (int): Number of sample rows to return. Default is 5, max is 20.
    
    Returns:
        str: Sample rows from the table formatted as a markdown table.
    
    Example:
        # Get 5 sample rows from customers table
        sample = database_sample_data(
            connection_name="sales_db",
            table_name="customers"
        )
        
        # Get 10 sample rows
        sample = database_sample_data(
            connection_name="sales_db",
            table_name="orders",
            num_rows=10
        )
    """
    # Sanitize table name to prevent SQL injection
    if not re.match(r'^[a-zA-Z_][a-zA-Z0-9_]*$', table_name):
        return f"🚫 **Error:** Invalid table name '{table_name}'. Table names must contain only letters, numbers, and underscores."
    
    num_rows = min(max(1, num_rows), 20)  # Clamp between 1 and 20
    
    query = f"SELECT * FROM {table_name} LIMIT {num_rows}"
    
    result = database_query_tool(
        connection_name=connection_name,
        query=query,
        limit=num_rows,
        output_format="table"
    )
    
    # Add context to the result
    header = f"# Sample Data: {table_name}\n\n"
    header += f"**Connection:** {connection_name}\n"
    header += f"**Sample Size:** {num_rows} rows\n\n"
    
    return header + result.replace(f"Query executed successfully on `{connection_name}`.", "")


def database_table_stats(
    connection_name: str,
    table_name: str
) -> str:
    """
    Get basic statistics about a database table including row count and column info.
    
    Use this to understand the size and structure of a table before querying.
    
    Args:
        connection_name (str): Name of the database connection.
        table_name (str): Name of the table to get stats for.
    
    Returns:
        str: Table statistics including row count, column count, and sample values.
    
    Example:
        stats = database_table_stats(
            connection_name="sales_db",
            table_name="orders"
        )
    """
    # Sanitize table name
    if not re.match(r'^[a-zA-Z_][a-zA-Z0-9_]*$', table_name):
        return f"🚫 **Error:** Invalid table name '{table_name}'."
    
    try:
        db_manager = _get_db_manager()
        session = db_manager.get_sql_session(connection_name)
        
        try:
            # Get row count
            count_result = session.execute(text(f"SELECT COUNT(*) FROM {table_name}"))
            row_count = count_result.fetchone()[0]
            
            # Get schema info
            schema_info = database_schema_discovery(
                connection_name=connection_name,
                table_name=table_name,
                include_relationships=True
            )
            
            output = f"# Table Statistics: {table_name}\n\n"
            output += f"**Connection:** {connection_name}\n"
            output += f"**Total Rows:** {row_count:,}\n\n"
            output += schema_info.replace(f"# Table Schema: {table_name}\n\n", "")
            
            return output
            
        finally:
            session.close()
            
    except Exception as e:
        return f"🚫 **Error:** {str(e)}"


# =============================================================================
# MONGODB TOOLS
# =============================================================================

def mongodb_query_tool(
    connection_name: str,
    collection_name: str,
    query_filter: Optional[str] = None,
    projection: Optional[str] = None,
    limit: int = 20
) -> str:
    """
    Query a MongoDB collection and return documents.
    
    This tool allows agents to fetch data from MongoDB databases using the
    configured connection. Only read operations are allowed.
    
    Args:
        connection_name (str): Name of the MongoDB connection.
        collection_name (str): Name of the collection to query.
        query_filter (str, optional): JSON string representing the query filter.
                                       Example: '{"status": "active", "age": {"$gt": 18}}'
        projection (str, optional): JSON string specifying fields to include/exclude.
                                     Example: '{"name": 1, "email": 1, "_id": 0}'
        limit (int): Maximum documents to return. Default 20, max 100.
    
    Returns:
        str: Query results as formatted JSON.
    
    Example:
        # Get all active users
        result = mongodb_query_tool(
            connection_name="user_db",
            collection_name="users",
            query_filter='{"status": "active"}',
            limit=10
        )
        
        # Get specific fields
        result = mongodb_query_tool(
            connection_name="user_db",
            collection_name="users",
            query_filter='{"role": "admin"}',
            projection='{"name": 1, "email": 1}'
        )
    """
    try:
        import asyncio
        from bson import ObjectId
        
        db_manager = _get_db_manager()
        db = db_manager.get_mongo_database(connection_name)
        collection = db[collection_name]
        
        # Parse filter and projection
        filter_dict = json.loads(query_filter) if query_filter else {}
        projection_dict = json.loads(projection) if projection else None
        
        limit = min(max(1, limit), 100)
        
        # Execute query asynchronously
        async def run_query():
            cursor = collection.find(filter_dict, projection_dict).limit(limit)
            documents = await cursor.to_list(length=limit)
            return documents
        
        # Run in event loop
        loop = asyncio.get_event_loop()
        if loop.is_running():
            # If already in async context, create a new task
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor() as executor:
                documents = executor.submit(asyncio.run, run_query()).result()
        else:
            documents = loop.run_until_complete(run_query())
        
        # Convert ObjectIds to strings
        def clean_doc(doc):
            for key, value in doc.items():
                if isinstance(value, ObjectId):
                    doc[key] = str(value)
                elif isinstance(value, dict):
                    clean_doc(value)
            return doc
        
        documents = [clean_doc(doc) for doc in documents]
        
        output = f"✅ Query executed on `{connection_name}.{collection_name}`.\n\n"
        output += f"**Documents returned:** {len(documents)}\n\n"
        output += "```json\n"
        output += json.dumps(documents, indent=2, default=str)
        output += "\n```"
        
        return output
        
    except Exception as e:
        log.error(f"[DB Tool] MongoDB query error: {e}")
        return f"🚫 **MongoDB Error:** {str(e)}"


def mongodb_list_collections(connection_name: str) -> str:
    """
    List all collections in a MongoDB database.
    
    Args:
        connection_name (str): Name of the MongoDB connection.
    
    Returns:
        str: List of collection names in the database.
    
    Example:
        collections = mongodb_list_collections(connection_name="user_db")
    """
    try:
        import asyncio
        
        db_manager = _get_db_manager()
        db = db_manager.get_mongo_database(connection_name)
        
        async def get_collections():
            return await db.list_collection_names()
        
        loop = asyncio.get_event_loop()
        if loop.is_running():
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor() as executor:
                collections = executor.submit(asyncio.run, get_collections()).result()
        else:
            collections = loop.run_until_complete(get_collections())
        
        output = f"# Collections in {connection_name}\n\n"
        
        if not collections:
            return output + "No collections found."
        
        for coll in sorted(collections):
            output += f"- {coll}\n"
        
        output += f"\n**Total Collections:** {len(collections)}"
        
        return output
        
    except Exception as e:
        log.error(f"[DB Tool] MongoDB list collections error: {e}")
        return f"🚫 **MongoDB Error:** {str(e)}"


# =============================================================================
# TOOL EXPORT FOR ONBOARDING
# =============================================================================

# These are the main tools to be onboarded to the IAF Foundry (3 core tools)
EXPORTABLE_TOOLS = [
    database_schema_discovery,
    database_query_tool,
    database_sample_data,
    database_table_stats,
    mongodb_query_tool,
    mongodb_list_collections,
]

__all__ = [
    "database_schema_discovery",
    "database_query_tool", 
    "database_sample_data",
    "database_table_stats",
    "mongodb_query_tool",
    "mongodb_list_collections",
    "EXPORTABLE_TOOLS",
]
