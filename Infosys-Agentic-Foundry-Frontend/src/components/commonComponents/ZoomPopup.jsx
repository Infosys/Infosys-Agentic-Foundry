import React, { useEffect, useState, useRef, useCallback } from "react";
import ReactDOM from "react-dom";
import styles from "./ZoomPopup.module.css";
import { faCompress } from "@fortawesome/free-solid-svg-icons";
import { FontAwesomeIcon } from "@fortawesome/react-fontawesome";
import CodeEditor from "./CodeEditor.jsx";
import IAFButton from "../../iafComponents/GlobalComponents/Buttons/Button.jsx";
import { sanitizeInput } from "../../utils/sanitization";
import SVGIcons from "../../Icons/SVGIcons";
import { copyToClipboard } from "../../utils/clipboardUtils";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

const ZoomPopup = (props) => {
  const { show, onClose, title, content, onSave, recycleBin, type = "code", readOnly = false, hideFooter = false, showCopy = false } = props;

  const [editableContent, setEditableContent] = useState(content || "");
  const [copied, setCopied] = useState(false);

  // Copy handler
  const handleCopy = useCallback(async () => {
    if (!editableContent) return;
    const success = await copyToClipboard(editableContent);
    if (success) {
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    }
  }, [editableContent]);
  const [editorHeight, setEditorHeight] = useState("300px");
  const textareaRef = useRef(null);
  const overlayRef = useRef(null);
  const editorContainerRef = useRef(null);

  useEffect(() => {
    if (show) {
      setEditableContent(content || "");

      // Calculate editor height based on container
      const calculateHeight = () => {
        if (editorContainerRef.current) {
          const containerHeight = editorContainerRef.current.clientHeight;
          setEditorHeight(`${Math.max(containerHeight - 10, 200)}px`);
        }
      };

      // Initial calculation with delay to allow DOM to render
      setTimeout(calculateHeight, 50);

      // Recalculate on window resize
      window.addEventListener("resize", calculateHeight);

      if (type === "text") {
        setTimeout(() => {
          if (textareaRef.current) {
            const len = textareaRef.current.value.length;
            textareaRef.current.focus();
            textareaRef.current.setSelectionRange(len, len);
            // Scroll to bottom to show cursor at end
            textareaRef.current.scrollTop = textareaRef.current.scrollHeight;
          }
        }, 100);
        setTimeout(() => {
          if (textareaRef.current && document.activeElement !== textareaRef.current) {
            const len = textareaRef.current.value.length;
            textareaRef.current.focus();
            textareaRef.current.setSelectionRange(len, len);
            textareaRef.current.scrollTop = textareaRef.current.scrollHeight;
          }
        }, 250);
      }

      return () => {
        window.removeEventListener("resize", calculateHeight);
      };
    }
  }, [content, show, type]);

  const handleSave = () => {
    if (!readOnly) {
      onSave(editableContent);
      onClose();
    }
  };

  if (!show) return null;

  return ReactDOM.createPortal(
    <div className={styles.popup} onClick={onClose}>
      <div className={styles.popupContent} onClick={(e) => e.stopPropagation()}>
        <div className={styles.popupHeader}>
          <h3>{title}</h3>
          <div className={styles.headerActions}>
            {showCopy && (
              <button
                type="button"
                className={styles.copyBtn}
                onClick={handleCopy}
                title={copied ? "Copied!" : "Copy to clipboard"}
                disabled={!editableContent}
              >
                <SVGIcons icon="fa-regular fa-copy" width={16} height={16} />
                {copied && <span className={styles.copiedBadge}>Copied!</span>}
              </button>
            )}
            <button className={`closeBtn ${styles.collapseBtn}`} aria-label="Close modal" onClick={onClose}>
              ×
            </button>
          </div>
        </div>
        <div ref={editorContainerRef} className={styles.editorContainer} style={hideFooter ? { marginBottom: 0 } : {}}>
          {type === "code" ? (
            <div className={styles.codeEditorWrapper}>
              <CodeEditor
                mode="python"
                codeToDisplay={editableContent || ""}
                onChange={readOnly ? undefined : (value) => setEditableContent(value)}
                readOnly={readOnly}
                width="100%"
                height={editorHeight}
                fontSize={14}
                showLanguageBadge={false}
                setOptions={{
                  enableBasicAutocompletion: true,
                  enableLiveAutocompletion: true,
                  enableSnippets: true,
                  showLineNumbers: true,
                  tabSize: 4,
                  useWorker: false,
                  wrap: true,
                }}
                placeholder="Enter your code here..."
              />
            </div>
          ) : type === "markdown" ? (
            <div className={styles.markdownContainer}>
              <ReactMarkdown remarkPlugins={[remarkGfm]}>
                {editableContent || ""}
              </ReactMarkdown>
            </div>
          ) : (
            <textarea
              ref={textareaRef}
              className={`textarea ${styles.textArea}`}
              value={editableContent}
              onChange={readOnly ? undefined : (e) => setEditableContent(sanitizeInput(e.target.value, "text"))}
              readOnly={readOnly}
            />
          )}
        </div>
        {!hideFooter && (
          <div className={styles.popupFooter}>
            <IAFButton type="secondary" onClick={onClose}>
              Cancel
            </IAFButton>
            {!recycleBin && (
              <IAFButton type="primary" onClick={handleSave} disabled={readOnly}>
                Ok
              </IAFButton>
            )}
          </div>
        )}
      </div>
    </div>,
    document.body
  );
};

export default ZoomPopup;
