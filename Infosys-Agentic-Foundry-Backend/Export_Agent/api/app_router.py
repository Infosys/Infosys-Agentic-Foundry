# © 2024-25 Infosys Limited, Bangalore, India. All Rights Reserved.
import time
import json
from datetime import datetime, timezone
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

# Import the Redis-PostgreSQL manager
from src.auth.authorization_service import AuthorizationService
from src.database.redis_postgres_manager import RedisPostgresManager, TimedRedisPostgresManager, create_manager_from_env, create_timed_manager_from_env

from src.schemas import AgentInferenceRequest, ChatSessionRequest, OldChatSessionsRequest, StoreExampleRequest, StoreExampleResponse, SDLCAgentInferenceRequest

from src.database.services import ChatService, FeedbackLearningService, AgentService, PipelineService
from src.inference.inference_utils import EpisodicMemoryManager
from src.inference.centralized_agent_inference import CentralizedAgentInference
from src.inference.pipeline_inference import PipelineInference
from src.api.dependencies import ServiceProvider # The dependency provider
from src.auth.dependencies import get_current_user, get_user_info_from_request


from telemetry_wrapper import logger as log, update_session_context

from src.models.model_service import ModelService
from src.models.base_ai_model_service import BaseAIModelService

from src.auth.models import UserRole, User



task_tracker: dict[str, asyncio.Task] = {}

# Create an APIRouter instance for endpoints
router = APIRouter()

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
    is_streaming: bool = False
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


