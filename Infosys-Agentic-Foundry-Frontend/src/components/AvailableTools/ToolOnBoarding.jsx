import React, { useEffect, useState, useRef, useCallback } from "react";
import ReactDOM, { createPortal } from "react-dom";
import style from "../../css_modules/ToolOnboarding.module.css";
import { useToolsAgentsService } from "../../services/toolService.js";
import Loader from "../commonComponents/Loader.jsx";
import NewCommonDropdown from "../commonComponents/NewCommonDropdown";
import { APIs } from "../../constant";
import { useMessage } from "../../Hooks/MessageContext";
import useFetch from "../../Hooks/useAxios.js";
import { getRoleFromToken, getEmailFromToken, getUserNameFromToken } from "../../utils/jwtUtils";
import DeleteModal from "../commonComponents/DeleteModal.jsx";
import { useAuth } from "../../context/AuthContext";
import { usePermissions } from "../../context/PermissionsContext";
import SVGIcons from "../../Icons/SVGIcons.js";
import ZoomPopup from "../commonComponents/ZoomPopup.jsx";
import { WarningModal } from "../AvailableTools/WarningModal.jsx";
import AddServer from "../AgentOnboard/AddServer";
import ExecutorPanel from "../commonComponents/ExecutorPanel";
import ChatPanel from "../commonComponents/ChatPanel";
import CodeEditor from "../commonComponents/CodeEditor.jsx";
import TagSelector from "../commonComponents/TagSelector/TagSelector.jsx";
import UploadBox from "../commonComponents/UploadBox.jsx";
import IAFButton from "../../iafComponents/GlobalComponents/Buttons/Button";
import TextareaWithActions from "../commonComponents/TextareaWithActions";
import AccessControlGuide from "../commonComponents/AccessControlGuide";
import { FullModal } from "../../iafComponents/GlobalComponents/FullModal";

import { sanitizeFormField, isValidEvent } from "../../utils/sanitization";
import { copyToClipboard } from "../../utils/clipboardUtils";
import { encodePassword } from "../../utils/encodeUtils";
import ConfirmationModal from "../commonComponents/ToastMessages/ConfirmationPopup";

