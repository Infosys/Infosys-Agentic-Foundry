import React from "react";
import styles from "./DeleteModal.module.css";

const DeleteModal = ({ show, onClose, children }) => {
  if (!show) {
    return null;
  }

  return (
    <div className={styles.modalOverlay}>
      <div className={styles.modal}>
        <button className={styles.closeBtn} onClick={onClose}>
          &times;
        </button>
        <div className={styles.modalContent}>{children}</div>
      </div>
    </div>
  );
};

export default DeleteModal;