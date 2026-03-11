# © 2024-25 Infosys Limited, Bangalore, India. All Rights Reserved.
from pydantic import BaseModel, Field
from typing import List, Optional, Union, Dict, Any, Literal

class ToolData(BaseModel):
    """Schema for creating a new tool."""
    tool_description: str = Field(..., description="A brief description of the tool.")
    code_snippet: str = Field(..., description="The Python code snippet for the tool's function.")
    model_name: str = Field(..., description="The name of the LLM model to be used for docstring regeneration.")
    created_by: str = Field(..., description="The email ID of the user who created the tool.")
    tag_ids: Optional[Union[List[str], str]] = Field(None, description="Optional list of tag IDs for the tool.")
    is_validator: Optional[bool] = Field(False, description="Indicates if the tool is a validator tool. Validator tools must have exactly 2 parameters (query, response) and return validation results.")
    is_public: Optional[bool] = Field(False, description="If True, the tool will be visible to all departments. Default is False.")
    shared_with_departments: Optional[List[str]] = Field(None, description="Optional list of department names to share this tool with. Only applicable for Admin users.")

class AddToolRequest(BaseModel):
    """Schema for adding a new tool."""
    tool_description: str = Field(..., description="A brief description of the tool.")
    code_snippet: str = Field(..., description="The Python code snippet for the tool's function.")
    model_name: str = Field(..., description="The name of the LLM model to be used for docstring regeneration.")
    created_by: str = Field(..., description="The email ID of the user who created the tool.")
    tag_ids: Optional[Union[List[str], str]] = Field(None, description="Optional comma-separated string or list of tag IDs for the tool.")
    force_add: Optional[bool] = Field(False, description="Force add flag for bypassing certain validations.")
    is_validator: Optional[bool] = Field(False, description="Indicates if the tool is a validator tool. Validator tools must have exactly 2 parameters (query, response) and return validation results.")
    session_id: Optional[str] = Field(None, description="Optional session identifier for tracking tool creation."),
    is_public: Optional[bool] = Field(False, description="Whether the tool should be public (accessible to all departments).")
    shared_with_departments: Optional[List[str]] = Field(None, description="List of department names to share the tool with.")

class UpdateToolRequest(BaseModel):
    """Schema for updating an existing tool."""
    model_name: str = Field(..., description="The name of the LLM model to be used for docstring regeneration.")
    user_email_id: str = Field(..., description="The email ID of the user requesting the update.")
    is_admin: bool = Field(False, description="Indicates if the user has admin privileges.")
    tool_description: Optional[str] = Field(None, description="New description for the tool.")
    code_snippet: Optional[str] = Field(None, description="New Python code snippet for the tool.")
    updated_tag_id_list: Optional[Union[List[str], str]] = Field(None, description="Optional list of new tag IDs for the tool.")
    is_validator: Optional[bool] = Field(False, description="Indicates if the tool is a validator tool. Validator tools must have exactly 2 parameters (query, response) and return validation results.")
    is_public: Optional[bool] = Field(None, description="If provided, updates the tool's public visibility. True makes it visible to all departments.")
    shared_with_departments: Optional[List[str]] = Field(None, description="If provided, replaces the list of departments this tool is shared with. Pass empty list to unshare from all.")

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
    mandatory: bool = True

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
    
    shared_with_departments: Optional[List[str]] = Field(None, description="If provided, replaces the list of departments this MCP tool is shared with. Pass empty list to unshare from all.")
    
    is_public: Optional[bool] = Field(None, description="If provided, updates the MCP tool's public visibility. True makes it visible to all departments.")

class McpToolInvocation(BaseModel):
    """Schema for a single MCP tool invocation."""
    tool_name: str = Field(..., description="Name of the MCP tool to invoke.")
    args: Dict[str, Any] = Field(..., description="Arguments to pass to the tool.")

class McpToolTestRequest(BaseModel):
    """Schema for testing MCP tools."""
    invocations: List[McpToolInvocation] = Field(..., min_length=1, max_length=10, description="List of tool invocations to execute (max 10).")
    parallel: bool = Field(False, description="Whether to execute invocations in parallel.")
    timeout_sec: int = Field(15, ge=1, le=60, description="Timeout per tool invocation in seconds (1-60).")

