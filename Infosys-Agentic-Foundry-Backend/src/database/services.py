# © 2024-25 Infosys Limited, Bangalore, India. All Rights Reserved.
import re
import json
import uuid
import inspect
import pandas as pd
from datetime import datetime, timezone
from typing import List, Optional, Union, Dict, Any, Literal

from fastapi import UploadFile
from langchain_core.tools import BaseTool, StructuredTool
from langchain_core.prompts import PromptTemplate
from langchain_core.output_parsers import StrOutputParser
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage, ChatMessage, AnyMessage
from langchain_mcp_adapters.client import MultiServerMCPClient
from langchain_community.embeddings import HuggingFaceEmbeddings
from sentence_transformers import CrossEncoder

from src.database.repositories import (
    TagRepository, TagToolMappingRepository, TagAgentMappingRepository,
    ToolRepository, ToolAgentMappingRepository, RecycleToolRepository,
    AgentRepository, RecycleAgentRepository, ChatHistoryRepository,
    FeedbackLearningRepository, EvaluationDataRepository,
    ToolEvaluationMetricsRepository, AgentEvaluationMetricsRepository,
    ExportAgentRepository, McpToolRepository
)
from src.models.model_service import ModelService
from src.prompts.prompts import CONVERSATION_SUMMARY_PROMPT
from src.tools.tool_code_processor import ToolCodeProcessor
from src.utils.secrets_handler import get_user_secrets
from telemetry_wrapper import logger as log, update_session_context
from src.tools.tool_validation import graph



# --- Tag Service ---

class TagService:
    """
    Service layer for managing tags and their associations with tools and agents.
    Applies business rules and orchestrates repository calls.
    """

    def __init__(
        self,
        tag_repo: TagRepository,
        tag_tool_mapping_repo: TagToolMappingRepository,
        tag_agent_mapping_repo: TagAgentMappingRepository
    ):
        self.tag_repo = tag_repo
        self.tag_tool_mapping_repo = tag_tool_mapping_repo
        self.tag_agent_mapping_repo = tag_agent_mapping_repo


    # Tags Operations

    async def create_tag(self, tag_name: str, created_by: str) -> Dict[str, Any]:
        """
        Creates a new tag record.

        Args:
            tag_name (str): The name of the tag to insert.
            created_by (str): The user who created the tag.

        Returns:
            dict: The status of the tag creation operation.
        """
        tag_id = str(uuid.uuid4())
        success = await self.tag_repo.insert_tag_record(tag_id, tag_name, created_by)

        if success:
            return {
                "message": f"Successfully inserted tag with tag_id: {tag_id}",
                "tag_id": tag_id,
                "tag_name": tag_name,
                "created_by": created_by,
                "is_created": True
            }
        else:
            return {
                "message": f"Integrity error: Tag '{tag_name}' already exists or another error occurred.",
                "tag_id": "",
                "tag_name": tag_name,
                "created_by": created_by,
                "is_created": False
            }

    async def get_all_tags(self) -> List[Dict[str, Any]]:
        """
        Retrieves all tag records.

        Returns:
            list: A list of tags, represented as dictionaries.
        """
        return await self.tag_repo.get_all_tag_records()

    async def get_tag(self, tag_id: Optional[str] = None, tag_name: Optional[str] = None) -> Dict[str, Any] | None:
        """
        Retrieves a single tag record by ID or name.

        Args:
            tag_id (str, optional): Tag ID.
            tag_name (str, optional): Tag name.

        Returns:
            dict: A dictionary representing the retrieved tag, or None if not found.
        """
        return await self.tag_repo.get_tag_record(tag_id=tag_id, tag_name=tag_name)

    async def update_tag(self, new_tag_name: str, created_by: str, tag_id: Optional[str] = None, tag_name: Optional[str] = None) -> Dict[str, Any]:
        """
        Updates the name of an existing tag.

        Args:
            new_tag_name (str): The new name for the tag.
            created_by (str): The ID of the user performing the update.
            tag_id (str, optional): The ID of the tag to update.
            tag_name (str, optional): The current name of the tag to update.

        Returns:
            dict: Status of the operation.
        """
        if not tag_id and not tag_name:
            return {"message": "Tag ID or Tag Name is required.", "is_updated": False}

        # First, get the tag to ensure it exists and get its ID if only name is provided
        current_tag = await self.get_tag(tag_id=tag_id, tag_name=tag_name)
        if not current_tag:
            return {"message": f"No tag found with ID: {tag_id} or Name: {tag_name}.", "is_updated": False}

        if current_tag['created_by'] != created_by:
            return {"message": "Permission denied: Only the tag's creator can update it.", "is_updated": False}

        success = await self.tag_repo.update_tag_record(current_tag['tag_id'], new_tag_name, created_by)

        if success:
            return {
                "message": f"Successfully updated tag with ID: {current_tag['tag_id']}",
                "tag_id": current_tag['tag_id'],
                "tag_name": new_tag_name,
                "is_updated": True
            }
        else:
            return {
                "message": f"Failed to update tag with ID: {current_tag['tag_id']}.",
                "tag_id": current_tag['tag_id'],
                "tag_name": current_tag['tag_name'],
                "is_updated": False
            }

    async def delete_tag(self, created_by: str, tag_id: Optional[str] = None, tag_name: Optional[str] = None) -> Dict[str, Any]:
        """
        Deletes a tag record after checking if it's in use.

        Args:
            created_by (str): The ID of the user performing the deletion.
            tag_id (str, optional): The ID of the tag to delete.
            tag_name (str, optional): The name of the tag to delete.

        Returns:
            dict: Status of the operation.
        """
        if not tag_id and not tag_name:
            return {"message": "Tag ID or Tag Name is required.", "is_deleted": False}

        current_tag = await self.get_tag(tag_id=tag_id, tag_name=tag_name)
        if not current_tag:
            return {"message": f"No tag found with ID: {tag_id} or Name: {tag_name}.", "is_deleted": False}

        if current_tag['created_by'] != created_by:
            return {"message": "Permission denied: Only the tag's creator can delete it.", "is_deleted": False}

        if await self.is_tag_in_use(tag_id=current_tag['tag_id']):
            return {
                "message": f"Cannot delete tag {current_tag['tag_name']}, it is in use by an agent or a tool.",
                "tag_id": current_tag['tag_id'],
                "tag_name": current_tag['tag_name'],
                "is_deleted": False
            }

        success = await self.tag_repo.delete_tag_record(current_tag['tag_id'], created_by)

        if success:
            return {
                "message": f"Successfully deleted tag with ID: {current_tag['tag_id']}",
                "tag_id": current_tag['tag_id'],
                "tag_name": current_tag['tag_name'],
                "is_deleted": True
            }
        else:
            return {
                "message": f"Failed to delete tag with ID: {current_tag['tag_id']}.",
                "tag_id": current_tag['tag_id'],
                "tag_name": current_tag['tag_name'],
                "is_deleted": False
            }

    # Tags Helper functions

    async def clear_tags(self, tool_id: Optional[str] = None, agent_id: Optional[str] = None) -> bool:
        """
        Clears all tags associated with a given tool ID or agent ID.

        Args:
            tool_id (str, optional): The ID of the tool.
            agent_id (str, optional): The ID of the agent.

        Returns:
            bool: True if the operation was successful, False otherwise.
        """
        if not tool_id and not agent_id:
            log.error("Either tool_id or agent_id must be provided to clear tags.")
            return False

        if tool_id:
            return await self.tag_tool_mapping_repo.delete_all_tags_for_tool(tool_id)
        elif agent_id:
            return await self.tag_agent_mapping_repo.delete_all_tags_for_agent(agent_id)
        return False

    async def is_tag_in_use(self, tag_id: Optional[str] = None, tag_name: Optional[str] = None) -> bool:
        """
        Checks if a given tag ID or tag name is being used by any agent or tool.

        Args:
            tag_id (str, optional): The ID of the tag.
            tag_name (str, optional): The name of the tag.

        Returns:
            bool: True if the tag is in use, False otherwise.
        """
        if not tag_id and not tag_name:
            log.error("Either tag_id or tag_name must be provided to check usage.")
            return False

        if not tag_id: # If only name is provided, get the ID
            tag_record = await self.tag_repo.get_tag_record(tag_name=tag_name)
            if tag_record:
                tag_id = tag_record['tag_id']
            else:
                return False # Tag doesn't exist, so it's not in use

        # Check if the tag_id is used in tool_tag_mapping_table
        tool_mappings = await self.tag_tool_mapping_repo.get_tool_tag_mappings()
        if any(m['tag_id'] == tag_id for m in tool_mappings):
            return True

        # Check if the tag_id is used in agent_tag_mapping_table
        agent_mappings = await self.tag_agent_mapping_repo.get_agent_tag_mappings()
        if any(m['tag_id'] == tag_id for m in agent_mappings):
            return True

        return False

    async def get_tag_id_to_tag_dict(self) -> Dict[str, Any]:
        """
        Fetches all tags and returns them as a dictionary keyed by tag_id.

        Returns:
            dict: A dictionary where each key is a tag_id and the value is a dictionary
                  of the tag's details.
        """
        all_tags = await self.tag_repo.get_all_tag_records()
        return {tag['tag_id']: tag for tag in all_tags}

    # Tags and Tools Operations

    async def assign_tags_to_tool(self, tag_ids: Union[List[str], str], tool_id: str) -> Dict[str, Any]:
        """
        Assigns tags to a tool.

        Args:
            tag_ids (Union[List[str], str]): The ID(s) of the tag(s).
            tool_id (str): The ID of the tool.

        Returns:
            dict: Status of the operation.
        """
        if isinstance(tag_ids, str):
            tag_ids = [tag_ids]

        inserted_tags = []
        failed_tags = []

        for tag_id in tag_ids:
            success = await self.tag_tool_mapping_repo.assign_tag_to_tool_record(tag_id, tool_id)
            if success:
                inserted_tags.append(tag_id)
            else:
                failed_tags.append(tag_id) # Simplified error message for now

        return {
            "message": f"Inserted mappings for tag_ids: {inserted_tags}. Failed for tag_ids: {failed_tags}",
            "inserted_tag_ids": inserted_tags,
            "failed_tag_ids": failed_tags,
            "tool_id": tool_id,
            "is_created": len(inserted_tags) > 0
        }

    async def remove_tags_from_tool(self, tag_ids: Union[List[str], str], tool_id: str) -> Dict[str, Any]:
        """
        Removes tags from a tool.

        Args:
            tag_ids (Union[List[str], str]): The ID(s) of the tag(s).
            tool_id (str): The ID of the tool.

        Returns:
            dict: Status of the operation.
        """
        if isinstance(tag_ids, str):
            tag_ids = [tag_ids]

        deleted_count = 0
        for tag_id in tag_ids:
            success = await self.tag_tool_mapping_repo.remove_tag_from_tool_record(tag_id, tool_id)
            if success:
                deleted_count += 1

        if deleted_count > 0:
            return {
                "message": f"Successfully deleted {deleted_count} mappings.",
                "tag_ids": tag_ids,
                "tool_id": tool_id,
                "is_deleted": True
            }
        else:
            return {
                "message": "No mappings found or deleted.",
                "tag_ids": tag_ids,
                "tool_id": tool_id,
                "is_deleted": False
            }

    async def get_tool_id_to_tags_dict(self) -> Dict[str, Any]:
        """
        Fetches the mapping between tools and their associated tags.

        Returns:
            dict: A dictionary where each key is a tool_id and the value is a list of tag detail dictionaries.
        """
        tool_to_tags_map = {}
        all_tags_dict = await self.get_tag_id_to_tag_dict()
        raw_mappings = await self.tag_tool_mapping_repo.get_tool_tag_mappings()

        for mapping in raw_mappings:
            tool_id = mapping['tool_id']
            tag_id = mapping['tag_id']
            tag_details = all_tags_dict.get(tag_id)
            if tag_details:
                if tool_id not in tool_to_tags_map:
                    tool_to_tags_map[tool_id] = []
                tool_to_tags_map[tool_id].append(tag_details)
        return tool_to_tags_map

    async def get_tags_by_tool(self, tool_id: str) -> List[Dict[str, Any]]:
        """
        Retrieves tags associated with a given tool ID.

        Args:
            tool_id (str): The ID of the tool.

        Returns:
            list: A list of tags associated with the tool, represented as dictionaries.
        """
        tag_ids = await self.tag_tool_mapping_repo.get_tags_by_tool_id_records(tool_id)
        if not tag_ids:
            return []

        all_tags_dict = await self.get_tag_id_to_tag_dict()
        return [all_tags_dict[tag_id] for tag_id in tag_ids if tag_id in all_tags_dict]

    # Tags and Agent Operations

    async def assign_tags_to_agent(self, tag_ids: Union[List[str], str], agentic_application_id: str) -> Dict[str, Any]:
        """
        Assigns tags to an agent.

        Args:
            tag_ids (Union[List[str], str]): The ID(s) of the tag(s).
            agentic_application_id (str): The ID of the agentic application.

        Returns:
            dict: Status of the operation.
        """
        if isinstance(tag_ids, str):
            tag_ids = [tag_ids]

        inserted_tags = []
        failed_tags = []

        for tag_id in tag_ids:
            success = await self.tag_agent_mapping_repo.assign_tag_to_agent_record(tag_id, agentic_application_id)
            if success:
                inserted_tags.append(tag_id)
            else:
                failed_tags.append(tag_id) # Simplified error message for now

        return {
            "message": f"Inserted mappings for tag_ids: {inserted_tags}. Failed for tag_ids: {failed_tags}",
            "inserted_tag_ids": inserted_tags,
            "failed_tag_ids": failed_tags,
            "agentic_application_id": agentic_application_id,
            "is_created": len(inserted_tags) > 0
        }

    async def remove_tags_from_agent(self, tag_ids: Union[List[str], str], agentic_application_id: str) -> Dict[str, Any]:
        """
        Removes tags from an agent.

        Args:
            tag_ids (Union[List[str], str]): The ID(s) of the tag(s).
            agentic_application_id (str): The ID of the agentic application.

        Returns:
            dict: Status of the operation.
        """
        if isinstance(tag_ids, str):
            tag_ids = [tag_ids]

        deleted_count = 0
        for tag_id in tag_ids:
            success = await self.tag_agent_mapping_repo.remove_tag_from_agent_record(tag_id, agentic_application_id)
            if success:
                deleted_count += 1

        if deleted_count > 0:
            return {
                "message": f"Successfully deleted {deleted_count} mappings.",
                "tag_ids": tag_ids,
                "agentic_application_id": agentic_application_id,
                "is_deleted": True
            }
        else:
            return {
                "message": "No mappings found or deleted.",
                "tag_ids": tag_ids,
                "agentic_application_id": agentic_application_id,
                "is_deleted": False
            }

    async def get_agent_id_to_tags_dict(self) -> Dict[str, Any]:
        """
        Fetches the mapping between agents and their associated tags.

        Returns:
            dict: A dictionary where each key is an agentic_application_id and the value is a list of tag detail dictionaries.
        """
        agent_to_tags_map = {}
        all_tags_dict = await self.get_tag_id_to_tag_dict()
        raw_mappings = await self.tag_agent_mapping_repo.get_agent_tag_mappings()

        for mapping in raw_mappings:
            agent_id = mapping['agentic_application_id']
            tag_id = mapping['tag_id']
            tag_details = all_tags_dict.get(tag_id)
            if tag_details:
                if agent_id not in agent_to_tags_map:
                    agent_to_tags_map[agent_id] = []
                agent_to_tags_map[agent_id].append(tag_details)
        return agent_to_tags_map

    async def get_tags_by_agent(self, agent_id: str) -> List[Dict[str, Any]]:
        """
        Retrieves tags associated with a given agent ID.

        Args:
            agent_id (str): The ID of the agent.

        Returns:
            list: A list of tags associated with the agent, represented as dictionaries.
        """
        tag_ids = await self.tag_agent_mapping_repo.get_tags_by_agent_id_records(agent_id)
        if not tag_ids:
            return []

        all_tags_dict = await self.get_tag_id_to_tag_dict()
        return [all_tags_dict[tag_id] for tag_id in tag_ids if tag_id in all_tags_dict]


