# © 2024-25 Infosys Limited, Bangalore, India. All Rights Reserved.
import os
import ast
import time
import shutil

from urllib import response
from bson import ObjectId
from langchain_openai import AzureChatOpenAI

import asyncpg
from MultiDBConnection_Manager import get_connection_manager
import asyncio
import bcrypt
import uuid
import secrets
import warnings
from dotenv import load_dotenv
from sqlalchemy import text
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.exc import SQLAlchemyError
from motor.motor_asyncio import AsyncIOMotorClient


from typing import List, Dict, Optional, Union
from fastapi import (
    FastAPI, UploadFile, File, HTTPException, Request, Response, WebSocket, WebSocketDisconnect, Query,
    BackgroundTasks, Depends, Form
)
from pathlib import Path
from fastapi_ws_router import WSRouter
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, FileResponse
from fastapi.encoders import jsonable_encoder

from langchain_google_genai import GoogleGenerativeAIEmbeddings
from langchain_community.vectorstores import FAISS
from langchain_community.document_loaders import TextLoader
from langchain.text_splitter import CharacterTextSplitter
from langchain_pymupdf4llm import PyMuPDF4LLMLoader

from contextlib import asynccontextmanager
from contextlib import closing
from pydantic import BaseModel, Field, validator
from phoenix.otel import register
from phoenix.trace import using_project
from tool_validation import graph
from src.models.model import load_model
from src.utils.secrets_handler import current_user_email
from typing import Literal
from groundtruth import evaluate_ground_truth_file

from src.database.database_manager import DatabaseManager, REQUIRED_DATABASES
from src.database.repositories import (
    TagRepository, TagToolMappingRepository, TagAgentMappingRepository,
    ToolRepository, ToolAgentMappingRepository, RecycleToolRepository,
    AgentRepository, RecycleAgentRepository, ChatHistoryRepository
)
from src.tools.tool_code_processor import ToolCodeProcessor
from src.database.services import (
    TagService, ToolService, AgentService, ChatService
)

from src.inference.inference_utils import InferenceUtils
from src.inference.base_agent_inference import (
    AgentInferenceRequest, AgentInferenceHITLRequest, BaseAgentInference
)
from src.inference.react_agent_inference import ReactAgentInference
from src.inference.planner_executor_critic_agent_inference import MultiAgentInference
from src.inference.planner_executor_agent_inference import PlannerExecutorAgentInference
from src.inference.react_critic_agent_inference import ReactCriticAgentInference
from src.inference.meta_agent_inference import MetaAgentInference
from src.inference.planner_meta_agent_inference import PlannerMetaAgentInference

from src.agent_templates.react_agent_onboard import ReactAgentOnboard
from src.agent_templates.planner_executor_critic_agent_onboard import MultiAgentOnboard
from src.agent_templates.planner_executor_agent_onboard import PlannerExecutorAgentOnboard
from src.agent_templates.react_critic_agent_onboard import ReactCriticAgentOnboard
from src.agent_templates.meta_agent_onboard import MetaAgentOnboard
from src.agent_templates.planner_meta_agent_onboard import PlannerMetaAgentOnboard

from database_creation import initialize_tables
from database_manager import (
    get_agents_by_id, assign_general_tag_to_untagged_items, insert_into_db_connections_table, insert_into_feedback_table,
    get_approvals, get_approval_agents, update_feedback_response, get_response_data,
    get_evaluation_data_by_agent_names, get_agent_metrics_by_agent_names,
    get_tool_metrics_by_agent_names, get_tool_data
)

from evaluation_metrics import process_unprocessed_evaluations
from telemetry_wrapper import logger as log, update_session_context
import asyncio
import sys
import tempfile
import json
from datetime import datetime

from src.utils.secrets_handler import (
    setup_secrets_manager, 
    get_user_secrets, 
    set_user_secret, 
    delete_user_secret, 
    list_user_secrets, 
    get_user_secrets_dict,
    current_user_email,
    create_public_key,
    update_public_key,
    get_public_key,
    get_all_public_keys,
    delete_public_key,
    list_public_keys,
)

load_dotenv()
task_tracker: dict[str, asyncio.Task] = {}
DB_URI=os.getenv("POSTGRESQL_DATABASE_URL", "")
POSTGRESQL_HOST = os.getenv("POSTGRESQL_HOST", "")
POSTGRESQL_USER = os.getenv("POSTGRESQL_USER", "")
POSTGRESQL_PASSWORD = os.getenv("POSTGRESQL_PASSWORD", "")
DATABASE = os.getenv("DATABASE", "")

DB_URI = os.getenv("POSTGRESQL_DATABASE_URL", "")
# Set Phoenix collector endpoint
os.environ["PHOENIX_COLLECTOR_ENDPOINT"] = os.getenv("PHOENIX_COLLECTOR_ENDPOINT")
os.environ["PHOENIX_GRPC_PORT"] = os.getenv("PHOENIX_GRPC_PORT",'50051')
os.environ["PHOENIX_SQL_DATABASE_URL"] = os.getenv("PHOENIX_SQL_DATABASE_URL")


# --- Global Instances (initialized in lifespan) ---
# These will hold the single instances of managers and services.
# They are declared globally so FastAPI's Depends can access them.
db_manager: DatabaseManager = None

# Repositories (usually not directly exposed via Depends, but used by services)
tag_repo: TagRepository = None
tag_tool_mapping_repo: TagToolMappingRepository = None
tag_agent_mapping_repo: TagAgentMappingRepository = None
tool_repo: ToolRepository = None
tool_agent_mapping_repo: ToolAgentMappingRepository = None
recycle_tool_repo: RecycleToolRepository = None
agent_repo: AgentRepository = None
recycle_agent_repo: RecycleAgentRepository = None
chat_history_repo: ChatHistoryRepository = None

# Utility Processors
tool_code_processor: ToolCodeProcessor = None

# Services (these are typically exposed via Depends for endpoints)
tag_service: TagService = None
tool_service: ToolService = None
agent_service: AgentService = None
chat_service: ChatService = None

# Specific Agent Services (these are typically exposed via Depends for endpoints)
react_agent_service: ReactAgentOnboard = None
multi_agent_service: MultiAgentOnboard = None
planner_executor_agent_service: PlannerExecutorAgentOnboard = None
react_critic_agent_service: ReactCriticAgentOnboard = None
meta_agent_service: MetaAgentOnboard = None
planner_meta_agent_service: PlannerMetaAgentOnboard = None

# Inference
inference_utils: InferenceUtils = None
react_agent_inference: ReactAgentInference = None
multi_agent_inference: MultiAgentInference = None
planner_executor_agent_inference: PlannerExecutorAgentInference = None
react_critic_agent_inference : ReactCriticAgentInference = None
meta_agent_inference: MetaAgentInference = None
planner_meta_agent_inference: PlannerMetaAgentInference = None


