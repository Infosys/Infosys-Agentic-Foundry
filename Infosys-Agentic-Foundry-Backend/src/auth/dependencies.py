from typing import Optional
from fastapi import HTTPException, Request, Depends, status
from src.auth.models import User, UserRole, Permission
from src.auth.auth_service import AuthService
from src.auth.authorization_service import AuthorizationService
from telemetry_wrapper import logger as log
from src.api.dependencies import ServiceProvider

def get_auth_service(request: Request) -> AuthService:
    """Dependency to get AuthService instance"""
    log.info("Retrieving AuthService instance")
    return ServiceProvider.get_auth_service()


def get_authorization_service(request: Request) -> AuthorizationService:
    """Dependency to get AuthorizationService instance"""
    log.info("Retrieving AuthorizationService instance")
    return ServiceProvider.get_authorization_service()


async def get_current_user(request: Request) -> User:
    """Dependency to get current authenticated user using JWT"""
    log.info("Getting auth service inference user from request")
    auth_svc = get_auth_service(request=request)
    log.info("Getting current user from request")
    # Get JWT token from Authorization header
    auth_header = request.headers.get("Authorization")
    if not auth_header or not auth_header.startswith("Bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required"
        )
    token = auth_header.split(" ", 1)[1]
    log.info(f"JWT token: {token}")
    user = await auth_svc.validate_jwt(token)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token"
        )
    return user


async def get_current_user_optional(request: Request) -> Optional[User]:
    """Dependency to get current user (optional - returns None if not authenticated)"""
    try:
        return await get_current_user(request)
    except HTTPException:
        return None


def require_role(required_role: UserRole):
    """Dependency factory to require a specific role"""
    async def role_checker(
        current_user: User = Depends(get_current_user),
        authz_service: AuthorizationService = Depends(get_authorization_service)
    ):
        if not await authz_service.has_role(current_user.id, required_role):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Role {required_role.value} required"
            )
        return current_user
    return role_checker


def require_permission(permission: Permission):
    """Dependency factory to require a specific permission"""
    async def permission_checker(
        current_user: User = Depends(get_current_user),
        authz_service: AuthorizationService = Depends(get_authorization_service)
    ):
        if not await authz_service.has_permission(current_user.id, permission):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Permission {permission.value} required"
            )
        return current_user
    return permission_checker


def require_approval_permission(approval_type: str):
    """Dependency factory to require agent or tool approval permission"""
    async def approval_checker(
        current_user: User = Depends(get_current_user),
        authz_service: AuthorizationService = Depends(get_authorization_service)
    ):
        if approval_type == "agent":
            can_approve = await authz_service.can_approve_agents(current_user.id)
        elif approval_type == "tool":
            can_approve = await authz_service.can_approve_tools(current_user.id)
        else:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid approval type"
            )
        
        if not can_approve:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Permission to approve {approval_type}s required"
            )
        return current_user
    return approval_checker


async def get_user_info_from_request(request: Request) -> Optional[User]:
    """Helper to extract user info from request for middleware"""
    try:
        auth_header = request.headers.get("Authorization")
        log.info("JWT is checking")
        auth_service = get_auth_service(request)
        log.info(f"Authorization header: {auth_header}")
        if not auth_header or not auth_header.startswith("Bearer "):
            return None
        token = auth_header.split(" ", 1)[1]
        if not auth_service:
            return None
        
        user = await auth_service.validate_jwt(token)
        log.info("user is validated")
        return user
    except Exception as e:
        log.error(f"Error getting user info from request: {e}")
        return None


def get_client_ip(request: Request) -> str:
    """Helper to get client IP address"""
    # Check for forwarded headers first
    forwarded_for = request.headers.get("X-Forwarded-For")
    if forwarded_for:
        return forwarded_for.split(",")[0].strip()
    
    real_ip = request.headers.get("X-Real-IP")
    if real_ip:
        return real_ip
    
    # Fall back to direct connection
    if hasattr(request, "client") and request.client:
        return request.client.host
    
    return "unknown"


def get_user_agent(request: Request) -> str:
    """Helper to get user agent"""
    return request.headers.get("User-Agent", "unknown")


async def require_active_user(
    current_user: User = Depends(get_current_user),
    authz_service: AuthorizationService = Depends(get_authorization_service)
):
    """Dependency to require user to be active"""
    if not await authz_service.is_user_active(current_user.id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User account is not active"
        )
    return current_user
