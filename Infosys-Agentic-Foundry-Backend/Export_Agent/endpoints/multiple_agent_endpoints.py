import os
import ast
import time
import shutil

from urllib import response
from bson import ObjectId
from langchain_openai import AzureChatOpenAI

import asyncpg

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



from typing import List, Dict, Optional, Union,Any
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


from contextlib import asynccontextmanager
from contextlib import closing
from pydantic import BaseModel, Field, validator

from src.models.model import load_model
from src.utils.secrets_handler import current_user_email
from typing import Literal

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

from src.database.database_manager import DatabaseManager, REQUIRED_DATABASES
from src.database.repositories import ( ToolRepository, 
    AgentRepository, ChatHistoryRepository
)

from src.database.services import (ToolService, AgentService, ChatService)

from database_creation import initialize_tables
from database_manager import insert_into_feedback_table

from telemetry_wrapper import logger as log, update_session_context
import asyncio
import sys
import tempfile
import json
from datetime import datetime

load_dotenv()
task_tracker: dict[str, asyncio.Task] = {}
DB_URI=os.getenv("POSTGRESQL_DATABASE_URL", "")
POSTGRESQL_HOST = os.getenv("POSTGRESQL_HOST", "")
POSTGRESQL_USER = os.getenv("POSTGRESQL_USER", "")
POSTGRESQL_PASSWORD = os.getenv("POSTGRESQL_PASSWORD", "")
DATABASE = os.getenv("DATABASE", "")

DB_URI = os.getenv("POSTGRESQL_DATABASE_URL", "")

# --- Global Instances (initialized in lifespan) ---
# These will hold the single instances of managers and services.
# They are declared globally so FastAPI's Depends can access them.
db_manager: DatabaseManager = None

# Repositories (usually not directly exposed via Depends, but used by services)

tool_repo: ToolRepository = None
agent_repo: AgentRepository = None
chat_history_repo: ChatHistoryRepository = None


