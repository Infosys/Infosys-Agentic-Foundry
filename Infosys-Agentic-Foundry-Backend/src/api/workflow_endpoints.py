# © 2024-25 Infosys Limited, Bangalore, India. All Rights Reserved.
"""
Workflow Endpoints Module

This module provides REST API endpoints for managing and executing agent workflows.
"""

import asyncio
from typing import Dict, Optional, List
from fastapi import APIRouter, Depends, HTTPException, Request, Query, BackgroundTasks
from fastapi.responses import StreamingResponse, JSONResponse
import json
from pydantic import BaseModel

from src.schemas.workflow_schemas import (
    WorkflowCreateRequest, WorkflowUpdateRequest, DeleteWorkflowRequest,
    WorkflowResponse, WorkflowListResponse,
)
from src.database.services import WorkflowService, AgentService
from src.inference.workflow_inference import WorkflowInference
from src.api.dependencies import ServiceProvider
from src.auth.authorization_service import AuthorizationService
from src.auth.models import User, UserRole
from src.auth.dependencies import get_current_user

from telemetry_wrapper import logger as log, update_session_context


# Create an APIRouter instance for workflow-related endpoints
router = APIRouter(prefix="/workflows", tags=["Workflows"])


# --- Workflow CRUD Endpoints ---

# EXPORT:EXCLUDE:START
@router.post("/create")
async def create_workflow_endpoint(
    request: Request,
    workflow_request: WorkflowCreateRequest,
    authorization_service: AuthorizationService = Depends(ServiceProvider.get_authorization_service),
    user_data: User = Depends(get_current_user)
):
    """
    Create a new agent workflow.

    Parameters:
    ----------
    request : Request
        The FastAPI Request object.
    workflow_request : WorkflowCreateRequest
        The request body containing workflow definition.

    Returns:
    -------
    dict
        A dictionary containing the status of the creation operation.
    """
    if user_data.role == UserRole.SUPER_ADMIN:
        raise HTTPException(status_code=403, detail="Superadmin is not allowed to create workflows.")
    
    # Check permissions using workflows permission
    user_department = user_data.department_name
    if not await authorization_service.check_operation_permission(user_data.email, user_data.role, "create", "workflows", user_department):
        raise HTTPException(
            status_code=403,
            detail="You don't have permission to create workflows."
        )

    user_session = request.cookies.get("user_session")
    update_session_context(user_session=user_session)

    workflow_service: WorkflowService = ServiceProvider.get_workflow_service()

    try:
        result = await workflow_service.create_workflow(
            workflow_name=workflow_request.workflow_name,
            workflow_description=workflow_request.workflow_description,
            workflow_definition=workflow_request.workflow_definition.model_dump(),
            created_by=workflow_request.created_by,
            department_name=user_data.department_name
        )

        if not result.get("is_created"):
            raise HTTPException(status_code=400, detail=result.get("message"))

        log.info(f"Workflow created: {result.get('workflow_id')}")
        return {"status": "success", "result": result}

    except HTTPException:
        raise
    except Exception as e:
        log.error(f"Error creating workflow: {e}")
        raise HTTPException(status_code=500, detail=f"Error creating workflow: {str(e)}")
# EXPORT:EXCLUDE:END


@router.get("/get")
async def get_all_workflows_endpoint(
    request: Request,
    created_by: Optional[str] = Query(None, description="Filter by creator email"),
    is_active: Optional[bool] = Query(None, description="Filter by active status"),
    authorization_service: AuthorizationService = Depends(ServiceProvider.get_authorization_service),
    user_data: User = Depends(get_current_user)
):
    """
    Retrieve all workflows with optional filtering.

    Parameters:
    ----------
    request : Request
        The FastAPI Request object.
    created_by : Optional[str]
        Filter workflows by creator email.
    is_active : Optional[bool]
        Filter workflows by active status.

    Returns:
    -------
    dict
        A dictionary containing the list of workflows.
    """
    # Check permissions using workflows permission
    user_department = user_data.department_name
    if not await authorization_service.check_operation_permission(user_data.email, user_data.role, "read", "workflows", user_department):
        raise HTTPException(
            status_code=403,
            detail="You don't have permission to view workflows."
        )

    workflow_service: WorkflowService = ServiceProvider.get_workflow_service()

    try:
        # If user is SUPER_ADMIN, do not restrict by department; otherwise include department_name
        if user_data.role == UserRole.SUPER_ADMIN:
            workflows = await workflow_service.get_all_workflows(
                created_by=created_by,
                is_active=is_active
            )
        else:
            workflows = await workflow_service.get_all_workflows(
                created_by=created_by,
                is_active=is_active,
                department_name=user_data.department_name
            )
        
        return {
            "status": "success",
            "workflows": workflows,
            "total_count": len(workflows)
        }

    except Exception as e:
        log.error(f"Error retrieving workflows: {e}")
        raise HTTPException(status_code=500, detail=f"Error retrieving workflows: {str(e)}")


