# © 2024-25 Infosys Limited, Bangalore, India. All Rights Reserved.
"""
AgentOS API Endpoints - New endpoints for skill-based agents.

This is a completely standalone router — it does NOT modify any existing IAF endpoints.
Register it in main.py: app.include_router(agentos_router)

Endpoints:
    === Agent Lifecycle ===
    POST /agentos/agents                    — Create a skill-based agent (inline skills)
    POST /agentos/agents/from-folder        — Create from a folder structure
    GET  /agentos/agents                    — List all skill-based agents
    GET  /agentos/agents/{agent_id}         — Get agent details
    PUT  /agentos/agents/{agent_id}          — Update agent config & enterprise context
    DELETE /agentos/agents/{agent_id}       — Soft-delete (moves to recycle bin)

    === Recycle Bin ===
    GET  /agentos/agents/recycle-bin                        — List recycled skill agents
    POST /agentos/agents/recycle-bin/restore/{agent_id}     — Restore from recycle bin
    DELETE /agentos/agents/recycle-bin/permanent/{agent_id}  — Permanently delete

    === Skill Management ===
    GET  /agentos/agents/{agent_id}/skills              — List skills for an agent
    GET  /agentos/agents/{agent_id}/skills/{skill_name} — Get skill details
    POST /agentos/agents/{agent_id}/skills              — Add a skill (JSON)
    POST /agentos/agents/{agent_id}/skills/upload       — Add a skill (file upload)
    PUT  /agentos/agents/{agent_id}/skills/{skill_name} — Update a skill
    DELETE /agentos/agents/{agent_id}/skills/{skill_name} — Remove a skill

    === Skill File Management ===
    GET  /agentos/agents/{id}/skills/{name}/files              — List files in a skill
    POST /agentos/agents/{id}/skills/{name}/files              — Upload files (multipart)
    DELETE /agentos/agents/{id}/skills/{name}/files/{filename}  — Delete a file

    === Enterprise Context ===
    GET  /agentos/agents/{agent_id}/context         — Get enterprise context
    PUT  /agentos/agents/{agent_id}/context         — Update enterprise context

    === Audit ===
    GET  /agentos/audit/shell               — Shell audit logs
"""

import os
import json
import uuid
import shutil
from pathlib import Path
from typing import Dict, Optional, Any, List
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, UploadFile, File, Form, Query, Depends
from fastapi.responses import JSONResponse

from src.agentos.schemas import (
    SkillAgentOnboardingRequest,
    SkillAgentFromFolderRequest,
    AddSkillRequest,
    UpdateSkillRequest,
    RemoveSkillRequest,
    UpdateAgentRequest,
    UpdateEnterpriseContextRequest,
    AuditLogRequest,
)
from src.agentos.skill_loader import SkillLoader
from src.agentos.skill_router import SkillRouter
from src.agentos.enterprise_context import EnterpriseContextManager
from src.agentos.hardened_shell import HardenedShell, ShellAuditLogger
from src.agentos.hook_code_validator import validate_hook_code, validate_hooks_config
from src.auth.dependencies import get_current_user
from src.auth.models import User
from src.api.dependencies import ServiceProvider
from src.database.services import AgentService

try:
    from telemetry_wrapper import logger as log
except ImportError:
    import logging
    log = logging.getLogger(__name__)

try:
    import yaml
except ImportError:
    yaml = None


# ============================================================================
# Constants
# ============================================================================

# Base workspace directory (matches IAF's agent_workspaces/{department}/... pattern)
AGENT_WORKSPACES_BASE = os.getenv("AGENT_WORKSPACES_BASE", "./agent_workspaces")
AGENTOS_FOLDER_NAME = "agentos_agents"

# Global metadata directories (audit is cross-department)
AGENTOS_META_DIR = os.path.join(AGENT_WORKSPACES_BASE, "_agentos_meta")
AGENTOS_AUDIT_DIR = os.path.join(AGENTOS_META_DIR, "_audit")


# Use the shared hooks config validator from hook_code_validator module
_validate_hooks_config = validate_hooks_config


async def _ensure_agent_from_blob(agent_id: str, department: str = "General") -> bool:
    """Restore an agent's workspace from blob if agent_config.json is missing locally.

    Called by read-only endpoints (GET /agents/{id}, GET .../skills, etc.) so that
    a fresh/different node can serve agent data without a 404.
    Returns True if agent_config.json exists on disk after the attempt.
    """
    agent_dir = _get_agent_dir(agent_id, department)
    config_file = agent_dir / "agent_config.json"
    if config_file.exists():
        return True
    try:
        _sp = os.getenv('STORAGE_PROVIDER', '')
        if not _sp:
            return False
        from src.utils.workspace_blob_sync import WorkspaceBlobSync
        from src.storage import get_storage_client
        _client = get_storage_client(_sp)
        _syncer = WorkspaceBlobSync(
            storage_client=_client,
            workspace_root=AGENT_WORKSPACES_BASE,
            department=department,
            agent_id=agent_id,
        )
        report = await _syncer.check_and_restore_if_needed()
        if report and report.synced > 0:
            log.info(f"[BlobRestore] Restored {report.synced} files for agent {agent_id} from blob")
        return config_file.exists()
    except Exception as e:
        log.debug(f"[BlobRestore] agent restore skipped (non-critical): {e}")
        return config_file.exists()


def _schedule_blob_sync_for_agent(agent_id: str, department: str = "General"):
    """Fire-and-forget: sync agent's skills/config/enterprise_context to blob."""
    try:
        _sp = os.getenv('STORAGE_PROVIDER', '')
        if not _sp:
            return
        from src.utils.workspace_blob_sync import WorkspaceBlobSync
        from src.storage import get_storage_client
        _client = get_storage_client(_sp)
        _syncer = WorkspaceBlobSync(
            storage_client=_client,
            workspace_root=AGENT_WORKSPACES_BASE,
            department=department,
            agent_id=agent_id,
        )
        _syncer.schedule_skills_sync()
        _syncer.schedule_agent_data_sync()
    except Exception:
        pass  # Non-critical


def _schedule_blob_delete(blob_prefix: str, department: str = "General"):
    """Fire-and-forget: delete all blobs under a prefix after local deletion."""
    try:
        _sp = os.getenv('STORAGE_PROVIDER', '')
        if not _sp:
            return
        from src.utils.workspace_blob_sync import WorkspaceBlobSync
        from src.storage import get_storage_client
        _client = get_storage_client(_sp)
        _syncer = WorkspaceBlobSync(
            storage_client=_client,
            workspace_root=AGENT_WORKSPACES_BASE,
            department=department,
        )
        _syncer.schedule_blob_prefix_delete(blob_prefix, name="blob_delete_after_local_rm")
    except Exception:
        pass  # Non-critical

def _get_department_root(department: str = "General") -> Path:
    """Get the agentos_agents root for a specific department."""
    return Path(AGENT_WORKSPACES_BASE) / department / AGENTOS_FOLDER_NAME


def _get_agent_dir(agent_id: str, department: str = "General") -> Path:
    """Get agent directory: agent_workspaces/{department}/agentos_agents/{agent_id}/"""
    return _get_department_root(department) / agent_id


def _get_skills_dir(agent_id: str, department: str = "General") -> Path:
    return _get_agent_dir(agent_id, department) / "skills"


def _get_enterprise_dir(agent_id: str, department: str = "General") -> Path:
    return _get_agent_dir(agent_id, department) / "enterprise_context"


def _build_skill_md(
    skill_name: str,
    description: str = "",
    keywords: Optional[List[str]] = None,
    details: str = "",
    execution_mode: str = "react",
    category: str = "general",
    version: str = "1.0",
    databases: Optional[List[Dict[str, str]]] = None,
    hooks: Optional[Dict[str, Any]] = None,
    steps: Optional[List[Dict[str, Any]]] = None,
    worker_skills: Optional[List[Dict[str, str]]] = None,
    max_steps: Optional[int] = None,
    max_iterations: Optional[int] = None,
    quality_threshold: Optional[int] = None,
    evaluation_criteria: Optional[str] = None,
) -> str:
    """
    Build a well-formed SKILL.md string from structured fields.

    The UI sends simple fields (name, description, keywords, details,
    databases, hooks, steps, worker_skills, etc.) and this helper assembles
    them into the standard ``---`` frontmatter format that the SkillLoader expects.
    """
    lines: List[str] = ["---"]
    lines.append(f"name: {skill_name}")
    lines.append(f'version: "{version}"')
    lines.append(f'description: "{description}"')
    lines.append(f"execution_mode: {execution_mode}")
    if keywords:
        lines.append("triggers:")
        for kw in keywords:
            # Always quote to preserve types — YAML would parse 404 as int, true as bool
            lines.append(f'  - "{kw}"')
    else:
        lines.append("triggers: []")
    lines.append(f"category: {category}")

    # Mode-specific fields
    if steps and yaml:
        # Serialize steps into YAML — clean, human-readable
        steps_yaml = yaml.dump({"steps": steps}, default_flow_style=False, allow_unicode=True)
        for s_line in steps_yaml.strip().splitlines():
            lines.append(s_line)

    if worker_skills and yaml:
        ws_yaml = yaml.dump({"worker_skills": worker_skills}, default_flow_style=False, allow_unicode=True)
        for ws_line in ws_yaml.strip().splitlines():
            lines.append(ws_line)

    if max_steps is not None:
        lines.append(f"max_steps: {max_steps}")

    if max_iterations is not None:
        lines.append(f"max_iterations: {max_iterations}")

    if quality_threshold is not None:
        lines.append(f"quality_threshold: {quality_threshold}")

    if evaluation_criteria:
        lines.append(f'evaluation_criteria: "{evaluation_criteria}"')

    # Database connections (from Data Connector)
    if databases:
        lines.append("databases:")
        for db in databases:
            lines.append(f"  - connection_name: {db['connection_name']}")
            lines.append(f"    sql_mode: {db.get('sql_mode', 'read_only')}")

    # Skill-level lifecycle hooks
    if hooks and isinstance(hooks, dict):
        h_yaml = yaml.dump({"hooks": hooks}, default_flow_style=False, allow_unicode=True)
        for h_line in h_yaml.strip().splitlines():
            lines.append(h_line)

    lines.append("---")
    lines.append("")
    if details:
        lines.append(details)
    else:
        lines.append(f"# {skill_name}")
        lines.append("")
        lines.append("_Add detailed instructions, procedures, and knowledge here._")

    # ── Auto-inject database workflow section ──────────────────────────
    # When a skill declares database connections AND the user-provided
    # details do NOT already contain a workflow/database section, append
    # standardized instructions so the agent knows how to discover the
    # schema, query, and handle errors — without the user typing it.
    if databases:
        body_lower = (details or "").lower()
        already_has_workflow = any(
            marker in body_lower
            for marker in ["run_shell_command", "database_query_tool", "### workflow", "## database"]
        )
        if not already_has_workflow:
            lines.append("")
            lines.append("---")
            lines.append("")
            lines.append("## Database Access")
            lines.append("")
            for db in databases:
                conn = db["connection_name"]
                mode = db.get("sql_mode", "read_only")
                mode_label = "read-only" if mode == "read_only" else "read-write"
                lines.append(f"### Connection: `{conn}` ({mode_label})")
                lines.append("")
                lines.append("**Workflow — follow these steps in order:**")
                lines.append("")
                lines.append(
                    f'1. **Read the schema** first: `run_shell_command(command="cat /databases/{conn}/schema.md")`'
                )
                lines.append(
                    f'   - For large schemas, use targeted reads: `run_shell_command(command="sed -n \'1,50p\' /databases/{conn}/schema.md")`'
                )
                lines.append(
                    f'   - To find specific tables/columns: `run_shell_command(command="grep -C 3 \'column_name\' /databases/{conn}/schema.md")`'
                )
                lines.append("2. **Understand** the table and column names from the schema before writing any SQL.")
                lines.append(
                    f'3. **Execute SQL**: `database_query_tool(connection_name="{conn}", query="SELECT ...", limit=100)`'
                )
                lines.append(
                    f'4. **If a query fails**, read examples: `run_shell_command(command="cat /databases/{conn}/samples.md")`'
                )
                lines.append(
                    f'5. **Shell tips**: Use `stat` to check file size, `diff` to compare schemas, `grep -rni` to search across all DBs, pipes like `grep "table" schema.md | head -5`'
                )
                lines.append("")
                if mode == "read_only":
                    lines.append("> **This is a read-only connection.** Only `SELECT` queries are allowed.")
                else:
                    lines.append(
                        "> **This is a read-write connection.** `SELECT`, `INSERT`, `UPDATE`, and `DELETE` are allowed. "
                        "Always confirm destructive operations with the user first."
                    )
                lines.append("")

    return "\n".join(lines) + "\n"


