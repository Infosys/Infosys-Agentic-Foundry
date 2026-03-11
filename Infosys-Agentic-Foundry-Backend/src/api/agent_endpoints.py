# © 2024-25 Infosys Limited, Bangalore, India. All Rights Reserved.
import os
import shutil
import traceback
import pytz
import io
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, Request, Query, BackgroundTasks, Form, UploadFile, File
from fastapi.responses import FileResponse
from typing import List, Optional, Union

from src.schemas import AgentOnboardingRequest, UpdateAgentRequest, DeleteAgentRequest, TagIdName
from src.database.services import AgentService, AgentServiceUtils, PipelineService, ToolService, McpToolService, FeedbackLearningService
from src.config.constants import AgentType, DatabaseName
from src.utils.secrets_handler import get_user_secrets
from src.api.dependencies import ServiceProvider # The dependency provider
# EXPORT:EXCLUDE:START
from Export_Agent.AgentsExport import AgentExporter
from Export_Agent.AgentImporter import AgentImporter

from github_pusher import push_project
# EXPORT:EXCLUDE:END

from telemetry_wrapper import logger as log, update_session_context
from src.utils.phoenix_manager import ensure_project_registered, traced_project_context_sync
from src.auth.authorization_service import AuthorizationService
from src.auth.models import UserRole, User
from src.auth.dependencies import get_current_user

# Create an APIRouter instance for agent-related endpoints
router = APIRouter(prefix="/agents", tags=["Agents"])


# EXPORT:EXCLUDE:START
@router.post("/onboard")
async def onboard_agent_endpoint(
    request: Request, 
    onboarding_request: AgentOnboardingRequest,
    authorization_service: AuthorizationService = Depends(ServiceProvider.get_authorization_service),
    user_data: User = Depends(get_current_user)
):
    """
    Onboards a new agent.

    Parameters:
    ----------
    request : Request
        The FastAPI Request object.
    onboarding_request : AgentOnboardingRequest
        The request body containing the agent's details.
    agent_service : AgentService
        Dependency-injected AgentService instance.

    Returns:
    -------
    dict
        A dictionary containing the status of the onboarding operation.
        If an error occurs, raises an HTTPException with status code 500 and the error message.
    """
    if user_data.role == UserRole.SUPER_ADMIN:
        raise HTTPException(status_code=403, detail="Superadmin is not allowed to onboard agents.")
    # Check permissions first
    user_department = user_data.department_name  
    if not await authorization_service.check_operation_permission(user_data.email, user_data.role, "create", "agents", user_department):
        raise HTTPException(status_code=403, detail="You don't have permission to create agents.")
    
    user_id = request.cookies.get("user_id")
    user_session = request.cookies.get("user_session")
    update_session_context(user_session=user_session, user_id=user_id)

    specialized_agent_service = ServiceProvider.get_specialized_agent_service(agent_type=onboarding_request.agent_type)
    update_session_context(model_used=onboarding_request.model_name,
                           agent_name=onboarding_request.agent_name,
                           agent_type=onboarding_request.agent_type,
                           tools_binded=onboarding_request.tools_id)
    project_name = f"onboard-{onboarding_request.agent_type.replace('_', '-')}"
    try:
        # Register Phoenix project (only once per unique project name)
        ensure_project_registered(
                project_name=project_name,
                auto_instrument=True,
                set_global_tracer_provider=False,
                batch=True
            )
        with traced_project_context_sync(project_name):
            update_session_context(
                model_used=onboarding_request.model_name,
                agent_name=onboarding_request.agent_name,
                agent_type=onboarding_request.agent_type,
                tools_binded=onboarding_request.tools_id
            )
            if onboarding_request.agent_type.is_meta_type:
                result = await specialized_agent_service.onboard_agent(
                    agent_name=onboarding_request.agent_name,
                    agent_goal=onboarding_request.agent_goal,
                    workflow_description=onboarding_request.workflow_description,
                    model_name=onboarding_request.model_name,
                    worker_agents_id=onboarding_request.tools_id,
                    user_id=onboarding_request.email_id,
                    department_name=user_data.department_name,
                    tag_ids=onboarding_request.tag_ids,
                    is_public=onboarding_request.is_public if onboarding_request.is_public else False,
                    shared_with_departments=onboarding_request.shared_with_departments
                )
            else:
                result = await specialized_agent_service.onboard_agent(
                    agent_name=onboarding_request.agent_name,
                    agent_goal=onboarding_request.agent_goal,
                    workflow_description=onboarding_request.workflow_description,
                    model_name=onboarding_request.model_name,
                    tools_id=onboarding_request.tools_id,
                    user_id=onboarding_request.email_id,
                    department_name=user_data.department_name,
                    tag_ids=onboarding_request.tag_ids,
                    validation_criteria=onboarding_request.validation_criteria,
                    knowledgebase_ids=onboarding_request.knowledgebase_ids,
                    is_public=onboarding_request.is_public if onboarding_request.is_public else False,
                    shared_with_departments=onboarding_request.shared_with_departments
                )
        update_session_context(model_used='Unassigned',
                            agent_name='Unassigned',
                            agent_id='Unassigned',
                            agent_type='Unassigned',
                            tools_binded='Unassigned',
                            tags='Unassigned')

    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Error during agent onboarding: {str(e)}"
        ) from e

    if not result.get("is_created"):
        raise HTTPException(status_code=400, detail=result.get("message"))
    return {"status": "success", "result": result}
# EXPORT:EXCLUDE:END


@router.get("/get")
async def get_all_agents_endpoint(
    request: Request, 
    agentic_application_type: Optional[Union[str, List[str]]] = Query(None), 
    agent_service: AgentService = Depends(ServiceProvider.get_agent_service),
    authorization_service: AuthorizationService = Depends(ServiceProvider.get_authorization_service),
    user_data: User = Depends(get_current_user)
):
    """
    Retrieves agents from the specified agent table.

    Parameters:
    ----------
    request : Request
        The FastAPI Request object.
    agentic_application_type : Optional[str], optional
        The type of agentic application to filter agents by.
    agent_service : AgentService
        Dependency-injected AgentService instance.

    Returns:
    -------
    list
        A list of agents. If no agents are found, raises an HTTPException with status code 404.
    """
    # Check permissions first
    user_department = user_data.department_name 
    if not await authorization_service.check_operation_permission(user_data.email, user_data.role, "read", "agents", user_department):
        raise HTTPException(status_code=403, detail="You don't have permission to view agents.")
    
    user_id = request.cookies.get("user_id")
    user_session = request.cookies.get("user_session")
    update_session_context(user_session=user_session, user_id=user_id)

    try:
        # If user is SUPER_ADMIN, do not restrict by department; otherwise include department_name
        if user_data.role == UserRole.SUPER_ADMIN:
            response = await agent_service.get_all_agents(agentic_application_type=agentic_application_type)
        else:
            response = await agent_service.get_all_agents(agentic_application_type=agentic_application_type, department_name=user_data.department_name)

        if not response:
            raise HTTPException(status_code=404, detail="No agents found")

        # Add knowledgebase IDs for each agent
        try:
            knowledgebase_service = ServiceProvider.get_knowledgebase_service()
            for agent in response:
                agent_id = agent.get("agentic_application_id")
                if agent_id:
                    kb_ids = await knowledgebase_service.agent_kb_mapping_repo.get_knowledgebase_ids_for_agent(
                        agentic_application_id=agent_id
                    )
                    agent["knowledgebase_ids"] = kb_ids if kb_ids else []
                else:
                    agent["knowledgebase_ids"] = []
        except Exception as e:
            log.warning(f"Error fetching KB IDs for agents: {e}")
            for agent in response:
                agent["knowledgebase_ids"] = []

        return response

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error retrieving agents: {str(e)}")


