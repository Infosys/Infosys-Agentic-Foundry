# © 2024-25 Infosys Limited, Bangalore, India. All Rights Reserved.
import os
import shutil
import traceback
from datetime import datetime, timezone
import pytz
from fastapi import APIRouter, Depends, HTTPException, Request, Query, BackgroundTasks, Form
from fastapi.responses import FileResponse
from typing import List, Optional, Union

from src.schemas import AgentOnboardingRequest, UpdateAgentRequest, DeleteAgentRequest, TagIdName
from src.database.services import AgentService
from src.utils.secrets_handler import get_user_secrets
from src.api.dependencies import ServiceProvider # The dependency provider
from Export_Agent.AgentsExport import AgentExporter

from github_pusher import push_project

from phoenix.otel import register
from phoenix.trace import using_project
from telemetry_wrapper import logger as log, update_session_context
from src.auth.authorization_service import AuthorizationService
from src.auth.models import UserRole, User
from src.auth.dependencies import get_current_user

# Create an APIRouter instance for agent-related endpoints
router = APIRouter(prefix="/agents", tags=["Agents"])


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
    # Check permissions first
    if not await authorization_service.check_operation_permission(user_data.email, user_data.role, "create", "agents"):
        raise HTTPException(status_code=403, detail="You don't have permission to create agents. Only admins and developers can perform this action")
    
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
        register(
                project_name=project_name,
                auto_instrument=True,
                set_global_tracer_provider=False,
                batch=True
            )
        with using_project(project_name):
            update_session_context(
                model_used=onboarding_request.model_name,
                agent_name=onboarding_request.agent_name,
                agent_type=onboarding_request.agent_type,
                tools_binded=onboarding_request.tools_id
            )
            if onboarding_request.agent_type in specialized_agent_service.meta_type_templates:
                result = await specialized_agent_service.onboard_agent(
                    agent_name=onboarding_request.agent_name,
                    agent_goal=onboarding_request.agent_goal,
                    workflow_description=onboarding_request.workflow_description,
                    model_name=onboarding_request.model_name,
                    worker_agents_id=onboarding_request.tools_id,
                    user_id=onboarding_request.email_id,
                    tag_ids=onboarding_request.tag_ids
                )
            else:
                result = await specialized_agent_service.onboard_agent(
                    agent_name=onboarding_request.agent_name,
                    agent_goal=onboarding_request.agent_goal,
                    workflow_description=onboarding_request.workflow_description,
                    model_name=onboarding_request.model_name,
                    tools_id=onboarding_request.tools_id,
                    user_id=onboarding_request.email_id,
                    tag_ids=onboarding_request.tag_ids
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
    if not await authorization_service.check_operation_permission(user_data.email, user_data.role, "read", "agents"):
        raise HTTPException(status_code=403, detail="You don't have permission to view agents. Only admins and developers can perform this action")
    
    user_id = request.cookies.get("user_id")
    user_session = request.cookies.get("user_session")
    update_session_context(user_session=user_session, user_id=user_id)

    try:
        response = await agent_service.get_all_agents(agentic_application_type=agentic_application_type)

        if not response:
            raise HTTPException(status_code=404, detail="No agents found")

        return response

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error retrieving agents: {str(e)}")


@router.get("/get/details-for-chat-interface")
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


@router.get("/get/{agent_id}")
async def get_agent_by_id_endpoint(
    request: Request, 
    agent_id: str, 
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
    agent_service : AgentService
        Dependency-injected AgentService instance.

    Returns:
    -------
    dict
        A dictionary containing the agent's details.
        If no agent is found, raises an HTTPException with status code 404.
    """
    # Check permissions first
    if not await authorization_service.check_operation_permission(user_data.email, user_data.role, "read", "agents"):
        raise HTTPException(status_code=403, detail="You don't have permission to view agents. Only admins and developers can perform this action")
    
    user_id = request.cookies.get("user_id")
    user_session = request.cookies.get("user_session")
    update_session_context(user_session=user_session, user_id=user_id, agent_id=agent_id)
    response = await agent_service.get_agent(agentic_application_id=agent_id)

    if not response:
        raise HTTPException(status_code=404, detail="No agents found")
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
    if not await authorization_service.check_operation_permission(user_data.email, user_data.role, "read", "agents"):
        raise HTTPException(status_code=403, detail="You don't have permission to view agents. Only admins and developers can perform this action")
    
    user_id = request.cookies.get("user_id")
    user_session = request.cookies.get("user_session")
    update_session_context(user_session=user_session, user_id=user_id, agent_id=agent_id)

    response = await agent_service.get_agent_details_studio(agentic_application_id=agent_id)
    if not response:
        raise HTTPException(status_code=404, detail="Agent not found")
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
    if not await authorization_service.check_operation_permission(user_data.email, user_data.role, "read", "agents"):
        raise HTTPException(status_code=403, detail="You don't have permission to view agents. Only admins and developers can perform this action")
    
    user_id = request.cookies.get("user_id")
    user_session = request.cookies.get("user_session")
    update_session_context(user_session=user_session, user_id=user_id)
    
    agents = []
    for agent_id in agent_ids:
        agent = await agent_service.get_agent(agentic_application_id=agent_id)
        if agent:
            agents.append(agent[0]) # get_agent returns a list
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
    if not await authorization_service.check_operation_permission(user_data.email, user_data.role, "read", "agents"):
        raise HTTPException(status_code=403, detail="You don't have permission to view agents. Only admins and developers can perform this action")
    
    user_id = request.cookies.get("user_id")
    user_session = request.cookies.get("user_session")
    update_session_context(user_session=user_session, user_id=user_id)

    result = await agent_service.get_agents_by_search_or_page(
        search_value=search_value,
        limit=page_size,
        page=page_number,
        agentic_application_type=agentic_application_type,
        created_by=created_by,
        tag_names=tag_names
    )
    if not result["details"]:
        raise HTTPException(status_code=404, detail="No agents found matching criteria.")
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
    if not await authorization_service.check_operation_permission(user_data.email, user_data.role, "read", "agents"):
        raise HTTPException(status_code=403, detail="You don't have permission to view agents. Only admins and developers can perform this action")
    
    user_id = request.cookies.get("user_id")
    user_session = request.cookies.get("user_session")
    update_session_context(user_session=user_session, user_id=user_id)

    result = await agent_service.get_agents_by_tag(
        tag_ids=tag_data.tag_ids,
        tag_names=tag_data.tag_names
    )
    if not result:
        raise HTTPException(status_code=404, detail="Agents not found")
    return result


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
    # Check basic operation permission first
    if not await authorization_server.check_operation_permission(user_data.email, user_data.role, "update", "agents"):
        raise HTTPException(status_code=403, detail="You don't have permission to update agents. Only admins and developers can perform this action")
    
    agent_current_data = await agent_service.get_agent(
        agentic_application_id=update_request.agentic_application_id_to_modify
    )
    if not agent_current_data:
        log.error(f"Agent not found: {update_request.agentic_application_id_to_modify}")
        raise HTTPException(status_code=404, detail="Agent not found")
    agent_current_data = agent_current_data[0]
    agent_type: str = agent_current_data["agentic_application_type"]
    user_id = user_data.email
    user_session = request.cookies.get("user_session")
    is_admin = False
    if update_request.is_admin:
        is_admin = await authorization_server.has_role(user_email=user_id, required_role=UserRole.ADMIN)
    is_creator = (agent_current_data.get("created_by") == user_id)
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
    register(
            project_name=project_name,
            auto_instrument=True,
            set_global_tracer_provider=False,
            batch=True
        )

    specialized_agent_service = ServiceProvider.get_specialized_agent_service(agent_type=agent_type)

    with using_project(project_name):
        if agent_type in specialized_agent_service.meta_type_templates:
            response = await specialized_agent_service.update_agent(
                agentic_application_id=update_request.agentic_application_id_to_modify,
                agentic_application_description=update_request.agentic_application_description,
                agentic_application_workflow_description=update_request.agentic_application_workflow_description,
                model_name=update_request.model_name,
                created_by=update_request.user_email_id,
                system_prompt=update_request.system_prompt,
                is_admin=is_admin,
                worker_agents_id_to_add=update_request.tools_id_to_add,
                worker_agents_id_to_remove=update_request.tools_id_to_remove,
                updated_tag_id_list=update_request.updated_tag_id_list
            )
        else:
            response = await specialized_agent_service.update_agent(
                agentic_application_id=update_request.agentic_application_id_to_modify,
                agentic_application_description=update_request.agentic_application_description,
                agentic_application_workflow_description=update_request.agentic_application_workflow_description,
                model_name=update_request.model_name,
                created_by=update_request.user_email_id,
                system_prompt=update_request.system_prompt,
                is_admin=is_admin,
                tools_id_to_add=update_request.tools_id_to_add,
                tools_id_to_remove=update_request.tools_id_to_remove,
                updated_tag_id_list=update_request.updated_tag_id_list
            )
        response["status_message"] = response.get("message", "")
        log.info(f"Agent update response: {response}")
        if response["is_update"]:
            new_value = await agent_service.get_agent(agentic_application_id=update_request.agentic_application_id_to_modify)
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
    # Check basic operation permission first
    if not await authorization_server.check_operation_permission(user_data.email, user_data.role, "delete", "agents"):
        raise HTTPException(status_code=403, detail="You don't have permission to delete agents. Only admins and developers can perform this action")
    
    previous_value = await agent_service.get_agent(agentic_application_id=agent_id)
    if not previous_value:
        raise HTTPException(status_code=404, detail="Agent not found")
    previous_value = previous_value[0]
    user_id = user_data.email
    user_session = request.cookies.get("user_session")
    is_admin = False
    if delete_request.is_admin:
        is_admin = await authorization_server.has_role(user_email=user_id, required_role=UserRole.ADMIN)
    is_creator = (previous_value.get("created_by") == user_id)
    if not (is_admin or is_creator):
        log.warning(f"User {user_id} attempted to delete agent without admin privileges or creator access")
        raise HTTPException(status_code=403, detail="Admin privileges or agent creator access required to delete this agent")
    
    update_session_context(user_session=user_session, user_id=user_id, agent_id=agent_id,
                           action_on='agent',
                           action_type='delete',
                           previous_value=previous_value)
    
    response = await agent_service.delete_agent(
        agentic_application_id=agent_id,
        user_id=delete_request.user_email_id,
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
    if not await authorization_service.check_operation_permission(user_data.email, user_data.role, "read", "agents"):
        raise HTTPException(status_code=403, detail="You don't have permission to view agents. Only admins and developers can perform this action")
    
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
    if not await authorization_server.check_operation_permission(user_data.email, user_data.role, "read", "agents"):
        raise HTTPException(status_code=403, detail="You don't have permission to view agents. Only admins and developers can perform this action")
    
    user_id = user_data.email
    user_session = request.cookies.get("user_session")
    update_session_context(user_session=user_session, user_id=user_id)
    if not await authorization_server.has_role(user_email=user_email_id, required_role=UserRole.ADMIN):
        log.warning(f"User {user_email_id} attempted to access recycle bin without admin privileges")
        raise HTTPException(status_code=403, detail="Admin privileges required to access agent recycle bin")
    agents = await agent_service.get_all_agents_from_recycle_bin()
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
    # Check permissions first
    if not await authorization_server.check_operation_permission(user_data.email, user_data.role, "create", "agents"):
        raise HTTPException(status_code=403, detail="You don't have permission to restore agents. Only admins and developers can perform this action")
    
    user_id = user_data.email
    user_session = request.cookies.get("user_session")
    update_session_context(user_session=user_session, user_id=user_id)
    if not await authorization_server.has_role(user_email=user_email_id, required_role=UserRole.ADMIN):
        log.warning(f"User {user_email_id} attempted to restore agent without admin privileges")
        raise HTTPException(status_code=403, detail="Admin privileges required to restore agents")

    result = await agent_service.restore_agent(agentic_application_id=agent_id)
    result["status_message"] = result.get("message", "")
    if not result.get("is_restored"):
        raise HTTPException(status_code=400, detail=result.get("message"))
    return result


@router.delete("/recycle-bin/permanent-delete/{agent_id}")
async def delete_agent_from_recycle_bin_endpoint(
    request: Request, 
    agent_id: str, 
    user_email_id: str = Query(...), 
    agent_service: AgentService = Depends(ServiceProvider.get_agent_service),
    authorization_server: AuthorizationService = Depends(ServiceProvider.get_authorization_service),
    user_data: User = Depends(get_current_user)
):
    """Permanently deletes an agent from the recycle bin."""
    # Check permissions first
    if not await authorization_server.check_operation_permission(user_data.email, user_data.role, "delete", "agents"):
        raise HTTPException(status_code=403, detail="You don't have permission to delete agents. Only admins and developers can perform this action")
    
    user_id = user_data.email
    user_session = request.cookies.get("user_session")
    update_session_context(user_session=user_session, user_id=user_id)
    if not await authorization_server.has_role(user_email=user_email_id, required_role=UserRole.ADMIN):
        log.warning(f"User {user_email_id} attempted to permanently delete agent without admin privileges")
        raise HTTPException(status_code=403, detail="Admin privileges required to permanently delete agents")

    result = await agent_service.delete_agent_from_recycle_bin(agentic_application_id=agent_id)
    result["status_message"] = result.get("message", "")
    if not result.get("is_delete"):
        raise HTTPException(status_code=400, detail=result.get("message"))
    return result

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
    if not await authorization_service.check_operation_permission(user_data.email, user_data.role, "execute", "agents"):
        raise HTTPException(status_code=403, detail="You don't have permission to export agents. Only admins and developers can perform this action")
    
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
    login_pool= await db_manager.get_pool('login')
    exporter = AgentExporter(
        agent_ids=agent_ids,
        user_email=user_email,
        file_names=file_names,
        env_config=config_dict,
        tool_service=ServiceProvider.get_tool_service(),
        agent_service=ServiceProvider.get_agent_service(),
        mcp_service=ServiceProvider.get_mcp_tool_service(),
        export_repo=ServiceProvider.get_export_service(),
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

            push_project(exporter.work_dir,exporter.work_dir, GITHUB_USERNAME, GITHUB_PAT, GITHUB_EMAIL, TARGET_REPO_NAME, TARGET_REPO_OWNER)


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
    if not await authorization_server.check_operation_permission(user_data.email, user_data.role, "read", "agents"):
        raise HTTPException(status_code=403, detail="You don't have permission to view agents. Only admins and developers can perform this action")
    
    user_id = user_data.email
    user_session = request.cookies.get("user_session")
    update_session_context(user_session=user_session, user_id=user_id)
    
    if not await authorization_server.has_role(user_email=user_id, required_role=UserRole.ADMIN):
        raise HTTPException(status_code=403, detail="Admin privileges required to get unused agents")
    
    try:
        unused_agents = await agent_service.get_unused_agents(threshold_days=threshold_days)

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