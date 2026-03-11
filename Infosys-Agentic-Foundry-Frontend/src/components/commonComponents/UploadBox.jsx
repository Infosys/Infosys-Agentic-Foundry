import React from "react";
import SVGIcons from "../../Icons/SVGIcons.js";
import styles from "./UploadBox.module.css";

/**
 * Formats file size to human readable format
 * @param {number} bytes - File size in bytes
 * @returns {string} Formatted file size (e.g., "726.7 KB")
 */
const formatFileSize = (bytes) => {
  if (!bytes || bytes === 0) return "0 Bytes";
  const k = 1024;
  const sizes = ["Bytes", "KB", "MB", "GB"];
  const i = Math.floor(Math.log(bytes) / Math.log(k));
  return parseFloat((bytes / Math.pow(k, i)).toFixed(1)) + " " + sizes[i];
};

/**
 * Get file icon based on file extension
 * @param {string} fileName - Name of the file
 * @returns {string} Icon name for SVGIcons
 */
const getFileIcon = (fileName) => {
  const ext = fileName.split(".").pop()?.toLowerCase();
  if (["pdf"].includes(ext)) return "file-pdf";
  if (["csv", "xlsx", "xls"].includes(ext)) return "file-csv";
  if (["jpg", "jpeg", "png", "gif", "bmp", "svg", "webp", "img"].includes(ext)) return "file-image";
  return "file-default";
};

/**
 * UploadBox - A reusable file upload component with drag-and-drop support
 * Always shows the upload area, with selected files displayed below
 *
 * @param {Object} props
 * @param {File|File[]|null} props.file - Single file or array of files (for multi-file mode)
 * @param {File[]|null} props.files - Alternative prop for multiple files (takes precedence if provided)
 * @param {boolean} props.isDragging - Whether user is currently dragging over the component
 * @param {function} props.onDragEnter - Handler for drag enter event
 * @param {function} props.onDragLeave - Handler for drag leave event
 * @param {function} props.onDragOver - Handler for drag over event
 * @param {function} props.onDrop - Handler for drop event
 * @param {function} props.onClick - Handler for click to upload
 * @param {function} props.onRemoveFile - Handler for removing a file (receives index for multi-file)
 * @param {boolean} props.loading - Whether the component is in loading state
 * @param {string} props.fileInputId - ID of the hidden file input
 * @param {string} props.acceptedFileTypes - Accepted file types for input
 * @param {string} props.supportedText - Text showing supported file types
 * @param {string} props.dragText - Text shown when dragging
 * @param {string} props.uploadText - Main upload button text
 * @param {string} props.dragDropText - Text after upload button
 * @param {boolean} props.disabled - Whether the component is disabled
 * @param {string} props.disabledHint - Hint text shown when disabled (explains why)
 * @param {boolean} props.multiple - Whether multiple files can be uploaded
 */
const UploadBox = ({
  file,
  files: filesProp,
  isDragging,
  onDragEnter,
  onDragLeave,
  onDragOver,
  onDrop,
  onClick,
  onRemoveFile,
  loading = false,
  fileInputId,
  acceptedFileTypes = ".py",
  supportedText = "Supported: .py",
  dragText = "Drop file here",
  uploadText = "Click to upload",
  dragDropText = " or drag and drop",
  disabled = false,
  disabledHint = "",
  multiple = false,
}) => {
  // Normalize files - support both single file and array of files
  const normalizedFiles = React.useMemo(() => {
    if (filesProp && Array.isArray(filesProp) && filesProp.length > 0) {
      return filesProp;
    }
    if (file) {
      return Array.isArray(file) ? file : [file];
    }
    return [];
  }, [file, filesProp]);

  const hasFiles = normalizedFiles.length > 0;

  return (
    <div className={styles.uploadBoxWrapper}>
      {/* Always visible drag-drop area */}
      <div
        className={`
          ${styles.uploadContainer}
          ${loading || disabled ? styles.uploadContainerDisabled : styles.uploadContainerEnabled}
        `}
        onDragEnter={!disabled ? onDragEnter : undefined}
        onDragLeave={!disabled ? onDragLeave : undefined}
        onDragOver={!disabled ? onDragOver : undefined}
        onDrop={!disabled ? onDrop : undefined}
        onClick={!loading && !disabled ? onClick : undefined}
        tabIndex={disabled ? -1 : 0}
        role="button"
        aria-disabled={disabled}
        aria-label="Upload File">
        <div className={`${styles.uploadPrompt}`}>
          <div className={styles.iconContainer}>
            <SVGIcons icon="upload" width={20} height={20} color={disabled ? "var(--muted)" : "var(--content-color)"} />
          </div>
          <div>
            <p className={styles.uploadPromptText}>
              {disabled && disabledHint ? (
                <span className={styles.disabledHintText}>{disabledHint}</span>
              ) : isDragging ? (
                dragText
              ) : (
                <>
                  <span className={styles.uploadPromptHighlight}>{uploadText}</span>
                  {dragDropText}
                </>
              )}
            </p>
            {!disabled && <p className={styles.supportedText}>{supportedText}</p>}
          </div>
        </div>
      </div>

      {/* Files list displayed below the upload area */}
      {hasFiles && (
        <div className={styles.filesListSection}>
          <label className="label-desc">Files to Upload ({normalizedFiles.length})</label>
          <div className={styles.filesList}>
            {normalizedFiles.map((f, index) => (
              <div key={`${f.name}-${index}`} className={styles.fileItem}>
                <div className={styles.fileItemLeft}>
                  <div className={styles.fileItemIcon}>
                    <SVGIcons icon={getFileIcon(f.name)} width={20} height={20} color="#0073CF" />
                  </div>
                  <div className={styles.fileItemInfo}>
                    <span className={styles.fileItemName} title={f.name}>
                      {f.name}
                    </span>
                    <span className={styles.fileItemSize}>{formatFileSize(f.size)}</span>
                  </div>
                </div>
                <button type="button" onClick={() => onRemoveFile && onRemoveFile(index)} className={styles.fileItemRemoveBtn} aria-label={`Remove ${f.name}`} disabled={disabled}>
                  <SVGIcons icon="x" width={16} height={16} color={disabled ? "var(--muted)" : "#ef4444"} />
                </button>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
};

export default UploadBox;
