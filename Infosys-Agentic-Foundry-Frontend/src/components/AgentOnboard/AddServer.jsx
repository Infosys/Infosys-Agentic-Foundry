import React, { useState, useEffect, useRef } from "react";
import DropDown from "../commonComponents/DropDowns/DropDown";
import "../../css_modules/AddServer.css";
import styles from "../../css_modules/ToolOnboarding.module.css";
import InfoTag from "../commonComponents/InfoTag";
import { useToolsAgentsService } from "../../services/toolService";
import Cookies from "js-cookie";
import SVGIcons from "../../Icons/SVGIcons.js";
import ZoomPopup from "../commonComponents/ZoomPopup.jsx";
import Editor from "@monaco-editor/react";
import groundTruthStyles from "../GroundTruth/GroundTruth.module.css";
import { useMcpServerService } from "../../services/serverService";
import { useMessage } from "../../Hooks/MessageContext";
import Tag from "../Tag/Tag";
import useFetch from "../../Hooks/useAxios.js";
import { APIs } from "../../constant";

export default function AddServer({ editMode = false, serverData = null, onClose, drawerFormClass, setRefreshPaginated = () => {} }) {
  const { addServer } = useToolsAgentsService();
  const { fetchData } = useFetch();
  const { getAllServers, updateServer } = useMcpServerService();
  const user = { isAdmin: true, teams: ["dev", "ops"], team_ids: ["dev", "ops"] };
  const isAdmin = !!(user && (user.isAdmin || user.is_admin));
  const userTeams = user?.teams || user?.team_ids || [];

  const [serverType, setServerType] = useState("code");
  const [serverName, setServerName] = useState("");
  const [moduleName, setModuleName] = useState("");
  const [description, setDescription] = useState("");
  const [selectedTeam, setSelectedTeam] = useState("");
  const [endpoint, setEndpoint] = useState("");
  const [codeFile, setCodeFile] = useState(null);
  const [codeContent, setCodeContent] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  const [isDraggingCode, setIsDraggingCode] = useState(false);
  const [isDraggingCapabilities, setIsDraggingCapabilities] = useState(false);
  const [showZoomPopup, setShowZoomPopup] = useState(false);
  const [popupTitle, setPopupTitle] = useState("");
  const [popupContent, setPopupContent] = useState("");
  const [copiedStates, setCopiedStates] = useState({});
  const [isDarkTheme] = useState(true); // Use isDarkTheme for theme logic
  const { addMessage, setShowPopup } = useMessage();
  const creatorEmail =
    (serverData &&
      (serverData.created_by || serverData.user_email_id || serverData.createdBy || (serverData.raw && (serverData.raw.created_by || serverData.raw.user_email_id)))) ||
    Cookies.get("email") ||
    Cookies.get("userName") ||
    "";

  const teamOptions = userTeams.map((t) => ({ label: t, value: t }));

  const [tagList, setTagList] = useState([]);
  const hasLoadedTagsOnce = useRef(false);
  const prefillDoneRef = useRef(false);
  const editorRef = useRef(null);

  const serverIdForPrefill = serverData ? serverData.id : null;
  useEffect(() => {
    prefillDoneRef.current = false;
  }, [editMode, serverIdForPrefill]);
  useEffect(() => {
    if (hasLoadedTagsOnce.current) return;
    hasLoadedTagsOnce.current = true;
    (async () => {
      try {
        const data = await fetchData(APIs.GET_TAGS);
        const normalized = Array.isArray(data)
          ? data.map((t) => ({ tag: t.tag_name || t.tag || t.name || "", tagId: t.tag_id || t.id || t.tagId || t.slug || "", selected: false }))
          : [];
        setTagList(normalized);
      } catch (e) {
        console.error("Failed to fetch tags for AddServer", e);
      }
    })();
  }, [fetchData]);

  const toggleTagSelection = (index) => {
    setTagList((prev) => prev.map((tag, i) => (i === index ? { ...tag, selected: !tag.selected } : tag)));
  };

  const validateFile = (file, type) => {
    if (!file) return false;
    if (type === "code") {
      const validExtensions = [".py", ".txt"];
      const fileName = file.name.toLowerCase();
      return validExtensions.some((ext) => fileName.endsWith(ext));
    }
    if (type === "json") {
      const validExtensions = [".json"];
      const fileName = file.name.toLowerCase();
      return validExtensions.some((ext) => fileName.endsWith(ext));
    }
    return true;
  };

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
    if (type === "code") setCodeFile(null);
    const fileInput = document.getElementById(type + "File");
    if (fileInput) fileInput.value = "";
  };
  const validate = () => {
    if (!serverName.trim() || !description.trim()) return "Server Name and Description are required.";
    if (!isAdmin) {
      if (!selectedTeam.trim()) return "Team selection is required for non-admin users.";
    }
    if (serverType === "code") {
      // For Update Server mode, only validate code snippet (no file upload option)
      if (editMode) {
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
    if (!err) return setError("");
    if (typeof err === "string") return setError(err);
    setError(formatErrorMessage(err));
  };

  // Patch all setError calls to use safeSetError
  const handleSubmit = async (e) => {
    if (e) {
      e.preventDefault();
      e.stopPropagation();
    }
    setMessage("");
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
      let mcp_type = serverType === "active" ? "url" : serverType === "code" ? "file" : "module";
      const selectedTagIds = tagList
        .filter((t) => t.selected)
        .map((t) => {
          const raw = t.tagId;
          const num = Number(raw);
          return typeof raw === "string" && raw.trim() !== "" && !Number.isNaN(num) ? num : raw;
        });

      let payload = {
        tool_name: serverName.trim(),
        tool_description: description.trim(),
        mcp_type,
        created_by: Cookies.get("email") || "Guest",
        mcp_url: mcp_type === "url" ? endpoint.trim() : "",
        mcp_module_name: mcp_type === "module" ? moduleName.trim() : "",
        code_content: mcp_type === "file" && !codeFile ? codeContent.trim() : "",
        mcp_file: mcp_type === "file" && codeFile ? codeFile : undefined,
        tag_ids: selectedTagIds,
      };
      if (!payload.mcp_file) delete payload.mcp_file;

      try {
        try {
          console.debug("[AddServer] submitting payload preview:", {
            tool_name: payload.tool_name,
            mcp_type: payload.mcp_type,
            tag_ids: payload.tag_ids,
            hasFile: !!payload.mcp_file,
          });
        } catch (e) {}

        const response = await addServer(payload);
        const ok = response && (response?.is_created === true || response?.is_update === true || response?.status === "success");
        if (ok) {
          const msg = response?.status_message || response?.message || "Server added successfully!";
          try {
            addMessage(msg, "success");
            setShowPopup(true);
          } catch (e) {}
          setMessage(msg);
          setServerName("");
          setModuleName("");
          setDescription("");
          setSelectedTeam("");
          setEndpoint("");
          setCodeFile(null);
          setCodeContent("");
          setTagList(tagList.map((tag) => ({ ...tag, selected: false })));
          try {
            if (typeof setRefreshPaginated === "function") {
              try {
                setRefreshPaginated();
              } catch (e) {
                try {
                  setRefreshPaginated(true);
                } catch (e2) {
                  console.debug("[AddServer] setRefreshPaginated invocation failed", e, e2);
                }
              }
            }
          } catch (e) {
            console.debug("[AddServer] setRefreshPaginated failed", e);
          }
          try {
            window.dispatchEvent(new CustomEvent("AddServer:RefreshRequested"));
          } catch (e) {
            console.debug("[AddServer] dispatch refresh event failed", e);
          }
          // Use the existing cancel logic to reliably close regardless of prop availability
          try {
            handleCancel();
            // retry shortly after in case DOM elements mount asynchronously
            setTimeout(() => {
              try {
                handleCancel();
              } catch (_) {}
            }, 300);
          } catch (e) {
            try {
              window.dispatchEvent(new CustomEvent("AddServer:CloseRequested"));
            } catch (e2) {
              console.debug("[AddServer] close fallback failed", e, e2);
            }
          }
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
    } catch (e2) {
      safeSetError(e2?.detail || e2?.message || e2 || "Submit failed");
    } finally {
      setSubmitting(false);
    }
  };

  const handleUpdate = async (e) => {
    e.preventDefault();
    setMessage("");
    setError("");
    setSubmitting(true);
    try {
      const is_admin = Cookies.get("role")?.toUpperCase() === "ADMIN";
      let mcp_type = serverType === "active" ? "url" : serverType === "code" ? "file" : "module";
      const selectedTagIds = tagList
        .filter((t) => t.selected)
        .map((t) => {
          const raw = t.tagId;
          const num = Number(raw);
          return typeof raw === "string" && raw.trim() !== "" && !Number.isNaN(num) ? num : raw;
        });
      // Defensive fallback for all required fields
      const id = serverData?.id || serverData.tool_id || (serverData?.raw && serverData.raw.id) || "";
      const tool_name = serverName?.trim() || serverData?.tool_name || serverData?.name || (serverData?.raw && (serverData.raw.tool_name || serverData.raw.name)) || "";
      const tool_description =
        description?.trim() ||
        serverData?.tool_description ||
        serverData?.description ||
        (serverData?.raw && (serverData.raw.tool_description || serverData.raw.description)) ||
        "";
      const mcp_url = mcp_type === "url" ? endpoint?.trim() || serverData?.endpoint || (serverData?.raw && serverData.raw.endpoint) || "" : "";
      const mcp_module_name = mcp_type === "module" ? moduleName?.trim() || serverData?.mcp_module_name || (serverData?.raw && serverData.raw.mcp_module_name) || "" : "";
      const code_content =
        mcp_type === "file" && !codeFile
          ? codeContent?.trim() || serverData?.codeContent || serverData?.code_content || (serverData?.raw && (serverData.raw.codeContent || serverData.raw.code_content)) || ""
          : "";
      let payload = {
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
      };
      if (selectedTeam) payload.team_id = selectedTeam;
      let sendPayload = payload;
      let isForm = false;
      if (codeFile) {
        const fd = new FormData();
        Object.keys(payload).forEach((k) => {
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
        isForm = true;
      }
      try {
        console.debug("[AddServer] sending update payload preview:", {
          tool_id: payload.tool_id,
          tool_name: payload.tool_name,
          mcp_type: payload.mcp_type,
          tag_ids: payload.tag_ids,
          hasFile: !!codeFile,
          isForm,
        });
      } catch (e) {}
      const response = await updateServer(id, sendPayload);
      const ok = response && (response?.status === "success" || response?.is_update === true || response?.is_updated === true);
      if (ok) {
        const msg = response?.status_message || response?.message || "Server updated successfully!";
        setMessage(msg);
        try {
          addMessage(msg, "success");
          setShowPopup(true);
        } catch (e) {}
        try {
          if (typeof setRefreshPaginated === "function") setRefreshPaginated();
        } catch (e) {
          console.debug("[AddServer] setRefreshPaginated failed", e);
        }
        // Patch: Fetch latest server data and update tags live
        prefillDoneRef.current = false;
        if (response?.updated_server) {
          // If backend returns updated server, update tags live
          setTimeout(() => {
            // Update serverData and re-run prefill
            if (typeof response.updated_server === "object") {
              // This assumes you have a way to update serverData prop/state
              // If serverData is a prop, you may need to lift state up or use a callback
              // For now, just update tagList directly
              const rawTags = response.updated_server.tags || response.updated_server.tag_ids || [];
              const normalizedTagValues = Array.isArray(rawTags)
                ? rawTags
                    .flatMap((t) => {
                      if (t === null || t === undefined) return [];
                      if (typeof t === "string" || typeof t === "number") return [t.toString().toLowerCase()];
                      if (typeof t === "object") {
                        const candidates = [t.tag_name, t.tag, t.tagId, t.tag_id, t.name, t.slug, t.id];
                        return candidates.filter(Boolean).map((c) => c.toString().toLowerCase());
                      }
                      return [];
                    })
                    .filter(Boolean)
                : [];
              const selectedSet = new Set(normalizedTagValues);
              setTagList((prev) =>
                prev.map((tag) => ({
                  ...tag,
                  selected: selectedSet.has((tag.tagId || "").toString().toLowerCase()) || selectedSet.has((tag.tag || "").toString().toLowerCase()),
                }))
              );
            }
          }, 100);
        }
        try {
          window.dispatchEvent(new CustomEvent("AddServer:RefreshRequested"));
        } catch (e) {
          console.debug("[AddServer] dispatch refresh event failed", e);
        }
        if (onClose) onClose();
      } else {
        // Handle validation errors just like ToolOnBoarding
        if (response?.message?.includes("Verification failed:")) {
          safeSetError(response.message);
        } else if (response?.status && response?.response?.status !== 200) {
          safeSetError(response?.response?.data?.detail || "Update failed");
        } else {
          safeSetError(response?.message || response?.status_message || "Update failed");
        }
      }
    } catch (err) {
      safeSetError(err?.message || err || "Update failed");
    } finally {
      setSubmitting(false);
    }
  };

  const handleCancel = (e) => {
    if (e && typeof e.preventDefault === "function") {
      try {
        e.preventDefault();
        e.stopPropagation();
      } catch (err) {}
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
      const trySelectors = ["button.closeBtn", 'button[aria-label="Close"]', 'button[aria-label="close"]', ".modalOverlay button", ".modalDrawerRight button"];
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
    if (!editMode || !serverData || tagList.length === 0) return;
    if (prefillDoneRef.current) return;
    prefillDoneRef.current = true;
    const raw = serverData.raw || serverData || {};
    const rawTags = serverData.tags || raw.tags || serverData.tag_ids || raw.tag_ids || [];

    // Defensive fallback for missing fields
    let incomingType = (serverData.mcp_type || raw.mcp_type || serverData.type || raw.type || "code").toString().toLowerCase();
    let mappedType = "code";
    if (incomingType.includes("url") || incomingType.includes("remote") || incomingType === "active") mappedType = "active";
    else if (incomingType.includes("module") || incomingType === "external") mappedType = "external";
    else mappedType = "code";

    setServerType(mappedType);
    setServerName(serverData.name || serverData.tool_name || raw.tool_name || "");
    setModuleName(serverData.moduleName || raw.mcp_module_name || raw.mcp_module || "");
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
          } catch (e) {}
        }
      } catch (e) {}
      return v;
    };

    if (mappedType === "active") {
      const endpointCandidates = [raw.mcp_url, raw.mcp_config && raw.mcp_config.url, raw.endpoint, serverData.endpoint, raw.mcp_config && raw.mcp_config.mcp_url];
      const ep = endpointCandidates.find((c) => typeof c === "string" && c.trim().length > 0) || "";
      setEndpoint(ep);
      setCodeFile(null);
      setCodeContent("");
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
    } else {
      setEndpoint(raw.mcp_url || serverData.endpoint || "");
      setCodeFile(null);
      setCodeContent(raw.code_content || serverData.codeContent || "");
    }

    // Patch: normalize all possible tag formats
    const normalizedTagValues = Array.isArray(rawTags)
      ? rawTags
          .flatMap((t) => {
            if (t === null || t === undefined) return [];
            if (typeof t === "string" || typeof t === "number") return [t.toString().toLowerCase()];
            if (typeof t === "object") {
              const candidates = [t.tag_name, t.tag, t.tagId, t.tag_id, t.name, t.slug, t.id];
              return candidates.filter(Boolean).map((c) => c.toString().toLowerCase());
            }
            return [];
          })
          .filter(Boolean)
      : [];
    const selectedSet = new Set(normalizedTagValues);
    setTagList((prev) =>
      prev.map((tag) => ({
        ...tag,
        selected: selectedSet.has((tag.tagId || "").toString().toLowerCase()) || selectedSet.has((tag.tag || "").toString().toLowerCase()),
      }))
    );
  }, [editMode, serverData, tagList]);

  const renderTeamSelector = () => {
    if (isAdmin) {
      return null;
    }
    if (userTeams.length) {
      return (
        <div className={styles["form-block"]}>
          <label className={styles["label-desc"]} htmlFor="selectedTeam" style={{ fontWeight: 500, fontSize: "15px", marginBottom: "6px", color: "#222" }}>
            Select Team ID
          </label>
          <DropDown
            options={teamOptions}
            value={teamOptions.find((opt) => opt.value === selectedTeam) || null}
            onChange={(opt) => setSelectedTeam(opt ? opt.value : "")}
            placeholder="-- choose --"
            selectStyle={styles["selectStyle"]}
            style={{
              width: "260px",
              zIndex: 1000,
              borderRadius: "8px",
              border: "2px solid #1976d2",
              background: "#fafbfc",
              color: "#222",
              fontWeight: 500,
              fontSize: "15px",
              boxShadow: "0 2px 8px rgba(25,118,210,0.08)",
            }}
            aria-label="Select Team ID"
          />
        </div>
      );
    }
    return (
      <div className={styles["form-block"]}>
        <div className={styles["warn-msg"]}>No teams assigned. Contact an admin.</div>
      </div>
    );
  };

  const renderActiveSection = () => (
    <>
      <div className={styles["form-block"]}>
        <label className={styles["label-desc"]} htmlFor="endpoint">
          Endpoint URL
        </label>
        <input
          id="endpoint"
          className={styles["input-class"]}
          value={endpoint}
          onChange={(e) => setEndpoint(e.target.value)}
          placeholder="http://localhost:5000/mcp"
          aria-label="Endpoint URL"
          style={commonInputStyle}
          disabled={editMode}
        />
      </div>
    </>
  );

  const commonInputStyle = {
    width: "100%",
    maxWidth: "700px",
    marginLeft: 0,
    marginRight: 0,
    boxSizing: "border-box",
    display: "block",
  };

  const handleCopy = (key, text) => {
    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard
        .writeText(text)
        .then(() => {
          setCopiedStates((prev) => ({ ...prev, [key]: true }));
          setTimeout(() => {
            setCopiedStates((prev) => ({ ...prev, [key]: false }));
          }, 2000);
        })
        .catch(() => {
          console.error("Failed to copy text, AddServer");
        });
    } else {
      const textarea = document.createElement("textarea");
      textarea.value = text;
      textarea.style.position = "fixed";
      textarea.style.opacity = "0";
      document.body.appendChild(textarea);
      textarea.focus();
      textarea.select();
      try {
        document.execCommand("copy");
        setCopiedStates((prev) => ({ ...prev, [key]: true }));
        setTimeout(() => {
          setCopiedStates((prev) => ({ ...prev, [key]: false }));
        }, 2000);
      } catch {
        console.error("Fallback: Failed to copy text, AddServer");
      } finally {
        document.body.removeChild(textarea);
      }
    }
  };
  const handleZoomClick = (title, content) => {
    setPopupTitle(title);
    setPopupContent(content || "");
    setShowZoomPopup(true);
  };

  const handleZoomSave = (updatedContent) => {
    if (popupTitle === "Code Snippet") {
      setCodeContent(updatedContent);
    } else if (popupTitle === "Description") {
      setDescription(updatedContent);
    }
    setShowZoomPopup(false);
  };

  const renderCodeSection = () => (
    <div className={styles["snippet-container"]}>
      <label className={styles["label-desc"]} htmlFor="codeContent">
        CODE SNIPPET
        <InfoTag message="Paste your code or upload a file." />
      </label>
      <div className={styles.codeEditorContainer}>
        <div
          style={{
            border: "1px solid #e0e0e0",
            borderRadius: "8px",
            overflow: "hidden",
            fontFamily: "Consolas, Monaco, monospace",
            backgroundColor: isDarkTheme ? "#1e1e1e" : "#ffffff",
            position: "relative",
          }}>
          <div
            style={{
              display: "flex",
              justifyContent: "space-between",
              alignItems: "center",
              padding: "8px 12px",
              backgroundColor: isDarkTheme ? "#2d2d30" : "#f8f9fa",
              borderBottom: isDarkTheme ? "1px solid #3e3e42" : "1px solid #e0e0e0",
              fontSize: "12px",
            }}>
            <span
              style={{
                padding: "4px 8px",
                border: "1px solid #d0d7de",
                borderRadius: "4px",
                backgroundColor: isDarkTheme ? "#3c3c3c" : "white",
                color: isDarkTheme ? "#ffffff" : "#000000",
                fontSize: "12px",
                display: "inline-block",
              }}>
              Python
            </span>
          </div>
          <Editor
            height="250px"
            language="python"
            theme={isDarkTheme ? "vs-dark" : "vs-light"}
            value={codeFile ? "" : codeContent}
            onChange={codeFile ? undefined : (value) => setCodeContent(value)}
            options={{
              fontSize: 14,
              lineHeight: 1.2,
              padding: { top: 8, right: 8, bottom: 8, left: 8 },
              minimap: { enabled: false },
              scrollBeyondLastLine: false,
              automaticLayout: true,
              tabSize: 4,
              // if a file is present, snapshot view only; otherwise allow editing
              // also if we're in editMode and serverType is 'code', allow editing even if codeFile is null
              readOnly: !!codeFile ? true : !(editMode && serverType === "code") && false,
            }}
            onMount={(editor) => {
              // Store editor reference if needed
              editorRef.current = editor;

              // Optional: Add custom resize handling
              const resizeObserver = new ResizeObserver(() => {
                requestAnimationFrame(() => {
                  editor.layout();
                });
              });

              resizeObserver.observe(editor.getDomNode().parentElement);

              return () => {
                resizeObserver.disconnect();
              };
            }}
          />
        </div>
        <button type="button" className={styles.copyIcon} onClick={() => handleCopy("code-snippet", codeFile ? "" : codeContent)} title="Copy">
          <SVGIcons icon="fa-regular fa-copy" width={16} height={16} fill={isDarkTheme ? "#ffffff" : "#000000"} />
        </button>
        <div className={styles.iconGroup}>
          <button type="button" className={styles.expandIcon} onClick={() => handleZoomClick("Code Snippet", codeFile ? "" : codeContent)} title="Expand">
            <SVGIcons icon="fa-solid fa-up-right-and-down-left-from-center" width={16} height={16} fill={isDarkTheme ? "#ffffff" : "#000000"} />
          </button>
        </div>
        <span className={`${styles.copiedText} ${copiedStates["code-snippet"] ? styles.visible : styles.hidden}`}>Text Copied!</span>
      </div>{" "}
      {/* File upload UI below, matching GroundTruth structure - Only show for Add Server mode */}
      {!editMode && (
        <div className={styles["form-block"]}>
          <label htmlFor="codeFile" className={styles["label-desc"]}>
            Python File (.py)
            <span style={{ fontWeight: 400, fontSize: "13px", marginLeft: "8px", color: "#888" }}>(Supported: .py)</span>
          </label>
          <input
            type="file"
            id="codeFile"
            name="codeFile"
            onChange={(e) => {
              const file = e.target.files?.[0];
              if (validateFile(file, "code")) {
                setCodeFile(file);
                setCodeContent("");
              }
            }}
            className={styles["input-class"]}
            accept=".py"
            style={{ display: "none" }}
            disabled={submitting}
          />
          {!codeFile ? (
            <div
              className={groundTruthStyles.fileUploadContainer + (isDraggingCode ? " " + groundTruthStyles.dragging : "") + (submitting ? " " + groundTruthStyles.disabled : "")}
              onDragEnter={handleDragEnter("code")}
              onDragLeave={handleDragLeave("code")}
              onDragOver={handleDragOver("code")}
              onDrop={(e) => {
                e.preventDefault();
                e.stopPropagation();
                setIsDraggingCode(false);
                if (e.dataTransfer.files && e.dataTransfer.files.length > 0) {
                  const file = e.dataTransfer.files[0];
                  if (validateFile(file, "code")) {
                    setCodeFile(file);
                    setCodeContent("");
                  }
                }
              }}
              onClick={() => !submitting && document.getElementById("codeFile").click()}
              tabIndex={0}
              role="button"
              aria-label="Upload Python File"
              style={commonInputStyle}>
              <div className={groundTruthStyles.uploadPrompt} style={{ width: "100%", textAlign: "left" }}>
                <span>{isDraggingCode ? "Drop file here" : "Click to upload or drag and drop"}</span>
                <span>
                  <small>Supported: .py</small>
                </span>
              </div>
            </div>
          ) : (
            <div className={groundTruthStyles.fileCard} style={commonInputStyle}>
              <div className={groundTruthStyles.fileInfo} style={{ width: "100%", textAlign: "left" }}>
                <span className={groundTruthStyles.fileName}>{codeFile.name}</span>
                <button type="button" onClick={() => handleRemoveFile("code")} className={groundTruthStyles.removeFileButton} aria-label="Remove file">
                  &times;
                </button>
              </div>
            </div>
          )}
        </div>
      )}
      <ZoomPopup
        show={showZoomPopup}
        onClose={() => setShowZoomPopup(false)}
        title={popupTitle}
        content={popupContent}
        onSave={handleZoomSave}
        type={popupTitle === "Code Snippet" ? "code" : "text"}
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
  return (
    <div id="myOverlay" className="overlay">
      <div className={drawerFormClass ? drawerFormClass : "form-container"}>
        <form
          className={styles.addServer}
          aria-label={editMode ? "Update Server Form" : "Add Server Form"}
          onSubmit={editMode ? handleUpdate : handleSubmit}
          style={{ minHeight: 0 }}>
          <div style={{ marginBottom: 24 }}>
            <h2 style={{ fontSize: "22px", fontWeight: 700, color: "#0f172a", margin: 0 }}>{editMode ? "UPDATE SERVER" : "ADD SERVER"}</h2>
          </div>
          {/* Error message display, always friendly and readable */}
          {(!!error || !!message) && (
            <div className={styles["form-block"]}>
              {error && (
                <div className={styles["warn-msg"]} style={{ color: "#d32f2f", fontWeight: 500, marginBottom: 8 }}>
                  {typeof error === "string" ? error : formatErrorMessage(error) || JSON.stringify(error)}
                </div>
              )}
              {message && (
                <div className={styles["success-msg"]} style={{ color: "#388e3c", fontWeight: 500, marginBottom: 8 }}>
                  {message}
                </div>
              )}
            </div>
          )}
          <div className={styles["form-block"]} style={{ display: "flex", gap: 24, alignItems: "flex-start" }}>
            <div style={{ display: "flex", flexDirection: "column", gap: 6, minWidth: 0 }}>
              <label className={styles["label-desc"]} htmlFor="serverType" style={{ marginBottom: 0 }}>
                Server Type
              </label>
              <DropDown
                options={[
                  { label: "REMOTE", value: "active" },
                  { label: "LOCAL", value: "code" },
                  // { label: 'External', value: 'external' } // External option commented out as requested
                ]}
                value={serverType}
                disabled={editMode}
                onChange={(e) => {
                  if (editMode) return; // prevent changing type in edit
                  const val = e?.target ? e.target.value : e;
                  setServerType(val);
                  setEndpoint("");
                  setCodeFile(null);
                  setCodeContent("");
                  setError("");
                  setMessage("");
                }}
                placeholder="-- select --"
                selectStyle={styles["selectStyle"]}
                style={{ width: "260px", zIndex: 1000 }}
                aria-label="Server Type"
              />
            </div>
            {editMode && (
              <div style={{ display: "flex", flexDirection: "column", gap: 6, minWidth: 260 }}>
                <label className={styles["label-desc"]} style={{ marginBottom: 0 }}>
                  CREATED BY
                </label>
                <input
                  value={creatorEmail}
                  disabled
                  readOnly
                  className={styles["input-class"]}
                  style={{ width: "260px", background: "#f3f4f6", borderRadius: 6, padding: "8px 10px", border: "1px solid #e5e7eb", color: "#111" }}
                />
              </div>
            )}
          </div>
          <div className={styles["form-block"]}>
            <label className={styles["label-desc"]} htmlFor="serverName">
              Server Name *
            </label>
            <input
              id="serverName"
              className={styles["input-class"]}
              value={serverName}
              onChange={(e) => setServerName(e.target.value)}
              disabled={editMode}
              placeholder={serverType === "external" ? "Enter MCP module name" : "Enter server name"}
              aria-label={serverType === "external" ? "Module Name" : "Server Name"}
              required
              style={commonInputStyle}
            />
          </div>
          <div className={styles["form-block"]}>
            <label className={styles["label-desc"]} htmlFor="description">
              Description *
            </label>
            <textarea
              id="description"
              className={styles["input-class"]}
              rows={3}
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              placeholder={serverType === "external" ? "Describe your module" : "Describe your server"}
              aria-label="Description"
              required
              style={commonInputStyle}
            />
          </div>
          {renderTeamSelector()}
          {serverType === "active" && renderActiveSection()}
          {serverType === "code" && <div style={{ marginBottom: "18px" }}>{renderCodeSection()}</div>}
          <div className={styles["tagsMainContainer"]}>
            <label htmlFor="tags" className={styles["label-desc"]}>
              Select Tags
              <InfoTag message="Select the tags." />
            </label>
            <div className={styles["tagsContainer"]}>
              {tagList.map((tag, index) => (
                <Tag key={"li-<ulName>-" + index} index={index} tag={tag.tag} selected={tag.selected} toggleTagSelection={toggleTagSelection} />
              ))}{" "}
            </div>
          </div>

          {/* Form actions with proper AddServer styling */}
          <div className="form-actions">
            <button type="submit" className={styles["add-button"]} disabled={submitting} aria-label={editMode ? "Update Server" : "Add Server"}>
              {submitting ? (editMode ? "UPDATING..." : "ADDING...") : editMode ? "UPDATE" : "ADD SERVER"}
            </button>
            <button type="button" className="closeBtn" onClick={handleCancel} aria-label="Cancel">
              CANCEL
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
