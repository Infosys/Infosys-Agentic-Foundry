# © 2024-25 Infosys Limited, Bangalore, India. All Rights Reserved.
from fastapi import APIRouter, Depends, HTTPException, Request

from src.schemas import ApprovalRequest
from src.database.services import FeedbackLearningService
from src.api.dependencies import ServiceProvider # The dependency provider
from telemetry_wrapper import update_session_context

from src.utils.secrets_handler import current_user_department
from src.auth.models import UserRole, User
from src.auth.dependencies import get_current_user


router = APIRouter(prefix="/feedback-learning", tags=["Feedback Learning"])


@router.get("/get/approvals-list")
async def get_approvals_list_endpoint(request: Request, feedback_learning_service: FeedbackLearningService = Depends(ServiceProvider.get_feedback_learning_service), user_data: User = Depends(get_current_user)):
    """
    API endpoint to retrieve the list of agents who have provided feedback.

    Parameters:
    - request: The FastAPI Request object.
    - feedback_learning_service: Dependency-injected FeedbackLearningService instance.

    Returns:
    - List[Dict[str, Any]]: A list of agents with feedback.
    """
    user_department = user_data.department_name
    user_id = request.cookies.get("user_id")
    user_session = request.cookies.get("user_session")
    update_session_context(user_session=user_session, user_id=user_id)

    approvals = await feedback_learning_service.get_agents_with_feedback(department_name=user_department)
    if not approvals:
        raise HTTPException(status_code=404, detail="No approvals found")
    return approvals


@router.get("/get/responses-data/{response_id}")
async def get_responses_data_endpoint(request: Request, response_id: str, feedback_learning_service: FeedbackLearningService = Depends(ServiceProvider.get_feedback_learning_service), user_data: User = Depends(get_current_user)):
    """
    API endpoint to retrieve detailed data for a specific feedback response.

    Parameters:
    - response_id: The ID of the feedback response.
    - request: The FastAPI Request object.
    - feedback_learning_service: Dependency-injected FeedbackLearningService instance.

    Returns:
    - Dict[str, Any]: The detailed feedback response data.
    """
    user_department = user_data.department_name
    
    user_id = request.cookies.get("user_id")
    user_session = request.cookies.get("user_session")
    update_session_context(user_session=user_session, user_id=user_id)

    approvals = await feedback_learning_service.get_feedback_details_by_response_id(response_id=response_id, department_name=user_department)
    if not approvals:
        raise HTTPException(status_code=404, detail="No Response found")
    return approvals


@router.get("/get/approvals-by-agent/{agent_id}")
async def get_approval_by_agent_id_endpoint(request: Request, agent_id: str, feedback_learning_service: FeedbackLearningService = Depends(ServiceProvider.get_feedback_learning_service), user_data: User = Depends(get_current_user)):
    """
    API endpoint to retrieve all feedback (approvals) for a specific agent.

    Parameters:
    - request: The FastAPI Request object.
    - agent_id: The ID of the agent.
    - feedback_learning_service: Dependency-injected FeedbackLearningService instance.

    Returns:
    - List[Dict[str, Any]]: A list of feedback entries for the agent.
    """
    user_department = user_data.department_name
    
    user_id = request.cookies.get("user_id")
    user_session = request.cookies.get("user_session")
    update_session_context(user_session=user_session, user_id=user_id)

    approval = await feedback_learning_service.get_all_approvals_for_agent(agent_id=agent_id, department_name=user_department)
    if not approval:
        raise HTTPException(status_code=404, detail="Approval not found")
    return approval


