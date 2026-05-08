# © 2024-25 Infosys Limited, Bangalore, India. All Rights Reserved.
import os
import time
import json
import uuid
from datetime import datetime, timezone
import asyncio
from pathlib import Path
import pandas as pd
from typing import Literal, Union, Any, List
from fastapi import APIRouter, Depends, HTTPException, Request, UploadFile, File, Form, Query
from fastapi.responses import JSONResponse, FileResponse
from fastapi.responses import StreamingResponse
from fastapi.encoders import jsonable_encoder
from src.utils.remote_model_client import RemoteSentenceTransformer as SentenceTransformer
from src.utils.remote_model_client import RemoteCrossEncoder as CrossEncoder
from src.utils.remote_model_client import RemoteSentenceTransformersUtil
util = RemoteSentenceTransformersUtil()

# Import the Redis-PostgreSQL manager
from src.auth.authorization_service import AuthorizationService
from src.database.redis_postgres_manager import RedisPostgresManager, TimedRedisPostgresManager, create_manager_from_env, create_timed_manager_from_env

from src.schemas import AgentInferenceRequest, ChatSessionRequest, OldChatSessionsRequest, StoreExampleRequest, StoreExampleResponse, M2MInferenceRequest

from src.database.services import ChatService, FeedbackLearningService, WorkflowService, TaskRegistryService
from src.database.repositories import QueryTokenUsageRepository
from src.inference.inference_utils import EpisodicMemoryManager
from src.inference.centralized_agent_inference import CentralizedAgentInference
from src.inference.workflow_inference import WorkflowInference
from src.api.dependencies import ServiceProvider # The dependency provider
from src.auth.dependencies import get_current_user, get_user_info_from_request, setup_tool_user_context
from src.decorators.tool_access import ToolUserContext
from src.utils.file_manager import FileManager
from src.utils.kafka_manager import KafkaManager

from src.utils.secrets_handler import current_user_department, current_user_email


from telemetry_wrapper import logger as log, update_session_context

from src.models.model_service import ModelService
from src.models.base_ai_model_service import BaseAIModelService
from src.auth.models import UserRole, User



task_tracker: dict[str, asyncio.Task] = {}

# Create an APIRouter instance for chat-related endpoints
router = APIRouter(prefix="/chat", tags=["Chat / Inference"])

STORAGE_PROVIDER = os.getenv('STORAGE_PROVIDER', "")

# Initialize the global manager
_global_manager = None

async def get_global_manager():
    """Get or create the global RedisPostgresManager instance (async)"""
    global _global_manager
    if _global_manager is None and RedisPostgresManager is not None:
        try:
            base_manager = await create_manager_from_env()
            _global_manager = TimedRedisPostgresManager(base_manager, time_threshold_minutes=15)
            log.info("Global TimedRedisPostgresManager initialized successfully")
        except Exception as e:
            log.error(f"Failed to initialize TimedRedisPostgresManager: {e}")
            _global_manager = None
    return _global_manager

async def save_feedback_and_logs(
    inference_request: AgentInferenceRequest,
    final_response: dict,
    feedback_learning_service: FeedbackLearningService,
    chat_service: ChatService,
    session_id: str,
    time_taken: float,
    is_streaming: bool = False,
    department_name: str = None
):
    """
    Helper function to handle post-inference logic:
    1. Saving Plan/Verifier Feedback
    2. Updating Chat History Response Time
    """
    # 1. Handle Feedback / Verifier Data
    if inference_request.plan_verifier_flag:
        try:
            # Adjust extraction logic based on whether response is a dict or accumulated chunks
            # For this example, assuming final_response follows the standard dictionary structure
            if isinstance(final_response, dict) and "plan" in final_response:
                current_plan = "\n".join(i for i in final_response.get("plan", []))
                old_plan = "\n".join(i for i in inference_request.prev_response.get("plan", []))
                
                await feedback_learning_service.save_feedback(
                    agent_id=inference_request.agentic_application_id,
                    query=inference_request.query,
                    old_final_response=old_plan,
                    old_steps="", # Adjust based on actual data availability
                    new_final_response=current_plan,
                    feedback=inference_request.plan_feedback, 
                    new_steps="",
                    lesson="",
                    department_name=department_name
                )
                log.info(f"[{session_id}] Data saved for future learnings.")
        except Exception as e:
            log.warning(f"[{session_id}] Could not save data for future learnings: {e}")

    # 2. Update Chat History Response Time
    try:
        if not await chat_service.is_python_based_agent(inference_request.agentic_application_id):
            await chat_service.update_latest_response_time(
                agentic_application_id=inference_request.agentic_application_id,
                session_id=session_id,
                response_time=time_taken
            )
            log.info(f"[{session_id}] Updated chat history response time: {time_taken:.2f}s")
    except Exception as e:
        log.warning(f"[{session_id}] Could not update response time in chat history: {e}")

@router.post("/m2m_inference")
async def m2m_inference_endpoint(
    request: Request,
    chat_request: M2MInferenceRequest,
    kafka_manager: KafkaManager = Depends(ServiceProvider.get_kafka_manager),
    task_registry_service: TaskRegistryService = Depends(ServiceProvider.get_task_registry_service),
    user_data: User = Depends(get_current_user)
    ):
    """
    API endpoint to start the machine-to-machine (M2M) inference process.
    Adds the request to Kafka queue for async processing.
    """
    
    # fetching the framework type
    task_id = f"task_{chat_request.framework_type.code}_{uuid.uuid4().hex[:12]}"
    # Session ID is task_id + user email (no user input needed)
    session_id = f"{task_id}_{current_user_email.get()}"
    
    # Register task with computed session_id
    await task_registry_service.register_task(
        task_id=task_id,
        agentic_application_id=chat_request.agentic_application_id,
        user_session_id=session_id,
        query=chat_request.query,
        model_name=chat_request.model_name,
        created_by=user_data.email if user_data else None
    )
    
    # Send request to Kafka for async processing by AgentWorker
    success = kafka_manager.send_agent_request(
        agent_call_id=task_id,
        agentic_application_id=chat_request.agentic_application_id,
        session_id=session_id,
        model_name=chat_request.model_name,
        query=chat_request.query,
        user_email=current_user_email.get(),  # Pass user_email from context
        reset_conversation=chat_request.reset_conversation,
    )
    
    if not success:
        # Mark task as failed if Kafka queuing fails
        await task_registry_service.mark_task_failed(
            task_id=task_id,
            error_message="Failed to queue task to Kafka"
        )
        raise HTTPException(
            status_code=500,
            detail="Failed to queue M2M task for async processing"
        )
    
    log.info(f"[{session_id}] M2M Task {task_id} added to queue")
    
    # Return task_id for client to poll progress
    return {
        "status": "queued",
        "task_id": task_id,
        "session_id": session_id,
        "message": f"M2M task has been queued for async processing. Use /chat/task/{task_id}/status to check status and /chat/task/{task_id}/result to get the final result."
    }


