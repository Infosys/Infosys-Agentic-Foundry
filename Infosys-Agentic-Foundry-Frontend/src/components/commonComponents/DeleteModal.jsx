import React from "react";
import { createPortal } from "react-dom";
import styles from "./DeleteModal.module.css";

/** Default overlay z-index; FullModal portals at 1000001 — use overlayZIndex higher + portal when nested inside FullModal */
const DeleteModal = ({ show, onClose, children, overlayZIndex }) => {
  if (!show) {
    return null;
  }

  const overlayStyle =
    overlayZIndex != null ? { zIndex: overlayZIndex } : undefined;

  const modalTree = (
    <div className={styles.modalOverlay} style={overlayStyle}>
      <div className={styles.modal}>
        <button type="button" className={styles.closeBtn} onClick={onClose} aria-label="Close">
          &times;
        </button>
        <div className={styles.modalContent}>{children}</div>
      </div>
    </div>
  );

  if (overlayZIndex != null && typeof document !== "undefined") {
    return createPortal(modalTree, document.body);
  }

  return modalTree;
};

export default DeleteModal;