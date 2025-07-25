import React, { useState, useEffect } from "react";
import styles from "../DataConnectors/DataConnectors.module.css";
import { useDatabase } from "./context/DatabaseContext";

const ActiveConnections = ({ 
}) => {
  // Use database context
  const { 
    fetchActiveConnections, 
    getActiveSqlConnections, 
    getActiveMongoConnections, 
    loadingActiveConnections,
    connectedDatabases 
  } = useDatabase();

  // Local state
  const [lastFetchTime, setLastFetchTime] = useState(null);
  const [autoRefresh, setAutoRefresh] = useState(false);
  const [fetchError, setFetchError] = useState(null);

  // Auto-fetch connections when component mounts
  useEffect(() => {
    const fetchInitialConnections = async () => {
      await fetchActiveConnections();
      setLastFetchTime(new Date());
    };
    
    fetchInitialConnections();
  }, []);

  // ...existing code...

  // Auto-refresh effect
  useEffect(() => {
    let interval;
    if (autoRefresh) {
      interval = setInterval(() => {
        handleRefreshConnections();
      }, 30000); // Refresh every 30 seconds
    }
    return () => {
      if (interval) {
        clearInterval(interval);
      }
    };
  }, [autoRefresh]);

  // Handle refresh connections
  const handleRefreshConnections = async () => {
    try {
      setFetchError(null);
      await fetchActiveConnections();
      setLastFetchTime(new Date());
    } catch (error) {
      setFetchError("Failed to refresh connections. Please try again.");
    }
  };

  // Get connections from API
  const getApiSqlConnections = () => getActiveSqlConnections();
  const getApiMongoConnections = () => getActiveMongoConnections();

  return (
    <div className={styles.formSection}>
      
      {fetchError && (
        <div className={styles.errorMessage}>
          <p>{fetchError}</p>
        </div>
      )}

      <div className={styles.connectionsSection}>
        <ConnectionTypeList 
          title="Active SQL Connections"
          connections={getApiSqlConnections()} 
          emptyMessage="No active SQL connections found"
          loading={loadingActiveConnections}
          showDetails={true}
        />

        <div className={styles.connectionsSpacer}></div>

        <ConnectionTypeList 
          title="Active MongoDB Connections"
          connections={getApiMongoConnections()} 
          emptyMessage="No active MongoDB connections found"
          loading={loadingActiveConnections}
          showDetails={true}
        />
      </div>
    </div>
  );
};

// Helper component to display connections by type in bulleted list format
const ConnectionTypeList = ({ title, connections, emptyMessage, loading, showDetails = false, handleDisconnect }) => {
  
  // Helper function to get connection name
  const getConnectionName = (connection, index) => {
    if (typeof connection === 'string') {
      return connection;
    }
    return connection.name || connection.connection_name || connection.database_name || `Connection ${index + 1}`;
  };

  return (
    <div className={styles.connectionTypeSection}>
      <h4 className={styles.connectionTypeTitle}>
        {title}
      </h4>
      {loading ? (
        <div className={styles.loadingMessage}>
          <p>Loading connections...</p>
        </div>
      ) : connections.length === 0 ? (
        <ul className={styles.connectionsBulletList}>
          <li className={styles.emptyConnectionItem}>{emptyMessage}</li>
        </ul>
      ) : (
        <ul className={styles.connectionsBulletList}>
          {connections.map((connection, index) => (
            <li key={index} className={styles.connectionBulletItem}>
              <span className={styles.connectionIcon}>🔗</span>
              <span className={styles.connectionName}>
                {getConnectionName(connection, index)}
              </span>
              {typeof connection === 'object' && connection.type && (
                <span className={styles.connectionType}>({connection.type})</span>
              )}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
};

export default ActiveConnections;