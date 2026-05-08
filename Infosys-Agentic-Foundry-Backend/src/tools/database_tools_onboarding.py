# © 2024-25 Infosys Limited, Bangalore, India. All Rights Reserved.
"""
Database Tools - Individual Tool Code Snippets for IAF Onboarding

This file contains standalone tool functions that can be directly copied
and onboarded to the IAF Foundry via the /tool/create API.

Each tool is self-contained with all necessary imports and can be
onboarded independently.

USAGE:
1. Copy the desired tool function code
2. Use the IAF /tool/create endpoint with:
   - tool_description: (provided below each function)
   - code_snippet: (the function code)
   - model_name: "gpt-4o" (or your preferred model)
   - tag_ids: ["database", "data-retrieval"] (suggested tags)
"""

# =============================================================================
# TOOL 1: Database Schema Discovery
# =============================================================================
# Tool Description: "Discovers and returns the schema of a database including 
# tables, columns, data types, and relationships. Use this before writing SQL 
# queries to understand the database structure."

def database_schema_discovery(
    connection_name: str,
    table_name: str = None,
    include_relationships: bool = True
) -> str:
    """
    Discover database schema for a configured connection. Use this BEFORE writing SQL queries
    to understand the table structure, column names, data types, and relationships.
    
    Args:
        connection_name (str): Name of the pre-configured database connection 
                               (e.g., 'sales_db', 'crm_database').
        table_name (str, optional): Specific table to get schema for. If not provided,
                                    returns list of all tables.
        include_relationships (bool): Whether to include foreign key relationships. Default True.
    
    Returns:
        str: Schema information formatted as markdown with tables, columns, types, and keys.
    
    Example:
        # Get all tables
        schema = database_schema_discovery(connection_name="sales_db")
        
        # Get specific table
        schema = database_schema_discovery(connection_name="sales_db", table_name="orders")
    """
    from sqlalchemy import text
    from MultiDBConnection_Manager import get_connection_manager
    
    SCHEMA_QUERIES = {
        "postgresql": {
            "tables": "SELECT table_name, table_type FROM information_schema.tables WHERE table_schema = 'public' ORDER BY table_name",
            "columns": "SELECT column_name, data_type, is_nullable, column_default FROM information_schema.columns WHERE table_schema = 'public' AND table_name = :table_name ORDER BY ordinal_position",
        },
        "mysql": {
            "tables": "SELECT table_name, table_type FROM information_schema.tables WHERE table_schema = DATABASE() ORDER BY table_name",
            "columns": "SELECT column_name, data_type, is_nullable, column_default FROM information_schema.columns WHERE table_schema = DATABASE() AND table_name = :table_name ORDER BY ordinal_position",
        },
        "sqlite": {
            "tables": "SELECT name as table_name, type as table_type FROM sqlite_master WHERE type IN ('table', 'view') AND name NOT LIKE 'sqlite_%' ORDER BY name",
            "columns": None,  # Uses PRAGMA
        }
    }
    
    try:
        db_manager = get_connection_manager()
        config = db_manager._fetch_connection_config_sync(connection_name)
        db_type = config.get('db_type', 'postgresql').lower()
        
        if db_type not in SCHEMA_QUERIES:
            db_type = 'postgresql'
        queries = SCHEMA_QUERIES[db_type]
        
        session = db_manager.get_sql_session(connection_name)
        
        try:
            if table_name is None:
                result = session.execute(text(queries["tables"]))
                tables = result.fetchall()
                
                if not tables:
                    return f"No tables found in database '{connection_name}'."
                
                output = f"# Database Schema: {connection_name}\n\n"
                output += f"**Database Type:** {db_type}\n\n"
                output += "## Tables\n\n| Table Name | Type |\n|------------|------|\n"
                
                for table in tables:
                    output += f"| {table[0]} | {table[1] if len(table) > 1 else 'TABLE'} |\n"
                
                output += f"\n**Total Tables:** {len(tables)}"
                return output
            
            else:
                output = f"# Table Schema: {table_name}\n\n**Connection:** {connection_name}\n\n## Columns\n\n"
                
                if db_type == 'sqlite':
                    result = session.execute(text(f"PRAGMA table_info({table_name})"))
                    columns = result.fetchall()
                    output += "| Column | Type | Nullable | Default | PK |\n|--------|------|----------|---------|----|\n"
                    for col in columns:
                        output += f"| {col[1]} | {col[2]} | {'NO' if col[3] else 'YES'} | {col[4] or '-'} | {'YES' if col[5] else 'NO'} |\n"
                else:
                    result = session.execute(text(queries["columns"]), {"table_name": table_name})
                    columns = result.fetchall()
                    
                    if not columns:
                        return f"Table '{table_name}' not found."
                    
                    output += "| Column | Type | Nullable | Default |\n|--------|------|----------|----------|\n"
                    for col in columns:
                        output += f"| {col[0]} | {col[1]} | {col[2]} | {col[3] or '-'} |\n"
                
                return output
                
        finally:
            session.close()
            
    except Exception as e:
        return f"Error: {str(e)}"


