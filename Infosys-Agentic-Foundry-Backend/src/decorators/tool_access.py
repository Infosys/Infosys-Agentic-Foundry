# © 2024-25 Infosys Limited, Bangalore, India. All Rights Reserved.
"""
Tool Access Control Decorators

Provides decorators for controlling access to tools based on:
1. @resource_access - Data-level access (checks if user can access specific resource values)
2. @require_role - Role-level access (checks if user has required role)

Usage:
    @resource_access("employees", "emp_id")
    def get_employee_salary(emp_id: str):
        ...

    @require_role("Admin", "Manager")
    def delete_employee(emp_id: str):
        ...
"""

from functools import wraps
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Dict, List, Set, Optional, Any
import inspect

from telemetry_wrapper import logger as log


# ─────────────────────────────────────────────────────────────────────────────
# USER CONTEXT
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class ToolUserContext:
    """
    User context for tool access control.
    Built from JWT at API layer and passed through agent runtime.
    """
    user_id: str
    email: str
    role: str
    department: Optional[str] = None
    token: Optional[str] = None
    
    # Resource access: { "employees": ["EMP001", "EMP002"], "projects": ["*"] }
    resource_access: Dict[str, List[str]] = field(default_factory=dict)
    
    # Resource exclusions: { "employees": ["CEO001", "CFO001"] } - these take priority over allowed
    resource_exclusions: Dict[str, List[str]] = field(default_factory=dict)
    
    def can_access_resource(self, access_key: str, value: str) -> bool:
        """
        Check if user can access a specific resource value.
        Exclusions take priority over allowed values.
        
        Args:
            access_key: The resource type (e.g., "employees", "projects")
            value: The specific value to check (e.g., "EMP001")
        
        Returns:
            bool: True if user has access, False otherwise
        """
        # Check exclusions first - they take priority
        excluded_values = self.resource_exclusions.get(access_key, [])
        if value in excluded_values:
            return False
        
        allowed_values = self.resource_access.get(access_key, [])
        
        # Wildcard means access to all (except excluded)
        if "*" in allowed_values:
            return True
        
        return value in allowed_values
    
    def has_role(self, *required_roles: str) -> bool:
        """Check if user has one of the required roles."""
        return self.role in required_roles


# Context variable to store current user - set at API layer
current_tool_user: ContextVar[Optional[ToolUserContext]] = ContextVar('current_tool_user', default=None)


# ─────────────────────────────────────────────────────────────────────────────
# DECORATORS
# ─────────────────────────────────────────────────────────────────────────────

def resource_access(access_key: str, param_name: str):
    """
    Decorator that checks if the user has access to the resource value passed as a parameter.
    
    The tool creator specifies:
    - access_key: The type of resource (e.g., "employees", "projects", "databases")
    - param_name: The function parameter that contains the resource ID to check
    
    The department admin assigns allowed values to users via user_access_keys table.
    
    Usage:
        @resource_access("employees", "emp_id")
        def get_employee_salary(emp_id: str):
            # User must have this emp_id in their "employees" access list
            return {"salary": 85000}
    
    Args:
        access_key: Resource type key (e.g., "employees", "projects")
        param_name: Name of the function parameter containing the resource ID
    """
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            # Get current user from context
            user = current_tool_user.get()
            
            if user is None:
                log.warning(f"Tool access denied: No user context for {func.__name__}")
                return {
                    "error": "Access denied: User context not available",
                    "code": 401,
                    "tool": func.__name__
                }
            
            # Extract parameter value from function call
            sig = inspect.signature(func)
            params = list(sig.parameters.keys())
            
            resource_value = kwargs.get(param_name)
            if resource_value is None and param_name in params:
                param_index = params.index(param_name)
                if param_index < len(args):
                    resource_value = args[param_index]
            
            # If parameter not found or None, allow (no value to check)
            if resource_value is None:
                log.debug(f"Resource access: param '{param_name}' is None, allowing")
                return func(*args, **kwargs)
            
            # Check access
            if not user.can_access_resource(access_key, str(resource_value)):
                log.warning(
                    f"Resource access denied: user={user.email}, "
                    f"access_key={access_key}, value={resource_value}, tool={func.__name__}"
                )
                return {
                    "error": f"Access denied: You don't have access to {access_key}:{resource_value}",
                    "code": 403,
                    "tool": func.__name__,
                    "access_key": access_key,
                    "requested_value": str(resource_value)
                }
            
            log.debug(
                f"Resource access granted: user={user.email}, "
                f"access_key={access_key}, value={resource_value}, tool={func.__name__}"
            )
            return func(*args, **kwargs)
        
        # Store metadata for introspection
        wrapper._access_control = {
            "type": "resource_access",
            "access_key": access_key,
            "param_name": param_name
        }
        
        return wrapper
    return decorator


