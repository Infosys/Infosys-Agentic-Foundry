from fastapi import APIRouter, Depends, HTTPException, status
from typing import List, Optional
from pydantic import BaseModel

from src.auth.models import User, UserRole
from src.auth.dependencies import get_current_user
from src.auth.authorization_service import AuthorizationService
from src.api.dependencies import ServiceProvider
from src.database.services import GroupSecretsService

router = APIRouter(prefix="/groups", tags=["Group Keys"])

# --- Request/Response Models ---
class SecretCreateRequest(BaseModel):
    key_name: str
    secret_value: str

class SecretUpdateRequest(BaseModel):
    secret_value: str

class SecretResponse(BaseModel):
    key_name: str
    secret_value: str
    created_by: str
    created_at: str
    updated_at: Optional[str] = None

class SecretListResponse(BaseModel):
    key_name: str
    created_by: str
    created_at: str
    updated_at: Optional[str] = None

# --- Endpoints ---

@router.post("/{group_name}/secrets", response_model=SecretResponse, status_code=status.HTTP_201_CREATED)
async def create_group_secret(
    group_name: str,
    request: SecretCreateRequest,
    current_user: User = Depends(get_current_user),
    group_secrets_service: GroupSecretsService = Depends(ServiceProvider.get_group_secrets_service),
    authorization_service: AuthorizationService = Depends(ServiceProvider.get_authorization_service)
):
    """Create a new key for a group (Admin/Developer only). Department context is extracted from user data."""
    if current_user.role == UserRole.SUPER_ADMIN:
        raise HTTPException(status_code=403, detail="Superadmin is not allowed to create group secrets.")
    # Extract department from user data
    department_name = current_user.department_name 
    
    # Check vault access permission
    has_access = await authorization_service.check_vault_access(current_user.role, department_name)
    if not has_access:
        raise HTTPException(status_code=403, detail="Access denied: You don't have permission to access vault endpoints")
    
    try:
        response = await group_secrets_service.create_group_secret(
            group_name=group_name,
            department_name=department_name,
            key_name=request.key_name,
            secret_value=request.secret_value,
            user=current_user
        )
        
        # Check if the service returned an error
        if not response.get("success", False):
            # Map specific error types based on message content
            message = response.get("message", "Unknown error")
            if "does not exist" in message or "not found" in message:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=message)
            elif "does not have access" in message or "role:" in message:
                raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=message)
            elif "already exists" in message:
                raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=message)
            else:
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=message)
        
        # For create, we need to get the actual secret_record to return full details
        # Since create only returns status, we need to fetch the created secret_record
        get_response = await group_secrets_service.get_group_secret(
            group_name=group_name,
            department_name=department_name,
            key_name=request.key_name,
            user=current_user
        )
        
        if not get_response.get("success", False):
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, 
                              detail="Secret created but could not retrieve details")
        
        return SecretResponse(
            key_name=get_response["key_name"],
            secret_value=get_response["secret_value"],
            created_by=get_response["created_by"],
            created_at=get_response["created_at"].isoformat(),
            updated_at=get_response["updated_at"].isoformat() if get_response["updated_at"] else None
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))

@router.get("/{group_name}/secrets", response_model=List[SecretListResponse])
async def list_group_secrets(
    group_name: str,
    current_user: User = Depends(get_current_user),
    group_secrets_service: GroupSecretsService = Depends(ServiceProvider.get_group_secrets_service),
    authorization_service: AuthorizationService = Depends(ServiceProvider.get_authorization_service)
):
    """List all keys for a group (Group members only)"""
    # Extract department from user data
    department_name = current_user.department_name 
    
    # Check vault access permission
    has_access = await authorization_service.check_vault_access(current_user.role, department_name)
    if not has_access:
        raise HTTPException(status_code=403, detail="Access denied: You don't have permission to access vault endpoints")
    
    try:
        response = await group_secrets_service.list_group_secrets(
            group_name=group_name,
            department_name=department_name,
            user=current_user
            )
        
        # Check if the service returned an error
        if not response.get("success", False):
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=response.get("message", "Unknown error"))
        
        # Extract the secrets list from the response
        secrets = response.get("secrets", [])
        return [
            SecretListResponse(
                key_name=secret["key_name"],
                created_by=secret["created_by"],
                created_at=secret["created_at"].isoformat(),
                updated_at=secret["updated_at"].isoformat() if secret["updated_at"] else None
            )
            for secret in secrets
        ]
    except PermissionError as e:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))

