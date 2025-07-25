import React, { createContext, useContext, useState } from 'react';
import axios from 'axios';
import { BASE_URL, APIs } from '../../../constant';

// Create context
const DatabaseContext = createContext();

// Create provider component
export const DatabaseProvider = ({ children }) => {
  // State for connected databases - start with empty array
  const [connectedDatabases, setConnectedDatabases] = useState([]);

  // State for active connections from API
  const [activeConnections, setActiveConnections] = useState({
    active_sql_connections: [],
    active_mongo_connections: []
  });

  // State for loading active connections
  const [loadingActiveConnections, setLoadingActiveConnections] = useState(false);

  // Function to fetch active connections from API
  const fetchActiveConnections = async () => {
    setLoadingActiveConnections(true);
    try {
      const response = await axios.get(`${BASE_URL}${APIs.GET_ACTIVE_CONNECTIONS}`);
      if (response.data) {
        // Ensure the structure matches what we expect
        const processedData = {
          active_sql_connections: response.data.active_sql_connections || [],
          active_mongo_connections: response.data.active_mongo_connections || []
        };
        setActiveConnections(processedData);
        
        // Log the connection count for debugging
        console.log('Active connections fetched:', {
          sql: processedData.active_sql_connections.length,
          mongo: processedData.active_mongo_connections.length
        });
        
        return processedData;
      }
      return {
        active_sql_connections: [],
        active_mongo_connections: []
      };
    } catch (error) {
      console.error('Error fetching active connections:', error);
      
      // Return empty connections on error
      const emptyConnections = {
        active_sql_connections: [],
        active_mongo_connections: []
      };
      setActiveConnections(emptyConnections);
      return emptyConnections;
    } finally {
      setLoadingActiveConnections(false);
    }
  };

  // Actions for managing databases
  const addDatabase = (database) => {
    setConnectedDatabases(prev => [...prev, {
      id: Date.now().toString(),
      ...database,
      status: "Connected",
      connectedAt: new Date().toLocaleString()
    }]);
  };

  const removeDatabase = (id) => {
    setConnectedDatabases(prev => prev.filter(db => db.id !== id));
  };

  const updateDatabase = (id, updates) => {
    setConnectedDatabases(prev => 
      prev.map(db => db.id === id ? { ...db, ...updates } : db)
    );
  };

  // Filter functions for mock data
  const getSqlDatabases = () => connectedDatabases.filter(db => db.type !== 'MongoDB');
  const getMongoDatabases = () => connectedDatabases.filter(db => db.type === 'MongoDB');
  const getDatabaseById = (id) => connectedDatabases.find(db => db.id === id);

  // Functions for API active connections
  const getActiveSqlConnections = () => activeConnections.active_sql_connections || [];
  const getActiveMongoConnections = () => activeConnections.active_mongo_connections || [];

  // Context value
  const value = {
    connectedDatabases,
    addDatabase,
    removeDatabase,
    updateDatabase,
    getSqlDatabases,
    getMongoDatabases,
    getDatabaseById,
    activeConnections,
    fetchActiveConnections,
    getActiveSqlConnections,
    getActiveMongoConnections,
    loadingActiveConnections
  };

  return (
    <DatabaseContext.Provider value={value}>
      {children}
    </DatabaseContext.Provider>
  );
};

// Custom hook for using the database context
export const useDatabase = () => {
  const context = useContext(DatabaseContext);
  if (context === undefined) {
    throw new Error('useDatabase must be used within a DatabaseProvider');
  }
  return context;
};