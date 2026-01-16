# © 2024-25 Infosys Limited, Bangalore, India. All Rights Reserved.
from typing import Any, Dict

from src.models.base_ai_model_service import BaseAIModelService
from src.inference.inference_utils import InferenceUtils
from src.inference.python_based_inference.base_python_based_agent_inference import BasePythonBasedAgentInference

from telemetry_wrapper import logger as log


class SimpleAIAgentInference(BasePythonBasedAgentInference):
    """
    A simple AI agent inference class that utilizes various services to process user queries.
    It inherits common Python-based agent logic from BasePythonBasedAgentInference.
    """

    def __init__(self, inference_utils: InferenceUtils):
        super().__init__(inference_utils=inference_utils)


    async def _build_agent_and_chains(self, llm: BaseAIModelService, agent_config: Dict) -> Dict[str, Any]:
        """
        Builds the agent and chains for the Simple AI Agent.
        """
        tool_ids = agent_config["TOOLS_INFO"]
        system_prompt = agent_config["SYSTEM_PROMPT"]
        
        # Use the common helper to get the agent instance
        simple_ai_agent, _ = await self._get_python_based_agent_instance(
                                        llm,
                                        system_prompt=system_prompt.get("SYSTEM_PROMPT_SIMPLE_AI_AGENT", ""),
                                        tool_ids=tool_ids
                                    )
        chains = {
            "llm": llm,
            "simple_ai_agent": simple_ai_agent,
            "agent": simple_ai_agent # Use generic name 'agent'
        }
        log.info("Built Simple AI Agent successfully")
        return chains


