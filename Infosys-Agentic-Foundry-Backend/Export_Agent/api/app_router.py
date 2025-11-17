# © 2024-25 Infosys Limited, Bangalore, India. All Rights Reserved.
import os,ast,uuid,json
import asyncio,time,tempfile
import pandas as pd
from typing import Literal,List,Dict,Optional,Callable,Awaitable , Union
from pathlib import Path
from fastapi import APIRouter, Depends, HTTPException, Request,Query,UploadFile,File
from fastapi.responses import JSONResponse,FileResponse,StreamingResponse
from fastapi.encoders import jsonable_encoder
from sentence_transformers import SentenceTransformer, util
from sentence_transformers import CrossEncoder
from datetime import datetime
from pytz import timezone
from pydantic import BaseModel

# Import the Redis-PostgreSQL manager
# from src.database.redis_postgres_manager import RedisPostgresManager, TimedRedisPostgresManager, create_manager_from_env, create_timed_manager_from_env

from src.schemas import AgentInferenceRequest, ChatSessionRequest, OldChatSessionsRequest, StoreExampleRequest, StoreExampleResponse, SDLCAgentInferenceRequest

from src.database.services import ChatService, FeedbackLearningService, AgentService,EvaluationService
from src.inference.inference_utils import EpisodicMemoryManager
from src.inference.centralized_agent_inference import CentralizedAgentInference
from src.api.dependencies import ServiceProvider # The dependency provider
from src.auth.dependencies import get_user_info_from_request
from src.database.services import EvaluationService, ConsistencyService
from src.database.core_evaluation_service import CoreEvaluationService, CoreConsistencyEvaluationService, CoreRobustnessEvaluationService
from telemetry_wrapper import logger as log, update_session_context
from src.models.model_service import ModelService
from src.schemas import GroundTruthEvaluationRequest

from groundtruth import evaluate_ground_truth_file
from phoenix.otel import register
from phoenix.trace import using_project
#----Imports end---------#
task_tracker: dict[str, asyncio.Task] = {}

# Create an APIRouter instance for chat-related endpoints
router = APIRouter()

# Initialize the global manager
_global_manager = None

# async def get_global_manager():
#     """Get or create the global RedisPostgresManager instance (async)"""
#     global _global_manager
#     if _global_manager is None and RedisPostgresManager is not None:
#         try:
#             base_manager = await create_manager_from_env()
#             _global_manager = TimedRedisPostgresManager(base_manager, time_threshold_minutes=15)
#             log.info("Global TimedRedisPostgresManager initialized successfully")
#         except Exception as e:
#             log.error(f"Failed to initialize TimedRedisPostgresManager: {e}")
#             _global_manager = None
#     return _global_manager
#--------------------Chat endpoints--------------------#
@router.post("/chat/inference")
async def run_agent_inference_endpoint(
                        request: Request,
                        inference_request: AgentInferenceRequest,
                        inference_service: CentralizedAgentInference = Depends(ServiceProvider.get_centralized_agent_inference),
                        feedback_learning_service: FeedbackLearningService = Depends(ServiceProvider.get_feedback_learning_service)
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
    sse_manager = request.app.state.sse_manager
    session_id = inference_request.session_id
    log.info(f"[{session_id}] Received new request for {inference_request.agentic_application_id}")

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
            result = await inference_service.run(inference_request, sse_manager=sse_manager)
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


@router.post("/chat/get/feedback-response/{feedback_type}")
async def send_feedback_endpoint(
                    request: Request,
                    feedback_type: Literal["like", "regenerate", "submit_feedback"],
                    inference_request: AgentInferenceRequest,
                    chat_service: ChatService = Depends(ServiceProvider.get_chat_service),
                    inference_service: CentralizedAgentInference = Depends(ServiceProvider.get_centralized_agent_inference),
                    feedback_learning_service: FeedbackLearningService = Depends(ServiceProvider.get_feedback_learning_service),
                    model_service: ModelService = Depends(ServiceProvider.get_model_service)
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
        llm, feedback_prompt, feedback_learning_service,
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
                You are a lesson generator for an AI agent. Based on the original user query, the agent's initial response, user feedback on that response, and the improved final response, generate a concise lesson that the agent can apply in similar future situations.

                **Original Query:** {original_query}

                **Old Response:** {old_response}

                **User Feedback:** {user_feedback}

                **Final Response (after incorporating feedback):** {final_response}

                **Task:** Generate a specific, actionable lesson that captures what the agent learned from this feedback. The lesson should:
                1. Identify the key pattern or trigger from the original query
                2. Specify what action should be taken when this pattern is detected
                3. Be applicable to similar future scenarios

                **Format:** Return only the lesson statement - no explanations or additional text.

                **Example format:** "When a user mentions [trigger word/pattern], always [specific action] before [main task]."
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
@router.post("/chat/get/history")
async def get_chat_history_endpoint(request: Request, chat_session_request: ChatSessionRequest, chat_service: ChatService = Depends(ServiceProvider.get_chat_service)):
    """
    API endpoint to retrieve the chat history of a previous session.

    Parameters:
    - request: The FastAPI Request object.
    - chat_session_request: Pydantic model containing agent_id and session_id.
    - chat_service: Dependency-injected ChatService instance.

    Returns:
    - Dict[str, Any]: A dictionary containing the previous conversation history.
    """
    user_id = request.cookies.get("user_id")
    user_session = request.cookies.get("user_session")
    update_session_context(user_session=user_session, user_id=user_id, session_id=chat_session_request.session_id, agent_id=chat_session_request.agent_id)

    history = await chat_service.get_chat_history_from_short_term_memory(
        agentic_application_id=chat_session_request.agent_id,
        session_id=chat_session_request.session_id,
    )
    update_session_context(user_session="Unassigned", user_id="Unassigned", session_id="Unassigned", agent_id="Unassigned")
    return history


@router.delete("/chat/clear-history")
async def clear_chat_history_endpoint(request: Request, chat_session_request: ChatSessionRequest, chat_service: ChatService = Depends(ServiceProvider.get_chat_service)):
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


@router.post("/chat/get/old-conversations")
async def get_old_conversations_endpoint(request: Request, chat_session_request: OldChatSessionsRequest, chat_service: ChatService = Depends(ServiceProvider.get_chat_service)):
    """
    API endpoint to retrieve old chat sessions for a specific user and agent.

    Parameters:
    - request: The FastAPI Request object.
    - chat_session_request: Pydantic model containing user_email and agent_id.
    - chat_service: Dependency-injected ChatService instance.

    Returns:
    - JSONResponse: A dictionary containing old chat sessions grouped by session ID.
    """
    user_id = request.cookies.get("user_id")
    user_session = request.cookies.get("user_session")
    update_session_context(user_session=user_session, user_id=user_id)

    result = await chat_service.get_old_chats_by_user_and_agent(
        user_email=chat_session_request.user_email,
        agent_id=chat_session_request.agent_id
    )

    if not result:
        raise HTTPException(status_code=404, detail="No old chats found for this user and agent.")
    
    return JSONResponse(content=jsonable_encoder(result))
@router.get("/agents/get/details-for-chat-interface")
async def get_agents_details_for_chat_interface_endpoint(request: Request, agent_service: AgentService = Depends(ServiceProvider.get_agent_service)):
    """Retrieves basic agent details for chat purposes."""
    user_id = request.cookies.get("user_id")
    user_session = request.cookies.get("user_session")
    update_session_context(user_session=user_session, user_id=user_id)
    
    agent_details = await agent_service.get_agents_details_for_chat()
    if not agent_details:
        raise HTTPException(status_code=404, detail="No agents found for chat interface.")
    return agent_details

@router.get("/chat/get/new-session-id")
async def create_new_session_endpoint(request: Request, chat_service: ChatService = Depends(ServiceProvider.get_chat_service)) -> str:
    """
    API endpoint to create a new unique session ID for a given user email.

    Parameters:
    - request: The FastAPI Request object.
    - chat_service: Dependency-injected ChatService instance.

    Returns:
    - str: The newly generated session ID.
    """
    user = await get_user_info_from_request(request)
    log.info(user)
    session_id = await chat_service.create_new_session_id(user.email)

    update_session_context(session_id=session_id)
    return session_id


@router.get("/chat/auto-suggest-agent-queries")
async def auto_suggest_agent_queries_endpoint(fastapi_request: Request, agentic_application_id:str, user_email:str, chat_service: ChatService = Depends(ServiceProvider.get_chat_service)):
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



@router.post("/chat/memory/store-example", response_model=StoreExampleResponse)
async def store_episodic_example(
                        request: Request,
                        store_example_request: StoreExampleRequest,
                        chat_service: ChatService = Depends(ServiceProvider.get_chat_service),
                        embedding_model: SentenceTransformer = Depends(ServiceProvider.get_embedding_model),
                        cross_encoder: CrossEncoder = Depends(ServiceProvider.get_cross_encoder)
                    ):
    """
    Store an interaction example as positive or negative for episodic learning.
    
    Args:
        request: Contains query, response, label (positive/negative), and optional user_id
        
    Returns:
        Success status and confirmation message
    """
    try:
        user_id = store_example_request.agent_id
        episodic_memory = EpisodicMemoryManager(user_id, embedding_model=embedding_model, cross_encoder=cross_encoder)
        result = await episodic_memory.store_interaction_example(
            query=store_example_request.query,
            response=store_example_request.response,
            label=store_example_request.label,
            tool_calls=store_example_request.tool_calls
        )
        if result["status"] == "duplicate":
            return StoreExampleResponse(
                success=False,
                message="Duplicate interaction detected. Cannot store - this query-response pair already exists",
                stored_as=None
            )
        elif result["status"] == "invalid":
            return StoreExampleResponse(
                success=False,
                message="Cannot store example: Query and response are identical (invalid interaction)",
                stored_as=None
            )
        elif result["status"] == "error":
            return StoreExampleResponse(
                success=False,
                message=f"Storage failed: {result['message']}",
                stored_as=None
            )
        else:  # success
            return StoreExampleResponse(
                success=True,
                message=f"Successfully stored interaction as {store_example_request.label} example",
                stored_as=store_example_request.label
            )

    except Exception as e:
        log.error(f"Failed to store episodic example: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Failed to store example: {str(e)}"
        )

@router.get("/chat/memory/get-examples/")
async def get_stored_examples(
                            agent_id: str,
                            limit: int = 10,
                            chat_service: ChatService = Depends(ServiceProvider.get_chat_service),
                            embedding_model: SentenceTransformer = Depends(ServiceProvider.get_embedding_model),
                            cross_encoder: CrossEncoder = Depends(ServiceProvider.get_cross_encoder)
                        ):
    """
    Get stored episodic examples for a user (for debugging/review)
    """
    try:
        user_id = agent_id
        # Use RedisPostgresManager to get records from both cache and database
        manager = await get_global_manager()
        examples = []
        if manager:
            # Get records from both cache and database
            records = await manager.get_records_by_category(user_id, limit=limit)
            for record in records:
                record_data = record.data
                examples.append({
                    "key": record_data.get("key", record.id),
                    "query": record_data.get("query", ""),
                    "response": record_data.get("response", "")[:200] + "...",  
                    "label": record_data.get("label", "unknown"),
                    "tool_calls": record_data.get("tool_calls", {}),
                    "timestamp": record_data.get("timestamp", ""),
                    "usage_count": record_data.get("total_usage_count", 0)
                })
        else:
            log.warning("Manager not available, cannot retrieve examples")
            return {
                "user_id": user_id,
                "total_examples": 0,
                "examples": [],
                "error": "Manager not available"
            }
        return {
            "user_id": user_id,
            "total_examples": len(examples),
            "examples": examples
        }
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to retrieve examples: {str(e)}"
        )

@router.delete("/chat/memory/delete-examples/")
async def delete_stored_example(
                            agent_id: str,
                            key: str,
                            chat_service: ChatService = Depends(ServiceProvider.get_chat_service)
                        ):
    """
    Delete a specific stored episodic example by its key.
    
    Args:
        session_id (str): The session ID of the user.
        key (str): The key of the example to delete.
        
    Returns:
        Dict[str, str]: Confirmation message indicating success or failure.
    """
    try:
        manager = await get_global_manager()
        if manager:
            await manager.delete_record(key)
        return {"message": f"Successfully deleted example with key {key}"}
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to delete example: {str(e)}"
        )

