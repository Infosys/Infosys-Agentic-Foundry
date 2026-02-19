import Cookies from "js-cookie";

import pkg from "../package.json";

// Runtime environment config injected by nginx (from runtime-config.js)
// Falls back to process.env for local development
export const env = window._env_ || {};

export const APP_VERSION = pkg.version;

export const BOT = "bot";
export const USER = "user";

//   { label: "Custom Template", value: "custom_template" }

export const agentTypesDropdown = [
  { label: "Hybrid Agent", value: "hybrid_agent" },
  { label: "Meta", value: "meta_agent" },
  { label: "Meta Planner ", value: "planner_meta_agent" },
  { label: "Planner Executor", value: "planner_executor_agent" },
  { label: "Planner Executor Critic", value: "multi_agent" },
  { label: "Pipeline", value: "pipeline" },
  { label: "React", value: "react_agent" },
  { label: "React Critic", value: "react_critic_agent" },
];

export const REACT_AGENT = "react_agent";
export const MULTI_AGENT = "multi_agent";
export const META_AGENT = "meta_agent";
export const PLANNER_META_AGENT = "planner_meta_agent";
export const CUSTOM_TEMPLATE = "custom_template";
export const REACT_CRITIC_AGENT = "react_critic_agent";
export const PLANNER_EXECUTOR_AGENT = "planner_executor_agent";
export const HYBRID_AGENT = "hybrid_agent";
export const PIPELINE_AGENT = "pipeline";

export const like = "like";
export const regenerate = "regenerate";
export const dislike = "submit_feedback";

export const CHAT_BOT_DATA = "CHAT_BOT_DATA";

export const BASE_URL = env.REACT_APP_BASE_URL || process.env.REACT_APP_BASE_URL ;

export const mkDocs_baseURL = env.REACT_APP_MKDOCS_BASE_URL || process.env.REACT_APP_MKDOCS_BASE_URL;

export const liveTrackingUrl = env.REACT_APP_LIVE_TRACKING_URL || process.env.REACT_APP_LIVE_TRACKING_URL;

export const grafanaDashboardUrl = env.REACT_APP_GRAFANA_DASHBOARD_URL || process.env.REACT_APP_GRAFANA_DASHBOARD_URL;

