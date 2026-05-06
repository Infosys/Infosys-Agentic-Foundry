import { useState, useEffect } from "react";
import styles from "./ToolDetailModal.module.css";
import ReactMarkdown from "react-markdown";
import { META_AGENT, PLANNER_META_AGENT, APIs } from "../../constant";
import { useMessage } from "../../Hooks/MessageContext";
import Loader from "../commonComponents/Loader";
import { useToolsAgentsService } from "../../services/toolService";
import AddServer from "../AgentOnboard/AddServer.jsx";
import { useMcpServerService } from "../../services/serverService";
import CodeEditor from "../commonComponents/CodeEditor.jsx";
import IAFButton from "../../iafComponents/GlobalComponents/Buttons/Button";
import useFetch from "../../Hooks/useAxios";

const ToolDetailModal = ({
  isOpen,
  onClose,
  description,
  endpoint,
  codeSnippet,
  moduleName,
  agenticApplicationWorkflowDescription,
  systemPrompt,
  isMappedTool,
  setShowForm,
  agentType,
  tool,
  resourceTab = "tools",
  selectedVersion,
  useToolCardDescriptionStyle = false,
  hideModifyButton = false,
  onExpandSlider = null, // Callback to expand/contract the parent slider
}) => {
  const { addMessage } = useMessage();
  const [loading, setLoading] = useState(false);
  const [showEditServerModal, setShowEditServerModal] = useState(false);
  const [serverDataForEdit, setServerDataForEdit] = useState(null);
  const [fetchedCodeSnippet, setFetchedCodeSnippet] = useState("");
  const [fetchedDescription, setFetchedDescription] = useState("");
  const [fetchedEndpoint, setFetchedEndpoint] = useState("");
  const [fetchedModuleName, setFetchedModuleName] = useState("");
  const [fetchedWorkflowDescription, setFetchedWorkflowDescription] = useState("");
  const [fetchedSystemPrompt, setFetchedSystemPrompt] = useState(null);
  const { checkToolEditable, getToolById } = useToolsAgentsService();
  const { getServerById } = useMcpServerService();
  const { fetchData } = useFetch();

  // Fetch full tool/server details when modal opens
  useEffect(() => {
    if (!isOpen) {
      setFetchedCodeSnippet("");
      setFetchedDescription("");
      setFetchedEndpoint("");
      setFetchedModuleName("");
      setFetchedWorkflowDescription("");
      setFetchedSystemPrompt(null);
      return;
    }
    const toolId = tool?.tool_id || tool?.id;
    const agentId = tool?.agentic_application_id || tool?.agent_id || tool?.tool_id || tool?.id;

    // Determine resource type
    const isAgent = resourceTab === "agents" || tool?.type === "agents";
    const mcpType = (tool?.mcp_type || "").toLowerCase();
    const isMcpToolId = typeof toolId === "string" && toolId.startsWith("mcp_");
    const isServer = mcpType === "file" || mcpType === "url" || mcpType === "module" || resourceTab === "servers" || isMcpToolId;

    // For agents, fetch using GET_AGENTS_BY_ID
    if (isAgent && agentId) {
      const fetchAgentDetails = async () => {
        setLoading(true);
        try {
          const agentData = await fetchData(APIs.GET_AGENTS_BY_ID + agentId);
          const fullData = Array.isArray(agentData) ? agentData[0] : agentData;
          if (!fullData) return;

          if (!description && (fullData?.agentic_application_description || fullData?.description)) {
            setFetchedDescription(fullData.agentic_application_description || fullData.description);
          }
          if (fullData?.agentic_application_workflow_description) {
            setFetchedWorkflowDescription(fullData.agentic_application_workflow_description);
          }
          if (fullData?.system_prompt) {
            setFetchedSystemPrompt(fullData.system_prompt);
          }
        } catch {
          console.error("Failed to fetch agent details for preview");
        } finally {
          setLoading(false);
        }
      };
      fetchAgentDetails();
      return;
    }

    if (!toolId) return;

    // Always fetch for servers to get fresh data from MCP_GET_SERVER_BY_ID
    // For tools, fetch if we don't have the needed data OR if a specific version is selected
    const hasToolData = codeSnippet && !codeSnippet.includes("No code available");
    const needsFetch = isServer || !hasToolData || selectedVersion;

    if (!needsFetch) return;

    const fetchDetails = async () => {
      setLoading(true);
      try {
        // Use MCP_GET_SERVER_BY_ID for servers, GET_TOOLS_BY_ID for regular tools
        const details = isServer ? await getServerById(toolId) : await getToolById(toolId);
        const fullData = Array.isArray(details) ? details[0] : details;
        if (!fullData) return;

        // Set description if not already provided
        if (!description && fullData?.tool_description) {
          setFetchedDescription(fullData.tool_description);
        }

        // Check if it's a server (has mcp_type) — extract server-specific data
        const fetchedMcpType = (fullData?.mcp_type || "").toLowerCase();
        if (fetchedMcpType === "file") {
          const code = fullData?.mcp_config?.args?.[1];
          if (typeof code === "string" && code.trim().length > 0) {
            setFetchedCodeSnippet(code);
          }
        } else if (fetchedMcpType === "url") {
          const url = fullData?.mcp_config?.url || "";
          if (url) setFetchedEndpoint(url);
        } else if (fetchedMcpType === "module") {
          const mod = fullData?.mcp_config?.args?.[1] || "";
          if (mod) setFetchedModuleName(mod);
        } else {
          // Regular tool — extract version-specific or main code snippet
          if (selectedVersion && fullData?.versioning?.[selectedVersion]) {
            const versionData = fullData.versioning[selectedVersion];
            if (versionData.code_snippet) setFetchedCodeSnippet(versionData.code_snippet);
            if (versionData.tool_description) setFetchedDescription(versionData.tool_description);
          } else if (fullData?.code_snippet) {
            setFetchedCodeSnippet(fullData.code_snippet);
          }
        }
      } catch {
        console.error("Failed to fetch resource details for preview");
      } finally {
        setLoading(false);
      }
    };
    fetchDetails();
  }, [isOpen, tool?.tool_id, tool?.id, resourceTab, selectedVersion]);

  if (!isOpen) return null;

  // Use fetched data — when a version is selected, prefer fetched (version-specific) data over props
  const isPlaceholderCode = codeSnippet && codeSnippet.includes("No code available");
  const displayCodeSnippet = selectedVersion
    ? (fetchedCodeSnippet || codeSnippet)
    : (isPlaceholderCode ? (fetchedCodeSnippet || codeSnippet) : (codeSnippet || fetchedCodeSnippet));
  const displayDescription = selectedVersion
    ? (fetchedDescription || description)
    : (description || fetchedDescription);
  const displayEndpoint = endpoint || fetchedEndpoint;
  const displayModuleName = moduleName || fetchedModuleName;
  const displayWorkflowDescription = agenticApplicationWorkflowDescription || fetchedWorkflowDescription;
  const displaySystemPrompt = systemPrompt || fetchedSystemPrompt;

  /**
   * Handle Modify button click
   * - For servers: Calls GET API (MCP_GET_SERVER_BY_ID) to fetch latest data, then opens AddServer modal
   * - For tools: Calls GET API (GET_TOOLS_BY_ID) via checkToolEditable
   * - For agents (isMetaAgent): Calls GET API (GET_AGENTS_BY_ID) to fetch latest data
   */
  const handleModify = async (e) => {
    e.preventDefault();

    const mcpType = (tool?.mcp_type || "").toLowerCase();
    const isServer = resourceTab === "servers" || mcpType === "file" || mcpType === "url" || mcpType === "module";
    const isMetaAgent = agentType === META_AGENT || agentType === PLANNER_META_AGENT;
    const isAgentResource = resourceTab === "agents" || tool?.type === "agents";

    setLoading(true);
    try {
      if (isMetaAgent || isAgentResource) {
        // For Meta Agents / Agent resources: Call GET_AGENTS_BY_ID
        const agentId = tool?.agentic_application_id || tool?.agent_id || tool?.tool_id || tool?.id;
        if (agentId) {
          const agentData = await fetchData(APIs.GET_AGENTS_BY_ID + agentId);
          if (agentData) {
            // Agent editing is handled differently - typically redirects to AgentForm
            // For now, just show success and close
            addMessage("Agent data fetched successfully", "success");
            onClose();
          } else {
            addMessage("Failed to fetch agent details", "error");
          }
        }
      } else if (isServer && (mcpType === "file" || mcpType === "module" || mcpType === "url")) {
        // For all server types (LOCAL/FILE, EXTERNAL/MODULE, REMOTE/URL): Call MCP_GET_SERVER_BY_ID
        const serverId = tool?.tool_id || tool?.id;
        if (serverId) {
          const serverData = await getServerById(serverId);
          if (serverData) {
            setServerDataForEdit(serverData);
            setShowEditServerModal(true);
            // Expand the slider when showing edit form
            if (onExpandSlider) onExpandSlider(true);
          } else {
            addMessage("Failed to fetch server details", "error");
          }
        }
      } else if (!isServer) {
        // For regular tools: Use checkToolEditable which calls GET_TOOLS_BY_ID internally
        const isEditable = await checkToolEditable(tool, setShowForm, addMessage, setLoading);
        if (isEditable) onClose();
      }
    } catch (error) {
      addMessage("Failed to fetch resource details", "error");
    } finally {
      setLoading(false);
    }
  };

  const handleServerEditClose = () => {
    setShowEditServerModal(false);
    setServerDataForEdit(null);
    // Contract the slider when closing edit form
    if (onExpandSlider) onExpandSlider(false);
  };

  // Extract resource name for title
  const resourceName = tool?.tool_name || tool?.agentic_application_name || tool?.name || "Resource Details";

  return (
    <>
      {/* Normal detail modal - Hide when edit modal is open */}
      {!showEditServerModal && (
        <div className={styles.modalOverlay} onClick={onClose}>
          {loading && <Loader />}
          <div className={styles.modalContainer} onClick={(e) => e.stopPropagation()}>
            {/* Header with resource name and close button */}
            <div className={styles.modalTitleHeader}>
              <h2 className={styles.modalTitle}>{resourceName}</h2>
              <button className="closeBtn" aria-label="Close modal" onClick={onClose}>
                ×
              </button>
            </div>

            {/* Scrollable content area */}
            <div className={styles.modalContentScrollable}>
              {/* Description Section - Always shown when description exists */}
              {displayDescription && (
                <div className={styles.contentSection}>
                  <span className={styles.sectionLabel}>Description</span>
                  <p className={styles.descriptionText}>{displayDescription}</p>
                </div>
              )}

              {/* Endpoint - Show when endpoint exists (REMOTE/URL servers - mcp_type: "url") */}
              {displayEndpoint && (
                <div className={styles.endpointSection}>
                  <span className="label-desc">Endpoint</span>
                  <a href={displayEndpoint} target="_blank" rel="noopener noreferrer" className={styles.endpointLink}>
                    {displayEndpoint}
                  </a>
                </div>
              )}

              {/* Module - Show when moduleName is provided (EXTERNAL servers - mcp_type: "module") */}
              {displayModuleName && (
                <div className={styles.contentSection}>
                  <span className={styles.sectionLabel}>Module</span>
                  <div className={styles.moduleContent}>
                    <p className={styles.descriptionText}>{displayModuleName}</p>
                  </div>
                </div>
              )}

              {/* Code Snippet - Show when codeSnippet exists (LOCAL/FILE servers - mcp_type: "file" or regular tools) */}
              {displayCodeSnippet && (
                <div className={styles.contentSection}>
                  <span className={styles.sectionLabel}>Code Snippet</span>
                  <div className={styles.codeEditorWrapper}>
                    <CodeEditor
                      mode="python"
                      codeToDisplay={displayCodeSnippet}
                      width="100%"
                      height="250px"
                      fontSize={14}
                      readOnly={true}
                      setOptions={{
                        enableBasicAutocompletion: false,
                        enableLiveAutocompletion: false,
                        enableSnippets: false,
                        showLineNumbers: true,
                        tabSize: 4,
                        useWorker: false,
                        wrap: false,
                      }}
                      style={{
                        fontFamily: "Consolas, Monaco, 'Courier New', monospace",
                        border: "1px solid #e0e0e0",
                        borderRadius: "8px",
                      }}
                    />
                  </div>
                </div>
              )}

              {/* Workflow Description - Show when workflow description exists */}
              {displayWorkflowDescription && (
                <div className={styles.contentSection}>
                  <span className={styles.sectionLabel}>Workflow Description</span>
                  <div className={styles.markdownContent}>
                    <ReactMarkdown>{String(displayWorkflowDescription)}</ReactMarkdown>
                  </div>
                </div>
              )}

              {/* System Prompt - Show when systemPrompt exists */}
              {displaySystemPrompt && (
                <div className={styles.contentSection}>
                  <span className={styles.sectionLabel}>System Prompt</span>
                  <div className={styles.markdownContent}>
                    {(() => {
                      const promptObj = typeof displaySystemPrompt === "string" ? (() => { try { return JSON.parse(displaySystemPrompt); } catch { return {}; } })() : displaySystemPrompt;
                      return Object.entries(promptObj).map(([key, value]) => (
                        value ? <ReactMarkdown key={key}>{String(value)}</ReactMarkdown> : null
                      ));
                    })()}
                  </div>
                </div>
              )}
            </div>

            {/* Footer with Modify button - Original logic preserved */}
            {/* {!isMappedTool && agentType !== META_AGENT && agentType !== PLANNER_META_AGENT && !hideModifyButton && (
              <div className={styles.modalFooter}>
                <IAFButton type="primary" onClick={handleModify}>
                  Modify
                </IAFButton>
              </div>
            )} */}
          </div>
        </div>
      )}
      {/* Server Edit Modal - Shows within expanded ResourceSlider */}
      {showEditServerModal && (
        <div className={styles.serverEditModalOverlay}>
          <div className={styles.serverEditModalContainer}>
            <AddServer
              editMode={true}
              serverData={serverDataForEdit || tool}
              onClose={() => {
                handleServerEditClose();
                onClose(); // Also close the parent modal when AddServer closes
              }}
              setRefreshPaginated={() => { }}
            />
          </div>
        </div>
      )}
    </>
  );
};

export default ToolDetailModal;
