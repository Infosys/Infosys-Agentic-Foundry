# © 2024-25 Infosys Limited, Bangalore, India. All Rights Reserved.
import asyncio
from fastapi import APIRouter, HTTPException, Request, Depends, status

from src.schemas import (
    SecretCreateRequest, PublicSecretCreateRequest, SecretUpdateRequest, PublicSecretUpdateRequest,
    SecretDeleteRequest, PublicSecretDeleteRequest, SecretGetRequest, PublicSecretGetRequest, SecretListRequest
)
from src.utils.secrets_handler import (
    setup_secrets_manager, get_user_secrets, set_user_secret, delete_user_secret, list_user_secrets,
    get_user_secrets_dict, create_public_key, update_public_key, get_public_key,
    get_all_public_keys, delete_public_key, list_public_keys
)
from src.auth.dependencies import get_current_user
from src.auth.models import UserRole, User
from src.auth.authorization_service import AuthorizationService
from src.api.dependencies import ServiceProvider

from telemetry_wrapper import logger as log, update_session_context


# Create an APIRouter instance for secrets-related endpoints
router = APIRouter(prefix="/secrets", tags=["Secrets"])


@router.post("/create")
async def create_user_secret_endpoint(
    fastapi_request: Request, 
    request: SecretCreateRequest,
    authorization_service: AuthorizationService = Depends(ServiceProvider.get_authorization_service),
    user_data: User = Depends(get_current_user)
):
    """
    Create or update a user secret_data.
    
    Args:
        request (SecretCreateRequest): The request containing user email, secret_data name, and value.
    
    Returns:
        dict: Success or error response.
    
    Raises:
        HTTPException: If secret_data creation fails.
    """
    user_id = fastapi_request.cookies.get("user_id")
    user_session = fastapi_request.cookies.get("user_session")
    update_session_context(user_session=user_session, user_id=user_id)
    
    if user_data.role == UserRole.SUPER_ADMIN:
        raise HTTPException(status_code=403, detail="Superadmin is not allowed to create user keys.")
    
    # Check vault access permission with department context
    department_name = user_data.department_name 
    has_access = await authorization_service.check_vault_access(user_data.role, department_name)
    if not has_access:
        raise HTTPException(status_code=403, detail="Access denied: You don't have permission to access vault endpoints")
    
    try:
        # Initialize secrets manager
        secrets_manager = setup_secrets_manager()
        
        # Store the secret_data
        success = secrets_manager.create_user_secret(
            user_email=request.user_email,
            key_name=request.key_name,
            key_value=request.key_value,
            department_name=department_name
        )
        
        if success:
            log.info(f"Secret '{request.key_name}' created/updated successfully for user: {request.user_email}")
            return {
                "success": True,
                "message": f"Secret '{request.key_name}' created/updated successfully",
                "user_email": request.user_email,
                "key_name": request.key_name
            }
        else:
            log.error(f"Failed to create/update secret '{request.key_name}' for user: {request.user_email}")
            raise HTTPException(
                status_code=500,
                detail=f"Failed to create/update secret '{request.key_name}'"
            )
    except ValueError as e:
        log.error(f"Error creating secret for user {request.user_email}: {str(e)}")
        raise HTTPException(
            status_code=400,
            detail=f"{str(e)}"
        )
    except Exception as e:
        log.error(f"Error creating secret for user {request.user_email}: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"Internal server error: {str(e)}"
        )


