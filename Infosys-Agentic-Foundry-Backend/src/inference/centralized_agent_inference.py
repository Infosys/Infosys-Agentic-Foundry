# © 2024-25 Infosys Limited, Bangalore, India. All Rights Reserved.
from typing import Literal, Any

from src.schemas import AgentInferenceRequest
from src.config.constants import AgentType, FrameworkType
# Langgraph based Inference Imports
from src.inference.base_agent_inference import BaseAgentInference
from src.inference.react_agent_inference import ReactAgentInference
from src.inference.planner_executor_critic_agent_inference import MultiAgentInference
from src.inference.planner_executor_agent_inference import PlannerExecutorAgentInference
from src.inference.react_critic_agent_inference import ReactCriticAgentInference
from src.inference.meta_agent_inference import MetaAgentInference
from src.inference.planner_meta_agent_inference import PlannerMetaAgentInference
# Python based Inference Imports
from src.inference.python_based_inference.hybrid_agent_inference import HybridAgentInference
# Google ADK based Inference Imports
from src.inference.google_adk_inference.react_agent_gadk_inference import ReactAgentGADKInference
from src.inference.google_adk_inference.planner_executor_critic_agent_gadk_inference import PlannerExecutorCriticAgentGADKInference
from src.inference.google_adk_inference.planner_executor_agent_gadk_inference import PlannerExecutorAgentGADKInference
from src.inference.google_adk_inference.react_critic_agent_gadk_inference import ReactCriticAgentGADKInference
from src.inference.google_adk_inference.meta_agent_gadk_inference import MetaAgentGADKInference
from src.inference.google_adk_inference.planner_meta_agent_gadk_inference import PlannerMetaAgentGADKInference

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

            hybrid_agent_inference: HybridAgentInference,

            gadk_react_agent_inference: ReactAgentGADKInference,
            gadk_planner_executor_critic_agent_inference: PlannerExecutorCriticAgentGADKInference,
            gadk_planner_executor_agent_inference: PlannerExecutorAgentGADKInference,
            gadk_react_critic_agent_inference: ReactCriticAgentGADKInference,
            gadk_meta_agent_inference: MetaAgentGADKInference,
            gadk_planner_meta_agent_inference: PlannerMetaAgentGADKInference,

            inference_utils: InferenceUtils
        ):
        self.react_agent_inference = react_agent_inference
        self.multi_agent_inference = multi_agent_inference
        self.planner_executor_agent_inference = planner_executor_agent_inference
        self.react_critic_agent_inference = react_critic_agent_inference
        self.meta_agent_inference = meta_agent_inference
        self.planner_meta_agent_inference = planner_meta_agent_inference

        self.hybrid_agent_inference = hybrid_agent_inference

        self.gadk_react_agent_inference = gadk_react_agent_inference
        self.gadk_planner_executor_critic_agent_inference = gadk_planner_executor_critic_agent_inference
        self.gadk_planner_executor_agent_inference = gadk_planner_executor_agent_inference
        self.gadk_react_critic_agent_inference = gadk_react_critic_agent_inference
        self.gadk_meta_agent_inference = gadk_meta_agent_inference
        self.gadk_planner_meta_agent_inference = gadk_planner_meta_agent_inference

        self.inference_utils = inference_utils
        self.feedback_learning_service = inference_utils.feedback_learning_service

        self.langgraph_inference_services_map = {
            AgentType.REACT_AGENT: self.react_agent_inference,
            AgentType.PLANNER_EXECUTOR_CRITIC_AGENT: self.multi_agent_inference,
            AgentType.PLANNER_EXECUTOR_AGENT: self.planner_executor_agent_inference,
            AgentType.REACT_CRITIC_AGENT: self.react_critic_agent_inference,
            AgentType.META_AGENT: self.meta_agent_inference,
            AgentType.PLANNER_META_AGENT: self.planner_meta_agent_inference
        }

        self.google_adk_inference_services_map = {
            AgentType.REACT_AGENT: self.gadk_react_agent_inference,
            AgentType.PLANNER_EXECUTOR_CRITIC_AGENT: self.gadk_planner_executor_critic_agent_inference,
            AgentType.PLANNER_EXECUTOR_AGENT: self.gadk_planner_executor_agent_inference,
            AgentType.REACT_CRITIC_AGENT: self.gadk_react_critic_agent_inference,
            AgentType.META_AGENT: self.gadk_meta_agent_inference,
            AgentType.PLANNER_META_AGENT: self.gadk_planner_meta_agent_inference
        }

    async def get_specialized_agent_inference(self, agent_type: str, framework_type: FrameworkType = FrameworkType.LANGGRAPH) -> BaseAgentInference:
        """Return the appropriate specialized service instance"""

        if agent_type == AgentType.HYBRID_AGENT:
            return self.hybrid_agent_inference

        if framework_type == FrameworkType.GOOGLE_ADK and agent_type in self.google_adk_inference_services_map:
            return self.google_adk_inference_services_map[agent_type]

        if framework_type == FrameworkType.LANGGRAPH and agent_type in self.langgraph_inference_services_map:
            return self.langgraph_inference_services_map[agent_type]

        raise ValueError(f"Unknown agent type: {agent_type}")

    @staticmethod
    def get_user_context_prompt(user_name: str, role: str, department_name: str = None) -> str:
        """
        Generate a user context prompt to be injected into the system prompt.
        This allows agent creators to define role-based data visibility rules.
        
        Args:
            user_name: The logged-in user's name/email
            role: The user's role (User, Developer, Admin, SuperAdmin)
            department_name: The user's department (optional)
        
        Returns:
            A formatted string containing user context information
        """
        department_info = f"\n- Department: {department_name}" if department_name else ""
        return f'''

## CURRENT USER CONTEXT
The following information identifies the currently logged-in user. Use this context to apply any role-based or user-specific rules defined in this prompt.

- User Name: {user_name}
- Role: {role}{department_info}

- Use User Name in your responses to personalize interactions.

### ROLE-BASED ACCESS INSTRUCTIONS:
When executing tools or returning data, apply any role-specific visibility rules defined by the agent creator. For example:
- If the agent creator specified "show only summary data for User role", filter the response accordingly
- If the agent creator specified "show full details for Admin role", provide complete information
- Always respect the data visibility rules based on the current user's role

'''

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
            role: str = None,
            department_name: str = None,
            user_name: str = None
        ):
        """
        Run the inference request using the appropriate agent inference service based on the agent type.
        
        Args:
            inference_request: The inference request containing all necessary parameters
            insert_into_eval_flag: Flag to insert evaluation data
            sse_manager: SSE manager for streaming
            role: The logged-in user's role (User, Developer, Admin, SuperAdmin)
            department_name: The user's department
            user_name: The logged-in user's name/email for role-based access control
        """
        agent_id = inference_request.mentioned_agentic_application_id or inference_request.agentic_application_id
        agent_config = await self.react_agent_inference._get_agent_config(agent_id)
        
        # Generate user context prompt if user information is available
        user_context_prompt = ""
        if user_name and role:
            user_context_prompt = self.get_user_context_prompt(user_name, role, department_name)

        # Handle Feedback Learning Integration
        feedback_learning_data = await self.feedback_learning_service.get_approved_feedback(agent_id=agent_id, department_name=department_name)
        feedback_msg = await self.inference_utils.format_feedback_learning_data(feedback_learning_data)
        lesson_prompt = self.get_lesson_prompt(feedback_msg) if feedback_msg else ""
        system_prompts: dict = agent_config.get('SYSTEM_PROMPT', {})
        for system_prompt_key in system_prompts.keys():
            agent_config['SYSTEM_PROMPT'][system_prompt_key] += lesson_prompt
            if user_context_prompt:
                agent_config['SYSTEM_PROMPT'][system_prompt_key] += user_context_prompt


        agent_inference: BaseAgentInference = await self.get_specialized_agent_inference(agent_type=agent_config["AGENT_TYPE"], framework_type=inference_request.framework_type)

        async for response in agent_inference.run(
                inference_request=inference_request,
                agent_config=agent_config,
                insert_into_eval_flag=insert_into_eval_flag,
                role=role,
                department_name=department_name
            ):
            yield response

    async def update_response_time(self, agent_id: str, session_id: str,  start_time: float, time_stamp: Any):
        """Updates the response time in the last executor message for the given session. 
        As update_response_time method is common for all types we are calling react agent inference method here."""
        return await self.react_agent_inference.update_response_time(agent_id, session_id,  start_time=start_time, time_stamp=time_stamp)
