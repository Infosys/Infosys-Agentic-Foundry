# © 2024-25 Infosys Limited, Bangalore, India. All Rights Reserved.
"""
Resource Allocation Management Endpoints

This module provides API endpoints for Resource Allocation Management, allowing
department admins to:
- View access keys in their department
- View users in their department (for assigning access key values)
- Assign access key values to users in their department
- Delete access keys (with tool usage check)

**Admin Only** - All endpoints require Admin or SuperAdmin role.
"""

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from typing import List, Optional
from src.auth.models import User, UserRole
from src.auth.dependencies import get_current_user
from src.api.dependencies import ServiceProvider
from telemetry_wrapper import logger as log

router = APIRouter(prefix="/resource-allocation", tags=["Resource Allocation Management"])


# ─────────────────────────────────────────────────────────────────────────────
# HELPER FUNCTIONS
# ─────────────────────────────────────────────────────────────────────────────

def require_admin(current_user: User):
    """Check if user is Admin or SuperAdmin"""
    if current_user.role not in [UserRole.ADMIN.value, UserRole.SUPER_ADMIN.value, "Admin", "SuperAdmin"]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied. Only department admins can access Resource Allocation Management."
        )


# ─────────────────────────────────────────────────────────────────────────────
# REQUEST/RESPONSE MODELS
# ─────────────────────────────────────────────────────────────────────────────

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


class ToolUsingAccessKey(BaseModel):
    """Response model for tool using an access key"""
    tool_id: str
    tool_name: str


class DeleteAccessKeyResponse(BaseModel):
    """Response model for delete access key operation"""
    success: bool
    message: str
    tools_using_key: Optional[List[ToolUsingAccessKey]] = None


class UserAccessKeyValues(BaseModel):
    """Response model for a user's access key values"""
    user_email: str
    user_name: Optional[str] = None
    allowed_values: List[str]
    excluded_values: List[str] = []


class AccessKeyUsersResponse(BaseModel):
    """Response model for listing users with values for an access key"""
    access_key: str
    department_name: str
    total_users: int
    users: List[UserAccessKeyValues]


class BulkAssignValuesRequest(BaseModel):
    """Request model for assigning values to multiple users at once"""
    user_emails: List[str] = Field(..., description="List of user emails to assign values to")
    add_values: Optional[List[str]] = Field(None, description="List of values to add to users")


class UpdateUserAccessRequest(BaseModel):
    """Unified request model for updating a user's access - both allowed values and exclusions"""
    add_values: Optional[List[str]] = Field(None, description="List of values to add to allowed list")
    remove_values: Optional[List[str]] = Field(None, description="List of values to remove from allowed list")
    add_exclusions: Optional[List[str]] = Field(None, description="List of values to add to exclusion list")
    remove_exclusions: Optional[List[str]] = Field(None, description="List of values to remove from exclusion list")


class UpdateAccessKeyUsersRequest(BaseModel):
    """Request model for adding/removing users from an access key"""
    add_users: Optional[List[str]] = Field(None, description="List of user emails to add to this access key")
    remove_users: Optional[List[str]] = Field(None, description="List of user emails to remove from this access key")

# ─────────────────────────────────────────────────────────────────────────────
# ACCESS KEY MANAGEMENT ENDPOINTS (ADMIN ONLY)
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/access-keys", response_model=AccessKeyListResponse)
async def list_access_keys_in_department(
    current_user: User = Depends(get_current_user)
):
    """
    List all access keys in the admin's department.
    
    **Admin Only** - Requires Admin or SuperAdmin role.
    
    Returns:
        List of access keys with their definitions
    """
    require_admin(current_user)
    
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

