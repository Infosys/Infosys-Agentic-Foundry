import React, { useState, useEffect } from "react";
import style from "./ToastMessage.module.css";
import SVGIcons from "../../Icons/SVGIcons";

const ToastMessage = (props) => {
  const { message, duration, setShowToast } = props;
  const handleClose = () => {
    setShowToast(false);
  };
  return (
    <div className={style.toastContainer}>
      <div>
        <button className={style.closeButton} onClick={handleClose}>
          <SVGIcons icon="close-icon" color="#7F7F7F" width={20} height={20} />
        </button>
      </div>
      <span>{message}</span>
    </div>
  );
};

export default ToastMessage;
