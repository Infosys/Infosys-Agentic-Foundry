import { useEffect, useState, useRef, useCallback } from "react";
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
  systemPromptReactCriticAgents,
  systemPromptPlannerExecutorAgents,
  agentTypesDropdown,
} from "../../constant";
import useFetch from "../../Hooks/useAxios";
import Loader from "../commonComponents/Loader";
import { useMessage } from "../../Hooks/MessageContext";
import Cookies from "js-cookie";
import DeleteModal from "../commonComponents/DeleteModal";
import { sanitizeFormField, isValidEvent } from "../../utils/sanitization";
import { useAuth } from "../../context/AuthContext";
import { useErrorHandler } from "../../Hooks/useErrorHandler";
import ValidatorPatternsGroup from "../validators/ValidatorPatternsGroup";
import TagSelector from "../commonComponents/TagSelector/TagSelector";
import DepartmentSelector from "../commonComponents/DepartmentSelector/DepartmentSelector";
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
  const loggedInUserEmail = Cookies.get("email");
  const userName = Cookies.get("userName");
  const role = Cookies.get("role");

  // ============ Hooks ============
  const { fetchData, postData, putData } = useFetch();
  const { addMessage, setShowPopup } = useMessage();
  const { handleApiError, handleError } = useErrorHandler();
  const { logout } = useAuth();
  const { getKnowledgeBasesForAgent } = useKnowledgeBaseService();
  const { hasPermission } = usePermissions();

  // ============ Resource Permissions ============
  // Check if user can access any resource type (tools, servers, knowledge bases, agents)
  const canViewTools = hasPermission("read_access.tools", true);
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
  const [loading, setLoading] = useState(false);
  const [selectedToolsLoading, setSelectedToolsLoading] = useState(isUpdateMode);

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

  // ============ UI State ============
  const [showGuestModal, setShowGuestModal] = useState(false);
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
        resources: selectedResources.length > 0
      }));
    }
  }, [isUpdateMode, selectedResources.length]);

  // ============ Welcome Message State ============
  const [welcomeMessage, setWelcomeMessage] = useState("");

  // ============ File Context Management Prompt State (Update Mode) ============
  const [fileContextManagementPrompt, setFileContextManagementPrompt] = useState("");
  const [fileContextPromptExists, setFileContextPromptExists] = useState(false);

  // ============ Regenerate Toggles (Update Mode Only) ============
  const [regenerateWelcomeMessage, setRegenerateWelcomeMessage] = useState(false);
  const [regenerateSystemPrompt, setRegenerateSystemPrompt] = useState(false);
  const [regenerateFileContextPrompt, setRegenerateFileContextPrompt] = useState(false);

  // ============ Constants ============
  const COPY_FEEDBACK_MS = 2000;
  const DISABLED_OPACITY = 0.5;

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

  // ============ Helper: Get Knowledge Base IDs from Agent Data ============
  const getKnowledgeBaseIds = (agentObj) => {
    const kbIdsField = agentObj?.knowledgebase_ids || agentObj?.kb_ids;
    return parseJsonArrayField(kbIdsField, "knowledgebase_ids");
  };

  // Add new state for non-removable tags
  const [nonRemovableTags, setNonRemovableTags] = useState([]);
  const generalTagRef = useRef(null);

  // ============ Is Public & Shared Departments State ============
  const [isPublic, setIsPublic] = useState(false);
  const [sharedDepartments, setSharedDepartments] = useState([]);
  const [departmentsList, setDepartmentsList] = useState([]);
  const [departmentsLoading, setDepartmentsLoading] = useState(false);

  // Get logged-in user's department from cookies
  const loggedInDepartment = Cookies.get("department") || "";

  // ============ Fetch Departments List ============
  useEffect(() => {
    const fetchDepartments = async () => {
      setDepartmentsLoading(true);
      try {
        const response = await fetchData(APIs.GET_DEPARTMENTS_LIST);
        if (response && Array.isArray(response)) {
          setDepartmentsList(response.map((dept) => dept.department_name || dept.name || dept));
        } else if (response?.departments && Array.isArray(response.departments)) {
          setDepartmentsList(response.departments.map((dept) => dept.department_name || dept.name || dept));
        } else {
          setDepartmentsList([]);
        }
      } catch (err) {
        console.error("Failed to fetch departments", err);
        setDepartmentsList([]);
      } finally {
        setDepartmentsLoading(false);
      }
    };
    fetchDepartments();
  }, [fetchData]);

  // Modify the fetch models useEffect to also set default "general" tag
  useEffect(() => {
    if (hasLoadedModelsOnce.current) return;
    hasLoadedModelsOnce.current = true;

    (async () => {
      // Fetch models
      try {
        const data = await fetchData(APIs.GET_MODELS);
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

  // ============ Load Related Tools/Agents/KnowledgeBases ============
  const loadRelatedTools = async (type, selectedToolsId, selectedKbIds = []) => {
    try {
      const isToolBasedAgent = [REACT_AGENT, MULTI_AGENT, REACT_CRITIC_AGENT, PLANNER_EXECUTOR_AGENT, HYBRID_AGENT].includes(type);
      const isAgentBasedAgent = [META_AGENT, PLANNER_META_AGENT].includes(type);

      let allResources = [];

      if (isToolBasedAgent) {
        const response = await postData(APIs.GET_TOOLS_BY_LIST, selectedToolsId);
        // API returns { tools: [...], servers: [...] } separately
        const tools = Array.isArray(response?.tools) ? response.tools : [];
        const servers = Array.isArray(response?.servers) ? response.servers : [];

        const toolResources = tools.map((tool) => ({ ...tool, type: "tools" }));
        const serverResources = servers.map((server) => ({ ...server, type: "servers" }));
        allResources = [...allResources, ...toolResources, ...serverResources];

        // Fallback: if response is a flat array (old API format), infer type from mcp_config
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

      // Fetch knowledge bases using the service
      if (selectedKbIds && selectedKbIds.length > 0) {
        const kbResources = await getKnowledgeBasesForAgent(selectedKbIds);
        allResources = [...allResources, ...kbResources];
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
        setAgentType(currentAgentData?.agentic_application_type);
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
        // Set is_public and shared_with_departments for recycle bin
        setIsPublic(agentData?.is_public !== false);
        setSharedDepartments(agentData?.shared_with_departments || []);
        // Set file context management prompt fields
        setFileContextManagementPrompt(agentData?.file_context_management_prompt || "");
        setFileContextPromptExists(agentData?.file_context_prompt_exists || false);
        try {
          // Safely parse tools_id and knowledgebase_ids for recycle bin
          const toolsId = parseJsonArrayField(agentData?.tools_id, "tools_id");
          const kbIds = getKnowledgeBaseIds(agentData);
          loadRelatedTools(agentData?.agentic_application_type, toolsId, kbIds);
        } catch {
          setSelectedToolsLoading(false);
        }
        return;
      }

      setLoading(true);
      try {
        const data = await fetchData(APIs.GET_AGENTS_BY_ID + currentAgentData?.agentic_application_id);
        console.log("Fetched agent data:", data); // Debug log

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
        setSystemPromptData(systemPrompts || {});

        // Set welcome message from API response
        setWelcomeMessage(agent?.welcome_message || "");

        // Set file context management prompt fields from API response
        setFileContextManagementPrompt(agent?.file_context_management_prompt || "");
        setFileContextPromptExists(agent?.file_context_prompt_exists || false);

        // Set is_public and shared_with_departments from API response
        setIsPublic(agent?.is_public !== false);
        setSharedDepartments(agent?.shared_with_departments || []);

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
          loadRelatedTools(type, selectedToolsId, selectedKbIds);
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
    const resourceId = resource.tool_id || resource.agentic_application_id || resource.kb_id || resource.id;
    const newResources = selectedResources.filter((r) => (r.tool_id || r.agentic_application_id || r.kb_id || r.id) !== resourceId);
    setSelectedResources(newResources);

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
    if (resource?.server_id || resource?.server_name || resource?.mcp_config) return "servers";
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
    return [META_AGENT, PLANNER_META_AGENT, HYBRID_AGENT].includes(typeToCheck);
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
          loadRelatedTools(type, selectedToolsId, selectedKbIds);
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
      if (!formData.agent_goal?.trim()) {
        addMessage("Agent goal is required", "error");
        return;
      }
      if (!formData.workflow_description?.trim()) {
        addMessage("Workflow description is required", "error");
        return;
      }
    }

    // Update mode validations
    if (isUpdateMode) {
      if (!formData.agentic_application_name?.trim()) {
        addMessage("Agent name is required", "error");
        return;
      }
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

    // Common validations for both modes
    if (!formData.model_name) {
      addMessage("Please select a model", "error");
      return;
    }

    setLoading(true);

    try {
      if (isCreateMode) {
        // ============ Create Agent ============
        // Separate resources by type for the payload
        const toolServerResources = selectedResources.filter((r) => r.type === "tools" || r.type === "servers" || (!r.kb_id && !r.agentic_application_id));
        const kbResources = selectedResources.filter((r) => r.type === "knowledgebases" || r.kb_id);

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
          tools_id: toolServerResources.map((r) => r.tool_id || r.id),
          knowledgebase_ids: kbResources.map((r) => r.kb_id || r.id),
          is_public: isPublic,
          shared_with_departments: isPublic ? [] : sharedDepartments,
        };

        const response = await postData(APIs.ONBOARD_AGENTS, payload);

        // ============ AUTO-TRANSITION TO UPDATE MODE ============
        if (response?.result?.agentic_application_id) {
          const agentId = response?.result?.agentic_application_id || "";

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
        setIsPublic(false);
        setSharedDepartments([]);

        fetchAgents?.();
        onClose?.();
      } else {
        // ============ Update Agent ============
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
          is_public: isPublic,
          shared_with_departments: isPublic ? [] : sharedDepartments,
          // Knowledge base IDs to add/remove
          knowledgebase_ids_to_add: addedKnowledgeBaseIds,
          knowledgebase_ids_to_remove: removedKnowledgeBaseIds,
          // File context management prompt fields
          ...(fileContextPromptExists && {
            file_context_management_prompt: fileContextManagementPrompt,
            regenerate_file_context_prompt: regenerateFileContextPrompt,
          }),
        };

        if (filteredPatterns.length > 0) {
          payload.validation_criteria = filteredPatterns;
        }

        const res = await putData(APIs.UPDATE_AGENTS, payload);

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
          const agentId = currentAgentData?.agentic_application_id;

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
          {/* Access Control Toggle */}
          <div className={styles.footerToggleItem}>
            <Toggle
              value={isPublic}
              onChange={(e) => {
                const newIsPublic = e.target.checked;
                setIsPublic(newIsPublic);
                if (newIsPublic) {
                  // When toggling to public, clear shared departments
                  setSharedDepartments([]);
                } else {
                  // Restore departments from last saved agent data
                  setSharedDepartments(fullAgentData?.shared_with_departments || []);
                }
              }}
            />
            <span className={`label-desc ${styles.footerToggleLabel}`}>
              {isPublic ? "Visible to All Departments" : "Visible to All Departments"}
            </span>
          </div>
          {/* Regenerate Toggles (Update Mode Only) */}
          {isUpdateMode && (
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
        footer={readOnlyProp ? null : renderFooter()}
        loading={loading}>
        <form onSubmit={handleSubmit}>
          <div className="formContent">
            <div className={`form ${styles.compactForm}`}>
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
                              if (found) setFormData((prev) => ({ ...prev, agent_type: found.value }));
                            }}
                            placeholder="Select Agent Type"
                          />
                        </div>
                      </div>
                    </div>
                  </div>
                </div>
              )}

              {/* Tools & Components Section - Collapsible */}
              {hasAnyResourcePermission && (
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
                      {selectedResources.length > 0 && (
                        <span className={styles.collapsibleSectionBadge}>{selectedResources.length}</span>
                      )}
                    </div>
                    <div className={styles.collapsibleSectionRight}>
                      <div className={styles.collapsibleHeaderActions} onClick={(e) => e.stopPropagation()}>
                        {!isReadOnly && (
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
                      ) : selectedResources.length === 0 ? (
                        <div className={styles.emptyState}>
                          <p className={styles.emptyStateText}>
                            No resources added yet. Click{' '}
                            <button
                              type="button"
                              onClick={() => setShowResourcesSlider(true)}
                              className={styles.inlineAddBtn}
                              aria-label="Add resources"
                            >
                              +
                            </button>
                            {' '}to attach tools, servers, or agents.
                          </p>
                        </div>
                      ) : (
                        <ResourceAccordion
                          selectedResources={selectedResources}
                          onRemoveResource={isReadOnly ? undefined : handleRemoveResource}
                          onResourceClick={handleResourceClick}
                          onClearAll={isReadOnly ? undefined : handleClearAll}
                          disabled={isReadOnly}
                        />
                      )}
                    </div>
                  </div>
                </div>
              )}

              {/* Purpose Section - Collapsible (CREATE MODE ONLY) */}
              {isCreateMode && (
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

              {/* Agent Details Section - UPDATE MODE ONLY (Agent Goal, Workflow, Welcome Message) - Default Closed */}
              {isUpdateMode && (
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

              {/* Prompts Section - UPDATE MODE ONLY (System Prompt, File Context Prompt) - Default Open */}
              {isUpdateMode && (
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
                        Model, Tags, Departments{isUpdateMode ? ", Temperature" : ""}
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
                              placeholder="Select Model"
                              disabled={isReadOnly}
                              selectFirstByDefault={true}
                            />
                          </div>
                        </div>
                      </div>
                      {/* Tags Section */}
                      <TagSelector selectedTags={selectedTagsForSelector} onTagsChange={handleTagsChange} nonRemovableTags={nonRemovableTags} disabled={isReadOnly} />
                      {/* Departments Section - Styled like TagSelector with round + button */}
                      {!isPublic && (
                        <DepartmentSelector
                          selectedDepartments={sharedDepartments}
                          onChange={setSharedDepartments}
                          departmentsList={departmentsList.filter(dept => dept !== loggedInDepartment)}
                          disabled={isReadOnly}
                          loading={departmentsLoading}
                        />
                      )}
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
          description={
            previewResource?.agentic_application_description ||
            previewResource?.tool_description ||
            previewResource?.description
          }
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
            if (previewResource?.code_snippet) return previewResource.code_snippet;
            const resourceTab = getResourceTab(previewResource);
            if (resourceTab === "servers") {
              const mcpType = (previewResource?.mcp_type || "").toLowerCase();
              if (mcpType === "file") {
                return getServerCodePreview(previewResource);
              }
            }
            return undefined;
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
          hideModifyButton={true}
          useToolCardDescriptionStyle={true}
        />
      </FullModal>

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
        />
      )}
    </>
  );
};

export default AgentForm;
