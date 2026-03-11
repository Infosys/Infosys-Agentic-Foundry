# © 2024-25 Infosys Limited, Bangalore, India. All Rights Reserved.
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Request, Query

from src.schemas import (
    CreateGroupRequest, UpdateGroupRequest, AddUsersRequest, RemoveUsersRequest,
    AddAgentsRequest, RemoveAgentsRequest, GroupResponse, GroupOperationResponse,
    CreateGroupResponse, GetGroupResponse, GetAllGroupsResponse,
    GroupUserManagementResponse, GroupAgentManagementResponse,
    GroupUpdateResponse, GetGroupsByUserResponse, GetGroupsByAgentResponse
)
from src.database.services import GroupService, AgentService
from src.auth.auth_service import AuthService
from src.api.dependencies import ServiceProvider
from src.auth.dependencies import get_current_user
from src.auth.models import User, UserRole
from src.auth.authorization_service import AuthorizationService
from telemetry_wrapper import logger as log

# Create an APIRouter instance for group management related endpoints
router = APIRouter(prefix="/groups", tags=["Group Management"])


async def require_admin(
    current_user: User,
    authorization_service: AuthorizationService
):
    """
    Helper function to check if the current user is a super-admin.
    For now, we'll treat ADMIN role as super-admin. This can be extended later
    with a separate SUPER_ADMIN role if needed.
    """
    is_admin = await authorization_service.has_role(user_email=current_user.email, required_role=UserRole.ADMIN, department_name= current_user.department_name)
    if not is_admin:
        log.warning(f"User {current_user.email} attempted to access super-admin endpoint without privileges")
        raise HTTPException(
            status_code=403, 
            detail="Super-admin or admin privileges required for group management operations"
        )


def check_group_admin_permissions(user: User, target_department: str) -> None:
    """Check if user has permissions to manage groups in the specified department"""
    # SuperAdmin can manage groups in any department
    if user.role == 'SuperAdmin':
        return
    
    # Admin can only manage groups in their own department
    if user.role == 'Admin':
        user_department = getattr(user, 'department_name', None) 
        if user_department != target_department:
            raise HTTPException(
                status_code=403,
                detail=f"Access denied. Admin users can only manage groups in their own department ('{user_department}'). Cannot manage groups in department '{target_department}'."
            )
        return
    
    # Other roles cannot manage groups
    raise HTTPException(
        status_code=403,
        detail="Access denied. Only Admin and SuperAdmin can manage groups."
    )


async def validate_users_exist(user_emails: List[str], auth_service, department_name: str = None) -> List[str]:
    """
    Validate that all provided user emails exist in the database.
    
    Args:
        user_emails: List of user emails to validate
        auth_service: AuthService instance for user validation
        
    Returns:
        List of validated user emails
        
    Raises:
        HTTPException: If any user email is not found
    """
    if not user_emails:
        return []
    
    invalid_users = []
    for email in user_emails:
        user = await auth_service.user_repo.get_user_by_email(email, department_name = department_name)
        if not user:
            invalid_users.append(email)
    
    if invalid_users:
        raise HTTPException(
            status_code=400, 
            detail=f"The following user emails do not exist: {', '.join(invalid_users)}"
        )
    
    return user_emails


async def validate_users_exist_and_in_department(user_emails: List[str], auth_service,  target_department: str) -> List[str]:
    """
    Validate that all provided user emails exist and belong to the specified department.
    
    Args:
        user_emails: List of user emails to validate
        auth_service: AuthService instance for user validation
        target_department: The target department to validate users against
        
    Returns:
        List of validated user emails
        
    Raises:
        HTTPException: If any user email is not found or belongs to different department
    """
    if not user_emails:
        return []
    
    invalid_users = []
    wrong_department_users = []
    
    for email in user_emails:
        user = await auth_service.user_repo.get_user_by_email(email, department_name=target_department)
        if not user:
            invalid_users.append(email)
        else:
            # Check user's department
            user_department = user.get('department_name') 
            if user_department != target_department:
                wrong_department_users.append(f"{email} (belongs to '{user_department}')")
    
    error_messages = []
    if invalid_users:
        error_messages.append(f"The following user emails do not exist: {', '.join(invalid_users)}")
    if wrong_department_users:
        error_messages.append(f"The following users belong to different departments: {', '.join(wrong_department_users)}")
    
    if error_messages:
        raise HTTPException(
            status_code=400, 
            detail=f"User validation failed: {'; '.join(error_messages)}"
        )
    
    return user_emails


