import Cookies from "js-cookie";
import { patchCookiesForPortScoping } from "./utils/cookieUtils";
import pkg from "../package.json";

// Ensure cookie scoping is applied before any Cookies.get() at module level
patchCookiesForPortScoping();

// Runtime environment config injected by nginx (from runtime-config.js)
// Falls back to process.env for local development
export const env = window._env_ || {};

export const APP_VERSION = pkg.version;

export const BOT = "bot";
export const USER = "user";

export const agentTypesDropdown = [
  { label: "Hybrid Agent", value: "hybrid_agent" },
  { label: "Meta", value: "meta_agent" },
  { label: "Meta Planner ", value: "planner_meta_agent" },
  { label: "Planner Executor", value: "planner_executor_agent" },
  { label: "Planner Executor Critic", value: "multi_agent" },
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
export const WORKFLOW_AGENT = "workflow";

export const like = "like";
export const regenerate = "regenerate";
export const dislike = "submit_feedback";

export const CHAT_BOT_DATA = "CHAT_BOT_DATA";

export const BASE_URL = env.REACT_APP_BASE_URL || process.env.REACT_APP_BASE_URL ;

export const mkDocs_baseURL = env.REACT_APP_MKDOCS_BASE_URL || process.env.REACT_APP_MKDOCS_BASE_URL;

export const liveTrackingUrl = env.REACT_APP_LIVE_TRACKING_URL || process.env.REACT_APP_LIVE_TRACKING_URL;

export const grafanaDashboardUrl = env.REACT_APP_GRAFANA_DASHBOARD_URL || process.env.REACT_APP_GRAFANA_DASHBOARD_URL;

// Default blocked SQL commands for data connectors
export const DEFAULT_BLOCKED_SQL_COMMANDS = [
  "DROP", "DELETE", "UPDATE", "INSERT", "ALTER", "CREATE",
  "TRUNCATE", "EXEC", "EXECUTE", "GRANT", "REVOKE", "COMMIT", "ROLLBACK",
];

export const APIs = {
  RESTART_SERVER: "/utility/vm/restart-server",
  INSTALL_DEPENDENCIES: "/utility/vm/install-dependencies",

  // Inference Config APIs
  GET_INFERENCE_CONFIG_LIMITS: "/admin/config/limits",
  UPDATE_INFERENCE_CONFIG_LIMITS: "/admin/config/limits",
  RESET_INFERENCE_CONFIG_LIMITS: "/admin/config/limits/reset",

  //Feedback Learning APIs
  GET_APPROVALS_LIST: "/feedback-learning/get/approvals-list",
  GET_APPROVALS_BY_ID: "/feedback-learning/get/approvals-by-agent/",
  UPDATE_APPROVAL_RESPONSE: "/feedback-learning/update/approval-response",
  GET_RESPONSES_DATA: "/feedback-learning/get/responses-data/",
  GET_ALL_FEEDBACKS: "/feedback-learning/get/all-feedbacks",
  GET_FEEDBACK_STATS: "/feedback-learning/get/feedback-stats",

  //Unused Items APIs
  AGENTS_UNUSED: "/agents/unused/get",
  TOOLS_UNUSED: "/tools/unused/get",
  SERVERS_UNUSED: "/tools/mcp/unused/get",

  // Default APIs
  LOGIN: "/auth/login",
  LOGOUT: "/auth/logout",
  REGISTER: "/auth/register",
  REGISTER_SUPERADMIN: "/auth/register-superadmin",
  SUPERADMIN_EXISTS: "/auth/superadmin/exists",
  ASSIGN_ROLE_DEPARTMENT: "/auth/assign-role-department",
  UPDATE_PASSWORD_ROLE: "/auth/update-password",
  CHANGE_PASSWORD: "/auth/change-password",
  GUEST_LOGIN: "/auth/guest-login",
  REFRESH_TOKEN: "/auth/refresh-token",
  GET_ADMIN_CONTACTS: "/auth/admin-contacts",
  GET_REGISTRATION_REQUESTS: "/auth/registration-requests",
  APPROVE_REGISTRATION_REQUEST: "/auth/registration-requests/approve",
  REJECT_REGISTRATION_REQUEST: "/auth/registration-requests/reject",

  //Utility APIs
  GET_VERSION: "/utility/get/version",
  GET_MODELS: "/utility/get/models",
  GET_INSTALLED_PACKAGES: "/utility/get/installed-packages",
  GET_MISSING_DEPENDENCIES: "/utility/get-missing-dependencies",
  GET_PENDING_MODULES: "/tools/pending-modules",
  UPLOAD_FILES: "/utility/files/user-uploads/upload/",
  GET_ALLUPLOADFILELIST: "/utility/files/user-uploads/get-file-structure/",
  DOWNLOAD_FILE: "/utility/files/user-uploads/download",
  UTILITY_FILES_PREFIX: "/utility/files/",
  DELETE_FILE: "/utility/files/user-uploads/delete/",
  // Knowledge Base APIs
  KB_UPLOAD_DOCUMENTS: "/utility/knowledge-base/documents/upload",
  KB_GET_LIST: "/utility/knowledge-base/list",
  KB_GET_BY_ID: "/utility/knowledge-base/get/",
  KB_GET_BY_LIST: "/utility/knowledge-base/get/by-list",
  KB_GET_BY_LIST_FOR_AGENT: "/utility/knowledge-base/get/by-list-for-agent",
  KB_DELETE: "/utility/remove-knowledgebases",
  KB_UPDATE_SHARING: "/utility/knowledge-base/",
  
  CONVERSATION_CLEANUP_STATUS: "/utility/conversation-cleanup/status",
  CONVERSATION_CLEANUP: "/utility/conversation-cleanup",

  // System Cleanup & Backup APIs
  BACKUP_AND_EXPORT: "/utility/backup-and-export",
  CLEANUP_PREVIEW: "/utility/cleanup/preview",
  CLEANUP_EXECUTE: "/utility/cleanup/execute",
  CLEANUP_REPORT_DOWNLOAD: "/utility/cleanup/report/download/",
  CLEANUP_REPORTS_LIST: "/utility/cleanup/reports/list",

  TRANSCRIBE_AUDIO: "/utility/transcribe/",
  LIST_ALL_MARKDOWN_FILES: "/utility/docs/list-all-markdown-files",
  LIST_MARKDOWN_FILES_IN_DIRECTORY: "/utility/docs/list-markdown-files-in-directory/{dir_name}",

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
  CONSISTENCY_DELETE_AGENT: "/evaluation/delete-agent",
  CONSISTENCY_AVAILABLE_AGENTS: "/evaluation/available_agents/",
  CONSISTENCY_GENERATE_UPDATE_PREVIEW: "/evaluation/generate-update-preview/",
  ROBUSTNESS_PREVIEW_QUERIES: "/evaluation/robustness/preview-queries/",
  ROBUSTNESS_APPROVE_EVALUATION: "/evaluation/approve-robustness-evaluation/",

  // Chat APIs
  CHAT_INFERENCE: "/chat/inference",
  CHAT_FILES_UPLOAD: "/chat/files/upload",
  GET_FEEDBACK_RESPONSE: "/chat/get/feedback-response/",
  GET_CHAT_HISTORY: "/chat/get/history",
  CLEAR_CHAT_HISTORY: "/chat/clear-history",
  GET_OLD_CONVERSATIONS: "/chat/get/old-conversations",
  GET_NEW_SESSION_ID: "/chat/get/new-session-id/",
  SUGGESTIONS: "/chat/auto-suggest-agent-queries",
  // Memory store example endpoint
  MEMORY_STORE_EXAMPLE: "/chat/memory/store-example",
  // Viber agent ID for floating chatbot
  GET_VIBER_AGENT_ID: "/agents/viber-agent-id",

  // Tools APIs
  GET_TOOLS_SEARCH_PAGINATED: "/tools/get/search-paginated/",
  GET_TOOLS_AND_VALIDATORS_SEARCH_PAGINATED: "/tools/get/tools-and-validators-search-paginated/",
  ADD_TOOLS: "/tools/add",
  ADD_TOOLS_MESSAGE_QUEUE: "/tools/add-message-queue",
  GET_TOOLS_BY_LIST: "/tools/get/by-list",
  UPDATE_TOOLS: "/tools/update/",
  DELETE_TOOLS: "/tools/delete",
  // Validator-specific tool segregation
  // Backend expected to return only non-validator tools for existing endpoints.
  // New endpoints explicitly differentiate validator tools so UI can fetch them for validation patterns.
  GET_VALIDATOR_TOOLS: "/tools/validators/get",
  TOOLS_BY_TAGS: "/tools/get/by-tags",
  GET_TOOLS_BY_ID: "/tools/get/",

  // Tool Version Management APIs
  TOOL_VERSION_SAVE: "/tools/generate/versions/save",
  TOOL_VERSION_LIST: "/tools/generate/versions/list/",
  TOOL_VERSION_GET: "/tools/generate/versions/get/",
  TOOL_VERSION_CURRENT: "/tools/generate/versions/current/",
  TOOL_VERSION_SWITCH: "/tools/generate/versions/switch",
  TOOL_VERSION_LABEL: "/tools/generate/versions/label",
  TOOL_VERSION_DELETE: "/tools/generate/versions/delete",
  TOOL_VERSION_CLEAR: "/tools/generate/versions/clear/",
  TOOL_VERSION_COUNT: "/tools/generate/versions/count/",
  TOOL_CONVERSATION_HISTORY: "/tools/generate/conversation/history/",
  TOOL_CONVERSATION_LATEST_CODE: "/tools/generate/conversation/latest-code/",
  TOOL_CONVERSATION_CLEAR: "/tools/generate/conversation/clear/",

  TOOLS_RECYCLE_BIN: "/tools/recycle-bin/get",
  TOOLS_RECYCLE_BIN_VERSIONS: "/tools/recycle-bin/versions",
  TOOLS_RECYCLE_BIN_TOOL_VERSIONS: "/tools/recycle-bin/",
  RESTORE_TOOLS: "/tools/recycle-bin/restore/",
  RESTORE_TOOL_VERSION: "/tools/recycle-bin/versions/restore/",
  DELETE_TOOLS_PERMANENTLY: "/tools/recycle-bin/permanent-delete/",
  DELETE_TOOL_VERSION_PERMANENTLY: "/tools/recycle-bin/versions/permanent-delete/",
  EXECUTE_CODE: "/tools/execute",
  EXPORT_TOOLS: "/tools/export",
  IMPORT_TOOLS_PREVIEW: "/tools/import-preview",
  IMPORT_TOOLS: "/tools/import",
  INLINE_MCP_RUN: "/tools/inline-mcp/run",
  INLINE_MCP_RUN_REMOTE: "/tools/inline-mcp/run-remote",

  // Agents APIs
  ONBOARD_AGENTS: "/agents/onboard",
  GET_AGENTS_BY_DETAILS: "/agents/get/details-for-chat-interface",
  GET_AGENTS_BY_ID: "/agents/get/",
  GET_AGENTS_BY_LIST: "/agents/get/by-list",
  UPDATE_AGENTS: "/agents/update",
  DELETE_AGENTS: "/agents/delete",
  GET_AGENTS_SEARCH_PAGINATED: "/agents/get/search-paginated/",
  GET_AGENTS_BY_TAGS: "/agents/get/by-tags",
  AGENTS_RECYCLE_BIN: "/agents/recycle-bin/get",
  RESTORE_AGENTS: "/agents/recycle-bin/restore/",
  DELETE_AGENTS_PERMANENTLY: "/agents/recycle-bin/permanent-delete/",
  EXPORT_AGENTS: "/agents/export",
  GET_TOOLS_MAPPED_BY_AGENT: "/agents/tools-mapped/",

  // Sharing APIs
  GET_TOOL_SHARING: "/tools/",           // GET /tools/{tool_id}/sharing-info
  UPDATE_TOOL_SHARING: "/tools/",         // PUT /tools/{tool_id}/sharing
  GET_AGENT_SHARING: "/agents/",          // GET /agents/{agent_id}/sharing-info
  UPDATE_AGENT_SHARING: "/agents/",       // PUT /agents/{agent_id}/sharing
  GET_SERVER_SHARING: "/tools/mcp/",      // GET /tools/mcp/{mcp_tool_id}/sharing-info
  UPDATE_SERVER_SHARING: "/tools/mcp/",   // PUT /tools/mcp/{mcp_tool_id}/sharing
  GET_KB_SHARING: "/utility/knowledge-base/",     // GET /utility/knowledge-base/{kb_id}/sharing-info
  UPDATE_KB_SHARING: "/utility/knowledge-base/",   // PUT /utility/knowledge-base/{kb_id}/sharing
  GET_WORKFLOW_SHARING: "/workflows/",    // GET /workflows/{workflow_id}/sharing
  UPDATE_WORKFLOW_SHARING: "/workflows/", // PUT /workflows/{workflow_id}/sharing

  // MCP Server Recycle Bin APIs
  SERVERS_RECYCLE_BIN: "/tools/mcp/recycle-bin/get",
  RESTORE_SERVERS: "/tools/mcp/recycle-bin/restore/",
  DELETE_SERVERS_PERMANENTLY: "/tools/mcp/recycle-bin/permanent-delete/",

  // Agent Assignment APIs
  GET_USERS: "/user-agent-access/all",
  GRANT_USER_AGENT_ACCESS: "/user-agent-access/grant",
  REVOKE_USER_AGENT_ACCESS: "/user-agent-access/revoke",
  GET_USER_AGENT_ACCESS: "/user-agent-access/user/",
  
  // Group Management APIs
  GET_GROUPS: "/groups/get-all-groups",
  GET_GROUP_BY_NAME: "/groups/get-group-by-name/",
  GET_GROUPS_SEARCH_PAGINATED: "/groups/get/search-paginated/",
  GET_GROUPS_BY_USER: "/groups/by-user/",
  GET_GROUPS_BY_AGENT: "/groups/by-agent/",
  CREATE_GROUP: "/groups/create-group",
  UPDATE_GROUP: "/groups/update-group/",
  DELETE_GROUP: "/groups/delete-group/",
  ADD_USERS_TO_GROUP: "/groups/{group_name}/add-users",
  REMOVE_USERS_FROM_GROUP: "/groups/{group_name}/users",
  ADD_AGENTS_TO_GROUP: "/groups/{group_name}/agents",
  REMOVE_AGENTS_FROM_GROUP: "/groups/{group_name}/agents",
  GROUP_ADD_SECRET: "/groups/{group_name}/secrets",
  GROUP_UPDATE_SECRET: "/groups/{group_name}/secrets/{key_name}",
  GROUP_DELETE_SECRET: "/groups/{group_name}/secrets/{key_name}",
  GROUP_DELETE_SECRETS_BULK: "/groups/{group_name}/secrets/delete-bulk",
  GET_GROUP_SECRETS: "/groups/{group_name}/secrets",
  GROUP_SECRETS_GET: "/groups/{group_name}/secrets/{key_name}",

  // Domain Management APIs (legacy)
  GET_DOMAINS: "/domains/get-all-domains",
  GET_DOMAINS_BY_USER: "/domains/by-user/",
  GET_DOMAINS_SEARCH_PAGINATED: "/domains/get/search-paginated/",
  CREATE_DOMAIN: "/domains/create-domain",
  GET_AGENT_ASSIGNMENTS: "/agents/assignments/get",
  CREATE_AGENT_ASSIGNMENT: "/agents/assignments/create",
  UPDATE_AGENT_ASSIGNMENT: "/agents/assignments/update",
  UPDATE_DOMAIN: "/domains/update-domain/{domain_name}",
  DELETE_DOMAIN: "/domains/delete-domain/{domain_name}",
  DELETE_AGENT_ASSIGNMENT: "/agents/assignments/delete",


  RD_GET_ACCESS_KEYS: "/resource-dashboard/access-keys",
  RD_CREATE_ACCESS_KEY: "/resource-dashboard/access-keys",
  RD_GET_ACCESS_KEY_DETAILS: "/resource-dashboard/access-keys/",
  RD_DELETE_ACCESS_KEY: "/resource-dashboard/access-keys/",
  RD_GET_ACCESS_KEY_TOOLS: "/resource-dashboard/access-keys/", // {access_key}/tools
  RD_UPDATE_MY_ACCESS: "/resource-dashboard/access-keys/", // PUT {access_key}/my-access
  RD_GET_MY_FULL_ACCESS: "/resource-dashboard/access-keys/", // GET {access_key}/my-access/full
  RD_GET_MY_ACCESS_KEYS: "/resource-dashboard/my-access-keys",
  RD_GET_MY_ACCESS_KEYS_FULL: "/resource-dashboard/my-access-keys/full",

  GET_ACCESS_KEYS: "/resource-allocation/access-keys",
  DELETE_ACCESS_KEY: "/resource-allocation/access-keys/",
  GET_ACCESS_KEY_USERS: "/resource-allocation/access-keys/",
  UPDATE_ACCESS_KEY_USERS: "/resource-allocation/access-keys/",
  GET_USER_VALUES: "/resource-allocation/access-keys/",
  REMOVE_USER_FROM_ACCESS_KEY: "/resource-allocation/access-keys/",
  UPDATE_USER_ACCESS: "/resource-allocation/access-keys/",
  BULK_ASSIGN_VALUES: "/resource-allocation/access-keys/",

  // My Requests APIs
  GET_MY_REQUESTS: "/auth/my-requests",
  REQUEST_DEPARTMENT_ACCESS: "/auth/request-department-access",

  // Department Management APIs
  GET_DEPARTMENTS: "/auth/departments",
  GET_DEPARTMENTS_LIST: "/departments/list",
  GET_DEPARTMENT_USERS: "/departments/{department_name}/users",
  SET_USER_ACTIVE_STATUS: "/auth/users/set-active-status",
  ADD_DEPARTMENT: "/departments/add",
  DELETE_DEPARTMENT: "/departments/",
  GET_DEPARTMENT_ROLES: "/departments/",
  ADD_DEPARTMENT_ROLE: "/departments/",
  DELETE_DEPARTMENT_ROLE: "/departments/",

  // Role Management APIs
  GET_ROLES: "/roles/list",
  ADD_ROLE: "/roles/add",
  DELETE_ROLE: "/departments",
  UPDATE_USER_ROLE: "/auth/users/update-role",

  // Role Assignment APIs
  GET_ROLE_ASSIGNMENTS: "/role-agent-access/get/assignments",
  CREATE_ROLE_ASSIGNMENT: "/role-agent-access/create",
  DELETE_ROLE_ASSIGNMENT: "/role-agent-access/delete",
  ASSIGN_USER_ROLE: "/roles/users/assign",

  // Role Permissions APIs
  GET_ROLE_PERMISSIONS: "/roles/permissions/get",
  CREATE_ROLE_PERMISSIONS: "/roles/permissions/create",
  UPDATE_ROLE_PERMISSIONS: "/roles/permissions/update",
  DELETE_ROLE_PERMISSIONS: "/roles/permissions/delete",
  SET_ROLE_PERMISSIONS: "/roles/permissions/set",

  // MCP APIs
  MCP_ADD_TOOLS: "/tools/mcp/add",
  MCP_DELETE_TOOLS: "/tools/mcp/delete/",
  MCP_GET_ALL_SERVERS: "/tools/mcp/get/search-paginated/",
  MCP_UPDATE_SERVER: "/tools/mcp/update/",
  MCP_UPDATE_REMOTE_URL: "/tools/mcp/update-remote-url/",
  MCP_SERVERS_UNUSED: "/tools/mcp/unused/get",
  MCP_LIVE_TOOL_DETAIL: "/tools/mcp/get/live-tool-details/",
  MCP_GET_SERVER_BY_ID: "/tools/mcp/get/",
  MCP_EXPORT_SERVERS: "/tools/mcp/export",
  MCP_IMPORT_SERVERS: "/tools/mcp/import",
  MCP_TEST_TOOL: "/tools/mcp/test/",
  MCP_UPDATE_MODULE_CONFIG: "/tools/mcp/update-module-config/",
   MCP_CONVERSION_GENERATE_SERVER: "/mcp-conversion/generate-server-from-all",

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
  // DB Details, Blocked Commands & Schema APIs
  GET_DB_DETAILS: "/data-connector/get-db-details/",                 // GET /data-connector/get-db-details/{connection_name}
  GET_BLOCKED_COMMANDS: "/data-connector/blocked-commands/",         // GET /data-connector/blocked-commands/{connection_name}
  UPDATE_BLOCKED_COMMANDS: "/data-connector/blocked-commands/",      // PUT /data-connector/blocked-commands/{connection_name}
  REGENERATE_SCHEMA_SAMPLES: "/data-connector/regenerate-schema-samples/", // POST /data-connector/regenerate-schema-samples/{connection_name}
  STORE_DB_SCHEMA: "/data-connector/store-db-schema",
  STORE_DB_SAMPLES: "/data-connector/store-db-samples",
  LIST_DB_FILES: "/data-connector/list-db-files",
  CLEAR_DB_FILES: "/data-connector/clear-db-files/",                // DELETE /data-connector/clear-db-files/{connection_name}
  CLEAR_ALL_DB_FILES: "/data-connector/clear-all-db-files",

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

  // Workflow APIs
  WORKFLOW_CREATE: "/workflows/create",
  WORKFLOW_GET_ALL: "/workflows/get",
  WORKFLOW_CHAT: "/tools/generate/workflow/chat",
  CONVERSATION_HISTORY: "/tools/generate/conversation/history/",
  DELETE_TOOL_BOT_CONVERSATION: "/tools/generate/conversation/clear/{session_id}",
  WORKFLOW_GET_PAGINATED: "/workflows/get/search-paginated/",
  WORKFLOW_GET_BY_ID: "/workflows/get/",
  WORKFLOW_UPDATE: "/workflows/update/",
  WORKFLOW_DELETE: "/workflows/delete/",
  WORKFLOW_EXECUTE: "/workflows/{workflow_id}/execute",
  WORKFLOW_EXECUTE_SYNC: "/workflows/{workflow_id}/execute/sync",
  WORKFLOW_RESUME: "/workflows/executions/{execution_id}/resume",
  WORKFLOW_EXECUTION_STATUS: "/workflows/executions/{execution_id}/status",
  WORKFLOW_GET_EXECUTIONS: "/workflows/{workflow_id}/executions",
  WORKFLOW_AVAILABLE_AGENTS: "/workflows/available-agents",
  WORKFLOW_GET_BY_NAME: "/workflows/get-by-name",
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

// Card Footer Buttons Configuration
// Maps context type to default footer button configurations
// Buttons are displayed from right to left in the order specified
export const card_config = {
  agent: {
    footerButtons: [{ type: "share", visible: true }, { type: "delete", visible: true }],
  },
  tool: {
    footerButtons: [{ type: "share", visible: true }, { type: "delete", visible: true }],
  },
  server: {
    footerButtons: [
      { type: "share", visible: true },
      { type: "delete", visible: true },
      { type: "view", visible: true },
    ],
  },
  group: {
    footerButtons: [{ type: "delete", visible: true }],
  },
  role: {
    footerButtons: [{ type: "delete", visible: true }],
  },
  department: {
    footerButtons: [{ type: "delete", visible: true }],
  },
  "knowledge base": {
    footerButtons: [{ type: "share", visible: true }, { type: "delete", visible: true }],
  },
  workflow: {
    footerButtons: [{ type: "share", visible: true }, { type: "delete", visible: true }],
  },
  recycleAgents: {
    footerButtons: [], // No buttons for recycled agents
  },
  recycleTools: {
    footerButtons: [], // No buttons for recycled tools
  },
  default: {
    footerButtons: [
      { type: "chat", visible: true },
      { type: "view", visible: true },
      { type: "info", visible: true },
      { type: "delete", visible: true },
    ],
  },
};

// Verifier Settings Configuration
// Maps framework + agent type to visibility of each toggle
// true = Show, false = Hidden
export const chat_screen_config = {
  google_adk: {
    mentionAgentTypes: ["meta_agent", "planner_meta_agent", "planner_executor_agent", "multi_agent", "react_agent", "react_critic_agent"],
    meta_agent: {
      planVerifier: false,
      toolVerifier: true,
      validator: true,
      fileContext: false,
      canvasView: true,
      context: false,
      onlineEvaluator: true,
      showMentionButton: true,
    },
    planner_meta_agent: {
      planVerifier: true,
      toolVerifier: true,
      validator: true,
      fileContext: false,
      canvasView: true,
      context: false,
      onlineEvaluator: true,
      showMentionButton: true,
    },
    planner_executor_agent: {
      planVerifier: true,
      toolVerifier: true,
      validator: true,
      fileContext: false,
      canvasView: true,
      context: false,
      onlineEvaluator: true,
      showMentionButton: true,
    },
    multi_agent: {
      planVerifier: true,
      toolVerifier: true,
      validator: true,
      fileContext: false,
      canvasView: true,
      context: false,
      onlineEvaluator: true,
      showMentionButton: true,
      criticSliders: true,
    },
    react_agent: {
      planVerifier: false,
      toolVerifier: true,
      validator: true,
      fileContext: false,
      canvasView: true,
      context: false,
      onlineEvaluator: true,
      showMentionButton: true,
    },
    react_critic_agent: {
      planVerifier: false,
      toolVerifier: true,
      validator: true,
      fileContext: false,
      canvasView: true,
      context: false,
      onlineEvaluator: true,
      showMentionButton: true,
      criticSliders: true,
    },
  },
  langgraph: {
    mentionAgentTypes: ["meta_agent", "workflow", "planner_meta_agent", "planner_executor_agent", "multi_agent", "react_agent", "react_critic_agent"],
    meta_agent: {
      planVerifier: false,
      toolVerifier: true,
      validator: true,
      fileContext: true,
      canvasView: true,
      context: true,
      onlineEvaluator: true,
      showMentionButton: true,
    },
    planner_meta_agent: {
      planVerifier: true,
      toolVerifier: true,
      validator: true,
      fileContext: true,
      canvasView: true,
      context: true,
      onlineEvaluator: true,
      showMentionButton: true,
    },
    planner_executor_agent: {
      planVerifier: true,
      toolVerifier: true,
      validator: true,
      fileContext: true,
      canvasView: true,
      context: true,
      onlineEvaluator: true,
      showMentionButton: true,
    },
    multi_agent: {
      planVerifier: true,
      toolVerifier: true,
      validator: true,
      fileContext: true,
      canvasView: true,
      context: true,
      onlineEvaluator: true,
      showMentionButton: true,
      criticSliders: true,
    },
    react_agent: {
      planVerifier: false,
      toolVerifier: true,
      validator: true,
      fileContext: true,
      canvasView: true,
      context: true,
      onlineEvaluator: true,
      showMentionButton: true,
    },
    react_critic_agent: {
      planVerifier: false,
      toolVerifier: true,
      validator: true,
      fileContext: true,
      canvasView: true,
      context: true,
      onlineEvaluator: true,
      showMentionButton: true,
      criticSliders: true,
    },
    workflow: {
      planVerifier: false,
      toolVerifier: false,
      validator: false,
      fileContext: false,
      canvasView: false,
      context: true,
      onlineEvaluator: false,
      showMentionButton: false,
    },
  },
  pure_python: {
    mentionAgentTypes: ["hybrid_agent"],
    hybrid_agent: {
      planVerifier: true,
      toolVerifier: true,
      validator: true,
      fileContext: false,
      canvasView: true,
      context: true,
      onlineEvaluator: true,
      showMentionButton: true,
    },
  },
};

export const threshold_epoch_config = {
  critic_score_threshold: 0.7,
  max_critic_epochs: 3,
  evaluation_score_threshold: 0.7,
  max_evaluation_epochs: 3,
  validation_score_threshold: 0.7,
  max_validation_epochs: 3,
  langgraph_recursion_limit: 25,
  chat_summary_interval: 10,
};

/**
 * Inference Config UI Configuration
 * Defines sections and sliders for the InferenceConfig component.
 * Each section contains a title, description, and array of sliders.
 * Adding/removing sliders is as simple as modifying this config.
 */
export const inference_config_ui = {
  sections: [
    {
      id: "critic",
      title: "Critic Settings",
      description: "Configure score threshold and epochs for critic evaluation in multi-agent and react-critic workflows.",
      sliders: [
        {
          key: "critic_score_threshold",
          label: "Score Threshold",
          min: 0,
          max: 1,
          step: 0.05,
          isFloat: true,
        },
        {
          key: "max_critic_epochs",
          label: "Max Epochs",
          min: 1,
          max: 5,
          step: 1,
          isFloat: false,
        },
      ],
    },
    {
      id: "evaluation",
      title: "Evaluation Settings",
      description: "Configure score threshold and epochs for online evaluator responses.",
      sliders: [
        {
          key: "evaluation_score_threshold",
          label: "Score Threshold",
          min: 0,
          max: 1,
          step: 0.05,
          isFloat: true,
        },
        {
          key: "max_evaluation_epochs",
          label: "Max Epochs",
          min: 1,
          max: 5,
          step: 1,
          isFloat: false,
        },
      ],
    },
    {
      id: "validation",
      title: "Validation Settings",
      description: "Configure score threshold and epochs for validator checks.",
      sliders: [
        {
          key: "validation_score_threshold",
          label: "Score Threshold",
          min: 0,
          max: 1,
          step: 0.05,
          isFloat: true,
        },
        {
          key: "max_validation_epochs",
          label: "Max Epochs",
          min: 1,
          max: 5,
          step: 1,
          isFloat: false,
        },
      ],
    },
    {
      id: "execution",
      title: "Execution Limits",
      description: "Configure limits for LangGraph recursion and chat summarization intervals.",
      sliders: [
        {
          key: "langgraph_recursion_limit",
          label: "LangGraph Recursion Limit",
          min: 1,
          max: 100,
          step: 1,
          isFloat: false,
        },
        {
          key: "chat_summary_interval",
          label: "Chat Summary Interval",
          min: 1,
          max: 50,
          step: 1,
          isFloat: false,
        },
      ],
    },
  ],
};
