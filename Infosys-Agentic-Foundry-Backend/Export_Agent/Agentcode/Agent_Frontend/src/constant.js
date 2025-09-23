import Cookies from "js-cookie";

import pkg from '../package.json';

export const APP_VERSION = pkg.version;

export const BOT = "bot";
export const USER = "user";

//   { label: "Custom Template", value: "custom_template" }

export const agentTypesDropdown = [
  { label: "Meta", value: "meta_agent" },
  { label: "Meta Planner ",value:"planner_meta_agent"},
  { label: "Planner Executor",value:"planner_executor_agent"},
  { label: "Planner Executor Critic", value: "multi_agent" },
  { label: "React", value: "react_agent" },
  { label: "React Critic", value: "react_critic_agent"}
];

export const REACT_AGENT = "react_agent";
export const MULTI_AGENT = "multi_agent";
export const META_AGENT = "meta_agent";
export const PLANNER_META_AGENT="planner_meta_agent";
export const CUSTOM_TEMPLATE = "custom_template";
export const REACT_CRITIC_AGENT = "react_critic_agent";
export const PLANNER_EXECUTOR_AGENT = "planner_executor_agent";

export const like = "like";
export const regenerate = "regenerate";
export const dislike = "feedback";

export const CHAT_BOT_DATA = "CHAT_BOT_DATA";

export const BASE_URL = process.env.REACT_APP_BASE_URL;

export const mkDocs_baseURL = process.env.REACT_APP_MKDOCS_BASE_URL;

export const liveTrackingUrl = process.env.REACT_APP_LIVE_TRACKING_URL;

export const APIs = {
  //Feedback Learning APIs
  GET_APPROVALS_LIST:'/feedback-learning/get/approvals-list',
  GET_APPROVALS_BY_ID:'/feedback-learning/get/approvals-by-agent/',
  UPDATE_APPROVAL_RESPONSE:'/feedback-learning/update/approval-response',
  GET_RESPONSES_DATA:'/feedback-learning/get/responses-data/',

  GET_VERSION:"/utility/get/version",
  DELETE_AGENT: "/react-agent/delete-agent/",
  ONBOARD_AGENT: "/onboard-agent",
  GET_AGENT: "/get-agent/",
  UPDATE_AGENT: "/update-agent",
  PLANNER: "/planner-executor-critic-agent/get-query-response-hitl-replanner",
  CUSTOME_TEMPLATE_QUERY: "/custom_template/get-query-response-hitl-replanner",
  META_AGENT_QUERY: "/meta-agent/get-query-response",
  REACT_MULTI_AGENT_QUERY: "/get-query-response",
  GET_CHAT_HISTORY: "/get-chat-history",
  CLEAR_CHAT_HISTORY: "/clear-chat-history",
  META_AGENT_HISTORY: "/meta-agent/get-chat-history",
  GET_TAGS: "/tags/get",
  FETCH_OLD_CHATS: "/old-chats",
  NEW_CHAT: "/new_chat/",
  GET_ALLUPLOADFILELIST: "/files/user-uploads/get-file-structure/",
  GET_MODELS: "/utility/get/models",
  FILE_UPLOAD:'/files/user-uploads/delete-file/?file_path=',
  GET_AGENTS_BY_DETAILS:"/agents/get/details-for-chat-interface",
  PLANNER_META_AGENT_QUERY:"/planner-meta-agent/get-query-response",
  PLANNER_EXECUTOR_AGENT_QUERY:"/planner-executor-agent/get-query-response-hitl-replanner",
  UPDATE_PASWORD_ROLE:"/update-password-role",
  RECYCLE_BIN:"/recycle-bin",
  RESTORE_TOOL:"/restore/",
  DELETE_TOOL:"/delete/",
  KNOWLEDGE_BASE_FILE_UPLOAD:"/kbdocuments",
  KB_LIST:"/kb_list",
  GET_ACTIVE_CONNECTIONS:"/data-connector/get/active-connection-names",
  CONNECT_DATABASE:"/data-connector/connect",
  GENERATE_QUERY:"/data-connector/generate-query",
  RUN_QUERY:"/data-connector/run-query",
  DISCONNECT_DATABASE:"/data-connector/disconnect",
  AVAILABLE_CONNECTIONS:"/data-connector/connections",
  SQL_CONNECTIONS:"/data-connector/connections/sql",
  MONGODB_CONNECTIONS:"/data-connector/connections/mongodb",
  MONGODB_OPERATION: "/data-connector/mongodb-operation/",
  ADD_SECRET:"/secrets/create",
  DELETE_SECRET:"/secrets/delete",
  UPDATE_SECRET:"/secrets/update",
  PUBLIC_ADD_SECRET:"/secrets/public/create",
  PUBLIC_UPDATE_SECRET:"/secrets/public/update",
  PUBLIC_DELETE_SECRET:"/secrets/public/delete",
  GET_SECRETS:"/secrets/list",
  GET_PUBLIC_SECRETS:"/secrets/public/list",
  SECRETS_GET:'/secrets/get',
  PUBLIC_SECRETS_GET:'/secrets/public/get',
  HEALTH_SECRETS:'/secrets/health',
  SUGGESTIONS:'/chat/auto-suggest-agent-queries'
};

