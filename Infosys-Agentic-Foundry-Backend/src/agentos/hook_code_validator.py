# © 2024-25 Infosys Limited, Bangalore, India. All Rights Reserved.
"""
Hook Code Validator — Static analysis of Python hook scripts.

Validates that hook code:
  1. Is syntactically valid Python
  2. Does not use dangerous/blocked operations
  3. Only imports from an approved set of modules
  4. Does not access internal framework internals

This validator runs at hook CREATION and UPDATE time (in hook_endpoints.py
and agent onboard/update endpoints) to prevent malicious code from being
stored or executed.
"""

import ast
import re
from dataclasses import dataclass, field
from typing import List, Optional, Set, Tuple

try:
    from telemetry_wrapper import logger as log
except ImportError:
    import logging
    log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Configuration: Allowed and Blocked
# ---------------------------------------------------------------------------

# Modules that hooks are allowed to import (top-level).
# Sub-modules (e.g., os.path) are handled separately.
ALLOWED_IMPORTS: Set[str] = frozenset({
    # Standard library — safe for hook use
    "os",           # Only os.path.*, os.getenv, os.makedirs, os.getcwd allowed (function-level check)
    "sys",          # For sys.exit, sys.stdout
    "json",         # Parse/serialize data
    "re",           # Pattern matching
    "datetime",     # Timestamps
    "time",         # time.time(), sleep (limited)
    "logging",      # Standard logging
    "hashlib",      # Hashing for fingerprinting
    "typing",       # Type hints
    "pathlib",      # Path manipulation (no destructive ops enforced separately)
    "math",         # Math operations
    "string",       # String constants
    "collections",  # namedtuple, defaultdict
    "functools",    # lru_cache, partial
    "enum",         # Enumerations
    "dataclasses",  # Dataclass decorator
    "copy",         # Shallow/deep copy
    "textwrap",     # Text formatting
    "uuid",         # UUID generation
    "base64",       # Encoding
    "hmac",         # HMAC for signature verification
    "fnmatch",      # Filename pattern matching
    "traceback",    # For error logging
})

# Modules that are COMPLETELY blocked — no legitimate hook use.
BLOCKED_IMPORTS: Set[str] = frozenset({
    "subprocess",       # Shell execution
    "socket",           # Network access
    "http",             # HTTP server/client
    "urllib",           # URL fetching
    "requests",         # HTTP library
    "httpx",            # HTTP library
    "aiohttp",         # Async HTTP
    "ctypes",           # FFI / native code
    "importlib",        # Dynamic imports (bypass restrictions)
    "multiprocessing",  # Process spawning
    "threading",        # Thread spawning (limited usefulness, DoS risk)
    "signal",           # Signal handling
    "shutil",           # Destructive file ops (rmtree, move)
    "tempfile",         # Can be used for arbitrary writes
    "pickle",           # Deserialization attacks
    "marshal",          # Code object manipulation
    "code",             # Interactive interpreter
    "codeop",           # Code compilation
    "compile",          # Bytecode compilation
    "ast",              # AST manipulation (meta-programming)
    "inspect",          # Frame introspection
    "dis",              # Bytecode disassembly
    "gc",               # Garbage collector manipulation
    "sys.modules",      # Module registry access (not a real module, caught as attr)
    "builtins",         # Direct builtins access
    "io",               # Raw I/O (can bypass file restrictions)
    "sqlite3",          # Direct DB access
    "psycopg2",         # PostgreSQL access
    "pymongo",          # MongoDB access
    "redis",            # Redis access
    "boto3",            # AWS access
    "azure",            # Azure access
    "google.cloud",     # GCP access
    "paramiko",         # SSH access
    "fabric",           # Remote execution
    "pexpect",          # Process control
    "pty",              # Pseudo-terminal
    "resource",         # System resource manipulation
    "select",           # I/O multiplexing (network)
    "ssl",              # TLS (network indicator)
    "ftplib",           # FTP
    "smtplib",          # Email sending
    "telnetlib",        # Telnet
    "xmlrpc",           # RPC
    "webbrowser",       # Open browser
})