@router.post("/batch_m2m_inference")
async def batch_m2m_inference_endpoint(
    request: Request,
    chat_requests: List[M2MInferenceRequest],
    kafka_manager: KafkaManager = Depends(ServiceProvider.get_kafka_manager),
    task_registry_service: TaskRegistryService = Depends(ServiceProvider.get_task_registry_service),
    user_data: User = Depends(get_current_user)
    ):
    """
    API endpoint to start batch machine-to-machine (M2M) inference process.
    Adds multiple requests to Kafka queue for async processing.
    All tasks share a common batch prefix for identification.
    """
    # Generate a unique batch prefix
    batch_prefix = f"batch_{uuid.uuid4().hex[:12]}"
    user_email = current_user_email.get()
    
    queued_tasks = []
    failed_tasks = []
    
    for idx, chat_request in enumerate(chat_requests):
        # Create task_id with batch prefix
        task_id = f"{batch_prefix}_task_{chat_request.framework_type.code}_{idx}"
        # Session ID is task_id + user email (no user input needed)
        session_id = f"{task_id}_{user_email}"
        
        # Register task with computed session_id
        await task_registry_service.register_task(
            task_id=task_id,
            agentic_application_id=chat_request.agentic_application_id,
            user_session_id=session_id,
            query=chat_request.query,
            model_name=chat_request.model_name,
            batch_id=batch_prefix,
            created_by=user_data.email if user_data else None
        )
        
        # Send request to Kafka for async processing by AgentWorker
        success = kafka_manager.send_agent_request(
            agent_call_id=task_id,
            agentic_application_id=chat_request.agentic_application_id,
            session_id=session_id,
            model_name=chat_request.model_name,
            query=chat_request.query,
            user_email=user_email,  # Pass user_email from context
            reset_conversation=chat_request.reset_conversation,
        )
        
        if success:
            queued_tasks.append({
                "task_id": task_id,
                "session_id": session_id,
                "agentic_application_id": chat_request.agentic_application_id
            })
            log.info(f"[{session_id}] Batch M2M Task {task_id} added to queue")
        else:
            # Mark task as failed in registry
            await task_registry_service.mark_task_failed(
                task_id=task_id,
                error_message="Failed to queue task to Kafka"
            )
            failed_tasks.append({
                "index": idx,
                "task_id": task_id,
                "session_id": session_id,
                "agentic_application_id": chat_request.agentic_application_id,
                "error": "Failed to queue task"
            })
            log.error(f"[{session_id}] Failed to add batch M2M task to queue")
    
    log.info(f"Batch {batch_prefix}: {len(queued_tasks)} queued, {len(failed_tasks)} failed")
    
    return {
        "status": "queued" if queued_tasks else "failed",
        "batch_id": batch_prefix,
        "total_requests": len(chat_requests),
        "queued_count": len(queued_tasks),
        "failed_count": len(failed_tasks),
        "queued_tasks": queued_tasks,
        "failed_tasks": failed_tasks,
        "message": f"Batch M2M tasks queued for async processing. Use /chat/batch/{batch_prefix}/status to check batch status."
    }


# ---------------------------------------------------------
# Task Registry Endpoints
# ---------------------------------------------------------

@router.get("/task/{task_id}/status")
async def get_task_status_endpoint(
    task_id: str,
    task_registry_service: TaskRegistryService = Depends(ServiceProvider.get_task_registry_service)
):
    """
    Get the current status of an M2M task.
    
    Args:
        task_id: The unique task identifier returned from m2m_inference
        
    Returns:
        Task status and metadata including:
        - status: queued | processing | completed | failed
        - response_time_ms: Processing time if completed
        - error_message: Error details if failed
    """
    result = await task_registry_service.get_task_status(task_id)
    if not result.get("success"):
        raise HTTPException(status_code=404, detail=result.get("message", "Task not found"))
    return result


@router.get("/task/{task_id}/result")
async def get_task_result_endpoint(
    task_id: str,
    task_registry_service: TaskRegistryService = Depends(ServiceProvider.get_task_registry_service),
    chat_service: ChatService = Depends(ServiceProvider.get_chat_service),
    user_data: User = Depends(get_current_user)
):
    """
    Get the result of a completed M2M task, including the conversation history.
    
    Args:
        task_id: The unique task identifier
        
    Returns:
        Task details and conversation history if completed.
        For incomplete tasks, returns current status only.
    """
    result = await task_registry_service.get_task_result(
        task_id=task_id,
        chat_service=chat_service,
        role=user_data.role if user_data else None,
        department_name=user_data.department_name if user_data else None
    )
    if not result.get("success"):
        raise HTTPException(status_code=404, detail=result.get("message", "Task not found"))
    return result


@router.get("/batch/{batch_id}/status")
async def get_batch_status_endpoint(
    batch_id: str,
    task_registry_service: TaskRegistryService = Depends(ServiceProvider.get_task_registry_service)
):
    """
    Get the aggregated status summary for a batch of M2M tasks.
    
    Args:
        batch_id: The batch identifier returned from batch_m2m_inference
        
    Returns:
        Aggregated batch status including:
        - total: Total number of tasks
        - queued, processing, completed, failed: Counts by status
        - avg_response_time_ms: Average processing time for completed tasks
        - is_complete: True if all tasks finished (completed or failed)
    """
    result = await task_registry_service.get_batch_status(batch_id)
    if result.get("error"):
        raise HTTPException(status_code=404, detail=result.get("error"))
    return result

