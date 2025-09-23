import Editor from '@monaco-editor/react';
import React, { useState } from "react";
import styles from "./ToolDetailModal.module.css";
import ReactMarkdown from "react-markdown";
import Markdown from "react-markdown";
import { META_AGENT,MULTI_AGENT } from "../../constant";
import { checkToolEditable } from "../../util";
import { useMessage } from "../../Hooks/MessageContext";
import Loader from "../commonComponents/Loader";

const ToolDetailModal = ({
  isOpen,
  onClose,
  description,
  codeSnippet,
  agenticApplicationWorkflowDescription,
  systemPrompt,
  isMappedTool,
  setShowForm,
  agentType,
  tool,
}) => {
  const { addMessage } = useMessage();
  const [loading, setLoading] = useState(false);
  if (!isOpen) return null;

  const handleModify = async (e) => {
    e.preventDefault();
    const isEditable = await checkToolEditable(tool, setShowForm, addMessage, setLoading);
    if (isEditable) onClose();
  };

  return (
    <div className={styles.modalOverlay} onClick={onClose}>
      {loading && <Loader />}
      <div
        className={styles.modalContainer}
        onClick={(e) => e.stopPropagation()}
      >
        <div className={styles.closeBtnContainer}>
          <h2>Description</h2>
          <div className={styles.closeBtn}>
            <button onClick={onClose}>&times;</button>
          </div>
        </div>
        <div
          className={`${styles.modalBody} ${styles.description} ${styles.descriptionFont}`}
        >
          <p>{description}</p>
        </div>
        {codeSnippet && (
          <div className={styles.modalHeader}>
            <h2>Code Snippet</h2>
          </div>
        )}
        {codeSnippet && (
                   <div className={`${styles.modalBody} ${styles.codeSnippet}`}>
         <div className={styles.codeEditorContainer}>
            <Editor
              height="200px"
              defaultLanguage="python"
              value={codeSnippet}
              theme="vs-dark"
              options={{
                readOnly: true,
                minimap: { enabled: false },
                fontSize: 14,
                scrollBeyondLastLine: false,
                lineNumbers: 'on',
                wordWrap: 'on',
                domReadOnly: true,
                renderLineHighlight: 'all',
                scrollbar: { vertical: 'auto', horizontal: 'auto' },
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
          <div
            className={`${styles.modalBody} ${styles.codeSnippet} ${styles.descriptionFont}`}
          >
            <p>{agenticApplicationWorkflowDescription}</p>
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
              {typeof systemPrompt === "string"
                ? JSON.parse(systemPrompt)?.SYSTEM_PROMPT_REACT_AGENT || ""
                : systemPrompt?.SYSTEM_PROMPT_REACT_AGENT || ""}
            </ReactMarkdown>
            <ReactMarkdown>
              {typeof systemPrompt === "string"
                ? JSON.parse(systemPrompt)?.SYSTEM_PROMPT_EXECUTOR_AGENT || ""
                : systemPrompt?.SYSTEM_PROMPT_EXECUTOR_AGENT || ""}
            </ReactMarkdown>
          </div>
        )}
        {!isMappedTool && agentType !== META_AGENT && (
          <div className={styles.modalFooter}>
            <button className={styles.modifyBtn} onClick={handleModify}>
              Modify
            </button>
          </div>
        )}
      </div>
    </div>
  );
};

export default ToolDetailModal;