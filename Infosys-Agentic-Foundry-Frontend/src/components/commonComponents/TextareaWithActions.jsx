import React, { useState, useCallback } from "react";
import styles from "./TextareaWithActions.module.css";
import SVGIcons from "../../Icons/SVGIcons";
import ZoomPopup from "./ZoomPopup";
import { copyToClipboard } from "../../utils/clipboardUtils";

/**
 * TextareaWithActions - Reusable textarea with copy and expand functionality
 *
 * @param {Object} props
 * @param {string} props.name - Field name for form handling
 * @param {string} props.value - Current textarea value
 * @param {Function} props.onChange - Change handler (receives event object)
 * @param {string} props.label - Label text for the textarea
 * @param {boolean} props.disabled - Whether the textarea is disabled
 * @param {number} props.rows - Number of rows for the textarea
 * @param {string} props.placeholder - Placeholder text
 * @param {boolean} props.required - Whether the field is required
 * @param {boolean} props.showCopy - Show copy icon (default: true)
 * @param {boolean} props.showExpand - Show expand icon (default: true)
 * @param {boolean} props.readOnly - Whether the content is read-only in zoom popup
 * @param {string} props.zoomType - Type for ZoomPopup ("text" or "code")
 * @param {Function} props.onZoomSave - Custom save handler for zoom popup
 * @param {Object} props.style - Additional inline styles for textarea
 * @param {string} props.className - Additional class name for textarea
 */
const TextareaWithActions = ({
  name,
  value = "",
  onChange,
  label,
  disabled = false,
  rows = 4,
  placeholder = "",
  required = false,
  showCopy = true,
  showExpand = true,
  readOnly = false,
  zoomType = "text",
  onZoomSave,
  style = {},
  className = "",
}) => {
  // ============ State ============
  const [showZoomPopup, setShowZoomPopup] = useState(false);
  const [copied, setCopied] = useState(false);

  // ============ Constants ============
  const COPY_FEEDBACK_MS = 2000;

  // ============ Copy Handler ============
  const handleCopy = useCallback(async () => {
    if (!value) return;

    const success = await copyToClipboard(value);
    if (success) {
      setCopied(true);
      setTimeout(() => setCopied(false), COPY_FEEDBACK_MS);
    } else {
      console.error("Failed to copy text to clipboard");
    }
  }, [value]);

  // ============ Zoom Handlers ============
  const handleZoomClick = useCallback(() => {
    setShowZoomPopup(true);
  }, []);

  const handleZoomSave = useCallback(
    (updatedContent) => {
      if (onZoomSave) {
        onZoomSave(updatedContent);
      } else if (onChange) {
        // Create synthetic event for form compatibility
        const event = {
          target: {
            name,
            value: updatedContent,
          },
        };
        onChange(event);
      }
      setShowZoomPopup(false);
    },
    [name, onChange, onZoomSave],
  );

  const handleZoomClose = useCallback(() => {
    setShowZoomPopup(false);
  }, []);

  return (
    <div className={styles.textareaContainer}>
      {label && (
        <label className="label-desc" htmlFor={name} style={{ marginBottom: "6px" }}>
          {label}
          {required && <span className="required"> *</span>}
        </label>
      )}
      <div className={styles.textareaWrapper}>
        <textarea
          id={name}
          name={name}
          value={value}
          onChange={onChange}
          className={`textarea ${className}`}
          disabled={disabled}
          rows={rows}
          placeholder={placeholder}
          style={style}
        />

        {/* Copy Icon */}
        {showCopy && (
          <button type="button" className={styles.copyIcon} onClick={handleCopy} title="Copy to clipboard" disabled={!value}>
            <SVGIcons icon="fa-regular fa-copy" width={16} height={16} />
          </button>
        )}

        {/* Copied Feedback */}
        <span className={`${styles.copiedText} ${copied ? styles.visible : styles.hidden}`}>Copied!</span>

        {/* Expand Icon */}
        {showExpand && (
          <div className={styles.iconGroup}>
            <button type="button" className={styles.expandIcon} onClick={handleZoomClick} title="Expand">
              <SVGIcons icon="fa-solid fa-up-right-and-down-left-from-center" width={16} height={16} />
            </button>
          </div>
        )}
      </div>

      {/* Zoom Popup */}
      <ZoomPopup
        show={showZoomPopup}
        onClose={handleZoomClose}
        title={label || "Content"}
        content={value}
        onSave={handleZoomSave}
        type={zoomType}
        readOnly={readOnly || disabled}
      />
    </div>
  );
};

export default TextareaWithActions;