@router.get("/get/search-paginated")
async def search_paginated_workflows_endpoint(
    request: Request,
    search_value: Optional[str] = Query(None, description="Search by workflow name"),
    page_number: int = Query(1, ge=1, description="Page number (1-indexed)"),
    page_size: int = Query(20, ge=1, description="Number of results per page"),
    created_by: Optional[str] = Query(None, description="Filter by creator email"),
    is_active: Optional[bool] = Query(None, description="Filter by active status"),
    authorization_service: AuthorizationService = Depends(ServiceProvider.get_authorization_service),
    user_data: User = Depends(get_current_user)
):
    """
    Search and retrieve workflows with pagination.

    Parameters:
    ----------
    request : Request
        The FastAPI Request object.
    search_value : Optional[str]
        Search string to filter workflows by name.
    page_number : int
        Page number for pagination (1-indexed).
    page_size : int
        Number of results per page.
    created_by : Optional[str]
        Filter workflows by creator email.
    is_active : Optional[bool]
        Filter workflows by active status.

    Returns:
    -------
    dict
        A dictionary containing total_count and paginated workflow details.
    """
    # Check permissions using workflows permission
    user_department = user_data.department_name
    # if not await authorization_service.check_operation_permission(user_data.email, user_data.role, "read", "workflows", user_department):
    #     raise HTTPException(
    #         status_code=403,
    #         detail="You don't have permission to view workflows."
    #     )

    user_session = request.cookies.get("user_session")
    update_session_context(user_session=user_session)

    workflow_service: WorkflowService = ServiceProvider.get_workflow_service()

    try:
        # If user is SUPER_ADMIN, do not restrict by department; otherwise include department_name
        if user_data.role == UserRole.SUPER_ADMIN:
            result = await workflow_service.get_workflows_by_search_or_page(
                search_value=search_value or '',
                limit=page_size,
                page=page_number,
                created_by=created_by,
                is_active=is_active
            )
        else:
            result = await workflow_service.get_workflows_by_search_or_page(
                search_value=search_value or '',
                limit=page_size,
                page=page_number,
                created_by=created_by,
                is_active=is_active,
                department_name=user_data.department_name
            )
        
        if not result["details"]:
            raise HTTPException(status_code=404, detail="No workflows found matching criteria.")
        
        # Filter to only requested fields
        filtered_details = []
        for workflow in result["details"]:
            workflow_def = workflow.get("workflow_definition", {})
            nodes = workflow_def.get("nodes", []) if isinstance(workflow_def, dict) else []
            
            filtered_details.append({
                "workflow_id": workflow.get("workflow_id"),
                "workflow_name": workflow.get("workflow_name"),
                "workflow_description": workflow.get("workflow_description"),
                "workflow_definition": {"nodes_count": len(nodes)},
                "created_by": workflow.get("created_by"),
                "department_name": workflow.get("department_name")
            })
        
        return {
            "total_count": result["total_count"],
            "details": filtered_details
        }

    except HTTPException:
        raise
    except Exception as e:
        log.error(f"Error searching workflows: {e}")
        raise HTTPException(status_code=500, detail=f"Error searching workflows: {str(e)}")


@router.get("/get-by-name")
async def get_workflow_by_name_endpoint(
    request: Request,
    workflow_name: str = Query(..., description="The name of the workflow to look up"),
    authorization_service: AuthorizationService = Depends(ServiceProvider.get_authorization_service),
    user_data: User = Depends(get_current_user)
):
    """
    Retrieve a workflow by its name.

    Parameters:
    ----------
    request : Request
        The FastAPI Request object.
    workflow_name : str
        The name of the workflow to look up.

    Returns:
    -------
    dict
        A dictionary containing the workflow_id and workflow details.
    """
    user_department = user_data.department_name if hasattr(user_data, 'department_name') else None
    if not await authorization_service.check_operation_permission(user_data.email, user_data.role, "read", "agents", user_department):
        raise HTTPException(
            status_code=403,
            detail="You don't have permission to view workflows."
        )

    workflow_service: WorkflowService = ServiceProvider.get_workflow_service()

    try:
        workflow = await workflow_service.get_workflow_by_name(workflow_name)

        if not workflow:
            raise HTTPException(status_code=404, detail=f"Workflow with name '{workflow_name}' not found.")

        return {
            "status": "success",
            "workflow_id": workflow.get("workflow_id"),
            "workflow": workflow
        }

    except HTTPException:
        raise
    except Exception as e:
        log.error(f"Error retrieving workflow by name '{workflow_name}': {e}")
        raise HTTPException(status_code=500, detail=f"Error retrieving workflow: {str(e)}")


