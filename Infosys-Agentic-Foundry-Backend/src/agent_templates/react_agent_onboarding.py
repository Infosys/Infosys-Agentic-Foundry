# © 2024-25 Infosys Limited, Bangalore, India. All Rights Reserved.
from langchain.prompts import PromptTemplate
from langchain_core.output_parsers.string import StrOutputParser
from src.prompts.prompts import react_system_prompt_generator
from telemetry_wrapper import logger as log

async def react_system_prompt_gen_func(agent_name, agent_goal, workflow_description, tool_prompt, llm):
    react_system_prompt_template = PromptTemplate.from_template(react_system_prompt_generator)
    react_system_prompt_gen = react_system_prompt_template | llm | StrOutputParser()
    log.info(f"Generating React System Prompt for agent {agent_name}")
    react_system_prompt = await react_system_prompt_gen.ainvoke({"agent_name": agent_name,
                                "agent_goal": agent_goal,
                                "workflow_description": workflow_description,
                                "tool_prompt": tool_prompt})
    log.info(f"Generated React System Prompt for agent {agent_name}")
    return react_system_prompt
