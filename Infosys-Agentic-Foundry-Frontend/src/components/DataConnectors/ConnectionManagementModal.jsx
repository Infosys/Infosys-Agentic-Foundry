import React, { useState, useEffect } from 'react';
import styles from './ConnectionManagementModal.module.css';
import SVGIcons from '../../Icons/SVGIcons';
import { activateDatabase } from '../../services/databaseService';
import ActiveConnections from '../DataConnectors/ActiveConnections.jsx';
import { useDatabaseConnections } from "./hooks/useDatabaseConnections";
import { useMessage } from "../../Hooks/MessageContext";
import Loader from "../commonComponents/Loader.jsx";

const ConnectionManagementModal = ({ 
  isOpen, 
  onClose, 
  availableConnections = [], 
  isLoadingConnections = false,
  onDisconnect,
  onActivate
}) => {
  const [selectedConnection, setSelectedConnection] = useState('');
  const [selectedConnectionData, setSelectedConnectionData] = useState(null);
  const [isDisconnecting, setIsDisconnecting] = useState(false);
  const [isActivating, setIsActivating] = useState(false);
  const [disconnectMessage, setDisconnectMessage] = useState("");
  const { updateConnectionsImmediate, handleDisconnect: hookHandleDisconnect } = useDatabaseConnections();
  const { addMessage, setShowPopup } = useMessage();

  // Debug: Log availableConnections to see the data structure
  useEffect(() => {
    console.log('Available connections:', availableConnections);
    console.log('Available connections length:', availableConnections.length);
    
    // Log the structure of the first connection to understand the data format
    if (availableConnections.length > 0) {
      console.log('First connection structure:', availableConnections[0]);
      console.log('First connection keys:', Object.keys(availableConnections[0]));
    }
  }, [availableConnections]);

  useEffect(() => {
    if (selectedConnection && availableConnections.length > 0) {
      // Try to find connection by different possible identifiers
      const connectionData = availableConnections.find(conn => 
        conn.connection_name === selectedConnection || 
        conn.name === selectedConnection ||
        conn.id === selectedConnection || 
        conn.connectionName === selectedConnection
      );
      console.log('Selected connection data:', connectionData);
      setSelectedConnectionData(connectionData);
    } else {
      setSelectedConnectionData(null);
    }
  }, [selectedConnection, availableConnections]);

  const handleConnectionSelect = (connectionId) => {
    // Find the full connection object
    const connectionObj = availableConnections.find(conn =>
      conn.connection_name === connectionId ||
      conn.name === connectionId ||
      conn.id === connectionId ||
      conn.connectionName === connectionId
    );
    setSelectedConnection(connectionId);
    setSelectedConnectionData(connectionObj || null);
  };

  const handleDisconnect = async () => {
    if (selectedConnection && selectedConnectionData) {
      setIsDisconnecting(true);
      try {
        await hookHandleDisconnect(
          selectedConnectionData.connection_name || selectedConnectionData.name || selectedConnection,
          selectedConnectionData.connection_database_type || selectedConnectionData.databaseType || selectedConnectionData.db_type || selectedConnectionData.type
        );
        setSelectedConnection('');
        setSelectedConnectionData(null);
        onClose();
        addMessage("Disconnected successfully!", "success");
      } catch (error) {
        console.error('Disconnect error:', error);
        onClose();
        addMessage(`Error disconnecting connection: ${error.message}`, "error");
      } finally {
        setIsDisconnecting(false);
      }
    }
  };

  const handleActivate = async () => {
    if (selectedConnection && selectedConnectionData) {
      setIsActivating(true);
      try {
        if (onActivate) {
          await onActivate(selectedConnectionData);
          onClose();
          addMessage('Database connection activated successfully!', 'success');
        } else {
          const result = await activateDatabase(selectedConnection, selectedConnectionData);
          if (result.success) {
            onClose();
            addMessage('Database connection activated successfully!', 'success');
          } else {
            onClose();
            addMessage(`Failed to activate connection: ${result.error}`, 'error');
          }
        }
      } catch (error) {
        onClose();
        addMessage(`Error activating connection: ${error.message}`, 'error');
      } finally {
        setIsActivating(false);
      }
    } else {
      console.log('Activate - Missing data:', { selectedConnection, selectedConnectionData });
    }
  };

  useEffect(() => {
    if (!isLoadingConnections) {
      setShowPopup(true);
    } else {
      setShowPopup(false);
    }
  }, [isLoadingConnections, setShowPopup]);

  if (!isOpen) return null;

  return (
    <div className={styles.modalOverlay} onClick={onClose}>
      <div className={styles.modalContent} onClick={(e) => e.stopPropagation()}>
        {isLoadingConnections && <Loader />}
        <div className={styles.modalHeader}>
          <h2 className={styles.modalTitle}>Manage Database Connections</h2>
          <button className={styles.closeButton} onClick={onClose}>
            <SVGIcons icon="close" width={24} height={24} fill="#666" />
          </button>
        </div>

        {/* Show active connections inside the modal */}
        <div style={{marginBottom: '1rem'}}>
          <ActiveConnections />
        </div>

        <div className={styles.modalBody}>
          {disconnectMessage && (
            <div style={{color: disconnectMessage.startsWith('Error') ? 'red' : 'green', marginBottom: '1rem'}}>
              {disconnectMessage}
            </div>
          )}
          <div className={styles.formSection}>
            <h3 className={styles.sectionTitle}>Manage Existing Connections</h3>
            
            <div className={styles.dropdownContainer}>
              <label className={styles.dropdownLabel}>Select Connection:</label>
              <select
                className={styles.connectionDropdown}
                value={selectedConnection}
                onChange={(e) => handleConnectionSelect(e.target.value)}
                disabled={isLoadingConnections}
              >
                <option value="">
                  {isLoadingConnections ? 'Loading connections...' : 'Select a connection'}
                </option>
                {availableConnections && availableConnections.length > 0 && availableConnections.map((connection, index) => {
                  const connectionId = connection.connection_name || connection.name || connection.id || connection.connectionName || `connection-${index}`;
                  const connectionName = connection.connection_name || connection.name || connection.connectionName || connection.title || `Connection ${index + 1}`;
                  return (
                    <option key={connectionId} value={connectionId}>
                      {connectionName}
                    </option>
                  );
                })}
              </select>
            </div>
            
            <div className={styles.buttonGroup}>
              <button
                className={`${styles.disconnectButton} ${!selectedConnection ? styles.disabled : ''}`}
                onClick={handleDisconnect}
                disabled={!selectedConnection || isDisconnecting}
              >
                {isDisconnecting ? (
                  <>
                    <SVGIcons icon="loading" width={16} height={16} fill="white" />
                    Disconnecting...
                  </>
                ) : (
                  <>
                    <SVGIcons icon="close" width={16} height={16} fill="white" />
                    Disconnect
                  </>
                )}
              </button>
              
              <button
                className={`${styles.activateButton} ${!selectedConnection ? styles.disabled : ''}`}
                onClick={handleActivate}
                disabled={!selectedConnection || isActivating}
              >
                {isActivating ? (
                  <>
                    <SVGIcons icon="loading" width={16} height={16} fill="white" />
                    Activating...
                  </>
                ) : (
                  <>
                    <SVGIcons icon="plug" width={16} height={16} fill="white" />
                    Activate
                  </>
                )}
              </button>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
};

export default ConnectionManagementModal;