def _resolve_skill_md_content(
    skill_name: str,
    skill_md_content: Optional[str],
    description: Optional[str] = None,
    keywords: Optional[List[str]] = None,
    details: Optional[str] = None,
    execution_mode: Optional[str] = None,
    category: Optional[str] = None,
    databases: Optional[List[Dict[str, str]]] = None,
    hooks: Optional[Dict[str, Any]] = None,
    steps: Optional[List[Dict[str, Any]]] = None,
    worker_skills: Optional[List[Dict[str, str]]] = None,
    max_steps: Optional[int] = None,
    max_iterations: Optional[int] = None,
    quality_threshold: Optional[int] = None,
    evaluation_criteria: Optional[str] = None,
) -> Optional[str]:
    """
    Resolve SKILL.md content: prefer raw content if provided, otherwise
    build from structured fields.  Returns None if nothing to write.
    """
    if skill_md_content:
        return skill_md_content
    # If at least one structured field was provided, generate the file
    if any(v is not None for v in [description, keywords, details, databases, hooks, steps, worker_skills]):
        return _build_skill_md(
            skill_name=skill_name,
            description=description or "",
            keywords=keywords,
            details=details or "",
            execution_mode=execution_mode or "react",
            category=category or "general",
            databases=databases,
            hooks=hooks,
            steps=steps,
            worker_skills=worker_skills,
            max_steps=max_steps,
            max_iterations=max_iterations,
            quality_threshold=quality_threshold,
            evaluation_criteria=evaluation_criteria,
        )
    return None


def _merge_skill_md_content(
    existing_content: str,
    skill_name: str,
    description: Optional[str] = None,
    keywords: Optional[List[str]] = None,
    details: Optional[str] = None,
    execution_mode: Optional[str] = None,
    category: Optional[str] = None,
    databases: Optional[List[Dict[str, str]]] = None,
    hooks: Optional[Dict[str, Any]] = None,
    steps: Optional[List[Dict[str, Any]]] = None,
    worker_skills: Optional[List[Dict[str, str]]] = None,
    max_steps: Optional[int] = None,
    max_iterations: Optional[int] = None,
    quality_threshold: Optional[int] = None,
    evaluation_criteria: Optional[str] = None,
) -> str:
    """
    Merge structured fields into an existing SKILL.md, preserving fields
    that the caller did NOT supply.

    Uses SkillLoader to parse the existing file, patches the changed
    fields, and regenerates a clean ``---``-delimited SKILL.md.
    """
    from src.agentos.skill_loader import SkillLoader
    import tempfile, shutil as _shutil

    # Parse existing content via a disposable SkillLoader
    tmpdir = Path(tempfile.mkdtemp())
    try:
        skill_dir = tmpdir / skill_name
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text(existing_content, encoding="utf-8")
        loader = SkillLoader(str(tmpdir))
        skill = loader.load(skill_name)
    finally:
        _shutil.rmtree(tmpdir, ignore_errors=True)

    if skill is None:
        # Cannot parse existing → fall back to full rebuild
        return _build_skill_md(
            skill_name=skill_name,
            description=description or "",
            keywords=keywords,
            details=details or "",
            execution_mode=execution_mode or "react",
            category=category or "general",
            databases=databases,
            hooks=hooks,
            steps=steps,
            worker_skills=worker_skills,
            max_steps=max_steps,
            max_iterations=max_iterations,
            quality_threshold=quality_threshold,
            evaluation_criteria=evaluation_criteria,
        )

    # Resolve hooks: use provided, or preserve existing from disk
    resolved_hooks = hooks
    if resolved_hooks is None and skill.hooks:
        resolved_hooks = skill.hooks
    elif resolved_hooks == {}:
        resolved_hooks = None

    return _build_skill_md(
        skill_name=skill.name,
        description=description if description is not None else skill.description,
        keywords=keywords if keywords is not None else skill.triggers,
        details=details if details is not None else skill.body,
        execution_mode=execution_mode if execution_mode is not None else skill.execution_mode,
        category=category if category is not None else skill.category,
        version=skill.version,
        databases=databases if databases is not None else skill.databases,
        hooks=resolved_hooks,
        steps=steps if steps is not None else (skill.steps or None),
        worker_skills=worker_skills if worker_skills is not None else (skill.worker_skills or None),
        max_steps=max_steps,
        max_iterations=max_iterations if max_iterations is not None else (skill.max_iterations if skill.max_iterations != 3 else None),
        quality_threshold=quality_threshold if quality_threshold is not None else (skill.quality_threshold if skill.quality_threshold != 7 else None),
        evaluation_criteria=evaluation_criteria if evaluation_criteria is not None else (skill.evaluation_criteria or None),
    )


def _resolve_agent_department(agent_id: str, department: Optional[str] = None) -> str:
    """
    Resolve the actual department where the agent's folder lives on disk.

    If *department* is provided AND the agent exists there, return it.
    Otherwise, scan all department folders to find the agent — this handles
    cross-department sharing where the requesting user's department differs
    from the agent owner's department.
    """
    base = Path(AGENT_WORKSPACES_BASE)

    # Fast path: check caller-supplied department first
    if department:
        candidate = base / department / AGENTOS_FOLDER_NAME / agent_id
        if candidate.exists():
            return department

    # Slow path: scan all departments to find the agent's actual home
    if base.exists():
        for dept_dir in base.iterdir():
            if dept_dir.is_dir() and not dept_dir.name.startswith("_"):
                agent_dir = dept_dir / AGENTOS_FOLDER_NAME / agent_id
                if agent_dir.exists():
                    return dept_dir.name

    # Fallback: use the provided department or "General"
    return department or "General"


# ============================================================================
# Authorization Helpers
# ============================================================================

_ADMIN_ROLES = {"Admin", "SuperAdmin"}


def _is_admin(user_data: "User") -> bool:
    """Return True if the user has Admin or SuperAdmin role."""
    return getattr(user_data, "role", "") in _ADMIN_ROLES





def _check_agent_ownership(config: dict, user_data: "User", agent_id: str) -> None:
    """Raise 403 if the current user is not the agent creator and not an admin.

    Only the **creator** of the agent or an **Admin/SuperAdmin** is allowed
    to modify agent configuration (additional_paths, mount roots, etc.).
    """
    if _is_admin(user_data):
        return  # admins can modify any agent

    created_by = config.get("created_by", "")
    if created_by and created_by != user_data.email:
        raise HTTPException(
            status_code=403,
            detail=(
                f"Permission denied: only the agent creator ('{created_by}') "
                f"or an Admin can update agent '{agent_id}'."
            ),
        )


def _require_admin_for_absolute_roots(
    allowed_roots: Optional[list],
    user_data: "User",
) -> None:
    """Raise 403 if a non-admin tries to set allowed_absolute_mount_roots."""
    if allowed_roots and not _is_admin(user_data):
        raise HTTPException(
            status_code=403,
            detail=(
                "Permission denied: only Admin or SuperAdmin users can set "
                "'allowed_absolute_mount_roots'. Contact your administrator."
            ),
        )


def _derive_absolute_roots(additional_paths_dicts: list[dict]) -> list[str]:
    """Auto-derive ``allowed_absolute_mount_roots`` from absolute entries.

    For each ``additional_paths`` entry with ``absolute: true``, takes the
    parent directory of the path as an allowed root.  This ensures the
    shell's security check (``_allowed_abs_roots``) is satisfied without
    the user having to specify roots separately.

    Returns a de-duplicated sorted list of root strings.
    """
    from pathlib import Path as _P
    roots: set[str] = set()
    for entry in additional_paths_dicts:
        if entry.get("absolute"):
            raw = entry.get("path", "").strip()
            if raw:
                # Use the resolved parent of the entry path as the root.
                # If the path itself is a directory, use it directly.
                p = _P(raw).resolve()
                if p.is_dir():
                    roots.add(str(p))
                else:
                    roots.add(str(p.parent))
    return sorted(roots)


# ============================================================================
# DB Sync Helper
# ============================================================================

async def _save_agent_to_db(
    agent_id: str,
    agent_name: str,
    description: str,
    model_name: str,
    department: str,
    email: str,
    skill_names: list,
    welcome_message: str = "Hello, how can I help you?",
    db_connection_names: list = None,
):
    """
    Insert an AgentOS skill-based agent into the IAF agent_table
    so that it appears in the UI alongside normal agents.
    """
    try:
        agent_service: AgentService = ServiceProvider.get_agent_service()
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        agent_data = {
            "agentic_application_id": agent_id,
            "agentic_application_name": agent_name,
            "agentic_application_description": description or f"Skill-based agent with skills: {', '.join(skill_names)}",
            "agentic_application_workflow_description": f"Skill-based agent powered by AgentOS. Skills: {', '.join(skill_names)}",
            "agentic_application_type": "skill_agent",
            "model_name": model_name or "gpt-4o",
            "system_prompt": json.dumps({"type": "skill_agent", "skills": skill_names}),
            "tools_id": json.dumps([]),
            "created_by": email,
            "department_name": department,
            "created_on": now,
            "updated_on": now,
            "is_public": False,
            "validation_criteria": "[]",
            "welcome_message": welcome_message,
            "db_connection_names": json.dumps(db_connection_names or []),
        }
        success = await agent_service.agent_repo.save_agent_record(agent_data)
        if success:
            log.info(f"AgentOS agent '{agent_id}' registered in agent_table for UI visibility.")
        else:
            log.warning(f"AgentOS agent '{agent_id}' could not be registered in agent_table (may already exist).")
        return success
    except Exception as e:
        log.error(f"Failed to register AgentOS agent '{agent_id}' in agent_table: {e}")
        return False


async def _delete_agent_from_db(agent_id: str):
    """Remove an AgentOS agent from the IAF agent_table (hard delete — used only as fallback)."""
    try:
        agent_service: AgentService = ServiceProvider.get_agent_service()
        success = await agent_service.agent_repo.delete_agent_record(agent_id)
        if success:
            log.info(f"AgentOS agent '{agent_id}' removed from agent_table.")
        return success
    except Exception as e:
        log.error(f"Failed to remove AgentOS agent '{agent_id}' from agent_table: {e}")
        return False


