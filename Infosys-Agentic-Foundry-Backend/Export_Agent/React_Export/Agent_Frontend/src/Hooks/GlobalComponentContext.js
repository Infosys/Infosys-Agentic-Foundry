import React, { createContext, useState, useContext } from 'react';

const GlobalComponentContext = createContext();

export const useGlobalComponent = () => useContext(GlobalComponentContext);

export const GlobalComponentProvider = ({ children }) => {
  const [isVisible, setIsVisible] = useState(false);
  const [componentContent, setComponentContent] = useState("");

  const showComponent = (content) => {
    setComponentContent(content);
    setIsVisible(true);
  };

  const hideComponent = () => {
    setIsVisible(false);
    setComponentContent(null);
  };
  

  return (
    <GlobalComponentContext.Provider value={{ isVisible, showComponent, hideComponent, componentContent }}>
      {children}
    </GlobalComponentContext.Provider>
  );
};