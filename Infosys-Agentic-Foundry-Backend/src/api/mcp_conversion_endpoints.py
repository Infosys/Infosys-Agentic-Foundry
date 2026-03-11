# © 2024-25 Infosys Limited, Bangalore, India. All Rights Reserved.

import logging
import ast
import re
import socket
import datetime
from typing import List, Optional, Dict, Any, Tuple
from enum import Enum

from fastapi import APIRouter, Depends, HTTPException, Request, Query, Body
from pydantic import BaseModel, Field
from langchain_core.messages import HumanMessage

# Internal Project Dependencies
from src.database.services import ToolService, McpToolService
from src.api.dependencies import ServiceProvider
from src.auth.dependencies import get_current_user
from src.auth.authorization_service import AuthorizationService
from src.auth.models import User, UserRole
from src.models.model_service import ModelService
from telemetry_wrapper import logger,update_session_context

# Initialize Router
router = APIRouter(prefix="/mcp-conversion", tags=["MCP Conversion"])

# ==================== Schemas ====================

class FunctionInfo(BaseModel):
    name: str
    code: str
    imports: List[str] = []
    docstring: Optional[str] = None

class GenerateMCPServerResponse(BaseModel):
    success: bool
    message: str
    server_name: str
    server_description: str
    generated_code: str
    tool_id: Optional[str]
    saved_to_db: bool

class GenerateMCPFromAllFunctionsRequest(BaseModel):
    tool_ids: List[str] = Field(..., description="List of tool IDs to convert")
    server_name: Optional[str] = None
    server_description: Optional[str] = None

# ==================== Helper Functions ====================

def extract_functions_and_imports(code_snippet: str) -> List[FunctionInfo]:
    """Extracts ONLY top-level function definitions and module imports, removing internal imports from functions."""
    functions = []
    try:
        tree = ast.parse(code_snippet)
        code_lines = code_snippet.split('\n')
        
        # Extract top-level imports
        module_imports = []
        for node in tree.body:
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                import_stmt = ast.get_source_segment(code_snippet, node)
                if import_stmt:
                    module_imports.append(import_stmt)

        # Extract ONLY top-level functions (not nested)
        for node in tree.body:
            if isinstance(node, ast.FunctionDef):
                func_name = node.name
                docstring = ast.get_docstring(node)
                
                # Extract function code and remove internal imports
                func_start = node.lineno - 1
                func_end = node.end_lineno if hasattr(node, 'end_lineno') else len(code_lines)
                func_lines = code_lines[func_start:func_end]
                
                # Remove import statements from within the function
                cleaned_func_lines = []
                inside_function = False
                for i, line in enumerate(func_lines):
                    stripped = line.strip()
                    if i == 0 or inside_function:
                        inside_function = True
                        # Skip import lines inside function body
                        if inside_function and (stripped.startswith('import ') or stripped.startswith('from ')):
                            continue
                        cleaned_func_lines.append(line)
                
                func_code = '\n'.join(cleaned_func_lines)
                
                functions.append(FunctionInfo(
                    name=func_name, code=func_code, imports=module_imports,
                    docstring=docstring
                ))
    except Exception as e:
        logger.error(f"AST Extraction Error: {e}")
    return functions

def generate_server_code(
    functions: List[FunctionInfo],
    server_name: str
) -> str:
    """Assembles the final Python code for LOCAL MCP server with stdio transport."""
    
    # 1. Imports (FastMCP always first)
    unique_imports = set()
    for f in functions:
        for imp in f.imports:
            if "fastmcp" not in imp.lower():
                unique_imports.add(imp)
    
    code_lines = [
        "from fastmcp import FastMCP",
        "\n".join(sorted(list(unique_imports))),
        "",
        "# Create a LOCAL MCP server",
        f'mcp = FastMCP(name="{server_name}")',
        ""
    ]

    # 2. Tools
    for f in functions:
        code_lines.append("@mcp.tool()")
        code_lines.append(f.code)
        code_lines.append("")

    # 3. Main execution block with stdio transport
    code_lines.append('if __name__ == "__main__":')
    code_lines.append('    mcp.run()')

    return "\n".join(code_lines)