@router.get("/access-keys/{access_key}/users", response_model=AccessKeyUsersResponse)
async def get_users_with_access_key(
    access_key: str,
    current_user: User = Depends(get_current_user)
):
    """
    Get all users who have a specific access key.
    
    **Admin Only** - Requires Admin or SuperAdmin role.
    
    Args:
        access_key: The access key to look up
        
    Returns:
        List of users with their assigned values for this access key
    """
    require_admin(current_user)
    
    # Check if access key exists in admin's department
    access_key_repo = ServiceProvider.get_access_key_definitions_repository()
    key_definition = await access_key_repo.get_access_key(access_key, department_name=current_user.department_name)
    
    if not key_definition:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Access key '{access_key}' not found in your department"
        )
    
    # Get users who have this access key directly from repository
    user_access_repo = ServiceProvider.get_user_access_key_repository()
    users_data = await user_access_repo.get_users_with_access_key(access_key, department_name=current_user.department_name)
    
    users_with_values = [
        UserAccessKeyValues(
            user_email=user["user_id"],
            allowed_values=list(user.get("allowed_values", [])),
            excluded_values=list(user.get("excluded_values", []))
        )
        for user in users_data
    ]
    
    return AccessKeyUsersResponse(
        access_key=access_key,
        department_name=current_user.department_name,
        total_users=len(users_with_values),
        users=users_with_values
    )


@router.get("/access-keys/{access_key}/users/{user_email}")
async def get_user_values_for_access_key(
    access_key: str,
    user_email: str,
    current_user: User = Depends(get_current_user)
):
    """
    Get a specific user's values for an access key.
    
    **Admin Only** - Requires Admin or SuperAdmin role.
    
    Use this when clicking "Edit" button on a user to see their current values.
    
    Args:
        access_key: The access key to look up
        user_email: The user's email
        
    Returns:
        User's allowed values for this access key
    """
    require_admin(current_user)
    
    # Check if access key exists in admin's department
    access_key_repo = ServiceProvider.get_access_key_definitions_repository()
    key_definition = await access_key_repo.get_access_key(access_key, department_name=current_user.department_name)
    
    if not key_definition:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Access key '{access_key}' not found in your department"
        )
    
    # Verify user is in admin's department
    user_dept_mapping_repo = ServiceProvider.get_user_department_mapping_repository()
    is_in_department = await user_dept_mapping_repo.check_user_in_department(
        user_email, 
        current_user.department_name
    )
    
    if not is_in_department:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"User '{user_email}' is not in your department."
        )
    
    # Get user's values for this access key
    user_access_repo = ServiceProvider.get_user_access_key_repository()
    user_access_keys = await user_access_repo.get_user_access_keys(user_email, department_name=current_user.department_name)
    user_exclusions = await user_access_repo.get_user_excluded_values(user_email, department_name=current_user.department_name)
    values = user_access_keys.get(access_key, [])
    exclusions = user_exclusions.get(access_key, [])
    
    return {
        "user_email": user_email,
        "access_key": access_key,
        "allowed_values": values,
        "excluded_values": exclusions,
        "has_access": access_key in user_access_keys
    }


# ─────────────────────────────────────────────────────────────────────────────
# UNIFIED USER ACCESS UPDATE ENDPOINT (ADMIN ONLY)
# ─────────────────────────────────────────────────────────────────────────────

