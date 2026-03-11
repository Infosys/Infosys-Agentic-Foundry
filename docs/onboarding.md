# Sample Data Auto-Onboarding

## Overview

The Sample Data Insertion module automatically reads and loads sample tools, agents, and pipelines from the configuration file into the database when the server starts. This enables quick setup and testing without manual data entry.

**Key Features:**

- **Automatic Loading** — Sample data is inserted on server startup
- **No Code Changes Required** — Simply edit the JSON configuration file
- **Supports Multiple Resources** — Tools, Agents, and Pipelines can all be pre-loaded

---

## Configuration File

**File Location:** `src/onboard/sample_data.json`

To add new sample tools, agents, or pipelines, edit this JSON file. No code modifications are needed—just add your data to the appropriate list (tools, agents, or pipelines).

---

## File Structure

The `sample_data.json` file contains three main sections:

### 1. Tools

Define reusable tools that agents can use during execution.

**Structure:**

```json
{
    "tools": [
        {
            "tool_name": "",
            "tool_description": "",
            "code_snippet": ""
        },
        {
            "tool_name": "",
            "tool_description": "",
            "code_snippet": ""
        }
    ]
}
```

**Fields:**

- `tool_name` — Unique identifier for the tool
- `tool_description` — Brief description of what the tool does
- `code_snippet` — Python code that implements the tool functionality

---

### 2. Agents

Define agents with specific configurations and behaviors.

**Structure:**

```json
{
    "agents": [
        {
            "agentic_application_name": "",
            "agentic_application_description": "",
            "agentic_application_workflow_description": "",
            "agentic_application_type": "",
            "system_prompt": {},
            "tool_names": [],
            "validation_criteria": [],
            "welcome_message": ""
        }
    ]
}
```

**Fields:**

- `agentic_application_name` — Unique name for the agent
- `agentic_application_description` — High-level description of the agent's purpose
- `agentic_application_workflow_description` — Detailed workflow explanation
- `agentic_application_type` — Agent template type (e.g., `react_agent`, `meta_agent`, `hybrid_agent`)
- `system_prompt` — Configuration object for the agent's system prompt
- `tool_names` — Array of tool names the agent can access
- `validation_criteria` — Array of validation rules for the agent
- `welcome_message` — Initial message displayed when the agent starts

---

### 3. Pipelines

Define multi-node workflows that orchestrate agents and data flow.

**Structure:**

```json
{
    "pipelines": [
        {
            "pipeline_name": "",
            "pipeline_description": "",
            "always_onboard": true,
            "pipeline_definition": {
                "nodes": [
                    {
                        "node_id": "",
                        "node_type": "",
                        "node_name": "",
                        "position": { "x": 100, "y": 100 },
                        "config": {
                            "input_schema": {
                                "query": { "type": "string", "raw": null }
                            },
                            "description": {
                                "query": { "text": "The user's chat message" }
                            }
                        }
                    },
                    {
                        "node_id": "",
                        "node_type": "",
                        "node_name": "",
                        "position": { "x": 300, "y": 100 },
                        "config": {
                            "agent_name": "",
                            "tool_verifier": false,
                            "plan_verifier": false,
                            "accessible_inputs": { "input_keys": ["all"] }
                        }
                    },
                    {
                        "node_id": "",
                        "node_type": "",
                        "node_name": "",
                        "position": { "x": 500, "y": 100 },
                        "config": {
                            "output_schema": {
                                "message": "text goes in this place",
                                "code_snippet": "code snippet goes in this place"
                            }
                        }
                    }
                ],
                "edges": [
                    {
                        "edge_id": "",
                        "source_node_id": "",
                        "target_node_id": ""
                    },
                    {
                        "edge_id": "",
                        "source_node_id": "",
                        "target_node_id": ""
                    }
                ]
            }
        }
    ]
}
```

**Pipeline Fields:**

- `pipeline_name` — Unique identifier for the pipeline
- `pipeline_description` — Description of the pipeline's purpose
- `always_onboard` — Boolean flag to control automatic onboarding
- `pipeline_definition` — Object containing nodes and edges

**Node Configuration:**

- `node_id` — Unique identifier for the node
- `node_type` — Type of node (e.g., `input`, `agent`, `output`)
- `node_name` — Display name for the node
- `position` — X/Y coordinates for visual representation
- `config` — Node-specific configuration (schema, agent settings, etc.)

**Edge Configuration:**

- `edge_id` — Unique identifier for the connection
- `source_node_id` — ID of the source node
- `target_node_id` — ID of the destination node

---

## Usage

1. **Edit Configuration** — Open `src/onboard/sample_data.json`
2. **Add Your Data** — Insert tools, agents, or pipelines into the respective arrays
3. **Start Server** — The onboarding module automatically loads the data on startup
4. **Verify** — Check the database or UI to confirm your sample data was loaded

!!! tip "Best Practice"
    Keep your sample data organized and well-documented. Use clear naming conventions and descriptions to make the data easy to understand and maintain.

!!! warning "Important"
    Ensure all referenced tools exist before creating agents that depend on them. Pipelines should reference valid agent names.

---
