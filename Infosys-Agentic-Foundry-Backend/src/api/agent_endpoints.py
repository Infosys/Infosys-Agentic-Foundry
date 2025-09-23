# © 2024-25 Infosys Limited, Bangalore, India. All Rights Reserved.
import os
import shutil
import asyncpg
import traceback
from fastapi import APIRouter, Depends, HTTPException, Request, Query, BackgroundTasks
from fastapi.responses import FileResponse
from typing import List, Optional, Union

from src.schemas import AgentOnboardingRequest, UpdateAgentRequest, DeleteAgentRequest, TagIdName
from src.database.services import AgentService
from src.api.dependencies import ServiceProvider # The dependency provider
from Export_Agent.AgentsExport import AgentExporter

from phoenix.otel import register
from phoenix.trace import using_project
from telemetry_wrapper import logger as log, update_session_context


# Create an APIRouter instance for agent-related endpoints
router = APIRouter(prefix="/agents", tags=["Agents"])


@router.post("/onboard")
async def onboard_agent_endpoint(request: Request, onboarding_request: AgentOnboardingRequest):
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
async def get_all_agents_endpoint(request: Request, agentic_application_type: Optional[Union[str, List[str]]] = Query(None), agent_service: AgentService = Depends(ServiceProvider.get_agent_service)):
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
async def get_agents_details_for_chat_interface_endpoint(request: Request, agent_service: AgentService = Depends(ServiceProvider.get_agent_service)):
    """Retrieves basic agent details for chat purposes."""
    user_id = request.cookies.get("user_id")
    user_session = request.cookies.get("user_session")
    update_session_context(user_session=user_session, user_id=user_id)
    
    agent_details = await agent_service.get_agents_details_for_chat()
    if not agent_details:
        raise HTTPException(status_code=404, detail="No agents found for chat interface.")
    return agent_details


@router.get("/get/{agent_id}")
async def get_agent_by_id_endpoint(request: Request, agent_id: str, agent_service: AgentService = Depends(ServiceProvider.get_agent_service)):
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
    user_id = request.cookies.get("user_id")
    user_session = request.cookies.get("user_session")
    update_session_context(user_session=user_session, user_id=user_id, agent_id=agent_id)
    response = await agent_service.get_agent(agentic_application_id=agent_id)

    if not response:
        raise HTTPException(status_code=404, detail="No agents found")
    update_session_context(agent_id='Unassigned')
    return response


@router.get("/get/details/{agent_id}")
async def get_agent_details_endpoint(request: Request, agent_id: str, agent_service: AgentService = Depends(ServiceProvider.get_agent_service)):
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
    user_id = request.cookies.get("user_id")
    user_session = request.cookies.get("user_session")
    update_session_context(user_session=user_session, user_id=user_id, agent_id=agent_id)

    response = await agent_service.get_agent_details_studio(agentic_application_id=agent_id)
    if not response:
        raise HTTPException(status_code=404, detail="Agent not found")
    update_session_context(agent_id='Unassigned')
    return response


@router.post("/get/by-list")
async def get_agents_by_list_endpoint(request: Request, agent_ids: List[str], agent_service: AgentService = Depends(ServiceProvider.get_agent_service)):
    """Retrieves agents by a list of IDs."""
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
    agent_service: AgentService = Depends(ServiceProvider.get_agent_service)
):
    """Searches agents with pagination."""
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
async def get_agents_by_tags_endpoint(request: Request, tag_data: TagIdName, agent_service: AgentService = Depends(ServiceProvider.get_agent_service)):
    """Retrieves agents associated with given tag IDs or tag names."""
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
async def update_agent_endpoint(request: Request, update_request: UpdateAgentRequest, agent_service: AgentService = Depends(ServiceProvider.get_agent_service)):
    """
    Updates an agent by its ID.

    Parameters:
    ----------
    request : Request
        The FastAPI Request object.
    update_request : UpdateAgentRequest
        The request body containing the update details.
    agent_service : AgentService
        Dependency-injected AgentService instance.

    Returns:
    -------
    dict
        A dictionary containing the status of the update operation.
        If the update is unsuccessful, raises an HTTPException with
        status code 400 and the status message.
    """
    agent_current_data = await agent_service.get_agent(
        agentic_application_id=update_request.agentic_application_id_to_modify
    )
    if not agent_current_data:
        log.error(f"Agent not found: {update_request.agentic_application_id_to_modify}")
        raise HTTPException(status_code=404, detail="Agent not found")
    agent_current_data = agent_current_data[0]
    agent_type: str = agent_current_data["agentic_application_type"]

    user_id = request.cookies.get("user_id")
    user_session = request.cookies.get("user_session")
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
                is_admin=update_request.is_admin,
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
                is_admin=update_request.is_admin,
                tools_id_to_add=update_request.tools_id_to_add,
                tools_id_to_remove=update_request.tools_id_to_remove,
                updated_tag_id_list=update_request.updated_tag_id_list
            )
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
        raise HTTPException(status_code=400, detail=response.get("status_message"))
    return response


