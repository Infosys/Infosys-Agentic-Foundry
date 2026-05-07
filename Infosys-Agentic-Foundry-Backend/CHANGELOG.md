# Changelog


## [1.9.0] - Release 1.9.0

### Merged
- **Main Branch Merge:** Merged the latest development changes into the `main` branch, ensuring all new features, bug fixes, and improvements are available in the primary codebase.


## [1.8.8]

### Changes
- **Fixed Few SAST Scan Vulnerabilities:** Fixed few SAST scan vulnerability issues.
- **Password Encode-Decode Validation in Data Connectors:** Added password encode-decode validation in data connectors endpoints.
- **Fixed Agent Tool Binding Response:** Fixed agent tool binding response.
- **Removed Data Connectors New Change:** Removed data connectors new change.
- **Update Use LiteLLM Proxy Flag:** Updated use litellm proxy flag str of .env key to fix Google ADK issue.


## [1.8.7]

### Changes
- **Refactor: Move SMTP Configuration to Environment Variables:** Moved SMTP configuration to environment variables.
- **Fix: Case-Insensitive Name Uniqueness Across All Entities:** Fixed case-insensitive name uniqueness checks across all entities.
- **Implemented Tool Versioning in Export Agent:** Implemented tool versioning in export agent.
- **Fixed Import Issue for Tools Present in Recycle Bin:** Fixed import issue for the tools that are present in recycle bin with the same name.
- **Fix: Resolved User ID and Model Cost Defaulting to 0 Issue:** Fixed user id and model cost defaulting to 0 issue.
- **Fix: User Email Instead of User Name in Query Usage Report:** Fixed query usage report to use user email instead of user name.
- **Fixed Minor Bugs in Message Queue Implementation:** Fixed minor bugs in message queue implementation.
- **Modified Status for Tool Import and Fixed Response Bugs:** Modified the status for tool import if name already present and fixed some response bugs.


## [1.8.6]

### Changes
- **Chat Inference Minor Bug Fix:** Fixed a minor bug in chat inference.
- **Modified Message Key for Tool Import:** Modified the message key for tool import.
- **Modified Tool Import Response:** Modified tool import response to provide detailed information.
- **Export Agent Code Updated:** Updated export agent code to have latest changes.


## [1.8.5]

### Changes
- **Fixed Restoring Logic for Version:** Fixed the restoring logic for version tracking to ensure proper version recovery.
- **SMTP Timeout Configuration:** Set SMTP timeout to 3 seconds for email sending to prevent long-running connections.
- **Admin Role Only Privileges for Multiple Deletion:** Added Admin role restriction for multiple deletion operations to enforce proper access control.
- **Base64 Decoding for Tools and MCP Tool Codes:** Implemented base64 decoding for tools and MCP tool codes to ensure proper handling of encoded content.
- **Recycle Bin Name Conflict Logic Updated:** Modified recycle bin logic to allow users to create resources with names that already exist in the bin, instead prompting to rename when restoring from the bin.
- **Tool Execution Fix During Inference:** Fixed an issue with tool execution while inferencing.
- **Recycle Bin Restore Error Fixed:** Fixed recycle bin restore error.
- **Cleanup and Backup Services Updated for Tool Versioning:** Modified cleanup and backup services to work with tool versioning.
- **Message Queue Implementation Using Kafka:** Implemented Kafka-based message queue for tools and agents to support asynchronous and batch asynchronous inference requests.
- **LiteLLM Proxy Server Integration:** Implemented LiteLLM proxy server to route LLM calls through custom model servers.
- **LangGraph LLM Model Helper Wrapper Classes:** Implemented wrapper classes and functions for LangGraph LLM model helper classes to retrieve custom token usage details.


## [1.8.4]

### Changes
- **Sample MCP Tool Data in JSON:** Updated default MCP tools and servers with sample JSON data for easier configuration and deployment.
- **MCP Remote URLs and Inline Execution Endpoints:** Added new endpoints for updating remote MCP URLs and executing MCP code inline.
- **MCP Permissions Migration:** Migrated Admin/Developer MCP permissions to align with the latest RBAC framework.
- **MCP Tool Creation and Management:** Implemented comprehensive code for database tool creation, implementation, and management workflows.
- **Agent and MCP Server Deletion Endpoints:** Fixed merge conflicts in agent and MCP server deletion endpoints.
- **MCP Command Field in Payload:** Added `mcp_command` field to the MCP tool creation payload for specifying execution commands.
- **External MCP Type Update Endpoint:** Added new endpoint for updating external MCP type tools.
- **Default MCP Servers and Public Field:** Added default MCP servers and modified the approve MCP function to include an `is_public` field for controlling tool visibility.
- **Viber Endpoint Rename:** Changed `/viber` endpoint name for improved clarity and consistency.
- **MCP Server Payload Updates:** Modified default MCP servers payload structure for better configuration management.
- **Base64 Encoded Password Handling:** Added support for handling base64-encoded values in password fields for secure credential transmission.
- **Tool Versioning:** Implemented version tracking for tools to support iterative updates and rollback capabilities.


## [1.8.3]

### Changes
- **Frontend and Backend Validation Alignment:** Synchronized validation logic between frontend and backend.
- **MCP Tool Recycle Bin Check:** Added validation to check if an MCP tool exists in the recycle bin before creating a new tool with the same name.
- **Multiple Approval for Registration:** Implemented a multi-step approval workflow for user registrations, requiring approval from multiple administrators.
- **Swagger UI Static Files Restored:** Re-added the static folder containing Swagger UI code to resolve the issue where Swagger UI was not accessible.
- **Sample MCP Servers Added:** Added default availability of sample MCP (Model Context Protocol) servers.
- **Multiple Selection for Deletion:** Implemented functionality to select and delete multiple tools, agents, MCP tools, or servers in a single operation.
- **Backup and Export Endpoints:** Added new endpoints to create backups and export system data for preservation and migration purposes.
- **Cleanup Endpoint:** Implemented a dedicated endpoint to perform cleanup operations on system resources and temporary data.
- **Pipelines Renamed to Workflows:** Renamed the "pipelines" feature to "workflows" throughout the framework for improved clarity and consistency. Implemented comprehensive data migration to update all existing pipeline references, database records, and API endpoints to use the new "workflows" terminology.
- **Tool and MCP Server Export/Import Functionality:** Implemented export and import capabilities for tools and MCP servers.


## [1.8.2]

### Changes
- **Workflow ID Prefix Update (ppl_ → wf_):** Updated workflow ID generation to use `wf_` prefix instead of `ppl_` for better identification. Added a database migration (`ppl_to_wf_prefix_v1`) to update all existing workflow IDs across all related tables. Workflow detection logic now supports both `wf_` and legacy `ppl_` prefixed IDs for backward compatibility.
- **Department Name in Unused Resources Report:** Added `department_name` field to the response when retrieving unused tools and agents.
- **Manual TTL Logic Modified:** Updated the Time-To-Live (TTL) logic.
- **Workflow Chat File Upload:** Implemented file upload functionality within chat for workflows.
- **Viber Agent ID Retrieval Endpoint:** Added a new endpoint to retrieve the Viber agent ID.
- **Meta Agent Sub-Agent Details Fix:** Fixed an issue where sub-agent details were missing when retrieving meta type agent information via the get agent endpoint.
- **Local Namespace Object Added for Google ADK and Pure Python:** Added missing local namespace (`ns`) object initialization for Google ADK and pure Python.
- **Tool Code Security Restrictions:** Implemented security restrictions to prevent tools from importing from the `src` folder (except for load_model), reading environment variables, or accessing `.env` files, reducing potential security vulnerabilities.


## [1.8.1]

### Changes
- **Standalone File Server for User Uploads:** Implemented a dedicated file server that allows browsing and downloading files from the `user_uploads` directory without requiring authentication, enabling seamless public access to uploaded user files.
- **Registration Logic Modified:** Updated registration logic for improved security and processing.
- **Knowledge Base Server Proxy Settings Updated:** Modified the knowledge base server configuration to use an improved proxy setting approach.
- **Separate Permissions for Servers, Workflows, and Export Agent:** Implemented distinct permission sets for servers, workflows, and export agents to provide granular access control and improve security boundaries.
- **MCP Get Endpoints and Search Pagination Updated:** Modified MCP get endpoints and removed permission restrictions from the MCP search paginated endpoint to improve accessibility.
- **Server and Knowledge Base Binding Fix:** Resolved an issue where servers and knowledge bases were being unintentionally updated when bound to an agent.
- **Email Helper Functionality Added:** Implemented email sending helper functions to support notifications and communications within the framework.
- **Cross-Department Resource Sharing:** Enhanced sharing capabilities for tools, MCP tools, knowledge bases, agents, and workflows across department boundaries.
- **Registration Process Improvements:** Applied suggested changes to the registration workflow for improved user onboarding.
- **Department Default Roles and Share Info Response:** Added handling for department default roles during access requests and standardized share information responses across all endpoints.
- **Department Access Request Email Notifications:** Added email sending functionality to notify users when receiving department access requests.
- **Old Chat Cleanup Endpoint for Super Admin:** Implemented a new endpoint allowing super admin users to perform cleanup of old chat histories for maintenance and data management.
- **Admin Tool and MCP Server Updates:** Enabled admins to update tools and MCP servers even when they are bound to agents, providing greater flexibility in resource management.
- **Created By System Filter:** Added system-level filtering capability by `created_by` field for tools, servers, agents, and workflows, enabling better resource organization and tracking across the framework.
- **Agent Name Filtering:** Added optional filtering capability by agent name across relevant endpoints, enabling users to search and retrieve agents more efficiently based on their names.
- **Custom Headers Support for MCP:** Added support for custom headers in MCP server configuration, allowing users to specify additional HTTP headers for requests to MCP servers via the `headers` key in the configuration.
- **Message Queue Enhancement with Kafka-Python:** Extended Kafka integration to support machine-to-machine (M2M) inference and batch processing, enabling agents and tools to communicate asynchronously through a scalable message queue infrastructure. Agents can now publish inference requests and subscribe to results, supporting distributed workflows and improved throughput for batch inference operations.


## [1.8.0] - Release 1.8.0

### Merged
- **Main Branch Merge:** Merged the latest development changes into the `main` branch, ensuring all new features, bug fixes, and improvements are available in the primary codebase.