class McpToolInvocationResult(BaseModel):
    """Schema for the result of a single MCP tool invocation."""
    tool_name: str = Field(..., description="Name of the MCP tool that was invoked.")
    success: bool = Field(..., description="Whether the invocation was successful.")
    latency_ms: float = Field(..., description="Execution latency in milliseconds.")
    output: Optional[Any] = Field(None, description="Output from the tool invocation.")
    error: Optional[str] = Field(None, description="Error message if invocation failed.")

class McpToolTestResponse(BaseModel):
    """Schema for MCP tool test response."""
    tool_id: str = Field(..., description="ID of the MCP server that was tested.")
    server_name: str = Field(..., description="Name of the MCP server.")
    started_at: str = Field(..., description="ISO timestamp when testing started.")
    finished_at: str = Field(..., description="ISO timestamp when testing finished.")
    overall_success: bool = Field(..., description="Whether all invocations were successful.")
    results: List[McpToolInvocationResult] = Field(..., description="Results of individual tool invocations.")

class InlineMcpRequest(BaseModel):
    """Schema for inline MCP code execution request."""
    code: str = Field(..., description="Python MCP server code to execute.")
    tool_name: Optional[str] = Field(None, description="Name of the tool to execute. If not provided, returns tool introspection.")
    arguments: Optional[Dict[str, Any]] = Field(None, description="Arguments to pass to the tool.")
    timeout_sec: Optional[int] = Field(5, ge=1, le=15, description="Timeout for tool execution in seconds.")
    debug: Optional[bool] = Field(False, description="If true, include lightweight discovery diagnostics in warnings (introspection mode only).")
    handle_default: Optional[bool] = Field(False, description="If true, on coercion failure or missing required params with defaults, auto-apply defaults instead of erroring. Also echoed back in responses.")

class InlineMcpParam(BaseModel):
    """Schema for inline MCP tool parameter information."""
    name: str = Field(..., description="Parameter name.")
    type: str = Field(..., description="Parameter type (integer, number, string, boolean).")
    required: bool = Field(..., description="Whether the parameter is required.")
    default: Optional[Any] = Field(None, description="Default value for the parameter.")
    default_repr: Optional[bool] = Field(False, description="Whether the default value is represented as string.")

class InlineMcpToolMeta(BaseModel):
    """Schema for inline MCP tool metadata."""
    name: str = Field(..., description="Tool name.")
    doc: str = Field(..., description="Tool documentation.")
    params: List[InlineMcpParam] = Field(..., description="Tool parameters.")

class InlineMcpIntrospectResponse(BaseModel):
    """Schema for inline MCP introspection response."""
    mode: str = Field("introspect", description="Response mode.")
    tool_count: int = Field(..., description="Number of discovered tools.")
    tools: List[InlineMcpToolMeta] = Field(..., description="List of discovered tools.")
    warnings: List[str] = Field([], description="Any warnings during introspection.")

class InlineMcpExecuteResponse(BaseModel):
    """Schema for inline MCP execution response."""
    mode: str = Field("execute", description="Response mode.")
    tool_name: str = Field(..., description="Name of the executed tool.")
    success: bool = Field(..., description="Whether execution was successful.")
    latency_ms: float = Field(..., description="Execution latency in milliseconds.")
    result: Optional[Any] = Field(None, description="Tool execution result.")
    error: Optional[str] = Field(None, description="Error message if execution failed.")
    error_code: Optional[str] = Field(None, description="Error code if execution failed.")
    warnings: List[str] = Field([], description="Any warnings during execution.")

class InlineMcpErrorResponse(BaseModel):
    """Schema for inline MCP error response."""
    success: bool = Field(False, description="Always false for error responses.")
    error_code: str = Field(..., description="Error code.")
    message: str = Field(..., description="Error message.")
    detail: Optional[str] = Field(None, description="Additional error details.")


# ============================================================================
# Tool Generation Pipeline Schemas
# ============================================================================

