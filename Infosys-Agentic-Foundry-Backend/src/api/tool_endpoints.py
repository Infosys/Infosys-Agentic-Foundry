# © 2024-25 Infosys Limited, Bangalore, India. All Rights Reserved.
import os
import sys
import ast
import json
import inspect
import time
import asyncio
from io import StringIO
from datetime import datetime, timezone
import pytz
from typing import List, Optional, Literal, Dict, Any, Union, get_origin, get_args, Tuple, Set
from enum import Enum
try:
    from dataclasses import is_dataclass, fields, MISSING
except Exception:  # pragma: no cover
    def is_dataclass(x):
        return False
    MISSING = object()
    def fields(x):
        return []
from fastapi import APIRouter, Depends, HTTPException, Request, UploadFile, Query, File, Form

from src.tools.tool_validation import graph
from src.schemas import ToolData, UpdateToolRequest, DeleteToolRequest, TagIdName, ExecuteRequest, ExecuteResponse, ParamInfo, McpToolUpdateRequest, McpToolTestRequest, McpToolTestResponse, InlineMcpRequest, InlineMcpIntrospectResponse, InlineMcpExecuteResponse, InlineMcpErrorResponse
from src.database.services import ToolService, McpToolService

from src.api.dependencies import ServiceProvider # The dependency provider
from src.utils.secrets_handler import get_user_secrets, current_user_email, get_public_key
from src.auth.dependencies import get_current_user
from src.auth.models import User, UserRole

from phoenix.otel import register
from telemetry_wrapper import logger as log, update_session_context
from src.utils.phoenix_manager import ensure_project_registered, traced_project_context_sync

from src.auth.authorization_service import AuthorizationService
from src.auth.models import UserRole, User
from src.auth.dependencies import get_current_user

# Create an APIRouter instance for tool-related endpoints
router = APIRouter(prefix="/tools", tags=["Tools"])

# Helper functions for inline MCP processing

def _compile_and_exec_code(code: str) -> tuple[dict, Optional[str]]:
    """
    Compile and execute Python code in a restricted environment.
    Returns (exec_globals, error_message).
    """
    try:
        compiled = compile(code, "<inline_mcp>", "exec")
    except SyntaxError as e:
        return {}, f"Syntax error: {e.msg} at line {e.lineno}"
    
    # Create restricted globals - need to include __import__ and other essentials for FastMCP
    safe_builtins = {
        "len": len, "range": range, "min": min, "max": max, "sum": sum, 
        "abs": abs, "enumerate": enumerate, "isinstance": isinstance,
        "str": str, "int": int, "float": float, "bool": bool, "list": list,
        "dict": dict, "tuple": tuple, "set": set, "type": type, "getattr": getattr,
        "setattr": setattr, "hasattr": hasattr, "callable": callable,
        "__import__": __import__, "object": object, "super": super,
        "property": property, "classmethod": classmethod, "staticmethod": staticmethod,
        "Exception": Exception, "ValueError": ValueError, "TypeError": TypeError,
        "AttributeError": AttributeError, "KeyError": KeyError, "IndexError": IndexError,
        # Added for inline MCP sandbox completeness (previously present before revert):
        # 'sorted' is commonly used in user snippets; '__build_class__' required for class/Enum definitions.
        "sorted": sorted,
        "__build_class__": __build_class__,
    }
    exec_globals = {
        "__name__": "__inline_mcp__",
        "__builtins__": safe_builtins
    }
    
    try:
        exec(compiled, exec_globals)
        return exec_globals, None
    except Exception as e:
        return {}, f"Execution error: {str(e)}"

def _extract_mcp_object(exec_globals: dict) -> tuple[Any, Optional[str]]:
    """
    Extract the mcp object from executed globals.
    Returns (mcp_object, error_message).
    """
    mcp = exec_globals.get("mcp")
    if mcp is None:
        return None, "MCP_OBJECT_NOT_FOUND"
    return mcp, None

def _discover_tools(mcp_obj, exec_globals: Optional[dict] = None, debug: bool = False) -> tuple[dict, Optional[str], list]:
    """
    Deterministic multi-strategy MCP tool discovery (simplified, no scoring).
    Strategies (stop at first producing user-facing tools):
      1. Public API get_tools()
      2. Known registries on root
      3. Known registries on nested server/app objects
      4. Public attribute scan (callables) excluding known internal names
      5. Inline globals fallback (functions from executed snippet)

    Returns: (tools_dict, error_code, trace_list)
      error_code is None on success, else "NO_TOOLS_DISCOVERED".
      trace_list contains minimal diagnostics if debug=True, else empty.
    """
    trace: list[str] = []
    def log(msg: str):
        if debug:
            trace.append(msg)

    internal_names = {
        'custom_route','http_app','run_http_async','run_streamable_http_async',
        'streamable_http_app','mount','unmount','import_server','sse_app'
    }
    attr_func_candidates = ("handler","fn","func","callback","_function")
    registry_names = ["_tools","tools","_tool_registry","registry","_registry"]

    def normalize_collection(collection) -> dict:
        result = {}
        if isinstance(collection, dict):
            iterable = collection.items()
        else:
            iterable = collection or []
        for entry in iterable:
            if isinstance(collection, dict):
                name, obj = entry
            else:
                obj = entry
                name = getattr(obj, 'name', None)
            if not name:
                continue
            func = None
            if callable(obj):
                func = obj
            else:
                for attr in attr_func_candidates:
                    if hasattr(obj, attr):
                        cand = getattr(obj, attr)
                        if callable(cand):
                            func = cand
                            break
            if func:
                result[name] = func
        return result

    # Strategy 1: public API
    tools: dict[str, Any] = {}
    try:
        if hasattr(mcp_obj, 'get_tools') and callable(getattr(mcp_obj, 'get_tools')):
            raw = mcp_obj.get_tools()
            if inspect.iscoroutine(raw):
                # Do not attempt asyncio.run inside existing loops; just skip async variant for now.
                log('get_tools() returned coroutine - skipping await (sync context).')
                raw = None
            if raw is not None:
                tools = normalize_collection(raw)
                log(f"strategy:get_tools count:{len(tools)}")
    except Exception as e:
        log(f"strategy:get_tools error:{e}")
    if tools:
        log('selected:get_tools')
    
    # Strategy 2: root registries
    if not tools:
        for reg_name in registry_names:
            if hasattr(mcp_obj, reg_name):
                reg = getattr(mcp_obj, reg_name)
                normalized = normalize_collection(reg)
                if normalized:
                    tools = normalized
                    log(f"strategy:registry:{reg_name} count:{len(tools)}")
                    break
    # Strategy 3: nested containers
    if not tools:
        for nested_name in ("app","_app","server","_server"):
            if not hasattr(mcp_obj, nested_name):
                continue
            nested = getattr(mcp_obj, nested_name)
            for reg_name in registry_names + ["tools","_registered_tools"]:
                if hasattr(nested, reg_name):
                    reg = getattr(nested, reg_name)
                    normalized = normalize_collection(reg)
                    if normalized:
                        tools = normalized
                        log(f"strategy:nested:{nested_name}.{reg_name} count:{len(tools)}")
                        break
            if tools:
                break
    # Strategy 4: attribute scan
    if not tools:
        scanned = {}
        skip_base = internal_names | {
            'add_tool','add_resource','add_prompt','tool','resource','prompt','run','run_async',
            'run_stdio_async','run_sse_async','get_tools','get_resources','get_prompts','get_context',
            'from_client','from_fastapi','from_openapi','get_resource_templates','add_resource_fn'
        }
        for name in dir(mcp_obj):
            if name.startswith('_') or name in skip_base:
                continue
            attr = getattr(mcp_obj, name)
            if callable(attr) and hasattr(attr, '__code__'):
                scanned[name] = attr
        if scanned:
            tools = scanned
            log(f"strategy:attribute_scan count:{len(tools)}")
    # Strategy 5: inline globals fallback
    used_inline_fallback = False
    if not tools and exec_globals:
        inline_funcs = {}
        for name, obj in exec_globals.items():
            if name == 'mcp':
                continue
            if callable(obj) and hasattr(obj, '__code__'):
                filename = getattr(obj.__code__, 'co_filename', '')
                if '<inline_mcp>' in filename:
                    inline_funcs[name] = obj
        if inline_funcs:
            tools = inline_funcs
            used_inline_fallback = True
            log(f"strategy:inline_globals count:{len(tools)}")

    # Internal filtering: remove infrastructure names when we have any inline or non-internal functions
    if tools:
        # Determine inline origin presence
        has_inline_origin = any(
            hasattr(fn, '__code__') and '<inline_mcp>' in getattr(fn.__code__, 'co_filename', '')
            for fn in tools.values()
        )
        if has_inline_origin:
            removed = 0
            for iname in list(tools.keys()):
                if iname in internal_names:
                    tools.pop(iname, None)
                    removed += 1
            if removed:
                log(f"filter:removed_internal {removed}")

    if not tools:
        log('result:none')
        return {}, "NO_TOOLS_DISCOVERED", trace if debug else []
    log(f"result:success final_count:{len(tools)} inline_fallback:{used_inline_fallback}")
    return tools, None, trace if debug else []

def _python_type_to_json_type(tp: Any) -> str:
    """Map Python types to JSON schema types."""
    type_mapping = {
        int: "integer",
        float: "number", 
        str: "string",
        bool: "boolean"
    }
    return type_mapping.get(tp, "string")

