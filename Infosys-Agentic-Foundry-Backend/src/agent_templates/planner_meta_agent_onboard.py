# © 2024-25 Infosys Limited, Bangalore, India. All Rights Reserved.
import asyncio
from typing import TypedDict, Dict, Any, Optional, Union
from langchain.prompts import PromptTemplate
from langchain_core.output_parsers.string import StrOutputParser
from langgraph.graph import StateGraph, END, START

from src.prompts.prompts import (
    meta_agent_planner_system_prompt_generator_prompt,
    meta_agent_supervisor_executor_system_prompt_generator_prompt,
    meta_agent_response_generator_system_prompt_generator_prompt
)
from telemetry_wrapper import logger as log

from src.database.services import AgentServiceUtils
from src.agent_templates.base_agent_onboard import BaseMetaTypeAgentOnboard
from src.config.constants import AgentType



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

    def __init__(self, agent_service_utils: AgentServiceUtils):
        super().__init__(agent_type=AgentType.PLANNER_META_AGENT, agent_service_utils=agent_service_utils)


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
        
        # Run both LLM calls in parallel
        agent_config_resp, _ = await asyncio.gather(
            graph.ainvoke(input={}),
            self._generate_and_save_file_context_prompt(
                agent_name=agent_name,
                agent_goal=agent_goal,
                workflow_description=workflow_description,
                tool_or_worker_agents_prompt=tool_or_worker_agents_prompt,
                llm=llm
            )
        )
        
        log.info(f"Meta-agent system prompts built successfully for agent: {agent_name}")
        
        # The final output structure matches your example's return value
        return agent_config_resp["META_AGENT_SYSTEM_PROMPTS"]

    async def _generate_and_save_file_context_prompt(self, agent_name, agent_goal, workflow_description, tool_or_worker_agents_prompt, llm):
        """
        Generates and saves the file-context system prompt for AgentShell-based context management.
        This prompt is stored in a separate file and loaded when file_context_management_flag=True.
        
        Note: Memory tools (manage_tool, search_tool) are filtered out from the tool prompt
        because file-based context management uses shell commands for memory operations.
        """
        from ..prompts.prompts import file_context_system_prompt_generator
        from langchain.prompts import PromptTemplate
        from langchain_core.output_parsers.string import StrOutputParser
        import os
        
        log.info("Generating file-context prompt for agent: %s", agent_name)
        
        # Filter out memory tool information from tool_or_worker_agents_prompt
        # Use common utility from AgentServiceUtils
        filtered_tool_prompt = AgentServiceUtils.filter_memory_tools_from_prompt(tool_or_worker_agents_prompt)
        
        # Generate file-context prompt using LLM
        file_context_prompt_template = PromptTemplate.from_template(file_context_system_prompt_generator)
        file_context_prompt_gen = file_context_prompt_template | llm | StrOutputParser()
        
        file_context_prompt = await file_context_prompt_gen.ainvoke({
            "agent_name": agent_name,
            "agent_goal": agent_goal,
            "workflow_description": workflow_description,
            "tool_prompt": filtered_tool_prompt
        })
        
        # Save to file
        safe_agent_name = "".join(c if c.isalnum() or c in ('-', '_') else '_' for c in agent_name)
        file_context_dir = os.path.join("agent_workspaces", "file_context_prompts")
        os.makedirs(file_context_dir, exist_ok=True)
        file_context_path = os.path.join(file_context_dir, f"{safe_agent_name}_file_context_prompt.md")
        
        with open(file_context_path, "w", encoding="utf-8") as f:
            f.write(file_context_prompt)
        
        log.info("File-context prompt saved to: %s", file_context_path)