@router.delete("/delete/{agent_id}")
async def delete_agent_endpoint(request: Request, agent_id: str, delete_request: DeleteAgentRequest, agent_service: AgentService = Depends(ServiceProvider.get_agent_service)):
    """
    Deletes an agent by its ID.

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
    previous_value = await agent_service.get_agent(agentic_application_id=agent_id)
    if not previous_value:
        raise HTTPException(status_code=404, detail="Agent not found")
    previous_value = previous_value[0]
    user_id = request.cookies.get("user_id")
    user_session = request.cookies.get("user_session")
    update_session_context(user_session=user_session, user_id=user_id, agent_id=agent_id,
                           action_on='agent',
                           action_type='delete',
                           previous_value=previous_value)
    
    response = await agent_service.delete_agent(
        agentic_application_id=agent_id,
        user_id=delete_request.user_email_id,
        is_admin=delete_request.is_admin
    )

    update_session_context(agent_id='Unassigned', action_on='Unassigned', action_type='Unassigned', previous_value='Unassigned')
    if not response.get("is_delete"):
        raise HTTPException(status_code=400, detail=response.get("status_message"))
    return response


# Recycle bin requires modification with proper login/authentication functionality

@router.get("/recycle-bin/get")
async def get_all_agents_from_recycle_bin_endpoint(request: Request, user_email_id: str = Query(...), agent_service: AgentService = Depends(ServiceProvider.get_agent_service)):
    """Retrieves all agents from the recycle bin."""
    user_id = request.cookies.get("user_id")
    user_session = request.cookies.get("user_session")
    update_session_context(user_session=user_session, user_id=user_id)
    
    connection_login = await asyncpg.connect(
        host=os.getenv("POSTGRESQL_HOST"),
        database="login",
        user=os.getenv("POSTGRESQL_USER"),
        password=os.getenv("POSTGRESQL_PASSWORD")
    )
    user_role = await connection_login.fetchval("SELECT role FROM login_credential WHERE mail_id = $1", user_email_id)
    if user_role.lower() != "admin":
        raise HTTPException(status_code=403, detail="You are not authorized to access this resource")
    await connection_login.close()

    agents = await agent_service.get_all_agents_from_recycle_bin()
    if not agents:
        raise HTTPException(status_code=404, detail="No agents found in recycle bin")
    return agents


@router.post("/recycle-bin/restore/{agent_id}")
async def restore_agent_endpoint(request: Request, agent_id: str, user_email_id: str = Query(...), agent_service: AgentService = Depends(ServiceProvider.get_agent_service)):
    """Restores an agent from the recycle bin."""
    user_id = request.cookies.get("user_id")
    user_session = request.cookies.get("user_session")
    update_session_context(user_session=user_session, user_id=user_id)
    
    connection_login = await asyncpg.connect(
        host=os.getenv("POSTGRESQL_HOST"),
        database="login",
        user=os.getenv("POSTGRESQL_USER"),
        password=os.getenv("POSTGRESQL_PASSWORD")
    )
    user_role = await connection_login.fetchval("SELECT role FROM login_credential WHERE mail_id = $1", user_email_id)
    if user_role.lower() != "admin":
        raise HTTPException(status_code=403, detail="You are not authorized to access this resource")
    await connection_login.close()

    result = await agent_service.restore_agent(agentic_application_id=agent_id)
    if not result.get("is_restored"):
        raise HTTPException(status_code=400, detail=result.get("status_message"))
    return result


@router.delete("/recycle-bin/permanent-delete/{agent_id}")
async def delete_agent_from_recycle_bin_endpoint(request: Request, agent_id: str, user_email_id: str = Query(...), agent_service: AgentService = Depends(ServiceProvider.get_agent_service)):
    """Permanently deletes an agent from the recycle bin."""
    user_id = request.cookies.get("user_id")
    user_session = request.cookies.get("user_session")
    update_session_context(user_session=user_session, user_id=user_id)
    
    connection_login = await asyncpg.connect(
        host=os.getenv("POSTGRESQL_HOST"),
        database="login",
        user=os.getenv("POSTGRESQL_USER"),
        password=os.getenv("POSTGRESQL_PASSWORD")
    )
    user_role = await connection_login.fetchval("SELECT role FROM login_credential WHERE mail_id = $1", user_email_id)
    if user_role.lower() != "admin":
        raise HTTPException(status_code=403, detail="You are not authorized to access this resource")
    await connection_login.close()

    result = await agent_service.delete_agent_from_recycle_bin(agentic_application_id=agent_id)
    if not result.get("is_delete"):
        raise HTTPException(status_code=400, detail=result.get("status_message"))
    return result


@router.get("/export")
async def export_agents_endpoint(
        request: Request,
        agent_ids: List[str] = Query(..., description="List of agent IDs to export"),
        user_email: Optional[str] = Query(None, description="Email of the user requesting the export"),
        background_tasks: BackgroundTasks = BackgroundTasks(),
    ):
    from src.database.repositories import ExportAgentRepository
    export_repo : ExportAgentRepository =None
    exporter = AgentExporter(
        agent_ids=agent_ids,
        user_email=user_email,
        tool_service=ServiceProvider.get_tool_service(),
        agent_service=ServiceProvider.get_agent_service(),
        export_repo=ServiceProvider.get_export_service()
    )

    try:
        zipfile_path = await exporter.export()
        filename = os.path.basename(zipfile_path)

        def cleanup():
            try:
                shutil.rmtree(exporter.work_dir, ignore_errors=True)
                shutil.rmtree(exporter.exp_dir, ignore_errors=True)
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


