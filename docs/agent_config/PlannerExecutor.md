# Planner-Executor Agent Configuration

The **Planner-Executor Agent** uses the same onboarding and configuration steps as the multi agent, based on the `Planner-Executor-Critic` paradigm. The main difference is in the system prompt configuration.

---

### **Planner-Executor Agent Onboarding**

Follow the onboarding steps in [Multi Agent Onboarding](./multiAgent.md#multi-agent-onboarding):

1. **Select Template**: Choose the Planner-Executor Agent template.
2. **Select Tools**: Select tools for the agent's tasks.
3. **Agent Name**: Provide a name for your agent.
4. **Agent Goal**: Define the agent's main objective.
5. **Workflow Description**: Give instructions and guidelines for task execution.
6. **Model Name**: Select the model for generating system prompts.

**System Prompts**

The Planner-Executor Agent generates five system prompts for the planner, executor, and critic components, offering detailed guidance for each workflow stage.

---

### **Agent Updation**

Agent updation is similar to [React Agent Updation](reactAgent.md#agent-updation).

### **Agent Deletion**

Agent deletion is similar to [React Agent Deletion](reactAgent.md#agent-deletion).

!!! warning "Important"
    Only the original creator of the agent can update or delete it. Other users cannot modify or remove these resources.
