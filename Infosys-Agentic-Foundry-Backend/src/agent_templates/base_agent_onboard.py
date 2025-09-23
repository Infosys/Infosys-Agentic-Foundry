# © 2024-25 Infosys Limited, Bangalore, India. All Rights Reserved.
from abc import ABC, abstractmethod
from typing import List, Dict, Any, Optional, Union

from src.database.services import AgentServiceUtils, AgentService


# Normal Type Agent's Base Template Class

class BaseAgentOnboard(AgentService, ABC):
    """
    BaseAgentTemplate provides a foundational template for agent services, enforcing a standard interface and shared logic for onboarding and updating agents.
    Args:
        agent_type (str): The type of agent being instantiated. Must be provided.
        agent_service_utils (AgentServiceUtils): Utility class for agent service operations.
    Raises:
        ValueError: If agent_type is not provided.
    Methods:
        _generate_system_prompt(agent_name, agent_goal, workflow_description, tool_or_worker_agents_prompt, llm):
            Abstract method to generate a system prompt for the agent. Must be implemented by subclasses.
        onboard_agent(agent_name, agent_goal, workflow_description, model_name, tools_id, user_id, tag_ids=None):
            Asynchronously onboard a new agent with the provided details.
        update_agent(agentic_application_id=None, agentic_application_name=None, agentic_application_description="", agentic_application_workflow_description="", model_name=None, created_by=None, system_prompt={}, is_admin=False, tools_id=[], tools_id_to_add=[], tools_id_to_remove=[], updated_tag_id_list=None):
            Asynchronously update an existing agent's details.
    """

    def __init__(self, agent_type: str, agent_service_utils: AgentServiceUtils):
        if not agent_type:
            raise ValueError("Agent type must be provided.")

        super().__init__(agent_service_utils=agent_service_utils)

        if agent_type in self.meta_type_templates:
            raise ValueError(f"Agent type '{agent_type}' is reserved for meta-type agents and cannot be used here.")
        self.agent_type = agent_type


    @abstractmethod
    async def _generate_system_prompt(self, agent_name: str, agent_goal: str,
                                      workflow_description: str,
                                      tool_or_worker_agents_prompt: str, llm) -> Dict[str, str]:
        pass

    async def onboard_agent(self,
                            agent_name: str,
                            agent_goal: str,
                            workflow_description: str,
                            model_name: str,
                            tools_id: List[str],
                            user_id: str,
                            tag_ids: Optional[Union[str, List[str]]] = None) -> Dict[str, Any]:
        return await self._onboard_agent(
            agent_name=agent_name,
            agent_goal=agent_goal,
            workflow_description=workflow_description,
            agent_type=self.agent_type,
            model_name=model_name,
            associated_ids=tools_id,
            user_id=user_id,
            tag_ids=tag_ids
        )

    async def update_agent(self,
                           agentic_application_id: Optional[str] = None,
                           agentic_application_name: Optional[str] = None,
                           agentic_application_description: str = "",
                           agentic_application_workflow_description: str = "",
                           model_name: Optional[str] = None,
                           created_by: Optional[str] = None,
                           system_prompt: Dict[str, Any] = {},
                           is_admin: bool = False,
                           tools_id: List[str] = [],
                           tools_id_to_add: List[str] = [],
                           tools_id_to_remove: List[str] = [],
                           updated_tag_id_list: Optional[Union[str, List[str]]] = None) -> Dict[str, Any]:
        return await self._update_agent(
            agentic_application_id=agentic_application_id,
            agentic_application_name=agentic_application_name,
            agentic_application_description=agentic_application_description,
            agentic_application_workflow_description=agentic_application_workflow_description,
            model_name=model_name,
            created_by=created_by,
            system_prompt=system_prompt,
            is_admin=is_admin,
            associated_ids=tools_id,
            associated_ids_to_add=tools_id_to_add,
            associated_ids_to_remove=tools_id_to_remove,
            updated_tag_id_list=updated_tag_id_list
        )


# Meta Type Agent's Base Template Class

class BaseMetaTypeAgentOnboard(AgentService, ABC):
    """
    BaseMetaTypeAgentOnboard provides a foundational template for agent services, enforcing a standard interface and shared logic for onboarding and updating agents.
    Args:
        agent_type (str): The type of agent being instantiated. Must be provided.
        agent_service_utils (AgentServiceUtils): Utility class for agent service operations.
    Raises:
        ValueError: If agent_type is not provided.
    Methods:
        _generate_system_prompt(agent_name, agent_goal, workflow_description, tool_or_worker_agents_prompt, llm):
            Abstract method to generate a system prompt for the agent. Must be implemented by subclasses.
        onboard_agent(agent_name, agent_goal, workflow_description, model_name, worker_agents_id, user_id, tag_ids=None):
            Asynchronously onboard a new agent with the provided details.
        update_agent(agentic_application_id=None, agentic_application_name=None, agentic_application_description="", agentic_application_workflow_description="", model_name=None, created_by=None, system_prompt={}, is_admin=False, worker_agents_id=[], worker_agents_id_to_add=[], worker_agents_id_to_remove=[], updated_tag_id_list=None):
            Asynchronously update an existing agent's details.
    """

    def __init__(self, agent_type: str, agent_service_utils: AgentServiceUtils):
        if not agent_type:
            raise ValueError("Agent type must be provided.")

        super().__init__(agent_service_utils=agent_service_utils)

        if not agent_type in self.meta_type_templates:
            raise ValueError(f"Agent type '{agent_type}' is not a meta-type agent and cannot be used here.")
        self.agent_type = agent_type


    @abstractmethod
    async def _generate_system_prompt(self, agent_name: str, agent_goal: str,
                                      workflow_description: str,
                                      tool_or_worker_agents_prompt: str, llm) -> Dict[str, str]:
        pass

    async def onboard_agent(self,
                            agent_name: str,
                            agent_goal: str,
                            workflow_description: str,
                            model_name: str,
                            worker_agents_id: List[str],
                            user_id: str,
                            tag_ids: Optional[Union[str, List[str]]] = None) -> Dict[str, Any]:
        return await self._onboard_agent(
            agent_name=agent_name,
            agent_goal=agent_goal,
            workflow_description=workflow_description,
            agent_type=self.agent_type,
            model_name=model_name,
            associated_ids=worker_agents_id,
            user_id=user_id,
            tag_ids=tag_ids
        )

    async def update_agent(self,
                           agentic_application_id: Optional[str] = None,
                           agentic_application_name: Optional[str] = None,
                           agentic_application_description: str = "",
                           agentic_application_workflow_description: str = "",
                           model_name: Optional[str] = None,
                           created_by: Optional[str] = None,
                           system_prompt: Dict[str, Any] = {},
                           is_admin: bool = False,
                           worker_agents_id: List[str] = [],
                           worker_agents_id_to_add: List[str] = [],
                           worker_agents_id_to_remove: List[str] = [],
                           updated_tag_id_list: Optional[Union[str, List[str]]] = None) -> Dict[str, Any]:
        return await self._update_agent(
            agentic_application_id=agentic_application_id,
            agentic_application_name=agentic_application_name,
            agentic_application_description=agentic_application_description,
            agentic_application_workflow_description=agentic_application_workflow_description,
            model_name=model_name,
            created_by=created_by,
            system_prompt=system_prompt,
            is_admin=is_admin,
            associated_ids=worker_agents_id,
            associated_ids_to_add=worker_agents_id_to_add,
            associated_ids_to_remove=worker_agents_id_to_remove,
            updated_tag_id_list=updated_tag_id_list
        )


