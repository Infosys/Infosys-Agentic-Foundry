# © 2024-25 Infosys Limited, Bangalore, India. All Rights Reserved.
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Request, Query

from src.schemas import (
    GrantAgentAccessRequest, RevokeAgentAccessRequest, AgentAccessOperationResponse,
    UserAgentAccessResponse, AllUserAgentAccessResponse, GetUserAgentAccessResponse,
    GetUserToolIdsRequest, GetUserToolIdsResponse
)
from src.database.services import UserAgentAccessService, AgentService
from src.auth.auth_service import AuthService
from src.api.dependencies import ServiceProvider
from src.auth.dependencies import get_current_user
from src.auth.models import User, UserRole
from src.auth.authorization_service import AuthorizationService
from telemetry_wrapper import logger as log

# Create an APIRouter instance for user agent access related endpoints
router = APIRouter(prefix="/user-agent-access", tags=["User Agent Access"])


async def require_super_admin(
    current_user: User,
    authorization_service: AuthorizationService
):
    """
    Helper function to check if the current user is a super-admin.
    For now, we'll treat ADMIN role as super-admin. This can be extended later
    with a separate SUPER_ADMIN role if needed.
    """
    is_admin = await authorization_service.has_role(user_email=current_user.email, required_role=UserRole.ADMIN)
    if not is_admin:
        log.warning(f"User {current_user.email} attempted to access super-admin endpoint without privileges")
        raise HTTPException(
            status_code=403, 
            detail="Super-admin privileges required for user agent access management operations"
        )


async def validate_user_exists(user_email: str, auth_service) -> str:
    """
    Validate that a user email exists in the database.
    
    Args:
        user_email: User email to validate
        auth_service: AuthService instance for user validation
        
    Returns:
        Validated user email
        
    Raises:
        HTTPException: If user email is not found
    """
    user = await auth_service.user_repo.get_user_by_email(user_email)
    if not user:
        raise HTTPException(
            status_code=400, 
            detail=f"User email '{user_email}' does not exist"
        )
    return user_email


async def validate_agent_exists(agent_id: str, agent_service) -> str:
    """
    Validate that an agent ID exists in the database.
    
    Args:
        agent_id: Agent ID to validate
        agent_service: AgentService instance for agent validation
        
    Returns:
        Validated agent ID
        
    Raises:
        HTTPException: If agent ID is not found
    """
    # Use get_agent method with agentic_application_id parameter
    agents = await agent_service.get_agent(agentic_application_id=agent_id)
    if not agents or len(agents) == 0:
        raise HTTPException(
            status_code=400, 
            detail=f"Agent ID '{agent_id}' does not exist"
        )
    return agent_id


@router.post("/grant", response_model=AgentAccessOperationResponse)
async def grant_agent_access_endpoint(
    request: Request,
    grant_request: GrantAgentAccessRequest,
    current_user: User = Depends(get_current_user),
    user_agent_access_service: UserAgentAccessService = Depends(ServiceProvider.get_user_agent_access_service),
    authorization_service: AuthorizationService = Depends(ServiceProvider.get_authorization_service),
    auth_service: AuthService = Depends(ServiceProvider.get_auth_service),
    agent_service: AgentService = Depends(ServiceProvider.get_agent_service)
):
    """
    Grants access to an agent for a user. Only admins can grant access.
    
    Args:
        request: The FastAPI Request object
        grant_request: Request containing user_email and agent_id
        current_user: The currently authenticated user
        user_agent_access_service: The user agent access service
        authorization_service: The authorization service for checking admin privileges
        
    Returns:
        AgentAccessOperationResponse: Status of the grant operation
    """
    user_session = request.cookies.get("user_session")
    
    # Check if the current user is an admin
    is_admin = await authorization_service.has_role(user_email=current_user.email, required_role=UserRole.ADMIN)
    if not is_admin:
        log.warning(f"User {current_user.email} attempted to grant agent access without admin privileges")
        raise HTTPException(
            status_code=403, 
            detail="Admin privileges required to grant agent access to users"
        )
    
    try:
        # Validate that user and agent exist before granting access
        validated_user_email = await validate_user_exists(grant_request.user_email, auth_service)
        validated_agent_id = await validate_agent_exists(grant_request.agent_id, agent_service)
        
        result = await user_agent_access_service.grant_agent_access(
            user_email=validated_user_email,
            agent_id=validated_agent_id,
            given_access_by=current_user.email
        )
        
        if result["success"]:
            log.info(f"Admin {current_user.email} granted access to agent {grant_request.agent_id} for user {grant_request.user_email}")
            return AgentAccessOperationResponse(
                success=True,
                message=result["message"],
                user_email=grant_request.user_email,
                agent_id=grant_request.agent_id,
                granted_by=current_user.email
            )
        else:
            log.error(f"Failed to grant agent access: {result['message']}")
            raise HTTPException(status_code=400, detail=result["message"])
            
    except Exception as e:
        log.error(f"Error granting agent access: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error granting agent access: {str(e)}")


