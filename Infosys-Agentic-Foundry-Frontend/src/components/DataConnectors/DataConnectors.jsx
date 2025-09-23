import React, { useState, useEffect, useRef } from "react";
import styles from "./DataConnectors.module.css";
import ConnectionModal from "./ConnectionModal";
import QueryModal from "./QueryModal";
import CrudModal from "./CrudModal";
import ConnectionManagementModal from "./ConnectionManagementModal";
import SVGIcons from "../../Icons/SVGIcons";
import { useDatabaseConnections } from "./hooks/useDatabaseConnections";
import { DatabaseProvider, useDatabase } from "./context/DatabaseContext";
import { useDatabases} from './service/databaseService.js';
import Editor from "@monaco-editor/react";

const DataConnectorsContent = () => {
  const [showConnectionModal, setShowConnectionModal] = useState(false);
  const [showQueryModal, setShowQueryModal] = useState(false);
  const [showCrudModal, setShowCrudModal] = useState(false);
  const [showManagementModal, setShowManagementModal] = useState(false);
  const [selectedDatabase, setSelectedDatabase] = useState(null);
  const [managementDatabase, setManagementDatabase] = useState(null);
  const [isExecuting, setIsExecuting] = useState(false);
  const [isCrudExecuting, setIsCrudExecuting] = useState(false);
  const [sqlConnections, setSqlConnections] = useState([]);
  const activeConnectionsFetched = useRef(false);
  const sqlConnectionsFetched = useRef(false);
  const {fetchSqlConnections ,executeMongodbOperation} = useDatabases();

  // Use the database connections hook
  const { 
    handleConnectionSubmit, 
    isConnecting, 
    availableConnections, 
    isLoadingConnections,
    handleDisconnect: hookHandleDisconnect,
    handleActivateConnection: hookHandleActivateConnection,
    handleDeactivate:hookHandleDeactivate,
    isDisConnecting,
    isActivating,
    loadAvailableConnections
  } = useDatabaseConnections();
  const { getActiveMySQLConnections, getActivePostgresConnections, getActiveSQLiteConnections, getActiveMongoConnections, fetchActiveConnections } = useDatabase();

  // Database types with their configurations
  const databaseTypes = [
    {
      id: 'postgresql',
      name: 'PostgreSQL',
      description: 'Open-source relational database',
      icon: 'database',
      color: '#336791',
      fields: [
        {name: 'connectionName', label: 'Connection Name', type: 'text', required: true},
        {name: 'databaseType', label: 'Database Type', type: 'text', required: true, defaultValue: 'PostgreSQL', readOnly: true},
        { name: 'host', label: 'Host', type: 'text', required: true },
        { name: 'port', label: 'Port', type: 'number', required: true },
        { name: 'databaseName', label: 'Database', type: 'text', required: true },
        { name: 'username', label: 'Username', type: 'text', required: true },
        { name: 'password', label: 'Password', type: 'password', required: true },
      ]
    },
    {
      id: 'mysql',
      name: 'MySQL',
      description: 'Popular open-source database',
      icon: 'database',
      color: '#4479A1',
      fields: [
        {name: 'connectionName', label: 'Connection Name', type: 'text', required: true},
        {name: 'databaseType', label: 'Database Type', type: 'text', required: true, defaultValue: 'MySQL', readOnly: true},
        { name: 'host', label: 'Host', type: 'text', required: true },
        { name: 'port', label: 'Port', type: 'number', required: true },
        { name: 'databaseName', label: 'Database', type: 'text', required: true},
        { name: 'username', label: 'Username', type: 'text', required: true },
        { name: 'password', label: 'Password', type: 'password', required: true },
      ]
    },
    {
      id: 'mongodb',
      name: 'MongoDB',
      description: 'NoSQL document database',
      icon: 'database',
      color: '#47A248',
      fields: [
        {name: 'connectionName', label: 'Connection Name', type: 'text', required: true},
        {name: 'databaseType', label: 'Database Type', type: 'text', required: true, defaultValue: 'MongoDB', readOnly: true},
        { name: 'host', label: 'Host', type: 'text', required: true },
        { name: 'port', label: 'Port', type: 'number', required: true },
        { name: 'databaseName', label: 'Database', type: 'text', required: true },
        { name: 'username', label: 'Username', type: 'text', required: false, },
        { name: 'password', label: 'Password', type: 'password', required: false }
      ]
    },
    {
      id: 'sqlite',
      name: 'SQLite',
      description: 'Lightweight file-based database',
      icon: 'database',
      color: '#003B57',
      fields: [
        {name: 'connectionName', label: 'Connection Name', type: 'text', required: true},
        {name: 'databaseType', label: 'Database Type', type: 'text', required: true, defaultValue: 'SQLite', readOnly: true},
        { name: 'databaseName', label: 'New SQLITE DB Filename(.db,.sqlite)', type: 'text' },
      ]
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
        conn_name: crudData.selectedConnection.replace(/^mongodb_/, ''),
        collection: crudData.collection,
        operation: crudData.operation,
        mode: crudData.mode,
        query: crudData.jsonQuery ? JSON.parse(crudData.jsonQuery) : {},
        data: crudData.dataJson ? JSON.parse(crudData.dataJson) : {},
        update_data: crudData.updateJson ? JSON.parse(crudData.updateJson) : {}
      };
      Object.keys(payload).forEach(key => payload[key] === undefined && delete payload[key]);
      const result = await executeMongodbOperation(payload);
      return result;
    } catch (error) {
      console.error("CRUD execution error:", error);
      throw error;
    } finally {
      setIsCrudExecuting(false);
    }
  };

  // Fetch active connections from backend when component mounts
  useEffect(() => {
    if (!activeConnectionsFetched.current && typeof fetchActiveConnections === 'function') {
      fetchActiveConnections();
      activeConnectionsFetched.current = true;
    }
    if (!sqlConnectionsFetched.current) {
      fetchSqlConnections().then(result => {
        if (result.success) {
          setSqlConnections(result.data.connections || result.data || []);
        } else {
          setSqlConnections([]);
        }
      });
      sqlConnectionsFetched.current = true;
    }
    // Fetch available connections immediately on mount
    loadAvailableConnections && loadAvailableConnections();
  }, [fetchActiveConnections, loadAvailableConnections]);

  return (
    <div className={styles.container}>
      {/* Header */}
      <div className={styles.header} style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
        <h1 className={styles.title}>Data Connectors</h1>
      </div>
      {/* Database Cards */}
      <div className={styles.cardsContainer}>
        {databaseTypes.filter(db => !db.isManagement).length > 0 ? (
          databaseTypes.filter(db => !db.isManagement).map((database) => {
            // Count connections for this database type
            const connectionCount = availableConnections.filter(conn => {
              // Normalize type for comparison
              const dbType = (conn.connection_database_type || conn.type || '').toLowerCase();
              const expectedType = (database.name || '').toLowerCase();
              return dbType === expectedType;
            }).length;
            // Count active connections for this database type
            let activeConnectionCount = 0;
            if (database.id === 'postgresql') {
              activeConnectionCount = getActivePostgresConnections().length;
            } else if (database.id === 'mysql') {
              activeConnectionCount = getActiveMySQLConnections().length;
            } else if (database.id === 'sqlite') {
              activeConnectionCount = getActiveSQLiteConnections().length;
            } else if (database.id === 'mongodb') {
              activeConnectionCount = getActiveMongoConnections().length;
            }
            return (
            <div
              key={database.id}
              className={styles.databaseCard}
              onClick={() => database.id !== 'mongodb' ? handleCardClick(database) : null}
              style={{ 
                cursor: database.id === 'mongodb' ? 'not-allowed' : 'pointer', 
                opacity: database.id === 'mongodb' ? 0.5 : 1 
              }}
            >
              <div className={styles.cardHeader} style={{ justifyContent: 'space-between' }}>
                <div style={{ display: 'flex', alignItems: 'center' }}>
                  <div
                    className={styles.cardIcon}
                    style={{ backgroundColor: database.color }}
                  >
                    <SVGIcons
                      icon={database.icon}
                      width={32}
                      height={32}
                      fill="white"
                    />
                  </div>
                  <div className={styles.cardTitleSection}>
                    <h3 className={styles.cardTitle}>{database.name}</h3>
                    {/* Show connection count badge for non-management cards */}
                    <span style={{marginLeft:0,background:'#eee', borderRadius:12, padding:'2px 8px', fontSize:12}}>
                      {connectionCount} connection{connectionCount !== 1 ? 's' : ''}, {activeConnectionCount} active
                    </span>
                  </div>
                </div>
              </div>
              <p className={styles.cardDescription}>{database.description}</p>
              <div className={styles.cardFooter}>
                <div className={styles.cardButtons}>
                  {/* Run button: Show for all databases except MongoDB */}
                  {database.id !== 'mongodb' && (
                    <>
                      <button
                        className={styles.runButton}
                        onClick={(e) => handleRunClick(database, e)}
                      >
                        Run
                      </button>
                      <button
                        className={styles.manageButton}
                        onClick={(e) => handleManagementClick(database, e)}
                        style={{ marginLeft: 8 }}
                      >
                        Manage
                      </button>
                    </>
                  )}
                  {/* CRUD and Manage buttons: Show for MongoDB */}
                  {database.id === 'mongodb' && (
                    <>
                      <button
                        className={styles.crudButton}
                        onClick={(e) => e.stopPropagation()}
                        disabled={true}
                        style={{ opacity: 0.5, cursor: 'not-allowed' }}
                      >
                        CRUD
                      </button>
                      <button
                        className={styles.manageButton}
                        onClick={(e) => e.stopPropagation()}
                        disabled={true}
                        style={{ marginLeft: 8, opacity: 0.5, cursor: 'not-allowed' }}
                      >
                        Manage
                      </button>
                    </>
                  )}
                </div>
              </div>
            </div>
            );
          })
        ) : null}
      </div>

      {/* Connection Modal */}
      {showConnectionModal && selectedDatabase && (
        <ConnectionModal
          database={selectedDatabase}
          onClose={handleCloseModal}
          onSubmit={handleConnectionSubmit}
          isConnecting={isConnecting}
        />
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
      {showCrudModal && selectedDatabase && (
        <CrudModal
          database={selectedDatabase}
          onClose={handleCloseModal}
          onExecuteCrud={handleExecuteCrud}
          isExecuting={isCrudExecuting}
        />
      )}

      {/* Connection Management Modal */}
      {showManagementModal && (
        <ConnectionManagementModal
          isOpen={showManagementModal}
          onClose={handleCloseModal}
          availableConnections={managementDatabase ? availableConnections.filter(conn => (conn.connection_database_type || conn.type || '').toLowerCase() === (managementDatabase.name || '').toLowerCase()) : availableConnections}
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
      <div className={styles.codeExampleSection}>
          Python code example to use the connection_name to connect to database in your tools:
      </div>
      <div className={styles.codeSnippet} style={{ marginLeft: '40px', marginRight: '40px', marginTop: '20px' }}>
        <Editor
          height="600px"
          language="python"
          value={`# [PostgreSQL,MySQL,SQLite]
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
        return f'Error fetching data from database {connection_name}: {str(e)}

# [MONGODB]
def fetch_all_from_xyz(connection_name: str):
    """
    Fetches all records from the 'xyz' collection in the specified MongoDB database using the provided connection name.
    Args:
        connection_name (str): The key used to identify and connect to the specific MongoDB database.
    Returns:
        list: A list of dictionaries, where each dictionary represents a document from the 'xyz' collection.
    """
    from MultiDBConnection_Manager import get_connection_manager
    try:
        manager = get_connection_manager()
        mongo_db = manager.get_mongodb_client(connection_name)
        collection = mongo_db['xyz']
        cursor = collection.find({})
        documents = []
        async for document in cursor:
            documents.append(document)
        return documents
    except Exception as e:
        return f'Error fetching data from MongoDB {connection_name}: {str(e)}

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
          options={{
            readOnly: true,
            domReadOnly: true,
            minimap: { enabled: false },
            scrollBeyondLastLine: false,
            wordWrap: "on",
            lineNumbers: "on",
            folding: false,
            selectOnLineNumbers: false,
            automaticLayout: true,
            fontSize: 14,
            theme: "vs-dark",
            contextmenu: false,
            quickSuggestions: false,
            parameterHints: { enabled: false },
            suggestOnTriggerCharacters: false,
            acceptSuggestionOnCommitCharacter: false,
            tabCompletion: "off",
            wordBasedSuggestions: false
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
