# © 2024-25 Infosys Limited, Bangalore, India. All Rights Reserved.
from typing import TypedDict, Dict, Any, Optional, Union
from langchain.prompts import PromptTemplate
from langchain_core.output_parsers.string import StrOutputParser
from langgraph.graph import StateGraph, END, START
from langchain_openai import AzureChatOpenAI, ChatOpenAI
from langchain_google_genai import ChatGoogleGenerativeAI

from src.prompts.prompts import (
    meta_agent_planner_system_prompt_generator_prompt,
    meta_agent_supervisor_executor_system_prompt_generator_prompt,
    meta_agent_response_generator_system_prompt_generator_prompt
)
from telemetry_wrapper import logger as log

from src.database.repositories import AgentRepository, RecycleAgentRepository
from src.database.services import TagService, ToolService
from src.agent_templates.base_agent_onboard import BaseMetaTypeAgentOnboard



# --- Using your provided State Definition ---
class MultiAgentConfigurationState(TypedDict):
    """
    Represents the state of a multi-agent configuration.
    """
    system_prompt_executor_agent: Optional[str]
    system_prompt_planner_agent: Optional[str]
    system_prompt_response_generator_agent: Optional[str]
    META_AGENT_SYSTEM_PROMPTS: Optional[dict]


class PlannerMetaAgentOnboard(BaseMetaTypeAgentOnboard):
    """
    PlannerMetaAgentOnboard is a specialized onboarding service for meta-agents with a planner,
    extending the BaseMetaTypeAgentOnboard class.
    """

    def __init__(
        self,
        agent_repo: AgentRepository,
        recycle_agent_repo: RecycleAgentRepository,
        tool_service: ToolService,
        tag_service: TagService,
    ):
        super().__init__(
            agent_type="planner_meta_agent",
            agent_repo=agent_repo,
            recycle_agent_repo=recycle_agent_repo,
            tool_service=tool_service,
            tag_service=tag_service
        )


    async def _generate_system_prompt(self, agent_name, agent_goal, workflow_description, tool_or_worker_agents_prompt, llm):
        """
        Builds the three required system prompts for the Planner-Supervisor-Responder
        meta-agent architecture in parallel using a compiled LangGraph. This function
        is designed to be compatible with the MultiAgentConfigurationState.

        Args:
            agent_name: The public-facing name of the meta-agent.
            agent_goal: The overall goal of the meta-agent.
            workflow_description: A description of how the agent operates.
            worker_agents_prompt: A formatted string detailing the available worker agents.
            llm: The language model instance to use for generation.

        Returns:
            A dictionary containing the final, structured system prompts.
        """
        log.info(f"Building meta-agent system prompts with planner for agent: {agent_name}")
        
        # --- Define Graph Nodes ---

        async def build_planner_prompt_node(state: MultiAgentConfigurationState):
            """Generates the system prompt for the Meta-Agent's Planner."""
            log.info("Node: Generating planner system prompt...")
            prompt_template = PromptTemplate.from_template(
                meta_agent_planner_system_prompt_generator_prompt
            )
            input_data = {
                "agent_name": agent_name,
                "agent_goal": agent_goal,
                "workflow_description": workflow_description,
                "worker_agents_prompt": tool_or_worker_agents_prompt
            }
            chain = prompt_template | llm | StrOutputParser()
            result = await chain.ainvoke(input_data)
            return {
                "system_prompt_planner_agent": result
            }

        async def build_supervisor_prompt_node(state: MultiAgentConfigurationState):
            """Generates the system prompt for the Meta-Agent's Supervisor/Executor."""
            log.info("Node: Generating supervisor system prompt...")
            prompt_template = PromptTemplate.from_template(
                meta_agent_supervisor_executor_system_prompt_generator_prompt
            )
            input_data = {
                "agent_name": agent_name,
                "agent_goal": agent_goal,
                "workflow_description": workflow_description,
                "worker_agents_prompt": tool_or_worker_agents_prompt
            }
            chain = prompt_template | llm | StrOutputParser()
            result = await chain.ainvoke(input_data)
            return {
                "system_prompt_executor_agent": result
            }

        async def build_responder_prompt_node(state: MultiAgentConfigurationState):
            """Generates the system prompt for the Meta-Agent's Final Response Generator."""
            log.info("Node: Generating responder system prompt...")
            prompt_template = PromptTemplate.from_template(
                meta_agent_response_generator_system_prompt_generator_prompt
            )
            input_data = {
                "agent_name": agent_name,
                "agent_goal": agent_goal,
                "workflow_description": workflow_description,
                "worker_agents_prompt": tool_or_worker_agents_prompt
            }
            chain = prompt_template | llm | StrOutputParser()
            result = await chain.ainvoke(input_data)
            return {
                "system_prompt_response_generator_agent": result
            }

        def merge_prompts_node(state: MultiAgentConfigurationState):
            """Merges the generated prompts into the final output structure."""
            log.info("Node: Merging all generated prompts.")
            outputs = {
                "SYSTEM_PROMPT_META_AGENT_PLANNER": state["system_prompt_planner_agent"],
                "SYSTEM_PROMPT_META_AGENT_SUPERVISOR": state["system_prompt_executor_agent"],
                "SYSTEM_PROMPT_META_AGENT_RESPONDER": state["system_prompt_response_generator_agent"],
            }
            return {"META_AGENT_SYSTEM_PROMPTS": outputs}

        # --- Build and Compile Graph ---
        
        # The graph is built using your specified state class
        builder = StateGraph(MultiAgentConfigurationState)

        # Add all nodes
        builder.add_node("PlannerPromptBuilder", build_planner_prompt_node)
        builder.add_node("SupervisorPromptBuilder", build_supervisor_prompt_node)
        builder.add_node("ResponderPromptBuilder", build_responder_prompt_node)
        builder.add_node("Merge", merge_prompts_node)

        # Define the graph flow for parallel execution
        builder.add_edge(START, "PlannerPromptBuilder")
        builder.add_edge(START, "SupervisorPromptBuilder")
        builder.add_edge(START, "ResponderPromptBuilder")

        # Merge after all builders are complete
        builder.add_edge("PlannerPromptBuilder", "Merge")
        builder.add_edge("SupervisorPromptBuilder", "Merge")
        builder.add_edge("ResponderPromptBuilder", "Merge")
        
        builder.add_edge("Merge", END)

        graph = builder.compile()
        
        agent_config_resp = await graph.ainvoke(input={})
        
        log.info(f"Meta-agent system prompts built successfully for agent: {agent_name}")
        
        # The final output structure matches your example's return value
        return agent_config_resp["META_AGENT_SYSTEM_PROMPTS"]