async def validate_agents_exist(agent_ids: List[str], agent_service) -> List[str]:
    """
    Validate that all provided agent IDs exist in the database.
    
    Args:
        agent_ids: List of agent IDs to validate
        agent_service: AgentService instance for agent validation
        
    Returns:
        List of validated agent IDs
        
    Raises:
        HTTPException: If any agent ID is not found
    """
    if not agent_ids:
        return []
    
    invalid_agents = []
    for agent_id in agent_ids:
        # Use get_agent method with agentic_application_id parameter
        agents = await agent_service.get_agent(agentic_application_id=agent_id)
        if not agents or len(agents) == 0:
            invalid_agents.append(agent_id)
    
    if invalid_agents:
        raise HTTPException(
            status_code=400, 
            detail=f"The following agent IDs do not exist: {', '.join(invalid_agents)}"
        )
    
    return agent_ids


async def validate_agents_exist_and_in_department(agent_ids: List[str], agent_service, target_department: str) -> List[str]:
    """
    Validate that all provided agent IDs exist and belong to the specified department.
    
    Args:
        agent_ids: List of agent IDs to validate
        agent_service: AgentService instance for agent validation
        target_department: The target department to validate agents against
        
    Returns:
        List of validated agent IDs
        
    Raises:
        HTTPException: If any agent ID is not found or belongs to different department
    """
    if not agent_ids:
        return []
    
    invalid_agents = []
    wrong_department_agents = []
    
    for agent_id in agent_ids:
        # Use get_agent method with department_name parameter to check if agent exists in target department
        agents = await agent_service.get_agent(agentic_application_id=agent_id, department_name=target_department)
        if not agents or len(agents) == 0:
            # Check if agent exists in any department
            all_dept_agents = await agent_service.get_agent(agentic_application_id=agent_id)
            if not all_dept_agents or len(all_dept_agents) == 0:
                invalid_agents.append(agent_id)
            else:
                # Agent exists but in different department
                agent_department = all_dept_agents[0].get('department_name') 
                wrong_department_agents.append(f"{agent_id} (belongs to '{agent_department}')")
    
    error_messages = []
    if invalid_agents:
        error_messages.append(f"The following agent IDs do not exist: {', '.join(invalid_agents)}")
    if wrong_department_agents:
        error_messages.append(f"The following agents belong to different departments: {', '.join(wrong_department_agents)}")
    
    if error_messages:
        raise HTTPException(
            status_code=400, 
            detail=f"Agent validation failed: {'; '.join(error_messages)}"
        )
    
    return agent_ids


