# © 2024-25 Infosys Limited, Bangalore, India. All Rights Reserved.
from fastapi import APIRouter, Depends, HTTPException, Request

from src.schemas import ApprovalRequest
from src.database.services import FeedbackLearningService
from src.api.dependencies import ServiceProvider # The dependency provider
from telemetry_wrapper import update_session_context


router = APIRouter(prefix="/feedback-learning", tags=["Feedback Learning"])


@router.get("/get/approvals-list")
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


@router.get("/get/responses-data/{response_id}")
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


@router.get("/get/approvals-by-agent/{agent_id}")
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


@router.put("/update/approval-response")
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