@router.get("/get/details-for-chat-interface")
async def get_agents_details_for_chat_interface_endpoint(
    request: Request, 
    agent_service: AgentService = Depends(ServiceProvider.get_agent_service),
    pipeline_service: PipelineService = Depends(ServiceProvider.get_pipeline_service),
    authorization_service: AuthorizationService = Depends(ServiceProvider.get_authorization_service),
    user_data: User = Depends(get_current_user)
):
    """Retrieves basic agent and pipeline details for chat purposes, filtered by user access."""
    user_id = request.cookies.get("user_id")
    user_session = request.cookies.get("user_session")
    
    update_session_context(user_session=user_session, user_id=user_id)
    
    # If SUPER_ADMIN, do not restrict by department
    if user_data.role == UserRole.SUPER_ADMIN:
        # Fetch agents
        agent_details = await agent_service.get_agents_details_for_chat()
        log.info("SUPER_ADMIN: returning all agents for chat interface")
    else:
        agent_details = await agent_service.get_agents_details_for_chat(department_name=user_data.department_name)
        log.info(f"Returning {len(agent_details) if agent_details else 0} agents for chat interface for department {user_data.department_name}")
    
    
    # Fetch pipelines and format them to match agent structure
    pipelines = await pipeline_service.get_all_pipelines(is_active=True, department_name=user_data.department_name)
    
    default_welcome_message = "Hello! I'm here to help you. What can I assist you with today?"
    
    pipeline_details = []
    for pipeline in pipelines:
        pipeline_details.append({
            "agentic_application_id": pipeline.get("pipeline_id"),
            "agentic_application_name": pipeline.get("pipeline_name"),
            "agentic_application_type": "pipeline",
            "welcome_message": pipeline.get("welcome_message", default_welcome_message)
        })
    
    # Combine agents and pipelines
    combined_details = (agent_details or []) + pipeline_details
    
    if not combined_details:
        raise HTTPException(status_code=404, detail="No agents or pipelines found for chat interface.")
    return combined_details


@router.get("/get/{agent_id}")
async def get_agent_by_id_endpoint(
    request: Request, 
    agent_id: str,
    include_file_context_prompt: bool = True,
    agent_service: AgentService = Depends(ServiceProvider.get_agent_service),
    authorization_service: AuthorizationService = Depends(ServiceProvider.get_authorization_service),
    user_data: User = Depends(get_current_user)
):
    """
    Retrieves an agent by its ID.

    Parameters:
    ----------
    request : Request
        The FastAPI Request object.
    agent_id : str
        The ID of the agent to be retrieved.
    include_file_context_prompt : bool
        If True, includes the file-context management prompt in the response (if it exists).
    agent_service : AgentService
        Dependency-injected AgentService instance.

    Returns:
    -------
    dict
        A dictionary containing the agent's details
        If no agent is found, raises an HTTPException with status code 404.
        If include_file_context_prompt=True and prompt exists, includes 'file_context_management_prompt' field.
    """
    # Check permissions first
    user_department = user_data.department_name 
    if not await authorization_service.check_operation_permission(user_data.email, user_data.role, "read", "agents", user_department):
        raise HTTPException(status_code=403, detail="You don't have permission to view agents.")
    
    user_id = request.cookies.get("user_id")
    user_session = request.cookies.get("user_session")
    update_session_context(user_session=user_session, user_id=user_id, agent_id=agent_id)

    # If SUPER_ADMIN, do not pass department_name
    if user_data.role == UserRole.SUPER_ADMIN:
        response = await agent_service.get_agent(agentic_application_id=agent_id)
    else:
        response = await agent_service.get_agent(agentic_application_id=agent_id, department_name=user_data.department_name)

    if not response:
        raise HTTPException(status_code=404, detail="No agents found")
    
    # Fetch mapped KB IDs for this agent
    try:
        from src.api.dependencies import ServiceProvider
        knowledgebase_service = ServiceProvider.get_knowledgebase_service()
        kb_ids = await knowledgebase_service.agent_kb_mapping_repo.get_knowledgebase_ids_for_agent(
            agentic_application_id=agent_id
        )
        response[0]["knowledgebase_ids"] = kb_ids if kb_ids else []
    except Exception as e:
        log.warning(f"Error fetching KB IDs for agent {agent_id}: {e}")
        response[0]["knowledgebase_ids"] = []
        
    # get_agent returns a list, extract the first element
    response = response[0]
    
    # If file_context_prompt is requested, try to load it from file
    if include_file_context_prompt:
        try:
            agent_name = response.get("AGENT_NAME", response.get("agent_name", response.get("agentic_application_name", "")))
            log.info(f"Loading file-context prompt for agent: '{agent_name}'")
            if agent_name:
                # Sanitize agent name for filename (use same logic as AgentServiceUtils)
                safe_agent_name = AgentServiceUtils.get_safe_agent_name(agent_name)
                prompt_file_path = os.path.join("agent_workspaces", "file_context_prompts", f"{safe_agent_name}_file_context_prompt.md")
                log.info(f"Looking for file-context prompt at: '{prompt_file_path}'")
                
                if os.path.exists(prompt_file_path):
                    with open(prompt_file_path, "r", encoding="utf-8") as f:
                        file_context_prompt = f.read()
                    response["file_context_management_prompt"] = file_context_prompt
                    response["file_context_prompt_exists"] = True
                    log.info(f"File-context prompt loaded successfully, length: {len(file_context_prompt)}")
                else:
                    response["file_context_management_prompt"] = None
                    response["file_context_prompt_exists"] = False
                    log.warning(f"File-context prompt not found at: '{prompt_file_path}'")
            else:
                log.warning(f"Agent name not found in response. Keys available: {list(response.keys())}")
                response["file_context_management_prompt"] = None
                response["file_context_prompt_exists"] = False
        except Exception as e:
            log.warning(f"Failed to load file-context prompt: {str(e)}")
            response["file_context_management_prompt"] = None
            response["file_context_prompt_exists"] = False
    
    update_session_context(agent_id='Unassigned')
    return response


@router.get("/get/details/{agent_id}")
async def get_agent_details_endpoint(
    request: Request, 
    agent_id: str, 
    agent_service: AgentService = Depends(ServiceProvider.get_agent_service),
    authorization_service: AuthorizationService = Depends(ServiceProvider.get_authorization_service),
    user_data: User = Depends(get_current_user)
):
    """
    Retrieves detailed information about an agent by its ID for studio display.

    Parameters:
    ----------
    request : Request
        The FastAPI Request object.
    agent_id : str
        The ID of the agent to be retrieved.
    agent_service : AgentService
        Dependency-injected AgentService instance.

    Returns:
    -------
    dict
        A dictionary containing the agent's detailed information.
        If the agent is not found, raises an HTTPException with status code 404.
    """
    # Check permissions first
    user_department = user_data.department_name 
    if not await authorization_service.check_operation_permission(user_data.email, user_data.role, "read", "agents", user_department):
        raise HTTPException(status_code=403, detail="You don't have permission to view agents.")
    
    user_id = request.cookies.get("user_id")
    user_session = request.cookies.get("user_session")
    update_session_context(user_session=user_session, user_id=user_id, agent_id=agent_id)

    # If SUPER_ADMIN, do not pass department_name
    if user_data.role == UserRole.SUPER_ADMIN:
        response = await agent_service.get_agent_details_studio(agentic_application_id=agent_id)
    else:
        response = await agent_service.get_agent_details_studio(agentic_application_id=agent_id, department_name=user_data.department_name)

    if not response:
        raise HTTPException(status_code=404, detail="Agent not found")
    
    # Fetch mapped KB IDs for this agent
    try:
        knowledgebase_service = ServiceProvider.get_knowledgebase_service()
        kb_ids = await knowledgebase_service.agent_kb_mapping_repo.get_knowledgebase_ids_for_agent(
            agentic_application_id=agent_id
        )
        response["knowledgebase_ids"] = kb_ids if kb_ids else []
    except Exception as e:
        log.warning(f"Error fetching KB IDs for agent {agent_id}: {e}")
        response["knowledgebase_ids"] = []
    
    update_session_context(agent_id='Unassigned')
    return response