@router.post("/create-group", response_model=CreateGroupResponse)
async def create_group_endpoint(
    request: Request,
    group_request: CreateGroupRequest,
    current_user: User = Depends(get_current_user),
    group_service: GroupService = Depends(ServiceProvider.get_group_service),
    authorization_service: AuthorizationService = Depends(ServiceProvider.get_authorization_service),
    auth_service: AuthService = Depends(ServiceProvider.get_auth_service),
    agent_service: AgentService = Depends(ServiceProvider.get_agent_service)
):
    """
    Creates a new group. SuperAdmins can create groups in any department, Admins can create groups in their own department.
    Department context is automatically extracted from the current user's department.
    
    Args:
        request: The FastAPI Request object
        group_request: Request containing group creation details
        current_user: The currently authenticated user (department extracted from user data)
        group_service: The group service
        authorization_service: The authorization service for checking admin privileges
        auth_service: The auth service for user validation
        agent_service: The agent service for agent validation
        
    Returns:
        CreateGroupResponse: Status of the group creation operation
    """
    if current_user.role == UserRole.SUPER_ADMIN:
        raise HTTPException(status_code=403, detail="Superadmin is not allowed to create groups.")
    # Extract department from user data
    department_name = current_user.department_name 
    
    # Check if user has permissions to create groups in this department
    check_group_admin_permissions(current_user, department_name)
    
    try:
        # Validate that users and agents exist and belong to the same department
        validated_users = await validate_users_exist_and_in_department(group_request.user_emails, auth_service, department_name)
        validated_agents = await validate_agents_exist_and_in_department(group_request.agent_ids, agent_service, department_name)
        
        result = await group_service.create_group(
            group_name=group_request.group_name,
            group_description=group_request.group_description,
            user_emails=validated_users,
            agent_ids=validated_agents,
            created_by=current_user.email,
            department_name=department_name
        )
        
        if result["success"]:
            log.info(f"User {current_user.email} ({current_user.role}) created group '{group_request.group_name}' in department '{department_name}'")
            return CreateGroupResponse(
                success=True,
                message=result["message"],
                group_name=result["group_name"],
                department_name=department_name,
                created_by=result["created_by"],
                user_count=result["user_count"],
                agent_count=result["agent_count"]
            )
        else:
            raise HTTPException(status_code=400, detail=result["message"])
            
    except HTTPException:
        raise
    except Exception as e:
        log.error(f"Error creating group in department '{department_name}': {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error creating group: {str(e)}")


@router.get("/get-group-by-name/{group_name}", response_model=GetGroupResponse)
async def get_group_endpoint(
    request: Request,
    group_name: str,
    current_user: User = Depends(get_current_user),
    group_service: GroupService = Depends(ServiceProvider.get_group_service),
    authorization_service: AuthorizationService = Depends(ServiceProvider.get_authorization_service)
):
    """
    Retrieves a group by its name. super-admin or admin of own department can view groups.
    Department context is automatically extracted from the current user's department.
    
    Args:
        request: The FastAPI Request object
        group_name: The name of the group to retrieve
        current_user: The currently authenticated user (department extracted from user data)
        group_service: The group service
        authorization_service: The authorization service for checking super-admin privileges
        
    Returns:
        GetGroupResponse: Group information
    """
    await require_admin(current_user, authorization_service)
    
    # Extract department from user data
    department_name = current_user.department_name 
    
    try:
        if current_user.role == UserRole.SUPER_ADMIN:
            result = await group_service.get_group(group_name)
        else:
            result = await group_service.get_group(group_name, department_name=department_name)
        
        return GetGroupResponse(
            success=result["success"],
            message=result["message"],
            group=GroupResponse(**result["group"]) if result["group"] else None
        )
            
    except Exception as e:
        log.error(f"Error retrieving group: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error retrieving group: {str(e)}")


@router.get("/get-all-groups", response_model=GetAllGroupsResponse)
async def get_all_groups_endpoint(
    request: Request,
    current_user: User = Depends(get_current_user),
    group_service: GroupService = Depends(ServiceProvider.get_group_service),
    authorization_service: AuthorizationService = Depends(ServiceProvider.get_authorization_service)
):
    """
    Retrieves all groups. Only super-admins can view all groups.
    
    Args:
        request: The FastAPI Request object
        current_user: The currently authenticated user
        group_service: The group service
        authorization_service: The authorization service for checking super-admin privileges
        
    Returns:
        GetAllGroupsResponse: All groups information
    """
    await require_admin(current_user, authorization_service)
    
    # Extract department from user data
    department_name = current_user.department_name 
    
    try:
        if current_user.role == UserRole.SUPER_ADMIN:
            result = await group_service.get_all_groups()
        else:
            result = await group_service.get_all_groups(department_name=department_name)
        
        return GetAllGroupsResponse(
            success=result["success"],
            message=result["message"],
            groups=[GroupResponse(**group) for group in result["groups"]],
            total_count=result["total_count"]
        )
            
    except Exception as e:
        log.error(f"Error retrieving all groups: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error retrieving all groups: {str(e)}")