# Services (these are typically exposed via Depends for endpoints)
tool_service: ToolService = None
agent_service: AgentService = None
chat_service: ChatService = None

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
    global db_manager, tool_repo, agent_repo,chat_history_repo, tool_service, agent_service, \
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
        await db_manager.connect(db_names=REQUIRED_DATABASES,
                                 min_size=3, max_size=5, # Default pool sizes
                                 db_main_min_size=5, db_main_max_size=7) # Custom sizes for main DB or agentic_workflow_as_service_database
        log.info("All database connection pools established.")

        # 4. Initialize Repositories (Pass the correct pool to each)
        # Repositories only handle raw DB operations.
        main_pool = await db_manager.get_pool('db_main')

        tool_repo = ToolRepository(pool=main_pool)
        agent_repo = AgentRepository(pool=main_pool)
        chat_history_repo = ChatHistoryRepository(pool=main_pool)
        log.info("All repositories initialized.")


        # 6. Initialize Services (Pass their required repositories and other services)
        # Services contain business logic and orchestrate repository calls.
        tool_service = ToolService(
            tool_repo=tool_repo,
            agent_repo=agent_repo # ToolService needs AgentRepository for dependency checks
        )
        agent_service = AgentService(
            agent_repo=agent_repo,
            tool_service=tool_service, # AgentService needs ToolService
            tool_repo=tool_repo

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
        # await tag_repo.create_table_if_not_exists()
        await tool_repo.create_table_if_not_exists()
        await tool_repo.save_tool_record()
        await agent_repo.create_table_if_not_exists()
        await agent_repo.save_agent_record()

        # Remaining tables
        await initialize_tables()
        log.info("All database tables checked/created.")

        asyncio.create_task(cleanup_old_files())

        log.info("Application startup complete. FastAPI is ready to serve requests.")

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



app = FastAPI(lifespan=lifespan, title="Export Agent API")
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


def get_tool_service() -> ToolService:
    """Returns the global ToolService instance."""
    return tool_service

def get_agent_service() -> AgentService:
    """Returns the global AgentService instance."""
    return agent_service

def get_chat_service() -> ChatService:
    """Returns the global ChatService instance."""
    return chat_service

class PrevSessionRequest(BaseModel):
    """
    Pydantic model representing the input request for retriving previous conversations.
    """
    agent_id: str  # agent id user is working on
    session_id: str  # session id of the user

class old_session_request(BaseModel):
    user_email: str
    agent_id: str
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

def get_specialized_inference_service(agent_type: str):
    """Return the appropriate inference service instance based on agent type."""
    if agent_type == "react_agent":
        return react_agent_inference
    if agent_type == "multi_agent":
        return multi_agent_inference # type: ignore
    if agent_type == "planner_executor_agent":
        return planner_executor_agent_inference # type: ignore
    if agent_type == "react_critic_agent":
        return react_critic_agent_inference # type: ignore
    if agent_type == "meta_agent":
        return meta_agent_inference
    if agent_type == "planner_meta_agent":
        return planner_meta_agent_inference # type: ignore
    raise HTTPException(status_code=400, detail=f"Unsupported agent type: {agent_type}")

@app.get("/fetchuser", response_model=Dict[str, Any])
async def fetch_user_data(request: Request):
    load_dotenv(override=True)
    try:
        id = str(uuid.uuid4()).replace("-","_")
        session_id = os.getenv("USER_EMAIL", "system@infosys.com")+ "_" + id
        default_user_data = {
            "user_name": os.getenv("USER_NAME", "Guest"),
            "username": os.getenv("USER_NAME", "Guest"), 
            "email": os.getenv("USER_EMAIL", "system@infosys.com"),
            "role": os.getenv("ROLE", "Developer"), 
            "session_id": session_id,
            "approval": True,
            "message": "User data fetched successfully.",
        }
        return default_user_data
    except Exception as e:
        log.error(f"Error in /fetchuser endpoint: {e}")
        raise HTTPException(status_code=500, detail="Internal server error while fetching user data.")

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
        agent_config = await react_agent_inference._get_agent_config(request.agentic_application_id)
        agent_inference = get_specialized_inference_service(agent_config["AGENT_TYPE"])
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
@app.post("/planner-executor-critic-agent/get-query-response-hitl-replanner")
async def generate_response_replanner_executor_critic_agent_main(fastapi_request: Request, request: AgentInferenceHITLRequest):
    """
    Handles the inference request for the Planner-Executor-Critic-replanner agent.

    Args:
        request (ReplannerAgentInferenceRequest): The request object containing the query, session ID, and other parameters.

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
    planner_meta_agent_inference: PlannerMetaAgentInference = get_specialized_inference_service("planner_meta_agent")
    response = await planner_meta_agent_inference.run(request)
    update_session_context(agent_id='Unassigned',session_id='Unassigned',
                           model_used='Unassigned',user_query='Unassigned',response='Unassigned')
    return response

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
    # current_user_email.set(request.session_id.split("_")[0])
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

    agent_config = await react_agent_inference._get_agent_config(request.agentic_application_id)
    agent_inference = get_specialized_inference_service(agent_config["AGENT_TYPE"])

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

@app.post("/planner-executor-agent/get-query-response-hitl-replanner")
async def generate_response_replanner_executor_agent_main(fastapi_request: Request, request: AgentInferenceHITLRequest):
    """
    Handles the inference request for the Planner-Executor-Critic-replanner agent.

    Args:
        request (ReplannerAgentInferenceRequest): The request object containing the query, session ID, and other parameters.

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
    meta_agent_inference = get_specialized_inference_service("meta_agent")
    response = await meta_agent_inference.run(inference_request=request)
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

@app.get('/get-models')
async def get_available_models(fastapi_request: Request):
    #changed
    user_id = fastapi_request.cookies.get("user_id")
    user_session = fastapi_request.cookies.get("user_session")
    update_session_context(user_session=user_session, user_id=user_id)
    data = ["gpt4-8k","gpt-4o-mini","gpt-4o","gpt-35-turbo","gpt-4o-2","gpt-4o-3"]
    return JSONResponse(content={"models": data})

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