@router.get("/get/system-workflows")
async def get_system_workflows_endpoint(
    request: Request,
    workflow_name: Optional[str] = Query(None, description="Filter by workflow name. If provided, returns only the matching workflow."),
    authorization_service: AuthorizationService = Depends(ServiceProvider.get_authorization_service),
    user_data: User = Depends(get_current_user)
):
    """
    Retrieves all system-onboarded workflows (created_by = 'system').
    Optionally filters by workflow name to return a specific workflow.

    Parameters:
    ----------
    workflow_name : str, optional
        The name of the workflow to filter by. If provided, returns only the matching workflow.

    Returns:
    -------
    dict
        A dictionary containing the list of system-onboarded workflows.
        If no system workflows are found, raises an HTTPException with status code 404.
    """
    # Check permissions using agents permission
    user_department = user_data.department_name
    if not await authorization_service.check_operation_permission(user_data.email, user_data.role, "read", "agents", user_department):
        raise HTTPException(status_code=403, detail="You don't have permission to view workflows.")

    user_session = request.cookies.get("user_session")
    update_session_context(user_session=user_session)

    workflow_service: WorkflowService = ServiceProvider.get_workflow_service()

    workflows = await workflow_service.get_system_workflows(workflow_name=workflow_name)

    if not workflows:
        detail = f"No system workflow found with name '{workflow_name}'" if workflow_name else "No system workflows found"
        raise HTTPException(status_code=404, detail=detail)
    return {
        "status": "success",
        "workflows": workflows,
        "total_count": len(workflows)
    }


@router.get("/get/{workflow_id}")
async def get_workflow_endpoint(
    request: Request,
    workflow_id: str,
    authorization_service: AuthorizationService = Depends(ServiceProvider.get_authorization_service),
    user_data: User = Depends(get_current_user)
):
    """
    Retrieve a single workflow by ID.

    Parameters:
    ----------
    request : Request
        The FastAPI Request object.
    workflow_id : str
        The ID of the workflow to retrieve.

    Returns:
    -------
    dict
        A dictionary containing the workflow details.
    """
    # Check permissions using workflows permission
    user_department = user_data.department_name
    if not await authorization_service.check_operation_permission(user_data.email, user_data.role, "read", "workflows", user_department):
        raise HTTPException(
            status_code=403,
            detail="You don't have permission to view workflows."
        )

    workflow_service: WorkflowService = ServiceProvider.get_workflow_service()

    try:
        # If user is SUPER_ADMIN, do not restrict by department; otherwise include department_name
        if user_data.role == UserRole.SUPER_ADMIN:
            workflow = await workflow_service.get_workflow(workflow_id)
        else:
            workflow = await workflow_service.get_workflow(workflow_id, department_name=user_data.department_name)
        
        if not workflow:
            raise HTTPException(status_code=404, detail=f"Workflow '{workflow_id}' not found.")
        
        return {"status": "success", "workflow": workflow}

    except HTTPException:
        raise
    except Exception as e:
        log.error(f"Error retrieving workflow {workflow_id}: {e}")
        raise HTTPException(status_code=500, detail=f"Error retrieving workflow: {str(e)}")

