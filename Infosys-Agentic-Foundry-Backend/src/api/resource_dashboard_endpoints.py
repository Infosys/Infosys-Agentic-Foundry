# © 2024-25 Infosys Limited, Bangalore, India. All Rights Reserved.
"""
Resource Dashboard Endpoints

This module provides API endpoints for the Resource Dashboard, allowing users to:
- View access keys in their department (no role restriction)
- Create new access keys
- View tools that use a specific access key
- View their own values for an access key
- Delete access keys (only by creator)

The Resource Dashboard is accessible by all authenticated users.
"""

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from typing import List, Optional
from src.auth.models import User
from src.auth.dependencies import get_current_user
from src.api.dependencies import ServiceProvider
from src.auth.authorization_service import AuthorizationService
from telemetry_wrapper import logger as log

router = APIRouter(prefix="/resource-dashboard", tags=["Resource Dashboard"])


# ─────────────────────────────────────────────────────────────────────────────
# REQUEST/RESPONSE MODELS
# ─────────────────────────────────────────────────────────────────────────────

class CreateAccessKeyRequest(BaseModel):
    """Request model for creating a new access key"""
    access_key: str = Field(..., description="Unique identifier for the access key (e.g., 'employees', 'projects')")
    description: Optional[str] = Field(None, description="Description of what this access key controls")


class AccessKeyDefinition(BaseModel):
    """Response model for an access key definition"""
    access_key: str
    department_name: str
    created_by: str
    created_at: str
    description: Optional[str] = None


class AccessKeyListResponse(BaseModel):
    """Response model for listing access keys"""
    department_name: str
    total_count: int
    access_keys: List[AccessKeyDefinition]


class ToolInfo(BaseModel):
    """Response model for tool information"""
    tool_id: str
    tool_name: str
    access_keys: List[str]


class ToolsByAccessKeyResponse(BaseModel):
    """Response model for tools by access key"""
    access_key: str
    total_tools: int
    tools: List[ToolInfo]


class MyValuesResponse(BaseModel):
    """Response model for user's values in an access key"""
    user_id: str
    access_key: str
    allowed_values: List[str]


class LinkToolRequest(BaseModel):
    """Request model for linking a tool to access keys"""
    tool_id: str = Field(..., description="The ID of the tool to link")
    tool_name: str = Field(..., description="The name of the tool")
    access_keys: List[str] = Field(..., description="List of access keys to link to this tool")


class UpdateMyAccessRequest(BaseModel):
    """Unified request model for updating user's access key - both allowed values and exclusions"""
    add_values: Optional[List[str]] = Field(None, description="List of values to add to allowed list")
    remove_values: Optional[List[str]] = Field(None, description="List of values to remove from allowed list")
    add_exclusions: Optional[List[str]] = Field(None, description="List of values to add to exclusion list")
    remove_exclusions: Optional[List[str]] = Field(None, description="List of values to remove from exclusion list")


class MyAccessKeyFullResponse(BaseModel):
    """Response model showing both allowed and excluded values for an access key"""
    user_id: str
    access_key: str
    allowed_values: List[str]
    excluded_values: List[str]
    

# ─────────────────────────────────────────────────────────────────────────────
# ACCESS KEY MANAGEMENT ENDPOINTS
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/access-keys", response_model=AccessKeyListResponse)
async def list_access_keys_in_department(
    current_user: User = Depends(get_current_user),
    authorization_service: AuthorizationService = Depends(ServiceProvider.get_authorization_service)
):
    """
    List all access keys in the current user's department.
    
    **Permission required** - read access on tools.
    
    Returns:
        List of access keys with their definitions
    """
    # Check permissions first - use user's department for department-wise permission check
    user_department = current_user.department_name 
    if not await authorization_service.check_operation_permission(current_user.email, current_user.role, "create", "tools", user_department):
        raise HTTPException(status_code=403, detail="You don't have permission to read access keys")
    repo = ServiceProvider.get_access_key_definitions_repository()
    access_keys = await repo.get_access_keys_by_department(current_user.department_name)
    
    return AccessKeyListResponse(
        department_name=current_user.department_name,
        total_count=len(access_keys),
        access_keys=[
            AccessKeyDefinition(
                access_key=ak["access_key"],
                department_name=ak["department_name"],
                created_by=ak["created_by"],
                created_at=ak["created_at"],
                description=ak.get("description")
            )
            for ak in access_keys
        ]
    )


