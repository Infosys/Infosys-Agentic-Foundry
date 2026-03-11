from enum import Enum
import re
from typing import Optional, List, Dict
from pydantic import BaseModel, Field, field_validator, Field
from datetime import datetime


class UserRole(str, Enum):
    USER = "User"
    DEVELOPER = "Developer"
    ADMIN = "Admin"
    SUPER_ADMIN = "SuperAdmin"


class UserStatus(str, Enum):
    ACTIVE = "active"
    INACTIVE = "inactive"
    PENDING_APPROVAL = "pending_approval"


class Permission(str, Enum):
    # Tool permissions
    READ_TOOLS = "read_tools"
    CREATE_TOOLS = "create_tools"
    UPDATE_TOOLS = "update_tools"
    DELETE_TOOLS = "delete_tools"
    EXECUTE_TOOLS = "execute_tools"
    
    # Agent permissions
    READ_AGENTS = "read_agents"
    CREATE_AGENTS = "create_agents"
    UPDATE_AGENTS = "update_agents"
    DELETE_AGENTS = "delete_agents"
    EXECUTE_AGENTS = "execute_agents"
    
    # Pipeline permissions
    READ_PIPELINES = "read_pipelines"
    CREATE_PIPELINES = "create_pipelines"
    UPDATE_PIPELINES = "update_pipelines"
    DELETE_PIPELINES = "delete_pipelines"
    EXECUTE_PIPELINES = "execute_pipelines"
    
    # User management permissions
    MANAGE_USERS = "manage_users"
    VIEW_ALL_USERS = "view_all_users"
    
    # Approval permissions
    APPROVE_AGENTS = "approve_agents"
    APPROVE_TOOLS = "approve_tools"
    GRANT_APPROVAL_PERMISSIONS = "grant_approval_permissions"
    
    # System permissions
    SYSTEM_ADMIN = "system_admin"
    VIEW_AUDIT_LOGS = "view_audit_logs"


# Role-based permission mapping
ROLE_PERMISSIONS = {
    UserRole.USER: [
        # Users can read and execute pipelines for testing
        Permission.READ_PIPELINES,
        Permission.EXECUTE_PIPELINES,
        Permission.READ_AGENTS,
        Permission.EXECUTE_AGENTS,
    ],
    UserRole.DEVELOPER: [
        Permission.READ_TOOLS,
        Permission.CREATE_TOOLS,
        Permission.UPDATE_TOOLS,
        Permission.EXECUTE_TOOLS,
        Permission.DELETE_TOOLS,
        Permission.READ_AGENTS,
        Permission.CREATE_AGENTS,
        Permission.UPDATE_AGENTS,
        Permission.EXECUTE_AGENTS,
        Permission.DELETE_AGENTS,
        Permission.READ_PIPELINES,
        Permission.CREATE_PIPELINES,
        Permission.UPDATE_PIPELINES,
        Permission.DELETE_PIPELINES,
        Permission.EXECUTE_PIPELINES
    ],
    UserRole.ADMIN: [
        Permission.READ_TOOLS,
        Permission.CREATE_TOOLS,
        Permission.UPDATE_TOOLS,
        Permission.DELETE_TOOLS,
        Permission.EXECUTE_TOOLS,
        Permission.READ_AGENTS,
        Permission.CREATE_AGENTS,
        Permission.UPDATE_AGENTS,
        Permission.DELETE_AGENTS,
        Permission.EXECUTE_AGENTS,
        Permission.READ_PIPELINES,
        Permission.CREATE_PIPELINES,
        Permission.UPDATE_PIPELINES,
        Permission.DELETE_PIPELINES,
        Permission.EXECUTE_PIPELINES,
        Permission.MANAGE_USERS,
        Permission.VIEW_ALL_USERS,
        Permission.VIEW_AUDIT_LOGS,
    ],
    UserRole.SUPER_ADMIN: [
        # Super Admin has all permissions
        Permission.READ_TOOLS,
        Permission.CREATE_TOOLS,
        Permission.UPDATE_TOOLS,
        Permission.DELETE_TOOLS,
        Permission.EXECUTE_TOOLS,
        Permission.READ_AGENTS,
        Permission.CREATE_AGENTS,
        Permission.UPDATE_AGENTS,
        Permission.DELETE_AGENTS,
        Permission.EXECUTE_AGENTS,
        Permission.READ_PIPELINES,
        Permission.CREATE_PIPELINES,
        Permission.UPDATE_PIPELINES,
        Permission.DELETE_PIPELINES,
        Permission.EXECUTE_PIPELINES,
        Permission.MANAGE_USERS,
        Permission.VIEW_ALL_USERS,
        Permission.APPROVE_AGENTS,
        Permission.APPROVE_TOOLS,
        Permission.GRANT_APPROVAL_PERMISSIONS,
        Permission.SYSTEM_ADMIN,
        Permission.VIEW_AUDIT_LOGS,
    ]
}