# Framework-internal modules that hooks must NOT import.
BLOCKED_IMPORT_PREFIXES: List[str] = [
    "src.",             # Entire IAF framework internals
    "agent_os.",        # Agent OS internals
    "langchain",        # LLM framework
    "langgraph",        # Graph framework
    "litellm",          # LLM proxy
    "openai",           # Direct LLM access
    "anthropic",        # Direct LLM access
    "google.generativeai",  # Direct LLM access
]

# Allowed os.* function calls (attribute access on `os` module)
ALLOWED_OS_FUNCTIONS: Set[str] = frozenset({
    "os.path.join",
    "os.path.exists",
    "os.path.dirname",
    "os.path.basename",
    "os.path.realpath",
    "os.path.abspath",
    "os.path.isfile",
    "os.path.isdir",
    "os.path.splitext",
    "os.path.split",
    "os.path.expanduser",
    "os.path.normpath",
    "os.path.getsize",
    "os.getenv",
    "os.environ.get",
    "os.makedirs",
    "os.getcwd",
    "os.listdir",  # Reading directory contents (non-destructive)
})

# Blocked os.* attribute accesses
BLOCKED_OS_FUNCTIONS: Set[str] = frozenset({
    "os.system",
    "os.popen",
    "os.exec",
    "os.execl",
    "os.execle",
    "os.execlp",
    "os.execlpe",
    "os.execv",
    "os.execve",
    "os.execvp",
    "os.execvpe",
    "os.spawn",
    "os.spawnl",
    "os.spawnle",
    "os.spawnlp",
    "os.spawnlpe",
    "os.spawnv",
    "os.spawnve",
    "os.spawnvp",
    "os.spawnvpe",
    "os.kill",
    "os.killpg",
    "os.remove",
    "os.unlink",
    "os.rmdir",
    "os.removedirs",
    "os.rename",       # Can overwrite files
    "os.replace",      # Can overwrite files
    "os.chmod",
    "os.chown",
    "os.chroot",
    "os.fork",
    "os.forkpty",
    "os.putenv",       # Modify environment for other processes
    "os.unsetenv",
})

# Built-in function calls that are completely blocked
BLOCKED_BUILTINS: Set[str] = frozenset({
    "eval",
    "exec",
    "compile",
    "__import__",
    "globals",
    "locals",
    "vars",
    "dir",          # Can be used for introspection
    "getattr",      # Dynamic attribute access (bypass restrictions)
    "setattr",      # Dynamic attribute setting
    "delattr",      # Dynamic attribute deletion
    "breakpoint",   # Debugger
    "exit",         # Use sys.exit instead (clearly intentional)
    "quit",         # Same as exit
    "open",         # Blocked globally — use os.path for checks only
})

# Allowed built-in calls (explicitly permitted)
ALLOWED_BUILTINS: Set[str] = frozenset({
    "print", "len", "str", "int", "float", "bool",
    "list", "dict", "set", "tuple", "frozenset",
    "type", "isinstance", "issubclass",
    "range", "enumerate", "zip", "map", "filter",
    "sorted", "reversed", "min", "max", "sum", "abs",
    "any", "all", "round", "divmod", "pow",
    "repr", "format", "chr", "ord",
    "hasattr",  # Read-only check (less dangerous than getattr)
    "id", "hash", "hex", "oct", "bin",
    "input",    # For interactive hooks — not dangerous in subprocess context
    "super", "object", "staticmethod", "classmethod", "property",
    "ValueError", "TypeError", "KeyError", "IndexError",
    "RuntimeError", "Exception", "StopIteration",
    "NotImplementedError", "AttributeError", "IOError",
    "OSError", "FileNotFoundError", "PermissionError",
})


# ---------------------------------------------------------------------------
# Validation Result
# ---------------------------------------------------------------------------

@dataclass
class ValidationResult:
    """Result of hook code validation."""
    is_valid: bool = True
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)

    def add_error(self, msg: str, line: Optional[int] = None):
        prefix = f"Line {line}: " if line else ""
        self.errors.append(f"{prefix}{msg}")
        self.is_valid = False

    def add_warning(self, msg: str, line: Optional[int] = None):
        prefix = f"Line {line}: " if line else ""
        self.warnings.append(f"{prefix}{msg}")

    def to_dict(self) -> dict:
        return {
            "is_valid": self.is_valid,
            "errors": self.errors,
            "warnings": self.warnings,
            "error_count": len(self.errors),
            "warning_count": len(self.warnings),
        }