@router.put("/access-keys/{access_key}/users/{user_email}/access")
async def update_user_access(
    access_key: str,
    user_email: str,
    request: UpdateUserAccessRequest,
    current_user: User = Depends(get_current_user)
):
    """
    **UNIFIED ENDPOINT** - Update both allowed values and exclusions for a user.
    
    **Admin Only** - Requires Admin or SuperAdmin role.
    
    Request body supports:
    - **add_values**: List of values to add to allowed list
    - **remove_values**: List of values to remove from allowed list
    - **add_exclusions**: List of values to add to exclusion list (these take priority)
    - **remove_exclusions**: List of values to remove from exclusion list
    
    Example: Grant user access to all employees except executives:
    ```json
    {
        "add_values": ["*"],
        "add_exclusions": ["CEO001", "CFO001"]
    }
    ```
    
    Args:
        access_key: The access key to update
        user_email: The user's email
        request: Contains any combination of add_values, remove_values, add_exclusions, remove_exclusions
        
    Returns:
        Success message with updated allowed and excluded values
    """
    require_admin(current_user)
    
    # Check if access key exists in admin's department
    access_key_repo = ServiceProvider.get_access_key_definitions_repository()
    key_definition = await access_key_repo.get_access_key(access_key, department_name=current_user.department_name)
    
    if not key_definition:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Access key '{access_key}' not found in your department"
        )
    
    # Verify user is in admin's department
    user_dept_mapping_repo = ServiceProvider.get_user_department_mapping_repository()
    is_in_department = await user_dept_mapping_repo.check_user_in_department(
        user_email, 
        current_user.department_name
    )
    
    if not is_in_department:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"User '{user_email}' is not in your department."
        )
    
    user_access_repo = ServiceProvider.get_user_access_key_repository()
    
    # Get current state for validation
    current_access_keys = await user_access_repo.get_user_access_keys(user_email, department_name=current_user.department_name)
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
        user_exclusions = await user_access_repo.get_user_excluded_values(user_email, department_name=current_user.department_name)
        current_exclusions = user_exclusions.get(access_key, [])
        
        for value in request.remove_exclusions:
            if value in current_exclusions:
                success = await user_access_repo.remove_excluded_value(
                    user_id=user_email,
                    access_key=access_key,
                    value=value,
                    department_name=current_user.department_name
                )
                if success:
                    removed_exclusions.append(value)
                    current_exclusions = [v for v in current_exclusions if v != value]
        
        if removed_exclusions:
            messages.append(f"Removed {len(removed_exclusions)} exclusion(s)")
            log.info(f"Admin {current_user.email} removed exclusions {removed_exclusions} from user {user_email} for access key '{access_key}'")
    
    # Handle remove_values SECOND
    if request.remove_values:
        # Validation: If removing *, check if there are exclusions that would become invalid
        if "*" in request.remove_values:
            # Get current exclusions, but account for exclusions already removed in this request
            current_exclusions_check = await user_access_repo.get_user_excluded_values(user_email, department_name=current_user.department_name)
            existing_exclusions = current_exclusions_check.get(access_key, [])
            # Filter out exclusions that were just removed in this request
            remaining_exclusions = [e for e in existing_exclusions if e not in removed_exclusions]
            if remaining_exclusions:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Cannot remove '*' from allowed_values while exclusions exist: {remaining_exclusions}. Remove exclusions first."
                )
        
        user_access_keys = await user_access_repo.get_user_access_keys(user_email, department_name=current_user.department_name)
        current_values = user_access_keys.get(access_key, [])
        
        for value in request.remove_values:
            if value in current_values:
                success = await user_access_repo.remove_value_from_access_key(
                    user_id=user_email,
                    access_key=access_key,
                    value=value,
                    department_name=current_user.department_name
                )
                if success:
                    removed_values.append(value)
                    current_values = [v for v in current_values if v != value]
        
        if removed_values:
            messages.append(f"Removed {len(removed_values)} allowed value(s)")
            log.info(f"Admin {current_user.email} removed values {removed_values} from user {user_email} for access key '{access_key}'")
    
    # Handle add_values THIRD
    if request.add_values:
        for value in request.add_values:
            success = await user_access_repo.add_value_to_access_key(
                user_id=user_email,
                access_key=access_key,
                value=value,
                assigned_by=current_user.email,
                department_name=current_user.department_name
            )
            if success:
                added_values.append(value)
        
        if added_values:
            messages.append(f"Added {len(added_values)} allowed value(s)")
            log.info(f"Admin {current_user.email} added values {added_values} to user {user_email} for access key '{access_key}'")
    
    # Handle add_exclusions FOURTH
    if request.add_exclusions:
        for value in request.add_exclusions:
            success = await user_access_repo.add_excluded_value(
                user_id=user_email,
                access_key=access_key,
                value=value,
                assigned_by=current_user.email,
                department_name=current_user.department_name
            )
            if success:
                added_exclusions.append(value)
        
        if added_exclusions:
            messages.append(f"Added {len(added_exclusions)} exclusion(s)")
            log.info(f"Admin {current_user.email} added exclusions {added_exclusions} to user {user_email} for access key '{access_key}'")
    
    # Check if any operations were requested
    if not any([request.add_values, request.remove_values, request.add_exclusions, request.remove_exclusions]):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No update operations specified. Provide at least one of: add_values, remove_values, add_exclusions, remove_exclusions."
        )
    
    # Get final state
    user_access_keys = await user_access_repo.get_user_access_keys(user_email, department_name=current_user.department_name)
    user_exclusions = await user_access_repo.get_user_excluded_values(user_email, department_name=current_user.department_name)
    final_values = user_access_keys.get(access_key, [])
    final_exclusions = user_exclusions.get(access_key, [])
    
    return {
        "success": True,
        "message": f"User '{user_email}' access for '{access_key}' updated. " + "; ".join(messages) if messages else "No changes made.",
        "user_email": user_email,
        "access_key": access_key,
        "added_values": added_values if added_values else None,
        "removed_values": removed_values if removed_values else None,
        "added_exclusions": added_exclusions if added_exclusions else None,
        "removed_exclusions": removed_exclusions if removed_exclusions else None,
        "allowed_values": final_values,
        "excluded_values": final_exclusions
    }


