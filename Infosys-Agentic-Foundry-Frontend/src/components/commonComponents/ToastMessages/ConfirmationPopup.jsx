import React, { useRef, useEffect } from "react";
import ReactDOM from "react-dom";
import style from "./ConfirmationPopup.module.css";
import IAFButton from "../../../iafComponents/GlobalComponents/Buttons/Button";

const ConfirmationModal = ({ message, onConfirm, setShowConfirmation, loading = false, confirmLabel = "Confirm", cancelLabel = "Cancel", hideCancel = false }) => {
  const modalRef = useRef(null);

  const hanleClose = () => {
    if (!loading) setShowConfirmation(false);
  };

  return ReactDOM.createPortal(
    <div className={style.backdrop} onClick={hanleClose}>
      <div ref={modalRef} className={style.modal} onClick={(e) => e.stopPropagation()}>
        <p>{message}</p>
        <div className={style.buttons}>
          {!hideCancel && (
            <IAFButton type="danger" onClick={hanleClose} aria-label="Cancel" disabled={loading}>
              {cancelLabel}
            </IAFButton>
          )}
          <IAFButton type="primary" onClick={onConfirm} aria-label="Confirm" disabled={loading} loading={loading}>
            {confirmLabel}
          </IAFButton>
        </div>
      </div>
    </div>,
    document.body
  );
};

export default ConfirmationModal;
