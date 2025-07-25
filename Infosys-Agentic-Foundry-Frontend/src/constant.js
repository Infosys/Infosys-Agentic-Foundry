import Cookies from "js-cookie";

import pkg from '../package.json';

export const APP_VERSION = pkg.version;

export const BOT = "bot";
export const USER = "user";

export const dropdown1 = [
  { label: "React Agent", value: "react_agent" },
  { label: "Multi Agent", value: "multi_agent" },
  { label: "Meta Agent", value: "meta_agent" },
  { label:"Planner Meta Agent",value:"planner_meta_agent"},
  { label: "React Critic Agent", value: "react_critic_agent"},
  { label:"Planner Executor Agent",value:"planner_executor_agent"},
];
//   { label: "Custom Template", value: "custom_template" }

export const agentTypes = [
  { label: "React Agent", value: "react_agent" },
  { label: "Multi Agent", value: "multi_agent" },
  { label: "Meta Agent", value: "meta_agent" },
  {label:"Planner Meta Agent",value:"planner_meta_agent"},
  {label: "React Critic Agent", value: "react_critic_agent"},
  {label:"Planner Executor Agent",value:"planner_executor_agent"},
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

export const BASE_URL = "add_your_server_host_url";

export const mkDocs_baseURL = "http://10.208.82.47:9000/";

export const liveTrackingUrl = "add_your_live_track_Url";

export const APIs = {
  GET_AGENTS: "/get-agents/",
  // DELETE_AGENT: "/delete-agent/",
  DELETE_AGENT: "/react-agent/delete-agent/",
  ONBOARD_AGENT: "/react-agent/onboard-agent",
  ONBOARD_MULTI_AGENT: "/planner-executor-critic-agent/onboard-agents",
  ONBOARD_META_AGENT: "/meta-agent/onboard-agents",
  GET_TOOLS: "/get-tools/",
  GET_AGENT: "/get-agent/",
  UPDATE_AGENT: "/react-agent/update-agent",
  UPDATE_MULTI_AGENT: "/planner-executor-critic-agent/update-agent",
  UPADATE_META_AGENT: "/meta-agent/update-agent",
  PLANNER: "/planner-executor-critic-agent/get-query-response-hitl-replanner",
  CUSTOME_TEMPLATE_QUERY: "/custom_template/get-query-response-hitl-replanner",
  META_AGENT_QUERY: "/meta-agent/get-query-response",
  REACT_MULTI_AGENT_QUERY: "/get-query-response",
  GET_CHAT_HISTORY: "/get-chat-history",
  META_AGENT_HISTORY: "/meta-agent/get-chat-history",
  GET_TAGS: "/tags/get-available-tags",
  FETCH_OLD_CHATS: "/old-chats",
  NEW_CHAT: "/new_chat/",
  GET_ALLUPLOADFILELIST: "/files/user-uploads/get-file-structure/",
  GET_MODELS: "/get-models",
  FILE_UPLOAD:'/files/user-uploads/delete-file/?file_path=',
  GET_TOOLS_BY_SEARCH:"/get-tools-by-search",
  GET_AGENTS_BY_SEARCH:"/get-agents-by-search",
  GET_AGENTS_BY_DETAILS:"/get-agents-details-for-chat",
  PLANNER_META_AGENT_QUERY:"/planner-meta-agent/get-query-response",
  ONBOARD_PLANNER_META_AGENT:"/planner-meta-agent/onboard-agents",
  UPDATE_PLANNER_META_AGENT:"/planner-meta-agent/update-agent",
  UPDATE_PLANNER_SYSTEM_PROMT:"/planner-meta-agent/update-system-prompt",
  ONBOARD_PLANNER_EXECUTOR_AGENT:"/planner-executor-agent/onboard-agents",
  ONBOARD_REACT_CRITIC_AGENT:"/react-critic-agent/onboard-agent",
  UPDATE_REACT_CRITIC_AGENT:"/react-critic-agent/update-agent",
  UPDATE_PLANNER_EXECUTOR_AGENT:"/planner-executor-agent/update-agent",
  PLANNER_EXECUTOR_AGENT_QUERY:"/planner-executor-agent/get-query-response-hitl-replanner",
  UPDATE_PASWORD_ROLE:"/update-password-role",
  RECYCLE_BIN:"/recycle-bin",
  RESTORE_TOOL:"/restore/",
  DELETE_TOOL:"/delete/",
  KNOWLEDGE_BASE_FILE_UPLOAD:"/kbdocuments",
  KB_LIST:"/kb_list",
  GET_ACTIVE_CONNECTIONS:"/get-active-connection-names",
  CONNECT_DATABASE:"/connect",
  GENERATE_QUERY:"/generate_query",
  RUN_QUERY:"/run_query",
  DISCONNECT_DATABASE:"/disconnect",
  CRUD_CONNECTIONS:"/crud-connections",
  AVAILABLE_CONNECTIONS:"/connections",
  SQL_CONNECTIONS:"/connections_sql",
  MONGODB_CONNECTIONS:"/connections_mongodb",
  MONGODB_OPERATION: "/mongodb-operation/",
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
  HEALTH_SECRETS:'/secrets/health'
};

// export const sessionId = "test_101";
const session_id = Cookies.get("session_id");
export const sessionId = session_id;

export const userEmail = "test";

export const feedBackMessage =
  "I apologize for the previous response. Could you please provide more details on what went wrong? Your feedback will help us improve.";

export const likeMessage =
  "Thanks for the like! We're glad you found the response helpful. If you have any more questions or need further assistance, feel free to ask!";
export const SystemPromptsTypesPlanner=[
  { label:"SYSTEM_PROMPT_META_AGENT_PLANNER", value:"SYSTEM_PROMPT_META_AGENT_PLANNER"},
  { label:"SYSTEM_PROMPT_META_AGENT_RESPONDER", value:"SYSTEM_PROMPT_META_AGENT_RESPONDER"},
  { label:"SYSTEM_PROMPT_META_AGENT_SUPERVISOR",value:"SYSTEM_PROMPT_META_AGENT_SUPERVISOR"}
]
export const SystemPromptsTypes = [
  { label: "SYSTEM PROMPT CRITIC AGENT", value: "SYSTEM_PROMPT_CRITIC_AGENT" },
  {
    label: "SYSTEM PROMPT CRITIC BASED PLANNER AGENT",
    value: "SYSTEM_PROMPT_CRITIC_BASED_PLANNER_AGENT",
  },
  {
    label: "SYSTEM PROMPT EXECUTOR AGENT",
    value: "SYSTEM_PROMPT_EXECUTOR_AGENT",
  },
  {
    label: "SYSTEM PROMPT PLANNER AGENT",
    value: "SYSTEM_PROMPT_PLANNER_AGENT",
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

export const branchInteruptKey =
  "branch:interrupt_node:interrupt_node_decision:feedback_collector";
export const branchInteruptValue = "interrupt_node";

export const customTemplatId = "custom_template_1";

export const roleOptions = ["Admin", "Developer", "User"];

export const systemPromptReactCriticAgents = 
[
  {label:"SYSTEM PROMPT EXECUTOR AGENT",value:"SYSTEM_PROMPT_EXECUTOR_AGENT"},
  {label:"SYSTEM PROMPT CTRITIC AGENT",value:"SYSTEM_PROMPT_CRITIC_AGENT"}
];

export const systemPromptPlannerExecutorAgents =
[
  {label:"SYSTEM PROMPT GENERAL LLM",value:"SYSTEM_PROMPT_GENERAL_LLM"},
  {label:"SYSTEM PROMPT RESPONSE GENERATOR AGENT",value:"SYSTEM_PROMPT_RESPONSE_GENERATOR_AGENT"},
  {label:"SYSTEM PROMPT REPLANNER AGENT",value:"SYSTEM_PROMPT_REPLANNER_AGENT"},
  {label:"SYSTEM PROMPT EXECUTOR AGENT",value:"SYSTEM_PROMPT_EXECUTOR_AGENT"},
  {label:"SYSTEM PROMPT PLANNER AGENT",value:"SYSTEM_PROMPT_PLANNER_AGENT"}
];