@router.put("/chat/memory/update-examples/")
async def update_stored_example(agent_id: str, key: str, label: str = None):
    try:
        manager = await get_global_manager()
        if not manager:
            raise HTTPException(status_code=500, detail="Manager not found")
        records = await manager.get_records_by_category(agent_id)
        print(records)
        if not records:
            raise HTTPException(status_code=404, detail="No records found")
        for record in records:
            item = record.data
            if item.get("key", record.id) == key:
                if label and label.lower() in ["positive", "negative"]:
                    item['label'] = label.lower()
                    # success = manager.update_record_in_database(record)
                    success = await manager.base_manager.update_record(record)
                    if success:
                        return {"message": f"Successfully updated example with key {key}"}
                    else:
                        raise HTTPException(status_code=500, detail="Failed to update record")
                else:
                    raise HTTPException(status_code=400, detail="Invalid label")
        raise HTTPException(status_code=404, detail=f"Record with key {key} not found")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to update example: {str(e)}")
 

@router.get("/chat/connect_to_postgres")
async def check_postgres_db(chat_service: ChatService = Depends(ServiceProvider.get_chat_service)):
    try:
        result = await chat_service.fetch_memory_from_postgres()
        if "error" in result:
            raise HTTPException(status_code=500, detail=f"Failed to fetch memory: {result['error']}")
        return result["data"]
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to check PostgreSQL database: {str(e)}"
        )
 
#-------------- Evaluation endpoints ----------------#
# Base directory for uploads
BASE_DIR = "user_uploads"
TRUE_BASE_DIR = os.path.dirname(BASE_DIR)  # This will now point to the folder that contains both `user_uploads` and `evaluation_uploads`
EVALUATION_UPLOAD_DIR = os.path.join(TRUE_BASE_DIR, "evaluation_uploads")
os.makedirs(EVALUATION_UPLOAD_DIR, exist_ok=True) # Ensure directory exists on startup


# Helper functions

async def _parse_agent_names(agent_input: Optional[List[str]]) -> Optional[List[str]]:
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

async def _evaluate_agent_performance(
    evaluation_request: GroundTruthEvaluationRequest,
    file_path: str,
    progress_callback: Optional[Callable[[str], Awaitable[None]]] = None
):
    """
    Wrapper function to evaluate an agent against a ground truth file.
    Supports optional progress_callback for SSE streaming.
    """
    if not os.path.isfile(file_path):
        raise FileNotFoundError(f"File not found: {file_path}")

    if not file_path.lower().endswith((".csv", ".xlsx", ".xls")):
        raise ValueError("File must be a CSV or Excel file.")

    if progress_callback:
        await progress_callback("Initializing model and inference service...")

    model_service = ServiceProvider.get_model_service()
    inference_service = ServiceProvider.get_centralized_agent_inference()
    llm = await model_service.get_llm_model(evaluation_request.model_name)

    if progress_callback:
        await progress_callback("Starting evaluation of ground truth file...")

    avg_scores, summary, excel_path = await evaluate_ground_truth_file(
        model_name=evaluation_request.model_name,
        agent_type=evaluation_request.agent_type,
        file_path=file_path,
        agentic_application_id=evaluation_request.agentic_application_id,
        session_id=evaluation_request.session_id,
        inference_service=inference_service,
        llm=llm,
        use_llm_grading=evaluation_request.use_llm_grading,
        progress_callback=progress_callback  # ✅ Pass callback here
    )

    if progress_callback:
        await progress_callback("Evaluation completed successfully.")

    return avg_scores, summary, excel_path

async def cleanup_old_files(directories=["outputs", "evaluation_uploads"], expiration_hours=24):
    log.debug("Starting cleanup task for old files...")
    while True:
        try:
            now = time.time()
            cutoff = now - (expiration_hours * 60 * 60)

            for directory in directories:
                abs_path = os.path.abspath(directory)
                deleted_files = []

                log.debug(f"[Cleanup Task] Scanning '{abs_path}' for files older than {expiration_hours} hours...")

                if not os.path.exists(abs_path):
                    log.warning(f"[Cleanup Task] Directory does not exist: {abs_path}")
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


# Endpoints

@router.post("/evaluation/process-unprocessed")
async def process_unprocessed_evaluations_endpoint(
    fastapi_request: Request,
    evaluating_model1: str = Query(..., description="Model name for comparison (e.g., 'gpt-4o')"),
    evaluating_model2: str = Query(..., description="Another model name for comparison (e.g., 'gpt-35-turbo')"),
    core_evaluation_service: CoreEvaluationService = Depends(ServiceProvider.get_core_evaluation_service)
):
    """
    API endpoint to stream progress of unprocessed evaluation records.

    Parameters:
    - fastapi_request: The FastAPI Request object.
    - evaluating_model1: First model name for evaluation comparison.
    - evaluating_model2: Second model name for evaluation comparison.
    - core_evaluation_service: Dependency-injected CoreEvaluationService instance.

    Returns:
    - Dict[str, str]: A message indicating the status of the processing.
    """
    user_id = fastapi_request.cookies.get("user_id")
    user_session = fastapi_request.cookies.get("user_session")
    user = await get_user_info_from_request(fastapi_request)
    update_session_context(user_session=user_session, user_id=user_id)

    register(
        project_name='evaluation-metrics',
        auto_instrument=True,
        set_global_tracer_provider=False,
        batch=True
    )

    async def event_stream():
        with using_project('evaluation-metrics'):
            async for update in core_evaluation_service.process_unprocessed_evaluations(
                model1=evaluating_model1,
                model2=evaluating_model2,
                user=user
            ):
                yield f"data: {json.dumps(update)}\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@router.get("/evaluation/get/data")