class User(BaseModel):
    id: str
    email: str
    username: str
    role: str
    status: UserStatus
    created_at: datetime
    updated_at: datetime
    last_login: Optional[datetime] = None
    approved_by: Optional[str] = None
    approved_at: Optional[datetime] = None
    department_name: Optional[str] = None


class ApprovalPermission(BaseModel):
    id: str
    admin_user_id: str
    granted_by: str  # Super Admin who granted the permission
    permission_type: str  # 'agent_approval' or 'tool_approval'
    granted_at: datetime
    is_active: bool = True


class AuditLog(BaseModel):
    id: str
    user_id: str
    action: str
    resource_type: str  # 'user', 'agent', 'tool', 'approval_permission'
    resource_id: Optional[str] = None
    old_value: Optional[str] = None
    new_value: Optional[str] = None
    timestamp: datetime
    ip_address: Optional[str] = None
    user_agent: Optional[str] = None


# Request/Response Models
class LoginRequest(BaseModel):
    email_id: str
    password: str
    department_name: Optional[str] = None


class LoginResponse(BaseModel):
    approval: bool
    token: Optional[str] = None  # JWT token
    refresh_token: Optional[str] = None  # Long-lived refresh token
    role: Optional[str] = None
    username: Optional[str] = None
    email: Optional[str] = None
    department_name: Optional[str] = None  # Added department field
    must_change_password: bool = Field(default=False, description="Flag indicating user must change password")
    message: str


class RefreshTokenRequest(BaseModel):
    """Request payload for refreshing access token.

    If refresh_token is not provided in body, the API will attempt to read it from the
    HttpOnly cookie named 'refresh_token'. This keeps backward compatibility with existing
    login response schema while enabling refresh flow.
    """
    refresh_token: Optional[str] = None


class RefreshTokenResponse(BaseModel):
    """Response returned when a refresh token is used to obtain a new access token."""
    approval: bool
    token: Optional[str] = None  # New access JWT
    refresh_token: Optional[str] = None  # Rotated refresh token (if rotation enabled)
    message: str
    # (Intentionally NOT returning a new refresh token field in JSON to avoid breaking clients.)


class RegisterRequest(BaseModel):
    email_id: str
    password: str
    user_name: str

    @field_validator('user_name')
    @classmethod
    def validate_username(cls, v: str) -> str:
        if not re.match(r'^[a-zA-Z0-9 ]+$', v):
            raise ValueError('Username must contain only alphanumeric characters and spaces')
        return v.strip()


class RegisterResponse(BaseModel):
    approval: bool
    message: str


class AssignRoleDepartmentRequest(BaseModel):
    email_id: str
    department_name: str
    role: str


class AssignRoleDepartmentResponse(BaseModel):
    success: bool
    message: str


class GrantApprovalPermissionRequest(BaseModel):
    admin_user_id: str
    permission_type: str  # 'agent_approval' or 'tool_approval'


class RevokeApprovalPermissionRequest(BaseModel):
    admin_user_id: str
    permission_type: str


class ApprovalPermissionResponse(BaseModel):
    success: bool
    message: str
    approval_permission: Optional[ApprovalPermission] = None


class UpdatePasswordRequest(BaseModel):
    email_id: str
    new_password: Optional[str] = Field(None, description="New password for the user")
    role: Optional[str] = None
    department_name: Optional[str] = None
    

