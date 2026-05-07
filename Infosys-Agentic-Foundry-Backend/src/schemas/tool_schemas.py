# © 2024-25 Infosys Limited, Bangalore, India. All Rights Reserved.
import base64
from pydantic import BaseModel, Field, field_validator, model_validator
from typing import List, Optional, Union, Dict, Any, Literal

class ToolData(BaseModel):
    """Schema for creating a new tool."""
    tool_description: str = Field(..., description="A brief description of the tool.")
    code_snippet: str = Field(..., description="The Python code snippet for the tool's function.")
    model_name: str = Field(..., description="The name of the LLM model to be used for docstring regeneration.")
    created_by: str = Field(..., description="The email ID of the user who created the tool.")
    tag_ids: Optional[Union[List[str], str]] = Field(None, description="Optional list of tag IDs for the tool.")
    is_validator: Optional[bool] = Field(False, description="Indicates if the tool is a validator tool. Validator tools must have exactly 2 parameters (query, response) and return validation results.")

class AddToolRequest(BaseModel):
    """Schema for adding a new tool."""
    tool_description: str = Field(..., description="A brief description of the tool.")
    code_snippet: str = Field(..., description="The Python code snippet for the tool's function (base64 encoded).")
    model_name: str = Field(..., description="The name of the LLM model to be used for docstring regeneration.")
    created_by: str = Field(..., description="The email ID of the user who created the tool.")
    tag_ids: Optional[Union[List[str], str]] = Field(None, description="Optional comma-separated string or list of tag IDs for the tool.")
    force_add: Optional[bool] = Field(False, description="Force add flag for bypassing certain validations.")
    is_validator: Optional[bool] = Field(False, description="Indicates if the tool is a validator tool. Validator tools must have exactly 2 parameters (query, response) and return validation results.")
    session_id: Optional[str] = Field(None, description="Optional session identifier for tracking tool creation.")

    @field_validator('code_snippet')
    @classmethod
    def decode_code_snippet(cls, v: str) -> str:
        try:
            v = base64.b64decode(v).decode('utf-8')
        except Exception:
            pass  # If not base64, use as-is (backward compatibility)
        return v

