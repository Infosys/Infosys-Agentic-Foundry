"""
Pre-Inference Asset Restoration Module
=======================================

Ensures ALL required assets are available locally before inference starts.
Runs restoration checks in parallel using asyncio.gather() for minimum latency.

Assets checked/restored:
    1. File context prompts (.md) — when file_context_management_flag=True
    2. Database schema/samples — for each bound db_connection_name
    3. SQLite .db files — for SQLite-type connections
    4. User uploads — when inference has uploaded_files
    5. Skills folder — for skill agents, if skills_dir is missing/empty

Only activates when STORAGE_PROVIDER env var has a value.
"""

import asyncio
import hashlib
import logging
import os
import struct
import time
from pathlib import Path
from typing import List, Optional, Dict, Any

log = logging.getLogger(__name__)

# Configurable timeout for blob restore operations (seconds)
_BLOB_RESTORE_TIMEOUT = int(os.getenv('BLOB_RESTORE_TIMEOUT', '30'))

# Retry configuration — helps survive transient network blips
_BLOB_RESTORE_MAX_RETRIES = int(os.getenv('BLOB_RESTORE_MAX_RETRIES', '3'))
_BLOB_RESTORE_BACKOFF_BASE = float(os.getenv('BLOB_RESTORE_BACKOFF_BASE', '0.5'))  # seconds

# Toggle integrity checks on/off
_BLOB_INTEGRITY_CHECK = os.getenv('BLOB_INTEGRITY_CHECK', 'true').lower() in ('true', '1', 'yes')

# ---------------------------------------------------------------------------
# Fix #M4 — Per-agent asyncio locks to prevent duplicate concurrent restores
# ---------------------------------------------------------------------------
_agent_restore_locks: Dict[str, asyncio.Lock] = {}
_agent_locks_mutex = asyncio.Lock()  # Guards access to the dict itself


async def _get_agent_lock(agent_id: str) -> asyncio.Lock:
    """Return (or create) a per-agent asyncio.Lock.

    Ensures that concurrent inference requests for the *same* agent
    serialise their blob restores, while different agents proceed in
    parallel.
    """
    async with _agent_locks_mutex:
        if agent_id not in _agent_restore_locks:
            _agent_restore_locks[agent_id] = asyncio.Lock()
        return _agent_restore_locks[agent_id]


# ---------------------------------------------------------------------------
# Fix #28 — Blob Restore Integrity Verification
# ---------------------------------------------------------------------------

def _verify_file_integrity(path: Path) -> Optional[str]:
    """Verify structural integrity of a restored file.

    Returns ``None`` if OK, or a short error description if corrupt.
    Checks:
      * Non-zero file size
      * ``.db`` files: SQLite magic bytes (``SQLite format 3\\x00``)
      * ``.py`` / ``.md`` / ``.txt`` / ``.json`` / ``.yaml`` / ``.yml``:
        valid UTF-8 encoding
    """
    try:
        size = path.stat().st_size
        if size == 0:
            return f"empty file (0 bytes)"

        suffix = path.suffix.lower()

        # SQLite database check
        if suffix == ".db":
            with open(path, "rb") as f:
                header = f.read(16)
            if not header.startswith(b"SQLite format 3\x00"):
                return f"invalid SQLite header"

        # Text-based file check
        if suffix in (".py", ".md", ".txt", ".json", ".yaml", ".yml"):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    f.read(4096)  # Read first 4KB to verify encoding
            except UnicodeDecodeError:
                return f"invalid UTF-8 encoding"

        return None  # All checks passed
    except Exception as e:
        return f"integrity check error: {e}"


def verify_restored_directory(directory: Path) -> Dict[str, List[str]]:
    """Verify all files in *directory* after blob restore.

    Returns ``{"ok": [...], "corrupt": [...]}`` where each list contains
    relative file paths.
    """
    result: Dict[str, List[str]] = {"ok": [], "corrupt": []}
    if not directory.exists():
        return result
    for f in directory.rglob("*"):
        if f.is_file():
            issue = _verify_file_integrity(f)
            rel = str(f.relative_to(directory))
            if issue:
                result["corrupt"].append(f"{rel}: {issue}")
                log.warning(f"[BlobIntegrity] Corrupt file after restore: {rel} — {issue}")
            else:
                result["ok"].append(rel)
    return result