# --- McpToolService ---

class McpToolService:
    """
    Service layer for managing MCP tools (server definitions).
    Handles business rules, file management for code-based MCPs,
    and orchestrates repository calls.
    """

    def __init__(
        self,
        mcp_tool_repo: McpToolRepository,
        tag_service: TagService, # Needed for tag mapping
        tool_agent_mapping_repo: ToolAgentMappingRepository, # Needed for dependency checks
        agent_repo: AgentRepository # Needed for dependency checks
    ):
        self.mcp_tool_repo = mcp_tool_repo
        self.tag_service = tag_service
        self.tool_agent_mapping_repo = tool_agent_mapping_repo
        self.agent_repo = agent_repo
        self.VAULT_PREFIX = "VAULT::"

    # --- Helper Methods for File Management ---

    @staticmethod
    async def _get_mcp_type_by_id(tool_id: str) -> Optional[str]:
        """
        Extracts the MCP type from the tool_id prefix.
        Expected prefixes: 'mcp_file_', 'mcp_url_', 'mcp_module_'
        """
        if tool_id.startswith("mcp_file_"):
            return "file"
        elif tool_id.startswith("mcp_url_"):
            return "url"
        elif tool_id.startswith("mcp_module_"):
            return "module"
        else:
            return "invalid"

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

    # --- MCP Tool Creation Operations ---

    async def create_mcp_tool(
            self,
            tool_name: str,
            tool_description: str,
            mcp_type: Literal["file", "url", "module"],
            created_by: str,
            tag_ids: Optional[Union[List[str], str]] = None,
            mcp_url: Optional[str] = None,
            headers: Optional[Dict[str, str]] = None,
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
            mcp_config["command"] = "python"
            mcp_config["args"] = ["-c", code_content]

        elif mcp_type == "url":
            if not mcp_url:
                return {"message": "URL is required for 'url' type MCP tools.", "is_created": False}
            mcp_config["url"] = mcp_url
            mcp_config["transport"] = "streamable_http" # URL-based typically use HTTP
            if headers:             # Add headers if provided
                mcp_config["headers"] = headers

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
            record["mcp_type"] = await self._get_mcp_type_by_id(record['tool_id'])
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
            tool["mcp_type"] = await self._get_mcp_type_by_id(tool['tool_id'])
            tool['tags'] = tool_id_to_tags.get(tool['tool_id'], [])
        log.info(f"Retrieved {len(tool_records)} MCP tools.")
        return tool_records

    async def get_mcp_tools_by_search_or_page(self, search_value: str = '', limit: int = 20, page: int = 1, tag_names: Optional[List[str]] = None, mcp_type: Optional[List[Literal["file", "url", "module"]]] = None) -> Dict[str, Any]:
        """
        Retrieves MCP tools (server definitions) with pagination and search filtering, including associated tags.
        """
        total_count = await self.mcp_tool_repo.get_total_mcp_tool_count(search_value, mcp_type)
        if tag_names:
            tag_names = set(tag_names)
            tool_records = await self.mcp_tool_repo.get_mcp_tools_by_search_or_page_records(search_value, total_count, 1, mcp_type)
        else:
            tool_records = await self.mcp_tool_repo.get_mcp_tools_by_search_or_page_records(search_value, limit, page, mcp_type)

        tool_id_to_tags = await self.tag_service.get_tool_id_to_tags_dict()
        filtered_tools = []

        for tool in tool_records:
            if isinstance(tool.get("mcp_config"), str):
                tool["mcp_config"] = json.loads(tool["mcp_config"])
            tool["mcp_type"] = await self._get_mcp_type_by_id(tool['tool_id'])                     
            tool['tags'] = tool_id_to_tags.get(tool['tool_id'], [])
            if tag_names:
                for tag in tool['tags']:
                    if tag['tag_name'] in tag_names:
                        filtered_tools.append(tool)
                        break

        if tag_names:
            total_count = len(filtered_tools)
            offset = limit * max(0, page-1)
            filtered_tools = filtered_tools[offset: offset + limit]
        else:
            filtered_tools = tool_records

        return {
            "total_count": total_count,
            "details": filtered_tools
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
        if tool_id.startswith("mcp_file_") and code_content:
            if isinstance(tool_data.get("mcp_config"), str):
                tool_data["mcp_config"] = json.loads(tool_data["mcp_config"])
            tool_data["mcp_config"]["args"][1] = code_content.strip() # Update code content

            update_payload["mcp_config"] = tool_data["mcp_config"] # Add updated config to payload
            log.info(f"Code content updated for MCP file tool ID: {tool_id}")


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

    async def get_tools_from_mcp_configs(self, mcp_configs: Dict[str, Dict[str, Any]]) -> List[StructuredTool]:
        """
        Connects to multiple MCP server(s) defined by the given mcp_configs and discovers
        all tools they expose.

        Args:
            mcp_configs (Dict[str, Dict[str, Any]]): A dictionary where each key is a unique server name
                                                     and the value is the MCP configuration dictionary.

        Returns:
            List[StructuredTool]: A list of StructuredTool instances discovered from all servers.
        """
        for server_name, config in mcp_configs.items():
            headers: dict = config.get("headers", None)
            if not headers:
                continue
            for k, v in headers.items():
                if isinstance(v, str) and v.startswith(self.VAULT_PREFIX):
                    vault_key = v[len(self.VAULT_PREFIX):].strip()
                    vault_val = get_user_secrets(vault_key, None)
                    if not vault_val:
                        raise ValueError(f"Vault key '{vault_key}' not found for MCP server '{server_name}'.")
                    headers[k] = vault_val

        try:
            log.info(f"Connecting to {len(mcp_configs)} MCP servers.")
            client = MultiServerMCPClient(mcp_configs)
            all_tools = await client.get_tools()
            log.info(f"Discovered {len(all_tools)} tools from {len(mcp_configs)} MCP servers.")
            return all_tools

        except Exception as e:
            log.error(f"Error discovering tools from MCP servers: {e}")
            raise

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
            mcp_server_data["mcp_config"] = mcp_config = json.loads(mcp_config)

        try:
            mcp_server_data["live_tools"] = await self.get_tools_from_mcp_configs({mcp_server_data["tool_name"]: mcp_config})
            log.info(f"Discovered {len(mcp_server_data['live_tools'])} tools from live MCP server: {mcp_server_data['tool_name']}")
            return mcp_server_data

        except Exception as e:
            log.error(f"Error discovering tools from MCP server {mcp_server_data['tool_name']} ({tool_id}): {e}")
            raise ValueError(f"Failed to connect to or discover tools from MCP server: {e}")

    async def get_live_mcp_tools_from_servers(self, tool_ids: List[str]) -> Dict[str, Any]:
        """
        Connects to multiple live MCP server(s) defined by the given tool_id(s) and discovers
        all tools they expose in a single batch operation.

        Args:
            tool_ids (List[str]): A list of tool_id(s) for the MCP server definitions in the database.

        Returns:
            Dict[str, Any]: A dictionary with the following structure:
                            {
                                "tool_id_1": mcp_server_data_1,  # Database record for server 1
                                "tool_id_2": mcp_server_data_2,  # Database record for server 2
                                # ... (for each successfully processed tool_id) ...
                                "tool_id_with_error_A": {"error": "Error message A"}, # For servers that failed to load config
                                "all_live_tools": [
                                    StructuredTool_from_server_1_tool_A,
                                    StructuredTool_from_server_1_tool_B,
                                    StructuredTool_from_server_2_tool_X,
                                    # ... all live tools from all successfully connected servers combined
                                ]
                            }
                            Note: The individual mcp_server_data entries will NOT have a "live_tools" key.
                                  All discovered tools are combined into the top-level "all_live_tools" list.
        """
        server_configs_for_client: Dict[str, Dict[str, Any]] = {}
        server_details_map: Dict[str, Any] = {} # To store the original mcp_server_data (DB record)
        
        # First pass: Collect all server configurations and original DB data
        for single_tool_id in tool_ids:
            if not single_tool_id.startswith("mcp_"):
                continue

            try:
                tool_records = await self.mcp_tool_repo.get_mcp_tool_record(tool_id=single_tool_id)
                if not tool_records:
                    server_details_map[single_tool_id] = {"error": f"MCP server definition not found for tool_id: {single_tool_id}"}
                    log.warning(f"MCP server definition not found for tool_id: {single_tool_id}")
                    continue

                mcp_server_data = tool_records[0]
                mcp_config = mcp_server_data["mcp_config"]

                # Ensure mcp_config is a Python dict
                if isinstance(mcp_config, str):
                    mcp_server_data["mcp_config"] = mcp_config = json.loads(mcp_config)

                # Store the prepared config for the MultiServerMCPClient
                server_configs_for_client[mcp_server_data["tool_name"]] = mcp_config

                # Store the original mcp_server_data (DB record) for the final return map
                server_details_map[single_tool_id] = mcp_server_data

            except Exception as e:
                server_details_map[single_tool_id] = {"error": f"Failed to prepare config for MCP server {mcp_server_data.get('tool_name', single_tool_id)} ({single_tool_id}): {e}"}
                log.error(f"Error preparing config for MCP server {mcp_server_data.get('tool_name', single_tool_id)} ({single_tool_id}): {e}")

        all_combined_live_tools: List[StructuredTool] = []
        if server_configs_for_client:
            try:
                all_combined_live_tools = await self.get_tools_from_mcp_configs(server_configs_for_client)
                log.info(f"Discovered {len(all_combined_live_tools)} tools from {len(server_configs_for_client)} live MCP servers.")
            except Exception as e:
                # This error applies to all servers if the client itself fails to initialize or connect
                log.error(f"Error during batch discovery from MCP servers: {e}")
                # Update all successfully prepared server entries with a general error
                for tool_id_key in server_details_map.keys():
                    if "error" not in server_details_map[tool_id_key]: # Don't overwrite specific config errors
                        server_details_map[tool_id_key] = {"error": f"Failed to connect to MCP servers for batch discovery: {e}"}
        else:
            log.info("No valid MCP server configurations to attempt batch discovery.")

        # Add the combined list of all live tools at the top level
        server_details_map["all_live_tools"] = all_combined_live_tools

        return server_details_map

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
        recycle_tool_repo: RecycleToolRepository,
        tool_agent_mapping_repo: ToolAgentMappingRepository,
        tag_service: TagService,
        tool_code_processor: ToolCodeProcessor,
        agent_repo: AgentRepository, # Need agent_repo for dependency checks
        model_service: ModelService,
        mcp_tool_service: McpToolService # Inject the new MCP Tool Service
    ):
        self.tool_repo = tool_repo
        self.recycle_tool_repo = recycle_tool_repo
        self.tool_agent_mapping_repo = tool_agent_mapping_repo
        self.tag_service = tag_service
        self.tool_code_processor = tool_code_processor
        self.agent_repo = agent_repo # Store agent_repo for direct use in dependency checks
        self.model_service = model_service
        self.mcp_tool_service = mcp_tool_service # Store MCP Tool Service

    # --- Tool Creation Operations ---

    async def create_tool(self, tool_data: Dict[str, Any],force_add) -> Dict[str, Any]:
        """
        Creates a new tool, including validation, docstring generation, and saving to the database.

        Args:
            tool_data (dict): A dictionary containing the tool data to save.

        Returns:
            dict: Status of the operation, including success message or error details.
        """
        validation_status = await self.tool_code_processor.validate_and_extract_tool_name(code_str=tool_data.get("code_snippet", ""))
        if "error" in validation_status:
            log.error(f"Tool creation failed: {validation_status['error']}")
            return {
                "message": validation_status["error"],
                "tool_id": "",
                "is_created": False
            }

        tool_data["tool_name"] = validation_status["function_name"]
        update_session_context(tool_name=tool_data["tool_name"])

        if await self.recycle_tool_repo.is_tool_in_recycle_bin_record(tool_name=tool_data["tool_name"]):
            log.info(f"Tool Insertion Status: Integrity error inserting data: Tool name {tool_data['tool_name']} already exists in recycle bin.")
            return {
                "message": f"Integrity error inserting data: Tool name {tool_data['tool_name']} already exists in recycle bin.",
                "tool_id": "",
                "tool_name": tool_data['tool_name'],
                "model_name": tool_data.get('model_name', ''),
                "created_by": tool_data.get('created_by', ''),
                "is_created": False
            }
        initial_state = {
                "code": tool_data["code_snippet"],
                "validation_case1": None,
                "feedback_case1": None,
                "validation_case3": None,
                "feedback_case3": None,
                "validation_case4": None,
                "feedback_case4": None,
                "validation_case5": None,
                "feedback_case5": None,
                "validation_case6": None,
                "feedback_case6": None,
                "validation_case7": None,
                "feedback_case7": None
            }
        workflow_result = await graph.ainvoke(input=initial_state)
        w_cases=["validation_case3","validation_case5"]
        e_cases=["validation_case1","validation_case6","validation_case4","validation_case7"]
        warnings={}
        errors={}
        for i in w_cases:
            if not workflow_result.get(i):
                feedback_key = i.replace("validation_", "feedback_")
                if workflow_result.get(feedback_key):
                    warnings[i] = workflow_result.get(feedback_key)
        for j in e_cases:
            if not workflow_result.get(j):
                feedback_key = j.replace("validation_", "feedback_")
                errors[j] = workflow_result.get(feedback_key)
        # if warnings and not force_add:
        #         verify=list(warnings.values())
        #         return {
        #             "message": ("Verification failed: "+str(verify)),
        #             "tool_id": "",
        #             "is_created": False
        #         }
        if errors:
            verify=list(errors.values())
            return {
                    "message": verify[0],
                    "tool_id": "",
                    "tool_name": tool_data['tool_name'],
                    "model_name": tool_data.get('model_name', ''),
                    "created_by": tool_data.get('created_by', ''),
                    "is_created": False
                }
        if warnings and not force_add:
                verify=list(warnings.values())
                return {
                    "message": ("Verification failed: "+str(verify)),
                    "tool_id": "",
                    "is_created": False
                }
        if not tool_data.get("tool_id"):
            tool_data["tool_id"] = str(uuid.uuid4())
            update_session_context(tool_id=tool_data.get("tool_id", None))

        if not tool_data.get("tag_ids"):
            general_tag = await self.tag_service.get_tag(tag_name="General")
            tool_data['tag_ids'] = [general_tag['tag_id']] if general_tag else []

        llm = await self.model_service.get_llm_model(model_name=tool_data["model_name"])
        docstring_generation = await self.tool_code_processor.generate_docstring_for_tool_onboarding(
            llm=llm,
            tool_code_str=tool_data["code_snippet"],
            tool_description=tool_data["tool_description"]
        )
        if "error" in docstring_generation:
            log.error(f"Tool Onboarding Failed: {docstring_generation['error']}")
            return {
                "message": docstring_generation['error'],
                "tool_id": "",
                "tool_name": tool_data['tool_name'],
                "model_name": tool_data.get('model_name', ''),
                "created_by": tool_data.get('created_by', ''),
                "is_created": False
            }
        tool_data["code_snippet"] = docstring_generation["code_snippet"]

        now = datetime.now(timezone.utc).replace(tzinfo=None)
        tool_data['created_on'] = now
        tool_data['updated_on'] = now

        success = await self.tool_repo.save_tool_record(tool_data)

        if success:
            tags_status = await self.tag_service.assign_tags_to_tool(
                tag_ids=tool_data['tag_ids'], tool_id=tool_data['tool_id']
            )
            log.info(f"Successfully onboarded tool with tool_id: {tool_data['tool_id']}")
            return {
                "message": f"Successfully onboarded tool with tool_id: {tool_data['tool_id']}",
                "tool_id": tool_data['tool_id'],
                "tool_name": tool_data['tool_name'],
                "model_name": tool_data.get('model_name', ''),
                "tags_status": tags_status,
                "created_by": tool_data.get('created_by', ''),
                "is_created": True
            }
        else:
            log.info(f"Tool Insertion Status: Integrity error inserting data: Tool name {tool_data['tool_name']} already exists.")
            return {
                "message": f"Integrity error inserting data: Tool name {tool_data['tool_name']} already exists.",
                "tool_id": "",
                "tool_name": tool_data['tool_name'],
                "model_name": tool_data.get('model_name', ''),
                "created_by": tool_data.get('created_by', ''),
                "is_created": False
            }

    # --- Tool Retrieval Operations ---

    async def get_all_tools(self) -> List[Dict[str, Any]]:
        """
        Retrieves all tools with their associated tags.

        Returns:
            list: A list of tools, represented as dictionaries.
        """
        tool_records = await self.tool_repo.get_all_tool_records()
        tool_id_to_tags = await self.tag_service.get_tool_id_to_tags_dict()

        for tool in tool_records:
            tool['tags'] = tool_id_to_tags.get(tool['tool_id'], [])
        return tool_records

    async def get_tools_by_tags(self, tag_ids: Optional[Union[List[str], str]] = None, tag_names: Optional[Union[List[str], str]] = None) -> List[Dict[str, Any]]:
        """
        Retrieves tools associated with given tag IDs or tag names.

        Args:
            tag_ids (Union[List[str], str], optional): A list of tag IDs or a single tag ID.
            tag_names (Union[List[str], str], optional): A list of tag names or a single tag name.

        Returns:
            list: A list of tools associated with the tags, represented as dictionaries.
        """
        if tag_names:
            resolved_tag_ids = []
            for name in (tag_names if isinstance(tag_names, list) else [tag_names]):
                tag_record = await self.tag_service.get_tag(tag_name=name)
                if tag_record:
                    resolved_tag_ids.append(tag_record['tag_id'])
            if tag_ids:
                tag_ids.extend(resolved_tag_ids)
            else:
                tag_ids = resolved_tag_ids

        if not tag_ids:
            log.info("No tag_ids or tag_names provided, returning empty list.")
            return []

        # Get raw tool records that have these tags
        all_tool_records = await self.tool_repo.get_all_tool_records()
        filtered_tools = []
        for tool in all_tool_records:
            tool_tag_ids = await self.tag_service.get_tags_by_tool(tool['tool_id'])
            if any(t['tag_id'] in tag_ids for t in tool_tag_ids):
                filtered_tools.append(tool)

        # Attach full tag details
        tool_id_to_tags = await self.tag_service.get_tool_id_to_tags_dict()
        for tool in filtered_tools:
            tool['tags'] = tool_id_to_tags.get(tool['tool_id'], [])
        return filtered_tools

    async def get_tool(self, tool_id: Optional[str] = None, tool_name: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        Retrieves a single tool record by ID or name, with associated tags.

        Args:
            tool_id (str, optional): Tool ID. Can be used to retrieve both MCP tools (if prefixed with "mcp_") and normal Python function tools.
            tool_name (str, optional): Tool name. Should only be used to retrieve normal Python function tools.

        Returns:
            List[Dict[str, Any]]: A list of dictionaries representing the retrieved tool(s), each with associated tags. Returns an empty list if no tool is found.
        """
        if tool_id and tool_id.startswith("mcp_"):
            return await self.mcp_tool_service.get_mcp_tool(tool_id=tool_id)

        tool_records = await self.tool_repo.get_tool_record(tool_id=tool_id, tool_name=tool_name)

        if not tool_records:
            log.info(f"No tool found with ID: {tool_id} or Name: {tool_name}.")
            return []

        for tool_record in tool_records:
            tool_record['tags'] = await self.tag_service.get_tags_by_tool(tool_record['tool_id'])
        log.info(f"Retrieved tool with ID: {tool_records[0]['tool_id']} and Name: {tool_records[0]['tool_name']}.")
        return tool_records

    async def get_tools_by_search_or_page(self, search_value: str = '', limit: int = 20, page: int = 1, tag_names: Optional[List[str]] = None) -> Dict[str, Any]:
        """
        Retrieves tools with pagination and search filtering, including associated tags.

        Args:
            search_value (str, optional): Tool name to filter by.
            limit (int, optional): Number of results per page.
            page (int, optional): Page number for pagination.

        Returns:
            dict: A dictionary containing the total count of tools and the paginated tool details.
        """
        total_count = await self.tool_repo.get_total_tool_count(search_value)

        if tag_names:
            tag_names = set(tag_names)
            tool_records = await self.tool_repo.get_tools_by_search_or_page_records(search_value, total_count, 1)
        else:
            tool_records = await self.tool_repo.get_tools_by_search_or_page_records(search_value, limit, page)

        tool_id_to_tags = await self.tag_service.get_tool_id_to_tags_dict()
        filtered_tools = []

        for tool in tool_records:
            tool['tags'] = tool_id_to_tags.get(tool['tool_id'], [])
            if tag_names:
                for tag in tool['tags']:
                    if tag['tag_name'] in tag_names:
                        filtered_tools.append(tool)
                        break

        if tag_names:
            total_count = len(filtered_tools)
            offset = limit * max(0, page - 1)
            filtered_tools = filtered_tools[offset : offset + limit]
        else:
            filtered_tools = tool_records

        return {
            "total_count": total_count,
            "details": filtered_tools
        }

    # --- Tool Updation Operations ---

    async def update_tool(self, tool_id: str, model_name: str, code_snippet: str = "", tool_description: str = "", updated_tag_id_list: Optional[Union[List[str], str]] = None, user_id: Optional[str] = None, is_admin: bool = False) -> Dict[str, Any]:
        """
        Updates an existing tool record, including code validation, docstring regeneration,
        permission checks, dependency checks, and tag updates.

        Args:
            tool_id (str): The ID of the tool to update.
            model_name (str): The model name to use for docstring generation.
            code_snippet (str, optional): New code snippet for the tool.
            tool_description (str, optional): New description for the tool.
            updated_tag_id_list (Union[List, str], optional): List of new tag IDs for the tool.
            user_id (str, optional): The ID of the user performing the update.
            is_admin (bool, optional): Whether the user has admin privileges.

        Returns:
            dict: Status of the update operation.
        """
        tool_data = await self.tool_repo.get_tool_record(tool_id=tool_id)
        if not tool_data:
            log.error(f"Error: Tool not found with ID: {tool_id}")
            return {
                "status_message": f"Error: Tool not found with ID: {tool_id}",
                "details": [],
                "is_update": False
            }
        tool_data = tool_data[0]

        if not is_admin and tool_data["created_by"] != user_id:
            err = f"Permission denied: Only the admin or the tool's creator can perform this action for Tool ID: {tool_id}."
            log.error(err)
            return {
                "status_message": err,
                "details": [],
                "is_update": False
            }

        if not tool_description and not code_snippet and updated_tag_id_list is None:
            log.error("Error: Please specify at least one of the following fields to modify: tool_description, code_snippet, tags.")
            return {
                "status_message": "Error: Please specify at least one of the following fields to modify: tool_description, code_snippet, tags.",
                "details": [],
                "is_update": False
            }

        tag_update_status = None
        if updated_tag_id_list:
            await self.tag_service.clear_tags(tool_id=tool_id) # Clear existing tags
            tag_update_status = await self.tag_service.assign_tags_to_tool(tag_ids=updated_tag_id_list, tool_id=tool_id)
            log.info("Successfully updated tags for the tool.")

        if not tool_description and not code_snippet: # Only tags were updated
            log.info("No modifications made to the tool attributes.")
            return {
                "status_message": "Tags updated successfully",
                "details": [],
                "tag_update_status": tag_update_status,
                "is_update": True
            }

        if code_snippet:
            validation_status = await self.tool_code_processor.validate_and_extract_tool_name(code_str=code_snippet)
            if "error" in validation_status:
                log.error(f"Tool updation failed: {validation_status['error']}")
                return {
                    "status_message": validation_status["error"],
                    "details": [],
                    "is_update": False
                }
            if validation_status["function_name"] != tool_data["tool_name"]:
                err = f"Tool name mismatch: Provided function name \'{validation_status['function_name']}\' does not match existing tool name \'{tool_data['tool_name']}\'."
                log.error(err)
                return {
                    "status_message": err,
                    "details": [],
                    "is_update": False
                }
            tool_data["code_snippet"] = code_snippet # Update for docstring generation

        if tool_description:
            tool_data["tool_description"] = tool_description

        # Check for agent dependencies before updating core tool data
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
                return {
                    "status_message": f"The tool you are trying to update is being referenced by {len(agent_details)} agentic applications.",
                    "details": agent_details,
                    "is_update": False
                }

        llm = await self.model_service.get_llm_model(model_name=model_name)
        docstring_generation = await self.tool_code_processor.generate_docstring_for_tool_onboarding(
            llm=llm,
            tool_code_str=tool_data["code_snippet"],
            tool_description=tool_data["tool_description"]
        )
        if "error" in docstring_generation:
            log.error(f"Tool Update Failed: {docstring_generation['error']}")
            return {
                "status_message": f"Tool Update Failed: {docstring_generation['error']}",
                "details": [],
                "is_update": False
            }
        tool_data["code_snippet"] = docstring_generation["code_snippet"]
        tool_data["model_name"] = model_name # Ensure model name is updated if changed

        success = await self.tool_repo.update_tool_record(tool_data, tool_id)

        if success:
            status = {
                "status_message": "Successfully updated the tool.",
                "details": [],
                "is_update": True
            }
        else:
            status = {
                "status_message": "Failed to update the tool.",
                "details": [],
                "is_update": False
            }

        if tag_update_status:
            status['tag_update_status'] = tag_update_status
        log.info(f"Tool update status: {status['status_message']}")
        return status

    # --- Tool Deletion Operations ---

    async def delete_tool(self, tool_id: Optional[str] = None, tool_name: Optional[str] = None, user_id: Optional[str] = None, is_admin: bool = False) -> Dict[str, Any]:
        """
        Deletes a tool by moving it to the recycle bin and then removing it from the main tool table.
        It checks for user permissions and dependencies before deletion.

        Args:
            tool_id (str, optional): The ID of the tool to delete.
            tool_name (str, optional): The name of the tool to delete.
            user_id (str, optional): The ID of the user performing the deletion.
            is_admin (bool, optional): Whether the user is an admin.

        Returns:
            dict: Status of the operation.
        """
        if not tool_id and not tool_name:
            log.error("Error: Must provide 'tool_id' or 'tool_name' to delete a tool.")
            return {
                "status_message": "Error: Must provide 'tool_id' or 'tool_name' to delete a tool.",
                "details": [],
                "is_delete": False
            }

        tool_data = await self.tool_repo.get_tool_record(tool_id=tool_id, tool_name=tool_name)
        if not tool_data:
            log.error(f"No Tool available with ID: {tool_id or tool_name}")
            return {
                "status_message": f"No Tool available with ID: {tool_id or tool_name}",
                "details": [],
                "is_delete": False
            }
        tool_data = tool_data[0]

        if not is_admin and tool_data["created_by"] != user_id:
            log.error(f"Permission denied: User {user_id} is not authorized to delete Tool ID: {tool_data['tool_id']}.")
            return {
                "status_message": f"Permission denied: Only the admin or the tool's creator can perform this action for Tool ID: {tool_data['tool_id']}.",
                "details": [],
                "is_delete": False
            }

        agents_using_this_tool_raw = await self.tool_agent_mapping_repo.get_tool_agent_mappings_record(tool_id=tool_data['tool_id'])
        if agents_using_this_tool_raw:
            agent_ids = [m['agentic_application_id'] for m in agents_using_this_tool_raw]
            agent_details = []
            for agent_id in agent_ids:
                agent_record = await self.agent_repo.get_agent_record(agentic_application_id=agent_id)
                agent_record = agent_record[0] if agent_record else None
                if agent_record:
                    agent_details.append({
                        "agentic_application_id": agent_record['agentic_application_id'],
                        "agentic_application_name": agent_record['agentic_application_name'],
                        "agentic_app_created_by": agent_record['created_by']
                    })
            if agent_details:
                log.error(f"The tool you are trying to delete is being referenced by {len(agent_details)} agentic applications.")
                return {
                    "status_message": f"The tool you are trying to delete is being referenced by {len(agent_details)} agentic application(s).",
                    "details": agent_details,
                    "is_delete": False
                }

        # Move to recycle bin
        recycle_success = await self.recycle_tool_repo.insert_recycle_tool_record(tool_data)
        if not recycle_success:
            log.error(f"Failed to move tool {tool_data['tool_id']} to recycle bin.")
            return {
                "status_message": f"Failed to move tool {tool_data['tool_id']} to recycle bin.",
                "details": [],
                "is_delete": False
            }

        # Clean up mappings
        await self.tool_agent_mapping_repo.remove_tool_from_agent_record(tool_id=tool_data['tool_id'])
        await self.tag_service.clear_tags(tool_id=tool_data['tool_id'])

        # Delete from main table
        delete_success = await self.tool_repo.delete_tool_record(tool_data['tool_id'])

        if delete_success:
            log.info(f"Successfully deleted tool with ID: {tool_data['tool_id']}")
            return {
                "status_message": f"Successfully deleted tool with ID: {tool_data['tool_id']}",
                "details": [],
                "is_delete": True
            }
        else:
            log.error(f"Failed to delete tool {tool_data['tool_id']} from main table.")
            return {
                "status_message": f"Failed to delete tool {tool_data['tool_id']} from main table.",
                "details": [],
                "is_delete": False
            }

    # --- Tool Helper Functions ---
    
    async def approve_tool(self, tool_id: str, approved_by: str, comments: Optional[str] = None) -> Dict[str, Any]:
        """
        Approves a tool by calling the repository's approve_tool method.

        Args:
            tool_id (str): The ID of the tool to approve.
            approved_by (str): The email/identifier of the admin approving the tool.
            comments (Optional[str]): Optional comments about the approval.

        Returns:
            dict: Status of the approval operation.
        """
        success = await self.tool_repo.approve_tool(tool_id=tool_id, approved_by=approved_by, comments=comments)
        
        if success:
            log.info(f"Successfully approved tool with ID: {tool_id}")
            return {
                "status_message": f"Successfully approved tool with ID: {tool_id}",
                "tool_id": tool_id,
                "approved_by": approved_by,
                "is_approved": True
            }
        else:
            log.error(f"Failed to approve tool with ID: {tool_id}")
            return {
                "status_message": f"Failed to approve tool with ID: {tool_id}",
                "tool_id": tool_id,
                "approved_by": approved_by,
                "is_approved": False
            }

    async def get_all_tools_for_approval(self) -> List[Dict[str, Any]]:
        """
        Retrieves all tools for admin approval purposes.

        Returns:
            list: A list of tools, represented as dictionaries.
        """
        return await self.tool_repo.get_all_tools_for_approval()

    async def get_tools_for_approval_by_search_or_page(self, search_value: str = '', limit: int = 20, page: int = 1) -> Dict[str, Any]:
        """
        Retrieves tools with pagination and search filtering for admin approval purposes.

        Args:
            search_value (str, optional): Tool name to filter by.
            limit (int, optional): Number of results per page.
            page (int, optional): Page number for pagination.

        Returns:
            dict: A dictionary containing the total count of tools and the paginated tool details.
        """
        total_count = await self.tool_repo.get_total_tool_count(search_value)
        tool_records = await self.tool_repo.get_tools_by_search_or_page_records_for_approval(search_value, limit, page)
        
        return {
            "total_count": total_count,
            "details": tool_records
        }
    
    async def validate_tools(self, tools_id: Union[List[str], str]) -> Dict[str, Any]:
        """
        Validates whether the given tool IDs exist in the database.

        Args:
            tools_id (Union[List[str], str]): A list of tool IDs to validate.

        Returns:
            dict: Validation result message indicating success or failure.
        """
        if not tools_id:
            return {"info": "No Tool ID to check"}

        if isinstance(tools_id, str):
            tools_id = [tools_id]

        for tool_id_single in tools_id:
            if tool_id_single.startswith("mcp_"):
                tool = await self.mcp_tool_service.mcp_tool_repo.get_mcp_tool_record(tool_id=tool_id_single)
            else:
                tool = await self.tool_repo.get_tool_record(tool_id=tool_id_single)
            tool = tool[0] if tool else None
            if not tool:
                return {"error": f"Tool with ID {tool_id_single} not found."}
        log.info("Tool Check Complete. All tools are available.")
        return {"info": "Tool Check Complete. All tools are available."}

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
        This method is used internally to build the tool prompt.

        Args:
            tools_id (Union[List[str], str]): List of tool IDs to retrieve details for.

        Returns:
            dict: A dictionary containing tool information indexed by tool names.
        """
        if isinstance(tools_id, str):
            tools_id = [tools_id]

        tools_info_user = {}
        for idx, tool_id_single in enumerate(tools_id):
            if tool_id_single.startswith("mcp_"):
                # For MCP tools, we need to get live tool details to render prompt
                try:
                    mcp_server_def = await self.mcp_tool_service.get_live_mcp_tools_from_server(tool_id_single)
                    live_mcp_tools: List[StructuredTool] = mcp_server_def.get("live_tools", [])
                    if live_mcp_tools:
                        # For prompt generation, we want to describe the *server* as a tool and list its capabilities.

                        server_name = mcp_server_def.get("tool_name", "MCP Server")
                        server_description = mcp_server_def.get("tool_description", "A Micro-Agentic Protocol server.")

                        # Summarize the tools it exposes for the prompt
                        exposed_tools_summary = ", ".join([f"{t.name} ({t.description[:50]}...)" for t in live_mcp_tools])
                        
                        tools_info_user[f"Tool_{idx+1}"] = {
                            "Tool_Name": server_name,
                            "Tool_Description": server_description,
                            "code_snippet": f"This MCP server is exposes the following capabilities: {exposed_tools_summary}"
                                            f"To use its tools, call the appropriate function from this server."
                        }
                    else:
                        tools_info_user[f"Tool_{idx+1}"] = {"error": f"MCP server '{tool_id_single}' is not live or has no tools."}
                except Exception as e:
                    tools_info_user[f"Tool_{idx+1}"] = {"error": f"Error connecting to MCP server '{tool_id_single}': {e}"}

            else:
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

    # removes foreign key constraint on tool_agent_mapping_table.tool_id so that it can store worker agent id
    async def fix_tool_agent_mapping_for_meta_agents(self):
        """
        Addresses the foreign key constraint issue on tool_agent_mapping_table.tool_id
        and populates/cleans up mappings for meta-agents.

        This function performs the following steps:
        1. Removes the foreign key constraint on tool_agent_mapping_table.tool_id.
        2. Retrieves all existing meta-agents and planner-meta-agents.
        3. For each meta-agent, validates its associated worker agent IDs:
           - Removes non-existent worker agent IDs from the meta-agent's tools_id list in agent_table.
           - Inserts valid worker agent mappings into the tool_agent_mapping_table.

        Returns:
            Dict[str, Any]: A dictionary indicating the status of the migration/fix.
        """
        log.info("Starting fix for tool_agent_mapping_table foreign key and meta-agent mappings...")

        # --- Step 1: Remove Foreign Key Constraint on tool_agent_mapping_table.tool_id ---
        try:
            is_dropped = await self.tool_agent_mapping_repo.drop_tool_id_fk_constraint()
            if is_dropped:
                log.info("Successfully dropped foreign key constraint on tool_agent_mapping_table.tool_id.")
            else:
                msg = "Foreign key constraint on tool_agent_mapping_table.tool_id was not found (already dropped)."
                log.info(msg)
                return {"status": "success", "message": msg}
        except Exception as e:
            log.error(f"Error attempting to drop foreign key constraint on tool_agent_mapping_table.tool_id: {e}")
            return {"status": "error", "message": f"Failed to drop FK constraint: {e}"}

        # --- Step 2: Retrieve all Meta-Agents and Planner-Meta-Agents ---
        log.info("Retrieving all meta-agents and planner-meta-agents for mapping cleanup...")
        meta_agents_to_process = []
        try:
            # Use agent_repo to get meta-agents
            meta_agents_to_process = await self.agent_repo.get_all_agent_records(
                agentic_application_type=['meta_agent', 'planner_meta_agent']
            )
            log.info(f"Found {len(meta_agents_to_process)} meta-agents to process.")
        except Exception as e:
            log.error(f"Error retrieving meta-agents for mapping fix: {e}")
            return {"status": "error", "message": f"Failed to retrieve meta-agents for fix: {e}"}

        # --- Step 3: Process Each Meta-Agent's Worker IDs and Populate Mappings ---
        for meta_agent_data in meta_agents_to_process:
            meta_agent_id = meta_agent_data['agentic_application_id']
            meta_agent_created_by = meta_agent_data['created_by']
            worker_agent_ids_raw = meta_agent_data['tools_id'] # This column stores worker agent IDs for meta-agents

            log.info(f"Processing meta-agent: {meta_agent_id}")

            try:
                # tools_id is JSONB, so it should already be a Python list/object.
                # Add a check for string type just in case old data is not JSONB.
                current_worker_agent_ids = json.loads(worker_agent_ids_raw) if isinstance(worker_agent_ids_raw, str) else worker_agent_ids_raw
            except json.JSONDecodeError:
                log.warning(f"Skipping meta-agent {meta_agent_id}: 'tools_id' (worker_agent_ids) is not valid JSON. Raw: {worker_agent_ids_raw}")
                continue # Skip to the next meta-agent

            valid_worker_agent_ids = []
            needs_update_in_agent_table = False

            for worker_id in current_worker_agent_ids:
                worker_agent_info = None
                try:
                    # Directly query the agent_repo for worker agent details
                    worker_agent_info = await self.agent_repo.get_agent_record(agentic_application_id=worker_id)
                    worker_agent_info = worker_agent_info[0] if worker_agent_info else None
                except Exception as e:
                    log.error(f"Error querying worker agent {worker_id} for meta-agent {meta_agent_id} during fix: {e}")
                    # Continue processing, but this worker_id will be treated as non-existent
                    worker_agent_info = None

                if worker_agent_info:
                    # Worker agent exists, add to valid list
                    valid_worker_agent_ids.append(worker_id)
                    worker_created_by = worker_agent_info['created_by']

                    # Insert mapping into tool_agent_mapping_table (using ToolAgentMappingRepository)
                    await self.tool_agent_mapping_repo.assign_tool_to_agent_record(
                        tool_id=worker_id, # This is the worker agent's ID
                        agentic_application_id=meta_agent_id, # This is the meta-agent's ID
                        tool_created_by=worker_created_by, # Creator of the worker agent
                        agentic_app_created_by=meta_agent_created_by # Creator of the meta-agent
                    )
                    log.info(f"Mapped worker agent {worker_id} to meta-agent {meta_agent_id}.")
                else:
                    # Worker agent does not exist, mark for update
                    log.warning(f"Worker agent {worker_id} for meta-agent {meta_agent_id} not found in agent_table. Removing from meta-agent's tools_id.")
                    needs_update_in_agent_table = True

            # If any worker agents were removed, update the meta-agent's tools_id list in agent_table
            if needs_update_in_agent_table:
                log.info(f"Updating tools_id for meta-agent {meta_agent_id} in agent_table to remove non-existent worker agents.")
                
                # Prepare update data for agent_repo
                agent_update_data = {
                    "tools_id": json.dumps(valid_worker_agent_ids), # tools_id must be JSON dumped for DB
                    "updated_on": datetime.now(timezone.utc).replace(tzinfo=None)
                }
                
                # Use agent_repo to update the agent record directly
                success = await self.agent_repo.update_agent_record(
                    agent_data=agent_update_data,
                    agentic_application_id=meta_agent_id
                )
                if success:
                    log.info(f"Successfully updated tools_id for meta-agent {meta_agent_id}.")
                else:
                    log.error(f"Failed to update tools_id for meta-agent {meta_agent_id} (no rows updated).")

        log.info("Finished fixing tool_agent_mapping_table and meta-agent mappings.")
        return {"status": "success", "message": "Database mapping fix and cleanup completed."}

    # --- Recycle Bin Operations ---

    async def get_all_tools_from_recycle_bin(self) -> List[Dict[str, Any]]:
        """
        Retrieves all tools from the recycle bin.

        Returns:
            list: A list of dictionaries representing the tools in the recycle bin.
        """
        return await self.recycle_tool_repo.get_all_recycle_tool_records()

    async def restore_tool(self, tool_id: Optional[str] = None, tool_name: Optional[str] = None) -> Dict[str, Any]:
        """
        Restores a tool from the recycle bin to the main tool table.

        Args:
            tool_id (str, optional): The ID of the tool to restore.
            tool_name (str, optional): The name of the tool to restore.

        Returns:
            dict: Status of the operation.
        """
        if not tool_id and not tool_name:
            log.warning("No tool ID or name provided for restoration.")
            return {
                "status_message": "Error: Must provide 'tool_id' or 'tool_name' to restore a tool.",
                "details": [],
                "is_restored": False
            }

        tool_data = await self.recycle_tool_repo.get_recycle_tool_record(tool_id=tool_id, tool_name=tool_name)
        if not tool_data:
            log.warning(f"No Tool available in recycle bin with ID: {tool_id or tool_name}")
            return {
                "status_message": f"No Tool available in recycle bin with ID: {tool_id or tool_name}",
                "details": [],
                "is_restored": False
            }

        # Attempt to save to main table
        success = await self.tool_repo.save_tool_record(tool_data)
        general_tag = await self.tag_service.get_tag(tag_name="General")
        tags_status = await self.tag_service.assign_tags_to_tool(
            tag_ids=general_tag["tag_id"],
            tool_id=tool_data['tool_id']
        )
        if not success:
            log.error(f"Failed to restore tool {tool_data['tool_name']} to main table (might already exist).")
            return {
                "status_message": f"Failed to restore tool {tool_data['tool_name']} to main table (might already exist).",
                "details": [],
                "is_restored": False
            }

        # Delete from recycle bin
        delete_success = await self.recycle_tool_repo.delete_recycle_tool_record(tool_data['tool_id'])
        if delete_success:
            log.info(f"Successfully deleted tool {tool_data['tool_id']} from recycle bin.")
            return {
                "status_message": f"Successfully restored tool with ID: {tool_data['tool_id']}",
                "details": [],
                "is_restored": True
            }
        else:
            log.error(f"Failed to delete tool {tool_data['tool_id']} from recycle bin after restoration.")
            return {
                "status_message": f"Tool {tool_data['tool_id']} restored to main table, but failed to delete from recycle bin.",
                "details": [],
                "is_restored": False
            }

    async def delete_tool_from_recycle_bin(self, tool_id: Optional[str] = None, tool_name: Optional[str] = None) -> Dict[str, Any]:
        """
        Deletes a tool permanently from the recycle bin.

        Args:
            tool_id (str, optional): The ID of the tool to delete.
            tool_name (str, optional): The name of the tool to delete.

        Returns:
            dict: Status of the operation.
        """
        if not tool_id and not tool_name:
            log.warning("No tool ID or name provided for permanent deletion.")
            return {
                "status_message": "Error: Must provide 'tool_id' or 'tool_name' to permanently delete a tool.",
                "details": [],
                "is_delete": False
            }

        tool_data = await self.recycle_tool_repo.get_recycle_tool_record(tool_id=tool_id, tool_name=tool_name)
        if not tool_data:
            log.warning(f"No Tool available in recycle bin with ID: {tool_id or tool_name}")
            return {
                "status_message": f"No Tool available in recycle bin with ID: {tool_id or tool_name}",
                "details": [],
                "is_delete": False
            }

        success = await self.recycle_tool_repo.delete_recycle_tool_record(tool_data['tool_id'])
        if success:
            log.info(f"Successfully deleted tool from recycle bin with ID: {tool_data['tool_id']}")
            return {
                "status_message": f"Successfully deleted tool from recycle bin with ID: {tool_data['tool_id']}",
                "details": [],
                "is_delete": True
            }
        else:
            log.error(f"Failed to delete tool {tool_data['tool_id']} from recycle bin.")
            return {
                "status_message": f"Failed to delete tool {tool_data['tool_id']} from recycle bin.",
                "details": [],
                "is_delete": False
            }


# --- Agent Service ---

class AgentServiceUtils:

    def __init__(
        self,
        agent_repo: AgentRepository,
        recycle_agent_repo: RecycleAgentRepository,
        tool_service: ToolService,
        tag_service: TagService,
        model_service: ModelService,
        meta_type_templates: Optional[List[str]] = None
    ):
        self.agent_repo = agent_repo
        self.recycle_agent_repo = recycle_agent_repo
        self.tool_service = tool_service
        self.tag_service = tag_service
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
        self.recycle_agent_repo = agent_service_utils.recycle_agent_repo
        self.tool_service = agent_service_utils.tool_service
        self.mcp_tool_service = self.tool_service.mcp_tool_service
        self.tag_service = agent_service_utils.tag_service
        self.model_service = agent_service_utils.model_service
        self.meta_type_templates = agent_service_utils.meta_type_templates


    # --- Agent Creation Operations ---

    async def _save_agent_data(self, agent_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Saves agent data to the database, including associated tool/worker agent mappings and tags.
        This is a private helper method used by public onboarding methods.

        Args:
            agent_data (dict): A dictionary containing the agent data to insert.

        Returns:
            dict: Status of the operation.
        """
        agent_data['system_prompt'] = json.dumps(agent_data['system_prompt'])
        agent_data['tools_id'] = json.dumps(agent_data.get('tools_id', []))

        now = datetime.now(timezone.utc).replace(tzinfo=None)
        agent_data["created_on"] = now
        agent_data["updated_on"] = now

        if not agent_data.get("agentic_application_id"):
            agent_data["agentic_application_id"] = str(uuid.uuid4())
        update_session_context(agent_id=agent_data["agentic_application_id"])

        success = await self.agent_repo.save_agent_record(agent_data)

        if success:
            is_meta_agent = agent_data["agentic_application_type"] in self.meta_type_templates
            associated_ids = json.loads(agent_data["tools_id"])

            for associated_id in associated_ids:
                associated_created_by = None
                if is_meta_agent:
                    worker_agent_info = await self.get_agent(agentic_application_id=associated_id)
                    associated_created_by = worker_agent_info[0]["created_by"] if worker_agent_info else None
                else:
                    tool_info = await self.tool_service.get_tool(tool_id=associated_id)
                    associated_created_by = tool_info[0]["created_by"] if tool_info else None

                if associated_created_by is not None:
                    await self.tool_service.tool_agent_mapping_repo.assign_tool_to_agent_record(
                        tool_id=associated_id,
                        agentic_application_id=agent_data["agentic_application_id"],
                        tool_created_by=associated_created_by,
                        agentic_app_created_by=agent_data["created_by"]
                    )

            tags_status = await self.tag_service.assign_tags_to_agent(
                tag_ids=agent_data.get("tag_ids", []),
                agentic_application_id=agent_data["agentic_application_id"]
            )

            log.info(f"Successfully onboarded Agentic Application with ID: {agent_data['agentic_application_id']}")
            return {
                "message": f"Successfully onboarded Agentic Application with ID: {agent_data['agentic_application_id']}",
                "agentic_application_id": agent_data["agentic_application_id"],
                "agentic_application_name": agent_data["agentic_application_name"],
                "agentic_application_type": agent_data["agentic_application_type"],
                "model_name": agent_data.get("model_name", ""),
                "tags_status": tags_status,
                "created_by": agent_data["created_by"],
                "is_created": True
            }
        else:
            log.error(f"Integrity error inserting data: Agent name {agent_data.get('agentic_application_name', '')} already exists.")
            return {
                "message": f"Integrity error inserting data: Agent name {agent_data.get('agentic_application_name', '')} already exists.",
                "agentic_application_id": "",
                "agentic_application_name": agent_data.get("agentic_application_name", ""),
                "agentic_application_type": agent_data.get("agentic_application_type", ""),
                "model_name": agent_data.get("model_name", ""),
                "created_by": agent_data.get("created_by", ""),
                "is_created": False
            }

    async def _onboard_agent(self,
                             agent_name: str,
                             agent_goal: str,
                             workflow_description: str,
                             agent_type: str,
                             model_name: str,
                             associated_ids: List[str],
                             user_id: str,
                             tag_ids: Optional[Union[str, List[str]]] = None) -> Dict[str, Any]:
        """
        Onboards a new Agent.

        Args:
            agent_name (str): The name of the agent.
            agent_goal (str): The goal or purpose of the agent.
            workflow_description (str): A description of the workflow the agent will follow.
            agent_type (str): The type of agent.
            model_name (str): The name of the model to be used by the agent.
            associated_ids (List[str]): A list of Tool IDs or Agent IDs that the agent will use.
            user_id (str): The user ID associated with the agent.
            tag_ids (Union[List[str], str], optional): A list of tag IDs for the agent.

        Returns:
            dict: Status of the onboarding operation.
        """
        if await self.is_agent_in_recycle_bin(agentic_application_name=agent_name):
            err = f"Agentic Application with name {agent_name} already exists in recycle bin."
            log.error(err)
            return {
                "message": err,
                "agentic_application_id": "",
                "agentic_application_name": agent_name,
                "agentic_application_type": "",
                "model_name": "",
                "created_by": "",
                "is_created": False
            }
        agent_check = await self.get_agent(agentic_application_name=agent_name)
        if agent_check:
            log.error(f"Agentic Application with name {agent_name} already exists.")
            status = {
                "message": "Agentic Application with the same name already exists.",
                "agentic_application_id": agent_check[0]["agentic_application_id"],
                "agentic_application_name": agent_check[0]["agentic_application_name"],
                "agentic_application_type": agent_check[0]["agentic_application_type"],
                "model_name": agent_check[0]["model_name"],
                "created_by": agent_check[0]["created_by"],
                "is_created": False
            }
            return status

        associated_ids = list(set(associated_ids))
        system_prompt = await self._get_system_prompt_for_agent(
            agent_name=agent_name,
            agent_goal=agent_goal,
            workflow_description=workflow_description,
            agent_type=agent_type,
            associated_ids=associated_ids,
            model_name=model_name
        )

        if "error" in system_prompt:
            log.error(f"Error generating system prompt: {system_prompt['error']}")
            return {
                "message": system_prompt["error"],
                "agentic_application_id": "",
                "agentic_application_name": agent_name,
                "agentic_application_type": agent_type,
                "model_name": model_name,
                "created_by": user_id,
                "is_created": False
            }

        if not tag_ids:
            general_tag = await self.tag_service.get_tag(tag_name="General")
            tag_ids = [general_tag['tag_id']] if general_tag else []
        update_session_context(tags=tag_ids)

        agent_data = {
            "agentic_application_name": agent_name,
            "agentic_application_description": agent_goal,
            "agentic_application_workflow_description": workflow_description,
            "agentic_application_type": agent_type,
            "model_name": model_name,
            "system_prompt": system_prompt,
            "tools_id": associated_ids,
            "created_by": user_id,
            "tag_ids": tag_ids
        }
        agent_creation_status = await self._save_agent_data(agent_data)
        log.info(f"Agentic Application '{agent_name}' of type {agent_type.replace('_', ' ').title()} created successfully.")
        return agent_creation_status

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
                agent_record['tags'] = await self.tag_service.get_tags_by_agent(agent_record['agentic_application_id'])
                log.info(f"Retrieved agentic application with name: {agentic_application_name}")
        return agent_records

    async def get_all_agents(self, agentic_application_type: Optional[Union[str, List[str]]] = None) -> List[Dict[str, Any]]:
        """
        Retrieves all agents, optionally filtered by type, with associated tags.

        Args:
            agentic_application_type (Union[List[str], str], optional): The type(s) of agentic application to filter by.

        Returns:
            list: A list of agents, represented as dictionaries.
        """
        agent_records = await self.agent_repo.get_all_agent_records(agentic_application_type=agentic_application_type)
        agent_id_to_tags = await self.tag_service.get_agent_id_to_tags_dict()

        for agent in agent_records:
            agent['system_prompt'] = json.loads(agent['system_prompt']) if isinstance(agent['system_prompt'], str) else agent['system_prompt']
            agent['tools_id'] = json.loads(agent['tools_id']) if isinstance(agent['tools_id'], str) else agent['tools_id']
            agent['tags'] = agent_id_to_tags.get(agent['agentic_application_id'], [])
        log.info(f"Retrieved {len(agent_records)} agentic applications.")
        return agent_records

    async def get_agents_by_search_or_page(self,
                                           search_value: str = '',
                                           limit: int = 20,
                                           page: int = 1,
                                           agentic_application_type: Optional[Union[str, List[str]]] = None,
                                           created_by: Optional[str] = None,
                                           tag_names: Optional[List[str]] = None ) -> Dict[str, Any]:
        """
        Retrieves agents with pagination and search filtering, including associated tags.

        Args:
            search_value (str, optional): Agent name to filter by.
            limit (int, optional): Number of results per page.
            page (int, optional): Page number for pagination.
            agentic_application_type (Union[List[str], str], optional): The type(s) of agentic application to filter by.
            created_by (str, optional): The email ID of the user who created the agent.

        Returns:
            dict: A dictionary containing the total count of agents and the paginated agent details.
        """
        total_count = await self.agent_repo.get_total_agent_count(search_value, agentic_application_type, created_by)

        if tag_names:
            tag_names = set(tag_names)
            agent_records = await self.agent_repo.get_agents_by_search_or_page_records(search_value, total_count, 1, agentic_application_type, created_by)
        else:
            agent_records = await self.agent_repo.get_agents_by_search_or_page_records(search_value, limit, page, agentic_application_type, created_by)

        agent_id_to_tags = await self.tag_service.get_agent_id_to_tags_dict()
        filtered_agents = []

        for agent in agent_records:
            agent['system_prompt'] = json.loads(agent['system_prompt']) if isinstance(agent['system_prompt'], str) else agent['system_prompt']
            agent['tools_id'] = json.loads(agent['tools_id']) if isinstance(agent['tools_id'], str) else agent['tools_id']
            agent['tags'] = agent_id_to_tags.get(agent['agentic_application_id'], [])
            if tag_names:
                for tag in agent['tags']:
                    if tag['tag_name'] in tag_names:
                        filtered_agents.append(agent)
                        break

        if tag_names:
            total_count = len(filtered_agents)
            offset = limit * max(0, page - 1)
            filtered_agents = filtered_agents[offset: offset + limit]
        else:
            filtered_agents = agent_records

        log.info(f"Retrieved {len(agent_records)} agentic applications with search '{search_value}' on page {page}.")
        return {
            "total_count": total_count,
            "details": filtered_agents
        }

    async def get_agents_by_tag(self,
                                tag_ids: Optional[Union[List[str], str]] = None,
                                tag_names: Optional[Union[List[str], str]] = None) -> List[Dict[str, Any]]:
        """
        Retrieves agents associated with given tag IDs or tag names.

        Args:
            tag_ids (Union[List[str], str], optional): A list of tag IDs or a single tag ID.
            tag_names (Union[List[str], str], optional): A list of tag names or a single tag name.

        Returns:
            list: A list of agents associated with the tags, represented as dictionaries.
        """
        if tag_names:
            resolved_tag_ids = []
            for name in (tag_names if isinstance(tag_names, list) else [tag_names]):
                tag_record = await self.tag_service.get_tag(tag_name=name)
                if tag_record:
                    resolved_tag_ids.append(tag_record['tag_id'])
            if tag_ids:
                tag_ids.extend(resolved_tag_ids)
            else:
                tag_ids = resolved_tag_ids

        if not tag_ids:
            log.error("No tag IDs or names provided to filter agents.")
            return []

        # Get raw agent records that have these tags
        all_agent_records = await self.agent_repo.get_all_agent_records()
        filtered_agents = []
        for agent in all_agent_records:
            agent_tag_ids = await self.tag_service.get_tags_by_agent(agent['agentic_application_id'])
            if any(t['tag_id'] in tag_ids for t in agent_tag_ids):
                filtered_agents.append(agent)

        # Attach full tag details
        agent_id_to_tags = await self.tag_service.get_agent_id_to_tags_dict()
        for agent in filtered_agents:
            agent['system_prompt'] = json.loads(agent['system_prompt']) if isinstance(agent['system_prompt'], str) else agent['system_prompt']
            agent['tools_id'] = json.loads(agent['tools_id']) if isinstance(agent['tools_id'], str) else agent['tools_id']
            agent['tags'] = agent_id_to_tags.get(agent['agentic_application_id'], [])
        log.info(f"Filtered {len(filtered_agents)} agents by tags: {tag_ids or tag_names}.")
        return filtered_agents

    async def get_agent_details_studio(self, agentic_application_id: str) -> Dict[str, Any]:
        """
        Retrieves agent details along with associated tool/worker agent information for studio display.

        Args:
            agentic_application_id (str): The agentic application ID.

        Returns:
            dict: A dictionary with agent details and associated items information.
        """
        agent_record = await self.agent_repo.get_agent_record(agentic_application_id=agentic_application_id)
        agent_record = agent_record[0] if agent_record else None
        if not agent_record:
            log.warning(f"No agentic application found with ID: {agentic_application_id}")
            return {}

        agent_details = agent_record
        agent_details['system_prompt'] = json.loads(agent_details['system_prompt']) if isinstance(agent_details['system_prompt'], str) else agent_details['system_details']
        agent_details['tools_id'] = json.loads(agent_details['tools_id']) if isinstance(agent_details['tools_id'], str) else agent_details['tools_id']

        associated_ids = agent_details.get("tools_id", [])
        associated_info_list = []

        if agent_details['agentic_application_type'] in self.meta_type_templates:
            for worker_agent_id in associated_ids:
                worker_agent_info = await self.get_agent(agentic_application_id=worker_agent_id)
                if worker_agent_info:
                    associated_info_list.append(worker_agent_info[0])
        else:
            for tool_id in associated_ids:
                tool_info = await self.tool_service.get_tool(tool_id=tool_id)
                if tool_info:
                    associated_info_list.append(tool_info[0])

        agent_details["tools_id"] = associated_info_list
        log.info(f"Retrieved agentic application details for ID: {agentic_application_id}")
        return agent_details

    async def get_agents_details_for_chat(self) -> List[Dict[str, Any]]:
        """
        Fetches basic agent details (ID, name, type) for chat purposes.

        Returns:
            list[dict]: A list of dictionaries, where each dictionary contains
                        'agentic_application_id', 'agentic_application_name',
                        and 'agentic_application_type'.
        """
        return await self.agent_repo.get_agents_details_for_chat_records()

    # --- Agent Updation Operations ---

    async def _update_agent_data_util(self, agent_data: Dict[str, Any], agentic_application_id: str) -> bool:
        """
        Updates an agent record in the database and manages associated tool/worker agent mappings.
        This is a private helper method.

        Args:
            agent_data (dict): A dictionary containing the agent data to update.
            agentic_application_id (str): The ID of the agentic application to update.

        Returns:
            bool: True if the update was successful, False otherwise.
        """
        agent_data["updated_on"] = datetime.now(timezone.utc).replace(tzinfo=None)
        tags = agent_data.pop("tags", None)

        success = await self.agent_repo.update_agent_record(agent_data, agentic_application_id)

        if success:
            # Clean up and re-insert associated tool/agent mappings
            await self.tool_service.tool_agent_mapping_repo.remove_tool_from_agent_record(agentic_application_id=agent_data['agentic_application_id'])
            
            associated_ids = json.loads(agent_data['tools_id'])
            for associated_id in associated_ids:
                associated_created_by = None
                if agent_data['agentic_application_type'] in self.meta_type_templates:
                    worker_agent_info = await self.get_agent(agentic_application_id=associated_id)
                    associated_created_by = worker_agent_info[0]["created_by"] if worker_agent_info else None
                else:
                    tool_info = await self.tool_service.get_tool(tool_id=associated_id)
                    associated_created_by = tool_info[0]["created_by"] if tool_info else None

                if associated_created_by is not None:
                    await self.tool_service.tool_agent_mapping_repo.assign_tool_to_agent_record(
                        tool_id=associated_id,
                        agentic_application_id=agent_data["agentic_application_id"],
                        tool_created_by=associated_created_by,
                        agentic_app_created_by=agent_data["created_by"]
                    )
            return True
        return False

    async def _update_agent(self,
                            agentic_application_id: Optional[str] = None,
                            agentic_application_name: Optional[str] = None,
                            agentic_application_description: str = "",
                            agentic_application_workflow_description: str = "",
                            model_name: Optional[str] = None,
                            created_by: Optional[str] = None,
                            system_prompt: Dict[str, Any] = {},
                            is_admin: bool = False,
                            associated_ids: List[str] = [],
                            associated_ids_to_add: List[str] = [],
                            associated_ids_to_remove: List[str] = [],
                            updated_tag_id_list: Optional[Union[str, List[str]]] = None) -> Dict[str, Any]:
        """
        Updates a agent in the database.

        Args:
            agentic_application_id (str, optional): The ID of the agent to update.
            agentic_application_name (str, optional): The name of the agent to update.
            agentic_application_description (str, optional): New description for the agent.
            agentic_application_workflow_description (str, optional): New workflow description.
            model_name (str, optional): New model name for the agent.
            created_by (str, optional): User performing the update.
            system_prompt (dict, optional): New system prompt parts.
            is_admin (bool, optional): Whether the user is an admin.
            associated_ids (list, optional): New complete list of tool IDs.
            associated_ids_to_add (list, optional): Tool IDs to add.
            associated_ids_to_remove (list, optional): Tool IDs to remove.
            updated_tag_id_list (Union[List, str], optional): New list of tag IDs.

        Returns:
            dict: Status of the update operation.
        """
        agent_records = await self.get_agent(agentic_application_id=agentic_application_id, agentic_application_name=agentic_application_name)
        if not agent_records:
            log.error(f"No Agentic Application found with ID: {agentic_application_id or agentic_application_name}")
            return {"status_message": "Please validate the AGENTIC APPLICATION ID.", "is_update": False}
        agent = agent_records[0]
        agentic_application_id = agent["agentic_application_id"]

        if not agentic_application_description and not agentic_application_workflow_description and not system_prompt and not associated_ids and not associated_ids_to_add and not associated_ids_to_remove and updated_tag_id_list is None:
            log.error("No fields provided to update the agentic application.")
            return {"status_message": "Error: Please specify at least one field to modify.", "is_update": False}

        if not is_admin and agent["created_by"] != created_by:
            log.error(f"Permission denied: User {created_by} is not authorized to update Agentic Application ID: {agent['agentic_application_id']}.")
            return {"status_message": f"You do not have permission to update Agentic Application with ID: {agent['agentic_application_id']}.", "is_update": False}

        tag_status = None
        if updated_tag_id_list is not None:
            await self.tag_service.clear_tags(agent_id=agentic_application_id)
            tag_status = await self.tag_service.assign_tags_to_agent(tag_ids=updated_tag_id_list, agentic_application_id=agentic_application_id)

        if not agentic_application_description and not agentic_application_workflow_description and not system_prompt and not associated_ids and not associated_ids_to_add and not associated_ids_to_remove:
            log.info("Tags updated successfully. No other fields modified.")
            return {"status_message": "Tags updated successfully", "tag_update_status": tag_status, "is_update": True}

        associated_ids_to_check = associated_ids + associated_ids_to_add + associated_ids_to_remove
        is_meta_template = agent['agentic_application_type'] in self.meta_type_templates
        if is_meta_template:
            valid_associated_ids_resp= await self.validate_agent_ids(agents_id=associated_ids_to_check)
        else:
            valid_associated_ids_resp = await self.tool_service.validate_tools(tools_id=associated_ids_to_check)

        if "error" in valid_associated_ids_resp:
            log.error(f"{'Worker agent' if is_meta_template else 'Tool'} validation failed: {valid_associated_ids_resp['error']}")
            return {"status_message": valid_associated_ids_resp["error"], "is_update": False}

        if agentic_application_description:
            agent["agentic_application_description"] = agentic_application_description
        if agentic_application_workflow_description:
            agent["agentic_application_workflow_description"] = agentic_application_workflow_description
        if system_prompt:
            agent["system_prompt"] = {**agent.get("system_prompt", {}), **system_prompt}

        current_associated_ids_set = set(agent.get("tools_id", []))
        if associated_ids:
            current_associated_ids_set = set(associated_ids)
        if associated_ids_to_add:
            current_associated_ids_set.update(associated_ids_to_add)
        if associated_ids_to_remove:
            current_associated_ids_set.difference_update(associated_ids_to_remove)
        agent["tools_id"] = list(current_associated_ids_set)
        agent["model_name"] = model_name

        if not system_prompt: # Regenerate system prompt if not explicitly provided
            llm = await self.model_service.get_llm_model(model_name=model_name)
            tool_or_worker_agents_prompt = None
            if is_meta_template:
                worker_agents_prompt = await self.generate_worker_agents_prompt(agents_id=agent["tools_id"])
                tool_or_worker_agents_prompt = worker_agents_prompt
            else:
                tool_prompt = await self.tool_service.generate_tool_prompt(agent["tools_id"])
                tool_or_worker_agents_prompt = tool_prompt

            agent['system_prompt'] = await self._generate_system_prompt(
                agent_name=agent["agentic_application_name"],
                agent_goal=agent["agentic_application_description"],
                workflow_description=agent["agentic_application_workflow_description"],
                tool_or_worker_agents_prompt=tool_or_worker_agents_prompt,
                llm=llm
            )

        agent['system_prompt'] = json.dumps(agent['system_prompt'])
        agent['tools_id'] = json.dumps(agent['tools_id'])
        
        success = await self._update_agent_data_util(agent_data=agent, agentic_application_id=agentic_application_id)
        
        if success:
            log.info(f"Successfully updated Agentic Application with ID: {agentic_application_id}.")
            status = {"status_message": f"Successfully updated Agentic Application with ID: {agentic_application_id}.", "is_update": True}
        else:
            log.error(f"Failed to update Agentic Application with ID: {agentic_application_id}.")
            status = {"status_message": "Failed to update the Agentic Application.", "is_update": False}
        
        if tag_status:
            status['tag_update_status'] = tag_status
        return status

    # --- Agent Deletion Operations ---

    async def delete_agent(self,
                           agentic_application_id: Optional[str] = None,
                           agentic_application_name: Optional[str] = None,
                           user_id: Optional[str] = None,
                           is_admin: bool = False) -> Dict[str, Any]:
        """
        Deletes an agent by moving it to the recycle bin and then removing it from the main agent table.
        It checks for user permissions and dependencies before deletion.

        Args:
            agentic_application_id (str, optional): The ID of the agent to delete.
            agentic_application_name (str, optional): The name of the agent to delete.
            user_id (str, optional): The ID of the user performing the deletion.
            is_admin (bool, optional): Whether the user is an admin.

        Returns:
            dict: Status of the operation.
        """
        if not agentic_application_id and not agentic_application_name:
            log.error("No agentic application ID or name provided for deletion.")
            return {"status_message": "Error: Must provide 'agentic_application_id' or 'agentic_application_name' to delete an agentic application.", "is_delete": False}

        # Retrieve agent data from the main table
        agent_data = await self.agent_repo.get_agent_record(agentic_application_id=agentic_application_id, agentic_application_name=agentic_application_name)
        
        if not agent_data:
            log.error(f"No Agentic Application found with ID: {agentic_application_id or agentic_application_name}")
            return {"status_message": f"No Agentic Application available with ID: {agentic_application_id or agentic_application_name}", "is_delete": False}
        agent_data = agent_data[0]

        # Check permissions
        if not is_admin and agent_data["created_by"] != user_id:
            log.error(f"Permission denied: User {user_id} is not authorized to delete Agentic Application ID: {agent_data['agentic_application_id']}.")
            return {
                "status_message": f"You do not have permission to delete Agentic Application with ID: {agent_data['agentic_application_id']}.",
                "details": [],
                "is_delete": False
            }

        # Check if this agent is used as a worker agent by any meta-agent ---
        agent_to_delete_id = agent_data['agentic_application_id']
        
        # Get all meta-agents and planner-meta-agents
        meta_agents = await self.agent_repo.get_all_agent_records(agentic_application_type=self.meta_type_templates)

        dependent_meta_agents_details = []
        for meta_agent in meta_agents:
            # tools_id for meta-agents stores worker agent IDs (JSONB, so already a list/Python object)
            worker_agent_ids = meta_agent.get('tools_id', []) 
            if agent_to_delete_id in worker_agent_ids:
                dependent_meta_agents_details.append({
                    "agentic_application_id": meta_agent['agentic_application_id'],
                    "agentic_application_name": meta_agent['agentic_application_name'],
                    "agentic_app_created_by": meta_agent['created_by']
                })

        if dependent_meta_agents_details:
            log.error(f"Agent deletion failed: Agent {agent_data['agentic_application_name']} is being used as a worker agent by {len(dependent_meta_agents_details)} other meta-agent(s).")
            return {
                "status_message": f"The agent you are trying to delete is being referenced as a worker agent by {len(dependent_meta_agents_details)} other agentic application(s).",
                "details": dependent_meta_agents_details,
                "is_delete": False
            }

        # Move to recycle bin
        recycle_success = await self.recycle_agent_repo.insert_recycle_agent_record(agent_data)
        if not recycle_success:
            log.error(f"Failed to move Agentic Application {agent_data['agentic_application_id']} to recycle bin.")
            return {"status_message": f"Failed to move agent {agent_data['agentic_application_id']} to recycle bin.", "is_delete": False}

        # Clean up mappings
        # This removes mappings where the deleted agent was a TOOL/WORKER_AGENT for others
        await self.tool_service.tool_agent_mapping_repo.remove_tool_from_agent_record(agentic_application_id=agent_data['agentic_application_id'])
        # This removes mappings where the deleted agent had TAGS
        await self.tag_service.clear_tags(agent_id=agent_data['agentic_application_id'])

        # Delete from main table
        delete_success = await self.agent_repo.delete_agent_record(agent_data['agentic_application_id'])

        if delete_success:
            log.info(f"Successfully deleted Agentic Application with ID: {agent_data['agentic_application_id']}.")
            return {"status_message": f"Successfully deleted Agentic Application with ID: {agent_data['agentic_application_id']}.", "is_delete": True}
        else:
            log.error(f"Failed to delete Agentic Application {agent_data['agentic_application_id']} from main table.")
            return {"status_message": f"Failed to delete Agentic Application {agent_data['agentic_application_id']} from main table.", "is_delete": False}

    # --- Agent Helper Functions ---

    async def validate_agent_ids(self, agents_id: Union[List[str], str]) -> Dict[str, Any]:
        """
        Validates whether the given agent IDs exist in the database.

        Args:
            agents_id (Union[List[str], str]): A list of agent IDs to validate.

        Returns:
            dict: Validation result message indicating success or failure.
        """
        if not agents_id:
            log.info("No agents provided for validation.")
            return {"info": "No Agentic Application ID to check"}

        if isinstance(agents_id, str):
            agents_id = [agents_id]

        for agent_id_single in agents_id:
            agent = await self.agent_repo.get_agent_record(agentic_application_id=agent_id_single)
            agent = agent[0] if agent else None
            if not agent:
                log.error(f"Agent with ID {agent_id_single} not found.")
                return {"error": f"The agent with Agentic Application ID: {agent_id_single} is not available. Please validate the provided agent id."}
        log.info("All agents are available for onboarding.")
        return {"info": "Agent Check Complete. All agents are available."}

    async def generate_worker_agents_prompt(self, agents_id: List[str]):
        """
        Generates worker agents prompt for the meta type agent describing the available agents.
        """
        worker_agents_prompt = ""
        success_count = 0
        for agent_id in agents_id:
            agent_info = await self.agent_repo.get_agent_record(agentic_application_id=agent_id)
            if not agent_info:
                log.warning(f"Agent with ID {agent_id} not found.")
                continue

            agent_info = agent_info[0]
            agent_name = await self.agent_service_utils._normalize_agent_name(agent_info["agentic_application_name"])
            worker_agents_prompt += f"Agentic Application Name: {agent_name}\nAgentic Application Description: {agent_info['agentic_application_description']}\n\n"
            success_count += 1

        log.info(f"Generated worker agents prompt for {success_count} agents.")
        return worker_agents_prompt

    async def _get_system_prompt_for_agent(self,
                                           agent_name: str,
                                           agent_goal: str,
                                           workflow_description: str,
                                           agent_type: str,
                                           associated_ids: List[str],
                                           model_name: str):
        """
        Asynchronously generates a system prompt for an agent based on its type, associated IDs, and model.
        Args:
            agent_name (str): The name of the agent.
            agent_goal (str): The goal or objective of the agent.
            workflow_description (str): Description of the workflow the agent is part of.
            agent_type (str): The type of the agent (e.g., meta or tool-based).
            associated_ids (List[str]): List of IDs associated with the agent (either worker agent IDs or tool IDs).
            model_name (str): The name of the language model to use for prompt generation.
        Returns:
            dict or str: The generated system prompt, or a dictionary containing an error message if validation fails.
        Raises:
            None
        Notes:
            - Validates associated IDs based on agent type (worker agents or tools).
            - Loads the specified language model.
            - Generates the appropriate prompt for worker agents or tools.
            - Combines all information to generate the final system prompt.
        """
        is_meta_template = agent_type in self.meta_type_templates
        if is_meta_template:
            valid_associated_ids_resp= await self.validate_agent_ids(agents_id=associated_ids)
        else:
            valid_associated_ids_resp = await self.tool_service.validate_tools(tools_id=associated_ids)

        if "error" in valid_associated_ids_resp:
            log.error(f"{'Worker agent' if is_meta_template else 'Tool'} validation failed: {valid_associated_ids_resp['error']}")
            return {"error": valid_associated_ids_resp["error"]}

        try:
            llm = await self.model_service.get_llm_model(model_name=model_name)
            tool_or_worker_agents_prompt = None
            if is_meta_template:
                worker_agents_prompt = await self.generate_worker_agents_prompt(agents_id=associated_ids)
                tool_or_worker_agents_prompt = worker_agents_prompt
            else:
                tool_prompt = await self.tool_service.generate_tool_prompt(tools_id=associated_ids)
                tool_or_worker_agents_prompt = tool_prompt

            system_prompt = await self._generate_system_prompt(
                agent_name=agent_name,
                agent_goal=agent_goal,
                workflow_description=workflow_description,
                tool_or_worker_agents_prompt=tool_or_worker_agents_prompt,
                llm=llm
            )
            log.info("Successfully generated system prompt.")
            return system_prompt

        except Exception as e:
            log.error(f"Error generating system prompt: {str(e)}")
            return {"error": f"Failed to generate system prompt: {str(e)}"}

    # Method to generate system prompt for agent, which must be implemented in the subclasses of respective agent templates
    async def _generate_system_prompt(self, agent_name: str, agent_goal: str, workflow_description: str, tool_or_worker_agents_prompt: str, llm):
        raise NotImplementedError(f"'_generate_system_prompt' method must be implemented in the subclasses of respective agent templates.")

    # --- Recycle Bin Operations for Agents ---

    async def is_agent_in_recycle_bin(self, agentic_application_id: Optional[str] = None, agentic_application_name: Optional[str] = None) -> bool:
        """
        Checks if an agent exists in the recycle bin.

        Args:
            agentic_application_id (str, optional): The ID of the agent to check.
            agentic_application_name (str, optional): The name of the agent to check.

        Returns:
            bool: True if the agent exists in the recycle bin, False otherwise.
        """
        return await self.recycle_agent_repo.is_agent_in_recycle_bin_record(agentic_application_id=agentic_application_id, agentic_application_name=agentic_application_name)

    async def get_all_agents_from_recycle_bin(self) -> List[Dict[str, Any]]:
        """
        Retrieves all agents from the recycle bin.

        Returns:
            list: A list of dictionaries representing the agents in the recycle bin.
        """
        return await self.recycle_agent_repo.get_all_recycle_agent_records()

    async def restore_agent(self, agentic_application_id: Optional[str] = None, agentic_application_name: Optional[str] = None) -> Dict[str, Any]:
        """
        Restores an agent from the recycle bin to the main agent table.

        Args:
            agentic_application_id (str, optional): The ID of the agent to restore.
            agentic_application_name (str, optional): The name of the agent to restore.

        Returns:
            dict: Status of the operation.
        """
        if not agentic_application_id and not agentic_application_name:
            log.error("Error: Must provide 'agentic_application_id' or 'agentic_application_name' to restore an agent.")
            return {
                "status_message": "Error: Must provide 'agentic_application_id' or 'agentic_application_name' to restore an agent.",
                "is_restored": False
            }

        agent_data = await self.recycle_agent_repo.get_recycle_agent_record(agentic_application_id=agentic_application_id, agentic_application_name=agentic_application_name)
        if not agent_data:
            log.error(f"No Agentic Application found in recycle bin with ID: {agentic_application_id or agentic_application_name}")
            return {
                "status_message": f"No Agentic Application available in recycle bin with ID: {agentic_application_id or agentic_application_name}",
                "is_restored": False
            }

        # Delete from recycle bin first
        delete_success = await self.recycle_agent_repo.delete_recycle_agent_record(agent_data['agentic_application_id'])
        if not delete_success:
            log.error(f"Failed to delete agent {agent_data['agentic_application_id']} from recycle bin.")
            return {
                "status_message": f"Failed to delete agent {agent_data['agentic_application_id']} from recycle bin.",
                "is_restored": False
            }

        # Validate and clean up associated tools/worker agents before restoring
        associated_ids: List[str] = json.loads(agent_data["tools_id"])
        new_associated_ids = []
        new_associated_created_bys = []
        for associated_id in associated_ids:
            associated_created_by = None
            if agent_data['agentic_application_type'] in self.meta_type_templates:
                worker_agent_info = await self.get_agent(agentic_application_id=associated_id)
                associated_created_by = worker_agent_info[0]["created_by"] if worker_agent_info else None
            else:
                tool_info = await self.tool_service.get_tool(tool_id=associated_id)
                associated_created_by = tool_info[0]["created_by"] if tool_info else None

            if associated_created_by is not None:
                new_associated_ids.append(associated_id)
                new_associated_created_bys.append(associated_created_by)
        agent_data["tools_id"] = json.dumps(new_associated_ids) # Update tools_id with only valid ones

        # Insert into main agent table
        insert_success = await self.agent_repo.save_agent_record(agent_data)
        general_tag = await self.tag_service.get_tag(tag_name="General")
        tags_status = await self.tag_service.assign_tags_to_agent(
            tag_ids=general_tag["tag_id"],
            agentic_application_id=agent_data["agentic_application_id"]
        )
        if not insert_success:
            log.error(f"Failed to restore agent {agent_data['agentic_application_id']} to main table (might already exist).")
            return {
                "status_message": f"Failed to restore agent {agent_data['agentic_application_id']} to main table (might already exist).",
                "is_restored": False
            }

        # Re-establish tool-agent mappings for valid associated items
        for associated_id, associated_created_by in zip(new_associated_ids, new_associated_created_bys):
            await self.tool_service.tool_agent_mapping_repo.assign_tool_to_agent_record(
                tool_id=associated_id,
                agentic_application_id=agent_data["agentic_application_id"],
                tool_created_by=associated_created_by,
                agentic_app_created_by=agent_data["created_by"]
            )

        log.info(f"Successfully restored Agentic Application with ID: {agent_data['agentic_application_id']}")

        return {
            "status_message": f"Successfully restored Agentic Application with ID: {agent_data['agentic_application_id']}",
            "is_restored": True
        }

    async def delete_agent_from_recycle_bin(self, agentic_application_id: Optional[str] = None, agentic_application_name: Optional[str] = None) -> Dict[str, Any]:
        """
        Deletes an agent permanently from the recycle bin.

        Args:
            agentic_application_id (str, optional): The ID of the agent to delete.
            agentic_application_name (str, optional): The name of the agent to delete.

        Returns:
            dict: Status of the operation.
        """
        if not agentic_application_id and not agentic_application_name:
            log.error("Error: Must provide 'agentic_application_id' or 'agentic_application_name' to permanently delete an agent from recycle bin.")
            return {
                "status_message": "Error: Must provide 'agentic_application_id' or 'agentic_application_name' to permanently delete an agent from recycle bin.",
                "is_delete": False
            }

        agent_data = await self.recycle_agent_repo.get_recycle_agent_record(agentic_application_id=agentic_application_id, agentic_application_name=agentic_application_name)
        if not agent_data:
            log.error(f"No Agentic Application found in recycle bin with ID: {agentic_application_id or agentic_application_name}")
            return {"status_message": f"No Agentic Application available in recycle bin with ID: {agentic_application_id or agentic_application_name}", "is_delete": False}

        success = await self.recycle_agent_repo.delete_recycle_agent_record(agent_data['agentic_application_id'])
        if success:
            log.info(f"Successfully deleted Agentic Application from recycle bin with ID: {agent_data['agentic_application_id']}")
            return {"status_message": f"Successfully deleted Agentic Application from recycle bin with ID: {agent_data['agentic_application_id']}.", "is_delete": True}
        else:
            log.error(f"Failed to delete agent {agent_data['agentic_application_id']} from recycle bin.")
            return {"status_message": f"Failed to delete agent {agent_data['agentic_application_id']} from recycle bin.", "is_delete": False}

    # --- Agent Approval Operations ---

    async def approve_agent(self, agentic_application_id: str, approved_by: str, comments: Optional[str] = None) -> Dict[str, Any]:
        """
        Approves an agent by calling the repository's approve_agent method.

        Args:
            agentic_application_id (str): The ID of the agent to approve.
            approved_by (str): The email/identifier of the admin approving the agent.
            comments (Optional[str]): Optional comments about the approval.

        Returns:
            dict: Status of the approval operation.
        """
        success = await self.agent_repo.approve_agent(agentic_application_id=agentic_application_id, approved_by=approved_by, comments=comments)
        
        if success:
            log.info(f"Successfully approved agent with ID: {agentic_application_id}")
            return {
                "status_message": f"Successfully approved agent with ID: {agentic_application_id}",
                "agentic_application_id": agentic_application_id,
                "approved_by": approved_by,
                "is_approved": True
            }
        else:
            log.error(f"Failed to approve agent with ID: {agentic_application_id}")
            return {
                "status_message": f"Failed to approve agent with ID: {agentic_application_id}",
                "agentic_application_id": agentic_application_id,
                "approved_by": approved_by,
                "is_approved": False
            }

    async def get_all_agents_for_approval(self) -> List[Dict[str, Any]]:
        """
        Retrieves all agents for admin approval purposes.

        Returns:
            list: A list of agents, represented as dictionaries.
        """
        return await self.agent_repo.get_all_agents_for_approval()

    async def get_agents_for_approval_by_search_or_page(self, search_value: str = '', limit: int = 20, page: int = 1) -> Dict[str, Any]:
        """
        Retrieves agents with pagination and search filtering for admin approval purposes.

        Args:
            search_value (str, optional): Agent name to filter by.
            limit (int, optional): Number of results per page.
            page (int, optional): Page number for pagination.

        Returns:
            dict: A dictionary containing the total count of agents and the paginated agent details.
        """
        total_count = await self.agent_repo.get_total_agent_count(search_value)
        agent_records = await self.agent_repo.get_agents_by_search_or_page_records_for_approval(search_value, limit, page)
        
        return {
            "total_count": total_count,
            "details": agent_records
        }

# --- Chat History Service ---

class ChatService:
    """
    Service layer for managing chat history.
    Applies business rules for naming conventions and orchestrates repository calls.
    """

    def __init__(self, chat_history_repo: ChatHistoryRepository, embedding_model: HuggingFaceEmbeddings, cross_encoder: CrossEncoder):
        """
        Initializes the ChatService.

        Args:
            chat_history_repo (ChatHistoryRepository): The repository for chat history data access.
            embedding_model (HuggingFaceEmbeddings): The embedding model for episodic memory.
            cross_encoder (CrossEncoder): The cross-encoder for episodic memory.
        """
        self.repo = chat_history_repo
        self.embedding_model = embedding_model
        self.cross_encoder = cross_encoder
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
        user_id = thread_id
        return {"configurable": {"thread_id": thread_id, "user_id": user_id}, "recursion_limit": recursion_limit}


    async def _get_summary_chain(self, llm):
        return self.conversation_summary_prompt_template | llm | StrOutputParser()
    

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
        parts_dict = response.get("parts_storage_dict", {})
        try:
            if "parts_storage_dict" in response:
                del response["parts_storage_dict"]
            if "parts_storage" in response:
                del response["parts_storage"]
        except KeyError:
            pass

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
                    "additional_details": agent_steps,
                    "parts": parts_dict.get(agent_steps[0].id, [
                        {
                        "type": "text",
                        "data": {
                            "content": agent_steps[0].content if (agent_steps[0].type == "ai") and ("tool_calls" not in agent_steps[0].additional_kwargs) and ("function_call" not in agent_steps[0].additional_kwargs) else ""
                        },
                        "metadata": {}
                        }
                    ])
                }
                for sub_part in new_conversation["parts"]:
                    if sub_part.get("type") != "text":
                        new_conversation.update({"show_canvas": True})
                        break
                else:
                    new_conversation.update({"show_canvas": False})
                if (agent_steps[0].type == "ai") and (("tool_calls" in agent_steps[0].additional_kwargs) or ("function_call" in agent_steps[0].additional_kwargs)):
                    new_conversation["parts"] = []
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

    async def extract_conversation_details_from_short_term_memory(self, agentic_application_id: str, session_id: str) -> Dict[str, List[Dict]]:
        """
        Extract user_query, final_response, and tool calls from data.
        
        Args:
            agentic_application_id (str): The agent ID
            session_id (str): The session ID
        Returns:
            Dict[str, List[Dict]]:  A dictionary containing conversation details
        """
        try:
            data = await self.get_chat_history_from_short_term_memory(
                    agentic_application_id=agentic_application_id,
                    session_id=session_id
                )
            if "error" in data:
                log.error(f"Error retrieving chat history: {data['error']}")
                return {"conversations": []}
            
            executor_messages = data.get("executor_messages", [])
            if not executor_messages:
                log.warning("No executor messages found in chat history")
                return {"conversations": []}
            
            conversations = []
            
            # Process each conversation object
            for conversation in executor_messages:
                if isinstance(conversation, dict):
                    user_query = conversation.get("user_query", "")
                    final_response = conversation.get("final_response", "")
                    tools_used = conversation.get("tools_used", {})
                    
                    # Extract tool calls from tools_used
                    tool_calls = []
                    for tool_id, tool_info in tools_used.items():
                        if isinstance(tool_info, dict):
                            tool_name = tool_info.get("name", "")
                            tool_args = tool_info.get("args", {})
                            
                            if tool_name:
                                if tool_args:
                                    args_str = ", ".join([str(v) for v in tool_args.values()])
                                    tool_call = f"{tool_name}({args_str})"
                                else:
                                    tool_call = f"{tool_name}()"
                                tool_calls.append(tool_call)
                    
                    if user_query: 
                        conversations.append({
                            "user_query": user_query,
                            "final_response": final_response,
                            "tool_calls": tool_calls
                        })
            limited_conversations = conversations[-4:] if len(conversations) > 4 else conversations
            log.info(f"Extracted {len(conversations)} total conversations from short term memory, returning last {len(limited_conversations)} conversations")
            return {"conversations": limited_conversations}
                
        except Exception as e:
            log.error(f"Error extracting conversation details: {e}")
            return {"conversations": []}
 
    async def update_preferences_and_analyze_conversation(
        self, 
        user_input: str, 
        llm: Any, 
        agentic_application_id: str, 
        session_id: str,
    ) -> Dict[str, Any]:
        """
        Update preferences and analyze conversation for episodic storage in a single LLM call.
        
        Returns:
            Dict containing both preference updates and conversation analysis results
        """
        try:
            from src.inference.inference_utils import EpisodicMemoryManager
            preferences = await self.repo.get_agent_conversation_summary_with_preference(agentic_application_id=agentic_application_id, session_id= session_id)
            print(preferences)
            preferences_string = ""
            if isinstance(preferences, dict):
                preferences_string = preferences.get('preference', '')
            elif isinstance(preferences, str):
                preferences_string = preferences

            # Use empty string for "no preferences available" 
            if not preferences_string or preferences_string.strip() == "no preferences available":
                preferences_string = ""

            conversation_details = await self.extract_conversation_details_from_short_term_memory(
                agentic_application_id=agentic_application_id,
                session_id=session_id
            )
            conversations = conversation_details.get('conversations', [])
            # Format conversations for analysis
            formatted_conversation = ""
            for i, conv in enumerate(conversations):
                user_query = conv.get('user_query', '')
                final_response = conv.get('final_response', '')
                tool_calls = conv.get('tool_calls', [])
                
                formatted_conversation += f"Turn {i+1}:\n"
                formatted_conversation += f"User: {user_query}\n"
                formatted_conversation += f"AI: {final_response}\n"
                if tool_calls:
                    formatted_conversation += f"Tool calls used: {', '.join(tool_calls)}\n"
                formatted_conversation += "\n"
            log.debug(f"Formatted {len(conversations)} conversations for analysis")

            combined_prompt = f"""
            # Multi-Task AI Assistant

            You are an expert AI assistant that performs two tasks simultaneously:
            1. **Preference Analysis and Update**
            2. **Conversation Analysis for Learning Examples**

            ## Task 1: Preference Analysis and Update

            ### Current Preferences:
            {preferences_string if preferences_string else "no preferences available"}

            ### User Input:
            {user_input}

            ### Instructions for Preferences:

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

            ### Examples for Preferences:

            user query: output should in markdown format
                - the user query is related to preference and should be added to the preferences.
                user query: a person is running at 5km per hour how much distance he can cover by 2 hours
                - The user query is related to task and should not be added to the preferences.
                user query: give me the response in meters.
                - This is a perference and should be added to the preferences.

            ## Task 2: Conversation Analysis for Learning Examples

            ### Conversation to Analyze
            {formatted_conversation}

            ### Objective
            Identify all query response pairs where the user gives **explicit or implicit feedback** (positive or negative). Each pair must contain:
            - The **original meaningful user query** (not clarifications like "explain more", "want descriptive", etc.)
            - The **AI response that was actually evaluated** (often the final one if clarifications were requested)
            - The **user's feedback** (explicit or implicit)

            ### Analysis Criteria

            #### Positive Indicators  ("good_example")
            - **Explicit signals:** "helpful", "perfect", "thank you", "ok", "good", "useful", "that worked", "got it"
            - **Engagement:** user builds upon, confirms, or continues naturally after the answer
            - **Resolution:** user indicates the problem is solved or answer is satisfactory

            #### Negative Indicators ("bad_example")
            - **Explicit negative signals:** "wrong", "not correct", "bad", "not helpful", "no"
            - **Rejections/corrections:** user provides alternative answer, asks to retry, or repeats same question
            - **Signs of failure:** user abandons or shifts after showing dissatisfaction

            #### No Feedback
            - If the user just moves on to another question without acknowledging or rejecting the previous response, **ignore that pair** (do not generate an example).

            ### Critical Rules

            1. **Trace feedback to the original query**  
            - Always link user feedback back to the **original substantive query** that generated the evaluated response.

            2. **Do not treat feedback as a query**  
            - Feedback itself is not a query-response pair.  
            - Never store `[feedback → acknowledgment]`.

            3. **Pairing logic**  
            - When feedback is given, locate the **previous substantive query**.  
            - Store as:  
                `[Original Query] → [AI Response] → [User Feedback]`  
            - Do **not** store:  
                `[User Feedback] → [AI Acknowledgment]`

            4. **Clarifications**  
            - If clarifications occur, pair the **original substantive query** with the **final AI response** that the user evaluated (not intermediate responses).
            
            5. **ONLY store examples where there is EXPLICIT user feedback** 
            - (positive or negative words/phrases) about an AI response.
            - Do **not** treat clarifications like *"in steps," "shorter," "in JSON format"* as feedback.

            6. **Format requests are NOT feedback** 
            - "give in json format", "explain in steps", "make it shorter" etc. are clarifications/instructions, not evaluative feedback.
            
            7. **Meta-requests are NOT feedback** 
            - "explain more", "want descriptive", "can you elaborate" are requests for more information, not evaluations.

            8. **Conversation flow to identify:**
            - User asks substantive question → AI responds → User gives evaluative feedback
            - Store the original question and the AI response that user evaluated

            9. **If no evaluative feedback is found** in the entire conversation, return `[]`.

            ### Confidence Scoring Rules
            **IMPORTANT - USE NUMBERS NOT STRINGS**

            #### For `good_example`: Set confidence 0.7-1.0 based on clarity of positive feedback
            - **"helpful", "thank you"** = 0.8-0.9
            - **Clear engagement/building upon response** = 0.7-0.8
            - **Implicit satisfaction** = 0.6-0.7

            #### For `bad_example`: Set confidence 0.6-1.0 based on clarity of negative feedback
            - **Explicit "wrong", "incorrect"** = 0.8-1.0
            - **Implicit dissatisfaction** = 0.6-0.7

            **NEVER set confidence to 0.0** unless completely uncertain

            ### Example

            #### Input Conversation:

            User: What is 6*7?  
            Assistant: The answer is 42.  
            User: want descriptive or give in steps.  
            Assistant: Multiplication means repeated addition... (detailed explanation).  
            User: Helpful.  

            #### Expected Output:

            ```json
            {{
            "preferences": {{
                "preferences": ["all new preferences with comma as separator are added here", "", "...goes on"]
            }},
            "episodic_analysis": [
                {{
                "intent": "good_example" | "bad_example",
                "confidence": "<float between 0 and 1>",
                "reasoning": "<why this is good or bad based on user feedback>",
                "should_store": "true",
                "user_query": "<original meaningful query>",
                "ai_response": "<final response user evaluated>",
                "tool_calls": ["<any tool calls from the original query if applicable>"]
                }}
            ]
            }}
            """
            
            response = await llm.ainvoke(combined_prompt)
            if hasattr(response, 'content'):
                content = response.content
            else:
                content = str(response)
            content = content.strip()
            
            json_start = content.find('{')
            json_end = content.rfind('}') + 1
            
            if json_start == -1 or json_end == 0:
                raise json.JSONDecodeError("No JSON found in response", "", 0)
            
            content = content[json_start:json_end]
            
            try:
                combined_results = json.loads(content)
                log.debug("Successfully parsed JSON response from LLM")
            except json.JSONDecodeError as json_err:
                log.error(f"Failed to parse JSON from LLM response: {json_err}. Content preview: {content[:200]}...")
                return {
                    "preferences_result": "",
                    "episodic_results": [{
                        "intent": "bad_example",
                        "confidence": 0.0,
                        "reasoning": f"Failed to parse LLM response: {str(json_err)}",
                        "should_store": False,
                        "user_query": "",
                        "ai_response": "",
                        "tool_calls": [],
                        "storage_status": "failed"
                    }]
                }
           
            preferences_data = combined_results.get("preferences", {})
            if isinstance(preferences_data, str):
                if preferences_data.strip().lower() == "no preferences available":
                    final_preferences_response = ""
                else:
                    final_preferences_response = preferences_data
            elif isinstance(preferences_data, dict):
                preferences_list = preferences_data.get("preferences", [])
                valid_preferences = [
                    str(pref) for pref in preferences_list 
                    if str(pref).strip() and str(pref).strip().lower() != "no preferences available"
                ]
                final_preferences_response = "\n".join(valid_preferences) if valid_preferences else ""
            else:
                final_preferences_response = ""
            
            # Store preferences
            try:
                await self.repo.insert_preference_for_agent_conversation(
                    agentic_application_id=agentic_application_id, 
                    session_id=session_id, 
                    preference=final_preferences_response
                )
                log.info("Preferences updated successfully")
            except Exception as e:
                log.error(f"Error storing preferences: {e}")
            
            # Process episodic analysis results
            episodic_results = combined_results.get("episodic_analysis", [])
            
            if not isinstance(episodic_results, list):
                episodic_results = [episodic_results] if episodic_results else []
                log.debug("Converted single episodic result to list format")
            
            processed_results = []
            valid_intents = ["good_example", "bad_example"]
            
            if episodic_results and conversations:
                user_id = agentic_application_id

                episodic_memory_manager = EpisodicMemoryManager(
                    user_id=user_id,
                    embedding_model=self.embedding_model,
                    cross_encoder=self.cross_encoder
                )
                
                # Process each result
                for i, result in enumerate(episodic_results):
                    if not isinstance(result, dict):
                        log.warning(f"Skipping non-dict result at index {i}")
                        continue
                
                    if result.get("intent") not in valid_intents:
                        log.warning(f"Invalid intent '{result.get('intent')}' at index {i}, defaulting to 'bad_example'")
                        result["intent"] = "bad_example"
                    
                    confidence = result.get("confidence", 0.0)
                    try:
                        if isinstance(confidence, str):
                            confidence = float(confidence)
                        elif not isinstance(confidence, (int, float)):
                            confidence = 0.0
                        confidence = max(0.0, min(1.0, confidence))
                        
                        if result.get("intent") == "good_example" and confidence == 0.0:
                            confidence = 0.7  
                            
                    except (ValueError, TypeError):
                        log.warning(f"Invalid confidence value at index {i}, using default")
                        confidence = 0.7 if result.get("intent") == "good_example" else 0.0
                    
                    result["confidence"] = confidence
                    
                    should_store = result.get("should_store", False)
                    if isinstance(should_store, str):
                        should_store = should_store.lower() in ("true", "1", "yes")
                    elif not isinstance(should_store, bool):
                        should_store = True if result.get("intent") == "good_example" else False
                    
                    if result["intent"] == "good_example" and confidence < 0.3:
                        should_store = False
                        log.debug(f"Disabling storage for good example at index {i} due to low confidence: {confidence}")
                    elif result["intent"] == "bad_example" and confidence < 0.5:
                        should_store = False
                        log.debug(f"Disabling storage for bad example at index {i} due to low confidence: {confidence}")
                    
                    result["should_store"] = should_store
                    
                    result["user_query"] = str(result.get("user_query", ""))
                    result["ai_response"] = str(result.get("ai_response", ""))
                    result["reasoning"] = str(result.get("reasoning", ""))
                    
                    tool_calls = result.get("tool_calls", [])
                    if not isinstance(tool_calls, list):
                        log.warning(f"Converting non-list tool_calls to empty list at index {i}")
                        tool_calls = []
                    result["tool_calls"] = tool_calls
                    
                    result["storage_status"] = "not_attempted"
                    
                    # Only attempt storage if should_store is True and query is not empty
                    if result["user_query"].strip() and result["should_store"]:
                        try:
                            label = "positive" if result["intent"] == "good_example" else "negative"
                            
                            log.debug(f"Attempting to store example {i+1}: {result['intent']} - Query: '{result['user_query'][:50]}...'")
                            await episodic_memory_manager.store_interaction_example(
                                query=result["user_query"],
                                response=result["ai_response"],
                                label=label,
                                tool_calls=tool_calls
                            )
                            result["storage_status"] = "stored_successfully"
                            result["storage_message"] = f"Successfully stored as {label} example"
                            print(f"Successfully stored example {i+1} as {label} example")
                                
                        except Exception as storage_error:
                            result["storage_status"] = "failed"
                            result["storage_message"] = f"Storage failed: {str(storage_error)}"
                            print(f"Failed to store example {i+1}: {storage_error}")
                    
                    elif result["user_query"].strip():
                        result["storage_status"] = "skipped_low_confidence"
                        result["storage_message"] = "Skipped due to low confidence or should_store=False"
                        log.debug(f"Skipping storage for example {i+1} due to low confidence or should_store=False")
                    else:
                        result["storage_status"] = "skipped_empty_query"
                        result["storage_message"] = "Skipped due to empty user query"
                        log.debug(f"Skipping example {i+1} due to empty user_query")
                    
                    processed_results.append(result)
            
            if processed_results:
                print(f"Analysis and storage completed: Found {len(processed_results)} valid examples out of {len(episodic_results)} total results")
                
                storage_summary = {}
                for result in processed_results:
                    status = result.get("storage_status", "unknown")
                    storage_summary[status] = storage_summary.get(status, 0) + 1
                
                log.info(f"Storage summary: {storage_summary}")
            
            return {
                "preferences_result": final_preferences_response,
                "episodic_results": processed_results if processed_results else []
            }
            
        except Exception as e:
            error_msg = f"Error in combined analysis: {e}"
            log.error(error_msg, exc_info=True)
            return {
                "preferences_result": "",
                "episodic_results": [{
                    "intent": "bad_example",
                    "confidence": 0.0,
                    "reasoning": error_msg,
                    "should_store": False,
                    "user_query": "",
                    "ai_response": "",
                    "tool_calls": [],
                    "storage_status": "failed",
                    "storage_message": error_msg
                }]
            }
        
    async def fetch_memory_from_postgres(self):
        """
        Fetches memory value for a given key from PostgreSQL for the specified agent.

        Args:
            agent_id (str): The ID of the agent.
            key (str): The memory key to fetch.

        Returns:
            str: The memory value associated with the key, or an empty string if not found.
        """
        try:
            memory_value = await self.repo.fetch_memory_from_postgres()
            if memory_value is not None:
                log.info(f"Fetched memory for")
                return memory_value
            else:
                log.info(f"No memory found ")
                return ""
        except Exception as e:
            log.error(f"Error fetching memory : {e}")
            return ""

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


# --- Export Service ---

class ExportService:
    def __init__(
        self,
        export_repo: ExportAgentRepository
    ):
        self.export_repo = export_repo


    async def insert_export_log(self, export_id, agent_id: str, agent_name: str, user_name: str, user_email: str, export_time: datetime) -> bool:
        await self.export_repo.insert_export_log_record(export_id=export_id, agent_id=agent_id, agent_name=agent_name, user_name=user_name, user_email=user_email, export_time=export_time)

    async def get_unique_exporters_by_agent_id(self, agent_id: str) -> List[str]:
        return await self.export_repo.get_unique_exporters_record_by_agent_id(agent_id=agent_id)

    async def send_email(self, agentic_application_id: str, agentic_application_name: str, updater: str) -> bool:
        import smtplib
        from email.mime.multipart import MIMEMultipart
        from email.mime.text import MIMEText
        SENDER_EMAIL_ADDRESS = 'BLRKECSMTP01.ad.infosys.com'
        SMTP_IP = '172.21.5.10'
        SMTP_PORT = 25
        SMTP_USER = None
        SMTP_PASS = None
        SMTP_REQUIRES_AUTH = False
        USE_SSL_CONNECTION = False
        USE_TLS_CONNECTION = False
        from datetime import date
        current_date = date.today()
        recipient_list = await self.get_unique_exporters_by_agent_id(agentic_application_id)
        if not recipient_list:
            return True  # No recipients, nothing to send
        actual_smtp_username = SMTP_USER if SMTP_USER else SENDER_EMAIL_ADDRESS
        subject = f"Important: The '{agentic_application_name}' You Exported Has Been Updated"
        body = f"""
        Dear User,
 
        This is an automated notification from the Infosys Agentic Foundry Team.
	    The agent, '{agentic_application_name}', which you previously exported, has recently been updated.
 
        Update Details:
        Agent Name: {agentic_application_name}
        Updated By: {updater}
        Date of Update: {current_date}
 
        For a detailed understanding of the changes, please contact the individual who performed the update.
 
        Regards,
        Infosys Agentic Foundry Team
        """
        msg = MIMEMultipart()
        msg['From'] = SENDER_EMAIL_ADDRESS
        msg['To'] = ', '.join(recipient_list)
        msg['Subject'] = subject
        msg.attach(MIMEText(body, 'plain'))
        server = None
        try:
            server = smtplib.SMTP(SMTP_IP, SMTP_PORT)
            if USE_TLS_CONNECTION:
                server.starttls()
            if SMTP_REQUIRES_AUTH:
                if not actual_smtp_username or not SMTP_PASS:
                    return False
                server.login(actual_smtp_username, SMTP_PASS)
            server.sendmail(SENDER_EMAIL_ADDRESS, recipient_list, msg.as_string())
            return True
        except Exception as e:
            return False
        finally:
            if server:
                try:
                    server.quit()
                except Exception as e:
                    log.error('Error while quitting SMTP server: {e}')