@router.post("/get/by-list")
async def get_agents_by_list_endpoint(
    request: Request, 
    agent_ids: List[str], 
    agent_service: AgentService = Depends(ServiceProvider.get_agent_service),
    authorization_service: AuthorizationService = Depends(ServiceProvider.get_authorization_service),
    user_data: User = Depends(get_current_user)
):
    """Retrieves agents by a list of IDs."""
    # Check permissions first
    user_department = user_data.department_name 
    if not await authorization_service.check_operation_permission(user_data.email, user_data.role, "read", "agents", user_department):
        raise HTTPException(status_code=403, detail="You don't have permission to view agents.")
    
    user_id = request.cookies.get("user_id")
    user_session = request.cookies.get("user_session")
    update_session_context(user_session=user_session, user_id=user_id)
    
    agents = []
    knowledgebase_service = ServiceProvider.get_knowledgebase_service()
    
    for agent_id in agent_ids:
        if user_data.role == UserRole.SUPER_ADMIN:
            agent = await agent_service.get_agent(agentic_application_id=agent_id)
        else:
            agent = await agent_service.get_agent(agentic_application_id=agent_id, department_name=user_data.department_name)
        if agent:
            agent_data = agent[0]  # get_agent returns a list
            # Fetch mapped KB IDs for this agent
            try:
                kb_ids = await knowledgebase_service.agent_kb_mapping_repo.get_knowledgebase_ids_for_agent(
                    agentic_application_id=agent_id
                )
                agent_data["knowledgebase_ids"] = kb_ids if kb_ids else []
            except Exception as e:
                log.warning(f"Error fetching KB IDs for agent {agent_id}: {e}")
                agent_data["knowledgebase_ids"] = []
            agents.append(agent_data)
    return agents


@router.get("/get/search-paginated/")
async def search_paginated_agents_endpoint(
    request: Request,
    agentic_application_type: Optional[Union[str, List[str]]] = Query(None),
    search_value: Optional[str] = Query(None),
    page_number: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1),
    created_by: Optional[str] = Query(None),
    tag_names: List[str] = Query(None, description="Filter by tag names"),
    agent_service: AgentService = Depends(ServiceProvider.get_agent_service),
    authorization_service: AuthorizationService = Depends(ServiceProvider.get_authorization_service),
    user_data: User = Depends(get_current_user)
):
    """Searches agents with pagination."""
    # Check permissions first
    user_department = user_data.department_name 
    # if not await authorization_service.check_operation_permission(user_data.email, user_data.role, "read", "agents", user_department):
    #     raise HTTPException(status_code=403, detail="You don't have permission to view agents.")
    
    user_id = request.cookies.get("user_id")
    user_session = request.cookies.get("user_session")
    update_session_context(user_session=user_session, user_id=user_id)

    # If SUPER_ADMIN, do not restrict by department; otherwise include department_name
    if user_data.role == UserRole.SUPER_ADMIN:
        result = await agent_service.get_agents_by_search_or_page(
            search_value=search_value,
            limit=page_size,
            page=page_number,
            agentic_application_type=agentic_application_type,
            created_by=created_by,
            tag_names=tag_names
        )
    else:
        result = await agent_service.get_agents_by_search_or_page(
            search_value=search_value,
            limit=page_size,
            page=page_number,
            agentic_application_type=agentic_application_type,
            created_by=created_by,
            tag_names=tag_names,
            department_name=user_department
        )

    if not result["details"]:
        raise HTTPException(status_code=404, detail="No agents found matching criteria.")
    
    # Add knowledgebase IDs for each agent in the paginated results
    try:
        knowledgebase_service = ServiceProvider.get_knowledgebase_service()
        for agent in result["details"]:
            agent_id = agent.get("agentic_application_id")
            if agent_id:
                kb_ids = await knowledgebase_service.agent_kb_mapping_repo.get_knowledgebase_ids_for_agent(
                    agentic_application_id=agent_id
                )
                agent["knowledgebase_ids"] = kb_ids if kb_ids else []
            else:
                agent["knowledgebase_ids"] = []
    except Exception as e:
        log.warning(f"Error fetching KB IDs for paginated agents: {e}")
        for agent in result["details"]:
            agent["knowledgebase_ids"] = []
    
    return result


@router.post("/get/by-tags")
async def get_agents_by_tags_endpoint(
    request: Request, 
    tag_data: TagIdName, 
    agent_service: AgentService = Depends(ServiceProvider.get_agent_service),
    authorization_service: AuthorizationService = Depends(ServiceProvider.get_authorization_service),
    user_data: User = Depends(get_current_user)
):
    """Retrieves agents associated with given tag IDs or tag names."""
    # Check permissions first
    user_department = user_data.department_name 
    if not await authorization_service.check_operation_permission(user_data.email, user_data.role, "read", "agents", user_department):
        raise HTTPException(status_code=403, detail="You don't have permission to view agents.")
    
    user_id = request.cookies.get("user_id")
    user_session = request.cookies.get("user_session")
    update_session_context(user_session=user_session, user_id=user_id)

    result = await agent_service.get_agents_by_tag(
        tag_ids=tag_data.tag_ids,
        tag_names=tag_data.tag_names
    )
    if not result:
        raise HTTPException(status_code=404, detail="Agents not found")
    
    # Add knowledgebase IDs for each agent
    try:
        knowledgebase_service = ServiceProvider.get_knowledgebase_service()
        for agent in result:
            agent_id = agent.get("agentic_application_id")
            if agent_id:
                kb_ids = await knowledgebase_service.agent_kb_mapping_repo.get_knowledgebase_ids_for_agent(
                    agentic_application_id=agent_id
                )
                agent["knowledgebase_ids"] = kb_ids if kb_ids else []
            else:
                agent["knowledgebase_ids"] = []
    except Exception as e:
        log.warning(f"Error fetching KB IDs for agents by tags: {e}")
        for agent in result:
            agent["knowledgebase_ids"] = []
    
    return result


