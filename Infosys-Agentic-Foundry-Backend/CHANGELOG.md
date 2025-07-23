# Changelog


## [1.0.7]

### Changes
- **Recycle Bin Logic Improved:** Fixed the process so that an agent or tool is deleted from its original table before being inserted into the recycle bin, and similarly, during restore, it is first deleted from the recycle bin before being restored to the main table.
- **Markdown Files Listing Endpoints:** Added new API endpoints to list markdown files related to the project.


## [1.0.6]

### Changes
- **Updated Secrets Handler Module:** Introduced a new `secrets_handler.py` module to centralize the management of sensitive information such as API keys and other secrets. This enhancement improves both the security and maintainability of the Agentic Workflow as a Service project.
- **Added Secrets Endpoints:** Implemented new API endpoints to handle all secrets-related functionality, enabling secure storage, retrieval, and management of sensitive information.


## [1.0.5]

### Changes
- **Removed SQLite import statements:** Cleaned up codebase by eliminating unused SQLite imports following the migration to PostgreSQL.


## [1.0.4]

### Changes
- **Fixed upload document issue:** Resolved problems related to uploading documents within the framework.
- **Improved multi-agent export:** Fixed and enhanced the export functionality for multiple agents to ensure smoother setup and deployment.


## [1.0.3]

### Changes
- **New Agent Templates:**
  - **Multi-Agent (Planner & Executor):** Added a template featuring only planner and executor agents for streamlined multi-agent workflows.
  - **Multi-Agent (React & Critic):** Introduced a template with just a react agent and a critic agent, enabling focused evaluation and feedback cycles.
  - **Function Renaming:** Updated function names to reflect the migration from SQLite to PostgreSQL. Any references to "sqlite" in function names have been changed to "database" for clarity and accuracy.


## [1.0.2]

### Changes
- **Export Agent Functionality:** Users can now export any agent created within the framework. This allows agents to be easily set up and deployed on other machines.


## [1.0.1]

### Changes
- **Recycle Bin Feature:** Added a recycle bin for agents and tools. When users delete an agent or tool, it is now moved to the recycle bin instead of being permanently deleted. Admins can restore or permanently delete items from the recycle bin.


## [1.0.0] - Second Release

### Added
- **New Agent Templates:**
  - **Meta Agent (Supervisor Agent):** A template where a supervisor agent delegates tasks to worker agents.
  - **Planner Meta Agent:** A two-stage workflow where a planner node generates a plan, and a meta/supervisor agent executes each step.
- **Feedback Learning:** Agents (React and Multi-Agent) now learn from user feedback. Implemented a workflow requiring admin approval for feedback before it is used for training.
- **Tool Interrupt Support:** Added tool interrupt capability for React and Multi-Agent workflows for dynamic intervention.
- **Async/Await Refactoring:** Core functions now use `async`/`await` to handle multiple concurrent requests efficiently.
- **Improved Feedback Handling:** Enhanced the multi-agent system to better process and incorporate user feedback.
- **Telemetry & Tracing:**
  - Enabled OpenTelemetry to monitor agent activities and system performance for improved diagnostics, analytics, and framework-level debugging.
  - Integrated Arize Phoenix for detailed agent tracing and monitoring.
- **Evaluation & Metrics:**
  - Introduced evaluation metrics to assess agent performance using the "LLM as Judge" approach.
  - Added an API to trigger evaluations.
  - Implemented endpoints to expose evaluation data, including tool utilization and agent efficiency scores.


## [0.0.1] - First Release

### Initial Features
- **Tool Management:** Implemented functionality to create and onboard custom tools (Python functions) for LLM agents. Tools are saved in a database, making them reusable across multiple agents.
- **Agent Templates:**
  - **React Agent:** A template for a single agent that can reason and act to accomplish tasks.
  - **Multi-Agent:** A template for a team of agents using a Planner-Executor-Critic framework. Includes an optional "human-in-the-loop" mode where users can verify the generated plan and provide feedback for replanning before execution.
- **Memory:** Enabled simple memory for agents to maintain conversation history.

