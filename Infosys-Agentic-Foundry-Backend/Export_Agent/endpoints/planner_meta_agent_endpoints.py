import os
import ast
import time
import shutil

from urllib import response
from bson import ObjectId
from langchain_openai import AzureChatOpenAI

import asyncpg
import sqlite3
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



from typing import List, Dict, Optional, Union,Any,Literal
from fastapi import (
    FastAPI, UploadFile, File, HTTPException, Request, Response, WebSocket, WebSocketDisconnect, Query,
    BackgroundTasks, Depends, Form
)
from pathlib import Path

from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, FileResponse
from fastapi.encoders import jsonable_encoder

from langchain_google_genai import GoogleGenerativeAIEmbeddings
from langchain_community.vectorstores import FAISS
from langchain_community.document_loaders import TextLoader
from langchain.text_splitter import CharacterTextSplitter
from langchain_pymupdf4llm import PyMuPDF4LLMLoader
from langchain_community.embeddings import HuggingFaceEmbeddings
from sentence_transformers import CrossEncoder
from contextlib import asynccontextmanager
from contextlib import closing
from pydantic import BaseModel, Field, validator
from exportagent.src.models.model import load_model

from typing import Literal
from exportagent.groundtruth import evaluate_ground_truth_file
from exportagent.src.models.model_service import ModelService
from exportagent.src.inference.centralized_agent_inference import CentralizedAgentInference
from exportagent.src.inference.inference_utils import InferenceUtils
from exportagent.src.inference.base_agent_inference import BaseAgentInference
from exportagent.src.inference.react_agent_inference import ReactAgentInference
from exportagent.src.inference.planner_meta_agent_inference import PlannerMetaAgentInference
from exportagent.src.schemas import AgentInferenceRequest,ChatSessionRequest,TempAgentInferenceRequest

from exportagent.src.database.database_manager import DatabaseManager, REQUIRED_DATABASES
from exportagent.src.database.repositories import ( McpToolRepository,ToolRepository,
    AgentRepository, ChatHistoryRepository,FeedbackLearningRepository,EvaluationDataRepository,ToolEvaluationMetricsRepository,AgentEvaluationMetricsRepository
)
from exportagent.src.database.services import (McpToolService,ToolService, AgentService, AgentServiceUtils,ChatService,FeedbackLearningService, EvaluationService)

from exportagent.telemetry_wrapper import logger as log, update_session_context
import asyncio
import sys
import tempfile
import json
from datetime import datetime
from exportagent.src.database.core_evaluation_service import CoreEvaluationService
from exportagent.MultiDBConnection_Manager import MultiDBConnectionRepository, get_connection_manager
from exportagent.src.utils.stream_sse import SSEManager
from phoenix.otel import register
from phoenix.trace import using_project
load_dotenv()
task_tracker: dict[str, asyncio.Task] = {}
DB_URI=os.getenv("POSTGRESQL_DATABASE_URL", "")
POSTGRESQL_HOST = os.getenv("POSTGRESQL_HOST", "")
POSTGRESQL_USER = os.getenv("POSTGRESQL_USER", "")
POSTGRESQL_PASSWORD = os.getenv("POSTGRESQL_PASSWORD", "")
DATABASE = os.getenv("DATABASE", "")

DB_URI = os.getenv("POSTGRESQL_DATABASE_URL", "")
os.environ["PHOENIX_COLLECTOR_ENDPOINT"] = os.getenv("PHOENIX_COLLECTOR_ENDPOINT")
os.environ["PHOENIX_GRPC_PORT"] = os.getenv("PHOENIX_GRPC_PORT",'50051')
os.environ["PHOENIX_SQL_DATABASE_URL"] = os.getenv("PHOENIX_SQL_DATABASE_URL")
# --- Global Instances (initialized in lifespan) ---
# These will hold the single instances of managers and services.
# They are declared globally so FastAPI's Depends can access them.
db_manager: DatabaseManager = None

# Repositories (usually not directly exposed via Depends, but used by services)
tool_repo: ToolRepository = None
agent_repo: AgentRepository = None
chat_history_repo: ChatHistoryRepository = None
feedback_learning_repo: FeedbackLearningRepository = None
evaluation_data_repo: EvaluationDataRepository = None
tool_evaluation_metrics_repo: ToolEvaluationMetricsRepository = None
agent_evaluation_metrics_repo: AgentEvaluationMetricsRepository = None
multi_db_connection_manager: MultiDBConnectionRepository = None
mcp_tool_repo: McpToolRepository = None
# Services (these are typically exposed via Depends for endpoints)
model_service: ModelService = None
tool_service: ToolService = None
agent_service: AgentService = None
chat_service: ChatService = None
feedback_learning_service: FeedbackLearningService = None
evaluation_service: EvaluationService = None
core_evaluation_service: CoreEvaluationService = None
embedding_model: HuggingFaceEmbeddings = None
cross_encoder: CrossEncoder = None
# Inference
inference_utils: InferenceUtils = None
planner_meta_agent_inference: PlannerMetaAgentInference = None
react_agent_inference: ReactAgentInference = None
centralized_agent_inference: CentralizedAgentInference = None