@router.put("/update/approval-response")
async def update_approval_response_endpoint(
    request: Request,
    approval_request: ApprovalRequest,
    feedback_learning_service: FeedbackLearningService = Depends(ServiceProvider.get_feedback_learning_service),
    user_data: User = Depends(get_current_user)
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
    user_department = user_data.department_name
    
    user_id = request.cookies.get("user_id")
    user_session = request.cookies.get("user_session")
    update_session_context(user_session=user_session, user_id=user_id)

    update_data= {}
    
    if approval_request.lesson:
        update_data["lesson"] = approval_request.lesson
        
    if approval_request.status is not None:
        update_data["status"] = approval_request.status

    response = await feedback_learning_service.update_feedback_status(
        response_id=approval_request.response_id,
        update_data=update_data,
        department_name=user_department
    )
    response["status_message"] = response.get("message", "")

    if not response.get("is_update"):
        raise HTTPException(status_code=400, detail=response.get("message"))
    return response


@router.get("/get/all-feedbacks")
async def get_all_feedback_endpoint(
    request: Request,
    feedback_learning_service: FeedbackLearningService = Depends(ServiceProvider.get_feedback_learning_service),
    user_data: User = Depends(get_current_user)
):
    """
    API endpoint to retrieve all feedback records for agents that exist in the main database.
    Returns only feedback for agents that are still available (filters out orphaned records).

    Parameters:
    - request: The FastAPI Request object.
    - feedback_learning_service: Dependency-injected FeedbackLearningService instance.

    Returns:
    - Dict with feedback_list: List of feedback records (with agent_name, agent_type), total_count: int
    """
    user_department = user_data.department_name

    try:
        result = await feedback_learning_service.get_all_feedback_records_with_count(department_name=user_department)
        if result is None:
            raise HTTPException(status_code=500, detail="Failed to retrieve feedback records")
        return result
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error retrieving feedback records: {str(e)}")


@router.get("/get/feedback-stats")
async def get_feedback_stats_endpoint(
    request: Request,
    feedback_learning_service: FeedbackLearningService = Depends(ServiceProvider.get_feedback_learning_service),
    user_data: User = Depends(get_current_user)
):
    """
    API endpoint to retrieve aggregated feedback statistics.

    Parameters:
    - request: The FastAPI Request object.
    - feedback_learning_service: Dependency-injected FeedbackLearningService instance.

    Returns:
    - Dict[str, Any]: Statistics including total_feedback, approved_feedback, pending_feedback, and agents_with_feedback.
    """
    user_department = user_data.department_name

    try:
        stats = await feedback_learning_service.get_feedback_stats(department_name=user_department)
        if stats is None:
            raise HTTPException(status_code=500, detail="Failed to retrieve feedback statistics")
        return stats
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error retrieving feedback statistics: {str(e)}")


@router.get("/get/total-feedback-count")
async def get_total_feedback_count_endpoint(
    request: Request,
    feedback_learning_service: FeedbackLearningService = Depends(ServiceProvider.get_feedback_learning_service),
    user_data: User = Depends(get_current_user)
):
    """
    API endpoint to retrieve the total count of feedback records.

    Parameters:
    - request: The FastAPI Request object.
    - feedback_learning_service: Dependency-injected FeedbackLearningService instance.

    Returns:
    - Dict[str, int]: The total feedback count.
    """
    user_department = user_data.department_name
    

    try:
        count = await feedback_learning_service.get_total_feedback_count(department_name=user_department)
        if count is None:
            raise HTTPException(status_code=500, detail="Failed to retrieve total feedback count")
        return {"total_feedback_count": count}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error retrieving total feedback count: {str(e)}")


@router.get("/get/approved-feedback-count")
async def get_approved_feedback_count_endpoint(
    request: Request,
    feedback_learning_service: FeedbackLearningService = Depends(ServiceProvider.get_feedback_learning_service),
    user_data: User = Depends(get_current_user)
):
    """
    API endpoint to retrieve the count of approved feedback records.

    Parameters:
    - request: The FastAPI Request object.
    - feedback_learning_service: Dependency-injected FeedbackLearningService instance.

    Returns:
    - Dict[str, int]: The approved feedback count.
    """
    user_department = user_data.department_name

    try:
        count = await feedback_learning_service.get_approved_feedback_count(department_name=user_department)
        if count is None:
            raise HTTPException(status_code=500, detail="Failed to retrieve approved feedback count")
        return {"approved_feedback_count": count}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error retrieving approved feedback count: {str(e)}")


@router.get("/get/pending-feedback-count")
async def get_pending_feedback_count_endpoint(
    request: Request,
    feedback_learning_service: FeedbackLearningService = Depends(ServiceProvider.get_feedback_learning_service),
    user_data: User = Depends(get_current_user)
):
    """
    API endpoint to retrieve the count of pending feedback records.

    Parameters:
    - request: The FastAPI Request object.
    - feedback_learning_service: Dependency-injected FeedbackLearningService instance.

    Returns:
    - Dict[str, int]: The pending feedback count.
    """
    user_department = user_data.department_name
    

    try:
        count = await feedback_learning_service.get_pending_feedback_count(department_name=user_department)
        if count is None:
            raise HTTPException(status_code=500, detail="Failed to retrieve pending feedback count")
        return {"pending_feedback_count": count}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error retrieving pending feedback count: {str(e)}")


@router.get("/get/rejected-feedback-count")
async def get_rejected_feedback_count_endpoint(
    request: Request,
    feedback_learning_service: FeedbackLearningService = Depends(ServiceProvider.get_feedback_learning_service),
    user_data: User = Depends(get_current_user)
):
    """
    API endpoint to retrieve the count of rejected feedback records.

    Parameters:
    - request: The FastAPI Request object.
    - feedback_learning_service: Dependency-injected FeedbackLearningService instance.

    Returns:
    - Dict[str, int]: The rejected feedback count.
    """
    user_department = user_data.department_name
    

    try:
        count = await feedback_learning_service.get_rejected_feedback_count(department_name=user_department)
        if count is None:
            raise HTTPException(status_code=500, detail="Failed to retrieve rejected feedback count")
        return {"rejected_feedback_count": count}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error retrieving rejected feedback count: {str(e)}")


@router.get("/get/agents-with-feedback-count")
async def get_agents_with_feedback_count_endpoint(
    request: Request,
    feedback_learning_service: FeedbackLearningService = Depends(ServiceProvider.get_feedback_learning_service),
    user_data: User = Depends(get_current_user)
):
    """
    API endpoint to retrieve the count of distinct agents that have associated feedback.

    Parameters:
    - request: The FastAPI Request object.
    - feedback_learning_service: Dependency-injected FeedbackLearningService instance.

    Returns:
    - Dict[str, int]: The count of agents with feedback.
    """
    user_department = user_data.department_name
    

    try:
        count = await feedback_learning_service.get_agents_with_feedback_count(department_name=user_department)
        if count is None:
            raise HTTPException(status_code=500, detail="Failed to retrieve agents with feedback count")
        return {"agents_with_feedback_count": count}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error retrieving agents with feedback count: {str(e)}")


