# © 2024-25 Infosys Limited, Bangalore, India. All Rights Reserved.
import asyncio
from typing import Literal, Union, Any
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from fastapi.responses import StreamingResponse
from fastapi.encoders import jsonable_encoder
from src.utils.remote_model_client import RemoteSentenceTransformer as SentenceTransformer
from src.utils.remote_model_client import RemoteCrossEncoder as CrossEncoder
from src.utils.remote_model_client import RemoteSentenceTransformersUtil
util = RemoteSentenceTransformersUtil()
import time 
import json

# Import the Redis-PostgreSQL manager
from src.auth.authorization_service import AuthorizationService
from src.database.redis_postgres_manager import RedisPostgresManager, TimedRedisPostgresManager, create_manager_from_env, create_timed_manager_from_env

from src.schemas import AgentInferenceRequest, ChatSessionRequest, OldChatSessionsRequest, StoreExampleRequest, StoreExampleResponse, SDLCAgentInferenceRequest

from src.database.services import ChatService, FeedbackLearningService, AgentService
from src.inference.inference_utils import EpisodicMemoryManager
from src.inference.centralized_agent_inference import CentralizedAgentInference
from src.api.dependencies import ServiceProvider # The dependency provider
from src.auth.dependencies import get_current_user, get_user_info_from_request


from telemetry_wrapper import logger as log, update_session_context

from src.models.model_service import ModelService
from src.models.base_ai_model_service import BaseAIModelService

from src.auth.models import UserRole, User



task_tracker: dict[str, asyncio.Task] = {}

# Create an APIRouter instance for chat-related endpoints
router = APIRouter(prefix="/chat", tags=["Chat / Inference"])

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
    inference_request, 
    final_response, 
    feedback_learning_service, 
    chat_service, 
    session_id, 
    time_taken, 
    is_streaming=False
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
                    new_steps=""
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


@router.post("/inference")
async def run_agent_inference_endpoint(
    request: Request,
    inference_request: AgentInferenceRequest,
    inference_service: CentralizedAgentInference = Depends(ServiceProvider.get_centralized_agent_inference),
    feedback_learning_service: FeedbackLearningService = Depends(ServiceProvider.get_feedback_learning_service),
    chat_service: ChatService = Depends(ServiceProvider.get_chat_service),
    authorization_service: AuthorizationService = Depends(ServiceProvider.get_authorization_service),
    user_data: User = Depends(get_current_user)
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
    role = user_data.role
    
    start_time = time.monotonic()
    
    # 1. User & Session Setup
    role = user_data.role
    user_id = request.cookies.get("user_id") or user_data.email
    user_session = request.cookies.get("user_session")
    session_id = inference_request.session_id
    
    # Update context
    update_session_context(user_session=user_session, user_id=user_id)
    sse_manager = request.app.state.sse_manager

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

    # 4. Role-Based Flag Modification
    if role == UserRole.USER:
        if inference_request.tool_verifier_flag:
            inference_request.tool_verifier_flag = False
        if inference_request.plan_verifier_flag:
            inference_request.plan_verifier_flag = False
        if inference_request.evaluation_flag:
            inference_request.evaluation_flag = False

    # ---------------------------------------------------------
    # Scenario A: Streaming Response
    # ---------------------------------------------------------
    if inference_request.enable_streaming_flag:
        
        async def stream_generator():
            full_accumulated_response = {} # To store data needed for post-processing logic
            
            try:
                # Add task to tracker (Self-reference not easily possible in generator, 
                # so we rely on the tracker logic wrapping the endpoint or simple key existence)
                task_tracker[session_id] = asyncio.current_task()
                
                async for chunk in inference_service.run(inference_request, sse_manager=sse_manager, role=role):
                    # 1. Yield the intermediate chunk to the client
                    yield json.dumps(jsonable_encoder(chunk)) + "\n"
                    
                    # 2. Accumulate chunk data if needed for post-processing (e.g., feedback saving)
                    # This logic depends on your chunk structure. 
                    # If the last chunk contains the full result, verify that.
                    if isinstance(chunk, dict) and "query" in chunk:
                        full_accumulated_response.update(chunk) 

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
                if "executor_messages" in full_accumulated_response and isinstance(full_accumulated_response["executor_messages"], list) and full_accumulated_response["executor_messages"]:
                    last_message = full_accumulated_response["executor_messages"][-1]
                    # Only set response_time if it's not already set (preserve values from base class)
                    if last_message.get("response_time") is None:
                        last_message["response_time"] = time_taken
                    # Always copy timestamps from response to last_message if available
                    if "start_timestamp" in full_accumulated_response:
                        last_message["time_stamp"] = full_accumulated_response.get("start_timestamp")
                        last_message["start_timestamp"] = full_accumulated_response.get("start_timestamp")
                    if "end_timestamp" in full_accumulated_response:
                        last_message["end_timestamp"] = full_accumulated_response.get("end_timestamp")
                # Run background logic (Feedback, DB updates)
                # We await here to ensure it completes before the connection fully closes
                await save_feedback_and_logs(
                    inference_request=inference_request,
                    final_response=full_accumulated_response,
                    feedback_learning_service=feedback_learning_service,
                    chat_service=chat_service,
                    session_id=session_id,
                    time_taken=time_taken,
                    is_streaming=True
                )

        return StreamingResponse(stream_generator(), media_type="application/json")

    # ---------------------------------------------------------
    # Scenario B: Non-Streaming Response (Blocking)
    # ---------------------------------------------------------
    else:
        async def do_inference():
            try:
                # Assuming non-streaming returns a single result via anext or a list
                result = await anext(inference_service.run(inference_request, sse_manager=sse_manager, role=role))
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
            if "executor_messages" in response and isinstance(response["executor_messages"], list) and response["executor_messages"]:
                last_message = response["executor_messages"][-1]
                # Only set response_time if it's not already set (preserve values from base class)
                if last_message.get("response_time") is None:
                    last_message["response_time"] = time_taken
                # Always copy timestamps from response to last_message if available
                if "start_timestamp" in response:
                    last_message["time_stamp"] = response.get("start_timestamp")
                    last_message["start_timestamp"] = response.get("start_timestamp")
                if "end_timestamp" in response:
                    last_message["end_timestamp"] = response.get("end_timestamp")

            # Run Post-Processing
            await save_feedback_and_logs(
                inference_request=inference_request,
                final_response=response,
                feedback_learning_service=feedback_learning_service,
                chat_service=chat_service,
                session_id=session_id,
                time_taken=time_taken,
                is_streaming=False
            )
            
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
    inference_request.enable_streaming_flag = False
    if feedback_type == "regenerate":
        # Modify inference_request for regeneration
        inference_request.query = "[regenerate:][:regenerate]" # Special query for regeneration
    elif feedback_type == "submit_feedback":
        # Modify inference_request for feedback processing
        inference_request.query = f"[feedback:]{user_feedback}[:feedback]" # Special query for feedback
    else:
        raise HTTPException(status_code=400, detail="Invalid feedback type.")

    try:
        response = await anext(inference_service.run(inference_request))

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


@router.post("/get/history")
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
        framework_type=chat_session_request.framework_type
    )
    update_session_context(user_session="Unassigned", user_id="Unassigned", session_id="Unassigned", agent_id="Unassigned")
    return history


@router.delete("/clear-history")
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
        session_id=chat_session_request.session_id,
        framework_type=chat_session_request.framework_type
    )
    if result.get("status") == "error":
        raise HTTPException(status_code=500, detail=result.get("message"))
    return result


@router.post("/get/old-conversations")
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
 