@router.post("/access-keys", response_model=AccessKeyDefinition)
async def create_access_key(
    request: CreateAccessKeyRequest,
    current_user: User = Depends(get_current_user),
    authorization_service: AuthorizationService = Depends(ServiceProvider.get_authorization_service)
):
    """
    Create a new access key in the current user's department.
    
    **Permission required** - create access on tools.
    
    The access key will be associated with the user's department and can only be deleted
    by the user who created it.
    
    Args:
        request: Access key name and optional description
        
    Returns:
        Created access key definition
    """
    # Check permissions first - use user's department for department-wise permission check
    user_department = current_user.department_name 
    if not await authorization_service.check_operation_permission(current_user.email, current_user.role, "create", "tools", user_department):
        raise HTTPException(status_code=403, detail="You don't have permission to create access keys")
    repo = ServiceProvider.get_access_key_definitions_repository()
    result = await repo.create_access_key(
        access_key=request.access_key,
        department_name=current_user.department_name,
        created_by=current_user.username,
        description=request.description
    )
    
    if not result.get("success"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=result.get("error", "Failed to create access key")
        )
    
    log.info(f"User {current_user.email} created access key '{request.access_key}' in department '{current_user.department_name}'")
    
    return AccessKeyDefinition(
        access_key=result["access_key"],
        department_name=result["department_name"],
        created_by=result["created_by"],
        created_at=result["created_at"],
        description=result.get("description")
    )


@router.get("/access-keys/{access_key}", response_model=AccessKeyDefinition)
async def get_access_key_details(
    access_key: str,
    current_user: User = Depends(get_current_user),
    authorization_service: AuthorizationService = Depends(ServiceProvider.get_authorization_service)
):
    """
    Get details of a specific access key.
    
    **Permission required** - read access on tools.
    
    Args:
        access_key: The access key to retrieve
        
    Returns:
        Access key definition
    """
    # Check permissions first - use user's department for department-wise permission check
    user_department = current_user.department_name 
    if not await authorization_service.check_operation_permission(current_user.email, current_user.role, "create", "tools", user_department):
        raise HTTPException(status_code=403, detail="You don't have permission to read access keys")
    repo = ServiceProvider.get_access_key_definitions_repository()
    result = await repo.get_access_key(access_key, department_name=current_user.department_name)
    
    if not result:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Access key '{access_key}' not found in your department"
        )
    
    return AccessKeyDefinition(
        access_key=result["access_key"],
        department_name=result["department_name"],
        created_by=result["created_by"],
        created_at=result["created_at"],
        description=result.get("description")
    )


@router.delete("/access-keys/{access_key}")
async def delete_access_key(
    access_key: str,
    current_user: User = Depends(get_current_user),
    authorization_service: AuthorizationService = Depends(ServiceProvider.get_authorization_service)
):
    """
    Delete an access key.
    
    **Permission required** - delete access on tools.
    **Creator only** - Only the user who created the access key can delete it.
    
    Args:
        access_key: The access key to delete
        
    Returns:
        Success message or error with details
    """
    # Check permissions first - use user's department for department-wise permission check
    user_department = current_user.department_name 
    if not await authorization_service.check_operation_permission(current_user.email, current_user.role, "create", "tools", user_department):
        raise HTTPException(status_code=403, detail="You don't have permission to delete access keys")
    repo = ServiceProvider.get_access_key_definitions_repository()
    
    # Check if access key exists in user's department
    key_definition = await repo.get_access_key(access_key, department_name=current_user.department_name)
    if not key_definition:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Access key '{access_key}' not found in your department"
        )
    
    # Check if user is the creator
    if key_definition["created_by"] != current_user.username:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Only the creator ({key_definition['created_by']}) can delete this access key"
        )
    
    # Check if any tools are using this access key
    tool_mapping_repo = ServiceProvider.get_tool_access_key_mapping_repository()
    tools_using_key = await tool_mapping_repo.get_tools_by_access_key(access_key, department_name=current_user.department_name)
    
    if tools_using_key:
        tool_names = [t["tool_name"] for t in tools_using_key]
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "message": f"Cannot delete access key '{access_key}' because it is being used by {len(tools_using_key)} tool(s): {tool_names}"
            }
        )
    
    # Delete the access key definition
    result = await repo.delete_access_key(access_key, department_name=current_user.department_name, requesting_user=current_user.username)
    
    if not result.get("success"):
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=result.get("error", "Failed to delete access key")
        )
    
    # Also delete all user access key entries for this access key
    user_access_repo = ServiceProvider.get_user_access_key_repository()
    deleted_user_entries = await user_access_repo.delete_all_for_access_key(access_key, department_name=current_user.department_name)
    
    log.info(f"User {current_user.email} deleted access key '{access_key}' (removed {deleted_user_entries} user entries)")
    
    return {
        "success": True,
        "message": f"Access key '{access_key}' deleted successfully",
        "deleted_user_entries": deleted_user_entries
    }