def _build_param_metadata(func) -> List[Dict[str, Any]]:
    """Build parameter metadata for a function."""
    sig = inspect.signature(func)
    params = []
    
    for name, param in sig.parameters.items():
        if name in ("self", "cls"):
            continue
            
        param_type = _python_type_to_json_type(param.annotation if param.annotation != inspect.Parameter.empty else str)
        required = param.default == inspect.Parameter.empty
        default_val = None
        default_repr = False
        
        if not required:
            try:
                # Try to serialize default value
                json.dumps(param.default)
                default_val = param.default
            except (TypeError, ValueError):
                default_val = repr(param.default)
                default_repr = True
        
        param_info = {
            "name": name,
            "type": param_type,
            "required": required,
            "default": default_val
        }
        if default_repr:
            param_info["default_repr"] = True
            
        params.append(param_info)
    
    return params

def _serialize_result(result: Any) -> tuple[Any, bool]:
    """
    Serialize function result.
    Returns (serialized_result, was_repr).
    """
    try:
        json.dumps(result)
        return result, False
    except (TypeError, ValueError):
        return repr(result), True


_MAX_COERCE_DEPTH = 12
_MAX_CONTAINER_LENGTH = 2000
_BOOL_TRUE = {"true","1","yes","y","on"}
_BOOL_FALSE = {"false","0","no","n","off"}

def _coerce_basic(value: Any, target_type: Any):
    """Coerce a primitive value to target_type if possible (int, float, bool, str)."""
    if target_type in (int, float, str, bool):
        if isinstance(value, target_type):
            return value
        if isinstance(value, str):
            v = value.strip()
            if target_type is bool:
                lowered = v.lower()
                if lowered in _BOOL_TRUE: return True
                if lowered in _BOOL_FALSE: return False
                raise ValueError(f"Cannot coerce '{value}' to bool")
            if target_type is int:
                if v.isdigit() or (v.startswith('-') and v[1:].isdigit()):
                    return int(v)
                raise ValueError(f"Cannot coerce '{value}' to int")
            if target_type is float:
                try:
                    return float(v)
                except Exception as e:
                    raise ValueError(f"Cannot coerce '{value}' to float") from e
            if target_type is str:
                return value
        try:
            return target_type(value)
        except Exception as e:
            raise ValueError(f"Cannot coerce '{value}' to {getattr(target_type,'__name__',target_type)}") from e
    return value


def _coerce_collection(value: Any, coll_type: Any, sub_args: tuple, depth: int):
    """Coerce a parsed collection to annotated collection type (supports nested generics)."""
    if depth > _MAX_COERCE_DEPTH:
        raise ValueError("Maximum coercion nesting depth exceeded")
    origin = get_origin(coll_type)
    if origin in (list, List):
        if not isinstance(value, list):
            raise ValueError("Expected list")
        subtype = sub_args[0] if sub_args else Any
        if len(value) > _MAX_CONTAINER_LENGTH:
            raise ValueError("List too large")
        return [_coerce_value(v, subtype, depth+1) for v in value]
    if origin in (set, Set):
        if not isinstance(value, (list, set, tuple)):
            raise ValueError("Expected set-compatible iterable")
        subtype = sub_args[0] if sub_args else Any
        if len(value) > _MAX_CONTAINER_LENGTH:
            raise ValueError("Set too large")
        return {_coerce_value(v, subtype, depth+1) for v in value}
    if origin in (tuple, Tuple):
        if not isinstance(value, (list, tuple)):
            raise ValueError("Expected tuple-compatible iterable")
        if len(sub_args) == 2 and sub_args[1] is Ellipsis:
            # Variadic Tuple[T, ...]
            subtype = sub_args[0]
            return tuple(_coerce_value(v, subtype, depth+1) for v in value)
        # Fixed length tuple
        if sub_args and len(value) != len(sub_args):
            raise ValueError(f"Expected tuple length {len(sub_args)} got {len(value)}")
        return tuple(_coerce_value(v, t, depth+1) for v, t in zip(value, sub_args))
    if origin in (dict, Dict):
        if not isinstance(value, dict):
            raise ValueError("Expected dict")
        if len(value) > _MAX_CONTAINER_LENGTH:
            raise ValueError("Dict too large")
        if len(sub_args) == 2:
            k_type, v_type = sub_args
            coerced = {}
            for k, v in value.items():
                coerced_key = _coerce_value(k, k_type, depth+1)
                coerced_val = _coerce_value(v, v_type, depth+1)
                coerced[coerced_key] = coerced_val
            return coerced
        return value
    return value


def _coerce_union(value: Any, union_type: Any, depth: int):
    """Attempt coercion against each option in a Union/Optional."""
    last_err = None
    for opt in get_args(union_type):
        if opt is type(None):
            if value in (None, "", "null", "None"):
                return None
            continue
        try:
            return _coerce_value(value, opt, depth+1)
        except Exception as e:  # collect last error
            last_err = e
            continue
    raise ValueError(f"Value '{value}' does not match any allowed types in Union" + (f": {last_err}" if last_err else ""))


def _coerce_literal(value: Any, lit_type: Any):
    allowed = get_args(lit_type)
    if value in allowed:
        return value
    # Try numeric coercion if target literals include numbers but input is str
    if isinstance(value, str):
        for a in allowed:
            if isinstance(a, (int, float)):
                try:
                    num = float(value) if isinstance(a, float) else int(value)
                except Exception:
                    continue
                if num == a:
                    return a
    raise ValueError(f"Value '{value}' not in Literal {allowed}")


def _parse_raw_string_container(raw: str):
    """Safely parse a raw string potentially representing a JSON / Python literal collection."""
    raw_strip = raw.strip()
    if not raw_strip:
        return raw
    if len(raw_strip) > 10000:  # guard
        return raw
    # Prefer JSON first
    if (raw_strip.startswith('{') and raw_strip.endswith('}')) or (raw_strip.startswith('[') and raw_strip.endswith(']')):
        try:
            return json.loads(raw_strip)
        except Exception:
            pass
    # Guard characters before literal_eval
    allowed_chars = set("[]{}:,\"'0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ_ -.+()\n\t")
    if not all(c in allowed_chars for c in raw_strip):
        return raw
    # Basic suspicious token block
    lowered = raw_strip.lower()
    if any(tok in lowered for tok in ("__", "lambda", "import")):
        return raw
    try:
        return ast.literal_eval(raw_strip)
    except Exception:
        return raw


def _is_enum_type(tp):
    return isinstance(tp, type) and issubclass(tp, Enum)

def _is_dataclass_type(tp):
    try:
        return is_dataclass(tp)
    except Exception:
        return False

def _coerce_dataclass(value: Any, tp: Any, depth: int):
    if not isinstance(value, dict):
        if isinstance(value, str):
            value = _parse_raw_string_container(value)
        if not isinstance(value, dict):
            raise ValueError(f"Expected object for dataclass {getattr(tp,'__name__','')}" )
    out = {}
    for f in fields(tp):
        if f.name not in value:
            if f.default is not MISSING and f.default is not None:
                out[f.name] = f.default
                continue
            if getattr(f, 'default_factory', MISSING) is not MISSING:  # pragma: no cover
                out[f.name] = f.default_factory()
                continue
            raise ValueError(f"Missing required field '{f.name}' for {tp.__name__}")
        out[f.name] = _coerce_value(value[f.name], f.type, depth+1)
    return tp(**out)

def _coerce_enum(value: Any, enum_type: Any):
    if isinstance(value, enum_type):
        return value
    if isinstance(value, str):
        vlow = value.lower()
        for m in enum_type:
            if m.name.lower() == vlow:
                return m
    for m in enum_type:
        if m.value == value:
            return m
    raise ValueError(f"Value '{value}' not valid for Enum {enum_type.__name__}")

def _coerce_value(value: Any, annotation: Any, depth: int = 0):
    """Main dispatcher to coerce a single value based on annotation (with depth tracking)."""
    if depth > _MAX_COERCE_DEPTH:
        raise ValueError("Maximum coercion nesting depth exceeded")
    if annotation is inspect._empty or annotation is Any:
        return value
    # Enum
    if _is_enum_type(annotation):
        return _coerce_enum(value, annotation)
    # Dataclass
    if _is_dataclass_type(annotation):
        return _coerce_dataclass(value, annotation, depth+1)
    origin = get_origin(annotation)
    if origin is Literal:
        return _coerce_literal(value, annotation)
    if origin is Union:
        return _coerce_union(value, annotation, depth)
    if origin in (list, List, set, Set, tuple, Tuple, dict, Dict):
        parsed_val = value
        if isinstance(value, str):
            parsed_val = _parse_raw_string_container(value)
        sub_args = get_args(annotation)
        return _coerce_collection(parsed_val, annotation, sub_args, depth+1)
    return _coerce_basic(value, annotation)


def _coerce_arguments_for_tool(tool_func, arguments: Dict[str, Any], handle_default: bool = False) -> tuple[Dict[str, Any], list[str]]:
    """Coerce incoming string arguments to the annotated types of tool_func.
    Returns (coerced_args, warnings). Raises ValueError on fatal mismatch."""
    sig = inspect.signature(tool_func)
    coerced: Dict[str, Any] = {}
    warnings: list[str] = []
    for name, param in sig.parameters.items():
        if name not in arguments:
            # Will rely on apply_defaults later; skip
            continue
        raw_val = arguments[name]
        ann = param.annotation
        try:
            before_type = type(raw_val).__name__
            new_val = _coerce_value(raw_val, ann)
            coerced[name] = new_val
            after_type = type(new_val).__name__
            if before_type != after_type:
                warnings.append(f"Coerced parameter '{name}' from {before_type} to {after_type}")
        except ValueError as ve:
            if handle_default and param.default is not inspect._empty:
                coerced[name] = param.default
                warnings.append(f"Parameter '{name}' invalid ({ve}); used default due to handle_default=True")
                continue
            raise ValueError(f"Parameter '{name}': {ve}") from ve
    # Add untouched parameters (not provided) later in binding
    return coerced, warnings

