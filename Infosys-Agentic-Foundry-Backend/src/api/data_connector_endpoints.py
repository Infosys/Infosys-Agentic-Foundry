# © 2024-25 Infosys Limited, Bangalore, India. All Rights Reserved.
import os
import uuid
import sqlite3 # For SQLite specific operations
from typing import Dict, Optional, Any, Union
from bson import ObjectId # For MongoDB ObjectId handling
from sqlalchemy import create_engine, text # For SQL Alchemy engine
from sqlalchemy.exc import SQLAlchemyError # For SQL Alchemy exceptions

from fastapi import APIRouter, Depends, HTTPException, Request, Form, UploadFile, File

from src.schemas import QueryGenerationRequest, QueryExecutionRequest, DBDisconnectRequest, MONGODBOperation

from MultiDBConnection_Manager import MultiDBConnectionRepository, get_connection_manager
from src.api.dependencies import ServiceProvider # The dependency provider
from src.database.services import ModelService # For generate_query endpoint
from telemetry_wrapper import logger as log, update_session_context # Your custom logger and context updater
from src.auth.authorization_service import AuthorizationService
from src.auth.models import User
from src.auth.dependencies import get_current_user

router = APIRouter(prefix="/data-connector", tags=["Data Connector"])


UPLOAD_DIR = "uploaded_sqlite_dbs"
os.makedirs(UPLOAD_DIR, exist_ok=True)


# Helper functions

async def _build_connection_string_helper(config: dict) -> str:
    db_type = config["db_type"].lower()
    if db_type == "mysql":
        return f"mysql+mysqlconnector://{config['username']}:{config['password']}@{config['host']}:{config['port']}/{config['database']}"
    if db_type == "postgresql":
        return f"postgresql+psycopg2://{config['username']}:{config['password']}@{config['host']}:{config['port']}/{config['database']}"
    if db_type == "azuresql":
        return f"mssql+pyodbc://{config['username']}:{config['password']}@{config['host']}:{config['port']}/{config['database']}?driver=ODBC+Driver+17+for+SQL+Server"
    if db_type == "sqlite":
        return f"sqlite:///{UPLOAD_DIR}/{config['database']}"
    if db_type == "mongodb":
        host = config["host"]
        port = config["port"]
        db_name = config["database"]
        username = config.get("username")
        password = config.get("password")
        if username and password:
            return f"mongodb://{username}:{password}@{host}:{port}/?authSource={db_name}"
        else:
            return f"mongodb://{host}:{port}/{db_name}"
    raise HTTPException(status_code=400, detail=f"Unsupported database type: {config['db_type']}")


async def _create_database_if_not_exists_helper(config: dict):
    db_type = config["db_type"].lower()
    db_name = config["database"]
    
    # SQLite DB creation not needed
    if db_type == "sqlite":
        # Connect to the database file (creates it if it doesn't exist)
        db_path = os.path.join(UPLOAD_DIR, db_name)

        if os.path.exists(db_path):
            raise HTTPException(status_code=400, detail=f"Database file '{db_name}' already exists")
        try:
            # File doesn't exist, so this will create it
            conn = sqlite3.connect(db_path)
            # Close the connection immediately to keep it empty
            conn.close()
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Error creating SQLite DB file: {str(e)}")
        return

    if db_type == "mongodb":
        return # MongoDB DB creation is implicit in connection

    # For SQL DBs, connect to admin DB for creation
    config_copy = config.copy()
    if db_type == "postgresql":
        config_copy["database"] = "postgres"
        engine = create_engine(await _build_connection_string_helper(config_copy), isolation_level="AUTOCOMMIT")
        with engine.connect() as conn:
            result = conn.execute(text("SELECT 1 FROM pg_database WHERE datname = :dbname"), {"dbname": db_name})
            if not result.fetchone():
                # Validate database name to prevent SQL injection
                import re
                if not re.match(r'^[a-zA-Z_][a-zA-Z0-9_]*$', db_name):
                    raise HTTPException(status_code=400, detail="Invalid database name")
                
                # Use string concatenation since parameterized queries don't work for identifiers
                conn.execute(text('CREATE DATABASE "' + db_name + '"'))
            return

    if db_type == "mysql":
        config_copy["database"] = ""
        engine = create_engine(await _build_connection_string_helper(config_copy))
        with engine.connect() as conn:
            with conn.begin(): # Use begin() context to control transactions
                 # Validate database name to prevent SQL injection
                import re
                if not re.match(r'^[a-zA-Z_][a-zA-Z0-9_]*$', db_name):
                    raise HTTPException(status_code=400, detail="Invalid database name")
                
                # Use string concatenation instead of f-string
                conn.execute(text("CREATE DATABASE IF NOT EXISTS `" + db_name + "`"))
                return

    raise HTTPException(status_code=400, detail=f"Database creation not supported for {config['db_type']}")