async def llm_generate_metadata(functions: List[FunctionInfo], req_name: Optional[str], req_desc: Optional[str]) -> Dict[str, str]:
    """
    Use LLM to generate server name and description if not provided.
    
    Args:
        functions: List of extracted function information
        req_name: Optional user-provided server name
        req_desc: Optional user-provided description
        
    Returns:
        Dictionary containing 'name' and 'description'
    """
    result = {}
    
    try:
        model_service = ServiceProvider.get_model_service()
        llm = await model_service.get_llm_model(model_name=model_service.default_model_name, temperature=0.3)
    except Exception as e:
        logger.error(f"Error creating LLM client: {e}")
        # Fallback metadata generation
        fallback_name = req_name
        fallback_desc = req_desc
        
        if not fallback_name:
            func_names = [f.name for f in functions[:3]]
            if func_names:
                fallback_name = " ".join(func_names).replace('_', ' ').title()[:50] + " Server"
            else:
                fallback_name = "Generated MCP Server"
        
        if not fallback_desc:
            func_count = len(functions)
            func_names = [f.name for f in functions[:5]]
            fallback_desc = f"MCP Server with {func_count} function{'s' if func_count != 1 else ''}: {', '.join(func_names)}"
            if func_count > 5:
                fallback_desc += f" and {func_count - 5} more"
        
        return {"name": fallback_name, "description": fallback_desc}
    
    # Generate name if not provided
    if not req_name:
        functions_summary = ", ".join([f.name for f in functions])
        name_prompt = f"""Based on the following function names, generate a concise, descriptive name for an MCP server:

Functions: {functions_summary}

Generate only a short server name (2-5 words, no quotes):"""
        
        try:
            response = llm.invoke([HumanMessage(content=name_prompt)])
            generated_name = response.content.strip().strip('"\'')
            result["name"] = generated_name
            logger.info(f"LLM generated server name: {generated_name}")
        except Exception as e:
            logger.error(f"Error generating server name: {e}")
            result["name"] = "Generated MCP Server"
    else:
        result["name"] = req_name
    
    # Generate description if not provided
    if not req_desc:
        functions_info = []
        for func in functions:
            func_desc = f"- {func.name}: {func.docstring or 'No description'}"
            functions_info.append(func_desc)
        
        desc_prompt = f"""Generate a clear, professional description for an MCP server that contains these functions:

{chr(10).join(functions_info)}

The description should:
- Be 1-2 sentences
- Explain what the server does overall
- Be professional and concise

Generate only the description (no quotes):"""
        
        try:
            response = llm.invoke([HumanMessage(content=desc_prompt)])
            generated_desc = response.content.strip().strip('"\'')
            result["description"] = generated_desc
            logger.info(f"LLM generated server description: {generated_desc}")
        except Exception as e:
            logger.error(f"Error generating server description: {e}")
            result["description"] = "Auto-generated MCP server with custom functions"
    else:
        result["description"] = req_desc
    
    return result

# ==================== Endpoints ====================

