"""
Execution backend (subprocess) and error analysis for Smart Code Executor.

SubprocessBackend: Writes code to temp file → runs via asyncio subprocess → captures output.
ErrorAnalyzer: Classifies execution errors → determines recovery action.
"""

import asyncio
import logging
import os
import re
import shutil
import time
from pathlib import Path
from typing import List, Optional, Set

from src.agentos.code_executor.config import CodeExecutorConfig, SecurityConfig
from src.agentos.code_executor.models import (
    ErrorAnalysis,
    ErrorType,
    ExecutionResult,
    RecoveryAction,
)

logger = logging.getLogger("agentos.code_executor.execution")


# ---------------------------------------------------------------------------
# Language helpers
# ---------------------------------------------------------------------------

LANGUAGE_EXTENSIONS = {
    "python": ".py",
    "javascript": ".js",
    "bash": ".sh",
    "shell": ".sh",
}

LANGUAGE_INTERPRETERS = {
    "python": ["python3", "python"],
    "javascript": ["node"],
    "bash": ["bash"],
    "shell": ["bash"],
}


def _discover_interpreter(language: str) -> Optional[str]:
    """Find a working interpreter for the given language."""
    candidates = LANGUAGE_INTERPRETERS.get(language, [])
    for cmd in candidates:
        try:
            result = asyncio.get_event_loop().run_until_complete(
                asyncio.create_subprocess_exec(
                    cmd, "--version",
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
            )
            # If we got here without error, the interpreter exists
            return cmd
        except Exception:
            continue
    return candidates[0] if candidates else None


def _discover_interpreter_sync(language: str) -> Optional[str]:
    """Synchronous version — probes interpreter via subprocess."""
    import subprocess as _sp
    candidates = LANGUAGE_INTERPRETERS.get(language, [])
    for cmd in candidates:
        try:
            _sp.run([cmd, "--version"], capture_output=True, timeout=5)
            return cmd
        except Exception:
            continue
    return candidates[0] if candidates else None


# ---------------------------------------------------------------------------
# Security validation
# ---------------------------------------------------------------------------

def validate_code_security(code: str, language: str, security: SecurityConfig) -> Optional[str]:
    """
    Check code for blocked patterns. Returns error message if blocked, None if safe.
    """
    code_lower = code.lower()

    # Check blocked commands
    for blocked in security.blocked_commands:
        if blocked.lower() in code_lower:
            return f"Blocked command detected: {blocked}"

    # Check restricted imports (Python only)
    if language == "python":
        for restricted in security.restricted_imports:
            # Match `import X` or `from X import`
            pattern = rf'(?:^|\n)\s*(?:import\s+{re.escape(restricted)}|from\s+{re.escape(restricted)}\s+import)'
            if re.search(pattern, code):
                return f"Restricted import detected: {restricted}"

    return None


# ---------------------------------------------------------------------------
# SubprocessBackend
# ---------------------------------------------------------------------------

class SubprocessBackend:
    """
    Executes code in a subprocess with timeout and output capture.
    Each execution writes code to a temp script file in the workspace,
    runs the interpreter, then captures stdout/stderr.
    """

    def __init__(self, config: CodeExecutorConfig):
        self.config = config
        self._interpreters: dict = {}
        self._init_interpreters()

    def _init_interpreters(self):
        """Discover available interpreters."""
        for lang in ["python", "javascript", "bash"]:
            interp = _discover_interpreter_sync(lang)
            if interp:
                self._interpreters[lang] = interp
                logger.info(f"Discovered interpreter for {lang}: {interp}")
            else:
                logger.warning(f"No interpreter found for {lang}")

        # Allow config overrides
        if self.config.languages.python_interpreter:
            self._interpreters["python"] = self.config.languages.python_interpreter
        if self.config.languages.node_interpreter:
            self._interpreters["javascript"] = self.config.languages.node_interpreter
        if self.config.languages.bash_interpreter:
            self._interpreters["bash"] = self.config.languages.bash_interpreter

    def get_interpreter(self, language: str) -> Optional[str]:
        return self._interpreters.get(language)

    async def execute(
        self,
        code: str,
        language: str,
        workspace: str,
        timeout: Optional[int] = None,
    ) -> ExecutionResult:
        """
        Execute code in a subprocess.

        Args:
            code: Source code to execute.
            language: Programming language (python, javascript, bash).
            workspace: Working directory for execution.
            timeout: Max seconds (defaults to config).

        Returns:
            ExecutionResult with stdout, stderr, exit code, timing, created files.
        """
        timeout = timeout or self.config.execution.timeout_per_attempt
        interpreter = self.get_interpreter(language)
        if not interpreter:
            return ExecutionResult(
                success=False,
                error=f"No interpreter available for language: {language}",
                exit_code=-1,
            )

        # Security check
        sec_error = validate_code_security(code, language, self.config.security)
        if sec_error:
            return ExecutionResult(success=False, error=sec_error, exit_code=-1)

        # Ensure workspace exists
        ws_path = Path(workspace).resolve()
        ws_path.mkdir(parents=True, exist_ok=True)

        # Write code to script file
        ext = LANGUAGE_EXTENSIONS.get(language, ".txt")
        script_path = ws_path / f"script{ext}"
        script_path.write_text(code, encoding="utf-8")

        # Snapshot files before execution
        files_before: Set[str] = set()
        try:
            files_before = {str(p.relative_to(ws_path)) for p in ws_path.rglob("*") if p.is_file()}
        except Exception:
            pass

        start = time.perf_counter()

        try:
            process = await asyncio.create_subprocess_exec(
                interpreter, str(script_path),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=str(ws_path),
                env={**os.environ},  # Inherit env
            )

            try:
                stdout, stderr = await asyncio.wait_for(
                    process.communicate(), timeout=timeout
                )
            except asyncio.TimeoutError:
                process.kill()
                await process.wait()
                elapsed = (time.perf_counter() - start) * 1000
                return ExecutionResult(
                    success=False,
                    error=f"Execution timed out after {timeout}s",
                    exit_code=-1,
                    execution_time_ms=elapsed,
                )

            elapsed = (time.perf_counter() - start) * 1000
            stdout_str = stdout.decode("utf-8", errors="replace").strip()
            stderr_str = stderr.decode("utf-8", errors="replace").strip()

            # Detect newly created files
            files_after: Set[str] = set()
            try:
                files_after = {str(p.relative_to(ws_path)) for p in ws_path.rglob("*") if p.is_file()}
            except Exception:
                pass
            new_files = sorted(files_after - files_before - {f"script{ext}"})

            return ExecutionResult(
                success=(process.returncode == 0),
                output=stdout_str,
                error=stderr_str if process.returncode != 0 else "",
                exit_code=process.returncode or 0,
                execution_time_ms=elapsed,
                files_created=new_files,
            )

        except Exception as exc:
            elapsed = (time.perf_counter() - start) * 1000
            return ExecutionResult(
                success=False,
                error=f"Execution error: {exc}",
                exit_code=-1,
                execution_time_ms=elapsed,
            )

    async def install_package(
        self, package: str, language: str, workspace: str
    ) -> ExecutionResult:
        """
        Install a package using the appropriate package manager.

        Args:
            package: Package name to install.
            language: Language (determines pip vs npm).
            workspace: Working directory.

        Returns:
            ExecutionResult indicating success/failure.
        """
        start = time.perf_counter()

        if language == "python":
            cmd = [self._interpreters.get("python", "python"), "-m", "pip",
                   "install", package, "--quiet", "--disable-pip-version-check"]
        elif language == "javascript":
            cmd = ["npm", "install", package, "--prefix", workspace, "--silent"]
        else:
            return ExecutionResult(
                success=False,
                error=f"Package installation not supported for {language}",
                exit_code=-1,
            )

        try:
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=workspace,
            )
            stdout, stderr = await asyncio.wait_for(
                process.communicate(), timeout=120
            )
            elapsed = (time.perf_counter() - start) * 1000
            return ExecutionResult(
                success=(process.returncode == 0),
                output=stdout.decode("utf-8", errors="replace").strip(),
                error=stderr.decode("utf-8", errors="replace").strip() if process.returncode != 0 else "",
                exit_code=process.returncode or 0,
                execution_time_ms=elapsed,
            )
        except asyncio.TimeoutError:
            return ExecutionResult(
                success=False,
                error=f"Package install timed out for {package}",
                exit_code=-1,
                execution_time_ms=(time.perf_counter() - start) * 1000,
            )
        except Exception as exc:
            return ExecutionResult(
                success=False,
                error=f"Package install error: {exc}",
                exit_code=-1,
                execution_time_ms=(time.perf_counter() - start) * 1000,
            )


