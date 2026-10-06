"""
SmartCodeExecutor — Core orchestrator for goal-driven code execution.

Flow:
  Goal → Detect Language → Check Cache → LLM Code Generation
    → Sandboxed Execution → Error? → Analyze → Install Package / LLM Fix / Retry
    → Cache Result → Return

Supports:
  - Sync and async execution modes
  - Automatic error recovery (package install + LLM code fixing)
  - Two-layer caching (goal→code, goal→result)
  - Multi-tenant workspace isolation
  - Direct code execution (bypass LLM)
"""

import asyncio
import logging
import os
import re
import shutil
import time
from pathlib import Path
from typing import Any, Dict, List, Optional
import uuid

from src.agentos.code_executor.cache import CacheManager
from src.agentos.code_executor.config import CodeExecutorConfig
from src.agentos.code_executor.execution import ErrorAnalyzer, SubprocessBackend
from src.agentos.code_executor.llm_codegen import LLMCodeGenerator
from src.agentos.code_executor.models import (
    ErrorType,
    ExecutionResult,
    RecoveryAction,
    TaskResult,
    TaskStatus,
)
from src.agentos.code_executor.task_manager import TaskManager

logger = logging.getLogger("agentos.code_executor")


class SmartCodeExecutor:
    """
    Goal-driven code execution engine.

    Takes an English-language goal, generates code via LLM, executes it
    safely in a subprocess, auto-recovers from errors, and caches results.
    """

    def __init__(self, config: Optional[CodeExecutorConfig] = None, llm: Optional[object] = None):
        """
        Args:
            config: Configuration. Uses defaults if None.
            llm: Optional pre-built LangChain chat model for code generation.
                 If None, the LLMCodeGenerator will use IAF's model service.
        """
        self.config = config or CodeExecutorConfig()

        # Components
        self._backend = SubprocessBackend(self.config)
        self._codegen = LLMCodeGenerator(self.config.llm, llm=llm)
        self._cache = CacheManager(self.config.cache)
        self._task_manager: Optional[TaskManager] = None
        self._initialized = False

        # Workspace
        self._workspace_base = Path(self.config.workspace.base_path)
        self._outputs_base = Path(self.config.output.outputs_base_path)

    async def initialize(self):
        """Initialize async components (task manager workers)."""
        if self._initialized:
            return

        # Ensure base directories exist
        self._workspace_base.mkdir(parents=True, exist_ok=True)
        self._outputs_base.mkdir(parents=True, exist_ok=True)

        # Start task manager if async is enabled
        if self.config.async_config.enabled:
            self._task_manager = TaskManager(
                config=self.config.async_config,
                executor_func=self._execute_task_internal,
            )
            await self._task_manager.start()

        self._initialized = True
        logger.info("SmartCodeExecutor initialized")

    async def shutdown(self):
        """Gracefully shut down async workers."""
        if self._task_manager:
            await self._task_manager.stop()
        self._initialized = False
        logger.info("SmartCodeExecutor shut down")

    # ===================================================================
    # Public API: Execute Task (Goal → Code → Result)
    # ===================================================================

    async def execute_task(
        self,
        goal: str,
        tenant_id: str = "default",
        files: Optional[Dict[str, str]] = None,
        language: Optional[str] = None,
        async_mode: bool = False,
        use_cache: bool = True,
    ) -> Dict[str, Any]:
        """
        Execute a goal-driven task.

        Args:
            goal: Natural-language description of what to accomplish.
            tenant_id: Tenant identifier for workspace isolation.
            files: Optional dict of filename → content to place in workspace.
            language: Programming language hint (auto-detected if None).
            async_mode: If True, returns a task_id for polling.
            use_cache: Whether to check/populate caches.

        Returns:
            Dict with execution results or task_id (async mode).
        """
        if not self._initialized:
            await self.initialize()

        # Async mode: submit to task manager
        if async_mode:
            if not self._task_manager:
                return {
                    "success": False,
                    "error": "Async execution is not enabled",
                }
            task = await self._task_manager.submit_task(
                goal=goal, tenant_id=tenant_id, files=files, language=language
            )
            return {
                "success": True,
                "async": True,
                "task_id": task.task_id,
                "status": task.status.value,
                "message": "Task queued for async execution. Poll /task/{task_id} for status.",
            }

        # Sync mode: execute immediately
        result = await self._execute_task_internal(
            goal=goal,
            tenant_id=tenant_id,
            files=files,
            language=language,
            use_cache=use_cache,
        )
        return result.to_dict()

    # ===================================================================
    # Public API: Execute Direct Code (bypass LLM)
    # ===================================================================

    async def execute_code(
        self,
        code: str,
        language: str = "python",
        tenant_id: str = "default",
    ) -> Dict[str, Any]:
        """
        Execute exact code (no LLM generation).

        Args:
            code: Source code to execute.
            language: Programming language.
            tenant_id: Tenant identifier.

        Returns:
            Dict with execution results.
        """
        if not self._initialized:
            await self.initialize()

        workspace = self._get_workspace(tenant_id, str(uuid.uuid4()))

        try:
            result = await self._backend.execute(
                code=code,
                language=language,
                workspace=workspace,
                timeout=self.config.execution.timeout_per_attempt,
            )

            # Collect output files
            output_files = self._collect_output_files(workspace, result.files_created)

            return TaskResult(
                success=result.success,
                result=result.output,
                error=result.error,
                code=code,
                language=language,
                files_created=output_files,
                execution_time_ms=result.execution_time_ms,
                cached=False,
                attempts=1,
            ).to_dict()

        finally:
            self._cleanup_workspace(workspace)

    # ===================================================================
    # Public API: Task Management
    # ===================================================================

    async def get_task_status(self, task_id: str, tenant_id: Optional[str] = None) -> Optional[Dict]:
        if self._task_manager:
            return await self._task_manager.get_status(task_id, tenant_id)
        return None

    async def cancel_task(self, task_id: str, tenant_id: Optional[str] = None) -> bool:
        if self._task_manager:
            return await self._task_manager.cancel_task(task_id, tenant_id)
        return False

    def list_tasks(self, tenant_id: Optional[str] = None) -> List[Dict]:
        if self._task_manager:
            return self._task_manager.list_tasks(tenant_id)
        return []

    # ===================================================================
    # Public API: Health & Capabilities
    # ===================================================================

    async def health_check(self) -> Dict[str, Any]:
        llm_ok = await self._codegen.is_available()
        return {
            "status": "healthy" if llm_ok else "degraded",
            "components": {
                "llm": "ok" if llm_ok else "unavailable",
                "execution_backend": "ok",  # subprocess is always available
                "cache": self._cache.stats(),
            },
        }

    def get_capabilities(self) -> Dict[str, Any]:
        return {
            "languages": list(self._backend._interpreters.keys()),
            "features": {
                "async_execution": self.config.async_config.enabled,
                "caching": self.config.cache.enabled,
                "auto_recovery": True,
                "package_install": self.config.auto_recovery.install_packages,
            },
            "limits": {
                "timeout_per_attempt": self.config.execution.timeout_per_attempt,
                "total_timeout": self.config.execution.total_timeout,
                "max_attempts": self.config.execution.max_attempts,
                "max_result_length": self.config.output.max_result_length,
            },
        }

    # ===================================================================
    # Internal: Task Execution Pipeline
    # ===================================================================

    async def _execute_task_internal(
        self,
        goal: str,
        tenant_id: str = "default",
        files: Optional[Dict[str, str]] = None,
        language: Optional[str] = None,
        use_cache: bool = True,
    ) -> TaskResult:
        """Core execution pipeline: detect lang → cache → generate → execute → retry → cache."""

        total_start = time.perf_counter()
        task_id = str(uuid.uuid4())

        # 1. Detect language
        if not language:
            language = self._detect_language(goal)

        # 2. Check result cache
        if use_cache:
            cached = self._cache.get_cached_result(goal, language, files)
            if cached:
                cached["cached"] = True
                return TaskResult(**cached)

        # 3. Create workspace and write input files
        workspace = self._get_workspace(tenant_id, task_id)
        try:
            if files:
                for fname, fcontent in files.items():
                    fpath = Path(workspace) / fname
                    fpath.parent.mkdir(parents=True, exist_ok=True)
                    fpath.write_text(fcontent, encoding="utf-8")

            # 4. Build context from files
            context = self._build_context(files, language)

            # 5. Get or generate code
            code = None
            if use_cache:
                code = self._cache.get_cached_code(goal, language)

            if not code:
                try:
                    code = await self._codegen.generate_code(
                        goal=goal, language=language, context=context
                    )
                    if use_cache:
                        self._cache.cache_code(goal, language, code)
                except Exception as exc:
                    elapsed = (time.perf_counter() - total_start) * 1000
                    return TaskResult(
                        success=False,
                        error=f"Code generation failed: {exc}",
                        language=language,
                        execution_time_ms=elapsed,
                        attempts=0,
                    )

            # 6. Execute with retries
            exec_result, final_code, attempts = await self._execute_with_retries(
                code=code,
                language=language,
                workspace=workspace,
                goal=goal,
            )

            # 7. Collect output artifacts
            output_files = self._collect_output_files(workspace, exec_result.files_created)
            elapsed = (time.perf_counter() - total_start) * 1000

            # 8. Truncate long output
            output = exec_result.output
            if len(output) > self.config.output.max_result_length:
                if self.config.output.summarize_long_results:
                    output = (
                        output[: self.config.output.max_result_length // 2]
                        + "\n\n... [output truncated] ...\n\n"
                        + output[-self.config.output.max_result_length // 2:]
                    )
                else:
                    output = output[: self.config.output.max_result_length]

            result = TaskResult(
                success=exec_result.success,
                result=output,
                error=exec_result.error,
                code=final_code,
                language=language,
                files_created=output_files,
                execution_time_ms=elapsed,
                cached=False,
                attempts=attempts,
            )

            # 9. Cache successful results
            if exec_result.success and use_cache:
                self._cache.cache_result(goal, language, result.to_dict(), files)

            return result

        finally:
            if self.config.workspace.cleanup_policy == "after_task":
                self._cleanup_workspace(workspace)

    # ===================================================================
    # Internal: Retry Loop
    # ===================================================================

    async def _execute_with_retries(
        self,
        code: str,
        language: str,
        workspace: str,
        goal: str,
    ) -> tuple:  # (ExecutionResult, final_code, attempt_count)
        """
        Execute code with automatic error recovery.

        Recovery actions:
          - install_package: auto-pip/npm install, doesn't count as attempt
          - fix_code: ask LLM to rewrite code, counts as attempt
          - retry: re-execute unchanged code, counts as attempt
          - abort: stop immediately

        Returns:
            Tuple of (ExecutionResult, final_code_string, attempt_count)
        """
        max_attempts = self.config.execution.max_attempts
        total_timeout = self.config.execution.total_timeout
        total_start = time.perf_counter()
        installed_packages: set = set()
        current_code = code
        attempts = 0

        for attempt in range(max_attempts):
            # Check total timeout
            elapsed = time.perf_counter() - total_start
            if elapsed > total_timeout:
                return (
                    ExecutionResult(
                        success=False,
                        error=f"Total timeout ({total_timeout}s) exceeded after {attempts} attempts",
                        execution_time_ms=elapsed * 1000,
                    ),
                    current_code,
                    attempts,
                )

            # Execute
            remaining_time = min(
                self.config.execution.timeout_per_attempt,
                total_timeout - elapsed,
            )
            result = await self._backend.execute(
                code=current_code,
                language=language,
                workspace=workspace,
                timeout=int(remaining_time),
            )
            attempts += 1

            # Success!
            if result.success:
                return result, current_code, attempts

            # Analyze error
            analysis = ErrorAnalyzer.analyze(result.error, language)
            logger.info(
                f"Attempt {attempts}/{max_attempts}: {analysis.error_type.value} → "
                f"{analysis.action.value} (recoverable={analysis.recoverable})"
            )

            if not analysis.recoverable:
                return result, current_code, attempts

            # --- Recovery actions ---

            if analysis.action == RecoveryAction.INSTALL_PACKAGE and analysis.package_name:
                pkg = analysis.package_name
                if pkg in installed_packages:
                    # Already tried installing this — fall through to fix_code
                    analysis.action = RecoveryAction.FIX_CODE
                else:
                    logger.info(f"Auto-installing package: {pkg}")
                    install_result = await self._backend.install_package(
                        package=pkg, language=language, workspace=workspace
                    )
                    installed_packages.add(pkg)
                    if install_result.success:
                        # Don't count install as attempt — retry immediately
                        attempts -= 1
                        continue
                    else:
                        logger.warning(f"Package install failed for {pkg}: {install_result.error}")
                        # Fall through to fix_code

            if analysis.action == RecoveryAction.FIX_CODE:
                try:
                    fixed_code = await self._codegen.fix_code(
                        code=current_code,
                        error=result.error,
                        goal=goal,
                        language=language,
                    )
                    if fixed_code and fixed_code != current_code:
                        current_code = fixed_code
                        logger.info(f"Code fixed by LLM ({len(fixed_code)} chars)")
                    else:
                        logger.warning("LLM returned identical code — no fix possible")
                except Exception as exc:
                    logger.warning(f"LLM fix failed: {exc}")

            elif analysis.action == RecoveryAction.RETRY:
                # Simple retry (e.g., timeout) — no code change
                logger.info("Retrying unchanged code...")

            elif analysis.action == RecoveryAction.ABORT:
                return result, current_code, attempts

        # Exhausted all attempts
        return result, current_code, attempts

    # ===================================================================
    # Internal: Language Detection
    # ===================================================================

    @staticmethod
    def _detect_language(goal: str) -> str:
        """Detect programming language from goal keywords."""
        goal_lower = goal.lower()

        js_keywords = [
            "javascript", "node", "npm", "react", "express",
            "typescript", "webpack", "jquery", "dom", "html",
        ]
        if any(kw in goal_lower for kw in js_keywords):
            return "javascript"

        bash_keywords = [
            "bash", "shell", "terminal", "command line", "cli",
            "grep", "awk", "sed", "curl", "wget",
        ]
        if any(kw in goal_lower for kw in bash_keywords):
            return "bash"

        return "python"  # Default

    # ===================================================================
    # Internal: Context Building
    # ===================================================================

    @staticmethod
    def _build_context(
        files: Optional[Dict[str, str]], language: str
    ) -> str:
        """Build context string from input files for the LLM."""
        if not files:
            return ""

        parts = ["Available files in the workspace:"]
        for fname, content in files.items():
            preview = content[:1000]
            if len(content) > 1000:
                preview += f"\n... ({len(content)} total chars)"
            parts.append(f"\n--- {fname} ---\n{preview}")

        return "\n".join(parts)

    # ===================================================================
    # Internal: Workspace Management
    # ===================================================================

    def _get_workspace(self, tenant_id: str, task_id: str) -> str:
        """Get or create workspace directory for a task."""
        ws = self._workspace_base / tenant_id / task_id
        ws.mkdir(parents=True, exist_ok=True)
        return str(ws)

    def _cleanup_workspace(self, workspace: str):
        """Remove workspace directory."""
        try:
            ws_path = Path(workspace)
            if ws_path.exists():
                shutil.rmtree(ws_path, ignore_errors=True)
        except Exception as exc:
            logger.warning(f"Workspace cleanup failed: {exc}")

    def _collect_output_files(self, workspace: str, new_files: List[str]) -> List[str]:
        """
        Copy output files from workspace to persistent outputs directory.
        Returns list of output file paths.
        """
        if not new_files:
            return []

        collected = []
        ws_path = Path(workspace)

        for fname in new_files:
            src = ws_path / fname
            if not src.exists() or not src.is_file():
                continue

            # Check file size
            size_mb = src.stat().st_size / (1024 * 1024)
            if size_mb > self.config.output.max_output_size_mb:
                logger.warning(f"Output file too large: {fname} ({size_mb:.1f}MB)")
                continue

            # Check allowed extensions
            ext = src.suffix.lower()
            if self.config.output.allowed_output_extensions and ext not in self.config.output.allowed_output_extensions:
                # Still include it but warn
                logger.debug(f"Output file extension not in allowed list: {ext}")

            # Copy to outputs directory
            try:
                task_output_dir = self._outputs_base / ws_path.parts[-1]  # task_id
                task_output_dir.mkdir(parents=True, exist_ok=True)
                dst = task_output_dir / fname
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(str(src), str(dst))
                collected.append(str(dst))
            except Exception as exc:
                logger.warning(f"Could not collect output file {fname}: {exc}")
                collected.append(fname)  # Return relative path as fallback

        return collected
