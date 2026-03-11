from fastapi import APIRouter, Depends, HTTPException, Request
from typing import List
from src.auth.models import (
    SetRolePermissionsRequest, UpdateRolePermissionsRequest, GetRolePermissionsRequest,
    RoleListResponse, RolePermissionsResponse, AllRolePermissionsResponse, User
)
from src.database.services import RoleAccessService
from src.auth.dependencies import get_current_user
from src.api.dependencies import ServiceProvider
from telemetry_wrapper import logger as log

router = APIRouter(prefix="/roles", tags=["Role Access Management"])

def get_role_access_service(request: Request) -> RoleAccessService:
    """Dependency to get RoleAccessService instance"""
    return ServiceProvider.get_role_access_service()

def check_admin_permissions(user: User) -> None:
    """Check if user has admin or super admin permissions"""
    if user.role not in ['Admin', 'SuperAdmin']:
        raise HTTPException(
            status_code=403, 
            detail="Access denied. Only Admin and SuperAdmin can access role management endpoints."
        )

def check_department_admin_permissions(user: User, target_department: str) -> None:
    """Check if user has permissions to manage the specified department"""
    # SuperAdmin can manage any department
    if user.role == 'SuperAdmin':
        return
    
    # Admin can only manage their own department
    if user.role == 'Admin':
        user_department = getattr(user, 'department_name', None) 
        if user_department != target_department:
            raise HTTPException(
                status_code=403,
                detail=f"Access denied. Admin users can only manage permissions for their own department ('{user_department}'). Cannot manage department '{target_department}'."
            )
        return
    
    # Other roles cannot manage departments
    raise HTTPException(
        status_code=403,
        detail="Access denied. Only Admin and SuperAdmin can manage role permissions."
    )

def check_admin_role_permissions(user: User, target_role_name: str) -> None:
    """Check if user has permissions to modify permissions for the specified role"""
    # SuperAdmin can modify permissions for any role including Admins
    if user.role == 'SuperAdmin':
        return
    
    # Admin users cannot modify permissions for Admin roles (including themselves and other Admins)
    if user.role == 'Admin' and target_role_name == 'Admin':
        raise HTTPException(
            status_code=403,
            detail="Access denied. Only SuperAdmin can set permissions for Admin roles. Admin users cannot modify permissions for Admin roles."
        )
    
    # Admin users can modify permissions for non-Admin roles in their own department
    return

def validate_read_access_prerequisite(permissions_request) -> None:
    """
    Validate that read access is enabled before granting other permissions.
    Read access is a prerequisite for add, update, delete, and execute permissions.
    """
    # Get the read access from the request
    read_access = getattr(permissions_request, 'read_access', None)
    
    # If read_access is None (for patch operations), we'll skip validation here
    # as the service layer will handle current permissions
    if read_access is None:
        return
    
    # Check if read access is disabled for both tools and agents
    read_tools_disabled = not read_access.tools
    read_agents_disabled = not read_access.agents
    
    # Define the permissions that require read access as prerequisite
    permission_fields = ['add_access', 'update_access', 'delete_access', 'execute_access']
    
    for field_name in permission_fields:
        permission = getattr(permissions_request, field_name, None)
        if permission is not None:
            # Check if any permission is being granted without corresponding read access
            if permission.tools and read_tools_disabled:
                raise HTTPException(
                    status_code=400,
                    detail=f"Cannot grant {field_name}.tools permission without read_access.tools enabled"
                )
            if permission.agents and read_agents_disabled:
                raise HTTPException(
                    status_code=400,
                    detail=f"Cannot grant {field_name}.agents permission without read_access.agents enabled"
                )

