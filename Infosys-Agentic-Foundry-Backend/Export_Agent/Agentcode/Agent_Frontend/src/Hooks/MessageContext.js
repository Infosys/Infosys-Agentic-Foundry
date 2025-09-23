import React, { createContext, useState, useContext, useEffect } from "react";

// Create a Context for the message system
const MessageContext = createContext();

// Provider Component to wrap the entire application
export const MessageProvider = ({ children }) => {
  const [message, setMessage] = useState("");
  const [showPopup, setShowPopup] = useState(false);

  const addMessage = (message, type) => {
    const newMessage = { message, type, id: Date.now() };
    setMessage(newMessage);
    setShowPopup(true);
  };

  const removeMessage = () => {
    setMessage(null);
    setShowPopup(false);
  };

  // Auto-hide success messages after 3 seconds
  useEffect(() => {
    if (showPopup && message && message.type === "success") {
      const timer = setTimeout(() => {
        removeMessage();
      }, 3000);
      
      return () => clearTimeout(timer);
    }
  }, [showPopup, message]);

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