def require_role(*required_roles: str):
    """
    Decorator that checks if the user has one of the required roles.
    
    Usage:
        @require_role("Admin", "Manager", "HR")
        def delete_employee(emp_id: str):
            # Only Admin, Manager, or HR can call this
            ...
    
    Args:
        *required_roles: One or more role names that are allowed
    """
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            # Get current user from context
            user = current_tool_user.get()
            
            if user is None:
                log.warning(f"Role check failed: No user context for {func.__name__}")
                return {
                    "error": "Access denied: User context not available",
                    "code": 401,
                    "tool": func.__name__
                }
            
            # Check role
            if not user.has_role(*required_roles):
                log.warning(
                    f"Role access denied: user={user.email}, "
                    f"user_role={user.role}, required_roles={required_roles}, tool={func.__name__}"
                )
                return {
                    "error": f"Access denied: Role {user.role} is not authorized. Required: {', '.join(required_roles)}",
                    "code": 403,
                    "tool": func.__name__,
                    "user_role": user.role,
                    "required_roles": list(required_roles)
                }
            
            log.debug(
                f"Role access granted: user={user.email}, "
                f"role={user.role}, tool={func.__name__}"
            )
            return func(*args, **kwargs)
        
        # Store metadata for introspection
        wrapper._access_control = {
            "type": "require_role",
            "required_roles": list(required_roles)
        }
        
        return wrapper
    return decorator


# ─────────────────────────────────────────────────────────────────────────────
# HELPER FUNCTIONS
# ─────────────────────────────────────────────────────────────────────────────

def set_tool_user_context(user: ToolUserContext) -> None:
    """
    Set the current user context for tool access control.
    Called at API layer before agent execution.
    """
    current_tool_user.set(user)
    log.debug(f"Tool user context set: {user.email}")


def clear_tool_user_context() -> None:
    """Clear the current user context."""
    current_tool_user.set(None)


def get_tool_user_context() -> Optional[ToolUserContext]:
    """Get the current user context."""
    return current_tool_user.get()


# ─────────────────────────────────────────────────────────────────────────────
# COMBINED DECORATOR (for complex checks)
# ─────────────────────────────────────────────────────────────────────────────

def authorized_tool(
    required_roles: List[str] = None,
    resource_checks: Dict[str, str] = None  # {access_key: param_name}
):
    """
    All-in-one decorator for tool access control.
    Combines role check and resource access check.
    
    Usage:
        @authorized_tool(
            required_roles=["Manager", "Admin"],
            resource_checks={"projects": "project_id", "employees": "emp_id"}
        )
        def update_project_assignment(project_id: str, emp_id: str):
            ...
    
    Args:
        required_roles: List of roles allowed to call this tool (None = any role)
        resource_checks: Dict mapping access_key to param_name for resource checks
    """
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            user = current_tool_user.get()
            
            if user is None:
                log.warning(f"Authorized tool denied: No user context for {func.__name__}")
                return {
                    "error": "Access denied: User context not available",
                    "code": 401,
                    "tool": func.__name__
                }
            
            # 1. Check role
            if required_roles and not user.has_role(*required_roles):
                log.warning(
                    f"Role check failed: user={user.email}, role={user.role}, "
                    f"required={required_roles}, tool={func.__name__}"
                )
                return {
                    "error": f"Access denied: Role {user.role} not authorized",
                    "code": 403,
                    "tool": func.__name__,
                    "required_roles": required_roles
                }
            
            # 2. Check resource access
            if resource_checks:
                sig = inspect.signature(func)
                params = list(sig.parameters.keys())
                
                for access_key, param_name in resource_checks.items():
                    # Get param value
                    resource_value = kwargs.get(param_name)
                    if resource_value is None and param_name in params:
                        idx = params.index(param_name)
                        if idx < len(args):
                            resource_value = args[idx]
                    
                    if resource_value and not user.can_access_resource(access_key, str(resource_value)):
                        log.warning(
                            f"Resource check failed: user={user.email}, "
                            f"access_key={access_key}, value={resource_value}, tool={func.__name__}"
                        )
                        return {
                            "error": f"Access denied: No access to {access_key}:{resource_value}",
                            "code": 403,
                            "tool": func.__name__,
                            "access_key": access_key
                        }
            
            log.debug(f"Authorized tool access granted: user={user.email}, tool={func.__name__}")
            return func(*args, **kwargs)
        
        wrapper._access_control = {
            "type": "authorized_tool",
            "required_roles": required_roles,
            "resource_checks": resource_checks
        }
        
        return wrapper
    return decorator
 