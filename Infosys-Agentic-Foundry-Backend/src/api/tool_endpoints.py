# © 2024-25 Infosys Limited, Bangalore, India. All Rights Reserved.
import os
import sys
import ast
import json
import inspect
import asyncpg
from io import StringIO
from typing import List, Optional, Literal, Dict
from fastapi import APIRouter, Depends, HTTPException, Request, UploadFile, Query, File, Form

from src.tools.tool_validation import graph
from src.schemas import ToolData, UpdateToolRequest, DeleteToolRequest, TagIdName, ExecuteRequest, ExecuteResponse, ParamInfo,McpToolUpdateRequest
from src.database.services import ToolService, McpToolService

from src.api.dependencies import ServiceProvider # The dependency provider
from src.utils.secrets_handler import get_user_secrets, current_user_email, get_public_key

from phoenix.otel import register
from phoenix.trace import using_project
from telemetry_wrapper import logger as log, update_session_context


# Create an APIRouter instance for tool-related endpoints
router = APIRouter(prefix="/tools", tags=["Tools"])


@router.post("/add")
async def add_tool_endpoint(request: Request, tool_data: ToolData, tool_service: ToolService = Depends(ServiceProvider.get_tool_service),force_add:Optional[bool] = False):
    """
    Adds a new tool to the tool table.

    Parameters:
    ----------
    tool_data : ToolData
        The data of the tool to be added.

    Returns:
    -------
    dict
        A dictionary containing the status of the operation.
        If the tool name is successfully extracted and inserted
        into the tool table, the status will indicate success.
        Otherwise, it will provide an error message.

    The status dictionary contains:
    - message : str
        A message indicating the result of the operation.
    - tool_id : str
        The ID of the tool (empty if not created).
    - is_created : bool
        Indicates whether the tool was successfully created.
    """
    user_id = request.cookies.get("user_id")
    user_session = request.cookies.get("user_session")
    update_session_context(
        model_used=tool_data.model_name,
        tags=tool_data.tag_ids,
        user_session=user_session,
        user_id=user_id
    )
    register(
            project_name='add-tool',
            auto_instrument=True,
            set_global_tracer_provider=False,
            batch=True
        )
    with using_project('add-tool'):
        status = await tool_service.create_tool(tool_data=dict(tool_data),force_add=force_add)
        log.debug(f"Tool creation status: {status}")

    update_session_context(model_used='Unassigned',
                            tags='Unassigned',
                            tool_id='Unassigned',
                            tool_name='Unassigned',)
    if not status.get("is_created"):
        raise HTTPException(status_code=400, detail=status.get("message"))
    return status


@router.get("/get")
async def get_all_tools_endpoint(request: Request, tool_service: ToolService = Depends(ServiceProvider.get_tool_service)):
    """
    Retrieves all tools from the tool table.

    Returns:
    -------
    list
        A list of tools. If no tools are found, raises an HTTPException with status code 404.
    """
    user_id = request.cookies.get("user_id")
    user_session = request.cookies.get("user_session")
    update_session_context(user_session=user_session, user_id=user_id)
    tools = await tool_service.get_all_tools()
    if not tools:
        raise HTTPException(status_code=404, detail="No tools found")
    return tools


@router.get("/get/{tool_id}")
async def get_tool_by_id_endpoint(request: Request, tool_id: str, tool_service: ToolService = Depends(ServiceProvider.get_tool_service)):
    """
    Retrieves a tool by its ID.

    Parameters:
    ----------
    id : str
        The ID of the tool to be retrieved.

    Returns:
    -------
    dict
        A dictionary containing the tool's details.
        If the tool is not found, raises an HTTPException with status code 404.
    """
    user_id = request.cookies.get("user_id")
    user_session = request.cookies.get("user_session")
    update_session_context(tool_id=tool_id, user_session=user_session, user_id=user_id)
    tool = await tool_service.get_tool(tool_id=tool_id)
    if not tool:
        raise HTTPException(status_code=404, detail="Tool not found")
    update_session_context(tool_id='Unassigned')
    return tool


