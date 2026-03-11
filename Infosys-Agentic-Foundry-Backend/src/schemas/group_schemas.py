# © 2024-25 Infosys Limited, Bangalore, India. All Rights Reserved.
from typing import List, Optional
from pydantic import BaseModel, Field
from datetime import datetime


class CreateGroupRequest(BaseModel):
    """Request model for creating a new group."""
    group_name: str = Field(..., min_length=1, max_length=100, description="Unique name of the group")
    group_description: Optional[str] = Field(None, max_length=500, description="Description of the group")
    user_emails: List[str] = Field(default_factory=list, description="List of user emails in the group")
    agent_ids: List[str] = Field(default_factory=list, description="List of agent IDs in the group")


class UpdateGroupRequest(BaseModel):
    """Request model for updating a group with granular user and agent management."""
    group_description: Optional[str] = Field(None, max_length=500, description="New group description")
    add_users: Optional[List[str]] = Field(None, description="List of user emails to add to group")
    remove_users: Optional[List[str]] = Field(None, description="List of user emails to remove from group")
    add_agents: Optional[List[str]] = Field(None, description="List of agent IDs to add to group")
    remove_agents: Optional[List[str]] = Field(None, description="List of agent IDs to remove from group")


class AddUsersRequest(BaseModel):
    """Request model for adding users to a group."""
    user_emails: List[str] = Field(..., min_items=1, description="List of user emails to add")


class RemoveUsersRequest(BaseModel):
    """Request model for removing users from a group."""
    user_emails: List[str] = Field(..., min_items=1, description="List of user emails to remove")


class AddAgentsRequest(BaseModel):
    """Request model for adding agents to a group."""
    agent_ids: List[str] = Field(..., min_items=1, description="List of agent IDs to add")


class RemoveAgentsRequest(BaseModel):
    """Request model for removing agents from a group."""
    agent_ids: List[str] = Field(..., min_items=1, description="List of agent IDs to remove")


class GroupResponse(BaseModel):
    """Response model for group information."""
    group_name: str
    group_description: Optional[str]
    department_name: str
    user_emails: List[str]
    agent_ids: List[str]
    created_by: str
    created_at: datetime
    updated_at: datetime


class GroupOperationResponse(BaseModel):
    """Response model for group operations."""
    success: bool
    message: str
    group_name: str
    department_name: Optional[str] = None


class CreateGroupResponse(GroupOperationResponse):
    """Response model for group creation."""
    created_by: Optional[str] = None
    user_count: Optional[int] = None
    agent_count: Optional[int] = None


class GetGroupResponse(BaseModel):
    """Response model for getting a group."""
    success: bool
    message: str
    group: Optional[GroupResponse] = None


class GetAllGroupsResponse(BaseModel):
    """Response model for getting all groups."""
    success: bool
    message: str
    groups: List[GroupResponse]
    total_count: int


class GroupUserManagementResponse(GroupOperationResponse):
    """Response model for group user management operations."""
    added_users: Optional[List[str]] = None
    removed_users: Optional[List[str]] = None


class GroupAgentManagementResponse(GroupOperationResponse):
    """Response model for group agent management operations."""
    added_agents: Optional[List[str]] = None
    removed_agents: Optional[List[str]] = None


class GroupUpdateResponse(GroupOperationResponse):
    """Response model for comprehensive group update operations."""
    added_users: Optional[List[str]] = None
    removed_users: Optional[List[str]] = None
    added_agents: Optional[List[str]] = None
    removed_agents: Optional[List[str]] = None
    description_updated: bool = False


class GetGroupsByUserResponse(BaseModel):
    """Response model for getting groups by user."""
    success: bool
    message: str
    user_email: str
    groups: List[GroupResponse]
    total_count: int


class GetGroupsByAgentResponse(BaseModel):
    """Response model for getting groups by agent."""
    success: bool
    message: str
    agent_id: str
    groups: List[GroupResponse]
    total_count: int