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



class AddToolRequest(BaseModel):
    """Schema for adding a new tool."""
    tool_description: str = Field(..., description="A brief description of the tool.")
    code_snippet: str = Field(..., description="The Python code snippet for the tool's function.")
    model_name: str = Field(..., description="The name of the LLM model to be used for docstring regeneration.")
    created_by: str = Field(..., description="The email ID of the user who created the tool.")
    tag_ids: Optional[Union[List[str], str]] = Field(None, description="Optional comma-separated string or list of tag IDs for the tool.")
    force_add: Optional[bool] = Field(False, description="Force add flag for bypassing certain validations.")
    is_validator: Optional[bool] = Field(False, description="Indicates if the tool is a validator tool. Validator tools must have exactly 2 parameters (query, response) and return validation results.")


class UpdateToolRequest(BaseModel):
    """Schema for updating an existing tool."""
    model_name: str = Field(..., description="The name of the LLM model to be used for docstring regeneration.")
    user_email_id: str = Field(..., description="The email ID of the user requesting the update.")
    is_admin: bool = Field(False, description="Indicates if the user has admin privileges.")
    tool_description: Optional[str] = Field(None, description="New description for the tool.")
    code_snippet: Optional[str] = Field(None, description="New Python code snippet for the tool.")
    updated_tag_id_list: Optional[Union[List[str], str]] = Field(None, description="Optional list of new tag IDs for the tool.")
    is_validator: Optional[bool] = Field(False, description="Indicates if the tool is a validator tool. Validator tools must have exactly 2 parameters (query, response) and return validation results.")

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

    # # Auth-related fields for internal service logic, not directly from user input for update
    # is_public: Optional[bool] = Field(None, description="New public status for the tool.")
    # status: Optional[str] = Field(None, description="New approval status for the tool ('pending', 'approved', 'rejected').")
    # comments: Optional[str] = Field(None, description="New comments regarding the tool's status or approval.")
    # approved_at: Optional[datetime] = Field(None, description="New timestamp when the tool was approved.")
    # approved_by: Optional[str] = Field(None, description="New user who approved the tool.")

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