# EXPORT:EXCLUDE:START
@router.put("/update")
async def update_agent_endpoint(request: Request, update_request: UpdateAgentRequest, agent_service: AgentService = Depends(ServiceProvider.get_agent_service), authorization_server: AuthorizationService = Depends(ServiceProvider.get_authorization_service), user_data: User = Depends(get_current_user)):
    """
    Updates an agent by its ID.
    
    Access Control:
    - Admins can update any agent
    - Agent creators can update their own agents
    - Other users cannot update agents

    Parameters:
    ----------
    request : Request
        The FastAPI Request object.
    update_request : UpdateAgentRequest
        The request body containing the update details.
    agent_service : AgentService
        Dependency-injected AgentService instance.
    authorization_server: AuthorizationService

    Returns:
    -------
    dict
        A dictionary containing the status of the update operation.
        If the update is unsuccessful, raises an HTTPException with
        status code 400 and the status message.
    """
    if user_data.role == UserRole.SUPER_ADMIN:
        raise HTTPException(status_code=403, detail="Superadmin is not allowed to update agents.")
    # Check basic operation permission first
    user_department = user_data.department_name 
    if not await authorization_server.check_operation_permission(user_data.email, user_data.role, "update", "agents", user_department):
        raise HTTPException(status_code=403, detail="You don't have permission to update agents.")
    
    # Fetch current agent data; don't pass department_name for SUPER_ADMIN
    if user_data.role == UserRole.SUPER_ADMIN:
        agent_current_data = await agent_service.get_agent(agentic_application_id=update_request.agentic_application_id_to_modify)
    else:
        agent_current_data = await agent_service.get_agent(
            agentic_application_id=update_request.agentic_application_id_to_modify, department_name=user_data.department_name
        )

    if not agent_current_data:
        log.error(f"Agent not found: {update_request.agentic_application_id_to_modify}")
        raise HTTPException(status_code=404, detail="Agent not found")
    agent_current_data = agent_current_data[0]
    
    # Check if user's department owns this agent (public agents can only be updated by owning department)
    agent_department = agent_current_data.get("department_name")
    if agent_department and agent_department != user_data.department_name:
        raise HTTPException(
            status_code=403, 
            detail=f"You cannot update this agent. It belongs to department '{agent_department}'. Only users from the owning department can update it."
        )
    
    agent_type: str = agent_current_data["agentic_application_type"]
    user_id = user_data.email
    user_session = request.cookies.get("user_session")
    is_admin = False
    if update_request.is_admin:
        is_admin = await authorization_server.has_role(user_email=user_id, required_role=UserRole.ADMIN, department_name= user_department)
    is_creator = (agent_current_data.get("created_by") == user_data.username)
    if not (is_admin or is_creator):
        log.warning(f"User {user_id} attempted to update agent without admin privileges or creator access")
        raise HTTPException(status_code=403, detail="Admin privileges or agent creator access required to update this agent")
    
    update_session_context(user_session=user_session, user_id=user_id, model_used=update_request.model_name,
                           agent_id=update_request.agentic_application_id_to_modify,
                           agent_name=agent_current_data["agentic_application_name"],
                           agent_type=agent_type,
                           tools_binded=update_request.tools_id_to_remove,
                           tags=update_request.updated_tag_id_list,
                           action_type='update',
                           action_on='agent',
                           previous_value=agent_current_data)
    project_name = f"update-{agent_type.replace('_', '-')}"
    # Register Phoenix project (only once per unique project name)
    ensure_project_registered(
            project_name=project_name,
            auto_instrument=True,
            set_global_tracer_provider=False,
            batch=True
        )

    specialized_agent_service = ServiceProvider.get_specialized_agent_service(agent_type=agent_type)

    with traced_project_context_sync(project_name):
        if AgentType(agent_type).is_meta_type:
            response = await specialized_agent_service.update_agent(
                agentic_application_id=update_request.agentic_application_id_to_modify,
                agentic_application_description=update_request.agentic_application_description,
                agentic_application_workflow_description=update_request.agentic_application_workflow_description,
                model_name=update_request.model_name,
                created_by=user_data.username,
                system_prompt=update_request.system_prompt,
                welcome_message=update_request.welcome_message,
                regenerate_system_prompt=update_request.regenerate_system_prompt,
                regenerate_welcome_message=update_request.regenerate_welcome_message,
                is_admin=is_admin,
                worker_agents_id_to_add=update_request.tools_id_to_add,
                worker_agents_id_to_remove=update_request.tools_id_to_remove,
                updated_tag_id_list=update_request.updated_tag_id_list,
                is_public=update_request.is_public,
                shared_with_departments=update_request.shared_with_departments
            )
        else:
            response = await specialized_agent_service.update_agent(
                agentic_application_id=update_request.agentic_application_id_to_modify,
                agentic_application_description=update_request.agentic_application_description,
                agentic_application_workflow_description=update_request.agentic_application_workflow_description,
                model_name=update_request.model_name,
                created_by=agent_current_data.get("created_by"),
                system_prompt=update_request.system_prompt,
                welcome_message=update_request.welcome_message,
                regenerate_system_prompt=update_request.regenerate_system_prompt,
                regenerate_welcome_message=update_request.regenerate_welcome_message,
                is_admin=is_admin,
                tools_id_to_add=update_request.tools_id_to_add,
                tools_id_to_remove=update_request.tools_id_to_remove,
                updated_tag_id_list=update_request.updated_tag_id_list,
                validation_criteria=update_request.validation_criteria,
                knowledgebase_ids_to_add=update_request.knowledgebase_ids_to_add,
                knowledgebase_ids_to_remove=update_request.knowledgebase_ids_to_remove,
                is_public=update_request.is_public,
                shared_with_departments=update_request.shared_with_departments
            )
        response["status_message"] = response.get("message", "")
        log.info(f"Agent update response: {response}")
        if response["is_update"]:
            # Fetch new value; don't pass department_name for SUPER_ADMIN
            if user_data.role == UserRole.SUPER_ADMIN:
                new_value = await agent_service.get_agent(agentic_application_id=update_request.agentic_application_id_to_modify)
            else:
                new_value = await agent_service.get_agent(agentic_application_id=update_request.agentic_application_id_to_modify, department_name=user_data.department_name)
            update_session_context(new_value=new_value[0])
        log.debug(f"Agent update status: {response}")
        update_session_context(
                            model_used='Unassigned', agent_id='Unassigned', agent_name='Unassigned',
                            agent_type='Unassigned', tools_binded='Unassigned', tags='Unassigned',
                            action_on='Unassigned', action_type='Unassigned', previous_value='Unassigned',
                            new_value='Unassigned'
                        )
        # if response.get("is_update"):
        #     export_service=ServiceProvider.get_export_service()
        #     try:
        #         await export_service.send_email(agentic_application_id=update_request.agentic_application_id_to_modify, agentic_application_name=agent_current_data["agentic_application_name"],updater=user_id)
        #         log.info("Email notification sent successfully.")
        #     except Exception as e:
        #         log.info(f"Failed to send email notification: {e}")

    if not response.get("is_update"):
        raise HTTPException(status_code=400, detail=response.get("message"))
    
    # Handle file-context prompt regeneration or update
    # Priority: regenerate_file_context_prompt > file_context_management_prompt
    if update_request.regenerate_file_context_prompt:
        try:
            agent_name = agent_current_data.get("agentic_application_name", "")
            agent_goal = update_request.agentic_application_description or agent_current_data.get("agentic_application_description", "")
            workflow_description = update_request.agentic_application_workflow_description or agent_current_data.get("agentic_application_workflow_description", "")
            
            # Get the updated tools list from the agent
            updated_agent = await agent_service.get_agent(agentic_application_id=update_request.agentic_application_id_to_modify)
            if updated_agent:
                updated_agent = updated_agent[0] if isinstance(updated_agent, list) else updated_agent
                tools_id = updated_agent.get("tools_id", [])
                
                # Get model name from update request or agent data
                model_name = update_request.model_name or updated_agent.get("model_name", "gpt-4o")
                
                # Check if it's a meta agent
                is_meta_agent = updated_agent.get("agentic_application_type") in ["meta_agent", "planner_meta_agent"]
                
                # Use service method to regenerate file-context prompt
                result = await agent_service.agent_service_utils.regenerate_file_context_prompt(
                    agent_name=agent_name,
                    agent_goal=agent_goal,
                    workflow_description=workflow_description,
                    tools_id=tools_id,
                    model_name=model_name,
                    is_meta_agent=is_meta_agent
                )
                
                response["file_context_prompt_regenerated"] = result["success"]
                response["file_context_prompt_path"] = result.get("file_path")
                if not result["success"]:
                    response["file_context_prompt_error"] = result["message"]
            else:
                response["file_context_prompt_regenerated"] = False
                response["file_context_prompt_message"] = "Failed to fetch updated agent data for regeneration"
        except Exception as e:
            log.error(f"Failed to regenerate file-context prompt: {str(e)}")
            response["file_context_prompt_regenerated"] = False
            response["file_context_prompt_error"] = str(e)
    
    # Handle file-context prompt direct update if provided (and not regenerating)
    elif update_request.file_context_management_prompt is not None:
        try:
            agent_name = agent_current_data.get("agentic_application_name", "")
            if agent_name:
                # Use service method to update file-context prompt
                result = AgentServiceUtils.update_file_context_prompt(
                    agent_name=agent_name,
                    prompt_content=update_request.file_context_management_prompt
                )
                
                response["file_context_prompt_updated"] = result["success"]
                response["file_context_prompt_path"] = result.get("file_path")
                if not result["success"]:
                    response["file_context_prompt_error"] = result["message"]
            else:
                response["file_context_prompt_updated"] = False
                response["file_context_prompt_message"] = "Agent name not found, cannot save file-context prompt"
        except Exception as e:
            log.error(f"Failed to update file-context prompt: {str(e)}")
            response["file_context_prompt_updated"] = False
            response["file_context_prompt_error"] = str(e)
    
    return response


