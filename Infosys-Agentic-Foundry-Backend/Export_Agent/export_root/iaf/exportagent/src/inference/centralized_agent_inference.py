
from typing import Optional, Dict, Union, Any, TYPE_CHECKING
from exportagent.src.inference.base_agent_inference import BaseAgentInference
from exportagent.src.schemas import AgentInferenceRequest
from exportagent.src.utils.stream_sse import SSEManager
if TYPE_CHECKING:
    from exportagent.src.inference.react_agent_inference import ReactAgentInference
    from exportagent.src.inference.planner_executor_critic_agent_inference import MultiAgentInference # Assuming this is MultiAgent
    from exportagent.src.inference.planner_executor_agent_inference import PlannerExecutorAgentInference
    from exportagent.src.inference.react_critic_agent_inference import ReactCriticAgentInference
    from exportagent.src.inference.meta_agent_inference import MetaAgentInference
    from exportagent.src.inference.planner_meta_agent_inference import PlannerMetaAgentInference


class CentralizedAgentInference:
    """
    Centralized service to handle inference requests for different agent types.
    It delegates requests to the appropriate specialized agent inference instance
    provided during its initialization.
    """

    # Stores the instantiated agent inference handlers
    _agent_handlers: Dict[str, BaseAgentInference]
    _config_fetcher: Optional[BaseAgentInference] # The agent instance used to fetch config

    def __init__(self, agent_handlers: Dict[str, BaseAgentInference]):
        """
        Initializes the CentralizedAgentInference with a dictionary of agent handlers.

        Args:
            agent_handlers: A dictionary where keys are agent type strings
                            (e.g., "react_agent", "meta_agent") and values are
                            instantiated objects of their respective inference classes,
                            all inheriting from BaseAgentInference.
                            Example: {"react_agent": ReactAgentInference(...),
                                      "meta_agent": MetaAgentInference(...)}
        """
        if not isinstance(agent_handlers, dict):
            raise TypeError("agent_handlers must be a dictionary mapping agent types to instances.")

        # Store the provided handlers
        self._agent_handlers = agent_handlers
        self._config_fetcher = self._agent_handlers.get("react_agent")
        if self._config_fetcher is None:
            for handler_key, handler_instance in self._agent_handlers.items():
                if hasattr(handler_instance, "_get_agent_config"):
                    self._config_fetcher = handler_instance
                    break
            if self._config_fetcher is None:
                raise ValueError("No agent handler with a '_get_agent_config' method was provided. Cannot fetch agent configurations.")


    async def get_specialized_agent_inference(self, agent_type: str) -> BaseAgentInference:
        """
        Returns the appropriate specialized service instance based on the agent type.

        Raises:
            ValueError: If the agent_type is not recognized or its handler
                        was not provided during initialization.
        """
        handler = self._agent_handlers.get(agent_type)
        if handler is None:
            raise ValueError(
                f"Agent type '{agent_type}' is not supported by this CentralizedAgentInference instance. "
                f"Supported types: {list(self._agent_handlers.keys())}"
            )
        return handler

    async def run(self,
            inference_request: AgentInferenceRequest,
            *,
            insert_into_eval_flag: bool = True,
            sse_manager: SSEManager = None
        ):
        """
        Run the inference request using the appropriate agent inference service based on the agent type.
        """
        # agent_config = await self.react_agent_inference._get_agent_config(inference_request.agentic_application_id)
        # agent_inference: BaseAgentInference = await self.get_specialized_agent_inference(agent_type=agent_config["AGENT_TYPE"])
        if not hasattr(self._config_fetcher, "_get_agent_config"):
            raise RuntimeError(f"Config fetcher instance ({type(self._config_fetcher).__name__}) "
                               "does not implement the '_get_agent_config' method.")
        agent_config = await self._config_fetcher._get_agent_config(inference_request.agentic_application_id)

        if not agent_config or "AGENT_TYPE" not in agent_config:
            raise ValueError(
                f"Agent configuration for ID '{inference_request.agentic_application_id}' "
                "is invalid or missing 'AGENT_TYPE'."
            )
        agent_inference_handler: BaseAgentInference = await self.get_specialized_agent_inference(
            agent_type=agent_config["AGENT_TYPE"]
        )
        return await agent_inference_handler.run(
            inference_request=inference_request,
            agent_config=agent_config,
            insert_into_eval_flag=insert_into_eval_flag,
            sse_manager=sse_manager
        )