// export const sessionId = "test_101";
const session_id = Cookies.get("session_id");
export const sessionId = session_id;

export const userEmail = "test";

export const feedBackMessage =
  "I apologize for the previous response. Could you please provide more details on what went wrong? Your feedback will help us improve.";

export const likeMessage =
  "Thanks for the like! We're glad you found the response helpful. If you have any more questions or need further assistance, feel free to ask!";
export const SystemPromptsPlannerMetaAgent=[
  {label:"SYSTEM_PROMPT_META_AGENT_PLANNER", value:"SYSTEM_PROMPT_META_AGENT_PLANNER"},
  {label:"SYSTEM_PROMPT_META_AGENT_RESPONDER", value:"SYSTEM_PROMPT_META_AGENT_RESPONDER"},
  {label:"SYSTEM_PROMPT_META_AGENT_SUPERVISOR",value:"SYSTEM_PROMPT_META_AGENT_SUPERVISOR"}
]
export const SystemPromptsMultiAgent = [
  {label : "SYSTEM PROMPT GENERAL LLM", value: "SYSTEM_PROMPT_GENERAL_LLM"},
  { label: "SYSTEM PROMPT CRITIC AGENT", value: "SYSTEM_PROMPT_CRITIC_AGENT" },
  {label: "SYSTEM PROMPT PLANNER AGENT",value: "SYSTEM_PROMPT_PLANNER_AGENT"},
  {label: "SYSTEM PROMPT EXECUTOR AGENT",value: "SYSTEM_PROMPT_EXECUTOR_AGENT"},
  {label: "SYSTEM PROMPT REPLANNER AGENT",value: "SYSTEM_PROMPT_REPLANNER_AGENT"},
  {label: "SYSTEM PROMPT RESPONSE GENERATOR AGENT",value: "SYSTEM_PROMPT_RESPONSE_GENERATOR_AGENT"},
  {label: "SYSTEM PROMPT CRITIC BASED PLANNER AGENT",value: "SYSTEM_PROMPT_CRITIC_BASED_PLANNER_AGENT"}
];

export const branchInteruptKey =
  "branch:interrupt_node:interrupt_node_decision:feedback_collector";
export const branchInteruptValue = "interrupt_node";

export const customTemplatId = "custom_template_1";

export const roleOptions = ["Admin", "Developer", "User"];

export const systemPromptReactCriticAgents = 
[
  {label:"SYSTEM PROMPT CTRITIC AGENT",value:"SYSTEM_PROMPT_CRITIC_AGENT"},
  {label:"SYSTEM PROMPT EXECUTOR AGENT",value:"SYSTEM_PROMPT_EXECUTOR_AGENT"},
];

export const systemPromptPlannerExecutorAgents =
[
  {label:"SYSTEM PROMPT GENERAL LLM",value:"SYSTEM_PROMPT_GENERAL_LLM"},
  {label:"SYSTEM PROMPT PLANNER AGENT",value:"SYSTEM_PROMPT_PLANNER_AGENT"},
  {label:"SYSTEM PROMPT EXECUTOR AGENT",value:"SYSTEM_PROMPT_EXECUTOR_AGENT"},
  {label:"SYSTEM PROMPT REPLANNER AGENT",value:"SYSTEM_PROMPT_REPLANNER_AGENT"},
  {label:"SYSTEM PROMPT RESPONSE GENERATOR AGENT",value:"SYSTEM_PROMPT_RESPONSE_GENERATOR_AGENT"},
];