@router.post("/chat/inference")
async def run_agent_inference_endpoint(
    request: Request,
    inference_request: AgentInferenceRequest,
    inference_service: CentralizedAgentInference = Depends(ServiceProvider.get_centralized_agent_inference),
    pipeline_inference: PipelineInference = Depends(ServiceProvider.get_pipeline_inference),
    feedback_learning_service: FeedbackLearningService = Depends(ServiceProvider.get_feedback_learning_service),
    chat_service: ChatService = Depends(ServiceProvider.get_chat_service),
    authorization_service: AuthorizationService = Depends(ServiceProvider.get_authorization_service),
    user_data: User = Depends(get_current_user)
):
    """
    
    API endpoint to run agent inference.

    This is a unified endpoint that handles various agent types, HITL scenarios, and pipeline execution.
    When is_pipeline_call is True, it executes a pipeline instead of a single agent.

    Parameters:
    
    - request: The FastAPI Request object.
    - inference_request: Pydantic model containing all inference parameters.
    - inference_service: Dependency-injected CentralizedAgentInference instance.
    - pipeline_inference: Dependency-injected PipelineInference instance.
    - feedback_learning_service: Dependency-injected FeedbackLearningService instance.

    Returns:
    - Dict[str, Any]: A dictionary with the agent's response or pipeline execution result.
    """
    role = user_data.role
    
    start_time = time.monotonic()
    start_time_stamp = datetime.now(timezone.utc).replace(tzinfo=None)
    
    # 1. User & Session Setup
    role = user_data.role
    user_id = request.cookies.get("user_id") or user_data.email
    user_session = request.cookies.get("user_session")
    session_id = inference_request.session_id
    
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

    # 4. Role-Based Flag Modification
    if role == UserRole.USER:
        if inference_request.tool_verifier_flag:
            inference_request.tool_verifier_flag = False
        if inference_request.plan_verifier_flag:
            inference_request.plan_verifier_flag = False
        if inference_request.evaluation_flag:
            inference_request.evaluation_flag = False

    # ---------------------------------------------------------
    # Check if this is a Pipeline Resume Request
    # ---------------------------------------------------------
    # if inference_request.is_pipeline_resume:
    #     # Validate required fields for resume
    #     pipeline_id = inference_request.pipeline_id or inference_request.agentic_application_id
    #     if not pipeline_id:
    #         raise HTTPException(
    #             status_code=400,
    #             detail="pipeline_id is required when is_pipeline_resume is True"
    #         )
    #     if not inference_request.execution_id:
    #         raise HTTPException(
    #             status_code=400,
    #             detail="execution_id is required when is_pipeline_resume is True"
    #         )
    #     if not inference_request.paused_node_id:
    #         raise HTTPException(
    #             status_code=400,
    #             detail="paused_node_id is required when is_pipeline_resume is True"
    #         )
        
    #     # Check if abort action
    #     if inference_request.pipeline_action == "abort":
    #         log.info(f"[{session_id}] Pipeline execution aborted by user for execution_id: {inference_request.execution_id}")
    #         return {
    #             "status": "aborted",
    #             "message": "Pipeline execution was aborted by user",
    #             "execution_id": inference_request.execution_id
    #         }
        
    #     log.info(f"[{session_id}] Resuming pipeline execution for execution_id: {inference_request.execution_id}")
        
    #     # ---------------------------------------------------------
    #     # Pipeline Resume Streaming Response
    #     # ---------------------------------------------------------
    #     if inference_request.enable_streaming_flag:
    #         async def pipeline_resume_stream_generator():
    #             """Generate SSE events from resumed pipeline execution."""
    #             try:
    #                 task_tracker[session_id] = asyncio.current_task()
                    
    #                 async for event in pipeline_inference.resume_pipeline(
    #                     pipeline_id=pipeline_id,
    #                     session_id=session_id,
    #                     model_name=inference_request.model_name,
    #                     execution_id=inference_request.execution_id,
    #                     node_states=inference_request.node_states or {},
    #                     input_dict=inference_request.input_dict or {},
    #                     paused_node_id=inference_request.paused_node_id,
    #                     is_plan_approved=inference_request.is_plan_approved,
    #                     plan_feedback=inference_request.plan_feedback,
    #                     tool_feedback=inference_request.tool_feedback,
    #                     context_flag=inference_request.context_flag,
    #                     temperature=inference_request.temperature or 0.0,
    #                     role=str(role)
    #                 ):
    #                     yield json.dumps(jsonable_encoder(event)) + "\n"

    #             except HTTPException as e:
    #                 error_event = {
    #                     'event_type': 'error',
    #                     'message': e.detail
    #                 }
    #                 yield json.dumps(error_event) + "\n"

    #             except Exception as e:
    #                 log.error(f"[{session_id}] Pipeline resume error: {e}")
    #                 error_event = {
    #                     'event_type': 'error',
    #                     'message': str(e)
    #                 }
    #                 yield json.dumps(error_event) + "\n"
                    
    #             finally:
    #                 end_time = time.monotonic()
    #                 time_taken = end_time - start_time
                    
    #                 # Cleanup Task Tracker
    #                 if session_id in task_tracker:
    #                     del task_tracker[session_id]
                    
    #                 update_session_context(
    #                     agent_id='Unassigned', session_id='Unassigned', 
    #                     model_used='Unassigned', user_query='Unassigned', response='Unassigned'
    #                 )
    #                 log.info(f"[{session_id}] Pipeline resume streaming completed in {time_taken:.2f}s")

    #         return StreamingResponse(pipeline_resume_stream_generator(), media_type="application/json")

    #     # ---------------------------------------------------------
    #     # Pipeline Resume Non-Streaming Response (Synchronous)
    #     # ---------------------------------------------------------
    #     else:
    #         async def do_pipeline_resume():
    #             try:
    #                 events = []
    #                 final_event = None

    #                 async for event in pipeline_inference.resume_pipeline(
    #                     pipeline_id=pipeline_id,
    #                     session_id=session_id,
    #                     model_name=inference_request.model_name,
    #                     execution_id=inference_request.execution_id,
    #                     node_states=inference_request.node_states or {},
    #                     input_dict=inference_request.input_dict or {},
    #                     paused_node_id=inference_request.paused_node_id,
    #                     is_plan_approved=inference_request.is_plan_approved,
    #                     plan_feedback=inference_request.plan_feedback,
    #                     tool_feedback=inference_request.tool_feedback,
    #                     context_flag=inference_request.context_flag,
    #                     temperature=inference_request.temperature or 0.0,
    #                     role=str(role)
    #                 ):
    #                     events.append(event)
    #                     final_event = event

    #                 return {
    #                     "status": "success",
    #                     "events": events,
    #                     "final_event": final_event
    #                 }
    #             except asyncio.CancelledError:
    #                 log.warning(f"[{session_id}] Pipeline resume task cancelled.")
    #                 raise
    #             except StopAsyncIteration:
    #                 return {"status": "success", "events": [], "final_event": None}

    #         # Create Task
    #         new_task = asyncio.create_task(do_pipeline_resume())
    #         task_tracker[session_id] = new_task

    #         try:
    #             response = await new_task
    #             end_time = time.monotonic()
    #             time_taken = end_time - start_time
                
    #             log.info(f"[{session_id}] Pipeline resume completed in {time_taken:.2f}s")
    #             return response

    #         except asyncio.CancelledError:
    #             raise HTTPException(status_code=499, detail="Request was cancelled")
    #         except Exception as e:
    #             log.error(f"[{session_id}] Pipeline resume failed: {e}")
    #             raise HTTPException(status_code=500, detail=f"Pipeline resume failed: {str(e)}")
    #         finally:
    #             # Cleanup
    #             update_session_context(
    #                 agent_id='Unassigned', session_id='Unassigned', 
    #                 model_used='Unassigned', user_query='Unassigned', response='Unassigned'
    #             )
    #             if session_id in task_tracker and task_tracker[session_id].done():
    #                 del task_tracker[session_id]

    # ---------------------------------------------------------
    # Check if this is a Pipeline Call
    # ---------------------------------------------------------
    if inference_request.agentic_application_id.startswith("ppl_"):
        # Validate pipeline_id is provided
        pipeline_id = inference_request.agentic_application_id
        if not pipeline_id:
            raise HTTPException(
                status_code=400,
                detail="pipeline_id is required when is_pipeline_call is True"
            )
        
        log.info(f"[{session_id}] Routing to pipeline execution for pipeline_id: {pipeline_id}")
        
        # ---------------------------------------------------------
        # Pipeline Streaming Response
        # ---------------------------------------------------------
        if inference_request.enable_streaming_flag:
            async def pipeline_stream_generator():
                """Generate SSE events from pipeline execution."""
                try:
                    task_tracker[session_id] = asyncio.current_task()
                    
                    async for event in pipeline_inference.run_pipeline(
                        pipeline_id=pipeline_id,
                        session_id=session_id,
                        model_name=inference_request.model_name,
                        input_query=inference_request.query,
                        project_name=f"pipeline_{pipeline_id}",
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
                        role=str(role)
                    ):
                        yield json.dumps(jsonable_encoder(event)) + "\n"

                except HTTPException as e:
                    error_event = {
                        'event_type': 'error',
                        'message': e.detail
                    }
                    yield json.dumps(error_event) + "\n"

                except Exception as e:
                    log.error(f"[{session_id}] Pipeline execution error: {e}")
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
                    log.info(f"[{session_id}] Pipeline streaming completed in {time_taken:.2f}s")

            return StreamingResponse(pipeline_stream_generator(), media_type="application/json")

        # ---------------------------------------------------------
        # Pipeline Non-Streaming Response (Synchronous)
        # ---------------------------------------------------------
        else:
            async def do_pipeline_inference():
                try:
                    events = []
                    final_event = None

                    async for event in pipeline_inference.run_pipeline(
                        pipeline_id=pipeline_id,
                        session_id=session_id,
                        model_name=inference_request.model_name,
                        input_query=inference_request.query,
                        project_name=f"pipeline_{pipeline_id}",
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
                        role=str(role)
                    ):
                        response = event

                    return response
                except asyncio.CancelledError:
                    log.warning(f"[{session_id}] Pipeline task cancelled.")
                    raise
                except StopAsyncIteration:
                    return {"status": "success", "events": [], "final_event": None}

            # Create Task
            new_task = asyncio.create_task(do_pipeline_inference())
            task_tracker[session_id] = new_task

            try:
                response = await new_task
                end_time = time.monotonic()
                time_taken = end_time - start_time
                
                log.info(f"[{session_id}] Pipeline execution completed in {time_taken:.2f}s")
                return response

            except asyncio.CancelledError:
                raise HTTPException(status_code=499, detail="Request was cancelled")
            except Exception as e:
                log.error(f"[{session_id}] Pipeline execution failed: {e}")
                raise HTTPException(status_code=500, detail=f"Pipeline execution failed: {str(e)}")
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
                
                async for chunk in inference_service.run(inference_request, role=role):
                    # 1. Yield the intermediate chunk to the client                    
                    # 2. Accumulate chunk data if needed for post-processing (e.g., feedback saving)
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
                    is_streaming=True
                )
                if chat_service and not await chat_service.is_python_based_agent(inference_request.agentic_application_id):
                    response_time = await inference_service.update_response_time(agent_id=inference_request.agentic_application_id, session_id=session_id, start_time=start_time, time_stamp=start_time_stamp)
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
                result = await anext(inference_service.run(inference_request, role=role))
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
                last_message["start_timestamp"] = start_time_stamp.isoformat()

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
            if chat_service and not await chat_service.is_python_based_agent(inference_request.agentic_application_id):
                response_time = await inference_service.update_response_time(agent_id=inference_request.agentic_application_id, session_id=session_id, start_time=start_time, time_stamp=start_time_stamp)
            else:
                response_time = time.monotonic() - start_time
                response_time_details = {
                    "response_time": response_time,
                    "start_timestamp": start_time_stamp.isoformat()
                }
                thread_id = await chat_service._get_thread_id(inference_request.agentic_application_id, session_id)
                await inference_service.hybrid_agent_inference._add_additional_data_to_final_response(response_time_details, thread_id=thread_id)
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


