# © 2024-25 Infosys Limited, Bangalore, India. All Rights Reserved.
"""
Pipeline Endpoints Module

This module provides REST API endpoints for managing and executing agent pipelines.
"""

import asyncio
from typing import Optional, List
from fastapi import APIRouter, Depends, HTTPException, Request, Query, BackgroundTasks
from fastapi.responses import StreamingResponse, JSONResponse
import json

from src.schemas.pipeline_schemas import (
    PipelineCreateRequest, PipelineUpdateRequest,
    PipelineResponse, PipelineListResponse,
)
from src.database.services import PipelineService, AgentService
from src.inference.pipeline_inference import PipelineInference
from src.api.dependencies import ServiceProvider
from src.auth.authorization_service import AuthorizationService
from src.auth.models import User, UserRole
from src.auth.dependencies import get_current_user

from telemetry_wrapper import logger as log, update_session_context


# Create an APIRouter instance for pipeline-related endpoints
router = APIRouter(prefix="/pipelines", tags=["Pipelines"])


# --- Pipeline CRUD Endpoints ---

@router.post("/create")
async def create_pipeline_endpoint(
    request: Request,
    pipeline_request: PipelineCreateRequest,
    authorization_service: AuthorizationService = Depends(ServiceProvider.get_authorization_service),
    user_data: User = Depends(get_current_user)
):
    """
    Create a new agent pipeline.

    Parameters:
    ----------
    request : Request
        The FastAPI Request object.
    pipeline_request : PipelineCreateRequest
        The request body containing pipeline definition.

    Returns:
    -------
    dict
        A dictionary containing the status of the creation operation.
    """
    # Check permissions
    if not await authorization_service.check_operation_permission(user_data.email, user_data.role, "create", "pipelines"):
        raise HTTPException(
            status_code=403,
            detail="You don't have permission to create pipelines."
        )

    user_session = request.cookies.get("user_session")
    update_session_context(user_session=user_session)

    pipeline_service: PipelineService = ServiceProvider.get_pipeline_service()

    try:
        result = await pipeline_service.create_pipeline(
            pipeline_name=pipeline_request.pipeline_name,
            pipeline_description=pipeline_request.pipeline_description,
            pipeline_definition=pipeline_request.pipeline_definition.model_dump(),
            created_by=pipeline_request.created_by
        )

        if not result.get("is_created"):
            raise HTTPException(status_code=400, detail=result.get("message"))

        log.info(f"Pipeline created: {result.get('pipeline_id')}")
        return {"status": "success", "result": result}

    except HTTPException:
        raise
    except Exception as e:
        log.error(f"Error creating pipeline: {e}")
        raise HTTPException(status_code=500, detail=f"Error creating pipeline: {str(e)}")


@router.get("/get")
async def get_all_pipelines_endpoint(
    request: Request,
    created_by: Optional[str] = Query(None, description="Filter by creator email"),
    is_active: Optional[bool] = Query(None, description="Filter by active status"),
    authorization_service: AuthorizationService = Depends(ServiceProvider.get_authorization_service),
    user_data: User = Depends(get_current_user)
):
    """
    Retrieve all pipelines with optional filtering.

    Parameters:
    ----------
    request : Request
        The FastAPI Request object.
    created_by : Optional[str]
        Filter pipelines by creator email.
    is_active : Optional[bool]
        Filter pipelines by active status.

    Returns:
    -------
    dict
        A dictionary containing the list of pipelines.
    """
    # Check permissions
    if not await authorization_service.check_operation_permission(user_data.email, user_data.role, "read", "pipelines"):
        raise HTTPException(
            status_code=403,
            detail="You don't have permission to view pipelines."
        )

    pipeline_service: PipelineService = ServiceProvider.get_pipeline_service()

    try:
        pipelines = await pipeline_service.get_all_pipelines(
            created_by=created_by,
            is_active=is_active
        )
        
        return {
            "status": "success",
            "pipelines": pipelines,
            "total_count": len(pipelines)
        }

    except Exception as e:
        log.error(f"Error retrieving pipelines: {e}")
        raise HTTPException(status_code=500, detail=f"Error retrieving pipelines: {str(e)}")


