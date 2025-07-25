# © 2024-25 Infosys Limited, Bangalore, India. All Rights Reserved.
from langchain.prompts import PromptTemplate
from langchain_core.output_parsers.string import StrOutputParser
from telemetry_wrapper import logger as log
from typing import Optional, TypedDict, Union
from langgraph.graph import StateGraph, START, END

from langchain_openai import AzureChatOpenAI, ChatOpenAI
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain.prompts import PromptTemplate
from langchain_core.output_parsers import StrOutputParser

from src.prompts.prompts import react_system_prompt_generator
from src.prompts.prompts import multi_agent_critic_system_prompt_generator_prompt

from src.database.repositories import AgentRepository, RecycleAgentRepository
from src.database.services import TagService, ToolService
from src.agent_templates.base_agent_onboard import BaseAgentOnboard



async def multi_agent_executor_system_prompt_generator_function(agent_name, agent_goal, workflow_description, tool_prompt, llm):
    executor_prompt_template = PromptTemplate.from_template(react_system_prompt_generator)
    executor_prompt_generator = executor_prompt_template | llm | StrOutputParser()
    executor_prompt = await executor_prompt_generator.ainvoke({
        "agent_name": agent_name,
        "agent_goal": agent_goal,
        "workflow_description": workflow_description,
        "tool_prompt": tool_prompt
    })
    return executor_prompt

async def multi_agent_critic_system_prompt_generator_function(agent_name, agent_goal, workflow_description, tool_prompt, llm):
    critic_prompt_template = PromptTemplate.from_template(
        multi_agent_critic_system_prompt_generator_prompt
    )
    critic_prompt_generator = critic_prompt_template | llm | StrOutputParser()
    critic_prompt = await critic_prompt_generator.ainvoke({
        "agent_name": agent_name,
        "agent_goal": agent_goal,
        "workflow_description": workflow_description,
        "tools_prompt": tool_prompt
    })
    return critic_prompt


class MultiAgentConfigurationStateRE(TypedDict):
    """
    Represents the state of a multi-agent configuration.
    Attributes:
        agent_name: Name of the agent
        agent_goal: A description of the use case.
        workflow_description: A description of the workflow.
        tool_prompt: Information about the tools available to the agents.
        llm: Choice of LLM
        system_prompt_executor_agent: The system prompt for the executor agent.
        system_prompt_critic_agent: The system prompt for the critic agent.
        MULTI_AGENT_SYSTEM_PROMPTS: A dictionary of system prompts for all agents.
    """
    agent_name: str
    agent_goal: str
    workflow_description: str
    tool_prompt: str
    llm: Union[AzureChatOpenAI, ChatOpenAI, ChatGoogleGenerativeAI]
    system_prompt_executor_agent: Optional[str]
    system_prompt_critic_agent: Optional[str]
    MULTI_AGENT_SYSTEM_PROMPTS: Optional[dict]

async def system_prompt_build_executor_agent(state: MultiAgentConfigurationStateRE):
    """
    Builds the system prompt for the executor agent.

    Args:
        state: The current state of the multi-agent configuration.

    Returns:
        A dictionary containing the system prompt for the executor agent.
    """
    response = await multi_agent_executor_system_prompt_generator_function(agent_name=state["agent_name"],
                                                            agent_goal=state["agent_goal"],
                                                            workflow_description=state["workflow_description"],
                                                            tool_prompt=state["tool_prompt"],
                                                            llm=state["llm"])
    return {"system_prompt_executor_agent": response}

async def system_prompt_build_critic_agent(state: MultiAgentConfigurationStateRE):
    """
    Builds the system prompt for the critic agent.

    Args:
        state: The current state of the multi-agent configuration.

    Returns:
        A dictionary containing the system prompt for the critic agent.
    """
    response = await multi_agent_critic_system_prompt_generator_function(agent_name=state["agent_name"],
                                                            agent_goal=state["agent_goal"],
                                                            workflow_description=state["workflow_description"],
                                                            tool_prompt=state["tool_prompt"],
                                                            llm=state["llm"])
    return {"system_prompt_critic_agent": response}


async def merge(state: MultiAgentConfigurationStateRE):
    """
    Merges the system prompts into a single output.

    Args:
        state (MultiAgentConfigurationState):
        The current state of the multi-agent configuration.

    Returns:
        dict: A dictionary containing the merged system prompts and tools information.
    """
    outputs = {}
    outputs['SYSTEM_PROMPT_EXECUTOR_AGENT'] = state["system_prompt_executor_agent"]
    outputs['SYSTEM_PROMPT_CRITIC_AGENT'] = state["system_prompt_critic_agent"]
    return {"MULTI_AGENT_SYSTEM_PROMPTS": outputs}

builder = StateGraph(MultiAgentConfigurationStateRE)
builder.add_node("ExecutorAgent", system_prompt_build_executor_agent)
builder.add_node("CriticAgent", system_prompt_build_critic_agent)
builder.add_node("Merge", merge)

# Flow
builder.add_edge(START, "ExecutorAgent")
builder.add_edge(START, "CriticAgent")

builder.add_edge("ExecutorAgent", "Merge")
builder.add_edge("CriticAgent", "Merge")
builder.add_edge("Merge", END)
graph = builder.compile()



class ReactCriticAgentOnboard(BaseAgentOnboard):
    """
    ReactCriticAgentOnboard is a specialized onboarding service for React critic agents, extending the BaseAgentOnboard class.
    """

    def __init__(
        self,
        agent_repo: AgentRepository,
        recycle_agent_repo: RecycleAgentRepository,
        tool_service: ToolService,
        tag_service: TagService,
    ):
        super().__init__(
            agent_type="react_critic_agent",
            agent_repo=agent_repo,
            recycle_agent_repo=recycle_agent_repo,
            tool_service=tool_service,
            tag_service=tag_service
        )


    async def _generate_system_prompt(self, agent_name, agent_goal, workflow_description, tool_or_worker_agents_prompt, llm):
        log.info("Building multi-agent system prompts for agent: %s", agent_name)
        agent_config_resp = await graph.ainvoke(input={
                                        'agent_name': agent_name,
                                        'agent_goal': agent_goal,
                                        'workflow_description': workflow_description,
                                        'tool_prompt': tool_or_worker_agents_prompt,
                                        'llm': llm
                                    })
        log.info("Multi-agent system prompts built successfully for agent: %s", agent_name)
        return agent_config_resp["MULTI_AGENT_SYSTEM_PROMPTS"]


