# © 2024-25 Infosys Limited, Bangalore, India. All Rights Reserved.
"""
Phoenix Project Manager - Handles efficient project registration for Arize Phoenix tracing.
Prevents duplicate registrations and manages project lifecycle.

CRITICAL: This module addresses trace mixing issues in concurrent environments.
"""

import threading
import contextvars
from typing import Set, Optional
from contextlib import asynccontextmanager, contextmanager
from phoenix.otel import register
from phoenix.trace import using_project
from opentelemetry import trace
from telemetry_wrapper import logger as log

# Context variable to store the current project name per async task
_current_project: contextvars.ContextVar[Optional[str]] = contextvars.ContextVar(
    'phoenix_current_project', 
    default=None
)


class PhoenixProjectManager:
    """
    Singleton manager for Phoenix project registration.
    Ensures each project is only registered once to avoid performance overhead.
    """
    _instance = None
    _lock = threading.Lock()
    
    def __new__(cls):
        with cls._lock:
            if cls._instance is None:
                cls._instance = super(PhoenixProjectManager, cls).__new__(cls)
                cls._instance._initialized = False
        return cls._instance
    
    def __init__(self):
        # Double-checked locking to ensure thread-safe singleton initialization
        if self._initialized:
            return
        with self.__class__._lock:
            if self._initialized:
                return
            self._registered_projects: Set[str] = set()
            self._project_lock = threading.Lock()
            self._initialized = True
            log.info("PhoenixProjectManager initialized")
    
    def register_project(self, project_name: str, auto_instrument: bool = True, 
                        set_global_tracer_provider: bool = False, batch: bool = True) -> bool:
        """
        Register a Phoenix project if it hasn't been registered yet.
        
        Args:
            project_name: Name of the project to register
            auto_instrument: Enable automatic instrumentation
            set_global_tracer_provider: Set as global tracer (usually False)
            batch: Enable batch export
            
        Returns:
            bool: True if newly registered, False if already registered
        """
        with self._project_lock:
            if project_name in self._registered_projects:
                log.debug(f"[Phoenix] Project '{project_name}' already registered, skipping")
                return False
            
            try:
                log.info(f"[Phoenix] Registering new Phoenix project: '{project_name}'")
                register(
                    project_name=project_name,
                    auto_instrument=auto_instrument,
                    set_global_tracer_provider=set_global_tracer_provider,
                    batch=batch
                )
                self._registered_projects.add(project_name)
                log.info(f"[Phoenix] Successfully registered Phoenix project: '{project_name}'")
                return True
            
            except Exception as e:
                log.error(f"[Phoenix] Failed to register Phoenix project '{project_name}': {e}", exc_info=True)
                raise
    
    def is_registered(self, project_name: str) -> bool:
        """Check if a project is already registered."""
        with self._project_lock:
            return project_name in self._registered_projects
    
    def get_registered_projects(self) -> Set[str]:
        """Get a copy of all registered project names."""
        with self._project_lock:
            return self._registered_projects.copy()
    
    def clear_registry(self):
        """
        Clear the registration cache.
        WARNING: Only use for testing or during shutdown.
        Does not actually unregister projects from Phoenix.
        """
        with self._project_lock:
            log.warning("Clearing Phoenix project registry")
            self._registered_projects.clear()


# Global singleton instance
phoenix_manager = PhoenixProjectManager()


def ensure_project_registered(project_name: str, **kwargs) -> None:
    """
    Ensure a Phoenix project is registered, registering if needed.
    """
    phoenix_manager.register_project(project_name, **kwargs)


