import React, { createContext, useContext, useState } from 'react';
import { APIs } from '../../../constant';
import useFetch from '../../../Hooks/useAxios';

// Create context
const DatabaseContext = createContext();

// Create provider component
export const DatabaseProvider = ({ children }) => {
  // State for connected databases - start with empty array
  const [connectedDatabases, setConnectedDatabases] = useState([]);
  const {fetchData} = useFetch();

  // State for active connections from API
  const [activeConnections, setActiveConnections] = useState({
    active_mysql_connections: [],
    active_postgres_connections: [],
    active_sqlite_connections: [],
    active_mongo_connections: []
  });

  // State for loading active connections
  const [loadingActiveConnections, setLoadingActiveConnections] = useState(false);

  // Function to fetch active connections from API
  const fetchActiveConnections = async () => {
    setLoadingActiveConnections(true);
    try {
      const response = await fetchData(APIs.GET_ACTIVE_CONNECTIONS);
      if (response) {
        // Ensure the structure matches what we expect
        const processedData = {
          active_mysql_connections: response.active_mysql_connections || [],
          active_postgres_connections: response.active_postgres_connections || [],
          active_sqlite_connections: response.active_sqlite_connections || [],
          active_mongo_connections: response.active_mongo_connections || []
        };
        setActiveConnections(processedData);
        return processedData;
      }
      return {
        active_mysql_connections: [],
        active_postgres_connections: [],
        active_sqlite_connections: [],
        active_mongo_connections: []
      };
    } catch (error) {
      console.error('Error fetching active connections:', error);
      // Return empty connections on error
      const emptyConnections = {
        active_mysql_connections: [],
        active_postgres_connections: [],
        active_sqlite_connections: [],
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
  const getActiveMySQLConnections = () => activeConnections.active_mysql_connections || [];
  const getActivePostgresConnections = () => activeConnections.active_postgres_connections || [];
  const getActiveSQLiteConnections = () => activeConnections.active_sqlite_connections || [];
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
    getActiveMySQLConnections,
    getActivePostgresConnections,
    getActiveSQLiteConnections,
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

// Custom hook for mapping active SQL connection names to objects
export const useActiveSqlConnections = (availableConnections = []) => {
  const { activeConnections } = useDatabase();
  // No fetching here; expects availableConnections to be provided
  const names = activeConnections.active_sql_connections || [];
  return names.map(name =>
    availableConnections.find(conn =>
      conn.connection_name === name ||
      conn.name === name ||
      conn.database_name === name
    ) || name
  );
};