## [1.7.12]

### Changes
- **SAST Vulnerabilities Fixed:** Resolved all new SAST scan security vulnerabilities identified in the codebase.
- **Feedback Learning Enhancements:** Updated endpoints for feedback learning, fixed associated bugs, and exposed statistics in feedback learning functionality.
- **Cascaded Delete for Agent Workflow:** Fixed cascaded deletion logic for agent workflows to ensure proper cleanup of related data.
- **Admin Role Update Restriction:** Resolved issue that allowed admins to update their own role; now restricted for security compliance.
- **Search Paginated MCP Endpoint Changes:** Updated search paginated MCP endpoint and removed permission checks for tools and agents search paginated endpoints.
- **Feedback Status Edited:** Feedback Status Implementation edited.
- **Agent-Workflow Mapping Validation:** Added validation check for agent-workflow mapping before agent deletion to prevent orphaned dependencies.


## [1.7.11]

### Changes
- **Resource Username Issue Resolved:** Fixed an issue where resource usernames were not being properly handled in user preference and resource management operations.
- **MCP Restore Functionality Fixed:** Resolved issues with restoring MCP tools and servers from the recycle bin, ensuring proper recovery and reactivation of deleted resources.
- **Shared Tools and Servers Handling:** Implemented proper handling for shared tools and servers across users, ensuring correct access control and data consistency.
- **Duplicate/Double Streaming Responses Fixed:** Resolved an issue where hybrid agents were sending duplicate streaming responses during inference, eliminating redundant output.
- **Hybrid Agent Response Time Optimized:** Fixed performance issues affecting response time calculations for hybrid agent templates, ensuring accurate timing measurements.
- **MCP Tool Soft Delete & Restore:** Implemented soft delete and proper restore functionality for MCP tools, enabling reliable recovery from the recycle bin.
- **Feedback Lessons Display Fixed:** Fixed an issue where lessons from feedback were not being properly displayed in the UI, ensuring users can view all feedback learning content.
- **Export Agent RBAC Integration:** Updated the export agent functionality to incorporate Role-Based Access Control (RBAC) and other latest framework changes, ensuring exported agents respect permission boundaries.


## [1.7.10]

### Changes
- **RBAC Logic Fixes in Metrics:** Resolved RBAC issues affecting tool and agent metrics to ensure correct data access.
- **Super Admin Department Assignment:** Fixed a super admin issue to allow assignment to any department with a specific role.
- **Tool Workflow Permissions:** Fixed permission issues related to the tool onboarding workflow.
- **Hybrid Agent Welcome Message:** Resolved a defect where the welcome message was not generating for hybrid agents.
- **Agent Onboarding Optimization:** Optimized the agent onboarding and updating process by parallelizing LLM calls for improved performance.


## [1.7.9]

### Changes
- **Async Tool Docstring Fix:** Resolved an issue where async methods were not generating docstrings during the onboarding of asynchronous tools.
- **Google ADK SSE Response Cleanup:** Fixed the double description issue in Google ADK SSE responses and updated the display to show only the score for critic and validator steps.
- **Agent Efficiency Metric by Type:** Implemented agent type functionality for tool and agent efficiency metrics to provide more granular performance insights.
- **Hybrid Template Validators:** Implemented validators for the hybrid agent template and fixed the combination logic for verifiers and validators.
- **Chatbot Resource Onboarding & Optimization:** Implemented onboarding of chatbot-related resources on server start, removed MCP dependency from the tool chatbot, and refactored dependency analysis using regex for improved efficiency.
- **Model Server No-Proxy Configuration:** Modified code to use `NO_PROXY` settings for `MODEL_SERVER_URL` API calls.
- **Role-Based Access Control (RBAC):** Implemented a comprehensive Role-Based Access Control (RBAC) system organized around departments, providing fine-grained control over permissions for viewing, creating, updating, deleting, and executing tools, agents, and workflows.


## [1.7.8]

### Changes
- **Filter Functionality for Tools and Validators:** Added filter options in the paginated search endpoint to enable more precise filtering of tools and validators based on various criteria.
- **Knowledge Base Cache Changes Removed:** Removed caching logic previously applied to knowledge base operations to ensure real-time data consistency.
- **Tool and Server Segregation in Tool Get By List Endpoint:** Updated the `tool/get/by-list` endpoint to properly segregate tools and server instances, improving endpoint clarity and response structure.
- **Tool Code Generation via LLM:** Implemented functionality to generate tool code automatically using LLM capabilities, streamlining tool creation and reducing manual code writing requirements.
- **Model Service Updated:** Updated the model service to only display models when all required configuration keys are provided in the `.env` file, ensuring that incomplete or improperly configured models are not made available for use.


## [1.7.7]

### Changes
- **Privacy Violation SAST Issue Fixed:** Resolved security vulnerability related to privacy exposure in SAST scan.
- **Sample Tools and Agents Onboarding:** Added functionality to onboard sample tools and agents during application startup, providing example resources for new setups.
- **Safe Unparsing in Tool Code Processing:** Implemented safe unparsing mechanisms in tool code processing to prevent code injection and parsing errors.
- **Add Tool Endpoint Refactored:** Removed file upload option from `add_tool_endpoint` and created a separate dedicated endpoint for file-based tool uploads, improving endpoint separation of concerns.
- **Path Manipulation SAST Issue Fixed:** Resolved path manipulation flagging in SAST security scan.
- **Agent Type Filter for Evaluation Service:** Implemented agent type filtering in the evaluation service for improved query accuracy and results.
- **Frontend Export Code Updated:** Updated frontend export code and removed dependencies from GitHub for improved maintainability and security.


## [1.7.6]

### Changes
- **Retention Days Argparse Key:** Added `retention-days` argparse key in the conversation cleanup file for configurable retention period.
- **Azure GPT-4 Models Access Fix:** Fixed Azure GPT-4 models access denied issue caused by invalid subscription and resolved auto-suggestion `user_history` issue.
- **Arize Phoenix Traces Fix:** Fixed Arize Phoenix traces issue for all agent templates.
- **Workflow Execution Improvements:** Fixed additional details and older outputs correction, updated logic for parallel workflow execution, and resolved rate limit and context limit errors.
- **Agent-Knowledge Base Mapping:** Implemented Agent-Knowledge Base mapping functionality.


## [1.7.5]

### Changes
- **Welcome Message Prompt Updated:** Updated the prompt used for generating the agent's welcome message.
- **Blob Storage for Export Agent:** Implemented blob storage integration for the export agent functionality.
- **Message Queue (Kafka) Implementation:** Added Kafka-based asynchronous tool execution in `kafka_handler.py`, featuring `KafkaToolExecutor` for publishing messages to topics and `KafkaToolConsumer` for processing tool calls and returning results through dedicated response topics.
- **File-Based Context Management:** Implemented file-based context management across agent templates and services, generating specialized system prompts (stored in `file_context_prompts`) that use shell commands (`run_shell_command` tool) instead of memory tools (`manage_tool`/`search_tool`) for conversation persistence, with context stored in markdown files within agent workspaces.
- **Google ADK SSE Fix:** Fixed Server-Sent Events (SSE) issue in Google ADK.
- **Python Tool to MCP Local Server Conversion:** Added functionality to convert Python-based tools to MCP local server format.
- **Parallel Dependency Analysis Caching:** Implemented caching logic for faster dependency analysis during agent export and missing dependency identification with parallel processing via ThreadPoolExecutor for improved performance.


## [1.7.4]

### Changes
- **Blob Storage Integration & Chat File Upload Cleanup:** Integrated blob storage functionality and removed the creation of agent directories for chat file uploads.
- **Google ADK Output Schema & Prompt Refinements:** Fixed output schema issues and refined evaluator, validator, and critic prompts for Google ADK.
- **Workflow Agent History Fix:** Fixed agent-level history retrieval issue for workflow workflows.
- **Inference Configuration Endpoint Refactor:** Removed inference threshold and epoch configuration from the inference endpoint; created new admin-only endpoints to update or reset epochs and threshold scores.


## [1.7.3]

### Changes
- **Welcome Message & Regeneration Toggle:** Added a welcome message for the agent along with a toggle to control regeneration of it.
- **Chat Inference File Upload:** Implemented file upload functionality within chat inference.
- **Chat Details Endpoint Update:** Updated the chat details endpoint to retrieve workflow details.
- **Tool File Cloud Upload:** Modified the tool file manager so that tool files are now uploaded to the cloud.
- **Hardcoded Model Names Removed:** Removed hardcoded model names from the codebase and updated the export agent to utilize these constant changes.
- **Hardcoded Table Names Removed:** Removed hardcoded table names for conversation cleanup files and other files where it was missed in initial removal.


## [1.7.2]

### Changes
- **Blob Storage Implementation:** Implemented blob storage functionality.
- **Selective Tool Interrupt for Hybrid Agents:** Extended selective tool interrupt capabilities to the hybrid agent template.


## [1.7.1]

### Changes
- **Google ADK Framework Re-added:** Re-added the Google ADK framework type support.
- **Constants Centralization:** Moved hardcoded constant values into a single `constants.py` file for better maintainability.
- **Env Example Cleanup:** Removed unnecessary repeated PostgreSQL database connection entries from `.env.example`.
- **Inference Configuration Settings:** Refactored inference agents to utilize `InferenceConfigSettings`, allowing configurable thresholds and iterations for validators, evaluators, and critics via endpoints.
- **Hybrid Agent Evaluator Context Fix:** Fixed an issue where the hybrid agent evaluator lacked updated context for tools and the plan verifier.


## [1.7.0A] - hotfix

### Changes
- **OpenAI Model Support for LangGraph Templates:** Added support for OpenAI models in LangGraph-based agent templates, enabling seamless integration and utilization of OpenAI's language models.
- **Safe Tool Code Parsing:** Implemented safe tool code parsing in add/update tool operations, and modified the add tool endpoint payload to accept JSON format for improved handling of large code snippets that previously caused network errors when sent as form data.
- **Enterprise GitHub Dependency Removal:** Removed enterprise GitHub dependency from the export agent's frontend code export process, simplifying deployment and reducing external service requirements.
- **Async Tool Docstring Fix:** Fixed the issue of docstrings not getting generated for async functions during tool onboarding.


