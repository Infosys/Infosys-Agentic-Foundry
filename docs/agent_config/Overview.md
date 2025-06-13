# Agent Configuration

The **Agent Configuration** is a core functionality in agentic framework that enables users to **create, update, and delete agents**.
## What is an Agent?

An **agent** is composed of three core components:

1. **Large Language Model (LLM)**
    The core reasoning engine that drives the agent's behavior.

2. **Tools**
    A set of Python functions (onboarded as tools) that the agent can call to perform actions such as querying data, generating content, or interacting with systems.

3. **Prompt (Workflow Description)**
    A detailed set of instructions that guides the agent's decisions and actions.

--- 


## Agent Configuration Overview

Agent configuration involves using a reusable, template-driven setup that allows creation of agents with specific **roles**, **goals**, and **personas**.

--- 


## Templates Overview

The system supports three types of agent templates and each template offers different capabilities, suited for specific use cases:

1. [React Agent](reactAgent.md): The ReAct (Reasoning and Acting) agent combines reasoning traces with action execution.

2. [Multi Agent](multiAgent.md): The multi agent follows the Plan and Execute paradigm.

3. [Meta Agent](metaAgent.md): An agent supervisor is responsible for routing to individual agents.

---