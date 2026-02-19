# Release Notes

## Version 1.7.0 - January 2026

### Features

* **Agent Pipelines**
Introduced agent pipeline feature for chaining multiple agents to create deterministic workflows.

* **Selective Tool Interrupt**
Enabled selective tool interruption for agent templates (React, React Critic, Planner Executor, Planner Executor Critic, Meta, and Meta Planner).
Expanded support to include both tools and agents.

* **Meta & Meta Planner**
Added plan verifier for Planner Meta agent template.
Enabled validator support for Meta and Planner Meta agents.
Enabled SSE streaming for Meta and Planner Meta agent responses.
Meta and Meta Planner can now bind React Critic (RC) and Planner Executor (PE) worker agents (previously restricted to React and Planner-Executor-Critic).

* **Hybrid Agent**
Enabled SSE streaming for hybrid agent template.

### Enhancements

* **Chat & UX**
Plans are displayed for planner agents even after SSE steps complete and regardless of plan verifier toggle.
Display timestamp for all user queries.
For Meta and Planner Meta agents, feedback buttons are now shown for the final response.

* **Export Agent**
Enabled SSE streaming for export agent inference.
Introduced validator support within export agent workflows.
Added ability to export agents along with tool dependencies and base requirements.
Updated and improved inference and export endpoints for consistency.
Reduced image sizes during export and trimmed requirements/dependency packages.
Removed unused imports and integrated new response time logic.

* **Tools & Admin**
Tools saved as files on server during onboarding/update; supports update, delete, and restore aligned with DB logic.
Admins can view installed packages, find missing dependencies referenced by older tools, and list pending modules needed for new tools (module name, tool code, user email, timestamp).

* **Database & TTL**
All database names configurable via .env.
Modified logic for restoring long-term memory records in TTL system (fixed previous error during restore).
MCP servers have recycle bin with TTL on deletions; endpoint to restore MCP servers from recycle bin items.
Detect and display unused MCP servers in the unused tab on Admin page.

* **Evaluation & Feedback**
Persist evaluation and validation feedback (like/dislike/regenerate) for chat inferences to database.

### Fixes

* Resolved UI display issues and fixed feedback reset in plan verifier.
* Fixed epoch handling in React Critic and Planner-Executor-Critic templates.
* Resolved infinite loop in evaluation flow.
* Fixed response time calculation for all agent templates.
* Added exception handling to manage SBERT model connection failures.
* Fixed Ground Truth page to display toast message for streaming response errors instead of leaving screen in idle state.

## Version 1.6.0 - December 18, 2025
Everyone Release Notes – 1.6.0
 
### Features
* Live Steps with Streaming (SSE)
Added Server-Sent Events (SSE) for real-time step-by-step execution displayed in chat when a query is sent (LangChain-based agent templates).
Users can click on each step for a detailed view.
* Validators Framework
Users can now create validators similar to tools and map them to agents during onboarding or updates. Agent responses are validated internally when a validator is linked. Added Validator toggle in the chat screen to apply validators for that agent.
* Context Agent (@) in Chat
Introduced a new “@” button to add a context agent alongside the main agent. Context agent learns from main agent’s queries and responses for improved contextual understanding.
* Agent Verifier Toggle
Added agent verifier toggle for Meta and Meta Planner templates in chat, similar to tool verifier for other templates.
* Grafana Dashboard Integration
New header button to open Grafana dashboard in a separate tab.

### Enhancements
* File Upload Enhancements
Revamped file uploads section with a collapsible folder structure for better readability.
* Evaluation Enhancements
Added support for running online evaluations for Meta and Planner Meta agents, enabling real-time quality assessment of agent responses.
* Agent Enhancements
Updated React Critic Agent to include tool metadata for better context awareness.
* Data Connector Enhancements
MongoDB insert operation restricted to single mode.
* Performance & Reliability
    * Enhanced TTL cleanup logic with configurable RECYCLE_BIN_RETENTION_DAYS.
    * Implemented permanent deletion for old checkpoint records.
    * Evaluation records now saved to the database in the background for smoother and faster user experience.
    * Decoupled model dependencies from tool validation (removed hardcoded gpt-4o).
    * Enabled passing updated tool context to response generator for improved response quality during tool interrupt.

