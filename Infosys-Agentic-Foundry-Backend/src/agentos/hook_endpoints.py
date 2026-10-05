# © 2024-25 Infosys Limited, Bangalore, India. All Rights Reserved.
"""
Hook Repository REST endpoints.

Provides CRUD for the file-based, department-segregated hook repository.
Users upload Python hook scripts, get a ``hook_id``, and bind it to agent
lifecycle events via the agent config ``hooks`` section.

Department is resolved automatically from the authenticated user's JWT.
Event type (PreToolUse, PostToolUse, etc.) and tool matcher are configured
when the hook is bound to an agent skill — NOT at hook creation time.

Routes (all under ``/agentos/hooks``):
    POST   /               — Create a new hook script
    GET    /               — List hooks in user's department
    GET    /{hook_id}      — Get hook details + code
    PUT    /{hook_id}      — Update hook code/metadata
    DELETE /{hook_id}      — Delete a hook
    POST   /{hook_id}/test — Dry-run the hook with sample env vars
"""

from fastapi import APIRouter, HTTPException, Depends, Body, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from typing import Any, Dict, List, Optional

from src.agentos.hook_repository import (
    get_hook_repository,
    HookRepository,
)
from src.agentos.hook_code_validator import validate_hook_code
from src.auth.dependencies import get_current_user
from src.auth.models import User

try:
    from telemetry_wrapper import logger as log
except ImportError:
    import logging
    log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Router
# ---------------------------------------------------------------------------

router = APIRouter(prefix="/agentos/hooks", tags=["AgentOS - Hook Repository"])


# ---------------------------------------------------------------------------
# Request / response schemas
# ---------------------------------------------------------------------------

class CreateHookRequest(BaseModel):
    name: str = Field(..., description="Human-readable hook name", max_length=120)
    code: str = Field(..., description="Python source code of the hook script")
    description: str = Field("", description="What this hook does")


class UpdateHookRequest(BaseModel):
    code: Optional[str] = Field(None, description="Updated Python source code")
    name: Optional[str] = Field(None, max_length=120)
    description: Optional[str] = None


class TestHookRequest(BaseModel):
    tool_name: str = Field("run_shell_command", description="Simulated tool name")
    tool_input: Any = Field({"command": "ping 8.8.8.8"}, description="Simulated tool input — accepts JSON object or JSON string")
    event: str = Field("PreToolUse", description="Hook event type to simulate")


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get("/sample-hooks", summary="Get example hook scripts")
async def get_sample_hooks():
    """Return a dictionary of 3 built-in example hook scripts.

    These serve as starter templates users can copy and customise
    for their own PreToolUse, PostToolUse, and PreResponse hooks.
    """
    import pathlib, textwrap

    examples_dir = pathlib.Path(__file__).parent / "example_hooks"

    samples: Dict[str, Dict[str, str]] = {}
    hook_files = {
        "pre_tool_use": {
            "file": "template_pre_tool_use.py",
            "event": "PreToolUse",
            "description": "Template for hooks that inspect tool calls before execution. "
                           "Use exit 0 (ALLOW), exit 1 (BLOCK), or exit 2 (APPROVAL_REQUIRED).",
        },
        "post_tool_use": {
            "file": "template_post_tool_use.py",
            "event": "PostToolUse",
            "description": "Template for hooks that inspect tool output after execution. "
                           "Use exit 0 (ALLOW), exit 1 (BLOCK), or exit 2 (APPROVAL_REQUIRED).",
        },
        "pre_response": {
            "file": "template_pre_response.py",
            "event": "PreResponse",
            "description": "Template for hooks that filter or modify the agent response before the user sees it. "
                           "Use exit 0 (ALLOW, or stdout = replacement text) or exit 1 (BLOCK).",
        },
    }

    for key, info in hook_files.items():
        file_path = examples_dir / info["file"]
        try:
            code = file_path.read_text(encoding="utf-8")
        except FileNotFoundError:
            code = "# Source file not found on server"
        samples[key] = {
            "name": key,
            "event": info["event"],
            "description": info["description"],
            "code": code,
        }

    return {
        "status": "success",
        "count": len(samples),
        "sample_hooks": samples,
    }


@router.post("", summary="Create a new hook script")
async def create_hook(req: CreateHookRequest, user_data: User = Depends(get_current_user)):
    """Upload a Python hook script to the repository and get a hook_id.

    Department is automatically resolved from the authenticated user's JWT.
    Event binding and tool matcher are configured when attaching the hook to an agent skill.

    Users create hooks for tool-specific events (PreToolUse, PostToolUse, PreResponse)
    and bind them per-agent. Global lifecycle hooks (OnAgentStart, OnAgentEnd,
    OnAgentError, PostSampling) are managed internally by the system.
    """
    repo = get_hook_repository()
    department = user_data.department_name or "General"

    if not req.code.strip():
        raise HTTPException(400, "Hook code cannot be empty")

    # --- Hook Code Security Validation ---
    validation = validate_hook_code(req.code)
    if not validation.is_valid:
        error_detail = "; ".join(validation.errors)
        raise HTTPException(422, detail=f"Hook code failed security validation: {error_detail}")

    try:
        meta = repo.create_hook(
            name=req.name,
            code=req.code,
            department=department,
            description=req.description,
            created_by=user_data.username or "",
            scope="agent",
        )
    except ValueError as e:
        raise HTTPException(409, str(e))

    return {
        "status": "success",
        "hook_id": meta.hook_id,
        "name": meta.name,
        "department": meta.department,
        "filename": meta.filename,
        "message": f"Hook '{meta.name}' created. Use hook_id '{meta.hook_id}' in agent hooks config.",
    }


