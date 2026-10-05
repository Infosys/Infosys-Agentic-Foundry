"""
Tests for src/inference/pre_inference_restore.py

Validates the parallel pre-inference asset restoration logic.
"""

import asyncio
import os
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch
import pytest

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.inference.pre_inference_restore import (
    ensure_inference_assets_available,
    _restore_file_context_prompt,
    _restore_database_assets,
    _restore_user_uploads,
    _restore_skills_folder,
)


# ================================================================== #
#  Test: ensure_inference_assets_available skips when no STORAGE_PROVIDER
# ================================================================== #


@pytest.mark.asyncio
async def test_skips_when_no_storage_provider():
    """Should return immediately with empty results if STORAGE_PROVIDER is unset."""
    with patch.dict(os.environ, {"STORAGE_PROVIDER": ""}, clear=False):
        result = await ensure_inference_assets_available(
            department="General",
            agent_id="test-agent-123",
            agent_name="Test Agent",
            db_connection_names=["my_db"],
            file_context_management_flag=True,
            uploaded_files=["report.pdf"],
            is_skill_agent=True,
            skills_dir=Path("/fake/skills"),
        )

    assert result["restored"] == []
    assert result["skipped"] == []
    assert result["failed"] == []
    assert result["elapsed_ms"] == 0.0


# ================================================================== #
#  Test: ensure_inference_assets_available with STORAGE_PROVIDER set
# ================================================================== #


@pytest.mark.asyncio
async def test_runs_parallel_tasks_when_storage_provider_set(tmp_path):
    """Should run multiple restore tasks in parallel when STORAGE_PROVIDER is set."""
    with patch.dict(os.environ, {"STORAGE_PROVIDER": "azure"}, clear=False):
        # Mock all internal restore functions
        with patch(
            "src.inference.pre_inference_restore._restore_file_context_prompt",
            new_callable=AsyncMock,
            return_value={"restored": ["file_context_prompt:Test Agent"], "skipped": [], "failed": []},
        ) as mock_fcp, patch(
            "src.inference.pre_inference_restore._restore_database_assets",
            new_callable=AsyncMock,
            return_value={"restored": ["schema:my_db (2 files)"], "skipped": [], "failed": []},
        ) as mock_db, patch(
            "src.inference.pre_inference_restore._restore_user_uploads",
            new_callable=AsyncMock,
            return_value={"restored": ["upload:report.pdf"], "skipped": [], "failed": []},
        ) as mock_uploads, patch(
            "src.inference.pre_inference_restore._restore_skills_folder",
            new_callable=AsyncMock,
            return_value={"restored": ["skills:agent-123 (3 files)"], "skipped": [], "failed": []},
        ) as mock_skills:
            skills_dir = tmp_path / "skills"
            result = await ensure_inference_assets_available(
                department="General",
                agent_id="agent-123",
                agent_name="Test Agent",
                db_connection_names=["my_db"],
                file_context_management_flag=True,
                uploaded_files=["report.pdf"],
                is_skill_agent=True,
                skills_dir=skills_dir,
            )

    # All tasks should have been called
    mock_fcp.assert_called_once()
    mock_db.assert_called_once()
    mock_uploads.assert_called_once()
    mock_skills.assert_called_once()

    # Results should be aggregated
    assert "file_context_prompt:Test Agent" in result["restored"]
    assert "schema:my_db (2 files)" in result["restored"]
    assert "upload:report.pdf" in result["restored"]
    assert "skills:agent-123 (3 files)" in result["restored"]
    assert result["elapsed_ms"] > 0


# ================================================================== #
#  Test: No tasks created when no flags/assets are needed
# ================================================================== #


@pytest.mark.asyncio
async def test_no_tasks_when_nothing_needed():
    """Should return quickly with no tasks if no assets are needed."""
    with patch.dict(os.environ, {"STORAGE_PROVIDER": "azure"}, clear=False):
        result = await ensure_inference_assets_available(
            department="General",
            agent_id="test-agent-123",
            agent_name="",
            db_connection_names=None,
            file_context_management_flag=False,
            uploaded_files=None,
            is_skill_agent=False,
        )

    assert result["restored"] == []
    assert result["skipped"] == []
    assert result["failed"] == []