# ---------------------------------------------------------------------------
# AST Visitor — walks the parsed tree to detect violations
# ---------------------------------------------------------------------------

class HookCodeAnalyzer(ast.NodeVisitor):
    """AST visitor that checks hook code for disallowed operations."""

    def __init__(self):
        self.result = ValidationResult()
        self._imported_names: dict = {}  # alias → module (e.g., {"np": "numpy"})

    def visit_Import(self, node: ast.Import):
        """Check `import X` statements."""
        for alias in node.names:
            module_name = alias.name
            local_name = alias.asname or alias.name
            self._imported_names[local_name] = module_name
            self._check_import(module_name, node.lineno)
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom):
        """Check `from X import Y` statements."""
        module_name = node.module or ""
        self._check_import(module_name, node.lineno)

        # Also check the specific names imported
        for alias in (node.names or []):
            # e.g., from os import system
            full_name = f"{module_name}.{alias.name}" if module_name else alias.name
            local_name = alias.asname or alias.name
            self._imported_names[local_name] = full_name

            # Check if the specific import is a blocked function
            if full_name in BLOCKED_OS_FUNCTIONS:
                self.result.add_error(
                    f"Blocked import: '{full_name}' — this function is not allowed in hooks",
                    node.lineno,
                )
            # Block importing from framework internals
            for prefix in BLOCKED_IMPORT_PREFIXES:
                if full_name.startswith(prefix):
                    self.result.add_error(
                        f"Blocked import: '{full_name}' — framework internals are not accessible from hooks",
                        node.lineno,
                    )
                    break

        self.generic_visit(node)

    def visit_Call(self, node: ast.Call):
        """Check function calls for blocked builtins and dangerous patterns."""
        func_name = self._resolve_call_name(node.func)

        if func_name:
            # Check blocked builtins
            base_name = func_name.split(".")[-1] if "." in func_name else func_name
            # Special case: sys.exit() is allowed (hooks use exit codes for signaling)
            if func_name == "sys.exit":
                pass  # Explicitly permitted
            elif func_name in BLOCKED_BUILTINS or base_name in BLOCKED_BUILTINS:
                # Special case: allow open() — we'll just warn for now, block in strict mode
                if base_name == "open":
                    self.result.add_warning(
                        f"Use of 'open()' detected — hooks should not perform file I/O outside logging. "
                        f"Consider using os.path.exists() for checks only.",
                        node.lineno,
                    )
                elif base_name in ("getattr", "setattr", "delattr"):
                    self.result.add_error(
                        f"Blocked call: '{base_name}()' — dynamic attribute access can bypass security restrictions",
                        node.lineno,
                    )
                elif base_name in ("eval", "exec", "compile", "__import__"):
                    self.result.add_error(
                        f"Blocked call: '{base_name}()' — dynamic code execution is forbidden in hooks",
                        node.lineno,
                    )
                elif base_name in ("globals", "locals", "vars"):
                    self.result.add_error(
                        f"Blocked call: '{base_name}()' — namespace introspection is not allowed in hooks",
                        node.lineno,
                    )
                else:
                    self.result.add_error(
                        f"Blocked call: '{func_name}()' — this function is not allowed in hooks",
                        node.lineno,
                    )

            # Check blocked os.* calls
            elif func_name in BLOCKED_OS_FUNCTIONS:
                self.result.add_error(
                    f"Blocked call: '{func_name}()' — this OS operation is not allowed in hooks",
                    node.lineno,
                )
            # Check os.* calls that aren't explicitly allowed
            elif func_name.startswith("os.") and func_name not in ALLOWED_OS_FUNCTIONS:
                # Check if it's under os.path.* (allow all os.path)
                if not func_name.startswith("os.path."):
                    self.result.add_warning(
                        f"Unrecognized os function: '{func_name}()' — only approved os functions are allowed",
                        node.lineno,
                    )

            # Check calls via imported aliases that resolve to blocked modules
            top_level = func_name.split(".")[0]
            if top_level in self._imported_names:
                resolved_module = self._imported_names[top_level]
                resolved_full = func_name.replace(top_level, resolved_module, 1)
                if resolved_full in BLOCKED_OS_FUNCTIONS:
                    self.result.add_error(
                        f"Blocked call: '{resolved_full}()' (via alias '{top_level}') — not allowed in hooks",
                        node.lineno,
                    )

        self.generic_visit(node)

    def visit_Attribute(self, node: ast.Attribute):
        """Check attribute access patterns for sneaky bypasses."""
        attr_chain = self._resolve_attr_chain(node)

        # Check the immediate attribute name regardless of chain resolution
        attr_name = node.attr
        allowed_dunders = {"__name__", "__doc__", "__init__", "__main__", "__file__"}
        if attr_name.startswith("__") and attr_name.endswith("__") and attr_name not in allowed_dunders:
            self.result.add_error(
                f"Blocked: access to '{attr_name}' — dunder attribute manipulation is not allowed in hooks",
                node.lineno,
            )

        if attr_chain:
            # Also check the full chain for additional dunders
            if any(part.startswith("__") and part.endswith("__") for part in attr_chain.split(".")):
                dunder = [p for p in attr_chain.split(".") if p.startswith("__") and p.endswith("__")]
                for d in dunder:
                    if d not in allowed_dunders:
                        # Already caught on the immediate attr, avoid duplicate for the last part
                        if d != attr_name:
                            self.result.add_error(
                                f"Blocked: access to '{d}' — dunder attribute manipulation is not allowed in hooks",
                                node.lineno,
                            )

        self.generic_visit(node)

    def visit_FunctionDef(self, node: ast.FunctionDef):
        """Track function definitions (no restriction, just visit children)."""
        self.generic_visit(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef):
        """Async function definitions — warn but allow."""
        self.result.add_warning(
            f"Async function '{node.name}' detected — hooks should preferably be synchronous",
            node.lineno,
        )
        self.generic_visit(node)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _check_import(self, module_name: str, lineno: int):
        """Validate a module import."""
        if not module_name:
            return

        # Top-level module for checking
        top_level = module_name.split(".")[0]

        # Check against completely blocked modules
        if top_level in BLOCKED_IMPORTS or module_name in BLOCKED_IMPORTS:
            self.result.add_error(
                f"Blocked import: '{module_name}' — this module is not allowed in hooks",
                lineno,
            )
            return

        # Check against blocked prefixes (framework internals)
        for prefix in BLOCKED_IMPORT_PREFIXES:
            if module_name.startswith(prefix):
                self.result.add_error(
                    f"Blocked import: '{module_name}' — framework internals are not accessible from hooks",
                    lineno,
                )
                return

        # Check against allowed modules
        if top_level not in ALLOWED_IMPORTS:
            self.result.add_error(
                f"Disallowed import: '{module_name}' — only approved standard library modules are permitted. "
                f"Allowed: {sorted(ALLOWED_IMPORTS)}",
                lineno,
            )

    def _resolve_call_name(self, node: ast.expr) -> Optional[str]:
        """Resolve a call target to a dotted name string (best-effort)."""
        if isinstance(node, ast.Name):
            return node.id
        elif isinstance(node, ast.Attribute):
            return self._resolve_attr_chain(node)
        return None

    def _resolve_attr_chain(self, node: ast.expr) -> Optional[str]:
        """Resolve chained attribute access: a.b.c → 'a.b.c'."""
        parts = []
        current = node
        while isinstance(current, ast.Attribute):
            parts.append(current.attr)
            current = current.value
        if isinstance(current, ast.Name):
            parts.append(current.id)
            return ".".join(reversed(parts))
        return None