## [1.7.0] - Release 1.7.0

### Merged
- **Main Branch Merge:** Merged the latest development changes into the `main` branch, ensuring all new features, bug fixes, and improvements are available in the primary codebase.


## [1.6.10]

### Changes
- **MCP Tool Recycle Bin Updates:** Added an endpoint to retrieve unused recycle bin items for MCP tools and resolved a related recycle bin issue.
- **Export Agent Cleanup & Response Time:** Removed unused import statements and incorporated the new response time logic into the export agent.
- **Admin Package Management:** Added functionality to view all installed packages, identify missing dependencies referenced in older code, and list pending modules required for new tools (showing module name, tool code, user email, and timestamp).
- **Agent Workflow ID Update & Cleanup:** Updated the ID creation logic for agent workflows to include a `ppl_` prefix for better identification, removed the `is_workflow_call` key from the inference payload, and eliminated log statements that were exposing sensitive data.
- **Critic Agent Epoch Fix:** Fixed the critic agent's epoch not handled properly issue for React Critic and Planner-Executor-Critic templates.
- **Tool Feedback Datatype Handling:** Updated the `convert_value_type_of_candidate_as_given_in_reference` method to handle complex data types, for tool feedback datatype correction in Hybird agents.
- **Hybrid Agent Validator Reversion:** Reverted the validator agent part for the hybrid agent template.


## [1.6.9]

### Changes
- **Export Agent Inference Endpoint Updated:** Updated the inference endpoint for export agent to include agent workflow classes.
- **Workflow Flow Response Formatting Disabled:** Disabled response formatting for agents in the workflow flow.
- **MCP Deletion Recycle Bin TTL:** Added TTL (Time-To-Live) to MCP deletion recycle bin entries.
- **Response Time Fix for LangGraph & Hybrid Templates:** Fixed response time issue for LangGraph and hybrid templates.
- **Workflow Output Node Prompt Fix:** Fixed the output prompt of the output node in the workflow.
- **Validator Node Fixes & Hybrid Agent Support:** Fixed issues related to the validator node for LangGraph templates and implemented validator support for hybrid agent templates.


## [1.6.8]

### Changes
- **Agent Workflow in LangGraph:** Enabled a new feature called agent workflow in LangGraph, allowing the creation of workflows where a chain of agent flows can be utilized.


## [1.6.7]

### Changes
- **Evaluation Attempts & Loop Fix:** Added an increment step for evaluation attempts and resolved an infinite loop issue to ensure smoother execution.
- **Chat Inference Feedback Persistence:** Implemented logic to save evaluation and validation feedback received during chat inferences.
- **Export Agent Dependency Handling:** Enabled exporting of agents with tool dependencies along with base requirements.
- **Export Agent Validators:** Added validator support to the export agent functionality.


## [1.6.6]

### Changes
- **Google ADK Cleanup:** Removed Google ADK inference files and commented out other Google ADK-related components to streamline the codebase.
- **Export Agent Endpoint Updates:** Updated several endpoints for the export agent to improve functionality and consistency.
- **Tool File Creation on Update:** Added logic to automatically create a file representation when updating an existing tool, ensuring consistency with file-based tool management.
- **MCP Tool Recycle Bin:** Added recycle bin functionality for MCP tools.


## [1.6.5]

### Changes
- **Selective Interrupt Expansion:** Extended selective interrupt capabilities to include MCP tools and agents, allowing for more precise control over execution flow.
- **Google ADK Database Migration:** Migrated the Google ADK state memory database from SQLite to PostgreSQL for improved scalability and consistency.


## [1.6.4]

### Changes
- **Username Validation Fix:** Corrected the username validation logic for the register endpoint.
- **Tool File Persistence:** Implemented functionality to save tools as files on the server during onboarding, with update, delete, and restore operations mirroring database logic.
- **Selective Tool Interrupt:** Added support for selective tool interruption in LangGraph templates, enabling more granular control over tool execution flow.
- **SSE Naming Update:** Modified Server-Sent Events (SSE) naming conventions for Meta and Planner Meta agents within LangGraph templates for better consistency.


## [1.6.3]

### Changes
- **Expanded Meta Worker Templates:** Enabled React-Critic and Planner-Executor templates to function as worker agents within meta agent architectures.
- **Meta Agent Worker Streaming:** Enabled streaming for worker agents within meta agent workflows using LangGraph.
- **Conversation Summary Cleanup:** Implemented deletion of past conversation summaries when a chat is deleted.
- **Google ADK Episodic Memory:** Added episodic memory management support for Google ADK.
- **Google ADK SSE Streaming:** Enabled Server-Sent Events (SSE) streaming for Google ADK responses.
- **Meta & Planner Meta Validators:** Added validator support for Meta and Planner Meta agent templates in LangGraph workflows.


## [1.6.2]

### Changes
- **Database Configuration via .env:** All database names can now be set up through the `.env` file.
- **Hybrid Agent SSE Streaming:** Enabled Server-Sent Events (SSE) streaming for the hybrid agent template.
- **SBERT Connection Handling:** Added handling for SBERT model connection issues.
- **Google ADK Inference Enhancements:** Enabled offline evaluation (LLM as a Judge), feedback learning, and feedback functionalities (like, dislike, regenerate) for the last response of a session in Google ADK inference.


## [1.6.1]

### Changes
- **Plan Verifier for Planner Meta:** Added plan verifier (Human-in-the-Loop) functionality to the Planner Meta agent template.
- **Plan Verifier UI & Feedback Fixes:** Resolved UI display issues for the plan verifier and fixed the feedback reset mechanism.
- **Evaluation Score Fix:** Fixed an issue where changing the plan resulted in a low evaluation score.
- **Google ADK Inference Restoration:** Restored Google ADK inference support for React, Planner-Executor-Critic (PEC), Planner-Executor (PE), React Critic (RC), Meta, and Planner Meta templates, with support for Plan Verifier and Canvas View toggles.
- **TTL Table Check:** Added a check to verify if tables exist before performing Time-To-Live (TTL) operations.
- **Conversation Restore Update:** Modified the conversation restore logic to include restoring long-term memory records in TTL.


## [1.6.0] - Release 1.6.0

### Merged
- **Main Branch Merge:** Merged the latest development changes into the `main` branch, ensuring all new features, bug fixes, and improvements are available in the primary codebase.


## [1.5.16]

### Changes
- **Critic Content Message Length Reduced:** Reduced the length of critic content messages in SSE streamed data for better performance.
- **OpenInference Instrumentation Added:** Added `openinference-instrumentation` to `requirements.txt` to support enhanced tracing capabilities.
- **Phoenix Trace Mixing Prevention:** Implemented measures to prevent Phoenix trace mixing during concurrent requests, ensuring accurate trace data.
- **Phoenix Manager Fix:** Applied a fix to the Phoenix manager to resolve operational issues.
- **Graph Recursion Limit Handling:** Added handling for graph recursion limit exceeded errors to improve stability during complex executions.
- **Data Connector Password Key Update:** Updated the connect API for data connectors to accept the password value in either the `password` or `user_pwd` key, whereas previously it only accepted the `password` key.
- **SAST Security Fixes:** Removed sudo hardcoded passwords from `.env.example` and addressed security false positive issues related to `secret` and `password` keywords.


## [1.5.15]

### Changes
- **Reviewing Response Critic Score:** Modified the reviewing response critic score logic for both standard and streamed responses.
- **SSE Response Consistency:** Fixed typos and improved consistency in response messages across inference modules during Server-Sent Events (SSE) streaming.
- **SBERT Similarity Error Handling:** Added error handling to the SBERT similarity calculation process to prevent failures.
- **Conversation Summary Deletion Fix:** Resolved an issue where the conversation summary was not deleted when the chat history was cleared.


## [1.5.14]

### Changes
- **Export Agent Import Updates:** Updated import statements for sentence transformer and cross encoder in the export agent.
- **SSE Fix:** Resolved an issue related to Server-Sent Events (SSE) functionality.


## [1.5.13]

### Changes
- **Google ADK Reversion:** Removed Google ADK-related inference files and reverted the app container configuration to exclude Google ADK usage.
- **Export Agent Updates:** Fixed and updated the export agent codebase for improved stability and functionality.
- **Dependency Updates:** Added `rapidfuzz` to `requirements.txt` and resolved a version typo for an existing module.


## [1.5.12]

### Changes
- **Hybrid Agent Response Fixes:** Resolved issues with response time and timestamp accuracy for the hybrid agent.
- **Dependency Optimization:** Removed `transformers` and `torch` dependencies from the core package, integrating them into the model server setup for a lighter footprint.


## [1.5.11]

### Changes
- **Regenerator Feedback Query:** Added the original query along with feedback to the regenerator node to improve context during regeneration.
- **Replanner Conditional Edge:** Implemented a conditional edge from the replanner to the general LLM to handle cases where no plan is generated.
- **Ground Truth Error Fix:** Fixed an error related to ground truth.
- **Tool Delete Response Update:** Changed the `status_message` key to `message` in the `delete_tool` method of the tool service for consistency.


## [1.5.10]

### Changes
- **Validation Score & PEC Loop Fix:** Fixed validation score resetting and resolved the infinite loop issue in the Planner-Executor-Critic (PEC) workflow.
- **Context Passing to Validators:** Enabled passing of updated query context or tool arguments to validators.
- **Replanner Node in PEC:** Modified the Planner-Executor-Critic workflow to utilize a replanner node.
- **Planner Executor State Update:** Added missing evaluation attempts to the state variables of the Planner-Executor template.
- **Google ADK Inference Support:** Added functionality to use React and Planner-Executor-Critic template inference with Google ADK.
- **Google ADK Session Management:** Completed and integrated session management for Google ADK.


## [1.5.9]