# ================================================================== #
#  Test: _restore_file_context_prompt skips when file exists
# ================================================================== #


@pytest.mark.asyncio
async def test_file_context_prompt_skips_when_exists(tmp_path, monkeypatch):
    """Should skip restoration if the prompt file already exists."""
    # Create the expected file structure under tmp_path as workspace root
    workspace = tmp_path / "agent_workspaces" / "General" / "file_context_prompts"
    workspace.mkdir(parents=True)
    prompt_file = workspace / "Test Agent_file_context_prompt.md"
    prompt_file.write_text("existing content")

    # Change cwd so os.path.abspath("./agent_workspaces") resolves under tmp_path
    monkeypatch.chdir(tmp_path)

    with patch.dict(os.environ, {"STORAGE_PROVIDER": "azure"}, clear=False):
        result = await _restore_file_context_prompt(
            storage_provider="azure",
            department="General",
            agent_name="Test Agent",
        )

    assert len(result["skipped"]) == 1
    assert "file_context_prompt:Test Agent" in result["skipped"][0]
    assert result["restored"] == []


# ================================================================== #
#  Test: _restore_file_context_prompt restores from blob
# ================================================================== #


@pytest.mark.asyncio
async def test_file_context_prompt_restores_from_blob(tmp_path, monkeypatch):
    """Should restore from blob when file is missing locally."""
    # Workspace dir exists but prompt file does NOT
    workspace = tmp_path / "agent_workspaces" / "General" / "file_context_prompts"
    workspace.mkdir(parents=True)

    monkeypatch.chdir(tmp_path)

    mock_result = MagicMock()
    mock_result.success = True

    mock_syncer = MagicMock()
    mock_syncer.restore_file = AsyncMock(return_value=mock_result)

    with patch.dict(os.environ, {"STORAGE_PROVIDER": "azure"}, clear=False), \
         patch("src.storage.get_storage_client") as mock_get_client, \
         patch("src.utils.workspace_blob_sync.WorkspaceBlobSync", return_value=mock_syncer):
        mock_get_client.return_value = MagicMock()
        result = await _restore_file_context_prompt(
            storage_provider="azure",
            department="General",
            agent_name="Test Agent",
        )

    assert "file_context_prompt:Test Agent" in result["restored"]
    assert result["failed"] == []


# ================================================================== #
#  Test: _restore_skills_folder skips when dir has contents
# ================================================================== #


@pytest.mark.asyncio
async def test_skills_folder_skips_when_populated(tmp_path):
    """Should skip if skills_dir already has files."""
    skills_dir = tmp_path / "skills"
    skills_dir.mkdir()
    (skills_dir / "skill_1.md").write_text("# Skill 1")

    with patch.dict(os.environ, {"STORAGE_PROVIDER": "azure"}, clear=False):
        result = await _restore_skills_folder(
            storage_provider="azure",
            department="General",
            agent_id="agent-123",
            skills_dir=skills_dir,
        )

    assert "skills:agent-123" in result["skipped"]
    assert result["restored"] == []


# ================================================================== #
#  Test: _restore_skills_folder restores from blob
# ================================================================== #


@pytest.mark.asyncio
async def test_skills_folder_restores_from_blob(tmp_path):
    """Should restore skills from blob when dir is empty."""
    skills_dir = tmp_path / "skills"
    # Don't create it — it should be missing

    mock_report = MagicMock()
    mock_report.synced = 5

    mock_syncer = MagicMock()
    mock_syncer.blob_prefix = ""
    mock_syncer.restore_workspace = AsyncMock(return_value=mock_report)

    with patch.dict(os.environ, {"STORAGE_PROVIDER": "azure"}, clear=False), \
         patch("src.storage.get_storage_client") as mock_gc, \
         patch("src.utils.workspace_blob_sync.WorkspaceBlobSync", return_value=mock_syncer):
        mock_gc.return_value = MagicMock()
        result = await _restore_skills_folder(
            storage_provider="azure",
            department="General",
            agent_id="agent-123",
            skills_dir=skills_dir,
        )

    assert any("skills:agent-123" in r for r in result["restored"])
    assert result["failed"] == []
    mock_syncer.restore_workspace.assert_called_once()