async def get_evaluation_data_endpoint(
        fastapi_request: Request,
        agent_names: Optional[List[str]] = Query(default=None),
        page: int = Query(default=1, ge=1),
        limit: int = Query(default=10, ge=1, le=100),
        evaluation_service: EvaluationService = Depends(ServiceProvider.get_evaluation_service)
    ):
    """
    API endpoint to retrieve raw evaluation data records.

    Parameters:
    - fastapi_request: The FastAPI Request object.
    - agent_names: Optional list of agent names to filter by.
    - page: Page number for pagination.
    - limit: Number of records per page.
    - evaluation_service: Dependency-injected EvaluationService instance.

    Returns:
    - List[Dict[str, Any]]: A list of evaluation data records.
    """
    user_id = fastapi_request.cookies.get("user_id")
    user_session = fastapi_request.cookies.get("user_session")
    update_session_context(user_session=user_session, user_id=user_id)
    user = await get_user_info_from_request(fastapi_request)

    # Use InferenceUtils to parse agent names
    parsed_names = await _parse_agent_names(agent_names)
    data = await evaluation_service.get_evaluation_data(user,parsed_names, page, limit)
    if not data:
        raise HTTPException(status_code=404, detail="No evaluation data found")
    return data


@router.get("/evaluation/get/tool-metrics")
async def get_tool_metrics_endpoint(
        fastapi_request: Request,
        agent_names: Optional[List[str]] = Query(default=None),
        page: int = Query(default=1, ge=1, description="Page number (starts from 1)"),
        limit: int = Query(default=10, ge=1, le=100, description="Number of records per page (max 100)"),
        evaluation_service: EvaluationService = Depends(ServiceProvider.get_evaluation_service),
    ):
    """
    API endpoint to retrieve tool evaluation metrics.

    Parameters:
    - fastapi_request: The FastAPI Request object.
    - agent_names: Optional list of agent names to filter by.
    - page: Page number for pagination.
    - limit: Number of records per page.
    - evaluation_service: Dependency-injected EvaluationService instance.

    Returns:
    - List[Dict[str, Any]]: A list of tool metrics records.
    """
    user_id = fastapi_request.cookies.get("user_id")
    user_session = fastapi_request.cookies.get("user_session")
    update_session_context(user_session=user_session, user_id=user_id)
    user = await get_user_info_from_request(fastapi_request)

    parsed_names = await _parse_agent_names(agent_names)
    data = await evaluation_service.get_tool_metrics(user,parsed_names, page, limit)
    if not data:
        raise HTTPException(status_code=404, detail="No tool metrics found")
    return data


@router.get("/evaluation/get/agent-metrics")
async def get_agent_metrics_endpoint(
        fastapi_request: Request,
        agent_names: Optional[List[str]] = Query(default=None),
        page: int = Query(default=1, ge=1),
        limit: int = Query(default=10, ge=1, le=100),
        evaluation_service: EvaluationService = Depends(ServiceProvider.get_evaluation_service)
    ):
    """
    API endpoint to retrieve agent evaluation metrics.

    Parameters:
    - fastapi_request: The FastAPI Request object.
    - agent_names: Optional list of agent names to filter by.
    - page: Page number for pagination.
    - limit: Number of records per page.
    - evaluation_service: Dependency-injected EvaluationService instance.

    Returns:
    - List[Dict[str, Any]]: A list of agent metrics records.
    """
    user_id = fastapi_request.cookies.get("user_id")
    user_session = fastapi_request.cookies.get("user_session")
    update_session_context(user_session=user_session, user_id=user_id)
    user = await get_user_info_from_request(fastapi_request)

    parsed_names = await _parse_agent_names(agent_names)
    data = await evaluation_service.get_agent_metrics(user,parsed_names, page, limit)
    if not data:
        raise HTTPException(status_code=404, detail="No agent metrics found")
    return data


@router.get("/evaluation/download-result")
async def download_evaluation_result_endpoint(fastapi_request: Request, file_name: str):
    """
    API endpoint to download the evaluation result file.

    Parameters:
    - fastapi_request: The FastAPI Request object.
    - file_name: The name of the result file to download.

    Returns:
    - FileResponse: Returns the file as a downloadable response.
    """
    user_id = fastapi_request.cookies.get("user_id")
    user_session = fastapi_request.cookies.get("user_session")
    update_session_context(user_session=user_session, user_id=user_id)

    # Full path to file (assuming 'outputs' is a subdirectory in the current working directory)
    file_path = os.path.join(Path.cwd(), 'outputs', file_name)

    if not os.path.exists(file_path):
        log.error(f"File not found: {file_path}")
        raise HTTPException(status_code=404, detail="File not found")
    log.info(f"Downloading evaluation result file: {file_path}")
    return FileResponse(path=file_path, filename=file_name, media_type="application/octet-stream")


@router.get("/evaluation/download-groundtruth-template")
async def download_groundtruth_template_endpoint(fastapi_request: Request, file_name: str='Groundtruth_template.xlsx'):
    """
    API endpoint to download sample upload file for groundtruth evaluation.

    Parameters:
    - fastapi_request: The FastAPI Request object.
    - file_name: The name of the template file to download (default is 'Groundtruth_template.xlsx').
    
    Returns:
    - FileResponse: Returns the file as a downloadable response.
    """
    user_id = fastapi_request.cookies.get("user_id")
    user_session = fastapi_request.cookies.get("user_session")
    update_session_context(user_session=user_session, user_id=user_id)

    file_path = os.path.join(Path.cwd(), 'src/file_templates', file_name)

    if not os.path.exists(file_path):
        log.error(f"File not found: {file_path}")
        raise HTTPException(status_code=404, detail="File not found")
    log.info(f"Downloading sample upload file for groundtruth evaluation: {file_path}")
    return FileResponse(path=file_path, filename=file_name, media_type="application/octet-stream")

@router.post("/evaluation/upload-and-evaluate")
async def upload_and_evaluate_endpoint(
        fastapi_request: Request,
        file: UploadFile = File(...),
        subdirectory: str = "",
        evaluation_request: GroundTruthEvaluationRequest = Depends()
    ):
    """
    API endpoint to upload an evaluation file and trigger evaluation.

    Parameters:
    - fastapi_request: The FastAPI Request object.
    - file: The uploaded evaluation file.
    - subdirectory: Optional subdirectory within the evaluation uploads directory.
    - evaluation_request: Pydantic model containing evaluation parameters.

    Returns:
    - FileResponse: The generated Excel evaluation report.
    """
    user_id = fastapi_request.cookies.get("user_id")
    user_session = fastapi_request.cookies.get("user_session")
    update_session_context(user_session=user_session, user_id=user_id)

    # Step 1: Upload file using the internal helper
    upload_resp = await _upload_evaluation_file(file, subdirectory)

    if "file_path" not in upload_resp:
        raise HTTPException(status_code=400, detail="File upload failed.")

    file_path = upload_resp["file_path"]

    try:
        avg_scores, summary, excel_path = await _evaluate_agent_performance(
            evaluation_request=evaluation_request,
            file_path=file_path
        )

        file_name = os.path.basename(excel_path)

        # Return the Excel file as response with custom headers
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
        log.error(f"Evaluation failed: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Evaluation failed: {str(e)}")


@router.post("/evaluation/upload-and-evaluate-json")
async def upload_and_evaluate_json(
    fastapi_request: Request,
    file: UploadFile = File(...),
    subdirectory: str = "",
    evaluation_request: GroundTruthEvaluationRequest = Depends()
):
    user_id = fastapi_request.cookies.get("user_id")
    user_session = fastapi_request.cookies.get("user_session")
    update_session_context(user_session=user_session, user_id=user_id)

    upload_resp = await _upload_evaluation_file(file, subdirectory)

    if "file_path" not in upload_resp:
        raise HTTPException(status_code=400, detail="File upload failed.")
    file_path = upload_resp["file_path"]

    async def event_stream():
        queue = asyncio.Queue()

        async def progress_callback(message: str):
            await queue.put(json.dumps({"progress": message}) + "\n")

        async def run_evaluation():
            try:
                await queue.put(json.dumps({"status": "Starting evaluation..."}) + "\n")

                avg_scores, summary, excel_path = await _evaluate_agent_performance(
                    evaluation_request=evaluation_request,
                    file_path=file_path,
                    progress_callback=progress_callback
                )

                summary_safe = summary.encode("ascii", "ignore").decode().replace("\n", " ")
                file_name = os.path.basename(excel_path)
                download_url = f"{fastapi_request.base_url}evaluation/download-result?file_name={file_name}"

                result_payload = {
                    "message": "Evaluation completed successfully",
                    "download_url": download_url,
                    "average_scores": avg_scores,
                    "diagnostic_summary": summary_safe
                }

                await queue.put(json.dumps({"result": result_payload}) + "\n")
            except Exception as e:
                await queue.put(json.dumps({"error": f"Evaluation failed: {str(e)}"}) + "\n")

        asyncio.create_task(run_evaluation())

        while True:
            message = await queue.get()
            yield message
            if message.startswith("{\"result\":") or message.startswith("{\"error\":"):
                break

    return StreamingResponse(event_stream(), media_type="application/json")

    