if sys.platform.startswith("win"):
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Manages the startup and shutdown events for the FastAPI application.
    - On startup: Initializes database connections, creates tables, and sets up service instances.
    - On shutdown: Closes database connections.
    """
    global mcp_tool_repo,mcp_tool_service,embedding_model,cross_encoder,db_manager, tool_repo, agent_repo,chat_history_repo, tool_service, agent_service,multi_db_connection_manager, \
           chat_service, inference_utils, react_agent_inference, planner_meta_agent_inference,feedback_learning_repo, \
           evaluation_data_repo, tool_evaluation_metrics_repo, agent_evaluation_metrics_repo,model_service,\
           feedback_learning_service, evaluation_service, core_evaluation_service,centralized_agent_inference

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
        mcp_tool_repo = McpToolRepository(pool=main_pool)
        feedback_learning_repo = FeedbackLearningRepository(pool=main_pool)
        evaluation_data_repo = EvaluationDataRepository(pool=main_pool)
        tool_evaluation_metrics_repo = ToolEvaluationMetricsRepository(pool=main_pool)
        agent_evaluation_metrics_repo = AgentEvaluationMetricsRepository(pool=main_pool)
        multi_db_connection_manager = MultiDBConnectionRepository(pool=main_pool)
        log.info("All repositories initialized.")

        app.state.sse_manager = SSEManager()
        # 6. Initialize Services (Pass their required repositories and other services)
        # Services contain business logic and orchestrate repository calls.
        model_service = ModelService()
        mcp_tool_service = McpToolService( # Initialize McpToolService
            mcp_tool_repo=mcp_tool_repo,
            agent_repo=agent_repo,
            mcp_runtime_files_dir=os.getenv("MCP_RUNTIME_FILES_DIR", "mcp_runtime_files")
        )
        tool_service = ToolService(
            tool_repo=tool_repo,
            model_service=model_service,
            agent_repo=agent_repo ,# ToolService needs AgentRepository for dependency checks
            mcp_tool_service=mcp_tool_service # ToolService needs McpToolService for MCP tools
        )
        tool_service = ToolService(
            tool_repo=tool_repo,
            model_service=model_service,
            agent_repo=agent_repo # ToolService needs AgentRepository for dependency checks
        )
        agent_service_utils = AgentServiceUtils(
            agent_repo=agent_repo,
            tool_service=tool_service, # AgentService needs ToolService
            model_service=model_service
        )
        agent_service = AgentService(agent_service_utils=agent_service_utils)
        chat_service = ChatService(chat_history_repo=chat_history_repo)
        feedback_learning_service = FeedbackLearningService(
            feedback_learning_repo=feedback_learning_repo,
            agent_service=agent_service
        )
        evaluation_service = EvaluationService(
            evaluation_data_repo=evaluation_data_repo,
            tool_evaluation_metrics_repo=tool_evaluation_metrics_repo,
            agent_evaluation_metrics_repo=agent_evaluation_metrics_repo,
            tool_service=tool_service,
            agent_service=agent_service
        )

        log.info("All services initialized.")
        embedding_model = HuggingFaceEmbeddings(
            model_name="intfloat/e5-base-v2",
            model_kwargs={"device": "cpu"}
        )
        cross_encoder = CrossEncoder("cross-encoder/stsb-roberta-base")
        log.info("Embeddings and Encoders initialized.")
        # 7. Initialize Inference Services
        inference_utils = InferenceUtils(
            chat_service=chat_service,
            tool_service=tool_service,
            agent_service=agent_service,
            model_service=model_service,
            feedback_learning_service=feedback_learning_service,
            evaluation_service=evaluation_service,
            embedding_model=embedding_model,
            cross_encoder=cross_encoder
        ) 
        planner_meta_agent_inference = PlannerMetaAgentInference(
            inference_utils=inference_utils
        )
        react_agent_inference = ReactAgentInference(
            inference_utils=inference_utils
        )
        agent_handlers_for_this_export = {
        "react_agent": react_agent_inference,
        "planner_meta_agent": planner_meta_agent_inference
        }
        centralized_agent_inference = CentralizedAgentInference(
            agent_handlers=agent_handlers_for_this_export
        )
        core_evaluation_service = CoreEvaluationService(
            evaluation_service=evaluation_service,
            centralized_agent_inference=centralized_agent_inference,
            model_service=model_service
        )


        # 8. Create Tables (if they don't exist)
        # Call create_tables_if_not_exists for each service/repository that manages tables.
        # Order matters for foreign key dependencies.
        await tool_repo.create_table_if_not_exists()
        await tool_repo.save_tool_record()
        await agent_repo.create_table_if_not_exists()
        await agent_repo.save_agent_record()

        # LLM Models
        await model_service.load_all_models_into_cache()
        await chat_history_repo.create_agent_conversation_summary_table()
        await multi_db_connection_manager.create_db_connections_table_if_not_exists()

        # Feedback Learning tables
        await feedback_learning_repo.create_tables_if_not_exists()

        # Evaluation Tables
        await evaluation_service.create_evaluation_tables_if_not_exists()
       

        log.info("All database tables checked/created.")

        # 9. Running necessary data migrations/fixes
        # await tool_service.fix_tool_agent_mapping_for_meta_agents() # Ensure FK is dropped
        # log.info("Database data migrations/fixes completed.")

        # await assign_general_tag_to_untagged_items()
        await feedback_learning_repo.migrate_agent_ids_to_hyphens()
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



app = FastAPI(lifespan=lifespan, title="Export Agent API")



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

def get_model_service() -> ModelService:
    """Returns the global ModelService instance."""
    if model_service is None:
        raise RuntimeError("ModelService not initialized yet.")
    return model_service

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
        return react_agent_inference # type: ignore
    if agent_type == "multi_agent":
        return multi_agent_inference # type: ignore
    if agent_type == "planner_executor_agent":
        return planner_executor_agent_inference # type: ignore
    if agent_type == "react_critic_agent":
        return react_critic_agent_inference # type: ignore
    if agent_type == "meta_agent":
        return meta_agent_inference # type: ignore
    if agent_type == "planner_meta_agent":
        return planner_meta_agent_inference # type: ignore
    raise HTTPException(status_code=400, detail=f"Unsupported agent type: {agent_type}")

def get_feedback_learning_service() -> FeedbackLearningService:
    """Returns the global FeedbackLearningService instance."""
    return feedback_learning_service

def get_specialized_inference_service(agent_type: str) -> BaseAgentInference:
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
        return meta_agent_inference # type: ignore
    if agent_type == "planner_meta_agent":
        return planner_meta_agent_inference # type: ignore
    raise HTTPException(status_code=400, detail=f"Unsupported agent type: {agent_type}")

def get_centralized_agent_inference() -> CentralizedAgentInference:
    """Returns the global CentralizedAgentInference instance."""
    if centralized_agent_inference is None:
        raise RuntimeError("CentralizedAgentInference not initialized yet.")
    return centralized_agent_inference

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

async def run_agent_inference_endpoint(
                        request: Request,
                        inference_request: AgentInferenceRequest,
                        inference_service: CentralizedAgentInference = Depends(get_centralized_agent_inference),
                        feedback_learning_service: FeedbackLearningService = Depends(get_feedback_learning_service)
                    ):
    """
    
    API endpoint to run agent inference.

    This is a unified endpoint that handles various agent types and HITL scenarios.

    Parameters:
    
    - request: The FastAPI Request object.
    - inference_request: Pydantic model containing all inference parameters.
    - inference_service: Dependency-injected CentralizedAgentInference instance.
    - feedback_learning_service: Dependency-injected FeedbackLearningService instance.

    Returns:
    - Dict[str, Any]: A dictionary with the agent's response.
    """
    user_id = request.cookies.get("user_id")
    user_session = request.cookies.get("user_session")
    update_session_context(user_session=user_session, user_id=user_id)
    # sse_manager = request.app.state.sse_manager
    session_id = inference_request.session_id
    log.info(f"[{session_id}] Received new request for {inference_request.agentic_application_id}")
    current_user_email.set(session_id.split("_")[0])

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
        agent_id=inference_request.agentic_application_id,
        session_id=session_id,
        model_used=inference_request.model_name,
        user_query=inference_request.query,
        response="Processing..."
    )

    log.info(f"[{session_id}] Starting agent inference...")

    # Define and create the inference task
    async def do_inference():
        try:
            result = await inference_service.run(inference_request)
            log.info(f"[{session_id}] Inference completed.")
            return result
        except asyncio.CancelledError:
            log.warning(f"[{session_id}] Task was cancelled during execution.")
            raise

    new_task = asyncio.create_task(do_inference())
    task_tracker[session_id] = new_task

    try:
        response = await new_task
        if inference_request.plan_verifier_flag:
            try:
                final_response = "\n".join(i for i in response["plan"])
                steps = ""
                old_response = "\n".join(i for i in inference_request.prev_response["plan"])
                old_steps = ""
                await feedback_learning_service.save_feedback(
                    agent_id=inference_request.agentic_application_id,
                    query=inference_request.query,
                    old_final_response= old_response,
                    old_steps=old_steps,
                    new_final_response=final_response,
                    feedback=inference_request.plan_feedback, 
                    new_steps=steps
                )
                log.info("Data saved for future learnings.")
            except Exception as e:
                log.info("Could not save data for future learnings.")

    except asyncio.CancelledError:
        raise HTTPException(status_code=499, detail="Request was cancelled")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Internal Server Error: {str(e)}")

    update_session_context(agent_id='Unassigned', session_id='Unassigned', model_used='Unassigned', user_query='Unassigned', response='Unassigned')
    if session_id in task_tracker and task_tracker[session_id].done():
        del task_tracker[session_id]
        log.info(f"[{session_id}] Task completed and removed from tracker.")

    return response
@app.post("/planner-meta-agent/get-query-response")
@app.post("/meta-agent/get-query-response")
@app.post("/get-query-response")
async def temporary_get_agent_response_endpoint(
                                fastapi_request: Request,
                                request: TempAgentInferenceRequest,
                                agent_inference: CentralizedAgentInference = Depends(get_centralized_agent_inference)
                            ):
    inference_request = AgentInferenceRequest(
        query=request.query,
        agentic_application_id=request.agentic_application_id,
        session_id=request.session_id,
        model_name=request.model_name,
        reset_conversation=request.reset_conversation,
        tool_verifier_flag=request.interrupt_flag,
        tool_feedback=request.feedback,
        prev_response=request.prev_response,
        knowledgebase_name=request.knowledgebase_name
    )
    return await run_agent_inference_endpoint(
        request=fastapi_request,
        inference_request=inference_request,
        inference_service=agent_inference,
        feedback_learning_service=None
    )

async def send_feedback_endpoint(
                    request: Request,
                    feedback_type: Literal["like", "regenerate", "submit_feedback"],
                    inference_request: AgentInferenceRequest,
                    chat_service: ChatService = Depends(get_chat_service),
                    inference_service: CentralizedAgentInference = Depends(get_centralized_agent_inference),
                    feedback_learning_service: FeedbackLearningService = Depends(get_feedback_learning_service),
                    model_service: ModelService = Depends(get_model_service)
                ):
    """
    API endpoint to handle like/unlike feedback for the latest message.

    Parameters:
    - request: The FastAPI Request object.
    - feedback_type: The type of feedback ('like', 'regenerate', 'submit_feedback').
    - inference_request: Pydantic model containing agent_id and session_id.
    - chat_service: Dependency-injected ChatService instance.
    - inference_service: Dependency-injected CentralizedAgentInference instance.
    - feedback_learning_service: Dependency-injected FeedbackLearningService instance.

    Returns:
    - Dict[str, str]: A message indicating the status of the like/unlike operation.
    """
    async def process_feedback_in_background(
        llm,
        feedback_prompt, 
        feedback_learning_service,
        agent_id, original_query, old_response, old_steps,
        final_response, user_feedback, steps
    ):
        try:
            # Run the LLM invocation asynchronously
            lesson_response = await llm.ainvoke(feedback_prompt)
            lesson = lesson_response.content
            
            # Save feedback asynchronously
            await feedback_learning_service.save_feedback(
                agent_id=agent_id,
                query=original_query,
                old_final_response=old_response,
                old_steps=old_steps,
                new_final_response=final_response,
                feedback=user_feedback, 
                new_steps=steps,
                lesson=lesson
            )
            log.info("Data saved for future learnings in background.")
        except Exception as e:
            log.error(f"Background feedback processing error: {str(e)}")
        
        
    user_id = request.cookies.get("user_id")
    user_session = request.cookies.get("user_session")
    update_session_context(user_session=user_session, user_id=user_id)

    if feedback_type == "like":
        # Call ChatService to handle like/unlike
        result = await chat_service.handle_like_feedback_message(
            agentic_application_id=inference_request.agentic_application_id,
            session_id=inference_request.session_id
        )
        update_session_context(user_session="Unassigned", user_id="Unassigned")
        return result

    current_user_email.set(inference_request.session_id.split("_")[0])

    # Store original query for feedback logging
    original_query = inference_request.query
    user_feedback = inference_request.final_response_feedback

    inference_request.reset_conversation = False
    # Ensure other feedback fields are cleared for this specific call
    inference_request.is_plan_approved = None
    inference_request.plan_feedback = None
    inference_request.tool_feedback = None

    if feedback_type == "regenerate":
        # Modify inference_request for regeneration
        inference_request.query = "[regenerate:][:regenerate]" # Special query for regeneration
    elif feedback_type == "submit_feedback":
        # Modify inference_request for feedback processing
        inference_request.query = f"[feedback:]{user_feedback}[:feedback]" # Special query for feedback
    else:
        raise HTTPException(status_code=400, detail="Invalid feedback type.")

    try:
        response = await inference_service.run(inference_request)

        # Save feedback for learning
        try:
            final_response = response["response"]
            steps = response["executor_messages"][-1]["agent_steps"]
            if inference_request.prev_response:
                old_response = inference_request.prev_response["response"]
                old_steps = inference_request.prev_response["executor_messages"][-1]["agent_steps"]
            else:
                old_response = ""
                old_steps = ""
            
            # llm = model_service.get_llm_model(inference_request.model_name)
            llm = await model_service.get_llm_model(inference_request.model_name)
                        
            feedback_prompt = f"""

            You are given four fields of information:  

            1. **{final_response}** - The final response or message to be evaluated.  
            2. **{steps}** - The detailed step-by-step breakdown of the recent conversation.  
            3. **{old_response}** - The older AI response to the same context.  
            4. **{old_steps}** - The step-by-step breakdown for the old response.  

            ### Task:
            Read and understand all four fields together. Then produce a short, **concise 2-3 line key take aways** explaining: 
            - what this agent can learn from this.
            - Response should be in first person

            ### Guidelines:
            - Be factual and clear.  
            - Avoid unnecessary details.  
            - Capture the **core purpose** of the interaction and notable changes from feedback.  

            **Important:** Return *only* the concise summary — no explanations of how you derived it.

            """
            
            asyncio.create_task(
                process_feedback_in_background(
                    llm, feedback_prompt, feedback_learning_service,
                    inference_request.agentic_application_id, original_query,
                    old_response, old_steps, final_response, user_feedback, steps
                )
            )
            log.info("Feedback learning process started in background.")
            log.info("Data saved for future learnings.")
        except Exception as e:
            log.info("Could not save data for future learnings.")

        update_session_context(agent_id='Unassigned', session_id='Unassigned', model_used='Unassigned', user_query='Unassigned', response='Unassigned')
        return response

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"An error occurred while processing the request: {str(e)}")


@app.post("/react-agent/get-feedback-response/{feedback}")
async def temporary_get_feedback_response_endpoint(
                            fastapi_request: Request,
                            feedback: str,
                            request: TempAgentInferenceRequest,
                            chat_service: ChatService = Depends(get_chat_service),
                            agent_inference: CentralizedAgentInference = Depends(get_centralized_agent_inference),
                            feedback_learning_service: FeedbackLearningService = Depends(get_feedback_learning_service)
                        ):
    if feedback == "feedback":
        feedback = "submit_feedback"
    inference_request = AgentInferenceRequest(
        query=request.query,
        agentic_application_id=request.agentic_application_id,
        session_id=request.session_id,
        model_name=request.model_name,
        reset_conversation=request.reset_conversation,
        final_response_feedback=request.feedback,
        prev_response=request.prev_response,
        knowledgebase_name=request.knowledgebase_name
    )
    return await send_feedback_endpoint(
        request=fastapi_request,
        feedback_type=feedback,
        inference_request=inference_request,
        chat_service=chat_service,
        inference_service=agent_inference,
        feedback_learning_service=feedback_learning_service
    )

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

@app.delete("/react-agent/clear-chat-history")
@app.delete("/clear-chat-history")
async def clear_chat_history_endpoint(request: Request, chat_session_request: ChatSessionRequest, chat_service: ChatService = Depends(get_chat_service)):
    """
    API endpoint to clear the chat history for a session.

    Parameters:
    - request: The FastAPI Request object.
    - chat_session_request: Pydantic model containing agent_id and session_id.
    - chat_service: Dependency-injected ChatService instance.

    Returns:
    - Dict[str, Any]: A status dictionary indicating the result of the operation.
    """
    user_id = request.cookies.get("user_id")
    user_session = request.cookies.get("user_session")
    update_session_context(user_session=user_session, user_id=user_id)
    
    result = await chat_service.delete_session(
        agentic_application_id=chat_session_request.agent_id,
        session_id=chat_session_request.session_id
    )
    if result.get("status") == "error":
        raise HTTPException(status_code=500, detail=result.get("message"))
    return result

@app.get('/utility/get/version')
def get_version(fastapi_request: Request):
    #changed
    user_id = fastapi_request.cookies.get("user_id")
    user_session = fastapi_request.cookies.get("user_session")
    update_session_context(user_session=user_session, user_id=user_id)
    return "1.3.1"

@app.get('/utility/get/models')
async def get_available_models(fastapi_request: Request, model_service: ModelService = Depends(get_model_service)):
    #changed
    user_id = fastapi_request.cookies.get("user_id")
    user_session = fastapi_request.cookies.get("user_session")
    update_session_context(user_session=user_session, user_id=user_id)
    try:
        # Use 'with' for automatic cleanup
        data = await model_service.get_all_available_model_names()
        log.debug(f"Models retrieved successfully: {data}")
        return JSONResponse(content={"models": data})

    except asyncpg.PostgresError as e:
        log.error(f"Database error while fetching models: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Database error: {str(e)}")

    except Exception as e:
        # Handle other unforeseen errors
        log.error(f"Unexpected error while fetching models: {str(e)}")
        raise HTTPException(status_code=500, detail=f"An error occurred: {str(e)}")

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

@app.get("/agents/get/details-for-chat-interface")
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


@app.get("/feedback-learning/get/approvals-list")
async def get_approvals_list(fastapi_request: Request, feedback_learning_service: FeedbackLearningService = Depends(get_feedback_learning_service)):
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

    approvals = await feedback_learning_service.get_agents_with_feedback()
    if not approvals:
        raise HTTPException(status_code=404, detail="No approvals found")
    return approvals

@app.get("/feedback-learning/get/approvals-by-agent/{agent_id}")
async def get_approval_by_id(agent_id: str, fastapi_request: Request, feedback_learning_service: FeedbackLearningService = Depends(get_feedback_learning_service)):
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

    approval = await feedback_learning_service.get_all_approvals_for_agent(agent_id=agent_id)
    if not approval:
        raise HTTPException(status_code=404, detail="Approval not found")
    return approval

@app.get("/feedback-learning/get/responses-data/{response_id}")
async def get_responses_data_endpoint(response_id, fastapi_request: Request, feedback_learning_service: FeedbackLearningService = Depends(get_feedback_learning_service)):
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

    approvals = await feedback_learning_service.get_feedback_details_by_response_id(response_id=response_id)
    if not approvals:
        raise HTTPException(status_code=404, detail="No Response found")
    return approvals

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

@app.put("/feedback-learning/update/approval-response")
async def update_approval_response(
                                fastapi_request: Request,
                                request: ApprovalRequest,
                                feedback_learning_service: FeedbackLearningService = Depends(get_feedback_learning_service)
                            ):
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

    response = await feedback_learning_service.update_feedback_status(
        response_id=request.response_id,
        update_data={
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
#----------------FEEDBACK LEARNING END-----------------
# #-----------------DATA CONNECTOR START-----------------
def get_multi_db_connection_manager() -> MultiDBConnectionRepository:
    """Returns the global MultiDBConnectionManager instance."""
    if multi_db_connection_manager is None:
        raise RuntimeError("MultiDBConnectionManager not initialized yet.")
    return multi_db_connection_manager

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
                conn.execute(text(f'CREATE DATABASE "{db_name}"'))
            return

    if db_type == "mysql":
        config_copy["database"] = ""
        engine = create_engine(await _build_connection_string_helper(config_copy))
        with engine.connect() as conn:
            with conn.begin(): # Use begin() context to control transactions
                conn.execute(text(f"CREATE DATABASE IF NOT EXISTS `{db_name}`"))
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

# @app.post("/connect")
@app.post("/data-connector/connect")
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
        sql_file: UploadFile = File(None),
        db_connection_manager: MultiDBConnectionRepository = Depends(get_multi_db_connection_manager)
    ):
    """
    API endpoint to connect to a database and optionally save its configuration.

    Parameters:
    - request: The FastAPI Request object.
    - name: Unique name for the connection.
    - db_type: Type of database.
    - host, port, username, password, database: Connection details.
    - flag_for_insert_into_db_connections_table: Flag to save config to DB.
    - sql_file: Optional SQL file for SQLite.
    - db_connection_manager: Dependency-injected MultiDBConnectionRepository.

    Returns:
    - Dict[str, Any]: Status message.
    """
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


@app.post("/data-connector/disconnect")
async def disconnect_database_endpoint(request: Request, disconnect_request: DBDisconnectRequest, db_connection_manager: MultiDBConnectionRepository = Depends(get_multi_db_connection_manager)):
    """
    API endpoint to disconnect from a database.

    Parameters:
    - request: The FastAPI Request object.
    - disconnect_request: Pydantic model containing disconnection details.
    - db_connection_manager: Dependency-injected MultiDBConnectionRepository.

    Returns:
    - Dict[str, str]: Status message.
    """
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
                return {"message": f"Disconnected MongoDB connection '{name}' successfully"}
            else:
                return {"message": f"MongoDB connection '{name}' was not active "}
 
        else:  # SQL
            if name in active_sql_connections:
                manager.dispose_sql_engine(name)
                return {"message": f"Disconnected SQL connection '{name}' successfully "}
            else:
                return {"message": f"SQL connection '{name}' was not active"}
 
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error while disconnecting: {str(e)}")


@app.post("/data-connector/generate-query")
async def generate_query_endpoint(request: Request, query_request: QueryGenerationRequest, model_service: ModelService = Depends(get_model_service)):
    """
    API endpoint to generate a database query from natural language.

    Parameters:
    - request: The FastAPI Request object.
    - query_request: Pydantic model containing database type and natural language query.
    - model_service: Dependency-injected ModelService instance.

    Returns:
    - Dict[str, str]: The generated database query.
    """
    user_id = request.cookies.get("user_id")
    user_session = request.cookies.get("user_session")
    update_session_context(user_session=user_session, user_id=user_id)

    try:
        llm = await model_service.get_llm_model(model_name="gpt-4o", temperature=0.7)
        
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


@app.post("/data-connector/run-query")
async def run_query_endpoint(request: Request, query_execution_request: QueryExecutionRequest, db_connection_manager: MultiDBConnectionRepository = Depends(get_multi_db_connection_manager)):
    """
    API endpoint to run a database query on a connected database.

    Parameters:
    - request: The FastAPI Request object.
    - query_execution_request: Pydantic model containing connection name and query.
    - db_connection_manager: Dependency-injected MultiDBConnectionRepository.

    Returns:
    - Dict[str, Any]: Query results or status message.
    """
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


@app.get("/data-connector/connections")
async def get_connections_endpoint(request: Request, db_connection_manager: MultiDBConnectionRepository = Depends(get_multi_db_connection_manager)):
    """
    API endpoint to retrieve all saved database connections.

    Parameters:
    - request: The FastAPI Request object.
    - db_connection_manager: Dependency-injected MultiDBConnectionRepository.

    Returns:
    - Dict[str, Any]: A dictionary containing all saved connections.
    """
    user_id = request.cookies.get("user_id")
    user_session = request.cookies.get("user_session")
    update_session_context(user_session=user_session, user_id=user_id)
    return await db_connection_manager.get_connections()
    

@app.get("/data-connector/connection/{connection_name}")
async def get_connection_config_endpoint(request: Request, connection_name: str, db_connection_manager: MultiDBConnectionRepository = Depends(get_multi_db_connection_manager)):
    """
    API endpoint to retrieve the configuration of a specific database connection.

    Parameters:
    - request: The FastAPI Request object.
    - connection_name: The name of the connection.
    - db_connection_manager: Dependency-injected MultiDBConnectionRepository.

    Returns:
    - Dict[str, Any]: The connection configuration.
    """
    user_id = request.cookies.get("user_id")
    user_session = request.cookies.get("user_session")
    update_session_context(user_session=user_session, user_id=user_id)
    return await db_connection_manager.get_connection_config(connection_name)


@app.get("/data-connector/connections/sql")
async def get_sql_connections_endpoint(request: Request, db_connection_manager: MultiDBConnectionRepository = Depends(get_multi_db_connection_manager)):
    """
    API endpoint to retrieve all saved SQL database connections.

    Parameters:
    - request: The FastAPI Request object.
    - db_connection_manager: Dependency-injected MultiDBConnectionRepository.

    Returns:
    - Dict[str, Any]: A dictionary containing all saved SQL connections.
    """
    user_id = request.cookies.get("user_id")
    user_session = request.cookies.get("user_session")
    update_session_context(user_session=user_session, user_id=user_id)
    return await db_connection_manager.get_connections_sql()


@app.get("/data-connector/connections/mongodb")
async def get_mongodb_connections_endpoint(request: Request, db_connection_manager: MultiDBConnectionRepository = Depends(get_multi_db_connection_manager)):
    """
    API endpoint to retrieve all saved MongoDB connections.

    Parameters:
    - request: The FastAPI Request object.
    - db_connection_manager: Dependency-injected MultiDBConnectionRepository.

    Returns:
    - Dict[str, Any]: A dictionary containing all saved MongoDB connections.
    """
    user_id = request.cookies.get("user_id")
    user_session = request.cookies.get("user_session")
    update_session_context(user_session=user_session, user_id=user_id)
    return await db_connection_manager.get_connections_mongodb()


@app.post("/data-connector/mongodb-operation/")
async def mongodb_operation_endpoint(request: Request, mongo_op_request: MONGODBOperation, db_connection_manager: MultiDBConnectionRepository = Depends(get_multi_db_connection_manager)):
    """
    API endpoint to perform MongoDB operations.

    Parameters:
    - request: The FastAPI Request object.
    - mongo_op_request: Pydantic model containing MongoDB operation details.
    - db_connection_manager: Dependency-injected MultiDBConnectionRepository.

    Returns:
    - Dict[str, Any]: Operation results.
    """
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


@app.get("/data-connector/get/active-connection-names")
async def get_active_connection_names_endpoint(request: Request, db_connection_manager: MultiDBConnectionRepository = Depends(get_multi_db_connection_manager)):
    """
    API endpoint to retrieve names of currently active database connections.

    Parameters:
    - request: The FastAPI Request object.
    - db_connection_manager: Dependency-injected MultiDBConnectionRepository.

    Returns:
    - Dict[str, List[str]]: A dictionary categorizing active connection names by type.
    """
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
#-----------------DATA CONNECTOR END-----------------

#-----------------EVALUATION METRICS START-----------------
class GroundTruthEvaluationRequest(BaseModel):
    model_name: str
    agent_type: str
    agent_name: str
    agentic_application_id: str
    session_id: str
    use_llm_grading: Optional[bool] = False

def get_core_evaluation_service() -> CoreEvaluationService:
    """Returns the global CoreEvaluationService instance."""
    if core_evaluation_service is None:
        raise RuntimeError("CoreEvaluationService not initialized yet.")
    return core_evaluation_service
def get_evaluation_service() -> EvaluationService:
    """Returns the global EvaluationService instance."""
    if evaluation_service is None:
        raise RuntimeError("EvaluationService not initialized yet.")
    return evaluation_service

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

@app.post('/evaluate')
async def evaluate(
            fastapi_request: Request,
            evaluating_model1,
            evaluating_model2,
            core_evaluation_service: CoreEvaluationService = Depends(get_core_evaluation_service)
        ):
    user_id = fastapi_request.cookies.get("user_id")
    user_session = fastapi_request.cookies.get("user_session")
    update_session_context(user_session=user_session, user_id=user_id)
    register(
            project_name='evaluation-metrics',
            auto_instrument=True,
            set_global_tracer_provider=False,
            batch=True
        )
    with using_project('evaluation-metrics'):
        return await core_evaluation_service.process_unprocessed_evaluations(
                model1=evaluating_model1,
                model2=evaluating_model2
            )
# @app.get("/evaluation/get/data")
@app.get("/evaluations")
async def get_evaluation_data(
        fastapi_request: Request,
        agent_names: Optional[List[str]] = Query(default=None),
        page: int = Query(default=1, ge=1),
        limit: int = Query(default=10, ge=1, le=100),
        evaluation_service: EvaluationService = Depends(get_evaluation_service)
    ):
    user_id = fastapi_request.cookies.get("user_id")
    user_session = fastapi_request.cookies.get("user_session")
    update_session_context(user_session=user_session, user_id=user_id)

    parsed_names = parse_agent_names(agent_names)
    data = await evaluation_service.get_evaluation_data(parsed_names, page, limit)
    if not data:
        raise HTTPException(status_code=404, detail="No evaluation data found")
    return data


# @app.get("/evaluation/get/agent-metrics")
@app.get("/agent-metrics")
async def get_agent_metrics(
        fastapi_request: Request,
        agent_names: Optional[List[str]] = Query(default=None),
        page: int = Query(default=1, ge=1),
        limit: int = Query(default=10, ge=1, le=100),
        evaluation_service: EvaluationService = Depends(get_evaluation_service)
    ):
    user_id = fastapi_request.cookies.get("user_id")
    user_session = fastapi_request.cookies.get("user_session")
    update_session_context(user_session=user_session, user_id=user_id)

    parsed_names = parse_agent_names(agent_names)
    data = await evaluation_service.get_agent_metrics(parsed_names, page, limit)
    if not data:
        raise HTTPException(status_code=404, detail="No agent metrics found")
    return data


# @app.get("/evaluation/get/tool-metrics")
@app.get("/tool-metrics")
async def get_tool_metrics(
        fastapi_request: Request,
        agent_names: Optional[List[str]] = Query(default=None),
        page: int = Query(default=1, ge=1, description="Page number (starts from 1)"),
        limit: int = Query(default=10, ge=1, le=100, description="Number of records per page (max 100)"),
        evaluation_service: EvaluationService = Depends(get_evaluation_service)
    ):
    user_id = fastapi_request.cookies.get("user_id")
    user_session = fastapi_request.cookies.get("user_session")
    update_session_context(user_session=user_session, user_id=user_id)

    parsed_names = parse_agent_names(agent_names)
    data = await evaluation_service.get_tool_metrics(parsed_names, page, limit)
    if not data:
        raise HTTPException(status_code=404, detail="No tool metrics found")
    return data
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


# @app.post("/evaluation/upload-and-evaluate")
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

        #  Return the Excel file as response with custom headers
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


#-----------------EVALUATION METRICS END-----------------
@app.get("/chat/auto-suggest-agent-queries")
async def auto_suggest_agent_queries_endpoint(fastapi_request: Request, agentic_application_id:str, user_email:str, chat_service: ChatService = Depends(get_chat_service)):
    """
    Suggests agent queries based on the provided agentic application ID and user email.

    Args:
        fastapi_request (Request): The FastAPI request object.
        agentic_application_id (str): The ID of the agentic application.
        session_id (str): The session ID for the user.
    
    Returns:
        list: A list of suggested queries for the agent.
    
    Raises:
        HTTPException: If an error occurs during query suggestion.
    """
    user_id = fastapi_request.cookies.get("user_id")
    user_session = fastapi_request.cookies.get("user_session")
    update_session_context(user_session=user_session, user_id=user_id)
    
    try:
        suggestions = await chat_service.fetch_all_user_queries(agentic_application_id=agentic_application_id, user_email=user_email)
        return suggestions
    except Exception as e:
        log.error(f"Error suggesting queries for agent {agentic_application_id}: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")
    
class GroundTruthEvaluationRequest(BaseModel):
    """Schema for requesting a ground truth evaluation."""
    model_name: str = Field(..., description="The name of the LLM model used by the agent being evaluated.")
    agent_type: str = Field(..., description="The type of the agent being evaluated (e.g., 'react_agent', 'multi_agent').")
    agent_name: str = Field(..., description="The name of the agent being evaluated.")
    agentic_application_id: str = Field(..., description="The ID of the agentic application being evaluated.")
    session_id: str = Field(..., description="A session ID to use for the evaluation runs (can be temporary).")
    use_llm_grading: Optional[bool] = Field(False, description="If true, uses LLM for grading instead of rule-based.")

def get_model_service() -> ModelService:
    """Returns the global ModelService instance."""
    if model_service is None:
        raise RuntimeError("ModelService not initialized yet.")
    return model_service

async def evaluate_agent_performance(evaluation_request: GroundTruthEvaluationRequest, file_path: str):
    """
    Internal function to evaluate an agent against a ground truth file.
    Returns evaluation results, file paths, and summary.
    """
    if not os.path.isfile(file_path):
        raise FileNotFoundError(f"File not found: {file_path}")

    if not file_path.lower().endswith((".csv", ".xlsx", ".xls")):
        raise ValueError("File must be a CSV or Excel file.")

    model_service = get_model_service()
    inference_service = get_centralized_agent_inference()
    llm = await model_service.get_llm_model(evaluation_request.model_name)

    avg_scores, summary, excel_path = await evaluate_ground_truth_file(
        model_name=evaluation_request.model_name,
        agent_type=evaluation_request.agent_type,
        file_path=file_path,  #  Use here
        agentic_application_id=evaluation_request.agentic_application_id,
        session_id=evaluation_request.session_id,
        inference_service=inference_service,
        llm=llm,
        use_llm_grading=evaluation_request.use_llm_grading
    )

    return avg_scores, summary, excel_path

async def _upload_evaluation_file(file: UploadFile = File(...), subdirectory: str = "") -> Dict[str, str]:
    """
    Internal helper to save an uploaded evaluation file.
    """
    if subdirectory.startswith("/") or subdirectory.startswith("\\"):
        subdirectory = subdirectory[1:]

    save_path = os.path.join(EVALUATION_UPLOAD_DIR, subdirectory) if subdirectory else EVALUATION_UPLOAD_DIR
    os.makedirs(save_path, exist_ok=True)

    # Ensure unique filename using UUID
    name, ext = os.path.splitext(file.filename)
    safe_filename = f"{name}_{uuid.uuid4().hex[:8]}{ext}"
    full_file_path = os.path.join(save_path, safe_filename)

    # Save file
    try:
        with open(full_file_path, "wb") as f:
            f.write(await file.read())

        log.info(f"Evaluation file '{file.filename}' uploaded as '{safe_filename}' at '{full_file_path}'")

        relative_path = os.path.relpath(full_file_path, start=os.getcwd())
        return {
            "info": f"File '{file.filename}' saved as '{safe_filename}' at '{relative_path}'",
            "file_path": relative_path
        }
    except Exception as e:
        log.error(f"Error saving evaluation file '{file.filename}': {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to save file: {e}")

@app.post("/upload-and-evaluate-json")
async def upload_and_evaluate_json_endpoint(
        fastapi_request: Request,
        file: UploadFile = File(...),
        subdirectory: str = "",
        evaluation_request: GroundTruthEvaluationRequest = Depends()
    ):
    """
    API endpoint to upload an evaluation file and trigger evaluation, returning JSON response.

    Parameters:
    - fastapi_request: The FastAPI Request object.
    - file: The uploaded evaluation file.
    - subdirectory: Optional subdirectory within the evaluation uploads directory.
    - evaluation_request: Pydantic model containing evaluation parameters.

    Returns:
    - Dict[str, Any]: JSON response with evaluation summary and download URL.
    """
    user_id = fastapi_request.cookies.get("user_id")
    user_session = fastapi_request.cookies.get("user_session")
    update_session_context(user_session=user_session, user_id=user_id)

    # Upload the file using the internal helper
    upload_resp = await _upload_evaluation_file(file, subdirectory)

    if "file_path" not in upload_resp:
        raise HTTPException(status_code=400, detail="File upload failed.")

    file_path = upload_resp["file_path"]

    try:
        avg_scores, summary, excel_path = await evaluate_agent_performance(
            evaluation_request=evaluation_request,
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
        log.error(f"Evaluation failed: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Evaluation failed: {str(e)}")

#--------------Secret Vault start-------------------------
from exportagent.src.schemas import (
    SecretCreateRequest, PublicSecretCreateRequest, SecretUpdateRequest, PublicSecretUpdateRequest,
    SecretDeleteRequest, PublicSecretDeleteRequest, SecretGetRequest, PublicSecretGetRequest, SecretListRequest
)
from exportagent.src.utils.secrets_handler import (
    setup_secrets_manager, current_user_email, create_public_key, update_public_key, get_public_key,
    delete_public_key, list_public_keys
)
@app.post("/secrets/create")
async def create_user_secret_endpoint(fastapi_request: Request, request: SecretCreateRequest):
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
async def create_public_secret_endpoint(fastapi_request: Request, request: PublicSecretCreateRequest):
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
async def get_user_secret_endpoint(fastapi_request: Request, request: SecretGetRequest):
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
async def get_public_secret_endpoint(fastapi_request: Request, request: PublicSecretGetRequest):
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
async def update_user_secret_endpoint(fastapi_request: Request, request: SecretUpdateRequest):
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
async def update_public_secret_endpoint(fastapi_request: Request, request: PublicSecretUpdateRequest):
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
async def secrets_health_check_endpoint(fastapi_request: Request):
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