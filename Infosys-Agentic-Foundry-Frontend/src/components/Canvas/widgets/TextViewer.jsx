import React, { useState } from "react";
import styles from "./TextViewer.module.css";
import SVGIcons from "../../../Icons/SVGIcons";
import { copyToClipboard } from "../../../utils/clipboardUtils";

const TextViewer = ({ content, messageId }) => {
  const [copySuccess, setCopySuccess] = useState(false);

  // Ensure content is always a string
  const safeContent = React.useMemo(() => {
    if (typeof content === "string") return content;
    if (content === null || content === undefined) return "";
    return JSON.stringify(content, null, 2);
  }, [content]);

  const handleCopy = async () => {
    const success = await copyToClipboard(safeContent);
    if (success) {
      setCopySuccess(true);
      setTimeout(() => setCopySuccess(false), 2000);
    } else {
      console.error("Copy operation failed");
    }
  };

  const handleDownload = () => {
    const blob = new Blob([safeContent], { type: "text/plain" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `text-${messageId || Date.now()}.txt`;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
  };

  if (!safeContent) {
    return (
      <div className={styles.emptyState}>
        <SVGIcons icon="file" width={32} height={32} fill="currentColor" />
        <p className={styles.emptyMessage}>No text content to display</p>
      </div>
    );
  }

  return (
    <div className={styles.textViewer}>
      {/* Toolbar */}
      <div className={styles.toolbar}>
        <div className={styles.toolbarLeft}>
          <div className={styles.contentTag}>
            <SVGIcons icon="file" width={14} height={14} fill="currentColor" />
            <span>Text</span>
          </div>
        </div>

        <div className={styles.toolbarActions}>
          <button className={styles.toolbarButton} onClick={handleDownload} title="Download text">
            <svg width="16" height="16" viewBox="0 0 20 20" fill="none">
              <path d="M10 13V3M7 10L10 13L13 10M5 17H15" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
            </svg>
          </button>

          <button className={`${styles.toolbarButton} ${copySuccess ? styles.copied : ""}`} onClick={handleCopy} title="Copy text">
            {copySuccess ? (
              <svg width="16" height="16" viewBox="0 0 20 20" fill="none">
                <path d="M16 6L8.5 14.5L4 10" stroke="#22c55e" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
              </svg>
            ) : (
              <SVGIcons icon="fa-regular fa-copy" width={14} height={14} fill="currentColor" />
            )}
          </button>
        </div>
      </div>

      {/* Text Content */}
      <div className={styles.textContent}>
        <pre className={styles.textPre}>{safeContent}</pre>
      </div>

      {/* Footer */}
      <div className={styles.footer}>
        <div className={styles.stats}>
          <span className={styles.stat}>Lines: {safeContent.split("\n").length}</span>
          <span className={styles.stat}>Characters: {safeContent.length}</span>
          <span className={styles.stat}>Words: {safeContent.split(/\s+/).filter((word) => word.length > 0).length}</span>
        </div>
      </div>
    </div>
  );
};

export default TextViewer;