### Changes
- **React Agent SSE & Context Fixes:** Fixed React agent SSE responses, updated naming conventions to prevent false updates, and fixed context handling for all agents.
- **Evaluator & Timestamp Fixes:** Resolved evaluator issues and fixed the `end_time` stamp key issue.
- **ChatMessage Tool Calls Attribute:** Fixed an issue where `ChatMessages` were missing the `tool_calls` attribute.
- **Streaming Node Names Update:** Modified node names in streaming for React Critic, Planner, Planner Critic, Meta, and Meta Planner agents.
- **Tool Verifier & Response Fixes:** Fixed tool verifiers and corrected issues related to multiple responses and content.
- **Google ADK Canvas Formatter:** Added canvas formatter for React and Planner-Executor-Critic agent templates in Google ADK inference.
- **Context Passing for Evaluators/Validators:** Added passing of updated tool arguments and tool context to online evaluator and validator nodes.
- **Online Evaluator Loop Fix:** Fixed an issue where online evaluators and validators went into an infinite loop due to the tool interrupt flag.


## [1.5.8]

### Changes
- **Plan Verifier for Google ADK:** Added plan verifier functionality for the Planner-Executor-Critic agent using Google ADK.
- **Created By Key Update:** Fixed the `created_by` key to return the actual user name instead of the email address.
- **Agent Endpoint Fixes:** Resolved issues in the update and delete agent endpoints.
- **Meta Agent Validation Cleanup:** Removed `validation_criteria` from meta agent templates.
- **Tool Execution Bug Fix:** Fixed a bug affecting tool execution logic.
- **Chat Endpoint Timestamp Fix:** Resolved response time and timestamp issues for the chat endpoint.
- **Formatter Node & Streaming Fix:** Fixed issues with the formatter node and streaming that caused online evaluation and validators to fail when enabled individually.
- **Planner Meta Code Cleanup:** Removed extra and unused code from the planner meta file.
- **Critic-Based Planner Fix:** Resolved a failing case in the critic-based planner where the critic score was null if the evaluation flag was enabled.
- **User Update Events (React & Planner Meta):** Added `user_update_events` functionality to React, React Critic, and Planner Meta agents.
- **Security Fixes:** Removed the `send_email` function and fixed insecure randomness vulnerability issues.
- **User Update Events (Inference Files):** Implemented `user_update_events` functionality across inference files for Planner-Executor, Planner-Executor-Critic, and Hybrid agents.
- **Context Passing for Updated Tools:** Enabled passing context for updated tools to the response generator across Planner-Executor, Planner-Executor-Critic, and Planner Meta inference files for better response quality.


## [1.5.7]

### Changes
- **Pagination for Tools and Validators:** Added paginated endpoints to browse tools and validators efficiently.
- **Tool-as-Validator Update Fix:** Resolved issue when updating a tool designated as a validator.
- **Raw Messages in PEC Writer:** Added raw message streaming for Planner-Executor-Critic and renamed event node labels for clarity.
- **Planner Meta Node Name Update:** Modified tool update argument node name in Planner Meta agent.
- **React Template Validation Fix:** Corrected validation logic defects in the React agent template.
- **Removed Unused YAML Files:** Cleaned up repository by deleting obsolete YAML configurations.
- **React Critic ToolInterrupt Fix:** Resolved recurring ToolInterrupt issue in the React Critic template.
- **TTL Files and Conversation Summary Update:** Introduced two TTL files, added `updated_on` to `agent_conversation_summary_table`, and implemented permanent deletion for checkpoint records with `thread_id` starting with `insidetable`; removed old TTL files.
- **Online Evaluator Query Update Fix:** Fixed bug where user query was not updated after ToolInterrupt during online evaluation.
- **Canvas Formatter Prompt Cleanup:** Removed clickable button instructions from canvas formatter prompt.
- **Google ADK Output Formatter:** Added output formatting support for Google ADK.
- **Async Tool Validation & Model Decoupling:** Implemented async checks for tool validation and removed hardcoded `gpt-4o` model from execution/validation.
- **Sync DB Config Fetch:** Added synchronous SQLAlchemy connection config retrieval in `MultiDBConnectionManager`.
- **Updated DB Env Usage:** Refreshed environment credential usage in `MultiDBConnection_Manager` for database connections.
- **Secret Terminology Removal:** Removed the word “secret” from response payloads and variable names.
- **Secrets Title-to-Keynames Update:** Renamed the `title` field to `keynames` for secrets.
- **Invalid Roles Fix:** Corrected role validation and assignment issues.
- **Background Evaluation Insert:** Made insertion of evaluation records a background task for improved responsiveness.


## [1.5.6]

### Changes
- **Meta Agent Infinite Recursion Fix:** Resolved an infinite recursion limit error encountered during meta agent inference, stabilizing execution flow.
- **Data Connector User Restriction Removal:** Relaxed certain user-level access checks on selected data connector endpoints to allow broader, appropriate usage.
- **Planner Executor & Planner Executor Critic Hallucination Fix:** Resolved hallucination issues in Planner-Executor and Planner-Executor-Critic agent workflows to improve response accuracy.
- **TTL Bug Fix & Retention Configuration:** Fixed TTL cleanup logic and added `RECYCLE_BIN_RETENTION_DAYS` to `.env` for configurable recycle bin retention.
- **Epoch Key Added to State Memory:** Introduced an `epoch` key in meta agent inference state memory to support iterative processing and clearer step tracking.
- **Streaming TODO List Updated:** Refactored internal streaming to-do tracking for clearer pending/completed step visibility and reduced redundancy.
- **Improved Node Naming Conventions:** Standardized descriptive node names across in streaming response for better streamed step clarity.
- **Hybrid Agent Inference Metadata Added:** Extended hybrid agent inference responses with additional metadata to align with LangGraph-based template format and enable compatibility with the ambient agent system.


## [1.5.5]

### Changes
- **Exposed IP Address Issue Fixed:** Resolved exposure of server IP addresses in API responses.
- **SQL Injection Vulnerability Mitigated in Data Connector:** Implemented parameterized queries and input sanitization to prevent injection attacks.
- **User Email Exposure Removed in Get Agents/Tools Endpoints:** Adjusted response payloads to avoid leaking other users' email addresses.
- **Export Agent Data Connector Endpoints Updated:** Adjusted endpoint logic and parameters for data connector operations within exported agents.
- **SSE Enhancements for Exported Agents:** Added/updated Server-Sent Events streaming to improve real-time feedback during exported agent execution.
- **Tool Validation Warning Adjustment:** Converted hard-coded value errors to warnings in export agent tool validation to reduce unnecessary failures.
- **Custom Response Validation Framework:** Users can define tool-backed validators with custom criteria, map selected validators during agent onboarding, and enable them in chat inference via a validator flag to automatically evaluate and flag agent responses.
- **Tool Interrupt for Meta & Planner Meta Agents:** Added tool interrupt support to enable controlled intervention and early termination of tool executions in both agent templates.
- **Planner Meta Tool Feedback & Interrupt Flags:** Added `tool_feedback` and `is_tool_interrupte` flags to the Planner Meta state for capturing per-tool feedback and marking interrupted executions.


## [1.5.4]

### Changes
- **Online Evaluation for Meta & Planner Meta Templates:** Added support for running online evaluation workflows for meta and planner meta agent templates.
- **Requirements Cleanup:** Removed unwanted/unused modules from `requirements.txt` to streamline dependencies.
- **Multiple File Upload Endpoint:** Updated /files/user-uploads/upload/ to accept multiple files instead of a single file.


## [1.5.3]

### Changes
- **Ground Truth Evaluation Payload Fix:** Corrected payload structure issues affecting ground truth-based evaluation processing.
- **FastAPI File Upload Key Update:** Resolved incompatibilities introduced by the newer FastAPI version regarding the file upload key handling.
- **Episodic Memory for Mentioned Agents:** Added episodic memory support when invoking (mentioning) specific agent IDs and introduced a shared utility function for episodic memory operations.
- **SSE Streaming Tool Arguments Display:** Included tool call arguments in the streamed content for Server-Sent Events to improve traceability during execution.
- **Tool Validation Logic Refined:** Improved validation flow for tools to enhance accuracy and reduce false warnings.
- **JSON Extraction & Model Handling Fix in Tool Validation:** Adjusted JSON parsing and resolved a model-related defect impacting tool validation reliability.
- **Google ADK Framework Inactive Files Restored:** Re-added inactive Google ADK framework files for future implementation (still not part of active runtime).


## [1.5.2]

### Changes
- **Role-Based Access for Data Connector Endpoints:** Added user role restrictions to data connector API endpoints to enforce proper access control.
- **Hybrid Agent Evaluation Data Fix:** Resolved issue preventing hybrid agent from inserting evaluation records and blocking evaluation processing.
- **SSE Streaming for LangChain Agents:** Enabled Server-Sent Events streaming of responses for LangChain-based agent templates to deliver incremental output. 


## [1.5.3*] - Release 1.5.3

### Merged
- **Main Branch Merge:** Merged the latest development changes into the `main` branch, ensuring all new features, bug fixes, and improvements are available in the primary codebase.


## [1.5.1B]

### Changes
- **FastAPI File Upload Key Update:** Resolved incompatibilities introduced by the newer FastAPI version regarding the file upload key handling.
- **Tool Validation Logic Refined:** Improved validation flow for tools to enhance accuracy and reduce false warnings.
- **JSON Extraction & Model Handling Fix in Tool Validation:** Adjusted JSON parsing and resolved a model-related defect impacting tool validation reliability.
- **Requirements Cleanup:** Removed unwanted/unused modules from `requirements.txt` to streamline dependencies.


## [1.5.1A]

### Changes
- **Role-Based Access for Data Connector Endpoints:** Added user role restrictions to data connector API endpoints to enforce proper access control.
- **Hybrid Agent Evaluation Data Fix:** Resolved issue preventing hybrid agent from inserting evaluation records and blocking evaluation processing.
- **Removed Inactive Google ADK Inference Files:** Deleted unused Google ADK Base and React agent inference files pending future implementation.


## [1.5.1]

### Changes
- **Google ADK Agent Inference Files (WIP):** Added Base and React agent inference files for Google ADK integration; these are not yet active as the implementation is incomplete.
- **Tool Metadata in React Critic Agent:** Updated the React Critic agent to include tool metadata within the agent context, enhancing context awareness and tool utilization.
- **Tool Validation Issue Fixed and Modified:** Fixed and improved the tool validation logic to resolve previous errors and enhance reliability.
- **Role-Based Access Restrictions:** Added user role restrictions to tools and agents endpoints.


## [1.5.0] - Release 1.5.0

### Merged
- **Main Branch Merge:** Merged the latest development changes into the `main` branch, ensuring all new features, bug fixes, and improvements are available in the primary codebase.