@router.get("/evaluation/available_agents/", summary="Get All Agent Evaluation Records")
async def get_all_agents_from_consistency_robustness_details_table(
    consistency_service: ConsistencyService = Depends(ServiceProvider.get_consistency_service)
):
    """
    Retrieves a list of all agent evaluation records from the database.
    """
    log.info("Received request to fetch all agent evaluation records.")
    try:
       
        all_agents = await consistency_service.get_all_agents()
        if not all_agents:
            log.info("No agent evaluation records found in the database.")
            return []
        return all_agents
    except Exception as e:
        log.error(f"An unexpected error occurred while fetching agent records: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="An internal server error occurred while fetching data.")
    
#---------------secret vault endpoints ----------------#
import asyncio
from fastapi import APIRouter, HTTPException, Request

from src.schemas import (
    SecretCreateRequest, PublicSecretCreateRequest, SecretUpdateRequest, PublicSecretUpdateRequest,
    SecretDeleteRequest, PublicSecretDeleteRequest, SecretGetRequest, PublicSecretGetRequest, SecretListRequest
)
from src.utils.secrets_handler import (
    setup_secrets_manager, get_user_secrets, set_user_secret, delete_user_secret, list_user_secrets,
    get_user_secrets_dict, create_public_key, update_public_key, get_public_key,
    get_all_public_keys, delete_public_key, list_public_keys
)

from telemetry_wrapper import logger as log, update_session_context


@router.post("/secrets/create")
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


@router.post("/secrets/public/create")
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


@router.post("/secrets/get")
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


@router.post("/secrets/public/get")
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


@router.put("/secrets/update")
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


@router.put("/secrets/public/update")
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


@router.delete("/secrets/delete")
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


@router.delete("/secrets/public/delete")
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


@router.post("/secrets/list")
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


@router.post("/secrets/public/list")
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
@router.get("/secrets/health")
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
#-----------Data connectors endpoints ----------------#
import os
import uuid
import sqlite3 # For SQLite specific operations
from typing import Dict, Optional, Any
from bson import ObjectId # For MongoDB ObjectId handling
from sqlalchemy import create_engine, text # For SQL Alchemy engine
from sqlalchemy.exc import SQLAlchemyError # For SQL Alchemy exceptions

from fastapi import APIRouter, Depends, HTTPException, Request, Form, UploadFile, File

from src.schemas import QueryGenerationRequest, QueryExecutionRequest, DBDisconnectRequest, MONGODBOperation

from MultiDBConnection_Manager import MultiDBConnectionRepository, get_connection_manager
from src.api.dependencies import ServiceProvider # The dependency provider
from src.database.services import ModelService # For generate_query endpoint
from telemetry_wrapper import logger as log, update_session_context # Your custom logger and context updater

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

@router.post("/data-connector/connect")
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
        db_connection_manager: MultiDBConnectionRepository = Depends(ServiceProvider.get_multi_db_connection_manager)
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
    if isinstance(sql_file, str):
        sql_file = None
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


@router.post("/data-connector/disconnect")
async def disconnect_database_endpoint(request: Request, disconnect_request: DBDisconnectRequest, db_connection_manager: MultiDBConnectionRepository = Depends(ServiceProvider.get_multi_db_connection_manager)):
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


@router.post("/data-connector/generate-query")
async def generate_query_endpoint(request: Request, query_request: QueryGenerationRequest, model_service: ModelService = Depends(ServiceProvider.get_model_service)):
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


@router.post("/data-connector/run-query")
async def run_query_endpoint(request: Request, query_execution_request: QueryExecutionRequest, db_connection_manager: MultiDBConnectionRepository = Depends(ServiceProvider.get_multi_db_connection_manager)):
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


@router.get("/data-connector/connections")
async def get_connections_endpoint(request: Request, db_connection_manager: MultiDBConnectionRepository = Depends(ServiceProvider.get_multi_db_connection_manager)):
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
    

@router.get("/data-connector/connection/{connection_name}")
async def get_connection_config_endpoint(request: Request, connection_name: str, db_connection_manager: MultiDBConnectionRepository = Depends(ServiceProvider.get_multi_db_connection_manager)):
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


@router.get("/data-connector/connections/sql")
async def get_sql_connections_endpoint(request: Request, db_connection_manager: MultiDBConnectionRepository = Depends(ServiceProvider.get_multi_db_connection_manager)):
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


@router.get("/data-connector/connections/mongodb")
async def get_mongodb_connections_endpoint(request: Request, db_connection_manager: MultiDBConnectionRepository = Depends(ServiceProvider.get_multi_db_connection_manager)):
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


@router.post("/data-connector/mongodb-operation/")
async def mongodb_operation_endpoint(request: Request, mongo_op_request: MONGODBOperation, db_connection_manager: MultiDBConnectionRepository = Depends(ServiceProvider.get_multi_db_connection_manager)):
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


@router.get("/data-connector/get/active-connection-names")
async def get_active_connection_names_endpoint(request: Request, db_connection_manager: MultiDBConnectionRepository = Depends(ServiceProvider.get_multi_db_connection_manager)):
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
#---------------Feedback learning endpoints----------------------#
from fastapi import APIRouter, Depends, HTTPException, Request

from src.schemas import ApprovalRequest
from src.database.services import FeedbackLearningService
from src.api.dependencies import ServiceProvider # The dependency provider


@router.get("/feedback-learning/get/approvals-list")
async def get_approvals_list_endpoint(request: Request, feedback_learning_service: FeedbackLearningService = Depends(ServiceProvider.get_feedback_learning_service)):
    """
    API endpoint to retrieve the list of agents who have provided feedback.

    Parameters:
    - request: The FastAPI Request object.
    - feedback_learning_service: Dependency-injected FeedbackLearningService instance.

    Returns:
    - List[Dict[str, Any]]: A list of agents with feedback.
    """
    user_id = request.cookies.get("user_id")
    user_session = request.cookies.get("user_session")
    update_session_context(user_session=user_session, user_id=user_id)

    approvals = await feedback_learning_service.get_agents_with_feedback()
    if not approvals:
        raise HTTPException(status_code=404, detail="No approvals found")
    return approvals


@router.get("/feedback-learning/get/responses-data/{response_id}")
async def get_responses_data_endpoint(request: Request, response_id: str, feedback_learning_service: FeedbackLearningService = Depends(ServiceProvider.get_feedback_learning_service)):
    """
    API endpoint to retrieve detailed data for a specific feedback response.

    Parameters:
    - response_id: The ID of the feedback response.
    - request: The FastAPI Request object.
    - feedback_learning_service: Dependency-injected FeedbackLearningService instance.

    Returns:
    - Dict[str, Any]: The detailed feedback response data.
    """
    user_id = request.cookies.get("user_id")
    user_session = request.cookies.get("user_session")
    update_session_context(user_session=user_session, user_id=user_id)

    approvals = await feedback_learning_service.get_feedback_details_by_response_id(response_id=response_id)
    if not approvals:
        raise HTTPException(status_code=404, detail="No Response found")
    return approvals


@router.get("/feedback-learning/get/approvals-by-agent/{agent_id}")
async def get_approval_by_agent_id_endpoint(request: Request, agent_id: str, feedback_learning_service: FeedbackLearningService = Depends(ServiceProvider.get_feedback_learning_service)):
    """
    API endpoint to retrieve all feedback (approvals) for a specific agent.

    Parameters:
    - request: The FastAPI Request object.
    - agent_id: The ID of the agent.
    - feedback_learning_service: Dependency-injected FeedbackLearningService instance.

    Returns:
    - List[Dict[str, Any]]: A list of feedback entries for the agent.
    """
    user_id = request.cookies.get("user_id")
    user_session = request.cookies.get("user_session")
    update_session_context(user_session=user_session, user_id=user_id)

    approval = await feedback_learning_service.get_all_approvals_for_agent(agent_id=agent_id)
    if not approval:
        raise HTTPException(status_code=404, detail="Approval not found")
    return approval


@router.put("/feedback-learning/update/approval-response")
async def update_approval_response_endpoint(
    request: Request,
    approval_request: ApprovalRequest,
    feedback_learning_service: FeedbackLearningService = Depends(ServiceProvider.get_feedback_learning_service)
):
    """
    API endpoint to update the approval status and details of a feedback response.

    Parameters:
    - request: The FastAPI Request object.
    - approval_request: Pydantic model containing the feedback details to update.
    - feedback_learning_service: Dependency-injected FeedbackLearningService instance.

    Returns:
    - Dict[str, Any]: Status of the update operation.
    """
    user_id = request.cookies.get("user_id")
    user_session = request.cookies.get("user_session")
    update_session_context(user_session=user_session, user_id=user_id)

    update_data= {}
    
    if approval_request.lesson:
        update_data["lesson"] = approval_request.lesson
        
    if approval_request.approved is not None:
        update_data["approved"] = approval_request.approved

    response = await feedback_learning_service.update_feedback_status(
        response_id=approval_request.response_id,
        update_data=update_data
    )
    if not response.get("is_update"):
        raise HTTPException(status_code=400, detail=response.get("message", response.get("status_message")))
    return response

#-------------------Utility endpoints---------------------#
import os
import shutil
import asyncpg
from typing import List
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request, UploadFile, File, Form, Query
from fastapi.responses import JSONResponse

import azure.cognitiveservices.speech as speechsdk
from langchain_google_genai import GoogleGenerativeAIEmbeddings
from langchain_community.vectorstores import FAISS
from langchain_community.document_loaders import TextLoader
from langchain.text_splitter import CharacterTextSplitter
from langchain_pymupdf4llm import PyMuPDF4LLMLoader

from src.database.services import ModelService
from src.utils.file_manager import FileManager
from src.api.dependencies import ServiceProvider # The dependency provider
from telemetry_wrapper import logger as log, update_session_context


@router.get("/utility/get/version")
async def get_version_endpoint(request: Request):
    """
    API endpoint to retrieve the application version.

    Parameters:
    - request: The FastAPI Request object.

    Returns:
    - Dict[str, str]: A dictionary containing the application version.
    """
    user_id = request.cookies.get("user_id")
    user_session = request.cookies.get("user_session")
    update_session_context(user_session=user_session, user_id=user_id)
    try:
        # Assuming VERSION file is in the same directory as the main app file
        version_file_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', 'VERSION')
        with open(version_file_path) as f:
            version = f.read().strip()
        return {"version": version}
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="VERSION file not found.")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error retrieving version: {e}")


