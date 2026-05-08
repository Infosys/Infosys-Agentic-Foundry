# © 2024-25 Infosys Limited, Bangalore, India. All Rights Reserved.
"""
Service for exporting and importing tools and MCP servers as .zip files.
"""

import ast
import hashlib
import io
import json
import os
import re
import uuid
import zipfile
from datetime import datetime, timezone
from typing import Any, Dict, List, Literal, Optional, Set

from telemetry_wrapper import logger as log, update_session_context

from src.database.services import ToolService, McpToolService, ModelService, TagService
from src.tools.tool_code_processor import ToolCodeProcessor, safe_to_source
from src.tools.tool_validation import graph


class ToolExportImportService:
    """
    Handles export/import of tools (Python function tools) as .zip files.
    """

    def __init__(self, tool_service: ToolService, mcp_tool_service: McpToolService, model_service: ModelService, tag_service: TagService):
        self.tool_service = tool_service
        self.mcp_tool_service = mcp_tool_service
        self.model_service = model_service
        self.tag_service = tag_service
        self.tool_code_processor = ToolCodeProcessor()

    # ─────────────────────────────────────────────
    # TOOL EXPORT
    # ─────────────────────────────────────────────

    async def export_tools(self, tool_ids: List[str]) -> Dict[str, Any]:
        """
        Export a list of tools by their IDs into a zip buffer.

        Each tool is exported with:
        - Main code file: {tool_name}.py (latest/main code)
        - Version files: {tool_name}_v1.py, {tool_name}_v2.py, etc.
        - Metadata JSON: {tool_name}_metadata.json (tool info + versions list)

        Args:
            tool_ids: List of tool IDs to export.

        Returns:
            dict with 'zip_buffer' (BytesIO), 'exported' count, 'failed' list, 'file_count'.
        """
        zip_buffer = io.BytesIO()
        exported = []
        failed = []

        with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zf:
            for tool_id in tool_ids:
                try:
                    tool_records = await self.tool_service.get_tool(tool_id=tool_id)
                    if not tool_records:
                        failed.append({"tool_id": tool_id, "reason": "Tool not found"})
                        continue

                    tool = tool_records[0]
                    tool_name = tool.get("tool_name", "unknown_tool")
                    code_snippet = tool.get("code_snippet", "")

                    if not code_snippet:
                        failed.append({"tool_id": tool_id, "tool_name": tool_name, "reason": "Empty code snippet"})
                        continue

                    # Write main code file
                    filename = f"{tool_name}.py"
                    zf.writestr(filename, code_snippet)
                    
                    # Export all versions from tool_versions_table
                    versions_exported = []
                    if hasattr(self.tool_service, 'tool_version_repo') and self.tool_service.tool_version_repo:
                        versions = await self.tool_service.tool_version_repo.get_all_versions(tool_id)
                        if versions:
                            for ver in versions:
                                ver_code = ver.get("code_snippet", "")
                                ver_name = ver.get("version", "v1")
                                if ver_code:
                                    ver_filename = f"{tool_name}_{ver_name}.py"
                                    zf.writestr(ver_filename, ver_code)
                                    versions_exported.append({
                                        "version": ver_name,
                                        "filename": ver_filename,
                                        "tool_description": ver.get("tool_description", ""),
                                        "model_name": ver.get("model_name", ""),
                                        "updated_by": ver.get("updated_by", ""),
                                    })
                    
                    # Write metadata JSON with tool info and versions
                    metadata = {
                        "tool_id": tool_id,
                        "tool_name": tool_name,
                        "tool_description": tool.get("tool_description", ""),
                        "model_name": tool.get("model_name", ""),
                        "created_by": tool.get("created_by", ""),
                        "main_code_file": filename,
                        "versions": versions_exported,
                    }
                    metadata_filename = f"{tool_name}_metadata.json"
                    zf.writestr(metadata_filename, json.dumps(metadata, indent=2))
                    
                    exported.append({
                        "tool_id": tool_id,
                        "tool_name": tool_name,
                        "filename": filename,
                        "versions_exported": len(versions_exported),
                    })

                except Exception as e:
                    log.error(f"Error exporting tool {tool_id}: {e}")
                    failed.append({"tool_id": tool_id, "reason": str(e)})

        zip_buffer.seek(0)
        return {
            "zip_buffer": zip_buffer,
            "exported": exported,
            "failed": failed,
            "file_count": len(exported),
        }

    # ─────────────────────────────────────────────
    # TOOL IMPORT PREVIEW
    # ─────────────────────────────────────────────

    async def preview_import_tools(
        self,
        zip_buffer: io.BytesIO,
        department_name: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Preview what will happen when importing tools from a .zip file.
        
        This method analyzes the zip contents and checks for conflicts WITHOUT
        actually importing anything. UI can use this to show a modal only when
        conflicts require user decision.

        Args:
            zip_buffer: BytesIO of the uploaded zip file.
            department_name: The department of the importing user (for department-scoped uniqueness).

        Returns:
            dict with:
            - has_conflicts: bool - True if any tool requires user decision
            - tools: List of tool analysis results with status and options
        """
        # Extract all files including metadata
        extracted = self._extract_all_files_from_zip(zip_buffer)
        py_files = extracted.get("py_files", {})
        metadata_files = extracted.get("metadata_files", {})

        if not py_files:
            return {
                "has_conflicts": False,
                "tools": [],
                "message": "No .py files found in the uploaded zip.",
            }

        tools_analysis = []
        has_conflicts = False
        
        # Identify which .py files are version files (should be skipped as main tool imports)
        versioned_code_files = set()
        for tool_name, metadata in metadata_files.items():
            for ver_info in metadata.get("versions", []):
                ver_filename = ver_info.get("filename", "")
                if ver_filename:
                    versioned_code_files.add(ver_filename)

        for filename, code_snippet in py_files.items():
            # Skip versioned code files
            if filename in versioned_code_files:
                continue
            
            # Extract tool name from filename
            tool_name = filename.replace(".py", "")
            
            # Check if tool exists in active tools
            existing_records = await self.tool_service.tool_repo.get_tool_record(
                tool_name=tool_name, department_name=department_name, include_public=False
            )
            
            # Check recycle bin
            in_recycle = await self.tool_service.recycle_tool_repo.is_tool_in_recycle_bin_record(tool_name=tool_name)
            
            if not existing_records and not in_recycle:
                # Tool doesn't exist anywhere - will import directly
                tools_analysis.append({
                    "filename": filename,
                    "tool_name": tool_name,
                    "status": "ready_to_import",
                    "message": "New tool - will be imported directly",
                    "requires_decision": False,
                })
            elif in_recycle:
                # Tool exists in recycle bin - user must provide a new name
                has_conflicts = True
                tools_analysis.append({
                    "filename": filename,
                    "tool_name": tool_name,
                    "status": "conflict",
                    "message": f"Tool '{tool_name}' exists in recycle bin. Please provide a new name for this tool.",
                    "requires_decision": True,
                    "needs_new_name": True,
                    "in_recycle_bin": True,
                    "options": [
                        {
                            "value": "create_new_tool",
                            "label": "Create as new tool",
                            "description": "Provide a new name for this tool (names ending with _v1, _v2, etc. are reserved)",
                            "requires_name_input": True,
                        },
                        {
                            "value": "skip",
                            "label": "Skip this tool",
                            "description": "Do not import this tool"
                        }
                    ],
                })
            else:
                # Tool exists in active tools - check if code is same or different
                existing_code = existing_records[0].get("code_snippet", "")
                existing_tool_id = existing_records[0].get("tool_id", "")
                
                incoming_hash = self._hash_code(code_snippet)
                existing_hash = self._hash_code(existing_code)
                
                if incoming_hash == existing_hash:
                    # Same code - will skip
                    tools_analysis.append({
                        "filename": filename,
                        "tool_name": tool_name,
                        "status": "skip",
                        "message": f"Tool '{tool_name}' already exists with identical code. Will be skipped.",
                        "existing_tool_id": existing_tool_id,
                        "requires_decision": False,
                    })
                else:
                    # Different code - CONFLICT! User must decide
                    has_conflicts = True
                    
                    # Get next version number if user chooses "create_new_version"
                    next_version = "v1"
                    if hasattr(self.tool_service, 'tool_version_repo') and self.tool_service.tool_version_repo:
                        next_version = await self.tool_service.tool_version_repo.get_next_version_number(existing_tool_id)
                    
                    tools_analysis.append({
                        "filename": filename,
                        "tool_name": tool_name,
                        "status": "conflict",
                        "message": f"Tool '{tool_name}' already exists with different code. Choose an action.",
                        "existing_tool_id": existing_tool_id,
                        "requires_decision": True,
                        "options": [
                            {
                                "value": "create_new_tool",
                                "label": "Create as new tool",
                                "description": "Provide a new name for this tool (names ending with _v1, _v2, etc. are reserved)",
                                "requires_name_input": True,
                            },
                            {
                                "value": "create_new_version", 
                                "label": f"Add as new version ({next_version})",
                                "description": f"Add this code as version '{next_version}' to existing tool"
                            },
                            {
                                "value": "skip",
                                "label": "Skip this tool",
                                "description": "Do not import this tool"
                            }
                        ],
                        "suggested_new_version": next_version,
                    })

        return {
            "has_conflicts": has_conflicts,
            "tools": tools_analysis,
            "total": len(tools_analysis),
            "conflicts_count": sum(1 for t in tools_analysis if t.get("requires_decision")),
            "ready_count": sum(1 for t in tools_analysis if t.get("status") == "ready_to_import"),
            "skip_count": sum(1 for t in tools_analysis if t.get("status") == "skip"),
        }

    # ─────────────────────────────────────────────
    # NAME VALIDATION (Before Import)
    # ─────────────────────────────────────────────

    async def _validate_single_name(
        self,
        original_name: str,
        new_name: str,
        department_name: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Validate a single tool name before import.
        
        Checks:
        1. Name is not empty
        2. Name doesn't end with _v1, _v2, etc. (reserved for versions)
        3. Name doesn't already exist in active tools
        4. Name doesn't exist in recycle bin
        
        Returns:
            Dict with 'valid', 'reason', and other details
        """
        # Check 1: Empty name
        if not new_name or not new_name.strip():
            return {
                "original_name": original_name,
                "new_name": new_name,
                "valid": False,
                "reason": "Tool name cannot be empty",
            }
        
        new_name = new_name.strip()
        
        # Check 2: Reserved pattern (_v1, _v2, etc.)
        if re.search(r'_v\d+$', new_name, re.IGNORECASE):
            return {
                "original_name": original_name,
                "new_name": new_name,
                "valid": False,
                "reason": f"Names ending with _v1, _v2, etc. are reserved for version files. Please choose a different name.",
            }
        
        # Check 3: Already exists in active tools
        existing_records = await self.tool_service.tool_repo.get_tool_record(
            tool_name=new_name, department_name=department_name, include_public=False
        )
        if existing_records:
            return {
                "original_name": original_name,
                "new_name": new_name,
                "valid": False,
                "reason": f"Tool '{new_name}' already exists in your department. Please choose a different name.",
            }
        
        # Check 4: Exists in recycle bin
        in_recycle = await self.tool_service.recycle_tool_repo.is_tool_in_recycle_bin_record(tool_name=new_name)
        if in_recycle:
            return {
                "original_name": original_name,
                "new_name": new_name,
                "valid": False,
                "reason": f"Tool '{new_name}' exists in recycle bin. Restore it first or choose a different name.",
            }
        
        # All checks passed
        return {
            "original_name": original_name,
            "new_name": new_name,
            "valid": True,
            "reason": None,
        }

    async def _validate_all_import_names(
        self,
        name_overrides: Dict[str, str],
        department_name: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Validate all names in name_overrides before importing.
        
        This is called at the start of import to ensure all user-provided names are valid
        BEFORE any database changes are made.
        
        Args:
            name_overrides: Dict mapping original function names to user-provided new names
            department_name: The department for uniqueness checking
            
        Returns:
            Dict with 'all_valid', 'validation_errors', etc.
        """
        if not name_overrides:
            return {"all_valid": True, "validation_errors": {}}
        
        validation_errors = {}
        invalid_count = 0
        
        for original_name, new_name in name_overrides.items():
            result = await self._validate_single_name(original_name, new_name, department_name)
            validation_errors[original_name] = result
            if not result.get("valid"):
                invalid_count += 1
        
        all_valid = invalid_count == 0
        
        return {
            "all_valid": all_valid,
            "validation_errors": validation_errors,
            "invalid_count": invalid_count,
            "total_count": len(name_overrides),
        }

    # ─────────────────────────────────────────────
    # TOOL IMPORT
    # ─────────────────────────────────────────────

    async def import_tools(
        self,
        zip_buffer: io.BytesIO,
        model_name: str,
        created_by: str,
        department_name: Optional[str] = None,
        conflict_resolution: Literal["create_new_tool", "create_new_version"] = "create_new_tool",
        name_overrides: Optional[Dict[str, str]] = None,
    ) -> Dict[str, Any]:
        """
        Import tools from a .zip file. Each .py file is treated as one tool.

        Handles nested folder structures (zip may contain a folder with .py files).
        Validates all names in name_overrides BEFORE importing - if any name is invalid,
        returns validation_failed=true with errors, and no tools are imported.
        Generates docstring only if one is not already present.
        Uses force_add=True to bypass graph validation.
        Supports versioned imports when metadata JSON files are present.

        Args:
            zip_buffer: BytesIO of the uploaded zip file.
            model_name: LLM model name to use for docstring generation.
            created_by: Email of the importing user.
            department_name: The department of the importing user (for department-scoped uniqueness).
            conflict_resolution: How to handle main tool code conflicts:
                - "create_new_tool": Create a new tool with user-provided name (via name_overrides)
                - "create_new_version": Add the conflicting code as a new version of existing tool
            name_overrides: Optional dict mapping original function names to user-provided new names.
                           Used when a previous import attempt returned needs_new_name=True.

        Returns:
            dict with 'imported', 'failed', 'summary' lists.
            If validation_failed=True, contains validation_errors with per-name details.
        """
        # Extract all files including metadata
        extracted = self._extract_all_files_from_zip(zip_buffer)
        py_files = extracted.get("py_files", {})
        metadata_files = extracted.get("metadata_files", {})

        if not py_files:
            return {
                "message": "No .py files found in the uploaded zip.",
                "imported": [],
                "failed": [],
                "total": 0,
            }

        imported = []
        failed = []
        skipped = []
        versions_imported = []
        merged_to_existing = []  # Tools where versions were merged to existing tool
        
        # Identify which .py files are version files (like tool_name_v1.py, tool_name_v2.py)
        # These should be skipped as main tool imports since they're handled via metadata
        versioned_code_files = set()
        for tool_name, metadata in metadata_files.items():
            for ver_info in metadata.get("versions", []):
                ver_filename = ver_info.get("filename", "")
                if ver_filename:
                    versioned_code_files.add(ver_filename)

        # Initialize name_overrides if not provided
        name_overrides = name_overrides or {}
        
        # ─────────────────────────────────────────────
        # VALIDATE ALL NAMES BEFORE IMPORTING
        # ─────────────────────────────────────────────
        # If user provided name_overrides, validate ALL names first.
        # If any name is invalid, return immediately without importing anything.
        # This keeps modal open and shows errors so user can fix them.
        if name_overrides:
            validation_result = await self._validate_all_import_names(name_overrides, department_name)
            if not validation_result.get("all_valid"):
                invalid_count = validation_result.get("invalid_count", 0)
                total_count = validation_result.get("total_count", 0)
                return {
                    "status": "validation_failed",
                    "validation_failed": True,
                    "message": f"{invalid_count} of {total_count} names are invalid. Please fix and try again.",
                    "validation_errors": validation_result.get("validation_errors", {}),
                    "imported": [],
                    "merged_to_existing": [],
                    "skipped": [],
                    "failed": [],
                    "versions_imported": [],
                    "total": len(py_files) - len(versioned_code_files),
                    "has_pending_conflicts": False,
                    "pending_conflicts": [],
                }
        
        for filename, code_snippet in py_files.items():
            # Skip versioned code files - they're imported via metadata
            if filename in versioned_code_files:
                continue
            
            # Get user-provided custom name if available
            # First extract function name to lookup in overrides
            temp_validation = await self.tool_code_processor.validate_and_extract_tool_name(code_snippet)
            original_func_name = temp_validation.get("function_name", "") if temp_validation.get("is_valid") else ""
            custom_name = name_overrides.get(original_func_name)
                
            result = await self._import_single_tool(
                filename=filename,
                code_snippet=code_snippet,
                model_name=model_name,
                created_by=created_by,
                department_name=department_name,
                conflict_resolution=conflict_resolution,
                custom_name=custom_name,
            )
            
            if result.get("is_created"):
                imported.append(result)
                
                # Import versions if metadata exists for this tool
                # Use original_name for metadata lookup (in case tool was renamed)
                tool_name = result.get("tool_name", "")
                original_name = result.get("original_name", tool_name)
                tool_id = result.get("tool_id", "")
                
                if tool_id and original_name in metadata_files:
                    # Metadata exists - import versions from metadata as-is
                    # (preserves original version numbers like v3, v9, etc.)
                    metadata = metadata_files[original_name]
                    ver_results = await self._import_tool_versions(
                        tool_id=tool_id,
                        tool_name=tool_name,
                        metadata=metadata,
                        py_files=py_files,
                        created_by=created_by,
                        original_name=original_name,  # Pass original name for function renaming
                    )
                    versions_imported.extend(ver_results)
                    
                    # If metadata exists but no versions were successfully imported,
                    # create default v1 (same as no-metadata case)
                    successful_imports = [v for v in ver_results if v.get("success")]
                    if not successful_imports:
                        version_created = await self._create_default_version(
                            tool_id=tool_id,
                            code_snippet=result.get("code_snippet", code_snippet),
                            tool_description=result.get("tool_description", ""),
                            model_name=model_name,
                            created_by=created_by,
                        )
                        if version_created:
                            versions_imported.append({
                                "tool_id": tool_id,
                                "tool_name": tool_name,
                                "version": "v1",
                                "success": True,
                                "message": "Default v1 created (metadata had no importable versions)"
                            })
                    
                    # Update main tool's description with metadata description (if available)
                    # This ensures "All Versions" tab shows the correct description
                    metadata_description = metadata.get("tool_description", "")
                    if metadata_description and hasattr(self.tool_service, 'tool_repo'):
                        try:
                            await self.tool_service.tool_repo.update_tool_record(
                                {"tool_description": metadata_description},
                                tool_id
                            )
                            log.info(f"Updated main tool description from metadata for '{tool_name}'")
                        except Exception as e:
                            log.warning(f"Failed to update main tool description from metadata: {e}")
                elif tool_id:
                    # No metadata file - create default v1 in tool_versions_table
                    # Same behavior as new tool creation in our system
                    version_created = await self._create_default_version(
                        tool_id=tool_id,
                        code_snippet=result.get("code_snippet", code_snippet),
                        tool_description=result.get("tool_description", ""),
                        model_name=model_name,
                        created_by=created_by,
                    )
                    if version_created:
                        versions_imported.append({
                            "tool_id": tool_id,
                            "tool_name": tool_name,
                            "version": "v1",
                            "success": True,
                            "message": "Default v1 created (no version data in ZIP)"
                        })
            
            elif result.get("merged_to_existing"):
                # Tool existed, main code added as new version, now import other versions
                merged_to_existing.append(result)
                tool_name = result.get("tool_name", "")
                tool_id = result.get("existing_tool_id", "")
                
                if tool_name and tool_id and tool_name in metadata_files:
                    ver_results = await self._import_tool_versions(
                        tool_id=tool_id,
                        tool_name=tool_name,
                        metadata=metadata_files[tool_name],
                        py_files=py_files,
                        created_by=created_by,
                    )
                    versions_imported.extend(ver_results)
            
            elif result.get("main_same_check_versions"):
                # Main tool code is same, check and import versions
                tool_name = result.get("tool_name", "")
                tool_id = result.get("existing_tool_id", "")
                
                if tool_name and tool_id and tool_name in metadata_files:
                    ver_results = await self._import_tool_versions(
                        tool_id=tool_id,
                        tool_name=tool_name,
                        metadata=metadata_files[tool_name],
                        py_files=py_files,
                        created_by=created_by,
                    )
                    if ver_results:
                        versions_imported.extend(ver_results)
                        skipped.append({
                            **result,
                            "message": f"Tool '{tool_name}' exists with same code. Imported {len([v for v in ver_results if v.get('success')])} new versions.",
                        })
                    else:
                        skipped.append(result)
                else:
                    skipped.append(result)
                    
            elif result.get("skipped"):
                skipped.append(result)
            else:
                failed.append(result)

        total_versions_success = len([v for v in versions_imported if v.get("success")])
        
        # Build detailed summary message with tool names
        summary_parts = []
        
        if imported:
            # Separate renamed vs original name imports
            renamed_imports = [r for r in imported if r.get("renamed_to")]
            original_imports = [r for r in imported if not r.get("renamed_to")]
            
            if original_imports:
                original_names = [r.get("tool_name", "unknown") for r in original_imports]
                summary_parts.append(f"{len(original_imports)} imported ({', '.join(original_names)})")
            
            if renamed_imports:
                renamed_details = [f"{r.get('original_name', 'unknown')} → {r.get('renamed_to', r.get('tool_name', 'unknown'))}" for r in renamed_imports]
                summary_parts.append(f"{len(renamed_imports)} imported with new name ({', '.join(renamed_details)})")
        
        if merged_to_existing:
            merged_details = [f"{r.get('tool_name', 'unknown')} as {r.get('new_version', 'new version')}" for r in merged_to_existing]
            summary_parts.append(f"{len(merged_to_existing)} merged as new versions ({', '.join(merged_details)})")
        
        if skipped:
            # Include reason for each skipped tool
            skipped_details = []
            for r in skipped:
                name = r.get("tool_name", "unknown")
                reason = r.get("message", "")
                # Extract short reason from message
                if "same code" in reason.lower() or "identical" in reason.lower():
                    skipped_details.append(f"{name}: same code already exists")
                elif "already exists" in reason.lower():
                    skipped_details.append(f"{name}: name already exists")
                else:
                    skipped_details.append(name)
            summary_parts.append(f"{len(skipped)} skipped ({', '.join(skipped_details)})")
        
        if failed:
            # Separate needs_new_name vs actual failures
            needs_name = [r for r in failed if r.get("needs_new_name")]
            actual_failures = [r for r in failed if not r.get("needs_new_name")]
            
            if needs_name:
                needs_name_tools = [r.get("tool_name", "unknown") for r in needs_name]
                summary_parts.append(f"{len(needs_name)} need new name ({', '.join(needs_name_tools)})")
            
            if actual_failures:
                failed_details = []
                for r in actual_failures:
                    name = r.get("tool_name", r.get("filename", "unknown"))
                    reason = r.get("message", "unknown error")
                    short_reason = reason[:40] + "..." if len(reason) > 40 else reason
                    failed_details.append(f"{name}: {short_reason}")
                summary_parts.append(f"{len(actual_failures)} failed ({', '.join(failed_details)})")
        
        if total_versions_success:
            # Show which tools had versions imported
            successful_versions = [v for v in versions_imported if v.get("success")]
            version_details = [f"{v.get('tool_name', 'unknown')} {v.get('version', '')}" for v in successful_versions]
            summary_parts.append(f"{total_versions_success} versions created ({', '.join(version_details)})")
        
        detailed_message = "Import complete. " + ("; ".join(summary_parts) if summary_parts else "No tools processed.")
        
        # Check if there are still tools that need new names (user provided invalid names)
        needs_name = [r for r in failed if r.get("needs_new_name")]
        has_pending_conflicts = len(needs_name) > 0
        
        return {
            "status": "success",
            "validation_failed": False,
            "message": detailed_message,
            "imported": imported,
            "merged_to_existing": merged_to_existing,
            "skipped": skipped,
            "failed": failed,
            "versions_imported": versions_imported,
            "total": len(py_files) - len(versioned_code_files),
            "has_pending_conflicts": has_pending_conflicts,
            "pending_conflicts": needs_name if has_pending_conflicts else [],
        }

    async def _create_default_version(
        self,
        tool_id: str,
        code_snippet: str,
        tool_description: str,
        model_name: str,
        created_by: str,
    ) -> bool:
        """
        Create default v1 entry in tool_versions_table for a newly imported tool.
        
        Returns:
            bool: True if version was created successfully, False otherwise.
        """
        if not hasattr(self.tool_service, 'tool_version_repo') or not self.tool_service.tool_version_repo:
            log.warning(f"tool_version_repo not available, skipping default v1 creation for tool {tool_id}")
            return False
        
        try:
            version_id = await self.tool_service.tool_version_repo.create_version(
                tool_id=tool_id,
                version="v1",
                code_snippet=code_snippet,
                tool_description=tool_description,
                model_name=model_name,
                updated_by=created_by,
            )
            if version_id:
                log.info(f"Created default v1 for imported tool {tool_id}")
                return True
            else:
                log.warning(f"Failed to create default v1 for tool {tool_id} - no version_id returned")
                return False
        except Exception as e:
            log.error(f"Failed to create default v1 for tool {tool_id}: {e}")
            return False

    async def _import_tool_versions(
        self,
        tool_id: str,
        tool_name: str,
        metadata: Dict[str, Any],
        py_files: Dict[str, str],
        created_by: str,
        original_name: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """
        Import tool versions from metadata into tool_versions_table.
        Uses O(m+n) hashing algorithm for efficient duplicate detection.
        
        Algorithm:
        1. Build hash set from existing DB versions - O(m)
        2. Check each imported version against hash set - O(n)
        3. Import only versions with unique code (not already in any existing version)
        
        Args:
            tool_id: The ID of the imported/existing tool
            tool_name: The name of the tool (may be renamed, e.g., 'hello_copy1')
            metadata: Metadata dict containing versions info
            py_files: Dict of all .py files extracted from zip
            created_by: User who is importing
            original_name: Original function name in ZIP (e.g., 'hello'). If different from tool_name,
                          functions in version code will be renamed.
            
        Returns:
            List of import results for each version
        """
        results = []
        
        # Determine if function renaming is needed
        needs_rename = original_name and original_name != tool_name
        
        if not hasattr(self.tool_service, 'tool_version_repo') or not self.tool_service.tool_version_repo:
            log.warning("Tool version repository not available, skipping versions import")
            return results
        
        versions = metadata.get("versions", [])
        if not versions:
            return results
        
        # Step 1: Build hash set from existing DB versions - O(m)
        existing_versions = await self.tool_service.tool_version_repo.get_all_versions(tool_id)
        existing_code_hashes: Set[str] = set()
        
        for ver in existing_versions:
            ver_code = ver.get("code_snippet", "")
            if ver_code:
                code_hash = self._hash_code(ver_code)
                existing_code_hashes.add(code_hash)
        
        log.info(f"Built hash set with {len(existing_code_hashes)} existing version hashes for tool '{tool_name}'")
        
        # Step 2: Check each imported version against hash set - O(n)
        for ver_info in versions:
            version = ver_info.get("version", "")
            ver_filename = ver_info.get("filename", "")
            
            if not version:
                continue
            
            # Get code from the version file
            code_snippet = py_files.get(ver_filename, "")
            if not code_snippet:
                results.append({
                    "tool_id": tool_id,
                    "tool_name": tool_name,
                    "version": version,
                    "message": f"Version file '{ver_filename}' not found in zip",
                    "success": False,
                })
                continue
            
            # Rename function in version code if tool was renamed (e.g., hello → hello_copy1)
            if needs_rename:
                renamed_code = self._rename_function_in_code(code_snippet, original_name, tool_name)
                if renamed_code:
                    code_snippet = renamed_code
                    log.info(f"Renamed function in version '{version}': '{original_name}' → '{tool_name}'")
                else:
                    log.warning(f"Could not rename function in version '{version}', using original code")
            
            # Hash the incoming code
            incoming_hash = self._hash_code(code_snippet)
            
            # O(1) lookup - check if code already exists in any version
            if incoming_hash in existing_code_hashes:
                results.append({
                    "tool_id": tool_id,
                    "tool_name": tool_name,
                    "version": version,
                    "message": f"Version '{version}' skipped - identical code already exists in another version",
                    "success": False,
                    "skipped_duplicate": True,
                })
                continue
            
            # Code is unique - import with ORIGINAL version number (preserve v3, v9, etc.)
            try:
                # Check if this version number already exists
                existing_ver = await self.tool_service.tool_version_repo.get_version(tool_id, version)
                if existing_ver:
                    # Version number already taken, use next available
                    target_version = await self.tool_service.tool_version_repo.get_next_version_number(tool_id)
                    log.info(f"Version '{version}' already exists, using '{target_version}' instead")
                else:
                    # Use original version number
                    target_version = version
                
                version_id = await self.tool_service.tool_version_repo.create_version(
                    tool_id=tool_id,
                    version=target_version,
                    code_snippet=code_snippet,
                    tool_description=ver_info.get("tool_description", ""),
                    model_name=ver_info.get("model_name", ""),
                    updated_by=ver_info.get("updated_by", created_by),
                )
                
                if version_id:
                    # Add to hash set to prevent duplicate imports within same batch
                    existing_code_hashes.add(incoming_hash)
                    
                    # Create version .py file
                    file_created = False
                    if hasattr(self.tool_service, 'tool_file_manager') and self.tool_service.tool_file_manager:
                        try:
                            version_tool_data = {
                                "tool_name": tool_name,
                                "code_snippet": code_snippet,
                            }
                            file_result = await self.tool_service.tool_file_manager.create_tool_file(version_tool_data, version=target_version)
                            file_created = file_result.get("success", False)
                            if file_created:
                                log.info(f"Created version file '{target_version}' for tool '{tool_name}'")
                        except Exception as e:
                            log.warning(f"Error creating version file '{target_version}' for tool '{tool_name}': {e}")
                    
                    # Report if version was remapped
                    if target_version != version:
                        results.append({
                            "tool_id": tool_id,
                            "tool_name": tool_name,
                            "original_version": version,
                            "imported_as": target_version,
                            "message": f"Version '{version}' imported as '{target_version}' (original version number was taken)",
                            "success": True,
                            "file_created": file_created,
                        })
                    else:
                        results.append({
                            "tool_id": tool_id,
                            "tool_name": tool_name,
                            "version": version,
                            "message": f"Version '{version}' imported successfully",
                            "success": True,
                            "file_created": file_created,
                        })
                else:
                    results.append({
                        "tool_id": tool_id,
                        "tool_name": tool_name,
                        "version": version,
                        "message": f"Version '{version}' failed to create",
                        "success": False,
                    })
            except Exception as e:
                log.error(f"Error importing version '{version}' for tool '{tool_name}': {e}")
                results.append({
                    "tool_id": tool_id,
                    "tool_name": tool_name,
                    "version": version,
                    "message": str(e),
                    "success": False,
                })
        
        return results

    async def _import_single_tool(
        self,
        filename: str,
        code_snippet: str,
        model_name: str,
        created_by: str,
        department_name: Optional[str] = None,
        conflict_resolution: Literal["create_new_tool", "create_new_version"] = "create_new_tool",
        custom_name: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Import a single tool from its code snippet.

        Follows the same validation workflow as create_tool but with:
        - Name conflict resolution via user-provided custom_name OR add as new version
        - Conditional docstring generation (only if absent)
        - force_add=True (skips graph.ainvoke warning-level validation)
        - Graph validation still runs for error-level cases
        
        Args:
            filename: Original filename from zip
            code_snippet: The tool's Python code
            model_name: LLM model for docstring generation
            created_by: User email
            department_name: Department scope
            conflict_resolution: How to handle conflicts - "create_new_tool" or "create_new_version"
            custom_name: User-provided new name when resolving conflicts
        """
        try:
            # Step 1: Validate and extract function name
            validation = await self.tool_code_processor.validate_and_extract_tool_name(code_snippet)
            if not validation.get("is_valid"):
                return {
                    "filename": filename,
                    "message": validation.get("error", "Validation failed"),
                    "is_created": False,
                }

            original_name = validation["function_name"]

            # Step 2: Resolve name conflicts or add as new version
            # Returns {"action": "proceed"|"skip"|"needs_new_name"|"add_version"|"main_same", "name": str, ...}
            conflict_result = await self._resolve_tool_name_conflict(
                original_name, code_snippet, 
                department_name=department_name, 
                conflict_resolution=conflict_resolution,
                custom_name=custom_name,
            )

            if conflict_result["action"] == "skip":
                return {
                    "filename": filename,
                    "tool_name": conflict_result.get("name", original_name),
                    "message": conflict_result["message"],
                    "is_created": False,
                    "skipped": True,
                    "already_imported": conflict_result.get("already_imported", False),
                }
            
            # Handle "needs_new_name" action - user must provide a new name 
            if conflict_result["action"] == "needs_new_name":
                # Determine if this is from recycle bin or existing tool conflict
                in_recycle = conflict_result.get("in_recycle_bin", False)
                existing_tool_id = conflict_result.get("existing_tool_id")
                
                # Build options based on conflict type
                options = [
                    {
                        "value": "create_new_tool",
                        "label": "Create as new tool",
                        "description": "Provide a new name for this tool (names ending with _v1, _v2, etc. are reserved)",
                        "requires_name_input": True,
                    },
                    {
                        "value": "skip",
                        "label": "Skip this tool",
                        "description": "Do not import this tool"
                    }
                ]
                
                # Add "create_new_version" option if tool exists (not just in recycle bin)
                if existing_tool_id and not in_recycle:
                    next_version = "v1"
                    if hasattr(self.tool_service, 'tool_version_repo') and self.tool_service.tool_version_repo:
                        next_version = await self.tool_service.tool_version_repo.get_next_version_number(existing_tool_id)
                    options.insert(1, {
                        "value": "create_new_version",
                        "label": f"Add as new version ({next_version})",
                        "description": f"Add this code as version '{next_version}' to existing tool"
                    })
                
                return {
                    "filename": filename,
                    "tool_name": original_name,
                    "status": "conflict",
                    "message": conflict_result.get("message", f"Tool '{original_name}' already exists. Please provide a new name."),
                    "is_created": False,
                    "needs_new_name": True,
                    "requires_decision": True,
                    "in_recycle_bin": in_recycle,
                    "existing_tool_id": existing_tool_id,
                    "options": options,
                }
            
            # Handle "add_version" action - add main code as new version to existing tool
            if conflict_result["action"] == "add_version":
                existing_tool_id = conflict_result.get("existing_tool_id")
                new_version = conflict_result.get("new_version")
                
                # Add the incoming code as a new version
                if hasattr(self.tool_service, 'tool_version_repo') and self.tool_service.tool_version_repo:
                    try:
                        version_id = await self.tool_service.tool_version_repo.create_version(
                            tool_id=existing_tool_id,
                            version=new_version,
                            code_snippet=code_snippet,
                            tool_description=self._extract_docstring(code_snippet) if self._has_docstring(code_snippet) else "",
                            model_name=model_name,
                            updated_by=created_by,
                        )
                        if version_id:
                            # Create version .py file
                            file_created = False
                            if hasattr(self.tool_service, 'tool_file_manager') and self.tool_service.tool_file_manager:
                                try:
                                    version_tool_data = {
                                        "tool_name": original_name,
                                        "code_snippet": code_snippet,
                                    }
                                    file_result = await self.tool_service.tool_file_manager.create_tool_file(version_tool_data, version=new_version)
                                    file_created = file_result.get("success", False)
                                    if file_created:
                                        log.info(f"Created version file '{new_version}' for existing tool '{original_name}'")
                                except Exception as e:
                                    log.warning(f"Error creating version file '{new_version}' for tool '{original_name}': {e}")
                            
                            return {
                                "filename": filename,
                                "tool_name": original_name,
                                "existing_tool_id": existing_tool_id,
                                "message": f"Main code added as version '{new_version}' to existing tool '{original_name}'",
                                "new_version": new_version,
                                "is_created": False,
                                "merged_to_existing": True,
                                "file_created": file_created,
                            }
                    except Exception as e:
                        log.error(f"Error adding version to existing tool: {e}")
                        return {
                            "filename": filename,
                            "tool_name": original_name,
                            "message": f"Failed to add as new version: {str(e)}",
                            "is_created": False,
                        }
                
                return {
                    "filename": filename,
                    "tool_name": original_name,
                    "message": "Tool version repository not available",
                    "is_created": False,
                }
            
            # Handle "main_same" action - main code is same, signal to check versions
            if conflict_result["action"] == "main_same":
                return {
                    "filename": filename,
                    "tool_name": original_name,
                    "existing_tool_id": conflict_result.get("existing_tool_id"),
                    "message": conflict_result["message"],
                    "is_created": False,
                    "main_same_check_versions": True,
                }

            resolved_name = conflict_result["name"]
            # Track original name for function renaming and metadata lookup
            resolved_original_name = conflict_result.get("original_name", original_name)

            # Step 3: If name changed, rename the function in the AST
            if resolved_name != original_name:
                code_snippet = self._rename_function_in_code(code_snippet, original_name, resolved_name)
                if code_snippet is None:
                    return {
                        "filename": filename,
                        "tool_name": original_name,
                        "message": f"Failed to rename function from '{original_name}' to '{resolved_name}'",
                        "is_created": False,
                    }

            update_session_context(tool_name=resolved_name)

            # Step 4: Run validation graph with force_add=True
            initial_state = {
                "code": code_snippet,
                "model": model_name,
                "validation_case1": None, "feedback_case1": None,
                "validation_case3": None, "feedback_case3": None,
                "validation_case4": None, "feedback_case4": None,
                "validation_case5": None, "feedback_case5": None,
                "validation_case6": None, "feedback_case6": None,
                "validation_case7": None, "feedback_case7": None,
                "validation_case8": None, "feedback_case8": None,
            }
            workflow_result = await graph.ainvoke(input=initial_state)

            # Check error cases (hard failures)
            e_cases = ["validation_case8", "validation_case1", "validation_case4"]
            errors = {}
            for j in e_cases:
                if not workflow_result.get(j):
                    feedback_key = j.replace("validation_", "feedback_")
                    errors[j] = workflow_result.get(feedback_key)

            if errors:
                verify = list(errors.values())
                return {
                    "filename": filename,
                    "tool_name": resolved_name,
                    "message": verify[0],
                    "is_created": False,
                }

            # Warning cases are skipped (force_add=True behavior)

            # Step 5: Check if docstring is already present
            has_docstring = self._has_docstring(code_snippet)

            # Step 6: Extract existing docstring or generate one
            tool_description = ""
            if has_docstring:
                tool_description = self._extract_docstring(code_snippet)
            else:
                # Generate docstring via LLM
                try:
                    llm = await self.model_service.get_llm_model(model_name=model_name, temperature=0.0)
                    docstring_result = await self.tool_code_processor.generate_docstring_for_tool_onboarding(
                        llm=llm,
                        tool_code_str=code_snippet,
                        tool_description="",
                    )
                    if "error" in docstring_result:
                        return {
                            "filename": filename,
                            "tool_name": resolved_name,
                            "message": f"Docstring generation failed: {docstring_result['error']}",
                            "is_created": False,
                        }
                    code_snippet = docstring_result["code_snippet"]
                    tool_description = self._extract_docstring(code_snippet)
                except Exception as e:
                    log.error(f"Error generating docstring for {resolved_name}: {e}")
                    return {
                        "filename": filename,
                        "tool_name": resolved_name,
                        "message": f"Docstring generation error: {str(e)}",
                        "is_created": False,
                    }

            # Step 7: Generate tool_id and default tag
            tool_id = str(uuid.uuid4())
            update_session_context(tool_id=tool_id)

            general_tag = await self.tag_service.get_tag(tag_name="General")
            tag_ids = [general_tag["tag_id"]] if general_tag else []

            # Step 8: Save tool record
            now = datetime.now(timezone.utc).replace(tzinfo=None)
            tool_data = {
                "tool_id": tool_id,
                "tool_name": resolved_name,
                "tool_description": tool_description,
                "code_snippet": code_snippet,
                "model_name": model_name,
                "created_by": created_by,
                "created_on": now,
                "updated_on": now,
                "department_name": department_name,
            }

            success = await self.tool_service.tool_repo.save_tool_record(tool_data)

            if success:
                # Assign tags
                tags_status = await self.tag_service.assign_tags_to_tool(
                    tag_ids=tag_ids, tool_id=tool_id
                )
                
                # Create tool .py file (same as create_tool flow)
                file_created = False
                file_path = ""
                if hasattr(self.tool_service, 'tool_file_manager') and self.tool_service.tool_file_manager:
                    try:
                        file_result = await self.tool_service.tool_file_manager.create_tool_file(tool_data, version="v1")
                        file_created = file_result.get("success", False)
                        file_path = file_result.get("file_path", "")
                        if file_created:
                            log.info(f"Created tool file for imported tool '{resolved_name}': {file_path}")
                        else:
                            log.warning(f"Failed to create tool file for imported tool '{resolved_name}': {file_result.get('message')}")
                    except Exception as e:
                        log.warning(f"Error creating tool file for imported tool '{resolved_name}': {e}")
                
                log.info(f"Successfully imported tool '{resolved_name}' with ID: {tool_id}")
                result = {
                    "filename": filename,
                    "message": f"Successfully imported tool: {resolved_name}",
                    "tool_id": tool_id,
                    "tool_name": resolved_name,
                    "original_name": original_name,
                    "tool_description": tool_description,
                    "code_snippet": code_snippet,
                    "model_name": model_name,
                    "created_by": created_by,
                    "tags_status": tags_status,
                    "is_created": True,
                    "file_created": file_created,
                    "file_path": file_path,
                }
                if resolved_name != original_name:
                    result["renamed_to"] = resolved_name
                return result
            else:
                return {
                    "filename": filename,
                    "tool_name": resolved_name,
                    "message": f"Integrity error: Tool name '{resolved_name}' already exists.",
                    "is_created": False,
                }

        except Exception as e:
            log.error(f"Error importing tool from {filename}: {e}")
            return {
                "filename": filename,
                "message": f"Import error: {str(e)}",
                "is_created": False,
            }

    async def _resolve_tool_name_conflict(
        self, 
        tool_name: str, 
        incoming_code: str, 
        department_name: Optional[str] = None,
        conflict_resolution: Literal["create_new_tool", "create_new_version"] = "create_new_tool",
        custom_name: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Check if tool_name exists in tool_table or recycle_tool table.
        Scoped by department_name since the DB constraint is UNIQUE(tool_name, department_name).

        - If custom_name provided: validate and use it if available
        - If not found anywhere: proceed with original name.
        - If found in recycle bin only: return needs_new_name asking user to provide a new name.
        - If found in normal table:
            - Same code_snippet: signal to check versions ("main_same" action)
            - Different code_snippet: 
                - If conflict_resolution="create_new_tool": return needs_new_name asking user to provide name
                - If conflict_resolution="create_new_version": add as new version to existing tool

        Returns:
            dict with 'action' ('proceed' | 'skip' | 'needs_new_name' | 'add_version' | 'main_same'), 
            'name', and optional 'message', 'existing_tool_id', 'new_version', 'needs_new_name'.
        """
        import re
        
        # Helper function to validate name format and availability
        async def validate_name(name: str) -> tuple:
            """Returns (is_valid, error_message)"""
            # Check for reserved _v\d+ pattern
            if re.search(r'_v\d+$', name, re.IGNORECASE):
                return False, f"Name '{name}' is invalid: Names ending with _v1, _v2, etc. are reserved for version files."
            
            # Check if name exists in normal table
            existing = await self.tool_service.tool_repo.get_tool_record(
                tool_name=name, department_name=department_name, include_public=False
            )
            if existing:
                return False, f"Name '{name}' already exists. Please provide a different name."
            
            # Check if name exists in recycle bin
            in_recycle = await self.tool_service.recycle_tool_repo.is_tool_in_recycle_bin_record(tool_name=name)
            if in_recycle:
                return False, f"Name '{name}' exists in recycle bin. Please provide a different name."
            
            return True, None
        
        # If user provided a custom_name, first check if it was already imported (same code exists)
        if custom_name:
            custom_name = custom_name.strip()
            
            # Check if tool with custom_name already exists with same code (already imported)
            existing_with_custom_name = await self.tool_service.tool_repo.get_tool_record(
                tool_name=custom_name, department_name=department_name, include_public=False
            )
            if existing_with_custom_name:
                existing_code = existing_with_custom_name[0].get("code_snippet", "")
                # Normalize both codes, also handle the case where function was renamed in the code
                existing_normalized = self._normalize_code(existing_code)
                incoming_normalized = self._normalize_code(incoming_code)
                
                # Check if codes match (ignoring function name difference since we renamed it)
                # Parse and compare the function body
                if self._codes_match_ignoring_function_name(existing_code, incoming_code, custom_name, tool_name):
                    # Tool was already imported with this name - auto-skip
                    log.info(f"Tool '{custom_name}' already exists with same code (imported previously). Auto-skipping.")
                    return {
                        "action": "skip", 
                        "name": custom_name, 
                        "message": f"Tool '{custom_name}' already imported with identical code. Skipped.",
                        "already_imported": True,
                    }
            
            # Now validate the custom name
            is_valid, error_msg = await validate_name(custom_name)
            if is_valid:
                return {"action": "proceed", "name": custom_name, "original_name": tool_name}
            else:
                # Custom name is invalid - need to determine original conflict type
                # Check if original tool exists in normal table
                existing_records = await self.tool_service.tool_repo.get_tool_record(
                    tool_name=tool_name, department_name=department_name, include_public=False
                )
                existing_tool_id = existing_records[0].get("tool_id", "") if existing_records else None
                
                # Check if original tool exists in recycle bin
                in_recycle = await self.tool_service.recycle_tool_repo.is_tool_in_recycle_bin_record(tool_name=tool_name)
                
                return {
                    "action": "needs_new_name",
                    "name": tool_name,
                    "needs_new_name": True,
                    "message": error_msg,
                    "existing_tool_id": existing_tool_id,
                    "in_recycle_bin": in_recycle and not existing_tool_id,
                }
        
        # First validate the incoming tool name format (no _v1, _v2 pattern)
        if re.search(r'_v\d+$', tool_name, re.IGNORECASE):
            return {
                "action": "needs_new_name",
                "name": tool_name,
                "needs_new_name": True,
                "message": f"Invalid tool name '{tool_name}': Function names ending with _v1, _v2, etc. are reserved for version files. Please provide a new name.",
                "existing_tool_id": None,
                "in_recycle_bin": False,
            }
        
        # Check normal table first (department-scoped, exclude public tools from other depts)
        existing_records = await self.tool_service.tool_repo.get_tool_record(
            tool_name=tool_name, department_name=department_name, include_public=False
        )
        if existing_records:
            existing_tool = existing_records[0]
            existing_code = existing_tool.get("code_snippet", "")
            existing_tool_id = existing_tool.get("tool_id", "")
            
            if self._normalize_code(existing_code) == self._normalize_code(incoming_code):
                # Main code is SAME - signal to check/import versions
                return {
                    "action": "main_same",
                    "name": tool_name,
                    "existing_tool_id": existing_tool_id,
                    "message": f"Tool '{tool_name}' already exists with identical main code.",
                }
            
            # Different code — handle based on conflict_resolution
            if conflict_resolution == "create_new_version":
                # Add as new version to existing tool
                if hasattr(self.tool_service, 'tool_version_repo') and self.tool_service.tool_version_repo:
                    next_version = await self.tool_service.tool_version_repo.get_next_version_number(existing_tool_id)
                    return {
                        "action": "add_version",
                        "name": tool_name,
                        "existing_tool_id": existing_tool_id,
                        "new_version": next_version,
                        "message": f"Will add imported code as version '{next_version}' to existing tool '{tool_name}'.",
                    }
                else:
                    log.warning("Tool version repository not available")
            
            # For create_new_tool: Return needs_new_name asking user to provide a name
            return {
                "action": "needs_new_name",
                "name": tool_name,
                "needs_new_name": True,
                "existing_tool_id": existing_tool_id,
                "in_recycle_bin": False,
                "message": f"Tool '{tool_name}' already exists with different code. Please provide a new name for this tool. Note: Names ending with _v1, _v2, etc. are reserved.",
            }

        # Check recycle bin
        in_recycle = await self.tool_service.recycle_tool_repo.is_tool_in_recycle_bin_record(tool_name=tool_name)
        if in_recycle:
            # Return needs_new_name asking user to provide a name
            return {
                "action": "needs_new_name",
                "name": tool_name,
                "needs_new_name": True,
                "in_recycle_bin": True,
                "existing_tool_id": None,
                "message": f"Tool '{tool_name}' exists in recycle bin. Please provide a new name for this tool. Note: Names ending with _v1, _v2, etc. are reserved.",
            }

        # Name is free
        return {"action": "proceed", "name": tool_name}

    @staticmethod
    def _normalize_code(code: str) -> str:
        """Normalize code for comparison by stripping whitespace variations."""
        return code.strip().replace("\r\n", "\n").replace("\r", "\n")

    def _codes_match_ignoring_function_name(self, existing_code: str, incoming_code: str, existing_name: str, incoming_name: str) -> bool:
        """
        Compare two code snippets, ignoring the function name difference.
        Used to detect if a tool was already imported (function was renamed but body is same).
        
        Args:
            existing_code: Code already in DB (with renamed function)
            incoming_code: Code from zip file (with original function name)
            existing_name: Function name in existing code
            incoming_name: Function name in incoming code
            
        Returns:
            True if the function bodies match (ignoring function name)
        """
        import re
        
        # Normalize both codes
        existing_norm = self._normalize_code(existing_code)
        incoming_norm = self._normalize_code(incoming_code)
        
        # Replace function names with a placeholder to compare bodies
        # Pattern: def function_name( -> def __FUNC__(
        existing_replaced = re.sub(
            rf'\bdef\s+{re.escape(existing_name)}\s*\(',
            'def __FUNC__(',
            existing_norm
        )
        incoming_replaced = re.sub(
            rf'\bdef\s+{re.escape(incoming_name)}\s*\(',
            'def __FUNC__(',
            incoming_norm
        )
        
        # Also replace any docstring references to the function name (optional)
        # Just compare the normalized versions
        return existing_replaced == incoming_replaced

    @staticmethod
    def _hash_code(code: str) -> str:
        """
        Create a SHA-256 hash of normalized code for O(1) comparison.
        Used for O(m+n) version comparison instead of O(m*n) string comparison.
        
        Args:
            code: The code snippet to hash
            
        Returns:
            SHA-256 hex digest of the normalized code
        """
        normalized = code.strip().replace("\r\n", "\n").replace("\r", "\n")
        return hashlib.sha256(normalized.encode('utf-8')).hexdigest()

    @staticmethod
    def _rename_function_in_code(code: str, old_name: str, new_name: str) -> Optional[str]:
        """
        Use AST to safely rename the function definition in the code.
        Only renames the top-level function def, not references inside the body.
        """
        try:
            tree = ast.parse(code)

            for node in tree.body:
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    if node.name == old_name:
                        node.name = new_name
                        break

            return safe_to_source(tree)
        except Exception as e:
            log.error(f"Error renaming function '{old_name}' to '{new_name}': {e}")
            return None

    @staticmethod
    def _has_docstring(code: str) -> bool:
        """Check if the function in the code has a docstring."""
        try:
            tree = ast.parse(code)
            for node in tree.body:
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    return ast.get_docstring(node) is not None
        except Exception:
            pass
        return False

    @staticmethod
    def _extract_docstring(code: str) -> str:
        """Extract the docstring from the function definition."""
        try:
            tree = ast.parse(code)
            for node in tree.body:
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    docstring = ast.get_docstring(node)
                    if docstring:
                        return docstring
        except Exception:
            pass
        return ""

    @staticmethod
    def _extract_py_files_from_zip(zip_buffer: io.BytesIO) -> List[tuple]:
        """
        Extract .py files from a zip buffer.
        Handles two scenarios:
        1. .py files directly in the zip root
        2. .py files inside a folder within the zip

        Returns:
            List of (filename, content) tuples.
        """
        py_files = []
        try:
            with zipfile.ZipFile(zip_buffer, "r") as zf:
                for entry in zf.namelist():
                    # Skip directories and hidden files
                    if entry.endswith("/") or entry.startswith("__MACOSX"):
                        continue

                    # Only process .py files
                    basename = os.path.basename(entry)
                    if basename.endswith(".py") and not basename.startswith("."):
                        try:
                            content = zf.read(entry).decode("utf-8")
                            # Normalize newlines
                            content = content.replace("\r\n", "\n").replace("\r", "\n")
                            py_files.append((basename, content))
                        except Exception as e:
                            log.warning(f"Could not read {entry} from zip: {e}")
        except zipfile.BadZipFile:
            log.error("Invalid zip file provided")
        except Exception as e:
            log.error(f"Error extracting zip: {e}")

        return py_files

    @staticmethod
    def _extract_all_files_from_zip(zip_buffer: io.BytesIO) -> Dict[str, Any]:
        """
        Extract all files (.py, .json) from a zip buffer for versioned tool import.
        
        Returns:
            Dict with:
            - 'py_files': Dict mapping filename -> content (for .py files)
            - 'metadata_files': Dict mapping tool_name -> metadata dict (from _metadata.json)
        """
        py_files = {}
        metadata_files = {}
        
        try:
            with zipfile.ZipFile(zip_buffer, "r") as zf:
                for entry in zf.namelist():
                    # Skip directories and hidden files
                    if entry.endswith("/") or entry.startswith("__MACOSX"):
                        continue

                    basename = os.path.basename(entry)
                    
                    # Process .py files
                    if basename.endswith(".py") and not basename.startswith("."):
                        try:
                            content = zf.read(entry).decode("utf-8")
                            content = content.replace("\r\n", "\n").replace("\r", "\n")
                            py_files[basename] = content
                        except Exception as e:
                            log.warning(f"Could not read {entry} from zip: {e}")
                    
                    # Process metadata JSON files
                    elif basename.endswith("_metadata.json"):
                        try:
                            content = zf.read(entry).decode("utf-8")
                            metadata = json.loads(content)
                            tool_name = metadata.get("tool_name", basename.replace("_metadata.json", ""))
                            metadata_files[tool_name] = metadata
                        except Exception as e:
                            log.warning(f"Could not read metadata {entry} from zip: {e}")
                    
        except zipfile.BadZipFile:
            log.error("Invalid zip file provided")
        except Exception as e:
            log.error(f"Error extracting zip: {e}")

        return {"py_files": py_files, "metadata_files": metadata_files}

    # ─────────────────────────────────────────────
    # MCP TOOL EXPORT
    # ─────────────────────────────────────────────

    async def export_mcp_tools(self, tool_ids: List[str]) -> Dict[str, Any]:
        """
        Export a list of MCP tools by their IDs into a zip buffer.

        Each MCP tool is exported as a .json file containing all metadata
        (including code_content for file-type MCPs and VAULT references for url-type).

        Args:
            tool_ids: List of MCP tool IDs to export.

        Returns:
            dict with 'zip_buffer' (BytesIO), 'exported' count, 'failed' list, 'file_count'.
        """
        zip_buffer = io.BytesIO()
        exported = []
        failed = []

        with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zf:
            for tool_id in tool_ids:
                try:
                    tool_records = await self.mcp_tool_service.get_mcp_tool(tool_id=tool_id)
                    if not tool_records:
                        failed.append({"tool_id": tool_id, "reason": "MCP tool not found"})
                        continue

                    tool = tool_records[0]
                    tool_name = tool.get("tool_name", "unknown_mcp_tool")
                    mcp_config: dict = tool.get("mcp_config", {})
                    mcp_type = await self.mcp_tool_service._get_mcp_type_by_id(tool_id=tool_id)

                    # Build export JSON
                    export_data = {
                        "tool_name": tool_name,
                        "tool_description": tool.get("tool_description", ""),
                        "mcp_type": mcp_type,
                    }

                    if mcp_type == "file":
                        # Extract code from mcp_config.args[1] and write as separate .py file
                        args = mcp_config.get("args", [])
                        code_content = args[1] if len(args) >= 2 else ""
                        if code_content:
                            py_filename = f"{tool_name}.py"
                            zf.writestr(py_filename, code_content)

                    elif mcp_type == "url":
                        export_data["mcp_url"] = mcp_config.get("url", "")
                        if mcp_config.get("headers"):
                            export_data["headers"] = mcp_config["headers"]

                    elif mcp_type == "module":
                        args = mcp_config.get("args", [])
                        if len(args) >= 2:
                            export_data["mcp_module_name"] = args[1]
                        else:
                            export_data["mcp_module_name"] = ""
                        # Export the command (e.g. "npx", "python", or custom path)
                        mcp_command = mcp_config.get("command", "python")
                        export_data["mcp_command"] = mcp_command

                    filename = f"{tool_name}.json"
                    json_content = json.dumps(export_data, indent=2, ensure_ascii=False)
                    zf.writestr(filename, json_content)
                    exported.append({"tool_id": tool_id, "tool_name": tool_name, "filename": filename, "mcp_type": mcp_type})

                except Exception as e:
                    log.error(f"Error exporting MCP tool {tool_id}: {e}")
                    failed.append({"tool_id": tool_id, "reason": str(e)})

        zip_buffer.seek(0)
        return {
            "zip_buffer": zip_buffer,
            "exported": exported,
            "failed": failed,
            "file_count": len(exported),
        }

    # ─────────────────────────────────────────────
    # MCP TOOL IMPORT
    # ─────────────────────────────────────────────

    async def import_mcp_tools(
        self,
        zip_buffer: io.BytesIO,
        created_by: str,
        department_name: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Import MCP tools from a .zip file. Each .json file is treated as one MCP tool.
        For file-type MCPs, code_content is read from a companion .py file with the same
        base name (e.g. my_server.json + my_server.py).

        Handles nested folder structures.
        Applies _copy1/_copy2 suffix for name conflicts.
        Follows same validation process as create_mcp_tool.

        Args:
            zip_buffer: BytesIO of the uploaded zip file.
            created_by: Email of the importing user.
            department_name: The department of the importing user (for department-scoped uniqueness).

        Returns:
            dict with 'imported', 'failed', 'summary' counts.
        """
        json_files, py_files_map = self._extract_mcp_files_from_zip(zip_buffer)

        if not json_files:
            return {
                "message": "No .json files found in the uploaded zip.",
                "imported": [],
                "failed": [],
                "total": 0,
            }

        imported = []
        failed = []
        skipped = []

        for filename, json_content in json_files:
            result = await self._import_single_mcp_tool(
                filename=filename,
                json_content=json_content,
                created_by=created_by,
                py_files_map=py_files_map,
                department_name=department_name,
            )
            if result.get("is_created"):
                imported.append(result)
            elif result.get("skipped"):
                skipped.append(result)
            else:
                failed.append(result)

        # Build detailed summary message with tool names
        summary_parts = []
        
        if imported:
            imported_names = [r.get("filename", "unknown") for r in imported]
            summary_parts.append(f"{len(imported)} imported ({', '.join(imported_names)})")
        
        if skipped:
            skipped_names = [r.get("filename", "unknown") for r in skipped]
            summary_parts.append(f"{len(skipped)} skipped ({', '.join(skipped_names)} - already exist)")
        
        if failed:
            failed_details = []
            for r in failed:
                name = r.get("filename", "unknown")
                reason = r.get("message", "unknown error")
                short_reason = reason[:50] + "..." if len(reason) > 50 else reason
                failed_details.append(f"{name}: {short_reason}")
            summary_parts.append(f"{len(failed)} failed ({', '.join(failed_details)})")
        
        detailed_message = "Import complete. " + ("; ".join(summary_parts) if summary_parts else "No MCP tools processed.")

        return {
            "message": detailed_message,
            "imported": imported,
            "skipped": skipped,
            "failed": failed,
            "total": len(json_files),
        }

    async def _import_single_mcp_tool(
        self,
        filename: str,
        json_content: str,
        created_by: str,
        py_files_map: Optional[Dict[str, str]] = None,
        department_name: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Import a single MCP tool from its JSON content.
        For file-type MCPs, code_content is loaded from the companion .py file
        found in py_files_map (keyed by base name without extension).
        """
        try:
            # Step 1: Parse JSON
            try:
                data: dict = json.loads(json_content)
            except json.JSONDecodeError as e:
                return {
                    "filename": filename,
                    "message": f"Invalid JSON: {str(e)}",
                    "is_created": False,
                }

            tool_name = data.get("tool_name", "").strip()
            tool_description = data.get("tool_description", "").strip()
            mcp_type = data.get("mcp_type", "").strip()

            if not tool_name:
                return {
                    "filename": filename,
                    "message": "Missing 'tool_name' in JSON",
                    "is_created": False,
                }

            if mcp_type not in ("file", "url", "module"):
                return {
                    "filename": filename,
                    "tool_name": tool_name,
                    "message": f"Invalid mcp_type: '{mcp_type}'. Must be 'file', 'url', or 'module'.",
                    "is_created": False,
                }

            # Step 2: Extract type-specific fields first (needed for duplicate comparison)
            original_name = tool_name
            mcp_url = data.get("mcp_url")
            headers = data.get("headers")
            mcp_module_name = data.get("mcp_module_name")
            mcp_command = data.get("mcp_command")
            code_content = data.get("code_content")

            # For file-type MCPs, load code from companion .py file early
            if mcp_type == "file" and py_files_map:
                base_name = os.path.splitext(filename)[0]
                if base_name in py_files_map:
                    code_content = py_files_map[base_name]
                elif not code_content:
                    return {
                        "filename": filename,
                        "tool_name": tool_name,
                        "message": f"No companion .py file found for file-type MCP '{tool_name}' and no code_content in JSON.",
                        "is_created": False,
                    }

            # Build incoming config for duplicate comparison
            incoming_config = {
                "mcp_type": mcp_type,
                "mcp_url": mcp_url,
                "headers": headers,
                "mcp_module_name": mcp_module_name,
                "mcp_command": mcp_command,
                "code_content": code_content,
            }

            # Resolve name conflicts (department-scoped)
            conflict_result = await self._resolve_mcp_tool_name_conflict(tool_name, incoming_config, department_name=department_name)

            if conflict_result["action"] == "skip":
                return {
                    "filename": filename,
                    "tool_name": original_name,
                    "message": conflict_result["message"],
                    "is_created": False,
                    "skipped": True,
                }

            resolved_name = conflict_result["name"]

            # Step 4: Delegate to create_mcp_tool (which handles all validation)
            status = await self.mcp_tool_service.create_mcp_tool(
                tool_name=resolved_name,
                tool_description=tool_description,
                mcp_type=mcp_type,
                created_by=created_by,
                tag_ids=None,  # Default to General
                mcp_url=mcp_url,
                headers=headers,
                mcp_module_name=mcp_module_name,
                mcp_command=mcp_command,
                code_content=code_content,
                department_name=department_name,
            )

            status["filename"] = filename
            if status.get("is_created"):
                status["original_name"] = original_name
                if resolved_name != original_name:
                    status["renamed_to"] = resolved_name

            return status

        except Exception as e:
            log.error(f"Error importing MCP tool from {filename}: {e}")
            return {
                "filename": filename,
                "message": f"Import error: {str(e)}",
                "is_created": False,
            }

    async def _resolve_mcp_tool_name_conflict(self, tool_name: str, incoming_config: Dict[str, Any], department_name: Optional[str] = None) -> Dict[str, Any]:
        """
        Check if MCP tool_name exists in mcp_tool_table or recycle_mcp_tool table.
        Scoped by department_name since the DB constraint is UNIQUE(tool_name, department_name).

        - If not found anywhere: proceed with original name.
        - If found in recycle bin only: rename with _copy1, _copy2, etc.
        - If found in normal table:
            - Same config (url/headers/code_content/module_name): skip.
            - Different config: rename with _copy1, _copy2, etc.

        Returns:
            dict with 'action' ('proceed' | 'skip' | 'rename'), 'name', and optional 'message'.
        """
        existing_records = await self.mcp_tool_service.mcp_tool_repo.get_mcp_tool_record(
            tool_name=tool_name, department_name=department_name
        )
        if existing_records:
            if self._is_mcp_config_identical(existing_records[0], incoming_config):
                return {
                    "action": "skip",
                    "name": tool_name,
                    "message": f"MCP server '{tool_name}' already exists with identical configuration. Skipping import.",
                }
            return await self._find_available_mcp_name(tool_name, incoming_config, department_name=department_name)

        in_recycle = await self.mcp_tool_service.recycle_mcp_tool_repo.is_mcp_tool_in_recycle_bin_record(tool_name=tool_name)
        if in_recycle:
            return await self._find_available_mcp_name(tool_name, incoming_config, department_name=department_name)

        return {"action": "proceed", "name": tool_name}

    async def _find_available_mcp_name(self, tool_name: str, incoming_config: Dict[str, Any], department_name: Optional[str] = None) -> Dict[str, Any]:
        """
        Find the next available name (_copy1, _copy2, ...) for an MCP tool,
        also checking if any copy name has identical config (skip if so).
        Department-scoped to match UNIQUE(tool_name, department_name) constraint.
        """
        copy_num = 1
        while copy_num <= 100:
            candidate = f"{tool_name}_copy{copy_num}"

            existing_records = await self.mcp_tool_service.mcp_tool_repo.get_mcp_tool_record(
                tool_name=candidate, department_name=department_name
            )
            if existing_records:
                if self._is_mcp_config_identical(existing_records[0], incoming_config):
                    return {
                        "action": "skip",
                        "name": candidate,
                        "message": f"MCP server '{candidate}' already exists with identical configuration. Skipping import.",
                    }
                copy_num += 1
                continue

            in_recycle = await self.mcp_tool_service.recycle_mcp_tool_repo.is_mcp_tool_in_recycle_bin_record(tool_name=candidate)
            if in_recycle:
                copy_num += 1
                continue

            log.info(f"Resolved MCP name conflict: '{tool_name}' -> '{candidate}'")
            return {"action": "rename", "name": candidate}

        raise ValueError(f"Could not resolve MCP name conflict for '{tool_name}' after 100 attempts")

    def _is_mcp_config_identical(self, existing_record: Dict[str, Any], incoming_config: Dict[str, Any]) -> bool:
        """
        Compare an existing MCP tool record's configuration with incoming import data.
        Ignores tool_description differences.

        Compares based on mcp_type:
        - file:   code_content
        - url:    mcp_url + headers
        - module: mcp_module_name
        """
        mcp_config = existing_record.get("mcp_config", {})
        if isinstance(mcp_config, str):
            mcp_config = json.loads(mcp_config)

        incoming_type = incoming_config.get("mcp_type", "")

        if incoming_type == "file":
            # Existing code is in mcp_config.args[1]
            existing_args = mcp_config.get("args", [])
            existing_code = existing_args[1] if len(existing_args) >= 2 else ""
            incoming_code = incoming_config.get("code_content") or ""
            return self._normalize_code(existing_code) == self._normalize_code(incoming_code)

        elif incoming_type == "url":
            existing_url = mcp_config.get("url", "")
            incoming_url = incoming_config.get("mcp_url") or ""
            if existing_url != incoming_url:
                return False
            existing_headers = mcp_config.get("headers") or {}
            incoming_headers = incoming_config.get("headers") or {}
            return existing_headers == incoming_headers

        elif incoming_type == "module":
            existing_args = mcp_config.get("args", [])
            existing_module = existing_args[1] if len(existing_args) >= 2 else ""
            incoming_module = (incoming_config.get("mcp_module_name") or "").replace("-", "_")
            # Also compare the command (e.g. "npx" vs "python")
            existing_command = mcp_config.get("command", "python")
            incoming_command = incoming_config.get("mcp_command") or "python"
            return existing_module == incoming_module and existing_command == incoming_command

        return False

    @staticmethod
    def _extract_mcp_files_from_zip(zip_buffer: io.BytesIO) -> tuple:
        """
        Extract .json and .py files from a zip buffer for MCP import.
        Handles both flat and nested folder structures.

        Returns:
            Tuple of:
            - json_files: List of (filename, content) tuples for .json files
            - py_files_map: Dict mapping base name (without extension) to .py file content
        """
        json_files = []
        py_files_map: Dict[str, str] = {}
        try:
            with zipfile.ZipFile(zip_buffer, "r") as zf:
                for entry in zf.namelist():
                    if entry.endswith("/") or entry.startswith("__MACOSX"):
                        continue

                    basename = os.path.basename(entry)
                    if basename.startswith("."):
                        continue

                    try:
                        if basename.endswith(".json"):
                            content = zf.read(entry).decode("utf-8")
                            json_files.append((basename, content))
                        elif basename.endswith(".py"):
                            content = zf.read(entry).decode("utf-8")
                            content = content.replace("\r\n", "\n").replace("\r", "\n")
                            base_name = os.path.splitext(basename)[0]
                            py_files_map[base_name] = content
                    except Exception as e:
                        log.warning(f"Could not read {entry} from zip: {e}")
        except zipfile.BadZipFile:
            log.error("Invalid zip file provided")
        except Exception as e:
            log.error(f"Error extracting zip: {e}")

        return json_files, py_files_map