async def _execute_tool_with_timeout(func, args: dict, timeout_sec: int) -> tuple[Any, Optional[str], Optional[str]]:
    """
    Execute tool function with timeout.
    Returns (result, error_message, error_code).
    """
    try:
        if inspect.iscoroutinefunction(func):
            result = await asyncio.wait_for(func(**args), timeout=timeout_sec)
        else:
            # For sync functions, we'll run them directly for now
            result = func(**args)
        return result, None, None
    except asyncio.TimeoutError:
        return None, "Execution timed out", "EXECUTION_TIMEOUT"
    except Exception as e:
        return None, str(e), "RUNTIME_EXCEPTION"


@router.post("/add")
async def add_tool_endpoint(
    request: Request, 
    tool_description: str = Form(..., description="A brief description of the tool."),
    code_snippet: Optional[str] = Form(None, description="The Python code snippet for the tool's function (required if no file is uploaded)."),
    model_name: str = Form(..., description="The name of the LLM model to be used for docstring regeneration."),
    created_by: str = Form(..., description="The email ID of the user who created the tool."),
    tag_ids: Optional[str] = Form(None, description="Optional comma-separated list of tag IDs for the tool."),
    tool_file: Union[UploadFile, str, None] = File(None, description="Optional: Upload a .py file for the tool (required if code_snippet is empty)."),
    tool_service: ToolService = Depends(ServiceProvider.get_tool_service),
    authorization_service: AuthorizationService = Depends(ServiceProvider.get_authorization_service),
    user_data: User = Depends(get_current_user),
    force_add: Optional[bool] = False,
    is_validator: Optional[bool] = Query(False, description="Indicates if the tool is a validator tool. Validator tools must have exactly 2 parameters (query, response) and return validation results.")
):
    """
    Adds a new tool to the tool table.

    Parameters:
    ----------
    tool_description : str
        A brief description of the tool.
    code_snippet : str, optional
        The Python code snippet for the tool's function (required if no file is uploaded).
    model_name : str
        The name of the LLM model to be used for docstring regeneration.
    created_by : str
        The email ID of the user who created the tool.
    tag_ids : str, optional
        Optional comma-separated list of tag IDs for the tool.
    tool_file : UploadFile, optional
        Upload a .py file for the tool (required if code_snippet is empty).
    is_validator : bool, optional
        Indicates if the tool is a validator tool. Validator tools must have exactly 2 parameters (query, response) and return validation results.

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
    if isinstance(tool_file, str):
        tool_file = None

    # Check permissions first
    if not await authorization_service.check_operation_permission(user_data.email, user_data.role, "create", "tools"):
        raise HTTPException(status_code=403, detail="You don't have permission to create tools. Only admins and developers can perform this action")
    
    user_id = request.cookies.get("user_id")
    user_session = request.cookies.get("user_session")

    # Handle file upload or use code_snippet
    final_code_snippet = code_snippet
    if tool_file and tool_file.filename:
        if not tool_file.filename.endswith(".py"):
            raise HTTPException(status_code=400, detail="Only .py files can be uploaded for tools.")
        final_code_snippet = await tool_service._read_uploaded_file_content(tool_file)
        if not final_code_snippet:
            raise HTTPException(status_code=400, detail="Uploaded file is empty or could not be read.")
    elif not code_snippet:
        raise HTTPException(status_code=400, detail="Either 'code_snippet' or a '.py' file must be provided.")

    if not final_code_snippet:
        raise HTTPException(status_code=400, detail="Either 'code_snippet' or a '.py' file must be provided.")

    # Convert tag_ids from comma-separated string to list if provided
    tag_ids_list = []
    if tag_ids:
        tag_ids_list = [t.strip() for t in tag_ids.split(',') if t.strip()]

    # Create tool_data dictionary compatible with ToolData schema
    tool_data_dict = {
        "tool_description": tool_description.strip(),
        "code_snippet": final_code_snippet,
        "model_name": model_name.strip(),
        "created_by": created_by.strip(),
        "tag_ids": tag_ids_list
    }

    update_session_context(
        model_used=model_name,
        tags=tag_ids_list,
        user_session=user_session,
        user_id=user_id
    )
    register(
            project_name='add-tool',
            auto_instrument=True,
            set_global_tracer_provider=False,
            batch=True
        )
    with traced_project_context_sync('add-tool'):
        status = await tool_service.create_tool(tool_data=tool_data_dict, force_add=force_add, is_validator=is_validator)
        log.debug(f"Tool creation status: {status}")

    update_session_context(model_used='Unassigned',
                            tags='Unassigned',
                            tool_id='Unassigned',
                            tool_name='Unassigned',)
    if not status.get("is_created"):
        if not status.get("warnings"):
            raise HTTPException(status_code=400, detail=status.get("message"))
    return status


@router.get("/get")
async def get_all_tools_endpoint(request: Request, tool_service: ToolService = Depends(ServiceProvider.get_tool_service), authorization_service: AuthorizationService = Depends(ServiceProvider.get_authorization_service), user_data: User = Depends(get_current_user)):
    """
    Retrieves all regular tools from the tool table (excludes validator tools).

    Returns:
    -------
    list
        A list of regular tools. If no tools are found, raises an HTTPException with status code 404.
        Use /tools/validators/get to retrieve validator tools.
    """
    # Check permissions first
    if not await authorization_service.check_operation_permission(user_data.email, user_data.role, "read", "tools"):
        raise HTTPException(status_code=403, detail="You don't have permission to view tools. Only admins and developers can perform this action")
    
    user_id = request.cookies.get("user_id")
    user_session = request.cookies.get("user_session")
    update_session_context(user_session=user_session, user_id=user_id)
    tools = await tool_service.get_all_tools()
    if not tools:
        raise HTTPException(status_code=404, detail="No tools found")
    return tools


@router.get("/get/{tool_id}")
async def get_tool_by_id_endpoint(request: Request, tool_id: str, tool_service: ToolService = Depends(ServiceProvider.get_tool_service), authorization_service: AuthorizationService = Depends(ServiceProvider.get_authorization_service), user_data: User = Depends(get_current_user)):
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
    # Check permissions first
    if not await authorization_service.check_operation_permission(user_data.email, user_data.role, "read", "tools"):
        raise HTTPException(status_code=403, detail="You don't have permission to view tools. Only admins and developers can perform this action")
    
    user_id = request.cookies.get("user_id")
    user_session = request.cookies.get("user_session")
    update_session_context(tool_id=tool_id, user_session=user_session, user_id=user_id)
    tool = await tool_service.get_tool(tool_id=tool_id)
    if not tool:
        raise HTTPException(status_code=404, detail="Tool not found")
    update_session_context(tool_id='Unassigned')
    return tool


@router.post("/get/by-list")
async def get_tools_by_list_endpoint(request: Request, tool_ids: List[str], tool_service: ToolService = Depends(ServiceProvider.get_tool_service), authorization_service: AuthorizationService = Depends(ServiceProvider.get_authorization_service), user_data: User = Depends(get_current_user)):
    """Retrieves tools by a list of IDs."""
    # Check permissions first
    if not await authorization_service.check_operation_permission(user_data.email, user_data.role, "read", "tools"):
        raise HTTPException(status_code=403, detail="You don't have permission to view tools. Only admins and developers can perform this action")
    
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
        created_by: Optional[str] = Query(None, description="Filter by creator's email ID"),
        tool_service: ToolService = Depends(ServiceProvider.get_tool_service),
        authorization_service: AuthorizationService = Depends(ServiceProvider.get_authorization_service),
        user_data: User = Depends(get_current_user)
    ):
    """Searches regular tools with pagination (excludes validator tools). Use /tools/validators/get/search-paginated/ for validator tools."""
    # Check permissions first
    if not await authorization_service.check_operation_permission(user_data.email, user_data.role, "read", "tools"):
        raise HTTPException(status_code=403, detail="You don't have permission to view tools. Only admins and developers can perform this action")
    
    user_id = request.cookies.get("user_id")
    user_session = request.cookies.get("user_session")
    update_session_context(user_session=user_session, user_id=user_id)
    

    result = await tool_service.get_tools_by_search_or_page(search_value=search_value, limit=page_size, page=page_number,tag_names=tag_names, created_by=created_by)
    if not result["details"]:
        raise HTTPException(status_code=404, detail="No tools found matching criteria.")
    return result


@router.get("/get/tools-and-validators-search-paginated/")
async def search_paginated_tools_and_validators_endpoint(
        request: Request,
        search_value: Optional[str] = Query(None),
        page_number: int = Query(1, ge=1),
        page_size: int = Query(20, ge=1),
        tag_names: List[str] = Query(None, description="Filter by tag names"),
        created_by: Optional[str] = Query(None, description="Filter by creator's email ID"),
        tool_service: ToolService = Depends(ServiceProvider.get_tool_service),
        authorization_service: AuthorizationService = Depends(ServiceProvider.get_authorization_service),
        user_data: User = Depends(get_current_user)
    ):
    """Searches tools and validators with pagination. This endpoint returns both regular tools and validator tools in a single response."""
    # Check permissions first
    if not await authorization_service.check_operation_permission(user_data.email, user_data.role, "read", "tools"):
        raise HTTPException(status_code=403, detail="You don't have permission to view tools. Only admins and developers can perform this action")
    
    user_id = request.cookies.get("user_id")
    user_session = request.cookies.get("user_session")
    update_session_context(user_session=user_session, user_id=user_id)
    
    result = await tool_service.get_all_tools_and_validators_by_search_or_page(
        search_value=search_value, 
        limit=page_size, 
        page=page_number,
        tag_names=tag_names, 
        created_by=created_by
    )
    if not result["details"]:
        raise HTTPException(status_code=404, detail="No tools found matching criteria.")
    return result


@router.post("/get/by-tags")
async def get_tools_by_tag_endpoint(request: Request, tag_data: TagIdName, tool_service: ToolService = Depends(ServiceProvider.get_tool_service), authorization_service: AuthorizationService = Depends(ServiceProvider.get_authorization_service), user_data: User = Depends(get_current_user)):
    """
    API endpoint to retrieve tools associated with given tag IDs or tag names.

    Parameters:
    - request: The FastAPI Request object.
    - tag_data: Pydantic model containing tag IDs or names.
    - tool_service: Dependency-injected ToolService instance.

    Returns:
    - List[Dict[str, Any]]: A list of tools.
    """
    # Check permissions first
    if not await authorization_service.check_operation_permission(user_data.email, user_data.role, "read", "tools"):
        raise HTTPException(status_code=403, detail="You don't have permission to view tools. Only admins and developers can perform this action")
    
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
async def update_tool_endpoint(request: Request, tool_id: str, update_request: UpdateToolRequest, tool_service: ToolService = Depends(ServiceProvider.get_tool_service),force_add:Optional[bool] = False, authorization_server: AuthorizationService = Depends(ServiceProvider.get_authorization_service), user_data: User = Depends(get_current_user)):
    """
    Updates a tool by its ID.
    
    Access Control:
    - Admins can update any tool
    - Tool creators can update their own tools
    - Other users cannot update tools

    Parameters:
    ----------
    tool_id : str
        The ID of the tool to be updated.
    update_request : UpdateToolRequest
        The request body containing the update details.
    force_add : bool, optional
        Force add flag for bypassing certain validations.

    Returns:
    -------
    dict
        A dictionary containing the status of the update operation.
        If the update is unsuccessful, raises an HTTPException with
        status code 400 and the status message.
    """
    previous_value = await tool_service.get_tool(tool_id=tool_id)
    user_id = user_data.email
    user_session = request.cookies.get("user_session")
    # Check basic operation permission first
    if not await authorization_server.check_operation_permission(user_id, user_data.role, "update", "tools"):
        raise HTTPException(status_code=403, detail="You don't have permission to update tools. Only admins and developers can perform this action")
    
    is_admin = False
    if update_request.is_admin:
        is_admin = await authorization_server.has_role(user_email=user_id, required_role=UserRole.ADMIN)
    
    is_creator = (previous_value and previous_value[0].get("created_by") == user_data.username)
    if not (is_admin or is_creator):
        log.warning(f"User {user_id} attempted to update tool without admin privileges or creator access")
        raise HTTPException(status_code=403, detail="Only admin or creator are allowed to update the tool")
    
    update_session_context(tool_id=tool_id, tags=update_request.updated_tag_id_list, model_used=update_request.model_name,
                            action_type='update', action_on='tool', previous_value=previous_value, user_session=user_session, user_id=user_id)
    register(
            project_name='update-tool',
            auto_instrument=True,
            set_global_tracer_provider=False,
            batch=True
        )
    with traced_project_context_sync('update-tool'):
        response = await tool_service.update_tool(
            tool_id=tool_id,
            model_name=update_request.model_name,
            force_add=force_add,
            code_snippet=update_request.code_snippet,
            tool_description=update_request.tool_description,
            updated_tag_id_list=update_request.updated_tag_id_list,
            user_id=user_data.username,
            is_admin=is_admin,
            is_validator=update_request.is_validator
        )

    if response["is_update"]:
        new_value=await tool_service.get_tool(tool_id=tool_id)
        update_session_context(new_value=new_value)
        log.debug(f"Tool update status: {response}")
        update_session_context(new_value='Unassigned')
    
    # Clean up session context - wrap in try-catch to prevent middleware errors
    try:
        update_session_context(tool_id='Unassigned',tags='Unassigned',model_used='Unassigned',action_type='Unassigned',
                            action_on='Unassigned',previous_value='Unassigned',new_value='Unassigned')
    except Exception as session_error:
        log.warning(f"Session context cleanup error (non-critical): {session_error}")

    if not response.get("is_update"):

        log.error(f"Tool update failed: {response['message']}")
        if response.get("warnings"):
            return response

        agents = []
        for res in response.get('details', []):
            if res.get('agentic_application_name'):
                agents.append(res.get('agentic_application_name'))
        log.error(f"Tool update failed: {response['message']} with names: {agents}" if agents!=[] else f"Tool update failed: {response['message']}")
        raise HTTPException(status_code=400, detail=f"Tool update failed: {response['message']} with names: {agents}" if agents!=[] else f"Tool update failed: {response['message']}")

    return response


@router.delete("/delete/{tool_id}")
async def delete_tool_endpoint(request: Request, tool_id: str, delete_request: DeleteToolRequest, tool_service: ToolService = Depends(ServiceProvider.get_tool_service), authorization_server: AuthorizationService = Depends(ServiceProvider.get_authorization_service), user_data: User = Depends(get_current_user)):
    """
    Deletes a tool by its ID.
    
    Access Control:
    - Admins can delete any tool
    - Tool creators can delete their own tools
    - Other users cannot delete tools

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
    # user_id = request.cookies.get("user_id")
    user_id = user_data.email
    user_session = request.cookies.get("user_session")
    
    # Check basic operation permission first
    if not await authorization_server.check_operation_permission(user_id, user_data.role, "delete", "tools"):
        raise HTTPException(status_code=403, detail="You don't have permission to delete tools. Only admins and developers can perform this action")
    
    is_admin = False
    if delete_request.is_admin:
        is_admin = await authorization_server.has_role(user_email=user_id, required_role=UserRole.ADMIN)
    is_creator = (previous_value.get("created_by") == user_data.username)
    if not (is_admin or is_creator):
        log.warning(f"User {user_id} attempted to delete tool without admin privileges or creator access")
        raise HTTPException(status_code=403, detail="Admin privileges or tool creator access required to delete this tool")
    
    update_session_context(user_session=user_session, user_id=user_id, tool_id=tool_id, action_on='tool', action_type='delete', previous_value=previous_value)
    status = await tool_service.delete_tool(
        tool_id=tool_id,
        user_id=user_data.username,
        is_admin=is_admin
    )
    status["status_message"] = status.get("message", "")
    update_session_context(tool_id='Unassigned',action_on='Unassigned', action_type='Unassigned',previous_value='Unassigned') # Telemetry context clear
    if not status.get("is_delete"):
        agents = []
        for res in status.get('details', []):
            if res.get('agentic_application_name'):
                agents.append(res.get('agentic_application_name'))
        log.error(f"Tool delete failed: {status['message']} with names: {agents}" if agents!=[] else f"Tool delete failed: {status['message']}")
        raise HTTPException(status_code=400, detail=f"Tool delete failed: {status['message']} with names: {agents}" if agents!=[] else f"Tool delete failed: {status['message']}")
    return status