async def _retry_blob_operation(
    coro_factory,
    *,
    label: str,
    max_retries: int = _BLOB_RESTORE_MAX_RETRIES,
    backoff_base: float = _BLOB_RESTORE_BACKOFF_BASE,
    timeout: float = _BLOB_RESTORE_TIMEOUT,
):
    """Execute an async blob operation with exponential-backoff retries.

    ``coro_factory`` is a zero-arg callable that returns a fresh awaitable
    on each invocation (because an already-awaited coroutine cannot be reused).

    Retries on ``asyncio.TimeoutError``, ``ConnectionError``, ``OSError``, and
    generic ``Exception`` (capped at *max_retries*).  The final attempt's
    exception propagates to the caller.
    """
    last_exc: Optional[Exception] = None
    for attempt in range(1, max_retries + 1):
        try:
            return await asyncio.wait_for(coro_factory(), timeout=timeout)
        except (asyncio.TimeoutError, ConnectionError, OSError) as exc:
            last_exc = exc
            if attempt < max_retries:
                delay = backoff_base * (2 ** (attempt - 1))
                log.warning(
                    f"[PreInferenceRestore] {label}: attempt {attempt}/{max_retries} "
                    f"failed ({type(exc).__name__}), retrying in {delay:.1f}s"
                )
                await asyncio.sleep(delay)
            else:
                log.warning(
                    f"[PreInferenceRestore] {label}: all {max_retries} attempts exhausted"
                )
    if last_exc is None:
        raise RuntimeError(
            f"[PreInferenceRestore] {label}: max_retries={max_retries} is 0 — no attempts made"
        )
    raise last_exc


async def ensure_inference_assets_available(
    *,
    department: str = "General",
    agent_id: str = "",
    agent_name: str = "",
    db_connection_names: Optional[List[str]] = None,
    file_context_management_flag: bool = False,
    uploaded_files: Optional[List[str]] = None,
    is_skill_agent: bool = False,
    skills_dir: Optional[Path] = None,
) -> Dict[str, Any]:
    """
    Run all asset-availability checks in parallel BEFORE inference starts.

    This prevents "No such file" errors during inference when the local
    filesystem is missing files that exist in blob storage.

    Args:
        department: The department name for file path resolution.
        agent_id: The agent's unique ID.
        agent_name: Human-readable agent name (for file_context_prompt filename).
        db_connection_names: List of db connection names bound to the agent.
        file_context_management_flag: Whether file-based context is enabled.
        uploaded_files: List of uploaded file relative paths (from inference request).
        is_skill_agent: Whether this is a skill agent (needs skills folder).
        skills_dir: Path to the skills directory (for skill agents).

    Returns:
        A dict summarizing what was restored:
        {
            "restored": [...],   # list of asset descriptions that were restored
            "skipped": [...],    # list of assets that already existed locally
            "failed": [...],     # list of assets that failed to restore
            "elapsed_ms": float, # total time spent
        }
    """
    storage_provider = os.getenv('STORAGE_PROVIDER', '')
    if not storage_provider:
        log.debug("[PreInferenceRestore] No STORAGE_PROVIDER set, skipping all asset checks")
        return {"restored": [], "skipped": [], "failed": [], "elapsed_ms": 0.0}

    # Per-agent lock: serialise concurrent restores for the SAME agent
    # while allowing different agents to proceed in parallel.
    _lock = await _get_agent_lock(agent_id or department)
    async with _lock:
        return await _ensure_inference_assets_locked(
            storage_provider=storage_provider,
            department=department,
            agent_id=agent_id,
            agent_name=agent_name,
            db_connection_names=db_connection_names,
            file_context_management_flag=file_context_management_flag,
            uploaded_files=uploaded_files,
            is_skill_agent=is_skill_agent,
            skills_dir=skills_dir,
        )


