import React, { createContext, useState, useContext, useEffect, useCallback } from "react";

// Create a Context for the message system
const MessageContext = createContext();

// Provider Component to wrap the entire application
export const MessageProvider = ({ children }) => {
  const [message, setMessage] = useState("");
  const [showPopup, setShowPopup] = useState(false);

  const addMessage = useCallback((message, type) => {
    const newMessage = { message, type, id: Date.now() };
    setMessage(newMessage);
    setShowPopup(true);
  }, []);

  const removeMessage = useCallback(() => {
    setMessage(null);
    setShowPopup(false);
  }, []);

  // Auto-hide success/error messages after 5 seconds
  useEffect(() => {
    if (showPopup && message && (message.type === "success" || message.type === "error")) {
      const timer = setTimeout(() => {
        removeMessage();
      }, 5000);
      
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