@router.post("/revoke", response_model=AgentAccessOperationResponse)
async def revoke_agent_access_endpoint(
    request: Request,
    revoke_request: RevokeAgentAccessRequest,
    current_user: User = Depends(get_current_user),
    user_agent_access_service: UserAgentAccessService = Depends(ServiceProvider.get_user_agent_access_service),
    authorization_service: AuthorizationService = Depends(ServiceProvider.get_authorization_service),
    auth_service: AuthService = Depends(ServiceProvider.get_auth_service),
    agent_service: AgentService = Depends(ServiceProvider.get_agent_service)
):
    """
    Revokes access to an agent for a user. Only admins can revoke access.
    
    Args:
        request: The FastAPI Request object
        revoke_request: Request containing user_email and agent_id
        current_user: The currently authenticated user
        user_agent_access_service: The user agent access service
        authorization_service: The authorization service for checking admin privileges
        
    Returns:
        AgentAccessOperationResponse: Status of the revoke operation
    """
    user_session = request.cookies.get("user_session")
    
    # Check if the current user is an admin
    is_admin = await authorization_service.has_role(user_email=current_user.email, required_role=UserRole.ADMIN)
    if not is_admin:
        log.warning(f"User {current_user.email} attempted to revoke agent access without admin privileges")
        raise HTTPException(
            status_code=403, 
            detail="Admin privileges required to revoke agent access from users"
        )
    
    try:
        # Validate that user and agent exist before revoking access
        validated_user_email = await validate_user_exists(revoke_request.user_email, auth_service)
        validated_agent_id = await validate_agent_exists(revoke_request.agent_id, agent_service)
        
        result = await user_agent_access_service.revoke_agent_access(
            user_email=validated_user_email,
            agent_id=validated_agent_id
        )
        
        if result["success"]:
            log.info(f"Admin {current_user.email} revoked access to agent {revoke_request.agent_id} for user {revoke_request.user_email}")
            return AgentAccessOperationResponse(
                success=True,
                message=result["message"],
                user_email=revoke_request.user_email,
                agent_id=revoke_request.agent_id
            )
        else:
            log.error(f"Failed to revoke agent access: {result['message']}")
            raise HTTPException(status_code=400, detail=result["message"])
            
    except Exception as e:
        log.error(f"Error revoking agent access: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error revoking agent access: {str(e)}")


@router.get("/user/{user_email}", response_model=GetUserAgentAccessResponse)
async def get_user_agent_access_endpoint(
    request: Request,
    user_email: str,
    current_user: User = Depends(get_current_user),
    user_agent_access_service: UserAgentAccessService = Depends(ServiceProvider.get_user_agent_access_service),
    authorization_service: AuthorizationService = Depends(ServiceProvider.get_authorization_service),
    auth_service: AuthService = Depends(ServiceProvider.get_auth_service)
):
    """
    Retrieves agent access information for a specific user. 
    Only admins can view other users' access, users can view their own.
    
    Args:
        request: The FastAPI Request object
        user_email: The email of the user to get access information for
        current_user: The currently authenticated user
        user_agent_access_service: The user agent access service
        authorization_service: The authorization service for checking admin privileges
        
    Returns:
        GetUserAgentAccessResponse: User's agent access information
    """
    user_session = request.cookies.get("user_session")
    
    # Users can view their own access, only admins can view others
    if current_user.email != user_email:
        is_admin = await authorization_service.has_role(user_email=current_user.email, required_role=UserRole.ADMIN)
        if not is_admin:
            log.warning(f"User {current_user.email} attempted to view agent access for other user without admin privileges")
            raise HTTPException(
                status_code=403, 
                detail="Admin privileges required to view other users' agent access"
            )
    
    try:
        # Validate that user exists before getting access info
        validated_user_email = await validate_user_exists(user_email, auth_service)
        access_info = await user_agent_access_service.get_user_agent_access(validated_user_email)
        
        if access_info:
            return GetUserAgentAccessResponse(
                user_email=user_email,
                agent_ids=access_info.get("agent_ids", []),
                has_access=True
            )
        else:
            return GetUserAgentAccessResponse(
                user_email=user_email,
                agent_ids=[],
                has_access=False
            )
            
    except Exception as e:
        log.error(f"Error retrieving user agent access: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error retrieving user agent access: {str(e)}")