async def _ensure_inference_assets_locked(
    *,
    storage_provider: str,
    department: str,
    agent_id: str,
    agent_name: str,
    db_connection_names: Optional[List[str]],
    file_context_management_flag: bool,
    uploaded_files: Optional[List[str]],
    is_skill_agent: bool,
    skills_dir: Optional[Path],
) -> Dict[str, Any]:
    """Inner implementation — runs under the per-agent asyncio.Lock."""

    start = time.perf_counter()
    results = {"restored": [], "skipped": [], "failed": []}

    # Build the list of parallel tasks
    tasks: List[asyncio.Task] = []
    task_labels: List[str] = []

    # --- 1. File context prompt ---
    if file_context_management_flag and agent_name:
        tasks.append(
            _restore_file_context_prompt(
                storage_provider=storage_provider,
                department=department,
                agent_name=agent_name,
            )
        )
        task_labels.append("file_context_prompt")

    # --- 2 & 3. Database schema/samples + SQLite DB files ---
    if db_connection_names:
        tasks.append(
            _restore_database_assets(
                storage_provider=storage_provider,
                department=department,
                db_connection_names=db_connection_names,
            )
        )
        task_labels.append("database_assets")

    # --- 4. User uploads ---
    if uploaded_files:
        tasks.append(
            _restore_user_uploads(
                storage_provider=storage_provider,
                uploaded_files=uploaded_files,
            )
        )
        task_labels.append("user_uploads")

    # --- 5. Skills folder (skill agents only) ---
    if is_skill_agent and skills_dir:
        tasks.append(
            _restore_skills_folder(
                storage_provider=storage_provider,
                department=department,
                agent_id=agent_id,
                skills_dir=skills_dir,
            )
        )
        task_labels.append("skills_folder")

    # --- 6. Enterprise context folder (skill agents only) ---
    if is_skill_agent and skills_dir:
        enterprise_dir = skills_dir.parent / "enterprise_context"
        tasks.append(
            _restore_enterprise_context(
                storage_provider=storage_provider,
                department=department,
                agent_id=agent_id,
                enterprise_dir=enterprise_dir,
            )
        )
        task_labels.append("enterprise_context")

    if not tasks:
        log.debug("[PreInferenceRestore] No asset checks needed for this inference")
        return {"restored": [], "skipped": [], "failed": [], "elapsed_ms": 0.0}

    log.info(
        f"[PreInferenceRestore] Running {len(tasks)} parallel asset checks: {task_labels}"
    )

    # Run all checks in parallel with individual timeouts
    task_results = await asyncio.gather(*tasks, return_exceptions=True)

    # Collect results
    for label, result in zip(task_labels, task_results):
        if isinstance(result, Exception):
            log.warning(f"[PreInferenceRestore] Task '{label}' raised exception: {result}")
            results["failed"].append(f"{label}: {result}")
        elif isinstance(result, dict):
            results["restored"].extend(result.get("restored", []))
            results["skipped"].extend(result.get("skipped", []))
            results["failed"].extend(result.get("failed", []))
        else:
            results["skipped"].append(label)

    elapsed_ms = (time.perf_counter() - start) * 1000
    results["elapsed_ms"] = elapsed_ms

    if results["restored"]:
        log.info(
            f"[PreInferenceRestore] Completed in {elapsed_ms:.0f}ms — "
            f"restored: {results['restored']}"
        )
    else:
        log.debug(
            f"[PreInferenceRestore] Completed in {elapsed_ms:.0f}ms — "
            f"all assets already present locally"
        )

    return results


# ================================================================== #
#  Individual restore tasks
# ================================================================== #


