# © 2024-25 Infosys Limited, Bangalore, India. All Rights Reserved.
"""
Sandbox utilities for restricting user-written tool code execution.

Provides:
- Restricted __import__ that blocks internal framework modules
- Restricted open() that blocks .env file reads
- Restricted os module that hides infrastructure env keys
- Restricted sys module that hides internal modules from sys.modules
- A helper to build sandboxed builtins for exec()

This file is itself blocked from being imported by user tool code.
"""

import os
import sys
import types

# Pre-import load_model so it's available for tool code namespaces
from src.models.model import load_model

# ============================================================================
# 1. BLOCKED DIRECT IMPORTS
# ============================================================================

# Block everything under src.* except explicitly allowed modules
BLOCKED_IMPORT_PREFIXES = (
    "src.",
    "main",
    "agent_worker",
)

# Exceptions: these specific modules ARE allowed through the import gate
ALLOWED_IMPORT_EXCEPTIONS = (
    "src.models.model",
)

# For each allowed module, restrict which names can be imported
ALLOWED_IMPORT_NAMES = {
    "src.models.model": ("load_model",),
}

_real_import = __import__


# ============================================================================
# 2. BLOCKED .env FILE READING
# ============================================================================

_real_open = open


def _restricted_open(file, *args, **kwargs):
    """Blocks opening .env files from tool code."""
    path_str = str(file).replace("\\", "/").lower()
    basename = path_str.rsplit("/", 1)[-1] if "/" in path_str else path_str

    # Block .env, .env.local, .env.production, etc.
    if basename == ".env" or basename.startswith(".env."):
        raise PermissionError("Reading .env files is not allowed in tool code")

    return _real_open(file, *args, **kwargs)


# ============================================================================
# 3. RESTRICTED os.environ / os.getenv
# ============================================================================

def _make_restricted_os() -> types.ModuleType:
    """
    Creates a restricted 'os' module where:
    - os.environ is a plain dict copy without blocked keys
    - os.getenv returns None/default for blocked keys
    - Everything else works normally
    """
    restricted_os: os = types.ModuleType("os")

    # Copy all attributes from real os
    for attr in dir(os):
        if not attr.startswith("__"):
            try:
                setattr(restricted_os, attr, getattr(os, attr))
            except (AttributeError, TypeError):
                pass

    # Empty environ — completely blocked
    restricted_os.environ = {}

    # Override getenv to always return default
    def restricted_getenv(key, default=None):
        return default

    restricted_os.getenv = restricted_getenv

    return restricted_os


# ============================================================================
# 4. RESTRICTED sys — hides internal modules from sys.modules
# ============================================================================

def _make_restricted_sys() -> types.ModuleType:
    """
    Creates a restricted 'sys' module where sys.modules hides
    internal framework entries (src.api.*, src.auth.*, etc.).
    """
    restricted_sys: sys = types.ModuleType("sys")

    for attr in dir(sys):
        if not attr.startswith("__"):
            try:
                setattr(restricted_sys, attr, getattr(sys, attr))
            except (AttributeError, TypeError):
                pass

    # Filtered copy of sys.modules — hide all src.*, main, agent_worker
    restricted_sys.modules = {
        k: v for k, v in sys.modules.items()
        if not any(k == pfx.rstrip(".") or k.startswith(pfx if pfx.endswith(".") else pfx + ".") for pfx in BLOCKED_IMPORT_PREFIXES)
    }

    return restricted_sys


# ============================================================================
# 5. SANDBOX IMPORT — combines import blocking + os/sys interception
# ============================================================================

_restricted_os_module = _make_restricted_os()
_restricted_sys_module = _make_restricted_sys()


def _make_sandbox_import():
    """
    Returns a custom __import__ that:
    - Blocks src.api.*, src.auth.*, src.database.*, etc.
    - Returns restricted 'os' module (hidden env keys)
    - Returns restricted 'sys' module (hidden internal modules)
    """
    def sandbox_import(name, globals=None, locals=None, fromlist=(), level=0):
        if level != 0:
            raise ImportError("Relative imports are not allowed in tool code")

        # Allow whitelisted modules with restricted fromlist
        if name in ALLOWED_IMPORT_EXCEPTIONS:
            allowed_names = ALLOWED_IMPORT_NAMES.get(name)
            if allowed_names is not None and fromlist:
                disallowed = [f for f in fromlist if f not in allowed_names]
                if disallowed:
                    raise ImportError(
                        f"Only {allowed_names} can be imported from '{name}'. "
                        f"'{', '.join(disallowed)}' is not allowed."
                    )
            elif allowed_names is not None and not fromlist:
                # bare "import src.models.model" — block since they could access anything via attribute
                raise ImportError(
                    f"Only 'from {name} import {', '.join(allowed_names)}' is allowed, not 'import {name}'"
                )
            return _real_import(name, globals, locals, fromlist, level)

        # Block internal modules
        for prefix in BLOCKED_IMPORT_PREFIXES:
            if name == prefix.rstrip(".") or name.startswith(prefix if prefix.endswith(".") else prefix + "."):
                raise ImportError(f"Importing '{name}' is not allowed in tool code")

        # Intercept 'os' to return restricted version
        if name == "os":
            return _restricted_os_module

        # Intercept 'sys' to return restricted version
        if name == "sys":
            return _restricted_sys_module

        # Everything else: normal import
        return _real_import(name, globals, locals, fromlist, level)

    return sandbox_import


# ============================================================================
# 6. PUBLIC API — build sandboxed builtins for exec()
# ============================================================================

def get_sandbox_builtins() -> dict:
    """
    Returns a __builtins__ dict with:
    - Restricted __import__ (blocks internal modules, swaps os/sys)
    - Restricted open() (blocks .env files)
    - All other builtins preserved
    """
    safe_builtins = dict(__builtins__) if isinstance(__builtins__, dict) else vars(__builtins__).copy()
    safe_builtins["__import__"] = _make_sandbox_import()
    safe_builtins["open"] = _restricted_open
    return safe_builtins


def get_sandbox_extras() -> dict:
    """
    Returns extra names to inject into the exec() namespace
    so tool code can use them without importing.
    """
    return {
        "load_model": load_model,
    }
