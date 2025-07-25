import React, { useState, useEffect } from "react";
import style from "./ToastMessage.module.css";
import SVGIcons from "../../../Icons/SVGIcons";

const ToastMessage = (props) => {
  const { setShowToast, successMessage, errorMessage } = props;

  useEffect(() => {
    const timer = setTimeout(() => {
      setShowToast(false);
    }, 5000);

    return () => clearTimeout(timer);
  }, []);

  const handleClose = () => {
    setShowToast(false);
  };

  return (
    <div
      className={`${style["toast"]} ${
        successMessage ? style["success"] : style["error"]
      }`}
    >
      <div
        className={`${style["icon-container"]} ${
          successMessage ? style["success"] : style["error"]
        }`}
      >
        {successMessage ? (
          <SVGIcons color="#333" icon="check" width={20} height={20} />
        ) : (
          <SVGIcons color="#333" icon="exclamation" width={20} height={20} />
        )}
      </div>
      <p>{successMessage ? successMessage : errorMessage}</p>

      <div className={`${style["close-btn"]}`} onClick={() => handleClose()}>
        <SVGIcons
          color="#000000"
          icon="close-icon"
          opacity={"28%"}
          width={25}
          height={25}
        />
      </div>
    </div>
  );
};

export default ToastMessage;
