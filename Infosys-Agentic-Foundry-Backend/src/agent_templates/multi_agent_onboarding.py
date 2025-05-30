# © 2024-25 Infosys Limited, Bangalore, India. All Rights Reserved.
from typing import Optional, TypedDict, Union
from langgraph.graph import StateGraph, START, END

from langchain_openai import AzureChatOpenAI, ChatOpenAI
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain.prompts import PromptTemplate
from langchain_core.output_parsers import StrOutputParser, JsonOutputParser

from src.prompts.prompts import multi_agent_planner_system_prompt_generator_prompt
from src.prompts.prompts import multi_agent_executor_system_prompt_generator_prompt
from src.prompts.prompts import multi_agent_critic_system_prompt_generator_prompt
from src.prompts.prompts import critic_based_planner_agent_system_prompt
from src.prompts.prompts import response_generator_agent_system_prompt
from src.prompts.prompts import replanner_agent_system_prompt
from src.prompts.prompts import multi_agent_general_llm_system_prompt_generator_prompt

def multi_agent_planner_system_prompt_generator_function(agent_name, agent_goal, workflow_description, tool_prompt, llm):
    planner_prompt_template = PromptTemplate.from_template(
        multi_agent_planner_system_prompt_generator_prompt
    )
    planner_prompt_generator = planner_prompt_template | llm | StrOutputParser()
    planner_prompt = planner_prompt_generator.invoke({
        "agent_name":agent_name,
        "agent_goal":agent_goal,
        "workflow_description": workflow_description,
        "tools_prompt": tool_prompt
    })
    return planner_prompt

def multi_agent_executor_system_prompt_generator_function(agent_name, agent_goal, workflow_description, tool_prompt, llm):
    executor_prompt_template = PromptTemplate.from_template(
        multi_agent_executor_system_prompt_generator_prompt
    )
    executor_prompt_generator = executor_prompt_template | llm | StrOutputParser()
    executor_prompt = executor_prompt_generator.invoke({
        "agent_name": agent_name,
        "agent_goal": agent_goal,
        "workflow_description": workflow_description,
        "tools_prompt": tool_prompt
    })
    return executor_prompt

def multi_agent_general_system_prompt_generator_function(agent_name, agent_goal, workflow_description, tool_prompt, llm):
    general_prompt_template = PromptTemplate.from_template(
        multi_agent_general_llm_system_prompt_generator_prompt
    )
    general_prompt_generator = general_prompt_template | llm | StrOutputParser()
    general_prompt = general_prompt_generator.invoke({
        "agent_name": agent_name,
        "agent_goal": agent_goal,
        "workflow_description": workflow_description,
        "tools_prompt": tool_prompt
    })
    return general_prompt

def response_generator_agent_system_prompt_generator_function(agent_name, agent_goal, workflow_description, tool_prompt, llm):
    response_prompt_template = PromptTemplate.from_template(
        response_generator_agent_system_prompt
    )
    response_prompt_generator = response_prompt_template | llm | StrOutputParser()
    response_prompt = response_prompt_generator.invoke({
        "agent_name": agent_name,
        "agent_goal": agent_goal,
        "workflow_description": workflow_description,
        "tools_prompt": tool_prompt
    })
    return response_prompt

def multi_agent_critic_system_prompt_generator_function(agent_name, agent_goal, workflow_description, tool_prompt, llm):
    critic_prompt_template = PromptTemplate.from_template(
        multi_agent_critic_system_prompt_generator_prompt
    )
    critic_prompt_generator = critic_prompt_template | llm | StrOutputParser()
    critic_prompt = critic_prompt_generator.invoke({
        "agent_name": agent_name,
        "agent_goal": agent_goal,
        "workflow_description": workflow_description,
        "tools_prompt": tool_prompt
    })
    return critic_prompt

def critic_based_planner_agent_system_prompt_generation_function(agent_name, agent_goal, workflow_description, tool_prompt, llm):
    planner_prompt_template = PromptTemplate.from_template(
        critic_based_planner_agent_system_prompt
    )
    planner_prompt_generator = planner_prompt_template | llm | StrOutputParser()
    planner_prompt = planner_prompt_generator.invoke({
        "agent_name": agent_name,
        "agent_goal": agent_goal,
        "workflow_description": workflow_description,
        "tools_prompt": tool_prompt
    })
    return planner_prompt

