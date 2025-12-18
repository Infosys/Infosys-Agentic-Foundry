# © 2024-25 Infosys Limited, Bangalore, India. All Rights Reserved.
from pydantic import BaseModel, Field
from typing import List, Optional, Union, Dict, Any

class AgentOnboardingRequest(BaseModel):
    """Schema for onboarding a new agent."""
    agent_name: str = Field(..., description="The name of the agent.")
    agent_goal: str = Field(..., description="The overall goal or purpose of the agent.")
    workflow_description: str = Field(..., description="A description of the workflow the agent will follow.")
    agent_type: str = Field(..., description="The type of the agent [Available types => 'react_agent', 'multi_agent', 'planner_executor_agent', 'react_critic_agent', 'simple_ai_agent', 'meta_agent', 'planner_meta_agent'].")
    model_name: str = Field(..., description="The name of the LLM model to be used by the agent.")
    tools_id: List[str] = Field(..., description="A list of tool IDs (or worker agent IDs for meta-agents) that the agent will use.")
    validation_criteria: Optional[List[Dict[str, Any]]] = Field(None, description="List of validation test cases for non-meta agents. Each object should contain: 'query' (test question), 'validator' (validator tool ID or null), 'expected_answer' (expected response pattern). Not applicable for meta agents.")
    email_id: str = Field(..., description="The email ID of the user creating the agent.")
    tag_ids: Optional[Union[List[str], str]] = Field(None, description="Optional list of tag IDs for the agent.")

class UpdateAgentRequest(BaseModel):
    """Schema for updating an existing agent."""
    agentic_application_id_to_modify: str = Field(..., description="The ID of the agentic application to be modified.")
    model_name: str = Field(..., description="The name of the LLM model to be updated.")
    user_email_id: str = Field(..., description="The email ID of the user requesting the update.")
    agentic_application_description: str = Field("", description="New description for the agentic application.")
    agentic_application_workflow_description: str = Field("", description="New workflow description for the agentic application.")
    system_prompt: Dict[str, Any] = Field({}, description="New system prompt parts for the agentic application.")
    tools_id_to_add: List[str] = Field([], description="A list of tool IDs (or worker agent IDs) to be added.")
    tools_id_to_remove: List[str] = Field([], description="A list of tool IDs (or worker agent IDs) to be removed.")
    updated_tag_id_list: Optional[Union[List[str], str]] = Field(None, description="Optional list of new tag IDs for the agent.")
    validation_criteria: Optional[List[Dict[str, Any]]] = Field(None, description="List of validation test cases for non-meta agents. Each object should contain: 'query' (test question), 'validator' (validator tool ID or null), 'expected_answer' (expected response pattern). Not applicable for meta agents.")
    is_admin: bool = Field(False, description="Indicates if the user has admin privileges.")

class DeleteAgentRequest(BaseModel):
    """Schema for deleting an agent."""
    user_email_id: str = Field(..., description="The email ID of the user requesting the deletion.")
    is_admin: bool = Field(False, description="Indicates if the user has admin privileges.")