@router.get("/get/search-paginated")
async def search_paginated_pipelines_endpoint(
    request: Request,
    search_value: Optional[str] = Query(None, description="Search by pipeline name"),
    page_number: int = Query(1, ge=1, description="Page number (1-indexed)"),
    page_size: int = Query(20, ge=1, description="Number of results per page"),
    created_by: Optional[str] = Query(None, description="Filter by creator email"),
    is_active: Optional[bool] = Query(None, description="Filter by active status"),
    authorization_service: AuthorizationService = Depends(ServiceProvider.get_authorization_service),
    user_data: User = Depends(get_current_user)
):
    """
    Search and retrieve pipelines with pagination.

    Parameters:
    ----------
    request : Request
        The FastAPI Request object.
    search_value : Optional[str]
        Search string to filter pipelines by name.
    page_number : int
        Page number for pagination (1-indexed).
    page_size : int
        Number of results per page.
    created_by : Optional[str]
        Filter pipelines by creator email.
    is_active : Optional[bool]
        Filter pipelines by active status.

    Returns:
    -------
    dict
        A dictionary containing total_count and paginated pipeline details.
    """
    # Check permissions
    if not await authorization_service.check_operation_permission(user_data.email, user_data.role, "read", "pipelines"):
        raise HTTPException(
            status_code=403,
            detail="You don't have permission to view pipelines."
        )

    user_session = request.cookies.get("user_session")
    update_session_context(user_session=user_session)

    pipeline_service: PipelineService = ServiceProvider.get_pipeline_service()

    try:
        result = await pipeline_service.get_pipelines_by_search_or_page(
            search_value=search_value or '',
            limit=page_size,
            page=page_number,
            created_by=created_by,
            is_active=is_active
        )
        
        if not result["details"]:
            raise HTTPException(status_code=404, detail="No pipelines found matching criteria.")
        
        return result

    except HTTPException:
        raise
    except Exception as e:
        log.error(f"Error searching pipelines: {e}")
        raise HTTPException(status_code=500, detail=f"Error searching pipelines: {str(e)}")


@router.get("/get/{pipeline_id}")
async def get_pipeline_endpoint(
    request: Request,
    pipeline_id: str,
    authorization_service: AuthorizationService = Depends(ServiceProvider.get_authorization_service),
    user_data: User = Depends(get_current_user)
):
    """
    Retrieve a single pipeline by ID.

    Parameters:
    ----------
    request : Request
        The FastAPI Request object.
    pipeline_id : str
        The ID of the pipeline to retrieve.

    Returns:
    -------
    dict
        A dictionary containing the pipeline details.
    """
    # Check permissions
    if not await authorization_service.check_operation_permission(user_data.email, user_data.role, "read", "pipelines"):
        raise HTTPException(
            status_code=403,
            detail="You don't have permission to view pipelines."
        )

    pipeline_service: PipelineService = ServiceProvider.get_pipeline_service()

    try:
        pipeline = await pipeline_service.get_pipeline(pipeline_id)
        
        if not pipeline:
            raise HTTPException(status_code=404, detail=f"Pipeline '{pipeline_id}' not found.")
        
        return {"status": "success", "pipeline": pipeline}

    except HTTPException:
        raise
    except Exception as e:
        log.error(f"Error retrieving pipeline {pipeline_id}: {e}")
        raise HTTPException(status_code=500, detail=f"Error retrieving pipeline: {str(e)}")


@router.put("/update/{pipeline_id}")
async def update_pipeline_endpoint(
    request: Request,
    pipeline_id: str,
    update_request: PipelineUpdateRequest,
    authorization_service: AuthorizationService = Depends(ServiceProvider.get_authorization_service),
    user_data: User = Depends(get_current_user)
):
    """
    Update an existing pipeline.
    
    Access Control:
    - Admins can update any pipeline
    - Pipeline creators can update their own pipelines
    - Other users cannot update pipelines

    Parameters:
    ----------
    request : Request
        The FastAPI Request object.
    pipeline_id : str
        The ID of the pipeline to update.
    update_request : PipelineUpdateRequest
        The request body containing fields to update.

    Returns:
    -------
    dict
        A dictionary containing the status of the update operation.
    """
    # Check basic operation permission first
    if not await authorization_service.check_operation_permission(user_data.email, user_data.role, "update", "pipelines"):
        raise HTTPException(
            status_code=403,
            detail="You don't have permission to update pipelines. Only admins and developers can perform this action"
        )

    pipeline_service: PipelineService = ServiceProvider.get_pipeline_service()

    # Get the existing pipeline to check creator
    existing_pipeline = await pipeline_service.get_pipeline(pipeline_id)
    if not existing_pipeline:
        raise HTTPException(status_code=404, detail=f"Pipeline '{pipeline_id}' not found.")
    
    # Check if user is admin or creator
    is_admin = await authorization_service.has_role(user_email=user_data.email, required_role=UserRole.ADMIN)
    is_creator = (existing_pipeline.get("created_by") == user_data.username or 
                  existing_pipeline.get("created_by") == user_data.email)
    
    if not (is_admin or is_creator):
        log.warning(f"User {user_data.email} attempted to update pipeline without admin privileges or creator access")
        raise HTTPException(
            status_code=403, 
            detail="Admin privileges or pipeline creator access required to update this pipeline"
        )

    try:
        pipeline_definition = None
        if update_request.pipeline_definition:
            pipeline_definition = update_request.pipeline_definition.model_dump()

        result = await pipeline_service.update_pipeline(
            pipeline_id=pipeline_id,
            pipeline_name=update_request.pipeline_name,
            pipeline_description=update_request.pipeline_description,
            pipeline_definition=pipeline_definition,
            is_active=update_request.is_active
        )

        if not result.get("is_updated"):
            raise HTTPException(status_code=400, detail=result.get("message"))

        log.info(f"Pipeline updated: {pipeline_id}")
        return {"status": "success", "result": result}

    except HTTPException:
        raise
    except Exception as e:
        log.error(f"Error updating pipeline {pipeline_id}: {e}")
        raise HTTPException(status_code=500, detail=f"Error updating pipeline: {str(e)}")


