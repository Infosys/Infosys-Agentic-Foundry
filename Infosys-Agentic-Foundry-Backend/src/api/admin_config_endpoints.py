# © 2024-25 Infosys Limited, Bangalore, India. All Rights Reserved.
from fastapi import APIRouter, Depends, HTTPException, status
from src.schemas.admin_config_schemas import AdminConfigResponse, AdminConfigUpdateResponse, UpdateAdminConfigRequest
from src.database.admin_config_service import AdminConfigService
from src.auth.dependencies import get_current_user
from src.auth.models import User, UserRole
from src.api.dependencies import ServiceProvider
from src.config.constants import Limits
from telemetry_wrapper import logger as log

router = APIRouter(prefix="/admin/config", tags=["Admin Configuration"])


def _require_admin_role(user_data: User) -> None:
    """Raises HTTPException if user is not Admin or SuperAdmin."""
    if user_data.role not in (UserRole.ADMIN, UserRole.SUPER_ADMIN):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only Admin or SuperAdmin can perform this action"
        )


@router.get("/limits", response_model=AdminConfigResponse, summary="Get current admin configuration")
async def get_admin_config(
    admin_config_service: AdminConfigService = Depends(ServiceProvider.get_admin_config_service)
):
    """Get the current admin configuration. Available to all authenticated users."""
    try:
        return await admin_config_service.get_config()
    except Exception as e:
        log.error(f"Error fetching admin config: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, 
            detail="Failed to fetch configuration"
        )


@router.put("/limits", response_model=AdminConfigUpdateResponse, summary="Update admin configuration")
async def update_admin_config(
    update_request: UpdateAdminConfigRequest,
    user_data: User = Depends(get_current_user),
    admin_config_service: AdminConfigService = Depends(ServiceProvider.get_admin_config_service)
):
    """Update the admin configuration. Requires Admin or SuperAdmin role."""
    _require_admin_role(user_data)

    try:
        updated_config = await admin_config_service.update_config(
            request=update_request,
            updated_by=user_data.email
        )
        return AdminConfigUpdateResponse(
            message=f"Configuration updated successfully. Changes will take effect within {Limits.ADMIN_CONFIG_CACHE_TTL_SECONDS} seconds.",
            config=updated_config
        )

    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))

    except Exception as e:
        log.error(f"Error updating admin config: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, 
            detail="Failed to update configuration"
        )


@router.post("/limits/reset", response_model=AdminConfigUpdateResponse, summary="Reset to defaults")
async def reset_admin_config(
    user_data: User = Depends(get_current_user),
    admin_config_service: AdminConfigService = Depends(ServiceProvider.get_admin_config_service)
):
    """Reset the admin configuration to defaults. Requires Admin or SuperAdmin role."""
    _require_admin_role(user_data)

    try:
        reset_config = await admin_config_service.reset_to_defaults(updated_by=user_data.email)
        return AdminConfigUpdateResponse(
            message=f"Configuration reset to defaults successfully. Changes will take effect within {Limits.ADMIN_CONFIG_CACHE_TTL_SECONDS} seconds.",
            config=reset_config
        )
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except Exception as e:
        log.error(f"Error resetting admin config: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, 
            detail="Failed to reset configuration"
        )