# EXPORT:EXCLUDE:START
@router.put("/update/{workflow_id}")
async def update_workflow_endpoint(
    request: Request,
    workflow_id: str,
    update_request: WorkflowUpdateRequest,
    authorization_service: AuthorizationService = Depends(ServiceProvider.get_authorization_service),
    user_data: User = Depends(get_current_user)
):
    """
    Update an existing workflow.
    
    Access Control:
    - Admins can update any workflow
    - Workflow creators can update their own workflows
    - Other users cannot update workflows

    Parameters:
    ----------
    request : Request
        The FastAPI Request object.
    workflow_id : str
        The ID of the workflow to update.
    update_request : WorkflowUpdateRequest
        The request body containing fields to update.

    Returns:
    -------
    dict
        A dictionary containing the status of the update operation.
    """
    if user_data.role == UserRole.SUPER_ADMIN:
        raise HTTPException(status_code=403, detail="Superadmin is not allowed to update workflows.")
    
    # Check basic operation permission first using workflows permission
    user_department = user_data.department_name
    if not await authorization_service.check_operation_permission(user_data.email, user_data.role, "update", "workflows", user_department):
        raise HTTPException(
            status_code=403,
            detail="You don't have permission to update workflows."
        )

    workflow_service: WorkflowService = ServiceProvider.get_workflow_service()

    # Get the existing workflow to check creator (with department filter for non-SUPER_ADMIN)
    if user_data.role == UserRole.SUPER_ADMIN:
        existing_workflow = await workflow_service.get_workflow(workflow_id)
    else:
        existing_workflow = await workflow_service.get_workflow(workflow_id, department_name=user_data.department_name)
    
    if not existing_workflow:
        raise HTTPException(status_code=404, detail=f"Workflow '{workflow_id}' not found.")
    
    # Check if user's department owns this workflow (public/shared workflows can only be updated by owning department)
    workflow_department = existing_workflow.get("department_name")
    if workflow_department and workflow_department != user_data.department_name:
        raise HTTPException(
            status_code=403,
            detail=f"You cannot update this workflow. It belongs to department '{workflow_department}'. Only users from the owning department can update it."
        )
    
    # Check if user is admin or creator
    is_admin = await authorization_service.has_role(user_email=user_data.email, required_role=UserRole.ADMIN, department_name=user_data.department_name)
    is_creator = (existing_workflow.get("created_by") == user_data.username or 
                  existing_workflow.get("created_by") == user_data.email)
    
    if not (is_admin or is_creator):
        log.warning(f"User {user_data.email} attempted to update workflow without admin privileges or creator access")
        raise HTTPException(
            status_code=403, 
            detail="Admin privileges or workflow creator access required to update this workflow"
        )

    try:
        workflow_definition = None
        if update_request.workflow_definition:
            workflow_definition = update_request.workflow_definition.model_dump()

        result = await workflow_service.update_workflow(
            workflow_id=workflow_id,
            workflow_name=update_request.workflow_name,
            workflow_description=update_request.workflow_description,
            workflow_definition=workflow_definition,
            is_active=update_request.is_active
        )

        if not result.get("is_updated"):
            raise HTTPException(status_code=400, detail=result.get("message"))

        log.info(f"Workflow updated: {workflow_id}")
        return {"status": "success", "result": result}

    except HTTPException:
        raise
    except Exception as e:
        log.error(f"Error updating workflow {workflow_id}: {e}")
        raise HTTPException(status_code=500, detail=f"Error updating workflow: {str(e)}")


