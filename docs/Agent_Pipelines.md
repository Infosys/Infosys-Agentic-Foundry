# Agent Pipelines

The **Agent Pipelines** feature provides a visual pipeline builder that allows users to create, configure, and manage multi-agent workflows using an intuitive drag-and-drop canvas interface. This enables the orchestration of multiple agents with conditional logic, input handling, and output management.

---

## Overview

Agent Pipelines allow you to visually design complex workflows by connecting multiple agents together. Instead of manually coordinating agent calls, you can create a pipeline that automatically routes data between agents based on your defined flow.

**Key Capabilities:**

- `Visual Workflow Design`: Drag-and-drop interface for building agent workflows
- `Multi-Agent Orchestration`: Connect multiple agents in sequence or parallel
- `Conditional Branching`: Route data based on conditions and agent outputs
- `Input/Output Management`: Define pipeline inputs and structure final outputs
- `Reusable Pipelines`: Save and reuse pipeline configurations

---

## Pipeline Components

### Canvas

The canvas is the main workspace where you design your pipeline. It provides:

- `Drag-and-Drop`: Place nodes by dragging them from the sidebar onto the canvas
- `Pan & Zoom`: Navigate large pipelines with zoom controls and canvas panning
- `Grid Alignment`: Nodes snap to a grid for clean visual organization
- `Canvas Controls`: Zoom in/out, fit view, and clear canvas buttons

---

### Node Types

Pipelines are built using four types of nodes:

**1. Input Node**

The **Input Node** defines the entry point of your pipeline and specifies what data the pipeline expects to receive.

- Defines a single input key: `query`
- Supports different data types: string, integer, JSON
- Only one Input node is allowed per pipeline
- Connects to Agent or Condition nodes

**Configuration:**

| Property | Description |
|----------|-------------|
| Node Name | Custom name for the input node |
| Input Keys | List of expected input parameters with their types |

---

**2. Agent Node**

The **Agent Node** represents an agent that will be executed as part of the pipeline workflow.

- Select from available agents in IAF
- Configure which inputs the agent can access
- Multiple Agent nodes can be added to a pipeline
- Receives data from Input, other Agents

**Configuration:**

| Property | Description |
|----------|-------------|
| Node Name | Custom name for the agent node |
| Agent | Select an agent from the dropdown |
| Accessible Inputs | Choose which pipeline inputs and agent outputs this agent can access |

**Accessible Inputs Options:**

- `All Inputs`: Agent has access to all pipeline inputs and outputs from other agents
- `Specific Inputs`: Select individual inputs (from Input node) and agent outputs to make available

---

**3. Condition Node**

The **Condition Node** enables conditional branching in your pipeline based on expressions.

- Define conditions to evaluate agent outputs
- Route data to different paths based on results
- Supports multiple output connections for branching logic
- Useful for error handling, validation, or decision trees

**Configuration:**

| Property | Description |
|----------|-------------|
| Node Name | Custom name for the condition node |
| Condition | Condition to evaluate, written in plain English (e.g., "If the status of result is equal to success, then...") |

---

**4. Output Node**

The **Output Node** defines the final output of your pipeline.

- Specifies the output schema for the pipeline
- Multiple Output nodes are allowed for different output paths
- Receives data from Agent or Condition nodes

**Configuration:**

| Property | Description |
|----------|-------------|
| Node Name | Custom name for the output node |
| Output Schema | JSON schema defining the structure of the output (optional) |

---

## Connections

Connections (edges) define the flow of data between nodes in your pipeline.

**Creating Connections**

1. Click on the output point of a source node
2. Drag to the input point of a target node
3. Release to create the connection

**Connection Rules**

| From ↓ / To → | Input | Agent | Condition | Output |
|---------------|-------|-------|-----------|--------|
| **Input** | ❌ | ✅ | ✅ | ✅ |
| **Agent** | ❌ | ✅ | ✅ | ✅ |
| **Condition** | ❌ | ✅ | ❌ | ✅ |
| **Output** | ❌ | ❌ | ❌ | ❌ |

- `Input nodes` can connect to Agent, Condition, or Output nodes
- `Agent nodes` can connect to other Agents, Conditions, or Output nodes
- `Condition nodes` can connect to Agent or Output nodes (not to other Conditions)
- `Output nodes` cannot have outgoing connections

---

## Properties Panel

When you click on a node, the Properties Panel opens on the side, allowing you to configure the selected node.

The panel displays:

- `Node Name`: Editable name for the node
- `Node Type`: The type of node (Input, Agent, Condition, Output)
- `Node ID`: Auto-generated unique identifier
- `Type-specific settings`: Configuration options based on node type

---

## Saving a Pipeline

To save your pipeline:

1. Ensure you have at least one `Input node` and one `Agent node` with a selected agent
2. Click the `Save` button
3. Enter a `Pipeline Name` (required)
4. Add an optional `Description`
5. Click `Save` to store the pipeline

**Save Requirements:**

- At least one Input node
- At least one Agent node with a selected agent
- Pipeline name is required

---

**Example Pipeline**

Here's an example of a simple research pipeline:

```
┌─────────┐     ┌──────────────┐     ┌─────────────┐     ┌────────┐
│  Input  │ ──► │ Research     │ ──► │ Writer      │ ──► │ Output │
│  Node   │     │ Agent        │     │ Agent       │     │ Node   │
└─────────┘     └──────────────┘     └─────────────┘     └────────┘
```

1. `Input Node`: Receives `query` (string) and `context` (JSON)
2. `Research Agent`: Searches for information based on the query
3. `Writer Agent`: Takes research output and generates a formatted response
4. `Output Node`: Returns the final structured response

---

**Using Pipelines in Chat Inference**

In the `Chat Inference` tab, you can select a pipeline as the agent type and interact with it just like any other agent template. This allows you to test and validate your multi-agent workflows directly from the chat interface.

---

!!! tip "Best Practices"

    1. **Name your nodes clearly**: Use descriptive names that indicate each node's purpose
    2. **Start simple**: Begin with a linear pipeline before adding conditions
    3. **Test incrementally**: Save and test your pipeline as you build it
    4. **Use conditions wisely**: Add conditional logic for error handling and validation
    5. **Document your pipelines**: Add descriptions when saving to help others understand the workflow
