import React, { useState, useEffect } from 'react';
import styles from './ConnectionManagementModal.module.css';
import SVGIcons from '../../Icons/SVGIcons';
import { fetchConnections } from '../../services/databaseService';
import ActiveConnections from '../DataConnectors/ActiveConnections.jsx';
import { useDatabaseConnections } from "./hooks/useDatabaseConnections";
import { useMessage } from "../../Hooks/MessageContext";
import Loader from "../commonComponents/Loader.jsx";
import { useDatabase } from "./context/DatabaseContext";

const ConnectionManagementModal = ({ 
  isOpen, 
  onClose, 
  availableConnections = [], 
  isLoadingConnections = false,
  databaseType // <-- new prop
}) => {
  const [selectedConnection, setSelectedConnection] = useState('');
  const [selectedConnectionData, setSelectedConnectionData] = useState(null);
  const [isDisconnecting, setIsDisconnecting] = useState(false);
  const [isActivating, setIsActivating] = useState(false);
  const { handleConnectOrActivate, handleDisconnect, handleDeactivate } = useDatabaseConnections();
  const { addMessage, setShowPopup } = useMessage();
  const [apiConnections, setApiConnections] = useState([]);
  const [loadingApiConnections, setLoadingApiConnections] = useState(false);
  const [pendingToast, setPendingToast] = useState(null);
  const { activeConnections } = useDatabase();

  // Fetch all available connections from API on mount
  useEffect(() => {
    const fetchAllConnections = async () => {
      setLoadingApiConnections(true);
      try {
        const result = await fetchConnections();
        if (result.success) {
          setApiConnections(result.data.connections || result.data || []);
        } else {
          setApiConnections([]);
        }
      } catch (error) {
        setApiConnections([]);
      } finally {
        setLoadingApiConnections(false);
      }
    };
    fetchAllConnections();
  }, []);

  // Filter connections if databaseType is provided (from API)
  const filteredConnections = databaseType
    ? apiConnections.filter(conn => (conn.connection_database_type || conn.type || '').toLowerCase() === databaseType.toLowerCase())
    : apiConnections;

  useEffect(() => {
    if (selectedConnection && filteredConnections.length > 0) {
      const connectionData = filteredConnections.find(conn => 
        conn.connection_name === selectedConnection || 
        conn.name === selectedConnection ||
        conn.id === selectedConnection || 
        conn.connectionName === selectedConnection
      );
      setSelectedConnectionData(connectionData);
    } else {
      setSelectedConnectionData(null);
    }
  }, [selectedConnection, filteredConnections]);

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

  const handleDisconnectClick = async () => {
    if (selectedConnection && selectedConnectionData) {
      setIsDisconnecting(true);
      try {
        await handleDisconnect(
          selectedConnectionData.connection_name || selectedConnectionData.name || selectedConnectionData.id || selectedConnectionData.connectionName,
          selectedConnectionData.connection_database_type || selectedConnectionData.type || selectedConnectionData.databaseType
        );
        // Remove the disconnected connection from the apiConnections list
        setApiConnections(prev => prev.filter(conn => {
          const name = conn.connection_name || conn.name || conn.id || conn.connectionName;
          return name !== (selectedConnectionData.connection_name || selectedConnectionData.name || selectedConnectionData.id || selectedConnectionData.connectionName);
        }));
        setSelectedConnection("");
        setSelectedConnectionData(null);
        onClose();
      } catch (error) {
        onClose();
        addMessage(`Error disconnecting connection: ${error.message}`, "error");
      } finally {
        setIsDisconnecting(false);
      }
    }
  };

  const handleDeactivateClick = async () => {
    if (selectedConnection && selectedConnectionData) {
      setIsDisconnecting(true);
      try {
        await handleDeactivate(
          selectedConnectionData.connection_name || selectedConnectionData.name || selectedConnectionData.id || selectedConnectionData.connectionName,
          selectedConnectionData.connection_database_type || selectedConnectionData.type || selectedConnectionData.databaseType
        );
        setSelectedConnection("");
        setSelectedConnectionData(null);
        onClose();
      } catch (error) {
        console.error('Deactivate error:', error);
        onClose();
      } finally {
        setIsDisconnecting(false);
      }
    }
  };

  const handleActivate = async () => {
    if (selectedConnection && selectedConnectionData) {
      setIsActivating(true);
      try {
        await handleConnectOrActivate(selectedConnectionData, "0");
        setSelectedConnection("");
        setSelectedConnectionData(null);
        onClose();
        addMessage("Database connection activated successfully!", "success");
      } catch (error) {
        onClose();
        addMessage(`Error activating connection: ${error.message}`, "error");
      } finally {
        setIsActivating(false);
      }
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
     {( isLoadingConnections || isActivating || isDisconnecting || loadingApiConnections) && <Loader />}
        <div className={styles.modalHeader}>
          <h2 className={styles.modalTitle}>Manage Database Connections {databaseType ? `- ${databaseType}` : ''}</h2>
          <button className={styles.closeButton} onClick={onClose}>
            <SVGIcons icon="close" width={24} height={24} fill="#666" />
          </button>
        </div>

        {/* Show active connections inside the modal, filtered for databaseType */}
        <div style={{marginBottom: '1rem'}}>
          <ActiveConnections databaseType={databaseType} />
        </div>

        <div className={styles.modalBody}>
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
                {filteredConnections && filteredConnections.length > 0 && filteredConnections.map((connection, index) => {
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
                onClick={handleDisconnectClick}
                disabled={!selectedConnection || isDisconnecting}
              >
                    <SVGIcons icon="fa-trash" width={16} height={16} fill="white" />
                    Disconnect
              </button>
              <button
                className={`${styles.activateButton} ${!selectedConnection ? styles.disabled : ''}`}
                onClick={handleActivate}
                disabled={!selectedConnection || isActivating}
              >
                <SVGIcons icon="check" width={16} height={16} fill="white" />
                    Activate
              </button>

              <button
                className={`${styles.disconnectButton} ${!selectedConnection ? styles.disabled : ''}`}
                onClick={handleDeactivateClick}
                disabled={!selectedConnection || isDisconnecting}
              >
                    <SVGIcons icon="close" width={16} height={16} fill="white" />
                    Deactivate
              </button>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
};

export default ConnectionManagementModal;
