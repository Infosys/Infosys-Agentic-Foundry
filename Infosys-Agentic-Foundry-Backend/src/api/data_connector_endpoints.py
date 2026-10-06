# © 2024-25 Infosys Limited, Bangalore, India. All Rights Reserved.
import re
import os
import uuid
import base64
import sqlite3 # For SQLite specific operations
from typing import Dict, Optional, Any, Union, List
from bson import ObjectId # For MongoDB ObjectId handling
from sqlalchemy import create_engine, text # For SQL Alchemy engine
from sqlalchemy.exc import SQLAlchemyError # For SQL Alchemy exceptions
from psycopg2 import sql as pg_sql

from cryptography.fernet import Fernet

from fastapi import APIRouter, Depends, HTTPException, Request, Form, UploadFile, File

from src.schemas import QueryGenerationRequest, QueryExecutionRequest, DBDisconnectRequest, MONGODBOperation

from MultiDBConnection_Manager import MultiDBConnectionRepository, get_connection_manager
from src.api.dependencies import ServiceProvider # The dependency provider
from src.database.services import ModelService # For generate_query endpoint
from telemetry_wrapper import logger as log, update_session_context # Your custom logger and context updater
from src.auth.authorization_service import AuthorizationService
from src.utils.llm_request_tracker import with_request_tracking
from src.auth.auth_service import AuthService
from src.auth.dependencies import get_current_user
from src.auth.models import User, UserRole

from typing import Union

router = APIRouter(prefix="/data-connector", tags=["Data Connector"])


UPLOAD_DIR = "uploaded_sqlite_dbs"
os.makedirs(UPLOAD_DIR, exist_ok=True)


# ---------------------------------------------------------------------------
#  Credential helpers — base64 decode (from UI) & Fernet encrypt/decrypt (DB)
# ---------------------------------------------------------------------------

def _get_fernet_cipher() -> Fernet:
    """Return a Fernet cipher initialised from ``SECRETS_MASTER_KEY``."""
    master_key = os.getenv("SECRETS_MASTER_KEY", "")
    if not master_key:
        raise RuntimeError("SECRETS_MASTER_KEY is not configured — cannot encrypt/decrypt data-connector passwords")
    return Fernet(master_key.encode()[:44].ljust(44, b'='))


def _decode_base64_password(raw: str) -> str:
    """Decode a base64-encoded credential sent by the UI.

    If decoding fails the value is returned as-is (backward-compat with older
    UIs that may still send plaintext).
    """
    if not raw:
        return raw
    try:
        return base64.b64decode(raw).decode("utf-8")
    except Exception:
        # Not valid base64 — treat as plain text (backward-compat)
        return raw


def _encrypt_password(plaintext: str) -> str:
    """Encrypt a plaintext credential with Fernet for safe DB storage."""
    if not plaintext:
        return plaintext
    cipher = _get_fernet_cipher()
    return cipher.encrypt(plaintext.encode("utf-8")).decode("utf-8")


def _decrypt_password(encrypted: str) -> str:
    """Decrypt a Fernet-encrypted credential read from the DB.

    If decryption fails (e.g. legacy row stored as plaintext) the value is
    returned as-is so existing connections keep working.
    """
    if not encrypted:
        return encrypted
    try:
        cipher = _get_fernet_cipher()
        return cipher.decrypt(encrypted.encode("utf-8")).decode("utf-8")
    except Exception:
        # Legacy unencrypted value — return as-is
        return encrypted


# Helper functions

async def _build_connection_string_helper(config: dict) -> str:
    from urllib.parse import quote_plus
    db_type = config["db_type"].lower()
    # URL-encode username and credential to prevent connection string injection
    # (special chars like @, /, :, ? corrupt the URL structure)
    _user = quote_plus(str(config.get('username') or ''))
    _pass = quote_plus(str(config.get('password') or ''))
    _host = config.get('host', 'localhost')
    _port = config.get('port', 0)
    _db   = config.get('database', '')
    if db_type == "mysql":
        return f"mysql+mysqlconnector://{_user}:{_pass}@{_host}:{_port}/{_db}"
    if db_type == "postgresql":
        return f"postgresql+psycopg2://{_user}:{_pass}@{_host}:{_port}/{_db}"
    if db_type == "azuresql":
        return f"mssql+pyodbc://{_user}:{_pass}@{_host}:{_port}/{_db}?driver=ODBC+Driver+17+for+SQL+Server"
    if db_type == "sqlite":
        # Check if department_name is available in config for department-specific path
        department_name = config.get("department_name", None)
        return f"sqlite:///{UPLOAD_DIR}/{department_name}/{_db}"
    if db_type == "mongodb":
        _host = config.get("host", "localhost")
        _port = config.get("port", 27017)
        db_name = config.get("database", "")
        username = config.get("username")
        password = config.get("password")
        if username and password:
            return f"mongodb://{quote_plus(str(username))}:{quote_plus(str(password))}@{_host}:{_port}/?authSource={db_name}"
        else:
            return f"mongodb://{_host}:{_port}/{db_name}"
    raise HTTPException(status_code=400, detail=f"Unsupported database type: {config['db_type']}")