@router.put("/update-group/{group_name}", response_model=GroupUpdateResponse)
async def update_group_endpoint(
    request: Request,
    group_name: str,
    update_request: UpdateGroupRequest,
    current_user: User = Depends(get_current_user),
    group_service: GroupService = Depends(ServiceProvider.get_group_service),
    authorization_service: AuthorizationService = Depends(ServiceProvider.get_authorization_service),
    auth_service: AuthService = Depends(ServiceProvider.get_auth_service),
    agent_service: AgentService = Depends(ServiceProvider.get_agent_service)
):
    """
    Comprehensively updates a group including description, users, and agents.
    Group name cannot be updated. Only super-admins can update groups.
    
    Args:
        request: The FastAPI Request object
        group_name: The name of the group to update (cannot be changed)
        update_request: Request containing group update details
        current_user: The currently authenticated user
        group_service: The group service
        authorization_service: The authorization service for checking super-admin privileges
        
    Returns:
        GroupUpdateResponse: Status of the comprehensive group update operation
    """
    if current_user.role == UserRole.SUPER_ADMIN:
        raise HTTPException(status_code=403, detail="Superadmin is not allowed to update groups.")
    
    await require_admin(current_user, authorization_service)
    
    # Extract department from user data
    department_name = current_user.department_name 
    
    try:
        # Initialize response tracking
        added_users = []
        removed_users = []
        added_agents = []
        removed_agents = []
        description_updated = False
        messages = []
        
        # Validate users and agents exist and belong to the correct department before performing any operations
        if update_request.add_users:
            await validate_users_exist_and_in_department(update_request.add_users, auth_service, department_name)
        if update_request.remove_users:
            await validate_users_exist_and_in_department(update_request.remove_users, auth_service, department_name)
        if update_request.add_agents:
            await validate_agents_exist_and_in_department(update_request.add_agents, agent_service, department_name)
        if update_request.remove_agents:
            await validate_agents_exist_and_in_department(update_request.remove_agents, agent_service, department_name)
        
        # Update description if provided
        if update_request.group_description is not None:
            desc_result = await group_service.update_group(
                group_name=group_name,
                new_group_name=None,  # Group name should not be updated
                group_description=update_request.group_description,
                user_emails=None,
                agent_ids=None,
                department_name=department_name
            )
            if desc_result["success"]:
                description_updated = True
                messages.append(f"Group description updated successfully")
                log.info(f"Super-admin {current_user.email} updated description for group '{group_name}'")
            else:
                raise HTTPException(status_code=400, detail=f"Failed to update description: {desc_result['message']}")
        
        # Add users if provided
        if update_request.add_users:
            add_users_result = await group_service.add_users_to_group(group_name, update_request.add_users, department_name=department_name)
            if add_users_result["success"]:
                added_users = add_users_result.get("added_users", update_request.add_users)
                messages.append(f"Added {len(added_users)} users to group")
                log.info(f"Super-admin {current_user.email} added users to group '{group_name}': {added_users}")
            else:
                raise HTTPException(status_code=400, detail=f"Failed to add users: {add_users_result['message']}")
        
        # Remove users if provided
        if update_request.remove_users:
            remove_users_result = await group_service.remove_users_from_group(group_name, update_request.remove_users, department_name=department_name)
            if remove_users_result["success"]:
                removed_users = remove_users_result.get("removed_users", update_request.remove_users)
                messages.append(f"Removed {len(removed_users)} users from group")
                log.info(f"Super-admin {current_user.email} removed users from group '{group_name}': {removed_users}")
            else:
                raise HTTPException(status_code=400, detail=f"Failed to remove users: {remove_users_result['message']}")
        
        # Add agents if provided
        if update_request.add_agents:
            add_agents_result = await group_service.add_agents_to_group(group_name, update_request.add_agents, department_name=department_name)
            if add_agents_result["success"]:
                added_agents = add_agents_result.get("added_agents", update_request.add_agents)
                messages.append(f"Added {len(added_agents)} agents to group")
                log.info(f"Super-admin {current_user.email} added agents to group '{group_name}': {added_agents}")
            else:
                raise HTTPException(status_code=400, detail=f"Failed to add agents: {add_agents_result['message']}")
        
        # Remove agents if provided
        if update_request.remove_agents:
            remove_agents_result = await group_service.remove_agents_from_group(group_name, update_request.remove_agents, department_name=department_name)
            if remove_agents_result["success"]:
                removed_agents = remove_agents_result.get("removed_agents", update_request.remove_agents)
                messages.append(f"Removed {len(removed_agents)} agents from group")
                log.info(f"Super-admin {current_user.email} removed agents from group '{group_name}': {removed_agents}")
            else:
                raise HTTPException(status_code=400, detail=f"Failed to remove agents: {remove_agents_result['message']}")
        
        # Check if any operations were performed
        if not any([description_updated, added_users, removed_users, added_agents, removed_agents]):
            raise HTTPException(status_code=400, detail="No valid update operations specified")
        
        # Construct final message
        final_message = f"group '{group_name}' updated successfully. " + "; ".join(messages)
        
        log.info(f"Super-admin {current_user.email} completed comprehensive update of group '{group_name}'")
        
        return GroupUpdateResponse(
            success=True,
            message=final_message,
            group_name=group_name,
            added_users=added_users if added_users else None,
            removed_users=removed_users if removed_users else None,
            added_agents=added_agents if added_agents else None,
            removed_agents=removed_agents if removed_agents else None,
            description_updated=description_updated
        )
            
    except HTTPException:
        raise
    except Exception as e:
        log.error(f"Error updating group: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error updating group: {str(e)}")