# Helper to clean MongoDB ObjectId
async def _clean_document_helper(doc: Dict[str, Any]) -> Dict[str, Any]:
    if not doc:
        return None
    if "_id" in doc and isinstance(doc["_id"], ObjectId):
        doc["_id"] = str(doc["_id"])
    for k, v in doc.items():
        if isinstance(v, ObjectId):
            doc[k] = str(v)
    return doc


# Endpoints

@router.post("/connect")
async def connect_to_database_endpoint(
        request: Request,
        name: str = Form(...),
        db_type: str = Form(...),
        host: Optional[str] = Form(None),
        port: Optional[int] = Form(None),
        username: Optional[str] = Form(None),
        password: Optional[str] = Form(None),
        database: Optional[str] = Form(None),
        flag_for_insert_into_db_connections_table: str = Form(None),
        # created_by: str = Form(...),  # <--- make sure to include this
        sql_file: Union[UploadFile, str, None] = File(None),
        db_connection_manager: MultiDBConnectionRepository = Depends(ServiceProvider.get_multi_db_connection_manager),
        authorization_service: AuthorizationService = Depends(ServiceProvider.get_authorization_service),
        user_data: User = Depends(get_current_user)
    ):
    """
    API endpoint to connect to a database and optionally save its configuration.

    Parameters:
    - request: The FastAPI Request object.
    - name: Unique name for the connection.
    - db_type: Type of database.
    - host, port, username etc.: Connection details.
    - flag_for_insert_into_db_connections_table: Flag to save config to DB.
    - sql_file: Optional SQL file for SQLite.
    - db_connection_manager: Dependency-injected MultiDBConnectionRepository.

    Returns:
    - Dict[str, Any]: Status message.
    """
    if isinstance(sql_file, str):
        sql_file = None
    # Check permissions first - data connectors require tools permission
    if not await authorization_service.check_operation_permission(user_data.email, user_data.role, "create", "tools"):
        raise HTTPException(status_code=403, detail="You don't have permission to create data connections. Only admins and developers can perform this action")
    
    user_id = request.cookies.get("user_id")
    user_session = request.cookies.get("user_session")
    update_session_context(user_session=user_session, user_id=user_id)

    manager = get_connection_manager()

    if flag_for_insert_into_db_connections_table == "1":
        name_exists = await db_connection_manager.check_connection_name_exists(name)
        if name_exists:
            raise HTTPException(status_code=400, detail=f"Connection name '{name}' already exists.")

    try:
        config = dict(
            name=name,
            db_type=db_type,
            host=host,
            port=port,
            username=username,
            password=password,
            database=database,
            flag_for_insert_into_db_connections_table=flag_for_insert_into_db_connections_table
        )

        # Adjust config based on DB type:
        if db_type.lower() == "sqlite":
            # For SQLite, host/port/user/pass not needed, database is file path
            config["host"] = None
            config["port"] = 0
            config["username"] = None
            config["password"] = None
            if sql_file is not None and flag_for_insert_into_db_connections_table == "1":
                config["database"] = sql_file.filename
                filename = os.path.basename(sql_file.filename)
                if not (filename.endswith(".db") or filename.endswith(".sqlite")):
                    raise HTTPException(status_code=400, detail="Only .db or .sqlite files are allowed")
                
                file_path = os.path.join(UPLOAD_DIR, filename)
                if os.path.exists(file_path):
                    raise HTTPException(status_code=400, detail="File with this name already exists")
                
                with open(file_path, "wb") as f:
                    content = await sql_file.read()
                    f.write(content)
            else:
                if flag_for_insert_into_db_connections_table=="1":
                    config["database"] = config["database"] + ".db"
                    await _create_database_if_not_exists_helper(config) # Create empty SQLite file

            manager.add_sql_database(config.get("name",""), await _build_connection_string_helper(config))
            session_sql = manager.get_sql_session(config.get("name",""))
            session_sql.commit()
            session_sql.close()

        elif db_type.lower() == "mongodb":
            manager.add_mongo_database(config.get("name",""), await _build_connection_string_helper(config), config.get("database",""))
            mongo_db = manager.get_mongo_database(config.get("name",""))
            try:
                await mongo_db.command("ping")
                log.info("[MongoDB] Connection test successful.")
            except Exception as e:
                active_mongo_connections = list(manager.mongo_clients.keys())
                if name in active_mongo_connections:
                    await manager.close_mongo_client(name)
                raise HTTPException(status_code=500, detail=f"MongoDB ping failed: {str(e)}")

        elif db_type.lower() in ["postgresql", "mysql"]:
            if flag_for_insert_into_db_connections_table=="1":
                await _create_database_if_not_exists_helper(config)
            manager.add_sql_database(config.get("name",""), await _build_connection_string_helper(config))
            

        else:
            raise HTTPException(status_code=500, detail=f"db_type name is incorrect:- mentioned is {db_type}")
    
        if flag_for_insert_into_db_connections_table == "1":
            connection_data = {
                "connection_id": str(uuid.uuid4()),
                "connection_name": name,
                "connection_database_type": db_type,
                "connection_host": config.get("host", ""),
                "connection_port": config.get("port", 0),
                "connection_username": config.get("username", ""),
                "connection_password": config.get("password", ""),
                "connection_database_name": config.get("database", "")
            }
            result = await db_connection_manager.insert_into_db_connections_table(connection_data)
            if result.get("is_created"):
                return {
                    "message": f"Connected to {db_type} database '{database}' and saved configuration.",
                    **result
                }
            else:
                return {
                    "message": f"Connected to {db_type} database '{database}', but failed to save configuration.--{result.get('message')}",
                    # **result
                }
        else:
            return {"message": f"Connected to {db_type} database '{database}'."}

    except SQLAlchemyError as e:
        raise HTTPException(status_code=500, detail=f"Connection failed: {str(e)}")

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Unexpected error: {str(e)}")