# ─────────────────────────────────────────────────────────────────────────────
# BULK AND USER MANAGEMENT ENDPOINTS (ADMIN ONLY)
# ─────────────────────────────────────────────────────────────────────────────

@router.put("/access-keys/{access_key}/users")
async def update_access_key_users(
    access_key: str,
    request: UpdateAccessKeyUsersRequest,
    current_user: User = Depends(get_current_user)
):
    """
    Add or remove users from an access key.
    
    **Admin Only** - Requires Admin or SuperAdmin role.
    
    Request body supports:
    - **add_users**: List of user emails to add to this access key
    - **remove_users**: List of user emails to remove from this access key
    - **default_values**: Optional values to assign when adding users (defaults to empty list)
    
    Args:
        access_key: The access key to update
        request: Contains add_users and/or remove_users lists
        
    Returns:
        Summary of added/removed users
    """
    require_admin(current_user)
    
    # Check if access key exists in admin's department
    access_key_repo = ServiceProvider.get_access_key_definitions_repository()
    key_definition = await access_key_repo.get_access_key(access_key, department_name=current_user.department_name)
    
    if not key_definition:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Access key '{access_key}' not found in your department"
        )
    
    if not request.add_users and not request.remove_users:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Provide add_users and/or remove_users"
        )
    
    user_dept_mapping_repo = ServiceProvider.get_user_department_mapping_repository()
    user_access_repo = ServiceProvider.get_user_access_key_repository()
    
    added_users = []
    removed_users = []
    not_in_department = []
    failed_users = []
    messages = []
    
    # Handle add_users
    if request.add_users:
        default_values = []
        for user_email in request.add_users:
            # Verify user is in admin's department
            is_in_department = await user_dept_mapping_repo.check_user_in_department(
                user_email, 
                current_user.department_name
            )
            
            if not is_in_department:
                not_in_department.append(user_email)
                continue
            
            try:
                success = await user_access_repo.set_user_access_key(
                    user_id=user_email,
                    access_key=access_key,
                    allowed_values=default_values,
                    assigned_by=current_user.email,
                    department_name=current_user.department_name
                )
                if success:
                    added_users.append(user_email)
                else:
                    failed_users.append(user_email)
            except Exception as e:
                log.error(f"Failed to add user {user_email} to access key: {str(e)}")
                failed_users.append(user_email)
        
        if added_users:
            messages.append(f"Added {len(added_users)} user(s)")
            log.info(f"Admin {current_user.email} added users {added_users} to access key '{access_key}'")
    
    # Handle remove_users
    if request.remove_users:
        for user_email in request.remove_users:
            # Verify user is in admin's department
            is_in_department = await user_dept_mapping_repo.check_user_in_department(
                user_email, 
                current_user.department_name
            )
            
            if not is_in_department:
                not_in_department.append(user_email)
                continue
            
            try:
                # Delete the access key row entirely for this user
                success = await user_access_repo.delete_access_key(
                    user_id=user_email,
                    access_key=access_key,
                    department_name=current_user.department_name
                )
                if success:
                    removed_users.append(user_email)
                else:
                    failed_users.append(user_email)
            except Exception as e:
                log.error(f"Failed to remove user {user_email} from access key: {str(e)}")
                failed_users.append(user_email)
        
        if removed_users:
            messages.append(f"Removed {len(removed_users)} user(s)")
            log.info(f"Admin {current_user.email} removed users {removed_users} from access key '{access_key}'")
    
    if not any([added_users, removed_users]):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"No users were updated. Users not in department: {not_in_department}. Failed: {failed_users}"
        )
    
    return {
        "success": True,
        "message": f"Access key '{access_key}' updated. " + "; ".join(messages),
        "access_key": access_key,
        "added_users": added_users if added_users else None,
        "removed_users": removed_users if removed_users else None,
        "users_not_in_department": not_in_department if not_in_department else None,
        "failed_users": failed_users if failed_users else None
    }