@router.delete("/delete-group/{group_name}", response_model=GroupOperationResponse)
async def delete_group_endpoint(
    request: Request,
    group_name: str,
    current_user: User = Depends(get_current_user),
    group_service: GroupService = Depends(ServiceProvider.get_group_service),
    authorization_service: AuthorizationService = Depends(ServiceProvider.get_authorization_service)
):
    """
    Deletes a group. Only super-admins can delete groups.
    
    Args:
        request: The FastAPI Request object
        group_name: The name of the group to delete
        current_user: The currently authenticated user
        group_service: The group service
        authorization_service: The authorization service for checking super-admin privileges
        
    Returns:
        GroupOperationResponse: Status of the group deletion operation
    """
    if current_user.role == UserRole.SUPER_ADMIN:
        raise HTTPException(status_code=403, detail="Superadmin is not allowed to delete groups.")
    
    await require_admin(current_user, authorization_service)
    
    # Extract department from user data
    department_name = current_user.department_name 
    
    try:
        result = await group_service.delete_group(group_name, department_name=department_name)
        
        if result["success"]:
            log.info(f"Super-admin {current_user.email} deleted group '{group_name}'")
            return GroupOperationResponse(
                success=True,
                message=result["message"],
                group_name=result["group_name"]
            )
        else:
            raise HTTPException(status_code=400, detail=result["message"])
            
    except HTTPException:
        raise
    except Exception as e:
        log.error(f"Error deleting group: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error deleting group: {str(e)}")

