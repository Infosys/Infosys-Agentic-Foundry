"""
Smart Code Executor — Phase 5 of AgentOS integration.

Goal-driven code execution service:
  English goal → LLM generates code → sandboxed execution → auto-retry on failure → cached results

Components:
  - SmartCodeExecutor: Core orchestrator
  - SubprocessBackend: Safe subprocess execution
  - LLMCodeGenerator: LLM-powered code generation using IAF models
  - CacheManager: Two-layer LRU cache (goal→code, goal→result)
  - TaskManager: Async task queue with polling
  - ErrorAnalyzer: Classifies errors for auto-recovery

Author: AgentOS Integration (Phase 5)
"""

from src.agentos.code_executor.models import (
    TaskResult,
    ExecutionResult,
    TaskStatus,
    Task,
    ErrorAnalysis,
)
from src.agentos.code_executor.config import CodeExecutorConfig
from src.agentos.code_executor.executor import SmartCodeExecutor

__all__ = [
    "SmartCodeExecutor",
    "CodeExecutorConfig",
    "TaskResult",
    "ExecutionResult",
    "TaskStatus",
    "Task",
    "ErrorAnalysis",
]