@router.post("/access-keys/{access_key}/bulk-assign")
async def bulk_assign_values_to_users(
    access_key: str,
    request: BulkAssignValuesRequest,
    current_user: User = Depends(get_current_user)
):
    """
    Assign access key values to multiple users at once.
    
    **Admin Only** - Requires Admin or SuperAdmin role.
    
    Request body supports:
    - **user_emails**: List of users to assign values to
    - **add_values**: Values to add to each user's existing values
    - **set_values**: Values to set for each user (replaces existing). If provided, add_values is ignored.
    
    Args:
        access_key: The access key to assign values for
        request: Contains user_emails and values to assign
        
    Returns:
        Summary of assignments with success/failure per user
    """
    require_admin(current_user)
    
    # Check if access key exists in admin's department
    access_key_repo = ServiceProvider.get_access_key_definitions_repository()
    key_definition = await access_key_repo.get_access_key(access_key, department_name=current_user.department_name)
    
    if not key_definition:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Access key '{access_key}' not found in your department"
        )
    
    if not request.user_emails:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="user_emails list cannot be empty"
        )
    
    if request.add_values is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Provide add_values"
        )
    
    # Validation: If * is in add_values, no other values should be allowed
    if "*" in request.add_values:
        other_values = [v for v in request.add_values if v != "*"]
        if other_values:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"When using '*' (wildcard) in add_values, no other values can be added. Remove: {other_values}"
            )
    
    user_dept_mapping_repo = ServiceProvider.get_user_department_mapping_repository()
    user_access_repo = ServiceProvider.get_user_access_key_repository()
    
    successful_users = []
    failed_users = []
    not_in_department = []
    skipped_wildcard_conflict = []
    
    for user_email in request.user_emails:
        # Verify user is in admin's department
        is_in_department = await user_dept_mapping_repo.check_user_in_department(
            user_email, 
            current_user.department_name
        )
        
        if not is_in_department:
            not_in_department.append(user_email)
            continue
        
        try:
            # Get user's current allowed values for validation
            user_access_keys = await user_access_repo.get_user_access_keys(user_email, department_name=current_user.department_name)
            current_allowed_values = user_access_keys.get(access_key, [])
            
            # Validation: Check wildcard conflicts per user
            if "*" in request.add_values:
                # If adding *, check if user has existing non-* values
                existing_non_wildcard = [v for v in current_allowed_values if v != "*"]
                if existing_non_wildcard:
                    skipped_wildcard_conflict.append({
                        "user": user_email,
                        "reason": f"Cannot add '*' - user has existing values: {existing_non_wildcard}"
                    })
                    continue
            else:
                # If not adding *, but user already has *, skip this user
                if "*" in current_allowed_values:
                    skipped_wildcard_conflict.append({
                        "user": user_email,
                        "reason": "Cannot add specific values when '*' is already in allowed_values"
                    })
                    continue
            
            # Add values to existing
            success = True
            for value in request.add_values:
                result = await user_access_repo.add_value_to_access_key(
                    user_id=user_email,
                    access_key=access_key,
                    value=value,
                    assigned_by=current_user.email,
                    department_name=current_user.department_name
                )
                if not result:
                    success = False
            
            if success:
                successful_users.append(user_email)
            else:
                failed_users.append(user_email)
        except Exception as e:
            log.error(f"Failed to assign values to user {user_email}: {str(e)}")
            failed_users.append(user_email)
    
    values_assigned = request.add_values
    
    log.info(f"Admin {current_user.email} bulk assigned values to {len(successful_users)} users for access key '{access_key}'")
    
    return {
        "success": len(successful_users) > 0,
        "access_key": access_key,
        "values": values_assigned,
        "successful_users": successful_users,
        "failed_users": failed_users,
        "users_not_in_department": not_in_department,
        "skipped_wildcard_conflicts": skipped_wildcard_conflict if skipped_wildcard_conflict else None,
        "message": f"Assigned values to {len(successful_users)} user(s). {len(failed_users)} failed. {len(not_in_department)} not in department. {len(skipped_wildcard_conflict)} skipped due to wildcard conflicts."
    }