@router.post("/chat/sdlc-agent/inference")
async def run_sdlc_agent_inference_endpoint(
                    request: Request,
                    chat_request: SDLCAgentInferenceRequest,
                    agent_service: AgentService = Depends(ServiceProvider.get_agent_service),
                    inference_service: CentralizedAgentInference = Depends(ServiceProvider.get_centralized_agent_inference),
                    feedback_learning_service: FeedbackLearningService = Depends(ServiceProvider.get_feedback_learning_service)
                ):
    """
    SDLC agent inference endpoint.
    """
    agent_record = await agent_service.agent_repo.get_agent_record(agentic_application_name="SDLC Web-Developer")
    if not agent_record:
        raise HTTPException(status_code=404, detail="SDLC Web-Developer agent not found.")

    agent_id = agent_record[0]["agentic_application_id"]
    chat_id = f"sdlc@sdlc.com_sdlc{chat_request.chat_id}"

    inference_request = AgentInferenceRequest(
        query=chat_request.query,
        agentic_application_id=agent_id,
        session_id=chat_id,
        model_name=chat_request.model_name,
        reset_conversation=chat_request.reset_conversation,
        temperature=chat_request.temperature
    )

    return await run_agent_inference_endpoint(
        request=request,
        inference_request=inference_request,
        inference_service=inference_service,
        feedback_learning_service=feedback_learning_service
    )


@router.post("/chat/get/history")
async def get_chat_history_endpoint(
    request: Request, 
    chat_session_request: ChatSessionRequest, 
    chat_service: ChatService = Depends(ServiceProvider.get_chat_service),
    pipeline_service: PipelineService = Depends(ServiceProvider.get_pipeline_service)
):
    """
    API endpoint to retrieve the chat history of a previous session.
    Supports both regular agent chats and pipeline conversations.

    Parameters:
    - request: The FastAPI Request object.
    - chat_session_request: Pydantic model containing agent_id and session_id.
    - chat_service: Dependency-injected ChatService instance.
    - pipeline_service: Dependency-injected PipelineService instance.

    Returns:
    - Dict[str, Any]: A dictionary containing the previous conversation history.
    """
    user_id = request.cookies.get("user_id")
    user_session = request.cookies.get("user_session")
    update_session_context(user_session=user_session, user_id=user_id, session_id=chat_session_request.session_id, agent_id=chat_session_request.agent_id)

    # Try to get pipeline history first
    try:
        pipeline_history = await pipeline_service.get_pipeline_conversation_history(
            pipeline_id=chat_session_request.agent_id,
            session_id=chat_session_request.session_id,
            role="developer"
        )
        if pipeline_history:
            update_session_context(user_session="Unassigned", user_id="Unassigned", session_id="Unassigned", agent_id="Unassigned")
            # Wrap in executor_messages format to match regular chat history structure
            return {"executor_messages": pipeline_history}
    except Exception as e:
        log.warning(f"Error fetching pipeline history, falling back to agent history: {e}")

    # Fall back to regular chat history
    history = await chat_service.get_chat_history_from_short_term_memory(
        agentic_application_id=chat_session_request.agent_id,
        session_id=chat_session_request.session_id,
        framework_type=chat_session_request.framework_type
    )
    update_session_context(user_session="Unassigned", user_id="Unassigned", session_id="Unassigned", agent_id="Unassigned")
    return history


@router.delete("/chat/clear-history")
async def clear_chat_history_endpoint(
    request: Request, 
    chat_session_request: ChatSessionRequest, 
    chat_service: ChatService = Depends(ServiceProvider.get_chat_service),
    pipeline_service: PipelineService = Depends(ServiceProvider.get_pipeline_service)
):
    """
    API endpoint to clear the chat history for a session.
    Supports both regular agent chats and pipeline conversations.

    Parameters:
    - request: The FastAPI Request object.
    - chat_session_request: Pydantic model containing agent_id and session_id.
    - chat_service: Dependency-injected ChatService instance.
    - pipeline_service: Dependency-injected PipelineService instance.

    Returns:
    - Dict[str, Any]: A status dictionary indicating the result of the operation.
    """
    user_id = request.cookies.get("user_id")
    user_session = request.cookies.get("user_session")
    update_session_context(user_session=user_session, user_id=user_id)
    
    # Try to delete pipeline history
    try:
        pipeline_result = await pipeline_service.delete_pipeline_session(
            pipeline_id=chat_session_request.agent_id,
            session_id=chat_session_request.session_id
        )
        if pipeline_result.get("status") == "success":
            log.info(f"Pipeline history cleared for session '{chat_session_request.session_id}'")
    except Exception as e:
        log.debug(f"No pipeline history to clear: {e}")
    
    # Also delete regular chat history
    result = await chat_service.delete_session(
        agentic_application_id=chat_session_request.agent_id,
        session_id=chat_session_request.session_id,
        framework_type=chat_session_request.framework_type
    )
    if result.get("status") == "error":
        raise HTTPException(status_code=500, detail=result.get("message"))
    return result


@router.post("/chat/get/old-conversations")
async def get_old_conversations_endpoint(
    request: Request, 
    chat_session_request: OldChatSessionsRequest, 
    chat_service: ChatService = Depends(ServiceProvider.get_chat_service),
    pipeline_service: PipelineService = Depends(ServiceProvider.get_pipeline_service)
):
    """
    API endpoint to retrieve old chat sessions for a specific user and agent.
    Supports both regular agent chats and pipeline conversations.

    Parameters:
    - request: The FastAPI Request object.
    - chat_session_request: Pydantic model containing user_email and agent_id.
    - chat_service: Dependency-injected ChatService instance.
    - pipeline_service: Dependency-injected PipelineService instance.

    Returns:
    - JSONResponse: A dictionary containing old chat sessions grouped by session ID.
    """
    user_id = request.cookies.get("user_id")
    user_session = request.cookies.get("user_session")
    update_session_context(user_session=user_session, user_id=user_id)

    # Try to get pipeline old conversations first
    try:
        pipeline_result = await pipeline_service.get_old_pipeline_conversations(
            user_email=chat_session_request.user_email,
            pipeline_id=chat_session_request.agent_id
        )
        if pipeline_result:
            return JSONResponse(content=jsonable_encoder(pipeline_result))
    except Exception as e:
        log.debug(f"No pipeline conversations found, checking agent conversations: {e}")

    # Fall back to regular chat history
    result = await chat_service.get_old_chats_by_user_and_agent(
        user_email=chat_session_request.user_email,
        agent_id=chat_session_request.agent_id,
        framework_type=chat_session_request.framework_type
    )

    if not result:
        raise HTTPException(status_code=404, detail="No old chats found for this user and agent.")
    
    return JSONResponse(content=jsonable_encoder(result))


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
 