@router.get("/all", response_model=AllUserAgentAccessResponse)
async def get_all_user_agent_access_endpoint(
    request: Request,
    current_user: User = Depends(get_current_user),
    user_agent_access_service: UserAgentAccessService = Depends(ServiceProvider.get_user_agent_access_service),
    authorization_service: AuthorizationService = Depends(ServiceProvider.get_authorization_service)
):
    """
    Retrieves all user agent access records. Only admins can access this endpoint.
    
    Args:
        request: The FastAPI Request object
        current_user: The currently authenticated user
        user_agent_access_service: The user agent access service
        authorization_service: The authorization service for checking admin privileges
        
    Returns:
        AllUserAgentAccessResponse: All user agent access records
    """
    user_session = request.cookies.get("user_session")
    
    # Check if the current user is an admin
    is_admin = await authorization_service.has_role(user_email=current_user.email, required_role=UserRole.ADMIN)
    if not is_admin:
        log.warning(f"User {current_user.email} attempted to view all user agent access without admin privileges")
        raise HTTPException(
            status_code=403, 
            detail="Admin privileges required to view all user agent access records"
        )
    
    try:
        all_access = await user_agent_access_service.get_all_user_agent_access()
        
        return AllUserAgentAccessResponse(
            total_records=len(all_access),
            access_records=[
                UserAgentAccessResponse(
                    user_email=record["user_email"],
                    agent_ids=record["agent_ids"],
                    given_access_by=record["given_access_by"]
                ) for record in all_access
            ]
        )
            
    except Exception as e:
        log.error(f"Error retrieving all user agent access: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error retrieving all user agent access: {str(e)}")


@router.get("/check/{user_email}/{agent_id}")
async def check_user_agent_access_endpoint(
    request: Request,
    user_email: str,
    agent_id: str,
    current_user: User = Depends(get_current_user),
    user_agent_access_service: UserAgentAccessService = Depends(ServiceProvider.get_user_agent_access_service),
    authorization_service: AuthorizationService = Depends(ServiceProvider.get_authorization_service),
    auth_service: AuthService = Depends(ServiceProvider.get_auth_service),
    agent_service: AgentService = Depends(ServiceProvider.get_agent_service)
):
    """
    Checks if a user has access to a specific agent.
    Only admins can check for other users, users can check their own access.
    
    Args:
        request: The FastAPI Request object
        user_email: The email of the user to check
        agent_id: The ID of the agent to check access for
        current_user: The currently authenticated user
        user_agent_access_service: The user agent access service
        authorization_service: The authorization service for checking admin privileges
        
    Returns:
        dict: Whether the user has access to the agent
    """
    user_session = request.cookies.get("user_session")
    
    # Users can check their own access, only admins can check for others
    if current_user.email != user_email:
        is_admin = await authorization_service.has_role(user_email=current_user.email, required_role=UserRole.ADMIN)
        if not is_admin:
            log.warning(f"User {current_user.email} attempted to check agent access for other user without admin privileges")
            raise HTTPException(
                status_code=403, 
                detail="Admin privileges required to check other users' agent access"
            )
    
    try:
        # Validate that user and agent exist before checking access
        validated_user_email = await validate_user_exists(user_email, auth_service)
        validated_agent_id = await validate_agent_exists(agent_id, agent_service)
        
        has_access = await user_agent_access_service.check_user_agent_access(validated_user_email, validated_agent_id)
        
        return {
            "user_email": user_email,
            "agent_id": agent_id,
            "has_access": has_access
        }
            
    except Exception as e:
        log.error(f"Error checking user agent access: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error checking user agent access: {str(e)}")


