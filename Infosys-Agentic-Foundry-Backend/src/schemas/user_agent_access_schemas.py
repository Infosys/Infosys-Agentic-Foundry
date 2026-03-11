# © 2024-25 Infosys Limited, Bangalore, India. All Rights Reserved.
from typing import List, Optional
from pydantic import BaseModel, EmailStr


class GrantAgentAccessRequest(BaseModel):
    """Request model for granting agent access to a user."""
    user_email: EmailStr
    agent_id: str


class RevokeAgentAccessRequest(BaseModel):
    """Request model for revoking agent access from a user."""
    user_email: EmailStr
    agent_id: str


class UserAgentAccessResponse(BaseModel):
    """Response model for user agent access information."""
    user_email: str
    agent_ids: List[str]
    given_access_by: str


class AgentAccessOperationResponse(BaseModel):
    """Response model for agent access operations."""
    success: bool
    message: str
    user_email: str
    agent_id: str
    granted_by: Optional[str] = None


class GetUserAgentAccessResponse(BaseModel):
    """Response model for getting user agent access."""
    user_email: str
    agent_ids: List[str]
    has_access: bool


class AllUserAgentAccessResponse(BaseModel):
    """Response model for getting all user agent access records."""
    total_records: int
    access_records: List[UserAgentAccessResponse]


class GetUserToolIdsRequest(BaseModel):
    """Request model for getting tool IDs for a user."""
    user_email: EmailStr


class GetUserToolIdsResponse(BaseModel):
    """Response model for getting tool IDs for a user."""
    user_email: str
    accessible_agent_ids: List[str]
    tool_ids: List[str]
    total_agents: int
    total_tools: int


