import React, { createContext, useContext, useMemo } from 'react';
import { useLocation } from 'react-router-dom';

const ApiUrlContext = createContext(null);

export const useApiUrl = () => {
  const context = useContext(ApiUrlContext);
  if (!context) {
    throw new Error('useApiUrl must be used within an ApiUrlProvider');
  }
  return context;
};

export const ApiUrlProvider = ({ children }) => {
  const location = useLocation();
  
  // Determine base URL based on current path
  const mkDocsInternalPath = useMemo(() => {
    const path = location.pathname;
    
    if (path.startsWith('/agent')) {
      return 'agent_config/Overview/';
    } else if (path.startsWith('/chat')) {
      return 'Inference/inference/';
    } else if (path.startsWith('/files')) {
      return 'Inference/inference/';
    } else if (path.startsWith('/admin')) {
      return '';
    } else {
      // Default URL
      return 'tools_config/tools/';
    }
  }, [location.pathname]);
  
  const value = { mkDocsInternalPath };
  
  return (
    <ApiUrlContext.Provider value={value}>
      {children}
    </ApiUrlContext.Provider>
  );
};