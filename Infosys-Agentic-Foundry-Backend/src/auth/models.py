from enum import Enum
from typing import Optional, List
from pydantic import BaseModel
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
    
    # Agent permissions
    READ_AGENTS = "read_agents"
    CREATE_AGENTS = "create_agents"
    UPDATE_AGENTS = "update_agents"
    DELETE_AGENTS = "delete_agents"
    
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
        Permission.READ_TOOLS,
        Permission.READ_AGENTS,
    ],
    UserRole.DEVELOPER: [
        Permission.READ_TOOLS,
        Permission.CREATE_TOOLS,
        Permission.UPDATE_TOOLS,
        Permission.READ_AGENTS,
        Permission.CREATE_AGENTS,
        Permission.UPDATE_AGENTS,
    ],
    UserRole.ADMIN: [
        Permission.READ_TOOLS,
        Permission.CREATE_TOOLS,
        Permission.UPDATE_TOOLS,
        Permission.DELETE_TOOLS,
        Permission.READ_AGENTS,
        Permission.CREATE_AGENTS,
        Permission.UPDATE_AGENTS,
        Permission.DELETE_AGENTS,
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
        Permission.READ_AGENTS,
        Permission.CREATE_AGENTS,
        Permission.UPDATE_AGENTS,
        Permission.DELETE_AGENTS,
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
    role: UserRole
    status: UserStatus
    created_at: datetime
    updated_at: datetime
    last_login: Optional[datetime] = None
    approved_by: Optional[str] = None
    approved_at: Optional[datetime] = None


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
    role: str


class LoginResponse(BaseModel):
    approval: bool
    token: Optional[str] = None  # JWT token
    role: Optional[str] = None
    username: Optional[str] = None
    email: Optional[str] = None
    message: str


class RegisterRequest(BaseModel):
    email_id: str
    password: str
    role: str
    user_name: str


class RegisterResponse(BaseModel):
    approval: bool
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
    new_password: Optional[str] = None
    role: Optional[str] = None