@router.post("/get/by-list")
async def get_tools_by_list_endpoint(request: Request, tool_ids: List[str], tool_service: ToolService = Depends(ServiceProvider.get_tool_service)):
    """Retrieves tools by a list of IDs."""
    user_id = request.cookies.get("user_id")
    user_session = request.cookies.get("user_session")
    update_session_context(user_session=user_session, user_id=user_id)
    
    tools = []
    for tool_id in tool_ids:
        tool = await tool_service.get_tool(tool_id=tool_id)
        if tool:
            tools.append(tool[0]) # get_tool returns a list
    return tools


@router.get("/get/search-paginated/")
async def search_paginated_tools_endpoint(
        request: Request,
        search_value: Optional[str] = Query(None),
        page_number: int = Query(1, ge=1),
        page_size: int = Query(20, ge=1),
        tag_names: List[str] = Query(None, description="Filter by tag names"),
        tool_service: ToolService = Depends(ServiceProvider.get_tool_service)
    ):
    """Searches tools with pagination."""
    user_id = request.cookies.get("user_id")
    user_session = request.cookies.get("user_session")
    update_session_context(user_session=user_session, user_id=user_id)
    

    result = await tool_service.get_tools_by_search_or_page(search_value=search_value, limit=page_size, page=page_number,tag_names=tag_names)
    if not result["details"]:
        raise HTTPException(status_code=404, detail="No tools found matching criteria.")
    return result


@router.post("/get/by-tags")
async def get_tools_by_tag_endpoint(request: Request, tag_data: TagIdName, tool_service: ToolService = Depends(ServiceProvider.get_tool_service)):
    """
    API endpoint to retrieve tools associated with given tag IDs or tag names.

    Parameters:
    - request: The FastAPI Request object.
    - tag_data: Pydantic model containing tag IDs or names.
    - tool_service: Dependency-injected ToolService instance.

    Returns:
    - List[Dict[str, Any]]: A list of tools.
    """
    user_id = request.cookies.get("user_id")
    user_session = request.cookies.get("user_session")
    update_session_context(user_session=user_session, user_id=user_id)

    result = await tool_service.get_tools_by_tags(
        tag_ids=tag_data.tag_ids,
        tag_names=tag_data.tag_names
    )
    if not result:
        raise HTTPException(status_code=404, detail="Tools not found")
    return result


@router.put("/update/{tool_id}")
async def update_tool_endpoint(request: Request, tool_id: str, update_request: UpdateToolRequest, tool_service: ToolService = Depends(ServiceProvider.get_tool_service)):
    """
    Updates a tool by its ID.

    Parameters:
    ----------
    id : str
        The ID of the tool to be updated.
    request : UpdateToolRequest
        The request body containing the update details.

    Returns:
    -------
    dict
        A dictionary containing the status of the update operation.
        If the update is unsuccessful, raises an HTTPException with
        status code 400 and the status message.
    """
    previous_value = await tool_service.get_tool(tool_id=tool_id)
    user_id = request.cookies.get("user_id")
    user_session = request.cookies.get("user_session")
    update_session_context(tool_id=tool_id, tags=update_request.updated_tag_id_list, model_used=update_request.model_name,
                            action_type='update', action_on='tool', previous_value=previous_value, user_session=user_session, user_id=user_id)

    register(
            project_name='update-tool',
            auto_instrument=True,
            set_global_tracer_provider=False,
            batch=True
        )
    with using_project('update-tool'):
        response = await tool_service.update_tool(
            tool_id=tool_id,
            model_name=update_request.model_name,
            code_snippet=update_request.code_snippet,
            tool_description=update_request.tool_description,
            updated_tag_id_list=update_request.updated_tag_id_list,
            user_id=update_request.user_email_id,
            is_admin=update_request.is_admin
        )

    if response["is_update"]:
        new_value=await tool_service.get_tool(tool_id=tool_id)
        update_session_context(new_value=new_value)
        log.debug(f"Tool update status: {response}")
        update_session_context(new_value='Unassigned')
    update_session_context(tool_id='Unassigned',tags='Unassigned',model_used='Unassigned',action_type='Unassigned',
                        action_on='Unassigned',previous_value='Unassigned',new_value='Unassigned')

    if not response.get("is_update"):
        log.error(f"Tool update failed: {response['status_message']}")
        raise HTTPException(status_code=400, detail=response.get("status_message"))
    return response


