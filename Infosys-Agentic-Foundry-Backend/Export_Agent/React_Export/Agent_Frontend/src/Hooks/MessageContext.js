import React, { createContext, useState, useContext } from "react";

// Create a Context for the message system
const MessageContext = createContext();

// Provider Component to wrap the entire application
export const MessageProvider = ({ children }) => {
  const [message, setMessage] = useState("");
  const [showPopup, setShowPopup] = useState(false);

  const addMessage = (message, type) => {
    const newMessage = { message, type, id: Date.now() };
    setMessage(newMessage);
  };

  const removeMessage = () => {
    setMessage(null);
  };

  return (
    <MessageContext.Provider value={{ addMessage, removeMessage, message, setShowPopup, showPopup }}>
      {children}
    </MessageContext.Provider>
  );
};

// Custom hook to access the message context
export const useMessage = () => {
  return useContext(MessageContext);
};
