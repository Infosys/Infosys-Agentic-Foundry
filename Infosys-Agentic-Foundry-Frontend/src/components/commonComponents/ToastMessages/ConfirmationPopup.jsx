import React, { useRef, useEffect } from "react";
import ReactDOM from "react-dom";
import style from "./ConfirmationPopup.module.css";
import IAFButton from "../../../iafComponents/GlobalComponents/Buttons/Button";

const ConfirmationModal = ({ message, onConfirm, setShowConfirmation }) => {
  const modalRef = useRef(null);

  const hanleClose = () => {
    setShowConfirmation(false);
  };

  return ReactDOM.createPortal(
    <div className={style.backdrop} onClick={hanleClose}>
      <div ref={modalRef} className={style.modal} onClick={(e) => e.stopPropagation()}>
        <p>{message}</p>
        <div className={style.buttons}>
          <IAFButton type="danger" onClick={hanleClose} aria-label="Confirm">
            Cancel
          </IAFButton>
          <IAFButton type="primary" onClick={onConfirm} aria-label="Cancel">
            Confirm
          </IAFButton>
        </div>
      </div>
    </div>,
    document.body
  );
};

export default ConfirmationModal;