@router.post("/disconnect")
async def disconnect_database_endpoint(
    request: Request, 
    disconnect_request: DBDisconnectRequest, 
    db_connection_manager: MultiDBConnectionRepository = Depends(ServiceProvider.get_multi_db_connection_manager),
    authorization_service: AuthorizationService = Depends(ServiceProvider.get_authorization_service),
    user_data: User = Depends(get_current_user)
):
    """
    API endpoint to disconnect from a database.

    Parameters:
    - request: The FastAPI Request object.
    - disconnect_request: Pydantic model containing disconnection details.
    - db_connection_manager: Dependency-injected MultiDBConnectionRepository.

    Returns:
    - Dict[str, str]: Status message.
    """
    # Check permissions first - data connectors require tools permission
    if not await authorization_service.check_operation_permission(user_data.email, user_data.role, "delete", "tools"):
        raise HTTPException(status_code=403, detail="You don't have permission to delete data connections. Only admins and developers can perform this action")
    
    user_id = request.cookies.get("user_id")
    user_session = request.cookies.get("user_session")
    update_session_context(user_session=user_session, user_id=user_id)

    name = disconnect_request.name
    db_type = disconnect_request.db_type.lower()
    manager = get_connection_manager()
 
    # Get current active connections
    active_sql_connections = list(manager.sql_engines.keys())
    active_mongo_connections = list(manager.mongo_clients.keys())

    if disconnect_request.flag=="1":
        delete_result = await db_connection_manager.delete_connection_by_name(name)

    try:
        if db_type == "mongodb":
            if name in active_mongo_connections:
                await manager.close_mongo_client(name)
                if disconnect_request.flag=="1":
                    return {"message": f"Disconnected MongoDB connection '{name}' successfully"}
                else:
                    return {"message": f"Deactivated MongoDB connection '{name}' successfully"}
                    # return {"message": f"MongoDB connection '{name}' was not active "}
            else:
                if disconnect_request.flag=="1":
                    return {"message": f"Disconnected MongoDB connection '{name}' successfully"}
                else:
                    return {"message": f"Deactivated MongoDB connection '{name}' successfully"}
                    # return {"message": f"MongoDB connection '{name}' was not active "}
 
        else:  # SQL
            if name in active_sql_connections:
                manager.dispose_sql_engine(name)
                if disconnect_request.flag=="1":
                    return {"message": f"Disconnected SQL connection '{name}' successfully "}
                else:
                    return {"message": f"Deactivated SQL connection '{name}' successfully "}

            else:
                if disconnect_request.flag=="1":
                    return {"message": f"Disconnected SQL connection '{name}' successfully "}
                else:
                    return {"message": f"Deactivated SQL connection '{name}' successfully "}
 
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error while disconnecting: {str(e)}")