@router.post("/public/create")
async def create_public_secret_endpoint(
    fastapi_request: Request, 
    request: PublicSecretCreateRequest,
    authorization_service: AuthorizationService = Depends(ServiceProvider.get_authorization_service),
    user_data: User = Depends(get_current_user)
):
    """
    Create or update a public secret_data.
    
    Args:
        request (PublicSecretCreateRequest): The request containing secret_data name and value.
    
    Returns:
        dict: Success or error response.
    
    Raises:
        HTTPException: If public secret_data creation fails.
    """
    if user_data.role == UserRole.SUPER_ADMIN:
        raise HTTPException(status_code=403, detail="Superadmin is not allowed to create public keys.")
    # Check vault access permission with department context
    department_name = user_data.department_name 
    has_access = await authorization_service.check_vault_access(user_data.role, department_name)
    if not has_access:
        raise HTTPException(status_code=403, detail="Access denied: You don't have permission to access vault endpoints")
        
    #changed
    user_id = fastapi_request.cookies.get("user_id")
    user_session = fastapi_request.cookies.get("user_session")
    update_session_context(user_session=user_session, user_id=user_id)
    try:
        create_public_key(
            key_name=request.key_name,
            key_value=request.key_value,
            department_name=department_name
            
        )
        log.info(f"Public key '{request.key_name}' created/updated successfully")
        return {
            "success": True,
            "message": f"Public key '{request.key_name}' created/updated successfully"
        }
    except ValueError as e:
        log.error(f"Error creating secret for user {request.key_name}: {str(e)}")
        raise HTTPException(
            status_code=400,
            detail=f"{str(e)}"
        )
    except Exception as e:
        log.error(f"Error creating public key '{request.key_name}': {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"{str(e)}"
        )


@router.post("/get")
async def get_user_secret_endpoint(
    fastapi_request: Request, 
    request: SecretGetRequest,
    authorization_service: AuthorizationService = Depends(ServiceProvider.get_authorization_service),
    user_data: User = Depends(get_current_user)
):
    """
    Retrieve user secrets by name or get all secrets.
    
    Args:
        request (SecretGetRequest): The request containing user email and optional secret_data names.
    
    Returns:
        dict: The requested secrets or all secrets for the user.
    
    Raises:
        HTTPException: If secret_data retrieval fails or secrets not found.
    """
    # Check vault access permission with department context
    department_name = user_data.department_name 
    has_access = await authorization_service.check_vault_access(user_data.role, department_name)
    if not has_access:
        raise HTTPException(status_code=403, detail="Access denied: You don't have permission to access vault endpoints")
        
    #changed
    user_id = fastapi_request.cookies.get("user_id")
    user_session = fastapi_request.cookies.get("user_session")
    update_session_context(user_session=user_session, user_id=user_id)
    try:
        # Set the user context
        
        # Initialize secrets manager
        secrets_manager = setup_secrets_manager()
        
        if request.user_email != user_data.email:
            raise HTTPException(status_code=403, detail="Access denied: You don't have permission to see these user secrets")
        
        if request.key_name:
            key_value = secrets_manager.get_user_secret(
                    user_email=request.user_email,
                    key_name=request.key_name,
                    department_name=department_name
                )
            
            if key_value is not None:
                log.info(f"Secret '{request.key_name}' retrieved successfully for user: {request.user_email}")
                return {
                    "success": True,
                    "user_email": request.user_email,
                    "key_name": request.key_name,
                    "key_value": key_value
                }
            else:
                log.warning(f"Secret '{request.key_name}' not found for user: {request.user_email}")
                raise HTTPException(
                    status_code=404,
                    detail=f"Secret '{request.key_name}' not found for user"
                )
                
        elif request.key_names:
            secrets_dict = secrets_manager.get_user_secrets(
                    user_email=request.user_email,
                    key_names=request.key_names,
                    department_name=department_name
            )
            
            log.info(f"Multiple secrets retrieved successfully for user: {request.user_email}")
            return {
                "success": True,
                "user_email": request.user_email,
                "secrets": secrets_dict
            }
            
        else:
            secrets_dict = secrets_manager.get_user_secrets(
                    user_email=request.user_email,
                    department_name=department_name
                )
            
            log.info(f"All secrets retrieved successfully for user: {request.user_email}")
            return {
                "success": True,
                "user_email": request.user_email,
                "secrets": secrets_dict
            }
            
    except HTTPException:
        raise
    except Exception as e:
        log.error(f"Error retrieving secrets for user {request.user_email}: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"Internal server error: {str(e)}"
        )