@router.delete("/delete/{tool_id}")
async def delete_tool_endpoint(request: Request, tool_id: str, delete_request: DeleteToolRequest, tool_service: ToolService = Depends(ServiceProvider.get_tool_service)):
    """
    Deletes a tool by its ID.

    Parameters:
    ----------
    id : str
        The ID of the tool to be deleted.
    request : DeleteToolRequest
        The request body containing the user email ID and admin status.

    Returns:
    -------
    dict
        A dictionary containing the status of the deletion operation.
    """
    previous_value = await tool_service.get_tool(tool_id=tool_id)
    if not previous_value:
        raise HTTPException(status_code=404, detail="Tool not found")
    previous_value = previous_value[0]
    user_id = request.cookies.get("user_id")
    user_session = request.cookies.get("user_session")
    update_session_context(user_session=user_session, user_id=user_id, tool_id=tool_id, action_on='tool', action_type='delete', previous_value=previous_value)

    status = await tool_service.delete_tool(
        tool_id=tool_id,
        user_id=delete_request.user_email_id,
        is_admin=delete_request.is_admin
    )
    update_session_context(tool_id='Unassigned',action_on='Unassigned', action_type='Unassigned',previous_value='Unassigned') # Telemetry context clear
    if not status.get("is_delete"):
        raise HTTPException(status_code=400, detail=status.get("status_message"))
    return status

