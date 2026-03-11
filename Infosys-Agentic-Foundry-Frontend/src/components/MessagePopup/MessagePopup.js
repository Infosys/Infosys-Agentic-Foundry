import React from "react";
import "./MessagePopup.css";
import { useMessage } from "./../../Hooks/MessageContext";
import SVGIcons from "../../Icons/SVGIcons";

const MessagePopup = () => {
  const { message, removeMessage, showPopup } = useMessage();

  if (!showPopup) return null;
  if (!message) return null;

  const { message: messageText, type, id } = message;

  return (
    <div className="popup-message-modal">
      <div className="message-container">
        <div key={id} className={`message-popup ${type}`}>
          <div className="icon-message">
            <div className={`icon-container ${type}`}>
              {type === "success" ? (
                <SVGIcons color="#FFFFFF" icon="check" width={16} height={16} />
              ) : (
                <SVGIcons color="#FFFFFF" icon="exclamation" width={16} height={16} />
              )}
            </div>
            <span>{messageText}</span>
          </div>
          <div className="close-btn" onClick={() => removeMessage()}>
            <SVGIcons color="#FFFFFF" icon="close-icon" width={20} height={20} />
          </div>
        </div>
      </div>
    </div>
  );
};

export default MessagePopup;