# ─────────────────────────────────────────────────────────────────────────────
# TOOL-ACCESS KEY RELATIONSHIP ENDPOINTS
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/access-keys/{access_key}/tools", response_model=ToolsByAccessKeyResponse)
async def get_tools_by_access_key(
    access_key: str,
    current_user: User = Depends(get_current_user),
    authorization_service: AuthorizationService = Depends(ServiceProvider.get_authorization_service)
):
    """
    Get all tools that require a specific access key.
    
    **Permission required** - read access on tools.
    
    This is useful for understanding what resources/tools are protected by a given access key.
    
    Args:
        access_key: The access key to look up
        
    Returns:
        List of tools that require this access key
    """
    # Check permissions first - use user's department for department-wise permission check
    user_department = current_user.department_name 
    if not await authorization_service.check_operation_permission(current_user.email, current_user.role, "create", "tools", user_department):
        raise HTTPException(status_code=403, detail="You don't have permission to read tools")
    tool_mapping_repo = ServiceProvider.get_tool_access_key_mapping_repository()
    tools = await tool_mapping_repo.get_tools_by_access_key(access_key, department_name=current_user.department_name)
    
    return ToolsByAccessKeyResponse(
        access_key=access_key,
        total_tools=len(tools),
        tools=[
            ToolInfo(
                tool_id=t["tool_id"],
                tool_name=t["tool_name"],
                access_keys=t["access_keys"]
            )
            for t in tools
        ]
    )


# ─────────────────────────────────────────────────────────────────────────────
# USER VALUES ENDPOINTS
# ─────────────────────────────────────────────────────────────────────────────

