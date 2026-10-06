# © 2024-25 Infosys Limited, Bangalore, India. All Rights Reserved.
import ast
import os
import re
import json
import time
import asyncio
from pathlib import Path
from datetime import datetime
from copy import deepcopy
from abc import ABC, abstractmethod
from typing_extensions import TypedDict
from typing import Any, List, Dict, Optional, Annotated, Union, Literal, Tuple
from fastapi import HTTPException
from langchain_core.tools import BaseTool, StructuredTool, tool
from langgraph.types import Command
from langgraph.errors import GraphRecursionError
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import JsonOutputParser, StrOutputParser
from langgraph.prebuilt import create_react_agent
from langchain_core.messages import AIMessage, HumanMessage, ChatMessage, AnyMessage
from langgraph.graph.message import add_messages
from langgraph.graph import START, END
from langgraph.graph.state import CompiledStateGraph, StateGraph
from langgraph.types import StreamWriter
from src.utils.helper_functions import get_timestamp
from src.utils.errors import LLMInfrastructureError
from src.utils.llm_error_handler import handle_llm_errors
from src.inference.inference_utils import InferenceUtils

from src.schemas import AgentInferenceRequest, AdminConfigLimits
from src.config.constants import AgentType
from src.config.application_config import app_config
from src.utils.secrets_handler import current_user_email, current_user_department
from src.utils.sandbox import get_builtins, get_sandbox_builtins, get_sandbox_extras, SANDBOX_EXEMPT_TOOLS
from telemetry_wrapper import logger as log, update_session_context
from src.utils.guardrail_helpers import (
    get_guardrail_response_from_exception, get_guardrail_response_from_errors,
    log_guardrail_or_exception, format_guardrail_user_response,
)
from src.utils.phoenix_manager import ensure_project_registered, traced_project_context, log_trace_context
from src.storage import get_storage_client

from src.utils.message_queue_factory.message_queue_manager import MessageQueueManager

# Define common TypedDict for state if applicable to all workflows
class BaseWorkflowState(TypedDict):
    query: str
    response: str
    past_conversation_summary: str
    executor_messages: Annotated[List[AnyMessage], add_messages]
    ongoing_conversation: Annotated[List[AnyMessage], add_messages]
    agentic_application_id: str
    session_id: str
    model_name: str
    start_timestamp: datetime
    end_timestamp: datetime
    reset_conversation: Optional[bool] = False
    errors: List[str]
    parts: List[Dict[Any, Any]]  # For formatted response parts
    parts_storage_dict: Annotated[Dict[Any, Any], InferenceUtils.add_parts]  # For storing parts temporarily
    response_formatting_flag: bool = True
    context_flag : bool = True
    file_context_management_flag: bool = False  # When True (and context_flag=True), use file-based context with tool
    validation_score: Optional[float] = None
    validation_feedback: Optional[str] = None
    validation_attempts: int = 0
    mentioned_agent_id: str = None
    evaluation_score: float = None
    evaluation_feedback: str = None
    evaluation_attempts: int = 0
    interrupt_items: Optional[List[str]] = None  # List of tool/node names to interrupt at during execution
    department_name: Optional[str] = None  # Department name for department-scoped feedback learning
    execution_mode: Optional[str] = None  # User-selected execution mode (None=SKILL.md default, "auto"=SmartRouter, or specific mode)