@router.post("/execute", response_model=ExecuteResponse)
async def execute(request: Request, execute_request: ExecuteRequest):
    # --- Syntax check ---
    try:
        compiled = compile(execute_request.code, "<string>", "exec")
    except SyntaxError as se:
        return ExecuteResponse(success=False, error=f"SyntaxError: {se.msg} at line {se.lineno}")

    # --- Function extraction ---
    try:
        tree = ast.parse(execute_request.code)
        func_defs = [node for node in tree.body if isinstance(node, ast.FunctionDef)]
        if len(func_defs) == 0:
            return ExecuteResponse(success=False, error="No function definition found in code")
        if len(func_defs) > 1:
            return ExecuteResponse(success=False, error="More than one function definition found. Input must only have a single function definition.")
        func = func_defs[0]
    except Exception as e:
        return ExecuteResponse(success=False, error=f"Error parsing code: {str(e)}")

    initial_state = {
        "code": execute_request.code,
        "validation_case1": None,
        "feedback_case1": None,
        "validation_case3": None,
        "feedback_case3": None,
        "validation_case4": None,
        "feedback_case4": None,
        "validation_case5": None,
        "feedback_case5": None,
        "validation_case6": None,
        "feedback_case6": None,
        "validation_case7": None,
        "feedback_case7": None
    }

    # Await workflow validation results
    workflow_result = await graph.ainvoke(input=initial_state)
    e_cases = ["validation_case1","validation_case4","validation_case6","validation_case7"]
    feedbacks = []
    for j in e_cases:
        if not workflow_result.get(j):
            feedback_key = j.replace("validation_", "feedback_")
            val = workflow_result.get(feedback_key)
            if val:
                feedbacks.append(val)
    if feedbacks:
        return ExecuteResponse(
            inputs_required=[],
            output=None,
            output_type=None,
            error=feedbacks[0],
            success=not bool(feedbacks),
            feedback=feedbacks if feedbacks else None
        )
    # --- Get all function parameters to inform the user ---
    try:
        global_ns = {
            "get_user_secrets": get_user_secrets,
            "current_user_email": current_user_email,
            "get_public_secrets": get_public_key
        }
        # exec(execute_request.code, global_ns)
        # func_object = global_ns[func.name]
        # sig = inspect.signature(func_object)
        # all_params = [p.name for p in sig.parameters.values()]
        # required_params = [p.name for p in sig.parameters.values() if p.default is inspect.Parameter.empty]
        # supplied_inputs = execute_request.inputs or {}
        # missing_required = [arg for arg in required_params if arg not in supplied_inputs]

        # if missing_required:
        #     return ExecuteResponse(
        #         inputs_required=all_params,
        #         output=None,
        #         output_type=None,
        #         error="",
        #         success=False,
        #         feedback=None
        #     )
        exec(execute_request.code, global_ns)
        func_object = global_ns[func.name]
        sig = inspect.signature(func_object)
        
        # Create the new list of ParamInfo objects
        all_params_info = []
        required_params = []
        for p in sig.parameters.values():
            default_val = None
            if p.default is not inspect.Parameter.empty or p.default is None:
                if p.default is None:
                    default_val = "None"
                else:
                    default_val = p.default
            else:
                required_params.append(p.name)
            
            all_params_info.append(ParamInfo(name=p.name, default=default_val))

        supplied_inputs = execute_request.inputs or {}
        missing_required = [arg for arg in required_params if arg not in supplied_inputs]
        default_vals_count = sum(1 for p in sig.parameters.values() if p.default is not inspect.Parameter.empty)
        if not all_params_info:
            execute_request.handle_default = True  # No params, so set to True to proceed with execution
        if (missing_required and not execute_request.handle_default) or (len(supplied_inputs) < (len(sig.parameters) - default_vals_count)) or (default_vals_count and not execute_request.handle_default) or (not missing_required and not execute_request.handle_default):
            return ExecuteResponse(
                inputs_required=all_params_info,
                output=None,
                output_type=None,
                error="",
                success=False,
                feedback=None
            )
    except Exception as e:
        return ExecuteResponse(success=False, error=f"Error processing function signature: {str(e)}")
    # --- Convert inputs and apply defaults for execution ---
    if execute_request.handle_default:
        converted_inputs = {}
        try:
            for param_name, param in sig.parameters.items():
                if param_name in supplied_inputs and supplied_inputs[param_name] != "":
                    input_value = supplied_inputs[param_name]
                        
                    # Check for types that need literal evaluation
                    annotation_type = getattr(param.annotation, '__origin__', param.annotation)
                    if annotation_type in (dict, list, set, tuple):
                        try:
                            literal_value = ast.literal_eval(input_value)

                            if not isinstance(literal_value, annotation_type):
                                return ExecuteResponse(
                                    success=False,
                                    error=f"Type mismatch for input '{param_name}'. Expected '{annotation_type.__name__}' but got '{type(literal_value).__name__}'.",
                                    inputs_required=all_params_info
                                )
                                
                            converted_inputs[param_name] = literal_value
                                
                        except (ValueError, SyntaxError):
                            return ExecuteResponse(
                                success=False,
                                error=f"Invalid format for input '{param_name}'. Expected a valid Python literal.",
                                inputs_required=all_params_info
                            )
                    # Handle other basic types
                    elif param.annotation is not inspect.Parameter.empty and param.annotation is not str:
                        try:
                            converted_inputs[param_name] = param.annotation(input_value)
                        except ValueError:
                            return ExecuteResponse(
                                success=False, 
                                error=f"Invalid type for input '{param_name}'. Expected '{param.annotation.__name__}'.",
                                inputs_required=all_params_info
                            )
                    else:
                        converted_inputs[param_name] = input_value
                elif param.default is not inspect.Parameter.empty:
                    converted_inputs[param_name] = param.default
            converted_inputs = {k: (None if v == 'None' else v) for k, v in converted_inputs.items()}
        except Exception as e:
            return ExecuteResponse(success=False, error=f"Error converting input types or applying defaults: {str(e)}")

        # --- Run function with converted inputs ---
        output = None
        otype=None
        error = ""
        try:
            old_stdout = sys.stdout
            sys.stdout = mystdout = StringIO()
            result = global_ns[func.name](**converted_inputs)
            output = mystdout.getvalue()
            if result is not None:
                output = result
                otype = type(output).__name__ if output is not None else None
        except Exception as e:
            error = str(e)
        finally:
            sys.stdout = old_stdout

        return ExecuteResponse(
            inputs_required=all_params_info,
            output=output,
            output_type=otype,
            error=error,
            success=not bool(error),
            feedback=None
        )