@router.put("/access-keys/{access_key}/my-access")
async def update_my_access_for_key(
    access_key: str,
    request: UpdateMyAccessRequest,
    current_user: User = Depends(get_current_user),
    authorization_service: AuthorizationService = Depends(ServiceProvider.get_authorization_service)
):
    """
    **UNIFIED ENDPOINT** - Update both allowed values and exclusions for an access key.
    
    **Permission required** - update access on tools.
    
    Request body supports:
    - **add_values**: List of values to add to allowed list
    - **remove_values**: List of values to remove from allowed list
    - **add_exclusions**: List of values to add to exclusion list (these take priority)
    - **remove_exclusions**: List of values to remove from exclusion list
    
    Example: Grant access to all employees except executives:
    ```json
    {
        "add_values": ["*"],
        "add_exclusions": ["CEO001", "CFO001"]
    }
    ```
    
    Args:
        access_key: The access key to update
        request: Contains any combination of add_values, remove_values, add_exclusions, remove_exclusions
        
    Returns:
        Success message with updated allowed and excluded values
    """
    # Check permissions first - use user's department for department-wise permission check
    user_department = current_user.department_name 
    if not await authorization_service.check_operation_permission(current_user.email, current_user.role, "create", "tools", user_department):
        raise HTTPException(status_code=403, detail="You don't have permission to update access keys")
    
    # Check if the access key exists in user's department
    access_key_repo = ServiceProvider.get_access_key_definitions_repository()
    key_definition = await access_key_repo.get_access_key(access_key, department_name=current_user.department_name)
    
    if not key_definition:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Access key '{access_key}' not found in your department"
        )
    
    user_access_repo = ServiceProvider.get_user_access_key_repository()
    
    # Get current state for validation
    current_access_keys = await user_access_repo.get_user_access_keys(current_user.email, department_name=current_user.department_name)
    current_allowed_values = current_access_keys.get(access_key, [])
    
    # Calculate what values will remain after remove_values is processed
    values_being_removed = request.remove_values or []
    remaining_values_after_removal = [v for v in current_allowed_values if v not in values_being_removed]
    
    # Validation: Check if allowed_values has * for exclusion operations
    # Exclusions can only be added if allowed_values contains "*"
    if request.add_exclusions:
        # Check if * is currently in allowed values (after removals) or will be added
        will_have_wildcard = "*" in remaining_values_after_removal or (request.add_values and "*" in request.add_values)
        if not will_have_wildcard:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Exclusions can only be added when allowed_values contains '*'. Add '*' to allowed_values first."
            )
    
    # Validation: If * is in allowed_values or being added, no other values should be allowed
    if request.add_values:
        if "*" in request.add_values:
            # If adding *, ensure no other values are being added
            other_values = [v for v in request.add_values if v != "*"]
            if other_values:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"When using '*' (wildcard) in allowed_values, no other values can be added. Remove: {other_values}"
                )
            # If * is being added and there are existing non-* values that won't be removed, reject
            existing_non_wildcard = [v for v in remaining_values_after_removal if v != "*"]
            if existing_non_wildcard:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Cannot add '*' when other allowed values exist: {existing_non_wildcard}. Remove them first."
                )
        else:
            # If not adding *, but * already exists (and won't be removed), reject new values
            if "*" in remaining_values_after_removal:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Cannot add specific values when '*' (wildcard) is already in allowed_values. Use exclusions instead or remove '*' first."
                )
    
    # Initialize response tracking
    added_values = []
    removed_values = []
    added_exclusions = []
    removed_exclusions = []
    messages = []
    
    # IMPORTANT: Process operations in the correct order for consistency:
    # 1. remove_exclusions first (so * can be removed if exclusions are cleared)
    # 2. remove_values (so * can be added after existing values are removed)
    # 3. add_values (now safe to add *)
    # 4. add_exclusions (now safe since * exists)
    
    # Handle remove_exclusions FIRST
    if request.remove_exclusions:
        user_exclusions = await user_access_repo.get_user_excluded_values(current_user.email, department_name=current_user.department_name)
        current_exclusions = user_exclusions.get(access_key, [])
        
        for value in request.remove_exclusions:
            if value in current_exclusions:
                success = await user_access_repo.remove_excluded_value(
                    user_id=current_user.email,
                    access_key=access_key,
                    value=value,
                    department_name=current_user.department_name
                )
                if success:
                    removed_exclusions.append(value)
                    current_exclusions = [v for v in current_exclusions if v != value]
        
        if removed_exclusions:
            messages.append(f"Removed {len(removed_exclusions)} exclusion(s)")
            log.info(f"User {current_user.email} removed exclusions {removed_exclusions} from access key '{access_key}'")
    
    # Handle remove_values SECOND
    if request.remove_values:
        # Validation: If removing *, check if there are exclusions that would become invalid
        if "*" in request.remove_values:
            # Get current exclusions, but account for exclusions already removed in this request
            current_exclusions_check = await user_access_repo.get_user_excluded_values(current_user.email, department_name=current_user.department_name)
            existing_exclusions = current_exclusions_check.get(access_key, [])
            # Filter out exclusions that were just removed in this request
            remaining_exclusions = [e for e in existing_exclusions if e not in removed_exclusions]
            if remaining_exclusions:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Cannot remove '*' from allowed_values while exclusions exist: {remaining_exclusions}. Remove exclusions first."
                )
        
        user_access_keys = await user_access_repo.get_user_access_keys(current_user.email, department_name=current_user.department_name)
        current_values = user_access_keys.get(access_key, [])
        
        for value in request.remove_values:
            if value in current_values:
                success = await user_access_repo.remove_value_from_access_key(
                    user_id=current_user.email,
                    access_key=access_key,
                    value=value,
                    department_name=current_user.department_name
                )
                if success:
                    removed_values.append(value)
                    current_values = [v for v in current_values if v != value]
        
        if removed_values:
            messages.append(f"Removed {len(removed_values)} allowed value(s)")
            log.info(f"User {current_user.email} removed values {removed_values} from access key '{access_key}'")
    
    # Handle add_values THIRD
    if request.add_values:
        for value in request.add_values:
            success = await user_access_repo.add_value_to_access_key(
                user_id=current_user.email,
                access_key=access_key,
                value=value,
                assigned_by=current_user.email,
                department_name=current_user.department_name
            )
            if success:
                added_values.append(value)
        
        if added_values:
            messages.append(f"Added {len(added_values)} allowed value(s)")
            log.info(f"User {current_user.email} added values {added_values} to access key '{access_key}'")
    
    # Handle add_exclusions FOURTH
    if request.add_exclusions:
        for value in request.add_exclusions:
            success = await user_access_repo.add_excluded_value(
                user_id=current_user.email,
                access_key=access_key,
                value=value,
                assigned_by=current_user.email,
                department_name=current_user.department_name
            )
            if success:
                added_exclusions.append(value)
        
        if added_exclusions:
            messages.append(f"Added {len(added_exclusions)} exclusion(s)")
            log.info(f"User {current_user.email} added exclusions {added_exclusions} to access key '{access_key}'")
    
    # Check if any operations were requested
    if not any([request.add_values, request.remove_values, request.add_exclusions, request.remove_exclusions]):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No update operations specified. Provide at least one of: add_values, remove_values, add_exclusions, remove_exclusions."
        )
    
    # Get final state
    user_access_keys = await user_access_repo.get_user_access_keys(current_user.email, department_name=current_user.department_name)
    user_exclusions = await user_access_repo.get_user_excluded_values(current_user.email, department_name=current_user.department_name)
    final_values = user_access_keys.get(access_key, [])
    final_exclusions = user_exclusions.get(access_key, [])
    
    return {
        "success": True,
        "message": f"Access key '{access_key}' updated. " + "; ".join(messages) if messages else "No changes made.",
        "user_id": current_user.email,
        "access_key": access_key,
        "added_values": added_values if added_values else None,
        "removed_values": removed_values if removed_values else None,
        "added_exclusions": added_exclusions if added_exclusions else None,
        "removed_exclusions": removed_exclusions if removed_exclusions else None,
        "allowed_values": final_values,
        "excluded_values": final_exclusions
    }