@router.delete("/access-keys/{access_key}", response_model=DeleteAccessKeyResponse)
async def delete_access_key(
    access_key: str,
    current_user: User = Depends(get_current_user)
):
    """
    Delete an access key from the department.
    
    **Admin Only** - Requires Admin or SuperAdmin role.
    
    Before deleting, this endpoint checks if any tools are using this access key.
    If tools are using it, an error is returned with the list of tools.
    Use force=true to delete anyway (will leave tools with orphaned access key references).
    
    Args:
        access_key: The access key to delete
        force: If true, delete even if tools are using this access key
        
    Returns:
        Success status or error with list of tools using this access key
    """
    require_admin(current_user)
    
    # Check if access key exists in admin's department
    access_key_repo = ServiceProvider.get_access_key_definitions_repository()
    key_definition = await access_key_repo.get_access_key(access_key, department_name=current_user.department_name)
    
    if not key_definition:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Access key '{access_key}' not found in your department"
        )
    
    # Check if any tools are using this access key
    tool_mapping_repo = ServiceProvider.get_tool_access_key_mapping_repository()
    tools_using_key = await tool_mapping_repo.get_tools_by_access_key(access_key, department_name=current_user.department_name)
    
    if tools_using_key:
        tool_list = [
            ToolUsingAccessKey(tool_id=t["tool_id"], tool_name=t["tool_name"])
            for t in tools_using_key
        ]
        return DeleteAccessKeyResponse(
            success=False,
            message=f"Cannot delete access key '{access_key}' because it is being used by {len(tools_using_key)} tool(s). Use force=true to delete anyway.",
            tools_using_key=tool_list
        )
        
    
    # Delete the access key definition
    result = await access_key_repo.delete_access_key(access_key, department_name=current_user.department_name, requesting_user=current_user.email)
    
    if not result.get("success"):
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=result.get("error", "Failed to delete access key")
        )
    
    # Also delete all user access key entries for this access key
    user_access_repo = ServiceProvider.get_user_access_key_repository()
    deleted_user_entries = await user_access_repo.delete_all_for_access_key(access_key, department_name=current_user.department_name)
    
    log.info(f"Admin {current_user.email} deleted access key '{access_key}' from department '{current_user.department_name}' (removed {deleted_user_entries} user entries)")
    
    return DeleteAccessKeyResponse(
        success=True,
        message=f"Access key '{access_key}' deleted successfully (removed {deleted_user_entries} user entries)",
        tools_using_key=None
    )


@router.delete("/access-keys/{access_key}/users/{user_email}")
async def remove_user_access_key_values(
    access_key: str,
    user_email: str,
    current_user: User = Depends(get_current_user)
):
    """
    Remove all values for a user's access key (revoke access completely).
    
    **Admin Only** - Requires Admin or SuperAdmin role.
    
    This removes the user's access to all resources controlled by this access key.
    
    Args:
        access_key: The access key to remove values from
        user_email: The user's email
        
    Returns:
        Success status
    """
    require_admin(current_user)
    
    # Verify user is in admin's department
    user_dept_mapping_repo = ServiceProvider.get_user_department_mapping_repository()
    is_in_department = await user_dept_mapping_repo.check_user_in_department(
        user_email, 
        current_user.department_name
    )
    
    if not is_in_department:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"User '{user_email}' is not in your department. You can only manage values for users in your department."
        )
    
    # Delete the user's access key record entirely from the database
    user_access_repo = ServiceProvider.get_user_access_key_repository()
    success = await user_access_repo.delete_access_key(
        user_id=user_email,
        access_key=access_key,
        department_name=current_user.department_name
    )
    
    if not success:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to remove user's access key record"
        )
    
    log.info(f"Admin {current_user.email} deleted access key record for user {user_email} on access key '{access_key}'")
    
    return {
        "success": True,
        "user_email": user_email,
        "access_key": access_key,
        "message": f"Successfully removed access key record for user '{user_email}' on access key '{access_key}'"
    }