# MCP Tool / Server

@router.post("/mcp/add")
async def add_mcp_tool_endpoint(
        request: Request,
        tool_name: str = Form(..., description="The unique name of the MCP tool server."),
        tool_description: str = Form(..., description="A brief description of the MCP tool server."),
        mcp_type: Literal["file", "url", "module"] = Form(..., description="The type of MCP tool: 'file' (code content), 'url' (HTTP server), or 'module' (Python module)."),
        created_by: str = Form(..., description="The email ID of the user creating the MCP tool."),
        
        # Optional fields for different MCP types
        mcp_url: Optional[str] = Form(None, description="The URL of the MCP server (required if mcp_type is 'url')."),
        headers: Optional[str] = Form(None, description="Optional: JSON string of HTTP headers for 'url' type MCP server. Values can be literal strings or vault references (  e.g., \"{'Content-Type': 'application/json', 'Authorization': 'VAULT::MY_API_KEY_SECRET_NAME', 'X-Custom-ID': 'VAULT::ANOTHER_SECRET', 'X-Literal-Value': 'some-fixed-string'}\"  )."),
        mcp_module_name: Optional[str] = Form(None, description="The Python module name for the MCP server (required if mcp_type is 'module')."),
        code_content: Optional[str] = Form(None, description="The Python code content for the MCP server (required if mcp_type is 'file' and no file is uploaded)."),
        mcp_file: UploadFile = File(None, description="Optional: Upload a .py file for 'file' type MCP tools (required if mcp_type is 'file' and code_content is empty)."),

        tag_ids: List[str] = Form(None, description="Optional list of tag IDs for the tool."),

        mcp_tool_service: McpToolService = Depends(ServiceProvider.get_mcp_tool_service)
    ):
    """
    Adds a new MCP tool (server definition) to the database.
    Supports 'file', 'url', and 'module' based MCP servers.
    For 'file' type, allows direct code content or a .py file upload.
    """
    user_id = request.cookies.get("user_id")
    user_session = request.cookies.get("user_session")

    final_code_content = code_content
    if mcp_type == "file":
        if mcp_file:
            if not mcp_file.filename.endswith(".py"):
                raise HTTPException(status_code=400, detail="Only .py files can be uploaded for 'file' type MCP tools.")
            final_code_content = await mcp_tool_service._read_uploaded_file_content(mcp_file)
            if not final_code_content:
                raise HTTPException(status_code=400, detail="Uploaded file is empty or could not be read.")
        elif not code_content:
            raise HTTPException(status_code=400, detail="Either 'code_content' or a '.py' file must be provided for 'file' type MCP tools.")

    # Convert tag_ids from comma-separated string to list if necessary
    if isinstance(tag_ids, str):
        tag_ids = [t.strip() for t in tag_ids.split(',') if t.strip()]

    # Parse headers JSON string if provided
    parsed_headers: Optional[Dict[str, str]] = None
    if headers:
        try:
            parsed_headers = json.loads(headers)
            if not isinstance(parsed_headers, dict):
                raise ValueError("Headers must be a JSON object.")
        except json.JSONDecodeError as e:
            raise HTTPException(status_code=400, detail=f"Invalid JSON format for 'headers' field: {e}")
        except ValueError as e:
            raise HTTPException(status_code=400, detail=f"Invalid 'headers' field: {e}")

    update_session_context(user_session=user_session, user_id=user_id)
    try:
        status = await mcp_tool_service.create_mcp_tool(
            tool_name=tool_name.strip(),
            tool_description=tool_description.strip(),
            mcp_type=mcp_type,
            created_by=created_by,
            tag_ids=tag_ids,
            mcp_url=mcp_url,
            headers=parsed_headers,
            mcp_module_name=mcp_module_name,
            code_content=final_code_content
        )

    except Exception as e:
        log.error(f"Error during MCP tool onboarding: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"Error during MCP tool onboarding: {str(e)}"
        ) from e

    finally:
        update_session_context(user_session="Unassigned", user_id="Unassigned")

    if not status.get("is_created"):
        raise HTTPException(status_code=400, detail=status.get("message"))
    return {"status": "success", "result": status}