@router.get("/{group_name}/secrets/{key_name}", response_model=SecretResponse)
async def get_group_secret(
    group_name: str,
    key_name: str,
    current_user: User = Depends(get_current_user),
    group_secrets_service: GroupSecretsService = Depends(ServiceProvider.get_group_secrets_service),
    authorization_service: AuthorizationService = Depends(ServiceProvider.get_authorization_service)
):
    """Get a specific key from a group (Group members only)"""
    # Extract department from user data
    department_name = current_user.department_name 
    
    # Check vault access permission
    has_access = await authorization_service.check_vault_access(current_user.role, department_name)
    if not has_access:
        raise HTTPException(status_code=403, detail="Access denied: You don't have permission to access vault endpoints")
    
    try:
        response = await group_secrets_service.get_group_secret(
            group_name=group_name,
            department_name=department_name,
            key_name=key_name,
            user=current_user
        )   
        
        # Check if the service returned an error
        if not response.get("success", False):
            message = response.get("message", "Unknown error")
            if "does not exist" in message or "not found" in message:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=message)
            elif "does not have access" in message:
                raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=message)
            else:
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=message)
        
        return SecretResponse(
            key_name=response["key_name"],
            secret_value=response["secret_value"],
            created_by=response["created_by"],
            created_at=response["created_at"].isoformat(),
            updated_at=response["updated_at"].isoformat() if response["updated_at"] else None
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))

@router.put("/{group_name}/secrets/{key_name}", response_model=SecretResponse)
async def update_group_secret(
    group_name: str,
    key_name: str,
    request: SecretUpdateRequest,
    current_user: User = Depends(get_current_user),
    group_secrets_service: GroupSecretsService = Depends(ServiceProvider.get_group_secrets_service),
    authorization_service: AuthorizationService = Depends(ServiceProvider.get_authorization_service)
):
    """Update a key in a group (Admin/Developer only)"""
    if current_user.role == UserRole.SUPER_ADMIN:
        raise HTTPException(status_code=403, detail="Superadmin is not allowed to update group secrets.")
    # Extract department from user data
    department_name = current_user.department_name 
    
    # Check vault access permission
    has_access = await authorization_service.check_vault_access(current_user.role, department_name)
    if not has_access:
        raise HTTPException(status_code=403, detail="Access denied: You don't have permission to access vault endpoints")
    
    try:
        response = await group_secrets_service.update_group_secret(
            group_name=group_name,
            department_name=department_name,
            key_name=key_name,
            secret_value=request.secret_value,
            user=current_user
        )
        
        # Check if the service returned an error
        if not response.get("success", False):
            message = response.get("message", "Unknown error")
            if "does not exist" in message or "not found" in message:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=message)
            elif "does not have access" in message or "role:" in message:
                raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=message)
            else:
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=message)
        
        # For update, we need to get the updated secret_record to return full details
        get_response = await group_secrets_service.get_group_secret(
            group_name=group_name,
            department_name=department_name,
            key_name=key_name,
            user=current_user
        )
        
        if not get_response.get("success", False):
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, 
                              detail="Secret updated but could not retrieve details")
        
        return SecretResponse(
            key_name=get_response["key_name"],
            secret_value=get_response["secret_value"],
            created_by=get_response["created_by"],
            created_at=get_response["created_at"].isoformat(),
            updated_at=get_response["updated_at"].isoformat() if get_response["updated_at"] else None
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))

@router.delete("/{group_name}/secrets/{key_name}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_group_secret(
    group_name: str,
    key_name: str,
    current_user: User = Depends(get_current_user),
    group_secrets_service: GroupSecretsService = Depends(ServiceProvider.get_group_secrets_service),
    authorization_service: AuthorizationService = Depends(ServiceProvider.get_authorization_service)
):
    """Delete a key from a group (Admin/Developer only)"""
    if current_user.role == UserRole.SUPER_ADMIN:
        raise HTTPException(status_code=403, detail="Superadmin is not allowed to delete group secrets.")
    # Extract department from user data
    department_name = current_user.department_name 
    
    # Check vault access permission
    has_access = await authorization_service.check_vault_access(current_user.role, department_name)
    if not has_access:
        raise HTTPException(status_code=403, detail="Access denied: You don't have permission to access vault endpoints")
    
    try:
        response = await group_secrets_service.delete_group_secret(
            group_name=group_name,
            department_name=department_name,
            key_name=key_name,
            user=current_user
        )
        
        # Check if the service returned an error
        if not response.get("success", False):
            message = response.get("message", "Unknown error")
            if "does not exist" in message or "not found" in message:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=message)
            elif "does not have access" in message or "role:" in message:
                raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=message)
            else:
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=message)
        
        # For delete operations with 204 status, we don't return any content
        return None
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))