@router.get('/utility/get/models')
async def get_available_models_endpoint(request: Request, model_service: ModelService = Depends(ServiceProvider.get_model_service)):
    user_id = request.cookies.get("user_id")
    user_session = request.cookies.get("user_session")
    update_session_context(user_session=user_session, user_id=user_id)

    try:
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


## ============ User Uploaded Files Endpoints ============

@router.post("/utility/files/user-uploads/upload/")
async def upload_file_endpoint(request: Request, file: UploadFile = File(...), subdirectory: str = "", file_manager: FileManager = Depends(ServiceProvider.get_file_manager)):
    user_id = request.cookies.get("user_id")
    user_session = request.cookies.get("user_session")
    update_session_context(user_session=user_session, user_id=user_id)

    file_location = await file_manager.save_uploaded_file(uploaded_file=file, subdirectory=subdirectory)

    log.info(f"File '{file.filename}' uploaded successfully to '{file_location}'")
    return {"info": f"File '{file.filename}' saved at '{file_location}'"}

@router.get("/utility/files/user-uploads/get-file-structure/")
async def get_file_structure_endpoint(request: Request, file_manager: FileManager = Depends(ServiceProvider.get_file_manager)):
    user_id = request.cookies.get("user_id")
    user_session = request.cookies.get("user_session")
    update_session_context(user_session=user_session, user_id=user_id)

    file_structure = await file_manager.generate_file_structure()
    log.info("File structure retrieved successfully")
    return JSONResponse(content=file_structure)

@router.get('/utility/files/user-uploads/download')
async def download_file_endpoint(request: Request, filename: str = Query(...), sub_dir_name: str = Query(None), file_manager: FileManager = Depends(ServiceProvider.get_file_manager)):
    user_id = request.cookies.get("user_id")
    user_session = request.cookies.get("user_session")
    update_session_context(user_session=user_session, user_id=user_id)
    return await file_manager.get_file(filename=filename, subdirectory=sub_dir_name)

@router.delete("/utility/files/user-uploads/delete/")
async def delete_file_endpoint(request: Request, file_path: str, file_manager: FileManager = Depends(ServiceProvider.get_file_manager)):
    user_id = request.cookies.get("user_id")
    user_session = request.cookies.get("user_session")
    update_session_context(user_session=user_session, user_id=user_id)
    return await file_manager.delete_file(file_path=file_path)

## ==========================================================


## ============ Knowledge Base Endpoints ============

KB_DIR = "KB_DIR"
GOOGLE_API_KEY = os.environ.get("GOOGLE_API_KEY", None)
GOOGLE_EMBEDDING_MODEL = os.environ.get("GOOGLE_EMBEDDING_MODEL", "models/text-embedding-004")
 

@router.post("/utility/knowledge-base/documents/upload")
async def upload_knowledge_base_documents_endpoint(
        request: Request,
        session_id: str = Form(...),
        kb_name: str = 'temp',
        files: List[UploadFile] = File(...)
    ):
    """
    API endpoint to upload documents for a knowledge base, create embeddings, and store them.

    Parameters:
    - request: The FastAPI Request object.
    - session_id: A session ID for temporary file storage during upload.
    - kb_name: The name of the knowledge base to create/update.
    - files: List of uploaded document files.

    Returns:
    - Dict[str, str]: Status message and storage path.
    """
    user_id = request.cookies.get("user_id")
    user_session = request.cookies.get("user_session")
    update_session_context(user_session=user_session, user_id=user_id)
    

    if not GOOGLE_API_KEY:
        raise HTTPException(status_code=500, detail="GOOGLE_API_KEY environment variable is not set for embeddings.")

    embeddings = GoogleGenerativeAIEmbeddings(
        model=GOOGLE_EMBEDDING_MODEL,
        google_api_key=GOOGLE_API_KEY
    )

    # Create temp directory
    TEMPFILE_DIR = "TEMPFILE_DIR"
    temp_dir = os.path.join(TEMPFILE_DIR, f"session_{session_id}")
    os.makedirs(temp_dir, exist_ok=True)

    file_paths = []
    for file in files:
        file_path = os.path.join(temp_dir, file.filename)
        try:
            with open(file_path, "wb") as buffer:
                shutil.copyfileobj(file.file, buffer)
            file_paths.append(file_path)
        except Exception as e:
            log.error(f"Error saving uploaded file {file.filename}: {e}", exc_info=True)
            raise HTTPException(status_code=500, detail=f"Failed to save file {file.filename}: {e}")

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
                log.warning(f"Unsupported file type for KB upload: {ext} for file {os.path.basename(path)}. Skipping.")
                continue
            documents.extend(loader.load())
        except Exception as e:
            log.error(f"Failed to load document {os.path.basename(path)}: {e}", exc_info=True)
            raise HTTPException(status_code=500, detail=f"Failed to load document {os.path.basename(path)}: {e}")

    # Split documents
    text_splitter = CharacterTextSplitter(chunk_size=1000, chunk_overlap=300)
    docs = text_splitter.split_documents(documents)

    faiss_path = os.path.join(KB_DIR, kb_name)
    
    try:
        # Create vector store
        vectorstore = FAISS.from_documents(docs, embeddings)
        # Save vector store to session-specific FAISS index folder
        vectorstore.save_local(faiss_path)
        log.info(f"Embeddings created and stored for KB '{kb_name}' at '{faiss_path}'.")
    except Exception as e:
        log.error(f"Error creating/saving vector store for KB '{kb_name}': {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to create/save knowledge base: {e}")

    return {
        "message": f"Uploaded {len(files)} files. Embeddings created and stored for knowledge base '{kb_name}'.",
        "storage_path": faiss_path
    }

@router.get("/utility/knowledge-base/list")
async def list_knowledge_base_directories_endpoint(request: Request):
    """
    API endpoint to list available knowledge base directories (vectorstores).

    Parameters:
    - request: The FastAPI Request object.

    Returns:
    - Dict[str, Any]: A dictionary containing a list of knowledge base names.
    """
    user_id = request.cookies.get("user_id")
    user_session = request.cookies.get("user_session")
    update_session_context(user_session=user_session, user_id=user_id)
    
    kb_path = Path(KB_DIR)

    if not kb_path.exists():
        return {"message": "No knowledge bases found."}

    directories = [d.name for d in kb_path.iterdir() if d.is_dir()]

    if not directories:
        return {"message": "No knowledge bases found."}

    return {"knowledge_bases": directories}

## ==========================================================


## ============ speech-to-text ============

@router.post("/utility/transcribe/")
async def transcribe_audio(file: UploadFile = File(...)):    
    SPEECH_KEY = os.getenv("SPEECH_KEY")
    STT_ENDPOINT = os.getenv("STT_ENDPOINT")
    SERVICE_REGION = os.getenv("SERVICE_REGION")
    os.makedirs('audios', exist_ok=True)
    file_location = os.path.join("audios", file.filename)# Save the uploaded file
    with open(file_location, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)
    speech_config = speechsdk.SpeechConfig(subscription=SPEECH_KEY, region=SERVICE_REGION)
    if STT_ENDPOINT:
        speech_config.endpoint_id = STT_ENDPOINT
    audio_config = speechsdk.audio.AudioConfig(filename=file_location)
    speech_recognizer = speechsdk.SpeechRecognizer(speech_config=speech_config, audio_config=audio_config)
    result = speech_recognizer.recognize_once()
    # os.remove(file_location)
    if result.reason == speechsdk.ResultReason.RecognizedSpeech:
        transcription = result.text
    elif result.reason == speechsdk.ResultReason.NoMatch:
        transcription = "No speech could be recognized."
    elif result.reason == speechsdk.ResultReason.Canceled:
        cancellation_details = result.cancellation_details
        transcription = f"Speech Recognition canceled: {cancellation_details.reason}"
        if cancellation_details.reason == speechsdk.CancellationReason.Error:
            transcription += f" Error details: {cancellation_details.error_details}"
    else:
        transcription = "Unknown error occurred during transcription."

    return {"transcription": transcription}