@router.get("/mcp/get")
async def get_all_mcp_tools_endpoint(request: Request, mcp_tool_service: McpToolService = Depends(ServiceProvider.get_mcp_tool_service)):
    """
    Retrieves all MCP tool (server definition) records.
    """
    user_id = request.cookies.get("user_id")
    user_session = request.cookies.get("user_session")
    update_session_context(user_session=user_session, user_id=user_id)

    try:
        tools = await mcp_tool_service.get_all_mcp_tools()
        if not tools:
            raise HTTPException(status_code=404, detail="No MCP tools found")
        return tools
    except Exception as e:
        log.error(f"Error retrieving all MCP tools: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error retrieving all MCP tools: {str(e)}")


@router.get("/mcp/get/{tool_id}")
async def get_mcp_tool_by_id_endpoint(
        request: Request,
        tool_id: str,
        mcp_tool_service: McpToolService = Depends(ServiceProvider.get_mcp_tool_service)
    ):
    """
    Retrieves a single MCP tool (server definition) record by its ID.
    """
    user_id = request.cookies.get("user_id")
    user_session = request.cookies.get("user_session")
    update_session_context(user_session=user_session, user_id=user_id, tool_id=tool_id)

    try:
        tool = await mcp_tool_service.get_mcp_tool(tool_id=tool_id)
        if not tool:
            raise HTTPException(status_code=404, detail=f"MCP tool with ID '{tool_id}' not found")
        return tool
    except Exception as e:
        log.error(f"Error retrieving MCP tool '{tool_id}': {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error retrieving MCP tool '{tool_id}': {str(e)}")

    finally:
        update_session_context(tool_id="Unassigned", user_session="Unassigned", user_id="Unassigned")


@router.get("/mcp/get/search-paginated/")
async def search_paginated_mcp_tools_endpoint(
        request: Request,
        search_value: Optional[str] = Query(None),
        page_number: int = Query(1, ge=1),
        page_size: int = Query(20, ge=1),
        tag_names: List[str] = Query(None, description="Filter by tag names"),
        mcp_type: List[str] = Query(None, description="Filter by MCP type: 'file', 'url', or 'module'."),
        mcp_tool_service: McpToolService = Depends(ServiceProvider.get_mcp_tool_service)
    ):
    """
    Searches MCP tool (server definition) records with pagination.
    """
    user_id = request.cookies.get("user_id")
    user_session = request.cookies.get("user_session")
    update_session_context(user_session=user_session, user_id=user_id)

    if mcp_type:
        allowed_mcp_types = set(["file", "url", "module"])
        cur_mcp_types = set(mcp_type)
        if not cur_mcp_types.issubset(allowed_mcp_types):
            raise HTTPException(status_code=400, detail=f"Invalid mcp_type filter. Allowed values are {allowed_mcp_types}.")
        mcp_type = list(cur_mcp_types)

    try:
        result = await mcp_tool_service.get_mcp_tools_by_search_or_page(
            search_value=search_value,
            limit=page_size,
            page=page_number,
            mcp_type=mcp_type,
            tag_names=tag_names
        )
        if not result["details"]:
            raise HTTPException(status_code=404, detail="No MCP tools found matching criteria.")
        return result
    except Exception as e:
        log.error(f"Error searching paginated MCP tools: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error searching paginated MCP tools: {str(e)}")


