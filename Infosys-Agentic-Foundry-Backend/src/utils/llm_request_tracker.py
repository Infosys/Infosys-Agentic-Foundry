# © 2024-25 Infosys Limited, Bangalore, India. All Rights Reserved.
"""
LLM Request Tracker & Request Context Management Utility

This module provides comprehensive utilities for:
1. Tracking all LLM requests with unique IDs and success/failure status
2. Managing request context for non-inference operations (CRUD, evaluations, etc.)
3. Decorators for automatic request tracking

Key Features:
- Generate unique request IDs with user context (UUID_USERID_TIMESTAMP format)
- Track request lifecycle (start, success, failure)
- Log detailed information for debugging and analytics
- Store in llm_request_tracking table for Grafana dashboards
- Automatic request context management via decorators
- SessionContext and thread-local storage integration

Usage Examples:

1. For LLM Request Tracking (used in LLM wrappers):
    from src.utils.llm_request_tracker import generate_llm_request_id, log_llm_request
    
    request_id = generate_llm_request_id(user_id="john.doe@company.com")
    
    try:
        response = await llm.generate(...)
        await log_llm_request(repository, request_id, llm_call_id, ..., status="success")
    except Exception as e:
        await log_llm_request(repository, request_id, llm_call_id, ..., status="failed", error_message=str(e))

2. For API Endpoint Tracking (used in endpoint decorators):
    from src.utils.llm_request_tracker import with_request_tracking
    
    @with_request_tracking("agent_operation")
    async def create_agent_endpoint(...):
        # request_id automatically set in SessionContext
        # LLM calls within this endpoint will inherit the request_id
        ...
"""

import re
import uuid
import time
import traceback
import inspect
from functools import wraps
from datetime import datetime
from typing import Optional
from telemetry_wrapper import SessionContext, logger as log


def get_call_origin_info() -> dict:
    """
    Extract detailed information about where the LLM call originated.
    
    Returns a dict with:
    - function_name: Name of the function that called the LLM
    - file_path: File path where the call originated
    - line_number: Line number of the call
    - module_name: Python module name
    - call_stack: List of parent functions in the call chain
    - stack_depth: Depth of the call stack
    
    Strategy: 
    1. First pass: Look for workspace code (src/, agent_worker/, etc.)
    2. Second pass: If no workspace code found, accept any non-utility frame
    """
    try:
        import os
        # Get the current stack
        stack = inspect.stack()
        
        # Identify workspace root (where this file is located)
        workspace_indicators = ['src', 'agent_worker', 'tool_worker', 'Export_Agent']
        
        # Two-pass approach
        workspace_frames = []
        non_internal_frames = []
        
        for frame_info in stack:
            filename = frame_info.filename
            function = frame_info.function
            
            # Always skip these utility/wrapper frames
            if any(skip in filename for skip in [
                'llm_request_tracker.py', 
                'guardrail_aware_llm.py',
                'azure_ai_model_service.py',
                'telemetry_wrapper.py'
            ]):
                continue
            
            # Skip deep framework internals
            if any(skip in filename for skip in [
                'site-packages\\asyncio',
                'site-packages\\uvicorn',
                'asyncio\\',
                '\\asyncio\\',
            ]):
                continue
            
            frame_data = {
                'info': frame_info,
                'function': function,
                'file': filename.split('\\')[-1],
                'line': frame_info.lineno,
                'full_path': filename  # Keep full path for debugging
            }
            
            # Check if this is workspace code (more precise check)
            is_workspace = False
            for indicator in workspace_indicators:
                # Check if 'src' or other indicator appears as a directory component
                if f'\\{indicator}\\' in filename or f'/{indicator}/' in filename:
                    is_workspace = True
                    break
            
            if is_workspace:
                workspace_frames.append(frame_data)
                log.debug(f"[CALL_ORIGIN] Workspace frame: {function} in {filename}")
            else:
                non_internal_frames.append(frame_data)
                log.debug(f"[CALL_ORIGIN] Non-internal frame: {function} in {filename}")
        
        # Prefer workspace frames, fall back to any non-internal frame
        call_chain_source = workspace_frames if workspace_frames else non_internal_frames
        
        # Debug logging to understand what's being captured
        log.debug(f"[CALL_ORIGIN] Found {len(workspace_frames)} workspace frames, {len(non_internal_frames)} non-internal frames")
        if call_chain_source:
            log.debug(f"[CALL_ORIGIN] First frame: {call_chain_source[0]['function']} in {call_chain_source[0]['file']}:{call_chain_source[0]['line']}")
        
        origin_frame = None
        call_chain = []
        
        for frame_data in call_chain_source[:10]:  # Limit to top 10 frames
            call_chain.append({
                'function': frame_data['function'],
                'file': frame_data['file'],
                'line': frame_data['line']
            })
            
            if origin_frame is None:
                origin_frame = frame_data['info']
        
        if origin_frame:
            return {
                'function_name': origin_frame.function,
                'file_path': origin_frame.filename,
                'file_name': origin_frame.filename.split('\\')[-1],
                'line_number': origin_frame.lineno,
                'module_name': inspect.getmodulename(origin_frame.filename) or 'unknown',
                'call_stack': call_chain[:5],  # Limit to top 5 frames
                'stack_depth': len(call_chain)
            }
        else:
            return {
                'function_name': 'unknown',
                'file_path': 'unknown',
                'file_name': 'unknown',
                'line_number': 0,
                'module_name': 'unknown',
                'call_stack': [],
                'stack_depth': 0
            }
    except Exception as e:
        log.warning(f"Failed to extract call origin info: {e}")
        return {
            'function_name': 'error_extracting',
            'file_path': 'error',
            'file_name': 'error',
            'line_number': 0,
            'module_name': 'error',
            'call_stack': [],
            'stack_depth': 0
        }


