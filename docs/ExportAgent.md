## Agent Export Functionality

Agentic Foundry allows you to export complete agent configurations, including agent data, tools, and required static files. This makes it easy to back up, migrate, or redeploy agents across different environments.

Exporting is done via a backend API endpoint, which takes an Agent ID and generates a folder containing all necessary backend and frontend code for the agent. You can select agents and click 'Export' to download this folder. The export process ensures that all dependencies, configurations, and scripts are included, so the agent can be redeployed without manual setup.

Exported agents are useful for:

- Backing up agent configurations and logic
- Migrating agents between development, staging, and production environments
- Sharing agent setups with other teams or organizations
- Rapidly redeploying agents after infrastructure changes

---

## Exporting Agents

**Key Features:**

- **SSE Streaming**: The exported agents include Server-Sent Events (SSE) support for real-time inference streaming, enabling pipeline-based processing and live response streaming
- **Validator Support**: Built-in validator configurations are included in the export, ensuring workflow integrity and data validation across agent operations
- **Tool Dependency Export**: All tool dependencies and base requirements are automatically packaged with the agent export, ensuring complete portability

All agent types can be exported, including React, React Critic, Planner Executor Critic, Planner Executor, Meta, and Planner Meta. The export includes both backend and frontend code, organized for easy redeployment.

The backend is provided as a folder containing all logic, configuration, and scripts needed for the agent. This folder includes configuration files, tool definitions, a Dockerfile for containerization, environment variables, and documentation. All dependencies are listed in requirements.txt for easy installation.

The frontend includes the source code, public assets, deployment configuration (such as YAML files for Kubernetes), and environment files. This ensures the user interface and all related assets are ready for deployment.

A typical exported folder structure includes:

- **Agent_Backend**: Contains the backend Python package (`exportagent`), configuration files, tool definitions with their dependencies, validator configurations, SSE streaming setup, Dockerfile for containerization, environment variables, and all scripts needed for agent operation. The wheel file is listed in `requirements.txt` so that installing dependencies will automatically install the agent backend along with all tool dependencies and base requirements.
- **Agent_Frontend**: Contains the frontend source code, public assets, deployment configuration, SSE client implementations, and all files required to run the agent's user interface.

This structure allows teams to:

- Install the backend in any Python environment using pip and requirements.txt
- Deploy the frontend using standard web deployment tools
- Use Docker for containerized deployments

The export process is designed to be comprehensive and portable, supporting both cloud and on-premises deployments. It simplifies agent management and ensures consistency across environments.