class UpdateUserRoleRequest(BaseModel):
    email_id: str = Field(..., description="Target user's email (mail_id)")
    new_role: Optional[str] = Field(None, description="New role to assign within the department")
    department_name: Optional[str] = Field(None, description="Department to update role in. Required for SuperAdmin, optional for Admin (defaults to admin's department).")
    temporary_password: Optional[str] = Field(None, description="Temporary password to set for the user. User will be required to change on next login.")


# User Enable/Disable Models
class SetUserActiveStatusRequest(BaseModel):
    """Request to enable or disable a user's login access"""
    email_id: str = Field(..., description="Target user's email (mail_id)")
    is_active: bool = Field(..., description="Whether the user should be active (True) or disabled (False)")
    department_name: Optional[str] = Field(None, description="Department to enable/disable user in. If None, applies globally.")


class UserActiveStatusResponse(BaseModel):
    """Response for user enable/disable operations"""
    success: bool
    message: str
    email: str
    is_active: bool
    department_name: Optional[str] = Field(None, description="Department affected, or None for global")
    scope: str = Field(default="global", description="'global' for account-wide, 'department' for department-specific")


# Role-based Access Control Models
class RoleModel(BaseModel):
    role_name: str
    created_at: datetime
    created_by: Optional[str] = None


class AccessPermission(BaseModel):
    """Permission structure for tools and agents"""
    tools: bool = False
    agents: bool = False


class RoleAccessModel(BaseModel):
    department_name: str
    role_name: str
    read_access: AccessPermission
    add_access: AccessPermission
    update_access: AccessPermission
    delete_access: AccessPermission
    execute_access: AccessPermission
    execution_steps_access: Optional[bool] = None
    tool_verifier_flag_access: Optional[bool] = None
    plan_verifier_flag_access: Optional[bool] = None
    online_evaluation_flag_access: Optional[bool] = None
    evaluation_access: Optional[bool] = None
    vault_access: Optional[bool] = None
    data_connector_access: Optional[bool] = None
    knowledgebase_access: Optional[bool] = None
    validator_access: Optional[bool] = None
    file_context_access: Optional[bool] = None
    canvas_view_access: Optional[bool] = None
    context_access: Optional[bool] = None
    created_at: datetime
    updated_at: datetime
    created_by: Optional[str] = None


# Request Models
class AddRoleRequest(BaseModel):
    department_name: str
    role_name: str


class SetRolePermissionsRequest(BaseModel):
    department_name: str
    role_name: str
    read_access: AccessPermission = AccessPermission()
    add_access: AccessPermission = AccessPermission()
    update_access: AccessPermission = AccessPermission()
    delete_access: AccessPermission = AccessPermission()
    execute_access: AccessPermission = AccessPermission()
    execution_steps_access: Optional[bool] = None
    tool_verifier_flag_access: Optional[bool] = None
    plan_verifier_flag_access: Optional[bool] = None
    online_evaluation_flag_access: Optional[bool] = None
    evaluation_access: Optional[bool] = None
    vault_access: Optional[bool] = None
    data_connector_access: Optional[bool] = None
    knowledgebase_access: Optional[bool] = None
    validator_access: Optional[bool] = None
    file_context_access: Optional[bool] = None
    canvas_view_access: Optional[bool] = None
    context_access: Optional[bool] = None


class UpdateRolePermissionsRequest(BaseModel):
    department_name: str
    role_name: str
    read_access: Optional[AccessPermission] = None
    add_access: Optional[AccessPermission] = None
    update_access: Optional[AccessPermission] = None
    delete_access: Optional[AccessPermission] = None
    execute_access: Optional[AccessPermission] = None
    execution_steps_access: Optional[bool] = None
    tool_verifier_flag_access: Optional[bool] = None
    plan_verifier_flag_access: Optional[bool] = None
    online_evaluation_flag_access: Optional[bool] = None
    evaluation_access: Optional[bool] = None
    vault_access: Optional[bool] = None
    data_connector_access: Optional[bool] = None
    knowledgebase_access: Optional[bool] = None
    validator_access: Optional[bool] = None
    file_context_access: Optional[bool] = None
    canvas_view_access: Optional[bool] = None
    context_access: Optional[bool] = None


class GetRolePermissionsRequest(BaseModel):
    department_name: str
    role_name: str