## ==========================================================


## ============ Documentation Files Endpoints ============

DOCS_ROOT = Path(r"C:\Agentic_foundary_documentation\docs")

async def _list_markdown_files_helper(directory: Path) -> List[str]:
    """
    Recursively lists all Markdown (.md) files in the given directory and its subdirectories.
    """
    log.debug(f"Listing markdown files in directory: {directory.resolve()}")

    if not directory.exists() or not directory.is_dir():
        raise HTTPException(status_code=404, detail=f"Directory not found at {directory.resolve()}")

    # Ensure path is within DOCS_ROOT to prevent directory traversal
    abs_directory = directory.resolve()
    if not abs_directory.startswith(DOCS_ROOT.resolve()):
        raise HTTPException(status_code=400, detail="Invalid directory path. Must be within documentation root.")

    files = [str(file.relative_to(DOCS_ROOT)) for file in directory.rglob("*.md")]
    return files

@router.get("/utility/docs/list-all-markdown-files")
async def list_all_docs_files_endpoint(request: Request):
    """
    API endpoint to list all Markdown files in the documentation root (including subfolders).

    Parameters:
    - request: The FastAPI Request object.

    Returns:
    - Dict[str, List[str]]: A dictionary containing the list of files.
    """
    user_id = request.cookies.get("user_id")
    user_session = request.cookies.get("user_session")
    update_session_context(user_session=user_session, user_id=user_id)
    try:
        files = await _list_markdown_files_helper(DOCS_ROOT)
        return {"files": files}
    except HTTPException:
        raise # Re-raise HTTPExceptions
    except Exception as e:
        log.error(f"Error listing all documentation files: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Error: {str(e)}")

@router.get("/utility/docs/list-markdown-files-in-directory/{dir_name}")
async def list_docs_files_in_directory_endpoint(request: Request, dir_name: str):
    """
    API endpoint to list all Markdown files in a specific subdirectory under the documentation root.

    Parameters:
    - request: The FastAPI Request object.
    - dir_name: The name of the subdirectory.

    Returns:
    - Dict[str, Any]: A dictionary containing the directory name and list of files.
    """
    user_id = request.cookies.get("user_id")
    user_session = request.cookies.get("user_session")
    update_session_context(user_session=user_session, user_id=user_id)
    
    target_dir = DOCS_ROOT / dir_name
    
    try:
        files = await _list_markdown_files_helper(target_dir)
        return {"directory": dir_name, "files": files}
    except HTTPException:
        raise # Re-raise HTTPExceptions
    except Exception as e:
        log.error(f"Error listing documentation files in directory '{dir_name}': {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Error: {str(e)}")

## =========================================================
#-----------------Consistency and Robustness-------------------------#
ist = timezone("Asia/Kolkata")

RESPONSES_TEMP_DIR = Path("responses_temp")
OUTPUT_DIR = Path("outputs")

RESPONSES_TEMP_DIR.mkdir(exist_ok=True)
OUTPUT_DIR.mkdir(exist_ok=True)

PREVIEW_DIR = Path("temp_previews")
PREVIEW_DIR.mkdir(exist_ok=True)
@router.post("/evaluation/consistency/preview-responses", summary="Preview Agent Responses for Consistency")
async def preview_agent_responses(
    file: Union[UploadFile, str, None] = File(None, description="Upload an Excel file with a 'queries' column"),
    queries: Optional[str] = Form(None, description='Enter queries as a JSON list of strings, e.g. ["Query1", "Query2"]'),
    agent_id: str = Form(...),
    agent_name: str = Form(...),
    agent_type: str = Form(...),
    model_name: str = Form(...),
    session_id: str = Form(...),
    consistency_service: ConsistencyService = Depends(ServiceProvider.get_consistency_service),
    core_consistency_service: CoreConsistencyEvaluationService = Depends(ServiceProvider.get_core_consistency_service)
):
    """
    Handles the initial 'preview' step. Checks if an agent exists,
    generates responses for a query file or manual input, and saves temporary results.
    """
    if isinstance(file, str):
        file = None
 
    # Validate input source
    if not file and not queries:
        raise HTTPException(status_code=400, detail="Either a file or manual queries must be provided.")
    if file and queries:
        raise HTTPException(status_code=400, detail="Provide either a file or manual queries, not both.")
 
    # Check if the agent already exists
    existing_agent = await consistency_service.get_agent_by_id(agent_id)
    if existing_agent:
        return {
            "status": "agent_exists",
            "message": f"Agent ID '{agent_id}' is already registered.",
            "update_url": f"/evaluation/generate-update-preview/{agent_id}"
        }
 
    # ✅ FIXED: Do NOT create agent record during preview - only create temp files
    # Agent record will be created only during approval step
    log.info(f"📋 Generating preview for agent_id: {agent_id} (no DB changes yet)")
 
    # Extract queries
    if file:
        try:
            df = pd.read_excel(file.file)
            df.columns = [c.strip().lower() for c in df.columns]
            if "queries" not in df.columns:
                raise HTTPException(status_code=400, detail="File must contain a 'queries' column.")
            queries_list = df["queries"].tolist()
        except HTTPException:
            raise  # Re-raise HTTP exceptions as-is
        except Exception as e:
            log.error(f"Error processing uploaded file: {e}", exc_info=True)
            raise HTTPException(status_code=400, detail=f"Error processing file: {str(e)}")
        finally:
            await file.close()
    else:
        try:
            queries_list = json.loads(queries)
            if not isinstance(queries_list, list):
                raise ValueError("Queries must be a list of strings.")
            queries_list = [q.strip() for q in queries_list if isinstance(q, str) and q.strip()]
        except json.JSONDecodeError as e:
            # If JSON parsing fails, try comma-separated format
            log.info(f"⚠️ JSON parsing failed: {str(e)}")
            try:
                log.info(f"🔄 Trying comma-separated format for queries: {queries}")
                queries_list = [q.strip() for q in queries.split(',') if q.strip()]
                if not queries_list:
                    raise ValueError("No valid queries found.")
                log.info(f"✅ Successfully parsed {len(queries_list)} queries from comma-separated format: {queries_list}")
            except Exception as e:
                raise HTTPException(
                    status_code=400, 
                    detail=f"Invalid queries format. Use JSON array format like [\"query1\", \"query2\"] or comma-separated like \"query1,query2\". Error: {str(e)}"
                )
        except Exception as e:
            log.error(f"❌ Error parsing queries: {str(e)}")
            raise HTTPException(status_code=400, detail=f"Invalid queries format: {str(e)}")
 
        df = pd.DataFrame({"queries": queries_list})
 
    # Generate responses
    responses = []
    timestamp = datetime.now(ist).strftime("%Y-%m-%d_%H-%M-%S")
    response_col = f"{timestamp}_response"
 
    for i, query in enumerate(queries_list):
        session = f"{session_id}_{i}"
        try:
            res = await core_consistency_service.call_agent(query, model_name, agent_id, session)
            responses.append(res)
        except Exception as e:
            log.error(f"Error calling agent for query {i+1}: {e}", exc_info=True)
            responses.append(f"Error: {str(e)}")
 
    df[response_col] = responses
 
    # Save temporary files
    temp_xlsx_path, temp_meta_path = get_temp_paths(agent_id)
    try:
        df.to_excel(temp_xlsx_path, index=False)
        meta = {
            "agentic_application_id": agent_id,
            "agent_name": agent_name,
            "agent_type": agent_type,
            "model_name": model_name,
            "session_id": session_id,
            "timestamp": timestamp,
            "response_column": response_col,
            "is_update_approval": False
        }
        with open(temp_meta_path, "w") as f:
            json.dump(meta, f)
    except Exception as e:
        log.error(f"Error saving temporary files for {agent_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to save temporary files: {str(e)}")
 
    # Return response
    return {
        "status": "preview_generated",
        "message": "Preview generated and saved successfully.",
        "filename": temp_xlsx_path.name,
        "response_column": response_col,
        "agentic_application_id": agent_id,
        "agent_name": agent_name,
        "queries": queries_list,
        "responses": responses,
        "rerun_url": f"/evaluation/consistency/rerun-response/?agentic_application_id={agent_id}",
        "approve_url": f"/evaluation/consistency/approve-responses/?agentic_application_id={agent_id}"
    }


