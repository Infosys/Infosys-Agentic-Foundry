# Changelog


## Release [2.1.0] - (Jul 25, 2025)

### New Features & Enhancements

#### Code Architecture & Modernization
- **OOP Refactoring:** Complete restructuring of the codebase following Object-Oriented Programming principles for better maintainability and scalability.
- **Service Layer Implementation:** Introduced modular service layers including AgentService, ToolService, and TagService to encapsulate business logic.
- **Repository Pattern:** Created dedicated repositories for each database table to manage data access and persistence cleanly.
- **Database Connection Pooling:** Replaced repeated database connections with a connection pool for improved performance and resource management.

#### Enhanced Agent Templates
- **Multi-Agent (Planner & Executor):** Added streamlined template with only planner and executor agents.
- **Multi-Agent (React & Critic):** Introduced template with react agent and critic agent for focused evaluation and feedback cycles.

#### Advanced Features
- **Ground Truth Based Evaluation:** New evaluation mechanism comparing agent outputs against predefined ground truth data.
- **Knowledge Base Integration:** Added support for integrating knowledge base with React agent for accessing stored information.

#### Database & Connectivity
- **Data Connector for Multiple Databases:** Users can connect to SQLite, PostgreSQL for specific use cases.
- **PostgreSQL Migration:** Updated function names and removed SQLite references following migration to PostgreSQL.

#### Security & Management
- **Secrets Handler Module:** Centralized management of sensitive information with secure storage, retrieval, and management capabilities.
- **Public Secrets Handler:** Users can create public secrets accessible by all users, stored in encrypted format.

#### Monitoring & Performance
- **Enhanced Telemetry:** Fixed trace ID recording issues and implemented session tracking for improved monitoring and diagnostics.
- **Chat Service Integration:** Modularized chat-related logic with dedicated service and repository layers.

#### Administrative Tools
- **Improved Recycle Bin Logic:** Enhanced deletion/restoration process between main tables and recycle bin.
- **Markdown Files Listing:** Added API endpoints to list project-related markdown files.



## Release [2.0.0] - (Jul 23, 2025)

### New Features & Enhancements

#### Admin Panel
- **User Registration:** Dedicated tab for registering new users.
- **User Update:** Functionality to update user password or profile.
- **Recycle Bin:** View and manage deleted agents or tools.
- **Evaluation Dashboard:** Displays evaluation results, including data used for evaluation, tool utilization scores, and agent efficiency scores.
- **Metrics & Evaluation:** Admins can trigger evaluations using the "LLM as a Judge" approach.
- **Feedback Management:** Admins can review and approve user feedback before it is used for agent training.

#### New Agent Templates
- **Meta Agent (Supervisor Agent):** Template where a supervisor agent delegates tasks to worker agents.
- **Planner Meta Agent:** Two-stage workflow—planner node generates a step-by-step plan, then each step is executed sequentially by the meta/supervisor agent.
- **Planner-Executor Agent:** Added templates with and without human-in-the-loop.
- **React Critic Agent:** New template for agent reasoning and critique.

#### Agent Creation & Export
- Users can create agents on the server and export code for any agent to run locally and modify as needed.

#### Feedback Learning
- Agents (React and Multi-Agent) now learn from user feedback to improve future responses. All feedback is subject to admin approval via the Admin Panel before being used for training.

#### Tool Interrupt Support
- Added tool interrupt capability for React Agent and Multi-Agent workflows, allowing dynamic intervention and correction during tool execution.

#### Async/Await Refactoring
- Refactored core functions to use async/await for efficient handling of concurrent requests and improved scalability.

#### Improved Feedback Handling
- Enhanced multi-agent system to better process and incorporate user feedback during task execution.

#### Telemetry & Tracing
- Enabled OpenTelemetry to monitor agent activities and system performance for diagnostics, analytics, and debugging.
- Integrated Arize Phoenix for detailed agent tracing and monitoring.

#### Evaluation Metrics
- Introduced evaluation metrics to assess performance and efficiency of AI agents, focusing on the "LLM as Judge" approach.



## Release [1.0.0] - (May 30, 2025)

### Initial Features
- **Tool Management:** Implemented functionality to create and onboard custom tools (Python functions) for LLM agents. Tools are saved in a database, making them reusable across multiple agents.
- **Agent Templates:**
  - **React Agent:** A template for a single agent that can reason and act to accomplish tasks.
  - **Multi-Agent:** A template for a team of agents using a Planner-Executor-Critic framework. Includes an optional "human-in-the-loop" mode where users can verify the generated plan and provide feedback for replanning before execution.
- **Memory:** Enabled simple memory for agents to maintain conversation history.
- **Inference & Chat:** Users can interact with agents via chat, enabling real-time inference and task execution.
- **File Upload & Tool Integration:** Users can upload files to the server, and agents can utilize the file content through integrated tools.

