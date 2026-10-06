import React, { useState } from "react";
import ReactDOM from "react-dom";
import styles from "./FileConflictModal.module.css";
import SVGIcons from "../../../Icons/SVGIcons";
import IAFButton from "../../../iafComponents/GlobalComponents/Buttons/Button";

const FileConflictModal = ({ warnings, onOverwrite, onDefaultFolder, onCustomFolder, onClose, loading = false }) => {
  const [customFolder, setCustomFolder] = useState("");

  // warnings shape: { files: string[], message: string, conflict_path: string }
  const conflictFiles = warnings?.files || [];
  const conflictPath = warnings?.conflict_path;

  const handleCustomUpload = () => {
    if (customFolder.trim()) {
      onCustomFolder(customFolder.trim());
      setCustomFolder("");
    }
  };

  return ReactDOM.createPortal(
    <div className={styles.overlay} onClick={onClose}>
      <div className={styles.modal} onClick={(e) => e.stopPropagation()}>
        <div className={styles.header}>
          <h3 className={styles.title}>File Conflict</h3>
          <button className={styles.closeBtn} onClick={onClose} disabled={loading} aria-label="Close">
            <SVGIcons icon="x" width={18} height={18} color="#6B7280" />
          </button>
        </div>

        <div className={styles.body}>
          <p className={styles.subtext}>The following file(s) already exist:</p>

          <div className={styles.warningList}>
            {conflictFiles.map((fileName, idx) => (
              <div key={idx} className={styles.warningItem}>
                <SVGIcons icon="warnings" width={16} height={16} color="#f59e0b" />
                <div className={styles.warningDetails}>
                  <span className={styles.fileName}>{fileName}</span>
                  {conflictPath && (
                    <span className={styles.conflictPath}>in: {conflictPath}</span>
                  )}
                </div>
              </div>
            ))}
          </div>

          <div className={styles.actions}>
            <IAFButton type="danger" onClick={onOverwrite} disabled={loading} loading={loading}>
              Overwrite
            </IAFButton>
            <IAFButton type="secondary" onClick={onDefaultFolder} disabled={loading}>
              Default Folder
            </IAFButton>
          </div>

          <div className={styles.divider}>
            <span>or save to a different folder</span>
          </div>

          <div className={styles.customFolderRow}>
            <input
              type="text"
              className={styles.customFolderInput}
              placeholder="Enter folder name..."
              value={customFolder}
              onChange={(e) => setCustomFolder(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && handleCustomUpload()}
              disabled={loading}
            />
            <IAFButton
              type="primary"
              onClick={handleCustomUpload}
              disabled={!customFolder.trim() || loading}
              loading={loading}
            >
              Upload
            </IAFButton>
          </div>
        </div>
      </div>
    </div>,
    document.body
  );
};

export default FileConflictModal;