@router.delete("/delete")
async def delete_workflow_endpoint(
    request: Request,
    delete_request: DeleteWorkflowRequest,
    authorization_service: AuthorizationService = Depends(ServiceProvider.get_authorization_service),
    user_data: User = Depends(get_current_user)
):
    """
    Deletes one or more workflows by their IDs.
    
    Access Control:
    - Admins can delete any workflow
    - Workflow creators can delete their own workflows
    - Other users cannot delete workflows

    Parameters:
    ----------
    request : Request
        The FastAPI Request object.
    delete_request : DeleteWorkflowRequest
        The request body containing the user email ID, admin status, and list of workflow IDs to delete.

    Returns:
    -------
    dict
        A dictionary containing the results of each deletion operation.
    """
    if user_data.role == UserRole.SUPER_ADMIN:
        raise HTTPException(status_code=403, detail="Superadmin is not allowed to delete workflows.")
    
    # Check basic operation permission first using workflows permission
    user_department = user_data.department_name
    if not await authorization_service.check_operation_permission(user_data.email, user_data.role, "delete", "workflows", user_department):
        raise HTTPException(
            status_code=403,
            detail="You don't have permission to delete workflows."
        )

    workflow_service: WorkflowService = ServiceProvider.get_workflow_service()

    is_admin = False
    if delete_request.is_admin:
        is_admin = await authorization_service.has_role(user_email=user_data.email, required_role=UserRole.ADMIN, department_name=user_department)

    # Only admins can delete multiple workflows at once; non-admins must delete one at a time
    if len(delete_request.workflow_ids) > 1 and not is_admin:
        raise HTTPException(status_code=403, detail="Only admins are allowed to delete multiple workflows at once. Please delete one workflow at a time.")

    results = []
    for workflow_id in delete_request.workflow_ids:
        # Get the existing workflow to check creator (with department filter for non-SUPER_ADMIN)
        if user_data.role == UserRole.SUPER_ADMIN:
            existing_workflow = await workflow_service.get_workflow(workflow_id)
        else:
            existing_workflow = await workflow_service.get_workflow(workflow_id, department_name=user_data.department_name)

        if not existing_workflow:
            results.append({"workflow_id": workflow_id, "is_deleted": False, "message": f"workflow '{workflow_id}' not found."})
            continue

        workflow_name = existing_workflow.get("workflow_name")

        # Check if user's department owns this workflow (public/shared workflows can only be deleted by owning department)
        workflow_department = existing_workflow.get("department_name")
        if workflow_department and workflow_department != user_data.department_name:
            raise HTTPException(
                status_code=403,
                detail=f"You cannot delete this workflow. It belongs to department '{workflow_department}'. Only users from the owning department can delete it."
            )
    
    # Check if user is admin or creator
        is_creator = (existing_workflow.get("created_by") == user_data.username or 
                      existing_workflow.get("created_by") == user_data.email)

        if not (is_admin or is_creator):
            log.warning(f"User {user_data.email} attempted to delete workflow {workflow_id} without admin privileges or creator access")
            results.append({"workflow_id": workflow_id, "workflow_name": workflow_name, "is_deleted": False, "message": "Admin privileges or workflow creator access required to delete this workflow"})
            continue

        try:
            result = await workflow_service.delete_workflow(workflow_id)

            if not result.get("is_deleted"):
                log.error(f"workflow delete failed for {workflow_id}: {result.get('message')}")
                result["workflow_id"] = workflow_id
                result["workflow_name"] = workflow_name
                results.append(result)
                continue

            log.info(f"workflow deleted: {workflow_id}")
            result["workflow_id"] = workflow_id
            result["workflow_name"] = workflow_name
            results.append(result)

        except Exception as e:
            log.error(f"Error deleting workflow {workflow_id}: {e}")
            results.append({"workflow_id": workflow_id, "workflow_name": workflow_name, "is_deleted": False, "message": f"Error deleting workflow: {str(e)}"})
            continue

    response: Dict[str, List[str]] = {}
    for res in results:
        workflow_name = res.get("workflow_name") or res.get("workflow_id", "unknown")
        reason = "Successfully deleted workflows" if res.get("is_deleted") else res.get("message", "Delete failed")
        response.setdefault(reason, []).append(workflow_name)

    status_message = " | ".join(
        f"{reason}: {', '.join(workflow_names)}"
        for reason, workflow_names in sorted(response.items(), key=lambda item: item[0] != "Successfully deleted workflows")
    )

    return {"results": results, "status_message": status_message}


# ============================================================================
# Workflow Sharing Endpoints (Admin Only)
# ============================================================================

class UpdateWorkflowSharingRequest(BaseModel):
    """Request model for updating workflow visibility and sharing settings."""
    is_public: bool = None
    shared_with_departments: List[str] = None


@router.put("/{workflow_id}/sharing")
async def update_workflow_sharing_endpoint(
    request: Request,
    workflow_id: str,
    body: UpdateWorkflowSharingRequest,
    current_user: User = Depends(get_current_user),
    authorization_service: AuthorizationService = Depends(ServiceProvider.get_authorization_service)
):
    """
    Update the visibility (is_public) and/or department sharing for a workflow.
    Only Admins of the workflow's department or SuperAdmins can update sharing settings.

    Parameters:
    - workflow_id: The workflow ID
    - is_public: Whether the workflow should be publicly accessible to all departments
    - shared_with_departments: List of department names to share the workflow with (replaces existing sharing)

    Returns:
    - Updated sharing information
    """
    user_id = request.cookies.get("user_id")
    user_session = request.cookies.get("user_session")
    update_session_context(user_session=user_session, user_id=user_id)

    if current_user.role not in [UserRole.SUPER_ADMIN, UserRole.ADMIN]:
        raise HTTPException(status_code=403, detail="Only Admins can update workflow sharing settings")

    if body.is_public is None and body.shared_with_departments is None:
        raise HTTPException(status_code=400, detail="At least one of 'is_public' or 'shared_with_departments' must be provided.")

    if body.is_public and body.shared_with_departments:
        raise HTTPException(
            status_code=400,
            detail="Cannot set both 'is_public' and 'shared_with_departments'. A public workflow is already accessible to all departments."
        )

    try:
        workflow_service: WorkflowService = ServiceProvider.get_workflow_service()
        result = await workflow_service.update_workflow_sharing(
            workflow_id=workflow_id,
            user_email=current_user.email,
            department_name=current_user.department_name,
            is_public=body.is_public,
            shared_with_departments=body.shared_with_departments
        )
        return {"message": "Workflow sharing settings updated successfully", **result}
    except HTTPException:
        raise
    except Exception as e:
        log.error(f"Error updating workflow sharing: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Error updating workflow sharing: {str(e)}")