@router.get("/agent/{agent_id}/users")
async def get_users_with_agent_access_endpoint(
    request: Request,
    agent_id: str,
    current_user: User = Depends(get_current_user),
    user_agent_access_service: UserAgentAccessService = Depends(ServiceProvider.get_user_agent_access_service),
    authorization_service: AuthorizationService = Depends(ServiceProvider.get_authorization_service),
    agent_service: AgentService = Depends(ServiceProvider.get_agent_service)
):
    """
    Retrieves all users who have access to a specific agent. Only admins can access this endpoint.
    
    Args:
        request: The FastAPI Request object
        agent_id: The ID of the agent
        current_user: The currently authenticated user
        user_agent_access_service: The user agent access service
        authorization_service: The authorization service for checking admin privileges
        
    Returns:
        dict: List of user emails who have access to the agent
    """
    user_session = request.cookies.get("user_session")
    
    # Check if the current user is an admin
    is_admin = await authorization_service.has_role(user_email=current_user.email, required_role=UserRole.ADMIN)
    if not is_admin:
        log.warning(f"User {current_user.email} attempted to view users with agent access without admin privileges")
        raise HTTPException(
            status_code=403, 
            detail="Admin privileges required to view users with agent access"
        )
    
    try:
        # Validate that agent exists before getting users with access
        validated_agent_id = await validate_agent_exists(agent_id, agent_service)
        users_with_access = await user_agent_access_service.get_users_with_agent_access(validated_agent_id)
        
        return {
            "agent_id": agent_id,
            "users_with_access": users_with_access,
            "total_users": len(users_with_access)
        }
            
    except Exception as e:
        log.error(f"Error retrieving users with agent access: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error retrieving users with agent access: {str(e)}")


@router.post("/user-tools", response_model=GetUserToolIdsResponse)
async def get_user_tool_ids_endpoint(
    request: Request,
    tool_request: GetUserToolIdsRequest,
    current_user: User = Depends(get_current_user),
    user_agent_access_service: UserAgentAccessService = Depends(ServiceProvider.get_user_agent_access_service),
    authorization_service: AuthorizationService = Depends(ServiceProvider.get_authorization_service),
    auth_service: AuthService = Depends(ServiceProvider.get_auth_service)
):
    """
    Retrieves all tool IDs for agents that a user has access to.
    Users can get their own tools, admins can get tools for any user.
    
    Args:
        request: The FastAPI Request object
        tool_request: Request containing user email
        current_user: The currently authenticated user
        user_agent_access_service: The user agent access service
        authorization_service: The authorization service for checking admin privileges
        
    Returns:
        GetUserToolIdsResponse: Tool IDs and access information
    """
    user_session = request.cookies.get("user_session")
    
    # Users can get their own tools, admins can get tools for any user
    if current_user.email != tool_request.user_email:
        is_admin = await authorization_service.has_role(user_email=current_user.email, required_role=UserRole.ADMIN)
        if not is_admin:
            log.warning(f"User {current_user.email} attempted to get tools for other user without admin privileges")
            raise HTTPException(
                status_code=403, 
                detail="Admin privileges required to get tools for other users"
            )
    
    try:
        # Validate that user exists before getting tool IDs
        validated_user_email = await validate_user_exists(tool_request.user_email, auth_service)
        result = await user_agent_access_service.get_all_tool_ids_for_user(
            user_email=validated_user_email
        )
        
        return GetUserToolIdsResponse(
            user_email=result["user_email"],
            accessible_agent_ids=result["accessible_agent_ids"],
            tool_ids=result["tool_ids"],
            total_agents=result["total_agents"],
            total_tools=result["total_tools"]
        )
            
    except Exception as e:
        log.error(f"Error retrieving tool IDs for user: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error retrieving tool IDs for user: {str(e)}")


@router.get("/get/search-paginated/")
async def search_paginated_user_agent_access_endpoint(
    request: Request,
    search_value: Optional[str] = Query(None),
    page_number: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1),
    created_by: Optional[str] = Query(None),
    current_user: User = Depends(get_current_user),
    user_agent_access_service: UserAgentAccessService = Depends(ServiceProvider.get_user_agent_access_service),
    authorization_service: AuthorizationService = Depends(ServiceProvider.get_authorization_service)
):
    """
    Searches user agent access records with pagination. Only super-admins can access this.
    
    Args:
        request: The FastAPI Request object
        search_value: Optional search term to filter records by user_email or given_access_by
        page_number: Page number for pagination (starts from 1)
        page_size: Number of results per page
        created_by: Optional filter by who granted the access
        current_user: The currently authenticated user
        user_agent_access_service: The user agent access service
        authorization_service: The authorization service for checking super-admin privileges
        
    Returns:
        Dict: Paginated user agent access search results
    """
    await require_super_admin(current_user, authorization_service)
    
    try:
        result = await user_agent_access_service.get_user_agent_access_by_search_or_page(
            search_value=search_value,
            limit=page_size,
            page=page_number,
            created_by=created_by
        )
        
        if not result["details"]:
            raise HTTPException(status_code=404, detail="No user agent access records found matching criteria.")
            
        return result
        
    except HTTPException:
        raise
    except Exception as e:
        log.error(f"Error in search paginated user agent access endpoint: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error searching user agent access records: {str(e)}")