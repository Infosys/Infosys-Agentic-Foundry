from fastapi import APIRouter, Depends, Request, Response, HTTPException, status
from src.auth.models import (
    User, LoginRequest, LoginResponse, RegisterRequest, RegisterResponse,
    UpdatePasswordRequest, GrantApprovalPermissionRequest, ApprovalPermissionResponse,
    RevokeApprovalPermissionRequest, UserRole, Permission
)
from src.auth.auth_service import AuthService
from src.auth.authorization_service import AuthorizationService
from src.auth.dependencies import (
    get_auth_service, get_authorization_service, get_current_user,
    require_role, require_permission, get_client_ip, get_user_agent
)
from telemetry_wrapper import logger as log


router = APIRouter(tags=["Authentication"], prefix="/auth")


@router.post("/login", response_model=LoginResponse)
async def login(
    request: Request,
    login_data: LoginRequest,
    auth_service: AuthService = Depends(get_auth_service)
):
    """Login endpoint"""
    ip_address = get_client_ip(request)
    user_agent = get_user_agent(request)
    log.info("Login attempt with data: %s")
    login_response = await auth_service.login(login_data, ip_address, user_agent)
    log.info("login attempeted")
    log.info("compelted login")
    return login_response


@router.post("/logout")
async def logout(
    request: Request,
    current_user: User = Depends(get_current_user),
    auth_service: AuthService = Depends(get_auth_service)
):
    """Logout endpoint"""
    auth_header = request.headers.get("Authorization")
    token = auth_header.split(" ", 1)[1]
    ip_address = get_client_ip(request)
    user_agent = get_user_agent(request)
    await auth_service.logout(token, ip_address, user_agent)
    return {"message": "Logged out successfully"}


@router.post("/register", response_model=RegisterResponse)
async def register(
    request: Request,
    register_data: RegisterRequest,
    auth_service: AuthService = Depends(get_auth_service)
):
    """Register endpoint"""
    ip_address = get_client_ip(request)
    user_agent = get_user_agent(request)
    
    return await auth_service.register(register_data, ip_address, user_agent)


@router.get("/guest-login", response_model=LoginResponse)
async def guest_login(
    request: Request,
    auth_service: AuthService = Depends(get_auth_service)
):
    """Guest login endpoint that returns JWT."""
    ip_address = get_client_ip(request)
    user_agent = get_user_agent(request)
    login_response = await auth_service.guest_login(ip_address, user_agent)
    log.info("Guest login attempted with response: %s", login_response)
    return login_response


@router.post("/update-password")
async def update_password(
    request: Request,
    password_data: UpdatePasswordRequest,
    current_user: User = Depends(require_role(UserRole.ADMIN)),
    auth_service: AuthService = Depends(get_auth_service)
):
    """Update user password (Admin only)"""
    ip_address = get_client_ip(request)
    user_agent = get_user_agent(request)
    
    success = False
    message = "No changes made"
    
    if password_data.new_password:
        success = await auth_service.update_password(
            email=password_data.email_id,
            new_password=password_data.new_password,
            current_user_id=current_user.id,
            ip_address=ip_address,
            user_agent=user_agent
        )
        message = "Password updated successfully" if success else "Failed to update password"
    
    if password_data.role:
        role_success = await auth_service.update_role(
            email=password_data.email_id,
            new_role=password_data.role,
            current_user_id=current_user.id,
            ip_address=ip_address,
            user_agent=user_agent
        )
        if password_data.new_password:
            message = f"Password and role updated successfully" if (success and role_success) else "Partial update failed"
        else:
            success = role_success
            message = "Role updated successfully" if success else "Failed to update role"
    
    return {"approval": success, "message": message}


@router.get("/me")
async def get_current_user_info(request: Request):
    """Get current user information"""
    current_user = await get_current_user(request)
    return {
        "user_id": current_user.id,
        "email": current_user.email,
        "username": current_user.username,
        "role": current_user.role,
        "status": current_user.status
    }


@router.get("/permissions")
async def get_user_permissions(
    current_user: User = Depends(get_current_user),
    authz_service: AuthorizationService = Depends(get_authorization_service)
):
    """Get current user's permissions"""
    permissions = await authz_service.get_user_permissions(current_user.id)
    return {
        "user_id": current_user.id,
        "email": current_user.email,
        "role": current_user.role,
        "permissions": [p.value for p in permissions]
    }


@router.post("/grant-approval-permission", response_model=ApprovalPermissionResponse)
async def grant_approval_permission(
    request: Request,
    permission_request: GrantApprovalPermissionRequest,
    current_user: User = Depends(require_role(UserRole.SUPER_ADMIN)),
    authz_service: AuthorizationService = Depends(get_authorization_service)
):
    """Grant approval permission to an admin (SuperAdmin only)"""
    ip_address = get_client_ip(request)
    user_agent = get_user_agent(request)
    
    return await authz_service.grant_approval_permission(
        request=permission_request,
        granted_by_user_id=current_user.id,
        ip_address=ip_address,
        user_agent=user_agent
    )


@router.post("/revoke-approval-permission", response_model=ApprovalPermissionResponse)
async def revoke_approval_permission(
    request: Request,
    revoke_request: RevokeApprovalPermissionRequest,
    current_user: User = Depends(require_role(UserRole.SUPER_ADMIN)),
    authz_service: AuthorizationService = Depends(get_authorization_service)
):
    """Revoke approval permission from an admin (SuperAdmin only)"""
    ip_address = get_client_ip(request)
    user_agent = get_user_agent(request)
    
    return await authz_service.revoke_approval_permission(
        admin_user_id=revoke_request.admin_user_id,
        permission_type=revoke_request.permission_type,
        revoked_by_user_id=current_user.id,
        ip_address=ip_address,
        user_agent=user_agent
    )


@router.get("/approval-permissions")
async def get_all_approval_permissions(
    current_user: User = Depends(require_role(UserRole.SUPER_ADMIN)),
    authz_service: AuthorizationService = Depends(get_authorization_service)
):
    """Get all approval permissions (SuperAdmin only)"""
    permissions = await authz_service.get_all_approval_permissions()
    return {"approval_permissions": permissions}


@router.get("/approval-permissions/{admin_user_id}")
async def get_admin_approval_permissions(
    admin_user_id: str,
    current_user: User = Depends(require_role(UserRole.SUPER_ADMIN)),
    authz_service: AuthorizationService = Depends(get_authorization_service)
):
    """Get approval permissions for a specific admin (SuperAdmin only)"""
    permissions = await authz_service.get_admin_approval_permissions(admin_user_id)
    return {"admin_user_id": admin_user_id, "approval_permissions": permissions}
