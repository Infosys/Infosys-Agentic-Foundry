import React, { useState, useEffect, useRef } from "react";
import NewCommonDropdown from "../commonComponents/NewCommonDropdown";
import styles from "../../css_modules/ToolOnboarding.module.css";
import { useToolsAgentsService } from "../../services/toolService";
import { copyToClipboard } from "../../utils/clipboardUtils";
import Cookies from "js-cookie";
import SVGIcons from "../../Icons/SVGIcons.js";
import ZoomPopup from "../commonComponents/ZoomPopup.jsx";
import { useMcpServerService } from "../../services/serverService";
import { useMessage } from "../../Hooks/MessageContext";
import TagSelector from "../commonComponents/TagSelector/TagSelector.jsx";
import DepartmentSelector from "../commonComponents/DepartmentSelector/DepartmentSelector.jsx";
import useFetch from "../../Hooks/useAxios.js";
import { APIs } from "../../constant";
import { useErrorHandler } from "../../Hooks/useErrorHandler";
import ExecutorPanel from "../commonComponents/ExecutorPanel";
import Loader from "../commonComponents/Loader.jsx";
import CodeEditor from "../commonComponents/CodeEditor.jsx";
import DeleteModal from "../commonComponents/DeleteModal.jsx";
import { useAuth } from "../../context/AuthContext";
import IAFButton from "../../iafComponents/GlobalComponents/Buttons/Button";
import UploadBox from "../commonComponents/UploadBox.jsx";
import TextareaWithActions from "../commonComponents/TextareaWithActions";
import { FullModal } from "../../iafComponents/GlobalComponents/FullModal";
import Toggle from "../commonComponents/Toggle";
import AccessControlGuide from "../commonComponents/AccessControlGuide";