@router.post("/generate-query")
async def generate_query_endpoint(
    request: Request, 
    query_request: QueryGenerationRequest, 
    model_service: ModelService = Depends(ServiceProvider.get_model_service),
    authorization_service: AuthorizationService = Depends(ServiceProvider.get_authorization_service),
    user_data: User = Depends(get_current_user)
):
    """
    API endpoint to generate a database query from natural language.

    Parameters:
    - request: The FastAPI Request object.
    - query_request: Pydantic model containing database type and natural language query.
    - model_service: Dependency-injected ModelService instance.

    Returns:
    - Dict[str, str]: The generated database query.
    """
    # Check permissions first - query generation requires tools permission
    if not await authorization_service.check_operation_permission(user_data.email, user_data.role, "execute", "tools"):
        raise HTTPException(status_code=403, detail="You don't have permission to generate queries. Only admins and developers can perform this action")
    
    user_id = request.cookies.get("user_id")
    user_session = request.cookies.get("user_session")
    update_session_context(user_session=user_session, user_id=user_id)

    try:
        llm = await model_service.get_llm_model(model_name="gpt-4o", temperature=query_request.temperature or 0.0)
        
        prompt = f"""
        Prompt Template:
        You are an intelligent query generation assistant.
        I will provide you with:
   
        The type of database (e.g., MySQL, PostgreSQL, MongoDB, etc.)
   
        A query in natural language
   
        Your task is to:
   
        Convert the natural language query into a valid query in the specified database’s query language.
   
        Ensure the syntax is appropriate for the chosen database.
   
        Do not include explanations or extra text.
   
        Do not include any extra quotes, punctuation marks, or explanations. Provide only the final query in the output field, without any additional text or symbols (e.g., no quotation marks, commas, or colons).
   
        Database: {query_request.database_type}
        Natural Language Query: {query_request.natural_language_query}
        Example Input:
        Database: PostgreSQL
        Natural Language Query: Show the top 5 customers with the highest total purchases.
   
         Expected Output:
        SELECT customer_id, SUM(purchase_amount) AS total_purchases
        FROM purchases
        GROUP BY customer_id
        ORDER BY total_purchases DESC
        LIMIT 5;
   
        Example 2 (MongoDB)
        Database: MongoDB
        Natural Language Query: Get all orders placed by customer with ID "12345" from the "orders" collection.
   
         Expected Output:
        db.orders.find({{ customer_id: "12345" }})
        """
        response = await llm.ainvoke([
            {"role": "system", "content": "You generate clean and executable database queries from user input."},
            {"role": "user", "content": prompt}
        ])
        return {"generated_query": response.content.strip()}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Query generation failed: {e}")