# ---------------------------------------------------------------------------
# Additional structural checks
# ---------------------------------------------------------------------------

def _check_code_size(code: str, result: ValidationResult, max_lines: int = 500, max_bytes: int = 50_000):
    """Enforce code size limits."""
    if len(code) > max_bytes:
        result.add_error(f"Code exceeds maximum size ({len(code)} bytes > {max_bytes} bytes limit)")
    lines = code.split("\n")
    if len(lines) > max_lines:
        result.add_error(f"Code exceeds maximum line count ({len(lines)} lines > {max_lines} limit)")


def _check_string_literals(tree: ast.Module, result: ValidationResult):
    """Check string literals for suspicious patterns (obfuscated code)."""
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            val = node.value
            # Detect base64-encoded large blobs (possible obfuscated code)
            if len(val) > 200 and re.match(r'^[A-Za-z0-9+/=]+$', val):
                result.add_warning(
                    f"Large base64-like string detected ({len(val)} chars) — "
                    f"possible obfuscated code payload",
                    getattr(node, "lineno", None),
                )
            # Detect chr() chains in string building
            if "\\x" in repr(val) and len(val) > 50:
                result.add_warning(
                    f"String with hex escapes detected — possible code obfuscation",
                    getattr(node, "lineno", None),
                )


def _check_comprehension_depth(tree: ast.Module, result: ValidationResult, max_depth: int = 3):
    """Detect deeply nested comprehensions (potential ReDoS/DoS)."""
    for node in ast.walk(tree):
        if isinstance(node, (ast.ListComp, ast.SetComp, ast.DictComp, ast.GeneratorExp)):
            if len(node.generators) > max_depth:
                result.add_warning(
                    f"Deeply nested comprehension ({len(node.generators)} generators) — "
                    f"potential performance issue",
                    node.lineno,
                )