def extract_workspace_code_from_stack_trace(stack_trace_str: str) -> dict:
    """
    Parse a full stack trace string and extract YOUR workspace code locations.
    
    This solves the async execution issue by parsing the COMPLETE stack trace
    (not just the live Python stack) to find where your actual code is.
    
    Returns:
    - origin_locations: List of dicts with {file, function, line} for YOUR code
    - entry_point: First workspace code location (where your code enters)
    - full_chain: All workspace locations in order
    """
    try:
        workspace_indicators = ['\\src\\', '\\agent_worker\\', '\\tool_worker\\', '\\Export_Agent\\', 
                               '/src/', '/agent_worker/', '/tool_worker/', '/Export_Agent/']
        
        # Parse stack trace line by line
        lines = stack_trace_str.split('\n')
        workspace_locations = []
        
        i = 0
        while i < len(lines):
            line = lines[i].strip()
            
            # Look for "File" lines in stack trace
            if line.startswith('File "') and (', line ' in line):
                # Extract file path
                try:
                    file_start = line.index('File "') + 6
                    file_end = line.index('",', file_start)
                    file_path = line[file_start:file_end]
                    
                    # Extract line number
                    line_start = line.index(', line ') + 7
                    line_end = line.index(',', line_start) if ',' in line[line_start:] else len(line)
                    line_number = line[line_start:line_end].strip()
                    
                    # Extract function name
                    func_start = line.index(', in ') + 5 if ', in ' in line else -1
                    function_name = line[func_start:].strip() if func_start > 0 else 'unknown'
                    
                    # Check if this is workspace code
                    if any(indicator in file_path for indicator in workspace_indicators):
                        # Skip internal utility/wrapper files (same as live stack filtering)
                        filename_lower = file_path.lower()
                        if any(skip in filename_lower for skip in [
                            'llm_request_tracker.py',
                            'guardrail_aware_llm.py',
                            'azure_ai_model_service.py',
                            'telemetry_wrapper.py'
                        ]):
                            continue  # Skip this frame
                        
                        # Get the actual code line (next line in stack trace)
                        code_line = lines[i + 1].strip() if i + 1 < len(lines) else ''
                        
                        workspace_locations.append({
                            'file': file_path.split('\\')[-1].split('/')[-1],  # Just filename
                            'full_path': file_path,
                            'function': function_name,
                            'line': int(line_number) if line_number.isdigit() else 0,
                            'code': code_line
                        })
                except (ValueError, IndexError) as e:
                    pass  # Skip malformed lines
            
            i += 1
        
        if workspace_locations:
            return {
                'found': True,
                'entry_point': workspace_locations[0],  # First workspace code (excluding wrappers)
                'full_chain': workspace_locations,
                'depth': len(workspace_locations)
            }
        else:
            return {
                'found': False,
                'entry_point': None,
                'full_chain': [],
                'depth': 0
            }
    
    except Exception as e:
        log.warning(f"Failed to parse stack trace: {e}")
        return {
            'found': False,
            'entry_point': None,
            'full_chain': [],
            'depth': 0,
            'error': str(e)
        }


