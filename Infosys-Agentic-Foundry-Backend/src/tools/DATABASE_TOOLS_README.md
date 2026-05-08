# IAF Database Tools - Documentation

## Overview

The IAF Database Tools provide a standardized way for agents to interact with databases. These tools support schema discovery, query execution, and data exploration across multiple database types.

## Supported Databases

| Database | Connection Type | Status |
|----------|-----------------|--------|
| PostgreSQL | SQL | ✅ Full Support |
| MySQL | SQL | ✅ Full Support |
| SQLite | SQL | ✅ Full Support |
| Azure SQL | SQL | ✅ Full Support |
| MongoDB | NoSQL | ✅ Full Support |

## Available Tools

### 1. `database_list_connections`
Lists all configured database connections in the IAF Foundry.

**When to use:** Start here to discover available databases.

```python
result = database_list_connections()
# Returns: Table of connection names, types, and hosts
```

### 2. `database_schema_discovery`
Discovers schema including tables, columns, data types, and relationships.

**When to use:** Before writing ANY SQL query to understand table structure.

```python
# List all tables
schema = database_schema_discovery(connection_name="sales_db")

# Get specific table columns
schema = database_schema_discovery(
    connection_name="sales_db",
    table_name="orders"
)
```

### 3. `database_query_tool`
Executes SQL SELECT queries against configured connections.

**When to use:** After discovering schema, to fetch actual data.

```python
result = database_query_tool(
    connection_name="sales_db",
    query="SELECT customer_name, SUM(amount) FROM orders GROUP BY customer_name",
    limit=50,
    output_format="table"  # or "json", "summary"
)
```

### 4. `database_sample_data`
Gets sample rows from a table to understand data format.

**When to use:** To preview data before writing complex queries.

```python
sample = database_sample_data(
    connection_name="sales_db",
    table_name="customers",
    num_rows=10
)
```

### 5. `database_table_stats`
Gets basic statistics about a table.

**When to use:** To understand table size and structure.

```python
stats = database_table_stats(
    connection_name="sales_db",
    table_name="orders"
)
```

### 6. `mongodb_query_tool`
Queries MongoDB collections.

**When to use:** For NoSQL database queries.

```python
result = mongodb_query_tool(
    connection_name="user_db",
    collection_name="users",
    query_filter='{"status": "active"}',
    limit=20
)
```

### 7. `mongodb_list_collections`
Lists collections in a MongoDB database.

```python
collections = mongodb_list_collections(connection_name="user_db")
```

## Recommended Workflow

```
┌─────────────────────────────────────────────────────────────────┐
│                    DATABASE QUERY WORKFLOW                       │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  1. LIST CONNECTIONS                                             │
│     └─► database_list_connections()                              │
│         "What databases are available?"                          │
│                                                                  │
│  2. DISCOVER SCHEMA                                              │
│     └─► database_schema_discovery(conn, table=None)              │
│         "What tables exist? What columns?"                       │
│                                                                  │
│  3. SAMPLE DATA (Optional)                                       │
│     └─► database_sample_data(conn, table, 5)                     │
│         "What does the data look like?"                          │
│                                                                  │
│  4. EXECUTE QUERY                                                │
│     └─► database_query_tool(conn, query)                         │
│         "Run the actual SQL query"                               │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

## Security Features

| Feature | Description |
|---------|-------------|
| **SELECT Only** | Only SELECT queries allowed; INSERT/UPDATE/DELETE blocked |
| **Keyword Blocking** | Dangerous keywords (DROP, TRUNCATE, etc.) rejected |
| **Row Limits** | Results capped at 100 rows to prevent token overflow |
| **Table Name Validation** | SQL injection prevention via name sanitization |
| **Centralized Credentials** | Connection credentials managed in foundry, not in tools |

## Onboarding Tools to IAF

### Method 1: Via API

```bash
POST /tool/create
Content-Type: application/json

{
    "tool_description": "Executes SQL SELECT queries against configured databases",
    "code_snippet": "<paste function code from database_tools_onboarding.py>",
    "model_name": "gpt-4o",
    "created_by": "your_email@company.com",
    "tag_ids": ["<database-tag-id>"]
}
```

### Method 2: Via IAF UI

1. Navigate to **Tools → Create New Tool**
2. Paste function code from `database_tools_onboarding.py`
3. Add description
4. Select tags (e.g., "database", "data-retrieval")
5. Submit for approval

## File Structure

```
src/tools/
├── __init__.py                    # Module exports
├── database_tools.py              # Full implementation (use in agents)
├── database_tools_onboarding.py   # Standalone functions for tool onboarding
├── database_tools_demo.py         # Demo agent showing usage
└── DATABASE_TOOLS_README.md       # This documentation
```

## Example Agent System Prompt

```
You are a Database Query Assistant. You help users explore and query databases.

## Your Workflow (ALWAYS FOLLOW)

1. Use `database_list_connections` to see available databases
2. Use `database_schema_discovery` to explore tables
3. Use `database_sample_data` to preview data (optional)
4. Use `database_query_tool` to execute queries

## Rules
- ALWAYS discover schema BEFORE writing queries
- Only SELECT queries are allowed
- Explain results in natural language
```

## Troubleshooting

| Error | Cause | Solution |
|-------|-------|----------|
| "Connection does not exist" | Invalid connection name | Use `database_list_connections()` to check names |
| "Column not found" | Wrong column name | Use `database_schema_discovery()` to check columns |
| "Security Error" | Forbidden SQL keyword | Use only SELECT queries |
| "Table not found" | Wrong table name | Use `database_schema_discovery()` without table_name |

## Version History

| Version | Date | Changes |
|---------|------|---------|
| 1.0.0 | 2026-02-09 | Initial release with SQL & MongoDB support |

---

© 2024-25 Infosys Limited, Bangalore, India. All Rights Reserved.
