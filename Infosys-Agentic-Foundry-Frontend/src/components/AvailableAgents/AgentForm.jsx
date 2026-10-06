import { useEffect, useState, useRef, useCallback, useMemo } from "react";
import styles from "./CreateAgent.module.css";
import SVGIcons from "../../Icons/SVGIcons";
import {
  APIs,
  META_AGENT,
  MULTI_AGENT,
  REACT_AGENT,
  PLANNER_META_AGENT,
  SystemPromptsMultiAgent,
  SystemPromptsPlannerMetaAgent,
  REACT_CRITIC_AGENT,
  PLANNER_EXECUTOR_AGENT,
  HYBRID_AGENT,
  SKILL_AGENT,
  systemPromptReactCriticAgents,
  systemPromptPlannerExecutorAgents,
  agentTypesDropdown,
} from "../../constant";
import useFetch from "../../Hooks/useAxios";
import Loader from "../commonComponents/Loader";
import { useMessage } from "../../Hooks/MessageContext";
import { getRoleFromToken, getEmailFromToken, getUserNameFromToken } from "../../utils/jwtUtils";
import DeleteModal from "../commonComponents/DeleteModal";
import { sanitizeFormField, isValidEvent } from "../../utils/sanitization";
import { getUnconfiguredCostModels } from "../../utils/modelUtils";
import UnconfiguredModelCostWarning from "../commonComponents/UnconfiguredModelCostWarning";
import { useAuth } from "../../context/AuthContext";
import { useErrorHandler } from "../../Hooks/useErrorHandler";
import { isAsyncModeEnabled, submitAndPollAsync } from "../../utils/asyncTaskPoller";
import ValidatorPatternsGroup from "../validators/ValidatorPatternsGroup";
import TagSelector from "../commonComponents/TagSelector/TagSelector";
import NewCommonDropdown from "../commonComponents/NewCommonDropdown";
import ResourceSlider from "../commonComponents/ResourceSlider/ResourceSlider";
import ResourceAccordion from "../commonComponents/ResourceAccordion/ResourceAccordion";
import ToolDetailModal from "../ToolDetailModal/ToolDetailModal";
import IAFButton from "../../iafComponents/GlobalComponents/Buttons/Button";
import TextareaWithActions from "../commonComponents/TextareaWithActions";
import Toggle from "../commonComponents/Toggle";
import { FullModal } from "../../iafComponents/GlobalComponents/FullModal";
import { useKnowledgeBaseService } from "../../services/knowledgeBaseService";
import { usePermissions } from "../../context/PermissionsContext";
import { useToolsAgentsService } from "../../services/toolService";
import ConfirmationModal from "../commonComponents/ToastMessages/ConfirmationPopup";
import { useDatabases } from "../DataConnectors/service/databaseService";
import { useHookRepositoryService } from "../../services/hookRepositoryService";
import InfoTag from "../commonComponents/InfoTag";

/**
 * AgentForm - Unified component for Create and Update Agent operations
 *
 * @param {Object} props
 * @param {"create" | "update"} props.mode - Form mode: "create" or "update"
 * @param {Object} props.agentData - Agent data for update mode (optional for create)
 * @param {Function} props.onClose - Callback to close the modal
 * @param {Function} props.fetchAgents - Callback to refresh agents list
 * @param {Array} props.tags - Available tags
 * @param {boolean} props.recycleBin - Whether viewing from recycle bin (update mode only)
 * @param {Function} props.onRestore - Restore callback (recycle bin only)
 * @param {Function} props.onDelete - Delete callback (recycle bin only)
 */

/** Format bytes to human-readable size */
const formatBytes = (bytes) => {
  if (!bytes || bytes === 0) return "0 B";
  const k = 1024;
  const sizes = ["B", "KB", "MB", "GB"];
  const i = Math.floor(Math.log(bytes) / Math.log(k));
  return parseFloat((bytes / Math.pow(k, i)).toFixed(1)) + " " + sizes[i];
};

