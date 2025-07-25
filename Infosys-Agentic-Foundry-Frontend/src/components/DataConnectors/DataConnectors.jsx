import React, { useState, useMemo } from "react";
import styles from "./DataConnectors.module.css";
import ConnectionModal from "./ConnectionModal";
import QueryModal from "./QueryModal";
import CrudModal from "./CrudModal";
import ConnectionManagementModal from "./ConnectionManagementModal";
import SVGIcons from "../../Icons/SVGIcons";
import { useDatabaseConnections } from "./hooks/useDatabaseConnections";
import { DatabaseProvider } from "./context/DatabaseContext";

const DataConnectorsContent = () => {
  const [searchTerm, setSearchTerm] = useState("");
  const [showConnectionModal, setShowConnectionModal] = useState(false);
  const [showQueryModal, setShowQueryModal] = useState(false);
  const [showCrudModal, setShowCrudModal] = useState(false);
  const [showManagementModal, setShowManagementModal] = useState(false);
  const [selectedDatabase, setSelectedDatabase] = useState(null);
  const [isExecuting, setIsExecuting] = useState(false);
  const [isCrudExecuting, setIsCrudExecuting] = useState(false);

  // Use the database connections hook
  const { 
    handleConnectionSubmit, 
    isConnecting, 
    availableConnections, 
    isLoadingConnections,
    handleDisconnect: hookHandleDisconnect,
    handleActivateConnection: hookHandleActivateConnection,
    isDisConnecting,
    isActivating
  } = useDatabaseConnections();

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
        { name: 'host', label: 'Host', type: 'text', required: true },
        { name: 'port', label: 'Port', type: 'number', required: true },
        { name: 'databaseName', label: 'Database Path', type: 'text', required: true },
        { name: 'username', label: 'Username', type: 'text', required: true },
        { name: 'password', label: 'Password', type: 'password', required: true}
      ]
    },
  ];

  // Filter database types based on search term
  const filteredDatabases = useMemo(() => 
    databaseTypes.filter(db =>
      db.name.toLowerCase().includes(searchTerm.toLowerCase()) ||
      db.description.toLowerCase().includes(searchTerm.toLowerCase())
    ), [searchTerm]
  );

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
    event.stopPropagation(); // Prevent card click event
    setShowManagementModal(true);
  };

  const handleCloseModal = () => {
    setShowConnectionModal(false);
    setShowQueryModal(false);
    setShowCrudModal(false);
    setShowManagementModal(false);
    setSelectedDatabase(null);
  };

  const handleRunQuery = async (queryData) => {
    setIsExecuting(true);
    try {
      // Add your query execution logic here
      console.log("Running query:", queryData);
      // Mock execution time
      await new Promise(resolve => setTimeout(resolve, 2000));
    } catch (error) {
      console.error("Query execution error:", error);
    } finally {
      setIsExecuting(false);
    }
  };

  const handleExecuteCrud = async (crudData) => {
    setIsCrudExecuting(true);
    try {
      // Add your CRUD execution logic here
      console.log("Executing CRUD operation:", crudData);
      
      // Mock execution time and result
      await new Promise(resolve => setTimeout(resolve, 2000));
      
      // Mock result based on operation
      let mockResult;
      switch (crudData.operation) {
        case 'find':
          mockResult = { success: true, data: [{ _id: "1", name: "John", email: "john@example.com" }] };
          break;
        case 'insert':
          mockResult = { success: true, insertedId: "60f7b4e8d4f8a84b2c1e3f5a" };
          break;
        case 'update':
          mockResult = { success: true, modifiedCount: 1 };
          break;
        case 'delete':
          mockResult = { success: true, deletedCount: 1 };
          break;
        default:
          mockResult = { success: true, message: "Operation completed" };
      }
      
      return mockResult;
    } catch (error) {
      console.error("CRUD execution error:", error);
      throw error;
    } finally {
      setIsCrudExecuting(false);
    }
  };

  const handleSearchChange = (value) => {
    setSearchTerm(value);
  };

  return (
    <div className={styles.container}>
      {/* Header */}
      <div className={styles.header} style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
        <h1 className={styles.title}>Data Connectors</h1>
        <button
          className={styles.manageButton}
          onClick={() => setShowManagementModal(true)}
        >
          
          Manage
        </button>
      </div>

      {/* Database Cards */}
      <div className={styles.cardsContainer}>
        {filteredDatabases.filter(db => !db.isManagement).length > 0 ? (
          filteredDatabases.filter(db => !db.isManagement).map((database) => {
            const isDisabled = database.id === 'mysql' || database.id === 'mongodb';
            // Count connections for this database type
            const connectionCount = availableConnections.filter(conn => {
              // Normalize type for comparison
              const dbType = (conn.connection_database_type || conn.type || '').toLowerCase();
              const expectedType = (database.name || '').toLowerCase();
              return dbType === expectedType;
            }).length;
            return (
            <div
              key={database.id}
              className={styles.databaseCard + (isDisabled ? ' ' + styles.disabledCard : '')}
              onClick={() => !isDisabled && handleCardClick(database)}
              style={{ cursor: isDisabled ? 'not-allowed' : 'pointer', opacity: isDisabled ? 0.5 : 1 }}
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
                      {connectionCount} connection{connectionCount !== 1 ? 's' : ''}
                    </span>
                  </div>
                </div>
              </div>
              <p className={styles.cardDescription}>{database.description}</p>
              <div className={styles.cardFooter}>
                <div className={styles.cardButtons}>
                  {/* Run button: Show for all databases except MongoDB */}
                  {database.id !== 'mongodb' && (
                    <button
                      className={styles.runButton}
                      onClick={(e) => handleRunClick(database, e)}
                      disabled={isDisabled}
                    >
                      Run
                    </button>
                  )}
                  {/* CRUD button: Show only for MongoDB */}
                  {database.id === 'mongodb' && (
                    <button
                      className={styles.crudButton}
                      onClick={(e) => handleCrudClick(database, e)}
                      disabled={isDisabled}
                    >
                      CRUD
                    </button>
                  )}
                </div>
              </div>
            </div>
            );
          })
        ) : (
          <div className={styles.noResults}>
            <SVGIcons
              icon="search"
              width={48}
              height={48}
              fill="#ccc"
            />
            <p>No database types found matching "{searchTerm}"</p>
          </div>
        )}
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
          availableConnections={availableConnections}
          isLoadingConnections={isLoadingConnections}
          onDisconnect={hookHandleDisconnect}
          onActivate={hookHandleActivateConnection}
          isDisConnecting={isDisConnecting}
          isActivating={isActivating}
        />
      )}
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
