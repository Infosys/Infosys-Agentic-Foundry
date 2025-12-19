# Data Connectors

The Agentic Foundry supports database connectivity through Data Connectors, allowing you to connect to and interact with different database systems for your agent workflows.

## Supported Databases

Currently, the foundry supports two database types:

- **PostgreSQL** - Enterprise-grade relational database
- **SQLite** - Lightweight file-based database
- **MySQL** - Popular open-source relational database, widely used for web applications
- **MongoDB** - Leading NoSQL document database, ideal for flexible and scalable data storage

## Creating Database Connections

### PostgreSQL Connection

To create a new PostgreSQL connection:

1. **Connection Name**: Enter a unique name for your connection
2. **Database Type**: Select "PostgreSQL"
3. **Host**: Database server hostname or IP address
4. **Port**: Database port (default: 5432)
5. **Database**: Database name to connect to
6. **Username**: Database username
7. **Password**: Database password
8. Click **Connect** to establish the connection

**Example Configuration:**
```
Connection Name: my_postgres_db
Database Type: PostgreSQL
Host: localhost
Port: 5432
Database: myapp_production
Username: db_user
Password: ********
```

### SQLite Connection

To create a new SQLite connection:

1. **Connection Name**: Enter a unique name for your connection
2. **Database Type**: Select "SQLite"
3. **New SQLite DB File**: Specify the path to your SQLite database file
4. Click **Connect** to establish the connection

**Example Configuration:**
```
Connection Name: my_sqlite_db
Database Type: SQLite
New SQLite DB File: database.db
```

### MySQL Connection

To create a new MySQL connection:

1. **Connection Name**: Enter a unique name for your connection
2. **Database Type**: Select "MySQL"
3. **Host**: Database server hostname or IP address
4. **Port**: Database port
5. **Database**: Database name to connect to
6. **Username**: Database username
7. **Password**: Database password
8. Click **Connect** to establish the connection

**Example Configuration:**
```
Connection Name: mysql_db
Database Type: MySQL
Host: localhost
Port: 3306
Database: myapp_production
Username: db_user
Password: ********
```

### MongoDB Connection

To create a new MongoDB connection:

1. **Connection Name**: Enter a unique name for your connection
2. **Database Type**: Select "MongoDB"
3. **Host**: Database server hostname or IP address
4. **Port**: Database port
5. **Database**: Database name to connect to
6. **Username**: Database username
7. **Password**: Database password
8. Click **Connect** to establish the connection

**Example Configuration:**
```
Connection Name: mongo_db
Database Type: MongoDB
Host: localhost
Port: 27017
Database: myapp_production
Username: db_user
Password: ********
```

## Data Connector Features

### Run Button Functionality

The **Run** button in Data Connectors provides an interactive query interface:

1. **Select Connection Name**: Choose from your active database connections
2. **Enter NLP Query**: Write your request in natural language
3. **Generate Query**: Click "Generate Query" to convert natural language to SQL
4. **Review and Edit**: Examine the generated  query and make modifications if needed
5. **Run Query**: Execute the query , it will show the output

**Example NLP Queries:**
- "Create a table called users with id, name, and email columns"
- "Insert a new user with name John and email john@example.com"
- "Show all users from the users table"
- "Update user with id 1 to have email newemail@example.com"

### Manage Button Functionality

The **Manage** button allows you to control your database connections:

### Available Actions:

- **Activate**: Enable a connection for to use that  in agent inferencing
- **Deactivate**: Disable a connection (prevents use in agents)
- **Delete**: Permanently remove the connection

!!! warning "Connection Status"
    A connection must be **active** to be used during agent inferencing. Inactive connections will not be available to agents.

!!! danger "Delete Warning"
    The delete option permanently removes the connection. This action cannot be undone.

## Using Data Connectors in Agent Inferencing

**Connection Requirements**

When using agents that contain database tools:

1. **Activate Connection**: Ensure the required database connection is active in Data Connectors
2. **Provide DB Key**: Supply the connection name as the database key during inferencing
3. **Tool Execution**: The agent will use the specified connection to fetch database information

**Error Handling**

If a database connection is not properly configured:

- The agent will return an error message
- No output will be produced from database-related tools
- Ensure the connection is active and the correct connection name is provided

**Sample Tool Implementation**

Here's an example of how to create a database tool for your agents:

```python
def fetch_all_from_xyz(connection_name: str):
    """
    Fetches all records from the 'xyz' table in the specified database using the provided database key.
    
    Args:
        connection_name (str): The key used to identify and connect to the specific database.
    
    Returns:
        list: A list of dictionaries, where each dictionary represents a row from the 'xyz' table.
    """
    from MultiDBConnection_Manager import get_connection_manager
    from sqlalchemy import text
    
    try:
        manager = get_connection_manager()
        session = manager.get_sql_session(connection_name)
        result = session.execute(text('SELECT * FROM xyz'))
        rows = result.fetchall()
        session.close()
        return [dict(row._mapping) for row in rows]
    except Exception as e:
        if 'session' in locals():
            session.close()
        return f'Error fetching data from database {connection_name}: {str(e)}'
```

## Important Notes for Tool Development

**Required Imports**

Always include these import statements in your database tools:

```python
from MultiDBConnection_Manager import get_connection_manager
from sqlalchemy import text
```

**Connection Manager Usage**

Follow this pattern for database operations:

```python
# Get the singleton instance of MultiDBConnectionManager
manager = get_connection_manager()

# Get a SQLAlchemy session for the specified connection
session = manager.get_sql_session(connection_name)
```

**Session Management**

**Always close sessions after use:**

```python
try:
    # Your database operations here
    pass
except Exception as e:
    # Handle errors
    pass
finally:
    if 'session' in locals():
        session.close()
```

**Best Practices Checklist**

-  **No need to manually activate a connection** before using it in agents; when you call `get_sql_session(connection_name)`, the connection will be activated automatically if the `connection_name` exists in the database.
-  **Include required imports** in your tool functions
-  **Always close database sessions** after use






