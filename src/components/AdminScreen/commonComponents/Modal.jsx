import React from "react";
import styles from "../AgentAssignment.module.css";

const Modal = ({ 
  isOpen, 
  onClose, 
  title, 
  children, 
  onResetForm 
}) => {
  if (!isOpen) return null;

  const handleClose = () => {
    if (onResetForm) {
      onResetForm();
    }
    onClose();
  };

  const handleOverlayClick = (e) => {
    if (e.target === e.currentTarget) {
      handleClose();
    }
  };

  return (
    <div className={styles.modalOverlay} onClick={handleOverlayClick}>
      <div className={styles.modal}>
        <div className={styles.modalHeader}>
          <h4>{title}</h4>
          <button 
            className={styles.closeBtn} 
            onClick={handleClose}
            type="button"
          >
            ×
          </button>
        </div>
        <div className={styles.modalContent}>
          {children}
        </div>
      </div>
    </div>
  );
};

export default Modal;