#-------------------------------------------------------------------------------------------
from fastapi import APIRouter, Request, Depends, HTTPException
from fastapi.responses import StreamingResponse
from typing import Literal, AsyncGenerator
from src.schemas import AgentInferenceRequest
from src.database.services import ChatService, FeedbackLearningService
from src.inference.centralized_agent_inference import CentralizedAgentInference
from src.api.dependencies import ServiceProvider
from src.auth.dependencies import get_user_info_from_request
from fastapi.encoders import jsonable_encoder
from src.models.model_service import ModelService
import asyncio
import json
from telemetry_wrapper import logger as log


async def stream_inference_result(result):
    """
    Streams the result from the inference service, correctly serializing
    each chunk using FastAPI's jsonable_encoder.
    """
    try:
        async for chunk in result:
            # 1. Convert the chunk (e.g., AIMessageChunk object) into a
            #    JSON-serializable Python dictionary.
            yield json.dumps(jsonable_encoder(chunk)) + "\n"

    except Exception as e:
        # Handle potential errors during streaming
        log.error(f"Error during streaming: {e}")
        # You might want to yield a final error message
        error_message = json.dumps({"error": str(e)})
        yield f"{error_message}\n"

@router.post("/chat/v2/inference")
async def run_agent_inference_streaming(
    request: Request,
    inference_request: AgentInferenceRequest,
    inference_service: CentralizedAgentInference = Depends(ServiceProvider.get_centralized_agent_inference),
    feedback_learning_service: FeedbackLearningService = Depends(ServiceProvider.get_feedback_learning_service)
):
    """
    V2 API endpoint to run agent inference and stream the response.
    """
    user = await get_user_info_from_request(request)
    user_id = user.email if user else None
    session_id = user_id
    
    inference_request.enable_streaming_flag = True
    # ...existing context logic if needed...
    try:
        async def result():
            try:
                async for out in inference_service.run(inference_request):
                    log.info(f"Streaming out: {out}")
                    yield out
            except Exception as e:
                log.error(f"Error in inference stream: {e}")
                yield {"error": str(e)}
        return StreamingResponse(stream_inference_result(result()), media_type="application/json")
    except Exception as e:
        log.error(f"Streaming inference error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/chat/v2/feedback-response/{feedback_type}")
async def send_feedback_streaming(
    request: Request,
    feedback_type: Literal["like", "regenerate", "submit_feedback"],
    inference_request: AgentInferenceRequest,
    chat_service: ChatService = Depends(ServiceProvider.get_chat_service),
    inference_service: CentralizedAgentInference = Depends(ServiceProvider.get_centralized_agent_inference),
    feedback_learning_service: FeedbackLearningService = Depends(ServiceProvider.get_feedback_learning_service),
    model_service: ModelService = Depends(ServiceProvider.get_model_service)
):
    """
    V2 API endpoint to handle feedback and stream the response.
    """
    user = await get_user_info_from_request(request)
    user_id = user.email if user else None
    session_id = inference_request.session_id

    if feedback_type == "like":
        result = await chat_service.handle_like_feedback_message(
            agentic_application_id=inference_request.agentic_application_id,
            session_id=session_id
        )
        return StreamingResponse(stream_inference_result(result), media_type="application/json")

    if feedback_type == "regenerate":
        inference_request.query = "[regenerate:][:regenerate]"
    elif feedback_type == "submit_feedback":
        user_feedback = inference_request.final_response_feedback
        inference_request.query = f"[feedback:]{user_feedback}[:feedback]"
    else:
        raise HTTPException(status_code=400, detail="Invalid feedback type.")

    try:
        async def result():
            try:
                async for out in inference_service.run(inference_request):
                    log.info(f"Streaming out: {out}")
                    yield out
            except Exception as e:
                log.error(f"Error in inference stream: {e}")
                yield {"error": str(e)}
        return StreamingResponse(stream_inference_result(result()), media_type="application/json")
    except Exception as e:
        log.error(f"Streaming feedback error: {e}")
        raise HTTPException(status_code=500, detail=str(e))
#-------------------------------------------------------------------------------------------
import os
import ast
import uuid
import time
import json
import asyncio
import json
import tempfile
import pandas as pd
from pathlib import Path
from pydantic import BaseModel
from fastapi import APIRouter, Depends, HTTPException, Request, Query, UploadFile, File, Form , Form
from fastapi.responses import FileResponse, StreamingResponse
from typing import List, Dict, Optional, Callable,Awaitable, Union
from datetime import datetime
from pytz import timezone as pytz_timezone

from src.schemas import GroundTruthEvaluationRequest
from src.database.services import EvaluationService
from src.database.core_evaluation_service import CoreEvaluationService
from src.api.dependencies import ServiceProvider # Dependency provider
from src.schemas import GroundTruthEvaluationRequest, AgentInferenceRequest
from src.database.services import EvaluationService, ConsistencyService
from src.database.core_evaluation_service import CoreEvaluationService, CoreConsistencyEvaluationService, CoreRobustnessEvaluationService
from src.inference import CentralizedAgentInference

from groundtruth import evaluate_ground_truth_file
from phoenix.otel import register
from telemetry_wrapper import logger as log, update_session_context
from src.utils.phoenix_manager import ensure_project_registered, traced_project_context
from src.auth.dependencies import get_user_info_from_request
# Alias name for timezone to prevent 'utc' issue
ist = pytz_timezone("Asia/Kolkata")


# Base directory for uploads
BASE_DIR = "user_uploads"
TRUE_BASE_DIR = os.path.dirname(BASE_DIR)  # This will now point to the folder that contains both `user_uploads` and `evaluation_uploads`
EVALUATION_UPLOAD_DIR = os.path.join(TRUE_BASE_DIR, "evaluation_uploads")
os.makedirs(EVALUATION_UPLOAD_DIR, exist_ok=True) # Ensure directory exists on startup

RESPONSES_TEMP_DIR = Path("responses_temp")
OUTPUT_DIR = Path("outputs")

RESPONSES_TEMP_DIR.mkdir(exist_ok=True)
OUTPUT_DIR.mkdir(exist_ok=True)

PREVIEW_DIR = Path("temp_previews")
PREVIEW_DIR.mkdir(exist_ok=True)

# Helper functions

def get_temp_paths(agentic_application_id: str):
    """Returns paths for temporary xlsx and meta files."""
    base = RESPONSES_TEMP_DIR / f"{agentic_application_id}"
    xlsx_path = base.with_suffix(".xlsx")
    meta_path = base.with_suffix(".meta.json")
    return xlsx_path, meta_path

