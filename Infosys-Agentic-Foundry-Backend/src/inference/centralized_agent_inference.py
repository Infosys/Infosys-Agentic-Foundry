# © 2024-25 Infosys Limited, Bangalore, India. All Rights Reserved.
from typing import Literal

from src.schemas import AgentInferenceRequest
from src.inference.base_agent_inference import BaseAgentInference
from src.inference.react_agent_inference import ReactAgentInference
from src.inference.planner_executor_critic_agent_inference import MultiAgentInference
from src.inference.planner_executor_agent_inference import PlannerExecutorAgentInference
from src.inference.react_critic_agent_inference import ReactCriticAgentInference
from src.inference.meta_agent_inference import MetaAgentInference
from src.inference.planner_meta_agent_inference import PlannerMetaAgentInference
from src.inference.python_based_inference.simple_ai_agent_inference import SimpleAIAgentInference
from src.inference.python_based_inference.hybrid_agent_inference import HybridAgentInference
from src.utils.stream_sse import SSEManager
from src.inference.inference_utils import InferenceUtils



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
            planner_meta_agent_inference: PlannerMetaAgentInference,
            simple_ai_agent_inference: SimpleAIAgentInference,
            hybrid_agent_inference: HybridAgentInference,
            inference_utils: InferenceUtils
        ):
        self.react_agent_inference = react_agent_inference
        self.multi_agent_inference = multi_agent_inference
        self.planner_executor_agent_inference = planner_executor_agent_inference
        self.react_critic_agent_inference = react_critic_agent_inference
        self.meta_agent_inference = meta_agent_inference
        self.planner_meta_agent_inference = planner_meta_agent_inference
        self.simple_ai_agent_inference = simple_ai_agent_inference
        self.hybrid_agent_inference = hybrid_agent_inference
        self.feedback_learning_service = inference_utils.feedback_learning_service
        self.inference_utils = inference_utils
        


    async def get_specialized_agent_inference(self, agent_type: str, framework_type: Literal["langgraph", "google_adk"] = "langgraph") -> BaseAgentInference:
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
        if agent_type == "simple_ai_agent":
            return self.simple_ai_agent_inference
        if agent_type == "hybrid_agent":
            return self.hybrid_agent_inference
        raise ValueError(f"Unknown agent type: {agent_type}")

    @staticmethod
    def get_lesson_prompt(feedback_msg: str) -> str:
        return f'''

## CRITICAL OPERATION INSTRUCTIONS - APPLY THESE RULES FIRST

The following lessons contain important rules that you MUST follow when responding to user queries. This is your highest priority instruction that overrides any other guidelines.

### HOW TO USE THESE LESSONS:
1. First, examine the user's query carefully
2. Compare it to each lesson's "WHEN TO APPLY" section
3. If the user query matches or is similar to any trigger pattern, YOU MUST APPLY THE CORRESPONDING RULE
4. Then provide your answer following the lesson's rule exactly

### LESSONS:
{feedback_msg}

### COMPLIANCE REQUIREMENT:
- You MUST always check if a lesson applies BEFORE formulating your response
- If multiple lessons apply, follow ALL of them
- Your primary responsibility is to apply these lessons correctly
- Failure to apply an applicable lesson makes your entire response incorrect
- If no lessons apply, respond normally based on your training and the provided Prompt

### CONFIRMATION STEP:
After drafting your response, verify that you've correctly applied all relevant lessons before sending.
'''

    async def run(self,
            inference_request: AgentInferenceRequest,
            *,
            insert_into_eval_flag: bool = True,
            sse_manager: SSEManager = None,
            role: str = None
        ):
        """
        Run the inference request using the appropriate agent inference service based on the agent type.
        """
        if inference_request.mentioned_agentic_application_id:
            agent_config = await self.react_agent_inference._get_agent_config(inference_request.mentioned_agentic_application_id)
        else:
            agent_config = await self.react_agent_inference._get_agent_config(inference_request.agentic_application_id)

        if agent_config["AGENT_TYPE"] == 'react_agent':
            feedback_learning_data = await self.feedback_learning_service.get_approved_feedback(agent_id=inference_request.agentic_application_id)
            feedback_msg = await self.inference_utils.format_feedback_learning_data(feedback_learning_data)
            if feedback_msg:
                agent_config['SYSTEM_PROMPT']['SYSTEM_PROMPT_REACT_AGENT'] += self.get_lesson_prompt(feedback_msg)
    
        elif agent_config["AGENT_TYPE"] == 'planner_executor_agent':
            feedback_learning_data = await self.feedback_learning_service.get_approved_feedback(agent_id=inference_request.agentic_application_id)
            feedback_msg = await self.inference_utils.format_feedback_learning_data(feedback_learning_data)
            if feedback_msg:
                agent_config['SYSTEM_PROMPT']['SYSTEM_PROMPT_EXECUTOR_AGENT'] += self.get_lesson_prompt(feedback_msg)
                agent_config['SYSTEM_PROMPT']['SYSTEM_PROMPT_PLANNER_AGENT'] += self.get_lesson_prompt(feedback_msg)
                agent_config['SYSTEM_PROMPT']['SYSTEM_PROMPT_REPLANNER_AGENT'] += self.get_lesson_prompt(feedback_msg)

        elif agent_config["AGENT_TYPE"] == 'multi_agent':
            feedback_learning_data = await self.feedback_learning_service.get_approved_feedback(agent_id=inference_request.agentic_application_id)
            feedback_msg = await self.inference_utils.format_feedback_learning_data(feedback_learning_data)
            if feedback_msg:
                agent_config['SYSTEM_PROMPT']['SYSTEM_PROMPT_EXECUTOR_AGENT'] += self.get_lesson_prompt(feedback_msg)
                agent_config['SYSTEM_PROMPT']['SYSTEM_PROMPT_PLANNER_AGENT'] += self.get_lesson_prompt(feedback_msg)
                agent_config['SYSTEM_PROMPT']['SYSTEM_PROMPT_REPLANNER_AGENT'] += self.get_lesson_prompt(feedback_msg)
                agent_config['SYSTEM_PROMPT']['SYSTEM_PROMPT_CRITIC_AGENT'] += self.get_lesson_prompt(feedback_msg)
                agent_config['SYSTEM_PROMPT']['SYSTEM_PROMPT_CRITIC_BASED_PLANNER_AGENT'] += self.get_lesson_prompt(feedback_msg)
        
        elif agent_config["AGENT_TYPE"] == 'react_critic_agent':
            feedback_learning_data = await self.feedback_learning_service.get_approved_feedback(agent_id=inference_request.agentic_application_id)
            feedback_msg = await self.inference_utils.format_feedback_learning_data(feedback_learning_data)
            if feedback_msg:
                agent_config['SYSTEM_PROMPT']['SYSTEM_PROMPT_CRITIC_AGENT'] += self.get_lesson_prompt(feedback_msg)
                agent_config['SYSTEM_PROMPT']['SYSTEM_PROMPT_EXECUTOR_AGENT'] += self.get_lesson_prompt(feedback_msg)

        elif agent_config["AGENT_TYPE"] == 'hybrid_agent':
            feedback_learning_data = await self.feedback_learning_service.get_approved_feedback(agent_id=inference_request.agentic_application_id)
            feedback_msg = await self.inference_utils.format_feedback_learning_data(feedback_learning_data)
            if feedback_msg:
                agent_config['SYSTEM_PROMPT']['SYSTEM_PROMPT_HYBRID_AGENT'] += self.get_lesson_prompt(feedback_msg)


        agent_inference: BaseAgentInference = await self.get_specialized_agent_inference(agent_type=agent_config["AGENT_TYPE"], framework_type=inference_request.framework_type)
        # if inference_request.enable_streaming_flag:
        #     async for output in agent_inference.run(
        #         inference_request=inference_request,
        #         agent_config=agent_config,
        #         insert_into_eval_flag=insert_into_eval_flag,
        #         sse_manager=sse_manager,
        #         role=role
        #     ):
        #         yield output
        # else:
        
        async for response in agent_inference.run(
                inference_request=inference_request,
                agent_config=agent_config,
                insert_into_eval_flag=insert_into_eval_flag,
                sse_manager=sse_manager,
                role=role
            ):
            yield response


