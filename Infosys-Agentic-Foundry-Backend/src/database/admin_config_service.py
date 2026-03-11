# © 2024-25 Infosys Limited, Bangalore, India. All Rights Reserved.
import time
from typing import Optional, Dict, Any
from src.database.admin_config_repository import AdminConfigRepository
from src.config.constants import Limits
from src.schemas.admin_config_schemas import AdminConfigLimits, AdminConfigResponse, UpdateAdminConfigRequest
from telemetry_wrapper import logger as log


class AdminConfigService:
    """
    Service for admin configuration management with caching.
    """
    
    _cache: Optional[Dict[str, Any]] = None
    _cache_timestamp: float = 0

    def __init__(self, admin_config_repo: AdminConfigRepository):
        self.repo = admin_config_repo

    def _is_cache_valid(self) -> bool:
        return (
            self._cache is not None 
            and (time.time() - self._cache_timestamp) < Limits.ADMIN_CONFIG_CACHE_TTL_SECONDS
        )

    def _invalidate_cache(self):
        AdminConfigService._cache = None
        AdminConfigService._cache_timestamp = 0

    async def get_config(self, force_refresh: bool = False) -> AdminConfigResponse:
        """Get current admin configuration with caching."""
        if not force_refresh and self._is_cache_valid():
            log.debug("Returning admin config from cache")
            return AdminConfigResponse(**self._cache)

        config = await self.repo.get_config()
        config["critic_score_threshold"] = round(config["critic_score_threshold"], 2)
        config["evaluation_score_threshold"] = round(config["evaluation_score_threshold"], 2)
        config["validation_score_threshold"] = round(config["validation_score_threshold"], 2)

        if config:
            AdminConfigService._cache = config
            AdminConfigService._cache_timestamp = time.time()
            return AdminConfigResponse(**config)

        log.warning("No admin config found, returning defaults")
        return AdminConfigResponse()

    async def get_limits(self, force_refresh: bool = False) -> AdminConfigLimits:
        """Get only the limit values (without audit fields)."""
        config = await self.get_config(force_refresh)
        return AdminConfigLimits(
            critic_score_threshold=config.critic_score_threshold,
            max_critic_epochs=config.max_critic_epochs,
            evaluation_score_threshold=config.evaluation_score_threshold,
            max_evaluation_epochs=config.max_evaluation_epochs,
            validation_score_threshold=config.validation_score_threshold,
            max_validation_epochs=config.max_validation_epochs,
            langgraph_recursion_limit=config.langgraph_recursion_limit,
            chat_summary_interval=config.chat_summary_interval
        )

    async def update_config(self, request: UpdateAdminConfigRequest, updated_by: str) -> AdminConfigResponse:
        """Update the admin configuration."""
        update_kwargs = {
            k: v for k, v in request.model_dump().items() if v is not None
        }

        if not update_kwargs:
            raise ValueError("No valid fields provided for update")

        success = await self.repo.update_config(updated_by=updated_by, **update_kwargs)

        if not success:
            raise ValueError("Failed to update admin configuration")

        self._invalidate_cache()
        return await self.get_config(force_refresh=True)

    async def reset_to_defaults(self, updated_by: str) -> AdminConfigResponse:
        """Reset all values to defaults."""
        success = await self.repo.reset_to_defaults(updated_by)
        
        if not success:
            raise ValueError("Failed to reset admin configuration")

        self._invalidate_cache()
        return await self.get_config(force_refresh=True)