async def validate_read_access_for_patch(
    permissions_request: UpdateRolePermissionsRequest, 
    role_service: RoleAccessService
) -> None:
    """
    Validate read access prerequisite for patch operations.
    For patch operations, we need to check current read permissions if read_access is not being updated.
    """
    # Get current permissions for the role in the specific department
    current_permissions_response = await role_service.get_role_permissions(permissions_request.department_name, permissions_request.role_name)
    if not current_permissions_response.success or not current_permissions_response.permissions:
        raise HTTPException(
            status_code=404,
            detail=f"Cannot retrieve current permissions for role '{permissions_request.role_name}'"
        )
    
    current_permissions = current_permissions_response.permissions
    
    # Determine effective read access (either from request or current permissions)
    if permissions_request.read_access is not None:
        # Read access is being updated, use the new values
        effective_read_tools = permissions_request.read_access.tools
        effective_read_agents = permissions_request.read_access.agents
    else:
        # Read access not being updated, use current values
        effective_read_tools = current_permissions.read_access.tools
        effective_read_agents = current_permissions.read_access.agents
    
    # Define the permissions that require read access as prerequisite
    permission_fields = ['add_access', 'update_access', 'delete_access', 'execute_access']
    
    for field_name in permission_fields:
        permission = getattr(permissions_request, field_name, None)
        if permission is not None:
            # Check if any permission is being granted without corresponding read access
            if permission.tools and not effective_read_tools:
                raise HTTPException(
                    status_code=400,
                    detail=f"Cannot grant {field_name}.tools permission without read_access.tools enabled. Enable read_access.tools first."
                )
            if permission.agents and not effective_read_agents:
                raise HTTPException(
                    status_code=400,
                    detail=f"Cannot grant {field_name}.agents permission without read_access.agents enabled. Enable read_access.agents first."
                )

def validate_special_access_permissions(permissions_request) -> None:
    """
    Validate special access permissions prerequisites:
    1. execution_steps_access, tool_verifier_flag_access, plan_verifier_flag_access, 
       and online_evaluation_flag_access require execute access for agents
    2. vault_access requires add or update access for tools
    """
    execute_access = getattr(permissions_request, 'execute_access', None)
    add_access = getattr(permissions_request, 'add_access', None)
    update_access = getattr(permissions_request, 'update_access', None)
    
    # Check if execute access for agents is disabled
    execute_agents_disabled = execute_access is None or not execute_access.agents
    
    # # Check if add/update access for tools is disabled
    # add_tools_disabled = add_access is None or not add_access.tools
    # update_tools_disabled = update_access is None or not update_access.tools
    # vault_tools_access_disabled = add_tools_disabled and update_tools_disabled
    
    # Special access permissions that require execute access for agents
    agent_execute_dependent_permissions = [
        ('execution_steps_access', 'execution_steps_access'),
        ('tool_verifier_flag_access', 'tool_verifier_flag_access'),
        ('plan_verifier_flag_access', 'plan_verifier_flag_access'),
        ('online_evaluation_flag_access', 'online_evaluation_flag_access'),
        ('validator_access', 'validator_access'),
        ('file_context_access', 'file_context_access'),
        ('canvas_view_access', 'canvas_view_access'),
        ('context_access', 'context_access')
    ]
    
    # Check agent execute dependent permissions
    for field_name, display_name in agent_execute_dependent_permissions:
        permission_value = getattr(permissions_request, field_name, None)
        if permission_value is True and execute_agents_disabled:
            raise HTTPException(
                status_code=400,
                detail=f"Cannot grant {display_name} without execute_access.agents enabled. Enable execute_access.agents first."
            )
    
    # # Check vault access prerequisite
    # vault_access = getattr(permissions_request, 'vault_access', None)
    # if vault_access is True and vault_tools_access_disabled:
    #     raise HTTPException(
    #         status_code=400,
    #         detail="Cannot grant vault_access without add_access.tools or update_access.tools enabled. Enable at least one of these permissions first."
    #     )

