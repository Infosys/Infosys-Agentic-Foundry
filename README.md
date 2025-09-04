# Infosys Agentic Foundry: An Open-Source Solution for Customizable Pro-Code AI Agents

**Agentic Foundry** is a comprehensive, open-source framework designed to empower developers to create, configure, and deploy customizable AI agents with minimal coding effort. It provides a robust platform for building intelligent systems by offering customizable templates and a powerful set of tools, streamlining the entire agentic workflow development process.

The platform facilitates the export of agents as standalone code or groups of agents, allowing them to be embedded into other workflows or hosted as separate applications with their own UI. The Infosys Agentic Service is successfully deployed on Azure Kubernetes Services, ensuring enterprise-grade scalability and reliability.

---

## Key Features & Capabilities

### 1. Simplified Agent & Tool Management

- **Easy Pro-Code Agent Creation**: Automates setup based on provided tool logic and workflow definitions.
- **Easy Agent & Tool Management**: Seamless onboarding, updating, and removal of agent components and tools.
- **In-Platform Customization**: Customize tools, workflows, and control logic without external IDEs or redeployments.
- **Reusable Components**: Modular, self-contained agents and tools for consistency and faster development.
- **Tools Configuration**:
  - Agents use external functions/actions (tools) for tasks beyond language generation.
  - Secure connection management for adapters and databases.
  - Tools can be created using natural language queries.

---

### 2. Advanced Agent Templates

Agentic Foundry supports three primary agent templates:

- **React Agent**:
  - Combines reasoning traces with action execution.
  - Ideal for precise, efficient single-task operations.

- **Multi Agent**:
  - Follows Planner-Executor-Critic paradigm.
  - Supports automated and Human-in-the-Loop (HITL) modes.

- **Meta Agent**:
  - Acts as a Supervisor Agent.
  - Dynamically selects and orchestrates worker agents.
  - Aggregates responses for a consolidated answer.

> _Additional patterns supported..._

---

### 3. Human-in-the-Loop (HITL) & Feedback Mechanisms

- **Human-in-the-Loop (HITL)**:
  - Manual checkpoints for human input and oversight.
  - Core to Multi Agent workflows.

- **Feedback-Driven Learning**:
  - Continuous agent improvement via structured/unstructured feedback.
  - Admin interface for feedback management.

- **Tool Interrupt**:
  - Step-by-step review and approval of tool calls.
  - Enhances transparency and control.

---

### 4. Robust Evaluation Frameworks

#### Ground Truth-Based Evaluation

- Compares agent output to a golden dataset.
- Metrics:
  - SBERT Similarity
  - TF-IDF Cosine Similarity
  - Jaccard Similarity
  - ROUGE (ROUGE-1, ROUGE-L)