class ToolGenerationPipelineRequest(BaseModel):
    """Request schema for tool generation via pipeline agent."""
    pipeline_id: str = Field(..., description="The pipeline ID for tool generation agent")
    session_id: str = Field(..., description="The user's session ID")
    query: str = Field(..., description="The user's query for tool generation")
    model_name: str = Field(default="gpt-4o", description="The LLM model to use")
    reset_conversation: bool = Field(default=False, description="Whether to reset conversation")
    current_code: Optional[str] = Field(
        default=None, 
        description="The current code in the editor. Send this if the user has manually edited the code, so the agent works with the latest version."
    )
    selected_code: Optional[str] = Field(
        default=None,
        description="The code that user has highlighted/selected in the editor. When provided, the agent will focus on this specific portion."
    )


# ============================================================================
# Code Version Management Schemas
# ============================================================================

class SaveCodeVersionRequest(BaseModel):
    """Request schema for saving a code version."""
    session_id: str = Field(..., description="The user's session ID")
    pipeline_id: str = Field(..., description="The pipeline ID")
    code_snippet: str = Field(..., description="The code to save")
    label: Optional[str] = Field(None, description="Optional label for this version (e.g., 'Added error handling')")
    user_query: Optional[str] = Field(None, description="The user query that generated this code")


class SwitchVersionRequest(BaseModel):
    """Request schema for switching to a specific version."""
    session_id: str = Field(..., description="The user's session ID")
    version_id: str = Field(..., description="The version ID to switch to")


class UpdateVersionLabelRequest(BaseModel):
    """Request schema for updating a version label."""
    version_id: str = Field(..., description="The version ID")
    label: str = Field(..., description="The new label")


class DeleteVersionRequest(BaseModel):
    """Request schema for deleting a version."""
    session_id: str = Field(..., description="The user's session ID")
    version_id: str = Field(..., description="The version ID to delete")


# ============================================================================
# Tool Generation Conversation History Schemas
# ============================================================================

class ToolGenerationConversationEntry(BaseModel):
    """Schema for a single conversation entry in tool generation."""
    role: Literal["user", "assistant"] = Field(..., description="The role of the message sender")
    message: str = Field(..., description="The text message content")
    code_snippet: Optional[str] = Field(None, description="Code snippet if any was generated/referenced")
    timestamp: Optional[str] = Field(None, description="ISO format timestamp of the message")


class SaveConversationRequest(BaseModel):
    """Request schema for saving a conversation entry."""
    session_id: str = Field(..., description="The user's session ID")
    pipeline_id: str = Field(..., description="The pipeline ID")
    role: Literal["user", "assistant"] = Field(..., description="The role: 'user' or 'assistant'")
    message: str = Field(..., description="The message content")
    code_snippet: Optional[str] = Field(None, description="Associated code snippet if any")


class GetConversationHistoryRequest(BaseModel):
    """Request schema for fetching conversation history."""
    session_id: str = Field(..., description="The user's session ID")
    pipeline_id: Optional[str] = Field(None, description="Optional pipeline ID filter")
    limit: Optional[int] = Field(50, description="Maximum number of messages to return")


class ClearConversationRequest(BaseModel):
    """Request schema for clearing conversation history."""
    session_id: str = Field(..., description="The user's session ID")
    pipeline_id: Optional[str] = Field(None, description="Optional pipeline ID - if not provided, clears all for session")


class ToolGenerationConversationHistoryRequest(BaseModel):
    """Request schema for fetching conversation history with pagination."""
    session_id: str = Field(..., description="The user's session ID")
    pipeline_id: Optional[str] = Field(None, description="Optional pipeline ID filter")
    limit: Optional[int] = Field(50, ge=1, le=200, description="Maximum number of messages to return")
    offset: Optional[int] = Field(0, ge=0, description="Number of messages to skip for pagination")
    include_code: bool = Field(True, description="Whether to include code snippets in response")


# ============================================================================
# Tool Export / Import Schemas
# ============================================================================

class ExportToolsRequest(BaseModel):
    """Request schema for exporting tools as a zip file."""
    tool_ids: List[str] = Field(..., min_length=1, description="List of tool IDs to export")


class ExportMcpToolsRequest(BaseModel):
    """Request schema for exporting MCP tools as a zip file."""
    tool_ids: List[str] = Field(..., min_length=1, description="List of MCP tool IDs to export")