async def validate_special_access_for_patch(
    permissions_request: UpdateRolePermissionsRequest,
    role_service: RoleAccessService
) -> None:
    """
    Validate special access permissions prerequisites for patch operations.
    For patch operations, we need to check current permissions if required fields are not being updated.
    """
    # Get current permissions for the role in the specific department
    current_permissions_response = await role_service.get_role_permissions(permissions_request.department_name, permissions_request.role_name)
    if not current_permissions_response.success or not current_permissions_response.permissions:
        raise HTTPException(
            status_code=404,
            detail=f"Cannot retrieve current permissions for role '{permissions_request.role_name}'"
        )
    
    current_permissions = current_permissions_response.permissions
    
    # Determine effective execute access (either from request or current permissions)
    if permissions_request.execute_access is not None:
        effective_execute_agents = permissions_request.execute_access.agents
    else:
        effective_execute_agents = current_permissions.execute_access.agents
    
    # # Determine effective add/update access for tools (either from request or current permissions)
    # if permissions_request.add_access is not None:
    #     effective_add_tools = permissions_request.add_access.tools
    # else:
    #     effective_add_tools = current_permissions.add_access.tools
        
    # if permissions_request.update_access is not None:
    #     effective_update_tools = permissions_request.update_access.tools
    # else:
    #     effective_update_tools = current_permissions.update_access.tools
    
    # Check special access permissions that require execute access for agents
    agent_execute_dependent_permissions = [
        ('execution_steps_access', 'execution_steps_access'),
        ('tool_verifier_flag_access', 'tool_verifier_flag_access'),
        ('plan_verifier_flag_access', 'plan_verifier_flag_access'),
        ('online_evaluation_flag_access', 'online_evaluation_flag_access'),
        ('validator_access', 'validator_access'),
        ('file_context_access', 'file_context_access'),
        ('canvas_view_access', 'canvas_view_access'),
        ('context_access', 'context_access')
    ]
    
    for field_name, display_name in agent_execute_dependent_permissions:
        permission_value = getattr(permissions_request, field_name, None)
        if permission_value is True and not effective_execute_agents:
            raise HTTPException(
                status_code=400,
                detail=f"Cannot grant {display_name} without execute_access.agents enabled. Enable execute_access.agents first."
            )
    
    # # Check vault access prerequisite
    # vault_access = getattr(permissions_request, 'vault_access', None)
    # if vault_access is True and not (effective_add_tools or effective_update_tools):
    #     raise HTTPException(
    #         status_code=400,
    #         detail="Cannot grant vault_access without add_access.tools or update_access.tools enabled. Enable at least one of these permissions first."
    #     )



@router.get("/list", response_model=RoleListResponse)
async def list_roles(
    user_data: User = Depends(get_current_user),
    role_service: RoleAccessService = Depends(get_role_access_service)
):
    """Get all roles from all departments - only Admins and SuperAdmins can view roles"""
    try:
        
        result = await role_service.get_all_roles()
        return result
    
    except HTTPException:
        raise
    except Exception as e:
        log.error(f"List roles endpoint error: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")



@router.post("/permissions/set", response_model=RolePermissionsResponse)
async def set_role_permissions(
    request: Request,
    permissions_request: SetRolePermissionsRequest,
    user_data: User = Depends(get_current_user),
    role_service: RoleAccessService = Depends(get_role_access_service)
):
    """Set permissions for a role in a specific department - only SuperAdmins can set permissions for Admin roles"""
    try:
        # Check department-specific admin permissions
        check_department_admin_permissions(user_data, permissions_request.department_name)
        
        # Check if user can modify permissions for this specific role
        check_admin_role_permissions(user_data, permissions_request.role_name)
        
        # Validate read access prerequisite for other permissions
        validate_read_access_prerequisite(permissions_request)
        
        # Validate special access permissions prerequisites
        validate_special_access_permissions(permissions_request)
        
        # Get client info for audit
        ip_address = request.client.host if request.client else None
        user_agent = request.headers.get("user-agent", "")
        
        result = await role_service.set_role_permissions(
            request=permissions_request,
            set_by=user_data.email,
            ip_address=ip_address,
            user_agent=user_agent,
            department_name=user_data.department_name
        )
        
        return result
    
    except HTTPException:
        raise
    except Exception as e:
        log.error(f"Set role permissions endpoint error: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")

