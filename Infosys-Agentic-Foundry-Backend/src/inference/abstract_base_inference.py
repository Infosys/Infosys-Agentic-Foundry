# © 2024-25 Infosys Limited, Bangalore, India. All Rights Reserved.
import re
import os
from dotenv import load_dotenv
import json
from abc import ABC, abstractmethod
from typing import Any, List, Dict, Optional, Union, Callable
from fastapi import HTTPException

from src.database.services import ChatService
from src.inference.inference_utils import InferenceUtils
from src.schemas import AgentInferenceRequest
from src.utils.secrets_handler import get_user_secrets, current_user_email, get_public_key, get_group_secrets

from telemetry_wrapper import logger as log

from src.storage import get_storage_client

load_dotenv()








class AbstractBaseInference(ABC):
    """
    Abstract base class for Agent Inference implementations.
    Defines common methods and properties for agent inference workflows.
    """

    def __init__(self, inference_utils: InferenceUtils):
        self.inference_utils = inference_utils
        self.chat_service = inference_utils.chat_service
        self.tool_service = inference_utils.tool_service
        self.mcp_tool_service = self.tool_service.mcp_tool_service
        self.agent_service = inference_utils.agent_service
        self.model_service = inference_utils.model_service
        self.feedback_learning_service = inference_utils.feedback_learning_service
        self.evaluation_service = inference_utils.evaluation_service
        self.storage_provider=os.getenv('STORAGE_PROVIDER', "")
        self.storage_client = None
        self.admin_config_service = self.chat_service.admin_config_service


    # --- Helper Methods ---

    def _initialize_storage_client(self):
        if self.storage_provider and self.storage_provider.strip():
            try:
                self.storage_client = get_storage_client(self.storage_provider)
            except ValueError as e:
                log.info(f"Warning: Storage client initialization failed: {e}")
            except Exception as e:
                log.info(f"Warning: Storage configuration error: {e}")

    @staticmethod
    def _extract_user_email_from_session_id(session_id: str) -> str:
        """
        Extracts the user email from the session ID using regex.
        """
        return ChatService._extract_user_email_from_session_id(session_id)

    @abstractmethod
    async def _get_mcp_tools_instances(self, tool_ids: List[str] = []) -> list:
        """
        Abstract method to retrieve MCP tool instances based on the provided tool IDs.
        Args:
            tool_ids (List[str], optional): List of tool IDs. Defaults to [].
        """
        mcp_server_records: List[dict] = []
        for tool_id in tool_ids:
            if not tool_id.startswith("mcp_"):
                continue

            try:
                log.info(f"Loading MCP tool for ID: {tool_id}")
                tool_record = await self.mcp_tool_service.mcp_tool_repo.get_mcp_tool_record(tool_id=tool_id)
                if not tool_record:
                    log.warning(f"MCP tool record for ID {tool_id} not found.")
                    raise HTTPException(status_code=404, detail=f"MCP tool record for ID {tool_id} not found.")

                tool_record = tool_record[0]
                mcp_config = tool_record["mcp_config"]
                tool_record["mcp_config"] = json.loads(mcp_config) if isinstance(mcp_config, str) else mcp_config
                mcp_server_records.append(tool_record)
                log.info(f"Fetched MCP tool record for ID: {tool_id}")

            except HTTPException:
                raise # Re-raise HTTPExceptions directly

            except Exception as e:
                log.error(f"Error occurred while loading MCP tool {tool_id}: {e}")
                raise HTTPException(status_code=500, detail=f"Error occurred while loading MCP tool {tool_id}: {e}")

        return mcp_server_records

    async def _get_memory_management_tools_instances(self, *, allow_union_annotation: bool = True) -> list:
        """
        Retrieves memory tool instances.
        """
        manage_memory_tool = await self.inference_utils.create_manage_memory_tool()
        if not allow_union_annotation:
            manage_memory_tool.__annotations__["memory_data"] = str
        search_memory_tool = await self.inference_utils.create_search_memory_tool(
            embedding_model=self.inference_utils.embedding_model
        )
        return [manage_memory_tool, search_memory_tool]

    async def _get_tools_instances(self, tool_ids: List[str] = []) -> list:
        """
        Retrieves tool instances based on the provided tool IDs.
        """
        # local_var for exec() context, including secrets handlers
        local_var = {
            "get_user_secrets": get_user_secrets,
            "current_user_email": current_user_email,
            "get_public_secrets": get_public_key,
            "get_group_secrets": get_group_secrets
        }
        # if self.storage_provider:
        #     self._initialize_storage_client()
        # if self.storage_client is not None and hasattr(self.storage_client, 'open'):
        #     log.info('Storage client initialized in agent execution environment.')
        #     local_var["open"] = self.storage_client.open
        # else:
        #     local_var["open"] = open  # Use Python's built-in open as fallback


        tool_list: List[Callable] = []
        mcp_server_ids: List[str] = []

        for tool_id in tool_ids:
            try:
                if tool_id.startswith("mcp_"):
                    mcp_server_ids.append(tool_id)
                    continue

                log.info(f"Loading Python tool for ID: {tool_id} - CACHE LOG")
                tool_record = await self.tool_service.tool_repo.get_tool_record(tool_id=tool_id, message_queue_implementation=False)
                log.info(f"Python tool reading completed for ID: {tool_id} - CACHE LOG")
                if tool_record:
                    tool_record = tool_record[0]
                    codes = tool_record["code_snippet"]
                    tool_name = tool_record["tool_name"]
                    exec(codes, local_var)
                    tool_list.append(local_var[tool_name])
                else:
                    log.warning(f"Python tool record for ID {tool_id} not found.")
                    raise HTTPException(status_code=404, detail=f"Python tool record for ID {tool_id} not found.")

            except HTTPException:
                raise # Re-raise HTTPExceptions directly

            except Exception as e:
                log.error(f"Error occurred while loading tool {tool_id}: {e}")
                raise HTTPException(status_code=500, detail=f"Error occurred while loading tool {tool_id}: {e}")
            
        mcp_tools = await self._get_mcp_tools_instances(tool_ids=mcp_server_ids)
        tool_list.extend(mcp_tools)

        return tool_list

    async def _get_agent_config(self, agentic_application_id: str) -> dict:
        """
        Retrieves the configuration for an agent and its associated tools.

        Args:
            agentic_application_id (str, optional): Agentic application ID.

        Returns:
            dict: A dictionary containing the system prompt and tool information.
        """
        # Retrieve agent details from the database
        log.info("Retrieving agent details - CACHE LOG")
        result = await self.agent_service.agent_repo.get_agent_record(agentic_application_id=agentic_application_id)
        log.info("Retrieved agent details successfully - CACHE LOG")
        if not result:
            log.error(f"Agentic Application ID {agentic_application_id} not found.")
            raise HTTPException(status_code=404, detail=f"Agentic Application ID {agentic_application_id} not found.")
        result: dict = result[0]

        validation_criteria = result.get("validation_criteria", [])
        if isinstance(validation_criteria, str):
            try:
                validation_criteria = json.loads(validation_criteria)
            except Exception as e:
                log.error(f"Error parsing validation criteria for Agentic Application ID {agentic_application_id}: {e}")
                validation_criteria = []

        agent_config = {
            "AGENT_NAME": result["agentic_application_name"],
            "SYSTEM_PROMPT": json.loads(result["system_prompt"]),
            "TOOLS_INFO": json.loads(result["tools_id"]),
            "AGENT_DESCRIPTION": result["agentic_application_description"],
            "WORKFLOW_DESCRIPTION": result["agentic_application_workflow_description"],
            "AGENT_TYPE": result['agentic_application_type'],
            "VALIDATION_CRITERIA": validation_criteria
        }
        log.info(f"Agent tools configuration retrieved for Agentic Application ID: {agentic_application_id}")
        return agent_config

    async def _get_validator_tool_instance(self, validator_tool_id: str) -> Optional[Callable]:
        """
        Retrieves and returns an executable validator function from the given validator tool ID.
        
        Args:
            validator_tool_id (str): The ID of the validator tool (e.g., "_validator_85b6330e-...")
            
        Returns:
            Optional[Callable]: The executable validator function if found, None otherwise.
            The function will have signature: func(query: str, response: str) -> dict
        """
        if not validator_tool_id:
            return None
            
        try:
            log.info(f"Loading validator tool for ID: {validator_tool_id}")
            
            # local_var for exec() context, including secrets handlers
            local_var = {
                "get_user_secrets": get_user_secrets,
                "current_user_email": current_user_email,
                "get_public_secrets": get_public_key
            }
            
            # Get validator tool record from tool service
            validator_tools = await self.tool_service.tool_repo.get_tool_record(tool_id=validator_tool_id)
            if not validator_tools:
                log.warning(f"Validator tool {validator_tool_id} not found")
                return None
            
            validator_tool = validator_tools[0]
            tool_name = validator_tool["tool_name"]
            tool_code = validator_tool["code_snippet"]

            if not tool_code:
                log.warning(f"Validator tool {validator_tool_id} has no code snippet")
                return None
            
            # Execute the tool code to define the function
            exec(tool_code, {"__builtins__": __builtins__, **local_var}, local_var)
            
            # Find the validator function (should have _validator in the name or be the only function)
            validator_function = local_var.get(tool_name)

            if validator_function:
                log.info(f"Successfully loaded validator function from tool: {validator_tool_id}")
            else:
                log.warning(f"No callable function found in validator tool {validator_tool_id}")

            return validator_function

        except Exception as e:
            log.error(f"Error loading validator tool {validator_tool_id}: {e}")
            return None

    async def _prepare_validation_criteria_with_tools(self, validation_criteria: List[dict]) -> List[dict]:
        """
        Processes validation criteria and replaces validator tool IDs with executable functions.
        
        Args:
            validation_criteria: List of validation criteria dictionaries containing:
                - query: The query pattern to match
                - validator: Tool ID (e.g., "_validator_xxx") or None
                - expected_answer: Expected behavior description
                
        Returns:
            List of validation criteria with validator tool IDs replaced by executable functions.
        """
        if not validation_criteria:
            return []
            
        processed_criteria = []
        
        for criteria in validation_criteria:
            processed_item = criteria.copy()
            validator_id = criteria.get("validator")
            
            if validator_id:
                # Load the validator tool and replace the ID with the function
                validator_func = await self._get_validator_tool_instance(validator_id)
                if validator_func:
                    processed_item["validator_function"] = validator_func
                    log.info(f"Loaded validator function for criteria: {criteria.get('query', 'Unknown')[:50]}...")
                else:
                    log.warning(f"Could not load validator function for ID: {validator_id}")
                    processed_item["validator_function"] = None
            else:
                processed_item["validator_function"] = None
                
            processed_criteria.append(processed_item)
            
        log.info(f"Processed {len(processed_criteria)} validation criteria, "
                 f"{sum(1 for c in processed_criteria if c.get('validator_function'))} with tool validators")
        return processed_criteria

    # Abstract Methods

    @abstractmethod
    async def run(self,
                  inference_request: AgentInferenceRequest,
                  *,
                  agent_config: Optional[Union[dict, None]] = None,
                  **kwargs
                ) -> Any:
        """
        Abstract method to run the agent inference process.
        Args:
            inference_request (AgentInferenceRequest): The agent inference request object.
            agent_config (Optional[Union[dict, None]], optional): Pre-fetched agent configuration. Defaults to None.
            **kwargs: Additional keyword arguments.
        """
        pass