## [1.4.24A]

### Changes
- **Consistency Service for Export Agent:** Introduced a dedicated consistency service to the export agent, enabling automated consistency checks during agent export operations.
- **Consistency and Robustness Enhancements:** Updated the consistency and robustness logic for improved reliability and accuracy in agent workflows.
- **RBAC User Permissions Reverted:** Rolled back recent changes related to RBAC user permissions to restore previous access control behavior.
- **Consistency and Robustness Endpoints for Export Agent:** Added new API endpoints to support consistency and robustness checks specifically for exported agents.


## [1.4.23]

### Changes
- **Detailed Authentication Error Responses:** Enhanced authentication error responses to provide more detailed information, improving troubleshooting and user feedback.
- **Recycle Bin Manager Logging and Error Handling:** Added comprehensive logs and improved error handling in `recycle_bin_manager.py` for better traceability and reliability.
- **Telemetry Logs with Server Name:** Updated telemetry logging to include the server name, aiding in log analysis across distributed deployments.
- **Consistency and Robustness Fixes:** Addressed issues affecting consistency and robustness in agent workflows.
- **SSE for LLM as Judge and Ground Truth Evaluations:** Implemented Server-Sent Events (SSE) support for real-time streaming of LLM as Judge and ground truth evaluation results.
- **Export Agent .env Configuration Keys:** Added missing configuration keys in the `.env` file required for export agent functionality.
- **Huggingface Models Integration Refactor:** Refactored Huggingface models integration within the FastAPI server and updated the README with relevant instructions.
- **Export Agent Login Pool Fix:** Fixed issues related to the login pool for the export agent to ensure stable authentication and session management.


## [1.4.22]

### Changes
- **Tool Name Length Validation:** Added a validation check to ensure tool names do not exceed the allowed length during onboarding.
- **Migration for Long Table Identifiers:** Implemented a migration function to resolve issues with excessively long table identifiers in the database.
- **Feedback Learning for Hybrid Agent:** Enabled feedback learning functionality for the hybrid agent template, allowing it to learn from user feedback.


## [1.4.21]

### Changes
- **Export Agent Vulnerability Fixed:** Addressed a security vulnerability in the export agent and removed password information from comments to enhance code safety.
- **Developer and Admin Access Issue Fixed:** Resolved issues affecting developer and admin access controls.
- **Role Reading Logic Updated:** Changed role reading from database to request-based logic for improved reliability.
- **YAML Files Added to .github:** Included new YAML configuration files in the `.github` folder for CI/CD and workflow automation.
- **TTL for Long-Term Chat History:** Implemented Time-To-Live (TTL) for long-term chat history tables to support automatic cleanup.
- **MCP Filter Message Fixed:** Corrected message filtering logic for MCP server integration.
- **Hybrid Agent Episodic and Semantic Memory:** Added support for episodic and semantic memory in the hybrid agent template.


## [1.4.20]

### Changes
- **Online Evaluation for Hybrid Agent:** Added support for online evaluation workflows in hybrid agent templates and fixed issues related to evaluation with interrupt states.
- **Status Message and Referencing Agent Name Updates:** Fixed issues with the `status_message` and unified `message` key in MCP server update/delete responses; added referencing agent name for improved clarity.
- **Local MCP Server Update Fix:** Resolved an issue where updates to the local MCP server were not being applied correctly.
- **Auto-Suggestions for Hybrid Agent Templates:** Enabled auto-suggestion functionality for hybrid agent templates to improve user experience.


## [1.4.19]

### Changes
- **Time-to-Live (TTL) and Automatic Database Cleanup:** Automatically cleans up checkpoints, writes, and blobs based on TTL configuration. Older checkpoint data is backed up in a recycle database, with support for restoration based on a specified number of days.
- **Permanent Deletion Logic:** Added logic to permanently delete data from the recycle database after the configured retention period. This includes cleanup of recycled tools and agents also.
- **Unused Tools and Agents Detection:** Identifies unused tools and agents by monitoring their usage in chat inference. If a tool or agent is not used by the user within a specified threshold, it is flagged and returned in a report to the admin.


## [1.4.18]

### Changes
- **Tool Update Endpoint Status Message Fix:** Corrected a merging mistake in the tool update endpoint, ensuring the `status_message` key is properly replaced with the unified `message` key for consistent API responses.
- **MCP Code Run Endpoint Datatype Support:** Fixed issues with unsupported datatypes in the inline MCP code run endpoint; now all datatypes are handled correctly.
- **Meta Agent Metrics and LLM as Judge for Users:** Added support for meta agent metrics and LLM as Judge evaluation, making these features available for user workflows.
- **Canvas View Fix for Planner-Executor and React-Critic:** Resolved rendering and workflow issues in the canvas view for Planner-Executor and React-Critic agent templates.


## [1.4.17]

### Changes
- **Unified Response Message Key for Export Agent and Tool Endpoints:** Standardized API responses by introducing a common `message` key across export agent and add/update tool endpoints.
- **Mention Agent Application:** Enabled cross-agent inference within the same chat session, allowing users to mention and invoke other agents during an ongoing conversation.
- **Tool Update/Delete Error Handling:** Improved error handling and reliability for tool update and delete operations; adjusted `is_last` response option behavior.
- **Speech-to-Text Endpoint Updated:** Enhanced the `/transcribe` endpoint for better accuracy and stability.
- **MCP Server Support for Hybrid Agent:** Added MCP server integration to the hybrid agent template.
- **GitHub Pusher for Export Agent:** Implemented GitHub push support, updated `agent_endpoints`, and added export-and-deploy capabilities for exported agents.
- **Tool Success Messages Simplified:** Removed the tool ID from success messages for add and update operations.
- **MCP Tool Usage Check:** Added validation to ensure MCP tools are not actively used by agents before updating the file server’s `code_content`.
- **Hybrid Agent Export Support:** Enabled export functionality for the hybrid agent template.
- **AgentsExport.py Updated:** Applied necessary changes to support the new export and validation logic.


## [1.4.16]

### Changes
- **Canvas View Feature for Hybrid Agent:** Introduced a canvas view for the hybrid agent template, enabling users to visualize agent workflows and interactions.
- **Agent Onboarding/Update Success Message Simplified:** Removed the agent ID from success messages when onboarding or updating agents for a cleaner user experience.
- **Tool Validation Pop-Up Improvements:** Added a dedicated key for warning and error pop-ups and fixed issues with displaying validation errors/warnings during tool onboarding.
- **Admin Validation Logic Modified:** Updated admin validation logic and resolved issues affecting admin validation in various endpoints.
- **MCP Run Code Endpoint Enhanced:** Updated the MCP run code endpoint to accept parameters of type `int` and `float` in addition to `string`, ensuring correct argument processing.
- **Public Secret Update Endpoint Fixed:** Fixed issues with the endpoint for updating public secrets.
- **Delete Knowledge Base Endpoint Added:** Implemented a new endpoint to delete knowledge bases.


## [1.4.15]

### Changes
- **Final Response Feedback for Hybrid Agent:** Added support for feedback actions (like, dislike, regenerate) on the final response in the hybrid agent template, enabling users to provide direct feedback and request response regeneration.
- **Tool Verifier Sequential Execution for Hybrid Agent:** When tool verifier is enabled in the hybrid agent template, parallel tool calls are disabled to ensure each tool call is verified one by one, maintaining consistency with other agent templates.


## [1.4.14]

### Changes
- **Response Time for Each Query:** Added tracking and reporting of response time for every agent query to improve monitoring and performance analysis.
- **Online Evaluation for Export Agent:** Enabled online evaluation workflows for exported agents.
- **Hybrid Agent Steps Format Fix:** Corrected the steps format for hybrid agent templates to ensure consistency.
- **Data Connector SQL Injection Vulnerabilities Resolved:** Addressed and fixed SQL injection vulnerabilities in the data connector to enhance security.
- **Evaluation States in `context_flag`:** Added evaluation state tracking within the `context_flag`.
- **MCP Code Running Endpoint VM Fix:** Fixed an issue where the MCP code running endpoint was not functioning correctly in virtual machine environments.
- **Authentication Removed for Utility-Download Endpoint:** Removed authentication requirements from the utility-download endpoint to simplify access for users.


## [1.4.13]

### Changes
- **Python-Based Agent Steps Format Fix:** Updated the steps format for Python-based agent templates to ensure consistency with other agent templates.
- **Refresh Tokens for Authentication:** Implemented refresh token support for authentication, enhancing security and session management.
- **Export Agent Environment Config Issue Fixed:** Resolved an issue with environment configuration during agent export to ensure correct setup.


## [1.4.12]

### Changes
- **Export Agent Endpoints Query Params Changed to Form Data:** Updated the export agent API endpoints to accept parameters as form data instead of query parameters, improving compatibility with file uploads and simplifying client integration.
- **Created By Filter for Tool and MCP Tool Search:** Added support for filtering tools and MCP tools by the `created_by` field in the paginated search endpoints, enabling users to view resources based on creator.
- **MCP Server Tools Run Code Endpoint Added:** Introduced a new API endpoint for running code on MCP server tools, enabling direct execution and testing of tool code via the MCP server.


## [1.4.11]

### Changes
- **Example `.env` File Configuration for Export Agent:** Updated sample environment file to guide users in configuring export agent deployments.
- **Tool Feedback Loader Fix for Hybrid Agent:** Resolved issues with the tool feedback loader in hybrid agent workflows to ensure accurate feedback processing.
- **Hybrid Agent Planner Added:** Introduced a planner module for hybrid agents, enabling advanced planning capabilities within hybrid agent workflows.


## [1.4.10]

### Changes
- **Swagger UI Not Loading Fixed:** Resolved an issue where the Swagger UI was not loading properly.
- **Agent Endpoints Role Issue Fixed:** Fixed role-related issues in the agent updation and deletion endpoints.
- **Python-Based Agent Response Format Updated:** Modified chat history and agent response handling for Python-based agent templates to follow the LangChain-based template format, ensuring consistency across all agent types.
- **Old Chat List Retrieval for Python-Based Agents:** Added support for retrieving lists of previous chats by session ID for Python-based agent templates, matching the functionality available in other templates.


## [1.4.9]