@router.patch("/permissions/update", response_model=RolePermissionsResponse)
async def patch_role_permissions(
    request: Request,
    permissions_request: UpdateRolePermissionsRequest,
    user_data: User = Depends(get_current_user),
    role_service: RoleAccessService = Depends(get_role_access_service)
):
    """Partially update permissions for an existing role in a specific department - only SuperAdmins can update permissions for Admin roles"""
    try:
        # Check department-specific admin permissions
        check_department_admin_permissions(user_data, permissions_request.department_name)
        
        # Check if user can modify permissions for this specific role
        check_admin_role_permissions(user_data, permissions_request.role_name)
        
        # Validate that at least one permission field is provided
        provided_fields = permissions_request.model_dump(exclude_unset=True, exclude={'department_name', 'role_name'})
        if not provided_fields:
            raise HTTPException(status_code=400, detail="At least one permission field must be provided for update")
        
        # Validate read access prerequisite for patch operations
        await validate_read_access_for_patch(permissions_request, role_service)
        
        # Validate special access permissions prerequisites for patch operations
        await validate_special_access_for_patch(permissions_request, role_service)
        
        # Get client info for audit
        ip_address = request.client.host if request.client else None
        user_agent = request.headers.get("user-agent", "")
        
        # Update permissions using the partial update service method
        result = await role_service.update_role_permissions(
            request=permissions_request,
            updated_by=user_data.email,
            ip_address=ip_address,
            user_agent=user_agent,
            department_name=user_data.department_name
        )
        
        return result
    
    except HTTPException:
        raise
    except Exception as e:
        log.error(f"Patch role permissions endpoint error: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")

@router.post("/permissions/get", response_model=RolePermissionsResponse)
async def get_role_permissions(
    get_request: GetRolePermissionsRequest,
    user_data: User = Depends(get_current_user),
    role_service: RoleAccessService = Depends(get_role_access_service)
):
    """Get permissions for a specific role in a specific department - only Admins (for their dept) and SuperAdmins can view role permissions"""
    try:
        
        # Get role permissions using the service
        result = await role_service.get_role_permissions(get_request.department_name, get_request.role_name)
        return result
    
    except HTTPException:
        raise
    except Exception as e:
        log.error(f"Get role permissions endpoint error: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")

@router.get("/permissions", response_model=AllRolePermissionsResponse)
async def get_all_role_permissions(
    department_name: str = None,
    user_data: User = Depends(get_current_user),
    role_service: RoleAccessService = Depends(get_role_access_service)
):
    """
    Get role permissions from role_access table. 
    - Without department_name: SuperAdmins see all departments, Admins see only their own
    - With department_name: Returns permissions for that specific department (with proper access control)
    """
    try:
        # SuperAdmin can see all departments
        if user_data.role == 'SuperAdmin':
            result = await role_service.get_all_role_permissions(department_name)
            return result
        
        # Admin can only see their own department
        elif user_data.role == 'Admin':
            user_department = getattr(user_data, 'department_name', None) 
            
            # If department_name is specified and it's not their department, deny access
            if department_name and department_name != user_department:
                raise HTTPException(
                    status_code=403,
                    detail=f"Access denied. Admin users can only view permissions for their own department ('{user_department}')."
                )
            
            # Always filter by their department
            result = await role_service.get_all_role_permissions(user_department)
            return result
        
        # Other roles cannot access this endpoint
        else:
            raise HTTPException(
                status_code=403,
                detail="Access denied. Only Admin and SuperAdmin can view role permissions."
            )
    
    except HTTPException:
        raise
    except Exception as e:
        log.error(f"Get all role permissions endpoint error: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")



@router.get("/department/{department_name}/overview")
async def get_department_overview(
    department_name: str,
    user_data: User = Depends(get_current_user)
):
    """Get complete overview: roles from departments table + permissions from role_access table"""
    try:
        # Check department-specific admin permissions
        check_department_admin_permissions(user_data, department_name)
        
        from src.api.dependencies import ServiceProvider
        
        # Get roles from departments.roles JSONB
        department_service = ServiceProvider.get_department_service()
        roles_result = await department_service.get_department_roles(department_name, user_department_name=user_data.department_name)
        
        # Get permissions from role_access table
        role_service = ServiceProvider.get_role_access_service()
        permissions_result = await role_service.get_all_role_permissions(department_name)
        
        return {
            "success": True,
            "department_name": department_name,
            "roles": {
                "source": "departments.roles JSONB column",
                "data": roles_result
            },
            "permissions": {
                "source": "role_access table",
                "data": permissions_result
            }
        }
    
    except HTTPException:
        raise
    except Exception as e:
        log.error(f"Get department overview endpoint error: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")

