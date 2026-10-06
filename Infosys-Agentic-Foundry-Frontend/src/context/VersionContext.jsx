import React, { createContext, useContext, useState, useEffect, useRef } from 'react';
import { APIs, APP_VERSION } from '../constant';
import useFetch from '../Hooks/useAxios';
import { useAuth } from './AuthContext';

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
  const { fetchData } = useFetch();
  const { isAuthenticated } = useAuth();

  useEffect(() => {
    // Wait until the user is authenticated before fetching — prevents
    // the version call going out without a token during SSO login.
    if (!isAuthenticated || fetchedRef.current) return;

    const fetchBackendVersion = async () => {
      try {
        fetchedRef.current = true;
        const response = await fetchData(APIs.GET_VERSION);
        const version = response.version || response || '';
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
  }, [isAuthenticated]);

  const refreshVersion = async () => {
    try {
      const response = await fetchData(APIs.GET_VERSION);
      const version = response.version || response || '';
      setBackendVersion(version);
      setCombinedVersion(`${APP_VERSION} ~ ${version}`);
    } catch (error) {
      console.error('Failed to fetch backend version:', error);
    }
  };

  const value = {
    backendVersion,
    combinedVersion,
    loading,
    refreshVersion,
  };

  return (
    <VersionContext.Provider value={value}>
      {children}
    </VersionContext.Provider>
  );
};