async def _soft_delete_agent(agent_id: str, user_email: str, is_admin: bool = True):
    """
    Soft-delete: move agent to recycle_agent table via the standard IAF
    AgentService.delete_agent() which handles dependency checks, tag cleanup,
    tool-agent mapping cleanup, and recycle-bin insertion.
    """
    try:
        agent_service: AgentService = ServiceProvider.get_agent_service()
        result = await agent_service.delete_agent(
            agentic_application_id=agent_id,
            user_id=user_email,
            is_admin=is_admin,
        )
        return result
    except Exception as e:
        log.error(f"Soft-delete failed for agent '{agent_id}': {e}")
        return {"message": str(e), "is_delete": False}


def _archive_agent_dir(agent_dir: Path):
    """
    Move the agent's disk folder into a `.recycle_bin` sibling folder
    so it can be restored later.  Returns the archive path or None.
    """
    if not agent_dir.exists():
        return None
    recycle_root = agent_dir.parent / ".recycle_bin"
    recycle_root.mkdir(parents=True, exist_ok=True)
    dest = recycle_root / agent_dir.name
    if dest.exists():
        shutil.rmtree(dest, ignore_errors=True)
    shutil.move(str(agent_dir), str(dest))
    log.info(f"Archived agent folder: {agent_dir} → {dest}")
    return dest


def _restore_agent_dir(agent_id: str, department: str):
    """
    Restore the agent's disk folder from `.recycle_bin` back to its
    original location.  Returns True on success.
    """
    base = Path(AGENT_WORKSPACES_BASE) / department / AGENTOS_FOLDER_NAME
    recycle_root = base / ".recycle_bin"
    archived = recycle_root / agent_id
    if not archived.exists():
        log.warning(f"No archived folder for agent '{agent_id}' in {recycle_root}")
        return False
    dest = base / agent_id
    if dest.exists():
        shutil.rmtree(dest, ignore_errors=True)
    shutil.move(str(archived), str(dest))
    log.info(f"Restored agent folder: {archived} → {dest}")
    return True


def _ensure_agent_completeness(agent_id: str, department: str) -> List[str]:
    """
    After a restore from recycle bin, ensure critical files exist.
    If enterprise_context/ or agent_config.json are missing, regenerate defaults.
    Returns a list of file names that were regenerated.
    """
    agent_dir = _get_agent_dir(agent_id, department)
    if not agent_dir.exists():
        return []

    regenerated: List[str] = []
    skills_dir = agent_dir / "skills"

    # --- Ensure enterprise_context/Enterprise_Context.md ---
    ec_dir = agent_dir / "enterprise_context"
    ec_file = ec_dir / "Enterprise_Context.md"
    if not ec_file.exists():
        ec_dir.mkdir(parents=True, exist_ok=True)
        # Derive agent name from skills index or folder for a meaningful default
        agent_name = agent_id
        config_file = agent_dir / "agent_config.json"
        if config_file.exists():
            try:
                cfg = json.loads(config_file.read_text(encoding="utf-8"))
                agent_name = cfg.get("agent_name", agent_id)
            except Exception:
                pass
        default_ec = (
            f"# Enterprise Context — {agent_name}\n\n"
            "_Edit this file to provide company-wide context, policies, "
            "and guidelines that apply across all skills._\n"
        )
        ec_file.write_text(default_ec, encoding="utf-8")
        regenerated.append("enterprise_context/Enterprise_Context.md")
        log.info(f"[Restore] Regenerated enterprise_context for agent {agent_id}")

        # Sync skills table into Enterprise_Context.md
        if skills_dir.exists():
            _sync_enterprise_context_skills(agent_id, skills_dir, department)

    # --- Ensure agent_config.json ---
    config_file = agent_dir / "agent_config.json"
    if not config_file.exists():
        # Build minimal config from what's on disk + known defaults
        skill_names = []
        default_skill = None
        if skills_dir.exists():
            index_file = skills_dir / "_index.yaml"
            if index_file.exists() and yaml:
                try:
                    index_data = yaml.safe_load(index_file.read_text(encoding="utf-8"))
                    default_skill = index_data.get("default_skill")
                    skill_names = list((index_data.get("skills") or {}).keys())
                except Exception:
                    pass
            if not skill_names:
                skill_names = [
                    d.name for d in skills_dir.iterdir()
                    if d.is_dir() and not d.name.startswith("_") and not d.name.startswith(".")
                ]

        config = {
            "agent_id": agent_id,
            "agent_name": agent_id,
            "agent_description": "Restored skill agent",
            "model_name": "gpt-4o",
            "department_name": department,
            "created_by": "system_restore",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "default_skill": default_skill or (skill_names[0] if skill_names else None),
            "skill_count": len(skill_names),
            "enterprise_context_enabled": True,
            "restored": True,
        }
        config_file.write_text(json.dumps(config, indent=2), encoding="utf-8")
        regenerated.append("agent_config.json")
        log.info(f"[Restore] Regenerated agent_config.json for agent {agent_id}")

    return regenerated


def _permanently_delete_agent_dir(agent_id: str, department: str):
    """
    Permanently remove the archived agent folder from `.recycle_bin`.
    Also removes any leftover live folder.
    Also deletes corresponding blobs so they don't resurrect on next restore.
    """
    base = Path(AGENT_WORKSPACES_BASE) / department / AGENTOS_FOLDER_NAME
    # Remove from recycle bin
    recycle_root = base / ".recycle_bin"
    archived = recycle_root / agent_id
    if archived.exists():
        shutil.rmtree(archived, ignore_errors=True)
        log.info(f"Permanently deleted archived folder: {archived}")
    # Remove live copy if it somehow still exists
    live = base / agent_id
    if live.exists():
        shutil.rmtree(live, ignore_errors=True)
        log.info(f"Permanently deleted live folder: {live}")
    # Delete agent blobs (both live and recycle-bin prefixes)
    _schedule_blob_delete(
        f"{department}/{AGENTOS_FOLDER_NAME}/{agent_id}/",
        department=department,
    )
    _schedule_blob_delete(
        f"{department}/{AGENTOS_FOLDER_NAME}/.recycle_bin/{agent_id}/",
        department=department,
    )


# ============================================================================
# Router
# ============================================================================

router = APIRouter(prefix="/agentos", tags=["AgentOS - Skill-Based Agents"])

# Include the Code Executor sub-router (Phase 5)
# Endpoints: /agentos/code-executor/execute, /execute-code, /task/{id}, etc.
from src.agentos.code_executor.endpoints import code_executor_router
router.include_router(code_executor_router)


# ============================================================================
# Agent Lifecycle
# ============================================================================