export const APIs = {
  //Feedback Learning APIs
  GET_APPROVALS_LIST: "/feedback-learning/get/approvals-list",
  GET_APPROVALS_BY_ID: "/feedback-learning/get/approvals-by-agent/",
  UPDATE_APPROVAL_RESPONSE: "/feedback-learning/update/approval-response",
  GET_RESPONSES_DATA: "/feedback-learning/get/responses-data/",

  //Unused Items APIs
  AGENTS_UNUSED: "/agents/unused/get",
  TOOLS_UNUSED: "/tools/unused/get",
  MCP_SERVERS_UNUSED: "/tools/mcp/unused/get",

  // Default APIs
  LOGIN: "/auth/login",
  LOGOUT: "/auth/logout",
  REGISTER: "/auth/register",
  UPDATE_PASSWORD_ROLE: "/auth/update-password",
  GUEST_LOGIN: "/auth/guest-login",
  REFRESH_TOKEN: "/auth/refresh-token",

  ADD_TOOLS_WITH_FILE: "/tools/add-with-file",

  //Utility APIs
  GET_VERSION: "/utility/get/version",
  GET_MODELS: "/utility/get/models",
  UPLOAD_FILES: "/utility/files/user-uploads/upload/",
  GET_ALLUPLOADFILELIST: "/utility/files/user-uploads/get-file-structure/",
  DOWNLOAD_FILE: "/utility/files/user-uploads/download",
  DELETE_FILE: "/utility/files/user-uploads/delete/",
  UPLOAD_KB_DOCUMENT: "/utility/knowledge-base/documents/upload",
  GET_KB_LIST: "/utility/knowledge-base/list",
  TRANSCRIBE_AUDIO: "/utility/transcribe/",
  LIST_ALL_MARKDOWN_FILES: "/utility/docs/list-all-markdown-files",
  LIST_MARKDOWN_FILES_IN_DIRECTORY: "/utility/docs/list-markdown-files-in-directory/{dir_name}",

  // Installation/VM APIs
  GET_MISSING_DEPENDENCIES: "/utility/get-missing-dependencies",
  GET_INSTALLED_PACKAGES: "/utility/get/installed-packages",
  INSTALL_DEPENDENCIES: "/utility/vm/install-dependencies",
  RESTART_SERVER: "/utility/vm/restart-server",

  //Tags APIs
  GET_TAGS: "/tags/get",

  //Evaluation APIs
  PROCESS_UNPROCESSED: "/evaluation/process-unprocessed",
  GET_EVALUATION_DATA: "/evaluation/get/data",
  GET_TOOL_METRICS: "/evaluation/get/tool-metrics",
  GET_AGENT_METRICS: "/evaluation/get/agent-metrics",
  UPLOAD_AND_EVALUATE_JSON: "/evaluation/upload-and-evaluate-json",
  DOWNLOAD_RESULTS: "/evaluation/download-result",
  DOWNLOAD_TEMPLATE: "/evaluation/download-groundtruth-template",
  DOWNLOAD_CONSISTENCY_TEMPLATE: "/download-consistency-template",
  SCORE_AND_DOWNLOAD_BASE: "/evaluation/agent/",
  CONSISTENCY_PREVIEW_RESPONSES: "/evaluation/consistency/preview-responses",
  CONSISTENCY_RERUN_RESPONSES: "/evaluation/consistency/rerun-response",
  CONSISTENCY_APPROVE_RESPONSES: "/evaluation/consistency/approve-responses",
  CONSISTENCY_DELETE_AGENT: "/evaluation/delete-agent/",
  CONSISTENCY_AVAILABLE_AGENTS: "/evaluation/available_agents/",
  CONSISTENCY_GENERATE_UPDATE_PREVIEW: "/evaluation/generate-update-preview/",
  ROBUSTNESS_PREVIEW_QUERIES: "/evaluation/robustness/preview-queries/",
  ROBUSTNESS_APPROVE_EVALUATION: "/evaluation/approve-robustness-evaluation/",

  // Chat APIs
  CHAT_INFERENCE: "/chat/inference",
  GET_FEEDBACK_RESPONSE: "/chat/get/feedback-response/",
  GET_CHAT_HISTORY: "/chat/get/history",
  CLEAR_CHAT_HISTORY: "/chat/clear-history",
  GET_OLD_CONVERSATIONS: "/chat/get/old-conversations",
  GET_NEW_SESSION_ID: "/chat/get/new-session-id/",
  SUGGESTIONS: "/chat/auto-suggest-agent-queries",
  // Memory store example endpoint
  MEMORY_STORE_EXAMPLE: "/chat/memory/store-example",

  // Tools APIs
  GET_TOOLS_SEARCH_PAGINATED: "/tools/get/search-paginated/",
  GET_TOOLS_AND_VALIDATORS_SEARCH_PAGINATED: "/tools/get/tools-and-validators-search-paginated/",
  ADD_TOOLS: "/tools/add",
  GET_TOOLS_BY_LIST: "/tools/get/by-list",
  UPDATE_TOOLS: "/tools/update/",
  DELETE_TOOLS: "/tools/delete/",
  // Validator-specific tool segregation
  // Backend expected to return only non-validator tools for existing endpoints.
  // New endpoints explicitly differentiate validator tools so UI can fetch them for validation patterns.
  GET_VALIDATOR_TOOLS: "/tools/validators/get",
  TOOLS_BY_TAGS: "/tools/get/by-tags",
  GET_TOOLS_BY_ID: "/tools/get/{tool_id}",
  TOOLS_RECYCLE_BIN: "/tools/recycle-bin/get",
  RESTORE_TOOLS: "/tools/recycle-bin/restore/",
  DELETE_TOOLS_PERMANENTLY: "/tools/recycle-bin/permanent-delete/",
  EXECUTE_CODE: "/tools/execute",
  INLINE_MCP_RUN: "/tools/inline-mcp/run",
  PENDING_MODULES: "/tools/pending-modules",

  // Agents APIs
  ONBOARD_AGENTS: "/agents/onboard",
  GET_AGENTS_BY_DETAILS: "/agents/get/details-for-chat-interface",
  GET_AGENTS_BY_ID: "/agents/get/",
  GET_AGENTS_BY_LIST: "/agents/get/by-list",
  UPDATE_AGENTS: "/agents/update",
  DELETE_AGENTS: "/agents/delete/",
  GET_AGENTS_SEARCH_PAGINATED: "/agents/get/search-paginated/",
  GET_AGENTS_BY_TAGS: "/agents/get/by-tags",
  AGENTS_RECYCLE_BIN: "/agents/recycle-bin/get",
  RESTORE_AGENTS: "/agents/recycle-bin/restore/",
  DELETE_AGENTS_PERMANENTLY: "/agents/recycle-bin/permanent-delete/",
  EXPORT_AGENTS: "/agents/export",
  GET_TOOLS_MAPPED_BY_AGENT: "/agents/tools-mapped/",

  // Agent Assignment APIs
  GET_USERS: "/user-agent-access/all",
  GRANT_USER_AGENT_ACCESS: "/user-agent-access/grant",
  REVOKE_USER_AGENT_ACCESS: "/user-agent-access/revoke",
  GET_USER_AGENT_ACCESS: "/user-agent-access/user/",
  GET_GROUPS: "/groups/get/list",
  GET_DOMAINS: "/domains/get-all-domains",
  GET_DOMAINS_BY_USER: "/domains/by-user/",
  CREATE_DOMAIN: "/domains/create-domain",
  GET_AGENT_ASSIGNMENTS: "/agents/assignments/get",
  CREATE_AGENT_ASSIGNMENT: "/agents/assignments/create",
  UPDATE_AGENT_ASSIGNMENT: "/agents/assignments/update",
  UPDATE_DOMAIN: "/domains/update-domain/{domain_name}",
  DELETE_DOMAIN: "/domains/delete-domain/{domain_name}",
  DELETE_AGENT_ASSIGNMENT: "/agents/assignments/delete",

  // Role Management APIs
  GET_ROLES: "/roles/list",
  ADD_ROLE: "/roles/add",
  DELETE_ROLE: "/roles",

  // Role Assignment APIs
  GET_ROLE_ASSIGNMENTS: "/role-agent-access/get/assignments",
  CREATE_ROLE_ASSIGNMENT: "/role-agent-access/create",
  DELETE_ROLE_ASSIGNMENT: "/role-agent-access/delete",
  ASSIGN_USER_ROLE: "/roles/users/assign",

  // Role Permissions APIs
  GET_ROLE_PERMISSIONS: "/roles/permissions",
  CREATE_ROLE_PERMISSIONS: "/roles/permissions/create",
  UPDATE_ROLE_PERMISSIONS: "/roles/permissions/update",
  DELETE_ROLE_PERMISSIONS: "/roles/permissions/delete",
  SET_ROLE_PERMISSIONS: "/roles/permissions/set",

  // MCP APIs
  MCP_ADD_TOOLS: "/tools/mcp/add",
  MCP_DELETE_TOOLS: "/tools/mcp/delete/",
  MCP_GET_ALL_SERVERS: "/tools/mcp/get/search-paginated/",
  MCP_UPDATE_SERVER: "/tools/mcp/update/",
  MCP_LIVE_TOOL_DETAIL: "/tools/mcp/get/live-tool-details/",
  MCP_SERVERS_RECYCLE_BIN: "/tools/mcp/recycle-bin/get",
  MCP_RESTORE_SERVERS: "/tools/mcp/recycle-bin/restore/",
  MCP_DELETE_SERVERS_PERMANENTLY: "/tools/mcp/recycle-bin/permanent-delete/",

  //Data Connector APIs
  GET_ACTIVE_CONNECTIONS: "/data-connector/get/active-connection-names",
  CONNECT_DATABASE: "/data-connector/connect",
  GENERATE_QUERY: "/data-connector/generate-query",
  RUN_QUERY: "/data-connector/run-query",
  DISCONNECT_DATABASE: "/data-connector/disconnect",
  AVAILABLE_CONNECTIONS: "/data-connector/connections",
  SQL_CONNECTIONS: "/data-connector/connections/sql",
  MONGODB_CONNECTIONS: "/data-connector/connections/mongodb",
  MONGODB_OPERATION: "/data-connector/mongodb-operation/",
  ACTIVATE_CONNECTION: "/data-connector/connect-by-name",

  // Secrets APIs
  ADD_SECRET: "/secrets/create",
  DELETE_SECRET: "/secrets/delete",
  UPDATE_SECRET: "/secrets/update",
  PUBLIC_ADD_SECRET: "/secrets/public/create",
  PUBLIC_UPDATE_SECRET: "/secrets/public/update",
  PUBLIC_DELETE_SECRET: "/secrets/public/delete",
  GET_SECRETS: "/secrets/list",
  GET_PUBLIC_SECRETS: "/secrets/public/list",
  SECRETS_GET: "/secrets/get",
  PUBLIC_SECRETS_GET: "/secrets/public/get",
  HEALTH_SECRETS: "/secrets/health",

  // Pipeline APIs
  PIPELINE_CREATE: "/pipelines/create",
  PIPELINE_GET_ALL: "/pipelines/get",
  PIPELINE_GET_PAGINATED: "/pipelines/get/search-paginated/",
  PIPELINE_GET_BY_ID: "/pipelines/get/",
  PIPELINE_UPDATE: "/pipelines/update/",
  PIPELINE_DELETE: "/pipelines/delete/",
  PIPELINE_EXECUTE: "/pipelines/{pipeline_id}/execute",
  PIPELINE_EXECUTE_SYNC: "/pipelines/{pipeline_id}/execute/sync",
  PIPELINE_RESUME: "/pipelines/executions/{execution_id}/resume",
  PIPELINE_EXECUTION_STATUS: "/pipelines/executions/{execution_id}/status",
  PIPELINE_GET_EXECUTIONS: "/pipelines/{pipeline_id}/executions",
  PIPELINE_AVAILABLE_AGENTS: "/pipelines/available-agents",
};

