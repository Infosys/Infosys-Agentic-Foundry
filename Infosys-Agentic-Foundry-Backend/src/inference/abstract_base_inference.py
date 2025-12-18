# © 2024-25 Infosys Limited, Bangalore, India. All Rights Reserved.
import re
import json
from abc import ABC, abstractmethod
from typing import Any, List, Dict, Optional, Union, Callable
from fastapi import HTTPException

from src.database.services import ChatService
from src.inference.inference_utils import InferenceUtils
from src.schemas import AgentInferenceRequest
from src.utils.secrets_handler import get_user_secrets, current_user_email, get_public_key

from telemetry_wrapper import logger as log



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


    # --- Helper Methods ---

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

    async def _get_tools_instances(self, tool_ids: List[str] = []) -> list:
        """
        Retrieves tool instances based on the provided tool IDs.
        """
        # local_var for exec() context, including secrets handlers
        local_var = {
            "get_user_secrets": get_user_secrets,
            "current_user_email": current_user_email,
            "get_public_secrets": get_public_key
        }

        tool_list: List[Callable] = []
        mcp_server_ids: List[str] = []

        for tool_id in tool_ids:
            try:
                if tool_id.startswith("mcp_"):
                    mcp_server_ids.append(tool_id)
                    continue

                log.info(f"Loading Python tool for ID: {tool_id} - CACHE LOG")
                tool_record = await self.tool_service.tool_repo.get_tool_record(tool_id=tool_id)
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
        result = result[0]

        agent_config = {
            "AGENT_NAME": result["agentic_application_name"],
            "SYSTEM_PROMPT": json.loads(result["system_prompt"]),
            "TOOLS_INFO": json.loads(result["tools_id"]),
            "AGENT_DESCRIPTION": result["agentic_application_description"],
            "WORKFLOW_DESCRIPTION": result["agentic_application_workflow_description"],
            "AGENT_TYPE": result['agentic_application_type']
        }
        log.info(f"Agent tools configuration retrieved for Agentic Application ID: {agentic_application_id}")
        return agent_config

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