@router.post("/agents", summary="Create a skill-based agent")
async def create_skill_agent(request: SkillAgentOnboardingRequest, user_data: User = Depends(get_current_user)):
    """
    Create a new skill-based agent with inline SKILL.md definitions.
    Department is resolved from the authenticated user's JWT token.
    
    This creates a full folder structure on disk:
    ```
    agent_workspaces/{department}/agentos_agents/{agent_id}/
    ├── agent_config.json
    ├── skills/
    │   ├── _index.yaml
    │   ├── skill_1/
    │   │   ├── SKILL.md
    │   │   ├── INSTRUCTIONS.md (optional)
    │   │   └── EXAMPLES.md (optional)
    │   └── skill_2/
    │       └── SKILL.md
    └── enterprise_context/
        ├── Enterprise_Context.md
        ├── contexts/
        ├── policies/
        └── entity_guide.md
    ```
    """
    department = user_data.department_name or "General"
    email = user_data.email

    # C1: Only admins can set allowed_absolute_mount_roots
    _require_admin_for_absolute_roots(request.allowed_absolute_mount_roots, user_data)

    agent_id = f"skl_{uuid.uuid4().hex[:12]}"
    agent_dir = _get_agent_dir(agent_id, department)

    log.info(f"[PVC:agent_workspaces] START create_skill_agent — agent_id={agent_id}, name='{request.agent_name}', department='{department}', skills={[s.skill_name for s in request.skills]}, path='{agent_dir}', mountPath=/app/agent_workspaces")

    try:
        # Create directory structure
        skills_dir = agent_dir / "skills"
        skills_dir.mkdir(parents=True, exist_ok=True)

        # Write each skill
        index_skills = {}
        for skill_def in request.skills:
            skill_folder = skills_dir / skill_def.skill_name
            skill_folder.mkdir(parents=True, exist_ok=True)

            # Write SKILL.md (structured fields or raw content)
            skill_md = _resolve_skill_md_content(
                skill_name=skill_def.skill_name,
                skill_md_content=skill_def.skill_md_content,
                description=skill_def.description,
                keywords=skill_def.keywords,
                details=skill_def.details,
                execution_mode=skill_def.execution_mode,
                category=skill_def.category,
                databases=[db.model_dump() for db in skill_def.databases] if skill_def.databases else None,
                hooks=skill_def.hooks,
                steps=[s.model_dump(by_alias=True, exclude_none=True) for s in skill_def.steps] if skill_def.steps else None,
                worker_skills=[w.model_dump() for w in skill_def.worker_skills] if skill_def.worker_skills else None,
                max_steps=skill_def.max_steps,
                max_iterations=skill_def.max_iterations,
                quality_threshold=skill_def.quality_threshold,
                evaluation_criteria=skill_def.evaluation_criteria,
            )
            if not skill_md:
                raise HTTPException(
                    status_code=400,
                    detail=f"Skill '{skill_def.skill_name}': provide either 'skill_md_content' or at least one of 'description', 'keywords', 'details'.",
                )
            (skill_folder / "SKILL.md").write_text(skill_md, encoding="utf-8")

            # Write optional companion files
            if skill_def.instructions_md_content:
                (skill_folder / "INSTRUCTIONS.md").write_text(
                    skill_def.instructions_md_content, encoding="utf-8"
                )
            if skill_def.examples_md_content:
                (skill_folder / "EXAMPLES.md").write_text(
                    skill_def.examples_md_content, encoding="utf-8"
                )

            # Write additional files (api.md, credentials.md, etc.)
            if skill_def.additional_files:
                for fname, fcontent in skill_def.additional_files.items():
                    safe_name = Path(fname).name  # prevent path traversal
                    if safe_name and safe_name not in ("SKILL.md", "INSTRUCTIONS.md", "EXAMPLES.md"):
                        (skill_folder / safe_name).write_text(fcontent, encoding="utf-8")

            # Extract description for index
            loader = SkillLoader(str(skills_dir))
            skill = loader.load(skill_def.skill_name)
            index_skills[skill_def.skill_name] = {
                "description": skill.description if skill else skill_def.skill_name,
                "keywords": skill.triggers if skill else [],
                "category": skill.category if skill else "general",
                "status": "active",
            }

        # Write _index.yaml
        if yaml:
            index_data = {
                "version": "1.0",
                "default_skill": request.default_skill,
                "skills": index_skills,
            }
            (skills_dir / "_index.yaml").write_text(
                yaml.dump(index_data, default_flow_style=False, allow_unicode=True),
                encoding="utf-8",
            )

        # Write enterprise context (always create the directory + default file)
        ec_dir = _get_enterprise_dir(agent_id, department)
        ec_dir.mkdir(parents=True, exist_ok=True)

        if request.enterprise_context and request.enterprise_context.enterprise_context_md:
            (ec_dir / "Enterprise_Context.md").write_text(
                request.enterprise_context.enterprise_context_md, encoding="utf-8"
            )
        else:
            # Create a default Enterprise_Context.md so context is always available
            default_ec = (
                f"# Enterprise Context — {request.agent_name}\n\n"
                "_Edit this file to provide company-wide context, policies, "
                "and guidelines that apply across all skills._\n"
            )
            (ec_dir / "Enterprise_Context.md").write_text(default_ec, encoding="utf-8")

        if request.enterprise_context:
            ec = request.enterprise_context
            if ec.skill_contexts:
                ctx_dir = ec_dir / "contexts"
                ctx_dir.mkdir(exist_ok=True)
                for name, content in ec.skill_contexts.items():
                    (ctx_dir / f"{name}_context.md").write_text(content, encoding="utf-8")

            if ec.policies:
                pol_dir = ec_dir / "policies"
                pol_dir.mkdir(exist_ok=True)
                for name, content in ec.policies.items():
                    (pol_dir / f"{name}.md").write_text(content, encoding="utf-8")

            if ec.entity_guide:
                (ec_dir / "entity_guide.md").write_text(ec.entity_guide, encoding="utf-8")

        # Write agent config
        config = {
            "agent_id": agent_id,
            "agent_name": request.agent_name,
            "agent_description": request.agent_description,
            "model_name": request.model_name,
            "department_name": department,
            "created_by": email,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "default_skill": request.default_skill,
            "skill_count": len(request.skills),
            "enterprise_context_enabled": True,
        }
        # Store additional_paths if provided
        if request.additional_paths:
            config["additional_paths"] = [
                {"path": ap.path, "permission": ap.permission, **(dict(absolute=True) if ap.absolute else {})}
                for ap in request.additional_paths
            ]
        # Store allowed_absolute_mount_roots if provided (auto-derive if absent)
        if request.allowed_absolute_mount_roots:
            config["allowed_absolute_mount_roots"] = list(request.allowed_absolute_mount_roots)
        elif request.additional_paths:
            derived = _derive_absolute_roots(config.get("additional_paths", []))
            if derived:
                config["allowed_absolute_mount_roots"] = derived
        (agent_dir / "agent_config.json").write_text(
            json.dumps(config, indent=2), encoding="utf-8"
        )

        # Write config.yaml with hooks if provided
        _has_yaml_updates = request.hooks and yaml
        if _has_yaml_updates:
            # Validate hooks config structure before writing
            hook_errors = _validate_hooks_config(request.hooks)
            if hook_errors:
                error_detail = "; ".join(hook_errors)
                raise HTTPException(422, detail=f"Invalid hooks configuration: {error_detail}")
            yaml_config: Dict[str, Any] = {}
            # Load existing config.yaml if present
            config_yaml_path = agent_dir / "config.yaml"
            if config_yaml_path.exists():
                try:
                    yaml_config = yaml.safe_load(config_yaml_path.read_text(encoding="utf-8")) or {}
                except Exception:
                    yaml_config = {}
            if request.hooks:
                yaml_config["hooks"] = request.hooks
            config_yaml_path.write_text(
                yaml.dump(yaml_config, default_flow_style=False, allow_unicode=True),
                encoding="utf-8",
            )
            log.info(f"Wrote config.yaml for agent {agent_id} (hooks={bool(request.hooks)})")

        # Populate Available Skills table in Enterprise_Context.md
        _sync_enterprise_context_skills(agent_id, skills_dir, department)

        log.info(f"Created skill-based agent: {agent_id} ({request.agent_name}) with {len(request.skills)} skills")

        # Collect all DB connection names from per-skill databases + agent-level
        all_db_connections = set()
        if request.db_connection_names:
            all_db_connections.update(request.db_connection_names)
        for skill_def in request.skills:
            if skill_def.databases:
                for db in skill_def.databases:
                    all_db_connections.add(db.connection_name)
        all_db_connections_list = sorted(all_db_connections) if all_db_connections else []
        if all_db_connections_list:
            log.info(f"Skill agent {agent_id} has DB connections: {all_db_connections_list}")

        # Register in IAF agent_table so it shows up in the UI
        await _save_agent_to_db(
            agent_id=agent_id,
            agent_name=request.agent_name,
            description=request.agent_description,
            model_name=request.model_name,
            department=department,
            email=email,
            skill_names=list(index_skills.keys()),
            db_connection_names=all_db_connections_list,
        )

        # --- Sync agent workspace to blob storage ---
        _schedule_blob_sync_for_agent(agent_id, department)

        log.info(f"[PVC:agent_workspaces] END create_skill_agent — agent_id={agent_id}, name='{request.agent_name}', department='{department}', skills_created={list(index_skills.keys())}, path='{agent_dir}', mountPath=/app/agent_workspaces")

        return {
            "status": "success",
            "agent_id": agent_id,
            "agent_name": request.agent_name,
            "skills_created": list(index_skills.keys()),
            "enterprise_context_enabled": True,
        }

    except Exception as e:
        # Cleanup on failure
        if agent_dir.exists():
            shutil.rmtree(agent_dir, ignore_errors=True)
        log.error(f"[PVC:agent_workspaces] FAILED create_skill_agent — agent_id={agent_id}, error={e}, mountPath=/app/agent_workspaces")
        raise HTTPException(status_code=500, detail=f"Failed to create agent: {str(e)}")


@router.post("/agents/from-folder", summary="Create agent from folder structure")
async def create_agent_from_folder(request: SkillAgentFromFolderRequest, user_data: User = Depends(get_current_user)):
    """
    Create a skill-based agent from a pre-existing folder structure.
    
    Expected folder structure:
    ```
    {folder_path}/
    ├── skills/
    │   ├── _index.yaml (optional, auto-generated if missing)
    │   ├── skill_1/SKILL.md
    │   └── skill_2/SKILL.md
    └── enterprise_context/ (optional)
        ├── Enterprise_Context.md
        ├── contexts/
        └── policies/
    ```
    """
    source = Path(request.folder_path)
    if not source.exists():
        raise HTTPException(status_code=400, detail=f"Folder not found: {request.folder_path}")

    # Validate skills directory exists
    source_skills = source / "skills"
    if not source_skills.exists():
        raise HTTPException(
            status_code=400,
            detail=f"No 'skills/' directory found in {request.folder_path}. Expected skills/{{skill_name}}/SKILL.md"
        )

    department = user_data.department_name or "General"
    email = user_data.email
    agent_id = f"skl_{uuid.uuid4().hex[:12]}"
    agent_dir = _get_agent_dir(agent_id, department)

    try:
        # Copy the entire folder structure
        shutil.copytree(str(source), str(agent_dir))

        # Ensure skills dir is at the right level
        final_skills_dir = agent_dir / "skills"
        if not final_skills_dir.exists():
            raise HTTPException(status_code=400, detail="Skills directory not found after copy.")

        # Generate _index.yaml if missing
        index_file = final_skills_dir / "_index.yaml"
        if not index_file.exists() and yaml:
            loader = SkillLoader(str(final_skills_dir))
            skills = loader.load_all()
            index_data = {
                "version": "1.0",
                "default_skill": "general",
                "skills": {
                    s.name: {
                        "description": s.description,
                        "keywords": s.triggers,
                        "category": s.category,
                        "status": "active",
                    }
                    for s in skills
                },
            }
            index_file.write_text(
                yaml.dump(index_data, default_flow_style=False, allow_unicode=True),
                encoding="utf-8",
            )
            log.info(f"Auto-generated _index.yaml with {len(skills)} skills")

        # Count skills
        loader = SkillLoader(str(final_skills_dir))
        skill_names = loader.list_skill_names()

        # Ensure enterprise context directory + default file always exist
        ec_dir = agent_dir / "enterprise_context"
        if not ec_dir.exists():
            ec_dir.mkdir(parents=True, exist_ok=True)
        ec_file = ec_dir / "Enterprise_Context.md"
        if not ec_file.exists():
            default_ec = (
                f"# Enterprise Context — {request.agent_name}\n\n"
                "_Edit this file to provide company-wide context, policies, "
                "and guidelines that apply across all skills._\n"
            )
            ec_file.write_text(default_ec, encoding="utf-8")

        # Sync Available Skills table into Enterprise_Context.md
        _sync_enterprise_context_skills(agent_id, agent_dir / "skills", department)

        # Write agent config
        config = {
            "agent_id": agent_id,
            "agent_name": request.agent_name,
            "agent_description": request.agent_description,
            "model_name": request.model_name,
            "department_name": department,
            "created_by": email,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "source_folder": request.folder_path,
            "skill_count": len(skill_names),
            "enterprise_context_enabled": True,
        }
        (agent_dir / "agent_config.json").write_text(
            json.dumps(config, indent=2), encoding="utf-8"
        )

        log.info(f"Created agent from folder: {agent_id} ({request.agent_name}) with {len(skill_names)} skills")

        # Register in IAF agent_table so it shows up in the UI
        await _save_agent_to_db(
            agent_id=agent_id,
            agent_name=request.agent_name,
            description=request.agent_description,
            model_name=request.model_name,
            department=department,
            email=email,
            skill_names=skill_names,
        )

        # --- Sync agent workspace to blob storage ---
        _schedule_blob_sync_for_agent(agent_id, department)

        return {
            "status": "success",
            "agent_id": agent_id,
            "agent_name": request.agent_name,
            "skills_discovered": skill_names,
            "enterprise_context_enabled": True,
        }

    except HTTPException:
        raise
    except Exception as e:
        if agent_dir.exists():
            shutil.rmtree(agent_dir, ignore_errors=True)
        log.error(f"Failed to create agent from folder: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to create agent: {str(e)}")


@router.get("/agents", summary="List all skill-based agents")
async def list_skill_agents(user_data: User = Depends(get_current_user)):
    """List all skill-based agents for the authenticated user's department."""
    department = user_data.department_name or "General"
    base = Path(AGENT_WORKSPACES_BASE)
    if not base.exists():
        return {"agents": [], "total": 0}

    agents = []

    def _scan_department(dept_dir: Path):
        """Scan a department folder for agentos agents."""
        agentos_dir = dept_dir / AGENTOS_FOLDER_NAME
        if not agentos_dir.exists():
            return
        for d in sorted(agentos_dir.iterdir()):
            if d.is_dir() and not d.name.startswith("_"):
                config_file = d / "agent_config.json"
                if config_file.exists():
                    try:
                        config = json.loads(config_file.read_text(encoding="utf-8"))
                        # Ensure department_name is in the response
                        if "department_name" not in config:
                            config["department_name"] = dept_dir.name
                        # Ensure additional_paths is always present for the UI
                        config.setdefault("additional_paths", [])
                        config.setdefault("allowed_absolute_mount_roots", [])
                        agents.append(config)
                    except Exception:
                        pass

    # Filter by user's department
    dept_path = base / department
    if dept_path.is_dir():
        _scan_department(dept_path)

    return {"agents": agents, "total": len(agents)}


# ---------------------------------------------------------------------------
# Recycle Bin — List / Restore / Permanent Delete
# (Defined BEFORE /agents/{agent_id} so FastAPI doesn't capture these as IDs)
# ---------------------------------------------------------------------------

