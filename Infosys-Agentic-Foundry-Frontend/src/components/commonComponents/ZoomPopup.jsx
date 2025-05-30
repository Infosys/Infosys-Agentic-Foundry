import React, { useEffect, useState, useRef } from "react";
import styles from "./ZoomPopup.module.css";
import { faCompress } from "@fortawesome/free-solid-svg-icons";
import { FontAwesomeIcon } from "@fortawesome/react-fontawesome";
import SVGIcons from "../../Icons/SVGIcons";

const ZoomPopup = (props) => {
  const { show, onClose, title, content, onSave } = props;

  const textareaRef = useRef(null);

  useEffect(() => {
    if (show && textareaRef.current) {
      // Ensure the textareaRef is not null before accessing its properties
      textareaRef.current.focus();
      const textLength = textareaRef.current.value.length;
      textareaRef.current.setSelectionRange(textLength, textLength); // Move cursor to the end
    }
  }, [show]);

  const [editableContent, setEditableContent] = useState(content || "");
  const [copiedStates, setCopiedStates] = useState({});

  useEffect(() => {
    if(show) {
      setEditableContent(content || "");
    }
  }, [content, show]);

  const handleInput = (e) => {
    setEditableContent(e?.target?.value);
  };

  const handleSave = () => {
    onSave(editableContent);
    onClose();
  };

  if (!show) return null;

  // const handleCopy = (key, text) => {
  //   navigator.clipboard.writeText(text);
  //   setCopiedStates((prev) => ({ ...prev, [key]: true })); // Set copied state for the specific key
  //   setTimeout(() => {
  //     setCopiedStates((prev) => ({ ...prev, [key]: false })); // Reset after 2 seconds
  //   }, 2000);
  // };

  const handleCopy = (key, text) => {
    if (navigator.clipboard && navigator.clipboard.writeText) {
      // Use Clipboard API if supported
      navigator.clipboard
        .writeText(text)
        .then(() => {
          setCopiedStates((prev) => ({ ...prev, [key]: true })); // Set copied state
          setTimeout(() => {
            setCopiedStates((prev) => ({ ...prev, [key]: false })); // Reset after 2 seconds
          }, 2000);
        })
        .catch(() => {
          console.error("Copy error");
        });
    } else {
      // Fallback for unsupported browsers
      const textarea = document.createElement("textarea");
      textarea.value = text;
      textarea.style.position = "fixed"; // Prevent scrolling to the bottom of the page
      textarea.style.opacity = "0"; // Hide the textarea
      document.body.appendChild(textarea);
      textarea.focus();
      textarea.select();
  
      try {
        document.execCommand("copy");
        setCopiedStates((prev) => ({ ...prev, [key]: true })); // Set copied state
        setTimeout(() => {
          setCopiedStates((prev) => ({ ...prev, [key]: false })); // Reset after 2 seconds
        }, 2000);
      } catch {
        console.error("Fallback: copy error");
      } finally {
        document.body.removeChild(textarea); // Clean up
      }
    }
  };

  return (
    <div className={styles.popup}>
      <div className={styles.popupContent}>
        <button
          type="button"
          className={styles.copyIcon}
          onClick={() => handleCopy(title, content)}
          title="Copy"
        >
          <SVGIcons
            icon="fa-regular fa-copy"
            width={16}
            height={16}
            fill="#343741"
          />
        </button>
        <span
          className={`${styles.copiedText} ${
            copiedStates[title]
              ? styles.visible
              : styles.hidden
          }`}
        >
          Text Copied!
        </span>
        <button className={styles.closePopup} onClick={onClose} title="Close">
          <FontAwesomeIcon icon={faCompress} style={{ color: "#7F7F7F" }} />
        </button>
        <h3>{title}</h3>
        <textarea
          ref={textareaRef}
          value={editableContent}
          onChange={handleInput}
          className={styles.content}
        />
        <div className={styles.popupFooter}>
          <button className={styles.saveButton} onClick={handleSave}>
            Save
          </button>
          <button className={styles.cancelButton} onClick={onClose}>
            Cancel
          </button>
        </div>
      </div>
    </div>
  );
};

export default ZoomPopup;