// export const sessionId = "test_101";
const user_session = Cookies.get("user_session");
export const sessionId = user_session;

export const userEmail = "test";

export const feedBackMessage = "I apologize for the previous response. Could you please provide more details on what went wrong? Your feedback will help us improve.";

export const likeMessage = "Thanks for the like! We're glad you found the response helpful. If you have any more questions or need further assistance, feel free to ask!";
export const SystemPromptsPlannerMetaAgent = [
  {
    label: "SYSTEM_PROMPT_META_AGENT_PLANNER",
    value: "SYSTEM_PROMPT_META_AGENT_PLANNER",
  },
  {
    label: "SYSTEM_PROMPT_META_AGENT_RESPONDER",
    value: "SYSTEM_PROMPT_META_AGENT_RESPONDER",
  },
  {
    label: "SYSTEM_PROMPT_META_AGENT_SUPERVISOR",
    value: "SYSTEM_PROMPT_META_AGENT_SUPERVISOR",
  },
];
export const SystemPromptsMultiAgent = [
  { label: "SYSTEM PROMPT GENERAL LLM", value: "SYSTEM_PROMPT_GENERAL_LLM" },
  { label: "SYSTEM PROMPT CRITIC AGENT", value: "SYSTEM_PROMPT_CRITIC_AGENT" },
  {
    label: "SYSTEM PROMPT PLANNER AGENT",
    value: "SYSTEM_PROMPT_PLANNER_AGENT",
  },
  {
    label: "SYSTEM PROMPT EXECUTOR AGENT",
    value: "SYSTEM_PROMPT_EXECUTOR_AGENT",
  },
  {
    label: "SYSTEM PROMPT REPLANNER AGENT",
    value: "SYSTEM_PROMPT_REPLANNER_AGENT",
  },
  {
    label: "SYSTEM PROMPT RESPONSE GENERATOR AGENT",
    value: "SYSTEM_PROMPT_RESPONSE_GENERATOR_AGENT",
  },
  {
    label: "SYSTEM PROMPT CRITIC BASED PLANNER AGENT",
    value: "SYSTEM_PROMPT_CRITIC_BASED_PLANNER_AGENT",
  },
];

