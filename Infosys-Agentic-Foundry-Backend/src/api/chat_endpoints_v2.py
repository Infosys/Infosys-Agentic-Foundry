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

router = APIRouter(prefix="/chat/v2", tags=["Chat / Inference V2"])

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

@router.post("/inference")
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

@router.post("/feedback-response/{feedback_type}")
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