def _check_hook_structure(tree: ast.Module, result: ValidationResult):
    """Validate that code has proper hook structure.

    A valid hook must have:
      - At least one function definition (typically `main()`)
      - An `if __name__ == "__main__":` guard (hooks are executed as scripts)
    """
    # Check for at least one function definition
    has_function = False
    has_main_function = False
    has_name_guard = False

    for node in ast.iter_child_nodes(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            has_function = True
            if node.name == "main":
                has_main_function = True
        elif isinstance(node, ast.If):
            # Check for: if __name__ == "__main__":
            test = node.test
            if isinstance(test, ast.Compare):
                left = test.left
                if (isinstance(left, ast.Name) and left.id == "__name__" and
                        len(test.comparators) == 1):
                    comp = test.comparators[0]
                    if isinstance(comp, ast.Constant) and comp.value == "__main__":
                        has_name_guard = True

    if not has_function:
        result.add_error(
            "Hook code must define at least one function (e.g., `def main():`) — "
            "raw statements are not valid hook scripts"
        )
    elif not has_main_function:
        result.add_warning(
            "Hook code should define a `main()` function as the entry point — "
            "this is the standard hook convention"
        )

    if not has_name_guard and has_function:
        result.add_warning(
            "Hook code should include an `if __name__ == \"__main__\":` guard — "
            "hooks are executed as standalone scripts"
        )


# ---------------------------------------------------------------------------
# Main validation function
# ---------------------------------------------------------------------------

def validate_hook_code(code: str) -> ValidationResult:
    """Validate Python hook code for security and correctness.

    Performs:
        1. Syntax validation (ast.parse)
        2. Code size limits check
        3. AST analysis for blocked imports/calls/attributes
        4. String literal obfuscation check
        5. Structural checks (nesting depth)

    Args:
        code: The Python source code string to validate.

    Returns:
        ValidationResult with is_valid, errors, and warnings.
    """
    result = ValidationResult()

    # 0. Empty code check
    if not code or not code.strip():
        result.add_error("Hook code cannot be empty")
        return result

    # 1. Size limits
    _check_code_size(code, result)
    if not result.is_valid:
        return result

    # 2. Syntax validation
    try:
        tree = ast.parse(code)
    except SyntaxError as e:
        result.add_error(f"Invalid Python syntax: {e.msg} (line {e.lineno}, col {e.offset})")
        return result

    # 3. AST analysis — imports, calls, attributes
    analyzer = HookCodeAnalyzer()
    analyzer.visit(tree)
    result = analyzer.result

    # 4. String literal checks
    _check_string_literals(tree, result)

    # 5. Structural checks
    _check_comprehension_depth(tree, result)
    _check_hook_structure(tree, result)

    if result.is_valid:
        log.info(f"[HookValidator] Code passed validation ({len(code)} bytes, {len(result.warnings)} warnings)")
    else:
        log.warning(f"[HookValidator] Code REJECTED: {len(result.errors)} error(s)")

    return result


# ---------------------------------------------------------------------------
# Hook Config Structure Validator
# ---------------------------------------------------------------------------

# Valid hook section keys for Python hooks
VALID_PYTHON_HOOK_SECTIONS = frozenset({
    "pre_hook", "post_hook", "on_agent_start", "on_agent_end",
    "on_agent_error", "before_node", "after_node", "before_route",
    "after_route", "before_llm", "after_llm", "pre_response",
    "post_turn", "post_sampling",
})

# Valid external hook events
VALID_EXTERNAL_EVENTS = frozenset({
    "PreToolUse", "PostToolUse", "PreResponse", "PostSampling",
    "OnAgentStart", "OnAgentEnd", "OnAgentError",
})


def validate_hooks_config(hooks: dict) -> List[str]:
    """Validate the hooks config dict passed at agent onboard/update time.

    Returns a list of error strings (empty list = valid).

    Validates:
      - Section keys are recognized (python sections or 'external')
      - External entries have valid event plus hook_id (raw command blocked)
      - Python entries have module + function (non-empty strings)
      - Timeout and priority within bounds
      - Pattern fields are valid regex
    """
    errors: List[str] = []

    if not isinstance(hooks, dict):
        errors.append("hooks must be a dictionary")
        return errors

    for section_key, entries in hooks.items():
        if section_key == "external":
            if not isinstance(entries, list):
                errors.append("hooks.external must be a list")
                continue
            for i, entry in enumerate(entries):
                if not isinstance(entry, dict):
                    errors.append(f"hooks.external[{i}]: each entry must be a dict")
                    continue
                # Must have either hook_id or command
                has_hook_id = bool(entry.get("hook_id"))
                has_command = bool(entry.get("command"))
                if not has_hook_id and not has_command:
                    errors.append(f"hooks.external[{i}]: must specify 'hook_id' (recommended) or 'command'")
                # Block raw 'command' — must use hook_id from Hook Repository
                if has_command and not has_hook_id:
                    errors.append(
                        f"hooks.external[{i}]: raw 'command' is not allowed for security reasons. "
                        f"Upload your hook script to the Hook Repository and use 'hook_id' instead."
                    )
                # Validate event
                event = entry.get("event", "")
                if event and event not in VALID_EXTERNAL_EVENTS:
                    errors.append(
                        f"hooks.external[{i}]: invalid event '{event}'. "
                        f"Must be one of: {sorted(VALID_EXTERNAL_EVENTS)}"
                    )
                # Validate timeout
                timeout = entry.get("timeout_seconds")
                if timeout is not None:
                    try:
                        t = int(timeout)
                        if t < 1 or t > 120:
                            errors.append(f"hooks.external[{i}]: timeout_seconds must be 1-120 (got {t})")
                    except (ValueError, TypeError):
                        errors.append(f"hooks.external[{i}]: timeout_seconds must be an integer")
                # Validate matcher regex
                matcher = entry.get("matcher")
                if matcher:
                    try:
                        re.compile(matcher)
                    except re.error as e:
                        errors.append(f"hooks.external[{i}]: invalid matcher regex: {e}")

        elif section_key in VALID_PYTHON_HOOK_SECTIONS:
            if not isinstance(entries, list):
                errors.append(f"hooks.{section_key} must be a list")
                continue
            for i, entry in enumerate(entries):
                if not isinstance(entry, dict):
                    errors.append(f"hooks.{section_key}[{i}]: each entry must be a dict")
                    continue
                module = entry.get("module", "")
                function = entry.get("function", "")
                if not module or not function:
                    errors.append(f"hooks.{section_key}[{i}]: must have 'module' and 'function' fields")
                # Validate priority
                priority = entry.get("priority")
                if priority is not None:
                    try:
                        p = int(priority)
                        if p < 1 or p > 1000:
                            errors.append(f"hooks.{section_key}[{i}]: priority must be 1-1000 (got {p})")
                    except (ValueError, TypeError):
                        errors.append(f"hooks.{section_key}[{i}]: priority must be an integer")
                # Validate pattern field as regex
                pattern = entry.get("pattern")
                if pattern:
                    try:
                        re.compile(pattern)
                    except re.error as e:
                        errors.append(f"hooks.{section_key}[{i}]: invalid pattern regex: {e}")
        else:
            errors.append(
                f"Unknown hooks section '{section_key}'. Valid sections: "
                f"{sorted(VALID_PYTHON_HOOK_SECTIONS | {'external'})}"
            )

    return errors
