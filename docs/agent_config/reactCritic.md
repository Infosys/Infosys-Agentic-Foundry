The **React Critic Agent** builds on the React Agent by adding a dual system prompt for improved self-critique and output quality. All onboarding and configuration steps are the same as the React Agent, except for the system prompt.

---

### **React Critic Agent Onboarding**

Follow the onboarding steps in [React Agent Onboarding](./reactAgent.md#react-agent-onboarding). The only difference is that the React Critic Agent generates two system prompts during setup:

1. **Executor Agent System Prompt**: Guides the agent's reasoning and actions (same as React Agent).
2. **Critic Agent System Prompt**: Adds critical evaluation, reviewing and refining the agent's reasoning, actions, and outputs.

---

### **Agent Updation**

To update the agent (e.g., add/remove tools, update workflow), follow the same steps as in [React Agent Updation](./reactAgent.md#agent-updation).

---

### **Agent Deletion**

See [React Agent Deletion](./reactAgent.md#agent-deletion) for deletion steps and permission notes.

!!! warning "Important"
    Only the original creator of the agent can update or delete it. Other users cannot modify or remove these resources.