@router.post("/run-query")
async def run_query_endpoint(
    request: Request, 
    query_execution_request: QueryExecutionRequest, 
    db_connection_manager: MultiDBConnectionRepository = Depends(ServiceProvider.get_multi_db_connection_manager),
    authorization_service: AuthorizationService = Depends(ServiceProvider.get_authorization_service),
    user_data: User = Depends(get_current_user)
):
    """
    API endpoint to run a database query on a connected database.

    Parameters:
    - request: The FastAPI Request object.
    - query_execution_request: Pydantic model containing connection name and query.
    - db_connection_manager: Dependency-injected MultiDBConnectionRepository.

    Returns:
    - Dict[str, Any]: Query results or status message.
    """
    # Check permissions first - query execution requires tools permission
    if not await authorization_service.check_operation_permission(user_data.email, user_data.role, "execute", "tools"):
        raise HTTPException(status_code=403, detail="You don't have permission to execute queries. Only admins and developers can perform this action")
    
    user_id = request.cookies.get("user_id")
    user_session = request.cookies.get("user_session")
    update_session_context(user_session=user_session, user_id=user_id)

    manager = get_connection_manager()
 
    config = await db_connection_manager.get_connection_config(query_execution_request.name)

   
    # Log the query for debugging purposes (sanitize or remove sensitive information before logging in production)
    log.debug(f"Running query: {query_execution_request.query}")
    session = None
 
    try:
        # Get the engine for the specific database connection
        # engine = get_engine(config)
        manager.add_sql_database(query_execution_request.name, await _build_connection_string_helper(config))
        session = manager.get_sql_session(query_execution_request.name)

        # with engine.connect() as conn:
        # Log query execution start
        log.debug(f"Executing query on connection {query_execution_request.name}")
        
        # Check if it's a DDL query (CREATE, ALTER, DROP)
        if any(word in query_execution_request.query.upper() for word in ["CREATE", "ALTER", "DROP"]):
            log.debug("Executing DDL Query")
            session.execute(text(query_execution_request.query))  # Execute DDL queries directly
            session.commit()  # Commit after DDL queries
            return {"message": "DDL Query executed successfully."}

        # Handle SELECT queries
        if query_execution_request.query.strip().upper().startswith("SELECT"):
            log.debug("Executing SELECT Query")
            result = session.execute(text(query_execution_request.query))  # Execute SELECT query
            
            # Fetch the column names
            columns = list(result.keys()) # This gives us the column names
            rows = result.fetchall()  # Get all rows

            # Convert rows into dictionaries with column names as keys
            rows_dict = [{columns[i]: row[i] for i in range(len(columns))} for row in rows]

            return {"columns": columns, "rows": rows_dict}

        # Handle DML queries (INSERT, UPDATE, DELETE)
        log.debug("Executing DML Query")
        result = session.execute(text(query_execution_request.query))  # Execute DML query
        session.commit()  # Commit the transaction

        # Log how many rows were affected
        log.debug(f"Rows affected: {result.rowcount}")
        
        return {"message": f"Query executed successfully, {result.rowcount} rows affected."}
 
    except SQLAlchemyError as e:
        # Log the exception for debugging
        log.debug(f"Query failed: {e}")
        raise HTTPException(status_code=400, detail=f"Query failed: {str(e)}")
 
    except Exception as e:
        # Catch all other exceptions (e.g., connection issues, etc.)
        log.debug(f"Unexpected error: {e}")
        raise HTTPException(status_code=500, detail=f"Unexpected error: {str(e)}")
    
    finally:
        if session:
            session.close()


@router.get("/connections")
async def get_connections_endpoint(
    request: Request, 
    db_connection_manager: MultiDBConnectionRepository = Depends(ServiceProvider.get_multi_db_connection_manager),
    authorization_service: AuthorizationService = Depends(ServiceProvider.get_authorization_service),
    user_data: User = Depends(get_current_user)
):
    """
    API endpoint to retrieve all saved database connections.

    Parameters:
    - request: The FastAPI Request object.
    - db_connection_manager: Dependency-injected MultiDBConnectionRepository.

    Returns:
    - Dict[str, Any]: A dictionary containing all saved connections.
    """
    # Check permissions first - viewing connections requires tools permission
    if not await authorization_service.check_operation_permission(user_data.email, user_data.role, "read", "tools"):
        raise HTTPException(status_code=403, detail="You don't have permission to view connections. Only admins and developers can perform this action")
    
    user_id = request.cookies.get("user_id")
    user_session = request.cookies.get("user_session")
    update_session_context(user_session=user_session, user_id=user_id)
    return await db_connection_manager.get_connections()
    