@router.delete("/delete/{agent_id}")
async def delete_agent_endpoint(request: Request, agent_id: str, delete_request: DeleteAgentRequest, agent_service: AgentService = Depends(ServiceProvider.get_agent_service), authorization_server: AuthorizationService = Depends(ServiceProvider.get_authorization_service), user_data: User = Depends(get_current_user)):
    """
    Deletes an agent by its ID.
    
    Access Control:
    - Admins can delete any agent
    - Agent creators can delete their own agents
    - Other users cannot delete agents

    Parameters:
    ----------
    request : Request
        The FastAPI Request object.
    agent_id : str
        The ID of the agent to be deleted.
    delete_request : DeleteAgentRequest
        The request body containing the user email ID and admin status.
    agent_service : AgentService
        Dependency-injected AgentService instance.

    Returns:
    -------
    dict
        A dictionary containing the status of the deletion operation.
        If the deletion is unsuccessful, raises an HTTPException
        with status code 400 and the status message.
    """
    if user_data.role == UserRole.SUPER_ADMIN:
        raise HTTPException(status_code=403, detail="Superadmin is not allowed to delete agents.")
    # Check basic operation permission first
    user_department = user_data.department_name 
    if not await authorization_server.check_operation_permission(user_data.email, user_data.role, "delete", "agents", user_department):
        raise HTTPException(status_code=403, detail="You don't have permission to delete agents.")
    
    # Fetch previous value; don't pass department_name for SUPER_ADMIN
    if user_data.role == UserRole.SUPER_ADMIN:
        previous_value = await agent_service.get_agent(agentic_application_id=agent_id)
    else:
        previous_value = await agent_service.get_agent(agentic_application_id=agent_id, department_name=user_data.department_name)

    if not previous_value:
        raise HTTPException(status_code=404, detail="Agent not found")
    previous_value = previous_value[0]
    
    # Check if user's department owns this agent (public agents can only be deleted by owning department)
    agent_department = previous_value.get("department_name")
    if agent_department and agent_department != user_data.department_name:
        raise HTTPException(
            status_code=403, 
            detail=f"You cannot delete this agent. It belongs to department '{agent_department}'. Only users from the owning department can delete it."
        )
    
    user_id = user_data.email
    user_session = request.cookies.get("user_session")
    is_admin = False
    if delete_request.is_admin:
        is_admin = await authorization_server.has_role(user_email=user_id, required_role=UserRole.ADMIN, department_name= user_department)
    is_creator = (previous_value.get("created_by") == user_data.username)
    if not (is_admin or is_creator):
        log.warning(f"User {user_id} attempted to delete agent without admin privileges or creator access")
        raise HTTPException(status_code=403, detail="Admin privileges or agent creator access required to delete this agent")
    
    update_session_context(user_session=user_session, user_id=user_id, agent_id=agent_id,
                           action_on='agent',
                           action_type='delete',
                           previous_value=previous_value)
    
    response = await agent_service.delete_agent(
        agentic_application_id=agent_id,
        user_id=user_data.username,
        is_admin=is_admin
    )
    response["status_message"] = response.get("message", "")

    update_session_context(agent_id='Unassigned', action_on='Unassigned', action_type='Unassigned', previous_value='Unassigned')
    if not response.get("is_delete"):
        agents = []
        for res in response.get('details', []):
            if res.get('agentic_application_name'):
                agents.append(res.get('agentic_application_name'))
        if agents:
            log.error(f"Agent delete failed: {response['message']} with names: {agents}")
            raise HTTPException(status_code=400, detail=f"Agent delete failed: {response['message']} with names: {agents}")
        raise HTTPException(status_code=400, detail=response.get("message"))
    
    # Move file-context prompt to recycle bin if agent deletion was successful
    agent_name = previous_value.get("agentic_application_name", "")
    if agent_name:
        file_context_result = AgentServiceUtils.move_file_context_prompt_to_recycle_bin(agent_name)
        response["file_context_prompt_recycled"] = file_context_result["success"]
        response["file_context_prompt_message"] = file_context_result["message"]
    
    return response


@router.get("/templates")
async def get_available_agent_templates_endpoint(
    request: Request, 
    agent_service: AgentService = Depends(ServiceProvider.get_agent_service),
    authorization_service: AuthorizationService = Depends(ServiceProvider.get_authorization_service),
    user_data: User = Depends(get_current_user)
):
    """Retrieves available agent templates."""
    # Check permissions first
    user_department = user_data.department_name 
    if not await authorization_service.check_operation_permission(user_data.email, user_data.role, "read", "agents", user_department):
        raise HTTPException(status_code=403, detail="You don't have permission to view agents.")
    
    user_id = request.cookies.get("user_id")
    user_session = request.cookies.get("user_session")
    update_session_context(user_session=user_session, user_id=user_id)

    templates = await agent_service.get_available_templates()
    if not templates:
        raise HTTPException(status_code=404, detail="No agent templates found")
    return templates


# Recycle bin requires modification with proper login/authentication functionality

@router.get("/recycle-bin/get")
async def get_all_agents_from_recycle_bin_endpoint(
    request: Request, 
    user_email_id: str = Query(...), 
    agent_service: AgentService = Depends(ServiceProvider.get_agent_service),
    authorization_server: AuthorizationService = Depends(ServiceProvider.get_authorization_service),
    user_data: User = Depends(get_current_user)
):
    """Retrieves all agents from the recycle bin."""
    # Check permissions first
    user_department = user_data.department_name 
    if not await authorization_server.check_operation_permission(user_data.email, user_data.role, "read", "agents", user_department):
        raise HTTPException(status_code=403, detail="You don't have permission to view agents.")
    
    user_id = user_data.email
    user_session = request.cookies.get("user_session")
    update_session_context(user_session=user_session, user_id=user_id)
    if not await authorization_server.has_role(user_email=user_email_id, required_role=UserRole.ADMIN, department_name= user_department):
        log.warning(f"User {user_email_id} attempted to access recycle bin without admin privileges")
        raise HTTPException(status_code=403, detail="Admin privileges required to access agent recycle bin")

    # Do not pass department_name for SUPER_ADMIN
    if user_data.role == UserRole.SUPER_ADMIN:
        agents = await agent_service.get_all_agents_from_recycle_bin()
    else:
        agents = await agent_service.get_all_agents_from_recycle_bin(department_name=user_data.department_name)

    if not agents:
        raise HTTPException(status_code=404, detail="No agents found in recycle bin")
    return agents


