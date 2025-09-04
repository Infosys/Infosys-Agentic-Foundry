# Release Notes

## Version 1.0.0 - May 30th, 2025

*   **Tool Management:** Introduced functionality to create, onboard, and manage custom tools (Python functions) for LLM agents, making them reusable. Users can write custom logic for tools to access uploaded file content.
*   **Agent Templates:** Released initial agent templates including:
    *   React Agent for single-task accomplishment.
    *   Multi-Agent system using a Planner-Executor-Critic framework, with an optional "Plan Verifier" mode.
*   **Memory & Interaction:** Implemented simple conversation memory for agents and enabled real-time interaction via chat for inference and task execution.
*   **File Integration:** Added support for file uploads, allowing agents to utilize file content through integrated tools.
*   **UI Enhancements:** Introduced live tracking for agent activities and provided access to documentation via a Help button.


## Version 1.1.0 - July 17th, 2025

*   **Admin Panel:** Launched a comprehensive Admin Panel with features for:
    *   User registration, User profile updates, and a recycle bin for deleted items.
    *   Evaluation Dashboard displaying evaluation results, tool utilization, and agent efficiency scores.
    *   Metric management: Allows admins to trigger evaluations using the "LLM as a Judge" approach.
    *   Feedback Management: Admins can review and approve user feedback before it is used for agent training.
*   **New Agent Templates:**
    *   **Meta Agent (Supervisor Agent):** Supervisor agent template which delegates tasks to worker agents.
    *   **Planner Meta Agent:** Two-stage workflow—first, a planner node generates a step-by-step plan; then, each step is executed sequentially by the meta/supervisor agent.
    *   **Planner-Executor Agent:** Template similar to Multiagent without Critic, with and without "Plan Verifier".
    *   **React Critic Agent:** Template similar to React introduced in version 1.0.0, with the addition of Critic.
*   **Agent Creation & Export:** Users can export the code for any agent, along with the tools used by agents, to run locally and modify as needed.
*   **Feedback Learning:** Agents (React and Multi-Agent) learn from user feedback to improve future responses, subject to admin approval.
*   **System Enhancements:**
    *   Added tool interrupt capability for both React Agent and Multi-Agent workflows, allowing dynamic intervention and correction during tool execution.
    *   Refactored core functions using `async/await` for scalability, and improved feedback handling in the multi-agent system.
*   **Telemetry & Tracing:**
    *   Enabled OpenTelemetry to monitor agent activities and system performance for improved diagnostics, analytics, and framework-level debugging.
    *   Integrated Arize Phoenix for detailed agent tracing and monitoring.
*   **Evaluation Metrics:** Introduced evaluation metrics to assess the performance and efficiency of AI agents, focusing on the "LLM as a Judge" approach.
*   **UI Updates:** Added new UI pages for updating users and managing the recycle bin.


## Version 1.2.0 - July 25th, 2025

*   **Code Architecture Modernization:** Refactored code using Object-Oriented Programming (OOP) principles, introduced modular service layers (AgentService, ToolService, and TagService), and implemented a repository pattern with database connection pooling for improved performance.
*   **Enhanced Agent Templates:** Streamlined Multi-Agent templates, adding a Planner & Executor configuration and a React & Critic setup for focused evaluation.
*   **Advanced Features:**
    *   Introduced Ground Truth Based Evaluation for precise agent output assessment.
    *   Integrated Knowledge Base support for React agents.
*   **Database & Connectivity:** Enhanced Data Connector functionality to support multiple databases (SQLite, PostgreSQL) and updated existing functions for PostgreSQL migration.
*   **Security & Management (Vault):** Developed a centralized Secrets Handler module for secure management of sensitive information, including public and private secrets.
*   **Monitoring Improvements:** Enhanced telemetry with trace ID fixes and session tracking, and modularized chat-related logic into dedicated service layers.
*   **Admin & UI Refinements:** Improved Recycle Bin logic, added API endpoints for listing markdown files, introduced new UI pages for Ground Truth and Secrets, and resolved various defects across admin screens and tool mapping.


## Version 1.3.0 – July 31st, 2025

*   **Continued Modularization:** Further modularized key functionalities, including feedback learning and evaluation metrics, for improved maintainability and integration into agent export.
*   **Configuration:** Introduced configurable CORS origins and SBERT model paths via environment variables.
*   **System Stability:** Addressed public/private key management issues.
*   **Development & Integration:** Performed legacy code cleanup and unified API access through FastAPI integration.
*   **UI & Agent Fixes:** Released Chat UI Version 2.0 (Inference page design with new look), added a new Data Connectors page, corrected API endpoints due to modularity changes, and resolved issues on agent screens related to Meta/Planner Meta Agents, System Prompts, and Evaluation metrics menu item changes.
*   **Inference Output Format Restructuring:** Restructured API endpoints' inference output to include a list of all tools invoked during the agent inference call along with their corresponding outputs.