@router.get("/connection/{connection_name}")
async def get_connection_config_endpoint(
    request: Request, 
    connection_name: str, 
    db_connection_manager: MultiDBConnectionRepository = Depends(ServiceProvider.get_multi_db_connection_manager),
    authorization_service: AuthorizationService = Depends(ServiceProvider.get_authorization_service),
    user_data: User = Depends(get_current_user)
):
    """
    API endpoint to retrieve the configuration of a specific database connection.

    Parameters:
    - request: The FastAPI Request object.
    - connection_name: The name of the connection.
    - db_connection_manager: Dependency-injected MultiDBConnectionRepository.

    Returns:
    - Dict[str, Any]: The connection configuration.
    """
    # Check permissions first - viewing connection config requires tools permission
    if not await authorization_service.check_operation_permission(user_data.email, user_data.role, "read", "tools"):
        raise HTTPException(status_code=403, detail="You don't have permission to view connection configuration. Only admins and developers can perform this action")
    
    user_id = request.cookies.get("user_id")
    user_session = request.cookies.get("user_session")
    update_session_context(user_session=user_session, user_id=user_id)
    return await db_connection_manager.get_connection_config(connection_name)


@router.get("/connections/sql")
async def get_sql_connections_endpoint(
    request: Request, 
    db_connection_manager: MultiDBConnectionRepository = Depends(ServiceProvider.get_multi_db_connection_manager),
    authorization_service: AuthorizationService = Depends(ServiceProvider.get_authorization_service),
    user_data: User = Depends(get_current_user)
):
    """
    API endpoint to retrieve all saved SQL database connections.

    Parameters:
    - request: The FastAPI Request object.
    - db_connection_manager: Dependency-injected MultiDBConnectionRepository.

    Returns:
    - Dict[str, Any]: A dictionary containing all saved SQL connections.
    """
    # Check permissions first - viewing SQL connections requires tools permission
    if not await authorization_service.check_operation_permission(user_data.email, user_data.role, "read", "tools"):
        raise HTTPException(status_code=403, detail="You don't have permission to view SQL connections. Only admins and developers can perform this action")
    
    user_id = request.cookies.get("user_id")
    user_session = request.cookies.get("user_session")
    update_session_context(user_session=user_session, user_id=user_id)
    return await db_connection_manager.get_connections_sql()


@router.get("/connections/mongodb")
async def get_mongodb_connections_endpoint(
    request: Request, 
    db_connection_manager: MultiDBConnectionRepository = Depends(ServiceProvider.get_multi_db_connection_manager),
    authorization_service: AuthorizationService = Depends(ServiceProvider.get_authorization_service),
    user_data: User = Depends(get_current_user)
):
    """
    API endpoint to retrieve all saved MongoDB connections.

    Parameters:
    - request: The FastAPI Request object.
    - db_connection_manager: Dependency-injected MultiDBConnectionRepository.

    Returns:
    - Dict[str, Any]: A dictionary containing all saved MongoDB connections.
    """
    # Check permissions first - viewing MongoDB connections requires tools permission
    if not await authorization_service.check_operation_permission(user_data.email, user_data.role, "read", "tools"):
        raise HTTPException(status_code=403, detail="You don't have permission to view MongoDB connections. Only admins and developers can perform this action")
    
    user_id = request.cookies.get("user_id")
    user_session = request.cookies.get("user_session")
    update_session_context(user_session=user_session, user_id=user_id)
    return await db_connection_manager.get_connections_mongodb()