@router.post("/execute", response_model=ExecuteResponse)
async def execute(request: Request, execute_request: ExecuteRequest, authorization_service: AuthorizationService = Depends(ServiceProvider.get_authorization_service), user_data: User = Depends(get_current_user)):
    # Check permissions first
    if not await authorization_service.check_operation_permission(user_data.email, user_data.role, "execute", "tools"):
        raise HTTPException(status_code=403, detail="You don't have permission to execute tools. Only admins and developers can perform this action")
    
    # --- Syntax check ---
    try:
        compiled = compile(execute_request.code, "<string>", "exec")
    except SyntaxError as se:
        return ExecuteResponse(success=False, error=f"SyntaxError: {se.msg} at line {se.lineno}")

    # --- Function extraction ---
    try:
        tree = ast.parse(execute_request.code)
        func_defs = [node for node in tree.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))]
        if len(func_defs) == 0:
            return ExecuteResponse(success=False, error="No function definition found in code")
        if len(func_defs) > 1:
            return ExecuteResponse(success=False, error="More than one function definition found. Input must only have a single function definition.")
        func = func_defs[0]
    except Exception as e:
        return ExecuteResponse(success=False, error=f"Error parsing code: {str(e)}")
    model_service = ServiceProvider.get_model_service()
    models = await model_service.get_all_available_model_names()
    model = models[0]
    print("Model_name:",model)
    initial_state = {
        "code": execute_request.code,
        "model": model,
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
        "feedback_case7": None,
        "validation_case8": None,
        "feedback_case8": None
    }

    # Await workflow validation results
    workflow_result = await graph.ainvoke(input=initial_state)
    e_cases = ["validation_case1","validation_case8","validation_case4"]
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
        mandatory = True
        for p in sig.parameters.values():
            if p.default is inspect.Parameter.empty:
                # No default → required
                default_val = None
                mandatory = True
                required_params.append(p.name)
            else:
                # Has default → optional
                default_val = p.default
                mandatory = False

            all_params_info.append(ParamInfo(name=p.name, default=default_val, mandatory=mandatory))


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
            # result = global_ns[func.name](**converted_inputs)
            func_object = global_ns[func.name]

            if inspect.iscoroutinefunction(func_object):
                result = await func_object(**converted_inputs)
            else:
                result = func_object(**converted_inputs)
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
        mcp_file: Union[UploadFile, str, None] = File(None, description="Optional: Upload a .py file for 'file' type MCP tools (required if mcp_type is 'file' and code_content is empty)."),

        tag_ids: List[str] = Form(None, description="Optional list of tag IDs for the tool."),

        mcp_tool_service: McpToolService = Depends(ServiceProvider.get_mcp_tool_service),
        authorization_service: AuthorizationService = Depends(ServiceProvider.get_authorization_service),
        user_data: User = Depends(get_current_user)
    ):
    """
    Adds a new MCP tool (server definition) to the database.
    Supports 'file', 'url', and 'module' based MCP servers.
    For 'file' type, allows direct code content or a .py file upload.
    """
    if isinstance(mcp_file, str):
        mcp_file = None
    # Check permissions first
    if not await authorization_service.check_operation_permission(user_data.email, user_data.role, "create", "tools"):
        raise HTTPException(status_code=403, detail="You don't have permission to create tools. Only admins and developers can perform this action")
    
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
        # Handle validation errors with detailed response
        if status.get("errors") or status.get("warnings"):
            error_detail = {
                "message": status.get("message", "MCP tool validation failed"),
                "errors": status.get("errors", []),
                "warnings": status.get("warnings", [])
            }
            raise HTTPException(status_code=400, detail=error_detail)
        else:
            raise HTTPException(status_code=400, detail=status.get("message"))
    
    # Include validation warnings in success response if any
    result = {"status": "success", "result": status}
    if status.get("warnings"):
        result["validation_warnings"] = status["warnings"]
    
    return result


