# © 2024-25 Infosys Limited, Bangalore, India. All Rights Reserved.
"""
Service for exporting and importing tools and MCP servers as .zip files.
"""

import ast
import io
import json
import os
import uuid
import zipfile
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

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

        Each tool's code_snippet is written as a .py file named after the tool.

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

                    filename = f"{tool_name}.py"
                    zf.writestr(filename, code_snippet)
                    exported.append({"tool_id": tool_id, "tool_name": tool_name, "filename": filename})

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
    # TOOL IMPORT
    # ─────────────────────────────────────────────

    async def import_tools(
        self,
        zip_buffer: io.BytesIO,
        model_name: str,
        created_by: str,
        department_name: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Import tools from a .zip file. Each .py file is treated as one tool.

        Handles nested folder structures (zip may contain a folder with .py files).
        Applies _V1/_V2 suffix for name conflicts (checking both tool and recycle tables).
        Generates docstring only if one is not already present.
        Uses force_add=True to bypass graph validation.

        Args:
            zip_buffer: BytesIO of the uploaded zip file.
            model_name: LLM model name to use for docstring generation.
            created_by: Email of the importing user.
            department_name: The department of the importing user (for department-scoped uniqueness).

        Returns:
            dict with 'imported', 'failed', 'summary' lists.
        """
        py_files = self._extract_py_files_from_zip(zip_buffer)

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

        for filename, code_snippet in py_files:
            result = await self._import_single_tool(
                filename=filename,
                code_snippet=code_snippet,
                model_name=model_name,
                created_by=created_by,
                department_name=department_name,
            )
            if result.get("is_created"):
                imported.append(result)
            elif result.get("skipped"):
                skipped.append(result)
            else:
                failed.append(result)

        return {
            "message": f"Import complete. {len(imported)} imported, {len(skipped)} skipped (already exist), {len(failed)} failed.",
            "imported": imported,
            "skipped": skipped,
            "failed": failed,
            "total": len(py_files),
        }

    async def _import_single_tool(
        self,
        filename: str,
        code_snippet: str,
        model_name: str,
        created_by: str,
        department_name: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Import a single tool from its code snippet.

        Follows the same validation pipeline as create_tool but with:
        - Name conflict resolution (_V1, _V2) via AST rename
        - Conditional docstring generation (only if absent)
        - force_add=True (skips graph.ainvoke warning-level validation)
        - Graph validation still runs for error-level cases
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

            # Step 2: Resolve name conflicts (_V1, _V2, etc.)
            # Returns {"action": "proceed"|"skip"|"rename", "name": str, "message": str?}
            conflict_result = await self._resolve_tool_name_conflict(original_name, code_snippet, department_name=department_name)

            if conflict_result["action"] == "skip":
                return {
                    "filename": filename,
                    "tool_name": original_name,
                    "message": conflict_result["message"],
                    "is_created": False,
                    "skipped": True,
                }

            resolved_name = conflict_result["name"]

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
                log.info(f"Successfully imported tool '{resolved_name}' with ID: {tool_id}")
                result = {
                    "filename": filename,
                    "message": f"Successfully imported tool: {resolved_name}",
                    "tool_id": tool_id,
                    "tool_name": resolved_name,
                    "original_name": original_name,
                    "model_name": model_name,
                    "created_by": created_by,
                    "tags_status": tags_status,
                    "is_created": True,
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

    async def _resolve_tool_name_conflict(self, tool_name: str, incoming_code: str, department_name: Optional[str] = None) -> Dict[str, Any]:
        """
        Check if tool_name exists in tool_table or recycle_tool table.
        Scoped by department_name since the DB constraint is UNIQUE(tool_name, department_name).

        - If not found anywhere: proceed with original name.
        - If found in recycle bin only: rename with _V1, _V2, etc.
        - If found in normal table:
            - Same code_snippet: skip (tool already present).
            - Different code_snippet: rename with _V1, _V2, etc.

        Returns:
            dict with 'action' ('proceed' | 'skip' | 'rename'), 'name', and optional 'message'.
        """
        # Check normal table first (department-scoped, exclude public tools from other depts)
        existing_records = await self.tool_service.tool_repo.get_tool_record(
            tool_name=tool_name, department_name=department_name, include_public=False
        )
        if existing_records:
            existing_code = existing_records[0].get("code_snippet", "")
            if self._normalize_code(existing_code) == self._normalize_code(incoming_code):
                return {
                    "action": "skip",
                    "name": tool_name,
                    "message": f"Tool '{tool_name}' already exists with identical code. Skipping import.",
                }
            # Different code — need to rename
            return await self._find_available_tool_name(tool_name, incoming_code, department_name=department_name)

        # Check recycle bin
        in_recycle = await self.tool_service.recycle_tool_repo.is_tool_in_recycle_bin_record(tool_name=tool_name)
        if in_recycle:
            return await self._find_available_tool_name(tool_name, incoming_code, department_name=department_name)

        # Name is free
        return {"action": "proceed", "name": tool_name}

    async def _find_available_tool_name(self, tool_name: str, incoming_code: str, department_name: Optional[str] = None) -> Dict[str, Any]:
        """
        Find the next available name (_V1, _V2, ...) for a tool,
        also checking if any versioned name has identical code (skip if so).
        Department-scoped to match UNIQUE(tool_name, department_name) constraint.
        """
        version = 1
        while version <= 100:
            candidate = f"{tool_name}_V{version}"

            # Check normal table (department-scoped)
            existing_records = await self.tool_service.tool_repo.get_tool_record(
                tool_name=candidate, department_name=department_name, include_public=False
            )
            if existing_records:
                existing_code = existing_records[0].get("code_snippet", "")
                if self._normalize_code(existing_code) == self._normalize_code(incoming_code):
                    return {
                        "action": "skip",
                        "name": candidate,
                        "message": f"Tool '{candidate}' already exists with identical code. Skipping import.",
                    }
                version += 1
                continue

            # Check recycle bin
            in_recycle = await self.tool_service.recycle_tool_repo.is_tool_in_recycle_bin_record(tool_name=candidate)
            if in_recycle:
                version += 1
                continue

            log.info(f"Resolved name conflict: '{tool_name}' -> '{candidate}'")
            return {"action": "rename", "name": candidate}

        raise ValueError(f"Could not resolve name conflict for '{tool_name}' after 100 attempts")

    @staticmethod
    def _normalize_code(code: str) -> str:
        """Normalize code for comparison by stripping whitespace variations."""
        return code.strip().replace("\r\n", "\n").replace("\r", "\n")

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
        Applies _V1/_V2 suffix for name conflicts.
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

        return {
            "message": f"Import complete. {len(imported)} imported, {len(skipped)} skipped (already exist), {len(failed)} failed.",
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
        - If found in recycle bin only: rename with _V1, _V2, etc.
        - If found in normal table:
            - Same config (url/headers/code_content/module_name): skip.
            - Different config: rename with _V1, _V2, etc.

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
        Find the next available name (_V1, _V2, ...) for an MCP tool,
        also checking if any versioned name has identical config (skip if so).
        Department-scoped to match UNIQUE(tool_name, department_name) constraint.
        """
        version = 1
        while version <= 100:
            candidate = f"{tool_name}_V{version}"

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
                version += 1
                continue

            in_recycle = await self.mcp_tool_service.recycle_mcp_tool_repo.is_mcp_tool_in_recycle_bin_record(tool_name=candidate)
            if in_recycle:
                version += 1
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
            return existing_module == incoming_module

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