### Changes
- **UI Repo Cloning Removed from Export Agent:** The export agent functionality no longer clones the UI repository as part of the export process.
- **MCP Code Server Validation Added:** Implemented validation logic for MCP code servers to ensure proper configuration and connectivity before use.
- **Test Server Tools Endpoint:** Introduced a new API endpoint that allows users to test tools available on the MCP code server, enabling quick verification of server tool functionality.


## [1.4.8]

### Changes
- **Online Evaluation Workflow Fixed for React and PEC Agent Templates:** Resolved issues in the online evaluation process for both React and Planner-Executor-Critic (PEC) agent templates.
- **Export Support for Agents with MCP Tools, Authentication, and User Uploads:** Enhanced the export functionality to support agents that utilize MCP tools, require authentication, or depend on user-uploaded files.
- **Python-Based Agent Template Enhancements:** Implemented a history retrieval mechanism for the Python-based agent template and added support for tool interrupt, enabling dynamic intervention during agent execution.
- **Tool Interrupt Support for Python-Based Tools:** Enhanced the Python-based agent template to support tool interrupt functionality, allowing dynamic intervention during the execution of Python-based tools.
- **Chat History Management for Python-Based Agents:** Added mechanisms to delete or retrieve chat history for agents using the Python-based template, improving control over conversation data.


## [1.4.7]

### Changes
- **Pure Python-Based Template Added:** Introduced a new agent template, `simple_ai_agent`, built using pure Python for lightweight and customizable agent workflows.
- **Chat State History Manager Repository Created:** Added a dedicated repository class for managing chat state history for python based agent templates.
- **Python-Based LLM Model Creation:** Implemented classes to support the creation and onboarding of LLM models using Python, enabling flexible integration of custom models.
- **Inference for Python Agent Template:** Added inference logic for the new Python-based agent template, allowing real-time interactions and task execution.
- **Chat State History Manager Updated:** Enhanced the chat state history manager repository class and added indexing for `thread_id` to improve performance and retrieval efficiency.


## [1.4.6]

### Changes
- **.py File Upload Option in Tool Onboarding:** Added support for uploading Python (`.py`) files during tool onboarding, allowing users to onboard tools directly from code files.
- **Semantic Memory Changed to User Level:** Modified semantic memory implementation to be maintained at the user level instead of the agent level, enabling shared memory across agents for each user.
- **Admin Validation in Tool and Agent Endpoints:** Implemented admin validation checks in tool and agent endpoints to ensure only authorized users can perform sensitive operations.


## [1.4.5]

### Changes
- **Cache Config and Utilities Refactored to Async:** Modified functions in cache configuration and cache utility files to use asynchronous implementations for improved performance.
- **Authentication Fixed for Download Endpoints:** Resolved authentication issues affecting download endpoints to ensure secure access.
- **All Functions Converted to Async:** Updated all relevant functions across the codebase to be asynchronous for better scalability and responsiveness.
- **Merged Intermediate Releases to Dev:** Integrated changes from intermediate releases (1.4.0A, 1.4.0B, 1.4.0C) into the development branch.
- **Online Evaluation with Inference:** Added support for running online evaluations during agent inference, enabling real-time assessment of agent outputs.
- **Schema Updates for Online Evaluation:** Updated relevant schemas to accommodate online evaluation parameters and results in API requests and responses.


## [1.4.4]

### Changes
- **Tag-Based Search for Tools and Agents:** Added support for searching tools and agents with tag-based filtering, enabling users to quickly find relevant resources by applying tag filters.
- **Conversation Summary Prompt Fine-Tuning:** Improved the prompt used for generating conversation summaries to enhance relevance and clarity of the generated summaries.
- **MongoDB Defect Fixes and API Response Updates:** Fixed defects related to MongoDB integration and updated the connect and disconnect API responses for better reliability and clearer feedback.
- **Speech-to-Text Endpoint Updated:** Enhanced the `/transcribe` endpoint for speech-to-text functionality.


## [1.4.3]

### Changes
- **Context Flag for Chat History:** Introduced a new context flag that, when set to `false`, prevents old chat history from being included in the agent's context. Chat history continues to be stored in the database, but the agent will not use it for context during inference.
- **Bi-Encoder Model Updated:** Replaced the previous bi-encoder with the already existing `all-MiniLM-L6-v2` model to improve stability and maintain consistency.
- **Cross-Encoder Model Enhanced:** Changed the cross-encoder to a more effective model for similarity score re-ranking and applied a proper sigmoid function to convert logits to probabilities in the 0-1 range.
- **Tool Validation Logic Improved:** Enhanced the tool validation process for greater accuracy and reliability.
- **Validation Prompt Refined:** Updated the validation prompt to provide clearer guidance and better detection of issues during tool onboarding.


## [1.4.2]

### Changes
- **Cache Configuration Updated:** Modified the cache configuration.
- **Cache Utilities Refactored:** Updated cache utility functions.


## [1.4.1]

### Changes
- **Malicious Code Detection for Tools:** Added a check to detect potentially malicious code before running a tool, enhancing security during tool execution.
- **Malicious Code Validation Prompt Updated:** Modified the prompt used for malicious code validation to improve detection accuracy and user guidance.
- **Tool Validation Updated:** Changed tool validation logic so that all validation checks are now treated as warnings instead of errors, allowing more flexibility during tool onboarding.


## [1.4.1*] - Release 1.4.1

### Merged
- **Main Branch Merge:** Merged the latest development changes into the `main` branch, ensuring all new features, bug fixes, and improvements are available in the primary codebase.


## [1.4.0C]

### Changes
- **Removed Chat Endpoints from Auth Exception:** Chat endpoints are now properly protected by authentication, improving security.
- **Tag Filter Issue Fixed for Agents:** Resolved an issue where tag-based filtering was not working correctly for agents.


## [1.4.0B]

### Changes
- **Canvas UI Updated:** Removed email and button elements from the canvas interface for a cleaner user experience.
- **Tags Filtering Fixed in Search:** Resolved issues with tag-based filtering in the paginated search functionality.
- **Multiple MCP Type Filter Support:** Added support for filtering by multiple `mcp_type` values in search operations.


## [1.4.0A]

### Changes
- **Context Flag for Chat History:** Introduced a new context flag that, when set to `false`, prevents old chat history from being included in the agent's context. Chat history continues to be stored in the database, but the agent will not use it for context during inference.
- **Tag-Based Search for Tools and Agents:** Added support for searching tools and agents with tag-based filtering, enabling users to quickly find relevant resources by applying tag filters.
- **Conversation Summary Prompt Fine-Tuning:** Improved the prompt used for generating conversation summaries to enhance relevance and clarity of the generated summaries.
- **Malicious Code Detection for Tools:** Added a check to detect potentially malicious code before running a tool, enhancing security during tool execution.
- **Malicious Code Validation Prompt Updated:** Modified the prompt used for malicious code validation to improve detection accuracy and user guidance.
- **Tool Validation Updated:** Changed tool validation logic so that all validation checks are now treated as warnings instead of errors, allowing more flexibility during tool onboarding.
- **Validation Prompt Refined:** Updated the validation prompt to provide clearer guidance and better detection of issues during tool onboarding.


## [1.4.0] - Release 1.4.0

### Merged
- **Main Branch Merge:** Merged the latest development changes into the `main` branch, preparing for the next release and ensuring all new features, bug fixes, and improvements are available in the primary codebase.


## [1.3.41]

### Changes
- **Ground Truth Template Added:** Introduced a new `groundtruth_template` to standardize ground truth data formatting for agent evaluation workflows.
- **Evaluation Endpoints Updated:** Refactored and enhanced evaluation-related API endpoints.
- **Authentication Error Handling Fixed:** Corrected authentication logic to ensure accurate error messages are displayed when authentication fails.
- **Feedback Learning Prompt Appended:** Updated the system prompt to include the latest feedback learning prompt, improving agent training and response quality.
- **Login Endpoints Bugs Fixed:** Resolved issues affecting login endpoints, ensuring reliable authentication and improved error handling.
- **UI Formatting Improved:** Fixed formatting inconsistencies in the user interface for a more consistent and user-friendly experience.


## [1.3.40]

### Changes
- **Token Exceed Issue Fixed in Tool Validation:** Resolved problems where tool validation failed due to token limits being exceeded.
- **Updated Tool Execution:** Segregated warnings and errors based on priority to improve clarity and troubleshooting during tool execution.
- **Knowledge Base Prompt Updated for React Agent:** Improved the prompt logic for React agent knowledge base integration to enhance context and accuracy.
- **Headers Key Enabled for MCP Config:** Added support for specifying custom headers in MCP server configuration via the `headers` key.


## [1.3.39]

### Changes
- **Feedback Learning Endpoint Updated:** The `feedback_learning_endpoint.py` now only allows updates to the `lesson` and `approved` fields, eliminating support for updating other fields.
- **Feedback Learning Schemas Simplified:** The `feedback_learning_schemas.py` has been modified to retain only the `lesson` and `approved` fields, removing all others.
- **Canvas Chat History Issues Fixed:** Addressed problems where old chat history was not properly displayed or managed within the canvas.
- **SDLC Agent Inference Endpoint Added:** Introduced a new API endpoint for SDLC agent inference which can be used without any authentication.
- **Optimized MCP `get_tools` Function Usage:** Improved the efficiency of the MCP server integration by optimizing the `get_tools` function calls during agent inference, reducing latency.
- **Execute Tool Endpoint Updated:** The API endpoint for executing tools has been updated.


## [1.3.38]

### Changes
- **Tool Validation Updated**


## [1.3.37]

### Changes
- **Canvas Rendering Issues Fixed:** Resolved problems with redundant component rendering and improved overall canvas stability.
- **Agents Updated for Data Formatting Node:** Agents are now aware of the additional node related to data formatting in the canvas.
- **Tool Verifier Plan and Canvas Compatibility:** Fixed issues where enabling the tool verifier plan affected canvas functionality; both now work seamlessly together.
- **Planner Meta Agent Prompt Updated:** Enhanced the planner meta agent prompt to ensure awareness of the canvas node.


## [1.3.36]

### Changes
- **Tool Validation on Add:** Added validation logic to ensure tools meet required criteria when being added, preventing invalid or incomplete tool configurations.


## [1.3.35]

