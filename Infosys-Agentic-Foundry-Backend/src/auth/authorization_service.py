from typing import List, Optional, Dict, Any
from src.auth.models import UserRole, Permission, ROLE_PERMISSIONS, GrantApprovalPermissionRequest, ApprovalPermissionResponse
from src.auth.repositories import UserRepository, ApprovalPermissionRepository, AuditLogRepository
from telemetry_wrapper import logger as log


class AuthorizationService:
    """Service for authorization and permission management"""
    
    def __init__(self, user_repo: UserRepository, approval_repo: ApprovalPermissionRepository, audit_repo: AuditLogRepository):
        self.user_repo = user_repo
        self.approval_repo = approval_repo
        self.audit_repo = audit_repo
    
    async def has_permission(self, user_email: str, permission: Permission) -> bool:
        """Check if user has a specific permission"""
        try:
            user_data = await self.user_repo.get_user_by_email(user_email)
            if not user_data:
                return False
            
            user_role = UserRole(user_data['role'])
            
            # Check role-based permissions
            if permission in ROLE_PERMISSIONS.get(user_role, []):
                return True
            
            # Check granted approval permissions for admins
            if user_role == UserRole.ADMIN:
                if permission == Permission.APPROVE_AGENTS:
                    return await self.approval_repo.has_approval_permission(user_email, "agent_approval")
                elif permission == Permission.APPROVE_TOOLS:
                    return await self.approval_repo.has_approval_permission(user_email, "tool_approval")
            
            return False
            
        except Exception as e:
            log.error(f"Permission check error: {e}")
            return False
    
    async def has_role(self, user_email: str, required_role: UserRole) -> bool:
        """Check if user has the required role or higher"""
        try:
            user_data = await self.user_repo.get_user_by_email(user_email)
            if not user_data:
                return False
            
            user_role = UserRole(user_data['role'])
            
            # Role hierarchy: SuperAdmin > Admin > Developer > User
            role_hierarchy = {
                UserRole.USER: 0,
                UserRole.DEVELOPER: 1,
                UserRole.ADMIN: 2,
                UserRole.SUPER_ADMIN: 3
            }
            
            user_level = role_hierarchy.get(user_role, 0)
            required_level = role_hierarchy.get(required_role, 0)
            
            return user_level >= required_level
            
        except Exception as e:
            log.error(f"Role check error: {e}")
            return False
    
    async def get_user_permissions(self, user_email: str) -> List[Permission]:
        """Get all permissions for a user"""
        try:
            user_data = await self.user_repo.get_user_by_email(user_email)
            if not user_data:
                return []
            
            user_role = UserRole(user_data['role'])
            permissions = ROLE_PERMISSIONS.get(user_role, []).copy()
            
            # Add granted approval permissions for admins
            if user_role == UserRole.ADMIN:
                if await self.approval_repo.has_approval_permission(user_email, "agent_approval"):
                    permissions.append(Permission.APPROVE_AGENTS)
                if await self.approval_repo.has_approval_permission(user_email, "tool_approval"):
                    permissions.append(Permission.APPROVE_TOOLS)
            
            return permissions
            
        except Exception as e:
            log.error(f"Get user permissions error: {e}")
            return []
    
    async def check_operation_permission(self, user_email: str, user_role: UserRole, operation: str, resource_type: str) -> bool:
        """Centralized function to check if user has permission for CRUD and execute operations
        
        Args:
            user_email: Email of the user
            user_role: Role of the user (from user_data.role)
            operation: 'create', 'read', 'update', 'delete', or 'execute'
            resource_type: 'tools' or 'agents'
            
        Returns:
            bool: True if user has permission, False otherwise
        """
        try:
            # Map operation and resource to permission
            permission_map = {
                ('create', 'tools'): Permission.CREATE_TOOLS,
                ('update', 'tools'): Permission.UPDATE_TOOLS,
                ('delete', 'tools'): Permission.DELETE_TOOLS,
                ('read', 'tools'):   Permission.READ_TOOLS,
                ('execute', 'tools'): Permission.EXECUTE_TOOLS,
                ('create', 'agents'): Permission.CREATE_AGENTS,
                ('update', 'agents'): Permission.UPDATE_AGENTS,
                ('delete', 'agents'): Permission.DELETE_AGENTS,
                ('read', 'agents'):   Permission.READ_AGENTS,
                ('execute', 'agents'): Permission.EXECUTE_AGENTS,
            }
            
            required_permission = permission_map.get((operation.lower(), resource_type.lower()))
            if not required_permission:
                log.warning(f"Invalid operation '{operation}' or resource_type '{resource_type}'")
                return False
            
            # Check if user role has the required permission
            user_permissions = ROLE_PERMISSIONS.get(user_role, [])
            has_permission = required_permission in user_permissions
            
            if not has_permission:
                log.warning(f"User {user_email} with role {user_role.value} attempted {operation} on {resource_type} without permission")
            
            return has_permission
            
        except Exception as e:
            log.error(f"Permission check error for {user_email}: {e}")
            return False
    
    async def grant_approval_permission(self, request: GrantApprovalPermissionRequest, 
                                      granted_by_user_email: str, ip_address: str = None, 
                                      user_agent: str = None) -> ApprovalPermissionResponse:
        """Grant approval permission to an admin (only SuperAdmin can do this)"""
        try:
            # Verify the granter is SuperAdmin
            if not await self.has_role(granted_by_user_email, UserRole.SUPER_ADMIN):
                return ApprovalPermissionResponse(
                    success=False,
                    message="Only SuperAdmin can grant approval permissions"
                )
            
            # Verify the target user is Admin
            admin_user = await self.user_repo.get_user_by_email(request.admin_user_id)
            if not admin_user:
                return ApprovalPermissionResponse(
                    success=False,
                    message="Admin user not found"
                )
            
            if admin_user['role'] != UserRole.ADMIN.value:
                return ApprovalPermissionResponse(
                    success=False,
                    message="Target user must be an Admin"
                )
            
            # Grant permission
            permission_id = await self.approval_repo.grant_approval_permission(
                admin_user_mail_id=request.admin_user_id,
                granted_by_mail_id=granted_by_user_email,
                permission_type=request.permission_type
            )
            
            if not permission_id:
                return ApprovalPermissionResponse(
                    success=False,
                    message="Failed to grant approval permission"
                )
            
            # Log the action
            await self.audit_repo.log_action(
                user_id=granted_by_user_email,
                action="APPROVAL_PERMISSION_GRANTED",
                resource_type="approval_permission",
                resource_id=permission_id,
                new_value=f"Admin: {admin_user['mail_id']}, Type: {request.permission_type}",
                ip_address=ip_address,
                user_agent=user_agent
            )
            
            return ApprovalPermissionResponse(
                success=True,
                message=f"Approval permission granted to {admin_user['mail_id']} for {request.permission_type}"
            )
            
        except Exception as e:
            log.error(f"Grant approval permission error: {e}")
            return ApprovalPermissionResponse(
                success=False,
                message="Failed to grant approval permission due to an error"
            )
    
    async def revoke_approval_permission(self, admin_user_mail_id: str, permission_type: str,
                                         revoked_by_mail_id: str, ip_address: str = None,
                                         user_agent: str = None) -> ApprovalPermissionResponse:
        """Revoke approval permission from an admin (only SuperAdmin can do this)"""
        try:
            # Verify the revoker is SuperAdmin
            if not await self.has_role(revoked_by_mail_id, UserRole.SUPER_ADMIN):
                return ApprovalPermissionResponse(
                    success=False,
                    message="Only SuperAdmin can revoke approval permissions"
                )
            # Get admin user info for audit log
            admin_user = await self.user_repo.get_user_by_email(admin_user_mail_id)
            if not admin_user:
                return ApprovalPermissionResponse(
                    success=False,
                    message="Admin user not found"
                )
            # Revoke permission
            success = await self.approval_repo.revoke_approval_permission(admin_user_mail_id, permission_type)
            if not success:
                return ApprovalPermissionResponse(
                    success=False,
                    message="Failed to revoke approval permission"
                )
            # Log the action
            await self.audit_repo.log_action(
                user_id=revoked_by_mail_id,
                action="APPROVAL_PERMISSION_REVOKED",
                resource_type="approval_permission",
                resource_id=admin_user_mail_id,
                new_value=f"Admin: {admin_user['mail_id']}, Type: {permission_type}",
                ip_address=ip_address,
                user_agent=user_agent
            )
            return ApprovalPermissionResponse(
                success=True,
                message=f"Approval permission revoked from {admin_user['mail_id']} for {permission_type}"
            )
        except Exception as e:
            log.error(f"Revoke approval permission error: {e}")
            return ApprovalPermissionResponse(
                success=False,
                message="Failed to revoke approval permission due to an error"
            )
    
    async def get_admin_approval_permissions(self, admin_user_email: str) -> List[Dict[str, Any]]:
        """Get all approval permissions for an admin"""
        try:
            return await self.approval_repo.get_admin_approval_permissions(admin_user_email)
        except Exception as e:
            log.error(f"Get admin approval permissions error: {e}")
            return []
    
    async def get_all_approval_permissions(self) -> List[Dict[str, Any]]:
        """Get all approval permissions (only for SuperAdmin)"""
        try:
            return await self.approval_repo.get_all_approval_permissions()
        except Exception as e:
            log.error(f"Get all approval permissions error: {e}")
            return []
    
    async def can_approve_agents(self, user_email: str) -> bool:
        """Check if user can approve agents"""
        try:
            user_data = await self.user_repo.get_user_by_email(user_email)
            if not user_data:
                return False
            
            user_role = UserRole(user_data['role'])
            
            # SuperAdmin can always approve
            if user_role == UserRole.SUPER_ADMIN:
                return True
            
            # Admin can approve if granted permission
            if user_role == UserRole.ADMIN:
                return await self.approval_repo.has_approval_permission(user_email, "agent_approval")
            
            return False
            
        except Exception as e:
            log.error(f"Can approve agents check error: {e}")
            return False
    
    async def can_approve_tools(self, user_email: str) -> bool:
        """Check if user can approve tools"""
        try:
            user_data = await self.user_repo.get_user_by_email(user_email)
            if not user_data:
                return False
            
            user_role = UserRole(user_data['role'])
            
            # SuperAdmin can always approve
            if user_role == UserRole.SUPER_ADMIN:
                return True
            
            # Admin can approve if granted permission
            if user_role == UserRole.ADMIN:
                return await self.approval_repo.has_approval_permission(user_email, "tool_approval")
            
            return False
            
        except Exception as e:
            log.error(f"Can approve tools check error: {e}")
            return False
