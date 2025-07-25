import React, { createContext, useContext, useState, useEffect, useRef } from 'react';
import { APP_VERSION, BASE_URL } from '../constant';
import axios from 'axios';

const VersionContext = createContext(null);

export const useVersion = () => {
  const context = useContext(VersionContext);
  if (!context) {
    throw new Error('useVersion must be used within a VersionProvider');
  }
  return context;
};

export const VersionProvider = ({ children }) => {
  const [backendVersion, setBackendVersion] = useState('');
  const [combinedVersion, setCombinedVersion] = useState(APP_VERSION);
  const [loading, setLoading] = useState(true);
  const fetchedRef = useRef(false);

  useEffect(() => {
    // Only fetch if we haven't already done so
    if (fetchedRef.current) return;
    
    const fetchBackendVersion = async () => {
      try {
        fetchedRef.current = true;
        const response = await axios.get(BASE_URL+'/get-version');
        const version = response.data.version || response.data || '';
        setBackendVersion(version);
        setCombinedVersion(`${APP_VERSION} ~ ${version}`);
      } catch (error) {
        console.error('Failed to fetch backend version:', error);
        // If there's an error, just use the frontend version
        setCombinedVersion(APP_VERSION);
      } finally {
        setLoading(false);
      }
    };

    fetchBackendVersion();
  }, []);

  const value = { 
    backendVersion, 
    combinedVersion, 
    loading 
  };

  return (
    <VersionContext.Provider value={value}>
      {children}
    </VersionContext.Provider>
  );
};