@router.get("/mcp/get")
async def get_all_mcp_tools_endpoint(request: Request, mcp_tool_service: McpToolService = Depends(ServiceProvider.get_mcp_tool_service), authorization_service: AuthorizationService = Depends(ServiceProvider.get_authorization_service), user_data: User = Depends(get_current_user)):
    """
    Retrieves all MCP tool (server definition) records.
    """
    # Check permissions first
    if not await authorization_service.check_operation_permission(user_data.email, user_data.role, "read", "tools"):
        raise HTTPException(status_code=403, detail="You don't have permission to view tools. Only admins and developers can perform this action")
    
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
        mcp_tool_service: McpToolService = Depends(ServiceProvider.get_mcp_tool_service),
        authorization_service: AuthorizationService = Depends(ServiceProvider.get_authorization_service),
        user_data: User = Depends(get_current_user)
    ):
    """
    Retrieves a single MCP tool (server definition) record by its ID.
    """
    # Check permissions first
    if not await authorization_service.check_operation_permission(user_data.email, user_data.role, "read", "tools"):
        raise HTTPException(status_code=403, detail="You don't have permission to view tools. Only admins and developers can perform this action")
    
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
        created_by: Optional[str] = Query(None, description="Filter by creator's email ID"),
        mcp_tool_service: McpToolService = Depends(ServiceProvider.get_mcp_tool_service),
        authorization_service: AuthorizationService = Depends(ServiceProvider.get_authorization_service),
        user_data: User = Depends(get_current_user)
    ):
    """
    Searches MCP tool (server definition) records with pagination.
    """
    # Check permissions first
    if not await authorization_service.check_operation_permission(user_data.email, user_data.role, "read", "tools"):
        raise HTTPException(status_code=403, detail="You don't have permission to view tools. Only admins and developers can perform this action")
    
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
            tag_names=tag_names,
            created_by=created_by
        )
        if not result["details"]:
            raise HTTPException(status_code=404, detail="No MCP tools found matching criteria.")
        return result

    except HTTPException:
        raise   # Re-raise HTTPExceptions directly

    except Exception as e:
        log.error(f"Error searching paginated MCP tools: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error searching paginated MCP tools: {str(e)}")


@router.put("/mcp/update/{tool_id}")
async def update_mcp_tool_endpoint(
        request: Request,
        tool_id: str,
        update_request_data: McpToolUpdateRequest,
        mcp_tool_service: McpToolService = Depends(ServiceProvider.get_mcp_tool_service),
        authorization_server: AuthorizationService = Depends(ServiceProvider.get_authorization_service),
        user_data: User = Depends(get_current_user)
    ):
    """
    Updates an existing MCP tool (server definition) record.
    Only allows 'code_content' updates for 'mcp_file_' type tools.
    
    Access Control:
    - Admins can update any MCP tool
    - Tool creators can update their own MCP tools
    - Other users cannot update MCP tools
    """
    # user_id = request.cookies.get("user_id")
    user_id = user_data.email
    user_session = request.cookies.get("user_session")
    
    # Check basic operation permission first
    if not await authorization_server.check_operation_permission(user_id, user_data.role, "update", "tools"):
        raise HTTPException(status_code=403, detail="You don't have permission to update tools. Only admins and developers can perform this action")
    
    try:
        existing_tool = await mcp_tool_service.get_mcp_tool(tool_id=tool_id)
        if not existing_tool:
            raise HTTPException(status_code=404, detail=f"MCP tool with ID '{tool_id}' not found")
    except Exception as e:
        log.error(f"Error retrieving MCP tool for authorization check: {str(e)}")
        raise HTTPException(status_code=500, detail="Error checking tool permissions")
    is_admin = False
    if update_request_data.is_admin:
        is_admin = await authorization_server.has_role(user_email=user_id, required_role=UserRole.ADMIN)
    is_creator = (existing_tool[0].get("created_by") == user_data.username)
    if not (is_admin or is_creator):
        log.warning(f"User {user_id} attempted to update MCP tool without admin privileges or creator access")
        raise HTTPException(status_code=403, detail="Admin privileges or tool creator access required to update this MCP tool")
    
    update_session_context(user_session=user_session, user_id=user_id, tool_id=tool_id)

    try:
        status = await mcp_tool_service.update_mcp_tool(
            tool_id=tool_id,
            user_id=user_data.username,
            is_admin=is_admin,
            tool_description=update_request_data.tool_description,
            code_content=update_request_data.code_content,
            updated_tag_id_list=update_request_data.updated_tag_id_list,
        )
        status["status_message"] = status.get("message", "")

    except Exception as e:
        log.error(f"Error updating MCP tool '{tool_id}': {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error updating MCP tool '{tool_id}': {str(e)}")

    finally:
        update_session_context(tool_id='Unassigned')

    if not status.get("is_update"):
        # Handle validation errors with detailed response
        agents = []
        for res in status.get('details', []):
            if res.get('agentic_application_name'):
                agents.append(res.get('agentic_application_name'))
        if agents:
            log.error(f"MCP tool update failed: {status['message']} with names: {agents}")
            raise HTTPException(status_code=400, detail=f"MCP tool update failed: {status['message']} with names: {agents}")

        if status.get("errors") or status.get("warnings"):
            error_detail = {
                "message": status.get("message", "MCP tool update validation failed"),
                "errors": status.get("errors", []),
                "warnings": status.get("warnings", [])
            }
            raise HTTPException(status_code=400, detail=error_detail)

        raise HTTPException(status_code=400, detail=status.get("message"))

    # Return response with validation warnings if any
    result = status.copy()
    if status.get("warnings"):
        result["validation_warnings"] = status["warnings"]
    
    return result


@router.delete("/mcp/delete/{tool_id}")
async def delete_mcp_tool_endpoint(
        request: Request,
        tool_id: str,
        delete_request_data: DeleteToolRequest,
        mcp_tool_service: McpToolService = Depends(ServiceProvider.get_mcp_tool_service),
        authorization_server: AuthorizationService = Depends(ServiceProvider.get_authorization_service),
        user_data: User = Depends(get_current_user)
    ):
    """
    Deletes an MCP tool (server definition) by moving it to the recycle bin.
    
    Access Control:
    - Admins can delete any MCP tool
    - Tool creators can delete their own MCP tools
    - Other users cannot delete MCP tools
    
    Note: All deletions move tools to the recycle bin (soft delete).
    Use the permanent delete endpoint to remove from recycle bin permanently.
    """
    # user_id = request.cookies.get("user_id")
    user_id = user_data.email
    user_session = request.cookies.get("user_session")
    
    # Check basic operation permission first
    if not await authorization_server.check_operation_permission(user_id, user_data.role, "delete", "tools"):
        raise HTTPException(status_code=403, detail="You don't have permission to delete tools. Only admins and developers can perform this action")
   
    try:
        existing_tool = await mcp_tool_service.get_mcp_tool(tool_id=tool_id)
        if not existing_tool:
            raise HTTPException(status_code=404, detail=f"MCP tool with ID '{tool_id}' not found")
    except Exception as e:
        log.error(f"Error retrieving MCP tool for authorization check: {str(e)}")
        raise HTTPException(status_code=500, detail="Error checking tool permissions")
    
    previous_value = existing_tool[0]
    is_admin = False
    if delete_request_data.is_admin:
        is_admin = await authorization_server.has_role(user_email=user_id, required_role=UserRole.ADMIN)
    is_creator = (previous_value.get("created_by") == user_data.username)
    if not (is_admin or is_creator):
        log.warning(f"User {user_id} attempted to delete MCP tool without admin privileges or creator access")
        raise HTTPException(status_code=403, detail="Admin privileges or tool creator access required to delete this MCP tool")
    
    update_session_context(user_session=user_session, user_id=user_id, tool_id=tool_id, action_on='mcp_tool', action_type='delete', previous_value=previous_value)
    status = await mcp_tool_service.delete_mcp_tool(
        tool_id=tool_id,
        user_id=user_data.username,
        is_admin=is_admin
    )
    status["status_message"] = status.get("message", "")
    update_session_context(tool_id='Unassigned', action_on='Unassigned', action_type='Unassigned', previous_value='Unassigned')  # Telemetry context clear

    if not status.get("is_delete"):
        agents = []
        for res in status.get('details', []):
            if res.get('agentic_application_name'):
                agents.append(res.get('agentic_application_name'))
        if agents:
            log.error(f"MCP tool delete failed: {status['message']} with names: {agents}")
            raise HTTPException(status_code=400, detail=f"MCP tool delete failed: {status['message']} with names: {agents}")
        raise HTTPException(status_code=400, detail=status.get("message"))
    return status