async def _restore_file_context_prompt(
    *,
    storage_provider: str,
    department: str,
    agent_name: str,
) -> Dict[str, List[str]]:
    """Restore the file_context_prompt .md file if missing locally."""
    result = {"restored": [], "skipped": [], "failed": []}

    safe_agent_name = "".join(
        c if c.isalnum() or c in ('_', '-', ' ') else '_' for c in agent_name
    ).strip()

    workspace_root = Path(os.path.abspath("./agent_workspaces"))
    prompt_dir = workspace_root / department / "file_context_prompts"
    prompt_file = prompt_dir / f"{safe_agent_name}_file_context_prompt.md"

    if prompt_file.exists():
        result["skipped"].append(f"file_context_prompt:{safe_agent_name}")
        return result

    try:
        from src.storage import get_storage_client
        from src.utils.workspace_blob_sync import WorkspaceBlobSync

        client = get_storage_client(storage_provider)
        syncer = WorkspaceBlobSync(
            storage_client=client,
            workspace_root="./agent_workspaces",
            department=department,
        )

        blob_key = f"{department}/file_context_prompts/{safe_agent_name}_file_context_prompt.md"
        restore_result = await _retry_blob_operation(
            lambda: syncer.restore_file(blob_key, prompt_file),
            label=f"file_context_prompt:{safe_agent_name}",
        )

        if restore_result and restore_result.success:
            result["restored"].append(f"file_context_prompt:{safe_agent_name}")
            log.info(f"[PreInferenceRestore] Restored file_context_prompt: {blob_key}")
        else:
            # Not in blob either — not an error, agent may not have one
            result["skipped"].append(f"file_context_prompt:{safe_agent_name} (not in blob)")

    except asyncio.TimeoutError:
        result["failed"].append(f"file_context_prompt:{safe_agent_name} (timeout after retries)")
        log.warning(f"[PreInferenceRestore] Timed out restoring file_context_prompt for '{safe_agent_name}' after retries")
    except Exception as e:
        result["failed"].append(f"file_context_prompt:{safe_agent_name} ({e})")
        log.debug(f"[PreInferenceRestore] file_context_prompt restore failed: {e}")

    return result


async def _restore_database_assets(
    *,
    storage_provider: str,
    department: str,
    db_connection_names: List[str],
) -> Dict[str, List[str]]:
    """Restore database schema/samples and SQLite .db files for all connections."""
    result = {"restored": [], "skipped": [], "failed": []}

    workspace_root = Path(os.path.abspath("./agent_workspaces"))

    try:
        from src.storage import get_storage_client
        from src.utils.workspace_blob_sync import WorkspaceBlobSync

        client = get_storage_client(storage_provider)
        syncer = WorkspaceBlobSync(
            storage_client=client,
            workspace_root="./agent_workspaces",
            department=department,
        )
    except Exception as e:
        result["failed"].append(f"database_assets:init_failed ({e})")
        return result

    # Run schema/samples restore + SQLite restore in parallel per connection
    per_conn_tasks = []
    per_conn_labels = []

    for conn_name in db_connection_names:
        per_conn_tasks.append(
            _restore_single_db_connection(
                syncer=syncer,
                client=client,
                storage_provider=storage_provider,
                workspace_root=workspace_root,
                department=department,
                conn_name=conn_name,
            )
        )
        per_conn_labels.append(conn_name)

    if per_conn_tasks:
        conn_results = await asyncio.gather(*per_conn_tasks, return_exceptions=True)
        for label, conn_result in zip(per_conn_labels, conn_results):
            if isinstance(conn_result, Exception):
                result["failed"].append(f"db:{label} ({conn_result})")
            elif isinstance(conn_result, dict):
                result["restored"].extend(conn_result.get("restored", []))
                result["skipped"].extend(conn_result.get("skipped", []))
                result["failed"].extend(conn_result.get("failed", []))

    return result