@router.post("/generate-server-from-all", response_model=GenerateMCPServerResponse)
async def process_conversion(
    request: Request,
    body: GenerateMCPFromAllFunctionsRequest,
    tool_service: ToolService = Depends(ServiceProvider.get_tool_service),
    mcp_tool_service: McpToolService = Depends(ServiceProvider.get_mcp_tool_service),
    authorization_service: AuthorizationService = Depends(ServiceProvider.get_authorization_service),
    user_data: User = Depends(get_current_user)
):
    """Convert tool IDs to a LOCAL MCP server script (file-based, stdio transport)."""
    update_session_context(user_id=request.cookies.get("user_id"))
    
    # Department-based permission check
    user_department = user_data.department_name
    if not await authorization_service.check_operation_permission(
        user_data.email, user_data.role, "create", "tools", user_department
    ):
        raise HTTPException(status_code=403, detail="You don't have permission to create MCP servers.")
    
    all_funcs: List[FunctionInfo] = []
    
    # 1. Extraction - include ALL functions (including private functions)
    for tid in body.tool_ids:
        # Use department-filtered tool retrieval (SUPER_ADMIN sees all)
        if user_data.role == UserRole.SUPER_ADMIN:
            tdata_list = await tool_service.get_tool(tool_id=tid)
        else:
            tdata_list = await tool_service.get_tool(tool_id=tid, department_name=user_data.department_name)
        
        tdata = tdata_list[0] if tdata_list else None
        if tdata and tdata.get("code_snippet"):
            extracted = extract_functions_and_imports(tdata["code_snippet"])
            all_funcs.extend(extracted)

    if not all_funcs:
        raise HTTPException(status_code=400, detail="No functions found for selected tools.")

    # Extract function names from selected tools
    function_names = [f.name for f in all_funcs]
    sorted_selected_functions = sorted(function_names)

    # Get all existing MCP servers (department-filtered)
    if user_data.role == UserRole.SUPER_ADMIN:
        existing_tools = await mcp_tool_service.get_all_mcp_tools()
    else:
        existing_tools = await mcp_tool_service.get_all_mcp_tools(department_name=user_data.department_name)

    # Check each server individually for exact match
    for existing_server in existing_tools:
        mcp_config = existing_server.get("mcp_config", {})
        server_functions = mcp_config.get("functions", [])
        
        # Sort this server's functions and compare
        sorted_server_functions = sorted(server_functions)
        
        # Check if EXACT match (same length + same functions)
        if (len(sorted_server_functions) == len(sorted_selected_functions) and
            sorted_server_functions == sorted_selected_functions):
            # Found exact match!
            raise HTTPException(
                status_code=400,
                detail=f"Server already exists with the selected tools. Server name: '{existing_server.get('tool_name')}'"
            )

    # 2. Metadata Generation
    meta = await llm_generate_metadata(all_funcs, body.server_name, body.server_description)

    # Check if server name already exists
    for existing_server in existing_tools:
        if existing_server.get("tool_name") == meta["name"]:
            raise HTTPException(
                status_code=400,
                detail=f"Server name '{meta['name']}' already exists. Please choose a different name."
            )

    # 3. Code Generation (LOCAL only - stdio transport)
    final_code = generate_server_code(all_funcs, meta["name"])

    # 4. Save to DB as LOCAL (file-based) MCP server
    try:
        logger.info(f"Saving LOCAL MCP server: name={meta['name']}, functions={len(function_names)}")
        
        # Create the MCP tool as file type (LOCAL) with department
        if user_data.role == UserRole.SUPER_ADMIN:
            save_result = await mcp_tool_service.create_mcp_tool(
                tool_name=meta["name"],
                tool_description=meta["description"],
                mcp_type="file",
                created_by=user_data.email,
                code_content=final_code
            )
        else:
            save_result = await mcp_tool_service.create_mcp_tool(
                tool_name=meta["name"],
                tool_description=meta["description"],
                mcp_type="file",
                created_by=user_data.email,
                code_content=final_code,
                department_name=user_data.department_name
            )
        
        if save_result.get("is_created"):
            # Update the mcp_config to include server_type and function list
            tool_id = save_result.get("tool_id")
            logger.info(f"MCP tool created with ID: {tool_id}, now updating metadata...")
            logger.info(f"Function names: {function_names}")

            update_success = await mcp_tool_service.mcp_tool_repo.update_mcp_config_metadata(
                tool_id=tool_id,
                server_type="file",
                functions=function_names
            )
            
            if update_success:
                logger.info(f"Successfully updated metadata for {tool_id} with server_type=file")
            else:
                logger.error(f"Failed to update metadata for {tool_id}")
        else:
            logger.error(f"Failed to create MCP tool: {save_result.get('message')}")
        
        # Generate success message
        success_message = f"MCP server '{meta['name']}' created successfully" if save_result.get("is_created") else f"Failed to create MCP server '{meta['name']}'"
        
        return {
            "success": True, 
            "message": success_message,
            "server_name": meta["name"], 
            "server_description": meta["description"],
            "generated_code": final_code,
            "tool_id": save_result.get("tool_id"), 
            "saved_to_db": save_result.get("is_created", False)
        }
    except Exception as e:
        logger.error(f"MCP Save failed: {e}")
        import traceback
        logger.error(f"Traceback: {traceback.format_exc()}")
        raise HTTPException(status_code=500, detail=f"Database save error: {str(e)}")