# ================================================================== #
#  Test: _restore_user_uploads skips existing files
# ================================================================== #


@pytest.mark.asyncio
async def test_user_uploads_skips_existing(tmp_path, monkeypatch):
    """Should skip files that already exist locally."""
    # Create the file locally
    upload_dir = tmp_path / "user_uploads" / "General"
    upload_dir.mkdir(parents=True)
    (upload_dir / "report.pdf").write_bytes(b"fake pdf")

    monkeypatch.chdir(tmp_path)

    with patch.dict(os.environ, {"STORAGE_PROVIDER": "azure"}, clear=False), \
         patch("src.storage.get_storage_client") as mock_gc:
        mock_gc.return_value = MagicMock()
        result = await _restore_user_uploads(
            storage_provider="azure",
            uploaded_files=["General/report.pdf"],
        )

    assert "upload:General/report.pdf" in result["skipped"]
    assert result["restored"] == []


# ================================================================== #
#  Test: Exception handling - one task failure doesn't break others
# ================================================================== #


@pytest.mark.asyncio
async def test_exception_in_one_task_doesnt_break_others():
    """If one restore task raises, others should still complete."""
    with patch.dict(os.environ, {"STORAGE_PROVIDER": "azure"}, clear=False):
        with patch(
            "src.inference.pre_inference_restore._restore_file_context_prompt",
            new_callable=AsyncMock,
            side_effect=RuntimeError("Blob connection failed"),
        ), patch(
            "src.inference.pre_inference_restore._restore_database_assets",
            new_callable=AsyncMock,
            return_value={"restored": ["schema:ok_db (1 files)"], "skipped": [], "failed": []},
        ):
            result = await ensure_inference_assets_available(
                department="General",
                agent_id="agent-123",
                agent_name="Agent",
                db_connection_names=["ok_db"],
                file_context_management_flag=True,
                uploaded_files=None,
                is_skill_agent=False,
            )

    # file_context_prompt failure should be reported
    assert any("file_context_prompt" in f for f in result["failed"])
    # database task should still succeed
    assert "schema:ok_db (1 files)" in result["restored"]


# ================================================================== #
#  Test: _restore_database_assets with schema files existing
# ================================================================== #


@pytest.mark.asyncio
async def test_database_assets_skips_when_schema_exists(tmp_path, monkeypatch):
    """Should skip restore if schema.md already exists."""
    # Create schema file at expected location
    db_dir = tmp_path / "agent_workspaces" / "General" / "databases" / "my_connection"
    db_dir.mkdir(parents=True)
    (db_dir / "schema.md").write_text("# Schema")

    # Change cwd so os.path.abspath("./agent_workspaces") resolves under tmp_path
    monkeypatch.chdir(tmp_path)

    mock_syncer = MagicMock()
    mock_syncer.restore_database_cache = AsyncMock()

    with patch.dict(os.environ, {"STORAGE_PROVIDER": "azure"}, clear=False), \
         patch("src.storage.get_storage_client") as mock_gc, \
         patch("src.utils.workspace_blob_sync.WorkspaceBlobSync", return_value=mock_syncer):
        mock_gc.return_value = MagicMock()
        result = await _restore_database_assets(
            storage_provider="azure",
            department="General",
            db_connection_names=["my_connection"],
        )

    # Schema was already present, so it should be skipped
    assert any("schema:my_connection" in s for s in result["skipped"])
    assert not any("schema:my_connection" in r for r in result["restored"])


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