@router.get("/agents/recycle-bin", summary="List skill agents in the recycle bin")
async def list_recycled_agents(user_data: User = Depends(get_current_user)):
    """Return all skill-based agents currently in the recycle bin.

    DB records are enriched with details from the archived disk folder
    (agent_config.json) so the UI receives full agent metadata (skills,
    additional_paths, model, etc.) even after soft-delete.
    """
    try:
        agent_service: AgentService = ServiceProvider.get_agent_service()
        department = user_data.department_name or "General"

        if (user_data.role or "").lower() == "super_admin":
            agents = await agent_service.get_all_agents_from_recycle_bin()
        else:
            agents = await agent_service.get_all_agents_from_recycle_bin(department_name=department)

        # Filter to skill_agent type only
        skill_agents = [
            a for a in (agents or [])
            if a.get("agentic_application_type") == "skill_agent"
        ]

        # Enrich each record with disk-level details from .recycle_bin/
        for agent in skill_agents:
            aid = agent.get("agentic_application_id", "")
            dept = agent.get("department_name") or department
            if not aid:
                continue
            archived_dir = (
                Path(AGENT_WORKSPACES_BASE) / dept / AGENTOS_FOLDER_NAME / ".recycle_bin" / aid
            )
            config_file = archived_dir / "agent_config.json"
            if config_file.exists():
                try:
                    disk_config = json.loads(config_file.read_text(encoding="utf-8"))
                    # Merge disk details into the DB record; DB fields take
                    # precedence for shared keys (name, department, etc.)
                    for key, value in disk_config.items():
                        if key not in agent:
                            agent[key] = value
                    # Always supply these from disk if present
                    for key in (
                        "skill_count", "default_skill", "enterprise_context_enabled",
                        "additional_paths", "allowed_absolute_mount_roots",
                    ):
                        if key in disk_config:
                            agent[key] = disk_config[key]
                except Exception:
                    pass
            # Ensure consistent defaults for the UI
            agent.setdefault("additional_paths", [])
            agent.setdefault("allowed_absolute_mount_roots", [])
            agent.setdefault("skill_count", 0)

        return {"agents": skill_agents, "count": len(skill_agents)}
    except Exception as e:
        log.error(f"Failed to list recycled agents: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/agents/recycle-bin/restore/{agent_id}", summary="Restore a skill agent from the recycle bin")
async def restore_skill_agent(agent_id: str, user_data: User = Depends(get_current_user)):
    """
    Restore a previously deleted skill agent:
    1. Moves the DB record from `recycle_agent` back to `agent_table`.
    2. Restores the disk folder from `.recycle_bin/`.
    3. Re-establishes tag/tool mappings.
    4. Ensures enterprise_context/ and agent_config.json exist (regenerates if missing).
    """
    department = user_data.department_name or "General"

    try:
        agent_service: AgentService = ServiceProvider.get_agent_service()
        result = await agent_service.restore_agent(
            agentic_application_id=agent_id,
            department_name=department,
        )
    except Exception as e:
        log.error(f"Restore failed for agent '{agent_id}': {e}")
        raise HTTPException(status_code=500, detail=str(e))

    if not result.get("is_restored"):
        raise HTTPException(status_code=400, detail=result.get("message", "Restore failed."))

    # Restore the disk folder
    dept = _resolve_agent_department(agent_id, department)
    disk_restored = _restore_agent_dir(agent_id, dept)

    # --- Ensure critical files exist after restore (enterprise_context, agent_config.json) ---
    regenerated = _ensure_agent_completeness(agent_id, dept)

    # Trigger blob sync so blob is up-to-date after restore
    _schedule_blob_sync_for_agent(agent_id, dept)

    log.info(f"Restored skill-based agent: {agent_id} by {user_data.email} (disk={disk_restored}, regenerated={regenerated})")

    return {
        "status": "success",
        "agent_id": agent_id,
        "restored": True,
        "disk_restored": disk_restored,
        "regenerated_files": regenerated,
        "message": result.get("message", "Agent restored."),
    }


@router.api_route("/agents/recycle-bin/permanent/{agent_id}", methods=["DELETE", "POST"], summary="Permanently delete a skill agent")
async def permanent_delete_skill_agent(agent_id: str, user_data: User = Depends(get_current_user)):
    """
    Permanently remove a skill agent from the recycle bin.
    Destroys both the DB recycle record and the archived disk folder.
    This action is irreversible.
    """
    department = user_data.department_name or "General"

    try:
        agent_service: AgentService = ServiceProvider.get_agent_service()
        result = await agent_service.delete_agent_from_recycle_bin(
            agentic_application_id=agent_id,
            department_name=department,
        )
    except Exception as e:
        log.error(f"Permanent delete failed for agent '{agent_id}': {e}")
        raise HTTPException(status_code=500, detail=str(e))

    if not result.get("is_delete"):
        raise HTTPException(status_code=400, detail=result.get("message", "Permanent delete failed."))

    # Remove disk folder from recycle bin & any live leftover
    dept = _resolve_agent_department(agent_id, department)
    _permanently_delete_agent_dir(agent_id, dept)

    log.info(f"Permanently deleted skill-based agent: {agent_id} by {user_data.email}")

    return {
        "status": "success",
        "agent_id": agent_id,
        "permanently_deleted": True,
        "message": result.get("message", "Agent permanently deleted."),
    }


@router.get("/agents/{agent_id}", summary="Get agent details")
async def get_skill_agent(agent_id: str, user_data: User = Depends(get_current_user)):
    """Get full details of a skill-based agent."""
    department = user_data.department_name or "General"
    # Access control: same pattern as react agent (only SuperAdmin bypasses dept filter)
    if getattr(user_data, "role", "") != "SuperAdmin":
        agent_service: AgentService = ServiceProvider.get_agent_service()
        if not await agent_service.get_agent(agentic_application_id=agent_id, department_name=department):
            raise HTTPException(status_code=404, detail="Agent not found.")
    department = _resolve_agent_department(agent_id, department)
    agent_dir = _get_agent_dir(agent_id, department)
    config_file = agent_dir / "agent_config.json"

    # Auto-restore from blob if agent data is missing locally (fresh node)
    if not config_file.exists():
        await _ensure_agent_from_blob(agent_id, department)

    # Ensure enterprise_context & agent_config exist (regenerate if missing)
    _ensure_agent_completeness(agent_id, department)

    # If still not found, check the recycle bin (.recycle_bin/ folder)
    is_recycled = False
    if not config_file.exists():
        recycle_dir = agent_dir.parent / ".recycle_bin" / agent_id
        recycle_config = recycle_dir / "agent_config.json"
        if recycle_config.exists():
            agent_dir = recycle_dir
            config_file = recycle_config
            is_recycled = True
        else:
            raise HTTPException(status_code=404, detail=f"Agent '{agent_id}' not found in department '{department}'.")

    config = json.loads(config_file.read_text(encoding="utf-8"))
    # Ensure additional_paths is always present for the UI
    config.setdefault("additional_paths", [])
    config.setdefault("allowed_absolute_mount_roots", [])

    # Load skills info — use agent_dir which may be the recycle_bin path
    skills_dir = agent_dir / "skills"
    loader = SkillLoader(str(skills_dir))
    skills = []
    for skill in loader.load_all():
        skills.append(skill.to_dict())

    # Check enterprise context
    ec_dir = agent_dir / "enterprise_context"
    ec_info = None
    if ec_dir.exists():
        ec_manager = EnterpriseContextManager(str(ec_dir))
        ec_info = ec_manager.list_available_contexts()

    # Load hooks from config.yaml if present
    hooks = {}
    if yaml:
        config_yaml_path = agent_dir / "config.yaml"
        if config_yaml_path.exists():
            try:
                yaml_config = yaml.safe_load(config_yaml_path.read_text(encoding="utf-8")) or {}
                hooks = yaml_config.get("hooks", {})
            except Exception:
                pass

    response = {
        "config": config,
        "skills": skills,
        "enterprise_context": ec_info,
        "hooks": hooks,
    }
    if is_recycled:
        response["is_recycled"] = True

    return response