# =============================================================================
# TOOL 2: Database Query Tool
# =============================================================================
# Tool Description: "Executes SQL SELECT queries against pre-configured database 
# connections and returns results. Only read operations allowed for safety."

def database_query_tool(
    connection_name: str,
    query: str,
    limit: int = 100,
    output_format: str = "table"
) -> str:
    """
    Execute a SQL SELECT query against a pre-configured database connection.
    
    IMPORTANT: Use database_schema_discovery first to understand table structure.
    Allowed SQL operations depend on the connection's blocked commands configuration.
    
    Args:
        connection_name (str): Name of the database connection (e.g., 'sales_db').
        query (str): SQL query to execute. Blocked operations depend on connection config.
        limit (int): Maximum rows to return. Default 100.
        output_format (str): 'table' (markdown), 'json', or 'summary'. Default 'table'.
    
    Returns:
        str: Query results in specified format.
    
    Example:
        result = database_query_tool(
            connection_name="sales_db",
            query="SELECT name, email FROM customers WHERE status = 'active'"
        )
    """
    import json
    import re
    from sqlalchemy import text
    from MultiDBConnection_Manager import get_connection_manager
    
    DANGEROUS = ["DROP", "DELETE", "UPDATE", "INSERT", "ALTER", "CREATE", "TRUNCATE", "EXEC", "--"]
    
    # Validate query against blocked commands list (single source of truth)
    query_upper = query.strip().upper()
    for kw in DANGEROUS:
        if re.search(r'\b' + re.escape(kw) + r'\b', query_upper):
            return f"🚫 Security Error: '{kw}' is blocked for this connection."
    
    limit = min(limit, 100)
    
    try:
        db_manager = get_connection_manager()
        session = db_manager.get_sql_session(connection_name)
        
        try:
            # Only add LIMIT for SELECT queries (not for INSERT, UPDATE, DELETE, etc.)
            is_select = query_upper.startswith("SELECT") or query_upper.startswith("WITH")
            
            if is_select and "LIMIT" not in query_upper:
                query = f"{query.rstrip().rstrip(';')} LIMIT {limit}"
            
            result = session.execute(text(query))
            
            # For non-SELECT queries (INSERT, UPDATE, DELETE), commit and return affected rows
            if not is_select:
                session.commit()
                affected = result.rowcount if result.rowcount >= 0 else 0
                return f"\u2705 Query executed on `{connection_name}`. Rows affected: {affected}"
            
            rows = result.fetchall()
            columns = list(result.keys())
            
            if not rows:
                return f"✅ Query on `{connection_name}`: No rows returned."
            
            if output_format == "json":
                data = [dict(zip(columns, [str(v) if v else None for v in row])) for row in rows]
                return f"✅ {len(rows)} rows returned.\n\n```json\n{json.dumps(data, indent=2)}\n```"
            
            # Table format
            widths = [max(len(str(c)), max(len(str(r[i]) if r[i] else "NULL") for r in rows)) for i, c in enumerate(columns)]
            
            output = f"✅ {len(rows)} rows from `{connection_name}`:\n\n"
            output += "| " + " | ".join(str(c).ljust(widths[i]) for i, c in enumerate(columns)) + " |\n"
            output += "|" + "|".join("-" * (w + 2) for w in widths) + "|\n"
            
            for row in rows:
                output += "| " + " | ".join(str(v if v else "NULL").ljust(widths[i]) for i, v in enumerate(row)) + " |\n"
            
            return output
            
        finally:
            session.close()
            
    except Exception as e:
        return f"🚫 Database Error: {str(e)}"


# =============================================================================
# TOOL 3: Database List Connections
# =============================================================================
# Tool Description: "Lists all available database connections configured in the 
# IAF Foundry. Use this to discover available databases before querying."

def database_list_connections() -> str:
    """
    List all available database connections configured in the IAF Foundry.
    
    Use this to discover what databases are available before running queries.
    
    Returns:
        str: Table of available connections with names and types.
    
    Example:
        connections = database_list_connections()
    """
    from sqlalchemy import text
    from MultiDBConnection_Manager import get_connection_manager
    
    try:
        db_manager = get_connection_manager()
        
        if db_manager._metadata_engine is None:
            return "No database connections configured."
        
        session = db_manager._metadata_session_factory()
        
        try:
            query = """
                SELECT connection_name, connection_database_type, connection_host, connection_database_name
                FROM db_connections_table ORDER BY connection_name
            """
            result = session.execute(text(query))
            connections = result.fetchall()
            
            if not connections:
                return "No database connections found."
            
            output = "# Available Database Connections\n\n"
            output += "| Connection Name | Type | Host | Database |\n"
            output += "|-----------------|------|------|----------|\n"
            
            for conn in connections:
                output += f"| {conn[0]} | {conn[1]} | {conn[2] or 'N/A'} | {conn[3]} |\n"
            
            output += f"\n**Total:** {len(connections)} connections"
            return output
            
        finally:
            session.close()
            
    except Exception as e:
        return f"Error: {str(e)}"


