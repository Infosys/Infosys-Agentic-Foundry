import React, { useState, useRef } from "react";
import { Prism as SyntaxHighlighter } from "react-syntax-highlighter";
import { oneLight } from "react-syntax-highlighter/dist/esm/styles/prism";
import styles from "./CodeViewer.module.css";
import SVGIcons from "../../../Icons/SVGIcons";
import CodeEditor from "../../commonComponents/CodeEditor.jsx";
import { copyToClipboard } from "../../../utils/clipboardUtils";

const CodeViewer = ({ content, messageId, language = "python" }) => {
  const [copySuccess, setCopySuccess] = useState(false);
  const [isEditMode, setIsEditMode] = useState(false);
  // Safely handle content - ensure it's always a string
  const safeContent = React.useMemo(() => {
    if (typeof content === "string") return content;
    if (content === null || content === undefined) return "";

    // Handle object with content property (common API response structure)
    if (typeof content === "object") {
      // If it has a content property, extract it
      if (content.content && typeof content.content === "string") {
        return content.content;
      }

      // If it has a code property, extract it
      if (content.code && typeof content.code === "string") {
        return content.code;
      }

      // If it has a text property, extract it
      if (content.text && typeof content.text === "string") {
        return content.text;
      }

      // If it has a data property, extract it
      if (content.data && typeof content.data === "string") {
        return content.data;
      }

      // Fallback to JSON stringify for other objects
      try {
        return JSON.stringify(content, null, 2);
      } catch (error) {
        return String(content);
      }
    }

    return String(content);
  }, [content]);

  const [editedContent, setEditedContent] = useState(safeContent);
  const textareaRef = useRef(null); // Auto-detect language from content if not provided
  const detectedLanguage = content.type === "json" ? "json" : content.language ? content.language : "python";
  const handleCopy = async () => {
    const success = await copyToClipboard(editedContent || safeContent);
    if (success) {
      setCopySuccess(true);
      setTimeout(() => setCopySuccess(false), 2000);
    } else {
      console.error("Failed to copy to clipboard");
    }
  };

  const toggleEditMode = () => {
    if (isEditMode) {
      // Save changes when exiting edit mode
      setEditedContent(textareaRef.current?.value || safeContent);
    }
    setIsEditMode(!isEditMode);
  };
  const handleDownload = () => {
    const blob = new Blob([editedContent || safeContent], { type: "text/plain" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `iaf_code.${getFileExtension(detectedLanguage)}`;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
  };

  const getFileExtension = (lang) => {
    const extensions = {
      javascript: "js",
      python: "py",
      html: "html",
      css: "css",
      sql: "sql",
      php: "php",
      cpp: "cpp",
      java: "java",
      go: "go",
      typescript: "ts",
      json: "json",
      xml: "xml",
      yaml: "yml",
      bash: "sh",
    };
    return extensions[lang] || "txt";
  };

  if (!content && !editedContent) {
    return (
      <div className={styles.emptyState}>
        <SVGIcons icon="hardware-chip" width={32} height={32} />
        <p className={styles.emptyMessage}>No code content to display</p>
      </div>
    );
  }

  return (
    <div className={styles.codeViewer}>
      {/* Toolbar */}
      <div className={styles.toolbar}>
        {/* <div className={styles.toolbarLeft}>
          <div className={styles.languageTag}>
            <SVGIcons icon="hardware-chip" width={14} height={14} fill="#007acc" />
            <span>{detectedLanguage}</span>
          </div>
          {(editedContent !== content && editedContent) && (
            <div className={styles.modifiedIndicator}>
              <span>Modified</span>
            </div>
          )}
        </div> */}

        <div className={styles.toolbarActions}>
          {/* <button
            className={styles.toolbarButton}
            onClick={toggleEditMode}
            title={isEditMode ? 'Exit edit mode' : 'Edit code'}
          >
            {isEditMode ? (
              <SVGIcons icon="eyeIcon" width={14} height={14} fill="#666" />
            ) : (
              <SVGIcons icon="fa-solid fa-pen" width={12} height={12} fill="#666" />
            )}
          </button> */}

          <button className={styles.toolbarButton} onClick={handleDownload} title="Download code">
            <svg width="14" height="14" viewBox="0 0 20 20" fill="none">
              <path d="M10 13V3M7 10L10 13L13 10M5 17H15" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
            </svg>
          </button>

          <button
            className={`${styles.toolbarButton} ${copySuccess ? styles.copied : ""}`}
            onClick={handleCopy}
            title="Copy code"
            disabled={!safeContent || safeContent.trim() === ""}
            style={{ opacity: !safeContent || safeContent.trim() === "" ? 0.4 : 1, cursor: !safeContent || safeContent.trim() === "" ? "not-allowed" : "pointer" }}>
            {copySuccess ? (
              <svg width="14" height="14" viewBox="0 0 20 20" fill="none">
                <path d="M16 6L8.5 14.5L4 10" stroke="#22c55e" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
              </svg>
            ) : (
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none">
                <rect x="9" y="9" width="11" height="11" rx="2" stroke="currentColor" strokeWidth="1.5" />
                <path d="M5 15H4C2.89543 15 2 14.1046 2 13V4C2 2.89543 2.89543 2 4 2H13C14.1046 2 15 2.89543 15 4V5" stroke="currentColor" strokeWidth="1.5" />
              </svg>
            )}
          </button>
        </div>
      </div>{" "}
      {/* Code Content */}
      <div className={styles.codeContent}>
        {isEditMode ? (
          <CodeEditor
            mode={language === "python" ? "python" : language === "javascript" ? "javascript" : language === "java" ? "java" : "python"}
            codeToDisplay={editedContent || safeContent}
            onChange={(value) => setEditedContent(value)}
            width="100%"
            height="400px"
            fontSize={13}
            setOptions={{
              enableBasicAutocompletion: true,
              enableLiveAutocompletion: true,
              enableSnippets: true,
              showLineNumbers: true,
              tabSize: 4,
              useWorker: false,
              wrap: false,
            }}
            style={{
              border: "1px solid var(--border)",
              borderRadius: "8px",
              fontFamily: "'Monaco', 'Menlo', 'Ubuntu Mono', 'Consolas', 'source-code-pro', monospace !important",
            }}
          />
        ) : (
          <SyntaxHighlighter
            language={detectedLanguage}
            style={oneLight}
            showLineNumbers={true}
            wrapLines={true}
            wrapLongLines={true}
            customStyle={{
              margin: 0,
              padding: "16px",
              background: "transparent",
              fontSize: "13px",
              lineHeight: "1.5",
            }}
            codeTagProps={{
              style: {
                fontFamily: "'Monaco', 'Menlo', 'Ubuntu Mono', 'Consolas', monospace",
              },
            }}>
            {editedContent || safeContent}
          </SyntaxHighlighter>
        )}
      </div>
      {/* Footer with stats */}
      <div className={styles.footer}>
        <div className={styles.stats}>
          <span className={styles.stat}>Lines: {(editedContent || safeContent).split("\n").length}</span>
          <span className={styles.stat}>Characters: {(editedContent || safeContent).length}</span>
        </div>
      </div>
    </div>
  );
};

export default CodeViewer;