class DeleteRoleRequest(BaseModel):
    department_name: str
    role_name: str


# Response Models
class RoleResponse(BaseModel):
    success: bool
    message: str
    role: Optional[RoleModel] = None


class RoleListResponse(BaseModel):
    success: bool
    message: str
    roles: List[RoleModel] = []


class RolePermissionsResponse(BaseModel):
    success: bool
    message: str
    permissions: Optional[RoleAccessModel] = None


class AllRolePermissionsResponse(BaseModel):
    success: bool
    message: str
    role_permissions: List[RoleAccessModel] = []


# Department Models
class DepartmentModel(BaseModel):
    department_name: str
    admins: Optional[List[str]] = []
    created_at: datetime
    created_by: Optional[str] = None


# Department Request Models
class AddDepartmentRequest(BaseModel):
    department_name: str = Field(..., min_length=1, max_length=50, description="Name of the department")

class AddAdminsToDepartmentRequest(BaseModel):
    admin_emails: List[str] = Field(..., description="List of admin email addresses to add")

class RemoveAdminFromDepartmentRequest(BaseModel):
    admin_email: str = Field(..., description="Email address of the admin to remove")


# Department Response Models
class DepartmentResponse(BaseModel):
    success: bool
    message: str
    department: Optional[DepartmentModel] = None


class DepartmentListResponse(BaseModel):
    success: bool
    message: str
    departments: List[DepartmentModel] = []

class AddRoleToDepartmentRequest(BaseModel):
    role_name: str = Field(..., min_length=1, max_length=50, description="Name of the role to add to department")

class RemoveRoleFromDepartmentRequest(BaseModel):
    role_name: str = Field(..., description="Name of the role to remove from department")

class DepartmentRoleResponse(BaseModel):
    success: bool
    message: str
    roles: List[str] = []


class DepartmentUserInfo(BaseModel):
    """Response model for user info in department"""
    email: str
    user_name: Optional[str] = None
    role: str
    is_active: bool = Field(default=True, description="Whether user is active in this department")
    global_is_active: bool = Field(default=True, description="Whether user account is globally active")


class DepartmentUsersResponse(BaseModel):
    """Response model for listing users in department"""
    department_name: str
    total_count: int
    users: List[DepartmentUserInfo]


class DepartmentUsersInfo(BaseModel):
    """Response model for users in a single department (used in all departments response)"""
    department_name: str
    user_count: int
    users: List[DepartmentUserInfo]


class AllDepartmentsUsersResponse(BaseModel):
    """Response model for listing users across all departments (SuperAdmin only)"""
    total_departments: int
    total_users: int
    departments: List[DepartmentUsersInfo]


class PaginatedDepartmentUsersResponse(BaseModel):
    """Response model for paginated search of users in a department"""
    department_name: str
    total_count: int
    page: int
    page_size: int
    total_pages: int
    has_next: bool
    has_previous: bool
    users: List[DepartmentUserInfo]


class PaginatedAllDepartmentsUsersResponse(BaseModel):
    """Response model for paginated search of users across all departments (SuperAdmin only)"""
    total_departments: int
    total_users: int
    filtered_count: int
    page: int
    page_size: int
    total_pages: int
    has_next: bool
    has_previous: bool
    users: List[DepartmentUserInfo]


# ─────────────────────────────────────────────────────────────────────────────
# PWD RESET FLOW MODELS
# ─────────────────────────────────────────────────────────────────────────────

class AdminResetPasswordRequest(BaseModel):
    """Request model for SuperAdmin to reset a user's PWD with a temporary PWD"""
    email_id: str = Field(..., description="Target user's email (mail_id)")
    temporary_password: str = Field(..., description="Temporary password to set for the user")


class AdminResetPasswordResponse(BaseModel):
    """Response model for SuperAdmin PWD reset"""
    success: bool
    message: str
    email: str
    must_change_password: bool = Field(default=True, description="Flag indicating user must change password on next login")


class ChangePasswordRequest(BaseModel):
    """Request model for user to change their own PWD"""
    current_password: str = Field(..., description="Current password for verification")
    new_password: str = Field(..., description="New password to set")


class ChangePasswordResponse(BaseModel):
    """Response model for user PWD change"""
    success: bool
    message: str