export const branchInteruptKey = "branch:interrupt_node:interrupt_node_decision:feedback_collector";
export const branchInteruptValue = "interrupt_node";

export const customTemplatId = "custom_template_1";

export const roleOptions = ["Admin", "Developer", "User"];

export const systemPromptReactCriticAgents = [
  { label: "SYSTEM PROMPT CTRITIC AGENT", value: "SYSTEM_PROMPT_CRITIC_AGENT" },
  {
    label: "SYSTEM PROMPT EXECUTOR AGENT",
    value: "SYSTEM_PROMPT_EXECUTOR_AGENT",
  },
];

export const systemPromptPlannerExecutorAgents = [
  { label: "SYSTEM PROMPT GENERAL LLM", value: "SYSTEM_PROMPT_GENERAL_LLM" },
  {
    label: "SYSTEM PROMPT PLANNER AGENT",
    value: "SYSTEM_PROMPT_PLANNER_AGENT",
  },
  {
    label: "SYSTEM PROMPT EXECUTOR AGENT",
    value: "SYSTEM_PROMPT_EXECUTOR_AGENT",
  },
  {
    label: "SYSTEM PROMPT REPLANNER AGENT",
    value: "SYSTEM_PROMPT_REPLANNER_AGENT",
  },
  {
    label: "SYSTEM PROMPT RESPONSE GENERATOR AGENT",
    value: "SYSTEM_PROMPT_RESPONSE_GENERATOR_AGENT",
  },
];