@router.post("/evaluation/consistency/rerun-response", summary="Re-run Agent for Consistency")
async def rerun_agent_responses(
    # Parameters from user request
    agent_id: str = Form(...),
    # Inject the service needed
    core_consistency_service: CoreConsistencyEvaluationService = Depends(ServiceProvider.get_core_consistency_service)
):
    """
    Re-runs the agent on existing queries from a temporary session file.
    """
    temp_xlsx_path, temp_meta_path = get_temp_paths(agent_id)
    if not temp_xlsx_path.exists() or not temp_meta_path.exists():
        raise HTTPException(status_code=404, detail="Session files not found. Cannot re-run.")

    try:
        with open(temp_meta_path, "r") as f:
            meta = json.load(f)

        response_col = meta.get("response_column")
        df = pd.read_excel(temp_xlsx_path)
        queries = df["queries"].tolist()
    except Exception as e:
        log.error(f"Error reading session files for {agent_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to read session files: {str(e)}")

    # Re-run the agent for all queries
    new_responses = []
    for i, query in enumerate(queries):
        session = f"{meta['session_id']}_{i}"
        try:
            # --- FIX: Call the method on the INJECTED OBJECT, not the class ---
            res = await core_consistency_service.call_agent(
                query, meta['model_name'], agent_id, session
            )
            new_responses.append(res)
        except Exception as e:
            log.error(f"Error re-running agent for query {i+1}: {e}", exc_info=True)
            new_responses.append(f"Error: {str(e)}")

    df[response_col] = new_responses
    
    try:
        df.to_excel(temp_xlsx_path, index=False)
        meta["last_rerun"] = datetime.now(ist).isoformat()
        with open(temp_meta_path, "w") as f:
            json.dump(meta, f)
    except Exception as e:
        log.error(f"Error saving updated files for {agent_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to save updated files: {str(e)}")

    # Your return value logic is unchanged
    return {
        "message": "Re-run completed and file updated.",
        "filename": temp_xlsx_path.name,
        "response_column": response_col,
        "agentic_application_id": agent_id,
        "agent_name": meta.get("agent_name"),
        "queries": queries,
        "responses": new_responses,
        "rerun_url": f"/evaluation/consistency/rerun-response/?agentic_application_id={agent_id}",
        "approve_url": f"/evaluation/consistency/approve-responses/?agentic_application_id={agent_id}"
    }

DB_OPERATION_LOCK = asyncio.Lock()
@router.post("/evaluation/consistency/approve-responses", summary="Approve and Save Consistency Data")
async def approve_responses_endpoint(
    agentic_application_id: str = Form(...),
    # Inject the service needed for database operations
    consistency_service: ConsistencyService = Depends(ServiceProvider.get_consistency_service)
):
    """
    Approves the current set of responses and saves the data permanently.
    This finalizes the consistency benchmark for a new agent or an update.
    """
    temp_xlsx_path, temp_meta_path = get_temp_paths(agentic_application_id)
    if not temp_xlsx_path.exists() or not temp_meta_path.exists():
        raise HTTPException(status_code=404, detail="Approval files not found. The session may have expired.")

    # This lock prevents race conditions if two approvals for the same agent happen at once.
    async with DB_OPERATION_LOCK:
        log.info(f"Approval process for '{agentic_application_id}' has acquired the database lock.")
        try:
            with open(temp_meta_path, "r") as f:
                metadata = json.load(f)
            
            df_from_temp = pd.read_excel(temp_xlsx_path)
            is_update_approval = metadata.get("is_update_approval", False)

            if is_update_approval:
                # --- LOGIC FOR UPDATE APPROVAL ---
                log.info(f"Processing UPDATE approval for agent: {agentic_application_id}")
                timestamp = metadata['update_timestamp']
                
                # Use the service for all database calls
                latest_response_col = await consistency_service.get_latest_response_column_name(agentic_application_id)
                if latest_response_col:
                    await consistency_service.rename_column_with_timestamp(agentic_application_id, "queries", timestamp, "queries")
                    await consistency_service.rename_column_with_timestamp(agentic_application_id, latest_response_col, timestamp, "response")

                await consistency_service.add_column_to_agent_table(agentic_application_id, "queries", "TEXT")
                await consistency_service.add_column_to_agent_table(agentic_application_id, "reference_response", "TEXT")
                
                await consistency_service.update_column_by_row_id(agentic_application_id, "queries", df_from_temp['queries'].tolist())
                await consistency_service.update_column_by_row_id(agentic_application_id, "reference_response", df_from_temp['reference_response'].tolist())
                
                await consistency_service.update_agent_model_in_db(agentic_application_id, metadata['model_name'])
            else:
                # --- LOGIC FOR NEW AGENT APPROVAL ---
                log.info(f"Processing NEW agent approval for: {agentic_application_id}")
                
                # ✅ FIXED: Create agent record only during approval (not preview)
                agent_name = metadata.get("agent_name", "Unknown Agent")
                model_name = metadata.get("model_name", "gpt-4o")
                log.info(f"🗃️ Creating agent record for: {agentic_application_id}")
                try:
                    agent_type = metadata.get("agent_type", "Unknown Type")
                    await consistency_service.upsert_agent_record(agentic_application_id, agent_name, agent_type, model_name)
                except Exception as e:
                    log.error(f"Error creating agent record for {agentic_application_id}: {e}", exc_info=True)
                    raise HTTPException(status_code=500, detail=f"Failed to create agent record: {str(e)}")
                
                response_col = metadata.get("response_column")
                if not response_col:
                    raise ValueError("Metadata is missing the original response column name.")

                df_from_temp.rename(columns={response_col: "reference_response"}, inplace=True)
                
                # Use the service for the database call
                await consistency_service.create_and_insert_initial_data(
                    table_name=agentic_application_id,
                    df=df_from_temp,
                    col_name="reference_response"
                )

            # --- COMMON FINAL STEPS ---
            await consistency_service.update_queries_timestamp(agentic_application_id)
            await consistency_service.update_evaluation_timestamp(agentic_application_id)
            
            log.info(f"Database operations for '{agentic_application_id}' committed successfully.")

        except Exception as e:
            log.error(f"Error during approval process for {agentic_application_id}: {e}", exc_info=True)
            raise HTTPException(status_code=500, detail="An internal server error occurred during approval.")
        finally:
            # Cleanup temporary files regardless of success or failure
            if temp_xlsx_path.exists(): os.remove(temp_xlsx_path)
            if temp_meta_path.exists(): os.remove(temp_meta_path)
            log.info(f"Approval process for '{agentic_application_id}' has released lock.")
    
    # Your original return value is preserved
    return {
        "approved": True,
        "message": f"Data for agent '{agentic_application_id}' has been successfully saved."
    }



def get_robustness_preview_path(agentic_id: str) -> Path:
    """Returns the path for a temporary robustness preview file."""
    return PREVIEW_DIR / f"robustness_preview_{agentic_id}.json"