@router.post("/public/get")
async def get_public_secret_endpoint(
    fastapi_request: Request, 
    request: PublicSecretGetRequest,
    authorization_service: AuthorizationService = Depends(ServiceProvider.get_authorization_service),
    user_data: User = Depends(get_current_user)
):
    """
    Retrieve a public secret_data by name.
    
    Args:
        request (PublicSecretGetRequest): The request containing the secret_data name.
    
    Returns:
        dict: The requested public secret_data value.
    
    Raises:
        HTTPException: If public secret_data retrieval fails or not found.
    """
    # Check vault access permission with department context
    department_name = user_data.department_name 
    has_access = await authorization_service.check_vault_access(user_data.role, department_name)
    if not has_access:
        raise HTTPException(status_code=403, detail="Access denied: You don't have permission to access vault endpoints")
        
    #changed
    user_id = fastapi_request.cookies.get("user_id")
    user_session = fastapi_request.cookies.get("user_session")
    update_session_context(user_session=user_session, user_id=user_id)
    try:
        public_key_value = get_public_key(request.key_name, department_name=department_name)
        
        if public_key_value is not None:
            log.info(f"Public key '{request.key_name}' retrieved successfully")
            return {
                "success": True,
                "key_name": request.key_name,
                "key_value": public_key_value
            }
        else:
            log.warning(f"Public key '{request.key_name}' not found")
            raise HTTPException(
                status_code=404,
                detail=f"Public key '{request.key_name}' not found"
            )
            
    except Exception as e:
        log.error(f"Error retrieving public key '{request.key_name}': {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"Internal server error: {str(e)}"
        )


@router.put("/update")
async def update_user_secret_endpoint(
    fastapi_request: Request, 
    request: SecretUpdateRequest,
    authorization_service: AuthorizationService = Depends(ServiceProvider.get_authorization_service),
    user_data: User = Depends(get_current_user)
):
    """
    Update an existing user secret_data.
    
    Args:
        request (SecretUpdateRequest): The request containing user email, secret_data name, and new value.
    
    Returns:
        dict: Success or error response.
    
    Raises:
        HTTPException: If secret_data update fails or secret_data doesn't exist.
    """
    if user_data.role == UserRole.SUPER_ADMIN:
        raise HTTPException(status_code=403, detail="Superadmin is not allowed to update user keys.")
    # Check vault access permission with department context
    department_name = user_data.department_name 
    has_access = await authorization_service.check_vault_access(user_data.role, department_name)
    if not has_access:
        raise HTTPException(status_code=403, detail="Access denied: You don't have permission to access vault endpoints")
        
    #changed
    user_id = fastapi_request.cookies.get("user_id")
    user_session = fastapi_request.cookies.get("user_session")
    update_session_context(user_session=user_session, user_id=user_id)
    try:
        # Set the user context
        
        # Initialize secrets manager
        secrets_manager = setup_secrets_manager()
        
        # Check if secret_data exists first
        existing_secret = secrets_manager.get_user_secret(
            user_email=request.user_email,
            key_name=request.key_name,
            department_name=department_name
        )
        
        if existing_secret is None:
            log.warning(f"Secret '{request.key_name}' not found for user: {request.user_email}")
            raise HTTPException(
                status_code=404,
                detail=f"Secret '{request.key_name}' not found for user"
            )
        
        # Update the secret_data
        success = secrets_manager.update_user_secret(
            user_email=request.user_email,
            key_name=request.key_name,
            key_value=request.key_value,
            department_name=department_name
        )
        
        if success:
            log.info(f"Secret '{request.key_name}' updated successfully for user: {request.user_email}")
            return {
                "success": True,
                "message": f"Secret '{request.key_name}' updated successfully",
                "user_email": request.user_email,
                "key_name": request.key_name
            }
        else:
            log.error(f"Failed to update secret '{request.key_name}' for user: {request.user_email}")
            raise HTTPException(
                status_code=500,
                detail=f"Failed to update secret '{request.key_name}'"
            )
            
    except HTTPException:
        raise
    except Exception as e:
        log.error(f"Error updating secret for user {request.user_email}: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"Internal server error: {str(e)}"
        )