const AgentForm = ({ mode = "create", agentData = null, onClose, fetchAgents, tags = [], recycleBin = false, onRestore, onDelete, readOnly: readOnlyProp = false }) => {
  // ============ State for Dynamic Mode Management ============
  const [currentMode, setCurrentMode] = useState(mode);
  const [currentAgentData, setCurrentAgentData] = useState(agentData);

  // Combine recycleBin and readOnly props into a single flag for disabling form fields
  const isReadOnly = recycleBin || Boolean(readOnlyProp);

  // ============ Constants ============
  const isCreateMode = currentMode === "create";
  const isUpdateMode = currentMode === "update";

  // ============ Cookies ============
  const loggedInUserEmail = getEmailFromToken();
  const userName = getUserNameFromToken();
  const role = getRoleFromToken();

  // ============ Hooks ============
  const { fetchData, postData, putData, deleteData } = useFetch();
  const { addMessage, setShowPopup } = useMessage();
  const { handleApiError, handleError } = useErrorHandler();
  const { logout } = useAuth();
  const { getKnowledgeBasesForAgent } = useKnowledgeBaseService();
  const { hasPermission } = usePermissions();
  const { deleteAgent: deleteAgentService } = useToolsAgentsService();
  const { listHooks: listRepoHooks } = useHookRepositoryService();
  const canDeleteAgents = typeof hasPermission === "function" ? hasPermission("delete_access.agents") : false;

  // ============ Delete Agent from Modal ============
  const handleDeleteAgentFromModal = async () => {
    const agentId = currentAgentData?.agentic_application_id || agentData?.agentic_application_id;
    if (!agentId) return;

    const isAdmin = role && role?.toLowerCase() === "admin";
    const emailId = userName === "Guest" ? (currentAgentData?.created_by || agentData?.created_by) : loggedInUserEmail;

    const payload = {
      user_email_id: emailId,
      is_admin: isAdmin,
    };

    try {
      setLoading(true);
      const response = await deleteAgentService(payload, [agentId]);

      if (response && typeof response !== "string") {
        const statusMsg = response.status_message || response.message;
        if (statusMsg) {
          const hasAnyFailure = Array.isArray(response.results) && response.results.some((r) => r.is_delete === false);
          addMessage(statusMsg, hasAnyFailure ? "error" : "success");
        }
      }

      setShowDeleteConfirm(false);
      setLoading(false);
      onClose();
      if (fetchAgents) await fetchAgents();
    } catch (e) {
      console.error("Delete agent error:", e);
      addMessage("Failed to delete agent", "error");
      setLoading(false);
      setShowDeleteConfirm(false);
    }
  };

  // ============ Resource Permissions ============
  // Check if user can access any resource type (tools, servers, knowledge bases, agents)
  const canViewTools = hasPermission("read_access.tools", true);
  const canViewServers = hasPermission("read_access.mcp_servers", true);
  const canViewAgents = hasPermission("read_access.agents", true);
  const canViewKnowledgeBases = hasPermission("knowledgebase_access", true);

  // ============ Refs ============
  const hasLoadedModelsOnce = useRef(false);
  const hasLoadedAgentData = useRef(false);

  // ============ Initial Form Data ============
  const createInitialFormData = {
    agent_name: "",
    email_id: loggedInUserEmail,
    agent_goal: "",
    workflow_description: "",
    model_name: "",
    agent_type: "react_agent",
    system_prompt: "",
    welcome_message: "",
    category: "Finance",
  };

  const updateInitialFormData = {
    agentic_application_name: agentData?.agentic_application_name || "",
    created_by: "",
    agentic_application_description: agentData?.agentic_application_description || "",
    agentic_application_workflow_description: agentData?.agentic_application_workflow_description || "",
    model_name: agentData?.model_name || "",
    system_prompt: agentData?.system_prompt || "",
  };

  // ============ Form State ============
  const [formData, setFormData] = useState(currentMode === "create" ? createInitialFormData : updateInitialFormData);
  const [fullAgentData, setFullAgentData] = useState({});
  const [models, setModels] = useState([]);
  const [modelsLoading, setModelsLoading] = useState(false);
  const [unconfiguredCostModels, setUnconfiguredCostModels] = useState([]);
  const [loading, setLoading] = useState(false);
  const [selectedToolsLoading, setSelectedToolsLoading] = useState(isUpdateMode);

  // ============ Guardrails State ============
  const [guardrailTypes, setGuardrailTypes] = useState([]);
  const [guardrailsLoading, setGuardrailsLoading] = useState(false);
  const [selectedGuardrail, setSelectedGuardrail] = useState("");

  // ============ Tags State ============
  const [selectedTagsForSelector, setSelectedTagsForSelector] = useState([]);
  const [selectedTagIds, setSelectedTagIds] = useState([]);

  // ============ Resources State ============
  const [showResourcesSlider, setShowResourcesSlider] = useState(false);
  const [selectedResources, setSelectedResources] = useState([]);
  const [initialSelectedResources, setInitialSelectedResources] = useState([]);

  // ============ Agent Type & System Prompt State (Update Mode) ============
  const [agentType, setAgentType] = useState("");
  const [systemPromptData, setSystemPromptData] = useState({});
  const [selectedPromptData, setSelectedPromptData] = useState("");
  const [systemPromptType, setSystemPromptType] = useState(SystemPromptsMultiAgent[0].value);
  const [plannersystempromtType, setPlannersystempromptType] = useState(SystemPromptsPlannerMetaAgent[0].value);
  const [reactCriticSystemPromptType, setReactCriticSystemPromptType] = useState(systemPromptReactCriticAgents[0].value);
  const [plannerExecutorSystemPromptType, setPlannerExecutorSystemPromptType] = useState(systemPromptPlannerExecutorAgents[0].value);

  // ============ Computed Resource Permission ============
  // For meta agents: need agents permission; for others: need tools/servers/kb permission
  const effectiveAgentType = isCreateMode ? formData.agent_type : agentType;
  const isMetaAgentType = effectiveAgentType === META_AGENT || effectiveAgentType === PLANNER_META_AGENT;
  const hasAnyResourcePermission = isMetaAgentType ? canViewAgents : (canViewTools || canViewKnowledgeBases);

  // ============ Validation Patterns (Update Mode) ============
  const [validationPatterns, setValidationPatterns] = useState([]);

  // ============ Tool/Agent/KB ID Tracking (Update Mode) ============
  const [addedToolsId, setAddedToolsId] = useState([]);
  const [removedToolsId, setRemovedToolsId] = useState([]);
  const [addedAgentsId, setAddedAgentsId] = useState([]);
  const [removedAgentsId, setRemovedAgentsId] = useState([]);
  const [addedKnowledgeBaseIds, setAddedKnowledgeBaseIds] = useState([]);
  const [removedKnowledgeBaseIds, setRemovedKnowledgeBaseIds] = useState([]);

  // ============ Tool Versions State ============
  // Maps tool_id -> selected version string, e.g. { "tool_abc": "v2" }
  const [toolVersions, setToolVersions] = useState({});

  // ============ Database Connections State ============
  const [availableDbConnections, setAvailableDbConnections] = useState([]);
  const [selectedDbConnections, setSelectedDbConnections] = useState([]);
  const [initialDbConnections, setInitialDbConnections] = useState([]);
  const [loadingDbConnections, setLoadingDbConnections] = useState(false);
  const { fetchConnections: fetchDbConnections } = useDatabases();
  const canViewDataConnectors = hasPermission("data_connector_access", true);

  // ============ UI State ============
  const [showGuestModal, setShowGuestModal] = useState(false);
  const [showDeleteConfirm, setShowDeleteConfirm] = useState(false);
  const [previewResource, setPreviewResource] = useState(null);
  const [previewModalOpen, setPreviewModalOpen] = useState(false);

  // ============ Collapsible Section State ============
  // Default sections based on mode
  const [expandedSections, setExpandedSections] = useState({
    identity: true,      // Always open by default
    resources: false,    // Will be set based on data in useEffect for update mode
    purpose: true,       // For create mode: Purpose & Workflow (default open)
    agentDetails: false, // For update mode: Agent Goal, Workflow, Welcome Message (default closed)
    prompts: true,       // For update mode: System Prompt, File Context Prompt (default open)
    validators: false,
    config: false,
    skills: true,        // For skill agent: Skills section (default open)
    enterpriseContext: false, // For skill agent: Enterprise context (default closed)
    hooks: false,            // For skill agent: Lifecycle hooks (default closed)
    additionalPaths: false,  // Additional folder paths (default closed)
    absolutePaths: false,     // Absolute path mounts - admin only (default closed)
  });

  // Toggle section expand/collapse
  const toggleSection = (sectionKey) => {
    setExpandedSections(prev => ({
      ...prev,
      [sectionKey]: !prev[sectionKey]
    }));
  };

  // Update resources section based on selectedResources in update mode
  useEffect(() => {
    if (isUpdateMode) {
      setExpandedSections(prev => ({
        ...prev,
        resources: selectedResources.length > 0 || selectedDbConnections.length > 0
      }));
    }
  }, [isUpdateMode, selectedResources.length, selectedDbConnections.length]);

  // Fetch hook repository entries for the hook picker dropdown
  useEffect(() => {
    (async () => {
      try {
        const data = await listRepoHooks();
        setRepoHooks(data || []);
      } catch {
        // non-blocking — manual command entry still available
      }
    })();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // ============ Combined Resources (tools + servers + KB + DB connections) ============
  const combinedResources = useMemo(() => {
    const dbResources = selectedDbConnections.map((connName) => {
      const connInfo = availableDbConnections.find((c) => (c.connection_name || c.name) === connName);
      return {
        db_connection_name: connName,
        name: connName,
        type: "databases",
        db_type: connInfo?.connection_database_type || connInfo?.type || "",
      };
    });
    return [...selectedResources, ...dbResources];
  }, [selectedResources, selectedDbConnections, availableDbConnections]);

  // ============ Welcome Message State ============
  const [welcomeMessage, setWelcomeMessage] = useState("");

  // ============ File Context Management Prompt State (Update Mode) ============
  const [fileContextManagementPrompt, setFileContextManagementPrompt] = useState("");
  const [fileContextPromptExists, setFileContextPromptExists] = useState(false);

  // ============ Regenerate Toggles (Update Mode Only) ============
  const [regenerateWelcomeMessage, setRegenerateWelcomeMessage] = useState(false);
  const [regenerateSystemPrompt, setRegenerateSystemPrompt] = useState(false);
  const [regenerateFileContextPrompt, setRegenerateFileContextPrompt] = useState(false);

  // ============ Skill Agent State ============
  const isSkillAgentType = (isCreateMode ? formData.agent_type : agentType) === SKILL_AGENT;
  const isAgentOSType = isSkillAgentType;

  // Skills array for skill agent — structured mode (recommended by backend)
  const [skills, setSkills] = useState([
    {
      skill_name: "",
      description: "",
      keywords: [],          // Array of trigger strings
      details: "",           // Markdown body
      execution_mode: "react",
      category: "general",
      instructions_md_content: "",
      examples_md_content: "",
      additional_files: [],  // Array of { filename: "", content: "" }
      databases: [],         // Array of { connection_name: "", sql_mode: "read_only" }
      hooks: {},             // Skill-level hooks → SKILL.md frontmatter
    },
  ]);

  // Skill-level expanded sections toggle (hooks per skill)
  const [skillConfigExpanded, setSkillConfigExpanded] = useState({ hooks: false });
  const toggleSkillConfig = (key) => setSkillConfigExpanded((prev) => ({ ...prev, [key]: !prev[key] }));

  // Default skill selection
  const [defaultSkill, setDefaultSkill] = useState("general");

  // Enterprise context for skill agent (all 4 sub-fields from the doc)
  const [enterpriseContext, setEnterpriseContext] = useState("");
  const [skillContexts, setSkillContexts] = useState([]); // Array of { skill_name, content, path, size_bytes }
  const [policies, setPolicies] = useState([]);             // Array of { name, content, size_bytes }
  const [entityGuide, setEntityGuide] = useState("");
  const [enterpriseContextEnabled, setEnterpriseContextEnabled] = useState(false);
  // File metadata from GET /context → available.master_context
  const [masterContextMeta, setMasterContextMeta] = useState(null); // { size_bytes }
  const [entityGuideMeta, setEntityGuideMeta] = useState(null);     // { name, size_bytes }
  // Active sub-tab inside Enterprise Context section: context | entity_guide | skill_contexts | policies | settings
  const [activeContextTab, setActiveContextTab] = useState("context");

  // Active skill index for editing
  const [activeSkillIndex, setActiveSkillIndex] = useState(0);

  // ============ Skill Agent Update Mode Tracking ============
  // Original skill names from server — used to compute add/remove/update diffs
  const [originalSkillNames, setOriginalSkillNames] = useState([]);
  // Track which skills have been modified (by skill_name)
  const [modifiedSkillNames, setModifiedSkillNames] = useState(new Set());
  // Track which skills were removed (by skill_name) during the update session
  const [removedSkillNames, setRemovedSkillNames] = useState([]);
  // Loading state for skill data in update mode
  const [skillsLoading, setSkillsLoading] = useState(false);
  // Track which additional file cards are expanded (by "skillIndex-fileIndex" key)
  const [expandedFileCards, setExpandedFileCards] = useState(new Set());

  // ============ Additional Folder Paths State (Section 1 — relative, all users) ============
  const [additionalPaths, setAdditionalPaths] = useState([]);
  const [initialAdditionalPaths, setInitialAdditionalPaths] = useState([]);

  // ============ Absolute Path Mounts State (Section 2 — admin only) ============
  const [absolutePaths, setAbsolutePaths] = useState([]);
  const [initialAbsolutePaths, setInitialAbsolutePaths] = useState([]);

  // ============ Hooks State (Skill Agent) ============
  // Only user-configurable events shown in UI; system events (OnAgentStart/End/Error, PostSampling) are auto-managed
  const HOOK_EVENTS = ["PreToolUse", "PostToolUse", "PreResponse"];
  const TOOL_EVENTS = ["PreToolUse", "PostToolUse"]; // events that support matcher

  // Matcher dropdown options
  const MATCHER_TOOL_OPTIONS = ["All", "run_shell_command", "database_query_tool", "execute_python_code"];

  /** Convert matcher regex string → dropdown selection array */
  const parseMatcherToSelection = (matcher) => {
    if (!matcher || matcher === ".*" || matcher === "*") return ["All"];
    return matcher.split("|").map((t) => t.trim()).filter(Boolean);
  };

  /** Convert dropdown selection array → matcher regex string */
  const buildMatcherFromSelection = (items) => {
    if (!items || items.length === 0 || items.includes("All")) return ".*";
    return items.join("|");
  };

  /** Handle matcher dropdown selection changes with All/specific toggle logic */
  const handleMatcherSelectionChange = (items, currentMatcher, updateFn) => {
    const prev = parseMatcherToSelection(currentMatcher);
    const prevHadAll = prev.includes("All");
    let newItems;
    if (!prevHadAll && items.includes("All")) {
      newItems = ["All"];
    } else if (items.includes("All") && items.length > 1) {
      newItems = items.filter((t) => t !== "All");
    } else if (items.length === 0) {
      newItems = ["All"];
    } else {
      newItems = items;
    }
    updateFn(buildMatcherFromSelection(newItems));
  };

  // Available hooks from repository (for hook picker dropdown)
  const [repoHooks, setRepoHooks] = useState([]);

  // Hooks state — { PreToolUse: [...], PostToolUse: [...], ... }
  const [hooks, setHooks] = useState({});
  const [initialHooks, setInitialHooks] = useState({});

  // Track whether hooks changed for update mode
  const hooksChanged = () => JSON.stringify(hooks) !== JSON.stringify(initialHooks);

  // ---- Hook helpers ----
  const addHookEntry = (eventType) => {
    setHooks((prev) => ({
      ...prev,
      [eventType]: [
        ...(prev[eventType] || []),
        { hook_id: "", command: "", matcher: "", block_on_nonzero: false, timeout_seconds: 10, skills: [] },
      ],
    }));
  };

  /**
   * When user selects a hook from the repository dropdown, auto-fill fields.
   */
  const selectRepoHook = (eventType, index, hookId) => {
    setHooks((prev) => {
      const updated = [...(prev[eventType] || [])];
      updated[index] = {
        ...updated[index],
        hook_id: hookId,
        command: "", // clear command when using hook_id
        _isManual: false,
      };
      return { ...prev, [eventType]: updated };
    });
  };

  const updateHookEntry = (eventType, index, field, value) => {
    setHooks((prev) => {
      const updated = [...(prev[eventType] || [])];
      updated[index] = { ...updated[index], [field]: value };
      return { ...prev, [eventType]: updated };
    });
  };

  const removeHookEntry = (eventType, index) => {
    setHooks((prev) => {
      const updated = [...(prev[eventType] || [])];
      updated.splice(index, 1);
      const newHooks = { ...prev, [eventType]: updated };
      if (updated.length === 0) delete newHooks[eventType];
      return newHooks;
    });
  };

  // Build clean hooks payload (strip empty entries)
  const buildHooksPayload = () => buildCleanHooks(hooks);

  // Generic: build clean hooks from any hooks object.
  // Converts UI state { EventName: [entries] } → API format { external: [{event, ...}] }.
  const buildCleanHooks = (hooksObj) => {
    const external = [];
    Object.entries(hooksObj || {}).forEach(([event, entries]) => {
      const valid = (entries || []).filter((e) => e.hook_id?.trim() || e.command?.trim());
      valid.forEach((e) => {
        const entry = {
          event,
          matcher: e.matcher || "",
          block_on_nonzero: !!e.block_on_nonzero,
          timeout_seconds: e.timeout_seconds || e.timeout || 10,
        };
        if (e.hook_id?.trim()) {
          entry.hook_id = e.hook_id.trim();
        } else {
          entry.command = e.command.trim();
        }
        if (e.skills?.length > 0) entry.skills = e.skills;
        external.push(entry);
      });
    });
    return external.length > 0 ? { external } : {};
  };

  /**
   * Parse hooks from backend response → UI state.
   * Handles both new { external: [{event, ...}] } and legacy { PreToolUse: [...] } formats.
   */
  const parseHooksFromBackend = (backendHooks) => {
    if (!backendHooks || typeof backendHooks !== "object") return {};
    // New format: { external: [{ event, hook_id, ... }] }
    if (Array.isArray(backendHooks.external)) {
      const result = {};
      backendHooks.external.forEach((entry) => {
        const ev = entry.event;
        if (!ev) return;
        if (!result[ev]) result[ev] = [];
        result[ev].push({
          hook_id: entry.hook_id || "",
          command: entry.command || "",
          matcher: entry.matcher || "",
          block_on_nonzero: !!entry.block_on_nonzero,
          timeout_seconds: entry.timeout_seconds || entry.timeout || 10,
          skills: entry.skills || [],
          _isManual: !entry.hook_id && !!entry.command,
        });
      });
      return result;
    }
    // Legacy format: { PreToolUse: [...], PostToolUse: [...] }
    const result = {};
    Object.entries(backendHooks).forEach(([ev, entries]) => {
      if (!Array.isArray(entries)) return;
      result[ev] = entries.map((e) => ({
        hook_id: e.hook_id || "",
        command: e.command || "",
        matcher: e.matcher || "",
        block_on_nonzero: !!e.block_on_nonzero,
        timeout_seconds: e.timeout_seconds || e.timeout || 10,
        skills: e.skills || [],
        _isManual: !e.hook_id && !!e.command,
      }));
    });
    return result;
  };

  // ---- Skill-level hook/approval helpers ----
  const updateSkillHooks = (skillIndex, updater) => {
    setSkills((prev) => {
      const updated = [...prev];
      const currentHooks = updated[skillIndex].hooks || {};
      updated[skillIndex] = { ...updated[skillIndex], hooks: typeof updater === "function" ? updater(currentHooks) : updater };
      return updated;
    });
  };

  // Derive admin status from role cookie
  const isAdminUser = role?.toLowerCase() === "admin" || role?.toLowerCase() === "superadmin";

  // ============ Constants ============
  const COPY_FEEDBACK_MS = 2000;
  const DISABLED_OPACITY = 0.5;

  // Reserved mount names that cannot be used as folder paths
  const RESERVED_MOUNT_NAMES = ["skills", "databases", "user", "agent", "session", "enterprise_context"];

  // ============ Path Handlers (shared for both sections) ============
  const addPath = (section) => {
    if (section === "relative") {
      setAdditionalPaths((prev) => [...prev, { path: "", permission: "read" }]);
    } else {
      setAbsolutePaths((prev) => [...prev, { path: "", permission: "read" }]);
    }
  };

  const removePath = (index, section) => {
    if (section === "relative") {
      setAdditionalPaths((prev) => prev.filter((_, i) => i !== index));
    } else {
      setAbsolutePaths((prev) => prev.filter((_, i) => i !== index));
    }
  };

  const updatePath = (index, field, value, section) => {
    const setter = section === "relative" ? setAdditionalPaths : setAbsolutePaths;
    setter((prev) => {
      const updated = [...prev];
      updated[index] = { ...updated[index], [field]: value };
      return updated;
    });
  };

  // ============ Merge Helper: Combine both sections for API payload ============
  const buildAdditionalPathsPayload = () => {
    const relativePaths = additionalPaths
      .filter((ap) => ap.path.trim() !== "")
      .map((ap) => ({ path: ap.path.trim(), permission: ap.permission, absolute: false }));
    const absPaths = absolutePaths
      .filter((ap) => ap.path.trim() !== "")
      .map((ap) => ({ path: ap.path.trim(), permission: ap.permission, absolute: true }));
    return [...relativePaths, ...absPaths];
  };

  /** Check if any path-related data has been modified from initial state */
  const hasPathsChanged = () => {
    return (
      JSON.stringify(additionalPaths) !== JSON.stringify(initialAdditionalPaths) ||
      JSON.stringify(absolutePaths) !== JSON.stringify(initialAbsolutePaths)
    );
  };

  // ============ Validation Helpers ============
  /** Validate a single path entry - returns error message or null */
  const validatePathEntry = (path) => {
    if (!path.trim()) return null; // Empty paths are filtered out
    if (path.includes("..")) return `Path cannot contain ".." (directory traversal)`;
    const mountName = path.trim().split("/").pop();
    if (RESERVED_MOUNT_NAMES.includes(mountName.toLowerCase())) {
      return `Conflicts with reserved mount name "${mountName}"`;
    }
    return null;
  };

  // ============ Helper: Extract Array from Response ============
  const extractArrayFromResponse = (response, fallbackKey) => {
    return Array.isArray(response) ? response : response?.details || response?.data || response?.results || response?.items || response?.[fallbackKey] || [];
  };

  // ============ Helper: Safely Parse JSON Array Field ============
  const parseJsonArrayField = (field, fieldName = "field") => {
    if (!field) return [];
    try {
      return typeof field === "string" ? JSON.parse(field) : (Array.isArray(field) ? field : []);
    } catch (error) {
      handleError && handleError(error, { customMessage: `Error parsing ${fieldName}` });
      addMessage && addMessage(`Failed to parse ${fieldName}. Please check your data format.`, "error");
      return [];
    }
  };

  // ============ Helper: Parse tools_with_versions array into { tool_id: version } map ============
  const parseToolVersions = (agentObj) => {
    // Support array format: [{ tool_id: "...", tool_version: "v1" }]
    const twv = agentObj?.tools_with_versions;
    if (Array.isArray(twv) && twv.length > 0) {
      const map = {};
      twv.forEach((item) => {
        if (item?.tool_id && item?.tool_version) {
          map[item.tool_id] = item.tool_version;
        }
      });
      if (Object.keys(map).length > 0) return map;
    }
    // Fallback: support legacy object format { tool_id: "v1" }
    if (agentObj?.tool_versions && typeof agentObj.tool_versions === "object" && !Array.isArray(agentObj.tool_versions)) {
      if (Object.keys(agentObj.tool_versions).length > 0) return agentObj.tool_versions;
    }
    // Fallback: extract from tools_details/tools array — use tool_version or default to latest version
    const toolsDetails = agentObj?.tools_details || agentObj?.tools || [];
    if (Array.isArray(toolsDetails) && toolsDetails.length > 0) {
      const map = {};
      toolsDetails.forEach((tool) => {
        const id = tool?.tool_id || tool?.id;
        if (!id) return;
        // Use explicit tool_version if available
        const version = tool?.tool_version || tool?.selected_version;
        if (version) {
          map[id] = version;
        } else if (Array.isArray(tool?.versions) && tool.versions.length > 0) {
          // Default to latest version from tool's versions array
          map[id] = tool.versions[tool.versions.length - 1];
        }
      });
      if (Object.keys(map).length > 0) return map;
    }
    return null;
  };

  // ============ Helper: Convert toolVersions map to tools_with_versions array ============
  const buildToolsWithVersions = (versionsMap) => {
    return Object.entries(versionsMap).map(([toolId, version]) => ({
      tool_id: toolId,
      tool_version: version,
    }));
  };

  // ============ Helper: Get Knowledge Base IDs from Agent Data ============
  const getKnowledgeBaseIds = (agentObj) => {
    const kbIdsField = agentObj?.knowledgebase_ids || agentObj?.kb_ids;
    return parseJsonArrayField(kbIdsField, "knowledgebase_ids");
  };

  // Add new state for non-removable tags
  const [nonRemovableTags, setNonRemovableTags] = useState([]);
  const generalTagRef = useRef(null);



  // Modify the fetch models useEffect to also set default "general" tag
  useEffect(() => {
    if (hasLoadedModelsOnce.current) return;
    hasLoadedModelsOnce.current = true;

    (async () => {
      // Fetch models
      setModelsLoading(true);
      try {
        const data = await fetchData(APIs.GET_MODELS);
        setUnconfiguredCostModels(getUnconfiguredCostModels(data));
        if (data?.models && Array.isArray(data.models)) {
          const formattedModels = data.models.map((model) => ({
            label: model,
            value: model,
          }));
          setModels(formattedModels);

          // Auto-select model based on mode
          if (!formData.model_name) {
            // For create mode: always use default_model_name
            // For update mode: prioritize existing agent's model (already set in formData via useEffect), fallback to default_model_name
            if (isCreateMode && data.default_model_name) {
              setFormData((prev) => ({ ...prev, model_name: data.default_model_name }));
            } else if (data.default_model_name) {
              // Update mode fallback (if model_name wasn't set from agent data)
              setFormData((prev) => ({ ...prev, model_name: data.default_model_name }));
            } else if (formattedModels.length > 0) {
              // Final fallback: first model alphabetically
              const sortedModels = [...formattedModels].sort((a, b) => a.label.localeCompare(b.label));
              setFormData((prev) => ({ ...prev, model_name: sortedModels[0].label }));
            }
          }
        }
      } catch (err) {
        const errorMessage = err?.response?.data?.detail || err?.response?.data?.message || err?.message || "Failed to load models";
        addMessage(errorMessage, "error");
      } finally {
        setModelsLoading(false);
      }

      // Fetch tags to find "general" tag (separate try-catch to avoid showing wrong error)
      try {
        const tagsData = await fetchData(APIs.GET_TAGS);
        if (tagsData && Array.isArray(tagsData)) {
          const generalTag = tagsData.find((tag) => tag.tag_name.toLowerCase() === "general");

          if (generalTag) {
            generalTagRef.current = generalTag;
            setNonRemovableTags([generalTag]);
            if (isCreateMode) {
              // Set general tag as default for create mode
              setSelectedTagsForSelector([generalTag]);
              setSelectedTagIds([generalTag.tag_id]);
            }
          }
        }
      } catch (err) {
        console.error("Failed to fetch tags for default:", err);
      }
    })();
  }, [fetchData, handleError, isCreateMode]);

  // ============ Fetch Guardrail Types ============
  useEffect(() => {
    (async () => {
      setGuardrailsLoading(true);
      try {
        const data = await fetchData(APIs.GET_GUARDRAIL_TYPES);
        if (Array.isArray(data)) {
          setGuardrailTypes(data);
        } else if (Array.isArray(data?.guardrail_types)) {
          setGuardrailTypes(data.guardrail_types);
        } else if (Array.isArray(data?.data)) {
          setGuardrailTypes(data.data);
        }
      } catch {
        setGuardrailTypes([]);
      } finally {
        setGuardrailsLoading(false);
      }
    })();
  }, [fetchData]);

  // ============ Fetch Available DB Connections ============
  useEffect(() => {
    if (!canViewDataConnectors || isMetaAgentType) return;
    const loadDbConnections = async () => {
      setLoadingDbConnections(true);
      try {
        const result = await fetchDbConnections();
        if (result.success) {
          const connections = result.data?.connections || result.data || [];
          setAvailableDbConnections(connections);
        }
      } catch {
        console.error("Failed to fetch database connections");
      } finally {
        setLoadingDbConnections(false);
      }
    };
    loadDbConnections();
  }, [canViewDataConnectors, isMetaAgentType]);

  // ============ Load Related Tools/Agents/KnowledgeBases ============
  // Build resources from agent response data directly (no separate API calls)
  const loadRelatedTools = async (type, selectedToolsId, selectedKbIds = [], agentResponse = null) => {
    try {
      const isToolBasedAgent = [REACT_AGENT, MULTI_AGENT, REACT_CRITIC_AGENT, PLANNER_EXECUTOR_AGENT, HYBRID_AGENT].includes(type);
      const isAgentBasedAgent = [META_AGENT, PLANNER_META_AGENT].includes(type);

      let allResources = [];

      // Try to use resource details from the agent response (backend now includes them)
      if (agentResponse) {
        // Extract tools from agent response
        const responseTools = agentResponse.tools_details || agentResponse.tools || [];
        const responseServers = agentResponse.servers_details || agentResponse.servers || [];
        const responseAgents = agentResponse.agents_details || agentResponse.sub_agents || [];
        const responseKbs = agentResponse.knowledgebases_details || agentResponse.knowledgebases || agentResponse.knowledge_bases || [];

        if (isToolBasedAgent && (responseTools.length > 0 || responseServers.length > 0)) {
          allResources = [
            ...responseTools.map((t) => ({ ...t, type: "tools" })),
            ...responseServers.map((s) => ({ ...s, type: "servers" })),
          ];
        } else if (isAgentBasedAgent && responseTools.length > 0) {
          allResources = responseTools.map((a) => ({ ...a, type: "agents" }));
        }

        // If we got tool/agent IDs but no detail objects, build minimal resources from IDs
        if (allResources.length === 0 && selectedToolsId.length > 0) {
          if (isToolBasedAgent) {
            allResources = selectedToolsId.map((id) => ({
              tool_id: id,
              tool_name: id,
              type: "tools",
            }));
          } else if (isAgentBasedAgent) {
            allResources = selectedToolsId.map((id) => ({
              agentic_application_id: id,
              agentic_application_name: id,
              type: "agents",
            }));
          }
        }

        // Add knowledge bases from response
        if (responseKbs.length > 0) {
          allResources = [
            ...allResources,
            ...responseKbs.map((kb) => ({ ...kb, type: "knowledgebases" })),
          ];
        } else if (selectedKbIds && selectedKbIds.length > 0) {
          // Fallback: fetch KB details via service if not in response
          const kbResources = await getKnowledgeBasesForAgent(selectedKbIds);
          allResources = [...allResources, ...kbResources];
        }
      } else {
        // Fallback: no agent response provided, use old API calls
        if (isToolBasedAgent) {
          const response = await postData(APIs.GET_TOOLS_BY_LIST, selectedToolsId);
          const tools = Array.isArray(response?.tools) ? response.tools : [];
          const servers = Array.isArray(response?.servers) ? response.servers : [];

          const toolResources = tools.map((tool) => ({ ...tool, type: "tools" }));
          const serverResources = servers.map((server) => ({ ...server, type: "servers" }));
          allResources = [...allResources, ...toolResources, ...serverResources];

          if (tools.length === 0 && servers.length === 0) {
            const flatItems = extractArrayFromResponse(response, "tools");
            const resourcesWithType = flatItems.map((item) => ({
              ...item,
              type: item.mcp_config ? "servers" : "tools",
            }));
            allResources = [...allResources, ...resourcesWithType];
          }
        } else if (isAgentBasedAgent) {
          const response = await postData(APIs.GET_AGENTS_BY_LIST, selectedToolsId);
          const agents = extractArrayFromResponse(response, "agents");
          const resourcesWithType = agents.map((agent) => ({ ...agent, type: "agents" }));
          allResources = [...allResources, ...resourcesWithType];
        }

        if (selectedKbIds && selectedKbIds.length > 0) {
          const kbResources = await getKnowledgeBasesForAgent(selectedKbIds);
          allResources = [...allResources, ...kbResources];
        }
      }

      setSelectedResources(allResources);
      setInitialSelectedResources(allResources);
    } catch (e) {
      const errorMessage = e?.response?.data?.detail || e?.response?.data?.message || e?.message || "Failed to load related tools";
      addMessage(errorMessage, "error");
    } finally {
      setSelectedToolsLoading(false);
    }
  };

  // ============ Fetch Agent Details (Update Mode) ============
  useEffect(() => {
    if (!isUpdateMode || !currentAgentData?.agentic_application_id || hasLoadedAgentData.current) return;
    hasLoadedAgentData.current = true;

    const fetchAgentDetail = async () => {
      if (recycleBin) {
        // Use provided data for recycle bin
        const type = currentAgentData?.agentic_application_type;
        setAgentType(type);
        // Safely parse system_prompt for recycle bin
        try {
          const systemPrompt = typeof agentData?.system_prompt === "string"
            ? JSON.parse(agentData.system_prompt)
            : (agentData?.system_prompt || {});
          setSystemPromptData(systemPrompt);
        } catch {
          setSystemPromptData({});
        }
        setFullAgentData(agentData);
        setWelcomeMessage(agentData?.welcome_message || "");
        // Set file context management prompt fields
        setFileContextManagementPrompt(agentData?.file_context_management_prompt || "");
        setFileContextPromptExists(agentData?.file_context_prompt_exists || false);
        // Initialize tool versions for recycle bin
        const parsedRecycleBinVersions = parseToolVersions(agentData);
        if (parsedRecycleBinVersions) {
          setToolVersions(parsedRecycleBinVersions);
        }
        try {
          // Safely parse tools_id and knowledgebase_ids for recycle bin
          const toolsId = parseJsonArrayField(agentData?.tools_id, "tools_id");
          const kbIds = getKnowledgeBaseIds(agentData);
          loadRelatedTools(agentData?.agentic_application_type, toolsId, kbIds, agentData);
        } catch {
          setSelectedToolsLoading(false);
        }

        // ── Skill Agent: fetch skills + enterprise context even in recycle bin ──
        if (type === SKILL_AGENT) {
          const agentId = currentAgentData?.agentic_application_id;
          setFormData({
            agentic_application_name: agentData?.agentic_application_name,
            agentic_application_type: type,
            created_by: agentData?.created_by || "",
            agentic_application_description: agentData?.agentic_application_description,
            model_name: agentData?.model_name,
          });

          // Load additional_paths from agent data
          const allPaths = Array.isArray(agentData?.additional_paths) ? agentData.additional_paths : [];
          const relativePaths = allPaths.filter((ap) => !ap.absolute).map((ap) => ({ path: ap.path, permission: ap.permission }));
          const absPaths = allPaths.filter((ap) => ap.absolute).map((ap) => ({ path: ap.path, permission: ap.permission }));
          setAdditionalPaths(relativePaths);
          setInitialAdditionalPaths(relativePaths);
          setAbsolutePaths(absPaths);
          setInitialAbsolutePaths(absPaths);

          setSkillsLoading(true);
          try {
            const [skillsResponse, contextResponse] = await Promise.all([
              fetchData(`${APIs.AGENTOS_AGENTS}/${agentId}/skills`).catch(() => null),
              fetchData(`${APIs.AGENTOS_AGENTS}/${agentId}/context`).catch(() => null),
            ]);

            if (skillsResponse) {
              const skillsList = skillsResponse?.skills || [];
              const skillNames = skillsList.map((s) => s.name);
              setOriginalSkillNames(skillNames);

              const skillDetails = skillsList.map((s) => {
                const filesDetail = s.files_detail || [];
                const getFileContent = (fileName) =>
                  filesDetail.find((f) => f.name === fileName)?.content || "";
                const reservedFileNames = ["SKILL.md", "INSTRUCTIONS.md", "EXAMPLES.md"];
                const additionalFiles = filesDetail
                  .filter((f) => !reservedFileNames.includes(f.name))
                  .map((f) => ({ filename: f.name, content: f.content || "" }));
                const skillHooks = parseHooksFromBackend(s.hooks);

                return {
                  skill_name: s.name,
                  description: s.description || "",
                  keywords: s.triggers || [],
                  details: s.body || "",
                  execution_mode: s.execution_mode || "react",
                  category: s.category || "general",
                  instructions_md_content: getFileContent("INSTRUCTIONS.md"),
                  examples_md_content: getFileContent("EXAMPLES.md"),
                  additional_files: additionalFiles,
                  databases: (s.databases || []).map((db) => ({
                    connection_name: db.connection_name || "",
                    sql_mode: db.sql_mode || "read_only",
                  })),
                  hooks: skillHooks,
                  steps: s.steps || [],
                  worker_skills: s.worker_skills || [],
                  max_steps: s.max_steps ?? null,
                  max_iterations: s.max_iterations ?? null,
                  quality_threshold: s.quality_threshold ?? null,
                  evaluation_criteria: s.evaluation_criteria || "",
                };
              });

              if (skillDetails.length > 0) {
                setSkills(skillDetails);
                setActiveSkillIndex(0);
              }
            }

            // Parse enterprise context
            if (contextResponse) {
              setEnterpriseContextEnabled(contextResponse?.enterprise_context_enabled ?? false);
              setDefaultSkill(contextResponse?.default_skill || agentData?.default_skill || "general");

              const available = contextResponse?.available || {};
              if (available.master_context) {
                setEnterpriseContext(available.master_context.content || "");
                setMasterContextMeta({ size_bytes: available.master_context.size_bytes || 0 });
              }
              if (available.entity_guide && typeof available.entity_guide === "object") {
                setEntityGuide(available.entity_guide.content || "");
                setEntityGuideMeta({
                  name: available.entity_guide.name || "",
                  size_bytes: available.entity_guide.size_bytes || 0,
                });
              }
              const scList = available.skill_contexts || [];
              setSkillContexts(
                scList.map((sc) => ({
                  skill_name: sc.name || "",
                  content: sc.content || "",
                  size_bytes: sc.size_bytes || 0,
                })),
              );
              const polList = available.policies || [];
              setPolicies(
                polList.map((p) => ({
                  name: p.name || "",
                  content: p.content || "",
                  size_bytes: p.size_bytes || 0,
                })),
              );
            }
          } catch (e) {
            console.error("Error loading skills/context for recycle bin:", e);
          } finally {
            setSkillsLoading(false);
          }
        }
        return;
      }

      setLoading(true);
      try {
        const data = await fetchData(APIs.GET_AGENTS_BY_ID + currentAgentData?.agentic_application_id);

        // Handle both array and object response formats
        const agent = Array.isArray(data) ? data[0] : data;

        if (!agent) {
          console.error("No agent data found in response");
          setSelectedToolsLoading(false);
          return;
        }

        const type = agent?.agentic_application_type;
        // Safely parse system_prompt - handle string, object, or undefined
        let systemPrompts = {};
        try {
          if (agent?.system_prompt) {
            systemPrompts = typeof agent.system_prompt === "string"
              ? JSON.parse(agent.system_prompt)
              : agent.system_prompt;
          }
        } catch (parseError) {
          console.error("Error parsing system_prompt:", parseError);
          systemPrompts = {};
        }

        // Parse tools_id and knowledgebase_ids using helper functions
        const selectedToolsId = parseJsonArrayField(agent?.tools_id, "tools_id");
        const selectedKbIds = getKnowledgeBaseIds(agent);

        setFullAgentData(agent);
        setAgentType(type || "");
        setSelectedGuardrail(agent?.guardrail_type || "");

        // ============ Skill Agent: Fetch Skills + Enterprise Context ============
        if (type === SKILL_AGENT) {
          const agentId = currentAgentData?.agentic_application_id;
          setFormData({
            agentic_application_name: agent?.agentic_application_name,
            agentic_application_type: type,
            created_by: userName === "Guest" ? agent.created_by : loggedInUserEmail,
            agentic_application_description: agent?.agentic_application_description,
            model_name: agent?.model_name,
          });

          // Load additional_paths from agent data — split by absolute flag
          const allPaths = Array.isArray(agent?.additional_paths) ? agent.additional_paths : [];
          const relativePaths = allPaths.filter((ap) => !ap.absolute).map((ap) => ({ path: ap.path, permission: ap.permission }));
          const absPaths = allPaths.filter((ap) => ap.absolute).map((ap) => ({ path: ap.path, permission: ap.permission }));
          setAdditionalPaths(relativePaths);
          setInitialAdditionalPaths(relativePaths);
          setAbsolutePaths(absPaths);
          setInitialAbsolutePaths(absPaths);

          // Fetch skills list and enterprise context in parallel
          setSkillsLoading(true);
          try {
            const [skillsResponse, contextResponse] = await Promise.all([
              fetchData(`${APIs.AGENTOS_AGENTS}/${agentId}/skills`),
              fetchData(`${APIs.AGENTOS_AGENTS}/${agentId}/context`).catch(() => null),
            ]);

            // Parse skills list — structured fields from GET response
            const skillsList = skillsResponse?.skills || [];
            const skillNames = skillsList.map((s) => s.name);
            setOriginalSkillNames(skillNames);

            // Map API response fields to internal state shape
            // API returns: { name, description, triggers[], category, body, execution_mode, files_detail? }
            const skillDetails = skillsList.map((s) => {
              // Also check for companion files if files_detail exists
              const filesDetail = s.files_detail || [];
              const getFileContent = (fileName) =>
                filesDetail.find((f) => f.name === fileName)?.content || "";

              // Additional files = everything except reserved files
              const reservedFileNames = ["SKILL.md", "INSTRUCTIONS.md", "EXAMPLES.md"];
              const additionalFiles = filesDetail
                .filter((f) => !reservedFileNames.includes(f.name))
                .map((f) => ({ filename: f.name, content: f.content || "" }));

              // Parse skill-level hooks from API
              const skillHooks = parseHooksFromBackend(s.hooks);

              return {
                skill_name: s.name,
                description: s.description || "",
                keywords: s.triggers || [],
                details: s.body || "",
                execution_mode: s.execution_mode || "react",
                category: s.category || "general",
                instructions_md_content: getFileContent("INSTRUCTIONS.md"),
                examples_md_content: getFileContent("EXAMPLES.md"),
                additional_files: additionalFiles,
                databases: (s.databases || []).map((db) => ({
                  connection_name: db.connection_name || "",
                  sql_mode: db.sql_mode || "read_only",
                })),
                hooks: skillHooks,
              };
            });

            if (skillDetails.length > 0) {
              setSkills(skillDetails);
              setActiveSkillIndex(0);
            }

            // Parse enterprise context from actual API shape
            // Response: { enterprise_context_enabled, available: { master_context: {size_bytes, content}, skill_contexts: [], policies: [{name, size_bytes, content}], entity_guide: null|{...}, users: [] } }
            if (contextResponse) {
              setEnterpriseContextEnabled(contextResponse?.enterprise_context_enabled ?? false);
              setDefaultSkill(contextResponse?.default_skill || agent?.default_skill || "general");

              const available = contextResponse?.available || {};

              // Master context — content + size_bytes
              if (available.master_context) {
                setEnterpriseContext(available.master_context.content || "");
                setMasterContextMeta({ size_bytes: available.master_context.size_bytes || 0 });
              } else {
                setEnterpriseContext("");
                setMasterContextMeta(null);
              }

              // Entity guide — null or object with {name, size_bytes, content}
              if (available.entity_guide && typeof available.entity_guide === "object") {
                setEntityGuide(available.entity_guide.content || "");
                setEntityGuideMeta({
                  name: available.entity_guide.name || "",
                  size_bytes: available.entity_guide.size_bytes || 0,
                });
              } else {
                setEntityGuide("");
                setEntityGuideMeta(null);
              }

              // Skill contexts — array of {name, size_bytes, content}
              const scList = available.skill_contexts || [];
              setSkillContexts(
                scList.map((sc) => ({
                  skill_name: sc.name || "",
                  content: sc.content || "",
                  size_bytes: sc.size_bytes || 0,
                })),
              );

              // Policies — array of {name, size_bytes, content}
              const polList = available.policies || [];
              setPolicies(
                polList.map((p) => ({
                  name: p.name || "",
                  content: p.content || "",
                  size_bytes: p.size_bytes || 0,
                })),
              );
            }
            // Load hooks from agent data
            const agentHooks = parseHooksFromBackend(agent?.hooks);
            setHooks(agentHooks);
            setInitialHooks(JSON.parse(JSON.stringify(agentHooks)));
          } catch (contextErr) {
            console.error("Error loading skill agent data:", contextErr);
          } finally {
            setSkillsLoading(false);
          }

          setSelectedToolsLoading(false);
          setModifiedSkillNames(new Set());
          setRemovedSkillNames([]);
          return; // Skip standard agent data loading below
        }

        // ============ Standard Agent Data Loading ============
        setSystemPromptData(systemPrompts || {});

        // Set welcome message from API response
        setWelcomeMessage(agent?.welcome_message || "");

        // Set file context management prompt fields from API response
        setFileContextManagementPrompt(agent?.file_context_management_prompt || "");

        // Load additional_paths from agent data — split by absolute flag
        const allPaths = Array.isArray(agent?.additional_paths) ? agent.additional_paths : [];
        const relativePaths = allPaths.filter((ap) => !ap.absolute).map((ap) => ({ path: ap.path, permission: ap.permission }));
        const absPaths = allPaths.filter((ap) => ap.absolute).map((ap) => ({ path: ap.path, permission: ap.permission }));
        setAdditionalPaths(relativePaths);
        setInitialAdditionalPaths(relativePaths);
        setAbsolutePaths(absPaths);
        setInitialAbsolutePaths(absPaths);

        setFileContextPromptExists(agent?.file_context_prompt_exists || false);

        // Initialize tool versions from agent data
        const parsedVersions = parseToolVersions(agent);
        if (parsedVersions) {
          setToolVersions(parsedVersions);
        }

        // Set database connection names from API response
        const dbConns = Array.isArray(agent?.db_connection_names) ? agent.db_connection_names : [];
        setSelectedDbConnections(dbConns);
        setInitialDbConnections(dbConns);

        setFormData({
          agentic_application_name: agent?.agentic_application_name,
          agentic_application_type: type,
          created_by: userName === "Guest" ? agent.created_by : loggedInUserEmail,
          agentic_application_description: agent?.agentic_application_description,
          agentic_application_workflow_description: agent?.agentic_application_workflow_description,
          system_prompt: agent?.system_prompt,
          model_name: agent?.model_name,
        });

        // Load validation criteria
        if (Array.isArray(agent?.validation_criteria)) {
          setValidationPatterns(
            agent.validation_criteria.map((p) => ({
              query: p.query || "",
              expected_answer: p.expected_answer || "none",
              validator: p.validator || null,
            })),
          );
        } else if (Array.isArray(agent?.validation_patterns)) {
          setValidationPatterns(
            agent.validation_patterns.map((p) => ({
              query: p.query_detail || "",
              expected_answer: p.criteria || "none",
              validator: p.validator_id || null,
            })),
          );
        }

        // Load related tools/agents/knowledge bases
        if (type) {
          setSelectedToolsLoading(true);
          loadRelatedTools(type, selectedToolsId, selectedKbIds, agent);
        } else {
          setSelectedToolsLoading(false);
        }
      } catch (e) {
        const errorMessage = e?.response?.data?.detail || e?.response?.data?.message || e?.message || "Failed to load agent details";
        addMessage(errorMessage, "error");
      } finally {
        setLoading(false);
      }
    };

    fetchAgentDetail();
  }, [isUpdateMode, currentAgentData, recycleBin, fetchData, handleError, loggedInUserEmail, userName, postData]);

  // ============ Control Global Popup Visibility ============
  useEffect(() => {
    setShowPopup(!loading);
  }, [loading, setShowPopup]);

  // ============ Update Selected Prompt Data ============
  useEffect(() => {
    if (!isUpdateMode) return;

    const promptMap = {
      [PLANNER_META_AGENT]: systemPromptData[plannersystempromtType],
      [REACT_CRITIC_AGENT]: systemPromptData[reactCriticSystemPromptType],
      [PLANNER_EXECUTOR_AGENT]: systemPromptData[plannerExecutorSystemPromptType],
    };

    setSelectedPromptData(promptMap[agentType] || systemPromptData[systemPromptType] || "");
  }, [isUpdateMode, agentType, systemPromptType, plannersystempromtType, reactCriticSystemPromptType, plannerExecutorSystemPromptType, systemPromptData]);

  // ============ Load Tags for Update Mode ============
  useEffect(() => {
    if (!isUpdateMode || !fullAgentData.tags || tags.length === 0) return;

    const selectedTagObjects = fullAgentData.tags || [];
    setSelectedTagsForSelector(selectedTagObjects);
    setSelectedTagIds(selectedTagObjects.map((t) => t.tag_id));

    // Cache the general tag for auto-add behavior
    const generalInTags = selectedTagObjects.find((tag) => tag.tag_name.toLowerCase() === "general");
    if (generalInTags) {
      generalTagRef.current = generalInTags;
      setNonRemovableTags([generalInTags]);
    }
  }, [isUpdateMode, fullAgentData, tags]);

  // ============ Event Handlers ============
  const handleChange = (event) => {
    if (!isValidEvent(event)) return;

    const { name, value } = event.target;
    const sanitizedValue = sanitizeFormField(name, value);

    setFormData((prev) => ({
      ...prev,
      [name]: sanitizedValue,
    }));
  };

  const handleTagsChange = (newSelectedTags) => {
    const general = generalTagRef.current;
    if (!general) {
      setSelectedTagsForSelector(newSelectedTags);
      setSelectedTagIds(newSelectedTags.map((t) => t.tag_id));
      return;
    }

    // If no tags left, default back to General (non-removable)
    if (newSelectedTags.length === 0) {
      setSelectedTagsForSelector([general]);
      setSelectedTagIds([general.tag_id]);
      setNonRemovableTags([general]);
      return;
    }

    const nonGeneralCount = newSelectedTags.filter((tag) => tag.tag_name.toLowerCase() !== "general").length;

    // General is removable only when other tags exist
    setSelectedTagsForSelector(newSelectedTags);
    setSelectedTagIds(newSelectedTags.map((t) => t.tag_id));
    setNonRemovableTags(nonGeneralCount > 0 ? [] : [general]);
  };

  const handleSaveSelection = (resources) => {
    setSelectedResources(resources);

    if (!isUpdateMode) return;

    // Separate resources by type
    const toolServerResources = resources.filter((r) => r.type === "tools" || r.type === "servers" || r.tool_id);
    const agentResources = resources.filter((r) => r.type === "agents" || r.agentic_application_id);
    const kbResources = resources.filter((r) => r.type === "knowledgebases" || r.kb_id);

    const initialToolServerResources = initialSelectedResources.filter((r) => r.type === "tools" || r.type === "servers" || r.tool_id);
    const initialAgentResources = initialSelectedResources.filter((r) => r.type === "agents" || r.agentic_application_id);
    const initialKbResources = initialSelectedResources.filter((r) => r.type === "knowledgebases" || r.kb_id);

    // Calculate added/removed for tools/servers
    const currentToolIds = toolServerResources.map((r) => r.tool_id || r.id);
    const initialToolIds = initialToolServerResources.map((r) => r.tool_id || r.id);
    const addedToolIds = currentToolIds.filter((id) => !initialToolIds.includes(id));
    const removedToolIds = initialToolIds.filter((id) => !currentToolIds.includes(id));

    // Calculate added/removed for agents
    const currentAgentIds = agentResources.map((r) => r.agentic_application_id || r.id);
    const initialAgentIds = initialAgentResources.map((r) => r.agentic_application_id || r.id);
    const addedAgentIds = currentAgentIds.filter((id) => !initialAgentIds.includes(id));
    const removedAgentIds = initialAgentIds.filter((id) => !currentAgentIds.includes(id));

    // Calculate added/removed for knowledge bases
    const currentKbIds = kbResources.map((r) => r.kb_id || r.id);
    const initialKbIds = initialKbResources.map((r) => r.kb_id || r.id);
    const addedKbIds = currentKbIds.filter((id) => !initialKbIds.includes(id));
    const removedKbIds = initialKbIds.filter((id) => !currentKbIds.includes(id));

    const isAgentBased = [META_AGENT, PLANNER_META_AGENT].includes(agentType);
    if (isAgentBased) {
      setAddedAgentsId(addedAgentIds);
      setRemovedAgentsId(removedAgentIds);
    } else {
      setAddedToolsId(addedToolIds);
      setRemovedToolsId(removedToolIds);
    }

    // Always track KB changes regardless of agent type
    setAddedKnowledgeBaseIds(addedKbIds);
    setRemovedKnowledgeBaseIds(removedKbIds);
  };

  const handleClearAll = () => {
    setSelectedResources([]);
    setToolVersions({});
    setSelectedDbConnections([]);

    if (!isUpdateMode) return;

    // Separate initial resources by type
    const initialToolServerResources = initialSelectedResources.filter((r) => r.type === "tools" || r.type === "servers" || r.tool_id);
    const initialAgentResources = initialSelectedResources.filter((r) => r.type === "agents" || r.agentic_application_id);
    const initialKbResources = initialSelectedResources.filter((r) => r.type === "knowledgebases" || r.kb_id);

    const initialToolIds = initialToolServerResources.map((r) => r.tool_id || r.id);
    const initialAgentIds = initialAgentResources.map((r) => r.agentic_application_id || r.id);
    const initialKbIds = initialKbResources.map((r) => r.kb_id || r.id);

    const isAgentBased = [META_AGENT, PLANNER_META_AGENT].includes(agentType);

    if (isAgentBased) {
      setAddedAgentsId([]);
      setRemovedAgentsId(initialAgentIds);
    } else {
      setAddedToolsId([]);
      setRemovedToolsId(initialToolIds);
    }

    // Always clear KB tracking
    setAddedKnowledgeBaseIds([]);
    setRemovedKnowledgeBaseIds(initialKbIds);
  };

  const handleRemoveResource = (resource) => {
    // Handle database connection removal
    if (resource.type === "databases" || resource.db_connection_name) {
      const connName = resource.db_connection_name || resource.name;
      setSelectedDbConnections((prev) => prev.filter((n) => n !== connName));
      return;
    }

    const resourceId = resource.tool_id || resource.agentic_application_id || resource.kb_id || resource.id;
    const newResources = selectedResources.filter((r) => (r.tool_id || r.agentic_application_id || r.kb_id || r.id) !== resourceId);
    setSelectedResources(newResources);

    // Clean up tool version for removed tool
    if (resource.type === "tools" || resource.tool_id) {
      setToolVersions((prev) => {
        const updated = { ...prev };
        delete updated[resourceId];
        return updated;
      });
    }

    if (!isUpdateMode) return;

    // Separate resources by type
    const toolServerResources = newResources.filter((r) => r.type === "tools" || r.type === "servers" || r.tool_id);
    const agentResources = newResources.filter((r) => r.type === "agents" || r.agentic_application_id);
    const kbResources = newResources.filter((r) => r.type === "knowledgebases" || r.kb_id);

    const initialToolServerResources = initialSelectedResources.filter((r) => r.type === "tools" || r.type === "servers" || r.tool_id);
    const initialAgentResources = initialSelectedResources.filter((r) => r.type === "agents" || r.agentic_application_id);
    const initialKbResources = initialSelectedResources.filter((r) => r.type === "knowledgebases" || r.kb_id);

    // Calculate added/removed for tools/servers
    const currentToolIds = toolServerResources.map((r) => r.tool_id || r.id);
    const initialToolIds = initialToolServerResources.map((r) => r.tool_id || r.id);
    const addedToolIds = currentToolIds.filter((id) => !initialToolIds.includes(id));
    const removedToolIds = initialToolIds.filter((id) => !currentToolIds.includes(id));

    // Calculate added/removed for agents
    const currentAgentIds = agentResources.map((r) => r.agentic_application_id || r.id);
    const initialAgentIds = initialAgentResources.map((r) => r.agentic_application_id || r.id);
    const addedAgentIds = currentAgentIds.filter((id) => !initialAgentIds.includes(id));
    const removedAgentIds = initialAgentIds.filter((id) => !currentAgentIds.includes(id));

    // Calculate added/removed for knowledge bases
    const currentKbIds = kbResources.map((r) => r.kb_id || r.id);
    const initialKbIds = initialKbResources.map((r) => r.kb_id || r.id);
    const addedKbIds = currentKbIds.filter((id) => !initialKbIds.includes(id));
    const removedKbIds = initialKbIds.filter((id) => !currentKbIds.includes(id));

    const isAgentBased = [META_AGENT, PLANNER_META_AGENT].includes(agentType);
    if (isAgentBased) {
      setAddedAgentsId(addedAgentIds);
      setRemovedAgentsId(removedAgentIds);
    } else {
      setAddedToolsId(addedToolIds);
      setRemovedToolsId(removedToolIds);
    }

    // Always track KB changes
    setAddedKnowledgeBaseIds(addedKbIds);
    setRemovedKnowledgeBaseIds(removedKbIds);
  };

  // Handle resource click to open detail modal
  const handleResourceClick = (resource) => {
    setPreviewResource(resource);
    setPreviewModalOpen(true);
  };

  // Helper functions for ToolDetailModal props
  const getServerCodePreview = (server) => {
    if (!server) return "";
    const mcpType = (server?.mcp_type || "").toLowerCase();
    if (mcpType === "file") {
      const codeContent = server?.mcp_config?.args?.[1];
      if (typeof codeContent === "string" && codeContent.trim().length > 0) {
        return codeContent;
      }
    }
    return "# No code available for this server.";
  };

  const getServerModuleName = (server) => {
    if (!server) return "";
    const mcpType = (server?.mcp_type || "").toLowerCase();
    if (mcpType === "module") {
      return server?.mcp_config?.args?.[1] || "";
    }
    return "";
  };

  const getServerEndpoint = (server) => {
    if (!server) return "";
    const mcpType = (server?.mcp_type || "").toLowerCase();
    if (mcpType === "url") {
      return server?.mcp_config?.url || "";
    }
    return "";
  };

  const getResourceTab = (resource) => {
    // Prefer explicit type if set (e.g. from loadRelatedTools)
    if (resource?.type && ["tools", "servers", "agents", "knowledgebases", "databases"].includes(resource.type)) {
      return resource.type;
    }
    // Fallback: check for server by mcp_type, mcp_config, server_id, or tool_id with mcp_ prefix
    const toolId = resource?.tool_id || "";
    const isMcpServer = toolId.startsWith("mcp_");
    if (resource?.server_id || resource?.server_name || resource?.mcp_config || resource?.mcp_type || isMcpServer) return "servers";
    if (resource?.agentic_application_id || resource?.agent_id) return "agents";
    return "tools";
  };

  const handlePromptChange = (e) => {
    if (!isValidEvent(e)) return;

    const sanitizedValue = sanitizeFormField("system_prompt", e.target.value);
    const promptKeyMap = {
      [MULTI_AGENT]: systemPromptType,
      [PLANNER_META_AGENT]: plannersystempromtType,
      [REACT_CRITIC_AGENT]: reactCriticSystemPromptType,
      [PLANNER_EXECUTOR_AGENT]: plannerExecutorSystemPromptType,
    };

    const key = promptKeyMap[agentType] || Object.keys(systemPromptData)[0];
    setSystemPromptData((prev) => ({
      ...prev,
      [key]: sanitizedValue,
    }));
  };

  const handleClose = () => {
    onClose?.();
  };

  const handleLoginButton = (e) => {
    e.preventDefault();
    logout("/login");
  };

  // ============ Zoom Save Handlers for TextareaWithActions ============
  const handleAgentGoalZoomSave = (updatedContent) => {
    setFormData((prev) => ({
      ...prev,
      [isCreateMode ? "agent_goal" : "agentic_application_description"]: updatedContent,
    }));
  };

  const handleWorkflowZoomSave = (updatedContent) => {
    setFormData((prev) => ({
      ...prev,
      [isCreateMode ? "workflow_description" : "agentic_application_workflow_description"]: updatedContent,
    }));
  };

  const handleSystemPromptZoomSave = (updatedContent) => {
    if (isUpdateMode) {
      const promptKeyMap = {
        [MULTI_AGENT]: systemPromptType,
        [PLANNER_META_AGENT]: plannersystempromtType,
        [REACT_CRITIC_AGENT]: reactCriticSystemPromptType,
        [PLANNER_EXECUTOR_AGENT]: plannerExecutorSystemPromptType,
      };
      const key = promptKeyMap[agentType] || Object.keys(systemPromptData)[0];
      setSystemPromptData((prev) => ({
        ...prev,
        [key]: updatedContent,
      }));
    }
  };

  // ============ Validation Pattern Hidden Check ============
  const isValidatorPatternHidden = () => {
    // Hide validators if user doesn't have tools read access
    if (!canViewTools) return true;

    // In create mode, use formData.agent_type instead of agentType
    const typeToCheck = isCreateMode ? formData.agent_type : agentType;

    if (!typeToCheck) return true;
    return [META_AGENT, PLANNER_META_AGENT, HYBRID_AGENT, SKILL_AGENT].includes(typeToCheck);
  };

  // ============ Form Submission ============
  // ============ Reusable: Refresh Agent Data and Stay in Modal ============
  const refreshAgentDataAndStayOpen = async (agentId, operationType = "created") => {
    try {
      const successMsg = operationType === "created" ? "Agent created successfully! Loading details..." : "Agent updated successfully! Refreshing details...";
      addMessage(successMsg, "success");

      // Fetch fresh agent data
      const agentData = await fetchData(APIs.GET_AGENTS_BY_ID + agentId);
      const agent = Array.isArray(agentData) ? agentData[0] : agentData;

      if (agent) {
        // Switch to update mode with fresh data
        setCurrentMode("update");
        setCurrentAgentData({
          agentic_application_id: agentId,
          agentic_application_name: agent?.agentic_application_name
        });
        hasLoadedAgentData.current = false;

        const type = agent?.agentic_application_type;

        // Skill agent or React Skill agent: let the fetchAgentDetail useEffect handle skill/context loading
        if (type === SKILL_AGENT) {
          setFullAgentData(agent);
          setAgentType(type);
          setFormData({
            agentic_application_name: agent?.agentic_application_name,
            agentic_application_type: type,
            created_by: userName === "Guest" ? agent.created_by : loggedInUserEmail,
            agentic_application_description: agent?.agentic_application_description,
            model_name: agent?.model_name,
          });
          fetchAgents?.();
          setLoading(false);
          const finalMsg = operationType === "created" ? "Skill agent created and opened for editing!" : "Skill agent updated successfully!";
          addMessage(finalMsg, "success");
          return true;
        }

        // Parse system_prompt
        let systemPrompts = {};
        try {
          systemPrompts = typeof agent?.system_prompt === "string" ? JSON.parse(agent.system_prompt) : agent?.system_prompt || {};
        } catch (parseError) {
          console.error("Error parsing system_prompt:", parseError);
          systemPrompts = {};
        }

        // Parse tools_id and knowledgebase_ids
        const selectedToolsId = parseJsonArrayField(agent?.tools_id, "tools_id");
        const selectedKbIds = getKnowledgeBaseIds(agent);

        // Update all state with fresh data
        setFullAgentData(agent);
        setAgentType(type || "");
        setSystemPromptData(systemPrompts || {});
        setWelcomeMessage(agent?.welcome_message || "");
        setFileContextManagementPrompt(agent?.file_context_management_prompt || "");
        setFileContextPromptExists(agent?.file_context_prompt_exists || false);

        // Refresh tool versions from agent data
        const refreshedVersions = parseToolVersions(agent);
        if (refreshedVersions) {
          setToolVersions(refreshedVersions);
        }

        // Refresh database connection names
        const refreshedDbConns = Array.isArray(agent?.db_connection_names) ? agent.db_connection_names : [];
        setSelectedDbConnections(refreshedDbConns);
        setInitialDbConnections(refreshedDbConns);

        setFormData({
          agentic_application_name: agent?.agentic_application_name,
          agentic_application_type: type,
          created_by: userName === "Guest" ? agent.created_by : loggedInUserEmail,
          agentic_application_description: agent?.agentic_application_description,
          agentic_application_workflow_description: agent?.agentic_application_workflow_description,
          system_prompt: agent?.system_prompt,
          model_name: agent?.model_name,
        });

        // Load validation criteria
        if (Array.isArray(agent?.validation_criteria)) {
          setValidationPatterns(
            agent.validation_criteria.map((p) => ({
              query: p.query || "",
              expected_answer: p.expected_answer || "none",
              validator: p.validator || null,
            }))
          );
        }

        // Load related tools/agents
        if (type && (selectedToolsId?.length > 0 || selectedKbIds?.length > 0)) {
          setSelectedToolsLoading(true);
          loadRelatedTools(type, selectedToolsId, selectedKbIds, agent);
        }

        // Update tags
        if (agent?.tags) {
          setSelectedTagsForSelector(agent.tags);
          setSelectedTagIds(agent.tags.map((t) => t.tag_id));

          // Cache the general tag for auto-add behavior
          const generalInTags = agent.tags.find((tag) => tag.tag_name.toLowerCase() === "general");
          if (generalInTags) {
            generalTagRef.current = generalInTags;
            setNonRemovableTags([generalInTags]);
          }
        }

        // Refresh agents list in parent component
        fetchAgents?.();

        // Reset loading state
        setLoading(false);

        const finalMsg = operationType === "created" ? "Agent created and opened for editing!" : "Agent updated and ready for further editing!";
        addMessage(finalMsg, "success");
        return true;
      }
      return false;
    } catch (error) {
      console.error(`Failed to fetch ${operationType} agent:`, error);
      addMessage(`Agent ${operationType} but failed to refresh details.`, "error");
      setLoading(false);
      return false;
    }
  };

  // ============ Skill Agent Helper Functions ============

  // Ref for hidden file inputs
  const skillFileInputRef = useRef(null);
  const additionalFilesInputRef = useRef(null);

  // Drag-drop state for skill file uploads
  const [isDraggingSkillFile, setIsDraggingSkillFile] = useState(false);
  const [draggingFieldTarget, setDraggingFieldTarget] = useState(null); // tracks which field is being dragged onto

  // Read a .md / .txt / .py file and return its text content
  const readMdFile = (file) => {
    return new Promise((resolve, reject) => {
      if (!file.name.toLowerCase().endsWith(".md") && !file.name.toLowerCase().endsWith(".txt") && !file.name.toLowerCase().endsWith(".py")) {
        reject(new Error("Only .md, .txt and .py files are supported"));
        return;
      }
      if (file.size > 2 * 1024 * 1024) {
        reject(new Error("File size exceeds 2 MB limit"));
        return;
      }
      const reader = new FileReader();
      reader.onload = (e) => resolve(e.target.result);
      reader.onerror = () => reject(new Error("Failed to read file"));
      reader.readAsText(file);
    });
  };

  // Upload handler: reads a .md file and puts content into a skill field
  const handleSkillFileUpload = async (file, fieldName) => {
    try {
      const content = await readMdFile(file);
      updateSkill(activeSkillIndex, fieldName, content);
      addMessage(`Loaded ${file.name} into ${fieldName.replace(/_/g, " ")}`, "success");
    } catch (err) {
      addMessage(err.message || "Failed to read file", "error");
    }
  };

  // Upload handler for additional files: reads file and adds as { filename, content }
  const handleAdditionalFileUpload = async (files) => {
    const reserved = ["skill.md", "instructions.md", "examples.md"];
    for (const file of files) {
      if (reserved.includes(file.name.toLowerCase())) {
        addMessage(`${file.name} is a reserved name — use the dedicated fields above`, "error");
        continue;
      }
      try {
        const content = await readMdFile(file);
        const newSkills = [...skills];
        newSkills[activeSkillIndex] = {
          ...newSkills[activeSkillIndex],
          additional_files: [
            ...(newSkills[activeSkillIndex].additional_files || []),
            { filename: file.name, content },
          ],
        };
        setSkills(newSkills);
      } catch (err) {
        addMessage(`${file.name}: ${err.message}`, "error");
      }
    }
  };

  // Generic drag-drop handlers for skill fields
  const handleSkillDragEnter = (fieldTarget) => (e) => {
    e.preventDefault();
    e.stopPropagation();
    setIsDraggingSkillFile(true);
    setDraggingFieldTarget(fieldTarget);
  };

  const handleSkillDragLeave = (e) => {
    e.preventDefault();
    e.stopPropagation();
    setIsDraggingSkillFile(false);
    setDraggingFieldTarget(null);
  };

  const handleSkillDragOver = (e) => {
    e.preventDefault();
    e.stopPropagation();
  };

  // Drop handler for SKILL.md / INSTRUCTIONS.md / EXAMPLES.md fields
  const handleSkillFieldDrop = (fieldName) => (e) => {
    e.preventDefault();
    e.stopPropagation();
    setIsDraggingSkillFile(false);
    setDraggingFieldTarget(null);
    if (e.dataTransfer.files?.length > 0) {
      handleSkillFileUpload(e.dataTransfer.files[0], fieldName);
    }
  };

  // Drop handler for additional files zone
  const handleAdditionalFilesDrop = (e) => {
    e.preventDefault();
    e.stopPropagation();
    setIsDraggingSkillFile(false);
    setDraggingFieldTarget(null);
    if (e.dataTransfer.files?.length > 0) {
      handleAdditionalFileUpload(Array.from(e.dataTransfer.files));
    }
  };

  // Upload handler for enterprise context / entity guide fields
  const handleEnterpriseFieldUpload = async (file, setter) => {
    try {
      const content = await readMdFile(file);
      setter(content);
      addMessage(`Loaded ${file.name}`, "success");
    } catch (err) {
      addMessage(err.message || "Failed to read file", "error");
    }
  };

  const addSkill = () => {
    setSkills([
      ...skills,
      {
        skill_name: "",
        description: "",
        keywords: [],
        details: "",
        execution_mode: "react",
        category: "general",
        instructions_md_content: "",
        examples_md_content: "",
        additional_files: [],
        databases: [],
        hooks: {},
      },
    ]);
    setActiveSkillIndex(skills.length);
  };

  const removeSkill = (index) => {
    if (skills.length <= 1) {
      addMessage("At least one skill is required", "error");
      return;
    }
    // Track removed skill for update mode diff
    const removedName = skills[index]?.skill_name?.trim();
    if (isUpdateMode && removedName && originalSkillNames.includes(removedName)) {
      setRemovedSkillNames((prev) => [...prev, removedName]);
    }
    const newSkills = skills.filter((_, i) => i !== index);
    setSkills(newSkills);
    setActiveSkillIndex(Math.max(0, activeSkillIndex - 1));
  };

  const updateSkill = (index, field, value) => {
    const newSkills = [...skills];
    newSkills[index] = { ...newSkills[index], [field]: value };
    setSkills(newSkills);
  };

  // Additional files helpers for a skill
  const addAdditionalFile = (skillIndex) => {
    const newSkills = [...skills];
    newSkills[skillIndex] = {
      ...newSkills[skillIndex],
      additional_files: [...(newSkills[skillIndex].additional_files || []), { filename: "", content: "" }],
    };
    setSkills(newSkills);
  };

  const removeAdditionalFile = (skillIndex, fileIndex) => {
    const newSkills = [...skills];
    newSkills[skillIndex] = {
      ...newSkills[skillIndex],
      additional_files: newSkills[skillIndex].additional_files.filter((_, i) => i !== fileIndex),
    };
    setSkills(newSkills);
  };

  const updateAdditionalFile = (skillIndex, fileIndex, field, value) => {
    const newSkills = [...skills];
    const files = [...newSkills[skillIndex].additional_files];
    files[fileIndex] = { ...files[fileIndex], [field]: value };
    newSkills[skillIndex] = { ...newSkills[skillIndex], additional_files: files };
    setSkills(newSkills);
  };

  // ============ Database Connection Helpers (per-skill) ============
  const addDbConnectionToSkill = (skillIndex) => {
    const newSkills = [...skills];
    newSkills[skillIndex] = {
      ...newSkills[skillIndex],
      databases: [...(newSkills[skillIndex].databases || []), { connection_name: "", sql_mode: "read_only" }],
    };
    setSkills(newSkills);
  };

  const removeDbConnectionFromSkill = (skillIndex, dbIndex) => {
    const newSkills = [...skills];
    newSkills[skillIndex] = {
      ...newSkills[skillIndex],
      databases: newSkills[skillIndex].databases.filter((_, i) => i !== dbIndex),
    };
    setSkills(newSkills);
  };

  const updateDbConnectionInSkill = (skillIndex, dbIndex, field, value) => {
    const newSkills = [...skills];
    const dbs = [...(newSkills[skillIndex].databases || [])];
    dbs[dbIndex] = { ...dbs[dbIndex], [field]: value };
    newSkills[skillIndex] = { ...newSkills[skillIndex], databases: dbs };
    setSkills(newSkills);
  };

  // Policy helpers for enterprise context
  const addPolicy = () => setPolicies([...policies, { name: "", content: "", size_bytes: 0 }]);
  const removePolicy = (index) => setPolicies(policies.filter((_, i) => i !== index));
  const updatePolicy = (index, field, value) => {
    const updated = [...policies];
    updated[index] = { ...updated[index], [field]: value };
    setPolicies(updated);
  };

  // Skill context helpers for enterprise context
  const addSkillContext = () => setSkillContexts([...skillContexts, { skill_name: "", content: "", size_bytes: 0 }]);
  const removeSkillContext = (index) => setSkillContexts(skillContexts.filter((_, i) => i !== index));
  const updateSkillContext = (index, field, value) => {
    const updated = [...skillContexts];
    updated[index] = { ...updated[index], [field]: value };
    setSkillContexts(updated);
  };

  const handleSubmit = async (e) => {
    e.preventDefault();

    // Guest user check for update mode
    if (userName === "Guest" && isUpdateMode) {
      setShowGuestModal(true);
      return;
    }

    // Validation
    const agentName = isCreateMode ? formData.agent_name : formData.agentic_application_name;

    // Create mode validations
    if (isCreateMode) {
      if (!agentName?.trim()) {
        addMessage("Agent name is required", "error");
        return;
      }

      // Skill agent specific validations
      if (isAgentOSType) {
        const validSkills = skills.filter(
          (s) => s.skill_name?.trim() && s.description?.trim() && s.keywords?.length > 0,
        );
        if (validSkills.length === 0) {
          addMessage("At least one skill with name, description, and keywords is required", "error");
          return;
        }
        // Validate skill_name is snake_case (for any skills present)
        const invalidName = skills.find(
          (s) => s.skill_name?.trim() && !/^[a-z][a-z0-9_]*$/.test(s.skill_name.trim()),
        );
        if (invalidName) {
          addMessage(`Skill name "${invalidName.skill_name}" must be snake_case (lowercase, underscores)`, "error");
          return;
        }
      } else {
        // Standard agent validations
        if (!formData.agent_goal?.trim()) {
          addMessage("Agent goal is required", "error");
          return;
        }
        if (!formData.workflow_description?.trim()) {
          addMessage("Workflow description is required", "error");
          return;
        }
      }
    }

    // Update mode validations
    if (isUpdateMode) {
      if (!formData.agentic_application_name?.trim()) {
        addMessage("Agent name is required", "error");
        return;
      }

      if (isAgentOSType) {
        // AgentOS update validations
        if (isSkillAgentType) {
          const hasValidSkill = skills.some(
            (s) => s.skill_name?.trim() && s.description?.trim() && s.keywords?.length > 0,
          );
          if (!hasValidSkill) {
            addMessage("At least one skill with name, description, and keywords is required", "error");
            return;
          }
        }
        const invalidName = skills.find(
          (s) => s.skill_name?.trim() && !/^[a-z][a-z0-9_]*$/.test(s.skill_name.trim()),
        );
        if (invalidName) {
          addMessage(`Skill name "${invalidName.skill_name}" must be snake_case (lowercase, underscores)`, "error");
          return;
        }
      } else {
        // Standard agent update validations
        if (!formData.agentic_application_description?.trim()) {
          addMessage("Agent goal is required", "error");
          return;
        }
        if (!formData.agentic_application_workflow_description?.trim()) {
          addMessage("Workflow description is required", "error");
          return;
        }
        if (!welcomeMessage?.trim()) {
          addMessage("Welcome message is required", "error");
          return;
        }

        // Validate system prompt
        const currentSystemPrompt = selectedPromptData || systemPromptData[Object.keys(systemPromptData)[0]] || "";
        if (!currentSystemPrompt?.trim()) {
          addMessage("System prompt is required", "error");
          return;
        }
      }
    }

    // Common validations for both modes
    if (!formData.model_name) {
      addMessage("Please select a model", "error");
      return;
    }

    // Validate additional paths (Section 1 — relative)
    for (const ap of additionalPaths) {
      const error = validatePathEntry(ap.path);
      if (error) {
        addMessage(`Folder path: ${error}`, "error");
        return;
      }
    }

    // Validate absolute paths (Section 2 — admin only)
    for (const ap of absolutePaths) {
      const error = validatePathEntry(ap.path);
      if (error) {
        addMessage(`Absolute path: ${error}`, "error");
        return;
      }
    }

    // Check for duplicate mount names across both sections
    const allPathEntries = [...additionalPaths, ...absolutePaths];
    const mountNames = allPathEntries
      .filter((ap) => ap.path.trim())
      .map((ap) => ap.path.trim().split("/").pop().toLowerCase());
    const uniqueMounts = new Set(mountNames);
    if (mountNames.length !== uniqueMounts.size) {
      addMessage("Duplicate folder mount names detected. Each folder must have a unique mount name.", "error");
      return;
    }

    setLoading(true);

    try {
      if (isCreateMode) {
        // ============ Create Agent ============

        if (isSkillAgentType) {
          // ============ Create Skill Agent (AgentOS) ============
          // Build skills array using structured mode (recommended)
          const validSkills = skills
            .filter((s) => s.skill_name?.trim() && s.description?.trim() && s.keywords?.length > 0)
            .map((s) => {
              // Build additional_files as { filename: content } dict
              const additionalFilesDict = {};
              (s.additional_files || []).forEach((f) => {
                if (f.filename?.trim() && f.content?.trim()) {
                  additionalFilesDict[f.filename.trim()] = f.content;
                }
              });

              return {
                skill_name: s.skill_name.trim(),
                description: s.description.trim(),
                keywords: s.keywords,
                ...(s.details?.trim() && { details: s.details }),
                ...(s.execution_mode && s.execution_mode !== "react" && { execution_mode: s.execution_mode }),
                ...(s.category && s.category !== "general" && { category: s.category }),
                ...(s.instructions_md_content?.trim() && { instructions_md_content: s.instructions_md_content }),
                ...(s.examples_md_content?.trim() && { examples_md_content: s.examples_md_content }),
                ...(Object.keys(additionalFilesDict).length > 0 && { additional_files: additionalFilesDict }),
                ...((s.databases || []).length > 0 && {
                  databases: s.databases.filter((db) => db.connection_name?.trim()).map((db) => ({
                    connection_name: db.connection_name.trim(),
                    sql_mode: db.sql_mode || "read_only",
                  })),
                }),
                // Skill-level hooks → SKILL.md frontmatter
                ...(() => { const h = buildCleanHooks(s.hooks); return Object.keys(h).length > 0 ? { hooks: h } : {}; })(),
              };
            });

          // Build enterprise_context object with all 4 sub-fields
          const enterpriseContextObj = {};
          if (enterpriseContext?.trim()) enterpriseContextObj.enterprise_context_md = enterpriseContext;
          // skill_contexts: { skill_name: content } dict
          const skillContextsDict = {};
          skillContexts.forEach((sc) => {
            if (sc.skill_name?.trim() && sc.content?.trim()) {
              skillContextsDict[sc.skill_name.trim()] = sc.content;
            }
          });
          if (Object.keys(skillContextsDict).length > 0) enterpriseContextObj.skill_contexts = skillContextsDict;
          // policies: { name: content } dict
          const policiesDict = {};
          policies.forEach((p) => {
            if (p.name?.trim() && p.content?.trim()) {
              policiesDict[p.name.trim()] = p.content;
            }
          });
          if (Object.keys(policiesDict).length > 0) enterpriseContextObj.policies = policiesDict;
          if (entityGuide?.trim()) enterpriseContextObj.entity_guide = entityGuide;

          // Build hooks payload
          const hooksPayload = buildHooksPayload();

          const skillAgentPayload = {
            agent_name: formData.agent_name,
            agent_description: formData.agent_goal || "Skill-based AI assistant",
            model_name: formData.model_name,
            default_skill: defaultSkill || "general",
            skills: validSkills,
            ...(Object.keys(enterpriseContextObj).length > 0 && { enterprise_context: enterpriseContextObj }),
            ...(() => { const merged = buildAdditionalPathsPayload(); return merged.length > 0 ? { additional_paths: merged } : {}; })(),
            ...(Object.keys(hooksPayload).length > 0 && { hooks: hooksPayload }),
          };

          const response = await postData(APIs.AGENTOS_CREATE_AGENT, skillAgentPayload);

          if (response?.agent_id || response?.status === "success") {
            addMessage("Skill Agent Created Successfully!", "success");
            setFormData(createInitialFormData);
            setSkills([{ skill_name: "", description: "", keywords: [], details: "", execution_mode: "react", category: "general", instructions_md_content: "", examples_md_content: "", additional_files: [], databases: [], hooks: {} }]);
            setEnterpriseContext("");
            setSkillContexts([]);
            setPolicies([]);
            setEntityGuide("");
            setDefaultSkill("general");
            setHooks({});
            fetchAgents?.();
            onClose?.();
          } else {
            addMessage(response?.message || "Failed to create skill agent", "error");
          }
        } else {
          // ============ Create Standard Agent ============
          // Separate resources by type for the payload
          const isAgentBased = [META_AGENT, PLANNER_META_AGENT].includes(formData.agent_type);
          const agentResources = selectedResources.filter((r) => r.type === "agents" || r.agentic_application_id);
          const toolServerResources = selectedResources.filter((r) => r.type === "tools" || r.type === "servers" || (!r.kb_id && !r.agentic_application_id));
          const kbResources = selectedResources.filter((r) => r.type === "knowledgebases" || r.kb_id);

          const filteredCreatePatterns = isValidatorPatternHidden()
            ? []
            : validationPatterns
              .filter((p) => p.query && p.expected_answer)
              .map((p) => ({
                query: p.query,
                expected_answer: p.expected_answer,
                validator: p.validator || null,
              }));

          const payload = {
            agent_name: formData.agent_name,
            email_id: loggedInUserEmail,
            agent_goal: formData.agent_goal,
            workflow_description: formData.workflow_description,
            model_name: formData.model_name,
            agent_type: formData.agent_type,
            system_prompt: formData.system_prompt,
            category: formData.category,
            tag_ids: selectedTagsForSelector.map((t) => t.tag_id),
            tools_id: isAgentBased
              ? agentResources.map((r) => r.agentic_application_id || r.id)
              : toolServerResources.map((r) => r.tool_id || r.id),
            knowledgebase_ids: kbResources.map((r) => r.kb_id || r.id),
            validation_criteria: filteredCreatePatterns,
            ...(Object.keys(toolVersions).length > 0 && { tools_with_versions: buildToolsWithVersions(toolVersions) }),
            ...(selectedDbConnections.length > 0 && { db_connection_names: selectedDbConnections }),
            ...(selectedGuardrail && { guardrail_type: selectedGuardrail }),
          };

          const response = isAsyncModeEnabled()
            ? await submitAndPollAsync(postData, APIs.ONBOARD_AGENTS, payload, {
              onStatusChange: (status) => {
                if (status === "processing") addMessage("Agent onboarding in progress...", "success");
              },
            })
            : await postData(APIs.ONBOARD_AGENTS, payload);

          // ============ AUTO-TRANSITION TO UPDATE MODE ============
          if (response?.result?.agentic_application_id) {
            const agentId = response?.result?.agentic_application_id || "";

            // If additional_paths configured, save via AgentOS endpoint
            const mergedPaths = buildAdditionalPathsPayload();
            if (agentId && mergedPaths.length > 0) {
              try {
                // List 2: PUT /agents/{agent_id}  →  POST /agents/{agent_id}/update
                await putData(`${APIs.AGENTOS_AGENTS}/${agentId}/update`, {
                  additional_paths: mergedPaths,
                });
              } catch (pathErr) {
                console.error("Failed to save additional paths:", pathErr);
                if (pathErr?.response?.status === 403) {
                  addMessage(pathErr?.response?.data?.detail || "Permission denied. Only Admin can configure absolute mounts.", "error");
                } else {
                  addMessage("Agent created but failed to save folder mounts. You can add them in update mode.", "error");
                }
              }
            }

            if (agentId) {
              const success = await refreshAgentDataAndStayOpen(agentId, "created");
              if (success) {
                return; // Stay in update mode
              }
            }
          }

          // Fallback: If auto-transition fails, use old behavior
          addMessage("Agent Created Successfully!", "success");
          setFormData(createInitialFormData);
          setSelectedTagsForSelector([]);
          setSelectedResources([]);

          fetchAgents?.();
          onClose?.();
        }
      } else {
        // ============ Update Agent ============
        const agentId = currentAgentData?.agentic_application_id;

        if (isAgentOSType) {
          // ============ Update AgentOS Agent (Skill / React Skill) ============
          // Skills are updated individually via /agentos/agents/{id}/skills/...
          const currentSkillNames = skills
            .filter((s) => s.skill_name?.trim())
            .map((s) => s.skill_name.trim());

          // 1. Delete removed skills
          const skillsToDelete = removedSkillNames.filter((name) => !currentSkillNames.includes(name));
          for (const skillName of skillsToDelete) {
            try {
              // List 2: DELETE /agents/{agent_id}/skills/{skill_name}  →  POST /agents/{agent_id}/skills/{skill_name}/delete
              await deleteData(`${APIs.AGENTOS_AGENTS}/${agentId}/skills/${encodeURIComponent(skillName)}/delete`);
            } catch (deleteErr) {
              console.error(`Failed to delete skill "${skillName}":`, deleteErr);
            }
          }

          // 2. Add new skills / Update existing skills (structured mode)
          for (const skill of skills) {
            if (!skill.skill_name?.trim() || !skill.description?.trim()) continue;

            const normalizedName = skill.skill_name.trim();
            const isExisting = originalSkillNames.includes(normalizedName);

            // Build additional_files as { filename: content } dict
            const additionalFilesDict = {};
            (skill.additional_files || []).forEach((f) => {
              if (f.filename?.trim() && f.content?.trim()) {
                additionalFilesDict[f.filename.trim()] = f.content;
              }
            });

            if (isExisting) {
              // PUT — Update existing skill (send only changed structured fields)
              const skillHooksPayload = buildCleanHooks(skill.hooks);
              const updatePayload = {
                description: skill.description,
                keywords: skill.keywords,
                ...(skill.details?.trim() && { details: skill.details }),
                ...(skill.execution_mode && { execution_mode: skill.execution_mode }),
                ...(skill.category && { category: skill.category }),
                ...(skill.instructions_md_content?.trim() && { instructions_md_content: skill.instructions_md_content }),
                ...(skill.examples_md_content?.trim() && { examples_md_content: skill.examples_md_content }),
                ...(Object.keys(additionalFilesDict).length > 0 && { additional_files: additionalFilesDict }),
                // databases: replace-all semantics — send full list
                databases: (skill.databases || []).filter((db) => db.connection_name?.trim()).map((db) => ({
                  connection_name: db.connection_name.trim(),
                  sql_mode: db.sql_mode || "read_only",
                })),
                // Skill-level hooks → SKILL.md frontmatter
                hooks: Object.keys(skillHooksPayload).length > 0 ? skillHooksPayload : {},
              };

              try {
                // List 2: PUT /agents/{agent_id}/skills/{skill_name}  →  POST /agents/{agent_id}/skills/{skill_name}/update
                await putData(
                  `${APIs.AGENTOS_AGENTS}/${agentId}/skills/${encodeURIComponent(normalizedName)}/update`,
                  updatePayload,
                );
              } catch (updateErr) {
                console.error(`Failed to update skill "${normalizedName}":`, updateErr);
                addMessage(`Failed to update skill "${normalizedName}"`, "error");
              }
            } else {
              // POST — Add new skill (structured mode)
              const newSkillHooks = buildCleanHooks(skill.hooks);
              const addPayload = {
                skill: {
                  skill_name: normalizedName,
                  description: skill.description,
                  keywords: skill.keywords,
                  ...(skill.details?.trim() && { details: skill.details }),
                  ...(skill.execution_mode && skill.execution_mode !== "react" && { execution_mode: skill.execution_mode }),
                  ...(skill.category && skill.category !== "general" && { category: skill.category }),
                  ...(skill.instructions_md_content?.trim() && { instructions_md_content: skill.instructions_md_content }),
                  ...(skill.examples_md_content?.trim() && { examples_md_content: skill.examples_md_content }),
                  ...(Object.keys(additionalFilesDict).length > 0 && { additional_files: additionalFilesDict }),
                  ...((skill.databases || []).filter((db) => db.connection_name?.trim()).length > 0 && {
                    databases: skill.databases.filter((db) => db.connection_name?.trim()).map((db) => ({
                      connection_name: db.connection_name.trim(),
                      sql_mode: db.sql_mode || "read_only",
                    })),
                  }),
                  // Skill-level hooks → SKILL.md frontmatter
                  ...(Object.keys(newSkillHooks).length > 0 && { hooks: newSkillHooks }),
                },
              };

              try {
                await postData(`${APIs.AGENTOS_AGENTS}/${agentId}/skills`, addPayload);
              } catch (addErr) {
                console.error(`Failed to add skill "${normalizedName}":`, addErr);
                addMessage(`Failed to add skill "${normalizedName}"`, "error");
              }
            }
          }

          // 3. Update enterprise context
          const enterpriseContextObj = {};
          if (enterpriseContext?.trim()) enterpriseContextObj.enterprise_context_md = enterpriseContext;
          const skillContextsDict = {};
          skillContexts.forEach((sc) => {
            if (sc.skill_name?.trim() && sc.content?.trim()) {
              skillContextsDict[sc.skill_name.trim()] = sc.content;
            }
          });
          if (Object.keys(skillContextsDict).length > 0) enterpriseContextObj.skill_contexts = skillContextsDict;
          const policiesDict = {};
          policies.forEach((p) => {
            if (p.name?.trim() && p.content?.trim()) {
              policiesDict[p.name.trim()] = p.content;
            }
          });
          if (Object.keys(policiesDict).length > 0) enterpriseContextObj.policies = policiesDict;
          if (entityGuide?.trim()) enterpriseContextObj.entity_guide = entityGuide;

          if (Object.keys(enterpriseContextObj).length > 0) {
            try {
              await putData(`${APIs.AGENTOS_AGENTS}/${agentId}/context`, enterpriseContextObj);
            } catch (ctxErr) {
              console.error("Failed to update enterprise context:", ctxErr);
              addMessage("Failed to update enterprise context", "error");
            }
          }

          // 4. Update additional_paths, hooks if changed
          const agentUpdatePayload = {};
          if (hasPathsChanged()) {
            agentUpdatePayload.additional_paths = buildAdditionalPathsPayload();
          }
          if (hooksChanged()) {
            agentUpdatePayload.hooks = buildHooksPayload();
          }
          if (Object.keys(agentUpdatePayload).length > 0) {
            try {
              // List 2: PUT /agents/{agent_id}  →  POST /agents/{agent_id}/update
              await putData(`${APIs.AGENTOS_AGENTS}/${agentId}/update`, agentUpdatePayload);
            } catch (pathErr) {
              console.error("Failed to update agent config:", pathErr);
              if (pathErr?.response?.status === 403) {
                addMessage(pathErr?.response?.data?.detail || "Permission denied. Only the creator or Admin can modify this agent.", "error");
              } else if (pathErr?.response?.status === 422) {
                const detail = pathErr?.response?.data?.detail;
                const msg = Array.isArray(detail) ? detail.map((d) => d.msg).join("; ") : detail;
                addMessage(`Validation error: ${msg}`, "error");
              } else {
                addMessage("Failed to update agent configuration", "error");
              }
            }
          }

          // Reset tracking state
          setOriginalSkillNames(currentSkillNames);
          setModifiedSkillNames(new Set());
          setRemovedSkillNames([]);

          // Refresh agents list
          fetchAgents?.();

          // Refresh and stay in update mode
          if (agentId) {
            hasLoadedAgentData.current = false;
            const success = await refreshAgentDataAndStayOpen(agentId, "updated");
            if (success) return;
          }

          addMessage(isSkillAgentType ? "Skill agent updated successfully" : "React Skill agent updated successfully", "success");
          setLoading(false);
        } else {
          // ============ Update Standard Agent ============
          const isSystemPromptChanged = (() => {
            let parsedSystemPrompt = {};
            try {
              parsedSystemPrompt = typeof fullAgentData?.system_prompt === "string" ? JSON.parse(fullAgentData?.system_prompt) : fullAgentData?.system_prompt || {};
            } catch {
              // Parsing error ignored
            }
            return JSON.stringify(systemPromptData) !== JSON.stringify(parsedSystemPrompt);
          })();

          const filteredPatterns = isValidatorPatternHidden()
            ? []
            : validationPatterns
              .filter((p) => p.query && p.expected_answer)
              .map((p) => ({
                query: p.query,
                expected_answer: p.expected_answer,
                validator: p.validator || null,
              }));

          const isAgentBased = [META_AGENT, PLANNER_META_AGENT].includes(agentType);

          const payload = {
            agentic_application_name: formData.agentic_application_name,
            agentic_application_description: formData.agentic_application_description,
            agentic_application_workflow_description: formData.agentic_application_workflow_description,
            model_name: formData.model_name,
            created_by: fullAgentData.created_by,
            welcome_message: welcomeMessage,
            regenerate_system_prompt: regenerateSystemPrompt,
            regenerate_welcome_message: regenerateWelcomeMessage,
            updated_tag_id_list: selectedTagIds,
            is_admin: role?.toLowerCase() === "admin",
            system_prompt: isSystemPromptChanged ? systemPromptData : {},
            user_email_id: formData?.created_by,
            agentic_application_id_to_modify: currentAgentData?.agentic_application_id,
            tools_id_to_add: isAgentBased ? addedAgentsId : addedToolsId,
            tools_id_to_remove: isAgentBased ? removedAgentsId : removedToolsId,
            // Tool versions - pass selected version for each tool
            ...(Object.keys(toolVersions).length > 0 && { tools_with_versions: buildToolsWithVersions(toolVersions) }),
            // Knowledge base IDs to add/remove
            knowledgebase_ids_to_add: addedKnowledgeBaseIds,
            knowledgebase_ids_to_remove: removedKnowledgeBaseIds,
            // File context management prompt fields
            ...(fileContextPromptExists && {
              file_context_management_prompt: fileContextManagementPrompt,
              regenerate_file_context_prompt: regenerateFileContextPrompt,
            }),
            ...(selectedGuardrail && { guardrail_type: selectedGuardrail }),
          };

          // Compute db_connection_names diff for update
          const dbToAdd = selectedDbConnections.filter((name) => !initialDbConnections.includes(name));
          const dbToRemove = initialDbConnections.filter((name) => !selectedDbConnections.includes(name));
          if (dbToAdd.length > 0) payload.db_connection_names_to_add = dbToAdd;
          if (dbToRemove.length > 0) payload.db_connection_names_to_remove = dbToRemove;

          if (!isValidatorPatternHidden()) {
            payload.validation_criteria = filteredPatterns;
          }

          const res = await putData(APIs.UPDATE_AGENTS, payload);

          // Update additional_paths via AgentOS endpoint if changed
          if (hasPathsChanged()) {
            try {
              const mergedPaths = buildAdditionalPathsPayload();
              // List 2: PUT /agents/{agent_id}  →  POST /agents/{agent_id}/update
              await putData(`${APIs.AGENTOS_AGENTS}/${currentAgentData?.agentic_application_id}/update`, { additional_paths: mergedPaths });
            } catch (pathErr) {
              console.error("Failed to update additional paths:", pathErr);
              if (pathErr?.response?.status === 403) {
                addMessage(pathErr?.response?.data?.detail || "Permission denied. Only the creator or Admin can modify this agent.", "error");
              } else if (pathErr?.response?.status === 422) {
                const detail = pathErr?.response?.data?.detail;
                const msg = Array.isArray(detail) ? detail.map((d) => d.msg).join("; ") : detail;
                addMessage(`Validation error: ${msg}`, "error");
              } else {
                addMessage("Failed to update folder mounts", "error");
              }
            }
          }

          // Reset tracking arrays
          if (isAgentBased) {
            setAddedAgentsId([]);
            setRemovedAgentsId([]);
          } else {
            setAddedToolsId([]);
            setRemovedToolsId([]);
          }
          // Reset KB tracking arrays
          setAddedKnowledgeBaseIds([]);
          setRemovedKnowledgeBaseIds([]);

          // Refresh agents list in parent component
          fetchAgents?.();

          if (res.detail) {
            handleApiError(res);
            setLoading(false);
          } else {
            // ============ STAY IN UPDATE MODE AFTER SUCCESSFUL UPDATE ============
            if (agentId) {
              const success = await refreshAgentDataAndStayOpen(agentId, "updated");
              if (success) {
                return; // Stay in update mode with refreshed data
              }
            }

            // Fallback: Show success message
            if (res.message) {
              addMessage(res.message, "success");
            } else {
              addMessage("Updated successfully", "success");
            }
            setLoading(false);
          }
        }
      }
    } catch (err) {
      // Extract detailed error message from API response
      const errorMessage =
        err?.response?.data?.detail ||
        err?.response?.data?.message ||
        err?.message ||
        (isCreateMode ? "Failed to create agent" : "Failed to update agent");

      addMessage(errorMessage, "error");
    } finally {
      setLoading(false);
    }
  };

  // ============ Get Prompt Dropdown Config ============
  const getPromptDropdownConfig = () => {
    const configs = {
      [MULTI_AGENT]: {
        options: SystemPromptsMultiAgent,
        selected: systemPromptType,
        setSelected: setSystemPromptType,
      },
      [PLANNER_META_AGENT]: {
        options: SystemPromptsPlannerMetaAgent,
        selected: plannersystempromtType,
        setSelected: setPlannersystempromptType,
      },
      [REACT_CRITIC_AGENT]: {
        options: systemPromptReactCriticAgents,
        selected: reactCriticSystemPromptType,
        setSelected: setReactCriticSystemPromptType,
      },
      [PLANNER_EXECUTOR_AGENT]: {
        options: systemPromptPlannerExecutorAgents,
        selected: plannerExecutorSystemPromptType,
        setSelected: setPlannerExecutorSystemPromptType,
      },
    };

    return configs[agentType] || null;
  };

  const promptDropdownConfig = getPromptDropdownConfig();
  const showPromptDropdown = isUpdateMode && promptDropdownConfig;

  // ============ Get Header Info ============
  const getHeaderInfo = () => {
    const info = [];
    // Agent Type (Update Mode Only)
    if (isUpdateMode && agentType) {
      const matchedType = agentTypesDropdown.find((a) => a.value === agentType);
      info.push({
        label: "Agent Type",
        value: matchedType ? matchedType.label : agentType.replace(/_/g, " "),
      });
    }
    // Created By
    info.push({
      label: "Created By",
      value: isCreateMode ? userName : fullAgentData.created_by || "",
    });
    return info;
  };

  // ============ Render Footer ============
  const renderFooter = () => (
    <div className={styles.footerContainer}>
      {/* Left side: Access Control + Regenerate Toggles (hidden in readOnly/recycleBin mode) */}
      {!isReadOnly && (
        <div className={styles.footerTogglesContainer}>
          {/* Regenerate Toggles (Update Mode Only, not for Skill Agent) */}
          {isUpdateMode && !isAgentOSType && (
            <>

              <div className={styles.footerToggleItem}>
                <Toggle value={regenerateWelcomeMessage} onChange={() => setRegenerateWelcomeMessage((prev) => !prev)} />
                <span className={`label-desc ${styles.footerToggleLabel}`}>Regenerate Welcome Message</span>
              </div>
              <div className={styles.footerToggleItem}>
                <Toggle value={regenerateSystemPrompt} onChange={() => setRegenerateSystemPrompt((prev) => !prev)} />
                <span className={`label-desc ${styles.footerToggleLabel}`}>Regenerate System Prompt</span>
              </div>
              {fileContextPromptExists && (
                <div className={styles.footerToggleItem}>
                  <Toggle
                    value={regenerateFileContextPrompt}
                    onChange={() => setRegenerateFileContextPrompt((prev) => !prev)}
                  />
                  <span className={`label-desc ${styles.footerToggleLabel}`}>Regenerate File Context Prompt</span>
                </div>
              )}
            </>
          )}
        </div>
      )}

      {/* Action Buttons */}
      <div className={styles.footerActionsContainer}>
        {recycleBin ? (
          <>
            <IAFButton type="secondary" onClick={onDelete} aria-label="Delete">
              Delete
            </IAFButton>
            <IAFButton type="primary" onClick={onRestore} aria-label="Restore">
              Restore
            </IAFButton>
          </>
        ) : readOnlyProp ? (
          /* Read-only mode: only show Close button, no submit/update */
          <IAFButton type="secondary" onClick={handleClose} aria-label="Close">
            Close
          </IAFButton>
        ) : (
          <>
            <IAFButton type="secondary" onClick={handleClose} aria-label="Cancel">
              Cancel
            </IAFButton>
            {/* Delete Button - shown for all roles with delete permission in update mode */}
            {!isCreateMode && !recycleBin && !isReadOnly && canDeleteAgents && (
              <IAFButton
                type="primary"
                onClick={() => setShowDeleteConfirm(true)}
                aria-label="Delete this agent"
              >
                Delete
              </IAFButton>
            )}
            <IAFButton
              type="primary"
              onClick={handleSubmit}
              disabled={loading || (isCreateMode ? !formData.agent_name?.trim() : false) || !formData.model_name}
              aria-label={isCreateMode ? "Add Agent" : "Update Agent"}>
              {loading ? (isCreateMode ? "Adding..." : "Updating...") : isCreateMode ? "Add Agent" : "Update Agent"}
            </IAFButton>
          </>
        )}
      </div>
    </div>
  );

  // ============ Render ============
  return (
    <>
      {/* Main Agent Form Modal */}
      <FullModal
        isOpen={true}
        onClose={handleClose}
        title={isCreateMode ? "Add Agent" : currentAgentData?.agentic_application_name}
        headerInfo={getHeaderInfo()}
        footer={(isCreateMode || hasPermission("update_access.agents")) ? renderFooter() : undefined}
        loading={loading}>
        <form onSubmit={handleSubmit}>
          <div className="formContent">
            <div className={`form ${styles.compactForm}`}>

              {/* Skill Agent Identity Section (Update Mode) - Collapsible */}
              {isUpdateMode && isAgentOSType && (
                <div className={styles.collapsibleSection}>
                  <div
                    className={styles.collapsibleSectionHeader}
                    onClick={() => toggleSection('identity')}
                  >
                    <div className={styles.collapsibleSectionTitle}>
                      <span className={styles.collapsibleSectionIcon}>
                        <SVGIcons icon="fa-robot" width={16} height={16} />
                      </span>
                      Identity
                    </div>
                    <div className={styles.collapsibleSectionRight}>
                      {!expandedSections.identity && (
                        <span className={styles.collapsibleSectionPreview}>
                          {formData.agentic_application_name || "Agent Name"}
                        </span>
                      )}
                      <span className={`${styles.collapsibleChevron} ${expandedSections.identity ? styles.expanded : ''}`}>
                        <SVGIcons icon="chevron-down" width={16} height={16} />
                      </span>
                    </div>
                  </div>
                  <div className={`${styles.collapsibleSectionContent} ${expandedSections.identity ? styles.expanded : ''}`}>
                    <div className={styles.collapsibleSectionInner}>
                      <div className="gridTwoCol">
                        <div className="formGroup">
                          <label className="label-desc">
                            Agent Name <span className="required">*</span>
                          </label>
                          <input
                            type="text"
                            className="input"
                            placeholder="Enter Agent Name"
                            value={formData.agentic_application_name || ""}
                            onChange={(e) => setFormData((prev) => ({ ...prev, agentic_application_name: e.target.value }))}
                            disabled={isReadOnly}
                          />
                        </div>
                        <div className="formGroup">
                          <label className="label-desc">Agent Description</label>
                          <input
                            type="text"
                            className="input"
                            placeholder="e.g., Handles IT inventory and procurement queries"
                            value={formData.agentic_application_description || ""}
                            onChange={(e) => setFormData((prev) => ({ ...prev, agentic_application_description: e.target.value }))}
                            disabled={isReadOnly}
                          />
                        </div>
                      </div>
                    </div>
                  </div>
                </div>
              )}

              {/* Identity Section (Create Mode Only) - Collapsible */}
              {isCreateMode && (
                <div className={styles.collapsibleSection}>
                  <div
                    className={styles.collapsibleSectionHeader}
                    onClick={() => toggleSection('identity')}
                  >
                    <div className={styles.collapsibleSectionTitle}>
                      <span className={styles.collapsibleSectionIcon}>
                        <SVGIcons icon="fa-robot" width={16} height={16} />
                      </span>
                      Identity
                    </div>
                    <div className={styles.collapsibleSectionRight}>
                      {!expandedSections.identity && (
                        <span className={styles.collapsibleSectionPreview}>
                          Agent Name, Agent Type
                        </span>
                      )}
                      <span className={`${styles.collapsibleChevron} ${expandedSections.identity ? styles.expanded : ''}`}>
                        <SVGIcons icon="chevron-down" width={16} height={16} />
                      </span>
                    </div>
                  </div>
                  <div className={`${styles.collapsibleSectionContent} ${expandedSections.identity ? styles.expanded : ''}`}>
                    <div className={styles.collapsibleSectionInner}>
                      <div className="gridTwoCol">
                        <div className="formGroup">
                          <label htmlFor="agent_name" className="label-desc">
                            Agent Name <span className="required">*</span>
                          </label>
                          <input
                            type="text"
                            id="agent_name"
                            name="agent_name"
                            className="input"
                            placeholder="Enter Agent Name"
                            value={formData.agent_name}
                            onChange={handleChange}
                            required
                          />
                        </div>
                        <div className="formGroup">
                          <NewCommonDropdown
                            label="Agent Type"
                            required={true}
                            options={agentTypesDropdown.map((a) => a.label)}
                            selected={agentTypesDropdown.find((a) => a.value === formData.agent_type)?.label || ""}
                            onSelect={(label) => {
                              const found = agentTypesDropdown.find((a) => a.label === label);
                              if (found) {
                                const prevType = formData.agent_type;
                                const newType = found.value;
                                const wasMetaType = [META_AGENT, PLANNER_META_AGENT].includes(prevType);
                                const isNewMetaType = [META_AGENT, PLANNER_META_AGENT].includes(newType);
                                // Clear selected resources when switching between tool-based and agent-based types
                                if (wasMetaType !== isNewMetaType) {
                                  setSelectedResources([]);
                                  setToolVersions({});
                                  setSelectedDbConnections([]);
                                }
                                setFormData((prev) => ({ ...prev, agent_type: newType }));
                              }
                            }}
                            placeholder="Select Agent Type"
                          />
                        </div>
                      </div>

                      {/* Agent Description - shown for AgentOS types (maps to agent_description in API) */}
                      {isAgentOSType && (
                        <div className="formGroup" style={{ marginTop: "12px" }}>
                          <label htmlFor="agent_goal" className="label-desc">
                            Agent Description
                          </label>
                          <input
                            type="text"
                            id="agent_goal"
                            name="agent_goal"
                            className="input"
                            placeholder="e.g., Handles IT inventory and procurement queries"
                            value={formData.agent_goal}
                            onChange={handleChange}
                          />
                          <span className={styles.fieldHint}>
                            Short description of what this agent does
                          </span>
                        </div>
                      )}
                    </div>
                  </div>
                </div>
              )}

              {/* Skills Section (AgentOS — Create & Update) */}
              {isAgentOSType && (
                <div className={styles.collapsibleSection}>
                  <div
                    className={styles.collapsibleSectionHeader}
                    onClick={() => toggleSection('skills')}
                  >
                    <div className={styles.collapsibleSectionTitle}>
                      <span className={styles.collapsibleSectionIcon}>
                        <SVGIcons icon="sparkles" width={16} height={16} />
                      </span>
                      Skills
                      {skills.length > 0 && (
                        <span className={styles.collapsibleSectionBadge}>{skills.length}</span>
                      )}
                    </div>
                    <div className={styles.collapsibleSectionRight}>
                      {!isReadOnly && (
                        <div className={styles.collapsibleHeaderActions} onClick={(e) => e.stopPropagation()}>
                          <button
                            type="button"
                            onClick={addSkill}
                            className={styles.collapsibleHeaderBtn}
                            aria-label="Add skill"
                          >
                            +
                          </button>
                        </div>
                      )}
                      <span className={`${styles.collapsibleChevron} ${expandedSections.skills ? styles.expanded : ''}`}>
                        <SVGIcons icon="chevron-down" width={16} height={16} />
                      </span>
                    </div>
                  </div>
                  <div className={`${styles.collapsibleSectionContent} ${expandedSections.skills ? styles.expanded : ''}`}>
                    <div className={styles.collapsibleSectionInner}>
                      {/* Loading state for update mode skill fetching */}
                      {skillsLoading ? (
                        <div style={{ padding: "24px", textAlign: "center", color: "var(--text-secondary)" }}>
                          Loading skills...
                        </div>
                      ) : (
                        <>
                          {/* Skill Tabs */}
                          <div className={styles.skillTabs}>
                            {skills.map((skill, index) => (
                              <div
                                key={index}
                                className={`${styles.skillTab} ${activeSkillIndex === index ? styles.active : ""}`}
                                onClick={() => setActiveSkillIndex(index)}
                              >
                                <span>{skill.skill_name || `Skill ${index + 1}`}</span>
                                {skills.length > 1 && !isReadOnly && (
                                  <button
                                    type="button"
                                    className={styles.removeSkillBtn}
                                    onClick={(e) => {
                                      e.stopPropagation();
                                      removeSkill(index);
                                    }}
                                    aria-label="Remove skill"
                                  >
                                    ×
                                  </button>
                                )}
                              </div>
                            ))}
                          </div>

                          {/* Active Skill Editor — Structured Mode */}
                          {skills[activeSkillIndex] && (
                            <div className={styles.skillEditor}>

                              {/* Row 1: Skill Name (30%) + Description (70%) */}
                              <div className={styles.skillFormRow}>
                                <div className={`formGroup ${styles.skillFormField}`} style={{ flex: 3 }}>
                                  <label className="label-desc">
                                    Skill Name <span className="required">*</span>
                                  </label>
                                  <input
                                    type="text"
                                    className={`input ${skills[activeSkillIndex].skill_name && !/^[a-z][a-z0-9_]*$/.test(skills[activeSkillIndex].skill_name) ? styles.inputError : ""}`}
                                    placeholder="e.g., password_reset"
                                    value={skills[activeSkillIndex].skill_name}
                                    onChange={(e) => updateSkill(activeSkillIndex, "skill_name", e.target.value.toLowerCase().replace(/\s+/g, "_"))}
                                    disabled={isUpdateMode && originalSkillNames.includes(skills[activeSkillIndex].skill_name)}
                                    readOnly={isReadOnly}
                                  />
                                  <span className={styles.fieldHint}>
                                    snake_case only (e.g., leave_policy, it_helpdesk)
                                  </span>
                                </div>
                                <div className={`formGroup ${styles.skillFormField}`} style={{ flex: 7 }}>
                                  <label className="label-desc">
                                    Description <span className="required">*</span>
                                  </label>
                                  <input
                                    type="text"
                                    className="input"
                                    placeholder="Short description of what this skill does"
                                    value={skills[activeSkillIndex].description}
                                    onChange={(e) => updateSkill(activeSkillIndex, "description", e.target.value)}
                                    disabled={isReadOnly}
                                  />
                                  <span className={styles.fieldHint}>
                                    Concise one-liner shown in routing hints and skill summary
                                  </span>
                                </div>
                              </div>

                              {/* Keywords — Tag/Chip Input (Mandatory) */}
                              <div className="formGroup">
                                <label className="label-desc">
                                  Keywords <span className="required">*</span>
                                </label>
                                <div className={styles.keywordChips}>
                                  {(skills[activeSkillIndex].keywords || []).map((kw, kwIdx) => (
                                    <span key={kwIdx} className={styles.keywordChip}>
                                      {kw}
                                      {!isReadOnly && (
                                        <button
                                          type="button"
                                          className={styles.keywordChipRemove}
                                          onClick={() => {
                                            const updated = [...skills[activeSkillIndex].keywords];
                                            updated.splice(kwIdx, 1);
                                            updateSkill(activeSkillIndex, "keywords", updated);
                                          }}
                                          aria-label={`Remove keyword ${kw}`}
                                        >
                                          ×
                                        </button>
                                      )}
                                    </span>
                                  ))}
                                  {!isReadOnly && (
                                    <input
                                      type="text"
                                      className={styles.keywordInput}
                                      placeholder={skills[activeSkillIndex].keywords?.length > 0 ? "Add more..." : "Type keyword and press Enter"}
                                      onKeyDown={(e) => {
                                        if ((e.key === "Enter" || e.key === ",") && e.target.value.trim()) {
                                          e.preventDefault();
                                          const newKw = e.target.value.trim().replace(/,$/g, "");
                                          if (newKw && !skills[activeSkillIndex].keywords.includes(newKw)) {
                                            updateSkill(activeSkillIndex, "keywords", [...skills[activeSkillIndex].keywords, newKw]);
                                          }
                                          e.target.value = "";
                                        }
                                      }}
                                    />
                                  )}
                                </div>
                                <span className={styles.fieldHint}>
                                  Trigger words/phrases for routing queries to this skill. Press Enter or comma to add.
                                </span>
                              </div>

                              {/* ── Data Connectors (compact section) ── */}
                              {canViewDataConnectors && (
                                <div className={styles.compactSection}>
                                  <div className={styles.compactSectionHeader}>
                                    <div className={styles.compactSectionLeft}>
                                      <SVGIcons icon="settings" width={15} height={15} color="var(--app-primary-color)" />
                                      <span className={styles.compactSectionTitle}>Data Connectors</span>
                                      {(skills[activeSkillIndex].databases || []).length > 0 && (
                                        <span className={styles.compactSectionCount}>
                                          {skills[activeSkillIndex].databases.length}
                                        </span>
                                      )}
                                    </div>
                                    {!isReadOnly && (
                                      <button
                                        type="button"
                                        className={styles.compactSectionAddBtn}
                                        onClick={() => addDbConnectionToSkill(activeSkillIndex)}
                                        title="Add database connection"
                                      >
                                        <SVGIcons icon="plus" width={12} height={12} />
                                        <span>Add</span>
                                      </button>
                                    )}
                                  </div>

                                  {(skills[activeSkillIndex].databases || []).length === 0 ? (
                                    <div className={`${styles.dbEmptyState} ${styles.compactSectionBody}`}>
                                      <span>No connections attached — click <strong>Add</strong> to link a database.</span>
                                    </div>
                                  ) : (
                                    <div className={`${styles.dbCardsList} ${styles.compactSectionBody}`}>
                                      {(skills[activeSkillIndex].databases || []).map((db, dbIdx) => {
                                        const isDuplicate =
                                          db.connection_name &&
                                          skills[activeSkillIndex].databases.filter(
                                            (d) => d.connection_name === db.connection_name
                                          ).length > 1;
                                        const connOptions = (() => {
                                          const names = availableDbConnections.map((c) => c.connection_name || c.name);
                                          if (db.connection_name && !names.includes(db.connection_name)) {
                                            return [db.connection_name, ...names];
                                          }
                                          return names;
                                        })();
                                        return (
                                          <div
                                            key={dbIdx}
                                            className={`${styles.dbCard} ${isDuplicate ? styles.dbCardDuplicate : ""}`}
                                          >
                                            <div className={styles.dbCardConnectionField}>
                                              <NewCommonDropdown
                                                options={connOptions}
                                                selected={db.connection_name || ""}
                                                onSelect={(val) =>
                                                  updateDbConnectionInSkill(activeSkillIndex, dbIdx, "connection_name", val)
                                                }
                                                placeholder="Select connection..."
                                                showSearch={connOptions.length > 5}
                                                disabled={isReadOnly || loadingDbConnections}
                                                hideFooter
                                              />
                                            </div>

                                            <div className={styles.dbCardModeField}>
                                              <label className={styles.sqlModeRadio}>
                                                <input
                                                  type="radio"
                                                  name={`sql_mode_${activeSkillIndex}_${dbIdx}`}
                                                  value="read_only"
                                                  checked={db.sql_mode === "read_only"}
                                                  onChange={() =>
                                                    updateDbConnectionInSkill(activeSkillIndex, dbIdx, "sql_mode", "read_only")
                                                  }
                                                  disabled={isReadOnly}
                                                />
                                                <span>Read Only</span>
                                              </label>
                                              <label className={styles.sqlModeRadio}>
                                                <input
                                                  type="radio"
                                                  name={`sql_mode_${activeSkillIndex}_${dbIdx}`}
                                                  value="read_write"
                                                  checked={db.sql_mode === "read_write"}
                                                  onChange={() =>
                                                    updateDbConnectionInSkill(activeSkillIndex, dbIdx, "sql_mode", "read_write")
                                                  }
                                                  disabled={isReadOnly}
                                                />
                                                <span>Read Write</span>
                                              </label>
                                            </div>

                                            {!isReadOnly && (
                                              <button
                                                type="button"
                                                className={styles.dbCardDeleteBtn}
                                                onClick={() => removeDbConnectionFromSkill(activeSkillIndex, dbIdx)}
                                                aria-label="Remove connection"
                                                title="Remove connection"
                                              >
                                                <SVGIcons icon="trash" width={14} height={14} />
                                              </button>
                                            )}

                                            {isDuplicate && (
                                              <span className={styles.dbDuplicateWarning}>⚠ Duplicate</span>
                                            )}
                                          </div>
                                        );
                                      })}
                                    </div>
                                  )}
                                </div>
                              )}

                              {/* Row: Skill Details (33%) + Instructions (33%) + Examples (33%) */}
                              <div className={styles.skillFormRow}>
                                <div
                                  className={`${styles.skillFormField} ${isDraggingSkillFile && draggingFieldTarget === "details" ? styles.dropHighlight : ""}`}
                                  onDragEnter={handleSkillDragEnter("details")}
                                  onDragLeave={handleSkillDragLeave}
                                  onDragOver={handleSkillDragOver}
                                  onDrop={handleSkillFieldDrop("details")}
                                >
                                  <div className={styles.labelWithUpload}>
                                    <label className="label-desc">
                                      Skill Details <span className="required">*</span>
                                    </label>
                                    {!isReadOnly && (
                                      <label className={styles.uploadFileBtn} title="Upload .md file">
                                        <SVGIcons icon="upload" width={14} height={14} />
                                        <input
                                          type="file"
                                          accept=".md,.txt"
                                          style={{ display: "none" }}
                                          onClick={(e) => e.stopPropagation()}
                                          onChange={(e) => {
                                            if (e.target.files?.[0]) handleSkillFileUpload(e.target.files[0], "details");
                                            e.target.value = "";
                                          }}
                                        />
                                      </label>
                                    )}
                                  </div>
                                  <TextareaWithActions
                                    value={skills[activeSkillIndex].details}
                                    onChange={(e) => updateSkill(activeSkillIndex, "details", e.target.value)}
                                    placeholder={`# ${skills[activeSkillIndex].skill_name || "Skill Name"}\n\nDetailed knowledge the LLM reads when activated...`}
                                    rows={6}
                                    enableCopy={true}
                                    enableClear={!isReadOnly}
                                    fullWidth
                                    disabled={isReadOnly}
                                    readOnly={isReadOnly}
                                  />
                                </div>

                                <div
                                  className={`${styles.skillFormField} ${isDraggingSkillFile && draggingFieldTarget === "instructions_md_content" ? styles.dropHighlight : ""}`}
                                  onDragEnter={handleSkillDragEnter("instructions_md_content")}
                                  onDragLeave={handleSkillDragLeave}
                                  onDragOver={handleSkillDragOver}
                                  onDrop={handleSkillFieldDrop("instructions_md_content")}
                                >
                                  <div className={styles.labelWithUpload}>
                                    <label className="label-desc">Instructions <span className={styles.optionalTag}>(Optional)</span></label>
                                    {!isReadOnly && (
                                      <label className={styles.uploadFileBtn} title="Upload .md file">
                                        <SVGIcons icon="upload" width={14} height={14} />
                                        <input
                                          type="file"
                                          accept=".md,.txt"
                                          style={{ display: "none" }}
                                          onClick={(e) => e.stopPropagation()}
                                          onChange={(e) => {
                                            if (e.target.files?.[0]) handleSkillFileUpload(e.target.files[0], "instructions_md_content");
                                            e.target.value = "";
                                          }}
                                        />
                                      </label>
                                    )}
                                  </div>
                                  <TextareaWithActions
                                    value={skills[activeSkillIndex].instructions_md_content}
                                    onChange={(e) => updateSkill(activeSkillIndex, "instructions_md_content", e.target.value)}
                                    placeholder="Step-by-step guidance, edge case handling..."
                                    rows={6}
                                    enableCopy={true}
                                    enableClear={!isReadOnly}
                                    fullWidth
                                    disabled={isReadOnly}
                                    readOnly={isReadOnly}
                                  />
                                </div>

                                <div
                                  className={`${styles.skillFormField} ${isDraggingSkillFile && draggingFieldTarget === "examples_md_content" ? styles.dropHighlight : ""}`}
                                  onDragEnter={handleSkillDragEnter("examples_md_content")}
                                  onDragLeave={handleSkillDragLeave}
                                  onDragOver={handleSkillDragOver}
                                  onDrop={handleSkillFieldDrop("examples_md_content")}
                                >
                                  <div className={styles.labelWithUpload}>
                                    <label className="label-desc">Examples <span className={styles.optionalTag}>(Optional)</span></label>
                                    {!isReadOnly && (
                                      <label className={styles.uploadFileBtn} title="Upload .md file">
                                        <SVGIcons icon="upload" width={14} height={14} />
                                        <input
                                          type="file"
                                          accept=".md,.txt"
                                          style={{ display: "none" }}
                                          onClick={(e) => e.stopPropagation()}
                                          onChange={(e) => {
                                            if (e.target.files?.[0]) handleSkillFileUpload(e.target.files[0], "examples_md_content");
                                            e.target.value = "";
                                          }}
                                        />
                                      </label>
                                    )}
                                  </div>
                                  <TextareaWithActions
                                    value={skills[activeSkillIndex].examples_md_content}
                                    onChange={(e) => updateSkill(activeSkillIndex, "examples_md_content", e.target.value)}
                                    placeholder="Q: Example query&#10;A: Example response..."
                                    rows={6}
                                    enableCopy={true}
                                    enableClear={!isReadOnly}
                                    fullWidth
                                    disabled={isReadOnly}
                                    readOnly={isReadOnly}
                                  />
                                </div>
                              </div>

                              {/* ── Additional Files (compact section) ── */}
                              <div className={styles.compactSection}>
                                <div className={styles.compactSectionHeader}>
                                  <div className={styles.compactSectionLeft}>
                                    <SVGIcons icon="fileText" width={15} height={15} color="var(--app-primary-color)" />
                                    <span className={styles.compactSectionTitle}>Additional Files</span>
                                    {(skills[activeSkillIndex].additional_files || []).length > 0 && (
                                      <span className={styles.compactSectionCount}>
                                        {skills[activeSkillIndex].additional_files.length}
                                      </span>
                                    )}
                                  </div>
                                  {!isReadOnly && (
                                    <button
                                      type="button"
                                      className={styles.compactSectionAddBtn}
                                      onClick={() => addAdditionalFile(activeSkillIndex)}
                                      title="Add blank file entry"
                                    >
                                      <SVGIcons icon="plus" width={12} height={12} />
                                      <span>Add</span>
                                    </button>
                                  )}
                                </div>

                                <div className={`${styles.filesBody} ${styles.compactSectionBody}`}>
                                  {/* Drag-drop upload zone */}
                                  {!isReadOnly && (
                                    <div
                                      className={`${styles.additionalDropZone} ${isDraggingSkillFile && draggingFieldTarget === "additional_files" ? styles.dropHighlight : ""}`}
                                      onDragEnter={handleSkillDragEnter("additional_files")}
                                      onDragLeave={handleSkillDragLeave}
                                      onDragOver={handleSkillDragOver}
                                      onDrop={handleAdditionalFilesDrop}
                                      onClick={(e) => {
                                        if (e.target !== additionalFilesInputRef.current) {
                                          additionalFilesInputRef.current?.click();
                                        }
                                      }}
                                      role="button"
                                      tabIndex={0}
                                      aria-label="Upload additional files"
                                    >
                                      <SVGIcons icon="upload" width={16} height={16} color="var(--text-tertiary)" />
                                      <span>Drop .md or .py files here or <strong>click to upload</strong></span>
                                      <input
                                        ref={additionalFilesInputRef}
                                        type="file"
                                        accept=".md,.txt,.py"
                                        multiple
                                        style={{ display: "none" }}
                                        onClick={(e) => e.stopPropagation()}
                                        onChange={(e) => {
                                          if (e.target.files?.length > 0) {
                                            handleAdditionalFileUpload(Array.from(e.target.files));
                                          }
                                          e.target.value = "";
                                        }}
                                      />
                                    </div>
                                  )}

                                  {/* File cards list */}
                                  {(skills[activeSkillIndex].additional_files || []).length > 0 && (
                                    <div className={styles.fileCardsList}>
                                      {(skills[activeSkillIndex].additional_files || []).map((file, fileIdx) => {
                                        const cardKey = `${activeSkillIndex}-${fileIdx}`;
                                        const isExpanded = expandedFileCards.has(cardKey);
                                        return (
                                          <div key={fileIdx} className={styles.fileCard}>
                                            <div
                                              className={styles.fileCardHeader}
                                              onClick={() => {
                                                setExpandedFileCards((prev) => {
                                                  const next = new Set(prev);
                                                  if (next.has(cardKey)) next.delete(cardKey);
                                                  else next.add(cardKey);
                                                  return next;
                                                });
                                              }}
                                            >
                                              <div className={styles.fileCardInfo}>
                                                <span className={`${styles.fileCardChevron} ${isExpanded ? styles.expanded : ""}`}>
                                                  <SVGIcons icon="chevron-down" width={14} height={14} />
                                                </span>
                                                <SVGIcons icon="fileText" width={16} height={16} color="var(--app-primary-color)" />
                                                {isExpanded && !isReadOnly ? (
                                                  <input
                                                    type="text"
                                                    className={`input ${styles.fileCardNameInput}`}
                                                    placeholder="filename.md"
                                                    value={file.filename}
                                                    onClick={(e) => e.stopPropagation()}
                                                    onChange={(e) => updateAdditionalFile(activeSkillIndex, fileIdx, "filename", e.target.value)}
                                                  />
                                                ) : (
                                                  <span className={styles.fileCardName}>
                                                    {file.filename || "untitled.md"}
                                                  </span>
                                                )}
                                              </div>
                                              <div className={styles.fileCardActions}>
                                                <span className={styles.fileCardSize}>
                                                  {file.content ? `${(file.content.length / 1024).toFixed(1)} KB` : "empty"}
                                                </span>
                                                {!isReadOnly && (
                                                  <button
                                                    type="button"
                                                    className={styles.fileCardDeleteBtn}
                                                    onClick={(e) => {
                                                      e.stopPropagation();
                                                      removeAdditionalFile(activeSkillIndex, fileIdx);
                                                    }}
                                                    aria-label="Remove file"
                                                    title="Remove file"
                                                  >
                                                    <SVGIcons icon="trash" width={14} height={14} />
                                                  </button>
                                                )}
                                              </div>
                                            </div>
                                            {isExpanded && (
                                              <div className={styles.fileCardContent}>
                                                <TextareaWithActions
                                                  value={file.content}
                                                  onChange={(e) => updateAdditionalFile(activeSkillIndex, fileIdx, "content", e.target.value)}
                                                  placeholder="File content in markdown..."
                                                  rows={6}
                                                  enableCopy={true}
                                                  enableClear={!isReadOnly}
                                                  fullWidth
                                                  disabled={isReadOnly}
                                                  readOnly={isReadOnly}
                                                />
                                              </div>
                                            )}
                                          </div>
                                        );
                                      })}
                                    </div>
                                  )}
                                </div>
                              </div>

                              {/* ── Skill-Level Hooks (compact section) ── */}
                              <div className={styles.compactSection}>
                                <div
                                  className={styles.compactSectionHeader}
                                  onClick={() => toggleSkillConfig("hooks")}
                                  style={{ cursor: "pointer" }}
                                >
                                  <div className={styles.compactSectionLeft}>
                                    <SVGIcons icon="settings" width={15} height={15} color="var(--app-primary-color)" />
                                    <span className={styles.compactSectionTitle}>Lifecycle Hooks</span>
                                    {(() => {
                                      const h = skills[activeSkillIndex]?.hooks || {};
                                      const count = Object.values(h).flat().length;
                                      return count > 0 ? <span className={styles.compactSectionCount}>{count}</span> : null;
                                    })()}
                                  </div>
                                  <SVGIcons icon={skillConfigExpanded.hooks ? "chevron-up" : "chevron-down"} width={14} height={14} />
                                </div>
                                {skillConfigExpanded.hooks && (
                                  <div className={styles.compactSectionBody}>
                                    <span className={styles.fieldHint} style={{ marginBottom: 10, display: "block" }}>
                                      Skill-level hooks — run only for this skill. Written to SKILL.md frontmatter.
                                    </span>
                                    {HOOK_EVENTS.map((event) => {
                                      const entries = skills[activeSkillIndex]?.hooks?.[event] || [];
                                      return (
                                        <div key={event} className={styles.hookEventBlock}>
                                          <div className={styles.hookEventHeader}>
                                            <span className={styles.hookEventLabel}>{event}</span>
                                            {!isReadOnly && (
                                              <button type="button" className={styles.hookAddBtn} onClick={() => updateSkillHooks(activeSkillIndex, (prev) => ({
                                                ...prev, [event]: [...(prev[event] || []), { hook_id: "", command: "", matcher: "", block_on_nonzero: false, timeout_seconds: 10 }],
                                              }))} disabled={isReadOnly}>
                                                <SVGIcons icon="plus" width={12} height={12} /> Add
                                              </button>
                                            )}
                                          </div>
                                          {entries.map((entry, idx) => (
                                            <div key={idx} className={styles.hookEntryRow}>
                                              <div className={styles.hookEntryFields}>
                                                {/* Hook — repo dropdown or manual command */}
                                                <div className={styles.hookField} style={{
                                                  flex: "0 0 auto",
                                                }}>
                                                  {repoHooks.length > 0 ? (
                                                    <NewCommonDropdown
                                                      label="Hook:"
                                                      labelPosition="left"
                                                      width="100%"
                                                      placeholder="Select a hook"
                                                      options={[
                                                        ...repoHooks.map((h) => h.name),
                                                        "⌨ Enter command manually",
                                                      ]}
                                                      selected={
                                                        entry.hook_id
                                                          ? repoHooks.find((h) => h.hook_id === entry.hook_id)
                                                            ? repoHooks.find((h) => h.hook_id === entry.hook_id).name
                                                            : ""
                                                          : (entry._isManual || entry.command) ? "⌨ Enter command manually" : ""
                                                      }
                                                      onSelect={(label) => {
                                                        if (label === "⌨ Enter command manually") {
                                                          updateSkillHooks(activeSkillIndex, (prev) => {
                                                            const updated = [...(prev[event] || [])];
                                                            updated[idx] = { ...updated[idx], hook_id: "", _isManual: true };
                                                            return { ...prev, [event]: updated };
                                                          });
                                                        } else {
                                                          const selectedHook = repoHooks.find((h) => h.name === label);
                                                          const hookId = selectedHook?.hook_id || "";
                                                          if (hookId) {
                                                            updateSkillHooks(activeSkillIndex, (prev) => {
                                                              const updated = [...(prev[event] || [])];
                                                              updated[idx] = {
                                                                ...updated[idx],
                                                                hook_id: hookId,
                                                                command: "",
                                                                _isManual: false,
                                                              };
                                                              return { ...prev, [event]: updated };
                                                            });
                                                          }
                                                        }
                                                      }}
                                                      disabled={isReadOnly}
                                                      showSearch={repoHooks.length > 5}
                                                    />
                                                  ) : (
                                                    <>
                                                      <label className={styles.hookFieldLabel}>Hook:</label>
                                                      <input type="text" className="input" placeholder="python hooks/my_script.py"
                                                        value={entry.command || ""}
                                                        onChange={(e) => updateSkillHooks(activeSkillIndex, (prev) => {
                                                          const updated = [...(prev[event] || [])]; updated[idx] = { ...updated[idx], command: e.target.value };
                                                          return { ...prev, [event]: updated };
                                                        })} disabled={isReadOnly} />
                                                    </>
                                                  )}
                                                </div>
                                                {/* Manual command — only when user explicitly chose manual mode */}
                                                {repoHooks.length > 0 && !entry.hook_id && (entry._isManual || entry.command) && (
                                                  <div className={styles.hookField} style={{ minWidth: 150 }}>
                                                    <label className={styles.hookFieldLabel}>Command:</label>
                                                    <input type="text" className="input" placeholder="python hooks/my_script.py"
                                                      value={entry.command || ""}
                                                      onChange={(e) => updateSkillHooks(activeSkillIndex, (prev) => {
                                                        const updated = [...(prev[event] || [])]; updated[idx] = { ...updated[idx], command: e.target.value };
                                                        return { ...prev, [event]: updated };
                                                      })} disabled={isReadOnly} />
                                                  </div>
                                                )}
                                                {/* Applicable Tools — only for tool events */}
                                                {TOOL_EVENTS.includes(event) && (
                                                  <div className={styles.hookField}>
                                                    <label className={styles.hookFieldLabel}>Tools:</label>
                                                    <div className={styles.matcherChipList}>
                                                      {MATCHER_TOOL_OPTIONS.map((tool) => {
                                                        const selected = parseMatcherToSelection(entry.matcher);
                                                        const isActive = selected.includes(tool);
                                                        return (
                                                          <button
                                                            key={tool}
                                                            type="button"
                                                            className={`${styles.matcherChip} ${isActive ? styles.matcherChipActive : ""}`}
                                                            onClick={() => {
                                                              if (isReadOnly) return;
                                                              handleMatcherSelectionChange(
                                                                isActive ? selected.filter((t) => t !== tool) : [...selected, tool],
                                                                entry.matcher,
                                                                (val) => {
                                                                  updateSkillHooks(activeSkillIndex, (prev) => {
                                                                    const updated = [...(prev[event] || [])]; updated[idx] = { ...updated[idx], matcher: val };
                                                                    return { ...prev, [event]: updated };
                                                                  });
                                                                }
                                                              );
                                                            }}
                                                            disabled={isReadOnly}
                                                          >
                                                            {tool}
                                                          </button>
                                                        );
                                                      })}
                                                    </div>
                                                  </div>
                                                )}
                                                <div className={styles.hookField} style={{ minWidth: 140 }}>
                                                  <label className={styles.hookFieldLabel}>Timeout(s):</label>
                                                  <input type="text" inputMode="numeric" className="input"
                                                    style={{ width: 60 }}
                                                    value={entry.timeout_seconds}
                                                    onKeyDown={(e) => { if (!/[0-9]/.test(e.key) && !["Backspace", "Delete", "ArrowLeft", "ArrowRight", "Tab"].includes(e.key)) e.preventDefault(); }}
                                                    onChange={(e) => {
                                                      const v = e.target.value.replace(/[^0-9]/g, ""); updateSkillHooks(activeSkillIndex, (prev) => {
                                                        const updated = [...(prev[event] || [])]; updated[idx] = { ...updated[idx], timeout_seconds: v === "" ? "" : parseInt(v, 10) };
                                                        return { ...prev, [event]: updated };
                                                      });
                                                    }}
                                                    onBlur={(e) => {
                                                      if (!e.target.value || parseInt(e.target.value, 10) < 1) updateSkillHooks(activeSkillIndex, (prev) => {
                                                        const updated = [...(prev[event] || [])]; updated[idx] = { ...updated[idx], timeout_seconds: 10 };
                                                        return { ...prev, [event]: updated };
                                                      });
                                                    }}
                                                    disabled={isReadOnly} />
                                                </div>
                                                <div className={styles.hookField} style={{ maxWidth: 100 }}>
                                                  <label className={styles.hookFieldLabel}>Block?</label>
                                                  <label className={styles.hookToggle}>
                                                    <input type="checkbox" checked={entry.block_on_nonzero}
                                                      onChange={(e) => updateSkillHooks(activeSkillIndex, (prev) => {
                                                        const updated = [...(prev[event] || [])]; updated[idx] = { ...updated[idx], block_on_nonzero: e.target.checked };
                                                        return { ...prev, [event]: updated };
                                                      })} disabled={isReadOnly} />
                                                    <span>{entry.block_on_nonzero ? "Yes" : "No"}</span>
                                                  </label>
                                                </div>
                                              </div>
                                              {!isReadOnly && (
                                                <button type="button" className={styles.hookRemoveBtn} title="Remove"
                                                  onClick={() => updateSkillHooks(activeSkillIndex, (prev) => {
                                                    const updated = [...(prev[event] || [])]; updated.splice(idx, 1);
                                                    const newHooks = { ...prev, [event]: updated };
                                                    if (updated.length === 0) delete newHooks[event];
                                                    return newHooks;
                                                  })}>
                                                  <SVGIcons icon="close" width={14} height={14} />
                                                </button>
                                              )}
                                            </div>
                                          ))}
                                        </div>
                                      );
                                    })}
                                  </div>
                                )}
                              </div>

                            </div>
                          )}
                        </>
                      )}
                    </div>
                  </div>
                </div>
              )}

              {/* Enterprise Context Section (AgentOS — Read-Only) */}
              {isAgentOSType && (
                <div className={styles.collapsibleSection}>
                  <div
                    className={styles.collapsibleSectionHeader}
                    onClick={() => toggleSection('enterpriseContext')}
                  >
                    <div className={styles.collapsibleSectionTitle}>
                      <span className={styles.collapsibleSectionIcon}>
                        <SVGIcons icon="settings" width={16} height={16} />
                      </span>
                      Enterprise Context
                      {enterpriseContextEnabled && (
                        <span className={styles.collapsibleSectionBadge} title="Context enabled">
                          <SVGIcons icon="check" width={12} height={12} />
                        </span>
                      )}
                    </div>
                    <div className={styles.collapsibleSectionRight}>
                      {!expandedSections.enterpriseContext && (
                        <span className={styles.collapsibleSectionPreview}>
                          {[
                            enterpriseContext ? "Context" : "",
                            entityGuide ? "Entity Guide" : "",
                            skillContexts.length > 0 ? `${skillContexts.length} skill context${skillContexts.length > 1 ? "s" : ""}` : "",
                            policies.length > 0 ? `${policies.length} polic${policies.length > 1 ? "ies" : "y"}` : "",
                          ].filter(Boolean).join(", ") || "Not configured"}
                        </span>
                      )}
                      <span className={`${styles.collapsibleChevron} ${expandedSections.enterpriseContext ? styles.expanded : ''}`}>
                        <SVGIcons icon="chevron-down" width={16} height={16} />
                      </span>
                    </div>
                  </div>
                  <div className={`${styles.collapsibleSectionContent} ${expandedSections.enterpriseContext ? styles.expanded : ''}`}>
                    <div className={styles.collapsibleSectionInner}>

                      {/* Read-only notice */}
                      <div className={styles.autoGenBanner}>
                        <SVGIcons icon="info" width={14} height={14} />
                        <span>Enterprise context is managed by the backend and is <strong>read-only</strong>.</span>
                      </div>

                      {/* Context Sub-Tabs */}
                      <div className={styles.contextTabs}>
                        {[
                          { key: "context", label: "Context", icon: "fileText" },
                          { key: "entity_guide", label: "Entity Guide", icon: "fileText" },
                          { key: "skill_contexts", label: "Skill Contexts", icon: "sparkles", count: skillContexts.length },
                          { key: "policies", label: "Policies", icon: "clipboard-check", count: policies.length },
                          { key: "settings", label: "Settings", icon: "settings" },
                        ].map((tab) => (
                          <button
                            key={tab.key}
                            type="button"
                            className={`${styles.contextTab} ${activeContextTab === tab.key ? styles.active : ""}`}
                            onClick={() => setActiveContextTab(tab.key)}
                          >
                            <SVGIcons icon={tab.icon} width={14} height={14} />
                            <span>{tab.label}</span>
                            {tab.count > 0 && <span className={styles.contextTabBadge}>{tab.count}</span>}
                          </button>
                        ))}
                      </div>

                      {/* ---- Tab: Context (Enterprise_Context.md) ---- */}
                      {activeContextTab === "context" && (
                        <div className={styles.contextTabPanel}>
                          <div className="formGroup">
                            <label className="label-desc">
                              Enterprise Context Markdown
                              {masterContextMeta?.size_bytes > 0 && (
                                <span className={styles.fileCardSize} style={{ marginLeft: 8 }}>
                                  {formatBytes(masterContextMeta.size_bytes)}
                                </span>
                              )}
                            </label>
                            <TextareaWithActions
                              value={enterpriseContext}
                              placeholder="No enterprise context configured"
                              rows={12}
                              enableCopy={true}
                              enableClear={false}
                              fullWidth
                              disabled
                              readOnly
                            />
                          </div>
                        </div>
                      )}

                      {/* ---- Tab: Entity Guide ---- */}
                      {activeContextTab === "entity_guide" && (
                        <div className={styles.contextTabPanel}>
                          <div className="formGroup">
                            <label className="label-desc">
                              Entity Guide
                              {entityGuideMeta?.size_bytes > 0 && (
                                <span className={styles.fileCardSize} style={{ marginLeft: 8 }}>
                                  {formatBytes(entityGuideMeta.size_bytes)}
                                </span>
                              )}
                            </label>
                            {entityGuide ? (
                              <TextareaWithActions
                                value={entityGuide}
                                placeholder=""
                                rows={8}
                                enableCopy={true}
                                enableClear={false}
                                fullWidth
                                disabled
                                readOnly
                              />
                            ) : (
                              <div className={styles.contextEmptyState}>
                                <SVGIcons icon="fileText" width={24} height={24} color="var(--text-tertiary)" />
                                <span>No entity guide configured</span>
                              </div>
                            )}
                          </div>
                        </div>
                      )}

                      {/* ---- Tab: Skill Contexts ---- */}
                      {activeContextTab === "skill_contexts" && (
                        <div className={styles.contextTabPanel}>
                          <div className={styles.contextTabPanelHeader}>
                            <div>
                              <span className={styles.contextTabPanelTitle}>Per-Skill Context Files</span>
                              <span className={styles.fieldHint}>
                                Additional context injected only into a specific skill's prompt
                              </span>
                            </div>
                          </div>

                          {skillContexts.length === 0 ? (
                            <div className={styles.contextEmptyState}>
                              <SVGIcons icon="fileText" width={24} height={24} color="var(--text-tertiary)" />
                              <span>No skill-specific contexts configured</span>
                            </div>
                          ) : (
                            <div className={styles.contextCardsList}>
                              {skillContexts.map((sc, idx) => (
                                <div key={idx} className={styles.contextCard}>
                                  <div className={styles.contextCardHeader}>
                                    <div className={styles.contextCardLabel}>
                                      <SVGIcons icon="sparkles" width={14} height={14} color="var(--app-primary-color)" />
                                      <span className={styles.contextCardName}>{sc.skill_name || "unnamed"}</span>
                                      {sc.size_bytes > 0 && (
                                        <span className={styles.fileCardSize}>{formatBytes(sc.size_bytes)}</span>
                                      )}
                                    </div>
                                  </div>
                                  <div className={styles.contextCardBody}>
                                    <TextareaWithActions
                                      value={sc.content}
                                      placeholder="No content"
                                      rows={4}
                                      enableCopy={true}
                                      enableClear={false}
                                      fullWidth
                                      disabled
                                      readOnly
                                    />
                                  </div>
                                </div>
                              ))}
                            </div>
                          )}
                        </div>
                      )}

                      {/* ---- Tab: Policies ---- */}
                      {activeContextTab === "policies" && (
                        <div className={styles.contextTabPanel}>
                          <div className={styles.contextTabPanelHeader}>
                            <div>
                              <span className={styles.contextTabPanelTitle}>Policy Documents</span>
                              <span className={styles.fieldHint}>
                                Business rules and policy documents applied across skills
                              </span>
                            </div>
                          </div>

                          {policies.length === 0 ? (
                            <div className={styles.contextEmptyState}>
                              <SVGIcons icon="clipboard-check" width={24} height={24} color="var(--text-tertiary)" />
                              <span>No policies configured</span>
                            </div>
                          ) : (
                            <div className={styles.contextCardsList}>
                              {policies.map((p, idx) => (
                                <div key={idx} className={styles.contextCard}>
                                  <div className={styles.contextCardHeader}>
                                    <div className={styles.contextCardLabel}>
                                      <SVGIcons icon="clipboard-check" width={14} height={14} color="var(--app-primary-color)" />
                                      <span className={styles.contextCardName}>{p.name || "unnamed"}</span>
                                      {p.size_bytes > 0 && (
                                        <span className={styles.fileCardSize}>{formatBytes(p.size_bytes)}</span>
                                      )}
                                    </div>
                                  </div>
                                  <div className={styles.contextCardBody}>
                                    <TextareaWithActions
                                      value={p.content}
                                      placeholder="No content"
                                      rows={4}
                                      enableCopy={true}
                                      enableClear={false}
                                      fullWidth
                                      disabled
                                      readOnly
                                    />
                                  </div>
                                </div>
                              ))}
                            </div>
                          )}
                        </div>
                      )}

                      {/* ---- Tab: Settings ---- */}
                      {activeContextTab === "settings" && (
                        <div className={styles.contextTabPanel}>
                          <div className="formGroup">
                            <label className="label-desc">Default Skill</label>
                            <input
                              type="text"
                              className="input"
                              value={defaultSkill}
                              disabled
                              readOnly
                            />
                            <span className={styles.fieldHint}>
                              Fallback skill used when no specific skill matches the user's query
                            </span>
                          </div>
                        </div>
                      )}

                    </div>
                  </div>
                </div>
              )}

              {/* ============ Lifecycle Hooks Section (Skill Agent Only) ============ */}
              {isAgentOSType && (
                <div className={styles.collapsibleSection}>
                  <div
                    className={styles.collapsibleSectionHeader}
                    onClick={() => toggleSection("hooks")}
                  >
                    <div className={styles.collapsibleSectionTitle}>
                      <span className={styles.collapsibleSectionIcon}>
                        <SVGIcons icon="settings" width={16} height={16} />
                      </span>
                      Lifecycle Hooks
                      {Object.values(hooks).flat().length > 0 && (
                        <span className={styles.collapsibleSectionBadge}>
                          {Object.values(hooks).flat().length}
                        </span>
                      )}
                    </div>
                    <div className={styles.collapsibleSectionRight}>
                      <SVGIcons
                        icon={expandedSections.hooks ? "chevron-up" : "chevron-down"}
                        width={16}
                        height={16}
                      />
                    </div>
                  </div>
                  <div className={`${styles.collapsibleSectionContent} ${expandedSections.hooks ? styles.expanded : ""}`}>
                    <div className={styles.collapsibleSectionInner}>
                      <span className={styles.fieldHint} style={{ marginBottom: 12 }}>
                        Run custom scripts at lifecycle events (before/after tool calls, after responses, etc.)
                      </span>

                      {HOOK_EVENTS.map((event) => {
                        const entries = hooks[event] || [];
                        return (
                          <div key={event} className={styles.hookEventBlock}>
                            <div className={styles.hookEventHeader}>
                              <span className={styles.hookEventLabel}>{event}</span>
                              <button
                                type="button"
                                className={styles.hookAddBtn}
                                onClick={() => addHookEntry(event)}
                                disabled={isReadOnly}
                              >
                                <SVGIcons icon="plus" width={12} height={12} />
                                Add
                              </button>
                            </div>
                            {entries.map((entry, idx) => (
                              <div key={idx} className={styles.hookEntryRow}>
                                <div className={styles.hookEntryFields}>
                                  {/* Hook Source — repository dropdown or manual command */}
                                  <div className={styles.hookField} style={{
                                    flex: "0 0 auto",
                                  }}>
                                    {repoHooks.length > 0 ? (
                                      <NewCommonDropdown
                                        label="Hook:"
                                        labelPosition="left"
                                        width="100%"
                                        placeholder="Select a hook"
                                        options={[
                                          ...repoHooks.map((h) => h.name),
                                          "⌨ Enter command manually",
                                        ]}
                                        selected={
                                          entry.hook_id
                                            ? repoHooks.find((h) => h.hook_id === entry.hook_id)
                                              ? repoHooks.find((h) => h.hook_id === entry.hook_id).name
                                              : ""
                                            : (entry._isManual || entry.command) ? "⌨ Enter command manually" : ""
                                        }
                                        onSelect={(label) => {
                                          if (label === "⌨ Enter command manually") {
                                            setHooks((prev) => {
                                              const updated = [...(prev[event] || [])];
                                              updated[idx] = { ...updated[idx], hook_id: "", _isManual: true };
                                              return { ...prev, [event]: updated };
                                            });
                                          } else {
                                            const selectedHook = repoHooks.find((h) => h.name === label);
                                            const hookId = selectedHook?.hook_id || "";
                                            if (hookId) {
                                              selectRepoHook(event, idx, hookId);
                                              setHooks((prev) => {
                                                const updated = [...(prev[event] || [])];
                                                updated[idx] = { ...updated[idx], _isManual: false };
                                                return { ...prev, [event]: updated };
                                              });
                                            }
                                          }
                                        }}
                                        disabled={isReadOnly}
                                        showSearch={repoHooks.length > 5}
                                      />
                                    ) : (
                                      <>
                                        <label className={styles.hookFieldLabel}>Hook:</label>
                                        <input
                                          type="text"
                                          className="input"
                                          placeholder="python hooks/my_script.py"
                                          value={entry.command || ""}
                                          onChange={(e) => updateHookEntry(event, idx, "command", e.target.value)}
                                          disabled={isReadOnly}
                                        />
                                      </>
                                    )}
                                  </div>
                                  {/* Manual command — shown only when user explicitly chose manual mode */}
                                  {repoHooks.length > 0 && !entry.hook_id && (entry._isManual || entry.command) && (
                                    <div className={styles.hookField} style={{ minWidth: 180 }}>
                                      <label className={styles.hookFieldLabel}>Command:</label>
                                      <input
                                        type="text"
                                        className="input"
                                        placeholder="python hooks/my_script.py"
                                        value={entry.command || ""}
                                        onChange={(e) => updateHookEntry(event, idx, "command", e.target.value)}
                                        disabled={isReadOnly}
                                      />
                                    </div>
                                  )}
                                  {/* Applicable Tools — only for PreToolUse / PostToolUse */}
                                  {TOOL_EVENTS.includes(event) && (
                                    <div className={styles.hookField}>
                                      <label className={styles.hookFieldLabel}>Tools:</label>
                                      <div className={styles.matcherChipList}>
                                        {MATCHER_TOOL_OPTIONS.map((tool) => {
                                          const selected = parseMatcherToSelection(entry.matcher);
                                          const isActive = selected.includes(tool);
                                          return (
                                            <button
                                              key={tool}
                                              type="button"
                                              className={`${styles.matcherChip} ${isActive ? styles.matcherChipActive : ""}`}
                                              onClick={() => {
                                                if (isReadOnly) return;
                                                handleMatcherSelectionChange(
                                                  isActive ? selected.filter((t) => t !== tool) : [...selected, tool],
                                                  entry.matcher,
                                                  (val) => updateHookEntry(event, idx, "matcher", val)
                                                );
                                              }}
                                              disabled={isReadOnly}
                                            >
                                              {tool}
                                            </button>
                                          );
                                        })}
                                      </div>
                                    </div>
                                  )}
                                  <div className={styles.hookField} style={{ minWidth: 140 }}>
                                    <label className={styles.hookFieldLabel}>Timeout(s):</label>
                                    <input
                                      type="text"
                                      inputMode="numeric"
                                      className="input"
                                      style={{ width: 60 }}
                                      value={entry.timeout_seconds}
                                      onKeyDown={(e) => { if (!/[0-9]/.test(e.key) && !["Backspace", "Delete", "ArrowLeft", "ArrowRight", "Tab"].includes(e.key)) e.preventDefault(); }}
                                      onChange={(e) => { const v = e.target.value.replace(/[^0-9]/g, ""); updateHookEntry(event, idx, "timeout_seconds", v === "" ? "" : parseInt(v, 10)); }}
                                      onBlur={(e) => { if (!e.target.value || parseInt(e.target.value, 10) < 1) updateHookEntry(event, idx, "timeout_seconds", 10); }}
                                      disabled={isReadOnly}
                                    />
                                  </div>
                                  <div className={styles.hookField} style={{ maxWidth: 100 }}>
                                    <label className={styles.hookFieldLabel}>Block?</label>
                                    <label className={styles.hookToggle}>
                                      <input
                                        type="checkbox"
                                        checked={entry.block_on_nonzero}
                                        onChange={(e) => updateHookEntry(event, idx, "block_on_nonzero", e.target.checked)}
                                        disabled={isReadOnly}
                                      />
                                      <span>{entry.block_on_nonzero ? "Yes" : "No"}</span>
                                    </label>
                                  </div>
                                </div>
                                {!isReadOnly && (
                                  <button
                                    type="button"
                                    className={styles.hookRemoveBtn}
                                    onClick={() => removeHookEntry(event, idx)}
                                    title="Remove hook"
                                  >
                                    <SVGIcons icon="close" width={14} height={14} />
                                  </button>
                                )}
                              </div>
                            ))}
                          </div>
                        );
                      })}
                    </div>
                  </div>
                </div>
              )}

              {/* Tools & Components Section - Collapsible (Hidden for Skill Agent) */}
              {!isSkillAgentType && (hasAnyResourcePermission || (isUpdateMode && combinedResources.length > 0) || (canViewDataConnectors && !isMetaAgentType)) && (
                <div className={styles.collapsibleSection}>
                  <div
                    className={styles.collapsibleSectionHeader}
                    onClick={() => toggleSection('resources')}
                  >
                    <div className={styles.collapsibleSectionTitle}>
                      <span className={styles.collapsibleSectionIcon}>
                        <SVGIcons icon="wrench" width={16} height={16} />
                      </span>
                      Resources
                      {combinedResources.length > 0 && (
                        <span className={styles.collapsibleSectionBadge}>{combinedResources.length}</span>
                      )}
                    </div>
                    <div className={styles.collapsibleSectionRight}>
                      <div className={styles.collapsibleHeaderActions} onClick={(e) => e.stopPropagation()}>
                        {!isReadOnly && hasAnyResourcePermission && (
                          <button
                            type="button"
                            onClick={() => setShowResourcesSlider(true)}
                            className={styles.collapsibleHeaderBtn}
                            aria-label="Add resources"
                          >
                            +
                          </button>
                        )}
                      </div>
                      <span className={`${styles.collapsibleChevron} ${expandedSections.resources ? styles.expanded : ''}`}>
                        <SVGIcons icon="chevron-down" width={16} height={16} />
                      </span>
                    </div>
                  </div>
                  <div className={`${styles.collapsibleSectionContent} ${expandedSections.resources ? styles.expanded : ''}`}>
                    <div className={styles.collapsibleSectionInner}>
                      {selectedToolsLoading && isUpdateMode ? (
                        <Loader />
                      ) : combinedResources.length === 0 ? (
                        <div className={styles.emptyState}>
                          <p className={styles.emptyStateText}>
                            {hasAnyResourcePermission ? (
                              <>No resources added yet. Click{' '}
                                <button
                                  type="button"
                                  onClick={() => setShowResourcesSlider(true)}
                                  className={styles.inlineAddBtn}
                                  aria-label="Add resources"
                                >
                                  +
                                </button>
                                {' '}to attach tools, servers, or agents.
                              </>
                            ) : (
                              "No resources attached to this agent."
                            )}
                          </p>
                        </div>
                      ) : (
                        <ResourceAccordion
                          selectedResources={combinedResources}
                          onRemoveResource={(isReadOnly || !hasAnyResourcePermission) ? undefined : handleRemoveResource}
                          onResourceClick={handleResourceClick}
                          onClearAll={(isReadOnly || !hasAnyResourcePermission) ? undefined : handleClearAll}
                          disabled={isReadOnly || !hasAnyResourcePermission}
                          toolVersions={toolVersions}
                          resourcePermissions={{
                            tools: canViewTools,
                            servers: canViewServers,
                            agents: canViewAgents,
                            knowledgebases: canViewKnowledgeBases,
                            databases: canViewDataConnectors,
                          }}
                        />
                      )}
                    </div>
                  </div>
                </div>
              )}

              {/* Additional Folder Mounts — All Agent Types */}
              {/* Section 1: Additional Folder Paths — all users, relative paths */}
              <div className={styles.collapsibleSection}>
                <div
                  className={styles.collapsibleSectionHeader}
                  onClick={() => toggleSection("additionalPaths")}
                >
                  <div className={styles.collapsibleSectionTitle}>
                    <span className={styles.collapsibleSectionIcon}>
                      <SVGIcons icon="folder" width={16} height={16} />
                    </span>
                    Additional Folder Paths
                    {additionalPaths.length > 0 && (
                      <span className={styles.collapsibleSectionBadge}>{additionalPaths.length}</span>
                    )}
                  </div>
                  <div className={styles.collapsibleSectionRight}>
                    {!expandedSections.additionalPaths && additionalPaths.length > 0 && (
                      <span className={styles.collapsibleSectionPreview}>
                        {additionalPaths.filter((ap) => ap.path.trim()).map((ap) => ap.path).join(", ")}
                      </span>
                    )}
                    <span className={`${styles.collapsibleChevron} ${expandedSections.additionalPaths ? styles.expanded : ""}`}>
                      <SVGIcons icon="chevron-down" width={16} height={16} />
                    </span>
                  </div>
                </div>
                <div className={`${styles.collapsibleSectionContent} ${expandedSections.additionalPaths ? styles.expanded : ""}`}>
                  <div className={styles.collapsibleSectionInner}>
                    <p className={styles.additionalPathsHint}>
                      Relative paths resolved from your department root.
                      The agent accesses these via <code>/folder_name/</code> in the shell.
                      Paths cannot contain <code>..</code>
                    </p>

                    {additionalPaths.map((ap, index) => {
                      const pathError = validatePathEntry(ap.path);
                      const allEntries = [...additionalPaths, ...absolutePaths];
                      const isDuplicate = allEntries.some(
                        (other, otherIdx) =>
                          otherIdx !== index &&
                          other.path.trim() &&
                          other.path.trim().split("/").pop() === ap.path.trim().split("/").pop() &&
                          ap.path.trim() !== ""
                      );
                      return (
                        <div key={index} className={styles.additionalPathRow}>
                          <div className={styles.additionalPathInputGroup}>
                            <input
                              type="text"
                              placeholder="e.g. company_policies"
                              value={ap.path}
                              onChange={(e) => updatePath(index, "path", e.target.value, "relative")}
                              className={`${styles.additionalPathInput} ${pathError || isDuplicate ? styles.additionalPathInputError : ""}`}
                              disabled={isReadOnly}
                              aria-label={`Folder path ${index + 1}`}
                            />
                            {(pathError || isDuplicate) && (
                              <span className={styles.additionalPathErrorText}>
                                {pathError || "Duplicate mount name detected"}
                              </span>
                            )}
                          </div>
                          <select
                            value={ap.permission}
                            onChange={(e) => updatePath(index, "permission", e.target.value, "relative")}
                            className={styles.additionalPathPermission}
                            disabled={isReadOnly}
                            aria-label={`Permission for folder path ${index + 1}`}
                          >
                            <option value="read">Read Only</option>
                            <option value="read-write">Read &amp; Write</option>
                          </select>
                          {!isReadOnly && (
                            <button
                              type="button"
                              onClick={() => removePath(index, "relative")}
                              className={styles.additionalPathRemoveBtn}
                              aria-label={`Remove folder path ${index + 1}`}
                            >
                              ✕
                            </button>
                          )}
                        </div>
                      );
                    })}

                    {!isReadOnly && (
                      <button
                        type="button"
                        onClick={() => addPath("relative")}
                        className={styles.additionalPathAddBtn}
                      >
                        + Add Folder Path
                      </button>
                    )}
                  </div>
                </div>
              </div>

              {/* Section 2: Absolute Path Mounts — Admin/SuperAdmin only */}
              {isAdminUser && (
                <div className={styles.collapsibleSection}>
                  <div
                    className={styles.collapsibleSectionHeader}
                    onClick={() => toggleSection("absolutePaths")}
                  >
                    <div className={styles.collapsibleSectionTitle}>
                      <span className={styles.collapsibleSectionIcon}>
                        <SVGIcons icon="vault-lock" width={16} height={16} />
                      </span>
                      Absolute Path Mounts
                      <span className={styles.adminOnlyBadge}>Admin</span>
                      {absolutePaths.length > 0 && (
                        <span className={styles.collapsibleSectionBadge}>{absolutePaths.length}</span>
                      )}
                    </div>
                    <div className={styles.collapsibleSectionRight}>
                      {!expandedSections.absolutePaths && absolutePaths.length > 0 && (
                        <span className={styles.collapsibleSectionPreview}>
                          {absolutePaths.filter((ap) => ap.path.trim()).map((ap) => ap.path).join(", ")}
                        </span>
                      )}
                      <span className={`${styles.collapsibleChevron} ${expandedSections.absolutePaths ? styles.expanded : ""}`}>
                        <SVGIcons icon="chevron-down" width={16} height={16} />
                      </span>
                    </div>
                  </div>
                  <div className={`${styles.collapsibleSectionContent} ${expandedSections.absolutePaths ? styles.expanded : ""}`}>
                    <div className={styles.collapsibleSectionInner}>
                      <p className={styles.additionalPathsHint}>
                        Mount absolute filesystem paths into the agent&apos;s shell.
                        Allowed root directories are managed by the backend. Paths cannot contain <code>..</code>
                      </p>

                      {absolutePaths.map((ap, index) => {
                        const pathError = validatePathEntry(ap.path);
                        const allEntries = [...additionalPaths, ...absolutePaths];
                        const isDuplicate = allEntries.some(
                          (other, otherIdx) =>
                            (otherIdx !== additionalPaths.length + index) &&
                            other.path.trim() &&
                            other.path.trim().split("/").pop() === ap.path.trim().split("/").pop() &&
                            ap.path.trim() !== ""
                        );
                        return (
                          <div key={index} className={styles.additionalPathRow}>
                            <div className={styles.additionalPathInputGroup}>
                              <input
                                type="text"
                                placeholder="e.g. C:/shared/data/reports"
                                value={ap.path}
                                onChange={(e) => updatePath(index, "path", e.target.value, "absolute")}
                                className={`${styles.additionalPathInput} ${pathError || isDuplicate ? styles.additionalPathInputError : ""}`}
                                disabled={isReadOnly}
                                aria-label={`Absolute path ${index + 1}`}
                              />
                              {(pathError || isDuplicate) && (
                                <span className={styles.additionalPathErrorText}>
                                  {pathError || "Duplicate mount name detected"}
                                </span>
                              )}
                            </div>
                            <select
                              value={ap.permission}
                              onChange={(e) => updatePath(index, "permission", e.target.value, "absolute")}
                              className={styles.additionalPathPermission}
                              disabled={isReadOnly}
                              aria-label={`Permission for absolute path ${index + 1}`}
                            >
                              <option value="read">Read Only</option>
                              <option value="read-write">Read &amp; Write</option>
                            </select>
                            {!isReadOnly && (
                              <button
                                type="button"
                                onClick={() => removePath(index, "absolute")}
                                className={styles.additionalPathRemoveBtn}
                                aria-label={`Remove absolute path ${index + 1}`}
                              >
                                ✕
                              </button>
                            )}
                          </div>
                        );
                      })}
                      {!isReadOnly && (
                        <button
                          type="button"
                          onClick={() => addPath("absolute")}
                          className={styles.additionalPathAddBtn}
                        >
                          + Add Absolute Path
                        </button>
                      )}
                    </div>
                  </div>
                </div>
              )}

              {/* Purpose Section - Collapsible (CREATE MODE ONLY, Hidden for AgentOS types) */}
              {isCreateMode && !isAgentOSType && (
                <div className={styles.collapsibleSection}>
                  <div
                    className={styles.collapsibleSectionHeader}
                    onClick={() => toggleSection('purpose')}
                  >
                    <div className={styles.collapsibleSectionTitle}>
                      <span className={styles.collapsibleSectionIcon}>
                        <SVGIcons icon="brain" width={16} height={16} />
                      </span>
                      Purpose & Workflow
                    </div>
                    <div className={styles.collapsibleSectionRight}>
                      {!expandedSections.purpose && (
                        <span className={styles.collapsibleSectionPreview}>
                          Agent Goal, Workflow
                        </span>
                      )}
                      <span className={`${styles.collapsibleChevron} ${expandedSections.purpose ? styles.expanded : ''}`}>
                        <SVGIcons icon="chevron-down" width={16} height={16} />
                      </span>
                    </div>
                  </div>
                  <div className={`${styles.collapsibleSectionContent} ${expandedSections.purpose ? styles.expanded : ''}`}>
                    <div className={styles.collapsibleSectionInner}>
                      <div className="gridTwoCol">
                        <div className="formGroup">
                          <TextareaWithActions
                            name="agent_goal"
                            value={formData.agent_goal}
                            onChange={handleChange}
                            label="Agent Goal"
                            required={true}
                            placeholder="Describe What This Agent Aims To Achieve..."
                            rows={3}
                            disabled={isReadOnly}
                            readOnly={isReadOnly}
                            showCopy={!isReadOnly}
                            showExpand={!isReadOnly}
                            onZoomSave={handleAgentGoalZoomSave}
                          />
                        </div>
                        <div className="formGroup">
                          <TextareaWithActions
                            name="workflow_description"
                            value={formData.workflow_description}
                            onChange={handleChange}
                            label="Workflow Description"
                            required={true}
                            placeholder="Describe The Workflow Using Markdown..."
                            rows={3}
                            disabled={isReadOnly}
                            readOnly={isReadOnly}
                            showCopy={!isReadOnly}
                            showExpand={!isReadOnly}
                            onZoomSave={handleWorkflowZoomSave}
                          />
                        </div>
                      </div>
                    </div>
                  </div>
                </div>
              )}

              {/* Agent Details Section - UPDATE MODE ONLY (Agent Goal, Workflow, Welcome Message) - Hidden for Skill Agent */}
              {isUpdateMode && !isSkillAgentType && (
                <div className={styles.collapsibleSection}>
                  <div
                    className={styles.collapsibleSectionHeader}
                    onClick={() => toggleSection('agentDetails')}
                  >
                    <div className={styles.collapsibleSectionTitle}>
                      <span className={styles.collapsibleSectionIcon}>
                        <SVGIcons icon="brain" width={16} height={16} />
                      </span>
                      Agent Details
                    </div>
                    <div className={styles.collapsibleSectionRight}>
                      {!expandedSections.agentDetails && (
                        <span className={styles.collapsibleSectionPreview}>
                          Goal, Workflow, Welcome Message
                        </span>
                      )}
                      <span className={`${styles.collapsibleChevron} ${expandedSections.agentDetails ? styles.expanded : ''}`}>
                        <SVGIcons icon="chevron-down" width={16} height={16} />
                      </span>
                    </div>
                  </div>
                  <div className={`${styles.collapsibleSectionContent} ${expandedSections.agentDetails ? styles.expanded : ''}`}>
                    <div className={styles.collapsibleSectionInner}>
                      <div className="gridThreeCol">
                        <div className="formGroup">
                          <TextareaWithActions
                            name="agentic_application_description"
                            value={formData.agentic_application_description}
                            onChange={handleChange}
                            label="Agent Goal"
                            required={true}
                            placeholder="Describe What This Agent Aims To Achieve..."
                            rows={3}
                            disabled={isReadOnly}
                            readOnly={isReadOnly}
                            showCopy={!isReadOnly}
                            showExpand={!isReadOnly}
                            onZoomSave={handleAgentGoalZoomSave}
                          />
                        </div>
                        <div className="formGroup">
                          <TextareaWithActions
                            name="agentic_application_workflow_description"
                            value={formData.agentic_application_workflow_description}
                            onChange={handleChange}
                            label="Workflow Description"
                            required={true}
                            placeholder="Describe The Workflow Using Markdown..."
                            rows={3}
                            disabled={isReadOnly}
                            readOnly={isReadOnly}
                            showCopy={!isReadOnly}
                            showExpand={!isReadOnly}
                            onZoomSave={handleWorkflowZoomSave}
                          />
                        </div>
                        <div className="formGroup">
                          <TextareaWithActions
                            name="welcome_message"
                            value={welcomeMessage}
                            onChange={(e) => setWelcomeMessage(e.target.value)}
                            label="Welcome Message"
                            required={true}
                            placeholder="Enter the welcome message for this agent..."
                            rows={3}
                            disabled={isReadOnly}
                            readOnly={isReadOnly}
                            showCopy={!isReadOnly}
                            showExpand={!isReadOnly}
                            onZoomSave={(updatedContent) => setWelcomeMessage(updatedContent)}
                          />
                        </div>
                      </div>
                    </div>
                  </div>
                </div>
              )}

              {/* Prompts Section - UPDATE MODE ONLY (System Prompt, File Context Prompt) - Hidden for Skill Agent */}
              {isUpdateMode && !isSkillAgentType && (
                <div className={styles.collapsibleSection}>
                  <div
                    className={styles.collapsibleSectionHeader}
                    onClick={() => toggleSection('prompts')}
                  >
                    <div className={styles.collapsibleSectionTitle}>
                      <span className={styles.collapsibleSectionIcon}>
                        <SVGIcons icon="fileText" width={16} height={16} />
                      </span>
                      Prompts
                    </div>
                    <div className={styles.collapsibleSectionRight}>
                      {!expandedSections.prompts && (
                        <span className={styles.collapsibleSectionPreview}>
                          System Prompt{fileContextPromptExists ? ", File Context" : ""}
                        </span>
                      )}
                      <span className={`${styles.collapsibleChevron} ${expandedSections.prompts ? styles.expanded : ''}`}>
                        <SVGIcons icon="chevron-down" width={16} height={16} />
                      </span>
                    </div>
                  </div>
                  <div className={`${styles.collapsibleSectionContent} ${expandedSections.prompts ? styles.expanded : ''}`}>
                    <div className={styles.collapsibleSectionInner}>
                      <div className={fileContextPromptExists ? "gridTwoCol" : ""}>
                        <div className={styles.systemPromptWrapper}>
                          {showPromptDropdown ? (
                            <>
                              <NewCommonDropdown
                                label="System Prompt"
                                required={true}
                                options={promptDropdownConfig.options.map((p) => p.label)}
                                selected={promptDropdownConfig.options.find((p) => p.value === promptDropdownConfig.selected)?.label || ""}
                                onSelect={(label) => {
                                  const found = promptDropdownConfig.options.find((p) => p.label === label);
                                  if (found) promptDropdownConfig.setSelected(found.value);
                                }}
                                placeholder="Select Prompt Type"
                                dropdownWidth={100}
                                disabled={isReadOnly}
                              />
                              <TextareaWithActions
                                name="system_prompt"
                                value={selectedPromptData}
                                onChange={handlePromptChange}
                                placeholder="Instructions That Define How The Agent Should Respond And Behave..."
                                rows={3}
                                disabled={isReadOnly}
                                readOnly={isReadOnly}
                                showCopy={!isReadOnly}
                                showExpand={!isReadOnly}
                                onZoomSave={handleSystemPromptZoomSave}
                              />
                            </>
                          ) : (
                            <div className="formGroup">
                              <TextareaWithActions
                                name="system_prompt"
                                value={systemPromptData[Object.keys(systemPromptData)[0]] || ""}
                                onChange={handlePromptChange}
                                label="System Prompt"
                                required={true}
                                placeholder="Instructions That Define How The Agent Should Respond And Behave..."
                                rows={3}
                                disabled={isReadOnly}
                                readOnly={isReadOnly}
                                showCopy={!isReadOnly}
                                showExpand={!isReadOnly}
                                onZoomSave={handleSystemPromptZoomSave}
                              />
                            </div>
                          )}
                        </div>
                        {fileContextPromptExists && (
                          <div className="formGroup">
                            <TextareaWithActions
                              name="file_context_management_prompt"
                              value={fileContextManagementPrompt}
                              onChange={(e) => setFileContextManagementPrompt(e.target.value)}
                              label="File Context Management Prompt"
                              placeholder="File context management instructions for the agent..."
                              rows={3}
                              disabled={isReadOnly}
                              readOnly={isReadOnly}
                              showCopy={!isReadOnly}
                              showExpand={!isReadOnly}
                              onZoomSave={(updatedContent) => setFileContextManagementPrompt(updatedContent)}
                            />
                          </div>
                        )}
                      </div>
                    </div>
                  </div>
                </div>
              )}

              {/* Validation Patterns - Collapsible */}
              {!isValidatorPatternHidden() && (
                <div className={styles.collapsibleSection}>
                  <div
                    className={styles.collapsibleSectionHeader}
                    onClick={() => toggleSection('validators')}
                  >
                    <div className={styles.collapsibleSectionTitle}>
                      <span className={styles.collapsibleSectionIcon}>
                        <SVGIcons icon="clipboard-check" width={16} height={16} />
                      </span>
                      Validation Patterns
                      {validationPatterns.length > 0 && (
                        <span className={styles.collapsibleSectionBadge}>{validationPatterns.length}</span>
                      )}
                    </div>
                    <div className={styles.collapsibleSectionRight}>
                      <span className={`${styles.collapsibleChevron} ${expandedSections.validators ? styles.expanded : ''}`}>
                        <SVGIcons icon="chevron-down" width={16} height={16} />
                      </span>
                    </div>
                  </div>
                  <div className={`${styles.collapsibleSectionContent} ${expandedSections.validators ? styles.expanded : ''}`}>
                    <div className={styles.collapsibleSectionInner}>
                      <ValidatorPatternsGroup value={validationPatterns} onChange={setValidationPatterns} disabled={isReadOnly} />
                    </div>
                  </div>
                </div>
              )}

              {/* Configuration Section - Collapsible */}
              <div className={styles.collapsibleSection}>
                <div
                  className={styles.collapsibleSectionHeader}
                  onClick={() => toggleSection('config')}
                >
                  <div className={styles.collapsibleSectionTitle}>
                    <span className={styles.collapsibleSectionIcon}>
                      <SVGIcons icon="settings" width={16} height={16} />
                    </span>
                    Configuration
                  </div>
                  <div className={styles.collapsibleSectionRight}>
                    {!expandedSections.config && (
                      <span className={styles.collapsibleSectionPreview}>
                        Model, Tags{isUpdateMode ? ", Temperature" : ""}
                      </span>
                    )}
                    <span className={`${styles.collapsibleChevron} ${expandedSections.config ? styles.expanded : ''}`}>
                      <SVGIcons icon="chevron-down" width={16} height={16} />
                    </span>
                  </div>
                </div>
                <div className={`${styles.collapsibleSectionContent} ${expandedSections.config ? styles.expanded : ''}`}>
                  <div className={styles.collapsibleSectionInner}>
                    <div className={styles.configRow}>
                      {/* Model Selector - Inline Layout */}
                      <div className={styles.modelSelectorContainer}>
                        <div className={styles.modelSelectorWrapper}>
                          <span className={styles.modelSelectorLabel}>
                            Model <span className="required">*</span>
                          </span>
                          <div className={styles.modelDropdownWrapper}>
                            <NewCommonDropdown
                              options={models.map((m) => m.label)}
                              selected={formData.model_name}
                              onSelect={(value) => setFormData((prev) => ({ ...prev, model_name: value }))}
                              placeholder={modelsLoading ? "Loading models..." : "Select Model"}
                              disabled={isReadOnly || modelsLoading}
                              selectFirstByDefault={true}
                            />
                            <UnconfiguredModelCostWarning
                              selectedModel={formData.model_name}
                              unconfiguredCostModels={unconfiguredCostModels}
                            />
                          </div>
                        </div>
                      </div>
                      {/* Guardrail Selector */}
                      <div className={styles.modelSelectorContainer}>
                        <div className={styles.modelSelectorWrapper}>
                          <span className={styles.modelSelectorLabel}>
                            Guardrail
                          </span>
                          <div className={styles.modelDropdownWrapper}>
                            <NewCommonDropdown
                              options={guardrailTypes.map((g) => typeof g === "string" ? g : g.label || g.name || String(g))}
                              selected={guardrailTypes.find((g) => g.key === selectedGuardrail)?.label || selectedGuardrail}
                              onSelect={(label) => {
                                const found = guardrailTypes.find((g) => (g.label || g.name) === label);
                                setSelectedGuardrail(found ? found.key : label);
                              }}
                              placeholder={guardrailsLoading ? "Loading..." : "Select Guardrail"}
                              disabled={isReadOnly || guardrailsLoading}
                            />
                          </div>
                        </div>
                      </div>
                      {/* Tags Section */}
                      <TagSelector selectedTags={selectedTagsForSelector} onTagsChange={handleTagsChange} nonRemovableTags={nonRemovableTags} disabled={isReadOnly} />
                    </div>
                  </div>
                </div>
              </div>
            </div>
          </div>
        </form>
        {/* Tool/Server/Agent Detail Modal - inside FullModal to share its portal stacking context */}
        <ToolDetailModal
          isOpen={previewModalOpen}
          onClose={() => {
            setPreviewModalOpen(false);
            setPreviewResource(null);
          }}
          description={(() => {
            // When a version is selected for a tool, pass null so ToolDetailModal fetches version-specific description
            const resourceTab = getResourceTab(previewResource);
            if (resourceTab === "tools") {
              const resourceId = previewResource?.tool_id || previewResource?.id;
              const selectedVer = resourceId && toolVersions[resourceId];
              if (selectedVer) return null;
            }
            return previewResource?.agentic_application_description ||
              previewResource?.tool_description ||
              previewResource?.description;
          })()}
          endpoint={(() => {
            const resourceTab = getResourceTab(previewResource);
            if (resourceTab === "servers") {
              const mcpType = (previewResource?.mcp_type || "").toLowerCase();
              if (mcpType === "url") {
                return getServerEndpoint(previewResource);
              }
            }
            return undefined;
          })()}
          codeSnippet={(() => {
            const resourceTab = getResourceTab(previewResource);
            // When a version is selected, pass null so ToolDetailModal fetches version-specific code
            if (resourceTab === "tools") {
              const resourceId = previewResource?.tool_id || previewResource?.id;
              const selectedVer = resourceId && toolVersions[resourceId];
              if (selectedVer) return null;
            }
            if (previewResource?.code_snippet) return previewResource.code_snippet;
            if (resourceTab === "servers") {
              const mcpType = (previewResource?.mcp_type || "").toLowerCase();
              if (mcpType === "file") {
                return getServerCodePreview(previewResource);
              }
            }
            return null;
          })()}
          moduleName={(() => {
            const resourceTab = getResourceTab(previewResource);
            if (resourceTab === "servers") {
              const mcpType = (previewResource?.mcp_type || "").toLowerCase();
              if (mcpType === "module") {
                return getServerModuleName(previewResource);
              }
            }
            return undefined;
          })()}
          agenticApplicationWorkflowDescription={
            previewResource?.agentic_application_workflow_description ||
            previewResource?.workflow_description ||
            previewResource?.agenticApplicationWorkflowDescription ||
            previewResource?.server_workflow_description
          }
          systemPrompt={previewResource?.system_prompt || previewResource?.systemPrompt || previewResource?.server_system_prompt}
          isMappedTool={true}
          tool={previewResource}
          agentType={agentType}
          resourceTab={getResourceTab(previewResource)}
          selectedVersion={(() => {
            const resourceId = previewResource?.tool_id || previewResource?.id;
            return resourceId ? toolVersions[resourceId] : void 0;
          })()}
          hideModifyButton={true}
          useToolCardDescriptionStyle={true}
        />
      </FullModal>

      {/* Delete Confirmation Modal */}
      {showDeleteConfirm && (
        <ConfirmationModal
          message={`Are you sure you want to delete "${currentAgentData?.agentic_application_name || agentData?.agentic_application_name || "this agent"}"? This action cannot be undone.`}
          onConfirm={handleDeleteAgentFromModal}
          setShowConfirmation={setShowDeleteConfirm}
        />
      )}

      {/* Resources Slider */}
      {!isReadOnly && (
        <ResourceSlider
          isOpen={showResourcesSlider}
          onClose={() => setShowResourcesSlider(false)}
          selectedResources={selectedResources}
          onSaveSelection={handleSaveSelection}
          onClearAll={handleClearAll}
          initialTab="tools"
          agentType={isCreateMode ? formData.agent_type : agentType}
          toolVersions={toolVersions}
          onToolVersionChange={(toolId, version) => {
            setToolVersions((prev) => {
              const updated = { ...prev };
              if (typeof version === "undefined") {
                delete updated[toolId];
              } else {
                updated[toolId] = version;
              }
              return updated;
            });
          }}
          availableDbConnections={canViewDataConnectors ? availableDbConnections : []}
          selectedDbConnections={selectedDbConnections}
          onDbConnectionsChange={setSelectedDbConnections}
        />
      )}
    </>
  );
};

export default AgentForm;