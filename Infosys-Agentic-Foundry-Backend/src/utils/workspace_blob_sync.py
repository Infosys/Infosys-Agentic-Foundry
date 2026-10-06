# © 2024-25 Infosys Limited, Bangalore, India. All Rights Reserved.
"""
Background Workspace Sync to Cloud Blob Storage
================================================

Fire-and-forget background sync system that automatically pushes ALL
agent workspace file-based data to cloud blob storage (Azure Blob / AWS
S3 / GCS) using ``asyncio.create_task``.  All sync operations are
non-blocking and won't disrupt the agent flow if they fail.

Covers ALL file-based storage in IAF:
  1. Skills (SKILL.md, _index.yaml)
  2. Enterprise Context (Enterprise_Context.md, entity_guide.md, policies)
  3. Agent Config (agent_config.json)
  4. File Context Prompts ({agent}_file_context_prompt.md)
  5. Conversations (conversations.json)
  6. Agent Facts / Learnings / Entities
  7. Session Workspace + Pending Context
  8. User Preferences (preferences.md)
  9. Database Schema Cache (schema.md, samples.md)
  10. Vector Store Index (vectors.json)
  11. Onboarded Tools (.py files)
  12. Credentials (.secrets/)
  13. Audit Logs (shell + tool audit JSONL)
  14. Approval Requests (JSON)

Usage::

    from src.utils.workspace_blob_sync import WorkspaceBlobSync

    syncer = WorkspaceBlobSync(
        storage_client=self.storage_client,
        workspace_root="./agent_workspaces",
        department="General",
        agent_id="skl_019fcb6b34c4",
        session_id="sess_001",
        user_email="test@example.com",
    )

    # Fire-and-forget after any file write
    syncer.schedule_file_sync(local_path, blob_key)

    # Sync everything for this agent
    syncer.schedule_full_sync()

    # Sync ALL categories (skills + prompts + conversations + tools + ...)
    await syncer.sync_all()

    # Auto-restore on startup if workspace is missing
    await syncer.check_and_restore_if_needed()
"""

import os
import io
import asyncio
import time
import logging
from pathlib import Path
from typing import Optional, Dict, List, Any
from dataclasses import dataclass, field

try:
    from telemetry_wrapper import logger as log
except ImportError:
    log = logging.getLogger(__name__)

try:
    from src.storage.base import StorageInterface
except ImportError:
    StorageInterface = None  # type: ignore


# ========================================================================
# Data Models
# ========================================================================

@dataclass
class SyncResult:
    """Result of a single file sync operation."""
    local_path: str
    blob_key: str
    success: bool
    error: Optional[str] = None
    bytes_uploaded: int = 0
    elapsed_ms: float = 0.0


@dataclass
class WorkspaceSyncReport:
    """Aggregate report for a full workspace sync."""
    total_files: int = 0
    synced: int = 0
    failed: int = 0
    skipped: int = 0
    errors: List[str] = field(default_factory=list)
    results: List[SyncResult] = field(default_factory=list)
    elapsed_ms: float = 0.0
    categories_synced: Dict[str, int] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "total_files": self.total_files,
            "synced": self.synced,
            "failed": self.failed,
            "skipped": self.skipped,
            "errors": self.errors,
            "elapsed_ms": round(self.elapsed_ms, 2),
            "categories": self.categories_synced,
        }


# ========================================================================
# Exclusion list — files/dirs never synced to blob
# ========================================================================

SYNC_EXCLUDE_DIRS = {
    "__pycache__", ".git", "node_modules",
    ".venv", "venv", ".mypy_cache", ".pytest_cache",
}

SYNC_EXCLUDE_EXTENSIONS = {
    ".pyc", ".pyo", ".sqlite3",
    ".pkl", ".pickle", ".npy", ".npz",
}

MAX_FILE_SIZE_BYTES = 50 * 1024 * 1024  # 50 MB hard cap per file

# Categories with their blob key prefixes
SYNC_CATEGORIES = [
    "skills",
    "enterprise_context",
    "agent_config",
    "file_context_prompts",
    "conversations",
    "agent_facts",
    "session_workspace",
    "user_preferences",
    "database_cache",
    "vector_index",
    "onboarded_tools",
    "credentials",
    "audit_logs",
    "approvals",
    "uploaded_sqlite_dbs",
    "user_uploads",
    "evaluation_uploads",
    "file_context_prompts_recycle_bin",
    "outputs",
    "deletion_reports",
]


# ========================================================================
# WorkspaceBlobSync
# ========================================================================