@router.put("/public/update")
async def update_public_secret_endpoint(
    fastapi_request: Request, 
    request: PublicSecretUpdateRequest,
    authorization_service: AuthorizationService = Depends(ServiceProvider.get_authorization_service),
    user_data: User = Depends(get_current_user)
):
    """
    Update an existing public secret_data.
    
    Args:
        request (PublicSecretUpdateRequest): The request containing secret_data name and new value.
    
    Returns:
        dict: Success or error response.
    
    Raises:
        HTTPException: If public secret_data update fails or secret_data doesn't exist.
    """
    if user_data.role == UserRole.SUPER_ADMIN:
        raise HTTPException(status_code=403, detail="Superadmin is not allowed to update public keys.")
    
    # Check vault access permission
    department_name = user_data.department_name 
    has_access = await authorization_service.check_vault_access(user_data.role, department_name)
    if not has_access:
        raise HTTPException(status_code=403, detail="Access denied: You don't have permission to access vault endpoints")
        
    #changed
    user_id = fastapi_request.cookies.get("user_id")
    user_session = fastapi_request.cookies.get("user_session")
    update_session_context(user_session=user_session, user_id=user_id)
    try:
        # Update the public key
        success = update_public_key(
            key_name=request.key_name,
            key_value=request.key_value,
            department_name=department_name
        )
        
        if success:
            log.info(f"Public key '{request.key_name}' updated successfully")
            return {
                "success": True,
                "message": f"Public key '{request.key_name}' updated successfully"
            }
        else:
            log.error(f"Failed to update public key '{request.key_name}'")
            raise HTTPException(
                status_code=500,
                detail=f"Failed to update public key '{request.key_name}'"
            )
            
    except Exception as e:
        log.error(f"Error updating public key '{request.key_name}': {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"Internal server error: {str(e)}"
        )


@router.delete("/delete")
async def delete_user_secret_endpoint(
    fastapi_request: Request, 
    request: SecretDeleteRequest,
    authorization_service: AuthorizationService = Depends(ServiceProvider.get_authorization_service),
    user_data: User = Depends(get_current_user)
):
    """
    Delete a user secret_data.
    
    Args:
        request (SecretDeleteRequest): The request containing user email and secret_data name.
    
    Returns:
        dict: Success or error response.
    
    Raises:
        HTTPException: If secret_data deletion fails or secret_data doesn't exist.
    """
    if user_data.role == UserRole.SUPER_ADMIN:
        raise HTTPException(status_code=403, detail="Superadmin is not allowed to delete user keys.")
    # Check vault access permission
    department_name = user_data.department_name 
    has_access = await authorization_service.check_vault_access(user_data.role, department_name)
    if not has_access:
        raise HTTPException(status_code=403, detail="Access denied: You don't have permission to access vault endpoints")
        
    #changed
    user_id = fastapi_request.cookies.get("user_id")
    user_session = fastapi_request.cookies.get("user_session")
    update_session_context(user_session=user_session, user_id=user_id)

    try:
        # Set the user context
        
        # Initialize secrets manager
        secrets_manager = setup_secrets_manager()
        
        # Delete the secret_data
        success = secrets_manager.delete_user_secret(
            user_email=request.user_email,
            key_name=request.key_name,
            department_name=department_name
        )
        
        if success:
            log.info(f"Secret '{request.key_name}' deleted successfully for user: {request.user_email}")
            return {
                "success": True,
                "message": f"Secret '{request.key_name}' deleted successfully",
                "user_email": request.user_email,
                "key_name": request.key_name
            }
        else:
            log.warning(f"Secret '{request.key_name}' not found for deletion for user: {request.user_email}")
            raise HTTPException(
                status_code=404,
                detail=f"Secret '{request.key_name}' not found for user"
            )
            
    except HTTPException:
        raise
    except Exception as e:
        log.error(f"Error deleting secret for user {request.user_email}: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"Internal server error: {str(e)}"
        )


