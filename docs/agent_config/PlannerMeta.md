**Meta Planner Agent** acts as the central orchestrator, coordinating multiple specialized agents (like ReAct, Multi-Agent, or hybrids) to solve complex queries. It extends the Meta Agent by using a multi-system-prompt approach for finer control and supervision.

---

## **Meta Planner Agent Onboarding**

The onboarding steps are the same as the Meta Agent. See [Meta Agent Onboarding](./metaAgent.md#meta-agent-onboarding):

1. **Select Template**: Choose the Meta Planner Agent template.
2. **Select Agents**: Select worker agents (e.g., React, Multi-Agent) to be managed.
3. **Agent Name**: Provide a name for your meta planner agent.
4. **Agent Goal**: Define the main objective.
5. **Workflow Description**: Give instructions and guidelines for orchestration and task delegation.
6. **Model Name**: Select the model for generating system prompts.

---

**System Prompts**

The Meta Planner Agent uses three system prompts:

- **Meta Planner System Prompt**: Guides high-level planning and query decomposition.
- **Meta Responser System Prompt**: Directs aggregation and synthesis of responses from worker agents.
- **Meta Supervisor System Prompt**: Oversees execution, coordination, and quality control.

---

## **Agent Updation**

To update the agent (add/remove worker agents, update workflow), follow the steps in [Meta Agent Updation](./metaAgent.md#agent-updation).

---

## **Agent Deletion**

See [Meta Agent Deletion](./metaAgent.md#agent-deletion) for deletion steps and permission notes.

!!! warning "Important"
    Only the original creator of the agent can update or delete it. Other users cannot modify or remove these resources.