def get_robustness_preview_path(agentic_id: str) -> Path:
    """Returns the path for a temporary robustness preview file."""
    return PREVIEW_DIR / f"robustness_preview_{agentic_id}.json"

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

    # Generate a unique session ID for this evaluation run
    session_id = str(uuid.uuid4())

    try:
        avg_scores, summary, excel_path = await evaluate_ground_truth_file(
            model_name=evaluation_request.model_name,
            agent_type=evaluation_request.agent_type,
            file_path=file_path,
            agentic_application_id=evaluation_request.agentic_application_id,
            session_id=session_id,
            inference_service=inference_service,
            llm=llm,
            use_llm_grading=evaluation_request.use_llm_grading,
            progress_callback=progress_callback  # ✅ Pass callback here
        )
    except Exception as e:
        log.error(f"Error in evaluate_ground_truth_file: {str(e)}", exc_info=True)
        raise

    # Validate return values
    if avg_scores is None:
        log.warning("evaluate_ground_truth_file returned None for avg_scores")
    if summary is None:
        log.warning("evaluate_ground_truth_file returned None for summary")
        summary = "No summary available"
    if excel_path is None:
        log.error("evaluate_ground_truth_file returned None for excel_path")
        raise ValueError("Excel path is None - evaluation may have failed")

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
        async with traced_project_context('evaluation-metrics'):
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

                # Defensive check: ensure summary is not None
                if summary is None:
                    log.warning("Evaluation returned None for summary")
                    summary = "No summary available"
                
                if excel_path is None:
                    log.error("Evaluation returned None for excel_path")
                    raise ValueError("Excel file path is None - evaluation may have failed")

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
                log.error(f"Evaluation error: {str(e)}", exc_info=True)
                await queue.put(json.dumps({"error": f"Evaluation failed: {str(e)}"}) + "\n")

        asyncio.create_task(run_evaluation())

        while True:
            message = await queue.get()
            yield message
            if message.startswith("{\"result\":") or message.startswith("{\"error\":"):
                break

    return StreamingResponse(event_stream(), media_type="application/json")

#-----------------Consistency and Robustness-------------------------#