@router.post("/recycle-bin/restore/{agent_id}")
async def restore_agent_endpoint(
    request: Request, 
    agent_id: str, 
    user_email_id: str = Query(...), 
    agent_service: AgentService = Depends(ServiceProvider.get_agent_service),
    authorization_server: AuthorizationService = Depends(ServiceProvider.get_authorization_service),
    user_data: User = Depends(get_current_user)
):
    """Restores an agent from the recycle bin."""
    if user_data.role == UserRole.SUPER_ADMIN:
        raise HTTPException(status_code=403, detail="Superadmin is not allowed to restore agents.")
    # Check permissions first
    user_department = user_data.department_name 
    if not await authorization_server.check_operation_permission(user_data.email, user_data.role, "create", "agents", user_department):
        raise HTTPException(status_code=403, detail="You don't have permission to restore agents.")
    
    user_id = user_data.email
    user_session = request.cookies.get("user_session")
    update_session_context(user_session=user_session, user_id=user_id)
    if not await authorization_server.has_role(user_email=user_email_id, required_role=UserRole.ADMIN, department_name= user_department):
        log.warning(f"User {user_email_id} attempted to restore agent without admin privileges")
        raise HTTPException(status_code=403, detail="Admin privileges required to restore agents")

    # Get agent info from recycle bin before restoring (to get agent name for file restore)
    recycled_agents = await agent_service.get_all_agents_from_recycle_bin(department_name=user_data.department_name)
    agent_name = None
    if recycled_agents:
        for agent in recycled_agents:
            if agent.get("agentic_application_id") == agent_id:
                agent_name = agent.get("agentic_application_name", "")
                break

    # Do not pass department_name for SUPER_ADMIN
    if user_data.role == UserRole.SUPER_ADMIN:
        result = await agent_service.restore_agent(agentic_application_id=agent_id)
    else:
        result = await agent_service.restore_agent(agentic_application_id=agent_id, department_name=user_data.department_name)

    result["status_message"] = result.get("message", "")
    if not result.get("is_restored"):
        raise HTTPException(status_code=400, detail=result.get("message"))
    
    # Restore file-context prompt from recycle bin if agent restoration was successful
    if agent_name:
        file_context_result = AgentServiceUtils.restore_file_context_prompt_from_recycle_bin(agent_name)
        result["file_context_prompt_restored"] = file_context_result["success"]
        result["file_context_prompt_message"] = file_context_result["message"]
    
    return result


@router.delete("/recycle-bin/permanent-delete/{agent_id}")
async def delete_agent_from_recycle_bin_endpoint(
    request: Request, 
    agent_id: str, 
    user_email_id: str = Query(...), 
    agent_service: AgentService = Depends(ServiceProvider.get_agent_service),
    authorization_server: AuthorizationService = Depends(ServiceProvider.get_authorization_service),
    feedback_learning_service: FeedbackLearningService = Depends(ServiceProvider.get_feedback_learning_service),
    user_data: User = Depends(get_current_user)
):
    """Permanently deletes an agent from the recycle bin."""
    if user_data.role == UserRole.SUPER_ADMIN:
        raise HTTPException(status_code=403, detail="Superadmin is not allowed to delete agents.")
    # Check permissions first
    user_department = user_data.department_name 
    if not await authorization_server.check_operation_permission(user_data.email, user_data.role, "delete", "agents", user_department):
        raise HTTPException(status_code=403, detail="You don't have permission to delete agents.")
    
    user_id = user_data.email
    user_session = request.cookies.get("user_session")
    update_session_context(user_session=user_session, user_id=user_id)
    if not await authorization_server.has_role(user_email=user_email_id, required_role=UserRole.ADMIN, department_name= user_department):
        log.warning(f"User {user_email_id} attempted to permanently delete agent without admin privileges")
        raise HTTPException(status_code=403, detail="Admin privileges required to permanently delete agents")

    # Get agent info from recycle bin before deleting (to get agent name for file deletion)
    recycled_agents = await agent_service.get_all_agents_from_recycle_bin(department_name=user_data.department_name)
    agent_name = None
    if recycled_agents:
        for agent in recycled_agents:
            if agent.get("agentic_application_id") == agent_id:
                agent_name = agent.get("agentic_application_name", "")
                break

    # Do not pass department_name for SUPER_ADMIN
    if user_data.role == UserRole.SUPER_ADMIN:
        result = await agent_service.delete_agent_from_recycle_bin(agentic_application_id=agent_id)
    else:
        result = await agent_service.delete_agent_from_recycle_bin(agentic_application_id=agent_id, department_name=user_data.department_name)

    result["status_message"] = result.get("message", "")
    if not result.get("is_delete"):
        raise HTTPException(status_code=400, detail=result.get("message"))
    
    # Permanently delete file-context prompt from recycle bin if agent deletion was successful
    if agent_name:
        file_context_result = AgentServiceUtils.permanently_delete_file_context_prompt(agent_name)
        result["file_context_prompt_deleted"] = file_context_result["success"]
        result["file_context_prompt_message"] = file_context_result["message"]
    
    # Delete all feedback/learning records for this agent
    feedback_delete_result = await feedback_learning_service.delete_feedback_by_agent_id(agent_id)
    result["feedback_learning_deleted"] = feedback_delete_result.get("status") == "success"
    result["feedback_learning_deleted_count"] = feedback_delete_result.get("deleted_count", 0)
    result["feedback_learning_message"] = feedback_delete_result.get("message", "")
    
    return result


# ============================================================================
# Agent Export / Import Endpoints
# ============================================================================

@router.post("/export")
async def export_agents_endpoint(
        request: Request,
        agent_ids: List[str] = Query(..., description="List of agent IDs to export"),
        file_names: List[str] = Query(None, description="Optional list of file names to include"),
        user_email: Optional[str] = Query(None, description="Email of the user requesting the export"),
        export_and_deploy: Optional[bool] = Query(False, description="Flag to indicate if export is for deployment"),
        background_tasks: BackgroundTasks = BackgroundTasks(),
        authorization_service: AuthorizationService = Depends(ServiceProvider.get_authorization_service),
        user_data: User = Depends(get_current_user)
    ):
    # Check permissions first
    user_department = user_data.department_name 
    if not await authorization_service.check_operation_permission(user_data.email, user_data.role, "execute", "agents", user_department):
        raise HTTPException(status_code=403, detail="You don't have permission to export agents.")
    
    from src.database.repositories import ExportAgentRepository
    export_repo: ExportAgentRepository = None
    body = await request.body()
    config_data = body.decode("utf-8")[1:-1]
    from urllib.parse import unquote
    config_dict = {}
    if config_data:
        for pair in config_data.split("&"):
            if "=" in pair:
                key, value = pair.split("=", 1)
                config_dict[unquote(key)] = unquote(value)
    db_manager=ServiceProvider.get_database_manager()
    login_pool= await db_manager.get_pool(DatabaseName.LOGIN.db_name)
    exporter = AgentExporter(
        agent_ids=agent_ids,
        user_email=user_email,
        file_names=file_names,
        env_config=config_dict,
        tool_service=ServiceProvider.get_tool_service(),
        agent_service=ServiceProvider.get_agent_service(),
        mcp_service=ServiceProvider.get_mcp_tool_service(),
        export_service=ServiceProvider.get_export_service(),
        export_and_deploy=export_and_deploy,       
        login_pool=login_pool
    )

    try:
        zipfile_path = await exporter.export()
        filename = os.path.basename(zipfile_path)

        if export_and_deploy:
            GITHUB_USERNAME= get_user_secrets('GITHUB_USERNAME','')
            GITHUB_PAT = get_user_secrets('GITHUB_PAT','')
            GITHUB_EMAIL = get_user_secrets('GITHUB_EMAIL','')
            TARGET_REPO_NAME = get_user_secrets('TARGET_REPO_NAME','')
            TARGET_REPO_OWNER = get_user_secrets('TARGET_REPO_OWNER','')

            push_project(exporter.work_dir, exporter.work_dir, GITHUB_USERNAME, GITHUB_PAT, GITHUB_EMAIL, TARGET_REPO_NAME, TARGET_REPO_OWNER)


        def cleanup():
            try:
                shutil.rmtree(exporter.work_dir, ignore_errors=True)
                if os.path.exists(zipfile_path):
                    os.remove(zipfile_path)
            except Exception as e:
                log.error(f"Failed cleanup: {e}")
        background_tasks.add_task(cleanup)
        return FileResponse(
            zipfile_path,
            media_type="application/zip",
            filename=filename,
        )
    except Exception as e:
        error_message = f"Export failed: {str(e)}"
        tb = traceback.format_exc()
        log.error(f"{error_message}\n{tb}")
        raise HTTPException(status_code=500, detail=error_message)


