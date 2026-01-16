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


The system supports multiple types of agent templates, each offering different capabilities suited for specific use cases:

1. [React Agent](reactAgent.md): The ReAct (Reasoning and Acting) agent combines reasoning traces with action execution.

2. [React Critic Agent](reactCritic.md): An enhanced React Agent with dual system prompts for self-critique and improved output quality.

3. [Multi Agent](multiAgent.md): The multi agent follows the Plan and Execute paradigm, enabling collaboration between specialized agents.

4. [Planner Executor Agent](PlannerExecutor.md): Implements the Planner-Executor-Critic workflow with a more granular system prompt structure.

5. [Meta Agent](metaAgent.md): An agent supervisor responsible for routing to individual agents and managing high-level orchestration.

6. [Meta Planner Agent](PlannerMeta.md): An advanced orchestrator using multiple system prompts for robust and adaptive agent-based workflows.

7. [Hybrid Agent](HybridAgent.md): Combines features from multiple agent types, enabling flexible workflows that leverage both reasoning and execution capabilities for complex tasks.

---