class BaseAgentInference(ABC):
    """
    Abstract base class for LangGraph-based inference workflows.
    Provides common dependencies and defines the interface for building workflows.
    """

    def __init__(self, inference_utils: InferenceUtils):
        self.inference_utils = inference_utils
        self.chat_service = inference_utils.chat_service
        self.tool_service = inference_utils.tool_service
        self.mcp_tool_service = self.tool_service.mcp_tool_service
        self.agent_service = inference_utils.agent_service
        self.model_service = inference_utils.model_service
        self.feedback_learning_service = inference_utils.feedback_learning_service
        self.evaluation_service = inference_utils.evaluation_service
        self.storage_provider = os.getenv('STORAGE_PROVIDER', "")
        self.storage_client = None
        self.message_queue=False
        self.admin_config_service = self.chat_service.admin_config_service


    # --- Helper Methods ---

    @staticmethod
    def _safe_background_task(coro, *, name: str = "background_task"):
        """
        Schedule *coro* as a background ``asyncio.Task`` with proper error handling.

        Unlike bare ``asyncio.create_task()``, failures are logged instead of
        silently swallowed — preventing "Task exception was never retrieved"
        warnings and ensuring observability for fire-and-forget operations.

        Args:
            coro: An awaitable (coroutine) to schedule.
            name: A human-readable label used in log messages on failure.

        Returns:
            The created ``asyncio.Task`` instance.
        """
        task = asyncio.create_task(coro, name=name)

        def _on_done(t: asyncio.Task):
            if t.cancelled():
                log.debug(f"Background task '{name}' was cancelled")
                return
            exc = t.exception()
            if exc is not None:
                log.error(
                    f"Background task '{name}' failed: {exc}",
                    exc_info=(type(exc), exc, exc.__traceback__),
                )

        task.add_done_callback(_on_done)
        return task

    def _initialize_storage_client(self):
        if self.storage_provider and self.storage_provider.strip():
            try:
                self.storage_client = get_storage_client(self.storage_provider)
            except ValueError as e:
                log.info(f"Warning: Storage client initialization failed: {e}")
            except Exception as e:
                log.info(f"Warning: Storage configuration error: {e}")

    async def _ensure_file_context_prompt_from_blob(
        self, prompt_path: str, department: str, safe_agent_name: str
    ) -> bool:
        """
        If a file_context_prompt .md file is missing locally, attempt to
        restore it from blob storage (single-file download).

        Returns True if the file exists on disk after the attempt.
        """
        if os.path.exists(prompt_path):
            return True
        try:
            from src.utils.workspace_blob_sync import WorkspaceBlobSync
            if not self.storage_client:
                self._initialize_storage_client()
            if not self.storage_client:
                return False
            blob_key = f"{department}/file_context_prompts/{safe_agent_name}_file_context_prompt.md"
            syncer = WorkspaceBlobSync(
                storage_client=self.storage_client,
                workspace_root="./agent_workspaces",
                department=department,
            )
            result = await syncer.restore_file(blob_key, prompt_path)
            if result and result.success:
                log.info(f"[BlobRestore] Restored file_context_prompt from blob: {blob_key}")
                return True
            return False
        except Exception as e:
            log.debug(f"[BlobRestore] file_context_prompt restore skipped (non-critical): {e}")
            return False

    # ================================================================== #
    #  Kafka MCP tool wrapper  (static, lives on the LangGraph base class)
    # ================================================================== #

    @staticmethod
    def _make_message_queue_mcp_tool(
        mcp_tool: StructuredTool,
        mcp_server_id: str,
        mq_manager: MessageQueueManager,
    ) -> StructuredTool:
        """
        Wrap a live MCP ``StructuredTool`` so that invocation is dispatched
        to a remote message queue worker instead of being executed locally.

        Preserves ``name``, ``description``, and ``args_schema`` from the
        original MCP tool.  The ``mcp_server_id`` is sent as the ``tool_id``
        in every message so the worker can fetch the correct MCP config
        from the DB and connect to the right server.

        Args:
            mcp_tool: The ``StructuredTool`` returned by the MCP client.
            mcp_server_id: Database PK of the MCP server definition
                           (prefixed with ``mcp_``).
            mq_manager: A :class:`MessageQueueManager` instance.

        Returns:
            A new ``StructuredTool`` whose ``coroutine`` publishes to the
            message queue and waits for the worker response.
        """
        import uuid

        tool_name = mcp_tool.name

        async def _kafka_mcp_dispatch(**kwargs) -> str:
            tool_call_id = uuid.uuid4().hex
            consumer = mq_manager.create_response_consumer()
            try:
                mq_manager.send_tool_request(
                    tool_call_id=tool_call_id,
                    tool_id=mcp_server_id,
                    tool_name=tool_name,
                    args=kwargs,
                )
                response = await mq_manager.collect_responses(consumer, tool_call_id)

                if response is None:
                    return f"[MQ timeout] No response received for {tool_name}"
                if response.get("status") != "success":
                    return f"[MQ error] {response.get('result', 'Unknown error')}"
                return str(response.get("result", ""))
            finally:
                try:
                    consumer.close()
                except Exception:
                    pass

        return StructuredTool(
            name=mcp_tool.name,
            description=mcp_tool.description,
            args_schema=mcp_tool.args_schema,
            coroutine=_kafka_mcp_dispatch,
        )

    # ================================================================== #
    #  Kafka-worker-aware executor agent builder
    # ================================================================== #

    async def _get_react_agent_as_executor_agent(
        self,
        llm: Any,
        system_prompt: str,
        checkpointer: Any = None,
        tool_ids: List[str] = [],
        tool_versions: Dict[str, str] = None,  # Map of tool_id -> version
        interrupt_tool: bool = False,
        knowledgebase_names: str = None,
        use_kafka_tool_worker: bool = False,
        session_id: str = None,
        use_shell_memory: bool = True,
        agent_id: str = None,
        context_flag: bool = True,
        file_context_management_flag: bool = False,
        extra_tools: List[Any] = None,
        additional_paths: list = None,
        allowed_absolute_mount_roots: list = None,
    ) -> Tuple[CompiledStateGraph, list, Any]:
        """
        Create a React agent with tools loaded dynamically.

        When ``use_kafka_tool_worker=True`` every Python / MCP tool loaded
        from the database is transparently wrapped so that invocations are
        dispatched to a remote Kafka worker instead of being executed in the
        main process.  Built-in tools (memory, knowledgebase, shell) are
        always executed locally.

        ``additional_paths`` is an optional list of dicts with keys 'path'
        and 'permission' for custom folder mounts in the agent shell.

        ``allowed_absolute_mount_roots`` is an optional list of absolute
        directory paths this agent is allowed to mount (from agent_config.json).
        
        Args:
            tool_versions: Optional dict mapping tool_id -> version (e.g., 'v1', 'v2').
                          If provided, loads versioned code from tool_versions_table.
        """
        log.info(f"[{session_id}] _get_react_agent_as_executor_agent called | agent_id={agent_id}, tool_count={len(tool_ids)}, kafka={use_kafka_tool_worker}, shell_memory={use_shell_memory}, context_flag={context_flag}, file_context_mgmt={file_context_management_flag}")
        # Initialize tool_versions if not provided
        if tool_versions is None:
            tool_versions = {}
            
        # local_var for exec() context, including secrets handlers and access control decorators
        base_local_extras = get_sandbox_extras()
        sandbox_exempt_local_var = {
            "__builtins__": get_builtins(),  # Full builtins for exempt tools
            **base_local_extras,
        }
        local_var = {
            "__builtins__": get_sandbox_builtins(),
            **base_local_extras,
        }

        tool_list: List[BaseTool | StructuredTool] = []
        
        # ========== MEMORY TOOLS SELECTION ==========
        # Only add memory tools if:
        # 1. context_flag is True (context management enabled)
        # 2. file_context_management_flag is True (use file-based context with tools)
        
        agent_shell = None  # Will hold AgentShell instance
        memory_loaded = False

        if not context_flag:
            log.info(f"[{session_id}] Skipping memory tools (context_flag=False) - no context management")
            memory_loaded = True  # Skip memory loading
        elif not file_context_management_flag:
            log.info(f"[{session_id}] Skipping memory tools (file_context_management_flag=False) - using traditional DB context")
            memory_loaded = True  # Skip memory loading, will use DB-based conversation fetch

        # Option 1: AgentShell - Single tool with Unix-like interface (RECOMMENDED)
        # Only when context_flag=True AND file_context_management_flag=True
        if not memory_loaded and use_shell_memory and agent_id and session_id:
            try:
                from src.memory.agent_shell.tools import get_shell_tools_for_session
                
                # Get user email and department from context variables for hierarchical storage
                user_email = current_user_email.get(None)
                user_department = current_user_department.get("General")

                # --- Auto-restore from blob if workspace is missing ---
                try:
                    from src.utils.workspace_blob_sync import WorkspaceBlobSync
                    if not self.storage_client:
                        self._initialize_storage_client()
                    if self.storage_client:
                        syncer = WorkspaceBlobSync(
                            storage_client=self.storage_client,
                            workspace_root="./agent_workspaces",
                            department=user_department or "General",
                            agent_id=agent_id,
                            session_id=session_id,
                            user_email=user_email or "",
                            project_root=os.path.abspath("."),
                        )
                        restore_report = await syncer.check_and_restore_if_needed()
                        if restore_report and restore_report.synced > 0:
                            log.info(f"[BlobRestore] Restored {restore_report.synced} files from blob for agent {agent_id}")
                        # Targeted: restore database cache if databases/ dir is missing/empty
                        db_report = await syncer.restore_database_cache()
                        if db_report and db_report.synced > 0:
                            log.info(f"[BlobRestore] Restored {db_report.synced} database cache files from blob")
                except Exception as e:
                    log.debug(f"[BlobRestore] Skipped (non-critical): {e}")
                # --- End auto-restore ---

                agent_shell, shell_tools = get_shell_tools_for_session(
                    agent_id=agent_id,
                    session_id=session_id,
                    user_email=user_email,
                    workspace_root="./agent_workspaces",
                    department=user_department,
                    additional_paths=additional_paths,
                    allowed_absolute_mount_roots=allowed_absolute_mount_roots,
                )
                tool_list.extend(shell_tools)
                memory_loaded = True
                log.info(f"[{session_id}] ✅ AgentShell loaded for user={user_email}, agent={agent_id}, session={session_id[:12]}... (1 tool: run_shell_command)")
                log.info(f"[{session_id}]    📁 Workspace: {agent_shell.shell_root}")
                log.info(f"[{session_id}]    🔍 Commands: ls, cd, cat, grep, find, echo, semgrep (semantic search)")
            except Exception as e:
                log.warning(f"[{session_id}] Failed to load AgentShell, falling back to database memory: {e}")
                use_shell_memory = False
        
        # Option 2: Database-backed memory (fallback when AgentShell fails)
        if not memory_loaded:
            manage_memory_tool = await self.inference_utils.create_manage_memory_tool()
            tool_list.append(manage_memory_tool)

            search_memory_tool = await self.inference_utils.create_search_memory_tool(
                embedding_model=self.inference_utils.embedding_model
            )
            tool_list.append(search_memory_tool)
            log.info(f"[{session_id}] Database memory tools loaded (2 tools: manage_memory, search_memory)")

        # Add knowledgebase retriever tool if knowledgebase_names is provided
        if knowledgebase_names:
            try:
                from src.utils.knowledgebase import knowledgebase_retriever
                tool_list.append(knowledgebase_retriever)
                log.info(f"[{session_id}] Knowledgebase retriever tool added for KB: {knowledgebase_names}")
            except Exception as e:
                log.error(f"[{session_id}] Error loading knowledgebase_retriever tool: {e}")

        # ========== DATABASE TOOLS AUTO-INJECTION ==========
        db_connection_names = getattr(self, '_db_connection_names', None)
        if db_connection_names:
            try:
                from src.inference.database_tools_integration import get_database_tools_for_injection
                db_tools = get_database_tools_for_injection(db_connection_names)
                log.info(f"Database tools auto-injected for connections: {db_connection_names}")

                # Also load run_shell_command so agent can read schema files
                if not any(hasattr(t, 'name') and t.name == 'run_shell_command' for t in tool_list):
                    try:
                        from src.memory.agent_shell.tools import get_shell_tools_for_session
                        user_email = current_user_email.get(None)
                        user_department = current_user_department.get("General")
                        # Security: validate additional_paths entries before
                        # passing to shell tools — reject traversal sequences
                        _sanitized_paths = []
                        if additional_paths:
                            for _ap_entry in additional_paths:
                                _ap_path = _ap_entry.get("path", "") if isinstance(_ap_entry, dict) else ""
                                if ".." in str(_ap_path):
                                    log.warning(f"[BaseAgentInference] Rejecting additional_path with traversal: {_ap_path!r}")
                                    continue
                                _sanitized_paths.append(_ap_entry)
                        agent_shell, shell_tools = get_shell_tools_for_session(
                            agent_id=agent_id,
                            session_id=session_id,
                            user_email=user_email,
                            workspace_root="./agent_workspaces",
                            department=user_department,
                            additional_paths=_sanitized_paths,
                            allowed_absolute_mount_roots=allowed_absolute_mount_roots,
                        )
                        tool_list.extend(shell_tools)
                    except Exception as e:
                        log.warning(f"Failed to load run_shell_command for db schema access: {e}")

                tool_list.extend(db_tools)
            except Exception as e:
                log.error(f"Error loading database tools: {e}")

        # ========== MOUNTED FOLDERS AUTO-INJECTION ==========
        # If the agent has any additional_paths (folder mounts) or
        # allowed_absolute_mount_roots configured, ensure run_shell_command is
        # available so the agent can actually read those mounted files. This
        # runs independently of file_context_management_flag / DB triggers so
        # the tool matches the prompt hints emitted by react_agent_inference
        # (and its meta/planner_meta variants).
        _has_relative_mounts = bool(additional_paths)
        _has_absolute_mounts = bool(allowed_absolute_mount_roots)
        if (_has_relative_mounts or _has_absolute_mounts) and agent_id and session_id:
            if not any(hasattr(t, 'name') and t.name == 'run_shell_command' for t in tool_list):
                try:
                    from src.memory.agent_shell.tools import get_shell_tools_for_session
                    user_email = current_user_email.get(None)
                    user_department = current_user_department.get("General")
                    # Security: validate additional_paths entries before
                    # passing to shell tools — reject traversal sequences
                    _sanitized_paths = []
                    if additional_paths:
                        for _ap_entry in additional_paths:
                            _ap_path = _ap_entry.get("path", "") if isinstance(_ap_entry, dict) else ""
                            if ".." in str(_ap_path):
                                log.warning(f"[BaseAgentInference] Rejecting additional_path with traversal: {_ap_path!r}")
                                continue
                            _sanitized_paths.append(_ap_entry)
                    agent_shell, shell_tools = get_shell_tools_for_session(
                        agent_id=agent_id,
                        session_id=session_id,
                        user_email=user_email,
                        workspace_root="./agent_workspaces",
                        department=user_department,
                        additional_paths=_sanitized_paths,
                        allowed_absolute_mount_roots=allowed_absolute_mount_roots,
                    )
                    tool_list.extend(shell_tools)
                    log.info(
                        f"[{session_id}] ✅ run_shell_command auto-injected for mounts "
                        f"(relative={_has_relative_mounts}, absolute={_has_absolute_mounts})"
                    )
                except Exception as e:
                    log.warning(f"[{session_id}] Failed to auto-load run_shell_command for mounts: {e}")

        # ========== EXECUTE_PYTHON_CODE TOOL (when file_context_management_flag) ==========
        # Inject execute_python_code into ALL agent types when file_context is
        # enabled, so agents can run Python against mounted files (pandas, etc.)
        if file_context_management_flag and agent_id:
            if not any(hasattr(t, 'name') and t.name == 'execute_python_code' for t in tool_list):
                try:
                    from src.agentos.skill_tools import create_skill_tools
                    _AGENTOS_BASE = app_config.AGENT_WORKSPACES_BASE
                    _AGENTOS_FOLDER = "agentos_agents"

                    # Sanitize env-sourced base path: resolve and reject traversal
                    _base_resolved = Path(os.path.realpath(_AGENTOS_BASE))
                    if ".." in _AGENTOS_BASE:
                        log.warning(f"[BaseAgentInference] Rejecting AGENT_WORKSPACES_BASE with traversal: {_AGENTOS_BASE!r}")
                        raise ValueError("Invalid workspace base path")

                    # Resolve agent_dir from agent_id
                    _agent_dir = None
                    _dept = current_user_department.get("General")
                    _candidate = _base_resolved / _dept / _AGENTOS_FOLDER / agent_id
                    if _candidate.exists():
                        _agent_dir = _candidate
                    else:
                        if _base_resolved.exists():
                            for _d in _base_resolved.iterdir():
                                if _d.is_dir() and not _d.name.startswith("_"):
                                    _c2 = _d / _AGENTOS_FOLDER / agent_id
                                    if _c2.exists():
                                        _agent_dir = _c2
                                        break
                        if not _agent_dir:
                            _fallback = _base_resolved / "General" / _AGENTOS_FOLDER / agent_id
                            if _fallback.exists():
                                _agent_dir = _fallback

                    if _agent_dir:
                        _code_tools = create_skill_tools(_agent_dir)
                        for _ct in _code_tools:
                            if hasattr(_ct, 'name') and _ct.name not in {t.name for t in tool_list if hasattr(t, 'name')}:
                                tool_list.append(_ct)
                        log.info(f"✅ execute_python_code injected for agent {agent_id} (file_context=True)")

                        # Detect writable mount names for prompt injection later
                        try:
                            _acfg_path = _agent_dir / "agent_config.json"
                            if _acfg_path.exists():
                                import json as _json_tmp
                                _acfg = _json_tmp.loads(_acfg_path.read_text(encoding="utf-8"))
                                _writable_mount_names = [
                                    "/" + "".join(c if c.isalnum() or c in ("-", "_") else "_" for c in Path(e.get("path", "").strip()).name.lower())
                                    for e in (_acfg.get("additional_paths") or [])
                                    if e.get("permission", "read").strip().lower() == "read-write" and e.get("path", "").strip()
                                ]
                            else:
                                _writable_mount_names = []
                        except Exception:
                            _writable_mount_names = []
                    else:
                        log.warning(f"⚠️ Cannot resolve agent_dir for {agent_id} — skipping execute_python_code injection")
                        _writable_mount_names = []
                except Exception as e:
                    log.warning(f"Failed to inject execute_python_code: {e}")
                    _writable_mount_names = []

        # ========== MESSAGE QUEUE SETUP (only when use_kafka_tool_worker=True) ==========
        mq_manager = None
        if use_kafka_tool_worker:
            from src.utils.message_queue_factory.mq_factory import create_mq_manager as _create_mq_manager
            from tool_worker.tool_wrappers import make_message_queue_tool
            mq_manager = _create_mq_manager()

        # ========== PYTHON TOOLS ==========
        mcp_server_ids: List[str] = []

        for tool_id in tool_ids:
            if tool_id.startswith("mcp_"):
                mcp_server_ids.append(tool_id)
                log.debug(f"[{session_id}] Deferred MCP tool: {tool_id}")
                continue

            try:
                log.info(f"[{session_id}] Loading Python tool for ID: {tool_id}")

                # Get tool metadata from tool_table
                tool_record = await self.tool_service.tool_repo.get_tool_record(
                    tool_id=tool_id, message_queue_implementation=False,
                )
                if not tool_record:
                    log.warning(f"[{session_id}] Python tool record for ID {tool_id} not found.")
                    raise HTTPException(status_code=404, detail=f"Python tool record for ID {tool_id} not found.")

                tool_record = tool_record[0]
                tool_name = tool_record["tool_name"]
                created_by = tool_record.get("created_by", "unknown")
                log.info(f"[{session_id}] Loading Python tool: {tool_name} (id={tool_id})")

                # ========== VERSIONED CODE LOADING ==========
                # Check if we have a version mapping for this tool
                target_version = tool_versions.get(tool_id, 'v1')
                codes = None
                
                # Try to load versioned code from tool_versions_table
                if self.tool_service.tool_version_repo:
                    try:
                        version_record = await self.tool_service.tool_version_repo.get_version(
                            tool_id=tool_id, 
                            version=target_version
                        )
                        if version_record and version_record.get('code_snippet'):
                            codes = version_record['code_snippet']
                            log.info(f"✅ Loaded versioned code for tool '{tool_name}' version '{target_version}'")
                    except Exception as e:
                        log.warning(f"Could not load versioned code for {tool_id} v{target_version}: {e}")
                
                # Fallback to tool_table.code_snippet if versioned code not found
                if not codes:
                    codes = tool_record.get("code_snippet", "")
                    log.info(f"Using fallback code_snippet from tool_table for tool '{tool_name}'")
                
                log.info(f"Loading Python tool: {tool_name} (version: {target_version})")

                if tool_id in SANDBOX_EXEMPT_TOOLS or (
                    tool_name in SANDBOX_EXEMPT_TOOLS and created_by == "system"
                ):
                    exec(codes, sandbox_exempt_local_var)
                    loaded_tool = sandbox_exempt_local_var[tool_name]
                    log.info(f"Tool '{tool_name}' (id={tool_id}) is exempt from sandboxing and loaded into a separate namespace")
                else:
                    exec(codes, local_var)
                    loaded_tool = local_var[tool_name]
                    log.info(f"Tool '{tool_name}' loaded into sandboxed namespace")

                if loaded_tool is None:
                    raise KeyError(f"No callable found in code_snippet for tool '{tool_name}' (id={tool_id})")
                if not callable(loaded_tool):
                    raise TypeError(
                        f"Resolved object for tool '{tool_name}' (id={tool_id}) is not callable: "
                        f"{type(loaded_tool).__name__}"
                    )

                if use_kafka_tool_worker:
                    # Wrap → Kafka dispatch (preserves signature via functools.wraps)
                    loaded_tool = make_message_queue_tool(
                        original_func=loaded_tool,
                        tool_id=tool_id,
                        mq_manager=mq_manager,
                        tool_version=target_version,
                    )
                    log.info(f"[{session_id}] Wrapped Python tool '{tool_name}' version '{target_version}' for Kafka dispatch")

                tool_list.append(loaded_tool)
                log.debug(f"[{session_id}] Python tool '{tool_name}' added to tool_list")

            except HTTPException:
                raise # Re-raise HTTPExceptions directly
            except Exception as e:
                log.error(f"[{session_id}] Error occurred while loading tool {tool_id}: {e}")
                raise HTTPException(status_code=500, detail=f"Error occurred while loading tool {tool_id}: {e}")

        # ========== MCP TOOLS (per-server loading for provenance) ==========
        if mcp_server_ids:
            log.info(f"[{session_id}] Loading MCP tools from {len(mcp_server_ids)} server(s): {mcp_server_ids}")

            try:
                mcp_server_details = await self.mcp_tool_service.get_live_mcp_tools_from_servers(tool_ids=mcp_server_ids)
                mcp_live_tools: List[StructuredTool] = mcp_server_details.get("all_live_tools", [])
                if mcp_live_tools:
                    tool_list.extend(mcp_live_tools)
                    log.info(f"[{session_id}] Loaded {len(mcp_live_tools)} MCP tools (non-Kafka mode)")
            except Exception as e:
                log.error(f"[{session_id}] Error occurred while loading tools from MCP servers {mcp_server_ids}: {e}")
                raise HTTPException(status_code=500, detail=f"Error occurred while loading tools from MCP servers {mcp_server_ids}: {e}")



        # NOTE: Context management prompt is NOT auto-injected.
        # Include run_shell_command instructions directly in your agent's system prompt if needed.
        # See: src/prompts/context_management_prompt.md for reference

        # ========== INJECT TOOL USAGE RULES WHEN FILE_CONTEXT IS ON ==========
        if file_context_management_flag:
            _has_exec = any(hasattr(t, 'name') and t.name == 'execute_python_code' for t in tool_list)
            _has_shell = any(hasattr(t, 'name') and t.name == 'run_shell_command' for t in tool_list)

            _tool_rules = "\n\n## Tool Usage Rules\n"

            if _has_shell:
                _tool_rules += (
                    "- **Reading binary/complex files (PDF, Excel, DOCX, PPTX, images, Parquet):** "
                    "Use `run_shell_command(command=\"readfile /mount_name/file.pdf\")`. "
                    "The `readfile` command extracts readable text from all common formats. "
                    "If you only know the filename, just use `readfile report.pdf` — it auto-discovers across all mounts.\n"
                    "  Example: `run_shell_command(command=\"readfile department_budgets.pdf\")`\n"
                )

            if _has_exec:
                _tool_rules += (
                    "- **Running Python code:** Use `execute_python_code(code=\"...\")` to run Python. "
                    "Results are returned automatically (like a REPL) — no `print()` needed for the last expression.\n"
                )
                if _has_shell:
                    _tool_rules += (
                        "- **File paths in `execute_python_code`:** When writing Python code that reads files "
                        "(pandas, open(), etc.), NEVER use raw virtual paths like `/mount_name/file.csv` or `/mnt/...`. "
                        "Instead, use the built-in `resolve_path()` function:\n"
                        "  ```python\n"
                        "  import pandas as pd\n"
                        "  df = pd.read_csv(resolve_path('/mount_name/inventory.csv'))\n"
                        "  ```\n"
                        "  Also available: `read_file_from_mount('/mount_name/file.pdf')` for text extraction "
                        "and `list_files_in_mount('/mount_name/')` to list directory contents.\n"
                    )

                # Add write-capability prompt when writable mounts are configured
                _wm = locals().get('_writable_mount_names', [])
                if _wm:
                    _wm_str = ", ".join(f"`{m}`" for m in _wm)
                    _tool_rules += (
                        f"- **Writing files:** You CAN write/create files (CSV, Excel, text, etc.) "
                        f"to the following writable folders: {_wm_str}. "
                    )
                    if _has_exec:
                        _tool_rules += (
                            f"In `execute_python_code`, use `resolve_path('<mount>/filename')` to get the real path, "
                            f"then write with `open()`, `pandas .to_csv()/.to_excel()`, etc.\n"
                        )
                    if _has_shell:
                        _tool_rules += (
                            f"  In `run_shell_command`, you can write via `echo content >> <mount>/file.txt`, "
                            f"`mkdir <mount>/subdir`, or `touch <mount>/newfile`.\n"
                        )
                    _tool_rules += (
                        f"  Writing to any other location is blocked.\n"
                    )

            system_prompt += _tool_rules

        # ========== INJECT CURRENT USER INFO INTO SYSTEM PROMPT ==========
        # Get current user info and inject into system prompt for personalization
        try:
            user_email = current_user_email.get(None)
            if user_email:
                # Try to get full user details from auth service
                try:
                    from src.api.dependencies import ServiceProvider
                    auth_service = ServiceProvider.get_auth_service()
                    user_data = await auth_service.user_repo.get_user_by_email(user_email)
                    
                    if user_data:
                        user_info_section = f"""
    ## Current User Information
    You are currently assisting the following user:
    - **Email:** {user_data.get('mail_id', user_email)}
    - **Name:** {user_data.get('user_name', 'Unknown')}
    - **Role:** {user_data.get('role', 'User')}

    Please personalize your responses appropriately for this user.
    #Always greet user by their Name for general calls
    """
                        system_prompt = f"{system_prompt}\n{user_info_section}"
                        log.info(f"[{session_id}] Injected user info into system prompt for: {user_email}")
                    else:
                        # Fallback: just inject email
                        user_info_section = f"""
    ## Current User Information
    You are currently assisting: {user_email}
    """
                        system_prompt = f"{system_prompt}\n{user_info_section}"
                        log.info(f"[{session_id}] Injected user email into system prompt: {user_email}")
                except Exception as e:
                    log.warning(f"[{session_id}] Could not fetch full user details, using email only: {e}")
                    user_info_section = f"""
    ## Current User Information
    You are currently assisting: {user_email}
    """
                    system_prompt = f"{system_prompt}\n{user_info_section}"
        except Exception as e:
            log.warning(f"[{session_id}] Could not inject user info into system prompt: {e}")

        # ========== BUILD REACT AGENT ==========
        # Inject extra tools if provided
        if extra_tools:
            existing_names = {t.name for t in tool_list if hasattr(t, 'name')}
            for et in extra_tools:
                if hasattr(et, 'name') and et.name not in existing_names:
                    tool_list.append(et)
            log.info(f"[EXTRA_TOOLS] Added {len(extra_tools)} extra tools: {[t.name for t in extra_tools if hasattr(t, 'name')]}")

        interrupt_before = ["tools"] if interrupt_tool and tool_list else None
        log.info(f"[{session_id}] [AGENT_CREATE] Creating react agent with {len(tool_list)} tools: {[t.name if hasattr(t, 'name') else str(t)[:30] for t in tool_list]}")
        
        # Add detailed DB tools instruction if database tools are available
        # NOTE: Schema and sample data are now PRE-LOADED from cache into the prompt
        # Only database_query_tool is available as a tool
        db_connection_names = getattr(self, '_db_connection_names', None)
        if db_connection_names:
            # The cached schema and sample data are already injected via inject_database_tools_into_config
            # This is a fallback instruction in case caching wasn't set up
            db_tools_instruction = f"""

## DATABASE QUERY CAPABILITY

You have access to query the following database connections: {db_connection_names}

### Available Tool:
- **database_query_tool(connection_name, query, limit=100)** - Execute SELECT queries

### HOW TO USE:
1. **Review the PRE-LOADED DATABASE SCHEMA above** - it contains all tables, columns, and data types
2. **Review the PRE-LOADED SAMPLE DATA** - it shows example values from key tables
3. **Write your SELECT query** using the exact table and column names from the schema
4. **Execute**: `database_query_tool(connection_name="{db_connection_names[0]}", query="SELECT ...")`

### IMPORTANT:
- The schema is ALREADY LOADED above - DO NOT say you need to discover it
- Only operations NOT in the connection's blocked commands list are allowed
- Use the sample data to understand data formats and values
- ALWAYS execute the tool to get real data - never guess or hallucinate
"""
            system_prompt = f"{system_prompt}\n{db_tools_instruction}"
        
        # Debug: Log final tool list before creating agent
        log.info(f"Final tool_list before create_react_agent: {len(tool_list)} tools")
        
        # FIX: Prepend clear tool instructions when database tools are available
        # This ensures the LLM knows the correct workflow: read schema -> execute query
        if db_connection_names and tool_list:
            connections_list = ", ".join(db_connection_names)
            db_tool_header = f"""## DATABASE QUERY WORKFLOW

You have access to query these databases: {connections_list}

### AVAILABLE TOOLS:
1. **run_shell_command** - Powerful shell with 18 commands + pipe support for reading files, searching, and more
   - `stat /file` — ALWAYS check file size before reading
   - `cat [-n] /databases/{{connection_name}}/schema.md` — Read schema (-n for line numbers)
   - `sed -n '10,20p' /file` — Read specific line range (MUST USE for large files instead of cat)
   - `grep -C 3 \"column_name\" /databases/{{connection_name}}/schema.md` — Find column with context (ALWAYS use -C for context)
   - `grep -e \"term1\" -e \"term2\" /file` — Multi-pattern search in one call
   - `diff /file1 /file2` — Compare schema files
   - `tree --size /path` — See directory structure with file sizes (use instead of ls)
   - Pipes: `grep \"table\" schema.md | head -5` — Filter results (ALWAYS pipe through head/tail for large results)
2. **database_query_tool** - Execute SQL SELECT queries

### REQUIRED WORKFLOW (Follow these steps IN ORDER):

**STEP 1: Check schema file size first**
```
run_shell_command(command="stat /databases/{db_connection_names[0]}/schema.md")
```

**STEP 2: Read the schema file (use sed for large schemas)**
```
run_shell_command(command="cat /databases/{db_connection_names[0]}/schema.md")
```
If stat showed >50 lines, use `sed -n '1,50p'` to read in chunks instead.

**STEP 3: (Optional) Search for specific tables/columns**
```
run_shell_command(command="grep -C 3 \\"table_name\\" /databases/{db_connection_names[0]}/schema.md")
```

**STEP 4: Execute your query**
```
database_query_tool(connection_name="{db_connection_names[0]}", query="SELECT ... FROM ...")
```

**STEP 5: If query fails, read samples.md and retry**
```
run_shell_command(command="cat /databases/{db_connection_names[0]}/samples.md")
```
→ Review sample data, rewrite query with corrected syntax

### IMPORTANT RULES:
- ALWAYS run `stat` before reading any file to check its size
- ALWAYS use `grep -C 3` (with context) instead of plain grep
- ALWAYS pipe large results through `head` or `tail`
- Use `sed -n '10,20p'` for targeted reads of large files  
- Use exact table and column names from the schema
- NEVER say you don't have tools - you have run_shell_command and database_query_tool

---

"""
            system_prompt = db_tool_header + system_prompt
            log.info(f"[DB_TOOLS] Prepended database workflow instructions to system prompt")
        
        try:
            executor_agent = create_react_agent(
                llm,
                tools=tool_list,
                checkpointer=checkpointer,
                interrupt_before=interrupt_before,
                prompt=system_prompt
            )
            log.info(f"[{session_id}] React agent created successfully")
            # Return executor_agent, tool_list, and memory instance (shell)
            return executor_agent, tool_list, agent_shell

        except Exception as e:
            log.error(f"[{session_id}] Error occurred while creating agent executor: {e}")
            raise HTTPException(status_code=500, detail=f"Error occurred while creating agent executor: {e}")

    @staticmethod
    async def _get_chains(llm: Any, system_prompt: str, *, get_json_chain: bool = True, get_str_chain: bool = True):
        """
        Helper method to create LangGraph chains for the agent based on the system prompt.
        """
        try:
            system_prompt_template = ChatPromptTemplate.from_messages([
                    ("system", system_prompt),
                    ("placeholder", "{messages}")
                ]
            )
            json_chain = str_chain = None

            if get_json_chain:
                json_chain = system_prompt_template | llm | JsonOutputParser()

            if get_str_chain:
                str_chain = system_prompt_template | llm | StrOutputParser()

            return json_chain, str_chain
        except Exception as e:
            log.error(f"Error occurred while creating chains: {e}")
            raise HTTPException(status_code=500, detail=f"Error occurred while creating chains: {e}")

    async def _get_agent_config(self, agentic_application_id: str, department_name: str = None, user_role: str = None) -> dict:
        """
        Retrieves the configuration for an agent and its associated tools.

        When department_name is provided and user_role is not SuperAdmin, the
        lookup includes department-based access control (same dept, public, or
        shared) — no extra DB call needed.

        Args:
            agentic_application_id (str): Agentic application ID.
            department_name (str, optional): Requesting user's department for access control.
            user_role (str, optional): Requesting user's role (SuperAdmin bypasses dept filter).

        Returns:
            dict: A dictionary containing the system prompt and tool information.
        """
        # Retrieve agent details from the database with access control
        log.info(f"Retrieving agent details for agent_id={agentic_application_id}")
        if department_name and user_role != "SuperAdmin":
            # Use service-level get_agent which applies: dept match OR is_public OR is_shared
            result = await self.agent_service.get_agent(
                agentic_application_id=agentic_application_id,
                department_name=department_name
            )
        else:
            # SuperAdmin or no department context — unrestricted lookup
            result = await self.agent_service.agent_repo.get_agent_record(agentic_application_id=agentic_application_id)
        log.info(f"Agent details retrieved successfully for agent_id={agentic_application_id}")
        if not result:
            log.error(f"Agentic Application ID {agentic_application_id} not found.")
            raise HTTPException(status_code=404, detail=f"Agentic Application ID {agentic_application_id} not found.")
        result = result[0]

        # Fetch tool-agent mappings to get version info
        tools_with_versions = {}
        try:
            mappings = await self.tool_service.tool_agent_mapping_repo.get_tool_agent_mappings_record(
                agentic_application_id=agentic_application_id
            )
            for mapping in mappings:
                tool_id = mapping.get('tool_id')
                tool_version = mapping.get('tool_version', 'v1')
                if tool_id:
                    tools_with_versions[tool_id] = tool_version
            log.info(f"Tool versions for agent {agentic_application_id}: {tools_with_versions}")
        except Exception as e:
            log.warning(f"Could not fetch tool versions: {e}. Defaulting to v1 for all tools.")

        # Handle both raw DB records (str) and enriched records (already parsed)
        system_prompt = result["system_prompt"]
        if isinstance(system_prompt, str):
            system_prompt = json.loads(system_prompt)
        tools_info = result["tools_id"]
        if isinstance(tools_info, str):
            tools_info = json.loads(tools_info)

        agent_config = {
            "AGENT_ID": result["agentic_application_id"],
            "AGENT_NAME": result["agentic_application_name"],
            "SYSTEM_PROMPT": system_prompt,
            "TOOLS_INFO": tools_info,
            "TOOLS_WITH_VERSIONS": tools_with_versions,  # Map of tool_id -> version
            "AGENT_DESCRIPTION": result["agentic_application_description"],
            "AGENT_TYPE": result['agentic_application_type'],
            "OWNER_DEPARTMENT": result.get("department_name", "General"),
            "GUARDRAIL_TYPE": result.get("guardrail_type", "none"),
        }
        log.info(f"Agent tools configuration retrieved for Agentic Application ID: {agentic_application_id}")
        return agent_config

    # Abstract Methods

    @abstractmethod
    async def _build_agent_and_chains(self, llm, agent_config, checkpointer, tool_interrupt_flag: bool = False, use_kafka_tool_worker: bool = False, session_id: str = None, agent_id: str = None, context_flag: bool = True, file_context_management_flag: bool = False) -> Any:
        """
        Abstract method to build and compile the LangGraph chains for a specific agent type.
        
        Args:
            session_id: Session ID to bind to message_queue tools for filtering Kafka results.
            agent_id: Agent/application ID for shell workspace (required if file_context_management_flag=True).
            context_flag: If False, no memory tools will be added.
            file_context_management_flag: If True (and context_flag=True), use file-based context with tool.
        """
        pass

    @abstractmethod
    async def _build_workflow(self, chains: dict, flags: Dict[str, bool] = {}, get_dummy: bool = False) -> StateGraph:
        """
        Abstract method to build the LangGraph workflow for a specific agent type.
        
        Args:
            chains: Dictionary of LLM chains and agents.
            flags: Dictionary of feature flags controlling workflow topology.
            get_dummy: If True, bypass chain validation (used for aupdate_state topology matching).
        """
        pass

    # Common Inference Method

    # --- Fields allowed in the final API response sent to the frontend ---
    _RESPONSE_ALLOWED_KEYS = frozenset({
        "response", "executor_messages", "__interrupt__", "interrupt_metadata",
        "current_query_status", "plan", "error", "error_type", "details",
        "parts", "evaluation_score", "evaluation_feedback",
        "validation_score", "validation_feedback",
    })

    @staticmethod
    def _filter_response_for_frontend(response: dict) -> dict:
        """Strip internal graph state fields from the response before sending to frontend.
        
        Only retains fields that the UI actually uses, removing internal
        state like ongoing_conversation, past_conversation_summary, session_id,
        model_name, step_idx, epoch, etc.
        """
        if not isinstance(response, dict):
            return response
        return {k: v for k, v in response.items() if k in BaseAgentInference._RESPONSE_ALLOWED_KEYS}

    @staticmethod
    async def _enrich_interrupted_response(
        app: "CompiledStateGraph",
        graph_config: dict,
        agent_resp: dict,
        session_id: str,
    ) -> dict:
        """Enrich an interrupted graph response with pending tool-call/plan info.

        When a skill agent node calls ``interrupt()`` before returning, the
        checkpointer state only contains the messages accumulated *before*
        that node started.  This helper reads the LangGraph task state to
        recover the pending tool call details and injects them into
        ``executor_messages`` so that ``segregate_conversation_...`` can
        produce the correct ``tools_used`` and ``final_response`` fields.
        
        Also handles plan verification interrupts where the interrupt value
        is a plain string like "Is this plan acceptable?" rather than a JSON
        tool payload.
        """
        import uuid as _uuid

        # --- PLAN VERIFICATION INTERRUPT DETECTION ---
        # Plan interrupts use plain-text values like "Is this plan acceptable?"
        # They are NOT tool/skill interrupts and need different handling.
        _PLAN_INTERRUPT_MARKERS = (
            "is this plan acceptable",
            "plan acceptable",
            "approve the plan",
            "review the plan",
        )

        # --- PLAN FEEDBACK (REPLANNING) INTERRUPT DETECTION ---
        # After user rejects the plan, feedback_collector calls interrupt()
        # to collect the reason/feedback before replanning.
        _PLAN_FEEDBACK_MARKERS = (
            "what went wrong",
            "provide feedback",
            "feedback to fix the plan",
            "feedback for the plan",
        )

        _is_plan_interrupt = False
        _is_plan_feedback_interrupt = False
        _interrupts = agent_resp.get("__interrupt__", [])
        for _intr in _interrupts:
            _val = _intr.get("value") if isinstance(_intr, dict) else getattr(_intr, "value", None)
            if isinstance(_val, str):
                _val_lower = _val.lower()
                if any(marker in _val_lower for marker in _PLAN_INTERRUPT_MARKERS):
                    _is_plan_interrupt = True
                    break
                if any(marker in _val_lower for marker in _PLAN_FEEDBACK_MARKERS):
                    _is_plan_feedback_interrupt = True
                    break

        # Also detect via state fields
        if agent_resp.get("current_query_status") == "plan" or agent_resp.get("_interrupt_type") == "plan_verification":
            _is_plan_interrupt = True
        if agent_resp.get("current_query_status") == "feedback" or agent_resp.get("_interrupt_type") == "plan_feedback":
            _is_plan_feedback_interrupt = True

        if _is_plan_interrupt:
            log.info(f"[{session_id}] Plan verification interrupt detected, building clean response")
            _plan = agent_resp.get("plan", [])
            _query_text = agent_resp.get("query", "")

            # Build minimal executor_messages for plan verification
            _hm = HumanMessage(content=_query_text, id=str(_uuid.uuid4()))
            _hm.role = "user_query"  # type: ignore[attr-defined]
            agent_resp["executor_messages"] = [_hm]
            agent_resp["response"] = ""
            agent_resp["current_query_status"] = "plan"
            agent_resp["interrupt_metadata"] = {
                "interrupt_type": "plan_verification",
                "plan": _plan,
                "actions": ["approve", "reject"],
            }
            log.info(f"[{session_id}] Enriched plan verification response: plan_steps={len(_plan)}")
            return agent_resp

        if _is_plan_feedback_interrupt:
            log.info(f"[{session_id}] Plan feedback (replanning) interrupt detected, building clean response")
            _plan = agent_resp.get("plan", [])
            _query_text = agent_resp.get("query", "")

            # Build minimal executor_messages for feedback collection
            _hm = HumanMessage(content=_query_text, id=str(_uuid.uuid4()))
            _hm.role = "user_query"  # type: ignore[attr-defined]
            agent_resp["executor_messages"] = [_hm]
            agent_resp["response"] = ""
            agent_resp["current_query_status"] = "feedback"
            agent_resp["interrupt_metadata"] = {
                "interrupt_type": "plan_feedback",
                "plan": _plan,
                "actions": ["submit_feedback"],
            }
            log.info(f"[{session_id}] Enriched plan feedback response: plan_steps={len(_plan)}")
            return agent_resp

        # --- TOOL/SKILL INTERRUPT HANDLING (existing logic) ---
        _pending_tool_name = None
        _pending_tool_args: dict = {}
        _pending_tool_call_id = None

        # 1. Try to extract tool info from the interrupt value itself
        #    (skill agent embeds a JSON payload with tool_name/tool_args).
        try:
            import json as _json
            for _intr in _interrupts:
                _val = _intr.get("value") if isinstance(_intr, dict) else getattr(_intr, "value", None)
                if isinstance(_val, str) and _val.startswith("{"):
                    _parsed = _json.loads(_val)
                    if "tool_name" in _parsed:
                        _pending_tool_name = _parsed["tool_name"]
                        _pending_tool_args = _parsed.get("tool_args", {})
                        _pending_tool_call_id = _parsed.get("tool_call_id", "")
                        break
        except Exception as _parse_err:
            log.debug(f"[{session_id}] Could not parse interrupt payload: {_parse_err}")

        # 2. Fallback: try to read from LangGraph task state
        if not _pending_tool_name:
            try:
                _state_snapshot = await app.aget_state(graph_config)
                if _state_snapshot and hasattr(_state_snapshot, 'tasks') and _state_snapshot.tasks:
                    for _task in _state_snapshot.tasks:
                        if hasattr(_task, 'state') and isinstance(_task.state, dict):
                            _ts = _task.state
                            if 'tool_name' in _ts:
                                _pending_tool_name = _ts['tool_name']
                                _pending_tool_args = _ts.get('tool_args', {})
                                _pending_tool_call_id = _ts.get('tool_call_id', '')
            except Exception as _e:
                log.debug(f"[{session_id}] Could not extract tool info from task state: {_e}")

        # 3. Fallback: scan existing executor_messages for AIMessage with tool_calls
        if not _pending_tool_name:
            for _msg in agent_resp.get("executor_messages", []):
                if hasattr(_msg, 'tool_calls') and _msg.tool_calls:
                    for _tc in _msg.tool_calls:
                        _pending_tool_name = _tc.get("name")
                        _pending_tool_args = _tc.get("args", {})
                        _pending_tool_call_id = _tc.get("id")

        _interrupt_msg = "⏸️ Tool execution requires approval. Please approve or reject to proceed."
        if _pending_tool_name:
            _args_preview = (
                ", ".join(f"{k}={v}" for k, v in _pending_tool_args.items())
                if isinstance(_pending_tool_args, dict) else str(_pending_tool_args)
            )
            _interrupt_msg = (
                f"⏸️ Tool **{_pending_tool_name}** requires approval before execution.\n\n"
                f"**Arguments:** {_args_preview}\n\n"
                f"Please approve or provide feedback to proceed."
            )

        # Match react agent format: response and final_response are empty
        # on tool interrupt. The approval prompt is delivered via streaming chunks only.
        agent_resp["response"] = ""
        _query_text = agent_resp.get("query", "")

        # Build executor_messages: HumanMessage(user_query) + AIMessage(tool_calls)
        # NO final AIMessage with interrupt text — keeps final_response="" after segregation.
        _exec_msgs: list = []
        _hm = HumanMessage(content=_query_text, id=str(_uuid.uuid4()))
        _hm.role = "user_query"  # type: ignore[attr-defined]
        _exec_msgs.append(_hm)

        if _pending_tool_name:
            import json as _json
            _tc_id = _pending_tool_call_id or f"tc_{_uuid.uuid4().hex[:8]}"
            _ai_with_tc = AIMessage(
                content="",
                tool_calls=[{"name": _pending_tool_name, "args": _pending_tool_args, "id": _tc_id}],
                additional_kwargs={
                    "tool_calls": [{
                        "id": _tc_id,
                        "function": {
                            "name": _pending_tool_name,
                            "arguments": (
                                _json.dumps(_pending_tool_args)
                                if isinstance(_pending_tool_args, dict)
                                else str(_pending_tool_args)
                            ),
                        },
                        "type": "function",
                    }]
                },
            )
            _exec_msgs.append(_ai_with_tc)

        agent_resp["executor_messages"] = _exec_msgs

        # --- Build interrupt_metadata for the UI ---
        _interrupt_type = agent_resp.get("_interrupt_type", "tool_interrupt")
        _interrupt_reason = agent_resp.get("_interrupt_reason", "")

        _actions = ["approve", "reject"]
        if _interrupt_type == "tool_interrupt":
            _actions = ["approve", "modify", "reject"]
        elif _interrupt_type == "skill_interrupt":
            _actions = ["approve", "modify", "reject"]
        # hook_approval → approve/reject only

        if _interrupt_type == "skill_interrupt":
            # Extract skill-specific info from interrupt payload
            _skill_name = ""
            _matched_skills = []
            _available_skills = []
            _routing_method = ""
            _routing_confidence = ""
            try:
                import json as _json2
                _interrupts = agent_resp.get("__interrupt__", [])
                for _intr in _interrupts:
                    _val = _intr.get("value") if isinstance(_intr, dict) else getattr(_intr, "value", None)
                    if isinstance(_val, str) and _val.startswith("{"):
                        _parsed = _json2.loads(_val)
                        if "selected_skill" in _parsed:
                            _skill_name = _parsed.get("selected_skill", "")
                            _matched_skills = _parsed.get("matched_skills", [])
                            _available_skills = _parsed.get("available_skills", [])
                            _routing_method = _parsed.get("routing_method", "")
                            _routing_confidence = _parsed.get("routing_confidence", "")
                            break
            except Exception as _e:
                log.debug(f"[{session_id}] Could not parse skill interrupt payload: {_e}")

            _interrupt_msg = (
                f"⏸️ Skill **{_skill_name}** was selected via **{_routing_method}** routing"
                f" (confidence: {_routing_confidence}).\n\n"
                f"Please approve, modify (pick a different skill), or reject."
            )

            agent_resp["interrupt_metadata"] = {
                "interrupt_type": _interrupt_type,
                "matched_skills": _matched_skills,
                "available_skills": _available_skills,
                "routing_method": _routing_method,
                "routing_confidence": _routing_confidence,
                "reason": _interrupt_reason or _interrupt_msg,
                "actions": _actions,
            }
        else:
            agent_resp["interrupt_metadata"] = {
                "interrupt_type": _interrupt_type,
                "tool_name": _pending_tool_name or "",
                "tool_args": _pending_tool_args or {},
                "tool_call_id": _pending_tool_call_id or "",
                "reason": _interrupt_reason or _interrupt_msg,
                "actions": _actions,
            }

        log.info(f"[{session_id}] Enriched interrupted response: type={_interrupt_type}, tool={_pending_tool_name}")
        return agent_resp

    @staticmethod
    async def _astream(
        app: CompiledStateGraph,
        invocation_input: dict,
        config: dict,
        *,
        is_plan_approved: Literal["yes", "no", None] = None,
        plan_feedback: str = None,
        tool_feedback: str = None,
        skill_feedback: str = None,
        session_id: str = None,
        message_queue: bool = False,
        tool_result: str = None
        ):
        try:
            async with handle_llm_errors(session_id):
                # Determine which stream to use based on conditions
                if not is_plan_approved and not tool_feedback and not skill_feedback:
                    temp = app.astream(invocation_input, config=config, stream_mode="custom")
                    async for state in temp:
                        yield state
                elif is_plan_approved == "yes":
                    async for state in app.astream(Command(resume="yes"), config=config,stream_mode="custom"):
                        yield state
                elif is_plan_approved == "no" and not plan_feedback:
                    async for state in app.astream(Command(resume="no"), config=config,stream_mode="custom"):
                        yield state
                elif message_queue and tool_result:
                    async for state in app.astream(Command(resume=tool_result), config=config,stream_mode="custom"):
                        yield state        
                elif is_plan_approved == "no" and plan_feedback is not None:
                    async for state in app.astream(Command(resume=plan_feedback), config=config,stream_mode="custom"):
                        yield state
                elif skill_feedback is not None:
                    async for state in app.astream(Command(resume=skill_feedback), config=config,stream_mode="custom"):
                        yield state
                elif tool_feedback is not None:
                    async for state in app.astream(Command(resume=tool_feedback), config=config,stream_mode="custom"):
                        yield state
                else:
                    yield {"error": "Invalid parameters provided for astream."}
        
        except GraphRecursionError as e:
            # LangGraph hit recursion limit during streaming; return controlled error
            log.error(f"[{session_id}] GraphRecursionError during streaming: {e}")
            yield {
                "error": "Agent hit recursion limit and was stopped.",
                "error_type": "GRAPH_RECURSION_LIMIT",
                "details": str(e),
            }
        
        except LLMInfrastructureError as e:
            log.error(f"[{session_id}] LLMInfrastructureError during streaming: {e}")
            raise # re-raising the error
        
        except Exception as e:
            log.error(f"[{session_id}] Unexpected error during streaming: {e}")
            log_guardrail_or_exception(f"[{session_id}] Error during streaming: {e}", e)
            raise

    @staticmethod
    async def _ainvoke(
                    app: CompiledStateGraph,
                    invocation_input: dict,
                    config: dict,
                    *,
                    is_plan_approved: Literal["yes", "no", None] = None,
                    plan_feedback: str = None,
                    tool_feedback: str = None,
                    skill_feedback: str = None,
                    session_id: str = None
                ):
        """
        Asynchronously invokes the agent application with the provided input and configuration.
        """
        async with handle_llm_errors(session_id):
            if not is_plan_approved and not tool_feedback and not skill_feedback:
                return await app.ainvoke(invocation_input, config=config)
            if is_plan_approved == 'yes':
                return await app.ainvoke(Command(resume='yes'), config=config)
            if is_plan_approved == 'no' and not plan_feedback:
                return await app.ainvoke(Command(resume='no'), config=config)
            if is_plan_approved == 'no' and plan_feedback is not None:
                return await app.ainvoke(Command(resume=plan_feedback), config=config)
            if skill_feedback is not None:
                return await app.ainvoke(Command(resume=skill_feedback), config=config)
            if tool_feedback is not None:
                return await app.ainvoke(Command(resume=tool_feedback), config=config)
        return {"error": "Invalid parameters provided for ainvoke."}

    async def _generate_response(
                                self,
                                query: str,
                                agentic_application_id: str,
                                session_id: str,
                                model_name: str,
                                agent_config: dict,
                                project_name: str,
                                reset_conversation: bool = False,
                                *,
                                plan_verifier_flag: bool = False,
                                is_plan_approved: Literal["yes", "no", None] = None,
                                plan_feedback: str = None,
                                response_formatting_flag:bool = True,
                                tool_interrupt_flag: bool = False,
                                tool_feedback: str = None,
                                skill_verifier_flag: bool = False,
                                skill_feedback: str = None,
                                context_flag: bool = True,
                                file_context_management_flag: bool = False,
                                temperature: float = 0.0,
                                enable_streaming_flag: bool = False,
                                evaluation_flag: bool = False,
                                validator_flag: bool = False,
                                mentioned_agent_id: str = None,
                                interrupt_items: List[str] = None,
                                use_kafka_tool_worker: bool = False,
                                inference_config: AdminConfigLimits = AdminConfigLimits(),
                                department_name: str = None,
                                execution_mode: str = None
                            ):
        if not plan_verifier_flag:
            is_plan_approved = plan_feedback = None

        log.info(f"[{session_id}] _generate_response started | agent_id={agentic_application_id}, model={model_name}, streaming={enable_streaming_flag}, eval_flag={evaluation_flag}, validator_flag={validator_flag}, kafka={use_kafka_tool_worker}")
        llm = await self.model_service.get_llm_model(model_name=model_name, temperature=temperature)
        agent_resp = {}

        log.debug(f"[{session_id}] Building agent and chains")
        async with await self.chat_service.get_checkpointer_context_manager() as checkpointer:
            chains = await self._build_agent_and_chains(
                llm, 
                agent_config, 
                checkpointer, 
                tool_interrupt_flag=tool_interrupt_flag,
                use_kafka_tool_worker=use_kafka_tool_worker,
                session_id=session_id,
                agent_id=agentic_application_id,
                context_flag=context_flag,
                file_context_management_flag=file_context_management_flag
            )
            if reset_conversation:
                try:
                    await self.chat_service.delete_session(agentic_application_id, session_id)
                    log.info(f"[{session_id}] Conversation history reset for agent_id={agentic_application_id}")
                except Exception as e:
                    log.error(f"[{session_id}] Error occurred while resetting conversation: {e}")

            flags_and_config = {
                "plan_verifier_flag": plan_verifier_flag,
                "tool_interrupt_flag": tool_interrupt_flag,
                "skill_verifier_flag": skill_verifier_flag,
                "response_formatting_flag": response_formatting_flag,
                "context_flag": context_flag,
                "file_context_management_flag": file_context_management_flag,
                "evaluation_flag": evaluation_flag,
                "validator_flag": validator_flag,
                "message_queue": False,
                "inference_config": inference_config
            }
            log.debug(f"[{session_id}] Building workflow")
            workflow = await self._build_workflow(chains, flags_and_config)
            log.debug(f"[{session_id}] Workflow built successfully")
            app = workflow.compile(checkpointer=checkpointer)
            log.debug(f"[{session_id}] Workflow compiled successfully")
            # Configuration for the workflow
            thread_id = await self.chat_service._get_thread_id(agentic_application_id, session_id)
            graph_config = await self.chat_service._get_thread_config(thread_id)

            log.info(f"[{session_id}] Invoking executor agent for query: {query}\n with Session ID: {session_id} and Agent Id: {agentic_application_id}")
            
            # Use the context-aware traced context manager to prevent trace mixing
            log_trace_context(f"before_agent_invocation_session_{session_id}")

            async with traced_project_context(project_name):
                log_trace_context(f"inside_traced_context_session_{session_id}")
                try:
                    invocation_input = {
                        'query': query,
                        'agentic_application_id': agentic_application_id,
                        'session_id': session_id,
                        'reset_conversation': reset_conversation,
                        'model_name': model_name,
                        'is_tool_interrupted': False,
                        'is_skill_interrupted': False,
                        'evaluation_flag': evaluation_flag,
                        "response_formatting_flag": response_formatting_flag,
                        "context_flag": context_flag,
                        "file_context_management_flag": file_context_management_flag,
                        "mentioned_agent_id": mentioned_agent_id,
                        "interrupt_items": interrupt_items,
                        "department_name": department_name,
                        "execution_mode": execution_mode
                    }
                    if enable_streaming_flag:
                        streammer = self._astream(
                            app,
                            invocation_input,
                            config=graph_config,
                            is_plan_approved=is_plan_approved,
                            plan_feedback=plan_feedback,
                            tool_feedback=tool_feedback,
                            skill_feedback=skill_feedback,
                            session_id=session_id
                        )
                        async for step in streammer:
                            yield step
                        agent_resp = await checkpointer.aget(graph_config)
                        if agent_resp:
                            agent_resp = agent_resp.get("channel_values", {})
                        else:
                            agent_resp = {}
                        if not agent_resp:
                            log.warning(f"[{session_id}] Unable to retrieve response from checkpointer")

                        # checkpointer.aget() doesn't include __interrupt__ metadata.
                        # Use aget_state() to detect pending interrupts so that
                        # the enrichment path below can fire for streaming too.
                        if not agent_resp.get("__interrupt__"):
                            try:
                                _snapshot = await app.aget_state(graph_config)
                                if _snapshot and hasattr(_snapshot, 'tasks') and _snapshot.tasks:
                                    _intrs = []
                                    for _t in _snapshot.tasks:
                                        if hasattr(_t, 'interrupts') and _t.interrupts:
                                            for _i in _t.interrupts:
                                                _intrs.append({
                                                    "value": getattr(_i, 'value', str(_i)),
                                                    "resumable": getattr(_i, 'resumable', True),
                                                })
                                    if _intrs:
                                        agent_resp["__interrupt__"] = _intrs
                                        log.info(f"[{session_id}] Detected {len(_intrs)} pending interrupt(s) via state snapshot")
                            except Exception as _e:
                                log.debug(f"[{session_id}] Could not check for interrupts via aget_state: {_e}")

                        # Enrich interrupted responses with pending tool call info
                        if agent_resp.get("__interrupt__") and not agent_resp.get("response"):
                            agent_resp = await self._enrich_interrupted_response(app, graph_config, agent_resp, session_id)

                        yield agent_resp


                        log.info(f"[{session_id}] Agent streaming invocation completed for agent_id={agentic_application_id}")
                    else:
                        agent_resp = await self._ainvoke(
                            app,
                            invocation_input,
                            config=graph_config,
                            is_plan_approved=is_plan_approved,
                            plan_feedback=plan_feedback,
                            tool_feedback=tool_feedback,
                            skill_feedback=skill_feedback,
                            session_id=session_id
                        )

                        # Enrich interrupted responses with pending tool call info
                        if isinstance(agent_resp, dict) and agent_resp.get("__interrupt__") and not agent_resp.get("response"):
                            agent_resp = await self._enrich_interrupted_response(app, graph_config, agent_resp, session_id)

                        log.info(f"Agent invoked successfully for query: {query} with session ID: {session_id}")
                        yield agent_resp

                except LLMInfrastructureError as e:
                    raise # Already handled, propagete up

                except GraphRecursionError as e:
                    # LangGraph hit recursion limit; return controlled error
                    log.error(f"[{session_id}] GraphRecursionError during inference for agent_id={agentic_application_id}: {e}")
                    agent_resp = {
                        "error": "Agent hit recursion limit and was stopped.",
                        "error_type": "GRAPH_RECURSION_LIMIT",
                        "details": str(e),
                    }
                    yield agent_resp

                except Exception as e:
                    log_guardrail_or_exception(f"[{session_id}] Error during agent inference: {e}", e)
                    raise
                
                finally:
                    log_trace_context(f"after_agent_invocation_session_{session_id}")


    async def run(self,
                  inference_request: AgentInferenceRequest,
                  *,
                  agent_config: Optional[Union[dict, None]] = None,
                  insert_into_eval_flag: bool = True,
                  role: str = None,
                  department_name: str = None,
                  use_kafka_tool_worker: bool = False
                ) -> Any:
        """
        Runs the Agent inference workflow.

        Args:
            request (AgentInferenceRequest): The request object containing all necessary parameters.
        """
        start_time = time.monotonic()
        agentic_application_id = inference_request.agentic_application_id
        session_id = inference_request.session_id
        log.info(f"[{session_id}] BaseAgentInference.run started | agent_id={agentic_application_id}, eval_flag={insert_into_eval_flag}, role={role}, department={department_name}, kafka={use_kafka_tool_worker}")
        if not agent_config:
            try:
                agent_config = await self._get_agent_config(agentic_application_id)
            except Exception as e:
                log.error(f"[{session_id}] Error occurred while retrieving agent configuration for agent_id={agentic_application_id}: {e}")
                raise HTTPException(status_code=500, detail=f"Error occurred while retrieving agent configuration: {str(e)}")

        from src.utils.guardrail_helpers import guardrail_type_ctx as _guardrail_type_ctx
        agent_guardrail_type = agent_config.get("GUARDRAIL_TYPE", "none")
        _guardrail_type_ctx.set(agent_guardrail_type)
        log.info(f"[{session_id}] Agent guardrail_type='{agent_guardrail_type}'")

        try:
            query = inference_request.query or ""
            
            if inference_request.uploaded_files:
                base_dir = "user_uploads"
                files_info = "\n".join([f"- {base_dir}/{f}" for f in inference_request.uploaded_files])
                query = f"{query}\n\n[Attached files:\n{files_info}]" if query else f"[Attached files:\n{files_info}]"
            
            session_id = inference_request.session_id
            model_name = inference_request.model_name
            reset_conversation = inference_request.reset_conversation
            tool_interrupt_flag = inference_request.tool_verifier_flag
            tool_feedback = inference_request.tool_feedback
            skill_verifier_flag = getattr(inference_request, 'skill_verifier_flag', False)
            skill_feedback = getattr(inference_request, 'skill_feedback', None)
            plan_verifier_flag = inference_request.plan_verifier_flag
            response_formatting_flag = inference_request.response_formatting_flag
            context_flag = inference_request.context_flag
            file_context_management_flag = inference_request.file_context_management_flag
            is_plan_approved = inference_request.is_plan_approved
            plan_feedback = inference_request.plan_feedback
            evaluation_flag = inference_request.evaluation_flag
            validator_flag = inference_request.validator_flag
            temperature=inference_request.temperature
            enable_streaming_flag = inference_request.enable_streaming_flag
            mentioned_agent_id = inference_request.mentioned_agentic_application_id
            interrupt_items = inference_request.interrupt_items
            message_queue = inference_request.message_queue
            execution_mode = getattr(inference_request, 'execution_mode', None)

            inference_config = await self.admin_config_service.get_limits()

            match = re.search(r'([a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+)', session_id)
            user_name = match.group(0) if match else "guest"
            agent_name = agent_config["AGENT_NAME"]
            project_name=agent_name+'_'+user_name

            # Register Phoenix project (only once per unique project name)
            ensure_project_registered(
                project_name=project_name,
                auto_instrument=True,
                set_global_tracer_provider=False,
                batch=True
            )

            update_session_context(
                user_id=user_name,          # email extracted from session_id — propagates to all LangGraph nodes
                agent_type=agent_config["AGENT_TYPE"],
                agent_name=agent_name
            )
            
            # Set explicit call_category for agent inference categorization
            from telemetry_wrapper import set_context
            set_context(agent_id=agentic_application_id, agent_type=agent_config["AGENT_TYPE"], call_category="agent_inference")

            # Fetch knowledgebase names from database if agent has KB mappings
            knowledgebase_names = None
            if agent_config["AGENT_TYPE"] in ["react_agent", "react_critic_agent"]:
                try:
                    # Get KB mappings for this agent from database
                    from src.api.app_container import app_container
                    if app_container.knowledgebase_service:
                        kb_records = await app_container.knowledgebase_service.agent_kb_mapping_repo.get_knowledgebases_for_agent(
                            agentic_application_id=agentic_application_id
                        )
                        
                        if kb_records:
                            # Extract KB names as a list
                            knowledgebase_names = [kb.get("knowledgebase_name") for kb in kb_records]
                            agent_config['KNOWLEDGEBASE_NAMES'] = knowledgebase_names
                            
                            log.info(f"Knowledge Bases configured from database: {knowledgebase_names}")
                            
                            # Enhanced system prompt to guide the agent on using the knowledge base tool
                            kb_instruction = f"""

IMPORTANT - Knowledge Base Retrieval Tool Available:
You have access to a 'knowledgebase_retriever' tool that can search knowledge bases for relevant information.

Knowledge Base Names: {knowledgebase_names}

CRITICAL INSTRUCTIONS:
- For ANY query, use the knowledgebase_retriever tool FIRST to search the knowledge base.
- If the retrieved information is irrelevant or doesn't answer the query, use other available tools.
- If the retrieved information is useful for another tool (e.g., code snippets, API details), pass that information to the appropriate tool.

How to use the tool:
- Call knowledgebase_retriever with TWO parameters:
  1. query: Your search query (what you want to find)
  2. knowledgebase_names: Pass the knowledge base list: {knowledgebase_names}

Example:
  knowledgebase_retriever(query="product features", knowledgebase_names={knowledgebase_names})

When to use:
- ALWAYS call this tool FIRST for any user query that might be answered by domain knowledge
- Review the retrieved information carefully and determine if it answers the query
- If the knowledge base provides relevant information, use it in your response
- If the knowledge base information is incomplete or irrelevant, proceed with other available tools
- You can combine knowledge base information with other tool outputs for comprehensive answers

Always prioritize accuracy: if the knowledge base provides specific information, use it in your response."""
                            
                            # Add instruction to the appropriate system prompt based on agent type
                            if agent_config["AGENT_TYPE"] == "react_agent":
                                agent_config['SYSTEM_PROMPT']['SYSTEM_PROMPT_REACT_AGENT'] += kb_instruction
                            elif agent_config["AGENT_TYPE"] == "react_critic_agent":
                                agent_config['SYSTEM_PROMPT']['SYSTEM_PROMPT_EXECUTOR_AGENT'] += kb_instruction
                except Exception as e:
                    log.warning(f"Error fetching knowledge bases for agent '{agentic_application_id}': {e}")

            # Fetch database connections for agent and auto-inject database query tool
            db_connection_names = None
            log.info(f"[DB_TOOLS_CHECK] Agent type: {agent_config.get('AGENT_TYPE')}, checking for db_connection_names...")
            if agent_config["AGENT_TYPE"] in ["react_agent", "react_critic_agent", "planner_executor_agent", "planner_executor_critic_agent"]:
                try:
                    from src.inference.database_tools_integration import (
                        get_db_connections_for_agent,
                        inject_database_tools_into_config,
                        ensure_database_files_restored
                    )
                    
                    log.info(f"[DB_TOOLS_CHECK] Calling get_db_connections_for_agent({agentic_application_id})...")
                    db_connection_names = await get_db_connections_for_agent(agentic_application_id)
                    log.info(f"[DB_TOOLS_CHECK] Result: {db_connection_names}")
                    
                    if db_connection_names:
                        # Store for tool loading in _get_react_agent_as_executor_agent
                        self._db_connection_names = db_connection_names
                        log.info(f"Database connections configured for agent '{agentic_application_id}': {db_connection_names}")
                        
                        # Ensure schema/samples files exist locally (restore from blob if missing)
                        _dept_for_restore = current_user_department.get("General")
                        await ensure_database_files_restored(db_connection_names, department=_dept_for_restore)
                        
                        agent_config['DB_CONNECTION_NAMES'] = db_connection_names
                        
                        # Inject database query tool and system prompt instructions
                        # Agent will use run_shell_command to read schema/sample files from /databases/{conn}/
                        agent_config = inject_database_tools_into_config(
                            agent_config, 
                            db_connection_names,
                            agent_id=agentic_application_id
                        )
                        
                        log.info(f"[DB_TOOLS_CHECK] Database connections configured for agent: {db_connection_names}")
                    else:
                        log.info(f"[DB_TOOLS_CHECK] No db_connection_names returned")
                except Exception as e:
                    log.warning(f"[DB_TOOLS_CHECK] Error fetching database connections for agent '{agentic_application_id}': {e}")
                    import traceback
                    log.warning(f"[DB_TOOLS_CHECK] Traceback: {traceback.format_exc()}")

            # ========== PRE-INFERENCE ASSET RESTORATION (parallel) ==========
            # Ensure all required files are available locally before inference.
            # Restores from blob storage in parallel: file_context_prompts, 
            # database schema/samples, SQLite DBs, user_uploads.
            try:
                from src.inference.pre_inference_restore import ensure_inference_assets_available
                await ensure_inference_assets_available(
                    department=current_user_department.get("General"),
                    agent_id=agentic_application_id,
                    agent_name=agent_config.get("AGENT_NAME", ""),
                    db_connection_names=db_connection_names,
                    file_context_management_flag=file_context_management_flag,
                    uploaded_files=inference_request.uploaded_files,
                    is_skill_agent=False,
                )
            except Exception as e:
                log.warning(f"[PreInferenceRestore] Non-critical error during asset restoration: {e}")

            # Generate response using the React agent workflow
            try:
                async for response in self._generate_response(
                    query=query,
                    agentic_application_id=agentic_application_id,
                    session_id=session_id,
                    model_name=model_name,
                    agent_config=agent_config,
                    project_name=project_name,
                    reset_conversation=reset_conversation,
                    plan_verifier_flag=plan_verifier_flag,
                    is_plan_approved=is_plan_approved,
                    plan_feedback=plan_feedback,
                    response_formatting_flag=response_formatting_flag,
                    context_flag=context_flag,
                    file_context_management_flag=file_context_management_flag,
                    evaluation_flag=evaluation_flag,
                    validator_flag=validator_flag,
                    tool_interrupt_flag=tool_interrupt_flag,
                    tool_feedback=tool_feedback,
                    skill_verifier_flag=skill_verifier_flag,
                    skill_feedback=skill_feedback,
                    temperature=temperature,
                    enable_streaming_flag=enable_streaming_flag,
                    mentioned_agent_id=mentioned_agent_id,
                    interrupt_items=interrupt_items,
                    use_kafka_tool_worker=use_kafka_tool_worker,
                    inference_config=inference_config,
                    department_name=department_name,
                    execution_mode=execution_mode
                ):
                    if "executor_messages" not in response:
                        yield response

            except LLMInfrastructureError as e:
                # Map error types to user-friendly messages
                ERROR_MESSAGES = ["rate_limit","context_length","content_policy","connection_error","invalid_credentials","bad_request","service_unavailable","timeout","api_error"]
                
                error_message = str(e) if e.type in ERROR_MESSAGES else f"An error occurred: {str(e)}"
                log.warning(f"[{session_id}] {e.type} error for agent_id={agentic_application_id}: {e}")
                
                # Response with error_type for UI team
                response = {
                    "response": error_message,
                    "error": str(e),
                    "error_type": e.type,  # <-- UI team can use this
                    "executor_messages": [
                        HumanMessage(content=query),
                        AIMessage(content=error_message)
                    ]
                }
                update_session_context(response=error_message)
                yield response
                return
                    
            except Exception as e:
                error_str = str(e).lower()
                error_message = None
                
                # Check for rate limit errors
                if any(keyword in error_str for keyword in ["rate limit", "ratelimit", "429", "too many requests", "quota exceeded", "requests per minute"]):
                    error_message = "I apologize, but the service is currently experiencing high demand. The rate limit has been exceeded. Please wait a moment and try again."
                    log.warning(f"Rate limit error encountered: {e}")
                
                # Check for request limit errors
                elif any(keyword in error_str for keyword in ["request limit", "max requests", "request quota"]):
                    error_message = "The maximum number of requests has been reached. Please try again later or contact support if this persists."
                    log.warning(f"Request limit error encountered: {e}")
                
                # Check for context length/token limit errors
                elif any(keyword in error_str for keyword in ["context length", "token limit", "max tokens", "context_length_exceeded", "maximum context", "too long", "reduce the length"]):
                    error_message = "The conversation has become too long and exceeds the context limit. Please start a new conversation or reduce the length of your message."
                    log.warning(f"Context limit error encountered: {e}")
                
                # Check for PII (Personally Identifiable Information) violations
                elif any(keyword in error_str for keyword in ["sensitive PII", "PII entities", "BANK_ACCOUNT_NUMBER", "AADHAR", "PAN", "PASSPORT", "personal information"]):
                    error_message = "I noticed you may have shared sensitive personal information (such as an Aadhar number, bank account, PAN, or passport details). For your privacy and security, I cannot process requests containing such data. Please rephrase your question without including personal identifiers."
                    log.warning(f"PII violation error encountered: {e}")
                
                # Check for content policy/jailbreak errors
                elif any(keyword in error_str for keyword in ["content policy", "jailbreak", "content filter", "unsafe content", "policy violation", "content management", "responsible ai"]):
                    error_message = "Your request could not be processed as it may violate content policies. Please rephrase your question and ensure it follows acceptable use guidelines."
                    log.warning(f"Content policy/jailbreak error encountered: {e}")
                
                # Generic error fallback
                error_message = f"An error occurred while processing your request: {str(e)}"
                log.error(f"[{session_id}] Unexpected error during response generation for agent_id={agentic_application_id}: {e}")
                
                # Create error response with AIMessage
                response = {
                    "response": error_message,
                    "error": str(e),
                    "executor_messages": [
                        HumanMessage(content=query),
                        AIMessage(content=error_message)
                    ]
                }
                update_session_context(response=error_message)
                yield response
                return

            if isinstance(response, str):
                update_session_context(response=response)
                response = {"error": response}
            elif "error" in response:
                update_session_context(response=response["error"])
            # ---- HITL interrupt handling (skill agent tool_verifier_flag) ----
            # When the graph is interrupted mid-node (e.g. skill_executor's
            # interrupt() call), the node hasn't returned yet so
            # executor_messages only contains the initial HumanMessage.
            # Reconstruct a proper response that matches the react agent format
            # so the UI can render the pending tool-call and approval prompt.
            elif response.get("__interrupt__") and not response.get("response"):
                import uuid
                _interrupt_data = response["__interrupt__"]
                log.info(f"[{session_id}] HITL interrupt detected, formatting response for UI")

                # --- Plan verification/feedback interrupts are already enriched ---
                # If _enrich_interrupted_response already identified this as a
                # plan_verification or plan_feedback interrupt, skip the tool extraction logic.
                _interrupt_meta = response.get("interrupt_metadata", {})
                if _interrupt_meta.get("interrupt_type") in ("plan_verification", "plan_feedback"):
                    log.info(f"[{session_id}] {_interrupt_meta.get('interrupt_type')} interrupt - skipping tool extraction")
                    update_session_context(response="")
                    response_evaluation = deepcopy(response)
                    response_evaluation["executor_messages"] = await self.chat_service.segregate_conversation_from_raw_chat_history_with_json_like_steps(response)
                    response["executor_messages"] = await self.chat_service.segregate_conversation_from_raw_chat_history_with_pretty_steps(
                        response,
                        agentic_application_id=agentic_application_id,
                        session_id=session_id,
                        role=role,
                        department_name=department_name,
                    )
                else:
                    # Extract pending tool call info from the streaming events
                    # that the writer already emitted.  Since the skill_executor
                    # node was interrupted mid-execution, its executor_messages
                    # never made it into the state.  We scan the streamed events
                    # that were yielded earlier to reconstruct tool call details.
                    _pending_tool_name = None
                    _pending_tool_args = {}
                    _pending_tool_call_id = None

                    # Check if any tool_call details were captured in streaming
                    # events stored on the response (some agents store them).
                    # Fallback: parse executor_messages from checkpoint if they
                    # contain AIMessages with tool_calls.
                    for _msg in response.get("executor_messages", []):
                        if hasattr(_msg, 'tool_calls') and _msg.tool_calls:
                            for _tc in _msg.tool_calls:
                                _pending_tool_name = _tc.get("name")
                                _pending_tool_args = _tc.get("args", {})
                                _pending_tool_call_id = _tc.get("id")

                    # Build the approval message
                    _interrupt_msg = "⏸️ Tool execution requires approval. Please approve or reject to proceed."
                    if _pending_tool_name:
                        _args_preview = ", ".join(f"{k}={v}" for k, v in _pending_tool_args.items()) if isinstance(_pending_tool_args, dict) else str(_pending_tool_args)
                        _interrupt_msg = (
                            f"⏸️ Tool **{_pending_tool_name}** requires approval before execution.\n\n"
                            f"**Arguments:** {_args_preview}\n\n"
                            f"Please approve or provide feedback to proceed."
                        )

                    # Match react agent format: response/final_response empty on interrupt
                    response["response"] = ""
                    _query_text = response.get("query", query)

                    # Build executor_messages matching react agent format:
                    # [HumanMessage(user_query), AIMessage(with tool_calls)]
                    # NO final AIMessage with interrupt text — keeps final_response=""
                    _exec_msgs = [HumanMessage(content=_query_text, id=str(uuid.uuid4()), additional_kwargs={}, response_metadata={})]
                    _exec_msgs[-1].role = "user_query"  # type: ignore[attr-defined]

                    if _pending_tool_name:
                        # Add AIMessage with tool_calls so segregate picks up tools_used
                        _tc_id = _pending_tool_call_id or f"tc_{uuid.uuid4().hex[:8]}"
                        _ai_with_tc = AIMessage(
                            content="",
                            tool_calls=[{"name": _pending_tool_name, "args": _pending_tool_args, "id": _tc_id}],
                            additional_kwargs={
                                "tool_calls": [{
                                    "id": _tc_id,
                                    "function": {
                                        "name": _pending_tool_name,
                                        "arguments": json.dumps(_pending_tool_args) if isinstance(_pending_tool_args, dict) else str(_pending_tool_args),
                                    },
                                    "type": "function",
                                }]
                            },
                        )
                        _exec_msgs.append(_ai_with_tc)

                    response["executor_messages"] = _exec_msgs
                    update_session_context(response="")
                    # Fall through to segregation below
                    response_evaluation = deepcopy(response)
                    response_evaluation["executor_messages"] = await self.chat_service.segregate_conversation_from_raw_chat_history_with_json_like_steps(response)
                    response["executor_messages"] = await self.chat_service.segregate_conversation_from_raw_chat_history_with_pretty_steps(
                        response,
                        agentic_application_id=agentic_application_id,
                        session_id=session_id,
                        role=role,
                        department_name=department_name,
                    )
            else:
                update_session_context(response=response['response'])
                response_evaluation = deepcopy(response)
                
                
                response_evaluation["executor_messages"] = await self.chat_service.segregate_conversation_from_raw_chat_history_with_json_like_steps(response)

                # call segregate to ensure proper formatting
                
                response["executor_messages"] = await self.chat_service.segregate_conversation_from_raw_chat_history_with_pretty_steps(
                    response, 
                    agentic_application_id=agentic_application_id,
                    session_id=session_id,
                    role=role,
                    department_name=department_name
                )
                
            if insert_into_eval_flag:
                try:
                    time_start = time.monotonic()
                    self._safe_background_task(
                        self.evaluation_service.log_evaluation_data(session_id, agentic_application_id, agent_config, response_evaluation, model_name),
                        name="log_evaluation_data",
                    )
                    time_end = time.monotonic()
                    log.info(f"[{session_id}] Evaluation data logging task created | time_to_dispatch={time_end - time_start:.4f}s")
                except Exception as e:
                    log.error(f"[{session_id}] Error Occurred while inserting into evaluation data for agent_id={agentic_application_id}: {e}")

            # --- Background sync ALL workspace files to blob after response ---
            try:
                if self.storage_client or self.storage_provider:
                    from src.utils.workspace_blob_sync import WorkspaceBlobSync
                    if not self.storage_client:
                        self._initialize_storage_client()
                    if self.storage_client:
                        _sync = WorkspaceBlobSync(
                            storage_client=self.storage_client,
                            workspace_root="./agent_workspaces",
                            department=department_name or "General",
                            agent_id=agentic_application_id or "",
                            session_id=session_id or "",
                            user_email=current_user_email.get("") if hasattr(current_user_email, 'get') else "",
                            project_root=os.path.abspath("."),
                        )
                        _sync.schedule_sync_all(name="blob_post_inference_sync")
            except Exception as e:
                log.debug(f"[BlobSync] Post-inference sync skipped: {e}")

            end_time = time.monotonic()
            time_taken = end_time - start_time
            log.info(f"[{session_id}] Inference completed | agent_id={agentic_application_id}, time_taken={time_taken:.2f}s")
            
            # Safely set response_time - only if executor_messages contains dicts (not AIMessage objects)
            if response.get("executor_messages") and isinstance(response["executor_messages"][-1], dict):
                response["executor_messages"][-1]["response_time"] = time_taken
            
            
            # Filter entire response based on user role permissions
            if department_name and role and self.chat_service.authorization_service:
                has_execution_steps_access = await self.chat_service.authorization_service.check_execution_steps_access(role, department_name=department_name)
                if not has_execution_steps_access:
                    # For roles without execution steps access, return only executor_messages with filtered fields
                    yield {"executor_messages": response.get("executor_messages", [])}
            
            # Strip internal graph state fields before sending to frontend.
            # Only retain fields the UI actually needs (response, executor_messages,
            # __interrupt__, interrupt_metadata, plan, current_query_status, etc.)
            response = self._filter_response_for_frontend(response)

            yield response

        except Exception as e:
            # Catch any unhandled exceptions and raise a 500 internal server error
            log_guardrail_or_exception(f"[{session_id}] Unhandled error in agent inference for agent_id={agentic_application_id}: {e}", e)
            log.error(f"[{session_id}] Unhandled error in agent inference for agent_id={agentic_application_id}: {e}", exc_info=True)
            raise HTTPException(status_code=500, detail=f"Internal Server Error in run method of Langgraph inference: {str(e)}")

    async def update_response_time(self, agent_id: str, session_id: str, start_time: float, time_stamp: Any, workflow: "StateGraph" = None):
        """Updates the response time in the last executor message for the given session.
        
        Args:
            workflow: Optional uncompiled StateGraph with the correct topology.
                      Compiled inside this method with the checkpointer.
                      When None, builds via _build_workflow(get_dummy=True).
        """
        log.debug(f"[{session_id}] Updating response time for agent_id={agent_id}")
        try:
            async with await self.chat_service.get_checkpointer_context_manager() as checkpointer:
                thread_id = await self.chat_service._get_thread_id(agent_id, session_id)
                graph_config = await self.chat_service._get_thread_config(thread_id)

                if workflow is None:
                    workflow = await self._build_workflow(chains={}, flags={}, get_dummy=True)
                app = workflow.compile(checkpointer=checkpointer)
                
                current_time = time.monotonic()
                response_time = current_time - start_time
                await app.aupdate_state(config=graph_config, values={"executor_messages":ChatMessage(content=[
                    {
                        "response_time":response_time,
                        "start_timestamp": time_stamp.isoformat()
                    }
                    ], role="response_time")})
                log.info(f"[{session_id}] Response time updated | agent_id={agent_id}, response_time={response_time:.2f}s")
                return response_time
        except Exception as e:
            log.error(f"[{session_id}] Error occurred while updating response time for agent_id={agent_id}: {e}")

    async def update_token_usage_in_graph(
        self,
        agent_id: str,
        session_id: str,
        token_records: List[Dict],
        workflow: "StateGraph" = None,
    ) -> None:
        """Inject per-query token/cost totals into the LangGraph checkpoint.

        Uses the actual workflow topology (via get_dummy=True) to preserve
        interrupt state in langgraph 1.1+. When a `workflow` is provided,
        compiles it with the checkpointer; otherwise builds one via get_dummy.
        """
        if not token_records:
            log.info(f"⏭️  [TokenUsageGraph] No token records to inject for session={session_id} — skipping")
            return
        try:
            log.info(
                f"🔄 [TokenUsageGraph] Injecting {len(token_records)} LLM call record(s) "
                f"into checkpoint for session={session_id}"
            )
            async with await self.chat_service.get_checkpointer_context_manager() as checkpointer:
                thread_id = await self.chat_service._get_thread_id(agent_id, session_id)
                graph_config = await self.chat_service._get_thread_config(thread_id)

                if workflow is None:
                    workflow = await self._build_workflow(chains={}, flags={}, get_dummy=True)
                app = workflow.compile(checkpointer=checkpointer)

                total_prompt     = sum(r.get('prompt_tokens', 0)     for r in token_records)
                total_completion = sum(r.get('completion_tokens', 0) for r in token_records)
                total_tokens     = sum(r.get('total_tokens', 0)      for r in token_records)
                total_cached     = sum(r.get('cached_tokens', 0)     for r in token_records)

                log.info(
                    f"📊 [TokenUsageGraph] Aggregated totals — "
                    f"prompt={total_prompt}, completion={total_completion}, "
                    f"cached={total_cached}, total={total_tokens}"
                )
                for i, r in enumerate(token_records, 1):
                    log.info(
                        f"    Call {i}: model={r.get('model')}, "
                        f"prompt={r.get('prompt_tokens')}, "
                        f"completion={r.get('completion_tokens')}, "
                        f"total={r.get('total_tokens')}, "
                        f"category={r.get('call_category')}/{r.get('call_sub_category')}"
                    )

                await app.aupdate_state(
                    config=graph_config,
                    values={"executor_messages": ChatMessage(
                        content=[{
                            "prompt_tokens":     total_prompt,
                            "completion_tokens": total_completion,
                            "total_tokens":      total_tokens,
                            "cached_tokens":     total_cached,
                            "llm_calls":         token_records,
                        }],
                        role="token_usage",
                    )},
                )
                log.info(
                    f"✅ [TokenUsageGraph] Sentinel written to checkpoint: "
                    f"session={session_id}, agent={agent_id}, "
                    f"total_tokens={total_tokens}, llm_calls={len(token_records)}"
                )
        except Exception as e:
            log.error(f"❌ [TokenUsageGraph] Error injecting token usage into graph: {e}", exc_info=True)