@router.post("/import")
async def import_agents_endpoint(
    request: Request,
    created_by: str = Form(..., description="Email ID of the user importing the agents."),
    zip_file: UploadFile = File(..., description="The .zip file exported from another server."),
    agent_service: AgentService = Depends(ServiceProvider.get_agent_service),
    authorization_service: AuthorizationService = Depends(ServiceProvider.get_authorization_service),
    user_data: User = Depends(get_current_user),
):
    """
    Imports agents (and their associated tools, MCP servers, worker agents,
    and user-uploaded files) from an exported agent ZIP file.

    Conflict-resolution rules:
    - If an agent/tool/MCP ID already exists (normal table or recycle bin) → skipped.
    - If the ID is new but the name conflicts → renamed with _V1, _V2, etc.
    - Uploaded files with identical content are skipped; different content → renamed.
    - File-name renames are propagated to tool code and agent system prompts.

    Parameters
    ----------
    created_by : str
        The email ID of the user performing the import.
    zip_file : UploadFile
        The .zip file previously exported via ``/agents/export``.

    Returns
    -------
    dict
        Detailed summary with imported / skipped / renamed / failed entries
        for files, tools, MCP tools, worker agents, and agents.
    """
    # Permission check
    if not await authorization_service.check_operation_permission(
        user_data.email, user_data.role, "create", "agents"
    ):
        raise HTTPException(
            status_code=403,
            detail="You don't have permission to import agents. Only admins and developers can perform this action.",
        )

    if not zip_file.filename.endswith(".zip"):
        raise HTTPException(status_code=400, detail="Only .zip files are accepted.")

    try:
        file_content = await zip_file.read()
        zip_buffer = io.BytesIO(file_content)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Failed to read uploaded file: {str(e)}")

    try:

        importer = AgentImporter(
            tool_service=ServiceProvider.get_tool_service(),
            agent_service=agent_service,
            mcp_tool_service=ServiceProvider.get_mcp_tool_service(),
            tag_service=ServiceProvider.get_tag_service(),
            created_by=created_by.strip(),
        )
        result = await importer.import_from_zip(zip_buffer=zip_buffer)
    except ValueError as ve:
        raise HTTPException(status_code=400, detail=str(ve))
    except Exception as e:
        error_message = f"Agent import failed: {str(e)}"
        tb = traceback.format_exc()
        log.error(f"{error_message}\n{tb}")
        raise HTTPException(status_code=500, detail=error_message)

    return {"status": "success", "result": result}
# EXPORT:EXCLUDE:END



@router.get("/unused/get")
async def get_unused_agents_endpoint(
    request: Request,
    user_data: User = Depends(get_current_user),
    threshold_days: int = Query(default=15, description="Number of days to consider an agent as unused"),
    agent_service: AgentService = Depends(ServiceProvider.get_agent_service),
    authorization_server: AuthorizationService = Depends(ServiceProvider.get_authorization_service)
):
    """
    Retrieves agents that haven't been used for the specified number of days.
    
    Args:
        request: The FastAPI Request object
        threshold_days: Number of days to consider an agent as unused (default: 15)
        agent_service: Injected AgentService dependency
        authorization_server: Injected AuthorizationService dependency
    
    Returns:
        Dict containing list of unused agents with IST timezone formatting
    """
    # Check permissions first
    user_department = user_data.department_name 
    if not await authorization_server.check_operation_permission(user_data.email, user_data.role, "read", "agents", user_department):
        raise HTTPException(status_code=403, detail="You don't have permission to view agents.")
    
    user_id = user_data.email
    user_session = request.cookies.get("user_session")
    update_session_context(user_session=user_session, user_id=user_id)
    
    if not await authorization_server.has_role(user_email=user_id, required_role=UserRole.ADMIN, department_name= user_department):
        raise HTTPException(status_code=403, detail="Admin privileges required to get unused agents")
    
    try:
        # Do not pass department_name for SUPER_ADMIN
        if user_data.role == UserRole.SUPER_ADMIN:
            unused_agents = await agent_service.get_unused_agents(threshold_days=threshold_days)
        else:
            unused_agents = await agent_service.get_unused_agents(threshold_days=threshold_days, department_name=user_data.department_name)

        def format_datetime_to_days_ago(obj):
            if obj is None:
                return "Never used"
            ist_timezone = pytz.timezone("Asia/Kolkata")

            if hasattr(obj, 'tzinfo') and obj.tzinfo is not None:
                utc_time = obj
            else:
                utc_time = obj.replace(tzinfo=timezone.utc)
            
            ist_time = utc_time.astimezone(ist_timezone)
            current_time_ist = datetime.now(ist_timezone)
            time_diff = current_time_ist - ist_time
            days_ago = time_diff.days
            
            if days_ago == 0:
                return "Today"
            elif days_ago == 1:
                return "1 day ago"
            else:
                return f"{days_ago} days ago"
        
        formatted_agents = []
        for agent in unused_agents:
            formatted_agent = dict(agent)
            formatted_agent['created_on'] = format_datetime_to_days_ago(formatted_agent.get('created_on'))
            formatted_agent['last_used'] = format_datetime_to_days_ago(formatted_agent.get('last_used'))
            formatted_agents.append(formatted_agent)
        
        response_data = {
            "threshold_days": threshold_days,
            "unused_agents": {
                "count": len(formatted_agents),
                "details": formatted_agents
            }
        }
        
        log.info(f"Retrieved {len(unused_agents)} unused agents with threshold of {threshold_days} days")
        return response_data
        
    except Exception as e:
        log.error(f"Error retrieving unused agents: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error retrieving unused agents: {str(e)}")

@router.get("/tools-mapped/{agent_id}")
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
    user_department = user_data.department_name
    if not await authorization_server.check_operation_permission(user_data.email, user_data.role, "read", "agents", user_department):
        raise HTTPException(status_code=403, detail="You don't have permission to view agents.")
    
    user_id = request.cookies.get("user_id")
    user_session = request.cookies.get("user_session")
    update_session_context(user_session=user_session, user_id=user_id, agent_id=agent_id)
    
    # Verify agent exists and user has access to it (department check)
    if user_data.role == UserRole.SUPER_ADMIN:
        agent = await agent_service.get_agent(agentic_application_id=agent_id)
    else:
        agent = await agent_service.get_agent(agentic_application_id=agent_id, department_name=user_data.department_name)
    
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found or you don't have access to it.")
    
    tools_mapped = await agent_service.get_tools_or_agents_mapped_to_agent(agentic_application_id=agent_id)
    if not tools_mapped:
        raise HTTPException(status_code=404, detail="No tools found for the specified agent.")
    return tools_mapped


# ============================================================================
# Agent Sharing Endpoints (Admin Only)
# ============================================================================

