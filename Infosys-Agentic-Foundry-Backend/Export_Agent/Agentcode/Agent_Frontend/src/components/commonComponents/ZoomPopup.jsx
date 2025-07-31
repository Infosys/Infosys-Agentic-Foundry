import React, { useEffect, useState, useRef } from "react";
import styles from "./ZoomPopup.module.css";
import { faCompress } from "@fortawesome/free-solid-svg-icons";
import { FontAwesomeIcon } from "@fortawesome/react-fontawesome";

const ZoomPopup = (props) => {
  const { show, onClose, title, content, onSave,recycleBin } = props;

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


  return (
    <div className={styles.popup}>
      <div className={styles.popupContent}>
        <button className={styles.closePopup} onClick={onClose} title="Close">
          <FontAwesomeIcon icon={faCompress} style={{ color: "#7F7F7F" }} />
        </button>
        <h3>{title}</h3>
        <textarea
          ref={textareaRef}
          value={editableContent}
          onChange={handleInput}
          className={styles.content}
          disabled={recycleBin}
        />
        <div className={styles.popupFooter}>
          {!recycleBin &&(
         <button className={styles.saveButton} onClick={handleSave} >
            Ok
          </button>
          )}
         
          <button className={styles.cancelButton} onClick={onClose}>
            Cancel
          </button>
        </div>
      </div>
    </div>
  );
};

export default ZoomPopup;