@router.post("/evaluation/robustness/preview-queries/{agentic_application_id}", summary="Preview Robustness Queries")
async def preview_robustness_queries(
    agentic_application_id: str,
    core_robustness_service: CoreRobustnessEvaluationService = Depends(ServiceProvider.get_core_robustness_service)
):
    """
    Generates a new set of robustness queries for preview.
    Does NOT run the agent or save to the main database.
    """
    log.info(f"Received request to generate robustness query preview for: {agentic_application_id}")
    try:
        # Step 1: Generate queries using the modular helper
        categories = [
            "Unexpected Input (Out-of-Scope Requests)",
            "Tool Error Simulation (Missing Specific Capability)",
            "Adversarial Input (Deceptive Details)"
        ]
        dataset = []
        for cat in categories:
            dataset += await core_robustness_service.generate_contextual_queries(agentic_application_id, cat)

        # Step 2: Save the queries to a temporary file
        preview_path = get_robustness_preview_path(agentic_application_id)
        with open(preview_path, "w") as f:
            json.dump(dataset, f)
        log.info(f"Saved preview queries for agent '{agentic_application_id}' to {preview_path}")

        # Step 3: Return the response
        return {
            "status": "preview_generated",
            "agent_id": agentic_application_id,
            "message": "Robustness queries have been generated for your review.",
            "generated_queries": [item['query'] for item in dataset],
            "rerun_url": f"/evaluation/robustness/preview-queries/{agentic_application_id}",
            "approve_url": f"/evaluation/robustness/approve-evaluation/{agentic_application_id}"
        }
    except ValueError as e:
        log.error(f"Validation error during query generation for '{agentic_application_id}': {e}")
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        log.error(f"An unexpected error occurred during query generation for '{agentic_application_id}': {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="An internal server error occurred.")


def get_robustness_preview_path(agentic_id: str) -> Path:
    """Returns the path for a temporary robustness preview file."""
    PREVIEW_DIR = Path("temp_previews")
    PREVIEW_DIR.mkdir(exist_ok=True)
    return PREVIEW_DIR / f"robustness_preview_{agentic_id}.json"



@router.post("/evaluation/approve-robustness-evaluation/{agentic_application_id}", summary="Approve and Run Robustness Evaluation")
async def approve_robustness_evaluation(
    agentic_application_id: str,
    # Inject the core service that has the pipeline logic
    core_robustness_service: CoreRobustnessEvaluationService = Depends(ServiceProvider.get_core_robustness_service)
):
    """
    Approves the previewed queries, runs the full evaluation pipeline,
    and saves the results to the database.
    """
    log.info(f"Received request to approve and run robustness evaluation for: {agentic_application_id}")
    
    preview_path = get_robustness_preview_path(agentic_application_id)
    if not preview_path.exists():
        raise HTTPException(status_code=404, detail="No preview queries found. Please generate queries before approving.")

    with open(preview_path, "r") as f:
        dataset = json.load(f)

    try:
      
        await core_robustness_service.execute_and_save_robustness_run(
            agent_id=agentic_application_id,
            dataset=dataset
        )
        
        os.remove(preview_path)

        return {
            "status": "success",
            "agent_id": agentic_application_id,
            "message": "Robustness evaluation has been completed successfully and results are saved to the database."
        }
    except Exception as e:
        log.error(f"An unexpected error occurred during the approved robustness run for '{agentic_application_id}': {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="An internal server error occurred during the evaluation.")


@router.get("/evaluation/available_agents/", summary="Get All Agent Evaluation Records")
async def get_all_agents_from_consistency_robustness_details_table(
    consistency_service: ConsistencyService = Depends(ServiceProvider.get_consistency_service)
):
    """
    Retrieves a list of all agent evaluation records from the database.
    """
    log.info("Received request to fetch all agent evaluation records.")
    try:
       
        all_agents = await consistency_service.get_all_agents()
        if not all_agents:
            log.info("No agent evaluation records found in the database.")
            return []
        return all_agents
    except Exception as e:
        log.error(f"An unexpected error occurred while fetching agent records: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="An internal server error occurred while fetching data.")
    

class UpdateEvaluationRequest(BaseModel):
    model_name: str
    queries: List[str]


def get_temp_paths(agentic_application_id: str):
    base = RESPONSES_TEMP_DIR / f"{agentic_application_id}"
    xlsx_path = base.with_suffix(".xlsx")
    meta_path = base.with_suffix(".meta.json")
    return xlsx_path, meta_path

@router.put("/evaluation/generate-update-preview/{agentic_application_id}", summary="Generate a Preview for an Agent Update")
async def generate_update_preview(
    agentic_application_id: str,
    request: UpdateEvaluationRequest,
    consistency_service: ConsistencyService = Depends(ServiceProvider.get_consistency_service),
    inference_service: CentralizedAgentInference = Depends(ServiceProvider.get_centralized_agent_inference)
):
    """
    Takes updated model/queries, runs a new evaluation, and returns a temporary preview.
    This does NOT permanently alter the database structure yet.
    """
    log.info(f"Generating an UPDATE PREVIEW for agent: {agentic_application_id}")
    
    model_name = request.model_name
    queries = [q.strip() for q in request.queries if q.strip()]
    if not queries:
        raise HTTPException(status_code=400, detail="Queries cannot be empty.")

    responses = []
    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    session_id = f"update_preview_{timestamp}"

    for i, query in enumerate(queries):
        try:
            req = AgentInferenceRequest(
                agentic_application_id=agentic_application_id,
                query=query, session_id=f"{session_id}_{i}", model_name=model_name, reset_conversation=True
            )
            res = await inference_service.run(req, insert_into_eval_flag=False)
            responses.append(res.get("response", "") if isinstance(res, dict) else str(res))
        except Exception as e:
            log.error(f"Error running inference for query {i+1} in update preview: {e}", exc_info=True)
            responses.append(f"Error: {str(e)}")

    df = pd.DataFrame({
        "queries": queries,
        "reference_response": responses
    })

    temp_xlsx_path, temp_meta_path = get_temp_paths(agentic_application_id)
    try:
        df.to_excel(temp_xlsx_path, index=False)

        meta = {
            "agentic_application_id": agentic_application_id,
            "model_name": model_name,
            "session_id": session_id,
            "response_column": "reference_response",
            "is_update_approval": True,
            "update_timestamp": timestamp
        }
        with open(temp_meta_path, "w") as f:
            json.dump(meta, f)
    except Exception as e:
        log.error(f"Error saving update preview files for {agentic_application_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to save update preview files: {str(e)}")

    return {
        "message": "Update preview generated. Please review and approve the new responses.",
        "agentic_application_id": agentic_application_id,
        "queries": queries,
        "responses": responses,
        "rerun_url": f"/evaluation/consistency/rerun-responses/?agentic_application_id={agentic_application_id}",
        "approve_url": f"/evaluation/consistency/approve-responses/?agentic_application_id={agentic_application_id}"
    }


@router.delete("/evaluation/delete-agent/{agentic_application_id}", summary="Delete Agent and All Associated Data")
async def delete_agent_details(
    agentic_application_id: str,
    consistency_service: ConsistencyService = Depends(ServiceProvider.get_consistency_service)
):
    """
    Completely deletes an agent and all of its associated data, including its
    consistency and robustness result tables. This is a destructive action.
    """
    log.warning(f"Received DELETE request for agent '{agentic_application_id}'.")
    try:
       
        await consistency_service.drop_agent_results_table(agentic_application_id)
        
        robustness_table_name = f"robustness_{agentic_application_id}"
        await consistency_service.drop_agent_results_table(robustness_table_name)
        
        await consistency_service.delete_agent_record_from_main_table(agentic_application_id)

        log.info(f"Successfully deleted all data for agent '{agentic_application_id}'.")

        return {
            "deleted": True,
            "agent_id": agentic_application_id,
            "message": "The agent and all of its associated data have been successfully deleted."
        }
    except Exception as e:
        log.error(f"An unexpected error occurred while deleting agent '{agentic_application_id}': {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="An internal server error occurred while deleting the agent.")



@router.get("/evaluation/agent/{agent_id}/recent_consistency_scores", summary="Get recent consistency scores for a specific agent")
async def get_consistency_scores(
    agent_id: str,
    consistency_service: ConsistencyService = Depends(ServiceProvider.get_consistency_service)
):
    try:
        # Step 1: Fetch agent metadata
        agent = await consistency_service.get_agent_by_id(agent_id)
        if not agent:
            raise HTTPException(status_code=404, detail=f"Agent with ID {agent_id} not found.")

        # Step 2: Fetch recent scores from the agent's table
        recent_scores = await consistency_service.data_repo.get_recent_consistency_scores(agent_id)

        # Step 3: Combine and return
        agent["recent_scores"] = await consistency_service.get_last_5_consistency_rows(recent_scores)
        return agent

    except Exception as e:
        log.error(f"Error fetching consistency scores for agent {agent_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to fetch recent consistency scores.")
    


@router.get("/evaluation/agent/{agent_id}/recent_robustness_scores", summary="Get recent robustness scores for a specific agent")
async def get_robustness_scores(
    agent_id: str,
    consistency_service: ConsistencyService = Depends(ServiceProvider.get_consistency_service)
):
    try:
        # Step 1: Fetch agent metadata
        agent = await consistency_service.get_agent_by_id(agent_id)
        if not agent:
            raise HTTPException(status_code=404, detail=f"Agent with ID {agent_id} not found.")

        # Step 2: Fetch recent robustness scores from the robustness_<agent_id> table
        robustness_table = f"robustness_{agent_id}"
        recent_scores = await consistency_service.data_repo.get_recent_consistency_scores(robustness_table)

        # Step 3: Filter last 5 rows based on timestamped score columns
        agent["recent_robustness_scores"] = await consistency_service.get_last_5_robustness_rows(recent_scores)
        return agent

    except Exception as e:
        log.error(f"Error fetching robustness scores for agent {agent_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to fetch recent robustness scores.")
    




def write_consistency_to_csv(records: List[Dict], file_path: str):
    df = pd.DataFrame(records)
    df.to_csv(file_path, index=False)




@router.get("/evaluation/agent/{agent_id}/download_consistency_record", summary="Download consistency records as CSV")
async def download_consistency_records(
    agent_id: str,
    consistency_service: ConsistencyService = Depends(ServiceProvider.get_consistency_service)
):
    try:
        table_name = agent_id  # assuming table name = agent_id
        records = await consistency_service.get_all_consistency_records(table_name)

        # Create temporary file with proper cross-platform path
        temp_dir = tempfile.gettempdir()
        file_path = os.path.join(temp_dir, f"{agent_id}_consistency.csv")
        write_consistency_to_csv(records, file_path)

        return FileResponse(file_path, filename=f"{agent_id}_consistency.csv", media_type="application/octet-stream")

    except Exception as e:
        log.error(f"Error generating consistency file for agent {agent_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to generate consistency file.")
    


@router.get("/evaluation/agent/{agent_id}/download_robustness_record", summary="Download robustness records as CSV")
async def download_robustness_records(
    agent_id: str,
    consistency_service: ConsistencyService = Depends(ServiceProvider.get_consistency_service)
):
    try:
        table_name = f"robustness_{agent_id}"  
        records = await consistency_service.get_all_robustness_records(table_name)

        # Create temporary file with proper cross-platform path
        temp_dir = tempfile.gettempdir()
        file_path = os.path.join(temp_dir, f"{agent_id}_robustness.csv")
        write_consistency_to_csv(records, file_path)

        return FileResponse(file_path, filename=f"{agent_id}_robustness.csv", media_type="application/octet-stream")

    except Exception as e:
        log.error(f"Error generating robustness file for agent {agent_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to generate robustness file.")
