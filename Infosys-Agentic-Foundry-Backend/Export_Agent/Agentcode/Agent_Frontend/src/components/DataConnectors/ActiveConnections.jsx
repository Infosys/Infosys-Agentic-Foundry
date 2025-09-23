import React, { useEffect, useRef } from "react";
import styles from "../DataConnectors/DataConnectors.module.css";
import { useDatabase } from "./context/DatabaseContext";

const ActiveConnections = ({ databaseType }) => {
  // Use database context
  const {
    fetchActiveConnections,
    getActivePostgresConnections,
    getActiveMySQLConnections,
    getActiveSQLiteConnections,
    getActiveMongoConnections,
    loadingActiveConnections,
  } = useDatabase();

  // Auto-fetch connections when component mounts
  const fetchRef = useRef(fetchActiveConnections);
  useEffect(() => {
    fetchRef.current = fetchActiveConnections;
  }, [fetchActiveConnections]);
  useEffect(() => {
    fetchRef.current();
  }, []);

  // Get connections from API
  const postgresConnections = getActivePostgresConnections();
  const mysqlConnections = getActiveMySQLConnections();
  const sqliteConnections = getActiveSQLiteConnections();
  const mongoConnections = getActiveMongoConnections();

  // If databaseType is provided, only show that type
  if (databaseType) {
    if (databaseType.toLowerCase() === 'postgresql') {
      return (
        <div className={styles.formSection}>
          <div className={styles.connectionsSection}>
            <div className={styles.connectionCard}>
              <ConnectionTypeList
                title="Active PostgreSQL Connections"
                connections={postgresConnections}
                emptyMessage="No active PostgreSQL connections found"
                loading={loadingActiveConnections}
                showDetails={true}
              />
            </div>
          </div>
        </div>
      );
    } else if (databaseType.toLowerCase() === 'mysql') {
      return (
        <div className={styles.formSection}>
          <div className={styles.connectionsSection}>
            <div className={styles.connectionCard}>
              <ConnectionTypeList
                title="Active MySQL Connections"
                connections={mysqlConnections}
                emptyMessage="No active MySQL connections found"
                loading={loadingActiveConnections}
                showDetails={true}
              />
            </div>
          </div>
        </div>
      );
    } else if (databaseType.toLowerCase() === 'sqlite') {
      return (
        <div className={styles.formSection}>
          <div className={styles.connectionsSection}>
            <div className={styles.connectionCard}>
              <ConnectionTypeList
                title="Active SQLite Connections"
                connections={sqliteConnections}
                emptyMessage="No active SQLite connections found"
                loading={loadingActiveConnections}
                showDetails={true}
              />
            </div>
          </div>
        </div>
      );
    } else if (databaseType.toLowerCase() === 'mongodb') {
      return (
        <div className={styles.formSection}>
          <div className={styles.connectionsSection}>
            <div className={styles.connectionCard}>
              <ConnectionTypeList
                title="Active MongoDB Connections"
                connections={mongoConnections}
                emptyMessage="No active MongoDB connections found"
                loading={loadingActiveConnections}
                showDetails={true}
              />
            </div>
          </div>
        </div>
      );
    }
  }

  return (
    <div className={styles.formSection}>
      <div className={styles.connectionsSection}>
        <div className={styles.connectionCard}>
          <ConnectionTypeList
            title="Active PostgreSQL Connections"
            connections={postgresConnections}
            emptyMessage="No active PostgreSQL connections found"
            loading={loadingActiveConnections}
            showDetails={true}
          />
        </div>
        <div className={styles.connectionsSpacer}></div>
        <div className={styles.connectionCard}>
          <ConnectionTypeList
            title="Active MySQL Connections"
            connections={mysqlConnections}
            emptyMessage="No active MySQL connections found"
            loading={loadingActiveConnections}
            showDetails={true}
          />
        </div>
        <div className={styles.connectionsSpacer}></div>
        <div className={styles.connectionCard}>
          <ConnectionTypeList
            title="Active SQLite Connections"
            connections={sqliteConnections}
            emptyMessage="No active SQLite connections found"
            loading={loadingActiveConnections}
            showDetails={true}
          />
        </div>
        <div className={styles.connectionsSpacer}></div>
        <div className={styles.connectionCard}>
          <ConnectionTypeList
            title="Active MongoDB Connections"
            connections={mongoConnections}
            emptyMessage="No active MongoDB connections found"
            loading={loadingActiveConnections}
            showDetails={true}
          />
        </div>
      </div>
    </div>
  );
};

// Helper component to display connections by type in bulleted list format
const ConnectionTypeList = ({ title, connections, emptyMessage, loading, showDetails = false }) => {
  return (
    <div className={styles.connectionTypeSection}>
      <h4 className={styles.connectionTypeTitle}>{title}</h4>
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
              <span className={styles.connectionName}>{connection}</span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
};

export default ActiveConnections;