@router.get("/batch/{batch_id}/get-excel-report")
async def get_excel_batch_report_endpoint(
    batch_id: str,
    task_registry_service: TaskRegistryService = Depends(ServiceProvider.get_task_registry_service),
    chat_service: ChatService = Depends(ServiceProvider.get_chat_service),
    user_data: User = Depends(get_current_user)
):
    """
    This function will take a batch ID, retrieve all the tasks related to that batch and asynchronously call final response for all the tasks which are completed and failed, generate an Excel report with their status and if it is not pending there response also will be there, and return the download link of the report.
    
    Args:
        batch_id: The batch identifier
        
    Returns:
        Download link for the generated Excel report.
    """
    # Ensure reports directory exists
    reports_dir = Path("reports")
    reports_dir.mkdir(exist_ok=True)
    
    # Retrieve all tasks for the batch
    batch_tasks_result = await task_registry_service.get_batch_tasks(batch_id)
    
    if not batch_tasks_result.get("success"):
        raise HTTPException(status_code=404, detail=f"Batch '{batch_id}' not found or has no tasks.")
    
    tasks = batch_tasks_result.get("tasks", [])
    
    if not tasks:
        raise HTTPException(status_code=404, detail=f"No tasks found for batch '{batch_id}'.")
    
    # Fetch results for completed and failed tasks concurrently
    async def fetch_task_result(task: dict) -> dict:
        """Fetch task result including response for completed/failed tasks."""
        task_id = task.get("task_id")
        status = task.get("status")
        
        result_data = {
            "task_id": task_id,
            "status": status,
            "agentic_application_id": task.get("agentic_application_id", ""),
            "query": task.get("query", ""),
            "model_name": task.get("model_name", ""),
            "created_at": task.get("created_at", ""),
            "started_at": task.get("started_at", ""),
            "completed_at": task.get("completed_at", ""),
            "response_time_ms": task.get("response_time_ms", ""),
            "error_message": task.get("error_message", ""),
            "response": "",
            "executor_messages":[]
        }
        
        # Fetch detailed result for completed, failed, and processing tasks
        if status in ["completed", "failed", "processing"]:
            try:
                task_result = await task_registry_service.get_task_result(
                    task_id=task_id,
                    chat_service=chat_service,
                    role=user_data.role if user_data else None,
                    department_name=user_data.department_name if user_data else None
                )
                
                if task_result.get("success"):
                    # Extract response from conversation if available
                    conversation = task_result.get("conversation", {})
                    executor_messages = conversation.get("executor_messages", [])
                    
                    if executor_messages:
                        # Get the last response from executor_messages
                        last_message = executor_messages[-1] if executor_messages else {}
                        response_text = last_message.get("response", "")
                        
                        # If response is a dict or list, convert to JSON string
                        if isinstance(response_text, (dict, list)):
                            response_text = json.dumps(response_text, ensure_ascii=False)
                        
                        result_data["response"] = response_text
                        result_data["executor_messages"] = executor_messages
                    
                    # Update error_message from result if available
                    if task_result.get("error_message"):
                        result_data["error_message"] = task_result.get("error_message")
                        
            except Exception as e:
                log.warning(f"Could not fetch result for task {task_id}: {e}")
                result_data["error_message"] = f"Error fetching result: {str(e)}"
                result_data["response"] = f"Error fetching result: {str(e)}"
        
        return result_data
    
    # Fetch all task results concurrently
    task_results = await asyncio.gather(
        *[fetch_task_result(task) for task in tasks],
        return_exceptions=True
    )
    
    # Process results, handling any exceptions
    report_data = []
    for i, result in enumerate(task_results):
        if isinstance(result, Exception):
            # If fetch failed, use basic task info
            task = tasks[i]
            report_data.append({
                "task_id": task.get("task_id", ""),
                "status": task.get("status", ""),
                "agentic_application_id": task.get("agentic_application_id", ""),
                "query": task.get("query", ""),
                "model_name": task.get("model_name", ""),
                "created_at": task.get("created_at", ""),
                "started_at": task.get("started_at", ""),
                "completed_at": task.get("completed_at", ""),
                "response_time_ms": task.get("response_time_ms", ""),
                "error_message": str(result),
                "executor_messages": task.get("executor_messages", []),
                "response": ""
            })
        else:
            report_data.append(result)
    
    # Create DataFrame and generate Excel report
    df = pd.DataFrame(report_data)
    
    # Reorder columns for better readability
    column_order = [
        "task_id",
        "status",
        "agentic_application_id",
        "query",
        "response",
        "error_message",
        "executor_messages",
        "model_name",
        "response_time_ms",
        "created_at",
        "started_at",
        "completed_at"
    ]
    df = df[[col for col in column_order if col in df.columns]]
    
    # Generate unique filename with timestamp
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"batch_report_{batch_id}_{timestamp}.xlsx"
    file_path = reports_dir / filename
    
    # Save to Excel
    try:
        df.to_excel(file_path, index=False, engine='openpyxl')
        log.info(f"Excel report generated: {file_path}")
    except Exception as e:
        log.error(f"Failed to generate Excel report: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to generate Excel report: {str(e)}")
    
    # Return the file as a download
    return FileResponse(
        path=str(file_path),
        filename=filename,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )


@router.get("/batch/{batch_id}/tasks")
async def get_batch_tasks_endpoint(
    batch_id: str,
    task_registry_service: TaskRegistryService = Depends(ServiceProvider.get_task_registry_service)
):
    """
    Get all tasks belonging to a batch.
    
    Args:
        batch_id: The batch identifier
        
    Returns:
        List of all tasks in the batch with their individual status.
    """
    result = await task_registry_service.get_batch_tasks(batch_id)
    return result


@router.get("/tasks/me")
async def get_my_tasks_endpoint(
    limit: int = Query(default=50, le=500, description="Maximum number of tasks to return"),
    status: str = Query(default=None, description="Filter by status: queued | processing | completed | failed"),
    task_registry_service: TaskRegistryService = Depends(ServiceProvider.get_task_registry_service),
    user_data: User = Depends(get_current_user)
):
    """
    Get M2M tasks created by the current user.
    
    Args:
        limit: Maximum number of tasks to return (default 50, max 500)
        status: Optional filter by task status
        
    Returns:
        List of tasks created by the authenticated user.
    """
    result = await task_registry_service.get_user_tasks(
        user_email=user_data.email,
        limit=limit,
        status=status
    )
    return result


@router.get("/tasks/agent/{agent_id}")
async def get_agent_tasks_endpoint(
    agent_id: str,
    limit: int = Query(default=50, le=500, description="Maximum number of tasks to return"),
    status: str = Query(default=None, description="Filter by status: queued | processing | completed | failed"),
    task_registry_service: TaskRegistryService = Depends(ServiceProvider.get_task_registry_service)
):
    """
    Get M2M tasks for a specific agent or workflow.
    
    Args:
        agent_id: The agent or workflow ID
        limit: Maximum number of tasks to return
        status: Optional filter by task status
        
    Returns:
        List of tasks for the specified agent/workflow.
    """
    result = await task_registry_service.get_agent_tasks(
        agentic_application_id=agent_id,
        limit=limit,
        status=status
    )
    return result


