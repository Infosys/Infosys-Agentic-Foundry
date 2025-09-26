import React, { useEffect, useState, useRef, useCallback } from "react";
import styles from "./ZoomPopup.module.css";
import { faCompress } from "@fortawesome/free-solid-svg-icons";
import { FontAwesomeIcon } from "@fortawesome/react-fontawesome";

const ZoomPopup = (props) => {
  const { show, onClose, title, content, onSave, recycleBin, type = "code" } = props;

  const [editableContent, setEditableContent] = useState(content || "");
  const [localDarkTheme] = useState(true);
  const textareaRef = useRef(null);
  const overlayRef = useRef(null);

  useEffect(() => {
    if (show) {
      setEditableContent(content || "");
      if (type === "text") {
        setTimeout(() => {
          if (textareaRef.current) {
            textareaRef.current.focus();
            textareaRef.current.setSelectionRange(0, 0);
            if (overlayRef.current) {
              overlayRef.current.scrollTop = 0;
              overlayRef.current.scrollLeft = 0;
            }
          }
        }, 100);
        setTimeout(() => {
          if (textareaRef.current && document.activeElement !== textareaRef.current) {
            textareaRef.current.focus();
            textareaRef.current.setSelectionRange(0, 0);
          }
        }, 250);
      }
    }
  }, [content, show, type]);

  // No effect syncing with parent theme; theme is always local

  const handleSave = () => {
    onSave(editableContent);
    onClose();
  };

  const handleInput = (value) => {
    setEditableContent(value);
  };

  if (!show) return null;

  return (
    <>
      <style>{`
        .code-textarea::selection {
          background-color: ${localDarkTheme ? "#264f78" : "#add6ff"} !important;
          color: ${localDarkTheme ? "#ffffff" : "#000000"} !important;
        }
        .code-textarea::-moz-selection {
          background-color: ${localDarkTheme ? "#264f78" : "#add6ff"} !important;
          color: ${localDarkTheme ? "#ffffff" : "#000000"} !important;
        }
        .code-textarea {
          caret-color: ${localDarkTheme ? "#ffffff" : "#000000"} !important;
        }
      `}</style>
      <div className={styles.popup}>
        <div className={styles.popupContent}>
          <button
            type="button"
            onClick={onClose}
            title="Collapse"
            style={{
              position: "absolute",
              top: "10px",
              right: "50px",
              background: "rgba(0, 0, 0, 0.1)",
              border: "1px solid rgba(255, 255, 255, 0.2)",
              cursor: "pointer",
              borderRadius: "4px",
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              width: "28px",
              height: "28px",
              zIndex: 20,
              transition: "all 0.2s ease",
            }}
            onMouseEnter={(e) => {
              e.target.style.transform = "scale(1.1)";
              e.target.style.background = "rgba(0, 0, 0, 0.2)";
            }}
            onMouseLeave={(e) => {
              e.target.style.transform = "scale(1)";
              e.target.style.background = "rgba(0, 0, 0, 0.1)";
            }}>
            <FontAwesomeIcon
              icon={faCompress}
              style={{
                width: "16px",
                height: "14px",
                color: "#000000",
                transform: "scale(1)",
                paddingTop: "2px",
              }}
            />
          </button>
          <h3>{title}</h3>
          <div className={styles.editorContainer} style={{ position: "relative" }}>
            {type === "code" ? (
              <textarea
                className={styles.codeTextarea}
                value={editableContent || ""}
                onChange={handleInput}
                placeholder="Enter your code here..."
                rows={15}
                style={{
                  width: "100%",
                  resize: "vertical",
                  fontFamily: "Consolas, Monaco, 'Courier New', monospace",
                  fontSize: "14px",
                  lineHeight: "1.4",
                  padding: "12px",
                  border: "1px solid #e0e0e0",
                  borderRadius: "8px",
                  backgroundColor: localDarkTheme ? "#1e1e1e" : "#ffffff",
                  color: localDarkTheme ? "#ffffff" : "#000000",
                  outline: "none",
                  boxSizing: "border-box",
                  minHeight: "250px"
                }}
              />
            ) : (
              <textarea
                ref={textareaRef}
                value={editableContent}
                onChange={(e) => setEditableContent(e.target.value)}
                style={{
                  width: "100%",
                  height: "200px",
                  fontSize: "16px",
                  fontFamily: "inherit",
                  border: "1px solid #e0e0e0",
                  borderRadius: "8px",
                  padding: "12px",
                  background: "#fff",
                  color: "#000",
                  resize: "vertical",
                  outline: "none",
                  marginTop: "8px",
                }}
              />
            )}
          </div>
          <div className={styles.popupFooter}>
            {!recycleBin && (
              <button className={styles.saveButton} onClick={handleSave}>
                Ok
              </button>
            )}
            <button className={styles.cancelButton} onClick={onClose}>
              Cancel
            </button>
          </div>
        </div>
      </div>
    </>
  );
};

export default ZoomPopup;