@router.get("/{workflow_id}/sharing-info")
async def get_workflow_sharing_info(
    request: Request,
    workflow_id: str,
    current_user: User = Depends(get_current_user),
    authorization_service: AuthorizationService = Depends(ServiceProvider.get_authorization_service)
):
    """
    Get sharing information for a workflow.
    """
    workflow_service: WorkflowService = ServiceProvider.get_workflow_service()
    workflow = await workflow_service.get_workflow(workflow_id)
    if not workflow:
        raise HTTPException(status_code=404, detail=f"Workflow not found with ID: {workflow_id}")

    from src.api.app_container import app_container
    shared_departments = []
    if app_container.workflow_sharing_repo:
        shared_departments = await app_container.workflow_sharing_repo.get_shared_departments_for_workflow(workflow_id)

    return {
        "workflow_id": workflow_id,
        "workflow_name": workflow.get('workflow_name', ''),
        "owner_department": workflow.get('department_name', 'General'),
        "is_public": workflow.get('is_public', False),
        "shared_with": [d.get('target_department') for d in shared_departments if d.get('target_department')]
    }


@router.get("/shared-with-me")
async def get_workflows_shared_with_me(
    request: Request,
    current_user: User = Depends(get_current_user)
):
    """
    Get all workflows shared with the current user's department.
    """
    from src.api.app_container import app_container
    if not app_container.workflow_sharing_repo:
        return {"workflows": [], "count": 0}

    shared_details = await app_container.workflow_sharing_repo.get_workflows_shared_with_department_details(
        current_user.department_name
    )
    return {
        "workflows": shared_details,
        "count": len(shared_details),
        "department": current_user.department_name
    }


# --- Agent List Endpoint for Workflow Builder ---

@router.get("/available-agents")
async def get_available_agents_endpoint(
    request: Request,
    authorization_service: AuthorizationService = Depends(ServiceProvider.get_authorization_service),
    user_data: User = Depends(get_current_user)
):
    """
    Get list of available IAF agents that can be used in workflows.

    Parameters:
    ----------
    request : Request
        The FastAPI Request object.

    Returns:
    -------
    dict
        List of available agents with their IDs, names, and types.
    """
    # Check permissions using agents permission
    user_department = user_data.department_name
        
    if not await authorization_service.check_operation_permission(user_data.email, user_data.role, "read", "workflows", user_department):
        raise HTTPException(
            status_code=403,
            detail="You don't have permission to view workflows."
        )

    agent_service: AgentService = Depends(ServiceProvider.get_agent_service)

    try:
        # Get agent service from provider
        from src.api.app_container import app_container
        agent_service = app_container.agent_service
        
        # If user is SUPER_ADMIN, do not restrict by department; otherwise include department_name
        if user_data.role == UserRole.SUPER_ADMIN:
            agents = await agent_service.agent_repo.get_all_agent_records()
        else:
            agents = await agent_service.agent_repo.get_all_agent_records(department_name=user_data.department_name)
        
        # Return simplified list for workflow builder
        available_agents = [
            {
                "agent_id": agent["agentic_application_id"],
                "agent_name": agent["agentic_application_name"],
                "agent_type": agent.get("agentic_application_type", "unknown"),
                "description": agent.get("agentic_application_description", "")
            }
            for agent in agents
            if agent.get("is_active", True)
        ]
        
        return {
            "status": "success",
            "agents": available_agents,
            "count": len(available_agents)
        }

    except Exception as e:
        log.error(f"Error getting available agents: {e}")
        raise HTTPException(status_code=500, detail=f"Error getting available agents: {str(e)}")