def replanner_agent_system_prompt_generation_function(agent_name, agent_goal, workflow_description, tool_prompt, llm):
    replanner_prompt_template = PromptTemplate.from_template(
        replanner_agent_system_prompt
    )
    replanner_prompt_generator = replanner_prompt_template | llm | StrOutputParser()
    replanner_prompt = replanner_prompt_generator.invoke({
        "agent_name": agent_name,
        "agent_goal": agent_goal,
        "workflow_description": workflow_description,
        "tools_prompt": tool_prompt
    })
    return replanner_prompt


### Build Graph for System Prompt Generator
class MultiAgentConfigurationState(TypedDict):
    """
    Represents the state of a multi-agent configuration.
    Attributes:
        agent_name: Name of the agent
        agent_goal: A description of the use case.
        workflow_description: A description of the workflow.
        tool_prompt: Information about the tools available to the agents.
        llm: Choice of LLM
        system_prompt_executor_agent: The system prompt for the executor agent.
        system_prompt_planner_agent: The system prompt for the planner agent.
        system_prompt_response_generator_agent: The system prompt for the response generator agent.
        system_prompt_critic_agent: The system prompt for the critic agent.
        system_prompt_critic_based_planner_agent: The system prompt for the critic-based planner agent.
        system_prompt_replanner_agent: The system prompt for the replanner agent.
        system_prompt_general_llm: The system prompt for the general query handler agent
        MULTI_AGENT_SYSTEM_PROMPTS: A dictionary of system prompts for all agents.
    """
    agent_name: str
    agent_goal: str
    workflow_description: str
    tool_prompt: str
    llm: Union[AzureChatOpenAI, ChatOpenAI, ChatGoogleGenerativeAI]
    system_prompt_executor_agent: Optional[str]
    system_prompt_planner_agent: Optional[str]
    system_prompt_response_generator_agent: Optional[str]
    system_prompt_critic_agent: Optional[str]
    system_prompt_critic_based_planner_agent: Optional[str]
    system_prompt_replanner_agent: Optional[str]
    system_prompt_general_llm: Optional[str]
    MULTI_AGENT_SYSTEM_PROMPTS: Optional[dict]

def system_prompt_build_executor_agent(state: MultiAgentConfigurationState):
    """
    Builds the system prompt for the executor agent.
    
    Args:
        state: The current state of the multi-agent configuration.
    
    Returns:
        A dictionary containing the system prompt for the executor agent.
    """
    response = multi_agent_executor_system_prompt_generator_function(agent_name=state["agent_name"], 
                                                            agent_goal=state["agent_goal"], 
                                                            workflow_description=state["workflow_description"], 
                                                            tool_prompt=state["tool_prompt"], 
                                                            llm=state["llm"])
    return {"system_prompt_executor_agent": response}

def system_prompt_build_general_agent(state: MultiAgentConfigurationState):
    """
    Builds the system prompt for the general query handler agent.
    
    Args:
        state: The current state of the multi-agent configuration.
    
    Returns:
        A dictionary containing the system prompt for the general query handler agent.
    """
    response = multi_agent_general_system_prompt_generator_function(agent_name=state["agent_name"], 
                                                            agent_goal=state["agent_goal"], 
                                                            workflow_description=state["workflow_description"], 
                                                            tool_prompt=state["tool_prompt"], 
                                                            llm=state["llm"])
    return {"system_prompt_general_llm": response}

def system_prompt_build_planner_agent(state: MultiAgentConfigurationState):
    """
    Builds the system prompt for the planner agent.
    
    Args:
        state: The current state of the multi-agent configuration.
    
    Returns:
        A dictionary containing the system prompt for the planner agent.
    """
    response = multi_agent_planner_system_prompt_generator_function(agent_name=state["agent_name"], 
                                                            agent_goal=state["agent_goal"], 
                                                            workflow_description=state["workflow_description"], 
                                                            tool_prompt=state["tool_prompt"], 
                                                            llm=state["llm"])
    return {"system_prompt_planner_agent": response}

def system_prompt_build_response_gen_agent(state: MultiAgentConfigurationState):
    """
    Builds the system prompt for the response generator agent.

    Args:
        state: The current state of the multi-agent configuration.

    Returns:
        A dictionary containing the system prompt for the response generator agent.
    """
    response = response_generator_agent_system_prompt_generator_function(agent_name=state["agent_name"], 
                                                            agent_goal=state["agent_goal"], 
                                                            workflow_description=state["workflow_description"], 
                                                            tool_prompt=state["tool_prompt"], 
                                                            llm=state["llm"])
    return {"system_prompt_response_generator_agent": response}