# ---------------------------------------------------------------------------
# ErrorAnalyzer
# ---------------------------------------------------------------------------

# Maps Python import names that differ from pip package names
PYTHON_PACKAGE_MAP = {
    "cv2": "opencv-python",
    "PIL": "Pillow",
    "sklearn": "scikit-learn",
    "yaml": "pyyaml",
    "bs4": "beautifulsoup4",
    "dateutil": "python-dateutil",
    "dotenv": "python-dotenv",
    "jwt": "pyjwt",
    "magic": "python-magic",
    "gi": "pygobject",
    "serial": "pyserial",
    "usb": "pyusb",
    "wx": "wxPython",
    "attr": "attrs",
    "skimage": "scikit-image",
    "docx": "python-docx",
    "pptx": "python-pptx",
    "lxml": "lxml",
}


class ErrorAnalyzer:
    """
    Classifies execution errors and determines recovery actions.
    All methods are classmethods — no state required.
    """

    @classmethod
    def analyze(cls, error: str, language: str = "python") -> ErrorAnalysis:
        """
        Analyze an execution error and recommend a recovery action.

        Args:
            error: The stderr / exception text.
            language: Programming language.

        Returns:
            ErrorAnalysis with error type, recommended action, and details.
        """
        if not error:
            return ErrorAnalysis(
                error_type=ErrorType.RUNTIME_ERROR,
                action=RecoveryAction.RETRY,
                recoverable=True,
                details="Empty error — retrying.",
            )

        # --- Missing package ---
        pkg = cls._extract_missing_package(error, language)
        if pkg:
            return ErrorAnalysis(
                error_type=ErrorType.MISSING_PACKAGE,
                action=RecoveryAction.INSTALL_PACKAGE,
                recoverable=True,
                package_name=pkg,
                details=f"Missing package: {pkg}",
            )

        # --- Syntax / indentation ---
        if any(kw in error for kw in ["SyntaxError", "IndentationError", "TabError"]):
            return ErrorAnalysis(
                error_type=ErrorType.SYNTAX_ERROR,
                action=RecoveryAction.FIX_CODE,
                recoverable=True,
                details="Syntax error — requesting LLM fix.",
            )

        # --- Name error ---
        if "NameError" in error:
            return ErrorAnalysis(
                error_type=ErrorType.NAME_ERROR,
                action=RecoveryAction.FIX_CODE,
                recoverable=True,
                details="Undefined name — requesting LLM fix.",
            )

        # --- Type error ---
        if "TypeError" in error:
            return ErrorAnalysis(
                error_type=ErrorType.TYPE_ERROR,
                action=RecoveryAction.FIX_CODE,
                recoverable=True,
                details="Type error — requesting LLM fix.",
            )

        # --- Permission error ---
        if "PermissionError" in error or "EACCES" in error:
            return ErrorAnalysis(
                error_type=ErrorType.PERMISSION_ERROR,
                action=RecoveryAction.ABORT,
                recoverable=False,
                details="Permission denied — cannot auto-recover.",
            )

        # --- File not found ---
        if "FileNotFoundError" in error or "ENOENT" in error:
            return ErrorAnalysis(
                error_type=ErrorType.FILE_NOT_FOUND,
                action=RecoveryAction.ABORT,
                recoverable=False,
                details="File not found — cannot auto-recover.",
            )

        # --- Timeout ---
        if "timed out" in error.lower() or "timeout" in error.lower():
            return ErrorAnalysis(
                error_type=ErrorType.TIMEOUT,
                action=RecoveryAction.RETRY,
                recoverable=True,
                details="Execution timed out — retrying.",
            )

        # --- Default: runtime error → ask LLM to fix ---
        return ErrorAnalysis(
            error_type=ErrorType.RUNTIME_ERROR,
            action=RecoveryAction.FIX_CODE,
            recoverable=True,
            details=f"Runtime error — requesting LLM fix. Error: {error[:200]}",
        )

    @classmethod
    def _extract_missing_package(cls, error: str, language: str) -> Optional[str]:
        """Extract the package name to install from an import error."""

        if language == "python":
            # ModuleNotFoundError: No module named 'foo'  (with or without quotes)
            m = re.search(r"No module named ['\"]?([^'\"\.\s]+)", error)
            if m:
                import_name = m.group(1)
                return PYTHON_PACKAGE_MAP.get(import_name, import_name)

            # ImportError: cannot import name ...
            m = re.search(r"ImportError.*cannot import name", error)
            if m:
                # This is usually a code bug, not a missing package
                return None

        elif language == "javascript":
            # Cannot find module 'foo' (with or without quotes)
            m = re.search(r"Cannot find module ['\"]?([^'\"\s]+)", error)
            if m:
                return m.group(1)

        return None
