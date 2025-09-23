# © 2024-25 Infosys Limited, Bangalore, India. All Rights Reserved.
from pydantic import BaseModel, Field
from typing import List, Optional, Union, Dict, Any

class ToolData(BaseModel):
    """Schema for creating a new tool."""
    tool_description: str = Field(..., description="A brief description of the tool.")
    code_snippet: str = Field(..., description="The Python code snippet for the tool's function.")
    model_name: str = Field(..., description="The name of the LLM model to be used for docstring regeneration.")
    created_by: str = Field(..., description="The email ID of the user who created the tool.")
    tag_ids: Optional[Union[List[str], str]] = Field(None, description="Optional list of tag IDs for the tool.")

class UpdateToolRequest(BaseModel):
    """Schema for updating an existing tool."""
    model_name: str = Field(..., description="The name of the LLM model to be used for docstring regeneration.")
    user_email_id: str = Field(..., description="The email ID of the user requesting the update.")
    is_admin: bool = Field(False, description="Indicates if the user has admin privileges.")
    tool_description: Optional[str] = Field(None, description="New description for the tool.")
    code_snippet: Optional[str] = Field(None, description="New Python code snippet for the tool.")
    updated_tag_id_list: Optional[Union[List[str], str]] = Field(None, description="Optional list of new tag IDs for the tool.")

class DeleteToolRequest(BaseModel):
    """Schema for deleting a tool."""
    user_email_id: str = Field(..., description="The email ID of the user requesting the deletion.")
    is_admin: bool = Field(False, description="Indicates if the user has admin privileges.")

class ExecuteRequest(BaseModel):
    code: str
    inputs: Optional[Dict[str, Any]] = {}
    handle_default: bool = False

# class ExecuteResponse(BaseModel):
#     inputs_required: List[str] = []
#     output: Optional[Any] = None
#     output_type: Optional[Any] = None
#     error: str = ""
#     success: bool = True
#     feedback: Optional[List[str]] = None

class ParamInfo(BaseModel):
    name: str
    default: Optional[Any] = None

class ExecuteResponse(BaseModel):
    inputs_required: List[ParamInfo] = []
    output: Optional[Any] = None
    output_type: Optional[Any] = None
    error: str = ""
    success: bool = True
    feedback: Optional[List[str]] = None

class McpToolUpdateRequest(BaseModel):
    """Schema for updating an existing MCP tool (server definition)."""
    # Note: tool_id is in the path, not in the body
    is_admin: bool = Field(False, description="Indicates if the user has admin privileges.")
    user_email_id: str = Field(..., description="The email ID of the user requesting the update.")

    tool_description: Optional[str] = Field(None, description="New description for the MCP tool server.")
    code_content: Optional[str] = Field(None, description="New Python code content for 'file' type MCP tools.")

    updated_tag_id_list: Optional[Union[List[str], str]] = Field(None, description="Optional list of new tag IDs for the tool.")

    # # Auth-related fields for internal service logic, not directly from user input for update
    # is_public: Optional[bool] = Field(None, description="New public status for the tool.")
    # status: Optional[str] = Field(None, description="New approval status for the tool ('pending', 'approved', 'rejected').")
    # comments: Optional[str] = Field(None, description="New comments regarding the tool's status or approval.")
    # approved_at: Optional[datetime] = Field(None, description="New timestamp when the tool was approved.")
    # approved_by: Optional[str] = Field(None, description="New user who approved the tool.")