def generate_llm_request_id(user_id: str) -> str:
    """
    Generate a unique request ID with user context for better visibility.
    
    Format: {short_uuid}_{sanitized_user_id}_{timestamp}
    Example: a3f5b2c7_john.doe@company.com_20260513143022
    
    This format provides:
    - Uniqueness: UUID component ensures no collisions even with concurrent requests
    - User visibility: User ID embedded for easy grep/search
    - Temporal context: Timestamp for chronological ordering
    
    Args:
        user_id: User identifier (email or username)
        
    Returns:
        Unique request ID string
    """
    # Generate short UUID (first 8 characters for readability)
    short_uuid = str(uuid.uuid4())[:8]
    
    # Create timestamp
    timestamp = datetime.now().strftime("%Y%m%d%H%M%S%f")[:17]  # Include milliseconds
    
    # Sanitize user_id to prevent issues with special characters
    # Keep alphanumeric, @, ., _, - characters
    safe_user_id = re.sub(r'[^a-zA-Z0-9@._-]', '_', user_id)
    
    # Construct request ID
    request_id = f"{short_uuid}_{safe_user_id}_{timestamp}"
    
    return request_id


async def log_llm_request(
    repository,
    request_id: str,
    llm_call_id: str,
    user_id: str,
    session_id: str,
    model_name: str,
    status: str,
    duration_ms: Optional[int] = None,
    error_message: Optional[str] = None,
    agent_id: Optional[str] = None,
    agent_name: Optional[str] = None,
    request_source: Optional[str] = None,
    request_context: Optional[dict] = None,
    input_tokens: Optional[int] = None,
    output_tokens: Optional[int] = None,
    total_tokens: Optional[int] = None,
    error_type: Optional[str] = None,
    stack_trace: Optional[str] = None,
    retry_count: Optional[int] = 0,
    department_name: Optional[str] = None
) -> None:
    """
    Log LLM request to database with comprehensive production-grade tracking.
    
    This function captures granular details for debugging and monitoring:
    - Who made the request (user_id, session_id)
    - What triggered it (request_source, request_context)
    - Success/failure status with detailed error information
    - Performance metrics (duration, tokens)
    - Full error diagnostics (error_type, stack_trace)
    - Request correlation (request_id ties all LLM calls from one user request)
    
    Args:
        repository: LLMRequestTrackingRepository instance
        request_id: Correlation ID - same for all LLM calls in a single user request
        llm_call_id: Unique ID for this specific LLM call
        user_id: User who made the request
        session_id: Session identifier
        model_name: LLM model used
        status: Request status ('success' or 'failed')
        duration_ms: Request duration in milliseconds (from LLM response metadata)
        error_message: Human-readable error message (optional)
        agent_id: Agent ID if applicable (optional, NULL for tool/eval calls)
        agent_name: Agent name if applicable (optional)
        request_source: What triggered the request (agent_inference, tool_call, evaluation, etc.)
        request_context: Additional context as dict (converted to JSON string)
        input_tokens: Number of input tokens
        output_tokens: Number of output tokens  
        total_tokens: Total tokens used
        error_type: Type/category of error (e.g., 'APIError', 'Timeout', 'RateLimitError')
        stack_trace: Full stack trace for debugging failures
        retry_count: Number of retries attempted
    """
    
    log.info(f"🔧 [log_llm_request] CALLED for request_id={request_id}, llm_call_id={llm_call_id}, status={status}, source={request_source}")
    log.info(f"🔧 [log_llm_request] Repository type: {type(repository)}")
    
    # Convert request_context dict to JSON string
    import json
    request_context_str = None
    if request_context:
        try:
            request_context_str = json.dumps(request_context, default=str)
        except Exception as e:
            log.warning(f"Failed to serialize request_context: {e}")
            request_context_str = str(request_context)
    
    # Truncate long fields to prevent database issues
    if error_message and len(error_message) > 2000:
        error_message = error_message[:2000] + "... (truncated)"
    
    if stack_trace and len(stack_trace) > 5000:
        stack_trace = stack_trace[:5000] + "... (truncated)"
    
    # Debug log with detailed information (will be removed after testing)
    log.info(f"""
📊 [DEBUG] Logging LLM Request to Database:
  ├─ request_id: {request_id}
  ├─ user_id: {user_id}
  ├─ session_id: {session_id}
  ├─ agent_id: {agent_id if agent_id else 'NULL (tool/eval call)'}
  ├─ agent_name: {agent_name if agent_name else 'NULL (tool/eval call)'}
  ├─ model_name: {model_name}
  ├─ request_source: {request_source if request_source else 'unknown'}
  ├─ request_context: {request_context_str[:100] if request_context_str else 'None'}...
  ├─ tokens: input={input_tokens}, output={output_tokens}, total={total_tokens}
  ├─ status: {status}
  ├─ duration_ms: {duration_ms if duration_ms is not None else 'N/A'}
  ├─ error_type: {error_type if error_type else 'None'}
  ├─ error_message: {error_message[:100] if error_message else 'None'}...
  ├─ retry_count: {retry_count}
  └─ stack_trace: {'Present' if stack_trace else 'None'}
    """)
    
    try:
        # Insert into database
        await repository.insert_request(
            request_id=request_id,
            llm_call_id=llm_call_id,
            user_id=user_id,
            session_id=session_id,
            model_name=model_name,
            status=status,
            duration_ms=duration_ms,
            error_message=error_message,
            agent_id=agent_id,
            agent_name=agent_name,
            request_source=request_source,
            request_context=request_context_str,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            total_tokens=total_tokens,
            error_type=error_type,
            stack_trace=stack_trace,
            retry_count=retry_count,
            department_name=department_name
        )
        
        # Success log
        if status == "success":
            log.info(f"✅ LLM Request Logged: {llm_call_id} (request={request_id}) | Status: {status} | Duration: {duration_ms}ms | Model: {model_name}")
        else:
            log.error(f"❌ LLM Request Failed: {llm_call_id} (request={request_id}) | Status: {status} | Error: {error_message}")
            
    except Exception as e:
        # Even if logging fails, don't break the main flow
        log.error(f"⚠️ Failed to log LLM request {llm_call_id} (request={request_id}) to database: {e}", exc_info=True)