@router.put("/mcp/update/{tool_id}")
async def update_mcp_tool_endpoint(
        request: Request,
        tool_id: str,
        update_request_data: McpToolUpdateRequest,
        mcp_tool_service: McpToolService = Depends(ServiceProvider.get_mcp_tool_service)
    ):
    """
    Updates an existing MCP tool (server definition) record.
    Only allows 'code_content' updates for 'mcp_file_' type tools.
    """
    user_id = request.cookies.get("user_id")
    user_session = request.cookies.get("user_session")
    update_session_context(user_session=user_session, user_id=user_id, tool_id=tool_id)

    try:
        status = await mcp_tool_service.update_mcp_tool(
            tool_id=tool_id,
            user_id=update_request_data.user_email_id,
            is_admin=update_request_data.is_admin,
            tool_description=update_request_data.tool_description,
            code_content=update_request_data.code_content,
            updated_tag_id_list=update_request_data.updated_tag_id_list,
        )

    except Exception as e:
        log.error(f"Error updating MCP tool '{tool_id}': {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error updating MCP tool '{tool_id}': {str(e)}")

    finally:
        update_session_context(tool_id='Unassigned')

    if not status.get("is_update"):
        raise HTTPException(status_code=400, detail=status.get("status_message"))
    return status


@router.delete("/mcp/delete/{tool_id}")
async def delete_mcp_tool_endpoint(
        request: Request,
        tool_id: str,
        delete_request_data: DeleteToolRequest,
        mcp_tool_service: McpToolService = Depends(ServiceProvider.get_mcp_tool_service)
    ):
    """
    Deletes an MCP tool (server definition) record from the database.
    """
    user_id = request.cookies.get("user_id")
    user_session = request.cookies.get("user_session")
    update_session_context(user_session=user_session, user_id=user_id, tool_id=tool_id)

    try:
        status = await mcp_tool_service.delete_mcp_tool(
            tool_id=tool_id,
            user_id=delete_request_data.user_email_id,
            is_admin=delete_request_data.is_admin
        )
    except Exception as e:
        log.error(f"Error deleting MCP tool '{tool_id}': {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error deleting MCP tool '{tool_id}': {str(e)}")
    finally:
        update_session_context(tool_id='Unassigned')

    if not status.get("is_delete"):
        raise HTTPException(status_code=400, detail=status.get("status_message"))
    return status


@router.get("/mcp/get/live-tool-details/{tool_id}")
async def get_live_mcp_tool_details_endpoint(
        request: Request,
        tool_id: str,
        mcp_tool_service: McpToolService = Depends(ServiceProvider.get_mcp_tool_service)
    ):
    """
    Connects to the live MCP server defined by the tool_id and retrieves details
    (name, description, args) of the individual tools it exposes for UI display.
    """
    user_id = request.cookies.get("user_id")
    user_session = request.cookies.get("user_session")
    update_session_context(user_session=user_session, user_id=user_id, tool_id=tool_id)

    try:
        details = await mcp_tool_service.get_mcp_tool_details_for_display(tool_id=tool_id)
        if not details:
            raise HTTPException(status_code=404, detail=f"No live tools found for MCP server '{tool_id}' or server is unreachable.")
        
        # Check for error messages from the service layer
        if details and isinstance(details[0], dict) and "error" in details[0]:
            raise HTTPException(status_code=500, detail=details[0]["error"])
            
        return details
    except HTTPException:
        raise # Re-raise HTTPExceptions directly
    except Exception as e:
        log.error(f"Error getting live MCP tool details for '{tool_id}': {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error getting live MCP tool details for '{tool_id}': {str(e)}")
    finally:
        update_session_context(tool_id='Unassigned')