@router.delete("/public/delete")
async def delete_public_secret_endpoint(
    fastapi_request: Request, 
    request: PublicSecretDeleteRequest,
    authorization_service: AuthorizationService = Depends(ServiceProvider.get_authorization_service),
    user_data: User = Depends(get_current_user)
):
    """
    Delete a public secret_data.

    Args:
        request (PublicSecretDeleteRequest): The request containing secret_data name.

    Returns:
        dict: Success or error response.

    Raises:
        HTTPException: If public secret_data deletion fails or secret_data doesn't exist.
    """
    if user_data.role == UserRole.SUPER_ADMIN:
        raise HTTPException(status_code=403, detail="Superadmin is not allowed to delete public keys.")
    # Check vault access permission
    department_name = user_data.department_name 
    has_access = await authorization_service.check_vault_access(user_data.role, department_name)
    if not has_access:
        raise HTTPException(status_code=403, detail="Access denied: You don't have permission to access vault endpoints")
        
    #changed
    user_id = fastapi_request.cookies.get("user_id")
    user_session = fastapi_request.cookies.get("user_session")
    update_session_context(user_session=user_session, user_id=user_id)
    try:
        # Delete the public key
        success = delete_public_key(
            key_name=request.key_name,
            department_name=department_name
        )

        if success:
            log.info(f"Public key '{request.key_name}' deleted successfully")
            return {
                "success": True,
                "message": f"Public key '{request.key_name}' deleted successfully"
            }
        else:
            log.error(f"Failed to delete public key '{request.key_name}'")
            raise HTTPException(
                status_code=500,
                detail=f"Failed to delete public key '{request.key_name}'"
            )

    except Exception as e:
        log.error(f"Error deleting public key '{request.key_name}': {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"Internal server error: {str(e)}"
        )


@router.post("/list")
async def list_user_secrets_endpoint(
    fastapi_request: Request, 
    request: SecretListRequest,
    authorization_service: AuthorizationService = Depends(ServiceProvider.get_authorization_service),
    user_data: User = Depends(get_current_user)
):
    """
    List all secret_data names for a user (without values).
    
    Args:
        request (SecretListRequest): The request containing user email.
    
    Returns:
        dict: List of secret_data names or error response.
    
    Raises:
        HTTPException: If listing secrets fails.
    """
    # Check vault access permission
    department_name = user_data.department_name 
    has_access = await authorization_service.check_vault_access(user_data.role, department_name)
    if not has_access:
        raise HTTPException(status_code=403, detail="Access denied: You don't have permission to access vault endpoints")
        
    #changed
    user_id = fastapi_request.cookies.get("user_id")
    user_session = fastapi_request.cookies.get("user_session")
    update_session_context(user_session=user_session, user_id=user_id)
    try:
        # Set the user context
        
        # Initialize secrets manager
        secrets_manager = setup_secrets_manager()
        
        if request.user_email != user_data.email:
            raise HTTPException(status_code=403, detail="Access denied: You don't have permission to see these user secrets")
        
        key_names = secrets_manager.list_user_secret_names(
                user_email=request.user_email,
                department_name=department_name
        )
        
        log.info(f"Secret names listed successfully for user: {request.user_email}")
        return {
            "success": True,
            "user_email": request.user_email,
            "key_names": key_names,
            "count": len(key_names)
        }
        
    except Exception as e:
        log.error(f"Error listing secrets for user {request.user_email}: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"Internal server error: {str(e)}"
        )


@router.post("/public/list")
async def list_public_secrets_endpoint(
    fastapi_request: Request,
    authorization_service: AuthorizationService = Depends(ServiceProvider.get_authorization_service),
    user_data: User = Depends(get_current_user)
):
    """
    List all public secret_data names (without values).
    
    Returns:
        dict: List of public secret_data names or error response.
    
    Raises:
        HTTPException: If listing public secrets fails.
    """
    # Check vault access permission
    department_name = user_data.department_name 
    has_access = await authorization_service.check_vault_access(user_data.role, department_name)
    if not has_access:
        raise HTTPException(status_code=403, detail="Access denied: You don't have permission to access vault endpoints")
        
    #changed
    user_id = fastapi_request.cookies.get("user_id")
    user_session = fastapi_request.cookies.get("user_session")
    update_session_context(user_session=user_session, user_id=user_id)
    try:
        public_key_names = list_public_keys(department_name=department_name)    
        
        log.info("Public key names listed successfully")
        return {
            "success": True,
            "public_key_names": public_key_names,
            "count": len(public_key_names)
        }
        
    except Exception as e:
        log.error(f"Error listing public keys: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"Internal server error: {str(e)}"
        )
