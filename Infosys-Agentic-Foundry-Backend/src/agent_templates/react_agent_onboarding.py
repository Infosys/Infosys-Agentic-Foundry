# © 2024-25 Infosys Limited, Bangalore, India. All Rights Reserved.
from langchain.prompts import PromptTemplate
from langchain_core.output_parsers.string import StrOutputParser
from src.prompts.prompts import react_system_prompt_generator

def react_system_prompt_gen_func(agent_name, agent_goal, workflow_description, tool_prompt, llm):
    react_system_prompt_template = PromptTemplate.from_template(react_system_prompt_generator)
    react_system_prompt_gen = react_system_prompt_template | llm | StrOutputParser()

    react_system_prompt = react_system_prompt_gen.invoke({"agent_name": agent_name, 
                                "agent_goal": agent_goal, 
                                "workflow_description": workflow_description, 
                                "tool_prompt": tool_prompt})    
    return react_system_prompt