def system_prompt_build_critic_agent(state: MultiAgentConfigurationState):
    """
    Builds the system prompt for the critic agent.

    Args:
        state: The current state of the multi-agent configuration.

    Returns:
        A dictionary containing the system prompt for the critic agent.
    """
    response = multi_agent_critic_system_prompt_generator_function(agent_name=state["agent_name"], 
                                                            agent_goal=state["agent_goal"], 
                                                            workflow_description=state["workflow_description"], 
                                                            tool_prompt=state["tool_prompt"], 
                                                            llm=state["llm"])
    return {"system_prompt_critic_agent": response}

def system_prompt_build_critic_replanner_agent(state: MultiAgentConfigurationState):
    """
    Builds the system prompt for the critic-based planner agent.

    Args:
        state: The current state of the multi-agent configuration.

    Returns:
        A dictionary containing the system prompt for the critic-based planner agent.
    """
    response = critic_based_planner_agent_system_prompt_generation_function(agent_name=state["agent_name"], 
                                                            agent_goal=state["agent_goal"], 
                                                            workflow_description=state["workflow_description"], 
                                                            tool_prompt=state["tool_prompt"], 
                                                            llm=state["llm"])
    return {"system_prompt_critic_based_planner_agent": response}

def system_prompt_build_replanner_agent(state: MultiAgentConfigurationState):
    """
    Builds the system prompt for the critic-based planner agent.

    Args:
        state: The current state of the multi-agent configuration.

    Returns:
        A dictionary containing the system prompt for the critic-based planner agent.
    """
    response = replanner_agent_system_prompt_generation_function(agent_name=state["agent_name"], 
                                                            agent_goal=state["agent_goal"], 
                                                            workflow_description=state["workflow_description"], 
                                                            tool_prompt=state["tool_prompt"], 
                                                            llm=state["llm"])
    return {"system_prompt_replanner_agent": response}


def merge(state: MultiAgentConfigurationState):
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
    outputs['SYSTEM_PROMPT_PLANNER_AGENT'] = state["system_prompt_planner_agent"]
    outputs['SYSTEM_PROMPT_RESPONSE_GENERATOR_AGENT'] = state["system_prompt_response_generator_agent"]
    outputs['SYSTEM_PROMPT_CRITIC_AGENT'] = state["system_prompt_critic_agent"]
    outputs['SYSTEM_PROMPT_CRITIC_BASED_PLANNER_AGENT'] = state["system_prompt_critic_based_planner_agent"]
    outputs['SYSTEM_PROMPT_REPLANNER_AGENT'] = state["system_prompt_replanner_agent"]
    outputs['SYSTEM_PROMPT_GENERAL_LLM'] = state["system_prompt_general_llm"]
    return {"MULTI_AGENT_SYSTEM_PROMPTS": outputs}

builder = StateGraph(MultiAgentConfigurationState)
builder.add_node("ExecutorAgent", system_prompt_build_executor_agent)
builder.add_node("PlannerAgent", system_prompt_build_planner_agent)
builder.add_node("ResponseGeneratorAgent", system_prompt_build_response_gen_agent)
builder.add_node("CriticAgent", system_prompt_build_critic_agent)
builder.add_node("CriticBasedPlannerAgent", system_prompt_build_critic_replanner_agent)
builder.add_node("ReplannerAgent", system_prompt_build_replanner_agent)
builder.add_node("GeneralAgent", system_prompt_build_general_agent)
builder.add_node("Merge", merge)

# Flow
builder.add_edge(START, "ExecutorAgent")
builder.add_edge(START, "PlannerAgent")
builder.add_edge(START, "ResponseGeneratorAgent")
builder.add_edge(START, "CriticAgent")
builder.add_edge(START, "CriticBasedPlannerAgent")
builder.add_edge(START, "ReplannerAgent")
builder.add_edge(START, "GeneralAgent")

builder.add_edge("ExecutorAgent", "Merge")
builder.add_edge("PlannerAgent", "Merge")
builder.add_edge("ResponseGeneratorAgent", "Merge")
builder.add_edge("CriticAgent", "Merge")
builder.add_edge("CriticBasedPlannerAgent", "Merge")
builder.add_edge("ReplannerAgent", "Merge")
builder.add_edge("GeneralAgent", "Merge")
builder.add_edge("Merge", END)
graph = builder.compile()


def planner_executor_critic_builder(agent_name, agent_goal, workflow_description, tool_prompt, llm):
    agent_config_resp = graph.invoke(input={
                                    'agent_name': agent_name,
                                    'agent_goal': agent_goal,
                                    'workflow_description': workflow_description,
                                    'tool_prompt': tool_prompt, 
                                    'llm': llm
                                })
    return {"MULTI_AGENT_SYSTEM_PROMPTS": agent_config_resp["MULTI_AGENT_SYSTEM_PROMPTS"]}