if sys.platform.startswith("win"):
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Manages the startup and shutdown events for the FastAPI application.
    - On startup: Initializes database connections, creates tables, and sets up service instances.
    - On shutdown: Closes database connections.
    """
    global db_manager, tag_repo, tag_tool_mapping_repo, tag_agent_mapping_repo, \
           tool_repo, tool_agent_mapping_repo, recycle_tool_repo, \
           agent_repo, recycle_agent_repo, chat_history_repo, \
           tool_code_processor, tag_service, tool_service, agent_service, \
           react_agent_service, multi_agent_service, planner_executor_agent_service, \
           react_critic_agent_service, meta_agent_service, planner_meta_agent_service, \
           chat_service, inference_utils, react_agent_inference, multi_agent_inference, \
           planner_executor_agent_inference, react_critic_agent_inference, meta_agent_inference, \
           planner_meta_agent_inference

    log.info("Application startup initiated.")

    try:
        # 1. Initialize DatabaseManager
        # The alias 'db_main' is used for the primary database pool, so both alias or main database
        # name can be used to connect, get or close the connection pool for main database.
        db_manager = DatabaseManager(alias_to_main_db='db_main')

        # 2. Check and Create Databases (Administrative Task)
        # This ensures the databases exist before we try to connect pools to them.
        await db_manager.check_and_create_databases(required_db_names=REQUIRED_DATABASES)
        log.info("All required databases checked/created.")

        # 3. Connect to all required database pools
        # Pass the list of all databases to connect to.
        DB_USED = [REQUIRED_DATABASES[0], REQUIRED_DATABASES[6]]
        await db_manager.connect(db_names=DB_USED,
                                 min_size=3, max_size=5, # Default pool sizes
                                 db_main_min_size=5, db_main_max_size=7) # Custom sizes for main DB or agentic_workflow_as_service_database
        log.info("All database connection pools established.")

        # 4. Initialize Repositories (Pass the correct pool to each)
        # Repositories only handle raw DB operations.
        main_pool = await db_manager.get_pool('db_main')
        recycle_pool = await db_manager.get_pool('recycle')

        tag_repo = TagRepository(pool=main_pool)
        tag_tool_mapping_repo = TagToolMappingRepository(pool=main_pool)
        tag_agent_mapping_repo = TagAgentMappingRepository(pool=main_pool)
        tool_repo = ToolRepository(pool=main_pool)
        tool_agent_mapping_repo = ToolAgentMappingRepository(pool=main_pool)
        recycle_tool_repo = RecycleToolRepository(pool=recycle_pool)
        agent_repo = AgentRepository(pool=main_pool)
        recycle_agent_repo = RecycleAgentRepository(pool=recycle_pool)
        chat_history_repo = ChatHistoryRepository(pool=main_pool)
        log.info("All repositories initialized.")

        # 5. Initialize Utility Processors
        tool_code_processor = ToolCodeProcessor()
        log.info("Utility processors initialized.")

        # 6. Initialize Services (Pass their required repositories and other services)
        # Services contain business logic and orchestrate repository calls.
        tag_service = TagService(
            tag_repo=tag_repo,
            tag_tool_mapping_repo=tag_tool_mapping_repo,
            tag_agent_mapping_repo=tag_agent_mapping_repo
        )
        tool_service = ToolService(
            tool_repo=tool_repo,
            recycle_tool_repo=recycle_tool_repo,
            tool_agent_mapping_repo=tool_agent_mapping_repo,
            tag_service=tag_service, # ToolService needs TagService
            tool_code_processor=tool_code_processor,
            agent_repo=agent_repo # ToolService needs AgentRepository for dependency checks
        )
        agent_service = AgentService(
            agent_repo=agent_repo,
            recycle_agent_repo=recycle_agent_repo,
            tool_service=tool_service, # AgentService needs ToolService
            tag_service=tag_service # AgentService needs TagService
        )
        react_agent_service = ReactAgentOnboard(
            agent_repo=agent_repo,
            recycle_agent_repo=recycle_agent_repo,
            tool_service=tool_service,
            tag_service=tag_service
        )
        multi_agent_service = MultiAgentOnboard(
            agent_repo=agent_repo,
            recycle_agent_repo=recycle_agent_repo,
            tool_service=tool_service,
            tag_service=tag_service
        )
        planner_executor_agent_service = PlannerExecutorAgentOnboard(
            agent_repo=agent_repo,
            recycle_agent_repo=recycle_agent_repo,
            tool_service=tool_service,
            tag_service=tag_service
        )
        react_critic_agent_service = ReactCriticAgentOnboard(
            agent_repo=agent_repo,
            recycle_agent_repo=recycle_agent_repo,
            tool_service=tool_service,
            tag_service=tag_service
        )
        meta_agent_service = MetaAgentOnboard(
            agent_repo=agent_repo,
            recycle_agent_repo=recycle_agent_repo,
            tool_service=tool_service,
            tag_service=tag_service
        )
        planner_meta_agent_service = PlannerMetaAgentOnboard(
            agent_repo=agent_repo,
            recycle_agent_repo=recycle_agent_repo,
            tool_service=tool_service,
            tag_service=tag_service
        )
        chat_service = ChatService(chat_history_repo=chat_history_repo)

        log.info("All services initialized.")

        # 7. Initialize Inference Services
        inference_utils = InferenceUtils()
        react_agent_inference = ReactAgentInference(
            chat_service=chat_service,
            tool_service=tool_service,
            agent_service=agent_service,
            inference_utils=inference_utils
        )
        multi_agent_inference = MultiAgentInference(
            chat_service=chat_service,
            tool_service=tool_service,
            agent_service=agent_service,
            inference_utils=inference_utils
        )
        planner_executor_agent_inference = PlannerExecutorAgentInference(
            chat_service=chat_service,
            tool_service=tool_service,
            agent_service=agent_service,
            inference_utils=inference_utils
        )
        react_critic_agent_inference = ReactCriticAgentInference(
            chat_service=chat_service,
            tool_service=tool_service,
            agent_service=agent_service,
            inference_utils=inference_utils
        )
        meta_agent_inference = MetaAgentInference(
            chat_service=chat_service,
            tool_service=tool_service,
            agent_service=agent_service,
            inference_utils=inference_utils
        )
        planner_meta_agent_inference = PlannerMetaAgentInference(
            chat_service=chat_service,
            tool_service=tool_service,
            agent_service=agent_service,
            inference_utils=inference_utils
        )

        # 8. Create Tables (if they don't exist)
        # Call create_tables_if_not_exists for each service/repository that manages tables.
        # Order matters for foreign key dependencies.
        await tag_repo.create_table_if_not_exists()
        await tool_repo.create_table_if_not_exists()
        await agent_repo.create_table_if_not_exists()

        # Mapping tables (depend on main tables)
        await tag_tool_mapping_repo.create_table_if_not_exists()
        await tag_agent_mapping_repo.create_table_if_not_exists()
        await tool_agent_mapping_repo.create_table_if_not_exists() # This one had the FK removed

        # Recycle tables (depend on nothing but their pool)
        await recycle_tool_repo.create_table_if_not_exists()
        await recycle_agent_repo.create_table_if_not_exists()

        # Remaining tables
        await initialize_tables()
        log.info("All database tables checked/created.")

        # 9. Running necessary data migrations/fixes
        await tool_service.fix_tool_agent_mapping_for_meta_agents() # Ensure FK is dropped
        log.info("Database data migrations/fixes completed.")

        await assign_general_tag_to_untagged_items()
        asyncio.create_task(cleanup_old_files())

        log.info("Application startup complete. FastAPI is ready to serve requests.")

        # 10. Yield control to the application (FastAPI starts serving requests)
        yield

    except Exception as e:
        log.critical(f"Critical error during application startup: {e}", exc_info=True)
        # In a real application, you might want to exit here or put the app in a degraded state.
        # For now, re-raising will prevent the app from starting.
        raise

    finally:
        # 10. Close database connections on shutdown
        log.info("Application shutdown initiated. Closing database connections.")
        if db_manager:
            await db_manager.close()
        log.info("Application shutdown complete. Database connections closed.")



app = FastAPI(lifespan=lifespan, title="Infosys Agentic Foundry API")
router = WSRouter()


# Configure CORS
origins = [
    "",  # Add your frontend IP address
    "",  # Add you frontend Ip with port number being
    "http://127.0.0.1", # Allow 127.0.0.1
    "http://127.0.0.1:3000", #If your frontend runs on port 3000
    "http://localhost",
    "http://localhost:3000"
]

 
 
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],  # Allows all methods
    allow_headers=["*"],  # Allows all headers
)


# --- Dependency Injection Functions ---
# These functions provide the service instances to your endpoints.
# FastAPI will call these when an endpoint declares a dependency on them.

def get_tag_service() -> TagService:
    """Returns the global TagService instance."""
    return tag_service

def get_tool_service() -> ToolService:
    """Returns the global ToolService instance."""
    return tool_service

def get_agent_service() -> AgentService:
    """Returns the global AgentService instance."""
    return agent_service

def get_specialized_agent_service(agent_type: str):
    """Return the appropriate specialized service instance"""
    if agent_type == "react_agent":
        return react_agent_service
    if agent_type == "multi_agent":
        return multi_agent_service
    if agent_type == "planner_executor_agent":
        return planner_executor_agent_service
    if agent_type == "react_critic_agent":
        return react_critic_agent_service
    if agent_type == "meta_agent":
        return meta_agent_service
    if agent_type == "planner_meta_agent":
        return planner_meta_agent_service
    raise HTTPException(status_code=400, detail=f"Unsupported agent type: {agent_type}")

def get_chat_service() -> ChatService:
    """Returns the global ChatService instance."""
    return chat_service

def get_specialized_inference_service(agent_type: str) -> BaseAgentInference:
    """Return the appropriate inference service instance based on agent type."""
    if agent_type == "react_agent":
        return react_agent_inference
    if agent_type == "multi_agent":
        return multi_agent_inference
    if agent_type == "planner_executor_agent":
        return planner_executor_agent_inference
    if agent_type == "react_critic_agent":
        return react_critic_agent_inference
    if agent_type == "meta_agent":
        return meta_agent_inference
    if agent_type == "planner_meta_agent":
        return planner_meta_agent_inference
    raise HTTPException(status_code=400, detail=f"Unsupported agent type: {agent_type}")


class GetAgentRequest(BaseModel):
    """
    A class used to represent a Get Agent Request.

    Attributes:
    ----------
    agentic_application_id : str
        The ID of the agentic application.
    agent_table_name : Optional[str], optional
        The name of the agent table (default is "agent_table").
    tool_table_name : Optional[str], optional
        The name of the tool table (default is "tool_table").
    """
    agentic_application_id: str
    agent_table_name: Optional[str] = "agent_table"
    tool_table_name: Optional[str] = "tool_table"


class ToolData(BaseModel):
    """
    A class used to represent tool data.

    Attributes
    ----------
    tool_description : str
        A brief description of the tool.
    code_snippet : str
        A code snippet demonstrating the tool's usage.
    model_name : str
        The name of the model associated with the tool.
    created_by : str
        The name of the person or entity that created the tool.
    """
    tool_description: str
    code_snippet: str
    model_name: str
    tag_ids: Optional[Union[str, List[str]]] = None
    created_by: str


class AgentOnboardingRequest(BaseModel):
    """
    A class used to represent an Agent Onboarding Request.

    Attributes:
    ----------
    agent_name : str
        The name of the agent.
    agent_goal : str
        The goal or purpose of the agent.
    workflow_description : str
        A description of the workflow the agent will follow.
    model_name : str
        The name of the model to be used by the agent.
    tools_id : List[str]
        A list of tool IDs that the agent will use.
    email_id : str
        The email ID associated with the agent.
    """
    agent_name: str
    agent_goal: str
    workflow_description: str
    agent_type: Optional[str] = None
    model_name: str
    tools_id: List[str]
    email_id: str
    tag_ids: Optional[Union[str, List[str]]] = None



class UpdateToolRequest(BaseModel):
    """
    A class used to represent an Update Tool Request.

    Attributes:
    ----------
    model_name : str
        The name of the model to be updated.
    user_email_id : str
        The email ID of the user requesting the update.
    is_admin : bool, optional
        Indicates if the user has admin privileges (default is False).
    tool_description : Optional[str], optional
        A description of the tool (default is None).
    code_snippet : Optional[str], optional
        A code snippet related to the tool (default is None).
    """
    model_name: str
    user_email_id: str
    is_admin: bool = False
    tool_description: Optional[str] = None
    code_snippet: Optional[str] = None
    updated_tag_id_list: Optional[Union[str, List[str]]] = None


class DeleteToolRequest(BaseModel):
    """
    A class used to represent a Delete Tool Request.

    Attributes:
    ----------
    user_email_id : str
        The email ID of the user requesting the deletion.
    is_admin : bool, optional
        Indicates if the user has admin privileges (default is False).
    """
    user_email_id: str
    is_admin: bool = False


class UpdateAgentRequest(BaseModel):
    """
    A class used to represent an Update Agent Request.

    Attributes:
    ----------
    agentic_application_id_to_modify : str
        The ID of the agentic application to be modified.
    model_name : str
        The name of the model to be updated.
    user_email_id : str
        The email ID of the user requesting the update.
    agentic_application_description : str, optional
        A description of the agentic application (default is an empty string).
    agentic_application_workflow_description : str, optional
        A description of the workflow of the agentic application (default is an empty string).
    system_prompt : dict
        The system prompt for the agentic application.
    tools_id_to_add : List[str], optional
        A list of tool IDs to be added (default is an empty list).
    tools_id_to_remove : List[str], optional
        A list of tool IDs to be removed (default is an empty list).
    is_admin : bool, optional
        Indicates if the user has admin privileges (default is False).
    """
    agentic_application_id_to_modify: str
    model_name: str
    user_email_id: str
    agentic_application_description: str = ""
    agentic_application_workflow_description: str = ""
    system_prompt: dict
    tools_id_to_add: List[str] = []
    tools_id_to_remove: List[str] = []
    updated_tag_id_list: Optional[Union[str, List[str]]] = None
    is_admin: bool = False


class DeleteAgentRequest(BaseModel):
    """
    A class used to represent a Delete Agent Request.

    Attributes:
    ----------
    user_email_id : str
        The email ID of the user requesting the deletion.
    is_admin : bool, optional
        Indicates if the user has admin privileges (default is False).
    """
    user_email_id: str
    is_admin: bool = False


class PrevSessionRequest(BaseModel):
    """
    Pydantic model representing the input request for retriving previous conversations.
    """
    agent_id: str  # agent id user is working on
    session_id: str  # session id of the user


class TagData(BaseModel):
    tag_name: str
    created_by: str

class UpdateTagData(BaseModel):
    tag_id: Optional[str] = None
    tag_name: Optional[str] = None
    new_tag_name: str
    created_by: str

class DeleteTagData(BaseModel):
    tag_id: Optional[str] = None
    tag_name: Optional[str] = None
    created_by: str

class TagIdName(BaseModel):
    tag_ids: Optional[Union[str, List[str]]] = None
    tag_names: Optional[Union[str, List[str]]] = None

class ApprovalRequest(BaseModel):
    response_id: str
    query: str
    old_final_response: str
    old_steps: str
    old_response: str
    feedback: str
    new_final_response: str
    new_steps: str
    approved: bool


# Secrets Management Models
class SecretCreateRequest(BaseModel):
    user_email: str
    secret_name: str
    secret_value: str

class PublicSecretCreateRequest(BaseModel):
    secret_name: str
    secret_value: str

class SecretUpdateRequest(BaseModel):
    user_email: str
    secret_name: str
    secret_value: str

class PublicSecretUpdateRequest(BaseModel):
    secret_name: str
    secret_value: str

class SecretDeleteRequest(BaseModel):
    user_email: str
    secret_name: str

class PublicSecretDeleteRequest(BaseModel):
    secret_name: str

class SecretGetRequest(BaseModel):
    user_email: str
    secret_name: Optional[str] = None
    secret_names: Optional[List[str]] = None

class PublicSecretGetRequest(BaseModel):
    secret_name: Optional[str] = None

class SecretListRequest(BaseModel):
    user_email: str


class GroundTruthEvaluationRequest(BaseModel):
    model_name: str
    agent_type: str
    agent_name: str
    agentic_application_id: str
    session_id: str
    use_llm_grading: Optional[bool] = False



@app.post('/evaluate')
async def evaluate(fastapi_request: Request, evaluating_model1, evaluating_model2):
    user_id = fastapi_request.cookies.get("user_id")
    user_session = fastapi_request.cookies.get("user_session")
    update_session_context(user_session=user_session, user_id=user_id)
    register(
            project_name='add-tool',
            auto_instrument=True,
            set_global_tracer_provider=False,
            batch=True
        )
    with using_project('evaluation-metrics'):
        return await process_unprocessed_evaluations(
            model1=evaluating_model1,
            model2=evaluating_model2,
            get_specialized_inference_service=get_specialized_inference_service
        )


 
def parse_agent_names(agent_input: Optional[List[str]]) -> Optional[List[str]]:
    if not agent_input:
        return None
 
    if len(agent_input) == 1:
        raw = agent_input[0]
        try:
            # Try parsing stringified list format: "['Agent1','Agent2']"
            parsed = ast.literal_eval(raw)
            if isinstance(parsed, list):
                return [str(x).strip() for x in parsed]
        except Exception:
            if ',' in raw:
                return [x.strip() for x in raw.split(',')]
 
    return agent_input


@app.get("/evaluations")
async def get_evaluation_data(fastapi_request: Request,
    agent_names: Optional[List[str]] = Query(default=None),
    page: int = Query(default=1, ge=1),
    limit: int = Query(default=10, ge=1, le=100)
):
    user_id = fastapi_request.cookies.get("user_id")
    user_session = fastapi_request.cookies.get("user_session")
    update_session_context(user_session=user_session, user_id=user_id)
    parsed_names = parse_agent_names(agent_names)
    data = await get_evaluation_data_by_agent_names(parsed_names, page, limit)
    if not data:
        raise HTTPException(status_code=404, detail="No evaluation data found")
    return data  # Just return the data, no pagination metadata


@app.get("/agent-metrics")
async def get_agent_metrics(fastapi_request: Request,
    agent_names: Optional[List[str]] = Query(default=None),
    page: int = Query(default=1, ge=1),
    limit: int = Query(default=10, ge=1, le=100)
):
    user_id = fastapi_request.cookies.get("user_id")
    user_session = fastapi_request.cookies.get("user_session")
    update_session_context(user_session=user_session, user_id=user_id)
    parsed_names = parse_agent_names(agent_names)
    data = await get_agent_metrics_by_agent_names(parsed_names, page, limit)
    if not data:
        raise HTTPException(status_code=404, detail="No agent metrics found")   
    return data


@app.get("/tool-metrics")
async def get_tool_metrics(
    fastapi_request: Request,
    agent_names: Optional[List[str]] = Query(default=None),
    page: int = Query(default=1, ge=1, description="Page number (starts from 1)"),
    limit: int = Query(default=10, ge=1, le=100, description="Number of records per page (max 100)")
):
    user_id = fastapi_request.cookies.get("user_id")
    user_session = fastapi_request.cookies.get("user_session")
    update_session_context(user_session=user_session, user_id=user_id)
    parsed_names = parse_agent_names(agent_names)
    data = await get_tool_metrics_by_agent_names(parsed_names, page, limit)
    if not data:
        raise HTTPException(status_code=404, detail="No tool metrics found")  
    return data


@app.get('/get-models')
async def get_available_models(fastapi_request: Request):
    #changed
    user_id = fastapi_request.cookies.get("user_id")
    user_session = fastapi_request.cookies.get("user_session")
    update_session_context(user_session=user_session, user_id=user_id)
    try:
        # Use 'with' for automatic cleanup
        connection = await asyncpg.connect(DB_URI)
        rows = await connection.fetch("SELECT model_name FROM models;")
        data = [row["model_name"] for row in rows]  # asyncpg returns a list of Record objects
        log.debug(f"Models retrieved successfully: {data}")
        return JSONResponse(content={"models": data})

    except asyncpg.PostgresError as e:
        log.error(f"Database error while fetching models: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Database error: {str(e)}")

    except Exception as e:
        # Handle other unforeseen errors
        log.error(f"Unexpected error while fetching models: {str(e)}")
        raise HTTPException(status_code=500, detail=f"An error occurred: {str(e)}")


@app.get('/get-version')
def get_version(fastapi_request: Request):
    #changed
    user_id = fastapi_request.cookies.get("user_id")
    user_session = fastapi_request.cookies.get("user_session")
    update_session_context(user_session=user_session, user_id=user_id)
    with open(os.path.join(os.path.dirname(__file__), 'VERSION')) as f:
        return f.read().strip()


@app.post("/add-tool")
async def add_tool_endpoint(fastapi_request: Request,
    tool_data: ToolData,
    tool_service: ToolService = Depends(get_tool_service)
):
    """
    Adds a new tool to the tool table.

    Parameters:
    ----------
    tool_data : ToolData
        The data of the tool to be added.

    Returns:
    -------
    dict
        A dictionary containing the status of the operation.
        If the tool name is successfully extracted and inserted
        into the tool table, the status will indicate success.
        Otherwise, it will provide an error message.

    The status dictionary contains:
    - message : str
        A message indicating the result of the operation.
    - tool_id : str
        The ID of the tool (empty if not created).
    - is_created : bool
        Indicates whether the tool was successfully created.
    """
    #changed
    user_id = fastapi_request.cookies.get("user_id")
    user_session = fastapi_request.cookies.get("user_session")
    update_session_context(model_used=tool_data.model_name,
                            tags=tool_data.tag_ids,user_session=user_session, user_id=user_id)
    register(
            project_name='add-tool',
            auto_instrument=True,
            set_global_tracer_provider=False,
            batch=True
        )
    with using_project('add-tool'):
        status = await tool_service.create_tool(tool_data=dict(tool_data))
        log.debug(f"Tool creation status: {status}")

    update_session_context(model_used='Unassigned', 
                            tags='Unassigned',
                            tool_id='Unassigned',
                            tool_name='Unassigned',)
    return status


@app.get("/get-tools/")
async def get_tools_endpoint(fastapi_request: Request, tool_service: ToolService = Depends(get_tool_service)):
    """
    Retrieves all tools from the tool table.

    Returns:
    -------
    list
        A list of tools. If no tools are found, raises an HTTPException with status code 404.
    """
    #changed
    user_id = fastapi_request.cookies.get("user_id")
    user_session = fastapi_request.cookies.get("user_session")
    update_session_context(user_session=user_session, user_id=user_id)
    tools = await tool_service.get_all_tools()
    if not tools:
        raise HTTPException(status_code=404, detail="No tools found")
    return tools


@app.get("/get-tool/{tool_id}")
async def get_tool_by_id_endpoint(fastapi_request: Request, tool_id: str, tool_service: ToolService = Depends(get_tool_service)):
    """
    Retrieves a tool by its ID.

    Parameters:
    ----------
    id : str
        The ID of the tool to be retrieved.

    Returns:
    -------
    dict
        A dictionary containing the tool's details.
        If the tool is not found, raises an HTTPException with status code 404.
    """
    #changed
    user_id = fastapi_request.cookies.get("user_id")
    user_session = fastapi_request.cookies.get("user_session")
    update_session_context(tool_id=tool_id, user_session=user_session, user_id=user_id)
    tool = await tool_service.get_tool(tool_id=tool_id)
    if not tool:
        raise HTTPException(status_code=404, detail="Tool not found")
    update_session_context(tool_id='Unassigned')
    return tool


@app.put("/update-tool/{tool_id}")
async def update_tool_endpoint(fastapi_request: Request, tool_id: str, request: UpdateToolRequest, tool_service: ToolService = Depends(get_tool_service)):
    """
    Updates a tool by its ID.

    Parameters:
    ----------
    id : str
        The ID of the tool to be updated.
    request : UpdateToolRequest
        The request body containing the update details.

    Returns:
    -------
    dict
        A dictionary containing the status of the update operation.
        If the update is unsuccessful, raises an HTTPException with
        status code 400 and the status message.
    """
    previous_value = await tool_service.get_tool(tool_id=tool_id) 
    #changed
    user_id = fastapi_request.cookies.get("user_id")
    user_session = fastapi_request.cookies.get("user_session")
    update_session_context(tool_id=tool_id,tags=request.updated_tag_id_list,model_used=request.model_name,
                            action_type='update',action_on='tool',previous_value=previous_value, user_session=user_session, user_id=user_id)

    register(
            project_name='update-tool',
            auto_instrument=True,
            set_global_tracer_provider=False,
            batch=True
        )
    with using_project('update-tool'):
        response = await tool_service.update_tool(
            tool_id=tool_id,
            model_name=request.model_name,
            code_snippet=request.code_snippet,
            tool_description=request.tool_description,
            updated_tag_id_list=request.updated_tag_id_list,
            user_id=request.user_email_id,
            is_admin=request.is_admin
        )

    if response["is_update"]:
        new_value=await tool_service.get_tool(tool_id=tool_id)
        update_session_context(new_value=new_value)
        log.debug(f"Tool update status: {response}")
        update_session_context(new_value='Unassigned')
    update_session_context(tool_id='Unassigned',tags='Unassigned',model_used='Unassigned',action_type='Unassigned',
                        action_on='Unassigned',previous_value='Unassigned',new_value='Unassigned')

    if not response["is_update"]:
        log.error(f"Tool update failed: {response['status_message']}")
        raise HTTPException(status_code=400, detail=response["status_message"])
    return response


@app.delete("/delete-tool/{tool_id}")
async def delete_tool_endpoint(fastapi_request: Request,tool_id: str, request: DeleteToolRequest, tool_service: ToolService = Depends(get_tool_service)):
    """
    Deletes a tool by its ID.

    Parameters:
    ----------
    id : str
        The ID of the tool to be deleted.
    request : DeleteToolRequest
        The request body containing the user email ID and admin status.

    Returns:
    -------
    dict
        A dictionary containing the status of the deletion operation.
    """
    previous_value = await tool_service.get_tool(tool_id=tool_id)
    #changed
    user_id = fastapi_request.cookies.get("user_id")
    user_session = fastapi_request.cookies.get("user_session")
    update_session_context(user_session=user_session, user_id=user_id,tool_id=tool_id,action_on='tool', action_type='delete',previous_value=previous_value)
    status = await tool_service.delete_tool(
        tool_id=tool_id,
        user_id=request.user_email_id,
        is_admin=request.is_admin
    )
    update_session_context(tool_id='Unassigned',action_on='Unassigned', action_type='Unassigned',previous_value='Unassigned')
    return status


@app.post("/onboard-agent")
async def onboard_agent_endpoint(fastapi_request: Request,request: AgentOnboardingRequest):
    """
    Onboards a new agent.

    Parameters:
    ----------
    request : AgentOnboardingRequest
        The request body containing the agent's details.

    Returns:
    -------
    dict
        A dictionary containing the status of the onboarding operation.
        If an error occurs, raises an HTTPException with
        status code 500 and the error message.
    """
    #changed
    user_id = fastapi_request.cookies.get("user_id")
    user_session = fastapi_request.cookies.get("user_session")
    update_session_context(user_session=user_session, user_id=user_id)

    if not request.agent_type:
        raise HTTPException(status_code=400, detail="Agent type is required for onboarding.")
    specialized_agent_service = get_specialized_agent_service(agent_type=request.agent_type)
    update_session_context(model_used=request.model_name,
                           agent_name=request.agent_name,
                           agent_type=request.agent_type,
                           tools_binded=request.tools_id)
    project_name = f"onboard-{request.agent_type.replace('_', '-')}"
    try:
        register(
            project_name=project_name,
            auto_instrument=True,
            set_global_tracer_provider=False,
            batch=True
        )
        with using_project(project_name):
            update_session_context(
                model_used=request.model_name,
                agent_name=request.agent_name,
                agent_type=request.agent_type,
                tools_binded=request.tools_id
            )
            if request.agent_type in specialized_agent_service.meta_type_templates:
                result = await specialized_agent_service.onboard_agent(
                    agent_name=request.agent_name,
                    agent_goal=request.agent_goal,
                    workflow_description=request.workflow_description,
                    model_name=request.model_name,
                    worker_agents_id=request.tools_id,
                    user_id=request.email_id,
                    tag_ids=request.tag_ids
                )
            else:
                result = await specialized_agent_service.onboard_agent(
                    agent_name=request.agent_name,
                    agent_goal=request.agent_goal,
                    workflow_description=request.workflow_description,
                    model_name=request.model_name,
                    tools_id=request.tools_id,
                    user_id=request.email_id,
                    tag_ids=request.tag_ids
                )
        update_session_context(model_used='Unassigned',
                            agent_name='Unassigned',
                            agent_id='Unassigned',
                            agent_type='Unassigned',
                            tools_binded='Unassigned',
                            tags='Unassigned')
        return {"status": "success", "result": result}
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Error during agent onboarding: {str(e)}"
        ) from e


@app.post("/react-agent/onboard-agent")
async def onboard_react_agent(fastapi_request: Request, request: AgentOnboardingRequest):
    """
    Onboards a new React agent.

    Parameters:
    ----------
    request : AgentOnboardingRequest
        The request body containing the agent's details.

    Returns:
    -------
    dict
        A dictionary containing the status of the onboarding operation.
        If an error occurs, raises an HTTPException with
        status code 500 and the error message.
    """
    #changed
    user_id = fastapi_request.cookies.get("user_id")
    user_session = fastapi_request.cookies.get("user_session")
    update_session_context(user_session=user_session, user_id=user_id,model_used=request.model_name,
                           agent_name=request.agent_name,
                           agent_type="react",
                           tools_binded=request.tools_id)
    react_agent_service = get_specialized_agent_service(agent_type="react_agent")
    try:
        register(
            project_name='onboard-react-agent',
            auto_instrument=True,
            set_global_tracer_provider=False,
            batch=True
        )
        with using_project('onboard-react-agent'):
            result = await react_agent_service.onboard_agent(
                agent_name=request.agent_name,
                agent_goal=request.agent_goal,
                workflow_description=request.workflow_description,
                model_name=request.model_name,
                tools_id=request.tools_id,
                user_id=request.email_id,
                tag_ids=request.tag_ids
            )
        update_session_context(model_used='Unassigned',
                            agent_name='Unassigned',
                            agent_id='Unassigned',
                            agent_type='Unassigned',
                            tools_binded='Unassigned',
                            tags='Unassigned')
        return {"status": "success", "result": result}
    except Exception as e:
        log.error(f"Error during React agent onboarding: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"Error during agent onboarding: {str(e)}"
        ) from e

@app.post("/react-critic-agent/onboard-agent")
async def onboard_react_agent(fastapi_request: Request,request: AgentOnboardingRequest):
    """
    Onboards a new React agent.

    Parameters:
    ----------
    request : AgentOnboardingRequest
        The request body containing the agent's details.

    Returns:
    -------
    dict
        A dictionary containing the status of the onboarding operation.
        If an error occurs, raises an HTTPException with
        status code 500 and the error message.
    """
    #changed
    user_id = fastapi_request.cookies.get("user_id")
    user_session = fastapi_request.cookies.get("user_session")
    update_session_context(user_session=user_session, user_id=user_id,model_used=request.model_name,
                           agent_name=request.agent_name,
                           agent_type="react",
                           tools_binded=request.tools_id)
    react_critic_agent_service = get_specialized_agent_service(agent_type="react_critic_agent")
    try:
        register(
            project_name='onboard-react-agent',
            auto_instrument=True,
            set_global_tracer_provider=False,
            batch=True
        )
        with using_project('onboard-react-agent'):
            result = await react_critic_agent_service.onboard_agent(
                agent_name=request.agent_name,
                agent_goal=request.agent_goal,
                workflow_description=request.workflow_description,
                model_name=request.model_name,
                tools_id=request.tools_id,
                user_id=request.email_id,
                tag_ids=request.tag_ids
            )
        update_session_context(model_used='Unassigned',
                            agent_name='Unassigned',
                            agent_id='Unassigned',
                            agent_type='Unassigned',
                            tools_binded='Unassigned',
                            tags='Unassigned')
        return {"status": "success", "result": result}
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Error during agent onboarding: {str(e)}"
        ) from e

@app.post("/planner-executor-critic-agent/onboard-agents")
async def onboard_pec_agent(fastapi_request: Request, request: AgentOnboardingRequest):
    """
    Onboards multiple agents in one go.
    Parameters:
    ----------
    request :  AgentOnboardingRequest
        The request body containing a list of agents' onboarding details.

    Returns:
    -------
    dict
        A dictionary containing the status of the onboarding operation for each agent.
        If an error occurs, raises an HTTPException with error details.
    """
    #changed
    user_id = fastapi_request.cookies.get("user_id")
    user_session = fastapi_request.cookies.get("user_session")
    update_session_context(user_session=user_session, user_id=user_id,model_used=request.model_name,
                            agent_name=request.agent_name,
                            agent_type="planner-executor-critic",
                            tools_binded=request.tools_id)
    multi_agent_service = get_specialized_agent_service(agent_type="multi_agent")
    try:
        register(
            project_name='onboard-pec-agent',
            auto_instrument=True,
            set_global_tracer_provider=False,
            batch=True
        )
        with using_project('onboard-pec-agent'):
            result = await multi_agent_service.onboard_agent(
                agent_name=request.agent_name,
                agent_goal=request.agent_goal,
                workflow_description=request.workflow_description,
                model_name=request.model_name,
                tools_id=request.tools_id,
                user_id=request.email_id,
                tag_ids=request.tag_ids
            )
        update_session_context(model_used='Unassigned',
                            agent_name='Unassigned',
                            agent_id='Unassigned',
                            agent_type='Unassigned',
                            tools_binded='Unassigned',
                            tags='Unassigned')
        return {"status": "success", "result": result}
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Error during agent onboarding: {str(e)}") from e


@app.post("/planner-executor-agent/onboard-agents")
async def onboard_pe_agent(fastapi_request: Request,request: AgentOnboardingRequest):
    """
    Onboards multiple agents in one go.
    Parameters:
    ----------
    request :  AgentOnboardingRequest
        The request body containing a list of agents' onboarding details.

    Returns:
    -------
    dict
        A dictionary containing the status of the onboarding operation for each agent.
        If an error occurs, raises an HTTPException with error details.
    """
    #changed
    user_id = fastapi_request.cookies.get("user_id")
    user_session = fastapi_request.cookies.get("user_session")
    update_session_context(user_session=user_session, user_id=user_id,model_used=request.model_name,
                            agent_name=request.agent_name,
                            agent_type="planner-executor",
                            tools_binded=request.tools_id)
    planner_executor_agent_service = get_specialized_agent_service(agent_type="planner_executor_agent")
    try:
        register(
            project_name='onboard-pe-agent',
            auto_instrument=True,
            set_global_tracer_provider=False,
            batch=True
        )
        with using_project('onboard-pe-agent'):
            result = await planner_executor_agent_service.onboard_agent(
                agent_name=request.agent_name,
                agent_goal=request.agent_goal,
                workflow_description=request.workflow_description,
                model_name=request.model_name,
                tools_id=request.tools_id,
                user_id=request.email_id,
                tag_ids=request.tag_ids
            )
        update_session_context(model_used='Unassigned',
                            agent_name='Unassigned',
                            agent_id='Unassigned',
                            agent_type='Unassigned',
                            tools_binded='Unassigned',
                            tags='Unassigned')
        return {"status": "success", "result": result}
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Error during agent onboarding: {str(e)}") from e


# Define the API endpoint for onboarding a meta-agent
@app.post("/meta-agent/onboard-agents")
async def onboard_meta_agent(fastapi_request: Request, request: AgentOnboardingRequest):
    """
    Onboards a meta-agent.

    Parameters:
    -------
    request : MetaAgentOnboardingRequest
        The request body containing details for onboarding the meta-agent.

    Returns:
    -------
    dict
        A dictionary containing the status of the onboarding operation.
        If an error occurs, raises an HTTPException with error details.
    """
    #changed
    user_id = fastapi_request.cookies.get("user_id")
    user_session = fastapi_request.cookies.get("user_session")
    update_session_context(user_session=user_session, user_id=user_id, model_used=request.model_name,
                           agent_name=request.agent_name,
                           agent_type="meta-agent",
                           agents_binded=request.tools_id)
    meta_agent_service = get_specialized_agent_service(agent_type="meta_agent")
    try:
        register(
            project_name='onboard-meta-agent',
            auto_instrument=True,
            set_global_tracer_provider=False,
            batch=True
        )
        with using_project('onboard-meta-agent'):
            result = await meta_agent_service.onboard_agent(
                agent_name=request.agent_name,
                agent_goal=request.agent_goal,
                workflow_description=request.workflow_description,
                model_name=request.model_name,
                worker_agents_id=request.tools_id,
                user_id=request.email_id,
                tag_ids=request.tag_ids
            )
        update_session_context(model_used='Unassigned',
                            agent_name='Unassigned',
                            agent_id='Unassigned',
                            agent_type='Unassigned',
                            agents_binded='Unassigned',
                            tags='Unassigned')
        # Return success response
        return {"status": "success", "result": result}

    except Exception as e:
        # Handle any errors and provide an informative response
        raise HTTPException(
            status_code=500,
            detail=f"Error during meta-agent onboarding: {str(e)}"
        ) from e


# Define the API endpoint for onboarding a planner-meta-agent
@app.post("/planner-meta-agent/onboard-agents")
async def onboard_planner_meta_agent(fastapi_request: Request, request: AgentOnboardingRequest):
    """
    Onboards a planner-meta-agent.

    Parameters:
    -------
    request : MetaAgentOnboardingRequest
        The request body containing details for onboarding the meta-agent.

    Returns:
    -------
    dict
        A dictionary containing the status of the onboarding operation.
        If an error occurs, raises an HTTPException with error details.
    """
    #changed
    user_id = fastapi_request.cookies.get("user_id")
    user_session = fastapi_request.cookies.get("user_session")
    update_session_context(user_session=user_session, user_id=user_id, model_used=request.model_name,
                           agent_name=request.agent_name,
                           agent_type="planner-meta-agent",
                           agents_binded=request.tools_id)
    planner_meta_agent_service = get_specialized_agent_service(agent_type="planner_meta_agent")
    try:
        register(
            project_name='onboard-planner-meta-agent',
            auto_instrument=True,
            set_global_tracer_provider=False,
            batch=True
        )
        with using_project('onboard-planner-meta-agent'):

            result = await planner_meta_agent_service.onboard_agent(
                agent_name=request.agent_name,
                agent_goal=request.agent_goal,
                workflow_description=request.workflow_description,
                model_name=request.model_name,
                worker_agents_id=request.tools_id,
                user_id=request.email_id,
                tag_ids=request.tag_ids
            )

        update_session_context(model_used='Unassigned',
                            agent_name='Unassigned',
                            agent_id='Unassigned',
                            agent_type='Unassigned',
                            agents_binded='Unassigned',
                            tags='Unassigned')
        # Return success response
        return {"status": "success", "result": result}

    except Exception as e:
        # Handle any errors and provide an informative response
        raise HTTPException(
            status_code=500,
            detail=f"Error during planner-meta-agent onboarding: {str(e)}"
        ) from e



@app.get("/get-agents/")
async def get_agents_endpoint(fastapi_request: Request,
    agentic_application_type:  Optional[Union[str, List[str]]] = None,
    agent_service: AgentService = Depends(get_agent_service)
):
    """
    Retrieves agents from the specified agent table.

    Parameters:
    ----------
    agentic_application_type : Optional[str], optional
        The type of agentic application to filter agents by (default is None).
    agent_table_name : str, optional
        The name of the agent table to retrieve agents from (default is "agent_table").

    Returns:
    -------
    list
        A list of agents. If no agents are found, raises an HTTPException with status code 404.
    """
    #changed
    user_id = fastapi_request.cookies.get("user_id")
    user_session = fastapi_request.cookies.get("user_session")
    update_session_context(user_session=user_session, user_id=user_id)

    try:
        response = await agent_service.get_all_agents(agentic_application_type=agentic_application_type)

        if not response:
            raise HTTPException(status_code=404, detail="No agents found")

        return response

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error retrieving agents: {str(e)}")


@app.get("/get-agent/{agent_id}")
async def get_agent_by_id_endpoint(fastapi_request: Request,agent_id: str, agent_service: AgentService = Depends(get_agent_service)):
    """
    Retrieves an agent by its ID.

    Parameters:
    ----------
    id : str
        The ID of the agent to be retrieved.

    Returns:
    -------
    dict
        A dictionary containing the agent's details.
        If no agent is found, raises an HTTPException with status code 404.
    """
    #changed
    user_id = fastapi_request.cookies.get("user_id")
    user_session = fastapi_request.cookies.get("user_session")
    update_session_context(user_session=user_session, user_id=user_id, agent_id=agent_id)
    response = await agent_service.get_agent(agentic_application_id=agent_id)

    if not response:
        raise HTTPException(status_code=404, detail="No agents found")
    update_session_context(agent_id='Unassigned')
    return response


@app.get("/agent-details/{agent_id}")
async def get_agent_details(fastapi_request: Request, agent_id: str, agent_service: AgentService = Depends(get_agent_service)):
    """
    Retrieves detailed information about an agent by its ID.

    Parameters:
    ----------
    id : str
        The ID of the agent to be retrieved.

    Returns:
    -------
    dict
        A dictionary containing the agent's detailed information.
        If the agent is not found, raises an HTTPException with status code 404.
    """
    #changed
    user_id = fastapi_request.cookies.get("user_id")
    user_session = fastapi_request.cookies.get("user_session")
    update_session_context(user_session=user_session, user_id=user_id, agent_id=agent_id)

    response = await agent_service.get_agent_details_studio(agentic_application_id=agent_id)
    if not response:
        raise HTTPException(status_code=404, detail="Agent not found")
    update_session_context(agent_id='Unassigned')
    return response


@app.put("/planner-meta-agent/update-agent")
@app.put("/meta-agent/update-agent")
@app.put("/react-critic-agent/update-agent")
@app.put("/planner-executor-critic-agent/update-agent")
@app.put("/planner-executor-agent/update-agent")
@app.put("/react-agent/update-agent")
@app.put("/update-agent")
async def update_agent_endpoint(fastapi_request: Request, request: UpdateAgentRequest, agent_service: AgentService = Depends(get_agent_service)):
    """
    Updates an agent by its ID.

    Parameters:
    ----------
    request : UpdateAgentRequest
        The request body containing the update details.

    Returns:
    -------
    dict
        A dictionary containing the status of the update operation.
        If the update is unsuccessful, raises an HTTPException with
        status code 400 and the status message.
    """
    #changed
    user_id = fastapi_request.cookies.get("user_id")
    user_session = fastapi_request.cookies.get("user_session")
    
    agent_current_data = await agent_service.get_agent(
        agentic_application_id=request.agentic_application_id_to_modify
    )
    if not agent_current_data:
        log.error(f"Agent not found: {request.agentic_application_id_to_modify}")
        raise HTTPException(status_code=404, detail="Agent not found")
    agent_current_data = agent_current_data[0]
    agent_type = agent_current_data["agentic_application_type"]

    update_session_context(user_session=user_session, user_id=user_id, model_used=request.model_name,
                           agent_id=request.agentic_application_id_to_modify,
                           agent_name=agent_current_data["agentic_application_name"],
                           agent_type=agent_type,
                           tools_binded=request.tools_id_to_remove,
                           tags=request.updated_tag_id_list,
                           action_type='update',
                           action_on='agent',
                           previous_value=agent_current_data)
    project_name = f"update-{agent_type.replace('_', '-')}"
    register(
            project_name=project_name,
            auto_instrument=True,
            set_global_tracer_provider=False,
            batch=True
        )

    specialized_agent_service = get_specialized_agent_service(agent_type=agent_type)

    with using_project(project_name):
        if agent_type in specialized_agent_service.meta_type_templates:
            response = await specialized_agent_service.update_agent(
                agentic_application_id=request.agentic_application_id_to_modify,
                agentic_application_description=request.agentic_application_description,
                agentic_application_workflow_description=request.agentic_application_workflow_description,
                model_name=request.model_name,
                created_by=request.user_email_id,
                system_prompt=request.system_prompt,
                is_admin=request.is_admin,
                worker_agents_id_to_add=request.tools_id_to_add,
                worker_agents_id_to_remove=request.tools_id_to_remove,
                updated_tag_id_list=request.updated_tag_id_list
            )
        else:
            response = await specialized_agent_service.update_agent(
                agentic_application_id=request.agentic_application_id_to_modify,
                agentic_application_description=request.agentic_application_description,
                agentic_application_workflow_description=request.agentic_application_workflow_description,
                model_name=request.model_name,
                created_by=request.user_email_id,
                system_prompt=request.system_prompt,
                is_admin=request.is_admin,
                tools_id_to_add=request.tools_id_to_add,
                tools_id_to_remove=request.tools_id_to_remove,
                updated_tag_id_list=request.updated_tag_id_list
            )
        log.info(f"Agent update response: {response}")
        if not response["is_update"]:
            raise HTTPException(status_code=400, detail=response["status_message"])
        new_value = await agent_service.get_agent(agentic_application_id=request.agentic_application_id_to_modify)
        update_session_context(new_value=new_value[0])
    log.debug(f"Agent update status: {response}")
    update_session_context(model_used='Unassigned', agent_id='Unassigned', agent_name='Unassigned',
                        agent_type='Unassigned', tools_binded='Unassigned', tags='Unassigned', 
                        action_on='Unassigned',action_type='Unassigned',previous_value='Unassigned',new_value='Unassigned')
    return response



@app.delete("/react-agent/delete-agent/{agent_id}")
@app.delete("/delete-agent/{agent_id}")
async def delete_agent(fastapi_request: Request, agent_id: str, request: DeleteAgentRequest, agent_service: AgentService = Depends(get_agent_service)):
    """
    Deletes an agent by its ID.

    Parameters:
    ----------
    id : str
        The ID of the agent to be deleted.
    request : DeleteAgentRequest
        The request body containing the user email ID and admin status.

    Returns:
    -------
        dict
        A dictionary containing the status of the deletion operation.
        If the deletion is unsuccessful, raises an HTTPException
        with status code 400 and the status message.
    """
    previous_value = await agent_service.get_agent(agentic_application_id=agent_id)
    if not previous_value:
        raise HTTPException(status_code=404, detail="Agent not found")
    previous_value = previous_value[0]
    #changed
    user_id = fastapi_request.cookies.get("user_id")
    user_session = fastapi_request.cookies.get("user_session")
    update_session_context(user_session=user_session, user_id=user_id, agent_id=agent_id,
                           action_on='agent',
                           action_type='delete',
                           previous_value=previous_value)
    response = await agent_service.delete_agent(
        agentic_application_id=agent_id,
        user_id=request.user_email_id,
        is_admin=request.is_admin
    )

    if not response["is_delete"]:
        raise HTTPException(status_code=400, detail=response["status_message"])
    update_session_context(agent_id='Unassigned',action_on='Unassigned', action_type='Unassigned',previous_value='Unassigned')
    return response

@app.post("/meta-agent/get-chat-history")
@app.post("/react-agent/get-chat-history")
@app.post("/get-chat-history")
async def get_history(fastapi_request: Request, request: PrevSessionRequest, chat_service: ChatService = Depends(get_chat_service)):
    """
    Retrieves the chat history of a previous session.

    Parameters:
    ----------
    request : PrevSessionRequest
        The request body containing the details of the previous session.

    Returns:
    -------
    dict
        A dictionary containing the previous conversation history.
    """

    #changed
    user_id = fastapi_request.cookies.get("user_id")
    user_session = fastapi_request.cookies.get("user_session")
    update_session_context(user_session=user_session, user_id=user_id, session_id=request.session_id,agent_id=request.agent_id)
    return await chat_service.get_chat_history_from_short_term_memory(
        agentic_application_id=request.agent_id,
        session_id=request.session_id,
    )


@app.post("/get-query-response")
async def get_react_and_pec_and_pe_rc_agent_response(fastapi_request: Request, request: AgentInferenceRequest):
    """
    Gets the response for a query using agent inference.

    Parameters:
    ----------
    request : AgentInferenceRequest
        The request body containing the query details.

    Returns:
    -------
    dict
        A dictionary containing the response generated by the agent.
    """
    #changed
    user_id = fastapi_request.cookies.get("user_id")
    user_session = fastapi_request.cookies.get("user_session")
    update_session_context(user_session=user_session, user_id=user_id)
    
    session_id = request.session_id
    log.info(f"[{session_id}] Received new request.")
    current_user_email.set(request.session_id.split("_")[0])
    # Cancel existing task for the session if it exists
    existing_task = task_tracker.get(session_id)
    if existing_task and not existing_task.done():
        log.info(f"[{session_id}] Cancelling existing task...")
        existing_task.cancel()
        try:
            await existing_task
        except asyncio.CancelledError:
            log.warning(f"[{session_id}] Previous task cancelled.")

    # Update context to "processing"
    update_session_context(
        agent_id=request.agentic_application_id,
        session_id=session_id,
        model_used=request.model_name,
        user_query=request.query,
        response="Processing..."
    )

    log.info(f"[{session_id}] Starting agent inference...")

    agent_inference: BaseAgentInference = get_specialized_inference_service("react_agent")
    agent_config = await agent_inference._get_agent_config(request.agentic_application_id)
    agent_inference: BaseAgentInference = get_specialized_inference_service(agent_config["AGENT_TYPE"])

    # Define and create the inference task
    async def do_inference():
        try:
            result = await agent_inference.run(request, agent_config=agent_config)
            log.info(f"[{session_id}] Inference completed.")
            return result
        except asyncio.CancelledError:
            log.warning(f"[{session_id}] Task was cancelled during execution.")
            raise

    new_task = asyncio.create_task(do_inference())
    task_tracker[session_id] = new_task

    try:
        response = await new_task
    except asyncio.CancelledError:
        raise HTTPException(status_code=499, detail="Request was cancelled")

    # Clear the context
    update_session_context(
        agent_id="Unassigned",
        session_id="Unassigned",
        model_used="Unassigned",
        user_query="Unassigned",
        response="Unassigned"
    )

    # Optionally: clean up finished task
    if session_id in task_tracker and task_tracker[session_id].done():
        del task_tracker[session_id]
        log.info(f"[{session_id}] Task cleaned up from tracker.")

    return response

@app.post("/react-agent/get-feedback-response/{feedback}")
async def get_react_feedback_response(fastapi_request: Request, feedback: str, request: AgentInferenceRequest, chat_service: ChatService = Depends(get_chat_service)):
    """
    Gets the response for the feedback using agent inference.

    Parameters:
    ----------
    feedback: str
        The feedback type
    request : AgentInferenceRequest
        The request body containing the feedback details.

    Returns:
    -------
    dict
        A dictionary containing the response generated by the agent.
    """
    #changed
    user_id = fastapi_request.cookies.get("user_id")
    user_session = fastapi_request.cookies.get("user_session")
    update_session_context(user_session=user_session, user_id=user_id)

    try:
        current_user_email.set(request.session_id.split("_")[0])
        query = request.query
        if feedback == "like":
            return await chat_service.handle_like_feedback_message(
                agentic_application_id=request.agentic_application_id,
                session_id=request.session_id
            )
        elif feedback == "regenerate":
            request.query = "[regenerate:][:regenerate]"
        elif feedback == "feedback":
            request.query = f"[feedback:]{request.feedback}[:feedback]"
        else:
            return {"error": "Invalid Path!"}
        
        user_feedback = request.feedback
        request.feedback=None

        request.reset_conversation = False
        agent_inference: BaseAgentInference = get_specialized_inference_service("react_agent")
        agent_config = await agent_inference._get_agent_config(request.agentic_application_id)
        agent_inference: BaseAgentInference = get_specialized_inference_service(agent_config["AGENT_TYPE"])
        response = await agent_inference.run(request)
        try:
            final_response = response["response"]
            steps = response["executor_messages"][-1]["agent_steps"]
            old_response = request.prev_response["response"]
            old_steps = request.prev_response["executor_messages"][-1]["agent_steps"]
            
            await insert_into_feedback_table(
                agent_id=request.agentic_application_id.replace("-","_"),
                query=query,
                old_final_response= old_response,
                old_steps=old_steps,
                new_final_response=final_response,
                feedback=user_feedback, 
                new_steps=steps)
        except Exception as e:
            response["error"] = f"An error occurred while processing the response: {str(e)}"
        
        update_session_context(agent_id='Unassigned',session_id='Unassigned',
                           model_used='Unassigned',user_query='Unassigned',response='Unassigned')
        return response
    except Exception as e:
        return {"error": f"An error occurred while processing the request: {str(e)}"}


@app.get("/get-approvals-list")
async def get_approvals_list(fastapi_request: Request):
    """
    Retrieves the list of approvals.

    Returns:
    -------
    list
        A list of approvals. If no approvals are found, raises an HTTPException with status code 404.
    """
    #changed
    user_id = fastapi_request.cookies.get("user_id")
    user_session = fastapi_request.cookies.get("user_session")
    update_session_context(user_session=user_session, user_id=user_id)

    approvals = await get_approval_agents()
    if not approvals:
        raise HTTPException(status_code=404, detail="No approvals found")
    return approvals

@app.get("/get-responses-data/{response_id}")
async def get_responses_data_endpoint(response_id, fastapi_request: Request):
    """
    Retrieves the list of approvals.

    Returns:
    -------
    list
        A list of approvals. If no approvals are found, raises an HTTPException with status code 404.
    """
    #changed
    user_id = fastapi_request.cookies.get("user_id")
    user_session = fastapi_request.cookies.get("user_session")
    update_session_context(user_session=user_session, user_id=user_id)

    approvals = await get_response_data(response_id=response_id)
    if not approvals:
        raise HTTPException(status_code=404, detail="No Response found")
    return approvals

@app.get("/get-approvals-by-id/{agent_id}")
async def get_approval_by_id(agent_id: str, fastapi_request: Request):
    """
    Retrieves an approval by its ID.

    Parameters:
    ----------
    approval_id : str
        The ID of the approval to be retrieved.

    Returns:
    -------
    dict
        A dictionary containing the approval details.
        If no approval is found, raises an HTTPException with status code 404.
    """
    #changed
    user_id = fastapi_request.cookies.get("user_id")
    user_session = fastapi_request.cookies.get("user_session")
    update_session_context(user_session=user_session, user_id=user_id)

    approval = await get_approvals(agent_id=agent_id)
    if not approval:
        raise HTTPException(status_code=404, detail="Approval not found")
    return approval

@app.post("/update-approval-response")
async def update_approval_response(fastapi_request: Request, request: ApprovalRequest):
    """
    Updates the approval response.

    Parameters:
    ----------
    request : ApprovalRequest
        The request body containing the approval details.

    Returns:
    -------
    dict
        A dictionary containing the status of the update operation.
        If the update is unsuccessful, raises an HTTPException with
        status code 400 and the status message.
    """
    #changed
    user_id = fastapi_request.cookies.get("user_id")
    user_session = fastapi_request.cookies.get("user_session")
    update_session_context(user_session=user_session, user_id=user_id)

    response = await update_feedback_response(
        response_id=request.response_id,
        data_dictionary={
        "query": request.query,
        "old_final_response": request.old_final_response,
        "old_steps": request.old_steps,
        "old_response": request.old_response,
        "feedback": request.feedback,
        "new_final_response": request.new_final_response,
        "new_steps": request.new_steps,
        "approved": request.approved
        }
    )
    if not response["is_update"]:
        raise HTTPException(status_code=400, detail=response["status_message"])
    return response

@app.post("/meta-agent/get-query-response")
async def get_meta_agent_response(fastapi_request: Request, request: AgentInferenceRequest):
    """
    Gets the response for a query using agent inference.

    Parameters:
    ----------
    request : AgentInferenceRequest
        The request body containing the query details.

    Returns:
    -------
    dict
        A dictionary containing the response generated by the agent.
    """
    #changed
    user_id = fastapi_request.cookies.get("user_id")
    user_session = fastapi_request.cookies.get("user_session")
    update_session_context(user_session=user_session, user_id=user_id, agent_id=request.agentic_application_id,
                            session_id=request.session_id,
                            model_used=request.model_name,
                            user_query=request.query,
                            response='Processing...')
    
    current_user_email.set(request.session_id.split("_")[0])
    meta_agent_inference: MetaAgentInference = get_specialized_inference_service("meta_agent")
    response = await meta_agent_inference.run(inference_request=request)
    update_session_context(agent_id='Unassigned',session_id='Unassigned',
                           model_used='Unassigned',user_query='Unassigned',response='Unassigned')
    return response

@app.post("/planner-meta-agent/get-query-response")
async def get_planner_meta_agent_response(fastapi_request: Request, request: AgentInferenceRequest):
    """
    Gets the response for a query using agent inference.

    Parameters:
    ----------
    request : AgentInferenceRequest
        The request body containing the query details.

    Returns:
    -------
    dict
        A dictionary containing the response generated by the agent.
    """
    #changed
    user_id = fastapi_request.cookies.get("user_id")
    user_session = fastapi_request.cookies.get("user_session")
    update_session_context(user_session=user_session, user_id=user_id, agent_id=request.agentic_application_id,
                            session_id=request.session_id,
                            model_used=request.model_name,
                            user_query=request.query,
                            response='Processing...')
    current_user_email.set(request.session_id.split("_")[0])
    planner_meta_agent_inference: PlannerMetaAgentInference = get_specialized_inference_service("planner_meta_agent")
    response = await planner_meta_agent_inference.run(request)
    update_session_context(agent_id='Unassigned',session_id='Unassigned',
                           model_used='Unassigned',user_query='Unassigned',response='Unassigned')
    return response


@app.delete("/react-agent/clear-chat-history")
@app.delete("/clear-chat-history")
async def clear_chat_history(fastapi_request: Request, request: PrevSessionRequest, chat_service: ChatService = Depends(get_chat_service)):
    #changed
    user_id = fastapi_request.cookies.get("user_id")
    user_session = fastapi_request.cookies.get("user_session")
    update_session_context(user_session=user_session, user_id=user_id)
    
    return await chat_service.delete_session(
        agentic_application_id=request.agent_id,
        session_id=request.session_id
    )

@app.get("/react-agent/get-chat-sessions")
async def get_chat_sessions(fastapi_request: Request, chat_service: ChatService = Depends(get_chat_service)):
    """
    Retrieves all tools from the tool table.

    Returns:
    -------
    list
        A list of all thread ids. If not found, raises an HTTPException with status code 404.
    """
    user_id = fastapi_request.cookies.get("user_id")
    user_session = fastapi_request.cookies.get("user_session")
    update_session_context(user_session=user_session, user_id=user_id)

    sessions = await chat_service.get_all_sessions()

    if not sessions:
        raise HTTPException(status_code=404, detail="No thread id found")
    return sessions


@app.get("/react-agent/create-new-session")
async def create_new_session(fastapi_request: Request):
    """
    Create a new session id

    Returns:
    -------
    str
        A string containing new session ID. If not found, raises an HTTPException with status code 404.
    """
    #changed
    user_id = fastapi_request.cookies.get("user_id")
    user_session = fastapi_request.cookies.get("user_session")
    import uuid
    session=str(uuid.uuid4())
    if not session:
        raise HTTPException(status_code=404, detail="Some problem occured while creating a new session")
    update_session_context(user_session=user_session, user_id=user_id, session_id=session)
    return session



@app.post("/planner-executor-agent/get-query-response-hitl-replanner")
async def generate_response_replanner_executor_agent_main(fastapi_request: Request, request: AgentInferenceHITLRequest):
    """
    Handles the inference request for the Planner-Executor-Critic-replanner agent.

    Args:
        request (AgentInferenceHITLRequest): The request object containing the query, session ID, and other parameters.

    Returns:
        JSONResponse: A JSON response containing the agent's response and state.

    Raises:
        HTTPException: If an error occurs during processing.
    """
    #changed
    user_id = fastapi_request.cookies.get("user_id")
    user_session = fastapi_request.cookies.get("user_session")
    update_session_context(user_session=user_session, user_id=user_id)

    planner_executor_agent_inference: PlannerExecutorAgentInference = get_specialized_inference_service("planner_executor_agent")

    query = request.query
    response = {}
    try:
        current_user_email.set(request.session_id.split("_")[0])
        response = await planner_executor_agent_inference.run(request, hitl_flag=True)
        final_response = "\n".join(i for i in response["plan"])
        steps = ""
        old_response = "\n".join(i for i in request.prev_response["plan"])
        old_steps = ""
        await insert_into_feedback_table(
        agent_id=request.agentic_application_id.replace("-","_"),
        query=query,
        old_final_response= old_response,
        old_steps=old_steps,
        new_final_response=final_response,
        feedback=request.feedback, 
        new_steps=steps)
    except Exception as e:
        response["error"] = f"An error occurred while processing the response: {str(e)}"
    
    
    return response


@app.post("/planner-executor-critic-agent/get-query-response-hitl-replanner")
async def generate_response_replanner_executor_critic_agent_main(fastapi_request: Request, request: AgentInferenceHITLRequest):
    """
    Handles the inference request for the Planner-Executor-Critic-replanner agent.

    Args:
        request (AgentInferenceHITLRequest): The request object containing the query, session ID, and other parameters.

    Returns:
        JSONResponse: A JSON response containing the agent's response and state.

    Raises:
        HTTPException: If an error occurs during processing.
    """
    #changed
    user_id = fastapi_request.cookies.get("user_id")
    user_session = fastapi_request.cookies.get("user_session")
    update_session_context(user_session=user_session, user_id=user_id)

    multi_agent_inference: MultiAgentInference = get_specialized_inference_service("multi_agent")

    query = request.query
    response = {}
    try:
        current_user_email.set(request.session_id.split("_")[0])
        response = await multi_agent_inference.run(request, hitl_flag=True)
        final_response = "\n".join(i for i in response["plan"])
        steps = ""
        old_response = "\n".join(i for i in request.prev_response["plan"])
        old_steps = ""
        await insert_into_feedback_table(
        agent_id=request.agentic_application_id.replace("-","_"),
        query=query,
        old_final_response= old_response,
        old_steps=old_steps,
        new_final_response=final_response,
        feedback=request.feedback, 
        new_steps=steps)
    except Exception as e:
        response["error"] = f"An error occurred while processing the response: {str(e)}"
    
    
    return response





@app.post("/tags/create-tag")
async def create_tag_endpoint(fastapi_request: Request, tag_data: TagData, tag_service: TagService = Depends(get_tag_service)):
    """
    Inserts data into the tags table.
    """
    #changed
    user_id = fastapi_request.cookies.get("user_id")
    user_session = fastapi_request.cookies.get("user_session")
    update_session_context(user_session=user_session, user_id=user_id)

    result = await tag_service.create_tag(tag_name=tag_data.tag_name, created_by=tag_data.created_by)
    return result

@app.get("/tags/get-available-tags")
async def get_available_tags_endpoint(fastapi_request: Request, tag_service: TagService = Depends(get_tag_service)):
    """
    Retrieves tags from the tags table.
    """
    #changed
    user_id = fastapi_request.cookies.get("user_id")
    user_session = fastapi_request.cookies.get("user_session")
    update_session_context(user_session=user_session, user_id=user_id)

    return await tag_service.get_all_tags()

@app.get("/tags/get-tag/{tag_id}")
async def read_tag_by_id_endpoint(fastapi_request: Request, tag_id: str, tag_service: TagService = Depends(get_tag_service)):
    """
    Retrieves tags from the database based on provided parameters.
    """
    #changed
    user_id = fastapi_request.cookies.get("user_id")
    user_session = fastapi_request.cookies.get("user_session")
    update_session_context(user_session=user_session, user_id=user_id)
    result = await tag_service.get_tag(tag_id=tag_id)
    if not result:
        raise HTTPException(status_code=404, detail="Tag not found")
    return result

@app.put("/tags/update-tag")
async def update_tag_endpoint(fastapi_request: Request, update_data: UpdateTagData, tag_service: TagService = Depends(get_tag_service)):
    """
    Updates the tag name in the tags table if the given tag ID or tag name is present and created by the given user ID.
    """
    #changed
    user_id = fastapi_request.cookies.get("user_id")
    user_session = fastapi_request.cookies.get("user_session")
    update_session_context(user_session=user_session, user_id=user_id)

    result = await tag_service.update_tag(
        new_tag_name=update_data.new_tag_name,
        created_by=update_data.created_by,
        tag_id=update_data.tag_id,
        tag_name=update_data.tag_name
    )
    return result

@app.delete("/tags/delete-tag")
async def delete_tag_endpoint(fastapi_request: Request, delete_data: DeleteTagData, tag_service: TagService = Depends(get_tag_service)):
    """
    Deletes a tag from the tags table if the given tag ID or tag name is present and created by the given user ID.
    """
    #changed
    user_id = fastapi_request.cookies.get("user_id")
    user_session = fastapi_request.cookies.get("user_session")
    update_session_context(user_session=user_session, user_id=user_id)

    result = await tag_service.delete_tag(
        created_by=delete_data.created_by,
        tag_id=delete_data.tag_id,
        tag_name=delete_data.tag_name
    )
    return result

@app.post("/tags/get-tools-by-tag")
async def read_tools_by_tag_endpoint(fastapi_request: Request, tag_data: TagIdName, tool_service: ToolService = Depends(get_tool_service)):
    """
    Retrieves tools associated with a given tag ID or tag name.
    """
    #changed
    user_id = fastapi_request.cookies.get("user_id")
    user_session = fastapi_request.cookies.get("user_session")
    update_session_context(user_session=user_session, user_id=user_id)

    result = await tool_service.get_tools_by_tags(
        tag_ids=tag_data.tag_ids,
        tag_names=tag_data.tag_names
    )
    if not result:
        raise HTTPException(status_code=404, detail="Tools not found")
    return result

@app.post("/tags/get-agents-by-tag")
async def read_agents_by_tag_endpoint(fastapi_request: Request, tag_data: TagIdName, agent_service: AgentService = Depends(get_agent_service)):
    """
    Retrieves agents associated with a given tag ID or tag name.
    """
    #changed
    user_id = fastapi_request.cookies.get("user_id")
    user_session = fastapi_request.cookies.get("user_session")
    update_session_context(user_session=user_session, user_id=user_id)

    result = await agent_service.get_agents_by_tag(
        tag_ids=tag_data.tag_ids,
        tag_names=tag_data.tag_names
    )
    if not result:
        raise HTTPException(status_code=404, detail="Agents not found")
    return result





# Document uploading

# Base directory for uploads
BASE_DIR = "user_uploads"
TRUE_BASE_DIR = os.path.dirname(BASE_DIR)  # This will now point to the folder that contains both `user_uploads` and `evaluation_uploads`
EVALUATION_UPLOAD_DIR = os.path.join(TRUE_BASE_DIR, "evaluation_uploads")

# Function to save uploaded files
def save_uploaded_file(uploaded_file: UploadFile, save_path: str):
    all_files = os.listdir(save_path)

    if uploaded_file.filename in all_files:
        raise HTTPException(status_code=400, detail="File already exists!")

    file_location = os.path.join(save_path, uploaded_file.filename)

    with open(file_location, "wb") as f:
        shutil.copyfileobj(uploaded_file.file, f)
    log.info(f"Saved uploaded file to: {file_location}")
    return file_location

# Function to generate file structure
def generate_file_structure(directory="user_uploads"):
    file_struct = {}
    for root, dirs, files in os.walk(directory):
        path_parts = root.split(os.sep)
        current_level = file_struct
        for part in path_parts:
            if part not in current_level:
                current_level[part] = {}
            current_level = current_level[part]
        if files:
            current_level["__files__"] = files
    log.info("File structure generated successfully")  
    return file_struct

@app.post("/files/user-uploads/upload-file/")
async def upload_file(fastapi_request: Request, file: UploadFile = File(...), subdirectory: str = ""):
    #changed
    user_id = fastapi_request.cookies.get("user_id")
    user_session = fastapi_request.cookies.get("user_session")
    update_session_context(user_session=user_session, user_id=user_id)

    if subdirectory.startswith("/") or subdirectory.startswith("\\"):
        subdirectory = subdirectory[1:]


    if ".." in subdirectory  or ":" in subdirectory:
        raise HTTPException(status_code=400, detail="Invalid Path File")

    save_path = os.path.join(BASE_DIR, subdirectory) if subdirectory else BASE_DIR
    
    # Before creating the directory, check if the save_path is valid and within the allowed directory
    abs_save_path = os.path.abspath(save_path)
    
    # Ensure that the absolute save path is inside the BASE_DIR and prevent directory traversal
    if not abs_save_path.startswith(os.path.abspath(BASE_DIR)):
        raise HTTPException(status_code=400, detail="Invalid Path File")
    
    if not os.path.exists(save_path):
        os.makedirs(save_path)
    file_location = save_uploaded_file(file, abs_save_path)
    if isinstance(file_location, HTTPException):
        raise file_location
    log.info(f"File '{file.filename}' uploaded successfully to '{file_location}'")
    return {"info": f"File '{file.filename}' saved at '{file_location}'"}

@app.get("/files/user-uploads/get-file-structure/")
async def get_file_structure(fastapi_request: Request):
    #changed
    user_id = fastapi_request.cookies.get("user_id")
    user_session = fastapi_request.cookies.get("user_session")
    update_session_context(user_session=user_session, user_id=user_id)

    file_structure = generate_file_structure(BASE_DIR)
    log.info("File structure retrieved successfully")
    return JSONResponse(content=file_structure)

@app.delete("/files/user-uploads/delete-file/")
async def delete_file(fastapi_request: Request, file_path: str):
    #changed
    user_id = fastapi_request.cookies.get("user_id")
    user_session = fastapi_request.cookies.get("user_session")
    update_session_context(user_session=user_session, user_id=user_id)

    full_path = os.path.join(BASE_DIR, file_path)
    if os.path.exists(full_path):
        if os.path.isfile(full_path):
            os.remove(full_path)
            log.info(f"File '{file_path}' deleted successfully.")
            return {"info": f"File '{file_path}' deleted successfully."}
        else:
            log.info(f"Attempted to delete a directory: '{file_path}'")
            raise HTTPException(status_code=400, detail="The specified path is a directory. Only files can be deleted.")
    else:
        log.info(f"File '{file_path}' not found.")
        raise HTTPException(status_code=404, detail="No such file or directory.")




DOCS_ROOT = Path(r"C:\Agentic_foundary_documentation\docs")

def list_markdown_files(directory: Path) -> List[str]:
    """
    Recursively lists all Markdown (.md) files in the given directory and its subdirectories.
    """
    print(f"Looking in directory: {directory.resolve()}")

    if not directory.exists() or not directory.is_dir():
        raise HTTPException(status_code=404, detail=f"Directory not found at {directory.resolve()}")

    files = [str(file.relative_to(DOCS_ROOT)) for file in directory.rglob("*.md")]
    return files

@app.get("/list_markdown_files/")
def list_all_files(fastapi_request: Request):
    """
    Lists all Markdown files in the docs folder (including subfolders).
    """
    #changed
    user_id = fastapi_request.cookies.get("user_id")
    user_session = fastapi_request.cookies.get("user_session")
    update_session_context(user_session=user_session, user_id=user_id)

    try:
        files = list_markdown_files(DOCS_ROOT)
        return {"files": files}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error: {str(e)}")

@app.get("/list_markdown_files/{dir_name}")
def list_files_in_directory(fastapi_request: Request, dir_name: str):
    """
    Lists all Markdown files in a specific subdirectory under the docs folder.
    """
    #changed
    user_id = fastapi_request.cookies.get("user_id")
    user_session = fastapi_request.cookies.get("user_session")
    update_session_context(user_session=user_session, user_id=user_id)
    target_dir = DOCS_ROOT / dir_name
    print(f"Target directory: {target_dir.resolve()}") 
    if not target_dir.exists() or not target_dir.is_dir():
        raise HTTPException(status_code=404, detail=f"Subdirectory '{dir_name}' not found")

    try:
        files = list_markdown_files(target_dir)
        return {"directory": dir_name, "files": files}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error: {str(e)}")




class login_data(BaseModel):
    email_id : str
    password: str
    role: str

class registration_data(BaseModel):
    email_id : str
    password: str
    role: str
    user_name: str


@app.post("/login")
async def login(data: login_data, response: Response):
    update_session_context(user_id=data.email_id)
    log.info(f"Login attempt for user: {data.email_id} with role: {data.role}")
    conn = await asyncpg.connect(
        host=POSTGRESQL_HOST,
        database='login',
        user=POSTGRESQL_USER,
        password=POSTGRESQL_PASSWORD
    )

    try:
        # Fetch user by email using parameterized query
        login_data = await conn.fetchrow(
            "SELECT mail_id, user_name, password, role FROM login_credential WHERE mail_id = $1",
            data.email_id
        )


        if login_data is None:
            log.info(f"Login failed for user: {data.email_id} - User not found")
            return {"approval": False, "message": "User not found"}

        if bcrypt.checkpw(data.password.encode('utf-8'), login_data['password'].encode('utf-8')):
            user_role = login_data['role']
            if user_role == "Admin":
                pass
            elif user_role == "Developer" and data.role == "Admin":
                log.info(f"Login failed for user: {data.email_id} - Unauthorized access attempt as Admin")
                return {"approval": False, "message": "You are not authorized as Admin"}
            elif user_role == "User" and data.role in ("Developer", "Admin"):
                log.info(f"Login failed for user: {data.email_id} - Unauthorized access attempt as {data.role}")
                return {"approval": False, "message": f"You are not authorized as {data.role}"}

            session_id = login_data['mail_id'] + "_" + str(uuid.uuid4()).replace("-", "_")
            user_session = login_data['mail_id'] + "_" + str(uuid.uuid4()).replace("-", "_")
            update_session_context(session_id=session_id, user_session=user_session, user_id=login_data['mail_id'])
            response.set_cookie(key="user_id", value=login_data['mail_id'], httponly=True, max_age=10800)
            response.set_cookie(key="user_session", value=user_session, httponly=True, max_age=10800)
            log.info(f"Login successful for user: {data.email_id} with session ID: {session_id} and role: {data.role}")

            csrf_token = secrets.token_hex(32)

            return {
                "approval": True,
                "session_id": session_id,
                "csrf_token": csrf_token,
                "role": data.role,
                "username": login_data['user_name'],
                "email": login_data['mail_id'],
                "message": "Login successful"
            }
        else:
            log.info(f"Login failed for user: {data.email_id} - Incorrect password")
            return {"approval": False, "message": "Incorrect password"}

    finally:
        await conn.close()

#changed 
@app.post("/logout")
def logout(response: Response):
    response.delete_cookie(key="user_id")
    response.delete_cookie(key="user_session")
    return {"message": "Logged out successfully"}

@app.post("/registration")
async def registration(data: registration_data):
    conn = await asyncpg.connect(
        host=POSTGRESQL_HOST,
        database='login',
        user=POSTGRESQL_USER,
        password=POSTGRESQL_PASSWORD
    )

    log.info(f"Registration attempt for user: {data.email_id} with role: {data.role}")

    try:
        # Check if user already exists
        existing_user = await conn.fetchrow(
            "SELECT * FROM login_credential WHERE mail_id = $1",
            data.email_id
        )

        if existing_user:
            log.info(f"Registration failed for user: {data.email_id} - User already exists")
            return {"approval": False, "message": "User already exists"}

        # Hash the password
        hashed_password = bcrypt.hashpw(data.password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')

        # Insert new user
        await conn.execute(
            '''
            INSERT INTO login_credential (mail_id, user_name, password, role)
            VALUES ($1, $2, $3, $4)
            ''',
            data.email_id, data.user_name, hashed_password, data.role
        )

        user_id = str(uuid.uuid4())
        log.info(f"Registration successful for user: {data.user_name} with email: {data.email_id} and role: {data.role}")
        return {"approval": True, "message": f"{data.user_name} registered successfully"}

    except Exception as e:
        log.error(f"Registration failed for user: {data.user_name} with email: {data.email_id} - Error occurred during registration")
        return {"approval": False, "message": "Registration failed due to an error"}

    finally:
        await conn.close()

@app.post("/update-password-role")
# Assuming you are using asyncpg for database interaction
async def update_user_password(fastapi_request: Request, email_id, new_password=None,role=None):
    """
    Updates the password for a user in the login_credential table.

    Args:
        conn: An active database connection object (e.g., from asyncpg.connect).
        email_id (str): The email ID of the user whose password needs to be updated.
        new_password (str): The new password for the user.
    Returns:
        dict: A dictionary indicating approval and a message.
    """
    user_id = fastapi_request.cookies.get("user_id")
    user_session = fastapi_request.cookies.get("user_session")
    update_session_context(user_session=user_session, user_id=user_id)

    conn = await asyncpg.connect(
        host=POSTGRESQL_HOST,
        database='login',
        user=POSTGRESQL_USER,
        password=POSTGRESQL_PASSWORD
    )
    try:
        # Check if the user exists
        existing_user = await conn.fetchrow(
            "SELECT * FROM login_credential WHERE mail_id = $1",
            email_id
        )

        if not existing_user:
            # log.info(f"Password update failed for user: {email_id} - User not found")
            return {"approval": False, "message": "User not found"}

        # Hash the new password
        if new_password is not None and role is None:
            hashed_new_password = bcrypt.hashpw(new_password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')

            # Update the password in the database
            await conn.execute(
                """
                UPDATE login_credential
                SET password = $1
                WHERE mail_id = $2
                """,
                hashed_new_password,
                email_id
            )

            # log.info(f"Password updated successfully for user: {email_id}")
            return {"approval": True, "message": "Password updated successfully"}
        elif role is not None and new_password is None:
            # Update the role in the database
            await conn.execute(
                """
                UPDATE login_credential
                SET role = $1
                WHERE mail_id = $2
                """,
                role,
                email_id
            )

            # log.info(f"Role updated successfully for user: {email_id}")
            return {"approval": True, "message": "Role updated successfully"}
        elif role is not None and new_password is not None:
            # Hash the new password
            hashed_new_password = bcrypt.hashpw(new_password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')

            # Update both password and role in the database
            await conn.execute(
                """
                UPDATE login_credential
                SET password = $1, role = $2
                WHERE mail_id = $3
                """,
                hashed_new_password,
                role,
                email_id
            )

            # log.info(f"Password and role updated successfully for user: {email_id}")
            return {"approval": True, "message": "Password and Role updated successfully"}

    except Exception as e:
        # log.error(f"Error updating password for user {email_id}: {e}")
        return {"approval": False, "message": f"An error occurred: {e}"}


@app.get("/login_guest")
async def login_guest(response: Response):
    update_session_context(user_id="Guest", session_id="test_101")
    user_session = "Guest" + "_" + str(uuid.uuid4()).replace("-", "_")
    update_session_context(session_id="test_101", user_session=user_session, user_id="Guest")
    response.set_cookie(key="user_id", value="Guest", httponly=True, max_age=10800)
    response.set_cookie(key="user_session", value=user_session, httponly=True, max_age=10800)
    log.info("Guest login successful")
    return {"approval": True, "email": "test", "session_id":"test_101", "user_name":"Guest", "message": "Guest Login Successful"}


class old_session_request(BaseModel):
    user_email: str
    agent_id: str

@app.post("/old-chats")
async def get_old_chats(fastapi_request: Request, request: old_session_request):
    #changed
    user_id = fastapi_request.cookies.get("user_id")
    user_session = fastapi_request.cookies.get("user_session")
    update_session_context(user_session=user_session, user_id=user_id)

    user_email = request.user_email
    agent_id = request.agent_id
    table_name = f'table_{agent_id.replace("-", "_")}'

    conn = await asyncpg.connect(
        host=POSTGRESQL_HOST,
        database=DATABASE,
        user=POSTGRESQL_USER,
        password=POSTGRESQL_PASSWORD
    )

    try:
        # Use parameterized query, but table name cannot be parameterized,
        # so make sure table_name is safe before usage.
        query = f"SELECT * FROM {table_name} WHERE session_id LIKE $1;"
        rows = await conn.fetch(query, f"{user_email}_%")
    except asyncpg.PostgresError:
        log.error(f"Error retrieving old chats for user: {user_email} and agent ID: {agent_id}")
        await conn.close()
        return JSONResponse(content={"detail": "no old chats found"}, status_code=404)
    finally:
        await conn.close()

    result = {}
    for row in rows:
        test_number = row[0]
        timestamp_start = row[1]
        timestamp_end = row[2]
        user_input = row[3]
        agent_response = row[4]

        if test_number not in result:
            result[test_number] = []

        result[test_number].append({
            "timestamp_start": timestamp_start,
            "timestamp_end": timestamp_end,
            "user_input": user_input,
            "agent_response": agent_response
        })
    log.info(f"Retrieved old chats for user: {user_email} and agent ID: {agent_id}")
    return JSONResponse(content=jsonable_encoder(result))

@app.get("/new_chat/{email}")
async def new_chat(fastapi_request: Request, email:str):
    import uuid

    id = str(uuid.uuid4()).replace("-","_")
    session_id = email + "_" + id
    #changed
    user_id = fastapi_request.cookies.get("user_id")
    user_session = fastapi_request.cookies.get("user_session")
    
    update_session_context(user_session=user_session, user_id=user_id, session_id=session_id) 
    log.info(f"New chat session created for user: {email} with session ID: {session_id}")
    return session_id

@app.get('/download')
async def download(fastapi_request: Request, filename: str = Query(...), sub_dir_name: str = Query(None)):
    #changed
    user_id = fastapi_request.cookies.get("user_id")
    user_session = fastapi_request.cookies.get("user_session")
    update_session_context(user_session=user_session, user_id=user_id)

    base_path = Path("user_uploads")

    # Compose the path safely
    if sub_dir_name:
        file_path = base_path / sub_dir_name / filename
    else:
        file_path = base_path / filename

    log.info(f"Download request for file: {file_path}")

    if file_path.exists() and file_path.is_file():
        return FileResponse(file_path, media_type='application/octet-stream', filename=filename)
    else:
        return {"error": f"File not found: {file_path}"}

# @router.receive(AgentInferenceRequest)
# async def websocket_endpoint(fastapi_request: Request, websocket: WebSocket, request: AgentInferenceRequest):
#     #changed
#     user_id = fastapi_request.cookies.get("user_id")
#     user_session = fastapi_request.cookies.get("user_session")
#     update_session_context(user_session=user_session, user_id=user_id)

#     try:
#         current_user_email.set(request.session_id.split("_")[0])
#         await agent_inference(request, websocket)
#     except Exception as e:
#         return f"Exception is {e}"


app.include_router(router, prefix="/ws")

@app.get("/get-tools-by-pages/{page}")
async def get_tools_by_pages_endpoint(fastapi_request: Request, 
    page: int = 1,
    limit : int = Query(20, ge=1),
    tool_service: ToolService = Depends(get_tool_service)
):
    """
    Retrieves tools from the database with pagination.

    Parameters:
    ----------
    page : int
        The page number to retrieve (default is 1).
    page_size : int
        The number of items per page (default is 10).

    Returns:
    -------
    list
        A list of tools for the specified page.
    """
    #changed
    user_id = fastapi_request.cookies.get("user_id")
    user_session = fastapi_request.cookies.get("user_session")
    update_session_context(user_session=user_session, user_id=user_id)

    tools = await tool_service.get_tools_by_search_or_page(page=page, limit=limit)
    if not tools:
        raise HTTPException(status_code=404, detail="No tools found")
    return tools


@app.get("/get-agents-by-pages/{page}")
async def get_agents_by_pages_endpoint(fastapi_request: Request, page: int = 1, user_email: str= None, agent_type: str = None, limit: int = 10, agent_service: AgentService = Depends(get_agent_service)):
    """
    Retrieves agents from the database with pagination.

    Parameters:
    ----------
    Pagination : Pagination
        The request body containing pagination details.

    Returns:
    -------
    list
        A list of agents for the specified page.
    """
    #changed
    user_id = fastapi_request.cookies.get("user_id")
    user_session = fastapi_request.cookies.get("user_session")
    update_session_context(user_session=user_session, user_id=user_id)

    agents = await agent_service.get_agents_by_search_or_page(page=page, limit=limit, created_by=user_email, agentic_application_type=agent_type)
    if not agents:
        raise HTTPException(status_code=404, detail="No agents found")
    return agents

@app.get("/get-tools-by-search/{tool_name}")
async def get_tools_by_search(fastapi_request: Request, tool_name: str, tool_service: ToolService = Depends(get_tool_service)):
    """
    Retrieves tools from the tool table in PostgreSQL.

    Args:
        tool_name (str): The name of the tool to search for.

    Returns:
        list: A list of tools from the tool table, represented as dictionaries.
    """
    #changed
    user_id = fastapi_request.cookies.get("user_id")
    user_session = fastapi_request.cookies.get("user_session")
    update_session_context(user_session=user_session, user_id=user_id)

    results = await tool_service.get_tools_by_search_or_page(search_value=tool_name, limit=1_000_000_000, page=1)
    log.info(f"Retrieved {len(results['details'])} tools matching search term {tool_name}")
    return results["details"]


@app.get("/get-agents-by-search/{agent_name}")
async def get_agents_by_search(fastapi_request: Request, agent_name: str = None, agentic_application_type=None, agent_service: AgentService = Depends(get_agent_service)):
    """
    Retrieves agents from the agent table in PostgreSQL.

    Args:
        agent_name (str): The name of the agent to search for.

    Returns:
        list: A list of agents from the agent table, represented as dictionaries.
    """
    #changed
    user_id = fastapi_request.cookies.get("user_id")
    user_session = fastapi_request.cookies.get("user_session")
    update_session_context(user_session=user_session, user_id=user_id)

    results = await agent_service.get_agents_by_search_or_page(search_value=agent_name, limit=1_000_000_000, page=1, agentic_application_type=agentic_application_type)
    log.info(f"Retrieved {len(results['details'])} agents matching search term {agent_name}")
    return results["details"]


@app.post("/get-tools-by-list")
async def get_tools_by_list(fastapi_request: Request, tool_ids: list[str], tool_service: ToolService = Depends(get_tool_service)):
    #changed
    user_id = fastapi_request.cookies.get("user_id")
    user_session = fastapi_request.cookies.get("user_session")
    update_session_context(user_session=user_session, user_id=user_id)
    tools = []
    for tool_id in tool_ids:
        tool = await tool_service.get_tool(tool_id=tool_id)
        if tool:
            tools.append(tool[0])
    return tools

@app.post("/get-agents-by-list")
async def get_agents_by_list(fastapi_request: Request, agent_ids: list[str], agent_service: AgentService = Depends(get_agent_service)):
    #changed
    user_id = fastapi_request.cookies.get("user_id")
    user_session = fastapi_request.cookies.get("user_session")
    update_session_context(user_session=user_session, user_id=user_id)
    agents = []
    for agent_id in agent_ids:
        agent = await agent_service.get_agent(agentic_application_id=agent_id)
        if agent:
            agents.append(agent[0])
    return agents

@app.get("/get-tools-search-paginated/")
async def get_tools_by_search_paginated(fastapi_request: Request, search_value: str = None, page_number: int = 1, page_size: int = 10, tool_service: ToolService = Depends(get_tool_service)):
    """
    Fetches tools from the database with pagination, filtering by tool_name.

    Args:
        tool_name (str): The name or partial name of the tool to search for.
        page_number (int): The current page number (1-indexed). Defaults to 1.
        page_size (int): The number of results per page. Defaults to 10.
        connection: An existing database connection object (e.g., from asyncpg.create_pool).

    Returns:
        list[dict]: A list of dictionaries, where each dictionary represents a tool.
    """
    #changed
    user_id = fastapi_request.cookies.get("user_id")
    user_session = fastapi_request.cookies.get("user_session")
    update_session_context(user_session=user_session, user_id=user_id)
    results = await tool_service.get_tools_by_search_or_page(search_value=search_value, page=page_number, limit=page_size)
    return results['details']

@app.get("/get-agents-search-paginated/")
async def get_agents_by_search_paginated(fastapi_request: Request, 
    agentic_application_type=None,
    search_value: str = None,
    page_number: int = 1,
    page_size: int = 10,
    agent_service: AgentService = Depends(get_agent_service)
):
    """
    Fetches agents from the database with pagination, filtering by agentic_application_type
    or searching by agent_name.

    Args:
        agentic_application_type (Union[str, list[str], None]): The type(s) of agentic applications to filter by.
                                                                 If None, searches by agent_name.
        agent_table_name (str): The name of the table containing agent data.
        agent_name (str, optional): The name or partial name of the agent to search for.
                                    Used if agentic_application_type is None.
        page_number (int): The current page number (1-indexed). Defaults to 1.
        page_size (int): The number of results per page. Defaults to 10.

    Returns:
        list[dict]: A list of dictionaries, where each dictionary represents an agent.
    """
    #changed
    user_id = fastapi_request.cookies.get("user_id")
    user_session = fastapi_request.cookies.get("user_session")
    update_session_context(user_session=user_session, user_id=user_id)

    results = await agent_service.get_agents_by_search_or_page(
        search_value=search_value,
        limit=page_size,
        page=page_number,
        agentic_application_type=agentic_application_type
    )
    return results["details"]


@app.get("/get-agents-details-for-chat")
async def get_agents_details(fastapi_request: Request, agent_service: AgentService = Depends(get_agent_service)):
    """
    Retrieves detailed information about agents for chat purposes.
    Returns:
    -------
    list
        A list of dictionaries containing agent details.
        If no agents are found, raises an HTTPException with status code 404.
    """
    #changed
    user_id = fastapi_request.cookies.get("user_id")
    user_session = fastapi_request.cookies.get("user_session")
    update_session_context(user_session=user_session, user_id=user_id)
    agent_details = await agent_service.get_agents_details_for_chat()
    return agent_details


@app.post("/secrets/create")
async def create_user_secret(fastapi_request: Request, request: SecretCreateRequest):
    """
    Create or update a user secret.
    
    Args:
        request (SecretCreateRequest): The request containing user email, secret name, and value.
    
    Returns:
        dict: Success or error response.
    
    Raises:
        HTTPException: If secret creation fails.
    """
    #changed
    user_id = fastapi_request.cookies.get("user_id")
    user_session = fastapi_request.cookies.get("user_session")
    update_session_context(user_session=user_session, user_id=user_id)
    try:
        # Set the user context
        current_user_email.set(request.user_email)
        
        # Initialize secrets manager
        secrets_manager = setup_secrets_manager()
        
        # Store the secret
        success = secrets_manager.create_user_secret(
            user_email=request.user_email,
            secret_name=request.secret_name,
            secret_value=request.secret_value
        )
        
        if success:
            log.info(f"Secret '{request.secret_name}' created/updated successfully for user: {request.user_email}")
            return {
                "success": True,
                "message": f"Secret '{request.secret_name}' created/updated successfully",
                "user_email": request.user_email,
                "secret_name": request.secret_name
            }
        else:
            log.error(f"Failed to create/update secret '{request.secret_name}' for user: {request.user_email}")
            raise HTTPException(
                status_code=500,
                detail=f"Failed to create/update secret '{request.secret_name}'"
            )
            
    except Exception as e:
        log.error(f"Error creating secret for user {request.user_email}: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"Internal server error: {str(e)}"
        )

@app.post("/secrets/public/create")
async def create_public_secret(fastapi_request: Request, request: PublicSecretCreateRequest):
    """
    Create or update a public secret.
    
    Args:
        request (PublicSecretCreateRequest): The request containing secret name and value.
    
    Returns:
        dict: Success or error response.
    
    Raises:
        HTTPException: If public secret creation fails.
    """
    #changed
    user_id = fastapi_request.cookies.get("user_id")
    user_session = fastapi_request.cookies.get("user_session")
    update_session_context(user_session=user_session, user_id=user_id)
    try:
        create_public_key(
            key_name=request.secret_name,
            key_value=request.secret_value
        )
        log.info(f"Public key '{request.secret_name}' created/updated successfully")
        return {
            "success": True,
            "message": f"Public key '{request.secret_name}' created/updated successfully"
        }
    except Exception as e:
        log.error(f"Error creating public key '{request.secret_name}': {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"Internal server error: {str(e)}"
        )

@app.post("/secrets/get")
async def get_user_secret(fastapi_request: Request, request: SecretGetRequest):
    """
    Retrieve user secrets by name or get all secrets.
    
    Args:
        request (SecretGetRequest): The request containing user email and optional secret names.
    
    Returns:
        dict: The requested secrets or all secrets for the user.
    
    Raises:
        HTTPException: If secret retrieval fails or secrets not found.
    """
    #changed
    user_id = fastapi_request.cookies.get("user_id")
    user_session = fastapi_request.cookies.get("user_session")
    update_session_context(user_session=user_session, user_id=user_id)
    try:
        # Set the user context
        current_user_email.set(request.user_email)
        
        # Initialize secrets manager
        secrets_manager = setup_secrets_manager()
        
        if request.secret_name:
            # Get a specific secret
            secret_value = secrets_manager.get_user_secret(
                user_email=request.user_email,
                secret_name=request.secret_name
            )
            
            if secret_value is not None:
                log.info(f"Secret '{request.secret_name}' retrieved successfully for user: {request.user_email}")
                return {
                    "success": True,
                    "user_email": request.user_email,
                    "secret_name": request.secret_name,
                    "secret_value": secret_value
                }
            else:
                log.warning(f"Secret '{request.secret_name}' not found for user: {request.user_email}")
                raise HTTPException(
                    status_code=404,
                    detail=f"Secret '{request.secret_name}' not found for user"
                )
                
        elif request.secret_names:
            # Get multiple specific secrets
            secrets_dict = secrets_manager.get_user_secrets(
                user_email=request.user_email,
                secret_names=request.secret_names
            )
            
            log.info(f"Multiple secrets retrieved successfully for user: {request.user_email}")
            return {
                "success": True,
                "user_email": request.user_email,
                "secrets": secrets_dict
            }
            
        else:
            # Get all secrets for the user
            secrets_dict = secrets_manager.get_user_secrets(
                user_email=request.user_email
            )
            
            log.info(f"All secrets retrieved successfully for user: {request.user_email}")
            return {
                "success": True,
                "user_email": request.user_email,
                "secrets": secrets_dict
            }
            
    except HTTPException:
        raise
    except Exception as e:
        log.error(f"Error retrieving secrets for user {request.user_email}: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"Internal server error: {str(e)}"
        )

@app.post("/secrets/public/get")
async def get_public_secret(fastapi_request: Request, request: PublicSecretGetRequest):
    """
    Retrieve a public secret by name.
    
    Args:
        request (PublicSecretGetRequest): The request containing the secret name.
    
    Returns:
        dict: The requested public secret value.
    
    Raises:
        HTTPException: If public secret retrieval fails or not found.
    """
    #changed
    user_id = fastapi_request.cookies.get("user_id")
    user_session = fastapi_request.cookies.get("user_session")
    update_session_context(user_session=user_session, user_id=user_id)
    try:
        # Get the public key
        public_key_value = get_public_key(request.secret_name)
        
        if public_key_value is not None:
            log.info(f"Public key '{request.secret_name}' retrieved successfully")
            return {
                "success": True,
                "key_name": request.secret_name,
                "key_value": public_key_value
            }
        else:
            log.warning(f"Public key '{request.secret_name}' not found")
            raise HTTPException(
                status_code=404,
                detail=f"Public key '{request.secret_name}' not found"
            )
            
    except Exception as e:
        log.error(f"Error retrieving public key '{request.secret_name}': {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"Internal server error: {str(e)}"
        )

@app.put("/secrets/update")
async def update_user_secret(fastapi_request: Request, request: SecretUpdateRequest):
    """
    Update an existing user secret.
    
    Args:
        request (SecretUpdateRequest): The request containing user email, secret name, and new value.
    
    Returns:
        dict: Success or error response.
    
    Raises:
        HTTPException: If secret update fails or secret doesn't exist.
    """
    #changed
    user_id = fastapi_request.cookies.get("user_id")
    user_session = fastapi_request.cookies.get("user_session")
    update_session_context(user_session=user_session, user_id=user_id)
    try:
        # Set the user context
        current_user_email.set(request.user_email)
        
        # Initialize secrets manager
        secrets_manager = setup_secrets_manager()
        
        # Check if secret exists first
        existing_secret = secrets_manager.get_user_secret(
            user_email=request.user_email,
            secret_name=request.secret_name
        )
        
        if existing_secret is None:
            log.warning(f"Secret '{request.secret_name}' not found for user: {request.user_email}")
            raise HTTPException(
                status_code=404,
                detail=f"Secret '{request.secret_name}' not found for user"
            )
        
        # Update the secret
        success = secrets_manager.update_user_secret(
            user_email=request.user_email,
            secret_name=request.secret_name,
            secret_value=request.secret_value
        )
        
        if success:
            log.info(f"Secret '{request.secret_name}' updated successfully for user: {request.user_email}")
            return {
                "success": True,
                "message": f"Secret '{request.secret_name}' updated successfully",
                "user_email": request.user_email,
                "secret_name": request.secret_name
            }
        else:
            log.error(f"Failed to update secret '{request.secret_name}' for user: {request.user_email}")
            raise HTTPException(
                status_code=500,
                detail=f"Failed to update secret '{request.secret_name}'"
            )
            
    except HTTPException:
        raise
    except Exception as e:
        log.error(f"Error updating secret for user {request.user_email}: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"Internal server error: {str(e)}"
        )

@app.put("/secrets/public/update")
async def update_public_secret(fastapi_request: Request, request: PublicSecretUpdateRequest):
    """
    Update an existing public secret.
    
    Args:
        request (PublicSecretUpdateRequest): The request containing secret name and new value.
    
    Returns:
        dict: Success or error response.
    
    Raises:
        HTTPException: If public secret update fails or secret doesn't exist.
    """
    #changed
    user_id = fastapi_request.cookies.get("user_id")
    user_session = fastapi_request.cookies.get("user_session")
    update_session_context(user_session=user_session, user_id=user_id)
    try:
        # Update the public key
        success = update_public_key(
            key_name=request.secret_name,
            key_value=request.secret_value
        )
        
        if success:
            log.info(f"Public key '{request.secret_name}' updated successfully")
            return {
                "success": True,
                "message": f"Public key '{request.secret_name}' updated successfully"
            }
        else:
            log.error(f"Failed to update public key '{request.secret_name}'")
            raise HTTPException(
                status_code=500,
                detail=f"Failed to update public key '{request.secret_name}'"
            )
            
    except Exception as e:
        log.error(f"Error updating public key '{request.secret_name}': {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"Internal server error: {str(e)}"
        )

@app.delete("/secrets/delete")
async def delete_user_secret_endpoint(fastapi_request: Request, request: SecretDeleteRequest):
    """
    Delete a user secret.
    
    Args:
        request (SecretDeleteRequest): The request containing user email and secret name.
    
    Returns:
        dict: Success or error response.
    
    Raises:
        HTTPException: If secret deletion fails or secret doesn't exist.
    """
    #changed
    user_id = fastapi_request.cookies.get("user_id")
    user_session = fastapi_request.cookies.get("user_session")
    update_session_context(user_session=user_session, user_id=user_id)

    try:
        # Set the user context
        current_user_email.set(request.user_email)
        
        # Initialize secrets manager
        secrets_manager = setup_secrets_manager()
        
        # Delete the secret
        success = secrets_manager.delete_user_secret(
            user_email=request.user_email,
            secret_name=request.secret_name
        )
        
        if success:
            log.info(f"Secret '{request.secret_name}' deleted successfully for user: {request.user_email}")
            return {
                "success": True,
                "message": f"Secret '{request.secret_name}' deleted successfully",
                "user_email": request.user_email,
                "secret_name": request.secret_name
            }
        else:
            log.warning(f"Secret '{request.secret_name}' not found for deletion for user: {request.user_email}")
            raise HTTPException(
                status_code=404,
                detail=f"Secret '{request.secret_name}' not found for user"
            )
            
    except HTTPException:
        raise
    except Exception as e:
        log.error(f"Error deleting secret for user {request.user_email}: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"Internal server error: {str(e)}"
        )

@app.delete("/secrets/public/delete")
async def delete_public_secret_endpoint(fastapi_request: Request, request: PublicSecretDeleteRequest):
    """
    Delete a public secret.

    Args:
        request (PublicSecretDeleteRequest): The request containing secret name.

    Returns:
        dict: Success or error response.

    Raises:
        HTTPException: If public secret deletion fails or secret doesn't exist.
    """
    #changed
    user_id = fastapi_request.cookies.get("user_id")
    user_session = fastapi_request.cookies.get("user_session")
    update_session_context(user_session=user_session, user_id=user_id)
    try:
        # Delete the public key
        success = delete_public_key(
            key_name=request.secret_name
        )

        if success:
            log.info(f"Public key '{request.secret_name}' deleted successfully")
            return {
                "success": True,
                "message": f"Public key '{request.secret_name}' deleted successfully"
            }
        else:
            log.error(f"Failed to delete public key '{request.secret_name}'")
            raise HTTPException(
                status_code=500,
                detail=f"Failed to delete public key '{request.secret_name}'"
            )

    except Exception as e:
        log.error(f"Error deleting public key '{request.secret_name}': {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"Internal server error: {str(e)}"
        )

@app.post("/secrets/list")
async def list_user_secrets_endpoint(fastapi_request: Request, request: SecretListRequest):
    """
    List all secret names for a user (without values).
    
    Args:
        request (SecretListRequest): The request containing user email.
    
    Returns:
        dict: List of secret names or error response.
    
    Raises:
        HTTPException: If listing secrets fails.
    """
    #changed
    user_id = fastapi_request.cookies.get("user_id")
    user_session = fastapi_request.cookies.get("user_session")
    update_session_context(user_session=user_session, user_id=user_id)
    try:
        # Set the user context
        current_user_email.set(request.user_email)
        
        # Initialize secrets manager
        secrets_manager = setup_secrets_manager()
        
        # Get list of secret names
        secret_names = secrets_manager.list_user_secret_names(
            user_email=request.user_email
        )
        
        log.info(f"Secret names listed successfully for user: {request.user_email}")
        return {
            "success": True,
            "user_email": request.user_email,
            "secret_names": secret_names,
            "count": len(secret_names)
        }
        
    except Exception as e:
        log.error(f"Error listing secrets for user {request.user_email}: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"Internal server error: {str(e)}"
        )

@app.post("/secrets/public/list")
async def list_public_secrets_endpoint(fastapi_request: Request):
    """
    List all public secret names (without values).
    
    Returns:
        dict: List of public secret names or error response.
    
    Raises:
        HTTPException: If listing public secrets fails.
    """
    #changed
    user_id = fastapi_request.cookies.get("user_id")
    user_session = fastapi_request.cookies.get("user_session")
    update_session_context(user_session=user_session, user_id=user_id)
    try:
        # Get list of public key names
        public_key_names = list_public_keys()
        
        log.info("Public key names listed successfully")
        return {
            "success": True,
            "public_key_names": public_key_names,
            "count": len(public_key_names)
        }
        
    except Exception as e:
        log.error(f"Error listing public keys: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"Internal server error: {str(e)}"
        )

# Health check endpoint for secrets functionality
@app.get("/secrets/health")
async def secrets_health_check(fastapi_request: Request):
    """
    Health check endpoint for secrets management functionality.
    
    Returns:
        dict: Health status of the secrets management system.
    """
    #changed
    user_id = fastapi_request.cookies.get("user_id")
    user_session = fastapi_request.cookies.get("user_session")
    update_session_context(user_session=user_session, user_id=user_id)
    try:
        # Try to initialize secrets manager
        secrets_manager = setup_secrets_manager()
        
        return {
            "success": True,
            "message": "Secrets management system is healthy",
            "timestamp": str(asyncio.get_event_loop().time())
        }
        
    except Exception as e:
        log.error(f"Secrets health check failed: {str(e)}")
        raise HTTPException(
            status_code=503,
            detail=f"Secrets management system is unhealthy: {str(e)}"
        )


@app.get("/recycle-bin/{param}")
async def restore_tools(fastapi_request: Request, param:Literal["tools", "agents"], user_email_id: str):
    """
    Restores tools from the recycle bin.

    Returns:
    -------
    list
        A list of restored tools. If no tools are found, raises an HTTPException with status code 404.
    """
    #changed
    user_id = fastapi_request.cookies.get("user_id")
    user_session = fastapi_request.cookies.get("user_session")
    update_session_context(user_session=user_session, user_id=user_id)
    connection_login = await asyncpg.connect(
        host=POSTGRESQL_HOST,
        database="login",
        user=POSTGRESQL_USER,
        password=POSTGRESQL_PASSWORD
    )

    # Check if the user's role is admin or not in the login database
    query = "SELECT role FROM login_credential WHERE mail_id = $1;"

    user_role = await connection_login.fetchval(query, user_email_id)
    if user_role.lower() != "admin":
        return HTTPException(status_code=403, detail="You are not authorized to access this resource")

    connection_recycle = await asyncpg.connect(
        host=POSTGRESQL_HOST,
        database="recycle",
        user=POSTGRESQL_USER,
        password=POSTGRESQL_PASSWORD
    )

    try:
        if param == "tools":
            # Fetch all tools from the recycle bin
            query = "SELECT * FROM recycle_tool;"
        elif param == "agents":
            # Fetch all agents from the recycle bin
            query = "SELECT * FROM recycle_agent;"
        else:
            return HTTPException(status_code=400, detail="Invalid parameter. Use 'tools' or 'agents'.")
        rows = await connection_recycle.fetch(query)
        restored_tools = [dict(row) for row in rows]
        if not restored_tools:
            return HTTPException(status_code=404, detail=f"No {param} found in recycle bin")
        return restored_tools
    except asyncpg.PostgresError as e:
        log.error(f"Error retrieving {param} from recycle bin: {e}")
        return HTTPException(status_code=500, detail="Internal server error")
    finally:
        await connection_recycle.close()


@app.post("/restore/{param}")
async def restore(fastapi_request: Request, param: Literal["tools", "agents"], item_id: str, user_email_id: str, agent_service: AgentService = Depends(get_agent_service)):
    """
    Restores a tool or agent from the recycle bin.

    Parameters:
    ----------
    param : Literal["tools", "agents"]
        The type of item to restore, either "tools" or "agents".
    item_id : str
        The ID of the tool or agent to restore.

    Returns:
    -------
    dict
        A dictionary containing the restored item details.
        If the item is not found, raises an HTTPException with status code 404.
    """
    #changed
    user_id = fastapi_request.cookies.get("user_id")
    user_session = fastapi_request.cookies.get("user_session")
    update_session_context(user_session=user_session, user_id=user_id)
    connection_login = await asyncpg.connect(
        host=POSTGRESQL_HOST,
        database="login",
        user=POSTGRESQL_USER,
        password=POSTGRESQL_PASSWORD
    )

    # Check if the user's role is admin or not in the login database
    query = "SELECT role FROM login_credential WHERE mail_id = $1;"

    user_role = await connection_login.fetchval(query, user_email_id)
    if user_role.lower() != "admin":
        return HTTPException(status_code=403, detail="You are not authorized to access this resource")
    if param == "tools":
        return await agent_service.tool_service.restore_tool(tool_id=item_id)
    elif param == "agents":
        return await agent_service.restore_agent(agentic_application_id=item_id)
    else:
        raise HTTPException(status_code=400, detail="Invalid parameter. Use 'tools' or 'agents'.")
    
@app.delete("/delete/{param}")
async def delete(fastapi_request: Request, param: Literal["tools", "agents"], item_id: str, user_email_id: str, agent_service: AgentService = Depends(get_agent_service)):
    """
    Deletes a tool or agent permanently from the recycle bin.

    Parameters:
    ----------
    param : Literal["tools", "agents"]
        The type of item to delete, either "tools" or "agents".
    item_id : str
        The ID of the tool or agent to delete.

    Returns:
    -------
    dict
        A dictionary containing the deleted item details.
        If the item is not found, raises an HTTPException with status code 404.
    """
    #changed
    user_id = fastapi_request.cookies.get("user_id")
    user_session = fastapi_request.cookies.get("user_session")
    update_session_context(user_session=user_session, user_id=user_id)
    connection_login = await asyncpg.connect(
        host=POSTGRESQL_HOST,
        database="login",
        user=POSTGRESQL_USER,
        password=POSTGRESQL_PASSWORD
    )

    # Check if the user's role is admin or not in the login database
    query = "SELECT role FROM login_credential WHERE mail_id = $1;"

    user_role = await connection_login.fetchval(query, user_email_id)
    if user_role.lower() != "admin":
        return HTTPException(status_code=403, detail="You are not authorized to access this resource")
    if param == "tools":
        return await agent_service.tool_service.delete_tool_from_recycle_bin(tool_id=item_id)
    elif param == "agents":
        return await agent_service.delete_agent_from_recycle_bin(agentic_application_id=item_id)
    else:
        raise HTTPException(status_code=400, detail="Invalid parameter. Use 'tools' or 'agents'.")


@app.get("/export-agents")
async def download_multipleagent_export(fastapi_request: Request,
    agent_ids: List[str] = Query(..., description="List of agent IDs to export"),
    user_email: Optional[str] = Query(None, description="Email of the user requesting the export"),
    background_tasks: BackgroundTasks = BackgroundTasks()
):
    """
    Downloads a zip archive of the specified agent's data and associated files.
    """
    #changed
    user_id = fastapi_request.cookies.get("user_id")
    user_session = fastapi_request.cookies.get("user_session")
    update_session_context(user_session=user_session, user_id=user_id)
    try:
        zip_file_path = await export_agent_by_id(agent_ids,user_email)

        if not os.path.exists(zip_file_path):
            raise HTTPException(status_code=500, detail="Generated zip file not found.")
        filename = os.path.basename(zip_file_path)
        media_type = "application/zip"
        async def cleanup_files():
            temp_base_dir = "temp_agent_exports"
            temp_working_dir = os.path.join(temp_base_dir, f"export")
            try:
                if os.path.exists(zip_file_path):
                    os.remove(zip_file_path)
                if os.path.exists(temp_working_dir):
                    shutil.rmtree(temp_working_dir)
            except Exception as e:
                pass
        background_tasks.add_task(cleanup_files)
        return FileResponse(
            path=zip_file_path,
            media_type=media_type,
            filename=filename
        )

    except HTTPException as he:
        raise he
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"An unexpected error occurred: {str(e)}")
           
async def export_agent_by_id(agent_ids: List[str],user_email:str) -> str:
    STATIC_EXPORTING_FOLDER="Export_Agent/Agentcode"
    if len(agent_ids)==1:
        adict={}
        agent_data_list = await get_agents_by_id(agentic_application_id=agent_ids[0])
        if not agent_data_list or not isinstance(agent_data_list, list) or len(agent_data_list) == 0:
            raise HTTPException(status_code=404, detail=f"Agent ID: '{agent_ids[0]}' not found.")
        agent_dict = agent_data_list[0]
        agent_for_json_dump = agent_dict.copy()
        for key, value in agent_for_json_dump.items():
            if isinstance(value, datetime):
                agent_for_json_dump[key] = value.isoformat()
        adict[agent_ids[0]]=agent_for_json_dump
        temp_base_dir = os.path.join(tempfile.gettempdir(), "your_app_agent_exports")
        unique_export_id = os.urandom(8).hex() # Re-add your unique export ID here
        temp_working_dir = os.path.join(temp_base_dir, f"{agent_ids[0]}_{unique_export_id}") # Append unique ID here
        final_zip_content_folder_name = agent_dict.get('agentic_application_name')
        target_export_folder_path = os.path.join(temp_working_dir, final_zip_content_folder_name)
        zip_file_full_path = None

        try:
            if os.path.exists(temp_working_dir):
                shutil.rmtree(temp_working_dir)
            os.makedirs(os.path.dirname(target_export_folder_path), exist_ok=True)
            shutil.copytree(STATIC_EXPORTING_FOLDER, target_export_folder_path)
            env_file_path = os.path.join(target_export_folder_path, 'Agent_Backend/.env')
            conn = await asyncpg.connect(
                host=POSTGRESQL_HOST,
                database='login',
                user=POSTGRESQL_USER,
                password=POSTGRESQL_PASSWORD
            )
            user_data = await conn.fetchrow(
                    "SELECT mail_id, user_name, role FROM login_credential WHERE mail_id = $1",
                    user_email
                )
            user=user_data[1] if user_data else None
            role=user_data[2] if user_data else None
            with open(env_file_path, 'a') as f: 
                f.write(f"\nUSER_EMAIL={user_email or ''}\n")
                f.write(f"\nUSER_NAME={user or ''}\n")
                f.write(f"\nROLE={role or ''}\n")
            agent_data_file_path = os.path.join(target_export_folder_path, 'Agent_Backend/agent_config.py')
            with open(agent_data_file_path, 'w') as f:
                f.write('agent_data = ')
                json.dump(adict, f, indent=4)
            inference_path = os.path.join(target_export_folder_path, 'Agent_Backend/src/inference')
            destination_file = os.path.join(target_export_folder_path,'Agent_Backend/agent_endpoints.py')
            backend_path=os.path.join(target_export_folder_path,'Agent_Backend')
            shutil.copy('src/inference/inference_utils.py', inference_path)
            shutil.copy('telemetry_wrapper.py',backend_path)
            shutil.copy('evaluation_metrics.py',backend_path)
            shutil.copy('src/inference/react_agent_inference.py', inference_path)
            shutil.copy('requirements.txt',backend_path)
            if agent_dict.get('agentic_application_type') in ['react_agent','react_critic_agent','planner_executor_agent','planner_executor_critic_agent']:
                if agent_dict.get('agentic_application_type') == 'react_agent':
                    source_file = 'Export_Agent/endpoints/react_agent_endpoints.py'
                    shutil.copyfile(source_file, destination_file)
                elif agent_dict.get('agentic_application_type') == 'react_critic_agent':
                    shutil.copy('src/inference/react_critic_agent_inference.py', inference_path)
                    source_file = 'Export_Agent/endpoints/react_critic_agent_endpoints.py'
                    shutil.copyfile(source_file, destination_file)
                elif agent_dict.get('agentic_application_type') == 'planner_executor_agent':
                    shutil.copy('src/inference/planner_executor_agent_inference.py', inference_path)
                    source_file = 'Export_Agent/endpoints/planner_executor_agent_endpoints.py'
                    shutil.copyfile(source_file, destination_file)
                elif agent_dict.get('agentic_application_type') == 'planner_executor_critic_agent':
                    shutil.copy('src/inference/planner_executor_critic_agent_inference.py', inference_path)
                    source_file = 'Export_Agent/endpoints/planner_executor_critic_agent_endpoints.py'
                    shutil.copyfile(source_file, destination_file)
                await get_tool_data(agent_dict, export_path=target_export_folder_path)
                worker_agent_data_file_path = os.path.join(target_export_folder_path, 'Agent_Backend/worker_agents_config.py')
                with open(worker_agent_data_file_path, 'w') as f:
                    f.write('worker_agents = ')
                    json.dump({}, f, indent=4)
                output_zip_name = f"EXPORTAGENT"
                zip_base_name = os.path.join(temp_base_dir, output_zip_name)
                zip_file_full_path = shutil.make_archive(zip_base_name, 'zip', temp_working_dir)
                return zip_file_full_path
            if agent_dict.get('agentic_application_type') in ['meta_agent','planner_meta_agent']:
                if agent_dict.get('agentic_application_type') == 'meta_agent':
                    shutil.copy('src/inference/meta_agent_inference.py', inference_path)
                    source_file = 'Export_Agent/endpoints/meta_agent_endpoints.py'
                    shutil.copyfile(source_file, destination_file)
                elif agent_dict.get('agentic_application_type') == 'planner_meta_agent':
                    shutil.copy('src/inference/planner_meta_agent_inference.py', inference_path)
                    source_file = 'Export_Agent/endpoints/planner_meta_agent_endpoints.py'
                    shutil.copyfile(source_file, destination_file)
                worker_agent_ids=agent_dict.get("tools_id")
                worker_agents={}
                for agent in json.loads(worker_agent_ids):
                    agent_data = await get_agents_by_id(agentic_application_id=agent)
                    if agent_data:
                        agent_dict= agent_data[0]
                        processed_agent_dict = {}
                        for key, value in agent_dict.items():
                            if isinstance(value, datetime):
                                processed_agent_dict[key] = value.isoformat()
                            else:
                                processed_agent_dict[key] = value
                        worker_agents[agent] = processed_agent_dict
                    else:
                        worker_agents[agent] = None
                worker_agent_data_file_path = os.path.join(target_export_folder_path, 'Agent_Backend/worker_agents_config.py')
                with open(worker_agent_data_file_path, 'w') as f:
                    f.write('worker_agents = ')
                    json.dump(worker_agents, f, indent=4)
                tool_list=[]
                for i in worker_agents:
                    tool_list=tool_list+(json.loads(worker_agents[i]["tools_id"]))
                await get_tool_data(agent_dict, export_path=target_export_folder_path,tools=tool_list)
                output_zip_name = f"EXPORTAGENT"
                zip_base_name = os.path.join(temp_base_dir, output_zip_name)
                zip_file_full_path = shutil.make_archive(zip_base_name, 'zip', temp_working_dir)
                return zip_file_full_path
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Failed to export agent: {str(e)}")
    else:
        workerids=set()
        app_types=set()
        toolids=set()
        adict={}
        for agent_id in agent_ids:
            agent_data_list = await get_agents_by_id(agentic_application_id=agent_id)
            if not agent_data_list or not isinstance(agent_data_list, list) or len(agent_data_list) == 0:
                raise HTTPException(status_code=404, detail=f"Agent with ID '{agent_id}' not found.")
            agent_dict = agent_data_list[0]
            agent_for_json_dump = agent_dict.copy()
            for key, value in agent_for_json_dump.items():
                if isinstance(value, datetime):
                    agent_for_json_dump[key] = value.isoformat()
            adict[agent_id]=agent_for_json_dump
            app_types.add(agent_for_json_dump['agentic_application_type'])
            if agent_dict.get("agentic_application_type") in ["meta_agent","planner_meta_agent"]:
                ids=json.loads(agent_dict.get('tools_id'))
                for i in ids:
                    workerids.add(i)
            else:
                ids=json.loads(agent_dict.get('tools_id'))
                for i in ids:
                    toolids.add(i)
        temp_base_dir = os.path.join(tempfile.gettempdir(), "your_app_agent_exports")
        unique_export_id = os.urandom(8).hex() # Re-add your unique export ID here
        temp_working_dir = os.path.join(temp_base_dir, f"exportagent_{unique_export_id}") # Append unique ID here
        final_zip_content_folder_name = "MultipleAgents"
        target_export_folder_path = os.path.join(temp_working_dir, final_zip_content_folder_name)
        zip_file_full_path = None

        try:
            if os.path.exists(temp_working_dir):
                shutil.rmtree(temp_working_dir)
            os.makedirs(os.path.dirname(target_export_folder_path), exist_ok=True)
            shutil.copytree(STATIC_EXPORTING_FOLDER, target_export_folder_path)
            env_file_path = os.path.join(target_export_folder_path, 'Agent_Backend/.env')
            conn = await asyncpg.connect(
                host=POSTGRESQL_HOST,
                database='login',
                user=POSTGRESQL_USER,
                password=POSTGRESQL_PASSWORD
            )
            user_data = await conn.fetchrow(
                    "SELECT mail_id, user_name, role FROM login_credential WHERE mail_id = $1",
                    user_email
                )
            user=user_data[1] if user_data else None
            role=user_data[2] if user_data else None
            with open(env_file_path, 'a') as f: 
                f.write(f"\nUSER_EMAIL={user_email or ''}\n")
                f.write(f"\nUSER_NAME={user or ''}\n")
                f.write(f"\nROLE={role or ''}\n")
            inference_path = os.path.join(target_export_folder_path, 'Agent_Backend/src/inference')
            destination_file = os.path.join(target_export_folder_path,'Agent_Backend/agent_enpoints.py')
            backend_path=os.path.join(target_export_folder_path,'Agent_Backend')
            shutil.copy('src/inference/inference_utils.py', inference_path)
            shutil.copy('telemetry_wrapper.py',backend_path)
            shutil.copy('evaluation_metrics.py',backend_path)
            shutil.copy('src/inference/react_agent_inference.py', inference_path)
            shutil.copy('src/inference/meta_agent_inference.py', inference_path)
            shutil.copy('src/inference/react_critic_agent_inference.py', inference_path)
            shutil.copy('src/inference/planner_executor_agent_inference.py', inference_path)
            shutil.copy('src/inference/planner_executor_critic_agent_inference.py', inference_path)
            shutil.copy('src/inference/planner_meta_agent_inference.py', inference_path)
            shutil.copy('requirements.txt',backend_path)
            source_file = 'Export_Agent/endpoints/multiple_agent_endpoints.py'
            shutil.copyfile(source_file, destination_file)
            agent_data_file_path = os.path.join(target_export_folder_path, 'Agent_Backend/agent_config.py')
            with open(agent_data_file_path, 'w') as f:
                f.write('agent_data = ')
                json.dump(adict, f, indent=4)
            worker_agents={}
            for agent in list(workerids):
                agent_data = await get_agents_by_id(agentic_application_id=agent)
                if agent_data:
                    agent_dict= agent_data[0]
                    processed_agent_dict = {}
                    for key, value in agent_dict.items():
                        if isinstance(value, datetime):
                            processed_agent_dict[key] = value.isoformat()
                        else:
                            processed_agent_dict[key] = value
                    worker_agents[agent] = processed_agent_dict
                else:
                    worker_agents[agent] = None
            worker_agent_data_file_path = os.path.join(target_export_folder_path, 'Agent_Backend/worker_agents_config.py')
            with open(worker_agent_data_file_path, 'w') as f:
                f.write('worker_agents = ')
                json.dump(worker_agents, f, indent=4)
            tool_list=[]
            for i in worker_agents:
                tool_list=tool_list+(json.loads(worker_agents[i]["tools_id"]))
            for i in tool_list:
                toolids.add(i)
            await get_tool_data(adict, export_path=target_export_folder_path,tools=list(toolids))
            output_zip_name = f"EXPORTAGENTS"
            zip_base_name = os.path.join(temp_base_dir, output_zip_name)
            zip_file_full_path = shutil.make_archive(zip_base_name, 'zip', temp_working_dir)
            return zip_file_full_path               
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Failed to export agent: {str(e)}")        



@app.get("/kb_list")
async def list_kb_directories(fastapi_request: Request):
    """
    Lists vectorstore directories in KB_DIR.
    """
    #changed
    user_id = fastapi_request.cookies.get("user_id")
    user_session = fastapi_request.cookies.get("user_session")
    update_session_context(user_session=user_session, user_id=user_id)
    KB_DIR = "KB_DIR"
    kb_path = Path(KB_DIR)

    if not kb_path.exists():
        raise HTTPException(status_code=404, detail="Knowledge base directory does not exist.")

    directories = [d.name for d in kb_path.iterdir() if d.is_dir()]

    if not directories:
        return {"message": "No knowledge bases found."}

    return {"knowledge_bases": directories}



GOOGLE_API_KEY = os.environ.get("GOOGLE_API_KEY", "no-api-key-set")
GOOGLE_EMBEDDING_MODEL = os.environ.get("GOOGLE_EMBEDDING_MODEL", "models/embedding-001")


@app.post("/kbdocuments")
async def upload_files(fastapi_request: Request, session_id: str = Form(...), kb_name:str = 'temp', files: List[UploadFile] = File(...)):
    #changed
    user_id = fastapi_request.cookies.get("user_id")
    user_session = fastapi_request.cookies.get("user_session")
    update_session_context(user_session=user_session, user_id=user_id)
    if GOOGLE_API_KEY == "no-api-key-set":
        raise ValueError("GOOGLE_API_KEY environment variable is not set.")

    # Initialize Google Embeddings
    embeddings = GoogleGenerativeAIEmbeddings(
        model=GOOGLE_EMBEDDING_MODEL,
        google_api_key=GOOGLE_API_KEY
    )

    # Create temp directory
    temp_dir = os.path.join('TEMPFILE_DIR', f"session_{session_id}")
    os.makedirs(temp_dir, exist_ok=True)

    file_paths = []

    for file in files:
        file_path = os.path.join(temp_dir, file.filename)
        with open(file_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
        file_paths.append(file_path)

    # Load text files and split into documents
    documents = []
    for path in file_paths:
        ext = os.path.splitext(path)[1].lower()
        try:
            if ext == ".txt":
                loader = TextLoader(path, encoding='utf-8')
            elif ext == ".pdf":
                loader = PyMuPDF4LLMLoader(path)
            else:
                continue  # Skip unsupported file types
            documents.extend(loader.load())
        except Exception as e:
            print(f"Failed to load {path}: {e}")

    # Split documents
    text_splitter = CharacterTextSplitter(chunk_size=1000, chunk_overlap=300)
    docs = text_splitter.split_documents(documents)

    # Create vector store
    vectorstore = FAISS.from_documents(docs, embeddings)

    # Save vector store to session-specific FAISS index folder
    faiss_path = os.path.join('KB_DIR', kb_name)
    vectorstore.save_local(faiss_path)

    return {
        "message": f"Uploaded {len(files)} files. Embeddings created and stored for session {session_id}.",
        "storage_path": faiss_path
    }
 

async def evaluate_agent_performance(request: GroundTruthEvaluationRequest, file_path: str):
    """
    Internal function to evaluate an agent against a ground truth file.
    Returns evaluation results, file paths, and summary.
    """
    if not os.path.isfile(file_path):
        raise FileNotFoundError(f"File not found: {file_path}")

    if not file_path.lower().endswith((".csv", ".xlsx", ".xls")):
        raise ValueError("File must be a CSV or Excel file.")

    llm = load_model(request.model_name)
    agent_type=request.agent_type
    specialized_agent_inference: BaseAgentInference = get_specialized_inference_service(agent_type=agent_type)

    avg_scores, summary, excel_path = await evaluate_ground_truth_file(
        model_name=request.model_name,
        agent_type=agent_type,
        file_path=file_path,  # ✅ Use here
        agentic_application_id=request.agentic_application_id,
        session_id=request.session_id,
        specialized_agent_inference=specialized_agent_inference,
        llm=llm,
        use_llm_grading=request.use_llm_grading
    )

    return avg_scores, summary, excel_path

@app.get("/download-evaluation-result")
async def download_evaluation_result(fastapi_request: Request, file_name: str):
    """
    Endpoint to download the evaluation result file.
    
    Query Parameters:
    - file_name (str): The name of the result file to download.

    Returns:
    - FileResponse: Returns the file as a downloadable response.
    """
    #changed
    user_id = fastapi_request.cookies.get("user_id")
    user_session = fastapi_request.cookies.get("user_session")
    update_session_context(user_session=user_session, user_id=user_id)
    # Full path to file
    file_path = os.path.join(Path.cwd(), 'outputs', file_name)

    if not os.path.exists(file_path):
        log.error(f"File not found: {file_path}")
        raise HTTPException(status_code=404, detail="❌ File not found")
    log.info(f"Downloading evaluation result file: {file_path}")
    return FileResponse(path=file_path, filename=file_name, media_type="application/octet-stream")


async def upload_evaluation_file(file: UploadFile = File(...), subdirectory: str = ""):
    if subdirectory.startswith("/") or subdirectory.startswith("\\"):
        subdirectory = subdirectory[1:]

    save_path = os.path.join(EVALUATION_UPLOAD_DIR, subdirectory) if subdirectory else EVALUATION_UPLOAD_DIR
    os.makedirs(save_path, exist_ok=True)

    # Ensure unique filename using UUID
    name, ext = os.path.splitext(file.filename)
    safe_filename = f"{name}_{uuid.uuid4().hex[:8]}{ext}"
    full_file_path = os.path.join(save_path, safe_filename)

    # Save file
    with open(full_file_path, "wb") as f:
        f.write(await file.read())

    log.info(f"Evaluation file '{file.filename}' uploaded as '{safe_filename}' at '{full_file_path}'")

    relative_path = os.path.relpath(full_file_path, start=os.getcwd())
    return {
        "info": f"File '{file.filename}' saved as '{safe_filename}' at '{relative_path}'",
        "file_path": relative_path
    }


@app.post("/upload-and-evaluate/")
async def upload_and_evaluate(fastapi_request: Request,
    file: UploadFile = File(...),
    subdirectory: str = "",
    request: GroundTruthEvaluationRequest = Depends()
):
    #changed
    user_id = fastapi_request.cookies.get("user_id")
    user_session = fastapi_request.cookies.get("user_session")
    update_session_context(user_session=user_session, user_id=user_id)
    # Step 1: Upload file
    upload_resp = await upload_evaluation_file(file, subdirectory)

    if "file_path" not in upload_resp:
        raise HTTPException(status_code=400, detail="File upload failed.")

    file_path = upload_resp["file_path"]

    try:
        avg_scores, summary, excel_path = await evaluate_agent_performance(request ,file_path)

        file_name = os.path.basename(excel_path)

        # ✅ Return the Excel file as response with custom headers
        summary_safe = summary.encode("ascii", "ignore").decode().replace("\n", " ")
        log.info(f"Evaluation completed successfully. Download URL: {file_name}")
        return FileResponse(
            path=excel_path,
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            filename=file_name,
            headers={
                "X-Message": "Evaluation completed successfully",
                "X-Average-Scores": str(avg_scores),
                "X-Diagnostic-Summary": summary_safe
            }
        )

    except Exception as e:
        log.error(f"Evaluation failed: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Evaluation failed: {str(e)}")


@app.post("/upload-and-evaluate-json/")
async def upload_and_evaluate_json(
    fastapi_request: Request,
    file: UploadFile = File(...),
    subdirectory: str = "",
    request: GroundTruthEvaluationRequest = Depends(),
    # fastapi_request: Request = None
):
    user_id = fastapi_request.cookies.get("user_id")
    user_session = fastapi_request.cookies.get("user_session")
    update_session_context(user_session=user_session, user_id=user_id)
    # Upload the file
    upload_resp = await upload_evaluation_file(file, subdirectory)

    if "file_path" not in upload_resp:
        raise HTTPException(status_code=400, detail="File upload failed.")

    file_path = upload_resp["file_path"]

    try:
        # Evaluate using new function that accepts file_path separately
        avg_scores, summary, excel_path = await evaluate_agent_performance(
            request,
            file_path=file_path
        )

        file_name = os.path.basename(excel_path)
        download_url = f"{fastapi_request.base_url}download-evaluation-result?file_name={file_name}"
        log.info(f"Evaluation completed successfully. Download URL: {download_url}")
        return {
            "message": "Evaluation completed successfully",
            "download_url": download_url,
            "average_scores": avg_scores,
            "diagnostic_summary": summary
        }

    except Exception as e:
        log.error(f"Evaluation failed: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Evaluation failed: {str(e)}")



async def cleanup_old_files(directories=["outputs", "evaluation_uploads"], expiration_hours=24):
    log.debug("Starting cleanup task for old files...")
    while True:
        try:
            now = time.time()
            cutoff = now - (expiration_hours * 60 * 60)

            for directory in directories:
                abs_path = os.path.abspath(directory)
                deleted_files = []

                log.debug(f"🔍 [Cleanup Task] Scanning '{abs_path}' for files older than {expiration_hours} hours...")

                if not os.path.exists(abs_path):
                    log.warning(f"⚠️ [Cleanup Task] Directory does not exist: {abs_path}")
                    continue

                for filename in os.listdir(abs_path):
                    file_path = os.path.join(abs_path, filename)
                    if os.path.isfile(file_path):
                        file_mtime = os.path.getmtime(file_path)
                        if file_mtime < cutoff:
                            try:
                                os.remove(file_path)
                                deleted_files.append(filename)
                                log.debug(f"[Cleanup Task] Deleted expired file: {filename}")
                            except Exception as e:
                                log.error(f"[Cleanup Task] Failed to delete '{filename}': {e}")

                if not deleted_files:
                    log.info(f"[Cleanup Task] No expired files found in '{abs_path}'.")
                else:
                    log.info(f"[Cleanup Task] Deleted {len(deleted_files)} file(s) from '{abs_path}': {deleted_files}")

        except Exception as e:
            log.error(f"[Cleanup Task] Error during cleanup: {e}")

        await asyncio.sleep(3600)  # Wait 1 hour before next cleanup cycle



# @app.on_event("startup")
# async def start_cleanup_task(fastapi_request: Request):
#     user_id = fastapi_request.cookies.get("user_id")
#     user_session = fastapi_request.cookies.get("user_session")
#     update_session_context(user_session=user_session, user_id=user_id)
#     log.debug(" [Startup] Launching background file cleanup task...")
#     asyncio.create_task(cleanup_old_files())



# data connector start
# ==================== Global Variables ====================  
connected_databases: Dict[str, dict] = {}

# ==================== Data_connector Models ====================
class ConnectionSchema(BaseModel):
    connection_name: str = Field(..., example="My SQLite DB")
    connection_database_type: str = Field(..., example="sqlite")  # postgresql, mysql, sqlite, mongodb, azuresql
    connection_host: Optional[str] = ""
    connection_port: Optional[int] = 0
    connection_username: Optional[str] = ""
    connection_password: Optional[str] = ""
    connection_database_name: str  # DB name, file path, or URI

    @validator('connection_database_type')
    def valid_db_type(cls, v):
        valid_types = ["postgresql", "mysql", "sqlite", "mongodb", "azuresql"]
        if v.lower() not in valid_types:
            raise ValueError(f"Database type must be one of {valid_types}")
        return v.lower()
    
class DBConnectionRequest(BaseModel):
    name: str
    db_type: str  
    host: str
    port: int
    username: str
    password: str
    database: str
    flag_for_insert_into_db_connections_table: str
 
class QueryGenerationRequest(BaseModel):
    database_type: str
    natural_language_query: str
 
class QueryExecutionRequest(BaseModel):
    name: str
    query: str
 
class CRUDRequest(BaseModel):
    name: str
    operation: str
    table: str
    data: dict = {}
    condition: str = ""

class ToolRequestModel(BaseModel):
    tool_description: str
    code_snippet: str
    model_name: str
    created_by: str
    tag_ids: List[int]
    db_connection_name: Optional[str] = None


# ==================== Utilities ===================================================================================================================#
 
def build_connection_string(config: dict) -> str:
    db_type = config["db_type"].lower()

    if db_type == "mysql":
        return f"mysql+mysqlconnector://{config['username']}:{config['password']}@{config['host']}:{config['port']}/{config['database']}"
    elif db_type == "postgresql":
        return f"postgresql+psycopg2://{config['username']}:{config['password']}@{config['host']}:{config['port']}/{config['database']}"
    elif db_type == "azuresql":
        return f"mssql+pyodbc://{config['username']}:{config['password']}@{config['host']}:{config['port']}/{config['database']}?driver=ODBC+Driver+17+for+SQL+Server"
    elif db_type == "sqlite":
        return f"sqlite:///{config['database']}"
    elif db_type == "mongodb":
        host = config["host"]
        port = config["port"]
        db_name = config["database"]
        username = config.get("username")
        password = config.get("password")
        if username and password:
            return f"mongodb://{username}:{password}@{host}:{port}/?authSource={db_name}"
        else:
            return f"mongodb://{host}:{port}/{db_name}"
    else:
        raise HTTPException(status_code=400, detail=f"Unsupported database type: {config['db_type']}")

def get_engine(config):
    db_type = config["db_type"].lower()

    if db_type == "mongodb":
        # Return Motor client for MongoDB

        mongo_uri = build_connection_string(config)
        if not mongo_uri:
            raise HTTPException(status_code=400, detail="MongoDB URI missing in 'database' field.")
        return AsyncIOMotorClient(mongo_uri)
    else:
        connection_str = build_connection_string(config)
        return create_engine(connection_str)

def create_database_if_not_exists(config):
    db_type = config["db_type"].lower()
    db_name = config["database"]

    # SQLite DB creation not needed
    if db_type == "sqlite":
        return

    # MongoDB DB creation is implicit in connection, so skip
    if db_type == "mongodb":
        return

    # For SQL DBs, connect to admin DB for creation
    config_copy = config.copy()
    if db_type == "postgresql":
        config_copy["database"] = "postgres"
    elif db_type == "mysql":
        config_copy["database"] = ""

    engine = create_engine(build_connection_string(config_copy), isolation_level="AUTOCOMMIT")
    

    with engine.connect() as conn:
        if db_type == "mysql":
            conn.execute(text(f"CREATE DATABASE IF NOT EXISTS `{db_name}`"))
        elif db_type == "postgresql":
            result = conn.execute(text("SELECT 1 FROM pg_database WHERE datname = :dbname"), {"dbname": db_name})
            if not result.fetchone():
                conn.execute(text(f'CREATE DATABASE "{db_name}"'))
        elif db_type == "azuresql":
            # Add Azure SQL DB creation logic here if needed
            pass
        else:
            raise HTTPException(status_code=400, detail=f"Database creation not supported for {config['db_type']}")
        



from fastapi import HTTPException

async def check_connection_name_exists(name: str, table_name="db_connections_table") -> bool:
    connection = None
    try:
        connection = await asyncpg.connect(
            host=POSTGRESQL_HOST,
            database=DATABASE,
            user=POSTGRESQL_USER,
            password=POSTGRESQL_PASSWORD
        )
        query = f"SELECT 1 FROM {table_name} WHERE connection_name = $1 LIMIT 1"
        result = await connection.fetchrow(query, name)
        return result is not None
    except Exception as e:
        # Log or handle error if necessary
        raise HTTPException(status_code=500, detail=f"Error checking connection name: {e}")
    finally:
        if connection:
            await connection.close()

@app.post("/connect")
async def connect_to_database(req: DBConnectionRequest):
    if req.flag_for_insert_into_db_connections_table == "1":
            name_exists = await check_connection_name_exists(req.name)
            if name_exists:
                raise HTTPException(status_code=400, detail=f"Connection name '{req.name}' already exists.")


    try:
        config = req.dict()


        # Adjust config based on DB type:
        if req.db_type == "sqlite":
            # For SQLite, host/port/user/pass not needed, database is file path
            config["host"] = "Na"
            config["port"] = 0
            config["username"] = "Na"
            config["password"] = "Na"
            create_database_if_not_exists(config)
            manager = get_connection_manager()
            manager.add_sql_database(config.get("name",""),build_connection_string(config))
            # session_sql = manager.get_sql_session(config.get("name",""))
            # session_sql.execute(text("CREATE TABLE IF NOT EXISTS ab (age INTEGER)"))
            # session_sql.commit()
            # session_sql.close()

        elif req.db_type == "mongodb":
            manager = get_connection_manager()
            manager.add_mongo_database(config.get("name",""),build_connection_string(config),config.get("database",""))
            mongo_db = manager.get_mongo_database(config.get("name",""))
            # sample_doc = await mongo_db.test_collection.find_one()
            try:
                await mongo_db.command("ping")
                print("[MongoDB] Connection test successful.")
            except Exception as e:
                raise HTTPException(status_code=500, detail=f"MongoDB ping failed: {str(e)}")
            connected_databases[req.name] = config

        elif req.db_type == "postgresql" or req.db_type == "mysql":
            create_database_if_not_exists(config)
            manager = get_connection_manager()
            manager.add_sql_database(config.get("name",""),build_connection_string(config))
            # session_postgres = manager.get_sql_session(config.get("name",""))
            # session_db1.execute(text("select * from ab;"))
            connected_databases[req.name] = config
            # session_postgres.close()


        

        if req.flag_for_insert_into_db_connections_table == "1":
            connection_data = {
                "connection_id": str(uuid.uuid4()),
                "connection_name": req.name,
                "connection_database_type": req.db_type,
                "connection_host": config.get("host", ""),
                "connection_port": config.get("port", ),
                "connection_username": config.get("username", ""),
                "connection_password": config.get("password", ""),
                "connection_database_name": config.get("database", "")
            }

        
            result = await insert_into_db_connections_table(connection_data)

            if result.get("is_created"):
                return {
                    "message": f"✅ Connected to {req.db_type} database '{req.database}' and saved configuration.",
                    **result
                }
            else:
                return {
                    "message": f"⚠️ Connected to {req.db_type} database '{req.database}', but failed to save configuration.",
                    # **result
                }
        else:
            return {
                    "message": f"✅ Connected to {req.db_type} database '{req.database}'."
                }
            

    except SQLAlchemyError as e:
        raise HTTPException(status_code=500, detail=f"Connection failed: {str(e)}")

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Unexpected error: {str(e)}")
    
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

class DBDisconnectRequest(BaseModel):
    name: str
    db_type: str



async def delete_connection_by_name(name: str, table_name="db_connections_table"):
    connection = None
    try:
        connection = await asyncpg.connect(
            host=POSTGRESQL_HOST,
            database=DATABASE,
            user=POSTGRESQL_USER,
            password=POSTGRESQL_PASSWORD
        )

        delete_query = f"DELETE FROM {table_name} WHERE connection_name = $1"
        result = await connection.execute(delete_query, name)

        return {"message": f"Deleted: {name}", "result": result}
    
    except Exception as e:
        return {"error": str(e)}
    
    finally:
        if connection:
            await connection.close()


@app.post("/disconnect")
async def disconnect_database(req: DBDisconnectRequest):
    manager = get_connection_manager()
    name = req.name
    db_type = req.db_type.lower()

    # Get current active connections
    active_sql_connections = list(manager.sql_engines.keys())
    active_mongo_connections = list(manager.mongo_clients.keys())
    delete_result = await delete_connection_by_name(name)


    try:
        if db_type == "mongodb":
            if name in active_mongo_connections:
                await manager.close_mongo_client(name)
                return {"message": f"Disconnected MongoDB connection '{name}' successfully and the details are deleted from the table.."}
            else:
                # Your custom logic here
                return {"message": f"ℹMongoDB connection '{name}' was not active but the details are deleted from the table."}

        else:  # SQL
            if name in active_sql_connections:
                manager.dispose_sql_engine(name)
                return {"message": f"Disconnected SQL connection '{name}' successfully and the details are deleted from the table."}
            else:
                # Your custom logic here
                return {"message": f"ℹSQL connection '{name}' was not active but the details are deleted from the table.."}

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error while disconnecting: {str(e)}")
 

@app.post("/generate_query")
async def generate_query(req: QueryGenerationRequest):
    try:
        llm = AzureChatOpenAI(
            azure_endpoint=os.getenv("AZURE_ENDPOINT"),
            api_key=os.getenv("AZURE_OPENAI_API_KEY"),  # ❗ Replace with env variable
            openai_api_version='2023-05-15',
            azure_deployment='gpt-4o',
            temperature=0.7,
            max_tokens=2000
        )
 
        prompt = f"""
        🔧 Prompt Template:
        You are an intelligent query generation assistant.
        I will provide you with:
   
        The type of database (e.g., MySQL, PostgreSQL, MongoDB, etc.)
   
        A query in natural language
   
        Your task is to:
   
        Convert the natural language query into a valid query in the specified database’s query language.
   
        Ensure the syntax is appropriate for the chosen database.
   
        Do not include explanations or extra text.
   
        Do not include any extra quotes, punctuation marks, or explanations. Provide only the final query in the output field, without any additional text or symbols (e.g., no quotation marks, commas, or colons).
   
        Database: {req.database_type}
        Natural Language Query: {req.natural_language_query}
        🔄 Example Input:
        Database: PostgreSQL
        Natural Language Query: Show the top 5 customers with the highest total purchases.
   
        ✅ Expected Output:
        SELECT customer_id, SUM(purchase_amount) AS total_purchases
        FROM purchases
        GROUP BY customer_id
        ORDER BY total_purchases DESC
        LIMIT 5;
   
        🔄 Example 2 (MongoDB)
        Database: MongoDB
        Natural Language Query: Get all orders placed by customer with ID "12345" from the "orders" collection.
   
        ✅ Expected Output:
        db.orders.find({{ customer_id: "12345" }})
        """
 
        response = llm.invoke([
            {"role": "system", "content": "You generate clean and executable database queries from user input."},
            {"role": "user", "content": prompt}
        ])
        return {"generated_query": response.content.strip()}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Query generation failed: {e}")
 
 
 
 
from typing import List, Dict

@app.post("/run_query")
async def run_query(req: QueryExecutionRequest):
    # Ensure the connection exists in the dictionary
    # if req.name not in connected_databases:
    #     raise HTTPException(status_code=404, detail="Connection not found.")
 
    config = await get_connection_config(req.name)

   
    # Log the query for debugging purposes (sanitize or remove sensitive information before logging in production)
    print(f"Running query: {req.query}")
    session = None
 
    try:
        # Get the engine for the specific database connection
        # engine = get_engine(config)
        manager=get_connection_manager()
        manager.add_sql_database(req.name,build_connection_string(config))
        session = manager.get_sql_session(req.name)

        # with engine.connect() as conn:
        # Log query execution start
        print(f"Executing query on connection {req.name}")
        
        # Check if it's a DDL query (CREATE, ALTER, DROP)
        if any(word in req.query.upper() for word in ["CREATE", "ALTER", "DROP"]):
            print("Executing DDL Query")
            session.execute(text(req.query))  # Execute DDL queries directly
            session.commit()  # Commit after DDL queries
            return {"message": "DDL Query executed successfully."}

        # Handle SELECT queries
        if req.query.strip().upper().startswith("SELECT"):
            print("Executing SELECT Query")
            result = session.execute(text(req.query))  # Execute SELECT query
            
            # Fetch the column names
            columns = list(result.keys()) # This gives us the column names
            rows = result.fetchall()  # Get all rows

            # Convert rows into dictionaries with column names as keys
            rows_dict = [{columns[i]: row[i] for i in range(len(columns))} for row in rows]

            return {"columns": columns, "rows": rows_dict}

        # Handle DML queries (INSERT, UPDATE, DELETE)
        print("Executing DML Query")
        result = session.execute(text(req.query))  # Execute DML query
        session.commit()  # Commit the transaction

        # Log how many rows were affected
        print(f"Rows affected: {result.rowcount}")
        
        return {"message": f"Query executed successfully, {result.rowcount} rows affected."}
 
    except SQLAlchemyError as e:
        # Log the exception for debugging
        print(f"Query failed: {e}")
        raise HTTPException(status_code=400, detail=f"Query failed: {str(e)}")
 
    except Exception as e:
        # Catch all other exceptions (e.g., connection issues, etc.)
        print(f"Unexpected error: {e}")
        raise HTTPException(status_code=500, detail=f"Unexpected error: {str(e)}")
    
    finally:
        if session:
            session.close()
 
 
 
@app.post("/crud")
def crud_operation(req: CRUDRequest):
    if req.name not in connected_databases:
        raise HTTPException(status_code=404, detail="Connection not found.")
    config = connected_databases[req.name]
 
    try:
        engine = get_engine(config)
        with engine.connect() as conn:
            op = req.operation.lower()
 
            if op == "create":
                columns = ', '.join(req.data.keys())
                placeholders = ', '.join(f":{k}" for k in req.data)
                query = f"INSERT INTO {req.table} ({columns}) VALUES ({placeholders})"
                conn.execute(text(query), req.data)
 
            elif op == "read":
                query = f"SELECT * FROM {req.table}"
                if req.condition:
                    query += f" WHERE {req.condition}"
                result = conn.execute(text(query))
                rows = [dict(row) for row in result]
                return {"columns": result.keys(), "rows": rows}
 
            elif op == "update":
                if not req.condition:
                    raise HTTPException(status_code=400, detail="Condition required for update.")
                set_clause = ', '.join(f"{k} = :{k}" for k in req.data)
                query = f"UPDATE {req.table} SET {set_clause} WHERE {req.condition}"
                conn.execute(text(query), req.data)
 
            # elif op == "delete":
            #     if not req.condition:
            #         raise HTTPException(status_code=400, detail="Condition required for delete.")
            #     query = f"DELETE FROM {req.table} WHERE {req.condition}"
            #     conn.execute(text(query))
 
            else:
                raise HTTPException(status_code=400, detail="Invalid operation.")
 
            return {"message": f"{op.upper()} operation completed on table '{req.table}'."}
    except SQLAlchemyError as e:
        raise HTTPException(status_code=500, detail=f"CRUD operation failed: {e}")

@app.get("/connections")
async def get_connections():
    try:
        conn = await asyncpg.connect(
            host=POSTGRESQL_HOST,
            database=DATABASE,
            user=POSTGRESQL_USER,
            password=POSTGRESQL_PASSWORD
        )
        rows = await conn.fetch("SELECT connection_name, connection_database_type, connection_host, connection_port, connection_username , connection_password, connection_database_name FROM db_connections_table")
        connections = [
            {
                "connection_name": row["connection_name"],
                "connection_database_type": row["connection_database_type"],
                "connection_host": row["connection_host"],
                "connection_port": row["connection_port"],
                "connection_username": row["connection_username"],
                "connection_password": row["connection_password"],
                "connection_database_name": row["connection_database_name"]
            }
            for row in rows
        ]
        await conn.close()
        return {"connections": connections}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    
@app.get("/connection/{connection_name}")
async def get_connection_config(connection_name: str):
    try:
        conn = await asyncpg.connect(
            host=POSTGRESQL_HOST,
            database=DATABASE,
            user=POSTGRESQL_USER,
            password=POSTGRESQL_PASSWORD
        )

        query = """
            SELECT connection_name, connection_database_type, connection_host,
                   connection_port, connection_username, connection_password,connection_database_name
            FROM db_connections_table
            WHERE connection_name = $1
        """
        row = await conn.fetchrow(query, connection_name)

        await conn.close()

        if not row:
            raise HTTPException(status_code=404, detail="Connection not found")

        config = {
            "name": row["connection_name"],
            "db_type": row["connection_database_type"],
            "host": row["connection_host"],
            "port": row["connection_port"],
            "username": row["connection_username"],
            "password": row["connection_password"],
            "database": row["connection_database_name"]
        }

        return config

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/connections_sql")
async def get_connections_sql():
    try:
        conn = await asyncpg.connect(
            host=POSTGRESQL_HOST,
            database=DATABASE,
            user=POSTGRESQL_USER,
            password=POSTGRESQL_PASSWORD
        )
        rows = await conn.fetch("SELECT connection_name,connection_database_type FROM db_connections_table where connection_database_type='mysql' or connection_database_type='postgresql' or connection_database_type='sqlite'")
        connections = [
            {
                "connection_name": row["connection_name"],
                "connection_database_type": row["connection_database_type"]
            }
            for row in rows
        ]
        await conn.close()
        return {"connections": connections}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/connections_mongodb")
async def get_connections_mongodb():
    try:
        conn = await asyncpg.connect(
            host=POSTGRESQL_HOST,
            database=DATABASE,
            user=POSTGRESQL_USER,
            password=POSTGRESQL_PASSWORD
        )
        rows = await conn.fetch("SELECT connection_name , connection_database_type FROM db_connections_table where connection_database_type='mongodb'")
        connections = [
            {
                "connection_name": row["connection_name"],
                "connection_database_type": row["connection_database_type"]
                
            }
            for row in rows
        ]
        await conn.close()
        return {"connections": connections}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    
#this below code is for mongo db crud operations

# Allow CORS for Streamlit
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# MongoDB setup
# MONGO_URI = os.getenv("MONGO_URI", "mongodb://localhost:27017")
# client = AsyncIOMotorClient(MONGO_URI)
# db = client["test_db"]  # Change this to your DB name
# class DBConnection(BaseModel):
#     connection_name: str
#     connection_database_type: str
#     connection_host: str
#     connection_port: Union[str, int]
#     connection_username: Optional[str]
#     connection_password: Optional[str]
#     connection_database_name: str

# Pydantic model
class MONGODBOperation(BaseModel):
    conn_name: str
    collection: str
    operation: Literal["find", "insert", "update", "delete"]
    mode: Literal["one", "many"]
    query: Optional[dict] = {}
    data: Optional[Union[dict, List[dict]]] = None
    update_data: Optional[dict] = None

# Helper to clean MongoDB ObjectId
def clean_document(doc):
    if not doc:
        return None
    doc["_id"] = str(doc["_id"])
    for k, v in doc.items():
        if isinstance(v, ObjectId):
            doc[k] = str(v)
    return doc

# Main endpoint
@app.post("/mongodb-operation/")
async def mongodb_operation(op: MONGODBOperation):
    

    # Ensure the connection exists in the dictionary
    # if op.conn_name not in connected_databases:
    #     raise HTTPException(status_code=404, detail="Connection not found.")
    
    
 
    # config = connected_databases[op.conn_name]
    # conn = await asyncpg.connect(
    #     host=POSTGRESQL_HOST,
    #     database=DATABASE,
    #     user=POSTGRESQL_USER,
    #     password=POSTGRESQL_PASSWORD
    # )
    
    
        # Get the engine for the specific database connection
        # engine = get_engine(config)
    config = await get_connection_config(op.conn_name)
    manager=get_connection_manager()
    manager.add_mongo_database(config.get("name",""),build_connection_string(config),config.get("database",""))
    mongo_db = manager.get_mongo_database(op.conn_name)
    collection = mongo_db["users"] 
    # sample_doc = await mongo_db.test_collection.find_one()
    try:
        # FIND
        if op.operation == "find":
            if op.mode == "one":
                doc = await collection.find_one(op.query)
                return {"status": "success", "data": clean_document(doc)}
            else:
                docs = await collection.find(op.query).to_list(100)
                return {"status": "success", "data": [clean_document(d) for d in docs]}

        # INSERT
        elif op.operation == "insert":
            if op.mode == "one":
                result = await collection.insert_one(op.data)
                return {"status": "success", "inserted_id": str(result.inserted_id)}
            else:
                result = await collection.insert_many(op.data)
                return {"status": "success", "inserted_ids": [str(_id) for _id in result.inserted_ids]}

        # UPDATE
        elif op.operation == "update":
            if op.mode == "one":
                result = await collection.update_one(op.query, {"$set": op.update_data})
            else:
                result = await collection.update_many(op.query, {"$set": op.update_data})
            return {
                "status": "success",
                "matched_count": result.matched_count,
                "modified_count": result.modified_count
            }

        # DELETE
        elif op.operation == "delete":
            if op.mode == "one":
                result = await collection.delete_one(op.query)
            else:
                result = await collection.delete_many(op.query)
            return {"status": "success", "deleted_count": result.deleted_count}

        else:
            raise HTTPException(status_code=400, detail="Invalid operation")

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/get-active-connection-names")
def get_active_connection_names():
    manager = get_connection_manager()

    active_sql_connections = list(manager.sql_engines.keys())
    active_mongo_connections = list(manager.mongo_clients.keys())

    return {
        "active_sql_connections": active_sql_connections,
        "active_mongo_connections": active_mongo_connections
    }





# data connector end

