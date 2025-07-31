# © 2024-25 Infosys Limited, Bangalore, India. All Rights Reserved.
from src.inference.base_agent_inference import BaseAgentInference, AgentInferenceRequest, AgentInferenceHITLRequest
from src.inference.react_agent_inference import ReactAgentInference
from src.inference.planner_executor_critic_agent_inference import MultiAgentInference
from src.inference.planner_executor_agent_inference import PlannerExecutorAgentInference
from src.inference.react_critic_agent_inference import ReactCriticAgentInference
from src.inference.meta_agent_inference import MetaAgentInference
from src.inference.planner_meta_agent_inference import PlannerMetaAgentInference



class CentralizedAgentInference:
    """
    Centralized service to handle inference requests for different agent types.
    """

    def __init__(
            self,
            react_agent_inference: ReactAgentInference,
            multi_agent_inference: MultiAgentInference,
            planner_executor_agent_inference: PlannerExecutorAgentInference,
            react_critic_agent_inference: ReactCriticAgentInference,
            meta_agent_inference: MetaAgentInference,
            planner_meta_agent_inference: PlannerMetaAgentInference
        ):
        self.react_agent_inference = react_agent_inference
        self.multi_agent_inference = multi_agent_inference
        self.planner_executor_agent_inference = planner_executor_agent_inference
        self.react_critic_agent_inference = react_critic_agent_inference
        self.meta_agent_inference = meta_agent_inference
        self.planner_meta_agent_inference = planner_meta_agent_inference


    async def get_specialized_agent_inference(self, agent_type: str) -> BaseAgentInference:
        """Return the appropriate specialized service instance"""
        if agent_type == "react_agent":
            return self.react_agent_inference
        if agent_type == "multi_agent":
            return self.multi_agent_inference
        if agent_type == "planner_executor_agent":
            return self.planner_executor_agent_inference
        if agent_type == "react_critic_agent":
            return self.react_critic_agent_inference
        if agent_type == "meta_agent":
            return self.meta_agent_inference
        if agent_type == "planner_meta_agent":
            return self.planner_meta_agent_inference
        raise ValueError(f"Unknown agent type: {agent_type}")

    async def run(self,
            inference_request: AgentInferenceRequest | AgentInferenceHITLRequest,
            *,
            hitl_flag: bool = False,
            insert_into_eval_flag: bool = True
        ):
        """
        Run the inference request using the appropriate agent inference service based on the agent type.
        """
        agent_config = await self.react_agent_inference._get_agent_config(inference_request.agentic_application_id)
        agent_inference: BaseAgentInference = await self.get_specialized_agent_inference(agent_type=agent_config["AGENT_TYPE"])
        return await agent_inference.run(
            inference_request=inference_request,
            agent_config=agent_config,
            hitl_flag=hitl_flag,
            insert_into_eval_flag=insert_into_eval_flag
        )