### Fixes
* Added confirmation popup on Delete of chat.
* Canvas hidden for older queries.
* Applied DAST & SAST related fixes across UI and backend.
* Corrected “created by” key to return username instead of email.
 
 
## Version 1.5.3 – November 17, 2025
* Introduced a new screen which provides a comprehensive methodology for measuring the reliability and resilience of AI agents through systematic evaluation of response consistency and robustness against challenging inputs.
* Enhanced functionality with security fixes, updated configurations, and GitHub push support (requires environment variable configurations in UI).
* Added support for consistency and robustness checks for exported agents.
* Added a new Hybrid Agent template, which is a pure Python-based template, with advanced capabilities present in other templates.
* Data Lifecycle Management
* Implemented Time-To-Live (TTL) for automatic cleanup of unused tools/agents.
* Fixed SQL injection vulnerabilities.
* Added malicious code detection and enhanced validation logic for tools.
* Implemented refresh token support for authentication, enhancing security and session management.
* Added Server-Sent Events (SSE) for live streaming of evaluation results (LLM as Judge & Ground Truth).
* Connected bi-encoder and cross-encoder models to hosted servers via URLs.
* Added temperature slider for models in chat screen.
* Revamped evaluation screen with three-column layout.
* Added support for tables, JSON, images, email and use-case specific cards in Canvas.
* Added error handler to have control over application errors.
* Removed .env file from codebase and replaced with .env-example.
* Expanded MCP Server tooling with support for running/testing mcp tools.
* Introduced a new context flag that, when disabled, prevents old chat history from being included in the agent's context.
* Added support for running online evaluations during agent inference, enabling real-time assessment of agent outputs
* Fixed code preview plugin and Admin screen design issues.
* Removed guest user login.
* Fixed filter/tag issues in listing pages.
* Updated chat history to fetch respective session to proceed with the chat with out issues.
* Role-Based Access Control (RBAC):
   Restricted access for users with USER role:
   Removed Tools, Agents, Data Connector, and Vault screens.
   Hidden debug steps and online evaluation in chat.
   Added restrictions on API endpoints for Tools, Agents, and Data Connector.
* Tool Validation Enhancements:
   Refined validation logic to improve accuracy and reduce false warnings.
   Fixed previous validation issues for better reliability.
   Updated React Critic Agent to include tool metadata for better context awareness.
* Removed unwanted/unused modules from `requirements.txt` to streamline dependencies.
* Bug Fixes:
   Fixed issue where error popup did not auto-hide when navigating to a different page.
   Corrected supported file types for Knowledge Base uploads.
   Allowed multiple file uploads only for Knowledge Base.
   Default port value converted to integer for data connector .

## Version 1.4.2 – September 26, 2025
*  Removed monaco code editor 

## Version 1.4.1 - September 23, 2025

*  Toggle feature for adding enabling or disabling of canvas.
*  Toggle to include context for the chat.
*  Admin screen scrolling fixed.
*  Update user defect fixed.
*  Added filter by server type in list of servers in tools and agents pages.
*  Filter by tags to show only for Servers in Filter Modal in update agent.
*  Guest login not able to chat.
*  Application title in browser tab changed to 'IAF'.
*  Tags button moved from the mapped section to the top of the screen in updated Agent page.
*  Added page total count for list of tools, list of servers, list of servers.


## Version 1.4.0 - September 5, 2025

*  **Dynamic Canvas Previewer** - In chat screen based on user query we show custom canvas for more visualisation of the data, Canvas can render Table, Chart, Image, Programming code preview, JSON viewer dynamically based on the response.
*  **MCP Servers** - Users can connect to MCP server(s).
*  **Data Connectors** - Provision to connect private database. Currently supports SQLite and MySQL. MongoDB yet to be allowed.
*  **Code Execution** - while tool onboarding users can run the python code to check for the output or errors.
*  **Prompt/Query suggestions** - In chat screen now users can choose from history of prompts or from prompt suggestions.
*  **JWT based Authentication** - Users are now authneticated using JWT bearer token.
*  **Memory** - Imlemented memory implementation for system responses in chat for future context and system references.
*  Code clean up.
*  Minor corrections and improvsations on UI.
*  Learning page added 'lesson'.

## Version 1.3.0 – July 31, 2025

