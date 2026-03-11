# © 2024-25 Infosys Limited, Bangalore, India. All Rights Reserved.
from pydantic import BaseModel, Field
from typing import List, Optional, Union, Dict, Any
from src.config.constants import AgentType

class AgentOnboardingRequest(BaseModel):
    """Schema for onboarding a new agent."""
    agent_name: str = Field(..., description="The name of the agent.")
    agent_goal: str = Field(..., description="The overall goal or purpose of the agent.")
    workflow_description: str = Field(..., description="A description of the workflow the agent will follow.")
    agent_type: AgentType = Field(..., description=f"The type of the agent, Available types => [{[e.value for e in AgentType]}].")
    model_name: str = Field(..., description="The name of the LLM model to be used by the agent.")
    tools_id: List[str] = Field(..., description="A list of tool IDs (or worker agent IDs for meta-agents) that the agent will use.")
    validation_criteria: Optional[List[Dict[str, Any]]] = Field(None, description="List of validation test cases for non-meta agents. Each object should contain: 'query' (test question), 'validator' (validator tool ID or null), 'expected_answer' (expected response pattern). Not applicable for meta agents.")
    email_id: str = Field(..., description="The email ID of the user creating the agent.")
    tag_ids: Optional[Union[List[str], str]] = Field(None, description="Optional list of tag IDs for the agent.")
    knowledgebase_ids: Optional[List[str]] = Field([], description="Optional list of knowledge base IDs to link with the agent.")
    is_public: Optional[bool] = Field(False, description="If True, the agent will be visible to all departments. Default is False.")
    shared_with_departments: Optional[List[str]] = Field(None, description="Optional list of department names to share this agent with. When shared, all agent's tools are also shared. Only applicable for Admin users.")

class UpdateAgentRequest(BaseModel):
    """Schema for updating an existing agent."""
    agentic_application_id_to_modify: str = Field(..., description="The ID of the agentic application to be modified.")
    model_name: str = Field(..., description="The name of the LLM model to be updated.")
    user_email_id: str = Field(..., description="The email ID of the user requesting the update.")
    agentic_application_description: str = Field("", description="New description for the agentic application.")
    agentic_application_workflow_description: str = Field("", description="New workflow description for the agentic application.")
    system_prompt: Dict[str, Any] = Field({}, description="New system prompt parts for the agentic application.")
    welcome_message: str = Field("", description="New welcome greeting message that the agent will use as its first response when a conversation starts.")
    regenerate_system_prompt: bool = Field(True, description="If True, automatically regenerate the system_prompt when agent description, workflow description, or tools are modified. If False, keep the existing system_prompt unchanged unless explicitly provided.")
    regenerate_welcome_message: bool = Field(True, description="If True, automatically regenerate the welcome_message when agent description, workflow description, or agent type changes. If False, keep the existing welcome_message unchanged unless explicitly provided.")
    tools_id_to_add: List[str] = Field([], description="A list of tool IDs (or worker agent IDs) to be added.")
    tools_id_to_remove: List[str] = Field([], description="A list of tool IDs (or worker agent IDs) to be removed.")
    updated_tag_id_list: Optional[Union[List[str], str]] = Field(None, description="Optional list of new tag IDs for the agent.")
    validation_criteria: Optional[List[Dict[str, Any]]] = Field(None, description="List of validation test cases for non-meta agents. Each object should contain: 'query' (test question), 'validator' (validator tool ID or null), 'expected_answer' (expected response pattern). Not applicable for meta agents.")
    knowledgebase_ids_to_add: List[str] = Field([], description="A list of knowledge base IDs to be added.")
    knowledgebase_ids_to_remove: List[str] = Field([], description="A list of knowledge base IDs to be removed.")
    is_admin: bool = Field(False, description="Indicates if the user has admin privileges.")
    file_context_management_prompt: Optional[str] = Field(None, description="Optional custom file-context system prompt. If provided, saves to agent_workspaces/file_context_prompts/{agent_name}_file_context_prompt.md. Only used when file_context_management_flag is enabled.")
    regenerate_file_context_prompt: bool = Field(False, description="If True, automatically regenerate the file-context system prompt using the same LLM-based generation as during onboarding. If False, keep the existing file-context prompt unchanged unless explicitly provided via file_context_management_prompt.")
    is_public: Optional[bool] = Field(None, description="If provided, updates the agent's public visibility. True makes it visible to all departments.")
    shared_with_departments: Optional[List[str]] = Field(None, description="If provided, replaces the list of departments this agent is shared with. When shared, all agent's tools are also shared. Pass empty list to unshare from all.")

class DeleteAgentRequest(BaseModel):
    """Schema for deleting an agent."""
    user_email_id: str = Field(..., description="The email ID of the user requesting the deletion.")
    is_admin: bool = Field(False, description="Indicates if the user has admin privileges.")
