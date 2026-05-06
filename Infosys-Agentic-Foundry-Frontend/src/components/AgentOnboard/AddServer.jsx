import React, { useState, useEffect, useRef } from "react";
import ReactDOM from "react-dom";
import NewCommonDropdown from "../commonComponents/NewCommonDropdown";
import styles from "../../css_modules/ToolOnboarding.module.css";
import { useToolsAgentsService } from "../../services/toolService";
import { copyToClipboard } from "../../utils/clipboardUtils";
import { getRoleFromToken, getEmailFromToken, getUserNameFromToken } from "../../utils/jwtUtils";
import SVGIcons from "../../Icons/SVGIcons.js";
import ZoomPopup from "../commonComponents/ZoomPopup.jsx";
import { useMcpServerService } from "../../services/serverService";
import { useMessage } from "../../Hooks/MessageContext";
import TagSelector from "../commonComponents/TagSelector/TagSelector.jsx";
import useFetch from "../../Hooks/useAxios.js";
import { APIs } from "../../constant";
import { useErrorHandler } from "../../Hooks/useErrorHandler";
import ExecutorPanel from "../commonComponents/ExecutorPanel";
import Loader from "../commonComponents/Loader.jsx";
import CodeEditor from "../commonComponents/CodeEditor.jsx";
import DeleteModal from "../commonComponents/DeleteModal.jsx";
import { useAuth } from "../../context/AuthContext";
import { usePermissions } from "../../context/PermissionsContext";
import ConfirmationModal from "../commonComponents/ToastMessages/ConfirmationPopup";
import IAFButton from "../../iafComponents/GlobalComponents/Buttons/Button";
import UploadBox from "../commonComponents/UploadBox.jsx";
import TextareaWithActions from "../commonComponents/TextareaWithActions";
import { FullModal } from "../../iafComponents/GlobalComponents/FullModal";
import AccessControlGuide from "../commonComponents/AccessControlGuide";
import { encodePassword } from "../../utils/encodeUtils";

