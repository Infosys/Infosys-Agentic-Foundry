import React, { useRef, useEffect } from "react";
import style from "./ConfirmationPopup.module.css";

const ConfirmationModal = ({ message, onConfirm, setShowConfirmation }) => {
  const modalRef = useRef(null);

  const hanleClose = () => {
    setShowConfirmation(false);
  };

  return (
    <div className={style.backdrop}>
      <div ref={modalRef} className={style.modal}>
        <p>{message}</p>
        <div className={style.buttons}>
          <button className={style.confirm} onClick={onConfirm}>
            Confirm
          </button>
          <button className={style.cancel} onClick={hanleClose}>
            Cancel
          </button>
        </div>
      </div>
    </div>
  );
};

export default ConfirmationModal;