### Changes
- **Planner Executor Critic Canvas Fix:** Fixed the issue where the Planner Executor Critic workflow was not displaying the canvas correctly.
- **ADDITIONAL_NO_PROXYS Key Added:** Introduced the `ADDITIONAL_NO_PROXYS` key in the `.env` file to specify IP addresses that should bypass proxy settings.


## [1.3.34]

### Changes
- **Canvas History Fix:** Resolved issues with canvas history tracking to ensure accurate recording and retrieval of canvas changes during agent interactions.
- **Async/Await Refactor for Redis DB:** Updated the Redis database functions to use `async`/`await`.


## [1.3.33]

### Changes
- **Redis Issues Fixed for Export Agent:** Resolved problems with Redis integration in the export agent workflow, ensuring reliable memory storage and retrieval during agent export operations.
- **MCP File Type Handling Updated:** Changed the MCP server integration to use the `-c` flag for file type specification instead of creating temporary files.


## [1.3.32]

### Changes
- **Redis Memory Implementation:** Added support for storing agent memory in Redis, enabling scalable and persistent memory management across sessions and deployments.
- **Memory Update & Delete Example Functionality:** Introduced endpoints to update and delete specific examples from agent memory, allowing for more granular control and management of stored conversational data.
- **Session ID Fix in Get Query Response Endpoint:** Fixed an issue where the `session_id` parameter was not handled correctly in the get query response endpoint, ensuring accurate retrieval of session-specific data.


## [1.3.31]

### Changes
- **MCP Server Integration:** Implemented support for using an MCP (Message Control Protocol) server within the agent framework, enabling agents to communicate and coordinate tasks through the MCP server infrastructure.


## [1.3.30]

### Changes
- **Tool Code Testing Endpoint:** Implemented a new API endpoint that allows users to test tool code directly, enabling rapid validation and debugging of custom tool implementations.
- **SSE Route Fixes and Response Compression:** Fixed issues with Server-Sent Events (SSE) routes and enabled gzip compression for API responses to improve performance and reduce bandwidth usage.
- **Session ID and Authentication Improvements:** Enhanced session ID handling, resolved logout and authentication error scenarios, and improved reliability of user authentication flows.
- **Current User Email Update:** Improved logic for updating the current user's email, ensuring accurate and consistent user information.
- **JWT Token and Swagger UI Enhancements:** Updated JWT token handling and improved Swagger UI integration for better API documentation and testing experience.
- **Output Formatting Enhancements:** Improved output formatting for agent templates and canvas text, ensuring clearer and more consistent presentation.
- **General Codebase Refinements:** Applied various reliability and performance improvements across the codebase.


## [1.3.29]

### Changes
- **LLM-Based Example Extraction from Memory:** Added functionality to extract relevant examples from agent conversations using LLMs, leveraging both episodic and semantic memory for improved context retrieval and reasoning.


## [1.3.28]

### Changes
- **Authorization and Authentication Added:** Implemented proper authorization and authentication mechanisms across the framework to ensure secure access control and protect sensitive operations.
- **Auth Integration Summary:** See [AUTH_INTEGRATION_SUMMARY.md](auth_integration_summary.md) for a detailed overview of the authentication and authorization implementation.


## [1.3.27]

### Changes
- **Ground Truth Support for Export Agent:** Added the ability to include ground truth data when exporting agents, enabling more accurate evaluation and validation of agent outputs.
- **Secret Vault Integration for Export Agent:** Integrated secret vault functionality into the export agent process, allowing secure handling and export of sensitive credentials and secrets.


## [1.3.26]

### Changes
- **Episodic and Semantic Memory for All Agent Templates:** Extended episodic and semantic memory support to all agent templates.


## [1.3.25]

### Changes
- **Configurable Redis Caching:** Added a flag in the `.env` file to enable or disable caching using Redis, allowing flexible control over caching behavior based on deployment needs.


## [1.3.24]

### Changes
- **Episodic and Semantic Memory Added for Agents:** Introduced support for both episodic and semantic memory, enabling agents to retain and utilize past experiences (episodic) as well as structured knowledge (semantic) for improved reasoning and contextual understanding.


## [1.3.23]

### Changes
- **Export Agent Enhanced with Evaluation Metrics and Data Connectors:** The export agent functionality now includes support for evaluation metrics and data connectors, enabling exported agents to leverage built-in evaluation workflows and connect to various data sources out of the box.
- **SSE Protocol Enabled for Streaming:** Implemented Server-Sent Events (SSE) protocol to stream intermediate agent steps in real-time, allowing clients to receive live updates during agent execution.


## [1.3.22]

### Changes
- **Caching Mechanism Added:** Implemented caching for tools, agents, tags data fetched from the database to improve performance and reduce redundant database queries.
- **Redis Integration for Caching:** Caching is implemented using Redis as the backend, ensuring fast access and efficient storage of tools, agents, and tags data.


## [1.3.21]

### Changes
- **Export Agent Code Updated:** Refactored the export agent functionality to incorporate recent changes in the model service and repository structure.


## [1.3.20]

### Changes
- **Available Models Configuration:** The list of available models is now set in the `.env` file, allowing for easier management and updates.
- **Models Table Removed:** The `models` table has been removed from the database as it is no longer required.
- **Model Repository Deleted:** The model repository and related code have been deleted to reflect the new configuration approach.
- **Export Agent Code Updated:** The export agent functionality now stores logs for exported agents, enabling better tracking and auditing of export operations.


## [1.3.19]

### Changes
- **Telemetry Modularization Restored and Fixed:** Reintroduced the modularized telemetry code after resolving previous issues.


## [1.3.18]

### Changes
- **Modularized User Upload File Manager Endpoints:** Refactored user upload file manager-related API endpoints using FastAPI's `APIRouter` for improved modularity and maintainability.
- **Deprecated Old User Upload File Manager Endpoints:** Marked legacy user upload file manager endpoints as deprecated in favor of the new modularized implementation.


## [1.3.17]

### Changes
- **PostgreSQL Connection Fix:** Small fix in PostgreSQL database connection logic.
- **MongoDB Database Added:** Integrated MongoDB as a supported database option, allowing users to connect and utilize MongoDB within the framework.
- **SQLite Activation Fix:** Fixed the activation process for SQLite databases, ensuring proper initialization and usage.


## [1.3.16]

### Changes
- **Modularized Utility Endpoints:** Refactored utility-related API endpoints using FastAPI's `APIRouter` for improved modularity and maintainability.
- **Export Agent Endpoint Moved:** Relocated the export agent endpoint to the `agent_endpoint` router and deprecated legacy export agent endpoints.
- **Modularized Data Connector Endpoints:** Refactored data connector-related API endpoints using FastAPI's `APIRouter` for better separation of concerns and maintainability.
- **Deprecated Old Data Connector Endpoints:** Marked legacy data connector endpoints as deprecated in favor of the new modularized implementation.


## [1.3.15]

### Chagnes
- **Modularized Evaluation Endpoints:** Refactored evaluation-related API endpoints using FastAPI's `APIRouter` for improved modularity and maintainability.
- **Deprecated Old Evaluation Endpoints:** Marked legacy evaluation endpoints as deprecated in favor of the new modularized implementation.
- **Modularized Feedback Learning Endpoints:** Refactored feedback learning-related API endpoints using FastAPI's `APIRouter` for better separation of concerns and maintainability.
- **Deprecated Old Feedback Learning Endpoints:** Marked legacy feedback learning endpoints as deprecated in favor of the new modularized implementation.


## [1.3.14]

### Changes
- **Auto Suggest Agent Queries:** Added a function and API endpoints that suggest agent queries based on the provided agentic application ID and user email.


## [1.3.13]

### Changes
- **Modularized Secrets Endpoints:** Refactored secrets-related API endpoints using FastAPI's `APIRouter` for improved modularity and maintainability.
- **Deprecated Endpoints Router:** Created a dedicated router to handle deprecated endpoints, streamlining legacy API management.


## [1.3.12]

### Changes
- **Modularized Chat and Inference Endpoints:** Refactored chat and inference-related endpoints using FastAPI's `APIRouter` for improved modularity and maintainability.
- **Deprecated Old Chat and Inference Endpoints:** Marked legacy chat and inference endpoints as deprecated in favor of the new modularized implementation.


## [1.3.11]

### Changes
- **Modularized Agent Endpoints:** Refactored agent-related endpoints using FastAPI's `APIRouter` for improved modularity and maintainability.
- **Deprecated Old Agent Endpoints:** Marked legacy agent endpoints as deprecated in favor of the new modularized implementation.


## [1.3.10]

### Changes
- **Modularized Tool Endpoints:** Refactored tool-related endpoints using FastAPI's `APIRouter` for improved modularity and maintainability.
- **Deprecated Old Tool Endpoints:** Marked legacy tool endpoints as deprecated in favor of the new modularized implementation.


## [1.3.9]

### Changes
- **Telemetry Modularization Reverted:** Rolled back the modularized telemetry code to the previous implementation.


## [1.3.8]

### Changes
- **FastAPI Endpoints Modularization Initiated:** Began modularizing FastAPI endpoints for improved maintainability and scalability.
- **App Container Introduced:** Created an `app_container` to store instances of objects such as repositories and services required throughout the application.
- **ServiceProvider Class Added:** Implemented a `ServiceProvider` class to supply getter methods for endpoint dependencies, streamlining dependency management.
- **Tag Endpoints Modularized:** Refactored tag-related endpoints using FastAPI's `APIRouter` for better separation of concerns.
- **Schema Folder Created:** Established a `schema` folder within `src` to organize all request schemas for endpoints, enhancing code structure and clarity.


## [1.3.7]

### Changes
- **Upload-and-Evaluate-JSON Endpoint Fix:** Fixed a minor issue in the upload-and-evaluate-json endpoint to ensure correct evaluation and upload functionality.
- **Meta and Planner Meta Build Chain Argument Fix:** Resolved a missing argument issue in the build chain method for meta and planner meta agent templates.


## [1.3.6]

### Changes
- **Modularized Data Connector Inference Fix:** Resolved an issue in the modularized data connector that was affecting inference operations, ensuring reliable data access and processing.
- **SQLite DB Upload Feature Added:** Introduced the ability to upload SQLite database files and connect to them directly, streamlining integration and workflow setup.


## [1.3.5]