@router.get("/by-user/{user_email}", response_model=GetGroupsByUserResponse)
async def get_groups_by_user_endpoint(
    request: Request,
    user_email: str,
    current_user: User = Depends(get_current_user),
    group_service: GroupService = Depends(ServiceProvider.get_group_service),
    authorization_service: AuthorizationService = Depends(ServiceProvider.get_authorization_service)
):
    """
    Retrieves all groups that contain a specific user.
    
    Args:
        request: The FastAPI Request object
        user_email: The email of the user to search groups for
        current_user: The currently authenticated user
        group_service: The group service
        authorization_service: The authorization service for checking super-admin privileges
        
    Returns:
        GetGroupsByUserResponse: Groups containing the user
    """
    
    # Extract department from user data
    department_name = current_user.department_name 
    
    try:
        result = await group_service.get_groups_by_user(user_email, department_name=department_name)
        
        return GetGroupsByUserResponse(
            success=result["success"],
            message=result["message"],
            user_email=result["user_email"],
            groups=[GroupResponse(**group) for group in result["groups"]],
            total_count=result["total_count"]
        )
            
    except Exception as e:
        log.error(f"Error retrieving groups by user: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error retrieving groups by user: {str(e)}")


@router.get("/by-agent/{agent_id}", response_model=GetGroupsByAgentResponse)
async def get_groups_by_agent_endpoint(
    request: Request,
    agent_id: str,
    current_user: User = Depends(get_current_user),
    group_service: GroupService = Depends(ServiceProvider.get_group_service),
    authorization_service: AuthorizationService = Depends(ServiceProvider.get_authorization_service)
):
    """
    Retrieves all groups that contain a specific agent. Only super-admins can access this.
    
    Args:
        request: The FastAPI Request object
        agent_id: The ID of the agent to search groups for
        current_user: The currently authenticated user
        group_service: The group service
        authorization_service: The authorization service for checking super-admin privileges
        
    Returns:
        GetGroupsByAgentResponse: Groups containing the agent
    """
    await require_admin(current_user, authorization_service)
    
    # Extract department from user data
    department_name = current_user.department_name 
    
    try:
        if current_user.role == UserRole.SUPER_ADMIN:
            result = await group_service.get_groups_by_agent(agent_id)
        else:
            result = await group_service.get_groups_by_agent(agent_id, department_name=department_name)
        
        return GetGroupsByAgentResponse(
            success=result["success"],
            message=result["message"],
            agent_id=result["agent_id"],
            groups=[GroupResponse(**group) for group in result["groups"]],
            total_count=result["total_count"]
        )
            
    except Exception as e:
        log.error(f"Error retrieving groups by agent: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error retrieving groups by agent: {str(e)}")


@router.get("/get/search-paginated/")
async def search_paginated_groups_endpoint(
    request: Request,
    search_value: Optional[str] = Query(None),
    page_number: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1),
    created_by: Optional[str] = Query(None),
    current_user: User = Depends(get_current_user),
    group_service: GroupService = Depends(ServiceProvider.get_group_service),
    authorization_service: AuthorizationService = Depends(ServiceProvider.get_authorization_service)
):
    """
    Searches groups with pagination. Only super-admins can access this.
    
    Args:
        request: The FastAPI Request object
        search_value: Optional group name to search for
        page_number: Page number for pagination (starts from 1)
        page_size: Number of results per page
        created_by: Optional email of the user who created the group
        current_user: The currently authenticated user
        group_service: The group service
        authorization_service: The authorization service for checking super-admin privileges
        
    Returns:
        Dict: Paginated group search results
    """
    await require_admin(current_user, authorization_service)
    
    # Extract department from user data
    department_name = current_user.department_name 
    
    try:
        if current_user.role == UserRole.SUPER_ADMIN:
            result = await group_service.get_groups_by_search_or_page(
                search_value=search_value,
                limit=page_size,
                page=page_number,
                created_by=created_by
            )
        else:
            result = await group_service.get_groups_by_search_or_page(
            search_value=search_value,
            limit=page_size,
            page=page_number,
            created_by=created_by,
            department_name=department_name
            )
        
        if not result["details"]:
            raise HTTPException(status_code=404, detail="No groups found matching criteria.")
            
        return result
        
    except HTTPException:
        raise
    except Exception as e:
        log.error(f"Error in search paginated groups endpoint: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error searching groups: {str(e)}")