# Recycle bin requires modification with proper login/authentication functionality

@router.get("/recycle-bin/get")
async def get_all_tools_from_recycle_bin_endpoint(request: Request, user_email_id: str = Query(...), tool_service: ToolService = Depends(ServiceProvider.get_tool_service)):
    """Retrieves all tools from the recycle bin."""
    user_id = request.cookies.get("user_id")
    user_session = request.cookies.get("user_session")
    update_session_context(user_session=user_session, user_id=user_id)
    
    connection_login = await asyncpg.connect(
        host=os.getenv("POSTGRESQL_HOST"),
        database="login",
        user=os.getenv("POSTGRESQL_USER"),
        password=os.getenv("POSTGRESQL_PASSWORD")
    )
    user_role = await connection_login.fetchval("SELECT role FROM login_credential WHERE mail_id = $1", user_email_id)
    if user_role.lower() != "admin":
        raise HTTPException(status_code=403, detail="You are not authorized to access this resource")
    await connection_login.close()

    tools = await tool_service.get_all_tools_from_recycle_bin()
    if not tools:
        raise HTTPException(status_code=404, detail="No tools found in recycle bin")
    return tools


@router.post("/recycle-bin/restore/{tool_id}")
async def restore_tool_endpoint(request: Request, tool_id: str, user_email_id: str = Query(...), tool_service: ToolService = Depends(ServiceProvider.get_tool_service)):
    """Restores a tool from the recycle bin."""
    user_id = request.cookies.get("user_id")
    user_session = request.cookies.get("user_session")
    update_session_context(user_session=user_session, user_id=user_id)
    
    connection_login = await asyncpg.connect(
        host=os.getenv("POSTGRESQL_HOST"),
        database="login",
        user=os.getenv("POSTGRESQL_USER"),
        password=os.getenv("POSTGRESQL_PASSWORD")
    )
    user_role = await connection_login.fetchval("SELECT role FROM login_credential WHERE mail_id = $1", user_email_id)
    if user_role.lower() != "admin":
        raise HTTPException(status_code=403, detail="You are not authorized to access this resource")
    await connection_login.close()

    result = await tool_service.restore_tool(tool_id=tool_id)
    if not result.get("is_restored"):
        raise HTTPException(status_code=400, detail=result.get("status_message"))
    return result


@router.delete("/recycle-bin/permanent-delete/{tool_id}")
async def delete_tool_from_recycle_bin_endpoint(request: Request, tool_id: str, user_email_id: str = Query(...), tool_service: ToolService = Depends(ServiceProvider.get_tool_service)):
    """Permanently deletes a tool from the recycle bin."""
    user_id = request.cookies.get("user_id")
    user_session = request.cookies.get("user_session")
    update_session_context(user_session=user_session, user_id=user_id)
    
    connection_login = await asyncpg.connect(
        host=os.getenv("POSTGRESQL_HOST"),
        database="login",
        user=os.getenv("POSTGRESQL_USER"),
        password=os.getenv("POSTGRESQL_PASSWORD")
    )
    user_role = await connection_login.fetchval("SELECT role FROM login_credential WHERE mail_id = $1", user_email_id)
    if user_role.lower() != "admin":
        raise HTTPException(status_code=403, detail="You are not authorized to access this resource")
    await connection_login.close()

    result = await tool_service.delete_tool_from_recycle_bin(tool_id=tool_id)
    if not result.get("is_delete"):
        raise HTTPException(status_code=400, detail=result.get("status_message"))
    return result


