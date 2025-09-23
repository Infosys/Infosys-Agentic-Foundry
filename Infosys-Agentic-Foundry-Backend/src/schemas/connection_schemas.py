# © 2024-25 Infosys Limited, Bangalore, India. All Rights Reserved.
from pydantic import BaseModel, Field, validator
from typing import Optional, Literal, Union, List, Dict, Any

class ConnectionSchema(BaseModel):
    """Schema for defining a database connection."""
    connection_name: str = Field(..., example="My SQLite DB", description="Unique name for the database connection.")
    connection_database_type: str = Field(..., example="sqlite", description="Type of the database (e.g., 'postgresql', 'mysql', 'sqlite', 'mongodb', 'azuresql').")
    connection_host: Optional[str] = Field("", example="localhost", description="Database host address.")
    connection_port: Optional[int] = Field(0, example=5432, description="Database port number.")
    connection_username: Optional[str] = Field("", example="user", description="Username for database authentication.")
    connection_password: Optional[str] = Field("", example="password", description="Password for database authentication.")
    connection_database_name: str = Field(..., description="Name of the database, file path for SQLite, or URI for MongoDB.")

    @validator('connection_database_type')
    def valid_db_type(cls, v):
        valid_types = ["postgresql", "mysql", "sqlite", "mongodb", "azuresql"]
        if v.lower() not in valid_types:
            raise ValueError(f"Database type must be one of {valid_types}")
        return v.lower()

class DBConnectionRequest(BaseModel):
    """Schema for requesting a database connection."""
    name: str = Field(..., description="Unique name for this connection instance.")
    db_type: str = Field(..., description="Type of the database (e.g., 'postgresql', 'mysql', 'sqlite', 'mongodb', 'azuresql').")
    host: str = Field(..., description="Database host.")
    port: int = Field(..., description="Database port.")
    username: str = Field(..., description="Database username.")
    password: str = Field(..., description="Database password.")
    database: str = Field(..., description="Database name, file path, or URI.")
    flag_for_insert_into_db_connections_table: str = Field(..., description="Flag to indicate if connection details should be saved to DB.")

class QueryGenerationRequest(BaseModel):
    """Schema for requesting a natural language query to SQL/NoSQL conversion."""
    database_type: str = Field(..., description="Type of the database (e.g., 'PostgreSQL', 'MongoDB').")
    natural_language_query: str = Field(..., description="The natural language query to convert.")

class QueryExecutionRequest(BaseModel):
    """Schema for executing a database query."""
    name: str = Field(..., description="The name of the established database connection.")
    query: str = Field(..., description="The database query to execute.")

class CRUDRequest(BaseModel):
    """Schema for performing CRUD operations via a connected database."""
    name: str = Field(..., description="The name of the established database connection.")
    operation: str = Field(..., description="CRUD operation: 'create', 'read', 'update', 'delete'.")
    table: str = Field(..., description="The table or collection name.")
    data: Dict[str, Any] = Field({}, description="Data for create/update operations.")
    condition: str = Field("", description="SQL WHERE clause or MongoDB query for read/update/delete.")

class ToolRequestModel(BaseModel):
    """Schema for a tool request that includes a database connection name."""
    tool_description: str
    code_snippet: str
    model_name: str
    created_by: str
    tag_ids: List[str] # Changed from List[int] to List[str] as tag_ids are UUIDs
    db_connection_name: Optional[str] = Field(None, description="Optional name of a database connection to associate with the tool.")

class DBDisconnectRequest(BaseModel):
    """Schema for disconnecting from a database."""
    name: str = Field(..., description="The name of the connection to disconnect.")
    db_type: str = Field(..., description="The type of the database (e.g., 'postgresql', 'mongodb').")
    flag: str = Field(..., description="Flag to indicate if connection details should be removed from DB.")

class MONGODBOperation(BaseModel):
    """Schema for performing MongoDB operations."""
    conn_name: str = Field(..., description="The name of the MongoDB connection.")
    collection: str = Field(..., description="The name of the MongoDB collection.")
    operation: Literal["find", "insert", "update", "delete"] = Field(..., description="MongoDB operation.")
    mode: Literal["one", "many"] = Field(..., description="Operation mode: 'one' or 'many'.")
    query: Optional[dict] = Field({}, description="Query filter for find/update/delete.")
    data: Optional[Union[dict, List[dict]]] = Field(None, description="Data for insert operations.")
    update_data: Optional[dict] = Field(None, description="Update data for update operations.")

# # Helper to clean MongoDB ObjectId (can be a static method in a utility class)
# def clean_document(doc: Dict[str, Any]) -> Dict[str, Any]:
#     if not doc:
#         return {}
#     if "_id" in doc and isinstance(doc["_id"], ObjectId):
#         doc["_id"] = str(doc["_id"])
#     for k, v in doc.items():
#         if isinstance(v, ObjectId):
#             doc[k] = str(v)
#     return doc

