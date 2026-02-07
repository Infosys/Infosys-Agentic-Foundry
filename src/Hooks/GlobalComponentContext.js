import React, { createContext, useState, useContext, useEffect } from 'react';
import { useAuth } from '../context/AuthContext';

const GlobalComponentContext = createContext();

export const useGlobalComponent = () => useContext(GlobalComponentContext);

export const GlobalComponentProvider = ({ children }) => {
  const [isVisible, setIsVisible] = useState(false);
  const [componentContent, setComponentContent] = useState("");
  const { isAuthenticated } = useAuth();

  const showComponent = (content) => {
    setComponentContent(content);
    setIsVisible(true);
  };

  const hideComponent = () => {
    setIsVisible(false);
    setComponentContent(null);
  };

  // Reset component state when user logs out
  useEffect(() => {
    if (!isAuthenticated) {
      setIsVisible(false);
      setComponentContent(null);
    }
  }, [isAuthenticated]);
  

  return (
    <GlobalComponentContext.Provider value={{ isVisible, showComponent, hideComponent, componentContent }}>
      {children}
    </GlobalComponentContext.Provider>
  );
};