class UpdateToolRequest(BaseModel):
    """Schema for updating an existing tool."""
    model_name: str = Field(..., description="The name of the LLM model to be used for docstring regeneration.")
    user_email_id: str = Field(..., description="The email ID of the user requesting the update.")
    is_admin: bool = Field(False, description="Indicates if the user has admin privileges.")
    tool_description: Optional[str] = Field(None, description="New description for the tool.")
    code_snippet: Optional[str] = Field(None, description="New Python code snippet for the tool (base64 encoded).")
    updated_tag_id_list: Optional[Union[List[str], str]] = Field(None, description="Optional list of new tag IDs for the tool.")
    is_validator: Optional[bool] = Field(False, description="Indicates if the tool is a validator tool. Validator tools must have exactly 2 parameters (query, response) and return validation results.")
    # Versioning fields
    version: Optional[str] = Field(None, description="The version to update (e.g., 'v1', 'v2'). If not provided, updates the current active version.")
    create_new_version: Optional[bool] = Field(False, description="If True, creates a new version instead of updating existing. The new version becomes the current active version.")

    @field_validator('code_snippet')
    @classmethod
    def decode_code_snippet(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return v
        try:
            v = base64.b64decode(v).decode('utf-8')
        except Exception:
            pass  # If not base64, use as-is (backward compatibility)
        return v

class DeleteToolRequest(BaseModel):
    """Schema for deleting a tool."""
    user_email_id: str = Field(..., description="The email ID of the user requesting the deletion.")
    is_admin: bool = Field(False, description="Indicates if the user has admin privileges.")
    tool_ids: List[str] = Field(..., description="List of tool IDs to delete.")
    # Versioning fields
    version: Optional[str] = Field(None, description="The specific version to delete (e.g., 'v1', 'v2'). If not provided, deletes the entire tool with all versions.")


# ============================================================================
# Tool Versioning Schemas
# ============================================================================

class ToolVersionInfo(BaseModel):
    """Schema for a single tool version."""
    code_snippet: str = Field(..., description="The Python code snippet for this version.")
    updated_date: str = Field(..., description="The date when this version was created/updated (ISO format).")
    updated_by: str = Field(..., description="The user who created/updated this version.")
    model_name: str = Field(..., description="The LLM model used for docstring generation.")


class ToolVersioningData(BaseModel):
    """Schema for the versioning data structure stored in the tool."""
    versions: Dict[str, ToolVersionInfo] = Field(default_factory=dict, description="Dictionary of version key (v1, v2, etc.) to version info.")


class GetToolVersionsRequest(BaseModel):
    """Request schema for getting all versions of a tool."""
    tool_id: str = Field(..., description="The tool ID to get versions for.")


class GetToolVersionsResponse(BaseModel):
    """Response schema for getting all versions of a tool."""
    tool_id: str = Field(..., description="The tool ID.")
    tool_name: str = Field(..., description="The tool name.")
    versions: Dict[str, ToolVersionInfo] = Field(..., description="All available versions - all versions are active and can be bound to agents.")
    total_versions: int = Field(..., description="Total number of versions.")


class DeleteToolVersionRequest(BaseModel):
    """Request schema for deleting a specific version of a tool."""
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
    code_content: Optional[str] = Field(None, description="New Python code content for 'file' type MCP tools (base64 encoded).")

    updated_tag_id_list: Optional[Union[List[str], str]] = Field(None, description="Optional list of new tag IDs for the tool.")

    @field_validator('code_content')
    @classmethod
    def decode_code_content(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return v
        try:
            v = base64.b64decode(v).decode('utf-8')
        except Exception:
            pass  # If not base64, use as-is (backward compatibility)
        return v

class McpRemoteUrlUpdateRequest(BaseModel):
    """Update streamable-HTTP MCP endpoint URL and/or headers for `mcp_url_*` tools only."""
    is_admin: bool = Field(False, description="Whether the caller is asserting admin privileges (verified server-side).")
    user_email_id: str = Field(..., description="Email of the user requesting the update.")
    mcp_url: Optional[str] = Field(None, description="New remote MCP URL (https://...). Omit to leave URL unchanged.")
    headers: Optional[Dict[str, str]] = Field(
        None,
        description="Replace HTTP headers for the MCP client. Send {} to clear. Omit to leave headers unchanged.",
    )

    @model_validator(mode="after")
    def _at_least_one_field(self):
        if self.mcp_url is None and self.headers is None:
            raise ValueError("Provide mcp_url and/or headers to update the remote MCP configuration.")
        return self

class McpModuleUpdateRequest(BaseModel):
    """Update module name and/or command for `mcp_module_*` tools only."""
    is_admin: bool = Field(False, description="Whether the caller is asserting admin privileges (verified server-side).")
    user_email_id: str = Field(..., description="Email of the user requesting the update.")
    mcp_module_name: Optional[str] = Field(None, description="New module/package name (e.g., 'sonar-mcp', '@playwright/mcp@latest'). Omit to leave unchanged.")
    mcp_command: Optional[str] = Field(None, description="New command to run the module (e.g., 'npx', 'python'). Omit to leave unchanged.")

    @model_validator(mode="after")
    def _at_least_one_field(self):
        if self.mcp_module_name is None and self.mcp_command is None:
            raise ValueError("Provide mcp_module_name and/or mcp_command to update the module MCP configuration.")
        return self

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

class InlineRemoteMcpRequest(BaseModel):
    """Schema for remote MCP server execution without registering the server."""
    endpoint: str = Field(..., description="Remote MCP server URL (e.g. https://host/path).")
    tool_name: Optional[str] = Field(None, description="Tool to execute; omit for introspection (list tools).")
    arguments: Optional[Dict[str, Any]] = Field(None, description="Arguments for the tool.")
    inputs: Optional[Dict[str, Any]] = Field(None, description="Alias for arguments (same semantics).")
    timeout_sec: int = Field(30, ge=1, le=120, description="Execution timeout in seconds.")
    auth_uuid: Optional[str] = Field(None, description="UUID for hosted servers; sent as Authorization header when set.")
    headers: Optional[Dict[str, str]] = Field(None, description="Extra HTTP headers; values may use VAULT::secret_key.")

    @model_validator(mode="after")
    def _merge_inputs_alias(self):
        if self.arguments is None and self.inputs is not None:
            self.arguments = self.inputs
        return self

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
# Tool Generation Workflow Schemas
# ============================================================================

class ToolGenerationWorkflowRequest(BaseModel):
    """Request schema for tool generation via workflow agent."""
    workflow_id: str = Field(..., description="The workflow ID for tool generation agent")
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
    workflow_id: str = Field(..., description="The workflow ID")
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
    workflow_id: str = Field(..., description="The workflow ID")
    role: Literal["user", "assistant"] = Field(..., description="The role: 'user' or 'assistant'")
    message: str = Field(..., description="The message content")
    code_snippet: Optional[str] = Field(None, description="Associated code snippet if any")


class GetConversationHistoryRequest(BaseModel):
    """Request schema for fetching conversation history."""
    session_id: str = Field(..., description="The user's session ID")
    workflow_id: Optional[str] = Field(None, description="Optional workflow ID filter")
    limit: Optional[int] = Field(50, description="Maximum number of messages to return")


class ClearConversationRequest(BaseModel):
    """Request schema for clearing conversation history."""
    session_id: str = Field(..., description="The user's session ID")
    workflow_id: Optional[str] = Field(None, description="Optional workflow ID - if not provided, clears all for session")


class ToolGenerationConversationHistoryRequest(BaseModel):
    """Request schema for fetching conversation history with pagination."""
    session_id: str = Field(..., description="The user's session ID")
    workflow_id: Optional[str] = Field(None, description="Optional workflow ID filter")
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