@router.get("/mcp/get/live-tool-details/{tool_id}")
async def get_live_mcp_tool_details_endpoint(
        request: Request,
        tool_id: str,
        mcp_tool_service: McpToolService = Depends(ServiceProvider.get_mcp_tool_service),
        authorization_service: AuthorizationService = Depends(ServiceProvider.get_authorization_service),
        user_data: User = Depends(get_current_user)
    ):
    """
    Connects to the live MCP server defined by the tool_id and retrieves details
    (name, description, args) of the individual tools it exposes for UI display.
    """
    # Check permissions first
    if not await authorization_service.check_operation_permission(user_data.email, user_data.role, "read", "tools"):
        raise HTTPException(status_code=403, detail="You don't have permission to view tools. Only admins and developers can perform this action")
    
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


@router.post("/mcp/test/{tool_id}", response_model=McpToolTestResponse)
async def test_mcp_tools_endpoint(
        request: Request,
        tool_id: str,
        test_request: McpToolTestRequest,
        current_user: User = Depends(get_current_user),
        mcp_tool_service: McpToolService = Depends(ServiceProvider.get_mcp_tool_service),
        authorization_service: AuthorizationService = Depends(ServiceProvider.get_authorization_service)
    ):
    """
    Tests MCP tools by executing them with provided arguments.
    
    Connects to the live MCP server defined by the tool_id and executes
    the specified tool invocations, returning detailed results including
    success status, execution latency, outputs, and error information.
    
    **Authorization**: Creator, admin, or public approved tools only.
    
    **Limits**: Max 10 invocations per request, timeout 1-60 seconds per invocation.
    """
    # Check permissions first
    if not await authorization_service.check_operation_permission(current_user.email, current_user.role, "execute", "tools"):
        raise HTTPException(status_code=403, detail="You don't have permission to execute tools. Only admins and developers can perform this action")
    
    user_session = request.cookies.get("user_session")
    update_session_context(user_session=user_session, user_id=current_user.email, tool_id=tool_id)

    try:
        # Convert request model to dict for service call
        invocations = [inv.model_dump() for inv in test_request.invocations]
        
        # Call service method
        result = await mcp_tool_service.test_mcp_tools(
            tool_id=tool_id,
            invocations=invocations,
            parallel=test_request.parallel,
            timeout_sec=test_request.timeout_sec,
            user_id=current_user.email,
            is_admin=(current_user.role == UserRole.ADMIN)
        )
        
        log.info(f"MCP tool test completed for '{tool_id}': {len(result['results'])} invocations, overall_success={result['overall_success']}")
        return result
        
    except ValueError as e:
        log.error(f"Validation error testing MCP tools for '{tool_id}': {str(e)}")
        raise HTTPException(status_code=400, detail=str(e))
    except PermissionError as e:
        log.error(f"Permission error testing MCP tools for '{tool_id}': {str(e)}")
        raise HTTPException(status_code=403, detail=str(e))
    except Exception as e:
        log.error(f"Error testing MCP tools for '{tool_id}': {str(e)}")
        # Check for specific error types and return appropriate status codes
        if "not found" in str(e).lower():
            raise HTTPException(status_code=404, detail=str(e))
        elif "connect" in str(e).lower() or "server" in str(e).lower():
            raise HTTPException(status_code=502, detail=f"Failed to connect to MCP server: {str(e)}")
        else:
            raise HTTPException(status_code=500, detail=f"Error testing MCP tools: {str(e)}")
    finally:
        update_session_context(tool_id='Unassigned')


@router.post("/inline-mcp/run")
async def run_inline_mcp_endpoint(
    request: Request,
    inline_request: InlineMcpRequest,
    current_user: User = Depends(get_current_user),
    authorization_service: AuthorizationService = Depends(ServiceProvider.get_authorization_service)
):
    """Unified inline MCP endpoint returning simplified dict structure.

    Always returns JSON with keys:
      - inputs_required: for introspection, list of tools with params; for execution, echo of tool params metadata
      - output: execution result (or list of tools for introspect)
      - output_type: type name of output ("list","dict","str", etc.) or "none"/"error"
      - error: error message string or null
      - success: boolean
      - feedback: reserved (currently null)
    """
    # Check permissions first
    if not await authorization_service.check_operation_permission(current_user.email, current_user.role, "execute", "tools"):
        raise HTTPException(status_code=403, detail="You don't have permission to execute tools. Only admins and developers can perform this action")
    
    user_session = request.cookies.get("user_session")
    update_session_context(
        user_session=user_session,
        user_id=current_user.email,
        action_type="inline_mcp",
        action_on="introspect" if not inline_request.tool_name else "execute"
    )
    def _resp(inputs_required: list[dict], output: Any, error: Optional[str], success: bool):
        return {
            "inputs_required": inputs_required,
            "output": output,
            "output_type": (type(output).__name__ if output is not None else None),
            "error": "" if error is None else error,
            "success": success,
            "feedback": None,
            "handle_default": getattr(inline_request, 'handle_default', False)
        }
    # end _resp
    try:
        # Basic code validation
        if len(inline_request.code) > 50 * 1024:
            return _resp([], None, "Code size exceeds 50KB limit", False)
        if not inline_request.code.strip():
            return _resp([], None, "Empty code provided", False)

        exec_globals, compile_error = _compile_and_exec_code(inline_request.code)
        if compile_error:
            return _resp([], None, compile_error, False)

        mcp_obj, mcp_error = _extract_mcp_object(exec_globals)
        tools: Dict[str, Any] = {}
        if not mcp_error and mcp_obj is not None:
            discovered, tools_error, trace = _discover_tools(
                mcp_obj,
                exec_globals=exec_globals,
                debug=False
            )
            if not tools_error and discovered:
                tools = discovered

        tool_meta: Dict[str, Any] = {}
        if tools:
            try:
                for t_name, t_func in tools.items():
                    tool_meta[t_name] = _build_param_metadata(t_func)
            except Exception as e:
                return _resp([], None, f"Failed building tool metadata: {e}", False)

        if not inline_request.tool_name:
            if tools:
                # Return list of tools with their params (not flattened)
                tools_list: list[dict] = []
                for t_name, param_list in tool_meta.items():
                    simple_params = []
                    for p in param_list:
                        # p may be dict already from _build_param_metadata
                        if isinstance(p, dict):
                            simple_params.append({"name": p.get("name"), "default": p.get("default")})
                        else:  # fallback if it's an object with attributes
                            simple_params.append({"name": getattr(p, 'name', None), "default": getattr(p, 'default', None)})
                    tools_list.append({"name": t_name, "params": simple_params})
                return _resp(tools_list, None, None, False)
            func = None
            for name, obj in exec_globals.items():
                if name == 'mcp':
                    continue
                if callable(obj) and hasattr(obj, '__code__'):
                    func = obj
                    break
            if not func:
                return _resp([], None, "No callable found", False)
            sig = inspect.signature(func)
            params_list = []
            for pname, param in sig.parameters.items():
                default_val = None if param.default is inspect._empty else param.default
                params_list.append({"name": pname, "default": default_val})
            return _resp(params_list, None, None, False)

        tool_name = inline_request.tool_name
        if tools and tool_name in tools:
            target_func = tools[tool_name]
        else:
            target_func = None
            for name, obj in exec_globals.items():
                if name == 'mcp':
                    continue
                if callable(obj) and hasattr(obj, '__code__'):
                    target_func = obj
                    break
            if target_func is None:
                return _resp([], None, f"Tool '{tool_name}' not found", False)

        raw_arguments = inline_request.arguments or {}
        # Alias support: if request body provided 'inputs' instead of 'arguments'
        if not raw_arguments and hasattr(inline_request, 'inputs'):
            try:
                alias_inputs = getattr(inline_request, 'inputs')
                if isinstance(alias_inputs, dict):
                    raw_arguments = alias_inputs
            except Exception:
                pass
        sig = inspect.signature(target_func)
        required_params = [n for n, p in sig.parameters.items() if p.default is inspect._empty]
        missing = [n for n in required_params if n not in raw_arguments]
        # If caller supplied no arguments at all, and we are about to execute purely on defaults, treat as introspection (success=false)
        if not raw_arguments:
            params_list = []
            for pname, param in sig.parameters.items():
                default_val = None if param.default is inspect._empty else param.default
                params_list.append({"name": pname, "default": default_val})
            return _resp(params_list, None, None, False)
        if missing:
            params_list = []
            for pname, param in sig.parameters.items():
                default_val = None if param.default is inspect._empty else param.default
                params_list.append({"name": pname, "default": default_val})
            return _resp(params_list, None, None, False)

        try:
            coerced_arguments, coercion_warnings = _coerce_arguments_for_tool(target_func, raw_arguments, handle_default=getattr(inline_request, 'handle_default', False))
            merged_args = {**raw_arguments, **coerced_arguments}
            bound = sig.bind(**merged_args)
            bound.apply_defaults()
        except (TypeError, ValueError) as e:
            params_list = []
            for pname, param in sig.parameters.items():
                default_val = None if param.default is inspect._empty else param.default
                params_list.append({"name": pname, "default": default_val})
            return _resp(params_list, None, str(e), False)

        result, error_message, error_code = await _execute_tool_with_timeout(
            target_func,
            bound.arguments,
            inline_request.timeout_sec or 5
        )
        params_list = []
        for pname, param in sig.parameters.items():
            default_val = None if param.default is inspect._empty else param.default
            params_list.append({"name": pname, "default": default_val})
        if error_message:
            return _resp(params_list, None, error_message, False)

        serialized_result, was_repr = _serialize_result(result)
        return _resp(params_list, serialized_result, None, True)
    except Exception as e:
        log.error(f"Inline MCP unexpected failure: {e}")
        return _resp([], None, f"Unexpected error: {e}", False)