@router.post("/inference")
async def run_agent_inference_endpoint(
                        request: Request,
                        inference_request: AgentInferenceRequest,
                        inference_service: CentralizedAgentInference = Depends(ServiceProvider.get_centralized_agent_inference),
                        workflow_inference: WorkflowInference = Depends(ServiceProvider.get_workflow_inference),
                        feedback_learning_service: FeedbackLearningService = Depends(ServiceProvider.get_feedback_learning_service),
                        chat_service: ChatService = Depends(ServiceProvider.get_chat_service),
                        authorization_service: AuthorizationService = Depends(ServiceProvider.get_authorization_service),
                        user_data: User = Depends(get_current_user),
                        tool_context: ToolUserContext = Depends(setup_tool_user_context),
                        kafka_manager: KafkaManager = Depends(ServiceProvider.get_kafka_manager),
                        query_token_usage_repo: QueryTokenUsageRepository = Depends(ServiceProvider.get_query_token_usage_repo)
                    ):
    """
    
    API endpoint to run agent inference.

    This is a unified endpoint that handles various agent types, HITL scenarios, and workflow execution.
    When is_workflow_call is True, it executes a workflow instead of a single agent.

    Parameters:
    
    - request: The FastAPI Request object.
    - inference_request: Pydantic model containing all inference parameters.
    - inference_service: Dependency-injected CentralizedAgentInference instance.
    - workflow_inference: Dependency-injected WorkflowInference instance.
    - feedback_learning_service: Dependency-injected FeedbackLearningService instance.

    Returns:
    - Dict[str, Any]: A dictionary with the agent's response or workflow execution result.
    """
    role = user_data.role
    
    # Check department-specific execute permission for agents
    user_department = user_data.department_name
    if not await authorization_service.check_operation_permission(user_data.email, user_data.role, "execute", "agents", user_department):
        raise HTTPException(
            status_code=403,
            detail=f"Access denied. User does not have execute permission for agents in department '{user_department}'."
        )
    
    start_time = time.monotonic()
    start_time_stamp = datetime.now(timezone.utc).replace(tzinfo=None)
    
    # 1. User & Session Setup
    role = user_data.role
    user_id = request.cookies.get("user_id") or user_data.email
    user_session = request.cookies.get("user_session")
    session_id = inference_request.session_id

    # Open a fresh per-request token accumulator so every LLM hook call during
    # this inference can append its record — enabling per-query token totals.
    from litellm_standalone_tracker import init_request_accumulator
    init_request_accumulator(session_id)

    #message queue
    message_queue = inference_request.message_queue

    
    # Update context
    update_session_context(user_session=user_session, user_id=user_id)

    log.info(f"[{session_id}] Received inference request. Streaming: {inference_request.enable_streaming_flag}")

    # 2. Concurrency Control (Task Locking)
    existing_task = task_tracker.get(session_id)
    if existing_task and not existing_task.done():
        log.info(f"[{session_id}] Concurrent inference request rejected.")
        raise HTTPException(
            status_code=499,
            detail="Parallel inference requests are not allowed for this session."
        )

    # 3. Update Context to 'Processing'
    update_session_context(
        agent_id=inference_request.agentic_application_id,
        session_id=session_id,
        model_used=inference_request.model_name,
        user_query=inference_request.query,
        response="Processing..."
    )

   # Modify inference request flags based on user role permissions (dynamic access control)
    # Get role permissions once to avoid multiple DB calls (user_department already defined above)
    role_permissions = await authorization_service.role_repo.get_role_permissions(user_department, role)
    
    # Check tool_verifier_flag access
    if inference_request.tool_verifier_flag:
        has_tool_verifier_access = role_permissions.get('tool_verifier_flag_access', False) if role_permissions else False
        if not has_tool_verifier_access:
            inference_request.tool_verifier_flag = False
            log.info(f"[{session_id}] Tool verifier flag disabled - role '{role}' doesn't have tool_verifier_flag_access permission")
    
    # Check plan_verifier_flag access
    if inference_request.plan_verifier_flag:
        has_plan_verifier_access = role_permissions.get('plan_verifier_flag_access', False) if role_permissions else False
        if not has_plan_verifier_access:
            inference_request.plan_verifier_flag = False
            log.info(f"[{session_id}] Plan verifier flag disabled - role '{role}' doesn't have plan_verifier_flag_access permission")
    
    # Check evaluation_flag access
    if inference_request.evaluation_flag:
        has_evaluation_access = role_permissions.get('online_evaluation_flag_access', False) if role_permissions else False
        if not has_evaluation_access:
            inference_request.evaluation_flag = False
            log.info(f"[{session_id}] Online Evaluation flag disabled - role '{role}' doesn't have online_evaluation_flag_access permission")

    # Check validator_flag access
    if inference_request.validator_flag:
        has_validator_access = role_permissions.get('validator_access', False) if role_permissions else False
        if not has_validator_access:
            inference_request.validator_flag = False
            log.info(f"[{session_id}] Validator flag disabled - role '{role}' doesn't have validator_access permission")

    # Check file_context_management_flag access
    if inference_request.file_context_management_flag:
        has_file_context_access = role_permissions.get('file_context_access', False) if role_permissions else False
        if not has_file_context_access:
            inference_request.file_context_management_flag = False
            log.info(f"[{session_id}] File context management flag disabled - role '{role}' doesn't have file_context_access permission")

    # Check response_formatting_flag access (canvas view)
    if inference_request.response_formatting_flag:
        has_canvas_view_access = role_permissions.get('canvas_view_access', False) if role_permissions else False
        if not has_canvas_view_access:
            inference_request.response_formatting_flag = False
            log.info(f"[{session_id}] Response formatting flag disabled - role '{role}' doesn't have canvas_view_access permission")

    # Check context_flag access
    if inference_request.context_flag:
        has_context_access = role_permissions.get('context_access', False) if role_permissions else False
        if not has_context_access:
            inference_request.context_flag = False
            log.info(f"[{session_id}] Context flag disabled - role '{role}' doesn't have context_access permission")

    # ---------------------------------------------------------
    # Handle Message Queue Mode - Async Execution via Worker
    # ---------------------------------------------------------
    if message_queue:
        # Generate unique task/agent_call_id
        task_id = f"task_{uuid.uuid4().hex[:16]}"
        
        # Send request to Kafka for async processing by AgentWorker
        success = kafka_manager.send_agent_request(
            agent_call_id=task_id,
            agentic_application_id=inference_request.agentic_application_id,
            session_id=session_id,
            model_name=inference_request.model_name,
            query=inference_request.query,
            user_role=role,
            department_name=user_data.department_name,
            username=user_data.email,
            user_email=user_data.email,  # Pass user_email
            reset_conversation=inference_request.reset_conversation,
            tool_verifier_flag=inference_request.tool_verifier_flag,
            plan_verifier_flag=inference_request.plan_verifier_flag,
            evaluation_flag=inference_request.evaluation_flag,
            validator_flag=inference_request.validator_flag,
            context_flag=inference_request.context_flag,
            file_context_management_flag=inference_request.file_context_management_flag,
            response_formatting_flag=inference_request.response_formatting_flag,
            temperature=inference_request.temperature,
            framework_type=inference_request.framework_type,
            tool_feedback=inference_request.tool_feedback,
            is_plan_approved=inference_request.is_plan_approved,
            plan_feedback=inference_request.plan_feedback,
            mentioned_agentic_application_id=inference_request.mentioned_agentic_application_id,
            interrupt_items=inference_request.interrupt_items,
            uploaded_files=inference_request.uploaded_files,
        )
        
        if not success:
            raise HTTPException(
                status_code=500,
                detail="Failed to queue task for async processing"
            )
        
        log.info(f"[{session_id}] Task {task_id} added to queue")
        
        # Return task_id for client to poll progress
        return {
            "status": "queued",
            "task_id": task_id,
            "session_id": session_id,
            "message": "Task has been queued for async processing. Use /chat/task/{task_id}/progress to check status and /chat/task/{task_id}/result to get the final result."
        }

    # ---------------------------------------------------------
    # Check if this is a Workflow Call
    # ---------------------------------------------------------
    if inference_request.agentic_application_id.startswith("wf_") or inference_request.agentic_application_id.startswith("ppl_"):
        # Validate workflow_id is provided
        workflow_id = inference_request.agentic_application_id
        if not workflow_id:
            raise HTTPException(
                status_code=400,
                detail="workflow_id is required when is_workflow_call is True"
            )
        
        log.info(f"[{session_id}] Routing to workflow execution for workflow_id: {workflow_id}")
        
        # ---------------------------------------------------------
        # Workflow Streaming Response
        # ---------------------------------------------------------
        if inference_request.enable_streaming_flag:
            async def workflow_stream_generator():
                """Generate SSE events from workflow execution."""
                try:
                    task_tracker[session_id] = asyncio.current_task()
                    
                    async for event in workflow_inference.run_workflow(
                        workflow_id=workflow_id,
                        session_id=session_id,
                        model_name=inference_request.model_name,
                        input_query=inference_request.query,
                        project_name=f"workflow_{workflow_id}",
                        reset_conversation=inference_request.reset_conversation,
                        plan_verifier_flag=inference_request.plan_verifier_flag,
                        is_plan_approved=inference_request.is_plan_approved,
                        plan_feedback=inference_request.plan_feedback,
                        tool_interrupt_flag=inference_request.tool_verifier_flag,
                        tool_feedback=inference_request.tool_feedback,
                        context_flag=inference_request.context_flag,
                        evaluation_flag=inference_request.evaluation_flag,
                        validator_flag=inference_request.validator_flag,
                        temperature=inference_request.temperature or 0.0,
                        role=str(role),
                        chat_file_upload=inference_request.uploaded_files
                    ):
                        yield json.dumps(jsonable_encoder(event)) + "\n"

                except HTTPException as e:
                    error_event = {
                        'event_type': 'error',
                        'message': e.detail
                    }
                    yield json.dumps(error_event) + "\n"

                except Exception as e:
                    log.error(f"[{session_id}] Workflow execution error: {e}")
                    error_event = {
                        'event_type': 'error',
                        'message': str(e)
                    }
                    yield json.dumps(error_event) + "\n"
                    
                finally:
                    end_time = time.monotonic()
                    time_taken = end_time - start_time
                    
                    # Cleanup Task Tracker
                    if session_id in task_tracker:
                        del task_tracker[session_id]
                    
                    update_session_context(
                        agent_id='Unassigned', session_id='Unassigned', 
                        model_used='Unassigned', user_query='Unassigned', response='Unassigned'
                    )
                    log.info(f"[{session_id}] Workflow streaming completed in {time_taken:.2f}s")

            return StreamingResponse(workflow_stream_generator(), media_type="application/json")

        # ---------------------------------------------------------
        # Workflow Non-Streaming Response (Synchronous)
        # ---------------------------------------------------------
        else:
            async def do_workflow_inference():
                try:
                    events = []
                    final_event = None

                    async for event in workflow_inference.run_workflow(
                        workflow_id=workflow_id,
                        session_id=session_id,
                        model_name=inference_request.model_name,
                        input_query=inference_request.query,
                        project_name=f"workflow_{workflow_id}",
                        reset_conversation=inference_request.reset_conversation,
                        plan_verifier_flag=inference_request.plan_verifier_flag,
                        is_plan_approved=inference_request.is_plan_approved,
                        plan_feedback=inference_request.plan_feedback,
                        tool_interrupt_flag=inference_request.tool_verifier_flag,
                        tool_feedback=inference_request.tool_feedback,
                        context_flag=inference_request.context_flag,
                        evaluation_flag=inference_request.evaluation_flag,
                        validator_flag=inference_request.validator_flag,
                        temperature=inference_request.temperature or 0.0,
                        chat_file_upload = inference_request.uploaded_files,
                        role=str(role)
                    ):
                        response = event

                    return response
                except asyncio.CancelledError:
                    log.warning(f"[{session_id}] Workflow task cancelled.")
                    raise
                except StopAsyncIteration:
                    return {"status": "success", "events": [], "final_event": None}

            # Create Task
            new_task = asyncio.create_task(do_workflow_inference())
            task_tracker[session_id] = new_task

            try:
                response = await new_task
                end_time = time.monotonic()
                time_taken = end_time - start_time
                
                log.info(f"[{session_id}] Workflow execution completed in {time_taken:.2f}s")
                return response

            except asyncio.CancelledError:
                raise HTTPException(status_code=499, detail="Request was cancelled")
            except Exception as e:
                log.error(f"[{session_id}] Workflow execution failed: {e}")
                raise HTTPException(status_code=500, detail=f"Workflow execution failed: {str(e)}")
            finally:
                # Cleanup
                update_session_context(
                    agent_id='Unassigned', session_id='Unassigned', 
                    model_used='Unassigned', user_query='Unassigned', response='Unassigned'
                )
                if session_id in task_tracker and task_tracker[session_id].done():
                    del task_tracker[session_id]

    # ---------------------------------------------------------
    # Scenario A: Streaming Response (Regular Agent)
    # ---------------------------------------------------------
    if inference_request.enable_streaming_flag:
        
        async def stream_generator():
            full_accumulated_response = {} # To store data needed for post-processing logic
            
            try:
                # Add task to tracker (Self-reference not easily possible in generator, 
                # so we rely on the tracker logic wrapping the endpoint or simple key existence)
                task_tracker[session_id] = asyncio.current_task()
                
                async for chunk in inference_service.run(inference_request, role=role, department_name=user_department, user_name=user_data.username):
                    # Accumulate chunk data if needed for post-processing (e.g., feedback saving)
                    # This logic depends on your chunk structure. 
                    # If the last chunk contains the full result, verify that.
                    if isinstance(chunk, dict) and "query" in chunk:
                        full_accumulated_response.update(chunk) 
                    else:
                        yield json.dumps(jsonable_encoder(chunk)) + "\n"

            except Exception as e:
                log.error(f"[{session_id}] Streaming error: {e}")
                yield json.dumps({"error": str(e)}) + "\n"
            finally:
                # --- Post-Processing inside Generator (After stream ends) ---
                end_time = time.monotonic()
                time_taken = end_time - start_time
                
                # Cleanup Task Tracker
                if session_id in task_tracker:
                    del task_tracker[session_id]
                
                update_session_context(
                    agent_id='Unassigned', session_id='Unassigned', 
                    model_used='Unassigned', user_query='Unassigned', response='Unassigned'
                )

                log.info(f"[{session_id}] Streaming completed in {time_taken:.2f}s")
                last_message = dict()
                if "executor_messages" in full_accumulated_response and isinstance(full_accumulated_response["executor_messages"], list) and full_accumulated_response["executor_messages"]:
                    last_message = full_accumulated_response["executor_messages"][-1]
                    last_message["start_timestamp"] = start_time_stamp.isoformat()
                # Run background logic (Feedback, DB updates)
                # We await here to ensure it completes before the connection fully closes
                await save_feedback_and_logs(
                    inference_request=inference_request,
                    final_response=full_accumulated_response,
                    feedback_learning_service=feedback_learning_service,
                    chat_service=chat_service,
                    session_id=session_id,
                    time_taken=time_taken,
                    is_streaming=True,
                    department_name=user_department
                )
                if chat_service and not await chat_service.is_python_based_agent(inference_request.agentic_application_id):
                    response_time = await inference_service.update_response_time(agent_id=inference_request.agentic_application_id, session_id=session_id, start_time=start_time, time_stamp=start_time_stamp)
                    # Inject per-query token totals into the same checkpoint
                    from litellm_standalone_tracker import get_and_clear_accumulator
                    token_records = get_and_clear_accumulator(session_id)
                    if token_records and last_message:
                        agent_name = token_records[0].get("agent_name") if token_records else None
                        await inference_service.update_token_usage_in_graph(
                            agent_id=inference_request.agentic_application_id,
                            session_id=session_id,
                            token_records=token_records,
                        )
                        last_message["token_usage"] = {
                            "prompt_tokens":     sum(r.get("prompt_tokens", 0)     for r in token_records),
                            "completion_tokens": sum(r.get("completion_tokens", 0) for r in token_records),
                            "total_tokens":      sum(r.get("total_tokens", 0)      for r in token_records),
                            "cached_tokens":     sum(r.get("cached_tokens", 0)     for r in token_records),
                            "total_cost":        sum(r.get("total_cost", 0.0)      for r in token_records),
                            "llm_calls":         token_records,
                        }
                        asyncio.create_task(query_token_usage_repo.insert(
                            session_id=session_id,
                            user_id=user_data.email,
                            agent_id=inference_request.agentic_application_id,
                            agent_name=agent_name,
                            query=inference_request.query,
                            token_records=token_records,
                        ))
                else:
                    response_time = time.monotonic() - start_time
                    response_time_details = {
                        "response_time_details":{
                            "response_time": response_time,
                            "start_timestamp": start_time_stamp.isoformat()
                        }
                    }
                    thread_id = await chat_service._get_thread_id(inference_request.agentic_application_id, session_id)
                    await inference_service.hybrid_agent_inference._add_additional_data_to_final_response(response_time_details, thread_id=thread_id)
                    # Drain accumulator and persist per-query token usage for python-based agents
                    from litellm_standalone_tracker import get_and_clear_accumulator
                    token_records = get_and_clear_accumulator(session_id)
                    if token_records and last_message:
                        agent_name = token_records[0].get("agent_name") if token_records else None
                        last_message["token_usage"] = {
                            "prompt_tokens":     sum(r.get("prompt_tokens", 0)     for r in token_records),
                            "completion_tokens": sum(r.get("completion_tokens", 0) for r in token_records),
                            "total_tokens":      sum(r.get("total_tokens", 0)      for r in token_records),
                            "cached_tokens":     sum(r.get("cached_tokens", 0)     for r in token_records),
                            "total_cost":        sum(r.get("total_cost", 0.0)      for r in token_records),
                            "llm_calls":         token_records,
                        }
                        asyncio.create_task(query_token_usage_repo.insert(
                            session_id=session_id,
                            user_id=user_data.email,
                            agent_id=inference_request.agentic_application_id,
                            agent_name=agent_name,
                            query=inference_request.query,
                            token_records=token_records,
                        ))
                if last_message:
                    last_message["response_time"] = response_time
                yield json.dumps(jsonable_encoder(full_accumulated_response))
        return StreamingResponse(stream_generator(), media_type="application/json")

    # ---------------------------------------------------------
    # Scenario B: Non-Streaming Response (Regular Agent - Blocking)
    # ---------------------------------------------------------
    else:
        async def do_inference():
            try:
                # Assuming non-streaming returns a single result via anext or a list
                result = await anext(inference_service.run(inference_request, role=role, department_name=user_department, user_name=user_data.username))
                return result
            except asyncio.CancelledError:
                log.warning(f"[{session_id}] Task cancelled.")
                raise
            except StopAsyncIteration:
                # Handle case where generator is empty
                return {}

        # Create Task
        new_task = asyncio.create_task(do_inference())
        task_tracker[session_id] = new_task

        try:
            response = await new_task
            end_time = time.monotonic()
            time_taken = end_time - start_time

            # Inject Response Time into the last message payload only if not already set
            # (Historical messages should already have response_time from the base class)
            last_message = dict()
            if "executor_messages" in response and isinstance(response["executor_messages"], list) and response["executor_messages"]:
                last_message = response["executor_messages"][-1]
                last_message["start_timestamp"] = start_time_stamp.isoformat()

            # Run Post-Processing
            await save_feedback_and_logs(
                inference_request=inference_request,
                final_response=response,
                feedback_learning_service=feedback_learning_service,
                chat_service=chat_service,
                session_id=session_id,
                time_taken=time_taken,
                is_streaming=False,
                department_name=user_department
            )
            if chat_service and not await chat_service.is_python_based_agent(inference_request.agentic_application_id):
                response_time = await inference_service.update_response_time(agent_id=inference_request.agentic_application_id, session_id=session_id, start_time=start_time, time_stamp=start_time_stamp)
                # Inject per-query token totals into the same checkpoint
                from litellm_standalone_tracker import get_and_clear_accumulator
                token_records = get_and_clear_accumulator(session_id)
                if token_records:
                    agent_name = token_records[0].get("agent_name") if token_records else None
                    await inference_service.update_token_usage_in_graph(
                        agent_id=inference_request.agentic_application_id,
                        session_id=session_id,
                        token_records=token_records,
                    )
                    last_message["token_usage"] = {
                        "prompt_tokens":     sum(r.get("prompt_tokens", 0)     for r in token_records),
                        "completion_tokens": sum(r.get("completion_tokens", 0) for r in token_records),
                        "total_tokens":      sum(r.get("total_tokens", 0)      for r in token_records),
                        "cached_tokens":     sum(r.get("cached_tokens", 0)     for r in token_records),
                        "total_cost":        sum(r.get("total_cost", 0.0)      for r in token_records),
                        "llm_calls":         token_records,
                    }
                    asyncio.create_task(query_token_usage_repo.insert(
                        session_id=session_id,
                        user_id=user_data.email,
                        agent_id=inference_request.agentic_application_id,
                        agent_name=agent_name,
                        query=inference_request.query,
                        token_records=token_records,
                    ))
            else:
                response_time = time.monotonic() - start_time
                response_time_details = {
                    "response_time": response_time,
                    "start_timestamp": start_time_stamp.isoformat()
                }
                thread_id = await chat_service._get_thread_id(inference_request.agentic_application_id, session_id)
                await inference_service.hybrid_agent_inference._add_additional_data_to_final_response(response_time_details, thread_id=thread_id)
                # Drain accumulator and persist per-query token usage for python-based agents
                from litellm_standalone_tracker import get_and_clear_accumulator
                token_records = get_and_clear_accumulator(session_id)
                if token_records:
                    agent_name = token_records[0].get("agent_name") if token_records else None
                    last_message["token_usage"] = {
                        "prompt_tokens":     sum(r.get("prompt_tokens", 0)     for r in token_records),
                        "completion_tokens": sum(r.get("completion_tokens", 0) for r in token_records),
                        "total_tokens":      sum(r.get("total_tokens", 0)      for r in token_records),
                        "cached_tokens":     sum(r.get("cached_tokens", 0)     for r in token_records),
                        "total_cost":        sum(r.get("total_cost", 0.0)      for r in token_records),
                        "llm_calls":         token_records,
                    }
                    asyncio.create_task(query_token_usage_repo.insert(
                        session_id=session_id,
                        user_id=user_data.email,
                        agent_id=inference_request.agentic_application_id,
                        agent_name=agent_name,
                        query=inference_request.query,
                        token_records=token_records,
                    ))
                    
            last_message["response_time"] = response_time
            return response

        except asyncio.CancelledError:
            raise HTTPException(status_code=499, detail="Request was cancelled")
        except Exception as e:
            log.error(f"[{session_id}] Inference failed: {e}")
            raise HTTPException(status_code=500, detail=f"Internal Server Error: {str(e)}")
        finally:
            # Cleanup
            update_session_context(
                agent_id='Unassigned', session_id='Unassigned', 
                model_used='Unassigned', user_query='Unassigned', response='Unassigned'
            )
            if session_id in task_tracker and task_tracker[session_id].done():
                del task_tracker[session_id]