class BaseMetaTypeAgentInference(BaseAgentInference):
    """
    Base class for meta-type agent inference.
    """

    def __init__(self, inference_utils: InferenceUtils):
        super().__init__(inference_utils)


    # --- Helper Methods ---

    async def _get_planner_executor_critic_agent_as_worker_agent(self,
                                                                 llm: Any,
                                                                 system_prompts: str,
                                                                 checkpointer: Any = None,
                                                                 tool_ids: List[str] = [],
                                                                 tool_versions: Dict[str, str] = None,
                                                                 interrupt_tool: bool = False,
                                                                 writer_holder: dict = None,
                                                                 use_kafka_tool_worker: bool = False
                                                                 ) -> Any:
        """
        Creates a planner-executor-critic agent as a meta agent worker with tools loaded dynamically.
        Supports streaming via writer_holder for real-time status updates.
        
        Args:
            llm: The language model to use
            system_prompts: Dictionary of system prompts for each agent role
            checkpointer: Optional checkpointer for state persistence
            tool_ids: List of tool IDs to load
            interrupt_tool: Whether to enable tool interruption
            writer_holder: A mutable dict that will hold the StreamWriter reference,
                          set by the parent graph node before execution.
                          Example: {"writer": <StreamWriter instance>}
        """
        
        # Initialize writer_holder if not provided (for standalone usage)
        if writer_holder is None:
            writer_holder = {"writer": None}
        
        # Helper function for safe streaming writes
        def safe_write(data):
            """Safely write to StreamWriter if available."""
            if writer_holder:
                writer = writer_holder.get("writer")
                if writer:
                    try:
                        writer(data)
                    except Exception as e:
                        log.warning(f"Failed to write to stream: {e}")
        # System Prompts
        planner_system_prompt = system_prompts.get("SYSTEM_PROMPT_PLANNER_AGENT", "").replace("{", "{{").replace("}", "}}")
        critic_based_planner_system_prompt = system_prompts.get("SYSTEM_PROMPT_CRITIC_BASED_PLANNER_AGENT", "").replace("{", "{{").replace("}", "}}")
        executor_system_prompt = system_prompts.get("SYSTEM_PROMPT_EXECUTOR_AGENT", "")
        critic_system_prompt = system_prompts.get("SYSTEM_PROMPT_CRITIC_AGENT", "").replace("{", "{{").replace("}", "}}")
        response_generator_system_prompt = system_prompts.get("SYSTEM_PROMPT_RESPONSE_GENERATOR_AGENT", "").replace("{", "{{").replace("}", "}}")

        # Agents and Chains
        planner_chain_json, planner_chain_str = await self._get_chains(llm, planner_system_prompt)
        executor_agent, tool_list, _ = await self._get_react_agent_as_executor_agent(
                                        llm,
                                        system_prompt=executor_system_prompt,
                                        checkpointer=checkpointer,
                                        tool_ids=tool_ids,
                                        tool_versions=tool_versions,  # Pass tool version mapping
                                        interrupt_tool=interrupt_tool,
                                        use_kafka_tool_worker=use_kafka_tool_worker
                                    )
        critic_chain_json, critic_chain_str = await self._get_chains(llm, critic_system_prompt)
        response_gen_chain_json, response_gen_chain_str = await self._get_chains(llm, response_generator_system_prompt)
        critic_planner_chain_json, critic_planner_chain_str = await self._get_chains(llm, critic_based_planner_system_prompt)

        if not llm or not executor_agent or not planner_chain_json or not planner_chain_str or \
                not critic_planner_chain_json or not critic_planner_chain_str or not critic_chain_json or \
                not critic_chain_str or not response_gen_chain_json or not response_gen_chain_str:
            raise HTTPException(status_code=500, detail="Required chains or agent executor are missing")

        # State Schema
        class PlanExecuteCritic(TypedDict):
            query: str
            messages: Annotated[List[AnyMessage], add_messages]
            plan: List[str]
            past_steps_input: List[str]
            past_steps_output: List[str]
            response: str
            response_quality_score: float
            critique_points: str
            epoch: int
            step_idx: int # App Related vars
            start_timestamp: datetime
            end_timestamp: datetime

        # Nodes

        async def planner_agent(state: PlanExecuteCritic):
            """
            This function takes the current state of the conversation and generates a plan for the agent to follow.

            Args:
                state (PlanExecuteCritic): The current state of the conversation, including past conversation summary, ongoing conversation, tools info, and the input query.

            Returns:
                dict: A dictionary containing the plan for the agent to follow.
            """
            safe_write({"Node Name": "Planner Agent", "Status": "Started"})
            strt_tmstp = get_timestamp()
            state["query"] = state["messages"][0].content
            # Format the query for the planner
            formatted_query = f'''\
Tools Info:
{await self.tool_service.render_text_description_for_tools(tool_list)}

Input Query:
{state["query"]}
'''
            invocation_input = {"messages": [("user", formatted_query)]}
            planner_response = await self.inference_utils.output_parser(
                                                            llm=llm,
                                                            chain_1=planner_chain_json,
                                                            chain_2=planner_chain_str,
                                                            invocation_input=invocation_input,
                                                            error_return_key="plan"
                                                        )
            safe_write({"raw": {"plan": planner_response['plan']}, "content": f"Generated execution plan with {len(planner_response['plan'])} steps"})
            log.info(f"Planner Agent generated plan: {planner_response['plan']}")
            safe_write({"Node Name": "Planner Agent", "Status": "Completed"})

            # Detect guardrail errors disguised as plan steps by output_parser
            if planner_response.get('plan'):
                for step_text in planner_response['plan']:
                    guardrail_message = format_guardrail_user_response(str(step_text))
                    if guardrail_message:
                        log.warning("Guardrail violation detected in planner output")
                        return {
                            "query": state["query"],
                            "messages": ChatMessage(content="", role="plan"),
                            "plan": [],
                            "response": guardrail_message,
                            "errors": [str(step_text)],
                            'response_quality_score': None,
                            'critique_points': None,
                            'past_steps_input': None,
                            'past_steps_output': None,
                            'epoch': 0,
                            'step_idx': 0,
                            'start_timestamp': strt_tmstp
                        }

            return {
                "query": state["query"],
                "messages": ChatMessage(content=planner_response['plan'], role="plan"),
                "plan": planner_response['plan'],
                'response': None,
                'response_quality_score': None,
                'critique_points': None,
                'past_steps_input': None,
                'past_steps_output': None,
                'epoch': 0,
                'step_idx': 0,
                'start_timestamp': strt_tmstp
            }

        async def executor_agent_node(state: PlanExecuteCritic):
            """
            Executes the current step in the plan using the executor agent.

            Args:
                state: The current state of the plan execution.

            Returns:
                A dictionary containing the response from the executor agent,
                the updated past steps, and the executor messages.
            """
            safe_write({"Node Name": "Executor Agent", "Status": "Started"})
            step = state["plan"][state["step_idx"]]
            completed_steps = []
            completed_steps_responses = []
            task_formatted = state["query"] + "\n\n"
            if state["step_idx"]!=0:
                completed_steps = state["past_steps_input"][:state["step_idx"]]
                completed_steps_responses = state["past_steps_output"][:state["step_idx"]]
                task_formatted += f"Past Steps:\n{await self.inference_utils.format_past_steps_list(completed_steps, completed_steps_responses)}"
            task_formatted += f"\n\nCurrent Step:\n{step}"
            
            safe_write({"raw": {"Current Step": step}, "content": f"Executing step {state['step_idx']+1}/{len(state['plan'])}: {step}"})
            
            # Stream execution for real-time updates
            final_content_parts = []
            try:
              async for msg in executor_agent.astream({"messages": [("user", task_formatted.strip())]}):
                if isinstance(msg, dict) and "agent" in msg:
                    agent_output = msg.get("agent", {})
                    messages = []
                    if isinstance(agent_output, dict) and "messages" in agent_output:
                        messages = agent_output.get("messages", [])
                
                    for message in messages:
                        # Handle tool calls
                        if hasattr(message, 'tool_calls') and message.tool_calls:
                            tool_call = message.tool_calls[0]
                            safe_write({"Node Name": "Tool Call", "Status": "Started", "Tool Name": tool_call['name'], "Tool Arguments": tool_call['args']})
                            tool_name = tool_call["name"]
                            tool_args = tool_call["args"]

                            if tool_args:   # Non-empty dict means arguments exist
                                if isinstance(tool_args, dict):
                                    args_str = ", ".join(f"{k}={v}" for k, v in tool_args.items())
                                else:
                                    args_str = str(tool_args)
                                tool_call_content = f"Agent called the tool '{tool_name}', passing arguments: {args_str}."
                            else:
                                tool_call_content = f"Agent called the tool '{tool_name}', passing no arguments."

                            safe_write({"content": tool_call_content})
                        
                    final_content_parts.extend(messages)
                    
                elif "tools" in msg:
                    tool_messages = msg.get("tools", {})
                    messages_list = tool_messages.get("messages", [])
                    
                    for tool_message in messages_list:
                        safe_write({"raw": {"Tool Name": tool_message.name, "Tool Output": tool_message.content}, "content": f"Tool {tool_message.name} returned: {tool_message.content}"})
                        if hasattr(tool_message, "name"):
                            safe_write({"Node Name": "Tool Call", "Status": "Completed", "Tool Name": tool_message.name})
                    final_content_parts.extend(messages_list)
                else:
                    # Handle other message types
                    if "agent" in msg:
                        final_content_parts.extend(msg["agent"]["messages"])
            except Exception as e:
              error = f"Error in Executor Agent: {e}"
              safe_write({"Node Name": "Executor Agent", "Status": "Failed"})
              log_guardrail_or_exception(error, e)
              guardrail_message = get_guardrail_response_from_exception(e)
              if guardrail_message:
                  return {"response": guardrail_message, "errors": [error]}
              return {"errors": [error]}
            
            # Extract final response from last message
            if final_content_parts:
                last_msg = final_content_parts[-1]
                if hasattr(last_msg, 'content'):
                    final_response = last_msg.content
                else:
                    final_response = str(last_msg)
            else:
                final_response = ""
            
            completed_steps.append(step)
            completed_steps_responses.append(final_response)
            log.info(f"Executor Agent executed step {state['step_idx']+1}/{len(state['plan'])}: {step}")
            safe_write({"Node Name": "Executor Agent", "Status": "Completed"})
            return {
                "response": final_response,
                "past_steps_input": completed_steps,
                "past_steps_output": completed_steps_responses,
                "messages": final_content_parts if final_content_parts else [ChatMessage(content=final_response, role="executor")]
            }

        def increment_step(state: PlanExecuteCritic):
            safe_write({"content": f"Incrementing step index from {state['step_idx']} to {state['step_idx']+1}"})
            log.info(f"Incrementing step index from {state['step_idx']} to {state['step_idx']+1}")
            return {"step_idx": state["step_idx"]+1}

        async def response_generator_agent(state: PlanExecuteCritic):
            """
            This function takes the current state of the conversation
            and generates a response using a response generation chain.
            Args:
                state (PlanExecuteCritic): The current state of the conversation,
                containing information about the past conversation,
                ongoing conversation, user query, completed steps,
                and the response from the executor agent.
            Returns:
                dict: A dictionary containing the generated response.
            """
            safe_write({"Node Name": "Response Generator", "Status": "Started"})
            formatted_query = f'''\
User Query:
{state["query"]}

Steps Completed to generate final response:
{await self.inference_utils.format_past_steps_list(state["past_steps_input"], state["past_steps_output"])}

Final Response from Executor Agent:
{state["response"]}
'''
            invocation_input = {"messages": [("user", formatted_query)]}
            response_gen_response = await self.inference_utils.output_parser(
                                                                llm=llm,
                                                                chain_1=response_gen_chain_json,
                                                                chain_2=response_gen_chain_str,
                                                                invocation_input=invocation_input,
                                                                error_return_key="response"
                                                            )
            if isinstance(response_gen_response, dict) and "response" in response_gen_response:
                    safe_write({"response": response_gen_response["response"]})
                    log.info(f"Response Generator Agent generated response: {response_gen_response['response']}")
                    safe_write({"Node Name": "Response Generator", "Status": "Completed"})
                    return {"response": response_gen_response["response"]}
            else:
                log.error(f"Response generation failed")
                safe_write({"Node Name": "Response Generator", "Status": "Failed"})
                result = await llm.ainvoke(f"Format the response in Markdown Format.\n\nResponse: {response_gen_response}")
                return {"response": result.content}

        async def critic_agent(state: PlanExecuteCritic):
            """
            This function takes a state object containing information about the conversation and the generated response,
            formats it into a query for the critic model, and returns the critic's evaluation of the response.

            Args:
                state (PlanExecuteCritic): A dictionary containing information about the conversation and the generated response.

            Returns:
                dict: A dictionary containing the critic's evaluation of the response, including the response quality score and critique points.
            """
            safe_write({"Node Name": "Critic Agent", "Status": "Started"})
            formatted_query = f'''\
Tools Info:
{await self.tool_service.render_text_description_for_tools(tool_list)}

User Query:
{state["query"]}

Steps Completed to generate final response:
{await self.inference_utils.format_past_steps_list(state["past_steps_input"], state["past_steps_output"])}

Final Response:
{state["response"]}
'''
            invocation_input = {"messages": [("user", formatted_query)]}
            critic_response = await self.inference_utils.output_parser(
                                                            llm=llm,
                                                            chain_1=critic_chain_json,
                                                            chain_2=critic_chain_str,
                                                            invocation_input=invocation_input,
                                                            error_return_key="critique_points"
                                                        )

            if critic_response["critique_points"] and "error" in critic_response["critique_points"][0]:
                critic_response = {'response_quality_score': 0, 'critique_points': critic_response["critique_points"]}
            safe_write({"raw": {"response_quality_score": critic_response["response_quality_score"], "critique_points": critic_response["critique_points"]}, "content": f"Response quality score: {critic_response['response_quality_score']}"})
            log.info(f"Critic Agent evaluated response with quality score: {critic_response['response_quality_score']}")
            safe_write({"Node Name": "Critic Agent", "Status": "Completed"})
            return {
                "response_quality_score": critic_response["response_quality_score"],
                "critique_points": critic_response["critique_points"],
                "messages": ChatMessage(
                    content=[{
                            "response_quality_score": critic_response["response_quality_score"],
                            "critique_points": critic_response["critique_points"]
                        }],
                    role="critic-response"
                ),
                "epoch": state["epoch"]+1
            }

        async def critic_based_planner_agent(state: PlanExecuteCritic):
            """
            This function takes a state object containing information about the current conversation, tools, and past steps,
            and uses a critic-based planner to generate a plan for the next step.

            Args:
                state (PlanExecuteCritic): A dictionary containing information about the current conversation, tools, and past steps.

            Returns:
                dict: A dictionary containing the plan for the next step and the index of the current step.
            """
            safe_write({"Node Name": "Critic-Based Planner", "Status": "Started"})
            formatted_query = f'''
Tools Info:
{await self.tool_service.render_text_description_for_tools(tool_list)}

User Query:
{state["query"]}

Steps Completed Previously to Generate Final Response:
{await self.inference_utils.format_past_steps_list(state["past_steps_input"], state["past_steps_output"])}

Final Response:
{state["response"]}

Response Quality Score:
{state.get("response_quality_score", "Not yet evaluated")}

Critique Points:
{await self.inference_utils.format_list_str(state["critique_points"]) if state.get("critique_points") else "No critique points available yet."}
'''

            invocation_input = {"messages": [("user", formatted_query)]}
            critic_planner_response = await self.inference_utils.output_parser(
                                                                    llm=llm,
                                                                    chain_1=critic_planner_chain_json,
                                                                    chain_2=critic_planner_chain_str,
                                                                    invocation_input=invocation_input,
                                                                    error_return_key="plan"
                                                                )
            safe_write({"raw": {"revised_plan": critic_planner_response['plan']}, "content": f"Generated revised plan with {len(critic_planner_response['plan'])} steps based on critique"})
            log.info(f"Critic-Based Planner Agent generated plan: {critic_planner_response['plan']}")
            safe_write({"Node Name": "Critic-Based Planner", "Status": "Completed"})
            return {
                "plan": critic_planner_response["plan"],
                "messages": ChatMessage(content=critic_planner_response['plan'], role="critic-plan"),
                "step_idx": 0
            }

        def final_response(state: PlanExecuteCritic):
            """
            This function handles the final response of the conversation.
            Args:
                state: A PlanExecuteCritic object containing the state of the conversation.
            Returns:
                A dictionary containing the final response and the end timestamp.
            """
            safe_write({"Node Name": "Final Response", "Status": "Started"})
            end_timestamp = get_timestamp()
            response = state['response']
            if not response and state.get('errors'):
                guardrail_resp = get_guardrail_response_from_errors(
                    state['errors'] if isinstance(state['errors'], list) else [state['errors']]
                )
                if guardrail_resp:
                    response = guardrail_resp
                    log.info("final_response: guardrail/moderation check triggered, returning policy alert to user.")
            response = response if response else "No plans to execute"

            final_response_message = AIMessage(content=response)
            safe_write({"raw": {"final_response": response}, "content": f"Final response generated successfully"})
            log.info(f"Final response generated: {final_response_message.content}")
            safe_write({"Node Name": "Final Response", "Status": "Completed"})
            return {
                "messages": final_response_message,
                "end_timestamp": end_timestamp
            }

        def critic_decision(state: PlanExecuteCritic):
            """
            Decides whether to return the final response or continue
            with the critic-based planner agent.

            Args:
                state: The current state of the plan execution process.

            Returns:
                "final_response": If the response quality score is
                high enough or the maximum number of epochs has been reached.
                "critic_based_planner_agent": Otherwise.
            """
            errors = state.get("errors", [])
            if errors and get_guardrail_response_from_errors(errors if isinstance(errors, list) else [errors]):
                return "final_response"
            decision = "final_response" if state["response_quality_score"]>=0.7 or state["epoch"]==3 else "critic_based_planner_agent"
            safe_write({"content": f"Critic decision: {decision} (score: {state['response_quality_score']}, epoch: {state['epoch']})"})
            if state["response_quality_score"]>=0.7 or state["epoch"]==3:
                return "final_response"
            else:
                return "critic_based_planner_agent"

        def check_plan_execution_status(state: PlanExecuteCritic):
            """
            Checks the status of the plan execution and decides which agent should be called next.
            Args:
                state: The current state of the plan execution process.
            Returns:
                "response_generator_agent": If the plan has been fully executed.
                "executor_agent_node": Otherwise.
            """
            safe_write({"content": f"Plan execution status: Step {state['step_idx']}/{len(state['plan'])}"})
            errors = state.get("errors", [])
            if errors and get_guardrail_response_from_errors(errors if isinstance(errors, list) else [errors]):
                return "response_generator_agent"
            if state["step_idx"]==len(state["plan"]):
                return "response_generator_agent"
            else:
                return "executor_agent_node"

        def route_non_planner_question(state: PlanExecuteCritic):
            """
            Determines the appropriate agent to handle a general question based on the current state.
            Args:
                state: The current state of the PlanExecuteCritic object.

            Returns:
                A string representing the agent to call:
                    - "general_llm_call": If there is no plan or the first step in the plan does not have a "STEP" key.
                    - "executor_agent_node": If there is a plan and the first step has a "STEP" key.
            """
            if not state["plan"] or "STEP" not in state["plan"][0]:
                safe_write({"content": "No actionable plan generated, routing to final response"})
                return "final_response"
            else:
                safe_write({"content": f"Plan has {len(state['plan'])} steps, routing to executor"})
                return "executor_agent_node"

        ### Build Graph

        workflow = StateGraph(PlanExecuteCritic)
        workflow.add_node("planner_agent", planner_agent)
        workflow.add_node("executor_agent_node", executor_agent_node)
        workflow.add_node("increment_step", increment_step)
        workflow.add_node("response_generator_agent", response_generator_agent)
        workflow.add_node("critic_agent", critic_agent)
        workflow.add_node("critic_based_planner_agent", critic_based_planner_agent)
        workflow.add_node("final_response", final_response)

        workflow.add_edge(START, "planner_agent")
        workflow.add_conditional_edges(
            "planner_agent",
            route_non_planner_question,
            ["final_response", "executor_agent_node"],
        )
        workflow.add_edge("executor_agent_node", "increment_step")
        workflow.add_conditional_edges(
            "increment_step",
            check_plan_execution_status,
            ["executor_agent_node", "response_generator_agent"],
        )
        workflow.add_edge("response_generator_agent", "critic_agent")
        workflow.add_conditional_edges(
            "critic_agent",
            critic_decision,
            ["final_response", "critic_based_planner_agent"],
        )
        workflow.add_edge("critic_based_planner_agent", "executor_agent_node")
        workflow.add_edge("final_response", END)

        app = workflow.compile()
        log.info(f"Planner-Executor-Critic Agent created as Meta Agent Worker with streaming support.")
        return app, tool_list, writer_holder

    async def _get_planner_executor_agent_as_worker_agent(self,
                                                          llm: Any,
                                                          system_prompts: str,
                                                          checkpointer: Any = None,
                                                          tool_ids: List[str] = [],
                                                          tool_versions: Dict[str, str] = None,
                                                          interrupt_tool: bool = False,
                                                          writer_holder: dict = None,
                                                          use_kafka_tool_worker: bool = False
                                                          ) -> Any:
        """
        Creates a planner-executor agent (without critic) as a meta agent worker with tools loaded dynamically.
        Supports streaming via writer_holder for real-time status updates.
        
        Args:
            llm: The language model to use
            system_prompts: Dictionary of system prompts for each agent role
            checkpointer: Optional checkpointer for state persistence
            tool_ids: List of tool IDs to load
            tool_versions: Optional dict mapping tool_id -> version (e.g., 'v1', 'v2')
            interrupt_tool: Whether to enable tool interruption
            writer_holder: A mutable dict that will hold the StreamWriter reference
        """
        
        # Initialize writer_holder if not provided
        if writer_holder is None:
            writer_holder = {"writer": None}
        
        # Helper function for safe streaming writes
        def safe_write(data):
            """Safely write to StreamWriter if available."""
            if writer_holder:
                writer = writer_holder.get("writer")
                if writer:
                    try:
                        writer(data)
                    except Exception as e:
                        log.warning(f"Failed to write to stream: {e}")

        # System Prompts
        planner_system_prompt = system_prompts.get("SYSTEM_PROMPT_PLANNER_AGENT", "").replace("{", "{{").replace("}", "}}")
        executor_system_prompt = system_prompts.get("SYSTEM_PROMPT_EXECUTOR_AGENT", "")
        response_generator_system_prompt = system_prompts.get("SYSTEM_PROMPT_RESPONSE_GENERATOR_AGENT", "").replace("{", "{{").replace("}", "}}")

        # Agents and Chains
        planner_chain_json, planner_chain_str = await self._get_chains(llm, planner_system_prompt)
        executor_agent, tool_list, _ = await self._get_react_agent_as_executor_agent(
                                        llm,
                                        system_prompt=executor_system_prompt,
                                        checkpointer=checkpointer,
                                        tool_ids=tool_ids,
                                        tool_versions=tool_versions,  # Pass tool version mapping
                                        interrupt_tool=interrupt_tool,
                                        use_kafka_tool_worker=use_kafka_tool_worker
                                    )
        response_gen_chain_json, response_gen_chain_str = await self._get_chains(llm, response_generator_system_prompt)

        if not llm or not executor_agent or not planner_chain_json or not planner_chain_str or \
                not response_gen_chain_json or not response_gen_chain_str:
            raise HTTPException(status_code=500, detail="Required chains or agent executor are missing")

        # State Schema
        class PlanExecute(TypedDict):
            query: str
            messages: Annotated[List[AnyMessage], add_messages]
            plan: List[str]
            past_steps_input: List[str]
            past_steps_output: List[str]
            response: str
            step_idx: int
            start_timestamp: datetime
            end_timestamp: datetime

        # Nodes
        async def planner_agent(state: PlanExecute):
            """Generates a plan for the agent to follow."""
            safe_write({"Node Name": "Planner Agent", "Status": "Started"})
            strt_tmstp = get_timestamp()
            state["query"] = state["messages"][0].content
            
            formatted_query = f'''\
Tools Info:
{await self.tool_service.render_text_description_for_tools(tool_list)}

Input Query:
{state["query"]}
'''
            invocation_input = {"messages": [("user", formatted_query)]}
            planner_response = await self.inference_utils.output_parser(
                                                            llm=llm,
                                                            chain_1=planner_chain_json,
                                                            chain_2=planner_chain_str,
                                                            invocation_input=invocation_input,
                                                            error_return_key="plan"
                                                        )
            safe_write({"raw": {"plan": planner_response['plan']}, "content": f"Generated execution plan with {len(planner_response['plan'])} steps"})
            log.info(f"Planner Agent generated plan: {planner_response['plan']}")
            safe_write({"Node Name": "Planner Agent", "Status": "Completed"})

            # Detect guardrail errors disguised as plan steps by output_parser
            if planner_response.get('plan'):
                for step_text in planner_response['plan']:
                    guardrail_message = format_guardrail_user_response(str(step_text))
                    if guardrail_message:
                        log.warning("Guardrail violation detected in planner output")
                        return {
                            "query": state["query"],
                            "messages": ChatMessage(content="", role="plan"),
                            "plan": [],
                            "response": guardrail_message,
                            "errors": [str(step_text)],
                            'past_steps_input': None,
                            'past_steps_output': None,
                            'step_idx': 0,
                            'start_timestamp': strt_tmstp
                        }

            return {
                "query": state["query"],
                "messages": ChatMessage(content=planner_response['plan'], role="plan"),
                "plan": planner_response['plan'],
                'response': None,
                'past_steps_input': None,
                'past_steps_output': None,
                'step_idx': 0,
                'start_timestamp': strt_tmstp
            }

        async def executor_agent_node(state: PlanExecute):
            """Executes the current step in the plan."""
            safe_write({"Node Name": "Executor Agent", "Status": "Started"})
            step = state["plan"][state["step_idx"]]
            completed_steps = []
            completed_steps_responses = []
            task_formatted = state["query"] + "\n\n"
            
            if state["step_idx"] != 0:
                completed_steps = state["past_steps_input"][:state["step_idx"]]
                completed_steps_responses = state["past_steps_output"][:state["step_idx"]]
                task_formatted += f"Past Steps:\n{await self.inference_utils.format_past_steps_list(completed_steps, completed_steps_responses)}"
            task_formatted += f"\n\nCurrent Step:\n{step}"
            
            safe_write({"raw": {"Current Step": step}, "content": f"Executing step {state['step_idx']+1}/{len(state['plan'])}: {step}"})
            
            final_content_parts = []
            try:
              async for msg in executor_agent.astream({"messages": [("user", task_formatted.strip())]}):
                if isinstance(msg, dict) and "agent" in msg:
                    agent_output = msg.get("agent", {})
                    messages = []
                    if isinstance(agent_output, dict) and "messages" in agent_output:
                        messages = agent_output.get("messages", [])
                
                    for message in messages:
                        if hasattr(message, 'tool_calls') and message.tool_calls:
                            tool_call = message.tool_calls[0]
                            safe_write({"Node Name": "Tool Call", "Status": "Started", "Tool Name": tool_call['name'], "Tool Arguments": tool_call['args']})
                            tool_name = tool_call["name"]
                            tool_args = tool_call["args"]
                            if tool_args:
                                if isinstance(tool_args, dict):
                                    args_str = ", ".join(f"{k}={v}" for k, v in tool_args.items())
                                else:
                                    args_str = str(tool_args)
                                tool_call_content = f"Agent called the tool '{tool_name}', passing arguments: {args_str}."
                            else:
                                tool_call_content = f"Agent called the tool '{tool_name}', passing no arguments."
                            safe_write({"content": tool_call_content})
                        
                    final_content_parts.extend(messages)
                    
                elif "tools" in msg:
                    tool_messages = msg.get("tools", {})
                    messages_list = tool_messages.get("messages", [])
                    for tool_message in messages_list:
                        safe_write({"raw": {"Tool Name": tool_message.name, "Tool Output": tool_message.content}, "content": f"Tool {tool_message.name} returned: {tool_message.content}"})
                        if hasattr(tool_message, "name"):
                            safe_write({"Node Name": "Tool Call", "Status": "Completed", "Tool Name": tool_message.name})
                    final_content_parts.extend(messages_list)
                else:
                    if "agent" in msg:
                        final_content_parts.extend(msg["agent"]["messages"])
            except Exception as e:
              error = f"Error in Executor Agent: {e}"
              safe_write({"Node Name": "Executor Agent", "Status": "Failed"})
              log_guardrail_or_exception(error, e)
              guardrail_message = get_guardrail_response_from_exception(e)
              if guardrail_message:
                  return {"response": guardrail_message, "errors": [error]}
              return {"errors": [error]}
            
            if final_content_parts:
                last_msg = final_content_parts[-1]
                final_response = last_msg.content if hasattr(last_msg, 'content') else str(last_msg)
            else:
                final_response = ""
            
            completed_steps.append(step)
            completed_steps_responses.append(final_response)
            log.info(f"Executor Agent executed step {state['step_idx']+1}/{len(state['plan'])}: {step}")
            safe_write({"Node Name": "Executor Agent", "Status": "Completed"})
            return {
                "response": final_response,
                "past_steps_input": completed_steps,
                "past_steps_output": completed_steps_responses,
                "messages": final_content_parts if final_content_parts else [ChatMessage(content=final_response, role="executor")]
            }

        def increment_step(state: PlanExecute):
            safe_write({"content": f"Incrementing step index from {state['step_idx']} to {state['step_idx']+1}"})
            log.info(f"Incrementing step index from {state['step_idx']} to {state['step_idx']+1}")
            return {"step_idx": state["step_idx"]+1}

        async def response_generator_agent(state: PlanExecute):
            """Generates final response from completed steps."""
            safe_write({"Node Name": "Response Generator", "Status": "Started"})
            formatted_query = f'''\
User Query:
{state["query"]}

Steps Completed to generate final response:
{await self.inference_utils.format_past_steps_list(state["past_steps_input"], state["past_steps_output"])}

Final Response from Executor Agent:
{state["response"]}
'''
            invocation_input = {"messages": [("user", formatted_query)]}
            response_gen_response = await self.inference_utils.output_parser(
                                                                llm=llm,
                                                                chain_1=response_gen_chain_json,
                                                                chain_2=response_gen_chain_str,
                                                                invocation_input=invocation_input,
                                                                error_return_key="response"
                                                            )
            if isinstance(response_gen_response, dict) and "response" in response_gen_response:
                safe_write({"response": response_gen_response["response"]})
                log.info(f"Response Generator Agent generated response")
                safe_write({"Node Name": "Response Generator", "Status": "Completed"})
                return {"response": response_gen_response["response"]}
            else:
                log.error(f"Response generation failed")
                safe_write({"Node Name": "Response Generator", "Status": "Failed"})
                result = await llm.ainvoke(f"Format the response in Markdown Format.\n\nResponse: {response_gen_response}")
                return {"response": result.content}

        def final_response(state: PlanExecute):
            """Handles the final response."""
            safe_write({"Node Name": "Final Response", "Status": "Started"})
            end_timestamp = get_timestamp()
            response = state['response']
            if not response and state.get('errors'):
                guardrail_resp = get_guardrail_response_from_errors(
                    state['errors'] if isinstance(state['errors'], list) else [state['errors']]
                )
                if guardrail_resp:
                    response = guardrail_resp
                    log.info("final_response: guardrail/moderation check triggered, returning policy alert to user.")
            response = response if response else "No plans to execute"
            final_response_message = AIMessage(content=response)
            safe_write({"raw": {"final_response": response}, "content": f"Final response generated successfully"})
            log.info(f"Final response generated")
            safe_write({"Node Name": "Final Response", "Status": "Completed"})
            return {"messages": final_response_message, "end_timestamp": end_timestamp}

        def check_plan_execution_status(state: PlanExecute):
            """Checks if all steps are executed."""
            safe_write({"content": f"Plan execution status: Step {state['step_idx']}/{len(state['plan'])}"})
            errors = state.get("errors", [])
            if errors and get_guardrail_response_from_errors(errors if isinstance(errors, list) else [errors]):
                return "response_generator_agent"
            if state["step_idx"] == len(state["plan"]):
                return "response_generator_agent"
            else:
                return "executor_agent_node"

        def route_non_planner_question(state: PlanExecute):
            """Routes based on plan availability."""
            if not state["plan"] or "STEP" not in state["plan"][0]:
                safe_write({"content": "No actionable plan generated, routing to final response"})
                return "final_response"
            else:
                safe_write({"content": f"Plan has {len(state['plan'])} steps, routing to executor"})
                return "executor_agent_node"

        # Build Graph
        workflow = StateGraph(PlanExecute)
        workflow.add_node("planner_agent", planner_agent)
        workflow.add_node("executor_agent_node", executor_agent_node)
        workflow.add_node("increment_step", increment_step)
        workflow.add_node("response_generator_agent", response_generator_agent)
        workflow.add_node("final_response", final_response)

        workflow.add_edge(START, "planner_agent")
        workflow.add_conditional_edges("planner_agent", route_non_planner_question, ["final_response", "executor_agent_node"])
        workflow.add_edge("executor_agent_node", "increment_step")
        workflow.add_conditional_edges("increment_step", check_plan_execution_status, ["executor_agent_node", "response_generator_agent"])
        workflow.add_edge("response_generator_agent", "final_response")
        workflow.add_edge("final_response", END)

        app = workflow.compile()
        log.info(f"Planner-Executor Agent created as Meta Agent Worker with streaming support.")
        return app, tool_list, writer_holder

    async def _get_react_critic_agent_as_worker_agent(self,
                                                      llm: Any,
                                                      system_prompts: str,
                                                      checkpointer: Any = None,
                                                      tool_ids: List[str] = [],
                                                      tool_versions: Dict[str, str] = None,
                                                      interrupt_tool: bool = False,
                                                      writer_holder: dict = None,
                                                      use_kafka_tool_worker: bool = False
                                                      ) -> Any:
        """
        Creates a react-critic agent as a meta agent worker with tools loaded dynamically.
        Supports streaming via writer_holder for real-time status updates.
        
        Args:
            llm: The language model to use
            system_prompts: Dictionary of system prompts for each agent role
            checkpointer: Optional checkpointer for state persistence
            tool_ids: List of tool IDs to load
            tool_versions: Optional dict mapping tool_id -> version (e.g., 'v1', 'v2')
            interrupt_tool: Whether to enable tool interruption
            writer_holder: A mutable dict that will hold the StreamWriter reference
        """
        
        # Initialize writer_holder if not provided
        if writer_holder is None:
            writer_holder = {"writer": None}
        
        # Helper function for safe streaming writes
        def safe_write(data):
            """Safely write to StreamWriter if available."""
            if writer_holder:
                writer = writer_holder.get("writer")
                if writer:
                    try:
                        writer(data)
                    except Exception as e:
                        log.warning(f"Failed to write to stream: {e}")

        # System Prompts
        executor_system_prompt = system_prompts.get("SYSTEM_PROMPT_EXECUTOR_AGENT", "")
        critic_system_prompt = system_prompts.get("SYSTEM_PROMPT_CRITIC_AGENT", "").replace("{", "{{").replace("}", "}}")

        # Agents and Chains
        executor_agent, tool_list, _ = await self._get_react_agent_as_executor_agent(
                                        llm,
                                        system_prompt=executor_system_prompt,
                                        checkpointer=checkpointer,
                                        tool_ids=tool_ids,
                                        tool_versions=tool_versions,  # Pass tool version mapping
                                        interrupt_tool=interrupt_tool,
                                        use_kafka_tool_worker=use_kafka_tool_worker
                                    )
        critic_chain_json, critic_chain_str = await self._get_chains(llm, critic_system_prompt)

        if not llm or not executor_agent or not critic_chain_json or not critic_chain_str:
            raise HTTPException(status_code=500, detail="Required chains or agent executor are missing")

        # State Schema
        class ReactCritic(TypedDict):
            query: str
            messages: Annotated[List[AnyMessage], add_messages]
            response: str
            response_quality_score: float
            critique_points: str
            epoch: int
            start_timestamp: datetime
            end_timestamp: datetime

        # Nodes
        async def executor_agent_node(state: ReactCritic):
            """Executes query using the react agent."""
            safe_write({"Node Name": "Executor Agent", "Status": "Started"})
            strt_tmstp = get_timestamp()
            query = state["messages"][0].content
            
            # Add critic feedback if available
            critic_context = ""
            if state.get("response_quality_score") is not None:
                critic_context = f"""
Previous Response:
{state["response"]}

Critic Score: {state["response_quality_score"]}
Critique Points: {await self.inference_utils.format_list_str(state["critique_points"]) if state.get("critique_points") else "No critique points"}

Please improve your response based on the feedback above.
"""
            
            formatted_query = f"{query}{critic_context}"
            safe_write({"content": f"Executing query: {query[:100]}..."})
            
            final_content_parts = []
            try:
              async for msg in executor_agent.astream({"messages": [("user", formatted_query.strip())]}):
                if isinstance(msg, dict) and "agent" in msg:
                    agent_output = msg.get("agent", {})
                    messages = []
                    if isinstance(agent_output, dict) and "messages" in agent_output:
                        messages = agent_output.get("messages", [])
                
                    for message in messages:
                        if hasattr(message, 'tool_calls') and message.tool_calls:
                            tool_call = message.tool_calls[0]
                            safe_write({"Node Name": "Tool Call", "Status": "Started", "Tool Name": tool_call['name'], "Tool Arguments": tool_call['args']})
                            tool_name = tool_call["name"]
                            tool_args = tool_call["args"]
                            if tool_args:
                                if isinstance(tool_args, dict):
                                    args_str = ", ".join(f"{k}={v}" for k, v in tool_args.items())
                                else:
                                    args_str = str(tool_args)
                                tool_call_content = f"Agent called the tool '{tool_name}', passing arguments: {args_str}."
                            else:
                                tool_call_content = f"Agent called the tool '{tool_name}', passing no arguments."
                            safe_write({"content": tool_call_content})
                        
                    final_content_parts.extend(messages)
                    
                elif "tools" in msg:
                    tool_messages = msg.get("tools", {})
                    messages_list = tool_messages.get("messages", [])
                    for tool_message in messages_list:
                        safe_write({"raw": {"Tool Name": tool_message.name, "Tool Output": tool_message.content}, "content": f"Tool {tool_message.name} returned: {tool_message.content}"})
                        if hasattr(tool_message, "name"):
                            safe_write({"Node Name": "Tool Call", "Status": "Completed", "Tool Name": tool_message.name})
                    final_content_parts.extend(messages_list)
                else:
                    if "agent" in msg:
                        final_content_parts.extend(msg["agent"]["messages"])
            except Exception as e:
              error = f"Error in Executor Agent: {e}"
              safe_write({"Node Name": "Executor Agent", "Status": "Failed"})
              log_guardrail_or_exception(error, e)
              guardrail_message = get_guardrail_response_from_exception(e)
              if guardrail_message:
                  return {"response": guardrail_message, "errors": [error]}
              return {"errors": [error]}
            
            if final_content_parts:
                last_msg = final_content_parts[-1]
                final_response = last_msg.content if hasattr(last_msg, 'content') else str(last_msg)
            else:
                final_response = ""
            
            log.info(f"Executor Agent generated response")
            safe_write({"Node Name": "Executor Agent", "Status": "Completed"})
            
            return_state = {
                "query": query,
                "response": final_response,
                "messages": final_content_parts if final_content_parts else [ChatMessage(content=final_response, role="executor")],
                "start_timestamp": strt_tmstp
            }
            
            # Initialize epoch if first run
            if state.get("epoch") is None:
                return_state["epoch"] = 0
                
            return return_state

        async def critic_agent(state: ReactCritic):
            """Evaluates the response quality."""
            safe_write({"Node Name": "Critic Agent", "Status": "Started"})
            formatted_query = f'''\
Tools Info:
{await self.tool_service.render_text_description_for_tools(tool_list)}

User Query:
{state["query"]}

Response:
{state["response"]}
'''
            invocation_input = {"messages": [("user", formatted_query)]}
            critic_response = await self.inference_utils.output_parser(
                                                            llm=llm,
                                                            chain_1=critic_chain_json,
                                                            chain_2=critic_chain_str,
                                                            invocation_input=invocation_input,
                                                            error_return_key="critique_points"
                                                        )

            if critic_response.get("critique_points") and isinstance(critic_response["critique_points"], list) and len(critic_response["critique_points"]) > 0 and "error" in str(critic_response["critique_points"][0]):
                critic_response = {'response_quality_score': 0, 'critique_points': critic_response["critique_points"]}
            
            safe_write({"raw": {"response_quality_score": critic_response["response_quality_score"], "critique_points": critic_response["critique_points"]}, "content": f"Response quality score: {critic_response['response_quality_score']}"})
            log.info(f"Critic Agent evaluated response with quality score: {critic_response['response_quality_score']}")
            safe_write({"Node Name": "Critic Agent", "Status": "Completed"})
            return {
                "response_quality_score": critic_response["response_quality_score"],
                "critique_points": critic_response["critique_points"],
                "messages": ChatMessage(
                    content=[{
                            "response_quality_score": critic_response["response_quality_score"],
                            "critique_points": critic_response["critique_points"]
                        }],
                    role="critic-response"
                ),
                "epoch": state["epoch"] + 1
            }

        def final_response(state: ReactCritic):
            """Handles the final response."""
            safe_write({"Node Name": "Final Response", "Status": "Started"})
            end_timestamp = get_timestamp()
            response = state['response']
            if not response and state.get('errors'):
                guardrail_resp = get_guardrail_response_from_errors(
                    state['errors'] if isinstance(state['errors'], list) else [state['errors']]
                )
                if guardrail_resp:
                    response = guardrail_resp
                    log.info("final_response: guardrail/moderation check triggered, returning policy alert to user.")
            response = response if response else "Unable to generate response"
            final_response_message = AIMessage(content=response)
            safe_write({"raw": {"final_response": response}, "content": f"Final response generated successfully"})
            log.info(f"Final response generated")
            safe_write({"Node Name": "Final Response", "Status": "Completed"})
            return {"messages": final_response_message, "end_timestamp": end_timestamp}

        def critic_decision(state: ReactCritic):
            """Decides whether to finalize or retry."""
            errors = state.get("errors", [])
            if errors and get_guardrail_response_from_errors(errors if isinstance(errors, list) else [errors]):
                return "final_response"
            decision = "final_response" if state["response_quality_score"] >= 0.7 or state["epoch"] >= 3 else "executor_agent_node"
            safe_write({"content": f"Critic decision: {decision} (score: {state['response_quality_score']}, epoch: {state['epoch']})"})
            if state["response_quality_score"] >= 0.7 or state["epoch"] >= 3:
                return "final_response"
            else:
                return "executor_agent_node"

        # Build Graph
        workflow = StateGraph(ReactCritic)
        workflow.add_node("executor_agent_node", executor_agent_node)
        workflow.add_node("critic_agent", critic_agent)
        workflow.add_node("final_response", final_response)

        workflow.add_edge(START, "executor_agent_node")
        workflow.add_edge("executor_agent_node", "critic_agent")
        workflow.add_conditional_edges("critic_agent", critic_decision, ["final_response", "executor_agent_node"])
        workflow.add_edge("final_response", END)

        app = workflow.compile()
        log.info(f"React-Critic Agent created as Meta Agent Worker with streaming support.")
        return app, tool_list, writer_holder

    # === Custom task-based handoff tool factory ===
    @staticmethod
    async def _create_agent_as_tool(*, agent_name: str, description: str = None, worker_agent: Any = None, writer_holder: dict = None) -> Any:
        """
        Creates a tool that delegates tasks to a specified agent.
        This tool can be used to hand off tasks to the specified agent based on the task description.
        
        Args:
            agent_name: Name of the worker agent
            description: Description for the tool
            worker_agent: The compiled worker agent graph
            writer_holder: A mutable dict that will hold the StreamWriter reference, 
                          set by the parent graph node before tool execution.
                          Example: {"writer": <StreamWriter instance>}
        """
        tool_description = description or f"Delegate task to {agent_name}"
        log.info(f"{agent_name} created as a tool for handoff.")

        @tool
        async def handoff_tool(
            task: Annotated[
                str,
                "Description of what the next agent should do, including all of the relevant context.",
            ],
        ) -> str:
            """Delegate subtask to agent based on task description."""
            log.info(f"Handoff tool '{agent_name}' invoked with task")
            
            # Get writer from the shared holder (set by parent node)
            writer = writer_holder.get("writer") if writer_holder else None
            
            def safe_write(data):
                """Safely write to StreamWriter if available."""
                if writer:
                    try:
                        writer(data)
                    except Exception as e:
                        log.warning(f"Failed to write to stream: {e}")
            
            try:
                final_content_parts = []
                final_response = None
                
                safe_write({"Node Name": f"Worker Agent: {agent_name} Thinking..", "Status": "Started"})
                
                async for msg in worker_agent.astream({"messages": [HumanMessage(content=task)]}):
                    log.debug(f"Worker agent '{agent_name}' streamed message keys: {msg.keys() if isinstance(msg, dict) else type(msg)}")
                    
                    # Handle react agent format (keys: "agent", "tools")
                    if isinstance(msg, dict) and "agent" in msg:
                        agent_output = msg.get("agent", {})
                        messages = []
                        if isinstance(agent_output, dict) and "messages" in agent_output:
                            messages = agent_output.get("messages", [])
                    
                        for message in messages:
                            safe_write({"raw": {"executor_agent": message.tool_calls}, "content": f"Agent is calling tools"})
                            # Handle tool calls
                            if hasattr(message, 'tool_calls') and message.tool_calls:
                                tool_call = message.tool_calls[0]
                                safe_write({"Node Name": "Tool Call", "Status": "Started", "Tool Name": tool_call['name'], "Tool Arguments": tool_call['args']})
                                tool_name = tool_call["name"]
                                tool_args = tool_call["args"]

                                if tool_args:   # Non-empty dict means arguments exist
                                    if isinstance(tool_args, dict):
                                        args_str = ", ".join(f"{k}={v}" for k, v in tool_args.items())
                                    else:
                                        args_str = str(tool_args)
                                    tool_call_content = f"Agent called the tool '{tool_name}', passing arguments: {args_str}."
                                else:
                                    tool_call_content = f"Agent called the tool '{tool_name}', passing no arguments."

                                safe_write({"content": tool_call_content})
                            
                            # Track the last message content for final response
                            if hasattr(message, 'content') and message.content:
                                final_response = message.content
                            
                        final_content_parts.extend(messages)
                        
                    elif isinstance(msg, dict) and "tools" in msg:
                        tool_messages = msg.get("tools", {})
                        messages_list = tool_messages.get("messages", [])
                        
                        for tool_message in messages_list:
                            safe_write({"raw": {"Tool Name": tool_message.name, "Tool Output": tool_message.content}, "content": f"Tool {tool_message.name} returned: {tool_message.content}"})
                            if hasattr(tool_message, "name"):
                                safe_write({"Node Name": "Tool Call", "Status": "Completed", "Tool Name": tool_message.name})
                        final_content_parts.extend(messages_list)
                    
                    # Handle custom workflow format (planner-executor-critic, planner-executor, react-critic)
                    # These emit messages with node names as keys: "planner_agent", "executor_agent_node", "final_response", etc.
                    elif isinstance(msg, dict) and "final_response" in msg:
                        # Extract final response from the final_response node
                        log.debug(f"Worker agent '{agent_name}' received final_response node output")
                        final_response_output = msg.get("final_response", {})
                        if isinstance(final_response_output, dict) and "messages" in final_response_output:
                            messages = final_response_output.get("messages")
                            log.debug(f"final_response messages type: {type(messages)}, value: {messages}")
                            if messages:
                                # Handle both single message and list of messages
                                last_msg = messages[-1] if isinstance(messages, list) else messages
                                if hasattr(last_msg, 'content') and last_msg.content:
                                    final_response = last_msg.content
                                    log.debug(f"Extracted final_response content: {final_response[:100] if final_response else 'None'}...")
                                elif isinstance(last_msg, str):
                                    final_response = last_msg
                                final_content_parts.extend(messages if isinstance(messages, list) else [messages])
                    
                    elif isinstance(msg, dict):
                        # Handle other node outputs from custom workflows
                        # Look for any node that has a "messages" key with content or "response" key
                        for node_name, node_output in msg.items():
                            if isinstance(node_output, dict) and "messages" in node_output:
                                messages = node_output.get("messages", [])
                                if messages:
                                    if isinstance(messages, list):
                                        for message in messages:
                                            if hasattr(message, 'content') and message.content:
                                                final_response = message.content
                                        final_content_parts.extend(messages)
                                    else:
                                        if hasattr(messages, 'content') and messages.content:
                                            final_response = messages.content
                                        final_content_parts.append(messages)
                            
                            # Also check for "response" key directly in node output
                            if isinstance(node_output, dict) and "response" in node_output:
                                response_val = node_output.get("response")
                                if response_val and isinstance(response_val, str):
                                    final_response = response_val
                                    log.debug(f"Found response in node '{node_name}': {response_val[:100] if response_val else 'None'}...")
                            
                safe_write({"Node Name": f"Worker Agent: {agent_name} Thinking..", "Status": "Completed"})
                
                log.debug(f"Worker agent '{agent_name}' final_response: {final_response[:100] if final_response else 'None'}, final_content_parts count: {len(final_content_parts)}")
                
                # Return the final response from streaming
                if final_response:
                    return final_response
                elif final_content_parts:
                    # Get content from last message if available
                    last_msg = final_content_parts[-1]
                    if hasattr(last_msg, 'content'):
                        return last_msg.content
                    return str(last_msg)
                else:
                    return f"Worker agent '{agent_name}' completed but returned no response."

            except Exception as e:
                log_guardrail_or_exception(f"Error during streaming execution of worker agent '{agent_name}': {e}", e)
                safe_write({"Node Name": f"Worker Agent: {agent_name} Thinking..", "Status": "Failed"})
                raise
        
        handoff_tool.name = agent_name
        handoff_tool.description = tool_description

        return handoff_tool

    async def _get_react_agent_as_supervisor_agent(self,
                                                   llm: Any,
                                                   system_prompt: str,
                                                   checkpointer: Any = None,
                                                   worker_agent_ids: List[str] = [],
                                                   interrupt_tool: bool = False,
                                                   file_context_management_flag: bool = False,
                                                   agent_id: str = None,
                                                   session_id: str = None,
                                                   additional_paths: list = None,
                                                   allowed_absolute_mount_roots: list = None,
                                                   use_kafka_tool_worker: bool = False
                                                   ) -> Any:
        """
        Helper method to create a React agent as a supervisor or meta agent with agents loaded dynamically.
        
        Args:
            file_context_management_flag: If True, use file-based shell tools instead of DB memory tools.
            agent_id: Agent ID for shell workspace (required if file_context_management_flag=True).
            session_id: Session ID for shell workspace (required if file_context_management_flag=True).
            use_kafka_tool_worker: If True, wraps sub-agent tools for Kafka-based remote execution.
        
        Returns:
            tuple: (supervisor_agent, worker_agents_as_tools_list, writer_holder)
                   The writer_holder dict should have its "writer" key set by the parent 
                   graph node before tool execution to enable streaming.
        """
        log.info(f"Creating supervisor agent with worker_agent_ids: {worker_agent_ids}, file_context_management_flag: {file_context_management_flag}, use_kafka_tool_worker: {use_kafka_tool_worker}")
        worker_agents_as_tools_list = []
        # Shared holder for StreamWriter - will be set by the meta agent node
        writer_holder = {"writer": None}
        
        # Add memory tools based on file_context_management_flag
        # Also load shell tools when mount paths are configured (independent of
        # file_context_management_flag), so agents can actually access mounts.
        _has_mounts = bool(additional_paths) or bool(allowed_absolute_mount_roots)
        _needs_shell = (file_context_management_flag or _has_mounts) and bool(agent_id) and bool(session_id)
        if _needs_shell:
            # Use file-based AgentShell tools
            try:
                from src.memory.agent_shell.tools import get_shell_tools_for_session
                from src.utils.secrets_handler import current_user_email
                
                user_email = current_user_email.get(None)
                user_department = current_user_department.get("General")
                
                agent_shell, shell_tools = get_shell_tools_for_session(
                    agent_id=agent_id,
                    session_id=session_id,
                    user_email=user_email,
                    workspace_root="./agent_workspaces",
                    department=user_department,
                    additional_paths=additional_paths,
                    allowed_absolute_mount_roots=allowed_absolute_mount_roots,
                )
                worker_agents_as_tools_list.extend(shell_tools)
                log.info(
                    f"✅ AgentShell loaded for meta/supervisor agent: user={user_email}, "
                    f"agent={str(agent_id)[:12]}... "
                    f"(file_context={file_context_management_flag}, mounts={_has_mounts})"
                )
            except Exception as e:
                log.warning(f"Failed to load AgentShell for meta agent, falling back to DB memory: {e}")
                # Fallback to DB memory tools
                manage_memory_tool = await self.inference_utils.create_manage_memory_tool()
                worker_agents_as_tools_list.append(manage_memory_tool)
                search_memory_tool = await self.inference_utils.create_search_memory_tool(
                    embedding_model=self.inference_utils.embedding_model
                )
                worker_agents_as_tools_list.append(search_memory_tool)
        else:
            # Use traditional DB memory tools
            manage_memory_tool = await self.inference_utils.create_manage_memory_tool()
            worker_agents_as_tools_list.append(manage_memory_tool)

            search_memory_tool = await self.inference_utils.create_search_memory_tool(
                embedding_model=self.inference_utils.embedding_model
            )
            worker_agents_as_tools_list.append(search_memory_tool)

        for worker_agent_id in worker_agent_ids:
            worker_agent_config = await self._get_agent_config(agentic_application_id=worker_agent_id)

            worker_agent_type = worker_agent_config["AGENT_TYPE"]
            worker_agent_description = worker_agent_config.get("AGENT_DESCRIPTION")
            worker_agent_system_prompt = worker_agent_config.get("SYSTEM_PROMPT")
            worker_agent_tool_ids = worker_agent_config.get("TOOLS_INFO")
            worker_agent_tool_versions = worker_agent_config.get("TOOLS_WITH_VERSIONS", {})  # Get tool versions
            worker_agent_name = worker_agent_config.get("AGENT_NAME")
            worker_agent_name = await self.agent_service.agent_service_utils._normalize_agent_name(worker_agent_name)

            if worker_agent_type == AgentType.REACT_AGENT:
                worker_agent, _, _ = await self._get_react_agent_as_executor_agent(
                                        llm=llm,
                                        system_prompt=worker_agent_system_prompt.get("SYSTEM_PROMPT_REACT_AGENT", ""),
                                        tool_ids=worker_agent_tool_ids,
                                        tool_versions=worker_agent_tool_versions,
                                        use_kafka_tool_worker=use_kafka_tool_worker
                                    )
                log.info(f"Worker agent '{worker_agent_name}' of type REACT_AGENT created for supervisor/meta agent.")
            elif worker_agent_type == AgentType.PLANNER_EXECUTOR_CRITIC_AGENT:
                worker_agent, _, _ = await self._get_planner_executor_critic_agent_as_worker_agent(
                    llm=llm,
                    system_prompts=worker_agent_system_prompt,
                    tool_ids=worker_agent_tool_ids,
                    tool_versions=worker_agent_tool_versions,
                    writer_holder=writer_holder,
                    use_kafka_tool_worker=use_kafka_tool_worker
                )
                log.info(f"Worker agent '{worker_agent_name}' of type PLANNER_EXECUTOR_CRITIC_AGENT created for supervisor/meta agent.")
            elif worker_agent_type == AgentType.PLANNER_EXECUTOR_AGENT:
                worker_agent, _, _ = await self._get_planner_executor_agent_as_worker_agent(
                    llm=llm,
                    system_prompts=worker_agent_system_prompt,
                    tool_ids=worker_agent_tool_ids,
                    tool_versions=worker_agent_tool_versions,
                    writer_holder=writer_holder,
                    use_kafka_tool_worker=use_kafka_tool_worker
                )
                log.info(f"Worker agent '{worker_agent_name}' of type PLANNER_EXECUTOR_AGENT created for supervisor/meta agent.")
            elif worker_agent_type == AgentType.REACT_CRITIC_AGENT:
                worker_agent, _, _ = await self._get_react_critic_agent_as_worker_agent(
                    llm=llm,
                    system_prompts=worker_agent_system_prompt,
                    tool_ids=worker_agent_tool_ids,
                    tool_versions=worker_agent_tool_versions,
                    writer_holder=writer_holder,
                    use_kafka_tool_worker=use_kafka_tool_worker
                )
                log.info(f"Worker agent '{worker_agent_name}' of type REACT_CRITIC_AGENT created for supervisor/meta agent.")
            else:
                err = f"Meta agent does not support worker agent of type '{worker_agent_type}' yet."
                log.error(err)
                raise HTTPException(status_code=501, detail=err)

            worker_agents_as_tools_list.append(
                await self._create_agent_as_tool(
                    agent_name=worker_agent_name,
                    description=worker_agent_description,
                    worker_agent=worker_agent,
                    writer_holder=writer_holder
                )
            )

        log.debug(f"{worker_agents_as_tools_list}:: tools created for supervisor/meta agent")

        try:
            interrupt_before = ["tools"] if interrupt_tool and worker_agents_as_tools_list else None
            supervisor_agent = create_react_agent(
                model=llm,
                prompt=system_prompt,
                tools=worker_agents_as_tools_list,
                interrupt_before=interrupt_before,
                checkpointer=checkpointer
            )
            return supervisor_agent, worker_agents_as_tools_list, writer_holder

        except Exception as e:
            log.error(f"Error occurred while creating meta agent: {e}")
            raise HTTPException(status_code=500, detail=f"Error occurred while creating meta agent\nError: {e}")

