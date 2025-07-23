# © 2024-25 Infosys Limited, Bangalore, India. All Rights Reserved.
from langchain.prompts import PromptTemplate
from langchain_core.output_parsers.string import StrOutputParser
from src.prompts.prompts import meta_agent_system_prompt_generator_prompt
from telemetry_wrapper import logger as log

async def meta_agent_system_prompt_gen_func(agent_name, agent_goal, workflow_description, worker_agents_prompt, llm):
    """Generates a single system prompt for a standard meta-agent."""
    meta_agent_system_prompt_generator_prompt_template = PromptTemplate.from_template(meta_agent_system_prompt_generator_prompt)
    meta_agent_system_prompt_generator = meta_agent_system_prompt_generator_prompt_template | llm | StrOutputParser()

    meta_agent_system_prompt = await meta_agent_system_prompt_generator.ainvoke({"agent_name": agent_name,
                                            "agent_goal": agent_goal,
                                            "workflow_description": workflow_description,
                                            "worker_agents_prompt": worker_agents_prompt})
    meta_agent_system_prompt = meta_agent_system_prompt
    log.info(f"Generated meta agent system prompt for agent '{agent_name}'")
    return meta_agent_system_prompt
