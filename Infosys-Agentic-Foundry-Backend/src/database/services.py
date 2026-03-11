# © 2024-25 Infosys Limited, Bangalore, India. All Rights Reserved.
import os
import re
import ast
import json
import uuid
import shutil
import inspect
import hashlib
import asyncio
import difflib
import subprocess
import pandas as pd
from pathlib import Path
from datetime import datetime, timezone
from typing import List, Optional, Union, Dict, Any, Literal, Tuple
from fastapi import UploadFile, HTTPException
from langchain_core.tools import BaseTool, StructuredTool
from langchain_core.prompts import PromptTemplate
from langchain_core.output_parsers import StrOutputParser
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage, ChatMessage, AnyMessage
from langchain_mcp_adapters.client import MultiServerMCPClient
from google.adk.events.event import Event
from google.adk.sessions.session import Session
from google.genai import types
from google.adk.sessions import DatabaseSessionService

from src.utils.remote_model_client import RemoteSentenceTransformer as SentenceTransformer
from src.utils.remote_model_client import RemoteCrossEncoder as CrossEncoder
from pathlib import Path
from src.auth.models import User, UserRole, AddRoleRequest, SetRolePermissionsRequest, UpdateRolePermissionsRequest, RoleResponse, RoleListResponse, RolePermissionsResponse, AllRolePermissionsResponse, RoleModel, RoleAccessModel, AccessPermission, DepartmentModel, AddDepartmentRequest, DepartmentResponse, DepartmentListResponse, AddAdminsToDepartmentRequest, RemoveAdminFromDepartmentRequest, DepartmentRoleResponse
import json
from typing import Any, Dict, List

from src.database.repositories import (
    AgentKnowledgebaseMappingRepository, KnowledgebaseRepository, TagRepository, TagToolMappingRepository, TagAgentMappingRepository,
    ToolRepository, ToolAgentMappingRepository, RecycleToolRepository,
    AgentRepository, RecycleAgentRepository, ChatHistoryRepository,
    FeedbackLearningRepository, EvaluationDataRepository,
    ToolEvaluationMetricsRepository, AgentEvaluationMetricsRepository,
    ExportAgentRepository, McpToolRepository, RecycleMcpToolRepository, AgentDataTableRepository, 
    AgentMetadataRepository, ChatStateHistoryManagerRepository, PipelineRepository, PipelineRunRepository, AgentPipelineMappingRepository,
    PipelineStepsRepository, save_pending_module, get_all_pending_modules, ToolGenerationCodeVersionRepository, 
    UserAgentAccessRepository, GroupRepository, GroupSecretsRepository, ToolAccessKeyMappingRepository,
    AccessKeyDefinitionsRepository, ToolDepartmentSharingRepository
)
from src.database.admin_config_service import AdminConfigService
from src.auth.repositories import RoleRepository, UserRepository, AuditLogRepository, DepartmentRepository
from src.auth.authorization_service import AuthorizationService
from src.models.model_service import ModelService
from src.prompts.prompts import CONVERSATION_SUMMARY_PROMPT
from src.tools.tool_code_processor import ToolCodeProcessor
from src.utils.secrets_handler import get_user_secrets, current_user_email
from src.utils.tool_file_manager import ToolFileManager
from src.config.constants import AgentType, FrameworkType, Limits, TableNames
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


# --- SecurityMaliciousOperationAnalyzer ---

class SecurityMaliciousOperationAnalyzer:
    """
    Advanced security analyzer for detecting malicious operations in MCP server code.
    Implements precise AST-based detection aligned with safe_validation policy.
    """
    
    # Dangerous operation categories and their detection patterns
    DANGEROUS_FILE_FUNCS = {
        "os.remove", "os.unlink", "os.rmdir", "shutil.rmtree", 
        "pathlib.Path.unlink", "pathlib.Path.rmdir", "pathlib.PurePath.unlink"
    }
    
    DANGEROUS_PROCESS_FUNCS = {
        "os.kill", "signal.kill", "psutil.Process.kill", "psutil.Process.terminate",
        "subprocess.kill", "subprocess.terminate"
    }
    
    DANGEROUS_PRIV_FUNCS = {
        "os.chown", "os.chmod"
    }
    
    DANGEROUS_CONFIG_PATHS = {
        "/etc/", "/etc/passwd", "/etc/shadow", "/etc/hosts", "/etc/fstab",
        "C:\\Windows\\System32", "C:\\Windows\\", "/usr/bin/", "/usr/sbin/",
        "/bin/", "/sbin/", "~/.bashrc", "~/.profile", "~/.bash_profile"
    }
    
    COMMAND_DANGEROUS_TOKENS = {
        "rm", "rmdir", "del", "shutdown", "reboot", "poweroff", "halt",
        "kill", "chmod", "chown", "taskkill", "pkill", "killall", "systemctl"
    }
    
    COMMAND_CRITICAL_FLAGS = {
        "-rf", "-r", "-f", "/s", "/q", "--force", "--recursive"
    }
    
    @staticmethod
    def analyze_code_for_malicious_operations(code: str) -> Dict[str, Any]:
        """
        Main analysis function that detects malicious operations in code.
        Returns validation result in safe_validation format.
        
        Args:
            code (str): Python code to analyze
            
        Returns:
            Dict: {"validation": bool, "suggestion": str (optional)}
        """
        try:
            # Stage 1: Parse AST
            tree = ast.parse(code)
            
            # Stage 2: Collect imports and their aliases
            import_aliases = SecurityMaliciousOperationAnalyzer._collect_import_aliases(tree)
            
            # Stage 3: Detect dangerous operations
            unsafe_operation = SecurityMaliciousOperationAnalyzer._detect_dangerous_operations(
                tree, import_aliases
            )
            
            if unsafe_operation:
                return {
                    "validation": False,
                    "suggestion": unsafe_operation
                }
            
            return {"validation": True}
            
        except SyntaxError:
            return {
                "validation": False,
                "suggestion": "Code contains syntax errors that prevent security analysis."
            }
        except Exception as e:
            # Default to unsafe if analysis fails
            return {
                "validation": False,
                "suggestion": f"Security analysis failed: {str(e)}"
            }
    
    @staticmethod
    def _collect_import_aliases(tree: ast.AST) -> Dict[str, str]:
        """
        Collect import aliases to resolve function calls.
        Returns mapping: alias -> original_module
        """
        aliases = {}
        
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.asname:
                        aliases[alias.asname] = alias.name
                    else:
                        aliases[alias.name] = alias.name
            elif isinstance(node, ast.ImportFrom) and node.module:
                for alias in node.names:
                    if alias.asname:
                        aliases[alias.asname] = f"{node.module}.{alias.name}"
                    else:
                        aliases[alias.name] = f"{node.module}.{alias.name}"
        
        return aliases
    
    @staticmethod
    def _detect_dangerous_operations(tree: ast.AST, import_aliases: Dict[str, str]) -> Optional[str]:
        """
        Detect dangerous operations in the AST.
        Returns first unsafe operation found or None if safe.
        """
        # First pass: collect variable assignments that involve string concatenation/formatting
        dangerous_vars = set()
        
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign):
                # Check for assignments like: code = "..." + user_input
                for target in node.targets:
                    if isinstance(target, ast.Name):
                        var_name = target.id
                        # Check if the value involves string concatenation or formatting
                        if SecurityMaliciousOperationAnalyzer._is_dynamic_string_construction(node.value):
                            dangerous_vars.add(var_name)
        
        # Second pass: check for dangerous operations
        for node in ast.walk(tree):
            # Check function calls
            if isinstance(node, ast.Call):
                unsafe_msg = SecurityMaliciousOperationAnalyzer._check_dangerous_call(
                    node, import_aliases, dangerous_vars
                )
                if unsafe_msg:
                    return unsafe_msg
            
            # Check file operations with write mode
            elif isinstance(node, ast.With):
                unsafe_msg = SecurityMaliciousOperationAnalyzer._check_dangerous_file_write(node)
                if unsafe_msg:
                    return unsafe_msg
            
            # Check direct assignments to system modules
            elif isinstance(node, ast.Assign):
                unsafe_msg = SecurityMaliciousOperationAnalyzer._check_dangerous_assignment(node)
                if unsafe_msg:
                    return unsafe_msg
        
        return None
    
    @staticmethod
    def _is_dynamic_string_construction(node: ast.AST) -> bool:
        """Check if a node represents dynamic string construction (concatenation/formatting)."""
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
            # String concatenation
            return True
        elif isinstance(node, ast.Call):
            if isinstance(node.func, ast.Attribute) and node.func.attr == "format":
                # String formatting
                return True
        return False
    
    @staticmethod
    def _check_dangerous_call(node: ast.Call, import_aliases: Dict[str, str], dangerous_vars: set = None) -> Optional[str]:
        """Check if a function call is dangerous."""
        func_path = SecurityMaliciousOperationAnalyzer._get_function_path(node.func, import_aliases)
        
        if not func_path:
            return None
        
        # 1. File deletion operations
        if func_path in SecurityMaliciousOperationAnalyzer.DANGEROUS_FILE_FUNCS:
            return f"Remove file deletion operation ({func_path}) to ensure safety."
        
        # 2. Process control operations
        if func_path in SecurityMaliciousOperationAnalyzer.DANGEROUS_PROCESS_FUNCS:
            return f"Remove process termination call ({func_path}); killing processes is prohibited."
        
        # 3. Permission changes (check for overly permissive chmod)
        if func_path == "os.chmod":
            if SecurityMaliciousOperationAnalyzer._is_permissive_chmod(node):
                return "Avoid broad permission chmod 0o777; remove or restrict."
        
        if func_path in SecurityMaliciousOperationAnalyzer.DANGEROUS_PRIV_FUNCS:
            return f"Remove privilege escalation operation ({func_path}) to ensure safety."
        
        # 4. Subprocess operations (detailed analysis)
        if func_path in ["subprocess.run", "subprocess.Popen", "subprocess.call", "subprocess.check_call"]:
            unsafe_msg = SecurityMaliciousOperationAnalyzer._check_subprocess_command(node)
            if unsafe_msg:
                return unsafe_msg
        
        # 5. System shutdown operations
        if func_path in ["os.system", "subprocess.run", "subprocess.call"]:
            unsafe_msg = SecurityMaliciousOperationAnalyzer._check_system_shutdown(node)
            if unsafe_msg:
                return unsafe_msg
        
        # 6. Code injection patterns - be more permissive per policy
        if func_path in ["__import__"]:
            # Only block dynamic imports which can be used for code injection
            return "Remove dynamic import (__import__); use static imports instead."
        
        # Note: exec and eval are allowed per safe_validation policy
        # Only block if combined with clearly malicious patterns
        
        return None
    
    @staticmethod
    def _get_function_path(func_node: ast.AST, import_aliases: Dict[str, str]) -> Optional[str]:
        """Extract the full path of a function call."""
        if isinstance(func_node, ast.Name):
            # Simple function call: func()
            if func_node.id in import_aliases:
                return import_aliases[func_node.id]
            return func_node.id
        elif isinstance(func_node, ast.Attribute):
            # Attribute call: obj.func()
            if isinstance(func_node.value, ast.Name):
                base = func_node.value.id
                if base in import_aliases:
                    return f"{import_aliases[base]}.{func_node.attr}"
                return f"{base}.{func_node.attr}"
            elif isinstance(func_node.value, ast.Attribute):
                # Nested attribute: obj.subobj.func()
                parent_path = SecurityMaliciousOperationAnalyzer._get_function_path(func_node.value, import_aliases)
                if parent_path:
                    return f"{parent_path}.{func_node.attr}"
        
        return None
    
    @staticmethod
    def _is_permissive_chmod(node: ast.Call) -> bool:
        """Check if chmod call uses overly permissive permissions."""
        if len(node.args) >= 2:
            perm_arg = node.args[1]
            if isinstance(perm_arg, ast.Constant):
                # Check for 0o777 or 511 (decimal)
                if isinstance(perm_arg.value, int) and perm_arg.value >= 0o777:
                    return True
            elif isinstance(perm_arg, ast.Num):  # Python < 3.8 compatibility
                if perm_arg.n >= 0o777:
                    return True
        return False
    
    @staticmethod
    def _check_subprocess_command(node: ast.Call) -> Optional[str]:
        """Analyze subprocess commands for dangerous operations."""
        if not node.args:
            return None
        
        command_arg = node.args[0]
        
        # Check string commands
        if isinstance(command_arg, ast.Constant) and isinstance(command_arg.value, str):
            return SecurityMaliciousOperationAnalyzer._analyze_command_string(command_arg.value)
        
        # Check list commands
        elif isinstance(command_arg, ast.List):
            command_tokens = []
            for elem in command_arg.elts:
                if isinstance(elem, ast.Constant) and isinstance(elem.value, str):
                    command_tokens.append(elem.value)
            
            if command_tokens:
                return SecurityMaliciousOperationAnalyzer._analyze_command_tokens(command_tokens)
        
        return None
    
    @staticmethod
    def _analyze_command_string(command: str) -> Optional[str]:
        """Analyze a command string for dangerous patterns."""
        tokens = command.lower().split()
        
        # Check for dangerous tokens
        for token in tokens:
            if token in SecurityMaliciousOperationAnalyzer.COMMAND_DANGEROUS_TOKENS:
                # Check for destructive flags
                if any(flag in command.lower() for flag in SecurityMaliciousOperationAnalyzer.COMMAND_CRITICAL_FLAGS):
                    return f"Remove destructive shell command '{token}'; destructive operations not allowed."
                
                # Specific dangerous patterns
                if token in ["shutdown", "reboot", "poweroff", "halt"]:
                    return "Remove system shutdown command; system control operations are disallowed."
                elif token in ["kill", "taskkill", "pkill", "killall"]:
                    return "Remove process termination command; killing processes is prohibited."
                elif token in ["rm", "rmdir", "del"] and any(flag in command.lower() for flag in ["-rf", "-r", "/s"]):
                    return "Remove destructive deletion command; destructive file operations not allowed."
        
        return None
    
    @staticmethod
    def _analyze_command_tokens(tokens: List[str]) -> Optional[str]:
        """Analyze command tokens list for dangerous patterns."""
        if not tokens:
            return None
        
        first_token = tokens[0].lower()
        
        if first_token in SecurityMaliciousOperationAnalyzer.COMMAND_DANGEROUS_TOKENS:
            if first_token in ["shutdown", "reboot", "poweroff", "halt"]:
                return "Remove system shutdown command; system control operations are disallowed."
            elif first_token in ["kill", "taskkill", "pkill", "killall"]:
                return "Remove process termination command; killing processes is prohibited."
            elif first_token in ["rm", "rmdir", "del"]:
                # Check for destructive flags
                for token in tokens[1:]:
                    if token.lower() in SecurityMaliciousOperationAnalyzer.COMMAND_CRITICAL_FLAGS:
                        return "Remove destructive deletion command; destructive file operations not allowed."
        
        return None
    
    @staticmethod
    def _check_system_shutdown(node: ast.Call) -> Optional[str]:
        """Check for system shutdown commands in os.system or subprocess calls."""
        if not node.args:
            return None
        
        command_arg = node.args[0]
        if isinstance(command_arg, ast.Constant) and isinstance(command_arg.value, str):
            command = command_arg.value.lower()
            shutdown_patterns = ["shutdown", "reboot", "poweroff", "halt", "systemctl reboot", "systemctl poweroff"]
            
            for pattern in shutdown_patterns:
                if pattern in command:
                    return "Remove system shutdown command; system control operations are disallowed."
        
        return None
    
    @staticmethod
    def _is_dangerous_exec(node: ast.Call) -> bool:
        """Check if exec() call is potentially dangerous."""
        if not node.args:
            return False
        
        # Simple heuristic: exec with string concatenation or format operations is risky
        code_arg = node.args[0]
        
        # Check for string operations that might indicate code injection
        if isinstance(code_arg, ast.BinOp) and isinstance(code_arg.op, ast.Add):
            return True  # String concatenation in exec
        elif isinstance(code_arg, ast.Call):
            if isinstance(code_arg.func, ast.Attribute) and code_arg.func.attr == "format":
                return True  # String format in exec
        
        return False
    
    @staticmethod
    def _exec_uses_dangerous_var(node: ast.Call, dangerous_vars: set) -> bool:
        """Check if exec() call uses a variable that was constructed dangerously."""
        if not node.args or not dangerous_vars:
            return False
        
        code_arg = node.args[0]
        if isinstance(code_arg, ast.Name) and code_arg.id in dangerous_vars:
            return True
        
        return False
    
    @staticmethod
    def _check_dangerous_file_write(node: ast.With) -> Optional[str]:
        """Check for dangerous file write operations to protected paths."""
        for item in node.items:
            if isinstance(item.context_expr, ast.Call):
                func_path = SecurityMaliciousOperationAnalyzer._get_function_path(item.context_expr.func, {})
                
                if func_path == "open" and len(item.context_expr.args) >= 2:
                    # Check file path and mode
                    path_arg = item.context_expr.args[0]
                    mode_arg = item.context_expr.args[1]
                    
                    if (isinstance(path_arg, ast.Constant) and isinstance(path_arg.value, str) and
                        isinstance(mode_arg, ast.Constant) and isinstance(mode_arg.value, str)):
                        
                        file_path = path_arg.value
                        mode = mode_arg.value
                        
                        # Check if writing to protected path
                        if any(mode_char in mode.lower() for mode_char in ['w', 'a']):
                            for protected_path in SecurityMaliciousOperationAnalyzer.DANGEROUS_CONFIG_PATHS:
                                if protected_path in file_path:
                                    return f"Do not overwrite system config file {protected_path}."
        
        return None
    
    @staticmethod
    def _check_dangerous_assignment(node: ast.Assign) -> Optional[str]:
        """Check for dangerous assignments to system modules."""
        for target in node.targets:
            if isinstance(target, ast.Subscript):
                # Check sys.modules[...] assignment
                if (isinstance(target.value, ast.Attribute) and 
                    isinstance(target.value.value, ast.Name) and
                    target.value.value.id == "sys" and 
                    target.value.attr == "modules"):
                    return "Remove modification of sys.modules; runtime tampering not allowed."
                
                # Check builtins assignment
                elif (isinstance(target.value, ast.Attribute) and
                      isinstance(target.value.value, ast.Name) and
                      target.value.value.id == "__builtins__"):
                    return "Remove modification of __builtins__; runtime tampering not allowed."
        
        return None


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
        recycle_mcp_tool_repo: 'RecycleMcpToolRepository',
        tag_service: TagService, # Needed for tag mapping
        tool_agent_mapping_repo: ToolAgentMappingRepository, # Needed for dependency checks
        agent_repo: AgentRepository, # Needed for dependency checks
        mcp_tool_sharing_repo = None  # Repository for MCP tool department sharing
    ):
        self.mcp_tool_repo = mcp_tool_repo
        self.recycle_mcp_tool_repo = recycle_mcp_tool_repo
        self.tag_service = tag_service
        self.tool_agent_mapping_repo = tool_agent_mapping_repo
        self.agent_repo = agent_repo
        self.mcp_tool_sharing_repo = mcp_tool_sharing_repo  # Store MCP tool sharing repo
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
            department_name: Optional[str] = None,
            shared_with_departments: Optional[List[str]] = None,  # For sharing MCP tool with other departments
            is_public: bool = False,  # Whether the MCP tool should be public
        ) -> Dict[str, Any]:
        """
        Creates a new MCP tool (server definition) and saves it to the database.
        Handles file creation for 'file' type MCPs with comprehensive validation.
        """
        # Validate: is_public and shared_with_departments are mutually exclusive
        if is_public and shared_with_departments:
            log.warning(f"Cannot create MCP tool '{tool_name}' with both is_public and shared_with_departments set.")
            return {
                "message": "Cannot set both 'is_public' and 'shared_with_departments'. A public MCP tool is already accessible to all departments.",
                "is_created": False
            }
        
        # Generate tool_id with appropriate prefix
        tool_id_prefix = f"mcp_{mcp_type}_"
        tool_id = tool_id_prefix + str(uuid.uuid4())
        update_session_context(tool_id=tool_id, tool_name=tool_name)

        if await self.mcp_tool_repo.get_mcp_tool_record(tool_name=tool_name, department_name= department_name):
            log.warning(f"MCP tool with name '{tool_name}' already exists.")
            return {"message": f"MCP tool with name '{tool_name}' already exists.", "is_created": False}

        # Inline validation for file-based MCP tools
        if mcp_type == "file":
            if not code_content:
                return {"message": "Code content is required for 'file' type MCP tools.", "is_created": False}
            
            # Enhanced validation pipeline with malicious operation detection
            validation_result = await self._validate_mcp_file_code(code_content)
            
            # Log validation result for auditing and security monitoring
            await self.mcp_tool_repo.log_mcp_validation_result(tool_id, validation_result)
            
            if not validation_result["is_valid"]:
                return {
                    "message": "File validation failed - code contains unsafe operations",
                    "is_created": False,
                    "errors": validation_result.get("errors", []),
                    "warnings": validation_result.get("warnings", [])
                }
            
            # Log any warnings but continue with creation
            if validation_result.get("warnings"):
                log.warning(f"MCP tool '{tool_name}' validation warnings: {validation_result['warnings']}")

        mcp_config: Dict[str, Any] = {"transport": "stdio"} # Default transport

        if mcp_type == "file":
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
            mcp_module_name = mcp_module_name.replace("-", "_") # Normalize module name
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
            "is_public": is_public,
            "status": "pending", # Default values as per schema
            "comments": None,
            "approved_at": None,
            "approved_by": None,
            "created_by": created_by,
            "created_on": now,
            "updated_on": now,
            "department_name": department_name
        }

        success = await self.mcp_tool_repo.save_mcp_tool_record(tool_data)

        if success:
            if not tag_ids:
                general_tag = await self.tag_service.get_tag(tag_name="General")
                tag_ids = [general_tag['tag_id']] if general_tag else []
            await self.tag_service.assign_tags_to_tool(tag_ids=tag_ids, tool_id=tool_id)

            log.info(f"Successfully onboarded MCP tool '{tool_name}' with ID: {tool_id}")
            result = {"message": f"Successfully onboarded MCP tool '{tool_name}'", "tool_id": tool_id, "is_created": True}
            
            # Include validation warnings in success response if any
            if mcp_type == "file" and validation_result.get("warnings"):
                result["warnings"] = validation_result["warnings"]
            
            # Handle sharing with other departments if requested
            if shared_with_departments and self.mcp_tool_sharing_repo and department_name:
                try:
                    sharing_result = await self.mcp_tool_sharing_repo.share_mcp_tool_with_multiple_departments(
                        mcp_tool_id=tool_id,
                        mcp_tool_name=tool_name,
                        source_department=department_name,
                        target_departments=shared_with_departments,
                        shared_by=created_by
                    )
                    result["sharing_status"] = sharing_result
                    log.info(f"MCP tool '{tool_name}' shared with {sharing_result['success_count']} department(s)")
                except Exception as e:
                    log.error(f"Error sharing MCP tool '{tool_name}' with departments: {e}")
                    result["sharing_status"] = {"error": str(e), "success_count": 0}
                
            return result
        else:
            log.error(f"Failed to onboard MCP tool '{tool_name}'.")
            return {"message": f"Failed to onboard MCP tool '{tool_name}'.", "is_created": False}

    async def _validate_mcp_file_code(self, code_content: str) -> Dict[str, Any]:
        """
        Comprehensive validation pipeline for file-based MCP server code.
        Returns validation result with errors/warnings.
        """
        log.info("Starting enhanced MCP file validation with SecurityMaliciousOperationAnalyzer")
        errors = []
        warnings = []
        
        # Helper functions for validation stages
        def _check_syntax_and_compile(code: str) -> bool:
            """Stage 1: Basic syntax validation"""
            try:
                ast.parse(code)
                compile(code, "<mcp_validation>", "exec")
                return True
            except SyntaxError as e:
                errors.append(f"SYNTAX_ERROR: {str(e)}")
                return False
            except Exception as e:
                errors.append(f"COMPILE_ERROR: {str(e)}")
                return False

        def _check_security_malicious_operations(code: str) -> bool:
            """Stage 2: Enhanced malicious operation detection using SecurityMaliciousOperationAnalyzer"""
            try:
                log.info("Running SecurityMaliciousOperationAnalyzer on code")
                security_result = SecurityMaliciousOperationAnalyzer.analyze_code_for_malicious_operations(code)
                log.info(f"Security analysis result: {security_result}")
                
                if not security_result.get("validation", True):
                    suggestion = security_result.get("suggestion", "Malicious operation detected")
                    errors.append(f"SECURITY_VIOLATION: {suggestion}")
                    log.warning(f"Malicious operation detected: {suggestion}")
                    return False
                
                log.info("Code passed security analysis")
                return True
                
            except Exception as e:
                log.error(f"Security analysis failed: {str(e)}")
                errors.append(f"SECURITY_ANALYSIS_ERROR: Failed to analyze code for malicious operations: {str(e)}")
                return False

        def _check_basic_imports(tree: ast.AST) -> bool:
            """Stage 2b: Basic import restrictions (still keeping some network restrictions)"""
            # Only restrict network libraries if you want to maintain current policy
            # Remove this if network operations should be fully allowed per your policy
            restricted_network_imports = {
                'socket', 'threading', 'multiprocessing'  # Keep minimal restrictions
            }
            
            for node in ast.walk(tree):
                # Check imports
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        if alias.name in restricted_network_imports:
                            warnings.append(f"NETWORK_IMPORT_WARNING: Import '{alias.name}' detected - ensure proper usage")
                elif isinstance(node, ast.ImportFrom):
                    if node.module and node.module in restricted_network_imports:
                        warnings.append(f"NETWORK_IMPORT_WARNING: Import 'from {node.module}' detected - ensure proper usage")
            return True

        def _check_mcp_structure(tree: ast.AST) -> bool:
            """Stage 3: Validate MCP server structure and patterns"""
            has_mcp_import = False
            has_tool_definitions = False
            has_server_start = False
            
            # Check for MCP-related imports
            mcp_patterns = ['fastmcp', 'mcp', 'model_context_protocol']
            server_calls = ['serve', 'run', 'start']
            
            for node in ast.walk(tree):
                # Check imports
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        if any(pattern in alias.name for pattern in mcp_patterns):
                            has_mcp_import = True
                elif isinstance(node, ast.ImportFrom):
                    if node.module and any(pattern in node.module for pattern in mcp_patterns):
                        has_mcp_import = True
                
                # Check for tool definitions (decorators or TOOLS list)
                # Support both synchronous (FunctionDef) and asynchronous (AsyncFunctionDef) tool functions
                elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    for decorator in node.decorator_list:
                        # Handle @tool, @fastmcp.tool patterns
                        if isinstance(decorator, ast.Name) and decorator.id == 'tool':
                            has_tool_definitions = True
                        elif isinstance(decorator, ast.Attribute):
                            # Handle @fastmcp.tool, @mcp.tool, @instance.tool patterns
                            if decorator.attr == 'tool':
                                has_tool_definitions = True
                        # Handle @mcp.tool() function calls (FastMCP instance methods)
                        elif isinstance(decorator, ast.Call):
                            if isinstance(decorator.func, ast.Attribute) and decorator.func.attr == 'tool':
                                has_tool_definitions = True
                            elif isinstance(decorator.func, ast.Name) and decorator.func.id == 'tool':
                                has_tool_definitions = True
                
                # Check for TOOLS assignment
                elif isinstance(node, ast.Assign):
                    for target in node.targets:
                        if isinstance(target, ast.Name) and target.id == 'TOOLS':
                            has_tool_definitions = True
                
                # Check for server start calls
                elif isinstance(node, ast.Call):
                    if isinstance(node.func, ast.Name) and node.func.id in server_calls:
                        has_server_start = True
                    elif isinstance(node.func, ast.Attribute) and node.func.attr in server_calls:
                        has_server_start = True
            
            if not has_mcp_import:
                errors.append("STRUCTURE_MISSING: No MCP library import found (fastmcp, mcp, model_context_protocol)")
                return False
            if not has_tool_definitions:
                errors.append("STRUCTURE_MISSING: No tool definitions found (@tool decorators or TOOLS list)")
                return False
            if not has_server_start:
                warnings.append("SERVER_START_MISSING: No server start call found (serve, run, start)")
            
            return True

        def _validate_tool_functions(tree: ast.AST) -> bool:
            """Stage 4: Validate individual tool functions"""
            for node in ast.walk(tree):
                # Support both sync and async tool functions
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    # Check if function has tool decorator
                    has_tool_decorator = False
                    for decorator in node.decorator_list:
                        # Handle @tool, @fastmcp.tool patterns
                        if isinstance(decorator, ast.Name) and decorator.id == 'tool':
                            has_tool_decorator = True
                        elif isinstance(decorator, ast.Attribute) and decorator.attr == 'tool':
                            has_tool_decorator = True
                        # Handle @mcp.tool() function calls (FastMCP instance methods)
                        elif isinstance(decorator, ast.Call):
                            if isinstance(decorator.func, ast.Attribute) and decorator.func.attr == 'tool':
                                has_tool_decorator = True
                            elif isinstance(decorator.func, ast.Name) and decorator.func.id == 'tool':
                                has_tool_decorator = True
                    
                    if has_tool_decorator:
                        # Check for docstring
                        docstring = ast.get_docstring(node)
                        if not docstring:
                            warnings.append(f"TOOL_DOCSTRING_MISSING: Tool function '{node.name}' missing docstring")
                        
                        # Check for type hints (basic check)
                        if not node.args.args:
                            warnings.append(f"TOOL_NO_PARAMS: Tool function '{node.name}' has no parameters")
            
            return True

        async def _runtime_smoke_test(code: str) -> bool:
            """Stage 5: Optional runtime validation"""
            try:
                # Create a safe environment for testing - preserve critical Windows vars
                import os
                test_env = dict(os.environ)  # Start with current environment
                
                # Override specific vars for security/testing
                test_env.update({
                    'PYTHONPATH': '',
                    'MCP_VALIDATION': '1',
                    'PYTHONIOENCODING': 'utf-8'
                })
                
                # Run with timeout
                result = subprocess.run(
                    ['python', '-c', code],
                    capture_output=True,
                    text=True,
                    timeout=5,
                    env=test_env,
                    shell=False
                )
                
                if result.returncode != 0:
                    if result.stderr:
                        # Check if it's a missing dependency error (non-critical)
                        stderr_lower = result.stderr.lower()
                        if any(pattern in stderr_lower for pattern in [
                            'modulenotfounderror', 'no module named', 'importerror',
                            'pygments', 'rich', 'fastmcp dependencies'
                        ]):
                            warnings.append(f"RUNTIME_DEPENDENCY_MISSING: {result.stderr.strip()}")
                            warnings.append("RUNTIME_TEST_SKIPPED: Skipping runtime test due to missing dependencies")
                            return True  # Don't fail validation for missing dependencies
                        # Check for Windows asyncio/socket initialization issues (non-critical)
                        elif 'winerror 10106' in stderr_lower or 'requested service provider could not be loaded' in stderr_lower:
                            warnings.append(f"RUNTIME_WINDOWS_SOCKET_ISSUE: {result.stderr.strip()}")
                            warnings.append("RUNTIME_TEST_SKIPPED: Skipping runtime test due to Windows socket initialization issue")
                            return True  # Don't fail validation for Windows socket issues
                        else:
                            errors.append(f"RUNTIME_FAILURE: {result.stderr.strip()}")
                            return False
                    else:
                        errors.append(f"RUNTIME_FAILURE: Process exited with code {result.returncode}")
                        return False
                
                # Check for any error patterns in output
                if "Error" in result.stderr or "Exception" in result.stderr:
                    warnings.append(f"RUNTIME_WARNING: {result.stderr.strip()}")
                
                return True
                
            except subprocess.TimeoutExpired:
                warnings.append("RUNTIME_TIMEOUT: Code execution timed out (>5 seconds) - treating as non-critical")
                return True  # Don't fail validation for timeout
            except Exception as e:
                warnings.append(f"RUNTIME_TEST_ERROR: {str(e)} - skipping runtime validation")
                return True  # Don't fail validation for runtime test errors

        # Validation pipeline execution
        # Stage 1: Size and basic checks
        if len(code_content.encode('utf-8')) > 100 * 1024:  # 100KB limit
            errors.append("FILE_TOO_LARGE: Code content exceeds 100KB limit")
            return {"is_valid": False, "errors": errors, "warnings": warnings}
        
        if not code_content.strip():
            errors.append("EMPTY_CODE: Code content is empty")
            return {"is_valid": False, "errors": errors, "warnings": warnings}

        # Stage 2: Syntax validation
        if not _check_syntax_and_compile(code_content):
            return {"is_valid": False, "errors": errors, "warnings": warnings}

        # Stage 3: Parse AST for further checks
        try:
            tree = ast.parse(code_content)
        except Exception as e:
            errors.append(f"AST_PARSE_ERROR: {str(e)}")
            return {"is_valid": False, "errors": errors, "warnings": warnings}

        # Stage 4: Enhanced malicious operation detection
        if not _check_security_malicious_operations(code_content):
            return {"is_valid": False, "errors": errors, "warnings": warnings}

        # Stage 5: Basic import warnings (optional network restrictions)
        _check_basic_imports(tree)

        # Stage 6: MCP structure validation
        if not _check_mcp_structure(tree):
            return {"is_valid": False, "errors": errors, "warnings": warnings}

        # Stage 7: Tool function validation
        _validate_tool_functions(tree)

        # Stage 8: Runtime smoke test (optional, only if no structural errors)
        try:
            await _runtime_smoke_test(code_content)
        except Exception as e:
            warnings.append(f"RUNTIME_TEST_SKIPPED: {str(e)}")

        # Return validation result
        is_valid = len(errors) == 0
        return {
            "is_valid": is_valid,
            "errors": errors,
            "warnings": warnings,
            "code_hash": hashlib.sha256(code_content.encode()).hexdigest()
        }

    # --- MCP Tool Retrieval Operations ---

    async def get_mcp_tool(self, tool_id: Optional[str] = None, tool_name: Optional[str] = None, department_name: str= None, include_shared: bool = True) -> List[Dict[str, Any]]:
        """
        Retrieves a single MCP tool (server definition) record by ID or name.
        If not found in own department, checks if it's shared with the department or public.
        """
        tool_records = await self.mcp_tool_repo.get_mcp_tool_record(tool_id=tool_id, tool_name=tool_name, department_name= department_name)
        
        # If not found and department_name provided, check if tool is shared with this department or public
        if not tool_records and department_name and tool_id:
            # First check if it's shared
            if self.mcp_tool_sharing_repo:
                is_shared = await self.mcp_tool_sharing_repo.is_mcp_tool_shared_with_department(tool_id, department_name)
                if is_shared:
                    # Get the tool without department filter
                    tool_records = await self.mcp_tool_repo.get_mcp_tool_record(tool_id=tool_id)
                    if tool_records:
                        tool_records[0]['is_shared'] = True
            
            # If still not found, check if it's public
            if not tool_records:
                tool_records = await self.mcp_tool_repo.get_mcp_tool_record(tool_id=tool_id)
                if tool_records and tool_records[0].get('is_public'):
                    tool_records[0]['is_public_access'] = True
                elif tool_records:
                    # Tool exists but user doesn't have access
                    tool_records = []
        
        if not tool_records:
            log.info(f"No MCP tool found with ID: {tool_id} or Name: {tool_name}.")
            return []

        # Ensure mcp_config is a Python dict (asyncpg usually handles JSONB deserialization)
        for record in tool_records:
            if isinstance(record.get("mcp_config"), str):
                record["mcp_config"] = json.loads(record["mcp_config"])
            record["mcp_type"] = await self._get_mcp_type_by_id(record['tool_id'])
            record['tags'] = await self.tag_service.get_tags_by_tool(record['tool_id'])
            
            # Add sharing info if repository is available
            if self.mcp_tool_sharing_repo:
                shared_info = await self.mcp_tool_sharing_repo.get_shared_departments_for_mcp_tool(record['tool_id'])
                record['shared_with_departments'] = [s['target_department'] for s in shared_info]
        
        log.info(f"Retrieved MCP tool with ID: {tool_records[0]['tool_id']} and Name: {tool_records[0]['tool_name']}.")
        return tool_records

    async def get_all_mcp_tools(self, department_name: str = None, include_shared: bool = True) -> List[Dict[str, Any]]:
        """
        Retrieves all MCP tool (server definition) records with associated tags.
        Includes shared MCP tools when department_name is specified and include_shared is True.
        """
        # Get shared MCP tool IDs for this department
        shared_mcp_tool_ids = []
        if department_name and include_shared and self.mcp_tool_sharing_repo:
            shared_mcp_tool_ids = await self.mcp_tool_sharing_repo.get_mcp_tools_shared_with_department(department_name)
        
        tool_records = await self.mcp_tool_repo.get_all_mcp_tool_records(department_name=department_name, shared_mcp_tool_ids=shared_mcp_tool_ids)
        tool_id_to_tags = await self.tag_service.get_tool_id_to_tags_dict()

        for tool in tool_records:
            if isinstance(tool.get("mcp_config"), str):
                tool["mcp_config"] = json.loads(tool["mcp_config"])
            tool["mcp_type"] = await self._get_mcp_type_by_id(tool['tool_id'])
            tool['tags'] = tool_id_to_tags.get(tool['tool_id'], [])
            
            # Extract server_type and functions from mcp_config for display
            mcp_config = tool.get("mcp_config", {})
            tool["server_type"] = mcp_config.get("server_type", "LOCAL")
            tool["functions"] = mcp_config.get("functions", [])
            tool["function_count"] = mcp_config.get("function_count", len(tool["functions"]))
            
            # Mark as shared if it's from another department
            if department_name and tool.get('department_name') != department_name:
                tool['is_shared'] = True
            else:
                tool['is_shared'] = False
            
            # Add sharing info if repository is available
            if self.mcp_tool_sharing_repo:
                shared_info = await self.mcp_tool_sharing_repo.get_shared_departments_for_mcp_tool(tool['tool_id'])
                tool['shared_with_departments'] = [s['target_department'] for s in shared_info]
            
        log.info(f"Retrieved {len(tool_records)} MCP tools.")
        return tool_records

    async def get_mcp_tools_by_search_or_page(self, search_value: str = '', limit: int = 20, page: int = 1, tag_names: Optional[List[str]] = None, mcp_type: Optional[List[Literal["file", "url", "module"]]] = None, created_by:str = None, department_name: str=None) -> Dict[str, Any]:
        """
        Retrieves MCP tools (server definitions) with pagination and search filtering, including associated tags.
        Includes shared and public MCP tools when department_name is specified.
        """
        # Get shared MCP tool IDs if department specified
        shared_mcp_tool_ids = []
        if department_name and self.mcp_tool_sharing_repo:
            shared_mcp_tool_ids = await self.mcp_tool_sharing_repo.get_mcp_tools_shared_with_department(department_name)
        
        total_count = await self.mcp_tool_repo.get_total_mcp_tool_count(search_value, mcp_type, created_by, department_name=department_name, shared_mcp_tool_ids=shared_mcp_tool_ids)
        if tag_names:
            tag_names = set(tag_names)
            tool_records = await self.mcp_tool_repo.get_mcp_tools_by_search_or_page_records(search_value, total_count, 1, mcp_type, created_by, department_name=department_name, shared_mcp_tool_ids=shared_mcp_tool_ids)
        else:
            tool_records = await self.mcp_tool_repo.get_mcp_tools_by_search_or_page_records(search_value, limit, page, mcp_type, created_by, department_name=department_name, shared_mcp_tool_ids=shared_mcp_tool_ids)

        tool_id_to_tags = await self.tag_service.get_tool_id_to_tags_dict()
        filtered_tools = []

        for tool in tool_records:
            if isinstance(tool.get("mcp_config"), str):
                tool["mcp_config"] = json.loads(tool["mcp_config"])
            tool["mcp_type"] = await self._get_mcp_type_by_id(tool['tool_id'])                     
            tool['tags'] = tool_id_to_tags.get(tool['tool_id'], [])
            
            # Extract server_type and functions from mcp_config for display
            mcp_config = tool.get("mcp_config", {})
            tool["server_type"] = mcp_config.get("server_type", "LOCAL")
            tool["functions"] = mcp_config.get("functions", [])
            tool["function_count"] = mcp_config.get("function_count", len(tool["functions"]))
            
            # Mark as shared if it's from another department
            if department_name and tool.get('department_name') != department_name:
                tool['is_shared'] = True
            else:
                tool['is_shared'] = False
            
            # Add shared departments information
            if self.mcp_tool_sharing_repo:
                shared_info = await self.mcp_tool_sharing_repo.get_shared_departments_for_mcp_tool(tool['tool_id'])
                tool['shared_with_departments'] = [s['target_department'] for s in shared_info]
            else:
                tool['shared_with_departments'] = []
            
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
        approved_by: Optional[str] = None,
        shared_with_departments: Optional[List[str]] = None  # For sharing MCP tool with other departments
    ) -> Dict[str, Any]:
        """
        Updates an existing MCP tool (server definition) record.
        Only allows 'code_content' updates for 'mcp_file_' type tools.
        """
        tool_records = await self.mcp_tool_repo.get_mcp_tool_record(tool_id=tool_id)
        if not tool_records:
            log.error(f"Error: MCP tool not found with ID: {tool_id}")
            return {"message": f"Error: MCP tool not found with ID: {tool_id}", "is_update": False}

        tool_data = tool_records[0]

        if not is_admin and tool_data["created_by"] != user_id:
            err = f"Permission denied: Only the admin or the tool's creator can perform this action for MCP Tool: {tool_data['tool_name']}."
            log.error(err)
            return {"message": err, "is_update": False}

        # Check if any actual updates are requested
        if not any([tool_description, code_content, updated_tag_id_list,
                    is_public is not None, status, comments, approved_at, approved_by,
                    shared_with_departments is not None]):
            return {"message": "No fields provided to update the MCP tool.", "is_update": False}

        # Validate: is_public and shared_with_departments are mutually exclusive
        # Check both the incoming update values and the existing tool state
        effective_is_public = is_public if is_public is not None else tool_data.get("is_public", False)
        if effective_is_public and shared_with_departments:
            log.warning(f"Cannot update MCP tool '{tool_id}' with both is_public=True and shared_with_departments.")
            return {
                "message": "Cannot set 'shared_with_departments' when MCP tool is public. A public tool is already accessible to all departments.",
                "is_update": False
            }

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

        # VALIDATION: Check if making tool non-public would break agents in other departments
        current_is_public = tool_data.get("is_public", False)
        is_public_changing_to_false = is_public is not None and not is_public and current_is_public
        
        if is_public_changing_to_false:
            agents_using_tool = await self.tool_agent_mapping_repo.get_tool_agent_mappings_record(tool_id=tool_id)
            if agents_using_tool:
                blocking_agents = []
                tool_department = tool_data.get('department_name', '')
                
                for mapping in agents_using_tool:
                    agent_id = mapping.get('agentic_application_id')
                    agent_records = await self.agent_repo.get_agent_record(agentic_application_id=agent_id)
                    if not agent_records:
                        continue
                    agent = agent_records[0]
                    agent_name = agent.get('agentic_application_name', agent_id)
                    agent_department = agent.get('department_name', '')
                    
                    # Block if agent is from a different department (it relies on tool being public)
                    if agent_department and tool_department and agent_department != tool_department:
                        blocking_agents.append({
                            "agentic_application_id": agent_id,
                            "agentic_application_name": agent_name,
                            "agent_department": agent_department,
                            "agentic_app_created_by": agent.get('created_by', ''),
                            "reason": f"Agent belongs to department '{agent_department}' and accesses this tool via public visibility."
                        })
                    # Also block if agent is public (needs tool accessible to all)
                    elif agent.get('is_public', False):
                        blocking_agents.append({
                            "agentic_application_id": agent_id,
                            "agentic_application_name": agent_name,
                            "agent_department": agent_department,
                            "agentic_app_created_by": agent.get('created_by', ''),
                            "reason": "Agent is public and requires this tool to be accessible."
                        })
                
                if blocking_agents:
                    agent_detail_msgs = []
                    for ba in blocking_agents[:5]:
                        dept_info = f" (Department: {ba['agent_department']})" if ba.get('agent_department') else ""
                        agent_detail_msgs.append(f"'{ba['agentic_application_name']}'{dept_info}")
                    agents_summary = ", ".join(agent_detail_msgs)
                    if len(blocking_agents) > 5:
                        agents_summary += f" and {len(blocking_agents) - 5} more"
                    
                    log.error(f"Cannot make MCP tool '{tool_data['tool_name']}' non-public: Used by agents in other departments: {[a['agentic_application_name'] for a in blocking_agents]}")
                    return {
                        "message": f"Cannot make tool '{tool_data['tool_name']}' non-public: It is currently used by {len(blocking_agents)} agent(s) in other departments that would lose access: {agents_summary}. Please remove this tool from those agents first, or keep the tool public.",
                        "details": blocking_agents,
                        "is_update": False
                    }

        # Handle tags update
        if updated_tag_id_list:
            await self.tag_service.clear_tags(tool_id=tool_id)
            await self.tag_service.assign_tags_to_tool(tag_ids=updated_tag_id_list, tool_id=tool_id)
            log.info(f"Tags updated for MCP tool ID: {tool_id}")

        # Handle code_content update for 'mcp_file_' type only
        validation_result = {}
        if tool_id.startswith("mcp_file_") and code_content:
            agent_using_this_tool_raw = await self.tool_agent_mapping_repo.get_tool_agent_mappings_record(tool_id=tool_id)
            if agent_using_this_tool_raw:
                agent_ids = [m['agentic_application_id'] for m in agent_using_this_tool_raw]
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
                    log.error(f"The MCP tool you are trying to update is being referenced by {len(agent_details)} agentic application(s).")
                    return {
                        "message": f"The MCP tool you are trying to update is being referenced by {len(agent_details)} agentic application(s).",
                        "details": agent_details,
                        "is_update": False
                    }

            # Enhanced validation with malicious operation detection
            validation_result = await self._validate_mcp_file_code(code_content)
            
            # Log validation result for security auditing
            await self.mcp_tool_repo.log_mcp_validation_result(tool_id, validation_result)
            
            if not validation_result["is_valid"]:
                return {
                    "message": "Code validation failed - contains unsafe operations",
                    "is_update": False,
                    "errors": validation_result.get("errors", []),
                    "warnings": validation_result.get("warnings", [])
                }
            
            # Log any warnings but continue with update
            if validation_result.get("warnings"):
                log.warning(f"MCP tool '{tool_id}' code update validation warnings: {validation_result['warnings']}")
            
            if isinstance(tool_data.get("mcp_config"), str):
                tool_data["mcp_config"] = json.loads(tool_data["mcp_config"])
            tool_data["mcp_config"]["args"][1] = code_content.strip() # Update code content

            update_payload["mcp_config"] = tool_data["mcp_config"] # Add updated config to payload
            log.info(f"Code content updated for MCP file tool ID: {tool_id}")


        success = await self.mcp_tool_repo.update_mcp_tool_record(update_payload, tool_id)

        if success:
            log.info(f"Successfully updated MCP tool with ID: {tool_id}.")
            result = {"message": f"Successfully updated MCP tool: {tool_data['tool_name']}.", "is_update": True}

            # Include validation warnings in success response if any
            if "warnings" in validation_result:
                result["warnings"] = validation_result["warnings"]
            
            # Handle sharing with other departments if requested
            if shared_with_departments is not None and self.mcp_tool_sharing_repo:
                source_department = tool_data.get('department_name', 'General')
                try:
                    # If empty list, unshare from all departments
                    if len(shared_with_departments) == 0:
                        removed_count = await self.mcp_tool_sharing_repo.unshare_mcp_tool_from_all_departments(tool_id)
                        result["sharing_status"] = {"message": f"Removed sharing from {removed_count} department(s)", "success_count": 0, "removed_count": removed_count}
                    else:
                        # First, clear existing shares
                        await self.mcp_tool_sharing_repo.unshare_mcp_tool_from_all_departments(tool_id)
                        # Then add new shares
                        sharing_result = await self.mcp_tool_sharing_repo.share_mcp_tool_with_multiple_departments(
                            mcp_tool_id=tool_id,
                            mcp_tool_name=tool_data['tool_name'],
                            source_department=source_department,
                            target_departments=shared_with_departments,
                            shared_by=user_id
                        )
                        result["sharing_status"] = sharing_result
                        log.info(f"MCP tool '{tool_id}' sharing updated: {sharing_result['success_count']} department(s)")
                except Exception as e:
                    log.error(f"Error updating MCP tool sharing: {e}")
                    result["sharing_status"] = {"error": str(e), "success_count": 0}
            
            return result

        else:
            log.error(f"Failed to update MCP tool with ID: {tool_id}.")
            return {"message": f"Failed to update MCP tool: {tool_data['tool_name']}.", "is_update": False}

    # --- MCP Tool Deletion Operations ---

    async def delete_mcp_tool(self, tool_id: str, user_id: str, is_admin: bool = False) -> Dict[str, Any]:
        """
        Deletes an MCP tool (server definition) record from the database.
        Handles file deletion for 'mcp_file_' type tools.
        """
        tool_records = await self.mcp_tool_repo.get_mcp_tool_record(tool_id=tool_id)
        if not tool_records:
            log.error(f"No MCP tool found with ID: {tool_id}")
            return {"message": f"No MCP tool found with ID: {tool_id}", "is_delete": False}
        
        tool_data = tool_records[0]

        if not is_admin and tool_data["created_by"] != user_id:
            err = f"Permission denied: Only the admin or the tool's creator can perform this action for MCP Tool: {tool_data['tool_name']}."
            log.error(err)
            return {"message": err, "is_delete": False}

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
                    "message": f"The MCP tool you are trying to delete is being referenced by {len(agent_details)} agentic application(s).",
                    "details": agent_details,
                    "is_delete": False
                }
        
        # All deletions (admin and creator) move to recycle bin (soft delete)
        insert_success = await self.recycle_mcp_tool_repo.insert_recycle_mcp_tool_record(tool_data)
        if not insert_success:
            log.error(f"Failed to move MCP tool '{tool_id}' to recycle bin.")
            return {"message": "Failed to move MCP tool to recycle bin.", "is_delete": False}

        # Clean up mappings before deleting from main table
        await self.tool_agent_mapping_repo.remove_tool_from_agent_record(tool_id=tool_data['tool_id'])
        await self.tag_service.clear_tags(tool_id=tool_id)

        # Clean up access key mapping if exists
        if hasattr(self, 'tool_access_key_mapping_repo') and self.tool_access_key_mapping_repo:
            await self.tool_access_key_mapping_repo.delete_tool_access_keys(tool_id=tool_data['tool_id'])

        # Delete from main table
        delete_success = await self.mcp_tool_repo.delete_mcp_tool_record(tool_id)
        if delete_success:
            log.info(f"Successfully moved MCP tool '{tool_data['tool_name']}' to recycle bin.")
            return {"message": f"Successfully moved MCP tool '{tool_data['tool_name']}' to recycle bin.", "is_delete": True}
        else:
            # Rollback: Remove from recycle bin since delete from main table failed
            log.error(f"Failed to delete MCP tool '{tool_data['tool_name']}' from main table. Rolling back recycle bin insert.")
            rollback_success = await self.recycle_mcp_tool_repo.delete_recycle_mcp_tool_record(tool_id)
            if not rollback_success:
                log.error(f"Rollback failed: Could not remove MCP tool '{tool_id}' from recycle bin. Tool may exist in both tables.")
            return {"message": f"Failed to delete MCP tool: {tool_data['tool_name']}. The tool remains in the main table.", "is_delete": False}

    # --- MCP Tool Recycle Bin Operations ---

    async def get_all_mcp_tools_from_recycle_bin(self, department_name: str = None) -> List[Dict[str, Any]]:
        """
        Retrieves all MCP tools from the recycle bin with tags and mcp_type.

        Args:
            department_name (str): The department name to filter by.

        Returns:
            list: A list of dictionaries representing the MCP tools in the recycle bin.
        """
        tool_records = await self.recycle_mcp_tool_repo.get_all_recycle_mcp_tool_records(department_name=department_name)
        tool_id_to_tags = await self.tag_service.get_tool_id_to_tags_dict()

        for tool in tool_records:
            # Parse mcp_config from JSON string to dict (if not already parsed)
            if isinstance(tool.get("mcp_config"), str):
                tool["mcp_config"] = json.loads(tool["mcp_config"])
            
            # Add mcp_type (file/url/module) derived from tool_id prefix
            tool["mcp_type"] = await self._get_mcp_type_by_id(tool['tool_id'])
            
            # Add tags
            tool['tags'] = tool_id_to_tags.get(tool['tool_id'], [])
        
        log.info(f"Retrieved {len(tool_records)} MCP tools from recycle bin.")
        return tool_records

    async def restore_mcp_tool_from_recycle_bin(self, tool_id: str, department_name: str = None) -> Dict[str, Any]:
        """
        Restores an MCP tool from the recycle bin to the main mcp_tool_table.

        Args:
            tool_id (str): The ID of the MCP tool to restore.
            department_name (str): The department name to filter by.

        Returns:
            dict: Status of the operation.
        """
        if not tool_id:
            log.warning("No tool ID provided for MCP tool restoration.")
            return {
                "message": "Error: Must provide 'tool_id' to restore an MCP tool.",
                "details": [],
                "is_restored": False
            }

        tool_data = await self.recycle_mcp_tool_repo.get_recycle_mcp_tool_record(tool_id=tool_id, department_name=department_name)
        if not tool_data:
            log.warning(f"No MCP tool available in recycle bin with ID: {tool_id}")
            return {
                "message": f"No MCP tool available in recycle bin with ID: {tool_id}",
                "details": [],
                "is_restored": False
            }

        # Attempt to save to main table
        success = await self.mcp_tool_repo.save_mcp_tool_record(tool_data)
        
        if not success:
            log.error(f"Failed to restore MCP tool {tool_data['tool_name']} to main table (might already exist).")
            return {
                "message": f"Failed to restore MCP tool {tool_data['tool_name']} to main table (might already exist).",
                "details": [],
                "is_restored": False
            }

        # Assign General tag only after successful save to main table
        general_tag = await self.tag_service.get_tag(tag_name="General")
        if general_tag:
            await self.tag_service.assign_tags_to_tool(
                tag_ids=general_tag["tag_id"],
                tool_id=tool_data['tool_id']
            )

        # Delete from recycle bin
        delete_success = await self.recycle_mcp_tool_repo.delete_recycle_mcp_tool_record(tool_data['tool_id'])
        if delete_success:
            log.info(f"Successfully restored MCP tool {tool_data['tool_id']} from recycle bin.")
            return {
                "message": f"Successfully restored MCP tool with ID: {tool_data['tool_id']}",
                "details": [],
                "is_restored": True
            }
        else:
            log.error(f"Failed to delete MCP tool {tool_data['tool_id']} from recycle bin after restoration.")
            return {
                "message": f"MCP tool {tool_data['tool_id']} restored to main table, but failed to delete from recycle bin.",
                "details": [],
                "is_restored": False
            }


    async def permanent_delete_mcp_tool_from_recycle_bin(self, tool_id: str, department_name: str = None) -> Dict[str, Any]:
        """
        Deletes an MCP tool permanently from the recycle bin.

        Args:
            tool_id (str): The ID of the MCP tool to delete.
            department_name (str): The department name to filter by.

        Returns:
            dict: Status of the operation.
        """
        if not tool_id:
            log.warning("No tool ID provided for permanent MCP tool deletion.")
            return {
                "message": "Error: Must provide 'tool_id' to permanently delete an MCP tool.",
                "details": [],
                "is_deleted": False
            }

        tool_data = await self.recycle_mcp_tool_repo.get_recycle_mcp_tool_record(tool_id=tool_id, department_name=department_name)
        if not tool_data:
            log.warning(f"No MCP tool available in recycle bin with ID: {tool_id}")
            return {
                "message": f"No MCP tool available in recycle bin with ID: {tool_id}",
                "details": [],
                "is_deleted": False
            }

        success = await self.recycle_mcp_tool_repo.delete_recycle_mcp_tool_record(tool_data['tool_id'])
        if success:
            log.info(f"Successfully permanently deleted MCP tool from recycle bin with ID: {tool_data['tool_id']}")
            return {
                "message": f"Successfully permanently deleted MCP tool from recycle bin with ID: {tool_data['tool_id']}",
                "details": [],
                "is_deleted": True
            }
        else:
            log.error(f"Failed to permanently delete MCP tool {tool_data['tool_id']} from recycle bin.")
            return {
                "message": f"Failed to permanently delete MCP tool {tool_data['tool_id']} from recycle bin.",
                "details": [],
                "is_deleted": False
            }

    async def get_unused_mcp_tools(self, threshold_days: int = 15, department_name: str = None) -> List[Dict[str, Any]]:
        """
        Retrieves all MCP tools that haven't been used (based on updated_on timestamp).
        Since MCP tools don't have a last_used field, we use updated_on as a proxy.
        
        Args:
            threshold_days (int): Number of days to consider an MCP tool as unused. Default is 15.
            department_name (str): The department name to filter by.
            
        Returns:
            List[Dict[str, Any]]: A list of unused MCP tools with their details, including mcp_type, tags, and mcp_config.
        """
        try:
            # Get MCP tools where updated_on is older than threshold
            # Using updated_on since MCP tools don't have a last_used column
            if department_name:
                query = f"""
                    SELECT *
                    FROM {TableNames.MCP_TOOL.value} 
                    WHERE updated_on < (NOW() - INTERVAL '1 day' * $1)
                    AND department_name = $2
                    ORDER BY updated_on ASC
                """
                result = await self.mcp_tool_repo.pool.fetch(query, threshold_days, department_name)
            else:
                query = f"""
                    SELECT *
                    FROM {TableNames.MCP_TOOL.value} 
                    WHERE updated_on < (NOW() - INTERVAL '1 day' * $1)
                    ORDER BY updated_on ASC
                """
                result = await self.mcp_tool_repo.pool.fetch(query, threshold_days)
            
            tools = []
            # Collect all unique created_by email addresses
            email_set = set(row.get('created_by') for row in result if row.get('created_by'))

            # Batch fetch usernames for all emails
            if email_set:
                email_list = list(email_set)
                async with self.mcp_tool_repo.login_pool.acquire() as conn:
                    user_rows = await conn.fetch(
                        f"SELECT mail_id, user_name FROM {TableNames.LOGIN_CREDENTIAL.value} WHERE mail_id = ANY($1)", email_list
                    )
                email_to_username = {row['mail_id']: row['user_name'] for row in user_rows}
            else:
                email_to_username = {}

            # Fetch tags mapping once for all tools
            tool_id_to_tags = await self.tag_service.get_tool_id_to_tags_dict()

            for row in result:
                tool_dict = dict(row)
                
                # Parse mcp_config from JSON string to dict if needed
                if isinstance(tool_dict.get("mcp_config"), str):
                    tool_dict["mcp_config"] = json.loads(tool_dict["mcp_config"])
                
                # Add mcp_type (file/url/module)
                tool_dict["mcp_type"] = await self._get_mcp_type_by_id(tool_dict['tool_id'])
                
                # Add tags
                tool_dict['tags'] = tool_id_to_tags.get(tool_dict['tool_id'], [])
                
                # Replace email with username if available
                email = tool_dict.get('created_by')
                if email:
                    username = email_to_username.get(email)
                    if username:
                        tool_dict['created_by'] = username
                
                tools.append(tool_dict)
                
            log.info(f"Found {len(tools)} unused MCP tools (threshold: {threshold_days} days)")
            return tools
            
        except Exception as e:
            log.error(f"Error retrieving unused MCP tools: {e}")
            return []

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
            return {"message": f"Successfully approved MCP tool with ID: {tool_id}", "is_approved": True}
        else:
            log.error(f"Failed to approve MCP tool with ID: {tool_id}")
            return {"message": f"Failed to approve MCP tool with ID: {tool_id}", "is_approved": False}

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

    async def get_live_mcp_tools_from_server(self, tool_id: str, department_name: str = None) -> Dict[str, Any]:
        """
        Connects to the live MCP server defined by the given tool_id and discovers
        the tools it exposes.
        """
        tool_records = await self.mcp_tool_repo.get_mcp_tool_record(tool_id=tool_id, department_name=department_name)
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
            live_tools: Optional[List[StructuredTool]] = None,
            department_name: str = None
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
                mcp_server_data = await self.get_live_mcp_tools_from_server(tool_id, department_name)
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

    # --- MCP Tool Testing Operations ---

    async def test_mcp_tools(
            self,
            tool_id: str,
            invocations: List[Dict[str, Any]],  # [{"tool_name": str, "args": Dict[str, Any]}]
            parallel: bool = False,
            timeout_sec: int = 15,
            user_id: str = "",
            is_admin: bool = False,
            department_name: str = None
        ) -> Dict[str, Any]:
        """
        Tests MCP tools by executing them with provided arguments.

        Args:
            tool_id (str): The ID of the MCP server definition.
            invocations (List[Dict[str, Any]]): List of tool invocations to execute.
            parallel (bool): Whether to execute invocations in parallel.
            timeout_sec (int): Timeout per tool invocation in seconds.
            user_id (str): The user performing the test.
            is_admin (bool): Whether the user is an admin.

        Returns:
            Dict[str, Any]: Test results with execution details.
        """
        started_at = datetime.now(timezone.utc)
        
        # Validate request
        if not invocations:
            raise ValueError("At least one invocation is required")
        
        if len(invocations) > 10:
            raise ValueError("Maximum 10 invocations allowed per request")
        
        if not (1 <= timeout_sec <= 60):
            raise ValueError("Timeout must be between 1 and 60 seconds")

        # Get MCP server definition
        tool_records = await self.mcp_tool_repo.get_mcp_tool_record(tool_id=tool_id, department_name=department_name)
        if not tool_records:
            raise ValueError(f"MCP server definition not found for tool_id: {tool_id}")

        tool_data = tool_records[0]
        
        # Authorization check
        if not is_admin and tool_data["created_by"] != user_id:
            if not (tool_data.get("status") == "approved" and tool_data.get("is_public")):
                raise PermissionError("Access denied: Only creator, admin, or public approved tools can be tested")

        server_name = tool_data["tool_name"]
        mcp_config = tool_data["mcp_config"]
        
        # Ensure mcp_config is a Python dict
        if isinstance(mcp_config, str):
            mcp_config = json.loads(mcp_config)

        try:
            # Discover live tools from server
            live_tools = await self.get_tools_from_mcp_configs({server_name: mcp_config})
            
            # Index tools by name
            name_to_tool = {tool.name: tool for tool in live_tools}
            log.info(f"Discovered {len(live_tools)} tools from MCP server: {server_name}")
            
            # Prepare invocation tasks
            async def execute_single_invocation(invocation: Dict[str, Any]) -> Dict[str, Any]:
                tool_name = invocation.get("tool_name", "")
                args = invocation.get("args", {})
                
                exec_start = datetime.now()
                
                # Validate tool exists
                if tool_name not in name_to_tool:
                    return {
                        "tool_name": tool_name,
                        "success": False,
                        "latency_ms": 0.0,
                        "output": None,
                        "error": "TOOL_NOT_FOUND: Tool not available in this MCP server"
                    }
                
                tool = name_to_tool[tool_name]
                
                # Basic argument validation
                try:
                    # Check for unexpected arguments
                    expected_args = set(tool.args.keys()) if tool.args else set()
                    provided_args = set(args.keys())
                    unexpected_args = provided_args - expected_args
                    
                    if unexpected_args:
                        return {
                            "tool_name": tool_name,
                            "success": False,
                            "latency_ms": 0.0,
                            "output": None,
                            "error": f"UNEXPECTED_ARGUMENTS: {list(unexpected_args)}"
                        }
                    
                    # Check for missing required arguments (basic check)
                    if tool.args:
                        for arg_name, arg_schema in tool.args.items():
                            if arg_name not in args:
                                # Check if argument has default or is optional
                                if not arg_schema.get("default") and arg_schema.get("type") != "optional":
                                    return {
                                        "tool_name": tool_name,
                                        "success": False,
                                        "latency_ms": 0.0,
                                        "output": None,
                                        "error": f"MISSING_REQUIRED_ARGUMENT: {arg_name}"
                                    }
                    
                    # Execute tool with timeout
                    try:
                        if hasattr(tool, 'ainvoke'):
                            output = await asyncio.wait_for(tool.ainvoke(args), timeout=timeout_sec)
                        elif hasattr(tool, 'arun'):
                            output = await asyncio.wait_for(tool.arun(**args), timeout=timeout_sec)
                        else:
                            # Fallback to sync invoke wrapped in asyncio
                            output = await asyncio.wait_for(
                                asyncio.to_thread(tool.invoke, args), 
                                timeout=timeout_sec
                            )
                        
                        exec_end = datetime.now()
                        latency_ms = (exec_end - exec_start).total_seconds() * 1000
                        
                        # Ensure output is JSON serializable
                        try:
                            json.dumps(output)
                            serialized_output = output
                        except (TypeError, ValueError):
                            serialized_output = str(output)
                        
                        return {
                            "tool_name": tool_name,
                            "success": True,
                            "latency_ms": round(latency_ms, 2),
                            "output": serialized_output,
                            "error": None
                        }
                        
                    except asyncio.TimeoutError:
                        exec_end = datetime.now()
                        latency_ms = (exec_end - exec_start).total_seconds() * 1000
                        return {
                            "tool_name": tool_name,
                            "success": False,
                            "latency_ms": round(latency_ms, 2),
                            "output": None,
                            "error": f"TIMEOUT: Execution exceeded {timeout_sec} seconds"
                        }
                    except Exception as e:
                        exec_end = datetime.now()
                        latency_ms = (exec_end - exec_start).total_seconds() * 1000
                        return {
                            "tool_name": tool_name,
                            "success": False,
                            "latency_ms": round(latency_ms, 2),
                            "output": None,
                            "error": f"EXECUTION_ERROR: {str(e)}"
                        }
                        
                except Exception as e:
                    return {
                        "tool_name": tool_name,
                        "success": False,
                        "latency_ms": 0.0,
                        "output": None,
                        "error": f"VALIDATION_ERROR: {str(e)}"
                    }
            
            # Execute invocations
            if parallel:
                log.info(f"Executing {len(invocations)} tool invocations in parallel")
                results = await asyncio.gather(
                    *[execute_single_invocation(inv) for inv in invocations],
                    return_exceptions=False
                )
            else:
                log.info(f"Executing {len(invocations)} tool invocations sequentially")
                results = []
                for invocation in invocations:
                    result = await execute_single_invocation(invocation)
                    results.append(result)
            
            finished_at = datetime.now(timezone.utc)
            overall_success = all(result["success"] for result in results)
            
            log.info(f"Completed MCP tool test for {tool_id}: {len(results)} invocations, overall_success={overall_success}")
            
            return {
                "tool_id": tool_id,
                "server_name": server_name,
                "started_at": started_at.isoformat(),
                "finished_at": finished_at.isoformat(),
                "overall_success": overall_success,
                "results": results
            }
            
        except Exception as e:
            finished_at = datetime.now(timezone.utc)
            log.error(f"Error during MCP tool test for {tool_id}: {e}")
            raise ValueError(f"Failed to execute MCP tool test: {str(e)}")


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
        mcp_tool_service: McpToolService, # Inject the new MCP Tool Service
        tool_file_manager: ToolFileManager, # Inject the ToolFileManager
        tool_access_key_mapping_repo: ToolAccessKeyMappingRepository = None,  # Repository for tool access key mappings
        access_key_definitions_repo: AccessKeyDefinitionsRepository = None,  # Repository for checking if access keys exist
        tool_sharing_repo: ToolDepartmentSharingRepository = None,  # Repository for tool department sharing
        department_repo: DepartmentRepository = None  # Repository for validating department names
    ):
        self.tool_repo = tool_repo
        self.recycle_tool_repo = recycle_tool_repo
        self.tool_agent_mapping_repo = tool_agent_mapping_repo
        self.tag_service = tag_service
        self.tool_code_processor = tool_code_processor
        self.agent_repo = agent_repo # Store agent_repo for direct use in dependency checks
        self.model_service = model_service
        self.mcp_tool_service = mcp_tool_service # Store MCP Tool Service
        self.tool_file_manager = tool_file_manager # Store ToolFileManager
        self.tool_access_key_mapping_repo = tool_access_key_mapping_repo  # Store access key mapping repo
        self.access_key_definitions_repo = access_key_definitions_repo  # Store access key definitions repo
        self.tool_sharing_repo = tool_sharing_repo  # Store tool sharing repo
        self.department_repo = department_repo  # Store department repo for validation

    def _extract_module_name_from_error(self, error_message: str) -> Optional[str]:
        """Extract module name from 'No module named' error messages."""
        if not error_message or "No module named" not in error_message:
            return None
        
        match = re.search(r"No module named ['\"]([^'\"]+)['\"]", error_message)
        if match:
            return match.group(1)
        return None

    async def get_pending_modules(self) -> List[Dict[str, Any]]:
        """Get all pending modules from the database."""
        try:
            return await get_all_pending_modules(self.tool_repo.pool)
        except Exception as e:
            log.error(f"Error retrieving pending modules: {e}")
            return []

    # --- Tool Creation Operations ---

    async def create_tool(self, tool_data: Dict[str, Any], force_add, is_validator: Optional[bool] = False, is_public: Optional[bool] = False, shared_with_departments: Optional[List[str]] = None) -> Dict[str, Any]:
        """
        Creates a new tool, including validation, docstring generation, and saving to the database.

        Args:
            tool_data (dict): A dictionary containing the tool data to save.
            force_add (bool): Force add flag for bypassing certain validations.
            is_validator (bool, optional): Whether this is a validator tool.
            is_public (bool, optional): Whether the tool is public (accessible to all departments).
            shared_with_departments (List[str], optional): List of department names to share the tool with.

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
        if not force_add:
            initial_state = {
                    "code": tool_data["code_snippet"],
                    "model": tool_data["model_name"],
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
                    "feedback_case7": None,
                    "validation_case8": None,
                    "feedback_case8": None
                }
            workflow_result = await graph.ainvoke(input=initial_state)
            w_cases=["validation_case3","validation_case5","validation_case6","validation_case7"]
            e_cases=["validation_case8","validation_case1","validation_case4"]
            warnings={}
            errors={}
            log.info(f"Tool validation results: {workflow_result}")
            for i in w_cases:
                if not workflow_result.get(i):
                    feedback_key = i.replace("validation_", "feedback_")
                    if workflow_result.get(feedback_key):
                        warnings[i] = workflow_result.get(feedback_key)
            for j in e_cases:
                if not workflow_result.get(j):
                    feedback_key = j.replace("validation_", "feedback_")
                    errors[j] = workflow_result.get(feedback_key)
            if errors:
                if 'validation_case1' in errors:
                    feedback_case1 = workflow_result.get('feedback_case1', '')
                    module_name = self._extract_module_name_from_error(feedback_case1)
                    if module_name:
                        try:
                            await save_pending_module(
                                pool=self.tool_repo.pool,
                                module_name=module_name,
                                tool_name=tool_data['tool_name'],
                                created_by=current_user_email.get(),
                                tool_code=tool_data.get('code_snippet')
                            )
                            log.info(f"Saved pending module '{module_name}' for tool '{tool_data['tool_name']}'")
                        except Exception as e:
                            log.error(f"Error saving pending module: {e}")
                
                verify=list(errors.values())
                return {
                        "message": verify[0],
                        "tool_id": "",
                        "tool_name": tool_data['tool_name'],
                        "model_name": tool_data.get('model_name', ''),
                        "created_by": tool_data.get('created_by', ''),
                        "is_created": False
                    }
            
            # Check if access keys used in @resource_access decorators exist in Resource Dashboard
            if self.access_key_definitions_repo:
                access_keys = self.tool_code_processor.extract_access_keys_from_code(tool_data.get("code_snippet", ""))
                department_name = tool_data.get("department_name", None)
                if access_keys and department_name:
                    missing_keys = []
                    for ak in access_keys:
                        key_definition = await self.access_key_definitions_repo.get_access_key(ak, department_name)
                        if not key_definition:
                            missing_keys.append(ak)
                    if missing_keys:
                        warning_msg = f"Access keys {missing_keys} used in @resource_access decorators are not defined in the Resource Dashboard.Please create them first."
                        log.warning(f"Tool '{tool_data.get('tool_name', 'unknown')}' uses undefined access keys: {missing_keys}")
                        warnings["access_key_validation"] = warning_msg
            
            # Return all warnings together
            if warnings:
                    verify=list(warnings.values())
                    return {
                        "message": ("Verification failed: "+str(verify)),
                        "tool_id": "",
                        "error_on_screen": False,
                        "warnings":True,
                        "is_created": False
                    }
        
        # [INFO] Validator-specific validation for validator tools
        if is_validator:
            validator_validation = await self.tool_code_processor.validate_validator_function(code_str=tool_data["code_snippet"])
            if "error" in validator_validation or not validator_validation.get("is_valid", False):
                log.error(f"Validator tool validation failed: {validator_validation.get('error', 'Unknown validation error')}")
                return {
                    "message": validator_validation.get('error', 'Validator tool validation failed'),
                    "tool_id": "",
                    "tool_name": tool_data['tool_name'],
                    "model_name": tool_data.get('model_name', ''),
                    "created_by": tool_data.get('created_by', ''),
                    "is_created": False
                }
            log.info(f"[SUCCESS] Validator tool validation passed for tool: {tool_data['tool_name']}")
        
        if not tool_data.get("tool_id"):
            if is_validator:
                tool_data["tool_id"] = f"_validator_{str(uuid.uuid4())}"
            else:
                tool_data["tool_id"] = str(uuid.uuid4())
            update_session_context(tool_id=tool_data.get("tool_id", None))

        if not tool_data.get("tag_ids"):
            general_tag = await self.tag_service.get_tag(tag_name="General")
            tool_data['tag_ids'] = [general_tag['tag_id']] if general_tag else []

        
        llm = await self.model_service.get_llm_model(model_name=tool_data["model_name"], temperature=0.0)
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

        # Set the is_validator flag in the tool data
        tool_data["is_validator"] = is_validator
        
        # Set the is_public flag in the tool data
        tool_data["is_public"] = is_public if is_public is not None else False

        now = datetime.now(timezone.utc).replace(tzinfo=None)
        tool_data['created_on'] = now
        tool_data['updated_on'] = now

        success = await self.tool_repo.save_tool_record(tool_data)

        if success:
            tags_status = await self.tag_service.assign_tags_to_tool(
                tag_ids=tool_data['tag_ids'], tool_id=tool_data['tool_id']
            )
            
            # Create .py file for the tool using tool_name
            file_creation_result = await self.tool_file_manager.create_tool_file(tool_data)
            if file_creation_result.get("success"):
                log.info(f"Tool file created at: {file_creation_result.get('file_path')}")
            else:
                log.warning(f"Failed to create tool file: {file_creation_result.get('message')}")
            
            # Extract and save access keys from @resource_access decorators
            if self.tool_access_key_mapping_repo:
                access_keys = self.tool_code_processor.extract_access_keys_from_code(tool_data["code_snippet"])
                if access_keys:
                    await self.tool_access_key_mapping_repo.save_tool_access_keys(
                        tool_id=tool_data['tool_id'],
                        tool_name=tool_data['tool_name'],
                        access_keys=access_keys,
                        department_name=tool_data.get('department_name')
                    )
                    log.info(f"Saved access keys {access_keys} for tool '{tool_data['tool_name']}'")
            
            # Handle department sharing if specified (skip if is_public=true as it's redundant)
            sharing_status = None
            if is_public and shared_with_departments:
                log.info(f"Tool '{tool_data['tool_name']}' is public, skipping shared_with_departments as public tools are visible to all departments")
                sharing_status = {"message": "Tool is public, shared_with_departments ignored"}
            elif shared_with_departments and self.tool_sharing_repo:
                try:
                    # Validate that all target departments exist
                    invalid_departments = []
                    valid_departments = []
                    if self.department_repo:
                        for dept_name in shared_with_departments:
                            dept = await self.department_repo.get_department_by_name(dept_name)
                            if dept:
                                valid_departments.append(dept_name)
                            else:
                                invalid_departments.append(dept_name)
                    else:
                        # If no department_repo available, proceed with all departments
                        valid_departments = shared_with_departments
                    
                    if invalid_departments:
                        log.warning(f"Invalid department names provided for sharing: {invalid_departments}")
                    
                    if valid_departments:
                        sharing_result = await self.tool_sharing_repo.share_tool_with_multiple_departments(
                            tool_id=tool_data['tool_id'],
                            tool_name=tool_data['tool_name'],
                            source_department=tool_data.get('department_name', ''),
                            target_departments=valid_departments,
                            shared_by=tool_data.get('created_by', '')
                        )
                        sharing_status = {
                            "shared_with": [f["department"] for f in sharing_result.get("failures", []) if False] or valid_departments[:sharing_result.get("success_count", 0)],
                            "failed": sharing_result.get("failures", []),
                            "invalid_departments": invalid_departments
                        }
                        log.info(f"Tool '{tool_data['tool_name']}' shared with departments: {sharing_result.get('shared_departments', [])}")
                    else:
                        sharing_status = {"error": "No valid departments to share with", "invalid_departments": invalid_departments}
                except Exception as share_error:
                    log.warning(f"Failed to share tool with departments: {share_error}")
                    sharing_status = {"error": str(share_error)}
            
            log.info(f"Successfully onboarded tool with tool_id: {tool_data['tool_id']}")
            result = {
                "message": f"Successfully onboarded tool: {tool_data['tool_name']}",
                "tool_id": tool_data['tool_id'],
                "tool_name": tool_data['tool_name'],
                "model_name": tool_data.get('model_name', ''),
                "tags_status": tags_status,
                "created_by": tool_data.get('created_by', ''),
                "is_created": True,
                "is_public": tool_data.get('is_public', False),
                "file_created": file_creation_result.get("success", False),
                "file_path": file_creation_result.get("file_path", "")
            }
            if sharing_status:
                result["sharing_status"] = sharing_status
            return result
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



    async def create_tool_for_message_queue(self, tool_data: Dict[str, Any], force_add, is_validator: Optional[bool] = False, is_public: Optional[bool] = False, shared_with_departments: Optional[List[str]] = None) -> Dict[str, Any]:
        """
        Creates a new tool, for message queue workflow whose task will be simply to :
        send message to the desired topic, 
        including validation, docstring generation, and saving to the database.

        Args:
            tool_data (dict): A dictionary containing the tool data to save.
            force_add (bool): Force add flag for bypassing certain validations.
            is_validator (bool, optional): Whether this is a validator tool.
            is_public (bool, optional): Whether the tool is public (accessible to all departments).
            shared_with_departments (List[str], optional): List of department names to share the tool with.

        Returns:
            dict: Status of the operation, including success message or error details.
        """
        
        log.info("======Executing message queue workflow======")

        # Create regular tool (with sharing parameters)
        regular_msg = await self.create_tool(tool_data, force_add, is_validator, is_public, shared_with_departments)

        #Fetch tool id and update for message queue version
        t_id=regular_msg['tool_id']
        tool_data["tool_id"] = t_id+'_message_queue'

        validation_status = await self.tool_code_processor.validate_and_extract_tool_name(code_str=tool_data.get("code_snippet", ""))
        if "error" in validation_status:
            log.error(f"Tool creation failed: {validation_status['error']}")
            return {
                "message": validation_status["error"],
                "tool_id": "",
                "is_created": False
            }

        tool_data["tool_name"] = validation_status["function_name"]

        

        #New tool name for message queue version
        tool_data["tool_name"] += '_message_queue'

        log.info("======modified tool name for message queue======")
        log.info(f"Modified tool name: {tool_data['tool_name']}")
        
        update_session_context(tool_name=tool_data["tool_name"],tool_id=tool_data.get("tool_id", None))


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
        if not force_add:
            initial_state = {
                    "code": tool_data["code_snippet"],
                    "model": tool_data["model_name"],
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
                    "feedback_case7": None,
                    "validation_case8": None,
                    "feedback_case8": None
                }
            workflow_result = await graph.ainvoke(input=initial_state)
            w_cases=["validation_case3","validation_case5","validation_case6","validation_case7"]
            e_cases=["validation_case8","validation_case1","validation_case4"]
            warnings={}
            errors={}
            log.info(f"Tool validation results: {workflow_result}")
            for i in w_cases:
                if not workflow_result.get(i):
                    feedback_key = i.replace("validation_", "feedback_")
                    if workflow_result.get(feedback_key):
                        warnings[i] = workflow_result.get(feedback_key)
            for j in e_cases:
                if not workflow_result.get(j):
                    feedback_key = j.replace("validation_", "feedback_")
                    errors[j] = workflow_result.get(feedback_key)
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
                        "error_on_screen": False,
                        "warnings":True,
                        "is_created": False
                    }
        
        # [INFO] Validator-specific validation for validator tools
        if is_validator:
            validator_validation = await self.tool_code_processor.validate_validator_function(code_str=tool_data["code_snippet"])
            if "error" in validator_validation or not validator_validation.get("is_valid", False):
                log.error(f"Validator tool validation failed: {validator_validation.get('error', 'Unknown validation error')}")
                return {
                    "message": validator_validation.get('error', 'Validator tool validation failed'),
                    "tool_id": "",
                    "tool_name": tool_data['tool_name'],
                    "model_name": tool_data.get('model_name', ''),
                    "created_by": tool_data.get('created_by', ''),
                    "is_created": False
                }
            log.info(f"[SUCCESS] Validator tool validation passed for tool: {tool_data['tool_name']}")
        
        
        if not tool_data.get("tag_ids"):
            general_tag = await self.tag_service.get_tag(tag_name="General")
            tool_data['tag_ids'] = [general_tag['tag_id']] if general_tag else []


       
        

        llm = await self.model_service.get_llm_model(model_name=tool_data["model_name"], temperature=0.0)
        
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
        log.info("===========PRINTING CODE SNIPPET BEFORE MODIFYING FOR MESSAGE QUEUE===============")
        log.info(tool_data["code_snippet"])

        # Modify tool to only call message queue
        tool_data["code_snippet"] = await self.tool_code_processor.modify_tool_for_kafka(tool_data["code_snippet"])
        log.info("=======Modified Tool Code Snippet for Message Queue======")
        log.info(tool_data["code_snippet"])

        # Set the is_validator flag in the tool data
        tool_data["is_validator"] = is_validator
        
        # Set the is_public flag in the tool data
        tool_data["is_public"] = is_public if is_public is not None else False

        now = datetime.now(timezone.utc).replace(tzinfo=None)
        tool_data['created_on'] = now
        tool_data['updated_on'] = now

        success = await self.tool_repo.save_tool_record(tool_data)

        if success:
            tags_status = await self.tag_service.assign_tags_to_tool(
                tag_ids=tool_data['tag_ids'], tool_id=tool_data['tool_id']
            )
            
            # Create .py file for the tool using tool_name
            file_creation_result = await self.tool_file_manager.create_tool_file(tool_data)
            if file_creation_result.get("success"):
                log.info(f"Tool file created at: {file_creation_result.get('file_path')}")
            else:
                log.warning(f"Failed to create tool file: {file_creation_result.get('message')}")
            
            # Extract and save access keys from @resource_access decorators
            if self.tool_access_key_mapping_repo:
                access_keys = self.tool_code_processor.extract_access_keys_from_code(tool_data["code_snippet"])
                if access_keys:
                    await self.tool_access_key_mapping_repo.save_tool_access_keys(
                        tool_id=tool_data['tool_id'],
                        tool_name=tool_data['tool_name'],
                        access_keys=access_keys,
                        department_name=tool_data.get('department_name')
                    )
                    log.info(f"Saved access keys {access_keys} for tool '{tool_data['tool_name']}'")
            
            # Handle department sharing if specified (skip if is_public=true as it's redundant)
            sharing_status = None
            if is_public and shared_with_departments:
                log.info(f"Tool '{tool_data['tool_name']}' is public, skipping shared_with_departments as public tools are visible to all departments")
                sharing_status = {"message": "Tool is public, shared_with_departments ignored"}
            elif shared_with_departments and self.tool_sharing_repo:
                try:
                    # Validate that all target departments exist
                    invalid_departments = []
                    valid_departments = []
                    if self.department_repo:
                        for dept_name in shared_with_departments:
                            dept = await self.department_repo.get_department_by_name(dept_name)
                            if dept:
                                valid_departments.append(dept_name)
                            else:
                                invalid_departments.append(dept_name)
                    else:
                        # If no department_repo available, proceed with all departments
                        valid_departments = shared_with_departments
                    
                    if invalid_departments:
                        log.warning(f"Invalid department names provided for sharing: {invalid_departments}")
                    
                    if valid_departments:
                        sharing_result = await self.tool_sharing_repo.share_tool_with_multiple_departments(
                            tool_id=tool_data['tool_id'],
                            tool_name=tool_data['tool_name'],
                            source_department=tool_data.get('department_name', ''),
                            target_departments=valid_departments,
                            shared_by=tool_data.get('created_by', '')
                        )
                        sharing_status = {
                            "shared_with": [f["department"] for f in sharing_result.get("failures", []) if False] or valid_departments[:sharing_result.get("success_count", 0)],
                            "failed": sharing_result.get("failures", []),
                            "invalid_departments": invalid_departments
                        }
                        log.info(f"Tool '{tool_data['tool_name']}' shared with departments: {sharing_result.get('shared_departments', [])}")
                    else:
                        sharing_status = {"error": "No valid departments to share with", "invalid_departments": invalid_departments}
                except Exception as share_error:
                    log.warning(f"Failed to share tool with departments: {share_error}")
                    sharing_status = {"error": str(share_error)}
            
            log.info(f"Successfully onboarded tool with tool_id: {tool_data['tool_id']}")
            result = {
                "message": f"Successfully onboarded tool: {tool_data['tool_name']}",
                "tool_id": tool_data['tool_id'],
                "tool_name": tool_data['tool_name'],
                "model_name": tool_data.get('model_name', ''),
                "tags_status": tags_status,
                "created_by": tool_data.get('created_by', ''),
                "is_created": True,
                "is_public": tool_data.get('is_public', False),
                "file_created": file_creation_result.get("success", False),
                "file_path": file_creation_result.get("file_path", "")
            }
            if sharing_status:
                result["sharing_status"] = sharing_status
            return result
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

    async def get_all_tools(self, department_name: str = None, include_shared: bool = True) -> List[Dict[str, Any]]:
        """
        Retrieves all regular tools (excludes validator tools) with their associated tags and sharing info.
        When department_name is specified, also includes shared and public tools.

        Args:
            department_name (str, optional): Filter by department. If provided and include_shared=True,
                                             includes tools shared with this department and public tools.
            include_shared (bool): Whether to include shared/public tools. Defaults to True.

        Returns:
            list: A list of regular tools, represented as dictionaries with tags and shared_with_departments.
        """
        # If department specified and sharing enabled, use the enhanced method
        if department_name and include_shared and self.tool_sharing_repo:
            # Get IDs of tools shared with this department
            shared_tool_ids = await self.tool_sharing_repo.get_tools_shared_with_department(department_name)
            tool_records = await self.tool_repo.get_all_tool_records_with_shared(
                department_name=department_name,
                shared_tool_ids=shared_tool_ids,
                include_public=True
            )
        else:
            tool_records = await self.tool_repo.get_all_tool_records(department_name=department_name)
        
        tool_id_to_tags = await self.tag_service.get_tool_id_to_tags_dict()

        # Filter out validator tools and add sharing info
        regular_tools = []
        for tool in tool_records:
            # Skip validator tools (check both flag and ID prefix)
            if tool.get('is_validator', False) or tool.get('tool_id', '').startswith('_validator') or tool.get('tool_id','').endswith('_message_queue'):
                continue
            tool['tags'] = tool_id_to_tags.get(tool['tool_id'], [])
            # Add shared departments information
            if self.tool_sharing_repo:
                shared_info = await self.tool_sharing_repo.get_shared_departments_for_tool(tool['tool_id'])
                tool['shared_with_departments'] = [info['target_department'] for info in shared_info]
            else:
                tool['shared_with_departments'] = []
            regular_tools.append(tool)
        
        log.info(f"Retrieved {len(regular_tools)} regular tools (excluding validators)")
        return regular_tools

    async def get_tools_by_tags(self, tag_ids: Optional[Union[List[str], str]] = None, tag_names: Optional[Union[List[str], str]] = None, department_name:str = None) -> List[Dict[str, Any]]:
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
        all_tool_records = await self.tool_repo.get_all_tool_records(department_name=department_name)
        filtered_tools = []
        for tool in all_tool_records:
            # Skip validator tools
            if tool.get('is_validator', False) or tool.get('tool_id', '').startswith('_validator'):
                continue
                
            tool_tag_ids = await self.tag_service.get_tags_by_tool(tool['tool_id'])
            if any(t['tag_id'] in tag_ids for t in tool_tag_ids):
                filtered_tools.append(tool)

        # Attach full tag details and sharing info
        tool_id_to_tags = await self.tag_service.get_tool_id_to_tags_dict()
        for tool in filtered_tools:
            tool['tags'] = tool_id_to_tags.get(tool['tool_id'], [])
            # Add shared departments information
            if self.tool_sharing_repo:
                shared_info = await self.tool_sharing_repo.get_shared_departments_for_tool(tool['tool_id'])
                tool['shared_with_departments'] = [info['target_department'] for info in shared_info]
            else:
                tool['shared_with_departments'] = []
        return filtered_tools

    async def get_tool(self, tool_id: Optional[str] = None, tool_name: Optional[str] = None, department_name: str = None) -> List[Dict[str, Any]]:
        """
        Retrieves a single tool record by ID or name, with associated tags and sharing information.
        Includes tools that are: owned by department, public, OR shared with the department.

        Args:
            tool_id (str, optional): Tool ID. Can be used to retrieve both MCP tools (if prefixed with "mcp_") and normal Python function tools.
            tool_name (str, optional): Tool name. Should only be used to retrieve normal Python function tools.
            department_name (str, optional): The department name to filter by.

        Returns:
            List[Dict[str, Any]]: A list of dictionaries representing the retrieved tool(s), each with associated tags and shared_with_departments. Returns an empty list if no tool is found.
        """
        if tool_id and tool_id.startswith("mcp_"):
            return await self.mcp_tool_service.get_mcp_tool(tool_id=tool_id, department_name= department_name)

        # First try to get tool (own department or public)
        tool_records = await self.tool_repo.get_tool_record(tool_id=tool_id, tool_name=tool_name, department_name=department_name)

        # If not found and department specified, check if tool is shared with this department
        if not tool_records and department_name and self.tool_sharing_repo and tool_id:
            # Check if this tool is shared with the user's department
            is_shared = await self.tool_sharing_repo.is_tool_shared_with_department(tool_id, department_name)
            if is_shared:
                # Get the tool without department filter
                tool_records = await self.tool_repo.get_tool_record(tool_id=tool_id, tool_name=tool_name)

        if not tool_records:
            log.info(f"No tool found with ID: {tool_id} or Name: {tool_name}.")
            return []

        for tool_record in tool_records:
            tool_record['tags'] = await self.tag_service.get_tags_by_tool(tool_record['tool_id'])
            # Add shared departments information
            if self.tool_sharing_repo:
                shared_info = await self.tool_sharing_repo.get_shared_departments_for_tool(tool_record['tool_id'])
                tool_record['shared_with_departments'] = [info['target_department'] for info in shared_info]
            else:
                tool_record['shared_with_departments'] = []
            
        log.info(f"Retrieved tool with ID: {tool_records[0]['tool_id']} and Name: {tool_records[0]['tool_name']}.")
        return tool_records
    
    async def get_tool_by_id(self, tool_id: str) -> Optional[Dict[str, Any]]:
        """
        Retrieves a single tool record by ID, with associated tags.
        This is a convenience method that returns a single tool instead of a list.

        Args:
            tool_id (str): Tool ID. Can be used to retrieve both MCP tools (if prefixed with "mcp_") and normal Python function tools.

        Returns:
            Optional[Dict[str, Any]]: A dictionary representing the retrieved tool with associated tags, or None if not found.
        """
        tool_records = await self.get_tool(tool_id=tool_id)
        
        if not tool_records:
            return None
        
        # Return the first tool record (should be only one for a specific ID)
        return tool_records[0]

    async def get_tools_by_search_or_page(self, search_value: str = '', limit: int = 20, page: int = 1, tag_names: Optional[List[str]] = None, created_by:str = None, department_name: str = None) -> Dict[str, Any]:
        """
        Retrieves regular tools (excludes validator tools) with pagination and search filtering, including associated tags.
        Includes shared and public tools when department_name is specified.

        Args:
            search_value (str, optional): Tool name to filter by.
            limit (int, optional): Number of results per page.
            page (int, optional): Page number for pagination.

        Returns:
            dict: A dictionary containing the total count of tools and the paginated tool details.
        """
        # Get shared tool IDs if department specified
        shared_tool_ids = []
        if department_name and self.tool_sharing_repo:
            shared_tool_ids = await self.tool_sharing_repo.get_tools_shared_with_department(department_name)
        
        total_count = await self.tool_repo.get_total_tool_count(search_value, created_by, department_name=department_name, shared_tool_ids=shared_tool_ids)

        if tag_names:
            tag_names = set(tag_names)
            tool_records = await self.tool_repo.get_tools_by_search_or_page_records(search_value, total_count, 1, created_by, department_name, shared_tool_ids=shared_tool_ids)
        else:
            tool_records = await self.tool_repo.get_tools_by_search_or_page_records(search_value, limit, page, created_by, department_name, shared_tool_ids=shared_tool_ids)

        tool_id_to_tags = await self.tag_service.get_tool_id_to_tags_dict()
        filtered_tools = []

        validator_count = 0
        for tool in tool_records:
            tool_id = tool.get('tool_id', '')
            is_validator_flag = tool.get('is_validator', False)
            starts_with_validator = tool_id.startswith('_validator')
            
            # Skip validator tools
            if is_validator_flag or starts_with_validator:
                validator_count += 1
                log.info(f"Filtering out validator tool: {tool_id} (is_validator={is_validator_flag}, starts_with_validator={starts_with_validator})")
                continue
                
            log.debug(f"Including regular tool: {tool_id}")
            tool['tags'] = tool_id_to_tags.get(tool['tool_id'], [])
            # Add shared departments information
            if self.tool_sharing_repo:
                shared_info = await self.tool_sharing_repo.get_shared_departments_for_tool(tool['tool_id'])
                tool['shared_with_departments'] = [info['target_department'] for info in shared_info]
            else:
                tool['shared_with_departments'] = []
            if tag_names:
                for tag in tool['tags']:
                    if tag['tag_name'] in tag_names:
                        filtered_tools.append(tool)
                        break
            else:
                filtered_tools.append(tool)
        
        log.info(f"Filtered out {validator_count} validator tools, kept {len(filtered_tools)} regular tools")

        # Recalculate total count for non-validator tools (after filtering)
        total_count = len(filtered_tools)
        log.info(f"After filtering validators: {total_count} tools found (originally {len(tool_records)})")
        
        # Apply pagination to filtered results
        offset = limit * max(0, page - 1)
        paginated_tools = filtered_tools[offset : offset + limit]
        log.info(f"Page {page} (size {limit}): returning {len(paginated_tools)} tools (offset {offset})")

        return {
            "total_count": total_count,
            "details": paginated_tools
        }

    async def get_unused_tools(self, threshold_days: int = 0, department_name: str = None) -> List[Dict[str, Any]]:
        """
        Retrieves all tools that haven't been used for the specified number of days.

        Args:
            threshold_days (int): Number of days to consider a tool as unused. Default is 15.
            department_name (str, optional): Filter by department name.

        Returns:
            List[Dict[str, Any]]: A list of unused tools with their details.
        """
        try:
            # Build query with optional department_name filter
            query = f"""
                SELECT tool_id, tool_name, tool_description, created_by, created_on, last_used
                FROM {TableNames.TOOL.value} 
                WHERE (last_used IS NULL OR last_used < (NOW() - INTERVAL '1 day' * $1))
            """
            params = [threshold_days]
            if department_name:
                query += " AND department_name = $2"
                params.append(department_name)
            query += " ORDER BY last_used ASC NULLS FIRST"

            result = await self.tool_repo.pool.fetch(query, *params)

            tools = []
            # Collect all unique created_by email addresses
            email_set = set(row.get('created_by') for row in result if row.get('created_by'))

            # Batch fetch usernames for all emails
            if email_set:
                email_list = list(email_set)
                async with self.tool_repo.login_pool.acquire() as conn:
                    user_rows = await conn.fetch(
                        f"SELECT mail_id, user_name FROM {TableNames.LOGIN_CREDENTIAL.value} WHERE mail_id = ANY($1)", email_list
                    )
                email_to_username = {row['mail_id']: row['user_name'] for row in user_rows}
            else:
                email_to_username = {}

            for row in result:
                tool_dict = dict(row)
                email = tool_dict.get('created_by')
                if email:
                    username = email_to_username.get(email)
                    if username:
                        tool_dict['created_by'] = username
                    elif '@' in email:
                        tool_dict['created_by'] = email.split('@')[0]
                tools.append(tool_dict)

            return tools

        except Exception as e:
            log.error(f"Error retrieving unused tools: {str(e)}")
            raise Exception(f"Failed to retrieve unused tools: {str(e)}")

    # --- Validator Tool Retrieval Operations ---

    async def get_all_validators(self, department_name: str = None) -> List[Dict[str, Any]]:
        """
        Retrieves all validator tools with their associated tags.

        Returns:
            list: A list of validator tools, represented as dictionaries.
        """
        tool_records = await self.tool_repo.get_all_tool_records(department_name=department_name)
        tool_id_to_tags = await self.tag_service.get_tool_id_to_tags_dict()

        # Filter for validator tools only
        validator_tools = []
        for tool in tool_records:
            if tool.get('is_validator', False) or tool.get('tool_id', '').startswith('_validator'):
                tool['tags'] = tool_id_to_tags.get(tool['tool_id'], [])
                validator_tools.append(tool)
        
        log.info(f"Retrieved {len(validator_tools)} validator tools")
        return validator_tools

    async def get_validators_by_search_or_page(self, search_value: str = '', limit: int = 20, page: int = 1, tag_names: Optional[List[str]] = None, created_by: Optional[str] = None, department_name:str = None) -> Dict[str, Any]:
        """
        Retrieves validator tools with pagination and search filtering, including associated tags.

        Args:
            search_value (str, optional): Tool name to filter by.
            limit (int, optional): Number of results per page.
            page (int, optional): Page number for pagination.
            tag_names (List[str], optional): Filter by tag names.
            created_by (str, optional): Filter by creator's email ID.

        Returns:
            dict: A dictionary containing the total count of validator tools and the paginated tool details.
        """
        # Get all validator tools first
        all_validators = await self.get_all_validators(department_name=department_name)
        
        # Apply search filter
        filtered_validators = []
        for tool in all_validators:
            # Apply search filter
            if search_value and search_value.lower() not in tool.get('tool_name', '').lower():
                continue
            
            # Apply creator filter
            if created_by and tool.get('created_by') != created_by:
                continue
            
            # Apply tag filter
            if tag_names:
                tool_tag_names = {tag.get('tag_name') for tag in tool.get('tags', [])}
                if not any(tag_name in tool_tag_names for tag_name in tag_names):
                    continue
            
            filtered_validators.append(tool)

        total_count = len(filtered_validators)
        
        # Apply pagination
        offset = limit * max(0, page - 1)
        paginated_validators = filtered_validators[offset : offset + limit]

        log.info(f"Retrieved {len(paginated_validators)} validator tools (page {page}, total: {total_count})")
        return {
            "total_count": total_count,
            "details": paginated_validators
        }

    async def get_all_tools_and_validators_by_search_or_page(self, search_value: str = '', limit: int = 20, page: int = 1, tag_names: Optional[List[str]] = None, created_by: Optional[str] = None, show_tools: bool = True, show_validators: bool = True, department_name:str = None) -> Dict[str, Any]:
        """
        Retrieves both regular tools AND validator tools combined with pagination and search filtering, including associated tags.

        Args:
            search_value (str, optional): Tool name to filter by.
            limit (int, optional): Number of results per page.
            page (int, optional): Page number for pagination.
            tag_names (List[str], optional): Filter by tag names.
            created_by (str, optional): Filter by creator's email ID.
            show_tools (bool, optional): Include regular tools in results. Default True.
            show_validators (bool, optional): Include validators in results. Default True.

        Returns:
            dict: A dictionary containing the total count of tools (regular + validators) and the paginated tool details.
        """
        # Get shared tool IDs if department specified
        shared_tool_ids = []
        if department_name and self.tool_sharing_repo:
            shared_tool_ids = await self.tool_sharing_repo.get_tools_shared_with_department(department_name)
        
        # Get all tools (regular and validators) first
        total_count = await self.tool_repo.get_total_tool_count(search_value, created_by, department_name=department_name, shared_tool_ids=shared_tool_ids)
        
        # Get ALL matching records first - we'll filter in Python
        tool_records = await self.tool_repo.get_tools_by_search_or_page_records(search_value, total_count, 1, created_by, department_name, shared_tool_ids=shared_tool_ids)
        
        if tag_names:
            tag_names = set(tag_names)

        tool_id_to_tags = await self.tag_service.get_tool_id_to_tags_dict()
        filtered_tools = []

        for tool in tool_records:
            tool_id = tool.get('tool_id', '')
            
            # Apply tool type filter (tools vs validators)
            # If both are unchecked, show all items
            if show_tools or show_validators:
                is_validator = tool.get('is_validator', False) or tool_id.startswith('_validator')
                if is_validator and not show_validators:
                    continue
                if not is_validator and not show_tools:
                    continue
            
            # Apply tag filter
            if tag_names:
                tool_tags = tool_id_to_tags.get(tool_id, [])
                tool_tag_names = {tag.get('tag_name') for tag in tool_tags}
                if not any(tag_name in tool_tag_names for tag_name in tag_names):
                    continue
            
            # Include tags in tool data
            tool_tags = tool_id_to_tags.get(tool_id, [])
            tool['tags'] = tool_tags
            
            # Add shared departments information
            if self.tool_sharing_repo:
                shared_info = await self.tool_sharing_repo.get_shared_departments_for_tool(tool_id)
                tool['shared_with_departments'] = [info['target_department'] for info in shared_info]
            else:
                tool['shared_with_departments'] = []
            
            filtered_tools.append(tool)

        # Apply pagination to filtered results
        total_filtered_count = len(filtered_tools)
        offset = limit * max(0, page - 1)
        paginated_tools = filtered_tools[offset : offset + limit]

        log.info(f"Retrieved {len(paginated_tools)} tools (regular + validators) (page {page}, total: {total_filtered_count})")
        return {
            "total_count": total_filtered_count,
            "details": paginated_tools
        }

    # --- Tool Updation Operations ---

    async def update_tool(self, tool_id: str, model_name: str, force_add, code_snippet: str = "", tool_description: str = "", updated_tag_id_list: Optional[Union[List[str], str]] = None, user_id: Optional[str] = None, is_admin: bool = False, is_validator: bool = False, is_public: Optional[bool] = None, shared_with_departments: Optional[List[str]] = None) -> Dict[str, Any]:
        """
        Updates an existing tool record, including code validation, docstring regeneration,
        permission checks, dependency checks, and tag updates.

        Args:
            tool_id (str): The ID of the tool to update.
            model_name (str): The model name to use for docstring generation.
            force_add (bool): Force add flag for bypassing certain validations.
            code_snippet (str, optional): New code snippet for the tool.
            tool_description (str, optional): New description for the tool.
            updated_tag_id_list (Union[List, str], optional): List of new tag IDs for the tool.
            user_id (str, optional): The ID of the user performing the update.
            is_admin (bool, optional): Whether the user has admin privileges.
            is_validator (bool, optional): Whether the tool is a validator tool.
            is_public (bool, optional): Whether the tool should be public (accessible to all departments).
            shared_with_departments (List[str], optional): List of department names to share the tool with.

        Returns:
            dict: Status of the update operation.
        """
        tool_data = await self.tool_repo.get_tool_record(tool_id=tool_id, message_queue_implementation=False)
        if not tool_data:
            log.error(f"Error: Tool not found with ID: {tool_id}")
            return {
                "message": f"Error: Tool not found with ID: {tool_id}",
                "details": [],
                "is_update": False
            }
        tool_data = tool_data[0]

        if not is_admin and tool_data["created_by"] != user_id:
            err = f"Permission denied: Only the admin or the tool's creator can perform this action for Tool: {tool_data['tool_name']}."
            log.error(err)
            return {
                "message": err,
                "details": [],
                "is_update": False
            }

        # Check if any field is being updated (including is_validator flag)
        current_is_validator = tool_data.get('is_validator', False) or tool_data.get('tool_id', '').startswith('_validator')
        validator_flag_changed = is_validator != current_is_validator
        
        # Check if is_public is being changed
        current_is_public = tool_data.get('is_public', False)
        is_public_changed = is_public is not None and is_public != current_is_public
        
        # Check if sharing is being updated
        sharing_changed = shared_with_departments is not None
        
        log.info(f"Validator status check: current={current_is_validator}, requested={is_validator}, changed={validator_flag_changed}")
        validator_flag_value = tool_data.get('is_validator', 'not_present') if isinstance(tool_data, dict) else 'invalid_data'
        log.info(f"Tool ID: {tool_data.get('tool_id', '') if isinstance(tool_data, dict) else 'unknown'}, has_is_validator_flag: {validator_flag_value}")
        

        tag_update_status = None
        if updated_tag_id_list:
            await self.tag_service.clear_tags(tool_id=tool_id) # Clear existing tags
            tag_update_status = await self.tag_service.assign_tags_to_tool(tag_ids=updated_tag_id_list, tool_id=tool_id)
            log.info("Successfully updated tags for the tool.")

        # Handle is_public and sharing updates even if no other fields change
        sharing_update_status = None
        
        # If setting is_public=true, sharing is redundant - clear any existing sharing
        if is_public_changed and is_public and self.tool_sharing_repo:
            if shared_with_departments:
                log.info(f"Tool '{tool_data['tool_name']}' is being set to public, ignoring shared_with_departments")
                sharing_update_status = {"message": "Tool is public, shared_with_departments ignored"}
                sharing_changed = False  # Skip further sharing processing
        
        # VALIDATION: Check if unsharing tool would break any shared agents
        if is_public_changed or sharing_changed:
            # Get agents that use this tool
            agents_using_tool = await self.tool_agent_mapping_repo.get_tool_agent_mappings_record(tool_id=tool_id)
            
            if agents_using_tool:
                blocking_agents = []
                
                for mapping in agents_using_tool:
                    agent_id = mapping.get('agentic_application_id')
                    agent_records = await self.agent_repo.get_agent_record(agentic_application_id=agent_id)
                    if not agent_records:
                        continue
                    agent = agent_records[0]
                    agent_name = agent.get('agentic_application_name', agent_id)
                    agent_is_public = agent.get('is_public', False)
                    
                    # Case 1: Tool is being made non-public
                    if is_public_changed and not is_public:
                        agent_department = agent.get('department_name', '')
                        tool_department = tool_data.get('department_name', '')
                        
                        # Block if agent is from a different department (it relies on tool being public)
                        if agent_department and tool_department and agent_department != tool_department:
                            blocking_agents.append({
                                "agent_name": agent_name,
                                "agent_id": agent_id,
                                "agent_department": agent_department,
                                "reason": f"Agent belongs to department '{agent_department}' and accesses this tool via public visibility. Making the tool non-public will revoke access for this agent."
                            })
                            continue
                        
                        # Also block if agent is public (it needs the tool to be accessible to all)
                        if agent_is_public:
                            blocking_agents.append({
                                "agent_name": agent_name,
                                "agent_id": agent_id,
                                "agent_department": agent_department,
                                "reason": "Agent is public and requires this tool to be accessible"
                            })
                            continue
                    
                    # Case 2: Check if tool is being unshared from departments where agent is shared
                    if sharing_changed and self.tool_sharing_repo:
                        # Get current tool sharing
                        current_tool_shared_info = await self.tool_sharing_repo.get_shared_departments_for_tool(tool_id)
                        current_tool_shared_set = set(d['target_department'] for d in current_tool_shared_info)
                        
                        # Get new tool sharing (after update)
                        valid_new_depts = []
                        if shared_with_departments and self.department_repo:
                            for dept_name in shared_with_departments:
                                dept = await self.department_repo.get_department_by_name(dept_name)
                                if dept:
                                    valid_new_depts.append(dept_name)
                        elif shared_with_departments:
                            valid_new_depts = shared_with_departments
                        new_tool_shared_set = set(valid_new_depts) if valid_new_depts else set()
                        
                        # Departments being unshared from
                        depts_being_unshared = current_tool_shared_set - new_tool_shared_set
                        
                        if depts_being_unshared:
                            # Get agent's sharing info
                            if self.tool_sharing_repo and hasattr(self, 'agent_repo'):
                                # Check if agent is shared with any of the departments being unshared
                                agent_shared_info = []
                                try:
                                    # Get agent sharing repo from tool_service context
                                    from src.database.repositories import AgentDepartmentSharingRepository
                                    agent_sharing_query = f"""
                                        SELECT target_department FROM agent_department_sharing 
                                        WHERE agentic_application_id = $1
                                    """
                                    async with self.tool_repo.pool.acquire() as conn:
                                        agent_shared_info = await conn.fetch(agent_sharing_query, agent_id)
                                except Exception as e:
                                    log.warning(f"Could not check agent sharing: {e}")
                                
                                agent_shared_depts = set(r['target_department'] for r in agent_shared_info)
                                
                                # Check if agent is shared with departments we're trying to unshare tool from
                                conflicting_depts = depts_being_unshared & agent_shared_depts
                                if conflicting_depts:
                                    blocking_agents.append({
                                        "agent_name": agent_name,
                                        "agent_id": agent_id,
                                        "reason": f"Agent is shared with departments {list(conflicting_depts)} and requires this tool"
                                    })
                
                if blocking_agents:
                    agent_names = [a['agent_name'] for a in blocking_agents]
                    log.error(f"Cannot update tool visibility for '{tool_data['tool_name']}': Used by agents in other departments: {agent_names}")
                    
                    # Build a specific, descriptive error message
                    agent_detail_msgs = []
                    for ba in blocking_agents[:5]:
                        dept_info = f" (Department: {ba['agent_department']})" if ba.get('agent_department') else ""
                        agent_detail_msgs.append(f"'{ba['agent_name']}'{dept_info}")
                    agents_summary = ", ".join(agent_detail_msgs)
                    if len(blocking_agents) > 5:
                        agents_summary += f" and {len(blocking_agents) - 5} more"
                    
                    return {
                        "message": f"Cannot make tool '{tool_data['tool_name']}' non-public: It is currently used by {len(blocking_agents)} agent(s) in other departments that would lose access: {agents_summary}. Please remove this tool from those agents first, or keep the tool public.",
                        "details": blocking_agents,
                        "is_update": False
                    }
        
        if is_public_changed or sharing_changed:
            # Update is_public in tool_data if changed
            if is_public_changed:
                tool_data["is_public"] = is_public
                await self.tool_repo.update_tool_record({"is_public": is_public}, tool_id)
                log.info(f"Updated is_public to {is_public} for tool: {tool_data['tool_name']}")
            
            # Handle sharing update (with department validation)
            if sharing_changed and self.tool_sharing_repo:
                try:
                    # Validate new departments exist
                    valid_new_depts = []
                    invalid_departments = []
                    if shared_with_departments and self.department_repo:
                        for dept_name in shared_with_departments:
                            dept = await self.department_repo.get_department_by_name(dept_name)
                            if dept:
                                valid_new_depts.append(dept_name)
                            else:
                                invalid_departments.append(dept_name)
                        if invalid_departments:
                            log.warning(f"Invalid department names provided for sharing: {invalid_departments}")
                    elif shared_with_departments:
                        valid_new_depts = shared_with_departments
                    
                    # Get current sharing state
                    current_shared_info = await self.tool_sharing_repo.get_shared_departments_for_tool(tool_id)
                    current_shared_set = set(d['target_department'] for d in current_shared_info)
                    new_shared_set = set(valid_new_depts) if valid_new_depts else set()
                    
                    # Departments to add (only valid ones)
                    depts_to_add = new_shared_set - current_shared_set
                    # Departments to remove
                    depts_to_remove = current_shared_set - new_shared_set
                    
                    added_depts = []
                    removed_depts = []
                    
                    # Remove sharing from departments no longer in the list
                    for dept in depts_to_remove:
                        try:
                            await self.tool_sharing_repo.unshare_tool_from_department(tool_id, dept)
                            removed_depts.append(dept)
                        except Exception as e:
                            log.warning(f"Failed to unshare tool from department {dept}: {e}")
                    
                    # Add sharing to new departments
                    if depts_to_add:
                        share_result = await self.tool_sharing_repo.share_tool_with_multiple_departments(
                            tool_id=tool_id,
                            tool_name=tool_data['tool_name'],
                            source_department=tool_data.get('department_name', ''),
                            target_departments=list(depts_to_add),
                            shared_by=user_id or ''
                        )
                        added_depts = list(depts_to_add)[:share_result.get("success_count", 0)]
                    
                    sharing_update_status = {
                        "added": added_depts,
                        "removed": removed_depts,
                        "current_shared_with": list(new_shared_set),
                        "invalid_departments": invalid_departments if invalid_departments else []
                    }
                    log.info(f"Updated sharing for tool '{tool_data['tool_name']}': added={added_depts}, removed={removed_depts}")
                except Exception as share_error:
                    log.warning(f"Failed to update tool sharing: {share_error}")
                    sharing_update_status = {"error": str(share_error)}

        if not tool_description and not code_snippet and not validator_flag_changed: # Only tags/sharing were updated
            log.info("No modifications made to the tool code/description attributes.")
            result = {
                "message": "Tool updated successfully",
                "details": [],
                "is_update": True
            }
            if tag_update_status:
                result["tag_update_status"] = tag_update_status
            if sharing_update_status:
                result["sharing_update_status"] = sharing_update_status
            if is_public_changed:
                result["is_public"] = is_public
            return result

        if code_snippet:
            validation_status = await self.tool_code_processor.validate_and_extract_tool_name(code_str=code_snippet)
            if "error" in validation_status:
                log.error(f"Tool updation failed: {validation_status['error']}")
                return {
                    "message": validation_status["error"],
                    "details": [],
                    "is_update": False
                }
            if validation_status["function_name"] != tool_data["tool_name"]:
                err = f"Tool name mismatch: Provided function name \'{validation_status['function_name']}\' does not match existing tool name \'{tool_data['tool_name']}\'."
                log.error(err)
                return {
                    "message": err,
                    "details": [],
                    "is_update": False
                }
            if not force_add:
                initial_state = {
                    "code": code_snippet,
                    "model": model_name,
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
                w_cases=["validation_case5","validation_case6","validation_case7"]
                e_cases=["validation_case1","validation_case4"]
                warnings={}
                errors={}
                log.info(f"Tool validation results: {workflow_result}")
                for i in w_cases:
                    if not workflow_result.get(i):
                        feedback_key = i.replace("validation_", "feedback_")
                        if workflow_result.get(feedback_key):
                            warnings[i] = workflow_result.get(feedback_key)
                for j in e_cases:
                    if not workflow_result.get(j):
                        feedback_key = j.replace("validation_", "feedback_")
                        errors[j] = workflow_result.get(feedback_key)
                if errors:
                    if 'validation_case1' in errors:
                        feedback_case1 = workflow_result.get('feedback_case1', '')
                        module_name = self._extract_module_name_from_error(feedback_case1)
                        if module_name:
                            try:
                                await save_pending_module(
                                    pool=self.tool_repo.pool,
                                    module_name=module_name,
                                    tool_name=tool_data['tool_name'],
                                    created_by=current_user_email.get(),
                                    tool_code=code_snippet  
                                )
                                log.info(f"Saved pending module '{module_name}' during tool update for '{tool_data['tool_name']}'")
                            except Exception as e:
                                log.error(f"Error saving pending module during update: {e}")
                    
                    verify=list(errors.values())
                    return {
                            "message": verify[0],
                            "details": [],
                            "is_update": False
                        }
                if warnings and not force_add:
                        verify=list(warnings.values())
                        return {
                            "message": ("Verification failed: "+str(verify)),
                            "details": [],
                            "error_on_screen": False,
                            "warnings":True,
                            "is_update": False
                        }           
            tool_data["code_snippet"] = code_snippet # Update for docstring generation

        if tool_description:
            tool_data["tool_description"] = tool_description

        # Update is_validator flag if provided - DISABLED: database column doesn't exist
        # if is_validator is not None:
        #     tool_data["is_validator"] = is_validator

        # [INFO] Validator-specific validation for validator tools
        # Always validate when converting to validator OR updating validator tool code
        if is_validator:
            # Use the current code snippet from tool_data if no new code provided
            code_to_validate = code_snippet or tool_data.get("code_snippet", "")
            log.info(f"Validating tool code for validator conversion: {tool_data['tool_name']}")
            validator_validation = await self.tool_code_processor.validate_validator_function(code_str=code_to_validate)
            if "error" in validator_validation or not validator_validation.get("is_valid", False):
                error_msg = validator_validation.get('error', 'Unknown validation error')
                log.error(f"Validator tool validation failed during update: {error_msg}")
                
                # Create detailed error message
                detailed_msg = f"❌ Validator Conversion Failed\n\n" \
                              f"Issue: {error_msg}\n\n" \
                              f"📋 Validator Requirements:\n" \
                              f"• Function must have exactly 2 parameters named: 'query', 'response'\n" \
                              f"• Function must return a dictionary with these keys:\n" \
                              f"  - 'validation_score' (float between 0.0 and 1.0)\n" \
                              f"  - 'feedback' (string with explanation)\n" \
                              f"  - 'validation_status' (string: 'valid' or 'invalid')\n\n" \
                              f"💡 Please update your tool's function signature and return format before converting to validator."
                
                raise HTTPException(
                    status_code=400,
                    detail=detailed_msg
                )
            log.info(f"[SUCCESS] Validator tool validation passed for updated tool: {tool_data['tool_name']}")

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
                    "message": f"The tool you are trying to update is being referenced by {len(agent_details)} agentic applications.",
                    "details": agent_details,
                    "is_update": False
                }

        llm = await self.model_service.get_llm_model(model_name=model_name, temperature=0.0)
        docstring_generation = await self.tool_code_processor.generate_docstring_for_tool_onboarding(
            llm=llm,
            tool_code_str=tool_data["code_snippet"],
            tool_description=tool_data["tool_description"]
        )
        if "error" in docstring_generation:
            log.error(f"Tool Update Failed: {docstring_generation['error']}")
            return {
                "message": f"Tool Update Failed: {docstring_generation['error']}",
                "details": [],
                "is_update": False
            }
        tool_data["code_snippet"] = docstring_generation["code_snippet"]
        tool_data["model_name"] = model_name # Ensure model name is updated if changed

        # Handle validator status change by updating tool_id prefix
        update_tool_id = tool_id  # Original tool_id for the update query
        if validator_flag_changed:
            current_tool_id = tool_data.get('tool_id', '')
            if is_validator and not current_tool_id.startswith('_validator'):
                # Convert to validator: add _validator prefix
                new_tool_id = f"_validator{current_tool_id}"
                tool_data["tool_id"] = new_tool_id
                log.info(f"Converting tool to validator: {current_tool_id} -> {new_tool_id}")
            elif not is_validator and current_tool_id.startswith('_validator'):
                # Convert from validator: remove _validator prefix
                new_tool_id = current_tool_id[10:]  # Remove '_validator' prefix
                tool_data["tool_id"] = new_tool_id
                log.info(f"Converting tool from validator: {current_tool_id} -> {new_tool_id}")

        success = await self.tool_repo.update_tool_record(tool_data, update_tool_id)

        if success:
            # Update the .py file for the tool using tool_name
            file_update_result = await self.tool_file_manager.update_tool_file(tool_data)
            if file_update_result.get("success"):
                log.info(f"Tool file updated at: {file_update_result.get('file_path')}")
            else:
                log.warning(f"Failed to update tool file: {file_update_result.get('message')}")
            # Extract and update access keys from @resource_access decorators
            if self.tool_access_key_mapping_repo:
                access_keys = self.tool_code_processor.extract_access_keys_from_code(tool_data["code_snippet"])
                if access_keys:
                    await self.tool_access_key_mapping_repo.save_tool_access_keys(
                        tool_id=tool_data['tool_id'],
                        tool_name=tool_data['tool_name'],
                        access_keys=access_keys,
                        department_name=tool_data.get('department_name')
                    )
                    log.info(f"Updated access keys {access_keys} for tool '{tool_data['tool_name']}'")
                else:
                    # No access keys found - remove any existing mapping
                    await self.tool_access_key_mapping_repo.delete_tool_access_keys(
                        tool_data['tool_id'],
                        department_name=tool_data.get('department_name')
                    )
                    log.info(f"Removed access key mapping for tool '{tool_data['tool_name']}' (no access decorators found)")
            
            status = {
                "message": f"Successfully updated the tool: {tool_data['tool_name']}",
                "details": [],
                "is_update": True,
                "file_updated": file_update_result.get("success", False),
                "file_path": file_update_result.get("file_path", "")
            }
        else:
            status = {
                "message": f"Failed to update the tool: {tool_data['tool_name']}.",
                "details": [],
                "is_update": False
            }

        if tag_update_status:
            status['tag_update_status'] = tag_update_status
        if sharing_update_status:
            status['sharing_update_status'] = sharing_update_status
        if is_public_changed:
            status['is_public'] = is_public
        log.info(f"Tool update status: {status['message']}")
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
                "message": "Error: Must provide 'tool_id' or 'tool_name' to delete a tool.",
                "details": [],
                "is_delete": False
            }

        tool_data = await self.tool_repo.get_tool_record(tool_id=tool_id, tool_name=tool_name, message_queue_implementation=False)
        if not tool_data:
            log.error(f"No Tool available with ID: {tool_id or tool_name}")
            return {
                "message": f"No Tool available with ID: {tool_id or tool_name}",
                "details": [],
                "is_delete": False
            }
        tool_data = tool_data[0]

        if not is_admin and tool_data["created_by"] != user_id:
            log.error(f"Permission denied: User {user_id} is not authorized to delete Tool ID: {tool_data['tool_id']}.")
            return {
                "message": f"Permission denied: Only the admin or the tool's creator can perform this action for Tool: {tool_data['tool_name']}.",
                "details": [],
                "is_delete": False
            }

        # Check for regular tool dependencies in tool-agent mappings
        agents_using_this_tool_raw = await self.tool_agent_mapping_repo.get_tool_agent_mappings_record(tool_id=tool_data['tool_id'])
        agent_details = []
        
        if agents_using_this_tool_raw:
            agent_ids = [m['agentic_application_id'] for m in agents_using_this_tool_raw]
            for agent_id in agent_ids:
                agent_record = await self.agent_repo.get_agent_record(agentic_application_id=agent_id)
                agent_record = agent_record[0] if agent_record else None
                if agent_record:
                    agent_details.append({
                        "agentic_application_id": agent_record['agentic_application_id'],
                        "agentic_application_name": agent_record['agentic_application_name'],
                        "agentic_app_created_by": agent_record['created_by'],
                        "dependency_type": "tool_binding"
                    })
        
        # Check for validator tool dependencies (OPTIMIZED: only for validator tools)
        is_validator = tool_data.get('is_validator', False) or tool_data.get('tool_id', '').startswith('_validator')
        if is_validator:
            # Use database LIKE query to find agents with this validator ID in their validation_criteria
            # This is much faster than loading and parsing all agents
            validator_using_agents = await self.agent_repo.find_agents_using_validator(tool_data['tool_id'])
            for agent in validator_using_agents:
                # Check if already added (avoid duplicates from tool_binding)
                if not any(detail.get('agentic_application_id') == agent['agentic_application_id'] for detail in agent_details):
                    agent_details.append({
                        "agentic_application_id": agent['agentic_application_id'],
                        "agentic_application_name": agent['agentic_application_name'],
                        "agentic_app_created_by": agent['created_by'],
                        "dependency_type": "validator_criteria"
                    })
        
        if agent_details:
            # Generate appropriate error message based on tool type
            tool_type = "validator tool" if is_validator else "tool"
            dependency_details = []
            for detail in agent_details:
                dependency_type_msg = "validation criteria" if detail["dependency_type"] == "validator_criteria" else "tool binding"
                dependency_details.append(f"Agent '{detail['agentic_application_name']}' (ID: {detail['agentic_application_id']}) uses it in {dependency_type_msg}")
            
            log.error(f"The {tool_type} you are trying to delete is being referenced by {len(agent_details)} agentic applications.")
            return {
                "message": f"Cannot delete {tool_type}: It is being used by {len(agent_details)} agent(s). Dependencies: {'; '.join(dependency_details[:3])}{'...' if len(dependency_details) > 3 else ''}",
                "details": agent_details,
                "is_delete": False
            }

        # Move to recycle bin
        recycle_success = await self.recycle_tool_repo.insert_recycle_tool_record(tool_data)
        if not recycle_success:
            log.error(f"Failed to move tool {tool_data['tool_id']} to recycle bin.")
            return {
                "message": f"Failed to move tool {tool_data['tool_id']} to recycle bin.",
                "details": [],
                "is_delete": False
            }

        # Clean up mappings
        await self.tool_agent_mapping_repo.remove_tool_from_agent_record(tool_id=tool_data['tool_id'])
        await self.tag_service.clear_tags(tool_id=tool_data['tool_id'])
        
        # Clean up access key mapping if exists
        if self.tool_access_key_mapping_repo:
            await self.tool_access_key_mapping_repo.delete_tool_access_keys(tool_id=tool_data['tool_id'])

        # Delete from main table
        delete_success = await self.tool_repo.delete_tool_record(tool_data['tool_id'])

        if delete_success:
            # Delete the .py file for the tool using tool_name
            file_delete_result = await self.tool_file_manager.delete_tool_file(tool_data['tool_name'])
            if file_delete_result.get("success"):
                log.info(f"Tool file deleted: {file_delete_result.get('success')}")
            else:
                log.warning(f"Failed to delete tool file (may not exist): {file_delete_result.get('message')}")
            
            log.info(f"Successfully deleted tool with ID: {tool_data['tool_id']}")
            return {
                "message": f"Successfully deleted tool: {tool_data['tool_name']}",
                "details": [],
                "is_delete": True,
                "file_deleted": file_delete_result.get("success", False)
            }
        else:
            # Rollback: Remove from recycle bin since delete from main table failed
            log.error(f"Failed to delete tool {tool_data['tool_id']} from main table. Rolling back recycle bin insert.")
            rollback_success = await self.recycle_tool_repo.delete_recycle_tool_record(tool_data['tool_id'])
            if not rollback_success:
                log.error(f"Rollback failed: Could not remove tool '{tool_data['tool_id']}' from recycle bin. Tool may exist in both tables.")
            return {
                "message": f"Failed to delete tool {tool_data['tool_name']} from main table. The tool remains in the main table.",
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
                "message": f"Successfully approved tool with ID: {tool_id}",
                "tool_id": tool_id,
                "approved_by": approved_by,
                "is_approved": True
            }
        else:
            log.error(f"Failed to approve tool with ID: {tool_id}")
            return {
                "message": f"Failed to approve tool with ID: {tool_id}",
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
                tool = await self.tool_repo.get_tool_record(tool_id=tool_id_single, message_queue_implementation=False)
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
                # Skip validator tools by tool_id prefix
                if tool_id_single.startswith("_validator"):
                    log.warning(f"Skipping validator tool with ID: {tool_id_single}")
                    continue
                    
                tool_record = await self.tool_repo.get_tool_record(tool_id=tool_id_single, message_queue_implementation=False)
                if tool_record:
                    tool_record = tool_record[0]
                    
                    # Additional check: Skip if is_validator flag is True
                    if tool_record.get("is_validator", False):
                        log.warning(f"Skipping validator tool '{tool_record.get('tool_name')}' (is_validator=True)")
                        continue
                        
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
    async def _generate_tool_prompt_from_tools_info(tools_info: Dict[str, Any], include_memory_tools: bool = True) -> str:
        """
        Generates a prompt for the agent describing the available tools.

        Args:
            tools_info (dict): A dictionary containing information about each tool.
            include_memory_tools (bool): Whether to include memory tool info in the prompt. Default is True.

        Returns:
            str: A prompt string describing the tools.
        """
        tool_prompt = ""
        
        if include_memory_tools:
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
            if tool_id.startswith("_validator"):
                log.warning(f"Tool '{tool_id}' is a validator tool and will be skipped.")
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

    async def generate_tool_prompt(self, tools_id: Union[List[str], str], include_memory_tools: bool = True) -> str:
        """
        Generates a prompt for the agent describing the available tools.

        Args:
            tools_id (Union[List[str], str]): A list of tool IDs to generate the prompt for.
            include_memory_tools (bool): Whether to include memory tool info in the prompt. Default is True.

        Returns:
            str: A prompt string describing the tools.
        """
        tools_info = await self._extract_tools_using_tool_ids(tools_id)
        return await self._generate_tool_prompt_from_tools_info(tools_info, include_memory_tools=include_memory_tools)

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
                agentic_application_type=[e.value for e in AgentType.meta_types()]
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

    async def get_all_tools_from_recycle_bin(self, department_name: str = None) -> List[Dict[str, Any]]:
        """
        Retrieves all tools from the recycle bin.

        Returns:
            list: A list of dictionaries representing the tools in the recycle bin.
        """
        return await self.recycle_tool_repo.get_all_recycle_tool_records(department_name=department_name)

    async def restore_tool(self, tool_id: Optional[str] = None, tool_name: Optional[str] = None, department_name: str = None) -> Dict[str, Any]:
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
                "message": "Error: Must provide 'tool_id' or 'tool_name' to restore a tool.",
                "details": [],
                "is_restored": False
            }

        tool_data = await self.recycle_tool_repo.get_recycle_tool_record(tool_id=tool_id, tool_name=tool_name, department_name=department_name)
        if not tool_data:
            log.warning(f"No Tool available in recycle bin with ID: {tool_id or tool_name}")
            return {
                "message": f"No Tool available in recycle bin with ID: {tool_id or tool_name}",
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
                "message": f"Failed to restore tool {tool_data['tool_name']} to main table (might already exist).",
                "details": [],
                "is_restored": False
            }

        # Recreate the .py file using database data
        file_restore_result = await self.tool_file_manager.restore_tool_file(tool_data)
        if file_restore_result.get("success"):
            log.info(f"Tool file restored at: {file_restore_result.get('file_path')}")
        else:
            log.warning(f"Failed to restore tool file: {file_restore_result.get('message')}")

        # Delete from recycle bin
        delete_success = await self.recycle_tool_repo.delete_recycle_tool_record(tool_data['tool_id'])
        if delete_success:
            log.info(f"Successfully deleted tool {tool_data['tool_id']} from recycle bin.")
            return {
                "message": f"Successfully restored tool with ID: {tool_data['tool_id']}",
                "details": [],
                "is_restored": True,
                "file_restored": file_restore_result.get("success", False),
                "file_path": file_restore_result.get("file_path", "")
            }
        else:
            log.error(f"Failed to delete tool {tool_data['tool_id']} from recycle bin after restoration.")
            return {
                "message": f"Tool {tool_data['tool_id']} restored to main table, but failed to delete from recycle bin.",
                "details": [],
                "is_restored": False,
                "file_restored": file_restore_result.get("success", False),
                "file_path": file_restore_result.get("file_path", "")
            }

    async def delete_tool_from_recycle_bin(self, tool_id: Optional[str] = None, tool_name: Optional[str] = None, department_name: str = None) -> Dict[str, Any]:
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
                "message": "Error: Must provide 'tool_id' or 'tool_name' to permanently delete a tool.",
                "details": [],
                "is_delete": False
            }

        tool_data = await self.recycle_tool_repo.get_recycle_tool_record(tool_id=tool_id, tool_name=tool_name, department_name=department_name)
        if not tool_data:
            log.warning(f"No Tool available in recycle bin with ID: {tool_id or tool_name}")
            return {
                "message": f"No Tool available in recycle bin with ID: {tool_id or tool_name}",
                "details": [],
                "is_delete": False
            }

        success = await self.recycle_tool_repo.delete_recycle_tool_record(tool_data['tool_id'])
        if success:
            log.info(f"Successfully deleted tool from recycle bin with ID: {tool_data['tool_id']}")
            return {
                "message": f"Successfully deleted tool from recycle bin with ID: {tool_data['tool_id']}",
                "details": [],
                "is_delete": True
            }
        else:
            log.error(f"Failed to delete tool {tool_data['tool_id']} from recycle bin.")
            return {
                "message": f"Failed to delete tool {tool_data['tool_id']} from recycle bin.",
                "details": [],
                "is_delete": False
            }

    async def _read_uploaded_file_content(self, uploaded_file: UploadFile) -> str:
        """
        Reads content from an uploaded FastAPI UploadFile and normalizes newlines.
        """
        try:
            content_bytes = await uploaded_file.read()
            content_str = content_bytes.decode("utf-8")
            normalized_content = content_str.replace('\r\n', '\n').replace('\r', '\n')
            return normalized_content

        except Exception as e:
            log.error(f"Error reading and normalizing uploaded file content: {e}")
            raise


# --- Agent Service ---

class AgentServiceUtils:

    def __init__(
        self,
        agent_repo: AgentRepository,
        recycle_agent_repo: RecycleAgentRepository,
        tool_service: ToolService,
        tag_service: TagService,
        model_service: ModelService,
        knowledgebase_service: 'KnowledgebaseService' = None,
        agent_pipeline_mapping_repo: AgentPipelineMappingRepository = None,
        pipeline_repo: PipelineRepository = None,
        agent_sharing_repo = None,  # Repository for agent department sharing
        department_repo = None,  # Repository for validating department names
    ):
        self.agent_repo = agent_repo
        self.recycle_agent_repo = recycle_agent_repo
        self.tool_service = tool_service
        self.tag_service = tag_service
        self.model_service = model_service
        self.knowledgebase_service = knowledgebase_service
        self.agent_pipeline_mapping_repo = agent_pipeline_mapping_repo
        self.pipeline_repo = pipeline_repo
        self.agent_sharing_repo = agent_sharing_repo  # Store agent sharing repo
        self.department_repo = department_repo  # Store department repo for validation
        self.meta_type_templates = [agent_type.value for agent_type in AgentType.meta_types()]
        self.agent_pipeline_mapping_repo = agent_pipeline_mapping_repo


    @staticmethod
    async def _normalize_agent_name(agent_name: str):
        """
        Normalizes the agent name by removing invalid characters and formatting it.
        """
        normalized_agent_name: str = re.sub(r'[^a-z0-9_]', '', agent_name.strip().lower().replace(" ", "_"))
        if not normalized_agent_name or normalized_agent_name[0].isdigit():
            normalized_agent_name = f"agent_{normalized_agent_name}"
        return normalized_agent_name

    @staticmethod
    def get_code_for_agent_type(agent_type: str) -> str:
        """
        Returns a three-letter code for the given agent type.
        """
        mapping = {
            "react_agent": "rea",
            "multi_agent": "pec", # Planner-Executor-Critic
            "planner_executor_agent": "pex",
            "react_critic_agent": "rec",
            "simple_ai_agent": "sai",
            "hybrid_agent": "hyb",
            "meta_agent": "met",
            "planner_meta_agent": "pme"
        }
        if agent_type not in mapping:
            log.warning(f"Agent type '{agent_type}' not recognized.")
        return mapping.get(agent_type)

    # =====================================================
    # File-Context Prompt Management Utilities
    # =====================================================
    FILE_CONTEXT_PROMPTS_DIR = os.path.join("agent_workspaces", "file_context_prompts")
    FILE_CONTEXT_RECYCLE_BIN_DIR = os.path.join("agent_workspaces", "file_context_prompts_recycle_bin")

    @staticmethod
    def get_safe_agent_name(agent_name: str) -> str:
        """Sanitize agent name for use in filenames."""
        return "".join(c if c.isalnum() or c in (' ', '-', '_') else '_' for c in agent_name).strip().replace(' ', '_')

    @staticmethod
    def filter_memory_tools_from_prompt(tool_prompt: str) -> str:
        """
        Remove memory tool information (manage_tool, search_tool) from the tool prompt.
        File-based context management uses shell commands instead of these memory tools.
        
        Args:
            tool_prompt: The tool prompt string containing tool definitions.
            
        Returns:
            The filtered tool prompt with memory tool data removed.
        """
        if not tool_prompt:
            return tool_prompt
        
        # Pattern to match the memory tool data block
        memory_tool_pattern = r'\s*tool_name\s*:\s*manage_tool.*?tool_namespace\s*:\s*infyagent_framework/\{user_id\}/conversation_collection\s*'
        
        # Remove the memory tool data
        filtered_prompt = re.sub(memory_tool_pattern, '', tool_prompt, flags=re.DOTALL | re.IGNORECASE)
        
        # Clean up any excessive newlines left over
        filtered_prompt = re.sub(r'\n{4,}', '\n\n\n\n', filtered_prompt)
        
        return filtered_prompt.strip()

    @staticmethod
    def move_file_context_prompt_to_recycle_bin(agent_name: str) -> dict:
        """
        Move file-context prompt to recycle bin when agent is deleted.
        
        Args:
            agent_name: The name of the agent whose prompt should be moved.
            
        Returns:
            dict with keys: success, message, source_path, dest_path
        """
        safe_agent_name = AgentServiceUtils.get_safe_agent_name(agent_name)
        source_path = os.path.join(AgentServiceUtils.FILE_CONTEXT_PROMPTS_DIR, f"{safe_agent_name}_file_context_prompt.md")
        dest_path = os.path.join(AgentServiceUtils.FILE_CONTEXT_RECYCLE_BIN_DIR, f"{safe_agent_name}_file_context_prompt.md")
        
        if not os.path.exists(source_path):
            return {
                "success": True,
                "message": "No file-context prompt exists for this agent",
                "source_path": source_path,
                "dest_path": None
            }
        
        try:
            # Ensure recycle bin directory exists
            os.makedirs(AgentServiceUtils.FILE_CONTEXT_RECYCLE_BIN_DIR, exist_ok=True)
            
            # Move file to recycle bin
            shutil.move(source_path, dest_path)
            log.info(f"Moved file-context prompt to recycle bin: {source_path} -> {dest_path}")
            
            return {
                "success": True,
                "message": "File-context prompt moved to recycle bin",
                "source_path": source_path,
                "dest_path": dest_path
            }
        except Exception as e:
            log.error(f"Failed to move file-context prompt to recycle bin: {str(e)}")
            return {
                "success": False,
                "message": f"Failed to move file-context prompt: {str(e)}",
                "source_path": source_path,
                "dest_path": dest_path
            }

    @staticmethod
    def restore_file_context_prompt_from_recycle_bin(agent_name: str) -> dict:
        """
        Restore file-context prompt from recycle bin when agent is restored.
        
        Args:
            agent_name: The name of the agent whose prompt should be restored.
            
        Returns:
            dict with keys: success, message, source_path, dest_path
        """
        safe_agent_name = AgentServiceUtils.get_safe_agent_name(agent_name)
        source_path = os.path.join(AgentServiceUtils.FILE_CONTEXT_RECYCLE_BIN_DIR, f"{safe_agent_name}_file_context_prompt.md")
        dest_path = os.path.join(AgentServiceUtils.FILE_CONTEXT_PROMPTS_DIR, f"{safe_agent_name}_file_context_prompt.md")
        
        if not os.path.exists(source_path):
            return {
                "success": True,
                "message": "No file-context prompt in recycle bin for this agent",
                "source_path": source_path,
                "dest_path": None
            }
        
        try:
            # Ensure prompts directory exists
            os.makedirs(AgentServiceUtils.FILE_CONTEXT_PROMPTS_DIR, exist_ok=True)
            
            # Move file back from recycle bin
            shutil.move(source_path, dest_path)
            log.info(f"Restored file-context prompt from recycle bin: {source_path} -> {dest_path}")
            
            return {
                "success": True,
                "message": "File-context prompt restored from recycle bin",
                "source_path": source_path,
                "dest_path": dest_path
            }
        except Exception as e:
            log.error(f"Failed to restore file-context prompt from recycle bin: {str(e)}")
            return {
                "success": False,
                "message": f"Failed to restore file-context prompt: {str(e)}",
                "source_path": source_path,
                "dest_path": dest_path
            }

    @staticmethod
    def permanently_delete_file_context_prompt(agent_name: str) -> dict:
        """
        Permanently delete file-context prompt from recycle bin.
        
        Args:
            agent_name: The name of the agent whose prompt should be deleted.
            
        Returns:
            dict with keys: success, message, file_path
        """
        safe_agent_name = AgentServiceUtils.get_safe_agent_name(agent_name)
        file_path = os.path.join(AgentServiceUtils.FILE_CONTEXT_RECYCLE_BIN_DIR, f"{safe_agent_name}_file_context_prompt.md")
        
        if not os.path.exists(file_path):
            return {
                "success": True,
                "message": "No file-context prompt in recycle bin for this agent",
                "file_path": file_path
            }
        
        try:
            os.remove(file_path)
            log.info(f"Permanently deleted file-context prompt: {file_path}")
            
            return {
                "success": True,
                "message": "File-context prompt permanently deleted",
                "file_path": file_path
            }
        except Exception as e:
            log.error(f"Failed to permanently delete file-context prompt: {str(e)}")
            return {
                "success": False,
                "message": f"Failed to delete file-context prompt: {str(e)}",
                "file_path": file_path
            }

    async def regenerate_file_context_prompt(
        self,
        agent_name: str,
        agent_goal: str,
        workflow_description: str,
        tools_id: List[str],
        model_name: str,
        is_meta_agent: bool = False
    ) -> dict:
        """
        Regenerate file-context prompt for an agent using LLM.
        
        Note: Memory tools (manage_tool, search_tool) are NOT included in the file-context prompt
        because file-based context management uses shell commands for memory operations instead.
        
        Args:
            agent_name: The name of the agent.
            agent_goal: The goal/description of the agent.
            workflow_description: The workflow description of the agent.
            tools_id: List of tool IDs associated with the agent.
            model_name: The model name to use for generation.
            is_meta_agent: Whether this is a meta agent (uses worker agents instead of tools).
            
        Returns:
            dict with keys: success, message, file_path, prompt (optional)
        """
        try:
            from src.prompts.prompts import file_context_system_prompt_generator
            
            # Generate tool/worker agents prompt WITHOUT memory tools
            # File-based context management uses shell commands for memory, not manage_tool/search_tool
            if is_meta_agent:
                # For meta agents, generate worker agents prompt
                # Get agent info for each worker agent
                worker_agents_info = []
                for agent_id in tools_id:
                    agent_info = await self.agent_repo.get_agent(agentic_application_id=agent_id)
                    if agent_info:
                        agent_data = agent_info[0] if isinstance(agent_info, list) else agent_info
                        worker_agents_info.append({
                            "name": agent_data.get("agentic_application_name", ""),
                            "description": agent_data.get("agentic_application_description", ""),
                            "type": agent_data.get("agentic_application_type", "")
                        })
                
                tool_or_worker_agents_prompt = "\n".join([
                    f"- **{info['name']}** ({info['type']}): {info['description']}"
                    for info in worker_agents_info
                ]) if worker_agents_info else "No worker agents configured."
            else:
                # For regular agents, generate tool prompt WITHOUT memory tools
                tool_or_worker_agents_prompt = await self.tool_service.generate_tool_prompt(
                    tools_id, 
                    include_memory_tools=False
                )
            
            # Apply filter as extra safety measure to ensure no memory tools in prompt
            tool_or_worker_agents_prompt = self.filter_memory_tools_from_prompt(tool_or_worker_agents_prompt)
            
            # Get LLM model
            llm = await self.model_service.get_llm_model(model_name=model_name, temperature=0)
            
            # Generate file-context prompt using the template with LLM
            file_context_prompt_template = PromptTemplate.from_template(file_context_system_prompt_generator)
            file_context_prompt_gen = file_context_prompt_template | llm | StrOutputParser()
            
            log.info(f"Generating File-Context System Prompt for agent '{agent_name}'")
            file_context_prompt = await file_context_prompt_gen.ainvoke({
                "agent_name": agent_name,
                "agent_goal": agent_goal,
                "workflow_description": workflow_description,
                "tool_prompt": tool_or_worker_agents_prompt
            })
            
            # Save to file
            safe_agent_name = self.get_safe_agent_name(agent_name)
            prompt_file_path = os.path.join(self.FILE_CONTEXT_PROMPTS_DIR, f"{safe_agent_name}_file_context_prompt.md")
            os.makedirs(os.path.dirname(prompt_file_path), exist_ok=True)
            
            with open(prompt_file_path, "w", encoding="utf-8") as f:
                f.write(file_context_prompt)
            
            log.info(f"File-context prompt regenerated for agent '{agent_name}' at: {prompt_file_path}")
            
            return {
                "success": True,
                "message": "File-context prompt regenerated successfully",
                "file_path": prompt_file_path,
                "prompt": file_context_prompt
            }
            
        except Exception as e:
            log.error(f"Failed to regenerate file-context prompt for agent '{agent_name}': {str(e)}")
            return {
                "success": False,
                "message": f"Failed to regenerate file-context prompt: {str(e)}",
                "file_path": None
            }

    @staticmethod
    def update_file_context_prompt(agent_name: str, prompt_content: str) -> dict:
        """
        Update/save file-context prompt content directly.
        
        Args:
            agent_name: The name of the agent.
            prompt_content: The prompt content to save.
            
        Returns:
            dict with keys: success, message, file_path
        """
        try:
            safe_agent_name = AgentServiceUtils.get_safe_agent_name(agent_name)
            prompt_file_path = os.path.join(AgentServiceUtils.FILE_CONTEXT_PROMPTS_DIR, f"{safe_agent_name}_file_context_prompt.md")
            os.makedirs(os.path.dirname(prompt_file_path), exist_ok=True)
            
            with open(prompt_file_path, "w", encoding="utf-8") as f:
                f.write(prompt_content)
            
            log.info(f"File-context prompt updated for agent '{agent_name}' at: {prompt_file_path}")
            
            return {
                "success": True,
                "message": "File-context prompt updated successfully",
                "file_path": prompt_file_path
            }
            
        except Exception as e:
            log.error(f"Failed to update file-context prompt for agent '{agent_name}': {str(e)}")
            return {
                "success": False,
                "message": f"Failed to update file-context prompt: {str(e)}",
                "file_path": None
            }


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
        self.knowledgebase_service = agent_service_utils.knowledgebase_service
        self.meta_type_templates = agent_service_utils.meta_type_templates
        self.agent_pipeline_mapping_repo = agent_service_utils.agent_pipeline_mapping_repo
        self.pipeline_repo = agent_service_utils.pipeline_repo
        self.agent_sharing_repo = agent_service_utils.agent_sharing_repo  # Store agent sharing repo
        self.department_repo = agent_service_utils.department_repo  # Store department repo for validation
        self.agent_pipeline_mapping_repo = agent_service_utils.agent_pipeline_mapping_repo


    # --- Agent Creation Operations ---

    async def _save_agent_data(self, agent_data: Dict[str, Any], shared_with_departments: Optional[List[str]] = None) -> Dict[str, Any]:
        """
        Saves agent data to the database, including associated tool/worker agent mappings and tags.
        This is a private helper method used by public onboarding methods.

        Args:
            agent_data (dict): A dictionary containing the agent data to insert.
            shared_with_departments (List[str], optional): List of department names to share the agent with.

        Returns:
            dict: Status of the operation.
        """
        agent_data['system_prompt'] = json.dumps(agent_data['system_prompt'])
        agent_data['tools_id'] = json.dumps(agent_data.get('tools_id', []))
        
        # Serialize validation_criteria if present
        if 'validation_criteria' in agent_data and agent_data['validation_criteria'] is not None:
            agent_data['validation_criteria'] = json.dumps(agent_data['validation_criteria'])

        now = datetime.now(timezone.utc).replace(tzinfo=None)
        agent_data["created_on"] = now
        agent_data["updated_on"] = now

        agent_type = agent_data.get("agentic_application_type", "")
        if not agent_data.get("agentic_application_id"):
            agent_code = AgentType(agent_type).code
            agent_data["agentic_application_id"] = f"{agent_code}_{uuid.uuid4()}"
            log.info(f"Generated new agentic_application_id: {agent_data['agentic_application_id']}")
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
            
            # Handle department sharing if specified (skip if is_public=true as it's redundant)
            sharing_status = None
            is_public = agent_data.get('is_public', False)
            
            # Get tools info for cascade sharing (separate regular tools and MCP tools)
            tools_info = []
            mcp_tools_info = []
            is_meta_agent = agent_data["agentic_application_type"] in self.meta_type_templates
            if not is_meta_agent:
                for tool_id in associated_ids:
                    if tool_id.startswith("mcp_"):
                        # MCP tool - fetch from MCP tool service
                        mcp_tool_data = await self.mcp_tool_service.get_mcp_tool(tool_id=tool_id)
                        if mcp_tool_data:
                            mcp_tools_info.append({
                                'tool_id': mcp_tool_data[0]['tool_id'],
                                'tool_name': mcp_tool_data[0].get('tool_name', ''),
                                'department_name': mcp_tool_data[0].get('department_name', agent_data.get('department_name', ''))
                            })
                    else:
                        # Regular tool - fetch from tool service
                        tool_data = await self.tool_service.get_tool(tool_id=tool_id)
                        if tool_data:
                            tools_info.append({
                                'tool_id': tool_data[0]['tool_id'],
                                'tool_name': tool_data[0].get('tool_name', ''),
                                'department_name': tool_data[0].get('department_name', agent_data.get('department_name', ''))
                            })
            
            # If agent is public, also make its tools public (both regular and MCP)
            if is_public and tools_info:
                for tool in tools_info:
                    try:
                        await self.tool_service.tool_repo.update_tool_record({"is_public": True}, tool['tool_id'])
                        log.info(f"Made tool '{tool['tool_name']}' public (cascade from public agent)")
                    except Exception as e:
                        log.warning(f"Failed to make tool '{tool['tool_id']}' public: {e}")
            
            if is_public and mcp_tools_info:
                for mcp_tool in mcp_tools_info:
                    try:
                        await self.mcp_tool_service.mcp_tool_repo.update_mcp_tool_record({"is_public": True}, mcp_tool['tool_id'])
                        log.info(f"Made MCP tool '{mcp_tool['tool_name']}' public (cascade from public agent)")
                    except Exception as e:
                        log.warning(f"Failed to make MCP tool '{mcp_tool['tool_id']}' public: {e}")
            
            # Gather KB info for cascade sharing/public (needed for both public and shared scenarios)
            kbs_info = []
            if self.knowledgebase_service:
                try:
                    kb_ids = await self.knowledgebase_service.agent_kb_mapping_repo.get_knowledgebase_ids_for_agent(agent_data['agentic_application_id'])
                    for kb_id in kb_ids:
                        kb_record = await self.knowledgebase_service.knowledgebase_repo.get_knowledgebase_by_id(kb_id)
                        if kb_record:
                            kbs_info.append({
                                'kb_id': kb_id,
                                'kb_name': kb_record.get('knowledgebase_name', ''),
                                'department_name': kb_record.get('department_name', agent_data.get('department_name', ''))
                            })
                except Exception as e:
                    log.warning(f"Failed to gather KB info for cascade sharing: {e}")
            
            # If agent is public, also make its knowledge bases public
            if is_public and kbs_info:
                for kb in kbs_info:
                    try:
                        await self.knowledgebase_service.knowledgebase_repo.update_kb_visibility(kb['kb_id'], True)
                        log.info(f"Made KB '{kb['kb_name']}' public (cascade from public agent)")
                    except Exception as e:
                        log.warning(f"Failed to make KB '{kb['kb_id']}' public: {e}")
            
            if is_public and shared_with_departments:
                log.info(f"Agent '{agent_data['agentic_application_name']}' is public, skipping shared_with_departments as public agents are visible to all departments")
                sharing_status = {"message": "Agent is public, shared_with_departments ignored"}
            elif shared_with_departments and self.agent_sharing_repo:
                try:
                    invalid_departments = []
                    valid_departments = []
                    if self.department_repo:
                        for dept_name in shared_with_departments:
                            dept = await self.department_repo.get_department_by_name(dept_name)
                            if dept:
                                valid_departments.append(dept_name)
                            else:
                                invalid_departments.append(dept_name)
                    else:
                        # If no department_repo available, proceed with all departments
                        valid_departments = shared_with_departments
                    
                    if invalid_departments:
                        log.warning(f"Invalid department names provided for sharing: {invalid_departments}")
                    
                    if valid_departments:
                        sharing_result = await self.agent_sharing_repo.share_agent_with_multiple_departments(
                            agentic_application_id=agent_data['agentic_application_id'],
                            agentic_application_name=agent_data['agentic_application_name'],
                            source_department=agent_data.get('department_name', ''),
                            target_departments=valid_departments,
                            shared_by=agent_data.get('created_by', ''),
                            tools_info=tools_info,  # Pass regular tools for cascade sharing
                            mcp_tools_info=mcp_tools_info,  # Pass MCP tools for cascade sharing
                            kbs_info=kbs_info  # Pass knowledge bases for cascade sharing
                        )
                        sharing_status = {
                            "shared_with": valid_departments[:sharing_result.get("success_count", 0)],
                            "failed": sharing_result.get("failures", []),
                            "invalid_departments": invalid_departments,
                            "tools_shared": sharing_result.get("total_tools_shared", 0),
                            "mcp_tools_shared": sharing_result.get("total_mcp_tools_shared", 0),
                            "kbs_shared": sharing_result.get("total_kbs_shared", 0)
                        }
                        log.info(f"Agent '{agent_data['agentic_application_name']}' shared with departments: {sharing_result.get('shared_departments', [])}")
                    else:
                        sharing_status = {"error": "No valid departments to share with", "invalid_departments": invalid_departments}
                except Exception as share_error:
                    log.warning(f"Failed to share agent with departments: {share_error}")
                    sharing_status = {"error": str(share_error)}

            log.info(f"Successfully onboarded Agentic Application with ID: {agent_data['agentic_application_id']}")
            result = {
                "message": f"Successfully onboarded Agent: {agent_data['agentic_application_name']}",
                "agentic_application_id": agent_data["agentic_application_id"],
                "agentic_application_name": agent_data["agentic_application_name"],
                "agentic_application_type": agent_data["agentic_application_type"],
                "model_name": agent_data.get("model_name", ""),
                "tags_status": tags_status,
                "created_by": agent_data["created_by"],
                "is_public": agent_data.get("is_public", False),
                "is_created": True
            }
            if sharing_status:
                result["sharing_status"] = sharing_status
            return result
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
                             department_name: Optional[str] = None,
                             tag_ids: Optional[Union[str, List[str]]] = None,
                             validation_criteria: Optional[List[Dict[str, Any]]] = None,
                             knowledgebase_ids: Optional[List[str]] = None,
                             is_public: Optional[bool] = False,
                             shared_with_departments: Optional[List[str]] = None) -> Dict[str, Any]:
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
            validation_criteria (List[Dict[str, Any]], optional): List of validation test cases for the agent.
            knowledgebase_ids (List[str], optional): A list of knowledgebase IDs to link to the agent.
            is_public (bool, optional): Whether the agent is public (accessible to all departments).
            shared_with_departments (List[str], optional): List of department names to share the agent with.

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

        # Generate tool_prompt for welcome message
        tool_prompt_for_welcome = ""
        is_meta_template = agent_type in self.meta_type_templates
        if is_meta_template:
            tool_prompt_for_welcome = await self.generate_worker_agents_prompt(agents_id=associated_ids)
        else:
            tool_prompt_for_welcome = await self.tool_service.generate_tool_prompt(associated_ids)

        system_prompt, welcome_message = await asyncio.gather(
            self._get_system_prompt_for_agent(
                agent_name=agent_name,
                agent_goal=agent_goal,
                workflow_description=workflow_description,
                agent_type=agent_type,
                associated_ids=associated_ids,
                model_name=model_name
            ),
            self._get_welcome_message_for_agent(
                agent_name=agent_name,
                agent_goal=agent_goal,
                workflow_description=workflow_description,
                agent_type=agent_type,
                model_name=model_name,
                tool_prompt=tool_prompt_for_welcome
            )
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
            "welcome_message": welcome_message,
            "tools_id": associated_ids,
            "created_by": user_id,
            "department_name": department_name,
            "tag_ids": tag_ids,
            "is_public": is_public if is_public is not None else False
        }

        # Only add validation_criteria for non-meta agents
        if agent_type not in self.meta_type_templates and validation_criteria is not None:
            agent_data["validation_criteria"] = validation_criteria
        agent_creation_status = await self._save_agent_data(agent_data, shared_with_departments=shared_with_departments)
        
        # Link knowledgebases if provided
        if agent_creation_status.get("is_created") and knowledgebase_ids and self.knowledgebase_service:
            try:
                # Validate that KB IDs exist and belong to the agent's department
                kb_validation = await self.knowledgebase_service.validate_knowledgebase_ids(
                    knowledgebase_ids=knowledgebase_ids,
                    department_name=department_name
                )
                if "error" in kb_validation:
                    log.warning(f"KB validation failed during onboarding agent '{agent_name}': {kb_validation['error']}")
                    agent_creation_status["knowledgebase_warning"] = kb_validation["error"]
                else:
                    await self.knowledgebase_service.link_knowledgebases_to_agent(
                        agentic_application_id=agent_creation_status["agentic_application_id"],
                        knowledgebase_ids=knowledgebase_ids
                    )
                    log.info(f"Linked {len(knowledgebase_ids)} knowledgebases to agent {agent_name}")
            except Exception as e:
                log.warning(f"Failed to link knowledgebases to agent {agent_name}: {e}")
        
        log.info(f"Agentic Application '{agent_name}' of type {agent_type.replace('_', ' ').title()} created successfully.")
        return agent_creation_status

    # --- Agent Retrieval Operations ---

    async def get_agent(self,
                        agentic_application_id: Optional[str] = None,
                        agentic_application_name: Optional[str] = None,
                        agentic_application_type: Optional[str] = None,
                        department_name: str = None,
                        created_by: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        Retrieves agents from the database based on provided parameters, with associated tags and sharing info.
        Includes agents that are: owned by department, public, OR shared with the department.

        Args:
            agentic_application_id (str, optional): The ID of the agentic application to filter by.
            agentic_application_name (str, optional): The name of the agentic application to filter by.
            agentic_application_type (str, optional): The type of agentic application to filter by.
            department_name (str, optional): The department name to filter by.
            created_by (str, optional): The creator of the agentic application to filter by.

        Returns:
            list: A list of dictionaries representing the retrieved agents with tags and shared_with_departments, or an empty list on error.
        """
        agent_records = await self.agent_repo.get_agent_record(
            agentic_application_id=agentic_application_id,
            agentic_application_name=agentic_application_name,
            agentic_application_type=agentic_application_type,
            department_name = department_name,
            created_by=created_by
        )

        # If not found and department specified, check if agent is shared with this department
        if not agent_records and department_name and self.agent_sharing_repo and agentic_application_id:
            # Check if this agent is shared with the user's department
            is_shared = await self.agent_sharing_repo.is_agent_shared_with_department(agentic_application_id, department_name)
            if is_shared:
                # Get the agent without department filter
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
                # Deserialize validation_criteria if present
                if 'validation_criteria' in agent_record and agent_record['validation_criteria'] is not None:
                    agent_record['validation_criteria'] = json.loads(agent_record['validation_criteria']) if isinstance(agent_record['validation_criteria'], str) else agent_record['validation_criteria']
                agent_record['tags'] = await self.tag_service.get_tags_by_agent(agent_record['agentic_application_id'])
                # Add shared departments information
                if self.agent_sharing_repo:
                    shared_info = await self.agent_sharing_repo.get_shared_departments_for_agent(agent_record['agentic_application_id'])
                    agent_record['shared_with_departments'] = [info['target_department'] for info in shared_info]
                else:
                    agent_record['shared_with_departments'] = []
                
                log.info(f"Retrieved agentic application with name: {agentic_application_name}")
        return agent_records

    async def get_all_agents(self, agentic_application_type: Optional[Union[str, List[str]]] = None, department_name: str = None, include_shared: bool = True) -> List[Dict[str, Any]]:
        """
        Retrieves all agents, optionally filtered by type, with associated tags and sharing info.
        When department_name is specified, also includes shared and public agents.

        Args:
            agentic_application_type (Union[List[str], str], optional): The type(s) of agentic application to filter by.
            department_name (str, optional): Filter by department. If provided and include_shared=True,
                                             includes agents shared with this department and public agents.
            include_shared (bool): Whether to include shared/public agents. Defaults to True.

        Returns:
            list: A list of agents with tags and shared_with_departments, represented as dictionaries.
        """
        # If department specified and sharing enabled, use the enhanced method
        if department_name and include_shared and self.agent_sharing_repo:
            # Get IDs of agents shared with this department
            shared_agent_ids = await self.agent_sharing_repo.get_agents_shared_with_department(department_name)
            agent_records = await self.agent_repo.get_all_agent_records_with_shared(
                department_name=department_name,
                shared_agent_ids=shared_agent_ids,
                include_public=True,
                agentic_application_type=agentic_application_type
            )
        else:
            agent_records = await self.agent_repo.get_all_agent_records(agentic_application_type=agentic_application_type, department_name=department_name)
        
        agent_id_to_tags = await self.tag_service.get_agent_id_to_tags_dict()

        for agent in agent_records:
            agent['system_prompt'] = json.loads(agent['system_prompt']) if isinstance(agent['system_prompt'], str) else agent['system_prompt']
            agent['tools_id'] = json.loads(agent['tools_id']) if isinstance(agent['tools_id'], str) else agent['tools_id']
            # Deserialize validation_criteria if present
            if 'validation_criteria' in agent and agent['validation_criteria'] is not None:
                agent['validation_criteria'] = json.loads(agent['validation_criteria']) if isinstance(agent['validation_criteria'], str) else agent['validation_criteria']
            agent['tags'] = agent_id_to_tags.get(agent['agentic_application_id'], [])
            # Add shared departments information
            if self.agent_sharing_repo:
                shared_info = await self.agent_sharing_repo.get_shared_departments_for_agent(agent['agentic_application_id'])
                agent['shared_with_departments'] = [info['target_department'] for info in shared_info]
            else:
                agent['shared_with_departments'] = []
        log.info(f"Retrieved {len(agent_records)} agentic applications.")
        return agent_records

    async def get_agents_by_search_or_page(self,
                                           search_value: str = '',
                                           limit: int = 20,
                                           page: int = 1,
                                           agentic_application_type: Optional[Union[str, List[str]]] = None,
                                           created_by: Optional[str] = None,
                                           tag_names: Optional[List[str]] = None,
                                           department_name: str = None) -> Dict[str, Any]:
        """
        Retrieves agents with pagination and search filtering, including associated tags.
        Includes shared and public agents when department_name is specified.

        Args:
            search_value (str, optional): Agent name to filter by.
            limit (int, optional): Number of results per page.
            page (int, optional): Page number for pagination.
            agentic_application_type (Union[List[str], str], optional): The type(s) of agentic application to filter by.
            created_by (str, optional): The email ID of the user who created the agent.

        Returns:
            dict: A dictionary containing the total count of agents and the paginated agent details.
        """
        # Get shared agent IDs if department specified
        shared_agent_ids = []
        if department_name and self.agent_sharing_repo:
            shared_agent_ids = await self.agent_sharing_repo.get_agents_shared_with_department(department_name)
        
        total_count = await self.agent_repo.get_total_agent_count(search_value, agentic_application_type, created_by, department_name, shared_agent_ids=shared_agent_ids)

        if tag_names:
            tag_names = set(tag_names)
            agent_records = await self.agent_repo.get_agents_by_search_or_page_records(search_value, total_count, 1, agentic_application_type, created_by, department_name, shared_agent_ids=shared_agent_ids)
        else:
            agent_records = await self.agent_repo.get_agents_by_search_or_page_records(search_value, limit, page, agentic_application_type, created_by, department_name, shared_agent_ids=shared_agent_ids)

        filtered_agents = []

        if tag_names:
            # Only fetch tags if tag filtering is needed
            agent_id_to_tags = await self.tag_service.get_agent_id_to_tags_dict()
            for agent in agent_records:
                agent['tags'] = agent_id_to_tags.get(agent['agentic_application_id'], [])
                for tag in agent['tags']:
                    if tag['tag_name'] in tag_names:
                        filtered_agents.append(agent)
                        break
            total_count = len(filtered_agents)
            offset = limit * max(0, page - 1)
            filtered_agents = filtered_agents[offset: offset + limit]
        else:
            # No tag filtering needed, use agent_records directly
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
            # Deserialize validation_criteria if present
            if 'validation_criteria' in agent and agent['validation_criteria'] is not None:
                agent['validation_criteria'] = json.loads(agent['validation_criteria']) if isinstance(agent['validation_criteria'], str) else agent['validation_criteria']
            agent['tags'] = agent_id_to_tags.get(agent['agentic_application_id'], [])
        log.info(f"Filtered {len(filtered_agents)} agents by tags: {tag_ids or tag_names}.")
        return filtered_agents

    async def get_agent_details_studio(self, agentic_application_id: str, department_name: str = None) -> Dict[str, Any]:
        """
        Retrieves agent details along with associated tool/worker agent information for studio display.

        Args:
            agentic_application_id (str): The agentic application ID.

        Returns:
            dict: A dictionary with agent details and associated items information.
        """
        agent_record = await self.agent_repo.get_agent_record(agentic_application_id=agentic_application_id, department_name= department_name)
        agent_record = agent_record[0] if agent_record else None
        if not agent_record:
            log.warning(f"No agentic application found with ID: {agentic_application_id}")
            return {}

        agent_details = agent_record
        agent_details['system_prompt'] = json.loads(agent_details['system_prompt']) if isinstance(agent_details['system_prompt'], str) else agent_details['system_details']
        agent_details['tools_id'] = json.loads(agent_details['tools_id']) if isinstance(agent_details['tools_id'], str) else agent_details['tools_id']
        # Deserialize validation_criteria if present
        if 'validation_criteria' in agent_details and agent_details['validation_criteria'] is not None:
            agent_details['validation_criteria'] = json.loads(agent_details['validation_criteria']) if isinstance(agent_details['validation_criteria'], str) else agent_details['validation_criteria']

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

    async def get_agents_details_for_chat(self, department_name: str = None, include_shared: bool = True) -> List[Dict[str, Any]]:
        """
        Fetches basic agent details (ID, name, type) for chat purposes.
        When department_name is specified and include_shared is True,
        also includes shared and public agents.

        Args:
            department_name (str, optional): Filter by department. If provided and include_shared=True,
                                             includes agents shared with this department and public agents.
            include_shared (bool): Whether to include shared/public agents. Defaults to True.

        Returns:
            list[dict]: A list of dictionaries, where each dictionary contains
                        'agentic_application_id', 'agentic_application_name',
                        'agentic_application_type', 'welcome_message', 'is_shared', and 'is_public_access'.
        """
        # If department specified and sharing enabled, include shared agents
        shared_agent_ids = []
        if department_name and include_shared and self.agent_sharing_repo:
            shared_agent_ids = await self.agent_sharing_repo.get_agents_shared_with_department(department_name)
        
        return await self.agent_repo.get_agents_details_for_chat_records(
            department_name=department_name,
            shared_agent_ids=shared_agent_ids,
            include_public=include_shared
        )

    async def get_agents_details_for_chat_by_user_access(self, user_email: str) -> List[Dict[str, Any]]:
        """
        Fetches basic agent details (ID, name, type) for chat purposes filtered by user access.
        Gets agents from user_agent_access table and groups table that the user has access to.

        Args:
            user_email (str): Email of the user to filter agents by

        Returns:
            list[dict]: A list of dictionaries, where each dictionary contains
                        'agentic_application_id', 'agentic_application_name',
                        and 'agentic_application_type' for agents the user has access to.
        """
        try:
            log.info(f"Fetching agents for user: {user_email}")
            
            # First, let's check what's in user_agent_access table for this user
            debug_query1 = "SELECT * FROM user_agent_access WHERE user_email = $1"
            debug_result1 = await self.agent_repo.pool.fetch(debug_query1, user_email)
            log.info(f"Direct agent access records for {user_email}: {len(debug_result1)} records")
            for record in debug_result1:
                log.info(f"  Agent access: {dict(record)}")
            
            # Check what's in groups table for this user
            debug_query2 = "SELECT * FROM groups WHERE $1 = ANY(user_emails)"
            debug_result2 = await self.agent_repo.pool.fetch(debug_query2, user_email)
            log.info(f"Group access records for {user_email}: {len(debug_result2)} records")
            for record in debug_result2:
                log.info(f"  Group: {dict(record)}")
                
            # Create a list to store all agent IDs the user has access to
            accessible_agent_ids = []
            
            # Get agent IDs from user_agent_access table
            if debug_result1:  # If user has direct access records
                for record in debug_result1:
                    agent_ids_from_access = record['agent_ids']
                    if agent_ids_from_access:
                        accessible_agent_ids.extend(agent_ids_from_access)
                        log.info(f"Added agent IDs from direct access: {agent_ids_from_access}")
            
            # Get agent IDs from groups table
            if debug_result2:  # If user belongs to groups
                for record in debug_result2:
                    agent_ids_from_group = record['agent_ids']
                    if agent_ids_from_group:
                        accessible_agent_ids.extend(agent_ids_from_group)
                        log.info(f"Added agent IDs from group: {agent_ids_from_group}")
            
            # Remove duplicates
            accessible_agent_ids = list(set(accessible_agent_ids))
            log.info(f"Total unique accessible agent IDs: {accessible_agent_ids}")
            
            if not accessible_agent_ids:
                log.info("No accessible agent IDs found, returning empty list")
                return []
            
            # Now query the agent_table for these agent IDs using ANY operator
            query = """
                SELECT agentic_application_id, agentic_application_name, agentic_application_type
                FROM agent_table
                WHERE agentic_application_id = ANY($1)
                ORDER BY created_on DESC
            """
            
            result = await self.agent_repo.pool.fetch(query, accessible_agent_ids)
            log.info(f"Final query returned {len(result)} agents for user {user_email}")
            
            agents = []
            for row in result:
                agent_dict = dict(row)
                agents.append(agent_dict)
                log.info(f"  Agent: {agent_dict}")
                
            return agents
            
        except Exception as e:
            log.error(f"Error in get_agents_details_for_chat_by_user_access: {e}")
            import traceback
            log.error(f"Traceback: {traceback.format_exc()}")
            # Return empty list on error rather than failing completely
            return []

    async def get_unused_agents(self, threshold_days: int = 0, department_name: str = None) -> List[Dict[str, Any]]:
        """
        Retrieves all agents that haven't been used for the specified number of days.
        
        Args:
            threshold_days (int): Number of days to consider an agent as unused. Default is 15.
            department_name (str, optional): Filter by department name.
        Returns:
            List[Dict[str, Any]]: A list of unused agents with their details.
        """
        try:
            # Build query with optional department_name filter
            query = f"""
                SELECT agentic_application_id, agentic_application_name, agentic_application_description, 
                       agentic_application_type, created_by, created_on, last_used
                FROM {TableNames.AGENT.value} 
                WHERE (last_used IS NULL OR last_used < (NOW() - INTERVAL '1 day' * $1))
            """
            params = [threshold_days]
            if department_name:
                query += " AND department_name = $2"
                params.append(department_name)
            query += " ORDER BY last_used ASC NULLS FIRST"

            result = await self.agent_repo.pool.fetch(query, *params)
            
            # Collect all unique created_by email addresses
            email_set = set(row.get('created_by') for row in result if row.get('created_by'))

            # Batch fetch usernames for all emails
            email_to_username = {}
            if email_set:
                email_list = list(email_set)
                async with self.agent_repo.login_pool.acquire() as conn:
                    user_rows = await conn.fetch(
                        f"SELECT mail_id, user_name FROM {TableNames.LOGIN_CREDENTIAL.value} WHERE mail_id = ANY($1)", email_list
                    )
                email_to_username = {row['mail_id']: row['user_name'] for row in user_rows}
            
            agents = []
            for row in result:
                agent_dict = dict(row)
                email = agent_dict.get('created_by')
                if email:
                    username = email_to_username.get(email)
                    if username:
                        agent_dict['created_by'] = username
                    elif '@' in email:
                        agent_dict['created_by'] = email.split('@')[0]
                agents.append(agent_dict)
                
            return agents
            
        except Exception as e:
            log.error(f"Error retrieving unused agents: {str(e)}")
            raise Exception(f"Failed to retrieve unused agents: {str(e)}")

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
        # Remove non-database fields that are added during get_agent()
        tags = agent_data.pop("tags", None)
        shared_with_departments = agent_data.pop("shared_with_departments", None)

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
                            welcome_message: str = "",
                            regenerate_system_prompt: bool = True,
                            regenerate_welcome_message: bool = True,
                            is_admin: bool = False,
                            associated_ids: List[str] = [],
                            associated_ids_to_add: List[str] = [],
                            associated_ids_to_remove: List[str] = [],
                            updated_tag_id_list: Optional[Union[str, List[str]]] = None,
                            validation_criteria: Optional[List[Dict[str, Any]]] = None,
                            knowledgebase_ids_to_add: Optional[List[str]] = None,
                            knowledgebase_ids_to_remove: Optional[List[str]] = None,
                            is_public: Optional[bool] = None,
                            shared_with_departments: Optional[List[str]] = None) -> Dict[str, Any]:
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
            welcome_message (str, optional): New welcome greeting message for the agent.
            regenerate_system_prompt (bool, optional): If True, regenerate system_prompt when description/workflow/tools change. Defaults to True.
            regenerate_welcome_message (bool, optional): If True, regenerate welcome_message when description/workflow changes. Defaults to True.
            is_admin (bool, optional): Whether the user is an admin.
            associated_ids (list, optional): New complete list of tool IDs.
            associated_ids_to_add (list, optional): Tool IDs to add.
            associated_ids_to_remove (list, optional): Tool IDs to remove.
            updated_tag_id_list (Union[List, str], optional): New list of tag IDs.
            validation_criteria (List[Dict[str, Any]], optional): List of validation test cases for the agent.
            knowledgebase_ids_to_add (List[str], optional): Knowledgebase IDs to add to the agent.
            knowledgebase_ids_to_remove (List[str], optional): Knowledgebase IDs to remove from the agent.
            is_public (bool, optional): Whether the agent should be public (accessible to all departments).
            shared_with_departments (List[str], optional): List of department names to share the agent with.

        Returns:
            dict: Status of the update operation.
        """
        agent_records = await self.get_agent(agentic_application_id=agentic_application_id, agentic_application_name=agentic_application_name)
        if not agent_records:
            log.error(f"No Agentic Application found with ID: {agentic_application_id or agentic_application_name}")
            return {"message": "Please validate the AGENTIC APPLICATION ID.", "is_update": False}
        agent = agent_records[0]
        agentic_application_id = agent["agentic_application_id"]

        # Check if any fields are provided for update
        is_meta_agent = agent["agentic_application_type"] in self.meta_type_templates
        validation_criteria_check = validation_criteria is None if not is_meta_agent else True  # Skip validation_criteria check for meta agents
        kb_check = not knowledgebase_ids_to_add and not knowledgebase_ids_to_remove  # Check if KB fields are empty
        
        # Check if is_public is being changed
        current_is_public = agent.get('is_public', False)
        is_public_changed = is_public is not None and is_public != current_is_public
        
        # Check if sharing is being updated
        sharing_changed = shared_with_departments is not None
        
        if not agentic_application_description and not agentic_application_workflow_description and not system_prompt and not welcome_message and not associated_ids and not associated_ids_to_add and not associated_ids_to_remove and updated_tag_id_list is None and validation_criteria_check and not is_public_changed and not sharing_changed:
            log.error("No fields provided to update the agentic application.")
            return {"message": "Error: Please specify at least one field to modify.", "is_update": False}

        if not is_admin and agent["created_by"] != created_by:
            log.error(f"Permission denied: User {created_by} is not authorized to update Agentic Application ID: {agent['agentic_application_id']}.")
            return {"message": f"You do not have permission to update Agentic Application: {agent['agentic_application_name']}.", "is_update": False}

        tag_status = None
        if updated_tag_id_list is not None:
            await self.tag_service.clear_tags(agent_id=agentic_application_id)
            tag_status = await self.tag_service.assign_tags_to_agent(tag_ids=updated_tag_id_list, agentic_application_id=agentic_application_id)

        # Handle is_public and sharing updates
        sharing_update_status = None
        
        # Get agent's tools info for cascade sharing (needed for both public and shared scenarios)
        # Separate regular tools and MCP tools
        tools_info = []
        mcp_tools_info = []
        if not is_meta_agent:
            tools_id_raw = agent.get('tools_id', '[]')
            current_tools_id = tools_id_raw if isinstance(tools_id_raw, list) else json.loads(tools_id_raw)
            for tool_id in current_tools_id:
                if tool_id.startswith("mcp_"):
                    # MCP tool - fetch from MCP tool service
                    mcp_tool_data = await self.mcp_tool_service.get_mcp_tool(tool_id=tool_id)
                    if mcp_tool_data:
                        mcp_tools_info.append({
                            'tool_id': mcp_tool_data[0]['tool_id'],
                            'tool_name': mcp_tool_data[0].get('tool_name', ''),
                            'department_name': mcp_tool_data[0].get('department_name', agent.get('department_name', ''))
                        })
                else:
                    # Regular tool - fetch from tool service
                    tool_data = await self.tool_service.get_tool(tool_id=tool_id)
                    if tool_data:
                        tools_info.append({
                            'tool_id': tool_data[0]['tool_id'],
                            'tool_name': tool_data[0].get('tool_name', ''),
                            'department_name': tool_data[0].get('department_name', agent.get('department_name', ''))
                        })
        
        # If setting is_public=true, sharing is redundant - skip shared_with_departments
        if is_public_changed and is_public and self.agent_sharing_repo:
            if shared_with_departments:
                log.info(f"Agent '{agent['agentic_application_name']}' is being set to public, ignoring shared_with_departments")
                sharing_update_status = {"message": "Agent is public, shared_with_departments ignored"}
                sharing_changed = False  # Skip further sharing processing
        
        # Gather KB info for cascade sharing/public (needed for both public and shared scenarios)
        kbs_info = []
        if (is_public_changed or sharing_changed) and self.knowledgebase_service:
            try:
                kb_ids = await self.knowledgebase_service.agent_kb_mapping_repo.get_knowledgebase_ids_for_agent(agentic_application_id)
                for kb_id in kb_ids:
                    kb_record = await self.knowledgebase_service.knowledgebase_repo.get_knowledgebase_by_id(kb_id)
                    if kb_record:
                        kbs_info.append({
                            'kb_id': kb_id,
                            'kb_name': kb_record.get('knowledgebase_name', ''),
                            'department_name': kb_record.get('department_name', agent.get('department_name', ''))
                        })
            except Exception as e:
                log.warning(f"Failed to gather KB info for cascade sharing during update: {e}")
        
        if is_public_changed or sharing_changed:
            # Update is_public in agent record if changed
            if is_public_changed:
                agent["is_public"] = is_public
                await self.agent_repo.update_agent_record({"is_public": is_public}, agentic_application_id)
                log.info(f"Updated is_public to {is_public} for agent: {agent['agentic_application_name']}")
                
                # If agent is made public, also make its tools public (both regular and MCP)
                if is_public and tools_info:
                    for tool in tools_info:
                        try:
                            await self.tool_service.tool_repo.update_tool_record({"is_public": True}, tool['tool_id'])
                            log.info(f"Made tool '{tool['tool_name']}' public (cascade from public agent)")
                        except Exception as e:
                            log.warning(f"Failed to make tool '{tool['tool_id']}' public: {e}")
                
                if is_public and mcp_tools_info:
                    for mcp_tool in mcp_tools_info:
                        try:
                            await self.mcp_tool_service.mcp_tool_repo.update_mcp_tool_record({"is_public": True}, mcp_tool['tool_id'])
                            log.info(f"Made MCP tool '{mcp_tool['tool_name']}' public (cascade from public agent)")
                        except Exception as e:
                            log.warning(f"Failed to make MCP tool '{mcp_tool['tool_id']}' public: {e}")
                
                # If agent is made public, also make its knowledge bases public
                if is_public and kbs_info:
                    for kb in kbs_info:
                        try:
                            await self.knowledgebase_service.knowledgebase_repo.update_kb_visibility(kb['kb_id'], True)
                            log.info(f"Made KB '{kb['kb_name']}' public (cascade from public agent)")
                        except Exception as e:
                            log.warning(f"Failed to make KB '{kb['kb_id']}' public: {e}")
            
            # Handle sharing update (with department validation)
            if sharing_changed and self.agent_sharing_repo:
                try:
                    # Validate new departments exist
                    valid_new_depts = []
                    invalid_departments = []
                    if shared_with_departments and self.department_repo:
                        for dept_name in shared_with_departments:
                            dept = await self.department_repo.get_department_by_name(dept_name)
                            if dept:
                                valid_new_depts.append(dept_name)
                            else:
                                invalid_departments.append(dept_name)
                        if invalid_departments:
                            log.warning(f"Invalid department names provided for sharing: {invalid_departments}")
                    elif shared_with_departments:
                        valid_new_depts = shared_with_departments
                    
                    # Get current sharing state
                    current_shared_info = await self.agent_sharing_repo.get_shared_departments_for_agent(agentic_application_id)
                    current_shared_set = set(d['target_department'] for d in current_shared_info) if isinstance(current_shared_info, list) and current_shared_info and isinstance(current_shared_info[0], dict) else set(current_shared_info) if current_shared_info else set()
                    new_shared_set = set(valid_new_depts) if valid_new_depts else set()
                    
                    # Departments to add (only valid ones)
                    depts_to_add = new_shared_set - current_shared_set
                    # Departments to remove
                    depts_to_remove = current_shared_set - new_shared_set
                    
                    added_depts = []
                    removed_depts = []
                    
                    # Remove sharing from departments no longer in the list
                    for dept in depts_to_remove:
                        try:
                            await self.agent_sharing_repo.unshare_agent_from_department(agentic_application_id, dept)
                            removed_depts.append(dept)
                        except Exception as e:
                            log.warning(f"Failed to unshare agent from department {dept}: {e}")
                    
                    # Add sharing to new departments
                    if depts_to_add:
                        share_result = await self.agent_sharing_repo.share_agent_with_multiple_departments(
                            agentic_application_id=agentic_application_id,
                            agentic_application_name=agent['agentic_application_name'],
                            source_department=agent.get('department_name', ''),
                            target_departments=list(depts_to_add),
                            shared_by=created_by or '',
                            tools_info=tools_info,  # Pass regular tools for cascade sharing
                            mcp_tools_info=mcp_tools_info,  # Pass MCP tools for cascade sharing
                            kbs_info=kbs_info  # Pass knowledge bases for cascade sharing
                        )
                        added_depts = list(depts_to_add)[:share_result.get("success_count", 0)]
                    
                    sharing_update_status = {
                        "added": added_depts,
                        "removed": removed_depts,
                        "current_shared_with": list(new_shared_set),
                        "invalid_departments": invalid_departments if invalid_departments else [],
                        "tools_shared": share_result.get("total_tools_shared", 0) if depts_to_add else 0,
                        "mcp_tools_shared": share_result.get("total_mcp_tools_shared", 0) if depts_to_add else 0,
                        "kbs_shared": share_result.get("total_kbs_shared", 0) if depts_to_add else 0
                    }
                    log.info(f"Updated sharing for agent '{agent['agentic_application_name']}': added={added_depts}, removed={removed_depts}")
                except Exception as share_error:
                    log.warning(f"Failed to update agent sharing: {share_error}")
                    sharing_update_status = {"error": str(share_error)}

        if not agentic_application_description and not agentic_application_workflow_description and not system_prompt and not welcome_message and not associated_ids and not associated_ids_to_add and not associated_ids_to_remove and validation_criteria_check and kb_check:
            log.info("Tags/sharing updated successfully. No other fields modified.")
            result = {"message": "Agent updated successfully", "is_update": True}
            if tag_status:
                result["tag_update_status"] = tag_status
            if sharing_update_status:
                result["sharing_update_status"] = sharing_update_status
            if is_public_changed:
                result["is_public"] = is_public
            return result

        associated_ids_to_check = associated_ids + associated_ids_to_add + associated_ids_to_remove
        is_meta_template = agent['agentic_application_type'] in self.meta_type_templates
        if is_meta_template:
            valid_associated_ids_resp= await self.validate_agent_ids(agents_id=associated_ids_to_check)
        else:
            valid_associated_ids_resp = await self.tool_service.validate_tools(tools_id=associated_ids_to_check)

        if "error" in valid_associated_ids_resp:
            log.error(f"{'Worker agent' if is_meta_template else 'Tool'} validation failed: {valid_associated_ids_resp['error']}")
            return {"message": valid_associated_ids_resp["error"], "is_update": False}

        if agentic_application_description:
            agent["agentic_application_description"] = agentic_application_description
        if agentic_application_workflow_description:
            agent["agentic_application_workflow_description"] = agentic_application_workflow_description
        
        # Only use provided system_prompt if regenerate_system_prompt is False
        if not regenerate_system_prompt and system_prompt:
            agent["system_prompt"] = {**agent.get("system_prompt", {}), **system_prompt}
        
        # Only use provided welcome_message if regenerate_welcome_message is False
        if not regenerate_welcome_message and welcome_message:
            agent["welcome_message"] = welcome_message

        current_associated_ids_set = set(agent.get("tools_id", []))
        if associated_ids:
            current_associated_ids_set = set(associated_ids)
        if associated_ids_to_add:
            current_associated_ids_set.update(associated_ids_to_add)
        if associated_ids_to_remove:
            current_associated_ids_set.difference_update(associated_ids_to_remove)
        agent["tools_id"] = list(current_associated_ids_set)
        agent["model_name"] = model_name
        
        # Only update validation_criteria for non-meta agents
        if agent["agentic_application_type"] not in self.meta_type_templates and validation_criteria is not None:
            agent["validation_criteria"] = validation_criteria

        # Generate tool_prompt if either system_prompt or welcome_message needs to be regenerated
        tool_or_worker_agents_prompt = None
        if regenerate_system_prompt or regenerate_welcome_message:
            if is_meta_template:
                worker_agents_prompt = await self.generate_worker_agents_prompt(agents_id=agent["tools_id"])
                tool_or_worker_agents_prompt = worker_agents_prompt
            else:
                tool_prompt = await self.tool_service.generate_tool_prompt(agent["tools_id"])
                tool_or_worker_agents_prompt = tool_prompt

        # Regenerate system prompt and/or welcome message
        # Run in parallel when both need to be regenerated
        if regenerate_system_prompt and regenerate_welcome_message:
            llm = await self._get_llm_model(model_name=model_name, temperature=0.0)
            agent['system_prompt'], agent['welcome_message'] = await asyncio.gather(
                self._generate_system_prompt(
                    agent_name=agent["agentic_application_name"],
                    agent_goal=agent["agentic_application_description"],
                    workflow_description=agent["agentic_application_workflow_description"],
                    tool_or_worker_agents_prompt=tool_or_worker_agents_prompt,
                    llm=llm
                ),
                self._get_welcome_message_for_agent(
                    agent_name=agent["agentic_application_name"],
                    agent_goal=agent["agentic_application_description"],
                    workflow_description=agent["agentic_application_workflow_description"],
                    agent_type=agent["agentic_application_type"],
                    model_name=model_name,
                    tool_prompt=tool_or_worker_agents_prompt or ""
                )
            )
        elif regenerate_system_prompt:
            llm = await self._get_llm_model(model_name=model_name, temperature=0.0)
            agent['system_prompt'] = await self._generate_system_prompt(
                agent_name=agent["agentic_application_name"],
                agent_goal=agent["agentic_application_description"],
                workflow_description=agent["agentic_application_workflow_description"],
                tool_or_worker_agents_prompt=tool_or_worker_agents_prompt,
                llm=llm
            )
        elif regenerate_welcome_message:
            agent['welcome_message'] = await self._get_welcome_message_for_agent(
                agent_name=agent["agentic_application_name"],
                agent_goal=agent["agentic_application_description"],
                workflow_description=agent["agentic_application_workflow_description"],
                agent_type=agent["agentic_application_type"],
                model_name=model_name,
                tool_prompt=tool_or_worker_agents_prompt or ""
            )

        agent['system_prompt'] = json.dumps(agent['system_prompt'])
        agent['tools_id'] = json.dumps(agent['tools_id'])
        
        # Serialize validation_criteria if present
        if 'validation_criteria' in agent and agent['validation_criteria'] is not None:
            agent['validation_criteria'] = json.dumps(agent['validation_criteria'])
        
        success = await self._update_agent_data_util(agent_data=agent, agentic_application_id=agentic_application_id)
        
        # Handle knowledgebase updates
        if success and self.knowledgebase_service:
            try:
                agent_department = agent.get("department_name")
                
                if knowledgebase_ids_to_add:
                    # Validate that KB IDs exist and belong to the agent's department
                    kb_validation = await self.knowledgebase_service.validate_knowledgebase_ids(
                        knowledgebase_ids=knowledgebase_ids_to_add,
                        department_name=agent_department
                    )
                    if "error" in kb_validation:
                        log.warning(f"KB validation failed during update for agent '{agentic_application_id}': {kb_validation['error']}")
                        status = {"message": kb_validation["error"], "is_update": False}
                        return status
                    
                    await self.knowledgebase_service.add_knowledgebases_to_agent(
                        agentic_application_id=agentic_application_id,
                        knowledgebase_ids=knowledgebase_ids_to_add
                    )
                    log.info(f"Added {len(knowledgebase_ids_to_add)} knowledgebases to agent {agentic_application_id}")
                
                if knowledgebase_ids_to_remove:
                    await self.knowledgebase_service.remove_knowledgebases_from_agent(
                        agentic_application_id=agentic_application_id,
                        knowledgebase_ids=knowledgebase_ids_to_remove
                    )
                    log.info(f"Removed {len(knowledgebase_ids_to_remove)} knowledgebases from agent {agentic_application_id}")
            except Exception as e:
                log.warning(f"Failed to update knowledgebases for agent {agentic_application_id}: {e}")
        
        # Cascade public/sharing to NEWLY ADDED tools, MCP tools, and KBs
        # This handles the case where agent is already public or shared and user swaps tools/KBs
        if success and not is_meta_agent:
            effective_is_public = is_public if is_public is not None else current_is_public
            
            # Determine which tools/KBs were newly added
            newly_added_tool_ids = set()
            if associated_ids:
                # Full replacement: new tools = final set minus what was there before
                old_tools_set = set(tools_id_raw if isinstance(tools_id_raw, list) else json.loads(tools_id_raw)) if tools_id_raw else set()
                newly_added_tool_ids = set(associated_ids) - old_tools_set
            elif associated_ids_to_add:
                newly_added_tool_ids = set(associated_ids_to_add)
            
            newly_added_kb_ids = set(knowledgebase_ids_to_add) if knowledgebase_ids_to_add else set()
            
            if newly_added_tool_ids or newly_added_kb_ids:
                # Gather info for newly added tools
                new_tools_info = []
                new_mcp_tools_info = []
                for tool_id in newly_added_tool_ids:
                    if tool_id.startswith("mcp_"):
                        mcp_tool_data = await self.mcp_tool_service.get_mcp_tool(tool_id=tool_id)
                        if mcp_tool_data:
                            new_mcp_tools_info.append({
                                'tool_id': mcp_tool_data[0]['tool_id'],
                                'tool_name': mcp_tool_data[0].get('tool_name', ''),
                                'department_name': mcp_tool_data[0].get('department_name', agent.get('department_name', ''))
                            })
                    else:
                        tool_data = await self.tool_service.get_tool(tool_id=tool_id)
                        if tool_data:
                            new_tools_info.append({
                                'tool_id': tool_data[0]['tool_id'],
                                'tool_name': tool_data[0].get('tool_name', ''),
                                'department_name': tool_data[0].get('department_name', agent.get('department_name', ''))
                            })
                
                # Gather info for newly added KBs
                new_kbs_info = []
                for kb_id in newly_added_kb_ids:
                    try:
                        kb_record = await self.knowledgebase_service.knowledgebase_repo.get_knowledgebase_by_id(kb_id)
                        if kb_record:
                            new_kbs_info.append({
                                'kb_id': kb_id,
                                'kb_name': kb_record.get('knowledgebase_name', ''),
                                'department_name': kb_record.get('department_name', agent.get('department_name', ''))
                            })
                    except Exception:
                        pass
                
                # If agent is public, make newly added items public
                if effective_is_public:
                    for tool in new_tools_info:
                        try:
                            await self.tool_service.tool_repo.update_tool_record({"is_public": True}, tool['tool_id'])
                            log.info(f"Made newly added tool '{tool['tool_name']}' public (agent is public)")
                        except Exception as e:
                            log.warning(f"Failed to make newly added tool '{tool['tool_id']}' public: {e}")
                    
                    for mcp_tool in new_mcp_tools_info:
                        try:
                            await self.mcp_tool_service.mcp_tool_repo.update_mcp_tool_record({"is_public": True}, mcp_tool['tool_id'])
                            log.info(f"Made newly added MCP tool '{mcp_tool['tool_name']}' public (agent is public)")
                        except Exception as e:
                            log.warning(f"Failed to make newly added MCP tool '{mcp_tool['tool_id']}' public: {e}")
                    
                    for kb in new_kbs_info:
                        try:
                            await self.knowledgebase_service.knowledgebase_repo.update_kb_visibility(kb['kb_id'], True)
                            log.info(f"Made newly added KB '{kb['kb_name']}' public (agent is public)")
                        except Exception as e:
                            log.warning(f"Failed to make newly added KB '{kb['kb_id']}' public: {e}")
                
                # If agent is shared with departments, share newly added items too
                elif not effective_is_public and self.agent_sharing_repo:
                    try:
                        shared_depts_info = await self.agent_sharing_repo.get_shared_departments_for_agent(agentic_application_id)
                        shared_depts = [d['target_department'] for d in shared_depts_info] if isinstance(shared_depts_info, list) and shared_depts_info and isinstance(shared_depts_info[0], dict) else list(shared_depts_info) if shared_depts_info else []
                        
                        if shared_depts:
                            agent_department = agent.get('department_name', '')
                            
                            # Share newly added regular tools with departments
                            if new_tools_info and self.tool_service.tool_sharing_repo:
                                for tool in new_tools_info:
                                    for dept in shared_depts:
                                        try:
                                            await self.tool_service.tool_sharing_repo.share_tool_with_department(
                                                tool_id=tool['tool_id'],
                                                tool_name=tool['tool_name'],
                                                source_department=tool.get('department_name', agent_department),
                                                target_department=dept,
                                                shared_by=created_by or ''
                                            )
                                        except Exception as e:
                                            log.warning(f"Failed to share newly added tool '{tool['tool_id']}' with dept '{dept}': {e}")
                            
                            # Share newly added MCP tools with departments
                            if new_mcp_tools_info and self.mcp_tool_service.mcp_tool_sharing_repo:
                                for mcp_tool in new_mcp_tools_info:
                                    for dept in shared_depts:
                                        try:
                                            await self.mcp_tool_service.mcp_tool_sharing_repo.share_mcp_tool_with_department(
                                                tool_id=mcp_tool['tool_id'],
                                                tool_name=mcp_tool['tool_name'],
                                                source_department=mcp_tool.get('department_name', agent_department),
                                                target_department=dept,
                                                shared_by=created_by or ''
                                            )
                                        except Exception as e:
                                            log.warning(f"Failed to share newly added MCP tool '{mcp_tool['tool_id']}' with dept '{dept}': {e}")
                            
                            # Share newly added KBs with departments
                            if new_kbs_info and self.knowledgebase_service and self.knowledgebase_service.kb_sharing_repo:
                                for kb in new_kbs_info:
                                    for dept in shared_depts:
                                        try:
                                            await self.knowledgebase_service.kb_sharing_repo.share_kb_with_department(
                                                knowledgebase_id=kb['kb_id'],
                                                knowledgebase_name=kb['kb_name'],
                                                source_department=kb.get('department_name', agent_department),
                                                target_department=dept,
                                                shared_by=created_by or ''
                                            )
                                        except Exception as e:
                                            log.warning(f"Failed to share newly added KB '{kb['kb_id']}' with dept '{dept}': {e}")
                            
                            log.info(f"Cascaded sharing to newly added items for agent '{agentic_application_id}' across {len(shared_depts)} departments")
                    except Exception as e:
                        log.warning(f"Failed to cascade sharing to newly added items: {e}")
        
        if success:
            log.info(f"Successfully updated Agentic Application with ID: {agentic_application_id}.")
            status = {"message": f"Successfully updated Agent: {agent['agentic_application_name']}.", "is_update": True}
        else:
            log.error(f"Failed to update Agentic Application with ID: {agentic_application_id}.")
            status = {"message": "Failed to update the Agentic Application.", "is_update": False}
        
        if tag_status:
            status['tag_update_status'] = tag_status
        if sharing_update_status:
            status['sharing_update_status'] = sharing_update_status
        if is_public_changed:
            status['is_public'] = is_public
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
            return {"message": "Error: Must provide 'agentic_application_id' or 'agentic_application_name' to delete an agentic application.", "is_delete": False}

        # Retrieve agent data from the main table
        agent_data = await self.agent_repo.get_agent_record(agentic_application_id=agentic_application_id, agentic_application_name=agentic_application_name)
        
        if not agent_data:
            log.error(f"No Agentic Application found with ID: {agentic_application_id or agentic_application_name}")
            return {"message": f"No Agentic Application available with ID: {agentic_application_id or agentic_application_name}", "is_delete": False}
        agent_data = agent_data[0]

        # Check permissions
        if not is_admin and agent_data["created_by"] != user_id:
            log.error(f"Permission denied: User {user_id} is not authorized to delete Agentic Application ID: {agent_data['agentic_application_id']}.")
            return {
                "message": f"You do not have permission to delete Agentic Application with ID: {agent_data['agentic_application_name']}.",
                "details": [],
                "is_delete": False
            }

        # Check if this agent is used as a worker agent by any meta-agent ---
        agent_to_delete_id = agent_data['agentic_application_id']
        
        # Get all meta-agents and planner-meta-agents
        meta_agents = await self.agent_repo.get_all_agent_records(agentic_application_type=self.meta_type_templates)

        pipelines = await self.agent_pipeline_mapping_repo.get_agent_pipeline_mappings_record(agentic_application_id=agentic_application_id)

        dependent_meta_agents_details = []

        for meta_agent in meta_agents:
            # tools_id for meta-agents stores worker agent IDs (JSONB, so already a list/Python object)
            worker_agent_ids = meta_agent.get('tools_id', []) 
            if agent_to_delete_id in worker_agent_ids:
                dependent_meta_agents_details.append({
                    "agentic_application_id": meta_agent['agentic_application_id'],
                    "agentic_application_name": meta_agent['agentic_application_name'],
                    "agentic_application_created_by": meta_agent['created_by']
                })

        for pipeline in pipelines:
            pipeline_id = pipeline.get('pipeline_id')
            pipeline_name = pipeline.get('pipeline_name')
            pipeline_created_by = pipeline.get('pipeline_created_by')

            dependent_meta_agents_details.append({
                "agentic_application_id": pipeline_id,
                "agentic_application_name": pipeline_name + " PipeLine",
                "agentic_application_created_by": pipeline_created_by
            })

        if dependent_meta_agents_details:
            log.error(f"Agent deletion failed: Agent {agent_data['agentic_application_name']} is being used as a worker agent by {len(dependent_meta_agents_details)} other meta-agent(s).")
            return {
                "message": f"The agent you are trying to delete is being referenced as a worker agent by {len(dependent_meta_agents_details)} other agentic application(s).",
                "details": dependent_meta_agents_details,
                "is_delete": False
            }

        # Move to recycle bin
        recycle_success = await self.recycle_agent_repo.insert_recycle_agent_record(agent_data)
        if not recycle_success:
            log.error(f"Failed to move Agentic Application {agent_data['agentic_application_id']} to recycle bin.")
            return {"message": f"Failed to move agent {agent_data['agentic_application_name']} to recycle bin.", "is_delete": False}

        # Clean up mappings
        # This removes mappings where the deleted agent was a TOOL/WORKER_AGENT for others
        await self.tool_service.tool_agent_mapping_repo.remove_tool_from_agent_record(agentic_application_id=agent_data['agentic_application_id'])
        # This removes mappings where the deleted agent had TAGS
        await self.tag_service.clear_tags(agent_id=agent_data['agentic_application_id'])

        # Delete from main table
        delete_success = await self.agent_repo.delete_agent_record(agent_data['agentic_application_id'])

        if delete_success:
            log.info(f"Successfully deleted Agentic Application with ID: {agent_data['agentic_application_id']}.")
            return {"message": f"Successfully deleted Agentic Application: {agent_data['agentic_application_name']}.", "is_delete": True}
        else:
            log.error(f"Failed to delete Agentic Application {agent_data['agentic_application_id']} from main table.")
            return {"message": f"Failed to delete Agentic Application {agent_data['agentic_application_name']} from main table.", "is_delete": False}

    # --- Agent Helper Functions ---

    async def get_available_templates(self):
        """
        Returns the list of available agent templates.
        """
        return [agent_type.value for agent_type in AgentType]

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

    async def generate_worker_agents_prompt(self, agents_id: List[str], include_memory_tools: bool = True):
        """
        Generates worker agents prompt for the meta type agent describing the available agents.
        
        Args:
            agents_id (List[str]): List of worker agent IDs.
            include_memory_tools (bool): Whether to include memory tool info in the prompt. Default is True.
        
        Returns:
            str: A prompt string describing the worker agents.
        """
        worker_agents_prompt = ""
        
        if include_memory_tools:
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
            worker_agents_prompt = f"{memory_tool_data}\n\n\n\n"
        
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

    async def _get_llm_model(self, model_name: str, temperature: float = 0):
        """
        Retrieves the LLM model instance for the specified model name and temperature.
        """
        return await self.model_service.get_llm_model(model_name=model_name, temperature=temperature)

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
            tool_or_worker_agents_prompt = None
            if is_meta_template:
                worker_agents_prompt = await self.generate_worker_agents_prompt(agents_id=associated_ids)
                tool_or_worker_agents_prompt = worker_agents_prompt
            else:
                tool_prompt = await self.tool_service.generate_tool_prompt(tools_id=associated_ids)
                tool_or_worker_agents_prompt = tool_prompt

            llm = await self._get_llm_model(model_name=model_name, temperature=0.0)
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

    async def _get_welcome_message_for_agent(self,
                                              agent_name: str,
                                              agent_goal: str,
                                              workflow_description: str,
                                              agent_type: str,
                                              model_name: str,
                                              tool_prompt: str = "") -> str:
        """
        Asynchronously generates a welcome greeting message for an agent.
        
        Args:
            agent_name (str): The name of the agent.
            agent_goal (str): The goal or objective of the agent.
            workflow_description (str): The workflow description of the agent.
            agent_type (str): The type of the agent.
            model_name (str): The name of the language model to use for message generation.
            tool_prompt (str): The tool/capabilities prompt describing available tools.
            
        Returns:
            str: The generated welcome message, or a fallback message if generation fails.
        """
        try:
            llm = await self._get_llm_model(model_name=model_name, temperature=0.7)
            welcome_message = await self._generate_welcome_message(
                agent_name=agent_name,
                agent_goal=agent_goal,
                workflow_description=workflow_description,
                agent_type=agent_type,
                tool_prompt=tool_prompt,
                llm=llm
            )
            log.info(f"Successfully generated welcome message for agent '{agent_name}'.")
            return welcome_message
        except Exception as e:
            log.error(f"Error generating welcome message: {str(e)}. Using fallback message.")
            return "Hello, how can I help you?"

    # Method to generate welcome message for agent
    async def _generate_welcome_message(self, agent_name: str, agent_goal: str, workflow_description: str, agent_type: str, tool_prompt: str, llm) -> str:
        """
        Generates a welcome greeting message for an agent using LLM.
        Can be overridden in subclasses for custom behavior.
        
        Args:
            agent_name (str): The name of the agent.
            agent_goal (str): The goal or objective of the agent.
            workflow_description (str): The workflow description of the agent.
            agent_type (str): The type of the agent.
            tool_prompt (str): The tool/capabilities prompt describing available tools.
            llm: The language model to use for generation.
            
        Returns:
            str: The generated welcome message.
        """
        from langchain.prompts import PromptTemplate
        from langchain_core.output_parsers.string import StrOutputParser
        from src.prompts.prompts import welcome_message_generator
        
        welcome_message_template = PromptTemplate.from_template(welcome_message_generator)
        welcome_message_chain = welcome_message_template | llm | StrOutputParser()
        
        welcome_message = await welcome_message_chain.ainvoke({
            "agent_name": agent_name,
            "agent_goal": agent_goal,
            "workflow_description": workflow_description,
            "agent_type": agent_type.replace("_", " ").title(),
            "tool_prompt": tool_prompt if tool_prompt else "No specific tools available."
        })
        
        # Clean up the message - remove quotes and extra whitespace
        welcome_message = welcome_message.strip().strip('"').strip("'")
        return welcome_message

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

    async def get_all_agents_from_recycle_bin(self, department_name: str = None) -> List[Dict[str, Any]]:
        """
        Retrieves all agents from the recycle bin.

        Returns:
            list: A list of dictionaries representing the agents in the recycle bin.
        """
        return await self.recycle_agent_repo.get_all_recycle_agent_records(department_name=department_name)

    async def restore_agent(self, agentic_application_id: Optional[str] = None, agentic_application_name: Optional[str] = None, department_name: str = None) -> Dict[str, Any]:
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
                "message": "Error: Must provide 'agentic_application_id' or 'agentic_application_name' to restore an agent.",
                "is_restored": False
            }

        agent_data = await self.recycle_agent_repo.get_recycle_agent_record(agentic_application_id=agentic_application_id, agentic_application_name=agentic_application_name, department_name= department_name)
        if not agent_data:
            log.error(f"No Agentic Application found in recycle bin with ID: {agentic_application_id or agentic_application_name}")
            return {
                "message": f"No Agentic Application available in recycle bin with ID: {agentic_application_id or agentic_application_name}",
                "is_restored": False
            }

        # Delete from recycle bin first
        delete_success = await self.recycle_agent_repo.delete_recycle_agent_record(agent_data['agentic_application_id'])
        if not delete_success:
            log.error(f"Failed to delete agent {agent_data['agentic_application_id']} from recycle bin.")
            return {
                "message": f"Failed to delete agent {agent_data['agentic_application_id']} from recycle bin.",
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
                "message": f"Failed to restore agent {agent_data['agentic_application_id']} to main table (might already exist).",
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
            "message": f"Successfully restored Agentic Application with ID: {agent_data['agentic_application_id']}",
            "is_restored": True
        }

    async def delete_agent_from_recycle_bin(self, agentic_application_id: Optional[str] = None, agentic_application_name: Optional[str] = None, department_name: str = None) -> Dict[str, Any]:
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
                "message": "Error: Must provide 'agentic_application_id' or 'agentic_application_name' to permanently delete an agent from recycle bin.",
                "is_delete": False
            }

        agent_data = await self.recycle_agent_repo.get_recycle_agent_record(agentic_application_id=agentic_application_id, agentic_application_name=agentic_application_name, department_name= department_name)
        if not agent_data:
            log.error(f"No Agentic Application found in recycle bin with ID: {agentic_application_id or agentic_application_name}")
            return {"message": f"No Agentic Application available in recycle bin with ID: {agentic_application_id or agentic_application_name}", "is_delete": False}

        success = await self.recycle_agent_repo.delete_recycle_agent_record(agent_data['agentic_application_id'])
        if success:
            log.info(f"Successfully deleted Agentic Application from recycle bin with ID: {agent_data['agentic_application_id']}")
            return {"message": f"Successfully deleted Agentic Application from recycle bin with ID: {agent_data['agentic_application_id']}.", "is_delete": True}
        else:
            log.error(f"Failed to delete agent {agent_data['agentic_application_id']} from recycle bin.")
            return {"message": f"Failed to delete agent {agent_data['agentic_application_id']} from recycle bin.", "is_delete": False}

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
                "message": f"Successfully approved agent with ID: {agentic_application_id}",
                "agentic_application_id": agentic_application_id,
                "approved_by": approved_by,
                "is_approved": True
            }
        else:
            log.error(f"Failed to approve agent with ID: {agentic_application_id}")
            return {
                "message": f"Failed to approve agent with ID: {agentic_application_id}",
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
        
    async def get_tools_or_agents_mapped_to_agent(self, agentic_application_id: str) -> List[Dict[str, Any]]:
        """
        Retrieves all tools or worker agents mapped to a specific agent.
        For meta/planner-meta agents, returns worker agent names.
        For other agents, returns tool names.

        Args:
            agentic_application_id (str): The ID of the agent.

        Returns:
            list: A list of tool names or worker agent names mapped to the agent.
        """
        # First, get the agent type
        agent_records = await self.get_agent_details_studio(agentic_application_id=agentic_application_id)
        names = []
        mcp_tool_ids = []
        if agent_records["agentic_application_type"] in self.meta_type_templates:
            # It's a meta agent, return worker agent names
            for worker_agent in agent_records["tools_id"]:
                names.append(await AgentServiceUtils._normalize_agent_name(worker_agent["agentic_application_name"]))
            return names

        for tools in agent_records["tools_id"]:
            if tools["tool_id"].startswith('mcp_'):
                mcp_tool_ids.append(tools["tool_id"])
            else:
                names.append(tools["tool_name"])
        # Fetch MCP tool names
        mcp_tools = await self.mcp_tool_service.get_live_mcp_tools_from_servers(mcp_tool_ids)
        for mcp_tool in mcp_tools["all_live_tools"]:
            names.append(mcp_tool.name)
        return names 

    # --- New Migration Function For agent Id ---
    async def migrate_agent_ids_and_references(self) -> Dict[str, Any]:
        """
        Orchestrates the migration of agent IDs and all their references across the database.
        This function handles:
        1. Updating agentic_application_id in agent_table to the new `{agent_code}_{uuid}` format.
        2. Updating references in tag_agentic_app_mapping_table.
        3. Updating references in tool_agent_mapping_table (both as agentic_application_id and tool_id).
        4. Renaming long-term memory tables (e.g., `table_old_id` to `table_new_id`).
        5. Updating thread_id in short-term memory tables (checkpoints, checkpoint_blobs, checkpoint_writes).
        6. Updating references in agent_feedback table.
        7. Updating references in export_agent table.
        8. Updating references in evaluation_data table.
        9. Updating references in agent_chat_state_history_table (for Python-based agents).
        10. Independently updating agent IDs in the recycle_agent table.
        11. Updating the `tools_id` (worker agent IDs) column within the `agent_table` itself for meta-agents.
        """
        import os, asyncpg
        from src.database.database_manager import REQUIRED_DATABASES
        log.info("Starting agent ID migration process...")
        
        migration_summary = {
            "active_agents_updated": 0,
            "recycled_agents_updated": 0,
            "tag_mappings_updated": 0,
            "tool_mappings_updated": 0,
            "long_term_memory_tables_renamed": 0,
            "short_term_memory_langgraph_threads_updated": 0,
            "agent_feedback_updated": 0,
            "export_agent_updated": 0,
            "evaluation_data_updated": 0,
            "python_agent_history_updated": 0,
            "agent_internal_tools_id_updated": 0,
            "failed_migrations": []
        }

        active_agent_id_map: Dict[str, str] = {} # old_id -> new_id for active agents
        recycled_agent_id_map: Dict[str, str] = {} # old_id -> new_id for recycled agents
        agent_type_map: Dict[str, str] = {} # new_id -> agent_type (for all agents)
        
        # Store original agent records to access tools_id before primary key update
        original_active_agent_records: Dict[str, Dict[str, Any]] = {}

        # --- Database Connection Details (from environment) ---
        db_user = os.getenv("POSTGRESQL_USER", "postgres")
        db_password = os.getenv("POSTGRESQL_PASSWORD", "postgres")
        db_host = os.getenv("POSTGRESQL_HOST", "localhost")
        db_port = os.getenv("POSTGRESQL_PORT", "5432")

        # --- Helper to establish direct connections for other databases ---
        async def _get_direct_db_connection(db_name: str) -> asyncpg.Connection:
            try:
                conn = await asyncpg.connect(
                    user=db_user,
                    password=db_password,
                    host=db_host,
                    port=db_port,
                    database=db_name
                )
                log.info(f"Established direct connection to database '{db_name}'.")
                return conn
            except Exception as e:
                log.error(f"Failed to establish direct connection to '{db_name}': {e}")
                raise

        # --- Helper to get agent type code mapping ---
        def _get_agent_type_code_mapping(agent_type: str) -> str:
            return self.agent_service_utils.get_code_for_agent_type(agent_type)

        # --- Helper to determine the new agent ID ---
        def _determine_new_agent_id(old_agent_id: str, agent_type: str) -> str:
            agent_code = _get_agent_type_code_mapping(agent_type)
            if old_agent_id.startswith(f"{agent_type}_"):
                # Replace agent_type prefix with agent_code prefix
                uuid_part = old_agent_id[len(agent_type) + 1:]
                return f"{agent_code}_{uuid_part}"
            return old_agent_id

        # --- Phase 1: Determine all new IDs and build mappings ---
        
        # 1.1 Active Agents
        all_active_agents = await self.agent_repo.get_all_agent_records(agentic_application_type=None)
        for agent_record in all_active_agents:
            old_id = agent_record["agentic_application_id"]
            agent_type = agent_record["agentic_application_type"]
            new_id = _determine_new_agent_id(old_id, agent_type)
            
            if old_id != new_id:
                active_agent_id_map[old_id] = new_id
            agent_type_map[new_id] = agent_type
            original_active_agent_records[old_id] = agent_record

        # 1.2 Recycled Agents
        all_recycled_agents = await self.recycle_agent_repo.get_all_recycle_agent_records()
        for agent_record in all_recycled_agents:
            old_id = agent_record["agentic_application_id"]
            agent_type = agent_record["agentic_application_type"]
            new_id = _determine_new_agent_id(old_id, agent_type)
            
            if old_id != new_id:
                recycled_agent_id_map[old_id] = new_id

        if not active_agent_id_map and not recycled_agent_id_map:
            log.info("No agent IDs require migration. Exiting migration process.")
            return {"status": "success", "message": "No agent IDs required migration."}

        log.info(f"Identified {len(active_agent_id_map)} active agents and {len(recycled_agent_id_map)} recycled agents requiring ID migration.")

        # --- Phase 2: Manage Foreign Key Constraints on agent_table ---
        fk_constraints_to_manage = []
        main_db_conn = None
        try:
            main_db_conn = await self.agent_repo.pool.acquire()
            
            # Query to find FKs referencing agent_table.agentic_application_id
            fk_query = f"""
                SELECT
                    con.conname AS constraint_name,
                    rel.relname AS table_name,
                    pg_get_constraintdef(con.oid) AS constraint_definition
                FROM
                    pg_constraint con
                JOIN
                    pg_class rel ON rel.oid = con.conrelid
                JOIN
                    pg_namespace nsp ON nsp.oid = rel.relnamespace
                WHERE
                    con.confrelid = (SELECT oid FROM pg_class WHERE relname = '{self.agent_repo.table_name}')
                    AND con.contype = 'f'
                    AND nsp.nspname = 'public'; -- Assuming public schema
            """
            fk_records = await main_db_conn.fetch(fk_query)

            for record in fk_records:
                constraint_name = record["constraint_name"]
                table_name = record["table_name"]
                constraint_definition = record["constraint_definition"]
                
                fk_constraints_to_manage.append({
                    "constraint_name": constraint_name,
                    "table_name": table_name,
                    "definition": constraint_definition
                })
                
                # Disable the constraint
                await main_db_conn.execute(f"ALTER TABLE {table_name} DROP CONSTRAINT {constraint_name} CASCADE;")
                log.info(f"Temporarily dropped FK constraint '{constraint_name}' on table '{table_name}'.")

            # --- Phase 3: Update references for ACTIVE agents first ---

            # 3.1 tag_agentic_app_mapping_table
            log.info("Migrating tag_agentic_app_mapping_table references for active agents...")
            for old_id, new_id in active_agent_id_map.items():
                try:
                    result = await main_db_conn.execute(f"""
                        UPDATE tag_agentic_app_mapping_table
                        SET agentic_application_id = $1
                        WHERE agentic_application_id = $2;
                    """, new_id, old_id)
                    rows_affected = int(result.split()[-1])
                    migration_summary["tag_mappings_updated"] += rows_affected
                except Exception as e:
                    migration_summary["failed_migrations"].append({"table": "tag_agentic_app_mapping_table", "old_id": old_id, "new_id": new_id, "reason": str(e)})
                    log.error(f"Failed to update tag_agentic_app_mapping_table for {old_id}: {e}")

            # 3.2 tool_agent_mapping_table
            log.info("Migrating tool_agent_mapping_table references for active agents...")
            for old_id, new_id in active_agent_id_map.items():
                try:
                    # Update agentic_application_id column
                    result_agent_col = await main_db_conn.execute(f"""
                        UPDATE tool_agent_mapping_table
                        SET agentic_application_id = $1
                        WHERE agentic_application_id = $2;
                    """, new_id, old_id)
                    rows_affected_agent_col = int(result_agent_col.split()[-1])
                    migration_summary["tool_mappings_updated"] += rows_affected_agent_col

                    # Update tool_id column (for meta-agents acting as worker agents)
                    result_tool_col = await main_db_conn.execute(f"""
                        UPDATE tool_agent_mapping_table
                        SET tool_id = $1
                        WHERE tool_id = $2;
                    """, new_id, old_id)
                    rows_affected_tool_col = int(result_tool_col.split()[-1])
                    migration_summary["tool_mappings_updated"] += rows_affected_tool_col
                except Exception as e:
                    migration_summary["failed_migrations"].append({"table": "tool_agent_mapping_table", "old_id": old_id, "new_id": new_id, "reason": str(e)})
                    log.error(f"Failed to update tool_agent_mapping_table for {old_id}: {e}")

            # 3.3 agent_feedback table (in 'feedback_learning' database)
            log.info("Migrating agent_feedback table references for active agents...")
            feedback_db_conn = None
            try:
                feedback_db_conn = await _get_direct_db_connection(REQUIRED_DATABASES[1]) # 'feedback_learning' db
                for old_id, new_id in active_agent_id_map.items():
                    result = await feedback_db_conn.execute(f"""
                        UPDATE agent_feedback
                        SET agent_id = $1
                        WHERE agent_id = $2;
                    """, new_id, old_id)
                    rows_affected = int(result.split()[-1])
                    migration_summary["agent_feedback_updated"] += rows_affected
            except Exception as e:
                migration_summary["failed_migrations"].append({"table": "agent_feedback", "old_id": old_id, "new_id": new_id, "reason": str(e)})
                log.error(f"Failed to update agent_feedback table: {e}")
            finally:
                if feedback_db_conn:
                    await feedback_db_conn.close()

            # 3.4 export_agent table (in main database)
            log.info("Migrating export_agent table references for active agents...")
            for old_id, new_id in active_agent_id_map.items():
                try:
                    result = await main_db_conn.execute(f"""
                        UPDATE export_agent
                        SET agent_id = $1
                        WHERE agent_id = $2;
                    """, new_id, old_id)
                    rows_affected = int(result.split()[-1])
                    migration_summary["export_agent_updated"] += rows_affected
                except Exception as e:
                    migration_summary["failed_migrations"].append({"table": "export_agent", "old_id": old_id, "new_id": new_id, "reason": str(e)})
                    log.error(f"Failed to update export_agent for {old_id}: {e}")

            # 3.5 evaluation_data table (in 'evaluation_logs' database)
            log.info("Migrating evaluation_data table references for active agents...")
            evaluation_db_conn = None
            try:
                evaluation_db_conn = await _get_direct_db_connection(REQUIRED_DATABASES[2]) # 'evaluation_logs' db
                for old_id, new_id in active_agent_id_map.items():
                    result = await evaluation_db_conn.execute(f"""
                        UPDATE evaluation_data
                        SET agent_id = $1
                        WHERE agent_id = $2;
                    """, new_id, old_id)
                    rows_affected = int(result.split()[-1])
                    migration_summary["evaluation_data_updated"] += rows_affected
            except Exception as e:
                migration_summary["failed_migrations"].append({"table": "evaluation_data", "old_id": old_id, "new_id": new_id, "reason": str(e)})
                log.error(f"Failed to update evaluation_data table: {e}")
            finally:
                if evaluation_db_conn:
                    await evaluation_db_conn.close()

            # --- Phase 4: Rename Long-Term Memory Tables (LangGraph) for ACTIVE agents ---
            log.info("Renaming long-term memory tables for active LangGraph agents...")
            for old_id, new_id in active_agent_id_map.items():
                if agent_type_map.get(new_id) != "hybrid_agent":
                    old_table_name = f'table_{old_id.replace("-", "_")}'
                    new_table_name = f'table_{new_id.replace("-", "_")}'
                    old_table_name = old_table_name[:63]  # Truncate to 63 chars
                    try:
                        table_exists = await main_db_conn.fetchval(
                            "SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = $1)",
                            old_table_name
                        )
                        if table_exists:
                            await main_db_conn.execute(f"ALTER TABLE {old_table_name} RENAME TO {new_table_name};")
                            migration_summary["long_term_memory_tables_renamed"] += 1
                            log.info(f"Renamed long-term memory table: {old_table_name} -> {new_table_name}")
                    except Exception as e:
                        migration_summary["failed_migrations"].append({"table": "long_term_memory_table_rename", "old_name": old_table_name, "new_name": new_table_name, "reason": str(e)})
                        log.error(f"Failed to rename long-term memory table {old_table_name}: {e}")

            # --- Phase 5: Update Short-Term Memory (LangGraph Checkpoints) for ACTIVE agents ---
            log.info("Migrating short-term memory (LangGraph checkpoints) thread_ids for active agents...")
            for old_id, new_id in active_agent_id_map.items():
                if agent_type_map.get(new_id) != "hybrid_agent":
                    old_thread_id_prefix = f'table_{old_id.replace("-", "_")}_'
                    new_thread_id_prefix = f'table_{new_id.replace("-", "_")}_'
                    
                    tables_to_update = ["checkpoints", "checkpoint_blobs", "checkpoint_writes"]
                    for table_name in tables_to_update:
                        try:
                            result = await main_db_conn.execute(f"""
                                UPDATE {table_name}
                                SET thread_id = REPLACE(thread_id, $1, $2)
                                WHERE thread_id LIKE $3;
                            """, old_thread_id_prefix, new_thread_id_prefix, f"{old_thread_id_prefix}%")
                            rows_affected = int(result.split()[-1])
                            migration_summary["short_term_memory_langgraph_threads_updated"] += rows_affected
                        except Exception as e:
                            migration_summary["failed_migrations"].append({"table": table_name, "old_prefix": old_thread_id_prefix, "new_prefix": new_thread_id_prefix, "reason": str(e)})
                            log.error(f"Failed to update {table_name} for {old_thread_id_prefix}: {e}")

            # --- Phase 6: Update Short-Term Memory (Python-based Agent History) for ACTIVE agents ---
            log.info("Migrating short-term memory (Python-based agent history) thread_ids for active agents...")
            for old_id, new_id in active_agent_id_map.items():
                if agent_type_map.get(new_id) == "hybrid_agent":
                    old_thread_id_prefix = f'table_{old_id.replace("-", "_")}_'
                    new_thread_id_prefix = f'table_{new_id.replace("-", "_")}_'

                    try:
                        result = await main_db_conn.execute(f"""
                            UPDATE agent_chat_state_history_table
                            SET thread_id = REPLACE(thread_id, $1, $2)
                            WHERE thread_id LIKE $3;
                        """, old_thread_id_prefix, new_thread_id_prefix, f"{old_thread_id_prefix}%")
                        rows_affected = int(result.split()[-1])
                        migration_summary["python_agent_history_updated"] += rows_affected
                    except Exception as e:
                        migration_summary["failed_migrations"].append({"table": "agent_chat_state_history_table", "old_prefix": old_thread_id_prefix, "new_prefix": new_thread_id_prefix, "reason": str(e)})
                        log.error(f"Failed to update agent_chat_state_history_table for {old_thread_id_prefix}: {e}")

            # --- Phase 7: Update agent_table.tools_id (worker agent IDs) for ACTIVE agents and agent_table.agentic_application_id (LAST STEP for active agents) ---
            log.info("Updating agent_table.tools_id (worker agent IDs) for active meta-agents... and agent_table.agentic_application_id with new IDs for active agents (final step)...")
            for old_id, new_id in active_agent_id_map.items():
                original_record = original_active_agent_records.get(old_id)
                update_payload = {"agentic_application_id": new_id}

                if original_record and original_record["agentic_application_type"] in self.meta_type_templates:
                    old_tools_id_json = original_record["tools_id"]
                    old_worker_agent_ids = json.loads(old_tools_id_json) if isinstance(old_tools_id_json, str) else old_tools_id_json

                    updated_worker_agent_ids = []
                    needs_update = False
                    for worker_id in old_worker_agent_ids:
                        if worker_id in active_agent_id_map:
                            updated_worker_agent_ids.append(active_agent_id_map[worker_id])
                            if active_agent_id_map[worker_id] != worker_id:
                                needs_update = True
                        else:
                            updated_worker_agent_ids.append(worker_id) # Keep if not in map (e.g., a tool, or not migrated)

                    if needs_update:
                        update_payload["tools_id"] = json.dumps(updated_worker_agent_ids)

                try:
                    # This is the final update for the primary key itself
                    success = await self.agent_repo.update_agent_record(update_payload, old_id) # Use old_id for WHERE clause

                    if success:
                        log.info(f"Final update of agent_table.agentic_application_id: {old_id} -> {new_id}")
                        log.info(f"Updated agent_table.tools_id for meta-agent {new_id}")
                    else:
                        migration_summary["failed_migrations"].append({"table": "agent_table_final_pk", "old_id": old_id, "new_id": new_id, "reason": "Final PK update failed"})
                except Exception as e:
                    migration_summary["failed_migrations"].append({"table": "agent_table_final_pk", "old_id": old_id, "new_id": new_id, "reason": str(e)})
                    log.error(f"Failed final update of agent_table for {old_id}: {e}")

            # --- Phase 8: Independently Update Recycled Agents ---
            log.info("Migrating recycle_agent table IDs...")
            recycle_db_conn = None
            try:
                recycle_db_conn = await _get_direct_db_connection(REQUIRED_DATABASES[3]) # 'recycle' db
                for old_id, new_id in recycled_agent_id_map.items():
                    try:
                        result = await recycle_db_conn.execute(f"""
                            UPDATE recycle_agent
                            SET agentic_application_id = $1
                            WHERE agentic_application_id = $2;
                        """, new_id, old_id)
                        rows_affected = int(result.split()[-1])
                        if rows_affected > 0:
                            migration_summary["recycled_agents_updated"] += 1
                            log.info(f"Updated recycle_agent: {old_id} -> {new_id}")
                    except Exception as e:
                        migration_summary["failed_migrations"].append({"table": "recycle_agent", "old_id": old_id, "new_id": new_id, "reason": str(e)})
                        log.error(f"Failed to update recycle_agent for {old_id}: {e}")
            except Exception as e:
                 log.error(f"Failed to connect to recycle database: {e}")
            finally:
                if recycle_db_conn:
                    await recycle_db_conn.close()

        finally:
            # --- Phase 9: Re-enable Foreign Key Constraints ---
            if main_db_conn:
                for fk_info in fk_constraints_to_manage:
                    try:
                        # Re-add the constraint with its original definition
                        await main_db_conn.execute(f"ALTER TABLE {fk_info['table_name']} ADD CONSTRAINT {fk_info['constraint_name']} {fk_info['definition']};")
                        log.info(f"Re-enabled FK constraint '{fk_info['constraint_name']}' on table '{fk_info['table_name']}'.")
                    except Exception as e:
                        migration_summary["failed_migrations"].append({"table": "re_enable_fk", "constraint": fk_info['constraint_name'], "reason": str(e)})
                        log.error(f"Failed to re-enable FK constraint '{fk_info['constraint_name']}': {e}")
                await self.agent_repo.pool.release(main_db_conn)

        log.info("Agent ID migration process completed.")
        return {"status": "completed", "summary": migration_summary}


# --- Chat History Service ---

class ChatService:
    """
    Service layer for managing chat history.
    Applies business rules for naming conventions and orchestrates repository calls.
    """

    def __init__(
            self,
            chat_history_repo: ChatHistoryRepository,
            chat_state_history_manager: ChatStateHistoryManagerRepository,
            admin_config_service: AdminConfigService,
            embedding_model: SentenceTransformer,
            cross_encoder: CrossEncoder,
            tool_repo: ToolRepository = None,
            agent_repo: AgentRepository = None,
            authorization_service: AuthorizationService = None,
            gadk_session_service: DatabaseSessionService = None
        ):
        """
        Initializes the ChatService.

        Args:
            chat_history_repo (ChatHistoryRepository): The repository for chat history data access.
            chat_state_history_manager (ChatStateHistoryManagerRepository): The repository for Python-based agent chat state.
            admin_config_service (AdminConfigService): The service for admin configuration access.
            embedding_model (SentenceTransformer): The embedding model for episodic memory.
            cross_encoder (CrossEncoder): The cross-encoder for episodic memory.
            tool_repo (ToolRepository): The repository for tool data access (for updating last_used).
            agent_repo (AgentRepository): The repository for agent data access.
            gadk_session_service (DatabaseSessionService, optional): The database session service. Defaults to None.
        """
        self.repo = chat_history_repo
        self.chat_state_history_manager = chat_state_history_manager
        self.admin_config_service = admin_config_service    
        self.embedding_model = embedding_model
        self.cross_encoder = cross_encoder
        self.tool_repo = tool_repo
        self.agent_repo = agent_repo
        self.authorization_service = authorization_service
        self.conversation_summary_prompt_template = PromptTemplate.from_template(CONVERSATION_SUMMARY_PROMPT)
        self.python_based_agent_types = [agent_type.value for agent_type in AgentType.python_based_types()]
        # db_url = "sqlite:///./google_adk_db1.db"
        db_url = chat_history_repo.DB_URL
        self.gadk_session_service = gadk_session_service or DatabaseSessionService(db_url=db_url)


    # --- Private Helper Methods (Business Logic) ---

    @staticmethod
    def _extract_user_email_from_session_id(session_id: str) -> str:
        """
        Extracts the user email from the session ID using regex.
        """
        match = re.search(r'([a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+)', session_id)
        user_email = match.group(0) if match else "guest"
        log.info(f"Extracted user email: {user_email} from session ID: {session_id}")
        return user_email

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

    async def _get_thread_config(self, thread_id: str, recursion_limit: Optional[int] = None) -> Dict[str, Any]:
        """
        Retrieves the thread configuration for a specific thread_id.
        """
        if recursion_limit is None:
            config_limits = await self.admin_config_service.get_limits()
            recursion_limit = config_limits.langgraph_recursion_limit
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
        ai_message: str,
        response_time: float = None
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
                response_time=response_time
            )
            return True
        except Exception as e:
            log.error(f"Service-level error saving chat message for session '{session_id}': {e}")
            return False

    async def save_chat_to_file(
        self,
        agentic_application_id: str, 
        session_id: str, 
        start_timestamp: str, 
        end_timestamp: str,
        human_message: str, 
        ai_message: str,
        llm: Any = None
    ) -> bool:
        """
        Saves chat message to a single JSON file organized by agent_id and session_id.
        If messages exceed 10, summarizes older messages using LLM.
        Structure: { agent_id: { session_id: { messages: [], summaries: [], ... } } }
        
        Args:
            agentic_application_id: The agent application ID
            session_id: The session ID
            start_timestamp: Start timestamp of the message
            end_timestamp: End timestamp of the message
            human_message: The user's message
            ai_message: The AI's response
            llm: Optional LLM for summarizing old messages
            
        Returns:
            bool: True if successful, False otherwise
        """
        import os
        import json
        import tempfile
        import shutil
        from datetime import datetime
        
        # Helper function to convert datetime to string
        def ensure_string(value):
            if isinstance(value, datetime):
                return value.isoformat()
            return str(value) if value is not None else ""
        
        MAX_MESSAGES_BEFORE_SUMMARY = 10
        
        try:
            # Create the chat_logs directory path (relative to this file's location)
            chat_logs_dir = os.path.join(os.path.dirname(__file__), "..", "inference", "chat_logs")
            os.makedirs(chat_logs_dir, exist_ok=True)
            
            # Single file for all conversations
            filepath = os.path.join(chat_logs_dir, "conversations.json")
            
            # Prepare the chat entry (convert datetime to string if needed)
            chat_entry = {
                "start_timestamp": ensure_string(start_timestamp),
                "end_timestamp": ensure_string(end_timestamp),
                "human_message": str(human_message) if human_message else "",
                "ai_message": str(ai_message) if ai_message else ""
            }
            
            # Load existing data or create new structure
            all_conversations = {}
            if os.path.exists(filepath):
                try:
                    with open(filepath, 'r', encoding='utf-8') as f:
                        content = f.read().strip()
                        if content:
                            all_conversations = json.loads(content)
                        else:
                            all_conversations = {}
                except (json.JSONDecodeError, FileNotFoundError) as e:
                    log.warning(f"Error reading conversations.json, starting fresh: {e}")
                    all_conversations = {}
            
            # Initialize agent_id key if not exists
            if agentic_application_id not in all_conversations:
                all_conversations[agentic_application_id] = {}
            
            # Initialize session_id key if not exists
            if session_id not in all_conversations[agentic_application_id]:
                all_conversations[agentic_application_id][session_id] = {
                    "created_at": ensure_string(start_timestamp),
                    "messages": [],
                    "summaries": []  # Store summaries of older conversations
                }
            
            # Ensure summaries key exists for older sessions
            if "summaries" not in all_conversations[agentic_application_id][session_id]:
                all_conversations[agentic_application_id][session_id]["summaries"] = []
            
            # Append new message to the session
            all_conversations[agentic_application_id][session_id]["messages"].append(chat_entry)
            all_conversations[agentic_application_id][session_id]["updated_at"] = ensure_string(end_timestamp)
            
            # Check if messages exceed threshold - if so, summarize older ones
            messages = all_conversations[agentic_application_id][session_id]["messages"]
            if len(messages) > MAX_MESSAGES_BEFORE_SUMMARY and llm:
                try:
                    # Get messages to summarize (all except the last 5)
                    messages_to_summarize = messages[:-5]
                    messages_to_keep = messages[-5:]
                    
                    # Format messages for summarization (same format as get_chat_summary)
                    chat_history = "\n\n".join([
                        f"""Human Message: {msg['human_message']}
    AI Message: {msg['ai_message']}"""
                        for msg in messages_to_summarize
                    ])
                    
                    # Get existing summary from file (past_conversation_summary)
                    existing_summaries = all_conversations[agentic_application_id][session_id].get("summaries", [])
                    past_conversation_summary = ""
                    if existing_summaries:
                        # Combine all existing summaries
                        past_conversation_summary = "\n\n".join([s.get("summary", "") for s in existing_summaries if s.get("summary")])
                    
                    # Use the same CONVERSATION_SUMMARY_PROMPT approach
                    conversation_summary_chain = self.conversation_summary_prompt_template | llm | StrOutputParser()
                    summary_text = await conversation_summary_chain.ainvoke({
                        "chat_history": chat_history,
                        "past_conversation_summary": past_conversation_summary
                    })
                    
                    # Create summary entry
                    summary_entry = {
                        "summarized_at": ensure_string(end_timestamp),
                        "message_count": len(messages_to_summarize),
                        "time_range": {
                            "from": messages_to_summarize[0]["start_timestamp"],
                            "to": messages_to_summarize[-1]["end_timestamp"]
                        },
                        "summary": summary_text
                    }
                    
                    # Add to summaries and keep only recent messages
                    all_conversations[agentic_application_id][session_id]["summaries"].append(summary_entry)
                    all_conversations[agentic_application_id][session_id]["messages"] = messages_to_keep
                    
                    log.info(f"Summarized {len(messages_to_summarize)} messages for session {session_id[:8]}...")
                    
                except Exception as e:
                    log.error(f"Failed to summarize conversation: {e}")
                    # Continue without summarization if it fails
            
            # Save to file using atomic write (write to temp file, then rename)
            # First serialize to ensure valid JSON
            json_content = json.dumps(all_conversations, indent=2, ensure_ascii=False)
            
            # Write to temp file first
            temp_fd, temp_path = tempfile.mkstemp(dir=chat_logs_dir, suffix='.tmp')
            try:
                with os.fdopen(temp_fd, 'w', encoding='utf-8') as f:
                    f.write(json_content)
                    f.flush()
                    os.fsync(f.fileno())  # Ensure data is written to disk
                
                # Atomic replace (on Windows, need to remove first)
                if os.path.exists(filepath):
                    os.remove(filepath)
                shutil.move(temp_path, filepath)
                
                log.info(f"Chat saved to file: {filepath} [Agent: {agentic_application_id[:8]}..., Session: {session_id[:8]}...]")
                return True
            except Exception as e:
                # Clean up temp file if it exists
                if os.path.exists(temp_path):
                    os.remove(temp_path)
                raise e
                
        except Exception as e:
            log.error(f"Failed to save chat to file: {e}")
            return False

    async def update_latest_response_time(
        self,
        agentic_application_id: str,
        session_id: str,
        response_time: float
    ) -> bool:
        """
        Updates the response time for the most recent chat record for a given session.
        This is called after the centralized response time calculation to ensure accuracy.

        Args:
            agentic_application_id (str): The ID of the agent application.
            session_id (str): The session ID.
            response_time (float): The calculated response time in seconds.

        Returns:
            bool: True if successful, False otherwise.
        """
        table_name = await self._get_chat_history_table_name(agentic_application_id)
        try:
            await self.repo.create_chat_history_table(table_name)
            return await self.repo.update_latest_response_time(
                table_name=table_name,
                session_id=session_id,
                response_time=response_time
            )
                    
        except Exception as e:
            log.error(f"Service-level error updating response time for session '{session_id}': {e}")
            return False

    async def get_chat_history_from_short_term_memory(
        self,
        agentic_application_id: str,
        session_id: str,
        framework_type: FrameworkType = FrameworkType.LANGGRAPH,
        role: str = None,
        department_name: str = None
    ) -> Dict[str, Any]:
        """
        Retrieves the conversation history for a session, supporting multiple agent frameworks.

        Args:
            agentic_application_id (str): The ID of the agent or application.
            session_id (str): The session ID of the user.
            framework_type (FrameworkType): The framework type, either 'langgraph' or 'google_adk'.

        Returns:
            A dictionary containing the conversation history or an error message.
        """
        # --- This block contains all the original logic for LangGraph agents ---
        thread_id = await self._get_thread_id(agentic_application_id, session_id)

        if await self.is_python_based_agent(agentic_application_id):
            try:
                # ... (original logic for Python-based agents)
                history_entries = await self.chat_state_history_manager.get_recent_history(thread_id)
                if not history_entries:
                    log.warning(f"No previous conversation found for Python-based agent session ID: {session_id}.")
                    return {"executor_messages": []}

                # Format the history entries into the desired structure
                formatted_history = await self._format_python_based_agent_history(history_entries)
                formatted_history["agentic_application_id"] = agentic_application_id
                formatted_history["session_id"] = session_id

                
                log.info(f"Previous conversation retrieved and formatted for Python-based agent session ID: {session_id}.")
                return formatted_history

            except Exception as e:
                log.error(f"Error retrieving Python-based agent history for session {session_id}: {e}", exc_info=True)
                return {"error": f"An unknown error occurred while retrieving conversation: {e}"}

            finally:
                update_session_context(session_id='Unassigned', agent_id='Unassigned')

        elif framework_type == FrameworkType.GOOGLE_ADK:
            user_id = self._extract_user_email_from_session_id(session_id)
            
            log.info(f"Retrieving Google ADK history for session '{session_id}' and user '{user_id}'.")
            try:
                # Assuming `self.gadk_session_service` is an initialized ADK client
                gadk_chat_session = await self.gadk_session_service.get_session(
                    user_id=user_id,
                    session_id=session_id,
                    app_name=agentic_application_id
                )

                if not gadk_chat_session:
                    log.warning(f"No previous conversation found for Google ADK session ID: {session_id}.")
                    return {"executor_messages": []}

                # Call the static method to format the history
                formatted_history = await self._format_google_adk_agent_history(gadk_chat_session)
                
                log.info(f"Previous conversation retrieved and formatted for Google ADK session ID: {session_id}.")
                return formatted_history

            except Exception as e:
                log.error(f"Error retrieving Google ADK history for session {session_id}: {e}", exc_info=True)
                return {"error": f"An unknown error occurred while retrieving conversation: {e}"}

            finally:
                update_session_context(session_id='Unassigned', agent_id='Unassigned')

        elif framework_type == FrameworkType.LANGGRAPH:
            try:
                # ... (original logic for standard LangGraph agents)
                async with await self.get_checkpointer_context_manager() as checkpointer:
                # checkpointer.setup() is often called implicitly or handled by LangGraph's app.compile()
                # but explicitly calling it here ensures the table exists if it's the first time.
                # However, for just retrieving, it might not be strictly necessary if tables are pre-created.
                    await checkpointer.setup() # Ensure table exists
                    config = await self._get_thread_config(thread_id)
                    data = await checkpointer.aget(config) # Retrieve the state
                    data = data.get("channel_values", {}) if data else {}
                if not data:
                    log.warning(f"No previous conversation found for LangGraph agent session ID: {session_id} and agent ID: {agentic_application_id}.")
                    return {"executor_messages": []} # Return empty list if no data

                # Segregate messages using the static method
                data["executor_messages"] = await self.segregate_conversation_from_raw_chat_history_with_pretty_steps(data, agentic_application_id=agentic_application_id, session_id=session_id, role=role, department_name=department_name)

                log.info(f"Previous conversation retrieved successfully for session ID: {session_id} and agent ID: {agentic_application_id}.")
                return data
            except Exception as e:
                log.error(f"Error occurred while retrieving previous conversation for LangGraph agent session {session_id}: {e}", exc_info=True)
                return {"error": f"An unknown error occurred while retrieving conversation: {e}"}
            finally:
                update_session_context(session_id='Unassigned', agent_id='Unassigned')

        else:
            log.warning(f"Attempted to get history for session '{session_id}' with an unknown framework_type: '{framework_type}'.")
            return {"error": f"Retrieval failed: Unknown framework_type '{framework_type}'. Supported types are 'google_adk' and 'langgraph'."}

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

    async def get_chat_summary(
            self,
            agentic_application_id,
            session_id,
            llm,
            conversation_limit=Limits.LANGGRAPH_LONG_TERM_MEMORY_LIMIT,
            executor_messages=None,
            executor_message_limit=Limits.LANGGRAPH_EXECUTOR_MESSAGES_LIMIT
        ) -> str:
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

    async def get_detailed_chats_by_user_and_app_for_gadk(self, user_id: str, app_name: str) -> Dict[str, List[Dict[str, Any]]]:
        """
        Retrieves detailed chat histories for all sessions of a specific user and Google ADK application.

        Args:
            user_id (str): The ID of the user (typically their email).
            app_name (str): The name of the Google ADK application (agent ID).
        Returns:
            Dict[str, List[Dict[str, Any]]]: A dictionary where keys are session IDs and values are lists of chat records.
        """
        all_sessions_history: Dict[str, List[Dict[str, Any]]] = {}
        log.info(f"Starting detailed chat retrieval for user '{user_id}' and app '{app_name}'.")

        try:
            sessions_list = await self.gadk_session_service.list_sessions(user_id=user_id, app_name=app_name)
            sessions_list = sessions_list.sessions

            if not sessions_list:
                log.info(f"No sessions found for user '{user_id}' and app '{app_name}'.")
                return {}

            for session in sessions_list:
                log.info(f"Fetching and parsing full details for session_id: {session.id}")
                complete_session_chat_history = await self.gadk_session_service.get_session(
                    app_name=app_name, user_id=user_id, session_id=session.id
                )

                current_chat = []
                formatted_session_chat_history = await self._format_google_adk_agent_history(gadk_chat_session=complete_session_chat_history)
                for chat_record in formatted_session_chat_history.get("executor_messages", []):
                    chat_record: dict = chat_record
                    current_chat.append({
                        "user_input": chat_record.get("user_query", ""),
                        "agent_response": chat_record.get("final_response", ""),
                        "timestamp_start": chat_record.get("st_time_stamp", ""),
                        "timestamp_end": chat_record.get("time_stamp", ""),
                    })

                if current_chat:
                    all_sessions_history[session.id] = current_chat

            log.info(f"Finished retrieving and parsing chats for user '{user_id}' and app '{app_name}'.")
            return all_sessions_history

        except Exception as e:
            log.error(f"An error occurred while retrieving detailed chats for user '{user_id}': {e}")
            return {}

    async def get_old_chats_by_user_and_agent(self, user_email: str, agent_id: str, framework_type: FrameworkType = FrameworkType.LANGGRAPH) -> Dict[str, Any]:
        """
        Retrieves old chat sessions for a specific user and agent.
        Handles both LangGraph-based and Python-based agents.

        Args:
            user_email (str): The email of the user.
            agent_id (str): The ID of the agent.
            framework_type (FrameworkType): The framework used by the agent ('google_adk', 'langgraph').

        Returns:
            Dict[str, Any]: A dictionary where keys are session IDs and values are lists of chat records.
        """
        table_name = await self._get_chat_history_table_name(agent_id)
        result = {}

        # Determine if it's a Python-based agent or LangGraph-based
        if await self.is_python_based_agent(agent_id):
            # The thread_id for Python-based agents is `hybrid_agent_uuid_user@example.com_uuid`
            # So, we need to search for `hybrid_agent_uuid_user@example.com_%`
            thread_id_prefix = f"{table_name}_{user_email}_%"
            try:
                raw_records = await self.chat_state_history_manager.get_chat_records_by_thread_id_prefix(
                    thread_id_prefix=thread_id_prefix
                )
            except Exception as e:
                log.error(f"Error retrieving old chats for Python-based agent '{agent_id}' and user '{user_email}': {e}")
                return {} # Return empty dict on error

            for row in raw_records:
                # For Python-based agents, the thread_id is the session_id
                session_id_full = row.get('thread_id')[len(table_name)+1:] # Remove the table_name_ prefix to get session_id
                timestamp = row.get('timestamp')
                user_input = row.get('user_query')
                agent_steps = row.get('agent_steps') # This is the full list of messages for the turn
                final_response = row.get('final_response')

                if session_id_full not in result:
                    result[session_id_full] = []

                # Extract the final AI message from agent_steps for 'agent_response'
                ai_message_content = ""
                if final_response:
                    ai_message_content = final_response
                elif agent_steps:
                    # Look for the last assistant message if final_response is null
                    for msg in reversed(agent_steps):
                        if msg.get("role") == "assistant" and msg.get("content"):
                            ai_message_content = msg["content"]
                            break

                result[session_id_full].append({
                    "timestamp_start": timestamp, # Using timestamp for both start/end for simplicity of a turn
                    "timestamp_end": timestamp,
                    "user_input": user_input,
                    "agent_response": ai_message_content
                })

        elif framework_type == FrameworkType.GOOGLE_ADK:
            return await self.get_detailed_chats_by_user_and_app_for_gadk(user_id=user_email, app_name=agent_id)

        else:
            try:
                raw_records = await self.repo.get_chat_records_by_session_prefix(
                    table_name=table_name,
                    session_id_prefix=f"{user_email}_%"
                )
            except Exception as e:
                log.error(f"Error retrieving old chats for LangGraph agent '{agent_id}' and user '{user_email}': {e}")
                return {} # Return empty dict on error

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

    async def delete_session(self, agentic_application_id: str, session_id: str, framework_type: FrameworkType = FrameworkType.LANGGRAPH) -> Dict[str, Any]:
        """
        Deletes the entire conversation history for a specific session based on the agent's framework.

        Args:
            agentic_application_id (str): The ID of the agent or application.
            session_id (str): The session ID to delete.
            framework_type (FrameworkType): The framework used by the agent ('google_adk', 'langgraph').

        Returns:
            A dictionary indicating the status of the deletion operation.
        """
        # --- Handle LangGraph Session Deletion (maintaining original logic) ---
        thread_id = await self._get_thread_id(agentic_application_id, session_id)

        if await self.is_python_based_agent(agentic_application_id):
            # Handle "Python-based" LangGraph agents
            log.info(f"Attempting to delete Python-based LangGraph session '{session_id}'.")
            try:
                success = await self.chat_state_history_manager.clear_chat_history(thread_id)
                if success:
                    return {
                        "status": "success",
                        "message": f"Memory history deleted successfully for Python-based agent session {session_id}.",
                        "chat_rows_deleted": "N/A"
                    }
                else:
                    return {"status": "error", "message": f"Failed to clear history for Python-based agent session {session_id}."}
            except Exception as e:
                log.error(f"Service-level error during delete for Python-based agent session '{session_id}': {e}")
                return {"status": "error", "message": f"An error occurred during deletion: {e}"}

        elif framework_type == FrameworkType.GOOGLE_ADK:
            # --- Handle Google ADK Session Deletion ---
            user_id = self._extract_user_email_from_session_id(session_id)
            log.info(f"Attempting to delete Google ADK session '{session_id}' for user '{user_id}'.")
            try:
                # Assuming `self.gadk_session_service` is an initialized ADK session service client
                await self.gadk_session_service.delete_session(
                    app_name=agentic_application_id,
                    user_id=user_id,
                    session_id=session_id
                )

                return {
                    "status": "success",
                    "message": f"Session history deleted successfully for Google ADK session {session_id}."
                }
            except Exception as e:
                log.error(f"Service-level error during delete for Google ADK session '{session_id}': {e}")
                return {"status": "error", "message": f"An error occurred during Google ADK session deletion: {e}"}

        elif framework_type == FrameworkType.LANGGRAPH:
            # Handle standard LangGraph agents
            log.info(f"Attempting to delete standard LangGraph session '{session_id}'.")
            chat_table_name = await self._get_chat_history_table_name(agentic_application_id)

            try:
                chat_rows_deleted = await self.repo.delete_session_transactional(
                    chat_table_name=chat_table_name,
                    thread_id=thread_id,
                    session_id=session_id
                )
                conversation_summary_and_preference_deleted = await self.repo.delete_agent_conversation_summary(
                    agentic_application_id=agentic_application_id,
                    session_id=session_id
                )
                if conversation_summary_and_preference_deleted:
                    log.info(f"Deleted conversation summary and preference for session '{session_id}'.")

                return {
                    "status": "success",
                    "message": f"Memory history deleted successfully for LangGraph agent session {session_id}.",
                    "chat_rows_deleted": chat_rows_deleted
                }
            except Exception as e:
                log.error(f"Service-level error during transactional delete for LangGraph agent session '{session_id}': {e}")
                return {"status": "error", "message": f"An error occurred during deletion: {e}"}

        else:
            # --- Handle Unknown Framework Type ---
            log.warning(f"Attempted to delete session '{session_id}' with an unknown framework_type: '{framework_type}'.")
            return {
                "status": "error",
                "message": f"Deletion failed: Unknown framework_type '{framework_type}'. Supported types are 'google_adk' and 'langgraph'."
            }

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
    async def get_formatted_messages(messages: List[AnyMessage], msg_limit: int = None) -> str:
        """
        Formats a list of messages for display.

        Args:
            messages (list): The list of messages.
            msg_limit (int): The maximum number of messages to display.

        Returns:
            str: The formatted message string.
        """
        if msg_limit is None:
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
        return f"ongoing conversation : {msg_formatted.strip()}"

    async def segregate_conversation_from_raw_chat_history_with_pretty_steps(self, response: Dict[str, Any], agentic_application_id=None, session_id=None, role=None, department_name=None) -> List[Dict[str, Any]]:
        """
        Segregates and formats conversation messages from a raw response into a human-readable list.
        Preserves existing response_time values from previous segregated data.
        """
        if "error" in response:
            log.error(f"Error in response")
            return [response]
        error_message = [{"error": "Chat History not compatable with the new version. Please reset your chat."}]
        executor_messages = response.get("executor_messages", [{}])

        if hasattr(self, 'agent_repo') and self.agent_repo:
            try:
                await self.agent_repo.update_last_used_agent(agentic_application_id)
            except Exception as e:
                # Log the error but don't fail the conversation processing
                log.warning(f"Warning: Failed to update last_used for agent {agentic_application_id}: {e}")

                        
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
        response_time = None
        start_timestamp = None
        for message in reversed(executor_messages):
            if message.type == "chat" and message.role == "response_time":
                response_time = message.content[0].get("response_time")
                start_timestamp = message.content[0].get("start_timestamp")
                continue
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
                            tool_name = tool_msg["name"]

                            # Update last_used timestamp for the tool
                            if hasattr(self, 'tool_repo') and self.tool_repo:
                                try:
                                    await self.tool_repo.update_last_used(tool_name)
                                except Exception as e:
                                    # Log the error but don't fail the conversation processing
                                    log.info(f"Warning: Failed to update last_used for tool {tool_name}: {e}")
                                    
                            tools_used[tool_msg["id"]].update(tool_msg)

                    elif msg.type == "tool":
                        if msg.tool_call_id not in tools_used:
                            tools_used[msg.tool_call_id] = {}
                        tools_used[msg.tool_call_id]["status"] = msg.status
                        tools_used[msg.tool_call_id]["output"] = msg.content
                    data += "\n"+ msg.pretty_repr()


                # Create conversation object based on execution steps access
                has_execution_steps_access = False
                if self.authorization_service and role:
                    has_execution_steps_access = await self.authorization_service.check_execution_steps_access(role, department_name=department_name)
                
                if not has_execution_steps_access:
                    # Calculate final_response first
                    final_response_content = agent_steps[0].content if (agent_steps[0].type == "ai") and ("tool_calls" not in agent_steps[0].additional_kwargs) and ("function_call" not in agent_steps[0].additional_kwargs) else ""
                    
                    new_conversation = {
                        "user_query": message.content,
                        "final_response": final_response_content,
                        "response_time": response_time,
                        "start_timestamp": start_timestamp,
                        "parts": parts_dict.get(agent_steps[0].id, [
                            {
                                "type": "text",
                                "data": {
                                    "content": final_response_content
                                },
                                "metadata": {}
                            }
                        ]),
                    }
                    
                    # If final_response is empty, include essential tool call information from additional_details
                    if not final_response_content:
                        filtered_additional_details = []
                        for step in agent_steps:
                            if step.type == "ai" and ("tool_calls" in step.additional_kwargs or "function_call" in step.additional_kwargs):
                                # Include only essential tool call information
                                essential_step = {
                                    "content": step.content,
                                    "additional_kwargs": {}
                                }
                                
                                # Include tool_calls with essential information only
                                if "tool_calls" in step.additional_kwargs:
                                    essential_step["additional_kwargs"]["tool_calls"] = []
                                    for tool_call in step.additional_kwargs["tool_calls"]:
                                        essential_tool_call = {
                                            "id": tool_call.get("id"),
                                            "function": {
                                                "arguments": tool_call.get("function", {}).get("arguments"),
                                                "name": tool_call.get("function", {}).get("name")
                                            },
                                            "type": tool_call.get("type")
                                        }
                                        essential_step["additional_kwargs"]["tool_calls"].append(essential_tool_call)
                                
                                # Include refusal if present
                                if "refusal" in step.additional_kwargs:
                                    essential_step["additional_kwargs"]["refusal"] = step.additional_kwargs["refusal"]
                                
                                filtered_additional_details.append(essential_step)
                        
                        if filtered_additional_details:
                            new_conversation["additional_details"] = filtered_additional_details
                    
                    for sub_part in new_conversation["parts"]:
                        if sub_part.get("type") != "text":
                            new_conversation.update({"show_canvas": True})
                            break
                    else:
                        new_conversation.update({"show_canvas": False})
                else:
                    # For other roles (DEVELOPER, ADMIN, SUPER_ADMIN), include all fields
                    new_conversation = {
                        "user_query": message.content,
                        "final_response": agent_steps[0].content if (agent_steps[0].type == "ai") and ("tool_calls" not in agent_steps[0].additional_kwargs) and ("function_call" not in agent_steps[0].additional_kwargs) else "",
                        "response_time": response_time,
                        "start_timestamp": start_timestamp,
                        "tools_used": tools_used,
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
                    
                    
                    # Apply tool call logic only for non-USER roles
                    if (agent_steps[0].type == "ai") and (("tool_calls" in agent_steps[0].additional_kwargs) or ("function_call" in agent_steps[0].additional_kwargs)):
                        new_conversation["parts"] = []
                
                conversation_list.append(new_conversation)
                agent_steps = []
                tools_used = dict()
        log.info("Conversation segregated from chat history successfully")
        
        # Apply parts processing only for roles with execution steps access
        has_execution_steps_access_final = False
        if self.authorization_service and role:
            has_execution_steps_access_final = await self.authorization_service.check_execution_steps_access(role, department_name=department_name)
        if len(conversation_list) > 0 and has_execution_steps_access_final:
            for part in conversation_list[0]["parts"]:
                if part["type"] not in ("text", "image"):
                    part.update({"is_last": True})
        
        final_conversation_list = list(reversed(conversation_list))
        return final_conversation_list

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
        end_tag: str = "[:liked_by_user]",
        framework_type: FrameworkType = FrameworkType.LANGGRAPH
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
        if await self.is_python_based_agent(agentic_application_id) or framework_type == FrameworkType.GOOGLE_ADK:
            update_status = True
        else:
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

    @staticmethod
    async def get_unique_messages(messages: List[str], similarity_threshold=0.5):
        """
        Filters a list of messages to return only those that are not too similar to each other.
        The `similarity_threshold` is a float from 0 to 1.
        """
        if not messages:
            return []

        unique_messages: List[str] = []
        # Loop through each message in the original list
        for new_message in messages:
            is_similar = False
            # Compare the new message to all the messages we've already deemed unique
            for existing_message in unique_messages:
                # Use SequenceMatcher to get a similarity ratio (e.g., 0.95)
                similarity = difflib.SequenceMatcher(None, new_message.lower(), existing_message.lower()).ratio()
                if similarity >= similarity_threshold:
                    is_similar = True
                    break  # Found a similar message, no need to check further
            
            # If no similar message was found, add it to our unique list
            if not is_similar:
                unique_messages.append(new_message)

        return unique_messages

    async def fetch_user_queries_from_python_based_agent_for_suggestions(self, user_email: str, agentic_application_id: str, chat_table_name: str) -> Dict[str, List[str]]:
        """
        Fetches all user queries from Python-based agents for a specific user and agent.

        Args:
            user_email (str): The email of the user to fetch queries for.
            agentic_application_id (str): The ID of the agentic application.
        """
        queries = {"user_history": [], "agent_history": []}
        thread_id_prefix = f"{chat_table_name}_"
        try:
            raw_records = await self.chat_state_history_manager.get_chat_records_by_thread_id_prefix(
                thread_id_prefix=thread_id_prefix
            )
        except Exception as e:
            log.error(f"Error retrieving user queries for Python-based agent '{agentic_application_id}' and user '{user_email}': {e}")
            return queries

        thread_id_prefix = f"{thread_id_prefix}{user_email}_"
        for row in raw_records:
            thread_id: str = row.get('thread_id')
            if thread_id.startswith(thread_id_prefix):
                queries["user_history"].append(row['user_query'])
            else:
                queries["agent_history"].append(row['user_query'])

        return queries

    async def fetch_user_queries_from_google_adk_for_suggestions(self, user_email: str, agentic_application_id: str) -> Dict[str, List[str]]:
        """
        Fetches all user queries from Google ADK database for a specific user and agent.

        Args:
            user_email (str): The email of the user to fetch queries for.
            agentic_application_id (str): The ID of the agentic application (app_name in ADK).

        Returns:
            Dict[str, List[str]]: A dictionary containing user queries and query library.
        """
        queries = {"user_history": [], "agent_history": []}
        log.info(f"Fetching user queries from Google ADK for agent '{agentic_application_id}'.")

        try:
            # Get all sessions for a agent_id from Google ADK
            sessions_list = await self.gadk_session_service.list_sessions(app_name=agentic_application_id)
            sessions_list = sessions_list.sessions

            if not sessions_list:
                log.info(f"No Google ADK sessions found for agent '{agentic_application_id}'.")
                return queries

            # Iterate through each session to extract user queries
            for session in sessions_list:
                try:
                    complete_session_chat_history = await self.gadk_session_service.get_session(
                        app_name=agentic_application_id, 
                        user_id=session.user_id, 
                        session_id=session.id
                    )
                    formatted_session_chat_history = await self._format_google_adk_agent_history(gadk_chat_session=complete_session_chat_history)

                    current_chat_queries = [chat_record.get("user_query", "") for chat_record in formatted_session_chat_history.get("executor_messages", [])]
                    if session.user_id == user_email:
                        queries["user_history"].extend(current_chat_queries)
                    else:
                        queries["agent_history"].extend(current_chat_queries)

                except Exception as session_error:
                    log.warning(f"Error fetching session '{session.id}' for Google ADK: {session_error}")
                    continue

        except Exception as e:
            log.error(f"Error fetching user queries from Google ADK for user '{user_email}' and agent '{agentic_application_id}': {e}")

        return queries

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

        if await self.is_python_based_agent(agentic_application_id):
            queries = await self.fetch_user_queries_from_python_based_agent_for_suggestions(user_email=user_email, agentic_application_id=agentic_application_id, chat_table_name=chat_table_name)

        else:
            queries = await self.repo.fetch_user_query_from_chat_table(user_email=user_email, chat_table_name=chat_table_name)
            queries_adk = await self.fetch_user_queries_from_google_adk_for_suggestions(user_email=user_email, agentic_application_id=agentic_application_id)
            queries["user_history"].extend(queries_adk.get("user_history", []))
            queries["agent_history"].extend(queries_adk.get("agent_history", []))

        try:
            queries["user_history"] = list(set(queries["user_history"]))
            queries["agent_history"] = list(set(queries["agent_history"]))
            all_message = queries["user_history"] + queries["agent_history"]

            query_library = await self.get_unique_messages(all_message)
            queries["query_library"] = query_library
            log.info(f"Fetched {len(queries['user_history'])} user queries and {len(queries['agent_history'])} agent queries for user '{user_email}' and agent '{agentic_application_id}'. Total unique queries: {len(query_library)}")

        except Exception as e:
            log.error(f"Error processing user queries for user '{user_email}' and agent '{agentic_application_id}': {e}")
            queries["query_library"] = []

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
                    tools_used: dict = conversation.get("tools_used", {})
                    
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
            elif isinstance(response, dict) and "final_response" in response:
                content = response["final_response"]
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
                            log.info(f"Successfully stored example {i+1} as {label} example")
                                
                        except Exception as storage_error:
                            result["storage_status"] = "failed"
                            result["storage_message"] = f"Storage failed: {str(storage_error)}"
                            log.info(f"Failed to store example {i+1}: {storage_error}")
                    
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
                log.info(f"Analysis and storage completed: Found {len(processed_results)} valid examples out of {len(episodic_results)} total results")
                
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

    # Chat State Management for Python based agents - Helper Methods

    async def is_python_based_agent(self, agentic_application_id: str) -> bool:
        """
        Determines if the agent type corresponds to a Python-based agent.

        Args:
            agentic_application_id (str): The ID of the agent.
        """
        for agent_type in self.python_based_agent_types:
            agent_code = AgentType(agent_type).code
            if agentic_application_id.startswith(f"{agent_type}_") or agentic_application_id.startswith(f"{agent_code}_"):
                return True
        return False

    @staticmethod
    async def _format_python_based_agent_history(history_entries: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Formats the raw history entries from ChatStateHistoryManagerRepository into the
        desired structure for the UI, similar to LangGraph's output.

        Args:
            history_entries: A list of dictionaries, each representing a turn from the DB.

        Returns:
            A list of dictionaries, each representing a formatted conversation turn.
        """
        formatted_conversation_list = []
        ongoing_conversation = []
        final_formatted_conversation = {
            "query": "",
            "response": "",
            "past_conversation_summary": "",
            "executor_messages": formatted_conversation_list,
            "ongoing_conversation": ongoing_conversation,
            "agentic_application_id": "",
            "session_id": "",
            "model_name": "",
            "start_timestamp": "",
            "end_timestamp": "",
            "reset_conversation": False,
            "errors": [],
            "parts": [],
            "response_formatting_flag": None,
            "context_flag": None,
            "validation_score": None,
            "validation_feedback": None,
            "mentioned_agent_id": None,
            "preference": "",
            "is_tool_interrupted": None,
            "evaluation_score": None,
            "evaluation_feedback": None,
            "workflow_description": "",
        }
        last_conversation_plan: List[str] = None

        for entry in history_entries:
            user_query = entry.get("user_query", "")
            final_response = entry.get("final_response", "")
            agent_steps_raw: List[Dict[str, Any]] = entry.get("agent_steps", []) # This is already a list of dicts

            # Reconstruct 'agent_steps' (pretty-printed string)
            pretty_printed_steps = ""
            tools_used = {}
            additional_details = [] # To store messages with 'type' key
            last_conversation_plan = None
            is_replan = False
            response_time = 0
            start_timestamp = None
            # Iterate through agent_steps_raw in chronological order for pretty printing
            for msg in agent_steps_raw:
                role = msg.get("role")
                content = msg.get("content", "")
                
                # Add to additional_details with 'type' key
                detail_msg = msg.copy()
                response_time_details = detail_msg.pop("response_time_details", {})
                if response_time_details:
                    response_time += response_time_details.get("response_time", 0)
                    if not start_timestamp:
                        start_timestamp = response_time_details.get("start_timestamp", start_timestamp)
                online_evaluation_results: dict = None
                online_validation_results: dict = None
                if role == "user":
                    detail_msg["type"] = "human"
                elif role == "assistant":
                    detail_msg["type"] = "ai"
                    online_evaluation_results = detail_msg.pop("online_evaluation_results", None)
                    online_validation_results = detail_msg.pop("online_validation_results", None)
                elif role == "tool":
                    detail_msg["type"] = "tool"

                additional_details.append(detail_msg)

                # Handle online validation results - add as separate step
                if online_validation_results and isinstance(online_validation_results, dict):
                    pretty_printed_steps += f"\n================================ Validation =================================\n\n{online_validation_results}\n"
                    validation_status = online_validation_results.get("validation_status", "unknown")
                    online_validation_msg = {
                        "content": online_validation_results,
                        "role": "validator-error" if validation_status == "error" else "validator-response",
                        "type": "chat",
                        "validation_score": online_validation_results.get("validation_score"),
                        "validation_status": validation_status,
                        "validation_feedback": online_validation_results.get("feedback"),
                    }
                    additional_details.append(online_validation_msg)

                if online_evaluation_results and isinstance(online_evaluation_results, dict):
                    pretty_printed_steps += f"\n================================ Chat Message =================================\n\n{online_evaluation_results}\n"
                    online_evaluation_msg = {
                        "content": online_evaluation_results,
                        "role": "evaluator-error" if "error" in online_evaluation_results else "evaluator-response",
                        "type": "chat"
                    }
                    additional_details.append(online_evaluation_msg)
                    additional_details.append(detail_msg)

                if role == "user":
                    pretty_printed_steps += f"\n================================ Human Message =================================\n\n{content}\n"

                elif role == "assistant":
                    detail_msg.pop("role", None)
                    pretty_printed_steps += f"\n================================== Ai Message ==================================\n\n{content}\n\n"

                    if msg.get("tool_calls"):
                        if detail_msg["content"] is None:
                            detail_msg["content"] = ""
                        detail_msg["additional_kwargs"] = {"tool_calls": msg["tool_calls"]}
                        pretty_printed_steps += f"Tool Calls:\n"
                        for tool_call in msg["tool_calls"]:
                            pretty_printed_steps += f"  {tool_call['function']['name']} (call_{tool_call['id']})\n"
                            pretty_printed_steps += f"  Call ID: {tool_call['id']}\n"
                            pretty_printed_steps += f"  Args:\n    {tool_call['function']['arguments']}\n"
                            tools_used[tool_call["id"]] = {
                                "id": tool_call["id"],
                                "name": tool_call["function"]["name"],
                                "args": json.loads(tool_call["function"]["arguments"]),
                                "type": "tool_call",
                            }
                            tool_call["name"] = tool_call["function"]["name"]
                            tool_call["args"] = json.loads(tool_call["function"]["arguments"])
                            tool_call["type"] = "tool_call"

                elif role == "tool":
                    pretty_printed_steps += f"\n================================= Tool Message =================================\n"
                    pretty_printed_steps += f"Name: {msg.get('name')}\n\n{content}\n"
                    if msg.get("tool_call_id") in tools_used:
                        tools_used[msg["tool_call_id"]]["status"] = "success" # Assuming success if output is here
                        tools_used[msg["tool_call_id"]]["output"] = content


                response_custom_metadata = msg.get("response_custom_metadata", {})
                if response_custom_metadata and isinstance(response_custom_metadata, dict):
                    if "plan" in response_custom_metadata:
                        last_conversation_plan = detail_msg["content"] = response_custom_metadata["plan"]
                        detail_msg["role"] = "re-plan" if is_replan else "plan"
                        is_replan = True
                        detail_msg["type"] = "chat"
                    elif "response" in response_custom_metadata:
                        detail_msg["content"] = response_custom_metadata["response"]

            # Reverse additional_details to match the example's reversed order
            additional_details.reverse()

            is_plan_verifier_state = agent_steps_raw[-1].get("response_custom_metadata", {})
            is_plan_verifier_state = isinstance(is_plan_verifier_state, dict) and "plan" in is_plan_verifier_state

            final_response = additional_details[0]["content"] if not is_plan_verifier_state else ""
            if not isinstance(final_response, str):
                final_response = entry.get("final_response", "")
            additional_details[-1]["role"] = "user_query"

            parts = [{
                "type": "text",
                "data": {"content": final_response},
                "metadata": {}
            }]
            parts = additional_details[0].pop("parts", parts)
            show_canvas = False
            for sub_part in parts:
                if sub_part.get("type") != "text":
                    show_canvas = True
                    break


            # Adding other fields for consistency in response format
            final_formatted_conversation["query"] = user_query
            final_formatted_conversation["response"] = final_response
            ongoing_conversation.append(additional_details[-1])
            if final_response:
                ongoing_conversation.append(additional_details[0])
            final_formatted_conversation["parts"] = parts
            
            formatted_conversation_list.append({
                "user_query": user_query,
                "final_response": final_response,
                "tools_used": tools_used,
                "agent_steps": pretty_printed_steps.strip(),
                "response_time": response_time,
                "start_timestamp": start_timestamp,
                "additional_details": additional_details,
                "parts": parts,
                "show_canvas": show_canvas
            })

        if len(formatted_conversation_list) > 0:
            for part in formatted_conversation_list[-1]["parts"]:
                if part.get("type") not in ("text", "image"):
                    part["is_last"] = True

        if last_conversation_plan:
            final_formatted_conversation["plan"] = last_conversation_plan

        return final_formatted_conversation

    @staticmethod
    async def _format_google_adk_agent_history(gadk_chat_session: Session) -> Dict[str, Any]:
        """
        Formats the conversation history from a Google ADK chat session into a structured dictionary.

        Args:
            gadk_chat_session (Session): The Google ADK chat session containing events and state.
        Returns:
            Dict[str, Any]: A dictionary representing the formatted conversation history.
        """

        FEEDBACK_KEYWORD = "FEEDBACK:"

        def get_message_pretty_string(message: Any, msg_type: Literal["human", "ai", "tool", "chat"]) -> str:
            if hasattr(message, "model_dump"):
                message = message.model_dump()
                message = json.dumps(message, indent=2)

            if msg_type == "human":
                return f"\n================================ Human Message =================================\n\n{message}\n\n"
            elif msg_type == "ai":
                return f"\n================================== AI Message ==================================\n\n{message}\n\n"
            elif msg_type == "tool":
                return f"\n================================== Tool Message =================================\n\n{message}\n\n"
            elif msg_type == "chat":
                return f"\n================================= Chat Message =================================\n\n{message}\n\n"
            else:
                return f"\n==================================== Message ====================================\n\n{message}\n\n"

        def resolve_duplicate_nested_key(state: dict, key: str, default: Any = None) -> Any:
            val = state.get(key, default)
            if isinstance(val, dict) and len(val) == 1 and key in val:
                return val[key]
            return val

        def is_parts_for_feedback(parts: List[types.Part]) -> bool:
            if len(parts) != 2:
                return False
            if parts[0].text == FEEDBACK_KEYWORD and parts[1].text:
                return True
            return False

        def is_pending_status_response_for_tool_call(function_response: types.FunctionResponse) -> bool:
            response = function_response.response
            if isinstance(response, dict) and len(response) == 1 and "status" in response:
                status: str = response.get("status", "")
                pending_status_msg_prefix = "Pending tool confirmation for tool '"
                return status.startswith(pending_status_msg_prefix)
            return False

        def is_pending_tool_call(msg_dict: dict) -> bool:
            return all([msg_dict, msg_dict.get("type") == "ai", not msg_dict.get("content"), msg_dict.get("tool_calls")])

        plan_feedback_collector_tool = "get_user_approval_or_feedback"
        ignore_tool_call_names = [plan_feedback_collector_tool, "set_model_response", "exit_replanner_loop", "adk_request_confirmation"]
        executor_message = []
        ongoing_conversation = []
        cur_state = gadk_chat_session.state or {}
        final_formatted_conversation = {
            "query": cur_state.get("query", ""),
            "response": resolve_duplicate_nested_key(state=cur_state, key="response"),
            "past_conversation_summary": "",
            "executor_messages": executor_message,
            "ongoing_conversation": ongoing_conversation,
            "agentic_application_id": gadk_chat_session.app_name,
            "session_id": gadk_chat_session.id,
            "model_name": "",
            "start_timestamp": "",
            "end_timestamp": "",
            "reset_conversation": False,
            "errors": [],
            "parts": [],
            "response_formatting_flag": None,
            "context_flag": None,
            "validation_score": None,
            "validation_feedback": None,
            "mentioned_agent_id": None,
            "preference": "",
            "is_tool_interrupted": None,
            "evaluation_score": None,
            "evaluation_feedback": None,
            "workflow_description": "",
        }

        if "plan" in cur_state:
            final_formatted_conversation["plan"] = resolve_duplicate_nested_key(state=cur_state, key="plan")

        events = gadk_chat_session.events
        if not events:
            return final_formatted_conversation
        
        # Segment events by invocation_id and process each invocation
        log.info(f"Formatting {len(events)} events from Google ADK session '{gadk_chat_session.id}'")
        current_invocation_id: str = None
        segmented_events: List[List[Event]] = []
        for event in events:
            if event.invocation_id != current_invocation_id:
                current_invocation_id = event.invocation_id
                parts = event.content.parts
                if not is_parts_for_feedback(parts):
                    segmented_events.append([])
            segmented_events[-1].append(event)


        # Process each invocation's Events to build executor messages and ongoing conversation
        log.info(f"Processing {len(segmented_events)} invocations from segmented events")
        empty_part = [{"type": "text", "data": {"content": ""}, "metadata": {}}]
        for invocation_events in segmented_events:
            query_event = invocation_events[0]
            user_query = query_event.content.parts[0].text
            tools_used: Dict[str, Dict[str, Any]] = {}
            additional_details = [{
                "content": user_query,
                "additional_kwargs": {},
                "type": "human",
                "name": None,
                "id": query_event.id,
                "role": "user_query"
            }]
            start_timestamp = query_event.timestamp
            end_timestamp = invocation_events[-1].timestamp
            datetime_start_timestamp = datetime.fromtimestamp(start_timestamp)
            datetime_end_timestamp = datetime.fromtimestamp(end_timestamp)
            final_formatted_conversation["start_timestamp"] = datetime_start_timestamp
            final_formatted_conversation["end_timestamp"] = datetime_end_timestamp

            new_invocation = {
                "user_query": user_query,
                "final_response": "",
                "tools_used": tools_used,
                "agent_steps": get_message_pretty_string(user_query, "human"),
                "additional_details": additional_details,
                "parts": empty_part,
                "show_canvas": False,
                "response_time": end_timestamp - start_timestamp,
                "st_time_stamp": datetime_start_timestamp,
                "time_stamp": datetime_end_timestamp
            }
            executor_message.append(new_invocation)
            ongoing_conversation.append(additional_details[0])


            log.debug(f"Processing invocation with query: '{user_query}' and {len(invocation_events)} events")
            final_response_msg: Dict[str, Any] = None
            for event in invocation_events:
                content = event.content
                if not content or not content.parts or event.id == query_event.id:
                    continue

                author = event.author or ""
                state_delta = event.actions.state_delta or {}
                usage_metadata = event.usage_metadata

                for part in content.parts:
                    current_msg = {
                        "content": "",
                        "additional_kwargs": {},
                        "type": "",
                        "name": None,
                        "id": event.id,
                    }
                    if usage_metadata:
                        current_msg["usage_metadata"] = usage_metadata.model_dump()

                    if part.function_call:
                        func_call = part.function_call
                        if func_call.name in ignore_tool_call_names:
                            continue
                        current_msg["type"] = "ai"
                        current_msg["tool_calls"] = [func_call.model_dump()]
                        current_msg["tool_calls"][0]["type"] = "tool_call"
                        current_msg["additional_kwargs"]["tool_calls"] = [{
                            "id": func_call.id,
                            "function": {
                                "arguments": json.dumps(func_call.args),
                                "name": func_call.name
                            },
                            "type": "function"
                        }]
                        tools_used[func_call.id] = func_call.model_dump()
                        tools_used[func_call.id].update({
                            "type": "tool_call",
                            "status": "unknown",
                            "output": None
                        })
                        new_invocation["agent_steps"] += get_message_pretty_string(func_call, current_msg["type"])

                    elif part.function_response:
                        func_resp = part.function_response
                        if func_resp.name == plan_feedback_collector_tool:
                            # Append feedback as a chat message
                            feedback = func_resp.response.get("result", "")
                            if str(feedback).lower() == "approved":
                                continue
                            current_msg["content"] = feedback
                            current_msg["type"] = "chat"
                            current_msg["role"] = "re-plan-feedback"
                            new_invocation["agent_steps"] += get_message_pretty_string(feedback, current_msg["type"])
                        elif func_resp.name in ignore_tool_call_names or is_pending_status_response_for_tool_call(func_resp):
                            continue
                        else:
                            current_msg["content"] = func_resp.response.get("result", func_resp.response)
                            current_msg["type"] = "tool"
                            current_msg["name"] = func_resp.name
                            current_msg["tool_call_id"] = func_resp.id
                            current_msg["status"] = "success"
                            tools_used[func_resp.id]["status"] = "success"
                            tools_used[func_resp.id]["output"] = func_resp.response.get("result", func_resp.response)
                            new_invocation["agent_steps"] += get_message_pretty_string(func_resp, current_msg["type"])

                    elif "plan" in state_delta:
                        final_response_msg = None
                        new_invocation["final_response"] = ""
                        new_invocation["parts"] = empty_part
                        new_invocation["show_canvas"] = False
                        plan = resolve_duplicate_nested_key(state_delta, "plan")
                        if not plan:
                            continue
                        current_msg["content"] = plan
                        current_msg["type"] = "chat"
                        current_msg["role"] = "plan"
                        new_invocation["agent_steps"] += get_message_pretty_string(plan, current_msg["type"])

                    elif "response" in state_delta and state_delta.get("response", None):
                        response_content = str(resolve_duplicate_nested_key(state_delta, "response"))
                        current_msg["content"] = response_content
                        current_msg["type"] = "ai"
                        current_msg["tool_calls"] = []
                        final_response_msg = current_msg
                        new_invocation["final_response"] = response_content
                        new_invocation["agent_steps"] += get_message_pretty_string(response_content, current_msg["type"])
                        canvas_parts = [{"type": "text", "data": {"content": response_content}, "metadata": {}}]
                        new_invocation["parts"] = canvas_parts
                        new_invocation["show_canvas"] = False

                    elif "evaluation_result" in state_delta:
                        evaluation_result = state_delta.get("evaluation_result", {})
                        evaluation_result["evaluation_aggregate_score"] = evaluation_result.pop("aggregate_score", None)
                        current_msg["content"] = [evaluation_result]
                        current_msg["type"] = "chat"
                        current_msg["role"] = "evaluator-response"
                        new_invocation["agent_steps"] += get_message_pretty_string(evaluation_result, current_msg["type"])

                    elif "validation_result" in state_delta:
                        evaluation_result = state_delta.get("validation_result", {})
                        current_msg["content"] = [evaluation_result]
                        current_msg["type"] = "chat"
                        current_msg["role"] = "validator-response"
                        new_invocation["agent_steps"] += get_message_pretty_string(evaluation_result, current_msg["type"])

                    elif "critic_response" in state_delta:
                        critic_response = state_delta.get("critic_response", {})
                        current_msg["content"] = [critic_response]
                        current_msg["type"] = "chat"
                        current_msg["role"] = "critic-response"
                        new_invocation["agent_steps"] += get_message_pretty_string(critic_response, current_msg["type"])

                    elif "canvas_parts" in state_delta:
                        canvas_parts = state_delta.get("canvas_parts", {}).get("parts", [])
                        canvas_parts = json.loads(canvas_parts)
                        new_invocation["parts"] = canvas_parts
                        for canvas_part in canvas_parts:
                            if canvas_part.get("type", None) != "text":
                                new_invocation["show_canvas"] = True
                                break
                        continue

                    elif content.role == "model":
                        current_msg["content"] = part.text
                        current_msg["type"] = "ai"
                        current_msg["tool_calls"] = []
                        new_invocation["agent_steps"] += get_message_pretty_string(part.text, current_msg["type"])

                    elif is_parts_for_feedback(content.parts):
                        if part.text == FEEDBACK_KEYWORD:
                            continue
                        current_msg["content"] = part.text
                        current_msg["type"] = "chat"
                        current_msg["role"] = "feedback"
                        new_invocation["agent_steps"] += get_message_pretty_string(part.text, current_msg["type"])
                        new_invocation["response_time"] = end_timestamp - event.timestamp

                    else:
                        current_msg["content"] = part.text
                        current_msg["type"] = "human"
                        new_invocation["agent_steps"] += get_message_pretty_string(part.text, current_msg["type"])

                    additional_details.append(current_msg)

            if final_response_msg:
                ongoing_conversation.append(final_response_msg)
                if is_pending_tool_call(additional_details[-1]):
                    new_invocation["final_response"] = ""
                    new_invocation["parts"] = empty_part
                    new_invocation["show_canvas"] = False

                elif final_response_msg != additional_details[-1]:
                    additional_details.append(final_response_msg)
            additional_details.reverse()

        last_executor_message = executor_message[-1]
        # final_formatted_conversation["query"] = last_executor_message["user_query"]
        # final_formatted_conversation["response"] = last_executor_message["final_response"]
        final_formatted_conversation["parts"] = last_executor_message["parts"]

        for canvas_part in last_executor_message["parts"]:
            if canvas_part.get("type") not in ("text", "image"):
                canvas_part["is_last"] = True
        log.debug(f"Formatted conversation from Google ADK session '{gadk_chat_session.id}' successfully.")
        return final_formatted_conversation

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


    async def save_feedback(self, agent_id: str, query: str, old_final_response: str, old_steps: str, feedback: str, new_final_response: str, new_steps: str, lesson: str, status: str = 'pending', department_name:str = None) -> Dict[str, Any]:
        """
        Saves new feedback data, including the feedback response and its mapping to an agent.
        status should be one of: 'pending', 'approve', 'reject'
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
            status=status, 
            lesson=lesson,
            department_name=department_name
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

    async def get_approved_feedback(self, agent_id: str, department_name: str = None) -> List[Dict[str, Any]]:
        """
        Retrieves approved feedback for a specific agent, optionally filtered by department.
        """
        return await self.repo.get_approved_feedback_records(agent_id, department_name=department_name)

    async def get_all_approvals_for_agent(self, agent_id: str, department_name:str=None) -> List[Dict[str, Any]]:
        """
        Retrieves all feedback and their approval status for a given agent_id.
        """
        return await self.repo.get_all_feedback_records_by_agent(agent_id, department_name=department_name)

    async def get_feedback_details_by_response_id(self, response_id: str, department_name:str = None) -> List[Dict[str, Any]]:
        """
        Retrieves all details for a specific feedback response, including agent name.
        """
        feedback_records = await self.repo.get_feedback_record_by_response_id(response_id, department_name=department_name)
        for feedback_record in feedback_records:
            agent_id = feedback_record.get("agent_id", "")
            agent_details_list = await self.agent_service.get_agent(agentic_application_id=agent_id)
            agent_name = agent_details_list[0].get("agentic_application_name", "Unknown") if agent_details_list else "Unknown"
            feedback_record["agent_name"] = agent_name
        log.info(f"Retrieved feedback details for response_id: {response_id}.")
        return feedback_records

    async def get_agents_with_feedback(self, department_name: str = None) -> List[Dict[str, Any]]:
        """
        Retrieves all agents who have given feedback along with their names.
        Only returns agents that exist in the main database (batch query, no N+1).
        """
        valid_agent_ids = await self._get_valid_agent_ids_for_department(department_name)
        if not valid_agent_ids:
            return []
        agent_records = await self.agent_service.agent_repo.get_agent_records_by_ids(valid_agent_ids)
        agent_data = [
            {
                "agent_id": a["agentic_application_id"],
                "agent_name": a.get("agentic_application_name", "Unknown"),
                "agent_type": a.get("agentic_application_type", "Unknown"),
            }
            for a in agent_records
        ]
        log.info(f"Retrieved {len(agent_data)} agents with feedback (existing agents only).")
        return agent_data

    async def update_feedback_status(self, response_id: str, update_data: Dict[str, Any], department_name: str=None) -> Dict[str, Any]:
        """
        Updates fields in a feedback_response record.
        `update_data` should be a dictionary with keys as column names and values as the new values.
        """
        success = await self.repo.update_feedback_record(response_id, update_data, department_name=department_name)
        if success:
            return {"is_update": True, "message": "Feedback updated successfully."}
        else:
            return {"is_update": False, "message": "Failed to update feedback."}

    async def _get_valid_agent_ids_for_feedback(self, feedback_agent_ids: List[str]) -> List[str]:
        """
        Returns agent_ids that exist in the main database (agent_table).
        """
        if not feedback_agent_ids:
            return []
        agent_records = await self.agent_service.agent_repo.get_agent_records_by_ids(feedback_agent_ids)
        return [a["agentic_application_id"] for a in agent_records]

    async def _get_valid_agent_ids_for_department(self, department_name: str = None) -> List[str]:
        """
        Gets distinct agent_ids from feedback for the department, then filters to only those that exist in main DB.
        """
        distinct_agent_ids = await self.repo.get_distinct_agents_with_feedback(department_name=department_name)
        return await self._get_valid_agent_ids_for_feedback(distinct_agent_ids)

    async def get_all_feedback_records(self, department_name: str = None) -> List[Dict[str, Any]]:
        """
        Retrieves all feedback records only for agents that exist in the main database.
        Uses batch queries (no N+1). Enriches each record with agent name and type.
        """
        valid_agent_ids = await self._get_valid_agent_ids_for_department(department_name)
        if not valid_agent_ids:
            return []
        feedback_records = await self.repo.get_all_feedback_records(department_name=department_name, agent_ids=valid_agent_ids)
        agent_records = await self.agent_service.agent_repo.get_agent_records_by_ids(valid_agent_ids)
        agent_map = {a["agentic_application_id"]: a for a in agent_records}
        for record in feedback_records:
            agent_id = record.get("agent_id", "")
            agent_info = agent_map.get(agent_id, {})
            record["agent_name"] = agent_info.get("agentic_application_name", "Unknown")
            record["agent_type"] = agent_info.get("agentic_application_type", "Unknown")
        log.info(f"Retrieved {len(feedback_records)} feedback records (existing agents only).")
        return feedback_records

    async def get_all_feedback_records_with_count(self, department_name: str = None) -> Dict[str, Any]:
        """
        Retrieves all feedback records and total count for agents that exist in the main database.
        Fetches valid_agent_ids once to avoid duplicate lookups.
        """
        valid_agent_ids = await self._get_valid_agent_ids_for_department(department_name)
        if not valid_agent_ids:
            return {"feedback_list": [], "total_count": 0}
        feedback_records = await self.repo.get_all_feedback_records(department_name=department_name, agent_ids=valid_agent_ids)
        total_count = await self.repo.get_total_feedback_count(department_name=department_name, agent_ids=valid_agent_ids)
        agent_records = await self.agent_service.agent_repo.get_agent_records_by_ids(valid_agent_ids)
        agent_map = {a["agentic_application_id"]: a for a in agent_records}
        for record in feedback_records:
            agent_id = record.get("agent_id", "")
            agent_info = agent_map.get(agent_id, {})
            record["agent_name"] = agent_info.get("agentic_application_name", "Unknown")
            record["agent_type"] = agent_info.get("agentic_application_type", "Unknown")
        log.info(f"Retrieved {len(feedback_records)} feedback records with count {total_count} (existing agents only).")
        return feedback_records

    async def get_total_feedback_count(self, department_name: str = None) -> int:
        """
        Returns the total count of feedback records for agents that exist in the main database.
        """
        valid_agent_ids = await self._get_valid_agent_ids_for_department(department_name)
        return await self.repo.get_total_feedback_count(department_name=department_name, agent_ids=valid_agent_ids)

    async def get_approved_feedback_count(self, department_name: str = None) -> int:
        """
        Returns the count of approved feedback records for agents that exist in the main database.
        """
        valid_agent_ids = await self._get_valid_agent_ids_for_department(department_name)
        return await self.repo.get_approved_feedback_count(department_name=department_name, agent_ids=valid_agent_ids)

    async def get_pending_feedback_count(self, department_name: str = None) -> int:
        """
        Returns the count of pending feedback records for agents that exist in the main database.
        """
        valid_agent_ids = await self._get_valid_agent_ids_for_department(department_name)
        return await self.repo.get_pending_feedback_count(department_name=department_name, agent_ids=valid_agent_ids)


    async def get_rejected_feedback_count(self, department_name: str = None) -> int:
        """
        Returns the count of rejected feedback records, optionally filtered by department.
        """
        return await self.repo.get_pending_feedback_count(department_name=department_name)

    async def get_agents_with_feedback_count(self, department_name: str = None) -> int:
        """
        Returns the count of distinct agents (that exist in main DB) that have associated feedback.
        """
        valid_agent_ids = await self._get_valid_agent_ids_for_department(department_name)
        return await self.repo.get_agents_with_feedback_count(department_name=department_name, agent_ids=valid_agent_ids)

    async def get_feedback_stats(self, department_name: str = None) -> Dict[str, Any]:
        """
        Returns aggregated feedback statistics including total, approved, pending, rejected counts and agent count.
        """
        valid_agent_ids = await self._get_valid_agent_ids_for_department(department_name)
        stats = await self.repo.get_feedback_stats(department_name=department_name, agent_ids=valid_agent_ids)
        log.info(f"Retrieved feedback stats: {stats}")
        return stats

    async def delete_feedback_by_agent_id(self, agent_id: str) -> Dict[str, Any]:
        """
        Deletes all feedback/learning records for a specific agent.
        
        Args:
            agent_id (str): The ID of the agent whose feedback records should be deleted.
            
        Returns:
            Dict[str, Any]: A dictionary with status, message, and count of deleted records.
        """
        result = await self.repo.delete_feedback_by_agent_id(agent_id)
        if result.get("status") == "success":
            log.info(f"Successfully deleted feedback for agent_id: {agent_id}. Deleted count: {result.get('deleted_count', 0)}")
        else:
            log.error(f"Failed to delete feedback for agent_id: {agent_id}. Error: {result.get('message')}")
        return result


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
            elif isinstance(msg, dict) and "agent_steps" not in msg:
                serialized.append(msg)
            else:
                serialized.append(str(msg))   # last resort
        return serialized

    async def log_evaluation_data(self, session_id: str, agentic_application_id: str, agent_config: Dict[str, Any], response: Dict[str, Any], model_name: str) -> bool:
        """
        Logs raw inference data into the evaluation_data table.
        """
        agent_last_step = response.get("executor_messages", [{}])[-1].get("agent_steps", [{}])[-1]

        if not response.get('response') or (hasattr(agent_last_step, "role") and agent_last_step.role == 'plan') \
            or (isinstance(agent_last_step, dict) and ("plan" in agent_last_step or "re-plan" in agent_last_step)):
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
            data_to_log["department"] = agent_details.get('department_name', 'General')  # Add department field
            
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
                original_query_content = ""
                if data_to_log["steps"]:
                    original_query_content = data_to_log["steps"][0]["content"] if isinstance(data_to_log["steps"][0], dict) else data_to_log["steps"][0].content
                data_to_log['query'] = f"Query:{original_query_content}\nFeedback: {feedback_content}"

            elif data_to_log['query'].startswith("[regenerate:]"):
                original_query_content = ""
                if data_to_log["steps"]:
                    original_query_content = data_to_log["steps"][0]["content"] if isinstance(data_to_log["steps"][0], dict) else data_to_log["steps"][0].content
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

    async def fetch_next_unprocessed_evaluation(self, user: Optional[User]) -> Dict[str, Any] | None:
        """
        Fetches the next unprocessed evaluation entry with department-based filtering.
        - SuperAdmin: Can access all unprocessed evaluations
        - Admin: Can access unprocessed evaluations in their department
        - User: Can access unprocessed evaluations for agents they created in their department
        """
        if user and user.role == UserRole.SUPER_ADMIN:
            # SuperAdmin can access all unprocessed records
            record = await self.evaluation_data_repo.get_unprocessed_record()
        elif user and user.role == UserRole.ADMIN:
            # Admin can access unprocessed records in their department
            record = await self.evaluation_data_repo.get_unprocessed_record_by_department(user.department_name)
        else:
            # Regular users can only access records for agents they created
            record = await self.evaluation_data_repo.get_unprocessed_record_by_creator(user.email if user else "")

        if record:
            record['steps'] = json.loads(record['steps']) if isinstance(record['steps'], str) else record['steps']
            record['executor_messages'] = json.loads(record['executor_messages']) if isinstance(record['executor_messages'], str) else record['executor_messages']
            log.info(f"Fetched unprocessed evaluation entry with ID: {record['id']}.")
            return record

        return None

    async def count_unprocessed_evaluations(self, user: Optional[User]) -> int:
        """
        Counts unprocessed evaluations with department-based filtering.
        - SuperAdmin: Can count all unprocessed evaluations
        - Admin: Can count unprocessed evaluations in their department
        - User: Can count unprocessed evaluations for agents they created in their department
        """
        if user and user.role == UserRole.SUPER_ADMIN:
            # SuperAdmin can count all unprocessed records
            return await self.evaluation_data_repo.count_all_unprocessed_records()
        elif user and user.role == UserRole.ADMIN:
            # Admin can count unprocessed records in their department
            return await self.evaluation_data_repo.count_unprocessed_records_by_department(user.department_name)
        else:
            # Regular users can only count records for agents they created
            record = await self.evaluation_data_repo.get_unprocessed_record_by_creator(user.email if user else "")
            if not record:
                return 0

            agent_id = record.get("agent_id")
            if not agent_id:
                return 0

            return await self.evaluation_data_repo.count_unprocessed_records_by_agent_ids([agent_id])

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
        success = await self.agent_evaluation_metrics_repo.insert_metrics_record(metrics_data)
        if success:
            log.info(f"Agent Evaluation metrics inserted successfully for evaluation_id: {metrics_data.get('evaluation_id')}.")
        else:
            log.error(f"Failed to insert agent evaluation metrics for evaluation_id: {metrics_data.get('evaluation_id')}.")
        return success

    async def get_evaluation_data(self, user : Optional[User], agent_names: Optional[List[str]] = None, agent_types: Optional[List[str]] = None, page: int = 1, limit: int = 10) -> List[Dict[str, Any]]:
        """
        Retrieves evaluation data records.
        """
        return await self.evaluation_data_repo.get_records_by_agent_names(user, agent_names, agent_types, page, limit)

    async def get_tool_metrics(self, user: Optional[User], agent_names: Optional[List[str]] = None, agent_types: Optional[List[str]] = None, page: int = 1, limit: int = 10) -> List[Dict[str, Any]]:
        """
        Retrieves tool evaluation metrics records.
        """
        return await self.tool_evaluation_metrics_repo.get_metrics_by_agent_names(user, agent_names, agent_types, page, limit)

    async def get_agent_metrics(self, user: Optional[User], agent_names: Optional[List[str]] = None, agent_types: Optional[List[str]] = None, page: int = 1, limit: int = 10) -> List[Dict[str, Any]]:
        """
        Retrieves agent evaluation metrics records.
        """
        return await self.agent_evaluation_metrics_repo.get_metrics_by_agent_names(user, agent_names, agent_types, page, limit)


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





#---------------- Consistency and Robustness services---------------------------#


# Define constants at the module level for clarity
UPLOAD_DIR = Path("evaluation_uploads")
RESPONSES_TEMP_DIR = Path("responses_temp")
# IST = timezone("Asia/Kolkata")

# Ensure directories exist
UPLOAD_DIR.mkdir(exist_ok=True)
RESPONSES_TEMP_DIR.mkdir(exist_ok=True)

# This lock protects database operations during the critical 'approve' phase
DB_OPERATION_LOCK = asyncio.Lock()


class ConsistencyService:
    """
    Service layer for handling the consistency evaluation workflow.
    This includes previewing, re-running, and approving agent responses.
    """

    def __init__(
        self,
        metadata_repo: AgentMetadataRepository,
        data_repo: AgentDataTableRepository,
        
    ):
        self.metadata_repo = metadata_repo
        self.data_repo = data_repo
       



    async def upsert_agent_record(self, agent_id: str, agent_name: str, agent_type: str, model_name: str, department_name: str = None, created_by: str = None):
        return await self.metadata_repo.upsert_agent_record(agent_id, agent_name, agent_type, model_name, department_name=department_name, created_by=created_by)

    async def get_agent_by_id(self, agent_id: str, user: Optional[User] = None) -> Optional[Dict[str, Any]]:
        """
        Get agent by ID with user permission validation.
        """
        agent = await self.metadata_repo.get_agent_by_id(agent_id)
        if not agent:
            return None
        
        # Check if user has permission to access this agent (always filter by department)
        if user:
            if agent.get('department_name') != user.department_name:
                return None
        
        return agent

    async def get_agents_to_reevaluate(self, interval_minutes: int) -> list:
        return await self.metadata_repo.get_agents_to_reevaluate(interval_minutes)

    async def get_agents_for_robustness_reeval(self, interval_minutes: int) -> list:
        return await self.metadata_repo.get_agents_for_robustness_reeval(interval_minutes)

    async def update_evaluation_timestamp(self, agent_id: str):
        return await self.metadata_repo.update_evaluation_timestamp(agent_id)

    async def update_robustness_timestamp(self, agent_id: str):
        return await self.metadata_repo.update_robustness_timestamp(agent_id)

    async def update_queries_timestamp(self, agent_id: str):
        return await self.metadata_repo.update_queries_timestamp(agent_id)

    async def update_agent_model_in_db(self, agent_id: str, model_name: str):
        return await self.metadata_repo.update_agent_model_in_db(agent_id, model_name)

    async def delete_agent_record_from_main_table(self, agent_id: str):
        return await self.metadata_repo.delete_agent_record_from_main_table(agent_id)

    async def fetch_agent_context(self, agentic_id: str) -> Optional[Dict[str, Any]]:
        return await self.metadata_repo.fetch_agent_context(agentic_id)

    # ===================================================================
    #           PASS-THROUGH METHODS FOR AgentDataTableRepository
    # ===================================================================

    async def create_and_insert_initial_data(self, table_name: str, df: pd.DataFrame, col_name: str):
        return await self.data_repo.create_and_insert_initial_data(table_name, df, col_name)

    async def create_and_insert_robustness_data(self, table_name: str, dataset: list, res_col: str, score_col: str):
        return await self.data_repo.create_and_insert_robustness_data(table_name, dataset, res_col, score_col)

    async def create_and_insert_robustness_data_initial(self, agent_id: str, dataset: list):
        return await self.data_repo.create_and_insert_robustness_data_initial(agent_id, dataset)

    async def get_full_data_as_dataframe(self, table_name: str) -> pd.DataFrame:
        return await self.data_repo.get_full_data_as_dataframe(table_name)

    async def get_approved_queries_from_db(self, agentic_application_id: str) -> list:
        return await self.data_repo.get_approved_queries_from_db(agentic_application_id)

    async def get_latest_response_column_name(self, table_name: str) -> Optional[str]:
        return await self.data_repo.get_latest_response_column_name(table_name)

    async def add_column_to_agent_table(self, table_name: str, new_column_name: str, column_type: str = "TEXT"):
        return await self.data_repo.add_column_to_agent_table(table_name, new_column_name, column_type)

    async def rename_column_with_timestamp(self, table_name: str, old_name: str, timestamp: str, new_suffix: str):
        return await self.data_repo.rename_column_with_timestamp(table_name, old_name, timestamp, new_suffix)

    async def update_data_in_agent_table(self, table_name: str, column_name: str, data_to_update: list):
        return await self.data_repo.update_data_in_agent_table(table_name, column_name, data_to_update)

    async def update_column_by_row_id(self, table_name: str, column_name: str, new_data_list: list):
        return await self.data_repo.update_column_by_row_id(table_name, column_name, new_data_list)

    async def drop_agent_results_table(self, table_name: str):
        return await self.data_repo.drop_agent_results_table(table_name)



    async def create_evaluation_table_if_not_exists(self):
        """
        Orchestrates the creation of all evaluation-related tables.
        """
        await self.metadata_repo.create_agent_consistency_robustness()
      
        log.info("All tables checked/created successfully.")

    def _get_temp_paths(self, agent_id: str) -> Tuple[Path, Path]:
        """Generates the standard temporary file paths for an agent session."""
        base = RESPONSES_TEMP_DIR / f"{agent_id}"
        xlsx_path = base.with_suffix(".xlsx")
        meta_path = base.with_suffix(".meta.json")
        return xlsx_path, meta_path

   


    async def get_approved_queries(self, agent_id: str) -> list:
        """Fetches the approved queries for an agent from its consistency table."""
        return await self.data_repo.get_approved_queries_from_db(agent_id)

    async def create_and_insert_robustness_table_data(self, agent_id: str, dataset: list, response_col: str, score_col: str):
        """Creates/replaces the robustness results table for an agent with new data."""
        return await self.data_repo.create_and_insert_robustness_data(agent_id, dataset, response_col, score_col)

    

    async def get_all_agents(self, user: Optional[User] = None, agent_type: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        Retrieves a list of all agent evaluation records based on user permissions.
        - Admin: All agents in their department
        - Developer: Only agents they created in their department
        
        Optionally filter by agent_type.
        """
        # Strip quotes if user accidentally included them in the filter
        if agent_type:
            agent_type = agent_type.strip('"').strip("'")
        log.info(f"Service layer: fetching agent records. agent_type filter: {agent_type}")
        return await self.data_repo.get_all_agent_records(user, agent_type=agent_type)
    
    async def get_all_consistency_records(self, table_name):
        """
        Retrieves all records from consistency table.
        """
        log.info("Service layer: fetching all records.")
        return await self.data_repo.get_all_consistency_records(table_name)
    
    async def get_all_robustness_records(self, table_name):
        """
        Retrieves all records from consistency table.
        """
        log.info("Service layer: fetching all records.")
        return await self.data_repo.get_all_robustness_records(table_name)

    
    async def get_agents_with_recent_consistency_scores(self, days: int = 5):
        agents = await self.get_all_agents()
        enriched = []

        for agent in agents:
            agent_id = agent["agent_id"]
            table_name = agent_id  # assuming table name = agent_id
            try:
                recent_scores = await self.data_repo.get_recent_consistency_scores(table_name, days)
                agent["recent_scores"] = recent_scores
            except Exception as e:
                log.warning(f"Could not fetch scores for agent {agent_id}: {e}")
                agent["recent_scores"] = []
            enriched.append(agent)

        return enriched



    async def get_last_5_consistency_rows(self, rows: List[Dict]) -> List[Dict]:
        from collections import defaultdict

        def flatten_scores(row: Dict) -> List[Dict]:
            row_id = row.get("id")
            query = row.get("queries")
            flattened = []

            for key in row.keys():
                if key.endswith("_score"):
                    try:
                        timestamp_str = key.replace("_score", "")
                        timestamp = datetime.strptime(timestamp_str, "%Y-%m-%d_%H-%M-%S")
                        score = row[key]
                        response_key = f"{timestamp_str}_response"
                        response = row.get(response_key, "")
                        flattened.append({
                            "id": row_id,
                            "query": query,
                            "timestamp": timestamp,
                            "score": score,
                            "response": response
                        })
                    except ValueError:
                        continue
            return flattened

        # Step 1: Flatten all rows
        all_flattened = []
        for row in rows:
            all_flattened.extend(flatten_scores(row))

        # Step 2: Group by 'id'
        grouped_by_id = defaultdict(list)
        for entry in all_flattened:
            grouped_by_id[entry["id"]].append(entry)

        # Step 3: Sort and merge into single dict per ID
        final_result = []
        for row_id, entries in grouped_by_id.items():
            sorted_entries = sorted(entries, key=lambda x: x["timestamp"], reverse=True)[:5]
            merged = {"id": row_id, "query": sorted_entries[0]["query"]}
            for i, entry in enumerate(sorted_entries, start=1):
                merged[f"timestamp_{i}"] = entry["timestamp"].isoformat()
                merged[f"score_{i}"] = entry["score"]
                merged[f"response_{i}"] = entry["response"]
            final_result.append(merged)

        return final_result
    
    async def get_last_5_robustness_rows(self, rows: List[Dict]) -> List[Dict]:
        """
        Flattens rows containing multiple timestamped score/response pairs into individual entries,
        groups them by 'id', and returns a single dictionary per id with last 5 entries inline.
        """

        def flatten_scores(row: Dict) -> List[Dict]:
            row_id = row.get("id")
            query = row.get("query")
            category = row.get("category")
            flattened = []

            for key in row.keys():
                if key.endswith("_score"):
                    try:
                        timestamp_str = key.replace("_score", "")
                        timestamp = datetime.strptime(timestamp_str, "%Y-%m-%d_%H-%M-%S")
                        score = row[key]
                        response_key = f"{timestamp_str}_response"
                        response = row.get(response_key, "")
                        flattened.append({
                            "id": row_id,
                            "query": query,
                            "category": category,
                            "timestamp": timestamp,
                            "score": score,
                            "response": response
                        })
                    except ValueError:
                        continue
            return flattened

        # Step 1: Flatten all rows
        all_flattened = []
        for row in rows:
            all_flattened.extend(flatten_scores(row))

        # Step 2: Group by 'id'
        from collections import defaultdict
        grouped_by_id = defaultdict(list)
        for entry in all_flattened:
            grouped_by_id[entry["id"]].append(entry)

        # Step 3: Sort and merge into single dict per ID
        final_result = []
        for row_id, entries in grouped_by_id.items():
            sorted_entries = sorted(entries, key=lambda x: x["timestamp"], reverse=True)[:5]
            merged = {
                "id": row_id,
                "query": sorted_entries[0]["query"],
                "category": sorted_entries[0]["category"]
            }
            for i, entry in enumerate(sorted_entries, start=1):
                merged[f"timestamp_{i}"] = entry["timestamp"].isoformat()
                merged[f"score_{i}"] = entry["score"]
                merged[f"response_{i}"] = entry["response"]
            final_result.append(merged)

        return final_result
    

class VMManagementService:
    """Manages package installation and server operations for VMs and localhost environments."""
    
    def __init__(self):
        pass
    
    def validate_module_name(self, module: str) -> Dict[str, Any]:
        """
        Validates if a module name is safe to install.
        Returns dict with 'valid' boolean and 'error' message if invalid.
        """
        if not module or not module.strip():
            return {"valid": False, "error": "Empty module name"}
        pkg_name = module.split('==')[0].split('>=')[0].split('<=')[0].split('!=')[0].split('[')[0].strip().lower()
        import re
        if not re.match(r'^[a-zA-Z0-9]([a-zA-Z0-9\-_\.]*[a-zA-Z0-9])?$', pkg_name):
            return {"valid": False, "error": f"Invalid package name format: '{pkg_name}'"}
        
        return {"valid": True, "error": None}
    
    def parse_module_version(self, module: str) -> tuple:
        """
        Parses module string into (package_name, version_specifier, version).
        Returns (pkg_name, operator, version) or (pkg_name, None, None) if no version specified.
        """
        import re
        module = module.split('[')[0].strip()
        match = re.match(r'^([a-zA-Z0-9\-_\.]+)\s*(==|>=|<=|!=|~=|>|<)?\s*(.*)$', module)
        if match:
            pkg_name = match.group(1).strip()
            operator = match.group(2)
            version = match.group(3).strip() if match.group(3) else None
            return (pkg_name, operator, version)
        
        return (module.strip(), None, None)
    
    def remove_duplicates(self, modules: List[str]) -> tuple:
        """
        Removes exact duplicate modules from the list.
        """
        seen = set()
        unique_modules = []
        duplicates = []
        
        for module in modules:
            if module in seen:
                original_module = module 
                duplicates.append({
                    "package": self.parse_module_version(module)[0],
                    "original": original_module,
                    "duplicate": module
                })
            else:
                seen.add(module)
                unique_modules.append(module)
        
        return (unique_modules, duplicates)
    
    # async def install_dependencies(self, modules: List[str]) -> Dict[str, Any]:
    #     """Install Python modules using current Python environment."""
    #     try:
    #         import subprocess
    #         import sys
    #     except ImportError as e:
    #         return {
    #             "success": False,
    #             "message": "Required libraries not available",
    #             "error": str(e)
    #         }

    #     try:
    #         if not modules:
    #             return {
    #                 "success": False,
    #                 "message": "No modules provided",
    #                 "error": "Please provide at least one module to install"
    #             }

    #         processed_modules = []
    #         for module in modules:
    #             if isinstance(module, str) and ',' in module:
    #                 split_modules = [m.strip() for m in module.split(',') if m.strip()]
    #                 processed_modules.extend(split_modules)
    #             else:
    #                 processed_modules.append(module.strip() if isinstance(module, str) else module)

    #         processed_modules = [m for m in processed_modules if m]
            
    #         if not processed_modules:
    #             return {
    #                 "success": False,
    #                 "message": "No valid modules provided after processing",
    #                 "error": "Please provide at least one valid module to install"
    #             }

    #         validation_errors = []
    #         for module in processed_modules:
    #             validation_result = self.validate_module_name(module)
    #             if not validation_result["valid"]:
    #                 validation_errors.append(validation_result["error"])
            
    #         if validation_errors:
    #             return {
    #                 "success": False,
    #                 "message": "Module validation failed",
    #                 "error": "; ".join(validation_errors),
    #                 "validation_errors": validation_errors
    #             }
    #         unique_modules, duplicates = self.remove_duplicates(processed_modules)
    #         modules_to_install = []
    #         already_installed = []
    #         version_conflicts = []
            
    #         for module in unique_modules:
    #             pkg_name, operator, requested_version = self.parse_module_version(module)
                
    #             try:
    #                 check_result = subprocess.run(
    #                     [sys.executable, "-m", "pip", "show", pkg_name],
    #                     capture_output=True,
    #                     text=True,
    #                     timeout=30
    #                 )
                    
    #                 if check_result.returncode == 0:
    #                     installed_version = None
    #                     for line in check_result.stdout.split('\n'):
    #                         if line.startswith("Version:"):
    #                             installed_version = line.split("Version:")[1].strip()
    #                             break
                        
    #                     if installed_version:
    #                         if requested_version and operator == '==' and installed_version != requested_version:
    #                             version_conflicts.append({
    #                                 "package": pkg_name,
    #                                 "installed_version": installed_version,
    #                                 "requested_version": requested_version
    #                             })
    #                         else:
    #                             already_installed.append(f"{pkg_name}=={installed_version}")
    #                     else:
    #                         already_installed.append(pkg_name)
    #                 else:
    #                     modules_to_install.append(module)
                        
    #             except Exception as e:
    #                 modules_to_install.append(module)
    #         if version_conflicts:
    #             if len(version_conflicts) == 1:
    #                 conflict = version_conflicts[0]
    #                 if len(already_installed) > 0:
    #                     already_list = ', '.join([f"'{mod.split('==')[0]}'" for mod in already_installed])
    #                     error_msg = f"Module '{conflict['package']}' already installed with version {conflict['installed_version']} but requested {conflict['requested_version']}. Already correctly installed: {already_list}"
    #                 else:
    #                     error_msg = f"Module '{conflict['package']}' already installed with version {conflict['installed_version']} but requested {conflict['requested_version']}"
    #             else:
    #                 if len(already_installed) > 0:
    #                     already_list = ', '.join([f"'{mod.split('==')[0]}'" for mod in already_installed])
    #                     error_msg = f"Version conflicts detected for {len(version_conflicts)} module(s). Already correctly installed: {already_list}"
    #                 else:
    #                     error_msg = f"Version conflicts detected for {len(version_conflicts)} module(s)"
                
    #             return {
    #                 "success": False,
    #                 "message": "Version conflict detected",
    #                 "error": error_msg,
    #                 "version_conflicts": version_conflicts,
    #                 "already_installed": already_installed,
    #                 "duplicates_removed": duplicates if duplicates else []
    #             }
    #         if not modules_to_install:
    #             if len(already_installed) == 1:
    #                 pkg_name = already_installed[0].split('==')[0]
    #                 message = f"Module '{pkg_name}' is already installed"
    #             else:
    #                 module_names = [pkg.split('==')[0] for pkg in already_installed]
    #                 message = f"Modules {', '.join(module_names)} are already installed"
                
    #             if duplicates:
    #                 message += f". Removed {len(duplicates)} duplicate(s) from request"
                
    #             return {
    #                 "success": False,
    #                 "message": message,
    #                 "already_installed": already_installed,
    #                 "modules_installed": [],
    #                 "duplicates_removed": duplicates if duplicates else [],
    #                 "skipped": True
    #             }

    #         install_result = subprocess.run(
    #             [sys.executable, "-m", "pip", "install"] + modules_to_install,
    #             capture_output=True,
    #             text=True,
    #             timeout=300
    #         )
            
    #         if install_result.returncode != 0:
    #             return {
    #                 "success": False,
    #                 "message": "Failed to install modules",
    #                 "error": install_result.stderr,
    #                 "stdout": install_result.stdout,
    #                 "already_installed": already_installed
    #             }
            
    #         if len(modules_to_install) == 1:
    #             message = f"Successfully installed '{modules_to_install[0]}'"
    #         else:
    #             installed_names = [m.split('==')[0] for m in modules_to_install]
    #             message = f"Successfully installed {', '.join(installed_names)}"
            
    #         if already_installed:
    #             if len(already_installed) == 1:
    #                 already_name = already_installed[0].split('==')[0]
    #                 message += f". '{already_name}' was already installed"
    #             else:
    #                 already_names = [pkg.split('==')[0] for pkg in already_installed]
    #                 message += f". {', '.join(already_names)} were already installed"
            
    #         return {
    #             "success": True,
    #             "message": message,
    #             "python_executable": sys.executable,
    #             "modules_installed": modules_to_install,
    #             "already_installed": already_installed,
    #             "duplicates_removed": duplicates if duplicates else [],
    #             "output": install_result.stdout
    #         }
            
    #     except subprocess.TimeoutExpired:
    #         return {
    #             "success": False,
    #             "message": "Installation timed out",
    #             "error": "The installation command took too long to complete"
    #         }
    #     except Exception as e:
    #         return {
    #             "success": False,
    #             "message": "Localhost installation failed",
    #             "error": str(e)
    #         }

    async def get_installed_packages(self) -> Dict[str, Any]:
        """Get installed Python packages from current Python environment."""
        try:
            import subprocess
            import sys
        except ImportError as e:
            return {
                "success": False,
                "message": "Required libraries not available",
                "error": str(e),
                "packages": []
            }
        try:
            list_result = subprocess.run(
                [sys.executable, "-m", "pip", "list", "--format=freeze"],
                capture_output=True,
                text=True,
                timeout=60
            )
            
            if list_result.returncode != 0:
                return {
                    "success": False,
                    "message": "Failed to list packages on localhost",
                    "error": list_result.stderr,
                    "packages": []
                }

            packages = []
            output_lines = list_result.stdout.strip().split('\n')
            for line in output_lines:
                if line and '==' in line:
                    packages.append(line.strip())

            return {
                "success": True,
                "message": f"Found {len(packages)} packages in current Python environment",
                "python_executable": sys.executable,
                "packages": packages
            }

        except subprocess.TimeoutExpired:
            return {
                "success": False,
                "message": "Package listing timed out",
                "error": "Command took too long to complete",
                "packages": []
            }
        except Exception as e:
            return {
                "success": False,
                "message": "Failed to list packages",
                "error": str(e),
                "packages": []
            }


# --- Pipeline Service ---

class PipelineService:
    """
    Service layer for managing agent pipelines and their executions.
    Applies business rules and orchestrates repository calls.
    """

    def __init__(
        self,
        pipeline_repo: PipelineRepository,
        pipeline_run_repo: PipelineRunRepository,
        pipeline_steps_repo: PipelineStepsRepository,
        agent_pipeline_mapping_repo: AgentPipelineMappingRepository,
        agent_service: AgentService
    ):
        self.pipeline_repo = pipeline_repo
        self.pipeline_run_repo = pipeline_run_repo
        self.pipeline_steps_repo = pipeline_steps_repo
        self.agent_pipeline_mapping_repo = agent_pipeline_mapping_repo
        self.agent_service = agent_service

    # --- Pipeline Run & Step Tracking (Business Logic) ---

    async def create_pipeline_run(self, run_id: str, user_query: str, pipeline_id: str = None, session_id: str = None, status: str = "pending") -> bool:
        """
        Creates a new pipeline run record.

        Args:
            run_id: Unique identifier for this run
            user_query: The user's input query
            pipeline_id: The pipeline definition ID
            session_id: The user session ID for conversation tracking
            status: Initial status (default: pending)

        Returns:
            bool: True if successful, False otherwise
        """
        return await self.pipeline_run_repo.create_run(run_id, user_query, pipeline_id, session_id, status)

    async def add_pipeline_step(self, run_id: str, step_order: int, agent_id: str, step_data: dict) -> bool:
        """
        Adds a step record for a pipeline run.

        Args:
            run_id: The pipeline run ID
            step_order: The order/sequence of this step
            agent_id: The agent ID that executed this step
            step_data: JSON data containing step execution details

        Returns:
            bool: True if successful, False otherwise
        """
        return await self.pipeline_steps_repo.add_step(run_id, step_order, agent_id, step_data)

    async def update_pipeline_run_status(self, run_id: str, status: str, final_response: Optional[str] = None, response_time: Optional[float] = None) -> bool:
        """
        Updates run status and optionally final response.

        Args:
            run_id: The run ID to update
            status: New status value
            final_response: Optional final response text
            response_time: Optional response time in seconds

        Returns:
            bool: True if successful, False otherwise
        """
        return await self.pipeline_run_repo.update_status(run_id, status, final_response, response_time)

    async def get_pipeline_run(self, run_id: str) -> Optional[Dict[str, Any]]:
        """
        Gets a pipeline run by ID.

        Args:
            run_id: The run ID to retrieve

        Returns:
            Dict with run details or None if not found
        """
        return await self.pipeline_run_repo.get_run(run_id)

    async def get_pipeline_steps(self, run_id: str) -> List[Dict[str, Any]]:
        """
        Gets all steps for a pipeline run.

        Args:
            run_id: The pipeline run ID

        Returns:
            List of step dictionaries ordered by step_order
        """
        return await self.pipeline_steps_repo.get_steps_by_run(run_id)

    async def get_latest_step_order(self, run_id: str) -> int:
        """
        Gets the latest step order for a pipeline run.

        Args:
            run_id: The pipeline run ID

        Returns:
            int: The latest step order, or 0 if no steps exist
        """
        return await self.pipeline_steps_repo.get_latest_step_order(run_id)

    # --- Pipeline CRUD Operations ---

    async def create_pipeline(
        self,
        pipeline_name: str,
        pipeline_description: str,
        pipeline_definition: dict,
        created_by: str,
        department_name: str = None
    ) -> Dict[str, Any]:
        """
        Creates a new pipeline after validating the definition.

        Args:
            pipeline_name: Name of the pipeline
            pipeline_description: Description of the pipeline
            pipeline_definition: Graph definition with nodes and edges
            created_by: Email of the creator
            department_name: Department name for the pipeline

        Returns:
            dict: Status of the creation operation
        """
        # Validate the pipeline definition
        validation_result = await self._validate_pipeline_definition(pipeline_definition)
        if not validation_result['is_valid']:
            return {
                "message": validation_result['message'],
                "is_created": False
            }

        pipeline_id = "ppl_" + str(uuid.uuid4())
        result = await self.pipeline_repo.insert_pipeline(
            pipeline_id=pipeline_id,
            pipeline_name=pipeline_name,
            pipeline_description=pipeline_description,
            pipeline_definition=pipeline_definition,
            created_by=created_by,
            department_name=department_name
        )

        if result.get("success"):
            # Create agent-pipeline mappings for all agent nodes
            await self._create_agent_pipeline_mappings(
                pipeline_id=pipeline_id,
                pipeline_definition=pipeline_definition,
                pipeline_created_by=created_by
            )
            return {
                "message": f"Pipeline '{pipeline_name}' created successfully.",
                "pipeline_id": pipeline_id,
                "is_created": True
            }
        else:
            # Handle duplicate name error specifically
            error_message = result.get("message", f"Failed to create pipeline '{pipeline_name}'.")
            return {
                "message": error_message,
                "is_created": False
            }

    async def _create_agent_pipeline_mappings(
        self,
        pipeline_id: str,
        pipeline_definition: dict,
        pipeline_created_by: str
    ) -> None:
        """
        Creates agent-pipeline mappings for all agent nodes in the pipeline definition.

        Args:
            pipeline_id: The ID of the pipeline
            pipeline_definition: The pipeline definition containing nodes
            pipeline_created_by: Email of the pipeline creator
        """
        try:
            nodes = pipeline_definition.get('nodes', [])
            agent_nodes = [n for n in nodes if n.get('node_type') == 'agent']
            
            for node in agent_nodes:
                config = node.get('config', {})
                agent_id = config.get('agent_id') if isinstance(config, dict) else None
                
                if agent_id:
                    # Get the agent's creator
                    agent_record = await self.agent_service.agent_repo.get_agent_record(agentic_application_id=agent_id)
                    if agent_record:
                        agent_record = agent_record[0] if isinstance(agent_record, list) and len(agent_record) > 0 else agent_record
                        agent_created_by = agent_record.get('created_by', '') if agent_record else ''
                    
                    # Create the mapping
                    await self.agent_pipeline_mapping_repo.assign_agent_to_pipeline_record(
                        agentic_application_id=agent_id,
                        pipeline_id=pipeline_id,
                        agent_created_by=agent_created_by,
                        pipeline_created_by=pipeline_created_by
                    )
                    log.info(f"Created agent-pipeline mapping: agent '{agent_id}' -> pipeline '{pipeline_id}'")
        except Exception as e:
            log.error(f"Error creating agent-pipeline mappings for pipeline '{pipeline_id}': {e}")

    async def get_all_pipelines(
        self,
        created_by: Optional[str] = None,
        is_active: Optional[bool] = None,
        department_name: str = None
    ) -> List[Dict[str, Any]]:
        """
        Retrieves all pipelines with optional filtering.

        Args:
            created_by: Filter by creator email
            is_active: Filter by active status
            department_name: Filter by department name

        Returns:
            List of pipeline dictionaries
        """
        return await self.pipeline_repo.get_all_pipelines(created_by=created_by, is_active=is_active, department_name=department_name)

    async def get_pipeline_by_name(self, pipeline_name: str) -> Optional[Dict[str, Any]]:
        """
        Retrieves a single pipeline by its exact name.

        Args:
            pipeline_name: The exact pipeline name to look up

        Returns:
            Pipeline dictionary if found, None otherwise
        """
        return await self.pipeline_repo.get_pipeline_by_name(pipeline_name=pipeline_name)

    async def get_pipelines_by_search_or_page(
        self,
        search_value: str = '',
        limit: int = 20,
        page: int = 1,
        created_by: Optional[str] = None,
        is_active: Optional[bool] = None,
        department_name: str = None
    ) -> Dict[str, Any]:
        """
        Retrieves pipelines with pagination and search filtering.

        Args:
            search_value: Search string to match against pipeline name
            limit: Number of results per page
            page: Page number (1-indexed)
            created_by: Filter by creator email
            is_active: Filter by active status
            department_name: Filter by department name

        Returns:
            dict: A dictionary containing total_count and list of pipeline details
        """
        total_count = await self.pipeline_repo.get_total_pipeline_count(
            search_value=search_value,
            created_by=created_by,
            is_active=is_active,
            department_name=department_name
        )
        
        pipeline_records = await self.pipeline_repo.get_pipelines_by_search_or_page(
            search_value=search_value,
            limit=limit,
            page=page,
            created_by=created_by,
            is_active=is_active,
            department_name=department_name
        )
        
        log.info(f"Retrieved {len(pipeline_records)} pipelines with search '{search_value}' on page {page}.")
        return {
            "total_count": total_count,
            "details": pipeline_records
        }

    async def get_pipeline(self, pipeline_id: str, department_name: str = None) -> Optional[Dict[str, Any]]:
        """
        Retrieves a single pipeline by ID.

        Args:
            pipeline_id: The pipeline ID
            department_name: Filter by department name

        Returns:
            Pipeline dictionary or None
        """
        return await self.pipeline_repo.get_pipeline(pipeline_id, department_name=department_name)

    async def update_pipeline(
        self,
        pipeline_id: str,
        pipeline_name: Optional[str] = None,
        pipeline_description: Optional[str] = None,
        pipeline_definition: Optional[dict] = None,
        is_active: Optional[bool] = None
    ) -> Dict[str, Any]:
        """
        Updates a pipeline.

        Args:
            pipeline_id: The pipeline ID to update
            pipeline_name: New name (optional)
            pipeline_description: New description (optional)
            pipeline_definition: New definition (optional)
            is_active: New active status (optional)

        Returns:
            dict: Status of the update operation
        """
        # Check if pipeline exists
        existing = await self.pipeline_repo.get_pipeline(pipeline_id)
        if not existing:
            return {
                "message": f"Pipeline '{pipeline_id}' not found.",
                "is_updated": False
            }

        # Validate definition if provided
        if pipeline_definition:
            validation_result = await self._validate_pipeline_definition(pipeline_definition)
            if not validation_result['is_valid']:
                return {
                    "message": validation_result['message'],
                    "is_updated": False
                }

        result = await self.pipeline_repo.update_pipeline(
            pipeline_id=pipeline_id,
            pipeline_name=pipeline_name,
            pipeline_description=pipeline_description,
            pipeline_definition=pipeline_definition,
            is_active=is_active
        )

        if result.get("success"):
            # If pipeline_definition was updated, refresh agent-pipeline mappings
            if pipeline_definition:
                pipeline_created_by = existing.get('created_by', '')
                await self._update_agent_pipeline_mappings(
                    pipeline_id=pipeline_id,
                    pipeline_definition=pipeline_definition,
                    pipeline_created_by=pipeline_created_by
                )
            return {
                "message": f"Pipeline '{pipeline_id}' updated successfully.",
                "is_updated": True
            }
        else:
            # Handle specific error messages (e.g., duplicate name)
            error_message = result.get("message", f"Failed to update pipeline '{pipeline_id}'.")
            return {
                "message": error_message,
                "is_updated": False
            }

    async def _update_agent_pipeline_mappings(
        self,
        pipeline_id: str,
        pipeline_definition: dict,
        pipeline_created_by: str
    ) -> None:
        """
        Updates agent-pipeline mappings when a pipeline definition is updated.
        Removes old mappings and creates new ones based on the updated definition.

        Args:
            pipeline_id: The ID of the pipeline
            pipeline_definition: The updated pipeline definition containing nodes
            pipeline_created_by: Email of the pipeline creator
        """
        try:
            # Remove existing mappings for this pipeline
            await self.agent_pipeline_mapping_repo.remove_agent_from_pipeline_record(pipeline_id=pipeline_id)
            log.info(f"Removed existing agent-pipeline mappings for pipeline '{pipeline_id}'")
            
            # Create new mappings based on updated definition
            await self._create_agent_pipeline_mappings(
                pipeline_id=pipeline_id,
                pipeline_definition=pipeline_definition,
                pipeline_created_by=pipeline_created_by
            )
            log.info(f"Recreated agent-pipeline mappings for pipeline '{pipeline_id}'")
        except Exception as e:
            log.error(f"Error updating agent-pipeline mappings for pipeline '{pipeline_id}': {e}")

    async def delete_pipeline(self, pipeline_id: str) -> Dict[str, Any]:
        """
        Deletes a pipeline.

        Args:
            pipeline_id: The pipeline ID to delete

        Returns:
            dict: Status of the deletion operation
        """
        success = await self.pipeline_repo.delete_pipeline(pipeline_id)

        if success:
            return {
                "message": f"Pipeline '{pipeline_id}' deleted successfully.",
                "is_deleted": True
            }
        else:
            return {
                "message": f"Pipeline '{pipeline_id}' not found or deletion failed.",
                "is_deleted": False
            }

    # --- Pipeline Validation ---

    async def _validate_pipeline_definition(self, pipeline_definition: dict) -> Dict[str, Any]:
        """
        Validates a pipeline definition based on the updated schema.

        Args:
            pipeline_definition: The definition to validate

        Returns:
            dict: Validation result with 'is_valid' and 'message'
        """
        nodes = pipeline_definition.get('nodes', [])
        edges = pipeline_definition.get('edges', [])

        if not nodes:
            return {"is_valid": False, "message": "Pipeline must have at least one node."}

        # Check for input node
        input_nodes = [n for n in nodes if n.get('node_type') == 'input']
        if len(input_nodes) != 1:
            return {"is_valid": False, "message": "Pipeline must have exactly one input node."}

        # Check all agent nodes have valid agent_ids in their config
        agent_nodes = [n for n in nodes if n.get('node_type') == 'agent']
        for node in agent_nodes:
            config = node.get('config', {})
            agent_id = config.get('agent_id') if isinstance(config, dict) else None
            if not agent_id:
                return {
                    "is_valid": False,
                    "message": f"Agent node '{node.get('node_id')}' must have an agent_id in its config."
                }
            # Verify agent exists
            agent = await self.agent_service.agent_repo.get_agent_record(agentic_application_id=agent_id)
            if not agent:
                return {
                    "is_valid": False,
                    "message": f"Agent '{agent_id}' not found for node '{node.get('node_id')}'."
                }

        # Check edges reference valid nodes
        node_ids = {n['node_id'] for n in nodes}
        for edge in edges:
            if edge.get('source_node_id') not in node_ids:
                return {
                    "is_valid": False,
                    "message": f"Edge source '{edge.get('source_node_id')}' does not exist."
                }
            # target_node_ids is now a list of target node IDs
            target_node_id = edge.get('target_node_id', [])
            # Ensure it's a list
            if isinstance(target_node_id, str):
                if target_node_id and target_node_id not in node_ids:
                    return {
                        "is_valid": False,
                        "message": f"Edge target '{target_node_id}' does not exist."
                    }

        # Check input node has at least one outgoing edge
        input_node_id = input_nodes[0]['node_id']
        input_edges = [e for e in edges if e.get('source_node_id') == input_node_id]
        if not input_edges:
            return {"is_valid": False, "message": "Input node must connect to at least one agent."}

        return {"is_valid": True, "message": "Pipeline definition is valid."}

    # --- Pipeline Conversation History ---

    async def get_pipeline_conversation_history(
        self,
        pipeline_id: str,
        session_id: str,
        limit: int = 50,
        role: str = None
    ) -> List[Dict[str, Any]]:
        """
        Gets the formatted conversation history for a pipeline session.

        Args:
            pipeline_id: The pipeline definition ID
            session_id: The user session ID
            limit: Maximum number of conversations to return
            role: User role for determining response detail level

        Returns:
            List of formatted conversation dictionaries
        """
        # Get previous runs for this session
        runs = await self.pipeline_run_repo.get_runs_by_session(pipeline_id, session_id, limit)
        
        conversations = []
        for run in runs:
            # Get steps for this run
            steps = await self.pipeline_steps_repo.get_steps_by_run(run['id'])
            
            # Format conversation entry
            conversation = await self._format_pipeline_conversation(
                run=run,
                steps=steps,
                role=role
            )
            conversations.append(conversation)
        
        # Return in chronological order (oldest first)
        return list(reversed(conversations))

    async def _format_pipeline_conversation(
        self,
        run: Dict[str, Any],
        steps: List[Dict[str, Any]],
        role: str = None
    ) -> Dict[str, Any]:
        """
        Formats a single pipeline run into a conversation entry similar to agent response format.

        Args:
            run: The pipeline run record
            steps: The pipeline steps for this run
            role: User role for determining response detail level

        Returns:
            Formatted conversation dictionary
        """
        user_query = run.get('user_query', '')
        final_response = run.get('final_response', '')
        response_time = run.get('response_time')
        created_at = run.get('created_at')
        completed_at = run.get('completed_at')
        
        # Extract tools used and agent steps from the step data
        tools_used = {}
        agent_steps_data = []
        
        for step in reversed(steps):
            step_data = step.get('step_data', {})
            node_type = step_data.get('node_type', '')
            
            if node_type == 'agent':
                # Extract executor_messages if available
                executor_messages = step_data.get('executor_messages', [])
                
                # Extract tools from executor messages
                for msg in executor_messages:
                    if isinstance(msg, dict):
                        tool_calls = msg.get('tool_calls', [])
                        for tool_call in tool_calls:
                            tool_id = tool_call.get('id')
                            if tool_id and tool_id not in tools_used:
                                tools_used[tool_id] = {
                                    'name': tool_call.get('name'),
                                    'args': tool_call.get('args', {})
                                }
                
                # agent_steps_data.append({
                #     'node_id': step_data.get('node_id'),
                #     'agent_id': step_data.get('agent_id'),
                #     'input_query': step_data.get('input_query'),
                #     'content': step_data.get('response'),
                #     'role': "Agent",
                #     'status': step_data.get('status')
                # })
                    agent_steps_data.extend(msg.get('additional_details', []))
            elif node_type == 'input':
                agent_steps_data.append({
                    'node_id': step_data.get('node_id'),
                    'content': step_data.get('input_query'),
                    'role': "Input",
                    'status': step_data.get('status')
                })
            elif node_type == 'output':
                agent_steps_data.append({
                    'node_id': step_data.get('node_id'),
                    'content': step_data.get('response'),
                    'role': "Output",
                    'status': step_data.get('status')
                })
        
        # Build parts array
        parts = []

        if final_response and isinstance(final_response, str):
                # Try to parse string as JSON, fallback to text if not valid JSON
                try:
                    parsed_json = json.loads(final_response)
                    for k in parsed_json.keys():
                        parts.append({
                            "type": "json",
                            "output_key": k,
                            "data": {
                                "content" :parsed_json[k]
                            },
                            "metadata": {
                                "output_key": k
                            }
                        })
                except (json.JSONDecodeError, TypeError):
                    parts.append({
                        "type": "text",
                        "data": {"content": final_response},
                        "metadata": {}
                    })
            
        
        # Determine show_canvas based on parts content
        show_canvas = False
        for part in parts:
            if part.get("type") not in ("text", "image"):
                show_canvas = True
                break
        
        # Build conversation entry based on role
        if role.lower() == "user":
            # For USER role, include only essential fields
            conversation = {
                "user_query": user_query,
                "final_response": final_response,
                "parts": parts,
                "show_canvas": show_canvas
            }
        else:
            # For other roles (DEVELOPER, ADMIN), include all fields
            conversation = {
                "user_query": user_query,
                "final_response": final_response,
                "tools_used": tools_used,
                "additional_details": agent_steps_data,
                "pipeline_steps": steps,
                "parts": parts,
                "show_canvas": show_canvas,
                "response_time": response_time,
                "time_stamp": str(completed_at) if completed_at else None,
                "start_timestamp": str(created_at) if created_at else None,
                "end_timestamp": str(completed_at) if completed_at else None
            }
        
        return conversation

    async def format_pipeline_response_with_history(
        self,
        current_response: Dict[str, Any],
        pipeline_id: str,
        session_id: str,
        role: str = "user",
        response_time: float = None
    ) -> List[Dict[str, Any]]:
        """
        Formats the current pipeline response and includes previous conversation history.

        Args:
            current_response: The current pipeline execution response
            pipeline_id: The pipeline definition ID
            session_id: The user session ID
            role: User role for determining response detail level
            response_time: Response time for current execution

        Returns:
            List of formatted conversations including history and current response
        """
        # Get previous conversation history
        history = await self.get_pipeline_conversation_history(
            pipeline_id=pipeline_id,
            session_id=session_id,
            limit=49,  # Leave room for current response
            role=role
        )
        
        # Format current response
        user_query = current_response.get('query', '')
        final_response = current_response.get('response', '')
        parts = current_response.get('parts', [])
        executor_messages = current_response.get('executor_messages', [])
        
        # Determine show_canvas
        # show_canvas = False
        # for part in parts:
        #     if part.get("type") not in ("text", "image"):
        #         show_canvas = True
        #         break
        
        # # Build current conversation entry based on role
        # if role.lower() == "user":
        #     current_conversation = {
        #         "user_query": user_query,
        #         "final_response": final_response,
        #         "parts": parts,
        #         "show_canvas": show_canvas
        #     }
        # else:
        #     current_conversation = {
        #         "user_query": user_query,
        #         "final_response": final_response,
        #         "tools_used": {},
        #         "pipeline_steps": executor_messages,
        #         "additional_details": [],
        #         "parts": parts,
        #         "show_canvas": show_canvas,
        #         "response_time": response_time,
        #         "time_stamp": None,
        #         "start_timestamp": None,
        #         "end_timestamp": None
        #     }
        
        # # Mark current parts with is_last flag for non-USER roles
        # if role.lower() != "user" and parts:
        #     for part in current_conversation["parts"]:
        #         if part.get("type") not in ("text", "image"):
        #             part["is_last"] = True
        
        # Append current response to history
        # history.append(current_conversation)
        if history:
            history[-1]["parts"] = current_response.get("parts", [])
        else:
            # No history, create a new entry for current response
            show_canvas = False
            for part in parts:
                if part.get("type") not in ("text", "image"):
                    show_canvas = True
                    break
            
            if role.lower() == "user":
                current_conversation = {
                    "user_query": user_query,
                    "final_response": final_response,
                    "parts": parts,
                    "show_canvas": show_canvas
                }
            else:
                current_conversation = {
                    "user_query": user_query,
                    "final_response": final_response,
                    "tools_used": {},
                    "pipeline_steps": [],
                    "additional_details": [],
                    "parts": parts,
                    "show_canvas": show_canvas,
                    "response_time": response_time,
                    "time_stamp": None,
                    "start_timestamp": None,
                    "end_timestamp": None
                }
            history.append(current_conversation)
        
        return history

    async def delete_pipeline_session(
        self,
        pipeline_id: str,
        session_id: str
    ) -> Dict[str, Any]:
        """
        Deletes all pipeline run history for a given pipeline and session.

        Args:
            pipeline_id: The pipeline definition ID
            session_id: The user session ID

        Returns:
            Dict with status of the deletion operation
        """
        try:
            # First get all run IDs to delete their steps
            run_ids = await self.pipeline_run_repo.get_run_ids_by_session(pipeline_id, session_id)
            
            # Delete steps for each run
            for run_id in run_ids:
                await self.pipeline_steps_repo.delete_steps_by_run(run_id)
            
            # Delete all runs for this session
            success = await self.pipeline_run_repo.delete_runs_by_session(pipeline_id, session_id)
            
            if success:
                return {
                    "status": "success",
                    "message": f"Pipeline history cleared for session '{session_id}'."
                }
            else:
                return {
                    "status": "error",
                    "message": f"Failed to clear pipeline history for session '{session_id}'."
                }
        except Exception as e:
            log.error(f"Error deleting pipeline session '{session_id}': {e}")
            return {
                "status": "error",
                "message": f"Error clearing pipeline history: {str(e)}"
            }

    async def get_old_pipeline_conversations(
        self,
        user_email: str,
        pipeline_id: str
    ) -> Dict[str, Any]:
        """
        Gets old pipeline conversations for a user, grouped by session ID.
        Similar to ChatService.get_old_chats_by_user_and_agent but for pipelines.
        Returns simplified format with timestamp_start, timestamp_end, user_input, agent_response.

        Args:
            user_email: The user's email address
            pipeline_id: The pipeline definition ID

        Returns:
            Dict with session IDs as keys and conversation lists as values
        """
        try:
            # Get all sessions for this user and pipeline
            sessions = await self.pipeline_run_repo.get_sessions_by_user_and_pipeline(
                user_email=user_email,
                pipeline_id=pipeline_id
            )
            
            if not sessions:
                return {}
            
            result = {}
            for session_info in sessions:
                session_id = session_info.get('session_id')
                if not session_id:
                    continue
                
                # Get runs for this session
                runs = await self.pipeline_run_repo.get_runs_by_session(
                    pipeline_id=pipeline_id,
                    session_id=session_id,
                    limit=100
                )
                
                if runs:
                    # Format runs into simplified format (same as agent old conversations)
                    conversations = []
                    for run in reversed(runs):  # Oldest first
                        user_query = run.get('user_query', '')
                        final_response = run.get('final_response', '')
                        created_at = run.get('created_at')
                        completed_at = run.get('completed_at')
                        
                        # Format timestamps
                        timestamp_start = str(created_at) if created_at else None
                        timestamp_end = str(completed_at) if completed_at else timestamp_start
                        
                        conversations.append({
                            "timestamp_start": timestamp_start,
                            "timestamp_end": timestamp_end,
                            "user_input": user_query,
                            "agent_response": final_response
                        })
                    
                    # Use full session_id as key (format: user_email_session_id)
                    result[session_id] = conversations
            
            return result
            
        except Exception as e:
            log.error(f"Error getting old pipeline conversations for user '{user_email}': {e}")
            return {}


# --- Tool Generation Code Version Service ---

class ToolGenerationCodeVersionService:
    """
    Service layer for managing code version history in tool generation sessions.
    Provides business logic for saving, retrieving, and switching between code versions.
    """

    def __init__(self, code_version_repo: ToolGenerationCodeVersionRepository):
        self.code_version_repo = code_version_repo

    async def save_version(
        self,
        session_id: str,
        pipeline_id: str,
        code_snippet: str,
        created_by: str,
        label: Optional[str] = None,
        is_auto_saved: bool = True,
        user_query: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Saves a new code version.

        Args:
            session_id: The user's session ID
            pipeline_id: The pipeline ID
            code_snippet: The code to save
            created_by: Email of the creator
            label: Optional label for the version
            is_auto_saved: Whether this was auto-saved or manually saved
            user_query: The user query that generated this code (stored in metadata)

        Returns:
            Dict with version details and status
        """
        # Validate code snippet
        if not code_snippet or len(code_snippet.strip()) < 20:
            return {
                "success": False,
                "message": "Code snippet is too short or empty",
                "version": None
            }

        # Build metadata
        metadata = {}
        if user_query:
            metadata["user_query"] = user_query
        metadata["code_length"] = len(code_snippet)

        # Save version
        version = await self.code_version_repo.save_code_version(
            session_id=session_id,
            pipeline_id=pipeline_id,
            code_snippet=code_snippet,
            created_by=created_by,
            label=label,
            is_auto_saved=is_auto_saved,
            metadata=metadata
        )

        if version:
            return {
                "success": True,
                "message": f"Code version {version['version_number']} saved successfully",
                "version": version
            }
        return {
            "success": False,
            "message": "Failed to save code version",
            "version": None
        }

    async def get_all_versions(
        self,
        session_id: str,
        include_code: bool = False
    ) -> Dict[str, Any]:
        """
        Gets all code versions for a session.

        Args:
            session_id: The user's session ID
            include_code: Whether to include full code in response

        Returns:
            Dict with versions list and count
        """
        versions = await self.code_version_repo.get_all_versions(
            session_id=session_id,
            include_code=include_code
        )
        
        return {
            "session_id": session_id,
            "total_versions": len(versions),
            "versions": versions
        }

    async def get_version(self, version_id: str) -> Dict[str, Any]:
        """
        Gets a specific version by ID.

        Args:
            version_id: The version ID

        Returns:
            Dict with version details or error
        """
        version = await self.code_version_repo.get_version(version_id)
        
        if version:
            return {
                "success": True,
                "version": version
            }
        return {
            "success": False,
            "message": f"Version '{version_id}' not found"
        }

    async def get_version_by_number(self, session_id: str, version_number: int) -> Dict[str, Any]:
        """
        Gets a specific version by session_id and version_number.

        Args:
            session_id: The user's session ID
            version_number: The version number (1, 2, 3, etc.)

        Returns:
            Dict with version details or error
        """
        version = await self.code_version_repo.get_version_by_number(session_id, version_number)
        
        if version:
            return {
                "success": True,
                "version": version
            }
        return {
            "success": False,
            "message": f"Version {version_number} not found for this session"
        }

    async def get_current_version(self, session_id: str) -> Dict[str, Any]:
        """
        Gets the current active version for a session.

        Args:
            session_id: The user's session ID

        Returns:
            Dict with current version or message if none exists
        """
        version = await self.code_version_repo.get_current_version(session_id)
        
        if version:
            return {
                "success": True,
                "version": version
            }
        return {
            "success": False,
            "message": f"No current version found for session '{session_id}'"
        }

    async def switch_version(
        self,
        session_id: str,
        version_id: str
    ) -> Dict[str, Any]:
        """
        Switches to a specific version, making it the current version.

        Args:
            session_id: The user's session ID
            version_id: The version ID to switch to

        Returns:
            Dict with switched version details or error
        """
        version = await self.code_version_repo.switch_to_version(
            session_id=session_id,
            version_id=version_id
        )
        
        if version:
            return {
                "success": True,
                "message": f"Switched to version {version['version_number']}",
                "version": version
            }
        return {
            "success": False,
            "message": f"Failed to switch to version '{version_id}'. Version may not exist or belong to a different session."
        }

    async def update_label(
        self,
        version_id: str,
        label: str
    ) -> Dict[str, Any]:
        """
        Updates the label for a version.

        Args:
            version_id: The version ID
            label: The new label

        Returns:
            Dict with success status
        """
        success = await self.code_version_repo.update_version_label(version_id, label)
        
        if success:
            return {
                "success": True,
                "message": f"Label updated for version '{version_id}'"
            }
        return {
            "success": False,
            "message": f"Failed to update label for version '{version_id}'"
        }

    async def delete_version(
        self,
        version_id: str,
        session_id: str
    ) -> Dict[str, Any]:
        """
        Deletes a specific version (cannot delete current version).

        Args:
            version_id: The version ID to delete
            session_id: The session ID for verification

        Returns:
            Dict with success status
        """
        success = await self.code_version_repo.delete_version(version_id, session_id)
        
        if success:
            return {
                "success": True,
                "message": f"Version '{version_id}' deleted successfully"
            }
        return {
            "success": False,
            "message": f"Failed to delete version '{version_id}'. It may be the current version or not exist."
        }

    async def clear_session_versions(self, session_id: str) -> Dict[str, Any]:
        """
        Deletes all versions for a session (used when resetting conversation).


        Args:
            session_id: The session ID

        Returns:
            Dict with success status
        """
        success = await self.code_version_repo.delete_all_versions_for_session(session_id)
        
        if success:
            return {
                "success": True,
                "message": f"All versions cleared for session '{session_id}'"
            }
        return {
            "success": False,
            "message": f"Failed to clear versions for session '{session_id}'"
        }

    async def get_version_count(self, session_id: str) -> int:
        """
        Gets the total number of versions for a session.

        Args:
            session_id: The session ID

        Returns:
            Number of versions
        """
        return await self.code_version_repo.get_version_count(session_id)


# --- Tool Generation Conversation History Service ---

class ToolGenerationConversationHistoryService:
    """
    Service layer for managing conversation history in tool generation sessions.
    Provides business logic for saving, retrieving, and managing chat messages.
    """

    def __init__(self, conversation_repo):
        from src.database.repositories import ToolGenerationConversationHistoryRepository
        self.conversation_repo: ToolGenerationConversationHistoryRepository = conversation_repo

    async def save_user_message(
        self,
        session_id: str,
        pipeline_id: str,
        message: str,
        created_by: str,
        code_snippet: Optional[str] = None,
        metadata: Optional[dict] = None
    ) -> Dict[str, Any]:
        """
        Saves a user message to conversation history.

        Args:
            session_id: The user's session ID
            pipeline_id: The pipeline ID
            message: The user's message/query
            created_by: Email of the user
            code_snippet: Optional code context (e.g., current_code or selected_code)
            metadata: Optional additional metadata

        Returns:
            Dict with message details and status
        """
        result = await self.conversation_repo.save_message(
            session_id=session_id,
            pipeline_id=pipeline_id,
            role="user",
            message=message,
            code_snippet=code_snippet,
            created_by=created_by,
            metadata=metadata
        )

        if result:
            return {
                "success": True,
                "message_id": result["message_id"],
                "data": result
            }
        return {
            "success": False,
            "message": "Failed to save user message"
        }

    async def save_assistant_message(
        self,
        session_id: str,
        pipeline_id: str,
        message: str,
        code_snippet: Optional[str] = None,
        metadata: Optional[dict] = None
    ) -> Dict[str, Any]:
        """
        Saves an assistant response to conversation history.

        Args:
            session_id: The user's session ID
            pipeline_id: The pipeline ID
            message: The assistant's response message
            code_snippet: Optional generated code snippet
            metadata: Optional additional metadata (e.g., model_name, tokens)

        Returns:
            Dict with message details and status
        """
        result = await self.conversation_repo.save_message(
            session_id=session_id,
            pipeline_id=pipeline_id,
            role="assistant",
            message=message,
            code_snippet=code_snippet,
            created_by=None,
            metadata=metadata
        )

        if result:
            return {
                "success": True,
                "message_id": result["message_id"],
                "data": result
            }
        return {
            "success": False,
            "message": "Failed to save assistant message"
        }

    async def save_conversation_pair(
        self,
        session_id: str,
        pipeline_id: str,
        user_message: str,
        assistant_message: str,
        user_email: str,
        user_code_context: Optional[str] = None,
        assistant_code_snippet: Optional[str] = None,
        metadata: Optional[dict] = None
    ) -> Dict[str, Any]:
        """
        Saves both user query and assistant response as a pair.
        Useful for saving complete conversation turns.

        Args:
            session_id: The user's session ID
            pipeline_id: The pipeline ID
            user_message: The user's query
            assistant_message: The assistant's response
            user_email: Email of the user
            user_code_context: Optional code context sent by user
            assistant_code_snippet: Optional code generated by assistant
            metadata: Optional shared metadata

        Returns:
            Dict with both message IDs and status
        """
        # Save user message
        user_result = await self.save_user_message(
            session_id=session_id,
            pipeline_id=pipeline_id,
            message=user_message,
            created_by=user_email,
            code_snippet=user_code_context,
            metadata=metadata
        )

        if not user_result["success"]:
            return user_result

        # Save assistant message
        assistant_result = await self.save_assistant_message(
            session_id=session_id,
            pipeline_id=pipeline_id,
            message=assistant_message,
            code_snippet=assistant_code_snippet,
            metadata=metadata
        )

        if not assistant_result["success"]:
            return assistant_result

        return {
            "success": True,
            "user_message_id": user_result["message_id"],
            "assistant_message_id": assistant_result["message_id"]
        }

    async def get_conversation_history(
        self,
        session_id: str,
        pipeline_id: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
        include_code: bool = True
    ) -> Dict[str, Any]:
        """
        Gets conversation history for a session.

        Args:
            session_id: The user's session ID
            pipeline_id: Optional filter by pipeline ID
            limit: Maximum number of messages to return
            offset: Number of messages to skip (for pagination)
            include_code: Whether to include code snippets

        Returns:
            Dict with conversation history
        """
        messages = await self.conversation_repo.get_conversation_history(
            session_id=session_id,
            pipeline_id=pipeline_id,
            limit=limit,
            offset=offset,
            include_code=include_code
        )
        
        return {
            "session_id": session_id,
            "pipeline_id": pipeline_id,
            "total_messages": len(messages),
            "messages": messages
        }

    async def get_latest_messages(
        self,
        session_id: str,
        pipeline_id: str,
        count: int = 10
    ) -> List[Dict[str, Any]]:
        """
        Gets the latest N messages for a session.

        Args:
            session_id: The user's session ID
            pipeline_id: The pipeline ID
            count: Number of messages to return

        Returns:
            List of latest messages
        """
        return await self.conversation_repo.get_latest_messages(
            session_id=session_id,
            pipeline_id=pipeline_id,
            count=count
        )

    async def clear_conversation_history(
        self,
        session_id: str,
        pipeline_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Clears conversation history for a session.

        Args:
            session_id: The session ID
            pipeline_id: Optional pipeline ID

        Returns:
            Dict with success status
        """
        success = await self.conversation_repo.clear_conversation_history(
            session_id=session_id,
            pipeline_id=pipeline_id
        )
        
        if success:
            return {
                "success": True,
                "message": f"Conversation history cleared for session '{session_id}'"
            }
        return {
            "success": False,
            "message": f"Failed to clear conversation history for session '{session_id}'"
        }

    async def get_message_count(
        self,
        session_id: str,
        pipeline_id: Optional[str] = None
    ) -> int:
        """
        Gets the total number of messages for a session.

        Args:
            session_id: The session ID
            pipeline_id: Optional pipeline ID filter

        Returns:
            Number of messages
        """
        return await self.conversation_repo.get_message_count(
            session_id=session_id,
            pipeline_id=pipeline_id
        )

    async def get_latest_code(
        self,
        session_id: str,
        pipeline_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Gets the latest code snippet from conversation history.

        Args:
            session_id: The user's session ID
            pipeline_id: Optional filter by pipeline ID

        Returns:
            Dict with latest code snippet or None
        """
        result = await self.conversation_repo.get_latest_code_snippet(
            session_id=session_id,
            pipeline_id=pipeline_id
        )
        
        if result:
            return {
                "success": True,
                "session_id": session_id,
                "pipeline_id": pipeline_id,
                "code_snippet": result.get("code_snippet"),
                "message_id": result.get("message_id"),
                "timestamp": result.get("timestamp")
            }
        return {
            "success": True,
            "session_id": session_id,
            "pipeline_id": pipeline_id,
            "code_snippet": None,
            "message": "No code snippet found in conversation history"
        }

    async def clear_conversation(
        self,
        session_id: str,
        pipeline_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Clears conversation history for a session.
        Alias for clear_conversation_history.

        Args:
            session_id: The session ID
            pipeline_id: Optional pipeline ID

        Returns:
            Dict with success status
        """
        return await self.clear_conversation_history(
            session_id=session_id,
            pipeline_id=pipeline_id
        )

    async def restore_to_message(
        self,
        session_id: str,
        message_id: str
    ) -> Dict[str, Any]:
        """
        Restores conversation to a specific message point.
        Deletes all messages after the specified message.

        Args:
            session_id: The session ID
            message_id: The message ID to restore to

        Returns:
            Dict with success status and deleted count
        """
        deleted_count = await self.conversation_repo.clear_from_message(
            session_id=session_id,
            message_id=message_id
        )
        
        if deleted_count >= 0:
            return {
                "success": True,
                "message": f"Restored conversation to message '{message_id}'",
                "deleted_messages": deleted_count
            }
        return {
            "success": False,
            "message": f"Failed to restore conversation. Message '{message_id}' may not exist."
        }
      

# --- Knowledgebase Service ---

class KnowledgebaseService:
    """
    Service layer for managing knowledge bases and their associations with agents.
    Handles business logic for KB operations.
    """

    def __init__(
        self,
        knowledgebase_repo: KnowledgebaseRepository,
        agent_kb_mapping_repo: AgentKnowledgebaseMappingRepository,
        vector_store=None,
        kb_sharing_repo=None
    ):
        self.knowledgebase_repo = knowledgebase_repo
        self.agent_kb_mapping_repo = agent_kb_mapping_repo
        self.vector_store = vector_store
        self.kb_sharing_repo = kb_sharing_repo

    async def create_knowledgebase(
        self,
        kb_name: str,
        list_of_documents: list = None,
        created_by: str = "system",
        department_name: str = "General",
        is_public: bool = False,
        shared_with_departments: List[str] = None
    ) -> Dict[str, Any]:
        """Create a new knowledge base record with optional sharing."""
        # Validate: is_public and shared_with_departments are mutually exclusive
        if is_public and shared_with_departments:
            raise HTTPException(
                status_code=400,
                detail="Cannot set both 'is_public' and 'shared_with_departments'. A public knowledge base is already accessible to all departments."
            )
        
        # Check if KB with same name already exists in the department
        existing_kb = await self.knowledgebase_repo.get_knowledgebase_by_name(kb_name, department_name=department_name)
        if existing_kb:
            raise HTTPException(
                status_code=400,
                detail=f"Knowledge base with name '{kb_name}' already exists in department '{department_name}'. Please use a different name."
            )
        
        kb_id = str(uuid.uuid4())
        kb_data = {
            "knowledgebase_id": kb_id,
            "knowledgebase_name": kb_name,
            "list_of_documents": list_of_documents or [],
            "created_by": created_by,
            "department_name": department_name,
            "is_public": is_public,
            "created_on": datetime.now(timezone.utc)
        }
        
        is_created = await self.knowledgebase_repo.save_knowledgebase_record(kb_data)
        
        # Handle department sharing if specified
        sharing_result = None
        if is_created and shared_with_departments and self.kb_sharing_repo:
            try:
                sharing_result = await self.kb_sharing_repo.share_kb_with_multiple_departments(
                    knowledgebase_id=kb_id,
                    knowledgebase_name=kb_name,
                    source_department=department_name,
                    target_departments=shared_with_departments,
                    shared_by=created_by
                )
                log.info(f"KB '{kb_name}' shared with {sharing_result.get('success_count', 0)} departments during creation")
            except Exception as e:
                log.warning(f"Error sharing KB '{kb_name}' with departments during creation: {e}")
        
        result = {
            "knowledgebase_id": kb_id,
            "knowledgebase_name": kb_name,
            "is_created": is_created,
            "is_public": is_public,
            "message": f"Knowledge base '{kb_name}' created successfully"
        }
        if sharing_result:
            result["sharing"] = sharing_result
        return result

    async def get_all_knowledgebases(self, department_name: str = None) -> List[Dict[str, Any]]:
        """Retrieve all knowledge base records, optionally filtered by department. Also includes KBs shared with the department."""
        kb_records = await self.knowledgebase_repo.get_all_knowledgebase_records(department_name=department_name)
        
        # Also include KBs shared with this department
        if department_name and self.kb_sharing_repo:
            try:
                shared_kb_ids = await self.kb_sharing_repo.get_kbs_shared_with_department(department_name)
                if shared_kb_ids:
                    # Filter out KBs already in the list
                    existing_kb_ids = {kb.get('knowledgebase_id') for kb in kb_records}
                    new_shared_kb_ids = [kb_id for kb_id in shared_kb_ids if kb_id not in existing_kb_ids]
                    
                    if new_shared_kb_ids:
                        shared_kb_records = await self.knowledgebase_repo.get_knowledgebases_by_ids_with_email(new_shared_kb_ids)
                        for kb in shared_kb_records:
                            kb['is_shared'] = True
                        kb_records.extend(shared_kb_records)
            except Exception as e:
                log.warning(f"Error fetching shared KBs for department '{department_name}': {e}")
        
        return kb_records

    async def get_knowledgebase_by_id(self, kb_id: str) -> Optional[Dict[str, Any]]:
        """Retrieve a specific knowledge base by ID."""
        return await self.knowledgebase_repo.get_knowledgebase_by_id(kb_id)

    async def get_knowledgebase_by_name(self, kb_name: str, department_name: str = None) -> Optional[Dict[str, Any]]:
        """Retrieve a specific knowledge base by name."""
        return await self.knowledgebase_repo.get_knowledgebase_by_name(kb_name, department_name=department_name)

    async def delete_knowledgebase(self, kb_id: str) -> Dict[str, Any]:
        """Delete a knowledge base record."""
        # First unlink all agent associations
        await self.agent_kb_mapping_repo.unlink_all_knowledgebases_from_agent(kb_id)
        
        # Then delete the KB record
        deleted = await self.knowledgebase_repo.delete_knowledgebase(kb_id)
        
        return {
            "deleted": deleted,
            "message": f"Knowledge base {'deleted successfully' if deleted else 'not found'}"
        }

    async def link_knowledgebases_to_agent(
        self,
        agentic_application_id: str,
        knowledgebase_ids: List[str]
    ) -> Dict[str, Any]:
        """Link knowledge bases to an agent (replaces existing)."""
        await self.agent_kb_mapping_repo.set_knowledgebases_for_agent(
            agentic_application_id, knowledgebase_ids
        )
        
        return {
            "success": True,
            "message": f"Linked {len(knowledgebase_ids)} knowledge bases to agent"
        }

    async def add_knowledgebases_to_agent(
        self,
        agentic_application_id: str,
        knowledgebase_ids: List[str]
    ) -> Dict[str, Any]:
        """Add knowledge bases to an agent's existing list."""
        await self.agent_kb_mapping_repo.add_knowledgebases_to_agent(
            agentic_application_id, knowledgebase_ids
        )
        
        return {
            "success": True,
            "message": f"Added {len(knowledgebase_ids)} knowledge bases to agent"
        }

    async def remove_knowledgebases_from_agent(
        self,
        agentic_application_id: str,
        knowledgebase_ids: List[str]
    ) -> Dict[str, Any]:
        """Remove knowledge bases from an agent."""
        await self.agent_kb_mapping_repo.remove_knowledgebases_from_agent(
            agentic_application_id, knowledgebase_ids
        )
        
        return {
            "success": True,
            "message": f"Removed {len(knowledgebase_ids)} knowledge bases from agent"
        }

    async def get_agent_knowledgebases(
        self,
        agentic_application_id: str
    ) -> List[Dict[str, Any]]:
        """Get all knowledge bases for an agent."""
        return await self.agent_kb_mapping_repo.get_knowledgebases_for_agent(
            agentic_application_id
        )

    async def validate_knowledgebase_ids(
        self,
        knowledgebase_ids: List[str],
        department_name: str = None
    ) -> Dict[str, Any]:
        """
        Validates that the provided knowledgebase IDs exist and belong to the specified department.

        Args:
            knowledgebase_ids (List[str]): List of knowledgebase IDs to validate.
            department_name (str, optional): The department name to validate ownership against.

        Returns:
            dict: {"valid": True} if all IDs are valid, or {"error": "...", "invalid_ids": [...]} if not.
        """
        if not knowledgebase_ids:
            return {"valid": True}

        invalid_ids = []
        wrong_department_ids = []

        for kb_id in knowledgebase_ids:
            kb_record = await self.knowledgebase_repo.get_knowledgebase_by_id(kb_id)
            if not kb_record:
                invalid_ids.append(kb_id)
            elif department_name and kb_record.get("department_name") != department_name:
                # Check if the KB is public or shared with this department
                is_accessible = kb_record.get("is_public", False)
                if not is_accessible and self.kb_sharing_repo:
                    try:
                        is_accessible = await self.kb_sharing_repo.is_kb_shared_with_department(kb_id, department_name)
                    except Exception:
                        pass
                if not is_accessible:
                    wrong_department_ids.append({
                        "kb_id": kb_id,
                        "kb_name": kb_record.get("knowledgebase_name", ""),
                        "kb_department": kb_record.get("department_name", "")
                    })

        if invalid_ids:
            return {
                "error": f"The following knowledgebase IDs do not exist: {invalid_ids}",
                "invalid_ids": invalid_ids
            }

        if wrong_department_ids:
            details = ", ".join(
                f"'{item['kb_name']}' (belongs to '{item['kb_department']}')" for item in wrong_department_ids
            )
            return {
                "error": f"The following knowledgebases do not belong to department '{department_name}': {details}",
                "invalid_ids": [item["kb_id"] for item in wrong_department_ids]
            }

        log.info(f"All {len(knowledgebase_ids)} knowledgebase IDs validated successfully for department '{department_name}'.")
        return {"valid": True}

    async def update_kb_sharing(
        self,
        kb_id: str,
        user_email: str,
        department_name: str,
        is_public: bool = None,
        shared_with_departments: List[str] = None
    ) -> Dict[str, Any]:
        """
        Updates the visibility (is_public) and/or department sharing for a knowledge base.

        Args:
            kb_id: The knowledge base ID.
            user_email: The email of the user making the update.
            department_name: The department of the user.
            is_public: If provided, update the is_public flag.
            shared_with_departments: If provided, replace the shared departments list.

        Returns:
            Dict with update results.
        """
        # Verify KB exists and belongs to user's department
        kb_record = await self.knowledgebase_repo.get_knowledgebase_by_id(kb_id)
        if not kb_record:
            raise HTTPException(status_code=404, detail=f"Knowledge base '{kb_id}' not found.")
        
        if kb_record.get("department_name") != department_name:
            raise HTTPException(
                status_code=403,
                detail=f"Knowledge base '{kb_id}' belongs to department '{kb_record.get('department_name')}', not '{department_name}'. Only the owning department can update sharing settings."
            )
        
        result = {"kb_id": kb_id, "kb_name": kb_record.get("knowledgebase_name", "")}
        
        # Determine effective is_public value
        effective_is_public = is_public if is_public is not None else kb_record.get("is_public", False)
        
        # Validate: is_public and shared_with_departments are mutually exclusive
        if effective_is_public and shared_with_departments:
            raise HTTPException(
                status_code=400,
                detail="Cannot set both 'is_public' and 'shared_with_departments'. A public knowledge base is already accessible to all departments."
            )
        
        # Update is_public if provided
        if is_public is not None:
            updated = await self.knowledgebase_repo.update_kb_visibility(kb_id, is_public)
            result["is_public_updated"] = updated
            result["is_public"] = is_public
            
            # If setting to public, remove all existing department sharing
            if is_public and self.kb_sharing_repo:
                removed = await self.kb_sharing_repo.unshare_kb_from_all_departments(kb_id)
                if removed > 0:
                    log.info(f"Removed {removed} department sharing records for KB '{kb_id}' since it is now public.")
                    result["sharing"] = {"message": f"All department sharing removed (KB is now public). {removed} records cleared.", "success_count": 0}
        
        # Update shared departments if provided
        if shared_with_departments is not None and self.kb_sharing_repo:
            kb_name = kb_record.get("knowledgebase_name", "")
            source_department = kb_record.get("department_name", "")
            
            # First, remove all existing sharing
            await self.kb_sharing_repo.unshare_kb_from_all_departments(kb_id)
            
            # Then share with the new list of departments
            if shared_with_departments:
                sharing_result = await self.kb_sharing_repo.share_kb_with_multiple_departments(
                    knowledgebase_id=kb_id,
                    knowledgebase_name=kb_name,
                    source_department=source_department,
                    target_departments=shared_with_departments,
                    shared_by=user_email
                )
                result["sharing"] = sharing_result
            else:
                result["sharing"] = {"message": "All department sharing removed", "success_count": 0}
        
        return result

class UserAgentAccessService:
    """
    Service layer for managing user agent access.
    Applies business rules and orchestrates repository calls.
    """

    def __init__(self, user_agent_access_repo: UserAgentAccessRepository):
        self.user_agent_access_repo = user_agent_access_repo

    async def grant_agent_access(self, user_email: str, agent_id: str, given_access_by: str) -> Dict[str, Any]:
        """
        Grants access to an agent for a user.
        
        Args:
            user_email (str): The email of the user to grant access to.
            agent_id (str): The ID of the agent to grant access to.
            given_access_by (str): The admin who is granting the access.
            
        Returns:
            Dict[str, Any]: Status of the operation.
        """
        try:
            success, message = await self.user_agent_access_repo.grant_agent_access(user_email, agent_id, given_access_by)
            
            if success:
                return {
                    "success": True,
                    "message": message,
                    "user_email": user_email,
                    "agent_id": agent_id,
                    "granted_by": given_access_by
                }
            else:
                return {
                    "success": False,
                    "message": message,
                    "user_email": user_email,
                    "agent_id": agent_id
                }
        except Exception as e:
            log.error(f"Error in grant_agent_access service: {e}")
            return {
                "success": False,
                "message": f"Error granting access: {str(e)}",
                "user_email": user_email,
                "agent_id": agent_id
            }

    async def revoke_agent_access(self, user_email: str, agent_id: str) -> Dict[str, Any]:
        """
        Revokes access to an agent for a user.
        
        Args:
            user_email (str): The email of the user to revoke access from.
            agent_id (str): The ID of the agent to revoke access to.
            
        Returns:
            Dict[str, Any]: Status of the operation.
        """
        try:
            success = await self.user_agent_access_repo.revoke_agent_access(user_email, agent_id)
            
            if success:
                return {
                    "success": True,
                    "message": f"Successfully revoked access to agent '{agent_id}' for user '{user_email}'.",
                    "user_email": user_email,
                    "agent_id": agent_id
                }
            else:
                return {
                    "success": False,
                    "message": f"Failed to revoke access to agent '{agent_id}' for user '{user_email}'. User may not have had access.",
                    "user_email": user_email,
                    "agent_id": agent_id
                }
        except Exception as e:
            log.error(f"Error in revoke_agent_access service: {e}")
            return {
                "success": False,
                "message": f"Error revoking access: {str(e)}",
                "user_email": user_email,
                "agent_id": agent_id
            }

    async def get_user_agent_access(self, user_email: str) -> Dict[str, Any]:
        """
        Retrieves agent access information for a specific user.
        
        Args:
            user_email (str): The email of the user.
            
        Returns:
            Dict[str, Any]: User's agent access information.
        """
        try:
            return await self.user_agent_access_repo.get_user_agent_access(user_email)
        except Exception as e:
            log.error(f"Error in get_user_agent_access service: {e}")
            return {}

    async def get_all_user_agent_access(self) -> List[Dict[str, Any]]:
        """
        Retrieves all user agent access records.
        
        Returns:
            List[Dict[str, Any]]: List of all user agent access records.
        """
        try:
            return await self.user_agent_access_repo.get_all_user_agent_access()
        except Exception as e:
            log.error(f"Error in get_all_user_agent_access service: {e}")
            return []

    async def check_user_agent_access(self, user_email: str, agent_id: str) -> bool:
        """
        Checks if a user has access to a specific agent.
        
        Args:
            user_email (str): The email of the user.
            agent_id (str): The ID of the agent.
            
        Returns:
            bool: True if user has access, False otherwise.
        """
        try:
            return await self.user_agent_access_repo.check_user_agent_access(user_email, agent_id)
        except Exception as e:
            log.error(f"Error in check_user_agent_access service: {e}")
            return False

    async def get_users_with_agent_access(self, agent_id: str) -> List[str]:
        """
        Retrieves all users who have access to a specific agent.
        
        Args:
            agent_id (str): The ID of the agent.
            
        Returns:
            List[str]: List of user emails who have access to the agent.
        """
        try:
            return await self.user_agent_access_repo.get_users_with_agent_access(agent_id)
        except Exception as e:
            log.error(f"Error in get_users_with_agent_access service: {e}")
            return []

    async def get_all_tool_ids_for_user(self, user_email: str) -> Dict[str, Any]:
        """
        Retrieves all tool IDs bound to agents that the user has access to.
        
        Args:
            user_email (str): The email of the user.
            
        Returns:
            Dict[str, Any]: Dictionary containing tool IDs and access information.
        """
        try:
            # Get all tool IDs for the user
            result = await self.user_agent_access_repo.get_all_tool_ids_for_user(user_email)
            
            return {
                "user_email": user_email,
                "accessible_agent_ids": result["accessible_agent_ids"],
                "tool_ids": result["tool_ids"],
                "total_agents": len(result["accessible_agent_ids"]),
                "total_tools": len(result["tool_ids"]),
                "message": f"Retrieved {len(result['tool_ids'])} tool IDs for {len(result['accessible_agent_ids'])} accessible agents."
            }
            
        except Exception as e:
            log.error(f"Error in get_all_tool_ids_for_user service: {e}")
            return {
                "user_email": user_email,
                "accessible_agent_ids": [],
                "tool_ids": [],
                "total_agents": 0,
                "total_tools": 0,
                "message": f"Error retrieving tool IDs: {str(e)}"
            }

    async def get_user_agent_access_by_search_or_page(self,
                                                     search_value: str = '',
                                                     limit: int = 20,
                                                     page: int = 1,
                                                     created_by: Optional[str] = None) -> Dict[str, Any]:
        """
        Retrieves user agent access records with pagination and search filtering.

        Args:
            search_value (str, optional): Search term to filter by user_email or given_access_by.
            limit (int, optional): Number of results per page.
            page (int, optional): Page number for pagination.
            created_by (str, optional): The email ID of the user who granted access.

        Returns:
            dict: A dictionary containing the total count of records and the paginated details.
        """
        try:
            total_count = await self.user_agent_access_repo.get_total_user_agent_access_count(search_value, created_by)
            records = await self.user_agent_access_repo.get_user_agent_access_by_search_or_page_records(search_value, limit, page, created_by)

            # Calculate pagination info
            total_pages = (total_count + limit - 1) // limit  # Ceiling division
            
            return {
                "success": True,
                "message": f"Successfully retrieved {len(records)} user agent access records (page {page} of {total_pages})",
                "details": records,
                "total_count": total_count,
                "total_pages": total_pages,
                "current_page": page,
                "page_size": limit,
                "has_next": page < total_pages,
                "has_previous": page > 1
            }
            
        except Exception as e:
            log.error(f"Error in get_user_agent_access_by_search_or_page: {e}")
            return {
                "success": False,
                "message": f"Error retrieving user agent access records: {str(e)}",
                "details": [],
                "total_count": 0,
                "total_pages": 0,
                "current_page": page,
                "page_size": limit,
                "has_next": False,
                "has_previous": False
            }


# --- Group Management Service ---
class GroupService:
    """
    Service layer for group management.
    Applies business rules and orchestrates repository calls for group operations.
    """

    def __init__(self, group_repo: GroupRepository):
        self.group_repo = group_repo

    async def create_group(self, group_name: str, group_description: str, 
                           user_emails: List[str], agent_ids: List[str], created_by: str, department_name: str= None) -> Dict[str, Any]:
        """
        Creates a new group.
        
        Args:
            group_name (str): The unique name of the group.
            group_description (str): The description of the group.
            user_emails (List[str]): List of user emails in the group.
            agent_ids (List[str]): List of agent IDs in the group.
            created_by (str): The super-admin who created the group.
            
        Returns:
            Dict[str, Any]: Status of the operation.
        """
        try:
            # Check if group already exists
            if await self.group_repo.group_exists(group_name, department_name=department_name):
                return {
                    "success": False,
                    "message": f"Group '{group_name}' already exists.",
                    "group_name": group_name
                }
            
            success = await self.group_repo.create_group(
                group_name=group_name,
                group_description=group_description,
                user_emails=user_emails,
                agent_ids=agent_ids,
                created_by=created_by,
                department_name=department_name
            )
            
            if success:
                return {
                    "success": True,
                    "message": f"Successfully created Group '{group_name}'.",
                    "group_name": group_name,
                    "created_by": created_by,
                    "user_count": len(user_emails),
                    "agent_count": len(agent_ids)
                }
            else:
                # Repository returned False, likely due to unique constraint violation
                return {
                    "success": False,
                    "message": f"Failed to create Group '{group_name}'. Group name may already exist.",
                    "group_name": group_name
                }
                
        except Exception as e:
            log.error(f"Error in create_group service: {e}")
            return {
                "success": False,
                "message": f"Error creating group: {str(e)}",
                "group_name": group_name
            }

    async def get_group(self, group_name: str, department_name: str= None) -> Dict[str, Any]:
        """
        Retrieves a group by its name.
        
        Args:
            group_name (str): The group name.
            
        Returns:
            Dict[str, Any]: Group information or error message.
        """
        try:
            group = await self.group_repo.get_group(group_name, department_name=department_name)
            
            if group:
                return {
                    "success": True,
                    "group": group,
                    "message": f"Group '{group_name}' retrieved successfully."
                }
            else:
                return {
                    "success": False,
                    "message": f"Group '{group_name}' not found.",
                    "group": None
                }
                
        except Exception as e:
            log.error(f"Error in get_group service: {e}")
            return {
                "success": False,
                "message": f"Error retrieving group: {str(e)}",
                "group": None
            }

    async def get_all_groups(self, department_name: str=None) -> Dict[str, Any]:
        """
        Retrieves all groups.
        
        Returns:
            Dict[str, Any]: List of all groups.
        """
        try:
            groups = await self.group_repo.get_all_groups(department_name=department_name)
            
            return {
                "success": True,
                "groups": groups,
                "total_count": len(groups),
                "message": f"Retrieved {len(groups)} groups successfully."
            }
            
        except Exception as e:
            log.error(f"Error in get_all_groups service: {e}")
            return {
                "success": False,
                "groups": [],
                "total_count": 0,
                "message": f"Error retrieving groups: {str(e)}"
            }

    async def update_group(self, group_name: str, new_group_name: Optional[str] = None,
                           group_description: Optional[str] = None, user_emails: Optional[List[str]] = None,
                           agent_ids: Optional[List[str]] = None, department_name:str=None) -> Dict[str, Any]:
        """
        Updates a group's information.
        
        Args:
            group_name (str): The current group name to update.
            new_group_name (Optional[str]): New group name.
            group_description (Optional[str]): New group description.
            user_emails (Optional[List[str]]): New list of user emails.
            agent_ids (Optional[List[str]]): New list of agent IDs.
            
        Returns:
            Dict[str, Any]: Status of the operation.
        """
        try:
            # Check if group exists
            existing_group = await self.group_repo.get_group(group_name, department_name=department_name)
            if not existing_group:
                return {
                    "success": False,
                    "message": f"Group '{group_name}' not found.",
                    "group_name": group_name
                }
            
            success = await self.group_repo.update_group(
                group_name=group_name,
                new_group_name=new_group_name,
                group_description=group_description,
                user_emails=user_emails,
                agent_ids=agent_ids,
                department_name=department_name
            )
            
            if success:
                final_name = new_group_name if new_group_name else group_name
                return {
                    "success": True,
                    "message": f"Successfully updated Group '{final_name}'.",
                    "group_name": final_name
                }
            else:
                return {
                    "success": False,
                    "message": f"Failed to update Group '{group_name}'.",
                    "group_name": group_name
                }
                
        except Exception as e:
            log.error(f"Error in update_group service: {e}")
            return {
                "success": False,
                "message": f"Error updating group: {str(e)}",
                "group_name": group_name
            }

    async def delete_group(self, group_name: str, department_name:str =None) -> Dict[str, Any]:
        """
        Deletes a group.
        
        Args:
            group_name (str): The group name to delete.
            
        Returns:
            Dict[str, Any]: Status of the operation.
        """
        try:
            # Check if group exists
            existing_group = await self.group_repo.get_group(group_name, department_name=department_name)
            if not existing_group:
                return {
                    "success": False,
                    "message": f"Group '{group_name}' not found.",
                    "group_name": group_name
                }
            
            success = await self.group_repo.delete_group(group_name, department_name=department_name)
            
            if success:
                return {
                    "success": True,
                    "message": f"Successfully deleted Group '{group_name}'.",
                    "group_name": group_name
                }
            else:
                return {
                    "success": False,
                    "message": f"Failed to delete Group '{group_name}'.",
                    "group_name": group_name
                }
                
        except Exception as e:
            log.error(f"Error in delete_group service: {e}")
            return {
                "success": False,
                "message": f"Error deleting group: {str(e)}",
                "group_name": group_name
            }

    async def add_users_to_group(self, group_name: str, user_emails: List[str], department_name:str = None) -> Dict[str, Any]:
        """
        Adds users to a group.
        
        Args:
            group_name (str): The group name.
            user_emails (List[str]): List of user emails to add.
            
        Returns:
            Dict[str, Any]: Status of the operation with details about duplicates.
        """
        try:
            result = await self.group_repo.add_users_to_group(group_name, user_emails, department_name=department_name)
            
            if result["success"]:
                users_added = result["users_added"]
                users_already_present = result["users_already_present"]
                
                # Simple, clear messages
                if users_already_present and not users_added:
                    # All users were duplicates
                    message = f"All users are already in Group '{group_name}'."
                elif users_already_present and users_added:
                    # Some duplicates, some new
                    message = f"Added {len(users_added)} users. {len(users_already_present)} were already in group."
                else:
                    # All new users
                    message = f"Successfully added {len(users_added)} users to Group '{group_name}'."
                
                return {
                    "success": True,
                    "message": message,
                    "group_name": group_name,
                    "users_added": users_added,
                    "users_already_present": users_already_present,
                    "total_requested": len(user_emails)
                }
            else:
                return result  # Return the error result from repository
                
        except Exception as e:
            log.error(f"Error in add_users_to_group service: {e}")
            return {
                "success": False,
                "message": f"Error adding users to group: {str(e)}",
                "group_name": group_name
            }

    async def remove_users_from_group(self, group_name: str, user_emails: List[str], department_name:str = None) -> Dict[str, Any]:
        """
        Removes users from a group.
        
        Args:
            group_name (str): The group name.
            user_emails (List[str]): List of user emails to remove.
            
        Returns:
            Dict[str, Any]: Status of the operation.
        """
        try:
            success = await self.group_repo.remove_users_from_group(group_name, user_emails, department_name=department_name)
            
            if success:
                return {
                    "success": True,
                    "message": f"Successfully removed {len(user_emails)} users from Group '{group_name}'.",
                    "group_name": group_name,
                    "removed_users": user_emails
                }
            else:
                return {
                    "success": False,
                    "message": f"Failed to remove users from Group '{group_name}'. Group may not exist.",
                    "group_name": group_name
                }
                
        except Exception as e:
            log.error(f"Error in remove_users_from_group service: {e}")
            return {
                "success": False,
                "message": f"Error removing users from group: {str(e)}",
                "group_name": group_name
            }

    async def add_agents_to_group(self, group_name: str, agent_ids: List[str], department_name:str =None) -> Dict[str, Any]:
        """
        Adds agents to a group.
        
        Args:
            group_name (str): The group name.
            agent_ids (List[str]): List of agent IDs to add.
            
        Returns:
            Dict[str, Any]: Status of the operation with details about duplicates.
        """
        try:
            result = await self.group_repo.add_agents_to_group(group_name, agent_ids, department_name=department_name)
            
            if result["success"]:
                agents_added = result["agents_added"]
                agents_already_present = result["agents_already_present"]
                
                # Simple, clear messages
                if agents_already_present and not agents_added:
                    # All agents were duplicates
                    message = f"All agents are already in Group '{group_name}'."
                elif agents_already_present and agents_added:
                    # Some duplicates, some new
                    message = f"Added {len(agents_added)} agents. {len(agents_already_present)} were already in group."
                else:
                    # All new agents
                    message = f"Successfully added {len(agents_added)} agents to Group '{group_name}'."
                
                return {
                    "success": True,
                    "message": message,
                    "group_name": group_name,
                    "agents_added": agents_added,
                    "agents_already_present": agents_already_present,
                    "total_requested": len(agent_ids)
                }
            else:
                return result  # Return the error result from repository
                
        except Exception as e:
            log.error(f"Error in add_agents_to_group service: {e}")
            return {
                "success": False,
                "message": f"Error adding agents to group: {str(e)}",
                "group_name": group_name
            }

    async def remove_agents_from_group(self, group_name: str, agent_ids: List[str], department_name:str =None) -> Dict[str, Any]:
        """
        Removes agents from a group.
        
        Args:
            group_name (str): The group name.
            agent_ids (List[str]): List of agent IDs to remove.
            
        Returns:
            Dict[str, Any]: Status of the operation.
        """
        try:
            success = await self.group_repo.remove_agents_from_group(group_name, agent_ids, department_name=department_name)
            
            if success:
                return {
                    "success": True,
                    "message": f"Successfully removed {len(agent_ids)} agents from Group '{group_name}'.",
                    "group_name": group_name,
                    "removed_agents": agent_ids
                }
            else:
                return {
                    "success": False,
                    "message": f"Failed to remove agents from Group '{group_name}'. Group may not exist.",
                    "group_name": group_name
                }
                
        except Exception as e:
            log.error(f"Error in remove_agents_from_group service: {e}")
            return {
                "success": False,
                "message": f"Error removing agents from group: {str(e)}",
                "group_name": group_name
            }

    async def get_groups_by_user(self, user_email: str, department_name:str = None) -> Dict[str, Any]:
        """
        Retrieves all groups that contain a specific user.
        
        Args:
            user_email (str): The user email to search for.
            
        Returns:
            Dict[str, Any]: List of groups containing the user.
        """
        try:
            groups = await self.group_repo.get_groups_by_user(user_email, department_name=department_name)
            
            return {
                "success": True,
                "groups": groups,
                "total_count": len(groups),
                "user_email": user_email,
                "message": f"Found {len(groups)} groups containing user '{user_email}'."
            }
            
        except Exception as e:
            log.error(f"Error in get_groups_by_user service: {e}")
            return {
                "success": False,
                "groups": [],
                "total_count": 0,
                "user_email": user_email,
                "message": f"Error retrieving groups for user: {str(e)}"
            }

    async def get_groups_by_agent(self, agent_id: str, department_name:str = None) -> Dict[str, Any]:
        """
        Retrieves all groups that contain a specific agent.
        
        Args:
            agent_id (str): The agent ID to search for.
            
        Returns:
            Dict[str, Any]: List of groups containing the agent.
        """
        try:
            groups = await self.group_repo.get_groups_by_agent(agent_id, department_name=department_name)
            
            return {
                "success": True,
                "groups": groups,
                "total_count": len(groups),
                "agent_id": agent_id,
                "message": f"Found {len(groups)} groups containing agent '{agent_id}'."
            }
            
        except Exception as e:
            log.error(f"Error in get_groups_by_agent service: {e}")
            return {
                "success": False,
                "groups": [],
                "total_count": 0,
                "agent_id": agent_id,
                "message": f"Error retrieving groups for agent: {str(e)}"
            }

    async def get_groups_by_search_or_page(self,
                                           search_value: str = '',
                                           limit: int = 20,
                                           page: int = 1,
                                           created_by: Optional[str] = None, department_name:str = None) -> Dict[str, Any]:
        """
        Retrieves groups with pagination and search filtering.

        Args:
            search_value (str, optional): Group name to filter by.
            limit (int, optional): Number of results per page.
            page (int, optional): Page number for pagination.
            created_by (str, optional): The email ID of the user who created the group.

        Returns:
            dict: A dictionary containing the total count of groups and the paginated group details.
        """
        try:
            total_count = await self.group_repo.get_total_group_count(search_value, created_by, department_name=department_name)
            group_records = await self.group_repo.get_groups_by_search_or_page_records(search_value, limit, page, created_by, department_name=department_name)

            # Calculate pagination info
            total_pages = (total_count + limit - 1) // limit  # Ceiling division
            
            return {
                "success": True,
                "message": f"Successfully retrieved {len(group_records)} groups (page {page} of {total_pages})",
                "details": group_records,
                "total_count": total_count,
                "total_pages": total_pages,
                "current_page": page,
                "page_size": limit,
                "has_next": page < total_pages,
                "has_previous": page > 1
            }
            
        except Exception as e:
            log.error(f"Error in get_groups_by_search_or_page: {e}")
            return {
                "success": False,
                "message": f"Error retrieving groups: {str(e)}",
                "details": [],
                "total_count": 0,
                "total_pages": 0,
                "current_page": page,
                "page_size": limit,
                "has_next": False,
                "has_previous": False
            }

class GroupSecretsService:
    """
    Service layer for group secrets management.
    Handles business logic for group-scoped encrypted key-value storage with role-based access control.
    """

    def __init__(self, group_secrets_repo: GroupSecretsRepository, group_repo: GroupRepository, secrets_handler):
        self.group_secrets_repo = group_secrets_repo
        self.group_repo = group_repo
        self.secrets_handler = secrets_handler

    async def create_group_secret(self, group_name: str, key_name: str, secret_value: str, 
                                   user: User, department_name:str = None) -> Dict[str, Any]:
        """
        Creates a new group secret_record. Only developers and admins can create secrets.
        
        Args:
            group_name (str): The group name.
            key_name (str): The name of the secret_key.
            secret_value (str): The plain text secret_value.
            user (User): The user creating the secret_record.
            
        Returns:
            Dict[str, Any]: Status of the operation.
        """
        try:
            # Check if group exists
            if not await self.group_repo.group_exists(group_name, department_name=department_name):
                return {
                    "success": False,
                    "message": f"Group '{group_name}' does not exist.",
                    "group_name": group_name,
                    "key_name": key_name
                }
            
            # Check if user is a group member (admin/super admin bypass group restrictions)
            if user.role not in [UserRole.SUPER_ADMIN]:
                if not await self.group_repo.check_user_group_access(user.email, group_name, department_name=department_name):
                    return {
                        "success": False,
                        "message": f"You don't not have access to Group '{group_name}'.",
                        "group_name": group_name,
                        "key_name": key_name
                    }
            
            # Check if secret_record already exists
            if await self.group_secrets_repo.group_secret_exists(group_name, key_name, department_name=department_name):
                return {
                    "success": False,
                    "message": f"Secret '{key_name}' already exists in Group '{group_name}'.",
                    "group_name": group_name,
                    "key_name": key_name
                }
            
            # Encrypt the secret_value
            encrypted_value = self.secrets_handler._encrypt_value(secret_value)
            
            # Create the group secret_record
            success = await self.group_secrets_repo.create_group_secret(
                group_name, key_name, encrypted_value, user.email, department_name=department_name
            )
            
            if success:
                return {
                    "success": True,
                    "message": f"Successfully created group secret '{key_name}' in Group '{group_name}'.",
                    "group_name": group_name,
                    "key_name": key_name
                }
            else:
                return {
                    "success": False,
                    "message": f"Failed to create group secret '{key_name}' in Group '{group_name}'.",
                    "group_name": group_name,
                    "key_name": key_name
                }
                
        except Exception as e:
            log.error(f"Error in create_group_secret service: {e}")
            return {
                "success": False,
                "message": f"Error creating group secret: {str(e)}",
                "group_name": group_name,
                "key_name": key_name
            }

    async def get_group_secret(self, group_name: str, key_name: str, user: User, department_name:str = None) -> Dict[str, Any]:
        """
        Retrieves a group secret_record. All group members can read secrets.
        
        Args:
            group_name (str): The group name.
            key_name (str): The name of the secret_key.
            user (User): The user requesting the secret_record.
            
        Returns:
            Dict[str, Any]: The secret_value if authorized, error otherwise.
        """
        try:
            # Check if group exists
            if not await self.group_repo.group_exists(group_name,department_name=department_name):
                return {
                    "success": False,
                    "message": f"Group '{group_name}' does not exist.",
                    "group_name": group_name,
                    "key_name": key_name
                }
            
            # Check if user is a group member (admin/super admin bypass group restrictions)
            if user.role not in [UserRole.SUPER_ADMIN]:
                if not await self.group_repo.check_user_group_access(user.email, group_name, department_name=department_name):
                    return {
                        "success": False,
                        "message": f"You don't not have access to Group '{group_name}'.",
                        "group_name": group_name,
                        "key_name": key_name
                    }
            
            
            # Get the encrypted secret_record
            secret_record = await self.group_secrets_repo.get_group_secret(group_name, key_name, department_name=department_name)
            if not secret_record:
                return {
                    "success": False,
                    "message": f"Secret '{key_name}' not found in Group '{group_name}'.",
                    "group_name": group_name,
                    "key_name": key_name
                }
            
            # Decrypt the secret_value
            decrypted_value = self.secrets_handler._decrypt_value(secret_record['encrypted_value'])
            
            return {
                "success": True,
                "message": f"Successfully retrieved group secret '{key_name}' from Group '{group_name}'.",
                "group_name": group_name,
                "key_name": key_name,
                "secret_value": decrypted_value,
                "created_by": secret_record['created_by'],
                "created_at": secret_record['created_at'],
                "updated_at": secret_record['updated_at']
            }
            
        except Exception as e:
            log.error(f"Error in get_group_secret service: {e}")
            return {
                "success": False,
                "message": f"Error retrieving group secret: {str(e)}",
                "group_name": group_name,
                "key_name": key_name
            }
    
    async def update_group_secret(self, group_name: str, key_name: str, secret_value: str, 
                                   user: User, department_name:str = None) -> Dict[str, Any]:
        """
        Updates an existing group secret_record. Only developers and admins can update secrets.
        
        Args:
            group_name (str): The group name.
            key_name (str): The name of the secret_key.
            secret_value (str): The new plain text secret_value.
            user (User): The user updating the secret_record.
            
        Returns:
            Dict[str, Any]: Status of the operation.
        """
        try:
            # Check if group exists
            if not await self.group_repo.group_exists(group_name, department_name=department_name):
                return {
                    "success": False,
                    "message": f"Group '{group_name}' does not exist.",
                    "group_name": group_name,
                    "key_name": key_name
                }
            
            # Check if user is a group member (admin/super admin bypass group restrictions)
            if user.role not in [UserRole.SUPER_ADMIN]:
                if not await self.group_repo.check_user_group_access(user.email, group_name, department_name=department_name):
                    return {
                        "success": False,
                        "message": f"You don't not have access to Group '{group_name}'.",
                        "group_name": group_name,
                        "key_name": key_name
                    }
            
            # Check if secret_record exists
            if not await self.group_secrets_repo.group_secret_exists(group_name, key_name, department_name=department_name):
                return {
                    "success": False,
                    "message": f"Secret '{key_name}' does not exist in Group '{group_name}'.",
                    "group_name": group_name,
                    "key_name": key_name
                }
            
            # Encrypt the new secret_value
            encrypted_value = self.secrets_handler._encrypt_value(secret_value)
            
            # Update the group secret_data
            success = await self.group_secrets_repo.update_group_secret(
                group_name, key_name, encrypted_value, user.email, department_name=department_name
            )
            
            if success:
                return {
                    "success": True,
                    "message": f"Successfully updated group secret '{key_name}' in Group '{group_name}'.",
                    "group_name": group_name,
                    "key_name": key_name
                }
            else:
                return {
                    "success": False,
                    "message": f"Failed to update group secret '{key_name}' in Group '{group_name}'.",
                    "group_name": group_name,
                    "key_name": key_name
                }
                
        except Exception as e:
            log.error(f"Error in update_group_secret service: {e}")
            return {
                "success": False,
                "message": f"Error updating group secret: {str(e)}",
                "group_name": group_name,
                "key_name": key_name
            }

    async def delete_group_secret(self, group_name: str, key_name: str, user: User, department_name: str=None) -> Dict[str, Any]:
        """
        Deletes a group secret_record. Only developers and admins can delete secrets.
        
        Args:
            group_name (str): The group name.
            key_name (str): The name of the secret_key.
            user (User): The user deleting the secret_record.
            
        Returns:
            Dict[str, Any]: Status of the operation.
        """
        try:
            # Check if group exists
            if not await self.group_repo.group_exists(group_name, department_name=department_name):
                return {
                    "success": False,
                    "message": f"Group '{group_name}' does not exist.",
                    "group_name": group_name,
                    "key_name": key_name
                }
            
            # Check if user is a group member (admin/super admin bypass group restrictions)
            if user.role not in [UserRole.SUPER_ADMIN]:
                if not await self.group_repo.check_user_group_access(user.email, group_name, department_name=department_name):
                    return {
                        "success": False,
                        "message": f"You don't not have access to Group '{group_name}'.",
                        "group_name": group_name,
                        "key_name": key_name
                    }
            
            # Delete the group secret_record
            success = await self.group_secrets_repo.delete_group_secret(group_name, key_name, department_name=department_name)
            
            if success:
                return {
                    "success": True,
                    "message": f"Successfully deleted group secret '{key_name}' from Group '{group_name}'.",
                    "group_name": group_name,
                    "key_name": key_name
                }
            else:
                return {
                    "success": False,
                    "message": f"Secret '{key_name}' not found in Group '{group_name}'.",
                    "group_name": group_name,
                    "key_name": key_name
                }
                
        except Exception as e:
            log.error(f"Error in delete_group_secret service: {e}")
            return {
                "success": False,
                "message": f"Error deleting group secret: {str(e)}",
                "group_name": group_name,
                "key_name": key_name
            }

    async def list_group_secrets(self, group_name: str, user: User, department_name:str =None) -> Dict[str, Any]:
        """
        Lists all secrets for a group (without values for security). All group members can list secrets.
        
        Args:
            group_name (str): The group name.
            user (User): The user requesting the list.
            
        Returns:
            Dict[str, Any]: List of secret_metadata.
        """
        try:
            # Check if group exists
            if not await self.group_repo.group_exists(group_name, department_name=department_name):
                return {
                    "success": False,
                    "message": f"Group '{group_name}' does not exist.",
                    "group_name": group_name,
                    "secrets": []
                }
            
            # Check if user is a group member (admin/super admin bypass group restrictions)
            if user.role not in [UserRole.SUPER_ADMIN]:
                if not await self.group_repo.check_user_group_access(user.email, group_name, department_name=department_name):
                    return {
                        "success": False,
                        "message": f"You don't not have access to Group '{group_name}'.",
                        "group_name": group_name,
                        "secrets": []
                    }
            
            # Get all secrets for the group
            secrets = await self.group_secrets_repo.list_group_secrets(group_name, department_name=department_name)
            
            return {
                "success": True,
                "message": f"Successfully retrieved {len(secrets)} group secrets for Group '{group_name}'.",
                "group_name": group_name,
                "secrets": secrets,
                "total_count": len(secrets)
            }
            
        except Exception as e:
            log.error(f"Error in list_group_secrets service: {e}")
            return {
                "success": False,
                "message": f"Error listing group secrets: {str(e)}",
                "group_name": group_name,
                "secrets": []
            }



# --- Role Access Service ---

class RoleAccessService:
    """
    Service for role-based access control management.
    
    Manages role permissions within departments using a clean two-table design:
    - departments table: stores available roles per department as JSONB arrays
    - role_access table: stores detailed permissions for department+role combinations
    
    This design eliminates the need for a separate global roles table.
    """

    def __init__(self, role_repo: RoleRepository, user_repo: UserRepository, audit_repo: AuditLogRepository, department_repo: DepartmentRepository):
        self.role_repo = role_repo
        self.user_repo = user_repo
        self.audit_repo = audit_repo
        self.department_repo = department_repo

    def _json_to_access_permission(self, json_data) -> AccessPermission:
        """Convert JSON permission data to AccessPermission object"""
        # Handle different data types that might come from PostgreSQL
        if isinstance(json_data, dict):
            return AccessPermission(
                tools=json_data.get('tools', False),
                agents=json_data.get('agents', False)
            )
        elif isinstance(json_data, str):
            # If it's a JSON string, parse it
            try:
                import json
                parsed_data = json.loads(json_data)
                return AccessPermission(
                    tools=parsed_data.get('tools', False),
                    agents=parsed_data.get('agents', False)
                )
            except (json.JSONDecodeError, TypeError):
                log.warning(f"Failed to parse JSON string: {json_data}")
                return AccessPermission(tools=False, agents=False)
        elif isinstance(json_data, bool):
            # Backward compatibility for boolean values
            return AccessPermission(tools=json_data, agents=json_data)
        else:
            log.warning(f"Unexpected data type for permission: {type(json_data)} - {json_data}")
            return AccessPermission(tools=False, agents=False)



    async def get_all_roles(self) -> RoleListResponse:
        """Get all roles from all departments"""
        try:
            # Get all departments and their roles
            all_departments = await self.department_repo.get_all_departments()
            roles = []

            for dept in all_departments:
                department_name = dept.get('department_name')
                department_roles = await self.department_repo.get_department_roles(department_name)
                
                if department_roles:
                    for role_name in department_roles:
                        # Create a role entry with department context
                        role = RoleModel(
                            role_name=f"{department_name}:{role_name}",  # Show department context
                            created_at=dept.get('created_at'),
                            created_by=dept.get('created_by')
                        )
                        roles.append(role)

            return RoleListResponse(success=True, message="Department roles retrieved successfully", roles=roles)

        except Exception as e:
            log.error(f"Get all roles error: {e}")
            return RoleListResponse(success=False, message="Failed to retrieve roles due to an error")

    async def set_role_permissions(self, request: SetRolePermissionsRequest, set_by: str,
                                  ip_address: str = None, user_agent: str = None, department_name: str = None) -> RolePermissionsResponse:
        """Set permissions for a role - Admin users can set permissions for non-Admin roles in their department, SuperAdmin can set permissions for any role"""
        try:
            # Validate setter permissions
            setter_data = await self.user_repo.get_user_by_email(set_by, department_name=department_name)
            if not setter_data:
                return RolePermissionsResponse(success=False, message="Setter user not found")

            setter_role = setter_data['role']
            if setter_role not in ['Admin', 'SuperAdmin']:
                return RolePermissionsResponse(success=False, message="Only Admin and SuperAdmin can set role permissions")
            
            # Additional department-level validation for Admin users
            if setter_role == 'Admin':
                setter_department = setter_data.get('department_name') 
                if setter_department != request.department_name:
                    return RolePermissionsResponse(
                        success=False, 
                        message=f"Admin users can only set permissions for their own department ('{setter_department}'). Cannot modify department '{request.department_name}'."
                    )
                
                # Admin users cannot modify permissions for Admin roles
                if request.role_name == 'Admin':
                    return RolePermissionsResponse(
                        success=False,
                        message="Only SuperAdmin can set permissions for Admin roles. Admin users cannot modify permissions for Admin roles."
                    )

            # Check if role exists in the specified department
            if not await self.role_repo.role_exists(request.role_name, request.department_name):
                return RolePermissionsResponse(success=False, message=f"Role '{request.role_name}' does not exist in department '{request.department_name}'")

            # Convert AccessPermission objects to dictionaries
            read_dict = {"tools": request.read_access.tools, "agents": request.read_access.agents}
            add_dict = {"tools": request.add_access.tools, "agents": request.add_access.agents}
            update_dict = {"tools": request.update_access.tools, "agents": request.update_access.agents}
            delete_dict = {"tools": request.delete_access.tools, "agents": request.delete_access.agents}
            execute_dict = {"tools": request.execute_access.tools, "agents": request.execute_access.agents}

            # Set permissions
            success = await self.role_repo.set_role_permissions(
                department_name=request.department_name,
                role_name=request.role_name,
                read_access=read_dict,
                add_access=add_dict,
                update_access=update_dict,
                delete_access=delete_dict,
                execute_access=execute_dict,
                execution_steps_access=request.execution_steps_access,
                tool_verifier_flag_access=request.tool_verifier_flag_access,
                plan_verifier_flag_access=request.plan_verifier_flag_access,
                online_evaluation_flag_access=request.online_evaluation_flag_access,
                evaluation_access=request.evaluation_access,
                vault_access=request.vault_access,
                data_connector_access=request.data_connector_access,
                knowledgebase_access=request.knowledgebase_access,
                validator_access=request.validator_access,
                file_context_access=request.file_context_access,
                canvas_view_access=request.canvas_view_access,
                context_access=request.context_access,
                created_by=set_by
            )

            if not success:
                return RolePermissionsResponse(success=False, message="Failed to set role permissions")

            # Log the action
            await self.audit_repo.log_action(
                user_id=set_by,
                action="ROLE_PERMISSIONS_SET",
                resource_type="role_access",
                resource_id=request.role_name,
                new_value=f"Role: {request.role_name}, Read: {read_dict}, Add: {add_dict}, Update: {update_dict}, Delete: {delete_dict}, Execute: {execute_dict}, ExecutionStepsAccess: {request.execution_steps_access}, ToolVerifierAccess: {request.tool_verifier_flag_access}, PlanVerifierAccess: {request.plan_verifier_flag_access}, OnlineEvaluationAccess: {request.online_evaluation_flag_access}, EvaluationAccess: {request.evaluation_access}, VaultAccess: {request.vault_access}, DataConnectorAccess: {request.data_connector_access}, KnowledgebaseAccess: {request.knowledgebase_access}, ValidatorAccess: {request.validator_access}, FileContextAccess: {request.file_context_access}, CanvasViewAccess: {request.canvas_view_access}, ContextAccess: {request.context_access}",
                ip_address=ip_address,
                user_agent=user_agent
            )

            # Get the updated permissions
            permissions_data = await self.role_repo.get_role_permissions(request.department_name, request.role_name)
            if permissions_data:
                permissions_model = RoleAccessModel(
                    department_name=permissions_data['department_name'],
                    role_name=permissions_data['role_name'],
                    read_access=self._json_to_access_permission(permissions_data['read_access']),
                    add_access=self._json_to_access_permission(permissions_data['add_access']),
                    update_access=self._json_to_access_permission(permissions_data['update_access']),
                    delete_access=self._json_to_access_permission(permissions_data['delete_access']),
                    execute_access=self._json_to_access_permission(permissions_data['execute_access']),
                    execution_steps_access=permissions_data.get('execution_steps_access', False),
                    tool_verifier_flag_access=permissions_data.get('tool_verifier_flag_access', False),
                    plan_verifier_flag_access=permissions_data.get('plan_verifier_flag_access', False),
                    online_evaluation_flag_access=permissions_data.get('online_evaluation_flag_access', False),
                    vault_access=permissions_data.get('vault_access', False),
                    data_connector_access=permissions_data.get('data_connector_access', False),
                    knowledgebase_access=permissions_data.get('knowledgebase_access', False),
                    validator_access=permissions_data.get('validator_access', False),
                    file_context_access=permissions_data.get('file_context_access', False),
                    canvas_view_access=permissions_data.get('canvas_view_access', False),
                    context_access=permissions_data.get('context_access', False),
                    created_at=permissions_data['created_at'],
                    updated_at=permissions_data['updated_at'],
                    created_by=permissions_data['created_by']
                )
                return RolePermissionsResponse(success=True, message="Role permissions set successfully", permissions=permissions_model)
            else:
                return RolePermissionsResponse(success=True, message="Role permissions set successfully")

        except Exception as e:
            log.error(f"Set role permissions error: {e}")
            return RolePermissionsResponse(success=False, message="Failed to set permissions due to an error")

    async def get_role_permissions(self, department_name: str, role_name: str) -> RolePermissionsResponse:
        """Get permissions for a specific role in a specific department"""
        try:
            permissions_data = await self.role_repo.get_role_permissions(department_name, role_name)
            
            if not permissions_data:
                # Return default permissions with all fields set to false
                from datetime import datetime
                default_access = AccessPermission(tools=False, agents=False)
                default_permissions = RoleAccessModel(
                    department_name=department_name,
                    role_name=role_name,
                    read_access=default_access,
                    add_access=default_access,
                    update_access=default_access,
                    delete_access=default_access,
                    execute_access=default_access,
                    execution_steps_access=False,
                    tool_verifier_flag_access=False,
                    plan_verifier_flag_access=False,
                    online_evaluation_flag_access=False,
                    evaluation_access=False,
                    vault_access=False,
                    data_connector_access=False,
                    knowledgebase_access=False,
                    validator_access=False,
                    file_context_access=False,
                    canvas_view_access=False,
                    context_access=False,
                    created_at=datetime.now(),
                    updated_at=datetime.now(),
                    created_by=None
                )
                return RolePermissionsResponse(success=True, message=f"No permissions configured for role '{role_name}' in department '{department_name}', returning default (all false)", permissions=default_permissions)

            permissions_model = RoleAccessModel(
                department_name=permissions_data['department_name'],
                role_name=permissions_data['role_name'],
                read_access=self._json_to_access_permission(permissions_data['read_access']),
                add_access=self._json_to_access_permission(permissions_data['add_access']),
                update_access=self._json_to_access_permission(permissions_data['update_access']),
                delete_access=self._json_to_access_permission(permissions_data['delete_access']),
                execute_access=self._json_to_access_permission(permissions_data['execute_access']),
                execution_steps_access=permissions_data.get('execution_steps_access', False),
                tool_verifier_flag_access=permissions_data.get('tool_verifier_flag_access', False),
                plan_verifier_flag_access=permissions_data.get('plan_verifier_flag_access', False),
                online_evaluation_flag_access=permissions_data.get('online_evaluation_flag_access', False),
                evaluation_access=permissions_data.get('evaluation_access', False),
                vault_access=permissions_data.get('vault_access', False),
                data_connector_access=permissions_data.get('data_connector_access', False),
                knowledgebase_access=permissions_data.get('knowledgebase_access', False),
                validator_access=permissions_data.get('validator_access', False),
                file_context_access=permissions_data.get('file_context_access', False),
                canvas_view_access=permissions_data.get('canvas_view_access', False),
                context_access=permissions_data.get('context_access', False),
                created_at=permissions_data['created_at'],
                updated_at=permissions_data['updated_at'],
                created_by=permissions_data['created_by']
            )

            return RolePermissionsResponse(success=True, message="Permissions retrieved successfully", permissions=permissions_model)

        except Exception as e:
            log.error(f"Get role permissions error: {e}")
            return RolePermissionsResponse(success=False, message="Failed to retrieve permissions due to an error")

    async def get_all_role_permissions(self, department_name: str = None) -> AllRolePermissionsResponse:
        """Get all role permissions, optionally filtered by department"""
        try:
            role_permissions_data = await self.role_repo.get_all_role_permissions(department_name)
                        
            # Convert raw data to proper models (same format as get_role_permissions)
            permissions_models = []
            for perm_data in role_permissions_data:
                role_name = perm_data.get('role_name')
                if role_name:  # Only process if role exists
                    # Check if role has permissions configured (not ALL NULL values)
                    has_permissions = any([
                        perm_data.get('read_access') is not None,
                        perm_data.get('add_access') is not None,
                        perm_data.get('update_access') is not None,
                        perm_data.get('delete_access') is not None,
                        perm_data.get('execute_access') is not None,
                        perm_data.get('execution_steps_access') is not None,
                        perm_data.get('tool_verifier_flag_access') is not None,
                        perm_data.get('plan_verifier_flag_access') is not None,
                        perm_data.get('online_evaluation_flag_access') is not None,
                        perm_data.get('vault_access') is not None,
                        perm_data.get('data_connector_access') is not None,
                        perm_data.get('knowledgebase_access') is not None,
                        perm_data.get('validator_access') is not None,
                        perm_data.get('file_context_access') is not None,
                        perm_data.get('canvas_view_access') is not None,
                        perm_data.get('context_access') is not None
                    ])
                    
                    if has_permissions:
                        # Role has permissions configured
                        from datetime import datetime
                        default_datetime = datetime.now()
                        
                        permissions_model = RoleAccessModel(
                            department_name=perm_data.get('department_name', 'General'),
                            role_name=role_name,
                            read_access=self._json_to_access_permission(perm_data.get('read_access')),
                            add_access=self._json_to_access_permission(perm_data.get('add_access')),
                            update_access=self._json_to_access_permission(perm_data.get('update_access')),
                            delete_access=self._json_to_access_permission(perm_data.get('delete_access')),
                            execute_access=self._json_to_access_permission(perm_data.get('execute_access')),
                            execution_steps_access=perm_data.get('execution_steps_access', False),
                            tool_verifier_flag_access=perm_data.get('tool_verifier_flag_access', False),
                            plan_verifier_flag_access=perm_data.get('plan_verifier_flag_access', False),
                            online_evaluation_flag_access=perm_data.get('online_evaluation_flag_access', False),
                            evaluation_access=perm_data.get('evaluation_access', False),
                            vault_access=perm_data.get('vault_access', False),
                            data_connector_access=perm_data.get('data_connector_access', False),
                            knowledgebase_access=perm_data.get('knowledgebase_access', False),
                            validator_access=perm_data.get('validator_access', False),
                            file_context_access=perm_data.get('file_context_access', False),
                            canvas_view_access=perm_data.get('canvas_view_access', False),
                            context_access=perm_data.get('context_access', False),
                            created_at=perm_data.get('created_at') or default_datetime,
                            updated_at=perm_data.get('updated_at') or default_datetime,
                            created_by=perm_data.get('created_by') or "system"
                        )
                        permissions_models.append(permissions_model)
                    else:
                        # Role exists but no permissions configured - create default model
                        from datetime import datetime
                        default_datetime = datetime.now()
                        permissions_model = RoleAccessModel(
                            role_name=role_name,
                            read_access=AccessPermission(tools=False, agents=False),
                            add_access=AccessPermission(tools=False, agents=False),
                            update_access=AccessPermission(tools=False, agents=False),
                            delete_access=AccessPermission(tools=False, agents=False),
                            execute_access=AccessPermission(tools=False, agents=False),
                            execution_steps_access=False,
                            tool_verifier_flag_access=False,
                            plan_verifier_flag_access=False,
                            online_evaluation_flag_access=False,
                            evaluation_access=False,
                            vault_access=False,
                            data_connector_access=False,
                            knowledgebase_access=False,
                            validator_access=False,
                            file_context_access=False,
                            canvas_view_access=False,
                            context_access=False,
                            created_at=default_datetime,
                            updated_at=default_datetime,
                            created_by="system"
                        )
                        permissions_models.append(permissions_model)
            
            return AllRolePermissionsResponse(success=True, message="All role permissions retrieved successfully", role_permissions=permissions_models)

        except Exception as e:
            log.error(f"Get all role permissions error: {e}")
            return AllRolePermissionsResponse(success=False, message="Failed to retrieve all permissions due to an error")



    async def update_role_permissions(self, request: UpdateRolePermissionsRequest, updated_by: str,
                                     ip_address: str = None, user_agent: str = None, department_name: str = None) -> RolePermissionsResponse:
        """Update specific permissions for a role - Admin users can update permissions for non-Admin roles in their department, SuperAdmin can update permissions for any role"""
        try:
            # Validate updater permissions
            updater_data = await self.user_repo.get_user_by_email(updated_by, department_name=department_name)
            if not updater_data:
                return RolePermissionsResponse(success=False, message="Updater user not found")

            updater_role = updater_data['role']
            if updater_role not in ['Admin', 'SuperAdmin']:
                return RolePermissionsResponse(success=False, message="Only Admin and SuperAdmin can update role permissions")
            
            # Additional department-level validation for Admin users
            if updater_role == 'Admin':
                updater_department = updater_data.get('department_name') 
                if updater_department != request.department_name:
                    return RolePermissionsResponse(
                        success=False, 
                        message=f"Admin users can only update permissions for their own department ('{updater_department}'). Cannot modify department '{request.department_name}'."
                    )
                
                # Admin users cannot modify permissions for Admin roles
                if request.role_name == 'Admin':
                    return RolePermissionsResponse(
                        success=False,
                        message="Only SuperAdmin can update permissions for Admin roles. Admin users cannot modify permissions for Admin roles."
                    )

            # Check if role exists and get current permissions
            current_permissions = await self.role_repo.get_role_permissions(request.department_name, request.role_name)
            if not current_permissions:
                return RolePermissionsResponse(success=False, message=f"Role '{request.role_name}' does not exist in department '{request.department_name}' or has no permissions configured")

            # Prepare updated permissions - keep current values if new ones are not provided
            # Convert AccessPermission objects to dictionaries when provided
            updated_permissions = {}
            
            if request.read_access is not None:
                updated_permissions['read_access'] = {"tools": request.read_access.tools, "agents": request.read_access.agents}
            if request.add_access is not None:
                updated_permissions['add_access'] = {"tools": request.add_access.tools, "agents": request.add_access.agents}
            if request.update_access is not None:
                updated_permissions['update_access'] = {"tools": request.update_access.tools, "agents": request.update_access.agents}
            if request.delete_access is not None:
                updated_permissions['delete_access'] = {"tools": request.delete_access.tools, "agents": request.delete_access.agents}
            if request.execute_access is not None:
                updated_permissions['execute_access'] = {"tools": request.execute_access.tools, "agents": request.execute_access.agents}

            # Update permissions using the partial update method
            success = await self.role_repo.update_role_permissions(
                department_name=request.department_name,
                role_name=request.role_name,
                execution_steps_access=request.execution_steps_access,
                tool_verifier_flag_access=request.tool_verifier_flag_access,
                plan_verifier_flag_access=request.plan_verifier_flag_access,
                online_evaluation_flag_access=request.online_evaluation_flag_access,
                evaluation_access=request.evaluation_access,
                vault_access=request.vault_access,
                data_connector_access=request.data_connector_access,
                knowledgebase_access=request.knowledgebase_access,
                validator_access=request.validator_access,
                file_context_access=request.file_context_access,
                canvas_view_access=request.canvas_view_access,
                context_access=request.context_access,
                **updated_permissions
            )

            if not success:
                return RolePermissionsResponse(success=False, message="Failed to update role permissions")

            # Log the action
            updated_fields = []
            for field, value in request.model_dump(exclude_unset=True).items():
                if field != 'role_name' and value is not None:
                    if field == 'execution_steps_access':
                        updated_fields.append(f"ExecutionStepsAccess={value}")
                    elif field == 'tool_verifier_flag_access':
                        updated_fields.append(f"ToolVerifierAccess={value}")
                    elif field == 'plan_verifier_flag_access':
                        updated_fields.append(f"PlanVerifierAccess={value}")
                    elif field == 'online_evaluation_flag_access':
                        updated_fields.append(f"OnlineEvaluationAccess={value}")
                    elif field == 'evaluation_access':
                        updated_fields.append(f"EvaluationAccess={value}")
                    elif field == 'vault_access':
                        updated_fields.append(f"VaultAccess={value}")
                    elif field == 'data_connector_access':
                        updated_fields.append(f"DataConnectorAccess={value}")
                    elif field == 'knowledgebase_access':
                        updated_fields.append(f"KnowledgebaseAccess={value}")
                    elif field == 'validator_access':
                        updated_fields.append(f"ValidatorAccess={value}")
                    elif field == 'file_context_access':
                        updated_fields.append(f"FileContextAccess={value}")
                    elif field == 'canvas_view_access':
                        updated_fields.append(f"CanvasViewAccess={value}")
                    elif field == 'context_access':
                        updated_fields.append(f"ContextAccess={value}")
                    else:
                        updated_fields.append(f"{field}={value}")
            
            await self.audit_repo.log_action(
                user_id=updated_by,
                action="ROLE_PERMISSIONS_UPDATED",
                resource_type="role_access",
                resource_id=request.role_name,
                old_value=f"Previous permissions for role: {request.role_name}",
                new_value=f"Updated fields: {', '.join(updated_fields)}",
                ip_address=ip_address,
                user_agent=user_agent
            )

            # Get the updated permissions to return
            permissions_data = await self.role_repo.get_role_permissions(request.department_name, request.role_name)
            if permissions_data:
                permissions_model = RoleAccessModel(
                    department_name=permissions_data['department_name'],
                    role_name=permissions_data['role_name'],
                    read_access=self._json_to_access_permission(permissions_data['read_access']),
                    add_access=self._json_to_access_permission(permissions_data['add_access']),
                    update_access=self._json_to_access_permission(permissions_data['update_access']),
                    delete_access=self._json_to_access_permission(permissions_data['delete_access']),
                    execute_access=self._json_to_access_permission(permissions_data['execute_access']),
                    execution_steps_access=permissions_data.get('execution_steps_access', False),
                    tool_verifier_flag_access=permissions_data.get('tool_verifier_flag_access', False),
                    plan_verifier_flag_access=permissions_data.get('plan_verifier_flag_access', False),
                    online_evaluation_flag_access=permissions_data.get('online_evaluation_flag_access', False),
                    evaluation_access=permissions_data.get('evaluation_access', False),
                    vault_access=permissions_data.get('vault_access', False),
                    data_connector_access=permissions_data.get('data_connector_access', False),
                    knowledgebase_access=permissions_data.get('knowledgebase_access', False),
                    validator_access=permissions_data.get('validator_access', False),
                    file_context_access=permissions_data.get('file_context_access', False),
                    canvas_view_access=permissions_data.get('canvas_view_access', False),
                    context_access=permissions_data.get('context_access', False),
                    created_at=permissions_data['created_at'],
                    updated_at=permissions_data['updated_at'],
                    created_by=permissions_data['created_by']
                )
                return RolePermissionsResponse(
                    success=True, 
                    message=f"Permissions updated successfully for role '{request.role_name}'. Updated: {', '.join(updated_fields)}", 
                    permissions=permissions_model
                )
            else:
                return RolePermissionsResponse(success=True, message=f"Permissions updated successfully for role '{request.role_name}'")

        except Exception as e:
            log.error(f"Update role permissions error: {e}")
            return RolePermissionsResponse(success=False, message="Failed to update permissions due to an error")

    
    # async def check_execution_steps_access(self, user_email: str) -> bool:
    #     """Check if a user has execution steps access based on their role"""
    #     try:
    #         # Get user role
    #         user_data = await self.user_repo.get_user_by_email(user_email)
    #         if not user_data:
    #             return False

    #         user_role = user_data['role']
            
    #         # Get role permissions
    #         permissions_data = await self.role_repo.get_role_permissions(user_role)
    #         if not permissions_data:
    #             return False

    #         # Return execution steps access
    #         return permissions_data.get('execution_steps_access', False)

    #     except Exception as e:
    #         log.error(f"Check execution steps access error: {e}")
    #         return False


class DepartmentService:
    """Service for department management"""

    def __init__(self, department_repo: DepartmentRepository, user_repo: UserRepository, audit_repo: AuditLogRepository,
                 login_pool=None, main_pool=None, recycle_pool=None, logs_pool=None, feedback_learning_pool=None):
        self.department_repo = department_repo
        self.user_repo = user_repo
        self.audit_repo = audit_repo
        # Database pools for cascade delete operations
        self.login_pool = login_pool
        self.main_pool = main_pool
        self.recycle_pool = recycle_pool
        self.logs_pool = logs_pool
        self.feedback_learning_pool = feedback_learning_pool

    async def add_department(self, request: AddDepartmentRequest, created_by: str, 
                           ip_address: str = None, user_agent: str = None) -> DepartmentResponse:
        """Add a new department - only SuperAdmin can add departments"""
        try:
            # Validate creator permissions
            creator_data = await self.user_repo.get_user_by_email(created_by)
            if not creator_data:
                return DepartmentResponse(success=False, message="Creator user not found")
            
            creator_role = creator_data['role']
            if creator_role != 'SuperAdmin':
                return DepartmentResponse(success=False, message="Only SuperAdmin can add departments")

            # Validate department name
            department_name = request.department_name.strip()
            if not department_name:
                return DepartmentResponse(success=False, message="Department name cannot be empty")

            if len(department_name) > 50:
                return DepartmentResponse(success=False, message="Department name cannot exceed 50 characters")

            # Validate that department name starts with capital letter
            if not department_name[0].isupper():
                return DepartmentResponse(success=False, message="Department name must start with a capital letter")

            # Check for valid characters (letters, numbers, spaces, hyphens, underscores)
            import re
            if not re.match(r'^[A-Z][A-Za-z0-9\s\-_]*$', department_name):
                return DepartmentResponse(success=False, message="Department name must start with capital letter and contain only letters, numbers, spaces, hyphens, and underscores")

            # Check if department already exists
            if await self.department_repo.department_exists(department_name.capitalize()):
                return DepartmentResponse(success=False, message=f"Department '{department_name.capitalize()}' already exists")

            # Add department
            success = await self.department_repo.add_department(department_name, created_by)
            
            if success:
                # Log the action
                await self.audit_repo.log_action(
                    user_id=created_by,
                    action="DEPARTMENT_ADDED",
                    resource_type="department",
                    resource_id=department_name.capitalize(),
                    new_value=f"Added department: {department_name.capitalize()}",
                    ip_address=ip_address,
                    user_agent=user_agent
                )
                
                return DepartmentResponse(
                    success=True, 
                    message=f"Department '{department_name.capitalize()}' added successfully",
                    department=DepartmentModel(
                        department_name=success['department_name'],
                        admins=success.get('admins', []),
                        created_at=success['created_at'],
                        created_by=success['created_by']
                    )
                )
            else:
                return DepartmentResponse(success=False, message="Failed to add department")

        except Exception as e:
            log.error(f"Add department error: {e}")
            return DepartmentResponse(success=False, message=f"Internal error: {str(e)}")

    async def get_all_departments(self, requested_by: str) -> DepartmentListResponse:
        """Get all departments - only SuperAdmin can view all departments"""
        try:

            # Get all departments
            departments_data = await self.department_repo.get_all_departments()
            
            departments = [
                DepartmentModel(
                    department_name=dept['department_name'],
                    admins=dept.get('admins', []),
                    created_at=dept['created_at'],
                    created_by=dept['created_by']
                )
                for dept in departments_data
            ]
            
            return DepartmentListResponse(
                success=True,
                message=f"Found {len(departments)} departments",
                departments=departments
            )

        except Exception as e:
            log.error(f"Get all departments error: {e}")
            return DepartmentListResponse(success=False, message=f"Internal error: {str(e)}")

    async def delete_department(self, department_name: str, deleted_by: str, 
                              ip_address: str = None, user_agent: str = None) -> DepartmentResponse:
        """Delete a department with cascade delete - only SuperAdmin can delete departments
        
        This method deletes a department and all related records from:
        LOGIN DB: userdepartmentmapping, role_access, user_access_keys
        MAIN DB: tool_table, mcp_tool_table, agent_table, tool_department_sharing, agent_department_sharing,
                 access_key_definitions, tool_access_key_mapping, groups, group_secrets, pipelines_table,
                 db_connections_table, public_keys, user_secrets, agent_evaluations, user_agent_access
                 + Dynamic tables: table_{agent_id} (chat history tables for each agent)
        RECYCLE DB: recycle_tool, recycle_mcp_tool, recycle_agent
        EVALUATION_LOGS DB: evaluation_data, tool_evaluation_metrics, agent_evaluation_metrics
                 + Dynamic tables: {agent_id} (consistency tables), robustness_{agent_id} (robustness tables)
        FEEDBACK_LEARNING DB: feedback_response
        
        Note: Tables with FK CASCADE (auto-deleted when parent is deleted):
        - tag_agent_mapping_table (FK to agent_table)
        - tool_agent_mapping_table (FK to agent_table)
        - agent_feedback (FK to feedback_response)
        """
        try:
            # Validate deleter permissions
            deleter_data = await self.user_repo.get_user_by_email(deleted_by)
            if not deleter_data:
                return DepartmentResponse(success=False, message="Deleter user not found")
            
            deleter_role = deleter_data['role']
            if deleter_role != 'SuperAdmin':
                return DepartmentResponse(success=False, message="Only SuperAdmin can delete departments")

            # Don't allow deleting the default "General" department
            if department_name.lower() == 'general':
                return DepartmentResponse(success=False, message="Cannot delete the default 'General' department")

            # Check if department exists
            if not await self.department_repo.department_exists(department_name):
                return DepartmentResponse(success=False, message=f"Department '{department_name}' not found")

            # Cascade delete all related data using repository method
            deletion_stats = await self.department_repo.cascade_delete_department_data(
                department_name=department_name,
                main_pool=self.main_pool,
                recycle_pool=self.recycle_pool,
                logs_pool=self.logs_pool,
                feedback_learning_pool=self.feedback_learning_pool
            )
            
            # Finally delete the department itself
            success = await self.department_repo.delete_department(department_name)
            
            if success:
                # Log the action with deletion stats
                await self.audit_repo.log_action(
                    user_id=deleted_by,
                    action="DEPARTMENT_DELETED",
                    resource_type="department",
                    resource_id=department_name,
                    old_value=f"Deleted department: {department_name} with cascade. Stats: {deletion_stats}",
                    ip_address=ip_address,
                    user_agent=user_agent
                )
                
                log.info(f"Department '{department_name}' deleted with cascade. Deletion stats: {deletion_stats}")
                return DepartmentResponse(success=True, message=f"Department '{department_name}' deleted successfully with all related records")
            else:
                return DepartmentResponse(success=False, message="Failed to delete department")

        except Exception as e:
            log.error(f"Delete department error: {e}")
            return DepartmentResponse(success=False, message=f"Internal error: {str(e)}")

    async def get_department_by_name(self, department_name: str, requested_by: str) -> DepartmentResponse:
        """Get a specific department by name - only SuperAdmin can view departments"""
        try:
            # Validate requester permissions
            requester_data = await self.user_repo.get_user_by_email(requested_by)
            if not requester_data:
                return DepartmentResponse(success=False, message="Requester user not found")
            
            requester_role = requester_data['role']
            if requester_role != 'SuperAdmin':
                return DepartmentResponse(success=False, message="Only SuperAdmin can view departments")

            # Get department
            department_data = await self.department_repo.get_department_by_name(department_name)
            
            if department_data:
                department = DepartmentModel(
                    department_name=department_data['department_name'],
                    admins=department_data.get('admins', []),
                    created_at=department_data['created_at'],
                    created_by=department_data['created_by']
                )
                
                return DepartmentResponse(
                    success=True,
                    message=f"Department '{department_name}' found",
                    department=department
                )
            else:
                return DepartmentResponse(success=False, message=f"Department '{department_name}' not found")

        except Exception as e:
            log.error(f"Get department by name error: {e}")
            return DepartmentResponse(success=False, message=f"Internal error: {str(e)}")

    async def add_role_to_department(self, department_name: str, role_name: str, added_by: str, 
                                   ip_address: str = None, user_agent: str = None, user_department_name: str = None) -> DepartmentRoleResponse:
        """Add a role to department's allowed roles list"""
        try:
            # Validate permissions
            user_data = await self.user_repo.get_user_by_email(added_by, department_name=user_department_name)
            if not user_data:
                return DepartmentRoleResponse(success=False, message="User not found")
            
            user_role = user_data['role']
            if user_role not in ['Admin', 'SuperAdmin']:
                return DepartmentRoleResponse(success=False, message="Only Admin and SuperAdmin can manage department roles")
            
            # Admin can only manage their own department
            if user_role == 'Admin':
                user_department = user_data.get('department_name') 
                if user_department != department_name:
                    return DepartmentRoleResponse(
                        success=False, 
                        message=f"Admin users can only manage roles for their own department ('{user_department}'). Cannot manage department '{department_name}'."
                    )

            # Validate role name
            role_name = role_name.strip()
            if not role_name:
                return DepartmentRoleResponse(success=False, message="Role name cannot be empty")

            # Add role to department
            result = await self.department_repo.add_role_to_department(department_name, role_name, added_by)
            
            if result["success"]:
                # Log the action
                await self.audit_repo.log_action(
                    user_id=added_by,
                    action="DEPARTMENT_ROLE_ADDED",
                    resource_type="department",
                    resource_id=department_name,
                    new_value=f"Added role '{role_name}' to department '{department_name}'",
                    ip_address=ip_address,
                    user_agent=user_agent
                )
                
                # Get updated roles for response
                roles_result = await self.department_repo.get_department_roles(department_name)
                roles = roles_result["roles"] if roles_result and roles_result["success"] else []
                
                return DepartmentRoleResponse(
                    success=True, 
                    message=result["message"],
                    roles=roles
                )
            else:
                return DepartmentRoleResponse(success=False, message=result["message"])

        except Exception as e:
            log.error(f"Add role to department error: {e}")
            return DepartmentRoleResponse(success=False, message=f"Internal error: {str(e)}")

    async def remove_role_from_department(self, department_name: str, role_name: str, removed_by: str, 
                                        ip_address: str = None, user_agent: str = None, user_department_name: str = None) -> DepartmentRoleResponse:
        """Remove a role from department's allowed roles list"""
        try:
            # Validate permissions
            user_data = await self.user_repo.get_user_by_email(removed_by, department_name=user_department_name)
            if not user_data:
                return DepartmentRoleResponse(success=False, message="User not found")
            
            user_role = user_data['role']
            if user_role not in ['Admin', 'SuperAdmin']:
                return DepartmentRoleResponse(success=False, message="Only Admin and SuperAdmin can manage department roles")
            
            # Admin can only manage their own department
            if user_role == 'Admin':
                user_department = user_data.get('department_name') 
                if user_department != department_name:
                    return DepartmentRoleResponse(
                        success=False, 
                        message=f"Admin users can only manage roles for their own department ('{user_department}'). Cannot manage department '{department_name}'."
                    )

            # Remove role from department
            result = await self.department_repo.remove_role_from_department(department_name, role_name)
            
            if result["success"]:
                # Log the action
                await self.audit_repo.log_action(
                    user_id=removed_by,
                    action="DEPARTMENT_ROLE_REMOVED",
                    resource_type="department",
                    resource_id=department_name,
                    old_value=f"Removed role '{role_name}' from department '{department_name}'",
                    ip_address=ip_address,
                    user_agent=user_agent
                )
                
                # Get updated roles for response
                roles_result = await self.department_repo.get_department_roles(department_name)
                roles = roles_result["roles"] if roles_result and roles_result["success"] else []
                
                return DepartmentRoleResponse(
                    success=True, 
                    message=result["message"],
                    roles=roles
                )
            else:
                return DepartmentRoleResponse(success=False, message=result["message"])

        except Exception as e:
            log.error(f"Remove role from department error: {e}")
            return DepartmentRoleResponse(success=False, message=f"Internal error: {str(e)}")

    async def get_department_roles(self, department_name: str, requested_by: str, user_department_name: str = None) -> DepartmentRoleResponse:
        """Get all allowed roles for a department - only SuperAdmin can view department roles"""
        try:
            # Try to get user data in the context of their department first
            user_data = await self.user_repo.get_user_by_email(requested_by, department_name=user_department_name)
            
            if not user_data:
                return DepartmentRoleResponse(success=False, message="User not found")
            
            user_role = user_data['role']
            if user_role not in ['Admin', 'SuperAdmin']:
                return DepartmentRoleResponse(success=False, message="Only Admin and SuperAdmin can view department roles")
            
            # Admin can only view their own department
            if user_role == 'Admin':
                user_department = user_data.get('department_name') 
                if user_department != department_name:
                    return DepartmentRoleResponse(
                        success=False, 
                        message=f"Admin users can only view roles for their own department ('{user_department}'). Cannot view department '{department_name}'."
                    )

            # Check if department exists
            if not await self.department_repo.department_exists(department_name):
                return DepartmentRoleResponse(success=False, message=f"Department '{department_name}' not found")

            # Get department roles
            roles_result = await self.department_repo.get_department_roles(department_name)
            
            if roles_result["success"]:
                return DepartmentRoleResponse(
                    success=True,
                    message=f"Retrieved roles for department '{department_name}'",
                    roles=roles_result["roles"]
                )
            else:
                return DepartmentRoleResponse(success=False, message=roles_result["message"])

        except Exception as e:
            log.error(f"Get department roles error: {e}")
            return DepartmentRoleResponse(success=False, message=f"Internal error: {str(e)}")
