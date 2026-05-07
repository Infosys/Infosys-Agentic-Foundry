# © 2024-25 Infosys Limited, Bangalore, India. All Rights Reserved.
from pydantic import BaseModel, Field, ConfigDict
from typing import List, Optional, Union, Dict, Any
from src.config.constants import AgentType


class ToolBinding(BaseModel):
    """Schema for binding a tool with a specific version to an agent."""
    tool_id: str = Field(..., description="The ID of the tool to bind.")
    tool_version: Optional[str] = Field("v1", description="The version of the tool to use (e.g., 'v1', 'v2'). Defaults to 'v1' if not specified.")


class AgentOnboardingRequest(BaseModel):
    """Schema for onboarding a new agent."""
    model_config = ConfigDict(populate_by_name=True)  # Accept both field name and alias
    
    agent_name: str = Field(..., description="The name of the agent.")
    agent_goal: str = Field(..., description="The overall goal or purpose of the agent.")
    workflow_description: str = Field(..., description="A description of the workflow the agent will follow.")
    agent_type: AgentType = Field(..., description=f"The type of the agent, Available types => [{[e.value for e in AgentType]}].")
    model_name: str = Field(..., description="The name of the LLM model to be used by the agent.")
    tools_id: List[str] = Field(..., description="A list of tool IDs (or worker agent IDs for meta-agents) that the agent will use.")
    tool_versions: Optional[List[ToolBinding]] = Field(None, alias="tools_with_versions", description="Optional list of tool bindings with versions (e.g., [{'tool_id': 'uuid-1', 'tool_version': 'v2'}]). If not provided, defaults to 'v1' for all tools. Also accepts 'tools_with_versions' key.")
    validation_criteria: Optional[List[Dict[str, Any]]] = Field(None, description="List of validation test cases for non-meta agents. Each object should contain: 'query' (test question), 'validator' (validator tool ID or null), 'expected_answer' (expected response pattern). Not applicable for meta agents.")
    email_id: str = Field(..., description="The email ID of the user creating the agent.")
    tag_ids: Optional[Union[List[str], str]] = Field(None, description="Optional list of tag IDs for the agent.")
    knowledgebase_ids: Optional[List[str]] = Field([], description="Optional list of knowledge base IDs to link with the agent.")
    db_connection_names: Optional[List[str]] = Field([], description="Optional list of database connection names for auto-injecting database query tools. These must match existing connections configured in the data-connector.")

class UpdateAgentRequest(BaseModel):
    """Schema for updating an existing agent."""
    model_config = ConfigDict(populate_by_name=True)  # Accept both field name and alias
    
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
    tool_versions: Optional[List[ToolBinding]] = Field(None, alias="tools_with_versions", description="Optional list of tool bindings with versions (e.g., [{'tool_id': 'uuid-1', 'tool_version': 'v2'}]). Used when adding tools or updating versions of existing tools. Also accepts 'tools_with_versions' key.")
    updated_tag_id_list: Optional[Union[List[str], str]] = Field(None, description="Optional list of new tag IDs for the agent.")
    validation_criteria: Optional[List[Dict[str, Any]]] = Field(None, description="List of validation test cases for non-meta agents. Each object should contain: 'query' (test question), 'validator' (validator tool ID or null), 'expected_answer' (expected response pattern). Not applicable for meta agents.")
    knowledgebase_ids_to_add: List[str] = Field([], description="A list of knowledge base IDs to be added.")
    knowledgebase_ids_to_remove: List[str] = Field([], description="A list of knowledge base IDs to be removed.")
    db_connection_names_to_add: List[str] = Field([], description="A list of database connection names to be added for auto-injecting database tools.")
    db_connection_names_to_remove: List[str] = Field([], description="A list of database connection names to be removed.")
    is_admin: bool = Field(False, description="Indicates if the user has admin privileges.")
    file_context_management_prompt: Optional[str] = Field(None, description="Optional custom file-context system prompt. If provided, saves to agent_workspaces/{department}/file_context_prompts/{agent_name}_file_context_prompt.md. Only used when file_context_management_flag is enabled.")
    regenerate_file_context_prompt: bool = Field(False, description="If True, automatically regenerate the file-context system prompt using the same LLM-based generation as during onboarding. If False, keep the existing file-context prompt unchanged unless explicitly provided via file_context_management_prompt.")

class DeleteAgentRequest(BaseModel):
    """Schema for deleting an agent."""
    user_email_id: str = Field(..., description="The email ID of the user requesting the deletion.")
    is_admin: bool = Field(False, description="Indicates if the user has admin privileges.")
    agent_ids: List[str] = Field(..., description="List of agent IDs to delete.")