async def _create_database_if_not_exists_helper(config: dict):
    db_type = config["db_type"].lower()
    db_name = config["database"]

    # Validate database name early. Rules differ by engine:
    #   - SQLite:  the value is a *filename* on disk, so allow letters/digits/
    #              `_`, `-`, `.` (for extensions like .db / .sqlite / .sqlite3).
    #              Reject path separators and traversal to keep it inside the
    #              upload directory.
    #   - Others:  the value becomes a SQL identifier — apply the strict
    #              allowlist so we can safely quote it.
    if db_type == "sqlite":
        if (
            not db_name
            or len(db_name) > 128
            or "/" in db_name
            or "\\" in db_name
            or db_name in (".", "..")
            or db_name.startswith(".")
            or not re.fullmatch(r'[A-Za-z0-9_][A-Za-z0-9_.\-]*', db_name)
        ):
            raise HTTPException(
                status_code=400,
                detail=(
                    "Invalid SQLite database file name: use letters, digits, "
                    "'_', '-' or '.' (e.g. 'my_data.db'); no path separators, "
                    "no leading dot, max 128 chars"
                ),
            )
    else:
        if not re.fullmatch(r'[a-zA-Z_][a-zA-Z0-9_]{0,63}', db_name):
            raise HTTPException(status_code=400, detail="Invalid database name: must be alphanumeric/underscore, start with letter/underscore, max 64 chars")

    # SQLite DB creation not needed
    if db_type == "sqlite":
        # Get department name from config, default to "General" if not provided
        department_name = config.get("department_name", None)
        
        # Create department-specific directory if it doesn't exist
        department_dir = os.path.join(UPLOAD_DIR, department_name)
        os.makedirs(department_dir, exist_ok=True)
        
        # Connect to the database file (creates it if it doesn't exist)
        db_path = os.path.join(department_dir, db_name)

        if os.path.exists(db_path):
            raise HTTPException(status_code=400, detail=f"Database file '{db_name}' already exists in department '{department_name}'")
        try:
            # File doesn't exist, so this will create it
            conn = sqlite3.connect(db_path)
            # Close the connection immediately to keep it empty
            conn.close()

            # --- Fire-and-forget blob sync for newly created SQLite DB ---
            try:
                import os as _os
                _sp = _os.getenv('STORAGE_PROVIDER', '')
                if _sp:
                    from src.utils.workspace_blob_sync import WorkspaceBlobSync
                    from src.storage import get_storage_client
                    _client = get_storage_client(_sp)
                    _syncer = WorkspaceBlobSync(
                        storage_client=_client,
                        workspace_root="./agent_workspaces",
                        department=department_name,
                        project_root=_os.path.abspath("."),
                    )
                    _syncer.schedule_sqlite_db_sync(department_name, db_name)
            except Exception:
                pass  # Non-critical
            # ---
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
        raw_conn = engine.raw_connection()
        try:
            cur = raw_conn.cursor()
            # SELECT check uses %s parameterized query (safe value binding)
            cur.execute("SELECT 1 FROM pg_database WHERE datname = %s", (db_name,))
            if not cur.fetchone():
                # CREATE DATABASE uses pg_sql.Identifier for safe identifier quoting
                cur.execute(pg_sql.SQL("CREATE DATABASE {}").format(pg_sql.Identifier(db_name)))
            cur.close()
        finally:
            raw_conn.close()
        return

    if db_type == "mysql":
        config_copy["database"] = ""
        engine = create_engine(await _build_connection_string_helper(config_copy))
        raw_conn = engine.raw_connection()
        try:
            cur = raw_conn.cursor()
            cur.execute(f"CREATE DATABASE IF NOT EXISTS `{db_name}`")
            cur.close()
            raw_conn.commit()
        finally:
            raw_conn.close()
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
        port: Optional[int] = Form(0),
        username: Optional[str] = Form(None),
        password: Optional[str] = Form(None, description="Password can be passed either in 'password' or 'user_pwd' field"),
        user_pwd: Optional[str] = Form(None, description="Password can be passed either in 'password' or 'user_pwd' field"),
        database: Optional[str] = Form(None),
        flag_for_insert_into_db_connections_table: str = Form(None),
        # created_by: str = Form(...),  # <--- make sure to include this
        sql_file: Union[UploadFile, str, None] = File(None),
        created_by: Optional[str]= Form(None),
        blocked_sql_commands: Optional[str] = Form(None, description="JSON array of SQL keywords to block (e.g., '[\"DELETE\", \"DROP\"]'). If not provided, defaults apply."),
        connection_description: Optional[str] = Form(None, description="Description of the database connection"),
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
    - blocked_sql_commands: JSON array of SQL keywords to block for this connection.
                            Default: ["DROP", "DELETE", "UPDATE", "INSERT", "ALTER", "CREATE", "TRUNCATE", "EXEC", "EXECUTE", "GRANT", "REVOKE"]
    - connection_description: Description of the database connection.
    - db_connection_manager: Dependency-injected MultiDBConnectionRepository.

    Returns:
    - Dict[str, Any]: Status message.
    """
    if isinstance(sql_file, str):
        sql_file = None
    
    # Check data connector access permission with department context
    user_department = user_data.department_name 
    has_access = await authorization_service.check_data_connector_access(user_data.role, user_department)
    if not has_access:
        raise HTTPException(status_code=403, detail="You don't have permission to access data connector endpoints.")

    user_id = request.cookies.get("user_id")
    user_session = request.cookies.get("user_session")
    update_session_context(user_session=user_session, user_id=user_id, session_id=user_session, call_category="data_connector_operation")
    password = password or user_pwd

    # --- Decode base64 credential from UI ---
    if password:
        password = _decode_base64_password(password)

    # Get restricted database name from environment variable
    RESTRICTED_DATABASE = os.getenv("DATABASE", "agentic_workflow_as_service_database")
    # Validate database name - prevent connecting to system database
    if database and database.lower() == RESTRICTED_DATABASE.lower():
        raise HTTPException(
            status_code=403, 
            detail=f"Connecting to '{RESTRICTED_DATABASE}' is not allowed."
        )
    manager = get_connection_manager()

    if flag_for_insert_into_db_connections_table == "1":
        name_exists = await db_connection_manager.check_connection_name_exists(name, department_name=user_department)
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
            flag_for_insert_into_db_connections_table=flag_for_insert_into_db_connections_table,
            created_by=created_by,
            department_name=user_department  # Add department name to config
        )

        # Adjust config based on DB type:
        if db_type.lower() == "sqlite":
            # For SQLite, host/port/user/pass not needed, database is file path
            config["host"] = None
            config["port"] = 0
            config["username"] = None
            config["password"] = None
            
            # Create department-specific directory for SQLite files
            department_dir = os.path.join(UPLOAD_DIR, user_department)
            os.makedirs(department_dir, exist_ok=True)
            
            if sql_file is not None and flag_for_insert_into_db_connections_table == "1":
                config["database"] = sql_file.filename
                filename = os.path.basename(sql_file.filename)
                if not (filename.endswith(".db") or filename.endswith(".sqlite")):
                    raise HTTPException(status_code=400, detail="Only .db or .sqlite files are allowed")
                
                # Store file in department-specific directory
                file_path = os.path.join(department_dir, filename)
                if os.path.exists(file_path):
                    raise HTTPException(status_code=400, detail="File with this name already exists")
                
                with open(file_path, "wb") as f:
                    content = await sql_file.read()
                    f.write(content)

                # --- Fire-and-forget blob sync for uploaded SQLite DB ---
                try:
                    _sp = os.getenv('STORAGE_PROVIDER', '')
                    if _sp:
                        from src.utils.workspace_blob_sync import WorkspaceBlobSync
                        from src.storage import get_storage_client
                        _client = get_storage_client(_sp)
                        _syncer = WorkspaceBlobSync(
                            storage_client=_client,
                            workspace_root="./agent_workspaces",
                            department=user_department,
                            project_root=os.path.abspath("."),
                        )
                        _syncer.schedule_sqlite_db_sync(user_department, filename)
                except Exception:
                    pass  # Non-critical
                # ---
            else:
                if flag_for_insert_into_db_connections_table=="1":
                    # Only append `.db` if the user didn't already supply a
                    # SQLite-style extension. This keeps `new` -> `new.db` and
                    # `new.db` -> `new.db` (instead of `new.db.db`).
                    _db_name = (config.get("database") or "").strip()
                    if not _db_name.lower().endswith((".db", ".sqlite", ".sqlite3")):
                        _db_name = _db_name + ".db"
                    config["database"] = _db_name
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
            # Parse blocked_sql_commands if provided as JSON string
            parsed_blocked_commands = None
            if blocked_sql_commands:
                try:
                    import json as json_mod
                    parsed_blocked_commands = json_mod.loads(blocked_sql_commands)
                    if not isinstance(parsed_blocked_commands, list):
                        parsed_blocked_commands = None
                except:
                    parsed_blocked_commands = None
            
            # Encrypt credential before storing in DB
            encrypted_pwd = _encrypt_password(config.get("password", ""))

            connection_data = {
                "connection_id": str(uuid.uuid4()),
                "connection_name": name,
                "connection_database_type": db_type,
                "connection_host": config.get("host", ""),
                "connection_port": config.get("port", 0),
                "connection_username": config.get("username", ""),
                "connection_password": encrypted_pwd,
                "connection_database_name": config.get("database", ""),
                "connection_created_by": config.get("created_by", ""),
                "blocked_sql_commands": parsed_blocked_commands,
                "connection_description": connection_description,
                "department_name": user_data.department_name
            }
            result = await db_connection_manager.insert_into_db_connections_table(connection_data)
            
            # Auto-generate schema and samples
            schema_samples_result = None
            try:
                from src.inference.database_tools_cache import auto_generate_schema_and_samples
                schema_samples_result = await auto_generate_schema_and_samples(
                    connection_name=name,
                    db_type=db_type,
                    connection_manager=manager,
                    department=user_data.department_name
                )
                log.info(f"[DATA_CONNECTOR] Auto-generated schema/samples for {name}: {schema_samples_result.get('status')}")
            except Exception as schema_error:
                log.warning(f"[DATA_CONNECTOR] Failed to auto-generate schema/samples for {name}: {schema_error}")
                schema_samples_result = {"status": "error", "message": str(schema_error)}
            
            if result.get("is_created"):
                response_data = {
                    "message": f"Connected to {db_type} database '{database}' and saved configuration.",
                    **result
                }
                if schema_samples_result:
                    response_data["schema_samples"] = schema_samples_result
                return response_data
            else:
                return {
                    "message": f"Connected to {db_type} database '{database}', but failed to save configuration.",
                }
        else:
            return {"message": f"Connected to {db_type} database '{database}'."}

    except HTTPException:
        # Re-raise HTTPException without modification
        raise
        
    except SQLAlchemyError as e:
        # Log the full error for debugging
        log.error(f"SQLAlchemy connection error for '{name}': {str(e)}")
        
        # Return sanitized error message
        error_type = type(e).__name__
        
        # Provide helpful hints without exposing sensitive data
        if "authentication" in str(e).lower() or "password" in str(e).lower():
            detail = "Authentication failed. Please verify your username and password."
        elif "host" in str(e).lower() or "connection refused" in str(e).lower():
            detail = "Unable to reach the database server. Please verify the connection is accessible."
        elif "timeout" in str(e).lower():
            detail = "Connection timeout. The database server is not responding."
        elif "database" in str(e).lower() and "does not exist" in str(e).lower():
            detail = "The specified database does not exist."
        else:
            detail = f"Database connection failed. Please verify your connection details."
        
        raise HTTPException(status_code=500, detail=detail)

    except Exception as e:
        # Log the full error for debugging
        log.error(f"Unexpected connection error for '{name}': {str(e)}")
        
        # Return generic error message
        raise HTTPException(
            status_code=500, 
            detail="An unexpected error occurred while connecting to the database. Please contact support if the issue persists."
        )


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
    # Check data connector access permission with department context
    user_department = user_data.department_name 
    has_access = await authorization_service.check_data_connector_access(user_data.role, user_department)
    if not has_access:
        raise HTTPException(status_code=403, detail="You don't have permission to access data connector endpoints.")

    user_id = request.cookies.get("user_id")
    user_session = request.cookies.get("user_session")
    update_session_context(user_session=user_session, user_id=user_id, session_id=user_session, call_category="data_connector_operation")
 
    name = disconnect_request.name 
    name_with_dept = disconnect_request.name + "_" + user_department
    db_type = disconnect_request.db_type.lower()
    manager = get_connection_manager()
 
    # Get current active connections
    active_sql_connections = list(manager.sql_engines.keys())
    active_mongo_connections = list(manager.mongo_clients.keys())
    
    def strip_department_suffix(conn_name: str, dept: str) -> str:
        if not conn_name:
            return conn_name
        if dept:
            suffix = f"_{dept}"
            if conn_name.lower().endswith(suffix.lower()):
                return conn_name[: -len(suffix)]
        # fallback: remove last underscore segment if present
        if "_" in conn_name:
            return conn_name.rsplit("_", 1)[0]
        return conn_name
    
    
 
    try:
        # If flag is "1", we need to delete from database
        if disconnect_request.flag == "1":
            # First check if connection exists in database and get creator info
            creator_email = None
            try:
                creator_info = await db_connection_manager.get_user_email(name, department_name= user_department)
                creator_email = creator_info.get("created_by") if creator_info else None
               
                # Clean up creator_email (strip whitespace and handle empty strings)
                if creator_email:
                    creator_email = creator_email.strip()
                    if not creator_email:  # Empty string after strip
                        creator_email = None
                       
            except HTTPException as e:
                if e.status_code == 404:
                    # Connection doesn't exist in database
                    log.warning(f"Connection '{name}' not found in database during disconnect")
                    creator_email = None
                else:
                    raise
           
            # ==================== OWNERSHIP VERIFICATION ====================
            # If creator_email is NULL in DB, allow anyone to disconnect (public connection)
            # If creator_email is NOT NULL, verify ownership
            if creator_email is not None:
                # This is a PRIVATE connection - verify ownership
                if not disconnect_request.created_by:
                    raise HTTPException(
                        status_code=403,
                        detail="This is a private connection. Please provide created_by field to verify ownership."
                    )
               
                if disconnect_request.created_by.strip().lower() != creator_email.lower():
                    raise HTTPException(
                        status_code=403,
                        detail="You don't have permission to delete this connection. Only the creator can delete it."
                    )
               
                log.info(f"[PRIVATE CONNECTION] User '{disconnect_request.created_by}' verified as creator, deleting connection '{name}'")
            else:
                # This is a PUBLIC connection (created_by is NULL) - allow anyone to disconnect
                log.info(f"[PUBLIC CONNECTION] Allowing deletion of public connection '{name}' by {disconnect_request.created_by or 'anonymous'}")
           
            # Delete from database (only if it exists)
            if creator_email is not None or creator_email is None:
                try:
                    delete_result = await db_connection_manager.delete_connection_by_name(name, department_name = user_department)
                    log.info(f"Deleted connection '{name}' from database")
                except Exception as delete_error:
                    log.warning(f"Failed to delete connection '{name}' from database: {str(delete_error)}")

            # Clean up local database schema/samples files AND blob storage
            try:
                from src.inference.database_tools_cache import clear_database_files
                clear_database_files(name, department=user_department)
                log.info(f"Cleared database schema/samples for '{name}'")
            except Exception as cleanup_err:
                log.warning(f"Failed to clear database files for '{name}': {cleanup_err}")

            # Delete uploaded SQLite .db file from blob if applicable
            try:
                _sp = os.getenv('STORAGE_PROVIDER', '')
                if _sp:
                    from src.utils.workspace_blob_sync import WorkspaceBlobSync
                    from src.storage import get_storage_client
                    _client = get_storage_client(_sp)
                    _syncer = WorkspaceBlobSync(
                        storage_client=_client,
                        workspace_root=os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "agent_workspaces"),
                        department=user_department,
                    )
                    # Delete uploaded sqlite file blob if exists
                    _syncer.schedule_blob_prefix_delete(
                        f"{user_department}/databases/{name}/",
                        name="disconnect_db_blob_delete",
                    )
            except Exception as blob_err:
                log.warning(f"Blob delete for disconnected DB '{name}' failed: {blob_err}")
 
        # ==================== CLOSE ACTIVE CONNECTIONS ====================
        # Close active connections (whether deleting from DB or just deactivating)
        if db_type == "mongodb":
            if name_with_dept in active_mongo_connections:
                await manager.close_mongo_client(name)
                if disconnect_request.flag == "1":
                    return {"message": f"Disconnected MongoDB connection '{name}' successfully"}
                else:
                    return {"message": f"Deactivated MongoDB connection '{name}' successfully"}
            else:
                if disconnect_request.flag == "1":
                    return {"message": f"MongoDB connection '{name}' was not active, but removed from database"}
                else:
                    return {"message": f"MongoDB connection '{name}' was not active"}
 
        else:  # SQL
            if name_with_dept in active_sql_connections:
                manager.dispose_sql_engine(name)
                if disconnect_request.flag == "1":
                    return {"message": f"Disconnected SQL connection '{name}' successfully"}
                else:
                    return {"message": f"Deactivated SQL connection '{name}' successfully"}
            else:
                if disconnect_request.flag == "1":
                    return {"message": f"SQL connection '{name}' was not active, but removed from database"}
                else:
                    return {"message": f"SQL connection '{name}' was not active"}
 
    except HTTPException:
        raise
    except Exception as e:
        log.error(f"Error while disconnecting '{name}': {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Error while disconnecting: {str(e)}")

@with_request_tracking("data_connector_query_generation")
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
    # Check data connector access permission with department context
    user_department = user_data.department_name 
    has_access = await authorization_service.check_data_connector_access(user_data.role, user_department)
    if not has_access:
        raise HTTPException(status_code=403, detail="You don't have permission to access data connector endpoints.")

    user_id = request.cookies.get("user_id")
    user_session = request.cookies.get("user_session")
    update_session_context(user_session=user_session, user_id=user_id, session_id=user_session, call_category="data_connector_operation")

    try:
        model_name = model_service.default_model_name
        llm = await model_service.get_llm_model(model_name=model_name, temperature=query_request.temperature or 0.0)
        
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


import re

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
    # Check data connector access permission with department context
    user_department = user_data.department_name 
    has_access = await authorization_service.check_data_connector_access(user_data.role, user_department)
    if not has_access:
        raise HTTPException(status_code=403, detail="You don't have permission to access data connector endpoints.")

    user_id = request.cookies.get("user_id")
    user_session = request.cookies.get("user_session")
    update_session_context(user_session=user_session, user_id=user_id, session_id=user_session, call_category="data_connector_operation")

    import base64
    manager = get_connection_manager()
 
    config = await db_connection_manager.get_connection_config(query_execution_request.name)
    
    # ==================== DECODE BASE64 QUERY ====================
    try:
        decoded_sql = base64.b64decode(query_execution_request.data).decode("utf-8")
        log.info(f"Decoded SQL: {decoded_sql}")
        query_execution_request.data = decoded_sql
    except Exception as decode_error:
        log.error(f"Failed to decode base64 query: {str(decode_error)}")
        raise HTTPException(
            status_code=400, 
            detail="Invalid query format. Please ensure the query is properly encoded."
        )
    
    # ==================== SECURITY VALIDATIONS ====================
    
    query_input = query_execution_request.data.strip()
    query_upper = query_input.upper()
    
    # Get current user email from request (can be None)
    current_user_email = query_execution_request.created_by
    
    # 1. Remove comments to prevent bypass attempts
    query_no_comments = re.sub(r'--.*$', '', query_upper, flags=re.MULTILINE)
    query_no_comments = re.sub(r'/\*.*?\*/', '', query_no_comments, flags=re.DOTALL)
    
    # 2. BLOCK DROP and TRUNCATE (completely forbidden for everyone)
    if re.search(r'\bDROP\b', query_no_comments):
        log.warning(f"[SECURITY] Blocked DROP attempt by {current_user_email or 'anonymous'} on connection {query_execution_request.name}")
        raise HTTPException(
            status_code=403, 
            detail="DROP operations are completely forbidden for security reasons."
        )
    
    if re.search(r'\bTRUNCATE\b', query_no_comments):
        log.warning(f"[SECURITY] Blocked TRUNCATE attempt by {current_user_email or 'anonymous'} on connection {query_execution_request.name}")
        raise HTTPException(
            status_code=403, 
            detail="TRUNCATE operations are completely forbidden for security reasons."
        )
    
    # 3. BLOCK multiple statements (only one query allowed)
    cleaned_query = re.sub(r"'[^']*'", "", query_input)
    cleaned_query = re.sub(r'"[^"]*"', "", cleaned_query)
    
    semicolons = cleaned_query.count(';')
    ends_with_semicolon = cleaned_query.strip().endswith(';')
    
    if semicolons > 1 or (semicolons == 1 and not ends_with_semicolon):
        log.warning(f"[SECURITY] Blocked multiple statements by {current_user_email or 'anonymous'} on connection {query_execution_request.name}")
        raise HTTPException(
            status_code=403, 
            detail="Multiple SQL statements are not allowed. Please execute one query at a time."
        )
    
    # 4. Additional dangerous pattern checks
    dangerous_patterns = [
        (r';\s*DELETE\s+', "Chained DELETE detected"),
        (r';\s*UPDATE\s+', "Chained UPDATE detected"),
        (r';\s*INSERT\s+', "Chained INSERT detected"),
        (r';\s*CREATE\s+', "Chained CREATE detected"),
        (r';\s*ALTER\s+', "Chained ALTER detected"),
        (r'UNION\s+.*SELECT', "UNION-based injection attempt"),
        (r'INTO\s+OUTFILE', "File writing not allowed"),
        (r'INTO\s+DUMPFILE', "File writing not allowed"),
        (r'LOAD_FILE', "File reading not allowed"),
    ]
    
    for pattern, error_msg in dangerous_patterns:
        if re.search(pattern, query_no_comments, re.IGNORECASE):
            log.warning(f"[SECURITY] Blocked dangerous pattern by {current_user_email or 'anonymous'}: {error_msg}")
            raise HTTPException(
                status_code=403,
                detail=f"Security violation: {error_msg}"
            )
    
    # ==================== END SECURITY VALIDATIONS ====================
   
    log.debug(f"Running query: {query_execution_request.data}")
    session = None
 
    try:
        # Get the engine for the specific database connection
        manager.add_sql_database(query_execution_request.name, await _build_connection_string_helper(config))
        session = manager.get_sql_session(query_execution_request.name)

        # ==================== GET CONNECTION CREATOR FROM DATABASE ====================
        creator_info = await db_connection_manager.get_user_email(query_execution_request.name)
        creator_email = creator_info.get("created_by") if creator_info else None
        
        # Clean up creator_email (strip whitespace and handle empty strings)
        if creator_email:
            creator_email = creator_email.strip()
            if not creator_email:  # Empty string after strip
                creator_email = None
        
        # ==================== DETERMINE IF CONNECTION IS PUBLIC ====================
        # Public connection: created_by is NULL in db_connections table
        is_public_connection = (creator_email is None)
        
        log.debug(f"Executing query on connection {query_execution_request.name}")
        log.debug(f"Connection creator (from DB): {creator_email or 'NULL (public connection)'}")
        log.debug(f"Request user: {current_user_email or 'NULL'}")
        log.debug(f"Is public connection: {is_public_connection}")
        
        # ==================== DETERMINE QUERY TYPE ====================
        is_ddl = any(query_upper.startswith(word) for word in ["CREATE", "ALTER"])
        is_select = query_upper.startswith("SELECT")
        is_dml = any(query_upper.startswith(word) for word in ["INSERT", "UPDATE", "DELETE"])
        
        # ==================== HANDLE SELECT QUERIES ====================
        # SELECT queries are allowed for EVERYONE
        if is_select:
            log.debug("Executing SELECT Query")
            result = session.execute(text(query_execution_request.data))
            
            columns = list(result.keys())
            rows = result.fetchall()

            rows_dict = [{columns[i]: row[i] for i in range(len(columns))} for row in rows]

            return {
                "status": "success",
                "operation": "SELECT",
                "columns": columns,
                "rows": rows_dict,
                "row_count": len(rows_dict)
            }
        
        # ==================== HANDLE DDL QUERIES (CREATE, ALTER) ====================
        elif is_ddl:
            # If it's a PUBLIC connection (creator_email is NULL in DB), allow everyone
            if is_public_connection:
                log.info(f"[PUBLIC CONNECTION] Allowing DDL operation on public connection '{query_execution_request.name}' by {current_user_email or 'anonymous'}")
            else:
                # If it's a PRIVATE connection, require created_by field and verify ownership
                if not current_user_email:
                    raise HTTPException(
                        status_code=403,
                        detail="DDL operations on private connections require user identification. Please provide created_by field."
                    )
                
                # Check if current user is the creator
                if creator_email.lower() != current_user_email.lower():
                    raise HTTPException(
                        status_code=403,
                        detail="You don't have permission to execute DDL queries (CREATE, ALTER) on this connection. Only the connection creator can perform these operations."
                    )
                
                log.info(f"[PRIVATE CONNECTION] Allowing DDL operation by creator {current_user_email} on connection '{query_execution_request.name}'")
            
            log.debug("Executing DDL Query")
            result = session.execute(text(query_execution_request.data))
            session.commit()
            
            return {
                "status": "success",
                "operation": "DDL",
                "message": "DDL Query executed successfully."
            }
        
        # ==================== HANDLE DML QUERIES (INSERT, UPDATE, DELETE) ====================
        elif is_dml:
            # If it's a PUBLIC connection (creator_email is NULL in DB), allow everyone
            if is_public_connection:
                log.info(f"[PUBLIC CONNECTION] Allowing DML operation on public connection '{query_execution_request.name}' by {current_user_email or 'anonymous'}")
            else:
                # If it's a PRIVATE connection, require created_by field and verify ownership
                if not current_user_email:
                    raise HTTPException(
                        status_code=403,
                        detail="DML operations on private connections require user identification. Please provide created_by field."
                    )
                
                # Check if current user is the creator
                if creator_email.lower() != current_user_email.lower():
                    raise HTTPException(
                        status_code=403,
                        detail="You don't have permission to execute DML queries (INSERT, UPDATE, DELETE) on this connection. Only the connection creator can perform these operations."
                    )
                
                log.info(f"[PRIVATE CONNECTION] Allowing DML operation by creator {current_user_email} on connection '{query_execution_request.name}'")
            
            log.debug("Executing DML Query")
            result = session.execute(text(query_execution_request.data))
            session.commit()

            affected_rows = result.rowcount if hasattr(result, 'rowcount') else 0
            log.debug(f"Rows affected: {affected_rows}")
            
            return {
                "status": "success",
                "operation": "DML",
                "affected_rows": affected_rows,
                "message": f"Query executed successfully. {affected_rows} rows affected."
            }
        
        # ==================== UNKNOWN QUERY TYPE ====================
        else:
            raise HTTPException(
                status_code=400,
                detail="Unable to determine query type. Supported operations: SELECT, INSERT, UPDATE, DELETE, CREATE, ALTER"
            )
 
    except HTTPException:
        raise
        
    except SQLAlchemyError as e:
        log.error(f"Query failed for {current_user_email or 'anonymous'} on connection {query_execution_request.name}: {str(e)}")
        
        error_str = str(e).lower()
        
        if "syntax error" in error_str or "near" in error_str:
            detail = "SQL syntax error. Please check your query syntax."
        elif "does not exist" in error_str:
            detail = "The specified table or column does not exist."
        elif "permission denied" in error_str or "access denied" in error_str:
            detail = "Database permission denied. Please verify your access rights."
        elif "foreign key" in error_str or "constraint" in error_str:
            detail = "Database constraint violation. Please check your data and relationships."
        elif "duplicate" in error_str or "unique" in error_str:
            detail = "Duplicate entry. A record with this value already exists."
        elif "timeout" in error_str:
            detail = "Query execution timeout. Please try a simpler query."
        elif "connection" in error_str:
            detail = "Database connection error. Please try again."
        elif "does not return rows" in error_str or "closed automatically" in error_str:
            detail = "Query executed but returned no result set. This is normal for DDL/DML operations."
        else:
            detail = "Query execution failed. Please check your query and try again."
        
        raise HTTPException(status_code=400, detail=detail)
 
    except Exception as e:
        log.error(f"Unexpected error for {current_user_email or 'anonymous'} on connection {query_execution_request.name}: {str(e)}")
        raise HTTPException(status_code=500, detail="An unexpected error occurred while executing the query. Please try again or contact support.")
    
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
    # Check data connector access permission with department context
    user_department = user_data.department_name 
    has_access = await authorization_service.check_data_connector_access(user_data.role, user_department)
    if not has_access:
        raise HTTPException(status_code=403, detail="You don't have permission to access data connector endpoints.")

    user_id = request.cookies.get("user_id")
    user_session = request.cookies.get("user_session")
    update_session_context(user_session=user_session, user_id=user_id, session_id=user_session, call_category="data_connector_operation")

    return await db_connection_manager.get_connections(user_data.department_name)
    


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
    # Check data connector access permission with department context
    user_department = user_data.department_name 
    has_access = await authorization_service.check_data_connector_access(user_data.role, user_department)
    if not has_access:
        raise HTTPException(status_code=403, detail="You don't have permission to access data connector endpoints.")

    user_id = request.cookies.get("user_id")
    user_session = request.cookies.get("user_session")
    update_session_context(user_session=user_session, user_id=user_id, session_id=user_session, call_category="data_connector_operation")

    return await db_connection_manager.get_connections_sql(user_data.department_name)


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
    # Check data connector access permission with department context
    user_department = user_data.department_name 
    has_access = await authorization_service.check_data_connector_access(user_data.role, user_department)
    if not has_access:
        raise HTTPException(status_code=403, detail="You don't have permission to access data connector endpoints.")

    user_id = request.cookies.get("user_id")
    user_session = request.cookies.get("user_session")
    update_session_context(user_session=user_session, user_id=user_id, session_id=user_session, call_category="data_connector_operation")

    return await db_connection_manager.get_connections_mongodb(user_data.department_name)


@router.post("/mongodb-operation")
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
    # Check data connector access permission with department context
    user_department = user_data.department_name 
    has_access = await authorization_service.check_data_connector_access(user_data.role, user_department)
    if not has_access:
        raise HTTPException(status_code=403, detail="You don't have permission to access data connector endpoints.")

    user_id = request.cookies.get("user_id")
    user_session = request.cookies.get("user_session")
    update_session_context(user_session=user_session, user_id=user_id, session_id=user_session, call_category="data_connector_operation")

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
    # Check data connector access permission with department context
    user_department = user_data.department_name 
    has_access = await authorization_service.check_data_connector_access(user_data.role, user_department)
    if not has_access:
        raise HTTPException(status_code=403, detail="You don't have permission to access data connector endpoints.")

    user_id = request.cookies.get("user_id")
    user_session = request.cookies.get("user_session")
    update_session_context(user_session=user_session, user_id=user_id, session_id=user_session, call_category="data_connector_operation")

    manager = get_connection_manager()
 
    active_sql_connections = list(manager.sql_engines.keys())

    active_mongo_connections_raw = list(manager.mongo_clients.keys())
 
    db_info_list = await db_connection_manager.get_connections_sql(department_name=user_department)
 
    connections = db_info_list.get("connections", [])

    db_type_map = {item["connection_name"]+"_"+item["department_name"]: item["connection_database_type"].lower() for item in connections}
 
    active_mysql_connections = []
    active_postgres_connections = []
    active_sqlite_connections = []
    active_mongo_connections = []
    
    def strip_department_suffix(conn_name: str, dept: str) -> str:
        if not conn_name:
            return conn_name
        if dept:
            suffix = f"_{dept}"
            if conn_name.lower().endswith(suffix.lower()):
                return conn_name[: -len(suffix)]
        # fallback: remove last underscore segment if present
        if "_" in conn_name:
            return conn_name.rsplit("_", 1)[0]
        return conn_name

    # Process MongoDB connections and strip department suffix similarly
    for conn_name in active_mongo_connections_raw:
        display_name = strip_department_suffix(conn_name, user_department)
        active_mongo_connections.append(display_name)
    
 
    for conn_name in active_sql_connections:
        db_type = db_type_map.get(conn_name)
        display_name = conn_name

        # If we have the current user's department, strip that exact suffix (case-insensitive)
        if user_department:
            suffix = "_" + user_department
            if conn_name.lower().endswith(suffix.lower()):
                display_name = conn_name[: -len(suffix)]
        else:
            # Fallback: remove only the last underscore part
            if "_" in conn_name:
                display_name = conn_name.rsplit("_", 1)[0]

        if db_type == "mysql":
            active_mysql_connections.append(display_name)
        elif db_type in ("postgres", "postgresql"):
            active_postgres_connections.append(display_name)
        elif db_type == "sqlite":
            active_sqlite_connections.append(display_name)

    return {
        "active_mysql_connections": active_mysql_connections,
        "active_postgres_connections": active_postgres_connections,
        "active_sqlite_connections": active_sqlite_connections,
        "active_mongo_connections": active_mongo_connections
    }


@router.post("/connect-by-name")
async def connect_by_connection_name(
        request: Request,
        connection_name: str = Form(...),
        db_connection_manager: MultiDBConnectionRepository = Depends(ServiceProvider.get_multi_db_connection_manager),
        authorization_service: AuthorizationService = Depends(ServiceProvider.get_authorization_service),
        user_data: User = Depends(get_current_user)
    ):
    """
    API endpoint to connect to an existing database using a saved connection name.
    
    Parameters:
    - request: The FastAPI Request object.
    - connection_name: The name of the saved connection.
    - db_connection_manager: Dependency-injected MultiDBConnectionRepository.
    - authorization_service: Authorization service for permission checking.
    - user_data: Current user information.
    
    Returns:
    - Dict[str, Any]: Status message with connection details.
    """
    # Check permissions
    # if not await authorization_service.check_operation_permission(user_data.email, user_data.role, "create", "tools"):
    #     raise HTTPException(
    #         status_code=403, 
    #         detail="You don't have permission to connect to databases. Only admins and developers can perform this action"
    #     )
    
    # Check data connector access permission with department context
    user_department = user_data.department_name 
    has_access = await authorization_service.check_data_connector_access(user_data.role, user_department)
    if not has_access:
        raise HTTPException(status_code=403, detail="You don't have permission to access data connector endpoints.")
    
    user_id = request.cookies.get("user_id")
    user_session = request.cookies.get("user_session")
    update_session_context(user_session=user_session, user_id=user_id, session_id=user_session, call_category="data_connector_operation")
    
    manager = get_connection_manager()
    
    try:
        # Fetch connection configuration from database
        config = await db_connection_manager.get_connection_config(connection_name, department_name=user_department)
        
        if not config:
            raise HTTPException(
                status_code=404, 
                detail=f"Connection '{connection_name}' not found in saved connections"
            )
        
        # Decrypt the stored PWD before using it to build the connection string
        if config.get("password"):
            config["password"] = _decrypt_password(config["password"])

        db_type = config.get("db_type", "").lower()
        
        # Validate database type
        if db_type not in ["postgresql", "mysql", "sqlite", "mongodb"]:
            raise HTTPException(
                status_code=400, 
                detail=f"Unsupported database type: {config.get('db_type')}"
            )
        
        # Check if connection is already active
        if db_type == "mongodb":
            if connection_name in manager.mongo_clients:
                return {
                    "message": f"Connection '{connection_name}' is already active",
                    "connection_name": connection_name,
                    "database_type": config.get("db_type"),
                    "database_name": config.get("database")
                }
        else:
            if connection_name in manager.sql_engines:
                return {
                    "message": f"Connection '{connection_name}' is already active",
                    "connection_name": connection_name,
                    "database_type": config.get("db_type"),
                    "database_name": config.get("database")
                }
        
        # Handle SQLite connections
        if db_type == "sqlite":
            try:
                # --- Auto-restore SQLite .db from blob if missing locally ---
                try:
                    _sp = os.getenv('STORAGE_PROVIDER', '')
                    db_filename = config.get('database', '')
                    _dept = config.get('department_name') or user_department or 'General'
                    db_file_path = os.path.join(UPLOAD_DIR, _dept, db_filename)
                    if _sp and not os.path.exists(db_file_path):
                        from src.utils.workspace_blob_sync import WorkspaceBlobSync
                        from src.storage import get_storage_client
                        _client = get_storage_client(_sp)
                        _syncer = WorkspaceBlobSync(
                            storage_client=_client,
                            project_root=os.path.abspath("."),
                        )
                        restored = _syncer.restore_sqlite_db_sync(_dept, db_filename)
                        if restored:
                            log.info(f"[BlobRestore] Restored SQLite DB '{db_filename}' for connect-by-name")
                except Exception as _re:
                    log.debug(f"[BlobRestore] SQLite DB restore skipped on connect-by-name: {_re}")

                # Build connection string
                connection_string = await _build_connection_string_helper(config)
                
                # Add SQL database connection
                manager.add_sql_database(connection_name, connection_string)
                
                # Test connection
                session_sql = manager.get_sql_session(connection_name)
                try:
                    session_sql.execute(text("SELECT 1"))
                    session_sql.commit()
                    log.info(f"[SQLite] Connection test successful for '{connection_name}'")
                except Exception as test_error:
                    manager.dispose_sql_engine(connection_name)
                    # Log full error server-side
                    log.error(f"SQLite connection test failed for '{connection_name}': {str(test_error)}")
                    # Return sanitized error
                    raise HTTPException(
                        status_code=500, 
                        detail="SQLite connection test failed. Please verify the database file exists and is accessible."
                    )
                finally:
                    session_sql.close()
                
                return {
                    "message": f"Successfully connected to SQLite database '{config.get('database')}'",
                    "connection_name": connection_name,
                    "database_type": config.get("db_type"),
                    "database_name": config.get("database")
                }
                
            except HTTPException:
                raise
            except Exception as e:
                # Log full error server-side
                log.error(f"Failed to connect to SQLite '{connection_name}': {str(e)}")
                # Return sanitized error
                raise HTTPException(
                    status_code=500, 
                    detail="Failed to connect to SQLite database. Please verify the connection configuration."
                )
        
        # Handle MongoDB connections
        elif db_type == "mongodb":
            try:
                # Validate required fields
                if not config.get("host") or not config.get("port"):
                    raise HTTPException(
                        status_code=400, 
                        detail="Host and port are required for MongoDB connections"
                    )
                
                # Build connection string
                connection_string = await _build_connection_string_helper(config)
                
                # Add MongoDB database connection
                manager.add_mongo_database(
                    connection_name, 
                    connection_string, 
                    config.get("database")
                )
                
                # Test connection
                mongo_db = manager.get_mongo_database(connection_name)
                try:
                    await mongo_db.command("ping")
                    log.info(f"[MongoDB] Connection test successful for '{connection_name}'")
                except Exception as ping_error:
                    await manager.close_mongo_client(connection_name)
                    # Log full error server-side
                    log.error(f"MongoDB connection test failed for '{connection_name}': {str(ping_error)}")
                    
                    # Categorize error and return sanitized message
                    error_str = str(ping_error).lower()
                    if "authentication" in error_str or "auth" in error_str:
                        detail = "MongoDB authentication failed. Please verify your credentials."
                    elif "timeout" in error_str:
                        detail = "MongoDB connection timeout. The server is not responding."
                    elif "connection refused" in error_str or "network" in error_str:
                        detail = "Unable to reach MongoDB server. Please verify network connectivity."
                    else:
                        detail = "MongoDB connection test failed. Please verify your connection settings."
                    
                    raise HTTPException(status_code=500, detail=detail)
                
                return {
                    "message": f"Successfully connected to MongoDB database '{config.get('database')}'",
                    "connection_name": connection_name,
                    "database_type": config.get("db_type"),
                    "database_name": config.get("database")
                }
                
            except HTTPException:
                raise
            except Exception as e:
                # Cleanup
                if connection_name in manager.mongo_clients:
                    await manager.close_mongo_client(connection_name)
                
                # Log full error server-side
                log.error(f"Failed to connect to MongoDB '{connection_name}': {str(e)}")
                
                # Return sanitized error
                error_str = str(e).lower()
                if "authentication" in error_str or "auth" in error_str:
                    detail = "MongoDB authentication failed. Please verify your credentials."
                elif "timeout" in error_str:
                    detail = "MongoDB connection timeout."
                elif "connection refused" in error_str or "network" in error_str:
                    detail = "Unable to reach MongoDB server."
                else:
                    detail = "Failed to connect to MongoDB. Please verify your connection configuration."
                
                raise HTTPException(status_code=500, detail=detail)
        
        # Handle PostgreSQL and MySQL connections
        elif db_type in ["postgresql", "mysql"]:
            try:
                # Validate required fields
                if not config.get("host") or not config.get("port"):
                    raise HTTPException(
                        status_code=400, 
                        detail=f"Host and port are required for {config.get('db_type')} connections"
                    )
                
                if not config.get("username") or not config.get("password"):
                    raise HTTPException(
                        status_code=400, 
                        detail=f"Username and password are required for {config.get('db_type')} connections"
                    )
                
                # Build connection string
                connection_string = await _build_connection_string_helper(config)
                
                # Add SQL database connection
                manager.add_sql_database(connection_name, connection_string)
                
                # Test connection
                session_sql = manager.get_sql_session(connection_name)
                try:
                    session_sql.execute(text("SELECT 1"))
                    session_sql.commit()
                    log.info(f"[{config.get('db_type').upper()}] Connection test successful for '{connection_name}'")
                except Exception as test_error:
                    manager.dispose_sql_engine(connection_name)
                    # Log full error server-side
                    log.error(f"{config.get('db_type')} connection test failed for '{connection_name}': {str(test_error)}")
                    
                    # Categorize error and return sanitized message
                    error_str = str(test_error).lower()
                    if "authentication" in error_str or "password" in error_str or "access denied" in error_str:
                        detail = f"{config.get('db_type')} authentication failed. Please verify your credentials."
                    elif "timeout" in error_str:
                        detail = f"{config.get('db_type')} connection timeout. The server is not responding."
                    elif "connection refused" in error_str or "network" in error_str or "host" in error_str:
                        detail = f"Unable to reach {config.get('db_type')} server. Please verify network connectivity."
                    elif "does not exist" in error_str and "database" in error_str:
                        detail = f"The specified database does not exist on {config.get('db_type')} server."
                    else:
                        detail = f"{config.get('db_type')} connection test failed. Please verify your connection settings."
                    
                    raise HTTPException(status_code=500, detail=detail)
                finally:
                    session_sql.close()
                
                return {
                    "message": f"Successfully connected to {config.get('db_type')} database '{config.get('database')}'",
                    "connection_name": connection_name,
                    "database_type": config.get("db_type"),
                    "database_name": config.get("database")
                }
                
            except HTTPException:
                raise
            except Exception as e:
                # Cleanup
                if connection_name in manager.sql_engines:
                    manager.dispose_sql_engine(connection_name)
                
                # Log full error server-side
                log.error(f"Failed to connect to {config.get('db_type')} '{connection_name}': {str(e)}")
                
                # Return sanitized error
                error_str = str(e).lower()
                if "authentication" in error_str or "password" in error_str or "access denied" in error_str:
                    detail = f"{config.get('db_type')} authentication failed. Please verify your credentials."
                elif "timeout" in error_str:
                    detail = f"{config.get('db_type')} connection timeout."
                elif "connection refused" in error_str or "network" in error_str or "host" in error_str:
                    detail = f"Unable to reach {config.get('db_type')} server."
                elif "does not exist" in error_str and "database" in error_str:
                    detail = f"The specified database does not exist."
                else:
                    detail = f"Failed to connect to {config.get('db_type')}. Please verify your connection configuration."
                
                raise HTTPException(status_code=500, detail=detail)
    
    except HTTPException:
        raise
    except Exception as e:
        # Log full error server-side
        log.error(f"Unexpected error connecting by name '{connection_name}': {str(e)}")
        
        # Return generic sanitized error
        raise HTTPException(
            status_code=500, 
            detail="An unexpected error occurred while connecting to the database. Please contact support if the issue persists."
        )


@router.post("/store-db-schema")
async def store_database_schema(
    request: Request,
    connection_name: str = Form(...),
    schema_text: str = Form(...),
    authorization_service: AuthorizationService = Depends(ServiceProvider.get_authorization_service),
    user_data: User = Depends(get_current_user)
):
    """
    Store database schema to a file (SHARED/REUSABLE across all agents).
    
    Any agent can read this using: cat /databases/{connection_name}/schema.md
    
    Parameters:
    - connection_name: The database connection name
    - schema_text: The schema text (markdown format)
    
    Returns:
    - Dict with storage status and file path
    """
    try:
        from src.inference.database_tools_cache import save_database_schema
        
        result = save_database_schema(
            connection_name=connection_name,
            schema_text=schema_text,
            department=user_data.department_name
        )
        
        return result
        
    except Exception as e:
        log.error(f"Error storing database schema for {connection_name}: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to store database schema: {str(e)}"
        )


@router.post("/store-db-samples")
async def store_database_samples(
    request: Request,
    connection_name: str = Form(...),
    samples_text: str = Form(...),
    authorization_service: AuthorizationService = Depends(ServiceProvider.get_authorization_service),
    user_data: User = Depends(get_current_user)
):
    """
    Store database sample data to a file (SHARED/REUSABLE across all agents).
    
    Any agent can read this using: cat /databases/{connection_name}/samples.md
    
    Parameters:
    - connection_name: The database connection name
    - samples_text: The sample data text (markdown format)
    
    Returns:
    - Dict with storage status and file path
    """
    try:
        from src.inference.database_tools_cache import save_database_samples
        
        result = save_database_samples(
            connection_name=connection_name,
            samples_text=samples_text,
            department=user_data.department_name
        )
        
        return result
        
    except Exception as e:
        log.error(f"Error storing database samples for {connection_name}: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to store database samples: {str(e)}"
        )


@router.get("/list-db-files")
async def list_database_files(
    connection_name: str = None,
    authorization_service: AuthorizationService = Depends(ServiceProvider.get_authorization_service),
    user_data: User = Depends(get_current_user)
):
    """
    List all database schema/sample files.
    
    If connection_name is provided, lists files for that connection only.
    Otherwise, lists all connections and their files.
    
    Parameters:
    - connection_name: Optional - specific connection to list
    
    Returns:
    - List of file info dicts with name and virtual_path
    """
    try:
        from src.inference.database_tools_cache import get_database_files, list_database_connections

        files = get_database_files(connection_name, department=user_data.department_name)
        connections = list_database_connections(department=user_data.department_name)

        # Auto-restore from blob if no local database files found
        if not files and not connections:
            try:
                _sp = os.getenv('STORAGE_PROVIDER', '')
                if _sp:
                    from src.utils.workspace_blob_sync import WorkspaceBlobSync
                    from src.storage import get_storage_client
                    _client = get_storage_client(_sp)
                    _dept = user_data.department_name or "General"
                    _syncer = WorkspaceBlobSync(
                        storage_client=_client,
                        workspace_root="./agent_workspaces",
                        department=_dept,
                    )
                    report = await _syncer.restore_database_cache()
                    if report and report.synced > 0:
                        log.info(f"[BlobRestore] Restored {report.synced} database cache files from blob")
                        # Re-read after restore
                        files = get_database_files(connection_name, department=user_data.department_name)
                        connections = list_database_connections(department=user_data.department_name)
            except Exception as _e:
                log.debug(f"[BlobRestore] database cache restore skipped: {_e}")

        return {
            "status": "success",
            "connections": connections,
            "files": files
        }
        
    except Exception as e:
        log.error(f"Error listing database files: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to list database files: {str(e)}"
        )


@router.get("/get-db-details/{connection_name}")
async def get_database_details(
    connection_name: str,
    db_connection_manager: MultiDBConnectionRepository = Depends(ServiceProvider.get_multi_db_connection_manager),
    authorization_service: AuthorizationService = Depends(ServiceProvider.get_authorization_service),
    user_data: User = Depends(get_current_user)
):
    """
    Get the schema, sample data, blocked commands and default commands for a specific database connection.

    Parameters:
    - connection_name: The database connection name

    Returns:
    - Dict with schema content, samples content, blocked commands and default commands
    """
    try:
        from src.inference.database_tools_cache import get_database_directory

        db_dir = get_database_directory(connection_name, department=user_data.department_name)
        schema_file = db_dir / "schema.md"
        samples_file = db_dir / "samples.md"

        schema_content = None
        samples_content = None

        if schema_file.exists():
            schema_content = schema_file.read_text(encoding="utf-8")
        if samples_file.exists():
            samples_content = samples_file.read_text(encoding="utf-8")

        # --- Auto-restore from blob if schema/samples missing locally ---
        if schema_content is None and samples_content is None:
            try:
                import asyncio
                _sp = os.getenv('STORAGE_PROVIDER', '')
                _BLOB_RESTORE_TIMEOUT = int(os.getenv('BLOB_RESTORE_TIMEOUT', '30'))
                if _sp:
                    from src.utils.workspace_blob_sync import WorkspaceBlobSync
                    from src.storage import get_storage_client
                    _client = get_storage_client(_sp)
                    _dept = user_data.department_name or "General"
                    _syncer = WorkspaceBlobSync(
                        storage_client=_client,
                        workspace_root="./agent_workspaces",
                        department=_dept,
                    )
                    # Restore database cache (schema.md / samples.md) from blob with timeout
                    try:
                        report = await asyncio.wait_for(
                            _syncer.restore_database_cache(connection_name=connection_name),
                            timeout=_BLOB_RESTORE_TIMEOUT
                        )
                    except asyncio.TimeoutError:
                        log.warning(f"[BlobRestore] Timed out restoring database cache for '{connection_name}' after {_BLOB_RESTORE_TIMEOUT}s")
                        report = None
                    if report and report.synced > 0:
                        log.info(f"[BlobRestore] Restored {report.synced} database cache files for '{connection_name}' from blob")
                        # Re-read after restore
                        if schema_file.exists():
                            schema_content = schema_file.read_text(encoding="utf-8")
                        if samples_file.exists():
                            samples_content = samples_file.read_text(encoding="utf-8")

                    # Also restore the SQLite .db file if missing
                    config = await db_connection_manager.get_connection_config(connection_name)
                    if config and config.get("db_type", "").lower() == "sqlite":
                        db_filename = config.get("database", "")
                        _conn_dept = config.get("department_name") or _dept
                        if db_filename:
                            db_file_path = os.path.join(UPLOAD_DIR, _conn_dept, db_filename)
                            if not os.path.exists(db_file_path):
                                _syncer_for_db = WorkspaceBlobSync(
                                    storage_client=_client,
                                    project_root=os.path.abspath("."),
                                )
                                try:
                                    restored = await asyncio.wait_for(
                                        asyncio.to_thread(_syncer_for_db.restore_sqlite_db_sync, _conn_dept, db_filename),
                                        timeout=_BLOB_RESTORE_TIMEOUT
                                    )
                                except asyncio.TimeoutError:
                                    log.warning(f"[BlobRestore] Timed out restoring SQLite DB '{db_filename}' after {_BLOB_RESTORE_TIMEOUT}s")
                                    restored = False
                                if restored:
                                    log.info(f"[BlobRestore] Restored SQLite DB '{db_filename}' for get-db-details")
            except Exception as _restore_err:
                log.debug(f"[BlobRestore] database cache/sqlite restore skipped for get-db-details: {_restore_err}")

        if schema_content is None and samples_content is None:
            raise HTTPException(
                status_code=404,
                detail=f"No schema or samples files found for connection '{connection_name}'"
            )

        # Fetch blocked commands for this connection
        default_blocked_commands = [
            "DROP", "DELETE", "UPDATE", "INSERT", "ALTER", "CREATE",
            "TRUNCATE", "EXEC", "EXECUTE", "GRANT", "REVOKE", "COMMIT", "ROLLBACK"
        ]
        blocked_commands = None
        try:
            blocked_commands = await db_connection_manager.get_blocked_sql_commands(connection_name)
        except Exception as bc_err:
            log.warning(f"Could not fetch blocked commands for {connection_name}: {bc_err}")

        return {
            "status": "success",
            "connection_name": connection_name,
            "schema": schema_content,
            "samples": samples_content,
            "schema_exists": schema_content is not None,
            "samples_exists": samples_content is not None,
            "blocked_commands": blocked_commands if blocked_commands else default_blocked_commands,
            "is_custom_blocked": blocked_commands is not None,
            "default_blocked_commands": default_blocked_commands
        }

    except HTTPException:
        raise
    except Exception as e:
        log.error(f"Error reading schema/samples for {connection_name}: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to read schema/samples: {str(e)}"
        )


@router.api_route("/clear-db-files/{connection_name}", methods=["DELETE", "POST"])
async def clear_database_files(
    connection_name: str,
    authorization_service: AuthorizationService = Depends(ServiceProvider.get_authorization_service),
    user_data: User = Depends(get_current_user)
):
    """
    Clear all files for a specific database connection.
    
    Parameters:
    - connection_name: The database connection name
    
    Returns:
    - Dict with clear status
    """
    try:
        from src.inference.database_tools_cache import clear_database_files
        
        success = clear_database_files(connection_name, department=user_data.department_name)
        
        return {
            "status": "success" if success else "error",
            "message": f"Database files cleared for {connection_name}" if success else "Failed to clear files",
            "connection_name": connection_name
        }
        
    except Exception as e:
        log.error(f"Error clearing database files for {connection_name}: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to clear database files: {str(e)}"
        )


@router.api_route("/clear-all-db-files", methods=["DELETE", "POST"])
async def clear_all_database_files_endpoint(
    authorization_service: AuthorizationService = Depends(ServiceProvider.get_authorization_service),
    user_data: User = Depends(get_current_user)
):
    """
    Clear all database schema/sample files for ALL connections.
    
    Returns:
    - Dict with clear status
    """
    try:
        from src.inference.database_tools_cache import clear_all_database_files
        
        success = clear_all_database_files(department=user_data.department_name)
        
        return {
            "status": "success" if success else "error",
            "message": "All database files cleared" if success else "Failed to clear files"
        }
        
        
    except Exception as e:
        log.error(f"Error clearing all database files: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to clear all database files: {str(e)}"
        )


@router.post("/regenerate-schema-samples/{connection_name}")
async def regenerate_schema_samples_endpoint(
    connection_name: str,
    db_connection_manager: MultiDBConnectionRepository = Depends(ServiceProvider.get_multi_db_connection_manager),
    authorization_service: AuthorizationService = Depends(ServiceProvider.get_authorization_service),
    user_data: User = Depends(get_current_user)
):
    """
    Regenerate schema and sample files for an existing database connection.

    This is useful when:
    - Database schema has changed (new tables, columns)
    - Sample data needs to be refreshed
    - Schema/samples files were accidentally deleted

    Parameters:
    - connection_name: The database connection name

    Returns:
    - Dict with regeneration status and file paths
    """
    try:
        # Get connection config to determine db_type
        config = await db_connection_manager.get_connection_config(connection_name)

        if not config:
            raise HTTPException(
                status_code=404,
                detail=f"Connection '{connection_name}' not found"
            )

        db_type = config.get("db_type", "sqlite")
        manager = get_connection_manager()

        # Build department-qualified key (engines are stored as name_department)
        user_department = user_data.department_name
        name_with_dept = f"{connection_name}_{user_department}"

        # Check if connection is active, if not try to connect
        if db_type.lower() == "mongodb":
            if connection_name not in manager.mongo_clients and name_with_dept not in manager.mongo_clients:
                raise HTTPException(
                    status_code=400,
                    detail=f"Connection '{connection_name}' is not active. Please connect first using /connect-by-name"
                )
        else:
            if connection_name not in manager.sql_engines and name_with_dept not in manager.sql_engines:
                # --- Auto-restore SQLite .db from blob and reconnect ---
                reconnected = False
                if db_type.lower() == "sqlite":
                    try:
                        import asyncio
                        _sp = os.getenv('STORAGE_PROVIDER', '')
                        _BLOB_RESTORE_TIMEOUT = int(os.getenv('BLOB_RESTORE_TIMEOUT', '30'))
                        db_filename = config.get("database", "")
                        _dept = config.get("department_name") or user_department or "General"
                        db_file_path = os.path.join(UPLOAD_DIR, _dept, db_filename)
                        if _sp and db_filename and not os.path.exists(db_file_path):
                            from src.utils.workspace_blob_sync import WorkspaceBlobSync
                            from src.storage import get_storage_client
                            _client = get_storage_client(_sp)
                            _syncer = WorkspaceBlobSync(
                                storage_client=_client,
                                project_root=os.path.abspath("."),
                            )
                            try:
                                restored = await asyncio.wait_for(
                                    asyncio.to_thread(_syncer.restore_sqlite_db_sync, _dept, db_filename),
                                    timeout=_BLOB_RESTORE_TIMEOUT
                                )
                            except asyncio.TimeoutError:
                                log.warning(f"[BlobRestore] Timed out restoring SQLite DB '{db_filename}' for regenerate after {_BLOB_RESTORE_TIMEOUT}s")
                                restored = False
                            if restored:
                                log.info(f"[BlobRestore] Restored SQLite DB '{db_filename}' for regenerate-schema-samples")
                        # Try to reconnect after restore (or if file already exists)
                        if db_filename and os.path.exists(os.path.join(UPLOAD_DIR, _dept, db_filename)):
                            conn_string = await _build_connection_string_helper(config)
                            manager.add_sql_database(connection_name, conn_string)
                            reconnected = True
                            log.info(f"[Regenerate] Auto-reconnected SQLite '{connection_name}' after blob restore")
                    except Exception as _re:
                        log.debug(f"[BlobRestore] SQLite auto-restore/reconnect failed for regenerate: {_re}")

                if not reconnected:
                    raise HTTPException(
                        status_code=400,
                        detail=f"Connection '{connection_name}' is not active. Please connect first using /connect-by-name"
                    )

        # Regenerate schema and samples
        from src.inference.database_tools_cache import auto_generate_schema_and_samples

        result = await auto_generate_schema_and_samples(
            connection_name=connection_name,
            db_type=db_type,
            connection_manager=manager,
            department=user_data.department_name
        )

        return {
            "status": result.get("status"),
            "message": f"Schema and samples regenerated for {connection_name}",
            "connection_name": connection_name,
            "database_type": db_type,
            **result
        }

    except HTTPException:
        raise
    except Exception as e:
        log.error(f"Error regenerating schema/samples for {connection_name}: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to regenerate schema/samples: {str(e)}"
        )


# =============================================================================
# BLOCKED SQL COMMANDS MANAGEMENT
# =============================================================================

@router.get("/blocked-commands/{connection_name}")
async def get_blocked_commands_endpoint(
    connection_name: str,
    db_connection_manager: MultiDBConnectionRepository = Depends(ServiceProvider.get_multi_db_connection_manager),
    user_data: User = Depends(get_current_user)
):
    """
    Get the blocked SQL commands for a specific database connection.
    
    Args:
        connection_name: Name of the database connection
        
    Returns:
        Dict with blocked commands list or default commands if not configured
    """
    try:
        blocked_commands = await db_connection_manager.get_blocked_sql_commands(connection_name)
        
        # Default blocked commands if not configured
        default_blocked = [
            "DROP", "DELETE", "UPDATE", "INSERT", "ALTER", "CREATE", 
            "TRUNCATE", "EXEC", "EXECUTE", "GRANT", "REVOKE", "COMMIT", "ROLLBACK"
        ]
        
        return {
            "connection_name": connection_name,
            "blocked_commands": blocked_commands if blocked_commands else default_blocked,
            "is_custom": blocked_commands is not None,
            "default_commands": default_blocked
        }
        
    except Exception as e:
        log.error(f"Error fetching blocked commands for {connection_name}: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to fetch blocked commands: {str(e)}"
        )


@router.api_route("/blocked-commands/{connection_name}", methods=["PUT", "POST"])
async def update_blocked_commands_endpoint(
    connection_name: str,
    blocked_commands: List[str],
    db_connection_manager: MultiDBConnectionRepository = Depends(ServiceProvider.get_multi_db_connection_manager),
    authorization_service: AuthorizationService = Depends(ServiceProvider.get_authorization_service),
    user_data: User = Depends(get_current_user)
):
    """
    Update the blocked SQL commands for a specific database connection.
    
    Args:
        connection_name: Name of the database connection
        blocked_commands: List of SQL keywords to block (e.g., ["DELETE", "DROP", "TRUNCATE"])
        
    Returns:
        Dict with update status
    """
    # Check permissions - use data connector access check (consistent with /connect endpoint)
    has_access = await authorization_service.check_data_connector_access(user_data.role, user_data.department_name)
    if not has_access:
        raise HTTPException(status_code=403, detail="You don't have permission to update data connections")
    
    try:
        result = await db_connection_manager.update_blocked_sql_commands(connection_name, blocked_commands)
        
        if result.get("success"):
            return {
                "status": "success",
                "connection_name": connection_name,
                "blocked_commands": blocked_commands,
                "message": result.get("message")
            }
        else:
            raise HTTPException(status_code=400, detail=result.get("error"))
        
    except HTTPException:
        raise
    except Exception as e:
        log.error(f"Error updating blocked commands for {connection_name}: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to update blocked commands: {str(e)}"
        )