class WorkspaceBlobSync:
    """
    Non-blocking background sync of ALL agent workspace files to cloud
    blob storage.

    Supports Azure Blob, AWS S3, and GCS via the StorageInterface
    abstraction.  All ``schedule_*`` methods use ``asyncio.create_task``
    to run fire-and-forget - failures are logged, never raised.

    Blob key structure::

        {dept}/agentos_agents/{agent_id}/skills/...
        {dept}/agentos_agents/{agent_id}/enterprise_context/...
        {dept}/agentos_agents/{agent_id}/agent_config.json
        {dept}/agentos_agents/{agent_id}/.secrets/...
        {dept}/agents/{agent_id}/agent/facts/...
        {dept}/agents/{agent_id}/sessions/{session_id}/...
        {dept}/users/{user_email}/preferences.md
        {dept}/databases/{conn_name}/schema.md
        {dept}/file_context_prompts/{agent}_file_context_prompt.md
        _global/onboarded_tools/{tool}.py
        _global/conversations/conversations.json
        _global/audit/{date}.jsonl
        _global/approvals/{id}.json
    """

    def __init__(
        self,
        storage_client,
        workspace_root: str = "./agent_workspaces",
        department: str = "General",
        agent_id: str = "",
        session_id: str = "",
        user_email: str = "",
        blob_prefix: str = "",
        project_root: str = "",
    ):
        self.storage_client = storage_client
        self.workspace_root = Path(workspace_root).resolve()
        self.department = department
        self.agent_id = agent_id
        self.session_id = session_id
        self.user_email = user_email
        self.user_dir_name = user_email.replace("@", "_at_").replace(".", "_") if user_email else ""
        self.blob_prefix = blob_prefix or ""
        self.project_root = Path(project_root).resolve() if project_root else self.workspace_root.parent
        self._pending_tasks: List[asyncio.Task] = []

    # ================================================================== #
    #  Path builders for all categories
    # ================================================================== #

    @property
    def _dept_root(self) -> Path:
        return self.workspace_root / self.department

    @property
    def _agentos_root(self) -> Path:
        return self._dept_root / "agentos_agents" / self.agent_id

    @property
    def _agent_root(self) -> Path:
        return self._dept_root / "agents" / self.agent_id

    @property
    def _session_root(self) -> Path:
        return self._agent_root / "sessions" / self.session_id

    def _get_sync_targets(self) -> List[Dict[str, Any]]:
        """
        Return list of all sync targets with their local root, blob prefix,
        and whether they exist. Each target is one category.
        """
        targets = []

        # 1. Skills
        skills = self._agentos_root / "skills"
        if skills.is_dir():
            targets.append({
                "category": "skills",
                "local_root": skills,
                "blob_prefix": f"{self.department}/agentos_agents/{self.agent_id}/skills/",
            })

        # 2. Enterprise Context
        ec = self._agentos_root / "enterprise_context"
        if ec.is_dir():
            targets.append({
                "category": "enterprise_context",
                "local_root": ec,
                "blob_prefix": f"{self.department}/agentos_agents/{self.agent_id}/enterprise_context/",
            })

        # 3. Agent Config
        config = self._agentos_root / "agent_config.json"
        if config.is_file():
            targets.append({
                "category": "agent_config",
                "local_root": None,
                "single_file": config,
                "blob_key": f"{self.department}/agentos_agents/{self.agent_id}/agent_config.json",
            })

        # 4. File Context Prompts (entire dept prompts dir)
        prompts_dir = self._dept_root / "file_context_prompts"
        if prompts_dir.is_dir():
            targets.append({
                "category": "file_context_prompts",
                "local_root": prompts_dir,
                "blob_prefix": f"{self.department}/file_context_prompts/",
            })

        # 5. Conversations (global)
        conv_path = self.project_root / "src" / "inference" / "chat_logs" / "conversations.json"
        if conv_path.is_file():
            targets.append({
                "category": "conversations",
                "local_root": None,
                "single_file": conv_path,
                "blob_key": "_global/conversations/conversations.json",
            })

        # 6. Agent Facts / Learnings / Entities
        agent_data = self._agent_root / "agent"
        if agent_data.is_dir():
            targets.append({
                "category": "agent_facts",
                "local_root": agent_data,
                "blob_prefix": f"{self.department}/agents/{self.agent_id}/agent/",
            })

        # 7. Session Workspace + pending context + history
        if self.session_id:
            session_data = self._session_root / "session"
            if session_data.is_dir():
                targets.append({
                    "category": "session_workspace",
                    "local_root": session_data,
                    "blob_prefix": f"{self.department}/agents/{self.agent_id}/sessions/{self.session_id}/session/",
                })

        # 8. User Preferences
        if self.user_dir_name:
            user_dir = self._dept_root / "users" / self.user_dir_name
            if user_dir.is_dir():
                targets.append({
                    "category": "user_preferences",
                    "local_root": user_dir,
                    "blob_prefix": f"{self.department}/users/{self.user_dir_name}/",
                })

        # 9. Database Schema Cache (shared across dept)
        db_dir = self._dept_root / "databases"
        if db_dir.is_dir():
            targets.append({
                "category": "database_cache",
                "local_root": db_dir,
                "blob_prefix": f"{self.department}/databases/",
            })

        # 10. Vector Store Index
        if self.session_id:
            index_dir = self._session_root / ".index"
            if index_dir.is_dir():
                targets.append({
                    "category": "vector_index",
                    "local_root": index_dir,
                    "blob_prefix": f"{self.department}/agents/{self.agent_id}/sessions/{self.session_id}/.index/",
                })

        # 11. Onboarded Tools (global)
        tools_dir = self.project_root / "onboarded_tools"
        if tools_dir.is_dir():
            targets.append({
                "category": "onboarded_tools",
                "local_root": tools_dir,
                "blob_prefix": "_global/onboarded_tools/",
            })

        # 12. Credentials
        secrets_dir = self._agentos_root / ".secrets"
        if secrets_dir.is_dir():
            targets.append({
                "category": "credentials",
                "local_root": secrets_dir,
                "blob_prefix": f"{self.department}/agentos_agents/{self.agent_id}/.secrets/",
            })

        # 13. Audit Logs
        audit_dir = self.workspace_root / "_agentos_meta" / "_audit"
        if audit_dir.is_dir():
            targets.append({
                "category": "audit_logs",
                "local_root": audit_dir,
                "blob_prefix": "_global/audit/",
            })
        # Per-agent audit
        agent_audit = self._agentos_root / ".audit"
        if agent_audit.is_dir():
            targets.append({
                "category": "audit_logs",
                "local_root": agent_audit,
                "blob_prefix": f"{self.department}/agentos_agents/{self.agent_id}/.audit/",
            })

        # 15. Uploaded SQLite DBs (global)
        sqlite_dbs_dir = self.project_root / "uploaded_sqlite_dbs"
        if sqlite_dbs_dir.is_dir():
            targets.append({
                "category": "uploaded_sqlite_dbs",
                "local_root": sqlite_dbs_dir,
                "blob_prefix": "_global/uploaded_sqlite_dbs/",
            })

        # 16. User Uploads (global)
        user_uploads_dir = self.project_root / "user_uploads"
        if user_uploads_dir.is_dir():
            targets.append({
                "category": "user_uploads",
                "local_root": user_uploads_dir,
                "blob_prefix": "_global/user_uploads/",
            })

        # 17. Evaluation Uploads (global)
        eval_uploads_dir = self.project_root / "evaluation_uploads"
        if eval_uploads_dir.is_dir():
            targets.append({
                "category": "evaluation_uploads",
                "local_root": eval_uploads_dir,
                "blob_prefix": "_global/evaluation_uploads/",
            })

        # 18. File Context Prompts Recycle Bin (per-dept)
        recycle_dir = self._dept_root / "file_context_prompts_recycle_bin"
        if recycle_dir.is_dir():
            targets.append({
                "category": "file_context_prompts_recycle_bin",
                "local_root": recycle_dir,
                "blob_prefix": f"{self.department}/file_context_prompts_recycle_bin/",
            })

        # 19. Outputs — evaluation result files (global)
        outputs_dir = self.project_root / "outputs"
        if outputs_dir.is_dir():
            targets.append({
                "category": "outputs",
                "local_root": outputs_dir,
                "blob_prefix": "_global/outputs/",
            })

        # 20. Deletion Reports — admin audit trail (global)
        deletion_reports_dir = self.project_root / "deletion_reports"
        if deletion_reports_dir.is_dir():
            targets.append({
                "category": "deletion_reports",
                "local_root": deletion_reports_dir,
                "blob_prefix": "_global/deletion_reports/",
            })

        return targets

    # ================================================================== #
    #  Public: sync ALL categories (blocking)
    # ================================================================== #

    async def sync_all(self, dry_run: bool = False) -> WorkspaceSyncReport:
        """
        Sync ALL file-based data for this agent to blob storage.

        Walks every category (skills, prompts, conversations, facts,
        session workspace, preferences, DB cache, tools, credentials,
        audit, approvals) and uploads everything.

        Args:
            dry_run: Enumerate files without uploading.

        Returns:
            WorkspaceSyncReport with per-category breakdown.
        """
        start = time.perf_counter()
        report = WorkspaceSyncReport()

        if not self.storage_client:
            report.errors.append("No storage client configured")
            return report

        targets = self._get_sync_targets()

        for target in targets:
            category = target["category"]

            if "single_file" in target:
                # Single file sync
                local_path = target["single_file"]
                blob_key = self.blob_prefix + target["blob_key"]

                if dry_run:
                    report.total_files += 1
                    report.synced += 1
                    report.categories_synced[category] = report.categories_synced.get(category, 0) + 1
                    continue

                result = await self.sync_file(local_path, blob_key)
                report.total_files += 1
                report.results.append(result)
                if result.success:
                    report.synced += 1
                    report.categories_synced[category] = report.categories_synced.get(category, 0) + 1
                else:
                    report.failed += 1
                    report.errors.append(f"[{category}] {result.error}")
            else:
                # Directory sync
                local_root = target["local_root"]
                blob_prefix = self.blob_prefix + target["blob_prefix"]
                files = self._collect_files(local_root)

                for local_path in files:
                    try:
                        relative = local_path.relative_to(local_root)
                    except ValueError:
                        continue

                    blob_key = blob_prefix + str(relative).replace("\\", "/")
                    report.total_files += 1

                    if dry_run:
                        report.synced += 1
                        report.categories_synced[category] = report.categories_synced.get(category, 0) + 1
                        continue

                    result = await self.sync_file(local_path, blob_key)
                    report.results.append(result)
                    if result.success:
                        report.synced += 1
                        report.categories_synced[category] = report.categories_synced.get(category, 0) + 1
                    else:
                        report.failed += 1
                        report.errors.append(f"[{category}] {blob_key}: {result.error}")

        report.elapsed_ms = (time.perf_counter() - start) * 1000
        log.info(
            f"[WorkspaceBlobSync] Full sync: "
            f"{report.synced}/{report.total_files} files across "
            f"{len(report.categories_synced)} categories in {report.elapsed_ms:.0f}ms"
        )
        return report

    # ================================================================== #
    #  Public: auto-restore on startup
    # ================================================================== #

    async def check_and_restore_if_needed(self) -> Optional[WorkspaceSyncReport]:
        """
        Check if agent's local workspace is missing or empty.
        If so, automatically restore ALL data from blob storage.

        Restores:
          - agentos_agents/{agent_id}/ (skills, enterprise_context, config, secrets)
          - agents/{agent_id}/ (facts, learnings, sessions)
          - users/{user_email}/ (preferences)
          - databases/ (schema cache)
          - file_context_prompts/ (system prompts)
          - Conversations (conversations.json)
          - Onboarded tools

        Triggers restore when:
          1. agentos_agents/{agent_id} directory is missing
          2. OR skills/ directory is empty
          3. OR agent/{agent_id}/agent/ (facts) is missing

        Returns:
            WorkspaceSyncReport if restore was performed, None otherwise.
        """
        if not self.storage_client:
            return None
        if not self.agent_id:
            return None

        needs_restore = False
        restore_targets: List[Dict[str, Any]] = []

        # Check agentos path (skills + enterprise_context + config)
        agentos_root = self._agentos_root
        skills_root = agentos_root / "skills"
        if not agentos_root.exists():
            log.info(f"[WorkspaceBlobSync] Agent workspace missing: {agentos_root}")
            needs_restore = True
            restore_targets.append({
                "blob_prefix": f"{self.department}/agentos_agents/{self.agent_id}/",
                "local_root": agentos_root,
            })
        elif not skills_root.exists() or not any(skills_root.iterdir()):
            log.info(f"[WorkspaceBlobSync] Skills missing/empty: {skills_root}")
            needs_restore = True
            restore_targets.append({
                "blob_prefix": f"{self.department}/agentos_agents/{self.agent_id}/",
                "local_root": agentos_root,
            })

        # Check agent data (facts/learnings/entities)
        agent_data = self._agent_root / "agent"
        if not agent_data.exists():
            log.info(f"[WorkspaceBlobSync] Agent facts missing: {agent_data}")
            needs_restore = True
            restore_targets.append({
                "blob_prefix": f"{self.department}/agents/{self.agent_id}/",
                "local_root": self._agent_root,
            })

        # Check file context prompts (only if agent workspace itself is missing)
        if needs_restore:
            prompts_dir = self._dept_root / "file_context_prompts"
            if not prompts_dir.exists() or (prompts_dir.exists() and not any(prompts_dir.iterdir())):
                restore_targets.append({
                    "blob_prefix": f"{self.department}/file_context_prompts/",
                    "local_root": prompts_dir,
                })

        # Check user preferences (only piggyback on primary restore)
        if needs_restore and self.user_dir_name:
            user_dir = self._dept_root / "users" / self.user_dir_name
            if not user_dir.exists():
                restore_targets.append({
                    "blob_prefix": f"{self.department}/users/{self.user_dir_name}/",
                    "local_root": user_dir,
                })

        # Check database schema cache (only piggyback on primary restore)
        if needs_restore:
            db_dir = self._dept_root / "databases"
            if not db_dir.exists():
                restore_targets.append({
                    "blob_prefix": f"{self.department}/databases/",
                    "local_root": db_dir,
                })

        # Check conversations (only piggyback on primary restore)
        if needs_restore:
            conv_path = self.project_root / "src" / "inference" / "chat_logs" / "conversations.json"
            if not conv_path.exists():
                restore_targets.append({
                    "blob_prefix": "_global/conversations/",
                    "local_root": conv_path.parent,
                })

        # Check onboarded tools (only piggyback on primary restore)
        if needs_restore:
            tools_dir = self.project_root / "onboarded_tools"
            if not tools_dir.exists() or (tools_dir.exists() and not any(tools_dir.iterdir())):
                restore_targets.append({
                    "blob_prefix": "_global/onboarded_tools/",
                    "local_root": tools_dir,
                })

        if not needs_restore:
            return None

        log.info(
            f"[WorkspaceBlobSync] Restore needed for {len(restore_targets)} targets. "
            f"Agent: {self.agent_id}"
        )

        # Perform restore for each target
        start = time.perf_counter()
        combined = WorkspaceSyncReport()

        for target in restore_targets:
            # Prepend self.blob_prefix so restore_workspace uses the full blob path
            full_prefix = self.blob_prefix + target["blob_prefix"]
            report = await self.restore_workspace(
                blob_prefix=full_prefix,
                restore_root=target["local_root"],
            )
            combined.total_files += report.total_files
            combined.synced += report.synced
            combined.failed += report.failed
            combined.errors.extend(report.errors)
            combined.results.extend(report.results)

        combined.elapsed_ms = (time.perf_counter() - start) * 1000

        if combined.synced > 0:
            log.info(
                f"[WorkspaceBlobSync] Auto-restored {combined.synced} files "
                f"for agent {self.agent_id} from blob in {combined.elapsed_ms:.0f}ms"
            )
        elif combined.total_files == 0:
            log.warning(
                f"[WorkspaceBlobSync] No files found in blob for agent {self.agent_id}. "
                f"Workspace will start empty."
            )

        return combined

    # ================================================================== #
    #  Public: single-file sync (blocking)
    # ================================================================== #

    async def sync_file(self, local_path: Path, blob_key: str) -> SyncResult:
        """
        Upload a single local file to blob storage.

        Args:
            local_path: Absolute path to the local file.
            blob_key: The object key (path) in blob storage.

        Returns:
            SyncResult with success/failure details.
        """
        start = time.perf_counter()
        local_path = Path(local_path).resolve()

        if not local_path.is_file():
            return SyncResult(
                local_path=str(local_path),
                blob_key=blob_key,
                success=False,
                error=f"File not found: {local_path}",
            )

        file_size = local_path.stat().st_size
        if file_size > MAX_FILE_SIZE_BYTES:
            return SyncResult(
                local_path=str(local_path),
                blob_key=blob_key,
                success=False,
                error=f"File too large ({file_size} bytes > {MAX_FILE_SIZE_BYTES})",
            )

        if local_path.suffix.lower() in SYNC_EXCLUDE_EXTENSIONS:
            return SyncResult(
                local_path=str(local_path),
                blob_key=blob_key,
                success=False,
                error=f"Excluded extension: {local_path.suffix}",
            )

        try:
            content = await asyncio.to_thread(local_path.read_bytes)
            file_obj = io.BytesIO(content)

            url = await asyncio.to_thread(
                self.storage_client.upload_file, file_obj, blob_key
            )

            elapsed = (time.perf_counter() - start) * 1000
            log.info(f"[WorkspaceBlobSync] Synced '{blob_key}' ({file_size}B) in {elapsed:.0f}ms")

            return SyncResult(
                local_path=str(local_path),
                blob_key=blob_key,
                success=True,
                bytes_uploaded=file_size,
                elapsed_ms=elapsed,
            )

        except Exception as e:
            elapsed = (time.perf_counter() - start) * 1000
            log.error(f"[WorkspaceBlobSync] Failed to sync {blob_key}: {e}")
            return SyncResult(
                local_path=str(local_path),
                blob_key=blob_key,
                success=False,
                error=str(e),
                elapsed_ms=elapsed,
            )

    # ================================================================== #
    #  Public: directory sync (blocking)
    # ================================================================== #

    async def sync_workspace(
        self,
        root_override: Optional[Path] = None,
        dry_run: bool = False,
    ) -> WorkspaceSyncReport:
        """
        Walk a directory and sync all eligible files to blob storage.

        Args:
            root_override: Override the sync root (defaults to agent dir).
            dry_run: If True, enumerate files but don't upload.

        Returns:
            WorkspaceSyncReport with per-file results.
        """
        start = time.perf_counter()
        report = WorkspaceSyncReport()

        sync_root = root_override or (
            self.workspace_root / self.department / "agents" / self.agent_id
        )

        if not sync_root.is_dir():
            report.errors.append(f"Sync root not found: {sync_root}")
            return report

        files = self._collect_files(sync_root)
        report.total_files = len(files)

        for local_path in files:
            try:
                relative = local_path.relative_to(self.workspace_root)
            except ValueError:
                try:
                    relative = local_path.relative_to(sync_root)
                except ValueError:
                    continue

            blob_key = self.blob_prefix + str(relative).replace("\\", "/")

            if dry_run:
                report.results.append(SyncResult(
                    local_path=str(local_path),
                    blob_key=blob_key,
                    success=True,
                    error="dry_run",
                ))
                report.synced += 1
                continue

            result = await self.sync_file(local_path, blob_key)
            report.results.append(result)

            if result.success:
                report.synced += 1
            else:
                report.failed += 1
                report.errors.append(f"{blob_key}: {result.error}")

        report.elapsed_ms = (time.perf_counter() - start) * 1000
        log.info(
            f"[WorkspaceBlobSync] Workspace sync: "
            f"{report.synced}/{report.total_files} synced, "
            f"{report.failed} failed in {report.elapsed_ms:.0f}ms"
        )
        return report

    # ================================================================== #
    #  Blob Deletion (remove files from blob after local deletion)
    # ================================================================== #

    async def delete_blob_prefix(self, blob_prefix: str) -> int:
        """
        Delete ALL blob keys under a given prefix.

        Used when a local folder is deleted (skill, agent, db schema) to keep
        blob in sync and prevent stale files from being restored later.

        Args:
            blob_prefix: The full blob key prefix (e.g. "General/agentos_agents/{id}/skills/{name}/")

        Returns:
            Number of blobs successfully deleted.
        """
        if not self.storage_client:
            return 0

        deleted = 0
        try:
            full_prefix = self.blob_prefix + blob_prefix
            blob_keys = await asyncio.to_thread(
                self.storage_client.list_files, full_prefix
            )
            for key in blob_keys:
                try:
                    success = await asyncio.to_thread(
                        self.storage_client.delete_file, key
                    )
                    if success:
                        deleted += 1
                except Exception as e:
                    log.debug(f"[WorkspaceBlobSync] Failed to delete blob '{key}': {e}")

            if deleted > 0:
                log.info(
                    f"[WorkspaceBlobSync] Deleted {deleted}/{len(blob_keys)} blobs "
                    f"under prefix '{full_prefix}'"
                )
        except Exception as e:
            log.warning(f"[WorkspaceBlobSync] delete_blob_prefix failed for '{blob_prefix}': {e}")

        return deleted

    async def delete_blob_file(self, blob_key: str) -> bool:
        """
        Delete a single blob by its key.

        Args:
            blob_key: The blob key relative to blob_prefix (e.g. "General/databases/conn/schema.md")

        Returns:
            True if deleted successfully.
        """
        if not self.storage_client:
            return False
        try:
            full_key = self.blob_prefix + blob_key
            success = await asyncio.to_thread(
                self.storage_client.delete_file, full_key
            )
            if success:
                log.info(f"[WorkspaceBlobSync] Deleted blob: {full_key}")
            return success
        except Exception as e:
            log.debug(f"[WorkspaceBlobSync] delete_blob_file failed for '{blob_key}': {e}")
            return False

    def schedule_blob_prefix_delete(
        self, blob_prefix: str, *, name: str = "blob_prefix_delete"
    ) -> Optional[asyncio.Task]:
        """Fire-and-forget: delete all blobs under a prefix."""
        if not self.storage_client:
            return None
        try:
            task = asyncio.create_task(
                self.delete_blob_prefix(blob_prefix), name=name
            )
            task.add_done_callback(self._on_task_done)
            self._pending_tasks.append(task)
            return task
        except RuntimeError:
            log.debug("[WorkspaceBlobSync] No event loop - skipping schedule_blob_prefix_delete")
            return None

    def schedule_blob_file_delete(
        self, blob_key: str, *, name: str = "blob_file_delete"
    ) -> Optional[asyncio.Task]:
        """Fire-and-forget: delete a single blob."""
        if not self.storage_client:
            return None
        try:
            task = asyncio.create_task(
                self.delete_blob_file(blob_key), name=name
            )
            task.add_done_callback(self._on_task_done)
            self._pending_tasks.append(task)
            return task
        except RuntimeError:
            log.debug("[WorkspaceBlobSync] No event loop - skipping schedule_blob_file_delete")
            return None

    # ================================================================== #
    #  Public: fire-and-forget schedulers
    # ================================================================== #

    def schedule_file_sync(
        self, local_path: Path, blob_key: str, *, name: str = "blob_file_sync"
    ) -> Optional[asyncio.Task]:
        """Schedule a single file upload as a background task."""
        if not self.storage_client:
            return None
        try:
            task = asyncio.create_task(
                self.sync_file(local_path, blob_key), name=name
            )
            task.add_done_callback(self._on_task_done)
            self._pending_tasks.append(task)
            return task
        except RuntimeError:
            log.debug("[WorkspaceBlobSync] No event loop - skipping schedule_file_sync")
            return None

    def _schedule_dir_sync(
        self, local_dir: Path, blob_prefix: str, *, name: str = "blob_dir_sync"
    ) -> Optional[asyncio.Task]:
        """Schedule upload of every file in *local_dir* as a single background task."""
        if not self.storage_client:
            return None

        async def _sync_dir():
            for fpath in local_dir.rglob("*"):
                if fpath.is_file() and fpath.stat().st_size <= MAX_FILE_SIZE_BYTES:
                    rel = fpath.relative_to(local_dir).as_posix()
                    await self.sync_file(fpath, blob_prefix + rel)

        try:
            task = asyncio.create_task(_sync_dir(), name=name)
            task.add_done_callback(self._on_task_done)
            self._pending_tasks.append(task)
            return task
        except RuntimeError:
            log.debug("[WorkspaceBlobSync] No event loop - skipping _schedule_dir_sync")
            return None

    def schedule_full_sync(
        self,
        root_override: Optional[Path] = None,
        *,
        name: str = "blob_workspace_sync",
    ) -> Optional[asyncio.Task]:
        """Schedule a full workspace sync as a background task."""
        if not self.storage_client:
            return None
        try:
            task = asyncio.create_task(
                self.sync_workspace(root_override=root_override), name=name
            )
            task.add_done_callback(self._on_task_done)
            self._pending_tasks.append(task)
            return task
        except RuntimeError:
            log.debug("[WorkspaceBlobSync] No event loop - skipping schedule_full_sync")
            return None

    def schedule_sync_all(self, *, name: str = "blob_sync_all") -> Optional[asyncio.Task]:
        """Schedule sync of ALL categories as a background task."""
        if not self.storage_client:
            return None
        try:
            task = asyncio.create_task(self.sync_all(), name=name)
            task.add_done_callback(self._on_task_done)
            self._pending_tasks.append(task)
            return task
        except RuntimeError:
            log.debug("[WorkspaceBlobSync] No event loop - skipping schedule_sync_all")
            return None

    # ================================================================== #
    #  Public: category-specific sync helpers
    # ================================================================== #

    def schedule_conversation_sync(self) -> Optional[asyncio.Task]:
        """Fire-and-forget sync of conversations.json after a chat save."""
        conv_path = self.project_root / "src" / "inference" / "chat_logs" / "conversations.json"
        if conv_path.is_file():
            return self.schedule_file_sync(
                conv_path,
                self.blob_prefix + "_global/conversations/conversations.json",
                name="blob_sync_conversations",
            )
        return None

    def schedule_file_context_prompt_sync(self, agent_name: str) -> Optional[asyncio.Task]:
        """Fire-and-forget sync of a file context prompt after write."""
        safe_name = agent_name.replace(" ", "_").replace("-", "_")
        prompt_file = self._dept_root / "file_context_prompts" / f"{safe_name}_file_context_prompt.md"
        if prompt_file.is_file():
            blob_key = f"{self.department}/file_context_prompts/{safe_name}_file_context_prompt.md"
            return self.schedule_file_sync(
                prompt_file, self.blob_prefix + blob_key,
                name="blob_sync_prompt",
            )
        return None

    def schedule_database_cache_sync(self, connection_name: str) -> Optional[asyncio.Task]:
        """Fire-and-forget sync of database schema/samples after save."""
        db_dir = self._dept_root / "databases" / connection_name
        if db_dir.is_dir():
            return self.schedule_full_sync(
                root_override=db_dir,
                name=f"blob_sync_db_{connection_name}",
            )
        return None

    async def restore_database_cache(
        self, connection_name: str = None
    ) -> Optional["WorkspaceSyncReport"]:
        """Restore database schema/samples from blob if missing locally.

        Args:
            connection_name: Restore files for a specific connection.
                             If None, restores the entire databases/ directory.

        Returns:
            WorkspaceSyncReport if restore was performed, None otherwise.
        """
        if not self.storage_client:
            return None

        if connection_name:
            local_dir = self._dept_root / "databases" / connection_name
            blob_prefix = f"{self.department}/databases/{connection_name}/"
        else:
            local_dir = self._dept_root / "databases"
            blob_prefix = f"{self.department}/databases/"

        # Only restore if local directory is empty/missing
        if local_dir.exists() and any(local_dir.rglob("*.md")):
            return None

        log.info(f"[WorkspaceBlobSync] Restoring database cache from blob: {blob_prefix}")
        return await self.restore_workspace(self.blob_prefix + blob_prefix, local_dir)

    def schedule_tool_file_sync(self, tool_name: str) -> Optional[asyncio.Task]:
        """Fire-and-forget sync of a tool .py file after create/update."""
        sanitized = "".join(c if c.isalnum() or c in ('_', '-') else '_' for c in tool_name)
        tool_file = self.project_root / "onboarded_tools" / f"{sanitized}.py"
        if tool_file.is_file():
            blob_key = f"_global/onboarded_tools/{sanitized}.py"
            return self.schedule_file_sync(
                tool_file, self.blob_prefix + blob_key,
                name="blob_sync_tool",
            )
        return None

    def schedule_skills_sync(self) -> Optional[asyncio.Task]:
        """Fire-and-forget sync of entire skills directory."""
        skills_dir = self._agentos_root / "skills"
        if skills_dir.is_dir():
            return self.schedule_full_sync(
                root_override=skills_dir,
                name="blob_sync_skills",
            )
        return None

    def schedule_agent_data_sync(self) -> Optional[asyncio.Task]:
        """Fire-and-forget sync of agent facts/learnings/entities."""
        agent_data = self._agent_root / "agent"
        if agent_data.is_dir():
            return self.schedule_full_sync(
                root_override=agent_data,
                name="blob_sync_agent_data",
            )
        return None

    # ================================================================== #
    #  Uploaded SQLite DBs  (uploaded_sqlite_dbs/)
    # ================================================================== #

    def schedule_sqlite_db_sync(self, department: str, filename: str) -> Optional[asyncio.Task]:
        """Fire-and-forget sync of an uploaded SQLite .db file."""
        db_file = self.project_root / "uploaded_sqlite_dbs" / department / filename
        if db_file.is_file():
            blob_key = f"_global/uploaded_sqlite_dbs/{department}/{filename}"
            return self.schedule_file_sync(
                db_file, self.blob_prefix + blob_key,
                name=f"blob_sync_sqlite_{filename}",
            )
        return None

    async def restore_sqlite_db(
        self, department: str, filename: str
    ) -> bool:
        """Restore a single SQLite .db file from blob if missing locally.

        Returns True if the file exists on disk after the attempt.
        """
        local_path = self.project_root / "uploaded_sqlite_dbs" / department / filename
        if local_path.exists():
            return True
        if not self.storage_client:
            return False
        blob_key = f"_global/uploaded_sqlite_dbs/{department}/{filename}"
        result = await self.restore_file(self.blob_prefix + blob_key, local_path)
        if result and result.success:
            log.info(f"[BlobRestore] Restored SQLite DB from blob: {blob_key}")
            return True
        return False

    def restore_sqlite_db_sync(
        self, department: str, filename: str
    ) -> bool:
        """Synchronous version of :meth:`restore_sqlite_db`.

        Safe to call from non-async code (e.g. ``get_sql_session``).
        Uses the storage client's native sync methods directly.
        Returns True if the file is present on disk after the call.
        """
        local_path = self.project_root / "uploaded_sqlite_dbs" / department / filename
        if local_path.exists():
            return True
        if not self.storage_client:
            return False
        blob_key = self.blob_prefix + f"_global/uploaded_sqlite_dbs/{department}/{filename}"
        try:
            if not self.storage_client.file_exists(blob_key):
                return False
            file_obj = self.storage_client.download_file(blob_key)
            local_path.parent.mkdir(parents=True, exist_ok=True)
            content = file_obj.read() if hasattr(file_obj, "read") else file_obj
            local_path.write_bytes(content)
            log.info(
                f"[BlobRestore] Restored SQLite DB from blob (sync): "
                f"_global/uploaded_sqlite_dbs/{department}/{filename}"
            )
            return True
        except Exception as exc:
            log.warning(f"[BlobRestore] sync restore of SQLite DB failed: {exc}")
            return False

    # ================================================================== #
    #  User Uploads  (user_uploads/)
    # ================================================================== #

    def schedule_user_upload_sync(
        self, relative_path: str
    ) -> Optional[asyncio.Task]:
        """Fire-and-forget sync of a file in user_uploads/.

        Args:
            relative_path: Path relative to user_uploads/, e.g. "General/report.pdf"
        """
        local_file = self.project_root / "user_uploads" / relative_path
        if local_file.is_file():
            blob_key = f"_global/user_uploads/{relative_path}"
            return self.schedule_file_sync(
                local_file, self.blob_prefix + blob_key,
                name="blob_sync_user_upload",
            )
        return None

    async def restore_user_upload(self, relative_path: str) -> bool:
        """Restore a single file from user_uploads/ if missing locally."""
        local_path = self.project_root / "user_uploads" / relative_path
        if local_path.exists():
            return True
        if not self.storage_client:
            return False
        blob_key = f"_global/user_uploads/{relative_path}"
        result = await self.restore_file(self.blob_prefix + blob_key, local_path)
        if result and result.success:
            log.info(f"[BlobRestore] Restored user upload: {blob_key}")
            return True
        return False

    # ================================================================== #
    #  Evaluation Uploads  (evaluation_uploads/)
    # ================================================================== #

    def schedule_evaluation_upload_sync(
        self, relative_path: str
    ) -> Optional[asyncio.Task]:
        """Fire-and-forget sync of a file in evaluation_uploads/."""
        local_file = self.project_root / "evaluation_uploads" / relative_path
        if local_file.is_file():
            blob_key = f"_global/evaluation_uploads/{relative_path}"
            return self.schedule_file_sync(
                local_file, self.blob_prefix + blob_key,
                name="blob_sync_eval_upload",
            )
        return None

    async def restore_evaluation_upload(self, relative_path: str) -> bool:
        """Restore a single evaluation upload file if missing locally."""
        local_path = self.project_root / "evaluation_uploads" / relative_path
        if local_path.exists():
            return True
        if not self.storage_client:
            return False
        blob_key = f"_global/evaluation_uploads/{relative_path}"
        result = await self.restore_file(self.blob_prefix + blob_key, local_path)
        if result and result.success:
            log.info(f"[BlobRestore] Restored evaluation upload: {blob_key}")
            return True
        return False

    # ================================================================== #
    #  Credentials  (.secrets/)
    # ================================================================== #

    def schedule_credentials_sync(self) -> Optional[asyncio.Task]:
        """Fire-and-forget sync of the .secrets/ folder for the current agent."""
        secrets_dir = self._agentos_root / ".secrets"
        if not secrets_dir.is_dir():
            return None
        blob_prefix = f"{self.department}/agentos_agents/{self.agent_id}/.secrets/"
        return self._schedule_dir_sync(
            secrets_dir, self.blob_prefix + blob_prefix,
            name="blob_sync_credentials",
        )

    # ================================================================== #\n    #  Onboarded Tools — immediate per-file sync\n    # ================================================================== #

    def schedule_tool_file_sync(self, filename: str) -> Optional[asyncio.Task]:
        """Fire-and-forget sync of a single onboarded tool .py file."""
        tool_file = self.project_root / "onboarded_tools" / filename
        if tool_file.is_file():
            blob_key = f"_global/onboarded_tools/{filename}"
            return self.schedule_file_sync(
                tool_file, self.blob_prefix + blob_key,
                name=f"blob_sync_tool_{filename}",
            )
        return None

    # ================================================================== #
    #  File Context Prompts Recycle Bin  (per-dept)
    # ================================================================== #

    def schedule_recycle_bin_sync(self, filename: str) -> Optional[asyncio.Task]:
        """Fire-and-forget sync of a file in the recycle bin."""
        rb_dir = self._dept_root / "file_context_prompts_recycle_bin"
        local_file = rb_dir / filename
        if local_file.is_file():
            blob_key = f"{self.department}/file_context_prompts_recycle_bin/{filename}"
            return self.schedule_file_sync(
                local_file, self.blob_prefix + blob_key,
                name="blob_sync_recycle_bin",
            )
        return None

    async def restore_recycle_bin_file(self, filename: str) -> bool:
        """Restore a single file from the recycle bin if missing."""
        local_path = self._dept_root / "file_context_prompts_recycle_bin" / filename
        if local_path.exists():
            return True
        if not self.storage_client:
            return False
        blob_key = f"{self.department}/file_context_prompts_recycle_bin/{filename}"
        result = await self.restore_file(self.blob_prefix + blob_key, local_path)
        if result and result.success:
            log.info(f"[BlobRestore] Restored recycle bin file: {blob_key}")
            return True
        return False

    # ================================================================== #
    #  Outputs — evaluation result XLSX (global)
    # ================================================================== #

    def schedule_output_sync(self, filename: str) -> Optional[asyncio.Task]:
        """Fire-and-forget sync of an evaluation result file."""
        local_file = self.project_root / "outputs" / filename
        if local_file.is_file():
            blob_key = f"_global/outputs/{filename}"
            return self.schedule_file_sync(
                local_file, self.blob_prefix + blob_key,
                name="blob_sync_output",
            )
        return None

    async def restore_output_file(self, filename: str) -> bool:
        """Restore a single output file from blob if missing locally."""
        local_path = self.project_root / "outputs" / filename
        if local_path.exists():
            return True
        if not self.storage_client:
            return False
        blob_key = f"_global/outputs/{filename}"
        result = await self.restore_file(self.blob_prefix + blob_key, local_path)
        if result and result.success:
            log.info(f"[BlobRestore] Restored output file: {blob_key}")
            return True
        return False

    # ================================================================== #
    #  Deletion Reports — admin audit trail (global)
    # ================================================================== #

    def schedule_deletion_report_sync(self, filename: str) -> Optional[asyncio.Task]:
        """Fire-and-forget sync of a deletion report XLSX."""
        local_file = self.project_root / "deletion_reports" / filename
        if local_file.is_file():
            blob_key = f"_global/deletion_reports/{filename}"
            return self.schedule_file_sync(
                local_file, self.blob_prefix + blob_key,
                name="blob_sync_deletion_report",
            )
        return None

    # ================================================================== #
    #  Public: blob key builders
    # ================================================================== #

    def make_blob_key(self, virtual_path: str) -> str:
        """
        Convert a virtual shell path to a blob storage key.

        /session/workspace/notes.md
          -> General/agents/skl_001/sessions/sess_001/session/workspace/notes.md
        """
        vp = virtual_path.lstrip("/")
        prefix = f"{self.department}/agents/{self.agent_id}/sessions/{self.session_id}/"
        return self.blob_prefix + prefix + vp

    def make_agentos_blob_key(self, virtual_path: str) -> str:
        """
        Convert a virtual path under /skills or /enterprise_context.

        /skills/leave_policy/SKILL.md
          -> General/agentos_agents/skl_001/skills/leave_policy/SKILL.md
        """
        vp = virtual_path.lstrip("/")
        prefix = f"{self.department}/agentos_agents/{self.agent_id}/"
        return self.blob_prefix + prefix + vp

    def make_global_blob_key(self, category: str, filename: str) -> str:
        """Build a blob key for global files (tools, conversations, audit)."""
        return self.blob_prefix + f"_global/{category}/{filename}"

    async def verify_blob_exists(self, blob_key: str) -> bool:
        """Check if a blob exists in storage."""
        if not self.storage_client:
            return False
        try:
            return await asyncio.to_thread(
                self.storage_client.file_exists, blob_key
            )
        except Exception:
            return False

    # ================================================================== #
    #  Public: restore from blob (download)
    # ================================================================== #

    async def restore_file(self, blob_key: str, local_path: Path) -> SyncResult:
        """
        Download a single file from blob storage and write to local disk.
        """
        start = time.perf_counter()
        local_path = Path(local_path)

        if not self.storage_client:
            return SyncResult(
                local_path=str(local_path),
                blob_key=blob_key,
                success=False,
                error="No storage client configured",
            )

        try:
            exists = await asyncio.to_thread(
                self.storage_client.file_exists, blob_key
            )
            if not exists:
                return SyncResult(
                    local_path=str(local_path),
                    blob_key=blob_key,
                    success=False,
                    error=f"Blob not found: {blob_key}",
                )

            file_obj = await asyncio.to_thread(
                self.storage_client.download_file, blob_key
            )

            local_path.parent.mkdir(parents=True, exist_ok=True)

            content = file_obj.read() if hasattr(file_obj, 'read') else file_obj
            await asyncio.to_thread(local_path.write_bytes, content)

            elapsed = (time.perf_counter() - start) * 1000
            file_size = local_path.stat().st_size
            log.info(
                f"[WorkspaceBlobSync] Restored {blob_key} -> {local_path} "
                f"({file_size}B) in {elapsed:.0f}ms"
            )

            return SyncResult(
                local_path=str(local_path),
                blob_key=blob_key,
                success=True,
                bytes_uploaded=file_size,
                elapsed_ms=elapsed,
            )

        except Exception as e:
            elapsed = (time.perf_counter() - start) * 1000
            log.error(f"[WorkspaceBlobSync] Failed to restore {blob_key}: {e}")
            return SyncResult(
                local_path=str(local_path),
                blob_key=blob_key,
                success=False,
                error=str(e),
                elapsed_ms=elapsed,
            )

    async def restore_workspace(
        self,
        blob_prefix: str,
        restore_root: Path,
    ) -> WorkspaceSyncReport:
        """
        Restore all files under a blob prefix to a local directory.
        """
        start = time.perf_counter()
        report = WorkspaceSyncReport()

        if not self.storage_client:
            report.errors.append("No storage client configured")
            return report

        try:
            blob_keys = await asyncio.to_thread(
                self.storage_client.list_files, blob_prefix
            )
            report.total_files = len(blob_keys)

            for blob_key in blob_keys:
                relative = blob_key[len(blob_prefix):].lstrip("/")
                local_path = restore_root / relative

                result = await self.restore_file(blob_key, local_path)
                report.results.append(result)

                if result.success:
                    report.synced += 1
                else:
                    report.failed += 1
                    report.errors.append(f"{blob_key}: {result.error}")

        except Exception as e:
            report.errors.append(f"Restore failed: {e}")
            log.error(f"[WorkspaceBlobSync] Restore workspace failed: {e}")

        report.elapsed_ms = (time.perf_counter() - start) * 1000
        log.info(
            f"[WorkspaceBlobSync] Workspace restore: "
            f"{report.synced}/{report.total_files} restored, "
            f"{report.failed} failed in {report.elapsed_ms:.0f}ms"
        )
        return report

    # ================================================================== #
    #  Internal helpers
    # ================================================================== #

    def _collect_files(self, root: Path) -> List[Path]:
        """Walk root and collect all syncable files.

        The root path is resolved to an absolute canonical path before
        traversal to prevent path manipulation via symlinks or traversal.
        """
        # Security: reject path traversal sequences before resolution
        _root_str = str(root)
        if ".." in _root_str:
            log.warning(f"[WorkspaceBlobSync] _collect_files: rejecting path with traversal: {_root_str}")
            return []
        # Sanitize: resolve to canonical path
        root = Path(os.path.realpath(root))
        # Containment check: ensure resolved root is under workspace_root
        if hasattr(self, 'workspace_root') and self.workspace_root:
            if not str(root).startswith(str(self.workspace_root)):
                log.warning(f"[WorkspaceBlobSync] _collect_files: path escapes workspace: {root}")
                return []
        if not root.is_dir():
            log.warning(f"[WorkspaceBlobSync] _collect_files: root is not a directory: {root}")
            return []
        files = []
        try:
            for dirpath, dirnames, filenames in os.walk(root):
                dirnames[:] = [
                    d for d in dirnames if d not in SYNC_EXCLUDE_DIRS
                ]
                for fname in filenames:
                    fpath = Path(dirpath) / fname
                    if fpath.suffix.lower() in SYNC_EXCLUDE_EXTENSIONS:
                        continue
                    try:
                        if fpath.stat().st_size > MAX_FILE_SIZE_BYTES:
                            continue
                    except OSError:
                        continue
                    files.append(fpath)
        except Exception as e:
            log.warning(f"[WorkspaceBlobSync] Error collecting files from {root}: {e}")
        return sorted(files)

    @staticmethod
    def _on_task_done(task: asyncio.Task):
        """Callback for background tasks - log errors, never raise."""
        if task.cancelled():
            log.debug(f"[WorkspaceBlobSync] Task '{task.get_name()}' cancelled")
            return
        exc = task.exception()
        if exc is not None:
            log.error(
                f"[WorkspaceBlobSync] Task '{task.get_name()}' failed: {exc}",
                exc_info=(type(exc), exc, exc.__traceback__),
            )
