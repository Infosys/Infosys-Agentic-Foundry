import React, { useEffect, useState, useRef, useCallback } from "react";
import style from "../../css_modules/ToolOnboarding.module.css";
import { useToolsAgentsService } from "../../services/toolService.js";
import Loader from "../commonComponents/Loader.jsx";
import NewCommonDropdown from "../commonComponents/NewCommonDropdown";
import { APIs } from "../../constant";
import { useMessage } from "../../Hooks/MessageContext";
import useFetch from "../../Hooks/useAxios.js";
import Cookies from "js-cookie";
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
import DepartmentSelector from "../commonComponents/DepartmentSelector/DepartmentSelector.jsx";
import UploadBox from "../commonComponents/UploadBox.jsx";
import IAFButton from "../../iafComponents/GlobalComponents/Buttons/Button";
import Toggle from "../commonComponents/Toggle.jsx";
import TextareaWithActions from "../commonComponents/TextareaWithActions";
import AccessControlGuide from "../commonComponents/AccessControlGuide";
import { FullModal } from "../../iafComponents/GlobalComponents/FullModal";

import { sanitizeFormField, isValidEvent } from "../../utils/sanitization";
import { copyToClipboard } from "../../utils/clipboardUtils";

function ToolOnBoarding(props) {
  const mainRef = React.useRef(null);
  const { permissions, loading: permissionsLoading, hasPermission } = usePermissions();
  const HTTP_OK = 200;
  const COPY_FEEDBACK_MS = 2000;
  const loggedInUserEmail = Cookies.get("email");
  const userName = Cookies.get("userName");
  const role = Cookies.get("role");
  const { updateTools, addTool, recycleTools, getValidatorTools, getToolById } = useToolsAgentsService();

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

  // Is Public toggle and Shared Departments state
  const [isPublic, setIsPublic] = useState(false);
  const [sharedDepartments, setSharedDepartments] = useState([]);
  const [departmentsList, setDepartmentsList] = useState([]);
  const [departmentsLoading, setDepartmentsLoading] = useState(false);
  // Store departments before clearing when toggling to public
  const previousDepartmentsRef = React.useRef([]);

  // Get logged-in user's department from cookies
  const loggedInDepartment = Cookies.get("department") || "";

  const activeTab = contextType === "servers" ? "addServer" : "toolOnboarding"; // 'toolOnboarding' | 'addServer'

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

  // Dynamically fetched pipeline ID for the coding agent
  const [codingAgentPipelineId, setCodingAgentPipelineId] = useState("");

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

  useEffect(() => {
    const fetchToolDetails = async () => {
      if (!isAddTool || props?.recycle) {
        // In recycle mode, use editTool directly since the tool is not in the main database
        if (props?.recycle) {
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
          // Load is_public and shared_with_departments
          setIsPublic(editTool.is_public === true);
          const departments = editTool.shared_with_departments || [];
          setSharedDepartments(departments);
          previousDepartmentsRef.current = departments;
          // Autoselect VALIDATOR if tool_id starts with _validator
          if (editTool.tool_id && String(editTool.tool_id).startsWith("_validator")) {
            setIsValidatorTool(true);
          } else {
            setIsValidatorTool(Boolean(editTool.is_validator));
          }
        } else {
          // Normal edit mode - fetch from API
          const toolId = editTool.tool_id;
          if (toolId) {
            setLoading(true); // Show loader while fetching tool details
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
              // Load is_public and shared_with_departments
              setIsPublic(toolDetails?.is_public === true);
              const departments = toolDetails?.shared_with_departments || [];
              setSharedDepartments(departments);
              previousDepartmentsRef.current = departments;
              // Autoselect VALIDATOR if tool_id starts with _validator
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
              // Load is_public and shared_with_departments
              setIsPublic(editTool.is_public === true);
              const deptsFallback = editTool.shared_with_departments || [];
              setSharedDepartments(deptsFallback);
              previousDepartmentsRef.current = deptsFallback;
              // Autoselect VALIDATOR if tool_id starts with _validator
              if (editTool.tool_id && String(editTool.tool_id).startsWith("_validator")) {
                setIsValidatorTool(true);
              } else {
                setIsValidatorTool(Boolean(editTool.is_validator));
              }
            } finally {
              setLoading(false); // Hide loader after fetching completes
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
  }, [currentEditTool, currentMode, props?.recycle]);

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

  const deleteTool = async () => {
    let response;
    if (props?.recycle) {
      // delete in recycle branch does not require toolsdata here
      let url = "";
      if (props?.selectedType === "tools") {
        url = `${APIs.DELETE_TOOLS_PERMANENTLY}${editTool?.tool_id}?user_email_id=${encodeURIComponent(Cookies?.get("email"))}`;
      }

      response = await deleteData(url);
      if (response?.is_delete) {
        props?.setRestoreData(response);
        addMessage(response?.message, "success");
        setLoading(false);
        setShowForm(false);
      } else {
        addMessage(response?.message, "error");
        setLoading(false);
        //  setShowForm(false)
      }
    }
  };

  // ============ Reusable: Refresh Tool Data and Stay in Modal ============
  const refreshToolDataAndStayOpen = async (toolId, operationType = "created") => {
    try {
      const successMsg = operationType === "created" ? "Tool created successfully! Loading details..." : "Tool updated successfully! Refreshing details...";
      addMessage(successMsg, "success");

      // Fetch fresh tool data
      const toolData = await getToolById(toolId);
      const tool = Array.isArray(toolData) ? toolData[0] : toolData;

      if (tool) {
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
    if (!isAddTool && !canUpdate) {
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
        code_snippet: formData.code,
        // Add is_public and shared_with_departments
        is_public: isPublic,
        shared_with_departments: isPublic ? [] : sharedDepartments,
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
        code_snippet: formData.code,
        created_by: editTool.created_by,
        user_email_id: formData.userEmail,
        updated_tag_id_list: selectedTagsForSelector.map((tag) => tag.tag_id || tag.tagId),
        is_validator: isValidatorTool ? "true" : "false",
        // Add is_public and shared_with_departments
        is_public: isPublic,
        shared_with_departments: isPublic ? [] : sharedDepartments,
      };
      response = await updateTools(toolsdata, editTool.tool_id, force);
    }
    // ============ RESTORE TOOL OPERATION ============
    else if (props?.recycle) {
      let url = "";
      if (props?.selectedType === "tools") {
        url = `${APIs.RESTORE_TOOLS}${editTool?.tool_id}?user_email_id=${encodeURIComponent(Cookies?.get("email"))}`;
      }

      response = await postData(url);
      if (response?.is_restored) {
        props?.setRestoreData(response);
        addMessage(response?.message, "success");
        setLoading(false);
        setShowForm(false);
      } else {
        addMessage(response?.message, "error");
        setLoading(false);
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

      // Fallback: Show success message but don't close modal
      addMessage(`Tool has been ${operationType} successfully!`, "success");
      setLoading(false);

      if (refreshData && typeof fetchPaginatedTools === "function") {
        await props.fetchPaginatedTools(1);
      }
      // Reset form state including file upload
      setCodeFile(null);
      setFormData(formObject);
      setIsPublic(false);
      setSharedDepartments([]);
      setShowForm(false);
      setErrorModalVisible(false);
      setForceAdd(false);
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

  // Fetch departments for shared departments dropdown
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
      } catch {
        console.error("Failed to fetch departments");
        setDepartmentsList([]);
      } finally {
        setDepartmentsLoading(false);
      }
    };
    fetchDepartments();
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
    if (!isAddTool && !props?.recycle) {
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
        {/* Access Control Toggle - On/Off style */}
        {!isReadOnly && (
          <div style={{ display: "flex", alignItems: "center", gap: "10px", flexShrink: 0 }}>
            <span className={style.footerToggleLabel}>
              Share with All Departments
            </span>
            <Toggle
              value={isPublic}
              onChange={(e) => {
                const newIsPublic = e.target.checked;
                setIsPublic(newIsPublic);
                if (newIsPublic) {
                  // When toggling to public, save current departments and clear
                  previousDepartmentsRef.current = sharedDepartments;
                  setSharedDepartments([]);
                } else {
                  // When toggling back to private, restore previous departments
                  setSharedDepartments(previousDepartmentsRef.current);
                }
              }}
              disabled={isReadOnly}
            />
            <span className={`${style.toolValidatorOption} ${isPublic ? style.active : style.inactive}`} style={{ minWidth: "28px", fontSize: "12px" }}>
              {isPublic ? "ON" : "OFF"}
            </span>
          </div>
        )}

      </div>

      {/* Right side: Action Buttons */}
      <div style={{ display: "flex", gap: "12px", flexShrink: 0 }}>
        {props?.recycle ? (
          <>
            <IAFButton type="secondary" onClick={deleteTool} aria-label="Delete">
              Delete
            </IAFButton>
            <IAFButton
              type="primary"
              onClick={() => {
                const form = document.querySelector("form");
                if (form) form.requestSubmit();
              }}
              aria-label="Restore">
              Restore
            </IAFButton>
          </>
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
            <IAFButton
              type="primary"
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
        pipelineId={codingAgentPipelineId}
        models={models}
        onCodeUpdate={(code) => {
          setFormData((prev) => ({ ...prev, code }));
          addMessage("Code snippet updated successfully", "success");
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
        footer={readOnlyProp ? null : renderFooter()}
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
                    disabled={isReadOnly}
                    readOnly={isReadOnly}
                    placeholder={props?.descriptionPlaceholder || "Describe what this tool does..."}
                    rows={3}
                    onZoomSave={(updatedContent) => setFormData((prev) => ({ ...prev, description: updatedContent }))}
                  />
                </div>

                <div className="formGroup" style={{ marginTop: 0, marginBottom: 0 }}>
                  <div className={style.codeEditorWrapper}>
                    <CodeEditor
                      codeToDisplay={formData.code || ""}
                      onChange={isReadOnly ? () => { } : (value) => setFormData((prev) => ({ ...prev, code: value }))}
                      readOnly={isReadOnly}
                      enableDragDrop={!isReadOnly}
                      acceptedFileTypes={['.py']}
                      showUploadButton={!isReadOnly}
                      showHelperText={!isReadOnly}
                      helperText="(drag & drop / upload .py file / type directly)"
                      label="Code Snippet"
                      onLabelClick={() => {
                        // Focus the ace editor by finding it in the DOM
                        const editor = document.querySelector(".ace_editor .ace_text-input");
                        if (editor) editor.focus();
                      }}
                      onFileLoad={(content, file) => {
                        console.log(`Loaded ${file.name}`);
                      }}
                      onExplainSelection={handleExplainSelection} // hide code highlight explain option
                    />
                    {!isReadOnly && (
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
                    {!isReadOnly && (
                      <>
                        <button type="button" className={style.playIcon} onClick={() => runCode(formData.code)} title="Run Code">
                          <SVGIcons icon="lucide-play" width={16} height={16} stroke="var(--icon-color)" fill="none" />
                        </button>
                        <button type="button" className={style.infoIcon} onClick={(e) => { e.stopPropagation(); setShowAccessControlInfo(true); }} title="Access Control Guide">
                          <SVGIcons icon="info-modern" width={16} height={16} />
                        </button>
                      </>
                    )}
                    {!isReadOnly && (
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
                            placeholder={"Select Model"}
                            showSearch={true}
                            disabled={isReadOnly}
                            selectFirstByDefault={true}
                          />
                        </div>
                      </div>
                    </div>
                    {/* Tags Section */}
                    <TagSelector selectedTags={selectedTagsForSelector} onTagsChange={handleTagsChange} disabled={isReadOnly} nonRemovableTags={nonRemovableTags} />
                    {/* Departments Section - Using DepartmentSelector component */}
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

        {/* Floating AI Assistant Button - only on Create Tool page */}
        {isAddTool && !isReadOnly && (
          <button
            type="button"
            className={`${style.floatingAgentBtn} ${showChatPanel ? style.floatingAgentBtnHidden : ""} ${showExecutorPanel ? style.floatingAgentBtnShifted : ""}`}
            onClick={async () => {
              try {
                const res = await fetchData(
                  `${APIs.PIPELINE_GET_BY_NAME}?pipeline_name=${encodeURIComponent("Tool Onboard Agent")}`
                );
                const pId = res?.data?.pipeline_id || res?.pipeline_id || "";
                if (pId) {
                  setCodingAgentPipelineId(pId);
                } else {
                  addMessage(res?.detail || "Pipeline 'Tool Onboard Agent' not found.", "error");
                  return;
                }
              } catch (err) {
                const detail = err?.response?.data?.detail || err?.message || "Failed to fetch coding agent pipeline.";
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
        readOnly={isReadOnly || (popupTitle === "Code Snippet" && Boolean(codeFile))}
      />

      {/* Access Control Guide Modal */}
      <AccessControlGuide
        isOpen={showAccessControlInfo}
        onClose={() => setShowAccessControlInfo(false)}
      />
    </>
  );
}

export default ToolOnBoarding;
