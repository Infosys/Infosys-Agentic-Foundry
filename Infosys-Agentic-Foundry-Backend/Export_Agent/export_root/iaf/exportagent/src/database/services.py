import re
import json
import uuid
import inspect
from datetime import datetime, timezone
import pandas as pd
import os
from typing import List, Optional, Union, Dict, Any,Literal
import shutil
from langchain_core.tools import BaseTool, StructuredTool
from langchain_core.prompts import PromptTemplate
from langchain_core.output_parsers import StrOutputParser
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage, ChatMessage, AnyMessage
from copy import deepcopy
from fastapi import UploadFile
from langchain_mcp_adapters.client import MultiServerMCPClient
from exportagent.src.database.repositories import McpToolRepository ,AgentRepository,ToolRepository,ChatHistoryRepository,EvaluationDataRepository,ToolEvaluationMetricsRepository,AgentEvaluationMetricsRepository,FeedbackLearningRepository
from exportagent.src.prompts.prompts import CONVERSATION_SUMMARY_PROMPT
from exportagent.src.models.model_service import ModelService
from exportagent.telemetry_wrapper import logger as log, update_session_context
class McpToolService:
    """
    Service layer for managing MCP tools (server definitions).
    Handles business rules, file management for code-based MCPs,
    and orchestrates repository calls.
    """

    def __init__(
        self,
        mcp_tool_repo: McpToolRepository,
        agent_repo: AgentRepository, # Needed for dependency checks
        mcp_runtime_files_dir: str = "mcp_runtime_files"
    ):
        import os
        self.mcp_tool_repo = mcp_tool_repo
        self.agent_repo = agent_repo
        self.mcp_runtime_files_dir = mcp_runtime_files_dir
        os.makedirs(self.mcp_runtime_files_dir, exist_ok=True) # Ensure dir exists on init

    # --- Helper Methods for File Management ---

    @staticmethod
    async def _generate_mcp_file_name(tool_name: str, tool_id: str) -> str:
        """
        Generates a standardized filename for an MCP server code file.

        Args:
            tool_name (str): The name of the tool.
            tool_id (str): The ID of the tool.

        Returns:
            str: The generated filename.
        """
        filename_base = re.sub(r'[^a-zA-Z0-9_]', '_', tool_name).lower()
        tool_id = tool_id.replace("-", "_")
        return f"{filename_base}_{tool_id}.py"

    async def _write_mcp_file_to_runtime_dir(self, filename: str, code_content: str) -> str:
        """
        Writes the Python code content for an MCP server to a file in the runtime directory.
        Returns the full path to the created file.
        """
        os.makedirs(self.mcp_runtime_files_dir, exist_ok=True) # Ensure dir exists
        file_path = os.path.join(self.mcp_runtime_files_dir, filename)
        try:
            with open(file_path, "w", encoding="utf-8") as f:
                f.write(code_content)
            log.info(f"MCP server code written to: {file_path}")
            return file_path
        except Exception as e:
            log.error(f"Error writing MCP server code to {file_path}: {e}")
            raise

    async def _delete_mcp_file_from_runtime_dir(self, filename: str) -> bool:
        """
        Deletes a specific MCP server code file from the runtime directory.
        """
        file_path = os.path.join(self.mcp_runtime_files_dir, filename)
        try:
            if os.path.exists(file_path):
                os.remove(file_path)
                log.info(f"MCP server code file deleted: {file_path}")
                return True
            log.warning(f"Attempted to delete non-existent MCP server code file: {file_path}")
            return False
        except Exception as e:
            log.error(f"Error deleting MCP server code file {file_path}: {e}")
            return False

    async def _read_uploaded_file_content(self, uploaded_file: UploadFile) -> str:
        """
        Reads content from an uploaded FastAPI UploadFile and normalizes newlines.
        """
        try:
            content_bytes = await uploaded_file.read()
            content_str = content_bytes.decode("utf-8")
            
            # Normalize newlines: Replace all Windows-style (\r\n) and old Mac-style (\r)
            # newlines with Unix-style (\n) newlines.
            # Then, ensure no double newlines are present if they were introduced.
            normalized_content = content_str.replace('\r\n', '\n').replace('\r', '\n')
            return normalized_content

        except Exception as e:
            log.error(f"Error reading and normalizing uploaded file content: {e}")
            raise

    # --- Lifecycle Management for MCP Runtime Directory ---

    async def create_mcp_runtime_directory_on_startup(self):
        """
        Ensures the MCP runtime directory exists and populates it with files
        for all 'mcp_file_' type tools from the database.
        This method should be called during application startup.
        """
        os.makedirs(self.mcp_runtime_files_dir, exist_ok=True)
        log.info(f"Ensured MCP runtime directory exists: {self.mcp_runtime_files_dir}")

        all_mcp_tools = await self.mcp_tool_repo.get_all_mcp_tool_records()
        for tool_data in all_mcp_tools:
            if tool_data["tool_id"].startswith("mcp_file_"):
                mcp_config = json.loads(tool_data["mcp_config"])
                code_content = mcp_config.get("code_content")
                if code_content:
                    # Filename will be tool_name_tool_id.py
                    filename = await self._generate_mcp_file_name(tool_name=tool_data["tool_name"], tool_id=tool_data["tool_id"])
                    await self._write_mcp_file_to_runtime_dir(filename, code_content)
                else:
                    log.warning(f"MCP file tool '{tool_data['tool_name']}' ({tool_data['tool_id']}) has no 'code_content' in mcp_config.")

    async def cleanup_mcp_runtime_directory_on_shutdown(self):
        """
        Deletes the entire MCP runtime directory and its contents.
        This method should be called during application shutdown.
        """
        try:
            if os.path.exists(self.mcp_runtime_files_dir):
                shutil.rmtree(self.mcp_runtime_files_dir)
                log.info(f"Cleaned up MCP runtime directory: {self.mcp_runtime_files_dir}")
            else:
                log.info(f"MCP runtime directory does not exist, no cleanup needed: {self.mcp_runtime_files_dir}")
        except Exception as e:
            log.error(f"Error cleaning up MCP runtime directory {self.mcp_runtime_files_dir}: {e}")

    # --- MCP Tool Creation Operations ---

    async def create_mcp_tool(
            self,
            tool_name: str,
            tool_description: str,
            mcp_type: Literal["file", "url", "module"],
            created_by: str,
            tag_ids: Optional[Union[List[str], str]] = None,
            mcp_url: Optional[str] = None,
            mcp_module_name: Optional[str] = None,
            code_content: Optional[str] = None, # For file-based MCPs
        ) -> Dict[str, Any]:
        """
        Creates a new MCP tool (server definition) and saves it to the database.
        Handles file creation for 'file' type MCPs.
        """
        # Generate tool_id with appropriate prefix
        tool_id_prefix = f"mcp_{mcp_type}_"
        tool_id = tool_id_prefix + str(uuid.uuid4())
        update_session_context(tool_id=tool_id, tool_name=tool_name)

        if await self.mcp_tool_repo.get_mcp_tool_record(tool_name=tool_name):
            log.warning(f"MCP tool with name '{tool_name}' already exists.")
            return {"message": f"MCP tool with name '{tool_name}' already exists.", "is_created": False}

        mcp_config: Dict[str, Any] = {"transport": "stdio"} # Default transport

        if mcp_type == "file":
            if not code_content:
                return {"message": "Code content is required for 'file' type MCP tools.", "is_created": False}

            # Filename will be tool_name_tool_id.py
            filename = await self._generate_mcp_file_name(tool_name=tool_name, tool_id=tool_id)
            
            # Store code_content in mcp_config for DB persistence
            mcp_config["code_content"] = code_content
            mcp_config["command"] = "python"
            mcp_config["args"] = []
            
            # Write the file to the runtime directory immediately
            await self._write_mcp_file_to_runtime_dir(filename, code_content)

        elif mcp_type == "url":
            if not mcp_url:
                return {"message": "URL is required for 'url' type MCP tools.", "is_created": False}
            mcp_config["url"] = mcp_url
            mcp_config["transport"] = "streamable_http" # URL-based typically use HTTP

        elif mcp_type == "module":
            if not mcp_module_name:
                return {"message": "Module name is required for 'module' type MCP tools.", "is_created": False}
            mcp_config["command"] = "python"
            mcp_config["args"] = ["-m", mcp_module_name]

        else:
            return {"message": f"Unsupported MCP type: {mcp_type}", "is_created": False}

        now = datetime.now(timezone.utc).replace(tzinfo=None)
        tool_data = {
            "tool_id": tool_id,
            "tool_name": tool_name,
            "tool_description": tool_description,
            "mcp_config": mcp_config,
            "is_public": False, # Default values as per schema
            "status": "pending", # Default values as per schema
            "comments": None,
            "approved_at": None,
            "approved_by": None,
            "created_by": created_by,
            "created_on": now,
            "updated_on": now
        }

        success = await self.mcp_tool_repo.save_mcp_tool_record(tool_data)

        if success:
            if not tag_ids:
                general_tag = await self.tag_service.get_tag(tag_name="General")
                tag_ids = [general_tag['tag_id']] if general_tag else []
            await self.tag_service.assign_tags_to_tool(tag_ids=tag_ids, tool_id=tool_id)

            log.info(f"Successfully onboarded MCP tool '{tool_name}' with ID: {tool_id}")
            return {"message": f"Successfully onboarded MCP tool '{tool_name}'", "tool_id": tool_id, "is_created": True}
        else:
            log.error(f"Failed to onboard MCP tool '{tool_name}'.")
            return {"message": f"Failed to onboard MCP tool '{tool_name}'.", "is_created": False}

    # --- MCP Tool Retrieval Operations ---

    async def get_mcp_tool(self, tool_id: Optional[str] = None, tool_name: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        Retrieves a single MCP tool (server definition) record by ID or name.
        """
        tool_records = await self.mcp_tool_repo.get_mcp_tool_record(tool_id=tool_id, tool_name=tool_name)
        if not tool_records:
            log.info(f"No MCP tool found with ID: {tool_id} or Name: {tool_name}.")
            return []

        # Ensure mcp_config is a Python dict (asyncpg usually handles JSONB deserialization)
        for record in tool_records:
            if isinstance(record.get("mcp_config"), str):
                record["mcp_config"] = json.loads(record["mcp_config"])
            record['tags'] = await self.tag_service.get_tags_by_tool(record['tool_id'])
        
        log.info(f"Retrieved MCP tool with ID: {tool_records[0]['tool_id']} and Name: {tool_records[0]['tool_name']}.")
        return tool_records

    async def get_all_mcp_tools(self) -> List[Dict[str, Any]]:
        """
        Retrieves all MCP tool (server definition) records with associated tags.
        """
        tool_records = await self.mcp_tool_repo.get_all_mcp_tool_records()
        tool_id_to_tags = await self.tag_service.get_tool_id_to_tags_dict()

        for tool in tool_records:
            if isinstance(tool.get("mcp_config"), str):
                tool["mcp_config"] = json.loads(tool["mcp_config"])
            tool['tags'] = tool_id_to_tags.get(tool['tool_id'], [])
        log.info(f"Retrieved {len(tool_records)} MCP tools.")
        return tool_records

    async def get_mcp_tools_by_search_or_page(self, search_value: str = '', limit: int = 20, page: int = 1) -> Dict[str, Any]:
        """
        Retrieves MCP tools (server definitions) with pagination and search filtering, including associated tags.
        """
        total_count = await self.mcp_tool_repo.get_total_mcp_tool_count(search_value)
        tool_records = await self.mcp_tool_repo.get_mcp_tools_by_search_or_page_records(search_value, limit, page)
        
        tool_id_to_tags = await self.tag_service.get_tool_id_to_tags_dict()
        for tool in tool_records:
            if isinstance(tool.get("mcp_config"), str):
                tool["mcp_config"] = json.loads(tool["mcp_config"])
            tool['tags'] = tool_id_to_tags.get(tool['tool_id'], [])

        return {
            "total_count": total_count,
            "details": tool_records
        }

    # --- MCP Tool Updation Operations ---

    async def update_mcp_tool(
        self,
        tool_id: str,
        user_id: str,
        is_admin: bool = False,
        tool_description: Optional[str] = None,
        code_content: Optional[str] = None, # Only for 'mcp_file_' type
        updated_tag_id_list: Optional[Union[List[str], str]] = None,
        is_public: Optional[bool] = None,
        status: Optional[str] = None,
        comments: Optional[str] = None,
        approved_at: Optional[datetime] = None,
        approved_by: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Updates an existing MCP tool (server definition) record.
        Only allows 'code_content' updates for 'mcp_file_' type tools.
        """
        tool_records = await self.mcp_tool_repo.get_mcp_tool_record(tool_id=tool_id)
        if not tool_records:
            log.error(f"Error: MCP tool not found with ID: {tool_id}")
            return {"status_message": f"Error: MCP tool not found with ID: {tool_id}", "is_update": False}
        
        tool_data = tool_records[0]

        if not is_admin and tool_data["created_by"] != user_id:
            err = f"Permission denied: Only the admin or the tool's creator can perform this action for MCP Tool ID: {tool_id}."
            log.error(err)
            return {"status_message": err, "is_update": False}

        # Check if any actual updates are requested
        if not any([tool_description, code_content, updated_tag_id_list,
                    is_public is not None, status, comments, approved_at, approved_by]):
            return {"status_message": "No fields provided to update the MCP tool.", "is_update": False}

        update_payload: Dict[str, Any] = {"updated_on": datetime.now(timezone.utc).replace(tzinfo=None)}
        
        # Update basic metadata
        if tool_description:
            update_payload["tool_description"] = tool_description.strip()
        if is_public is not None:
            update_payload["is_public"] = is_public
        if status:
            update_payload["status"] = status
        if comments:
            update_payload["comments"] = comments
        if approved_at:
            update_payload["approved_at"] = approved_at
        if approved_by:
            update_payload["approved_by"] = approved_by

        # Handle tags update
        if updated_tag_id_list:
            await self.tag_service.clear_tags(tool_id=tool_id)
            await self.tag_service.assign_tags_to_tool(tag_ids=updated_tag_id_list, tool_id=tool_id)
            log.info(f"Tags updated for MCP tool ID: {tool_id}")

        # Handle code_content update for 'mcp_file_' type only
        if tool_id.startswith("mcp_file_"):
            if code_content:
                if isinstance(tool_data.get("mcp_config"), str):
                    tool_data["mcp_config"] = json.loads(tool_data["mcp_config"])
                mcp_config = tool_data["mcp_config"] # Get current config
                mcp_config["code_content"] = code_content.strip() # Update code content
                
                # Regenerate file in runtime directory
                filename = await self._generate_mcp_file_name(tool_name=tool_data["tool_name"], tool_id=tool_id)
                await self._write_mcp_file_to_runtime_dir(filename, code_content)
                
                update_payload["mcp_config"] = mcp_config # Add updated config to payload
                log.info(f"Code content updated for MCP file tool ID: {tool_id}")
        else:
            if code_content: # If code_content is provided for non-file type, reject
                return {"status_message": "Code content can only be updated for 'file' type MCP tools.", "is_update": False}
            # For URL/Module types, mcp_config (URL/module name) is not editable
            # If mcp_config was passed in payload, it would be ignored or rejected here.
            # The current update_payload only includes metadata and code_content.

        success = await self.mcp_tool_repo.update_mcp_tool_record(update_payload, tool_id)

        if success:
            log.info(f"Successfully updated MCP tool with ID: {tool_id}.")
            return {"status_message": f"Successfully updated MCP tool with ID: {tool_id}.", "is_update": True}
        else:
            log.error(f"Failed to update MCP tool with ID: {tool_id}.")
            return {"status_message": f"Failed to update MCP tool with ID: {tool_id}.", "is_update": False}

    # --- MCP Tool Deletion Operations ---

    async def delete_mcp_tool(self, tool_id: str, user_id: str, is_admin: bool = False) -> Dict[str, Any]:
        """
        Deletes an MCP tool (server definition) record from the database.
        Handles file deletion for 'mcp_file_' type tools.
        """
        tool_records = await self.mcp_tool_repo.get_mcp_tool_record(tool_id=tool_id)
        if not tool_records:
            log.error(f"No MCP tool found with ID: {tool_id}")
            return {"status_message": f"No MCP tool found with ID: {tool_id}", "is_delete": False}
        
        tool_data = tool_records[0]

        if not is_admin and tool_data["created_by"] != user_id:
            err = f"Permission denied: Only the admin or the tool's creator can perform this action for MCP Tool ID: {tool_id}."
            log.error(err)
            return {"status_message": err, "is_delete": False}

        # Check for agent dependencies
        agents_using_this_tool_raw = await self.tool_agent_mapping_repo.get_tool_agent_mappings_record(tool_id=tool_id)
        if agents_using_this_tool_raw:
            agent_ids = [m['agentic_application_id'] for m in agents_using_this_tool_raw]
            agent_details = []
            for agent_id in agent_ids:
                agent_record = await self.agent_repo.get_agent_record(agentic_application_id=agent_id)
                if agent_record:
                    agent_record = agent_record[0]
                    agent_details.append({
                        "agentic_application_id": agent_record['agentic_application_id'],
                        "agentic_application_name": agent_record['agentic_application_name'],
                        "agentic_app_created_by": agent_record['created_by']
                    })
            if agent_details:
                log.error(f"The MCP tool you are trying to delete is being referenced by {len(agent_details)} agentic applications.")
                return {
                    "status_message": f"The MCP tool you are trying to delete is being referenced by {len(agent_details)} agentic application(s).",
                    "details": agent_details,
                    "is_delete": False
                }

        # Delete from database
        delete_success = await self.mcp_tool_repo.delete_mcp_tool_record(tool_id)

        if delete_success:
            # Clean up associated file if 'mcp_file_' type
            if tool_id.startswith("mcp_file_"):
                filename = await self._generate_mcp_file_name(tool_name=tool_data["tool_name"], tool_id=tool_id)
                await self._delete_mcp_file_from_runtime_dir(filename)
            
            # Clean up tags
            await self.tag_service.clear_tags(tool_id=tool_id)

            log.info(f"Successfully deleted MCP tool with ID: {tool_id}")
            return {"status_message": f"Successfully deleted MCP tool with ID: {tool_id}.", "is_delete": True}
        else:
            log.error(f"Failed to delete MCP tool with ID: {tool_id}.")
            return {"status_message": f"Failed to delete MCP tool with ID: {tool_id}.", "is_delete": False}

    # --- MCP Tool Approval Operations ---

    async def approve_mcp_tool(self, tool_id: str, approved_by: str, comments: Optional[str] = None) -> Dict[str, Any]:
        """
        Approves an MCP tool by updating its status in the repository.
        """
        update_payload = {
            "status": "approved",
            "approved_by": approved_by,
            "approved_at": datetime.now(timezone.utc).replace(tzinfo=None),
            "comments": comments
        }
        success = await self.mcp_tool_repo.update_mcp_tool_record(update_payload, tool_id)
        
        if success:
            log.info(f"Successfully approved MCP tool with ID: {tool_id}")
            return {"status_message": f"Successfully approved MCP tool with ID: {tool_id}", "is_approved": True}
        else:
            log.error(f"Failed to approve MCP tool with ID: {tool_id}")
            return {"status_message": f"Failed to approve MCP tool with ID: {tool_id}", "is_approved": False}

    async def get_all_mcp_tools_for_approval(self) -> List[Dict[str, Any]]:
        """
        Retrieves all MCP tools with 'pending' status for admin approval.
        """
        all_mcp_tools = await self.mcp_tool_repo.get_all_mcp_tool_records()
        pending_mcp_tools = [tool for tool in all_mcp_tools if tool.get("status") == "pending"]
        
        tool_id_to_tags = await self.tag_service.get_tool_id_to_tags_dict()
        for tool in pending_mcp_tools:
            if isinstance(tool.get("mcp_config"), str):
                tool["mcp_config"] = json.loads(tool["mcp_config"])
            tool['tags'] = tool_id_to_tags.get(tool['tool_id'], [])
        
        return pending_mcp_tools

    async def get_mcp_tools_for_approval_by_search_or_page(self, search_value: str = '', limit: int = 20, page: int = 1) -> Dict[str, Any]:
        """
        Retrieves MCP tools with 'pending' status, with pagination and search filtering, for admin approval.
        """
        # First get all pending tools, then apply search/pagination in memory for simplicity
        # For large datasets, this would need to be pushed to the repository query.
        all_pending_tools = await self.get_all_mcp_tools_for_approval()
        
        filtered_tools = [
            tool for tool in all_pending_tools 
            if not search_value or search_value.lower() in tool.get("tool_name", "").lower()
        ]
        
        total_count = len(filtered_tools)
        offset = limit * max(0, page - 1)
        paginated_tools = filtered_tools[offset : offset + limit]
        
        return {
            "total_count": total_count,
            "details": paginated_tools
        }

    # --- Runtime Tool Discovery from MCP Server ---

    async def get_live_mcp_tools_from_server(self, tool_id: str) -> Dict[str, Any]:
        """
        Connects to the live MCP server defined by the given tool_id and discovers
        the tools it exposes.
        """
        tool_records = await self.mcp_tool_repo.get_mcp_tool_record(tool_id=tool_id)
        if not tool_records:
            raise ValueError(f"MCP server definition not found for tool_id: {tool_id}")
        
        mcp_server_data = tool_records[0]
        mcp_config = mcp_server_data["mcp_config"]
        
        # Ensure mcp_config is a Python dict
        if isinstance(mcp_config, str):
            mcp_config = json.loads(mcp_config)
        mcp_server_data_copy = deepcopy(mcp_server_data)


        if mcp_server_data["tool_id"].startswith("mcp_file_"):
            filename = await self._generate_mcp_file_name(tool_name=mcp_server_data["tool_name"], tool_id=mcp_server_data["tool_id"])
            # temp_file_path = await self._write_mcp_file_to_runtime_dir(filename, mcp_config["code_content"])
            file_path = os.path.join(self.mcp_runtime_files_dir, filename)
            mcp_config["args"] = [file_path]
            code_content = mcp_config.pop("code_content", None)

        try:
            # Instantiate MultiServerMCPClient with the specific server config
            client = MultiServerMCPClient({mcp_server_data["tool_name"]: mcp_config})
            mcp_server_data_copy["live_tools"] = await client.get_tools()
            log.info(f"Discovered {len(mcp_server_data_copy['live_tools'])} tools from live MCP server: {mcp_server_data['tool_name']}")
            return mcp_server_data_copy

        except Exception as e:
            log.error(f"Error discovering tools from MCP server '{mcp_server_data['tool_name']}' ({tool_id}): {e}")
            raise ValueError(f"Failed to connect to or discover tools from MCP server: {e}")

    async def get_mcp_tool_details_for_display(
            self,
            tool_id: Optional[str] = None,
            live_tools: Optional[List[StructuredTool]] = None
        ) -> List[Dict[str, Any]]:
        """
        Extracts and formats details (name, description, args) from MCP tools for UI display.
        Can accept either an MCP server tool_id (to discover live tools) or a pre-fetched list of StructuredTool objects.

        Args:
            tool_id (Optional[str]): The ID of the MCP server definition in the database.
                                      If provided, live tools will be discovered from this server.
            live_tools (Optional[List[StructuredTool]]): A list of StructuredTool objects,
                                                          if tools have already been discovered.

        Returns:
            List[Dict[str, Any]]: A list of dictionaries, each containing 'name', 'description', and 'args'
                                  for an individual MCP tool.
        """
        if tool_id:
            try:
                # Discover live tools from the MCP server definition
                mcp_server_data = await self.get_live_mcp_tools_from_server(tool_id)
                live_tools: List[StructuredTool] = mcp_server_data.get("live_tools", [])
            except ValueError as e:
                log.error(f"Failed to get live MCP tools for display from tool_id {tool_id}: {e}")
                return [{"error": str(e)}]
            except Exception as e:
                log.error(f"Unexpected error getting live MCP tools for display from tool_id {tool_id}: {e}")
                return [{"error": f"An unexpected error occurred: {e}"}]

        if not live_tools:
            log.info(f"No live MCP tools found for display for tool_id: {tool_id or 'N/A'}.")
            return []

        extracted_details = []
        for tool_obj in live_tools:
            if isinstance(tool_obj, StructuredTool):
                extracted_details.append({
                    "name": tool_obj.name,
                    "description": tool_obj.description,
                    "args": tool_obj.args # This is already a dictionary representing the schema
                })
            else:
                log.warning(f"Skipping non-StructuredTool object: {tool_obj}")
        
        log.info(f"Extracted details for {len(extracted_details)} MCP tools for display.")
        return extracted_details

# --- Tool Service ---

class ToolService:
    """
    Service layer for managing tools.
    Applies business rules, handles docstring generation, validation,
    dependency checks, and orchestrates repository calls.
    """

    def __init__(
        self,
        tool_repo: ToolRepository,
        agent_repo: AgentRepository, # Need agent_repo for dependency checks
        model_service: ModelService,
        mcp_tool_service: McpToolService
    ):
        self.tool_repo = tool_repo
        self.agent_repo = agent_repo # Store agent_repo for direct use in dependency checks
        self.model_service = model_service
        self.mcp_tool_service = mcp_tool_service

    async def get_tool(self, tool_id: Optional[str] = None, tool_name: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        Retrieves a single tool record by ID or name, with associated tags.

        Args:
            tool_id (str, optional): Tool ID.
            tool_name (str, optional): Tool name.

        Returns:
            dict: A dictionary representing the retrieved tool, or None if not found.
        """
        tool_records = await self.tool_repo.get_tool_record(tool_id=tool_id, tool_name=tool_name)
        if not tool_records:
            log.info(f"No tool found with ID: {tool_id} or Name: {tool_name}.")
            return []

        log.info(f"Retrieved tool with ID: {tool_records[0]['tool_id']} and Name: {tool_records[0]['tool_name']}.")
        return tool_records

    @staticmethod
    async def render_text_description_for_tools(tools: List[BaseTool | StructuredTool]) -> str:
        """Render the tool name and description in plain text.

        Args:
            tools: The tools to render.

        Returns:
            The rendered text.

        Output will be in the format of:

        .. code-block:: markdown

            search: This tool is used for search
            calculator: This tool is used for math
        """
        descriptions = []
        for tool in tools:
            if isinstance(tool, StructuredTool):
                description = f"tool name:\n{tool.name} \n tool arguments:\n{tool.args} \ntool Docstring:\n{tool.__doc__}\n"
            else:
                signature = inspect.signature(tool)
                args_list = ""

                for param_name, param in signature.parameters.items():
                    args_list +=f"Parameter: {param_name}, Type: {param.annotation}\n"
                description = f"tool name:\n{tool.__name__} \n tool arguments:\n{args_list} \ntool Docstring:\n{tool.__doc__}\n"
            descriptions.append(description)
        return "\n\n".join(descriptions)

    async def _extract_tools_using_tool_ids(self, tools_id: Union[List[str], str]) -> Dict[str, Any]:
        """
        Extracts tool information from the database using tool IDs.

        Args:
            tools_id (Union[List[str], str]): List of tool IDs to retrieve details for.

        Returns:
            dict: A dictionary containing tool information indexed by tool names.
        """
        if isinstance(tools_id, str):
            tools_id = [tools_id]

        tools_info_user = {}
        for idx, tool_id_single in enumerate(tools_id):
            tool_record = await self.tool_repo.get_tool_record(tool_id=tool_id_single)
            if tool_record:
                tool_record = tool_record[0]
                tools_info_user[f"Tool_{idx+1}"] = {
                    "Tool_Name": tool_record.get("tool_name"),
                    "Tool_Description": tool_record.get("tool_description"),
                    "code_snippet": tool_record.get("code_snippet")
                }
            else:
                tools_info_user[f"Tool_{idx+1}"] = {"error": f"No data found for tool_id: {tool_id_single}"}
        log.info(f"Extracted {len(tools_info_user)} tools using provided tool IDs.")
        return tools_info_user

    @staticmethod
    async def _generate_tool_prompt_from_tools_info(tools_info: Dict[str, Any]) -> str:
        """
        Generates a prompt for the agent describing the available tools.

        Args:
            tools_info (dict): A dictionary containing information about each tool.

        Returns:
            str: A prompt string describing the tools.
        """
        memory_tool_data = """
        tool_name : manage_tool
        tool_description : Stores personal or contextual information for the user in long-term memory.
                Useful when the user says something you'd want to remember later — like their name,
                preferences, relationships, or other personal facts.
        
        tool_namespace : infyagent_framework/{user_id}/conversation_collection
        
        tool_name : search_tool
        tool_description : Searches the user's memory for previously stored facts or information.
                Useful when the user asks a question that may refer to something they told earlier.
                The tool searches the user's memory for previously stored facts or information.
        tool_namespace : infyagent_framework/{user_id}/conversation_collection
        """
        tool_prompt = f"{memory_tool_data}\n\n\n\n"
        for tool_id, tool_info_desc in tools_info.items():
            if "error" in tool_info_desc:
                log.error(f"Error in tool info: {tool_info_desc['error']}")
                continue
            tool_nm = tool_info_desc.get("Tool_Name", "")
            tool_desc = tool_info_desc.get("Tool_Description", "")
            tool_code = tool_info_desc.get("code_snippet", "")
            tool_prompt_temp = f"""{tool_id}
-------------------------
Tool Name: {tool_nm}

Tool Description: {tool_desc}

Tool Code Snippet:
{tool_code}"""
            tool_prompt = tool_prompt + tool_prompt_temp + "\n\n\n\n"
        if not tools_info:
            log.warning("No tools available for onboarding.")
            tool_prompt = "No tools are available"
        log.info(f"Generated tool prompt with {len(tools_info)} tools.")
        return tool_prompt

    async def generate_tool_prompt(self, tools_id: Union[List[str], str]) -> str:
        """
        Generates a prompt for the agent describing the available tools.

        Args:
            tools_id (Union[List[str], str]): A list of tool IDs to generate the prompt for.

        Returns:
            str: A prompt string describing the tools.
        """
        tools_info = await self._extract_tools_using_tool_ids(tools_id)
        return await self._generate_tool_prompt_from_tools_info(tools_info)
class AgentServiceUtils:

    def __init__(
        self,
        agent_repo: AgentRepository,
        tool_service: ToolService,
        model_service: ModelService,
        meta_type_templates: Optional[List[str]] = None
    ):
        self.agent_repo = agent_repo
        self.tool_service = tool_service
        self.model_service = model_service
        self.meta_type_templates = meta_type_templates or ["meta_agent", "planner_meta_agent"]


    @staticmethod
    async def _normalize_agent_name(agent_name: str):
        """
        Normalizes the agent name by removing invalid characters and formatting it.
        """
        return re.sub(r'[^a-z0-9_]', '', agent_name.strip().lower().replace(" ", "_"))


class AgentService:
    """
    Service layer for managing agents (Agentic Applications).
    Applies business rules, handles prompt generation, validation,
    dependency checks, and orchestrates repository and other service calls.
    """

    def __init__(self, agent_service_utils: AgentServiceUtils):
        self.agent_service_utils = agent_service_utils
        self.agent_repo = agent_service_utils.agent_repo
        self.tool_service = agent_service_utils.tool_service
        self.model_service = agent_service_utils.model_service
        self.meta_type_templates = agent_service_utils.meta_type_templates

    async def get_agents_details_for_chat(self) -> List[Dict[str, Any]]:
        """
        Fetches basic agent details (ID, name, type) for chat purposes.

        Returns:
            list[dict]: A list of dictionaries, where each dictionary contains
                        'agentic_application_id', 'agentic_application_name',
                        and 'agentic_application_type'.
        """
        return await self.agent_repo.get_agents_details_for_chat_records()
    # --- Agent Retrieval Operations ---

    async def get_agent(self,
                        agentic_application_id: Optional[str] = None,
                        agentic_application_name: Optional[str] = None,
                        agentic_application_type: Optional[str] = None,
                        created_by: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        Retrieves agents from the database based on provided parameters, with associated tags.

        Args:
            agentic_application_id (str, optional): The ID of the agentic application to filter by.
            agentic_application_name (str, optional): The name of the agentic application to filter by.
            agentic_application_type (str, optional): The type of agentic application to filter by.
            created_by (str, optional): The creator of the agentic application to filter by.

        Returns:
            list: A list of dictionaries representing the retrieved agents, or an empty list on error.
        """
        agent_records = await self.agent_repo.get_agent_record(
            agentic_application_id=agentic_application_id,
            agentic_application_name=agentic_application_name,
            agentic_application_type=agentic_application_type,
            created_by=created_by
        )

        if not agent_records:
            log.error(f"No agentic application found with ID: {agentic_application_id or agentic_application_name or agentic_application_type or created_by}")
            return []

        for agent_record in agent_records:
            if agent_record:
                agentic_application_name = agent_record.get('agentic_application_name')
                # Ensure JSONB fields are loaded as Python objects (asyncpg usually handles this)
                agent_record['system_prompt'] = json.loads(agent_record['system_prompt']) if isinstance(agent_record['system_prompt'], str) else agent_record['system_prompt']
                agent_record['tools_id'] = json.loads(agent_record['tools_id']) if isinstance(agent_record['tools_id'], str) else agent_record['tools_id']
                # agent_record['tags'] = await self.tag_service.get_tags_by_agent(agent_record['agentic_application_id'])
                log.info(f"Retrieved agentic application with name: {agentic_application_name}")
        return agent_records

    @staticmethod
    async def _normalize_agent_name(agent_name: str):
        """
        Normalizes the agent name by removing invalid characters and formatting it.
        """
        return re.sub(r'[^a-z0-9_]', '', agent_name.strip().lower().replace(" ", "_"))
  

# --- Chat History Service ---

class ChatService:
    """
    Service layer for managing chat history.
    Applies business rules for naming conventions and orchestrates repository calls.
    """

    def __init__(self, chat_history_repo: ChatHistoryRepository):
        """
        Initializes the ChatService.

        Args:
            chat_history_repo (ChatHistoryRepository): The repository for chat history data access.
        """
        self.repo = chat_history_repo
        self.conversation_summary_prompt_template = PromptTemplate.from_template(CONVERSATION_SUMMARY_PROMPT)

    # --- Private Helper Methods (Business Logic) ---

    @staticmethod
    async def _get_chat_history_table_name(agentic_application_id: str) -> str:
        """
        Generates the dynamic table name for a specific agent's chat history.
        This encapsulates the naming convention logic.
        
        Args:
            agentic_application_id (str): The unique ID of the agentic application.

        Returns:
            str: The formatted table name.
        """
        return f'table_{agentic_application_id.replace("-", "_")}'

    @staticmethod
    async def _get_thread_id(agentic_application_id: str, session_id: str) -> str:
        """
        Generates the thread_id used in checkpoint tables.

        Args:
            agentic_application_id (str): The unique ID of the agentic application.
            session_id (str): The unique ID for the session.
        
        Returns:
            str: The formatted thread ID.
        """
        table_name = await ChatService._get_chat_history_table_name(agentic_application_id)
        return f"{table_name}_{session_id}"

    @staticmethod
    async def _get_thread_config(thread_id: str, recursion_limit: int = 50) -> Dict[str, Any]:
        """
        Retrieves the thread configuration for a specific thread_id.
        """
        # return {"configurable": {"thread_id": thread_id}, "recursion_limit": recursion_limit}
        # user_id = thread_id[-36:]  
        user_id = thread_id
        return {"configurable": {"thread_id": thread_id, "user_id": user_id}, "recursion_limit": recursion_limit}


    async def _get_summary_chain(self, llm):
        return self.conversation_summary_prompt_template | llm | StrOutputParser()
    
    
    async def update_preferences(self, user_input: str, llm: Any, agentic_application_id, session_id) -> str:
        """
        Update the preferences based on user input.
        """
        try:
            final_response = ""
            preferences = await self.repo.get_agent_conversation_summary_with_preference(agentic_application_id=agentic_application_id, session_id= session_id)
            print(preferences)
            prompt = f"""
    Current Preferences:
    {preferences}

    User Input:
    {user_input}


    Instructions:
    - Understand the User query, now analyze is the user intention with query is to provide feedback or related to task.
    - Understand the feedback points from the given query and add them into the feedback.
    - Inputs related to any task are not preferences. Don't consider them.
    - If user intention is providing feed back then update the preferences based on below guidelines.
    - Update the preferences based on the user input.
    - If it's a new preference or feedback, add it as a new line.
    - If it modifies an existing preference or feedback, update the relevant line with detailed preference context.
    - User input can include new preferences, feedback on mistakes, or corrections to model behavior.
    - Store these preferences or feedback as lessons to help the model avoid repeating the same mistakes.
    - The output should contain only the updated preferences, with no extra explanation or commentary.
    - if no preferences are there then output should is "no preferences available".

    Examples:
    user query: output should in markdown format
    - the user query is related to preference and should be added to the preferences.
    user query: a person is running at 5km per hour how much distance he can cover by 2 hours
    - The user query is related to task and should not be added to the preferences.
    user query: give me the response in meters.
    - This is a perference and should be added to the preferences.
    """+"""
    Output:
    ```json
    {
    "preferences": ["all new preferences with comma as separator are added here", "", ...goes on]
    }
    ```

    """
            response = await llm.ainvoke(prompt)
            response = response.content.strip()
            if "```json" in response:
                response = response[response.find("```json") + len("```json"):]
            response = response.replace('```json', '').replace('```', '').strip()
            try:
                final_response = "\n".join(i for i in json.loads(response)["preferences"])
                await self.repo.insert_preference_for_agent_conversation(agentic_application_id=agentic_application_id, session_id=session_id, preference=final_response)
            except json.JSONDecodeError:
                log.error("Failed to decode JSON response from model.")
                return response
            log.info("Preferences updated successfully")
        except Exception as e:
            log.info(f"Error while updating preferences: {e}")
        return final_response

    # --- Public Service Methods ---

    async def save_chat_message(
        self,
        agentic_application_id: str,
        session_id: str,
        start_timestamp: datetime,
        end_timestamp: datetime,
        human_message: str,
        ai_message: str
    ) -> bool:
        """
        Orchestrates saving a new chat message pair to the database.
        It ensures the target table exists before inserting the record.

        Args:
            (all args are data for the chat message)

        Returns:
            bool: True if successful, False otherwise.
        """
        table_name = await self._get_chat_history_table_name(agentic_application_id)
        try:
            # Orchestration: ensure table exists, then insert.
            await self.repo.create_chat_history_table(table_name)
            await self.repo.insert_chat_record(
                table_name=table_name,
                session_id=session_id,
                start_timestamp=start_timestamp,
                end_timestamp=end_timestamp,
                human_message=human_message,
                ai_message=ai_message,
            )
            return True
        except Exception as e:
            log.error(f"Service-level error saving chat message for session '{session_id}': {e}")
            return False

    async def get_chat_history_from_short_term_memory(
            self,
            agentic_application_id: str,
            session_id: str
        ) -> Dict[str, Any]:
        """
        Retrieves the previous conversation history for a given session from the LangGraph checkpointer.

        Args:
            agentic_application_id (str): The ID of the agent.
            session_id (str): The session ID of the user.

        Returns:
            Dict[str, Any]: A dictionary containing the previous conversation history,
                            or an error message if retrieval fails.
        """
        thread_id = await self._get_thread_id(agentic_application_id, session_id)

        try:
            # The checkpointer needs its own connection setup
            async with await self.get_checkpointer_context_manager() as checkpointer:
                # checkpointer.setup() is often called implicitly or handled by LangGraph's app.compile()
                # but explicitly calling it here ensures the table exists if it's the first time.
                # However, for just retrieving, it might not be strictly necessary if tables are pre-created.
                await checkpointer.setup()

                config = await self._get_thread_config(thread_id)
                data = await checkpointer.aget(config) # Retrieve the state
                if data:
                    # data.channel_values contains the state of the graph, including messages
                    data = data.get("channel_values", {})
                else:
                    data = {}

                if not data:
                    log.warning(f"No previous conversation found for session ID: {session_id} and agent ID: {agentic_application_id}.")
                    return {"executor_messages": []} # Return empty list if no data

                # Segregate messages using the static method
                data["executor_messages"] = await self.segregate_conversation_from_raw_chat_history_with_pretty_steps(data)
                log.info(f"Previous conversation retrieved successfully for session ID: {session_id} and agent ID: {agentic_application_id}.")
                return data

        except Exception as e:
            log.error(f"Error occurred while retrieving previous conversation for session {session_id}: {e}", exc_info=True)
            return {"error": f"An unknown error occurred while retrieving conversation: {e}"}
        finally:
            update_session_context(session_id='Unassigned',agent_id='Unassigned')

    async def get_chat_history_from_long_term_memory(
            self,
            agentic_application_id: str,
            session_id: str,
            limit: int = 30
        ) -> List[Dict[str, Any]]:
        """
        Retrieves recent chat history for a given session.

        Args:
            agentic_application_id (str): The ID of the agent.
            session_id (str): The ID of the chat session.
            limit (int): The maximum number of conversation pairs to retrieve.

        Returns:
            A list of chat history records.
        """
        table_name = await self._get_chat_history_table_name(agentic_application_id)
        return await self.repo.get_chat_records_by_session_from_long_term_memory(
            table_name=table_name,
            session_id=session_id,
            limit=limit
        )

    async def get_chat_summary(self, agentic_application_id, session_id, llm, conversation_limit=8, executor_messages=None, executor_message_limit=30) -> str:
        """Retrieves a summary of the conversation history for a given session ID."""
        # return ""
        conversation_history_df = pd.DataFrame(
            await self.get_chat_history_from_long_term_memory(
                    agentic_application_id=agentic_application_id,
                    session_id=session_id,
                    limit=conversation_limit
                )
        )
        conversation_summary_chain = await self._get_summary_chain(llm)

        # Process chat history if available
        if len(conversation_history_df):
            conversation_history_df = conversation_history_df.sort_values(
                by=["start_timestamp", "end_timestamp"]
            ).reset_index(drop=True)
            chat_history = "\n\n".join(
                [
                    f"""Human Message: {Human_Message}
    AI Message: {AI_Message}"""
                    for Human_Message, AI_Message in conversation_history_df[
                        ["human_message", "ai_message"]
                    ].itertuples(index=False)
                ]
            )
            if executor_messages:
                chat_history += "\n\n" + "\n\n".join(self.get_formatted_messages(messages=executor_messages, msg_limit=executor_message_limit))
            past_conversation_summary = await self.repo.get_agent_conversation_summary_with_preference(
                                agentic_application_id=agentic_application_id,
                                session_id=session_id
                                )
            past_conversation_summary = past_conversation_summary.get("summary", "") if past_conversation_summary else ""
            conversation_summary = await conversation_summary_chain.ainvoke(
                {"chat_history": chat_history, "past_conversation_summary": past_conversation_summary}
            )
            await self.repo.update_agent_conversation_summary(
                agentic_application_id=agentic_application_id,
                session_id=session_id,
                summary=conversation_summary
            )
            log.debug("Chat summary stored successfully")
        else:
            conversation_summary = ""
        log.info(f"Conversation Summary generated for agent id {agentic_application_id} and session {session_id}")
        return conversation_summary
    
    async def get_chat_conversation_summary(
        self, agentic_application_id: str, session_id: str
    ) -> Optional[Dict[str, Any]]:
        """
        Retrieves the conversation summary for a specific agent and session.

        Args:
            agentic_application_id (str): The ID of the agentic application.
            session_id (str): The ID of the session.

        Returns:
            dict: A dictionary representing the conversation summary, or None if not found.
        """
        return await self.repo.get_agent_conversation_summary_with_preference(
            agentic_application_id=agentic_application_id,
            session_id=session_id
        )

    async def create_new_session_id(self, email: str) -> str:
        """
        Generates a new unique session ID based on the user's email.

        Args:
            email (str): The user's email.

        Returns:
            str: The newly generated session ID.
        """
        new_uuid = str(uuid.uuid4()).replace("-", "_")
        session_id = f"{email}_{new_uuid}"
        log.info(f"New chat session ID generated for user '{email}': {session_id}.")
        return session_id

    async def get_old_chats_by_user_and_agent(self, user_email: str, agent_id: str) -> Dict[str, Any]:
        """
        Retrieves old chat sessions for a specific user and agent.

        Args:
            user_email (str): The email of the user.
            agent_id (str): The ID of the agent.

        Returns:
            Dict[str, Any]: A dictionary where keys are session IDs and values are lists of chat records.
        """
        table_name = await self._get_chat_history_table_name(agent_id)
        
        try:
            raw_records = await self.repo.get_chat_records_by_session_prefix(
                table_name=table_name,
                session_id_prefix=f"{user_email}_%"
            )
        except Exception as e:
            log.error(f"Error retrieving old chats for user '{user_email}' and agent '{agent_id}': {e}")
            return {} # Return empty dict on error

        result = {}
        for row in raw_records:
            session_id_full = row.get('session_id')
            timestamp_start = row.get('start_timestamp')
            timestamp_end = row.get('end_timestamp')
            user_input = row.get('human_message')
            agent_response = row.get('ai_message')

            if session_id_full not in result:
                result[session_id_full] = []

            result[session_id_full].append({
                "timestamp_start": timestamp_start,
                "timestamp_end": timestamp_end,
                "user_input": user_input,
                "agent_response": agent_response
            })
        log.info(f"Retrieved old chats for user '{user_email}' and agent '{agent_id}'.")
        return result

    async def delete_session(self, agentic_application_id: str, session_id: str) -> Dict[str, Any]:
        """
        Deletes the entire conversation history for a specific session.
        This involves deleting from chat history and checkpoint tables transactionally.

        Args:
            agentic_application_id (str): The ID of the agent.
            session_id (str): The session ID to delete records for.

        Returns:
            dict: A status dictionary indicating the result of the operation.
        """
        chat_table_name = await self._get_chat_history_table_name(agentic_application_id)
        thread_id = await self._get_thread_id(agentic_application_id, session_id)
        
        try:
            chat_rows_deleted = await self.repo.delete_session_transactional(
                chat_table_name=chat_table_name,
                thread_id=thread_id,
                session_id=session_id
            )
            return {
                "status": "success",
                "message": f"Memory history deleted successfully for session {session_id}.",
                "chat_rows_deleted": chat_rows_deleted
            }
        except Exception as e:
            log.error(f"Service-level error during transactional delete for session '{session_id}': {e}")
            return {"status": "error", "message": f"An error occurred during deletion: {e}"}
        
    async def delete_internal_thread(self, internal_thread:str):
        """
        Deletes an internal thread from the checkpoints table.
        
        Args:
            internal_thread (str): The thread_id of the internal thread to delete.

        Returns:
            bool: True if deletion was successful, False otherwise.
        """
        try:
            success = await self.repo.delete_session_transactional_internal(internal_thread=internal_thread)
            return success
        except Exception as e:
            log.error(f"Error deleting internal thread '{internal_thread}': {e}")
            return f"Error deleting internal thread '{internal_thread}': {e}"

    async def get_all_sessions(self) -> List[Dict[str, str]]:
        """
        Retrieves all unique chat session thread_ids from the checkpoints table.
        """
        return await self.repo.get_all_thread_ids_from_checkpoints()

    async def update_latest_query_response_with_tag(
        self,
        agentic_application_id: str,
        session_id: str,
        message_type: str = "ai",
        start_tag: str = "[liked_by_user:]",
        end_tag: str = "[:liked_by_user]"
    ) -> Optional[bool]: # <--- Reverted return type hint
        """
        Updates the latest query response (or human message) by adding or removing
        specified tags.

        Args:
            agentic_application_id (str): The ID of the agentic application.
            session_id (str): The session ID to identify the conversation.
            message_type (str): The type of message to update ('ai' or 'human').
            start_tag (str): The starting tag to add or remove.
            end_tag (str): The ending tag to add or remove.

        Returns:
            Optional[bool]: True if tags were added, False if tags were removed,
                            None if the message was not found or an error occurred.
        """
        table_name = await self._get_chat_history_table_name(agentic_application_id)

        message_type_lower = message_type.lower()
        if message_type_lower == "human":
            message_column = "human_message"
        elif message_type_lower == "ai":
            message_column = "ai_message"
        else:
            log.warning(f"Invalid message_type '{message_type}'. Must be 'ai' or 'human'.")
            return None

        try:
            latest_message_record = await self.repo.get_latest_message_record(
                table_name=table_name,
                session_id=session_id,
                message_column=message_column
            )

            if not latest_message_record:
                log.warning(f"No latest {message_type} message found for session {session_id} in table {table_name}.")
                return None

            current_message_content = latest_message_record['message_content']
            end_timestamp = latest_message_record['end_timestamp']

            tags_were_present: bool
            if current_message_content.startswith(start_tag) and current_message_content.endswith(end_tag):
                # Tags are present, remove them
                updated_content = current_message_content[len(start_tag):-len(end_tag)].strip()
                tags_were_present = True
                log.info(f"Removing tags from latest {message_type} message for session {session_id}.")
            else:
                # Tags are not present, add them
                updated_content = f"{start_tag}{current_message_content}{end_tag}".strip()
                tags_were_present = False
                log.info(f"Adding tags to latest {message_type} message for session {session_id}.")

            success = await self.repo.update_message_tag_record(
                table_name=table_name,
                session_id=session_id,
                message_column=message_column,
                updated_message_content=updated_content,
                end_timestamp=end_timestamp
            )

            if success:
                return not tags_were_present # True if tags were added, False if removed
            else:
                log.error(f"Failed to update {message_type} message for session {session_id} in table {table_name} after processing tags.")
                return None

        except Exception as e:
            log.error(f"Service-level error updating query response with tag for session '{session_id}': {e}")
            return None

    # --- Chat Helper Methods ---

    async def get_checkpointer_context_manager(self):
        """
        Retrieves the checkpointer context manager for managing conversation state.
        """
        return await self.repo.get_checkpointer_context_manager()

    async def get_store_context_manager(self):
        """
        Retrieves the store context manager for managing chat memory.
        """
        return await self.repo.get_store_context_manager()

    @staticmethod
    async def get_formatted_messages(messages: List[AnyMessage], msg_limit: int = 30) -> str:
        """
        Formats a list of messages for display.

        Args:
            messages (list): The list of messages.
            msg_limit (int): The maximum number of messages to display.

        Returns:
            str: The formatted message string.
        """

        if (len(messages)+1)%8 == 0:
            msg_limit = 8
        else:
            msg_limit = len(messages) % 8
        msg_formatted = ""
        for m in messages[-msg_limit:]: # Display only the last `msg_limit` messages
            if isinstance(m, HumanMessage):
                hmn_format = f"Human Message: {m.content}"
                msg_formatted += hmn_format + "\n\n"
            elif isinstance(m, ChatMessage) and m.role == "feedback":
                feedback_format = f"Feedback: {m.content}"
                msg_formatted += feedback_format + "\n\n"
            elif isinstance(m, AIMessage):
                ai_format = f"AI Message: {m.content}"
                msg_formatted += ai_format + "\n\n"
            elif isinstance(m, ToolMessage):
                tool_msg_format = f"Tool Message: {m.content}"
                msg_formatted += tool_msg_format + "\n\n"
        return msg_formatted.strip()

    @staticmethod
    async def segregate_conversation_from_raw_chat_history_with_pretty_steps(response: Dict[str, Any]) -> List[Dict[str, Any]]:
        """
        Segregates and formats conversation messages from a raw response into a human-readable list.
        """
        if "error" in response:
            log.error(f"Error in response")
            return [response]
        error_message = [{"error": "Chat History not compatable with the new version. Please reset your chat."}]
        executor_messages = response.get("executor_messages", [{}])
        # return executor_messages
        if not executor_messages[0] or not hasattr(executor_messages[0], 'role') or executor_messages[0].role != "user_query":
            return error_message

        conversation_list = []
        agent_steps = []
        

        for message in reversed(executor_messages):
            agent_steps.append(message)
            if message.type == "human" and hasattr(message, 'role') and message.role=="user_query":
                data = ""
                tools_used = dict()

                # Pretty-print each message to the buffer
                for msg in list(reversed(agent_steps)):
                    if msg.type == "ai" and msg.tool_calls != []:
                        for tool_msg in msg.tool_calls:
                            if tool_msg["id"] not in tools_used:
                                tools_used[tool_msg["id"]] = {}
                            tools_used[tool_msg["id"]].update(tool_msg)

                    elif msg.type == "tool":
                        if msg.tool_call_id not in tools_used:
                            tools_used[msg.tool_call_id] = {}
                        tools_used[msg.tool_call_id]["status"] = msg.status
                        tools_used[msg.tool_call_id]["output"] = msg.content
                    data += "\n"+ msg.pretty_repr()


                new_conversation = {
                    "user_query": message.content,
                    "final_response": agent_steps[0].content if (agent_steps[0].type == "ai") and ("tool_calls" not in agent_steps[0].additional_kwargs) and ("function_call" not in agent_steps[0].additional_kwargs) else "",
                    "tools_used": tools_used,
                    "agent_steps": data,
                    "additional_details": agent_steps
                }
                conversation_list.append(new_conversation)
                agent_steps = []
                tools_used = dict()
        log.info("Conversation segregated from chat history successfully")
        return list(reversed(conversation_list))

    @staticmethod
    async def segregate_conversation_from_raw_chat_history_with_json_like_steps(response: Dict[str, Any]) -> List[Dict[str, Any]]:
        """
        Segregates and formats conversation messages from a raw response into a JSON-serializable list.
        """
        if "error" in response:
            log.error(f"Error in response")
            return [response]
        error_message = [{"error": "Chat History not compatable with the new version. Please reset your chat."}]
        executor_messages = response.get("executor_messages", [{}])
        # return executor_messages
        if not executor_messages[0] or not hasattr(executor_messages[0], 'role') or executor_messages[0].role != "user_query":
            return error_message

        conversation_list = []
        agent_steps = []

        for message in reversed(executor_messages):
            agent_steps.append(message)
            if message.type == "human" and hasattr(message, 'role') and message.role=="user_query":
                new_conversation = {
                    "user_query": message.content,
                    "final_response": agent_steps[0].content if (agent_steps[0].type == "ai") and ("tool_calls" not in agent_steps[0].additional_kwargs) and ("function_call" not in agent_steps[0].additional_kwargs) else "",
                    "agent_steps": list(reversed(agent_steps)),
                }
                conversation_list.append(new_conversation)
                agent_steps = []
        log.info("Conversation segregated in JSON format successfully")
        return list(reversed(conversation_list))

    async def handle_like_feedback_message(
        self,
        agentic_application_id: str,
        session_id: str,
        message_type: str = "ai",
        start_tag: str = "[liked_by_user:]",
        end_tag: str = "[:liked_by_user]"
    ) -> Dict[str, str]:
        """
        Handles the like/unlike feedback for the latest message and returns a user-friendly message.

        Args:
            agentic_application_id (str): The ID of the agentic application.
            session_id (str): The session ID to identify the conversation.
            message_type (str): The type of message to update ('ai' or 'human').
            start_tag (str): The starting tag to add or remove.
            end_tag (str): The ending tag to add or remove.

        Returns:
            Dict[str, str]: A dictionary containing a 'message' key with the status.
        """
        update_status = await self.update_latest_query_response_with_tag(
            agentic_application_id=agentic_application_id,
            session_id=session_id,
            message_type=message_type,
            start_tag=start_tag,
            end_tag=end_tag
        )

        if update_status is True: # Tags were added
            return {"message": "Thanks for the like! We're glad you found the response helpful. If you have any more questions or need further assistance, feel free to ask!"}
        elif update_status is False: # Tags were removed
            return {"message": "Your like has been removed. If you have any more questions or need further assistance, feel free to ask!"}
        else: # None was returned (message not found or error)
            return {"message": "Sorry, we couldn't update your request at the moment. Please try again later."}

    async def fetch_all_user_queries(self, user_email: str, agentic_application_id: str) -> Dict[str, List[str]]:
        """
        Fetches all user queries from the chat table for a specific user email.

        Args:
            user_email (str): The email of the user to fetch queries for.
            agentic_application_id (str): The ID of the agentic application.

        Returns:
            Dict[str, List[str]]: A dictionary containing user queries and other session IDs.
        """
        chat_table_name = await self._get_chat_history_table_name(agentic_application_id)
        queries = await self.repo.fetch_user_query_from_chat_table(user_email=user_email, chat_table_name=chat_table_name)
        return queries

# --- Feedback Learning Service ---

class FeedbackLearningService:
    """
    Service layer for managing feedback data.
    Orchestrates FeedbackLearningRepository calls and applies business logic,
    including data enrichment (e.g., adding agent names).
    """

    def __init__(self, feedback_learning_repo: FeedbackLearningRepository, agent_service: 'AgentService'):
        """
        Initializes the FeedbackLearningService.

        Args:
            feedback_learning_repo (FeedbackLearningRepository): The repository for feedback data access.
            agent_service (AgentService): The service for agent-related operations (for data enrichment).
        """
        self.repo = feedback_learning_repo
        self.agent_service = agent_service


    async def save_feedback(self, agent_id: str, query: str, old_final_response: str, old_steps: str, feedback: str, new_final_response: str, new_steps: str, lesson: str, approved: bool = False) -> Dict[str, Any]:
        """
        Saves new feedback data, including the feedback response and its mapping to an agent.
        """
        response_id = str(uuid.uuid4()).replace("-", "_") # Generate a unique response ID
        feedback_success = await self.repo.insert_feedback_record(
            response_id=response_id,
            query=query,
            old_final_response=old_final_response,
            old_steps=old_steps,
            feedback=feedback,
            new_final_response=new_final_response,
            new_steps=new_steps,
            approved=approved, 
            lesson=lesson
        )
        if feedback_success:
            mapping_success = await self.repo.insert_agent_feedback_mapping(
                agent_id=agent_id,
                response_id=response_id
            )
            if mapping_success:
                log.info(f"Feedback inserted successfully for agent_id: {agent_id} with response_id: {response_id}.")
                return {"message": "Feedback saved successfully.", "response_id": response_id, "is_saved": True}
            else:
                log.error(f"Failed to map feedback {response_id} to agent {agent_id}.")
                # Consider deleting the feedback record if mapping failed to prevent orphaned data
                return {"message": "Feedback saved but failed to map to agent.", "response_id": response_id, "is_saved": False}
        else:
            log.error(f"Failed to insert feedback record for agent_id: {agent_id}.")
            return {"message": "Failed to save feedback.", "response_id": None, "is_saved": False}

    async def get_approved_feedback(self, agent_id: str) -> List[Dict[str, Any]]:
        """
        Retrieves approved feedback for a specific agent.
        """
        return await self.repo.get_approved_feedback_records(agent_id)

    async def get_all_approvals_for_agent(self, agent_id: str) -> List[Dict[str, Any]]:
        """
        Retrieves all feedback and their approval status for a given agent_id.
        """
        return await self.repo.get_all_feedback_records_by_agent(agent_id)

    async def get_feedback_details_by_response_id(self, response_id: str) -> List[Dict[str, Any]]:
        """
        Retrieves all details for a specific feedback response, including agent name.
        """
        feedback_records = await self.repo.get_feedback_record_by_response_id(response_id)
        for feedback_record in feedback_records:
            agent_id = feedback_record.get("agent_id", "")
            agent_details_list = await self.agent_service.get_agent(agentic_application_id=agent_id)
            agent_name = agent_details_list[0].get("agentic_application_name", "Unknown") if agent_details_list else "Unknown"
            feedback_record["agent_name"] = agent_name
        log.info(f"Retrieved feedback details for response_id: {response_id}.")
        return feedback_records

    async def get_agents_with_feedback(self) -> List[Dict[str, Any]]:
        """
        Retrieves all agents who have given feedback along with their names.
        """
        distinct_agent_ids = await self.repo.get_distinct_agents_with_feedback()
        agent_data = []
        for agent_id in distinct_agent_ids:
            agent_details_list = await self.agent_service.agent_repo.get_agent_record(agentic_application_id=agent_id)
            agent_name = agent_details_list[0].get("agentic_application_name", "Unknown") if agent_details_list else "Unknown"
            agent_data.append({
                "agent_id": agent_id,
                "agent_name": agent_name
            })
        log.info(f"Retrieved {len(agent_data)} agents with feedback.")
        return agent_data

    async def update_feedback_status(self, response_id: str, update_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Updates fields in a feedback_response record.
        `update_data` should be a dictionary with keys as column names and values as the new values.
        """
        success = await self.repo.update_feedback_record(response_id, update_data)
        if success:
            return {"is_update": True, "message": "Feedback updated successfully."}
        else:
            return {"is_update": False, "message": "Failed to update feedback."}


# --- Evaluation Service ---

class EvaluationService:
    """
    Service layer for managing evaluation metrics.
    Orchestrates repository calls for evaluation data, agent metrics, and tool metrics.
    Handles data preparation and serialization for database insertion.
    """

    def __init__(
        self,
        evaluation_data_repo: EvaluationDataRepository,
        tool_evaluation_metrics_repo: ToolEvaluationMetricsRepository,
        agent_evaluation_metrics_repo: AgentEvaluationMetricsRepository,
        tool_service: 'ToolService',    # For getting tool details for logging/enrichment
        agent_service: 'AgentService' # For getting agent details for logging/enrichment
    ):
        self.evaluation_data_repo = evaluation_data_repo
        self.tool_evaluation_metrics_repo = tool_evaluation_metrics_repo
        self.agent_evaluation_metrics_repo = agent_evaluation_metrics_repo
        self.tool_service = tool_service
        self.agent_service = agent_service


    async def create_evaluation_tables_if_not_exists(self):
        """
        Orchestrates the creation of all evaluation-related tables.
        """
        await self.evaluation_data_repo.create_table_if_not_exists()
        await self.tool_evaluation_metrics_repo.create_table_if_not_exists()
        await self.agent_evaluation_metrics_repo.create_table_if_not_exists()
        log.info("All evaluation tables checked/created successfully.")

    @staticmethod
    async def serialize_executor_messages(messages: list) -> list:
        serialized = []
        for msg in messages:
            if hasattr(msg, 'dict'):
                serialized.append(msg.dict())
            elif hasattr(msg, '__dict__'):
                serialized.append(vars(msg))  # fallback
            else:
                serialized.append(str(msg))   # last resort
        return serialized

    async def log_evaluation_data(self, session_id: str, agentic_application_id: str, agent_config: Dict[str, Any], response: Dict[str, Any], model_name: str) -> bool:
        """
        Logs raw inference data into the evaluation_data table.
        """
        agent_last_step = response.get("executor_messages", [{}])[-1].get("agent_steps", [{}])[-1]

        if not response.get('response') or (hasattr(agent_last_step, "role") and agent_last_step.role == 'plan'):
            log.info("Skipping evaluation data logging due to empty response or planner role in last step.")
            return False
        
        try:
            data_to_log = {}
            data_to_log["session_id"] = session_id
            data_to_log["query"] = response['query']
            data_to_log["response"] = response['response']
            data_to_log["model_used"] = model_name
            data_to_log["agent_id"] = agentic_application_id
            
            agent_details_list = await self.agent_service.agent_repo.get_agent_record(agentic_application_id=agentic_application_id)
            agent_details = agent_details_list[0] if agent_details_list else {}

            data_to_log["agent_name"] = agent_details.get('agentic_application_name', 'Unknown')
            data_to_log["agent_type"] = agent_details.get('agentic_application_type', 'Unknown')
            data_to_log["agent_goal"] = agent_details.get('agentic_application_description', '')
            data_to_log["workflow_description"] = agent_details.get('agentic_application_workflow_description', '')
            
            # Reconstruct tool_prompt from agent_config's TOOLS_INFO
            tools_info_ids = agent_config.get('TOOLS_INFO', [])
            if data_to_log["agent_type"] in self.agent_service.meta_type_templates:
                data_to_log["tool_prompt"] = await self.agent_service.generate_worker_agents_prompt(agents_id=tools_info_ids)
            else:
                data_to_log["tool_prompt"] = await self.tool_service.generate_tool_prompt(tools_id=tools_info_ids)

            # Ensure messages are in a serializable format (list of dicts)
            # Assuming response['executor_messages'] is already a list of LangChain Message objects
            # and segregate_conversation_in_json_format handles conversion to dicts.
            # The repository expects JSON dumped strings for JSONB columns.
            data_to_log["executor_messages"] = response['executor_messages']
            data_to_log["steps"] = response['executor_messages'][-1]['agent_steps']


            # Adjust query for feedback/regenerate if needed (business logic)
            if data_to_log['query'].startswith("[feedback:]") and data_to_log['query'].endswith("[:feedback]"):
                feedback_content = data_to_log['query'][11:-11]
                original_query_content = data_to_log["steps"][0].content if data_to_log["steps"] else ''
                data_to_log['query'] = f"Query:{original_query_content}\nFeedback: {feedback_content}"
            elif data_to_log['query'].startswith("[regenerate:]"):
                original_query_content = data_to_log["steps"][0].content if data_to_log["steps"] else ''
                data_to_log['query'] = f"Query:{original_query_content} (Regenerate)"

            data_to_log["steps"] = json.dumps(await self.serialize_executor_messages(data_to_log["steps"]))
            data_to_log["executor_messages"] = json.dumps(await self.serialize_executor_messages(data_to_log["executor_messages"]))

            success = await self.evaluation_data_repo.insert_evaluation_record(data_to_log)
            if success:
                log.info("Data inserted into evaluation_data table successfully.")
                return True
            else:
                log.error("Failed to insert data into evaluation_data table.")
                return False
        except Exception as e:
            log.error(f"Error preparing/inserting data into evaluation_data table: {e}", exc_info=True)
            return False

    async def fetch_next_unprocessed_evaluation(self) -> Dict[str, Any] | None:
        """
        Fetches the next unprocessed evaluation entry.
        """
        record = await self.evaluation_data_repo.get_unprocessed_record()
        if record:
            # Deserialize JSONB fields if they are not automatically converted by asyncpg
            # (asyncpg usually handles JSONB to Python dict/list automatically)
            record['steps'] = json.loads(record['steps']) if isinstance(record['steps'], str) else record['steps']
            record['executor_messages'] = json.loads(record['executor_messages']) if isinstance(record['executor_messages'], str) else record['executor_messages']
            log.info(f"Fetched unprocessed evaluation entry with ID: {record['id']}.")
            return record
        return None

    async def update_evaluation_status(self, evaluation_id: int, status: str) -> bool:
        """
        Updates the processing status of an evaluation record.
        """
        success = await self.evaluation_data_repo.update_status(evaluation_id, status)
        if success:
            log.info(f"Status for evaluation_id {evaluation_id} updated to '{status}'.")
        else:
            log.error(f"Failed to update status for evaluation_id {evaluation_id} to '{status}'.")
        return success

    async def insert_tool_metrics(self, metrics_data: Dict[str, Any]) -> bool:
        """
        Inserts tool evaluation metrics.
        """
        success = await self.tool_evaluation_metrics_repo.insert_metrics_record(metrics_data)
        if success:
            log.info(f"Tool evaluation metrics inserted successfully for evaluation_id: {metrics_data.get('evaluation_id')}.")
        else:
            log.error(f"Failed to insert tool evaluation metrics for evaluation_id: {metrics_data.get('evaluation_id')}.")
        return success

    async def insert_agent_metrics(self, metrics_data: Dict[str, Any]) -> bool:
        """
        Inserts agent evaluation metrics.
        """
        # Ensure JSONB fields are dumped if not already
        metrics_data['consistency_queries'] = json.dumps(metrics_data.get('consistency_queries', []))
        metrics_data['robustness_queries'] = json.dumps(metrics_data.get('robustness_queries', []))

        success = await self.agent_evaluation_metrics_repo.insert_metrics_record(metrics_data)
        if success:
            log.info(f"Agent Evaluation metrics inserted successfully for evaluation_id: {metrics_data.get('evaluation_id')}.")
        else:
            log.error(f"Failed to insert agent evaluation metrics for evaluation_id: {metrics_data.get('evaluation_id')}.")
        return success

    async def get_evaluation_data(self, agent_names: Optional[List[str]] = None, page: int = 1, limit: int = 10) -> List[Dict[str, Any]]:
        """
        Retrieves evaluation data records.
        """
        return await self.evaluation_data_repo.get_records_by_agent_names(agent_names, page, limit)

    async def get_tool_metrics(self, agent_names: Optional[List[str]] = None, page: int = 1, limit: int = 10) -> List[Dict[str, Any]]:
        """
        Retrieves tool evaluation metrics records.
        """
        return await self.tool_evaluation_metrics_repo.get_metrics_by_agent_names(agent_names, page, limit)

    async def get_agent_metrics(self, agent_names: Optional[List[str]] = None, page: int = 1, limit: int = 10) -> List[Dict[str, Any]]:
        """
        Retrieves agent evaluation metrics records.
        """
        return await self.agent_evaluation_metrics_repo.get_metrics_by_agent_names(agent_names, page, limit)