@router.post("/get/feedback-response/{feedback_type}")
async def send_feedback_endpoint(
    request: Request,
    feedback_type: Literal["like", "regenerate", "submit_feedback"],
    inference_request: AgentInferenceRequest,
    chat_service: ChatService = Depends(ServiceProvider.get_chat_service),
    inference_service: CentralizedAgentInference = Depends(ServiceProvider.get_centralized_agent_inference),
    feedback_learning_service: FeedbackLearningService = Depends(ServiceProvider.get_feedback_learning_service),
    model_service: ModelService = Depends(ServiceProvider.get_model_service),
    user_data: User = Depends(get_current_user) 
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
    
    role = user_data.role
    
    # Check department-specific execute permission for agents
    user_department = user_data.department_name
    
    async def process_feedback_in_background(
        llm: Union[BaseAIModelService, Any], feedback_prompt, feedback_learning_service: FeedbackLearningService,
        agent_id, original_query, old_response, old_steps,
        final_response, user_feedback, steps
    ):
        try:
            # Run the LLM invocation asynchronously
            lesson_response = await llm.ainvoke(feedback_prompt)
            if isinstance(llm, BaseAIModelService):
                lesson = lesson_response["final_response"]
            else:
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
                lesson=lesson,
                department_name = user_department
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
            session_id=inference_request.session_id,
            framework_type=inference_request.framework_type
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
    inference_request.enable_streaming_flag = False
    inference_request.context_flag = True
    if feedback_type == "regenerate":
        # Modify inference_request for regeneration
        inference_request.query = "[regenerate:][:regenerate]" # Special query for regeneration
    elif feedback_type == "submit_feedback":
        # Modify inference_request for feedback processing
        inference_request.query = f"[feedback:]{user_feedback}[:feedback]" # Special query for feedback
    else:
        raise HTTPException(status_code=400, detail="Invalid feedback type.")

    try:
        response = await anext(inference_service.run(inference_request, role=role, department_name=user_department, user_name=user_data.username))

        # Save feedback for learning
        try:

            final_response = response.get("response", "")
            executor_msgs = response.get("executor_messages", [])
            steps = executor_msgs[-1].get("agent_steps", "") if executor_msgs and isinstance(executor_msgs[-1], dict) else ""
            if inference_request.prev_response:
                old_response = inference_request.prev_response.get("response", "")
                old_executor_msgs = inference_request.prev_response.get("executor_messages", [])
                old_steps = old_executor_msgs[-1].get("agent_steps", "") if old_executor_msgs and isinstance(old_executor_msgs[-1], dict) else ""
            else:
                old_response = ""
                old_steps = ""
            
            if await chat_service.is_python_based_agent(inference_request.agentic_application_id):
                llm = await model_service.get_llm_model_using_python(inference_request.model_name, temperature=inference_request.temperature or 0.0)
            else:
                llm = await model_service.get_llm_model(inference_request.model_name, temperature=inference_request.temperature or 0.0)

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
            if feedback_type!="regenerate":
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
            log.error(f"Could not save data for future learnings: {str(e)}")

        update_session_context(agent_id='Unassigned', session_id='Unassigned', model_used='Unassigned', user_query='Unassigned', response='Unassigned')
        return response

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"An error occurred while processing the request: {str(e)}")