async def _restore_single_db_connection(
    *,
    syncer,
    client,
    storage_provider: str,
    workspace_root: Path,
    department: str,
    conn_name: str,
) -> Dict[str, List[str]]:
    """Restore schema/samples AND SQLite .db for a single connection."""
    result = {"restored": [], "skipped": [], "failed": []}

    # --- Schema/Samples restore ---
    db_dir = workspace_root / department / "databases" / conn_name
    schema_file = db_dir / "schema.md"
    samples_file = db_dir / "samples.md"

    if schema_file.exists() or samples_file.exists():
        result["skipped"].append(f"schema:{conn_name}")
    else:
        try:
            report = await _retry_blob_operation(
                lambda: syncer.restore_database_cache(connection_name=conn_name),
                label=f"schema:{conn_name}",
            )
            if report and report.synced > 0:
                result["restored"].append(f"schema:{conn_name} ({report.synced} files)")
                log.info(f"[PreInferenceRestore] Restored {report.synced} schema/sample files for '{conn_name}'")
            else:
                result["skipped"].append(f"schema:{conn_name} (not in blob)")
        except asyncio.TimeoutError:
            result["failed"].append(f"schema:{conn_name} (timeout after retries)")
            log.warning(f"[PreInferenceRestore] Timed out restoring schema for '{conn_name}' after retries")
        except Exception as e:
            result["failed"].append(f"schema:{conn_name} ({e})")
            log.debug(f"[PreInferenceRestore] Schema restore failed for '{conn_name}': {e}")

    # --- SQLite .db file restore ---
    try:
        from src.api.data_connector_endpoints import db_connection_manager
        config = await db_connection_manager.get_connection_config(conn_name)
        if config and config.get("db_type", "").lower() == "sqlite":
            db_filename = config.get("database", "")
            _conn_dept = config.get("department_name") or department
            if db_filename:
                db_file_path = Path(os.path.abspath(".")) / "uploaded_sqlite_dbs" / _conn_dept / db_filename
                if db_file_path.exists():
                    result["skipped"].append(f"sqlite:{conn_name}/{db_filename}")
                else:
                    try:
                        from src.utils.workspace_blob_sync import WorkspaceBlobSync
                        syncer_for_db = WorkspaceBlobSync(
                            storage_client=client,
                            project_root=os.path.abspath("."),
                        )
                        restored = await asyncio.wait_for(
                            syncer_for_db.restore_sqlite_db(_conn_dept, db_filename),
                            timeout=_BLOB_RESTORE_TIMEOUT,
                        )
                        if restored:
                            result["restored"].append(f"sqlite:{conn_name}/{db_filename}")
                            log.info(f"[PreInferenceRestore] Restored SQLite DB '{db_filename}' for '{conn_name}'")
                        else:
                            result["skipped"].append(f"sqlite:{conn_name}/{db_filename} (not in blob)")
                    except asyncio.TimeoutError:
                        result["failed"].append(f"sqlite:{conn_name}/{db_filename} (timeout)")
                    except Exception as e:
                        result["failed"].append(f"sqlite:{conn_name}/{db_filename} ({e})")
    except Exception as e:
        # Not critical — connection may not be SQLite
        log.debug(f"[PreInferenceRestore] SQLite check skipped for '{conn_name}': {e}")

    return result


async def _restore_user_uploads(
    *,
    storage_provider: str,
    uploaded_files: List[str],
) -> Dict[str, List[str]]:
    """Restore uploaded files that are missing locally."""
    result = {"restored": [], "skipped": [], "failed": []}

    project_root = Path(os.path.abspath("."))

    try:
        from src.storage import get_storage_client
        from src.utils.workspace_blob_sync import WorkspaceBlobSync

        client = get_storage_client(storage_provider)
        syncer = WorkspaceBlobSync(
            storage_client=client,
            project_root=str(project_root),
        )
    except Exception as e:
        result["failed"].append(f"user_uploads:init_failed ({e})")
        return result

    # Restore each file in parallel
    file_tasks = []
    file_labels = []

    for rel_path in uploaded_files:
        local_path = project_root / "user_uploads" / rel_path
        if local_path.exists():
            result["skipped"].append(f"upload:{rel_path}")
            continue
        file_tasks.append(
            asyncio.wait_for(
                syncer.restore_user_upload(rel_path),
                timeout=_BLOB_RESTORE_TIMEOUT,
            )
        )
        file_labels.append(rel_path)

    if file_tasks:
        file_results = await asyncio.gather(*file_tasks, return_exceptions=True)
        for label, file_result in zip(file_labels, file_results):
            if isinstance(file_result, Exception):
                if isinstance(file_result, asyncio.TimeoutError):
                    result["failed"].append(f"upload:{label} (timeout)")
                else:
                    result["failed"].append(f"upload:{label} ({file_result})")
            elif file_result:
                result["restored"].append(f"upload:{label}")
            else:
                result["skipped"].append(f"upload:{label} (not in blob)")

    return result


