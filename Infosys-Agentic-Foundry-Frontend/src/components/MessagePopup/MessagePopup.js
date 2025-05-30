import React from "react";
import "./MessagePopup.css";
import { useMessage } from "./../../Hooks/MessageContext";
import SVGIcons from "../../Icons/SVGIcons";

const MessagePopup = () => {
  const { message, removeMessage, showPopup } = useMessage(); 

  if(!showPopup) return null;
  if (!message) return null; 

  const { message: messageText, type, id } = message; 

  return (
    <div className="popup-message-modal">
      <div className="message-container">
      <div key={id} className={`message-popup ${type}`}>
        <div className="icon-message">
        <div className={`icon-container ${type}`}>
          {type === "success" ? (<SVGIcons color="#333" icon="check" width={20} height={20} />):(<SVGIcons color="#333" icon="exclamation" width={20} height={20} />)}
        </div>
        {messageText}
        </div>
        <div className="close-btn" onClick={() => removeMessage()}>
          <SVGIcons color="#000000" icon="close-icon" opacity={"28%"} width={25} height={25} />
        </div>
      </div>
    </div>
    </div>
  );
};

export default MessagePopup;
