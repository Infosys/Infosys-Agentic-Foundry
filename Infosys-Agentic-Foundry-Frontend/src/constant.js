import Cookies from "js-cookie";

import pkg from "../package.json";

export const APP_VERSION = pkg.version;

export const BOT = "bot";
export const USER = "user";

//   { label: "Custom Template", value: "custom_template" }

export const agentTypesDropdown = [
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

export const like = "like";
export const regenerate = "regenerate";
export const dislike = "submit_feedback";

export const CHAT_BOT_DATA = "CHAT_BOT_DATA";

export const BASE_URL = process.env.REACT_APP_BASE_URL;

export const mkDocs_baseURL = process.env.REACT_APP_MKDOCS_BASE_URL;

export const liveTrackingUrl = process.env.REACT_APP_LIVE_TRACKING_URL;

export const APIs = {
  //Feedback Learning APIs
  GET_APPROVALS_LIST: "/feedback-learning/get/approvals-list",
  GET_APPROVALS_BY_ID: "/feedback-learning/get/approvals-by-agent/",
  UPDATE_APPROVAL_RESPONSE: "/feedback-learning/update/approval-response",
  GET_RESPONSES_DATA: "/feedback-learning/get/responses-data/",

  //Default APIs
  // LOGIN: "/login",
  // LOGOUT:"/logout",
  // REGISTER: "/registration",
  // UPDATE_PASSWORD_ROLE: "/update-password-role",
  // GUEST_LOGIN: "/login_guest",

  LOGIN: "/auth/login",
  LOGOUT: "/auth/logout",
  REGISTER: "/auth/register",
  UPDATE_PASSWORD_ROLE: "/auth/update-password",
  GUEST_LOGIN: "/auth/guest-login",

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
  ADD_TOOLS: "/tools/add",
  GET_TOOLS_BY_LIST: "/tools/get/by-list",
  UPDATE_TOOLS: "/tools/update/",
  DELETE_TOOLS: "/tools/delete/",
  TOOLS_BY_TAGS: "/tools/get/by-tags",
  TOOLS_RECYCLE_BIN: "/tools/recycle-bin/get",
  RESTORE_TOOLS: "/tools/recycle-bin/restore/",
  DELETE_TOOLS_PERMANENTLY: "/tools/recycle-bin/permanent-delete/",
  EXECUTE_CODE: "/tools/execute",

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

  // MCP APIs
  MCP_ADD_TOOLS: "/tools/mcp/add",
  MCP_DELETE_TOOLS: "/tools/mcp/delete/",
  MCP_GET_ALL_SERVERS: "/tools/mcp/get/search-paginated/",
  MCP_UPDATE_SERVER: "/tools/mcp/update/",
  MCP_LIVE_TOOL_DETAIL: "/tools/mcp/get/live-tool-details/",

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
