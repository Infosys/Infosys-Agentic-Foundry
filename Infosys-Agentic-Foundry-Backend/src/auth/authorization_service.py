from typing import List, Optional, Dict, Any
from src.auth.models import UserRole, Permission, ROLE_PERMISSIONS, GrantApprovalPermissionRequest, ApprovalPermissionResponse
from src.auth.repositories import UserRepository, ApprovalPermissionRepository, AuditLogRepository, RoleRepository
from telemetry_wrapper import logger as log

from src.utils.secrets_handler import current_user_email, current_user_department, current_user_role


class AuthorizationService:
    """Service for authorization and permission management"""
    
    def __init__(self, user_repo: UserRepository, approval_repo: ApprovalPermissionRepository, audit_repo: AuditLogRepository, role_repo: RoleRepository):
        self.user_repo = user_repo
        self.approval_repo = approval_repo
        self.audit_repo = audit_repo
        self.role_repo = role_repo
    
    async def _is_superadmin(self, user_email: str, department_name: str = None) -> bool:
        """Check if user is SuperAdmin - helper method for bypassing permission checks"""
        try:
            user_data = await self.user_repo.get_user_by_email(user_email, department_name= department_name)
            if not user_data:
                return False
            return user_data['role'] == UserRole.SUPER_ADMIN
        except Exception as e:
            log.error(f"SuperAdmin check error: {e}")
            return False
    
    async def has_permission(self, user_email: str, permission: Permission, department_name:str = None) -> bool:
        """Check if user has a specific permission"""
        try:
            # SuperAdmin bypass - has all permissions
            if await self._is_superadmin(user_email):
                log.info(f"SuperAdmin {user_email} granted permission: {permission}")
                return True
            
            user_data = await self.user_repo.get_user_by_email(user_email, department_name=department_name)
            if not user_data:
                return False
            
            user_role = user_data['role']
            
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
    
    async def has_role(self, user_email: str, required_role: UserRole, department_name: str = None) -> bool:
        """Check if user has the required role or higher"""
        try:
            # SuperAdmin bypass - always has required role
            if await self._is_superadmin(user_email):
                log.info(f"SuperAdmin {user_email} granted role access: {required_role}")
                return True
            
            user_data = await self.user_repo.get_user_by_email(user_email, department_name=department_name)
            if not user_data:
                return False
            
            user_role = user_data['role']
            
            # Role hierarchy: SuperAdmin > Admin > Developer > User
            role_hierarchy = {
                UserRole.USER: 0,
                UserRole.DEVELOPER: 1,
                UserRole.ADMIN: 2,
                UserRole.SUPER_ADMIN: 3
            }
            
            user_level = role_hierarchy.get(user_role, 0)
            required_level = role_hierarchy.get(required_role, 0)
            
            return user_level == required_level
            
        except Exception as e:
            log.error(f"Role check error: {e}")
            return False
    
    async def get_user_permissions(self, user_email: str, department_name: str = None) -> List[Permission]:
        """Get all permissions for a user"""
        try:
            user_data = await self.user_repo.get_user_by_email(user_email, department_name=department_name)
            if not user_data:
                return []
            
            user_role = user_data['role']
            
            # SuperAdmin gets all possible permissions
            if user_role == UserRole.SUPER_ADMIN:
                all_permissions = list(Permission)  # All permissions from enum
                log.info(f"SuperAdmin {user_email} granted all permissions")
                return all_permissions
            
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
    
    async def check_operation_permission(self, user_email: str, user_role: str, operation: str, resource_type: str, department_name: str = None) -> bool:
        """Centralized function to check if user has permission for CRUD and execute operations
        
        Args:
            user_email: Email of the user
            user_role: Role of the user (from user_data.role)
            operation: 'create', 'read', 'update', 'delete', or 'execute'
            resource_type: 'tools' or 'agents'
            department_name: Name of the department (if None, uses user's department)
            
        Returns:
            bool: True if user has permission, False otherwise
        """
        try:
            # SuperAdmin bypass - has all operation permissions
            if await self._is_superadmin(user_email):
                log.info(f"SuperAdmin {user_email} granted {operation} permission on {resource_type}")
                return True
            
            # Get user data to find their role name and department
            user_data = await self.user_repo.get_user_by_email(user_email, department_name=department_name)
            if not user_data:
                log.warning(f"User {user_email} not found in database")
                return False
            
            role_name = user_role
            
            # Use provided department_name or default to user's department, fallback to "General"
            effective_department = department_name or user_data.get('department_name') 
            
            # Get role permissions from role_access table for specific department
            role_permissions = await self.role_repo.get_role_permissions(effective_department, role_name)
            if not role_permissions:
                log.warning(f"No permissions found for role '{role_name}'")
                return False
            
            # Map operation to permission field name
            operation_field_map = {
                'create': 'add_access',
                'read': 'read_access',
                'update': 'update_access', 
                'delete': 'delete_access',
                'execute': 'execute_access'
            }
            
            operation_field = operation_field_map.get(operation.lower())
            if not operation_field:
                log.warning(f"Invalid operation '{operation}'")
                return False
            
            # Get the permission data for this operation
            permission_data = role_permissions.get(operation_field)
            if not permission_data:
                log.warning(f"No {operation_field} found for role '{role_name}'")
                return False
            
            # Handle different data types (dict from JSONB, string from JSONB, or boolean from old system)
            if isinstance(permission_data, dict):
                # New JSON structure: {"tools": boolean, "agents": boolean}
                resource_key = resource_type.lower()  # 'tools' or 'agents'
                has_permission = permission_data.get(resource_key, False)
            elif isinstance(permission_data, str):
                # JSONB data returned as string - parse it
                try:
                    import json
                    parsed_data = json.loads(permission_data)
                    resource_key = resource_type.lower()  # 'tools' or 'agents'
                    has_permission = parsed_data.get(resource_key, False)
                except (json.JSONDecodeError, TypeError) as e:
                    log.error(f"Failed to parse JSON permission data for {operation_field}: {permission_data} - {e}")
                    return False
            elif isinstance(permission_data, bool):
                # Fallback for old boolean system - apply to both tools and agents
                has_permission = permission_data
            else:
                log.warning(f"Unexpected permission data type for {operation_field}: {type(permission_data)}")
                return False
            
            if not has_permission:
                log.warning(f"User {user_email} with role '{role_name}' attempted {operation} on {resource_type} without permission")
            else:
                log.info(f"User {user_email} with role '{role_name}' granted {operation} permission on {resource_type}")
            
            return has_permission
            
        except Exception as e:
            log.error(f"Permission check error for {user_email}: {e}")
            return False
    
    async def check_execution_steps_access(self, role: str, department_name: str = None) -> bool:
        """Check if user has access to view execution steps (detailed information)
        
        Args:
            role: Role name of the user
            department_name: Department name (defaults to "General")
            
        Returns:
            bool: True if user can see execution steps, False if only essential fields
        """
        try:
            # SuperAdmin bypass - always has execution steps access
            if role == "SuperAdmin":
                log.info(f"SuperAdmin granted execution steps access")
                return True
            
            # Get role permissions directly using the role parameter and department
            role_permissions = await self.role_repo.get_role_permissions(department_name, role)
            if not role_permissions:
                log.warning(f"No permissions found for role '{role}'")
                return False
            
            # Get execution_steps_access permission
            execution_steps_access = role_permissions.get('execution_steps_access', False)
            
            log.info(f"Role '{role}' execution steps access: {execution_steps_access}")
            return execution_steps_access
            
        except Exception as e:
            log.error(f"Execution steps access check error for role '{role}': {e}")
            return False

    

    async def check_vault_access(self, role: str, department_name: str = "General") -> bool:
        """Check if user has access to vault/secrets endpoints
        
        Args:
            role: Role name of the user
            department_name: Department name (defaults to "General")
            
        Returns:
            bool: True if user can access vault endpoints, False otherwise
        """
        try:
            # SuperAdmin bypass - no permission checks needed
            if role == 'SuperAdmin':
                log.info(f"SuperAdmin bypass - granted vault access without permission check")
                return True
            
            # Get role permissions from role_access table for the specific department
            role_permissions = await self.role_repo.get_role_permissions(department_name, role)
            if not role_permissions:
                log.warning(f"No permissions found for role '{role}' in department '{department_name}'")
                return False
            
            # Get vault_access permission
            vault_access = role_permissions.get('vault_access', False)
            
            log.info(f"Role '{role}' in department '{department_name}' vault access: {vault_access}")
            return vault_access
            
        except Exception as e:
            log.error(f"Vault access check error for role '{role}': {e}")
            return False

    async def check_data_connector_access(self, role: str, department_name: str = None) -> bool:
        """Check if user has access to data connector endpoints
        
        Args:
            role: Role name of the user
            department_name: Department name (defaults to "General")
            
        Returns:
            bool: True if user can access data connector endpoints, False otherwise
        """
        try:
            # SuperAdmin bypass - no permission checks needed
            if role == 'SuperAdmin':
                log.info(f"SuperAdmin bypass - granted data connector access without permission check")
                return True
            
            # Get role permissions from role_access table for the specific department
            role_permissions = await self.role_repo.get_role_permissions(department_name, role)
            if not role_permissions:
                log.warning(f"No permissions found for role '{role}' in department '{department_name}'")
                return False
            
            # Get data_connector_access permission
            data_connector_access = role_permissions.get('data_connector_access', False)
            
            log.info(f"Role '{role}' in department '{department_name}' data connector access: {data_connector_access}")
            return data_connector_access
            
        except Exception as e:
            log.error(f"Data connector access check error for role '{role}': {e}")
            return False

    async def check_knowledgebase_access(self, role: str, department_name: str = None) -> bool:
        """Check if user has access to knowledge base endpoints
        
        Args:
            role: Role name of the user
            department_name: Department name (defaults to "General")
            
        Returns:
            bool: True if user can access knowledge base endpoints, False otherwise
        """
        try:
            # SuperAdmin bypass - no permission checks needed
            if role == 'SuperAdmin':
                log.info(f"SuperAdmin bypass - granted knowledgebase access without permission check")
                return True
            
            # Get role permissions from role_access table for the specific department
            role_permissions = await self.role_repo.get_role_permissions(department_name, role)
            if not role_permissions:
                log.warning(f"No permissions found for role '{role}' in department '{department_name}'")
                return False
            
            # Get knowledgebase_access permission
            knowledgebase_access = role_permissions.get('knowledgebase_access', False)
            
            log.info(f"Role '{role}' in department '{department_name}' knowledgebase access: {knowledgebase_access}")
            return knowledgebase_access
            
        except Exception as e:
            log.error(f"Knowledgebase access check error for role '{role}': {e}")
            return False

    async def check_evaluation_access(self, role: str, department_name: str = "General") -> bool:
        """
        Check if user has evaluation access permission
        
        Args:
            role: Role name of the user
            department_name: Department name (defaults to "General")
            
        Returns:
            bool: True if user can access evaluation endpoints, False otherwise
        """
        try:
            # SuperAdmin bypass - no permission checks needed
            if role == 'SuperAdmin':
                log.info(f"SuperAdmin bypass - granted evaluation access without permission check")
                return True
            
            # Get role permissions from role_access table for the specific department
            role_permissions = await self.role_repo.get_role_permissions(department_name, role)
            if not role_permissions:
                log.warning(f"No permissions found for role '{role}' in department '{department_name}'")
                return False
            
            # Get evaluation_access permission
            evaluation_access = role_permissions.get('evaluation_access', False)
            
            log.info(f"Role '{role}' in department '{department_name}' evaluation access: {evaluation_access}")
            return evaluation_access
            
        except Exception as e:
            log.error(f"Evaluation access check error for role '{role}': {e}")
            return False