function ToolOnBoarding(props) {
  const mainRef = React.useRef(null);
  const { permissions, loading: permissionsLoading, hasPermission } = usePermissions();
  const HTTP_OK = 200;
  const COPY_FEEDBACK_MS = 2000;
  const loggedInUserEmail = getEmailFromToken();
  const userName = getUserNameFromToken();
  const role = getRoleFromToken();
  const { updateTools, addTool, recycleTools, getValidatorTools, getToolById, getToolVersions, deleteTool: deleteToolService } = useToolsAgentsService();

  // Permission check for delete
  const canDeleteTools = typeof hasPermission === "function" ? hasPermission("delete_access.tools") : false;

  const formObject = {
    description: "",
    code: "",
    model: "",
    createdBy: userName === "Guest" ? userName : loggedInUserEmail,
    userEmail: "",
  };
  const { isAddTool: isAddToolProp, setShowForm, editTool: editToolProp, tags, refreshData = true, fetchPaginatedTools, hideServerTab = false, contextType = "tools", readOnly: readOnlyProp = false } = props;
  const loggedInUserName = userName || "Guest";

  // Combine recycle and readOnly props into a single flag for disabling form fields
  const isReadOnly = Boolean(props?.recycle) || Boolean(readOnlyProp);

  // ============ State for Dynamic Mode Management ============
  const [currentMode, setCurrentMode] = useState(isAddToolProp ? "create" : "update");
  const [currentEditTool, setCurrentEditTool] = useState(editToolProp);

  // Derived state for mode checking
  const isAddTool = currentMode === "create";
  const editTool = currentEditTool || editToolProp || {};

  const [formData, setFormData] = useState(formObject);
  const [showKnowledge, setShowKnowledge] = useState(false);
  const [loading, setLoading] = useState(false);
  const [errorModalVisible, setErrorModalVisible] = useState(false);
  const [errorMessages, setErrorMessages] = useState([]);

  const [files, setFiles] = useState([]);
  const [codeFile, setCodeFile] = useState(null);
  const [isDraggingCode, setIsDraggingCode] = useState(false);
  const [isDraggingCapabilities, setIsDraggingCapabilities] = useState(false);

  const { addMessage, setShowPopup } = useMessage();

  const [models, setModels] = useState([]);
  const [modelsLoading, setModelsLoading] = useState(false);
  const [updateModal, setUpdateModal] = useState(false);

  const [hideCloseIcon, setHideCloseIcon] = useState(false);

  const [showZoomPopup, setShowZoomPopup] = useState(false);
  const [popupTitle, setPopupTitle] = useState("");
  const [popupContent, setPopupContent] = useState("");

  const [copiedStates, setCopiedStates] = useState({});
  const [forceAdd, setForceAdd] = useState(false);
  // Distinguish validator vs normal tool
  const [isValidatorTool, setIsValidatorTool] = useState(false);
  // Message queue toggle - when ON, use /tools/add-message-queue endpoint
  const [useMessageQueue, setUseMessageQueue] = useState(false);
  // Access control info popup state
  const [showAccessControlInfo, setShowAccessControlInfo] = useState(false);

  // Delete confirmation modal state
  const [showDeleteConfirm, setShowDeleteConfirm] = useState(false);

  // Rename-on-conflict state (recycle bin restore)
  const [restoreConflict, setRestoreConflict] = useState(null);
  const [restoreNewName, setRestoreNewName] = useState("");
  const [restoreAction, setRestoreAction] = useState(""); // "add_version" | "create_new_tool" | "skip"
  const [restoreNameError, setRestoreNameError] = useState("");

  // ============ Version Management State ============
  const [toolVersions, setToolVersions] = useState([]);
  const [selectedVersion, setSelectedVersion] = useState("");
  const [showVersionDropdown, setShowVersionDropdown] = useState(false);
  const [showUpdateVersionModal, setShowUpdateVersionModal] = useState(false);
  const [createNewVersion, setCreateNewVersion] = useState(false);
  const [newVersionName, setNewVersionName] = useState("");
  const [pendingUpdateEvent, setPendingUpdateEvent] = useState(null);
  const [pendingForceFlag, setPendingForceFlag] = useState(false);
  const versionDropdownRef = useRef(null);

  const activeTab = contextType === "servers" ? "addServer" : "toolOnboarding"; // 'toolOnboarding' | 'addServer'

  // In update mode, lock code/description editing when "All Versions" is selected (no specific version picked)
  const isAllVersionsLocked = !isAddTool && !props?.recycle && toolVersions.length > 0 && !selectedVersion;

  const { fetchData, deleteData, postData } = useFetch();

  // ExecutorPanel now manages its own loader, no need for executingCode state

  // Executor panel (autonomous) state triggers
  const [showExecutorPanel, setShowExecutorPanel] = useState(false);
  const [executeTrigger, setExecuteTrigger] = useState(0); // increment to trigger fresh run

  // Chat panel state
  const [showChatPanel, setShowChatPanel] = useState(false);

  // Ref to access ChatPanel's explainCode method
  const chatPanelRef = useRef(null);

  // To retain the chat conversation we pass the data from Toolonboarding to ChatPanel
  const [chatMessages, setChatMessages] = useState([]);

  // Store chat session ID received from ChatPanel (used for tool operations)
  const [chatSessionId, setChatSessionId] = useState("");

  // Dynamically fetched workflow ID for the coding agent
  const [codingAgentWorkflowId, setCodingAgentWorkflowId] = useState("");

  // control global popup visibility on loading change
  useEffect(() => {
    if (!loading) {
      setShowPopup(true);
    } else {
      setShowPopup(false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [loading]);

  useEffect(() => {
    setFiles(files);
  }, [files, setFiles]);

  // ============ Fetch versions from API: GET /tools/generate/versions/list/{session_id} ============
  const fetchToolVersionsList = async (sessionId) => {
    if (!sessionId) return;
    try {
      const response = await getToolVersions(sessionId, false);
      // Response can be an array directly or { versions: [...] }
      const versions = Array.isArray(response)
        ? response
        : response?.versions && Array.isArray(response.versions)
          ? response.versions
          : [];
      if (versions.length > 0) {
        setToolVersions(versions);
        // Select the newest version (first in list since API returns newest first)
        const newest = versions[0];
        setSelectedVersion(newest?.version_number ?? newest?.version_label ?? newest);
      }
    } catch {
      // Silent — keep existing versions from tool data
    }
  };

  // ============ Initialize versions from tool data ("versions": ["v1"]) as fallback ============
  useEffect(() => {
    if (!isAddTool) {
      const toolVersionsArr = currentEditTool?.versions || editToolProp?.versions || editTool?.versions;
      if (Array.isArray(toolVersionsArr) && toolVersionsArr.length > 0) {
        setToolVersions(toolVersionsArr);
        const toolStatus = editTool?.tool_status || currentEditTool?.tool_status || "deleted";
        if (props?.recycle && toolStatus === "active") {
          // Active tool = only specific version(s) were deleted
          // Auto-select the first version so user can restore/delete immediately
          const v = toolVersionsArr[0];
          const label = typeof v === "string" ? v : (v?.version || v?.version_label || `v${v?.version_number}`);
          setSelectedVersion(label);
        } else {
          // Deleted tool or non-recycle mode: default to "All Versions" (empty)
          setSelectedVersion("");
        }
      }
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isAddTool, currentEditTool?.versions, editToolProp?.versions, editTool?.versions]);

  // ============ Fetch version list from API when session ID is available ============
  useEffect(() => {
    if (chatSessionId && !props?.recycle) {
      fetchToolVersionsList(chatSessionId);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [chatSessionId]);

  // ============ Close Version Dropdown on Outside Click ============
  useEffect(() => {
    const handleClickOutside = (e) => {
      if (versionDropdownRef.current && !versionDropdownRef.current.contains(e.target)) {
        setShowVersionDropdown(false);
      }
    };
    if (showVersionDropdown) {
      document.addEventListener("mousedown", handleClickOutside);
    }
    return () => document.removeEventListener("mousedown", handleClickOutside);
  }, [showVersionDropdown]);

  // Track which tool_id has been fetched to avoid re-fetching on setCurrentEditTool
  const lastFetchedToolId = useRef(null);

  useEffect(() => {
    const fetchToolDetails = async () => {
      if (!isAddTool || props?.recycle) {
        // In recycle mode, use editTool directly since the tool is not in the main database
        if (props?.recycle) {
          // When tool_status is "active", only a version was deleted — show version's code
          const isVersionDeleted = editTool.tool_status === "active" && Array.isArray(editTool.versions) && editTool.versions.length > 0;
          const versionData = isVersionDeleted ? editTool.versions[0] : null;
          const fallbackFormData = {
            ...formObject,
            id: editTool.tool_id || "",
            description: versionData?.tool_description || editTool.tool_description || "",
            code: versionData?.code_snippet || editTool.code_snippet || "",
            model: versionData?.model_name || editTool.model_name || "",
            userEmail: loggedInUserEmail || "",
            name: editTool.tool_name || "",
            createdBy: userName === "Guest" ? null : editTool.created_by || "",
          };
          setFormData(fallbackFormData);
          if (editTool.tool_id && String(editTool.tool_id).startsWith("_validator")) {
            setIsValidatorTool(true);
          } else {
            setIsValidatorTool(Boolean(editTool.is_validator));
          }
        } else {
          // Normal edit mode - fetch from API
          const toolId = editToolProp?.tool_id || editTool.tool_id;
          // Skip if we already fetched this exact tool
          if (toolId && lastFetchedToolId.current !== toolId) {
            lastFetchedToolId.current = toolId;
            setLoading(true);
            try {
              const toolDetailsArr = await getToolById(toolId);
              const toolDetails = Array.isArray(toolDetailsArr) ? toolDetailsArr[0] : toolDetailsArr;
              const newFormData = {
                ...formObject,
                id: toolDetails?.tool_id || "",
                description: toolDetails?.tool_description || "",
                code: toolDetails?.code_snippet || "",
                model: toolDetails?.model_name || "",
                userEmail: loggedInUserEmail || "",
                name: toolDetails?.tool_name || "",
                createdBy: userName === "Guest" ? null : toolDetails?.created_by || "",
              };
              setFormData(newFormData);
              // Store full tool details (including versioning data) for version dropdown
              setCurrentEditTool(toolDetails);
              if (toolDetails?.tool_id && String(toolDetails.tool_id).startsWith("_validator")) {
                setIsValidatorTool(true);
              } else {
                setIsValidatorTool(toolDetails?.is_validator === true || toolDetails?.is_validator === "true");
              }
            } catch {
              const fallbackFormData = {
                ...formObject,
                id: editTool.tool_id || "",
                description: editTool.tool_description || "",
                code: editTool.code_snippet || "",
                model: editTool.model_name || "",
                userEmail: loggedInUserEmail || "",
                name: editTool.tool_name || "",
                createdBy: userName === "Guest" ? null : editTool.created_by || "",
              };
              setFormData(fallbackFormData);
              if (editTool.tool_id && String(editTool.tool_id).startsWith("_validator")) {
                setIsValidatorTool(true);
              } else {
                setIsValidatorTool(Boolean(editTool.is_validator));
              }
            } finally {
              setLoading(false);
            }
          }
        }
      } else {
        setFormData(formObject);
        if (activeTab === "addServer") {
          setIsValidatorTool(true);
        }
      }
    };
    fetchToolDetails();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [editToolProp, currentMode, props?.recycle]);

  const handleChange = (event) => {
    // Validate event structure before destructuring
    if (!isValidEvent(event)) {
      return;
    }

    const { name, value } = event.target;

    // Sanitize value using centralized utility
    const sanitizedValue = sanitizeFormField(name, value);

    setFormData((values) => ({ ...values, [name]: sanitizedValue }));
  };

  const validateFile = (file, type) => {
    if (!file) return false;
    if (type === "code") {
      const validExtensions = [".py", ".txt"];
      const fileName = file.name.toLowerCase();
      const hasValidExtension = validExtensions.some((ext) => fileName.endsWith(ext));
      if (!hasValidExtension) {
        addMessage("Please upload a valid Python (.py) or text (.txt) file", "error");
        setShowPopup(true);
        return false;
      }
    }
    if (type === "json") {
      const validExtensions = [".json"];
      const fileName = file.name.toLowerCase();
      return validExtensions.some((ext) => fileName.endsWith(ext));
    }
    return true;
  };

  // Drag and drop handlers
  const handleDragEnter = (type) => (e) => {
    e.preventDefault();
    e.stopPropagation();
    if (type === "code") setIsDraggingCode(true);
    if (type === "capabilities") setIsDraggingCapabilities(true);
  };

  const handleDragLeave = (type) => (e) => {
    e.preventDefault();
    e.stopPropagation();
    if (type === "code") setIsDraggingCode(false);
    if (type === "capabilities") setIsDraggingCapabilities(false);
  };

  const handleDragOver = (type) => (e) => {
    e.preventDefault();
    e.stopPropagation();
    if (type === "code" && !isDraggingCode) setIsDraggingCode(true);
    if (type === "capabilities" && !isDraggingCapabilities) setIsDraggingCapabilities(true);
  };

  const handleRemoveFile = (type) => {
    if (type === "code") {
      setCodeFile(null);
    }
    const fileInput = document.getElementById(type + "File");
    if (fileInput) fileInput.value = "";
  };

  // ============ Version Selection Handler ============
  // ============ "All Versions" Selection - resets to default tool data ============
  const handleAllVersionsSelect = () => {
    setSelectedVersion("");
    setShowVersionDropdown(false);
    // In recycle bin for active tools, don't reset form — main tool data isn't available
    if (!props?.recycle) {
      setFormData((prev) => ({
        ...prev,
        code: editTool?.code_snippet || prev.code,
        description: editTool?.tool_description || prev.description,
        model: editTool?.model_name || prev.model,
      }));
    }
  };

  const handleVersionSelect = (version) => {
    // version can be a string ("v1") or object ({version_number, version_label, version, ...})
    const label = typeof version === "string"
      ? version
      : (version?.version || version?.version_label || `v${version?.version_number}`);
    setSelectedVersion(label);
    setShowVersionDropdown(false);

    // Try 1: Load from versioning map (tools page format: { v1: { code_snippet, ... } })
    const versioning = currentEditTool?.versioning || editToolProp?.versioning || editTool?.versioning;
    if (versioning && versioning[label]) {
      const versionData = versioning[label];
      setFormData((prev) => ({
        ...prev,
        code: versionData.code_snippet || prev.code,
        description: versionData.tool_description || prev.description,
        model: versionData.model_name || prev.model,
      }));
      return;
    }

    // Try 2: Load from toolVersions array (recycle bin format: [{ version: "v1", code_snippet, ... }])
    const versionObj = typeof version === "object" ? version
      : toolVersions.find((v) => (v?.version || v?.version_label) === label);
    if (versionObj && typeof versionObj === "object") {
      setFormData((prev) => ({
        ...prev,
        code: versionObj.code_snippet || prev.code,
        description: versionObj.tool_description || prev.description,
        model: versionObj.model_name || prev.model,
      }));
    }
  };

  // ============ Get display label for a version item ============
  const getVersionLabel = (version) => {
    if (typeof version === "string") return version;
    return version?.version || version?.version_label || (version?.version_number != null ? `v${version.version_number}` : "Unknown");
  };

  // ============ Get unique key for a version item ============
  const getVersionKey = (version, idx) => {
    if (typeof version === "string") return version;
    return version?.id ?? version?.version_number ?? version?.version_id ?? idx;
  };

  const deleteTool = async () => {
    if (props?.recycle) {
      const toolStatus = editTool?.tool_status || "deleted";
      setLoading(true);

      if (props?.selectedType === "tools" && toolStatus === "active") {
        // Active tool — delete specific version(s) permanently
        const versionsToDelete = selectedVersion
          ? [selectedVersion]
          : toolVersions.map((v) => typeof v === "string" ? v : (v?.version || v?.version_label || `v${v?.version_number}`));

        if (versionsToDelete.length === 0) {
          addMessage("No versions available to delete", "error");
          setLoading(false);
          return;
        }

        try {
          let allSuccess = true;
          let lastResponse = null;
          for (const ver of versionsToDelete) {
            const url = `${APIs.DELETE_TOOL_VERSION_PERMANENTLY}${editTool?.tool_id}/${encodeURIComponent(ver)}?user_email_id=${encodeURIComponent(getEmailFromToken())}`;
            const res = await deleteData(url);
            lastResponse = res;
            if (!res?.is_delete) {
              allSuccess = false;
              const statusMsg = res?.status_message || res?.message;
              if (statusMsg) addMessage(statusMsg, "error");
            }
          }
          if (allSuccess && lastResponse) {
            const statusMsg = lastResponse?.status_message || lastResponse?.message;
            const msg = versionsToDelete.length === 1
              ? statusMsg || `Version ${versionsToDelete[0]} deleted successfully`
              : `All ${versionsToDelete.length} versions deleted permanently`;
            addMessage(msg, "success");
            props?.setRestoreData(lastResponse);
            setShowForm(false);
          }
        } catch (err) {
          const errMsg = err?.response?.data?.detail || err?.response?.data?.message || err?.message || "Failed to delete version(s)";
          addMessage(errMsg, "error");
        }
        setLoading(false);
      } else {
        // Fully deleted tool — delete entire tool permanently
        const url = `${APIs.DELETE_TOOLS_PERMANENTLY}${editTool?.tool_id}?user_email_id=${encodeURIComponent(getEmailFromToken())}`;
        try {
          const response = await deleteData(url);
          const statusMsg = response?.status_message || response?.message;
          if (response?.is_delete) {
            if (statusMsg) addMessage(statusMsg, "success");
            props?.setRestoreData(response);
            setShowForm(false);
          } else {
            if (statusMsg) addMessage(statusMsg, "error");
          }
        } catch (err) {
          const errMsg = err?.response?.data?.detail || err?.response?.data?.message || err?.message || "Failed to delete tool";
          addMessage(errMsg, "error");
        }
        setLoading(false);
      }
    }
  };

  // ============ Delete Tool (from update modal) with selected version ============
  const handleDeleteToolFromModal = async () => {
    const toolId = editTool?.tool_id || editTool?.id;
    if (!toolId) return;

    const isAdmin = role && role?.toLowerCase() === "admin";
    const emailId = userName === "Guest" ? editTool.created_by : loggedInUserEmail;
    // Use the currently selected version from the version dropdown
    const versionToDelete = selectedVersion || null;

    const data = {
      user_email_id: emailId,
      is_admin: isAdmin,
      version: versionToDelete,
    };

    try {
      setLoading(true);
      const response = await deleteToolService(data, toolId);

      if (response && typeof response !== "string") {
        const statusMsg = response.status_message || response.message;
        if (statusMsg) {
          const hasAnyFailure = Array.isArray(response.results) && response.results.some((r) => r.is_delete === false);
          addMessage(statusMsg, hasAnyFailure ? "error" : "success");
        }
      }

      setShowDeleteConfirm(false);
      setLoading(false);
      setShowForm(false);
      // Refresh tools list
      if (fetchPaginatedTools) {
        await fetchPaginatedTools(1);
      }
    } catch (e) {
      console.error("Delete error:", e);
      addMessage("Failed to delete tool", "error");
      setLoading(false);
      setShowDeleteConfirm(false);
    }
  };

  // ============ Reusable: Refresh Tool Data and Stay in Modal ============
  const refreshToolDataAndStayOpen = async (toolId, operationType = "created") => {
    try {
      const successMsg = operationType === "created" ? "Tool created successfully! Loading details..." : "Tool updated successfully! Refreshing details...";
      addMessage(successMsg, "success");

      // Fetch fresh tool data — retry once after a short delay if 404 (eventual consistency)
      let toolData = await getToolById(toolId);
      if (!toolData || typeof toolData === "string" || toolData?.error || toolData?.detail) {
        // Wait 1.5s and retry — backend may not have indexed the tool yet
        await new Promise((r) => setTimeout(r, 1500));
        toolData = await getToolById(toolId);
      }
      const tool = Array.isArray(toolData) ? toolData[0] : toolData;

      if (tool && typeof tool === "object" && tool.tool_id) {
        // Mark as fetched so the fetchToolDetails useEffect won't re-fetch
        lastFetchedToolId.current = tool.tool_id;

        // Switch to update mode with fresh data
        setCurrentMode("update");
        setCurrentEditTool(tool);

        // Update form data with fresh tool data
        setFormData({
          ...formObject,
          id: tool?.tool_id || "",
          description: tool?.tool_description || "",
          code: tool?.code_snippet || "",
          model: tool?.model_name || "",
          userEmail: loggedInUserEmail || "",
          name: tool?.tool_name || "",
          createdBy: userName === "Guest" ? null : tool?.created_by || "",
        });

        // Set versions and auto-select v1 after creation
        if (Array.isArray(tool?.versions) && tool.versions.length > 0) {
          setToolVersions(tool.versions);
          const firstVer = tool.versions[0];
          const label = typeof firstVer === "string" ? firstVer : (firstVer?.version || firstVer?.version_label || "v1");
          setSelectedVersion(label);
        } else if (operationType === "created") {
          setToolVersions(["v1"]);
          setSelectedVersion("v1");
        }

        // Update validator tool flag
        if (tool?.tool_id && String(tool.tool_id).startsWith("_validator")) {
          setIsValidatorTool(true);
        } else {
          setIsValidatorTool(tool?.is_validator === true || tool?.is_validator === "true");
        }

        // Update tags
        if (tool?.tags) {
          setSelectedTagsForSelector(tool.tags);
          const generalInTags = tool.tags.find((tag) => tag.tag_name.toLowerCase() === "general");
          if (generalInTags) {
            generalTagRef.current = generalInTags;
            setNonRemovableTags([generalInTags]);
          }
        }

        // Refresh tools list in parent component
        if (refreshData && typeof fetchPaginatedTools === "function") {
          await props.fetchPaginatedTools(1);
        }

        // Clear error and file upload states
        setCodeFile(null);
        setErrorModalVisible(false);
        setErrorMessages([]);
        setForceAdd(false);
        setLoading(false);

        const finalMsg = operationType === "created" ? "Tool created and opened for editing!" : "Tool updated and ready for further editing!";
        addMessage(finalMsg, "success");
        return true;
      }
      return false;
    } catch (error) {
      console.error(`Failed to fetch ${operationType} tool:`, error);
      // On failure, switch to update mode but keep existing form data
      if (operationType === "created" && toolId) {
        setCurrentMode("update");
        setCurrentEditTool({ ...editTool, tool_id: toolId });
        setFormData((prev) => ({ ...prev, id: toolId }));
        setToolVersions(["v1"]);
        setSelectedVersion("v1");
        setLoading(false);
        addMessage("Tool created successfully!", "success");
        return true;
      }
      addMessage(`Tool ${operationType} but failed to refresh details.`, "error");
      setLoading(false);
      return false;
    }
  };

  const handleSubmit = async (event, force = false) => {
    // Check add/update permissions before proceeding
    const canAdd = typeof hasPermission === "function" ? hasPermission("add_access.tools") : !(permissions && permissions.add_access && permissions.add_access.tools === false);
    const canUpdate =
      typeof hasPermission === "function" ? hasPermission("update_access.tools") : !(permissions && permissions.update_access && permissions.update_access.tools === false);

    if (isAddTool && !canAdd) {
      addMessage("You do not have permission to add a tool", "error");
      setLoading(false);
      return;
    }
    if (!isAddTool && !props?.recycle && !canUpdate) {
      addMessage("You do not have permission to update tools", "error");
      setLoading(false);
      return;
    }
    if (event) {
      event.preventDefault();
      event.stopPropagation();
    }
    if (userName === "Guest") {
      setUpdateModal(true);
      return;
    }

    // ============ INTERCEPT UPDATE: Show Version Modal ============
    if (!isAddTool && !props?.recycle && !showUpdateVersionModal) {
      setPendingUpdateEvent(null);
      setPendingForceFlag(force);
      setCreateNewVersion(true);
      setNewVersionName(toolVersions.length > 0 ? `v${toolVersions.length + 1}` : "v2");
      setShowUpdateVersionModal(true);
      return;
    }

    setLoading(true);
    let response;

    // ============ ADD TOOL OPERATION ============
    if (isAddTool) {
      const jsonData = {
        tool_description: formData.description,
        model_name: formData.model,
        created_by: userName === "Guest" ? formData.createdBy : loggedInUserEmail,
        tag_ids: selectedTagsForSelector.map((tag) => tag.tag_id || tag.tagId).join(","),
        is_validator: Boolean(isValidatorTool),
        force_add: Boolean(force),
        code_snippet: encodePassword(formData.code),
      };

      if (chatSessionId) {
        jsonData.session_id = chatSessionId;
      }

      response = await addTool(jsonData, useMessageQueue);
    }
    // ============ UPDATE TOOL OPERATION ============
    else if (!isAddTool && !props?.recycle) {
      const isAdmin = role && role?.toLowerCase() === "admin";
      const toolsdata = {
        model_name: formData.model,
        is_admin: isAdmin,
        tool_description: formData.description,
        code_snippet: encodePassword(formData.code),
        user_email_id: loggedInUserEmail || formData.userEmail,
        updated_tag_id_list: selectedTagsForSelector.map((tag) => tag.tag_id || tag.tagId),
        is_validator: isValidatorTool ? "true" : "false",
        version: selectedVersion || "",
        create_new_version: createNewVersion,
      };
      response = await updateTools(toolsdata, editTool.tool_id, force);
    }
    // ============ RESTORE TOOL OPERATION ============
    else if (props?.recycle) {
      if (props?.selectedType === "tools") {
        const toolStatus = editTool?.tool_status || "deleted";

        if (toolStatus === "active") {
          // Active tool — restore deleted version(s)
          const versionsToRestore = selectedVersion
            ? [selectedVersion]
            : toolVersions.map((v) => typeof v === "string" ? v : (v?.version || v?.version_label || `v${v?.version_number}`));

          if (versionsToRestore.length === 0) {
            addMessage("No versions available to restore", "error");
            setLoading(false);
            return;
          }

          try {
            let allSuccess = true;
            let lastResponse = null;
            for (const ver of versionsToRestore) {
              let url = `${APIs.RESTORE_TOOL_VERSION}${editTool?.tool_id}/${encodeURIComponent(ver)}?user_email_id=${encodeURIComponent(getEmailFromToken())}`;
              if (restoreNewName.trim()) url += `&new_name=${encodeURIComponent(restoreNewName.trim())}`;
              const res = await postData(url);
              lastResponse = res;
              if (!res?.is_restored) {
                allSuccess = false;
                addMessage(res?.message || `Failed to restore ${ver}`, "error");
              }
            }
            if (allSuccess && lastResponse) {
              props?.setRestoreData(lastResponse);
              const msg = versionsToRestore.length === 1
                ? lastResponse?.message || `Version ${versionsToRestore[0]} restored successfully`
                : `All ${versionsToRestore.length} versions restored successfully`;
              addMessage(msg, "success");
              setShowForm(false);
            }
            setLoading(false);
          } catch (err) {
            const errMsg = err?.response?.data?.detail || err?.response?.data?.message || err?.message || "Failed to restore version(s)";
            addMessage(errMsg, "error");
            setLoading(false);
          }
        } else {
          // Fully deleted tool — restore entire tool
          let url = `${APIs.RESTORE_TOOLS}${editTool?.tool_id}?user_email_id=${encodeURIComponent(getEmailFromToken())}`;
          // Append conflict resolution params as query parameters
          if (restoreAction) url += `&action=${encodeURIComponent(restoreAction)}`;
          if (restoreAction === "create_new_tool" && restoreNewName.trim()) url += `&new_name=${encodeURIComponent(restoreNewName.trim())}`;
          // Also send in body for backward compatibility
          const restoreBody = {};
          if (restoreAction) restoreBody.action = restoreAction;
          if (restoreAction === "create_new_tool" && restoreNewName.trim()) restoreBody.new_name = restoreNewName.trim();

          try {
            // eslint-disable-next-line no-undefined
            response = await postData(url, Object.keys(restoreBody).length > 0 ? restoreBody : undefined, { silent: true });
            if (response?.is_restored) {
              props?.setRestoreData(response);
              addMessage(response?.message, "success");
              setRestoreConflict(null);
              setRestoreNewName("");
              setRestoreAction("");
              setRestoreNameError("");
              setLoading(false);
              setShowForm(false);
            } else if (response?.name_conflict && response?.options) {
              // Initial 409 conflict — show conflict resolution modal with options
              setRestoreConflict(response);
              setRestoreNewName(response.default_new_name || response.suggested_name || "");
              const firstOption = response.options[0] || "";
              setRestoreAction(firstOption);
              setRestoreNameError("");
              setLoading(false);
            } else if (response?.name_conflict || response?.invalid_name) {
              // User's chosen name already exists or is invalid — show inline error on modal
              setRestoreNameError(response?.message || "Name not available. Please try a different name.");
              setLoading(false);
            } else if (response?.skipped) {
              addMessage(response?.message || "Restore operation skipped", "success");
              setRestoreConflict(null);
              setRestoreNewName("");
              setRestoreAction("");
              setRestoreNameError("");
              setLoading(false);
              setShowForm(false);
            } else {
              addMessage(response?.message || "Restore failed", "error");
              setLoading(false);
            }
          } catch (err) {
            const errData = err?.response?.data;
            // Handle 409 conflict response from catch block
            if (errData?.name_conflict && errData?.options) {
              setRestoreConflict(errData);
              setRestoreNewName(errData.default_new_name || errData.suggested_name || "");
              const firstOption = errData.options[0] || "";
              setRestoreAction(firstOption);
              setRestoreNameError("");
              setLoading(false);
            } else if (errData?.name_conflict || errData?.invalid_name) {
              setRestoreNameError(errData?.message || "Name not available. Please try a different name.");
              setLoading(false);
            } else {
              const errMsg = errData?.detail || errData?.message || err?.message || "Failed to restore tool";
              addMessage(errMsg, "error");
              setLoading(false);
            }
          }
        }
      }
      return;
    }

    // ============ HANDLE SUCCESS RESPONSE ============
    if (response?.is_created || response?.is_update) {
      const toolId = response?.tool_id || response?.result?.tool_id || editTool?.tool_id || currentEditTool?.tool_id;
      const operationType = response?.is_created ? "created" : "updated";

      if (toolId) {
        const success = await refreshToolDataAndStayOpen(toolId, operationType);
        if (success) {
          return; // Stay in modal with refreshed data
        }
      }

      // Fallback: Keep the form open with current data in update mode
      addMessage(`Tool has been ${operationType} successfully!`, "success");
      if (operationType === "created" && toolId) {
        setCurrentMode("update");
        setFormData((prev) => ({ ...prev, id: toolId }));
        setToolVersions(["v1"]);
        setSelectedVersion("v1");
      }
      setCodeFile(null);
      setErrorModalVisible(false);
      setForceAdd(false);
      setLoading(false);

      if (refreshData && typeof fetchPaginatedTools === "function") {
        await props.fetchPaginatedTools(1);
      }
    } else if (!props?.recycle) {
      setLoading(false);
      if (response?.message?.includes("Verification failed:") && response?.error_on_screen !== true) {
        const match = response.message.match(/Verification failed:\s*\[(.*)\]/s);
        if (match && match[1]) {
          const raw = match[1];
          let warnings = [];
          try {
            warnings = JSON.parse(`[${raw}]`);
          } catch {
            warnings = raw.split(/(?<!\\)'\s*,\s*|(?<!\\)"\s*,\s*/).map((s) => s.replace(/^['"]|['"]$/g, ""));
          }
          setErrorMessages(warnings);
          setErrorModalVisible(true);
          setForceAdd(true);
          return;
        }
      }
      // Handle other errors
      const errorMsg = response?.detail || response?.response?.data?.detail || response?.message || "No response received. Please try again.";
      addMessage(errorMsg, "error");
    }
  };

  // ============ Confirm Update with Version Choice ============
  const handleConfirmUpdate = async (shouldCreateNewVersion) => {
    setCreateNewVersion(shouldCreateNewVersion);
    setShowUpdateVersionModal(false);
    setLoading(true);
    try {
      const isAdmin = role && role?.toLowerCase() === "admin";
      const toolsdata = {
        model_name: formData.model,
        is_admin: isAdmin,
        tool_description: formData.description,
        code_snippet: encodePassword(formData.code),
        user_email_id: loggedInUserEmail || formData.userEmail,
        updated_tag_id_list: selectedTagsForSelector.map((tag) => tag.tag_id || tag.tagId),
        is_validator: isValidatorTool ? "true" : "false",
        version: shouldCreateNewVersion ? newVersionName.trim() : (selectedVersion || ""),
        create_new_version: shouldCreateNewVersion,
      };
      const response = await updateTools(toolsdata, editTool.tool_id, pendingForceFlag);

      if (response?.is_created || response?.is_update) {
        const toolId = response?.tool_id || response?.result?.tool_id || editTool?.tool_id || currentEditTool?.tool_id;
        const operationType = response?.is_created ? "created" : "updated";

        if (toolId) {
          const success = await refreshToolDataAndStayOpen(toolId, operationType);
          if (success) return;
        }

        addMessage(`Tool has been ${operationType} successfully!`, "success");
        setLoading(false);
        if (refreshData && typeof fetchPaginatedTools === "function") {
          await props.fetchPaginatedTools(1);
        }
        setCodeFile(null);
        setFormData(formObject);
        setShowForm(false);
        setErrorModalVisible(false);
        setForceAdd(false);
      } else {
        setLoading(false);
        if (response?.message?.includes("Verification failed:") && response?.error_on_screen !== true) {
          const match = response.message.match(/Verification failed:\s*\[(.*)\]/s);
          if (match && match[1]) {
            const raw = match[1];
            let warnings = [];
            try {
              warnings = JSON.parse(`[${raw}]`);
            } catch {
              warnings = raw.split(/(?<!\\)'\s*,\s*|(?<!\\)"\s*,\s*/).map((s) => s.replace(/^['"]|['"]$/g, ""));
            }
            setErrorMessages(warnings);
            setErrorModalVisible(true);
            setForceAdd(true);
            return;
          }
        }
        const errorMsg = response?.detail || response?.response?.data?.detail || response?.message || "No response received. Please try again.";
        addMessage(errorMsg, "error");
      }
    } catch (error) {
      console.error("Update with version failed:", error);
      addMessage("Failed to update tool. Please try again.", "error");
      setLoading(false);
    }
  };

  // TagSelector state and handler (new pattern)
  const [selectedTagsForSelector, setSelectedTagsForSelector] = useState([]);
  const [nonRemovableTags, setNonRemovableTags] = useState([]);
  const generalTagRef = useRef(null);

  // Fetch tags and set default "general" tag for new tools
  const fetchAndSetDefaultTags = async () => {
    try {
      const tagsData = await fetchData(APIs.GET_TAGS);
      if (tagsData && Array.isArray(tagsData)) {
        // Find the "general" tag
        const generalTag = tagsData.find((tag) => tag.tag_name.toLowerCase() === "general");
        if (generalTag) {
          generalTagRef.current = generalTag;
          setNonRemovableTags([generalTag]);
          setSelectedTagsForSelector([generalTag]);
        }
      }
    } catch (error) {
      console.error("Error fetching tags:", error);
    }
  };

  useEffect(() => {
    if (!isAddTool && editTool.tags) {
      setSelectedTagsForSelector(editTool.tags);

      // Cache the general tag for auto-add behavior
      const generalInTags = editTool.tags.find((tag) => tag.tag_name.toLowerCase() === "general");
      if (generalInTags) {
        generalTagRef.current = generalInTags;
        setNonRemovableTags([generalInTags]);
      }
    } else if (isAddTool) {
      // Fetch tags and set "general" as default for new tools
      fetchAndSetDefaultTags();
    }
  }, [editTool.tags, currentMode, isAddTool]);

  const handleTagsChange = (newSelectedTags) => {
    const general = generalTagRef.current;
    if (!general) {
      setSelectedTagsForSelector(newSelectedTags);
      return;
    }

    // If no tags left, default back to General (non-removable)
    if (newSelectedTags.length === 0) {
      setSelectedTagsForSelector([general]);
      setNonRemovableTags([general]);
      return;
    }

    const nonGeneralCount = newSelectedTags.filter((tag) => tag.tag_name.toLowerCase() !== "general").length;

    // General is removable only when other tags exist
    setSelectedTagsForSelector(newSelectedTags);
    setNonRemovableTags(nonGeneralCount > 0 ? [] : [general]);
  };

  const fetchModels = async () => {
    setModelsLoading(true);
    try {
      const data = await fetchData(APIs.GET_MODELS);
      if (data?.models && Array.isArray(data.models)) {
        const formattedModels = data.models.map((model) => ({
          label: model,
          value: model,
        }));
        setModels(formattedModels);

        // Auto-select model based on mode
        if (!formData.model) {
          // For create mode: use default_model_name
          // For update mode: prioritize existing tool's model (already set in formData), fallback to default_model_name
          const modelToSelect = data.default_model_name || (formattedModels.length > 0 ? formattedModels[0].label : "");
          if (modelToSelect) {
            setFormData((prev) => ({ ...prev, model: modelToSelect }));
          }
        }
      } else {
        setModels([]);
      }
    } catch {
      console.error("Fetching failed");
      setModels([]);
    } finally {
      setModelsLoading(false);
    }
  };

  const hasLoadedModelsOnce = useRef(false);

  useEffect(() => {
    if (!hasLoadedModelsOnce.current) {
      hasLoadedModelsOnce.current = true;
      fetchModels();
    }
    // intentionally run only on mount
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const { logout } = useAuth();

  const handleLoginButton = (e) => {
    e.preventDefault();
    logout("/login");
  };

  const handleZoomClick = useCallback((title, content) => {
    setPopupTitle(title);
    setPopupContent(content || "");
    setShowZoomPopup(true);
  }, []);

  const handleZoomSave = (updatedContent) => {
    if (popupTitle === "Code Snippet") {
      if (!codeFile) {
        setFormData((prev) => ({
          ...prev,
          code: updatedContent,
        }));
      }
    }
  };

  // Fire executor panel run
  // Restore scroll when executor panel closes
  React.useEffect(() => {
    if (!showExecutorPanel && mainRef.current) {
      mainRef.current.style.overflowY = "auto";
    }
  }, [showExecutorPanel]);

  const runCode = (userCode) => {
    if (!userCode) {
      addMessage("Please provide valid code to run", "error");
      return;
    }

    // Close ChatPanel if open (only one panel at a time)
    setShowChatPanel(false);

    if (!showExecutorPanel) {
      // First time: just open panel; ExecutorPanel auto executes on mount
      setShowExecutorPanel(true);
      // Hide vertical scroll on main
      if (mainRef.current) mainRef.current.style.overflowY = "hidden";
    } else {
      // Panel already open: bump trigger to re-run
      setExecuteTrigger((c) => c + 1);
    }
  };

  const handleCopy = async (key, text) => {
    const success = await copyToClipboard(text);
    if (success) {
      setCopiedStates((prev) => ({ ...prev, [key]: true }));
      setTimeout(() => {
        setCopiedStates((prev) => ({ ...prev, [key]: false }));
      }, COPY_FEEDBACK_MS);
    } else {
      console.error("Failed to copy text to clipboard");
    }
  };

  // ============ Modal Close Handler ============
  const handleModalClose = () => {
    setChatMessages([]); // Clear chatbot messages in ChatPanel
    setChatSessionId(""); // Reset chat session ID for next tool creation
    setCodeFile(null);
    setFormData(formObject);
    setShowForm(false);
  };

  // ============ Get Modal Title ============
  const getModalTitle = () => {
    if (isAddTool && activeTab === "addServer" && !hideServerTab) {
      return "Add Server";
    }
    if (props?.recycle) {
      return "Restore Tool";
    }
    if (isAddTool) {
      return isValidatorTool ? "Add Validator" : "Add Tool";
    }
    return formData.name || currentEditTool?.tool_name || editTool?.tool_name || (isValidatorTool ? "Update Validator" : "Update Tool");
  };

  // ============ Get Header Info ============
  const getHeaderInfo = () => {
    const info = [];
    if (!isAddTool) {
      info.push({
        label: "Type",
        value: isValidatorTool ? "Validator" : "Tool",
      });
    }
    info.push({
      label: "Created By",
      value: isAddTool ? userName : editTool.created_by || "",
    });
    return info;
  };

  // ============ Render Footer ============
  const renderFooter = () => (
    <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", width: "100%", gap: "16px" }}>
      {/* Left side: Toggles - with horizontal scroll when overflow */}
      <div style={{ display: "flex", alignItems: "center", gap: "24px", flex: 1, minWidth: 0, overflowX: "auto", overflowY: "hidden", paddingBottom: "4px", scrollbarWidth: "thin" }}>
        {/* Tool/Validator Toggle - Either/Or style */}
        {!isReadOnly && (
          <div className={style.toolValidatorToggle}>
            <span
              onClick={() => setIsValidatorTool(false)}
              className={`${style.toolValidatorOption} ${!isValidatorTool ? style.active : style.inactive}`}
            >
              Tool
            </span>
            <span className={style.toolValidatorDivider}>|</span>
            <span
              onClick={() => setIsValidatorTool(true)}
              className={`${style.toolValidatorOption} ${isValidatorTool ? style.active : style.inactive}`}
            >
              Validator
            </span>
          </div>
        )}

      </div>

      {/* Right side: Action Buttons */}
      <div style={{ display: "flex", gap: "12px", flexShrink: 0 }}>
        {props?.recycle ? (
          (() => {
            const isVersionRestore = (editTool?.tool_status || currentEditTool?.tool_status) === "active";
            const deleteLabel = isVersionRestore
              ? (selectedVersion ? `Delete ${selectedVersion}` : "Delete All Versions")
              : "Delete";
            const restoreLabel = isVersionRestore
              ? (selectedVersion ? `Restore ${selectedVersion}` : "Restore All Versions")
              : "Restore";
            return (
              <>
                <IAFButton type="secondary" onClick={deleteTool} aria-label={deleteLabel}>
                  {deleteLabel}
                </IAFButton>
                <IAFButton
                  type="primary"
                  onClick={() => {
                    const form = document.querySelector("form");
                    if (form) form.requestSubmit();
                  }}
                  aria-label={restoreLabel}
                >
                  {restoreLabel}
                </IAFButton>
              </>
            );
          })()
        ) : readOnlyProp ? (
          /* Read-only mode: only show Close button, no submit/update */
          <IAFButton type="secondary" onClick={handleModalClose} aria-label="Close">
            Close
          </IAFButton>
        ) : (
          <>
            <IAFButton type="secondary" onClick={handleModalClose} aria-label="Cancel">
              Cancel
            </IAFButton>
            {/* Delete Button - shown for all roles with delete permission in update mode */}
            {!isAddTool && !props?.recycle && !isReadOnly && canDeleteTools && (
              <IAFButton
                type="primary"
                onClick={() => setShowDeleteConfirm(true)}
                aria-label={selectedVersion ? `Delete version ${selectedVersion}` : "Delete all versions"}
              >
                {selectedVersion ? `Delete ${selectedVersion}` : "Delete"}
              </IAFButton>
            )}
            <IAFButton
              type="primary"
              disabled={isAllVersionsLocked}
              title={isAllVersionsLocked ? "Select a specific version to update" : ""}
              onClick={() => {
                const form = document.querySelector('form[class*="form-section"]');
                if (form) {
                  form.requestSubmit();
                }
              }}
              aria-label={
                isAddTool
                  ? contextType === "servers"
                    ? "Add Server"
                    : isValidatorTool
                      ? "Add Validator"
                      : "Add Tool"
                  : contextType === "servers"
                    ? "Update Server"
                    : isValidatorTool
                      ? "Update Validator"
                      : "Update Tool"
              }>
              {isAddTool
                ? contextType === "servers"
                  ? "Add Server"
                  : isValidatorTool
                    ? "Add Validator"
                    : "Add Tool"
                : contextType === "servers"
                  ? "Update Server"
                  : isValidatorTool
                    ? "Update Validator"
                    : "Update Tool"}
            </IAFButton>
            {isAddTool && errorMessages.length > 0 && !errorModalVisible && !forceAdd && (
              <IAFButton type="primary" onClick={() => setErrorModalVisible(true)}>
                View Warnings
              </IAFButton>
            )}
          </>
        )}
      </div>
    </div>
  );

  // ============ Render Side Panel (Executor) ============
  const renderSidePanel = () => {
    if (!showExecutorPanel) return null;
    return <ExecutorPanel code={formData.code} autoExecute={true} executeTrigger={executeTrigger} onClose={() => setShowExecutorPanel(false)} mode="tool" />;
  };

  // ============ Render Chat Panel ============
  const renderChatPanel = () => {
    if (!showChatPanel) return null;
    return (
      <ChatPanel
        ref={chatPanelRef}
        messages={chatMessages}
        setMessages={setChatMessages}
        workflowId={codingAgentWorkflowId}
        models={models}
        onCodeUpdate={(code) => {
          setFormData((prev) => ({ ...prev, code }));
          addMessage("Code snippet updated successfully", "success");
          // Re-fetch version list — AI generates a new version on the backend
          if (chatSessionId) {
            fetchToolVersionsList(chatSessionId);
          }
        }}
        onClose={() => setShowChatPanel(false)}
        codeSnippet={formData.code}
        toolId={formData.id || editTool?.tool_id || ""}
        chatSessionId={chatSessionId}
        onSessionIdChange={(newSessionId) => {
          // Store the new session ID for use in tool operations
          setChatSessionId(newSessionId);
        }}
      />
    );
  };

  /**
   * Handle "Explain" selection from CodeEditor
   * Opens chat panel if closed and sends the selected code for explanation
   */
  const handleExplainSelection = useCallback((selectedCode) => {
    // Open chat panel if not already open
    setShowExecutorPanel(false);
    setShowChatPanel(true);

    // Use setTimeout to ensure ChatPanel is mounted and ref is available
    setTimeout(() => {
      if (chatPanelRef.current?.explainCode) {
        chatPanelRef.current.explainCode(selectedCode);
      }
    }, 100);
  }, []);

  // Get the active side panel
  const getActiveSidePanel = () => {
    if (showChatPanel) return renderChatPanel();
    if (showExecutorPanel) return renderSidePanel();
    return null;
  };

  // Get split header labels based on active panel
  const getSplitHeaderLabels = () => {
    if (showChatPanel) return { left: "Configuration", right: "Chat Assistant" };
    if (showExecutorPanel) return { left: "Configuration", right: "Execution" };
    return null;
  };

  return (
    <>
      <DeleteModal show={updateModal} onClose={() => setUpdateModal(false)}>
        <p>You are not authorized to update a tool. Please login with registered email.</p>
        <div className={style.buttonContainer}>
          <button onClick={(e) => handleLoginButton(e)} className={style.loginBtn}>
            Login
          </button>
          <button onClick={() => setUpdateModal(false)} className={style.cancelBtn}>
            Cancel
          </button>
        </div>
      </DeleteModal>{" "}
      <FullModal
        isOpen={true}
        onClose={handleModalClose}
        title={getModalTitle()}
        headerInfo={getHeaderInfo()}
        footer={props?.readOnly ? undefined : renderFooter()}
        loading={loading}
        splitLayout={showExecutorPanel || showChatPanel}
        sidePanel={getActiveSidePanel()}
        splitHeaderLabels={getSplitHeaderLabels()}
        mainRef={mainRef}>
        {/* Only show ToolOnboarding form if editing, else allow tab switch */}
        {(isAddTool ? activeTab === "toolOnboarding" : true) && (
          <form onSubmit={handleSubmit} className={"form-section"}>
            <div className="formContent" style={{ paddingTop: 0 }}>
              <div className="form" style={{ gap: "4px" }}>
                <div className="formGroup" style={{ gap: "4px", marginTop: 0, marginBottom: 0 }}>
                  <TextareaWithActions
                    name="description"
                    value={formData.description}
                    onChange={handleChange}
                    label="Description"
                    required={true}
                    disabled={isReadOnly || isAllVersionsLocked}
                    readOnly={isReadOnly || isAllVersionsLocked}
                    placeholder={isAllVersionsLocked ? "Select a specific version to edit" : (props?.descriptionPlaceholder || "Describe what this tool does...")}
                    rows={3}
                    onZoomSave={(updatedContent) => setFormData((prev) => ({ ...prev, description: updatedContent }))}
                  />
                </div>

                <div className="formGroup" style={{ marginTop: 0, marginBottom: 0 }}>
                  <div className={style.codeEditorWrapper}>
                    {/* Version Dropdown - inside code editor header, left of action icons */}
                    {/* In recycle bin: only show for active tools (version-deleted). Hidden for fully-deleted tools. */}
                    {(!props?.recycle || (props?.recycle && toolVersions.length > 0 && (editTool?.tool_status || currentEditTool?.tool_status) === "active")) && (
                      <div className={style.versionDropdownInline} ref={versionDropdownRef}>
                        <button
                          type="button"
                          className={`${style.versionDropdownTrigger} ${toolVersions.length === 0 ? style.versionDropdownDisabled : ""}`}
                          onClick={() => toolVersions.length > 0 && setShowVersionDropdown((prev) => !prev)}
                          disabled={toolVersions.length === 0}
                          title={toolVersions.length === 0 ? "No versions available. Use AI assistant to generate code versions." : "Select a version"}
                        >
                          <SVGIcons icon="layers" width={12} height={12} color="var(--accent)" />
                          <span>
                            {toolVersions.length === 0
                              ? "No versions"
                              : selectedVersion || "All Versions"}
                          </span>
                          {toolVersions.length > 0 && (
                            <span style={{
                              transform: showVersionDropdown ? "rotate(180deg)" : "rotate(0deg)",
                              transition: "transform 0.2s ease",
                              display: "inline-flex"
                            }}>
                              <SVGIcons icon="chevron-down" width={12} height={12} color="var(--content-color)" />
                            </span>
                          )}
                        </button>
                        {showVersionDropdown && toolVersions.length > 0 && (
                          <div className={style.versionDropdownMenu}>
                            {/* "All Versions" option - selects all versions for bulk restore/delete */}
                            <div
                              key="all-versions"
                              className={`${style.versionDropdownItem} ${!selectedVersion ? style.versionDropdownItemActive : ""}`}
                              onClick={handleAllVersionsSelect}
                            >
                              <span className={style.versionItemLabel}>All Versions</span>
                            </div>
                            {toolVersions.map((version, idx) => {
                              const label = getVersionLabel(version);
                              const isActive = selectedVersion === label;
                              return (
                                <div
                                  key={getVersionKey(version, idx)}
                                  className={`${style.versionDropdownItem} ${isActive ? style.versionDropdownItemActive : ""}`}
                                  onClick={() => handleVersionSelect(version)}
                                >
                                  <span className={style.versionItemLabel}>{label}</span>
                                </div>
                              );
                            })}
                          </div>
                        )}
                      </div>
                    )}
                    <CodeEditor
                      codeToDisplay={formData.code || ""}
                      onChange={(isReadOnly || isAllVersionsLocked) ? () => { } : (value) => setFormData((prev) => ({ ...prev, code: value }))}
                      readOnly={isReadOnly || isAllVersionsLocked}
                      enableDragDrop={!isReadOnly && !isAllVersionsLocked}
                      acceptedFileTypes={['.py']}
                      showUploadButton={!isReadOnly && !isAllVersionsLocked}
                      showHelperText={!isReadOnly && !isAllVersionsLocked}
                      helperText={isAllVersionsLocked ? "Select a specific version to edit code" : "(drag & drop / upload .py file / type directly)"}
                      label="Code Snippet"
                      onLabelClick={() => {
                        // Focus the ace editor by finding it in the DOM
                        const editor = document.querySelector(".ace_editor .ace_text-input");
                        if (editor) editor.focus();
                      }}
                      onFileLoad={(content, file) => {
                        // File loaded successfully
                      }}
                      onExplainSelection={handleExplainSelection} // hide code highlight explain option
                    />
                    {!isReadOnly && !isAllVersionsLocked && (
                      <button
                        type="button"
                        className={style.copyIcon}
                        onClick={() => handleCopy("code-snippet", formData.code)}
                        title="Copy"
                        disabled={!formData.code || formData.code.trim() === ""}
                        style={{ opacity: !formData.code || formData.code.trim() === "" ? 0.4 : 1, cursor: !formData.code || formData.code.trim() === "" ? "not-allowed" : "pointer" }}>
                        <SVGIcons icon="fa-regular fa-copy" width={16} height={16} fill="var(--icon-color)" />
                      </button>
                    )}
                    {!isReadOnly && !isAllVersionsLocked && (
                      <>
                        <button type="button" className={style.playIcon} onClick={() => runCode(formData.code)} title="Run Code">
                          <SVGIcons icon="lucide-play" width={16} height={16} stroke="var(--icon-color)" fill="none" />
                        </button>
                        <button type="button" className={style.infoIcon} onClick={(e) => { e.stopPropagation(); setShowAccessControlInfo(true); }} title="Access Control Guide">
                          <SVGIcons icon="info-modern" width={16} height={16} />
                        </button>
                      </>
                    )}
                    {!isReadOnly && !isAllVersionsLocked && (
                      <div className={style.iconGroup}>
                        <button type="button" className={style.expandIcon} onClick={() => handleZoomClick("Code Snippet", formData.code)} title="Expand">
                          <SVGIcons icon="fa-solid fa-up-right-and-down-left-from-center" width={16} height={16} fill="var(--icon-color)" />
                        </button>
                      </div>
                    )}
                    <span className={`${style.copiedText} ${copiedStates["code-snippet"] ? style.visible : style.hidden}`}>Text Copied!</span>
                  </div>
                </div>

                {/* Configuration Section - Model, Tags & Departments */}
                <div className="formSection">
                  <div className={style.configRow}>
                    {/* Model Selector - Inline Layout */}
                    <div className={style.modelSelectorContainer}>
                      <div className={style.modelSelectorWrapper}>
                        <span className={style.modelSelectorLabel}>
                          Model <span className="required">*</span>
                        </span>
                        <div className={style.modelDropdownWrapper}>
                          <NewCommonDropdown
                            options={models.map((m) => (typeof m === "string" ? m : m.label || m.value || ""))}
                            selected={formData.model || ""}
                            onSelect={(val) => setFormData((prev) => ({ ...prev, model: val }))}
                            placeholder={modelsLoading ? "Loading models..." : "Select Model"}
                            showSearch={true}
                            disabled={isReadOnly || modelsLoading}
                            selectFirstByDefault={true}
                          />
                        </div>
                      </div>
                    </div>
                    {/* Tags Section */}
                    <TagSelector selectedTags={selectedTagsForSelector} onTagsChange={handleTagsChange} disabled={isReadOnly} nonRemovableTags={nonRemovableTags} />
                  </div>
                </div>
              </div>
            </div>
          </form>
        )}
        {isAddTool && activeTab === "addServer" && !hideServerTab && (
          <div className="modalContentWrapper">
            <AddServer />
          </div>
        )}
        <WarningModal
          show={errorModalVisible}
          messages={errorMessages}
          onClose={() => {
            setErrorModalVisible(false);
            setForceAdd(false);
          }}
          onForceAdd={async () => {
            setErrorModalVisible(false);
            await handleSubmit(null, true);
          }}
          showForceAdd={forceAdd}
          isUpdate={!isAddTool}
        />

        {/* Floating AI Assistant Button - only on Create Tool page, hidden for SuperAdmin */}
        {isAddTool && !isReadOnly && role?.toUpperCase() !== "SUPERADMIN" && (
          <button
            type="button"
            className={`${style.floatingAgentBtn} ${showChatPanel ? style.floatingAgentBtnHidden : ""} ${showExecutorPanel ? style.floatingAgentBtnShifted : ""}`}
            onClick={async () => {
              try {
                const res = await fetchData(
                  `${APIs.WORKFLOW_GET_BY_NAME}?workflow_name=${encodeURIComponent("Tool Onboard Agent")}`
                );
                const pId = res?.data?.workflow_id || res?.workflow_id || "";
                if (pId) {
                  setCodingAgentWorkflowId(pId);
                } else {
                  addMessage(res?.detail || "Workflow 'Tool Onboard Agent' not found.", "error");
                  return;
                }
              } catch (err) {
                const detail = err?.response?.data?.detail || err?.message || "Failed to fetch coding agent workflow.";
                addMessage(detail, "error");
                return;
              }
              setShowExecutorPanel(false);
              setShowChatPanel(true);
            }}
            aria-label="Coding Agent">
            <span className={style.floatingAgentBtnSparkle}></span>
            <span className={style.floatingAgentBtnSparkle}></span>
            <SVGIcons icon="fa-robot" width={26} height={26} fill="#fff" />
          </button>
        )}
      </FullModal>
      <ZoomPopup
        show={showZoomPopup}
        onClose={() => setShowZoomPopup(false)}
        title={popupTitle}
        content={popupContent}
        onSave={handleZoomSave}
        type={popupTitle === "Code Snippet" ? "code" : "text"}
        readOnly={isReadOnly || isAllVersionsLocked || (popupTitle === "Code Snippet" && Boolean(codeFile))}
      />

      {/* Access Control Guide Modal */}
      <AccessControlGuide
        isOpen={showAccessControlInfo}
        onClose={() => setShowAccessControlInfo(false)}
      />

      {/* Delete Confirmation Modal */}
      {showDeleteConfirm && (
        <ConfirmationModal
          message={selectedVersion
            ? `Are you sure you want to delete version "${selectedVersion}" of this tool? This action cannot be undone.`
            : `Are you sure you want to delete this tool? This will permanently delete all ${toolVersions.length > 0 ? toolVersions.length : ""} version(s) of "${editTool?.tool_name || editTool?.name || "this tool"}". This action cannot be undone.`
          }
          onConfirm={handleDeleteToolFromModal}
          setShowConfirmation={setShowDeleteConfirm}
          loading={loading}
        />
      )}

      {/* Update Version Modal */}
      {showUpdateVersionModal && createPortal(
        <div className={style.vmOverlay} onClick={() => setShowUpdateVersionModal(false)}>
          <div className={style.vmDialog} onClick={(e) => e.stopPropagation()}>
            <button type="button" className={style.vmCloseBtn} onClick={() => setShowUpdateVersionModal(false)} aria-label="Close">&times;</button>
            <div className={style.vmContent}>
              <p className={style.vmQuestion}>Create a new version?</p>
              <div className={style.vmRadioRow}>
                <label className={style.vmRadioLabel}>
                  <input type="radio" name="vmChoice" className={style.vmRadio} checked={createNewVersion} onChange={() => setCreateNewVersion(true)} />
                  <span>Yes</span>
                </label>
                <label className={style.vmRadioLabel}>
                  <input type="radio" name="vmChoice" className={style.vmRadio} checked={!createNewVersion} onChange={() => setCreateNewVersion(false)} />
                  <span>No</span>
                </label>
              </div>


            </div>
            <div className={style.vmActions}>
              <IAFButton type="secondary" onClick={() => setShowUpdateVersionModal(false)}>Cancel</IAFButton>
              <IAFButton type="primary" onClick={() => handleConfirmUpdate(createNewVersion)}>Confirm</IAFButton>
            </div>
          </div>
        </div>,
        document.body
      )}

      {/* Restore conflict resolution dialog (recycle bin restore) */}
      {restoreConflict && ReactDOM.createPortal(
        <div className={style.renameOverlay}
          onClick={() => { setRestoreConflict(null); setRestoreNewName(""); setRestoreAction(""); setRestoreNameError(""); }}>
          <div className={style.renameDialog} onClick={(e) => e.stopPropagation()}>
            <h3 className={style.renameTitle}>Restore Conflict</h3>
            <p className={style.renameMessage}>{restoreConflict.message}</p>

            {/* Radio options from API response */}
            {restoreConflict.options && restoreConflict.options.length > 0 && (
              <div className={style.renameFieldGroup}>
                <label className="label-desc">What would you like to do?</label>
                <div className={style.vmRadioRow} style={{ flexDirection: "column", alignItems: "flex-start", gap: "8px" }}>
                  {restoreConflict.options.includes("add_version") && (
                    <label className={style.vmRadioLabel}>
                      <input
                        type="radio"
                        name="restoreChoice"
                        className={style.vmRadio}
                        checked={restoreAction === "add_version"}
                        onChange={() => { setRestoreAction("add_version"); setRestoreNewName(""); setRestoreNameError(""); }}
                      />
                      <span>Add as new version</span>
                    </label>
                  )}
                  {restoreConflict.options.includes("create_new_tool") && (
                    <label className={style.vmRadioLabel}>
                      <input
                        type="radio"
                        name="restoreChoice"
                        className={style.vmRadio}
                        checked={restoreAction === "create_new_tool"}
                        onChange={() => { setRestoreAction("create_new_tool"); setRestoreNewName(restoreConflict.default_new_name || restoreConflict.suggested_name || ""); setRestoreNameError(""); }}
                      />
                      <span>Create as new tool</span>
                    </label>
                  )}
                  {restoreConflict.options.includes("skip") && (
                    <label className={style.vmRadioLabel}>
                      <input
                        type="radio"
                        name="restoreChoice"
                        className={style.vmRadio}
                        checked={restoreAction === "skip"}
                        onChange={() => { setRestoreAction("skip"); setRestoreNewName(""); setRestoreNameError(""); }}
                      />
                      <span>Skip (do not restore)</span>
                    </label>
                  )}
                </div>
              </div>
            )}

            {/* Name input — only shown when "create_new_tool" is selected */}
            {restoreAction === "create_new_tool" && (
              <div className={style.renameFieldGroup}>
                <label className="label-desc">New name</label>
                <input
                  className="input"
                  type="text"
                  value={restoreNewName}
                  onChange={(e) => { setRestoreNewName(e.target.value); setRestoreNameError(""); }}
                  onKeyDown={(e) => { if (e.key === "Enter" && restoreNewName.trim()) handleSubmit(null); }}
                  autoFocus
                  placeholder="Enter a new tool name"
                  style={restoreNameError ? { borderColor: "var(--error-color, #ef4444)" } : {}}
                />
                {restoreNameError && (
                  <span style={{ fontSize: "12px", color: "var(--error-color, #ef4444)", marginTop: "4px" }}>
                    {restoreNameError}
                  </span>
                )}
                <span style={{ fontSize: "12px", color: "var(--content-color)", opacity: 0.7, marginTop: "4px" }}>
                  Names ending with _v1, _v2, etc. are reserved and not allowed
                </span>
              </div>
            )}

            <div className={style.renameActions}>
              <IAFButton type="secondary" onClick={() => { setRestoreConflict(null); setRestoreNewName(""); setRestoreAction(""); setRestoreNameError(""); }}>Cancel</IAFButton>
              <IAFButton
                type="primary"
                disabled={loading || !restoreAction || (restoreAction === "create_new_tool" && !restoreNewName.trim())}
                onClick={() => handleSubmit(null)}
              >
                {restoreAction === "skip" ? "Skip" : restoreAction === "add_version" ? "Add Version" : "Restore"}
              </IAFButton>
            </div>
          </div>
        </div>,
        document.body
      )}
    </>
  );
}

export default ToolOnBoarding;