export default function AddServer({ editMode = false, serverData = null, onClose, setRefreshPaginated = () => { }, recycle = false, setRestoreData = () => { }, readOnly = false }) {
  const { addServer } = useToolsAgentsService();
  const { postData, deleteData, fetchData } = useFetch();
  const { getAllServers, updateServer, updateRemoteMcpUrl, updateModuleConfig, getServerById, deleteServer: deleteServerService } = useMcpServerService();
  const user = { isAdmin: true, teams: ["dev", "ops"], team_ids: ["dev", "ops"] };
  const isAdmin = Boolean(user && (user.isAdmin || user.is_admin));
  const userTeams = user?.teams || user?.team_ids || [];

  const { hasPermission } = usePermissions();
  const canDeleteServers = typeof hasPermission === "function" ? hasPermission("delete_access.mcp_servers") : false;

  // Combine recycle and readOnly props into a single flag for disabling form fields
  const isReadOnly = recycle || Boolean(readOnly);

  // ============ State for Dynamic Mode Management ============
  const [currentMode, setCurrentMode] = useState(editMode ? "update" : "create");
  const [currentServerData, setCurrentServerData] = useState(serverData);

  // Derived state for mode checking (matching ToolOnBoarding pattern)
  const isCreateMode = currentMode === "create";
  const isUpdateMode = currentMode === "update";
  // Derived server data: state first (updated after create), then prop (passed from parent on edit)
  const effectiveServerData = currentServerData || serverData || {};

  const [showDeleteConfirm, setShowDeleteConfirm] = useState(false);
  const [serverRestoreConflict, setServerRestoreConflict] = useState(null);
  const [serverRestoreNewName, setServerRestoreNewName] = useState("");
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
  const [showRemoteMcpHelp, setShowRemoteMcpHelp] = useState(false);
  const { addMessage, setShowPopup } = useMessage();
  const { handleApiError, handleError } = useErrorHandler();
  const userName = getUserNameFromToken();
  const creatorEmail =
    (effectiveServerData &&
      (effectiveServerData.created_by || effectiveServerData.user_email_id || effectiveServerData.createdBy || (effectiveServerData.raw && (effectiveServerData.raw.created_by || effectiveServerData.raw.user_email_id)))) ||
    getEmailFromToken() ||
    getUserNameFromToken() ||
    "";

  const teamOptions = userTeams.map((t) => ({ label: t, value: t }));

  const prefillDoneRef = useRef(null); // Stores server ID after prefill, null when not prefilled

  // Sync currentServerData when serverData prop changes (e.g., after API fetch on card click)
  useEffect(() => {
    if (serverData && Object.keys(serverData).length > 0) {
      setCurrentServerData(serverData);
      setCurrentMode("update");
      prefillDoneRef.current = null; // Reset to allow prefill for new server
    }
  }, [serverData]);

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

  const [command, setCommand] = useState("python");
  const [externalArgs, setExternalArgs] = useState("");

  const [vaultValue, setVaultValue] = useState("");
  const [vaultOptions, setVaultOptions] = useState([]);
  const [headerRows, setHeaderRows] = useState([{ name: "", value: "" }]);
  const [showHeadersSection, setShowHeadersSection] = useState(false);
  const [headersError, setHeadersError] = useState("");
  const [updateModal, setUpdateModal] = useState(false);
  const [loadingEndpoints, setLoadingEndpoints] = useState(false);
  const { logout } = useAuth();
  const handleLoginButton = (e) => {
    e.preventDefault();
    logout("/login");
  };

  const serverIdForPrefill = effectiveServerData?.id || effectiveServerData?.tool_id || null;
  useEffect(() => {
    prefillDoneRef.current = null; // Reset to allow prefill
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

  useEffect(() => {
    if (serverType !== "active") return;

    const loadVaultOptions = async () => {
      setLoadingEndpoints(true);
      try {
        const payload = { user_email: getEmailFromToken() };
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
  const restoreServer = async (overrideName) => {
    setSubmitting(true);
    try {
      const serverId = serverData?.tool_id || serverData?.id;
      let url = `${APIs.RESTORE_SERVERS}${serverId}?user_email_id=${encodeURIComponent(getEmailFromToken())}`;
      const nameToUse = overrideName || serverRestoreNewName.trim();
      if (nameToUse) url += `&new_name=${encodeURIComponent(nameToUse)}`;
      const response = await postData(url, undefined, { silent: true });
      setServerRestoreNewName("");
      if (response?.is_restored) {
        addMessage(response?.message || "Server restored successfully", "success");
        setRestoreData(response);
        onClose();
      } else {
        addMessage(response?.message || "Failed to restore server", "error");
      }
    } catch (error) {
      handleApiError(error, { context: "AddServer.restoreServer" });
      const detail = error?.response?.data?.detail;
      if (detail?.name_conflict) {
        setServerRestoreConflict(detail);
      } else {
        const errMsg = typeof detail === "string" ? detail : detail?.message || error?.message || "Failed to restore server";
        addMessage(errMsg, "error");
      }
    } finally {
      setSubmitting(false);
    }
  };

  const handleDeleteServerFromModal = async () => {
    const serverId = effectiveServerData?.tool_id || effectiveServerData?.id || serverData?.tool_id || serverData?.id;
    if (!serverId) return;

    const isAdmin = getRoleFromToken().toLowerCase() === "admin";
    const emailId = getEmailFromToken();

    const data = {
      user_email_id: emailId,
      is_admin: isAdmin,
    };

    try {
      setSubmitting(true);
      const response = await deleteServerService(data, serverId);

      if (response && typeof response !== "string") {
        const statusMsg = response.status_message || response.message;
        if (statusMsg) {
          const hasAnyFailure = Array.isArray(response.results) && response.results.some((r) => r.is_delete === false);
          addMessage(statusMsg, hasAnyFailure ? "error" : "success");
        }
      }

      setShowDeleteConfirm(false);
      setSubmitting(false);
      onClose();
      setRefreshPaginated((prev) => !prev);
    } catch (e) {
      console.error("Delete server error:", e);
      addMessage("Failed to delete server", "error");
      setSubmitting(false);
      setShowDeleteConfirm(false);
    }
  };

  const deleteServerPermanently = async () => {
    setSubmitting(true);
    try {
      const serverId = serverData?.tool_id || serverData?.id;
      const url = `${APIs.DELETE_SERVERS_PERMANENTLY}${serverId}?user_email_id=${encodeURIComponent(getEmailFromToken())}`;
      const response = await deleteData(url);
      if (response?.is_delete) {
        const statusMsg = response?.status_message || response?.message;
        if (statusMsg) addMessage(statusMsg, "success");
        setRestoreData(response);
        onClose();
      } else {
        const statusMsg = response?.status_message || response?.message;
        if (statusMsg) addMessage(statusMsg, "error");
      }
    } catch (error) {
      handleApiError(error, { context: "AddServer.deleteServerPermanently" });
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
      // Validate header rows (optional — skip fully empty rows)
      for (const row of headerRows) {
        const hasName = row.name.trim().length > 0;
        const hasValue = row.value.trim().length > 0;
        if (hasName && !hasValue) return `Header "${row.name}" is missing a value.`;
        if (!hasName && hasValue) return "A header row has a value but no header name.";
      }
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
        prefillDoneRef.current = null; // Reset to allow prefill for new server

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
          const endpointCandidates = [raw.mcp_url, raw.mcp_config && raw.mcp_config.url, server.endpoint, raw.endpoint, raw.mcp_config && raw.mcp_config.mcp_url];
          const ep = endpointCandidates.find((c) => typeof c === "string" && c.trim().length > 0) || "";
          setEndpoint(ep);
          // Extract vaultValue from mcp_config.headers.Authorization
          const headers = (raw.mcp_config && raw.mcp_config.headers) || (server.mcp_config && server.mcp_config.headers) || server.headers || raw.headers;
          if (headers) {
            const authHeader = headers.Authorization || headers.authorization;
            if (typeof authHeader === "string" && authHeader.startsWith("VAULT::")) {
              const vaultFromHeader = authHeader.replace("VAULT::", "");
              if (vaultFromHeader) {
                setVaultValue(vaultFromHeader);
                setVaultOptions((prevOptions) => {
                  const hasValue = prevOptions.some((opt) => opt.value === vaultFromHeader);
                  if (!hasValue) {
                    return [...prevOptions, { label: vaultFromHeader, value: vaultFromHeader }];
                  }
                  return prevOptions;
                });
              }
            }
            // Load non-vault-managed headers into header rows
            // Only exclude the exact vault-managed entry: key "Authorization" with VAULT:: prefix
            const nonAuthEntries = Object.entries(headers).filter(
              ([k, v]) => !(k === "Authorization" && typeof v === "string" && v.startsWith("VAULT::"))
            );
            if (nonAuthEntries.length > 0) {
              setHeaderRows(nonAuthEntries.map(([k, v]) => ({ name: k, value: String(v) })));
              setShowHeadersSection(true);
            } else {
              setHeaderRows([{ name: "", value: "" }]);
            }
          } else {
            setHeaderRows([{ name: "", value: "" }]);
          }
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
        created_by: getEmailFromToken() || "Guest",
        mcp_url: mcp_type === "url" ? endpoint.trim() : "",
        mcp_module_name: mcp_type === "module" ? moduleName.trim() : "",
        code_content: mcp_type === "file" && !codeFile ? encodePassword(codeContent.trim()) : "",
        mcp_file: mcp_type === "file" && codeFile ? codeFile : undefined,
        tag_ids: selectedTagIds,
        ...(serverType === "external" ? { mcp_command: command, externalArgs } : {}),
        ...(serverType === "active" && vaultValue ? { vault_id: vaultValue } : {}),
      };
      if (!payload.mcp_file) delete payload.mcp_file;
      // Build merged headers: vault Authorization + custom header rows for REMOTE (active) server
      if (serverType === "active") {
        const mergedHeaders = {};
        if (vaultValue && typeof vaultValue === "string" && vaultValue.trim().length > 0) {
          mergedHeaders.Authorization = `VAULT::${vaultValue}`;
        }
        for (const row of headerRows) {
          if (row.name.trim() && row.value.trim()) {
            mergedHeaders[row.name.trim()] = row.value.trim();
          }
        }
        if (Object.keys(mergedHeaders).length > 0) {
          payload.mcp_config = payload.mcp_config || {};
          payload.mcp_config.headers = mergedHeaders;
        }
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
        setHeaderRows([{ name: "", value: "" }]);
        setShowHeadersSection(false);
        setHeadersError("");

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
      const is_admin = getRoleFromToken().toLowerCase() === "admin";
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
          ? encodePassword(codeContent?.trim() || effectiveServerData?.codeContent || effectiveServerData?.code_content || (effectiveServerData?.raw && (effectiveServerData.raw.codeContent || effectiveServerData.raw.code_content)) || "")
          : "";
      const payload = {
        is_admin,
        tool_id: id,
        tool_name,
        tool_description,
        mcp_type,
        created_by: getEmailFromToken() || "Guest",
        user_email_id: getEmailFromToken() || "Guest",
        mcp_url,
        mcp_module_name,
        code_content,
        tag_ids: selectedTagIds,
        updated_tag_id_list: selectedTagIds,
        ...(serverType === "external" ? { mcp_command: command, externalArgs } : {}),
        ...(serverType === "active" && vaultValue ? { vault_id: vaultValue } : {}),
      };
      // --- Build merged headers for REMOTE (active) server ---
      if (serverType === "active") {
        const mergedHeaders = {};
        if (vaultValue && typeof vaultValue === "string" && vaultValue.trim().length > 0) {
          mergedHeaders.Authorization = `VAULT::${vaultValue}`;
        }
        for (const row of headerRows) {
          if (row.name.trim() && row.value.trim()) {
            mergedHeaders[row.name.trim()] = row.value.trim();
          }
        }
        if (Object.keys(mergedHeaders).length > 0) {
          payload.mcp_config = payload.mcp_config || {};
          payload.mcp_config.headers = mergedHeaders;
        }
        if (payload.vault_id) delete payload.vault_id;
      }
      if (selectedTeam) payload.team_id = selectedTeam;

      // Catalog remote MCP (`mcp_url_*`): dedicated URL / headers update (PUT .../update-remote-url/{tool_id})
      const isCatalogUrlMcp = /^mcp_url_/i.test(String(id));
      if (isUpdateMode && serverType === "active" && isCatalogUrlMcp) {
        const ed = effectiveServerData?.raw || effectiveServerData || {};
        const endpointCandidates = [
          ed.mcp_url,
          ed.mcp_config && ed.mcp_config.url,
          effectiveServerData.endpoint,
          ed.endpoint,
          ed.mcp_config && ed.mcp_config.mcp_url,
        ];
        const priorEndpoint = (endpointCandidates.find((c) => typeof c === "string" && c.trim().length > 0) || "").trim();
        const hdrs =
          (ed.mcp_config && ed.mcp_config.headers) ||
          (effectiveServerData.mcp_config && effectiveServerData.mcp_config.headers) ||
          effectiveServerData.headers ||
          ed.headers;
        let priorVault = "";
        if (hdrs) {
          const authHeader = hdrs.Authorization || hdrs.authorization;
          if (typeof authHeader === "string" && authHeader.startsWith("VAULT::")) {
            priorVault = authHeader.slice("VAULT::".length);
          }
        }
        priorVault = priorVault.trim();
        // Build prior custom headers object (all non-Authorization headers)
        const priorCustomObj = {};
        if (hdrs && typeof hdrs === "object") {
          for (const [k, v] of Object.entries(hdrs)) {
            // Only exclude the exact vault-managed entry
            if (!(k === "Authorization" && typeof v === "string" && v.startsWith("VAULT::"))) {
              priorCustomObj[k] = v;
            }
          }
        }
        // Build current custom headers object from rows
        const curCustomObj = {};
        for (const row of headerRows) {
          if (row.name.trim() && row.value.trim()) {
            curCustomObj[row.name.trim()] = row.value.trim();
          }
        }
        const curEp = (endpoint?.trim() || "").trim();
        const curVault = vaultValue && String(vaultValue).trim() ? String(vaultValue).trim() : "";
        const urlChanged = curEp !== priorEndpoint;
        const vaultChanged = curVault !== priorVault;
        const headersChanged = JSON.stringify(curCustomObj) !== JSON.stringify(priorCustomObj);
        if (urlChanged || vaultChanged || headersChanged) {
          if (urlChanged && !curEp) {
            safeSetError("Endpoint URL cannot be empty.");
            setSubmitting(false);
            return;
          }
          const remotePayload = {
            user_email_id: getEmailFromToken() || "Guest",
            is_admin,
          };
          if (urlChanged) remotePayload.mcp_url = curEp;
          if (vaultChanged || headersChanged) {
            const mergedHeaders = {};
            if (curVault) mergedHeaders.Authorization = `VAULT::${curVault}`;
            Object.assign(mergedHeaders, curCustomObj);
            remotePayload.headers = mergedHeaders;
          }
          let remoteRes;
          try {
            remoteRes = await updateRemoteMcpUrl(id, remotePayload);
          } catch (remoteErr) {
            const extracted = handleApiError(remoteErr, { context: "AddServer.handleUpdate.remoteUrl" });
            safeSetError(extracted?.userMessage || extracted?.message || "Failed to update remote MCP URL");
            setSubmitting(false);
            return;
          }
          const remoteOk =
            remoteRes &&
            (remoteRes?.status === "success" ||
              remoteRes?.is_update === true ||
              remoteRes?.is_updated === true ||
              remoteRes?.success === true);
          if (!remoteOk) {
            const msg =
              (typeof remoteRes === "string" && remoteRes) ||
              remoteRes?.detail ||
              remoteRes?.message ||
              "Failed to update remote MCP URL or headers";
            safeSetError(msg);
            setSubmitting(false);
            return;
          }
        }
      }

      // External (module) servers: update module name and command via dedicated endpoint
      if (isUpdateMode && serverType === "external") {
        const moduleConfigPayload = {
          is_admin,
          user_email_id: getEmailFromToken() || "Guest",
          mcp_module_name: moduleName?.trim() || "",
          mcp_command: command || "python",
        };
        try {
          const moduleRes = await updateModuleConfig(id, moduleConfigPayload);
          const moduleOk =
            moduleRes &&
            (moduleRes?.status === "success" ||
              moduleRes?.is_update === true ||
              moduleRes?.is_updated === true ||
              moduleRes?.success === true);
          if (!moduleOk) {
            const msg =
              (typeof moduleRes === "string" && moduleRes) ||
              moduleRes?.detail ||
              moduleRes?.message ||
              "Failed to update module configuration";
            safeSetError(msg);
            setSubmitting(false);
            return;
          }
        } catch (moduleErr) {
          const extracted = handleApiError(moduleErr, { context: "AddServer.handleUpdate.moduleConfig" });
          safeSetError(extracted?.userMessage || extracted?.message || "Failed to update module configuration");
          setSubmitting(false);
          return;
        }
      }

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

    // Use server ID to track if we've already prefilled this specific server
    const serverId = currentServerData?.tool_id || currentServerData?.id;
    const lastPrefillId = prefillDoneRef.current;
    if (lastPrefillId === serverId) return;

    setLoadingEndpoints(true);
    prefillDoneRef.current = serverId; // Store server ID instead of boolean
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
        if (typeof authHeader === "string" && authHeader.startsWith("VAULT::")) {
          vaultFromHeader = authHeader.replace("VAULT::", "");
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

      // Load non-vault-managed headers into header rows
      // Only exclude the exact vault-managed entry: key "Authorization" with VAULT:: prefix
      if (headers && typeof headers === "object") {
        const nonAuthEntries = Object.entries(headers).filter(
          ([k, v]) => !(k === "Authorization" && typeof v === "string" && v.startsWith("VAULT::"))
        );
        if (nonAuthEntries.length > 0) {
          setHeaderRows(nonAuthEntries.map(([k, v]) => ({ name: k, value: String(v) })));
          setShowHeadersSection(true);
        } else {
          setHeaderRows([{ name: "", value: "" }]);
        }
      } else {
        setHeaderRows([{ name: "", value: "" }]);
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
      setCommand(
        serverData.mcp_command || raw.mcp_command ||
        (serverData.mcp_config && serverData.mcp_config.command) ||
        (raw.mcp_config && raw.mcp_config.command) ||
        serverData.command || raw.command || "python"
      );
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
        <div className="formGroup" style={{ flex: "0 0 30%" }}>
          <NewCommonDropdown
            label="Header"
            options={vaultOptions.map((option) => option.label)}
            selected={vaultValue ? vaultOptions.find((option) => option.value === vaultValue)?.label || vaultValue : ""}
            onSelect={(label) => {
              const found = vaultOptions.find((option) => option.label === label);
              setVaultValue(found ? found.value : "");
            }}
            onClear={() => setVaultValue("")}
            showSelectedOnTop={!!vaultValue}
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
          <div className={styles.remoteEndpointRow}>
            <input
              id="endpoint"
              className={`input ${styles.remoteEndpointFlexInput}`}
              value={endpoint}
              onChange={(e) => setEndpoint(e.target.value)}
              placeholder="Http://Localhost:5000/Mcp"
              aria-label="Endpoint URL"
              disabled={isReadOnly}
              readOnly={isReadOnly}
            />
            <div className={styles.remoteEndpointIconGroup}>
              <button
                type="button"
                className={styles.infoIcon}
                onClick={(e) => {
                  e.stopPropagation();
                  setShowRemoteMcpHelp(true);
                }}
                title="Remote MCP URLs: use HTTPS in production; internal hosts need correct proxy/ingress. Tap for full guidance."
                aria-label="Remote MCP endpoint URL help">
                <SVGIcons icon="info-modern" width={16} height={16} />
              </button>
              <button type="button" className={styles.playIcon} onClick={handlePlayClickRemote} title="Load tools" style={{ display: isReadOnly ? "none" : undefined }}>
                <SVGIcons icon="lucide-play" width={16} height={16} stroke="var(--icon-color)" fill="none" />
              </button>
              {!isReadOnly && (
                <button
                  type="button"
                  className={styles.copyIcon}
                  onClick={() => handleCopy("endpoint-url", endpoint)}
                  title="Copy"
                  disabled={!endpoint || endpoint.trim() === ""}
                  style={{
                    opacity: !endpoint || endpoint.trim() === "" ? 0.4 : 1,
                    cursor: !endpoint || endpoint.trim() === "" ? "not-allowed" : "pointer",
                  }}>
                  <SVGIcons icon="fa-regular fa-copy" width={16} height={16} fill="var(--icon-color)" />
                </button>
              )}
            </div>
            <span className={`${styles.copiedText} ${copiedStates["endpoint-url"] ? styles.visible : styles.hidden}`}>Text Copied!</span>
          </div>
        </div>
      </div>

      {/* Collapsible HTTP Headers section */}
      <div className={styles.headersToggleRow}>
        <button
          type="button"
          className={styles.headersToggleBtn}
          onClick={() => setShowHeadersSection((prev) => !prev)}
          aria-expanded={showHeadersSection}
          disabled={isReadOnly && headerRows.every((r) => !r.name.trim() && !r.value.trim())}>
          {showHeadersSection ? "– Hide" : "+ Show"} HTTP Headers
        </button>
        <span className={styles.optionalLabel}>(Optional)</span>
      </div>

      {showHeadersSection && (
        <div className={styles.headersCard}>
          <div className={styles.headersCardHeader}>
            <span className={styles.headersCardTitle}>HTTP Headers</span>
            <button
              type="button"
              className={styles.headersInfoBtn}
              title="Header values can be plain text or VAULT::SECRET_NAME to reference a vault secret."
              aria-label="HTTP Headers info">
              <SVGIcons icon="info-modern" width={14} height={14} />
            </button>
          </div>

          {headerRows.map((row, idx) => (
            <div className={styles.headersRow} key={idx}>
              <input
                className={`input ${styles.headersNameInput}`}
                value={row.name}
                onChange={(e) => {
                  const updated = [...headerRows];
                  updated[idx] = { ...updated[idx], name: e.target.value };
                  setHeaderRows(updated);
                  setHeadersError("");
                }}
                placeholder="Header Name (e.g., Authorization)"
                disabled={isReadOnly}
                readOnly={isReadOnly}
                aria-label={`Header name ${idx + 1}`}
              />
              <input
                className={`input ${styles.headersValueInput}`}
                value={row.value}
                onChange={(e) => {
                  const updated = [...headerRows];
                  updated[idx] = { ...updated[idx], value: e.target.value };
                  setHeaderRows(updated);
                  setHeadersError("");
                }}
                placeholder="Value or VAULT::SECRET_NAME"
                disabled={isReadOnly}
                readOnly={isReadOnly}
                aria-label={`Header value ${idx + 1}`}
              />
              {!isReadOnly && headerRows.length > 1 && (
                <button
                  type="button"
                  className={styles.headersRemoveBtn}
                  onClick={() => {
                    setHeaderRows(headerRows.filter((_, i) => i !== idx));
                    setHeadersError("");
                  }}
                  title="Remove header"
                  aria-label={`Remove header ${idx + 1}`}>
                  ✕
                </button>
              )}
            </div>
          ))}

          {!isReadOnly && (
            <button
              type="button"
              className={styles.headersAddBtn}
              onClick={() => setHeaderRows([...headerRows, { name: "", value: "" }])}
              aria-label="Add header row">
              + Add Header
            </button>
          )}

          {headersError && <span className={styles.headersErrorText}>{headersError}</span>}
        </div>
      )}
    </div>
  );

  const renderExternalSection = () => (
    <div className="formSection">
      <div className={styles.configRow}>
        <div className="formGroup" style={{ flex: '0 0 30%' }}>
          <NewCommonDropdown
            label="Command"
            options={["python", "npx"]}
            selected={command}
            onSelect={(val) => setCommand(val)}
            placeholder="Select command"
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

  const handlePlayClickRemote = () => {
    if (!endpoint.trim()) {
      addMessage("Please provide an endpoint URL to load tools", "error");
      setShowPopup(true);
      return;
    }
    if (!showExecutorPanel) {
      setShowExecutorPanel(true);
    } else {
      setExecuteTrigger((c) => c + 1);
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
          <IAFButton type="primary" onClick={() => restoreServer()} aria-label="Restore Server" disabled={submitting}>
            {submitting ? "Restoring..." : "Restore"}
          </IAFButton>
        </>
      );
    }

    // Normal mode - show Cancel and Add/Update buttons
    // ReadOnly mode - hide toggles and show only Close button
    return (
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", width: "100%", gap: "16px" }}>
        {/* Right side: Buttons */}
        <div style={{ display: "flex", gap: "12px", flexShrink: 0, marginLeft: "auto" }}>
          {readOnly ? (
            <IAFButton type="secondary" onClick={handleCancel} aria-label="Close">
              Close
            </IAFButton>
          ) : (
            <>
              <IAFButton type="secondary" onClick={handleCancel} aria-label="Cancel" disabled={submitting}>
                Cancel
              </IAFButton>
              {/* Delete Button - shown for all roles with delete permission in update mode */}
              {isUpdateMode && !recycle && !readOnly && canDeleteServers && (
                <IAFButton
                  type="primary"
                  onClick={() => setShowDeleteConfirm(true)}
                  aria-label="Delete this server"
                  disabled={submitting}
                >
                  Delete
                </IAFButton>
              )}
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
    if (!showExecutorPanel) return null;
    if (serverType === "code" && !codeFile) {
      return (
        <ExecutorPanel
          key="executor-local"
          code={codeContent}
          autoExecute={true}
          executeTrigger={executeTrigger}
          onClose={() => setShowExecutorPanel(false)}
          mode="server"
        />
      );
    }
    if (serverType === "active") {
      return (
        <ExecutorPanel
          key="executor-remote"
          mode="remote"
          remoteEndpoint={endpoint}
          vaultValue={vaultValue}
          customHeaders={headerRows}
          autoExecute={true}
          executeTrigger={executeTrigger}
          onClose={() => setShowExecutorPanel(false)}
        />
      );
    }
    return null;
  };

  const showSplitLayout = showExecutorPanel && ((serverType === "code" && !codeFile) || serverType === "active");

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
        footer={readOnly ? undefined : renderFooter()}
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
                        setShowExecutorPanel(false);
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
                      placeholder={serverType === "external" ? "Enter MCP Server Name" : "Enter Server Name"}
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

              {/* Configuration Section - Tags */}
              <div className="formSection">
                <div className={styles.configRow}>
                  {/* Tags Section */}
                  <TagSelector selectedTags={selectedTagsForSelector} onTagsChange={handleTagsChange} nonRemovableTags={nonRemovableTags} disabled={isReadOnly} />
                </div>
              </div>
            </div >
          </div >
        </form >
      </FullModal >

      {/* Remote MCP endpoint URL — guidance (not the generic access-control doc) */}
      <DeleteModal show={showRemoteMcpHelp} onClose={() => setShowRemoteMcpHelp(false)} overlayZIndex={1000020}>
        <div style={{ textAlign: "left", maxWidth: "520px" }}>
          <h3 style={{ marginTop: 0, marginBottom: "12px", fontSize: "1.1rem" }}>Remote MCP endpoint URL</h3>
          <p style={{ margin: "0 0 12px", lineHeight: 1.55, color: "var(--content-color, inherit)" }}>
            Use a <strong>secure URL</strong> for remote MCP servers: prefer <strong>HTTPS</strong> in production. Plain HTTP is only appropriate for tightly controlled local or lab setups.
          </p>
          <p style={{ margin: "0 0 12px", lineHeight: 1.55, color: "var(--content-color, inherit)" }}>
            If the MCP server is <strong>hosted internally</strong> (private network, VPN-only, or no public DNS), our platform must be able to reach it. Work with your <strong>network or platform team</strong> to configure <strong>proxy, ingress, or API gateway</strong> rules, TLS, and allowlists. Misconfigured or missing proxy paths are a frequent reason <strong>Load tools</strong> or execution fails even when the URL works from your laptop.
          </p>
          <p style={{ margin: "0 0 16px", lineHeight: 1.55, color: "var(--content-color, inherit)" }}>
            If you still see errors after verifying the URL and headers, <strong>contact your team</strong> (platform / integration support) with the endpoint, what you tried, and any error message shown in the UI or API response.
          </p>
          <IAFButton type="primary" onClick={() => setShowRemoteMcpHelp(false)} aria-label="Close help">
            Got it
          </IAFButton>
        </div>
      </DeleteModal>

      {/* Access Control Guide Modal (code snippet / decorators) */}
      <AccessControlGuide isOpen={showAccessControlInfo} onClose={() => setShowAccessControlInfo(false)} />

      {/* Delete Confirmation Modal */}
      {showDeleteConfirm && (
        <ConfirmationModal
          message={`Are you sure you want to delete "${serverName || "this server"}"? This action cannot be undone.`}
          onConfirm={handleDeleteServerFromModal}
          setShowConfirmation={setShowDeleteConfirm}
        />
      )}

      {/* Rename-on-conflict dialog (recycle bin restore) */}
      {serverRestoreConflict && ReactDOM.createPortal(
        <div className={styles.renameOverlay}
          onClick={() => { setServerRestoreConflict(null); setServerRestoreNewName(""); }}>
          <div className={styles.renameDialog} onClick={(e) => e.stopPropagation()}>
            <h3 className={styles.renameTitle}>Name Already In Use</h3>
            <p className={styles.renameMessage}>{serverRestoreConflict.message}</p>
            {serverRestoreConflict.conflicting_resource && Object.keys(serverRestoreConflict.conflicting_resource).length > 0 && (
              <p className={styles.renameConflictInfo}>
                Active server: <strong>{serverRestoreConflict.conflicting_resource.tool_name || serverRestoreConflict.conflicting_resource.name}</strong>
                {serverRestoreConflict.conflicting_resource.created_by && <> &mdash; created by <strong>{serverRestoreConflict.conflicting_resource.created_by}</strong></>}
              </p>
            )}
            <div className={styles.renameFieldGroup}>
              <label className="label-desc">New name</label>
              <input
                className="input"
                type="text"
                placeholder={serverRestoreConflict.suggested_name || ""}
                value={serverRestoreNewName}
                onChange={(e) => setServerRestoreNewName(e.target.value)}
                onKeyDown={(e) => { if (e.key === "Enter" && serverRestoreNewName.trim()) { setServerRestoreConflict(null); restoreServer(serverRestoreNewName.trim()); } }}
                autoFocus
              />
            </div>
            <div className={styles.renameActions}>
              <IAFButton type="secondary" onClick={() => { setServerRestoreConflict(null); setServerRestoreNewName(""); }}>Cancel</IAFButton>
              <IAFButton type="primary" disabled={submitting || !serverRestoreNewName.trim()} onClick={() => { setServerRestoreConflict(null); restoreServer(serverRestoreNewName.trim()); }}>Restore</IAFButton>
            </div>
          </div>
        </div>,
        document.body
      )}
    </>
  );
}