# =============================================================================
# TOOL 4: Database Sample Data
# =============================================================================
# Tool Description: "Gets sample rows from a database table to understand data 
# format and content before writing complex queries."

def database_sample_data(
    connection_name: str,
    table_name: str,
    num_rows: int = 5
) -> str:
    """
    Get sample rows from a table to understand its data format.
    
    Args:
        connection_name (str): Name of the database connection.
        table_name (str): Name of the table to sample.
        num_rows (int): Number of rows to return (1-20). Default 5.
    
    Returns:
        str: Sample rows formatted as markdown table.
    
    Example:
        sample = database_sample_data(connection_name="sales_db", table_name="customers")
    """
    import re
    from sqlalchemy import text
    from MultiDBConnection_Manager import get_connection_manager
    
    if not re.match(r'^[a-zA-Z_][a-zA-Z0-9_]*$', table_name):
        return f"🚫 Invalid table name: {table_name}"
    
    num_rows = min(max(1, num_rows), 20)
    
    try:
        db_manager = get_connection_manager()
        session = db_manager.get_sql_session(connection_name)
        
        try:
            result = session.execute(text(f"SELECT * FROM {table_name} LIMIT {num_rows}"))
            rows = result.fetchall()
            columns = list(result.keys())
            
            if not rows:
                return f"Table '{table_name}' is empty."
            
            widths = [max(len(str(c)), max(len(str(r[i]) if r[i] else "NULL") for r in rows)) for i, c in enumerate(columns)]
            
            output = f"# Sample Data: {table_name}\n\n**{len(rows)} rows**\n\n"
            output += "| " + " | ".join(str(c).ljust(widths[i]) for i, c in enumerate(columns)) + " |\n"
            output += "|" + "|".join("-" * (w + 2) for w in widths) + "|\n"
            
            for row in rows:
                output += "| " + " | ".join(str(v if v else "NULL").ljust(widths[i]) for i, v in enumerate(row)) + " |\n"
            
            return output
            
        finally:
            session.close()
            
    except Exception as e:
        return f"🚫 Error: {str(e)}"


# =============================================================================
# TOOL 5: Database Table Stats
# =============================================================================
# Tool Description: "Gets statistics about a database table including row count, 
# column information, and basic metrics."

def database_table_stats(
    connection_name: str,
    table_name: str
) -> str:
    """
    Get statistics about a database table including row count and column info.
    
    Args:
        connection_name (str): Name of the database connection.
        table_name (str): Name of the table.
    
    Returns:
        str: Table statistics with row count and schema info.
    
    Example:
        stats = database_table_stats(connection_name="sales_db", table_name="orders")
    """
    import re
    from sqlalchemy import text
    from MultiDBConnection_Manager import get_connection_manager
    
    if not re.match(r'^[a-zA-Z_][a-zA-Z0-9_]*$', table_name):
        return f"🚫 Invalid table name: {table_name}"
    
    try:
        db_manager = get_connection_manager()
        session = db_manager.get_sql_session(connection_name)
        
        try:
            # Get row count
            count_result = session.execute(text(f"SELECT COUNT(*) FROM {table_name}"))
            row_count = count_result.fetchone()[0]
            
            # Get column info
            config = db_manager._fetch_connection_config_sync(connection_name)
            db_type = config.get('db_type', 'postgresql').lower()
            
            if db_type == 'sqlite':
                col_result = session.execute(text(f"PRAGMA table_info({table_name})"))
                columns = col_result.fetchall()
                col_count = len(columns)
            else:
                col_result = session.execute(text(
                    f"SELECT COUNT(*) FROM information_schema.columns WHERE table_name = '{table_name}'"
                ))
                col_count = col_result.fetchone()[0]
            
            output = f"# Table Stats: {table_name}\n\n"
            output += f"**Connection:** {connection_name}\n"
            output += f"**Database Type:** {db_type}\n"
            output += f"**Total Rows:** {row_count:,}\n"
            output += f"**Total Columns:** {col_count}\n"
            
            return output
            
        finally:
            session.close()
            
    except Exception as e:
        return f"🚫 Error: {str(e)}"


# =============================================================================
# ONBOARDING INSTRUCTIONS
# =============================================================================
"""
To onboard these tools to IAF Foundry:

1. Via API:
   POST /tool/create
   {
       "tool_description": "<description from above>",
       "code_snippet": "<function code>",
       "model_name": "gpt-4o",
       "created_by": "your_email@company.com",
       "tag_ids": ["<database-tag-id>"]
   }

2. Via IAF UI:
   - Go to Tools > Create New Tool
   - Paste the function code
   - Add description
   - Select appropriate tags
   - Submit for approval

Recommended Tags:
- database
- data-retrieval
- sql
- analytics
"""