@router.post("/get/history")
async def get_chat_history_endpoint(
    request: Request, 
    chat_session_request: ChatSessionRequest, 
    chat_service: ChatService = Depends(ServiceProvider.get_chat_service),
    workflow_service: WorkflowService = Depends(ServiceProvider.get_workflow_service),
    user_data: User = Depends(get_current_user)):
    """
    API endpoint to retrieve the chat history of a previous session.
    Supports both regular agent chats and workflow conversations.

    Parameters:
    - request: The FastAPI Request object.
    - chat_session_request: Pydantic model containing agent_id and session_id.
    - chat_service: Dependency-injected ChatService instance.
    - workflow_service: Dependency-injected WorkflowService instance.

    Returns:
    - Dict[str, Any]: A dictionary containing the previous conversation history.
    """
    user_id = request.cookies.get("user_id")
    user_session = request.cookies.get("user_session")
    update_session_context(user_session=user_session, user_id=user_id, session_id=chat_session_request.session_id, agent_id=chat_session_request.agent_id)
    
    role = user_data.role
    user_department = user_data.department_name
    # Try to get workflow history first
    try:
        workflow_history = await workflow_service.get_workflow_conversation_history(
            workflow_id=chat_session_request.agent_id,
            session_id=chat_session_request.session_id,
            role=role
        )
        if workflow_history:
            update_session_context(user_session="Unassigned", user_id="Unassigned", session_id="Unassigned", agent_id="Unassigned")
            # Wrap in executor_messages format to match regular chat history structure
            return {"executor_messages": workflow_history}
    except Exception as e:
        log.warning(f"Error fetching workflow history, falling back to agent history: {e}")

    # Fall back to regular chat history
    history = await chat_service.get_chat_history_from_short_term_memory(
        agentic_application_id=chat_session_request.agent_id,
        session_id=chat_session_request.session_id,
        framework_type=chat_session_request.framework_type,
        role=role,
        department_name=user_department
    )
    update_session_context(user_session="Unassigned", user_id="Unassigned", session_id="Unassigned", agent_id="Unassigned")
    return history


