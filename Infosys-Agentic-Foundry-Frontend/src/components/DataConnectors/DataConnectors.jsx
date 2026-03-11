import React, { useState, useEffect, useRef } from "react";
import { usePermissions } from "../../context/PermissionsContext";
import styles from "./DataConnectors.module.css";
import ConnectionModal from "./ConnectionModal";
import QueryModal from "./QueryModal";
import CrudModal from "./CrudModal";
import ConnectionManagementModal from "./ConnectionManagementModal";
import SVGIcons from "../../Icons/SVGIcons";
import { useDatabaseConnections } from "./hooks/useDatabaseConnections";
import { DatabaseProvider, useDatabase } from "./context/DatabaseContext";
import { useDatabases } from "./service/databaseService.js";
import CodeEditor from "../commonComponents/CodeEditor.jsx";
import IAFButton from "../../iafComponents/GlobalComponents/Buttons/Button.jsx";
import SubHeader from "../commonComponents/SubHeader";

const DataConnectorsContent = () => {
  // Always call hooks first
  const { permissions, loading: permissionsLoading, hasPermission } = usePermissions();
  const [showConnectionModal, setShowConnectionModal] = useState(false);
  const [showQueryModal, setShowQueryModal] = useState(false);
  const [showCrudModal, setShowCrudModal] = useState(false);
  const [showManagementModal, setShowManagementModal] = useState(false);
  const [selectedDatabase, setSelectedDatabase] = useState(null);
  const [managementDatabase, setManagementDatabase] = useState(null);
  const [isExecuting, setIsExecuting] = useState(false);
  const [isCrudExecuting, setIsCrudExecuting] = useState(false);
  const [sqlConnections, setSqlConnections] = useState([]);
  const initialFetchDone = useRef(false);
  const { fetchSqlConnections, executeMongodbOperation } = useDatabases();
  const {
    handleConnectionSubmit,
    isConnecting,
    availableConnections,
    isLoadingConnections,
    handleDisconnect: hookHandleDisconnect,
    handleActivateConnection: hookHandleActivateConnection,
    handleDeactivate: hookHandleDeactivate,
    isDisConnecting,
    isActivating,
    loadAvailableConnections,
  } = useDatabaseConnections();
  const { getActiveMySQLConnections, getActivePostgresConnections, getActiveSQLiteConnections, getActiveMongoConnections, fetchActiveConnections } = useDatabase();

  // Single useEffect for all initial data fetching - runs only once on mount
  useEffect(() => {
    if (initialFetchDone.current) {
      return;
    }
    initialFetchDone.current = true;

    // Fetch active connections
    if (typeof fetchActiveConnections === "function") {
      fetchActiveConnections();
    }

    // Fetch SQL connections
    fetchSqlConnections().then((result) => {
      if (result && result.success) {
        setSqlConnections(result.data.connections || result.data || []);
      } else {
        setSqlConnections([]);
      }
    });

    // Fetch available connections
    if (typeof loadAvailableConnections === "function") {
      loadAvailableConnections();
    }
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  // Permission check (generalized) - after all hooks
  if (permissionsLoading) {
    return <div>Loading...</div>;
  }
  const dataConnectorAllowed = typeof hasPermission === "function" ? hasPermission("data_connector_access") : !(permissions && permissions.data_connector_access === false);
  if (!dataConnectorAllowed) {
    return <div style={{ padding: 24, color: "var(--danger)", fontWeight: 600 }}>You do not have permission to access Data Connectors.</div>;
  }

  // Database types with their configurations
  const databaseTypes = [
    {
      id: "postgresql",
      name: "PostgreSQL",
      description: "Open-source relational database",
      icon: "postgresql",
      color: "#336791",
      fields: [
        { name: "connectionName", label: "Connection Name", type: "text", required: true },
        { name: "databaseType", label: "Database Type", type: "text", required: true, defaultValue: "PostgreSQL", readOnly: true },
        { name: "host", label: "Host", type: "text", required: true },
        { name: "port", label: "Port", type: "number", required: true },
        { name: "databaseName", label: "Database", type: "text", required: true },
        { name: "username", label: "Username", type: "text", required: true },
        { name: "user_pwd", label: "Password", type: "password", required: true },
      ],
    },
    {
      id: "mysql",
      name: "MySQL",
      description: "Popular open-source database",
      icon: "mysql",
      color: "#00758f",
      fields: [
        { name: "connectionName", label: "Connection Name", type: "text", required: true },
        { name: "databaseType", label: "Database Type", type: "text", required: true, defaultValue: "MySQL", readOnly: true },
        { name: "host", label: "Host", type: "text", required: true },
        { name: "port", label: "Port", type: "number", required: true },
        { name: "databaseName", label: "Database", type: "text", required: true },
        { name: "username", label: "Username", type: "text", required: true },
        { name: "user_pwd", label: "Password", type: "password", required: true },
      ],
    },
    {
      id: "mongodb",
      name: "MongoDB",
      description: "NoSQL document database",
      icon: "mongodb",
      color: "#47A248",
      fields: [
        { name: "connectionName", label: "Connection Name", type: "text", required: true },
        { name: "databaseType", label: "Database Type", type: "text", required: true, defaultValue: "MongoDB", readOnly: true },
        { name: "host", label: "Host", type: "text", required: true },
        { name: "port", label: "Port", type: "number", required: true },
        { name: "databaseName", label: "Database", type: "text", required: true },
        { name: "username", label: "Username", type: "text", required: false },
        { name: "user_pwd", label: "Password", type: "password", required: false },
      ],
    },
    {
      id: "sqlite",
      name: "SQLite",
      description: "Lightweight file-based database",
      icon: "sqlite",
      color: "#003B57",
      fields: [
        { name: "connectionName", label: "Connection Name", type: "text", required: true },
        { name: "databaseType", label: "Database Type", type: "text", required: true, defaultValue: "SQLite", readOnly: true },
        { name: "databaseName", label: "New SQLITE DB Filename(.db,.sqlite)", type: "text" },
      ],
    },
  ];

  const handleCardClick = (database) => {
    // Don't open connection modal for management card
    if (database.isManagement) {
      return;
    }
    setSelectedDatabase(database);
    setShowConnectionModal(true);
  };

  const handleRunClick = (database, event) => {
    event.stopPropagation(); // Prevent card click event
    setSelectedDatabase(database);
    setShowQueryModal(true);
  };

  const handleCrudClick = (database, event) => {
    event.stopPropagation(); // Prevent card click event
    setSelectedDatabase(database);
    setShowCrudModal(true);
  };

  const handleManagementClick = (database, event) => {
    event.stopPropagation();
    setManagementDatabase(database);
    setShowManagementModal(true);
  };

  const handleCloseModal = () => {
    setShowConnectionModal(false);
    setShowQueryModal(false);
    setShowCrudModal(false);
    setShowManagementModal(false);
    setSelectedDatabase(null);
    setManagementDatabase(null);
  };

  const handleRunQuery = async (queryData) => {
    setIsExecuting(true);
    try {
      // Add your query execution logic here
    } catch (error) {
      console.error("Query execution error:", error);
    } finally {
      setIsExecuting(false);
    }
  };

  const handleExecuteCrud = async (crudData) => {
    setIsCrudExecuting(true);
    try {
      // Prepare payload for MongoDB operation (API expects empty objects, not empty strings)
      const payload = {
        conn_name: crudData.selectedConnection.replace(/^mongodb_/, ""),
        collection: crudData.collection,
        operation: crudData.operation,
        mode: crudData.mode,
        query: crudData.jsonQuery ? JSON.parse(crudData.jsonQuery) : {},
        data: crudData.dataJson ? JSON.parse(crudData.dataJson) : {},
        update_data: crudData.updateJson ? JSON.parse(crudData.updateJson) : {},
      };
      Object.keys(payload).forEach((key) => typeof payload[key] === "undefined" && delete payload[key]);
      const result = await executeMongodbOperation(payload);
      return result;
    } catch (error) {
      console.error("CRUD execution error:", error);
      throw error;
    } finally {
      setIsCrudExecuting(false);
    }
  };

  const filteredDatabaseTypes = databaseTypes;

  // (duplicate useEffect removed) all fetch logic is handled above to keep hooks in stable order

  return (
    <div className={styles.container}>
      <SubHeader heading={"Data Connectors"} activeTab={"dataConnectors"} showRefreshButton={false} showPlusButton={false} showSearch={false} />
      {/* Database Cards */}
      <div className={styles.cardsContainer}>
        {filteredDatabaseTypes.filter((db) => !db.isManagement).length > 0 ? (
          filteredDatabaseTypes
            .filter((db) => !db.isManagement)
            .map((database) => {
              // Count connections for this database type
              const connectionCount = availableConnections.filter((conn) => {
                // Normalize type for comparison
                const dbType = (conn.connection_database_type || conn.type || "").toLowerCase();
                const expectedType = (database.name || "").toLowerCase();
                return dbType === expectedType;
              }).length;
              // Count active connections for this database type
              let activeConnectionCount = 0;
              if (database.id === "postgresql") {
                activeConnectionCount = getActivePostgresConnections().length;
              } else if (database.id === "mysql") {
                activeConnectionCount = getActiveMySQLConnections().length;
              } else if (database.id === "sqlite") {
                activeConnectionCount = getActiveSQLiteConnections().length;
              } else if (database.id === "mongodb") {
                activeConnectionCount = getActiveMongoConnections().length;
              }
              return (
                <div key={database.id} className={styles.databaseCard} onClick={() => handleCardClick(database)} style={{ cursor: "pointer", opacity: 1 }}>
                  <div className={styles.cardHeader} style={{ justifyContent: "space-between" }}>
                    <div style={{ display: "flex", alignItems: "center" }}>
                      <div className={styles.cardIcon} style={{ backgroundColor: database.color }}>
                        <SVGIcons icon={database.icon} width={32} height={32} fill="white" />
                      </div>
                      <div className={styles.cardTitleSection}>
                        <h3 className={styles.cardTitle}>{database.name}</h3>
                        {/* Show connection count badge for non-management cards */}
                        <span className={styles.connectionBadge}>
                          {connectionCount} connection{connectionCount !== 1 ? "s" : ""}, {activeConnectionCount} active
                        </span>
                      </div>
                    </div>
                  </div>
                  <p className={styles.cardDescription}>{database.description}</p>
                  <div className={styles.cardFooter}>
                    <div className={styles.cardButtons}>
                      {/* Run button: Show for all databases except MongoDB */}
                      {database.id !== "mongodb" && (
                        <>
                          <IAFButton type="primary" onClick={(e) => handleRunClick(database, e)} className={styles.runbutton}>
                            Run
                          </IAFButton>
                          <IAFButton type="primary" onClick={(e) => handleManagementClick(database, e)} className={styles.manageButtonSpacing}>
                            Manage
                          </IAFButton>
                        </>
                      )}
                      {/* CRUD and Manage buttons: Show for MongoDB */}
                      {database.id === "mongodb" && (
                        <>
                          <IAFButton type="primary" onClick={(e) => handleCrudClick(database, e)}>
                            CRUD
                          </IAFButton>
                          <IAFButton type="primary" onClick={(e) => handleManagementClick(database, e)} className={styles.manageButtonSpacing}>
                            Manage
                          </IAFButton>
                        </>
                      )}
                    </div>
                  </div>
                </div>
              );
            })
        ) : (
          <div className={styles.noResults}>
            <p>No databases found.</p>
          </div>
        )}
      </div>

      {/* Connection Modal */}
      {showConnectionModal && selectedDatabase && (
        <ConnectionModal database={selectedDatabase} onClose={handleCloseModal} onSubmit={handleConnectionSubmit} isConnecting={isConnecting} />
      )}

      {/* Query Modal */}
      {showQueryModal && selectedDatabase && (
        <QueryModal
          database={selectedDatabase}
          onClose={handleCloseModal}
          onRunQuery={handleRunQuery}
          isExecuting={isExecuting}
          sqlConnections={sqlConnections}
          setSqlConnections={setSqlConnections}
          loadingSqlConnections={false}
        />
      )}

      {/* CRUD Modal */}
      {showCrudModal && selectedDatabase && <CrudModal database={selectedDatabase} onClose={handleCloseModal} onExecuteCrud={handleExecuteCrud} isExecuting={isCrudExecuting} />}

      {/* Connection Management Modal */}
      {showManagementModal && (
        <ConnectionManagementModal
          isOpen={showManagementModal}
          onClose={handleCloseModal}
          availableConnections={
            managementDatabase
              ? availableConnections.filter((conn) => (conn.connection_database_type || conn.type || "").toLowerCase() === (managementDatabase.name || "").toLowerCase())
              : availableConnections
          }
          isLoadingConnections={isLoadingConnections}
          onDisconnect={hookHandleDisconnect}
          onActivate={hookHandleActivateConnection}
          isDisConnecting={isDisConnecting}
          isActivating={isActivating}
          databaseType={managementDatabase ? managementDatabase.name : null}
          onDeactivate={hookHandleDeactivate}
        />
      )}

      {/* Python Code Example Section */}
      <div className={styles.codeExampleSection}>Python code example to use the connection_name to connect to database in your tools:</div>
      <div className={styles.codeSnippet}>
        <CodeEditor
          mode="python"
          readOnly={true}
          codeToDisplay={`# [PostgreSQL,MySQL,SQLite]
def fetch_all_from_xyz(connection_name: str):
    """
    Fetches all records from the 'xyz' table in the specified database using the provided database key.
    Args:
        connection_name (str): The key used to identify and connect to the specific database.
    Returns:
        list: A list of dictionaries, where each dictionary represents a row from the 'xyz' table.
    """
    from MultiDBConnection_Manager import get_connection_manager
    from sqlalchemy import text
    try:
        manager = get_connection_manager()
        session = manager.get_sql_session(connection_name)
        result = session.execute(text('SELECT * FROM xyz'))
        rows = result.fetchall()
        session.close()
        return [dict(row._mapping) for row in rows]
    except Exception as e:
        if 'session' in locals():
            session.close()
        return f'Error fetching data from database {connection_name}: {str(e)}'

# [MONGODB]
async def fetch_all_for_mongo(connection_name: str):
    """
    Fetches all documents from the 'users' collection in a specified MongoDB database asynchronously.
    Args:
        connection_name (str): The key used to identify and connect to the desired MongoDB database.
    Returns:
        list: A list of documents retrieved from the 'users' collection.
    """
    from MultiDBConnection_Manager import get_connection_manager
    try:
        manager = get_connection_manager()
        mongo_db = manager.get_mongo_database(connection_name)
        collection = mongo_db['users']
        #  Use to_list() - more efficient and reliable
        documents = await collection.find({}).to_list(length=None)
        #  Convert ObjectId to string without importing bson
        for doc in documents:
            if '_id' in doc:
                doc['_id'] = str(doc['_id'])
        return documents
    except Exception as e:
        error_msg = f"Error fetching data from MongoDB {connection_name}: {str(e)}"
        print(error_msg)
        return []

# Note:
# - make sure your connection is active.
# - make sure you add the 2 import lines that are:
#       from MultiDBConnection_Manager import get_connection_manager
#       from sqlalchemy import text
# - you need to write:
#       manager = get_connection_manager() which gets a singleton instance of youMultiDBConnectionManager class.
#       session = manager.get_sql_session(connection_name) which asks the manager for a new SQLAlchemy session connected to the database identified by connection_name.
# -make sure you close the session after use:
#       session.close()`}
          width="100%"
          height="100%"
          fontSize={14}
          setOptions={{
            enableBasicAutocompletion: false,
            enableLiveAutocompletion: false,
            enableSnippets: false,
            showLineNumbers: true,
            tabSize: 4,
            useWorker: false,
            wrap: true,
          }}
          style={{
            fontFamily: "Consolas, Monaco, 'Courier New', monospace",
            border: "1px solid var(--border)",
            borderRadius: "8px",
            minHeight: "300px",
          }}
        />
      </div>
    </div>
  );
};

// Wrapper component with DatabaseProvider
const DataConnectors = () => {
  return (
    <DatabaseProvider>
      <DataConnectorsContent />
    </DatabaseProvider>
  );
};

export default DataConnectors;