@router.get("/access-keys/{access_key}/my-access/full", response_model=MyAccessKeyFullResponse)
async def get_my_full_access_for_key(
    access_key: str,
    current_user: User = Depends(get_current_user),
    authorization_service: AuthorizationService = Depends(ServiceProvider.get_authorization_service)
):
    """
    Get both allowed and excluded values for a specific access key.
    
    **Permission required** - read access on tools.
    
    This gives a complete picture of what the user can and cannot access
    for a given access key.
    
    Args:
        access_key: The access key to check
        
    Returns:
        Both allowed_values and excluded_values for this access key
    """
    # Check permissions first - use user's department for department-wise permission check
    user_department = current_user.department_name 
    if not await authorization_service.check_operation_permission(current_user.email, current_user.role, "create", "tools", user_department):
        raise HTTPException(status_code=403, detail="You don't have permission to read access keys")
    user_access_repo = ServiceProvider.get_user_access_key_repository()
    full_access = await user_access_repo.get_user_access_keys_full(current_user.email, department_name=current_user.department_name)
    
    access_data = full_access.get(access_key, {"allowed": [], "excluded": []})
    
    return MyAccessKeyFullResponse(
        user_id=current_user.email,
        access_key=access_key,
        allowed_values=access_data.get("allowed", []),
        excluded_values=access_data.get("excluded", [])
    )


@router.get("/my-access-keys")
async def get_all_my_access_keys(
    current_user: User = Depends(get_current_user),
    authorization_service: AuthorizationService = Depends(ServiceProvider.get_authorization_service)
):
    """
    Get all access keys and values assigned to the current user.
    
    **Permission required** - read access on tools.
    
    Returns:
        Dict mapping each access key to its allowed values for this user
    """
    # Check permissions first - use user's department for department-wise permission check
    user_department = current_user.department_name 
    if not await authorization_service.check_operation_permission(current_user.email, current_user.role, "create", "tools", user_department):
        raise HTTPException(status_code=403, detail="You don't have permission to read access keys")
    user_access_repo = ServiceProvider.get_user_access_key_repository()
    access_keys = await user_access_repo.get_user_access_keys(current_user.email, department_name=current_user.department_name)
    
    return {
        "user_id": current_user.email,
        "access_keys": access_keys,
        "total_keys": len(access_keys)
    }


@router.get("/my-access-keys/full")
async def get_all_my_access_keys_full(
    current_user: User = Depends(get_current_user),
    authorization_service: AuthorizationService = Depends(ServiceProvider.get_authorization_service)
):
    """
    Get all access keys with both allowed and excluded values for the current user.
    
    **Permission required** - read access on tools.
    
    Returns:
        Dict mapping each access key to {allowed: [...], excluded: [...]}
    """
    # Check permissions first - use user's department for department-wise permission check
    user_department = current_user.department_name 
    if not await authorization_service.check_operation_permission(current_user.email, current_user.role, "create", "tools", user_department):
        raise HTTPException(status_code=403, detail="You don't have permission to read access keys")
    user_access_repo = ServiceProvider.get_user_access_key_repository()
    full_access = await user_access_repo.get_user_access_keys_full(current_user.email, department_name=current_user.department_name)
    
    return {
        "user_id": current_user.email,
        "access_keys": full_access,
        "total_keys": len(full_access)
    }

 