@router.delete("/clear-history")
async def clear_chat_history_endpoint(
    request: Request, 
    chat_session_request: ChatSessionRequest, 
    chat_service: ChatService = Depends(ServiceProvider.get_chat_service),
    workflow_service: WorkflowService = Depends(ServiceProvider.get_workflow_service)
):
    """
    API endpoint to clear the chat history for a session.
    Supports both regular agent chats and workflow conversations.

    Parameters:
    - request: The FastAPI Request object.
    - chat_session_request: Pydantic model containing agent_id and session_id.
    - chat_service: Dependency-injected ChatService instance.
    - workflow_service: Dependency-injected WorkflowService instance.

    Returns:
    - Dict[str, Any]: A status dictionary indicating the result of the operation.
    """
    user_id = request.cookies.get("user_id")
    user_session = request.cookies.get("user_session")
    update_session_context(user_session=user_session, user_id=user_id)
    
    # Try to delete workflow history
    try:
        workflow_result = await workflow_service.delete_workflow_session(
            workflow_id=chat_session_request.agent_id,
            session_id=chat_session_request.session_id
        )
        if workflow_result.get("status") == "success":
            log.info(f"Workflow history cleared for session '{chat_session_request.session_id}'")
    except Exception as e:
        log.debug(f"No workflow history to clear: {e}")
    
    # Also delete regular chat history
    result = await chat_service.delete_session(
        agentic_application_id=chat_session_request.agent_id,
        session_id=chat_session_request.session_id,
        framework_type=chat_session_request.framework_type
    )
    if result.get("status") == "error":
        raise HTTPException(status_code=500, detail=result.get("message"))
    return result