# Removed complex error categorization - just use raw exception message
# def categorize_error(exception: Exception) -> tuple[str, str]:
#     """No longer needed - we use simple success/failed with raw error message"""
#     pass


class LLMRequestContext:
    """
    Context manager for tracking LLM requests with automatic error handling.
    
    Usage:
        async with LLMRequestContext(repository, user_id, session_id, model_name) as tracker:
            response = await llm.generate(...)
            tracker.set_response(response)
    """
    
    def __init__(
        self,
        repository,
        user_id: str,
        session_id: str,
        model_name: str,
        agent_id: Optional[str] = None,
        agent_name: Optional[str] = None
    ):
        self.repository = repository
        self.user_id = user_id
        self.session_id = session_id
        self.model_name = model_name
        self.agent_id = agent_id
        self.agent_name = agent_name
        
        self.request_id = generate_llm_request_id(user_id)
        self.start_time = None
        self.duration_ms = None
        self.status = "failed"  # Default to failed, change to success if completes
        self.error_message = None
        
    async def __aenter__(self):
        """Start tracking the request"""
        self.start_time = time.time()
        log.info(f"🔵 LLM Request Started: {self.request_id}")
        return self
        
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Complete tracking the request"""
        # Calculate duration
        if self.start_time:
            self.duration_ms = int((time.time() - self.start_time) * 1000)
        
        # Simple status and error handling
        if exc_val is not None:
            self.status = "failed"
            self.error_message = str(exc_val)  # Raw exception message
        else:
            self.status = "success"
            
        # Log to database
        await log_llm_request(
            repository=self.repository,
            request_id=self.request_id,
            user_id=self.user_id,
            session_id=self.session_id,
            model_name=self.model_name,
            status=self.status,
            duration_ms=self.duration_ms,
            error_message=self.error_message,
            agent_id=self.agent_id,
            agent_name=self.agent_name
        )
        
        # Don't suppress exceptions
        return False
    
    def set_response(self, response):
        """Optional: Set response metadata if needed"""
        pass


# =============================================================================
# REQUEST CONTEXT MANAGEMENT FOR NON-INFERENCE OPERATIONS
# =============================================================================

def generate_operation_request_id(operation_type: str, user_id: str = "system") -> str:
    """
    Generate a request_id for non-inference operations (CRUD, evaluations, etc.).
    
    Args:
        operation_type: Type of operation (e.g., "agent_operation", "tool_operation")
        user_id: User identifier
        
    Returns:
        Generated request_id with operation prefix
        
    Example:
        >>> generate_operation_request_id("agent_operation", "john@example.com")
        'req_agen_a3f5b2c7_john_example_com_1735680000'
    """
    # Create short prefix from operation type (first 4 chars)
    prefix = operation_type.replace("_", "")[:4]
    sanitized_user = user_id[:20].replace('@', '_').replace('.', '_')
    return f"req_{prefix}_{str(uuid.uuid4())[:8]}_{sanitized_user}_{int(time.time())}"


def set_operation_context(
    request_id: str,
    user_id: str = "system",
    operation_type: Optional[str] = None,
    **extra_context
):
    """
    Set SessionContext for non-inference operations.
    
    This ensures that any LLM calls made within the operation will inherit
    the request_id for proper correlation tracking.
    
    Args:
        request_id: Request identifier
        user_id: User identifier
        operation_type: Type of operation for categorization
        **extra_context: Additional context fields
        
    Example:
        set_operation_context(
            request_id="req_agen_123_user_456",
            user_id="john@example.com",
            operation_type="agent_operation"
        )
    """
    context_data = {
        'user_id': user_id,
        'request_id': request_id,
    }
    
    # Add call_category for categorization if operation_type provided
    if operation_type:
        context_data['call_category'] = operation_type
    
    # Add any extra context
    context_data.update(extra_context)
    
    SessionContext.set(**context_data)
    
    # Also set in thread-local fallback
    try:
        from src.models.guardrail_aware_llm import _set_request_id
        _set_request_id(request_id)
    except Exception as e:
        log.debug(f"Could not set thread-local request_id: {e}")


def clear_operation_context():
    """
    Clear operation context from SessionContext.
    
    Called automatically by the @with_request_tracking decorator after
    the operation completes.
    """
    SessionContext.set(
        request_id='Unassigned',
        call_category='Unassigned',
        user_id='Unassigned'
    )
    
    try:
        from src.models.guardrail_aware_llm import _clear_request_id
        _clear_request_id()
    except Exception as e:
        log.debug(f"Could not clear thread-local request_id: {e}")


def with_request_tracking(operation_type: str):
    """
    Decorator to automatically set request_id and categorization for operations.
    
    This decorator should be applied to all API endpoints that make LLM calls
    (except inference endpoints which handle tracking internally).
    
    Features:
    - Generates unique request_id
    - Sets SessionContext with request_id and operation type
    - All LLM calls within the decorated function inherit the request_id
    - Automatic cleanup after function completes
    
    Args:
        operation_type: Operation category for analytics grouping
            Examples:
            - "agent_operation" (agent onboard/update)
            - "tool_operation" (tool add/update/import)
            - "tool_generation_workflow" (NLP-to-code generation)
            - "data_connector_query_generation" (NL to SQL)
            - "mcp_server_generation" (MCP metadata)
            - "evaluation" (LLM-as-Judge)
            - "evaluation_consistency_preview", etc.
            - "auto_suggest" (query suggestions)
            - "feedback_learning" (feedback responses)
    
    Usage:
        @with_request_tracking("agent_operation")
        async def create_agent_endpoint(...):
            # request_id automatically set
            # Any LLM calls here will be tracked with same request_id
            ...
    
    Example:
        @router.post("/agent/onboard")
        @with_request_tracking("agent_operation")
        async def onboard_agent_endpoint(request: AgentOnboardingRequest, user_data: User):
            # Generate system prompt via LLM
            system_prompt = await generate_system_prompt(...)
            
            # All LLM calls tracked with same request_id
            ...
    """
    def decorator(func):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            # Try to extract user_id from common parameter names
            user_id = "system"
            if 'user_data' in kwargs and kwargs['user_data']:
                user_id = getattr(kwargs['user_data'], 'email', 'system')
            
            # Generate request_id
            request_id = generate_operation_request_id(operation_type, user_id)
            
            # Set context
            set_operation_context(
                request_id=request_id,
                user_id=user_id,
                operation_type=operation_type
            )
            
            log.debug(f"🔧 [OPERATION] {operation_type} started - request_id: {request_id}, user: {user_id}")
            
            try:
                return await func(*args, **kwargs)
            finally:
                # Cleanup
                clear_operation_context()
                log.debug(f"🔧 [OPERATION] {operation_type} completed - request_id: {request_id}")
        
        return wrapper
    return decorator