export default function AddServer({ editMode = false, serverData = null, onClose, setRefreshPaginated = () => { }, recycle = false, setRestoreData = () => { }, readOnly: readOnlyProp = false }) {
  const { addServer } = useToolsAgentsService();
  const { postData, deleteData, fetchData } = useFetch();
  const { getAllServers, updateServer, getServerById } = useMcpServerService();
  const user = { isAdmin: true, teams: ["dev", "ops"], team_ids: ["dev", "ops"] };
  const isAdmin = Boolean(user && (user.isAdmin || user.is_admin));
  const userTeams = user?.teams || user?.team_ids || [];

  // Combine recycle and readOnly props into a single flag for disabling form fields
  const isReadOnly = recycle || Boolean(readOnlyProp);

  // ============ State for Dynamic Mode Management ============
  const [currentMode, setCurrentMode] = useState(editMode ? "update" : "create");
  const [currentServerData, setCurrentServerData] = useState(serverData);

  // Derived state for mode checking (matching ToolOnBoarding pattern)
  const isCreateMode = currentMode === "create";
  const isUpdateMode = currentMode === "update";
  // Derived server data: state first (updated after create), then prop (passed from parent on edit)
  const effectiveServerData = currentServerData || serverData || {};

  const [serverType, setServerType] = useState("code");
  const [serverName, setServerName] = useState("");
  const [moduleName, setModuleName] = useState("");
  const [description, setDescription] = useState("");
  const [selectedTeam, setSelectedTeam] = useState("");
  const [endpoint, setEndpoint] = useState("");
  const [codeFile, setCodeFile] = useState(null);
  const [codeContent, setCodeContent] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");
  const [showZoomPopup, setShowZoomPopup] = useState(false);
  const [popupTitle, setPopupTitle] = useState("");
  const [popupContent, setPopupContent] = useState("");
  const [copiedStates, setCopiedStates] = useState({});
  const [showAccessControlInfo, setShowAccessControlInfo] = useState(false);
  const { addMessage, setShowPopup } = useMessage();
  const { handleApiError, handleError } = useErrorHandler();
  const userName = Cookies.get("userName");
  const creatorEmail =
    (effectiveServerData &&
      (effectiveServerData.created_by || effectiveServerData.user_email_id || effectiveServerData.createdBy || (effectiveServerData.raw && (effectiveServerData.raw.created_by || effectiveServerData.raw.user_email_id)))) ||
    Cookies.get("email") ||
    Cookies.get("userName") ||
    "";

  const teamOptions = userTeams.map((t) => ({ label: t, value: t }));

  const prefillDoneRef = useRef(false);

  // TagSelector state (new pattern matching ToolOnBoarding)
  const [selectedTagsForSelector, setSelectedTagsForSelector] = useState([]);
  const [nonRemovableTags, setNonRemovableTags] = useState([]);
  const generalTagRef = useRef(null);

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

  const [command, setCommand] = useState("Python");
  const [externalArgs, setExternalArgs] = useState("");

  const [vaultValue, setVaultValue] = useState("");
  const [vaultOptions, setVaultOptions] = useState([]);
  const [updateModal, setUpdateModal] = useState(false);
  const [loadingEndpoints, setLoadingEndpoints] = useState(false);
  const [isPublic, setIsPublic] = useState(false);
  const [sharedDepartments, setSharedDepartments] = useState([]);
  const [departmentsList, setDepartmentsList] = useState([]);
  const [departmentsLoading, setDepartmentsLoading] = useState(false);
  // Store departments before clearing when toggling to public
  const previousDepartmentsRef = React.useRef([]);
  const loggedInDepartment = Cookies.get("department") || "";
  const { logout } = useAuth();
  const handleLoginButton = (e) => {
    e.preventDefault();
    logout("/login");
  };

  const serverIdForPrefill = effectiveServerData?.id || effectiveServerData?.tool_id || null;
  useEffect(() => {
    prefillDoneRef.current = false;
    // Set General tag as default when in add mode
    if (isCreateMode) {
      (async () => {
        try {
          const tagsData = await fetchData(APIs.GET_TAGS);
          if (tagsData && Array.isArray(tagsData)) {
            const generalTag = tagsData.find((tag) => tag.tag_name.toLowerCase() === "general");
            if (generalTag) {
              generalTagRef.current = generalTag;
              setNonRemovableTags([generalTag]);
              setSelectedTagsForSelector([generalTag]);
            } else {
              setSelectedTagsForSelector([]);
            }
          } else {
            setSelectedTagsForSelector([]);
          }
        } catch (err) {
          console.error("Failed to fetch tags for default:", err);
          setSelectedTagsForSelector([]);
        }
      })();
    }
  }, [isCreateMode, serverIdForPrefill, fetchData]);

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
  }, [fetchData]);

  useEffect(() => {
    if (serverType !== "active") return;

    const loadVaultOptions = async () => {
      setLoadingEndpoints(true);
      try {
        const payload = { user_email: Cookies.get("email") };
        const data = await postData(APIs.GET_SECRETS, payload);

        let options = [];
        if (Array.isArray(data)) {
          options = data.map((item) => ({
            label: item["name"] || item["key_name"] || item["id"],
            value: item["id"] || item["key_id"] || item["name"],
          }));
        } else if (data?.key_names && Array.isArray(data["key_names"])) {
          options = data["key_names"].map((item) => ({
            label: item["name"] || item["key_name"] || item["id"] || item,
            value: item["id"] || item["key_id"] || item["name"] || item,
          }));
        }

        if (vaultValue && !options.some((opt) => opt.value === vaultValue)) {
          options.push({ label: vaultValue, value: vaultValue });
        }

        setVaultOptions(options);
      } catch (error) {
        handleApiError(error, { context: "AddServer.fetchSecrets" });
        setVaultOptions([]);
      } finally {
        setLoadingEndpoints(false);
      }
    };

    loadVaultOptions();
  }, [serverType]);

  // Recycle bin functions - Restore and Delete permanently
  const restoreServer = async () => {
    setSubmitting(true);
    try {
      const serverId = serverData?.tool_id || serverData?.id;
      const url = `${APIs.RESTORE_SERVERS}${serverId}?user_email_id=${encodeURIComponent(Cookies.get("email"))}`;
      const response = await postData(url);
      if (response?.is_restored) {
        addMessage(response?.message || "Server restored successfully", "success");
        setRestoreData(response);
        onClose();
      } else {
        addMessage(response?.message || "Failed to restore server", "error");
      }
    } catch (error) {
      handleApiError(error, { context: "AddServer.restoreServer" });
      addMessage(error?.response?.data?.detail || "Failed to restore server", "error");
    } finally {
      setSubmitting(false);
    }
  };

  const deleteServerPermanently = async () => {
    setSubmitting(true);
    try {
      const serverId = serverData?.tool_id || serverData?.id;
      const url = `${APIs.DELETE_SERVERS_PERMANENTLY}${serverId}?user_email_id=${encodeURIComponent(Cookies.get("email"))}`;
      const response = await deleteData(url);
      if (response?.is_delete || response?.is_deleted) {
        addMessage(response?.message || "Server deleted permanently", "success");
        setRestoreData(response);
        onClose();
      } else {
        addMessage(response?.message || "Failed to delete server", "error");
      }
    } catch (error) {
      handleApiError(error, { context: "AddServer.deleteServerPermanently" });
      addMessage(error?.response?.data?.detail || "Failed to delete server", "error");
    } finally {
      setSubmitting(false);
    }
  };

  const validateFile = (file, type) => {
    if (!file) {
      addMessage("No file selected", "error");
      setShowPopup(true);
      return false;
    }

    if (file.size === 0) {
      addMessage("The file is empty. Please select a valid file.", "error");
      setShowPopup(true);
      return false;
    }

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
      const hasValidExtension = validExtensions.some((ext) => fileName.endsWith(ext));
      if (!hasValidExtension) {
        addMessage("Please upload a valid JSON file", "error");
        setShowPopup(true);
        return false;
      }
    }
    return true;
  };

  const validate = () => {
    if (!serverName.trim()) return "Server Name is required.";
    if (!description.trim()) return "Description is required.";
    if (!isAdmin) {
      if (!selectedTeam.trim()) return "Team selection is required for non-admin users.";
    }
    if (serverType === "code") {
      // For Update Server mode, only validate code snippet (no file upload option)
      if (isUpdateMode) {
        if (!codeContent.trim()) {
          return "Code snippet is required.";
        }
      } else {
        // For Add Server mode: Either code snippet or file upload must be present
        if (!codeFile && !codeContent.trim()) {
          return "Either code snippet or Python file upload is required.";
        }
        // If both are present, allow (file takes precedence)
        // If file is present, codeContent is ignored
      }
    } else if (serverType === "active") {
      if (!endpoint.trim()) return "Endpoint URL is required for active servers.";
    } else if (serverType === "external") {
      if (!moduleName.trim()) return "Module Name is required for external servers.";
    }
    return "";
  };

  // Defensive error setter
  const safeSetError = (err) => {
    if (!err) return addMessage("", "error");
    if (typeof err === "string") return addMessage(err, "error");
    addMessage(formatErrorMessage(err), "error");
  };

  // ============ Reusable: Refresh Server Data and Stay in Modal ============
  const refreshServerDataAndStayOpen = async (serverId, operationType = "created") => {
    try {
      const successMsg = operationType === "created" ? "Server added successfully! Loading details..." : "Server updated successfully! Refreshing details...";
      addMessage(successMsg, "success");

      // Fetch fresh server data by ID (matching ToolOnBoarding's getToolById pattern)
      const serverResponse = await getServerById(serverId);
      const server = Array.isArray(serverResponse) ? serverResponse[0] : serverResponse;

      if (server) {
        // Switch to update mode with fresh data
        setCurrentMode("update");
        setCurrentServerData(server);
        prefillDoneRef.current = false;

        // Update form with fresh server data
        const raw = server.raw || server || {};
        const incomingType = (server.mcp_type || raw.mcp_type || server.type || raw.type || "code").toString().toLowerCase();
        let mappedType = "code";
        if (incomingType.includes("url") || incomingType.includes("remote") || incomingType === "active") mappedType = "active";
        else if (incomingType.includes("module") || incomingType === "external") mappedType = "external";
        else mappedType = "code";

        setServerType(mappedType);
        setServerName(server.name || server.tool_name || raw.tool_name || "");
        setDescription(server.description || server.tool_description || raw.tool_description || "");
        setSelectedTeam(server.team_id || raw.team_id || "");

        // Update code content for code servers
        if (mappedType === "code") {
          const codeCandidates = [
            raw.mcp_config && raw?.mcp_config?.args?.[1],
            raw.mcp_file && raw.mcp_file.code_content,
            raw.code_content,
            server.codeContent,
            server.code_content,
          ];
          const code = codeCandidates.find((c) => typeof c === "string" && c.trim().length > 0) || "";
          setCodeContent(code);
          setCodeFile(null);
        } else if (mappedType === "active") {
          const ep = raw.mcp_url || server.endpoint || "";
          setEndpoint(ep);
        } else if (mappedType === "external") {
          setModuleName(
            (server.mcp_config && Array.isArray(server.mcp_config.args) && server.mcp_config.args.length > 1 ? server.mcp_config.args[1] : "") || ""
          );
        }

        // Update tags
        const rawTags = server.tags || server.tag_ids || raw.tags || raw.tag_ids || [];
        if (Array.isArray(rawTags) && rawTags.length > 0) {
          const tagsForSelector = rawTags
            .map((t) => {
              if (typeof t === "object" && t !== null) {
                return {
                  tag_name: t.tag_name || t.tag || t.name || "",
                  tag_id: t.tag_id || t.id || t.tagId || "",
                  tagId: t.tag_id || t.id || t.tagId || "",
                };
              }
              return null;
            })
            .filter(Boolean);
          setSelectedTagsForSelector(tagsForSelector);

          const generalInTags = tagsForSelector.find((tag) => tag.tag_name.toLowerCase() === "general");
          if (generalInTags) {
            generalTagRef.current = generalInTags;
            setNonRemovableTags([generalInTags]);
          }
        }

        setSubmitting(false);

        // Refresh parent component's paginated list AFTER state updates
        try {
          if (typeof setRefreshPaginated === "function") {
            await setRefreshPaginated();
          }
        } catch (e) {
          console.debug("[AddServer] setRefreshPaginated failed", e);
        }

        const finalMsg = operationType === "created" ? "Server added and opened for editing!" : "Server updated and ready for further editing!";
        addMessage(finalMsg, "success");
        return true;
      }
      return false;
    } catch (error) {
      console.error(`Failed to fetch ${operationType} server:`, error);
      addMessage(`Server ${operationType} but failed to refresh details.`, "error");
      setSubmitting(false);
      return false;
    }
  };

  // Patch all setError calls to use safeSetError
  const handleSubmit = async (e) => {
    if (e) {
      e.preventDefault();
      e.stopPropagation();
    }
    setError("");
    const v = validate();
    if (v) {
      safeSetError(v);
      return;
    }
    try {
      const existing = await getAllServers();
      if (Array.isArray(existing)) {
        const lowerName = (serverName || "").trim().toLowerCase();
        const conflict = existing.some((s) => {
          const candidate = (s.tool_name || s.name || "").toString().trim().toLowerCase();
          return candidate && candidate === lowerName;
        });
        if (conflict) {
          safeSetError("Server name already exists. Choose a unique name.");
          return;
        }
      }
    } catch (lookupErr) {
      // If uniqueness check fails (network), proceed — backend will enforce unique constraint
      console.warn("Name uniqueness lookup failed", lookupErr);
    }

    setSubmitting(true);
    try {
      const mcp_type = serverType === "active" ? "url" : serverType === "code" ? "file" : "module";
      const selectedTagIds = selectedTagsForSelector.map((tag) => tag.tag_id || tag.tagId);

      const payload = {
        tool_name: serverName.trim(),
        tool_description: description.trim(),
        mcp_type,
        created_by: Cookies.get("email") || "Guest",
        mcp_url: mcp_type === "url" ? endpoint.trim() : "",
        mcp_module_name: mcp_type === "module" ? moduleName.trim() : "",
        code_content: mcp_type === "file" && !codeFile ? codeContent.trim() : "",
        mcp_file: mcp_type === "file" && codeFile ? codeFile : undefined,
        tag_ids: selectedTagIds,
        is_public: isPublic,
        shared_with_departments: isPublic ? [] : sharedDepartments,
        ...(serverType === "external" ? { command, externalArgs } : {}),
        ...(serverType === "active" && vaultValue ? { vault_id: vaultValue } : {}),
      };
      if (!payload.mcp_file) delete payload.mcp_file;
      // PATCH: Always include Authorization header for REMOTE (active) server
      if (serverType === "active" && vaultValue && typeof vaultValue === "string" && vaultValue.trim().length > 0) {
        payload.mcp_config = payload.mcp_config || {};
        payload.mcp_config.headers = payload.mcp_config.headers || {};
        payload.mcp_config.headers.Authorization = `VAULT::${vaultValue}`;
        // Remove vault_id from payload for REMOTE add, only use header
        if (payload.vault_id) delete payload.vault_id;
      }

      const response = await addServer(payload); // addServer uses /tools/mcp/add
      const ok = response && (response?.is_created === true || response?.is_update === true || response?.status === "success");

      if (ok) {
        // ============ AUTO-TRANSITION TO UPDATE MODE ============
        // Try all possible locations for server ID
        const serverId = response?.result?.tool_id || "";

        console.log("[AddServer] Extracted serverId:", serverId); // Debug log

        if (serverId) {
          const success = await refreshServerDataAndStayOpen(serverId, "created");
          if (success) {
            return; // Stay in update mode - success!
          }
        }

        // Fallback: If serverId not found or refresh fails, still refresh paginated list
        console.log("[AddServer] Auto-transition failed, calling setRefreshPaginated in fallback");
        const msg = response?.result?.message || response?.message || "Server added successfully!";
        addMessage(msg, "success");

        // ALWAYS refresh the paginated list even in fallback
        try {
          if (typeof setRefreshPaginated === "function") {
            await setRefreshPaginated();
          }
        } catch (e) {
          console.debug("[AddServer] setRefreshPaginated failed", e);
        }

        // Reset form
        setServerName("");
        setModuleName("");
        setDescription("");
        setSelectedTeam("");
        setEndpoint("");
        setCodeFile(null);
        setCodeContent("");
        setSelectedTagsForSelector([]);

        onClose?.();
      } else {
        if (response?.message && response.message.includes("Verification failed:")) {
          safeSetError(response.message);
        } else {
          safeSetError(response?.detail || response?.message || "Failed to add server");
        }
      }
    } catch (e2) {
      safeSetError(e2?.detail || e2?.message || e2 || "Submit failed");
    } finally {
      setSubmitting(false);
    }
  };

  const handleUpdate = async (e) => {
    e.preventDefault();
    if (userName === "Guest") {
      setUpdateModal(true);
      return;
    }
    setError("");
    setSubmitting(true);
    try {
      const is_admin = Cookies.get("role")?.toLowerCase() === "admin";
      const mcp_type = serverType === "active" ? "url" : serverType === "code" ? "file" : "module";
      const selectedTagIds = selectedTagsForSelector.map((tag) => tag.tag_id || tag.tagId);
      // Use derived effectiveServerData (state-first, then prop) — same pattern as ToolOnBoarding's editTool
      const id = effectiveServerData?.id || effectiveServerData?.tool_id || (effectiveServerData?.raw && effectiveServerData.raw.id) || "";

      if (!id) {
        safeSetError("Server ID not found. Please close and reopen the server to update.");
        setSubmitting(false);
        return;
      }

      const tool_name = serverName?.trim() || effectiveServerData?.tool_name || effectiveServerData?.name || (effectiveServerData?.raw && (effectiveServerData.raw.tool_name || effectiveServerData.raw.name)) || "";
      const tool_description =
        description?.trim() ||
        effectiveServerData?.tool_description ||
        effectiveServerData?.description ||
        (effectiveServerData?.raw && (effectiveServerData.raw.tool_description || effectiveServerData.raw.description)) ||
        "";
      const mcp_url = mcp_type === "url" ? endpoint?.trim() || effectiveServerData?.endpoint || (effectiveServerData?.raw && effectiveServerData.raw.endpoint) || "" : "";
      const mcp_module_name = mcp_type === "module" ? moduleName?.trim() || effectiveServerData?.mcp_module_name || (effectiveServerData?.raw && effectiveServerData.raw.mcp_module_name) || "" : "";
      const code_content =
        mcp_type === "file" && !codeFile
          ? codeContent?.trim() || effectiveServerData?.codeContent || effectiveServerData?.code_content || (effectiveServerData?.raw && (effectiveServerData.raw.codeContent || effectiveServerData.raw.code_content)) || ""
          : "";
      const payload = {
        is_admin,
        tool_id: id,
        tool_name,
        tool_description,
        mcp_type,
        created_by: Cookies.get("email") || "Guest",
        user_email_id: Cookies.get("email") || "Guest",
        mcp_url,
        mcp_module_name,
        code_content,
        tag_ids: selectedTagIds,
        updated_tag_id_list: selectedTagIds,
        is_public: isPublic,
        shared_with_departments: isPublic ? [] : sharedDepartments,
        ...(serverType === "external" ? { command, externalArgs } : {}),
        ...(serverType === "active" && vaultValue ? { vault_id: vaultValue } : {}),
      };
      // --- PATCH: Always include Authorization header for REMOTE (active) server ---
      if (serverType === "active" && vaultValue && typeof vaultValue === "string" && vaultValue.trim().length > 0) {
        payload.mcp_config = payload.mcp_config || {};
        payload.mcp_config.headers = { Authorization: `VAULT::${vaultValue}` };
        // Remove vault_id from payload for REMOTE update, only use header
        if (payload.vault_id) delete payload.vault_id;
      }
      if (selectedTeam) payload.team_id = selectedTeam;
      let sendPayload = payload;
      if (codeFile) {
        const fd = new FormData();
        Object.keys(payload).forEach((k) => {
          if (k === "mcp_config" && typeof payload[k] === "object") {
            fd.append("mcp_config", JSON.stringify(payload[k]));
            return;
          }
          const v = payload[k];
          if (v === undefined || v === null) return;
          if (Array.isArray(v)) {
            fd.append(k, JSON.stringify(v));
          } else {
            fd.append(k, v);
          }
        });
        fd.append("mcp_file", codeFile, codeFile.name || "upload");
        sendPayload = fd;
      }
      let response;
      try {
        response = await updateServer(id, sendPayload);
      } catch (apiErr) {
        const extracted = handleApiError(apiErr, { context: "AddServer.handleUpdate.api" });
        safeSetError(extracted?.userMessage || extracted?.message || "Update failed");
        throw apiErr; // abort further success logic
      }
      const ok = response && (response?.status === "success" || response?.is_update === true || response?.is_updated === true);
      if (ok) {
        // ============ STAY IN UPDATE MODE AFTER SUCCESSFUL UPDATE ============
        const serverId = id || currentServerData?.id || currentServerData?.tool_id;

        if (serverId) {
          const success = await refreshServerDataAndStayOpen(serverId, "updated");
          if (success) {
            return; // Stay in update mode with refreshed data
          }
        }

        // Fallback: Show success message
        const msg = response?.message || "Server updated successfully!";
        addMessage(msg, "success");

        try {
          if (typeof setRefreshPaginated === "function") setRefreshPaginated();
        } catch (e) {
          console.debug("[AddServer] setRefreshPaginated failed", e);
        }

        setSubmitting(false);
      } else {
        // Handle validation errors just like ToolOnBoarding
        const permissionDenied = /permission denied|only the admin|only the tool's creator/i.test(response?.detail || response?.message || "");
        if (response?.message?.includes("Verification failed:")) {
          safeSetError(response.message);
        } else if (permissionDenied) {
          const msg = response?.detail || response?.message || "Permission denied";
          handleError(new Error(msg), { customMessage: msg, context: "AddServer.handleUpdate.permission" });
          safeSetError(msg);
        } else if (response?.status && response?.response?.status !== 200) {
          const msg = response?.response?.data?.detail || response?.detail || response?.message || "Update failed";
          safeSetError(msg);
        } else {
          safeSetError(response?.detail || response?.message || "Update failed");
        }
      }
    } catch (err) {
      if (!error) {
        safeSetError(err?.standardizedMessage || err?.message || err || "Update failed");
      }
    } finally {
      setSubmitting(false);
    }
  };

  const handleCancel = (e) => {
    if (e && typeof e.preventDefault === "function") {
      try {
        e.preventDefault();
        e.stopPropagation();
      } catch (err) { }
    }
    try {
      if (typeof onClose === "function") {
        onClose();
        return;
      }
    } catch (err) {
      console.debug("[AddServer] handleCancel: onClose threw", err);
    }
    try {
      const trySelectors = [
        "button.closeBtn",
        'button[aria-label="Close"]',
        'button[aria-label="Cancel"]',
        'button[aria-label="close"]',
        'button[aria-label="cancel"]',
        ".modalOverlay button",
        ".modalDrawerRight button",
      ];
      for (const sel of trySelectors) {
        const btn = document.querySelector(sel);
        if (btn) {
          btn.click();
          return;
        }
      }

      const allButtons = Array.from(document.querySelectorAll("button"));
      const fuzzy = allButtons.find((b) => {
        const txt = (b.textContent || "").trim();
        return txt === "×" || /close/i.test(txt);
      });
      if (fuzzy) {
        fuzzy.click();
        return;
      }

      // final fallback: notify global listeners
      window.dispatchEvent(new CustomEvent("AddServer:CloseRequested"));
    } catch (err) {
      console.debug("[AddServer] handleCancel fallback error", err);
    }
  };

  React.useEffect(() => {
    if (!isUpdateMode || !currentServerData) return;
    if (prefillDoneRef.current) return;

    setLoadingEndpoints(true);
    prefillDoneRef.current = true;
    const serverData = currentServerData;
    const raw = serverData.raw || serverData || {};
    const rawTags = serverData.tags || raw.tags || serverData.tag_ids || raw.tag_ids || [];

    // Defensive fallback for missing fields
    const incomingType = (serverData.mcp_type || raw.mcp_type || serverData.type || raw.type || "code").toString().toLowerCase();
    let mappedType = "code";
    if (incomingType.includes("url") || incomingType.includes("remote") || incomingType === "active") mappedType = "active";
    else if (incomingType.includes("module") || incomingType === "external") mappedType = "external";
    else mappedType = "code";

    setServerType(mappedType);
    setServerName(serverData.name || serverData.tool_name || raw.tool_name || "");
    setModuleName(
      (serverData.mcp_config && Array.isArray(serverData.mcp_config.args) && serverData.mcp_config.args.length > 1 ? serverData.mcp_config.args[1] : "") ||
      (raw.mcp_config && Array.isArray(raw.mcp_config.args) && raw.mcp_config.args.length > 1 ? raw.mcp_config.args[1] : "") ||
      "",
    );
    setDescription(serverData.description || serverData.tool_description || raw.tool_description || "");
    setSelectedTeam(serverData.team_id || raw.team_id || "");

    // Prefill is_public and shared_with_departments
    const serverIsPublic = serverData.is_public === true || raw.is_public === true;
    setIsPublic(serverIsPublic);
    const serverDepartments = serverData.shared_with_departments || raw.shared_with_departments || [];
    setSharedDepartments(serverDepartments);
    previousDepartmentsRef.current = serverDepartments;

    // small helper to normalize args[1] or other string candidates
    const normalizeCandidate = (c) => {
      if (typeof c !== "string" && typeof c !== "number") return c;
      let v = c.toString();
      try {
        if (v.startsWith("-c ")) v = v.slice(3);
        v = v.replace(/\\n/g, "\n").replace(/\\"/g, '"');
        if ((v.startsWith('"') && v.endsWith('"')) || (v.startsWith("'") && v.endsWith("'"))) {
          v = v.slice(1, -1);
        }
        const trimmed = v.trim();
        if ((trimmed.startsWith("{") && trimmed.endsWith("}")) || (trimmed.startsWith("[") && trimmed.endsWith("]")) || (trimmed.startsWith('"') && trimmed.endsWith('"'))) {
          try {
            const parsed = JSON.parse(trimmed);
            if (typeof parsed === "string") return parsed;
            if (typeof parsed === "object") return JSON.stringify(parsed, null, 2);
            return String(parsed);
          } catch (e) { }
        }
      } catch (e) { }
      return v;
    };

    if (mappedType === "active") {
      const endpointCandidates = [raw.mcp_url, raw.mcp_config && raw.mcp_config.url, raw.endpoint, serverData.endpoint, raw.mcp_config && raw.mcp_config.mcp_url];
      const ep = endpointCandidates.find((c) => typeof c === "string" && c.trim().length > 0) || "";
      setEndpoint(ep);
      setCodeFile(null);
      setCodeContent("");
      // Patch: Extract vaultValue from mcp_config.headers.Authorization
      let vaultFromHeader = "";
      // Check all possible locations for the Authorization header
      const headers = (raw.mcp_config && raw.mcp_config.headers) || (serverData.mcp_config && serverData.mcp_config.headers) || serverData.headers || raw.headers;

      // Check both Authorization and authorization fields
      if (headers) {
        const authHeader = headers.Authorization || headers.authorization;
        if (typeof authHeader === "string") {
          if (authHeader.startsWith("VAULT::")) {
            vaultFromHeader = authHeader.replace("VAULT::", "");
          } else {
            vaultFromHeader = authHeader;
          }
        }
      }

      // Set vault value and ensure vaultOptions contains this value
      if (vaultFromHeader) {
        setVaultValue(vaultFromHeader);
        // Ensure vaultOptions includes this value if not already present
        setVaultOptions((prevOptions) => {
          const hasValue = prevOptions.some((opt) => opt.value === vaultFromHeader);
          if (!hasValue) {
            return [...prevOptions, { label: vaultFromHeader, value: vaultFromHeader }];
          }
          return prevOptions;
        });
      }
    } else if (mappedType === "code") {
      const codeCandidates = [
        raw.mcp_config && raw?.mcp_config?.args?.[1],
        raw.mcp_file && raw.mcp_file.code_content,
        raw.mcp_config && raw.mcp_config.file && raw.mcp_config.file.content,
        raw.file && raw.file.content,
        raw.code_content,
        raw.code,
        raw.script,
        serverData.codeContent,
        serverData.code_content,
      ];
      const code = codeCandidates.map((c) => (typeof c === "string" ? normalizeCandidate(c) : c)).find((c) => typeof c === "string" && c.trim().length > 0) || "";
      setCodeContent(code);
      setCodeFile(null);
      setEndpoint("");
    } else if (mappedType === "external") {
      setCommand(serverData.command || raw.command || "python");
      // Patch: Try all possible sources for externalArgs
      setExternalArgs(
        serverData.externalArgs || raw.externalArgs || raw.args || (raw.mcp_config && raw.mcp_config.args && (raw.mcp_config.args[2] || raw.mcp_config.args[1])) || "",
      );
      setModuleName(
        (serverData.mcp_config && Array.isArray(serverData.mcp_config.args) && serverData.mcp_config.args.length > 1 ? serverData.mcp_config.args[1] : "") ||
        (raw.mcp_config && Array.isArray(raw.mcp_config.args) && raw.mcp_config.args.length > 1 ? raw.mcp_config.args[1] : "") ||
        "",
      );
      setDescription(serverData.description || serverData.tool_description || raw.tool_description || "");
      setServerName(serverData.name || serverData.tool_name || raw.tool_name || "");
      setSelectedTeam(serverData.team_id || raw.team_id || "");
      setEndpoint(raw.mcp_url || serverData.endpoint || "");
      setCodeFile(null);
      setCodeContent(raw.code_content || serverData.codeContent || "");
    }

    // Initialize selectedTagsForSelector for edit mode
    if (Array.isArray(rawTags) && rawTags.length > 0) {
      const tagsForSelector = rawTags
        .map((t) => {
          if (typeof t === "object" && t !== null) {
            return {
              tag_name: t.tag_name || t.tag || t.name || "",
              tag_id: t.tag_id || t.id || t.tagId || "",
              tagId: t.tag_id || t.id || t.tagId || "",
            };
          }
          return null;
        })
        .filter(Boolean);
      setSelectedTagsForSelector(tagsForSelector);

      // Cache the general tag for auto-add behavior
      const generalInTags = tagsForSelector.find((tag) => tag.tag_name.toLowerCase() === "general");
      if (generalInTags) {
        generalTagRef.current = generalInTags;
        setNonRemovableTags([generalInTags]);
      }
    } else {
      console.log("[AddServer] No tags to set. rawTags:", rawTags);
    }

    // Turn off loading state after all initialization is complete
    setLoadingEndpoints(false);
  }, [isUpdateMode, currentServerData]);

  const renderTeamSelector = () => {
    if (isAdmin) {
      return null;
    }
    if (userTeams.length) {
      return (
        <div className="formGroup">
          <NewCommonDropdown
            label="Select Team ID"
            options={teamOptions.map((opt) => opt.label)}
            selected={teamOptions.find((opt) => opt.value === selectedTeam)?.label || ""}
            onSelect={(label) => {
              const found = teamOptions.find((opt) => opt.label === label);
              setSelectedTeam(found ? found.value : "");
            }}
            placeholder="-- Choose --"
            width={260}
            disabled={isReadOnly}
          />
        </div>
      );
    }
    return (
      <div className="formGroup">
        <div className={styles["warn-msg"]}>No teams assigned. Contact an admin.</div>
      </div>
    );
  };

  const renderActiveSection = () => (
    <div className="formSection">
      <div className={styles.configRow}>
        <div className="formGroup" style={{ flex: '0 0 30%' }}>
          <NewCommonDropdown
            label="Header"
            options={vaultOptions.map((option) => option.label)}
            selected={vaultValue ? vaultOptions.find((option) => option.value === vaultValue)?.label || vaultValue : ""}
            onSelect={(label) => {
              const found = vaultOptions.find((option) => option.label === label);
              setVaultValue(found ? found.value : "");
            }}
            placeholder="Select Header"
            style={{
              ...dropdownCommonStyle,
              background: isReadOnly ? "#f3f4f6" : "#fafbfc",
              borderColor: isReadOnly ? "#e5e7eb" : "#1976d2",
              color: isReadOnly ? "#6b7280" : "#222",
              cursor: isReadOnly ? "not-allowed" : "pointer",
            }}
            disabled={isReadOnly}
          />
        </div>
        <div className="formGroup" style={{ flex: 1 }}>
          <label className={"label-desc"} htmlFor="endpoint">
            Endpoint URL <span className="required">*</span>
          </label>
          <input
            id="endpoint"
            className="input"
            value={endpoint}
            onChange={(e) => setEndpoint(e.target.value)}
            placeholder="Http://Localhost:5000/Mcp"
            aria-label="Endpoint URL"
            disabled={isReadOnly}
            readOnly={isReadOnly}
          />
        </div>
      </div>
    </div>
  );

  const renderExternalSection = () => (
    <div className="formSection">
      <div className={styles.configRow}>
        <div className="formGroup" style={{ flex: '0 0 30%' }}>
          <NewCommonDropdown
            label="Command"
            options={["python"]}
            selected={command}
            onSelect={() => setCommand("python")}
            placeholder="python"
            style={dropdownCommonStyle}
            disabled={isReadOnly}
          />
        </div>
        <div className="formGroup" style={{ flex: 1 }}>
          <label className={"label-desc"} htmlFor="moduleName">
            Module Name <span className="required">*</span>
          </label>
          <input
            id="moduleName"
            className="input"
            value={moduleName}
            onChange={(e) => setModuleName(e.target.value)}
            placeholder="Enter MCP Module Name"
            aria-label="Module Name"
            required
            disabled={isReadOnly}
            readOnly={isReadOnly}
          />
        </div>
      </div>
    </div>
  );

  const handleCopy = async (key, text) => {
    const success = await copyToClipboard(text);
    if (success) {
      setCopiedStates((prev) => ({ ...prev, [key]: true }));
      setTimeout(() => {
        setCopiedStates((prev) => ({ ...prev, [key]: false }));
      }, 2000);
    } else {
      console.error("Failed to copy text to clipboard");
    }
  };
  const handleZoomClick = (title, content) => {
    setPopupTitle(title);
    setPopupContent(content || "");
    setShowZoomPopup(true);
  };

  const handleZoomSave = (updatedContent) => {
    if (popupTitle === "Code Snippet") {
      if (!updatedContent.trim()) {
        addMessage("Please enter valid code before proceeding", "error");
        return;
      }
      setCodeContent(updatedContent);
    }
    setShowZoomPopup(false);
  };

  // --- Executor Panel (new simplified integration) ---
  const [showExecutorPanel, setShowExecutorPanel] = useState(false);
  const [executeTrigger, setExecuteTrigger] = useState(0); // bump to re-introspect / re-run

  const handlePlayClick = () => {
    // For file uploads, we need to prevent execution and show error
    if (codeFile) {
      addMessage("Please provide valid code to run", "error");
      setShowPopup(true); // Ensure the message popup is shown
      return;
    }

    // Check for valid code content in the editor
    if (!codeContent.trim()) {
      addMessage("Please provide valid code to run", "error");
      setShowPopup(true);
      return;
    }

    // Only proceed with execution if we have code in the editor
    if (!showExecutorPanel) {
      setShowExecutorPanel(true); // ExecutorPanel will auto-introspect (autoExecute)
    } else {
      setExecuteTrigger((c) => c + 1); // force re-run / re-introspect
    }
  };

  const renderCodeSection = () => (
    <div className="formGroup">
      <div className={styles.codeEditorWrapper}>
        <CodeEditor
          codeToDisplay={codeContent}
          onChange={(value) => setCodeContent(value)}
          readOnly={isReadOnly}
          enableDragDrop={isCreateMode && !isReadOnly}
          acceptedFileTypes={['.py']}
          showUploadButton={isCreateMode && !isReadOnly}
          showHelperText={isCreateMode && !isReadOnly}
          helperText="(drag & drop / upload .py file / type directly)"
          label="Code Snippet"
          onLabelClick={() => {
            const editor = document.querySelector(".ace_editor .ace_text-input");
            if (editor) editor.focus();
          }}
          onFileLoad={(content, file) => {
            setCodeFile(file);
            setCodeContent(content);
            addMessage(`Loaded ${file.name} successfully`, "success");
          }}
        />
        {!isReadOnly && (
          <button
            type="button"
            className={styles.copyIcon}
            onClick={() => handleCopy("code-snippet", codeContent)}
            title="Copy"
            disabled={!codeContent || codeContent.trim() === ""}
            style={{ opacity: !codeContent || codeContent.trim() === "" ? 0.4 : 1, cursor: !codeContent || codeContent.trim() === "" ? "not-allowed" : "pointer" }}>
            <SVGIcons icon="fa-regular fa-copy" width={16} height={16} fill="var(--icon-color)" />
          </button>
        )}
        <button type="button" className={styles.playIcon} onClick={handlePlayClick} title="Run Code" style={{ display: isReadOnly ? "none" : undefined }}>
          <SVGIcons icon="lucide-play" width={16} height={16} stroke="var(--icon-color)" fill="none" />
        </button>
        <button type="button" className={styles.infoIcon} onClick={(e) => { e.stopPropagation(); setShowAccessControlInfo(true); }} title="Access Control Guide" style={{ display: isReadOnly ? "none" : undefined }}>
          <SVGIcons icon="info-modern" width={16} height={16} />
        </button>
        {!isReadOnly && (
          <div className={styles.iconGroup}>
            <button type="button" className={styles.expandIcon} onClick={() => handleZoomClick("Code Snippet", codeContent)} title="Expand">
              <SVGIcons icon="fa-solid fa-up-right-and-down-left-from-center" width={16} height={16} fill="var(--icon-color)" />
            </button>
          </div>
        )}
        <span className={`${styles.copiedText} ${copiedStates["code-snippet"] ? styles.visible : styles.hidden}`}>Text Copied!</span>
      </div>
      <ZoomPopup
        show={showZoomPopup}
        onClose={() => setShowZoomPopup(false)}
        title={popupTitle}
        content={popupContent}
        onSave={handleZoomSave}
        type={popupTitle === "Code Snippet" ? "code" : "text"}
        readOnly={isReadOnly || (popupTitle === "Code Snippet" && Boolean(codeFile))}
      />
    </div>
  );

  // Helper to format error objects for display
  const formatErrorMessage = (err) => {
    if (!err) return "";
    if (typeof err === "string") return err;
    if (Array.isArray(err)) {
      return err.map(formatErrorMessage).join("; ");
    }
    if (typeof err === "object") {
      // FastAPI validation error format: {type, loc, msg, input}
      if (err.msg) return err.msg;
      if (err.detail) return err.detail;
      if (err.message) return err.message;
      // If it's a list of errors
      if (err.errors && Array.isArray(err.errors)) {
        return err.errors.map(formatErrorMessage).join("; ");
      }
      // Fallback: show keys and values
      return Object.values(err).map(formatErrorMessage).join("; ");
    }
    return String(err);
  };

  // Utility: Render validation content (output/error)
  // Onclik of play button while validating the server code snippet the result might be in any form , hence below function will be needed
  // const renderValidationContent = (data) => {
  //   if (typeof data === "object") {
  //     return <pre style={{ margin: 0, whiteSpace: "pre-wrap", fontFamily: "inherit" }}>{JSON.stringify(data, null, 2)}</pre>;
  //   }
  //   return <pre style={{ margin: 0, whiteSpace: "pre-wrap", fontFamily: "inherit" }}>{data}</pre>;
  // };

  // Removed all legacy execution state (toolList, tool params, validation result etc.)

  // Common dropdown style for all NewCommonDropdown usages
  const dropdownCommonStyle = {
    width: "260px",
    zIndex: 1000,
    borderRadius: "8px",
    border: "2px solid #1976d2",
    background: "#fafbfc",
    color: "#222",
    fontWeight: 500,
    fontSize: "15px",
    boxShadow: "0 2px 8px rgba(25,118,210,0.08)",
    padding: "8px 12px",
    marginTop: "6px",
  };

  // ============ Get Header Info ============
  const getHeaderInfo = () => {
    const info = [];
    if (isUpdateMode) {
      info.push({
        label: "Server Type",
        value: serverType === "active" ? "Remote" : serverType === "code" ? "Local" : serverType === "external" ? "External" : "—",
      });
    }
    info.push({
      label: "Created By",
      value: isUpdateMode ? (currentServerData?.created_by || userName) : userName,
    });
    return info;
  };

  // ============ Render Footer ============
  const renderFooter = () => {
    // Recycle mode - show Restore and Delete buttons
    if (recycle) {
      return (
        <>
          <IAFButton type="secondary" onClick={deleteServerPermanently} aria-label="Delete" disabled={submitting}>
            {submitting ? "Deleting..." : "Delete"}
          </IAFButton>
          <IAFButton type="primary" onClick={restoreServer} aria-label="Restore Server" disabled={submitting}>
            {submitting ? "Restoring..." : "Restore"}
          </IAFButton>
        </>
      );
    }

    // Normal mode - show Cancel and Add/Update buttons
    // ReadOnly mode - hide toggles and show only Close button
    return (
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", width: "100%", gap: "16px" }}>
        {/* Left side: Toggle - On/Off style (hidden in readOnly mode) */}
        {!readOnlyProp && (
        <div style={{ display: "flex", alignItems: "center", gap: "10px", flex: 1, minWidth: 0, overflowX: "auto", overflowY: "hidden", paddingBottom: "4px", scrollbarWidth: "thin" }}>
          <span style={{ fontSize: "13px", color: "var(--content-color)", whiteSpace: "nowrap", flexShrink: 0 }}>
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
          <span style={{
            fontSize: "12px",
            color: isPublic ? "#37acea" : "var(--muted)",
            fontWeight: isPublic ? "600" : "400",
            minWidth: "28px",
            flexShrink: 0
          }}>
            {isPublic ? "ON" : "OFF"}
          </span>
        </div>
        )}
        {/* Right side: Buttons */}
        <div style={{ display: "flex", gap: "12px", flexShrink: 0, marginLeft: readOnlyProp ? "auto" : undefined }}>
          {readOnlyProp ? (
            <IAFButton type="secondary" onClick={handleCancel} aria-label="Close">
              Close
            </IAFButton>
          ) : (
            <>
              <IAFButton type="secondary" onClick={handleCancel} aria-label="Cancel" disabled={submitting}>
                Cancel
              </IAFButton>
              <IAFButton
                type="primary"
                onClick={() => {
                  const form = document.querySelector('form[class*="form-section"]');
                  if (form) form.requestSubmit();
                }}
                aria-label={isUpdateMode ? "Update Server" : "Add Server"}
                disabled={submitting}>
                {isUpdateMode ? "Update Server" : "Add Server"}
              </IAFButton>
            </>
          )}
        </div>
      </div>
    );
  };

  // ============ Render Side Panel (Executor) ============
  const renderSidePanel = () => {
    if (!(serverType === "code" && showExecutorPanel && !codeFile)) return null;
    return <ExecutorPanel code={codeContent} autoExecute={true} executeTrigger={executeTrigger} onClose={() => setShowExecutorPanel(false)} mode="server" />;
  };

  const showSplitLayout = serverType === "code" && showExecutorPanel;

  return (
    <>
      <DeleteModal show={updateModal} onClose={() => setUpdateModal(false)}>
        <p>You are not authorized to update a server. Please login with registered email.</p>
        <div className={styles.buttonContainer}>
          <button onClick={(e) => handleLoginButton(e)} className={styles.loginBtn}>
            Login
          </button>
          <button onClick={() => setUpdateModal(false)} className={styles.cancelBtn}>
            Cancel
          </button>
        </div>
      </DeleteModal>{" "}
      <FullModal
        isOpen={true}
        onClose={handleCancel}
        title={isUpdateMode ? serverName : "Add Server"}
        headerInfo={getHeaderInfo()}
        footer={readOnlyProp ? null : renderFooter()}
        loading={submitting || loadingEndpoints}
        splitLayout={showSplitLayout}
        sidePanel={renderSidePanel()}
        splitHeaderLabels={showSplitLayout ? { left: "Configuration", right: "Execution" } : null}>
        <form onSubmit={isUpdateMode ? handleUpdate : handleSubmit} className={"form-section"} aria-label={isUpdateMode ? "Update Server Form" : "Add Server Form"}>
          <div className="formContent">
            <div className="form">
              {isCreateMode && (
                <div className="gridTwoCol">
                  <div className="formGroup">
                    <NewCommonDropdown
                      options={["External", "Local", "Remote"]}
                      label="Server Type"
                      required={true}
                      selected={
                        isUpdateMode
                          ? serverType === "active"
                            ? "Remote"
                            : serverType === "code"
                              ? "Local"
                              : serverType === "external"
                                ? "External"
                                : ""
                          : serverType === "active"
                            ? "Remote"
                            : serverType === "code"
                              ? "Local"
                              : serverType === "external"
                                ? "External"
                                : ""
                      }
                      onSelect={(label) => {
                        if (isUpdateMode) return;
                        let val = "code";
                        if (label === "Remote") val = "active";
                        else if (label === "External") val = "external";
                        setServerType(val);
                        setEndpoint("");
                        setCodeFile(null);
                        setCodeContent("");
                        setError("");
                      }}
                      placeholder="-- Select --"
                      style={{
                        ...dropdownCommonStyle,
                        background: isUpdateMode ? "#f3f4f6" : "#fafbfc",
                        borderColor: isUpdateMode ? "#e5e7eb" : "#1976d2",
                        color: isUpdateMode ? "#6b7280" : "#222",
                        cursor: isUpdateMode ? "not-allowed" : "pointer",
                      }}
                      disabled={isUpdateMode || isReadOnly}
                    />
                  </div>

                  <div className="formGroup">
                    <label className={"label-desc"} htmlFor="serverName">
                      Server Name <span className="required">*</span>
                    </label>
                    <input
                      id="serverName"
                      className="input"
                      value={serverName}
                      onChange={(e) => setServerName(e.target.value)}
                      disabled={editMode || isReadOnly}
                      readOnly={isReadOnly}
                      placeholder={serverType === "external" ? "Enter MCP Module Name" : "Enter Server Name"}
                      aria-label={serverType === "external" ? "Module Name" : "Server Name"}
                      required
                    />
                  </div>
                </div>
              )}
              <div className="formGroup">
                <TextareaWithActions
                  name="description"
                  value={description}
                  onChange={(e) => setDescription(e.target.value)}
                  label="Description"
                  required={true}
                  rows={3}
                  placeholder={serverType === "external" ? "Describe Your Module" : "Describe Your Server"}
                  onZoomSave={(updatedContent) => setDescription(updatedContent)}
                  disabled={isReadOnly}
                  readOnly={isReadOnly}
                />
              </div>
              {renderTeamSelector()}
              {serverType === "code" && <div>{renderCodeSection()}</div>}
              {serverType === "active" && renderActiveSection()}
              {serverType === "external" && renderExternalSection()}

              {/* Configuration Section - Tags & Departments */}
              <div className="formSection">
                <div className={styles.configRow}>
                  {/* Tags Section */}
                  <TagSelector selectedTags={selectedTagsForSelector} onTagsChange={handleTagsChange} nonRemovableTags={nonRemovableTags} disabled={isReadOnly} />
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
            </div >
          </div >
        </form >
      </FullModal >

      {/* Access Control Guide Modal */}
      < AccessControlGuide
        isOpen={showAccessControlInfo}
        onClose={() => setShowAccessControlInfo(false)
        }
      />
    </>
  );
}