# Recycle bin requires modification with proper login/authentication functionality

@router.get("/recycle-bin/get")
async def get_all_tools_from_recycle_bin_endpoint(
    request: Request, 
    user_email_id: str = Query(...), 
    tool_service: ToolService = Depends(ServiceProvider.get_tool_service),
    authorization_server: AuthorizationService = Depends(ServiceProvider.get_authorization_service),
    user_data: User = Depends(get_current_user)
):
    """Retrieves all tools from the recycle bin."""
    # Check permissions first
    if not await authorization_server.check_operation_permission(user_data.email, user_data.role, "read", "tools"):
        raise HTTPException(status_code=403, detail="You don't have permission to view tools. Only admins and developers can perform this action")
    
    user_id = user_data.email
    user_session = request.cookies.get("user_session")
    update_session_context(user_session=user_session, user_id=user_id)
    
    if not await authorization_server.has_role(user_email=user_email_id, required_role=UserRole.ADMIN):
        log.warning(f"User {user_email_id} attempted to access tool recycle bin without admin privileges")
        raise HTTPException(status_code=403, detail="Admin privileges required to access tool recycle bin")

    tools = await tool_service.get_all_tools_from_recycle_bin()
    if not tools:
        raise HTTPException(status_code=404, detail="No tools found in recycle bin")
    return tools


@router.post("/recycle-bin/restore/{tool_id}")
async def restore_tool_endpoint(
    request: Request, 
    tool_id: str, 
    user_email_id: str = Query(...), 
    tool_service: ToolService = Depends(ServiceProvider.get_tool_service),
    authorization_server: AuthorizationService = Depends(ServiceProvider.get_authorization_service),
    user_data: User = Depends(get_current_user)
):
    """Restores a tool from the recycle bin."""
    # Check permissions first
    if not await authorization_server.check_operation_permission(user_data.email, user_data.role, "update", "tools"):
        raise HTTPException(status_code=403, detail="You don't have permission to update tools. Only admins and developers can perform this action")
    
    user_id = user_data.email
    user_session = request.cookies.get("user_session")
    update_session_context(user_session=user_session, user_id=user_id)
    
    if not await authorization_server.has_role(user_email=user_email_id, required_role=UserRole.ADMIN):
        log.warning(f"User {user_email_id} attempted to restore tool without admin privileges")
        raise HTTPException(status_code=403, detail="Admin privileges required to restore tools")

    result = await tool_service.restore_tool(tool_id=tool_id)
    result["status_message"] = result.get("message", "")
    if not result.get("is_restored"):
        raise HTTPException(status_code=400, detail=result.get("message"))
    return result


@router.delete("/recycle-bin/permanent-delete/{tool_id}")
async def delete_tool_from_recycle_bin_endpoint(
    request: Request, 
    tool_id: str, 
    user_email_id: str = Query(...), 
    tool_service: ToolService = Depends(ServiceProvider.get_tool_service),
    authorization_server: AuthorizationService = Depends(ServiceProvider.get_authorization_service),
    user_data: User = Depends(get_current_user)
):
    """Permanently deletes a tool from the recycle bin."""
    # Check permissions first
    if not await authorization_server.check_operation_permission(user_data.email, user_data.role, "delete", "tools"):
        raise HTTPException(status_code=403, detail="You don't have permission to delete tools. Only admins and developers can perform this action")
    
    user_id = user_data.email
    user_session = request.cookies.get("user_session")
    update_session_context(user_session=user_session, user_id=user_id)
    if not await authorization_server.has_role(user_email=user_email_id, required_role=UserRole.ADMIN):
        log.warning(f"User {user_email_id} attempted to permanently delete tool without admin privileges")
        raise HTTPException(status_code=403, detail="Admin privileges required to permanently delete tools")

    result = await tool_service.delete_tool_from_recycle_bin(tool_id=tool_id)
    result["status_message"] = result.get("message", "")
    if not result.get("is_delete"):
        raise HTTPException(status_code=400, detail=result.get("message"))
    return result


# --- MCP Recycle Bin Endpoints ---

@router.get("/mcp/recycle-bin/get")
async def get_all_mcp_tools_from_recycle_bin_endpoint(
    request: Request,
    user_email_id: str = Query(...),
    mcp_tool_service: McpToolService = Depends(ServiceProvider.get_mcp_tool_service),
    authorization_server: AuthorizationService = Depends(ServiceProvider.get_authorization_service),
    user_data: User = Depends(get_current_user)
):
    """Retrieves all MCP tools from the recycle bin."""
    # Check permissions first
    if not await authorization_server.check_operation_permission(user_data.email, user_data.role, "read", "tools"):
        raise HTTPException(status_code=403, detail="You don't have permission to view tools. Only admins and developers can perform this action")
    
    user_id = user_data.email
    user_session = request.cookies.get("user_session")
    update_session_context(user_session=user_session, user_id=user_id)
    
    if not await authorization_server.has_role(user_email=user_email_id, required_role=UserRole.ADMIN):
        log.warning(f"User {user_email_id} attempted to access MCP recycle bin without admin privileges")
        raise HTTPException(status_code=403, detail="Admin privileges required to access recycle bin")

    tools = await mcp_tool_service.get_all_mcp_tools_from_recycle_bin()
    if not tools:
        raise HTTPException(status_code=404, detail="No MCP tools found in recycle bin")
    return tools


@router.post("/mcp/recycle-bin/restore/{tool_id}")
async def restore_mcp_tool_endpoint(
    request: Request,
    tool_id: str,
    user_email_id: str = Query(...),
    mcp_tool_service: McpToolService = Depends(ServiceProvider.get_mcp_tool_service),
    authorization_server: AuthorizationService = Depends(ServiceProvider.get_authorization_service),
    user_data: User = Depends(get_current_user)
):
    """Restores an MCP tool from the recycle bin."""
    # Check permissions first
    if not await authorization_server.check_operation_permission(user_data.email, user_data.role, "update", "tools"):
        raise HTTPException(status_code=403, detail="You don't have permission to restore tools. Only admins and developers can perform this action")
    
    user_id = user_data.email
    user_session = request.cookies.get("user_session")
    update_session_context(user_session=user_session, user_id=user_id)
    
    if not await authorization_server.has_role(user_email=user_email_id, required_role=UserRole.ADMIN):
        log.warning(f"User {user_email_id} attempted to restore MCP tool without admin privileges")
        raise HTTPException(status_code=403, detail="Admin privileges required to restore MCP tools")

    result = await mcp_tool_service.restore_mcp_tool_from_recycle_bin(tool_id=tool_id)
    result["status_message"] = result.get("message", "")
    if not result.get("is_restored"):
        raise HTTPException(status_code=400, detail=result.get("message"))
    return result


@router.delete("/mcp/recycle-bin/permanent-delete/{tool_id}")
async def delete_mcp_tool_from_recycle_bin_endpoint(
    request: Request,
    tool_id: str,
    user_email_id: str = Query(...),
    mcp_tool_service: McpToolService = Depends(ServiceProvider.get_mcp_tool_service),
    authorization_server: AuthorizationService = Depends(ServiceProvider.get_authorization_service),
    user_data: User = Depends(get_current_user)
):
    """Permanently deletes an MCP tool from the recycle bin."""
    # Check permissions first
    if not await authorization_server.check_operation_permission(user_data.email, user_data.role, "delete", "tools"):
        raise HTTPException(status_code=403, detail="You don't have permission to delete tools. Only admins and developers can perform this action")
    
    user_id = user_data.email
    user_session = request.cookies.get("user_session")
    update_session_context(user_session=user_session, user_id=user_id, tool_id=tool_id, action_on='mcp_tool', action_type='permanent_delete')
    
    if not await authorization_server.has_role(user_email=user_email_id, required_role=UserRole.ADMIN):
        log.warning(f"User {user_email_id} attempted to permanently delete MCP tool without admin privileges")
        update_session_context(tool_id='Unassigned', action_on='Unassigned', action_type='Unassigned')
        raise HTTPException(status_code=403, detail="Admin privileges required to permanently delete MCP tools from recycle bin")

    status = await mcp_tool_service.permanent_delete_mcp_tool_from_recycle_bin(tool_id=tool_id)
    update_session_context(tool_id='Unassigned', action_on='Unassigned', action_type='Unassigned')
    
    if not status.get("is_deleted"):
        log.error(f"MCP tool permanent delete failed: {status.get('message')}")
        raise HTTPException(status_code=400, detail=status.get("message"))
    return status