@router.post("/mongodb-operation/")
async def mongodb_operation_endpoint(
    request: Request, 
    mongo_op_request: MONGODBOperation, 
    db_connection_manager: MultiDBConnectionRepository = Depends(ServiceProvider.get_multi_db_connection_manager),
    authorization_service: AuthorizationService = Depends(ServiceProvider.get_authorization_service),
    user_data: User = Depends(get_current_user)
):
    """
    API endpoint to perform MongoDB operations.

    Parameters:
    - request: The FastAPI Request object.
    - mongo_op_request: Pydantic model containing MongoDB operation details.
    - db_connection_manager: Dependency-injected MultiDBConnectionRepository.

    Returns:
    - Dict[str, Any]: Operation results.
    """
    # Check permissions first - MongoDB operations require tools permission
    if not await authorization_service.check_operation_permission(user_data.email, user_data.role, "execute", "tools"):
        raise HTTPException(status_code=403, detail="You don't have permission to perform MongoDB operations. Only admins and developers can perform this action")
    
    user_id = request.cookies.get("user_id")
    user_session = request.cookies.get("user_session")
    update_session_context(user_session=user_session, user_id=user_id)

    manager = get_connection_manager()
    config = await db_connection_manager.get_connection_config(mongo_op_request.conn_name)
    manager.add_mongo_database(config.get("name",""), await _build_connection_string_helper(config),config.get("database",""))
    mongo_db = manager.get_mongo_database(mongo_op_request.conn_name)
    collection = mongo_db[mongo_op_request.collection] 
    # sample_doc = await mongo_db.test_collection.find_one()
    try:
        # FIND
        if mongo_op_request.operation == "find":
            if mongo_op_request.mode == "one":
                doc = await collection.find_one(mongo_op_request.query)
                return {"status": "success", "data": await _clean_document_helper(doc)}
            else:
                docs = await collection.find(mongo_op_request.query).to_list(100)
                return {"status": "success", "data": [await _clean_document_helper(d) for d in docs]}

        # INSERT
        elif mongo_op_request.operation == "insert":
            if mongo_op_request.mode == "one":
                result = await collection.insert_one(mongo_op_request.data)
                return {"status": "success", "inserted_id": str(result.inserted_id)}
            else:
                result = await collection.insert_many(mongo_op_request.data)
                return {"status": "success", "inserted_ids": [str(_id) for _id in result.inserted_ids]}

        # UPDATE
        elif mongo_op_request.operation == "update":
            if mongo_op_request.mode == "one":
                result = await collection.update_one(mongo_op_request.query, {"$set": mongo_op_request.update_data})
            else:
                result = await collection.update_many(mongo_op_request.query, {"$set": mongo_op_request.update_data})
            return {
                "status": "success",
                "matched_count": result.matched_count,
                "modified_count": result.modified_count
            }

        # DELETE
        elif mongo_op_request.operation == "delete":
            if mongo_op_request.mode == "one":
                result = await collection.delete_one(mongo_op_request.query)
            else:
                result = await collection.delete_many(mongo_op_request.query)
            return {"status": "success", "deleted_count": result.deleted_count}

        else:
            raise HTTPException(status_code=400, detail="Invalid operation")

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/get/active-connection-names")
async def get_active_connection_names_endpoint(
    request: Request, 
    db_connection_manager: MultiDBConnectionRepository = Depends(ServiceProvider.get_multi_db_connection_manager),
    authorization_service: AuthorizationService = Depends(ServiceProvider.get_authorization_service),
    user_data: User = Depends(get_current_user)
):
    """
    API endpoint to retrieve names of currently active database connections.

    Parameters:
    - request: The FastAPI Request object.
    - db_connection_manager: Dependency-injected MultiDBConnectionRepository.

    Returns:
    - Dict[str, List[str]]: A dictionary categorizing active connection names by type.
    """
    # Check permissions first - viewing active connections requires tools permission
    if not await authorization_service.check_operation_permission(user_data.email, user_data.role, "read", "tools"):
        raise HTTPException(status_code=403, detail="You don't have permission to view active connections. Only admins and developers can perform this action")
    
    user_id = request.cookies.get("user_id")
    user_session = request.cookies.get("user_session")
    update_session_context(user_session=user_session, user_id=user_id)

    manager = get_connection_manager()
 
    active_sql_connections = list(manager.sql_engines.keys())
    active_mongo_connections = list(manager.mongo_clients.keys())
 
    db_info_list = await db_connection_manager.get_connections_sql()
 
    connections = db_info_list.get("connections", [])
    db_type_map = {item["connection_name"]: item["connection_database_type"].lower() for item in connections}
 
    active_mysql_connections = []
    active_postgres_connections = []
    active_sqlite_connections = []
 
    for conn_name in active_sql_connections:
        db_type = db_type_map.get(conn_name)
        if db_type == "mysql":
            active_mysql_connections.append(conn_name)
        elif db_type in ("postgres", "postgresql"):
            active_postgres_connections.append(conn_name)
        elif db_type == "sqlite":
            active_sqlite_connections.append(conn_name)
 
    return {
        "active_mysql_connections": active_mysql_connections,
        "active_postgres_connections": active_postgres_connections,
        "active_sqlite_connections": active_sqlite_connections,
        "active_mongo_connections": active_mongo_connections
    }