@router.get("", summary="List hooks in the authenticated user's department")
async def list_hooks(user_data: User = Depends(get_current_user)):
    """Returns user-created hooks (scope=agent) from the user's department.

    Global hooks are managed internally and not shown here.
    """
    repo = get_hook_repository()
    department = user_data.department_name or "General"

    log.info(f"[PVC:agent_workspaces] START list_hooks (GET) — department='{department}', mountPath=/app/agent_workspaces")

    hooks = repo.list_hooks(department=department)

    # Only show agent-scoped hooks to users (global hooks are internal)
    hooks = [h for h in hooks if h.get("scope", "agent") == "agent"]

    log.info(f"[PVC:agent_workspaces] END list_hooks (GET) — department='{department}', hooks_count={len(hooks)}, mountPath=/app/agent_workspaces")

    return {
        "status": "success",
        "count": len(hooks),
        "hooks": [dict(h) for h in hooks],
    }


@router.get("/{hook_id}", summary="Get hook details and source code")
async def get_hook(hook_id: str, user_data: User = Depends(get_current_user)):
    """Return full hook metadata plus the Python source code."""
    repo = get_hook_repository()
    meta = repo.get_hook(hook_id)
    if not meta:
        raise HTTPException(404, f"Hook '{hook_id}' not found")

    code = repo.get_hook_code(hook_id)
    return {
        "status": "success",
        "hook": dict(meta),
        "code": code,
    }


@router.put("/{hook_id}", summary="Update a hook")
@router.post("/update/{hook_id}", summary="Update a hook")
async def update_hook(hook_id: str, req: UpdateHookRequest, user_data: User = Depends(get_current_user)):
    """Update code and/or metadata of an existing hook."""
    repo = get_hook_repository()

    # --- Hook Code Security Validation (if code is being updated) ---
    if req.code is not None:
        if not req.code.strip():
            raise HTTPException(400, "Hook code cannot be empty")
        validation = validate_hook_code(req.code)
        if not validation.is_valid:
            error_detail = "; ".join(validation.errors)
            raise HTTPException(422, detail=f"Hook code failed security validation: {error_detail}")

    updated = repo.update_hook(
        hook_id=hook_id,
        code=req.code,
        name=req.name,
        description=req.description,
    )
    if not updated:
        raise HTTPException(404, f"Hook '{hook_id}' not found")

    return {
        "status": "success",
        "hook": dict(updated),
        "message": f"Hook '{hook_id}' updated (v{updated.get('version', '?')}).",
    }


@router.delete("/{hook_id}", summary="Delete a hook")
@router.post("/delete/{hook_id}", summary="Delete a hook")
async def delete_hook(hook_id: str, user_data: User = Depends(get_current_user)):
    """Delete a hook script and remove from manifest."""
    repo = get_hook_repository()
    deleted = repo.delete_hook(hook_id)
    if not deleted:
        raise HTTPException(404, f"Hook '{hook_id}' not found")

    return {"status": "success", "message": f"Hook '{hook_id}' deleted."}


@router.post("/{hook_id}/test", summary="Dry-run a hook with sample data")
async def test_hook(hook_id: str, req: TestHookRequest, user_data: User = Depends(get_current_user)):
    """Execute the hook script as a subprocess with simulated env vars.

    Returns the exit code, stdout, stderr — useful for testing before binding.
    """
    import subprocess

    repo = get_hook_repository()
    script_path = repo.get_hook_path(hook_id)
    if not script_path:
        raise HTTPException(404, f"Hook '{hook_id}' not found or script missing")

    import sys
    python_exe = sys.executable

    import json as _json
    # Normalize tool_input: accept both dict and pre-serialized string
    if isinstance(req.tool_input, dict):
        tool_input_str = _json.dumps(req.tool_input)
    elif isinstance(req.tool_input, str):
        tool_input_str = req.tool_input
    else:
        tool_input_str = str(req.tool_input)

    env = {
        **dict(__import__("os").environ),
        "IAF_HOOK_EVENT": req.event,
        "IAF_TOOL_NAME": req.tool_name,
        "IAF_TOOL_INPUT": tool_input_str,
    }

    try:
        proc = subprocess.run(
            [python_exe, str(script_path)],
            env=env,
            capture_output=True,
            text=True,
            timeout=15,
        )
        return {
            "status": "success",
            "exit_code": proc.returncode,
            "stdout": proc.stdout[:2000],
            "stderr": proc.stderr[:2000],
            "interpretation": (
                "ALLOW" if proc.returncode == 0
                else "APPROVAL_REQUIRED" if proc.returncode == 2
                else "BLOCKED"
            ),
        }
    except subprocess.TimeoutExpired:
        return {
            "status": "error",
            "exit_code": -1,
            "stdout": "",
            "stderr": "Hook timed out after 15 seconds",
            "interpretation": "TIMEOUT",
        }
    except Exception as e:
        raise HTTPException(500, f"Failed to run hook: {e}")