@router.get("/evaluation/download-consistency-template")
async def download_consistency_template_endpoint(fastapi_request: Request, file_name: str='Consistency_template.xlsx'):
    """
    API endpoint to download sample upload file for Consistency and robustness evaluation.

    Parameters:
    - fastapi_request: The FastAPI Request object.
    - file_name: The name of the template file to download (default is 'Consistency_template.xlsx').
    
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
    log.info(f"Downloading sample upload file for Consistency evaluation: {file_path}")
    return FileResponse(path=file_path, filename=file_name, media_type="application/octet-stream")




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
            try:
                with open(temp_meta_path, "r") as f:
                    metadata = json.load(f)
            except Exception as e:
                raise HTTPException(status_code=422, detail=f"Failed to read metadata file: {str(e)}")

            # Read Excel file
            try:
                df_from_temp = pd.read_excel(temp_xlsx_path)
                df_from_temp = df_from_temp.fillna("") 
            except Exception as e:
                raise HTTPException(status_code=422, detail=f"Failed to read Excel file: {str(e)}")

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
            res = await anext(inference_service.run(req, insert_into_eval_flag=False))
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

#-----------------------------------------------------------------------------------------
from fastapi import APIRouter, Depends, HTTPException, Request

from src.schemas import ApprovalRequest
from src.database.services import FeedbackLearningService
from src.api.dependencies import ServiceProvider # The dependency provider
from telemetry_wrapper import update_session_context


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
    response["status_message"] = response.get("message", "")

    if not response.get("is_update"):
        raise HTTPException(status_code=400, detail=response.get("message"))
    return response

#------------------------------------------------------------------------------------------
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
    Create or update a user secret_data.
    
    Args:
        request (SecretCreateRequest): The request containing user email, secret_data name, and value.
    
    Returns:
        dict: Success or error response.
    
    Raises:
        HTTPException: If secret_data creation fails.
    """
    #changed
    user_id = fastapi_request.cookies.get("user_id")
    user_session = fastapi_request.cookies.get("user_session")
    update_session_context(user_session=user_session, user_id=user_id)
    try:
        # Set the user context
        
        # Initialize secrets manager
        secrets_manager = setup_secrets_manager()
        
        # Store the secret_data
        success = secrets_manager.create_user_secret(
            user_email=request.user_email,
            key_name=request.key_name,
            key_value=request.key_value
        )
        
        if success:
            log.info(f"Secret '{request.key_name}' created/updated successfully for user: {request.user_email}")
            return {
                "success": True,
                "message": f"Secret '{request.key_name}' created/updated successfully",
                "user_email": request.user_email,
                "key_name": request.key_name
            }
        else:
            log.error(f"Failed to create/update secret '{request.key_name}' for user: {request.user_email}")
            raise HTTPException(
                status_code=500,
                detail=f"Failed to create/update secret '{request.key_name}'"
            )
    except ValueError as e:
        log.error(f"Error creating secret for user {request.user_email}: {str(e)}")
        raise HTTPException(
            status_code=400,
            detail=f"{str(e)}"
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
    Create or update a public secret_data.
    
    Args:
        request (PublicSecretCreateRequest): The request containing secret_data name and value.
    
    Returns:
        dict: Success or error response.
    
    Raises:
        HTTPException: If public secret_data creation fails.
    """
    #changed
    user_id = fastapi_request.cookies.get("user_id")
    user_session = fastapi_request.cookies.get("user_session")
    update_session_context(user_session=user_session, user_id=user_id)
    try:
        create_public_key(
            key_name=request.key_name,
            key_value=request.key_value
        )
        log.info(f"Public key '{request.key_name}' created/updated successfully")
        return {
            "success": True,
            "message": f"Public key '{request.key_name}' created/updated successfully"
        }
    except ValueError as e:
        log.error(f"Error creating secret for user {request.key_name}: {str(e)}")
        raise HTTPException(
            status_code=400,
            detail=f"{str(e)}"
        )
    except Exception as e:
        log.error(f"Error creating public key '{request.key_name}': {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"{str(e)}"
        )


@router.post("/secrets/get")
async def get_user_secret_endpoint(fastapi_request: Request, request: SecretGetRequest):
    """
    Retrieve user secrets by name or get all secrets.
    
    Args:
        request (SecretGetRequest): The request containing user email and optional secret_data names.
    
    Returns:
        dict: The requested secrets or all secrets for the user.
    
    Raises:
        HTTPException: If secret_data retrieval fails or secrets not found.
    """
    #changed
    user_id = fastapi_request.cookies.get("user_id")
    user_session = fastapi_request.cookies.get("user_session")
    update_session_context(user_session=user_session, user_id=user_id)
    try:
        # Set the user context
        
        # Initialize secrets manager
        secrets_manager = setup_secrets_manager()
        
        if request.key_name:
            # Get a specific secret_data
            key_value = secrets_manager.get_user_secret(
                user_email=request.user_email,
                key_name=request.key_name
            )
            
            if key_value is not None:
                log.info(f"Secret '{request.key_name}' retrieved successfully for user: {request.user_email}")
                return {
                    "success": True,
                    "user_email": request.user_email,
                    "key_name": request.key_name,
                    "key_value": key_value
                }
            else:
                log.warning(f"Secret '{request.key_name}' not found for user: {request.user_email}")
                raise HTTPException(
                    status_code=404,
                    detail=f"Secret '{request.key_name}' not found for user"
                )
                
        elif request.key_names:
            # Get multiple specific secrets
            secrets_dict = secrets_manager.get_user_secrets(
                user_email=request.user_email,
                key_names=request.key_names
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
    Retrieve a public secret_data by name.
    
    Args:
        request (PublicSecretGetRequest): The request containing the secret_data name.
    
    Returns:
        dict: The requested public secret_data value.
    
    Raises:
        HTTPException: If public secret_data retrieval fails or not found.
    """
    #changed
    user_id = fastapi_request.cookies.get("user_id")
    user_session = fastapi_request.cookies.get("user_session")
    update_session_context(user_session=user_session, user_id=user_id)
    try:
        # Get the public key
        public_key_value = get_public_key(request.key_name)
        
        if public_key_value is not None:
            log.info(f"Public key '{request.key_name}' retrieved successfully")
            return {
                "success": True,
                "key_name": request.key_name,
                "key_value": public_key_value
            }
        else:
            log.warning(f"Public key '{request.key_name}' not found")
            raise HTTPException(
                status_code=404,
                detail=f"Public key '{request.key_name}' not found"
            )
            
    except Exception as e:
        log.error(f"Error retrieving public key '{request.key_name}': {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"Internal server error: {str(e)}"
        )


@router.put("/secrets/update")
async def update_user_secret_endpoint(fastapi_request: Request, request: SecretUpdateRequest):
    """
    Update an existing user secret_data.
    
    Args:
        request (SecretUpdateRequest): The request containing user email, secret_data name, and new value.
    
    Returns:
        dict: Success or error response.
    
    Raises:
        HTTPException: If secret_data update fails or secret_data doesn't exist.
    """
    #changed
    user_id = fastapi_request.cookies.get("user_id")
    user_session = fastapi_request.cookies.get("user_session")
    update_session_context(user_session=user_session, user_id=user_id)
    try:
        # Set the user context
        
        # Initialize secrets manager
        secrets_manager = setup_secrets_manager()
        
        # Check if secret_data exists first
        existing_secret = secrets_manager.get_user_secret(
            user_email=request.user_email,
            key_name=request.key_name
        )
        
        if existing_secret is None:
            log.warning(f"Secret '{request.key_name}' not found for user: {request.user_email}")
            raise HTTPException(
                status_code=404,
                detail=f"Secret '{request.key_name}' not found for user"
            )
        
        # Update the secret_data
        success = secrets_manager.update_user_secret(
            user_email=request.user_email,
            key_name=request.key_name,
            key_value=request.key_value
        )
        
        if success:
            log.info(f"Secret '{request.key_name}' updated successfully for user: {request.user_email}")
            return {
                "success": True,
                "message": f"Secret '{request.key_name}' updated successfully",
                "user_email": request.user_email,
                "key_name": request.key_name
            }
        else:
            log.error(f"Failed to update secret '{request.key_name}' for user: {request.user_email}")
            raise HTTPException(
                status_code=500,
                detail=f"Failed to update secret '{request.key_name}'"
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
    Update an existing public secret_data.
    
    Args:
        request (PublicSecretUpdateRequest): The request containing secret_data name and new value.
    
    Returns:
        dict: Success or error response.
    
    Raises:
        HTTPException: If public secret_data update fails or secret_data doesn't exist.
    """
    #changed
    user_id = fastapi_request.cookies.get("user_id")
    user_session = fastapi_request.cookies.get("user_session")
    update_session_context(user_session=user_session, user_id=user_id)
    try:
        # Update the public key
        success = update_public_key(
            key_name=request.key_name,
            key_value=request.key_value
        )
        
        if success:
            log.info(f"Public key '{request.key_name}' updated successfully")
            return {
                "success": True,
                "message": f"Public key '{request.key_name}' updated successfully"
            }
        else:
            log.error(f"Failed to update public key '{request.key_name}'")
            raise HTTPException(
                status_code=500,
                detail=f"Failed to update public key '{request.key_name}'"
            )
            
    except Exception as e:
        log.error(f"Error updating public key '{request.key_name}': {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"Internal server error: {str(e)}"
        )


@router.delete("/secrets/delete")
async def delete_user_secret_endpoint(fastapi_request: Request, request: SecretDeleteRequest):
    """
    Delete a user secret_data.
    
    Args:
        request (SecretDeleteRequest): The request containing user email and secret_data name.
    
    Returns:
        dict: Success or error response.
    
    Raises:
        HTTPException: If secret_data deletion fails or secret_data doesn't exist.
    """
    #changed
    user_id = fastapi_request.cookies.get("user_id")
    user_session = fastapi_request.cookies.get("user_session")
    update_session_context(user_session=user_session, user_id=user_id)

    try:
        # Set the user context
        
        # Initialize secrets manager
        secrets_manager = setup_secrets_manager()
        
        # Delete the secret_data
        success = secrets_manager.delete_user_secret(
            user_email=request.user_email,
            key_name=request.key_name
        )
        
        if success:
            log.info(f"Secret '{request.key_name}' deleted successfully for user: {request.user_email}")
            return {
                "success": True,
                "message": f"Secret '{request.key_name}' deleted successfully",
                "user_email": request.user_email,
                "key_name": request.key_name
            }
        else:
            log.warning(f"Secret '{request.key_name}' not found for deletion for user: {request.user_email}")
            raise HTTPException(
                status_code=404,
                detail=f"Secret '{request.key_name}' not found for user"
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
    Delete a public secret_data.

    Args:
        request (PublicSecretDeleteRequest): The request containing secret_data name.

    Returns:
        dict: Success or error response.

    Raises:
        HTTPException: If public secret_data deletion fails or secret_data doesn't exist.
    """
    #changed
    user_id = fastapi_request.cookies.get("user_id")
    user_session = fastapi_request.cookies.get("user_session")
    update_session_context(user_session=user_session, user_id=user_id)
    try:
        # Delete the public key
        success = delete_public_key(
            key_name=request.key_name
        )

        if success:
            log.info(f"Public key '{request.key_name}' deleted successfully")
            return {
                "success": True,
                "message": f"Public key '{request.key_name}' deleted successfully"
            }
        else:
            log.error(f"Failed to delete public key '{request.key_name}'")
            raise HTTPException(
                status_code=500,
                detail=f"Failed to delete public key '{request.key_name}'"
            )

    except Exception as e:
        log.error(f"Error deleting public key '{request.key_name}': {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"Internal server error: {str(e)}"
        )


@router.post("/secrets/list")
async def list_user_secrets_endpoint(fastapi_request: Request, request: SecretListRequest):
    """
    List all secret_data names for a user (without values).
    
    Args:
        request (SecretListRequest): The request containing user email.
    
    Returns:
        dict: List of secret_data names or error response.
    
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
        
        # Get list of secret_data names
        key_names = secrets_manager.list_user_key_names(
            user_email=request.user_email
        )
        
        log.info(f"Secret names listed successfully for user: {request.user_email}")
        return {
            "success": True,
            "user_email": request.user_email,
            "key_names": key_names,
            "count": len(key_names)
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
    List all public secret_data names (without values).
    
    Returns:
        dict: List of public secret_data names or error response.
    
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

#-----------------------------------------------------------------------------------------
import uuid
import asyncio
from fastapi import APIRouter, Request, Response
from fastapi.responses import StreamingResponse
from telemetry_wrapper import logger as log

@router.get("/sse/stream/{session_id}")
async def stream(request: Request, session_id: str, response: Response):
    """The public API endpoint that clients connect to."""
    # We need a unique ID for each client to manage their connection.
    # A cookie is a standard way to persist this ID across requests from the same browser.
    
    if not session_id:
        session_id = str(uuid.uuid4())
        response.set_cookie(key="user_session", value=session_id, httponly=True)
    log.info(f"New SSE connection established with session ID: {session_id}")
    # Get the shared SSEManager instance from the application state.
    sse_manager = request.app.state.sse_manager
    
    # Register this new client connection with the manager.
    conn = sse_manager.register(session_id)

    async def event_generator():
        """
        This inner generator handles the lifecycle for a single request.
        It runs the core event_stream logic and ensures cleanup happens.
        """
        try:
            # Start yielding events from our main logic.
            async for event in conn.event_stream(request):
                yield event
        finally:
            # This is the crucial cleanup step for the manager.
            # It runs when the client disconnects or the server shuts down.
            sse_manager.unregister(session_id)

    return StreamingResponse(event_generator(), media_type="text/event-stream")
#-----------------------------------------------------------------------------------------
import os
import json
import shutil
import asyncpg
import requests
from typing import List, Dict
from pathlib import Path
from pydantic import BaseModel

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
from src.utils.tool_file_manager import ToolFileManager
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
async def get_available_models_endpoint(
    request: Request, 
    temperature: float = Query(default=0.0, ge=0.0, le=1.0, description="Temperature for model inference (0.0 to 1.0)"),
    model_service: ModelService = Depends(ServiceProvider.get_model_service)
):
    user_id = request.cookies.get("user_id")
    user_session = request.cookies.get("user_session")
    update_session_context(user_session=user_session, user_id=user_id)

    try:
        data = await model_service.get_all_available_model_names()
        log.debug(f"Models retrieved successfully: {data}, Temperature: {temperature}")
        return JSONResponse(content={"models": data, "temperature": temperature})

    except asyncpg.PostgresError as e:
        log.error(f"Database error while fetching models: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Database error: {str(e)}")

    except Exception as e:
        # Handle other unforeseen errors
        log.error(f"Unexpected error while fetching models: {str(e)}")
        raise HTTPException(status_code=500, detail=f"An error occurred: {str(e)}")


## ============ User Uploaded Files Endpoints ============

@router.post("/utility/files/user-uploads/upload/")
async def upload_file_endpoint(request: Request, files: List[UploadFile] = File(...), subdirectory: str = "", file_manager: FileManager = Depends(ServiceProvider.get_file_manager)):
    user_id = request.cookies.get("user_id")
    user_session = request.cookies.get("user_session")
    update_session_context(user_session=user_session, user_id=user_id)

    file_names = []
    for file in files:
        file_location = await file_manager.save_uploaded_file(uploaded_file=file, subdirectory=subdirectory)
        log.info(f"File '{file.filename}' uploaded successfully to '{file_location}'")
        file_names.append(file.filename)

    return {"info": f"Files {file_names} saved successfully."}

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

class DeleteFoldersRequest(BaseModel):
    knowledgebase_names: list[str]

@router.delete("/utility/remove-knowledgebases")
async def delete_folders(request: DeleteFoldersRequest):
    deleted_folders = []
    failed_folders = []

    for knowledgebase_name in request.knowledgebase_names:
        folder_path = Path(KB_DIR) / knowledgebase_name

        if not folder_path.exists():
            failed_folders.append({"KnowledgeBase": knowledgebase_name, "error": "KnowledgeBase not found"})
            continue

        if not folder_path.is_dir():
            failed_folders.append({"KnowledgeBase": knowledgebase_name, "error": "Not a KnowledgeBase"})
            continue

        try:
            shutil.rmtree(folder_path)
            deleted_folders.append(knowledgebase_name)
        except Exception as e:
            failed_folders.append({"folder": knowledgebase_name, "error": str(e)})

    return {
        "deleted_kbs": deleted_folders,
        "failed_kbs": failed_folders
    }
 
## ==========================================================


## ============ speech-to-text ============

@router.post("/utility/transcribe/")
async def transcribe_audio_endpoint(file: UploadFile = File(...)) -> Dict[str, str]:
    STT_ENDPOINT = os.getenv("STT_ENDPOINT")
    SPEECH_KEY = os.getenv("SPEECH_KEY")
    os.environ['HTTP_PROXY'] = ''
    os.environ['HTTPS_PROXY'] = 'http://blrproxy.ad.infosys.com:443'

    os.makedirs('audios', exist_ok=True)
    file_location = os.path.join("audios", file.filename)
    with open(file_location, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)

    url = f"{STT_ENDPOINT}speechtotext/transcriptions:transcribe?api-version=2024-05-15-preview"
    headers = {
        "Ocp-Apim-Subscription-Key": SPEECH_KEY,
        "Accept": "application/json"
    }
    definition = {
        "locales": ["en-US"],
        "profanityFilterMode": "Masked",
        "channels": [0]
    }

    proxies = {
        'http': 'http://blrproxy.ad.infosys.com:443',
        'https': 'http://blrproxy.ad.infosys.com:443'
    }

    try:
        with open(file_location, 'rb') as audio_file:
            files = {
                'audio': (file.filename, audio_file, 'audio/wav'),
                'definition': (None, json.dumps(definition), 'application/json')
            }

            response = requests.post(
                url,
                headers=headers,
                files=files,
                proxies=proxies,
                timeout=300
            )

        response.raise_for_status()
        result = response.json()

        if 'combinedPhrases' in result and len(result['combinedPhrases']) > 0:
            transcription = result['combinedPhrases'][0]['text']
        elif 'phrases' in result and len(result['phrases']) > 0:
            transcription = ' '.join([phrase['text'] for phrase in result['phrases']])
        else:
            transcription = "No speech could be recognized."

        os.remove(file_location)
        return {"transcription": transcription}

    except requests.exceptions.HTTPError as e:
        error_detail = e.response.text
        try:
            error_json = e.response.json()
            error_detail = json.dumps(error_json, indent=2)
        except:
            pass

        raise HTTPException(
            status_code=e.response.status_code,
            detail=f"HTTP Error: {e.response.status_code} - {error_detail}"
        )
    except requests.exceptions.RequestException as e:
        raise HTTPException(
            status_code=500,
            detail=f"Request Error: {str(e)}"
        )
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Internal Server Error: {str(e)}"
        )

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

## ==========================================================


@router.post("/utility/sync-tool-files")
async def sync_tool_files(
    request: Request,
    service_provider: ServiceProvider = Depends()
):
    """
    Sync existing database tools to .py files (one-time operation).
    Skips tools that already have files - only creates missing ones.
    """
    user_id = request.cookies.get("user_id")
    user_session = request.cookies.get("user_session")
    update_session_context(user_session=user_session, user_id=user_id)
    
    try:
        # Use the injected tool_file_manager from service provider
        tool_file_manager = service_provider.get_tool_file_manager()
        result = await tool_file_manager.sync_existing_tools_from_db()
        
        if result.get("success"):
            return {
                "success": True,
                "message": f"Sync complete: {result['created']} files created, {result['skipped']} skipped",
                "total_tools": result['total'],
                "files_created": result['created'],
                "files_skipped": result['skipped']
            }
        else:
            raise HTTPException(status_code=500, detail=result.get("error", "Unknown error"))
            
    except Exception as e:
        log.error(f"Error syncing tool files: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

## ==========================================================
@router.get("/agents/get/details-for-chat-interface")
async def get_agents_details_for_chat_interface_endpoint(
    request: Request, 
    agent_service: AgentService = Depends(ServiceProvider.get_agent_service),
    authorization_service: AuthorizationService = Depends(ServiceProvider.get_authorization_service),
    user_data: User = Depends(get_current_user)
):
    """Retrieves basic agent details for chat purposes, filtered by user access."""
    user_id = request.cookies.get("user_id")
    user_session = request.cookies.get("user_session")
    update_session_context(user_session=user_session, user_id=user_id)
    
    agent_details = await agent_service.get_agents_details_for_chat()
    if not agent_details:
        raise HTTPException(status_code=404, detail="No agents found for chat interface.")
    return agent_details
@router.get("/agents/tools-mapped/{agent_id}")
async def get_tools_or_agents_mapped_to_agent_endpoint(
    request: Request,
    agent_id: str,
    agent_service: AgentService = Depends(ServiceProvider.get_agent_service),
    authorization_server: AuthorizationService = Depends(ServiceProvider.get_authorization_service),
    user_data: User = Depends(get_current_user)
):
    """
    Retrieves tools mapped to a specific agent by its ID.

    Parameters:
    ----------
    request : Request
        The FastAPI Request object.
    agent_id : str
        The ID of the agent whose tools are to be retrieved.
    agent_service : AgentService
        Dependency-injected AgentService instance.

    Returns:
    -------
    dict
        A dictionary containing the list of tools mapped to the agent.
        If no tools are found, raises an HTTPException with status code 404.
    """
    # Check permissions first
    if not await authorization_server.check_operation_permission(user_data.email, user_data.role, "read", "agents"):
        raise HTTPException(status_code=403, detail="You don't have permission to view agents. Only admins and developers can perform this action")
    user_id = request.cookies.get("user_id")
    user_session = request.cookies.get("user_session")
    update_session_context(user_session=user_session, user_id=user_id, agent_id=agent_id)
    tools_mapped = await agent_service.get_tools_or_agents_mapped_to_agent(agentic_application_id=agent_id)
    if not tools_mapped:
        raise HTTPException(status_code=404, detail="No tools found for the specified agent.")
    return tools_mapped
#-------------------------------------------------------------------------------------------
import os
import uuid
import sqlite3 # For SQLite specific operations
import asyncpg 
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

from typing import Union



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

@router.post("/data-connector/connect")
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
    password = password or user_pwd

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
            flag_for_insert_into_db_connections_table=flag_for_insert_into_db_connections_table,
            created_by=created_by
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
                "connection_database_name": config.get("database", ""),
                "connection_created_by": config.get("created_by", "")
            }
            result = await db_connection_manager.insert_into_db_connections_table(connection_data)
            if result.get("is_created"):
                return {
                    "message": f"Connected to {db_type} database '{database}' and saved configuration.",
                    **result
                }
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


@router.post("/data-connector/disconnect")
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
 
    try:
        # If flag is "1", we need to delete from database
        if disconnect_request.flag == "1":
            # First check if connection exists in database and get creator info
            creator_email = None
            try:
                creator_info = await db_connection_manager.get_user_email(name)
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
                    delete_result = await db_connection_manager.delete_connection_by_name(name)
                    log.info(f"Deleted connection '{name}' from database")
                except Exception as delete_error:
                    log.warning(f"Failed to delete connection '{name}' from database: {str(delete_error)}")
 
        # ==================== CLOSE ACTIVE CONNECTIONS ====================
        # Close active connections (whether deleting from DB or just deactivating)
        if db_type == "mongodb":
            if name in active_mongo_connections:
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
            if name in active_sql_connections:
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

@router.post("/data-connector/generate-query")
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

import re

@router.post("/data-connector/run-query")
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


@router.get("/data-connector/connections")
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
    # if not await authorization_service.check_operation_permission(user_data.email, user_data.role, "read", "tools"):
    #     raise HTTPException(status_code=403, detail="You don't have permission to view connections. Only admins and developers can perform this action")
    
    user_id = request.cookies.get("user_id")
    user_session = request.cookies.get("user_session")
    update_session_context(user_session=user_session, user_id=user_id)
    return await db_connection_manager.get_connections()
    

@router.get("/data-connector/connections/sql")
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
    # if not await authorization_service.check_operation_permission(user_data.email, user_data.role, "read", "tools"):
    #     raise HTTPException(status_code=403, detail="You don't have permission to view SQL connections. Only admins and developers can perform this action")
    
    user_id = request.cookies.get("user_id")
    user_session = request.cookies.get("user_session")
    update_session_context(user_session=user_session, user_id=user_id)
    return await db_connection_manager.get_connections_sql()


@router.get("/data-connector/connections/mongodb")
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
    # if not await authorization_service.check_operation_permission(user_data.email, user_data.role, "read", "tools"):
    #     raise HTTPException(status_code=403, detail="You don't have permission to view MongoDB connections. Only admins and developers can perform this action")
    
    user_id = request.cookies.get("user_id")
    user_session = request.cookies.get("user_session")
    update_session_context(user_session=user_session, user_id=user_id)
    return await db_connection_manager.get_connections_mongodb()


@router.post("/data-connector/mongodb-operation/")
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


@router.get("/data-connector/get/active-connection-names")
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
    # if not await authorization_service.check_operation_permission(user_data.email, user_data.role, "read", "tools"):
    #     raise HTTPException(status_code=403, detail="You don't have permission to view active connections. Only admins and developers can perform this action")
    
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


@router.post("/data-connector/connect-by-name")
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
    
    user_id = request.cookies.get("user_id")
    user_session = request.cookies.get("user_session")
    update_session_context(user_session=user_session, user_id=user_id)
    
    manager = get_connection_manager()
    
    try:
        # Fetch connection configuration from database
        config = await db_connection_manager.get_connection_config(connection_name)
        
        if not config:
            raise HTTPException(
                status_code=404, 
                detail=f"Connection '{connection_name}' not found in saved connections"
            )
        
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