@router.post("/get/old-conversations")
async def get_old_conversations_endpoint(
    request: Request, 
    chat_session_request: OldChatSessionsRequest, 
    chat_service: ChatService = Depends(ServiceProvider.get_chat_service),
    workflow_service: WorkflowService = Depends(ServiceProvider.get_workflow_service)
):
    """
    API endpoint to retrieve old chat sessions for a specific user and agent.
    Supports both regular agent chats and workflow conversations.

    Parameters:
    - request: The FastAPI Request object.
    - chat_session_request: Pydantic model containing user_email and agent_id.
    - chat_service: Dependency-injected ChatService instance.
    - workflow_service: Dependency-injected WorkflowService instance.

    Returns:
    - JSONResponse: A dictionary containing old chat sessions grouped by session ID.
    """
    user_id = request.cookies.get("user_id")
    user_session = request.cookies.get("user_session")
    update_session_context(user_session=user_session, user_id=user_id)

    # Try to get workflow old conversations first
    try:
        workflow_result = await workflow_service.get_old_workflow_conversations(
            user_email=chat_session_request.user_email,
            workflow_id=chat_session_request.agent_id
        )
        if workflow_result:
            return JSONResponse(content=jsonable_encoder(workflow_result))
    except Exception as e:
        log.debug(f"No workflow conversations found, checking agent conversations: {e}")

    # Fall back to regular chat history
    result = await chat_service.get_old_chats_by_user_and_agent(
        user_email=chat_session_request.user_email,
        agent_id=chat_session_request.agent_id,
        framework_type=chat_session_request.framework_type
    )

    if not result:
        raise HTTPException(status_code=404, detail="No old chats found for this user and agent.")
    
    return JSONResponse(content=jsonable_encoder(result))


@router.get("/get/new-session-id")
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


@router.get("/auto-suggest-agent-queries")
async def auto_suggest_agent_queries_endpoint(
    fastapi_request: Request, 
    agentic_application_id: str, 
    user_email: str, 
    chat_service: ChatService = Depends(ServiceProvider.get_chat_service)
):
    """
    Suggests agent queries based on the provided agentic application ID and user email.

    Args:
        fastapi_request (Request): The FastAPI request object.
        agentic_application_id (str): The ID of the agentic application.
        user_email (str): The email of the user.
    
    Returns:
        list: A list of suggested queries for the agent.
    
    Raises:
        HTTPException: If an error occurs during query suggestion.
    """
    user_id = fastapi_request.cookies.get("user_id")
    user_session = fastapi_request.cookies.get("user_session")
    update_session_context(user_session=user_session, user_id=user_id)
    
    try:
        suggestions = await chat_service.fetch_all_user_queries(
            agentic_application_id=agentic_application_id, 
            user_email=user_email
        )
        return suggestions
    except Exception as e:
        log.error(f"Error suggesting queries for agent {agentic_application_id}: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")



@router.post("/memory/store-example", response_model=StoreExampleResponse)
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

@router.get("/memory/get-examples/")
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

@router.delete("/memory/delete-examples/")
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

@router.put("/memory/update-examples/")
async def update_stored_example(agent_id: str, key: str, label: str = None):
    try:
        manager = await get_global_manager()
        if not manager:
            raise HTTPException(status_code=500, detail="Manager not found")
        records = await manager.get_records_by_category(agent_id)
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
 

@router.get("/connect_to_postgres")
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

@router.post("/files/upload")
async def upload_chat_files(
    request: Request,
    files: List[UploadFile] = File(..., description="Files to upload."),
    session_id: str = Form(..., description="Session ID for the conversation."),
    file_manager: FileManager = Depends(ServiceProvider.get_file_manager),
    user_data: User = Depends(get_current_user)
):
    """
    Upload files during chat
    """
    user_id = request.cookies.get("user_id") or user_data.email
    user_session = request.cookies.get("user_session")
    update_session_context(user_session=user_session, user_id=user_id)
    
    uploaded_files = []
    
    # Get user's department and create department-specific subdirectory
    user_department = current_user_department.get()
    if not user_department:
        raise HTTPException(status_code=400, detail="User department not found")
    
    department_subdirectory = user_department

    if STORAGE_PROVIDER == "":
        for file in files:
            file_path = await file_manager.save_chat_file(
                uploaded_file=file,
                session_id=session_id,
                subdirectory=department_subdirectory
            )
            log.info(f"File '{file.filename}' uploaded successfully to '{file_path}' for department '{user_department}'")
            uploaded_files.append(file_path)
        
        return {
            "success": True,
            "message": f"Uploaded {len(uploaded_files)} file(s) successfully.",
            "uploaded_files": uploaded_files
        }
    else:
        status = {}
        for uploaded_file in files:
            status[uploaded_file.filename] = await file_manager.upload_file_to_storage(
                file=uploaded_file,
                storage_provider=STORAGE_PROVIDER
            )
            uploaded_files.append(uploaded_file.filename)
        
        return status

@router.get("/files/list")
async def list_chat_files(
    request: Request,
    session_id: str = Query(None, description="Optional session ID to filter files."),
    file_manager: FileManager = Depends(ServiceProvider.get_file_manager),
    user_data: User = Depends(get_current_user)
):
    """
    List files uploaded in user_uploads.
    """
    user_id = request.cookies.get("user_id") or user_data.email
    user_session = request.cookies.get("user_session")
    update_session_context(user_session=user_session, user_id=user_id)
    
    try:
        # Get user's department and list files from department-specific subdirectory
        user_department = current_user_department.get()
        if not user_department:
            raise HTTPException(status_code=400, detail="User department not found")
        
        files = await file_manager.list_chat_files(session_id=session_id, subdirectory=user_department)
        return {"files": files, "total_count": len(files)}
    except Exception as e:
        log.error(f"Failed to list chat files: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to list files: {str(e)}")