### Changes
- **Past Conversation Handling Fix:** Applied a minor fix to improve the management of past conversation data.
- **Deleted `database_manager.py` from Root:** Removed the obsolete `database_manager.py` file from the project root to streamline the codebase and eliminate redundancy.
- **Removed Junk Endpoints for Onboard Agent and Update Agent:** Cleaned up obsolete or unused API endpoints related to onboarding and updating agents to improve codebase clarity and maintainability.


## [1.3.4]

### Changes
- **Backend Package Creation for Export Agent:** Implemented backend logic to package and export agent code as a distributable package, streamlining agent deployment and sharing.


## [1.3.3]

### Changes
- **Conversation Summary Handling Improved:** Implemented proper management of past conversation summaries and optimized the prompt used for generating conversation summaries, resulting in more accurate and relevant outputs.
- **Internal Junk Data Clearing Mechanism:** Added a mechanism to clear internal junk data that was being stored for tool interrupt operations within the internal thread of React agent instances across all templates, improving memory usage and overall stability.
- **User Preferences Management Enhanced:** Improved handling and persistence of user preferences during conversations with agents, ensuring personalized and consistent interactions throughout the session.


## [1.3.2]

### Changes
- **Export Agent Code Updated:** Refactored the export agent code to ensure consistency with the newly modularized model functions, improving maintainability and alignment across the framework.


## [1.3.1]

### Changes
- **Modularized Model Functions:** Refactored model-related functions into dedicated modules for improved maintainability and extensibility.
- **Data Connector Modularization:** Separated data connector logic into its own module, enhancing code organization and simplifying future updates.


## [1.3.0] - Release 1.3.0 (31st July, 2025)

### Merged
- **Main Branch Merge:** Merged the latest development changes into the `main` branch, preparing for the next release and ensuring all new features, bug fixes, and improvements are available in the primary codebase.


## [1.2.10]

### Changes
- **Fixed .env File:** Corrected configuration issues in the `.env` file to ensure proper environment variable loading and application stability.


## [1.2.9]

### Changes
- **Updated Output response structure, included tools_used parameter, for getting the tools used in the conversation** 


## [1.2.8]

### Changes
- **Fixed Local System Log Issue in Telemetry:** Resolved an issue with local system logging in the new modularized telemetry code to ensure logs are correctly recorded on the local system.
- **Reverted SQLite File Upload Feature:** The previously introduced "Data Connector Updated for SQLite File Upload" enhancement has been reverted and is no longer available.
- **Updated Data Connector Endpoints:** Improved and refactored the data connector endpoints.


## [1.2.7]

### Changes
- **Telemetry Code Modularized:** Refactored telemetry logic into dedicated modules for improved maintainability, extensibility, and separation of concerns across the framework.
- **Export Agent Minor Fixes:** Fixed some minor issues in the export agent for improved reliability.


## [1.2.6]

### Changes
- **Data Connector Updated for SQLite File Upload:** Enhanced the data connector to support uploading SQLite database files directly through the UI or API. Users can now provide a `.db` file, which will be securely stored and made available for agent workflows, enabling seamless integration with existing SQLite databases.


## [1.2.5]

### Changes
- **Feedback Learning and Evaluation Metrics Modularized in Export Agent:** Integrated the modularized feedback learning and evaluation metrics code into the export agent functionality for improved maintainability and extensibility.
- **Export Agent Issue Fixed:** Resolved issues in the export agent that arose due to recent modularization changes, ensuring smooth export operations.
- **Knowledge Base Endpoint Minor Fix:** Applied a minor fix to the knowledge base endpoint to improve reliability and address recent issues.


## [1.2.4]

### Changes
- **Updated Logs Database Name:** Changed the logs database name to `evaluation_logs` for improved clarity and organization.
- **LLM as Judge Evaluation Simplified:** Removed agent consistency and robustness metrics from the LLM as Judge evaluation process.
- **Configurable SBERT Model Path:** Added `SBERT_MODEL_PATH` to the `.env` file, allowing the SBERT model path to be configured as needed.


## [1.2.3]

### Changes
- **Updated Data Connector Endpoints:** Enhanced and refactored data connector endpoints for improved reliability and flexibility.
- **Configurable CORS Origins:** Modified `.env` to allow configuration of the CORS origins list, enabling UI access from specified IP addresses.
- **Speech-to-Text Endpoints Added:** Introduced new API endpoints to support speech-to-text functionality, enabling audio input processing and transcription within the framework.


## [1.2.2]

### Changes
- **Modularized Evaluation Metrics:** Refactored the evaluation metrics logic into dedicated modules for improved maintainability and extensibility.
- **Core Evaluation Service:** Introduced a `CoreEvaluationService` class to encapsulate the core evaluation logic and workflows.
- **Evaluation Service Classes:** Added specialized evaluation service classes to handle different evaluation strategies and facilitate future enhancements.


## [1.2.1]

### Changes
- **Feedback Learning Modularized:** Refactored the feedback learning logic into dedicated modules, improving code organization and making it easier to extend or maintain feedback-related workflows.


## [1.2.0] - Release 1.2.0 (25th July, 2025)

### Merged
- **Main Branch Merge:** Merged the latest development changes into the `main` branch, ensuring all new features, bug fixes, and improvements are now available in the primary codebase.


## [1.1.9]

### Changes
- **Updated Export Agents Endpoints File:** Refactored and improved the export agents endpoints to enhance reliability and maintain consistency with the latest modular code structure.
- **Added `iafbackend-deployment2.yaml` File:** Introduced a new deployment YAML file to facilitate the implementation of a CI/CD workflow for automated deployments.


## [1.1.8]

### Changes
- **Fixed Public key updation and Private Updation and Creation parts**


## [1.1.7]

### Changes
- **Database Connector Disposal Logic Updated:** Refined the `dispose_sql_engine` method in the database connector to ensure proper cleanup and disposal of SQL engine resources, preventing potential connection leaks and improving overall stability.


## [1.1.6]

### Changes
- **Export Agent Code Modularized:** Refactored the export agent functionality to use the new modularized code structure, improving maintainability and consistency across the framework.


## [1.1.5]

### Changes
- **Removed Old Inference Files:** Deleted legacy inference files following the modularization of inference logic.
- **Cleaned Up Data Connector Endpoints:** Removed obsolete endpoints related to data connectors and updated a endpoints for improved functionality and consistency.


## [1.1.4]

### Changes
- **Modularized Inference for All Templates:** Refactored inference logic for all agent templates into dedicated modules for improved maintainability and scalability.
- **FastAPI Integration:** Integrated the modularized inference code into FastAPI endpoints, enabling unified API-based access for all agent templates.


## [1.1.3]

### Changes
- **Async/Await Issue Fixed in Tool Docstring Generator:** Resolved an issue with async/await usage in the tool docstring generator module to ensure proper asynchronous execution.
- **Requirements Updated:** Updated `requirements.txt` to reflect necessary dependency changes.
- **Conversation Summary Generation Removed:** Temporarily removed the conversation summary generation feature, as the `ongoing_conversation` context provides sufficient information for now.


## [1.1.2]

### Changes
- **Modularized Inference Code:** Refactored the inference logic for both React and Multi-Agent workflows into dedicated modules, improving code organization, maintainability, and extensibility.
- **FastAPI Integration:** The modularized inference code has been integrated into FastAPI endpoints, enabling seamless API-based access for both React and Multi-Agent workflows.


## [1.1.1]

### Changes
- **Session Management for Telemetry:** Implemented session tracking within the telemetry system to associate agent activities and traces with specific user sessions for improved monitoring and diagnostics.


## [1.1.0]

### Added
- **Data Connector for Use Case:** Users can now select and connect to various databases including MySQL, SQLite, PostgreSQL, and MongoDB for their specific use cases.


## [1.0.12]

### Changes
- **Ground Truth Based Evaluation:** Introduced a new evaluation mechanism that allows agent outputs to be compared against predefined ground truth data for more accurate performance assessment.


## [1.0.11]

### Changes
- **Chat Service Integration:** Integrated the modularized Chat Service code into FastAPI endpoints of delete chat, get session and like feedback storing for react agent.


## [1.0.10]

### Changes
- **Chat Service & Chat Repositories:** Introduced a dedicated chat service and corresponding repositories to further modularize chat-related logic and data management within the framework.
- **Knowledge Base Integration for React Agent:** Added support for integrating a knowledge base with the React agent, enabling it to access and utilize stored information during task execution.


## [1.0.9]

### Changes
- **Code Modularization & OOP Refactoring:** Refactored and restructured the codebase to follow Object-Oriented Programming (OOP) principles for better maintainability and scalability for tag, tool and agent.
- **Service Layer Implementation:** Introduced modular service layers including `AgentService`, `ToolService`, and `TagService` to encapsulate business logic.
- **Repository Pattern:** Created dedicated repositories for each database table to manage data access and persistence cleanly.
- **Tool Code Processor:** Added a separate processor module for handling tool-related code operations.
- **Database Connection Pooling:** Replaced repeated database connections with a connection pool for improved performance and resource management.


## [1.0.8]

### Changes
- **Updated Telemetry Wrapper:** Fixed an issue where trace IDs were being recorded as `0s`, ensuring accurate tracing and monitoring of agent activities.
- **Public Secrets Handler** User can create secrets which are accessable by all the users, and the secrets are stored in encrypted format in the database.


## [1.0.7] - Release 1.1.0 (17th July, 2025)

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


## [1.0.0]

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


## [0.0.1] - Release 1.0.0 (30th May, 2025)

### Initial Features
- **Tool Management:** Implemented functionality to create and onboard custom tools (Python functions) for LLM agents. Tools are saved in a database, making them reusable across multiple agents.
- **Agent Templates:**
  - **React Agent:** A template for a single agent that can reason and act to accomplish tasks.
  - **Multi-Agent:** A template for a team of agents using a Planner-Executor-Critic framework. Includes an optional "human-in-the-loop" mode where users can verify the generated plan and provide feedback for replanning before execution.
- **Memory:** Enabled simple memory for agents to maintain conversation history.
- **Inference & Chat:** Users can interact with agents via chat, enabling real-time inference and task execution.
- **File Upload & Tool Integration:** Users can upload files to the server, and agents can utilize the file content through integrated tools.

