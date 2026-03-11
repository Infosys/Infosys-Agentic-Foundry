import os
import io
import ast
import json
import hashlib
import zipfile
import tempfile
import shutil
from datetime import datetime, timezone
from typing import Dict, List, Any, Optional

from src.database.services import ToolService, AgentService, McpToolService, TagService
from src.config.constants import AgentType
from telemetry_wrapper import logger as log


class AgentImporter:
    """
    Handles importing agents (and their associated tools, MCP servers, worker agents,
    and user-uploaded files) from an exported agent ZIP file.

    Conflict-resolution rules
    -------------------------
    1. **ID check first** — if the agent/tool/MCP ID already exists in the normal
       table or the recycle-bin table the entry is **skipped**.
    2. **Name check second** — if the ID is new but a record with the same *name*
       exists (normal table or recycle-bin), the name is suffixed with ``_V1``,
       ``_V2``, … until an available name is found.
    3. **File uploads** — if a file with the same name exists and the content is
       identical it is skipped; if the content differs the file is renamed with
       ``_V1`` / ``_V2`` and every occurrence of the old filename inside non-skipped
       tool code and agent/worker-agent system prompts is replaced.
    """

    def __init__(
        self,
        tool_service: ToolService,
        agent_service: AgentService,
        mcp_tool_service: McpToolService,
        tag_service: TagService,
        created_by: str,
    ):
        self.tool_service = tool_service
        self.agent_service = agent_service
        self.mcp_tool_service = mcp_tool_service
        self.tag_service = tag_service
        self.created_by = created_by

    # ===================================================================== #
    #                         PUBLIC ENTRY POINT                            #
    # ===================================================================== #

    async def import_from_zip(self, zip_buffer: io.BytesIO) -> Dict[str, Any]:
        """
        Import agents and all dependencies from an exported ZIP file.

        Returns a detailed summary dict keyed by entity type, each containing
        ``imported``, ``skipped``, ``renamed``, and ``failed`` lists.
        """
        result: Dict[str, Any] = {
            "files":          {"imported": [], "skipped": [], "renamed": [], "failed": []},
            "mcp_tools":      {"imported": [], "skipped": [], "renamed": [], "failed": []},
            "tools":          {"imported": [], "skipped": [], "renamed": [], "failed": []},
            "worker_agents":  {"imported": [], "skipped": [], "renamed": [], "failed": []},
            "agents":         {"imported": [], "skipped": [], "renamed": [], "failed": []},
        }

        with tempfile.TemporaryDirectory() as temp_dir:
            # 1. Extract ZIP
            try:
                with zipfile.ZipFile(zip_buffer, 'r') as zf:
                    zf.extractall(temp_dir)
            except zipfile.BadZipFile as e:
                raise ValueError(f"Invalid ZIP file: {e}")

            # 2. Locate Agent_Backend folder
            backend_dir = self._find_agent_backend(temp_dir)
            if not backend_dir:
                raise ValueError(
                    "Invalid export ZIP: Could not locate an 'Agent_Backend' folder."
                )

            # 3. Parse config files
            agents_data = self._parse_config_file(
                os.path.join(backend_dir, 'agent_config.py'), 'agent_data'
            )
            tools_data = self._parse_config_file(
                os.path.join(backend_dir, 'tools_config.py'), 'tools_data'
            )
            worker_agents_data = self._parse_config_file(
                os.path.join(backend_dir, 'worker_agents_config.py'), 'worker_agents'
            )

            # 4. Read actual tool code from tools_codes/*.py
            self._load_tool_codes(backend_dir, tools_data)

            # 5. Resolve & import user-uploaded files ── FIRST
            uploads_dir = os.path.join(backend_dir, 'user_uploads')
            file_renames: Dict[str, str] = {}
            if os.path.exists(uploads_dir):
                file_renames = await self._resolve_and_import_files(uploads_dir, result)

            # 6. Apply file renames to tool code + agent / worker-agent prompts
            if file_renames:
                self._apply_file_renames_to_data(tools_data, file_renames, update_code=True)
                self._apply_file_renames_to_data(agents_data, file_renames, update_code=False)
                self._apply_file_renames_to_data(worker_agents_data, file_renames, update_code=False)

            # 7. Split tools into MCP vs regular
            mcp_prefixes = ('mcp_file_', 'mcp_url_', 'mcp_module_')
            mcp_data = {
                k: v for k, v in tools_data.items() if k.startswith(mcp_prefixes)
            }
            regular_tools = {
                k: v for k, v in tools_data.items() if not k.startswith(mcp_prefixes)
            }

            # 8. Import MCP tools
            await self._import_mcp_tools(mcp_data, result)

            # 9. Import regular tools
            await self._import_regular_tools(regular_tools, result)

            # 10. Import worker agents (must come before meta agents)
            await self._import_agents_batch(worker_agents_data, result, label="worker_agents")

            # 11. Import agents
            await self._import_agents_batch(agents_data, result, label="agents")

        # Build a human-readable summary
        result["summary"] = self._build_summary(result)
        return result

    # ===================================================================== #
    #                     ZIP / CONFIG PARSING HELPERS                       #
    # ===================================================================== #

    @staticmethod
    def _find_agent_backend(root: str) -> Optional[str]:
        """Walk the extracted tree and return the first ``Agent_Backend`` dir."""
        for dirpath, dirnames, _ in os.walk(root):
            if 'Agent_Backend' in dirnames:
                return os.path.join(dirpath, 'Agent_Backend')
        return None

    @staticmethod
    def _parse_config_file(file_path: str, var_name: str) -> Dict[str, Any]:
        """
        Parse a Python config file that looks like ``var_name = { ... }``.

        Returns the parsed dict or an empty dict on failure.
        """
        if not os.path.exists(file_path):
            log.warning(f"Config file not found: {file_path}")
            return {}

        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()

            prefix = f"{var_name} = "
            idx = content.find(prefix)
            if idx == -1:
                log.warning(f"Variable '{var_name}' not found in {file_path}")
                return {}

            json_str = content[idx + len(prefix):]
            return json.loads(json_str)
        except Exception as e:
            log.error(f"Error parsing config file {file_path}: {e}")
            return {}

    @staticmethod
    def _load_tool_codes(backend_dir: str, tools_data: Dict[str, Any]):
        """
        Replace the ``code_snippet`` field (which is a file path like
        ``tools_codes/my_tool.py``) with the actual file content.
        """
        for tool_id, tool_info in tools_data.items():
            if tool_info is None:
                continue
            if tool_id.startswith(('mcp_file_', 'mcp_url_', 'mcp_module_')):
                continue  # MCP tools have mcp_config, not code files

            code_ref = tool_info.get('code_snippet', '')
            if not code_ref:
                continue

            # If code_snippet already looks like actual code, skip
            stripped = code_ref.strip()
            if stripped.startswith('def ') or stripped.startswith('async def ') or stripped.startswith('import ') or stripped.startswith('from '):
                continue

            # Treat it as a relative path
            full_path = os.path.join(backend_dir, code_ref)
            if os.path.exists(full_path):
                with open(full_path, 'r', encoding='utf-8') as f:
                    tool_info['code_snippet'] = f.read()
            else:
                log.warning(f"Tool code file not found: {full_path} (tool_id={tool_id})")

    # ===================================================================== #
    #                    FILE CONFLICT RESOLUTION                           #
    # ===================================================================== #

    async def _resolve_and_import_files(
        self, uploads_dir: str, result: Dict
    ) -> Dict[str, str]:
        """
        Walk through the exported ``user_uploads`` folder, compare each file
        with what already exists on the server, and import / rename / skip.

        Returns ``{old_relative_path: new_relative_path}`` for every renamed file.
        """
        target_uploads = os.path.join(os.getcwd(), 'user_uploads')
        os.makedirs(target_uploads, exist_ok=True)
        file_renames: Dict[str, str] = {}

        for dirpath, _, filenames in os.walk(uploads_dir):
            for filename in filenames:
                src_file = os.path.join(dirpath, filename)
                rel_path = os.path.relpath(src_file, uploads_dir)  # e.g. "report.pdf" or "sub/report.pdf"
                target_file = os.path.join(target_uploads, rel_path)

                try:
                    if os.path.exists(target_file):
                        if self._files_are_identical(src_file, target_file):
                            result["files"]["skipped"].append({
                                "file": rel_path,
                                "message": "Identical file already exists. Skipped.",
                            })
                            continue
                        else:
                            # Different content → rename
                            new_rel = self._find_available_filename(rel_path, target_uploads)
                            new_target = os.path.join(target_uploads, new_rel)
                            os.makedirs(os.path.dirname(new_target), exist_ok=True)
                            shutil.copy2(src_file, new_target)
                            file_renames[rel_path] = new_rel
                            result["files"]["renamed"].append({
                                "original": rel_path,
                                "renamed_to": new_rel,
                                "message": "File renamed (different content with same name).",
                            })
                    else:
                        # No conflict → copy
                        os.makedirs(os.path.dirname(target_file), exist_ok=True)
                        shutil.copy2(src_file, target_file)
                        result["files"]["imported"].append({
                            "file": rel_path,
                            "message": "File imported successfully.",
                        })
                except Exception as e:
                    log.error(f"Error importing file '{rel_path}': {e}")
                    result["files"]["failed"].append({
                        "file": rel_path,
                        "message": str(e),
                    })

        return file_renames

    @staticmethod
    def _files_are_identical(file1: str, file2: str) -> bool:
        """Compare two files by SHA-256 hash."""
        def _sha256(path: str) -> str:
            h = hashlib.sha256()
            with open(path, 'rb') as f:
                for chunk in iter(lambda: f.read(8192), b''):
                    h.update(chunk)
            return h.hexdigest()
        return _sha256(file1) == _sha256(file2)

    @staticmethod
    def _find_available_filename(rel_path: str, target_dir: str) -> str:
        """Return ``name_V1.ext``, ``name_V2.ext``, … until available."""
        base, ext = os.path.splitext(rel_path)
        version = 1
        while version <= 100:
            candidate = f"{base}_V{version}{ext}"
            if not os.path.exists(os.path.join(target_dir, candidate)):
                return candidate
            version += 1
        raise ValueError(
            f"Could not resolve file name conflict for '{rel_path}' after 100 attempts."
        )

    # ===================================================================== #
    #               APPLY FILE RENAMES TO CODE / PROMPTS                    #
    # ===================================================================== #

    @staticmethod
    def _apply_file_renames_to_data(
        data: Dict[str, Any],
        file_renames: Dict[str, str],
        update_code: bool,
    ):
        """
        Replace old file references with new ones in tool ``code_snippet``
        and / or ``system_prompt`` fields.

        ``file_renames`` maps e.g. ``"report.pdf" → "report_V1.pdf"``.
        Both the bare filename and common prefixed forms
        (``user_uploads/…``, ``__files__/…``) are handled.
        """
        if not data or not file_renames:
            return

        for _item_id, item_data in data.items():
            if item_data is None:
                continue

            # Build search/replace pairs covering common path patterns
            replacements: List[tuple] = []
            for old_rel, new_rel in file_renames.items():
                old_name = os.path.basename(old_rel)
                new_name = os.path.basename(new_rel)
                # Use the full relative path variants so we don't accidentally
                # replace a substring of some unrelated word.
                replacements.append((f"user_uploads/{old_rel}", f"user_uploads/{new_rel}"))
                replacements.append((f"__files__/{old_rel}", f"__files__/{new_rel}"))
                # Also handle bare filename references (e.g. in prompts)
                # Only replace if the bare name hasn't been covered above
                if old_name != old_rel:
                    replacements.append((old_name, new_name))
                else:
                    # old_rel IS the bare name already; still add it as last-resort
                    replacements.append((old_rel, new_rel))

            # -- Tool code --
            if update_code and 'code_snippet' in item_data:
                code = item_data['code_snippet']
                if isinstance(code, str):
                    for old, new in replacements:
                        code = code.replace(old, new)
                    item_data['code_snippet'] = code

            # -- System prompt --
            if 'system_prompt' in item_data:
                prompt = item_data['system_prompt']
                if isinstance(prompt, dict):
                    prompt_str = json.dumps(prompt)
                    for old, new in replacements:
                        prompt_str = prompt_str.replace(old, new)
                    item_data['system_prompt'] = json.loads(prompt_str)
                elif isinstance(prompt, list):
                    prompt_str = json.dumps(prompt)
                    for old, new in replacements:
                        prompt_str = prompt_str.replace(old, new)
                    item_data['system_prompt'] = json.loads(prompt_str)
                elif isinstance(prompt, str):
                    for old, new in replacements:
                        prompt = prompt.replace(old, new)
                    item_data['system_prompt'] = prompt

    # ===================================================================== #
    #                  ID / NAME EXISTENCE CHECKS                           #
    # ===================================================================== #

    async def _check_id_exists_tool(self, tool_id: str) -> bool:
        """Return ``True`` if ``tool_id`` exists in tool_table or recycle_tool."""
        existing = await self.tool_service.tool_repo.get_tool_record(tool_id=tool_id)
        if existing:
            return True
        return await self.tool_service.recycle_tool_repo.is_tool_in_recycle_bin_record(
            tool_id=tool_id
        )

    async def _check_id_exists_mcp(self, tool_id: str) -> bool:
        """Return ``True`` if ``tool_id`` exists in mcp_tool_table or recycle_mcp_tool."""
        existing = await self.mcp_tool_service.mcp_tool_repo.get_mcp_tool_record(
            tool_id=tool_id
        )
        if existing:
            return True
        return await self.mcp_tool_service.recycle_mcp_tool_repo.is_mcp_tool_in_recycle_bin_record(
            tool_id=tool_id
        )

    async def _check_id_exists_agent(self, agent_id: str) -> bool:
        """Return ``True`` if ``agent_id`` exists in agent_table or recycle_agent."""
        existing = await self.agent_service.agent_repo.get_agent_record(
            agentic_application_id=agent_id
        )
        if existing:
            return True
        return await self.agent_service.recycle_agent_repo.is_agent_in_recycle_bin_record(
            agentic_application_id=agent_id
        )

    # ===================================================================== #
    #               NAME CONFLICT RESOLUTION (_V1, _V2, …)                 #
    # ===================================================================== #

    async def _find_available_tool_name(self, tool_name: str) -> str:
        """Return ``tool_name_V1``, ``_V2``, … checking both tables."""
        version = 1
        while version <= 100:
            candidate = f"{tool_name}_V{version}"
            existing = await self.tool_service.tool_repo.get_tool_record(tool_name=candidate)
            if existing:
                version += 1
                continue
            in_recycle = await self.tool_service.recycle_tool_repo.is_tool_in_recycle_bin_record(
                tool_name=candidate
            )
            if in_recycle:
                version += 1
                continue
            return candidate
        raise ValueError(
            f"Could not find available name for tool '{tool_name}' after 100 attempts."
        )

    async def _find_available_mcp_name(self, tool_name: str) -> str:
        """Return ``tool_name_V1``, ``_V2``, … checking both tables."""
        version = 1
        while version <= 100:
            candidate = f"{tool_name}_V{version}"
            existing = await self.mcp_tool_service.mcp_tool_repo.get_mcp_tool_record(
                tool_name=candidate
            )
            if existing:
                version += 1
                continue
            in_recycle = await self.mcp_tool_service.recycle_mcp_tool_repo.is_mcp_tool_in_recycle_bin_record(
                tool_name=candidate
            )
            if in_recycle:
                version += 1
                continue
            return candidate
        raise ValueError(
            f"Could not find available name for MCP tool '{tool_name}' after 100 attempts."
        )

    async def _find_available_agent_name(self, agent_name: str) -> str:
        """Return ``agent_name_V1``, ``_V2``, … checking both tables."""
        version = 1
        while version <= 100:
            candidate = f"{agent_name}_V{version}"
            existing = await self.agent_service.agent_repo.get_agent_record(
                agentic_application_name=candidate
            )
            if existing:
                version += 1
                continue
            in_recycle = await self.agent_service.recycle_agent_repo.is_agent_in_recycle_bin_record(
                agentic_application_name=candidate
            )
            if in_recycle:
                version += 1
                continue
            return candidate
        raise ValueError(
            f"Could not find available name for agent '{agent_name}' after 100 attempts."
        )

    # ===================================================================== #
    #                       IMPORT REGULAR TOOLS                            #
    # ===================================================================== #

    async def _import_regular_tools(
        self, tools_data: Dict[str, Any], result: Dict
    ):
        """Import regular (non-MCP) tools with ID-first, name-second conflict checks."""
        for tool_id, tool_info in tools_data.items():
            if tool_info is None:
                result["tools"]["failed"].append({
                    "tool_id": tool_id,
                    "message": "Tool data is null in export.",
                })
                continue

            tool_name = tool_info.get('tool_name', '')
            original_name = tool_name

            try:
                # ── Step 1: ID check ──
                if await self._check_id_exists_tool(tool_id):
                    result["tools"]["skipped"].append({
                        "tool_id": tool_id,
                        "tool_name": tool_name,
                        "message": f"Tool ID '{tool_id}' already exists in the server. Skipping.",
                    })
                    continue

                # ── Step 2: Name check ──
                existing_by_name = await self.tool_service.tool_repo.get_tool_record(
                    tool_name=tool_name
                )
                name_in_recycle = await self.tool_service.recycle_tool_repo.is_tool_in_recycle_bin_record(
                    tool_name=tool_name
                )
                if existing_by_name or name_in_recycle:
                    tool_name = await self._find_available_tool_name(original_name)
                    log.info(f"Tool name conflict resolved: '{original_name}' -> '{tool_name}'")

                    # Rename the function definition inside the code
                    code = tool_info.get('code_snippet', '')
                    if code:
                        renamed = self._rename_function_in_code(code, original_name, tool_name)
                        if renamed:
                            tool_info['code_snippet'] = renamed

                    result["tools"]["renamed"].append({
                        "tool_id": tool_id,
                        "original_name": original_name,
                        "new_name": tool_name,
                        "message": f"Tool renamed from '{original_name}' to '{tool_name}'.",
                    })

                # ── Step 3: Save ──
                now = datetime.now(timezone.utc).replace(tzinfo=None)
                tool_data = {
                    "tool_id": tool_id,
                    "tool_name": tool_name,
                    "tool_description": tool_info.get('tool_description', ''),
                    "code_snippet": tool_info.get('code_snippet', ''),
                    "model_name": tool_info.get('model_name', ''),
                    "created_by": self.created_by,
                    "created_on": now,
                }

                success = await self.tool_service.tool_repo.save_tool_record(tool_data)
                if success:
                    # Assign "General" tag
                    await self._assign_general_tag_to_tool(tool_id)

                    if tool_name == original_name:
                        result["tools"]["imported"].append({
                            "tool_id": tool_id,
                            "tool_name": tool_name,
                            "message": "Tool imported successfully.",
                        })
                else:
                    result["tools"]["failed"].append({
                        "tool_id": tool_id,
                        "tool_name": tool_name,
                        "message": "Failed to save tool record (possible unique violation).",
                    })

            except Exception as e:
                log.error(f"Error importing tool '{tool_id}' ({tool_name}): {e}")
                result["tools"]["failed"].append({
                    "tool_id": tool_id,
                    "tool_name": tool_name,
                    "message": str(e),
                })

    # ===================================================================== #
    #                        IMPORT MCP TOOLS                               #
    # ===================================================================== #

    async def _import_mcp_tools(self, mcp_data: Dict[str, Any], result: Dict):
        """Import MCP tools with ID-first, name-second conflict checks."""
        for tool_id, tool_info in mcp_data.items():
            if tool_info is None:
                result["mcp_tools"]["failed"].append({
                    "tool_id": tool_id,
                    "message": "MCP tool data is null in export.",
                })
                continue

            tool_name = tool_info.get('tool_name', '')
            original_name = tool_name

            try:
                # ── Step 1: ID check ──
                if await self._check_id_exists_mcp(tool_id):
                    result["mcp_tools"]["skipped"].append({
                        "tool_id": tool_id,
                        "tool_name": tool_name,
                        "message": f"MCP tool ID '{tool_id}' already exists in the server. Skipping.",
                    })
                    continue

                # ── Step 2: Name check ──
                existing_by_name = await self.mcp_tool_service.mcp_tool_repo.get_mcp_tool_record(
                    tool_name=tool_name
                )
                name_in_recycle = await self.mcp_tool_service.recycle_mcp_tool_repo.is_mcp_tool_in_recycle_bin_record(
                    tool_name=tool_name
                )
                if existing_by_name or name_in_recycle:
                    tool_name = await self._find_available_mcp_name(original_name)
                    log.info(f"MCP tool name conflict resolved: '{original_name}' -> '{tool_name}'")
                    result["mcp_tools"]["renamed"].append({
                        "tool_id": tool_id,
                        "original_name": original_name,
                        "new_name": tool_name,
                        "message": f"MCP tool renamed from '{original_name}' to '{tool_name}'.",
                    })

                # ── Step 3: Save ──
                now = datetime.now(timezone.utc).replace(tzinfo=None)

                mcp_config = tool_info.get('mcp_config', {})
                if isinstance(mcp_config, str):
                    mcp_config = json.loads(mcp_config)

                mcp_tool_data = {
                    "tool_id": tool_id,
                    "tool_name": tool_name,
                    "tool_description": tool_info.get('tool_description', ''),
                    "mcp_config": mcp_config,
                    "is_public": tool_info.get('is_public', False),
                    "status": "pending",
                    "comments": None,
                    "approved_at": None,
                    "approved_by": None,
                    "created_by": self.created_by,
                    "created_on": now,
                    "updated_on": now,
                }

                success = await self.mcp_tool_service.mcp_tool_repo.save_mcp_tool_record(
                    mcp_tool_data
                )
                if success:
                    await self._assign_general_tag_to_tool(tool_id)

                    if tool_name == original_name:
                        result["mcp_tools"]["imported"].append({
                            "tool_id": tool_id,
                            "tool_name": tool_name,
                            "message": "MCP tool imported successfully.",
                        })
                else:
                    result["mcp_tools"]["failed"].append({
                        "tool_id": tool_id,
                        "tool_name": tool_name,
                        "message": "Failed to save MCP tool record.",
                    })

            except Exception as e:
                log.error(f"Error importing MCP tool '{tool_id}' ({tool_name}): {e}")
                result["mcp_tools"]["failed"].append({
                    "tool_id": tool_id,
                    "tool_name": tool_name,
                    "message": str(e),
                })

    # ===================================================================== #
    #                  IMPORT AGENTS / WORKER AGENTS                        #
    # ===================================================================== #

    async def _import_agents_batch(
        self,
        agents_data: Dict[str, Any],
        result: Dict,
        label: str,
    ):
        """
        Import a batch of agents (or worker agents).

        ``label`` is ``"agents"`` or ``"worker_agents"`` — it determines which
        key in ``result`` receives the status entries.
        """
        meta_type_values = [at.value for at in AgentType.meta_types()]

        for agent_id, agent_info in agents_data.items():
            if agent_info is None:
                result[label]["failed"].append({
                    "agent_id": agent_id,
                    "message": "Agent data is null in export.",
                })
                continue

            agent_name = agent_info.get('agentic_application_name', '')
            original_name = agent_name

            try:
                # ── Step 1: ID check ──
                if await self._check_id_exists_agent(agent_id):
                    result[label]["skipped"].append({
                        "agent_id": agent_id,
                        "agent_name": agent_name,
                        "message": f"Agent ID '{agent_id}' already exists in the server. Skipping.",
                    })
                    continue

                # ── Step 2: Name check ──
                existing_by_name = await self.agent_service.agent_repo.get_agent_record(
                    agentic_application_name=agent_name
                )
                name_in_recycle = await self.agent_service.recycle_agent_repo.is_agent_in_recycle_bin_record(
                    agentic_application_name=agent_name
                )
                if existing_by_name or name_in_recycle:
                    agent_name = await self._find_available_agent_name(original_name)
                    log.info(f"Agent name conflict resolved: '{original_name}' -> '{agent_name}'")
                    result[label]["renamed"].append({
                        "agent_id": agent_id,
                        "original_name": original_name,
                        "new_name": agent_name,
                        "message": f"Agent renamed from '{original_name}' to '{agent_name}'.",
                    })

                # ── Step 3: Build & save agent record ──
                now = datetime.now(timezone.utc).replace(tzinfo=None)

                system_prompt = agent_info.get('system_prompt', {})
                if isinstance(system_prompt, (dict, list)):
                    system_prompt = json.dumps(system_prompt)

                tools_id = agent_info.get('tools_id', [])
                if isinstance(tools_id, list):
                    tools_id = json.dumps(tools_id)

                validation_criteria = agent_info.get('validation_criteria', [])
                if isinstance(validation_criteria, (list, dict)):
                    validation_criteria = json.dumps(validation_criteria)

                agent_data = {
                    "agentic_application_id": agent_id,
                    "agentic_application_name": agent_name,
                    "agentic_application_description": agent_info.get('agentic_application_description', ''),
                    "agentic_application_workflow_description": agent_info.get('agentic_application_workflow_description', ''),
                    "agentic_application_type": agent_info.get('agentic_application_type', ''),
                    "model_name": agent_info.get('model_name', ''),
                    "system_prompt": system_prompt,
                    "tools_id": tools_id,
                    "created_by": self.created_by,
                    "created_on": now,
                    "updated_on": now,
                    "validation_criteria": validation_criteria,
                    "welcome_message": agent_info.get('welcome_message', 'Hello, how can I help you?'),
                }

                success = await self.agent_service.agent_repo.save_agent_record(agent_data)
                if success:
                    # ── Create tool-agent mappings ──
                    tools_list = json.loads(agent_data["tools_id"])
                    is_meta = agent_info.get('agentic_application_type', '') in meta_type_values

                    for associated_id in tools_list:
                        try:
                            associated_created_by = None
                            if is_meta:
                                worker = await self.agent_service.get_agent(
                                    agentic_application_id=associated_id
                                )
                                associated_created_by = worker[0]["created_by"] if worker else None
                            else:
                                tool = await self.tool_service.get_tool(tool_id=associated_id)
                                associated_created_by = tool[0]["created_by"] if tool else None

                            if associated_created_by:
                                await self.tool_service.tool_agent_mapping_repo.assign_tool_to_agent_record(
                                    tool_id=associated_id,
                                    agentic_application_id=agent_id,
                                    tool_created_by=associated_created_by,
                                    agentic_app_created_by=self.created_by,
                                )
                        except Exception as mapping_err:
                            log.warning(
                                f"Could not create mapping for {associated_id} -> {agent_id}: {mapping_err}"
                            )

                    # ── Assign "General" tag ──
                    general_tag = await self.tag_service.get_tag(tag_name="General")
                    if general_tag:
                        await self.tag_service.assign_tags_to_agent(
                            tag_ids=[general_tag['tag_id']],
                            agentic_application_id=agent_id,
                        )

                    if agent_name == original_name:
                        result[label]["imported"].append({
                            "agent_id": agent_id,
                            "agent_name": agent_name,
                            "message": "Agent imported successfully.",
                        })
                else:
                    result[label]["failed"].append({
                        "agent_id": agent_id,
                        "agent_name": agent_name,
                        "message": "Failed to save agent record (possible unique violation).",
                    })

            except Exception as e:
                log.error(f"Error importing agent '{agent_id}' ({agent_name}): {e}")
                result[label]["failed"].append({
                    "agent_id": agent_id,
                    "agent_name": agent_name,
                    "message": str(e),
                })

    # ===================================================================== #
    #                     TAG ASSIGNMENT HELPER                             #
    # ===================================================================== #

    async def _assign_general_tag_to_tool(self, tool_id: str):
        """Assign the 'General' tag to a tool (regular or MCP)."""
        try:
            general_tag = await self.tag_service.get_tag(tag_name="General")
            if general_tag:
                await self.tag_service.assign_tags_to_tool(
                    tag_ids=[general_tag['tag_id']],
                    tool_id=tool_id,
                )
        except Exception as e:
            log.warning(f"Could not assign 'General' tag to tool '{tool_id}': {e}")

    # ===================================================================== #
    #                   AST-BASED FUNCTION RENAMING                         #
    # ===================================================================== #

    @staticmethod
    def _rename_function_in_code(
        code: str, old_name: str, new_name: str
    ) -> Optional[str]:
        """
        Use the AST to rename the top-level function definition from
        ``old_name`` to ``new_name``. Returns the modified source or
        ``None`` on failure.
        """
        try:
            tree = ast.parse(code)
            for node in tree.body:
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    if node.name == old_name:
                        node.name = new_name
                        break
            return ast.unparse(tree)
        except Exception as e:
            log.error(f"Error renaming function '{old_name}' to '{new_name}': {e}")
            return None

    # ===================================================================== #
    #                         RESULT SUMMARY                                #
    # ===================================================================== #

    @staticmethod
    def _build_summary(result: Dict[str, Any]) -> Dict[str, Any]:
        """Create a concise summary from the detailed result dict."""
        summary: Dict[str, Any] = {}
        for category in ("files", "mcp_tools", "tools", "worker_agents", "agents"):
            cat = result.get(category, {})
            summary[category] = {
                "imported": len(cat.get("imported", [])),
                "skipped": len(cat.get("skipped", [])),
                "renamed": len(cat.get("renamed", [])),
                "failed": len(cat.get("failed", [])),
            }
        return summary
