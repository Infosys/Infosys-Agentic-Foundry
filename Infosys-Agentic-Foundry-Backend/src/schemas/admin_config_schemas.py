# © 2024-25 Infosys Limited, Bangalore, India. All Rights Reserved.
from pydantic import BaseModel, Field
from typing import Optional, ClassVar
from datetime import datetime
from src.config.constants import Limits


class AdminConfigLimits(BaseModel):
    """
    Admin-configurable system limits.
    This is the single source of truth for default values.
    """
    # Config key - shared across all usages
    CONFIG_KEY: ClassVar[str] = "global_limits"
    # System user for initial setup
    SYSTEM_USER: ClassVar[str] = "system@infosys.com"
    
    # Critic Settings
    critic_score_threshold: float = Field(
        default=0.7, 
        ge=0.0, 
        le=1.0,
        description="Score threshold for critic evaluation (0.0-1.0)"
    )
    max_critic_epochs: int = Field(
        default=3, 
        ge=1, 
        le=Limits.MAX_CONFIGURABLE_EPOCHS,
        description=f"Maximum number of critic attempts (1-{Limits.MAX_CONFIGURABLE_EPOCHS})"
    )
    
    # Evaluation Settings
    evaluation_score_threshold: float = Field(
        default=0.7, 
        ge=0.0, 
        le=1.0,
        description="Score threshold for evaluation (0.0-1.0)"
    )
    max_evaluation_epochs: int = Field(
        default=3, 
        ge=1, 
        le=Limits.MAX_CONFIGURABLE_EPOCHS,
        description=f"Maximum number of evaluation attempts (1-{Limits.MAX_CONFIGURABLE_EPOCHS})"
    )
    
    # Validation Settings
    validation_score_threshold: float = Field(
        default=0.7, 
        ge=0.0, 
        le=1.0,
        description="Score threshold for validation (0.0-1.0)"
    )
    max_validation_epochs: int = Field(
        default=3, 
        ge=1, 
        le=Limits.MAX_CONFIGURABLE_EPOCHS,
        description=f"Maximum number of validation attempts (1-{Limits.MAX_CONFIGURABLE_EPOCHS})"
    )
    
    # LangGraph Settings
    langgraph_recursion_limit: int = Field(
        default=50, 
        ge=20, 
        le=200,
        description="Maximum recursion limit for LangGraph agents (20-200)"
    )
    
    # Chat Settings
    chat_summary_interval: int = Field(
        default=4,
        ge=1,
        le=100,
        description="Interval for chat summarization (1-100)"
    )


class AdminConfigResponse(AdminConfigLimits):
    """Response model including audit fields."""
    updated_by: Optional[str] = None
    updated_at: Optional[datetime] = None


class AdminConfigUpdateResponse(BaseModel):
    """Response model for update/reset operations with status message."""
    message: str = Field(..., description="Status message about the update")
    config: AdminConfigResponse = Field(..., description="The updated configuration")


class UpdateAdminConfigRequest(BaseModel):
    """Request model for updating admin configuration (partial updates)."""
    critic_score_threshold: Optional[float] = Field(None, ge=0.0, le=1.0)
    max_critic_epochs: Optional[int] = Field(None, ge=1, le=Limits.MAX_CONFIGURABLE_EPOCHS)
    evaluation_score_threshold: Optional[float] = Field(None, ge=0.0, le=1.0)
    max_evaluation_epochs: Optional[int] = Field(None, ge=1, le=Limits.MAX_CONFIGURABLE_EPOCHS)
    validation_score_threshold: Optional[float] = Field(None, ge=0.0, le=1.0)
    max_validation_epochs: Optional[int] = Field(None, ge=1, le=Limits.MAX_CONFIGURABLE_EPOCHS)
    langgraph_recursion_limit: Optional[int] = Field(None, ge=20, le=200)
    chat_summary_interval: Optional[int] = Field(None, ge=1, le=100)