@router.post("/{agent_id}/share")
async def share_agent_with_departments(
    request: Request,
    agent_id: str,
    target_departments: List[str],
    current_user: User = Depends(get_current_user),
    agent_service: AgentService = Depends(ServiceProvider.get_agent_service),
    tool_service: ToolService = Depends(ServiceProvider.get_tool_service),
    mcp_tool_service: McpToolService = Depends(ServiceProvider.get_mcp_tool_service),
    agent_sharing_repo = Depends(ServiceProvider.get_agent_sharing_repo)
):
    """
    Share an agent with one or more departments.
    Only Admins of the agent's department or SuperAdmins can share agents.
    When an agent is shared, all its tools (both regular and MCP) and knowledge bases are automatically shared too.
    
    Args:
        agent_id: The ID of the agent to share
        target_departments: List of department names to share with
        
    Returns:
        Dict with sharing results including tools and KBs shared count
    """
    user_id = request.cookies.get("user_id")
    user_session = request.cookies.get("user_session")
    update_session_context(user_session=user_session, user_id=user_id, agent_id=agent_id)
    
    # Check if user is Admin or SuperAdmin
    if current_user.role not in [UserRole.SUPER_ADMIN, UserRole.ADMIN]:
        raise HTTPException(
            status_code=403,
            detail="Only Admins can share agents with other departments"
        )
    
    # Get the agent to verify it exists and get its department
    agent_records = await agent_service.get_agent(agentic_application_id=agent_id)
    if not agent_records:
        raise HTTPException(status_code=404, detail=f"Agent not found with ID: {agent_id}")
    
    agent = agent_records[0] if isinstance(agent_records, list) else agent_records
    source_department = agent.get('department_name', 'General')
    agent_name = agent.get('agentic_application_name', '')
    
    # If Admin, verify they are admin of the agent's department
    if current_user.role == UserRole.ADMIN:
        if current_user.department_name != source_department:
            raise HTTPException(
                status_code=403,
                detail=f"You can only share agents from your own department ({current_user.department_name})"
            )
    
    # Get the agent's tools info for cascade sharing (separate regular tools and MCP tools)
    tools_id = agent.get('tools_id', [])
    tools_info = []
    mcp_tools_info = []
    if tools_id:
        for tid in tools_id:
            if tid.startswith("mcp_"):
                # MCP tool - fetch from MCP tool service
                mcp_tool_records = await mcp_tool_service.get_mcp_tool(tool_id=tid)
                if mcp_tool_records:
                    mcp_tool = mcp_tool_records[0]
                    mcp_tools_info.append({
                        'tool_id': tid,
                        'tool_name': mcp_tool.get('tool_name', ''),
                        'department_name': mcp_tool.get('department_name', source_department)
                    })
            else:
                # Regular tool - fetch from tool service
                tool_records = await tool_service.get_tool(tool_id=tid)
                if tool_records:
                    tool = tool_records[0]
                    tools_info.append({
                        'tool_id': tid,
                        'tool_name': tool.get('tool_name', ''),
                        'department_name': tool.get('department_name', source_department)
                    })
    
    # Get the agent's knowledge bases info for cascade sharing
    kbs_info = []
    if agent_service.knowledgebase_service:
        try:
            kb_ids = await agent_service.knowledgebase_service.agent_kb_mapping_repo.get_knowledgebase_ids_for_agent(agent_id)
            for kb_id in kb_ids:
                kb_record = await agent_service.knowledgebase_service.knowledgebase_repo.get_knowledgebase_by_id(kb_id)
                if kb_record:
                    kbs_info.append({
                        'kb_id': kb_id,
                        'kb_name': kb_record.get('knowledgebase_name', ''),
                        'department_name': kb_record.get('department_name', source_department)
                    })
        except Exception as e:
            log.warning(f"Failed to gather KB info for agent sharing: {e}")
    
    # Share the agent (and its tools + KBs will be shared automatically)
    result = await agent_sharing_repo.share_agent_with_multiple_departments(
        agentic_application_id=agent_id,
        agentic_application_name=agent_name,
        source_department=source_department,
        target_departments=target_departments,
        shared_by=current_user.email,
        tools_info=tools_info,
        mcp_tools_info=mcp_tools_info,
        kbs_info=kbs_info
    )
    
    log.info(f"Agent '{agent_id}' sharing result: {result}")
    return {
        "message": f"Agent shared with {result['success_count']} department(s), {result.get('total_tools_shared', 0)} tools, {result.get('total_mcp_tools_shared', 0)} MCP tools, and {result.get('total_kbs_shared', 0)} knowledge bases also shared",
        "agent_id": agent_id,
        "agent_name": agent_name,
        "source_department": source_department,
        "tools_shared": result.get('total_tools_shared', 0),
        "mcp_tools_shared": result.get('total_mcp_tools_shared', 0),
        "kbs_shared": result.get('total_kbs_shared', 0),
        **result
    }


@router.delete("/{agent_id}/share/{target_department}")
async def unshare_agent_from_department(
    request: Request,
    agent_id: str,
    target_department: str,
    current_user: User = Depends(get_current_user),
    agent_service: AgentService = Depends(ServiceProvider.get_agent_service),
    agent_sharing_repo = Depends(ServiceProvider.get_agent_sharing_repo)
):
    """
    Remove sharing of an agent from a specific department.
    Only Admins of the agent's department or SuperAdmins can unshare agents.
    """
    user_id = request.cookies.get("user_id")
    user_session = request.cookies.get("user_session")
    update_session_context(user_session=user_session, user_id=user_id, agent_id=agent_id)
    
    if current_user.role not in [UserRole.SUPER_ADMIN, UserRole.ADMIN]:
        raise HTTPException(
            status_code=403,
            detail="Only Admins can unshare agents"
        )
    
    agent_records = await agent_service.get_agent(agentic_application_id=agent_id)
    if not agent_records:
        raise HTTPException(status_code=404, detail=f"Agent not found with ID: {agent_id}")
    
    agent = agent_records[0] if isinstance(agent_records, list) else agent_records
    source_department = agent.get('department_name', 'General')
    
    if current_user.role == UserRole.ADMIN and current_user.department_name != source_department:
        raise HTTPException(
            status_code=403,
            detail=f"You can only manage sharing for agents from your own department"
        )
    
    success = await agent_sharing_repo.unshare_agent_from_department(agent_id, target_department)
    
    if success:
        return {
            "message": f"Agent '{agent.get('agentic_application_name')}' unshared from department '{target_department}'",
            "agent_id": agent_id,
            "target_department": target_department
        }
    else:
        raise HTTPException(
            status_code=404,
            detail=f"Agent was not shared with department '{target_department}'"
        )


@router.get("/{agent_id}/sharing")
async def get_agent_sharing_info(
    request: Request,
    agent_id: str,
    current_user: User = Depends(get_current_user),
    agent_service: AgentService = Depends(ServiceProvider.get_agent_service),
    agent_sharing_repo = Depends(ServiceProvider.get_agent_sharing_repo)
):
    """
    Get information about which departments an agent is shared with.
    """
    user_id = request.cookies.get("user_id")
    user_session = request.cookies.get("user_session")
    update_session_context(user_session=user_session, user_id=user_id, agent_id=agent_id)
    
    agent_records = await agent_service.get_agent(agentic_application_id=agent_id)
    if not agent_records:
        raise HTTPException(status_code=404, detail=f"Agent not found with ID: {agent_id}")
    
    agent = agent_records[0] if isinstance(agent_records, list) else agent_records
    
    # Get sharing info
    shared_departments = await agent_sharing_repo.get_shared_departments_for_agent(agent_id)
    
    return {
        "agent_id": agent_id,
        "agent_name": agent.get('agentic_application_name'),
        "owner_department": agent.get('department_name', 'General'),
        "is_public": agent.get('is_public', False),
        "shared_with": shared_departments
    }


@router.get("/shared-with-me")
async def get_agents_shared_with_my_department(
    request: Request,
    current_user: User = Depends(get_current_user),
    agent_service: AgentService = Depends(ServiceProvider.get_agent_service),
    agent_sharing_repo = Depends(ServiceProvider.get_agent_sharing_repo)
):
    """
    Get all agents that are shared with the current user's department.
    Returns agents shared via sharing table (not including public agents).
    """
    user_id = request.cookies.get("user_id")
    user_session = request.cookies.get("user_session")
    update_session_context(user_session=user_session, user_id=user_id)
    
    department = current_user.department_name or 'General'
    
    # Get agent IDs shared with this department
    shared_agent_ids = await agent_sharing_repo.get_agents_shared_with_department(department)
    
    if not shared_agent_ids:
        return {
            "department": department,
            "shared_agents": [],
            "count": 0
        }
    
    # Get full agent details
    shared_agents = []
    for agent_id in shared_agent_ids:
        agent_records = await agent_service.get_agent(agentic_application_id=agent_id)
        if agent_records:
            agent = agent_records[0] if isinstance(agent_records, list) else agent_records
            agent['is_shared'] = True
            shared_agents.append(agent)
    
    return {
        "department": department,
        "shared_agents": shared_agents,
        "count": len(shared_agents)
    }