async def _restore_skills_folder(
    *,
    storage_provider: str,
    department: str,
    agent_id: str,
    skills_dir: Path,
) -> Dict[str, List[str]]:
    """Restore the skills folder for skill agents if missing/empty locally."""
    result = {"restored": [], "skipped": [], "failed": []}

    # Check if skills_dir already has content
    if skills_dir.exists() and any(skills_dir.iterdir()):
        result["skipped"].append(f"skills:{agent_id}")
        return result

    try:
        from src.storage import get_storage_client
        from src.utils.workspace_blob_sync import WorkspaceBlobSync

        client = get_storage_client(storage_provider)
        syncer = WorkspaceBlobSync(
            storage_client=client,
            workspace_root="./agent_workspaces",
            department=department,
            agent_id=agent_id,
        )

        blob_prefix = f"{department}/agentos_agents/{agent_id}/skills/"
        skills_dir.mkdir(parents=True, exist_ok=True)

        _bp = syncer.blob_prefix + blob_prefix
        report = await _retry_blob_operation(
            lambda: syncer.restore_workspace(blob_prefix=_bp, restore_root=skills_dir),
            label=f"skills:{agent_id}",
        )

        if report and report.synced > 0:
            result["restored"].append(f"skills:{agent_id} ({report.synced} files)")
            log.info(
                f"[PreInferenceRestore] Restored {report.synced} skill files for agent '{agent_id}'"
            )
            # Fix #28: integrity verification
            if _BLOB_INTEGRITY_CHECK:
                iv = verify_restored_directory(skills_dir)
                if iv["corrupt"]:
                    result["failed"].extend(f"skills:{agent_id}:CORRUPT:{c}" for c in iv["corrupt"])
                    log.warning(f"[PreInferenceRestore] {len(iv['corrupt'])} corrupt files in skills for '{agent_id}'")
        else:
            result["skipped"].append(f"skills:{agent_id} (not in blob)")

    except asyncio.TimeoutError:
        result["failed"].append(f"skills:{agent_id} (timeout after retries)")
        log.warning(f"[PreInferenceRestore] Timed out restoring skills for '{agent_id}' after retries")
    except Exception as e:
        result["failed"].append(f"skills:{agent_id} ({e})")
        log.debug(f"[PreInferenceRestore] Skills restore failed for '{agent_id}': {e}")

    return result


async def _restore_enterprise_context(
    *,
    storage_provider: str,
    department: str,
    agent_id: str,
    enterprise_dir: Path,
) -> Dict[str, List[str]]:
    """Restore the enterprise_context folder for skill agents if missing/empty locally."""
    result = {"restored": [], "skipped": [], "failed": []}

    # Check if enterprise_dir already has content
    if enterprise_dir.exists() and any(enterprise_dir.iterdir()):
        result["skipped"].append(f"enterprise_context:{agent_id}")
        return result

    try:
        from src.storage import get_storage_client
        from src.utils.workspace_blob_sync import WorkspaceBlobSync

        client = get_storage_client(storage_provider)
        syncer = WorkspaceBlobSync(
            storage_client=client,
            workspace_root="./agent_workspaces",
            department=department,
            agent_id=agent_id,
        )

        blob_prefix = f"{department}/agentos_agents/{agent_id}/enterprise_context/"
        enterprise_dir.mkdir(parents=True, exist_ok=True)

        _bp = syncer.blob_prefix + blob_prefix
        report = await _retry_blob_operation(
            lambda: syncer.restore_workspace(blob_prefix=_bp, restore_root=enterprise_dir),
            label=f"enterprise_context:{agent_id}",
        )

        if report and report.synced > 0:
            result["restored"].append(f"enterprise_context:{agent_id} ({report.synced} files)")
            log.info(
                f"[PreInferenceRestore] Restored {report.synced} enterprise_context files for agent '{agent_id}'"
            )
            # Fix #28: integrity verification
            if _BLOB_INTEGRITY_CHECK:
                iv = verify_restored_directory(enterprise_dir)
                if iv["corrupt"]:
                    result["failed"].extend(f"enterprise:{agent_id}:CORRUPT:{c}" for c in iv["corrupt"])
                    log.warning(f"[PreInferenceRestore] {len(iv['corrupt'])} corrupt files in enterprise_context for '{agent_id}'")
        else:
            result["skipped"].append(f"enterprise_context:{agent_id} (not in blob)")

    except asyncio.TimeoutError:
        result["failed"].append(f"enterprise_context:{agent_id} (timeout after retries)")
        log.warning(f"[PreInferenceRestore] Timed out restoring enterprise_context for '{agent_id}' after retries")
    except Exception as e:
        result["failed"].append(f"enterprise_context:{agent_id} ({e})")
        log.debug(f"[PreInferenceRestore] Enterprise context restore failed for '{agent_id}': {e}")

    return result


__all__ = [
    "ensure_inference_assets_available",
]