@asynccontextmanager
async def traced_project_context(project_name: str):
    """
    Async context manager for Phoenix tracing with proper context isolation.
    
    This ensures traces don't mix between concurrent requests by:
    1. Setting the project name in a ContextVar (async-safe)
    2. Using Phoenix's using_project context manager
    3. Capturing the current OpenTelemetry context
    4. Properly propagating context through async operations
    
    Usage:
        async with traced_project_context(project_name):
            # All traced operations here belong to project_name
            response = await agent.run(query)
    
    WHY THIS FIXES TRACE MIXING:
    - ContextVar is task-local, not thread-local (works with asyncio)
    - Each async task gets isolated project context
    - Prevents context leakage between concurrent async tasks
    """
    # Store the project name in context variable (task-local isolation)
    project_token = _current_project.set(project_name)
    
    try:
        log.debug(f"[Phoenix] Starting traced context for project: '{project_name}'")
        
        # Use Phoenix's project context manager
        with using_project(project_name):
            yield
        
        log.debug(f"[Phoenix] Completed traced context for project: '{project_name}'")
    
    except Exception as e:
        log.error(f"[Phoenix] Error in traced context for project '{project_name}': {e}", exc_info=True)
        raise
    
    finally:
        # Reset the project context variable
        try:
            _current_project.reset(project_token)
        except ValueError as e:
            # Can occur if context was already reset (e.g., during streaming task transitions)
            log.debug(f"[Phoenix] Project context already cleaned up (expected during streaming): {e}")


@contextmanager
def traced_project_context_sync(project_name: str):
    """
    Synchronous context manager for Phoenix tracing (for sync code paths).
    
    Usage:
        with traced_project_context_sync(project_name):
            # All traced operations here belong to project_name
            response = agent.run(query)
    """
    project_token = _current_project.set(project_name)
    
    try:
        log.debug(f"[Phoenix] Starting traced context (sync) for project: '{project_name}'")
        
        with using_project(project_name):
            yield
        
        log.debug(f"[Phoenix] Completed traced context (sync) for project: '{project_name}'")
    
    except Exception as e:
        log.error(f"[Phoenix] Error in traced context (sync) for project '{project_name}': {e}", exc_info=True)
        raise
    
    finally:
        # Reset the project context variable
        try:
            _current_project.reset(project_token)
        except ValueError as e:
            # Can occur if context was already reset (e.g., during sync generator operations)
            log.debug(f"[Phoenix] Project context already cleaned up in sync (expected in some cases): {e}")


def get_current_project() -> Optional[str]:
    """
    Get the current Phoenix project name from context.
    
    Returns:
        The current project name, or None if not in a traced context.
    
    Usage:
        project = get_current_project()
        if project:
            log.info(f"Currently tracing to project: {project}")
    """
    return _current_project.get()


def log_trace_context(operation: str):
    """
    Log current trace context for debugging trace mixing issues.
    
    This is a DEBUGGING HELPER that logs:
    - Current operation name
    - Phoenix project name
    - OpenTelemetry span validity
    - Trace ID (if valid)
    
    WHY YOU NEED THIS:
    When traces are mixing between users, you can use this function
    to see EXACTLY which project and trace ID is active at different
    points in your code. This helps identify WHERE the context is
    being lost or mixed.
    
    Args:
        operation: A descriptive name for where you're logging from
                   (e.g., "before_agent_invocation", "after_tool_call")
    
    Usage:
        # At critical points in your code:
        log_trace_context("before_agent_invocation")
        await agent.run(query)
        log_trace_context("after_agent_invocation")
    
    Example Output:
        [Phoenix] Trace Context - Operation: before_agent_invocation, 
                  Project: CustomerAgent_user@example.com, 
                  Span Valid: True, 
                  Trace ID: 1234abcd5678ef90...
    
    DEBUGGING TRACE MIXING:
    If you see traces mixing, add this at multiple points and look for:
    - Project name changing unexpectedly
    - Trace ID changing mid-request
    - Span becoming invalid
    """
    project = get_current_project()
    span = trace.get_current_span()
    span_context = span.get_span_context() if span else None
    
    log.debug(
        f"[Phoenix] Trace Context - Operation: {operation}, "
        f"Project: {project}, "
        f"Span Valid: {span_context.is_valid if span_context else False}, "
        f"Trace ID: {format(span_context.trace_id, '032x') if span_context and span_context.is_valid else 'N/A'}"
    )