@router.get("/unused/get")
async def get_unused_tools_endpoint(
    request: Request,
    user_data: User = Depends(get_current_user),
    threshold_days: int = Query(default=15, description="Number of days to consider a tool as unused"),
    tool_service: ToolService = Depends(ServiceProvider.get_tool_service),
    authorization_server: AuthorizationService = Depends(ServiceProvider.get_authorization_service)
):
    """
    Retrieves tools that haven't been used for the specified number of days.
    
    Args:
        request: The FastAPI Request object
        threshold_days: Number of days to consider a tool as unused (default: 15)
        tool_service: Injected ToolService dependency
        authorization_server: Injected AuthorizationService dependency
    
    Returns:
        Dict containing list of unused tools with IST timezone formatting
    """
    # Check permissions first
    if not await authorization_server.check_operation_permission(user_data.email, user_data.role, "read", "tools"):
        raise HTTPException(status_code=403, detail="You don't have permission to view tools. Only admins and developers can perform this action")
    
    user_id = user_data.email
    user_session = request.cookies.get("user_session")
    update_session_context(user_session=user_session, user_id=user_id)
    
    if not await authorization_server.has_role(user_email=user_id, required_role=UserRole.ADMIN):
        raise HTTPException(status_code=403, detail="Admin privileges required to get unused tools")
    
    try:
        unused_tools = await tool_service.get_unused_tools(threshold_days=threshold_days)

        def format_datetime_to_days_ago(obj):
            if obj is None:
                return "Never used"
            ist_timezone = pytz.timezone("Asia/Kolkata")

            if hasattr(obj, 'tzinfo') and obj.tzinfo is not None:
                utc_time = obj
            else:
                utc_time = obj.replace(tzinfo=timezone.utc)
            
            ist_time = utc_time.astimezone(ist_timezone)
            current_time_ist = datetime.now(ist_timezone)
            time_diff = current_time_ist - ist_time
            days_ago = time_diff.days
            
            if days_ago == 0:
                return "Today"
            elif days_ago == 1:
                return "1 day ago"
            else:
                return f"{days_ago} days ago"
        
        formatted_tools = []
        for tool in unused_tools:
            formatted_tool = dict(tool)
            
            formatted_tool['created_on'] = format_datetime_to_days_ago(formatted_tool.get('created_on'))
            formatted_tool['last_used'] = format_datetime_to_days_ago(formatted_tool.get('last_used'))
            formatted_tools.append(formatted_tool)
        
        response_data = {
            "threshold_days": threshold_days,
            "unused_tools": {
                "count": len(formatted_tools),
                "details": formatted_tools
            }
        }
        
        log.info(f"Retrieved {len(unused_tools)} unused tools with threshold of {threshold_days} days")
        return response_data
        
    except Exception as e:
        log.error(f"Error retrieving unused tools: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error retrieving unused tools: {str(e)}")


@router.get("/mcp/unused/get")
async def get_unused_mcp_tools_endpoint(
    request: Request,
    user_data: User = Depends(get_current_user),
    threshold_days: int = Query(default=15, description="Number of days to consider an MCP tool as unused"),
    mcp_tool_service: McpToolService = Depends(ServiceProvider.get_mcp_tool_service),
    authorization_server: AuthorizationService = Depends(ServiceProvider.get_authorization_service)
):
    """
    Retrieves MCP tools that haven't been updated for the specified number of days.
    Note: MCP tools don't have a last_used field, so this uses updated_on timestamp.
    
    Args:
        request: The FastAPI Request object
        threshold_days: Number of days to consider an MCP tool as unused (default: 15)
        mcp_tool_service: Injected McpToolService dependency
        authorization_server: Injected AuthorizationService dependency
    
    Returns:
        Dict containing list of unused MCP tools with IST timezone formatting
    """
    # Check permissions first
    if not await authorization_server.check_operation_permission(user_data.email, user_data.role, "read", "tools"):
        raise HTTPException(status_code=403, detail="You don't have permission to view tools. Only admins and developers can perform this action")
    
    user_id = user_data.email
    user_session = request.cookies.get("user_session")
    update_session_context(user_session=user_session, user_id=user_id)
    
    if not await authorization_server.has_role(user_email=user_id, required_role=UserRole.ADMIN):
        raise HTTPException(status_code=403, detail="Admin privileges required to get unused MCP tools")
    
    try:
        unused_mcp_tools = await mcp_tool_service.get_unused_mcp_tools(threshold_days=threshold_days)

        def format_datetime_to_days_ago(obj):
            if obj is None:
                return "Never updated"
            ist_timezone = pytz.timezone("Asia/Kolkata")

            if hasattr(obj, 'tzinfo') and obj.tzinfo is not None:
                utc_time = obj
            else:
                utc_time = obj.replace(tzinfo=timezone.utc)
            
            ist_time = utc_time.astimezone(ist_timezone)
            current_time_ist = datetime.now(ist_timezone)
            time_diff = current_time_ist - ist_time
            days_ago = time_diff.days
            
            if days_ago == 0:
                return "Today"
            elif days_ago == 1:
                return "1 day ago"
            else:
                return f"{days_ago} days ago"
        
        def format_datetime_to_ist(dt_obj):
            """Format datetime to IST timezone string"""
            if dt_obj is None:
                return None
            ist_timezone = pytz.timezone("Asia/Kolkata")
            
            if hasattr(dt_obj, 'tzinfo') and dt_obj.tzinfo is not None:
                utc_time = dt_obj
            else:
                utc_time = dt_obj.replace(tzinfo=timezone.utc)
            
            ist_time = utc_time.astimezone(ist_timezone)
            return ist_time.isoformat()
        
        formatted_tools = []
        for tool in unused_mcp_tools:
            formatted_tool = dict(tool)
            
            # Format datetime fields to IST
            if formatted_tool.get('created_on'):
                formatted_tool['created_on'] = format_datetime_to_ist(formatted_tool.get('created_on'))
            if formatted_tool.get('updated_on'):
                formatted_tool['updated_on'] = format_datetime_to_ist(formatted_tool.get('updated_on'))
            if formatted_tool.get('approved_at'):
                formatted_tool['approved_at'] = format_datetime_to_ist(formatted_tool.get('approved_at'))
            
            formatted_tools.append(formatted_tool)
        
        response_data = {
            "threshold_days": threshold_days,
            "unused_mcp_tools": {
                "count": len(formatted_tools),
                "details": formatted_tools
            }
        }
        
        log.info(f"Retrieved {len(unused_mcp_tools)} unused MCP tools with threshold of {threshold_days} days")
        return response_data
        
    except Exception as e:
        log.error(f"Error retrieving unused MCP tools: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error retrieving unused MCP tools: {str(e)}")


# --- Validator Tool Endpoints ---

@router.get("/validators/get")
async def get_all_validators_endpoint(request: Request, tool_service: ToolService = Depends(ServiceProvider.get_tool_service)):
    """
    Retrieves all validator tools from the tool table.

    Returns:
    -------
    list
        A list of validator tools. If no validator tools are found, raises an HTTPException with status code 404.
    """
    user_id = request.cookies.get("user_id")
    user_session = request.cookies.get("user_session")
    update_session_context(user_session=user_session, user_id=user_id)
    validators = await tool_service.get_all_validators()
    if not validators:
        raise HTTPException(status_code=404, detail="No validator tools found")
    return validators


@router.get("/validators/get/search-paginated/")
async def search_paginated_validators_endpoint(
        request: Request,
        search_value: Optional[str] = Query(None),
        page_number: int = Query(1, ge=1),
        page_size: int = Query(20, ge=1),
        tag_names: List[str] = Query(None, description="Filter by tag names"),
        created_by: Optional[str] = Query(None, description="Filter by creator's email ID"),
        tool_service: ToolService = Depends(ServiceProvider.get_tool_service)
    ):
    """
    Searches validator tools with pagination.
    
    Parameters:
    ----------
    search_value : str, optional
        Search term to filter validator tool names.
    page_number : int
        Page number for pagination (starts from 1).
    page_size : int
        Number of validator tools per page.
    tag_names : List[str], optional
        Filter by tag names.
    created_by : str, optional
        Filter by creator's email ID.

    Returns:
    -------
    dict
        A dictionary containing the total count and paginated validator tool details.
    """
    user_id = request.cookies.get("user_id")
    user_session = request.cookies.get("user_session")
    update_session_context(user_session=user_session, user_id=user_id)
    
    result = await tool_service.get_validators_by_search_or_page(
        search_value=search_value, 
        limit=page_size, 
        page=page_number,
        tag_names=tag_names, 
        created_by=created_by
    )
    if not result["details"]:
        raise HTTPException(status_code=404, detail="No validator tools found matching criteria.")
    return result

@router.get("/pending-modules")
async def get_pending_modules_endpoint(
    request: Request,
    user_data: User = Depends(get_current_user),
    services: ServiceProvider = Depends()
):
    """
    API endpoint to retrieve pending modules with details.

    Returns:
    - Dict containing success status and detailed pending modules data.
    """
    user_id = request.cookies.get("user_id")
    user_session = request.cookies.get("user_session")
    update_session_context(user_session=user_session, user_id=user_id)
    
    try:
        from src.database.repositories import get_all_pending_modules
        
        db_manager = services.get_database_manager()
        pool = db_manager.pools.get('db_main')
        if not pool:
            raise HTTPException(status_code=500, detail="Database connection not available")
        
        pending_modules = await get_all_pending_modules(pool)
        detailed_modules = []
        for module in pending_modules:
            detailed_modules.append({
                "module_name": module.get('module_name'),
                "created_by": module.get('created_by'),
                "tool_name": module.get('tool_name'),
                "code_snippet": module.get('tool_code'),
                "created_on": module.get('created_on')
            })
        module_names = [module['module_name'] for module in pending_modules]
        log.info(f"Retrieved {len(module_names)} pending modules")
        return {
            "success": True,
            "count": len(module_names),
            "modules": module_names,
            "details": detailed_modules 
        }
    except Exception as e:
        log.error(f"Error getting pending modules: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Failed to get pending modules: {str(e)}"
        )