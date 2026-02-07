import { useState } from "react";
import styles from "./ToolDetailModal.module.css";
import ReactMarkdown from "react-markdown";
import { META_AGENT, PLANNER_META_AGENT } from "../../constant";
import { useMessage } from "../../Hooks/MessageContext";
import Loader from "../commonComponents/Loader";
import { useToolsAgentsService } from "../../services/toolService";
import AddServer from "../AgentOnboard/AddServer.jsx";
import Cookies from "js-cookie";
import { useMcpServerService } from "../../services/serverService";
import CodeEditor from "../commonComponents/CodeEditor.jsx";

const ToolDetailModal = ({
  isOpen,
  onClose,
  description,
  endpoint,
  codeSnippet,
  agenticApplicationWorkflowDescription,
  systemPrompt,
  isMappedTool,
  setShowForm,
  agentType,
  tool,
  useToolCardDescriptionStyle = false,
  hideModifyButton = false,
}) => {
  const { addMessage } = useMessage();
  const [loading, setLoading] = useState(false);
  const [showEditServerModal, setShowEditServerModal] = useState(false);
  const { checkToolEditable } = useToolsAgentsService();
  const { updateServer } = useMcpServerService();

  if (!isOpen) return null;

  const handleModify = async (e) => {
    e.preventDefault();
    if (tool.tool_id?.includes("mcp_file")) {
      const tagsArray = [];
      const mapItem = tool.raw ? tool.raw : tool;
      mapItem.tags.forEach((tagItem) => {
        tagsArray.push(tagItem.tag_id);
      });
      const mcpModifyPayload = {
        code_content: mapItem.mcp_config.args[1],
        created_by: mapItem.created_by,
        is_admin: true,
        mcp_module_name: "",
        mcp_type: mapItem.mcp_type,
        mcp_url: "",
        tag_ids: tagsArray,
        team_id: "Public",
        tool_description: mapItem.tool_description,
        tool_id: mapItem.tool_id,
        tool_name: mapItem.tool_name,
        updated_tag_id_list: tagsArray,
        user_email_id: Cookies.get("email") || "Guest",
      };
      const mcpModifyFromAgentList = await updateServer(tool.tool_id, mcpModifyPayload);
      if (mcpModifyFromAgentList) {
        setShowEditServerModal(true);
      }
    } else {
      const isEditable = await checkToolEditable(tool, setShowForm, addMessage, setLoading);
      if (isEditable) onClose();
    }
  };

  const handleServerEditClose = () => {
    setShowEditServerModal(false);
  };

  return (
    <>
      {/* Normal detail modal - always visible */}
      <div className={styles.modalOverlay} onClick={onClose}>
        {loading && <Loader />}
        <div className={styles.modalContainer} onClick={(e) => e.stopPropagation()}>
          {" "}
          <div className={styles.closeBtnContainer}>
            <h2>Description</h2>
            <button
              className={styles.closeBtn}
              style={{ position: "static", fontSize: 24, background: "#fff", border: "none", color: "#3D4359", cursor: "pointer", marginLeft: "auto" }}
              aria-label="Close tool details modal"
              onClick={onClose}>
              ×
            </button>
          </div>
          <div
            className={useToolCardDescriptionStyle ? `${styles.modalBody} ${styles.toolCardDescription}` : `${styles.modalBody} ${styles.description} ${styles.descriptionFont}`}>
            <textarea
              value={description}
              // onChange={(e) => {
              //   if (typeof setShowForm === "function") setShowForm((prev) => ({ ...prev, description: e.target.value }));
              // }}
              className={`${styles.descriptionFont} ${styles.descriptionTextarea}`}
            />
          </div>
          {endpoint && (
            <div className={styles.modalHeader}>
              <h2>Endpoint</h2>
            </div>
          )}
          {endpoint && (
            <div className={`${styles.modalBody} ${styles.description} ${styles.descriptionFont}`}>
              {/* <textarea
                value={endpoint}
                readOnly={true}
                className={`${styles.descriptionFont} ${styles.descriptionTextarea}`}
                style={{ backgroundColor: "#f5f5f5", cursor: "default" }}
              /> */}
              <a href="{endpoint}" target="_blank" rel="noopener noreferrer">
                {endpoint}
              </a>
            </div>
          )}
          {codeSnippet && tool?.mcp_type === "module" && (
            <>
              <div className={styles.modalHeader}>
                <h2>Module</h2>
              </div>
              <div className={`${styles.modalBody} ${styles.description} ${styles.descriptionFont}`}>
                <textarea
                  value={codeSnippet}
                  readOnly={true}
                  className={`${styles.descriptionFont} ${styles.descriptionTextarea}`}
                  style={{ backgroundColor: "#f5f5f5", cursor: "default" }}
                />
              </div>
            </>
          )}
          {((codeSnippet && tool?.mcp_type === "file") || (codeSnippet && !tool.tool_id.includes("mcp_"))) && (
            <div className={styles.modalHeader}>
              <h2>Code Snippet</h2>
            </div>
          )}
          {((codeSnippet && tool?.mcp_type === "file") || (codeSnippet && !tool.tool_id.includes("mcp_"))) && (
            <div className={`${styles.modalBody} ${styles.codeSnippet}`}>
              <div className={styles.codeEditorContainer}>
                <CodeEditor
                  mode="python"
                  theme="monokai"
                  isDarkTheme={true}
                  value={codeSnippet}
                  width="100%"
                  height="300px"
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
          {agenticApplicationWorkflowDescription && (
            <div className={styles.modalHeader}>
              <h2>Workflow Description</h2>
            </div>
          )}
          {agenticApplicationWorkflowDescription && (
            <div className={`${styles.modalBody} ${styles.codeSnippet} ${styles.descriptionFont}`}>
              <ReactMarkdown>{String(agenticApplicationWorkflowDescription)}</ReactMarkdown>
            </div>
          )}
          {systemPrompt && (
            <div className={styles.modalHeader}>
              <h2>System Prompt</h2>
            </div>
          )}
          {systemPrompt && (
            <div className={`${styles.modalBody} ${styles.codeSnippet}`}>
              <ReactMarkdown>
                {typeof systemPrompt === "string" ? JSON.parse(systemPrompt)?.SYSTEM_PROMPT_REACT_AGENT || "" : systemPrompt?.SYSTEM_PROMPT_REACT_AGENT || ""}
              </ReactMarkdown>
              <ReactMarkdown>
                {typeof systemPrompt === "string" ? JSON.parse(systemPrompt)?.SYSTEM_PROMPT_EXECUTOR_AGENT || "" : systemPrompt?.SYSTEM_PROMPT_EXECUTOR_AGENT || ""}
              </ReactMarkdown>
            </div>
          )}
          {!isMappedTool && agentType !== META_AGENT && agentType !== PLANNER_META_AGENT && !hideModifyButton && (
            <div className={styles.modalFooter}>
              <button className={styles.modifyBtn} onClick={handleModify}>
                Modify
              </button>
            </div>
          )}
        </div>{" "}
      </div>{" "}
      {/* Server Edit Modal - Appears as an overlay on top of the detail modal when editing */}
      {showEditServerModal && (
        <div className={styles.serverEditModalOverlay} onClick={handleServerEditClose}>
          <div className={styles.serverEditModalContainer} onClick={(e) => e.stopPropagation()}>
            <button className={styles.closeBtn} onClick={handleServerEditClose}>
              &times;
            </button>{" "}
            <AddServer
              editMode={true}
              serverData={tool}
              onClose={() => {
                handleServerEditClose();
                onClose(); // Also close the parent modal when AddServer closes
              }}
              setRefreshPaginated={() => {}}
            />
          </div>
        </div>
      )}
    </>
  );
};

export default ToolDetailModal;