*  **Continued Modularization:** Further modularized key functionalities, including feedback learning and evaluation metrics, for improved maintainability and integration into agent export.
*  **Configuration:** Introduced configurable CORS origins and SBERT model paths via environment variables.
*  **System Stability:** Addressed public/private key management issues.
*  **Development & Integration:** Performed legacy code cleanup and unified API access through FastAPI integration.
*  **UI & Agent Fixes:** Released Chat UI Version 2.0 (Inference page design with new look), added a new Data Connectors page, corrected API endpoints due to modularity changes, and resolved issues on agent screens related to Meta/Planner Meta Agents, System Prompts, and Evaluation metrics menu item changes.
*  **Inference Output Format Restructuring:** Restructured API endpoints' inference output to include a list of all tools invoked during the agent inference call along with their corresponding outputs.

## Version 1.2.0 - July 25, 2025

*  **Code Architecture Modernization:** Refactored code using Object-Oriented Programming (OOP) principles, introduced modular service layers (AgentService, ToolService, and TagService), and implemented a repository pattern with database connection pooling for improved performance.
*  **Enhanced Agent Templates:** Streamlined Multi-Agent templates, adding a Planner & Executor configuration and a React & Critic setup for focused evaluation.
*  **Advanced Features:**
    *   Introduced Ground Truth Based Evaluation for precise agent output assessment.
    *   Integrated Knowledge Base support for React agents.
*  **Database & Connectivity:** Enhanced Data Connector functionality to support multiple databases (SQLite, PostgreSQL) and updated existing functions for PostgreSQL migration.
*  **Security & Management (Vault):** Developed a centralized Secrets Handler module for secure management of sensitive information, including public and private secrets.
*  **Monitoring Improvements:** Enhanced telemetry with trace ID fixes and session tracking, and modularized chat-related logic into dedicated service layers.
*  **Admin & UI Refinements:** Improved Recycle Bin logic, added API endpoints for listing markdown files, introduced new UI pages for Ground Truth and Secrets, and resolved various defects across admin screens and tool mapping.


## Version 1.1.0 - July 17, 2025

*  **Admin Panel:** Launched a comprehensive Admin Panel with features for:
    *   User registration, User profile updates, and a recycle bin for deleted items.
    *   Evaluation Dashboard displaying evaluation results, tool utilization, and agent efficiency scores.
    *   Metric management: Allows admins to trigger evaluations using the "LLM as a Judge" approach.
    *   Feedback Management: Admins can review and approve user feedback before it is used for agent training.
*  **New Agent Templates:**
    *  **Meta Agent (Supervisor Agent):** Supervisor agent template which delegates tasks to worker agents.
    *  **Planner Meta Agent:** Two-stage workflow—first, a planner node generates a step-by-step plan; then, each step is executed sequentially by the meta/supervisor agent.
    *  **Planner-Executor Agent:** Template similar to Multiagent without Critic, with and without "Plan Verifier".
    *  **React Critic Agent:** Template similar to React introduced in version 1.0.0, with the addition of Critic.
*  **Agent Creation & Export:** Users can export the code for any agent, along with the tools used by agents, to run locally and modify as needed.
*  **Feedback Learning:** Agents (React and Multi-Agent) learn from user feedback to improve future responses, subject to admin approval.
*  **System Enhancements:**
    *   Added tool interrupt capability for both React Agent and Multi-Agent workflows, allowing dynamic intervention and correction during tool execution.
    *   Refactored core functions using `async/await` for scalability, and improved feedback handling in the multi-agent system.
*  **Telemetry & Tracing:**
    *   Enabled OpenTelemetry to monitor agent activities and system performance for improved diagnostics, analytics, and framework-level debugging.
    *   Integrated Arize Phoenix for detailed agent tracing and monitoring.
*  **Evaluation Metrics:** Introduced evaluation metrics to assess the performance and efficiency of AI agents, focusing on the "LLM as a Judge" approach.
*  **UI Updates:** Added new UI pages for updating users and managing the recycle bin.


## Version 1.0.0 - May 30, 2025

*  **Tool Management:** Introduced functionality to create, onboard, and manage custom tools (Python functions) for LLM agents, making them reusable. Users can write custom logic for tools to access uploaded file content.
*  **Agent Templates:** Released initial agent templates including:
    *   React Agent for single-task accomplishment.
    *   Multi-Agent system using a Planner-Executor-Critic framework, with an optional "Plan Verifier" mode.
*  **Memory & Interaction:** Implemented simple conversation memory for agents and enabled real-time interaction via chat for inference and task execution.
*  **File Integration:** Added support for file uploads, allowing agents to utilize file content through integrated tools.
*  **UI Enhancements:** Introduced live tracking for agent activities and provided access to documentation via a Help button.