@router.put("/agents/{agent_id}", summary="Update agent config and enterprise context")
@router.post("/agents/{agent_id}/update", summary="Update agent config and enterprise context")
async def update_skill_agent(agent_id: str, request: UpdateAgentRequest, user_data: User = Depends(get_current_user)):
    """
    Update a skill-based agent's configuration and/or enterprise context.

    Enterprise context behaviour:
    - If ``enterprise_context.enterprise_context_md`` is provided **and** differs
      from the currently saved file, the file is replaced with the new content.
    - Otherwise (not provided or identical) the Available Skills table inside
      ``Enterprise_Context.md`` is regenerated automatically from the current
      skills on disk.
    """
    department = user_data.department_name or "General"
    department = _resolve_agent_department(agent_id, department)
    agent_dir = _get_agent_dir(agent_id, department)
    config_file = agent_dir / "agent_config.json"

    log.info(f"[PVC:agent_workspaces] START update_skill_agent — agent_id={agent_id}, department='{department}', path='{agent_dir}', mountPath=/app/agent_workspaces")

    # If agent_config.json doesn't exist yet (DB-onboarded agents created
    # before the seed logic was added), create a minimal one so the update
    # can proceed.
    if not config_file.exists():
        agent_dir.mkdir(parents=True, exist_ok=True)
        _initial = {
            "agent_id": agent_id,
            "department_name": department,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        config_file.write_text(json.dumps(_initial, indent=2), encoding="utf-8")
        log.info(f"Created initial agent_config.json for agent {agent_id}")

    # ------ 0. Authorization ------
    config = json.loads(config_file.read_text(encoding="utf-8"))
    _check_agent_ownership(config, user_data, agent_id)
    if request.allowed_absolute_mount_roots is not None:
        _require_admin_for_absolute_roots(request.allowed_absolute_mount_roots, user_data)

    # ------ 1. Update agent_config.json ------
    if request.agent_name is not None:
        config["agent_name"] = request.agent_name
    if request.agent_description is not None:
        config["agent_description"] = request.agent_description
    if request.model_name is not None:
        config["model_name"] = request.model_name
    if request.default_skill is not None:
        config["default_skill"] = request.default_skill
    # Update additional_paths if provided (replaces entire list; empty list removes all)
    if request.additional_paths is not None:
        if request.additional_paths:
            config["additional_paths"] = [
                {"path": ap.path, "permission": ap.permission, **(dict(absolute=True) if ap.absolute else {})}
                for ap in request.additional_paths
            ]
        else:
            # Empty list explicitly clears additional_paths
            config.pop("additional_paths", None)
    # Update allowed_absolute_mount_roots if provided (auto-derive if absent)
    if request.allowed_absolute_mount_roots is not None:
        if request.allowed_absolute_mount_roots:
            config["allowed_absolute_mount_roots"] = list(request.allowed_absolute_mount_roots)
        else:
            config.pop("allowed_absolute_mount_roots", None)
    else:
        # Auto-derive from additional_paths when no explicit roots given
        ap_list = config.get("additional_paths", [])
        if ap_list:
            derived = _derive_absolute_roots(ap_list)
            if derived:
                config["allowed_absolute_mount_roots"] = derived
    config["updated_at"] = datetime.now(timezone.utc).isoformat()
    config_file.write_text(json.dumps(config, indent=2), encoding="utf-8")

    # Update hooks in config.yaml if provided
    _yaml_dirty = (request.hooks is not None) and yaml
    if _yaml_dirty:
        # Validate hooks config structure before writing
        if request.hooks:
            hook_errors = _validate_hooks_config(request.hooks)
            if hook_errors:
                error_detail = "; ".join(hook_errors)
                raise HTTPException(422, detail=f"Invalid hooks configuration: {error_detail}")
        config_yaml_path = agent_dir / "config.yaml"
        yaml_config: Dict[str, Any] = {}
        if config_yaml_path.exists():
            try:
                yaml_config = yaml.safe_load(config_yaml_path.read_text(encoding="utf-8")) or {}
            except Exception:
                yaml_config = {}
        if request.hooks is not None:
            if request.hooks:
                yaml_config["hooks"] = request.hooks
            else:
                yaml_config.pop("hooks", None)
        if yaml_config:
            config_yaml_path.write_text(
                yaml.dump(yaml_config, default_flow_style=False, allow_unicode=True),
                encoding="utf-8",
            )
        elif config_yaml_path.exists():
            config_yaml_path.unlink()
        log.info(f"Updated config.yaml for agent {agent_id} (hooks={request.hooks is not None})")

    # Also update the DB record if name/description/model changed
    if any(v is not None for v in [request.agent_name, request.agent_description, request.model_name]):
        try:
            svc: AgentService = ServiceProvider.get_service(AgentService)
            update_payload: Dict[str, Any] = {}
            if request.agent_name is not None:
                update_payload["agent_name"] = request.agent_name
            if request.agent_description is not None:
                update_payload["agent_description"] = request.agent_description
            if request.model_name is not None:
                update_payload["model_name"] = request.model_name
            if update_payload:
                svc.update_agent(agent_id, update_payload)
        except Exception as e:
            log.warning(f"Could not update agent DB record for {agent_id}: {e}")

    # ------ 2. Enterprise context ------
    ec_dir = _get_enterprise_dir(agent_id, department)
    ec_dir.mkdir(parents=True, exist_ok=True)
    ec_file = ec_dir / "Enterprise_Context.md"
    skills_dir = _get_skills_dir(agent_id, department)

    ec_replaced = False
    if request.enterprise_context:
        ec = request.enterprise_context

        # Check if enterprise_context_md differs from saved version
        if ec.enterprise_context_md:
            saved = ec_file.read_text(encoding="utf-8") if ec_file.exists() else ""
            if ec.enterprise_context_md.strip() != saved.strip():
                ec_file.write_text(ec.enterprise_context_md, encoding="utf-8")
                ec_replaced = True
                log.info(f"Enterprise context replaced for agent {agent_id}")

        # Skill-specific contexts
        if ec.skill_contexts:
            ctx_dir = ec_dir / "contexts"
            ctx_dir.mkdir(exist_ok=True)
            for name, content in ec.skill_contexts.items():
                (ctx_dir / f"{name}_context.md").write_text(content, encoding="utf-8")

        # Policies
        if ec.policies:
            pol_dir = ec_dir / "policies"
            pol_dir.mkdir(exist_ok=True)
            for name, content in ec.policies.items():
                (pol_dir / f"{name}.md").write_text(content, encoding="utf-8")

        # Entity guide
        if ec.entity_guide:
            (ec_dir / "entity_guide.md").write_text(ec.entity_guide, encoding="utf-8")

    # Always regenerate the Available Skills table (unless user just replaced the whole file)
    if not ec_replaced and skills_dir.exists():
        _sync_enterprise_context_skills(agent_id, skills_dir, department)

    # Also update _index.yaml from current skill files
    if skills_dir.exists():
        _update_skill_index(agent_id, skills_dir)

    log.info(f"Updated agent {agent_id} (ec_replaced={ec_replaced})")
    _schedule_blob_sync_for_agent(agent_id, department)

    log.info(f"[PVC:agent_workspaces] END update_skill_agent — agent_id={agent_id}, department='{department}', ec_replaced={ec_replaced}, path='{agent_dir}', mountPath=/app/agent_workspaces")

    return {
        "status": "success",
        "agent_id": agent_id,
        "config_updated": True,
        "enterprise_context_replaced": ec_replaced,
    }


@router.delete("/agents/{agent_id}", summary="Soft-delete a skill-based agent (moves to recycle bin)")
@router.post("/agents/{agent_id}/delete", summary="Soft-delete a skill-based agent (moves to recycle bin)")
async def delete_skill_agent(agent_id: str, user_data: User = Depends(get_current_user)):
    """
    Soft-delete a skill-based agent:
    1. Moves the DB record to `recycle_agent` table (via IAF AgentService).
    2. Archives the disk folder to `.recycle_bin/` so it can be restored.
    3. Cleans up tag and tool-agent mappings.

    Use POST /agentos/agents/recycle-bin/restore/{agent_id} to undo.
    """
    department = user_data.department_name or "General"
    department = _resolve_agent_department(agent_id, department)
    agent_dir = _get_agent_dir(agent_id, department)
    if not agent_dir.exists():
        raise HTTPException(status_code=404, detail=f"Agent '{agent_id}' not found in department '{department}'.")

    # Soft-delete via IAF (recycle_agent table + mapping cleanup)
    is_admin = (user_data.role or "").lower() in ("admin", "super_admin")
    result = await _soft_delete_agent(agent_id, user_data.email, is_admin=is_admin)

    if not result.get("is_delete"):
        raise HTTPException(status_code=400, detail=result.get("message", "Delete failed."))

    # Archive the disk folder (move to .recycle_bin/)
    _archive_agent_dir(agent_dir)

    log.info(f"Soft-deleted skill-based agent: {agent_id} by {user_data.email}")

    return {
        "status": "success",
        "agent_id": agent_id,
        "deleted": True,
        "recycle_bin": True,
        "message": result.get("message", "Agent moved to recycle bin."),
    }


# ============================================================================
# Skill Management
# ============================================================================

@router.get("/agents/{agent_id}/skills", summary="List skills for an agent")
async def list_skills(agent_id: str, user_data: User = Depends(get_current_user)):
    """
    List all skills defined for a skill-based agent.

    Returns skill metadata **plus** every file inside each skill folder
    (SKILL.md, INSTRUCTIONS.md, EXAMPLES.md, and any additional .md files)
    with full text content so the UI can render an inline editor / preview.
    """
    department = user_data.department_name or "General"
    # Access control: same pattern as react agent (only SuperAdmin bypasses dept filter)
    if getattr(user_data, "role", "") != "SuperAdmin":
        agent_service: AgentService = ServiceProvider.get_agent_service()
        if not await agent_service.get_agent(agentic_application_id=agent_id, department_name=department):
            raise HTTPException(status_code=404, detail="Agent not found.")
    department = _resolve_agent_department(agent_id, department)
    skills_dir = _get_skills_dir(agent_id, department)
    # Auto-restore from blob if skills dir is missing locally
    if not skills_dir.exists():
        await _ensure_agent_from_blob(agent_id, department)
    if not skills_dir.exists():
        raise HTTPException(status_code=404, detail=f"Agent '{agent_id}' not found in department '{department}'.")

    loader = SkillLoader(str(skills_dir))
    skills_out = []

    for skill in loader.load_all():
        skill_dict = skill.to_dict()
        skill_folder = Path(skill.folder_path) if skill.folder_path else None

        # ---- Collect every file in the skill folder with content ----
        file_entries = []
        if skill_folder and skill_folder.exists():
            for f in sorted(skill_folder.iterdir()):
                if not f.is_file():
                    continue
                entry = {
                    "name": f.name,
                    "size_bytes": f.stat().st_size,
                    "modified": datetime.fromtimestamp(
                        f.stat().st_mtime, tz=timezone.utc
                    ).isoformat(),
                }
                # Read text content for known editable extensions
                try:
                    entry["content"] = f.read_text(encoding="utf-8")
                except (UnicodeDecodeError, OSError):
                    entry["content"] = None  # binary / unreadable file
                file_entries.append(entry)

        skill_dict["files_detail"] = file_entries
        skill_dict["file_count"] = len(file_entries)

        # Convenience: surface top-level file names list for quick UI checks
        skill_dict["file_names"] = [e["name"] for e in file_entries]

        skills_out.append(skill_dict)

    return {"agent_id": agent_id, "skills": skills_out, "total": len(skills_out)}


@router.get("/agents/{agent_id}/skills/{skill_name}", summary="Get skill details")
async def get_skill(agent_id: str, skill_name: str, user_data: User = Depends(get_current_user)):
    """
    Get full details of a specific skill including all file contents.

    Returns the parsed skill metadata, the assembled full_prompt, and every
    file in the skill folder with its content so the UI can display an
    inline editor for SKILL.md, INSTRUCTIONS.md, EXAMPLES.md, and any
    additional files.
    """
    department = user_data.department_name or "General"
    # Access control: same pattern as react agent (only SuperAdmin bypasses dept filter)
    if getattr(user_data, "role", "") != "SuperAdmin":
        agent_service: AgentService = ServiceProvider.get_agent_service()
        if not await agent_service.get_agent(agentic_application_id=agent_id, department_name=department):
            raise HTTPException(status_code=404, detail="Agent not found.")
    department = _resolve_agent_department(agent_id, department)
    # Auto-restore from blob if agent data is missing locally
    skills_dir = _get_skills_dir(agent_id, department)
    if not skills_dir.exists():
        await _ensure_agent_from_blob(agent_id, department)
    loader = SkillLoader(str(skills_dir))
    skill = loader.load(skill_name)
    if not skill:
        raise HTTPException(status_code=404, detail=f"Skill '{skill_name}' not found.")

    result = skill.to_dict()
    result["full_prompt"] = loader.get_full_prompt(skill)

    # ---- Attach every file in the skill folder with content ----
    skill_folder = Path(skill.folder_path) if skill.folder_path else None
    file_entries = []
    if skill_folder and skill_folder.exists():
        for f in sorted(skill_folder.iterdir()):
            if not f.is_file():
                continue
            entry = {
                "name": f.name,
                "size_bytes": f.stat().st_size,
                "modified": datetime.fromtimestamp(
                    f.stat().st_mtime, tz=timezone.utc
                ).isoformat(),
            }
            try:
                entry["content"] = f.read_text(encoding="utf-8")
            except (UnicodeDecodeError, OSError):
                entry["content"] = None
            file_entries.append(entry)

    result["files_detail"] = file_entries
    result["file_count"] = len(file_entries)
    result["file_names"] = [e["name"] for e in file_entries]

    return result


@router.post("/agents/{agent_id}/skills", summary="Add a skill to an agent")
async def add_skill(agent_id: str, request: AddSkillRequest, user_data: User = Depends(get_current_user)):
    """Add a new skill to an existing agent."""
    department = user_data.department_name or "General"
    department = _resolve_agent_department(agent_id, department)
    skills_dir = _get_skills_dir(agent_id, department)
    if not skills_dir.exists():
        raise HTTPException(status_code=404, detail=f"Agent '{agent_id}' not found in department '{department}'.")

    skill_folder = skills_dir / request.skill.skill_name
    if skill_folder.exists():
        raise HTTPException(status_code=409, detail=f"Skill '{request.skill.skill_name}' already exists.")

    # Resolve SKILL.md content: raw string OR build from structured fields
    skill_md = _resolve_skill_md_content(
        skill_name=request.skill.skill_name,
        skill_md_content=request.skill.skill_md_content,
        description=request.skill.description,
        keywords=request.skill.keywords,
        details=request.skill.details,
        execution_mode=request.skill.execution_mode,
        category=request.skill.category,
        databases=[db.model_dump() for db in request.skill.databases] if request.skill.databases else None,
        hooks=request.skill.hooks,
        steps=[s.model_dump(by_alias=True, exclude_none=True) for s in request.skill.steps] if request.skill.steps else None,
        worker_skills=[w.model_dump() for w in request.skill.worker_skills] if request.skill.worker_skills else None,
        max_steps=request.skill.max_steps,
        max_iterations=request.skill.max_iterations,
        quality_threshold=request.skill.quality_threshold,
        evaluation_criteria=request.skill.evaluation_criteria,
    )
    if not skill_md:
        raise HTTPException(
            status_code=400,
            detail="Provide either 'skill_md_content' or at least one of 'description', 'keywords', 'details'.",
        )

    skill_folder.mkdir(parents=True)
    (skill_folder / "SKILL.md").write_text(skill_md, encoding="utf-8")

    if request.skill.instructions_md_content:
        (skill_folder / "INSTRUCTIONS.md").write_text(
            request.skill.instructions_md_content, encoding="utf-8"
        )
    if request.skill.examples_md_content:
        (skill_folder / "EXAMPLES.md").write_text(
            request.skill.examples_md_content, encoding="utf-8"
        )

    # Write additional files (api.md, credentials.md, etc.)
    if request.skill.additional_files:
        for fname, fcontent in request.skill.additional_files.items():
            safe_name = Path(fname).name  # prevent path traversal
            if safe_name and safe_name not in ("SKILL.md", "INSTRUCTIONS.md", "EXAMPLES.md"):
                (skill_folder / safe_name).write_text(fcontent, encoding="utf-8")

    # Update _index.yaml + Enterprise_Context.md
    _update_skill_index(agent_id, skills_dir)
    _sync_enterprise_context_skills(agent_id, skills_dir, department)

    log.info(f"Added skill '{request.skill.skill_name}' to agent {agent_id}")
    _schedule_blob_sync_for_agent(agent_id, department)
    return {"status": "success", "skill_name": request.skill.skill_name}


@router.post("/agents/{agent_id}/skills/upload", summary="Add a skill by uploading files")
async def add_skill_from_files(
    agent_id: str,
    skill_name: str = Form(..., description="Unique skill name (snake_case)."),
    files: List[UploadFile] = File(..., description="Upload SKILL.md (required) and any companion files (INSTRUCTIONS.md, EXAMPLES.md, api.md, etc.)."),
    user_data: User = Depends(get_current_user),
):
    """
    Create a new skill by uploading files directly (multipart form).
    
    **Required:** At least one file named `SKILL.md`.
    **Optional:** INSTRUCTIONS.md, EXAMPLES.md, plus any additional files
    (api.md, credentials.md, config.yaml, etc.)
    
    This is the drag-and-drop / file-upload alternative to the JSON-based
    POST /agents/{id}/skills endpoint.
    """
    department = user_data.department_name or "General"
    department = _resolve_agent_department(agent_id, department)
    skills_dir = _get_skills_dir(agent_id, department)
    if not skills_dir.exists():
        raise HTTPException(status_code=404, detail=f"Agent '{agent_id}' not found in department '{department}'.")

    # Validate skill_name
    safe_skill_name = Path(skill_name).name
    if not safe_skill_name or safe_skill_name != skill_name:
        raise HTTPException(status_code=400, detail="Invalid skill name. Use simple snake_case (e.g. 'employee_details').")

    skill_folder = skills_dir / safe_skill_name
    if skill_folder.exists():
        raise HTTPException(status_code=409, detail=f"Skill '{safe_skill_name}' already exists.")

    # Check that SKILL.md is present in uploads
    file_names = [f.filename for f in files if f.filename]
    if "SKILL.md" not in [Path(n).name for n in file_names]:
        raise HTTPException(
            status_code=400,
            detail="SKILL.md is required. Upload at least a SKILL.md file."
        )

    # Create skill folder and write all files
    skill_folder.mkdir(parents=True)
    saved = []
    errors = []

    for upload in files:
        safe_name = Path(upload.filename).name if upload.filename else None
        if not safe_name:
            errors.append({"file": upload.filename, "error": "Invalid filename"})
            continue

        content = await upload.read()
        if len(content) > 2 * 1024 * 1024:  # 2 MB
            errors.append({"file": safe_name, "error": f"File too large ({len(content)} bytes). Max: 2 MB."})
            continue

        (skill_folder / safe_name).write_bytes(content)
        saved.append({"name": safe_name, "size_bytes": len(content)})

    # If SKILL.md wasn't actually saved (e.g. too large), rollback
    if not (skill_folder / "SKILL.md").exists():
        shutil.rmtree(skill_folder, ignore_errors=True)
        raise HTTPException(status_code=400, detail="SKILL.md could not be saved. Skill creation aborted.")

    # Update _index.yaml + Enterprise_Context.md
    _update_skill_index(agent_id, skills_dir)
    _sync_enterprise_context_skills(agent_id, skills_dir, department)

    log.info(f"Added skill '{safe_skill_name}' (via file upload, {len(saved)} files) to agent {agent_id} by {user_data.email}")
    _schedule_blob_sync_for_agent(agent_id, department)
    return {
        "status": "success",
        "skill_name": safe_skill_name,
        "files_saved": saved,
        "errors": errors,
    }


@router.put("/agents/{agent_id}/skills/{skill_name}", summary="Update a skill")
@router.post("/agents/{agent_id}/skills/{skill_name}/update", summary="Update a skill")
async def update_skill(agent_id: str, skill_name: str, request: UpdateSkillRequest, user_data: User = Depends(get_current_user)):
    """Update an existing skill's files."""
    department = user_data.department_name or "General"
    department = _resolve_agent_department(agent_id, department)
    skills_dir = _get_skills_dir(agent_id, department)
    skill_folder = skills_dir / skill_name

    if not skill_folder.exists():
        raise HTTPException(status_code=404, detail=f"Skill '{skill_name}' not found.")

    log.info(f"[PVC:agent_workspaces] START update_skill — agent_id={agent_id}, skill='{skill_name}', department='{department}', path='{skill_folder}', mountPath=/app/agent_workspaces")

    # Resolve SKILL.md: raw content takes priority, else merge structured fields
    if request.skill_md_content:
        (skill_folder / "SKILL.md").write_text(request.skill_md_content, encoding="utf-8")
    elif any(v is not None for v in [request.description, request.keywords, request.details,
                                     request.execution_mode, request.category, request.databases,
                                     request.hooks, request.steps, request.worker_skills,
                                     request.max_steps, request.max_iterations,
                                     request.quality_threshold, request.evaluation_criteria]):
        # Merge structured fields into existing SKILL.md
        existing = (skill_folder / "SKILL.md").read_text(encoding="utf-8")
        merged = _merge_skill_md_content(
            existing_content=existing,
            skill_name=skill_name,
            description=request.description,
            keywords=request.keywords,
            details=request.details,
            execution_mode=request.execution_mode,
            category=request.category,
            databases=[db.model_dump() for db in request.databases] if request.databases else None,
            hooks=request.hooks,
            steps=[s.model_dump(by_alias=True, exclude_none=True) for s in request.steps] if request.steps else None,
            worker_skills=[w.model_dump() for w in request.worker_skills] if request.worker_skills else None,
            max_steps=request.max_steps,
            max_iterations=request.max_iterations,
            quality_threshold=request.quality_threshold,
            evaluation_criteria=request.evaluation_criteria,
        )
        (skill_folder / "SKILL.md").write_text(merged, encoding="utf-8")
    if request.instructions_md_content:
        (skill_folder / "INSTRUCTIONS.md").write_text(
            request.instructions_md_content, encoding="utf-8"
        )
    if request.examples_md_content:
        (skill_folder / "EXAMPLES.md").write_text(
            request.examples_md_content, encoding="utf-8"
        )

    # Write additional files (api.md, credentials.md, etc.)
    if request.additional_files:
        for fname, fcontent in request.additional_files.items():
            safe_name = Path(fname).name
            if safe_name and safe_name not in ("SKILL.md", "INSTRUCTIONS.md", "EXAMPLES.md"):
                (skill_folder / safe_name).write_text(fcontent, encoding="utf-8")

    # Remove files if requested
    if request.remove_files:
        for fname in request.remove_files:
            safe_name = Path(fname).name
            target = skill_folder / safe_name
            if target.exists() and safe_name not in ("SKILL.md",):  # never delete SKILL.md
                target.unlink()
                # Delete from blob so it doesn't get restored later
                _schedule_blob_delete(
                    f"{department}/agentos_agents/{agent_id}/skills/{skill_name}/{safe_name}",
                    department=department,
                )

    # Update _index.yaml + Enterprise_Context.md
    _update_skill_index(agent_id, skills_dir)
    _sync_enterprise_context_skills(agent_id, skills_dir, department)

    log.info(f"Updated skill '{skill_name}' for agent {agent_id}")
    _schedule_blob_sync_for_agent(agent_id, department)

    log.info(f"[PVC:agent_workspaces] END update_skill — agent_id={agent_id}, skill='{skill_name}', department='{department}', path='{skill_folder}', mountPath=/app/agent_workspaces")

    return {"status": "success", "skill_name": skill_name}


@router.delete("/agents/{agent_id}/skills/{skill_name}", summary="Remove a skill")
@router.post("/agents/{agent_id}/skills/{skill_name}/delete", summary="Remove a skill")
async def remove_skill(agent_id: str, skill_name: str, user_data: User = Depends(get_current_user)):
    """Remove a skill from an agent."""
    department = user_data.department_name or "General"
    department = _resolve_agent_department(agent_id, department)
    skills_dir = _get_skills_dir(agent_id, department)
    skill_folder = skills_dir / skill_name

    if not skill_folder.exists():
        raise HTTPException(status_code=404, detail=f"Skill '{skill_name}' not found.")

    shutil.rmtree(skill_folder, ignore_errors=True)

    # Update _index.yaml + Enterprise_Context.md
    _update_skill_index(agent_id, skills_dir)
    _sync_enterprise_context_skills(agent_id, skills_dir, department)

    log.info(f"Removed skill '{skill_name}' from agent {agent_id} by {user_data.email}")
    _schedule_blob_sync_for_agent(agent_id, department)
    # Delete the skill's blob files so they don't get restored later
    _schedule_blob_delete(
        f"{department}/agentos_agents/{agent_id}/skills/{skill_name}/",
        department=department,
    )
    return {"status": "success", "skill_name": skill_name, "deleted": True}


# ============================================================================
# Skill File Management
# ============================================================================

# Allowed extensions for file uploads (whitelist)
_ALLOWED_EXTENSIONS = {
    ".md", ".txt", ".yaml", ".yml", ".json", ".csv", ".xml",
    ".py", ".js", ".html", ".css", ".sql", ".sh", ".bat",
    ".cfg", ".ini", ".toml", ".env", ".log",
}
# Max file size: 2 MB
_MAX_FILE_SIZE = 2 * 1024 * 1024


@router.get("/agents/{agent_id}/skills/{skill_name}/files", summary="List skill files")
async def list_skill_files(agent_id: str, skill_name: str, user_data: User = Depends(get_current_user)):
    """List all files inside a skill folder with their content."""
    department = user_data.department_name or "General"
    # Access control: same pattern as react agent (only SuperAdmin bypasses dept filter)
    if getattr(user_data, "role", "") != "SuperAdmin":
        agent_service: AgentService = ServiceProvider.get_agent_service()
        if not await agent_service.get_agent(agentic_application_id=agent_id, department_name=department):
            raise HTTPException(status_code=404, detail="Agent not found.")
    department = _resolve_agent_department(agent_id, department)
    skill_folder = _get_skills_dir(agent_id, department) / skill_name
    # Auto-restore from blob if skill folder is missing locally
    if not skill_folder.exists():
        await _ensure_agent_from_blob(agent_id, department)
    if not skill_folder.exists():
        raise HTTPException(status_code=404, detail=f"Skill '{skill_name}' not found.")

    files = []
    for f in sorted(skill_folder.iterdir()):
        if f.is_file():
            entry = {
                "name": f.name,
                "size_bytes": f.stat().st_size,
                "modified": datetime.fromtimestamp(f.stat().st_mtime, tz=timezone.utc).isoformat(),
            }
            try:
                entry["content"] = f.read_text(encoding="utf-8")
            except (UnicodeDecodeError, OSError):
                entry["content"] = None
            files.append(entry)
    return {"agent_id": agent_id, "skill_name": skill_name, "files": files}


@router.post("/agents/{agent_id}/skills/{skill_name}/files", summary="Upload files to a skill")
async def upload_skill_files(
    agent_id: str,
    skill_name: str,
    files: List[UploadFile] = File(..., description="One or more files to upload into the skill folder."),
    user_data: User = Depends(get_current_user),
):
    """
    Upload one or more files into a skill's folder via multipart form.
    
    This supports any text file (markdown, yaml, json, csv, etc.).
    Files like api.md, credentials.md, config.yaml are written alongside SKILL.md.
    
    - Max file size: 2 MB per file
    - SKILL.md cannot be overwritten via this endpoint (use PUT /skills/{name})
    - Path traversal is blocked
    """
    department = user_data.department_name or "General"
    department = _resolve_agent_department(agent_id, department)
    skill_folder = _get_skills_dir(agent_id, department) / skill_name
    if not skill_folder.exists():
        raise HTTPException(status_code=404, detail=f"Skill '{skill_name}' not found.")

    saved = []
    errors = []

    for upload in files:
        safe_name = Path(upload.filename).name if upload.filename else None
        if not safe_name:
            errors.append({"file": upload.filename, "error": "Invalid filename"})
            continue

        # Extension whitelist
        ext = Path(safe_name).suffix.lower()
        if ext not in _ALLOWED_EXTENSIONS:
            errors.append({"file": safe_name, "error": f"Extension '{ext}' not allowed. Allowed: {sorted(_ALLOWED_EXTENSIONS)}"})
            continue

        # Protect core files
        if safe_name == "SKILL.md":
            errors.append({"file": safe_name, "error": "Cannot overwrite SKILL.md via file upload. Use PUT /skills/{name} instead."})
            continue

        # Read content with size check
        content = await upload.read()
        if len(content) > _MAX_FILE_SIZE:
            errors.append({"file": safe_name, "error": f"File too large ({len(content)} bytes). Max: {_MAX_FILE_SIZE} bytes."})
            continue

        # Write file
        target = skill_folder / safe_name
        target.write_bytes(content)
        saved.append({"name": safe_name, "size_bytes": len(content)})
        log.info(f"Uploaded '{safe_name}' to skill '{skill_name}' of agent {agent_id} by {user_data.email}")

    return {
        "status": "success" if saved else "partial" if errors else "success",
        "saved": saved,
        "errors": errors,
    }


@router.api_route("/agents/{agent_id}/skills/{skill_name}/files/{filename}", methods=["DELETE", "POST"], summary="Delete a skill file")
async def delete_skill_file(
    agent_id: str,
    skill_name: str,
    filename: str,
    user_data: User = Depends(get_current_user),
):
    """Delete a specific file from a skill folder. SKILL.md cannot be deleted."""
    department = user_data.department_name or "General"
    department = _resolve_agent_department(agent_id, department)
    skill_folder = _get_skills_dir(agent_id, department) / skill_name
    if not skill_folder.exists():
        raise HTTPException(status_code=404, detail=f"Skill '{skill_name}' not found.")

    safe_name = Path(filename).name
    if safe_name == "SKILL.md":
        raise HTTPException(status_code=400, detail="Cannot delete SKILL.md. Delete the entire skill instead.")

    target = skill_folder / safe_name
    if not target.exists():
        raise HTTPException(status_code=404, detail=f"File '{safe_name}' not found in skill '{skill_name}'.")

    target.unlink()
    log.info(f"Deleted '{safe_name}' from skill '{skill_name}' of agent {agent_id} by {user_data.email}")
    # Delete the file from blob so it doesn't get restored later
    _schedule_blob_delete(
        f"{department}/agentos_agents/{agent_id}/skills/{skill_name}/{safe_name}",
        department=department,
    )
    return {"status": "success", "deleted": safe_name}


# ============================================================================
# Enterprise Context
# ============================================================================

@router.get("/agents/{agent_id}/context", summary="Get enterprise context")
async def get_enterprise_context(agent_id: str, user_data: User = Depends(get_current_user)):
    """Get enterprise context details for an agent with full content."""
    department = user_data.department_name or "General"
    # Access control: same pattern as react agent (only SuperAdmin bypasses dept filter)
    if getattr(user_data, "role", "") != "SuperAdmin":
        agent_service: AgentService = ServiceProvider.get_agent_service()
        if not await agent_service.get_agent(agentic_application_id=agent_id, department_name=department):
            raise HTTPException(status_code=404, detail="Agent not found.")
    department = _resolve_agent_department(agent_id, department)
    ec_dir = _get_enterprise_dir(agent_id, department)
    # Auto-restore from blob if enterprise context is missing locally
    if not ec_dir.exists():
        await _ensure_agent_from_blob(agent_id, department)
    # Regenerate enterprise_context if still missing (partial creation)
    _ensure_agent_completeness(agent_id, department)
    ec_dir = _get_enterprise_dir(agent_id, department)
    if not ec_dir.exists():
        return {"agent_id": agent_id, "enterprise_context_enabled": False}

    manager = EnterpriseContextManager(str(ec_dir))
    return {
        "agent_id": agent_id,
        "enterprise_context_enabled": True,
        "available": manager.list_available_contexts(),
    }


@router.api_route("/agents/{agent_id}/context", methods=["PUT", "POST"], summary="Update enterprise context")
async def update_enterprise_context(agent_id: str, request: UpdateEnterpriseContextRequest, user_data: User = Depends(get_current_user)):
    """Update enterprise context files for an agent."""
    department = user_data.department_name or "General"
    department = _resolve_agent_department(agent_id, department)
    ec_dir = _get_enterprise_dir(agent_id, department)
    ec_dir.mkdir(parents=True, exist_ok=True)

    manager = EnterpriseContextManager(str(ec_dir))

    if request.enterprise_context_md:
        manager.save_master_context(request.enterprise_context_md)

    if request.skill_contexts:
        for name, content in request.skill_contexts.items():
            manager.save_skill_context(name, content)

    if request.policies:
        for name, content in request.policies.items():
            manager.save_policy(name, content)

    if request.entity_guide:
        (ec_dir / "entity_guide.md").write_text(request.entity_guide, encoding="utf-8")

    # Re-sync the Available Skills table into Enterprise_Context.md
    skills_dir = _get_skills_dir(agent_id, department)
    if skills_dir.exists():
        _sync_enterprise_context_skills(agent_id, skills_dir, department)

    log.info(f"Updated enterprise context for agent {agent_id}")
    _schedule_blob_sync_for_agent(agent_id, department)
    return {"status": "success", "agent_id": agent_id}


# ============================================================================
# Audit
# ============================================================================

@router.get("/audit/shell", summary="Shell audit logs")
async def get_shell_audit(
    date: Optional[str] = None,
    limit: int = Query(100, le=1000),
    user_data: User = Depends(get_current_user),
):
    """Get shell command audit logs."""
    logger = ShellAuditLogger(AGENTOS_AUDIT_DIR)
    logs = logger.get_logs(date=date, user_email=user_data.email, limit=limit)
    return {"logs": logs, "total": len(logs)}


# ============================================================================
# Helpers
# ============================================================================

def _sync_enterprise_context_skills(agent_id: str, skills_dir: Path, department: str = "General"):
    """
    Auto-update the '## Available Skills' section in Enterprise_Context.md
    so the LLM (and users reading the file) always know what skills exist.

    This is called whenever skills are added, updated, or removed.
    """
    ec_dir = _get_enterprise_dir(agent_id, department)
    ec_file = ec_dir / "Enterprise_Context.md"
    if not ec_file.exists():
        # Create default Enterprise_Context.md so skills table can be written
        ec_dir.mkdir(parents=True, exist_ok=True)
        ec_file.write_text(
            "# Enterprise Context\n\n"
            "_Edit this file to provide company-wide context._\n",
            encoding="utf-8",
        )

    # Load current skills from disk
    loader = SkillLoader(str(skills_dir))
    skills = loader.load_all()
    if not skills:
        return

    # Build the skills registry section
    lines = ["## Available Skills"]
    lines.append("")
    lines.append("| Skill | Description | Keywords |")
    lines.append("|-------|-------------|----------|")
    for s in sorted(skills, key=lambda x: x.name):
        keywords = ", ".join(str(t) for t in s.triggers[:5]) if s.triggers else "-"
        lines.append(f"| {s.name} | {s.description} | {keywords} |")
    lines.append("")
    skills_section = "\n".join(lines)

    # Read existing Enterprise_Context.md
    content = ec_file.read_text(encoding="utf-8")

    # Replace existing skills section, or append at end
    import re as _re
    pattern = _re.compile(
        r"## Available Skills.*?(?=\n## |\Z)",
        _re.DOTALL,
    )
    if pattern.search(content):
        content = pattern.sub(skills_section, content)
    else:
        content = content.rstrip() + "\n\n" + skills_section + "\n"

    ec_file.write_text(content, encoding="utf-8")
    log.info(f"[EnterpriseContext] Synced {len(skills)} skills into Enterprise_Context.md for agent {agent_id}")


def _update_skill_index(agent_id: str, skills_dir: Path):
    """Regenerate _index.yaml from skill folders."""
    if not yaml:
        return

    loader = SkillLoader(str(skills_dir))
    skills = loader.load_all()

    # Read existing index for default_skill
    index_file = skills_dir / "_index.yaml"
    default_skill = "general"
    if index_file.exists():
        try:
            existing = yaml.safe_load(index_file.read_text(encoding="utf-8")) or {}
            default_skill = existing.get("default_skill", "general")
        except Exception:
            pass

    index_data = {
        "version": "1.0",
        "default_skill": default_skill,
        "skills": {
            s.name: {
                "description": s.description,
                "keywords": s.triggers,
                "category": s.category,
                "status": "active",
            }
            for s in skills
        },
    }

    index_file.write_text(
        yaml.dump(index_data, default_flow_style=False, allow_unicode=True),
        encoding="utf-8",
    )