@router.delete("/delete/{pipeline_id}")
async def delete_pipeline_endpoint(
    request: Request,
    pipeline_id: str,
    authorization_service: AuthorizationService = Depends(ServiceProvider.get_authorization_service),
    user_data: User = Depends(get_current_user)
):
    """
    Delete a pipeline.
    
    Access Control:
    - Admins can delete any pipeline
    - Pipeline creators can delete their own pipelines
    - Other users cannot delete pipelines

    Parameters:
    ----------
    request : Request
        The FastAPI Request object.
    pipeline_id : str
        The ID of the pipeline to delete.

    Returns:
    -------
    dict
        A dictionary containing the status of the deletion operation.
    """
    # Check basic operation permission first
    if not await authorization_service.check_operation_permission(user_data.email, user_data.role, "delete", "pipelines"):
        raise HTTPException(
            status_code=403,
            detail="You don't have permission to delete pipelines. Only admins and developers can perform this action"
        )

    pipeline_service: PipelineService = ServiceProvider.get_pipeline_service()

    # Get the existing pipeline to check creator
    existing_pipeline = await pipeline_service.get_pipeline(pipeline_id)
    if not existing_pipeline:
        raise HTTPException(status_code=404, detail=f"Pipeline '{pipeline_id}' not found.")
    
    # Check if user is admin or creator
    is_admin = await authorization_service.has_role(user_email=user_data.email, required_role=UserRole.ADMIN)
    is_creator = (existing_pipeline.get("created_by") == user_data.username or 
                  existing_pipeline.get("created_by") == user_data.email)
    
    if not (is_admin or is_creator):
        log.warning(f"User {user_data.email} attempted to delete pipeline without admin privileges or creator access")
        raise HTTPException(
            status_code=403, 
            detail="Admin privileges or pipeline creator access required to delete this pipeline"
        )

    try:
        result = await pipeline_service.delete_pipeline(pipeline_id)

        if not result.get("is_deleted"):
            raise HTTPException(status_code=404, detail=result.get("message"))

        log.info(f"Pipeline deleted: {pipeline_id}")
        return {"status": "success", "result": result}

    except HTTPException:
        raise
    except Exception as e:
        log.error(f"Error deleting pipeline {pipeline_id}: {e}")
        raise HTTPException(status_code=500, detail=f"Error deleting pipeline: {str(e)}")

# --- Agent List Endpoint for Pipeline Builder ---

@router.get("/available-agents")
async def get_available_agents_endpoint(
    request: Request,
    authorization_service: AuthorizationService = Depends(ServiceProvider.get_authorization_service),
    user_data: User = Depends(get_current_user)
):
    """
    Get list of available IAF agents that can be used in pipelines.

    Parameters:
    ----------
    request : Request
        The FastAPI Request object.

    Returns:
    -------
    dict
        List of available agents with their IDs, names, and types.
    """
    # Check permissions
    if not await authorization_service.check_operation_permission(user_data.email, user_data.role, "read", "agents"):
        raise HTTPException(
            status_code=403,
            detail="You don't have permission to view agents."
        )

    agent_service: AgentService = Depends(ServiceProvider.get_agent_service)

    try:
        # Get agent service from provider
        from src.api.app_container import app_container
        agent_service = app_container.agent_service
        
        agents = await agent_service.agent_repo.get_all_agent_records()
        
        # Return simplified list for pipeline builder
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
