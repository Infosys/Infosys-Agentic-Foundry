# © 2024-25 Infosys Limited, Bangalore, India. All Rights Reserved.
from typing import List, Optional
from fastapi import HTTPException

from google.genai import types
from google.adk.models.lite_llm import LiteLlm
from google.adk.agents.callback_context import CallbackContext
from google.adk.tools.agent_tool import AgentTool

from src.inference.inference_utils import InferenceUtils
from src.inference.google_adk_inference.base_agent_gadk_inference import BaseAgentGADKInference
from src.inference.google_adk_inference.react_agent_gadk_inference import ReactAgentGADKInference
from src.inference.google_adk_inference.planner_executor_critic_agent_gadk_inference import PlannerExecutorCriticAgentGADKInference
from src.inference.google_adk_inference.planner_executor_agent_gadk_inference import PlannerExecutorAgentGADKInference
from src.inference.google_adk_inference.react_critic_agent_gadk_inference import ReactCriticAgentGADKInference
from src.config.constants import AgentType

from telemetry_wrapper import logger as log


class BaseMetaTypeAgentGADKInference(BaseAgentGADKInference):
    """
    Meta Inference class to handle different agent types using Google ADK.
    """

    def __init__(self, inference_utils: InferenceUtils):
        super().__init__(inference_utils)
        self.react_agent_inference = ReactAgentGADKInference(inference_utils)
        self.planner_executor_critic_agent_inference = PlannerExecutorCriticAgentGADKInference(inference_utils)
        self.planner_executor_agent_inference = PlannerExecutorAgentGADKInference(inference_utils)
        self.react_critic_agent_inference = ReactCriticAgentGADKInference(inference_utils)


    async def _get_agents_as_tool_list(self, llm: LiteLlm, worker_agent_ids: List[str]) -> List[AgentTool]:
        """
        Retrieves agent instances as a list of AgentTool objects based on the provided agent IDs.
        Args:
            worker_agent_ids (List[str]): List of agent IDs.
        """

        worker_agents_as_tools: List[AgentTool] = []

        for worker_agent_id in worker_agent_ids:
            worker_agent_config = await self._get_agent_config(agentic_application_id=worker_agent_id)

            worker_agent_type = worker_agent_config["AGENT_TYPE"]
            worker_agent_description = worker_agent_config.get("AGENT_DESCRIPTION")
            worker_agent_system_prompt = worker_agent_config.get("SYSTEM_PROMPT")
            worker_agent_tool_ids = worker_agent_config.get("TOOLS_INFO")
            worker_agent_name = worker_agent_config.get("AGENT_NAME")
            worker_agent_name = await self.agent_service.agent_service_utils._normalize_agent_name(worker_agent_name)

            agent_service = None
            if worker_agent_type == AgentType.REACT_AGENT:
                agent_service = self.react_agent_inference
            elif worker_agent_type == AgentType.PLANNER_EXECUTOR_CRITIC_AGENT:
                agent_service = self.planner_executor_critic_agent_inference
            elif worker_agent_type == AgentType.PLANNER_EXECUTOR_AGENT:
                agent_service = self.planner_executor_agent_inference
            elif worker_agent_type == AgentType.REACT_CRITIC_AGENT:
                agent_service = self.react_critic_agent_inference
            else:
                err = f"Google ADK meta agent workflow does not support worker agent of type '{worker_agent_type}' yet."
                log.error(err)
                raise HTTPException(status_code=501, detail=err)
            
            log.info(f"Building worker agent of type '{worker_agent_type}' with ID: {worker_agent_id}, and name: {worker_agent_name}")
            
            chains = await agent_service._build_agent_and_chains(
                            llm=llm,
                            agent_config=worker_agent_config,
                            tool_interrupt_flag=False
                        )
            flags = {
                "tool_interrupt_flag": False,
                "plan_verifier_flag": False,
                "response_formatting_flag": False,
                "context_flag": False,
                "evaluation_flag": False
            }
            worker_agent = await agent_service._build_workflow(chains=chains, flags=flags)

            log.info(f"Successfully built worker agent of type '{worker_agent_type}' with ID: {worker_agent_id}, and name: {worker_agent_name}")
            def _after_final_agent_callback(callback_context: CallbackContext) -> Optional[types.Content]:
                """
                Callback function to be executed after the final agent in the workflow completes.
                """
                state = callback_context.state
                response = state.get("response", "")
                if isinstance(response, dict):
                    response = response.get("response")
                log.info(f"Final agent as tool call response: {response}")
                return types.Content(role="model", parts=[types.Part(text=str(response))])

            worker_agent.description = worker_agent_description
            worker_agent.after_agent_callback = _after_final_agent_callback
            worker_agents_as_tools.append(AgentTool(agent=worker_agent))

        log.info(f"Total worker agents built as tools: {len(worker_agents_as_tools)}")
        return worker_agents_as_tools


